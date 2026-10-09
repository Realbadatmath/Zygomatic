# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
video_flux_still_service.py
============================
Shot-aware FLUX still generation helpers for the video pipeline.
"""

from __future__ import annotations

import os
import random
import re
from typing import Any, Callable
from zyg_workflows import paths

_PORTRAIT_SHOTS = frozenset(
    {
        'close-up',
        'close up',
        'extreme close-up',
        'extreme close up',
        'portrait',
        'head shot',
        'headshot',
    }
)
_WIDE_SHOTS = frozenset(
    {
        'wide cinematic shot',
        'wide shot',
        'establishing',
        'overhead drone shot',
        'landscape',
    }
)
_HUMAN_KW = frozenset(
    {
        'woman',
        'man',
        'person',
        'girl',
        'boy',
        'face',
        'portrait',
        'character',
        'lady',
        'female',
        'male',
        'human',
        'people',
    }
)
_SCENE_TYPE_BACKDROP = {
    'character': 'neutral studio backdrop',
    'landscape': '',
    'establishing': '',
    'pure_action': '',
}
_FLUX_DEV_UNET = 'flux1-dev.safetensors'
_FLUX_SCHNELL_UNET = 'flux1-schnell.safetensors'
_QWEN_T2I_UNET = 'qwen_image_2512_fp8_e4m3fn.safetensors'
# 2026-08-09: video anchor stills default to the Apache-2.0 Qwen-Image-2512
# base — while FLUX is licence-paused every anchor still returned
# (False, 'flux_licence_paused'), which silenced the whole video chain.
# ZYG_VIDEO_STILL_FAMILY=flux restores the old behaviour (still pause-gated).
_STILL_FAMILY = os.environ.get('ZYG_VIDEO_STILL_FAMILY', 'qwen').strip().lower() or 'qwen'
_MAX_STILL_ATTEMPTS = int(os.environ.get('ZYG_VIDEO_STILL_MAX_ATTEMPTS', '3'))


def is_portrait_shot(scene_data: dict | None) -> bool:
    sc = scene_data or {}
    shot = str(sc.get('shot_type') or '').strip().lower()
    if any(p in shot for p in _PORTRAIT_SHOTS):
        return True
    st = str(sc.get('scene_type') or '').strip().lower()
    if st == 'character':
        return True
    flux = str(sc.get('flux_prompt') or '').lower()
    return any(k in flux for k in ('close-up', 'close up', 'portrait', 'head shot'))


def is_wide_shot(scene_data: dict | None) -> bool:
    sc = scene_data or {}
    shot = str(sc.get('shot_type') or '').strip().lower()
    if any(w in shot for w in _WIDE_SHOTS):
        return True
    st = str(sc.get('scene_type') or '').strip().lower()
    return st in ('landscape', 'establishing')


def is_human_focus(topic: str, scene_data: dict | None = None) -> bool:
    sc = scene_data or {}
    if str(sc.get('scene_type') or '').lower() == 'character':
        return True
    tl = (topic or '').lower()
    return any(re.search(rf'\b{re.escape(kw)}\b', tl) for kw in _HUMAN_KW)


def flux_dimensions(scene_data: dict | None) -> tuple[int, int, str]:
    """Return (width, height, aspect_ratio_label) for FLUX latents."""
    if is_portrait_shot(scene_data):
        return 768, 1024, '3:4'
    if is_wide_shot(scene_data):
        return 1360, 768, '16:9'
    return 896, 896, '1:1'


def portrait_positive_extra() -> str:
    return (
        'solo subject, one person only, single face, centered composition, '
        'plain dark background, shallow depth of field, no other people'
    )


def build_flux_prompt(
    scene_data: dict,
    directive: str,
    vscfg: dict,
) -> str:
    """Assemble positive FLUX prompt with shot-aware prefix/suffix."""
    flux_core = (
        scene_data.get('flux_prompt')
        or scene_data.get('description')
        or f'{vscfg.get("claude_hint", "cinematic")} scene'
    )
    prefix = vscfg.get('prefix', 'cinematic photograph')
    if is_portrait_shot(scene_data):
        prefix = 'portrait photograph'
        suffix = 'photorealistic, dramatic lighting, shallow depth of field, film grain, single subject'
        flux_core = f'{flux_core}, {portrait_positive_extra()}'
    else:
        suffix = vscfg.get(
            'suffix',
            'photorealistic, dramatic lighting, 16:9 composition, film grain',
        )
    return f'{prefix}, {flux_core}, {suffix}'


def build_regen_boost(reason: str, scene_data: dict, directive: str) -> str:
    """Extra positive tokens when regenerating after QA failure."""
    r = (reason or '').lower()
    parts: list[str] = []
    if is_portrait_shot(scene_data) or is_human_focus(directive, scene_data):
        parts.append(portrait_positive_extra())
    if 'office' in r or 'classroom' in r or 'indoor' in r:
        parts.append('not an office, not a classroom, no desk, no laptop, no window view')
    if 'duplicate' in r or 'face' in r or 'clone' in r:
        parts.append('exactly one person, no duplicates, no twins, no cloned faces')
    if 'creature' in r or 'subject match' in r:
        parts.append(f'{directive[:80]}, subject clearly visible')
    return ', '.join(parts)


def dsl_setting_for_scene(scene_data: dict, directive: str) -> str:
    loc = str(scene_data.get('location') or '').strip()
    if loc:
        return loc[:120]
    st = str(scene_data.get('scene_type') or '').strip().lower()
    if st in _SCENE_TYPE_BACKDROP:
        return _SCENE_TYPE_BACKDROP[st]
    if st == 'character':
        return 'neutral studio backdrop'
    return ''


def dsl_aspect_for_scene(scene_data: dict) -> str:
    _w, _h, label = flux_dimensions(scene_data)
    if label == '16:9':
        return '16:9'
    if label == '3:4':
        return '4:3'
    return '1:1'


def resolve_style_lora(vscfg: dict) -> tuple[str | None, float]:
    """Return (absolute_lora_path, scale) for Comfy style LoRA staging."""
    scale = float(vscfg.get('lora_dir_scale', 0.75))
    lora_dir = vscfg.get('lora_dir')
    if lora_dir:
        path = os.path.join(lora_dir, 'pytorch_lora_weights.safetensors')
        if os.path.isfile(path):
            return path, scale
    lora_file = vscfg.get('lora')
    if lora_file:
        comfy_lora = os.path.join(
            str(paths.ZYG_COMFY_LORA_DIR),
            lora_file,
        )
        if os.path.isfile(comfy_lora):
            return comfy_lora, float(vscfg.get('scale', scale))
    return None, scale


def generation_tiers() -> list[dict[str, Any]]:
    """Hero-still attempts. qwen family (default since 2026-08-09) renders on
    Qwen-Image-2512; flux keeps the historical Dev tiers (licence-gated)."""
    if _STILL_FAMILY == 'qwen':
        return [
            {'unet': _QWEN_T2I_UNET, 'steps': 20, 'cfg': 2.5, 'guidance': 2.5},
            {'unet': _QWEN_T2I_UNET, 'steps': 28, 'cfg': 3.0, 'guidance': 3.0},
        ][:_MAX_STILL_ATTEMPTS]
    return [
        {'unet': _FLUX_DEV_UNET, 'steps': 28, 'cfg': 4.0, 'guidance': 4.0},
        {'unet': _FLUX_DEV_UNET, 'steps': 32, 'cfg': 4.5, 'guidance': 4.5},
    ][:_MAX_STILL_ATTEMPTS]


def apply_dsl_merge(
    prompt: str,
    seed: int,
    steps: int,
    cfg: float,
    dsl_yaml_path: str | None,
    *,
    portrait: bool,
) -> tuple[str, int, int, float]:
    try:
        from zyg_workflows.dsl_runtime import merge_flux_generation_params

        return merge_flux_generation_params(
            prompt,
            seed=seed,
            steps=steps,
            cfg=cfg,
            dsl_yaml_path=dsl_yaml_path,
            is_schnell=False,
            portrait_mode=portrait,
        )
    except Exception:
        return prompt, seed, steps, cfg


def generate_still_with_retries(
    dest_path: str,
    scene_data: dict,
    directive: str,
    visual_style: str,
    vscfg: dict,
    *,
    dsl_yaml_path: str | None,
    char_id: str = '',
    char_pkg: dict | None = None,
    model_family: str = 'flux',
    log_fn: Callable[[str], None] | None = None,
) -> tuple[bool, str]:
    """
    Generate one video still via Comfy with QA between attempts.
    Returns (success, last_backend_label).
    """
    from zyg_workflows import comfy_generation_service as cgs
    from zyg_workflows import video_still_qa_service as vsqa

    log = log_fn or (lambda _m: None)
    if not cgs.is_available():
        return False, 'unavailable'

    width, height, _aspect = flux_dimensions(scene_data)
    flux_hint = scene_data.get('flux_prompt') or scene_data.get('description') or directive
    extra_neg = vsqa.topic_negative_prompt(directive, scene_data, flux_hint)
    style_path, style_scale = resolve_style_lora(vscfg)
    portrait = is_portrait_shot(scene_data)
    tiers = generation_tiers()
    last_backend = 'none'
    _last_reason = ''

    for attempt, tier in enumerate(tiers):
        prompt = build_flux_prompt(scene_data, directive, vscfg)
        if attempt > 0:
            boost = build_regen_boost(_last_reason, scene_data, directive)
            if boost:
                prompt = f'{prompt}, {boost}'

        seed = random.randint(0, 2**32 - 1)
        steps = int(tier['steps'])
        cfg = float(tier['cfg'])
        prompt, seed, steps, cfg = apply_dsl_merge(
            prompt,
            seed,
            steps,
            cfg,
            dsl_yaml_path,
            portrait=portrait,
        )

        log(f'VideoFLUX attempt {attempt + 1}/{len(tiers)}: {width}×{height} dev steps={steps} cfg={cfg} seed={seed}')
        ok, backend = cgs.generate_still(
            dest_path,
            prompt,
            width=width,
            height=height,
            steps=steps,
            cfg=cfg,
            seed=seed,
            character_package=char_pkg,
            char_id=char_id,
            model_family=(_STILL_FAMILY if _STILL_FAMILY == 'qwen' and model_family == 'flux' else model_family),
            extra_negative=extra_neg,
            style_lora_path=style_path,
            style_lora_scale=style_scale,
            force_unet=tier['unet'],
            flux_guidance=float(tier['guidance']),
            log_fn=log,
        )
        last_backend = backend
        if not ok:
            log(f'VideoFLUX attempt {attempt + 1}: ComfyGen failed ({backend})')
            continue

        # QA retries disabled — return immediately on first successful generation
        log(f'VideoFLUX attempt {attempt + 1}: generated ({backend})')
        return True, backend

    return False, last_backend
