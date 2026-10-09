# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The phases of Stage 4b, lifted out of ``_pf_stage_4b`` one seam at a time.

``_pf_stage_4b`` is now an orchestrator that calls these in the order the
original statements ran: build the lookups, score every video (phase A), ask
the directors for moments (phase A.5), check the disk, build the render job
list, pre-generate the narrator lines (phase B.0), register the queued
markers, and — after the render pool has run — recover stray clips and report
the quality gate.  Bodies and log lines are unchanged; what used to be read
from the enclosing scope is a parameter.
"""

import json
import os
from zyg_workflows.pipeline_config import _SENSITIVE_TOPIC_KEYWORDS
from zyg_workflows.narrator_voice_service import _vid_to_channel_id
from zyg_workflows.stage_runner.stage4b_scoring import _pick_top_timestamps
from zyg_workflows.stage_runner.stage4b_scoring import _score_motion
from zyg_workflows.stage_runner.stage4b_scoring import _score_transcript
from zyg_workflows.subproc_registry import _register_marker
from zyg_workflows import paths

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.stage_runner')


def _build_video_lookups(state) -> tuple:
    """Return (vid_id -> title, vid_id -> channel name) from the pipeline state.

    Also populates the shared ``_vid_to_channel_id`` map used later for
    narrator voice resolution: ``video_candidates`` carries the channel name,
    the ``channels`` list carries the id, so the two are joined by name.
    """
    # Build vid_id → YouTube video title lookup for fallback naming

    _vid_meta_titles = {}
    _vid_channel_map = {}
    for _ac in state.get('approved_clips', []):
        _vid_meta_titles[_ac.get('video_id', '')] = _ac.get('title', '')
        _vid_channel_map[_ac.get('video_id', '')] = _ac.get('channel_name', '')

    # Build vid_id → channel_id for narrator voice resolution
    # video_candidates has channel_name; channels list has channel_id
    _name_to_chid = {c.get('name', ''): c.get('channel_id', '') for c in state.get('channels', [])}
    for _vc in state.get('video_candidates', []):
        _vc_vid = _vc.get('video_id', '')
        _vc_chname = _vc.get('channel_name', '')
        if _vc_vid:
            _vid_to_channel_id[_vc_vid] = _name_to_chid.get(_vc_chname, _vc_chname)
    return _vid_meta_titles, _vid_channel_map


def _ensure_asset_dirs() -> tuple:
    """Create and return the (sfx, reaction clips) asset directories."""
    # Asset directories for sound effects and reaction clips
    _ASSETS_DIR = str(paths.PKG_DIR.parent / 'data' / 'assets')
    _SFX_DIR = os.path.join(_ASSETS_DIR, 'sfx')
    _REACT_DIR = os.path.join(_ASSETS_DIR, 'reaction_clips')
    os.makedirs(_SFX_DIR, exist_ok=True)
    os.makedirs(_REACT_DIR, exist_ok=True)
    return _SFX_DIR, _REACT_DIR


def _process_one_video(vid_id_path, out_dir, viral_keywords, _log_err, _log_warn, _log_info):
    """Score one fetched video; return its scores or None if the file is gone.

    ``vid_id_path`` is the ``(vid_id, vid_path)`` pair straight off
    ``fetched_files``.  Reads the transcript next to it in ``out_dir``, warns
    about poor transcripts and sensitive topics, then returns the dict phase
    A.5 consumes: vid_id, vid_path, tx_path, tx_score, motion_score and
    vid_duration.
    """
    vid_id, vid_path = vid_id_path
    if not os.path.exists(vid_path):
        _log_err(f'Stage 4b {vid_id}', f'File not found: {vid_path}')
        return None

    # ── 1. Get video duration ────────────────────────────────────────
    try:
        import cv2 as _cv2

        _cap = _cv2.VideoCapture(vid_path)
        _fps = _cap.get(_cv2.CAP_PROP_FPS) or 25.0
        _fc = _cap.get(_cv2.CAP_PROP_FRAME_COUNT) or 0
        _cap.release()
        vid_duration = _fc / _fps
    except Exception:
        vid_duration = 3600.0

    _log_info(f'Stage 4b scoring {vid_id}: duration={vid_duration:.0f}s')

    # ── 2. Transcript quality check ──────────────────────────────────
    tx_path = os.path.join(out_dir, f'{vid_id}_transcript.json')
    _check_transcript_quality(tx_path, vid_id, _log_warn)
    tx_score = _score_transcript(tx_path, vid_duration, viral_keywords)
    _log_info(
        f'Stage 4b {vid_id}: transcript scored {len(tx_score)} seconds, top={max(tx_score.values(), default=0):.2f}'
    )

    # ── 3. Motion score (CPU-intensive — runs alone, 10 workers × 2 threads) ─
    _log_info(f'Stage 4b {vid_id}: running motion scorer at 2fps …')
    motion_score = _score_motion(vid_path, _log_err)
    _log_info(
        f'Stage 4b {vid_id}: motion scored {len(motion_score)} seconds, top={max(motion_score.values(), default=0):.2f}'
    )

    # Return scored data — GPT-4o is called ONCE for ALL videos after this loop
    return {
        'vid_id': vid_id,
        'vid_path': vid_path,
        'tx_path': tx_path,
        'tx_score': tx_score,
        'motion_score': motion_score,
        'vid_duration': vid_duration,
    }


def _check_transcript_quality(tx_path: str, vid_id: str, _log_warn) -> None:
    """Warn about a thin, mostly-empty or unreadable transcript, and about
    sensitive topics found in it. Warnings only — nothing is ever blocked."""
    try:
        with open(tx_path) as _txf:
            _tx_segs = json.load(_txf).get('segments', [])
        _tx_words = sum(len(s.get('text', '').split()) for s in _tx_segs)
        _tx_non_empty = sum(1 for s in _tx_segs if len(s.get('text', '').strip()) > 3)
        if _tx_words < 50:
            _log_warn(
                f'Stage 4b {vid_id}: ⚠ transcript has only {_tx_words} words — likely garbage or silent video. Clip selection will be poor.'
            )
        elif _tx_non_empty / max(len(_tx_segs), 1) < 0.4:
            _log_warn(
                f'Stage 4b {vid_id}: ⚠ transcript is {100 * _tx_non_empty // max(len(_tx_segs), 1)}% empty segments — transcript quality is low.'
            )
    except Exception:
        _log_warn(f'Stage 4b {vid_id}: ⚠ could not read transcript for quality check — scoring will use motion only.')

    # ── Sensitive topic detection (warning only — no block) ──────────
    try:
        with open(tx_path) as _txf2:
            _full_tx = ' '.join(s.get('text', '') for s in json.load(_txf2).get('segments', [])).lower()
        for _topic, _kws in _SENSITIVE_TOPIC_KEYWORDS.items():
            _hits = [kw for kw in _kws if kw in _full_tx]
            if _hits:
                _log_warn(
                    f'Stage 4b {vid_id}: [REVIEW REQUIRED] sensitive topic detected — '
                    f'{_topic} (triggered by: {", ".join(_hits[:3])})'
                )
    except Exception as _exc:
        _zyg_log.warning('sensitive topic scan of %s failed, no review flag raised: %s', tx_path, _exc)


def _score_all_videos(fetched, out_dir, viral_keywords, _log_err, _log_warn, _log_info) -> list:
    """Phase A: score every fetched video one at a time and return the results.

    Sequential on purpose — the motion scorer already uses 10 workers × 2
    threads, which keeps CPU at ~83% and leaves 4 cores for Flask/telemetry.
    """
    # ── Phase A: Score all videos SEQUENTIALLY (10 workers × 2 threads = 20 cores max) ──
    # One video at a time keeps CPU at ~83%, leaving 4 cores free for Flask/telemetry
    _log_info('Stage 4b Phase A: sequential motion scoring begins')
    scored_raw = []
    for _vid_entry in fetched.items():
        _result = _process_one_video(_vid_entry, out_dir, viral_keywords, _log_err, _log_warn, _log_info)
        if _result:
            scored_raw.append(_result)
    _log_info(f'Stage 4b Phase A complete: {len(scored_raw)} videos scored')
    return scored_raw


def _assign_moments(scored_raw, _ask_github_models_bulk, _log_warn, _log_info) -> tuple:
    """Phase A.5: ask the directors for clip moments, return (videos, moments).

    One request per video avoids a 413 on the bulk payload.  A video the
    directors skipped falls back to ``_pick_top_timestamps`` and generic
    titles.  The second element is the raw per-video moment map, which the
    quality gate later checks for emptiness.
    """
    # ── Phase A.5: per-video GPT-4o calls in parallel ────────────────────
    # One request per video avoids 413 Payload Too Large (bulk = ~44KB, limit ~32KB)
    _log_info(f'Stage 4b Phase A.5: sending {len(scored_raw)} per-video GPT-4o Director requests in parallel …')
    try:
        _bulk_moments, _bulk_titles, _bulk_sfx, _bulk_react, _bulk_intro = _ask_github_models_bulk(
            scored_raw, n_clips=5
        )
    except Exception as _bulk_ex:
        _log_warn(f'GPT-4o bulk call unpacking failed ({_bulk_ex}) — using algorithmic fallback for all videos')
        _bulk_moments, _bulk_titles, _bulk_sfx, _bulk_react, _bulk_intro = {}, {}, {}, {}, {}

    scored_videos = []
    for _sv in scored_raw:
        _vid_id = _sv['vid_id']
        _moments = _bulk_moments.get(_vid_id)
        _titles = _bulk_titles.get(_vid_id, [])
        _sfx_plan = _bulk_sfx.get(_vid_id, [])
        _react_plan = _bulk_react.get(_vid_id, [])
        _intro_line = _bulk_intro.get(_vid_id, '')
        if not _moments:
            _log_warn(
                f'Stage 4b {_vid_id}: ⚠ GPT-4o returned NO clips for this video — clip timestamps chosen by algorithm, titles will be generic. Check your GitHub Models quota.'
            )
            _moments = _pick_top_timestamps(_sv['motion_score'], _sv['tx_score'], _sv['vid_duration'], n_clips=5)
            _titles = []
        _log_info(f'Stage 4b {_vid_id}: selected clip starts: {_moments}')
        scored_videos.append(
            {
                'vid_id': _vid_id,
                'vid_path': _sv['vid_path'],
                'tx_path': _sv['tx_path'],
                'moments': _moments,
                'titles': _titles,
                'sfx_plan': _sfx_plan,
                'react_plan': _react_plan,
                'intro': _intro_line,
            }
        )
    _log_info(f'Stage 4b Phase A.5 complete: moments assigned for {len(scored_videos)} videos')
    return scored_videos, _bulk_moments


def _check_disk_space(out_dir: str, n_videos: int, _log_warn, _log_info) -> None:
    """Warn before rendering if the output volume cannot hold ~900MB per clip."""
    # ── Disk space check before rendering ───────────────────────────────
    try:
        import shutil as _shutil_disk

        _disk = _shutil_disk.disk_usage(out_dir)
        _free_gb = _disk.free / (1024**3)
        _needed_gb = n_videos * 5 * 0.9  # ~900MB per 15min clip estimate
        if _free_gb < 10.0:
            _log_warn(
                f'Stage 4b: ⚠ LOW DISK SPACE — {_free_gb:.1f} GB free on output volume. Rendering {n_videos} videos may fail.'
            )
        elif _free_gb < _needed_gb:
            _log_warn(
                f'Stage 4b: ⚠ disk space may be tight — {_free_gb:.1f} GB free, estimated need ~{_needed_gb:.1f} GB for {n_videos} videos.'
            )
        else:
            _log_info(f'Stage 4b: disk space OK — {_free_gb:.1f} GB free')
    except Exception as _dsk_e:
        _log_warn(f'Stage 4b: could not check disk space ({_dsk_e})')


def _build_render_jobs(scored_videos) -> list:
    """Flatten the scored videos into one render job tuple per clip moment.

    Each tuple is (vid_id, vid_path, tx_path, clip_index, start_ts, title,
    sfx_plan, react_plan, intro) — the argument the renderer is mapped over.
    """
    # Build flat render job list across all scored videos
    return [
        (
            sv['vid_id'],
            sv['vid_path'],
            sv['tx_path'],
            i,
            ts,
            sv['titles'][i] if i < len(sv.get('titles', [])) else '',
            sv.get('sfx_plan', []),
            sv.get('react_plan', []),
            sv.get('intro', ''),
        )
        for sv in scored_videos
        for i, ts in enumerate(sv['moments'])
    ]


def _pregenerate_narrator_lines(_render_jobs, _get_contextual_commentary, _log_info) -> dict:
    """Phase B.0: return (vid_id, clip_idx) -> narrator line for every job.

    The director's INTRO is used verbatim when it exists; otherwise the line
    is written from the ±30s of transcript around the clip start, with a 2s
    pause between calls to respect the model's rate limit.
    """
    # Use director INTRO as narrator line if available; otherwise pre-generate via GPT-4o
    import time as _time_nar

    _narrator_lines = {}  # (vid_id, clip_idx) -> narrator line string
    _log_info('Stage 4b Phase B.0: pre-generating narrator lines ...')
    for _jvid, _, _jtx, _ji, _jts, _jtitle, _jsfx, _jreact, _jintro in _render_jobs:
        if _jintro:
            # Director already wrote the intro line — use it as narrator for clip 0 (first clip of that video)
            _narrator_lines[(_jvid, _ji)] = _jintro
        else:
            _moment_txt = ''
            try:
                with open(_jtx) as _jtf:
                    _jsegs = json.load(_jtf).get('segments', [])
                _jwindow = [s.get('text', '') for s in _jsegs if abs(float(s.get('start', 0)) - float(_jts)) < 30]
                _moment_txt = ' '.join(_jwindow)[:300]
            except Exception as _exc:
                _zyg_log.warning(
                    'transcript %s unreadable, narrator line written without the moment text: %s', _jtx, _exc
                )
            _narrator_lines[(_jvid, _ji)] = _get_contextual_commentary(_moment_txt, _jtitle)
            _time_nar.sleep(2)
    _log_info(f'Stage 4b Phase B.0 complete: {len(_narrator_lines)} narrator lines ready')
    return _narrator_lines


def _register_queued_markers(_render_jobs, pipeline_id) -> dict:
    """Pre-register every render job as 'queued' so Tail Subs shows them at once.

    Returns (vid_id, clip_idx) -> marker pid, which the renderer flips to
    'running' when it picks the job up.
    """
    # Pre-register all render jobs as 'queued' so Tail Subs shows them immediately
    _queued_markers = {}  # (vid_id, clip_idx) -> fake_pid
    for _jargs in _render_jobs:
        _qvid, _, _, _qi, _qts, _qt = _jargs[0], _jargs[1], _jargs[2], _jargs[3], _jargs[4], _jargs[5]
        _qlabel = f'⏳ queued: render {_qvid} clip{_qi + 1}' + (f' — {_qt}' if _qt else '')
        _qpid = _register_marker(_qlabel, pipeline_id=pipeline_id, status='queued')
        _queued_markers[(_qvid, _qi)] = _qpid
    return _queued_markers


def _recover_processed_clips(processed, out_dir, _log_info) -> None:
    """If nothing was appended, scan ``out_dir`` for clips ffmpeg did write.

    Guards against a render-tool exception that prevented the append; appends
    the recovered entries (preferring the ``_norm`` variant) to ``processed``
    in place.  A non-empty ``processed`` is left untouched.
    """
    # Recovery scan: if processed is still empty, scan output dir for existing clip files
    # (guards against a render-tool exception that prevented append but ffmpeg still wrote the file)
    if not processed:
        _log_info('Stage 4b: processed list empty — scanning output dir for existing clips')
        import re as _re

        for _fn in sorted(os.listdir(out_dir)):
            _m = _re.match(r'^(.+)_clip(\d+)\.mp4$', _fn)
            if _m and '_norm' not in _fn:
                _vid_id, _ci = _m.group(1), int(_m.group(2))
                _fp = os.path.join(out_dir, _fn)
                if os.path.exists(_fp) and os.path.getsize(_fp) > 0:
                    # Prefer the norm version if it exists
                    _norm = os.path.join(out_dir, f'{_vid_id}_clip{_ci}_norm.mp4')
                    _final = _norm if os.path.exists(_norm) and os.path.getsize(_norm) > 0 else _fp
                    processed.append(
                        {
                            'video_id': _vid_id,
                            'clip_index': _ci,
                            'path': _final,
                            'source_ts': None,
                            'recovered': True,
                        }
                    )
        _log_info(f'Stage 4b recovery scan found {len(processed)} clips')


def _report_quality_gate(processed, _render_jobs, _bulk_moments, _log_warn, _log_info) -> None:
    """Flag the two ways Stage 4b silently degrades, then log the stage total.

    A job with an empty title field means the directors returned no title; an
    empty ``_bulk_moments`` means every clip fell back to the algorithm.
    """
    # ── Quality gate: flag anything that didn't work ─────────────────────
    _clips_without_titles = sum(1 for j in _render_jobs if not j[5])
    if _clips_without_titles > 0:
        _log_warn(
            f'Stage 4b QA: ⚠ {_clips_without_titles}/{len(_render_jobs)} clips have NO descriptive title — filenames are video_id only. GPT-4o did not return titles.'
        )
    if not _bulk_moments:
        _log_warn(
            'Stage 4b QA: ⚠ GPT-4o returned ZERO clip moments for ALL videos — every clip used dumb algorithmic fallback. Titles are missing. Check GITHUB_TOKEN validity and GitHub Models rate limits.'
        )
    _log_info(
        f'Stage 4b complete: {len(processed)} clips rendered, {len(_render_jobs) - _clips_without_titles} with titles'
    )
