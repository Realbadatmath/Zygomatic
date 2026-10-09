# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_conversion.py — put a fixed singer's voice on a sung vocal stem (RVC).

The kids-music voice leg ships ACE-Step's take, and ACE-Step draws a new voice
from the text on every new song (a seed is not a timbre lock —
kids_music_theory.SINGERS). This converts the take's separated vocal to one
trained voice with Applio RVC v2, keeps the melody and the words, and hands
back a stem aligned and level-matched to the original so the song's mix
balance is unchanged.

Model: `warm_control_v2` (models/vc_applio/logs), trained 2026-09-15 on Red
Train renditions selected by similarity to the one real Warm Control take.
Bench (tools/vc_bench.py, criteria fixed before the run, 8 held-out songs):
melody 5.4 cents median, octave errors <= 0.05 %, lyrics -1 line worst, the
voice moved toward Warm Control on 7/8 → PASS. Licences at file level:
models/vc_applio/PROVENANCE.json (Applio MIT; pretrained HiFi-GAN MIT, trained
on VCTK CC BY 4.0 — attribution; ContentVec MIT; RMVPE MIT).

The conversion runs in Applio's own venv (Python 3.12) as a subprocess via
tools/vc_applio_worker.py; nothing here imports torch.

`ship_check` is the per-song half of the bench's criteria, applied to every
conversion before it ships: melody drift <= 25 cents median and <= 2 % octave
errors, and no more than one lyric line lost against the unconverted take's
own review. Voice identity is NOT a per-song gate — TitaNet could not tell
voices apart on sung stems (output/kidsmusic/_voice_build/calibration.json).
A check that could not measure refuses to ship: the unconverted take is always
the safe fallback, and it is kept beside the song either way.
"""

import json
import os
import subprocess
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
APPLIO = os.environ.get('ZYG_VC_APPLIO', os.path.join(os.path.dirname(os.path.dirname(HERE)), 'models', 'vc_applio'))
WORKER = os.path.join(HERE, 'tools', 'vc_applio_worker.py')
PROVENANCE = 'models/vc_applio/PROVENANCE.json'
ENGINE = 'Applio RVC v2 (HiFi-GAN, 40 kHz)'

LICENCE = {
    'engine': 'Applio (IAHispano/Applio), MIT',
    'model': 'warm_control_v2 — trained on this box from our own ACE-Step renders (Red Train 1ba342d5cd75)',
    'pretrained': 'RVC v2 HiFi-GAN f0G/f0D (lj1995/VoiceConversionWebUI), MIT',
    'pretrained_training_data': 'VCTK corpus, CC BY 4.0 — attribution required',
    'embedder': 'ContentVec, MIT',
    'pitch': 'RMVPE, MIT',
    'attribution': (
        'Voice conversion uses RVC v2 pretrained weights trained on the VCTK corpus '
        '(CSTR, University of Edinburgh), licensed CC BY 4.0.'
    ),
    'evidence': PROVENANCE,
}

# The bench's pre-registered per-song criteria (tools/vc_bench.py).
MAX_MEDIAN_CENTS = 25.0
MAX_OCTAVE_SHARE = 0.02
MAX_LINES_LOST = 1
# INTELLIGIBILITY IS A SHIP CONDITION (2026-10-03). Measured over 16 songs that kept
# both stems, unprompted Whisper on the converted vs the unconverted mix: mean line
# coverage 70.7 % -> 62.0 %, i.e. RVC costs 8.6 points, and it was WORSE on 13 of the
# 16 (best case +3.0, worst -26.3). 25 of 216 lines crossed from clear to unclear
# purely by converting. None of that was visible to the old check, which compared
# `lyrics.sung` — the PROMPTED count, which a prompted recogniser keeps at ceiling
# off audio nobody can make out. Same allowance as MAX_LINES_LOST: the conversion is
# free to be no worse, not free to cost the song its words.
MAX_LINES_UNCLEARED = 1


def _log_noop(_m):
    return None


def enabled():
    return os.environ.get('ZYG_KIDSMUSIC_VC', '1').strip().lower() not in ('0', 'false', 'no', 'off')


def available(model, weights=''):
    """(ok, reason). Checks the venv and the weights exist — not that CUDA works."""
    py = os.path.join(APPLIO, '.venv', 'bin', 'python')
    if not os.path.isfile(py):
        return False, f'Applio venv missing ({py})'
    if not os.path.isfile(WORKER):
        return False, 'tools/vc_applio_worker.py missing'
    mdir = os.path.join(APPLIO, 'logs', model)
    if weights:
        if not os.path.isfile(os.path.join(mdir, weights)):
            return False, f'weights {weights} not found in logs/{model}'
    elif not any(
        f.endswith('.pth') and not f.startswith(('G_', 'D_')) for f in (os.listdir(mdir) if os.path.isdir(mdir) else [])
    ):
        return False, f'no trained weights for {model}'
    return True, ''


def match_gain_db(src, conv, sr, frame_s=0.05):
    """dB to add to `conv` so its RMS over the source's sung frames equals the
    source's. RVC's output level drifted -6..+5 dB from its source on bench v1.
    (Same function as tools/vc_bench.py, which stays frozen with its results.)"""
    hop = int(frame_s * sr)
    n = min(len(src), len(conv)) // hop
    if n < 10:
        return 0.0
    s = np.sqrt(np.mean(src[: n * hop].reshape(n, hop) ** 2, axis=1))
    c = np.sqrt(np.mean(conv[: n * hop].reshape(n, hop) ** 2, axis=1))
    sung = s > (s.max() * 10 ** (-30 / 20))
    if sung.sum() < 10:
        return 0.0
    return float(20 * np.log10(max(np.sqrt(np.mean(s[sung] ** 2)), 1e-9) / max(np.sqrt(np.mean(c[sung] ** 2)), 1e-9)))


def lag_samples(a, b, sr):
    """b[x + lag] ~ a[x], from 10 ms RMS envelopes. Some converted stems came
    back 441 samples (10 ms) early on the bench."""
    hop = sr // 100

    def env(y):
        n = len(y) // hop
        return np.sqrt(np.mean(y[: n * hop].reshape(n, hop) ** 2, axis=1))

    ea, eb = env(a), env(b)
    n = min(len(ea), len(eb))
    best, lag = -1.0, 0
    for k in range(-50, 51):
        x = ea[max(0, -k) : n - max(0, k)]
        y = eb[max(0, k) : n + min(0, k)][: len(x)]
        if len(x) < 100:
            continue
        c = float(np.corrcoef(x, y)[0, 1])
        if c > best:
            best, lag = c, k
    return lag * hop, round(best, 4)


def convert_stem(vocals_wav, work_dir, *, model, weights='', index_rate=0.5, protect=0.33, timeout_s=900, log_fn=None):
    """Convert one vocal stem. Returns a record with `path`: a stereo PCM_16 WAV
    at the SOURCE sample rate and length, aligned to the source and matched to
    its sung-frame RMS. `ok` False with `error` on any failure."""
    import soundfile as sf

    log_fn = log_fn or _log_noop
    rec = {
        'ok': False,
        'error': '',
        'engine': ENGINE,
        'model': model,
        'weights': weights,
        'index_rate': index_rate,
        'protect': protect,
        'f0_method': 'rmvpe',
    }
    t0 = time.time()
    try:
        ok, why = available(model, weights)
        if not ok:
            rec['error'] = why
            return rec
        src_dir, out_dir = os.path.join(work_dir, 'in'), os.path.join(work_dir, 'out')
        os.makedirs(src_dir, exist_ok=True)
        y, sr = sf.read(vocals_wav, dtype='float32', always_2d=True)
        sf.write(os.path.join(src_dir, 'vocals.wav'), y, sr, subtype='PCM_16')
        env = dict(os.environ, VC_PTH=weights) if weights else dict(os.environ)
        r = subprocess.run(
            [
                os.path.join(APPLIO, '.venv/bin/python'),
                WORKER,
                'convert',
                model,
                src_dir,
                out_dir,
                str(index_rate),
                str(protect),
            ],
            cwd=APPLIO,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        res = next(
            (json.loads(x) for x in reversed((r.stdout or '').strip().splitlines()) if x.startswith('{')),
            {'ok': False, 'error': (r.stderr or '')[-300:]},
        )
        out_wav = os.path.join(out_dir, 'vocals.wav')
        if not res.get('ok') or not os.path.isfile(out_wav):
            rec['error'] = f'conversion failed: {res.get("error") or "no output"}'[:300]
            return rec
        rec['weights'] = os.path.basename(res.get('pth') or weights)
        rec['convert_s'] = round(time.time() - t0, 1)

        import librosa

        yc, sr_c = sf.read(out_wav, dtype='float32', always_2d=True)
        yc = yc.mean(axis=1)
        if sr_c != sr:
            yc = librosa.resample(yc, orig_sr=sr_c, target_sr=sr)
        mono = y.mean(axis=1)
        lag, corr = lag_samples(mono, yc, sr)
        if lag > 0:
            yc = yc[lag:]
        elif lag < 0:
            yc = np.concatenate([np.zeros(-lag, np.float32), yc])
        yc = np.pad(yc, (0, max(0, len(mono) - len(yc))))[: len(mono)]
        gain_db = match_gain_db(mono, yc, sr)
        yc = yc * (10.0 ** (gain_db / 20.0))
        peak = float(np.abs(yc).max()) or 1.0
        if peak > 0.99:
            yc = yc * (0.99 / peak)
        dst = os.path.join(work_dir, 'vocals_converted.wav')
        sf.write(dst, np.stack([yc, yc], 1).astype(np.float32), sr, subtype='PCM_16')
        rec.update(
            {'ok': True, 'path': dst, 'lag_samples': int(lag), 'envelope_corr': corr, 'gain_db': round(gain_db, 2)}
        )
        log_fn(
            f'voice: converted to {model} in {rec["convert_s"]:.1f}s (lag {lag} samples, '
            f'envelope corr {corr}, level {gain_db:+.1f} dB to match the take)'
        )
    except subprocess.TimeoutExpired:
        rec['error'] = f'conversion timed out after {timeout_s}s'
    except Exception as e:  # noqa: BLE001 — the take ships unconverted
        rec['error'] = f'{type(e).__name__}: {e}'[:300]
    finally:
        rec['seconds'] = round(time.time() - t0, 1)
    return rec


def melody_drift(src_wav, conv_wav):
    """Median |cents| and octave-error share between the source and converted
    pitch tracks, over frames both voice (the bench's melody measure)."""
    from zyg_workflows import vocal_analysis as VA

    ts, tc = VA.pitch_track(src_wav), VA.pitch_track(conv_wav)
    n = min(len(ts['f0']), len(tc['f0']))
    both = ts['voiced'][:n] & tc['voiced'][:n]
    if int(both.sum()) < 20:
        return {'measured': False, 'frames_both_voiced': int(both.sum())}
    d = 1200.0 * np.log2(np.maximum(tc['f0'][:n][both], 1) / np.maximum(ts['f0'][:n][both], 1))
    return {
        'measured': True,
        'frames_both_voiced': int(both.sum()),
        'median_abs_cents': round(float(np.median(np.abs(d))), 1),
        'octave_error_share': round(float((np.abs(d) > 600).mean()), 4),
    }


def ship_check(before, after, drift):
    """(ship, reasons). `before`/`after` are vocal_analysis.review reports of
    the unconverted and converted vocal; `drift` is melody_drift. Every check
    must have MEASURED and passed — an unmeasured check is a reason not to ship."""
    reasons = []
    if not drift.get('measured'):
        reasons.append('melody drift unmeasured')
    else:
        if drift['median_abs_cents'] > MAX_MEDIAN_CENTS:
            reasons.append(f'melody moved {drift["median_abs_cents"]} cents (limit {MAX_MEDIAN_CENTS:g})')
        if drift['octave_error_share'] > MAX_OCTAVE_SHARE:
            reasons.append(f'octave errors {drift["octave_error_share"]:.1%} (limit {MAX_OCTAVE_SHARE:.0%})')
    lb = (before or {}).get('lyrics') or {}
    la = (after or {}).get('lyrics') or {}
    if not (lb.get('measured') and la.get('measured')):
        reasons.append('lyric lines unmeasured ' + ('before' if not lb.get('measured') else 'after') + ' conversion')
    elif la.get('sung', 0) < lb.get('sung', 0) - MAX_LINES_LOST:
        reasons.append(f'lyric lines sung {lb.get("sung")} -> {la.get("sung")} (limit: lose {MAX_LINES_LOST})')
    cb = (before or {}).get('lyrics_bare') or {}
    ca = (after or {}).get('lyrics_bare') or {}
    if not (cb.get('measured') and ca.get('measured')):
        # Unmeasured is a reason not to ship, exactly as for the lyric check above:
        # a conversion whose cost to the words was never measured ships unconverted.
        reasons.append(
            'intelligibility unmeasured ' + ('before' if not cb.get('measured') else 'after') + ' conversion'
        )
    elif ca.get('clear', 0) < cb.get('clear', 0) - MAX_LINES_UNCLEARED:
        reasons.append(
            f'lines you can make out {cb.get("clear")} -> {ca.get("clear")} (limit: lose {MAX_LINES_UNCLEARED})'
        )
    return not reasons, reasons
