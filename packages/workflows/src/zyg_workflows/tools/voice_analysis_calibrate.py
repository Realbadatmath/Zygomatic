# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Calibrate vocal_analysis.py on takes whose answers are already known.

Every number the production gate will act on is tested here against a null
first. Takes (all on disk, nothing rendered here):

  bench    output/kidsmusic/_male_octave_bench — stock male caption on 12 songs,
           score and lowered-melody conditioning, seeds +0..+2; labels from the
           bench's own gate reads (male / high / no vocal)
  null     output/kidsmusic/_voice_build/null_takes — m05/m06/m08 captions on the
           SAME 12 songs, same seed and conditioning as bench 'base'
  redtrain the ten male captions on one song (m01 = Warm Control reference)
  female   shipped adult_female takes from earlier jobs
  live     the three bumblebee/digger production takes

Questions, each with its null:
  identity   1. same take, two halves  vs  different captions on one song
             2. PAIRED across songs: is the stock-caption take closer to the Warm
                Control reference than m05/m06/m08 on the same song?
             3. do stock-caption takes cluster with each other across songs more
                than with other captions?
  register   per-line F0 on known-male vs known-high takes
  key        in-key share in the true key vs the same frames scored a semitone off
  level      per-line vocal-over-backing spread

Output: output/kidsmusic/_voice_build/calibration.json (+ per-take rows.json).
Stems are cached under _voice_build/stems/<id>/ so a rerun only re-measures.
"""

import glob
import json
import logging as _zyg_logging
import os
import sys
import time

import numpy as np
from zyg_workflows import paths

CREWS = str(paths.ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
if os.path.isdir(CREWS):  # absent on a bare checkout (CI, a fresh clone)
    os.chdir(CREWS)

from zyg_workflows import kids_music_theory as T  # noqa: E402
from zyg_workflows import vocal_analysis as VA  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)


KM = os.path.join(CREWS, 'output/kidsmusic')
VB = os.path.join(KM, '_voice_build')
BENCH = os.path.join(KM, '_male_octave_bench')
SONGS = [
    '19387e019f27',
    'c7284ed06145',
    '1ba342d5cd75',
    '0fc29420eb5a',
    '1da0a2c6f257',
    '36039a6c117a',
    '37159301a13c',
    '3f2b407846b0',
    '5e42a3574fd4',
    'e2cd9a19ef90',
    'dd194f224b94',
    '6e0a355deadf',
]
BENCH_ARMS = ['base', 'lead12', 'base+1', 'lead12+1', 'base+2', 'lead12+2']


def log(m):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {m}')


def plan_of(job):
    return json.load(open(os.path.join(KM, job, 'song.json')))


def collect():
    labels = {}
    for f in ('results.json', 'results_seeds.json'):
        p = os.path.join(BENCH, f)
        if os.path.isfile(p):
            for r in json.load(open(p)):
                labels[(r['song'], r['arm'])] = r
    takes = []
    for sid in SONGS:
        for arm in BENCH_ARMS:
            path = os.path.join(BENCH, sid, f'{arm}.mp3')
            r = labels.get((sid, arm))
            if os.path.isfile(path) and r:
                lab = 'novox' if r.get('f0') is None else ('male' if r.get('male') else 'high')
                takes.append(
                    {
                        'id': f'bench_{sid}_{arm}',
                        'path': path,
                        'song': sid,
                        'group': 'bench',
                        'voice': 'stock',
                        'label': lab,
                    }
                )
        for cap in ('m05_playful_cartoon', 'm06_folk_storyteller', 'm08_husky_bass'):
            path = os.path.join(VB, 'null_takes', sid, f'{cap}.mp3')
            if os.path.isfile(path):
                takes.append(
                    {'id': f'null_{sid}_{cap}', 'path': path, 'song': sid, 'group': 'null', 'voice': cap, 'label': None}
                )
    rt = os.path.join(KM, '1ba342d5cd75', 'male_voices')
    for p in sorted(glob.glob(os.path.join(rt, 'm[0-9][0-9]_*.mp3'))):
        if p.endswith('_master.mp3'):
            continue
        key = os.path.basename(p)[:-4]
        takes.append(
            {
                'id': f'rt_{key}',
                'path': p,
                'song': '1ba342d5cd75',
                'group': 'redtrain',
                'voice': 'stock' if key == 'm01_warm_control' else key,
                'label': 'male',
            }
        )
    for job in sorted(os.listdir(KM)):
        man = os.path.join(KM, job, 'manifest.json')
        song = os.path.join(KM, job, 'song.mp3')
        if not (os.path.isfile(man) and os.path.isfile(song)):
            continue
        try:
            m = json.load(open(man))
        except ValueError as _exc:
            _zyg_log.debug('manifest unreadable, take skipped: %s', _exc)
            continue
        b = m.get('brief') or {}
        sg = (m.get('gates') or {}).get('singer') or {}
        if b.get('singer') == 'adult_female' and sg.get('ok'):
            takes.append(
                {
                    'id': f'female_{job}',
                    'path': song,
                    'song': job,
                    'group': 'female',
                    'voice': 'female',
                    'label': 'female',
                }
            )
    for job, lab in (('19387e019f27', 'high'), ('82b8bc806676', 'male'), ('c7284ed06145', 'male')):
        takes.append(
            {
                'id': f'live_{job}',
                'path': os.path.join(KM, job, 'song.mp3'),
                'song': job,
                'group': 'live',
                'voice': 'stock',
                'label': lab,
            }
        )
    return takes


def measure_all(takes):
    rows_path = os.path.join(VB, 'rows.json')
    rows = {r['id']: r for r in json.load(open(rows_path))} if os.path.isfile(rows_path) else {}
    clips = {}
    # 1. stems
    for i, tk in enumerate(takes):
        sd = os.path.join(VB, 'stems', tk['id'])
        if not os.path.isfile(os.path.join(sd, 'vocals.wav')):
            sep = VA.separate(tk['path'], sd)
            if not sep.get('ok'):
                log(f'{tk["id"]}: separation failed {sep.get("error")}')
        if i % 20 == 0:
            log(f'separated {i + 1}/{len(takes)}')
    # 2. lyrics, one recogniser load for every stem still missing words.json
    need = {
        tk['id']: os.path.join(VB, 'stems', tk['id'], 'vocals.wav')
        for tk in takes
        if os.path.isfile(os.path.join(VB, 'stems', tk['id'], 'vocals.wav'))
        and not os.path.isfile(os.path.join(VB, 'stems', tk['id'], 'words.json'))
    }
    if need:
        log(f'chunking {len(need)} stems')
        by_id = {tk['id']: tk for tk in takes}
        items = {}
        for tid, voc in need.items():
            tr = VA.pitch_track(voc)
            items[tid] = {
                'wav': voc,
                'chunks': VA.phrase_chunks(tr),
                'prompt': VA.lyric_prompt(plan_of(by_id[tid]['song'])),
            }
        log(f'transcribing {len(need)} stems (chunked, prompted)')
        got = VA.transcribe(items, log_fn=log, timeout_s=7200)
        for tid, words in got.items():
            json.dump({'ok': True, 'words': words}, open(os.path.join(VB, 'stems', tid, 'words.json'), 'w'))
    # 3. measure
    for i, tk in enumerate(takes):
        sd = os.path.join(VB, 'stems', tk['id'])
        voc, rest = os.path.join(sd, 'vocals.wav'), os.path.join(sd, 'no_vocals.wav')
        if not os.path.isfile(voc):
            continue
        wpath = os.path.join(sd, 'words.json')
        words = json.load(open(wpath))['words'] if os.path.isfile(wpath) else None
        full, h1, h2 = (os.path.join(sd, f'clip_{n}.wav') for n in ('full', 'h1', 'h2'))
        if tk['id'] not in rows or 'lyrics' not in rows[tk['id']] or not os.path.isfile(h2):
            plan = plan_of(tk['song'])
            singer = T.SINGERS['adult_female' if tk['group'] == 'female' else 'adult_male']
            m = VA.measure(voc, rest, plan, singer, words=words)
            # the lyric null: these words aligned against a DIFFERENT song's lyrics
            other = next(s for s in SONGS if s != tk['song'] and plan_of(s).get('lyrics'))
            lyr_null = VA.align_lines(plan_of(other), words) if words else None
            tr = m.pop('track')
            vt = tr['t'][tr['voiced']]
            mid = float(np.median(vt)) if vt.size else 0.0
            c_full = VA.voiced_clip(voc, full, track=tr)
            c1 = VA.voiced_clip(voc, h1, track=tr, end_s=mid)
            c2 = VA.voiced_clip(voc, h2, track=tr, start_s=mid)
            # the key null: the same stable frames scored against a scale one semitone up
            wrong = dict(plan, key=dict(plan['key'], tonic_pc=(int(plan['key'].get('tonic_pc') or 0) + 1) % 12))
            m_wrong = VA.measure(voc, rest, wrong, singer, track=tr)
            rows[tk['id']] = dict(
                tk,
                **{k: m[k] for k in ('lines', 'lyrics', 'register', 'key', 'level')},
                key_wrong=m_wrong['key'],
                lyrics_null=(
                    {
                        'sung': sum(1 for r in lyr_null['lines'] if r['sung']),
                        'lines': len(lyr_null['lines']),
                        'mean_coverage': round(float(np.mean([r['coverage'] for r in lyr_null['lines']])), 3),
                    }
                    if lyr_null
                    else None
                ),
                clip_s={'full': c_full['seconds'], 'h1': c1['seconds'], 'h2': c2['seconds']},
            )
            json.dump(list(rows.values()), open(rows_path, 'w'), indent=1)
        for n, p in (('full', full), ('h1', h1), ('h2', h2)):
            if rows[tk['id']]['clip_s'][n] >= 3.0:
                clips[f'{tk["id"]}|{n}'] = p
        if i % 10 == 0:
            log(f'measured {i + 1}/{len(takes)}')
    return rows, clips


def summarize(rows, emb):
    cal = {}
    E = lambda tid, n='full': emb.get(f'{tid}|{n}')  # noqa: E731
    cos = VA.cosine
    voiced = [
        r
        for r in rows.values()
        if r['clip_s']['h1'] >= 3
        and r['clip_s']['h2'] >= 3
        and E(r['id'], 'h1') is not None
        and E(r['id'], 'h2') is not None
    ]

    # identity 1: same take halves vs other captions on Red Train
    same = [cos(E(r['id'], 'h1'), E(r['id'], 'h2')) for r in voiced]
    rt = [r for r in voiced if r['group'] == 'redtrain']
    cross_cap = [cos(E(a['id'], 'h1'), E(b['id'], 'h2')) for a in rt for b in rt if a['id'] != b['id']]
    fem = [r for r in voiced if r['group'] == 'female']
    male_rows = [r for r in voiced if r['label'] == 'male']
    sex = [cos(E(a['id']), E(b['id'])) for a in male_rows[:30] for b in fem]
    q = lambda xs: (
        {
            'n': len(xs),
            'mean': round(float(np.mean(xs)), 4),
            'p10': round(float(np.percentile(xs, 10)), 4),  # noqa: E731
            'p50': round(float(np.median(xs)), 4),
            'p90': round(float(np.percentile(xs, 90)), 4),
        }
        if xs
        else {'n': 0}
    )
    cal['identity_same_take_halves'] = q(same)
    cal['identity_redtrain_cross_caption_halves'] = q(cross_cap)
    cal['identity_male_vs_female'] = q(sex)

    # identity 2: paired across songs vs the Warm Control reference
    ref = E('rt_m01_warm_control')
    paired = []
    for sid in SONGS:
        if sid == '1ba342d5cd75':
            continue
        stock = [
            r
            for r in rows.values()
            if r['song'] == sid
            and r['group'] == 'bench'
            and r['id'].endswith('_base')
            and r['label'] == 'male'
            and E(r['id']) is not None
        ]
        others = [
            r
            for r in rows.values()
            if r['song'] == sid
            and r['group'] == 'null'
            and E(r['id']) is not None
            and (r['register'].get('f0_median_hz') or 0)
            and r['register']['f0_median_hz'] <= 285
        ]
        if not stock or not others or ref is None:
            continue
        s = cos(ref, E(stock[0]['id']))
        o = {r['voice']: round(cos(ref, E(r['id'])), 4) for r in others}
        paired.append(
            {
                'song': sid,
                'stock': round(s, 4),
                'others': o,
                'stock_wins': sum(1 for v in o.values() if s > v),
                'of': len(o),
            }
        )
    cal['identity_paired_vs_warm_control'] = paired
    wins = sum(p['stock_wins'] for p in paired)
    total = sum(p['of'] for p in paired)
    cal['identity_paired_summary'] = {'stock_closer': wins, 'comparisons': total}

    # identity 3: do stock takes cluster across songs?
    stock_all = [
        r
        for r in rows.values()
        if r['voice'] == 'stock' and r['label'] == 'male' and r['group'] in ('bench', 'live') and E(r['id']) is not None
    ]
    null_all = [r for r in rows.values() if r['group'] == 'null' and E(r['id']) is not None]
    ss = [cos(E(a['id']), E(b['id'])) for a in stock_all for b in stock_all if a['song'] < b['song']]
    sn = [cos(E(a['id']), E(b['id'])) for a in stock_all for b in null_all if a['song'] != b['song']]
    nn = [
        cos(E(a['id']), E(b['id']))
        for a in null_all
        for b in null_all
        if a['song'] != b['song'] and a['voice'] == b['voice']
    ]
    cal['identity_cross_song_stock_vs_stock'] = q(ss)
    cal['identity_cross_song_stock_vs_other_caption'] = q(sn)
    cal['identity_cross_song_same_other_caption'] = q(nn)
    same_song_diff_voice = [cos(E(a['id']), E(b['id'])) for a in stock_all for b in null_all if a['song'] == b['song']]
    cal['identity_same_song_stock_vs_other_caption'] = q(same_song_diff_voice)

    # lyrics vs its null
    lm = [r for r in rows.values() if (r.get('lyrics') or {}).get('measured') and r['label'] != 'novox']
    cal['lyrics_share_of_lines_sung'] = q([r['lyrics']['sung'] / max(1, r['lyrics']['lines']) for r in lm])
    cal['lyrics_null_share_sung_other_song'] = q(
        [r['lyrics_null']['sung'] / max(1, r['lyrics_null']['lines']) for r in lm if r.get('lyrics_null')]
    )
    cal['lyrics_takes_with_missing_lines'] = {
        'takes': len(lm),
        'with_missing': sum(1 for r in lm if r['lyrics']['missing']),
    }
    nv = [r for r in rows.values() if (r.get('lyrics') or {}).get('measured') and r['label'] == 'novox']
    cal['lyrics_share_sung_on_novox_takes'] = q([r['lyrics']['sung'] / max(1, r['lyrics']['lines']) for r in nv])

    # register per line (aligned, sung lines only)
    def lines_of(lab):
        return [
            ln
            for r in rows.values()
            if r['label'] == lab and r['group'] in ('bench', 'live', 'redtrain')
            for ln in r['lines']
            if ln.get('f0_median_hz') and ln.get('sung')
        ]

    for lab in ('male', 'high'):
        ls = lines_of(lab)
        cal[f'register_line_median_{lab}'] = q([ln['f0_median_hz'] for ln in ls])
        cal[f'register_line_above_share_{lab}'] = q([ln['above_band_share'] for ln in ls])
        cal[f'register_line_p95_{lab}'] = q([ln['f0_p95_hz'] for ln in ls])
    male_takes = [r for r in rows.values() if r['label'] == 'male' and r['group'] in ('bench', 'live')]
    cal['register_male_take_lines_above_285'] = q(
        [sum(1 for ln in r['lines'] if (ln.get('f0_median_hz') or 0) > 285) for r in male_takes]
    )

    # key vs its null
    kk = [r for r in rows.values() if r['key'].get('in_key_share') is not None]
    cal['key_in_key_share_true'] = q([r['key']['in_key_share'] for r in kk])
    cal['key_in_key_share_semitone_off'] = q(
        [r['key_wrong']['in_key_share'] for r in kk if r['key_wrong'].get('in_key_share') is not None]
    )
    cal['key_intonation_cents'] = q([r['key']['intonation_cents'] for r in kk])
    cal['key_line_in_key_share_true'] = q(
        [ln['in_key_share'] for r in kk for ln in r['lines'] if ln.get('in_key_share') is not None]
    )

    # level
    vv = [
        ln['vocal_over_backing_db']
        for r in rows.values()
        if r['label'] in ('male', 'high', 'female')
        for ln in r['lines']
        if ln.get('vocal_over_backing_db') is not None and (ln.get('voiced_s') or 0) > 0.5
    ]
    cal['level_line_vocal_over_backing_db'] = q(vv)
    cal['level_take_stem_peak_dbfs'] = q([r['level']['stem_peak_dbfs'] for r in rows.values()])
    return cal


def main():
    takes = collect()
    log(
        f'{len(takes)} takes: '
        + ', '.join(
            f'{g}={sum(1 for t in takes if t["group"] == g)}' for g in ('bench', 'null', 'redtrain', 'female', 'live')
        )
    )
    rows, clips = measure_all(takes)
    emb_path = os.path.join(VB, 'embeddings.json')
    emb = {}
    if os.path.isfile(emb_path):
        emb = {k: np.asarray(v) for k, v in json.load(open(emb_path)).items()}
    todo = {k: v for k, v in clips.items() if k not in emb}
    if todo:
        log(f'embedding {len(todo)} clips')
        emb.update(VA.embed(todo, log_fn=log, timeout_s=3600))
        json.dump({k: [float(x) for x in v] for k, v in emb.items()}, open(emb_path, 'w'))
    cal = summarize(rows, emb)
    json.dump(cal, open(os.path.join(VB, 'calibration.json'), 'w'), indent=1)
    for k, v in cal.items():
        if k == 'identity_paired_vs_warm_control':
            for p in v:
                log(f'  paired {p["song"]}: stock {p["stock"]} vs {p["others"]} -> {p["stock_wins"]}/{p["of"]}')
            continue
        log(f'{k}: {v}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
