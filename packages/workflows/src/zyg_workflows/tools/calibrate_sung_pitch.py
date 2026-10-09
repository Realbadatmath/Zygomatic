# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""calibrate_sung_pitch.py — measure sung_pitch.py against ground truth.

Dataset: vocadito (40 solo-vocal excerpts, frame-level f0 annotations, CC BY 4.0,
Zenodo 5578807) in data/assets/calibration/vocadito/ — see PROVENANCE.json there.

Two conditions per excerpt:

  CLEAN  the excerpt as published.
  MIXED  the excerpt summed with the soundfont band
         (output/kidsmusic/0fc29420eb5a/melody.mp3, looped/trimmed to length) at
         0 dB vocal-to-band RMS, then separated with tools/demucs_split.py and
         measured on the returned `vocals` stem.  This is the path a produced
         take actually takes, so its numbers are the calibration that matters.

Scores, per file and aggregated:

  RPA  raw pitch accuracy — share of reference-VOICED frames whose estimate is
       voiced and within +-50 cents.  An unvoiced estimate counts as wrong
       (mir_eval.melody.raw_pitch_accuracy's definition; mir_eval is not
       installed here, so the two lines of arithmetic are inline below).
  RCA  the same, octave-blind: the cent error is folded to its residue modulo
       1200 before the +-50 test.
  median_err_cents  1200*log2(measure_stem f0_median_hz / median of the
       reference's voiced f0) — the error in the ONE number the callers use.

sung_pitch.measure_stem returns order statistics, not frames, so the frame set
for RPA/RCA is taken from the module's own tracker with the module's own
constants (sung_pitch._rmvpe / CONF_MIN / RMVPE_SR, fmin/fmax as passed to
measure_stem).  Nothing in sung_pitch.py is modified or monkeypatched.

The OLD meter (models/voice_analysis/voice_metrics.py, Praat, floor 70 /
ceiling 550 Hz) is run on the first N clean excerpts for a same-file comparison.

Usage:
    python tools/calibrate_sung_pitch.py [--limit N] [--praat-n 10]
                                         [--device cuda|cpu] [--skip-mixed]
                                         [--out data/runtime/sung_pitch_calibration.json]
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from zyg_workflows import paths
from zyg_workflows.bin import exe

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from zyg_workflows import sung_pitch as SP  # noqa: E402

VOCADITO = os.path.join(ROOT, 'data', 'assets', 'calibration', 'vocadito')
AUDIO_DIR = os.path.join(VOCADITO, 'Audio')
F0_DIR = os.path.join(VOCADITO, 'Annotations', 'F0')
BAND = os.path.join(ROOT, 'output', 'kidsmusic', '0fc29420eb5a', 'melody.mp3')
VENV_PY = sys.executable
DEMUCS = os.path.join(ROOT, 'tools', 'demucs_split.py')
PRAAT_PY = str(paths.ZYG_MODELS_DIR / 'voice_analysis' / '.venv' / 'bin' / 'python')
PRAAT_SCRIPT = str(paths.ZYG_MODELS_DIR / 'voice_analysis' / 'voice_metrics.py')
OUT_DEFAULT = os.path.join(ROOT, 'data', 'runtime', 'sung_pitch_calibration.json')

CENT_TOL = 50.0
FMIN, FMAX = 80.0, 1400.0  # measure_stem's defaults


# ---------------------------------------------------------------------------
# reference
# ---------------------------------------------------------------------------


def load_reference(csv_path):
    """(times, hz) from a vocadito F0 csv. 0.0 Hz means 'no f0 present'."""
    t, f = [], []
    with open(csv_path, newline='') as fh:
        for row in csv.reader(fh):
            if len(row) < 2:
                continue
            t.append(float(row[0]))
            f.append(float(row[1]))
    return np.asarray(t, dtype=float), np.asarray(f, dtype=float)


def ref_on_grid(t_ref, f_ref, t_est):
    """Nearest-neighbour resample of the reference onto the estimate's grid.

    The reference hop is 256/44100 = 5.8 ms against RMVPE's 10 ms, so the
    nearest neighbour is never more than 2.9 ms away — well inside a sung note.
    Interpolating would smear the voiced/unvoiced boundary instead.
    """
    if t_ref.size == 0:
        return np.zeros_like(t_est)
    idx = np.clip(np.searchsorted(t_ref, t_est), 0, t_ref.size - 1)
    left = np.clip(idx - 1, 0, t_ref.size - 1)
    take_left = np.abs(t_ref[left] - t_est) <= np.abs(t_ref[idx] - t_est)
    idx = np.where(take_left, left, idx)
    return f_ref[idx]


# ---------------------------------------------------------------------------
# estimate — sung_pitch's own tracker, sung_pitch's own constants
# ---------------------------------------------------------------------------


def estimate_frames(wav_path, device='cpu'):
    """(times, hz, voiced_mask) exactly as measure_stem derives them."""
    import librosa

    y48, _ = librosa.load(str(wav_path), sr=SP.ANALYSIS_SR, mono=True)
    if y48.size == 0:
        return np.zeros(0), np.zeros(0), np.zeros(0, dtype=bool)
    y16 = librosa.resample(y48, orig_sr=SP.ANALYSIS_SR, target_sr=SP.RMVPE_SR)
    t, f0, conf, _act = SP._rmvpe(device).predict(y16, SP.RMVPE_SR)
    t = np.asarray(t, dtype=float)
    f0 = np.asarray(f0, dtype=float)
    conf = np.asarray(conf, dtype=float)
    voiced = (conf >= SP.CONF_MIN) & (f0 >= FMIN) & (f0 <= FMAX)
    return t, f0, voiced


# ---------------------------------------------------------------------------
# scores
# ---------------------------------------------------------------------------


def _cents(a, b):
    with np.errstate(divide='ignore', invalid='ignore'):
        return 1200.0 * np.log2(np.where(b > 0, a, np.nan) / np.where(b > 0, b, np.nan))


def score(t_est, f_est, v_est, t_ref, f_ref):
    """RPA / RCA over the reference's voiced frames."""
    ref = ref_on_grid(t_ref, f_ref, t_est)
    ref_voiced = ref > 0
    n_ref = int(ref_voiced.sum())
    if n_ref == 0:
        return {'rpa': None, 'rca': None, 'n_ref_voiced': 0, 'voicing_recall': None, 'voicing_false_alarm': None}
    both = ref_voiced & v_est
    err = np.zeros(t_est.shape, dtype=float)
    err[both] = _cents(f_est[both], ref[both])
    ok_pitch = both & (np.abs(err) < CENT_TOL)
    # octave-blind: fold the error onto (-600, 600]
    folded = np.abs(err - 1200.0 * np.round(err / 1200.0))
    ok_chroma = both & (folded < CENT_TOL)
    ref_unvoiced = ~ref_voiced
    return {
        'rpa': round(float(ok_pitch.sum()) / n_ref, 4),
        'rca': round(float(ok_chroma.sum()) / n_ref, 4),
        'n_ref_voiced': n_ref,
        'voicing_recall': round(float(both.sum()) / n_ref, 4),
        'voicing_false_alarm': (
            round(float((v_est & ref_unvoiced).sum()) / float(ref_unvoiced.sum()), 4) if ref_unvoiced.any() else 0.0
        ),
    }


def median_err_cents(measured_hz, f_ref):
    voiced = f_ref[f_ref > 0]
    if not measured_hz or voiced.size == 0:
        return None, None
    ref_med = float(np.median(voiced))
    return round(1200.0 * float(np.log2(measured_hz / ref_med)), 2), round(ref_med, 3)


# ---------------------------------------------------------------------------
# the mix
# ---------------------------------------------------------------------------


def _decode(path, sr):
    raw = subprocess.run(
        [exe('ffmpeg'), '-v', 'error', '-i', path, '-f', 'f32le', '-ac', '1', '-ar', str(sr), '-'],
        capture_output=True,
        timeout=600,
        check=True,
    )
    return np.frombuffer(raw.stdout, dtype='<f4').astype(np.float64)


def _rms(a):
    return float(np.sqrt(np.mean(np.square(a)))) if a.size else 0.0


def make_mix(voc_path, band_path, out_path, sr=44100, ratio_db=0.0):
    """Vocal + band at `ratio_db` vocal-to-band RMS. Band looped/trimmed."""
    import soundfile as sf

    v = _decode(voc_path, sr)
    b = _decode(band_path, sr)
    if b.size == 0 or v.size == 0:
        raise RuntimeError('empty decode')
    if b.size < v.size:
        b = np.tile(b, int(np.ceil(v.size / b.size)))
    b = b[: v.size]
    rv, rb = _rms(v), _rms(b)
    if rb <= 0 or rv <= 0:
        raise RuntimeError('silent input')
    b = b * (rv / rb) / (10.0 ** (ratio_db / 20.0))
    mix = v + b
    peak = float(np.max(np.abs(mix)))
    gain = (0.98 / peak) if peak > 0.98 else 1.0  # linear, no clipping
    sf.write(out_path, (mix * gain).astype(np.float32), sr, subtype='PCM_16')
    return {
        'vocal_rms_db': round(20.0 * np.log10(max(rv, 1e-12)), 2),
        'band_rms_db': round(20.0 * np.log10(max(_rms(b), 1e-12)), 2),
        'mix_gain': round(gain, 4),
    }


def demucs_vocals(mix_path, out_dir, device):
    cmd = [VENV_PY, DEMUCS, mix_path, out_dir]
    if device:
        cmd += ['--device', device]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=3600)
    line = (p.stdout or '').strip().splitlines()
    if not line:
        raise RuntimeError(f'demucs_split produced no JSON: {(p.stderr or "")[:300]}')
    j = json.loads(line[-1])
    if not j.get('ok') or not j.get('vocals'):
        raise RuntimeError(f'demucs_split failed: {j.get("error")}')
    return j


# ---------------------------------------------------------------------------
# old meter
# ---------------------------------------------------------------------------


def praat_medians(paths):
    p = subprocess.run([PRAAT_PY, PRAAT_SCRIPT] + list(paths), capture_output=True, text=True, timeout=1800)
    if p.returncode != 0:
        raise RuntimeError(f'voice_metrics.py failed: {(p.stderr or "")[:300]}')
    rows = json.loads((p.stdout or '').strip().splitlines()[-1])
    return {os.path.basename(r.get('path', p2)): r for r, p2 in zip(rows, paths)}


# ---------------------------------------------------------------------------


def _versions():
    import importlib.metadata as md

    v = {'python': sys.version.split()[0]}
    for pkg in ('rmvpe-onnx', 'swift-f0', 'librosa', 'numpy', 'soundfile', 'demucs', 'torch', 'mosqito', 'scipy'):
        try:
            v[pkg] = md.version(pkg)
        except Exception:  # noqa: BLE001
            v[pkg] = None
    return v


def _agg(vals):
    v = [x for x in vals if x is not None]
    return round(float(np.mean(v)), 4) if v else None


def _agg_median(vals):
    v = [x for x in vals if x is not None]
    return round(float(np.median(v)), 2) if v else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--praat-n', type=int, default=10)
    ap.add_argument('--device', default='cuda', help='demucs device')
    ap.add_argument('--skip-mixed', action='store_true')
    ap.add_argument('--out', default=OUT_DEFAULT)
    a = ap.parse_args(argv)

    stems = sorted(
        (f[:-4] for f in os.listdir(AUDIO_DIR) if f.endswith('.wav')), key=lambda s: int(s.rsplit('_', 1)[1])
    )
    if a.limit:
        stems = stems[: a.limit]
    if not os.path.exists(BAND):
        raise SystemExit(f'band missing: {BAND}')

    tmp = tempfile.mkdtemp(prefix='sungcal_')
    rows = []
    try:
        for i, stem in enumerate(stems, 1):
            wav = os.path.join(AUDIO_DIR, f'{stem}.wav')
            t_ref, f_ref = load_reference(os.path.join(F0_DIR, f'{stem}_f0.csv'))
            row = {'file': stem, 'seconds': None}

            m = SP.measure_stem(wav, fmin=FMIN, fmax=FMAX)
            t_e, f_e, v_e = estimate_frames(wav)
            row['seconds'] = m.get('seconds')
            row['clean'] = score(t_e, f_e, v_e, t_ref, f_ref)
            err, ref_med = median_err_cents(m.get('f0_median_hz'), f_ref)
            row['clean'].update(
                {
                    'measure_stem_ok': bool(m.get('ok')),
                    'f0_median_hz': m.get('f0_median_hz'),
                    'ref_median_hz': ref_med,
                    'median_err_cents': err,
                    'swiftf0_median_hz': m.get('swiftf0_median_hz'),
                    'agreement_cents': m.get('agreement_cents'),
                }
            )

            if not a.skip_mixed:
                mix = os.path.join(tmp, f'{stem}_mix.wav')
                sep = os.path.join(tmp, f'{stem}_sep')
                minfo = make_mix(wav, BAND, mix)
                d = demucs_vocals(mix, sep, a.device)
                voc = d['vocals']
                mm = SP.measure_stem(voc, fmin=FMIN, fmax=FMAX)
                t_m, f_m, v_m = estimate_frames(voc)
                row['mixed'] = score(t_m, f_m, v_m, t_ref, f_ref)
                merr, _ = median_err_cents(mm.get('f0_median_hz'), f_ref)
                row['mixed'].update(
                    {
                        'measure_stem_ok': bool(mm.get('ok')),
                        'f0_median_hz': mm.get('f0_median_hz'),
                        'median_err_cents': merr,
                        'demucs_device': d.get('device'),
                        'demucs_ratio_db': d.get('ratio_db'),
                        'mix': minfo,
                    }
                )
                shutil.rmtree(sep, ignore_errors=True)
                os.remove(mix)

            rows.append(row)
            c = row['clean']
            msg = f'[{i}/{len(stems)}] {stem} clean rpa={c["rpa"]} rca={c["rca"]} err={c["median_err_cents"]}c'
            if 'mixed' in row:
                mx = row['mixed']
                msg += f' | mixed rpa={mx["rpa"]} rca={mx["rca"]} err={mx["median_err_cents"]}c'
            print(msg, flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # old Praat meter on the first N clean excerpts
    praat = []
    pn = min(a.praat_n, len(stems))
    if pn:
        paths = [os.path.join(AUDIO_DIR, f'{s}.wav') for s in stems[:pn]]
        pr = praat_medians(paths)
        for s in stems[:pn]:
            r = pr.get(f'{s}.wav', {})
            hz = r.get('f0_median_hz')
            ref = next((x['clean']['ref_median_hz'] for x in rows if x['file'] == s), None)
            e = round(1200.0 * float(np.log2(hz / ref)), 2) if hz and ref else None
            praat.append(
                {
                    'file': s,
                    'praat_f0_median_hz': hz,
                    'ref_median_hz': ref,
                    'median_err_cents': e,
                    'error': r.get('error'),
                }
            )
            for x in rows:
                if x['file'] == s:
                    x['praat'] = praat[-1]

    doc = {
        'date': _dt.datetime.now().isoformat(timespec='seconds'),
        'dataset': 'vocadito (Zenodo 5578807, CC BY 4.0)',
        'dataset_dir': VOCADITO,
        'band': BAND,
        'meter': 'sung_pitch.measure_stem (RMVPE) — unmodified',
        'old_meter': PRAAT_SCRIPT,
        'cent_tolerance': CENT_TOL,
        'fmin_hz': FMIN,
        'fmax_hz': FMAX,
        'conf_min': SP.CONF_MIN,
        'mix_ratio_db': 0.0,
        'n_files': len(rows),
        'rpa_clean': _agg([r['clean']['rpa'] for r in rows]),
        'rca_clean': _agg([r['clean']['rca'] for r in rows]),
        'rpa_mixed': _agg([r['mixed']['rpa'] for r in rows if 'mixed' in r]),
        'rca_mixed': _agg([r['mixed']['rca'] for r in rows if 'mixed' in r]),
        'median_err_cents_clean': _agg_median([r['clean']['median_err_cents'] for r in rows]),
        'median_err_cents_mixed': _agg_median([r['mixed']['median_err_cents'] for r in rows if 'mixed' in r]),
        'abs_median_err_cents_clean': _agg_median(
            [abs(r['clean']['median_err_cents']) for r in rows if r['clean']['median_err_cents'] is not None]
        ),
        'abs_median_err_cents_mixed': _agg_median(
            [
                abs(r['mixed']['median_err_cents'])
                for r in rows
                if 'mixed' in r and r['mixed']['median_err_cents'] is not None
            ]
        ),
        'praat_median_err_cents': _agg_median([p['median_err_cents'] for p in praat]),
        'praat_abs_median_err_cents': _agg_median(
            [abs(p['median_err_cents']) for p in praat if p['median_err_cents'] is not None]
        ),
        'praat_n': len(praat),
        'versions': _versions(),
        'files': rows,
    }
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, 'w') as fh:
        json.dump(doc, fh, indent=2)

    print(
        '\nAGGREGATE '
        + json.dumps(
            {
                k: doc[k]
                for k in (
                    'n_files',
                    'rpa_clean',
                    'rca_clean',
                    'median_err_cents_clean',
                    'abs_median_err_cents_clean',
                    'rpa_mixed',
                    'rca_mixed',
                    'median_err_cents_mixed',
                    'abs_median_err_cents_mixed',
                    'praat_median_err_cents',
                    'praat_abs_median_err_cents',
                    'praat_n',
                )
            }
        )
    )
    print('wrote', a.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
