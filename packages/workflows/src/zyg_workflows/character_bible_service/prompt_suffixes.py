# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Negative prompts, scholarly anatomy and the storyteller prompt suffixes."""

from __future__ import annotations

import os
from typing import Any, Optional
import logging as _zyg_logging


from .references import (
    _env_on,
)
from .appearance_negatives import (
    PHOTOREAL_SKIN_NEG,
    age_prompt_phrase,
    describe_skin_tone,
    is_minor_identity,
    minor_safety_negatives,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.character_bible_service')


_SOLO_SUBJECT_NEG = (
    'multiple people, two people, three people, duplicate, twins, crowd, '
    'group shot, character sheet, lineup, extra person, clone, collage'
)
_PREVIEW_SCENE_NEG = (
    'office, classroom, desk, table, chair, window, sunset, sunrise, balcony, '
    'sea, ocean, horizon, skyscape, papers, books, laptop, furniture, outdoor, '
    'cityscape, interior clutter'
)
_ANATOMY_NEG = (
    'extra legs, extra arms, fused limbs, malformed hands, missing fingers, '
    'extra fingers, three fingers, four fingers, six fingers, 3 fingers, '
    'bad anatomy, deformed limbs, merged fingers, claw hands, '
    'asymmetric earrings, mismatched jewelry, duplicate earrings'
)

# Scholarly Stage 3.5 — first-pass anatomy (positive phrasing; guidance_scale > 0 on anatomy shots).
SCHOLARLY_ANATOMY_POSITIVE = (
    'anatomically correct human figure, exactly five fingers on each visible hand, '
    'natural relaxed hand pose with separated fingers, correct wrist and knuckle alignment, '
    'symmetrical facial features, realistic bone structure, photorealistic skin texture'
)

# Default ControlNet Union pose scale for scholarly anatomy (tuned for first-pass QA pass).
SCHOLARLY_CN_CONDITIONING_SCALE = 0.78


def apply_scholarly_conditioning_defaults(package: dict[str, Any] | None) -> dict[str, Any] | None:
    """Merge Tier-1 scholarly defaults into character package conditioning (non-destructive)."""
    if not package:
        return package
    cond = package.setdefault('conditioning', {})
    cond.setdefault('hand_detail_pass', True)
    cond.setdefault('hand_detail_strength', 0.42)
    cond.setdefault('controlnet_conditioning_scale', SCHOLARLY_CN_CONDITIONING_SCALE)
    cond.setdefault('anatomy_positive', SCHOLARLY_ANATOMY_POSITIVE)
    return package


def scholarly_anatomy_prompt_suffix(package: dict[str, Any] | None = None) -> str:
    """Extra positive tokens for anatomy-class FLUX slots (attempt #1)."""
    cond = (package or {}).get('conditioning', {}) or {}
    extra = (cond.get('anatomy_positive') or '').strip()
    if extra and extra != SCHOLARLY_ANATOMY_POSITIVE:
        return f'{SCHOLARLY_ANATOMY_POSITIVE}, {extra}'
    return SCHOLARLY_ANATOMY_POSITIVE


def scholarly_controlnet_scale(package: dict[str, Any] | None = None) -> float:
    """Resolve ControlNet conditioning scale from package or scholarly default."""
    if package:
        cond = package.get('conditioning', {}) or {}
        raw = cond.get('controlnet_conditioning_scale')
        if raw is not None:
            try:
                return max(0.55, min(0.95, float(raw)))
            except (TypeError, ValueError) as _exc:
                _zyg_log.debug('conditioning scale in the package not numeric, trying the env: %s', _exc)
    env = os.environ.get('ZYG_CN_CONDITIONING_SCALE', '').strip()
    if env:
        try:
            return max(0.55, min(0.95, float(env)))
        except ValueError as _exc:
            _zyg_log.debug('ZYG_CN_CONDITIONING_SCALE not numeric, using the default: %s', _exc)
    return SCHOLARLY_CN_CONDITIONING_SCALE


def scholarly_flux_negative_prompt(package: dict[str, Any] | None = None) -> str:
    """Strong anatomy negative for diffusers (used when guidance_scale > 0)."""
    if package:
        return negative_prompt_for_package(package)
    return (
        'blurry, low quality, deformed face, bad anatomy, extra fingers, extra limbs, '
        'mutated hands, watermark, text, ' + _ANATOMY_NEG
    )


def negative_prompt_for_package(
    package: dict[str, Any] | None,
    *,
    studio_preview: bool = False,
    solo_subject: bool = True,
) -> str:
    """Negative-prompt string for ComfyUI node 21 (always populated).

    ``studio_preview`` gates ``_PREVIEW_SCENE_NEG`` (the office/window/
    furniture/outdoor environment ban). It exists to keep character PREVIEWS
    on a clean studio background — appended unconditionally it reached every
    storyteller scene render, where it banned the very settings the scene
    prompts asked for (run dd36662e: bed/kitchen/office scenes all collapsed
    to the studio portrait their init image showed).

    ``solo_subject`` (2026-08-25, P-06) gates ``_SOLO_SUBJECT_NEG`` ("multiple
    people, two people, crowd, group shot, character sheet, …"). It exists for
    single-character renders; appended unconditionally it reached every
    package-less documentary still (run docsmoke-b58104c4, all 3 slots). On
    schnell (guidance 0) that was inert; on Qwen-Image at cfg 2.5 the negative
    is live and pulls against prompts that ask for crowds, "three human
    figures" or plague streets. Pass ``solo_subject=False`` for scene stills
    that are not about one locked character.
    """
    if not package:
        base = 'blurry, low quality, deformed face, bad anatomy, extra fingers, extra limbs, watermark, text'
    else:
        cond = package.get('conditioning', {}) or {}
        neg = (cond.get('negative_prompt') or '').strip()
        if neg:
            base = neg
        else:
            base = (
                'blurry, low quality, low resolution, jpeg artifacts, '
                'deformed face, bad anatomy, extra fingers, extra limbs, '
                'mutated hands, asymmetric eyes, watermark, text, signature'
            )
    low = base.lower()
    if solo_subject and 'multiple people' not in low and 'character sheet' not in low:
        base = f'{base}, {_SOLO_SUBJECT_NEG}'
    if studio_preview and 'office' not in low and 'desk' not in low:
        base = f'{base}, {_PREVIEW_SCENE_NEG}'
    if 'extra legs' not in low:
        base = f'{base}, {_ANATOMY_NEG}'
    if package:
        _rs = ((package.get('style_profile') or {}).get('render_style') or '').strip().lower()
        if _rs == 'photorealistic' and 'plastic skin' not in low:
            base = f'{base}, {PHOTOREAL_SKIN_NEG}'
    # 2026-07-31: MINOR SAFETY — unconditional, deliberately NOT gated on
    # studio_preview. build_locked_negative_prompt's whole age/hair/skin block
    # sits behind `if studio_preview and character_package:` and the storyteller
    # renders with the default studio_preview=False, so scene renders of an
    # under-18 character carried ZERO age defence: a 12-year-old's only
    # protection was a hand-typed clause in his bible negative_prompt, and any
    # character built through the normal flow had none at all. Appended here so
    # every caller of this function (preview AND scene) inherits it.
    # ZYG_MINOR_AGE_LOCK=0 restores the pre-2026-07-31 behaviour.
    if package:
        _minor_neg = minor_safety_negatives(package.get('identity') or {})
        if _minor_neg:
            # Exact-token dedup (not substring): 'adult man' already in the
            # bible must not suppress the stronger bare 'adult' token.
            _have = {t.strip().lower() for t in base.split(',')}
            _add = [t for t in (x.strip() for x in _minor_neg.split(',')) if t and t.lower() not in _have]
            if _add:
                base = f'{base}, ' + ', '.join(_add)
    return base


def preview_studio_suffix(package: dict[str, Any] | None) -> str:
    """Background tokens for character preview stills (empty stage, no props)."""
    style = (package or {}).get('style_profile', {}) or {}
    lp = (style.get('lighting_profile') or '').strip()
    # Directional key with visible shadow modelling instead of the old
    # 'controlled soft key + even fill' — flat even light reads as retouched
    # and hides the skin micro-texture the pipeline is trying to capture.
    bits = [
        'plain neutral gray studio backdrop',
        'seamless empty stage',
        'soft directional studio key light with gentle shadow modelling',
        'natural light falloff',
        'no furniture',
        'no desk',
        'no window',
        'no outdoor scenery',
        'character centered',
    ]
    if lp:
        bits.append(lp)
    return ', '.join(bits)


def quality_suffix_for_package(package: dict[str, Any] | None) -> str:
    """Photographic/illustrative quality booster appended after the scene description."""
    if not package:
        # No package can mean no character in frame (establishing shots) —
        # never request a face here or FLUX conjures a person into the scene.
        return 'highly detailed, sharp focus, natural lighting'
    cond = package.get('conditioning', {}) or {}
    qs = (cond.get('quality_suffix') or '').strip()
    return qs or 'highly detailed, sharp focus on face, natural lighting'


def storyteller_quality_suffix(
    package: dict[str, Any] | None,
    shot_type: str = 'medium',
) -> str:
    """Shot-aware quality booster — avoids face-only 85mm language on medium/wide scenes."""
    # 2026-07-25: animated (SDXL 3D-toon twin) gets a toon quality clause, not
    # the photoreal 'realistic skin, film grain, 85mm' language that fought the
    # 3D-Pixar checkpoint.
    _rs = ((package or {}).get('style_profile') or {}).get('render_style', '')
    if str(_rs).strip().lower() in ('animated', 'toon', 'cartoon', '3d_toon'):
        return (
            '3D Pixar animation style, stylized 3d animated character, cel-shaded, '
            'smooth subsurface shading, natural proportional eyes, realistic eye size, '
            'clean high quality 3d render'
        )
    st = (shot_type or 'medium').lower().replace('_', ' ')
    if 'close' in st or 'extreme' in st:
        return quality_suffix_for_package(package)
    if 'wide' in st or 'establish' in st or 'over-the-shoulder' in st:
        return (
            'cinematic wide composition, environment and subject visible, '
            'natural lighting, sharp focus, realistic textures, film grain'
        )
    return (
        'cinematic medium shot, waist up or full torso in frame, '
        'natural lighting, sharp focus, realistic skin and fabrics, film grain'
    )


def storyteller_face_detail_enabled(
    shot_type: str = 'medium',
    scene_emotion: str = '',
) -> bool:
    """Whether Comfy FaceDetailer second pass should run for this storyteller scene."""
    st = (shot_type or 'medium').lower().replace('_', ' ')
    if any(x in st for x in ('wide', 'establish', 'over-the-shoulder')):
        return False
    if 'close' in st or 'extreme' in st:
        return True
    # Medium shots: skip face crop/inpaint (prevents unwanted ECU)
    return False


def storyteller_identity_snippet(package: dict[str, Any] | None) -> str:
    """Compact identity descriptor for storyteller SCENE prompts.

    The LoRA + trigger token carry most of the identity, but Stage 2b's
    LLM-written prompts routinely re-describe the character generically
    (run dd36662e: box-braided coily-haired Caribbean Runa became a
    'brown-haired girl'), which fights the LoRA in txt2img. This snippet
    re-asserts the load-bearing visual attributes without the full bible
    identity wall (hair structure/colour, eyes, heritage-as-features, skin).

    2026-07-31: it emitted hair / eyes / heritage / skin but NOT age and NOT
    gender — exactly the two attributes that failed when a 12-year-old Dutch boy
    was delivered as an adult woman. Both now lead the snippet (this string is
    also handed to Stage 2b as 'canonical character appearance', so the LLM sees
    the age and gender before it writes a single scene prompt).
    ZYG_STORYTELLER_IDENTITY_AGE=0 restores the pre-2026-07-31 snippet.
    """
    if not package:
        return ''
    ident = package.get('identity', {}) or {}
    parts: list[str] = []
    if _env_on('ZYG_STORYTELLER_IDENTITY_AGE'):
        _gender = str(ident.get('gender') or '').strip()
        _age = ident.get('age')
        _age_r = str(ident.get('age_range') or '').strip()
        # age_prompt_phrase already carries the gendered noun (and, for minors,
        # explicit child/teen proportions); the bare gender token is added only
        # when that phrase does not already contain it.
        _lead = ''
        if _age not in (None, '', 'auto'):
            _lead = age_prompt_phrase(_age, _gender)
        elif _age_r and _gender:
            _lead = f'{_age_r} {_gender}'
        elif _age_r:
            _lead = _age_r
        elif _gender:
            _lead = f'{_gender} character'
        if _lead:
            parts.append(_lead)
        if _gender and _gender.lower() not in _lead.lower():
            parts.append(_gender)
        # Minor lock: age_range can be the ONLY minor signal when age arrives
        # null (the zpub local-fallback path), so re-assert it in the positive.
        if _age in (None, '', 'auto') and is_minor_identity(ident):
            parts.append('child, not an adult, child body proportions')
    hair_bits = [
        b
        for b in (
            ident.get('hair_length'),
            ident.get('hair_texture'),
            ident.get('hair_color'),
        )
        if b
    ]
    hs = ident.get('hair_style')
    if hs:
        hair_bits.append(hs)
    if hair_bits:
        parts.append(' '.join(hair_bits) + ' hair')
    ec = ident.get('eye_color')
    if ec:
        parts.append(f'{ec} eyes')
    heritage = ident.get('ethnic_heritage')
    if heritage:
        # Heritage as FEATURES (2026-07-21) — colour authority stays with skin_tone.
        parts.append(f'{heritage} facial features')
    skin = describe_skin_tone(
        ident.get('skin_tone', ''),
        ident.get('ethnic_heritage', ''),
    )
    if skin:
        parts.append(skin)
    return ', '.join(parts)


def compose_storyteller_render_prompt(
    flux_prompt: str,
    package: dict[str, Any] | None,
    *,
    shot_type: str = 'medium',
    shot_keyword: str = '',
    style_prefix: str = '',
    continuity_prefix: str = '',
    char_extra: str = '',
) -> str:
    """
    Scene-first prompt for storyteller Stage 3.5 (no bible identity wall, no indoor_stage).
    Identity is carried by LoRA + trigger token inside flux_prompt.
    """
    import os as _os_st

    parts: list[str] = []
    if shot_keyword:
        parts.append(shot_keyword.strip(' ,'))
    core = (flux_prompt or '').strip()
    if core:
        parts.append(core)
    if continuity_prefix:
        parts.append(continuity_prefix.strip(' ,'))
    if style_prefix:
        parts.append(style_prefix.strip(' ,'))
    trig = (package or {}).get('trigger_token', '')
    joined = ', '.join(parts)
    if trig and trig not in joined:
        joined = f'{trig}, {joined}'
    qs = storyteller_quality_suffix(package, shot_type)
    if qs:
        joined = f'{joined}, {qs}'
    if char_extra:
        joined = f'{joined}, {char_extra.strip(" ,")}'
    # r3: 1200 → 1400 — the identity snippet rides at the tail via char_extra
    # and was first in line for the slice; T5 handles this comfortably.
    _max = int(_os_st.environ.get('ZYG_STORYTELLER_PROMPT_MAX', '1400'))
    return joined[:_max]


def indoor_style_suffix(package: dict[str, Any] | None) -> str:
    if not package:
        return (
            'indoor cinematic set, photorealistic, consistent environment, no outdoor scenery, no copyrighted landmarks'
        )
    style = package.get('style_profile', {})
    cam = style.get('camera_language', '')
    pal = style.get('color_palette', '')
    bits = [
        'indoor virtual production stage',
        'photorealistic',
        'consistent character identity',
        'no outdoor scenery',
    ]
    if cam:
        bits.append(cam)
    if pal:
        bits.append(pal)
    return ', '.join(bits)


def get_master_reference(package: dict[str, Any] | None) -> Optional[str]:
    if not package:
        return None
    cond = package.get('conditioning', {})
    master = cond.get('master_reference_image')
    if master and os.path.isfile(master):
        return master
    refs = cond.get('ipadapter_reference_images') or []
    for p in refs:
        if p and os.path.isfile(p):
            return p
    return None
