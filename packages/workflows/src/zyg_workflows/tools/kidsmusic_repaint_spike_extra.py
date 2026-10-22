# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kidsmusic_repaint_spike_extra.py — second-pass measures on the repaint spike.

Reads output/kidsmusic/_repaint_spike/*.flac (made by kidsmusic_repaint_spike.py)
and writes extra.json next to them:
  * beat grid inside 20-25 s: offset (ms) of each render's beats to the nearest
    roundtrip beat — does the repainted passage stay on the song's grid?
  * level step at each boundary: 200 ms RMS just after minus just before, for
    the render and for the roundtrip at the same timestamps.
  * vocal F0 per second in the window (RMVPE on the demucs stem already cut by
    the main script).
  * words sung 14-31 s: faster-whisper (CPU) on the vocal stem, render vs rt.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
OUT = os.path.join(HERE, 'output', 'kidsmusic', '_repaint_spike')
SR = 48000


def _rms_db(x):
    import numpy as np

    return 20.0 * np.log10(max(float(np.sqrt(np.mean(np.square(x)))), 1e-12))


def beats(path):
    import librosa

    y, sr = librosa.load(path, sr=22050, mono=True)
    _tempo, b = librosa.beat.beat_track(y=y, sr=sr, start_bpm=117, units='time')
    return b


if __name__ == '__main__':  # the CLI lives in kidsmusic_repaint_spike_extra_cli
    from zyg_workflows.tools.kidsmusic_repaint_spike_extra_cli import main as _cli_main

    raise SystemExit(_cli_main())
