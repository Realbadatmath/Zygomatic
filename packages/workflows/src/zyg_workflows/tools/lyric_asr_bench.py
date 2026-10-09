# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Can the lyric check be trusted? A known answer, by construction.

Whole-file Whisper (large-v3, unprompted, no VAD) lost entire 30-second windows
on sung stems: the digger take heard 43 words of ~80 and ended on the classic
hallucination "We'll see you next time."; the sleepy-moon take (voiced, 219 Hz)
heard 5 words. So "95 of 99 takes miss lines" measured the recogniser, not the
singer.

Arms (all faster-whisper large-v3):
  whole        the worker as it stands (baseline)
  chunk        the stem cut at silences into <= 12 s phrases, each decoded alone
  chunk_prompt the same, each chunk prompted with the plan's lyric text

Known answers:
  * the MUTE test — Red Train m01 with one fully sung line (L6 "Little red
    train stops with cheer") replaced by silence in the stem. A trustworthy arm
    reports L6 missing, and does not newly report any other line.
  * coverage on takes whose stems ARE voiced through the song (digger base,
    sleepy moon base) — an arm that still hears nothing there is not usable.
  * a prompted arm must not "hear" the muted line — that is the hallucination
    the prompt risks.
"""

import json
import os
import sys
from zyg_workflows import paths


CREWS = str(paths.ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
os.chdir(CREWS)
import soundfile as sf  # noqa: E402

from zyg_workflows import vocal_analysis as VA  # noqa: E402

VB = 'output/kidsmusic/_voice_build'
OUT = os.path.join(VB, 'asr_bench')
CASES = [
    ('rt_m01_warm_control', '1ba342d5cd75'),
    ('bench_c7284ed06145_base', 'c7284ed06145'),
    ('bench_e2cd9a19ef90_base', 'e2cd9a19ef90'),
    ('live_82b8bc806676', '82b8bc806676'),
    ('female_0fc29420eb5a', '0fc29420eb5a'),
]


def chunks_of(vocals, max_s=12.0, min_gap_s=0.35):
    tr = VA.pitch_track(vocals)
    v, t = tr['voiced'], tr['t']
    runs, i, n = [], 0, len(v)
    while i < n:
        if not v[i]:
            i += 1
            continue
        j = i
        while j < n and (v[j] or (j + int(min_gap_s / VA.HOP_S) < n and v[j : j + int(min_gap_s / VA.HOP_S)].any())):
            j += 1
        runs.append([max(0.0, t[i] - 0.25), t[min(j, n - 1)] + 0.25])
        i = j
    out = []
    for s, e in runs:  # split long runs, merge tiny ones
        while e - s > max_s:
            out.append([s, s + max_s])
            s += max_s
        if out and s - out[-1][1] < 0.5 and e - out[-1][0] <= max_s:
            out[-1][1] = e
        else:
            out.append([s, e])
    return out


def decode(model, audio16, prompt=None):
    segs, _ = model.transcribe(
        audio16,
        language='en',
        word_timestamps=True,
        vad_filter=False,
        beam_size=5,
        condition_on_previous_text=False,
        temperature=0.0,
        initial_prompt=prompt,
    )
    return [
        {'w': w.word.strip(), 'start': float(w.start), 'end': float(w.end), 'p': float(w.probability)}
        for s in segs
        for w in (s.words or [])
    ]


def main():
    import librosa
    from faster_whisper import WhisperModel

    os.makedirs(OUT, exist_ok=True)
    model = WhisperModel('large-v3', device='cuda', compute_type='float16')
    results = {}
    cases = list(CASES) + [('MUTE_rt_m01_L6', '1ba342d5cd75')]
    for tid, song in cases:
        plan = json.load(open(f'output/kidsmusic/{song}/song.json'))
        src = f'{VB}/stems/{tid if not tid.startswith("MUTE") else "rt_m01_warm_control"}/vocals.wav'
        y, sr = librosa.load(src, sr=16000, mono=True)
        if tid.startswith('MUTE'):
            words = json.load(open(f'{VB}/stems/rt_m01_warm_control/words.json'))['words']
            al = VA.align_lines(plan, words)
            ln = next(r for r in al['lines'] if r['line'] == 6)
            a, b = int((ln['start_s'] - 0.15) * sr), int((ln['end_s'] + 0.15) * sr)
            y = y.copy()
            y[a:b] = 0.0
            src = os.path.join(OUT, 'mute_rt_m01_L6.wav')
            sf.write(src, y, sr)
            results.setdefault('_mute', {})['window'] = [ln['start_s'], ln['end_s'], ln['text']]
        prompt = ' '.join(plan.get('lyrics') or [])
        row = {}
        row['whole'] = decode(model, y)
        ch = chunks_of(src)
        for arm, pr in (('chunk', None), ('chunk_prompt', prompt)):
            ws = []
            for s, e in ch:
                seg = y[int(s * sr) : int(e * sr)]
                for w in decode(model, seg, pr):
                    ws.append(dict(w, start=round(w['start'] + s, 2), end=round(w['end'] + s, 2)))
            row[arm] = ws
        results[tid] = {'chunks': len(ch)}
        for arm, ws in row.items():
            al = VA.align_lines(plan, ws)
            results[tid][arm] = {
                'words': len(ws),
                'sung': sum(1 for r in al['lines'] if r['sung']),
                'lines': len(al['lines']),
                'missing': [r['line'] for r in al['lines'] if not r['sung']],
                'extra_words': al['extra_words'],
            }
            json.dump(ws, open(os.path.join(OUT, f'{tid}.{arm}.json'), 'w'))
        print(tid, json.dumps(results[tid]), flush=True)
    json.dump(results, open(os.path.join(OUT, 'results.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
