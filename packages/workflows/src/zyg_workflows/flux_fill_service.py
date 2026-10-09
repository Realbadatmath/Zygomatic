# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 3.6 — anatomy (hands/arms) inpaint repair pass.

After the still-generation loop produces images with qa_score < threshold,
this service runs a targeted inpainting pass over the defective anatomy
regions. (The module keeps its historical name; FLUX-Fill is now the LAST
resort, not the engine.)

Architecture decision
---------------------
Three tiers, tried in this order per image:

  Tier A (Quality, licence-clean, default):
    Qwen-Image-2512 + InstantX ControlNet-Inpainting through ComfyUI
    (``_comfy_workflows/hand_fixer_qwen_inpaint.json``). Both Apache-2.0.
    Needs ZYG_USE_COMFYUI=1, a reachable server and the two weight files.

  Tier B (Quality, NON-commercial, gated by ``use_flux_fill``):
    FluxFillPipeline in-process (or the ``flux_fill_inpaint`` Comfy graph).
    ``black-forest-labs/FLUX.1-Fill-dev`` is under the BFL Non-Commercial
    License — paused by licence_provenance.flux_paused() on a monetised
    channel, and only consulted when Tier A is unavailable.

  Tier C (Fast, always available):
    OpenCV TELEA inpainting — deterministic, CPU-only, instant.
    Good enough for minor artefacts and partially-melted regions.

``use_flux_fill=False`` suppresses ONLY Tier B. P-10 (run docsmoke-b58104c4):
the Comfy/Qwen documentary path skipped this whole service with a hard-coded
ImportError guard — which blocked exactly the licence-clean engine whose
weights and graph are on disk. Call ``repair_batch(..., use_flux_fill=False)``
there instead; :func:`is_available` says whether A or C can run.

Usage
-----
    from zyg_workflows import flux_fill_service as ffs
    updated_meta = ffs.repair_batch(
        flux_image_meta,           # list[dict] with qa_score + qa_issues fields
        qa_threshold=0.65,         # only repair images below this score
        use_flux_fill=True,        # False = never touch the FLUX-Fill tier
        log_fn=lambda m: print(m),
    )
    # updated_meta[i]['path'] may point to the repaired image now
"""

from __future__ import annotations

import os
import threading
from typing import Callable

import cv2
import mediapipe as mp
import numpy as np
from PIL import Image

from zyg_workflows import paths

try:
    from zyg_workflows import _comfy_client as _comfy
except ImportError:
    _comfy = None
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# ── Model path ────────────────────────────────────────────────────────────────
_FILL_MODEL_ID = 'black-forest-labs/FLUX.1-Fill-dev'
_FILL_MODEL_ALT = 'black-forest-labs/FLUX.1-schnell'  # fallback: schnell has fill
_MIN_VRAM_GB = 20.0  # skip Tier 2 if VRAM is tighter

_pipe_lock = threading.Lock()
_fill_pipe = None  # FluxFillPipeline cached instance


# ── Public API ────────────────────────────────────────────────────────────────


def repair_batch(
    flux_image_meta: list[dict],
    qa_threshold: float = 0.65,
    use_flux_fill: bool = True,
    log_fn: Callable[[str], None] | None = None,
) -> list[dict]:
    """Run Stage 3.6 repair on all images below *qa_threshold*.

    Parameters
    ----------
    flux_image_meta:
        Full list from Stage 3.5. Entries with ``qa_score < qa_threshold``
        and non-empty ``qa_issues`` are candidates for repair.
    qa_threshold:
        Images scoring below this float are repaired.  Default 0.65.
    use_flux_fill:
        Gates ONLY the FLUX-Fill tier (in-process ``FluxFillPipeline`` and its
        ComfyUI ``flux_fill_inpaint`` twin — both FLUX.1-Fill-dev, BFL
        Non-Commercial). With ``use_flux_fill=False`` the Apache-2.0 Qwen
        InstantX inpaint tier (ComfyUI) and the cv2 TELEA fallback still run.
        P-10: Stage 3.5 on the Comfy/Qwen path should call
        ``repair_batch(..., use_flux_fill=False)`` rather than skip the
        service outright.
    log_fn:
        Optional ``log_fn(message)`` callback.

    Returns
    -------
    list[dict]
        Same structure as input; ``path`` fields updated for repaired images,
        ``repair_pass`` field added (``'qwen_inpaint_comfy'``, ``'flux_fill'``,
        ``'flux_fill_comfy'`` or ``'cv2_telea'``).
    """

    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    candidates = [m for m in flux_image_meta if (m.get('qa_score') or 1.0) < qa_threshold and m.get('qa_issues')]

    if not candidates:
        _log('Stage 3.6: no images below QA threshold — repair pass skipped')
        return flux_image_meta

    _log(f'Stage 3.6: {len(candidates)} image(s) below QA threshold ({qa_threshold}) — starting repair pass')

    # Tier order: Qwen InstantX inpaint (Apache-2.0, ComfyUI) → FLUX-Fill (only
    # when use_flux_fill AND no Qwen) → cv2 TELEA (always). use_flux_fill=False
    # suppresses nothing but the FLUX tier — verified 2026-08-25 (P-10).
    qwen_inpaint_available = _can_use_qwen_inpaint(_log)
    flux_fill_available = False
    if use_flux_fill and not qwen_inpaint_available:
        flux_fill_available = _can_use_flux_fill(_log)
    _tiers = (
        (['qwen_inpaint_comfy'] if qwen_inpaint_available else [])
        + (['flux_fill'] if flux_fill_available else [])
        + ['cv2_telea']
    )
    _log(
        'Stage 3.6: repair tiers active — '
        + ' → '.join(_tiers)
        + ('' if use_flux_fill else ' (FLUX-Fill tier suppressed: use_flux_fill=False)')
    )

    repaired = 0
    for meta in candidates:
        src_path = meta.get('path', '')
        if not src_path or not os.path.exists(src_path):
            continue

        mask = _build_repair_mask(src_path, meta.get('qa_issues', []))
        if mask is None:
            _log(f'Stage 3.6: skipping {os.path.basename(src_path)} — mask generation failed')
            continue

        out_path = None
        if qwen_inpaint_available:
            out_path, method = _repair_via_qwen_comfyui(src_path, mask, meta.get('prompt', ''), _log)
        if not out_path and flux_fill_available:
            out_path, method = _repair_flux_fill(src_path, mask, meta.get('prompt', ''), _log)
        if not out_path:
            out_path, method = _repair_cv2(src_path, mask, _log)

        if out_path and os.path.exists(out_path):
            meta['path'] = out_path
            meta['repair_pass'] = method
            meta['qa_score'] = 0.70  # mark as repaired (will not re-trigger retry)
            repaired += 1
            _log(f'Stage 3.6: repaired slot {meta["index"]} → {os.path.basename(out_path)} ({method})')
        else:
            _log(f'Stage 3.6: repair failed for slot {meta["index"]} — keeping original')

    _log(f'Stage 3.6: repair pass complete — {repaired}/{len(candidates)} fixed')

    with _pipe_lock:
        _unload_fill_pipe(_log)

    return flux_image_meta


def _telea_available() -> bool:
    try:
        return callable(getattr(cv2, 'inpaint', None)) and hasattr(cv2, 'INPAINT_TELEA')
    except Exception:
        return False


def available_tiers(use_flux_fill: bool = True, log_fn: Callable[[str], None] | None = None) -> list[str]:
    """Repair tiers that could run right now, in the order repair_batch tries them."""

    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    tiers: list[str] = []
    if _can_use_qwen_inpaint(_log):
        tiers.append('qwen_inpaint_comfy')
    if use_flux_fill and not tiers and _can_use_flux_fill(_log):
        tiers.append('flux_fill')
    if _telea_available():
        tiers.append('cv2_telea')
    return tiers


def is_available() -> bool:
    """True when a licence-clean repair engine can run: the ComfyUI Qwen
    InstantX inpaint tier or cv2 TELEA. FLUX-Fill is deliberately NOT counted
    (P-10: the anatomy pass must not depend on the non-commercial engine)."""
    if _telea_available():
        return True
    try:
        return _can_use_qwen_inpaint(lambda _m: None)
    except Exception:
        return False


# ── Mask generation ───────────────────────────────────────────────────────────


def _build_repair_mask(image_path: str, qa_issues: list[str]) -> np.ndarray | None:
    """Return a uint8 binary mask (255 = inpaint, 0 = keep).

    Uses MediaPipe Holistic to detect hand + arm regions, then inflates
    the bounding box to give diffusion enough context.
    """
    try:
        img_bgr = cv2.imread(image_path)
        if img_bgr is None:
            return None
        h, w = img_bgr.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)

        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        mp_hol = mp.solutions.holistic
        with mp_hol.Holistic(
            static_image_mode=True,
            model_complexity=1,
            min_detection_confidence=0.4,
        ) as hol:
            res = hol.process(img_rgb)

            # Identify which sides are flagged in the qa_issues text
            flagged_sides = set()
            for iss in qa_issues:
                lo = iss.lower()
                if 'left' in lo:
                    flagged_sides.add('left')
                if 'right' in lo:
                    flagged_sides.add('right')
                if 'shoulder' in lo or 'arm' in lo:
                    flagged_sides.update({'left', 'right'})

            hand_map = {
                'left': res.left_hand_landmarks,
                'right': res.right_hand_landmarks,
            }
            pose_lms = res.pose_landmarks.landmark if res.pose_landmarks else []

            for side, hand_lms in hand_map.items():
                if hand_lms is None:
                    continue
                if flagged_sides and side not in flagged_sides:
                    continue
                xs = [int(lm.x * w) for lm in hand_lms.landmark]
                ys = [int(lm.y * h) for lm in hand_lms.landmark]
                x1, x2 = max(0, min(xs) - 40), min(w, max(xs) + 40)
                y1, y2 = max(0, min(ys) - 40), min(h, max(ys) + 40)
                mask[y1:y2, x1:x2] = 255

            # Add upper arm region if shoulder issues flagged
            if pose_lms and (not flagged_sides or 'shoulder' in ' '.join(qa_issues).lower()):
                arm_idxs = [11, 12, 13, 14, 15, 16]  # shoulders + elbows + wrists
                visible = [i for i in arm_idxs if pose_lms[i].visibility > 0.5]
                if visible:
                    xs2 = [int(pose_lms[i].x * w) for i in visible]
                    ys2 = [int(pose_lms[i].y * h) for i in visible]
                    x1, x2 = max(0, min(xs2) - 30), min(w, max(xs2) + 30)
                    y1, y2 = max(0, min(ys2) - 30), min(h, max(ys2) + 30)
                    mask[y1:y2, x1:x2] = 255

        if mask.max() == 0:
            # No landmarks found — mask entire lower half as conservative repair zone
            mask[h // 2 :, :] = 255

        # Dilate slightly for smooth blending
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21))
        mask = cv2.dilate(mask, kernel, iterations=1)
        return mask

    except Exception as _exc:
        _zyg_log.debug('mask build failed: %s: %s', type(_exc).__name__, _exc)
        return None


# ── Tier 1: OpenCV TELEA inpainting ──────────────────────────────────────────


def _repair_cv2(
    image_path: str,
    mask: np.ndarray,
    log_fn: Callable[[str], None],
) -> tuple[str | None, str]:
    """Fast CPU inpainting using OpenCV TELEA.  Returns (out_path, 'cv2_telea')."""
    try:
        img_bgr = cv2.imread(image_path)
        repaired = cv2.inpaint(img_bgr, mask, inpaintRadius=5, flags=cv2.INPAINT_TELEA)
        out_path = _repaired_path(image_path, 'r2')
        cv2.imwrite(out_path, repaired, [cv2.IMWRITE_JPEG_QUALITY, 92])
        return out_path, 'cv2_telea'
    except Exception as e:
        log_fn(f'Stage 3.6 cv2 repair failed: {e}')
        return None, 'cv2_telea'


# ── Tier 2: FLUX Fill pipeline ────────────────────────────────────────────────


def _can_use_flux_fill(log_fn: Callable[[str], None]) -> bool:
    """Check licence posture + VRAM + model cache availability for FluxFillPipeline."""
    try:
        # 2026-08-09 licence pause. FLUX.1-Fill-dev carries the same BFL
        # Non-Commercial License as flux1-dev. This is the right choke point:
        # every caller already handles False by degrading to the cv2 repair path,
        # so pausing costs quality here, not a broken stage.
        try:
            from zyg_workflows import licence_provenance as _lp

            if _lp.flux_paused():
                log_fn(
                    'Stage 3.6: FLUX fill PAUSED (BFL Non-Commercial License, '
                    'monetised channel) — using cv2 repair. '
                    'ZYG_FLUX_RENDERS=allowed to resume.'
                )
                return False
        except ImportError as _exc:
            _zyg_log.warning('licence_provenance unavailable, the FLUX licence pause was not checked: %s', _exc)

        import torch

        if not torch.cuda.is_available():
            return False
        free_gb = torch.cuda.mem_get_info(0)[0] / 1024**3
        if free_gb < _MIN_VRAM_GB:
            log_fn(f'Stage 3.6: VRAM too low ({free_gb:.1f} GB < {_MIN_VRAM_GB} GB) — using cv2 repair')
            return False
        from huggingface_hub import try_to_load_from_cache

        found = try_to_load_from_cache(_FILL_MODEL_ID, 'model_index.json')
        if found is None:
            log_fn(f'Stage 3.6: {_FILL_MODEL_ID} not in HF cache — using cv2 repair')
            return False
        return True
    except Exception:
        return False


def _load_fill_pipe(log_fn: Callable[[str], None]) -> None:
    global _fill_pipe
    if _fill_pipe is not None:
        return
    try:
        import torch
        from diffusers import FluxFillPipeline

        log_fn(f'Stage 3.6: loading {_FILL_MODEL_ID} …')
        _fill_pipe = FluxFillPipeline.from_pretrained(
            _FILL_MODEL_ID,
            torch_dtype=torch.bfloat16,
            local_files_only=True,
        ).to('cuda')
        log_fn('Stage 3.6: FluxFillPipeline loaded')
    except Exception as e:
        log_fn(f'Stage 3.6: FluxFillPipeline load failed — {e}')
        _fill_pipe = None


def _unload_fill_pipe(log_fn: Callable[[str], None]) -> None:
    global _fill_pipe
    if _fill_pipe is None:
        return
    try:
        import torch
        import gc

        _fill_pipe.to('cpu')
        del _fill_pipe
        _fill_pipe = None
        gc.collect()
        torch.cuda.empty_cache()
        log_fn('Stage 3.6: FluxFillPipeline unloaded')
    except Exception:
        _fill_pipe = None


def _repair_flux_fill(
    image_path: str,
    mask: np.ndarray,
    prompt: str,
    log_fn: Callable[[str], None],
) -> tuple[str | None, str]:
    """Diffusion inpainting with FluxFillPipeline (or ComfyUI when enabled)."""
    if _comfy is not None and _comfy.is_enabled() and _comfy.server_reachable():
        out = _repair_via_comfyui(image_path, mask, prompt, log_fn)
        if out[0] is not None:
            return out
        log_fn('Stage 3.6: ComfyUI repair returned no output — falling back to diffusers')

    global _fill_pipe
    try:
        import torch

        with _pipe_lock:
            _load_fill_pipe(log_fn)
            if _fill_pipe is None:
                return _repair_cv2(image_path, mask, log_fn)

            src_pil = Image.open(image_path).convert('RGB')
            mask_pil = Image.fromarray(mask).convert('L')

            # Anatomy repair prompt: strip style decorators, keep subject context
            repair_prompt = (
                prompt.split(',')[0].strip() + ', '
                'correct human anatomy, natural hands with exactly 5 fingers, '
                'realistic proportions, no deformities, photorealistic'
            )[:300]

            result = _fill_pipe(
                prompt=repair_prompt,
                image=src_pil,
                mask_image=mask_pil,
                width=src_pil.width,
                height=src_pil.height,
                num_inference_steps=20,
                guidance_scale=30.0,
                generator=torch.Generator('cuda').manual_seed(42),
            ).images[0]

            out_path = _repaired_path(image_path, 'r3f')
            result.save(out_path, 'JPEG', quality=92)
            return out_path, 'flux_fill'

    except Exception as e:
        log_fn(f'Stage 3.6 FluxFill repair failed — {e} — falling back to cv2')
        return _repair_cv2(image_path, mask, log_fn)


# ── ComfyUI backend (Tier 2 alternative) ──────────────────────────────────────


def _repair_via_comfyui(
    image_path: str,
    mask: np.ndarray,
    prompt: str,
    log_fn: Callable[[str], None],
) -> tuple[str | None, str]:
    """Submit the flux_fill_inpaint workflow to ComfyUI. Mask is written to
    ComfyUI's input dir as PNG. Returns (out_path, 'flux_fill_comfy') or
    (None, 'flux_fill_comfy') on failure so caller can fall through."""
    try:
        src_name = _comfy.stage_input_image(image_path)
        mask_path = os.path.join(_comfy.COMFY_INPUT, f'mask_{src_name}')
        cv2.imwrite(mask_path, mask)
        mask_name = os.path.basename(mask_path)

        repair_prompt = (
            prompt.split(',')[0].strip() + ', '
            'correct human anatomy, natural hands with exactly 5 fingers, '
            'realistic proportions, no deformities, photorealistic'
        )[:300]

        workflow = _comfy.load_workflow('flux_fill_inpaint')
        outputs = _comfy.submit(
            workflow,
            overrides={
                '15': {'image': src_name},
                '16': {'image': mask_name},
                '20': {'text': repair_prompt},
                '31': {'seed': 42, 'steps': 20},
            },
        )
        if not outputs:
            log_fn('Stage 3.6: ComfyUI returned no output files')
            return None, 'flux_fill_comfy'

        out_path = _repaired_path(image_path, 'r3f')
        Image.open(outputs[0]).convert('RGB').save(out_path, 'JPEG', quality=92)
        return out_path, 'flux_fill_comfy'

    except Exception as exc:
        log_fn(f'Stage 3.6 ComfyUI repair failed: {exc}')
        return None, 'flux_fill_comfy'


def _can_use_qwen_inpaint(log_fn: Callable[[str], None]) -> bool:
    """Apache-2.0 InstantX Qwen inpaint via ComfyUI — the licence-clean Tier 2
    (2026-08-09, replaces NC FLUX-Fill as the quality repair engine)."""
    if _comfy is None or not _comfy.is_enabled() or not _comfy.server_reachable():
        return False
    _root = str(paths.ZYG_COMFY_ROOT / 'models')
    ok = os.path.isfile(
        os.path.join(_root, 'controlnet', 'Qwen-Image-InstantX-ControlNet-Inpainting.safetensors')
    ) and os.path.isfile(os.path.join(_root, 'diffusion_models', 'qwen_image_2512_fp8_e4m3fn.safetensors'))
    if not ok:
        log_fn('Stage 3.6: Qwen inpaint stack incomplete — falling back')
    return ok


def _repair_via_qwen_comfyui(
    image_path: str,
    mask: np.ndarray,
    prompt: str,
    log_fn: Callable[[str], None],
) -> tuple[str | None, str]:
    """Submit the hand_fixer_qwen_inpaint graph (Qwen-Image-2512 + InstantX CN,
    both Apache-2.0). Returns (out_path, 'qwen_inpaint_comfy') or (None, ...)."""
    try:
        src_name = _comfy.stage_input_image(image_path)
        mask_path = os.path.join(_comfy.COMFY_INPUT, f'mask_{src_name}')
        cv2.imwrite(mask_path, mask)

        repair_prompt = (
            prompt.split(',')[0].strip() + ', '
            'a person with correct human anatomy, natural hands with exactly five fingers, '
            'realistic proportions, photographic detail'
        )[:300]

        workflow = _comfy.load_workflow('hand_fixer_qwen_inpaint')
        outputs = _comfy.submit(
            workflow,
            overrides={
                '14': {'image': src_name},
                '46': {'image': os.path.basename(mask_path)},
                '20': {'text': repair_prompt},
                '31': {'seed': 42, 'steps': 20},
            },
        )
        if not outputs:
            log_fn('Stage 3.6: Qwen inpaint returned no output files')
            return None, 'qwen_inpaint_comfy'
        out_path = _repaired_path(image_path, 'rqi')
        Image.open(outputs[0]).convert('RGB').save(out_path, 'JPEG', quality=92)
        return out_path, 'qwen_inpaint_comfy'
    except Exception as exc:
        log_fn(f'Stage 3.6 Qwen inpaint repair failed: {exc}')
        return None, 'qwen_inpaint_comfy'


# ── Helpers ───────────────────────────────────────────────────────────────────


def _repaired_path(original: str, suffix: str) -> str:
    base, ext = os.path.splitext(original)
    return f'{base}_{suffix}{ext}'
