# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
scene_still_helpers.py
----------------------
Stage 3.5 storyteller stills: LoRA load, scene QC, sharpening, seeds.
"""

from __future__ import annotations

import os
from typing import Callable
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


LogFn = Callable[[str], None]

# Laplacian sharpness — animated / soft styles tolerate lower variance.
_STYLE_SHARP_MULT: dict[str, float] = {
    'animated': 0.30,  # 3D-toon (DynaVision) — flat-shaded regions lower Laplacian
    'disney': 0.40,
    'anime': 0.45,
    'cinematic': 0.50,
    '3d_render': 0.55,
    'art': 0.60,
    'filmic': 0.65,
    'realism': 1.0,
    'scenery': 0.70,
    'mjv6': 0.65,
}


def scene_qc_thresholds(
    visual_style: str,
    *,
    lora_active: bool = True,
) -> tuple[float, float]:
    """Return (min_brightness, min_sharpness) for the visual style."""
    min_bright = float(os.environ.get('ZYG_SCENE_MIN_BRIGHT', '28'))
    base_sharp = float(os.environ.get('ZYG_SCENE_MIN_SHARP', '45'))
    mult = _STYLE_SHARP_MULT.get((visual_style or '').strip().lower(), 0.75)
    if not lora_active:
        mult *= float(os.environ.get('ZYG_SCENE_NO_LORA_SHARP_MULT', '0.40'))
    return min_bright, max(8.0, base_sharp * mult)


def scene_generation_seed(path: str, scene_index: int = 0, attempt: int = 0) -> int:
    """Stable but unique seed per scene path, retry attempt, and scene index."""
    base = hash(path) % (2**31)
    return int((base + attempt * 7919 + scene_index * 104729) % (2**31))


def _flux_adapter_names(pipe) -> list[str]:
    names: list[str] = []
    try:
        listed = pipe.get_list_adapters()
        if isinstance(listed, dict):
            for v in listed.values():
                if isinstance(v, list):
                    names.extend(v)
                elif isinstance(v, str):
                    names.append(v)
        elif isinstance(listed, (list, tuple)):
            names.extend(listed)
    except Exception as _exc:
        _zyg_log.debug('list_adapters probe failed, adapter names unknown: %s', _exc)
    try:
        active = pipe.get_active_adapters()
        if active:
            if isinstance(active, (list, tuple)):
                names.extend(active)
            else:
                names.append(str(active))
    except Exception as _exc:
        _zyg_log.debug('active_adapters probe failed, adapter names unknown: %s', _exc)
    out: list[str] = []
    seen: set[str] = set()
    for n in names:
        s = str(n).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _normalize_simpletuner_lora(path: str) -> dict | None:
    """Load safetensors and remap SimpleTuner keys to diffusers LoRA layout."""
    try:
        import safetensors.torch as st
    except ImportError:
        return None
    if not os.path.isfile(path):
        return None
    try:
        raw = st.load_file(path)
        return {k.replace('.lora.down.', '.lora_A.').replace('.lora.up.', '.lora_B.'): v for k, v in raw.items()}
    except Exception:
        return None


def _lora_candidate_paths(lora_path: str) -> list[str]:
    """Expand checkpoint file to related safetensors in the same tree."""
    paths: list[str] = []
    if not lora_path:
        return paths
    if os.path.isfile(lora_path):
        paths.append(lora_path)
        root = os.path.dirname(lora_path)
        for name in (
            'pytorch_lora_weights.safetensors',
            'adapter_model.safetensors',
            'lora.safetensors',
        ):
            p = os.path.join(root, name)
            if os.path.isfile(p) and p not in paths:
                paths.append(p)
        # checkpoint-XXXX/adapter_model.safetensors next to file
        parent = os.path.dirname(root)
        for name in ('pytorch_lora_weights.safetensors', 'adapter_model.safetensors'):
            p = os.path.join(parent, name)
            if os.path.isfile(p) and p not in paths:
                paths.append(p)
    elif os.path.isdir(lora_path):
        for dirpath, _, files in os.walk(lora_path):
            for fn in files:
                if fn.endswith('.safetensors'):
                    paths.append(os.path.join(dirpath, fn))
    return paths


def flux_load_character_lora(
    pipe,
    lora_path: str,
    log_fn: LogFn | None = None,
    *,
    scale: float = 0.8,
    adapter_name: str = 'char_lora',
) -> bool:
    """
      Load a character LoRA onto a FLUX diffusers pipeline with retries and
    SimpleTuner key normalization. Returns True when adapters are active.
    """
    log = log_fn or (lambda m: None)
    if not lora_path or pipe is None:
        return False

    try:
        if hasattr(pipe, 'unload_lora_weights'):
            pipe.unload_lora_weights()
    except Exception as _exc:
        _zyg_log.warning('previous LoRA unload failed, stale adapters may remain on the pipeline: %s', _exc)

    candidates = _lora_candidate_paths(lora_path)
    if not candidates:
        log(f'Character LoRA path not found: {lora_path}')
        return False

    last_err = ''
    for path in candidates:
        tries: list[tuple[str, str | dict, str | None]] = [
            ('file_named', path, adapter_name),
            ('file_default', path, None),
        ]
        norm = _normalize_simpletuner_lora(path)
        if norm:
            tries.append(('simpletuner_dict', norm, adapter_name))
            tries.append(('simpletuner_default', norm, None))

        for label, payload, adapter in tries:
            try:
                if isinstance(payload, dict):
                    pipe.load_lora_weights(payload, adapter_name=adapter or adapter_name)
                elif adapter:
                    pipe.load_lora_weights(payload, adapter_name=adapter)
                else:
                    pipe.load_lora_weights(payload)
                names = _flux_adapter_names(pipe)
                if not names:
                    last_err = f'{label}: no adapters registered after load'
                    continue
                use = adapter if adapter and adapter in names else names[0]
                pipe.set_adapters([use], adapter_weights=[scale])
                log(f'Character LoRA loaded ✓ ({os.path.basename(path)}, adapter={use}, via {label})')
                return True
            except Exception as exc:
                last_err = f'{label}: {exc}'
                try:
                    pipe.unload_lora_weights()
                except Exception as _exc:
                    _zyg_log.debug('LoRA unload after the failed attempt skipped: %s', _exc)

    log(f'LoRA load failed after {len(candidates)} path(s) — {last_err}')
    return False


def cuda_free_gb() -> float:
    try:
        import torch

        if torch.cuda.is_available():
            return torch.cuda.mem_get_info(0)[0] / 1e9
    except Exception as _exc:
        _zyg_log.debug('cuda free memory unavailable, reporting 0.0: %s', _exc)
    return 0.0


def sharpen_image_file(path: str, amount: float = 1.35) -> bool:
    """Mild unsharp mask to recover edge contrast before QC."""
    try:
        from PIL import Image, ImageFilter

        _, lap_before = scene_quality_metrics(path)
        img = Image.open(path).convert('RGB')
        sharp = img.filter(
            ImageFilter.UnsharpMask(
                radius=1.2,
                percent=int(amount * 100),
                threshold=2,
            )
        )
        sharp.save(path)
        _, lap_after = scene_quality_metrics(path)
        return lap_after >= lap_before * 0.85
    except Exception:
        return False


def scene_quality_metrics(img_path: str, normalize: bool = True) -> tuple[float, float]:
    """Return (mean_brightness, laplacian_variance).

    2026-07-24 r3: sharpness is judged at a fixed 512px long side. Laplacian
    variance shrinks as render resolution grows (the same crisp content
    measures ~13 at 1280×720 vs ~36 at 512px), so the historical thresholds —
    calibrated on 512px renders — would blur-reject every fair native-720p
    frame. Downscaling to the calibration scale keeps thresholds valid for
    all render sizes (512px legacy frames are untouched). Callers whose
    thresholds were tuned on raw native-resolution values (post-inpaint
    sharpen gate) pass normalize=False.
    """
    import numpy as np
    from PIL import Image

    _im = Image.open(img_path).convert('RGB')
    if normalize and max(_im.size) > 512:
        _r = 512.0 / max(_im.size)
        _im = _im.resize(
            (max(1, round(_im.width * _r)), max(1, round(_im.height * _r))),
            Image.LANCZOS,
        )
    arr = np.array(_im, dtype=np.float32)
    brightness = float(arr.mean())
    gray = arr.mean(axis=2)
    lap_var = float(
        np.var(gray[1:-1, 1:-1] - 0.25 * (gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:]))
    )
    return brightness, lap_var


def greybox_likelihood(img_path: str) -> float:
    """
    Heuristic 0..1 — high score suggests primitive / untextured greybox renders.
    Used to reject mannequin-like SDXL failures from Blender img2img anchors.
    """
    try:
        import numpy as np
        from PIL import Image

        arr = np.array(
            Image.open(img_path).convert('RGB').resize((320, 180)),
            dtype=np.float32,
        )
        q = (arr // 36).astype(np.int32)
        packed = q[:, :, 0] * 961 + q[:, :, 1] * 31 + q[:, :, 2]
        n_unique = len(np.unique(packed))
        n_pix = packed.size
        few_colors = 1.0 - min(1.0, n_unique / max(32, n_pix * 0.12))
        low_variance = 1.0 - min(1.0, float(arr.std()) / 42.0)
        return 0.55 * few_colors + 0.45 * low_variance
    except Exception:
        return 0.0


def scene_quality_check(
    img_path: str,
    visual_style: str,
    *,
    hand_qa_fn=None,
    lora_active: bool = True,
    check_greybox: bool = True,
) -> tuple[bool, str]:
    """
    Brightness + sharpness + optional hand QA + optional greybox reject.
    Returns (ok, reason_code) where reason_code is 'ok', 'dark', 'blur', 'hands', or 'greybox'.
    """
    min_bright, min_sharp = scene_qc_thresholds(visual_style, lora_active=lora_active)
    try:
        brightness, lap_var = scene_quality_metrics(img_path)
    except Exception:
        return True, 'ok'

    if check_greybox:
        _gb = greybox_likelihood(img_path)
        _gb_max = float(os.environ.get('ZYG_SCENE_MAX_GREYBOX', '0.65'))
        if _gb >= _gb_max:
            return False, 'greybox'

    if brightness < min_bright:
        return False, 'dark'
    if lap_var < min_sharp:
        return False, 'blur'
    if hand_qa_fn is not None:
        hand_s, _issues = hand_qa_fn(img_path)
        # r4: None = QC unavailable — unknown must not gate (and must never
        # count as clean either; callers record availability separately).
        # Strict threshold 0.5 (calibrated on run 030bab9c): only SEVERE hand
        # failures (0.10-class blobs/multiple defects) fail strict QC and feed
        # rescue/failure accounting. Single-flagged-hand frames (0.55) pass —
        # the fixer still improves them and they surface as an informational
        # degraded note, but a watchable video must not FAIL over them
        # (030bab9c: 8/25 single-flag rescues → 40% → spurious job failure).
        _hand_strict = float(os.environ.get('ZYG_HAND_QC_STRICT', '0.5'))
        if hand_s is not None and hand_s < _hand_strict:
            return False, 'hands'
    return True, 'ok'


def scene_qc_rank_score(
    img_path: str,
    visual_style: str,
    *,
    hand_qa_fn=None,
    lora_active: bool = True,
) -> float:
    """Higher is better — for best-of-N selection when strict QC cannot pass."""
    ok, reason = scene_quality_check(
        img_path,
        visual_style,
        hand_qa_fn=hand_qa_fn,
        lora_active=lora_active,
    )
    if not ok and reason in ('dark', 'greybox'):
        return -100.0
    try:
        brightness, lap_var = scene_quality_metrics(img_path)
    except Exception:
        return -50.0
    if lap_var < 5.0:
        # 2026-07-24 r3: a defocused/featureless frame must never be
        # rescue-eligible. Run dd36662e's scene_000 (smooth orange gradient,
        # lap_var 0.0) evaded the greybox/dark rejects — high colour variance,
        # brightness 107 — and brightness + the no-hands bonus alone produced
        # a positive rank (1.4), so the best-attempt rescue shipped it as the
        # video's opening frame. Content-free is unrankable, same as greybox.
        return -100.0
    _gb = greybox_likelihood(img_path)
    hand_bonus = 0.0
    if hand_qa_fn is not None:
        _hand_val = hand_qa_fn(img_path)[0]
        # r4: unknown (None) earns no bonus — the old 1.0-on-error scorer
        # handed every frame +5 including the person-free blob.
        hand_bonus = (_hand_val * 5.0) if _hand_val is not None else 0.0
    base = lap_var + brightness * 0.08 + hand_bonus
    # 2026-07-24 fix: cap the greybox penalty at 90% of the positive score. The
    # flat ×80 term drove soft-but-real renders (lap_var 1–12) far below zero, so
    # the best-attempt rescue never engaged and scenes shipped as reference-photo
    # tints instead (Runa job 10c84d83: 17/25 frames). Detected greybox/dark still
    # returns -100 above; this cap only orders *plausible* frames.
    return base - min(_gb * 80.0, base * 0.9)


def log_scene_qc_failure(
    log_fn: LogFn,
    img_path: str,
    visual_style: str,
    reason: str,
    hand_score: float | None = None,
    hand_issues: list | None = None,
) -> None:
    """Emit a precise QC log line (blur vs dark vs hands)."""
    min_bright, min_sharp = scene_qc_thresholds(visual_style, lora_active=True)
    base = os.path.basename(img_path)
    try:
        brightness, lap_var = scene_quality_metrics(img_path)
    except Exception:
        brightness, lap_var = 0.0, 0.0

    if reason == 'blur':
        log_fn(f'QC fail (blur): sharp={lap_var:.1f} (min {min_sharp:.1f}) brightness={brightness:.1f} → {base}')
    elif reason == 'dark':
        log_fn(f'QC fail (too dark): brightness={brightness:.1f} (min {min_bright:.0f}) sharp={lap_var:.1f} → {base}')
    elif reason == 'hands':
        log_fn(
            f'QC fail (hands): score='
            f'{"n/a" if hand_score is None else f"{hand_score:.2f}"} '
            f'issues={hand_issues or []} → {base}'
        )
    elif reason == 'greybox':
        try:
            _gb = greybox_likelihood(img_path)
        except Exception:
            _gb = 1.0
        log_fn(
            f'QC fail (greybox): likelihood={_gb:.2f} '
            f'(max {float(os.environ.get("ZYG_SCENE_MAX_GREYBOX", "0.65")):.2f}) → {base}'
        )
    else:
        log_fn(f'QC fail ({reason}) → {base}')


def retry_prompt_suffix(attempt: int) -> str:
    """Extra prompt tokens per regeneration attempt."""
    parts = []
    if attempt >= 1:
        parts.append(
            'perfectly formed hands, correct number of fingers, natural human anatomy, no deformities, no extra limbs'
        )
    if attempt >= 1:
        parts.append('tack sharp focus, crisp fine detail, high resolution clarity, sharp edges')
    if attempt >= 2:
        parts.append('ultra sharp, 8k detail, pin-sharp focus, no motion blur, no softness')
    return ', ' + ', '.join(parts) if parts else ''
