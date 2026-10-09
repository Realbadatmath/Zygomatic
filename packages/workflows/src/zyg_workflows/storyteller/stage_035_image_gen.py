# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 3.5 of the storyteller pipeline — one image per scene.

The last range `_run_storyteller_pipeline` kept, and the only one that could
not be lifted as it stood: 1,384 lines of which five were nested ``def``s
rebinding seven of the block's locals through ``nonlocal``, which no context
field can be. The move is therefore a *refactor* — the closures became module
functions taking the state explicitly — and not the verbatim cut the other
eight stages were. Nothing any statement does changed; see ``SPLIT_LOG.md``
for the closure → function and ``nonlocal`` → field tables.

This module keeps the skeleton and everything that was never nested. On 2026-10-09 the
skeleton was itself 309 lines in one def, over the 300-line function ceiling, so each
phase became a helper below it — no statement changed, only where it lives:

    stage_035_image_generation(ctx)
      │  _update_stage / _check_stop / the opening log / comfy-offload env
      ├─ _make_state(ctx)          ImageGenState + the Comfy availability probe
      ├─ _render_all_scenes(ctx, st)
      │    └─ with _GPU_PIPELINE_LOCK:
      │         try:
      │           prepare_flux_paths(ctx, st)   stage_035_backend.py
      │           wait_for_vram(ctx, …)         stage_035_backend.py
      │           select_backend(ctx, st)       stage_035_backend.py
      │           the Blender-dataset flag, _check_drift_reference(ctx, st)
      │           for _si, scene in enumerate(ctx.scenes):
      │               generate_scene(ctx, st, _si, scene)   stage_035_scene_loop.py
      │           stage_036_anatomy_repair(ctx, st)         stage_036_anatomy.py
      │           _teardown_backends(ctx, st)   IPAdapter / LoRA / Comfy
      │         except Exception as _fe:  …
      │  the flux_images state write
      ├─ _unload_flux(ctx, st)
      └─ _identity_qc(ctx, img_paths)
           _qc_char_style / _is_stylized_render → _animated_identity_qc, or
           _arcface_identity_qc → _resolve_identity_anchor, _shot_types,
           _score_identity, _report_identity_scores

`st._hand_qa_fn` is bound here, once, with ``functools.partial``: the hand-QA
helper is *passed* to ``scene_still_helpers`` as ``hand_qa_fn=`` and so has to
stay a one-argument callable, and binding it once keeps it the single object
every call site shared when it was a closure."""

from __future__ import annotations

import functools
import logging as _zyg_logging
import os

from zyg_workflows import gui_state
from zyg_workflows.pipeline_storyteller import _st_env_on
from zyg_workflows.runtime import _GPU_PIPELINE_LOCK
from zyg_workflows.storyteller.context import ImageGenState
from zyg_workflows.storyteller.stage_035_backend import prepare_flux_paths, select_backend, wait_for_vram
from zyg_workflows.storyteller.stage_035_qa import mediapipe_hand_qa
from zyg_workflows.storyteller.stage_035_scene_loop import generate_scene
from zyg_workflows.storyteller.stage_036_anatomy import stage_036_anatomy_repair
from zyg_workflows.vram_manager import _deep_unload_flux_pipeline_cache, _ensure_comfy_offload_env

# The monolith's logger name, so a run's log lines stay under one channel.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_storyteller')


def _make_state(ctx):
    """Build the stage's ImageGenState and pick the Comfy or diffusers backend, logging which.

    Stage 3.5 may re-resolve or clear the LoRA for its own renders; it works on a copy so
    `ctx.lora_path` keeps what Stage 1 published. Returns the state object every helper
    below carries the block's locals in.
    """
    _log = ctx._log
    model_family = ctx.model_family

    st = ImageGenState(lora_path=ctx.lora_path)
    st._hand_qa_fn = functools.partial(mediapipe_hand_qa, ctx, st)
    from zyg_workflows import scene_still_helpers as _ssh_st

    st._ssh_st = _ssh_st

    st._st_lora_active = bool(st.lora_path)
    st._st_comfy_available = False
    try:
        from zyg_workflows import comfy_generation_service as _cgs_st_head

        st._st_comfy_available = _cgs_st_head.is_available()
    except Exception as _exc:
        _zyg_log.debug('comfy availability probe failed, using the diffusers path: %s', _exc)
    st._st_comfy_primary = st._st_comfy_available and model_family in ('sdxl', 'flux')
    st._st_use_flux_diffusers = not st._st_comfy_primary
    if st._st_comfy_primary:
        _log(
            'INFO',
            'Stage 3.5',
            f'{model_family.upper()} Comfy-primary — diffusers FLUX will not preload '
            f'(Comfy owns GPU; diffusers loads only on fallback)',
        )
    elif st._st_comfy_available:
        _log('INFO', 'Stage 3.5', 'Comfy unavailable — FLUX diffusers-only path')
    return st


def _check_drift_reference(ctx, st) -> None:
    """Set `st._st_drift_ref_ok` and say out loud when the character is not identity-verified.

    2026-07-31: the scene-0 HARD drift gate can only mean anything when a verified
    reference embedding exists. consistency_qa now reports 'unknown' (NOT a pass) instead
    of a fake 1.000 when it has no reference, so asking for require_drift_pass without one
    would reject every scene 0. Check first, and say out loud when the character's frames
    are simply not identity-verified.
    """
    _log = ctx._log
    char_id = ctx.char_id

    st._st_drift_ref_ok = False
    try:
        from zyg_workflows import consistency_qa_service as _cqa_gate

        _cqa_gate.ensure_reference_from_bible(
            char_id,
            log_fn=lambda m: _log('INFO', 'Stage 3.5', m),
        )
        st._st_drift_ref_ok = bool(char_id) and _cqa_gate.has_reference(char_id)
    except Exception as _cqa_gate_e:
        _log(
            'WARNING',
            'Stage 3.5',
            f'Drift-reference check unavailable ({_cqa_gate_e!r}) — per-frame identity drift will NOT be enforced',
        )
    if char_id and not st._st_drift_ref_ok:
        ctx.pipeline_state['_st_drift_unverified'] = True
        _log(
            'WARNING',
            'Stage 3.5',
            'No verified drift reference for this character — per-frame '
            'identity drift is UNVERIFIED (scene-0 hard gate disabled); '
            'drift scores will be reported as unknown, never as a pass',
        )


def _teardown_backends(ctx, st) -> None:
    """Tear the IPAdapter down, unload the character LoRA, and release a Comfy-primary FLUX."""
    _log = ctx._log

    # ── Teardown IPAdapter after all scenes ──────────────────────────────────
    if st._ipa_ready_st and st._ipa_svc_st is not None and gui_state._FLUX_DEV_PIPELINE_CACHE is not None:
        try:
            st._ipa_svc_st.teardown(gui_state._FLUX_DEV_PIPELINE_CACHE)
        except (AttributeError, TypeError) as _ipa_te:
            # 2026-07-31: a failed teardown leaves IPAdapter hooks on
            # the cached pipeline — that must be visible, not silent.
            _log('WARNING', 'Stage 3.5', f'IPAdapter teardown failed: {_ipa_te!r}')
        except Exception as _exc:
            _zyg_log.warning('IPAdapter teardown failed, hooks stay on the cached pipeline: %s', _exc)

    # Unload character LoRA after generation (FLUX diffusers only)
    if st.lora_path and gui_state._FLUX_DEV_PIPELINE_CACHE is not None:
        try:
            gui_state._FLUX_DEV_PIPELINE_CACHE.unload_lora_weights()
        except Exception as _exc:
            _zyg_log.warning('character LoRA unload failed, it may leak into the next render: %s', _exc)

    if st._st_comfy_primary:
        _deep_unload_flux_pipeline_cache(
            log_fn=lambda m: _log('INFO', 'Stage 3.5', m),
        )


def _render_all_scenes(ctx, st) -> None:
    """Under the GPU lock: resolve the backend, render every scene, repair anatomy, tear down.

    A failure anywhere inside the lock is logged and recorded on `job['error']`, and the
    stage carries on with whatever images were produced — exactly as the monolith did.
    """
    _log = ctx._log
    pipeline_state = ctx.pipeline_state

    with _GPU_PIPELINE_LOCK:
        ctx._check_stop()
        pass  # (global stmt removed: names moved to gui_state)
        st._char_ref_img = pipeline_state.get('char_reference_image')
        try:
            _min_vram_gb = prepare_flux_paths(ctx, st)
            wait_for_vram(ctx, _min_vram_gb)
            select_backend(ctx, st)

            st._st_blender_ds = bool(pipeline_state.get('storyteller_blender_dataset'))
            _check_drift_reference(ctx, st)

            for _si, scene in enumerate(ctx.scenes):
                generate_scene(ctx, st, _si, scene)

            stage_036_anatomy_repair(ctx, st)
            _teardown_backends(ctx, st)

        except Exception as _fe:
            _log('ERROR', 'Stage 3.5', f'FLUX generation failed: {_fe}')
            ctx.job['error'] = str(_fe)


def _unload_flux(ctx, st) -> None:
    """Drop the FLUX pipeline cache and empty the CUDA allocator before the Ken Burns stage.

    Run unconditionally — even if _FLUX_DEV_PIPELINE_CACHE is None the pipeline object may
    have been partially loaded onto CUDA before an OOM, and those tensors need to be
    garbage-collected.
    """
    try:
        if gui_state._FLUX_DEV_PIPELINE_CACHE is not None:
            gui_state._FLUX_DEV_PIPELINE_CACHE = None
        import gc as _gc_st

        _gc_st.collect()
        _gc_st.collect()
        st._torch_st.cuda.empty_cache()
        ctx._log('INFO', 'Stage 3.5', 'FLUX unloaded — VRAM freed')
    except Exception as _ue:
        ctx._log('WARNING', 'Stage 3.5', f'FLUX unload warning: {_ue}')


def _qc_char_style(char_id):
    """Return the CHARACTER's render style, lower-cased, defaulting to 'photorealistic'.

    2026-07-24: identity QC gates on this and NOT on the scene visual_style — run a6f458bc
    skipped identity QC entirely because the scene style was 'cinematic' while the
    character is photoreal.
    """
    _char_style_idqc = 'photorealistic'
    try:
        from zyg_workflows.char_state_service import _char_render_style as _crs_idqc
        from zyg_workflows.char_state_service import _char_params_from_bible as _cpfb_idqc

        _p_idqc, _i_idqc = _cpfb_idqc(char_id)
        _char_style_idqc = (_crs_idqc(_p_idqc, _i_idqc) or 'photorealistic').lower()
    except Exception as _exc:
        _zyg_log.warning('render-style lookup failed, identity QC assumes photorealistic: %s', _exc)
    return _char_style_idqc


def _is_stylized_render(ctx, char_style) -> bool:
    """True when ArcFace must not judge these frames, so the photoreal path is skipped.

    2026-07-25: SDXL twin renders 3D-toon — ArcFace cannot embed a cartoon face and the
    anchor is the photoreal FLUX contact sheet, so identity QC would fail 23/23 (run
    b6dae41a). Skip it for animated renders (mirrors the hand-QC skip); consistency is
    still guarded by the animated drift gate against the animated master.
    2026-07-27: restyle (Arcane) is semi-realistic but the anchor is the photoreal master —
    route it through the SAME style-agnostic VLM skin/hair attribute gate as animated
    (preserves identity QC), NOT the ArcFace path.
    """
    return bool(
        ctx._animated_render
        or ctx._restyle_render
        or any(t in char_style for t in ('toon', 'anime', 'cartoon', 'animat'))
    )


def _animated_identity_qc(ctx, img_paths) -> None:
    """Run the VLM skin/hair attribute gate over a stylized render's frames.

    ArcFace can't reliably embed a stylized face — run a VLM attribute identity gate
    instead of skipping entirely (review finding).
    """
    _log = ctx._log
    try:
        from zyg_workflows import animated_sdxl_dataset as _anim_idc

        _anim_bad = _anim_idc.identity_check_frames(
            ctx.char_id, list(img_paths), log_fn=lambda m: _log('INFO', 'Stage 3.5', m)
        )
        if _anim_bad:
            ctx.pipeline_state['_st_identity_drift_scenes'] = _anim_bad
            _log(
                'WARNING',
                'Stage 3.5',
                f'Animated identity QC: {len(_anim_bad)}/{len(img_paths)} '
                f'frames mismatch character skin/hair: {_anim_bad}',
            )
        else:
            _log('INFO', 'Stage 3.5', f'Animated identity QC passed: {len(img_paths)} frames match')
    except Exception as _anim_idc_e:
        _log('WARNING', 'Stage 3.5', f'Animated identity QC skipped (error: {_anim_idc_e!r})')


def _resolve_identity_anchor(ctx):
    """Return the image identity QC may anchor on, or None when there is no verified one.

    2026-07-31: FAILS CLOSED BY DESIGN. This used to fall back to char_reference_image —
    an unverified runtime reference (for c3345deb5bde that was a generated preview of a
    DIFFERENT person). Anchoring identity QC on an unverified image certifies frames as
    correct exactly when they match the wrong person, and flags correct frames as drifted.
    Skip the gate and say so. With ZYG_ST_IDQC_REQUIRE_ANCHOR off the old fallback is
    returned, and the log says the results are not trustworthy.
    """
    _log = ctx._log
    from zyg_workflows import contact_sheet_pipeline as _csp_idqc

    _anchor_idqc = _csp_idqc.identity_anchor_face_path(ctx.char_id)
    if not (_anchor_idqc and os.path.isfile(_anchor_idqc)):
        if _st_env_on('ZYG_ST_IDQC_REQUIRE_ANCHOR'):
            _anchor_idqc = None
            ctx.pipeline_state['_st_identity_qc_unverified'] = True
            _log(
                'WARNING',
                'Stage 3.5',
                'Identity QC SKIPPED — no verified contact-sheet '
                'identity anchor for this character. Frames are '
                'UNVERIFIED; refusing to anchor on the runtime '
                'reference image (it is not a verified identity source)',
            )
        else:
            _anchor_idqc = ctx.pipeline_state.get('char_reference_image')
            _log(
                'WARNING',
                'Stage 3.5',
                'ZYG_ST_IDQC_REQUIRE_ANCHOR=0 — identity QC anchored on '
                'an UNVERIFIED reference image; results are not trustworthy',
            )
    return _anchor_idqc


def _shot_types(pipeline_state):
    """Return every scripted scene's shot_type, lower-cased, or [] when the script is unreadable."""
    try:
        return [str((s or {}).get('shot_type', '') or '').lower() for s in (pipeline_state.get('script') or [])]
    except Exception:
        return []


def _score_identity(idqc, embeds, ref_emb, img_paths, shots):
    """Return (drifted, no_face) for img_paths measured against the anchor embedding.

    `drifted` is [(scene number, similarity)] for every frame under the front threshold.
    `no_face` is the scene numbers with no detectable face: 2026-07-24 r3, for a photoreal
    character-led story a face-framed shot with NO detectable face is a defect, not a skip
    — dd36662e's opener was a person-free blob and that branch ignored it. r3 review fix:
    only shot types that PROMISE a visible face count, because wide/establishing framings
    ('environment prominent', 'full body visible') routinely defeat detection on
    legitimately good frames. Without an anchor embedding nothing is scored at all.
    """
    _drifted = []
    _no_face = []
    if not ref_emb:
        return _drifted, _no_face
    _thr_idqc = idqc.threshold_for('front')
    for _ii, _pth_idqc in enumerate(img_paths):
        _emb = (embeds.get(_pth_idqc) or {}).get('embedding')
        if not _emb:
            _shot_ii = shots[_ii] if _ii < len(shots) else ''
            if _shot_ii in ('wide', 'establishing'):
                continue
            _no_face.append(_ii + 1)
            continue
        _sim = idqc.cosine(ref_emb, _emb)
        if _sim < _thr_idqc:
            _drifted.append((_ii + 1, round(_sim, 3)))
    return _drifted, _no_face


def _report_identity_scores(ctx, img_paths, drifted, no_face) -> None:
    """Record the no-face and drifted scenes on the pipeline state and log what was found."""
    _log = ctx._log
    if no_face:
        ctx.pipeline_state['_st_no_face_scenes'] = no_face
        _log(
            'WARNING',
            'Stage 3.5',
            f'Identity QC: no face detected in scene(s) {no_face} — '
            f'counted as identity failures for the degradation gate',
        )
    if drifted:
        ctx.pipeline_state['_st_identity_drift_scenes'] = drifted
        _log(
            'WARNING',
            'Stage 3.5',
            f'Identity QC: {len(drifted)}/{len(img_paths)} scenes below '
            f'similarity threshold vs character anchor: {drifted}',
        )
    if not drifted and not no_face:
        _log(
            'INFO',
            'Stage 3.5',
            f'Identity QC passed: {len(img_paths)} scenes match the character anchor',
        )


def _arcface_identity_qc(ctx, img_paths) -> None:
    """Embed the anchor and every frame with insightface and report the identity drift."""
    from zyg_workflows import identity_qc_service as _idqc

    _idqc_ok, _idqc_why = _idqc.available()
    if not _idqc_ok:
        ctx._log('INFO', 'Stage 3.5', f'Identity QC unavailable ({_idqc_why}) — skipped')
        return
    _anchor_idqc = _resolve_identity_anchor(ctx)
    if not (_anchor_idqc and os.path.isfile(_anchor_idqc)):
        return
    # embed_images returns {path: {face_detected, embedding, ...}}
    _embeds = _idqc.embed_images([_anchor_idqc] + list(img_paths))
    _ref_emb = (_embeds.get(_anchor_idqc) or {}).get('embedding')
    _drifted, _no_face = _score_identity(_idqc, _embeds, _ref_emb, img_paths, _shot_types(ctx.pipeline_state))
    _report_identity_scores(ctx, img_paths, _drifted, _no_face)


def _identity_qc(ctx, img_paths) -> None:
    """Verify every frame is the right character — 2026-07-24 fix, never fatal.

    Per-scene identity QC (insightface via identity_qc_service). No frame identity was ever
    verified before assembly — job 10c84d83 shipped 17 wrong-character frames undetected.
    Photoreal chars only; a stylized render goes through the VLM attribute gate instead.
    """
    char_id = ctx.char_id
    try:
        _char_style_idqc = _qc_char_style(char_id)
        _skip_idqc_animated = _is_stylized_render(ctx, _char_style_idqc)
        if (ctx._animated_render or ctx._restyle_render) and char_id:
            _animated_identity_qc(ctx, img_paths)
        elif _skip_idqc_animated and char_id:
            ctx._log('INFO', 'Stage 3.5', 'Identity QC skipped — stylized render (ArcFace is photoreal-only)')
        if char_id and not _skip_idqc_animated:
            _arcface_identity_qc(ctx, img_paths)
    except Exception as _idqc_e:
        # repr + traceback: the 11:55 run logged the useless "error: 0"
        # because str(KeyError(0)) is just "0" and the traceback was dropped.
        import traceback as _tb_idqc

        ctx._log('WARNING', 'Stage 3.5', f'Identity QC skipped (error: {_idqc_e!r})\n{_tb_idqc.format_exc()}')


def stage_035_image_generation(ctx) -> None:
    """Stage 3.5: FLUX image generation — one image per scene, then per-scene identity QC."""
    _log = ctx._log
    model_family = ctx.model_family
    n_scenes = ctx.n_scenes

    # ── Stage 3.5: FLUX Image Generation ──────────────────────────────────────
    ctx._update_stage('Stage 3.5 — AI Image Generation', 30)
    ctx._check_stop()

    _log(
        'INFO',
        'Stage 3.5',
        f'Generating {n_scenes} {model_family.upper()} images '
        f'(style={ctx.visual_style}, LoRA={"yes" if ctx.lora_path else "no"})…',
    )
    _ensure_comfy_offload_env()

    st = _make_state(ctx)
    _render_all_scenes(ctx, st)

    img_paths = st.img_paths
    ctx.pipeline_state['flux_images'] = img_paths
    _log('INFO', 'Stage 3.5', f'Generated {len(img_paths)}/{n_scenes} images')

    # Unload FLUX to free VRAM before Ken Burns (CPU-only stage).
    _unload_flux(ctx, st)

    ctx._save()
    ctx._check_stop()

    if not img_paths:
        raise RuntimeError('No images generated — cannot assemble video')

    _identity_qc(ctx, img_paths)

    ctx.img_paths = img_paths
