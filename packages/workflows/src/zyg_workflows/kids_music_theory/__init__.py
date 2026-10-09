# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kids_music_theory.py — deterministic, constraint-driven composer for the
Children's Music workflow.  Melody and rhythm are CONSTRUCTED here, not sampled
from a model, and then MEASURED by ``score_plan`` against the properties that
actually make a children's song singable.

Why this module exists at all
─────────────────────────────
ACE-Step 1.5 (the pipeline's live music generator) renders a convincing
production, but nothing about a text-to-audio model lets you state — let alone
verify — "the range is one octave, the leaps resolve, every downbeat is a chord
tone, the tune ends on the tonic".  For a children's song those are not stylistic
preferences, they are the whole brief: a four-year-old can only sing back a tune
that stays inside their range and moves mostly by step.  So the melody is built
under hard constraints, scored, and only then handed to the renderers.  The
symbolic plan is the ground truth; the audio is a rendering of it.

Everything here is plain Python + the standard library.  No model, no weights,
no licence surface.

Units
─────
Time is in QUARTER-NOTE BEATS throughout (floats), including compound meters:
a 6/8 bar is 3.0 beats long with strong positions at 0.0 and 1.5.  That keeps one
arithmetic for every meter and makes the MIDI writer trivial (ticks = beats *
ticks_per_beat).

Pitch is carried as a SCALE INDEX (integer; 0 = tonic in the base octave, +1 =
next scale degree up, so ±1 is literally "a step") and converted to MIDI only at
the end.  Diatonic-by-construction: there is no way for the generator to emit an
accidental, and "stepwise motion" is the cheapest move in the search rather than
something checked afterwards.

Public API
──────────
    compose(brief, *, seed=None)         -> plan dict  (one candidate)
    compose_best(brief, *, candidates=..) -> plan dict  (seed search, best score)
    score_plan(plan)                     -> dict of measured metrics + verdict
    AGE_BANDS / MOODS / METERS / MODES   -> the option vocabulary for the UI
"""

# ruff: noqa: F401  (this package is a re-export facade for the module it replaced)

from __future__ import annotations


import math
import random
import statistics


from zyg_workflows.kids_music_theory.vocabulary import (
    AGE_BANDS,
    LYRIC_LINE_CAP,
    MODES,
    MOODS,
    NAME_TO_PC,
    PARENT_OF,
    PITCH_NAMES,
)

from zyg_workflows.kids_music_theory.styles import (
    EXCLUDED_STYLES,
    SONG_SECONDS,
    SONG_SECONDS_DEFAULT,
    SONG_SECONDS_HARD,
    STYLES,
    STYLE_FAMILY,
    _SONG_SECONDS_STEPS,
    song_seconds,
)

from zyg_workflows.kids_music_theory.cinematic import (
    CINEMATIC_FAMILY,
    CINEMATIC_STYLES,
    CLAP_NEGATIVES,
    DEFAULT_CLAP_POS,
    DEFAULT_THEME,
    EXTRA_ROLES,
    LYRICS_MODES,
    STYLE_FAMILIES,
    clap_captions,
    clap_negatives,
    style_for_plan,
    style_lookup,
)

from zyg_workflows.kids_music_theory.singers import (
    DEFAULT_SINGER,
    GM_LEAD_GAIN,
    GM_LEAD_GAIN_DEFAULT,
    SINGERS,
    SINGER_NEGATIVE,
    lead_gain,
)

from zyg_workflows.kids_music_theory.forms import FORMS, METERS, PROGRESSIONS, QUALITY, ROMAN

from zyg_workflows.kids_music_theory.rhythm import _CELLS, _cell_ok, _cells_for, _onsets, _pick_line_rhythm

from zyg_workflows.kids_music_theory.pitch import (
    _ARCH,
    _Composer,
    _bar_of,
    _chord_degrees,
    _chord_pcs,
    _contour_target,
    _index_pcs,
    _is_strong,
    _note_name,
    _scale_midi,
)

from zyg_workflows.kids_music_theory.brief_prep import (
    _VOWELS,
    _lines_per_section,
    _narrow_band_for_singer,
    _normalise_brief,
    _plan_sections,
    _progressions_for,
    _syllable_targets,
    count_syllables,
    lyric_hint_for,
    ui_spec,
)

from zyg_workflows.kids_music_theory.score import score_plan

from zyg_workflows.kids_music_theory.composer import compose, compose_best

from zyg_workflows.kids_music_theory.selftest import _selftest
