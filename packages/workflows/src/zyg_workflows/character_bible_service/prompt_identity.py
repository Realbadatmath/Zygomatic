# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Character Studio's field layer and the identity/presentation prompt text."""

from __future__ import annotations

import os
from typing import Any
import logging as _zyg_logging


from .smile import (
    format_expression_for_prompt,
)
from .appearance_negatives import (
    age_prompt_phrase,
    describe_skin_tone,
)
from .trait_tables import (
    _height_text,
)
from .store import (
    _presentation_from_package,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.character_bible_service')


# ── Character Studio's second field layer, folded into the prompts ───────────
# 2026-09-18. character_studio.FIELDS gained 66 new dotted paths under new
# top-level groups (appearance, wardrobe, accessories, grooming, …). A field
# that no prompt reads is rule 1's "knob that writes a key nothing reads", so
# the ones that describe how the character LOOKS are folded in here.
#
# Two invariants, in this order:
#
# 1. A BIBLE WITHOUT THE NEW KEYS PRODUCES THE PROMPT IT PRODUCED YESTERDAY.
#    Every clause below is emitted only when the group exists AND the value is
#    set AND it differs from the registry default. All 132 bibles on disk lack
#    these groups entirely, so today every one of these loops adds nothing.
# 2. THE DEFAULT IS SILENCE, NOT A WORD. 'natural jaw' in a prompt is not a
#    no-op — it is a token competing with the LoRA's own face. A field left at
#    its default must contribute no token at all.
#
# Each entry is (dotted key within the group, default, phrasing). Phrasing is
# either a template with {v}, or a dict of value -> phrase (with '' as the
# fallback template). The wording is the point: the choice strings are UI
# labels, and several of them ('gap', 'temples', 'centre') are meaningless on
# their own inside a comma-separated prompt.

_APPEARANCE_CLAUSES: tuple[tuple[str, Any, Any], ...] = (
    # Structure and surface — the permanent face. asymmetry / gaze / pupils are
    # deliberately absent: they are render-time staging, not identity.
    (
        'jaw',
        'natural',
        {'cleft chin': 'cleft chin', 'strong chin': 'strong chin', 'weak chin': 'weak chin', '': '{v} jaw'},
    ),
    ('cheekbones', 'natural', {'hollow cheeks': 'hollow cheeks', 'full cheeks': 'full cheeks', '': '{v} cheekbones'}),
    ('ears', 'natural', {'hidden by hair': 'ears hidden by hair', '': '{v} ears'}),
    (
        'teeth',
        'not shown',
        {
            'gap': 'a gap in the teeth',
            'missing tooth': 'a missing tooth',
            'gold tooth': 'a gold tooth',
            '': '{v} teeth',
        },
    ),
    ('complexion', 'natural', '{v} complexion'),
    ('ageing', 'none', {'weathered': 'weathered skin', 'sagging': 'sagging skin', '': '{v}'}),
    ('eyelids', 'natural', '{v} eyelids'),
    ('lashes', 'natural', '{v} eyelashes'),
    ('heterochromia', '', 'heterochromia, {v}'),
    (
        'under_eye',
        'none',
        {
            'faint shadow': 'faint shadows under the eyes',
            'dark circles': 'dark circles under the eyes',
            'puffy': 'puffy under-eyes',
            'tired band': 'tired bands under the eyes',
            '': '{v}',
        },
    ),
    ('hairline', 'natural', {'low': 'low hairline', 'high': 'high hairline', '': '{v}'}),
    ('parting', 'none', '{v} parting'),
    (
        'greying',
        'none',
        {
            'temples': 'greying at the temples',
            'streaks': 'grey streaks in the hair',
            'salt and pepper': 'salt and pepper hair',
            'mostly grey': 'mostly grey hair',
            'fully grey': 'fully grey hair',
            '': '{v}',
        },
    ),
    ('body_hair', 'light', '{v} body hair'),
    ('hair_behaviour', 'still', {'soft flyaways': 'soft flyaway hairs', '': '{v} hair'}),
    ('tattoos', '', '{v}'),
    ('body_scars', '', '{v}'),
)

_WARDROBE_CLAUSES: tuple[tuple[str, Any, Any], ...] = (
    (
        'fabric',
        'cotton',
        {'leather': 'leather', 'fur': 'fur', 'denim': 'denim', 'mixed': 'mixed fabrics', '': '{v} fabric'},
    ),
    (
        'period',
        'contemporary',
        {
            'timeless fantasy': 'timeless fantasy dress',
            'science fiction': 'science fiction dress',
            '': '{v} period clothing',
        },
    ),
    ('outerwear', 'none', '{v}'),
    ('headwear', 'none', '{v}'),
    ('footwear', 'shoes', '{v}'),
    ('condition', 'clean', '{v} clothing'),
)

_ACCESSORY_CLAUSES: tuple[tuple[str, Any, Any], ...] = (
    ('jewellery', '', '{v}'),
    ('eyewear', 'none', '{v}'),
    ('bags', 'none', '{v}'),
)

_GROOMING_CLAUSES: tuple[tuple[str, Any, Any], ...] = (
    ('makeup', 'none', {'smoky eyes': 'smoky eye make-up', 'red lips': 'red lipstick', '': '{v} make-up'}),
    (
        'kept',
        'neat',
        {'immaculate': 'immaculately groomed', 'everyday': 'everyday grooming', 'wild': 'wild, ungroomed', '': '{v}'},
    ),
    ('nails', 'natural', '{v} nails'),
)

# dirt/sweat are 0..100 sliders. Below this they are texture the renderer does
# not need a word for; above it they change what the shot is of.
_GRIME_THRESHOLD = 40


def _studio_clauses(group: dict[str, Any] | None, table: tuple[tuple[str, Any, Any], ...]) -> list[str]:
    """Phrases for the fields of one group that are set and off their default."""
    if not isinstance(group, dict) or not group:
        return []
    out: list[str] = []
    for key, default, phrasing in table:
        raw = group.get(key)
        if raw is None or isinstance(raw, (dict, list)):
            continue
        v = str(raw).strip()
        if not v or v == default or v.lower() in ('none', 'n/a'):
            continue
        tmpl = phrasing
        if isinstance(phrasing, dict):
            tmpl = phrasing.get(v) or phrasing.get('', '{v}')
        out.append(tmpl.replace('{v}', v) if '{v}' in tmpl else tmpl)
    return out


def _grime_clauses(grooming: dict[str, Any] | None) -> list[str]:
    if not isinstance(grooming, dict) or not grooming:
        return []
    out: list[str] = []
    for key, word in (('dirt', 'dusty'), ('sweat', 'sweating')):
        try:
            if float(grooming.get(key) or 0) > _GRIME_THRESHOLD:
                out.append(word)
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('grooming value not numeric, word skipped: %s', _exc)
            continue
    return out


def identity_prompt_prefix(package: dict[str, Any] | None) -> str:
    """Permanent identity tokens — face, hair structure, marks, build.

    Excludes default clothing/accessories/expression so presentation can change
    per scene without identity drift.  Use ``presentation_prompt_fragment()`` for
    the signature outfit, or ``full_character_descriptor()`` for both layers.
    """
    if not package:
        return ''
    trig = package.get('trigger_token', '')
    ident = package.get('identity', {}) or {}
    style = package.get('style_profile', {}) or {}

    parts: list[str] = []
    if trig:
        parts.append(trig)

    gender = ident.get('gender', '')
    age = ident.get('age')
    age_r = ident.get('age_range', '')
    if gender:
        if age:
            # Age-reinforced (2026-07-22): a bare '34-year-old woman' loses to
            # FLUX's young-glamour default; older specs get maturity cues.
            parts.append(age_prompt_phrase(age, gender))
        elif age_r:
            parts.append(f'{age_r} {gender}')
        else:
            parts.append(f'{gender} character')

    # Skin tone is promoted to right after gender/age (FLUX weights early tokens
    # heavily) and expanded to a strong melanin descriptor — a bare "dark skin"
    # buried mid-prompt was losing to the model's light-skin prior.
    skin_phrase = describe_skin_tone(
        ident.get('skin_tone', ''),
        ident.get('ethnic_heritage', ''),
    )
    if skin_phrase:
        parts.append(skin_phrase)

    # Heritage as FEATURES, not a skin-tone-loaded person label (2026-07-21).
    # "Caribbean heritage" made FLUX render the whole stereotype including brown
    # skin, overriding an explicit lighter skin_tone in the same prompt. Scoping
    # heritage to facial features + hair texture keeps the bone-structure /
    # hair priors while ceding COLOUR authority to the skin_tone token, so a
    # fair-skinned character with Caribbean features renders as requested.
    # ZYG_HERITAGE_PHRASING=label restores the old skin-loaded wording.
    heritage = ident.get('ethnic_heritage', '')
    if heritage:
        if os.environ.get('ZYG_HERITAGE_PHRASING', 'features').strip().lower() == 'label':
            parts.append(f'{heritage} heritage')
        else:
            parts.append(f'{heritage} facial features and hair texture')

    face_shape = ident.get('face_shape', '')
    if face_shape:
        parts.append(f'{face_shape} face')

    nose = ident.get('nose_shape', '')
    if nose:
        parts.append(f'{nose} nose')

    lips = ident.get('lip_shape', '')
    if lips:
        parts.append(f'{lips} lips')

    eye_color = ident.get('eye_color', '')
    eye_shape = ident.get('eye_shape', '')
    if eye_shape and eye_color:
        parts.append(f'{eye_shape} {eye_color} eyes')
    elif eye_color:
        parts.append(f'{eye_color} eyes')

    brows = ident.get('eyebrow_style', '')
    if brows:
        parts.append(f'{brows} eyebrows')

    hair_color = ident.get('hair_color', '')
    hair_len = ident.get('hair_length', '')
    hair_style = ident.get('hair_style', '')
    hair_tex = ident.get('hair_texture', '')
    hair_words: list[str] = []
    if hair_len:
        hair_words.append(hair_len)
    if hair_tex and hair_tex not in hair_words:
        hair_words.append(hair_tex)
    if hair_color and hair_color not in hair_words:
        hair_words.append(hair_color)
    if hair_style:
        _trim = hair_style
        for _stop in (hair_len, hair_tex):
            if _stop and _trim.lower().startswith(_stop.lower() + ' '):
                _trim = _trim[len(_stop) + 1 :]
        _trim = _trim.strip()
        if _trim and _trim.lower() not in (w.lower() for w in hair_words):
            hair_words.append(_trim)
    if hair_words:
        parts.append(' '.join(hair_words) + ' hair')

    fh = ident.get('facial_hair', 'none')
    if fh and fh != 'none':
        parts.append(f'{fh} facial hair')

    height_m = ident.get('height_m')
    if height_m:
        ht = _height_text(height_m)
        if ht:
            parts.append(ht)

    build = ident.get('body_build', '')
    if build:
        parts.append(build if 'build' in str(build).lower() else f'{build} build')

    marks = ident.get('distinctive_marks', '')
    if marks and marks.strip().lower() not in ('', 'none', 'n/a'):
        parts.append(marks)

    render = style.get('render_style', '')
    if render:
        # Insert render style right after gender/skin (position 2-3) so FLUX sees
        # the style class token during early high-impact denoising steps.
        _insert_pos = min(2, len(parts))
        parts.insert(_insert_pos, render)

    # The Character Studio appearance layer goes on the END, after the render
    # style has been inserted — appending earlier would move `_insert_pos` for a
    # sparse package and change a prompt that has none of these fields.
    parts.extend(_studio_clauses(package.get('appearance'), _APPEARANCE_CLAUSES))

    return ', '.join(parts)


def presentation_prompt_fragment(
    package: dict[str, Any] | None,
    *,
    include_lighting: bool = False,
) -> str:
    """Default presentation layer — outfit, accessories, expression, posture."""
    if not package:
        return ''
    pres = _presentation_from_package(package)
    style = package.get('style_profile', {}) or {}
    parts: list[str] = []

    clothing = pres.get('default_clothing', '')
    if clothing:
        parts.append(clothing)

    accs = pres.get('accessories', '')
    if accs and accs.strip().lower() not in ('', 'none'):
        parts.append(accs)

    expression = pres.get('default_expression', '')
    if expression:
        try:
            parts.append(format_expression_for_prompt(expression))
        except Exception:
            parts.append(f'{expression} expression')

    posture = pres.get('posture', '')
    if posture:
        parts.append(posture)

    # Character Studio's wardrobe / accessories / grooming layer. Presentation,
    # not identity: these are the things a scene is allowed to change.
    grooming = package.get('grooming')
    parts.extend(_studio_clauses(package.get('wardrobe'), _WARDROBE_CLAUSES))
    parts.extend(_studio_clauses(package.get('accessories'), _ACCESSORY_CLAUSES))
    parts.extend(_studio_clauses(grooming, _GROOMING_CLAUSES))
    parts.extend(_grime_clauses(grooming))

    if include_lighting:
        lp = (style.get('lighting_profile') or '').strip()
        if lp:
            parts.append(lp)

    return ', '.join(parts)


def enhance_accessories_for_prompt(accessories: str) -> str:
    """Prompt-safe accessories — avoid forcing studs when hoops/drops were chosen."""
    acc = (accessories or '').strip()
    if not acc or acc.lower() in ('none', 'n/a', ''):
        return ''
    low = acc.lower()
    if any(x in low for x in ('no earring', 'without earring', 'bare ears', 'unpierced')):
        return acc
    if 'earring' not in low:
        return acc
    if any(x in low for x in ('hoop', 'drop', 'dangle', 'chandelier', 'huggie', 'threader')):
        return f'{acc}, matching earrings on both ears, symmetrical jewelry'
    if any(x in low for x in ('stud', 'pearl')):
        return f'{acc}, matching identical stud earrings on both ears, symmetrical jewelry'
    return acc


def full_character_descriptor(package: dict[str, Any] | None) -> str:
    """Identity + default presentation (legacy combined prompt shape)."""
    ident = identity_prompt_prefix(package)
    pres = presentation_prompt_fragment(package, include_lighting=True)
    style = (package or {}).get('style_profile', {}) or {}
    bits = [p for p in (ident, pres) if p]
    if style.get('indoor_stage'):
        bits.append('indoor controlled studio environment, consistent lighting')
    return ', '.join(bits)
