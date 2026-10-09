# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Server-side folder import: allowlisted scan, per-folder character creation.

Opens with `_ingest_path`, moved down from the Images section so it sits in the
same module as the `_in_import_roots` allowlist it calls (the pre-split file had
no module boundary between them)."""

from __future__ import annotations

from zyg_dashboard.bp_medusa_training.storage import (
    Any,
    MEDUSA_IMPORT_ROOT,
    _ALLOWED_EXTS,
    _IMPORT_ROOTS,
    _IMPORT_SKIP_DIRS,
    _MAX_FILE_BYTES,
    _MAX_IMAGES_PER_CHAR,
    _MAX_SCAN_ENTRIES,
    _TRAIN_DATASET_ROOT,
    _auto_trigger,
    _ingest_image_bytes,
    _new_char_id,
    _normalize_family,
    _normalize_mode,
    _now_iso,
    _save_meta,
    _write_marker,
    bp,
    jsonify,
    os,
    request,
    threading,
    uuid,
)
from zyg_dashboard.bp_medusa_training import storage as _storage

# Bound by ASSIGNMENT, not `from ... import`: an import-originated global compiles
# `_zyg_log.debug(...)` to a different (non method-form) call sequence.
_zyg_log = _storage._zyg_log


def _ingest_path(src: str, train_dir: str, meta: dict) -> dict:
    # Last line of defence — never read a file the allowlist does not cover,
    # regardless of how the path reached us.
    if not _in_import_roots(src):
        return {'error': 'outside the allowed import roots'}
    ext = os.path.splitext(src)[1].lower()
    try:
        with open(src, 'rb') as fh:
            raw = fh.read(_MAX_FILE_BYTES + 1)
    except OSError as exc:
        return {'error': f'unreadable ({exc.__class__.__name__})'}
    return _ingest_image_bytes(raw, ext, train_dir, meta)


# ── Server-side folder import ────────────────────────────────────────────────
# The operator prepares N folders on disk, one per character, and points the
# Training tab at their parent. Uploading 80 x 60 photos through the browser
# works but is slow and fragile; reading them off disk is neither.
def _safe_import_path(raw: Any) -> str | None:
    """Resolve an operator-supplied path, confined to _IMPORT_ROOTS."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    expanded = os.path.expanduser(raw.strip())
    # Reject relative paths outright rather than resolving them against
    # whatever the server's CWD happens to be.
    if not os.path.isabs(expanded):
        return None
    p = os.path.realpath(expanded)
    for root in _IMPORT_ROOTS:
        if p == root or p.startswith(root + os.sep):
            return p
    return None


def _in_import_roots(p: str) -> bool:
    """Is a RESOLVED path inside the allowlist?

    os.scandir follows symlinks, so validating only the operator-supplied
    parent would leave the allowlist bounding just the first path component: a
    single symlink inside an allowed folder would otherwise let the scan read
    and copy from anywhere on the filesystem. Every directory and file the scan
    touches is re-resolved through here.
    """
    rp = os.path.realpath(p)
    return any(rp == root or rp.startswith(root + os.sep) for root in _IMPORT_ROOTS)


def _count_images_in(d: str) -> int:
    n = 0
    seen = 0
    try:
        with os.scandir(d) as it:
            for e in it:
                seen += 1
                if seen >= _MAX_SCAN_ENTRIES:
                    break
                try:
                    if (
                        e.is_file()
                        and os.path.splitext(e.name)[1].lower() in _ALLOWED_EXTS
                        and _in_import_roots(e.path)
                    ):
                        n += 1
                except OSError as _exc:
                    _zyg_log.debug('skipping import entry that cannot be stat-ed: %s', _exc)
                    continue
    except OSError:
        return 0
    return n


def _list_images_in(d: str) -> list[str]:
    out: list[str] = []
    seen = 0
    try:
        with os.scandir(d) as it:
            for e in it:
                seen += 1
                if seen >= _MAX_SCAN_ENTRIES:
                    break
                try:
                    if (
                        e.is_file()
                        and os.path.splitext(e.name)[1].lower() in _ALLOWED_EXTS
                        and _in_import_roots(e.path)
                    ):
                        out.append(e.path)
                except OSError as _exc:
                    _zyg_log.debug('skipping import entry that cannot be stat-ed: %s', _exc)
                    continue
    except OSError:
        return []
    return sorted(out)


def _scan_parent(path: str) -> dict:
    """Describe a parent directory as a set of candidate characters.

    ONE SUBFOLDER == ONE CHARACTER. If the path itself holds images and has no
    image-bearing subfolders, it is treated as a single character instead, so
    pointing at either level does the sensible thing.
    """
    subs: list[dict] = []
    try:
        with os.scandir(path) as it:
            entries = sorted((e for e in it), key=lambda e: e.name)
    except OSError as exc:
        return {'error': f'cannot read folder ({exc.__class__.__name__})'}

    for e in entries:
        try:
            if not e.is_dir() or e.name.startswith('.') or e.name in _IMPORT_SKIP_DIRS:
                continue
            # is_dir() follows symlinks — re-resolve before descending.
            if not _in_import_roots(e.path):
                continue
        except OSError as _exc:
            _zyg_log.debug('skipping import folder that cannot be stat-ed: %s', _exc)
            continue
        n = _count_images_in(e.path)
        if n:
            subs.append({'name': e.name, 'path': e.path, 'image_count': n})

    own = _count_images_in(path)
    if not subs and own:
        subs = [{'name': os.path.basename(path) or 'character', 'path': path, 'image_count': own}]
        return {'mode': 'single', 'folders': subs, 'total_images': own}

    return {'mode': 'multi', 'folders': subs, 'total_images': sum(s['image_count'] for s in subs), 'loose_images': own}


_import_jobs: dict[str, dict] = {}
_import_lock = threading.Lock()

# Body-prepare job state, same shape as the sheet builder's.
_body_jobs: dict[str, dict] = {}
_body_lock = threading.Lock()


def _body_set(char_id: str, **kw) -> None:
    with _body_lock:
        _body_jobs.setdefault(char_id, {}).update(kw)


def _body_status(char_id: str) -> dict | None:
    with _body_lock:
        j = _body_jobs.get(char_id)
        return dict(j) if j else None


def _body_running(char_id: str) -> bool:
    st = _body_status(char_id)
    return bool(st and st.get('running'))


def _import_set(batch_id: str, **kw) -> None:
    with _import_lock:
        _import_jobs.setdefault(batch_id, {}).update(kw)


def _run_import(batch_id: str, folders: list[dict], model_family: str, caption_suffix: str, build_sheets: bool) -> None:
    """Each folder entry may carry its own 'mode' and 'body_promptables' —
    mode is a per-character property, not a batch-wide one. A single toggle
    applied to 80 pre-selected folders is one click away from mis-moding an
    entire cast."""
    created: list[dict] = []
    errors: list[dict] = []
    total_imgs = sum(f.get('image_count') or 0 for f in folders)
    done_imgs = 0
    _import_set(
        batch_id, running=True, total_folders=len(folders), total_images=total_imgs, done_folders=0, done_images=0
    )

    for fi, folder in enumerate(folders):
        src = folder.get('path')
        name = (folder.get('name') or os.path.basename(src or '') or 'Untitled')[:80]
        _import_set(batch_id, current=name)
        try:
            char_id = _new_char_id()
            train_dir = os.path.join(_TRAIN_DATASET_ROOT, char_id, 'training')
            os.makedirs(train_dir, exist_ok=True)
            f_mode = _normalize_mode(folder.get('mode'))
            f_prompt = (folder.get('body_promptables') or '').strip()[:200]
            if f_mode == 'body' and not f_prompt:
                errors.append(
                    {'folder': name, 'error': 'skipped — body templates need a hair / skin / wardrobe description'}
                )
                _import_set(batch_id, done_folders=fi + 1, errors=list(errors))
                continue
            meta = {
                'char_id': char_id,
                'display_name': name,
                'trigger_token': _auto_trigger(char_id),
                'model_family': model_family,
                'caption_suffix': caption_suffix,
                'created_at': _now_iso(),
                'source_folder': src,
                'import_batch': batch_id,
                'mode': f_mode,
                'body_promptables': f_prompt,
                'mask_scope': 'face',
            }
            _save_meta(char_id, meta)
            _write_marker(char_id)

            n_ok = 0
            for img_path in _list_images_in(src):
                if _MAX_IMAGES_PER_CHAR and n_ok >= _MAX_IMAGES_PER_CHAR:
                    errors.append({'folder': name, 'error': f'stopped at the {_MAX_IMAGES_PER_CHAR}-image ceiling'})
                    break
                r = _ingest_path(img_path, train_dir, meta)
                if 'error' in r:
                    errors.append({'folder': name, 'file': os.path.basename(img_path), 'error': r['error']})
                else:
                    n_ok += 1
                done_imgs += 1
                if done_imgs % 10 == 0:
                    _import_set(batch_id, done_images=done_imgs)

            created.append({'char_id': char_id, 'display_name': name, 'image_count': n_ok})

            if build_sheets and n_ok:
                try:
                    from zyg_workflows import medusa_sheet_service as _sheet

                    _sheet.start_build(
                        char_id,
                        os.path.join(_TRAIN_DATASET_ROOT, char_id),
                        trigger=meta['trigger_token'],
                        suffix=caption_suffix,
                    )
                except Exception as exc:
                    errors.append({'folder': name, 'error': f'sheet build could not start: {exc}'})
        except Exception as exc:
            errors.append({'folder': name, 'error': f'{exc.__class__.__name__}: {exc}'})

        _import_set(batch_id, done_folders=fi + 1, done_images=done_imgs, created=list(created), errors=list(errors))

    _import_set(
        batch_id,
        running=False,
        done=True,
        current=None,
        created=created,
        errors=errors,
        done_folders=len(folders),
        done_images=done_imgs,
    )


@bp.route('/api/medusa/training/import-root', methods=['GET'])
def api_training_import_root():
    """Where the operator should drop their character folders.

    The UI prefills its path box from this so nobody has to remember the path,
    and so the allowlist and the displayed location can never drift apart.
    """
    try:
        os.makedirs(MEDUSA_IMPORT_ROOT, exist_ok=True)
        exists = os.path.isdir(MEDUSA_IMPORT_ROOT)
    except OSError:
        exists = os.path.isdir(MEDUSA_IMPORT_ROOT)
    return jsonify(
        {
            'ok': True,
            'root': MEDUSA_IMPORT_ROOT,
            'exists': exists,
            'roots': list(_IMPORT_ROOTS),
        }
    )


@bp.route('/api/medusa/training/scan-folder', methods=['POST'])
def api_training_scan_folder():
    """Preview a folder: which subfolders become characters, how many photos each."""
    body = request.get_json(silent=True) or {}
    # An empty path means "the dedicated drop folder" — the common case.
    path = _safe_import_path(body.get('path') or MEDUSA_IMPORT_ROOT)
    if not path:
        return jsonify(
            {'ok': False, 'error': 'path is outside the allowed import roots: ' + ', '.join(_IMPORT_ROOTS)}
        ), 400
    if not os.path.isdir(path):
        return jsonify({'ok': False, 'error': 'not a folder (or not readable)'}), 404
    result = _scan_parent(path)
    if 'error' in result:
        return jsonify({'ok': False, 'error': result['error']}), 400
    return jsonify({'ok': True, 'path': path, **result})


@bp.route('/api/medusa/training/import-folders', methods=['POST'])
def api_training_import_folders():
    """Create one character per selected folder and ingest its photos.

    Runs on a background thread — 80 folders x 60 photos is minutes of I/O and
    would time out any reasonable HTTP client.
    """
    body = request.get_json(silent=True) or {}
    parent = _safe_import_path(body.get('path'))
    if not parent or not os.path.isdir(parent):
        return jsonify({'ok': False, 'error': 'invalid or disallowed path'}), 400

    scan = _scan_parent(parent)
    if 'error' in scan:
        return jsonify({'ok': False, 'error': scan['error']}), 400

    wanted = body.get('folders')
    available = {f['name']: f for f in scan['folders']}
    folders = []
    if isinstance(wanted, list) and wanted:
        for item in wanted:
            # Accept both the old list-of-names shape and the per-folder dict.
            if isinstance(item, str):
                found = available.get(item)
                if found:
                    folders.append(dict(found))
            elif isinstance(item, dict):
                found = available.get(item.get('name'))
                if found:
                    merged = dict(found)
                    merged['mode'] = item.get('mode')
                    merged['body_promptables'] = item.get('body_promptables')
                    folders.append(merged)
    else:
        folders = [dict(f) for f in scan['folders']]
    if not folders:
        return jsonify({'ok': False, 'error': 'no folders with images selected'}), 400

    model_family = _normalize_family(body.get('model_family'))
    caption_suffix = (body.get('caption_suffix') or '').strip()[:200]
    build_sheets = bool(body.get('build_sheets', True))

    batch_id = f'imp_{uuid.uuid4().hex[:10]}'
    _import_set(batch_id, running=True, done=False, created=[], errors=[], started_at=_now_iso(), parent=parent)
    threading.Thread(
        target=_run_import,
        daemon=True,
        name=f'medusa-import-{batch_id}',
        args=(batch_id, folders, model_family, caption_suffix, build_sheets),
    ).start()

    return jsonify(
        {
            'ok': True,
            'batch_id': batch_id,
            'folders': len(folders),
            'total_images': sum(f['image_count'] for f in folders),
        }
    ), 202


@bp.route('/api/medusa/training/import/<batch_id>', methods=['GET'])
def api_training_import_status(batch_id):
    with _import_lock:
        job = _import_jobs.get(batch_id)
        job = dict(job) if job else None
    if not job:
        return jsonify({'ok': False, 'error': 'unknown batch'}), 404
    return jsonify({'ok': True, 'batch': job})
