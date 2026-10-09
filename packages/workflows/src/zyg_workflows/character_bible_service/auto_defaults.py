# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""apply_auto_defaults(): resolve every "auto" descriptor for a character.

The resolution is a fixed sequence of stages, each of which fills one family of
descriptors and may read what the earlier stages decided. The stages are module-level
functions so they can be unit-tested one at a time; `apply_auto_defaults` is the
orchestrator that calls them in the one order the result depends on.
"""

from __future__ import annotations

import functools
import random
from typing import Any, Callable


from .smile import (
    _is_auto,
)
from .genre_tables import (
    _GENRE_ACCESSORY_POOL,
    _GENRE_LIGHTING_POOL,
    _GENRE_PALETTE,
    _GENRE_WARDROBE_POOL,
)
from .appearance_negatives import (
    PHOTOREAL_SKIN_NEG,
)
from .trait_tables import (
    _AFRICAN_HERITAGES,
    _BROW_POOL,
    _EYES_DEEP_SKIN,
    _EYES_LIGHT_SKIN,
    _EYE_SHAPE_POOL,
    _EYE_SHAPE_POOL_ASIAN,
    _FACE_SHAPE_POOL,
    _GENDER_DEFAULTS,
    _HAIRCOLOR_TEXTURE,
    _HAIR_COMBOS,
    _HAIR_DEEP_SKIN,
    _HAIR_LIGHT_SKIN,
    _HERITAGE_BY_SKIN,
    _LIP_POOL,
    _MARKS_POOL,
    _MUSCLE_POOL,
    _NOSE_POOL,
    _SKIN_BY_HERITAGE,
    _SKIN_TONE_POOL,
    _age_range_from_age,
    _height_text,
    _muscle_text,
)

# Normalise colloquial tone words to the canonical scale so the whole pipeline
# (negatives, luminance floor, VLM judge) handles them (2026-07-21): 'white'/'pale' →
# 'fair' etc. Without this, a literal 'white' request got no skin defence and no
# luminance floor.
_SKIN_ALIAS = {
    'white': 'fair',
    'pale': 'fair',
    'porcelain': 'fair',
    'ebony': 'deep',
    'very dark': 'deep',
    'brown': 'dark',
}

# Auto males roll this pool (2026-07-18: the fixed 'none' default meant no auto
# character ever had facial hair, wasting one of the strongest male differentiators).
_FACIAL_HAIR_POOL = (
    'none',
    'none',
    'clean-shaven',
    'light stubble',
    'heavy stubble',
    'short boxed beard',
    'full beard',
    'moustache',
    'goatee',
)

# Grey/white hair on a character under this age reads as a data-entry mismatch.
_GREY_HAIRS = ('grey', 'gray', 'white', 'silver', 'platinum')

_BASE_NEGATIVES = (
    'blurry',
    'low quality',
    'low resolution',
    'jpeg artifacts',
    'deformed face',
    'bad anatomy',
    'extra fingers',
    'extra limbs',
    'mutated hands',
    'malformed',
    'asymmetric eyes',
    'watermark',
    'text',
    'signature',
    'logo',
    'multiple people',
    'two people',
    'three people',
    'duplicate character',
    'twins',
    'crowd',
    'group shot',
    'character sheet',
    'lineup',
    'extra person',
)

_Rand = Callable[[str], random.Random]


def _seed_key(p: dict[str, Any], seed_key: str | None) -> str:
    """The per-character seed string the field RNGs are built from.

    Takes the (already copied) params dict and the caller's explicit ``seed_key``;
    returns the first usable identity among seed_key, char_id, character_id and a
    non-auto name, lowercased and stripped, or '' when the character has no identity
    at all.
    """
    return (
        str(
            seed_key
            or p.get('char_id')
            or p.get('character_id')
            or ('' if _is_auto(p.get('name')) else (p.get('name') or ''))
        )
        .strip()
        .lower()
    )


def _field_rng(seed_key: str, field: str) -> random.Random:
    """A Random seeded on (character, field), or a fresh-entropy one with no seed.

    No usable seed at all still randomises — anything beats the old fixed same-face
    defaults — but such a character can drift between calls, so callers should pass
    seed_key.
    """
    return random.Random(f'zyg-char-traits:{seed_key}:{field}') if seed_key else random.Random()


def _resolve_core_identity(p: dict[str, Any], rand: _Rand) -> tuple[str, dict[str, str], str, str]:
    """Fill gender, render_style/style, genre, age, age_range, height, height_text.

    Mutates ``p`` in place and returns (gender, gender_defaults, style, genre) — the
    four values every later stage is keyed on.
    """
    # Gender — drives every other gender-keyed default. 'auto'/missing rolls the
    # per-character dice (2026-07-18: the public form pinned every auto character to
    # female); an explicit unrecognised value falls back female.
    gender = (p.get('gender') or '').strip().lower()
    if gender not in ('female', 'male'):
        gender = rand('gender').choice(('female', 'male')) if _is_auto(p.get('gender')) else 'female'
    p['gender'] = gender
    gd = _GENDER_DEFAULTS[gender]

    # Style + genre + age (used by other defaults).
    # Accept legacy 'style' key as an alias for 'render_style'.
    if _is_auto(p.get('render_style')) and not _is_auto(p.get('style')):
        p['render_style'] = p['style']
    if _is_auto(p.get('render_style')):
        p['render_style'] = 'photorealistic'
    p['style'] = p['render_style']  # keep legacy callers happy
    style = p['render_style']
    if _is_auto(p.get('genre')):
        p['genre'] = 'general'
    genre = p['genre']

    if _is_auto(p.get('age')):
        _r_age = rand('age')
        # 70% working-age triangular (centre ~33), 20% mature, 10% elder —
        # the pure 21-45 pool never produced older storytellers (2026-07-18).
        _age_roll = _r_age.random()
        if _age_roll < 0.70:
            p['age'] = round((_r_age.randint(21, 45) + _r_age.randint(21, 45)) / 2)
        elif _age_roll < 0.90:
            p['age'] = _r_age.randint(46, 60)
        else:
            p['age'] = _r_age.randint(61, 75)
    p['age_range'] = p.get('age_range') if not _is_auto(p.get('age_range')) else _age_range_from_age(p['age'])

    # Height — keep numeric meters separate from descriptive text.
    if _is_auto(p.get('height')):
        _r_h = rand('height')
        p['height'] = round(
            _r_h.uniform(1.65, 1.93) if gender == 'male' else _r_h.uniform(1.55, 1.79),
            2,
        )
    try:
        p['height'] = float(p['height'])
    except (TypeError, ValueError):
        p['height'] = 1.70
    p['height_text'] = _height_text(p['height'])
    return gender, gd, style, genre


def _resolve_skin_and_heritage(p: dict[str, Any], rand: _Rand) -> tuple[str, bool]:
    """Fill skin_tone and ethnic_heritage, and the two flags that travel with them.

    Mutates ``p`` in place and returns (heritage, deep_skin) for the colour pools below.

    Skin tone comes first, then a heritage coherent with it — together these two drive
    the colour pools and give FLUX real cross-character variety. 2026-07-19: an
    EXPLICIT heritage (UI ethnicity selector) constrains an auto skin roll to plausible
    tones for that heritage. 2026-07-21: ``_skin_tone_was_auto`` records whether the
    operator EXPLICITLY chose the tone, because the attribute gate must not sync an
    explicit skin choice away to a heritage-driven delivered tone — a light-skinned
    member of a dark heritage is a legitimate request, not drift to be "corrected".
    """
    p['_skin_tone_was_auto'] = bool(_is_auto(p.get('skin_tone')))
    _skin_raw = (p.get('skin_tone') or '').strip().lower()
    if _skin_raw in _SKIN_ALIAS:
        p['skin_tone'] = _SKIN_ALIAS[_skin_raw]
    if _is_auto(p.get('skin_tone')):
        _her_explicit = (p.get('ethnic_heritage') or '').strip()
        _skin_pool = (
            _SKIN_BY_HERITAGE.get(_her_explicit) if _her_explicit and not _is_auto(p.get('ethnic_heritage')) else None
        ) or _SKIN_TONE_POOL
        p['skin_tone'] = rand('skin_tone').choice(_skin_pool)
    _skin_lc = (p['skin_tone'] or '').strip().lower()
    if _is_auto(p.get('ethnic_heritage')):
        _her_pool = _HERITAGE_BY_SKIN.get(_skin_lc, ())
        p['ethnic_heritage'] = rand('ethnic_heritage').choice(_her_pool) if _her_pool else ''
    return (p.get('ethnic_heritage') or '').strip(), _skin_lc in ('dark', 'deep')


def _resolve_hair_and_eyes(
    p: dict[str, Any],
    rand: _Rand,
    gender: str,
    heritage: str,
    deep_skin: bool,
) -> None:
    """Fill hair_color, eye_color and the (style, length, texture) hair structure.

    Mutates ``p`` in place. A coherent combo is drawn when the style is auto; coily
    combos stay with African heritages so renders read naturally. ``_hair_color_was_auto``
    is recorded (2026-07-22) so the attribute gate never syncs an explicit colour away
    to a heritage-driven delivered one — a brown selection under a dark-hair heritage is
    legitimate, not drift.
    """
    p['_hair_color_was_auto'] = bool(_is_auto(p.get('hair_color')))
    if _is_auto(p.get('hair_color')):
        try:
            _age_hair = int(p.get('age') or 0)
        except (TypeError, ValueError):
            _age_hair = 0
        if _age_hair >= 58:
            # Older auto characters grey naturally instead of keeping the
            # young-adult colour pools (2026-07-18).
            p['hair_color'] = rand('hair_color').choice(
                ('grey', 'white', 'grey', 'dark brown'),
            )
        else:
            p['hair_color'] = rand('hair_color').choice(
                _HAIR_DEEP_SKIN if deep_skin else _HAIR_LIGHT_SKIN,
            )
    if _is_auto(p.get('eye_color')):
        p['eye_color'] = rand('eye_color').choice(
            _EYES_DEEP_SKIN if deep_skin else _EYES_LIGHT_SKIN,
        )

    if _is_auto(p.get('hair_style')):
        _combos = _HAIR_COMBOS[gender]
        if heritage in _AFRICAN_HERITAGES:
            _curl = tuple(c for c in _combos if c[2] in ('coily', 'curly'))
            _combos = _curl or _combos
        else:
            _combos = tuple(c for c in _combos if c[2] != 'coily') or _combos
        _style, _len, _tex = rand('hair_combo').choice(_combos)
        p['hair_style'] = _style
        if _is_auto(p.get('hair_length')):
            p['hair_length'] = _len
        if _is_auto(p.get('hair_texture')):
            p['hair_texture'] = _tex
    if _is_auto(p.get('hair_length')):
        p['hair_length'] = rand('hair_length').choice(
            ('short', 'medium', 'shoulder', 'long') if gender == 'female' else ('shaved', 'short', 'medium'),
        )
    if _is_auto(p.get('hair_texture')):
        p['hair_texture'] = _HAIRCOLOR_TEXTURE.get(p['hair_color'].lower(), 'straight')


def _resolve_features_and_build(p: dict[str, Any], rand: _Rand, gender: str, heritage: str) -> None:
    """Fill the face features, the body build, facial hair and distinctive marks.

    Mutates ``p`` in place: eye_shape, eyebrow_style, face_shape, nose_shape,
    lip_shape, muscle_mass, body_build, facial_hair, distinctive_marks. Females coerce
    facial hair to 'none'; explicit marks of 'none' are honoured while auto rolls a
    mostly-none pool (subtle freckles / beauty marks help differentiate similar faces).
    """
    if _is_auto(p.get('eye_shape')):
        _eye_pool = _EYE_SHAPE_POOL_ASIAN if 'Asian' in heritage else _EYE_SHAPE_POOL
        p['eye_shape'] = rand('eye_shape').choice(_eye_pool)
    if _is_auto(p.get('eyebrow_style')):
        p['eyebrow_style'] = rand('eyebrow_style').choice(_BROW_POOL[gender])
    if _is_auto(p.get('face_shape')):
        p['face_shape'] = rand('face_shape').choice(_FACE_SHAPE_POOL[gender])
    if _is_auto(p.get('nose_shape')):
        p['nose_shape'] = rand('nose_shape').choice(_NOSE_POOL)
    if _is_auto(p.get('lip_shape')):
        p['lip_shape'] = rand('lip_shape').choice(_LIP_POOL[gender])

    # Body build (numeric muscle_mass slider OR descriptor text).
    mm = p.get('muscle_mass') if p.get('muscle_mass') is not None else p.get('body_build')
    if _is_auto(mm):
        mm = rand('muscle_mass').choice(_MUSCLE_POOL[gender])
    p['muscle_mass'] = mm
    p['body_build'] = _muscle_text(mm)

    _fh_raw = p.get('facial_hair')
    fh = (_fh_raw or '').strip().lower()
    if gender == 'female':
        fh = 'none'
    elif _is_auto(_fh_raw):
        fh = rand('facial_hair').choice(_FACIAL_HAIR_POOL)
    p['facial_hair'] = fh if fh else 'none'

    if _is_auto(p.get('distinctive_marks')):
        p['distinctive_marks'] = rand('distinctive_marks').choice(_MARKS_POOL)

    # Ethnic heritage was resolved above (skin-tone-coherent pool); nothing to
    # do here — kept as a landmark for readers scanning the original order.


def _resolve_presentation(
    p: dict[str, Any],
    rand: _Rand,
    gender: str,
    genre: str,
    gd: dict[str, str],
) -> None:
    """Fill wardrobe, accessories, lighting, palette, posture, expression and camera.

    Mutates ``p`` in place. The wardrobe/accessory/lighting pools and the palette are
    keyed on the genre (falling back to 'general'); posture comes from the gender
    defaults; a locked smile keeps its expression.
    """
    if _is_auto(p.get('default_clothing')):
        _ward_pool = _GENRE_WARDROBE_POOL.get(genre, _GENRE_WARDROBE_POOL['general'])[gender]
        p['default_clothing'] = rand('default_clothing').choice(_ward_pool)
    if _is_auto(p.get('accessories')):
        _acc_pool = _GENRE_ACCESSORY_POOL.get(genre, _GENRE_ACCESSORY_POOL['general'])[gender]
        p['accessories'] = rand('accessories').choice(_acc_pool)
    if _is_auto(p.get('lighting_profile')):
        _light_pool = _GENRE_LIGHTING_POOL.get(genre, _GENRE_LIGHTING_POOL['general'])
        p['lighting_profile'] = rand('lighting_profile').choice(_light_pool)
    if _is_auto(p.get('color_palette')):
        p['color_palette'] = _GENRE_PALETTE.get(genre, _GENRE_PALETTE['general'])
    if _is_auto(p.get('posture')):
        p['posture'] = gd['posture']
    if _is_auto(p.get('default_expression')):
        if not p.get('smile_locked'):
            p['default_expression'] = 'neutral confident'
    if _is_auto(p.get('camera_language')):
        p['camera_language'] = 'medium shots, stable framing, documentary interior'


def _quality_suffix_text(style: str) -> str:
    """The quality suffix for a render style — photoreal optics or illustration polish."""
    if style == 'photorealistic':
        return (
            'shot on 85mm portrait lens, f/5.6, sharp focus on face, '
            'visible skin pores, natural skin microdetail, unretouched, '
            'fine film grain, realistic skin texture'
        )
    return (
        'highly detailed illustration, sharp linework, vibrant colors, '
        'expressive cinematic composition, polished render'
    )


def _negative_prompt_terms(p: dict[str, Any], gender: str, style: str) -> list[str]:
    """The negative-prompt term list for a resolved params dict, in render order.

    Reads facial_hair, distinctive_marks and the style off ``p``; returns the base
    terms plus the targeted suppressions. Nothing is mutated.
    """
    neg = list(_BASE_NEGATIVES)
    # Targeted suppression: if facial_hair=none, push beard out of frame.
    if p['facial_hair'] == 'none' and gender == 'male':
        neg += ['beard', 'moustache', 'goatee']
    # Freckle governance: the photoreal quality suffix asks for skin
    # "imperfections/microdetail", which FLUX sometimes renders as a dense
    # freckle field even when distinctive_marks is 'none' — qwen edits then
    # smear that field into scar-like mottling on derived tiles. Unless the
    # rolled marks explicitly include freckles, forbid freckle fields.
    if 'freckle' not in str(p.get('distinctive_marks') or '').lower():
        neg += ['heavy freckles', 'dense freckle field', 'freckled face', 'mottled skin']
    # If user picked photorealistic, suppress cartoon traits and vice versa.
    if style == 'photorealistic':
        neg += [
            'cartoon',
            'anime',
            'cel shading',
            'painterly',
            'sketch',
            *PHOTOREAL_SKIN_NEG.split(', '),
        ]
    else:
        neg += [
            'photographic noise',
            'film grain',
            'realistic skin pores',
            'oil painting',
            'soft brush',
            'painterly',
            'watercolor',
        ]
    return neg


def _resolve_prompt_text(p: dict[str, Any], gender: str, style: str) -> None:
    """Fill quality_suffix and negative_prompt, and nudge an implausible hair colour.

    Mutates ``p`` in place, in the order the original did: quality suffix, then the
    young-grey hair nudge (grey/white hair on a character under 35 reads as a
    data-entry mismatch, so it becomes ash brown and `_hair_age_adjusted` records it so
    LoRA + previews stay visually coherent), then the negative prompt, then the
    animated-style quality override. Neither prompt field is ever left empty.
    """
    if _is_auto(p.get('quality_suffix')):
        p['quality_suffix'] = _quality_suffix_text(style)
    try:
        _age_i = int(p.get('age', 0))
    except (TypeError, ValueError):
        _age_i = 28
    _hair_lc = (p.get('hair_color') or '').strip().lower()
    if _age_i < 35 and _hair_lc in _GREY_HAIRS:
        p['hair_color'] = 'ash brown'
        p['_hair_age_adjusted'] = True

    if _is_auto(p.get('negative_prompt')):
        p['negative_prompt'] = ', '.join(_negative_prompt_terms(p, gender, style))

    if (p.get('render_style') or p.get('style') or '').strip().lower() == 'animated':
        if _is_auto(p.get('quality_suffix')) or not (p.get('quality_suffix') or '').strip():
            p['quality_suffix'] = (
                'flat cel shading, clean line art, crisp outlines, vibrant flat colors, '
                'animation still frame, sharp focus'
            )


def apply_auto_defaults(
    raw_params: dict[str, Any],
    seed_key: str | None = None,
) -> dict[str, Any]:
    """Fill in every descriptor the user didn't explicitly set.

    Takes the raw params dict from the UI (any subset of keys, any value may
    be empty / 'auto' / None) and returns a fully-populated params dict that
    downstream code can rely on without further branching.

    Auto fields are drawn from trait pools with an RNG seeded per
    character+field (see the pool block above): explicitly chosen specs are
    honoured verbatim, the rest varies between characters so identical specs
    never resolve to the same face. Pass ``seed_key`` (char_id) wherever it is
    known so repeated calls for one character always agree; the fallback is
    ``params['char_id']``/``params['name']``.

    Heuristics are biased toward producing coherent characters that ComfyUI
    will render cleanly.  ``gender`` is the only required input — if missing
    we default to 'female' so generation still succeeds.
    """
    p = dict(raw_params or {})
    rand = functools.partial(_field_rng, _seed_key(p, seed_key))

    gender, gd, style, genre = _resolve_core_identity(p, rand)
    heritage, deep_skin = _resolve_skin_and_heritage(p, rand)
    _resolve_hair_and_eyes(p, rand, gender, heritage, deep_skin)
    _resolve_features_and_build(p, rand, gender, heritage)
    _resolve_presentation(p, rand, gender, genre, gd)
    _resolve_prompt_text(p, gender, style)
    return p
