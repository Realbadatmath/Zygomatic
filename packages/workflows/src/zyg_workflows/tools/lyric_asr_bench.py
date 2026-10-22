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

import os
import sys
from zyg_workflows import paths


CREWS = str(paths.ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
if os.path.isdir(CREWS):  # absent on a bare checkout (CI, a fresh clone)
    os.chdir(CREWS)
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


if __name__ == '__main__':  # the CLI lives in lyric_asr_bench_cli
    from zyg_workflows.tools.lyric_asr_bench_cli import main as _cli_main

    raise SystemExit(_cli_main())
