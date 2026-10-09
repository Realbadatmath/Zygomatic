# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Marketing dismissals, the 24 h new-video scan and the YouTube channel listing.

Moved verbatim out of bp_assets_media.py (original lines 1007-1374).
"""

import json
import os
import threading
import time

from flask import jsonify, request

from zyg_dashboard.cors import apply_cors
from zyg_dashboard.gui.runtime_state import _RUNTIME_DIR, _runtime_path
from zyg_dashboard.gui.timeutil import _ams_now

from zyg_dashboard.bp_assets_media.base import (
    _YT_TOKEN_FILE,
    _agent_log,
    _zero_claim_batch_slot,
    _zyg_log,
    bp,
)


# ── Marketing dismissals ──────────────────────────────────────────────────────
# A video the user dismisses on the Creator Nexus marketing board must never be
# uploaded. That board is a static frontend whose queue lives in localStorage, so
# a dismissal recorded only there is invisible to every other tab/browser and
# cannot stop an upload the scanner already queued. The authoritative list lives
# here: the scanner hides dismissed files, and the upload endpoint refuses them
# even if a stale tab still fires its batch trigger.
_MKT_DISMISS_PATH = os.path.join(_RUNTIME_DIR, 'marketing_dismissed.json')
_MKT_DISMISS_LOCK = threading.Lock()


def _mkt_ep_key(filename, size):
    """Same episode key the Creator Nexus board uses: filename||size."""
    return f'{filename}||{size}'


def _mkt_load_dismissed():
    try:
        with open(_MKT_DISMISS_PATH) as _f:
            _d = json.load(_f)
        return _d if isinstance(_d, dict) else {}
    except Exception:
        return {}


def _mkt_save_dismissed(entries):
    _tmp = _MKT_DISMISS_PATH + '.tmp'
    with open(_tmp, 'w', encoding='utf-8') as _f:
        json.dump(entries, _f, indent=2)
    os.replace(_tmp, _MKT_DISMISS_PATH)


def _mkt_is_dismissed(entries, filename, size=None):
    """Match on the exact filename||size key, and on the filename alone — a
    re-encode changes the byte size but it is still the episode the user killed.
    """
    if size is not None and _mkt_ep_key(filename, size) in entries:
        return True
    for _e in entries.values():
        if isinstance(_e, dict) and _e.get('filename') == filename:
            return True
    return False


def _mkt_cors(resp):
    apply_cors(resp, request)
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return resp


@bp.route('/api/marketing/dismissed', methods=['GET', 'OPTIONS'])
def api_marketing_dismissed():
    """List every dismissed episode key (polled by the board so a dismissal made
    in one tab propagates to all the others)."""
    if request.method == 'OPTIONS':
        return _mkt_cors(jsonify({}))
    _d = _mkt_load_dismissed()
    return _mkt_cors(jsonify({'success': True, 'dismissed': sorted(_d.keys()), 'entries': _d, 'total': len(_d)}))


@bp.route('/api/marketing/dismiss', methods=['POST', 'OPTIONS'])
def api_marketing_dismiss():
    """Permanently drop an episode from the marketing pipeline."""
    if request.method == 'OPTIONS':
        return _mkt_cors(jsonify({}))
    data = request.get_json(silent=True) or {}
    filename = (data.get('filename') or '').strip()
    if not filename:
        return _mkt_cors(jsonify({'success': False, 'error': 'filename required'})), 400
    size = data.get('size')
    key = (data.get('key') or '').strip() or _mkt_ep_key(filename, size if size is not None else '')
    with _MKT_DISMISS_LOCK:
        _d = _mkt_load_dismissed()
        _d[key] = {
            'filename': filename,
            'size': size,
            'pipeline_id': (data.get('pipeline_id') or '').strip(),
            'title': (data.get('title') or '').strip(),
            'at': _ams_now().isoformat(timespec='seconds'),
        }
        _mkt_save_dismissed(_d)
    _agent_log(
        'INFO',
        'MARKETING',
        _d[key].get('pipeline_id') or 'marketing',
        'Dismiss',
        f'Dismissed (will not upload): {filename}',
    )
    return _mkt_cors(jsonify({'success': True, 'key': key, 'total': len(_d)}))


@bp.route('/api/marketing/undismiss', methods=['POST', 'OPTIONS'])
def api_marketing_undismiss():
    """Undo a dismissal — the file becomes eligible for the scanner again."""
    if request.method == 'OPTIONS':
        return _mkt_cors(jsonify({}))
    data = request.get_json(silent=True) or {}
    key = (data.get('key') or '').strip()
    filename = (data.get('filename') or '').strip()
    with _MKT_DISMISS_LOCK:
        _d = _mkt_load_dismissed()
        _remove = [
            _k
            for _k, _e in _d.items()
            if _k == key or (filename and isinstance(_e, dict) and _e.get('filename') == filename)
        ]
        for _k in _remove:
            _d.pop(_k, None)
        if _remove:
            _mkt_save_dismissed(_d)
    return _mkt_cors(jsonify({'success': True, 'restored': _remove, 'total': len(_d)}))


@bp.route('/api/output/new-videos')
def api_output_new_videos():
    """Return .mp4 files produced in the last 24 hours across all pipeline runs.
    Used by Creator Nexus Stage 1 auto-scan (polls every 10 s).
    """
    clips_dir = os.path.join(os.path.dirname(_RUNTIME_DIR), 'output', 'clips')
    _dismissed = _mkt_load_dismissed()
    _now = time.time()
    cutoff_old = _now - 86400  # 24 h ago  — files older than this are stale
    cutoff_new = _now - 2700  # 45 min ago — files newer than this may still be encoding
    # Suffixes that indicate intermediate/non-final files
    _SKIP_SUFFIXES = (
        '_slideshow.mp4',
        '_subtitled.mp4',
        '_with_intro.mp4',
        '_audio.mp4',
        '_norm.mp4',
        '_nosub.mp4',
        '_raw.mp4',
        '_intro.mp4',
        '_outro.mp4',
        '_fx_outro.mp4',
        '_graded.mp4',
    )
    videos = []
    if not os.path.isdir(clips_dir):
        return jsonify({'videos': [], 'scanned': clips_dir, 'error': 'clips dir missing'})
    try:
        for pid in os.listdir(clips_dir):
            pd_path = os.path.join(clips_dir, pid)
            if not os.path.isdir(pd_path):
                continue
            # 2026-07-25: the documentary auto-uploader must ONLY pick up
            # DOCUMENTARY videos. Other pipelines historically shared this dir
            # (storyteller, crime), so their finished videos were being pushed
            # to the documentary channel. Skip anything that isn't documentary:
            #  - storyteller runs write storyteller_<pid>_state.json
            #  - crime/other pipeline_<pid>_state.json carry a non-documentary department
            if os.path.exists(_runtime_path(f'storyteller_{pid}_state.json')):
                continue
            _dept_state = _runtime_path(f'pipeline_{pid}_state.json')
            if os.path.exists(_dept_state):
                try:
                    with open(_dept_state) as _dsf:
                        _dep = (json.load(_dsf).get('department') or '').strip().lower()
                    if _dep and _dep not in ('scholarly', 'documentary'):
                        continue
                except (OSError, ValueError) as _exc:
                    _zyg_log.warning(
                        'department state unreadable for %s, keeping it in the list unfiltered: %s', pid, _exc
                    )
            for fname in os.listdir(pd_path):
                if not fname.endswith('.mp4'):
                    continue
                if any(fname.endswith(s) for s in _SKIP_SUFFIXES):
                    continue
                fpath = os.path.join(pd_path, fname)
                try:
                    st = os.stat(fpath)
                except OSError as _exc:
                    _zyg_log.debug('skipping video with unreadable stat: %s', _exc)
                    continue
                # Dismissed by the user — never re-surface it, or the board
                # re-queues it on the very next 10 s scan.
                if _mkt_is_dismissed(_dismissed, fname, st.st_size):
                    continue
                # Only surface files that finished encoding 45 min–24 h ago
                if st.st_mtime < cutoff_old or st.st_mtime > cutoff_new:
                    continue
                _yt_title = ''
                _yt_desc = ''
                _yt_tags = []
                _yt_language = 'en'
                _yt_audience = 'general'
                _yt_started = ''
                _scheduled_upload_at = ''
                _scheduled_publish_at = ''
                _state_path = os.path.join(_RUNTIME_DIR, f'pipeline_{pid}_state.json')
                if os.path.exists(_state_path):
                    try:
                        with open(_state_path) as _sf:
                            _ps = json.load(_sf)
                        _yt_title = _ps.get('youtube_title', '')
                        _yt_desc = _ps.get('youtube_description', '')
                        _yt_tags = _ps.get('youtube_tags', [])
                        _yt_language = _ps.get('youtube_language', 'en') or 'en'
                        _yt_audience = _ps.get('youtube_audience', 'general') or 'general'
                        _yt_started = _ps.get('started', '')
                        _scheduled_upload_at = _ps.get('scheduled_upload_at', '')
                        _scheduled_publish_at = _ps.get('scheduled_publish_at', '')
                    except (OSError, ValueError) as _exc:
                        _zyg_log.warning(
                            'pipeline state unreadable for %s, youtube metadata falls back to defaults: %s', pid, _exc
                        )
                # If not yet tagged, try to claim the next slot from the active batch schedule.
                if not _scheduled_publish_at:
                    _claimed = _zero_claim_batch_slot(pid)
                    if _claimed:
                        _scheduled_upload_at = _claimed.get('upload_at', '')
                        _scheduled_publish_at = _claimed.get('publish_at', '')
                videos.append(
                    {
                        'filename': fname,
                        'pipeline_id': pid,
                        'path': fpath,
                        'size': st.st_size,
                        'modified_ts': int(st.st_mtime * 1000),
                        'youtube_title': _yt_title,
                        'youtube_description': _yt_desc,
                        'youtube_tags': _yt_tags,
                        'youtube_language': _yt_language,
                        'youtube_audience': _yt_audience,
                        'started': _yt_started,
                        'scheduled_upload_at': _scheduled_upload_at,
                        'scheduled_publish_at': _scheduled_publish_at,
                    }
                )
    except Exception as exc:
        return jsonify({'videos': [], 'error': str(exc)})
    videos.sort(key=lambda v: v['modified_ts'], reverse=True)
    # `dismissed` rides along so the board can prune queue entries it already
    # holds — including ones dismissed from another tab or before a reload.
    resp = jsonify(
        {
            'videos': videos,
            'total': len(videos),
            'scanned': clips_dir,
            'dismissed': sorted(_dismissed.keys()),
            'dismissed_files': sorted(
                {_e.get('filename') for _e in _dismissed.values() if isinstance(_e, dict) and _e.get('filename')}
            ),
        }
    )
    apply_cors(resp, request)
    return resp


@bp.route('/api/youtube/channel-videos', methods=['GET', 'OPTIONS'])
def api_youtube_channel_videos():
    """Return the authenticated YouTube channel's video list with real stats."""
    if request.method == 'OPTIONS':
        resp = jsonify({})
        apply_cors(resp, request)
        resp.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return resp
    try:
        import pickle as _pk

        if not os.path.exists(_YT_TOKEN_FILE):
            resp = jsonify({'success': False, 'error': 'No YouTube token — run youtube/auth.py first'})
            apply_cors(resp, request)
            return resp
        with open(_YT_TOKEN_FILE, 'rb') as _tf:
            # The google-auth Credentials object has no JSON round-trip here; the file is written
            # by youtube/auth.py on this host and never leaves it.
            _creds = _pk.load(_tf)  # nosec B301  # noqa: S301  local credentials file written by youtube/auth.py
        if _creds.expired and _creds.refresh_token:
            from google.auth.transport.requests import Request as _GReq

            _creds.refresh(_GReq())
            with open(_YT_TOKEN_FILE, 'wb') as _tf:
                _pk.dump(_creds, _tf)
        from googleapiclient.discovery import build as _yt_build

        _yt = _yt_build('youtube', 'v3', credentials=_creds)

        # Channel info + uploads playlist ID + channel statistics (Creator Nexus Metrics tab)
        _ch_r = _yt.channels().list(part='contentDetails,snippet,statistics', mine=True).execute()
        _ch_list = _ch_r.get('items', [])
        if not _ch_list:
            resp = jsonify({'success': False, 'error': 'No authenticated YouTube channel found'})
            apply_cors(resp, request)
            return resp
        _uploads_id = _ch_list[0]['contentDetails']['relatedPlaylists']['uploads']
        _ch_title = _ch_list[0]['snippet']['title']
        _ch_id = _ch_list[0]['id']
        _ch_stats = _ch_list[0].get('statistics', {})

        # Collect video IDs from uploads playlist (up to 100)
        _vid_ids, _next = [], None
        for _ in range(2):
            _pl_r = (
                _yt.playlistItems()
                .list(
                    part='contentDetails',
                    playlistId=_uploads_id,
                    maxResults=50,
                    pageToken=_next,
                )
                .execute()
            )
            _vid_ids += [i['contentDetails']['videoId'] for i in _pl_r.get('items', [])]
            _next = _pl_r.get('nextPageToken')
            if not _next:
                break

        _videos = []
        for _i in range(0, len(_vid_ids), 50):
            _vr = (
                _yt.videos()
                .list(
                    part='snippet,statistics,status',
                    id=','.join(_vid_ids[_i : _i + 50]),
                )
                .execute()
            )
            for _v in _vr.get('items', []):
                _sn = _v.get('snippet', {})
                _st = _v.get('statistics', {})
                _thumbs = _sn.get('thumbnails', {})
                _th = (
                    _thumbs.get('maxres', {}).get('url')
                    or _thumbs.get('standard', {}).get('url')
                    or _thumbs.get('high', {}).get('url')
                    or _thumbs.get('medium', {}).get('url')
                    or _thumbs.get('default', {}).get('url')
                    or ''
                )
                _videos.append(
                    {
                        'id': _v['id'],
                        'title': _sn.get('title', ''),
                        'thumbnail': _th,
                        'publishedAt': _sn.get('publishedAt', ''),
                        'scheduledPublishAt': _v.get('status', {}).get('publishAt', ''),
                        'views': int(_st.get('viewCount', 0) or 0),
                        'likes': int(_st.get('likeCount', 0) or 0),
                        'comments': int(_st.get('commentCount', 0) or 0),
                        # dislikeCount is private since 2021 but still returned to the owner's token
                        'dislikes': int(_st.get('dislikeCount', 0) or 0),
                        'privacy': _v.get('status', {}).get('privacyStatus', 'private'),
                    }
                )
        _videos.sort(key=lambda x: x['publishedAt'], reverse=True)

        resp = jsonify(
            {
                'success': True,
                'channel': _ch_title,
                'channelId': _ch_id,
                'videos': _videos,
                'subscribers': int(_ch_stats.get('subscriberCount', 0) or 0),
                'subscribersHidden': bool(_ch_stats.get('hiddenSubscriberCount', False)),
                'channelViews': int(_ch_stats.get('viewCount', 0) or 0),
                'channelVideoCount': int(_ch_stats.get('videoCount', 0) or 0),
            }
        )
        apply_cors(resp, request)
        return resp
    except Exception as _e:
        resp = jsonify({'success': False, 'error': str(_e)})
        apply_cors(resp, request)
        return resp
