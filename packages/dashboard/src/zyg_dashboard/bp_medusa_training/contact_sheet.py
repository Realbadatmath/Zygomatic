# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Contact sheet endpoints: angle classification over the operator's own photos."""

from __future__ import annotations

from zyg_dashboard.bp_medusa_training.folder_import import _body_running, _body_set, _body_status
from zyg_dashboard.bp_medusa_training.storage import (
    _CHAR_ID_RE,
    _SHEET_PAGE_RE,
    _TRAIN_DATASET_ROOT,
    _list_images,
    _load_meta,
    _normalize_mode,
    _now_iso,
    _safe_char_dir,
    _save_meta,
    bp,
    jsonify,
    os,
    request,
    send_file,
    threading,
)


# ── Contact sheet (angle classification over the operator's own photos) ──────
@bp.route('/api/medusa/training/characters/<char_id>/sheet', methods=['POST'])
def api_training_build_sheet(char_id):
    cdir = _safe_char_dir(char_id)
    meta = _load_meta(char_id) if cdir else None
    if not cdir or not meta:
        return jsonify({'ok': False, 'error': 'unknown character'}), 404

    from zyg_workflows import medusa_sheet_service as _sheet

    ok, why = _sheet.detectors_available()
    if not ok:
        return jsonify({'ok': False, 'error': why}), 503
    if not _list_images(char_id):
        return jsonify({'ok': False, 'error': 'no images to classify'}), 400

    started = _sheet.start_build(
        char_id, cdir, trigger=meta.get('trigger_token') or '', suffix=(meta.get('caption_suffix') or '').strip()
    )
    if not started:
        return jsonify({'ok': False, 'error': 'a sheet build is already running'}), 409
    return jsonify({'ok': True, 'status': _sheet.get_status(char_id)}), 202


@bp.route('/api/medusa/training/characters/<char_id>/sheet', methods=['GET'])
def api_training_get_sheet(char_id):
    cdir = _safe_char_dir(char_id)
    if not cdir:
        return jsonify({'ok': False, 'error': 'unknown character'}), 404
    from zyg_workflows import medusa_sheet_service as _sheet

    return jsonify({'ok': True, 'sheet': _sheet.load_sheet(cdir), 'status': _sheet.get_status(char_id)})


@bp.route('/api/medusa/training/characters/<char_id>/sheet/page/<page>', methods=['GET'])
def api_training_sheet_page(char_id, page):
    cdir = _safe_char_dir(char_id)
    if not cdir or not _SHEET_PAGE_RE.match(page or ''):
        return jsonify({'ok': False, 'error': 'not found'}), 404
    from zyg_workflows import medusa_sheet_service as _sheet

    sdir = os.path.realpath(_sheet.sheet_dir(cdir))
    p = os.path.realpath(os.path.join(sdir, page))
    if os.path.dirname(p) != sdir or not os.path.isfile(p):
        return jsonify({'ok': False, 'error': 'not found'}), 404
    return send_file(p, mimetype='image/png')


@bp.route('/api/medusa/training/characters/<char_id>/body-prepare', methods=['POST'])
def api_training_body_prepare(char_id):
    """Build the body-template dataset (masked loss) for a body-mode character."""
    cdir = _safe_char_dir(char_id)
    meta = _load_meta(char_id) if cdir else None
    if not cdir or not meta:
        return jsonify({'ok': False, 'error': 'unknown character'}), 404
    if _normalize_mode(meta.get('mode')) != 'body':
        return jsonify(
            {
                'ok': False,
                'error': 'this character is an identity character — body preparation only applies to body templates',
            }
        ), 400

    body = request.get_json(silent=True) or {}
    promptables = (body.get('body_promptables') or meta.get('body_promptables') or '').strip()[:200]
    if not promptables:
        return jsonify(
            {'ok': False, 'error': 'body templates need a hair / skin / wardrobe description so those stay promptable'}
        ), 400
    if promptables != (meta.get('body_promptables') or ''):
        meta['body_promptables'] = promptables
        _save_meta(char_id, meta)

    if _body_running(char_id):
        return jsonify({'ok': False, 'error': 'body preparation already running'}), 409

    from zyg_workflows import medusa_body_mask as _bm

    ok, why = _bm.verifier_available()
    if not ok:
        return jsonify({'ok': False, 'retryable': True, 'error': f'independent face verifier unavailable ({why})'}), 503

    _body_set(char_id, running=True, done=False, failed=False, error=None, started_at=_now_iso())

    def run():
        try:
            res = _bm.prepare_body_dataset(
                char_id,
                cdir,
                trigger=meta.get('trigger_token') or '',
                body_promptables=promptables,
                suffix=(meta.get('caption_suffix') or '').strip(),
            )
            if res.get('ok'):
                _body_set(char_id, running=False, done=True, failed=False, report=res.get('report'))
            else:
                _body_set(char_id, running=False, done=False, failed=True, error=res.get('error'))
        except Exception as exc:
            _body_set(char_id, running=False, done=False, failed=True, error=f'{exc.__class__.__name__}: {exc}')

    threading.Thread(target=run, daemon=True, name=f'medusa-body-{char_id}').start()
    return jsonify({'ok': True, 'status': _body_status(char_id)}), 202


@bp.route('/api/medusa/training/characters/<char_id>/body-prepare', methods=['GET'])
def api_training_body_status(char_id):
    if not _safe_char_dir(char_id):
        return jsonify({'ok': False, 'error': 'unknown character'}), 404
    return jsonify({'ok': True, 'status': _body_status(char_id)})


@bp.route('/api/medusa/training/sheets', methods=['GET'])
def api_training_list_sheets():
    """Every built sheet — the data behind Medusa's Inspection > Contact Sheet.

    Scans ONLY _TRAIN_DATASET_ROOT and returns only mdt_* characters, so it can
    never surface a storyteller/medusa-swimwear/creature character.
    """
    from zyg_workflows import medusa_sheet_service as _sheet

    os.makedirs(_TRAIN_DATASET_ROOT, exist_ok=True)
    try:
        names = sorted(n for n in os.listdir(_TRAIN_DATASET_ROOT) if _CHAR_ID_RE.match(n))
    except OSError:
        names = []

    out = []
    for cid in names:
        cdir = _safe_char_dir(cid)
        if not cdir:
            continue
        meta = _load_meta(cid) or {}
        sheet = _sheet.load_summary(cdir)
        status = _sheet.get_status(cid)
        if not sheet and not status:
            continue
        entry = {
            'char_id': cid,
            'display_name': meta.get('display_name') or cid,
            'trigger_token': meta.get('trigger_token'),
            'source_folder': meta.get('source_folder'),
            'image_count': len(_list_images(cid)),
            'status': status,
        }
        entry['mode'] = _normalize_mode(meta.get('mode'))
        entry['body_promptables'] = meta.get('body_promptables') or ''
        entry['body_status'] = _body_status(cid)
        if sheet:
            entry['body_report'] = sheet.get('body_mode')
            entry.update(
                {
                    'built_at': sheet.get('built_at'),
                    'duration_s': sheet.get('duration_s'),
                    'coverage': sheet.get('coverage'),
                    'pages': sheet.get('pages') or [],
                    'flagged': sheet.get('flagged') or [],
                    'duplicate_groups': sheet.get('duplicate_groups') or [],
                }
            )
        out.append(entry)

    out.sort(key=lambda e: e.get('built_at') or '', reverse=True)
    return jsonify({'ok': True, 'sheets': out, 'count': len(out)})


@bp.route('/api/medusa/training/sheets/build-all', methods=['POST'])
def api_training_build_all_sheets():
    """Build a sheet for every character that has photos but no sheet yet."""
    from zyg_workflows import medusa_sheet_service as _sheet

    ok, why = _sheet.detectors_available()
    if not ok:
        return jsonify({'ok': False, 'error': why}), 503

    body = request.get_json(silent=True) or {}
    rebuild = bool(body.get('rebuild'))

    os.makedirs(_TRAIN_DATASET_ROOT, exist_ok=True)
    try:
        names = sorted(n for n in os.listdir(_TRAIN_DATASET_ROOT) if _CHAR_ID_RE.match(n))
    except OSError:
        names = []

    started, skipped = [], []
    for cid in names:
        cdir = _safe_char_dir(cid)
        meta = _load_meta(cid) if cdir else None
        if not cdir or not meta:
            continue
        if not _list_images(cid):
            skipped.append({'char_id': cid, 'why': 'no images'})
            continue
        if not rebuild and _sheet.load_summary(cdir):
            skipped.append({'char_id': cid, 'why': 'already built'})
            continue
        if _sheet.start_build(
            cid, cdir, trigger=meta.get('trigger_token') or '', suffix=(meta.get('caption_suffix') or '').strip()
        ):
            started.append(cid)
        else:
            skipped.append({'char_id': cid, 'why': 'already running'})

    return jsonify({'ok': True, 'started': started, 'skipped': skipped, 'started_count': len(started)}), 202
