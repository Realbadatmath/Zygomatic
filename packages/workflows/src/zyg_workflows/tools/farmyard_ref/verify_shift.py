# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""How far did each delivered file actually move in pitch?

Independent of F0 tracking, which the calibration just showed is unreliable on
this material. A pitch shift of n semitones translates the WHOLE spectrum by n
steps on a log-frequency axis, so resampling each average spectrum onto a
1/10-semitone log grid and cross-correlating base against shifted recovers n
directly -- every partial of every instrument votes, not just the singer's f0.
"""

import numpy as np
import soundfile as sf
import os
import json
import subprocess
import tempfile
from zyg_workflows import paths
from zyg_workflows.bin import exe

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

JOB = str(paths.ZYG_OUTPUT_ROOT / 'kidsmusic' / '0fc29420eb5a')
BASES = {
    'warm': f'{JOB}/voice_sweep/v01_warm_control_master.mp3',
    'cartoon': f'{JOB}/voice_sweep/v05_playful_cartoon_master.mp3',
}


def spec(path):
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as t:
        w = t.name
    subprocess.run(
        [exe('ffmpeg'), '-y', '-v', 'error', '-i', path, '-ar', '48000', '-ac', '1', '-c:a', 'pcm_s16le', w], check=True
    )
    x, sr = sf.read(w)
    os.unlink(w)
    n = 8192
    hop = 4096
    acc = np.zeros(n // 2 + 1)
    win = np.hanning(n)
    for i in range(0, len(x) - n, hop):
        acc += np.abs(np.fft.rfft(x[i : i + n] * win))
    f = np.fft.rfftfreq(n, 1 / sr)
    # log-frequency grid, 10 bins per semitone, 80 Hz .. 8 kHz
    lo, hi, per = 80.0, 8000.0, 10
    nb = int(round(np.log2(hi / lo) * 12 * per))
    grid = lo * 2 ** (np.arange(nb) / (12 * per))
    v = np.interp(grid, f, acc)
    v = np.log(v + 1e-9)
    return v - v.mean()


def shift_semitones(a, b, per=10, max_st=14):
    """Cross-correlate: how many log-bins must b move to line up with a."""
    best, bs = -1e9, 0
    for d in range(-max_st * per, max_st * per + 1):
        if d >= 0:
            x, y = a[d:], b[: len(b) - d] if d else b
        else:
            x, y = a[: len(a) + d], b[-d:]
        if len(x) < 100:
            continue
        c = float(np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y) + 1e-9))
        if c > best:
            best, bs = c, d
    return -bs / per, best


rows = []
_zyg_log.info(f'{"file":16s} {"asked":>6s} {"measured":>9s} {"corr":>6s}')
for base, src in BASES.items():
    a = spec(src)
    for n in [2, 3, 4, 5, 6]:
        p = f'{JOB}/pitch_fix/{base}_down{n}.mp3'
        if not os.path.isfile(p):
            _zyg_log.info(f'{base}_down{n}: missing')
            continue
        got, c = shift_semitones(a, spec(p))
        _zyg_log.info(f'{base + "_down" + str(n):16s} {-n:6d} {got:9.2f} {c:6.3f}')
        rows.append(
            {
                'file': f'{base}_down{n}.mp3',
                'asked_semitones': -n,
                'measured_semitones': round(got, 2),
                'correlation': round(c, 3),
            }
        )
json.dump(rows, open(f'{JOB}/pitch_fix/shift_verification.json', 'w'), indent=1)
