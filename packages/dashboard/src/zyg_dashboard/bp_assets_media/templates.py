# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Template store, template outputs and their thumbnails.

Moved verbatim out of bp_assets_media.py (original lines 1873-2036).
"""

import json
import os
import re
import time
from datetime import datetime

from flask import jsonify, request, send_from_directory


from zyg_dashboard import paths

from zyg_dashboard.bp_assets_media.base import (
    _CLIPS_OUTPUT_DIR,
    _TSTORE_FILE,
    bp,
    limiter,
)


def _tstore_read():
    try:
        with open(_TSTORE_FILE) as _f:
            return json.load(_f)
    except Exception:
        return {'templates': []}


def _tstore_write(data):
    os.makedirs(os.path.dirname(_TSTORE_FILE), exist_ok=True)
    with open(_TSTORE_FILE, 'w') as _f:
        json.dump(data, _f, indent=2)


@bp.route('/api/templates/list')
def api_templates_list():
    return jsonify(_tstore_read())


@bp.route('/api/templates/store', methods=['POST'])
def api_templates_store():
    body = request.get_json(silent=True) or {}
    store = _tstore_read()
    entry = {
        'id': body.get('id') or f'tmpl_{int(time.time())}',
        'name': body.get('name', 'Unnamed Template'),
        'type': body.get('type', 'template'),
        'category': body.get('category', 'TEMPLATE'),
        'sport': body.get('sport'),
        'date': body.get('date'),
        'matches': body.get('matches'),
        'video_path': body.get('video_path'),
        'size_mb': body.get('size_mb'),
        'created_at': body.get('created_at') or datetime.utcnow().isoformat() + 'Z',
        'thumbnail': body.get('thumbnail'),
    }
    store['templates'] = [t for t in store.get('templates', []) if t.get('id') != entry['id']]
    store['templates'].insert(0, entry)
    _tstore_write(store)
    return jsonify({'ok': True, 'id': entry['id']})


@bp.route('/api/templates/delete/<tmpl_id>', methods=['DELETE'])
def api_templates_delete(tmpl_id):
    store = _tstore_read()
    store['templates'] = [t for t in store.get('templates', []) if t.get('id') != tmpl_id]
    _tstore_write(store)
    return jsonify({'ok': True})


def _parse_clip_yaml(clip_path):
    try:
        yamls = [f for f in os.listdir(clip_path) if f.endswith('.yaml')]
        if not yamls:
            return {}
        import yaml as _yaml

        with open(os.path.join(clip_path, yamls[0])) as _f:
            return _yaml.safe_load(_f) or {}
    except Exception:
        return {}


@bp.route('/api/templates/outputs')
@limiter.exempt
def api_templates_outputs():
    # 2026-07-25: crime/clipfarm moved to their own output folders; scan all video
    # roots (documentary output/clips FIRST) so the crime/clipfarm category branches
    # below keep listing — both new runs under output/crime|clipfarm AND legacy runs
    # still sitting in output/clips. Deduped by clip_id, first root wins.
    _tpl_base = os.path.dirname(_CLIPS_OUTPUT_DIR)
    _tpl_roots = [_CLIPS_OUTPUT_DIR, os.path.join(_tpl_base, 'crime'), os.path.join(_tpl_base, 'clipfarm')]
    _clip_dirs = []  # [(clip_id, clip_path)] deduped
    _seen_ids = set()
    for _root in _tpl_roots:
        if not os.path.isdir(_root):
            continue
        for _cid in os.listdir(_root):
            if _cid in _seen_ids:
                continue
            if not re.match(r'^[0-9a-f\-]+$', _cid):
                continue
            _cp = os.path.join(_root, _cid)
            if not os.path.isdir(_cp):
                continue
            _seen_ids.add(_cid)
            _clip_dirs.append((_cid, _cp))
    results = []
    for clip_id, clip_path in _clip_dirs:
        # Find first non-4x flux thumbnail
        flux_dir = os.path.join(clip_path, 'flux_images')
        thumb = None
        if os.path.isdir(flux_dir):
            imgs = sorted([f for f in os.listdir(flux_dir) if f.lower().endswith('.jpg') and '4x' not in f])
            if imgs:
                thumb = imgs[0]
        # Find video
        videos = [f for f in os.listdir(clip_path) if f.lower().endswith('.mp4')]
        # Skip empty / in-progress folders (no image and no video)
        if thumb is None and not videos:
            continue
        # Parse YAML metadata
        meta = _parse_clip_yaml(clip_path)
        subject = (meta.get('semantic') or {}).get('subject', '')
        tags = (meta.get('metadata') or {}).get('tags', [])
        dur = (meta.get('metadata') or {}).get('duration', 0) or 0
        ts = (meta.get('metadata') or {}).get('timestamp', '')
        # Derive title from video filename if no YAML subject
        if not subject and videos:
            subject = videos[0].replace('.mp4', '').replace('_', ' ')
        # Derive category from tags
        cat = 'general'
        tag_set = {t.lower() for t in (tags or [])}
        if 'scholarly' in tag_set:
            cat = 'scholarly'
        elif 'crime' in tag_set:
            cat = 'crime'
        elif 'clipfarm' in tag_set or 'clip' in tag_set:
            cat = 'clipfarm'
        results.append(
            {
                'id': clip_id,
                'subject': subject or clip_id[:8],
                'tags': tags or [],
                'category': cat,
                'duration': round(dur),
                'timestamp': ts,
                'thumb': thumb,
                'has_video': bool(videos),
                'video': videos[0] if videos else None,
            }
        )
    results.sort(key=lambda r: r['timestamp'] or '', reverse=True)
    return jsonify({'outputs': results, 'total': len(results)})


@bp.route('/api/templates/thumb/<clip_id>/<fname>')
@limiter.exempt
def api_templates_thumb(clip_id, fname):
    if not re.match(r'^[0-9a-f\-]+$', clip_id):
        from flask import abort as _abort

        return _abort(400)
    if not re.match(r'^[\w\.\-]+$', fname):
        from flask import abort as _abort

        return _abort(400)
    # 2026-07-25: resolve the clip across all video roots (documentary output/clips
    # first, then crime/clipfarm) so thumbnails for moved crime/clipfarm clips render.
    _tpl_base = os.path.dirname(_CLIPS_OUTPUT_DIR)
    for _root in (_CLIPS_OUTPUT_DIR, os.path.join(_tpl_base, 'crime'), os.path.join(_tpl_base, 'clipfarm')):
        flux_dir = os.path.join(_root, clip_id, 'flux_images')
        if os.path.isfile(os.path.join(flux_dir, fname)):
            return send_from_directory(flux_dir, fname)
    from flask import abort as _abort

    return _abort(404)


@bp.route('/asset_manager/templates_board')
def asset_manager_templates_board():
    return send_from_directory(str(paths.TEMPLATES_DIR), 'asset_manager_templates_board.html')
