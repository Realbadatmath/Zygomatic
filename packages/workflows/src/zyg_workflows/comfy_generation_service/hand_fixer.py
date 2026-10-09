# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""HandFixer: the FLUX Fill inpaint pass over detected hand boxes (original lines 725-1192)."""

from __future__ import annotations

import os
import shutil
from typing import Callable
from zyg_workflows import comfy_generation_service_steps as _steps
from zyg_workflows.comfy_generation_service.constants import _COMFY_ROOT, _comfy, _log_default, _zyg_log
from zyg_workflows.comfy_generation_service.flux_graph import _hand_yolo_path


_FLUX_FILL_UNET = (
    os.environ.get(
        'ZYG_FLUX_FILL_UNET',
        'flux1-fill-dev.safetensors',
    ).strip()
    or 'flux1-fill-dev.safetensors'
)
_HAND_FIXER_STEPS = int(os.environ.get('ZYG_HAND_FIXER_STEPS', '20'))
_HAND_FIXER_GUIDANCE = float(os.environ.get('ZYG_HAND_FIXER_GUIDANCE', '30'))
_HAND_FIXER_PROMPT = (
    'anatomically correct hands, five fingers per hand, detailed knuckles and nails, '
    'natural hand skin texture, symmetrical hands, open relaxed fingers'
)


def hand_fixer_enabled() -> bool:
    """True unless ZYG_HAND_FIXER is explicitly disabled."""
    return os.environ.get('ZYG_HAND_FIXER', '1').strip().lower() in (
        '1',
        'true',
        'yes',
        'on',
    )


def _flux_fill_unet_path() -> str:
    return os.path.join(_COMFY_ROOT, 'models', 'unet', _FLUX_FILL_UNET)


def hand_fixer_stack_ready() -> bool:
    """HandFixer post-pass: YOLO weights + FLUX Fill UNet + encoders on disk.

    2026-07-24 rebuild: masks are host-built from ADetailer YOLO boxes and
    staged as images (the in-graph MediapipeHandNode missed malformed hands
    in 22/29 frames and produced giant false-positive masks on 7/29)."""
    if _comfy is None or not _comfy.server_reachable():
        return False
    if not (os.path.isfile(_hand_yolo_path()) and os.path.getsize(_hand_yolo_path()) > 1_000_000):
        return False
    unet = _flux_fill_unet_path()
    if not os.path.isfile(unet) or os.path.getsize(unet) < 1_000_000_000:
        return False
    clip_dir = os.path.join(_COMFY_ROOT, 'models', 'clip')
    vae_path = os.path.join(_COMFY_ROOT, 'models', 'vae', 'flux_ae.safetensors')
    return (
        os.path.isfile(os.path.join(clip_dir, 'clip_l.safetensors'))
        and os.path.isfile(os.path.join(clip_dir, 't5xxl_fp8_e4m3fn.safetensors'))
        and os.path.isfile(vae_path)
    )


def _hand_boxes_for_fix(image_path: str, log) -> 'list[tuple] | None':
    """Detect hand boxes for the fixer. FAIL-CLOSED (2026-07-24 rebuild).

    The old gate returned (True, -1) on ANY exception — run 6278904c ran a
    blind whole-graph inpaint on 29/29 renders and logged the sentinel inside
    a success message ('applied (-1 YOLO hand box(es))'). Now: detection
    failure → None → the caller SKIPS the pass loudly. Boxes larger than
    ZYG_HAND_FIXER_MAX_BOX_PCT of the frame are dropped as false positives
    (the 7 destructive repaints in 6278904c all came from giant masks).
    """
    try:
        from zyg_workflows import hand_qc_service as _hqs

        boxes = _hqs.detect_hand_boxes(image_path)
    except Exception as exc:
        log(f'ComfyGen: HandFixer SKIPPED — hand detection failed ({exc!r})')
        return None
    if not boxes:
        return []
    try:
        from PIL import Image as _PIL_hb

        with _PIL_hb.open(image_path) as _im:
            _fw, _fh = _im.size
    except Exception as exc:
        log(f'ComfyGen: HandFixer SKIPPED — cannot read frame ({exc!r})')
        return None
    _max_pct = float(os.environ.get('ZYG_HAND_FIXER_MAX_BOX_PCT', '12'))
    _frame_area = float(_fw * _fh)
    kept: list[tuple] = []
    for b in sorted(boxes, key=lambda bb: bb.get('conf', 0.0), reverse=True):
        x1, y1, x2, y2 = b['box']
        _area_pct = 100.0 * max(0.0, (x2 - x1)) * max(0.0, (y2 - y1)) / _frame_area
        if _area_pct > _max_pct:
            log(
                f'ComfyGen: HandFixer dropped oversized hand box '
                f'({_area_pct:.0f}% of frame > {_max_pct:.0f}% — false positive guard)'
            )
            continue
        kept.append((x1, y1, x2, y2))
    # Cap the fill workload on multi-person frames (each box costs up to two
    # fills + VLM verdicts) — highest-confidence boxes first.
    _max_boxes = int(os.environ.get('ZYG_HAND_FIXER_MAX_BOXES', '4'))
    if len(kept) > _max_boxes:
        log(f'ComfyGen: HandFixer capping {len(kept)} hand boxes to {_max_boxes}')
        kept = kept[:_max_boxes]
    return kept


def apply_hand_fixer_pass(
    out_path: str,
    prompt: str,
    *,
    seed: int = 42,
    log_fn: Callable[[str], None] | None = None,
    character_package: dict | None = None,
    receipt: dict | None = None,
) -> bool:
    """Run HandFixer FLUX-Fill post-pass; overwrites *out_path* on success.

    Exception-safe by contract: ANY unexpected error restores the original
    frame and returns False — a QC pass must never turn an already-saved good
    render into a failed generation (review finding on the r4 rebuild).

    receipt : dict | None
        Optional out-param. When given, it is cleared and populated in place
        with ``{'ran': bool, 'reason': str | None, 'stats': dict}`` describing
        whether a repair attempt actually ran and, when it did not, why (one
        of 'disabled', 'stack_not_ready', 'file_missing',
        'detection_unavailable', 'no_boxes', 'vlm_unavailable',
        'image_read_failed', 'skip_clean', 'flux_paused_no_qwen', 'halted',
        'no_accepted_repairs', 'reverted_hand_count_drop',
        'reverted_score_regression', 'unexpected_error'). ``reason`` is
        ``None`` when ``ran`` is True. This is purely additive — the bool
        return value and all existing behaviour are unchanged; callers that
        don't pass a dict see no difference. Added so callers (storyteller
        scene / episode pipelines) can log/record WHY a call produced no
        repair instead of only a bare boolean (previously only ad hoc log
        lines carried that information, and only at DEBUG-ish granularity).
    """
    log = log_fn or _log_default
    if receipt is not None:
        receipt.clear()
        receipt.update(ran=False, reason='not_started', stats={})
    import tempfile as _tf_guard

    _guard_snap = os.path.join(_tf_guard.gettempdir(), f'zyg_handfix_guard_{os.getpid()}_{seed}.png')
    _inner_snap = os.path.join(_tf_guard.gettempdir(), f'zyg_handfix_snap_{os.getpid()}_{seed}.png')
    _have_snap = False
    try:
        if os.path.isfile(out_path):
            shutil.copy2(out_path, _guard_snap)
            _have_snap = True
        return _apply_hand_fixer_pass_inner(
            out_path,
            prompt,
            seed=seed,
            log_fn=log_fn,
            character_package=character_package,
            receipt=receipt,
        )
    except Exception as exc:
        log(f'ComfyGen: HandFixer unexpected error ({exc!r}) — frame restored, pass skipped')
        if _have_snap:
            try:
                shutil.copy2(_guard_snap, out_path)
            except OSError as _exc:
                _zyg_log.warning(
                    'HandFixer guard restore of %s failed, frame left as the failed pass wrote it: %s',
                    out_path,
                    _exc,
                )
        if receipt is not None:
            receipt.update(ran=False, reason='unexpected_error', stats={'error': repr(exc)})
        return False
    finally:
        for _p in (_guard_snap, _inner_snap):
            try:
                os.remove(_p)
            except OSError as _exc:
                _zyg_log.debug('HandFixer snapshot cleanup of %s skipped: %s', _p, _exc)


def _apply_hand_fixer_pass_inner(
    out_path: str,
    prompt: str,
    *,
    seed: int = 42,
    log_fn: Callable[[str], None] | None = None,
    character_package: dict | None = None,
    receipt: dict | None = None,
) -> bool:
    """Body of the HandFixer pass; see apply_hand_fixer_pass for the contract.

    character_package: when given, the character's skin tone is injected into
    the repair prompt and enforced by the region tone guard — run 6278904c's
    old pass painted a pale hand onto a dark-skinned character.
    """
    log = log_fn or _log_default

    def _mark(reason: str | None, ran: bool = False, **stats) -> None:
        if receipt is not None:
            receipt.update(ran=ran, reason=reason, stats=stats)

    if not hand_fixer_enabled():
        _mark('disabled')
        return False
    if not hand_fixer_stack_ready():
        _mark('stack_not_ready')
        return False
    if not os.path.isfile(out_path):
        _mark('file_missing')
        return False

    boxes = _hand_boxes_for_fix(out_path, log)
    if boxes is None:
        _mark('detection_unavailable')
        return False  # detection unavailable — fail closed, already logged
    if not boxes:
        log('ComfyGen: HandFixer skipped — no hand boxes detected')
        _mark('no_boxes')
        return False

    _skin_bits = ''
    try:
        _ident_hf = (character_package or {}).get('identity') or {}
        _st_hf = (_ident_hf.get('skin_tone') or '').strip()
        if _st_hf:
            _skin_bits = f"{_st_hf} skin tone, hand skin color exactly matching the person's face, "
    except Exception:
        _skin_bits = ''
    repair_prompt = (
        (prompt.split(',')[0].strip() + ', ' + _skin_bits + _HAND_FIXER_PROMPT)
        if prompt
        else (_skin_bits + _HAND_FIXER_PROMPT)
    )[:400]

    # 2026-07-24 r4: DETAILER-STYLE crop fills. A whole-frame fill re-invents a
    # ~100px hand with far too little pixel density — the empirical test on run
    # 6278904c's scene_015 made the hands WORSE (VLM 0.55 → 0.10). Each hand is
    # cropped, upscaled to _HF_CROP_LONG px, filled, judged by the VLM, and
    # pasted back ONLY when the judge accepts the repaint.
    import tempfile as _tf_hfx
    from PIL import Image as _PIL_hf, ImageDraw as _PD_hf, ImageFilter as _PF_hf

    _HF_CROP_LONG = int(os.environ.get('ZYG_HAND_FIXER_CROP_PX', '1024'))
    _HF_CTX = float(os.environ.get('ZYG_HAND_FIXER_CROP_CTX', '2.2'))
    _max_cd = float(os.environ.get('ZYG_HAND_FIXER_MAX_COLOR_DELTA', '55'))

    try:
        from zyg_workflows import hand_qc_service as _hqs_fix
    except Exception as exc:
        log(f'ComfyGen: HandFixer SKIPPED — {exc!r}')
        _mark('vlm_unavailable', error=repr(exc))
        return False
    try:
        base_im = _PIL_hf.open(out_path).convert('RGB')
    except Exception as exc:
        log(f'ComfyGen: HandFixer SKIPPED — {exc!r}')
        _mark('image_read_failed', error=repr(exc))
        return False

    # Monotonic frame-score guard: the crop-level judge and the downstream
    # frame-level judge can disagree on the same hand (different crops), so
    # the final acceptance is scored with the SAME metric the pipeline gates
    # use — if the frame's hand score does not improve, everything reverts.
    _pre_score = None
    try:
        _pre_score, _ = _hqs_fix.hand_quality(out_path)
    except Exception:
        _pre_score = None
    _skip_clean = float(os.environ.get('ZYG_HAND_FIXER_SKIP_CLEAN', '0.9'))
    if _pre_score is not None and _pre_score >= _skip_clean:
        log(f'ComfyGen: HandFixer skipped — hands already clean (score {_pre_score:.2f} ≥ {_skip_clean:.2f})')
        _mark('skip_clean', pre_score=_pre_score, skip_clean_threshold=_skip_clean)
        return False
    _frame_snap = os.path.join(__import__('tempfile').gettempdir(), f'zyg_handfix_snap_{os.getpid()}_{seed}.png')
    shutil.copy2(out_path, _frame_snap)

    from zyg_workflows import pipeline_control as _pc_hf

    if _pc_hf.halt_requested():
        log('ComfyGen: HandFixer skipped — pipeline halt requested')
        _mark('halted')
        return False
    _fw, _fh = base_im.size
    accepted = 0
    rejected = 0
    for bi, (x1, y1, x2, y2) in enumerate(boxes):
        _check_halt = _pc_hf.halt_requested
        bw, bh = x2 - x1, y2 - y1
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        half = max(bw, bh) * _HF_CTX / 2
        half = max(half, 192.0)
        cx1, cy1 = max(0, int(cx - half)), max(0, int(cy - half))
        cx2, cy2 = min(_fw, int(cx + half)), min(_fh, int(cy + half))
        if cx2 - cx1 < 32 or cy2 - cy1 < 32:
            continue
        crop = base_im.crop((cx1, cy1, cx2, cy2))
        _scale = _HF_CROP_LONG / max(crop.size)
        up = crop.resize((max(8, round(crop.width * _scale)), max(8, round(crop.height * _scale))), _PIL_hf.LANCZOS)
        # hand mask inside the crop (box coords shifted + scaled, dilated 18%)
        mask = _PIL_hf.new('L', up.size, 0)
        _mx, _my = bw * 0.18, bh * 0.18
        _PD_hf.Draw(mask).rectangle(
            (
                max(0, (x1 - _mx - cx1) * _scale),
                max(0, (y1 - _my - cy1) * _scale),
                min(up.width, (x2 + _mx - cx1) * _scale),
                min(up.height, (y2 + _my - cy1) * _scale),
            ),
            fill=255,
        )
        mask = mask.filter(_PF_hf.GaussianBlur(10))
        _tag = f'{os.getpid()}_{seed}_{bi}'
        crop_p = os.path.join(_tf_hfx.gettempdir(), f'zyg_hfcrop_{_tag}.png')
        mask_p = os.path.join(_tf_hfx.gettempdir(), f'zyg_hfmask_{_tag}.png')
        up.save(crop_p)
        mask.convert('RGB').save(mask_p)
        outputs, _hf_abort = _steps.hand_fix_render_crop(
            crop_p,
            mask_p,
            repair_prompt,
            comfy=_comfy,
            hand_qc=_hqs_fix,
            seed=seed,
            box_index=bi,
            log=log,
            check_halt=_check_halt,
        )
        if _hf_abort:
            _mark(_hf_abort, box_index=bi, boxes=len(boxes))
            return False
        if not outputs:
            rejected += 1
            continue
        with _PIL_hf.open(outputs[0]) as _res:
            fixed_crop = _res.convert('RGB').resize(crop.size, _PIL_hf.LANCZOS)
        # Tone guard on the HAND REGION medians (not crop means — background
        # dilutes those and let a pale repaint through in testing). Anchor is
        # the original hand region: base renders carry the correct tone.
        import numpy as _np_hf

        _a = _np_hf.asarray(crop, dtype=_np_hf.float32)
        _b = _np_hf.asarray(fixed_crop, dtype=_np_hf.float32)
        _rx1 = max(0, int((x1 - cx1)))
        _ry1 = max(0, int((y1 - cy1)))
        _rx2 = min(crop.width, int((x2 - cx1)))
        _ry2 = min(crop.height, int((y2 - cy1)))
        if _rx2 > _rx1 and _ry2 > _ry1:
            _ma = _np_hf.median(_a[_ry1:_ry2, _rx1:_rx2].reshape(-1, 3), axis=0)
            _mb = _np_hf.median(_b[_ry1:_ry2, _rx1:_rx2].reshape(-1, 3), axis=0)
            _tone_d = float(_np_hf.linalg.norm(_ma - _mb))
            if _tone_d > _max_cd:
                log(f'ComfyGen: HandFixer crop {bi + 1} rejected (hand tone shifted {_tone_d:.0f} > {_max_cd:.0f})')
                rejected += 1
                continue
        paste_mask = mask.resize(crop.size, _PIL_hf.LANCZOS)
        base_im.paste(fixed_crop, (cx1, cy1), paste_mask)
        accepted += 1

    def _rm_snap():
        try:
            os.remove(_frame_snap)
        except OSError as _exc:
            _zyg_log.debug('HandFixer frame snapshot cleanup of %s skipped: %s', _frame_snap, _exc)

    if not accepted:
        _rm_snap()
        log(
            f'ComfyGen: HandFixer made no accepted repairs '
            f'({rejected}/{len(boxes)} repaint(s) rejected) — original kept'
        )
        _mark('no_accepted_repairs', rejected=rejected, boxes=len(boxes))
        return False

    base_im.save(out_path)
    _post_score = None
    _post_boxes = None
    try:
        _post_score, _ = _hqs_fix.hand_quality(out_path)
        _post_boxes = len(_hqs_fix.detect_hand_boxes(out_path))
    except Exception:
        _post_score = None
    # Box-count conservation: fewer detectable hands after the fix means a
    # hand was painted out — the score metric would otherwise REWARD erasure
    # (no hands → 1.0).
    if _post_boxes is not None and _post_boxes < len(boxes):
        shutil.copy2(_frame_snap, out_path)
        _rm_snap()
        log(f'ComfyGen: HandFixer REVERTED — hand count dropped {len(boxes)} → {_post_boxes} (erasure guard)')
        _mark(
            'reverted_hand_count_drop', boxes=len(boxes), post_boxes=_post_boxes, accepted=accepted, rejected=rejected
        )
        return False
    if _pre_score is not None and _post_score is not None and _post_score < _pre_score - 1e-9:
        shutil.copy2(_frame_snap, out_path)
        _rm_snap()
        log(f'ComfyGen: HandFixer REVERTED — frame hand score would drop {_pre_score:.2f} → {_post_score:.2f}')
        _mark(
            'reverted_score_regression',
            pre_score=_pre_score,
            post_score=_post_score,
            accepted=accepted,
            rejected=rejected,
        )
        return False
    _rm_snap()
    _score_note = ''
    if _pre_score is not None and _post_score is not None:
        _score_note = f' (frame hand score {_pre_score:.2f} → {_post_score:.2f})'
    log(
        f'ComfyGen: HandFixer applied — {accepted}/{len(boxes)} hand region(s) '
        f'repainted and VLM-verified' + (f', {rejected} repaint(s) rejected' if rejected else '') + _score_note
    )
    _mark(
        None,
        ran=True,
        accepted=accepted,
        rejected=rejected,
        boxes=len(boxes),
        pre_score=_pre_score,
        post_score=_post_score,
    )
    return True


def _maybe_recover_sharpness_after_inpaint(out_path: str, log_fn: Callable[[str], None]) -> None:
    """HandFixer inpaint often softens edges — mild sharpen when variance is low."""
    if os.environ.get('ZYG_POST_INPAINT_SHARPEN', '1').strip().lower() in ('0', 'false', 'no'):
        return
    try:
        from zyg_workflows import scene_still_helpers as _ssh

        # normalize=False: this threshold was tuned on raw native-resolution
        # variance; r3's 512px normalization would silently disable the gate
        # for >512px frames.
        _, lap = _ssh.scene_quality_metrics(out_path, normalize=False)
        thresh = float(os.environ.get('ZYG_POST_INPAINT_SHARP_THRESH', '30'))
        if lap < thresh and _ssh.sharpen_image_file(out_path):
            log_fn(f'ComfyGen: sharpened after inpaint (edge var was {lap:.1f}, threshold {thresh:.0f})')
    except Exception as _exc:
        _zyg_log.debug('post-inpaint sharpen skipped: %s', _exc)


def _patch_workflow_sam_loader(workflow: dict) -> None:
    """Impact-Pack SAMLoader requires device_mode (ComfyUI ≥ Impact-Pack 8.x)."""
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        if node.get('class_type') != 'SAMLoader':
            continue
        inp = node.setdefault('inputs', {})
        inp.setdefault('model_name', 'sam_vit_b_01ec64.pth')
        inp.setdefault('device_mode', 'AUTO')


def _strip_face_detailer(workflow: dict) -> dict:
    """Remove all detailer passes; SaveImage ← first-pass VAEDecode."""
    for nid in ('55', '56', '60', '61', '63'):
        workflow.pop(nid, None)
    save = workflow.get('50')
    if save and isinstance(save.get('inputs'), dict):
        save['inputs']['images'] = ['40', 0]
    return workflow


def _strip_hand_detailer(workflow: dict) -> dict:
    """Remove hand pass only; SaveImage ← face FaceDetailer output."""
    for nid in ('61', '63'):
        workflow.pop(nid, None)
    save = workflow.get('50')
    if save and isinstance(save.get('inputs'), dict):
        src = '60' if '60' in workflow else '40'
        save['inputs']['images'] = [src, 0]
    return workflow
