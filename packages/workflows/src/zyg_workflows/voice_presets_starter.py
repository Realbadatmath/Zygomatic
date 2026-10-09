# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_presets_starter.py — the delivery starter tier for the Voices tab.

WHY THIS EXISTS
---------------
voice_studio shipped with an empty preset store and seventeen voices, which is a
blank canvas and a rotary panel with twenty-five knobs on it. There is no public
library of presets for these knobs to import — Chatterbox and IndexTTS-2 publish
recommended RANGES, not preset packs, and the EQ/dynamics half of the rack is
ordinary broadcast practice. So this file is that library, written down once.

WHAT A STARTER PRESET IS AND IS NOT
-----------------------------------
These are DELIVERY presets: engine sampling knobs plus the post chain. They say
how a line is performed and how the recording is finished. They deliberately do
NOT touch seed_k / seed_m / size / pitch_st — the identity knobs — because those
are per-voice. A `size` value that makes m01 sit right would push f06 straight
through its 13 cm caution line. Identity is chosen by picking the right voice
from the pool and trimming it against the meters; delivery is what transfers.

They are installed as ordinary preset files, one copy per voice, not as a shared
read-only tier. That is the point: the operator is meant to load "Broadcast news"
on f08, find it needs 10 % less de-esser on that particular timbre, and save over
it. A shared library would have to refuse that edit, and the edit is the whole
job. The cost is that improving a starter here does not propagate to voices that
already have it — correct, since by then it is the operator's preset, not ours.

Everything below is still INERT, exactly as voice_studio's docstring promises:
nothing in the narration path reads the preset store.

PROVENANCE OF THE NUMBERS
-------------------------
The engine trio comes from Resemble AI's own guidance for Chatterbox — 0.5/0.5 is
the neutral default, and the interaction that matters is that raising
exaggeration SPEEDS THE READ UP, so expressive presets lower cfg_weight to put
the pacing back. That is the same correction Abel already carries (cfg 0.40
against a measured 221 wpm). `ix_emo_alpha` is set per preset so flipping the
engine select lands somewhere sane rather than on a default that contradicts the
preset's intent; 0.6 or lower is IndexTTS-2's own recommendation whenever the
emotion is inferred from the text.
"""

from __future__ import annotations

import json
import os
import time

from zyg_workflows import voice_studio as vs

# Only non-default knobs are listed. voice_studio.sanitize() fills the rest from
# the spec, so a preset written here still loads after a knob is added or its
# default moves.
STARTERS = [
    (
        'Documentary narrator',
        'Calm, measured, unhurried. The house default for factual narration.',
        {
            'cb_exaggeration': 0.30,
            'cb_cfg_weight': 0.50,
            'cb_temperature': 0.70,
            'ix_emo_alpha': 0.35,
            'hpf': 75,
            'warmth': 1.0,
            'deess': 25,
            'comp': 20,
        },
    ),
    (
        'Audiobook — literary',
        "Grave and deliberate, room for the pauses to land. Abel's shape.",
        {
            'cb_exaggeration': 0.30,
            'cb_cfg_weight': 0.40,
            'cb_temperature': 0.70,
            'ix_emo_alpha': 0.40,
            'tempo': 0.97,
            'hpf': 65,
            'deess': 20,
            'comp': 15,
        },
    ),
    (
        'Audiobook — warm / bedtime',
        'Slow, soft, close. Air pulled back so nothing hisses at low volume.',
        {
            'cb_exaggeration': 0.25,
            'cb_cfg_weight': 0.45,
            'cb_temperature': 0.60,
            'ix_emo_alpha': 0.30,
            'tempo': 0.95,
            'hpf': 70,
            'warmth': 2.0,
            'air': -1.0,
            'deess': 30,
            'comp': 30,
            'lufs': -18.0,
        },
    ),
    (
        'Broadcast news',
        'Brisk, forward, tightly levelled. Presence up, so the de-esser goes up too.',
        {
            'cb_exaggeration': 0.35,
            'cb_cfg_weight': 0.55,
            'cb_temperature': 0.65,
            'ix_emo_alpha': 0.35,
            'tempo': 1.05,
            'hpf': 90,
            'body': -1.5,
            'presence': 2.5,
            'deess': 45,
            'comp': 45,
        },
    ),
    (
        'Explainer / host',
        'Direct-to-camera energy without shouting. Bright but still even.',
        {
            'cb_exaggeration': 0.50,
            'cb_cfg_weight': 0.50,
            'cb_temperature': 0.75,
            'ix_emo_alpha': 0.50,
            'tempo': 1.03,
            'hpf': 80,
            'presence': 1.5,
            'air': 1.0,
            'deess': 35,
            'comp': 35,
        },
    ),
    (
        'Wise mentor',
        'Slow and thoughtful. Low cfg_weight is what buys the deliberate pacing.',
        {
            'cb_exaggeration': 0.30,
            'cb_cfg_weight': 0.30,
            'cb_temperature': 0.60,
            'ix_emo_alpha': 0.40,
            'tempo': 0.93,
            'hpf': 70,
            'warmth': 1.5,
            'deess': 20,
            'comp': 20,
            'room': 8,
        },
    ),
    (
        'Dramatic storyteller',
        'Expressive, with cfg_weight dropped to stop the exaggeration running away.',
        {
            'cb_exaggeration': 0.80,
            'cb_cfg_weight': 0.30,
            'cb_temperature': 0.85,
            'ix_emo_alpha': 0.80,
            'tempo': 0.95,
            'hpf': 70,
            'warmth': 1.0,
            'presence': 1.0,
            'deess': 30,
            'comp': 25,
            'room': 12,
        },
    ),
    (
        'Comic / energetic',
        'Fast and varied. High temperature means takes stop being repeatable.',
        {
            'cb_exaggeration': 0.80,
            'cb_cfg_weight': 0.70,
            'cb_temperature': 1.00,
            'ix_emo_alpha': 0.85,
            'tempo': 1.08,
            'hpf': 85,
            'presence': 2.0,
            'air': 1.5,
            'deess': 40,
            'comp': 40,
            'lufs': -15.0,
        },
    ),
    (
        'Menacing / grave',
        'Heavy and slow, air rolled off. Weight comes from the EQ, not from pitch.',
        {
            'cb_exaggeration': 0.45,
            'cb_cfg_weight': 0.35,
            'cb_temperature': 0.65,
            'ix_emo_alpha': 0.55,
            'tempo': 0.90,
            'hpf': 55,
            'warmth': 3.0,
            'air': -2.0,
            'deess': 15,
            'comp': 30,
            'room': 15,
            'room_ms': 90,
            'lufs': -17.0,
        },
    ),
    (
        'Whisper / confessional',
        'Intimate and quiet. Heavy de-ess, because close and bright means sibilant.',
        {
            'cb_exaggeration': 0.20,
            'cb_cfg_weight': 0.40,
            'cb_temperature': 0.55,
            'ix_emo_alpha': 0.30,
            'tempo': 0.92,
            'hpf': 95,
            'body': -2.0,
            'presence': 2.0,
            'air': 2.5,
            'deess': 55,
            'comp': 50,
            'lufs': -19.0,
        },
    ),
    (
        'Radio drama / period',
        'Deliberately bandlimited — high-passed, mid-forward, air gone, tight room.',
        {
            'cb_exaggeration': 0.55,
            'cb_cfg_weight': 0.40,
            'cb_temperature': 0.80,
            'ix_emo_alpha': 0.60,
            'hpf': 120,
            'mid': 2.5,
            'air': -4.0,
            'deess': 25,
            'comp': 55,
            'room': 20,
            'room_ms': 35,
        },
    ),
]


def install(vid: str, overwrite: bool = False) -> list:
    """Write the starter tier into one voice's preset dir. Idempotent.

    Skips any slug that already exists unless `overwrite` — an operator who tuned
    'Broadcast news' for a particular timbre, or deleted it because it is wrong
    for that voice, has said something, and a re-run must not overrule it.
    Returns the slugs actually written.
    """
    if not vs.voice(vid):
        raise ValueError(f'unknown voice: {vid!r}')
    d = os.path.join(vs.PRESET_ROOT, vid)
    os.makedirs(d, exist_ok=True)
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    written = []
    for name, why, params in STARTERS:
        slug = vs._slugify(name)
        path = os.path.join(d, slug + '.json')
        if os.path.isfile(path) and not overwrite:
            continue
        rec = {
            'name': name,
            'voice': vid,
            'created': now,
            'updated': now,
            # Engine is pinned, not left to the default: the trio below is
            # Chatterbox-specific, and a preset that silently applied nothing
            # because the panel happened to be on IndexTTS-2 would read as the
            # knobs being broken.
            'params': vs.sanitize(dict(params, engine='chatterbox')),
            # Empty on purpose — the GUI only replaces the audition line when a
            # preset carries one, so a starter never clobbers the line the
            # operator is in the middle of comparing against.
            'text': '',
            'metrics': {},
            'builtin': True,
            'why': why,
        }
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(rec, f, indent=2)
        os.replace(tmp, path)
        written.append(slug)
    return written


def install_all(overwrite: bool = False) -> dict:
    """Seed every registered voice. Run this again after adding a voice."""
    return {vid: install(vid, overwrite=overwrite) for vid in vs.VOICES}


if __name__ == '__main__':  # pragma: no cover — operator tool
    import argparse

    ap = argparse.ArgumentParser(description='Install the voice delivery starter tier')
    ap.add_argument('--voice', default='', help='one voice id (default: all)')
    ap.add_argument(
        '--overwrite', action='store_true', help='replace starters that already exist — DISCARDS operator edits'
    )
    a = ap.parse_args()
    res = {a.voice: install(a.voice, a.overwrite)} if a.voice else install_all(a.overwrite)
    total = sum(len(v) for v in res.values())
    for vid, slugs in res.items():
        print(f'{vid:22s} {len(slugs):2d} written' + (f'  ({", ".join(slugs)})' if slugs else '  — already present'))
    print(f'\n{total} preset files written across {len(res)} voices.')
