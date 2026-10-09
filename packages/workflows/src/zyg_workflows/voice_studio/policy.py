# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_studio.policy — voice licences, publication policy, the Kyutai donation bank, voice().

Moved verbatim from voice_studio.py lines 569-860 (2026-10-06 split).
"""

from __future__ import annotations

import json
import logging as _zyg_logging
import os
import re

from zyg_workflows.voice_studio.constants import (
    DEFAULT_LINES,
    VOICES,
    _SEED_DIR,
)
from zyg_workflows.voice_studio.benches import (
    _BENCH_DIR,
    _POOL_CAUTION,
    _POOL_LINES,
    _load_pool_voices,
    _load_teen_voices,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.voice_studio')


# ── Voice licences ───────────────────────────────────────────────────────────
#
# No voice carried a machine-readable licence, and derived voices recorded
# nothing at all about what they inherit. Only needed before any voice reaches
# published audio — which today none does, because the TTS stack cannot sing and
# every SVC route failed the file-level licence audit — but a derived voice that
# does not record its parentage cannot be cleared later either.
#
# A derived voice inherits its SOURCE's licence, and the donor-consent question
# rides with it: freezing a Kyutai donor at new (k, m) does not create a new
# donor. See publication_policy() below.
SOURCE_LICENCES = {
    'house': 'in-house recording, owned outright',
    'maya1': 'Maya1 synthetic seed — no human donor',
    'kyutai': 'CC0 1.0 (Kyutai voice donations); donor consent recorded for a SPEECH model — see publication_policy',
    'teen': 'derived: inherits its source voice licence (see source_voice)',
    'bench': 'derived: inherits its source voice licence (see source_voice)',
}


def voice_licence(row):
    """The licence a voice carries, and what it inherits it from."""
    src = str((row or {}).get('source') or '')
    base = src.split(':', 1)[0]
    out = {
        'source': src,
        'licence': SOURCE_LICENCES.get(base, 'UNRECORDED'),
        'derived_from': (row or {}).get('source_voice') or '',
        'inherits': '',
    }
    if base in ('teen', 'bench') and out['derived_from']:
        parent = VOICES.get(out['derived_from']) or {}
        pbase = str(parent.get('source') or '').split(':', 1)[0]
        out['inherits'] = SOURCE_LICENCES.get(pbase, 'UNRECORDED')
    return out


# ── Publication policy ───────────────────────────────────────────────────────
#
# Two independent reasons a registered voice may be fine to AUDITION and not fine
# to PUBLISH. Both are recorded per voice rather than being carried in someone's
# head, because the bank is 294 voices and a picker built on the spec row was
# blind to all of this.
#
# 1. AGE. Thirteen registered voices carry the harvest verdict
#    "CHILD/ADOLESCENT (pitch and size agree)" and four measure below the 13.0 cm
#    pre-pubertal caution line. voice_qc.AGE_BANDS['adolescent'] has no vtl_min
#    and no f0_max, so it structurally CANNOT fail them, and the caution figure
#    was consumed only by a red banner in the HTML and by no Python gate at all.
#    They are kept — deleting them destroys the measurement record — and excluded.
#
# 2. DONOR CONSENT. 227 of 294 voices descend from the Kyutai donations. CC0
#    permits the use, but the recorded consent says donors knew they were giving
#    a voice to a SPEECH model. Whether Dutch portrait rights survive a CC0
#    waiver is not a question this repo can answer, and the operator's standing
#    decision (2026-08-29) is: avoid the Kyutai-descended voices for published
#    audio and use the remaining 67 for now. Auditioning them is unaffected.
_PUBLISH_EXCLUDED_SOURCES = {'kyutai'}
_PUBLISH_EXCLUDED_AGE = {'child', 'adolescent', 'teen_male', 'teen_female'}


def publication_policy(row):
    """Why this voice may or may not reach published audio. Never raises.

    Returns {'publishable': bool, 'blockers': [str], 'age_class', 'source'}.
    """
    blockers = []
    src = str((row or {}).get('source') or '')
    age = str((row or {}).get('age_class') or '')
    base = src.split(':', 1)[0]
    if base in _PUBLISH_EXCLUDED_SOURCES:
        blockers.append('kyutai_donor_consent')
    if age in _PUBLISH_EXCLUDED_AGE:
        blockers.append(f'age_class:{age}')
    if (row or {}).get('reference_only'):
        blockers.append('reference_only')
    try:
        cau = float(row.get('vtl_caution_cm') or 0)
        meas = float(row.get('measured_vtl_cm') or 0)
        if cau and meas and meas < cau:
            blockers.append('below_vtl_caution')
    except (TypeError, ValueError) as _exc:
        _zyg_log.warning('vtl figures are not numeric, below_vtl_caution not evaluated for this voice: %s', _exc)
    return {'publishable': not blockers, 'blockers': blockers, 'age_class': age, 'source': src}


ADULT_AGE_CLASSES = ('adult_male', 'adult_female')


def singable_voices():
    """Voices allowed to reach PUBLISHED audio, adults only.

    Any singer vocabulary must be built from this, server-side. Nothing today
    routes a bank voice into published audio — the TTS stack cannot sing and
    every SVC route failed the licence audit — but a picker that offers a voice
    the policy excludes is a defect waiting for the day one can.
    """
    return {
        vid: v
        for vid, v in VOICES.items()
        if v.get('age_class') in ADULT_AGE_CLASSES and publication_policy(v)['publishable']
    }


def _load_bench_voices() -> dict:
    """Every character-audition bench under voice_seeds/benches/<bench>/.

    One generic loader, not one per character: a bench is fully described by its
    manifest, so adding a cast member is a builder run and not a code change.
    Never raises — an unreadable or absent bench is simply skipped, because a
    half-written manifest must not be able to take the Voices tab down.
    """
    out = {}
    try:
        benches = sorted(os.listdir(_BENCH_DIR))
    except OSError:
        return out
    for bench in benches:
        mpath = os.path.join(_BENCH_DIR, bench, 'manifest.json')
        try:
            with open(mpath, encoding='utf-8') as f:
                man = json.load(f) or {}
        except FileNotFoundError as _exc:
            _zyg_log.debug('bench %s has no manifest yet, skipping: %s', bench, _exc)
            continue
        except (OSError, ValueError) as _exc:
            _zyg_log.warning('bench manifest %s unreadable, continuing without that bench: %s', mpath, _exc)
            continue
        lines = man.get('test_lines') or DEFAULT_LINES
        for row in man.get('voices') or []:
            vid = str(row.get('name') or '').strip().lower()
            wav = str(row.get('wav') or '')
            if not re.match(r'^[a-z0-9][a-z0-9_-]{0,62}$', vid) or not os.path.isfile(wav):
                continue
            sidecar = os.path.splitext(wav)[0] + '.json'
            f0 = row.get('render_f0_hz')
            wear = row.get('render_wear')
            note = str(row.get('note') or '')
            # A candidate that must NOT ship says so in its own name, not only in
            # a JSON field an operator has no reason to open. The unreshaped
            # donor rows exist purely as the anchor to judge the reshapes
            # against; house practice is that a real donor's timbre is always
            # reshaped before a character speaks with it.
            disp = str(row.get('display') or vid)
            if row.get('reference_only'):
                disp += '  [reference only — do not ship]'
            out[vid] = {
                'id': vid,
                'name': disp,
                'role': str(row.get('role') or ''),
                'seed': wav,
                # Candidates, not shipping voices: an identity reference is what
                # a drift gate compares against, and there is nothing to compare
                # against until one is picked.
                'identity_ref': '',
                'meta_json': sidecar if os.path.isfile(sidecar) else '',
                'age_class': str(row.get('age_class') or 'adult_male'),
                'vtl_caution_cm': 14.5,
                'vtl_caution_note': 'below here a male voice starts reading female',
                'default_text': lines[0]['text'],
                'test_lines': lines,
                'note': (
                    (f'Rendered F0 {f0:g} Hz, wear {wear:g}. ' if f0 is not None and wear is not None else '') + note
                ),
                'source': f'bench:{bench}',
                'sex': str(row.get('gender') or 'm'),
                'bench': bench,
                'reference_only': bool(row.get('reference_only')),
                # Optional, and generic: a bench row may name what its seed IS
                # and offer further clips to audition it by. The sung benches
                # need this -- an isolated vocal stem and the same take inside
                # its arrangement are two different questions about one voice --
                # and a bench that declares neither is unchanged.
                'seed_label': str(row.get('seed_label') or ''),
                # `extras` is the general form -- [{label, path}] -- so a bench
                # can offer as many ways of hearing one voice as it has files.
                # `song_mp3` stays as the one-clip shorthand the first sung
                # bench was written against.
                'extra_audio': [
                    e
                    for e in (
                        [{'label': 'in the song', 'path': str(row.get('song_mp3') or '')}]
                        + [
                            {'label': str((x or {}).get('label') or 'clip'), 'path': str((x or {}).get('path') or '')}
                            for x in (row.get('extras') or [])
                        ]
                    )
                    if e['path']
                ],
            }
    return out


# ────────────────────────────────────────────── the Kyutai CC0 donation bank
# 228 voices donated to Kyutai's Unmute Voice Donation Project and released CC0.
# voice_harvest_kyutai.py downloads and classifies them; this only registers what
# that left behind, so a machine without the harvest simply has fewer voices.
#
# These are the first REAL HUMAN voices in the studio. Everything before them was
# Maya1-designed, which is why the pool clusters so tightly — a generator asked
# for sixteen voices returns sixteen samples of its own centre. Donations do not
# share a generator, so this is where actual acoustic range comes from.
#
# Names, sexes and bands here are all derived from MEASUREMENT, because the
# upstream repo ships opaque hex ids and no metadata whatsoever. See the harvest
# module for why the alternative — trusting a written description — is not on the
# table in this codebase.
_KYUTAI_DIR = os.path.join(_SEED_DIR, 'kyutai')
_KYUTAI_MANIFEST = os.path.join(_KYUTAI_DIR, 'manifest.json')

_KYUTAI_NOTE = (
    'CC0 — donated to the Kyutai Unmute Voice Donation Project by a '
    'volunteer who knew they were giving a voice to a speech model, '
    'which is a consent basis a permissive licence alone does not '
    'provide. A REAL HUMAN voice, unlike the Maya1 pool: keep it out '
    "of anything that would put words in an identifiable person's "
    'mouth. Figures below are measured from the SOURCE wav, not from '
    'a render — the engine re-synthesises, so a take can measure '
    'differently. An _enhanced (denoised) copy sits beside the seed; '
    'denoising moves formants, so A/B them rather than assuming '
    'cleaner is better.'
)


# Pulled from the picker on request (2026-08-31): 'kd_butter' ("Deep male ·
# Butter") — an operator call on the voice itself, not a licence or measurement
# problem. Kept as a name, not a deletion from the harvest manifest, so a future
# re-harvest cannot silently resurrect it.
_KYUTAI_EXCLUDED = {'kd_butter'}


def _load_kyutai_voices() -> dict:
    """Build voice entries from the harvest manifest. Never raises — no harvest
    means no Kyutai voices, not a broken tab."""
    try:
        with open(_KYUTAI_MANIFEST, encoding='utf-8') as f:
            man = json.load(f) or {}
    except (OSError, ValueError):
        return {}
    out = {}
    for row in man.get('voices') or []:
        vid = str(row.get('name') or '').strip().lower()
        wav = str(row.get('wav') or '')
        if vid in _KYUTAI_EXCLUDED:
            continue
        if not re.match(r'^[a-z0-9][a-z0-9_-]{0,62}$', vid) or not os.path.isfile(wav):
            continue
        sex = 'f' if str(row.get('gender') or '').startswith('f') else 'm'
        caution_cm, caution_note = _POOL_CAUTION[sex]
        f0, vtl = row.get('f0_hz'), row.get('vtl_cm')
        out[vid] = {
            'id': vid,
            'name': str(row.get('display') or vid),
            'role': str(row.get('role') or ''),
            'seed': wav,
            'identity_ref': '',
            'meta_json': '',
            'age_class': str(row.get('band') or ('adult_male' if sex == 'm' else 'adult_female')),
            'vtl_caution_cm': caution_cm,
            'vtl_caution_note': caution_note,
            'default_text': _POOL_LINES[0]['text'],
            'test_lines': _POOL_LINES,
            'note': (
                f'SOURCE measures F0 {f0:g} Hz, VTL {vtl:g} cm '
                f'({row.get("verdict", "?")}), {row.get("duration_s", "?")}s. '
                if f0 and vtl
                else ''
            )
            + _KYUTAI_NOTE,
            'source': 'kyutai',
            'sex': sex,
        }
    return out


# Abel stays FIRST: the GUI selects voices[0] on boot, and the tab opening on a
# pool seed instead of the shipping narrator would be a regression dressed as a
# feature. The teen bench sits directly behind him because it is the thing
# currently being auditioned and it is ten entries, not two hundred. Kyutai
# last — it is the largest and the least curated.
VOICES.update(_load_teen_voices())
# Character benches sit beside the teen bench for the same reason: they are what
# is actively being auditioned, and they are tens of entries, not hundreds.
VOICES.update(_load_bench_voices())
VOICES.update(_load_pool_voices())
VOICES.update(_load_kyutai_voices())


def voice(vid: str) -> dict:
    return VOICES.get((vid or '').strip().lower()) or {}
