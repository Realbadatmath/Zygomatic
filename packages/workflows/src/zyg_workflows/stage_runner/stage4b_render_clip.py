# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The stages behind Stage 4b's per-clip renderer.

`_make_render_clip` was a 324-line closure factory: one `_build_srt` closure,
one `_fmt` closure inside it, and a 247-line `_render_clip` reading fourteen
names out of `_stage_preflight`'s scope. Those fourteen names are
`RenderClipJob` here, built once by the factory and carried into the renderer;
everything the renderer does between its log lines is a function below, in the
same order, with the same strings and the same side effects.

The pure ones — `srt_cue_lines`, `clip_title_source`, `clip_filters`,
`nvenc_cmd`, `cpu_cmd` — were all closure or inline code before, so the unit
tests beside this module are the first time any of them ran on their own.

Import direction: this module imports nothing from `stage4b_render` — the
renderer imports from here. It is deliberately NOT in `stage_runner.__init__`'s
`_SECTIONS` write-through tuple, like its `stage4b_phases` /
`stage4b_scoring` / `stage4b_models_director` siblings: nothing monkeypatches a
name it holds through the package.
"""

import json
import logging as _zyg_logging
import os
import re
from dataclasses import dataclass

from zyg_workflows.bin import exe
from zyg_workflows.runtime import _NVENC_SEM
from zyg_workflows.subproc_registry import _finish_subproc
from zyg_workflows.subproc_registry import _register_subproc
from zyg_workflows.subproc_registry import _update_marker
from zyg_workflows.tts_service import _mask_bad_words

_zyg_log = _zyg_logging.getLogger('zyg_workflows.stage_runner')


@dataclass(frozen=True)
class RenderClipJob:
    """The Stage 4b frame the renderer used to read out of its enclosing scope.

    Four callables from `preflight` (the duration/boundary helpers and the
    post-processor), three log channels, three lookup tables keyed by video id,
    the output root, the pipeline id, and the shared `processed` list with the
    lock that guards it.
    """

    get_natural_clip_duration: object
    log_err: object
    log_info: object
    log_warn: object
    narrator_lines: dict
    post_process_clip: object
    queued_markers: dict
    snap_to_sentence_start: object
    vid_channel_map: dict
    vid_meta_titles: dict
    out_dir: str
    pipeline_id: object
    processed: list
    processed_lock: object


def _srt_timestamp(t) -> str:
    """One SRT clock reading: `HH:MM:SS,mmm` from a float number of seconds."""
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t % 1) * 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def srt_cue_lines(segs, clip_start_: float, clip_dur_: float) -> list:
    """The numbered SRT cues for the window `[clip_start_, clip_start_ + clip_dur_]`.

    In: the transcript's `segments` list (`start`, `end`, `text`) and the clip
    window. Out: one `'<n>\\n<from> --> <to>\\n<text>\\n'` string per non-empty
    segment that overlaps the window, timed relative to the clip start, with the
    text passed through `_mask_bad_words`. Empty when nothing overlaps.

    Each cue is held 0.8 s longer than the segment for readability, but never
    past 0.05 s before the next cue's start and never shorter than 0.3 s.
    """
    clip_end_ = clip_start_ + clip_dur_
    lines = []
    idx = 1
    segs_in_clip = []
    for seg in segs:
        s_start = float(seg.get('start', 0))
        s_end = float(seg.get('end', s_start + 1))
        if s_end < clip_start_ or s_start > clip_end_:
            continue
        segs_in_clip.append((s_start, s_end, seg.get('text', '').strip()))

    for ci, (s_start, s_end, text) in enumerate(segs_in_clip):
        if not text:
            continue
        rel_start = max(0.0, s_start - clip_start_)
        rel_end = max(rel_start + 0.1, s_end - clip_start_)
        # Extend end by 0.8s for readability, but never past the next segment's start
        hold = 0.8
        if ci + 1 < len(segs_in_clip):
            next_rel_start = max(0.0, segs_in_clip[ci + 1][0] - clip_start_)
            rel_end = min(rel_end + hold, next_rel_start - 0.05)
        else:
            rel_end = rel_end + hold
        rel_end = max(rel_end, rel_start + 0.3)

        lines.append(f'{idx}\n{_srt_timestamp(rel_start)} --> {_srt_timestamp(rel_end)}\n{_mask_bad_words(text)}\n')
        idx += 1
    return lines


def build_srt(tx_path_: str, clip_start_: float, clip_dur_: float) -> str | None:
    """Generate a temp .srt file for the clip window. Returns path or None.

    None when there is no transcript, when it will not parse, when no segment
    falls in the window, or when the .srt cannot be written.
    """
    if not tx_path_ or not os.path.exists(tx_path_):
        return None
    try:
        with open(tx_path_) as _f:
            segs = json.load(_f).get('segments', [])
    except Exception:
        return None
    lines = srt_cue_lines(segs, clip_start_, clip_dur_)
    if not lines:
        return None
    srt_path = tx_path_.replace('.json', f'_clip{clip_start_:.0f}.srt')
    try:
        with open(srt_path, 'w', encoding='utf-8') as _sf:
            _sf.write('\n'.join(lines))
        return srt_path
    except Exception:
        return None


def clip_title_source(clip_title, channel: str, meta_title: str, index: int) -> str:
    """The title the clip's filename and upload are built from.

    Priority: GPT-4o/director title → YouTube video title → channel+clip index
    fallback (`'<channel> clip <n>'`, or `'clip_<n>'` with no channel).
    """
    _title_src = clip_title or ''
    if not _title_src:
        _title_src = meta_title
    if not _title_src:
        _title_src = f'{channel} clip {index + 1}' if channel else f'clip_{index + 1}'
    return _title_src


def clip_output_path(out_dir: str, clean_title: str, index: int) -> str:
    """`out_dir/<filesystem-safe title>.mp4`, suffixed with the clip number on a clash.

    Sanitize to filesystem-safe characters, preserve spaces as underscores, and
    cap the stem at 80 characters.
    """
    _safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', clean_title).strip()
    _safe_name = re.sub(r'\s+', '_', _safe_name)[:80]
    final_path = os.path.join(out_dir, f'{_safe_name}.mp4')
    # If exact name already exists add a suffix to avoid collisions
    if os.path.exists(final_path):
        final_path = os.path.join(out_dir, f'{_safe_name}_{index + 1}.mp4')
    return final_path


def clip_filters(clip_dur: float) -> tuple:
    """(video filter chain, audio filter chain) for one clip.

    1920x1080 letterboxed at 30 fps, plus a 0.5 s fade-in at t=0 and a 0.5 s
    fade-out at the end — video and audio.
    """
    _vf_base = 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30'
    # 0.5s fade-in at t=0, 0.5s fade-out at end — video and audio
    _fade_v = f'fade=t=in:st=0:d=0.5,fade=t=out:st={clip_dur - 0.5:.3f}:d=0.5'
    _af = f'afade=t=in:st=0:d=0.5,afade=t=out:st={clip_dur - 0.5:.3f}:d=0.5'
    return ','.join([_vf_base, _fade_v]), _af


def ffmpeg_taskset() -> list:
    """The taskset prefix ffmpeg runs behind — the shared core ceiling.

    taskset pins ffmpeg to the shared core ceiling (was 0-20, one over); the
    fallback is the literal `0-19` the cap module would have returned.
    """
    try:
        from zyg_workflows import cpu_cap as _cpu_cap_ff

        return _cpu_cap_ff.taskset_prefix()
    except Exception:
        return ['taskset', '-c', '0-19']


def _clip_io_args(taskset: list, start, vid_path: str, clip_dur, vf: str, af: str) -> list:
    """The half of either ffmpeg command that does not depend on the encoder."""
    return taskset + [
        exe('ffmpeg'),
        '-y',
        '-ss',
        str(start),
        '-i',
        vid_path,
        '-t',
        str(clip_dur),
        '-vf',
        vf,
        '-af',
        af,
    ]


def nvenc_cmd(taskset: list, start, vid_path: str, clip_dur, vf: str, af: str, final_path: str) -> list:
    """The h264_nvenc command line for one clip: VBR, cq 24, one thread, AAC 192k."""
    return _clip_io_args(taskset, start, vid_path, clip_dur, vf, af) + [
        '-c:v',
        'h264_nvenc',
        '-preset',
        'p4',
        '-rc',
        'vbr',
        '-cq',
        '24',
        '-b:v',
        '0',
        '-c:a',
        'aac',
        '-b:a',
        '192k',
        '-threads',
        '1',
        final_path,
    ]


def cpu_cmd(taskset: list, start, vid_path: str, clip_dur, vf: str, af: str, final_path: str) -> list:
    """The libx264 fallback command line for one clip: veryfast, crf 23, two threads."""
    return _clip_io_args(taskset, start, vid_path, clip_dur, vf, af) + [
        '-c:v',
        'libx264',
        '-preset',
        'veryfast',
        '-crf',
        '23',
        '-c:a',
        'aac',
        '-b:a',
        '192k',
        '-threads',
        '2',
        final_path,
    ]


def render_nvenc(cmd: list, label: str, pipeline_id, queued_pid) -> None:
    """Run the NVENC leg under the NVENC semaphore, registering the process.

    Flips the queued placeholder marker to done as soon as the real pid is
    known — the real PID entry takes over — and raises RuntimeError with the
    last 300 bytes of ffmpeg's stderr on a non-zero exit, which is what sends
    the renderer down the CPU fallback.
    """
    import subprocess as _sp

    with _NVENC_SEM:  # max 4 concurrent NVENC sessions (RTX consumer limit = 5)
        _proc = _sp.Popen(cmd, stdout=_sp.PIPE, stderr=_sp.PIPE)
        _register_subproc(_proc.pid, label, pipeline_id)
        # Also mark the queued placeholder as done — real PID entry takes over
        if queued_pid is not None:
            _update_marker(queued_pid, status='done', label=f'✅ {label} (ffmpeg pid {_proc.pid})')
        _stdout, _stderr = _proc.communicate(timeout=600)
        _finish_subproc(_proc.pid, ok=(_proc.returncode == 0))
        if _proc.returncode != 0:
            raise RuntimeError(_stderr.decode(errors='replace')[-300:])


def render_cpu(cmd: list, label: str, pipeline_id) -> None:
    """Run the libx264 fallback leg, registered under `<label> [cpu-fallback]`."""
    import subprocess as _sp2

    _proc2 = _sp2.Popen(cmd, stdout=_sp2.PIPE, stderr=_sp2.PIPE)
    _register_subproc(_proc2.pid, f'{label} [cpu-fallback]', pipeline_id)
    _proc2.communicate(timeout=600)
    _finish_subproc(_proc2.pid, ok=(_proc2.returncode == 0))


def drop_file(path: str, note: str) -> None:
    """Unlink `path`, logging at debug and carrying on when the unlink fails."""
    try:
        os.remove(path)
    except OSError as _exc:
        _zyg_log.debug('%s %s cleanup skipped: %s', note, path, _exc)


def drop_temp_srt(srt_path) -> None:
    """Remove the clip's temp .srt, if one was made and is still on disk."""
    if srt_path and os.path.exists(srt_path):
        drop_file(srt_path, 'temp srt')


def rendered_duration(final_path: str) -> float:
    """The clip's real duration per ffprobe, or 999 when the probe fails.

    999 reads as "long enough" on purpose: a failed probe must not throw away a
    file that may be fine.
    """
    try:
        import subprocess as _sp_chk

        _dur_r = _sp_chk.run(
            [exe('ffprobe'), '-v', 'quiet', '-print_format', 'json', '-show_format', final_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return float(json.loads(_dur_r.stdout).get('format', {}).get('duration', 999))
    except Exception:
        return 999


def probe_streams(final_path: str) -> tuple:
    """([video streams], [audio streams]) of the rendered clip, per two ffprobe calls.

    Raises whatever ffprobe or the JSON parse raises — the caller reports that
    as "could not probe" and goes on, because a probe that fails is not proof
    the file is broken.
    """
    import subprocess as _sp_probe

    _probe = _sp_probe.run(
        [
            exe('ffprobe'),
            '-v',
            'error',
            '-select_streams',
            'v:0',
            '-show_entries',
            'stream=codec_type,width,height',
            '-of',
            'json',
            final_path,
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    _probe_data = json.loads(_probe.stdout)
    _vstreams = _probe_data.get('streams', [])
    _probe_a = _sp_probe.run(
        [
            exe('ffprobe'),
            '-v',
            'error',
            '-select_streams',
            'a:0',
            '-show_entries',
            'stream=codec_type',
            '-of',
            'json',
            final_path,
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    _astreams = json.loads(_probe_a.stdout).get('streams', [])
    return _vstreams, _astreams
