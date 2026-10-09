# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 10 — ControlNet pose conditioning for FLUX.

Uses MediaPipe Holistic to extract body + hand pose from an input image,
renders a pose visualisation (skeleton overlay), and feeds it to
FluxControlNetPipeline for spatially guided generation.

This dramatically improves hand anatomy and body proportions because FLUX
is told exactly where limbs should be — it's not free to invent them.

Architecture
------------
For each anatomy shot in _generate_one():

  1. If a reference pose image exists for this subject → use it directly
  2. Else: generate a canonical standing/action pose from the prompt text
     (stored as a MediaPipe-rendered skeleton) and cache it for the subject
  3. Run FluxControlNetPipeline with the pose image as conditioning

Model
-----
``InstantX/FLUX.1-dev-Controlnet-Union``  (~6.6 GB safetensors)
Union ControlNet supporting multiple modes: canny=0, tile=1, depth=2,
blur=3, pose=4, gray=5, lq=6.  This service uses mode 4 (pose / OpenPose).
Falls back gracefully if weights are not in HF cache.

Usage
-----
    from zyg_workflows import controlnet_service as cns

    # Call once per pipeline run after FLUX is loaded
    cn_pipe = cns.setup(flux_pipe, log_fn=_log)
    if cn_pipe is None:
        # ControlNet not available — use regular flux_pipe
        use_cn = False
    else:
        use_cn = True

    # Inside _generate_one() for anatomy shots:
    if use_cn:
        pose_img = cns.get_pose_image(subject_key, reference_flux_image_path)
        if pose_img is not None:
            cns.controlnet_to_cuda(cn_pipe)
            try:
                result = cn_pipe(prompt=..., control_image=pose_img, ...).images[0]
            finally:
                cns.controlnet_to_cpu(cn_pipe)
        else:
            result = flux_pipe(prompt=...).images[0]

    # Tear down after generation loop
    cns.teardown(cn_pipe, log_fn=_log)
"""

from __future__ import annotations

import os
from typing import Callable

import cv2
import mediapipe as mp
import numpy as np
from PIL import Image

_CN_REPO = 'InstantX/FLUX.1-dev-Controlnet-Union'
_CN_WEIGHT = 'diffusion_pytorch_model.safetensors'
_CN_CONTROL_MODE = 4  # Union mode 4 = pose/OpenPose
_MIN_VRAM_GB = 7.0  # headroom needed when ControlNet temporarily swaps to CUDA per-shot
# Scholarly anatomy first-pass default (was 0.7 — slightly stronger pose/hand structure).
SCHOLARLY_CN_CONDITIONING_SCALE = 0.78

_pose_cache: dict[str, Image.Image] = {}  # subject_key → pose PIL image


# ── Public API ────────────────────────────────────────────────────────────────


def setup(
    flux_pipe,
    log_fn: Callable[[str], None] | None = None,
):
    """Load FluxControlNetPipeline and return it, or None if unavailable."""

    def _log(m: str) -> None:
        if log_fn:
            log_fn(m)

    if not _check_vram(_MIN_VRAM_GB, _log):
        return None

    try:
        from huggingface_hub import try_to_load_from_cache

        cached = try_to_load_from_cache(_CN_REPO, _CN_WEIGHT)
        if cached is None:
            _log(f'Stage 10/ControlNet: {_CN_REPO} not in HF cache — pose conditioning skipped')
            return None
    except Exception:
        return None

    try:
        import torch
        from diffusers import FluxControlNetModel, FluxControlNetPipeline

        _log(f'Stage 10/ControlNet: loading {_CN_REPO} …')
        cn_model = FluxControlNetModel.from_pretrained(
            _CN_REPO,
            torch_dtype=torch.bfloat16,
            local_files_only=True,
            low_cpu_mem_usage=True,
        )
        # ControlNet stays in CPU RAM — moved to CUDA only per shot via
        # controlnet_to_cuda() / controlnet_to_cpu() to avoid OOM alongside FLUX.
        # CRITICAL: pass torch_dtype=torch.bfloat16 to prevent from_pipe() from
        # converting all CUDA components to float32 (its default), which doubles
        # VRAM from 22.5 GB to ~45 GB and causes OOM on every FLUX inference.
        cn_pipe = FluxControlNetPipeline.from_pipe(flux_pipe, controlnet=cn_model, torch_dtype=torch.bfloat16)
        _log('Stage 10/ControlNet: FluxControlNetPipeline ready')
        return cn_pipe
    except Exception as e:
        _log(f'Stage 10/ControlNet: load failed — {e}')
        return None


def teardown(
    cn_pipe,
    log_fn: Callable[[str], None] | None = None,
) -> None:
    """Release ControlNet pipeline resources."""

    def _log(m: str) -> None:
        if log_fn:
            log_fn(m)

    try:
        if cn_pipe is not None:
            import gc
            import torch

            cn_pipe.controlnet.to('cpu')
            del cn_pipe
            gc.collect()
            torch.cuda.empty_cache()
            _pose_cache.clear()
            _log('Stage 10/ControlNet: unloaded')
    except Exception as e:
        _log(f'Stage 10/ControlNet: teardown warning — {e}')


def prepare_flux_for_controlnet(flux_pipe, cn_pipe, log_fn: Callable[[str], None] | None = None) -> None:
    """When ControlNet is active, keep CLIP+T5 on CUDA to avoid encode device mismatch.

    Production Stage 3.5 may keep T5 on CPU for VRAM; parity benchmarks and any run
    that hits ``FluxControlNetPipeline`` device errors should call this after setup.
    """
    if cn_pipe is None or flux_pipe is None:
        return
    try:
        flux_pipe.text_encoder_2.to('cuda')
        if log_fn:
            log_fn('Stage 10/ControlNet: T5-XXL on GPU for ControlNet encode consistency')
    except Exception as exc:
        if log_fn:
            log_fn(f'Stage 10/ControlNet: T5 GPU placement skipped — {exc}')


def controlnet_to_cuda(cn_pipe) -> None:
    """Move ControlNet weights to CUDA immediately before inference."""
    if cn_pipe is not None:
        cn_pipe.controlnet.to('cuda')


def controlnet_to_cpu(cn_pipe) -> None:
    """Move ControlNet weights back to CPU after inference and free the VRAM."""
    if cn_pipe is not None:
        import torch

        cn_pipe.controlnet.to('cpu')
        torch.cuda.empty_cache()


def get_pose_image(
    subject_key: str,
    reference_image_path: str | None,
    *,
    fallback_reference_paths: list[str] | None = None,
) -> Image.Image | None:
    """Return a pose skeleton image for *subject_key*.

    - If a cached pose exists for this subject, return it.
    - If *reference_image_path* is given, extract pose from it and cache.
    - Else tries *fallback_reference_paths* (e.g. character bible portrait) for attempt #1.
    - Otherwise return None.
    """
    if subject_key in _pose_cache:
        return _pose_cache[subject_key]

    _candidates: list[str] = []
    if reference_image_path and os.path.exists(reference_image_path):
        _candidates.append(reference_image_path)
    for _fp in fallback_reference_paths or []:
        if _fp and os.path.exists(_fp) and _fp not in _candidates:
            _candidates.append(_fp)

    for _ref in _candidates:
        pose_img = extract_pose_image(_ref)
        if pose_img is not None:
            _pose_cache[subject_key] = pose_img
            return pose_img
    return None


def extract_pose_image(image_path: str) -> Image.Image | None:
    """Extract a MediaPipe pose skeleton from *image_path* and return it as PIL.

    The skeleton is rendered on a black background so ControlNet sees only
    the structural lines — no colour/texture bleed from the source image.
    """
    try:
        img_bgr = cv2.imread(image_path)
        if img_bgr is None:
            return None
        h, w = img_bgr.shape[:2]
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

        canvas = np.zeros((h, w, 3), dtype=np.uint8)

        mp_hol = mp.solutions.holistic
        mp_drw = mp.solutions.drawing_utils
        mp_sty = mp.solutions.drawing_styles

        with mp_hol.Holistic(
            static_image_mode=True,
            model_complexity=2,
            refine_face_landmarks=True,
            min_detection_confidence=0.4,
        ) as hol:
            res = hol.process(img_rgb)

            # Draw pose skeleton
            if res.pose_landmarks:
                mp_drw.draw_landmarks(
                    canvas,
                    res.pose_landmarks,
                    mp_hol.POSE_CONNECTIONS,
                    landmark_drawing_spec=mp_drw.DrawingSpec(color=(0, 255, 0), thickness=3, circle_radius=4),
                    connection_drawing_spec=mp_drw.DrawingSpec(color=(0, 200, 0), thickness=2),
                )

            # Draw hand skeletons (most critical for anatomy)
            for hand_lms, hand_connections in (
                (res.left_hand_landmarks, mp_hol.HAND_CONNECTIONS),
                (res.right_hand_landmarks, mp_hol.HAND_CONNECTIONS),
            ):
                if hand_lms:
                    mp_drw.draw_landmarks(
                        canvas,
                        hand_lms,
                        hand_connections,
                        landmark_drawing_spec=mp_drw.DrawingSpec(color=(255, 100, 0), thickness=2, circle_radius=3),
                        connection_drawing_spec=mp_drw.DrawingSpec(color=(200, 80, 0), thickness=1),
                    )

            # Draw face mesh (face structure reference for IPAdapter)
            if res.face_landmarks:
                mp_drw.draw_landmarks(
                    canvas,
                    res.face_landmarks,
                    mp_hol.FACEMESH_CONTOURS,
                    landmark_drawing_spec=None,
                    connection_drawing_spec=mp_sty.get_default_face_mesh_contours_style(),
                )

        if canvas.max() == 0:
            return None  # No landmarks detected

        return Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))

    except Exception:
        return None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _check_vram(min_gb: float, log_fn: Callable[[str], None]) -> bool:
    try:
        import torch

        if not torch.cuda.is_available():
            return False
        # mem_get_info() reads driver-level free bytes — the only accurate measure.
        # memory_allocated() only counts live PyTorch tensors and misses the reserved
        # pool, giving an inflated "free" number on a nearly-full card.
        free_bytes, _ = torch.cuda.mem_get_info(0)
        free_gb = free_bytes / 1024**3
        if free_gb < min_gb:
            log_fn(f'Stage 10/ControlNet: only {free_gb:.1f} GB free (driver) — skipping')
            return False
        return True
    except Exception:
        return False
