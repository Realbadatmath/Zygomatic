# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The steps of Stage 1 — character prep, one function per seam.

``stage_01_character_prep`` was a single 391-line function with seven blocks:
resolve the LoRA and its trigger token (waiting for a training run if one is in
flight), load the character bible, let the bible override the client's
``character_params``, sanitise the public ``extra_prompt`` once, read the render
mode off the on-disk manifest, pick a VERIFIED identity reference image, and
choose the narrator and character voices. Each is a function here and the stage
is the order they run in.

Nothing here changes a decision, a log line, an environment switch or the order
of the writes into ``pipeline_state`` — ``pipeline_state['lora_path']`` in
particular is still written from the value the LoRA step resolved, *before* the
bible step may re-resolve the local one."""

import os
import time

from zyg_workflows.char_state_service import _char_is_blender_dataset, _pick_char_preview_reference
from zyg_workflows.pipeline_storyteller import (
    _ST_DATASET_ROOT,
    _st_age_from_params,
    _st_char_manifest,
    _st_env_on,
    _st_is_minor,
    _st_pick_voice,
    _st_reconcile_params_with_bible,
    _st_sanitize_extra_prompt,
)


def wait_for_lora(ctx, trainer, st):
    """Poll a LoRA training run until it finishes, fails, or the window closes.

    The wait window is sized for 1200-step/1024-res runs (~70-85 min); the old
    30 minutes silently dropped every such character to IPAdapter-only. Returns
    the last trainer status dict."""
    _lora_wait_s = int(os.environ.get('ZYG_LORA_PIPELINE_WAIT_S', '5400'))
    ctx._log(
        'INFO',
        'Stage 1',
        f'LoRA training {st.get("pct", 0):.0f}% — waiting (max {_lora_wait_s // 60} min)…',
    )
    deadline = time.time() + _lora_wait_s
    while time.time() < deadline:
        ctx._check_stop()
        time.sleep(15)
        st = trainer.get_status(ctx.char_id, model_family=ctx.model_family)
        ctx._log(
            'INFO',
            'Stage 1',
            f'LoRA training {st.get("pct", 0):.0f}% — step {st.get("step", 0)}/{st.get("total_steps", 1000)}',
        )
        if st.get('done') or st.get('failed'):
            break
    return st


def resolve_lora(ctx):
    """Resolve the character's LoRA and trigger token; returns ``(path, token)``.

    A finished training run gives a path for this pipeline's model family and
    the token it was trained with; a run still in flight is waited for. A LoRA
    that exists but belongs to another family, a failed run and a missing
    trainer all fall back to IPAdapter-only conditioning with a warning. Also
    records both values in ``pipeline_state``."""
    lora_path = None
    trigger_token = f'ZYG_CHAR_{ctx.char_id[:6].upper()}' if ctx.char_id else ''

    from zyg_workflows import character_lora_family as _clf_st1

    if ctx.char_id:
        try:
            import importlib.util as _ilu_st

            _lts_spec = _ilu_st.find_spec('lora_trainer_service')
            if _lts_spec:
                from zyg_workflows import lora_trainer_service as _lts

                trainer = _lts.get_trainer()
                st = trainer.get_status(ctx.char_id, model_family=ctx.model_family)
                if st.get('done'):
                    lora_path = _clf_st1.resolve_char_lora_path(
                        ctx.char_id,
                        ctx.model_family,
                        preferred_path=st.get('lora_path'),
                    )
                    trigger_token = st.get('trigger_token') or trigger_token
                    if lora_path:
                        ctx._log('INFO', 'Stage 1', f'LoRA ready ({ctx.model_family}): {lora_path}')
                    elif st.get('lora_path'):
                        ctx._log(
                            'WARNING',
                            'Stage 1',
                            f'LoRA on disk does not match pipeline family {ctx.model_family} — IPAdapter / Comfy-only mode',
                        )
                elif st.get('failed') or st.get('status') == 'not_found':
                    ctx._log('WARNING', 'Stage 1', 'LoRA not available — using IPAdapter-only character conditioning')
                else:
                    st = wait_for_lora(ctx, trainer, st)
                    if st.get('done'):
                        lora_path = _clf_st1.resolve_char_lora_path(
                            ctx.char_id,
                            ctx.model_family,
                            preferred_path=st.get('lora_path'),
                        )
                        trigger_token = st.get('trigger_token') or trigger_token
                        ctx._log(
                            'INFO', 'Stage 1', f'LoRA training complete ({ctx.model_family}): {lora_path or "none"}'
                        )
                    else:
                        ctx._log('WARNING', 'Stage 1', 'LoRA training did not finish in time — IPAdapter-only mode')
        except Exception as _e_lora:
            ctx._log('WARNING', 'Stage 1', f'LoRA status check failed: {_e_lora} — continuing')

    ctx.pipeline_state['lora_path'] = lora_path
    ctx.pipeline_state['trigger_token'] = trigger_token
    return lora_path, trigger_token


def load_character_bible(ctx, lora_path):
    """Load the continuity package for Comfy and drift QA into ``pipeline_state``.

    The bible is pointed at whatever LoRA this family resolves to — which may
    produce a ``lora_path`` the LoRA step could not find, so the (possibly
    updated) path is returned. The loaded copy always gets
    ``conditioning.hand_detail_pass`` on. Non-fatal: a failure leaves
    ``pipeline_state['character_bible']`` None and logs a warning."""
    ctx.pipeline_state['character_bible'] = None
    if not ctx.char_id:
        return lora_path
    try:
        from zyg_workflows import character_bible_service as _cbs_st
        from zyg_workflows import character_lora_family as _clf_st1
        from zyg_workflows import consistency_qa_service as _cqa_st

        _bible_pkg = _cbs_st.load(ctx.char_id)
        if _bible_pkg and lora_path:
            _cbs_st.update_lora(ctx.char_id, lora_path, model_family=ctx.model_family)
            _bible_pkg = _cbs_st.load(ctx.char_id)
        elif _bible_pkg and ctx.char_id:
            _resolved_lora = _clf_st1.resolve_char_lora_path(ctx.char_id, ctx.model_family)
            if _resolved_lora:
                _cbs_st.update_lora(ctx.char_id, _resolved_lora, model_family=ctx.model_family)
                lora_path = _resolved_lora
                _bible_pkg = _cbs_st.load(ctx.char_id)
        if _bible_pkg:
            import copy as _copy_st_bible

            _bible_pkg = _copy_st_bible.deepcopy(_bible_pkg)
            _bible_pkg.setdefault('conditioning', {})['hand_detail_pass'] = True
            ctx.pipeline_state['character_bible'] = _bible_pkg
            _cqa_st.ensure_reference_from_bible(
                ctx.char_id,
                log_fn=lambda m: ctx._log('INFO', 'Stage 1', m),
            )
            ctx._log(
                'INFO',
                'Stage 1',
                f'Character bible loaded — trigger={_bible_pkg.get("trigger_token", "")} '
                f'refs={len(_bible_pkg.get("conditioning", {}).get("ipadapter_reference_images", []))} '
                f'hand_detail_pass=on',
            )
    except Exception as _bible_e:
        ctx._log('WARNING', 'Stage 1', f'Character bible load failed (non-fatal): {_bible_e}')
    return lora_path


def reconcile_character_params(ctx, character_params):
    """2026-07-31: THE BIBLE BEATS THE CLIENT. Returns the resolved params.

    ``character_params`` is unvalidated JSON from a public browser and used to
    be the SOLE source of gender/age/hair/eyes/skin/build/clothing for the
    Stage 2a story, the Stage 2b render prompts and the fallback scene builder,
    while the server-side bible was loaded and never consulted: a crafted POST
    could make Sonnet write a 25-year-old blonde woman's story for a
    12-year-old boy's LoRA. For a char_id that resolves to a bible the client
    may now decide NOTHING identity-bearing. ``ZYG_ST_BIBLE_WINS=0`` keeps the
    client authoritative and says so loudly; a reconciliation error does the
    same."""
    _st_bible_wins = _st_env_on('ZYG_ST_BIBLE_WINS')
    _st_bible_for_params = ctx.pipeline_state.get('character_bible')
    if _st_bible_for_params and _st_bible_wins:
        try:
            character_params, _param_conflicts = _st_reconcile_params_with_bible(
                character_params,
                _st_bible_for_params,
            )
            ctx.job['character_params_resolved'] = dict(character_params)
            if _param_conflicts:
                ctx._log(
                    'WARNING',
                    'Stage 1',
                    f'Client character_params OVERRIDDEN by the character bible '
                    f'({len(_param_conflicts)} field(s) disagreed): ' + '; '.join(_param_conflicts[:20]),
                )
            else:
                ctx._log(
                    'INFO',
                    'Stage 1',
                    'character_params reconciled with the character bible — no client/server disagreement',
                )
        except Exception as _rec_e:
            ctx._log(
                'WARNING',
                'Stage 1',
                f'character_params reconciliation failed ({_rec_e!r}) — '
                f'client values kept; identity may be client-controlled',
            )
    elif _st_bible_for_params and not _st_bible_wins:
        ctx._log(
            'WARNING',
            'Stage 1',
            'ZYG_ST_BIBLE_WINS=0 — client character_params are authoritative (identity is NOT server-validated)',
        )
    return character_params


def record_clean_extra_prompt(ctx, character_params):
    """Sanitise the PUBLIC ``extra_prompt`` ONCE, here, and record what was kept.

    2026-07-31 (finding #59): the accepted value lands in
    ``pipeline_state['_st_extra_prompt_clean']`` so an operator can audit what a
    public user injected; its *placement* in the prompt is Stage 3.5's business.
    With ``ZYG_ST_SANITIZE_EXTRA_PROMPT=0`` the client string is used verbatim
    and the log says so."""
    _st_extra_clean = ''
    if _st_env_on('ZYG_ST_SANITIZE_EXTRA_PROMPT'):
        _st_extra_raw = str((character_params or {}).get('extra_prompt') or '').strip()
        _st_extra_clean, _st_extra_notes = _st_sanitize_extra_prompt(
            _st_extra_raw,
            minor=_st_is_minor(character_params),
        )
        if _st_extra_raw:
            ctx._log(
                ('WARNING' if _st_extra_notes else 'INFO'),
                'Stage 1',
                f'Client extra_prompt accepted={_st_extra_clean[:200]!r} '
                f'(raw={_st_extra_raw[:200]!r}' + (f'; {"; ".join(_st_extra_notes)}' if _st_extra_notes else '') + ')',
            )
    else:
        _st_extra_clean = str((character_params or {}).get('extra_prompt') or '').strip()
        if _st_extra_clean:
            ctx._log('WARNING', 'Stage 1', 'ZYG_ST_SANITIZE_EXTRA_PROMPT=0 — client extra_prompt used VERBATIM')
    ctx.pipeline_state['_st_extra_prompt_clean'] = _st_extra_clean


def resolve_dataset_provenance(ctx, character_params):
    """Read the render mode off the on-disk manifest; returns the char-info dict.

    2026-07-31: render mode is a property of how the character was TRAINED, so
    it comes from ``manifest.json``, never from the request body (finding #58:
    the old call passed ``job={'render_mode': client string}`` and
    ``info={'package': bible}`` — a dict containing NONE of the keys
    ``_char_is_blender_dataset`` looks for, so the client string was the ONLY
    input and the server manifest was structurally unreachable). Sets
    ``pipeline_state['storyteller_blender_dataset']`` and logs the provenance.
    ``ZYG_ST_BLENDER_FROM_MANIFEST=0`` restores the client hint."""
    _st_manifest = _st_char_manifest(ctx.char_id, ctx.pipeline_state.get('character_bible'))
    _st_char_info = {
        'package': ctx.pipeline_state.get('character_bible'),
        'manifest': _st_manifest,
        'source': _st_manifest.get('source'),
        'render_mode': _st_manifest.get('render_mode'),
        'images': _st_manifest.get('images'),
        'dataset_dir': os.path.join(_ST_DATASET_ROOT, ctx.char_id) if ctx.char_id else '',
    }
    if _st_env_on('ZYG_ST_BLENDER_FROM_MANIFEST'):
        ctx.pipeline_state['storyteller_blender_dataset'] = _char_is_blender_dataset(
            _st_char_info,
            {},
        )
        if not _st_manifest:
            ctx._log(
                'WARNING',
                'Stage 1',
                'No manifest.json for this character — blender-dataset flag '
                'falls back to the bible/source hint (client render_mode ignored)',
            )
    else:
        ctx.pipeline_state['storyteller_blender_dataset'] = _char_is_blender_dataset(
            _st_char_info,
            {'render_mode': (character_params or {}).get('render_mode', '')},
        )
    ctx._log(
        'INFO',
        'Stage 1',
        f'Dataset provenance (server manifest): source='
        f'{_st_manifest.get("source") or "unknown"} '
        f'render_mode={_st_manifest.get("render_mode") or "unknown"} '
        f'stills={len(_st_manifest.get("images") or [])} '
        f'→ blender_dataset={ctx.pipeline_state.get("storyteller_blender_dataset")}',
    )
    return _st_char_info


def is_generated_preview(path):
    """Is this basename a GENERATED preview rather than a training still?

    ``preview_*`` and ``style_preview*`` files in the dataset root are renders,
    never ground truth, so they must not become the identity reference."""
    return os.path.basename(path).lower().startswith(('preview_', 'style_preview'))


def pick_reference_image(ctx, char_info, character_params):
    """Choose the VERIFIED identity reference image, or record that there is none.

    2026-07-31 (finding #11): THE IDENTITY REFERENCE MUST NOT BE A GENERATED
    PREVIEW. Order: (1) the verified contact-sheet identity anchor, (2) the
    dataset picker with the REAL info dict (training stills from
    ``manifest.json`` — the old stub ``{'package': bible}`` defeated the
    ``info['images']`` branch), (3) nothing. A broken sweep endpoint once wrote
    a generic adult-female non-LoRA ``preview_flux_front.png`` into a
    12-year-old boy's dataset and the last-resort listdir scan handed it to the
    render path, InstantID, the img2img base and the identity-QC anchor; a
    second blacklist check here rejects such a file even if the picker returns
    it. A Blender training set skips the whole question. Writes
    ``pipeline_state['char_reference_image']``."""
    if ctx.char_id and not ctx.pipeline_state.get('storyteller_blender_dataset'):
        _dataset_root_st = _ST_DATASET_ROOT
        _ref_pick = None
        _ref_src = ''
        if _st_env_on('ZYG_ST_REF_FROM_MANIFEST'):
            try:
                from zyg_workflows import contact_sheet_pipeline as _csp_ref

                _anchor_ref = _csp_ref.identity_anchor_face_path(ctx.char_id)
                if _anchor_ref and os.path.isfile(_anchor_ref):
                    _ref_pick, _ref_src = _anchor_ref, 'contact-sheet identity anchor'
            except Exception as _csp_ref_e:
                ctx._log('INFO', 'Stage 1', f'Contact-sheet anchor lookup skipped ({_csp_ref_e!r})')
        if not _ref_pick:
            _ref_pick = _pick_char_preview_reference(
                os.path.join(_dataset_root_st, ctx.char_id),
                (
                    char_info
                    if _st_env_on('ZYG_ST_REF_FROM_MANIFEST')
                    else {'package': ctx.pipeline_state.get('character_bible')}
                ),
                prefer_face=True,
            )
            _ref_src = 'dataset picker'
        # Belt-and-braces: reject a generated preview even if the picker
        # returns one (the picker gets the same blacklist separately).
        if _ref_pick and _st_env_on('ZYG_ST_REF_FROM_MANIFEST') and is_generated_preview(_ref_pick):
            ctx._log(
                'WARNING',
                'Stage 1',
                f'Rejected {os.path.basename(_ref_pick)} as character reference — '
                f'generated previews are not ground truth (no verified reference used)',
            )
            _ref_pick = None
        if _ref_pick and os.path.getsize(_ref_pick) > 10_000:
            ctx.pipeline_state['char_reference_image'] = _ref_pick
            ctx._log(
                'INFO', 'Stage 1', f'Character reference image found via {_ref_src}: {os.path.basename(_ref_pick)}'
            )
        else:
            ctx.pipeline_state['char_reference_image'] = None
            ctx._log(
                'WARNING',
                'Stage 1',
                'No VERIFIED character reference image — scenes rely on the '
                'LoRA/trigger token only (no img2img anchor, no InstantID face)',
            )
    elif ctx.pipeline_state.get('storyteller_blender_dataset'):
        ctx.pipeline_state['char_reference_image'] = None
        ctx._log(
            'INFO', 'Stage 1', 'Blender training set — greybox portrait skipped; LoRA locked generation for scenes'
        )


def legacy_narrator_voice(char_gender):
    """The pre-catalog narrator voice for a gender string.

    Jenny for anything female, Brian for male or unspecified — the hardcoded
    pair the catalog lookup still prefers, to avoid needless churn."""
    return (
        'en-US-JennyNeural'
        if 'female' in char_gender or char_gender == 'f'
        else 'en-US-BrianNeural'  # male or unspecified
    )


def pick_narrator_voice(ctx, char_gender, narrator_voice, from_bible):
    """The voice that TELLS the story; returns it (the user's choice wins).

    An adult narrator is correct here, so the catalog's narrator-eligible
    subset is used, gender-matched, with the legacy pair preferred. A catalog
    miss and ``ZYG_ST_VOICE_FROM_BIBLE=0`` both fall back to the legacy voice
    and log which happened."""
    if narrator_voice:
        ctx._log('INFO', 'Stage 1', f'Using user-selected narrator voice: {narrator_voice}')
        return narrator_voice
    _legacy_narrator = legacy_narrator_voice(char_gender)
    narrator_voice = _legacy_narrator
    if from_bible:
        _nv, _nwhy = _st_pick_voice(
            char_gender,
            None,
            kind='narrator',
            prefer=(_legacy_narrator, 'en-US-BrianNeural'),
        )
        if _nv:
            narrator_voice = _nv
            ctx._log(
                'INFO',
                'Stage 1',
                f'Auto-selected narrator voice: {narrator_voice} — {_nwhy} '
                f'(bible gender={char_gender or "unspecified"})',
            )
        else:
            ctx._log(
                'WARNING',
                'Stage 1',
                f'Narrator voice catalog lookup failed ({_nwhy}) — falling back to {narrator_voice}',
            )
    else:
        ctx._log(
            'INFO',
            'Stage 1',
            f'Auto-selected narrator voice: {narrator_voice} '
            f'(gender: {char_gender or "unspecified"}; '
            f'ZYG_ST_VOICE_FROM_BIBLE=0)',
        )
    return narrator_voice


def pick_character_voice(ctx, char_gender, char_age, narrator_voice, character_voice, voice_style, from_bible):
    """The voice the character SPEAKS with in character mode; returns it.

    2026-07-31: the voice IS the character — it must match the bible's gender
    AND age. Without this the code fell through to ``narrator_voice`` (an
    adult) for every child character. A catalog miss keeps the narrator and
    says so."""
    if voice_style == 'character' and not character_voice and from_bible:
        _cv, _cwhy = _st_pick_voice(char_gender, char_age, kind='character')
        if _cv:
            character_voice = _cv
            ctx._log(
                'INFO',
                'Stage 1',
                f'Auto-selected CHARACTER voice: {character_voice} — {_cwhy} '
                f'(bible gender={char_gender or "unspecified"}, '
                f'age={char_age if char_age is not None else "unknown"})',
            )
        else:
            ctx._log(
                'WARNING',
                'Stage 1',
                f'No age/gender-appropriate character voice ({_cwhy}) — narration falls back to {narrator_voice}',
            )
    return character_voice


def select_voices(ctx, character_params):
    """Pick the TTS voices; returns ``(narrator, character, effective)``.

    Gender comes from the RECONCILED (bible-authoritative) params and age is
    respected: the old code read the untrusted client gender field and
    hardcoded exactly two voices, so a 12-year-old boy was narrated — and, in
    character mode, SPOKEN — by an adult narrator. In character voice mode the
    character voice overrides the narrator for TTS, which is what ``effective``
    carries."""
    from_bible = _st_env_on('ZYG_ST_VOICE_FROM_BIBLE')
    _char_gender = str((character_params.get('gender') or '')).strip().lower()
    _char_age_v = _st_age_from_params(character_params)
    narrator_voice = pick_narrator_voice(ctx, _char_gender, ctx.narrator_voice, from_bible)
    character_voice = pick_character_voice(
        ctx,
        _char_gender,
        _char_age_v,
        narrator_voice,
        ctx.character_voice,
        ctx.voice_style,
        from_bible,
    )
    _effective_tts_voice = character_voice if (ctx.voice_style == 'character' and character_voice) else narrator_voice
    if ctx.voice_style == 'character' and character_voice:
        ctx._log('INFO', 'Stage 1', f'Character voice mode — using character voice: {character_voice}')
    return narrator_voice, character_voice, _effective_tts_voice
