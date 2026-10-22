# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_studio.constants — module imports, paths, the audition line list and the voice registry.

Moved verbatim from voice_studio.py lines 54-252 (2026-10-06 split).
"""

from __future__ import annotations

import os
import logging as _zyg_logging
from zyg_workflows import paths
from zyg_workflows import provenance_seal as _seal

# What the package re-exports through this module. The pre-split import block
# also bound json, re, shutil, subprocess, threading, time and exe; no sibling
# and no caller reads those names through here, so they are gone. The seal
# binding stays: it is the pipeline's provenance hook.
__all__ = [
    'annotations',
    'os',
    '_zyg_logging',
    'paths',
    '_seal',
]

_zyg_log = _zyg_logging.getLogger('zyg_workflows.voice_studio')


_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SEED_DIR = os.path.join(_HERE, 'data', 'assets', 'voice_seeds')
PRESET_ROOT = os.path.join(_HERE, 'data', 'assets', 'voice_presets')
RENDER_ROOT = os.path.join(_HERE, 'data', 'runtime', 'voice_studio')

_INDEXTTS_DIR = paths.ZYG_INDEXTTS_DIR
_INDEXTTS_PY = os.path.join(_INDEXTTS_DIR, '.venv', 'bin', 'python')
_INDEXTTS_WORKER = os.path.join(_INDEXTTS_DIR, 'indextts2_worker.py')
_CHATTERBOX_DIR = os.environ.get('ZYG_CHATTERBOX_DIR', str(paths.ZYG_LEGACY_MODELS / 'tts_chatterbox'))
_CHATTERBOX_PY = os.path.join(_CHATTERBOX_DIR, '.venv', 'bin', 'python')
_CHATTERBOX_WORKER = os.path.join(_CHATTERBOX_DIR, 'chatterbox_worker.py')
_TTS_CORES = os.environ.get('ZYG_TTS_CORES', '0-19')
_TTS_THREADS = os.environ.get('ZYG_TTS_THREADS', '8')

MAX_PREVIEW_CHARS = 400
_SR = 48000  # render sample rate
_SEED_SR = 24000  # the frozen seeds are 24k mono


# ────────────────────────────────────────────────────────────── the line list
# Two kinds of audition text, and the Line list button shows both:
#
#   DEFAULT_LINES  fixed sentences, the same on every one of the 244 voices, so
#                  two voices can be compared on identical words. That is the
#                  whole point of a reference line — a Kyutai donation and Abel
#                  reading the SAME sentence is a comparison; reading their own
#                  house lines is two anecdotes.
#   test_lines     per-voice READS (neutral / warm / grief / question / numbers /
#                  vowels). Same six jobs everywhere, but the wording is the
#                  voice's own, so Abel auditions on 1672 and a pool voice does
#                  not have to.
#
# Line 1 is canon: Abel's cold open from The Second Ledger, every dialogue line
# in order, stopping before the anchored one-word "Home." that lands over the
# DAY 1 card (storyteller_scene_service.SECOND_LEDGER_INTRO). It is the longest
# line here on purpose — because
# a four-sentence paragraph is where pacing and breath actually show (289 chars,
# well inside MAX_PREVIEW_CHARS).
DEFAULT_LINES = [
    {
        'id': 'ledger_open',
        'label': 'Second Ledger — cold open',
        'why': 'canon: the shipped intro, minus its final anchored word',
        'text': (
            'Five hundred and ninety three days. That is how long we have been '
            'at sea. I am tasked with upkeep of the ledgers, and with writing a '
            'journal of our voyage. The men are tired and malnourished. Our ship '
            'is broken. Yet home is far away, like a distant memory. It is '
            'likely we will not return.'
        ),
    },
    {
        'id': 'epigraph',
        'label': 'The epigraph',
        'why': 'the series epigraph — a semicolon and a long subordinate clause',
        'text': (
            'What we speak is not to be written. What we write is not to be '
            'spoken; therefore, I will tread carefully in the telling of our '
            'journey.'
        ),
    },
    # 227 of the 244 voices are contemporary Kyutai donations. Every other line in
    # this studio is 17th-century maritime, which reads as costume on them — so
    # one plainly modern line, with contractions, since that is where a cloner's
    # elisions either work or clatter.
    {
        'id': 'modern_plain',
        'label': 'Modern / plain speech',
        'why': 'contractions and everyday register — the Kyutai bank is contemporary',
        'text': (
            "I'll be honest with you. I read it twice, and I still don't know "
            "what they want us to do, or who's supposed to decide."
        ),
    },
    # The de-esser and compressor are two of the most-moved knobs on the rack and
    # neither can be judged on a line with nothing to work on.
    {
        'id': 'sibilance',
        'label': 'Sibilance & plosives',
        'why': 'dense /s/ and /p/ — the line to set the de-esser and compressor on',
        'text': (
            'She spoke softly, six or seven sentences at most, and then stopped, '
            'and the whole street seemed to stop with her.'
        ),
    },
    # Loudness is measured over the whole take, so a line that stays at one level
    # cannot show whether the compressor is flattening a performance.
    {
        'id': 'dynamics',
        'label': 'Quiet to loud',
        'why': 'a deliberate dynamic swing — shows compression flattening a read',
        'text': ('Listen. Not a sound now, not one, until I say so. And then, all at once, everything.'),
    },
]


# ─────────────────────────────────────────────────────────── voice registry
# Extensible on purpose: a second character voice is one entry plus its frozen
# seed. `identity_ref` is a known-good RENDER, never the seed — the seed is
# DSP-shifted audio whose formants measure differently from what the model
# re-synthesises (13.87 cm seed vs 11.99 cm render), so gating a render against
# the seed fails on a voice that is actually correct (abel_voice.py, 2026-08-06).
VOICES = {
    'abel': {
        'id': 'abel',
        'name': 'Abel van Haren',
        'role': 'Narrator — The Second Ledger',
        'seed': os.path.join(_SEED_DIR, 'abel_narrator_seed.wav'),
        'identity_ref': os.path.join(_SEED_DIR, 'abel_identity_reference.wav'),
        'meta_json': os.path.join(_SEED_DIR, 'abel_narrator_seed.json'),
        'age_class': 'teen_male',
        # The age band's own vtl_min is 14.0 cm, but the practical floor is
        # higher: adult female measured 14.44 cm on this box, and the two seed
        # candidates rejected during design sat at 14.16 and 14.04 — inside the
        # band, and still reading female. The meter draws this line so a render
        # that technically PASSES but crossed it is visible rather than implied.
        'vtl_caution_cm': 14.5,
        'vtl_caution_note': 'below here the voice starts reading female',
        'default_text': (
            'What we speak is not to be written. What we write is not '
            'to be spoken; therefore, I will tread carefully in the '
            'telling of our journey.'
        ),
        # Ready-made audition lines. Each one exercises something different, and
        # the last exists because MEASUREMENT needs voiced frames: a clipped or
        # consonant-heavy line gives Praat too little to fit formants to, and the
        # VTL meter goes blank on a render that is perfectly fine.
        'test_lines': [
            {
                'id': '1672',
                'label': '1672 opening',
                'text': 'What we speak is not to be written. What we write is not to be '
                'spoken; therefore, I will tread carefully in the telling of '
                'our journey.',
            },
            {
                'id': 'ledger',
                'label': 'Ledger — calm',
                'text': 'The harbour was quiet that morning. I counted the barrels '
                'twice, as my father taught me, and wrote each number in the '
                'ledger. The sea does not forgive a careless hand.',
            },
            {
                'id': 'grief',
                'label': 'Weight / grief',
                'text': 'They brought his coat back, and not him. My mother folded it '
                'as if he were coming for it in the morning.',
            },
            {
                'id': 'question',
                'label': 'Question / rise',
                'text': 'And who, then, was to sign for the cargo? Was it me? A boy of '
                'twelve, with my father three months in the ground?',
            },
            {
                'id': 'numbers',
                'label': 'Numbers & dates',
                'text': 'On the fourteenth of June, sixteen seventy-two, we loaded four '
                'hundred and twenty barrels at eleven guilders the barrel.',
            },
            {
                'id': 'vowels',
                'label': 'Long vowels (for the meters)',
                'text': 'The old road below the harbour rolled on and on, over stone and '
                'water, on toward the open sea.',
            },
        ],
        'note': (
            'Story age 12, VOICE age 14–15 — a deliberate split (the '
            'twelve-year-old render read too young for narration this grave). '
            'Wholly synthetic: no real person, adult or minor, was recorded.'
        ),
        # `source` and `sex` exist only so the rail can filter. Once the sidebar
        # holds hundreds of voices, an unfiltered list is not a feature.
        'source': 'house',
        'sex': 'm',
    },
}
