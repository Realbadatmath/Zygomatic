# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Skin / hair / age descriptors and the negative prompts that protect them."""

from __future__ import annotations

from typing import Any


from .references import (
    _env_on,
)


# Photoreal skin texture — shared across prompts, briefs, and ComfyUI negatives.
PHOTOREAL_SKIN_EXTRA = (
    'visible skin pores, natural skin microdetail, unretouched, '
    'no beauty filter, subtle skin imperfections, fine film grain'
)
PHOTOREAL_SKIN_NEG = (
    'airbrushed, plastic skin, beauty filter, overly smooth skin, '
    'doll face, wax skin, porcelain skin, heavy retouching, makeup filter'
)

# Skin-tone swatch word -> strong, unambiguous descriptor. A bare "dark skin"
# token loses to FLUX-dev's light-skin prior + bright studio lighting; rich
# melanin phrasing lands reliably. Custom values pass through as "<word> skin".
_SKIN_TONE_PHRASE = {
    'fair': 'fair pale skin',
    'light': 'light skin',
    # Truly neutral middle option (2026-07-16): 'medium' below is deliberately
    # warm/tan-leaning (skin-tone defence era) and reads darker than the word
    # suggests — operators wanting a neutral middle tone pick medium-light.
    'medium-light': 'light-medium neutral skin tone, balanced natural complexion',
    'medium': 'medium warm skin tone',
    # Richer descriptors below — bare "olive-toned" and "tan" lose to FLUX-dev's
    # light-skin prior at low cfg. Multi-token melanin phrasing (warm, tawny,
    # visibly tanned) gives the cross-attention more hooks to pull the render
    # toward the intended tone.
    'olive': 'light olive skin, warm olive Mediterranean complexion, greenish-tan olive undertone, sun-kissed light-olive skin, NOT dark brown',
    'tan': 'tan warm light-brown skin, visibly sun-tanned medium-brown complexion, tawny warm skin tone',
    'dark': 'dark brown skin, richly melanated warm dark complexion, deep warm brown skin tone',
    'deep': 'deep dark ebony skin, very dark brown skin, richly melanated deep complexion, near-black skin tone',
}
# Tones that must be actively defended against FLUX lightening them (fed into the
# negative prompt so "lighter/paler skin" is pushed away).
_DARK_SKIN_TONES = ('olive', 'tan', 'dark', 'deep')


# Region-free variants (2026-07-18): the strong 'olive' phrase names
# "Mediterranean", which fights a non-Mediterranean ethnic_heritage token in
# the same prompt (run 59f1f012: 'South Asian heritage' + 'Mediterranean skin'
# cancelled each other). When a heritage is present, use the neutral phrasing.
_SKIN_TONE_PHRASE_NEUTRAL = {
    'olive': 'light olive skin tone, warm greenish-tan olive complexion, light-olive sun-kissed undertone, NOT dark brown',
}

# Symmetric skin-tone defence (2026-07-21). The old defence (_DARK_SKIN_TONES +
# comfy_generation_service) only protected DARK tones from being lightened, and
# implicitly trusted FLUX's prior to hold fair/light — which fails when a
# dark-associated heritage token ("Caribbean heritage") sits in the same prompt
# and drags the skin brown (Noor Jensen: olive spec → brown render). A
# light-skinned member of a dark-associated heritage is common in reality, so
# skin tone must be defended in BOTH directions, independently of heritage.
_SKIN_SCALE_ORDER = ('fair', 'light', 'medium-light', 'medium', 'olive', 'tan', 'dark', 'deep')
_SKIN_NEG_PHRASE = {
    'fair': 'fair skin, pale skin',
    'light': 'light skin',
    'medium-light': 'light-medium skin',
    'medium': 'medium skin tone',
    'olive': 'olive skin',
    'tan': 'tan skin, sun-tanned skin',
    'dark': 'dark brown skin',
    'deep': 'deep dark skin, ebony skin, near-black skin',
}


def skin_tone_negatives(skin_tone: str, heritage: str | None = None) -> str:
    """Return contradicting-direction skin descriptors to push into the negative
    prompt, defending the REQUESTED tone against both the model's light-skin
    prior AND a heritage token that implies a different tone (2026-07-21).

    Generalises the old dark-only defence: every tone gets the tones ≥2 steps
    away on the scale negated (±1 step kept as tolerance), plus a directional
    catch-all. `heritage` is accepted for signature symmetry with
    describe_skin_tone but does not change the DIRECTION — the requested tone
    alone decides what to suppress, which is exactly what decouples skin from
    heritage. Empty string for an unknown/blank tone.
    """
    s = (skin_tone or '').strip().lower()
    if s not in _SKIN_SCALE_ORDER:
        return ''
    idx = _SKIN_SCALE_ORDER.index(s)
    terms: list[str] = []
    # Tones ≥2 steps DARKER than requested (defends a lighter request — the
    # fair-skin-on-dark-heritage case).
    for i in range(idx + 2, len(_SKIN_SCALE_ORDER)):
        terms.append(_SKIN_NEG_PHRASE[_SKIN_SCALE_ORDER[i]])
    # Tones ≥2 steps LIGHTER than requested (defends a darker request).
    for i in range(0, idx - 1):
        terms.append(_SKIN_NEG_PHRASE[_SKIN_SCALE_ORDER[i]])
    # Directional catch-all for extra cross-attention pull.
    if idx <= 2:
        terms.append('darkened skin, brown skin, deep skin tone')
    elif idx >= 5:
        terms.append('lightened skin tone, whitewashed skin, pale complexion')
    # Olive-specific booster (2026-07-22): olive sits one step from 'medium' so
    # the ±1 tolerance lets a Caribbean prior drag it to medium/deep BROWN
    # (Maren). Push the too-brown neighbours olive alone cannot reach.
    if s == 'olive':
        terms.append('deep brown skin, dark brown skin, muddy brown complexion, warm-brown skin')
    seen: set = set()
    out: list[str] = []
    for t in terms:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return ', '.join(out)


# Symmetric hair-colour defence (2026-07-22). Hair had the same one-directional
# coupling skin did: the negative defended only BLACK (by negating browns), so a
# lighter selection (brown/auburn/red/blonde) had NOTHING pushing back against
# the heritage/dark prior and rendered black (Maren Novak: brown → black, then
# the judge over-called it and synced the bible to black). Every colour now
# negates the contradicting ones so the SELECTED colour holds.
_HAIR_NEG_BY_COLOR = {
    'black': 'brown hair, auburn hair, blonde hair, red hair, grey hair',
    'brown': 'black hair, jet black hair',
    'dark brown': 'jet black hair, pure black hair',
    'light brown': 'black hair, dark hair, jet black hair',
    'auburn': 'black hair, dark brown hair, jet black hair',
    'red': 'black hair, dark brown hair, brown hair, jet black hair',
    'blonde': 'black hair, dark brown hair, brown hair, dark hair',
    'grey': 'black hair, dark brown hair, brown hair, dark hair',
    'gray': 'black hair, dark brown hair, brown hair, dark hair',
    'white': 'black hair, dark brown hair, brown hair, grey hair, dark hair',
    'silver': 'black hair, dark brown hair, brown hair, dark hair',
}


def hair_color_negatives(hair_color: str, heritage: str | None = None) -> str:
    """Contradicting hair-colour descriptors to push into the negative, so the
    REQUESTED colour holds against the model's dark-hair prior AND a heritage
    token implying dark hair (2026-07-22). `heritage` is accepted for signature
    symmetry with the skin defence but does not change the direction. Empty for
    an unknown/blank colour."""
    h = (hair_color or '').strip().lower()
    return _HAIR_NEG_BY_COLOR.get(h, '')


def age_negatives(age) -> str:
    """Push the WRONG age band into the negative (2026-07-22). FLUX skews every
    face toward a smooth mid-20s glamour attractor, so a 34/45/60 spec renders
    too young and tiles read as a 'different, prettier, younger woman' (Maren
    Novak). Age is a weak positive lever; a strong band negative is the cheap,
    generation-time defence (no regen). Empty for a young-adult spec that FLUX
    hits natively, or an unparseable age."""
    try:
        a = int(age)
    except (TypeError, ValueError):
        return ''
    if a >= 55:
        return 'young woman, youthful face, twenties, thirties, smooth young skin, teenager, child, glamour model'
    if a >= 45:
        return 'young woman, youthful face, early twenties, teenager, baby face, child'
    if a >= 33:
        return 'teenager, very young face, baby face, child, early twenties glamour model'
    # 2026-07-31: MINORS. The old <=20 band only pushed away from OLD — it had
    # nothing pushing away from an ADULT BODY, so a 12-year-old spec rendered
    # FLUX/SDXL's mid-20s adult default and no gate anywhere measured age.
    # ZYG_MINOR_AGE_LOCK=0 restores the pre-2026-07-31 weak band.
    if a < 18 and _env_on('ZYG_MINOR_AGE_LOCK'):
        return f'{_MINOR_SAFETY_NEG}, {_AGED_UP_NEG}'
    if a <= 20:
        return 'middle-aged, elderly, old woman, deep wrinkles, grey hair, aged sagging skin'
    return ''


# ── Minor-safety negatives (2026-07-31) ──────────────────────────────────────
# Applied UNCONDITIONALLY (not gated on studio_preview) for under-18 characters:
# the storyteller calls generate_still with studio_preview=False, so every
# age/hair/skin defence in build_locked_negative_prompt was skipped for scene
# renders and a 12-year-old boy's only protection was a hand-typed string in
# his bible. Anything created through the normal flow had none.
_MINOR_SAFETY_NEG = (
    'adult, grown man, grown woman, mature adult body, adult proportions, '
    'adult facial features, muscular, broad shoulders, beard, stubble, '
    'cleavage, breasts, busty, curvy figure, sexualized, revealing clothing'
)
# The other direction (a child spec must not be aged DOWN into a baby, nor up
# into a wrinkled face) — kept separate so callers can use either alone.
_AGED_UP_NEG = 'middle-aged, elderly, deep wrinkles, grey hair, aged sagging skin'

_MINOR_AGE_RANGES = ('child', 'teen', 'teenager', 'adolescent', 'kid')

# Gendered child/teen noun — '12-year-old male' is a weak, clinical lever;
# '12-year-old boy' is the token the models actually cluster on.
_MINOR_GENDER_NOUN = {
    'male': 'boy',
    'man': 'boy',
    'boy': 'boy',
    'm': 'boy',
    'female': 'girl',
    'woman': 'girl',
    'girl': 'girl',
    'f': 'girl',
}


def is_minor_identity(identity: dict[str, Any] | None) -> bool:
    """True when the bible identity describes an under-18 character.

    ``age`` is authoritative; ``age_range`` is a second, independent signal so a
    record whose age is missing/garbage still trips the minor defences (the
    zpub local-fallback path can deliver ``age: null``).
    """
    ident = identity or {}
    try:
        a = int(ident.get('age'))
    except (TypeError, ValueError):
        a = None
    if a is not None and a < 18:
        return True
    return str(ident.get('age_range') or '').strip().lower() in _MINOR_AGE_RANGES


def minor_safety_negatives(identity: dict[str, Any] | None) -> str:
    """Adult-body negatives for an under-18 character (empty for adults)."""
    if not _env_on('ZYG_MINOR_AGE_LOCK'):
        return ''
    return _MINOR_SAFETY_NEG if is_minor_identity(identity) else ''


def age_prompt_phrase(age, gender: str) -> str:
    """Age-reinforced person noun for the identity prompt (2026-07-22): a bare
    '34-year-old woman' is a weak lever, so append maturity cues for older
    specs to bias FLUX away from its young default.

    2026-07-31: under-18 specs get the same treatment in the other direction —
    a gendered child/teen noun plus explicit child/teen proportions, because
    nothing else in the storyteller render path asserts age at all.
    """
    g = (gender or 'person').strip() or 'person'
    try:
        a = int(age)
    except (TypeError, ValueError):
        return f'{g} character'
    if a >= 60:
        return f'{a}-year-old {g}, elderly senior, visible age lines, mature aged features'
    if a >= 45:
        return f'{a}-year-old {g}, middle-aged, mature adult, age-appropriate lines and features'
    if a >= 33:
        return f'{a}-year-old {g}, mature adult, age-appropriate adult features, not youthful'
    if a < 18 and _env_on('ZYG_MINOR_AGE_LOCK'):
        n = _MINOR_GENDER_NOUN.get(g.strip().lower(), 'child')
        if a < 13:
            return (
                f'{a}-year-old {n}, young child, child body proportions, '
                f'small child frame, childlike facial features, clearly a child, '
                f'not an adult'
            )
        return f'{a}-year-old teenage {n}, adolescent teenager, teenage face, slim teenage frame, not an adult'
    return f'{a}-year-old {g}'


def describe_skin_tone(skin_tone: str, heritage: str | None = None) -> str:
    """Map a skin-tone swatch word to a strong prompt phrase (empty if unset).

    Pass the character's ``ethnic_heritage`` so region-naming phrases are
    swapped for neutral ones when they would contradict it.
    """
    s = (skin_tone or '').strip().lower()
    if not s:
        return ''
    phrase = _SKIN_TONE_PHRASE.get(s, f'{s} skin')
    her = (heritage or '').strip().lower()
    if her and 'mediterranean' not in her and 'mediterranean' in phrase.lower():
        phrase = _SKIN_TONE_PHRASE_NEUTRAL.get(s, phrase)
    return phrase
