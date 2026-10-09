# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Composed character view, the CRUD/training endpoints and the trained-LoRA listing."""

from __future__ import annotations

from zyg_dashboard.bp_medusa_training.folder_import import _body_status
from zyg_dashboard.bp_medusa_training.storage import (
    MIN_IMAGES_TO_TRAIN,
    _CHAR_ID_RE,
    _IMAGE_NAME_RE,
    _IO_LOCK,
    _LIST_THUMBS,
    _MAX_FILES_PER_UPLOAD,
    _MAX_IMAGES_PER_CHAR,
    _MAX_REQUEST_BYTES,
    _TRAIN_DATASET_ROOT,
    _TRAIN_MAX_STEPS,
    _TRAIN_OUTPUT_ROOT,
    _auto_trigger,
    _fmt_ts,
    _ingest_one_image,
    _list_images,
    _load_meta,
    _new_char_id,
    _normalize_family,
    _normalize_mode,
    _now_iso,
    _safe_char_dir,
    _safe_output_dir,
    _sanitize_trigger,
    _save_meta,
    _write_marker,
    bp,
    jsonify,
    os,
    re,
    request,
    send_file,
    shutil,
)
from zyg_dashboard.bp_medusa_training import storage as _storage

# Bound by ASSIGNMENT, not `from ... import`: an import-originated global compiles
# `_zyg_log.warning(...)` to a different (non method-form) call sequence.
_zyg_log = _storage._zyg_log


# ── Composed view ─────────────────────────────────────────────────────────
def _character_view(char_id: str, *, max_images: int | None = None) -> dict | None:
    """Compose one character.

    max_images caps the thumbnail array. The list endpoint sets it because 80
    characters x 60 photos would otherwise ship ~4800 entries every poll and
    ask the browser to lay out that many <img> tags; the detail endpoint
    leaves it None and returns everything.
    """
    meta = _load_meta(char_id)
    if not meta:
        return None
    images = _list_images(char_id)
    view = dict(meta)
    view['image_count'] = len(images)
    view['images'] = images if max_images is None else images[:max_images]
    view['images_truncated'] = max_images is not None and len(images) > max_images
    view['can_train'] = len(images) >= MIN_IMAGES_TO_TRAIN
    try:
        from zyg_workflows.lora_trainer_service import get_trainer

        view['training'] = get_trainer().get_status(
            char_id,
            model_family=meta.get('model_family'),
            output_root=_TRAIN_OUTPUT_ROOT,
        )
    except Exception:
        view['training'] = None
    try:
        from zyg_workflows import medusa_sheet_service as _sheet

        cdir = os.path.join(_TRAIN_DATASET_ROOT, char_id)
        summary = _sheet.load_summary(cdir)
        view['sheet_status'] = _sheet.get_status(char_id)
        view['has_sheet'] = bool(summary)
        view['sheet_coverage'] = (summary or {}).get('coverage')
        view['sheet_pages'] = (summary or {}).get('pages') or []
        view['body_status'] = _body_status(char_id)
        view['body_report'] = (summary or {}).get('body_mode')
    except Exception:
        view['sheet_status'] = None
        view['has_sheet'] = False
    return view


# ── Endpoints ────────────────────────────────────────────────────────────────
@bp.route('/api/medusa/training/characters', methods=['POST'])
def api_training_create_character():
    """Create a dedicated character shell (no images yet).

    2026-08-06: this used to require a confirmed_adult flag in the request
    body before proceeding (mirroring the adults-only guardrail the rest of
    the Medusa workflow enforced at the time) — removed at the operator's
    request alongside the rest of Medusa's guardrails; see
    medusa_pipeline.py's module docstring.
    """
    body = request.get_json(silent=True) or {}

    display_name = (body.get('display_name') or '').strip()[:80] or 'Untitled'
    model_family = _normalize_family(body.get('model_family'))
    caption_suffix = (body.get('caption_suffix') or '').strip()[:200]
    trigger_token = _sanitize_trigger(body.get('trigger_token'))
    mode = _normalize_mode(body.get('mode'))
    body_promptables = (body.get('body_promptables') or '').strip()[:200]
    if mode == 'body' and not body_promptables:
        return jsonify(
            {'ok': False, 'error': 'body templates need a hair / skin / wardrobe description so those stay promptable'}
        ), 400

    char_id = _new_char_id()
    if not trigger_token:
        trigger_token = _auto_trigger(char_id)

    with _IO_LOCK:
        os.makedirs(os.path.join(_TRAIN_DATASET_ROOT, char_id, 'training'), exist_ok=True)
        meta = {
            'char_id': char_id,
            'display_name': display_name,
            'trigger_token': trigger_token,
            'model_family': model_family,
            'caption_suffix': caption_suffix,
            'created_at': _now_iso(),
            'mode': mode,
            'body_promptables': body_promptables,
            'mask_scope': 'face',
        }
        _save_meta(char_id, meta)
        _write_marker(char_id)

    return jsonify({'ok': True, 'character': _character_view(char_id)}), 201


@bp.route('/api/medusa/training/characters', methods=['GET'])
def api_training_list_characters():
    os.makedirs(_TRAIN_DATASET_ROOT, exist_ok=True)
    try:
        names = sorted(os.listdir(_TRAIN_DATASET_ROOT))
    except OSError:
        names = []
    out = []
    for name in names:
        if _CHAR_ID_RE.match(name):
            view = _character_view(name, max_images=_LIST_THUMBS)
            if view:
                out.append(view)
    out.sort(key=lambda c: c.get('created_at') or '', reverse=True)
    return jsonify({'ok': True, 'characters': out, 'count': len(out), 'min_images_to_train': MIN_IMAGES_TO_TRAIN})


@bp.route('/api/medusa/training/characters/<char_id>', methods=['GET'])
def api_training_get_character(char_id):
    view = _character_view(char_id) if _safe_char_dir(char_id) else None
    if not view:
        return jsonify({'ok': False, 'error': 'unknown character'}), 404
    return jsonify({'ok': True, 'character': view})


@bp.route('/api/medusa/training/characters/<char_id>', methods=['DELETE'])
def api_training_delete_character(char_id):
    cdir = _safe_char_dir(char_id)
    if not cdir:
        return jsonify({'ok': False, 'error': 'unknown character'}), 404

    try:
        from zyg_workflows.lora_trainer_service import get_trainer

        st = get_trainer().get_status(char_id, output_root=_TRAIN_OUTPUT_ROOT)
        if st and not st.get('done') and not st.get('failed') and (st.get('step') or 0) > 0:
            return jsonify({'ok': False, 'error': 'training is in progress — wait for it to finish first'}), 409
    except Exception as _exc:
        _zyg_log.warning(
            'training status check failed for %s, deleting without the in-progress guard: %s', char_id, _exc
        )

    # Drop any queued/running sheet build FIRST, so the pump cannot recreate
    # the directory tree we are about to remove.
    try:
        from zyg_workflows import medusa_sheet_service as _sheet

        _sheet.forget(char_id)
    except Exception as _exc:
        _zyg_log.warning('sheet job for %s could not be dropped, a pump may recreate its directory: %s', char_id, _exc)

    with _IO_LOCK:
        shutil.rmtree(cdir, ignore_errors=True)
        out_dir = _safe_output_dir(char_id)
        if out_dir:
            shutil.rmtree(out_dir, ignore_errors=True)

    return jsonify({'ok': True})


@bp.route('/api/medusa/training/characters/<char_id>/images', methods=['POST'])
def api_training_upload_images(char_id):
    cdir = _safe_char_dir(char_id)
    meta = _load_meta(char_id) if cdir else None
    if not cdir or not meta:
        return jsonify({'ok': False, 'error': 'unknown character'}), 404

    if request.content_length and request.content_length > _MAX_REQUEST_BYTES:
        return jsonify({'ok': False, 'error': 'upload request too large'}), 413

    files = request.files.getlist('images')
    if not files:
        return jsonify({'ok': False, 'error': 'no images in request (field "images")'}), 400
    if len(files) > _MAX_FILES_PER_UPLOAD:
        return jsonify({'ok': False, 'error': f'too many files in one request (max {_MAX_FILES_PER_UPLOAD})'}), 400

    train_dir = os.path.join(cdir, 'training')
    os.makedirs(train_dir, exist_ok=True)

    uploaded: list[dict] = []
    errors: list[dict] = []
    with _IO_LOCK:
        existing = len(_list_images(char_id))
        for f in files:
            # _MAX_IMAGES_PER_CHAR == 0 means "no ceiling" — without this guard a
            # 0 setting would reject every upload instead of allowing all of them.
            if _MAX_IMAGES_PER_CHAR and existing + len(uploaded) >= _MAX_IMAGES_PER_CHAR:
                errors.append(
                    {'file': f.filename, 'error': f'character already has the max {_MAX_IMAGES_PER_CHAR} images'}
                )
                continue
            result = _ingest_one_image(f, train_dir, meta)
            if 'error' in result:
                errors.append({'file': f.filename, 'error': result['error']})
            else:
                uploaded.append(result)

    return jsonify(
        {
            'ok': True,
            'uploaded': uploaded,
            'errors': errors,
            'image_count': existing + len(uploaded),
        }
    )


@bp.route('/api/medusa/training/characters/<char_id>/images/<image_id>', methods=['GET'])
def api_training_get_image(char_id, image_id):
    cdir = _safe_char_dir(char_id)
    if not cdir or not _IMAGE_NAME_RE.match(image_id or ''):
        return jsonify({'ok': False, 'error': 'not found'}), 404
    train_dir = os.path.realpath(os.path.join(cdir, 'training'))
    img_path = os.path.realpath(os.path.join(train_dir, image_id))
    if os.path.dirname(img_path) != train_dir or not os.path.isfile(img_path):
        return jsonify({'ok': False, 'error': 'not found'}), 404
    return send_file(img_path, mimetype='image/png')


@bp.route('/api/medusa/training/characters/<char_id>/images/<image_id>', methods=['DELETE'])
def api_training_delete_image(char_id, image_id):
    cdir = _safe_char_dir(char_id)
    if not cdir or not _IMAGE_NAME_RE.match(image_id or ''):
        return jsonify({'ok': False, 'error': 'not found'}), 404
    train_dir = os.path.realpath(os.path.join(cdir, 'training'))
    img_path = os.path.realpath(os.path.join(train_dir, image_id))
    if os.path.dirname(img_path) != train_dir:
        return jsonify({'ok': False, 'error': 'not found'}), 404

    with _IO_LOCK:
        removed = False
        for p in (img_path, img_path[:-4] + '.txt'):
            try:
                os.remove(p)
                removed = True
            except FileNotFoundError as _exc:
                _zyg_log.debug('nothing to remove at %s: %s', p, _exc)
    if not removed:
        return jsonify({'ok': False, 'error': 'image not found'}), 404
    return jsonify({'ok': True, 'image_count': len(_list_images(char_id))})


@bp.route('/api/medusa/training/characters/<char_id>/train', methods=['POST'])
def api_training_start(char_id):
    cdir = _safe_char_dir(char_id)
    meta = _load_meta(char_id) if cdir else None
    if not cdir or not meta:
        return jsonify({'ok': False, 'error': 'unknown character'}), 404

    body = request.get_json(silent=True) or {}
    model_family = _normalize_family(body.get('model_family') or meta.get('model_family'))
    mode = _normalize_mode(meta.get('mode'))
    loss_mask_dir = None

    if mode == 'body':
        # Body mode trains on training_body/ — the masked-loss dataset — NOT on
        # training/. Counting training/ here would happily start a run on a body
        # dataset that quarantining had gutted to three usable photographs.
        from zyg_workflows import medusa_body_mask as _bm

        dataset_dir = _bm.body_dataset_dir(cdir)
        loss_mask_dir = _bm.body_mask_dir(cdir)
        try:
            n_body = len([n for n in os.listdir(dataset_dir) if _IMAGE_NAME_RE.match(n)])
        except OSError:
            n_body = 0
        if n_body < MIN_IMAGES_TO_TRAIN:
            return jsonify(
                {
                    'ok': False,
                    'error': f'body dataset has {n_body} usable photo(s), need at least '
                    f'{MIN_IMAGES_TO_TRAIN} — run Prepare body dataset first, '
                    f'and check how many were quarantined',
                }
            ), 400
        n_mask = (
            len([n for n in os.listdir(loss_mask_dir) if _IMAGE_NAME_RE.match(n)])
            if os.path.isdir(loss_mask_dir)
            else 0
        )
        if n_mask != n_body:
            return jsonify(
                {
                    'ok': False,
                    'error': f'mask count ({n_mask}) does not match image count '
                    f'({n_body}) — re-run Prepare body dataset',
                }
            ), 400
        if _bm.is_stale(cdir):
            return jsonify(
                {
                    'ok': False,
                    'error': 'body dataset is stale — the photographs changed '
                    'since it was prepared. Re-prepare before training.',
                }
            ), 409
    else:
        images = _list_images(char_id)
        if len(images) < MIN_IMAGES_TO_TRAIN:
            return jsonify(
                {
                    'ok': False,
                    'error': f'need at least {MIN_IMAGES_TO_TRAIN} images to train (have {len(images)})',
                }
            ), 400
        dataset_dir = os.path.join(cdir, 'training')

    from zyg_workflows.lora_trainer_service import get_trainer, last_start_result

    get_trainer().start_training(
        char_id,
        dataset_dir,
        trigger_token=meta.get('trigger_token'),
        model_family=model_family,
        output_root=_TRAIN_OUTPUT_ROOT,
        cleanup_after=True,
        loss_mask_dir=loss_mask_dir,
        train_mode=mode,
        # Every imported photograph gets the full ZYG_LORA_EPOCHS passes.
        # The shared 1800-step ceiling was written for the storyteller cast's
        # ~50-image sets; a Medusa folder is a whole gallery import (340+), where
        # that ceiling silently drops each photo from 26 passes to about 5. The
        # operator's call is that a longer run is the correct trade here — the
        # storyteller paths keep the ceiling because they do not pass this.
        max_steps=_TRAIN_MAX_STEPS,
    )
    return jsonify({'ok': True, 'result': last_start_result(char_id)})


@bp.route('/api/medusa/training/characters/<char_id>/status', methods=['GET'])
def api_training_status(char_id):
    meta = _load_meta(char_id) if _safe_char_dir(char_id) else None
    if not meta:
        return jsonify({'ok': False, 'error': 'unknown character'}), 404

    mf = request.args.get('model_family') or meta.get('model_family')
    from zyg_workflows.lora_trainer_service import get_trainer

    status = get_trainer().get_status(char_id, model_family=mf, output_root=_TRAIN_OUTPUT_ROOT)
    return jsonify({'ok': True, 'status': status})


# ── Trained LoRAs ───────────────────────────────────────────────────────────
# Backs Medusa's Inspection > LoRA. Scans ONLY _TRAIN_OUTPUT_ROOT and filters
# to mdt_* ids, so it can never surface a storyteller/creature/wan adapter.
# The path it reports is whatever lora_trainer_service itself would resolve —
# not a hand-rolled guess — so what the operator sees is what a render loads.
_LORA_FAMILIES = ('flux', 'sdxl', 'qwen', 'klein')
_SAMPLE_NAME_RE = re.compile(r'^[A-Za-z0-9._-]+\.(?:png|jpg|jpeg|webp)$')
_SAMPLE_STEP_RE = re.compile(r'^step_(\d+)_')
_LORA_SAMPLES = 6


def _lora_samples(weights_dir: str) -> list[str]:
    """Validation renders, newest step first (the finished LoRA's own output)."""
    d = os.path.join(weights_dir, 'validation_images')
    try:
        names = [n for n in os.listdir(d) if _SAMPLE_NAME_RE.match(n)]
    except OSError:
        return []
    names.sort(key=lambda n: (int(m.group(1)) if (m := _SAMPLE_STEP_RE.match(n)) else -1, n), reverse=True)
    return names[:_LORA_SAMPLES]


@bp.route('/api/medusa/training/loras', methods=['GET'])
def api_training_list_loras():
    from zyg_workflows.lora_trainer_service import get_trainer

    trainer = get_trainer()
    os.makedirs(_TRAIN_OUTPUT_ROOT, exist_ok=True)
    try:
        names = sorted(n for n in os.listdir(_TRAIN_OUTPUT_ROOT) if _CHAR_ID_RE.match(n))
    except OSError:
        names = []

    out = []
    for cid in names:
        out_dir = _safe_output_dir(cid)
        if not out_dir:
            continue
        meta = _load_meta(cid) or {}
        for fam in _LORA_FAMILIES:
            wdir = os.path.join(out_dir, f'lora-weights-{fam}')
            if not os.path.isdir(wdir):
                continue
            status = trainer.get_status(cid, model_family=fam, output_root=_TRAIN_OUTPUT_ROOT) or {}
            path = trainer.get_lora_path(cid, model_family=fam, output_root=_TRAIN_OUTPUT_ROOT)
            entry = {
                'char_id': cid,
                'model_family': fam,
                'display_name': meta.get('display_name') or cid,
                'trigger_token': status.get('trigger_token') or meta.get('trigger_token'),
                'mode': _normalize_mode(meta.get('mode')),
                'source_folder': meta.get('source_folder'),
                'image_count': len(_list_images(cid)),
                'lora_path': path,
                'ready': bool(path) and os.path.isfile(path),
                'step': status.get('step'),
                'total_steps': status.get('total_steps'),
                'pct': status.get('pct'),
                'done': bool(status.get('done')),
                'failed': bool(status.get('failed')),
                'error': status.get('error'),
                'elapsed_s': status.get('elapsed_s'),
                'eta_iso': status.get('eta_iso'),
                'samples': _lora_samples(wdir),
            }
            if entry['ready']:
                st = os.stat(path)
                entry['size_bytes'] = st.st_size
                entry['finished_at'] = _fmt_ts(st.st_mtime)
            out.append(entry)

    out.sort(key=lambda e: e.get('finished_at') or '', reverse=True)
    return jsonify({'ok': True, 'loras': out, 'count': len(out), 'ready_count': sum(1 for e in out if e['ready'])})


@bp.route('/api/medusa/training/loras/<char_id>/<family>/sample/<name>', methods=['GET'])
def api_training_lora_sample(char_id, family, name):
    out_dir = _safe_output_dir(char_id)
    if not out_dir or family not in _LORA_FAMILIES or not _SAMPLE_NAME_RE.match(name or ''):
        return jsonify({'ok': False, 'error': 'not found'}), 404
    root = os.path.realpath(os.path.join(out_dir, f'lora-weights-{family}', 'validation_images'))
    p = os.path.realpath(os.path.join(root, name))
    if os.path.dirname(p) != root or not os.path.isfile(p):
        return jsonify({'ok': False, 'error': 'not found'}), 404
    return send_file(p)
