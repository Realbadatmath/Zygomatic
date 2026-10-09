# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).
import os

from zyg_workflows.encode_utils import _cq_for_crf, _ffmpeg_run_nvenc_first, _nvenc_vcodec_args, _x264_vcodec_args
from zyg_workflows.pipeline_common import _align_narration_word_timings
from zyg_workflows import provenance_seal as _seal  # noqa: F401  the egress test asserts this binding
from zyg_workflows.vram_manager import (
    _release_pipeline_vram,
)
from zyg_workflows.pipeline_config import (
    _BOOK_FONT,
    _BOOK_PNG,
)
from zyg_workflows.runtime import (
    _ams_iso,
    _GPU_PIPELINE_LOCK,
    _push_error_log,
    _runtime_path,
    workflow_jobs as _workflow_jobs,
)
from zyg_workflows.bin import exe
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# Never defined at module scope in crewai_web_gui.py either, so the ``getattr``
# this replaces always yielded None. Kept at None so behaviour is unchanged.
tts_duration = None


def _run_video_pipeline(
    pipeline_id: str,
    directive: str,
    image_paths: list = None,
    video_duration_minutes: float = 0.5,
    narration_enabled: bool = False,
    visual_style: str = 'cinematic',
    scene_mode: str = 'independent',
    ending_text: str = '',
):
    """
    Video pipeline: still images → 8+ minute video with TTS narration.

    Stages:
      1. Scene Planning   — Claude generates 24 scene descriptions + narration sentences
      2. Image Prep       — Use uploaded images; FLUX-generate any missing scenes
      3. TTS Narration    — IndexTTS-2 → per-scene audio segments
      4. AI Image Generation (re-uses stage 3.5 card)  — tracks FLUX runs
      5. Video Generation — WAN I2V clip per scene (animates FLUX image, looped to TTS duration) + subtitle burn
      6. Video Assembly   — ffmpeg concat → final MP4
    """
    import subprocess as _sp_video

    job = _workflow_jobs.get(pipeline_id)
    if not job:
        return

    _manga_mode = job.get('department') == 'manga'
    if _manga_mode:
        visual_style = 'manga'

    image_paths = image_paths or []

    _dir_prefix = 'manga_pipeline_' if _manga_mode else 'video_pipeline_'
    out_dir = _runtime_path(f'{_dir_prefix}{pipeline_id[:12]}')
    os.makedirs(out_dir, exist_ok=True)
    job['output_dir'] = out_dir

    def _log(level, stage, msg):
        from zoneinfo import ZoneInfo as _ZI

        _ams = _ZI('Europe/Amsterdam')
        ts = _ams_iso()
        ev = {'ts': ts, 'level': level, 'stage': stage, 'msg': msg}
        job.setdefault('debug_events', []).append(ev)
        if len(job['debug_events']) > 500:
            job['debug_events'] = job['debug_events'][-300:]
        _pipe_tag = 'MANGA-PIPELINE' if _manga_mode else 'VIDEO-PIPELINE'
        _zyg_log.info(f'[{_pipe_tag}][{level}][{stage}] {msg}')
        _push_error_log(level, stage, msg, pipeline_id)

    def _set_stage(name, status='running'):
        job['current_stage'] = name
        tl = job.setdefault('stage_timeline', [])
        # Rows carried a start ``ts`` but never an end, so the Kanban card
        # dialog could date a card and not time it (2026-08-26).  A worker is in
        # one stage at a time, so entering a stage also closes whatever the
        # previous one left open.
        now = _ams_iso()
        for entry in tl:
            if entry.get('name') != name and entry.get('status') == 'running':
                entry['status'] = 'completed'
                if not entry.get('ended_at'):
                    entry['ended_at'] = now
        for entry in tl:
            if entry['name'] == name:
                entry['status'] = status
                if status == 'running':
                    entry['ended_at'] = None
                    if not entry.get('started_at'):
                        entry['started_at'] = entry.get('ts') or now
                elif not entry.get('ended_at'):
                    entry['ended_at'] = now
                return
        tl.append(
            {
                'name': name,
                'status': status,
                'ts': now,
                'started_at': now,
                'ended_at': None if status == 'running' else now,
            }
        )

    def _complete_stage(name):
        _set_stage(name, 'completed')

    def _fail_stage(name, err):
        _set_stage(name, 'failed')
        job['error'] = err
        _log('ERROR', name, err)

    from zyg_workflows.video_stages.context import StageExit, VideoContext
    from zyg_workflows.video_stages.stage_01_scene_plan import stage_01_scene_plan
    from zyg_workflows.video_stages.stage_02_images import (
        stage_02_image_prep,
        stage_02b_anatomy_repair,
        stage_02c_still_gate,
    )
    from zyg_workflows.video_stages.stage_03_tts import stage_03_tts
    from zyg_workflows.video_stages.stage_04_video_generation import stage_04_video_generation
    from zyg_workflows.video_stages.stage_05_assembly import stage_05_assembly

    # Everything that crosses a stage boundary. `_flux_gpu_acq_v` /
    # `_wan_gpu_acq_v` are fields and not locals because the `except`/`finally`
    # below release `_GPU_PIPELINE_LOCK` off them, and the stage that acquires
    # the lock has to flip the flag where the handlers can see it at once.
    ctx = VideoContext(
        pipeline_id=pipeline_id,
        directive=directive,
        image_paths=image_paths,
        video_duration_minutes=video_duration_minutes,
        narration_enabled=narration_enabled,
        visual_style=visual_style,
        scene_mode=scene_mode,
        ending_text=ending_text,
        job=job,
        out_dir=out_dir,
        _manga_mode=_manga_mode,
        _dir_prefix=_dir_prefix,
        _sp_video=_sp_video,
        _log=_log,
        _set_stage=_set_stage,
        _complete_stage=_complete_stage,
        _fail_stage=_fail_stage,
    )

    try:
        stage_01_scene_plan(ctx)

        _stage_exit = stage_02_image_prep(ctx)
        if isinstance(_stage_exit, StageExit):
            return _stage_exit.value

        _stage_exit = stage_02c_still_gate(ctx)
        if isinstance(_stage_exit, StageExit):
            return _stage_exit.value

        stage_02b_anatomy_repair(ctx)

        stage_03_tts(ctx)

        stage_04_video_generation(ctx)

        # The module global the 4K master encode derives its ffmpeg timeout from.
        ctx.tts_duration = tts_duration
        _stage_exit = stage_05_assembly(ctx)
        if isinstance(_stage_exit, StageExit):
            return _stage_exit.value

    except Exception as _outer_e:
        import traceback

        tb = traceback.format_exc()
        _log('ERROR', 'Video Pipeline', f'Unhandled error: {_outer_e}\n{tb}')
        job['status'] = 'failed'
        job['error'] = str(_outer_e)
        # Release GPU lock if still held after unhandled exception
        if ctx._flux_gpu_acq_v or ctx._wan_gpu_acq_v:
            try:
                _GPU_PIPELINE_LOCK.release()
            except Exception as _exc:
                _zyg_log.warning('GPU pipeline lock release failed after the unhandled error: %s', _exc)
        # Mark all in-progress stages as failed
        _fail_now = _ams_iso()
        for entry in job.get('stage_timeline') or []:
            if entry.get('status') == 'running':
                entry['status'] = 'failed'
                if not entry.get('ended_at'):
                    entry['ended_at'] = _fail_now

    finally:
        if ctx._flux_gpu_acq_v or ctx._wan_gpu_acq_v:
            try:
                _GPU_PIPELINE_LOCK.release()
            except Exception as _exc:
                _zyg_log.debug('GPU pipeline lock already released: %s', _exc)
        _release_pipeline_vram('post-pipeline', lambda m: _log('INFO', 'Cleanup', m))


def _make_book_intro(out_dir: str, title: str, description: str, essay_img: str = None, duration: float = 8.0) -> str:
    """
    Render an open-book intro clip.
    Left page: title + description in historical handwriting font.
    Right page: essay image if available.
    Returns path to the rendered MP4, or '' on failure.
    """
    import textwrap as _tw

    book_out = os.path.join(out_dir, 'book_intro.mp4')
    if not os.path.exists(_BOOK_PNG) or not os.path.exists(_BOOK_FONT):
        return ''
    try:
        # Escape text for ffmpeg drawtext
        def _esc(t):
            return t.replace('\\', '\\\\').replace(':', '\\:').replace("'", "\\'").replace('%', '\\%')

        # Wrap title to ~28 chars per line
        title_lines = _tw.wrap(title[:120], width=28)
        title_text = '\n'.join(title_lines[:3])

        # Wrap description to ~32 chars per line
        desc_lines = _tw.wrap(description[:200], width=32)
        desc_text = '\n'.join(desc_lines[:4])

        # Left page centre: roughly x=240, right half of left page
        # Book occupies full 1920x1080; left page centre ~x=480, y=540
        _lx = 480  # left page horizontal centre
        _ty = 300  # title top y
        _dy = 560  # description top y

        # Build filter chain
        # 1. Scale book to 1920x1080
        # 2. Fade in (0→1s), hold, fade out (last 1s)
        _fade_in = 'fade=t=in:st=0:d=1.5'
        _fade_out = f'fade=t=out:st={duration - 1.5:.1f}:d=1.5'

        _title_filter = (
            f"drawtext=fontfile='{_BOOK_FONT}'"
            f":text='{_esc(title_text)}'"
            f':fontsize=54:fontcolor=0x2c1a0e'
            f':x={_lx}-text_w/2:y={_ty}'
            f':line_spacing=14'
        )
        _desc_filter = (
            f"drawtext=fontfile='{_BOOK_FONT}'"
            f":text='{_esc(desc_text)}'"
            f':fontsize=34:fontcolor=0x3a2510'
            f':x={_lx}-text_w/2:y={_dy}'
            f':line_spacing=10'
        )

        if essay_img and os.path.exists(essay_img):
            # Overlay essay image on right page (~x=1440, y=540, max 480x420)
            _vf = (
                f'[0:v]scale=1920:1080:force_original_aspect_ratio=increase,'
                f'crop=1920:1080,setsar=1[book];'
                f'[1:v]scale=480:420:force_original_aspect_ratio=decrease,'
                f'pad=480:420:(ow-iw)/2:(oh-ih)/2:color=0xd4a96400[img];'
                f'[book][img]overlay=x=1200:y=330[bk];'
                f'[bk]{_title_filter},{_desc_filter},{_fade_in},{_fade_out}[vout]'
            )
            _book_base = [
                exe('ffmpeg'),
                '-y',
                '-loop',
                '1',
                '-t',
                str(duration),
                '-i',
                _BOOK_PNG,
                '-loop',
                '1',
                '-t',
                str(duration),
                '-i',
                essay_img,
                '-filter_complex',
                _vf,
                '-map',
                '[vout]',
                '-r',
                '25',
            ]
            _book_nvenc = _book_base + _nvenc_vcodec_args(_cq_for_crf(22), 'p4') + [book_out]
            _book_x264 = _book_base + _x264_vcodec_args(22, 'fast') + [book_out]
        else:
            _vf = (
                f'scale=1920:1080:force_original_aspect_ratio=increase,'
                f'crop=1920:1080,setsar=1,'
                f'{_title_filter},{_desc_filter},{_fade_in},{_fade_out}'
            )
            _book_base = [
                exe('ffmpeg'),
                '-y',
                '-loop',
                '1',
                '-t',
                str(duration),
                '-i',
                _BOOK_PNG,
                '-vf',
                _vf,
                '-r',
                '25',
            ]
            _book_nvenc = _book_base + _nvenc_vcodec_args(_cq_for_crf(22), 'p4') + [book_out]
            _book_x264 = _book_base + _x264_vcodec_args(22, 'fast') + [book_out]

        _r = _ffmpeg_run_nvenc_first(_book_nvenc, _book_x264, 120, label='book intro')
        if _r.returncode == 0 and os.path.exists(book_out):
            return book_out
        _zyg_log.info(f'[BOOK INTRO] ffmpeg failed: {_r.stderr[-300:].decode(errors="replace")}')
        return ''
    except Exception as _e:
        _zyg_log.info(f'[BOOK INTRO ERROR] {_e}')
        return ''


def _burn_subtitles(
    video_path: str,
    audio_path: str,
    out_path: str,
    pipeline_id: str = '',
    word_timings_raw: list = None,
    intro_offset: float = 0.0,
    narration_script: str = '',
    voice_mode: str = 'narration',
    digits_in_subs: bool = False,
) -> bool:
    """
    Generate subtitles and burn into video.
    Primary path: TTS word timings aligned to narration_script (punctuation preserved).
    Fallback: Whisper on audio, aligned to script when narration_script is provided.
    Returns True on success.

    digits_in_subs: spell-out cardinals -> digits in the CAPTION text only
    (`_sub_digits`). Off by default so existing callers are byte-identical;
    the documentary passes True. It is applied to the caption and never to
    `narration_script`, because that string is what the word timings are
    aligned against — collapsing 'five hundred and ninety three' to '593'
    there would shift every subsequent cue.
    """

    srt_path = video_path.replace('.mp4', '.srt')

    def _digits(_t: str) -> str:
        """Convert one already-wrapped caption LINE. Per line, not per cue:
        `_sub_digits` treats any whitespace as joinable, so a number phrase
        straddling a line break would be folded into digits and take the
        break with it. Converting each line alone means such a phrase is
        simply left spelled — a missed conversion, never a mangled cue.
        Conversion only ever shortens a line, so wrapping stays valid."""
        if not digits_in_subs or not _t:
            return _t
        try:
            from zyg_workflows.storyteller_scene_service import _sub_digits as _sd

            return _sd(_t)
        except Exception:
            return _t

    def _fmt_ts(s):
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        sec = s % 60
        return f'{h:02d}:{m:02d}:{sec:06.3f}'.replace('.', ',')

    def _burn_srt(srt_file):
        # SRT is delivered to YouTube directly — copy clean video, no burn
        import shutil as _shu_srt

        _shu_srt.copy2(video_path, out_path)
        _zyg_log.info(f'[SUBTITLES] SRT saved: {srt_file}  (YouTube mode — no burn)')
        return True

    try:
        # ── Primary: word timings (Azure SDK), script-aligned ─────────
        if word_timings_raw:
            _timings_for_subs, _align_cov = _align_narration_word_timings(
                narration_script,
                word_timings_raw,
                voice_mode=voice_mode,
            )
            if _align_cov >= 0.5:
                _zyg_log.info(f'[SUBTITLES] Script-aligned {len(_timings_for_subs)} words ({_align_cov:.0%} coverage)')
            _MAX_LINE_CHARS = 42  # max chars per line
            _MAX_LINES = 2  # max 2 lines per subtitle card
            # Cinema anticipation: show subtitle this many seconds BEFORE the
            # first word of each card is spoken — reader's eye lands on the text
            # just as the narrator begins the sentence (2 frames at 24fps = 83ms).
            _CINEMA_LEAD = 0.083
            _lines = []

            _block_words_by_line = []  # list of lines, each line = list of words
            _block_start = None
            _cur_line = []
            _cur_line_chars = 0

            def _flush_block(end_t):
                if _block_words_by_line and _block_start is not None:
                    # Build SRT text: join lines with \n for hard line break
                    _text = '\n'.join(_digits(' '.join(ww)) for ww in _block_words_by_line)
                    _lines.append((_block_start, end_t, _text))

            for _word, _t in _timings_for_subs:
                # Shift all timestamps by intro offset then apply cinema lead-in.
                # Applying lead to every timestamp uniformly means block starts
                # and block ends both shift by the same amount — no overlap/gap.
                _t_shifted = max(0.0, _t + intro_offset - _CINEMA_LEAD)
                _word_len = len(_word) + 1  # +1 for space

                if _block_start is None:
                    _block_start = _t_shifted
                    _block_words_by_line = [[]]
                    _cur_line = _block_words_by_line[0]
                    _cur_line_chars = 0

                # Would this word overflow the current line?
                if _cur_line_chars + _word_len > _MAX_LINE_CHARS and _cur_line:
                    if len(_block_words_by_line) >= _MAX_LINES:
                        # Block full — emit it, start new block at this word's timestamp
                        _flush_block(_t_shifted)
                        _block_start = _t_shifted
                        _block_words_by_line = [[]]
                        _cur_line = _block_words_by_line[0]
                        _cur_line_chars = 0
                    else:
                        # Start a new line within same block
                        _block_words_by_line.append([])
                        _cur_line = _block_words_by_line[-1]
                        _cur_line_chars = 0

                _cur_line.append(_word)
                _cur_line_chars += _word_len

            # Flush the last block — hold 0.5s after the last word
            if _block_words_by_line and any(_block_words_by_line) and _block_start is not None:
                _last_t = max(0.0, _timings_for_subs[-1][1] + intro_offset - _CINEMA_LEAD) + 0.5
                _flush_block(_last_t)

            with open(srt_path, 'w', encoding='utf-8') as _sf:
                for _idx, (_s, _e, _text) in enumerate(_lines, 1):
                    _sf.write(f'{_idx}\n')
                    _sf.write(f'{_fmt_ts(_s)} --> {_fmt_ts(_e)}\n')
                    _sf.write(_text.strip() + '\n\n')

            _zyg_log.info(
                f'[SUBTITLES] SRT from word timings: {len(_lines)} lines (offset={intro_offset:.1f}s, lead={_CINEMA_LEAD * 1000:.0f}ms)'
            )
            return _burn_srt(srt_path)

        # ── Fallback: Whisper (script-aligned when narration provided) ────────
        if narration_script and narration_script.strip():
            try:
                from zyg_workflows import murch_engine as _murch_sub

                _whisper_aligned = _murch_sub.extract_word_timestamps_whisper(
                    audio_path,
                    narration_script,
                )
                if _whisper_aligned:
                    _MAX_LINE_CHARS = 42
                    _MAX_LINES = 2
                    _CINEMA_LEAD = 0.083
                    _lines = []
                    _block_words_by_line = []
                    _block_start = None
                    _cur_line = []
                    _cur_line_chars = 0

                    def _flush_block_w(end_t):
                        if _block_words_by_line and _block_start is not None:
                            _text = '\n'.join(_digits(' '.join(ww)) for ww in _block_words_by_line)
                            _lines.append((_block_start, end_t, _text))

                    for _word, _t in _whisper_aligned:
                        _t_shifted = max(0.0, _t + intro_offset - _CINEMA_LEAD)
                        _word_len = len(_word) + 1
                        if _block_start is None:
                            _block_start = _t_shifted
                            _block_words_by_line = [[]]
                            _cur_line = _block_words_by_line[0]
                            _cur_line_chars = 0
                        if _cur_line_chars + _word_len > _MAX_LINE_CHARS and _cur_line:
                            if len(_block_words_by_line) >= _MAX_LINES:
                                _flush_block_w(_t_shifted)
                                _block_start = _t_shifted
                                _block_words_by_line = [[]]
                                _cur_line = _block_words_by_line[0]
                                _cur_line_chars = 0
                            else:
                                _block_words_by_line.append([])
                                _cur_line = _block_words_by_line[-1]
                                _cur_line_chars = 0
                        _cur_line.append(_word)
                        _cur_line_chars += _word_len

                    if _block_words_by_line and any(_block_words_by_line) and _block_start is not None:
                        _last_t = max(0.0, _whisper_aligned[-1][1] + intro_offset - _CINEMA_LEAD) + 0.5
                        _flush_block_w(_last_t)

                    with open(srt_path, 'w', encoding='utf-8') as _sf:
                        for _idx, (_s, _e, _text) in enumerate(_lines, 1):
                            _sf.write(f'{_idx}\n')
                            _sf.write(f'{_fmt_ts(_s)} --> {_fmt_ts(_e)}\n')
                            _sf.write(_text.strip() + '\n\n')

                    _zyg_log.info(f'[SUBTITLES] SRT from Whisper+script: {len(_lines)} lines')
                    return _burn_srt(srt_path)
            except Exception as _wse:
                _zyg_log.info(f'[SUBTITLES] Whisper+script failed: {_wse}')

        # 2026-07-28: upgraded from openai-whisper `base` to faster-whisper
        # large-v3 + VAD via the shared VRAM-aware loader (CPU-safe fallback).
        import zyg_whisper as _zw

        _segs, _info = _zw.transcribe_segments(audio_path, language='en', want_words=False, vad=True)

        with open(srt_path, 'w', encoding='utf-8') as _sf:
            for i, seg in enumerate(_segs, 1):
                _sf.write(f'{i}\n')
                _s = seg['start'] + intro_offset
                _e = seg['end'] + intro_offset
                _sf.write(f'{_fmt_ts(_s)} --> {_fmt_ts(_e)}\n')
                _sf.write(_digits(seg['text'].strip()) + '\n\n')

        _zyg_log.info(f'[SUBTITLES] SRT from Whisper segments: {len(_segs)}')
        return _burn_srt(srt_path)

    except Exception as _e:
        _zyg_log.info(f'[SUBTITLES ERROR] {_e}')
        return False
