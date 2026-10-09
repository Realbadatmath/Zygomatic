# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Per-character trait pools and the numeric trait wordings."""

from __future__ import annotations

from typing import Any


_GENRE_LIGHTING: dict[str, str] = {
    'general': 'controlled studio key with moderate shadow definition, neutral fill',
    'action': 'dramatic rim light, deep shadows, hard key light',
    'romance': 'warm studio key with gentle shadow definition, not beauty-dish soft',
    'religion': 'top-down divine light, soft golden glow, dust motes',
    'finance': 'crisp daylight through large windows, clean shadows',
    'medieval': 'torchlit interior, warm fire glow, soft candle ambience',
    'education': 'natural window light, soft directional, indoor cinematic',
}

_GENRE_ACCESSORY: dict[str, dict[str, str]] = {
    'general': {'female': 'simple stud earrings', 'male': 'simple wristwatch'},
    'action': {'female': 'fingerless gloves, utility belt', 'male': 'fingerless gloves, weapon scabbard'},
    'romance': {'female': 'pearl earrings, delicate pendant', 'male': 'leather wristband'},
    'religion': {'female': 'simple woven cord', 'male': 'wooden prayer beads'},
    'finance': {'female': 'pearl studs, slim watch', 'male': 'silver cufflinks, slim wristwatch'},
    'medieval': {'female': 'leather pouch on belt', 'male': 'leather pouch on belt, simple silver brooch'},
    'education': {'female': 'reading glasses', 'male': 'reading glasses'},
}

# Hair-color → likely texture (only used when texture is auto)
_HAIRCOLOR_TEXTURE: dict[str, str] = {
    'blonde': 'soft wavy',
    'brown': 'straight',
    'dark brown': 'straight',
    'black': 'straight',
    'red': 'wavy',
    'auburn': 'wavy',
    'grey': 'straight',
    'white': 'straight',
}

# Gender-defaults for fields where biology often biases a sensible auto choice.
_GENDER_DEFAULTS: dict[str, dict[str, str]] = {
    'female': {
        'face_shape': 'oval',
        'eye_shape': 'almond',
        'eyebrow_style': 'natural arched',
        'lip_shape': 'natural full',
        'nose_shape': 'balanced',
        'hair_style': 'long flowing',
        'hair_length': 'shoulder',
        'posture': 'upright relaxed',
    },
    'male': {
        'face_shape': 'square',
        'eye_shape': 'almond',
        'eyebrow_style': 'natural',
        'lip_shape': 'natural',
        'nose_shape': 'balanced',
        'hair_style': 'short professional',
        'hair_length': 'short',
        'posture': 'upright confident',
    },
}

# ── Per-character trait pools (2026-07-17) ────────────────────────────────────
# apply_auto_defaults() used to resolve every 'auto' field to one FIXED value
# (age 28, 1.68 m, oval face, almond eyes, shoulder-length straight brown
# 'long flowing' hair, slender build). Combined with the storyteller form's
# fixed basics, every auto character rendered as the SAME woman under a
# different random name (verified 2026-07-17 across runs 880e9708 / e4395416 /
# ac97acfb — near-identical bibles and anchor faces). Auto fields now draw
# from these pools with an RNG seeded per character+field, so:
#   • explicitly chosen specs (e.g. brown hair, hazel eyes) are always honoured;
#   • the remaining traits differ between characters even with identical specs;
#   • the same character resolves to the same traits on every call — the
#     contact-sheet build, each bible save and later scene prompts must agree
#     or identity drifts mid-run (per-field seeding keeps one field's value
#     independent of which other fields happen to be auto at call time).
_SKIN_TONE_POOL = ('fair', 'medium-light', 'medium', 'olive', 'tan', 'dark', 'deep')
_HERITAGE_BY_SKIN: dict[str, tuple[str, ...]] = {
    'fair': (
        'Northern European',
        'Scandinavian',
        'Irish',
        'Slavic',
        'British',
        'Caribbean',
        'Latin American',
        'Mixed heritage',
    ),
    'light': ('Northern European', 'Central European', 'East Asian', 'Slavic'),
    'medium-light': (
        'Southern European',
        'Mediterranean',
        'East Asian',
        'Central European',
        'Latin American',
        'Caribbean',
        'Afro-Latin American',
    ),
    'medium': (
        'Mediterranean',
        'Latin American',
        'Middle Eastern',
        'East Asian',
        'South Asian',
        'Central Asian',
        'North African',
        'Indigenous American',
    ),
    'olive': ('Mediterranean', 'Middle Eastern', 'Latin American', 'South Asian', 'North African'),
    'tan': (
        'Latin American',
        'Southeast Asian',
        'South Asian',
        'Middle Eastern',
        'Pacific Islander',
        'North African',
        'Indigenous American',
        'Aboriginal Australian',
    ),
    'dark': (
        'West African',
        'East African',
        'Caribbean',
        'Afro-Latin American',
        'South Asian',
        'Pacific Islander',
        'Aboriginal Australian',
    ),
    'deep': ('West African', 'East African', 'Caribbean', 'Aboriginal Australian'),
}
_AFRICAN_HERITAGES = ('West African', 'East African', 'Caribbean', 'Afro-Latin American')
# Explicit-heritage → plausible skin tones (2026-07-19, for the UI ethnicity
# selector): when the user picks a heritage but leaves skin on Auto, the skin
# roll is constrained to coherent tones instead of the full pool ('West
# African' + rolled 'fair' made no sense). Kept alongside _HERITAGE_BY_SKIN
# (the auto→auto direction); update both when adding heritages.
_SKIN_BY_HERITAGE: dict[str, tuple[str, ...]] = {
    'Northern European': ('fair', 'medium-light'),
    'Scandinavian': ('fair', 'medium-light'),
    'British': ('fair', 'medium-light'),
    'Irish': ('fair',),
    'Central European': ('fair', 'medium-light'),
    'Southern European': ('medium-light', 'medium', 'olive'),
    'Mediterranean': ('medium-light', 'medium', 'olive'),
    'Slavic': ('fair', 'medium-light'),
    'East Asian': ('fair', 'medium-light', 'medium'),
    'Southeast Asian': ('medium', 'tan'),
    'South Asian': ('medium', 'olive', 'tan', 'brown', 'dark'),
    'Central Asian': ('medium-light', 'medium', 'tan'),
    'Middle Eastern': ('medium-light', 'medium', 'olive', 'tan'),
    'North African': ('medium', 'olive', 'tan'),
    'West African': ('dark', 'deep'),
    'East African': ('tan', 'dark', 'deep'),
    # Admixed New-World heritages span the FULL skin range in reality — a
    # light-skinned Caribbean/Latin person is common — so an AUTO skin roll for
    # these now reaches fair/medium-light too, not just medium-and-darker
    # (2026-07-21). Explicit skin choices bypass this map entirely.
    'Caribbean': ('fair', 'medium-light', 'medium', 'tan', 'dark', 'deep'),
    'Afro-Latin American': ('medium-light', 'medium', 'tan', 'dark'),
    'Latin American': ('fair', 'medium-light', 'medium', 'olive', 'tan'),
    'Indigenous American': ('medium', 'tan'),
    'Pacific Islander': ('medium', 'tan', 'dark'),
    'Aboriginal Australian': ('tan', 'dark', 'deep'),
    'Mixed heritage': ('fair', 'medium-light', 'medium', 'olive', 'tan', 'dark'),
}
_EYES_LIGHT_SKIN = ('brown', 'brown', 'hazel', 'green', 'blue', 'amber', 'gray')
_EYES_DEEP_SKIN = ('brown', 'brown', 'brown', 'amber', 'hazel')
_HAIR_LIGHT_SKIN = ('black', 'dark brown', 'brown', 'brown', 'auburn', 'red', 'blonde')
_HAIR_DEEP_SKIN = ('black', 'black', 'dark brown', 'brown')
_FACE_SHAPE_POOL = {
    'female': ('oval', 'round', 'heart', 'long', 'diamond', 'square'),
    'male': ('square', 'oval', 'long', 'round', 'diamond'),
}
_EYE_SHAPE_POOL = ('almond', 'round', 'hooded', 'upturned', 'downturned')
_EYE_SHAPE_POOL_ASIAN = ('almond', 'monolid', 'monolid', 'round', 'hooded', 'upturned')
_BROW_POOL = {
    'female': ('natural arched', 'natural', 'thick', 'bold straight', 'sparse'),
    'male': ('natural', 'thick', 'bold straight', 'natural arched'),
}
_NOSE_POOL = ('balanced', 'button', 'aquiline', 'broad', 'narrow')
_LIP_POOL = {
    'female': ('natural full', 'natural', 'full', 'thin', 'wide'),
    'male': ('natural', 'thin', 'wide'),
}
# (style, length, texture) combos — style implies the other two so auto hair
# stays coherent; texture 'coily' combos are reserved for African heritages.
_HAIR_COMBOS = {
    'female': (
        ('long flowing', 'long', 'straight'),
        ('long flowing waves', 'long', 'wavy'),
        ('sleek straight', 'shoulder', 'straight'),
        ('loose waves', 'shoulder', 'wavy'),
        ('layered bob', 'short', 'straight'),
        ('side-parted lob', 'shoulder', 'wavy'),
        ('high ponytail', 'long', 'straight'),
        ('low bun updo', 'medium', 'straight'),
        ('shoulder-length curls', 'shoulder', 'curly'),
        ('tight curls', 'medium', 'curly'),
        ('curly afro', 'medium', 'coily'),
        ('box braids', 'long', 'coily'),
        ('pixie cut', 'short', 'straight'),
    ),
    'male': (
        ('short professional', 'short', 'straight'),
        ('buzz cut', 'shaved', 'straight'),
        ('slicked back', 'short', 'straight'),
        ('textured crop', 'short', 'wavy'),
        ('side-parted classic', 'short', 'straight'),
        ('medium swept back', 'medium', 'wavy'),
        ('curly top', 'short', 'curly'),
        ('afro fade', 'short', 'coily'),
    ),
}
_MARKS_POOL = (
    'none',
    'none',
    'none',
    'light freckles across nose and cheeks',
    'small beauty mark on left cheek',
    'faint freckles',
    'small beauty mark above lip',
    'faint scar through one eyebrow',
)
_MUSCLE_POOL = {
    'female': (10, 15, 20, 20, 25, 25, 30, 35, 40, 50),
    'male': (20, 25, 30, 30, 35, 35, 40, 45, 50, 60),
}


def _muscle_text(v: Any) -> str:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 'average build'
    if n <= 20:
        return 'slender build'
    if n <= 40:
        return 'average build'
    if n <= 60:
        return 'athletic build'
    if n <= 80:
        return 'muscular build'
    return 'very muscular bodybuilder build'


def _height_text(v: Any) -> str:
    try:
        h = float(v)
    except (TypeError, ValueError):
        return ''
    if h < 1.40:
        return 'very short stature'
    if h < 1.55:
        return 'short stature'
    if h < 1.65:
        return 'below-average height'
    if h < 1.78:
        return 'average height'
    if h < 1.88:
        return 'tall stature'
    return 'very tall stature'


def _age_range_from_age(age: Any) -> str:
    try:
        a = int(age)
    except (TypeError, ValueError):
        return 'adult'
    if a < 13:
        return 'child'
    if a < 26:
        return 'young adult'
    if a < 51:
        return 'adult'
    if a < 71:
        return 'mature adult'
    return 'elder'
