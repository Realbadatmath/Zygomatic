# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 4b Phase B: the SRT builder and the per-clip nvenc/CPU renderer.

2026-10-09: `_make_render_clip` was 324 lines, over the 300-line cap. Its
stages — the SRT builder, the file naming, the filter chains, the two ffmpeg
command lines, the two render legs and the two post-render probes — are
`stage4b_render_clip`, and the fourteen names its `_render_clip` closure read
out of `_stage_preflight`'s scope are that module's `RenderClipJob`. The
factory now just builds the job and binds it; the renderer is module level, so
each of its stages is reachable from a test.
"""

import functools
import os
from zyg_workflows.subproc_registry import _update_marker
from zyg_workflows.tts_service import _sanitize_title
from zyg_workflows import gui_state
from zyg_workflows.stage_runner import stage4b_render_clip as _rc

# Never defined at module scope in crewai_web_gui.py either, so the ``getattr``
# this replaces always yielded None, and both uses below are guarded by it.
_srt_path = None


def _make_render_clip(
    _get_natural_clip_duration,
    _log_err,
    _log_info,
    _log_warn,
    _narrator_lines,
    _post_process_clip,
    _queued_markers,
    _snap_to_sentence_start,
    _vid_channel_map,
    _vid_meta_titles,
    out_dir,
    pipeline_id,
    processed,
    processed_lock,
):
    """Build Stage 4b's clip renderer.

    Returns `_render_clip` bound to the `RenderClipJob` holding exactly the
    fourteen names the old closure read out of `_stage_preflight`'s scope, so
    the single call site (`stage4b._pf_stage_4b`) keeps its signature and the
    returned callable still takes one packed `args` tuple.
    """
    return functools.partial(
        _render_clip,
        _rc.RenderClipJob(
            get_natural_clip_duration=_get_natural_clip_duration,
            log_err=_log_err,
            log_info=_log_info,
            log_warn=_log_warn,
            narrator_lines=_narrator_lines,
            post_process_clip=_post_process_clip,
            queued_markers=_queued_markers,
            snap_to_sentence_start=_snap_to_sentence_start,
            vid_channel_map=_vid_channel_map,
            vid_meta_titles=_vid_meta_titles,
            out_dir=out_dir,
            pipeline_id=pipeline_id,
            processed=processed,
            processed_lock=processed_lock,
        ),
    )


def _render_clip(job, args):
    """Render one clip of one video, then hand it to the post-processor.

    `args` is the packed job tuple Phase B builds: `(vid_id, vid_path, tx_path,
    i, ts, clip_title, sfx_plan, react_plan, intro)`. Returns early — drawing
    nothing — when the user has stopped the pipeline, when the source has less
    than 480 s left after the snapped start, when the render produced a clip
    under 480 s, or when the result has no video stream at all.
    """
    vid_id, vid_path, tx_path, i, ts, clip_title, sfx_plan, react_plan, intro = args
    _log_err, _log_info, _log_warn = job.log_err, job.log_info, job.log_warn
    # Check stop flag before starting any work for this clip
    if gui_state._pipeline_stop_flag:
        _log_info(f'Stage 4b: render {vid_id} clip{i + 1} — stopped by user, skipping')
        return
    _start = max(0.0, float(ts))
    # Snap start to nearest sentence boundary so clip doesn't begin mid-sentence
    _start = job.snap_to_sentence_start(tx_path, _start, window=8.0)
    _clip_dur = job.get_natural_clip_duration(tx_path, _start, min_dur=480.0, max_dur=900.0)
    # Hard-skip clips shorter than 480s (8 min) — means timestamp was near end of video
    if _clip_dur < 480.0:
        _log_info(f'Stage 4b: skipping {vid_id} clip{i + 1} — only {_clip_dur:.0f}s available (need ≥480s)')
        return
    # ── File naming: use clip title as the upload-ready filename ──
    _title_src = _rc.clip_title_source(
        clip_title, job.vid_channel_map.get(vid_id, ''), job.vid_meta_titles.get(vid_id, ''), i
    )
    # Sanitize bad words from title before it becomes the filename/upload title
    _clean_title = _sanitize_title(_title_src)
    if _clean_title != _title_src:
        _log_warn(
            f'Stage 4b naming {vid_id} clip{i + 1}: title sanitized for YT policy '
            f'("{_title_src[:60]}" → "{_clean_title[:60]}")'
        )
    final_path = _rc.clip_output_path(job.out_dir, _clean_title, i)
    _label = f'render {vid_id} clip{i + 1}' + (f' — {clip_title or _title_src}' if (clip_title or _title_src) else '')
    # Flip the queued marker to 'running' now that this slot has started
    _q_pid = job.queued_markers.get((vid_id, i))
    if _q_pid is not None:
        _update_marker(_q_pid, status='running', label=f'▶ {_label}')
    # Generate subtitle SRT for this clip window (saved to disk; not burned in)
    _rc.build_srt(tx_path, _start, _clip_dur)
    _vf, _af = _rc.clip_filters(_clip_dur)
    _taskset = _rc.ffmpeg_taskset()
    try:
        _rc.render_nvenc(
            _rc.nvenc_cmd(_taskset, _start, vid_path, _clip_dur, _vf, _af, final_path),
            _label,
            job.pipeline_id,
            _q_pid,
        )
        # Clean up temp SRT after successful GPU render
        _rc.drop_temp_srt(_srt_path)
    except Exception as _ge:
        _log_err(f'Stage 4b nvenc {vid_id} clip{i + 1}', f'GPU failed, using CPU: {_ge}')
        try:
            _rc.render_cpu(
                _rc.cpu_cmd(_taskset, _start, vid_path, _clip_dur, _vf, _af, final_path),
                _label,
                job.pipeline_id,
            )
            # Clean up temp SRT after CPU fallback
            _rc.drop_temp_srt(_srt_path)
        except Exception as _ce:
            _log_err(f'Stage 4b cpu render {vid_id} clip{i + 1}', str(_ce))
    if os.path.exists(final_path) and os.path.getsize(final_path) > 0:
        # Check actual rendered duration — skip clips under 45s (GPT picked near end of video)
        _actual_dur = _rc.rendered_duration(final_path)
        if _actual_dur < 480.0:
            _log_warn(
                f'Stage 4b: skipping {vid_id} clip{i + 1} — rendered only {_actual_dur:.0f}s (too short, need ≥8min)'
            )
            _rc.drop_file(final_path, 'rejected clip')
        else:
            # ── Stream integrity check before post-processing ────────
            try:
                _vstreams, _astreams = _rc.probe_streams(final_path)
                if not _vstreams:
                    _log_warn(f'Stage 4b QA: ⚠ {vid_id} clip{i + 1} has NO video stream — file is broken, skipping.')
                    _rc.drop_file(final_path, 'rejected clip')
                    return
                if not _astreams:
                    _log_warn(f'Stage 4b QA: ⚠ {vid_id} clip{i + 1} has NO audio stream — clip will be silent.')
            except Exception as _probe_e:
                _log_warn(f'Stage 4b QA: could not probe {vid_id} clip{i + 1} streams ({_probe_e})')

            job.post_process_clip(
                final_path,
                vid_id,
                _start,
                _clip_dur,
                tx_path,
                i + 1,
                clip_title,
                narrator_line_=job.narrator_lines.get((vid_id, i), ''),
                sfx_plan_=sfx_plan,
                react_plan_=react_plan,
            )
            with job.processed_lock:
                job.processed.append({'video_id': vid_id, 'clip_index': i + 1, 'path': final_path, 'source_ts': ts})
