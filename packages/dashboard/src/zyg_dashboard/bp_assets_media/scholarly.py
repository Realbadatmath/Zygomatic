# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Ready-for-deployment clips, scholarly imagery/videos and storyteller episodes.

Moved verbatim out of bp_assets_media.py (original lines 349-707).
"""

import json
import os
from datetime import datetime, timezone

from flask import jsonify, request, send_file

from zyg_dashboard.gui.runtime_state import _RUNTIME_DIR, _runtime_path
from zyg_dashboard.gui.timeutil import _AMS_TZ

from zyg_dashboard.bp_assets_media.base import (
    _zyg_log,
    bp,
)


@bp.route('/api/rfd/clips')
def api_rfd_clips():
    """Return all Ready-For-Deployment clips from all completed pipeline runs."""
    import os as _os

    rfd_clips = []
    from zyg_workflows.pipeline_common import is_test_pipeline_id as _is_test_pid, recent_state_files as _recent_sf

    # P-03 (2026-08-25): no smoke/gatecheck states (they were listed as
    # deployable clips, department "Clipfarm", category "General"), and the
    # department label comes from the state file instead of a constant.
    _RFD_DEPT_LABELS = {
        'scholarly': 'Documentary',
        'crime': 'Crime',
        'clipfarm': 'Clipfarm',
        'video': 'Video',
        'manga': 'Manga',
        'storyteller': 'Storyteller',
        'tokitoki': 'TokiToki',
        'stocks': 'Stocks',
    }
    state_files = _recent_sf(_runtime_path('pipeline_*_state.json'))
    for sf in state_files:
        try:
            with open(sf) as _f:
                st = json.load(_f)
            pid = st.get('pipeline_id', '')
            if _is_test_pid(pid):
                continue
            started = st.get('started', '')
            _dept_key = (st.get('department') or '').strip().lower()
            dept_label = _RFD_DEPT_LABELS.get(_dept_key) or (
                _dept_key.replace('_', ' ').title() if _dept_key else 'Clipfarm'
            )
            approved = {v.get('video_id', ''): v for v in st.get('approved_clips', [])}
            errors = [e for e in st.get('preflight_errors', []) if e]
            for clip in st.get('processed_clips', []):
                path = clip.get('path', '')
                if not path or not _os.path.exists(path):
                    continue
                vid_id = clip.get('video_id', '')
                src = approved.get(vid_id, {})
                ch_name = src.get('channel_name', '')
                fname = _os.path.basename(path)
                title = fname.replace('.mp4', '').replace('_', ' ').title()
                try:
                    stat = _os.stat(path)
                    size_mb = round(stat.st_size / 1024 / 1024, 1)
                    created_ts = stat.st_mtime
                    if _AMS_TZ is not None:
                        created = datetime.fromtimestamp(created_ts, tz=_AMS_TZ).isoformat(timespec='milliseconds')
                    else:
                        created = datetime.fromtimestamp(created_ts, tz=timezone.utc).isoformat(timespec='milliseconds')
                except Exception:
                    size_mb = 0
                    created = started
                ch_lower = ch_name.lower()
                if 'history' in ch_lower or 'predictive' in ch_lower:
                    category = 'History / Geopolitics'
                elif 'fit' in ch_lower or 'fresh' in ch_lower:
                    category = 'Entertainment / Dating'
                elif 'clav' in ch_lower:
                    category = 'Lifestyle / Commentary'
                elif 'crime' in ch_lower:
                    category = 'Crime / True Crime'
                elif _dept_key == 'scholarly':
                    category = 'Documentary'
                elif _dept_key == 'crime':
                    category = 'Crime / True Crime'
                else:
                    category = 'General'
                runtime_min = round(size_mb / 30, 1)
                rfd_clips.append(
                    {
                        'clip_id': f'{pid[:8]}_{vid_id}_{clip.get("clip_index", 0)}',
                        'title': title,
                        'filename': fname,
                        'path': path,
                        'pipeline_id': pid,
                        'pipeline_started': started,
                        'created': created,
                        'size_mb': size_mb,
                        'runtime_min': runtime_min,
                        'channel': ch_name,
                        'category': category,
                        'video_id': vid_id,
                        'source_url': f'https://www.youtube.com/watch?v={vid_id}' if vid_id else '',
                        'source_ts': clip.get('source_ts', 0),
                        'department': dept_label,
                        'flags': [e for e in errors if vid_id in str(e)],
                        'status': 'ready',
                    }
                )
        except Exception as _exc:
            _zyg_log.debug('skipping rfd clip that could not be summarised: %s', _exc)
            continue
    rfd_clips.sort(key=lambda x: x.get('created', ''), reverse=True)
    return jsonify({'clips': rfd_clips, 'total': len(rfd_clips)})


@bp.route('/api/scholarly/imagery')
def api_scholarly_imagery():
    """Returns FLUX-generated images from scholarly pipelines (stock images excluded)."""
    import glob as _glob_sch

    images_dir = os.path.join(_RUNTIME_DIR, 'scholarly_images')
    images = []
    if os.path.isdir(images_dir):
        for pipeline_dir in sorted(os.listdir(images_dir), reverse=True):
            pd_path = os.path.join(images_dir, pipeline_dir)
            if not os.path.isdir(pd_path):
                continue
            meta_file = os.path.join(pd_path, 'images_meta.json')
            meta = {}
            if os.path.exists(meta_file):
                try:
                    with open(meta_file) as _mf:
                        meta = json.load(_mf)
                except (OSError, ValueError) as _exc:
                    _zyg_log.warning(
                        'images_meta.json unreadable for %s, listing images without metadata: %s', pipeline_dir, _exc
                    )
            for img_file in sorted(
                _glob_sch.glob(os.path.join(pd_path, '*.jpg')) + _glob_sch.glob(os.path.join(pd_path, '*.png'))
            ):
                fname = os.path.basename(img_file)
                img_meta = meta.get(fname, {})
                # Only show FLUX-generated images — skip any stock/wikimedia assets
                if img_meta.get('source', 'flux') not in ('flux', ''):
                    continue
                images.append(
                    {
                        'path': img_file,
                        'filename': fname,
                        'pipeline_id': pipeline_dir,
                        'topic': img_meta.get('topic', ''),
                        'caption': img_meta.get('caption', fname),
                        'essay_title': img_meta.get('essay_title', ''),
                        'source': img_meta.get('source', 'flux'),
                        'duration_s': img_meta.get('duration_s'),
                        'used': img_meta.get('used', False),
                    }
                )
    return jsonify({'images': images, 'total': len(images)})


@bp.route('/api/scholarly/imagery/thumb')
def api_scholarly_imagery_thumb():
    """Serves a thumbnail of a scholarly image."""
    import flask as _fl_sch

    img_path = request.args.get('path', '')
    if not img_path or not os.path.exists(img_path):
        return _fl_sch.abort(404)
    # Security: must be within the scholarly_images dir
    images_dir = os.path.join(_RUNTIME_DIR, 'scholarly_images')
    if not os.path.abspath(img_path).startswith(os.path.abspath(images_dir)):
        return _fl_sch.abort(403)
    ext = os.path.splitext(img_path)[1].lower()
    mime = 'image/jpeg' if ext in ('.jpg', '.jpeg') else 'image/png'
    return _fl_sch.send_file(img_path, mimetype=mime)


@bp.route('/api/scholarly/videos')
def api_scholarly_videos():
    """Returns all scholarly pipeline videos."""
    clips_dir = os.path.join(os.path.dirname(_RUNTIME_DIR), 'output', 'clips')
    videos = []
    if os.path.isdir(clips_dir):
        for pid in sorted(os.listdir(clips_dir), reverse=True):
            pd_path = os.path.join(clips_dir, pid)
            if not os.path.isdir(pd_path):
                continue
            state_file = _runtime_path(f'pipeline_{pid}_state.json')
            if not os.path.exists(state_file):
                continue
            try:
                with open(state_file) as _sf:
                    state = json.load(_sf)
            except (OSError, ValueError) as _exc:
                _zyg_log.warning('pipeline state unreadable for %s, skipping it: %s', pid, _exc)
                continue
            if state.get('department') != 'scholarly':
                continue
            vid_path = state.get('video_path', '')
            if not vid_path or not os.path.exists(vid_path):
                # Fallback: find the largest .mp4 in the job folder that isn't a slideshow/intro
                _cands = sorted(
                    [
                        os.path.join(pd_path, f)
                        for f in os.listdir(pd_path)
                        if f.endswith('.mp4')
                        and '_slideshow' not in f
                        and '_subtitled' not in f
                        and '_with_intro' not in f
                    ],
                    key=lambda p: os.path.getsize(p) if os.path.exists(p) else 0,
                    reverse=True,
                )
                vid_path = _cands[0] if _cands else ''
            if not os.path.exists(vid_path):
                continue
            stat = os.stat(vid_path)
            _flux_manifest = []
            _flux_manifest_path = os.path.join(pd_path, 'flux_images', 'flux_manifest.json')
            if os.path.exists(_flux_manifest_path):
                try:
                    with open(_flux_manifest_path) as _fm:
                        _flux_manifest = json.load(_fm).get('images', [])
                except (OSError, ValueError) as _exc:
                    _zyg_log.debug('flux manifest unreadable, continuing without it: %s', _exc)
            videos.append(
                {
                    'pipeline_id': pid,
                    'topic': state.get('scholarly_topic', ''),
                    'title': state.get('essay_title', ''),
                    'description': next(
                        (c.get('description', '') for c in state.get('processed_clips', []) if c.get('description')), ''
                    ),
                    'duration_s': state.get('tts_duration', 0),
                    'word_count': state.get('word_count', 0),
                    'essay_authors': state.get('essay_authors', ''),
                    'episode': '1',
                    'created': state.get('started', ''),
                    'video_path': vid_path,
                    'filesize': stat.st_size,
                    'episode2_ready': bool(state.get('episode2_text')),
                    'episode3_ready': bool(state.get('episode3_text')),
                    'flux_images': len(_flux_manifest),
                    'flux_manifest': _flux_manifest,
                }
            )
    return jsonify({'videos': videos, 'total': len(videos)})


@bp.route('/api/storyteller/episodes')
def api_storyteller_episodes():
    """2026-07-24: list finished storyteller episodes in the Asset Manager
    (they were invisible — the videos list only matched pipeline_*_state.json,
    while storyteller jobs write storyteller_*_state.json)."""
    # 2026-07-25: storyteller now writes to output/storyteller/; scan it PLUS
    # output/clips (backward-compat for episodes produced before the split).
    _out_base = os.path.dirname(_RUNTIME_DIR)
    _roots = [os.path.join(_out_base, 'output', 'storyteller'), os.path.join(_out_base, 'output', 'clips')]
    episodes = []
    _seen_pids = set()
    for clips_dir in _roots:
        if not os.path.isdir(clips_dir):
            continue
        for pid in sorted(os.listdir(clips_dir), reverse=True):
            if pid in _seen_pids:
                continue
            pd_path = os.path.join(clips_dir, pid)
            if not os.path.isdir(pd_path):
                continue
            state_file = _runtime_path(f'storyteller_{pid}_state.json')
            if not os.path.exists(state_file):
                continue
            _seen_pids.add(pid)
            try:
                with open(state_file) as _sf:
                    state = json.load(_sf)
            except (OSError, ValueError) as _exc:
                _zyg_log.warning('storyteller state unreadable for %s, skipping the episode: %s', pid, _exc)
                continue
            vid_path = state.get('video_path', '')
            if not vid_path or not os.path.exists(vid_path):
                _cands = sorted(
                    [os.path.join(pd_path, f) for f in os.listdir(pd_path) if f.endswith('_final.mp4')],
                    key=lambda q: os.path.getsize(q) if os.path.exists(q) else 0,
                    reverse=True,
                )
                vid_path = _cands[0] if _cands else ''
            if not (vid_path and os.path.exists(vid_path) and os.path.getsize(vid_path) > 1000):
                continue
            _bible = state.get('character_bible') or {}
            _fb = state.get('_st_fallback_scenes') or []
            _drift = state.get('_st_identity_drift_scenes') or []
            _issues = []
            # 2026-07-24: audio-loss visibility — run 6278904c listed a fully
            # SILENT 600s episode with no audio-related issue at all.
            if state.get('narration_missing'):
                _issues.append('NO AUDIO (all TTS engines failed)')
            if state.get('narration_truncated'):
                _issues.append('narration truncated')
            if state.get('narration_voice_fallback'):
                _issues.append('Chatterbox fallback voice (IndexTTS-2 primary failed)')
            if _fb:
                _issues.append(f'{len(_fb)} fallback frame(s)')
            if _drift:
                _issues.append(f'{len(_drift)} identity-drift frame(s)')
            _rescued = state.get('_st_rescued_scenes') or []
            if _rescued:
                _issues.append(f'{len(_rescued)} rescued frame(s)')
            _dupes = state.get('_st_duplicate_scenes') or []
            if _dupes:
                _issues.append(f'{len(_dupes)} duplicate frame(s)')
            _handflag = state.get('_st_hand_flagged_scenes') or []
            if _handflag:
                _issues.append(f'{len(_handflag)} minor hand imperfection(s)')
            episodes.append(
                {
                    'pipeline_id': pid,
                    'title': state.get('story_title') or state.get('story_prompt', '')[:80],
                    'char_id': state.get('char_id', ''),
                    'character': (_bible.get('display_name') or _bible.get('name') or state.get('char_id', '')),
                    'duration_s': state.get('tts_duration', 0),
                    'created': state.get('started', ''),
                    'filesize': os.path.getsize(vid_path),
                    'filename': os.path.basename(vid_path),
                    'model_family': state.get('model_family', ''),
                    'issues': _issues,
                    'quality': 'degraded' if _issues else 'good',
                }
            )
    return jsonify({'episodes': episodes, 'total': len(episodes)})


@bp.route('/api/storyteller/episodes/<pipeline_id>/video')
def api_storyteller_episode_video(pipeline_id):
    """Stream/download a storyteller episode video (session-authenticated)."""
    # 2026-07-25: storyteller episodes live under output/storyteller/ (new) or
    # output/clips/ (pre-split). Allow both roots for lookup + path validation.
    _out_base = os.path.dirname(_RUNTIME_DIR)
    _clips_roots = [
        os.path.realpath(os.path.join(_out_base, 'output', 'storyteller')),
        os.path.realpath(os.path.join(_out_base, 'output', 'clips')),
    ]
    state_file = _runtime_path(f'storyteller_{pipeline_id}_state.json')
    vid_path = ''
    if os.path.exists(state_file):
        try:
            with open(state_file) as _sf:
                vid_path = json.load(_sf).get('video_path', '') or ''
        except Exception:
            vid_path = ''
    if not (vid_path and os.path.exists(vid_path)):
        for _root in _clips_roots:
            pd_path = os.path.join(_root, pipeline_id)
            if os.path.isdir(pd_path):
                _cands = sorted(
                    [os.path.join(pd_path, f) for f in os.listdir(pd_path) if f.endswith('_final.mp4')],
                    key=lambda q: os.path.getsize(q) if os.path.exists(q) else 0,
                    reverse=True,
                )
                if _cands:
                    vid_path = _cands[0]
                    break
    real = os.path.realpath(vid_path) if vid_path else ''
    if not (real and any(real.startswith(_r + os.sep) for _r in _clips_roots) and os.path.isfile(real)):
        return jsonify({'error': 'episode video not found'}), 404
    return send_file(
        real,
        mimetype='video/mp4',
        conditional=True,
        download_name=os.path.basename(real),
        as_attachment=request.args.get('download') == '1',
    )
