# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_studio.benches — the Maya1 reference pool and the character audition benches.

Moved verbatim from voice_studio.py lines 253-568 (2026-10-06 split).
"""

from __future__ import annotations

import json
import os
import re

from zyg_workflows.voice_studio.constants import (
    DEFAULT_LINES,
    _SEED_DIR,
)


# ──────────────────────────────────────────────── the Maya1 reference pool
# 16 wholly-synthetic seeds (build_seed_pool.py, Maya1 Apache-2.0 — no human was
# recorded) that tts_service._voice_seed_for has been cloning for months. They
# sat on disk unreachable from this tab, which meant the knob panel could only
# ever tune ONE voice. Registering them costs nothing at render time: a pool
# voice is the same contract as Abel — a frozen wav plus a band to grade it
# against — and the wavs are already 24 kHz mono, exactly what seed_chain wants.
#
# The manifest supplies the wav path, sex and description, so dropping a new seed
# + manifest row makes it appear here. What the manifest CANNOT supply is the
# editorial half below. `band` is a judgement about what a voice is FOR, not a
# measurement: grade m06 against adult_male and its perfectly correct late-teen
# render reports as a failure. `role` is likewise hand-written rather than parsed
# out of the description, because a regex over prose is a silent-wrong-answer
# machine and there are only sixteen of them.
_POOL_DIR = os.path.join(_SEED_DIR, 'pool')
_POOL_MANIFEST = os.path.join(_POOL_DIR, 'manifest.json')

_POOL_EDITORIAL = {
    'm01_warm_baritone': ('Warm Baritone', 'Male · early 40s · documentary narrator', 'adult_male'),
    'm02_bright_tenor': ('Bright Tenor', 'Male · late 20s · friendly, articulate', 'adult_male'),
    'm03_elder_gravel': ('Elder Gravel', 'Male · 60s · British, authoritative elder', 'adult_male'),
    'm04_british_crisp': ('British Crisp', 'Male · 30s · BBC documentary, precise', 'adult_male'),
    'm05_soft_intimate': ('Soft Intimate (m)', 'Male · mid 30s · close-mic audiobook', 'adult_male'),
    # Banded teen_male on the strength of its manifest description ("late teens,
    # youthful") and it FAILED on the first render: 101.9 Hz / 17.35 cm, which
    # voice_qc calls a flat adult male and which misses the teen_male band on
    # BOTH bounds (f0_min 140, vtl_max 16.8). The description is aspirational —
    # Maya1 was asked for a teenager and returned a man. Graded for what it
    # measures, not for what it was ordered as; see _POOL_MEASURED.
    'm06_young_earnest': ('Young Earnest', 'Male · adult, lighter read', 'adult_male'),
    'm07_dark_resonant': ('Dark Resonant', 'Male · 50s · bass, grave, ominous', 'adult_male'),
    'm08_wry_mid': ('Wry Mid', 'Male · 40s · dry, conversational', 'adult_male'),
    'f01_warm_alto': ('Warm Alto', 'Female · late 30s · calm, reassuring', 'adult_female'),
    'f02_bright_clear': ('Bright Clear', 'Female · late 20s · soprano, articulate', 'adult_female'),
    'f03_british_poised': ('British Poised', 'Female · 40s · refined, elegant diction', 'adult_female'),
    'f04_elder_gentle': ('Elder Gentle', 'Female · 60s · British, slow and warm', 'adult_female'),
    'f05_soft_intimate': ('Soft Intimate (f)', 'Female · 30s · breathy, quiet, thoughtful', 'adult_female'),
    # Late teens, but graded adult_female on purpose: the 'adolescent' band has
    # no upper F0 bound, so it would not catch the drift that actually happens to
    # a light young voice — sliding up into child territory.
    'f06_young_light': ('Young Light', 'Female · late teens · open, curious', 'adult_female'),
    'f07_low_smoky': ('Low Smoky', 'Female · 40s · contralto, deliberate', 'adult_female'),
    'f08_crisp_journalist': ('Crisp Journalist', 'Female · 30s · broadcast news, brisk', 'adult_female'),
}

# Abel's 14.5 cm line means "a male voice below here reads female". The mirror of
# it for a female voice is a different number and a different failure: pre-pubertal
# girls measure about 12.7 cm, so a female render sliding under ~13 stops reading
# adult at all. A caution copied across sexes would fire on every single female
# voice in the pool at its correct length, which is how a meter gets ignored.
_POOL_CAUTION = {
    'm': (14.5, 'below here a male voice starts reading female'),
    'f': (13.0, 'below here the voice starts reading pre-pubertal'),
}

# Generic auditions. Same six jobs as Abel's set — plain, warm, heavy, rising,
# numeric, and one deliberately vowel-rich line, because Praat needs voiced frames
# and a consonant-heavy take leaves the VTL meter blank on a render that is fine.
_POOL_LINES = [
    {
        'id': 'neutral',
        'label': 'Neutral read',
        'text': 'The report was delivered on a Tuesday, and nobody read it until the '
        'following spring. By then the numbers had changed.',
    },
    {
        'id': 'warm',
        'label': 'Warm / close',
        'text': 'Come and sit down. There is tea in the pot, and the rain has finally '
        'stopped, and there is nothing at all that needs doing tonight.',
    },
    {
        'id': 'weight',
        'label': 'Weight / grief',
        'text': 'They brought the letter in the morning. I read it twice, and then I '
        'put it in a drawer, and I did not open that drawer for a year.',
    },
    {
        'id': 'question',
        'label': 'Question / rise',
        'text': 'And who exactly was going to pay for it? Me? On what I earn, with two children and a roof that leaks?',
    },
    {
        'id': 'numbers',
        'label': 'Numbers & dates',
        'text': 'On the fourteenth of June, nineteen forty-seven, four hundred and '
        'twenty tonnes crossed the border at eleven marks the tonne.',
    },
    {
        'id': 'vowels',
        'label': 'Long vowels (for the meters)',
        'text': 'The old road below the harbour rolled on and on, over stone and water, on toward the open sea.',
    },
]

_POOL_NOTE = (
    'Wholly synthetic — designed by Maya1 (Apache-2.0) from a written '
    'description, so no real person was recorded and there is no consent '
    'or personality-rights exposure. This is the same pool that '
    'tts_service._voice_seed_for already clones for catalogue voice ids.'
)

# Every seed rendered once through Chatterbox on the 'Documentary narrator'
# starter and measured (2026-08-11, this box). Surfaced in the voice note so the
# operator can see what a seed IS before spending eleven seconds finding out.
#
# Read the columns before trusting a description. The pool is FAR narrower than
# its prose suggests: all eight male seeds land in 88.8–110.9 Hz and 16.8–17.8 cm,
# so "bright tenor" (m02, 110.9) and "dark resonant bass" (m07, 89.3) are about
# two semitones apart with vocal tracts matching to a hundredth of a centimetre.
# The female eight are tighter still. Worse, two labels inverted under
# measurement: f07 "low smoky contralto" reads HIGHER (178.4 Hz) than f01 "warm
# alto" (163.2). Whatever separates these voices by ear, F0 and VTL are not it —
# so pick by ear, and use seed_k when you need real acoustic distance.
_POOL_MEASURED = {
    'm01_warm_baritone': (88.8, 17.06),
    'm02_bright_tenor': (110.9, 17.38),
    'm03_elder_gravel': (99.8, 17.24),
    'm04_british_crisp': (96.2, 16.81),
    'm05_soft_intimate': (88.8, 17.36),
    'm06_young_earnest': (101.9, 17.35),
    'm07_dark_resonant': (89.3, 17.37),
    'm08_wry_mid': (92.1, 17.84),
    'f01_warm_alto': (163.2, 14.62),
    'f02_bright_clear': (186.6, 14.64),
    'f03_british_poised': (183.1, 14.12),
    'f04_elder_gentle': (160.1, 14.67),
    'f05_soft_intimate': (170.2, 14.30),
    'f06_young_light': (175.8, 14.81),
    'f07_low_smoky': (178.4, 14.13),
    'f08_crisp_journalist': (177.8, 14.45),
}


def _load_pool_voices() -> dict:
    """Build voice entries from the seed-pool manifest. Never raises: a missing or
    malformed manifest costs the pool voices, not the tab."""
    try:
        with open(_POOL_MANIFEST, encoding='utf-8') as f:
            man = json.load(f) or {}
    except (OSError, ValueError):
        return {}
    out = {}
    for row in man.get('voices') or []:
        vid = str(row.get('name') or '').strip().lower()
        # The id becomes a URL parameter AND a preset directory name, so anything
        # that is not a plain slug is dropped rather than sanitised — a silently
        # renamed voice would orphan the presets saved under its old name.
        if not vid or not re.match(r'^[a-z0-9][a-z0-9_-]{0,62}$', vid):
            continue
        wav = os.path.join(_POOL_DIR, vid + '.wav')
        if not os.path.isfile(wav):
            continue
        sex = 'f' if str(row.get('gender') or '').lower().startswith('f') else 'm'
        name, role, band = _POOL_EDITORIAL.get(
            vid,
            (
                vid.replace('_', ' ').title(),
                ('Female' if sex == 'f' else 'Male') + ' · pool seed',
                'adult_female' if sex == 'f' else 'adult_male',
            ),
        )
        caution_cm, caution_note = _POOL_CAUTION[sex]
        desc = str(row.get('description') or '').strip()
        meas = _POOL_MEASURED.get(vid)
        meas_txt = f' MEASURED on this box: F0 {meas[0]:g} Hz, VTL {meas[1]:g} cm.' if meas else ''
        out[vid] = {
            'id': vid,
            'name': name,
            'role': role,
            'seed': wav,
            # No identity reference and no per-voice seed JSON: these were
            # DESIGNED, not tuned through a rejected-candidate loop the way Abel
            # was, so there is no known-good render to gate drift against yet.
            # Saving a preset with its audition wav is how one gets created.
            'identity_ref': '',
            'meta_json': '',
            'age_class': band,
            'vtl_caution_cm': caution_cm,
            'vtl_caution_note': caution_note,
            'default_text': _POOL_LINES[0]['text'],
            'test_lines': _POOL_LINES,
            'note': (desc + ' — ' if desc else '') + _POOL_NOTE + meas_txt,
            'source': 'maya1',
            'sex': sex,
        }
    return out


# ─────────────────────────────────────────────── the teen-male audition bench
# Ten candidate boys' voices, built 2026-08-12 by build_teen_voices.py: a source
# seed reshaped with the studio's own seed_k/seed_m and FROZEN, exactly the way
# Abel was made. Each one is a voice in its own right here — knobs back at their
# defaults, the shaping already baked into the wav — so auditioning them is a
# click rather than a pair of numbers to retype.
#
# WHY THEY ARE NOT BUILT FROM THE ADULT-MALE POOL, which is the obvious move and
# is wrong. Measured on this box: seed_k shrinks the tract and lifts pitch
# together; seed_m BELOW 1.0 lowers pitch and GROWS the tract (+1.35 cm on the
# seed at m=0.90 — rubberband's formant preservation over-corrects downward on
# this build); seed_m ABOVE 1.0 lifts pitch but drags the formants up with it and
# collapses the tract. So there is no knob combination that turns a 90 Hz /
# 17.3 cm adult male into a 170 Hz teenager with a teenage tract: pushing m to
# 1.36 on one candidate measured 203.6 Hz over a 12.93 cm tract, i.e. an
# eight-year-old. All eight Maya1 male seeds sit at 88–107 Hz and cannot reach
# the band at any defensible tract.
#
# A boy mid-voice-change is not a shrunken man. His PITCH is already near adult
# female (150–180 Hz) while his TRACT is between the two adult sizes (~15–16 cm
# against 14.4 female / 17.3 male measured here). That is reached by starting
# from a LIGHT voice and moving down and outward — k to set the body, m<1 to put
# the pitch back without giving the body away.
_TEEN_DIR = os.path.join(_SEED_DIR, 'teens')
_TEEN_MANIFEST = os.path.join(_TEEN_DIR, 'manifest.json')

# ── character audition benches ───────────────────────────────────────────────
# The teen bench proved the shape: freeze N reshapes of a source as real seeds,
# register them as VOICES, and auditioning a candidate becomes a click instead of
# two numbers retyped into the knob rack. Casting a character is the same job, so
# it gets the same machinery rather than a second copy of it — one directory per
# bench under benches/, each with a manifest the builder writes. A machine with
# no benches simply has none; nothing here is required for the tab to run.
_BENCH_DIR = os.path.join(_SEED_DIR, 'benches')

# Abel's six lines are all 17th-century maritime and his own story; these voices
# are being auditioned as CHARACTERS, not as Abel understudies. What a listener
# actually judges a teenage voice on is whether it holds together under strain —
# a break, a shout, a sulk — so the set is built around those rather than around
# tone colour.
_TEEN_LINES = [
    {
        'id': 'plain',
        'label': 'Plain / level',
        'text': 'I waited by the gate for an hour, and then I walked home the long '
        'way, because I did not want to explain where I had been.',
    },
    {
        'id': 'defiant',
        'label': 'Defiance / push',
        'text': 'I am not a child. I carried it up three flights on my own and not '
        'one of you noticed, so do not tell me what I can lift.',
    },
    # The register break is the single most teenage thing a voice does, and it
    # only shows on a line that climbs.
    {
        'id': 'break',
        'label': 'Rising / where a voice cracks',
        'text': 'Wait — wait, stop, you cannot just take it, it is mine, I said it is mine!',
    },
    {
        'id': 'quiet',
        'label': 'Quiet / confiding',
        'text': 'Can I tell you something? I have not told anybody. I think I made '
        'a mistake, and I do not know how to undo it.',
    },
    {
        'id': 'ledger',
        'label': 'Ledger — grave narration',
        'text': 'The harbour was quiet that morning. I counted the barrels twice, '
        'as my father taught me, and wrote each number in the ledger.',
    },
    # Praat needs voiced frames; a consonant-heavy line leaves the VTL meter
    # blank on a render that is perfectly fine.
    {
        'id': 'vowels',
        'label': 'Long vowels (for the meters)',
        'text': 'The old road below the harbour rolled on and on, over stone and water, on toward the open sea.',
    },
]


def _load_teen_voices() -> dict:
    """Build voice entries from the teen manifest. Never raises — a machine that
    has not run the builder simply has no teen bench."""
    try:
        with open(_TEEN_MANIFEST, encoding='utf-8') as f:
            man = json.load(f) or {}
    except (OSError, ValueError):
        return {}
    out = {}
    for row in man.get('voices') or []:
        vid = str(row.get('name') or '').strip().lower()
        wav = str(row.get('wav') or '')
        if not re.match(r'^[a-z0-9][a-z0-9_-]{0,62}$', vid) or not os.path.isfile(wav):
            continue
        f0, vtl = row.get('render_f0_hz'), row.get('render_vtl_cm')
        sidecar = os.path.splitext(wav)[0] + '.json'
        out[vid] = {
            'id': vid,
            'name': str(row.get('display') or vid),
            'role': str(row.get('role') or ''),
            'seed': wav,
            # No identity reference: these are candidates, not shipping voices.
            # One becomes an identity ref the moment it is picked and a known-good
            # render exists to gate drift against — the way Abel got his.
            'identity_ref': '',
            'meta_json': sidecar if os.path.isfile(sidecar) else '',
            'age_class': 'teen_male',
            # Same line Abel is held to, and for the same reason: adult female
            # measures 14.44 cm on this box, so a male render below ~14.5 reads
            # female no matter how right the pitch is.
            'vtl_caution_cm': 14.5,
            'vtl_caution_note': 'below here the voice starts reading female',
            'default_text': DEFAULT_LINES[0]['text'],
            'test_lines': _TEEN_LINES,
            'note': (
                (f'Tuned to F0 {f0:g} Hz / VTL {vtl:g} cm as measured on the cold-open line. ' if f0 and vtl else '')
                + str(row.get('note') or '')
            ),
            'source': 'teen',
            'sex': 'm',
        }
    return out
