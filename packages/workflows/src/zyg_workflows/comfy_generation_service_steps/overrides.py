# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from .preflight import StillRenderCtx, _svc, os

import logging

# Re-created by assignment rather than imported from the sibling module: getLogger
# returns the one singleton the original module held, and an assigned global keeps the
# method-call bytecode of every `_zyg_log.debug(...)` below unchanged.
_zyg_log = logging.getLogger('zyg_workflows.comfy_generation_service_steps')
# --------------------------------------------------------------------------- #
# Per-workflow overrides
# --------------------------------------------------------------------------- #


def _set_node13_lora(ctx: StillRenderCtx, lora_name: str, scale: float) -> None:
    ctx.set_node(
        '13',
        {
            'lora_name': lora_name,
            'strength_model': scale,
            'strength_clip': scale,
        },
    )


def _cond_scale(ctx: StillRenderCtx, default: float) -> float:
    return float((ctx.character_package or {}).get('conditioning', {}).get('lora_scale', default))


def apply_workflow_overrides(ctx: StillRenderCtx) -> str | None:
    """The per-graph override chain — ORDER IS SEMANTICS.

    This is the same if/elif ladder ``generate_still`` carried inline: a branch
    that matches excludes every branch below it, which is why several branches
    set node 13 themselves instead of falling through to the generic LoRA
    patches near the end. Returns a refusal label or None.
    """
    svc = _svc()
    workflow, overrides = ctx.workflow, ctx.overrides
    workflow_name, lora_name = ctx.workflow_name, ctx.lora_name

    if workflow_name == 'flux_img2img':
        return _branch_flux_img2img(ctx)

    elif workflow_name == 'flux_character_ipadapter':
        return _branch_flux_character_ipadapter(ctx)

    elif workflow_name == 'flux_pulid_cell':
        return _branch_flux_pulid_cell(ctx)

    elif workflow_name == 'klein_refcontrol':
        return _branch_klein_refcontrol(ctx)

    elif workflow_name in ('klein_edit_angle', 'klein_pose_i2i'):
        return _branch_klein_edit(ctx)

    elif workflow_name == 'qwen_edit_angle':
        return _branch_qwen_edit_angle(ctx)

    elif workflow_name == 'flux_pose_ipa_cell':
        return _branch_flux_pose_ipa_cell(ctx)

    elif workflow_name == 'flux_pose_instantid_cell':
        return _branch_flux_pose_instantid_cell(ctx)

    elif workflow_name == 'flux_pose_ipa_i2i_cell':
        return _branch_flux_pose_ipa_i2i_cell(ctx)

    elif lora_name and workflow_name == 'flux_character_locked' and '13' in workflow:
        _set_node13_lora(ctx, lora_name, _cond_scale(ctx, 0.85))

    elif ctx.style_lora_name and workflow_name == 'flux_txt2img_style' and '13' in workflow:
        _set_node13_lora(ctx, ctx.style_lora_name, float(ctx.style_lora_scale))

    elif lora_name and workflow_name == 'sdxl_character_locked' and '13' in workflow:
        _set_node13_lora(ctx, lora_name, _cond_scale(ctx, 0.85))
        overrides.setdefault('31', {})['denoise'] = 1.0

    elif lora_name and workflow_name == 'qwen_character_locked' and '13' in workflow:
        _set_node13_lora(ctx, lora_name, _cond_scale(ctx, svc.default_lora_scale(lora_name)))

    # 'klein_edit_angle' and 'klein_refcontrol' are NOT in this tuple: both match earlier
    # in this same if/elif chain and set node 13 themselves. Naming them here too read
    # like live routing for a branch that can never be reached from them.
    elif lora_name and workflow_name == 'klein_character_locked' and '13' in workflow:
        _set_node13_lora(ctx, lora_name, _cond_scale(ctx, svc.default_lora_scale(lora_name)))

    elif workflow_name.endswith('_medusa_base') and '14' in workflow:
        return _branch_medusa_base(ctx)

    elif workflow_name == 'flux_character_instantid':
        return _branch_flux_character_instantid(ctx)

    elif workflow_name == 'sdxl_character_instantid':
        ref_path = ctx.reference_image or ctx.init_image
        if ref_path:
            ctx.set_node('15', {'image': ctx.comfy.stage_input_image(ref_path)})
        cond_ii = (ctx.character_package or {}).get('conditioning', {}) or {}
        ctx.set_node('17', {'weight': float(cond_ii.get('instantid_weight', 0.85)), 'start_at': 0.0, 'end_at': 1.0})
        _iid_file = ctx.comfy.resolve_instantid_model_file('ip-adapter.bin')
        if _iid_file:
            ctx.set_node('14', {'instantid_file': _iid_file})

    elif workflow_name == 'sdxl_img2img':
        ref_path = ctx.reference_image or ctx.init_image
        if ref_path:
            ctx.set_node('14', {'image': ctx.comfy.stage_input_image(ref_path)})
        if ctx.denoise is not None:
            overrides.setdefault('31', {})['denoise'] = float(ctx.denoise)
        elif ref_path:
            overrides.setdefault('31', {})['denoise'] = svc._SDXL_IMG2IMG_DENOISE

    return None


def _branch_flux_img2img(ctx: StillRenderCtx) -> None:
    # img2img has LoadImage(14) → VAEEncode(15) → KSampler(31); no node 30 —
    # so the width/height override above is a silent no-op and the OUTPUT
    # inherits the init's pixel size (run dd36662e: all 24 i2i scenes
    # rendered 512×512 while the log claimed 1280×720, then were
    # anamorphically stretched to the 720p canvas). Stage a cover-cropped
    # resize of the init at the requested resolution so the VAE-encoded
    # latent — and therefore the render — matches the request.
    svc = _svc()
    ref_path = ctx.init_image or ctx.reference_image
    if ref_path and os.path.isfile(ref_path):
        ref_name = ctx.comfy.stage_input_image(svc._resize_init_for_latent(ref_path, int(ctx.width), int(ctx.height)))
        ctx.set_node('14', {'image': ref_name})
    if ctx.denoise is not None:
        ctx.overrides.setdefault('31', {})['denoise'] = float(ctx.denoise)
    elif ref_path and os.path.isfile(ref_path):
        ctx.overrides.setdefault('31', {})['denoise'] = 0.65
    # 2026-07-24 fix: inject the character LoRA (graph gained optional node 13 —
    # previously every init-image scene rendered with NO identity lock)
    if ctx.lora_name and '13' in ctx.workflow:
        _set_node13_lora(ctx, ctx.lora_name, _cond_scale(ctx, 0.85))
    return None


def _branch_flux_character_ipadapter(ctx: StillRenderCtx) -> None:
    svc = _svc()
    ip_scale = float(
        (ctx.character_package or {}).get('conditioning', {}).get('ipadapter_scale', svc._IPA_SCALE_DEFAULT)
    )
    ref_path = ctx.reference_image or ctx.init_image
    if ref_path:
        ctx.set_node('15', {'image': ctx.comfy.stage_input_image(ref_path)})
    # Do not override LoadFluxIPAdapter (node 14) — use clip-vit-large-patch14-ipa in JSON.
    ctx.set_node('16', {'ip_scale': ip_scale})
    if ctx.lora_name and '13' in ctx.workflow:
        _set_node13_lora(ctx, ctx.lora_name, _cond_scale(ctx, 0.85))
    return None


def _branch_flux_pulid_cell(ctx: StillRenderCtx) -> None:
    # PuLID-FLUX identity lock: face-ID embedding patched into the model.
    ref_path = ctx.reference_image or ctx.init_image
    if ref_path:
        ctx.set_node('15', {'image': ctx.comfy.stage_input_image(ref_path)})
    _cond_pl = (ctx.character_package or {}).get('conditioning', {}) or {}
    ctx.set_node(
        '16',
        {
            'weight': float(_cond_pl.get('pulid_weight', 0.95)),
            'start_at': float(_cond_pl.get('pulid_start_at', 0.1)),
        },
    )
    # flux-dev via plain KSampler: real CFG must stay 1.0 (guidance lives in
    # CLIPTextEncodeFlux); replace the generic sampler patch entirely.
    ctx.set_node('31', {'seed': ctx.seed, 'steps': ctx.steps, 'cfg': 1.0})
    if ctx.lora_name and '13' in ctx.workflow:
        _set_node13_lora(ctx, ctx.lora_name, float(_cond_pl.get('lora_scale', 0.85)))
    return None


def _branch_klein_refcontrol(ctx: StillRenderCtx) -> str | None:
    # TWO reference images, and the ORDER IS THE MEANING. FLUX.2 concatenates every
    # chained ReferenceLatent as extra tokens with an incrementing positional index,
    # so chain position IS "image 1" vs "image 2" — RefControl was trained with the
    # depth map first and the appearance reference second, and swapping them asks the
    # adapter to take its geometry from a photograph.
    svc = _svc()
    log, _set = ctx.log, ctx.set_node
    _depth = ctx.pose_image
    _ref = ctx.reference_image or ctx.init_image
    if not (_depth and os.path.isfile(_depth)):
        log('ComfyGen: klein_refcontrol selected with no readable control image')
        return 'klein_refcontrol_no_control'
    if not (_ref and os.path.isfile(_ref)):
        log('ComfyGen: klein_refcontrol needs an appearance reference as image 2')
        return 'klein_refcontrol_no_reference'
    # Chain order is the image index, and which index RefControl wants is a claim
    # about someone else's training run — so it is a flag that can be MEASURED, not a
    # constant to be believed. Default follows the model card ("first image as depth
    # reference, second image input"); ZYG_KLEIN_REFCONTROL_ORDER=ref_first swaps it.
    _order = os.environ.get('ZYG_KLEIN_REFCONTROL_ORDER', 'depth_first').strip()
    _img1, _img2 = (_ref, _depth) if _order == 'ref_first' else (_depth, _ref)
    _set('22', {'image': ctx.comfy.stage_input_image(_img1)})
    _set('42', {'image': ctx.comfy.stage_input_image(_img2)})
    # resolution_steps is REQUIRED by this ComfyUI's ImageScaleToTotalPixels and is
    # absent from UI exports — without it the graph fails validation with "Required
    # input is missing", which reads like a broken link rather than signature drift.
    _mp = max(0.25, min(2.0, (ctx.width * ctx.height) / 1_048_576.0))
    _set('23', {'megapixels': _mp, 'resolution_steps': 1})
    _set('43', {'megapixels': _mp, 'resolution_steps': 1})
    _ctrl_lora = svc.klein_control_lora_name()
    if not _ctrl_lora:
        log('ComfyGen: klein_refcontrol selected but the control adapter is missing')
        return 'klein_control_lora_missing'
    _set('14', {'lora_name': _ctrl_lora, 'strength_model': svc.klein_control_lora_scale(_ctrl_lora)})
    # The adapter has a TRIGGER WORD, and the generic prompt write further up has
    # already queued the caller's text for node 20. Without the trigger the LoRA
    # loads and does nothing recognisable — which looks exactly like "the control
    # image was ignored" and gets debugged in the wrong place.
    #
    # READ THE OVERRIDE, NOT THE TEMPLATE. _set() records into `overrides`; it does
    # not mutate `workflow`. Reading workflow['20'] here returns the template's own
    # text, which is the literal string 'refcontrol' — so the guard would always see
    # the trigger already present and never prepend it to the REAL prompt. Measured:
    # every render in the first RefControl matrix went out untriggered.
    _pos = (ctx.overrides.get('20') or {}).get('text')
    if _pos is None:
        _pos = ((ctx.workflow.get('20') or {}).get('inputs') or {}).get('text') or ''
    if 'refcontrol' not in _pos.lower():
        _set('20', {'text': ('refcontrol, ' + _pos) if _pos.strip() else 'refcontrol'})
    # The identity LoRA sits FIRST (node 13) so the control adapter is applied on top
    # — the same ordering arcane_restyle uses for style-then-character on SDXL. When
    # nothing is staged, _flux_rewire_without_lora deletes 13 and rewires node 14's
    # model input to the raw UNET; it is generic over node ids, so that already works.
    if ctx.lora_name and '13' in ctx.workflow:
        _set_node13_lora(ctx, ctx.lora_name, _cond_scale(ctx, svc.default_lora_scale(ctx.lora_name)))
    return None


def _branch_klein_edit(ctx: StillRenderCtx) -> str | None:
    # 2026-08-26. The graph was reachable from _pick_workflow but NOTHING ever
    # populated its LoadImage, so every klein edit failed validation with
    # "node 22 [LoadImage]: Custom validation failed" — the node still held
    # the template's placeholder `init.png`, which is not in Comfy's input
    # dir. Staging the image is what makes the whole path work.
    svc = _svc()
    _set = ctx.set_node
    ref_path = ctx.init_image or ctx.reference_image
    if ref_path and os.path.isfile(ref_path):
        _set('22', {'image': ctx.comfy.stage_input_image(ref_path)})
    else:
        ctx.log('ComfyGen: klein_edit_angle selected with no readable init image')
        return 'klein_edit_no_init'
    # ReferenceLatent works at the model's ~1MP budget; node 23 rescales the
    # source to it. Keep it in step with the requested render size so the
    # conditioning latent and the output latent describe the same framing.
    # `resolution_steps` is REQUIRED by this ComfyUI's ImageScaleToTotalPixels
    # and absent from the stored template — without it the graph fails
    # validation with "node 23: Required input is missing", which reads like a
    # broken link rather than node-signature drift.
    _set(
        '23',
        {'megapixels': max(0.25, min(2.0, (ctx.width * ctx.height) / 1_048_576.0)), 'resolution_steps': 1},
    )
    # klein_pose_i2i samples FROM the init latent down a truncated sigma tail,
    # which is what actually LOCKS the pose. klein_edit_angle only offers the
    # init as ReferenceLatent conditioning off an EMPTY latent, so the sampler
    # starts from noise and the geometry is a suggestion: measured 2026-08-26,
    # a true top-down mesh render came back as a three-quarter front view.
    # Lower denoise = more faithful to the mesh, less room for the LoRA's look.
    if ctx.workflow_name == 'klein_pose_i2i' and '36' in ctx.workflow:
        _dn = float(os.environ.get('ZYG_KLEIN_POSE_DENOISE', '0.62'))
        _set('36', {'denoise': max(0.20, min(0.95, _dn))})
    # The LoRA patch further down this SAME if/elif chain can never be reached
    # once this branch matches, so node 13 is set here or it keeps the
    # template placeholder and Comfy rejects it with "Value not in list".
    if ctx.lora_name and '13' in ctx.workflow:
        _set_node13_lora(ctx, ctx.lora_name, _cond_scale(ctx, svc.default_lora_scale(ctx.lora_name)))
    return None


def _branch_qwen_edit_angle(ctx: StillRenderCtx) -> None:
    # Qwen-Image-Edit camera-rotation from an anchor image. The graph is
    # fully Qwen — replace every flux-generic patch that touched it.
    # Output size comes from node 30 (EmptySD3LatentImage, patched by the
    # generic size pass); the anchor stays unstretched into image1.
    svc = _svc()
    workflow, _set, log, comfy = ctx.workflow, ctx.set_node, ctx.log, ctx.comfy
    _qwen_control_on = False
    ref_path = ctx.reference_image or ctx.init_image
    if ref_path:
        _set('15', {'image': comfy.stage_input_image(ref_path)})
    # GEOMETRIC CONTROL, 2026-08-26. TextEncodeQwenImageEditPlus declares image1,
    # image2 and image3 as optional inputs and the repo had only ever used image1 —
    # so a depth map is a WIRING change, not a missing capability. Qwen-Image-Edit
    # 2509 added native support for reading a control image (depth / edge / keypoint)
    # as structure, which is the only geometric-control route open to this family:
    # QwenImageDiffsynthControlnet needs a MODEL_PATCH and models/model_patches/ holds
    # nothing but its placeholder.
    #
    # image1 stays the APPEARANCE anchor and image2 carries the geometry, matching
    # the order the klein RefControl path uses, so the two families do not disagree
    # about which slot means what.
    if ctx.pose_image and os.path.isfile(ctx.pose_image) and '16' not in workflow:
        workflow['16'] = {
            'inputs': {'image': comfy.stage_input_image(ctx.pose_image)},
            'class_type': 'LoadImage',
            '_meta': {'title': 'control image (depth) — service-injected'},
        }
        for _nid in ('20', '21'):
            if _nid in workflow:
                workflow[_nid]['inputs']['image2'] = ['16', 0]
        _qwen_control_on = True
        log(f'ComfyGen: qwen edit conditioned on a control image via image2 ({os.path.basename(ctx.pose_image)})')
    _set('10', {'unet_name': svc.qwen_edit_unet() or 'qwen_image_edit_2509_fp8_e4m3fn.safetensors'})
    # Angles LoRA at 0.9 (fal model-card guidance: 0.8-1.0, start at 0.9) —
    # the stock graph's 1.0 maximizes pose compliance but also maximizes
    # source-leakage ghosting pressure (2026-07-16 research).
    if workflow.get('14', {}).get('class_type') == 'LoraLoaderModelOnly':
        # Edit-2511 switch: only override the graph's flat 2509 default when
        # ZYG_QWEN_EDIT_ANGLES_LORA is set, so unset keeps the stock graph.
        if os.environ.get('ZYG_QWEN_EDIT_ANGLES_LORA', '').strip():
            workflow['14']['inputs']['lora_name'] = svc.qwen_edit_angles_lora_name()
        # The angles LoRA rotates the CAMERA. When a depth map is already dictating
        # the geometry the two conditioning signals fight, so the control path gets
        # its own default of 0.0 — the same value wardrobe_service,
        # asset_library_service and storyteller_scene_service pass for the same
        # reason. This assignment must stay HERE and not in the injection block
        # above: it runs later in the branch and would otherwise clobber it back
        # to 0.9.
        workflow['14']['inputs']['strength_model'] = float(
            os.environ.get('ZYG_QWEN_EDIT_ANGLES_LORA_SCALE_CONTROL', '0.0')
            if _qwen_control_on
            else os.environ.get('ZYG_QWEN_EDIT_ANGLES_LORA_SCALE', '0.9')
        )
    # 1500-char clause-boundary cap (was a blind [:800] that chopped the
    # anti-airbrush texture tail off every full-body/T-pose instruction).
    _qwen_pos = svc._trim_prompt_at_clause(ctx.scene_prompt or ctx.full_prompt or '', 1500)
    # Optional qwen-edit-skin texture LoRA (tlennon-ie/qwen-edit-skin,
    # trained on 2509 to reverse Qwen's plastic-skin prior). Injected
    # between the angles LoRA (14) and ModelSamplingAuraFlow (19) only when
    # the file exists, so the stock graph keeps working without it.
    # Photoreal characters only — animated/painterly sheets must keep their
    # cel-shading, and this LoRA (plus its trigger phrase) fights that.
    _qwen_render_st = svc._render_style_from_package(ctx.character_package)
    _skin_lora_style_ok = (not _qwen_render_st) or svc._is_photoreal_render_style(_qwen_render_st)
    _skin_lora_name = os.environ.get('ZYG_QWEN_EDIT_SKIN_LORA', 'qwen_edit_skin.safetensors').strip()
    _skin_lora_path = os.path.join(svc._COMFY_LORA_DIR, _skin_lora_name) if _skin_lora_name else ''
    if (
        _skin_lora_style_ok
        and _skin_lora_name
        and os.path.isfile(_skin_lora_path)
        and '14' in workflow
        and '19' in workflow
        and '18' not in workflow
    ):
        workflow['18'] = {
            'inputs': {
                'lora_name': _skin_lora_name,
                'strength_model': float(os.environ.get('ZYG_QWEN_EDIT_SKIN_LORA_SCALE', '1.0')),
                'model': ['14', 0],
            },
            'class_type': 'LoraLoaderModelOnly',
            '_meta': {'title': 'qwen-edit-skin texture LoRA (service-injected)'},
        }
        workflow['19']['inputs']['model'] = ['18', 0]
        # The LoRA's trigger phrase (exact model-card wording); appended
        # after the cap so it never truncates.
        _qwen_pos = f'{_qwen_pos}, make the subjects skin details more prominent and natural'
    _set('20', {'prompt': _qwen_pos})
    # Merge the character's full negative (skin-tone defence, anti-stylization,
    # etc.) with Qwen's waxy-skin term so dark-skin negatives reach cells 1-47.
    _qwen_base_neg = os.environ.get(
        'ZYG_QWEN_EDIT_NEGATIVE',
        'smooth plastic skin, airbrushed, retouched, wax figure, doll-like skin',
    )
    # P-06: dedupe the concat too — the waxy-skin terms overlap the
    # photoreal negatives already in full_negative.
    _set(
        '21',
        {
            'prompt': svc._dedupe_negative_clauses(
                f'{ctx.full_negative}, {_qwen_base_neg}' if ctx.full_negative else _qwen_base_neg
            )
        },
    )
    # 36 steps / true CFG 4.0 (official 2509 recipe: true_cfg 4.0, 40 steps).
    # The old 20/2.5 was the smoothness floor of every waxy cell; there is
    # no Lightning LoRA in this graph, so full-step sampling is safe.
    _set(
        '31',
        {
            'seed': ctx.seed,
            'steps': int(os.environ.get('ZYG_QWEN_EDIT_STEPS', '36')),
            'cfg': float(os.environ.get('ZYG_QWEN_EDIT_CFG', '4.0')),
        },
    )
    return None


def _branch_flux_pose_ipa_cell(ctx: StillRenderCtx) -> None:
    svc = _svc()
    _set = ctx.set_node
    ip_scale = float(
        (ctx.character_package or {})
        .get('conditioning', {})
        .get(
            'ipadapter_scale',
            os.environ.get('ZYG_CONTACT_SHEET_SHEET_B_IPA_SCALE', str(svc._IPA_SCALE_DEFAULT)),
        )
    )
    ref_path = ctx.reference_image or ctx.init_image
    pose_path = ctx.pose_image or (ctx.character_package or {}).get('_pose_image_path')
    if ref_path and os.path.isfile(ref_path):
        _set('15', {'image': ctx.comfy.stage_input_image(ref_path)})
    if pose_path and os.path.isfile(pose_path) and '19' in ctx.workflow:
        _set('19', {'image': ctx.comfy.stage_input_image(pose_path)})
    _set('16', {'ip_scale': ip_scale})
    # Pose-locked contact sheets need the pose to stay active late.
    cn_strength = float(os.environ.get('ZYG_CONTACT_SHEET_POSE_CN_STRENGTH', '0.95'))
    cn_end = float(os.environ.get('ZYG_CONTACT_SHEET_POSE_CN_END', '0.90'))
    try:
        from zyg_workflows import character_bible_service as _cbs_cn

        _sch_cn = _cbs_cn.scholarly_controlnet_scale(ctx.character_package)
        cn_strength = float(_sch_cn)
        cn_end = min(0.92, cn_strength + 0.10)
    except Exception as _exc:
        _zyg_log.warning(
            'scholarly controlnet scale lookup failed, continuing with the ZYG_CONTACT_SHEET_POSE_CN_* defaults: %s',
            _exc,
        )
    _set('22', {'strength': cn_strength, 'end_percent': cn_end})
    if ctx.lora_name and '13' in ctx.workflow:
        _set_node13_lora(ctx, ctx.lora_name, _cond_scale(ctx, 0.85))
        _set('16', {'model': ['13', 0]})
        _set('20', {'clip': ['13', 1]})
        _set('21', {'clip': ['13', 1]})
    return None


def _branch_flux_pose_instantid_cell(ctx: StillRenderCtx) -> None:
    # Pose + InstantID (strong face identity lock) — used by pose-locked contact sheets.
    _set = ctx.set_node
    ref_path = ctx.reference_image or ctx.init_image
    pose_path = ctx.pose_image or (ctx.character_package or {}).get('_pose_image_path')
    if ref_path and os.path.isfile(ref_path):
        _set('15', {'image': ctx.comfy.stage_input_image(ref_path)})
    if pose_path and os.path.isfile(pose_path) and '19' in ctx.workflow:
        _set('19', {'image': ctx.comfy.stage_input_image(pose_path)})
    cond_ii = (ctx.character_package or {}).get('conditioning', {}) or {}
    _set(
        '17',
        {
            'weight': float(cond_ii.get('instantid_weight', 0.92)),
            'start_at': 0.0,
            'end_at': 1.0,
        },
    )
    _iid_file = ctx.comfy.resolve_instantid_model_file('instantid_sdxl.safetensors')
    if _iid_file:
        _set('14', {'instantid_file': _iid_file})
    cn_strength = float(os.environ.get('ZYG_CONTACT_SHEET_POSE_CN_STRENGTH', '0.95'))
    cn_end = float(os.environ.get('ZYG_CONTACT_SHEET_POSE_CN_END', '0.95'))
    _set('22', {'strength': cn_strength, 'end_percent': cn_end})
    if ctx.lora_name and '13' in ctx.workflow:
        _set_node13_lora(ctx, ctx.lora_name, float(cond_ii.get('lora_scale', 0.70)))
        _set('17', {'model': ['13', 0]})
        _set('20', {'clip': ['13', 1]})
        _set('21', {'clip': ['13', 1]})
    return None


def _branch_flux_pose_ipa_i2i_cell(ctx: StillRenderCtx) -> None:
    # Pose + IP-Adapter + img2img (init latent) for outfit/lighting consistency.
    svc = _svc()
    _set = ctx.set_node
    ip_scale = float(
        (ctx.character_package or {})
        .get('conditioning', {})
        .get(
            'ipadapter_scale',
            os.environ.get('ZYG_CONTACT_SHEET_SHEET_B_IPA_SCALE', str(svc._IPA_SCALE_DEFAULT)),
        )
    )
    ref_path = ctx.reference_image or ctx.init_image
    init_path = ctx.init_image or ctx.reference_image
    pose_path = ctx.pose_image or (ctx.character_package or {}).get('_pose_image_path')
    if init_path and os.path.isfile(init_path):
        _set('14', {'image': ctx.comfy.stage_input_image(init_path)})
    if ref_path and os.path.isfile(ref_path):
        _set('17', {'image': ctx.comfy.stage_input_image(ref_path)})
    if pose_path and os.path.isfile(pose_path) and '21' in ctx.workflow:
        _set('21', {'image': ctx.comfy.stage_input_image(pose_path)})
    _set('18', {'ip_scale': ip_scale})
    cn_strength = float(os.environ.get('ZYG_CONTACT_SHEET_POSE_CN_STRENGTH', '1.0'))
    cn_end = float(os.environ.get('ZYG_CONTACT_SHEET_POSE_CN_END', '0.98'))
    _set('24', {'strength': cn_strength, 'end_percent': cn_end})
    if ctx.denoise is not None:
        ctx.overrides.setdefault('31', {})['denoise_strength'] = float(ctx.denoise)
    return None


def _branch_medusa_base(ctx: StillRenderCtx) -> None:
    # Node 14 = the Medusa base LoRA; node 13 = the optional character LoRA
    # chained after it. Node 13 is ZEROED rather than left at the template
    # default when this render has no character: the graph ships a
    # placeholder lora_name so the raw JSON validates, and a non-zero
    # strength on it would load an unrelated adapter — the same failure the
    # *_character_locked abort guard exists to prevent, which cannot fire
    # here because this graph is not named *_character_locked.
    svc = _svc()
    ctx.set_node(
        '14',
        {
            'lora_name': ctx.medusa_base_name,
            'strength_model': ctx.medusa_base_scale,
            'strength_clip': ctx.medusa_base_scale,
        },
    )
    if ctx.lora_name:
        _set_node13_lora(ctx, ctx.lora_name, _cond_scale(ctx, svc.default_lora_scale(ctx.lora_name)))
    else:
        # lora_name is repointed at the base adapter we JUST staged, not
        # left on the template placeholder: ComfyUI validates that the file
        # exists even at strength 0, and klein's placeholder
        # (zygchar_PLACEHOLDER_klein) is not on disk. Strength 0 keeps it a
        # no-op, so the base adapter is not applied twice.
        ctx.set_node('13', {'lora_name': ctx.medusa_base_name, 'strength_model': 0.0, 'strength_clip': 0.0})
    return None


def _branch_flux_character_instantid(ctx: StillRenderCtx) -> None:
    # Stronger identity lock when InstantID / PuLID custom nodes are present.
    # Node 15 = identity reference image, node 17 = ApplyInstantID/PulID with
    # strength dial, node 13 = optional LoRA stack.
    ref_path = ctx.reference_image or ctx.init_image
    if ref_path:
        ctx.set_node('15', {'image': ctx.comfy.stage_input_image(ref_path)})
    cond_ii = (ctx.character_package or {}).get('conditioning', {}) or {}
    ctx.set_node(
        '17',
        {
            'weight': float(cond_ii.get('instantid_weight', 0.85)),
            'start_at': 0.0,
            'end_at': 1.0,
        },
    )
    if ctx.lora_name and '13' in ctx.workflow:
        _set_node13_lora(ctx, ctx.lora_name, float(cond_ii.get('lora_scale', 0.7)))
    return None
