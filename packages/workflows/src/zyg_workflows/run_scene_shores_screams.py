#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Second Ledger cold-open — v15: the 20 s scream wall under the opening.

A COPY of the shipping v14 cut with exactly one addition: the 40-layer scream
merge built in the SFX merger on 2026-08-25 runs under the head of the scene.
Nothing else is allowed to move — same takes, same timeline, same levels — so
the only difference between the two files is the thing that was asked for.

WHY THIS FILE EXISTS IN THE REPO.  v4-v14 were driven by `run_v4.py`, which
lived only in a session scratchpad under /tmp.  That risk was flagged when it
was written and it duly came true: /tmp has since been cleared and the driver
for the SHIPPING cut was gone.  It was recovered by replaying its Write+Edit
history out of the session archive, and its numbers were then re-derived from
the delivered v14 files rather than trusted:

    _master_work.wav      -14.0 LUFS   -> MASTER_LUFS
    voice_sfx_stem_n.wav  -23.0 LUFS   -> STEM_LUFS
    bed_n.wav             -51.8 LUFS   -> BED_LUFS  (-51.9 authored)
    scene_state.json      suspense -35.9 / nuanced -37.2, master_fade_s 2.0,
                          audio_tail_s 0.0, end_fade 3.0

The version TABLES are gone with it — this driver hardcodes v14's numbers
instead, because a `_MUSIC.get(VERSION, _MUSIC['v5'])` fallback is how an
unregistered version silently ships a 7 dB-wrong mix.

The rendered TAKES are not re-synthesised: the TTS cache is per-output-dir, so
the approved wavs + their `.tune`/`.take` markers are carried across first and
build_scene reuses them.  That also makes the timeline reproduce exactly, since
every mark is derived from the audio's own length.

usage:  python3 run_scene_shores_screams.py
"""

import copy
import json
import logging as _zyg_logging
import os
import shutil
import sys

import soundfile as sf

from zyg_workflows import paths

CREWS = str(paths.ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
os.chdir(CREWS)

from zyg_workflows import storyteller_scene_service as sss  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)

ST = os.path.join(CREWS, 'output', 'storyteller')
SRC_DIR = os.path.join(ST, 'scene_second_ledger_intro_teen08_settled_shores_v14')
SLUG = 'second_ledger_intro_teen08_settled_shores_v15_screams'
OUT_DIR = os.path.join(ST, f'scene_{SLUG}')
SEED_WAV = os.path.join(CREWS, 'data', 'assets', 'voice_seeds', 'teens', 'teen08.wav')

SHORES = 'It started where every sea voyage begins, at the shores of civilization.'
CLOSING_SEED = 2024
# "It is likely we will not return." — the sad take, picked by F0 contour.
LINE3 = {'seed': 2024, 'exaggeration': 0.30, 'cfg_weight': 0.40}

# ── v14's levels, measured off the delivered files (see docstring) ───────────
STEM_LUFS = -23.0
MASTER_LUFS = -14.0
BED_LUFS = -51.9
MUSIC_LUFS = {'suspense': -35.9, 'nuanced': -37.2}

FADE_LEAD_S = 0.0  # v14: the fade starts AS he finishes, not before
END_FADE_S = 3.0  # picture fade length; picture_end = fade_start + this
MASTER_FADE_S = 2.0  # sound fades over this, landing with the picture

# ── the addition ─────────────────────────────────────────────────────────────
# `merge_2026_08_25_21_14_20_s.wav` — 40 screams staggered 0.0-19.3 s across the
# stereo field, pitched and room-treated in the SFX merger.  Licence-clean by
# derivation (every source is royalty-free-verified; `transform: dsp`, never
# model input).
#
# It is authored as a MUSIC cue, not a bed layer, for the reason the module
# gives: bed and cues are levelled separately but pass through the SAME
# sidechain duck, and a cue can be anchored to marks/events and given a shape.
# Same mechanism the Cornelis Day 1 opening uses for its crowd_agony bed.
#
# The shape, in order: out of the black over 2.5 s, full for the half second
# that carries into Abel's first word, then a 2.5 s recession to a murmur it
# holds for the rest of the run, and out over the four seconds before the score
# arrives.  A fade and a fade alone cannot author that middle — hence `settle`.
#
# -8 dB, not the Cornelis opening's -12: that scene had the screams alone in the
# head, this one has the water running under them at -51.9, so a -12 settle
# would put the murmur ~4 dB UNDER the bed and it would simply be gone.  -8
# lands it level with the water, i.e. part of the same distant weather.
#
# t_out is 20.0 because the source is exactly 20.0 s.  Do not extend it: the
# cue would then LOOP, and a one-shot wall spliced back onto its own head is
# the defect [[project-agony-bed-clap]] is about.
SCREAM_CUE = {
    'name': 'crowd_agony',
    'file': 'merge_2026_08_25_21_14_20_s.wav',
    't_in': 0.0,
    't_out': 20.0,
    'src_start_s': 0.0,
    'fade_in_s': 2.5,
    'settle': {'hold_s': 0.5, 'over_s': 2.5, 'db': -8.0},
    'fade_out_s': 4.0,
    # 21 LU under the voice stem, before the duck takes another ~7 dB out of it
    # under speech.  Felt, not heard — the same discipline the bed is held to.
    # The DELIVERED distance is not the authored one (the master gain-up moves
    # it), so verify against a speech window: [[project-scene-audio-levels]].
    'lufs': -44.0,
}

STILLS = (
    'still_cabin_abel.png',
    'still_cabin_abel.png.wlock_c3345deb',
    'still_cabin_abel.hires.png',
    'still_cabin_abel.hires.png.handfix',
    'still_day1_harbor.png',
    'still_day1_harbor.hires.png',
)
TAKES = tuple(f'line_{i:02d}_abel{s}' for i in range(4) for s in ('.wav', '.wav.tune', '_raw.wav', '_raw.wav.take')) + (
    'anchor_00_abel.wav',
    'anchor_00_abel.wav.tune',
)


_AUDIO_TAKES = tuple(f'line_{i:02d}_abel.wav' for i in range(4)) + ('anchor_00_abel.wav',)


def _md5(p):
    import hashlib

    with open(p, 'rb') as fh:
        return hashlib.md5(fh.read(), usedforsecurity=False).hexdigest()


def _cp(s, d):
    if os.path.isfile(s) and not os.path.isfile(d):
        shutil.copyfile(s, d)
        return 1
    return 0


def _carry(names, label):
    n = sum(_cp(os.path.join(SRC_DIR, f), os.path.join(OUT_DIR, f)) for f in names)
    _zyg_log.info(f'[run] carried {n} new / {len(names)} {label}')


def _restamp(spec):
    """Re-write the carried `.tune`/`.take` markers in the CURRENT key format.

    v14's markers were written before `_take_key` learned to include the voice
    REF — the fix for the worst of the three cache holes, where recasting a
    character left every cached clone in place.  Every marker from before that
    change therefore reads stale to today's service, and build_scene answers a
    stale marker the only way it can: by re-synthesising the line.

    That is correct behaviour and a disaster here.  v14's line 0 is a tempo
    SPLICE (only the number was slowed), line 3 is a take picked off an F0
    contour bench, and the closing line is another — none of them is a plain
    render of the spec, so "re-synthesise" means "silently ship different
    audio, and lose the takes that were approved".

    What is migrated is the KEY FORMAT, not the settings.  The ref is the same
    frozen seed at the same path, size and mtime; the seed, exaggeration,
    cfg_weight, temperature and text are the same values v14 rendered with.
    So the marker written here states exactly what the audio beside it was
    rendered with — which is the whole contract a marker has.  The wavs are
    checksummed against v14 after the build to prove nothing was re-rendered.
    """
    voices = spec['voices']
    jobs = [(f'line_{i:02d}_abel.wav', dict(spec['dialogue'][i])) for i in range(4)]
    jobs.append(('anchor_00_abel.wav', dict(spec['anchored_lines'][0])))
    n = 0
    for fname, ev in jobs:
        wav = os.path.join(OUT_DIR, fname)
        v = dict(voices[ev['speaker']])
        for k in ('seed', 'exaggeration', 'cfg_weight', 'temperature', 'tempo', 'pace_ref'):
            if k in ev:
                v[k] = ev[k]
        take = sss._take_key(v, ev['text'])
        want = f'{sss._tune_key(v, wav)}|{take}'
        got = None
        if os.path.isfile(wav + '.tune'):
            with open(wav + '.tune') as fh:
                got = fh.read().strip()
        if got == want:
            continue
        with open(wav + '.tune', 'w') as fh:
            fh.write(want)
        raw = wav.replace('.wav', '_raw.wav')
        if os.path.isfile(raw):
            with open(raw + '.take', 'w') as fh:
                fh.write(take)
        n += 1
        _zyg_log.info(f'[run] restamped {fname}: {got or "unmarked"} → {want}')
    _zyg_log.info(f'[run] {n} marker(s) migrated to the current key format')


def _dur(p):
    d, sr = sf.read(p, dtype='float64')
    return len(d) / sr


def _span(p):
    """What build_scene ships for a take='span' anchored line, measured through
    the same calls it uses — the island detector does not scale with sample
    rate, so reading the file natively gives a different answer."""
    d = sss._read_mono48k(p)
    a, b = sss._pick_island(d, sss._speech_islands(d), 'span')
    return (b - a) / 48000.0


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    _carry(STILLS, 'stills')
    _carry(TAKES, 'approved takes')

    anchor = os.path.join(OUT_DIR, 'anchor_00_abel.wav')
    for f in ('line_00_abel.wav', 'line_01_abel.wav', 'line_02_abel.wav', 'line_03_abel.wav', 'anchor_00_abel.wav'):
        if not os.path.isfile(os.path.join(OUT_DIR, f)):
            print(
                f'[run] ABORT: missing carried take {f} — v14 is the source '
                f'of truth for this cut and it must not be re-synthesised'
            )
            return 2

    # ── timeline: derived from the audio, exactly as v14 derived it ──────────
    durs = [_dur(os.path.join(OUT_DIR, f'line_{i:02d}_abel.wav')) for i in range(4)]
    pauses = [1.0, 1.0, 0.9, 0.6]
    spec = copy.deepcopy(sss.SECOND_LEDGER_INTRO)

    dialogue_end = float(spec.get('head_silence_s', 1.0)) + sum(d + p for d, p in zip(durs, pauses))
    pullout_end = dialogue_end + float(spec['pullout']['hold_s'])
    card_start = pullout_end + float(spec['fade_to_black_s'])
    tail_t0 = card_start + float(spec['title_card']['dur_s'])
    close_t0 = card_start + float(spec['anchored_lines'][0]['at']['offset'])
    close_t1 = close_t0 + _span(anchor)

    fade_start = close_t1 - FADE_LEAD_S  # == marks['total']
    picture_end = fade_start + END_FADE_S
    spec['audio_tail_s'] = 0.0
    spec['master_fade_s'] = MASTER_FADE_S

    tail_in_hold = fade_start - tail_t0  # fade-in + hold, before the fade
    if tail_in_hold < 0.4:
        print(f'[run] ABORT: only {tail_in_hold:.2f}s between the harbour appearing and the fade starting')
        return 3
    spec['tail_fade_in_s'] = round(min(1.1, tail_in_hold * 0.6), 3)
    spec['tail_hold_s'] = round(tail_in_hold - spec['tail_fade_in_s'], 3)
    spec['end_fade_s'] = round(picture_end - fade_start, 3)

    # ── spec ─────────────────────────────────────────────────────────────────
    spec['slug'] = SLUG
    spec['voices']['abel'] = {'ref': SEED_WAV, 'seed': 1672}
    spec['stem_lufs'] = STEM_LUFS
    spec['master_lufs'] = MASTER_LUFS
    spec['bed_lufs'] = BED_LUFS
    for cue in spec['music']:
        if cue.get('name') in MUSIC_LUFS:
            cue['lufs'] = MUSIC_LUFS[cue['name']]

    spec['dialogue'][3].update(LINE3)
    anch = dict(spec['anchored_lines'][0])
    anch.update({'text': SHORES, 'take': 'span', 'pace_ref': None, 'seed': CLOSING_SEED})
    spec['anchored_lines'] = [anch]

    # The last cue's own fade_out_s would MULTIPLY with the 2.0 s master fade.
    # Take it FIRST, while 'nuanced' is still spec['music'][-1] — the scream is
    # inserted at the head below and would otherwise not be the cue this means.
    spec['music'][-1]['fade_out_s'] = 0.3

    # ── the scream, and the one thing it breaks if left alone ────────────────
    # `bed_fade_out` defaults its anchor to the EARLIEST music cue.  A cue that
    # enters at 0.0 would therefore drag the water's hand-over to the score back
    # to the top of the scene and the bed would fade out before it faded in.
    # Pin it to the cue it has always meant: 'suspense', 0.3 s before line 3.
    spec['bed_fade_out'] = {'fade_s': 6.5, 'lead_s': -0.6, 'at': {'event': 3, 'at': 'start', 'offset': -0.3}}
    spec['music'].insert(0, dict(SCREAM_CUE))

    print(
        f'[run] closing line {close_t0:.2f}→{close_t1:.2f}s   '
        f'harbour in at {tail_t0:.2f}s   fade {fade_start:.2f}→{picture_end:.2f}s'
    )
    print(
        f'[run] tail_fade_in {spec["tail_fade_in_s"]}s  '
        f'tail_hold {spec["tail_hold_s"]}s  end_fade {spec["end_fade_s"]}s'
    )
    print(
        f'[run] scream cue {SCREAM_CUE["t_in"]}→{SCREAM_CUE["t_out"]}s @ '
        f'{SCREAM_CUE["lufs"]} LUFS, settles {SCREAM_CUE["settle"]["db"]:+g} dB'
    )

    # Must run with the spec FULLY built (voices, line-3 sampler override and
    # the anchored line all set), because those are what the keys hash.
    _restamp(spec)
    before = {f: _md5(os.path.join(OUT_DIR, f)) for f in _AUDIO_TAKES}

    r = sss.build_scene(spec, out_dir=OUT_DIR)
    if not r:
        print('[run] FAILED')
        return 1
    print(f'[run] done: {r["video"]}')

    # ── verify against v14, which is the thing this is a copy of ─────────────
    st = json.load(open(os.path.join(OUT_DIR, 'scene_state.json')))
    ref = json.load(open(os.path.join(SRC_DIR, 'scene_state.json')))
    ok = True
    # The takes are the approved ones or this is not a copy of v14. Checked
    # against BOTH the pre-build state and v14 itself, so neither a re-render
    # nor a bad carry can pass.
    for f in _AUDIO_TAKES:
        now = _md5(os.path.join(OUT_DIR, f))
        v14 = _md5(os.path.join(SRC_DIR, f))
        if now != before[f] or now != v14:
            ok = False
            print(f'[verify] TAKE RE-RENDERED: {f} (v14 {v14[:8]}, before {before[f][:8]}, after {now[:8]})')
    print(f'[verify] {len(_AUDIO_TAKES)} takes checksummed against v14')
    if st['marks'] != ref['marks']:
        ok = False
        print(f'[verify] MARKS MOVED\n  v14 {ref["marks"]}\n  new {st["marks"]}')
    else:
        print(f'[verify] marks identical to v14 (total {st["marks"]["end"]}s)')
    for a, b in zip(st['events'], ref['events']):
        if round(a['t0'], 2) != round(b['t0'], 2) or round(a['t1'], 2) != round(b['t1'], 2):
            ok = False
            print(
                f'[verify] LINE MOVED {b["text"][:40]!r} {b["t0"]:.2f}→{b["t1"]:.2f} became {a["t0"]:.2f}→{a["t1"]:.2f}'
            )
    names = [c['name'] for c in st['music']]
    if names[0] != 'crowd_agony':
        ok = False
        print(f'[verify] scream cue MISSING from the mix — cues are {names}')
    if st['bed_fade_out_s'] != ref['bed_fade_out_s']:
        ok = False
        print(
            f'[verify] bed hand-over moved {ref["bed_fade_out_s"]} → '
            f'{st["bed_fade_out_s"]} (the earliest-cue anchor trap)'
        )
    for a, b in zip(st['music'][1:], ref['music']):
        if a['t_in'] != b['t_in'] or a['t_out'] != b['t_out'] or a['lufs'] != b['lufs']:
            ok = False
            print(f'[verify] SCORE CUE MOVED {b["name"]}: {b} → {a}')
    return 0 if ok else 4


if __name__ == '__main__':
    raise SystemExit(main())
