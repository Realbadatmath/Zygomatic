# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from .preflight import Any, Callable, StillRenderCtx, _svc, os, shutil

import logging

# Re-created by assignment rather than imported from the sibling module: getLogger
# returns the one singleton the original module held, and an assigned global keeps the
# method-call bytecode of every `_zyg_log.debug(...)` below unchanged.
_zyg_log = logging.getLogger('zyg_workflows.comfy_generation_service_steps')
# --------------------------------------------------------------------------- #
# Submit, save, post-passes
# --------------------------------------------------------------------------- #


def log_submission(ctx: StillRenderCtx) -> None:
    """Log the SUBMITTED sampler values, not the local variables.

    The schnell clamp mutates locals that later branches (e.g. qwen_edit_angle)
    override, which made the run log claim "steps=4 cfg=1.0" for cells that
    actually ran 20/2.5 and sent the 2026-07-09 waxy-skin audit down a false
    trail. Same for the unet: the qwen_edit_angle branch overrides node 10 to
    the qwen model, so the old log printed 'flux1-schnell' for cells that
    actually ran on the qwen unet (2026-07-12 audit).
    """
    _sub31 = ctx.overrides.get('31', {})
    _log_steps = _sub31.get('steps', ctx.steps)
    _log_cfg = _sub31.get('cfg', _sub31.get('true_gs', ctx.cfg))
    _log_unet = ctx.overrides.get('10', {}).get('unet_name', ctx.unet) or 'default'
    ctx.log(
        f'ComfyGen: unet={_log_unet} workflow={ctx.workflow_name} '
        f'{ctx.width}×{ctx.height} steps={_log_steps} cfg={_log_cfg} '
        f'guidance={ctx.overrides.get("25", {}).get("guidance", ctx.cfg)} '
        f'seed={ctx.seed} pos="{ctx.full_prompt[:180]}…" neg="{ctx.full_negative[:120]}…"'
    )


def submit_render(
    ctx: StillRenderCtx,
    maybe_clear_vram: Callable[[str], None],
) -> tuple[list[str] | None, str | None]:
    """Submit the graph, with the XLabs poisoned-state retry.

    Returns ``(outputs, failure_label)`` — exactly one of the two is set.
    """
    svc = _svc()
    log, comfy = ctx.log, ctx.comfy
    try:
        from zyg_workflows import pipeline_control as _pc_gen

        outputs = comfy.submit(
            ctx.workflow,
            overrides=ctx.overrides,
            timeout_s=900,
            should_abort=_pc_gen.halt_requested,
        )
    except comfy.ComfyUIError as exc:
        log(f'ComfyGen: submit failed — {exc}')
        _exc_s = str(exc)
        # XLabs poisoned-state auto-recovery (2026-07-19): after an XLabs
        # IP-Adapter workflow, the FLUX attention processors can be left
        # half-patched in the ComfyUI process; the next plain XlabsSampler run
        # dies with "'DoubleStreamBlockProcessor' object has no attribute
        # 'ip_adapters'" (killed run ec827cd2 at cell 0). A full model unload
        # clears the patched state — do it and retry this submit once.
        if "no attribute 'ip_adapters'" in _exc_s or 'DoubleStreamBlockProcessor' in _exc_s:
            log('ComfyGen: XLabs processor state poisoned — unloading models and retrying once')
            try:
                import time as _time_xr

                comfy.free_vram(unload_models=True, free_memory=True)
                _time_xr.sleep(3)
                # Success falls through to the normal output handling below.
                outputs = comfy.submit(
                    ctx.workflow,
                    overrides=ctx.overrides,
                    timeout_s=900,
                    should_abort=_pc_gen.halt_requested,
                )
                log('ComfyGen: XLabs recovery retry succeeded')
            except Exception as _retry_exc:
                log(f'ComfyGen: retry after XLabs recovery failed — {_retry_exc}')
                maybe_clear_vram('post-error')
                svc._cb_record_failure(str(_retry_exc), log)
                return None, 'comfy_error'
        else:
            if 'memory' in _exc_s.lower() or 'oom' in _exc_s.lower():
                maybe_clear_vram('post-oom')
            else:
                maybe_clear_vram('post-error')
            svc._cb_record_failure(_exc_s, log)
            return None, 'comfy_error'

    if not outputs:
        log('ComfyGen: no output files')
        maybe_clear_vram('post-no-output')
        return None, 'no_output'
    svc._cb_record_success()
    return outputs, None


def save_render_output(
    ctx: StillRenderCtx,
    outputs: list[str],
    qwen_upscale_back: tuple[int, int] | None,
) -> None:
    """Copy the render to out_path and undo the qwen-edit 1MP downscale."""
    out_path, log = ctx.out_path, ctx.log
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    shutil.copy2(outputs[0], out_path)
    if qwen_upscale_back is not None:
        try:
            from PIL import Image as _PILUp

            _img_up = _PILUp.open(out_path).convert('RGB')
            if _img_up.size != qwen_upscale_back:
                _img_up.resize(qwen_upscale_back, _PILUp.LANCZOS).save(out_path, format='PNG')
                log(
                    f'ComfyGen: qwen-edit tile upscaled '
                    f'{_img_up.size[0]}×{_img_up.size[1]} → '
                    f'{qwen_upscale_back[0]}×{qwen_upscale_back[1]} (Lanczos)',
                )
        except Exception as _up_exc:
            log(f'ComfyGen: upscale-back skipped ({_up_exc})')
    log(f'ComfyGen: saved {out_path} ({ctx.workflow_name}, seed={ctx.seed})')


def apply_render_time_restyle(ctx: StillRenderCtx) -> None:
    """2026-07-27: RENDER-TIME ARCANE RESTYLE (Option 1).

    The Arcane style cannot be baked into an SDXL character LoRA (renders
    photoreal) and a style LoRA ages the subject up — so we render photoreal
    (good identity) and restyle the saved frame to Arcane via Qwen-Image-Edit,
    which preserves identity/age/pose/costume (denoise 1.0, source as
    conditioning). SDXL restyle chars only; runs BEFORE the hand-fixer (skipped
    anyway for restyle) and _post_save so QC scores the final Arcane frame.
    ~1-2 min/frame.
    """
    svc = _svc()
    out_path, log, seed = ctx.out_path, ctx.log, ctx.seed
    if not (ctx.mf == 'sdxl' and os.path.isfile(out_path)):
        return
    _rprof_rt = svc._restyle_profile_from_package(ctx.character_package)
    if not _rprof_rt:
        return
    _rcfg = _rprof_rt['restyle']
    _engine = (_rcfg.get('render_engine') or 'qwen_edit').strip().lower()
    try:
        from zyg_workflows import arcane_restyle as _ar_rt

        if _engine == 'depth_controlnet_arcane':
            # UNIVERSAL authentic-Arcane engine: style_arcane LoRA + the char's identity
            # LoRA + a DEPTH ControlNet (age-agnostic geometry) img2img. Works for adults
            # AND children — depth preserves a child's proportions where InstantID's
            # adult-trained face model DISFIGURES them. No face required.
            _ar_rt.depth_controlnet_arcane_restyle(
                ctx.char_id,
                _rcfg,
                out_path,
                out_path,
                seed=seed,
                log_fn=log,
            )
        elif _engine == 'instantid_arcane':
            # AUTHENTIC Arcane via the trained style_arcane LoRA + InstantID face-lock
            # (a text instruction to Qwen cannot reproduce the trained aesthetic). Falls
            # back to style_arcane-only for faceless frames (inside the fn).
            _ar_rt.instantid_arcane_restyle(
                ctx.char_id,
                _rcfg,
                out_path,
                out_path,
                seed=seed,
                log_fn=log,
            )
        else:
            _ar_rt.qwen_restyle_image(
                ctx.char_id,
                _rcfg,
                out_path,
                out_path,
                seed=seed,
                log_fn=log,
            )
    except Exception as _rt_e:
        log(f'ComfyGen: arcane render-restyle skipped ({_rt_e!r})')


def run_hand_fixer_stage(ctx: StillRenderCtx) -> bool:
    """The HandFixer post-pass; returns True when it repaired this frame."""
    svc = _svc()
    log, character_package = ctx.log, ctx.character_package
    cond_pkg = (character_package or {}).get('conditioning', {})
    _want_hand_fix = cond_pkg.get('hand_detail_pass', True)
    # r4: the VLM hand judge is calibrated on photoreal hands — stylized
    # characters (toon/anime) skip the fixer entirely.
    _rs_hfx = str(((character_package or {}).get('style_profile') or {}).get('render_style') or '').lower()
    # 2026-07-27: restyle (Arcane) is painterly — the photoreal-calibrated hand judge
    # would repaint hands photoreal and fight the style. SDXL-only (mf=='sdxl'): the FLUX
    # photoreal twin leg of a restyle char must keep its HandFixer pass.
    if (ctx.mf == 'sdxl' and svc._restyle_profile_from_package(character_package)) or any(
        t in _rs_hfx for t in ('toon', 'anime', 'cartoon', 'animat', 'illustrat', 'comic', 'drawn')
    ):
        _want_hand_fix = False
    if not (_want_hand_fix and svc.hand_fixer_enabled() and svc.hand_fixer_stack_ready()):
        return False
    _hf_receipt: dict = {}
    _hand_fixer_ok = svc.apply_hand_fixer_pass(
        ctx.out_path,
        ctx.full_prompt,
        seed=ctx.seed,
        log_fn=log,
        character_package=character_package,
        receipt=_hf_receipt,
    )
    if not _hand_fixer_ok:
        log(f'ComfyGen: HandFixer did not repair this frame (reason={_hf_receipt.get("reason", "unknown")})')
        if svc.hand_detailer_stack_ready() and '63' not in ctx.workflow:
            log('ComfyGen: HandFixer pass skipped/failed — no HandDetailer fallback this run')
    return _hand_fixer_ok


# --------------------------------------------------------------------------- #
# HandFixer inner loop
# --------------------------------------------------------------------------- #


def hand_fix_render_crop(
    crop_p: str,
    mask_p: str,
    repair_prompt: str,
    *,
    comfy: Any,
    hand_qc: Any,
    seed: int,
    box_index: int,
    log: Callable[[str], None],
    check_halt: Callable[[], bool],
) -> tuple[list[str] | None, str | None]:
    """Inpaint one hand crop, retrying until the VLM judge accepts a repaint.

    Returns ``(outputs, abort_reason)``: ``outputs`` is None when every attempt
    was rejected (the caller counts that as a rejected crop), and
    ``abort_reason`` is set only when the whole pass must stop.
    """
    bi = box_index
    _n_att = max(1, int(os.environ.get('ZYG_HAND_FIXER_ATTEMPTS', '2')))
    # 2026-08-09 engine switch: prefer the Apache-2.0 InstantX Qwen inpaint
    # graph. The FLUX-Fill graph is NC (BFL licence) and previously ran with
    # NO flux-pause check — that bypass is closed here: while paused, the
    # flux leg refuses and the caller degrades to TELEA/HandDetailer.
    _hf_engine = os.environ.get('ZYG_HAND_FIXER_ENGINE', 'qwen').strip().lower()
    _use_qwen_fix = _hf_engine != 'flux' and _svc().has_qwen_hand_inpaint()
    if not _use_qwen_fix:
        try:
            from zyg_workflows import licence_provenance as _lp_hf

            if _lp_hf.flux_paused():
                log(
                    'ComfyGen: HandFixer FLUX-Fill leg refused — flux licence paused and Qwen inpaint stack unavailable'
                )
                return None, 'flux_paused_no_qwen'
        except ImportError as _exc:
            _zyg_log.warning(
                'HandFixer flux licence-pause check unavailable, continuing with the FLUX-Fill leg: %s',
                _exc,
            )
    _hf_workflow = 'hand_fixer_qwen_inpaint' if _use_qwen_fix else 'hand_fixer_flux_fill'
    outputs = None
    try:
        for _att in range(_n_att):
            try:
                _hf_overrides = {
                    '14': {'image': comfy.stage_input_image(crop_p)},
                    '46': {'image': comfy.stage_input_image(mask_p)},
                    '20': {'text': repair_prompt},
                    '31': {
                        'seed': int(seed) + 3 + bi + _att * 1009,
                        'steps': _svc()._HAND_FIXER_STEPS,
                        'denoise': float(os.environ.get('ZYG_HAND_FIXER_DENOISE', '1.0')),
                    },
                }
                if _use_qwen_fix:
                    _hf_overrides['31']['cfg'] = float(os.environ.get('ZYG_HAND_FIXER_QWEN_CFG', '2.5'))
                else:
                    _hf_overrides['27'] = {'guidance': _svc()._HAND_FIXER_GUIDANCE}
                _att_out = comfy.submit(
                    comfy.load_workflow(_hf_workflow),
                    overrides=_hf_overrides,
                    timeout_s=900,
                    should_abort=check_halt,
                )
            except comfy.ComfyUIError as exc:
                log(f'ComfyGen: HandFixer crop {bi + 1} attempt {_att + 1} failed — {exc}')
                continue
            if not _att_out:
                continue
            # VLM acceptance: only paste repaints the judge accepts.
            # hand_visible=false is a REJECTION — YOLO boxed a hand at
            # exactly this location, so an invisible hand means the fill
            # painted it out (review finding: all three layers previously
            # approved hand erasure, and the frame metric rewarded it).
            try:
                verdict = hand_qc.judge_image_file(_att_out[0])
                _erased = not verdict.get('hand_visible', True)
                _bad = _erased or (
                    bool(verdict.get('defective'))
                    and str(verdict.get('confidence') or '').lower() in ('high', 'medium')
                )
                if _bad:
                    _why = 'hand erased by fill' if _erased else str(verdict.get('problem') or '')[:90]
                    log(f'ComfyGen: HandFixer crop {bi + 1} attempt {_att + 1} rejected by VLM ({_why})')
            except Exception as exc:
                log(
                    f'ComfyGen: HandFixer crop {bi + 1} — VLM verify unavailable '
                    f'({exc!r}); rejecting repaint (fail closed)'
                )
                _bad = True
            if not _bad:
                outputs = _att_out
                break
    finally:
        for _pth in (crop_p, mask_p):
            try:
                os.remove(_pth)
            except OSError as _exc:
                _zyg_log.debug('HandFixer crop/mask cleanup of %s skipped: %s', _pth, _exc)
    return outputs, None
