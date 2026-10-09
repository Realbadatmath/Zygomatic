#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Medusa Models blueprint — BASE-model LoRA training, one per model family.

Drives the Medusa (:5300) GUI's Models tab: a kanban board where the operator
switches between image model families (Qwen / Klein / SDXL), builds a dataset
per model from uploads, local folders or links, trains, and switches the result
on for Medusa renders.

ISOLATION CONTRACT
    Inherits bp_medusa_training.py's contract verbatim and adds medusa_model_lora's
    — read both before touching this file. In short: everything here lives under
    lora-datasets/medusa_models and lora-outputs/medusa_models, model ids are
    `mdm_<12 hex>` (a third id shape, distinct from `mdt_` and bare hex), nothing
    here imports contact_sheet_pipeline / char_state_service /
    character_bible_service / character_lora_family, and a trained adapter
    attaches only via medusa_model_lora's thread-local inside a Medusa worker.
    The only shared code touched is the generic, path-parameterised
    LoraTrainerService, always called with explicit dataset_dir/output_root
    inside the isolated roots.

    Do NOT add a generic sweep over lora-datasets/* or lora-outputs/* anywhere in
    this codebase without excluding medusa_models/ — that is the one thing that
    would break isolation.

AGE GATE
    medusa_age_gate is mandatory here and has no environment override. A dataset
    cannot begin training without a recorded adults-only attestation. That is an
    AGE floor only: nothing in this module restricts subject matter, wardrobe,
    pose or explicitness for adults.

Endpoints (all /api/medusa/models/..., inheriting the existing localhost-only
bypass that crewai_web_gui.py's before_request already applies to /api/medusa/*):
    GET    /api/medusa/models                       list (?family= filter)
    POST   /api/medusa/models                       create
    GET    /api/medusa/models/active                active model per family
    GET    /api/medusa/models/<id>                  detail
    DELETE /api/medusa/models/<id>                  delete (dataset + adapters)
    PATCH  /api/medusa/models/<id>                  rename / scale / park
    POST   /api/medusa/models/<id>/attest           record the adults-only attestation
    GET    /api/medusa/models/<id>/images           list dataset images
    POST   /api/medusa/models/<id>/images           multipart upload
    GET    /api/medusa/models/<id>/images/<name>    serve one
    DELETE /api/medusa/models/<id>/images/<name>    remove one
    POST   /api/medusa/models/<id>/ingest/urls      links: image URLs and/or .txt/.csv lists
    POST   /api/medusa/models/<id>/ingest/folder    a folder under the Medusa import root
    POST   /api/medusa/models/<id>/train            start training
    GET    /api/medusa/models/<id>/status           poll training
    POST   /api/medusa/models/<id>/sample           (re)render the sample pair
    GET    /api/medusa/models/<id>/sample/<name>    serve a sample image
    POST   /api/medusa/models/<id>/captions/reset   drop captions so the next run re-captions
    POST   /api/medusa/models/<id>/activate         switch on for its family
    POST   /api/medusa/models/<id>/deactivate       switch off
"""

from __future__ import annotations

import csv
import io
import ipaddress
import json
import os
import re
import socket
import threading
import time
import urllib.parse
import urllib.request

from flask import Blueprint, jsonify, request, send_file

from zyg_workflows import medusa_age_gate as age_gate
from zyg_workflows import medusa_model_jobs as jobs
from zyg_workflows import medusa_model_lora as mml
from zyg_workflows.paths import ZYG_HOME
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


bp = Blueprint('medusa_models', __name__)

# Training done -> switch on (if the family has nothing live) -> render a sample.
# Reads its work list from meta.json on disk, so a restart mid-training still
# ends with a sample. One daemon thread; start_watcher is idempotent.
jobs.start_watcher()

_ALLOWED_EXTS = ('.png', '.jpg', '.jpeg', '.webp')
_IMAGE_NAME_RE = re.compile(r'^img_[0-9a-f]{12}\.png$')

_MAX_FILE_BYTES = int(os.environ.get('ZYG_MEDUSA_MODEL_MAX_FILE_MB', '40')) * 1024 * 1024
_MAX_FILES_PER_UPLOAD = int(os.environ.get('ZYG_MEDUSA_MODEL_MAX_FILES_PER_REQUEST', '200'))
_MAX_EDGE_PX = int(os.environ.get('ZYG_MEDUSA_MODEL_MAX_EDGE_PX', '2048'))
_MAX_IMAGES = int(os.environ.get('ZYG_MEDUSA_MODEL_MAX_IMAGES', '20000'))
MIN_IMAGES_TO_TRAIN = int(os.environ.get('ZYG_MEDUSA_MODEL_MIN_IMAGES', '20'))

# Link ingest caps. Runaway guards, not design limits.
_URL_TIMEOUT_S = float(os.environ.get('ZYG_MEDUSA_MODEL_URL_TIMEOUT', '20'))
_URL_MAX_PER_CALL = int(os.environ.get('ZYG_MEDUSA_MODEL_URL_MAX_PER_CALL', '500'))
_URL_LIST_MAX_BYTES = 8 * 1024 * 1024

# Folder import shares the Training tab's dedicated drop folder, so the scan
# primitive's blast radius stays exactly what bp_medusa_training already
# narrowed it to on 2026-08-08 rather than opening a second, wider one.
_IMPORT_ROOTS = [
    os.path.realpath(p)
    for p in os.environ.get(
        'ZYG_MEDUSA_TRAINING_IMPORT_ROOTS',
        os.environ.get('ZYG_MEDUSA_IMPORT_ROOT', str(ZYG_HOME / 'medusa_import')),
    ).split(':')
    if p.strip()
]

_LOCK = threading.Lock()


# ── helpers ──────────────────────────────────────────────────────────────────
def _err(msg: str, code: int = 400):
    return jsonify({'error': str(msg)}), code


def _meta_or_404(model_id: str):
    meta = mml.load_meta(model_id)
    if not meta:
        return None, _err('model not found', 404)
    return meta, None


def _provenance_path(model_id: str) -> str | None:
    d = mml.dataset_dir(model_id)
    return os.path.join(d, 'provenance.jsonl') if d else None


def _record_provenance(model_id: str, entries: list[dict]) -> None:
    """Append one line per stored image saying where it came from.

    Not a gate — a record. The operator's standing licence policy is checked at
    FILE level, and a dataset whose files have no recorded origin cannot be
    checked at all later. Ingest never blocks on this.
    """
    p = _provenance_path(model_id)
    if not p or not entries:
        return
    try:
        with open(p, 'a', encoding='utf-8') as fh:
            for e in entries:
                fh.write(json.dumps(e, ensure_ascii=False) + '\n')
    except OSError as _exc:
        _zyg_log.warning('provenance append for %s failed, these files have no recorded origin: %s', model_id, _exc)


def _image_count(model_id: str) -> int:
    d = mml.images_dir(model_id)
    if not d or not os.path.isdir(d):
        return 0
    try:
        return sum(1 for f in os.listdir(d) if _IMAGE_NAME_RE.match(f))
    except OSError:
        return 0


def _store_image(model_id: str, raw: bytes, source: str) -> dict:
    """Decode, normalise to PNG, cap the long edge, store. Returns a result dict."""
    import hashlib

    if not raw:
        return {'ok': False, 'error': 'empty file'}
    if len(raw) > _MAX_FILE_BYTES:
        return {'ok': False, 'error': f'over {_MAX_FILE_BYTES // (1024 * 1024)} MB'}
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return {'ok': False, 'error': 'Pillow not installed on the server'}
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
        img = ImageOps.exif_transpose(img)
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        elif img.mode == 'L':
            img = img.convert('RGB')
        if max(img.size) > _MAX_EDGE_PX:
            img.thumbnail((_MAX_EDGE_PX, _MAX_EDGE_PX), Image.LANCZOS)
    except Exception as exc:
        return {'ok': False, 'error': f'not a readable image ({type(exc).__name__})'}

    d = mml.images_dir(model_id)
    if not d:
        return {'ok': False, 'error': 'bad model id'}
    os.makedirs(d, exist_ok=True)
    digest = hashlib.sha256(raw).hexdigest()
    name = f'img_{digest[:12]}.png'
    path = os.path.join(d, name)
    if os.path.isfile(path):
        return {'ok': True, 'name': name, 'duplicate': True}
    tmp = f'{path}.tmp.{os.getpid()}'
    try:
        img.save(tmp, 'PNG')
        os.replace(tmp, path)
    except Exception as exc:
        try:
            os.unlink(tmp)
        except OSError as _exc:
            _zyg_log.debug('temp image cleanup skipped: %s', _exc)
        return {'ok': False, 'error': f'could not write ({exc})'}
    return {
        'ok': True,
        'name': name,
        'duplicate': False,
        'provenance': {
            'file': name,
            'source': source,
            'sha256': digest,
            'bytes': len(raw),
            'at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        },
    }


# ── URL ingest ───────────────────────────────────────────────────────────────
def _is_public_host(host: str) -> bool:
    """False for loopback/private/link-local targets.

    A server-side fetcher that will resolve 127.0.0.1, 169.254.169.254 or the
    LAN is an SSRF primitive reachable from the Medusa GUI — it could be pointed
    at the other services on this machine. This is a network guard, not a
    content one.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


def _fetch(url: str, max_bytes: int) -> tuple[bytes | None, str]:
    """GET *url* with a size cap. Returns (body, error)."""
    try:
        parts = urllib.parse.urlparse(url)
    except ValueError:
        return None, 'unparseable URL'
    if parts.scheme not in ('http', 'https'):
        return None, f'unsupported scheme {parts.scheme!r} (http/https only)'
    if not parts.hostname:
        return None, 'no host in URL'
    if not _is_public_host(parts.hostname):
        return None, 'refused: host resolves to a private or loopback address'
    req = urllib.request.Request(  # noqa: S310  scheme and host validated above
        url,
        headers={
            # Some hosts (Zenodo among them) 403 a bare urllib UA.
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) ZygomaticDatasetFetcher/1.0',
            'Accept': 'image/*,text/plain,text/csv,*/*',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_URL_TIMEOUT_S) as resp:  # nosec B310  # noqa: S310  scheme and host validated above
            body = resp.read(max_bytes + 1)
    except Exception as exc:
        return None, f'{type(exc).__name__}: {str(exc)[:160]}'
    if len(body) > max_bytes:
        return None, f'over {max_bytes // (1024 * 1024)} MB'
    return body, ''


def _expand_url_list(body: bytes, origin: str) -> list[str]:
    """Pull URLs out of a .txt (one per line) or .csv (any cell that is a URL)."""
    try:
        text = body.decode('utf-8', errors='replace')
    except Exception:
        return []
    urls: list[str] = []
    if origin.lower().endswith('.csv'):
        try:
            for row in csv.reader(io.StringIO(text)):
                for cell in row:
                    c = cell.strip()
                    if c.startswith(('http://', 'https://')):
                        urls.append(c)
        except csv.Error as _exc:
            _zyg_log.debug('csv url parse failed, falling back to line scanning: %s', _exc)
    if not urls:
        for line in text.splitlines():
            c = line.strip().strip('"\'')
            if c.startswith(('http://', 'https://')):
                urls.append(c)
    return urls


# ── routes: registry ─────────────────────────────────────────────────────────
@bp.route('/api/medusa/models', methods=['GET'])
def api_models_list():
    fam = request.args.get('family', '')
    models = mml.list_models(fam)
    return jsonify(
        {
            'models': [_decorate(m) for m in models],
            'families': list(mml.FAMILIES),
            'active': {f: mml.get_active_id(f) for f in mml.FAMILIES},
            'min_images': MIN_IMAGES_TO_TRAIN,
            'min_age': age_gate.MIN_AGE,
        }
    )


def _decorate(meta: dict) -> dict:
    """Add DERIVED state. The board's lane comes from facts on disk, never from
    a stored status field — a lane that can be set independently of reality is
    how a stage stays green while it is unreachable."""
    mid = meta.get('model_id', '')
    fam = mml.normalize_family(meta.get('family'))
    out = dict(meta)
    n = _image_count(mid)
    trained = mml.is_trained(mid, fam)
    attested = bool((meta.get('age_attestation') or {}).get('adults_only'))
    st = _train_status(mid, fam)
    # get_status returns {'status','done','failed',…}; there is no 'running'
    # key. 'not_found' means no job was ever registered for this id.
    running = bool(
        st
        and not st.get('done')
        and not st.get('failed')
        and str(st.get('status') or '') not in ('not_found', '', 'done')
    )
    # The chain's own pre-training phases (captioning, freeing VRAM, starting)
    # count as training for the lane: the model is committed to the GPU queue.
    ph = jobs.state(mid)
    if ph.get('phase') in ('captioning', 'freeing', 'waiting', 'starting'):
        running = True
    out.update(
        {
            'images': n,
            'trained': trained,
            'attested': attested,
            'active': mml.get_active_id(fam) == mid,
            'training': st or {},
            'adapter': mml.adapter_path(mid, fam) or '',
            'can_train': bool(attested and n >= MIN_IMAGES_TO_TRAIN and not running),
            'blockers': _blockers(attested, n, running),
            'lane': _lane(meta, n, trained, attested, running, fam, mid),
            'phase': ph,
            'sample': meta.get('sample') or None,
            'awaiting_sample': bool(meta.get('awaiting_sample')),
        }
    )
    return out


def _blockers(attested: bool, n: int, running: bool) -> list[str]:
    b = []
    if not attested:
        b.append(f'needs an adults-only ({age_gate.MIN_AGE}+) attestation')
    if n < MIN_IMAGES_TO_TRAIN:
        b.append(f'needs {MIN_IMAGES_TO_TRAIN - n} more images ({n}/{MIN_IMAGES_TO_TRAIN})')
    if running:
        b.append('already training')
    return b


def _lane(meta, n, trained, attested, running, fam, mid) -> str:
    if meta.get('parked'):
        return 'parked'
    if running:
        return 'training'
    if mml.get_active_id(fam) == mid and trained:
        return 'active'
    if trained:
        return 'trained'
    if attested and n >= MIN_IMAGES_TO_TRAIN:
        return 'ready'
    return 'collecting'


def _train_status(model_id: str, family: str) -> dict | None:
    """Live training status, scoped to the ISOLATED output root.

    model_family/output_root are both passed: get_status falls back to a
    filesystem scan when the job is not in memory (after a restart), and an
    unscoped scan would look under the shared storyteller root instead of ours.
    """
    try:
        from zyg_workflows import lora_trainer_service as lts

        return (
            lts.get_trainer().get_status(
                model_id,
                model_family=mml.normalize_family(family),
                output_root=mml.MODEL_OUTPUT_ROOT,
            )
            or None
        )
    except Exception:
        return None


@bp.route('/api/medusa/models', methods=['POST'])
def api_models_create():
    body = request.get_json(silent=True) or {}
    name = str(body.get('name') or '').strip()[:80]
    if not name:
        return _err('name is required')
    fam = mml.normalize_family(body.get('family'))
    mid = mml.new_model_id()
    d = mml.dataset_dir(mid)
    if not d:
        return _err('could not allocate a model id', 500)
    os.makedirs(os.path.join(d, 'images'), exist_ok=True)
    meta = {
        'model_id': mid,
        'name': name,
        'family': fam,
        'notes': str(body.get('notes') or '')[:2000],
        'scale': float(body.get('scale') or 0.85),
        'trigger': f'ZYG_MDM_{mid[4:10].upper()}',
        'created': time.time(),
        'updated': time.time(),
        'parked': False,
        'age_attestation': None,
    }
    mml.save_meta(mid, meta)
    return jsonify({'ok': True, 'model': _decorate(meta)})


@bp.route('/api/medusa/models/active', methods=['GET'])
def api_models_active():
    out = {}
    for f in mml.FAMILIES:
        r = mml.resolve_active(f)
        out[f] = r or None
    return jsonify({'active': out})


@bp.route('/api/medusa/models/<model_id>', methods=['GET'])
def api_model_detail(model_id):
    meta, err = _meta_or_404(model_id)
    if err:
        return err
    return jsonify({'model': _decorate(meta)})


@bp.route('/api/medusa/models/<model_id>', methods=['PATCH'])
def api_model_patch(model_id):
    meta, err = _meta_or_404(model_id)
    if err:
        return err
    body = request.get_json(silent=True) or {}
    if 'name' in body:
        meta['name'] = str(body['name'] or '').strip()[:80] or meta['name']
    if 'notes' in body:
        meta['notes'] = str(body['notes'] or '')[:2000]
    if 'scale' in body:
        try:
            meta['scale'] = max(0.0, min(2.0, float(body['scale'])))
        except (TypeError, ValueError):
            return _err('scale must be a number')
    if 'parked' in body:
        meta['parked'] = bool(body['parked'])
    if 'caption_prefix' in body:
        cp = str(body['caption_prefix'] or '').strip()[:200]
        try:
            age_gate.assert_adult_prompt(cp, field='caption prefix')
        except age_gate.MedusaAgeError as exc:
            return _err(str(exc), 400)
        meta['caption_prefix'] = cp
    if 'sample_prompt' in body:
        sp = str(body['sample_prompt'] or '').strip()[:2000]
        try:
            age_gate.assert_adult_prompt(sp, field='sample prompt')
        except age_gate.MedusaAgeError as exc:
            return _err(str(exc), 400)
        meta['sample_prompt'] = sp
    mml.save_meta(model_id, mml.touch(meta))
    return jsonify({'ok': True, 'model': _decorate(meta)})


@bp.route('/api/medusa/models/<model_id>', methods=['DELETE'])
def api_model_delete(model_id):
    import shutil

    meta, err = _meta_or_404(model_id)
    if err:
        return err
    fam = mml.normalize_family(meta.get('family'))
    if mml.get_active_id(fam) == model_id:
        mml.set_active_id(fam, '')
    for d in (mml.dataset_dir(model_id), mml.output_dir(model_id)):
        if d and os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
    return jsonify({'ok': True, 'deleted': model_id})


# ── routes: age attestation ──────────────────────────────────────────────────
@bp.route('/api/medusa/models/<model_id>/attest', methods=['POST'])
def api_model_attest(model_id):
    meta, err = _meta_or_404(model_id)
    if err:
        return err
    body = request.get_json(silent=True) or {}
    if body.get('confirm') is not True:
        return _err(f'confirm must be true — this records that every subject in this dataset is {age_gate.MIN_AGE}+')
    if body.get('revoke') is True:
        meta['age_attestation'] = None
    else:
        meta['age_attestation'] = age_gate.attestation_record(
            who=str(body.get('who') or 'operator'), note=str(body.get('note') or '')
        )
    mml.save_meta(model_id, mml.touch(meta))
    return jsonify({'ok': True, 'model': _decorate(meta)})


# ── routes: dataset images ───────────────────────────────────────────────────
@bp.route('/api/medusa/models/<model_id>/images', methods=['GET'])
def api_model_images(model_id):
    meta, err = _meta_or_404(model_id)
    if err:
        return err
    d = mml.images_dir(model_id)
    names = []
    if d and os.path.isdir(d):
        try:
            names = sorted(f for f in os.listdir(d) if _IMAGE_NAME_RE.match(f))
        except OSError:
            names = []
    page = max(0, int(request.args.get('page', 0) or 0))
    per = min(500, max(1, int(request.args.get('per', 120) or 120)))
    page_names = names[page * per : (page + 1) * per]
    caps = {}
    for n in page_names:
        tp = os.path.join(d, n[:-4] + '.txt')
        if os.path.isfile(tp):
            try:
                with open(tp, encoding='utf-8') as fh:
                    caps[n] = fh.read().strip()[:400]
            except OSError as _exc:
                _zyg_log.debug('caption file unreadable, listing the image without it: %s', _exc)
    return jsonify({'images': page_names, 'captions': caps, 'total': len(names), 'page': page, 'per': per})


@bp.route('/api/medusa/models/<model_id>/images', methods=['POST'])
def api_model_images_upload(model_id):
    meta, err = _meta_or_404(model_id)
    if err:
        return err
    files = request.files.getlist('files') or request.files.getlist('file')
    if not files:
        return _err('no files in the request')
    if len(files) > _MAX_FILES_PER_UPLOAD:
        return _err(f'at most {_MAX_FILES_PER_UPLOAD} files per request — the browser should chunk a larger selection')
    if _image_count(model_id) + len(files) > _MAX_IMAGES:
        return _err(f'would exceed the {_MAX_IMAGES}-image ceiling for one model')
    added, dupes, errors, prov = 0, 0, [], []
    for f in files:
        ext = os.path.splitext(f.filename or '')[1].lower()
        if ext and ext not in _ALLOWED_EXTS:
            errors.append(f'{f.filename}: {ext} not accepted')
            continue
        res = _store_image(model_id, f.read(), f'upload:{f.filename}')
        if not res.get('ok'):
            errors.append(f'{f.filename}: {res.get("error")}')
        elif res.get('duplicate'):
            dupes += 1
        else:
            added += 1
            if res.get('provenance'):
                prov.append(res['provenance'])
    _record_provenance(model_id, prov)
    return jsonify(
        {'ok': True, 'added': added, 'duplicates': dupes, 'errors': errors[:40], 'total': _image_count(model_id)}
    )


@bp.route('/api/medusa/models/<model_id>/images/<name>', methods=['GET'])
def api_model_image_get(model_id, name):
    if not _IMAGE_NAME_RE.match(name or ''):
        return _err('bad image name', 404)
    d = mml.images_dir(model_id)
    p = os.path.join(d, name) if d else ''
    if not p or not os.path.isfile(p):
        return _err('not found', 404)
    return send_file(p, mimetype='image/png')


@bp.route('/api/medusa/models/<model_id>/images/<name>', methods=['DELETE'])
def api_model_image_delete(model_id, name):
    if not _IMAGE_NAME_RE.match(name or ''):
        return _err('bad image name', 404)
    d = mml.images_dir(model_id)
    p = os.path.join(d, name) if d else ''
    if p and os.path.isfile(p):
        try:
            os.unlink(p)
        except OSError as exc:
            return _err(f'could not remove: {exc}', 500)
    # Its caption too, or a stale .txt outlives the image it described.
    txt = p[:-4] + '.txt' if p else ''
    if txt and os.path.isfile(txt):
        try:
            os.unlink(txt)
        except OSError as _exc:
            _zyg_log.warning('caption file could not be removed, a stale .txt remains: %s', _exc)
    return jsonify({'ok': True, 'total': _image_count(model_id)})


# ── routes: link ingest ──────────────────────────────────────────────────────
@bp.route('/api/medusa/models/<model_id>/ingest/urls', methods=['POST'])
def api_model_ingest_urls(model_id):
    meta, err = _meta_or_404(model_id)
    if err:
        return err
    body = request.get_json(silent=True) or {}
    raw = body.get('urls')
    if isinstance(raw, str):
        candidates = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    elif isinstance(raw, list):
        candidates = [str(u).strip() for u in raw if str(u).strip()]
    else:
        return _err('urls must be a list or a newline-separated string')
    if not candidates:
        return _err('no URLs supplied')

    # A .txt/.csv link is a LIST of image URLs — fetch and expand it first.
    expanded: list[str] = []
    list_errors: list[str] = []
    for u in candidates:
        if u.lower().split('?')[0].endswith(('.txt', '.csv')):
            data, e = _fetch(u, _URL_LIST_MAX_BYTES)
            if e:
                list_errors.append(f'{u}: {e}')
                continue
            found = _expand_url_list(data, u)
            if not found:
                list_errors.append(f'{u}: no http(s) URLs found in the list')
            expanded.extend(found)
        else:
            expanded.append(u)

    # De-duplicate while preserving order, then cap.
    seen, urls = set(), []
    for u in expanded:
        if u not in seen:
            seen.add(u)
            urls.append(u)
    truncated = len(urls) > _URL_MAX_PER_CALL
    urls = urls[:_URL_MAX_PER_CALL]

    room = _MAX_IMAGES - _image_count(model_id)
    if room <= 0:
        return _err(f'already at the {_MAX_IMAGES}-image ceiling')
    urls = urls[:room]

    added, dupes, errors, prov = 0, 0, list(list_errors), []
    for u in urls:
        data, e = _fetch(u, _MAX_FILE_BYTES)
        if e:
            errors.append(f'{u}: {e}')
            continue
        res = _store_image(model_id, data, u)
        if not res.get('ok'):
            errors.append(f'{u}: {res.get("error")}')
        elif res.get('duplicate'):
            dupes += 1
        else:
            added += 1
            if res.get('provenance'):
                prov.append(res['provenance'])
    _record_provenance(model_id, prov)
    return jsonify(
        {
            'ok': True,
            'added': added,
            'duplicates': dupes,
            'attempted': len(urls),
            'truncated': truncated,
            'errors': errors[:60],
            'total': _image_count(model_id),
        }
    )


@bp.route('/api/medusa/models/<model_id>/ingest/folder', methods=['POST'])
def api_model_ingest_folder(model_id):
    meta, err = _meta_or_404(model_id)
    if err:
        return err
    body = request.get_json(silent=True) or {}
    raw = str(body.get('path') or '').strip()
    if not raw:
        return _err('path is required')
    target = os.path.realpath(raw)
    if not any(target == r or target.startswith(r + os.sep) for r in _IMPORT_ROOTS):
        return _err(f'path is outside the import root(s): {", ".join(_IMPORT_ROOTS)}')
    if not os.path.isdir(target):
        return _err('not a directory', 404)

    found: list[str] = []
    recurse = bool(body.get('recursive', True))
    for root, dirs, files in os.walk(target):
        for f in files:
            if os.path.splitext(f)[1].lower() in _ALLOWED_EXTS:
                found.append(os.path.join(root, f))
        if not recurse:
            dirs[:] = []
    found.sort()

    if body.get('preview'):
        return jsonify(
            {'ok': True, 'path': target, 'found': len(found), 'sample': [os.path.basename(p) for p in found[:20]]}
        )

    room = _MAX_IMAGES - _image_count(model_id)
    added, dupes, errors, prov = 0, 0, [], []
    for p in found[: max(0, room)]:
        try:
            with open(p, 'rb') as fh:
                data = fh.read(_MAX_FILE_BYTES + 1)
        except OSError as exc:
            errors.append(f'{os.path.basename(p)}: {exc}')
            continue
        res = _store_image(model_id, data, f'file://{p}')
        if not res.get('ok'):
            errors.append(f'{os.path.basename(p)}: {res.get("error")}')
        elif res.get('duplicate'):
            dupes += 1
        else:
            added += 1
            if res.get('provenance'):
                prov.append(res['provenance'])
    _record_provenance(model_id, prov)
    return jsonify(
        {
            'ok': True,
            'added': added,
            'duplicates': dupes,
            'found': len(found),
            'errors': errors[:60],
            'total': _image_count(model_id),
        }
    )


# ── routes: training ─────────────────────────────────────────────────────────
@bp.route('/api/medusa/models/<model_id>/train', methods=['POST'])
def api_model_train(model_id):
    meta, err = _meta_or_404(model_id)
    if err:
        return err

    # THE AGE FLOOR. No environment override, by design (medusa_age_gate).
    try:
        age_gate.require_attestation(meta, what='this dataset')
    except age_gate.MedusaAgeError as exc:
        return _err(str(exc), 409)

    n = _image_count(model_id)
    if n < MIN_IMAGES_TO_TRAIN:
        return _err(f'needs at least {MIN_IMAGES_TO_TRAIN} images, has {n}', 409)

    if not mml.dataset_dir(model_id) or not mml.output_dir(model_id):
        return _err('bad model id', 400)
    os.makedirs(mml.output_dir(model_id), exist_ok=True)

    body = request.get_json(silent=True) or {}
    try:
        steps = int(body.get('steps') or 0)
    except (TypeError, ValueError):
        return _err('steps must be a number')

    # Captioning (SimpleTuner's textfile strategy raises on a missing .txt),
    # freeing Ollama's VRAM, and the trainer launch all run in the background
    # chain — captioning a large set takes minutes, far past any HTTP timeout.
    if not jobs.start_pipeline(model_id, steps):
        return _err('this model is already captioning, training or sampling', 409)
    return jsonify({'ok': True, 'started': True, 'model': _decorate(meta)})


@bp.route('/api/medusa/models/<model_id>/status', methods=['GET'])
def api_model_status(model_id):
    meta, err = _meta_or_404(model_id)
    if err:
        return err
    fam = mml.normalize_family(meta.get('family'))
    return jsonify(
        {
            'ok': True,
            'status': _train_status(model_id, fam) or {},
            'trained': mml.is_trained(model_id, fam),
            'adapter': mml.adapter_path(model_id, fam) or '',
            'lane': _decorate(meta)['lane'],
        }
    )


# ── routes: activation ───────────────────────────────────────────────────────
@bp.route('/api/medusa/models/<model_id>/activate', methods=['POST'])
def api_model_activate(model_id):
    meta, err = _meta_or_404(model_id)
    if err:
        return err
    fam = mml.normalize_family(meta.get('family'))
    if not mml.is_trained(model_id, fam):
        return _err('no trained adapter on disk for this model yet', 409)
    try:
        age_gate.require_attestation(meta, what='this model')
    except age_gate.MedusaAgeError as exc:
        return _err(str(exc), 409)
    mml.set_active_id(fam, model_id)
    return jsonify({'ok': True, 'active': {fam: model_id}, 'model': _decorate(meta)})


@bp.route('/api/medusa/models/<model_id>/deactivate', methods=['POST'])
def api_model_deactivate(model_id):
    meta, err = _meta_or_404(model_id)
    if err:
        return err
    fam = mml.normalize_family(meta.get('family'))
    if mml.get_active_id(fam) == model_id:
        mml.set_active_id(fam, '')
    return jsonify({'ok': True, 'model': _decorate(meta)})


# ── routes: samples ──────────────────────────────────────────────────────────
_SAMPLE_NAME_RE = re.compile(r'^\d{8}_\d{6}_(?:lora|base)\.png$')


@bp.route('/api/medusa/models/<model_id>/sample', methods=['POST'])
def api_model_sample(model_id):
    meta, err = _meta_or_404(model_id)
    if err:
        return err
    fam = mml.normalize_family(meta.get('family'))
    if not mml.is_trained(model_id, fam):
        return _err('no trained adapter yet', 409)
    body = request.get_json(silent=True) or {}
    prompt = str(body.get('prompt') or '').strip()[:2000]
    if prompt:
        try:
            age_gate.assert_adult_prompt(prompt, field='sample prompt')
        except age_gate.MedusaAgeError as exc:
            return _err(str(exc), 400)
        meta['sample_prompt'] = prompt
        mml.save_meta(model_id, mml.touch(meta))
    if not jobs.sample_async(model_id, prompt):
        return _err('this model is busy (captioning, training or sampling)', 409)
    return jsonify({'ok': True, 'started': True})


@bp.route('/api/medusa/models/<model_id>/sample/<name>', methods=['GET'])
def api_model_sample_get(model_id, name):
    if not _SAMPLE_NAME_RE.match(name or ''):
        return _err('bad sample name', 404)
    od = mml.output_dir(model_id)
    p = os.path.join(od, 'samples', name) if od else ''
    if not p or not os.path.isfile(p):
        return _err('not found', 404)
    return send_file(p, mimetype='image/png')


@bp.route('/api/medusa/models/<model_id>/captions/reset', methods=['POST'])
def api_model_captions_reset(model_id):
    meta, err = _meta_or_404(model_id)
    if err:
        return err
    d = mml.images_dir(model_id)
    n = 0
    if d and os.path.isdir(d):
        for f in os.listdir(d):
            if re.match(r'^img_[0-9a-f]{12}\.txt$', f):
                try:
                    os.unlink(os.path.join(d, f))
                    n += 1
                except OSError as _exc:
                    _zyg_log.warning('caption %s could not be removed, it stays on disk: %s', f, _exc)
    meta.pop('captions', None)
    mml.save_meta(model_id, mml.touch(meta))
    return jsonify({'ok': True, 'removed': n})
