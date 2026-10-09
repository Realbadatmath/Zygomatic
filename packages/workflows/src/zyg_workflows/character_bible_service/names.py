# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Random display names, the voice pick and the library label."""

from __future__ import annotations

import json
import os
import logging as _zyg_logging

from zyg_workflows import paths

from .smile import (
    _BIBLE_FILENAME,
    _DATASET_ROOT,
)

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.character_bible_service')


# ── Random display names (first + last) ───────────────────────────────────────
# Keep eye-colour words (e.g. hazel) out of first-name pools — users confuse them.
_FIRST_NAMES_FEMALE = [
    'Elena',
    'Maya',
    'Aria',
    'Nora',
    'Luna',
    'Ivy',
    'Sofia',
    'Mia',
    'Zara',
    'Lila',
    'Isla',
    'Naya',
    'Vera',
    'Cleo',
    'Iris',
    'Juno',
    'Mira',
    'Sage',
    'Wren',
    'Anya',
    'Liv',
    'Eva',
    'Kira',
    'Rhea',
    'Nia',
    'Clara',
    'Naomi',
    'Tessa',
    'Violet',
    'Camila',
    # 2026-07-18 expansion — the library outgrew the original 30.
    'Freya',
    'Amara',
    'Leila',
    'Priya',
    'Sana',
    'Mei',
    'Yuki',
    'Ines',
    'Bianca',
    'Greta',
    'Dahlia',
    'Esme',
    'Noor',
    'Zoya',
    'Alba',
    'Runa',
    'Selin',
    'Adaeze',
    'Imani',
    'Rosa',
    'Petra',
    'Sylvie',
    'Maren',
    'Odessa',
]
_FIRST_NAMES_MALE = [
    'Marcus',
    'Leo',
    'Adrian',
    'Kai',
    'Theo',
    'Milo',
    'Felix',
    'Ezra',
    'Atlas',
    'Jonas',
    'Aiden',
    'Nolan',
    'Ronan',
    'Soren',
    'Caleb',
    'Owen',
    'Hugo',
    'Silas',
    'Cyrus',
    'Dorian',
    'Jasper',
    'Eli',
    'Arlo',
    'Nico',
    'Ethan',
    'Luca',
    'Miles',
    'Declan',
    'Victor',
    # 2026-07-18 expansion.
    'Anders',
    'Bruno',
    'Casper',
    'Dmitri',
    'Emeka',
    'Farid',
    'Gustav',
    'Hiro',
    'Idris',
    'Joaquin',
    'Kenji',
    'Lior',
    'Mateo',
    'Nadir',
    'Oscar',
    'Pavel',
    'Quinn',
    'Ravi',
    'Stellan',
    'Tariq',
    'Umberto',
    'Wesley',
    'Yusuf',
]
_LAST_NAMES = [
    'Reed',
    'Hayes',
    'Brooks',
    'Coleman',
    'Foster',
    'Bennett',
    'Parker',
    'Mitchell',
    'Sullivan',
    'Ramirez',
    'Nguyen',
    'Patel',
    'Kim',
    'Chen',
    'Jackson',
    'Turner',
    'Phillips',
    'Campbell',
    'Rivera',
    'Cooper',
    'Morgan',
    'Bailey',
    'Reyes',
    'Howard',
    'Ward',
    'Torres',
    'Peterson',
    'Gray',
    'Russell',
    'Griffin',
    'Dunn',
    'Walsh',
    'Bryant',
    'Lawson',
    # 2026-07-18 expansion.
    'Ashford',
    'Byrne',
    'Castellanos',
    'Duarte',
    'Eriksen',
    'Fontaine',
    'Grover',
    'Hansen',
    'Ibrahim',
    'Jensen',
    'Kowalski',
    'Lindqvist',
    'Moreau',
    'Novak',
    'Okafor',
    'Pereira',
    'Quintero',
    'Rossi',
    'Sato',
    'Tanaka',
    'Ueda',
    'Vasquez',
    'Weber',
    'Yamada',
    'Zhang',
    'Okonkwo',
]
_EYE_COLOR_WORDS = frozenset(
    {
        'brown',
        'blue',
        'green',
        'hazel',
        'grey',
        'gray',
        'amber',
        'black',
    }
)


def _title_word(word: str) -> str:
    w = (word or '').strip()
    if not w:
        return ''
    return w[0].upper() + w[1:].lower()


def _random_last_name() -> str:
    import random

    return random.choice(_LAST_NAMES)


_NARRATOR_VOICES_PATH = str(paths.DATA_DIR / 'runtime' / 'narrator_voices.json')


def _auto_character_voice(gender: str | None, age, seed_key: str) -> dict | None:
    """Pick an Azure voice profile matching gender + age band (2026-07-18).

    voice_profile used to stay empty until a human picked — the UI voice
    filter then assumed female/25, so a 61-year-old male character got no
    matching suggestion anywhere. Seeded per character for stable variety.
    """
    try:
        with open(_NARRATOR_VOICES_PATH, encoding='utf-8') as fh:
            voices = json.load(fh).get('voices') or {}
    except Exception:
        return None
    try:
        a = int(age)
    except (TypeError, ValueError):
        a = 30
    band = 'young' if a < 33 else ('mid' if a < 58 else 'elder')
    g = (gender or 'female').strip().lower()
    pool = [
        (pid, v)
        for pid, v in voices.items()
        if (v.get('gender') or '').lower() == g and (v.get('age_group') or '') == band
    ] or [(pid, v) for pid, v in voices.items() if (v.get('gender') or '').lower() == g]
    if not pool:
        return None
    import random as _random_v

    pid, v = _random_v.Random(f'zyg-char-voice:{seed_key}').choice(sorted(pool))
    return {'profile_id': pid, 'voice': v.get('voice'), 'label': v.get('label')}


def _existing_display_names() -> set[str]:
    """Lower-cased display names of every character in the library."""
    names: set[str] = set()
    try:
        for cid in os.listdir(_DATASET_ROOT):
            bp = os.path.join(_DATASET_ROOT, cid, _BIBLE_FILENAME)
            if not os.path.isfile(bp):
                continue
            try:
                with open(bp, encoding='utf-8') as fh:
                    n = (json.load(fh).get('display_name') or '').strip().lower()
                if n:
                    names.add(n)
            except (OSError, ValueError) as _exc:
                _zyg_log.debug('bible name skipped, file unreadable: %s', _exc)
                continue
    except OSError as _exc:
        _zyg_log.debug('name scan stopped, bibles directory unreadable: %s', _exc)
    return names


def generate_random_full_name(
    gender: str = 'female',
    avoid_existing: bool = True,
    seed_key: str | None = None,
) -> str:
    """Return a random ``First Last`` display name.

    2026-07-18: draws avoid names already in the character library — pure
    random draws over ~1000 combos produced Kira Dunn / Naya Dunn / Wren Dunn
    plus two Kiras, and nothing stopped an exact full-name collision. Bounded
    retries; a saturated pool falls back to the plain draw.

    ``seed_key`` (2026-07-19): deterministic draw per character. The
    contact-sheet payload is parsed twice (queue + approve); unseeded draws
    named the approval card one thing and built another (run d835e071:
    card 'Naomi Turner', character 'Dahlia Quintero').
    """
    import random

    rng = random.Random(f'zyg-char-name:{seed_key}') if seed_key else random
    pool = _FIRST_NAMES_MALE if (gender or '').strip().lower() == 'male' else _FIRST_NAMES_FEMALE
    taken = _existing_display_names() if avoid_existing else set()
    first = rng.choice(pool) if pool else 'Character'
    name = f'{first} {rng.choice(_LAST_NAMES)}'
    for _ in range(25):
        if name.lower() not in taken:
            break
        first = rng.choice(pool) if pool else 'Character'
        name = f'{first} {rng.choice(_LAST_NAMES)}'
    return name


def resolve_character_display_name(
    raw_name: str | None,
    gender: str = 'female',
    eye_color: str | None = None,
    seed_key: str | None = None,
) -> str:
    """Ensure every character has a first and last name.

    Blank / auto → random full name.  Single token → append random surname.
    Rejects eye-colour tokens accidentally used as names (e.g. ``hazel``).
    Pass ``seed_key`` (char_id) so repeated resolution yields the same name.
    """
    raw = (raw_name or '').strip()
    if not raw or raw.lower() in {'auto', 'none', 'null'}:
        return generate_random_full_name(gender, seed_key=seed_key)
    low = raw.lower()
    if low in _EYE_COLOR_WORDS or (eye_color and low == (eye_color or '').strip().lower()):
        return generate_random_full_name(gender, seed_key=seed_key)
    parts = raw.split()
    if len(parts) == 1:
        return f'{_title_word(parts[0])} {_random_last_name()}'
    first = _title_word(parts[0])
    last = ' '.join(_title_word(p) for p in parts[1:] if p.strip())
    return f'{first} {last}'.strip()


def format_library_label(display_name: str | None) -> str:
    """Short library label: ``Maya Jackson`` → ``Maya J``."""
    parts = (display_name or '').strip().split()
    if not parts:
        return 'Character'
    if len(parts) == 1:
        return parts[0]
    last = parts[-1]
    initial = last[0].upper() if last else ''
    return f'{parts[0]} {initial}' if initial else parts[0]
