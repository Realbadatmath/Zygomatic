# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""bp_picture_studio.py — Picture Studio advanced editing (2026-08-31).

Upscale / inpaint-repair / background-removal tools for the Picture Studio
tab in inspection.html (kanban_server.py, :8899). That process is an
unauthenticated raw http.server, so it never touches pixels itself — it only
proxies here via _pe_forward (kanban_server.py) with the shared
X-Zero-Public-Token credential, same shape as /api/internal/creature/*.

Contract: imported only at the BOTTOM of crewai_web_gui.py, after all of
main's globals (including `limiter`) exist.

This process is reachable by anything holding the token, not just the
same-host kanban proxy, so every route re-validates (id, cat, name, scope)
itself rather than trusting the caller — the same fail-closed chain
kanban_server.py's _serve_image/_delete_image already use, duplicated here
(bp_medusa.py already establishes the precedent of each side keeping its own
copy of these constants rather than importing across the process boundary).

Jobs are id-keyed (one job per short-lived edit), not char-id-keyed like
bp_medusa.py's per-character pipeline jobs — this is voice_studio.py's
_JOBS shape, which fits "one job per request" far better.
"""

from __future__ import annotations

import os
import re
import time
import threading

from flask import Blueprint, jsonify, request

from zyg_dashboard.appcore import limiter
from zyg_workflows import provenance_seal as _seal
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


bp = Blueprint('picture_studio', __name__)


def _local_only() -> bool:
    """Same-host check, identical to bp_movement._local_only.

    Added 2026-09-17 alongside this prefix's entry in crewai_web_gui's login
    allowlist. Every other prefix on that allowlist could be added safely
    because its blueprint already re-checked remote_addr on its state-changing
    routes; this one did not, so the check arrives with the allowlist line
    rather than after it. Read-only routes stay open, as mv_status/mv_spec are.
    """
    return request.remote_addr in ('127.0.0.1', '::1')


_CHARS_ROOT = os.path.realpath(
    os.environ.get('ZYG_STORYTELLER_CHARS', os.path.expanduser('~/lora-datasets/storyteller_chars'))
)
_HERE = os.path.dirname(os.path.abspath(__file__))
_RUNTIME = os.path.join(_HERE, 'data', 'runtime')

_ID_RE = re.compile(r'^[A-Za-z0-9_]{6,24}$')
_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.(png|jpg|jpeg|webp)$', re.IGNORECASE)
_CATS = {
    'cells': 'contact_sheet/cells',
    'tiles': 'contact_sheet/tiles',
    'arcane_final': 'arcane_instantid',
}

_TOOLS = ('upscale', 'inpaint', 'bg_remove')


def _safe_char_dir(cid):
    if not cid or not _ID_RE.match(cid):
        return None
    d = os.path.realpath(os.path.join(_CHARS_ROOT, cid))
    if d != os.path.join(_CHARS_ROOT, cid):
        return None
    if not (d.startswith(_CHARS_ROOT + os.sep) and os.path.isdir(d)):
        return None
    return d


_MEDUSA_IDS_CACHE = {'ts': 0.0, 'ids': None}


def _medusa_id_set():
    now = time.monotonic()
    c = _MEDUSA_IDS_CACHE
    if c['ids'] is not None and (now - c['ts']) < 4.0:
        return c['ids']
    ids = set()
    try:
        for fn in os.listdir(_RUNTIME):
            if fn.startswith('medusa_') and fn.endswith('_state.json'):
                cid = fn[len('medusa_') : -len('_state.json')]
                if cid:
                    ids.add(cid)
    except OSError as _exc:
        _zyg_log.warning('medusa runtime listing failed, medusa characters may not be excluded: %s', _exc)
    c['ts'] = now
    c['ids'] = ids
    return ids


def _is_medusa_char(cid, cdir):
    try:
        if os.path.exists(os.path.join(cdir, '.medusa_origin')):
            return True
    except OSError as _exc:
        _zyg_log.debug('medusa origin marker check failed, falling back to the id set: %s', _exc)
    return cid in _medusa_id_set()


def _resolve_source(cid, cat, name, scope):
    """Validate (id, cat, name, scope) and return the source file's real path,
    or None. Mirrors kanban_server._serve_image's fail-closed chain."""
    char_dir = _safe_char_dir(cid)
    if not char_dir or cat not in _CATS or not name or not _NAME_RE.match(name):
        return None
    if os.path.basename(name) != name:
        return None
    if _is_medusa_char(cid, char_dir) != (scope == 'medusa'):
        return None
    cat_dir = os.path.realpath(os.path.join(char_dir, _CATS[cat]))
    fp = os.path.realpath(os.path.join(cat_dir, name))
    if not (fp.startswith(cat_dir + os.sep) and cat_dir.startswith(char_dir) and os.path.isfile(fp)):
        return None
    return fp


def _derived_name(cat_dir, name, suffix, force_ext=None):
    """<stem>_<suffix><ext> in cat_dir, collision-suffixed _2/_3/... — same
    dedup loop shape as kanban_server._delete_image's trash collision loop."""
    stem, ext = os.path.splitext(name)
    ext = force_ext or ext
    candidate = f'{stem}_{suffix}{ext}'
    n = 2
    while os.path.exists(os.path.join(cat_dir, candidate)):
        candidate = f'{stem}_{suffix}_{n}{ext}'
        n += 1
    if not _NAME_RE.match(candidate):
        raise RuntimeError(f'derived name failed validation: {candidate}')
    return candidate


# ── job queue (id-keyed, mirrors voice_studio.py's _JOBS shape) ─────────────

_JOBS: dict = {}
_JOBS_LOCK = threading.Lock()
_JOB_KEEP = 24


def _job_set(jid, **kw):
    with _JOBS_LOCK:
        j = _JOBS.get(jid)
        if j:
            j.update(kw)


def _job_log(jid, msg):
    with _JOBS_LOCK:
        j = _JOBS.get(jid)
        if j:
            j['log'].append(f'{time.strftime("%H:%M:%S")} {msg}')
            j['log'] = j['log'][-40:]


def job(jid: str) -> dict:
    with _JOBS_LOCK:
        j = _JOBS.get(jid)
        return dict(j) if j else {}


def _prune_jobs():
    """Caller holds _JOBS_LOCK. Never evict a still-running job."""
    live = {k for k, j in _JOBS.items() if j.get('state') in ('queued', 'running')}
    finished = [k for k in sorted(_JOBS, key=lambda k: _JOBS[k]['started']) if k not in live]
    for old in finished[: max(0, len(finished) - _JOB_KEEP)]:
        _JOBS.pop(old, None)


# ── routes ────────────────────────────────────────────────────────────────


@bp.route('/api/internal/picture_studio/submit', methods=['POST'])
@limiter.exempt
def api_internal_picture_studio_submit():
    if not _local_only():
        return jsonify({'error': 'localhost only'}), 401
    data = request.get_json(silent=True) or {}
    cid = str(data.get('id') or '')
    cat = str(data.get('cat') or '')
    name = str(data.get('name') or '')
    scope = str(data.get('scope') or '')
    tool = str(data.get('tool') or '')

    if tool not in _TOOLS:
        return jsonify({'error': f'tool must be one of {_TOOLS}'}), 400

    char_dir = _safe_char_dir(cid)
    src = _resolve_source(cid, cat, name, scope)
    if not char_dir or not src:
        return jsonify({'error': 'bad params — image not found'}), 404

    params = {'char_dir': char_dir, 'cat': cat, 'name': name, 'src': src, 'tool': tool}
    if tool == 'upscale':
        params['scale'] = max(2, min(4, int(data.get('scale') or 2)))
    elif tool == 'inpaint':
        mask_b64 = str(data.get('mask_b64') or '')
        if not mask_b64:
            return jsonify({'error': 'mask_b64 required for inpaint'}), 400
        params['mask_b64'] = mask_b64
        params['prompt'] = str(data.get('prompt') or '')[:300]

    jid = f'{int(time.time() * 1000):x}{os.getpid():x}'
    with _JOBS_LOCK:
        _JOBS[jid] = {
            'id': jid,
            'tool': tool,
            'char_id': cid,
            'cat': cat,
            'name': name,
            'state': 'queued',
            'log': [],
            'error': '',
            'out_name': '',
            'started': time.time(),
            'finished': 0.0,
        }
        _prune_jobs()
    threading.Thread(target=_pe_worker, args=(jid, params), daemon=True, name=f'pic-edit-{jid}').start()
    return jsonify({'ok': True, 'job': job(jid)})


@bp.route('/api/internal/picture_studio/job/<jid>', methods=['GET'])
@limiter.exempt
def api_internal_picture_studio_job(jid):
    j = job(jid)
    if not j:
        return jsonify({'error': 'not found'}), 404
    return jsonify(j)


@bp.route('/api/internal/picture_studio/capability', methods=['GET'])
@limiter.exempt
def api_internal_picture_studio_capability():
    try:
        from zyg_workflows import flux_fill_service as ffs

        inpaint = {'available': ffs.is_available(), 'tiers': ffs.available_tiers()}
    except Exception as e:
        inpaint = {'available': False, 'tiers': [], 'error': f'{type(e).__name__}: {e}'}
    try:
        from zyg_workflows import bg_remove_service as bgr

        bg_remove = {'available': bgr.is_available(), 'detail': bgr.status_detail()}
    except Exception as e:
        bg_remove = {'available': False, 'detail': f'{type(e).__name__}: {e}'}
    return jsonify(
        {
            'upscale': {
                'available': True,
                'detail': 'Comfy ESRGAN when reachable, PIL LANCZOS fallback always available',
            },
            'inpaint': inpaint,
            'bg_remove': bg_remove,
        }
    )


# ── worker ────────────────────────────────────────────────────────────────


def _pe_worker(jid: str, params: dict):
    def log(msg: str):
        _job_log(jid, msg)

    _job_set(jid, state='running')
    try:
        tool = params['tool']
        src = params['src']
        cat_dir = os.path.dirname(src)
        name = params['name']

        if tool == 'upscale':
            from zyg_workflows import contact_sheet_pipeline as _csp

            scale = params['scale']
            # Both the Comfy and PIL paths always write PNG bytes regardless of
            # the destination filename's extension — force .png so the file's
            # extension matches its actual content.
            dst_name = _derived_name(cat_dir, name, f'upscaled{scale}x', force_ext='.png')
            dst = os.path.join(cat_dir, dst_name)
            try:
                _csp._upscale_sheet_comfy(src, dst, scale=scale, log_fn=log)
            except Exception as exc:
                log(f'Comfy ESRGAN failed ({exc}) — PIL LANCZOS fallback')
                _csp._upscale_sheet_pil(src, dst, scale=scale, log_fn=log)
            _seal.seal(dst, pipeline='picture_studio', run_id=jid, log_fn=log)
            _job_set(jid, state='done', out_name=dst_name, finished=time.time())

        elif tool == 'inpaint':
            import base64
            import cv2
            import numpy as np
            from PIL import Image
            from zyg_workflows import flux_fill_service as ffs

            mask_bytes = base64.b64decode(params['mask_b64'])
            mask = cv2.imdecode(np.frombuffer(mask_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
            if mask is None:
                _job_set(jid, state='error', error='could not decode mask', finished=time.time())
                return
            native_w, native_h = Image.open(src).size
            if mask.shape[1] != native_w or mask.shape[0] != native_h:
                mask = cv2.resize(mask, (native_w, native_h), interpolation=cv2.INTER_NEAREST)
            if mask.max() == 0:
                _job_set(jid, state='error', error='mask is empty — nothing to repaint', finished=time.time())
                return

            prompt = params.get('prompt') or (
                'a person with correct human anatomy, natural proportions, photographic detail'
            )
            log('submitting Qwen inpaint (qwen_inpaint_comfy)')
            out_path, tier = ffs._repair_via_qwen_comfyui(src, mask, prompt, log)
            if not out_path:
                _job_set(jid, state='error', error=f'inpaint failed on the {tier} tier', finished=time.time())
                return
            dst_name = _derived_name(cat_dir, name, 'repaired')
            dst = os.path.join(cat_dir, dst_name)
            os.rename(out_path, dst)
            _seal.seal(dst, pipeline='picture_studio', run_id=jid, log_fn=log)
            _job_set(jid, state='done', out_name=dst_name, finished=time.time())

        elif tool == 'bg_remove':
            from zyg_workflows import bg_remove_service as bgr

            dst_name = _derived_name(cat_dir, name, 'nobg', force_ext='.png')
            dst = os.path.join(cat_dir, dst_name)
            bgr.remove_background(src, dst, log_fn=log)
            _seal.seal(dst, pipeline='picture_studio', run_id=jid, log_fn=log)
            _job_set(jid, state='done', out_name=dst_name, finished=time.time())

    except Exception as e:
        _job_set(jid, state='error', error=str(e)[:300], finished=time.time())
