# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.kidsmusic_repaint_spike_extra`, moved out of the library
module so that library code never prints; `python -m
zyg_workflows.tools.kidsmusic_repaint_spike_extra` still reaches it.
"""

from __future__ import annotations

import glob
import json
import os

from zyg_workflows.tools.kidsmusic_repaint_spike_extra import OUT, SR, _rms_db, beats


def main():
    import numpy as np
    import soundfile as sf
    from zyg_workflows import sung_pitch
    from faster_whisper import WhisperModel

    names = sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(OUT, '*.flac')))
    rt, _ = sf.read(os.path.join(OUT, 'rt.flac'))
    rt_beats = beats(os.path.join(OUT, 'rt.flac'))
    asr = WhisperModel('small', device='cpu', compute_type='int8', cpu_threads=12)
    res_path = os.path.join(OUT, 'extra.json')
    res = json.load(open(res_path)) if os.path.isfile(res_path) else {}
    for name in names:
        stem_dir = 'rt' if name == 'rt' else name
        if name in res or not os.path.isfile(os.path.join(OUT, 'work', stem_dir, 'stems', 'vocals.wav')):
            continue
        p = os.path.join(OUT, name + '.flac')
        y, _ = sf.read(p)
        r = {}
        b = beats(p)
        inwin = b[(b >= 20.0) & (b < 25.0)]
        if len(inwin):
            off = [float(np.min(np.abs(rt_beats - t))) * 1000 for t in inwin]
            r['beats_in_window'] = len(inwin)
            r['beat_offset_ms_median'] = round(float(np.median(off)), 1)
            r['beat_offset_ms_max'] = round(float(np.max(off)), 1)
        step = {}
        for t in (20.0, 25.0):
            a0, a1, b1 = int((t - 0.2) * SR), int(t * SR), int((t + 0.2) * SR)
            step[f'{t:g}s'] = {
                'render_db': round(_rms_db(y[a1:b1]) - _rms_db(y[a0:a1]), 1),
                'rt_db': round(_rms_db(rt[a1:b1]) - _rms_db(rt[a0:a1]), 1),
            }
        r['level_step_200ms'] = step
        work = os.path.join(OUT, 'work', name)
        voc = os.path.join(work, 'stems', 'vocals.wav')
        if name == 'rt' and not os.path.isfile(voc):
            voc = os.path.join(OUT, 'work', 'rt', 'stems', 'vocals.wav')
        if os.path.isfile(voc):
            v, vsr = sf.read(voc, always_2d=True)
            per = []
            for s in range(5):
                seg = os.path.join(work, f'voc_{20 + s}.wav')
                sf.write(seg, v[int((6 + s) * vsr) : int((7 + s) * vsr)], vsr)
                m = sung_pitch.measure_stem(seg)
                per.append(round(m['f0_median_hz'], 0) if m.get('ok') else None)
            r['f0_per_second_20_25'] = per
            segs, _info = asr.transcribe(voc, language='en', beam_size=5, word_timestamps=True, vad_filter=False)
            words = []
            for sg in segs:
                for w in sg.words or []:
                    t = 14.0 + w.start
                    words.append((round(t, 2), w.word.strip()))
            r['words_19_26'] = [w for w in words if 19.0 <= w[0] < 26.0]
        res[name] = r
        with open(res_path, 'w') as f:
            json.dump(res, f, indent=1)
        print(name, json.dumps(r), flush=True)


if __name__ == '__main__':
    main()
