# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Does RVC make the kids-music singer the SAME voice on every song?

Model: models/vc_applio logs/warm_control (Applio RVC v2, 40 kHz, HiFi-GAN,
trained on 7 Warm Control renditions of Red Train, 176 s voiced).
Sources: the separated male vocal stems of 8 songs Warm Control did NOT train on.

Criteria, fixed BEFORE the run:
  melody     median |pitch change| <= 25 cents and octave errors <= 2 % of the
             frames voiced in both, on every song
  lyrics     converted lines sung >= source lines sung - 1, on every song
  identity   TitaNet cosine to the Warm Control reference rises on >= 7/8 songs;
             the mean rise toward Warm Control beats the mean rise toward a
             DIFFERENT male voice (m08 husky bass, same register) by >= 0.05;
             mean pairwise cosine across the 8 converted takes >= source + 0.15
  ear        A/B mixes (source vocal + backing vs converted vocal + backing) —
             the operator's call, not a number

Output: output/kidsmusic/_voice_build/vc/bench/results.json, ab/*.mp3
"""

import itertools
import json
import logging as _zyg_logging
import os
import shutil
import subprocess
import sys
import time

import numpy as np
from zyg_workflows import paths
from zyg_workflows.bin import exe

CREWS = str(paths.ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
if os.path.isdir(CREWS):  # absent on a bare checkout (CI, a fresh clone)
    os.chdir(CREWS)
import soundfile as sf  # noqa: E402

from zyg_workflows import vocal_analysis as VA  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)

APPLIO = str(paths.ZYG_LEGACY_MODELS / 'vc_applio')
WORKER = os.path.join(CREWS, 'tools', 'vc_applio_worker.py')
VB = os.path.join(CREWS, 'output/kidsmusic/_voice_build')
# VC_MODEL picks the RVC model; the songs, references and criteria never change.
MODEL = os.environ.get('VC_MODEL', 'warm_control')
OUT = os.path.join(VB, 'vc', 'bench' if MODEL == 'warm_control' else f'bench_{MODEL}')
SOURCES = {  # stem id -> song job (for plan + lyrics)
    'live_82b8bc806676': '82b8bc806676',
    'bench_c7284ed06145_base': 'c7284ed06145',
    'bench_0fc29420eb5a_base': '0fc29420eb5a',
    'bench_37159301a13c_base': '37159301a13c',
    'bench_e2cd9a19ef90_base': 'e2cd9a19ef90',
    'bench_6e0a355deadf_base': '6e0a355deadf',
    'bench_dd194f224b94_lead12': 'dd194f224b94',
    'bench_19387e019f27_lead12': '19387e019f27',
}
REFS = {'warm_control': 'rt_m01_warm_control', 'husky_bass': 'rt_m08_husky_bass'}
ARMS = {'idx050': (0.5, 0.33), 'idx075': (0.75, 0.33)}


def log(m):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {m}')


def convert(arm, in_dir):
    rate, protect = ARMS[arm]
    dst = os.path.join(OUT, arm)
    if os.path.isdir(dst) and len(os.listdir(dst)) >= len(SOURCES):
        return dst, {'cached': True}
    r = subprocess.run(
        [os.path.join(APPLIO, '.venv/bin/python'), WORKER, 'convert', MODEL, in_dir, dst, str(rate), str(protect)],
        cwd=APPLIO,
        capture_output=True,
        text=True,
        timeout=3600,
    )
    res = next(
        (json.loads(x) for x in reversed(r.stdout.strip().splitlines()) if x.startswith('{')),
        {'ok': False, 'error': r.stderr[-400:]},
    )
    return dst, res


def match_gain_db(src, conv, sr, frame_s=0.05):
    """dB to add to `conv` so its RMS over the source's sung frames equals the
    source's. RVC's output level drifted -6..+5 dB from its source on bench v1."""
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
    """b[x + lag] ~ a[x], from 10 ms RMS envelopes (coarse, then exact)."""
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


def main():
    os.makedirs(OUT, exist_ok=True)
    in_dir = os.path.join(OUT, 'in')
    os.makedirs(in_dir, exist_ok=True)
    for sid in SOURCES:
        dst = os.path.join(in_dir, f'{sid}.wav')
        if not os.path.isfile(dst):
            shutil.copyfile(os.path.join(VB, 'stems', sid, 'vocals.wav'), dst)
    conv = {}
    for arm in ARMS:
        d, res = convert(arm, in_dir)
        conv[arm] = d
        log(f'convert {arm}: {res.get("ok", res.get("cached"))} {res.get("error", "")} {res.get("seconds", "")}s')

    rows = {}
    clips, asr = {}, {}
    for sid, job in SOURCES.items():
        plan = json.load(open(os.path.join(CREWS, 'output/kidsmusic', job, 'song.json')))
        src = os.path.join(in_dir, f'{sid}.wav')
        tr_s = VA.pitch_track(src)
        row = {'song': job}
        clips[f'{sid}|src'] = VA.voiced_clip(src, os.path.join(OUT, 'clips', f'{sid}.src.wav'), track=tr_s)['path']
        asr[f'{sid}|src'] = {'wav': src, 'chunks': VA.phrase_chunks(tr_s), 'prompt': VA.lyric_prompt(plan)}
        ys, sr_s = sf.read(src, dtype='float32', always_2d=True)
        for arm in ARMS:
            cpath = os.path.join(conv[arm], f'{sid}.wav')
            if not os.path.isfile(cpath):
                row[arm] = {'error': 'not converted'}
                continue
            tr_c = VA.pitch_track(cpath)
            n = min(len(tr_s['f0']), len(tr_c['f0']))
            both = tr_s['voiced'][:n] & tr_c['voiced'][:n]
            d = 1200.0 * np.log2(np.maximum(tr_c['f0'][:n][both], 1) / np.maximum(tr_s['f0'][:n][both], 1))
            yc, sr_c = sf.read(cpath, dtype='float32', always_2d=True)
            import librosa

            yc_rs = librosa.resample(yc.mean(axis=1), orig_sr=sr_c, target_sr=sr_s) if sr_c != sr_s else yc.mean(axis=1)
            lag, corr = lag_samples(ys.mean(axis=1), yc_rs, sr_s)
            row[arm] = {
                'pitch_median_abs_cents': round(float(np.median(np.abs(d))), 1) if d.size else None,
                'octave_error_share': round(float((np.abs(d) > 600).mean()), 4) if d.size else None,
                'frames_both_voiced': int(both.sum()),
                'voiced_s_src': round(float(tr_s['voiced'].sum()) * VA.HOP_S, 1),
                'voiced_s_conv': round(float(tr_c['voiced'].sum()) * VA.HOP_S, 1),
                'rms_db_src': round(VA.db(float(np.sqrt(np.mean(ys**2)))), 1),
                'rms_db_conv': round(VA.db(float(np.sqrt(np.mean(yc**2)))), 1),
                'lag_samples': int(lag),
                'envelope_corr': corr,
                'sr_conv': int(sr_c),
            }
            clips[f'{sid}|{arm}'] = VA.voiced_clip(cpath, os.path.join(OUT, 'clips', f'{sid}.{arm}.wav'), track=tr_c)[
                'path'
            ]
            asr[f'{sid}|{arm}'] = {'wav': cpath, 'chunks': VA.phrase_chunks(tr_c), 'prompt': VA.lyric_prompt(plan)}
            # A/B mix: the converted vocal back over its own backing, time-aligned
            rest, sr_r = sf.read(os.path.join(VB, 'stems', sid, 'no_vocals.wav'), dtype='float32', always_2d=True)
            yc_al = (
                yc_rs[lag:] if lag > 0 else (np.concatenate([np.zeros(-lag, np.float32), yc_rs]) if lag < 0 else yc_rs)
            )
            g = match_gain_db(ys.mean(axis=1), yc_al, sr_s)
            row[arm]['level_match_db'] = round(g, 1)
            yc_al = yc_al * (10.0 ** (g / 20.0))
            yc_st = np.stack([yc_al, yc_al], 1)
            m = min(len(rest), len(yc_st), len(ys))
            ab = os.path.join(OUT, 'ab')
            os.makedirs(ab, exist_ok=True)
            for tag, voc in (('A_source', ys[:m]), (f'B_{arm}', yc_st[:m])):
                mix = rest[:m] + voc
                mix = mix / max(1.0, float(np.abs(mix).max()) / 0.95)
                w = os.path.join(ab, f'{job}.{tag}.wav')
                sf.write(w, mix, sr_s, subtype='PCM_16')
                subprocess.run([exe('ffmpeg'), '-y', '-v', 'error', '-i', w, '-b:a', '192k', w[:-4] + '.mp3'])
                os.remove(w)
        rows[sid] = row
        log(
            f'{job}: '
            + ' | '.join(
                f'{a} {row[a].get("pitch_median_abs_cents")}c oct {row[a].get("octave_error_share")} '
                f'lag {row[a].get("lag_samples")}'
                for a in ARMS
                if a in row
            )
        )

    for name, rid in REFS.items():
        voc = os.path.join(VB, 'stems', rid, 'vocals.wav')
        clips[f'REF|{name}'] = VA.voiced_clip(voc, os.path.join(OUT, 'clips', f'ref.{name}.wav'))['path']
    log(f'transcribing {len(asr)} tracks')
    words = VA.transcribe(asr, log_fn=log, timeout_s=3600)
    log(f'embedding {len(clips)} clips')
    emb = VA.embed(clips, log_fn=log, timeout_s=3600)

    verdict = {'melody': True, 'lyrics': True}
    for sid, job in SOURCES.items():
        plan = json.load(open(os.path.join(CREWS, 'output/kidsmusic', job, 'song.json')))
        row = rows[sid]
        sung_src = sum(1 for r in VA.align_lines(plan, words.get(f'{sid}|src') or [])['lines'] if r['sung'])
        row['lines_sung_src'] = sung_src
        for arm in ARMS:
            if 'error' in row.get(arm, {}):
                continue
            a = row[arm]
            a['lines_sung_conv'] = sum(
                1 for r in VA.align_lines(plan, words.get(f'{sid}|{arm}') or [])['lines'] if r['sung']
            )
            for name in REFS:
                e_ref, e_s, e_c = emb.get(f'REF|{name}'), emb.get(f'{sid}|src'), emb.get(f'{sid}|{arm}')
                if e_ref is not None and e_s is not None and e_c is not None:
                    a[f'cos_{name}_src'] = round(VA.cosine(e_ref, e_s), 4)
                    a[f'cos_{name}_conv'] = round(VA.cosine(e_ref, e_c), 4)
            if arm == 'idx050':
                if not (
                    a['pitch_median_abs_cents'] is not None
                    and a['pitch_median_abs_cents'] <= 25
                    and a['octave_error_share'] <= 0.02
                ):
                    verdict['melody'] = False
                if a['lines_sung_conv'] < sung_src - 1:
                    verdict['lyrics'] = False

    summary = {}
    for arm in ARMS:
        got = [rows[s][arm] for s in SOURCES if 'cos_warm_control_conv' in rows[s].get(arm, {})]
        rise_wc = [g['cos_warm_control_conv'] - g['cos_warm_control_src'] for g in got]
        rise_hb = [g['cos_husky_bass_conv'] - g['cos_husky_bass_src'] for g in got]
        pair_src = [
            VA.cosine(emb[f'{a}|src'], emb[f'{b}|src'])
            for a, b in itertools.combinations(SOURCES, 2)
            if f'{a}|src' in emb and f'{b}|src' in emb
        ]
        pair_conv = [
            VA.cosine(emb[f'{a}|{arm}'], emb[f'{b}|{arm}'])
            for a, b in itertools.combinations(SOURCES, 2)
            if f'{a}|{arm}' in emb and f'{b}|{arm}' in emb
        ]
        summary[arm] = {
            'songs': len(got),
            'wc_rises_on': sum(1 for x in rise_wc if x > 0),
            'mean_rise_toward_warm_control': round(float(np.mean(rise_wc)), 4) if rise_wc else None,
            'mean_rise_toward_husky_bass': round(float(np.mean(rise_hb)), 4) if rise_hb else None,
            'pairwise_cos_src': round(float(np.mean(pair_src)), 4) if pair_src else None,
            'pairwise_cos_conv': round(float(np.mean(pair_conv)), 4) if pair_conv else None,
            'pitch_median_abs_cents_worst': max(
                (rows[s][arm]['pitch_median_abs_cents'] or 0) for s in SOURCES if arm in rows[s]
            ),
            'octave_error_share_worst': max(
                (rows[s][arm]['octave_error_share'] or 0) for s in SOURCES if arm in rows[s]
            ),
            'lines_lost_worst': max(
                rows[s]['lines_sung_src'] - rows[s][arm].get('lines_sung_conv', 0) for s in SOURCES if arm in rows[s]
            ),
        }
    s = summary['idx050']
    verdict['identity'] = bool(
        s['wc_rises_on'] >= 7
        and s['mean_rise_toward_warm_control'] - s['mean_rise_toward_husky_bass'] >= 0.05
        and s['pairwise_cos_conv'] >= s['pairwise_cos_src'] + 0.15
    )
    verdict['pass'] = all(verdict.values())
    json.dump(
        {'model': MODEL, 'rows': rows, 'summary': summary, 'verdict': verdict, 'arms': ARMS},
        open(os.path.join(OUT, 'results.json'), 'w'),
        indent=1,
    )
    log(f'SUMMARY {json.dumps(summary)}')
    log(f'VERDICT {verdict}')


if __name__ == '__main__':
    main()
