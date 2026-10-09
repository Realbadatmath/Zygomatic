# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
animal_lora_service.py
======================
Animal Creation pipeline — LoRA profile registry and profile routing.

Cloned from creature_lora_service.py and adapted human/creature -> animal.
Animals are faceless-safe quadrupeds: NEVER InstantID / face-lock. The three
render profiles map onto the confirmed design:
  * real_wildlife  — 2D Flux photoreal (default)
  * arcane_animal  — Arcane restyle (style_profile.restyle='arcane_animation')
  * stylized_toon  — 3D SDXL animated toon twin

The profile dicts preserve the creature template's hyperparameter shape exactly
(label, lora_file, trigger, scale, claude_hint, negative_extra) — the trainer /
lora_trainer_service reads steps/lr/rank from env, not from these dicts — plus a
single animal-specific 'restyle' key required by the Arcane design.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from zyg_workflows import paths

ANIMAL_LORA_DIR = Path(paths.ZYG_ANIMAL_LORA_DIR)

ANIMAL_LORA_PROFILES: dict[str, dict] = {
    'real_wildlife': {
        'label': 'Real Wildlife / NatGeo cinematic',
        'lora_file': 'flux_cinematic_wildlife.safetensors',
        'trigger': 'ultra-realistic cinematic photography style',
        'scale': 0.75,
        'restyle': None,
        'claude_hint': (
            'National Geographic wildlife documentary photography — sharp fur/feather detail, '
            'natural habitat, golden-hour or overcast natural light, no humans'
        ),
        'negative_extra': (
            'human, person, man, woman, people, portrait, office, classroom, '
            'cartoon, anime, deformed anatomy, extra limbs, watermark'
        ),
    },
    'arcane_animal': {
        'label': 'Arcane-styled animal (painterly 2D animation)',
        'lora_file': 'flux_arcane_animation.safetensors',
        'trigger': 'arcane animation style, painterly 2D animated look',
        'scale': 0.80,
        'restyle': 'arcane_animation',
        'claude_hint': (
            'Arcane / League-of-Legends animated series aesthetic — hand-painted textured fur, '
            'expressive stylized anatomy, dramatic rim light and atmosphere, cinematic 2D '
            'animation still, single animal subject, no humans'
        ),
        'negative_extra': (
            'human, person, photoreal photograph, office, chibi, flat vector, '
            'deformed limbs, extra legs, watermark, blurry'
        ),
    },
    'stylized_toon': {
        'label': '3D animated toon (SDXL twin)',
        'lora_file': 'sdxl_animated_toon.safetensors',
        'trigger': 'stylized 3D animated toon render',
        'scale': 0.70,
        'restyle': None,
        'claude_hint': (
            'Polished 3D-animated feature-film creature — appealing toon proportions, soft '
            'sub-surface fur shading, cinematic key light, single animal subject, clean '
            'background, no humans'
        ),
        'negative_extra': (
            'human, person, photoreal photograph, live-action, office, watermark, '
            'deformed limbs, extra legs, broken anatomy, blurry'
        ),
    },
}

_ARCANE_KW = frozenset(
    {
        'arcane',
        'painterly',
        'animated',
        'animation',
        'stylised',
        'stylized',
    }
)
_TOON_KW = frozenset(
    {
        'toon',
        'cartoon',
        'pixar',
        'dreamworks',
        '3d',
        'cgi',
        'render',
        'rendered',
    }
)


def lora_path(profile_key: str) -> str | None:
    prof = ANIMAL_LORA_PROFILES.get(profile_key)
    if not prof:
        return None
    path = ANIMAL_LORA_DIR / prof['lora_file']
    return str(path) if path.is_file() and path.stat().st_size > 1_000_000 else None


def all_profiles_ready() -> bool:
    return all(lora_path(k) for k in ANIMAL_LORA_PROFILES)


def missing_profiles() -> list[str]:
    return [k for k in ANIMAL_LORA_PROFILES if not lora_path(k)]


def resolve_profile(key: str | None) -> dict:
    """Return the profile dict for an animal render key or free-text topic.

    Accepts either an explicit profile key ('real_wildlife' | 'arcane_animal' |
    'stylized_toon') or a free-text topic which is keyword-routed. Always returns
    a profile dict, defaulting to the photoreal 'real_wildlife'.
    """
    if key and key in ANIMAL_LORA_PROFILES:
        return ANIMAL_LORA_PROFILES[key]

    tl = (key or '').lower()
    tokens = set(re.findall(r'[a-z0-9]+', tl))
    if tokens & _ARCANE_KW or any(re.search(rf'\b{re.escape(kw)}\b', tl) for kw in _ARCANE_KW):
        return ANIMAL_LORA_PROFILES['arcane_animal']
    if tokens & _TOON_KW or any(re.search(rf'\b{re.escape(kw.strip())}\b', tl) for kw in _TOON_KW):
        return ANIMAL_LORA_PROFILES['stylized_toon']
    return ANIMAL_LORA_PROFILES['real_wildlife']


def resolve_profile_key(key: str | None) -> str:
    """Companion to resolve_profile: return the resolved profile KEY."""
    prof = resolve_profile(key)
    for k, v in ANIMAL_LORA_PROFILES.items():
        if v is prof:
            return k
    return 'real_wildlife'


def build_animal_prompt(flux_prompt: str, profile: dict) -> str:
    trigger = (profile.get('trigger') or '').strip()
    base = (flux_prompt or '').strip()
    if trigger and trigger.lower() not in base.lower():
        return f'{trigger}, {base}'
    return base


def status_report(log_fn: Callable[[str], None] | None = None) -> bool:
    log = log_fn or (lambda _m: None)
    ok = True
    for key, prof in ANIMAL_LORA_PROFILES.items():
        path = ANIMAL_LORA_DIR / prof['lora_file']
        if path.is_file() and path.stat().st_size > 1_000_000:
            log(f'AnimalLoRA OK {key}: {path.name} ({path.stat().st_size // 1_000_000} MB)')
        else:
            log(f'AnimalLoRA MISSING {key}: {path}')
            ok = False
    return ok
