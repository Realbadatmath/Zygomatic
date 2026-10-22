#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Melody-vs-bass margin, through the SAMPLER, for every children's style.

Why this exists as a tool rather than a test: the margin is a property of an
ARRANGEMENT (which lead against which pad and bass), not of the code, so it has
to be re-measured whenever `kids_music_theory.STYLES` names a different voice.
`kids_music_service.mix_balance` refuses to ship a run whose tune sits under its
bass by more than `MIX_MARGIN_MIN_DB`, and an ACE-less run of a failing style
therefore delivers nothing at all — a gate that only fires at render time is a
gate nobody sees until a song is missing.

One line per style:

    learning  xylophone/guitar_nylon/double_bass_pizz  margin=+7.31 dB ok

`--require N` turns it into a check: exit 1 if any style is under N dB. That is
what the tree's `verify_cmd` runs; the default N is the service's own gate.

The probe brief is deliberately NOT a real song: 30 seconds, unsung, one fixed
theme, 8 candidates. The margin is decided by the instruments and the note
durations, and none of the three depends on a lyric, so paying for a full
75-second sung composition per style would measure the same number slowly.

    ../.venv/bin/python tools/measure_style_margins.py
    ../.venv/bin/python tools/measure_style_margins.py --require 4.0
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import kids_music_theory as T  # noqa: E402
from zyg_workflows import kids_music_service as S  # noqa: E402


def measure(key, *, candidates=8, seconds=30):
    """(margin_db, voices, note) for one style key. margin_db None = unmeasured."""
    plan = T.compose_best(
        {'theme': 'margin probe', 'style': key, 'seconds': seconds, 'sung': False}, candidates=candidates
    )
    voices = plan.get('voices') or {}
    with tempfile.TemporaryDirectory() as td:
        midi = os.path.join(td, f'{key}.mid')
        S.write_midi(plan, midi)
        mix = S.mix_balance(midi, plan, engine='sampler')
    return mix.get('margin_db'), voices, mix.get('error')


if __name__ == '__main__':  # the CLI lives in measure_style_margins_cli
    from zyg_workflows.tools.measure_style_margins_cli import main as _cli_main

    raise SystemExit(_cli_main())
