# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.lyric_asr_bench`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.tools.lyric_asr_bench` still reaches it.
"""

import json
import os


def main():
    # soundfile is not part of a bare checkout (the library module is skip-listed for it), so the
    # CLI imports it only when it runs.
    import soundfile as sf

    # The library module needs Blender/bpy or an audio stack a bare checkout has not got (it is on
    # tests/import_smoke_skip.txt), so the CLI imports it only when it runs; this module imports clean.
    from zyg_workflows.tools.lyric_asr_bench import CASES, OUT, VA, VB, chunks_of, decode

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
