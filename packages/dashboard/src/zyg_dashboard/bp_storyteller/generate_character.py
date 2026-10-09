# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The character-generate route and its Agent-Zero snapshot launcher.

Verbatim move of bp_storyteller.py:1040-1384 and 1906-1954 (2026-10-06 split);
the thread body in between moved to generate_worker.py (see its docstring).
"""

import functools
import logging as _zyg_logging
import threading
import uuid
from typing import Tuple

from flask import jsonify, request, session

from zyg_dashboard.bp_storyteller import (  # noqa: E402  the package __init__ binds these before it imports this module
    _ZPUB_PENDING_LOCK,
    _ams_iso,
    _caveman_kw,
    _char_gen_jobs,
    _char_save_state,
    _main_mod,
    _record_token_usage,
    _resolve_char_model_family,
    _zero_audit_log,
    _zpub_pending_load,
    _zpub_pending_save,
    bp,
    gui_state,
    limiter,
)
from zyg_dashboard.bp_storyteller.generate_worker import _make_bg_generate
from zyg_dashboard.bp_storyteller.guards import (
    _CHAR_ID_RE,
    _env_on,
    _production_paused,
    _restore_parked_char_photos,
    _save_uploaded_char_photos,
)

_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_storyteller')


# ── The stages api_internal_storyteller_generate_character was split into (2026-10-09) ──
# The route was a 370-line function; the repo's quality ratchet caps a function at 300.
# Every helper below is a verbatim move of one of its blocks, in the order the route runs
# them, so the response, the parked record, the job dict and every print stay identical.
# They live in this file rather than a sibling because it is under the 600-line mark the
# split rule allows for in-file helpers.


def _read_request_payload():
    """Read the request body in either accepted format.

    Returns ``(data, uploaded_photo_files)``: the parameter dict, and the uploaded images
    (empty for a JSON body). A multipart body carries the parameters as a JSON string in
    the ``params`` field and may override the model family with a plain form field.
    """
    uploaded_photo_files = []
    if request.content_type and 'multipart/form-data' in request.content_type:
        import json as _json_mod

        data = _json_mod.loads(request.form.get('params', '{}') or '{}')
        uploaded_photo_files = request.files.getlist('photos')
        _mf_form = (request.form.get('model_family') or '').strip().lower()
        if _mf_form in ('flux', 'sdxl'):
            data['model_family'] = _mf_form
    else:
        data = request.get_json(silent=True) or {}
    return data, uploaded_photo_files


def _coerce_muscle_mass(raw):
    """Clamp the requested muscle_mass to 0..100; anything non-numeric becomes 20.

    2026-07-31: muscle_mass was coerced with a bare int() at param-parse time,
    outside any try block — every neighbouring advanced-identity field accepts
    the sentinel 'auto', so {"muscle_mass": "auto"} raised ValueError, Flask
    returned an HTML 500, and the public proxy's resp.json() turned that into
    a totally misleading "Main app unreachable" 503. Separately `or 20` made a
    legitimate muscle_mass=0 silently become 20.
    """
    try:
        _mm = int(raw)
    except (TypeError, ValueError):
        _mm = 20  # 'auto'/''/None/'medium' → let apply_auto_defaults decide
    return max(0, min(100, _mm))


def _character_params(data):
    """Normalise one request body into the character parameter dict the pipeline reads.

    Pure: every field is read off `data`, stripped, and defaulted. The identity and
    wardrobe descriptors default to the sentinel 'auto' so the Sonnet brief and
    `apply_auto_defaults` can fill them; the two conditioning toggles keep 'auto' as a
    third state ("use the bible default") and are cast much later, in
    character_bible_service.build_from_character_generate.
    """
    return {
        'name': (data.get('name') or '').strip(),
        'hair_color': (data.get('hair_color') or 'brown').strip(),
        'eye_color': (data.get('eye_color') or 'brown').strip(),
        'skin_tone': (data.get('skin_tone') or 'medium').strip(),
        'gender': (data.get('gender') or 'female').strip(),
        'height': str(data.get('height', '1.70')),
        'age': data.get('age'),
        'style': (data.get('style') or 'auto').strip(),
        'genre': (data.get('genre') or 'general').strip().lower(),
        'facial_hair': (data.get('facial_hair') or 'none').strip().lower(),
        'muscle_mass': _coerce_muscle_mass(data.get('muscle_mass')),
        'extra_prompt': (data.get('extra_prompt') or '').strip(),
        # ── Extended identity descriptors (any may be 'auto' / empty) ──────
        'hair_style': (data.get('hair_style') or 'auto').strip(),
        'hair_length': (data.get('hair_length') or 'auto').strip(),
        'hair_texture': (data.get('hair_texture') or 'auto').strip(),
        'eye_shape': (data.get('eye_shape') or 'auto').strip(),
        'eyebrow_style': (data.get('eyebrow_style') or 'auto').strip(),
        'face_shape': (data.get('face_shape') or 'auto').strip(),
        'nose_shape': (data.get('nose_shape') or 'auto').strip(),
        'lip_shape': (data.get('lip_shape') or 'auto').strip(),
        'distinctive_marks': (data.get('distinctive_marks') or 'auto').strip(),
        'ethnic_heritage': (data.get('ethnic_heritage') or '').strip(),
        # ── Wardrobe / style profile ───────────────────────────────────────
        'default_clothing': (data.get('default_clothing') or 'auto').strip(),
        'accessories': (data.get('accessories') or 'auto').strip(),
        'default_expression': (data.get('default_expression') or 'auto').strip(),
        'posture': (data.get('posture') or 'auto').strip(),
        # ── ComfyUI quality knobs ──────────────────────────────────────────
        'quality_suffix': (data.get('quality_suffix') or 'auto').strip(),
        'negative_prompt': (data.get('negative_prompt') or 'auto').strip(),
        # ── Conditioning toggles (FaceDetailer + InstantID) ────────────────
        # Accepted values:
        #   bool      → explicit on/off
        #   'auto'/'' → use bible default (True for both now that nodes are installed)
        # Cast happens later in character_bible_service.build_from_character_generate.
        'face_detail_pass': data.get('face_detail_pass', 'auto'),
        'face_detail_strength': data.get('face_detail_strength', 'auto'),
        'instantid_enabled': data.get('instantid_enabled', 'auto'),
        'instantid_weight': data.get('instantid_weight', 'auto'),
    }


def _photo_inputs(data, char_id, uploaded_photo_files):
    """Save the uploaded photos and read the client's vision analysis off the body.

    Returns ``(image paths on disk, analysis dict, locked field names)``. The locked
    fields are the ones the requester pinned by hand, lower-cased, which the analysis
    merge must leave alone.
    """
    _photo_analysis: dict = {}
    _photo_locked_fields: set[str] = set()
    if isinstance(data.get('photo_analysis'), dict):
        _photo_analysis = data['photo_analysis']
    _plf = data.get('photo_locked_fields') or []
    if isinstance(_plf, (list, tuple)):
        _photo_locked_fields = {str(x).strip().lower() for x in _plf if str(x).strip()}

    _uploaded_image_paths: list[str] = []
    if uploaded_photo_files:
        _uploaded_image_paths = _save_uploaded_char_photos(char_id, uploaded_photo_files)
    if not _uploaded_image_paths:
        # Replay of an operator-approved parked request: a multipart body cannot
        # be snapshotted into the pending store, so the photos were written to
        # disk at park time. Pick them up rather than silently falling back to a
        # Blender render of what the requester asked to be a photo character.
        _uploaded_image_paths = _restore_parked_char_photos(char_id, data.get('_preserved_photo_paths'))
    return _uploaded_image_paths, _photo_analysis, _photo_locked_fields


def _operator_session():
    """True when the caller holds an authenticated main-app session.

    Such a caller is exempt from the Agent Zero approval gate: the operator IS the
    approver. False outside a request context, and false for the zpub proxy, which calls
    this server-side with no session cookie.
    """
    try:
        return bool(session.get('user_role'))
    except Exception:
        return False


def _pending_prompt(params, label_name, n_photos):
    """The one-line description of a parked character request the approval queue shows."""
    return (
        f'{label_name} — {params.get("gender")}, '
        f'{params.get("hair_color")} hair, {params.get("eye_color")} eyes, '
        f'{params.get("skin_tone")} skin, {params.get("style")}; '
        f'{n_photos} uploaded photo(s); '
        f'character dataset + LoRA training'
    )


def _park_character_request(data, params, char_id, uploaded_image_paths):
    """Park an unapproved character request in the Agent Zero queue and answer 202.

    contact-sheet/start parks every non-auto-approved run in the pending queue and
    returns 202. This sibling — reachable from the public site with only an invite link,
    5/hour/IP and unbounded across IPs — spawned Blender, a billed Sonnet brief,
    SimpleTuner GPU training and a FLUX preview with no operator seeing anything, which is
    exactly what the 2026-07-25 zpub-approval work was supposed to have closed. Called
    BEFORE the vision analysis and the brief so a declined request costs nothing but disk.

    Returns the ``(response, status)`` pair the route returns unchanged.
    """
    import datetime as _dt_cg

    _req_id = 'preq_' + uuid.uuid4().hex[:12]
    _snapshot = dict(data)
    _snapshot['char_id'] = char_id
    _snapshot.pop('zero_approved', None)
    if uploaded_image_paths:
        _snapshot['_preserved_photo_paths'] = list(uploaded_image_paths)
    _label_name = (params.get('name') or '').strip() or char_id[:8]
    with _ZPUB_PENDING_LOCK:
        _pdata = _zpub_pending_load()
        _pdata.append(
            {
                'id': _req_id,
                'token': '',
                'label': f'Character generation — {_label_name}',
                'invite_url': '',
                'prompt': _pending_prompt(params, _label_name, len(uploaded_image_paths)),
                'pipeline': 'character_generate',
                'voice': '',
                'style': params.get('style', ''),
                'model': (data.get('model_family') or params.get('model_family') or ''),
                'ip': request.remote_addr or 'unknown',
                'session_id': '',
                'char_id': char_id,
                'body_snapshot': _snapshot,
                'requested_at': _dt_cg.datetime.utcnow().isoformat() + 'Z',
                'status': 'pending',
                'decided_at': None,
                'approved_job_id': None,
            }
        )
        _zpub_pending_save(_pdata)
    _zero_audit_log(
        'character_generate_approval_requested',
        {
            'req_id': _req_id,
            'char_id': char_id,
            'name': _label_name,
            'photos': len(uploaded_image_paths),
        },
    )
    return jsonify(
        {
            'pending': True,
            'pending_id': _req_id,
            'char_id': char_id,
            'status': 'pending_approval',
            'message': 'Character request queued — approve it via Agent Zero to start generation.',
        }
    ), 202


def _merge_photo_analysis(params, uploaded_image_paths, photo_analysis, photo_locked_fields):
    """Analyse the uploaded photos server-side and merge the result into `params`.

    Returns ``(params, analysis)``. Nothing happens without uploaded photos. The client's
    own analysis is reused when it carries both `ok` and `fields`; otherwise the service
    is asked for one. Only AUTO fields are filled and the requester's locked fields are
    never touched. Every failure is caught and printed: a photo character still generates
    from the uploaded images without the analysis.
    """
    if not uploaded_image_paths:
        return params, photo_analysis
    try:
        from zyg_workflows import character_photo_analysis_service as _cpas_pre

        if _cpas_pre.analysis_enabled():
            if not (photo_analysis.get('ok') and photo_analysis.get('fields')):
                _zyg_log.info('[ST-CHAR] Running server-side photo analysis before character brief…')
                photo_analysis = _cpas_pre.analyze_photo_paths(
                    uploaded_image_paths,
                    log_fn=lambda m: _zyg_log.info(f'[ST-CHAR-PHOTO] {m}'),
                )
            if photo_analysis.get('ok'):
                params = _cpas_pre.merge_analysis_into_params(
                    params,
                    photo_analysis,
                    locked_fields=photo_locked_fields,
                    only_auto=True,
                )
                params['_photo_analysis'] = photo_analysis
                _zyg_log.info(
                    f'[ST-CHAR] Photo analysis merged ({photo_analysis.get("backend", "?")}) '
                    f'— {len(photo_analysis.get("fields") or {})} field(s)'
                )
    except Exception as _cpa_e:
        _zyg_log.info(f'[ST-CHAR] Photo analysis merge skipped: {_cpa_e}')
    return params, photo_analysis


def _resolve_identity_fields(params, char_id):
    """Fill the AUTO identity fields, in the order the pipeline depends on.

    Display name first (the brief uses it in prose), then the smile intent, then the
    Sonnet brief, then the genre-table heuristics, then the photoreal skin texture, then
    the smile intent AGAIN because the auto defaults may have overwritten it. Each step is
    optional: a failure is logged or printed and the remaining AUTO fields are left for
    the next step — none of them may take the route down. Returns `params`.
    """
    # Resolve display name before brief (brief uses name in prose).
    try:
        from zyg_workflows import character_bible_service as _cbs_name

        params['name'] = _cbs_name.resolve_character_display_name(
            params.get('name'),
            params.get('gender', 'female'),
            params.get('eye_color'),
        )
    except Exception:
        _raw_name = (params.get('name') or '').strip()
        if not _raw_name or _raw_name.lower() in {'auto', 'none', 'null'}:
            params['name'] = 'Character_' + uuid.uuid4().hex[:6]
    try:
        from zyg_workflows import character_bible_service as _cbs_sm0

        params = _cbs_sm0.apply_smile_intent(params)
    except Exception as _exc:
        _zyg_log.warning('smile intent could not be applied: %s', _exc)
    # Sonnet brief fills AUTO identity + presentation before genre lookup tables.
    try:
        from zyg_workflows import character_brief_service as _cbs_brief

        if _cbs_brief.brief_enabled():
            _brief = _cbs_brief.generate_character_brief(
                params,
                log_fn=lambda m: _zyg_log.info(f'[ST-CHAR] {m}'),
                token_record_fn=lambda m, p, c: _record_token_usage(
                    m,
                    p,
                    c,
                    pipeline_type='character_brief',
                    stage='character_brief',
                    **_caveman_kw('planner'),
                ),
            )
            params = _cbs_brief.merge_brief_into_params(params, _brief)
    except Exception as _brief_e:
        _zyg_log.info(f'[ST-CHAR] Character brief skipped: {_brief_e}')
    # Fill remaining AUTO fields with heuristics (genre tables as fallback).
    try:
        from zyg_workflows import character_bible_service as _cbs_ad

        params = _cbs_ad.apply_auto_defaults(params, seed_key=char_id)
        if params.get('_hair_age_adjusted'):
            params.pop('_hair_age_adjusted', None)
            params['_hair_age_note'] = 'Hair set to ash brown — grey/white hair is unusual below age 35'
    except Exception as _exc:
        _zyg_log.warning('auto defaults could not be applied, AUTO fields stay unresolved: %s', _exc)
    try:
        from zyg_workflows import character_brief_service as _cbs_skin

        params = _cbs_skin.ensure_photoreal_skin_texture(params)
    except Exception as _exc:
        _zyg_log.warning('photoreal skin texture could not be applied: %s', _exc)
    try:
        from zyg_workflows import character_bible_service as _cbs_sm

        params = _cbs_sm.apply_smile_intent(params)
    except Exception as _exc:
        _zyg_log.warning('smile intent could not be re-applied after the auto defaults: %s', _exc)
    return params


def _register_char_job(char_id, params, model_family, uploaded_image_paths, kick_lora):
    """Register the run in the Kanban tracker and persist it. Returns the stop Event.

    The stage_timeline mirrors the story-pipeline shape so /api/metrics/dashboard can
    aggregate stage timings across server restarts.
    """
    _char_stop = threading.Event()
    _char_gen_jobs[char_id] = {
        'char_id': char_id,
        'status': 'running',
        'stage': 'blender_render',
        'current_stage': 'init',
        'started': _ams_iso(),
        'stop_event': _char_stop,
        'params': params,
        'model_family': model_family,
        'render_mode': 'uploaded_photos' if uploaded_image_paths else 'blender',
        'image_count': len(uploaded_image_paths),
        'kick_lora': bool(kick_lora),
        'error': None,
        'debug_events': [],  # live-tail event log
        'stage_timeline': [],  # [{name, status, started_at, ended_at, elapsed_s, extra}]
    }
    _char_save_state(char_id)
    return _char_stop


def _char_emit_event(char_id, msg: str, level: str = 'INFO', stage: str = ''):
    """Append a live-tail event to this char job (mirrors pipeline debug_events format)."""
    _job = _char_gen_jobs.get(char_id, {})
    ev = {
        'ts': _ams_iso(),  # full ISO so frontend regex parses date
        'level': level,
        'stage': stage or _job.get('stage', ''),
        'msg': msg,
    }
    evs = _job.setdefault('debug_events', [])
    evs.append(ev)
    if len(evs) > 300:
        _job['debug_events'] = evs[-200:]
    _zyg_log.info(f'[ST-CHAR] {msg}')


def _raise_if_char_stopped(char_id):
    """Raise RuntimeError when the operator stopped this run — or paused production."""
    from zyg_workflows import pipeline_control as _pc_ch

    _j = _char_gen_jobs.get(char_id, {})
    ev = _j.get('stop_event')
    if gui_state._pipeline_stop_flag or _pc_ch.halt_requested() or (ev is not None and ev.is_set()):
        raise RuntimeError('Character pipeline stopped by user')
    # 2026-07-31: the production hold was invisible here — an in-flight
    # char-gen thread ran Blender + SimpleTuner + Stage 1d previews to
    # completion after the operator paused production to free the GPU.
    # Phrased so the existing 'stopped by user' handler parks the job
    # instead of marking it errored.
    if _env_on('ZYG_CHAR_GEN_HONOR_PRODUCTION_PAUSE') and _pc_ch.is_paused(_pc_ch.SCOPE_PRODUCTION):
        raise RuntimeError('Character pipeline stopped by user — production paused')


@bp.route('/api/internal/storyteller/generate-character', methods=['POST'])
@limiter.exempt
def api_internal_storyteller_generate_character():
    """
    Trigger Blender character generation + kick off background LoRA training.
    Accepts two request formats:
      - JSON:       {char_id?, hair_color, eye_color, skin_tone?, gender, height?, style, kick_lora?}
      - Multipart:  params=<JSON string>, photos=<image files> (skips Blender; uses uploaded images)
    Returns: {char_id, trigger_token, status, images?, dataset_dir}
    """
    # ── Detect multipart vs JSON ────────────────────────────────────────────────
    data, uploaded_photo_files = _read_request_payload()

    params = _character_params(data)
    char_id = (data.get('char_id') or uuid.uuid4().hex[:12]).strip()
    # 2026-07-31: char_id arrived from the request body with only .strip(), was
    # joined to the dataset root, os.makedirs'd, and written to with uploaded
    # bytes — an invite-link holder POSTing char_id='../../../../tmp/pwn' created
    # directories and wrote attacker-supplied files outside the root as the
    # server user. Every other disk-touching route here validates this first.
    if _env_on('ZYG_STORYTELLER_CHAR_ID_STRICT') and not _CHAR_ID_RE.match(char_id):
        return jsonify({'error': 'invalid char_id (expected 12 lowercase hex characters)'}), 400

    # ── Production hold ───────────────────────────────────────────────────────
    # 2026-07-31: 'Pause production' promises to park every running run AND block
    # new starts, but this path had no gate — a fresh POST kept starting Blender,
    # SimpleTuner and a 36 GB FLUX preview while the operator believed the GPU
    # was being freed. Mirrors the 409 in _contact_sheet_launch_run.
    if _env_on('ZYG_CHAR_GEN_HONOR_PRODUCTION_PAUSE') and _production_paused():
        return jsonify(
            {
                'char_id': char_id,
                'status': 'paused',
                'message': 'New character runs are paused (production hold) — resume to start.',
            }
        ), 409

    # ── Photo upload: save early + vision analysis before Sonnet brief ─────────
    _uploaded_image_paths, _photo_analysis, _photo_locked_fields = _photo_inputs(data, char_id, uploaded_photo_files)

    # ── Agent Zero pre-activation gate (2026-07-31) ───────────────────────────
    # Park BEFORE the vision analysis and the brief so a declined request costs
    # nothing but disk (see _park_character_request for the whole reason).
    # Exempt: an authenticated main-app session (the operator IS the approver;
    # the zpub proxy calls this server-side with no session cookie) and the
    # decide-handler replay, which sets zero_approved.
    if _env_on('ZYG_CHAR_GEN_REQUIRE_ZERO_APPROVAL') and not data.get('zero_approved') and not _operator_session():
        return _park_character_request(data, params, char_id, _uploaded_image_paths)

    params, _photo_analysis = _merge_photo_analysis(
        params, _uploaded_image_paths, _photo_analysis, _photo_locked_fields
    )
    params = _resolve_identity_fields(params, char_id)
    kick_lora = bool(data.get('kick_lora', True))
    _mf_raw = (data.get('model_family') or params.get('model_family') or '').strip().lower()
    model_family = _resolve_char_model_family(
        _mf_raw if _mf_raw in ('flux', 'sdxl') else None,
        params,
        {},
    )
    params['model_family'] = model_family

    # Register in the Kanban tracker.
    _register_char_job(char_id, params, model_family, _uploaded_image_paths, kick_lora)

    info: dict = {'model_family': model_family, 'char_id': char_id}

    # 2026-10-09 split: both of these were closures over `char_id`; the partials rebuild
    # the identical callables the worker factory expects.
    _char_emit = functools.partial(_char_emit_event, char_id)
    _check_char_stop = functools.partial(_raise_if_char_stopped, char_id)

    # 2026-10-06 split: `_bg_generate` lives in generate_worker.py (the route function was
    # 879 lines, over the 800-line module ceiling). The factory rebuilds the identical
    # closure from the free variables it used to capture lexically.
    _bg_generate = _make_bg_generate(
        info,
        char_id,
        params,
        model_family,
        kick_lora,
        _uploaded_image_paths,
        _photo_analysis,
        _char_emit,
        _check_char_stop,
    )

    threading.Thread(target=_bg_generate, daemon=True, name=f'char-gen-{char_id[:8]}').start()

    trigger_token = f'ZYG_CHAR_{char_id[:6].upper()}'
    return jsonify(
        {
            'char_id': char_id,
            'trigger_token': trigger_token,
            'status': 'generating',
            'model_family': model_family,
            'params': params,
        }
    )


def launch_character_generate_from_snapshot(snapshot: dict) -> Tuple[dict, int]:
    """Start a parked character-generate request after Agent Zero approves it.

    2026-07-31: the decide handler starts parked contact-sheet runs with a direct
    in-process call (a self-POST 401s on the internal auth gate); this is the
    equivalent entry point for pipeline='character_generate'. Re-enters the view
    under a synthetic request context carrying the stored body plus
    zero_approved, so every other gate (char_id validation, production hold)
    still runs exactly as it would for a fresh request.
    """
    payload = dict(snapshot or {})
    payload['zero_approved'] = True
    _app_rp = None
    try:
        from flask import current_app as _cap_rp

        _app_rp = _cap_rp._get_current_object()
    except Exception:
        _app_rp = None
    if _app_rp is None:
        _app_rp = getattr(_main_mod, 'app', None)
    if _app_rp is None:
        return {'ok': False, 'error': 'flask app unavailable for replay'}, 500
    with _app_rp.test_request_context(
        '/api/internal/storyteller/generate-character',
        method='POST',
        json=payload,
    ):
        _rv = api_internal_storyteller_generate_character()
    _body, _status = (_rv[0], _rv[1]) if isinstance(_rv, tuple) else (_rv, 200)
    try:
        return (_body.get_json() or {}), int(_status)
    except Exception:
        return {'ok': False, 'error': 'character generate replay returned no JSON'}, 500
