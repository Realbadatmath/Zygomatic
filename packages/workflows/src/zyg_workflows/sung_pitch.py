# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sung_pitch.py — a pitch/brightness meter that survives sung material.

Why this exists
---------------
models/voice_analysis/voice_metrics.py measures F0 with Praat at pitch_floor 70 /
pitch_ceiling 550 Hz.  The picked Farmyard take
(output/kidsmusic/0fc29420eb5a/voice_sweep/v02_bright_soprano_master.mp3) has a
vocal track with median ~406 Hz, p95 736 Hz and a 1162 Hz peak: the ceiling
censors a large slice of every frame set, so the median moved *non-monotonically*
as pitch-shifted copies pulled different frames in and out of the window.  That is
why -3 st once read higher than -2 st.

The meter here uses:

* **RMVPE** (rmvpe-onnx, MIT weights from RVC's lj1995/VoiceConversionWebUI) —
  the only tracker trained on polyphonic mixes; 96.0 RPA on MIR-1K and 82-98 %
  at 0 dB SNR where CREPE falls to 61 %.
* **SwiftF0** (swift-f0, MIT, 95k params, CPU) as an independent cross-check;
  the two are reported together with their disagreement in cents.
* **MoSQITo** `sharpness_din` (Apache-2.0, DIN 45692) plus spectral centroid and
  the 2-8 kHz energy share for the *brightness* axis, which is not the same axis
  as register: "time above 500 Hz" would call a warm soprano shrill.
* The log-spectrum cross-correlation from tools/farmyard_ref/verify_shift.py as
  the F0-independent relative check on every production take.

Report the confidence-weighted median with p10/p90 — never a mean.

CLI
---
    python sung_pitch.py FILE [FILE...]     # one JSON line per file
    python sung_pitch.py --shift A B        # semitones B sits below/above A
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile

import numpy as np
import logging as _zyg_logging
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


# RMVPE frame hop is 160 samples at 16 kHz == 10 ms.
RMVPE_SR = 16_000
RMVPE_HOP = 160
ANALYSIS_SR = 48_000
CONF_MIN = 0.5

_RMVPE = None


def _rmvpe(device: str = 'cpu'):
    """Load (once) the RMVPE ONNX session.

    CPU by default: this meter is a light job and must not take the GPU slot
    away from a render.  The weights are fetched from Hugging Face on first use
    and cached inside the rmvpe_onnx package data dir.
    """
    global _RMVPE
    if _RMVPE is None:
        from rmvpe_onnx import RMVPE

        _RMVPE = RMVPE(device=device)
    return _RMVPE


# ---------------------------------------------------------------------------
# weighted order statistics
# ---------------------------------------------------------------------------


def _weighted_quantile(values, weights, q):
    """Confidence-weighted quantile. Returns None on an empty set."""
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    if v.size == 0 or w.sum() <= 0:
        return None
    order = np.argsort(v)
    v, w = v[order], w[order]
    cw = np.cumsum(w)
    cw /= cw[-1]
    return float(np.interp(q, cw, v))


def _hz_to_midi(hz):
    if not hz or hz <= 0:
        return None
    return float(69.0 + 12.0 * math.log2(hz / 440.0))


def _cents(a, b):
    if not a or not b or a <= 0 or b <= 0:
        return None
    return float(1200.0 * math.log2(a / b))


# ---------------------------------------------------------------------------
# timbre helpers
# ---------------------------------------------------------------------------


def _hf_ratio_2k8k(y, sr):
    """Energy share of 2-8 kHz inside the 80 Hz - 8 kHz band ("ring")."""
    n = 4096
    if len(y) < n:
        return None
    spec = np.abs(np.fft.rfft(y[: (len(y) // n) * n].reshape(-1, n) * np.hanning(n), axis=1))
    power = (spec**2).mean(axis=0)
    f = np.fft.rfftfreq(n, 1 / sr)
    band = (f >= 80.0) & (f <= 8000.0)
    hi = (f >= 2000.0) & (f <= 8000.0)
    denom = float(power[band].sum())
    if denom <= 0:
        return None
    return float(power[hi].sum() / denom)


def _sharpness_acum(y, sr):
    """DIN 45692 sharpness, time-averaged, in acum. None if MoSQITo fails.

    The signal is not calibrated to Pa, so the absolute number is only
    comparable between files measured the same way — which is all rank_score
    needs.
    """
    try:
        from mosqito.sq_metrics import sharpness_din_perseg

        s, _t = sharpness_din_perseg(np.asarray(y, dtype=float), sr, weighting='din')
        s = np.asarray(s, dtype=float)
        s = s[np.isfinite(s)]
        if s.size == 0:
            return None
        return float(s.mean())
    except Exception as _exc:
        _zyg_log.debug('per-segment sharpness unavailable, trying the single-value metric: %s', _exc)
    try:
        from mosqito.sq_metrics import sharpness_din_st

        return float(sharpness_din_st(np.asarray(y, dtype=float), sr, weighting='din'))
    except Exception:
        return None


def _swiftf0_median(y16, fmin, fmax):
    """Independent CPU cross-check. Returns (median_hz, voiced_frac) or (None, None)."""
    try:
        from swift_f0 import SwiftF0

        lo = max(float(fmin), 46.9)
        hi = min(float(fmax), 2093.7)
        det = SwiftF0(confidence_threshold=CONF_MIN, fmin=lo, fmax=hi)
        res = det.detect_from_array(np.asarray(y16, dtype=np.float32), RMVPE_SR)
        m = np.asarray(res.voicing, dtype=bool)
        if not m.any():
            return None, 0.0
        med = _weighted_quantile(np.asarray(res.pitch_hz)[m], np.asarray(res.confidence)[m], 0.5)
        return med, float(m.mean())
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# the meter
# ---------------------------------------------------------------------------


def measure_stem(wav_path, *, fmin=80, fmax=1400, device='cpu'):
    """Measure register and brightness of a (preferably vocal-stem) audio file.

    Returns a dict; on failure `ok` is False and `error` carries the reason.
    All frequencies are Hz.
    """
    out = {
        'path': os.path.abspath(str(wav_path)),
        'tracker': 'rmvpe',
        'f0_median_hz': None,
        'f0_p10_hz': None,
        'f0_p90_hz': None,
        'f0_median_midi': None,
        'voiced_frac': None,
        'pct_time_above_500hz': None,
        'swiftf0_median_hz': None,
        'agreement_cents': None,
        'centroid_hz': None,
        'hf_ratio_2k8k': None,
        'sharpness_acum': None,
        'seconds': None,
        'ok': False,
        'error': '',
    }
    try:
        import librosa

        y48, _ = librosa.load(str(wav_path), sr=ANALYSIS_SR, mono=True)
        if y48.size == 0:
            out['error'] = 'empty audio'
            return out
        out['seconds'] = round(len(y48) / ANALYSIS_SR, 3)
        y16 = librosa.resample(y48, orig_sr=ANALYSIS_SR, target_sr=RMVPE_SR)

        _t, f0, conf, _act = _rmvpe(device).predict(y16, RMVPE_SR)
        f0 = np.asarray(f0, dtype=float)
        conf = np.asarray(conf, dtype=float)
        voiced = (conf >= CONF_MIN) & (f0 >= float(fmin)) & (f0 <= float(fmax))
        out['voiced_frac'] = float(voiced.mean()) if f0.size else 0.0
        if not voiced.any():
            out['error'] = 'no voiced frames'
            return out

        fv, cv = f0[voiced], conf[voiced]
        out['f0_median_hz'] = round(_weighted_quantile(fv, cv, 0.50), 3)
        out['f0_p10_hz'] = round(_weighted_quantile(fv, cv, 0.10), 3)
        out['f0_p90_hz'] = round(_weighted_quantile(fv, cv, 0.90), 3)
        out['f0_median_midi'] = round(_hz_to_midi(out['f0_median_hz']), 3)
        out['pct_time_above_500hz'] = round(100.0 * float((fv > 500.0).mean()), 3)

        sm, _sv = _swiftf0_median(y16, fmin, fmax)
        if sm:
            out['swiftf0_median_hz'] = round(float(sm), 3)
            ac = _cents(out['f0_median_hz'], sm)
            out['agreement_cents'] = round(ac, 2) if ac is not None else None

        # centroid on the voiced frames only, 10 ms hop so frames align 1:1
        # with RMVPE's.
        cen = librosa.feature.spectral_centroid(
            y=y48, sr=ANALYSIS_SR, n_fft=2048, hop_length=ANALYSIS_SR * RMVPE_HOP // RMVPE_SR
        )[0]
        n = min(len(cen), len(voiced))
        cm = cen[:n][voiced[:n]]
        if cm.size:
            out['centroid_hz'] = round(float(np.median(cm)), 2)

        out['hf_ratio_2k8k'] = _hf_ratio_2k8k(y48, ANALYSIS_SR)
        if out['hf_ratio_2k8k'] is not None:
            out['hf_ratio_2k8k'] = round(out['hf_ratio_2k8k'], 6)
        sh = _sharpness_acum(y48, ANALYSIS_SR)
        out['sharpness_acum'] = round(sh, 4) if sh is not None else None

        out['ok'] = True
        return out
    except Exception as exc:  # pragma: no cover
        out['error'] = f'{type(exc).__name__}: {exc}'
        return out


# ---------------------------------------------------------------------------
# log-spectrum cross-correlation — copied from tools/farmyard_ref/verify_shift.py
#
# A pitch shift of n semitones translates the WHOLE spectrum by n steps on a
# log-frequency axis, so resampling each average spectrum onto a 1/10-semitone
# log grid and cross-correlating base against shifted recovers n directly --
# every partial of every instrument votes, not just the singer's f0.  This is
# independent of F0 tracking.
# ---------------------------------------------------------------------------


def spec(path):
    import soundfile as sf

    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as t:
        w = t.name
    subprocess.run(
        [exe('ffmpeg'), '-y', '-v', 'error', '-i', str(path), '-ar', '48000', '-ac', '1', '-c:a', 'pcm_s16le', w],
        check=True,
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


def _as_spec(x):
    return x if isinstance(x, np.ndarray) else spec(x)


def shift_semitones(a, b, per=10, max_st=14):
    """Cross-correlate: how many log-bins must b move to line up with a.

    Accepts paths or precomputed spec() vectors.  Returns (semitones, corr).
    """
    a = _as_spec(a)
    b = _as_spec(b)
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


# ---------------------------------------------------------------------------
# ranking
# ---------------------------------------------------------------------------


def _z(vals):
    v = np.asarray([np.nan if x is None else float(x) for x in vals], dtype=float)
    ok = np.isfinite(v)
    if ok.sum() < 2:
        return np.zeros(len(v))
    mu = v[ok].mean()
    sd = v[ok].std()
    if sd <= 0:
        return np.zeros(len(v))
    z = np.zeros(len(v))
    z[ok] = (v[ok] - mu) / sd
    return z


def rank_score(rows):
    """Add a z-scored 'rank' to each row. Lower = less shrill.

    rank = z(f0_median_hz) + z(sharpness_acum, centroid_hz fallback)
           + z(hf_ratio_2k8k)

    Register and brightness are separate axes, so both are in the sum: a warm
    soprano scores low on the brightness terms even though her median is high.
    Modifies and returns `rows`.
    """
    rows = list(rows)
    if not rows:
        return rows
    sharp = [r.get('sharpness_acum') for r in rows]
    if sum(1 for s in sharp if s is not None) < 2:
        bright = [r.get('centroid_hz') for r in rows]
        bright_key = 'centroid_hz'
    else:
        bright = sharp
        bright_key = 'sharpness_acum'
    z = _z([r.get('f0_median_hz') for r in rows]) + _z(bright) + _z([r.get('hf_ratio_2k8k') for r in rows])
    for r, s in zip(rows, z):
        r['rank'] = round(float(s), 4)
        r['rank_brightness_term'] = bright_key
    return rows


if __name__ == '__main__':  # the CLI lives in sung_pitch_cli
    from zyg_workflows.sung_pitch_cli import main as _cli_main

    raise SystemExit(_cli_main(sys.argv[1:]))
