#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Cornelis Day 1 — 20 s scream merge + the last cabin line replaced.

Builds on run_scene_cornelis_screams20.py (same scream swap, same deliberately
broken handover) and changes ONE more thing:

    "Yet the cost is more than I can bear."   ->   "Endless screams we leave in our wake."

That is `spec['dialogue'][3]` — index 2 is the 5.8 s scored beat, which is why
the file on disk is `line_03_cornelis.wav` and not `line_02`.

WHY THIS IS NOT A ONE-LINE EDIT
-------------------------------
The module says it plainly on `ledger_weight`: "Any further edit to t_in or
t_out is a LEVEL change: re-run the same window measurement before assuming the
balance survived."  The score's `t_out` is `{'mark': 'audio_end'}`, and
audio_end is derived from dialogue_end, which is derived from the LENGTH of
this line.  So replacing it re-lengthens the score's excerpt, and
`_music_segment` normalises the EXCERPT — a longer slice whose extra source is
quieter than the average gets the whole cue gained UP to still hit -37, which
lands the music the operator signed off louder than it was signed off at.  That
is exactly how -36 became -37 on the previous edit.

Rather than build, notice the drift and rebuild, this renders the LINE first,
derives the new audio_end from its measured duration, and computes the
correction analytically before the only build:

    gain applied by _music_segment = lufs - LUFS(compressed excerpt)
    hold the common portion still   =>  lufs_new = lufs_old + (raw_new - raw_old)

`raw_*` is measured on the excerpt AFTER the same acompressor the service runs
and BEFORE its loudnorm, because that is the signal the loudnorm actually sees
(cut -> compress -> loudnorm -> fades, in that order).

The scream cue is unaffected: this driver pins it to ABSOLUTE seconds
(0.0 -> 20.0), so it does not hang off a mark and its excerpt cannot move.

usage:  python3 run_scene_cornelis_wake.py
"""

import copy
import json
import logging as _zyg_logging
import os
import shutil
import subprocess
import sys

from zyg_workflows import paths
from zyg_workflows.bin import exe

CREWS = str(paths.ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
if os.path.isdir(CREWS):  # absent on a bare checkout (CI, a fresh clone)
    os.chdir(CREWS)

from zyg_workflows import storyteller_scene_service as sss  # noqa: E402
from zyg_workflows import scene_cornelis_day1 as cd1  # noqa: E402
from zyg_workflows import audio_mix  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)

ST = os.path.join(CREWS, 'output', 'storyteller')
SRC_DIR = os.path.join(ST, 'scene_cornelis_day1_screams20')  # the scream cut
BASE_DIR = os.path.join(ST, 'scene_cornelis_day1')  # the shipped cut
SLUG = 'cornelis_day1_wake'
OUT_DIR = os.path.join(ST, f'scene_{SLUG}')

NEW_LINE = 'Endless screams we leave in our wake.'
OLD_LINE = 'Yet the cost is more than I can bear.'
LINE_IDX = 3  # dialogue index; index 2 is {'beat': 5.8}

# SEED 99, not the scene's 1672 — and the reason is the KEY WORD.
# At 1672 this line renders, cleanly and with one speech island, as
# "Endless SCREENS we leave in our wake." Correct loudness, no clipping, no
# silence defect: nothing in the audio chain would have caught it, which is
# exactly what `_verify_line_text` exists for. /m/ and /n/ differ only in place
# of articulation, so one ASR reading cannot separate a bad RENDER from a bad
# HEARING — bench_wake_line.py settles it by re-rolling the sampler:
#
#   seed   dur   islands  transcript                          tail F0 (last 8 voiced)
#   1672   3.16     1     "Endless SCREENS we leave …"        78 78 78 73 70 67 66 65
#      7   2.92     1     exact                               62 66 68 70 72 71 71 70  RISES
#     99   3.08     1     exact                               81 61 62 61 60 59 64 61  falls
#    404   3.32     1     exact                               82 74 74 71 70 69 67 66  falls
#   2024   3.64     1     exact                               62 61 63 64 57 62 52 50  falls
#   1673   3.32     2     exact, but RESTATES itself
#   8814   4.00     1     exact
#
# 6 of 7 say it, so the synth can pronounce the word and 1672 is simply a bad
# roll. Picked by READING the contour, not by fitting it: a least-squares slope
# over seed 7's tail comes out flat/slightly falling and would have passed it,
# while the frames themselves climb 62 → 70 on the final syllable — a rising end
# reads as "another word is coming", and this line closes the cabin section.
# (The same disagreement between a fitted score and the actual contour picked
# the Abel closing line; see [[project-tts-take-direction]].)
# Among the falling takes 99 is the closest to the line it replaces on cadence
# (ends 24.4 Hz under its own median, against the shipped line's 22.3) and the
# shortest, so the timeline moves least. The seed re-rolls the SAMPLER only —
# identity still comes from the frozen cast clone, so this is the same voice.
LINE_SEED = 99
BENCH_TAKE = os.path.join('output', 'storyteller', '_bench_wake_line', f'wake_seed{LINE_SEED}.wav')

SCREAM_FILE = 'merge_2026_08_25_21_14_20_s.wav'
SCREAM_DUR = 20.0
SCREAM_FADE_OUT = 4.0

# Carried verbatim from the scream cut — everything except the line being replaced.
CARRY = (
    'still_cabin_cornelis.png',
    'still_cabin_cornelis.png.propedit',
    'still_cabin_cornelis.png.wlock_0015c8a3',
    'still_cabin_cornelis.hires.png',
    'still_cabin_cornelis.hires.png.handfix',
    'still_day1_chart.png',
    'still_day1_chart.hires.png',
    'anchor_00_cornelis.wav',
    'anchor_00_cornelis.wav.take',
    'anchor_00_cornelis.wav.tune',
    'line_00_cornelis.wav',
    'line_00_cornelis.wav.take',
    'line_00_cornelis.wav.tune',
    'line_01_cornelis.wav',
    'line_01_cornelis.wav.take',
    'line_01_cornelis.wav.tune',
)
UNCHANGED_TAKES = ('line_00_cornelis.wav', 'line_01_cornelis.wav', 'anchor_00_cornelis.wav')

_COMP_AF = 'acompressor=threshold=-26dB:ratio=4:attack=20:release=400:makeup=2'


def _md5(p):
    import hashlib

    with open(p, 'rb') as fh:
        return hashlib.md5(fh.read(), usedforsecurity=False).hexdigest()


def _dur(p):
    import soundfile as sf

    d, sr = sf.read(p, dtype='float64')
    return len(d) / sr


def _excerpt_lufs(src, start_s, dur_s, tag):
    """LUFS of the slice the service would hand its loudnorm: cut, then the
    SAME compressor, measured before any normalisation."""
    tmp = os.path.join(OUT_DIR, f'_lvlprobe_{tag}.wav')
    r = subprocess.run(
        [
            exe('ffmpeg'),
            '-loglevel',
            'error',
            '-y',
            '-ss',
            f'{start_s}',
            '-t',
            f'{dur_s}',
            '-i',
            src,
            '-af',
            _COMP_AF,
            '-ar',
            '48000',
            '-ac',
            '1',
            '-c:a',
            'pcm_s16le',
            tmp,
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        _zyg_log.info(f'[run] probe failed for {tag}: {r.stderr[:200]}')
        return None
    v = audio_mix.measure_lufs(tmp)
    os.remove(tmp)
    return v


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    n = 0
    for f in CARRY:
        s, d = os.path.join(SRC_DIR, f), os.path.join(OUT_DIR, f)
        if os.path.isfile(s) and not os.path.exists(d):
            shutil.copy2(s, d) if not os.path.islink(s) else os.symlink(os.readlink(s), d)
            n += 1
        elif not os.path.exists(s):
            print(f'[run] ABORT: {f} missing from {SRC_DIR}')
            return 2
    print(f'[run] carried {n} new / {len(CARRY)} files from the scream cut')
    # line_03 is deliberately NOT carried: new text must re-synthesise.
    for stale in (
        'line_03_cornelis.wav',
        'line_03_cornelis.wav.take',
        'line_03_cornelis.wav.tune',
        'line_03_cornelis_raw.wav',
        'line_03_cornelis_raw.wav.take',
    ):
        p = os.path.join(OUT_DIR, stale)
        if os.path.isfile(p):
            os.remove(p)

    spec = copy.deepcopy(cd1.CORNELIS_DAY1)
    spec['slug'] = SLUG

    ev = spec['dialogue'][LINE_IDX]
    if ev.get('text') != OLD_LINE:
        print(
            f'[run] ABORT: dialogue[{LINE_IDX}] is {ev.get("text")!r}, not the '
            f'line this driver was written against. The indices moved — check '
            f'whether a line or beat was added before assuming index {LINE_IDX}.'
        )
        return 2
    ev['text'] = NEW_LINE
    ev['seed'] = LINE_SEED
    print(f'[run] line {LINE_IDX}: {OLD_LINE!r}\n            -> {NEW_LINE!r} (seed {LINE_SEED})')

    # ── the scream swap, identical to run_scene_cornelis_screams20.py ────────
    cue = next(c for c in spec['music'] if c.get('name') == 'crowd_agony')
    cue['file'] = SCREAM_FILE
    cue['src_start_s'] = 0.0
    cue['t_out'] = SCREAM_DUR  # absolute: cannot move when the line does
    cue['fade_out_s'] = SCREAM_FADE_OUT

    # ── render the new line NOW, so its length is a measurement not a guess ──
    wav = os.path.join(OUT_DIR, f'line_{LINE_IDX:02d}_cornelis.wav')
    voice = dict(spec['voices'][ev['speaker']])
    for k in ('seed', 'exaggeration', 'cfg_weight', 'temperature', 'tempo', 'pace_ref'):
        if k in ev:
            voice[k] = ev[k]
    if not os.path.isfile(wav):
        # Carry the BENCHED take rather than re-rolling it, so the audio that
        # ships is bit-for-bit the audio that was transcribed and contour-scored.
        # Its marker was written by _synth_line with this same voice dict and
        # neither key depends on the path (no pace_ref here), so build_scene
        # accepts it as cached and does not re-synthesise.
        if os.path.isfile(BENCH_TAKE):
            shutil.copy2(BENCH_TAKE, wav)
            for ext in ('.take', '.tune'):
                if os.path.isfile(BENCH_TAKE + ext):
                    shutil.copy2(BENCH_TAKE + ext, wav + ext)
            print(f'[run] carried the benched seed-{LINE_SEED} take in')
        else:
            print(f'[run] benched take absent — synthesising seed {LINE_SEED} …')
            if not sss._synth_line(NEW_LINE, wav, voice, log_fn=print):
                print('[run] ABORT: TTS failed for the replacement line')
                return 1
    # The carried marker must match what build_scene will compute, or it re-rolls.
    want = f'{sss._tune_key(voice, wav)}|{sss._take_key(voice, NEW_LINE)}'
    got = open(wav + '.tune').read().strip() if os.path.isfile(wav + '.tune') else None
    if got != want:
        print(f'[run] ABORT: carried take marker will not be accepted\n       have {got}\n       want {want}')
        return 2
    print('[run] take marker verified — build_scene will reuse, not re-render')
    new_dur = _dur(wav)

    # ── derive the new timeline (every tail knob in this spec is static) ─────
    durs = [_dur(os.path.join(OUT_DIR, f'line_{i:02d}_cornelis.wav')) for i in (0, 1)]
    d_end = (
        float(spec['head_silence_s'])
        + durs[0]
        + float(spec['dialogue'][0]['pause_after_s'])
        + durs[1]
        + float(spec['dialogue'][1]['pause_after_s'])
        + float(spec['dialogue'][2]['beat'])
        + new_dur
        + float(ev['pause_after_s'])
    )
    tail_t0 = (
        d_end + float(spec['pullout']['hold_s']) + float(spec['fade_to_black_s']) + float(spec['title_card']['dur_s'])
    )
    total = tail_t0 + float(spec['tail_fade_in_s']) + float(spec['tail_hold_s'])
    audio_end = total + float(spec['end_fade_s']) + float(spec['audio_tail_s'])

    ref = json.load(open(os.path.join(SRC_DIR, 'scene_state.json')))
    old_end = ref['marks']['audio_end']
    print(
        f'[run] line {new_dur:.2f}s (was {ref["events"][2]["dur"]:.2f}s) '
        f'-> audio_end {audio_end:.2f}s (was {old_end:.2f}s), '
        f'{audio_end - old_end:+.2f}s'
    )

    # ── the level correction the module demands ─────────────────────────────
    score = next(c for c in spec['music'] if c.get('name') == 'ledger_weight')
    t_in = ref['music'][1]['t_in']  # 10.18 — unmoved, it hangs off event 1
    src = os.path.join(sss._MUSIC_DIR, ref['music'][1]['track'])
    s0 = float(score.get('src_start_s', 0.0))
    raw_old = _excerpt_lufs(src, s0, old_end - t_in, 'old')
    raw_new = _excerpt_lufs(src, s0, audio_end - t_in, 'new')
    authored = float(score['lufs'])
    if raw_old is None or raw_new is None:
        print('[run] WARN: could not probe the score excerpt — level left as authored')
    else:
        corr = raw_new - raw_old
        fixed = round(authored + corr, 2)
        print(
            f'[run] score excerpt {old_end - t_in:.2f}s -> {audio_end - t_in:.2f}s   '
            f'raw {raw_old:.2f} -> {raw_new:.2f} LUFS   drift {corr:+.2f} dB'
        )
        if abs(corr) < 0.05:
            print(f'[run] score level held at {authored} LUFS (drift below 0.05 dB)')
        else:
            score['lufs'] = fixed
            print(f'[run] score level {authored} -> {fixed} LUFS to hold the approved balance still')

    r = sss.build_scene(spec, out_dir=OUT_DIR)
    if not r:
        print('[run] FAILED')
        return 1
    print(f'[run] done: {r["video"]}')

    # ── verify ───────────────────────────────────────────────────────────────
    st = json.load(open(os.path.join(OUT_DIR, 'scene_state.json')))
    ok = True
    for f in UNCHANGED_TAKES:
        if _md5(os.path.join(OUT_DIR, f)) != _md5(os.path.join(SRC_DIR, f)):
            ok = False
            print(f'[verify] TAKE RE-RENDERED that should not have been: {f}')
    print(f'[verify] {len(UNCHANGED_TAKES)} untouched takes checksummed against the scream cut')

    texts = [e.get('text') for e in st['events'] if e.get('kind') == 'line']
    if NEW_LINE not in texts:
        ok = False
        print(f'[verify] NEW LINE NOT IN THE CUT — events say {texts}')
    if OLD_LINE in texts:
        ok = False
        print('[verify] OLD LINE STILL PRESENT')
    if ok:
        print(
            f'[verify] line replaced; dialogue_end {st["dialogue_end_s"]}s '
            f'(was {ref["dialogue_end_s"]}s), total {st["total_s"]}s '
            f'(was {ref["total_s"]}s)'
        )

    s = st['music'][0]
    if s['track'] != SCREAM_FILE or s['t_out'] != SCREAM_DUR:
        ok = False
        print(f'[verify] scream cue moved: {s}')
    else:
        print(f'[verify] scream {s["t_in"]}→{s["t_out"]}s @ {s["lufs"]} LUFS (unmoved — pinned to absolute seconds)')
    if st['music'][1]['t_in'] != ref['music'][1]['t_in']:
        ok = False
        print(f'[verify] SCORE ENTRY MOVED {ref["music"][1]["t_in"]} → {st["music"][1]["t_in"]}')
    else:
        print(f'[verify] score entry held at {st["music"][1]["t_in"]}s @ {st["music"][1]["lufs"]} LUFS')
    return 0 if ok else 4


if __name__ == '__main__':
    raise SystemExit(main())
