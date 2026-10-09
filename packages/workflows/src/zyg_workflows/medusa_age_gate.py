#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Adults-only floor for the Medusa app. 18+, enforced at BOTH ends.

WHY THIS FILE EXISTS AGAIN
    medusa_pipeline.py's docstring records that on 2026-08-06 the age floor
    (MedusaAgeError on sub-18), the minor-language reject on the free-text
    prompt, and the _assert_adult defence-in-depth recheck were all removed at
    the operator's explicit request, leaving sanitize_char_prompt as whitespace
    normalisation only. That was survivable while the Medusa base was stock
    Qwen-Image, which will not render explicit material at all.

    It stops being survivable the moment a base LoRA is trained to remove that
    limit (bp_medusa_models.py). A pipeline that CAN produce explicit output,
    driven by an uncensored local LLM with no content rules, needs the one floor
    that is not a matter of taste. This module is that floor and nothing else:
    it is an AGE gate, not a content filter. Nothing here restricts subject,
    wardrobe, pose or explicitness for adults — that was the operator's
    instruction and it is respected exactly.

NO ENVIRONMENT OVERRIDE, DELIBERATELY
    Every other guard in this tree carries a ZYG_* escape hatch so an operator
    can restore old behaviour. This one does not, and must not grow one. An
    env var that disables an age floor is indistinguishable from not having the
    floor: it would be set once during a debugging session and never unset.
    MIN_AGE is a module constant. Changing it is a code change with a diff.

BOTH ENDS
    generation — assert_adult_request() on every Medusa character request, and
                 assert_adult_prompt() on any free text that reaches a render.
    dataset    — require_attestation() before any training run can start, so a
                 model LoRA cannot be trained from a set nobody vouched for.
"""

from __future__ import annotations

import re
import time
from typing import Any

MIN_AGE = 18

__all__ = [
    'AUTO_RESOLVES_ADULT_FROM',
    'MIN_AGE',
    'MedusaAgeError',
    'assert_adult_age',
    'assert_adult_prompt',
    'assert_adult_request',
    'attestation_record',
    'require_attestation',
]


class MedusaAgeError(ValueError):
    """Raised when a request or dataset fails the adults-only floor.

    A ValueError subclass so the existing `except ValueError` -> 400 handlers in
    kanban_server / the crews API turn it into a clean rejection rather than a
    500, without every caller needing to know this type.
    """


# ── age parsing ──────────────────────────────────────────────────────────────
# Ages arrive as '32', '32 years old', 'early 30s', or already as an int. Only a
# number we can actually READ is allowed to pass: an unparseable age is a
# rejection, never a default, because defaulting is how a floor gets skipped.
_AGE_NUM_RE = re.compile(r'(\d{1,3})')


def _parse_age(raw: Any) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        n = int(raw)
        return n if 0 < n < 200 else None
    m = _AGE_NUM_RE.search(str(raw or ''))
    if not m:
        return None
    n = int(m.group(1))
    return n if 0 < n < 200 else None


def assert_adult_age(raw: Any, *, field: str = 'age') -> int:
    """Return the parsed age, or raise MedusaAgeError.

    An absent or unreadable age raises. This is the fail-CLOSED direction and it
    is the whole point: the pre-2026-08-06 gate could be walked past simply by
    omitting the field, which is not a floor.
    """
    age = _parse_age(raw)
    if age is None:
        raise MedusaAgeError(
            f'{field} is required and must be a number — Medusa is adults-only '
            f'({MIN_AGE}+), and an unreadable age cannot be checked',
        )
    if age < MIN_AGE:
        raise MedusaAgeError(
            f'{field} {age} is below the {MIN_AGE}+ floor — Medusa generates adults only. This is not configurable.',
        )
    return age


# ── minor-indicating language ────────────────────────────────────────────────
# Word-boundary matched, so 'adult' never trips on 'adultery' and 'teen' never
# trips on 'canteen' / 'sixteenth'. Ordered roughly by how often they show up in
# real prompts. This list guards the AGE of the depicted person only.
_MINOR_TERMS = (
    r'child(?:ren|ish)?',
    r'kid(?:s|die)?',
    r'minor',
    r'underage',
    r'under[\s-]?18',
    r'baby',
    r'babies',
    r'infant',
    r'toddler',
    r'newborn',
    r'neonate',
    r'boy',
    r'girl',
    r'lad',
    r'lass',
    r'teen(?:s|ager|aged|age)?',
    r'pre[\s-]?teen',
    r'tween',
    r'adolescent',
    r'juvenile',
    r'youngster',
    r'youth',
    r'school[\s-]?(?:girl|boy|kid|child|student)',
    r'schoolchild',
    r'pupil',
    r'kindergart(?:en|ner)',
    r'preschool(?:er)?',
    r'elementary[\s-]?school',
    r'middle[\s-]?school',
    r'high[\s-]?school',
    r'primary[\s-]?school',
    r'nursery',
    r'son',
    r'daughter',
    r'grandson',
    r'granddaughter',
    r'niece',
    r'nephew',
    r'stepdaughter',
    r'stepson',
    r'loli(?:ta|con)?',
    r'shota(?:con)?',
    r'jailbait',
    r'\d{1,2}[\s-]?(?:yo|y\.o\.|yr)',
    r'(?:aged?)[\s-]?(?:[0-9]|1[0-7])\b',
    r'little[\s-]?(?:one|girl|boy|sister|brother)',
    r'young[\s-]?(?:girl|boy|child|teen)',
)
_MINOR_RE = re.compile(r'\b(?:' + '|'.join(_MINOR_TERMS) + r')\b', re.IGNORECASE)

# Phrases that are ABOUT an adult and merely contain a flagged word. Stripped
# before the scan so ordinary adult prompts are not rejected for saying
# 'schoolteacher' or 'girlfriend'. Each one is an adult referent on its own.
_ADULT_CONTEXT = (
    r'girl(?:\s?)friend',
    r'boy(?:\s?)friend',
    r'school[\s-]?teacher',
    r'school[\s-]?mistress',
    r'head[\s-]?teacher',
    r'high[\s-]?school[\s-]?(?:teacher|reunion|sweetheart)',
    r'cow[\s-]?boy',
    r'cow[\s-]?girl',
    r'bus[\s-]?boy',
    r'play[\s-]?boy',
    r'old[\s-]?boy',
    r'home[\s-]?boy',
    r'b[\s-]?boy',
    r'tom[\s-]?boy',
    r'girl[\s-]?boss',
    r'it[\s-]?girl',
    r'pin[\s-]?up[\s-]?girl',
    r'bad[\s-]?boy',
    r'boy[\s-]?band',
    r'girl[\s-]?band',
    r'spice[\s-]?girl',
    r'delivery[\s-]?boy',
    r'pool[\s-]?boy',
    r'party[\s-]?girl',
    r'youth(?:ful)?[\s-]?(?:looking|appearance|glow|skin)',
    r'grand(?:son|daughter)[\s-]?of[\s-]?a',
)
_ADULT_CONTEXT_RE = re.compile(r'\b(?:' + '|'.join(_ADULT_CONTEXT) + r')\b', re.IGNORECASE)


def assert_adult_prompt(text: Any, *, field: str = 'prompt') -> str:
    """Return *text* unchanged, or raise MedusaAgeError naming what tripped.

    Rejects rather than silently strips. The pre-2026-08-06 gate stripped
    explicit tokens quietly, which trains an operator to believe a prompt was
    honoured when it was rewritten. A refusal that says which word tripped is
    both more honest and more useful.
    """
    t = str(text or '')
    if not t.strip():
        return t
    scan = _ADULT_CONTEXT_RE.sub(' ', t)
    hit = _MINOR_RE.search(scan)
    if hit:
        raise MedusaAgeError(
            f'{field} rejected: {hit.group(0)!r} indicates a minor. Medusa is '
            f'adults-only ({MIN_AGE}+). Rephrase for an adult subject.',
        )
    return t


# An empty / 'auto' age is NOT an unreadable one: it means "let the system pick",
# and character_bible_service resolves it from 21-75 (70% round((randint(21,45)
# + randint(21,45))/2), 20% 46-60, 10% 61-75 — minimum 21). That resolver is
# what makes 'auto' safe, so this gate depends on it. If that range is ever
# widened below 18, AUTO_RESOLVES_ADULT_FROM here must be updated with it.
_AUTO_AGE_VALUES = (None, '', 'auto', 'any', 'random')
AUTO_RESOLVES_ADULT_FROM = 21

# The bible treats age_range as a second, independent minor signal
# (character_bible_service._MINOR_AGE_RANGES). Accepting a clean 'auto' age next
# to age_range='teen' would walk straight past the age check.
_MINOR_AGE_RANGES = (
    'child',
    'teen',
    'teenager',
    'adolescent',
    'kid',
    'minor',
    'youth',
    'young teen',
    'preteen',
    'tween',
)


def assert_adult_request(
    payload: dict | None,
    *,
    prompt_fields: tuple = ('char_prompt', 'prompt', 'scene_prompt', 'description', 'notes', 'extra_prompt'),
) -> int | None:
    """Whole-request check: age, age_range, and every free-text field.

    Returns the parsed age, or None when the age is left to the system ('auto'),
    which resolves to an adult (see AUTO_RESOLVES_ADULT_FROM). An explicit age
    must parse and be 18+; a non-empty age that does not parse is rejected
    rather than guessed at.
    """
    body = payload or {}
    raw = body.get('age')
    if isinstance(raw, str):
        raw = raw.strip()
    age = None
    if not (raw in _AUTO_AGE_VALUES or (isinstance(raw, str) and raw.lower() in _AUTO_AGE_VALUES)):
        age = assert_adult_age(raw)
    rng = str(body.get('age_range') or '').strip().lower()
    if rng in _MINOR_AGE_RANGES:
        raise MedusaAgeError(
            f'age_range {rng!r} indicates a minor — Medusa is adults-only ({MIN_AGE}+). This is not configurable.',
        )
    for f in prompt_fields:
        if body.get(f):
            assert_adult_prompt(body.get(f), field=f)
    params = body.get('params')
    if isinstance(params, dict):
        for f in prompt_fields:
            if params.get(f):
                assert_adult_prompt(params.get(f), field=f'params.{f}')
    return age


# ── dataset attestation ──────────────────────────────────────────────────────
def attestation_record(who: str = '', note: str = '') -> dict:
    """The record written into a dataset manifest when the operator attests.

    Deliberately a RECORD, not a boolean: a bare True in a JSON file says
    nothing about when or by whom, and this is the field that would matter.
    """
    return {
        'adults_only': True,
        'min_age': MIN_AGE,
        'attested_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'attested_by': str(who or 'operator')[:120],
        'note': str(note or '')[:500],
    }


def require_attestation(meta: dict | None, *, what: str = 'dataset') -> None:
    """Raise unless *meta* carries a valid adult attestation.

    Called before a training run starts. A model LoRA trained from an
    unattested set is exactly the artefact nobody can account for later.
    """
    att = (meta or {}).get('age_attestation') or {}
    if not isinstance(att, dict) or att.get('adults_only') is not True:
        raise MedusaAgeError(
            f'{what} has no adults-only attestation — confirm every subject in '
            f'this dataset is {MIN_AGE}+ before training can start',
        )
    if int(att.get('min_age') or 0) < MIN_AGE:
        raise MedusaAgeError(
            f'{what} attestation records a {att.get("min_age")} floor, below the required {MIN_AGE}',
        )
