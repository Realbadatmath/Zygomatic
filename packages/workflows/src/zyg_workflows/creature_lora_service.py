# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
creature_lora_service.py
========================
Creature Creation pipeline — LoRA profile registry and topic routing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from zyg_workflows import paths

CREATURE_LORA_DIR = Path(paths.ZYG_CREATURE_LORA_DIR)

CREATURE_LORA_PROFILES: dict[str, dict] = {
    'real_wildlife': {
        'label': 'Real Wildlife / NatGeo cinematic',
        'lora_file': 'flux_cinematic_wildlife.safetensors',
        'trigger': 'ultra-realistic cinematic photography style',
        'scale': 0.75,
        'claude_hint': (
            'National Geographic wildlife documentary photography — sharp fur/feather detail, '
            'natural habitat, golden-hour or overcast natural light, no humans'
        ),
        'negative_extra': (
            'human, person, man, woman, people, portrait, office, classroom, '
            'cartoon, anime, deformed anatomy, extra limbs, watermark'
        ),
    },
    'fantasy_creature': {
        'label': 'Dark fantasy creature',
        'lora_file': 'flux_dark_fantasy.safetensors',
        'trigger': 'dark fantasy art style',
        'scale': 0.70,
        'claude_hint': (
            'Epic dark-fantasy creature illustration — dramatic rim light, mist, '
            'mythical anatomy, painterly cinematic mood'
        ),
        'negative_extra': (
            'human, person, modern city, office, cartoon, chibi, watermark, deformed limbs, extra legs, blurry'
        ),
    },
    'fantasy_dragon': {
        'label': 'Dragon / wyvern dark fantasy',
        'lora_file': 'flux_dark_fantasy_alt.safetensors',
        'trigger': 'dark fantasy dragon',
        'scale': 0.72,
        'claude_hint': (
            'Monumental dragon or wyvern — scales, wings, smoke, volcanic or storm sky, cinematic dark-fantasy realism'
        ),
        'negative_extra': (
            'human, person, rider close-up, office, cartoon, chibi, watermark, tiny wings, broken anatomy'
        ),
    },
}

_DRAGON_KW = frozenset(
    {
        'dragon',
        'dragons',
        'wyvern',
        'wyverns',
        'drake',
        'drakes',
        'wyrm',
        'wyrms',
        'serpent',
        'serpents',
        'hydra',
    }
)
_FANTASY_KW = frozenset(
    {
        'fantasy',
        'mythical',
        'mythic',
        'magical',
        'magic',
        'demon',
        'beast',
        'monster',
        'griffin',
        'gryphon',
        'phoenix',
        'unicorn',
        'chimera',
        'goblin',
        'troll',
        'elemental',
        'fae',
        'fairy',
        'faerie',
    }
)


def lora_path(profile_key: str) -> str | None:
    prof = CREATURE_LORA_PROFILES.get(profile_key)
    if not prof:
        return None
    path = CREATURE_LORA_DIR / prof['lora_file']
    return str(path) if path.is_file() and path.stat().st_size > 1_000_000 else None


def all_profiles_ready() -> bool:
    return all(lora_path(k) for k in CREATURE_LORA_PROFILES)


def missing_profiles() -> list[str]:
    return [k for k in CREATURE_LORA_PROFILES if not lora_path(k)]


def resolve_profile(topic: str, explicit: str | None = None) -> tuple[str, dict]:
    """Return (profile_key, profile_dict) for a creature topic."""
    if explicit and explicit in CREATURE_LORA_PROFILES:
        return explicit, CREATURE_LORA_PROFILES[explicit]

    tl = (topic or '').lower()
    tokens = set(re.findall(r'[a-z]+', tl))
    if tokens & _DRAGON_KW or any(re.search(rf'\b{re.escape(kw)}\b', tl) for kw in _DRAGON_KW):
        return 'fantasy_dragon', CREATURE_LORA_PROFILES['fantasy_dragon']
    if tokens & _FANTASY_KW or any(re.search(rf'\b{re.escape(kw.strip())}\b', tl) for kw in _FANTASY_KW):
        return 'fantasy_creature', CREATURE_LORA_PROFILES['fantasy_creature']
    return 'real_wildlife', CREATURE_LORA_PROFILES['real_wildlife']


def build_creature_prompt(flux_prompt: str, profile: dict) -> str:
    trigger = (profile.get('trigger') or '').strip()
    base = (flux_prompt or '').strip()
    if trigger and trigger.lower() not in base.lower():
        return f'{trigger}, {base}'
    return base


def status_report(log_fn: Callable[[str], None] | None = None) -> bool:
    log = log_fn or (lambda _m: None)
    ok = True
    for key, prof in CREATURE_LORA_PROFILES.items():
        path = CREATURE_LORA_DIR / prof['lora_file']
        if path.is_file() and path.stat().st_size > 1_000_000:
            log(f'CreatureLoRA OK {key}: {path.name} ({path.stat().st_size // 1_000_000} MB)')
        else:
            log(f'CreatureLoRA MISSING {key}: {path}')
            ok = False
    return ok
