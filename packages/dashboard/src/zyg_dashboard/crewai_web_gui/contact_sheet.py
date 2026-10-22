#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The contact-sheet review flow: approve, decline, push-to-review, launch.

Lines 1951-2568 of the original module, verbatim: the three manifest-state
mutators, the ``runtime.register`` call that hands the pipelines the three hooks
only a running dashboard has, the start-payload parser,
``_contact_sheet_launch_run`` and the character-preview sweep state.
"""

# Verbatim move: every name here is read back off zyg_dashboard.crewai_web_gui by the
# bp_* blueprints.
# (_CHAR_DEFAULT_MODEL_FAMILY is imported above and then re-bound at the bottom, which is what
# the original single module did to its own global. It is read before the re-binding, so that
# is not an F811 and needs no suppression.)

from zyg_dashboard.crewai_web_gui._bootstrap import (
    _CHAR_DEFAULT_MODEL_FAMILY,
    _ams_iso,
    _contact_sheet_jobs,
    _zero_audit_log,
    _zyg_log,
    gui_state,
    json,
    os,
    runtime,
    threading,
    uuid,
)
from zyg_dashboard.crewai_web_gui.security import _push_error_log
from zyg_dashboard.crewai_web_gui.pages import controller
from zyg_dashboard.crewai_web_gui.claude_clips import _clear_pipeline_halt
from zyg_workflows.char_state_service.contact_sheet import (
    _bg_contact_sheet_pipeline,
    _contact_sheet_save_state,
    _contact_sheet_state_path,
)
from zyg_workflows.pipeline_common import _parse_pipeline_model_family


def _contact_sheet_mark_manifest_approved(char_id: str) -> bool:
    """Set manifest approved=True PRESERVING extras (sheets specs, anchors, QC).

    The worker's wait_for_approval polls this flag; stripping extras here broke
    dual-sheet tile slicing downstream, so non-core keys must survive.
    """
    from zyg_workflows import contact_sheet_pipeline as _csp

    m = _csp.load_manifest(char_id) or {}
    extra = {
        k: m[k]
        for k in m
        if k
        not in (
            'char_id',
            'pipeline',
            'rows',
            'cols',
            'gutter_px',
            'cell_width',
            'cell_height',
            'sheet_path',
            'approved',
            'approved_at',
            'tiles',
            'updated_at',
        )
    }
    _csp.write_manifest(
        char_id,
        rows=int(m.get('rows') or _csp.DEFAULT_ROWS),
        cols=int(m.get('cols') or _csp.DEFAULT_COLS),
        gutter=int(m.get('gutter_px') or _csp.DEFAULT_GUTTER),
        cell_w=int(m.get('cell_width') or _csp.DEFAULT_CELL_W),
        cell_h=int(m.get('cell_height') or _csp.DEFAULT_CELL_H),
        sheet_path=m.get('sheet_path') or _csp.master_sheet_path(char_id),
        approved=True,
        tiles=m.get('tiles') or [],
        extra=extra,
    )
    job = _contact_sheet_jobs.get(char_id)
    if job is not None:
        job['approved'] = True
        # Clear any prior decline so a decline→approve sequence, or a resumed
        # run, does not immediately re-decline in wait_for_approval.
        job.pop('review_declined', None)
        if job.get('stage') == 'review_declined':
            job['stage'] = 'awaiting_approval'
        _contact_sheet_save_state(char_id)
    return True


def _contact_sheet_mark_declined(char_id: str) -> bool:
    """Register an operator DECLINE on a contact-sheet review so the run stops
    reporting `awaiting_approval` (2026-07-20).

    Before this, decline only flipped the pending-store card to 'declined' and
    never touched the job — so the job's stage stayed 'awaiting_approval', the
    status endpoint kept returning awaiting_approval:true, and the wizard kept
    showing "awaiting your decision" for a card the operator had already
    declined. Mirrors _contact_sheet_mark_manifest_approved: persists a manifest
    flag a live worker's wait_for_approval polls, and moves the job off the
    approval stage (in-memory job when present, else patches the state file for
    a run whose worker already exited, e.g. across a GUI restart).
    """
    from zyg_workflows import contact_sheet_pipeline as _csp

    # 1) Persisted manifest flag — the cross-process signal a live worker sees.
    #    Only when a manifest already exists: a pre-run 'contact_sheet'
    #    permission-card decline has no run yet, and creating a stub manifest
    #    with review_declined would be spurious.
    try:
        m = _csp.load_manifest(char_id) or {}
        if m:
            extra = {
                k: m[k]
                for k in m
                if k
                not in (
                    'char_id',
                    'pipeline',
                    'rows',
                    'cols',
                    'gutter_px',
                    'cell_width',
                    'cell_height',
                    'sheet_path',
                    'approved',
                    'approved_at',
                    'tiles',
                    'updated_at',
                )
            }
            extra['review_declined'] = True
            _csp.write_manifest(
                char_id,
                rows=int(m.get('rows') or _csp.DEFAULT_ROWS),
                cols=int(m.get('cols') or _csp.DEFAULT_COLS),
                gutter=int(m.get('gutter_px') or _csp.DEFAULT_GUTTER),
                cell_w=int(m.get('cell_width') or _csp.DEFAULT_CELL_W),
                cell_h=int(m.get('cell_height') or _csp.DEFAULT_CELL_H),
                sheet_path=m.get('sheet_path') or _csp.master_sheet_path(char_id),
                approved=bool(m.get('approved')),
                tiles=m.get('tiles') or [],
                extra=extra,
            )
    except Exception as _mexc:
        _zyg_log.info(f'[CONTACT-SHEET-DECLINE] manifest flag failed for {char_id}: {_mexc}')
    # 2) Job state — move off awaiting_approval so the status endpoint updates.
    job = _contact_sheet_jobs.get(char_id)
    if job is not None:
        job['review_declined'] = True
        job['status'] = 'declined'
        job['stage'] = 'review_declined'
        job['current_stage'] = 'Review declined by operator'
        job['approved'] = False
        _contact_sheet_save_state(char_id)
        return True
    # No in-memory job (worker already exited) — patch the state file directly.
    try:
        _sp = _contact_sheet_state_path(char_id)
        with open(_sp, encoding='utf-8') as fh:
            st = json.load(fh)
        st['review_declined'] = True
        st['status'] = 'declined'
        st['stage'] = 'review_declined'
        st['current_stage'] = 'Review declined by operator'
        st['approved'] = False
        tmp = _sp + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(st, fh, default=str)
        os.replace(tmp, _sp)
        return True
    except FileNotFoundError:
        return False
    except Exception as _sexc:
        _zyg_log.info(f'[CONTACT-SHEET-DECLINE] state patch failed for {char_id}: {_sexc}')
        return False


def _contact_sheet_push_review_pending(char_id: str) -> None:
    """Queue the mid-run sheet review in the Agent Zero pending store.

    Mirrors the documentary manual-approval entries so the same dashboard and
    decide endpoint drive it — Allow flips the manifest flag the worker polls.
    """
    import datetime as _dt

    # function-local: zyg_dashboard.bp_zero_public_store imports this package
    from zyg_dashboard.bp_zero_public_store import (
        _ZPUB_PENDING_LOCK,
        _zpub_pending_load,
        _zpub_pending_save,
    )

    job = _contact_sheet_jobs.get(char_id) or {}
    name = (job.get('params') or {}).get('name') or char_id[:8]
    total = job.get('sheet_cells_total') or 48
    # Selected-vs-delivered disclosure (2026-07-20): the anchor gate ships the
    # closest face FLUX could render and syncs to delivered reality, so the
    # operator must see what actually shipped BEFORE committing ~4h of tiles +
    # a LoRA. Colour deltas are hard (the LoRA renders them); structure deltas
    # are advisory (FLUX cannot reliably hit face/eye shape). Same source the
    # status endpoint reads: job['params']['_attr_deltas'] (written by the
    # attribute + structure gates during sheet_generate, before this gate).
    _deltas = ((job.get('params') or {}).get('_attr_deltas')) or {}
    _dlabels = {
        'eye_color': 'eye colour',
        'hair_color': 'hair colour',
        'skin_tone': 'skin tone',
        'face_shape': 'face shape',
        'eye_shape': 'eye shape',
        'age_band': 'apparent age',
    }
    _hard, _adv = [], []
    for _k, _d in _deltas.items():
        _sel, _del = (_d or {}).get('selected'), (_d or {}).get('delivered')
        if not (_sel and _del):
            continue
        _lbl = _dlabels.get(_k, _k.replace('_', ' '))
        _row = f'{_lbl}: {_del} (you selected {_sel})'
        (_adv if (_d or {}).get('advisory') else _hard).append(_row)
    _delta_note = ''
    if _hard:
        _delta_note += ' ⚠ Delivered differs from your selection — ' + '; '.join(_hard) + '.'
    if _adv:
        _delta_note += ' (Advisory, FLUX cannot reliably hit these: ' + '; '.join(_adv) + '.)'
    with _ZPUB_PENDING_LOCK:
        data = _zpub_pending_load()
        if any(
            r.get('pipeline') == 'contact_sheet_review'
            and r.get('char_id') == char_id
            and r.get('status') in ('pending', 'queued')
            for r in data
        ):
            return
        data.append(
            {
                'id': 'preq_' + uuid.uuid4().hex[:12],
                'token': '',
                'label': f'Review contact sheet — {name}',
                'invite_url': '',
                'prompt': (
                    f'{total}-angle sheet for "{name}" is ready. Review it at '
                    f'/api/storyteller/contact-sheet/image/{char_id} — Allow continues '
                    f'tiles → identity QC → captions → LoRA; Decline leaves it parked.' + _delta_note
                ),
                'attribute_deltas': [
                    {
                        'attribute': _k,
                        'label': _dlabels.get(_k, _k.replace('_', ' ')).title(),
                        'selected': (_d or {}).get('selected'),
                        'delivered': (_d or {}).get('delivered'),
                        'advisory': bool((_d or {}).get('advisory')),
                    }
                    for _k, _d in _deltas.items()
                    if (_d or {}).get('selected') and (_d or {}).get('delivered')
                ],
                'pipeline': 'contact_sheet_review',
                'voice': '',
                'style': (job.get('params') or {}).get('style', ''),
                'model': job.get('model_family', 'flux'),
                'ip': 'internal',
                'session_id': '',
                'char_id': char_id,
                'body_snapshot': {},
                'requested_at': _dt.datetime.utcnow().isoformat() + 'Z',
                'status': 'pending',
                'decided_at': None,
                'approved_job_id': None,
            }
        )
        _zpub_pending_save(data)
    _zero_audit_log('contact_sheet_review_queued', {'char_id': char_id, 'name': name})


# 2026-10-05 layering: hand the pipelines the GUI's own implementation of the
# three hooks whose behaviour only a running dashboard has.
runtime.register(
    push_error_log=_push_error_log,
    contact_sheet_push_review_pending=_contact_sheet_push_review_pending,
    controller=controller,
)


def _contact_sheet_parse_start_payload(data: dict) -> dict:
    """Normalize a contact-sheet start payload (route + Zero decide share this)."""
    from zyg_workflows import contact_sheet_pipeline as _csp

    char_id = (data.get('char_id') or uuid.uuid4().hex[:12]).strip()
    params = {
        'name': (data.get('name') or 'Character').strip(),
        'gender': (data.get('gender') or 'female').strip(),
        'hair_color': (data.get('hair_color') or 'brown').strip(),
        'eye_color': (data.get('eye_color') or 'brown').strip(),
        'skin_tone': (data.get('skin_tone') or 'medium').strip(),
        'style': (data.get('style') or 'photorealistic').strip(),
    }
    # Full characteristics pass-through (2026-07-17): this parser used to keep
    # only the six basics above, silently discarding age / height / genre and
    # the whole Advanced Identity panel — a user-selected age 25 never reached
    # the pipeline and auto-randomisation filled it instead. Absent or
    # ''/'auto' values still resolve per character via apply_auto_defaults().
    for _pk in (
        'age',
        'height',
        'genre',
        'hair_style',
        'hair_length',
        'hair_texture',
        'eye_shape',
        'eyebrow_style',
        'face_shape',
        'nose_shape',
        'lip_shape',
        'facial_hair',
        'muscle_mass',
        'distinctive_marks',
        'ethnic_heritage',
        'default_clothing',
        'accessories',
        'default_expression',
        'posture',
        'quality_suffix',
        'negative_prompt',
        'extra_prompt',
        'instantid_enabled',
        'face_detail_pass',
        # 2026-07-26: isolated per-character style profile (e.g. arcane_animation).
        # Absent → no effect; the public zpub UI never sends it, so the public
        # character flow stays on defaults. See arcane_restyle.py / char_state_service.
        'style_profile_restyle',
    ):
        _pv = data.get(_pk)
        if _pv is None:
            continue
        if isinstance(_pv, str):
            _pv = _pv.strip()
            if not _pv:
                continue
        params[_pk] = _pv
    # Materialise every 'auto' field NOW (2026-07-18). Resolution is seeded
    # per char_id+field, so resolving here or later yields identical values —
    # doing it here means the approval-queue label, the anchor attribute gate
    # and the bible all see the same concrete traits, and an auto gender gets
    # a matching random display name (the JS sends name='' in that case
    # because its name pools are gendered).
    try:
        from zyg_workflows import character_bible_service as _cbs_csp

        params = _cbs_csp.apply_auto_defaults(params, seed_key=char_id)
        _nm = (params.get('name') or '').strip()
        if not _nm or _nm.lower() in ('auto', 'character'):
            # seed_key: this payload is parsed twice (queue + approve) — the
            # unseeded draw named the card one thing and built another
            # (2026-07-19, 'Naomi Turner' card → 'Dahlia Quintero' character).
            params['name'] = _cbs_csp.resolve_character_display_name(
                '',
                params.get('gender', 'female'),
                params.get('eye_color'),
                seed_key=char_id,
            )
    except Exception as _csp_exc:
        _zyg_log.info(f'[CS-PARSE] auto-defaults materialisation skipped: {_csp_exc}')
    kick_lora = data.get('kick_lora', True)
    if isinstance(kick_lora, str):
        kick_lora = kick_lora.lower() not in ('0', 'false', 'no')
    auto_approve = data.get('auto_approve', False)
    if isinstance(auto_approve, str):
        auto_approve = auto_approve.lower() in ('1', 'true', 'yes')
    flywheel = data.get('flywheel', True)
    if isinstance(flywheel, str):
        flywheel = flywheel.lower() not in ('0', 'false', 'no')
    return {
        'char_id': char_id,
        'params': params,
        'mf': _parse_pipeline_model_family(data.get('model_family', 'flux')),
        'kick_lora': bool(kick_lora),
        'auto_approve': bool(auto_approve),
        'flywheel': bool(flywheel),
        'rows': int(data.get('rows') or _csp.DEFAULT_ROWS),
        'cols': int(data.get('cols') or _csp.DEFAULT_COLS),
        'sheet_mode': (data.get('sheet_mode') or 'auto').strip().lower(),
        'angle_set': (data.get('angle_set') or '').strip().lower() or None,
    }


def _contact_sheet_launch_run(p: dict) -> tuple[dict, int]:
    """Create the job dict and spawn the worker thread. Returns (payload, status)."""
    from zyg_workflows import contact_sheet_pipeline as _csp

    # Clear any latched emergency stop, exactly like the scholarly/video/manga/
    # creature start paths do — a stale halt otherwise kills every ComfyUI
    # submit of the new run ("pipeline halt requested", 2026-07-05 14:32).
    try:
        _clear_pipeline_halt()
    except Exception as _exc:
        _zyg_log.warning('clearing the latched pipeline halt failed, comfy submits may be refused: %s', _exc)
    # Scheduler pause: don't start NEW runs while queued/scheduled work or the
    # whole production line is paused. (Resuming an already-parked run goes
    # through _contact_sheet_resume_run, which is not gated here.)
    from zyg_workflows import pipeline_control as _pc_launch

    if _pc_launch.is_paused(_pc_launch.SCOPE_SCHEDULED) or _pc_launch.is_paused(_pc_launch.SCOPE_PRODUCTION):
        _which = 'production' if _pc_launch.is_paused(_pc_launch.SCOPE_PRODUCTION) else 'scheduled'
        return {
            'char_id': p.get('char_id', ''),
            'status': 'paused',
            'message': f'New runs are paused ({_which} hold) — resume to start.',
        }, 409
    char_id = p['char_id']
    existing = _contact_sheet_jobs.get(char_id)
    if existing and existing.get('status') == 'running':
        return {
            'char_id': char_id,
            'status': 'running',
            'message': 'Contact sheet pipeline already running',
        }, 409
    job = {
        'char_id': char_id,
        'status': 'running',
        'stage': 'sheet_generate',
        'pipeline': 'multi_angle_contact_sheet',
        'started': _ams_iso(),
        'params': p['params'],
        'model_family': p['mf'],
        'kick_lora': p['kick_lora'],
        'auto_approve': p['auto_approve'],
        'approved': p['auto_approve'],
        'rows': p['rows'],
        'cols': p['cols'],
        'sheet_mode': p['sheet_mode'],
        'angle_set': p['angle_set'],
        'flywheel': p['flywheel'],
        'trigger_token': _csp.trigger_token_for(char_id),
        'debug_events': [],
        'stage_timeline': [],
    }
    _contact_sheet_jobs[char_id] = job
    _contact_sheet_save_state(char_id)
    t = threading.Thread(
        target=_bg_contact_sheet_pipeline,
        args=(char_id,),
        daemon=True,
        name=f'contact-sheet-{char_id[:8]}',
    )
    t.start()
    return {
        'char_id': char_id,
        'status': 'running',
        'pipeline': 'multi_angle_contact_sheet',
        'model_family': p['mf'],
        'trigger_token': job['trigger_token'],
        'dataset_dir': os.path.join(os.path.expanduser('~/lora-datasets/storyteller_chars'), char_id),
        'sheet_path': _csp.master_sheet_path(char_id),
        'kick_lora': p['kick_lora'],
        'auto_approve': p['auto_approve'],
        # Auto fields are materialised at parse time — reflect the resolved
        # identity back so the UI can show the assigned name and filter
        # voices by the actual gender/age (2026-07-18).
        'resolved': {
            'name': (p['params'] or {}).get('name'),
            'gender': (p['params'] or {}).get('gender'),
            'age': (p['params'] or {}).get('age'),
        },
    }, 200


# 2026-07-17 heavy-tranche: api_internal_contact_sheet_start moved to bp_storyteller.py


# 2026-07-17 heavy-tranche: api_internal_contact_sheet_status moved to bp_storyteller.py


# 2026-07-17 heavy-tranche: api_internal_contact_sheet_approve moved to bp_storyteller.py


# 2026-07-17 heavy-tranche: api_internal_contact_sheet_pause moved to bp_storyteller.py


# 2026-07-17 heavy-tranche: api_internal_contact_sheet_resume moved to bp_storyteller.py


# 2026-07-17 heavy-tranche: api_internal_pipeline_pause moved to bp_storyteller.py


# 2026-07-17 heavy-tranche: api_internal_pipeline_resume moved to bp_storyteller.py


# 2026-07-17 heavy-tranche: api_internal_pipeline_pause_state moved to bp_storyteller.py


# 2026-07-17 heavy-tranche: api_internal_contact_sheet_image moved to bp_storyteller.py


# 2026-07-17 heavy-tranche: api_internal_list_contact_sheets moved to bp_storyteller.py


# 2026-07-17 heavy-tranche: api_internal_storyteller_generate_character moved to bp_storyteller.py


# 2026-07-17 heavy-tranche: api_internal_storyteller_voices moved to bp_storyteller.py


# 2026-07-17 heavy-tranche: api_internal_storyteller_voice_sample moved to bp_storyteller.py


# 2026-07-17 heavy-tranche: api_internal_storyteller_character_bible moved to bp_storyteller.py


# 2026-07-17 heavy-tranche: api_internal_storyteller_character_status moved to bp_storyteller.py


# 2026-10-05 layering: _PREVIEW_LORA_WAIT_S moved to zyg_workflows.pipeline_config
# 2026-10-05 layering: _CHAR_DRIFT_MIN moved to zyg_workflows.pipeline_config
# 2026-10-05 layering: _CHAR_DRIFT_ANIMATED moved to zyg_workflows.pipeline_config
# 2026-10-05 layering: _ANIMATED_USE_FLUX moved to zyg_workflows.pipeline_config
# 2026-10-05 layering: _PREVIEW_SEED_CANDIDATES moved to zyg_workflows.pipeline_config
# 2026-10-05 layering: _PREVIEW_FACE_SEED_CANDIDATES moved to zyg_workflows.pipeline_config
# 2026-10-05 layering: _CHAR_DEFAULT_MODEL_FAMILY moved to zyg_workflows.pipeline_config
if _CHAR_DEFAULT_MODEL_FAMILY not in ('flux', 'sdxl'):
    _CHAR_DEFAULT_MODEL_FAMILY = 'flux'
# 2026-10-05 layering: _CHAR_PHOTOREAL_HYBRID_PREVIEW moved to zyg_workflows.pipeline_config
# 2026-10-05 layering: _CHAR_DUAL_LORA_PHOTOREAL moved to zyg_workflows.pipeline_config
# 2026-10-05 layering: _PHOTOREAL_CLIP_POS moved to zyg_workflows.pipeline_config
# 2026-10-05 layering: _PHOTOREAL_CLIP_NEG moved to zyg_workflows.pipeline_config


# 2026-07-17 heavy-tranche: _char_render_style moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_is_photoreal_style moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_lora_train_families moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_has_sdxl_lora moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_effective_hybrid_preview moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_photoreal_hybrid_preview moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_lora_output_ready moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_library_trained_at moved to char_state_service.py


# 2026-07-17 heavy-tranche: _discover_char_sdxl_lora moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_preview_slot_lora_path moved to char_state_service.py


# 2026-07-17 heavy-tranche: _resolve_char_model_family moved to char_state_service.py


# 2026-07-17 heavy-tranche: _normalize_char_model_family moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_preview_slot_names moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_preview_png_names moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_sync_preview_legacy_aliases moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_reconcile_job_state moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_derive_pipeline_stage moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_mark_done moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_mark_error moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_reload_jobs_from_disk moved to char_state_service.py


# 2026-07-17 heavy-tranche: _build_char_preview_slots moved to char_state_service.py


# 2026-07-17 heavy-tranche: _pick_char_preview_reference moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_is_blender_dataset moved to char_state_service.py


# 2026-07-17 heavy-tranche: _pick_char_preview_reference_for_slot moved to char_state_service.py


# 2026-07-17 heavy-tranche: _preview_backend_tier moved to char_state_service.py


# 2026-07-17 heavy-tranche: _have_usable_char_preview moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_close_running_timeline moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_orphan_stale_running_job moved to char_state_service.py


gui_state._PREVIEW_HAND_YOLO = None
gui_state._PREVIEW_FACE_YOLO = None


# 2026-07-17 heavy-tranche: _preview_face_yolo_count moved to char_state_service.py


# 2026-07-17 heavy-tranche: _preview_hand_yolo_score moved to char_state_service.py


# 2026-07-17 heavy-tranche: _preview_hand_qa moved to char_state_service.py


# 2026-07-17 heavy-tranche: _preview_attempt_rank moved to char_state_service.py


# 2026-07-17 heavy-tranche: _generate_preview_slot_best_of_n moved to char_state_service.py


# 2026-07-17 heavy-tranche: _render_char_preview_slots moved to char_state_service.py


# 2026-07-17 heavy-tranche: _render_char_preview_images_comfy moved to char_state_service.py


# 2026-07-17 heavy-tranche: _render_char_preview_images_sdxl moved to char_state_service.py


# 2026-07-17 heavy-tranche: _render_char_preview_images moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_params_from_bible moved to char_state_service.py


# 2026-07-17 heavy-tranche: api_internal_storyteller_regen_preview moved to bp_storyteller.py


# ── Bulk FLUX preview generation for existing characters ──────────────────────
gui_state._CHAR_PREVIEW_SWEEP = {
    'running': False,
    'done': 0,
    'total': 0,
    'current': '',
    'errors': [],
}


# 2026-07-17 heavy-tranche: api_internal_storyteller_gen_char_previews moved to bp_storyteller.py


# 2026-07-17 heavy-tranche: api_internal_storyteller_char_preview_status moved to bp_storyteller.py
