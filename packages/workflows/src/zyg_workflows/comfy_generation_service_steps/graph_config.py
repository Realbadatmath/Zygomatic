# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from .preflight import Any, StillRenderCtx, _svc, os

import logging

# Re-created by assignment rather than imported from the sibling module: getLogger
# returns the one singleton the original module held, and an assigned global keeps the
# method-call bytecode of every `_zyg_log.debug(...)` below unchanged.
_zyg_log = logging.getLogger('zyg_workflows.comfy_generation_service_steps')
# --------------------------------------------------------------------------- #
# Graph configuration
# --------------------------------------------------------------------------- #


def configure_detailer_passes(ctx: StillRenderCtx) -> None:
    """Patch the SAM loader and enable/strip the face + hand second passes."""
    svc = _svc()
    workflow, log = ctx.workflow, ctx.log
    svc._patch_workflow_sam_loader(workflow)

    if '60' in workflow and not svc.sam_face_stack_ready():
        svc._strip_face_detailer(workflow)
        log('ComfyGen: FaceDetailer/SAM stack unavailable — detailer passes disabled')
    elif '60' in workflow:
        _fd_allowed = True
        if ctx.enable_face_detailer is False:
            _fd_allowed = False
        elif ctx.enable_face_detailer is None and ctx.shot_type:
            if svc._bible:
                _fd_allowed = svc._bible.storyteller_face_detail_enabled(
                    ctx.shot_type,
                    ctx.scene_emotion or '',
                )
            else:
                _st = ctx.shot_type.lower()
                _fd_allowed = 'close' in _st and 'wide' not in _st
        if not _fd_allowed:
            svc._strip_face_detailer(workflow)
            log('ComfyGen: FaceDetailer skipped (shot type / storyteller policy)')
        else:
            log('ComfyGen: FaceDetailer second pass enabled')
        if '63' in workflow:
            _use_hand_fixer = svc.hand_fixer_enabled() and svc.hand_fixer_stack_ready()
            if _use_hand_fixer:
                svc._strip_hand_detailer(workflow)
                log('ComfyGen: HandFixer post-pass enabled (Qwen InstantX inpaint primary, flux legacy gated)')
            elif not svc.hand_detailer_stack_ready():
                svc.ensure_hand_yolo_weights(log)
                if svc.hand_detailer_stack_ready():
                    log('ComfyGen: HandDetailer second pass enabled (hand_yolov8s + SAM)')
                else:
                    svc._strip_hand_detailer(workflow)
                    log('ComfyGen: HandDetailer unavailable — face-only second pass')
            else:
                log('ComfyGen: HandDetailer second pass enabled (hand_yolov8s + SAM)')


def apply_prompt_and_sampler(ctx: StillRenderCtx) -> None:
    """Write the prompt/latent nodes and the generic sampler patch."""
    svc = _svc()
    workflow, overrides, _set = ctx.workflow, ctx.overrides, ctx.set_node
    mf, cfg, is_schnell = ctx.mf, ctx.cfg, ctx.is_schnell

    _flux_g = float(ctx.flux_guidance if ctx.flux_guidance is not None else (cfg if not is_schnell else 1.0))
    if svc._workflow_uses_flux_clip_encode(workflow):
        clip_pos, t5_pos = svc._split_flux_dual_prompt(ctx.full_prompt)
        clip_neg, t5_neg = svc._split_flux_dual_prompt(ctx.full_negative)
        _set('20', {'clip_l': clip_pos, 't5xxl': t5_pos, 'guidance': _flux_g})
        _set('21', {'clip_l': clip_neg, 't5xxl': t5_neg, 'guidance': _flux_g})
    else:
        _set('20', {'text': ctx.full_prompt})
        _set('21', {'text': ctx.full_negative})
    _set('30', {'width': ctx.width, 'height': ctx.height, 'batch_size': 1})
    # flux via plain KSampler must run real CFG 1.0 — guidance already lives in
    # FluxGuidance/CLIPTextEncodeFlux. Real CFG 3.5 stacked on FluxGuidance 3.5
    # (double guidance) defocus-collapsed every 1280×720 flux_character_locked
    # render of runs a6f458bc + dd36662e (6/6 seeds → gradient blobs, sharp=0.0).
    # The FaceDetailer patch below has enforced this same rule since 2026-07-09;
    # the base sampler was the last flux path still stacking both.
    # XlabsSampler graphs keep cfg: true_gs is their single guidance mechanism.
    if mf == 'flux' and (workflow.get('31') or {}).get('class_type') == 'KSampler':
        _sampler_cfg = 1.0
    elif mf == 'klein':
        # klein carries no FluxGuidance node, so CFGGuider IS the single
        # guidance mechanism — real CFG here is correct, not double guidance.
        _sampler_cfg = 1.0 if svc.klein_is_distilled(ctx.unet) else cfg
    else:
        _sampler_cfg = 1.0 if (mf == 'flux' and is_schnell) else cfg
    svc._patch_flux_sampler(
        workflow,
        overrides,
        seed=ctx.seed,
        steps=ctx.steps,
        cfg=_sampler_cfg,
        is_schnell=is_schnell,
        cfg_start_frac=ctx.cfg_start_frac,
    )
    # The *_medusa_base graphs are excluded: their node 13 sits AFTER the base
    # LoRA at node 14, and this bypass rewires 13's consumers to the hardcoded
    # raw loaders (10/11) — which silently skips node 14 and renders stock
    # (measured 2026-09-18: 0.00/255 pixel diff with the adapter "on"). Those
    # graphs zero node 13 instead, so it passes node 14 straight through.
    if (
        not ctx.lora_name
        and ctx.workflow_name != 'flux_txt2img_style'
        and not (ctx.workflow_name or '').endswith('_medusa_base')
    ):
        svc._flux_rewire_without_lora(workflow)


def apply_model_nodes(ctx: StillRenderCtx) -> str | None:
    """Patch the guidance node and the per-family loader at node 10.

    Returns a refusal label when a required checkpoint is missing, else None.
    """
    svc = _svc()
    workflow, overrides, _set, log = ctx.workflow, ctx.overrides, ctx.set_node, ctx.log
    mf, cfg = ctx.mf, ctx.cfg

    if '25' in workflow:
        _g = ctx.flux_guidance if ctx.flux_guidance is not None else (cfg if not ctx.is_schnell else 1.0)
        overrides['25'] = {'guidance': _g}
    if mf == 'flux':
        _set('10', {'unet_name': ctx.unet})
    elif mf == 'qwen':
        if not ctx.unet:
            log('ComfyGen: qwen family selected but no 2512 checkpoint found')
            return 'qwen_missing_checkpoint'
        _set('10', {'unet_name': ctx.unet})
    elif mf == 'klein' and svc._graph_is_klein(workflow):
        _missing = svc.klein_missing_parts()
        if _missing:
            log('ComfyGen: klein family selected but missing ' + ', '.join(_missing))
            return 'klein_missing_checkpoint'
        _set('10', {'unet_name': ctx.unet})
        # klein pins its own encoder/VAE rather than inheriting the graph
        # defaults, so an env override actually reaches the render.
        _set('11', {'clip_name': svc.klein_text_encoder(), 'type': 'flux2'})
        _set('12', {'vae_name': svc.klein_vae()})
        # Flux2Scheduler derives its sigma schedule from the SEQUENCE LENGTH,
        # i.e. from width*height — so a resize has to reach node 33 as well as
        # the latent at node 30. Patching only the latent leaves the schedule
        # computed for 1024x1024 whatever size is actually rendered.
        #
        # MERGE, do not _set: _patch_flux_sampler already wrote {'steps': ...}
        # into overrides['33'] above, and _set replaces the whole dict. A plain
        # _set here would silently drop the step count and every klein render
        # would come back at the graph's baked-in 20 — a change that produces a
        # perfectly good image at the wrong settings, which is the hardest kind
        # of wrong to notice.
        if '33' in workflow:
            _sched_over = dict(overrides.get('33') or {})
            _sched_over.update({'width': ctx.width, 'height': ctx.height})
            overrides['33'] = _sched_over
    else:
        # SDXL workflows use checkpoint loader at node 10.
        _ckpt = svc._resolve_checkpoint_sdxl(ctx.character_package)
        # If the SDXL checkpoint isn't present, do NOT break the run — let the
        # caller fall back to diffusers/FLUX.
        try:
            _ckpt_path = os.path.join(svc._COMFY_ROOT, 'models', 'checkpoints', _ckpt)
            if not os.path.isfile(_ckpt_path):
                log(f'ComfyGen: SDXL checkpoint missing: {_ckpt} — fallback')
                return 'sdxl_missing_checkpoint'
        except Exception as _exc:
            # Best-effort check only; if the client can't check, proceed.
            _zyg_log.debug('SDXL checkpoint pre-check skipped: %s: %s', type(_exc).__name__, _exc)
        _set('10', {'ckpt_name': _ckpt})
    return None


def apply_face_detailer_patch(ctx: StillRenderCtx) -> None:
    """FaceDetailer second-pass tuning if the workflow has it (node id 60)."""
    svc = _svc()
    workflow, _set = ctx.workflow, ctx.set_node
    cond_pkg = ctx.cond_pkg
    if not ('60' in workflow and cond_pkg.get('face_detail_pass', True)):
        return
    mf, cfg, steps, seed = ctx.mf, ctx.cfg, ctx.steps, ctx.seed
    character_package = ctx.character_package
    _pore_pass = bool(cond_pkg.get('skin_pore_pass'))
    _fd_denoise = float(cond_pkg.get('face_detail_strength', svc._PREVIEW_FACE_PORE_DENOISE if _pore_pass else 0.42))
    if ctx.studio_preview and not _pore_pass:
        _fd_denoise = min(_fd_denoise, 0.38)
    _smile_req = bool(cond_pkg.get('smile_requested') or cond_pkg.get('smile_locked'))
    _emo = (ctx.scene_emotion or '').lower()
    _sp = (ctx.scene_prompt or '').lower()
    if _emo in ('sad', 'tense', 'mysterious') or 'fading' in _sp or 'no smile' in _sp:
        _smile_req = False
    if _smile_req and svc._bible and not cond_pkg.get('face_detail_wildcard'):
        try:
            cond_pkg = dict(cond_pkg)
            ctx.cond_pkg = cond_pkg
            cond_pkg['face_detail_wildcard'] = svc._bible.face_detail_wildcard_for_params(
                {
                    'default_expression': (
                        (character_package.get('style_profile') or {}).get('default_expression')
                        or ((character_package.get('default_presentation') or {}).get('default_expression'))
                    ),
                    'smile_requested': True,
                },
            )
        except Exception as _exc:
            _zyg_log.warning(
                'smile face-detail wildcard lookup failed, continuing with the workflow default: %s',
                _exc,
            )
    if _pore_pass and mf == 'flux':
        # >0.35 re-synthesizes the face crop with FLUX's smooth-skin prior
        # and erases the base pass's texture — the 2026-07-09 audit traced
        # the anchor's melted-jaw/forehead-patch artifacts to this pass.
        # flux-only: SDXL's detailer repairs small mangled faces and needs
        # its full calibrated denoise.
        _fd_denoise = min(
            _fd_denoise,
            float(os.environ.get('ZYG_FD_PORE_DENOISE_CAP', '0.30')),
        )
    _fd_patch: dict[str, Any] = {
        'guide_size': 384,
        'guide_size_for': True,
        'max_size': 768,
        'seed': seed + 1,
        'steps': int(max(10, steps // 2)),
        # flux-dev must run its internal KSampler at real CFG 1.0 (guidance
        # is already baked into the FluxGuidance conditioning the detailer
        # receives). float(cfg) here stacked real CFG 4.5 on top of
        # FluxGuidance 4.5 — double guidance, the burned/waxy "flux face".
        'cfg': 1.0 if mf == 'flux' else float(cfg),
        'denoise': _fd_denoise,
    }
    if _pore_pass or _smile_req:
        _fd_patch['wildcard'] = cond_pkg.get('face_detail_wildcard') or (
            svc._SKIN_PORE_FACE_WILDCARD + (f', {svc._SMILE_FACE_WILDCARD}' if _smile_req else '')
        )
        if _pore_pass:
            _fd_patch['guide_size'] = 512
            _fd_patch['max_size'] = 1024
        elif _smile_req:
            _fd_patch['guide_size'] = 448
            _fd_patch['max_size'] = 896
            _fd_denoise = min(_fd_denoise, 0.44)
            _fd_patch['denoise'] = _fd_denoise
    if mf == 'sdxl':
        _fd_patch['sampler_name'] = 'dpmpp_2m'
        _fd_patch['scheduler'] = 'karras'
    _set('60', _fd_patch)


def apply_hand_detailer_patch(ctx: StillRenderCtx) -> None:
    """HandDetailer second-pass tuning if the workflow has it (node id 63)."""
    svc = _svc()
    cond_pkg = ctx.cond_pkg
    if not ('63' in ctx.workflow and cond_pkg.get('hand_detail_pass', True)):
        return
    _hd_denoise = float(cond_pkg.get('hand_detail_strength', 0.40))
    if ctx.studio_preview:
        _hd_denoise = max(0.36, min(0.45, _hd_denoise))
    _hd_patch: dict[str, Any] = {
        'guide_size': 320,
        'guide_size_for': True,
        'max_size': 640,
        'seed': ctx.seed + 2,
        'steps': int(max(12, ctx.steps // 2)),
        # Same flux double-guidance rule as the FaceDetailer patch above.
        'cfg': 1.0 if ctx.mf == 'flux' else float(ctx.cfg),
        'denoise': _hd_denoise,
        'bbox_threshold': 0.45,
        'bbox_dilation': 8,
        'bbox_crop_factor': 2.5,
        'wildcard': cond_pkg.get('hand_detail_wildcard') or svc._HAND_DETAIL_WILDCARD,
    }
    if ctx.mf == 'sdxl':
        _hd_patch['sampler_name'] = 'dpmpp_2m'
        _hd_patch['scheduler'] = 'karras'
    else:
        _hd_patch['sampler_name'] = 'euler'
        _hd_patch['scheduler'] = 'simple'
    ctx.set_node('63', _hd_patch)
