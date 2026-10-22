#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Seed bench for the replacement Cornelis line, scored on TRANSCRIPT.

"Endless screams we leave in our wake." rendered at the scene's own seed (1672)
and transcribed back as "Endless SCREENS we leave in our wake." One speech
island, correct loudness, no clipping — nothing else in the chain would notice,
which is precisely the failure `_verify_line_text` exists for.

/m/ and /n/ differ only in place of articulation, so a single ASR reading is not
enough to tell a bad RENDER from a bad HEARING. This renders the line across
seeds and transcribes each: if some seeds come back "screams" the synth can say
the word and the take is just a bad roll; if every seed says "screens" the word
itself is the problem and the line needs rewording, not re-rolling.

Same method the Abel cut used on "Home." (1672 → "Q. Home.", 7 → "You know,
home.", 1673 → "Kewaum.", 99 → correct). The seed re-rolls the SAMPLER only —
identity still comes from the frozen cast clone — so every take here is the same
voice.

usage:  python3 bench_wake_line.py [seed ...]
"""

import os
import sys

from zyg_workflows.paths import ZYG_CREWS_ROOT

CREWS = str(ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
if os.path.isdir(CREWS):  # absent on a bare checkout (CI, a fresh clone)
    os.chdir(CREWS)

from zyg_workflows import storyteller_scene_service as sss  # noqa: E402
from zyg_workflows import scene_cornelis_day1 as cd1  # noqa: E402

TEXT = 'Endless screams we leave in our wake.'
KEYWORD = 'screams'
OUT = os.path.join(CREWS, 'output', 'storyteller', '_bench_wake_line')
SEEDS = [int(a) for a in sys.argv[1:]] or [1672, 7, 99, 404, 2024, 1673, 8814, 31337]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    voice = dict(cd1.CORNELIS_DAY1['voices']['cornelis'])
    print(f'ref: {os.path.basename(str(voice.get("ref")))}   text: {TEXT!r}')
    print(f'{"seed":>7}  {"dur":>5}  {"islands":>7}  {"kw":>3}  transcript')
    rows = []
    for sd in SEEDS:
        v = dict(voice, seed=sd)
        wav = os.path.join(OUT, f'wake_seed{sd}.wav')
        if not os.path.isfile(wav):
            if not sss._synth_line(TEXT, wav, v, log_fn=lambda m: None):
                print(f'{sd:>7}  SYNTH FAILED')
                continue
        d = sss._read_mono48k(wav)
        isl = sss._speech_islands(d)
        probe = os.path.join(OUT, '_probe.wav')
        import soundfile as sf

        sf.write(probe, d, 48000)
        heard = sss._transcribe(probe, log_fn=lambda m: None) or ''
        os.path.isfile(probe) and os.remove(probe)
        norm = ''.join(c for c in heard.lower() if c.isalnum() or c == ' ').split()
        want = ''.join(c for c in TEXT.lower() if c.isalnum() or c == ' ').split()
        kw = KEYWORD in norm
        exact = norm == want
        rows.append((sd, kw, exact, heard, len(d) / 48000, len(isl)))
        mark = 'YES' if kw else '-'
        print(f'{sd:>7}  {len(d) / 48000:5.2f}  {len(isl):>7}  {mark:>3}  "{heard}"' + ('   <= EXACT' if exact else ''))

    good = [r for r in rows if r[1]]
    print()
    if not good:
        print(
            f'NO seed transcribed "{KEYWORD}" — {len(rows)} takes, all heard as '
            f'something else. That points at the WORD, not the roll: either the '
            f'ASR cannot separate /m/ from /n/ here, or the synth cannot say it. '
            f'Listen before rewording.'
        )
    else:
        print(
            f'{len(good)}/{len(rows)} seeds say "{KEYWORD}" — the synth CAN say the '
            f'word, so 1672 was a bad roll. Exact matches: '
            f'{[r[0] for r in rows if r[2]] or "none"}'
        )
    print(f'takes kept in {OUT}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
