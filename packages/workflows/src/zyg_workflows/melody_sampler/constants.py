# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""melody_sampler.constants — the paths, the voice vocabulary and the pitch spelling.

Moved verbatim out of the 1,177-line melody_sampler.py; original lines 49-55, 56-185.
"""

# This module inherits the single file's own top import block; every name in
# it is re-exported from here, so F401 must not strip it.

import argparse
import json
import logging
import os
import random
import sys
import logging as _zyg_logging

from zyg_workflows import paths

# Re-export surface: these five are imported here and not used in this module —
# cli.py reads argparse and sys, sample_index.py json and os, render_engine.py
# random, all with ``from zyg_workflows.melody_sampler.constants import …``.
__all__ = ['argparse', 'json', 'os', 'random', 'sys']

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.melody_sampler')


# _HERE was melody_sampler.py's own directory — the zyg_workflows package directory.
_HERE = str(paths.PKG_DIR)

LOG = logging.getLogger('melody_sampler')

CATEGORY = 'instruments'
LIB_DIR = str(paths.DATA_DIR / 'asset_libraries' / CATEGORY)
SIDECAR = str(paths.DATA_DIR / 'runtime' / f'asset_library_{CATEGORY}_meta.json')
INDEX_CACHE = str(paths.DATA_DIR / 'runtime' / 'melody_sampler_index.json')

SR = 48000

# ── The voice vocabulary ─────────────────────────────────────────────────────
#
# A selector is either
#   ('master', substring)          — matched against the meta's `master` path
#   (pack, instrument, group)      — exact match on those three meta fields
#
# The `master` form exists because for the vcsl and vsco2ce packs the
# `instrument` meta field is WRONG: the ingest put the articulation folder in
# it, so 'Sustains' and 'Pizz' are the "instrument" for a hundred different
# things. The original path is the only honest discriminator there.
#
# Comments carry the measured (count, midi_lo, midi_hi) as of 2026-09-06 —
# tests/test_melody_sampler.py asserts the ranges still hold.
VOICES = {
    'piano': ('master', '/Chordophones/Zithers/Upright Piano, Knight/Sustains/'),
    'grand_piano': ('master', '/Chordophones/Zithers/Grand Piano, Steinway B/Sus/'),
    'guitar_nylon': ('freepats', 'spanish classical guitar', 'samples'),
    'guitar_steel': ('philharmonia', 'guitar', 'guitar — normal'),
    'guitar_electric': ('freepats', 'fsbs electric guitar clean 1', 'bridge'),
    'ukulele': ('freepats', 'ukulele', 'samples'),
    'mandolin': ('philharmonia', 'mandolin', 'mandolin — normal'),
    'banjo': ('philharmonia', 'banjo', 'banjo — normal'),
    'harp': ('master', '/Chordophones/Composite Chordophones/Concert Harp/'),
    'folk_harp': ('master', '/Chordophones/Composite Chordophones/Folk Harp/'),
    'glockenspiel': ('master', '/Idiophones/Struck Idiophones/Glockenspiel/'),
    'xylophone': ('master', '/Idiophones/Struck Idiophones/Xylophone/Medium Mallets/'),
    'marimba': ('master', '/Idiophones/Struck Idiophones/Marimba/'),
    'vibraphone': ('master', '/Idiophones/Struck Idiophones/Vibraphone/Soft Mallets/'),
    'kalimba': ('master', '/Idiophones/Plucked Idiophones/Kalimba, Tanzania/'),
    'hand_chimes': ('master', '/Idiophones/Struck Idiophones/Hand Chimes/'),
    'tubular_bells': ('freepats', 'tubular bells', 'samples'),
    'balafon': ('master', '/Idiophones/Struck Idiophones/Balafon/Soft Mallet/'),
    'steel_drum': ('sfzinstruments', 'jlearman.SteelDrum', 'flac'),
    'recorder': ('master', '/Edge-blown Aerophones/Baroque Soprano Recorder/Sustain/'),
    'recorder_alto': ('master', '/Edge-blown Aerophones/Baroque Alto Recorder/Sustain/'),
    'ocarina': ('freepats', 'ocarina', 'samples'),
    'flute': ('philharmonia', 'flute', 'flute — normal'),
    'clarinet': ('philharmonia', 'clarinet', 'clarinet — normal'),
    'oboe': ('philharmonia', 'oboe', 'oboe — normal'),
    'bassoon': ('philharmonia', 'bassoon', 'bassoon — normal'),
    'harmonica': ('master', '/Free Aerophones/Harmonica-Hohner-Super64/Sustains/Normal/'),
    'trumpet': ('philharmonia', 'trumpet', 'trumpet — normal'),
    'french_horn': ('philharmonia', 'french horn', 'french horn — normal'),
    'trombone': ('philharmonia', 'trombone', 'trombone — normal'),
    'tuba': ('philharmonia', 'tuba', 'tuba — normal'),
    'violin': ('philharmonia', 'violin', 'violin — arco-normal'),
    'violin_pizz': ('philharmonia', 'violin', 'violin — pizz-normal'),
    'violin_trem': ('philharmonia', 'violin', 'violin — arco-tremolo'),
    'viola': ('philharmonia', 'viola', 'viola — arco-normal'),
    'cello': ('philharmonia', 'cello', 'cello — arco-normal'),
    'cello_pizz': ('sfzinstruments', 'karoryfer-bigcat.cello', 'pizzcato'),
    'double_bass': ('philharmonia', 'double bass', 'double bass — arco-normal'),
    'double_bass_pizz': ('philharmonia', 'double bass', 'double bass — pizz-normal'),
    'strings_sus': ('master', '/Strings/Violin Section/susVib/'),
    'strings_sus_low': ('master', '/Strings/Cello Section/susvib/'),
    'strings_pizz': ('master', '/Strings/Violin Section/Pizz/'),
    'strings_trem': ('master', '/Strings/Violin Section/Trem/'),
    'strings_spic': ('master', '/Strings/Violin Section/Spic/'),
    'contrabass_pizz': ('master', '/Strings/Solo Contrabass/Pizz/'),
    'harpsichord': ('master', '/Chordophones/Zithers/Harpsichord, French/Sustains/'),
    'lute': ('master', '/Chordophones/Zithers/Harpsichord, English/Sustains/Lute/'),
    'organ': ('master', '/Edge-blown Aerophones/Pipe Organ/Quiet/'),
    'organ_full': ('master', '/Edge-blown Aerophones/Renaissance Organ/Full/'),
    'bass_electric': ('freepats', 'lately bass', 'samples'),
    # No pitched timpani one-shots were ingested. Left here as a deliberate
    # tombstone so nobody "fixes" the gap by pointing it at a drum folder —
    # timpani stay with the GM percussion kit.
    'timpani': None,
}

# A voice that is notated an octave below where it sounds, or whose recordings
# simply live an octave away from the composer's tessitura (melody 59-77,
# chords 48-65, bass 36-46). Applied by render_plan(); render_events() takes an
# explicit `transpose` so a caller can always override.
VOICE_TRANSPOSE = {
    'glockenspiel': 12,
}

# philharmonia only. 'phrase' is a played musical phrase, not a note, and the
# swelling dynamics are not usable as one-shots at a fixed velocity.
_PH_DROP_LENGTH = {'phrase'}
_PH_SOFT_DROP_LENGTH = {'very-long'}
_PH_DROP_DYNAMIC = {'cresc-decresc', 'crescendo', 'decrescendo', 'molto-pianissimo'}
_PH_LENGTH_S = {'025': 0.25, '05': 0.5, '1': 1.0, '15': 1.5, 'long': 3.0, 'very-long': 6.0}

_MIN_SAMPLES = 6  # below this a voice is unusable; WARN, do not raise

_PC = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}


def _log_noop(*_a, **_k):
    pass


def pitch_to_midi(pitch):
    """'A#4' -> 70, 'Bb3' -> 58, C4 == 60. None for anything unparseable.

    Always read this from the sidecar's `pitch` field, never from the file id:
    the ingest slugs '#' to '_', so 'a_4' is ambiguous between A#4 and A4 (both
    exist, e.g. fp_bagpipe_samples_a_4_31 and fp_bagpipe_samples_a4_31).
    """
    p = str(pitch or '').strip()
    if not p or p[0].upper() not in _PC:
        return None
    val = _PC[p[0].upper()]
    i = 1
    while i < len(p) and p[i] in '#b':
        val += 1 if p[i] == '#' else -1
        i += 1
    try:
        octave = int(p[i:])
    except (ValueError, TypeError):
        return None
    return val + (octave + 1) * 12
