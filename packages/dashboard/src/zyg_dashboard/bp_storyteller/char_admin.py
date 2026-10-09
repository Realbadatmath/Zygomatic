# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Voice samples, character bible/status and the manual LoRA retrain routes.

Verbatim move of bp_storyteller.py:1956-2249 (2026-10-06 split).
"""

import logging as _zyg_logging
import os
from typing import Any, Optional

from flask import jsonify, request

from zyg_dashboard.bp_storyteller import (  # noqa: E402  the package __init__ binds these before it imports this module
    _char_gen_jobs,
    _char_params_from_bible,
    _char_reconcile_job_state,
    _normalize_char_model_family,
    bp,
    limiter,
)
from zyg_dashboard.bp_storyteller.guards import (
    _CHARS_DATASET_ROOT,
    _CHAR_ID_RE,
    _env_on,
    _preview_provenance_map,
)

_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_storyteller')


@bp.route('/api/internal/storyteller/voices')
@limiter.exempt
def api_internal_storyteller_voices():
    """Voice catalog for Storyteller Step 2 (local Azure V1/V2 samples)."""
    try:
        from zyg_workflows.storyteller_voice_preview_service import (
            VOICE_SAMPLE_V1,
            VOICE_SAMPLE_V2,
            default_voice_id,
            grouped_voices_for_api,
        )

        kind = (request.args.get('kind') or 'character').strip().lower()
        if kind not in ('character', 'narrator'):
            kind = 'character'
        return jsonify(
            {
                'kind': kind,
                'groups': grouped_voices_for_api(kind=kind),
                'sample_phrases': {'v1': VOICE_SAMPLE_V1, 'v2': VOICE_SAMPLE_V2},
                'default_voice': default_voice_id(),
            }
        )
    except Exception as exc:
        return jsonify({'error': str(exc)[:200]}), 500


@bp.route('/api/internal/storyteller/voice-sample/<voice_id>/<variant>')
@limiter.exempt
def api_internal_storyteller_voice_sample(voice_id: str, variant: str):
    """Serve pre-generated local Azure MP3 (v1 or v2)."""
    from flask import send_file as _send_file
    from zyg_workflows.storyteller_voice_preview_service import resolve_sample_path, sample_mimetype

    variant = (variant or '').strip().lower()
    if variant not in ('v1', 'v2'):
        return jsonify({'error': 'variant must be v1 or v2'}), 400
    path = resolve_sample_path(voice_id, variant)
    if not path:
        return jsonify({'error': 'Sample not generated yet'}), 404
    try:
        return _send_file(
            path,
            mimetype=sample_mimetype(path),
            as_attachment=False,
            conditional=True,
        )
    except Exception as exc:
        return jsonify({'error': str(exc)[:200]}), 500


@bp.route('/api/internal/storyteller/character-bible/<char_id>')
@limiter.exempt
def api_internal_storyteller_character_bible(char_id: str):
    """Return the persisted character bible JSON for continuity / ComfyUI graphs."""
    try:
        from zyg_workflows import character_bible_service as _cbs_api

        pkg = _cbs_api.load(char_id)
        if not pkg:
            return jsonify({'char_id': char_id, 'found': False, 'bible': None}), 404
        return jsonify({'char_id': char_id, 'found': True, 'bible': pkg})
    except Exception as exc:
        return jsonify({'char_id': char_id, 'error': str(exc)[:200]}), 500


@bp.route('/api/internal/storyteller/character-status/<char_id>')
@limiter.exempt
def api_internal_storyteller_character_status(char_id: str):
    """
    Return character generation + LoRA training status.
    Returns: {char_id, lora_status: {step, done, pct, lora_path, trigger_token}, images_ready}
    """
    lora_status = {'step': 0, 'done': False, 'pct': 0, 'lora_path': None, 'trigger_token': None, 'status': 'unknown'}
    images_ready = False

    _mf_status = 'sdxl'
    try:
        _cj = _char_gen_jobs.get(char_id) or {}
        _mf_status = _normalize_char_model_family(
            _cj.get('model_family'),
            (_cj.get('params') or {}),
            {},
        )
    except Exception as _exc:
        _zyg_log.debug('model family lookup failed, assuming sdxl: %s', _exc)

    dataset_dir = os.path.join(_CHARS_DATASET_ROOT, char_id)
    try:
        import importlib.util as _ilu

        _spec = _ilu.find_spec('lora_trainer_service')
        if _spec:
            from zyg_workflows import lora_trainer_service as _lts

            trainer = _lts.get_trainer()
            lora_status = trainer.get_status(char_id, model_family=_mf_status)

        # Check if images exist in dataset dir
        if os.path.isdir(dataset_dir):
            pngs = [f for f in os.listdir(dataset_dir) if f.endswith('.png')]
            images_ready = len(pngs) >= 10
    except Exception as _e:
        _zyg_log.warning('lora status / dataset scan failed, reporting the defaults: %s', _e)

    # 2026-07-31 (contract D): per-slot preview provenance. lora_status.done says
    # "a LoRA finished training", NOT "the picture on screen was rendered through
    # it" — the wizard captioned a base-model render '✓ LoRA trained — full
    # character consistency' off exactly that conflation. A slot appears here
    # only when its sidecar exists; an ABSENT slot means unverified provenance
    # and the UI must not claim the image is LoRA-locked.
    _provenance: dict = {}
    if _env_on('ZYG_CHAR_PREVIEW_PROVENANCE'):
        try:
            _provenance = _preview_provenance_map(dataset_dir)
        except Exception:
            _provenance = {}

    _cj_out = _char_gen_jobs.get(char_id) or {}
    return jsonify(
        {
            'char_id': char_id,
            'model_family': _mf_status,
            'lora_status': lora_status,
            'images_ready': images_ready,
            'char_status': (_char_reconcile_job_state(dict(_cj_out)).get('status', 'unknown')),
            'lora_failed': _cj_out.get('lora_failed', False),
            'lora_error': _cj_out.get('lora_error', ''),
            'preview_quality_ok': _cj_out.get('preview_quality_ok'),
            'preview_warning': _cj_out.get('preview_warning', ''),
            'preview_backends': _cj_out.get('preview_backends') or [],
            'preview_provenance': _provenance,
        }
    )


# ── Manual per-character LoRA retrain (2026-08-09) ───────────────────────────
# Lets an already-existing storyteller_chars character (one whose contact-sheet
# run already finished and left a training/ dataset on disk) be (re)trained
# through lora_trainer_service directly, without re-running the whole
# contact-sheet pipeline. This is deliberately separate from
# bp_medusa_training.py's /api/medusa/training/* routes: those are hard-walled
# to the mdt_<12hex> namespace (see that file's ISOLATION CONTRACT docstring)
# and categorically refuse bare 12-hex storyteller_chars ids (verified live:
# HTTP 404 'unknown character'). This file already IS the general,
# non-isolated home for those ids — every other route here validates char_id
# with the same _CHAR_ID_RE defined at module scope — so the routes live here
# instead of duplicating validation/registration boilerplate in a new file.
#
# Resolution mirrors char_state_service._char_train_lora_for_family's own
# call site exactly rather than reinventing it:
#   - dataset_dir: contact_sheet_pipeline.training_dataset_dir(char_id) — the
#     SAME helper contact_sheet_pipeline.run_pipeline() calls right before it
#     builds the `info` dict handed to _char_train_lora_for_family (see
#     run_pipeline: `dataset_dir = training_dataset_dir(char_id)` then
#     `info['dataset_dir'] = dataset_dir`, `job['dataset_dir'] = dataset_dir`).
#     NOT the character root dir some OTHER call sites in char_state_service.py
#     default to (those are for preview rendering — a different dataset
#     concept whose fallback is the char root, e.g. `_char_params_from_bible`
#     below) — the root dir has no images at its own top level, only under
#     training/, and lora_trainer_service.start_training()'s own image count
#     / SimpleTuner instance_data_dir need a directory whose top level IS the
#     image set.
#   - trigger_token: _char_params_from_bible(char_id) (imported at the top of
#     this file) — the exact function char_state_service.py uses to check the
#     bible for an explicit trigger_token override before falling back to the
#     deterministic ZYG_CHAR_<char_id[:6].upper()> default (the same default
#     lora_trainer_service.start_training() itself falls back to when
#     trigger_token=None, and the same one contact_sheet_pipeline.
#     trigger_token_for() computes).
#
# Unlike char_state_service._char_train_lora_for_family, this route does NOT
# call that function directly — it blocks synchronously (a get_status() poll
# loop) for the entire training run, which would hang this HTTP request for
# hours. It calls start_training() directly instead (exactly like
# bp_medusa_training.py's api_training_start does) so the TrainingJob is
# created and the request returns immediately; the caller polls the /status
# route below, same response shape as bp_medusa_training.py's own /status
# route so scripts/qwen_cast_retrain.py needs only a URL-path change.
_RETRAIN_MODEL_FAMILIES = ('flux', 'sdxl', 'qwen', 'klein')


def _retrain_normalize_family(raw: Any) -> str:
    v = str(raw or 'qwen').strip().lower()
    return v if v in _RETRAIN_MODEL_FAMILIES else 'qwen'


def _retrain_char_dir(char_id: str) -> Optional[str]:
    """Existing storyteller_chars char dir for *char_id*, or None.

    Same containment pattern as bp_medusa_training.py's _safe_char_dir
    (regex match first, then a realpath+dirname containment check) even
    though _CHAR_ID_RE (^[a-f0-9]{12}$) structurally can't contain '..' or
    '/' — defense in depth, and consistent with how this file already
    handles char_id elsewhere (_restore_parked_char_photos above uses the
    same pattern). 'exists' means the bible is on disk, matching
    scripts/qwen_cast_retrain.py's own _discover_chars() existence check.
    """
    if not isinstance(char_id, str) or not _CHAR_ID_RE.match(char_id):
        return None
    root = os.path.realpath(_CHARS_DATASET_ROOT)
    cdir = os.path.realpath(os.path.join(root, char_id))
    if os.path.dirname(cdir) != root:
        return None
    if not os.path.isfile(os.path.join(cdir, 'character_bible.json')):
        return None
    return cdir


def _retrain_count_pairs(training_dir: str) -> int:
    """Count of image files with a same-stem .txt caption beside them."""
    try:
        names = set(os.listdir(training_dir))
    except OSError:
        return 0
    exts = ('.png', '.jpg', '.jpeg', '.webp')
    n = 0
    for fn in names:
        stem, ext = os.path.splitext(fn)
        if ext.lower() in exts and (stem + '.txt') in names:
            n += 1
    return n


@bp.route('/api/storyteller/training/characters/<char_id>/retrain', methods=['POST'])
@limiter.exempt
def api_storyteller_char_retrain(char_id: str):
    """Start LoRA training for an existing storyteller_chars character.

    Body (optional JSON): {'model_family': 'qwen' | 'flux' | 'sdxl'} —
    default 'qwen'. Response shape mirrors bp_medusa_training.py's
    POST .../train exactly: {'ok': True, 'result': {...}} once
    start_training() has been called — 'result' is
    lora_trainer_service.last_start_result(char_id) (its 'started' field
    tells a real launch from an internal refusal, e.g. already training) with
    'char_id' added — or {'ok': False, 'error': ...} for a pre-flight
    rejection (unknown character / empty dataset) that never reached
    start_training() at all.
    """
    cdir = _retrain_char_dir(char_id)
    if not cdir:
        return jsonify({'ok': False, 'error': 'unknown character'}), 404

    body = request.get_json(silent=True) or {}
    model_family = _retrain_normalize_family(body.get('model_family'))

    from zyg_workflows import contact_sheet_pipeline as _csp_retrain

    dataset_dir = _csp_retrain.training_dataset_dir(char_id)
    if not os.path.isdir(dataset_dir) or _retrain_count_pairs(dataset_dir) < 1:
        return jsonify(
            {
                'ok': False,
                'error': f'no training image+caption pairs at {dataset_dir} — run '
                f'the contact-sheet pipeline for this character first',
            }
        ), 400

    _params, _info = _char_params_from_bible(char_id)
    trigger_token = _info.get('trigger_token') or f'ZYG_CHAR_{char_id[:6].upper()}'

    from zyg_workflows.lora_trainer_service import get_trainer, last_start_result

    get_trainer().start_training(
        char_id,
        dataset_dir,
        trigger_token=trigger_token,
        model_family=model_family,
        cleanup_after=True,
    )
    result = last_start_result(char_id)
    result['char_id'] = char_id
    return jsonify({'ok': True, 'result': result})


@bp.route('/api/storyteller/training/characters/<char_id>/retrain/status', methods=['GET'])
@limiter.exempt
def api_storyteller_char_retrain_status(char_id: str):
    """Poll training status for a character started via the /retrain route
    above. Mirrors bp_medusa_training.py's GET .../status exactly:
    {'ok': True, 'status': {...}} — 'status' is whatever
    lora_trainer_service.get_status() returns, including its own
    status='not_found' shape for a character that was never trained (that is
    NOT a 404 here; the 404 below means the character itself doesn't exist).
    """
    if not _retrain_char_dir(char_id):
        return jsonify({'ok': False, 'error': 'unknown character'}), 404

    model_family = request.args.get('model_family')
    from zyg_workflows.lora_trainer_service import get_trainer

    status = get_trainer().get_status(char_id, model_family=model_family)
    return jsonify({'ok': True, 'status': status})
