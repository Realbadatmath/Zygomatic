# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Moved verbatim out of bp_pipeline_api.py (lines 574-731) when that 1,782-line module
# became this package. Zero logic edits: the bodies below are byte-for-byte the original.

import logging as _zyg_logging
import json
import os
import re
from flask import (
    jsonify,
    request,
    send_file,
)
from zyg_workflows import provenance_seal as _seal

from zyg_workflows.char_state_service import (
    _creature_state_path,
)

from zyg_dashboard.crewai_web_gui import (  # noqa: E402  late: crewai_web_gui imports this blueprint at its bottom, so `bp` must exist first
    _start_creature_pipeline_internal,
    limiter,
)
from zyg_dashboard.gui.runtime_state import (  # noqa: E402
    _char_gen_jobs,
    _creature_gen_jobs,
    _workflow_jobs,
)
from zyg_dashboard.gui.timeutil import _ams_iso  # noqa: E402


from zyg_dashboard.bp_pipeline_api import bp  # the Blueprint the package __init__ creates

_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_pipeline_api')


def approve_creature_review(creature_id: str) -> tuple[dict, int]:
    """Resume a creature parked at awaiting_review — captions → LoRA training →
    judged previews. Refuses while any pipeline runs.

    2026-08-26: lifted out of the route so the Agent Zero decide handler drives
    the SAME code path as the API. The operator now has three doors onto one
    gate (Zero card, Kanban banner, curl) and they cannot drift apart.
    """
    if not re.match(r'^[a-f0-9]{12}$', creature_id or ''):
        return {'error': 'bad creature id'}, 400
    running = [pid for pid, j in _workflow_jobs.items() if j.get('status') == 'running']
    running += [cid for cid, j in _creature_gen_jobs.items() if j.get('status') == 'running']
    running += [cid for cid, j in _char_gen_jobs.items() if j.get('status') == 'running']
    if running:
        return {'error': 'pipeline_busy', 'running_id': running[0]}, 409
    info = _start_creature_pipeline_internal(resume_creature_id=creature_id, phase='train')
    if 'error' in info:
        return info, 409
    # Close the pending card whichever door was used, so an approval by curl
    # does not leave Zero blinking at a gate that is already open.
    try:
        from zyg_workflows import creature_training_service as _cts_card

        _cts_card.resolve_review_card(creature_id, 'approved')
    except Exception as _exc:
        _zyg_log.warning('closing the creature review card as approved failed, Zero still shows the gate: %s', _exc)
    return {'success': True, **info}, 200


def reject_creature_review(creature_id: str, reason: str = '') -> tuple[dict, int]:
    """Mark a parked sheet rejected (nothing trains; the dataset stays on disk)."""
    if not re.match(r'^[a-f0-9]{12}$', creature_id or ''):
        return {'error': 'bad creature id'}, 400
    from zyg_workflows.char_state_service import _creature_save_state as _cr_save

    job = _creature_gen_jobs.get(creature_id)
    if job is None:
        try:
            with open(_creature_state_path(creature_id), encoding='utf-8') as _fh:
                job = json.load(_fh)
            _creature_gen_jobs[creature_id] = job
        except Exception:
            return {'error': 'not found'}, 404
    if job.get('status') != 'awaiting_review':
        return {'error': f'creature is {job.get("status")}, not awaiting_review'}, 409
    job['status'] = 'rejected'
    job['error'] = (reason or 'rejected at sheet review')[:300]
    job['ended'] = _ams_iso()
    job['current_stage'] = 'Sheet Review'
    _cr_save(creature_id)
    try:
        from zyg_workflows import creature_training_service as _cts_card

        _cts_card.resolve_review_card(creature_id, 'declined')
    except Exception as _exc:
        _zyg_log.warning('closing the creature review card as declined failed, Zero still shows the gate: %s', _exc)
    return {'success': True, 'creature_id': creature_id, 'status': 'rejected'}, 200


@bp.route('/api/internal/creature/<creature_id>/approve', methods=['POST'])
@limiter.exempt
def api_internal_creature_approve(creature_id):
    """Review gate (2026-08-25): resume a creature parked at awaiting_review."""
    payload, status = approve_creature_review(creature_id)
    return jsonify(payload), status


@bp.route('/api/internal/creature/<creature_id>/resume', methods=['POST'])
@limiter.exempt
def api_internal_creature_resume(creature_id):
    """Resume an interrupted/failed creature run (sheet checkpoints reused).
    Body {phase: full|sheet} — default full."""
    if not re.match(r'^[a-f0-9]{12}$', creature_id or ''):
        return jsonify({'error': 'bad creature id'}), 400
    running = [pid for pid, j in _workflow_jobs.items() if j.get('status') == 'running']
    running += [cid for cid, j in _creature_gen_jobs.items() if j.get('status') == 'running' and cid != creature_id]
    running += [cid for cid, j in _char_gen_jobs.items() if j.get('status') == 'running']
    if running:
        return jsonify({'error': 'pipeline_busy', 'running_id': running[0]}), 409
    data = request.get_json(silent=True) or {}
    phase = str(data.get('phase') or 'full')
    if phase not in ('full', 'sheet'):
        return jsonify({'error': 'phase must be full or sheet'}), 400
    info = _start_creature_pipeline_internal(resume_creature_id=creature_id, phase=phase)
    if 'error' in info:
        return jsonify(info), 409
    return jsonify({'success': True, **info})


@bp.route('/api/internal/creature/<creature_id>/reject', methods=['POST'])
@limiter.exempt
def api_internal_creature_reject(creature_id):
    """Review gate: mark a parked sheet rejected (nothing trains; the dataset stays on disk)."""
    data = request.get_json(silent=True) or {}
    payload, status = reject_creature_review(creature_id, str(data.get('reason') or ''))
    return jsonify(payload), status


@bp.route('/api/internal/creature/<creature_id>/sheet')
@limiter.exempt
def api_internal_creature_sheet(creature_id):
    """Serve the reviewed sheet for a creature — the picture the review gate is
    ABOUT. Added 2026-08-26: the gate had no image route at all, so neither the
    Zero card nor the board could show the operator what they were approving.
    ``?download=1`` returns it as an attachment named after the creature."""
    if not re.match(r'^[a-f0-9]{12}$', creature_id or ''):
        return jsonify({'error': 'bad creature id'}), 400
    from zyg_workflows import creature_training_service as _cts_sheet

    ds = os.path.join(_cts_sheet.DATASET_ROOT, creature_id)
    for cand in (os.path.join(ds, 'contact_sheet', 'sheet.png'), os.path.join(ds, 'sheet.png')):
        if os.path.isfile(cand):
            name = re.sub(r'[^A-Za-z0-9._-]+', '_', ((_read_creature_brief_name(ds) or creature_id) + '_sheet.png'))
            return send_file(
                cand,
                mimetype='image/png',
                as_attachment=request.args.get('download') in ('1', 'true', 'yes'),
                download_name=name,
            )
    return jsonify({'error': 'no sheet on disk for this creature'}), 404


def _read_creature_brief_name(dataset_dir: str) -> str:
    for fn in ('manifest.json', 'brief.json'):
        try:
            with open(os.path.join(dataset_dir, fn), encoding='utf-8') as fh:
                n = (json.load(fh) or {}).get('name')
            if n:
                return str(n)
        except (OSError, ValueError) as _exc:
            # Best effort only: both files are optional and the download name
            # falls back to the creature id.
            _zyg_log.debug('creature brief name unreadable from %s: %s', fn, _exc)
            continue
    return ''


def _seal_gate_outputs(entries):
    """Annotate the exposed output files with their content-credential status.

    This listing is what zero-public reads to decide what a stranger may download, so it is
    the last place a deliverable can still be held back. Each record gains ``sealed`` (a
    cheap manifest read); under ``ZYG_C2PA=strict`` an unsealed file is not offered at all.

    *entries* carry a ``path`` key, which is internal and never reaches the response.
    Returns ``(kept, withheld)`` — ``withheld`` is None outside strict mode, so the response
    shape only grows the ``unsealed_withheld`` key where it means something.
    """
    strict = (os.environ.get('ZYG_C2PA', 'warn') or '').strip().lower() == 'strict'
    kept, withheld = [], []
    for entry in entries:
        record = {k: v for k, v in entry.items() if k != 'path'}
        record['sealed'] = bool(_seal.is_sealed(entry['path']))
        if strict and not record['sealed']:
            withheld.append(record['name'])
            continue
        kept.append(record)
    return kept, (withheld if strict else None)
