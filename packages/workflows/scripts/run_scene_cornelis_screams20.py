#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Cornelis Day 1 — the 20 s scream merge in place of the 16 s built bed.

A COPY of the shipping cut with one element swapped and one coupling
deliberately broken. `CORNELIS_DAY1` in scene_cornelis_day1.py is NOT edited:
this deepcopies it, so the approved cut stays buildable from its own module.

WHAT CHANGES
------------
The opening bed becomes `merge_2026_08_25_21_14_20_s.wav` — the 40-layer wall
built in the SFX merger on 2026-08-25 (screams staggered 0.0-19.32 s across the
stereo field, each pitched/room-treated) — replacing `crowd_agony_16s.wav`, and
it runs its FULL 20 s instead of being cut at 14.18 s.

**The handover coupling is broken ON PURPOSE (operator decision).** The module
says, twice and in capitals, that the scream's `fade_out_s` and the score's
`fade_in_s` MUST both equal `_HANDOVER_S` — screams out over four, score in over
the same four, one trade. That is no longer what happens here:

    screams   0.0 → 20.0   (fade out 16.0 → 20.0)
    score    10.18 → …     (fade in 10.18 → 14.18, unchanged)

so the two run TOGETHER for ~10 s and the screams then fade out alone under the
established score. Asked for explicitly after being shown the alternative
(moving the score to 16.0 to keep the 4 s trade). Do not "repair" this back to
the coupled form without asking — it is the point of the cut.

`src_start_s` goes 1.2 → 0.0, because at 20.0 s the source has no headroom left
to start late. That is safe here and it was measured, not assumed: the twice-run
sweep behind the 1.2 was protecting the settle's LANDING at 7.8-8.2 s, where he
starts speaking, from the built bed's half-second lulls. The merge is a denser
construction and does not breathe the same way. At 100 ms resolution, over the
window each actually plays:

    old crowd_agony_16s @ 1.2   landing min -35.6 dB  plateau sd 5.9 dB  1 quiet window
    new 20 s merge      @ 0.0   landing min -35.5 dB  plateau sd 3.4 dB  0 quiet windows

i.e. the landing is level with the approved one and the plateau is markedly
more even. Re-sweep if the asset is ever replaced again.

The LEVEL is untouched at -46 LUFS. That number was measured on this scene's
master chain (the limiter passes eat the voice's crest and let quiet material
through: the plateau took +22.1 dB where the voice took +10.5), and it is
applied to the EXCERPT before the shape, so it still describes the 3 s plateau.
But the excerpt is now a different length of a different source, so the
delivered plateau / murmur / voice distances are re-measured after the build —
the module's own instruction.

usage:  python3 run_scene_cornelis_screams20.py
"""

import copy
import json
import os
import sys

from zyg_workflows import paths

CREWS = str(paths.ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
if os.path.isdir(CREWS):  # absent on a bare checkout (CI, a fresh clone)
    os.chdir(CREWS)

from zyg_workflows import storyteller_scene_service as sss  # noqa: E402
from zyg_workflows import scene_cornelis_day1 as cd1  # noqa: E402

ST = os.path.join(CREWS, 'output', 'storyteller')
SRC_DIR = os.path.join(ST, 'scene_cornelis_day1')
SLUG = 'cornelis_day1_screams20'
OUT_DIR = os.path.join(ST, f'scene_{SLUG}')

SCREAM_FILE = 'merge_2026_08_25_21_14_20_s.wav'
SCREAM_DUR = 20.0  # the source is exactly this long — never ask for more
SCREAM_FADE_OUT = 4.0  # 16.0 → 20.0, alone, under the established score

_TAKES = (
    'line_00_cornelis.wav',
    'line_01_cornelis.wav',
    'line_02_cornelis.wav',
    'line_03_cornelis.wav',
    'anchor_00_cornelis.wav',
)


def _md5(p):
    import hashlib

    with open(p, 'rb') as fh:
        return hashlib.md5(fh.read(), usedforsecurity=False).hexdigest()


def main() -> int:
    if not os.path.isdir(OUT_DIR):
        print(
            f'[run] ABORT: {OUT_DIR} does not exist — carry the approved stills and takes across from {SRC_DIR} first'
        )
        return 2
    for f in _TAKES:
        if not os.path.isfile(os.path.join(OUT_DIR, f)):
            print(f'[run] ABORT: missing carried take {f}')
            return 2

    src = sss._audio_asset(SCREAM_FILE)
    if not os.path.isfile(src):
        print(
            f'[run] ABORT: {SCREAM_FILE} not found (looked through '
            f'{", ".join(os.path.basename(d) for d in sss._AUDIO_DIRS)})'
        )
        return 2
    dur = sss._audio_dur(src)
    if dur + 1e-3 < SCREAM_DUR:
        # A short source does not error — _music_segment LOOPS it, splicing the
        # wall back onto its own head. Fail instead.
        print(f'[run] ABORT: {SCREAM_FILE} is {dur:.2f}s, too short for a {SCREAM_DUR}s cue — it would be looped')
        return 2

    spec = copy.deepcopy(cd1.CORNELIS_DAY1)
    spec['slug'] = SLUG

    cue = next(c for c in spec['music'] if c.get('name') == 'crowd_agony')
    cue['file'] = SCREAM_FILE
    cue['src_start_s'] = 0.0
    cue['t_out'] = SCREAM_DUR  # absolute seconds, no longer _HANDOVER_END
    cue['fade_out_s'] = SCREAM_FADE_OUT
    # t_in, fade_in_s, settle and lufs all stay as approved.

    score = next(c for c in spec['music'] if c.get('name') == 'ledger_weight')
    print(
        f'[run] scream  {cue["t_in"]}→{cue["t_out"]}s  src_start '
        f'{cue["src_start_s"]}  fade {cue["fade_in_s"]}s in / '
        f'{cue["fade_out_s"]}s out  @ {cue["lufs"]} LUFS  ({SCREAM_FILE})'
    )
    print(
        f'[run] score   t_in {score["t_in"]} (unchanged), fade_in '
        f'{score["fade_in_s"]}s — handover coupling deliberately broken'
    )

    r = sss.build_scene(spec, out_dir=OUT_DIR)
    if not r:
        print('[run] FAILED')
        return 1
    print(f'[run] done: {r["video"]}')

    # ── verify it is a copy of the shipping cut, plus the swap ──────────────
    st = json.load(open(os.path.join(OUT_DIR, 'scene_state.json')))
    ref = json.load(open(os.path.join(SRC_DIR, 'scene_state.json')))
    ok = True
    for f in _TAKES:
        if _md5(os.path.join(OUT_DIR, f)) != _md5(os.path.join(SRC_DIR, f)):
            ok = False
            print(f'[verify] TAKE RE-RENDERED: {f}')
    print(f'[verify] {len(_TAKES)} takes checksummed against the shipped cut')

    if st['marks'] != ref['marks']:
        ok = False
        print(f'[verify] MARKS MOVED\n  was {ref["marks"]}\n  now {st["marks"]}')
    else:
        print(f'[verify] marks identical (total {st["marks"]["end"]}s)')

    for a, b in zip(st['events'], ref['events']):
        if round(a['t0'], 2) != round(b['t0'], 2) or round(a['t1'], 2) != round(b['t1'], 2):
            ok = False
            print(f'[verify] LINE MOVED {b.get("text", "")[:40]!r}')

    got = {c['name']: c for c in st['music']}
    was = {c['name']: c for c in ref['music']}
    s = got.get('crowd_agony')
    if not s or s['track'] != SCREAM_FILE:
        ok = False
        print(f'[verify] scream NOT swapped — track is {s and s["track"]}')
    elif (s['t_out'], s['src_start_s'], s['lufs']) != (SCREAM_DUR, 0.0, was['crowd_agony']['lufs']):
        ok = False
        print(f'[verify] scream cue not as authored: {s}')
    else:
        print(
            f'[verify] scream {s["t_in"]}→{s["t_out"]}s @ {s["lufs"]} LUFS, '
            f'settle {s["settle"]["db"]:+g} dB {s["settle"]["from_s"]}→'
            f'{s["settle"]["to_s"]}s held to {s["settle"]["held_until_s"]}s'
        )
    if got['ledger_weight']['t_in'] != was['ledger_weight']['t_in']:
        ok = False
        print(
            f'[verify] SCORE ENTRY MOVED {was["ledger_weight"]["t_in"]} → '
            f'{got["ledger_weight"]["t_in"]} — it was meant to stay put'
        )
    else:
        print(
            f'[verify] score entry held at {got["ledger_weight"]["t_in"]}s '
            f'(overlaps the screams for '
            f'{SCREAM_DUR - got["ledger_weight"]["t_in"]:.2f}s by design)'
        )
    return 0 if ok else 4


if __name__ == '__main__':
    raise SystemExit(main())
