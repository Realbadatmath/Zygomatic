#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Medusa workflow blueprint — adult-women swimwear character generator.

Self-contained: its own operator-approval queue, its own job state, its own
kanban-status endpoint. It does NOT touch the shared approval store, the shared
/api/kanban/status handler, or any existing workflow's code path. The heavy
lifting is delegated to medusa_pipeline.run_medusa_pipeline, which in turn
reuses the stock (unmodified) FLUX contact-sheet + LoRA engine.

Contract (same as the other bp_*.py modules): imported at the BOTTOM of
crewai_web_gui.py, after main's globals exist.

Endpoints (all additive, medusa-namespaced):
    POST /api/medusa/generate                 park a request for operator approval
    GET  /api/medusa/pending                  list pending / recently-decided requests
    POST /api/medusa/pending/<req_id>/decide  {"action": "allow" | "decline"}
    GET  /api/medusa/jobs                      list medusa job states
    GET  /api/medusa/kanban_status            board status (template=medusa),
                                              including whether a Medusa workflow —
                                              a generation job, a Vicky/Victor turn,
                                              a Training/Models render, or a picture
                                              rendered for the Medusa app in another
                                              process — is running now
"""

from __future__ import annotations

import json
import logging as _zyg_logging
import os
import threading
import uuid
from typing import Any

from flask import Blueprint, jsonify, request

from zyg_dashboard.cors import apply_cors

# The two shared origin detectors live in zyg_workflows so the public site can ask whether
# a character came from Medusa without importing the dashboard. Re-exported from here
# because this module has always been their import site (bp_storyteller calls them on it).
from zyg_workflows.medusa_chars import filter_out_medusa, is_medusa_char
from zyg_workflows.paths import ZYG_HOME, ZYG_LORA_DATASETS

__all__ = ['bp', 'filter_out_medusa', 'is_medusa_char']

bp = Blueprint('medusa', __name__)

# ── Rate-limit exemption for the board poll (2026-09-23) ─────────────────────
# The Workflows board polls kanban_status twice a second (and every other board
# cross-probes it every 2 s), which is ~7 200 requests an hour against the app's
# default_limits of 200/hour. The shared board endpoint /api/kanban/status has
# carried @limiter.exempt since it was written; this one never did, so from the
# 201st poll of every hour the board got 429 and could not see a Medusa workflow
# at all. Measured on 2026-09-23: 5 018 × 200 and 6 232 × 429 on this path in one
# day, and 100 % 429 through the 18:43–18:49 window in which the operator
# generated pictures in the Medusa app — the board stayed idle for exactly that
# reason. Read-only status; the exemption opens nothing.
# Guarded: bp_medusa is imported at the BOTTOM of crewai_web_gui (so `limiter`
# already exists), but the module must still import standalone for offline checks.
try:  # pragma: no cover - wiring
    from zyg_dashboard.appcore import limiter as _limiter

    _rate_exempt = _limiter.exempt
except Exception:  # noqa: BLE001

    def _rate_exempt(fn):  # no limiter → nothing to exempt
        return fn


_zyg_log = _zyg_logging.getLogger(__name__)


# ── State locations (computed locally; mirrors crews/data/runtime) ───────────
_CREWS_DIR = os.path.dirname(os.path.abspath(__file__))
_RUNTIME_DIR = os.path.join(_CREWS_DIR, 'data', 'runtime')
_PENDING_PATH = os.path.join(_RUNTIME_DIR, 'medusa_pending.json')
# Where the reused pipeline writes each char's dataset dir (mirrors kanban_server
# + contact_sheet_pipeline). Used to stamp a durable '.medusa_origin' marker so
# every origin-aware view can tell a medusa char apart from a stock one.
_CHARS_ROOT = os.path.realpath(os.environ.get('ZYG_STORYTELLER_CHARS', str(ZYG_LORA_DATASETS / 'storyteller_chars')))
# The Medusa app (:5300) is a separate process with its own tree. A request made
# to Vicky or Victor in that app counts as a Medusa workflow (operator,
# 2026-09-17), so this blueprint reads the small beacon file medusa_vicky.py
# keeps there rather than probing the app over HTTP — a status poll every two
# seconds must never depend on, or disturb, a live assistant turn.
_MEDUSA_APP_DIR = os.environ.get('ZYG_MEDUSA_APP_DIR', str(ZYG_HOME / 'Zygomatic' / 'medusa'))
_VICKY_BEACON = os.path.join(_MEDUSA_APP_DIR, 'data', 'runtime', 'vicky', 'workflow_beacon.json')
# The beacon is refreshed every 10s while a turn runs; anything older than this
# is a service that died mid-turn, not a workflow still going.
_BEACON_STALE_S = 45.0
# Same contract, one directory, for every OTHER process that renders Medusa
# content. _render_activity() below can only see work running inside THIS
# process; a picture asked for in the Medusa app is rendered by the still
# service in the kanban server (:8899, video_stills.py) — a different process,
# so sys.modules here is blind to it. That process drops one small file per
# source in this directory while it works ({running, label, ts}, refreshed on a
# tick, ignored once stale) and the board sees it like any other Medusa run.
_PEER_BEACON_DIR = os.path.join(_RUNTIME_DIR, 'medusa_beacons')

_IO_LOCK = threading.Lock()
_medusa_jobs: dict[str, dict] = {}  # char_id -> job dict (in-memory, live)


def _ensure_runtime_dir() -> None:
    try:
        os.makedirs(_RUNTIME_DIR, exist_ok=True)
    except OSError as _exc:
        _zyg_log.warning('medusa runtime dir could not be created, state writes will fail: %s', _exc)


def _job_state_path(char_id: str) -> str:
    return os.path.join(_RUNTIME_DIR, f'medusa_{char_id}_state.json')


# ── Atomic JSON helpers ──────────────────────────────────────────────────────
def _load_json(path: str, default: Any) -> Any:
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return default


def _save_json(path: str, data: Any) -> None:
    _ensure_runtime_dir()
    tmp = f'{path}.tmp.{os.getpid()}'
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError) as exc:
        _zyg_log.warning('medusa state write to %s failed, the state is not persisted: %s', path, exc)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError as _exc:
            _zyg_log.debug('stale temp state file cleanup skipped: %s', _exc)


def _pending_load() -> list:
    data = _load_json(_PENDING_PATH, [])
    return data if isinstance(data, list) else []


def _pending_save(rows: list) -> None:
    _save_json(_PENDING_PATH, rows)


def _save_job(char_id: str, job: dict) -> None:
    _save_json(_job_state_path(char_id), job)


def _write_origin_marker(char_id: str) -> None:
    """Stamp a durable '.medusa_origin' marker into the char's dataset dir so every
    origin-aware view (inspection, libraries) can exclude/scope medusa chars even
    if the runtime state file is later rotated away. The char dir does NOT exist at
    worker start (the reused pipeline creates it), so makedirs first; the caller
    also re-asserts this in its finally so the marker is guaranteed after a run."""
    try:
        cdir = os.path.join(_CHARS_ROOT, char_id)
        os.makedirs(cdir, exist_ok=True)
        with open(os.path.join(cdir, '.medusa_origin'), 'w', encoding='utf-8') as fh:
            json.dump({'origin': 'medusa', 'char_id': char_id}, fh)
    except OSError as _exc:
        _zyg_log.warning('medusa origin marker for %s not written, origin-aware views may miss it: %s', char_id, _exc)


# ── Kanban board mapping (the 'medusa' template) ─────────────────────────────
# Card titles here MUST match the card `prompt` strings in the TEMPLATES.medusa
# board defined in kanban_assets/kanban_main.js.
_CARD_ORDER = [
    'Swimwear Character Request',  # 0 — request approved / run started
    'Per-Cell Contact Sheet',  # 1 — sheet_generate
    'Tile Crop + Identity QC',  # 2 — tile_crop / identity_qc
    'Caption Training Set',  # 3 — captions
    'FLUX LoRA Training',  # 4 — lora_training
    'Angle Expansion + LoRA v2',  # 5 — angle_expansion / lora_refine
    'Character Ready',  # 6 — done
]
_STAGE_TO_CARD_IDX = {
    'queued': 0,
    'sheet_generate': 1,
    'awaiting_approval': 1,
    'tile_crop': 2,
    'identity_qc': 2,
    'captions': 3,
    'lora_training': 4,
    'angle_expansion': 5,
    'lora_refine': 5,
    'done': 6,
}


def _cards_for_stage(stage: str, status: str) -> dict:
    idx = _STAGE_TO_CARD_IDX.get(stage, 0)
    cards: dict[str, str] = {}
    for i, title in enumerate(_CARD_ORDER):
        if status == 'error' and i == idx:
            cards[title] = 'error'
        elif status == 'done' or i < idx:
            cards[title] = 'done'
        elif i == idx:
            cards[title] = 'running'
        else:
            cards[title] = 'queued'
    return cards


def _card_times(job: dict) -> dict:
    """-> {card title: {started_at, elapsed_s, since_s, running}} for the dialog.

    Several stages share one card (``tile_crop`` and ``identity_qc`` are both
    'Tile Crop + Identity QC'), so a card starts at the first stamp that maps to
    it and ends at the first stamp that maps to a later card.  Runs recorded
    before the timeline carried timestamps yield nothing, and the board renders
    '—' rather than a made-up zero.
    """
    import time as _t

    rows = [
        e for e in (job.get('stage_timeline') or []) if isinstance(e, dict) and isinstance(e.get('ts'), (int, float))
    ]
    if not rows:
        return {}
    status = job.get('status') or 'running'
    running = status not in ('done', 'error', 'failed', 'cancelled')
    now = _t.time()
    last = max(float(r['ts']) for r in rows)
    # (card index, epoch) in the order the run reached them.
    marks = []
    for r in rows:
        idx = _STAGE_TO_CARD_IDX.get(str(r.get('name') or ''))
        if idx is None:
            continue
        if marks and marks[-1][0] == idx:
            continue  # same card, still its first stamp
        marks.append((idx, float(r['ts'])))
    out = {}
    for n, (idx, start) in enumerate(marks):
        card = _CARD_ORDER[idx]
        if n + 1 < len(marks):
            end, is_open = marks[n + 1][1], False
        elif running:
            end, is_open = now, True
        else:
            end, is_open = last, False  # freeze a dead run at its last stamp
        out[card] = {
            'started_at': _iso(start),
            'ended_at': None if is_open else _iso(end),
            'elapsed_s': round(max(0.0, end - start), 1),
            'since_s': round(max(0.0, now - start), 1),
            'running': is_open,
        }
    return out


def _iso(epoch: float) -> str | None:
    """Epoch -> local ISO-8601 with offset, the format every other board ships."""
    from datetime import datetime as _dt

    try:
        return _dt.fromtimestamp(float(epoch)).astimezone().isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _latest_job() -> dict | None:
    if not _medusa_jobs:
        return None
    return max(_medusa_jobs.values(), key=lambda j: j.get('started_ts', 0))


# ── Worker ───────────────────────────────────────────────────────────────────
def _bg_medusa_pipeline(char_id: str, params: dict) -> None:
    """Runs on a daemon thread once a request is approved."""
    import time as _time
    from zyg_workflows import medusa_pipeline as _mp

    try:
        from zyg_workflows import contact_sheet_pipeline as _csp

        trigger_token = _csp.trigger_token_for(char_id)
    except Exception:
        trigger_token = f'ZYG_CHAR_{char_id[:6].upper()}'

    job: dict = {
        'char_id': char_id,
        'department': 'medusa',
        'pipeline': 'medusa_swimwear',
        'params': params,
        'status': 'running',
        'stage': 'queued',
        'model_family': 'flux',
        # Angle plan comes from the approved request (Character Studio picker);
        # run_medusa_pipeline re-resolves it from params and wins over this.
        'angle_set': (params or {}).get('angle_set') or 'extended',
        'angle_ids': list((params or {}).get('angle_ids') or []),
        'sheet_mode': 'auto',
        'kick_lora': True,
        'flywheel': True,
        'trigger_token': trigger_token,
        'started_ts': _time.time(),
        'stage_timeline': [],
        'events': [],
    }
    _medusa_jobs[char_id] = job
    _save_job(char_id, job)
    _write_origin_marker(char_id)  # durable origin stamp (before generation starts)

    def _log(msg: Any = '', *_a: Any, **_k: Any) -> None:
        ev = job['events']
        ev.append(str(msg))
        if len(ev) > 50:
            del ev[:-50]
        _save_job(char_id, job)

    def _on_stage(stage: str) -> None:
        # Timestamped since 2026-08-26: the entries used to be bare stage-name
        # strings, so the Kanban card dialog had nothing to date its Started and
        # Duration rows with and showed "0s ago / 0s" for every Medusa card.
        job['stage'] = stage
        job['stage_timeline'].append({'name': stage, 'ts': _time.time()})
        _save_job(char_id, job)

    def _on_cells(done: int, total: int) -> None:
        job['cells_done'] = done
        job['cells_total'] = total
        _save_job(char_id, job)

    try:
        _mp.run_medusa_pipeline(
            job,
            log_fn=_log,
            on_stage=_on_stage,
            on_cell_progress=_on_cells,
        )
        job['status'] = 'done'
        job['stage'] = 'done'
    except Exception as exc:  # noqa: BLE001 — surface any failure to the board
        job['status'] = 'error'
        job['error'] = str(exc)[:500]
        _log(f'Medusa pipeline error: {exc}', level='ERROR')
    finally:
        _write_origin_marker(char_id)  # re-assert now the char dir certainly exists
        _save_job(char_id, job)


# ── Endpoints ────────────────────────────────────────────────────────────────
@bp.route('/api/medusa/generate', methods=['POST'])
def api_medusa_generate():
    """Park a swimwear-character request for operator approval."""
    from zyg_workflows import medusa_pipeline as _mp

    body = request.get_json(silent=True) or {}

    # ADULTS-ONLY FLOOR (restored 2026-09-18, medusa_age_gate). The 2026-08-06
    # removal of MedusaAgeError/MedusaPromptError was survivable while the
    # Medusa base was stock Qwen-Image; it stops being survivable now that
    # bp_medusa_models can train a base LoRA that removes that limit. This is
    # an AGE check only — it constrains nothing else about the request, and it
    # has no environment override by design.
    try:
        from zyg_workflows import medusa_age_gate as _age

        _age.assert_adult_request(body)
    except _age.MedusaAgeError as _age_exc:
        return jsonify({'error': str(_age_exc), 'code': 'adults_only'}), 400

    # build_medusa_params itself no longer raises (MedusaAgeError/
    # MedusaPromptError were removed 2026-08-06 — see medusa_pipeline.py's
    # module docstring); the gate above is what rejects now.
    params = _mp.build_medusa_params(body)

    name = (body.get('name') or '').strip() or 'Swimwear Model'
    char_id = uuid.uuid4().hex[:12]
    req_id = uuid.uuid4().hex[:16]

    with _IO_LOCK:
        rows = _pending_load()
        rows.append(
            {
                'id': req_id,
                'char_id': char_id,
                'label': f'Medusa swimwear — {name}',
                'name': name,
                'pipeline': 'medusa',
                'params': params,
                'status': 'pending',
                'created_at': _now_iso(),
                'decided_at': None,
                'approved_job_id': None,
            }
        )
        _pending_save(rows)

    return jsonify(
        {
            'ok': True,
            'pending': True,
            'pending_id': req_id,
            'char_id': char_id,
            'label': f'Medusa swimwear — {name}',
            'message': 'Parked for operator approval.',
        }
    ), 202


@bp.route('/api/medusa/angles', methods=['GET'])
def api_medusa_angles():
    """The angle catalog the Character Studio picker renders.

    Served from the generator's own constants so the picker can never offer an
    angle the per-cell engine does not know how to render.
    """
    from zyg_workflows import medusa_pipeline as _mp

    try:
        return jsonify({'ok': True, **_mp.angle_catalog()})
    except Exception as exc:  # noqa: BLE001 - the picker needs a reason, not a 500 page
        return jsonify({'ok': False, 'error': f'angle catalog unavailable: {exc}'}), 503


@bp.route('/api/medusa/pending', methods=['GET'])
def api_medusa_pending():
    rows = _pending_load()
    pending = [r for r in rows if r.get('status') in ('pending', 'queued')]
    return jsonify({'ok': True, 'pending': pending, 'count': len(pending), 'all': rows[-50:]})


@bp.route('/api/medusa/pending/<req_id>/decide', methods=['POST'])
def api_medusa_decide(req_id: str):
    body = request.get_json(silent=True) or {}
    action = (body.get('action') or '').strip().lower()
    if action not in ('allow', 'approve', 'decline', 'deny'):
        return jsonify({'ok': False, 'error': "action must be 'allow' or 'decline'"}), 400

    with _IO_LOCK:
        rows = _pending_load()
        rec = next((r for r in rows if r.get('id') == req_id), None)
        if not rec:
            return jsonify({'ok': False, 'error': 'unknown pending id'}), 404
        if rec.get('status') not in ('pending', 'queued'):
            return jsonify({'ok': False, 'error': f'already {rec.get("status")}'}), 409

        if action in ('decline', 'deny'):
            rec['status'] = 'declined'
            rec['decided_at'] = _now_iso()
            _pending_save(rows)
            return jsonify({'ok': True, 'status': 'declined'})

        rec['status'] = 'approved'
        rec['decided_at'] = _now_iso()
        rec['approved_job_id'] = rec['char_id']
        _pending_save(rows)
        char_id = rec['char_id']
        params = rec.get('params') or {}

    threading.Thread(
        target=_bg_medusa_pipeline,
        args=(char_id, params),
        daemon=True,
        name=f'medusa-{char_id[:8]}',
    ).start()
    return jsonify({'ok': True, 'status': 'approved', 'char_id': char_id})


@bp.route('/api/medusa/jobs', methods=['GET'])
def api_medusa_jobs():
    jobs = [
        {
            'char_id': j.get('char_id'),
            'status': j.get('status'),
            'stage': j.get('stage'),
            'name': (j.get('params') or {}).get('name'),
            'cells_done': j.get('cells_done'),
            'cells_total': j.get('cells_total'),
        }
        for j in _medusa_jobs.values()
    ]
    return jsonify({'ok': True, 'jobs': jobs})


def _cors(resp):
    """The Workflows board is served from :8899 and polls this on :5000, so the
    answer is cross-origin and a browser drops it without this header — the board
    then shows a Medusa run as idle for ever. Read-only status, same one-line
    pattern the other board endpoints use (bp_pipeline_api.py). The board's own
    origin has to be listed in ZYG_CORS_ORIGINS — see cors.py."""
    return apply_cors(resp, request)


def _assistant_activity() -> tuple[int, str]:
    """(running turns, label) for Vicky/Victor inside the Medusa app.

    Returns (0, '') for a missing, unreadable or stale beacon — an unknown
    assistant is reported as idle, never as busy.
    """
    import time as _time

    try:
        with open(_VICKY_BEACON, 'r', encoding='utf-8') as fh:
            b = json.load(fh)
        if not isinstance(b, dict):
            return 0, ''
        n = int(b.get('running') or 0)
        if n <= 0 or (_time.time() - float(b.get('ts') or 0)) > _BEACON_STALE_S:
            return 0, ''
        return n, str(b.get('label') or 'Assistant working')
    except Exception:  # noqa: BLE001
        return 0, ''


def _peer_activity() -> tuple[int, str]:
    """(running jobs, label) published by Medusa renders in OTHER processes.

    One file per source in _PEER_BEACON_DIR, written by the process doing the
    work. Missing, unreadable or stale files are read as idle, never as busy —
    the same rule _assistant_activity() applies, for the same reason: a service
    killed mid-render must not leave the board claiming a live workflow.
    """
    import glob
    import time as _time

    total = 0
    labels: list[str] = []
    try:
        paths = sorted(glob.glob(os.path.join(_PEER_BEACON_DIR, '*.json')))
    except Exception:  # noqa: BLE001
        return 0, ''
    now = _time.time()
    for path in paths:
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                b = json.load(fh)
            if not isinstance(b, dict):
                continue
            n = int(b.get('running') or 0)
            if n <= 0 or (now - float(b.get('ts') or 0)) > _BEACON_STALE_S:
                continue
            total += n
            lab = str(b.get('label') or '').strip()
            if lab and lab not in labels:
                labels.append(lab)
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('skipping unusable medusa peer beacon: %s', _exc)
            continue
    return total, ' · '.join(labels)


def _render_activity() -> tuple[int, str]:
    """(running jobs, label) for the Medusa app's OTHER render paths — Training
    (contact sheet, body dataset, LoRA run) and Models (caption, train, sample).

    Before 2026-09-22 only the swimwear sheet job and an assistant turn counted,
    so the Medusa app could spend an hour rendering and the board read idle.
    Modules are looked up in sys.modules, never imported: a module this process
    has not loaded cannot be running anything, and an import here would pull
    detector/trainer code into a status poll that fires every 500 ms.
    """
    import sys

    parts: list[str] = []

    sheet = sys.modules.get('zyg_workflows.medusa_sheet_service')
    if sheet is not None:
        try:
            with sheet._jobs_lock:
                n = sum(1 for j in sheet._jobs.values() if j.get('running'))
            if n:
                parts.append(f'Contact sheet ×{n}' if n > 1 else 'Contact sheet')
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('contact sheet job count unavailable: %s', _exc)

    training = sys.modules.get('zyg_dashboard.bp_medusa_training')
    if training is not None:
        try:
            with training._body_lock:
                n = sum(1 for j in training._body_jobs.values() if j.get('running'))
            if n:
                parts.append('Body dataset')
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('body dataset job count unavailable: %s', _exc)

    model_jobs = sys.modules.get('zyg_workflows.medusa_model_jobs')
    busy_models: set[str] = set()
    if model_jobs is not None:
        try:
            with model_jobs._LOCK:
                busy_models = set(model_jobs._BUSY)
                phases = [str((model_jobs._STATE.get(m) or {}).get('phase') or 'working') for m in busy_models]
            for ph in sorted(set(phases)):
                parts.append('Model · ' + ph)
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('model job state unavailable: %s', _exc)

    # LoRA runs: Training characters are mdt_*, Models are mdm_*. A model still
    # in its caption/sample chain is already counted above.
    lts = sys.modules.get('zyg_workflows.lora_trainer_service')
    if lts is not None:
        try:
            n = sum(
                1
                for cid, job in list(lts._training_jobs.items())
                if str(cid).startswith(('mdt_', 'mdm_'))
                and cid not in busy_models
                and not getattr(job, 'done', False)
                and not getattr(job, 'failed', False)
            )
            if n:
                parts.append(f'LoRA training ×{n}' if n > 1 else 'LoRA training')
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('lora training job count unavailable: %s', _exc)

    return len(parts), ' · '.join(parts)


@bp.route('/api/medusa/kanban_status', methods=['GET'])
@_rate_exempt
def api_medusa_kanban_status():
    """Board status. `active`/`active_label` answer one question for the
    Workflows board — is a Medusa workflow running right now — and count an
    assistant turn or any other render in the Medusa app as one, which
    `status` (a sheet render, and nothing else) cannot express."""
    a_n, a_label = _assistant_activity()
    r_n, r_label = _render_activity()
    p_n, p_label = _peer_activity()
    if r_n or p_n:
        a_n += r_n + p_n
        a_label = ' · '.join(x for x in (r_label, p_label, a_label) if x)
    job = _latest_job()
    if not job:
        return _cors(
            jsonify(
                {
                    'pipeline': 'medusa',
                    'template': 'medusa',
                    'cards': {},
                    'card_times': {},
                    'model_family': 'flux',
                    'active': a_n > 0,
                    'active_label': a_label,
                }
            )
        )
    cards = _cards_for_stage(job.get('stage') or 'queued', job.get('status') or 'running')
    running = job.get('status') == 'running'
    if running:
        label = 'Generating · ' + str(job.get('stage') or 'running')
        if a_n > 0:
            label += ' · ' + a_label
    else:
        label = a_label
    return _cors(
        jsonify(
            {
                'pipeline': job.get('char_id'),
                'template': 'medusa',
                'cards': cards,
                'card_times': _card_times(job),
                'model_family': 'flux',
                'status': job.get('status'),
                'stage': job.get('stage'),
                'active': bool(running or a_n > 0),
                'active_label': label,
            }
        )
    )


def _now_iso() -> str:
    import datetime

    return datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')


# ── Rehydrate live jobs from disk on import (survives restarts) ──────────────
def _rehydrate() -> None:
    try:
        import glob

        for path in glob.glob(os.path.join(_RUNTIME_DIR, 'medusa_*_state.json')):
            job = _load_json(path, None)
            if isinstance(job, dict) and job.get('char_id'):
                _medusa_jobs[job['char_id']] = job
    except Exception as _exc:
        _zyg_log.warning('medusa job rehydrate failed, live jobs are not restored: %s', _exc)


_rehydrate()
