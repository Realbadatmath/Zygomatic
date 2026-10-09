# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Creator Nexus marketing upload endpoint.

Moved verbatim out of bp_assets_media.py (original lines 1377-1669).
"""

import json
import os
import subprocess

from flask import jsonify, request

from zyg_dashboard.cors import apply_cors
from zyg_dashboard.gui.runtime_state import _RUNTIME_DIR
from zyg_dashboard.gui.timeutil import _ams_now
from zyg_workflows.bin import exe

from zyg_dashboard.bp_assets_media.base import (
    _YT_UPLOAD_SCRIPT,
    _YT_VENV_PYTHON,
    _agent_log,
    _zyg_log,
    bp,
)
from zyg_dashboard.bp_assets_media.marketing import _mkt_is_dismissed, _mkt_load_dismissed


@bp.route('/api/marketing/upload', methods=['POST', 'OPTIONS'])
def api_marketing_upload():
    """Trigger a YouTube upload for a produced episode (called by Creator Nexus batch trigger)."""
    if request.method == 'OPTIONS':
        resp = jsonify({})
        apply_cors(resp, request)
        resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return resp

    data = request.get_json(silent=True) or {}
    filename = data.get('filename', '').strip()
    pipeline_id = data.get('pipeline_id', '').strip()
    title = data.get('title') or filename
    description = data.get('description') or ''
    tags = ','.join(data.get('tags') or [])
    category = str(data.get('category') or 27)
    privacy = data.get('privacy') or 'private'
    air_slot = data.get('air_slot', '').strip()  # e.g. "20:00" AMS

    if not filename:
        resp = jsonify({'success': False, 'error': 'filename required'})
        apply_cors(resp, request)
        return resp, 400

    # ── Dismissal gate ────────────────────────────────────────────────────
    # Checked FIRST, before any file resolution or upload work: a browser tab
    # opened before the dismissal still holds the episode in its in-memory batch
    # queue and will call this endpoint at its slot. Refusing here is what makes
    # "Dismiss" actually stop the upload rather than just hide a card.
    _dismissed_now = _mkt_load_dismissed()
    if _mkt_is_dismissed(_dismissed_now, filename, data.get('size')):
        _agent_log(
            'WARNING',
            'MARKETING',
            pipeline_id or 'marketing',
            'Upload',
            f'Upload BLOCKED — episode was dismissed: {filename}',
        )
        resp = jsonify({'success': False, 'dismissed': True, 'error': 'Episode was dismissed — upload refused'})
        apply_cors(resp, request)
        return resp, 409

    # 2026-07-25: each pipeline now writes to its OWN output folder (documentary→clips,
    # crime→crime, clipfarm→clipfarm, storyteller→storyteller). Resolve the video
    # across all roots — output/clips FIRST so documentary uploads and the ~27 legacy
    # crime videos still sitting in output/clips resolve byte-for-byte unchanged. The
    # resolved root is reused below for thumbnail / flux / caption lookup.
    _out_base = os.path.dirname(_RUNTIME_DIR)
    _upload_roots = [
        os.path.join(_out_base, 'output', _d)
        for _d in ('clips', 'crime', 'clipfarm', 'storyteller', 'remix', 'stocks', 'crypto', 'tokitoki', 'arena')
    ]
    clips_dir = _upload_roots[0]
    file_path = ''
    for _root in _upload_roots:
        _cand = os.path.join(_root, pipeline_id, filename) if pipeline_id else os.path.join(_root, filename)
        if os.path.exists(_cand):
            file_path = _cand
            clips_dir = _root
            break
    if not file_path and pipeline_id:
        # 2026-08-06: the betting departments nest one level deeper —
        # output/<channel>/<category>/<job>/ — so a sub-channel episode is not
        # found by the flat <root>/<job>/ probe above.
        import glob as _g_sub

        for _root in _upload_roots:
            _hits = _g_sub.glob(os.path.join(_root, '*', pipeline_id, filename))
            if _hits:
                file_path = _hits[0]
                clips_dir = _root
                break

    if not file_path:
        # Preserve the pre-split error shape (points at output/clips) for callers.
        file_path = os.path.join(clips_dir, pipeline_id, filename) if pipeline_id else os.path.join(clips_dir, filename)
        resp = jsonify({'success': False, 'error': f'File not found: {file_path}'})
        apply_cors(resp, request)
        return resp, 404

    # Second pass on the real byte size — the caller may not have sent one, and
    # the board's key is filename||size.
    try:
        _size_on_disk = os.path.getsize(file_path)
    except OSError:
        _size_on_disk = None
    if _size_on_disk is not None and _mkt_is_dismissed(_dismissed_now, filename, _size_on_disk):
        _agent_log(
            'WARNING',
            'MARKETING',
            pipeline_id or 'marketing',
            'Upload',
            f'Upload BLOCKED — episode was dismissed: {filename}',
        )
        resp = jsonify({'success': False, 'dismissed': True, 'error': 'Episode was dismissed — upload refused'})
        apply_cors(resp, request)
        return resp, 409

    # ── Compute publishAt — prefer explicit full ISO datetime from batch schedule ──
    publish_at = ''
    publish_at_direct = data.get('publish_at', '').strip()  # full ISO from batch schedule
    if publish_at_direct:
        publish_at = publish_at_direct  # already an exact datetime; use as-is
    elif air_slot:
        try:
            from datetime import timedelta

            _now = _ams_now()
            _ah, _am = map(int, air_slot.split(':'))
            _pub_dt = _now.replace(hour=_ah, minute=_am, second=0, microsecond=0)
            if _pub_dt <= _now:
                _pub_dt += timedelta(days=1)
            publish_at = _pub_dt.isoformat(timespec='seconds')
        except Exception as _exc:
            _zyg_log.warning('air slot %r could not be parsed, no publish time is set: %s', air_slot, _exc)

    # ── Read pipeline state for enriched YouTube metadata ─────────────────
    yt_language = 'en'
    yt_audience = 'general'
    recording_date = ''
    if pipeline_id:
        _st_path = os.path.join(_RUNTIME_DIR, f'pipeline_{pipeline_id}_state.json')
        if os.path.exists(_st_path):
            try:
                with open(_st_path) as _sf:
                    _ps_data = json.load(_sf)
                yt_language = _ps_data.get('youtube_language', 'en') or 'en'
                yt_audience = _ps_data.get('youtube_audience', 'general') or 'general'
                recording_date = (_ps_data.get('started', '') or '')[:10]
                if not tags:
                    _state_tags = _ps_data.get('youtube_tags', [])
                    if _state_tags:
                        tags = ','.join(str(t) for t in _state_tags)
            except (OSError, ValueError) as _exc:
                _zyg_log.warning('pipeline state unreadable, youtube metadata falls back to defaults: %s', _exc)

    # ── Find best thumbnail ────────────────────────────────────────────────
    # Priority: _thumbnail.jpg in pipeline dir → manifest-ranked FLUX image →
    #           first FLUX image alphabetically → FFmpeg frame at 10% duration.
    _EMOTION_PRIORITY = {
        'climax': 6,
        'shock': 6,
        'awe': 5,
        'fear': 5,
        'tension': 4,
        'dread': 4,
        'anger': 4,
        'excitement': 4,
        'mystery': 3,
        'wonder': 3,
        'surprise': 3,
        'suspense': 3,
        'hope': 2,
        'joy': 2,
        'sadness': 2,
        'melancholy': 2,
        'calm': 1,
        'neutral': 1,
        'peaceful': 1,
    }
    thumbnail_path = ''
    if pipeline_id:
        _direct_thumb = os.path.join(clips_dir, pipeline_id, '_thumbnail.jpg')
        if os.path.exists(_direct_thumb):
            thumbnail_path = _direct_thumb
    if pipeline_id and not thumbnail_path:
        _flux_dir = os.path.join(clips_dir, pipeline_id, 'flux_images')
        if os.path.isdir(_flux_dir):
            _manifest_p = os.path.join(_flux_dir, 'flux_manifest.json')
            _picked = ''
            if os.path.isfile(_manifest_p):
                try:
                    with open(_manifest_p) as _mf:
                        _manifest = json.load(_mf)
                    _candidates = []
                    for _entry in _manifest.get('images', []):
                        _p = _entry.get('path', '')
                        if not _p or not os.path.isfile(_p):
                            continue
                        if '_4x' in os.path.basename(_p):
                            continue
                        _emotion = str(_entry.get('emotion', 'calm')).lower()
                        _ep = _EMOTION_PRIORITY.get(_emotion, 1)
                        _qa = float(_entry.get('qa_score', 0.5))
                        _candidates.append((_ep + _qa, _p))
                    if _candidates:
                        _candidates.sort(key=lambda x: x[0], reverse=True)
                        _picked = _candidates[0][1]
                except Exception as _exc:
                    _zyg_log.debug('manifest-ranked thumbnail pick failed, falling back to directory order: %s', _exc)
            if not _picked:
                for _img in sorted(os.listdir(_flux_dir)):
                    if _img.endswith('.jpg') and '_4x' not in _img:
                        _picked = os.path.join(_flux_dir, _img)
                        break
            thumbnail_path = _picked
        if not thumbnail_path:
            try:
                _probe = subprocess.run(
                    [
                        exe('ffprobe'),
                        '-v',
                        'error',
                        '-show_entries',
                        'format=duration',
                        '-of',
                        'default=noprint_wrappers=1:nokey=1',
                        file_path,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                _dur = float(_probe.stdout.strip())
                _t = max(1, int(_dur * 0.1))
                _thumb_out = os.path.join(clips_dir, pipeline_id, '_thumbnail.jpg')
                subprocess.run(
                    [exe('ffmpeg'), '-y', '-ss', str(_t), '-i', file_path, '-vframes', '1', '-q:v', '2', _thumb_out],
                    capture_output=True,
                    timeout=30,
                )
                if os.path.exists(_thumb_out):
                    thumbnail_path = _thumb_out
            except Exception as _exc:
                _zyg_log.warning(
                    'ffmpeg thumbnail extraction failed, continuing without a generated thumbnail: %s', _exc
                )

    # SRT captions — same basename as video file
    caption_path = os.path.splitext(file_path)[0] + '.srt'
    if not os.path.exists(caption_path):
        caption_path = ''

    cmd = [
        _YT_VENV_PYTHON,
        _YT_UPLOAD_SCRIPT,
        '--file',
        file_path,
        '--title',
        title,
        '--description',
        description,
        '--tags',
        tags,
        '--category',
        category,
        '--privacy',
        privacy,
        '--language',
        yt_language,
        '--audience',
        yt_audience,
    ]
    if publish_at:
        cmd += ['--publish-at', publish_at]
    if thumbnail_path:
        cmd += ['--thumbnail', thumbnail_path]
    if caption_path:
        cmd += ['--caption-file', caption_path]
    if recording_date:
        cmd += ['--recording-date', recording_date]
    _yt_playlist = os.environ.get('YT_PLAYLIST_ID', '')
    if _yt_playlist:
        cmd += ['--playlist-id', _yt_playlist]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode == 0:
            video_id = None
            for line in result.stdout.splitlines():
                if 'Video ID:' in line:
                    video_id = line.split('Video ID:')[-1].strip()
                    break
            resp = jsonify(
                {
                    'success': True,
                    'video_id': video_id,
                    'url': f'https://www.youtube.com/watch?v={video_id}' if video_id else None,
                    'publish_at': publish_at or None,
                    'thumbnail': os.path.basename(thumbnail_path) if thumbnail_path else None,
                    'captions': os.path.basename(caption_path) if caption_path else None,
                }
            )
        else:
            resp = jsonify({'success': False, 'error': (result.stderr or result.stdout).strip()})
    except subprocess.TimeoutExpired:
        resp = jsonify({'success': False, 'error': 'Upload timed out (10 min limit)'})
    except Exception as exc:
        resp = jsonify({'success': False, 'error': str(exc)})

    apply_cors(resp, request)
    return resp
