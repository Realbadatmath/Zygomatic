# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kidsmusic_chroma_test.py — does an audio leg follow the COMPOSED melody?

The test that established the two legs are not the same song, kept as a tool so
the claim can be re-checked rather than remembered.

METHOD. Build a chroma template from the plan's note list (pitch class x time,
at the plan's own tempo), build a chroma feature from the rendered audio, and
correlate them over a search of time lags. Compare that similarity against a
NULL built from the same take against OTHER songs' plans. Report z.

WHY A NULL AT ALL. Two pieces of tonal music in the same key correlate well
above zero by construction, so a bare similarity number cannot distinguish
"follows the melody" from "is also in C major". The null is what makes the
number mean something — the same lesson the pufferball fit and the GNM head
both had to learn the hard way.

CALIBRATION (2026-08-29, six shipped songs):
    score render : 0.8265 vs 0.2524 null -> z = +2.84, lag 0.00 s in 6 of 6
    ACE take     : 0.2791 vs 0.2524 null -> z = +0.65, lag pinned at the search
                   boundary in 5 of 6
So the method HAS power and the ACE result is a real negative, not a weak test.

ACCEPTANCE for the audio2audio spike: z > 2 against the cross-song null.

Usage:
    python kidsmusic_chroma_test.py AUDIO PLAN.json [--null OTHER_PLAN.json ...]
"""

import json
import logging as _zyg_logging
import os
import subprocess
import sys

import numpy as np

_zyg_log = _zyg_logging.getLogger(__name__)

SR = 22050
HOP = 512


def plan_chroma(plan, n_frames, sr=SR, hop=HOP):
    """Pitch-class x time template straight from the composed note list."""
    bpm = float(plan['bpm'])
    spb = 60.0 / bpm
    C = np.zeros((12, n_frames), dtype='float64')
    for n in plan['melody']:
        t0 = float(n['t']) * spb
        t1 = t0 + float(n['d']) * spb
        f0 = int(round(t0 * sr / hop))
        f1 = max(f0 + 1, int(round(t1 * sr / hop)))
        if f0 >= n_frames:
            continue
        C[int(n['p']) % 12, f0 : min(f1, n_frames)] += 1.0
    return C


def audio_chroma(path, sr=SR, hop=HOP):
    """Chroma from the audio, via a plain constant-Q-ish DFT folding.

    Deliberately dependency-light: numpy + ffmpeg, no librosa. The measurement
    is a correlation over pitch classes, which does not need a tuned CQT.
    """
    raw = subprocess.run(
        ['ffmpeg', '-v', 'error', '-i', path, '-f', 'f32le', '-ac', '1', '-ar', str(sr), '-'],
        capture_output=True,
        timeout=600,
    )
    if raw.returncode != 0 or not raw.stdout:
        raise RuntimeError('decode failed')
    x = np.frombuffer(raw.stdout, dtype='<f4').astype('float64')
    n_fft = 4096
    n_frames = max(1, 1 + (len(x) - n_fft) // hop)
    win = np.hanning(n_fft)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    # Map every bin to a pitch class; ignore sub-bass and everything above the
    # range a children's melody lives in.
    with np.errstate(divide='ignore'):
        midi = 69 + 12 * np.log2(np.maximum(freqs, 1e-9) / 440.0)
    keep = (freqs > 55.0) & (freqs < 2200.0)
    pc = np.zeros(len(freqs), dtype=int)
    pc[keep] = np.round(midi[keep]).astype(int) % 12
    C = np.zeros((12, n_frames), dtype='float64')
    for i in range(n_frames):
        seg = x[i * hop : i * hop + n_fft]
        if len(seg) < n_fft:
            break
        mag = np.abs(np.fft.rfft(seg * win))
        for k in range(12):
            C[k, i] = mag[keep & (pc == k)].sum()
    return C


def _norm(C):
    C = C - C.mean(axis=1, keepdims=True)
    n = np.linalg.norm(C, axis=1, keepdims=True)
    return C / np.maximum(n, 1e-12)


def similarity(audio_C, plan_C, max_lag_frames=200):
    """Best cosine similarity over a lag search. Returns (sim, lag_frames)."""
    A, P = _norm(audio_C), _norm(plan_C)
    best, best_lag = -1.0, 0
    for lag in range(-max_lag_frames, max_lag_frames + 1):
        if lag >= 0:
            a, p = A[:, lag:], P[:, : P.shape[1] - lag]
        else:
            a, p = A[:, : A.shape[1] + lag], P[:, -lag:]
        w = min(a.shape[1], p.shape[1])
        if w < 20:
            continue
        s = float((a[:, :w] * p[:, :w]).sum() / 12.0)
        if s > best:
            best, best_lag = s, lag
    return best, best_lag


def main(argv):
    audio, plan_path = argv[0], argv[1]
    nulls = []
    if '--null' in argv:
        nulls = argv[argv.index('--null') + 1 :]
    plan = json.load(open(plan_path))
    A = audio_chroma(audio)
    n = A.shape[1]
    sim, lag = similarity(A, plan_chroma(plan, n))
    out = {
        'audio': os.path.basename(audio),
        'similarity': round(sim, 4),
        'lag_s': round(lag * HOP / SR, 2),
        'frames': n,
    }
    null_sims = []
    for np_ in nulls:
        try:
            null_sims.append(similarity(A, plan_chroma(json.load(open(np_)), n))[0])
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
    if len(null_sims) >= 2:
        mu, sd = float(np.mean(null_sims)), float(np.std(null_sims) or 1e-9)
        out.update(
            {
                'null_mean': round(mu, 4),
                'null_sd': round(sd, 4),
                'null_n': len(null_sims),
                'z': round((sim - mu) / sd, 2),
            }
        )
        out['follows_melody'] = bool(out['z'] > 2.0)
    else:
        out['note'] = 'need >= 2 --null plans for a z score'
    print(json.dumps(out, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
