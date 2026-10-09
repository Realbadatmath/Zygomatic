# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Calibration for sung_pitch.py.

Two levels of truth:

1. **Synthetic** (no licence risk, no external asset): a harmonic "voice" whose
   F0 is known exactly, stepping D4-F#4-A4-D5-F4 with 5.5 Hz / +-40 cents
   vibrato.  The interesting part is D5 587 Hz: the old Praat meter's 550 Hz
   ceiling censored it, so its median and its p90 both moved for the wrong
   reason.  Here the median must land on F#4 and p90 on D5.

2. **Real material**: the picked Farmyard take, pitched down 2/3/4 st with
   rubberband, separated with demucs, measured on the vocal stem.  The medians
   must fall *monotonically* — the exact failure that started this work — and
   the F0-independent log-spectrum cross-correlation must read the shift back.

Run:  scripts/run_tests.sh tests/test_sung_pitch.py
"""

import json
import math
import os
import shutil
import subprocess
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows import sung_pitch as SP  # noqa: E402

CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# demucs_split.py is run out-of-process, but in the same interpreter as this suite: the
# REAL_OK gate below imports demucs here, so "demucs is installed" means installed for
# sys.executable.
VENV_PY = sys.executable
TAKE = os.path.join(CREWS, 'output/kidsmusic/0fc29420eb5a/voice_sweep/v02_bright_soprano_master.mp3')
# Cached so the second pytest run (the board re-runs verify_cmd on `st done`)
# does not redo four demucs passes.
CACHE = os.path.join(CREWS, 'data/runtime/sung_pitch_cal')

SR = 48_000
# D4, F#4, A4, D5, F4 — median of the five is F#4, p90 sits inside D5.
NOTES = [293.66, 369.99, 440.00, 587.33, 349.23]
TRUE_MEDIAN = 369.99
TRUE_P90 = 587.33


def _cents(a, b):
    return 1200.0 * math.log2(a / b)


def synth_voice(path, notes=NOTES, seconds=8.0, sr=SR, vibrato_hz=5.5, vibrato_cents=40.0, harmonics=12):
    """12 harmonics at 1/n amplitude on a vibrato'd, phase-continuous F0."""
    import soundfile as sf

    n = int(sr * seconds)
    t = np.arange(n) / sr
    seg = seconds / len(notes)
    f = np.full(n, notes[-1], dtype=float)
    for i, hz in enumerate(notes):
        f[(t >= i * seg) & (t < (i + 1) * seg)] = hz
    f = f * 2 ** (vibrato_cents * np.sin(2 * np.pi * vibrato_hz * t) / 1200.0)
    phase = np.cumsum(2 * np.pi * f / sr)
    y = np.zeros(n)
    for h in range(1, harmonics + 1):
        y += np.sin(h * phase) / h
    y /= np.abs(y).max() * 1.05
    k = int(0.005 * sr)  # de-click the ends only
    y[:k] *= np.linspace(0, 1, k)
    y[-k:] *= np.linspace(1, 0, k)
    sf.write(path, y, sr)
    return path


# ---------------------------------------------------------------------------
# 1 · synthetic truth
# ---------------------------------------------------------------------------


def test_measure_stem_synthetic_voice(tmp_path):
    pytest.importorskip('librosa', reason='measure_stem loads and resamples the stem with librosa')
    wav = synth_voice(str(tmp_path / 'voice.wav'))
    r = SP.measure_stem(wav)

    assert r['ok'], r['error']
    assert r['tracker'] == 'rmvpe'
    assert r['voiced_frac'] > 0.9, r['voiced_frac']

    med_err = _cents(r['f0_median_hz'], TRUE_MEDIAN)
    assert abs(med_err) <= 30.0, f'median {r["f0_median_hz"]} Hz = {med_err:.1f} cents off F#4'

    # The case the Praat meter could not read: p90 is above its 550 Hz ceiling.
    p90_err = _cents(r['f0_p90_hz'], TRUE_P90)
    assert abs(p90_err) <= 40.0, f'p90 {r["f0_p90_hz"]} Hz = {p90_err:.1f} cents off D5'

    assert r['f0_p10_hz'] < r['f0_median_hz'] < r['f0_p90_hz']
    assert abs(r['f0_median_midi'] - 66.0) < 0.5  # F#4 = MIDI 66
    # one of five equal segments is above 500 Hz
    assert 12.0 <= r['pct_time_above_500hz'] <= 28.0, r['pct_time_above_500hz']
    # the independent tracker must agree inside a quarter tone
    assert r['swiftf0_median_hz'] is not None
    assert abs(r['agreement_cents']) <= 50.0, r['agreement_cents']
    assert r['centroid_hz'] > 0 and 0.0 < r['hf_ratio_2k8k'] < 1.0


def test_rank_score_orders_least_shrill_first():
    rows = [
        {'name': 'warm', 'f0_median_hz': 300.0, 'sharpness_acum': 1.1, 'hf_ratio_2k8k': 0.04},
        {'name': 'mid', 'f0_median_hz': 380.0, 'sharpness_acum': 1.4, 'hf_ratio_2k8k': 0.07},
        {'name': 'shrill', 'f0_median_hz': 460.0, 'sharpness_acum': 1.9, 'hf_ratio_2k8k': 0.12},
    ]
    SP.rank_score(rows)
    assert [r['name'] for r in sorted(rows, key=lambda r: r['rank'])] == ['warm', 'mid', 'shrill']
    assert rows[0]['rank_brightness_term'] == 'sharpness_acum'

    # no sharpness anywhere -> centroid fallback, same ordering
    fallback = [dict(r, sharpness_acum=None, centroid_hz=c) for r, c in zip(rows, (1500.0, 2000.0, 2900.0))]
    for r in fallback:
        r.pop('rank', None)
    SP.rank_score(fallback)
    assert fallback[0]['rank_brightness_term'] == 'centroid_hz'
    assert fallback[0]['rank'] < fallback[1]['rank'] < fallback[2]['rank']


# ---------------------------------------------------------------------------
# 2 · real material: rubberband -> demucs -> RMVPE
# ---------------------------------------------------------------------------


def _demucs_available():
    try:
        import demucs  # noqa: F401

        return True
    except Exception:
        return False


REAL_OK = shutil.which('ffmpeg') is not None and os.path.isfile(TAKE) and _demucs_available()


def _shifted_mix(n):
    """Whole-mix copy pitched down n semitones (0 = the original take)."""
    if n == 0:
        return TAKE
    out = os.path.join(CACHE, f'mix_down{n}.wav')
    if not os.path.isfile(out):
        os.makedirs(CACHE, exist_ok=True)
        subprocess.run(
            [
                'ffmpeg',
                '-y',
                '-v',
                'error',
                '-i',
                TAKE,
                '-af',
                f'rubberband=pitch={2 ** (-n / 12)}:formant=preserved',
                out,
            ],
            check=True,
        )
    return out


def _vocal_stem(n):
    out_dir = os.path.join(CACHE, f'stem_down{n}')
    vocals = os.path.join(out_dir, 'vocals.wav')
    if not os.path.isfile(vocals):
        proc = subprocess.run(
            [VENV_PY, os.path.join(CREWS, 'tools/demucs_split.py'), _shifted_mix(n), out_dir],
            cwd=CREWS,
            capture_output=True,
            text=True,
            timeout=600,
        )
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith('{')]
        assert line, f'demucs_split gave no JSON: {proc.stdout[-500:]} {proc.stderr[-500:]}'
        info = json.loads(line[-1])
        assert info['ok'], info
        vocals = info['vocals']
    return vocals


@pytest.mark.skipif(not REAL_OK, reason='needs ffmpeg, demucs and the Farmyard take')
def test_shifted_take_medians_are_monotonic():
    """The regression that started this: Praat read -3 st *above* -2 st.

    Measured 2026-09-06 on v02_bright_soprano_master.mp3:
        0 st 375.1 Hz | -2 st 337.8 (+18.7 c) | -3 st 323.7 (+44.8 c)
        | -4 st 300.4 (+15.2 c)
    The tolerance below is 60 cents because the residual is not tracker error:
    rubberband's R2 engine and demucs together change which frames survive in
    the stem (voiced_frac 0.42 -> 0.37 at -3 st).  The shift itself is read back
    exactly by the log-spectrum instrument in the next test.
    """
    med = {}
    for n in (0, 2, 3, 4):
        r = SP.measure_stem(_vocal_stem(n))
        assert r['ok'], (n, r['error'])
        med[n] = r['f0_median_hz']

    order = [med[n] for n in (0, 2, 3, 4)]
    assert order == sorted(order, reverse=True), f'not monotonic: {med}'

    for n in (2, 3, 4):
        expect = med[0] * 2 ** (-n / 12)
        err = _cents(med[n], expect)
        assert abs(err) <= 60.0, f'-{n} st: {med[n]:.1f} Hz vs {expect:.1f} Hz ({err:+.1f} cents)'


@pytest.mark.skipif(not REAL_OK, reason='needs ffmpeg and the Farmyard take')
def test_shift_semitones_reads_the_shift_back():
    base = SP.spec(TAKE)
    for n in (2, 3, 4):
        got, corr = SP.shift_semitones(base, _shifted_mix(n))
        assert abs(got + n) <= 0.15, f'-{n} st read as {got}'
        assert corr > 0.9, (n, corr)
