# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Environments / effects / wardrobe / asset-library browsing and previews.

Moved verbatim out of bp_assets_media.py (original lines 709-1004).
"""

import os

from flask import jsonify, request, send_file


from zyg_dashboard import paths

from zyg_dashboard.bp_assets_media.base import (
    _main_mod,
    _zyg_log,
    bp,
)


# ── Environments / Effects assets (output/<dept>/<pid>/*.png|mp4) ─────────────
# pipeline_envfx_runner writes to <crews>/output (module-relative), NOT <crews>/data/output
# (the storyteller/clips root). Using dirname(_RUNTIME_DIR) here scanned the wrong tree and
# left every Generated board empty (2026-07-29 review fix).
_ENVFX_OUT_BASE = str(paths.PKG_DIR)


def _envfx_scan(dept):
    """List env/fx assets by scanning output/<dept>/<pid>/ (no state.json — the runner
    only keeps an in-memory job; cross-ref _workflow_jobs for directive/status)."""
    root = os.path.join(_ENVFX_OUT_BASE, 'output', dept)
    items = []
    if not os.path.isdir(root):
        return items
    _jobs = getattr(_main_mod, '_workflow_jobs', {}) or {}
    for pid in os.listdir(root):
        if pid.startswith('_'):
            continue  # e.g. _previews (wardrobe outfit thumbnails) — not a job result
        pdir = os.path.join(root, pid)
        if not os.path.isdir(pdir):
            continue
        job = _jobs.get(pid) or {}
        for fn in os.listdir(pdir):
            if fn.startswith(('_', '.')):
                continue
            ext = os.path.splitext(fn)[1].lower()
            if ext not in ('.png', '.jpg', '.jpeg', '.mp4'):
                continue
            fp = os.path.join(pdir, fn)
            try:
                sz = os.path.getsize(fp)
                mt = os.path.getmtime(fp)
            except OSError as _exc:
                _zyg_log.debug('skipping asset with unreadable size/mtime: %s', _exc)
                continue
            items.append(
                {
                    'pipeline_id': pid,
                    'name': fn,
                    'kind': 'video' if ext == '.mp4' else 'image',
                    'render_mode': job.get('render_mode', ''),
                    'directive': (job.get('directive') or '')[:140],
                    'status': job.get('status', ''),
                    'filesize': sz,
                    'mtime': round(mt, 1),
                    'url': f'/api/envfx/media?dept={dept}&pid={pid}&name={fn}',
                }
            )
    items.sort(key=lambda x: x['mtime'], reverse=True)
    return items


@bp.route('/api/environments/list')
def api_environments_list():
    return jsonify({'items': _envfx_scan('environments'), 'total': len(_envfx_scan('environments'))})


@bp.route('/api/effects/list')
def api_effects_list():
    _it = _envfx_scan('effects')
    return jsonify({'items': _it, 'total': len(_it)})


@bp.route('/api/wardrobe/list')
def api_wardrobe_list():
    _it = _envfx_scan('wardrobe')
    return jsonify({'items': _it, 'total': len(_it)})


@bp.route('/api/wardrobe/outfits')
def api_wardrobe_outfits():
    """The shared preset wardrobe library (character-agnostic outfits) + preview availability."""
    try:
        from zyg_workflows import wardrobe_service as _wd

        outfits = _wd.load_wardrobe()
        for o in outfits:
            o['has_preview'] = _wd.has_preview(o.get('id'))
        return jsonify({'outfits': outfits})
    except Exception as e:
        return jsonify({'outfits': [], 'error': str(e)[:120]}), 200


@bp.route('/api/wardrobe/preview')
def api_wardrobe_preview():
    """Serve an outfit's card preview image."""
    oid = (request.args.get('id') or '').strip()
    if not oid or any(t in oid for t in ('/', '\\', '..')):
        return jsonify({'error': 'bad id'}), 400
    try:
        from zyg_workflows import wardrobe_service as _wd

        fp = _wd.preview_path(oid)
    except Exception:
        return jsonify({'error': 'unavailable'}), 500
    if not os.path.isfile(fp):
        return jsonify({'error': 'no preview'}), 404
    return send_file(fp, mimetype='image/png', conditional=True)


@bp.route('/api/wardrobe/delete', methods=['POST'])
def api_wardrobe_delete():
    """Delete an outfit from the shared library."""
    data = request.get_json(silent=True) or {}
    oid = (data.get('id') or request.args.get('id') or '').strip()
    if not oid:
        return jsonify({'error': 'id required'}), 400
    try:
        from zyg_workflows import wardrobe_service as _wd

        _wd.remove_outfit(oid)
        # also drop its cached preview
        try:
            _pp = _wd.preview_path(oid)
            if os.path.isfile(_pp):
                os.remove(_pp)
        except OSError as _exc:
            _zyg_log.debug('cached outfit preview removal skipped: %s', _exc)
        return jsonify({'ok': True, 'id': oid})
    except Exception as e:
        return jsonify({'error': str(e)[:120]}), 500


@bp.route('/api/effects/library')
def api_effects_library():
    """The shared effects library (character-agnostic presets) + preview availability + kind."""
    try:
        from zyg_workflows import effects_service as _fx

        effects = _fx.load_effects()
        for e in effects:
            e['has_preview'] = _fx.has_preview(e.get('id'))
        return jsonify({'effects': effects})
    except Exception as e:
        return jsonify({'effects': [], 'error': str(e)[:120]}), 200


@bp.route('/api/effects/preview')
def api_effects_preview():
    """Serve an effect's card preview — a still (.png) for 2D, a short clip (.mp4) for 3D."""
    eid = (request.args.get('id') or '').strip()
    if not eid or any(t in eid for t in ('/', '\\', '..')):
        return jsonify({'error': 'bad id'}), 400
    try:
        from zyg_workflows import effects_service as _fx

        fp = _fx.preview_path(eid)
    except Exception:
        return jsonify({'error': 'unavailable'}), 500
    if not os.path.isfile(fp):
        return jsonify({'error': 'no preview'}), 404
    if os.path.splitext(fp)[1].lower() == '.mp4':
        return send_file(fp, mimetype='video/mp4', conditional=True)
    return send_file(fp, mimetype='image/png', conditional=True)


@bp.route('/api/effects/delete', methods=['POST'])
def api_effects_delete():
    """Delete an effect preset from the shared library."""
    data = request.get_json(silent=True) or {}
    eid = (data.get('id') or request.args.get('id') or '').strip()
    if not eid:
        return jsonify({'error': 'id required'}), 400
    try:
        from zyg_workflows import effects_service as _fx

        _fx.remove_effect(eid)
        try:
            _pp = _fx.preview_path(eid)
            if os.path.isfile(_pp):
                os.remove(_pp)
        except OSError as _exc:
            _zyg_log.debug('cached effect preview removal skipped: %s', _exc)
        return jsonify({'ok': True, 'id': eid})
    except Exception as e:
        return jsonify({'error': str(e)[:120]}), 500


_ASSETLIB_DEPTS = tuple(
    f'assetlib_{c}' for c in ('items', 'food', 'weapons', 'agriculture', 'water', 'clouds', 'geology', 'furniture')
)


@bp.route('/api/assetlib/list')
def api_assetlib_list():
    """One category's shared asset library + preview availability + kind."""
    cat = (request.args.get('cat') or '').strip()
    try:
        from zyg_workflows import asset_library_service as _al

        info = _al.category_info(cat)
        if not info:
            return jsonify({'error': 'unknown category'}), 400
        assets = _al.load_assets(cat)
        for a in assets:
            a['has_preview'] = _al.has_preview(cat, a.get('id'))
        return jsonify({'category': cat, 'kind': info['kind'], 'label': info['label'], 'assets': assets})
    except Exception as e:
        return jsonify({'assets': [], 'error': str(e)[:120]}), 200


_AUDIO_MIME = {
    '.wav': 'audio/wav',
    '.mp3': 'audio/mpeg',
    '.ogg': 'audio/ogg',
    '.flac': 'audio/flac',
    '.m4a': 'audio/mp4',
}


@bp.route('/api/assetlib/preview')
def api_assetlib_preview():
    """Serve an asset's card preview — a still for visual categories, the audio file for audio."""
    cat = (request.args.get('cat') or '').strip()
    aid = (request.args.get('id') or '').strip()
    if not cat or not aid or any(t in aid for t in ('/', '\\', '..')):
        return jsonify({'error': 'bad params'}), 400
    try:
        from zyg_workflows import asset_library_service as _al

        if not _al.category_info(cat):
            return jsonify({'error': 'unknown category'}), 400
        fp = _al.preview_path(cat, aid)
    except Exception:
        return jsonify({'error': 'unavailable'}), 500
    if not (fp and os.path.isfile(fp)):
        return jsonify({'error': 'no preview'}), 404
    ext = os.path.splitext(fp)[1].lower()
    if ext in _AUDIO_MIME:
        return send_file(fp, mimetype=_AUDIO_MIME[ext], conditional=True)
    return send_file(fp, mimetype='image/png', conditional=True)


@bp.route('/api/assetlib/delete', methods=['POST'])
def api_assetlib_delete():
    """Remove an asset from a category library (audio files go to .deleted/, recoverable)."""
    data = request.get_json(silent=True) or {}
    cat = (data.get('cat') or request.args.get('cat') or '').strip()
    aid = (data.get('id') or request.args.get('id') or '').strip()
    if not cat or not aid:
        return jsonify({'error': 'cat and id required'}), 400
    if any(t in aid for t in ('/', '\\', '..')) or os.path.basename(aid) != aid:
        return jsonify({'error': 'bad id'}), 400
    try:
        from zyg_workflows import asset_library_service as _al

        if not _al.category_info(cat):
            return jsonify({'error': 'unknown category'}), 400
        ok = _al.remove_asset(cat, aid)
        try:
            _pp = _al.preview_path(cat, aid)
            if ok and _pp and _pp.endswith('.png') and os.path.isfile(_pp):
                os.remove(_pp)
        except OSError as _exc:
            _zyg_log.debug('cached asset preview removal skipped: %s', _exc)
        return jsonify({'ok': bool(ok), 'cat': cat, 'id': aid})
    except Exception as e:
        return jsonify({'error': str(e)[:120]}), 500


@bp.route('/api/assetlib/generated')
def api_assetlib_generated():
    """Generated apply-results for one category (scan output/assetlib_<cat>/<pid>/)."""
    cat = (request.args.get('cat') or '').strip()
    dept = f'assetlib_{cat}'
    if dept not in _ASSETLIB_DEPTS:
        return jsonify({'items': [], 'total': 0})
    _it = _envfx_scan(dept)
    return jsonify({'items': _it, 'total': len(_it)})


@bp.route('/api/envfx/media')
def api_envfx_media():
    """Serve one env/fx asset (image or video) with strict path containment."""
    dept = (request.args.get('dept') or '').strip()
    pid = (request.args.get('pid') or '').strip()
    name = (request.args.get('name') or '').strip()
    if dept not in (('environments', 'effects', 'wardrobe') + _ASSETLIB_DEPTS) or not pid or not name:
        return jsonify({'error': 'bad params'}), 400
    if any(t in pid or t in name for t in ('/', '\\', '..')):
        return jsonify({'error': 'bad name'}), 400
    root = os.path.realpath(os.path.join(_ENVFX_OUT_BASE, 'output', dept))
    fp = os.path.realpath(os.path.join(root, pid, name))
    if not (fp.startswith(root + os.sep) and os.path.isfile(fp)):
        return jsonify({'error': 'not found'}), 404
    ext = os.path.splitext(fp)[1].lower()
    if ext == '.mp4':
        return send_file(
            fp,
            mimetype='video/mp4',
            conditional=True,
            download_name=name,
            as_attachment=request.args.get('download') == '1',
        )
    mime = 'image/jpeg' if ext in ('.jpg', '.jpeg') else 'image/png'
    return send_file(fp, mimetype=mime, conditional=True)
