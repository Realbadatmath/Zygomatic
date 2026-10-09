#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Melody sampler — play a composed plan with real recorded instruments.

Until now the only renderer for a `kids_music_theory` plan was
``kids_music_service.render_soundfont``: libfluidsynth driving General MIDI
patches out of MuseScore_General.sf3. That is a synthesiser playing an
impression of an instrument. The operator has since ingested 66,028
licence-clean instrument one-shots (``data/asset_libraries/instruments/``,
48 kHz PCM_16) — actual recordings of an actual concert harp, marimba,
recorder, cello section. This module plays a plan with those.

The engine is deliberately small and boring: pick the nearest recorded pitch,
varispeed it to the note that was asked for, window it, add it into a buffer.
No time-stretch, no formant correction, no reverb — a one-shot resampled by a
few semitones is the technique every hardware sampler used, and it is right
here precisely because the sample libraries are dense (a recording every
semitone or two), so the shift is almost always tiny.

Public API (fixed — the workflow calls these by name):

    index()                     {voice_key: [SampleRow, ...]}
    voice_info(key)             count / range / licences / packs
    render_events(events, key)  -> (float32 stereo array, stats)
    arrange_cinematic(plan)     -> {lead|pad|bass|extra: [events]}
    render_plan(plan, out_wav, voices=...)  -> manifest dict
    licence_refs(files) / credits(files)    -> the publish-stage fence

CLI:

    python melody_sampler.py --voices
    python melody_sampler.py --demo out.wav --lead flute --pad guitar_nylon \\
                             --bass double_bass_pizz
    python melody_sampler.py --demo cue.wav --lead trumpet --pad strings_spic \\
                             --bass contrabass_pizz --family cinematic \\
                             --extra marimba:ostinato

Licence note for whoever wires this into a pipeline: the `philharmonia` pack is
`royalty-free-verified` and carries ``no_ai_training: True``. Rendering it
through this module is ordinary DSP and is fine. Feeding the result to
ACE-Step (or any model) as audio conditioning is NOT — check
``render_plan()['packs']`` before you do that.
"""

# Pattern A split (2026-10-07): the 1,177-line melody_sampler.py became this
# package. Every section moved byte for byte into one of the modules below;
# this __init__ re-does the original top import block and re-exports every
# name the single file defined, so `from zyg_workflows import melody_sampler`
# resolves exactly as before.
# ruff: noqa: F401

import argparse
import json
import logging
import os
import random
import sys
import logging as _zyg_logging

# the submodules, in the original section order
from zyg_workflows.melody_sampler import constants
from zyg_workflows.melody_sampler import sample_index
from zyg_workflows.melody_sampler import render_engine
from zyg_workflows.melody_sampler import cinematic
from zyg_workflows.melody_sampler import cli

from zyg_workflows.melody_sampler.constants import (
    _zyg_log,
    _HERE,
    LOG,
    CATEGORY,
    LIB_DIR,
    SIDECAR,
    INDEX_CACHE,
    SR,
    VOICES,
    VOICE_TRANSPOSE,
    _PH_DROP_LENGTH,
    _PH_SOFT_DROP_LENGTH,
    _PH_DROP_DYNAMIC,
    _PH_LENGTH_S,
    _MIN_SAMPLES,
    _PC,
    _log_noop,
    pitch_to_midi,
)
from zyg_workflows.melody_sampler.sample_index import (
    _INDEX,
    _INDEX_STAMP,
    _sidecar_stamp,
    _row,
    _build_index,
    index,
    voice_keys,
    voice_info,
)
from zyg_workflows.melody_sampler.render_engine import (
    _AUDIO_CACHE,
    _resample,
    _read_stereo,
    _sample_audio,
    _dyn_rank,
    _pick,
    render_events,
    V_MEL_STRONG,
    V_MEL_WEAK,
    V_PAD_TOP,
    V_BASS,
    _ROLE_DB,
    _PERC_DB,
    CAL_PEAK,
    _CAL_PROBE,
    _CAL_CACHE,
    _db,
    voice_gain,
    _plan_events,
)
from zyg_workflows.melody_sampler.cinematic import (
    _CIN_ROLE_DB,
    _CIN_EXTRA_DB,
    _CIN_ROLES,
    _CIN_EXTRA_ROLES,
    V_CIN_MEL_STRONG,
    V_CIN_MEL_WEAK,
    V_CIN_PAD_TOP,
    V_CIN_BASS,
    V_CIN_BASS_8TH,
    V_CIN_COUNTER,
    V_CIN_OSTINATO,
    V_CIN_ARPEGGIO,
    CIN_PAD_OVERLAP_S,
    CIN_LEGATO_TAIL_S,
    CIN_CHASE_BPM,
    _vel,
    _cin_arc,
    _cin_triad,
    _cin_chord_id,
    _cin_pad_runs,
    _cin_octave_near,
    arrange_cinematic,
    _cin_extra,
    _is_cinematic,
    _role_events,
    _role_db,
    render_role,
    render_plan,
)
from zyg_workflows.melody_sampler.cli import (
    licence_refs,
    credits,
    _note_name,
    _print_voices,
    parse_extra,
    _demo,
    main,
)
