# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contact-sheet and production pause/resume routes.

Verbatim move of bp_storyteller.py:574-1037 (2026-10-06 split).
"""

import json
import logging as _zyg_logging
import os
import uuid
from typing import Tuple

from flask import jsonify, request

from zyg_dashboard.bp_storyteller import (  # noqa: E402  the package __init__ binds these before it imports this module
    _ZPUB_PENDING_LOCK,
    _char_gen_jobs,
    _contact_sheet_emit,
    _contact_sheet_jobs,
    _contact_sheet_launch_run,
    _contact_sheet_mark_manifest_approved,
    _contact_sheet_parse_start_payload,
    _contact_sheet_resume_run,
    _contact_sheet_state_path,
    _contact_sheet_worker_alive,
    _runtime_path,
    _zero_audit_log,
    _zpub_pending_load,
    _zpub_pending_save,
    bp,
    gui_state,
    limiter,
)
from zyg_dashboard.bp_storyteller.guards import (
    _CHARS_DATASET_ROOT,
    _CHAR_ID_RE,
    _CHAR_ID_WIDE_RE,
    _env_on,
)

_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_storyteller')


@bp.route('/api/internal/storyteller/contact-sheet/start', methods=['POST'])
@limiter.exempt
def api_internal_contact_sheet_start():
    """
    Multi-angle contact sheet pipeline: sheet → approve → tiles → identity QC →
    captions → LoRA → angle expansion (flywheel) → LoRA v2.

    JSON body: char_id?, name, gender, hair_color, eye_color, skin_tone, style,
    model_family (flux|sdxl), kick_lora, auto_approve, rows, cols,
    sheet_mode (mock|cells|single_canvas|dual_canvas|pose_locked_cells|auto — auto = pose stack or N×2×3 sheets),
    angle_set (extended = 8 sheets / 48 angles, default | classic = 4 sheets / 24),
    flywheel (bool — LoRA v1 generates hard angles, retrains as v2; default on).
    """
    data = request.get_json(silent=True) or {}
    p = _contact_sheet_parse_start_payload(data)
    char_id = p['char_id']
    params = p['params']
    mf = p['mf']
    auto_approve = p['auto_approve']

    # Pre-activation gate: park the run in the Agent Zero pending queue (same
    # store the documentary manual-approval flow uses) until the operator
    # allows it. Bypassed by the decide handler (zero_approved) and smoke runs.
    _require_zero = os.environ.get(
        'ZYG_CONTACT_SHEET_REQUIRE_ZERO_APPROVAL',
        '1',
    ).strip().lower() not in ('0', 'false', 'no', 'off')
    if _require_zero and not data.get('zero_approved') and not auto_approve:
        import datetime as _dt

        req_id = 'preq_' + uuid.uuid4().hex[:12]
        snapshot = dict(data)
        snapshot['char_id'] = char_id
        with _ZPUB_PENDING_LOCK:
            _pdata = _zpub_pending_load()
            _pdata.append(
                {
                    'id': req_id,
                    'token': '',
                    'label': f'Contact sheet — {params["name"]}',
                    'invite_url': '',
                    'prompt': (
                        f'{params["name"]} — {params["gender"]}, {params["hair_color"]} hair, '
                        f'{params["eye_color"]} eyes, {params["skin_tone"]} skin, {params["style"]}; '
                        f'multi-angle contact sheet + LoRA ({mf.upper()})'
                    ),
                    'pipeline': 'contact_sheet',
                    'voice': '',
                    'style': params['style'],
                    'model': mf,
                    'ip': request.remote_addr or 'unknown',
                    'session_id': '',
                    'char_id': char_id,
                    'body_snapshot': snapshot,
                    'requested_at': _dt.datetime.utcnow().isoformat() + 'Z',
                    'status': 'pending',
                    'decided_at': None,
                    'approved_job_id': None,
                }
            )
            _zpub_pending_save(_pdata)
        _zero_audit_log(
            'contact_sheet_approval_requested',
            {
                'req_id': req_id,
                'char_id': char_id,
                'name': params['name'],
            },
        )
        return jsonify(
            {
                'pending': True,
                'pending_id': req_id,
                'char_id': char_id,
                'message': 'Contact sheet run queued — approve it via Agent Zero to start generation.',
                'resolved': {
                    'name': params.get('name'),
                    'gender': params.get('gender'),
                    'age': params.get('age'),
                },
            }
        ), 202

    payload, _status = _contact_sheet_launch_run(p)
    return jsonify(payload), _status


@bp.route('/api/internal/storyteller/contact-sheet/status/<char_id>')
@limiter.exempt
def api_internal_contact_sheet_status(char_id: str):
    from zyg_workflows import contact_sheet_pipeline as _csp

    job = _contact_sheet_jobs.get(char_id) or {}
    if not job:
        try:
            with open(_contact_sheet_state_path(char_id), encoding='utf-8') as fh:
                job = json.load(fh)
        except Exception:
            job = {}
    manifest = _csp.load_manifest(char_id) or {}
    # Selected-vs-delivered attribute disclosure (2026-07-20): the anchor gate
    # ships the closest anchor FLUX could render and syncs the bible/params to
    # delivered reality, so the operator must see what actually shipped before
    # committing to training. Colour deltas (eye/hair/skin) are hard — the LoRA
    # will render them; structure deltas (face/eye shape, age band) are advisory
    # — FLUX cannot reliably hit them. Sourced from params['_attr_deltas'],
    # written by the pipeline's attribute + structure gates.
    _deltas_raw = ((job.get('params') or {}).get('_attr_deltas')) or {}
    _LABELS = {
        'eye_color': 'Eye colour',
        'hair_color': 'Hair colour',
        'skin_tone': 'Skin tone',
        'face_shape': 'Face shape',
        'eye_shape': 'Eye shape',
        'age_band': 'Apparent age',
    }
    attribute_deltas = [
        {
            'attribute': k,
            'label': _LABELS.get(k, k.replace('_', ' ').title()),
            'selected': (d or {}).get('selected'),
            'delivered': (d or {}).get('delivered'),
            'advisory': bool((d or {}).get('advisory')),
        }
        for k, d in _deltas_raw.items()
        if (d or {}).get('selected') and (d or {}).get('delivered')
    ]
    return jsonify(
        {
            'char_id': char_id,
            'status': job.get('status', 'unknown'),
            'stage': job.get('stage', 'unknown'),
            'model_family': job.get('model_family', 'flux'),
            'attribute_deltas': attribute_deltas,
            'approved': bool(job.get('approved') or manifest.get('approved')),
            'sheet_path': manifest.get('sheet_path') or _csp.master_sheet_path(char_id),
            'sheet_exists': os.path.isfile(_csp.master_sheet_path(char_id)),
            'tile_count': job.get('tile_count') or len(manifest.get('tiles') or []),
            'trigger_token': job.get('trigger_token') or _csp.trigger_token_for(char_id),
            'error': job.get('error'),
            'lora_failed': job.get('lora_failed'),
            'contact_sheet_url': _csp.contact_sheet_image_api_path(char_id),
            'preview_url': _csp.contact_sheet_image_api_path(char_id)
            if os.path.isfile(_csp.master_sheet_path(char_id))
            else None,
            'awaiting_approval': job.get('stage') == 'awaiting_approval',
            'creation_pipeline': 'multi_angle_contact_sheet',
            'sheet_cells_done': job.get('sheet_cells_done'),
            'sheet_cells_total': job.get('sheet_cells_total'),
            'sheet_substage': job.get('sheet_substage'),
            'generation_mode': job.get('generation_mode') or manifest.get('generation_mode'),
            'dual_sheet': bool(job.get('dual_sheet') or manifest.get('dual_sheet')),
            'sheet_count': job.get('sheet_count') or manifest.get('sheet_count'),
            'total_tiles': manifest.get('total_tiles') or _csp.DUAL_SHEET_TOTAL_ANGLES,
            'angle_set': job.get('angle_set') or manifest.get('angle_set'),
            'identity_qc': job.get('identity_qc') or manifest.get('identity_qc'),
            'flywheel': manifest.get('flywheel'),
            'lora_refined': bool(job.get('lora_refined')),
            'expansion_kept': job.get('expansion_kept'),
        }
    )


@bp.route('/api/internal/storyteller/contact-sheet/approve/<char_id>', methods=['POST'])
@limiter.exempt
def api_internal_contact_sheet_approve(char_id: str):
    """Approve the contact sheet so the background worker continues past the gate."""
    from zyg_workflows import contact_sheet_pipeline as _csp

    job = _contact_sheet_jobs.get(char_id)
    if not job:
        return jsonify({'char_id': char_id, 'ok': False, 'error': 'job not found'}), 404
    if job.get('stage') != 'awaiting_approval' and not job.get('approved'):
        if job.get('status') == 'done':
            return jsonify({'char_id': char_id, 'ok': True, 'message': 'already complete'})
        # Stale-dict fallback: if a state reload severed this dict from its
        # worker, `stage` freezes at an old snapshot while the run is really
        # sitting at the gate. The worker's actual trigger is the manifest
        # `approved` flag, so approve whenever the evidence says it's waiting:
        # sheet on disk + (timeline says Awaiting Approval or worker alive).
        _stale_waiting = _csp.master_sheet_exists(char_id) and (
            (job.get('current_stage') or '').strip().lower() == 'awaiting approval'
            or _contact_sheet_worker_alive(char_id)
        )
        if not _stale_waiting:
            return jsonify(
                {
                    'char_id': char_id,
                    'ok': False,
                    'error': f'not awaiting approval (stage={job.get("stage")})',
                }
            ), 400
    job['approved'] = True
    # Preserves manifest extras (dual-sheet specs, anchors, QC) — the old
    # bare write_manifest here stripped them and broke dual-sheet tiling.
    _contact_sheet_mark_manifest_approved(char_id)
    _contact_sheet_emit(char_id, 'Contact sheet approved — continuing pipeline')
    return jsonify({'char_id': char_id, 'ok': True, 'approved': True})


@bp.route('/api/internal/storyteller/contact-sheet/pause/<char_id>', methods=['POST'])
@limiter.exempt
def api_internal_contact_sheet_pause(char_id: str):
    """Pause one running production run. It parks at its current stage and frees
    its VRAM on the next per-cell / stage checkpoint (within one image)."""
    from zyg_workflows import pipeline_control as _pc

    job = _contact_sheet_jobs.get(char_id) or {}
    if job.get('status') not in ('running', None) and not _contact_sheet_worker_alive(char_id):
        # Allow pausing anything that still has a live worker; otherwise report.
        if job.get('status') == 'paused':
            return jsonify({'char_id': char_id, 'ok': True, 'already': 'paused'})
    reason = (request.get_json(silent=True) or {}).get('reason') or 'Paused by operator'
    _pc.pause(char_id, reason)
    _contact_sheet_emit(char_id, f'Pause requested — parking after current image ({reason})', level='WARN')
    return jsonify(
        {
            'char_id': char_id,
            'ok': True,
            'paused': True,
            'stage': job.get('stage'),
            'note': 'Run parks within one image and releases VRAM; use /resume to continue.',
        }
    )


@bp.route('/api/internal/storyteller/contact-sheet/resume/<char_id>', methods=['POST'])
@limiter.exempt
def api_internal_contact_sheet_resume(char_id: str):
    """Resume one paused run — relaunches the worker at its parked stage,
    skipping finished stages and reusing already-rendered cells."""
    payload, status = _contact_sheet_resume_run(char_id)
    return jsonify(payload), status


@bp.route('/api/internal/storyteller/pipeline/pause', methods=['POST'])
@limiter.exempt
def api_internal_pipeline_pause():
    """Pause a broad scope: 'scheduled' (block new/queued starts) or 'production'
    (park every running run + block new starts). Persists across restarts."""
    from zyg_workflows import pipeline_control as _pc

    data = request.get_json(silent=True) or {}
    scope = (data.get('scope') or '').strip().lower()
    reason = data.get('reason') or 'Paused by operator'
    if scope not in (_pc.SCOPE_SCHEDULED, _pc.SCOPE_PRODUCTION):
        return jsonify({'ok': False, 'error': "scope must be 'scheduled' or 'production'"}), 400
    _pc.pause(scope, reason)
    parked = []
    if scope == _pc.SCOPE_PRODUCTION:
        # Running workers self-park on their next checkpoint; note who's live.
        for cid, j in list(_contact_sheet_jobs.items()):
            if j.get('status') == 'running':
                parked.append(cid)
                _contact_sheet_emit(cid, 'Production paused — parking after current image', level='WARN')
        # 2026-07-31: affected_runs only ever listed contact-sheet jobs, so an
        # operator pausing production to free the GPU got ok:true while
        # character generation (Blender + SimpleTuner + FLUX previews) and the
        # preview sweep kept the card warm with no signal at all. Both now
        # honour the hold (see _check_char_stop / the sweep loop) and both are
        # reported here so the UI can show what is still winding down.
        for cid, j in list(_char_gen_jobs.items()):
            if j.get('status') == 'running':
                parked.append(cid)
        try:
            if (gui_state._CHAR_PREVIEW_SWEEP or {}).get('running'):
                parked.append('char-preview-sweep')
        except Exception as _exc:
            _zyg_log.debug('preview sweep state unavailable: %s', _exc)
    return jsonify({'ok': True, 'scope': scope, 'reason': reason, 'affected_runs': parked})


@bp.route('/api/internal/storyteller/pipeline/resume', methods=['POST'])
@limiter.exempt
def api_internal_pipeline_resume():
    """Resume a broad scope. For 'production', also relaunches every parked run."""
    from zyg_workflows import pipeline_control as _pc

    data = request.get_json(silent=True) or {}
    scope = (data.get('scope') or '').strip().lower()
    if scope not in (_pc.SCOPE_SCHEDULED, _pc.SCOPE_PRODUCTION):
        return jsonify({'ok': False, 'error': "scope must be 'scheduled' or 'production'"}), 400
    _pc.resume(scope)
    resumed = []
    if scope == _pc.SCOPE_PRODUCTION:
        for cid, j in list(_contact_sheet_jobs.items()):
            if j.get('status') == 'paused':
                _r, _st = _contact_sheet_resume_run(cid)
                if _st == 200:
                    resumed.append(cid)
    return jsonify({'ok': True, 'scope': scope, 'resumed_runs': resumed})


@bp.route('/api/internal/storyteller/pipeline/pause-state')
@limiter.exempt
def api_internal_pipeline_pause_state():
    """Report current pause scopes + per-run status for the UI controls."""
    from zyg_workflows import pipeline_control as _pc

    scopes = _pc.paused_scopes()
    runs = []
    for cid, j in list(_contact_sheet_jobs.items()):
        st = j.get('status')
        if st in ('running', 'paused'):
            runs.append(
                {
                    'char_id': cid,
                    'status': st,
                    'stage': j.get('paused_at_stage') if st == 'paused' else j.get('stage'),
                    'paused_reason': j.get('paused_reason'),
                    'name': (j.get('params') or {}).get('name'),
                }
            )
    return jsonify(
        {
            'scheduled_paused': _pc.is_paused(_pc.SCOPE_SCHEDULED),
            'production_paused': _pc.is_paused(_pc.SCOPE_PRODUCTION),
            'paused_scopes': scopes,
            'runs': runs,
        }
    )


@bp.route('/api/internal/storyteller/contact-sheet/image/<char_id>')
@limiter.exempt
def api_internal_contact_sheet_image(char_id: str):
    """Serve contact_sheet_master.png for library / approval UI."""
    import re as _re
    from zyg_workflows import contact_sheet_pipeline as _csp

    # 2026-07-31: the 12-hex-only gate made every legacy slug dir (33 on disk,
    # e.g. abel_van_haren) permanently un-reviewable — the approval queue emitted
    # review cards pointing here and the operator saw a blank card, then declined
    # a run they never actually saw. Widened for this READ-ONLY route to a
    # charset with no dots and no separators, so nothing can traverse; the
    # realpath containment check below is the real boundary either way.
    if not _CHAR_ID_RE.match(char_id):
        if not (_env_on('ZYG_CONTACT_SHEET_IMAGE_WIDE_IDS') and _CHAR_ID_WIDE_RE.match(char_id)):
            return '', 404
    # preview=<name> (2026-07-26): serve a calibration/preview PNG (e.g. the
    # Arcane style sweep grid) from the character's OWN style_preview_* dirs.
    # Path-safe: char_id is regex-validated above; the name is a strict basename
    # and the realpath-resolved candidate must stay inside the character's dir.
    _preview = (request.args.get('preview') or '').strip()
    if _preview:
        _pv = os.path.basename(_preview)
        if '..' in _pv or not _re.match(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$', _pv):
            return '', 404
        if not _pv.lower().endswith('.png'):
            _pv += '.png'
        _char_root = os.path.realpath(os.path.dirname(os.path.dirname(_csp.master_sheet_path(char_id))))
        for _sub in ('style_preview_arcane', 'style_preview_arcane_animation', 'contact_sheet'):
            _cand = os.path.realpath(os.path.join(_char_root, _sub, _pv))
            if _cand.startswith(_char_root + os.sep) and os.path.isfile(_cand):
                from flask import send_file as _sf_pv

                _rp = _sf_pv(_cand, mimetype='image/png')
                _rp.headers['Cache-Control'] = 'no-store, must-revalidate'
                return _rp
        return '', 404

    # 2026-07-31 (contract A): master_sheet_exists / library_preview_urls now
    # count multi-part contact_sheet_master_<x>.png, so list-chars advertises a
    # contact_sheet_url for characters that have parts but no stitched monolith
    # (an interrupted or declined 48-angle run). Serving only the monolith would
    # 404 exactly those cards. any_master_sheet_path resolves monolith-first,
    # then the alphabetically first part.
    def _resolve_master(cid: str) -> Tuple[str, bool]:
        _mono = _csp.master_sheet_path(cid)
        if os.path.isfile(_mono):
            return _mono, False
        _any = getattr(_csp, 'any_master_sheet_path', None)
        if callable(_any):
            try:
                _p = _any(cid)
                if _p and os.path.isfile(_p):
                    return _p, True
            except Exception as _exc:
                _zyg_log.debug('alternate master sheet lookup failed, using the canonical path: %s', _exc)
        return _mono, False

    # variant=training (2026-07-20): serve the training-set-only composite —
    # exactly the tiles an approval trains on, excluded tiles absent.
    _sheet_variant = 'master'
    if (request.args.get('variant') or '').strip().lower() == 'training':
        img_path = _csp.training_sheet_path(char_id)
        _sheet_variant = 'training'
        # The training sheet is only stitched after captions — at the EARLY
        # review parks (QC-skip, pass-rate safety valve, opt-in review gate) it
        # does not exist yet. Fall back to the master sheet so the review link
        # never 404s at exactly the QC-failure moments inspection matters most
        # (2026-07-22).
        if not os.path.isfile(img_path):
            img_path, _is_part = _resolve_master(char_id)
            # 2026-07-31: the fallback was SILENT. The caller asked for "exactly
            # the tiles an approval trains on" and got a superset including the
            # QC-rejected tiles, with nothing in the response saying so — the
            # 2026-07-16 Kira Dunn failure (17/49 bad cells trained) is exactly
            # what this review link exists to prevent. Declare the substitution.
            _sheet_variant = 'master_part_fallback' if _is_part else 'master_fallback'
    else:
        img_path, _is_part = _resolve_master(char_id)
        if _is_part:
            _sheet_variant = 'master_part'
    if not os.path.isfile(img_path):
        return '', 404
    # Containment: the widened id charset above cannot traverse, but keep the
    # served path provably inside the character dataset root regardless.
    try:
        _img_rp = os.path.realpath(img_path)
        _root_rp = os.path.realpath(_CHARS_DATASET_ROOT)
        if not _img_rp.startswith(_root_rp + os.sep):
            return '', 404
    except Exception:
        return '', 404
    from flask import send_file as _sf

    _emit_variant_hdr = _env_on('ZYG_SHEET_VARIANT_HEADER')
    want_download = (request.args.get('download') or '').strip().lower() in ('1', 'true', 'yes')
    if want_download:
        _rd = _sf(img_path, mimetype='image/png', as_attachment=True, download_name=f'contact_sheet_{char_id[:8]}.png')
        if _emit_variant_hdr:
            _rd.headers['X-Sheet-Variant'] = _sheet_variant
        return _rd
    _resp = _sf(img_path, mimetype='image/png')
    # no-store (2026-07-19): the sheet is re-stitched after QC repairs; a
    # cached copy hid the repaired sheet from the review flow.
    _resp.headers['Cache-Control'] = 'no-store, must-revalidate'
    _resp.headers['Pragma'] = 'no-cache'
    if _emit_variant_hdr:
        # 2026-07-31: 'training' = the real training composite, 'master_fallback'
        # = the full sheet standing in for a composite that is not stitched yet
        # (includes QC-EXCLUDED tiles). zpub must forward this and the review UI
        # must banner it — see the cross-file request in the audit report.
        _resp.headers['X-Sheet-Variant'] = _sheet_variant
    return _resp


@bp.route('/api/internal/storyteller/list-contact-sheets')
@limiter.exempt
def api_internal_list_contact_sheets():
    """Contact-sheet library: in-progress sheets and trained LoRA characters."""
    from zyg_workflows import contact_sheet_pipeline as _csp

    mf = (request.args.get('model_family') or '').strip().lower()
    if mf not in ('flux', 'sdxl'):
        mf = ''
    sheets = _csp.list_contact_sheet_library(
        model_family=mf,
        runtime_dir=_runtime_path(''),
    )
    # Medusa chars are isolated to the Medusa app — keep them out of this library.
    from zyg_dashboard import bp_medusa as _bm

    sheets = _bm.filter_out_medusa(sheets)
    return jsonify(
        {
            'sheets': sheets,
            'count': len(sheets),
            'pending_count': sum(1 for s in sheets if s.get('status') == 'running'),
            'trained_count': sum(1 for s in sheets if s.get('lora_ready')),
        }
    )
