#!/usr/bin/env python

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""vb_speaker_bench -- does ECAPA actually tell one voice from another here?

The proof behind voice_ext/speaker.py's threshold. Takes the Abel narrator seed,
cuts it in HALF (two different sentences, same speaker), and takes one seed from
the reference pool (a different speaker entirely), then prints three cosines:

    same   abel_A  vs abel_B        -- must be high
    cross  abel_A  vs other         -- must be low
    cross  abel_B  vs other

PASS requires  same - max(cross) >= MARGIN (0.15). That margin is the whole
claim: anything above it means a threshold exists that admits the operator and
refuses everyone else. It says nothing about recordings of the operator -- see
docs/voice_bridge_speaker.md.

Run from ZYG_CREWS_ROOT (the legacy production tree) with its own venv, ZYG_LEGACY_VENV_PY:
    ../.venv/bin/python tools/vb_speaker_bench.py
    ../.venv/bin/python tools/vb_speaker_bench.py --other f01_warm_alto
"""

import os
import sys
import wave

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

ABEL = os.path.join(HERE, 'data', 'assets', 'voice_seeds', 'abel_narrator_seed.wav')
POOL = os.path.join(HERE, 'data', 'assets', 'voice_seeds', 'pool')
MARGIN = 0.15


def _half(src, dst, which):
    """Write the first or second half of a wav to dst."""
    with wave.open(src, 'rb') as w:
        total = w.getnframes()
        half = total // 2
        if which == 1:
            w.setpos(half)
            frames = w.readframes(total - half)
        else:
            frames = w.readframes(half)
        params = w.getparams()
    with wave.open(dst, 'wb') as out:
        out.setnchannels(params.nchannels)
        out.setsampwidth(params.sampwidth)
        out.setframerate(params.framerate)
        out.writeframes(frames)
    return (total - half if which == 1 else half) / float(params.framerate)


if __name__ == '__main__':  # the CLI lives in vb_speaker_bench_cli
    from zyg_workflows.tools.vb_speaker_bench_cli import main as _cli_main

    raise SystemExit(_cli_main())
