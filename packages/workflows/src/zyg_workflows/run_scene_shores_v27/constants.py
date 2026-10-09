# ruff: noqa: F401  (this module inherits the original top import block)
#!/usr/bin/env python3


# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Second Ledger cold-open — v27: v26 claimed to fix "flies backwards near the
boat" and measured a bank-vs-turn correlation of +0.44 to prove it. The
operator watched v26 and reported the SAME symptom, unchanged — leaning right
approaching the boat. Both things are true: the correlation fix was real (a
fine 20Hz sweep of `pose['head']` across the whole v26 flight finds zero
mirror-sign flips), and the bird still visibly locks into a static right-lean
for over a second right at the ship pass. The bug survived its own
verification because the verification and the symptom are answering different
questions.

Measured directly against the delivered v26 file's own model (no rendering
needed, just calling `_bird_bank_table` on `bird_cfg3d_v26.json`): bank hits
its configured ceiling, `bank_max_deg=48`, and sits there — bit-identical,
-48.00 exactly — for 21 straight samples at 20Hz, 1.10 continuous seconds,
t_rel=3.30s to 4.40s, dead center on the ship pass at 3.67s. `bank_gain=3.1`
against this path's own natural (ungained) peak curvature of -31.45deg sends
the gained signal to -97degrees at its worst — nearly 100 degrees past
physical, clamped down to the 48deg ceiling for over a full second, not
clipped for an instant.

v26's own bank check (still here, `_bird_flies_away`) computes `at_lim`, the
FRACTION OF THE WHOLE 11s FLIGHT sitting at the clamp, and fails past 20%.
This defect measures 10.0% — a real number, correctly computed, and it says
nothing is wrong, because a fraction-of-flight-total statistic cannot tell
the difference between ten independent 0.1s clip instants scattered across
the flight (cosmetically harmless) and one continuous 1.1s freeze sitting
exactly on the story's one required beat (the boat pass) — same aggregate,
opposite defect. Fixed by adding a SECOND check next to it: the longest
CONTIGUOUS run of samples at the clamp, in seconds, not a share of the whole
flight — v26 scores 1.10s there against a 0.15s floor; v27, retuned, scores
0.00s. `bank_gain` 3.1 -> 1.3 is the actual fix: the model's own natural peak
(-31.45deg, unaffected by gain) times 1.3 lands at -40.8deg, 7 degrees of
headroom under the 48deg ceiling for the whole flight, so the ceiling goes
back to being a safety limit that is never actually hit rather than the
thing drawing the curve.

Also fixed, in the shared service (`storyteller_scene_service.py`), a real
but separate bug found while tracing this: `_bird_fly3d`'s `head` and
`_bird_bank_table`'s `th` both took `atan2` of screen coordinates that had
already been divided by plate width and height SEPARATELY (`x/W`, `y/H`)
before the angle was computed — correct only if W==H. This plate is
2688x1536, 1.75:1, so every tangent angle taken that way was stretched by
`tan(computed) = tan(true) * (W/H)`, up to ~15deg of error depending on
local heading. Checked directly: this does not explain the lean (it cannot
flip a sign, since dividing by a positive W or H before `atan2` never
changes which quadrant `(dx, dy)` falls in — confirmed empirically too, zero
mirror flips in either version) but it was a real, measurable angular error
riding along on every direction computed off the screen projection, now
fixed by scaling back to real pixel units (`tx*W, ty*H`) before the angle is
taken.

And, per the operator's direct instruction, BEFORE any of the above was
verified against the delivered picture rather than the model alone: the bird
was too small to check by eye AT ALL. `body_frac` 0.018 -> 0.15 (~8.3x): at
the ship pass the delivered sprite went from 3.75 REAL PIXELS (measured,
not estimated — a canary sprite whose native art is 429-977px was being
downsampled to single digits) to a size a human or a vision model can
actually look at and answer "which way is the lean" without guessing. This
is not a debug-only knob — it is the actual `body_frac` this shot renders
with now, because a defect nobody can see is a defect nobody can fix, and
that was true of the operator, of the model checking its own numbers, and
it would have been true of the same check being asked of an LLM.

--- v26's own header follows, unedited, for the fixes still in effect ---

Second Ledger cold-open — v26: the operator watched v25 and reported three
concrete, specific notes, all still open after v25's fix — v25 closed "the
bird can't turn, only roll" (a real bug), but three separate things were
still wrong underneath it: the curve itself was too short/too late, the wings
never stop flapping, and the bird still visibly flies backwards/sideways for
an instant near the boat. All three are fixed here, and the third turned out
to be the SAME underlying defect class as v25's own fix, one layer deeper.

1. "the curve is too short... make sure the curve goes from the right corner
   where the bird enters all the way up to the boat, then it should curve to
   the left out of the screen." Measured directly off v25's own path (all
   25 `path3d` points projected through the shot's camera): screen X moves
   smoothly and monotonically the whole flight (that part was genuinely
   fine), but screen Y does almost all of its bending in the FIRST ~1s near
   the entry, then sits nearly flat (0.402-0.438, a 0.04 range) for the
   entire 13-point swing-away segment (v23/v24's hand-authored exit Bezier)
   — visually a short dip-then-climb followed by a long near-straight
   diagonal exit, not one continuous bend. Rebuilt `path3d` from scratch as
   ONE curve, authored the way v23/v24 authored only the exit — as two
   screen-space quadratic Beziers (entry->ship, ship->exit) sharing a single
   tangent DIRECTION through the ship waypoint, so there is no seam between
   "approach" and "swing-away" the way v20-v24's stitched-together path
   always had one. Inverse-projected back through the same camera at the
   ORIGINAL, previously-measured-correct depth (Z) schedule (entry 4.2m,
   ship 27m, exit 46m unchanged) — only the screen-space SHAPE changed, not
   the recession/size, which was never the complaint.

2. "it only has to flap its wings 2-3 times in the entire duration... once
   during the curved flight towards the boat... when it reaches the boat it
   changes direction by adjusting its wings [no flap]... when it's finished
   turning, flap once more... then it smoothly leaves the screen." The old
   `_bird_wing` cycles `bound_period_s`/`flap_frac`/`beats` on a repeating
   `t_rel mod bound_period_s` clock for the WHOLE flight — ~18 beats over
   11s, no way to script when a burst happens. New, additive mode
   `flap_events_s`: an authored list of `{t0, beats}` bursts; every cfg
   before this one leaves it unset and renders bit-identical. Scripted here
   to exactly the brief: one 2-beat burst at t=1.1s (during the approach,
   well clear of the ship pass at t=3.67s and the turn that follows it), a
   second 2-beat burst at t=5.6s (after the turn's bank has eased back to
   its steady glide level — measured, not guessed, see below), gliding
   everywhere else including the entire turn itself, where only bank moves.

3. "when it approaches the boat, it flies to the left backwards for a second,
   then it reverts and flies with his head angled to the left correctly...
   if you make a 3D line... and attach the nose of the bird to the line...
   it can never angle itself wrong." That is exactly right, and pointed at
   the real bug: `_draw_bird_sprite` decided which way to MIRROR the side
   sprite off the SIGN of `yaw` — a world-space heading table
   (`_bird_bank_table`'s own `th`, `atan2(dX,dZ)`) built independently of
   the screen projection that actually places the bird. `_bird_fly3d`
   already computes a screen-space secant tangent every frame (`pose
   ['head']`) and never used it for this. The two signals usually agree, but
   nothing forces them to, and where they briefly disagree the sprite flips
   against its own visible direction of travel — the bird looks like it
   flies backwards for an instant even though the plotted trajectory never
   reversed. Same root defect, it turns out, as `_bird_bank_table`'s ROLL
   sign, which used the same world-space `th` to decide which way to bank:
   measured directly against this shot's new path, that scored bank-vs-
   apparent-turn correlation **-0.38 — banking the WRONG way**, not just
   weakly. Fixed both the same way, in the shared service: mirror is now
   decided by `cos(pose['head'])` (the screen tangent itself, so it cannot
   disagree with where the bird is actually going), and `_bird_bank_table`'s
   roll sign now comes from the PROJECTED screen heading instead of the
   world-plane one. Re-measured after the fix: correlation +0.44, bank
   single-signed for the entire flight (zero sign changes), which the old
   two-stitched-Bezier path could not have given even with the sign fixed —
   its own tangent discontinuity at the ship joint (see point 1) is what
   produced the wrong-signed spike in the first place.

`bird_cfg3d_v26.json` is a full re-author of `path3d` (see point 1) plus the
new `flap_events_s` (point 2); `bank_gain`/`bank_raw_cap_deg`/`bank_max_deg`/
`bank_entry_settle_frac` are re-swept for the new path, not carried over
unchanged, since v22's own header already established that old bank numbers
do not transfer across a path change. `water_poly.json` is still v22's.

usage:  python3 run_scene_shores_v27.py [--verify-only]
"""

import copy
import json
import logging as _zyg_logging
import math
import os
import shutil
import subprocess
import sys

import soundfile as sf

from zyg_workflows import paths
from zyg_workflows.bin import exe

CREWS = str(paths.ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
if os.path.isdir(CREWS):  # the scene script runs from the crews root; importing it elsewhere (CI) must not fail
    os.chdir(CREWS)

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from zyg_workflows import storyteller_scene_service as sss  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)

NO_BIRD = '--no-bird' in sys.argv
BLUE_WATER = '--blue-water' in sys.argv

ST = os.path.join(CREWS, 'output', 'storyteller')
SRC_DIR = os.path.join(ST, 'scene_second_ledger_intro_teen08_settled_shores_v20_quay')
SRC_MP4 = os.path.join(SRC_DIR, 'second_ledger_intro_teen08_settled_shores_v20_quay.mp4')
SLUG = 'second_ledger_intro_teen08_settled_shores_v27_leanfix'
if NO_BIRD:
    SLUG += '_nobird'
if BLUE_WATER:
    SLUG += '_bluewater'
OUT_DIR = os.path.join(ST, f'scene_{SLUG}')
SEED_WAV = os.path.join(CREWS, 'data', 'assets', 'voice_seeds', 'teens', 'teen08.wav')
SCENE_CFG = os.path.join(CREWS, 'data', 'assets', 'scenes', 'second_ledger_shores')
if BLUE_WATER:
    # A masked luminance->duotone recolor of v20's plate (see
    # scratchpad/recolor_water.py), not a Qwen re-edit — the water polygon
    # mask already exists for the ripple FX, so this stays scoped to the
    # water pixels only and can't drift the ship/quay/sky the way a
    # whole-image AI edit risked (see prior harbor-plate rebuild history).
    NEW_PLATE = os.path.join(SCENE_CFG, 'bluewater', 'still_day1_harbor.bluewater.png')
    NEW_HIRES = os.path.join(SCENE_CFG, 'bluewater', 'still_day1_harbor.hires.bluewater.png')
else:
    NEW_PLATE = os.path.join(SRC_DIR, 'still_day1_harbor.png')
    NEW_HIRES = os.path.join(SRC_DIR, 'still_day1_harbor.hires.png')
BIRD_CFG = os.path.join(SCENE_CFG, 'bird_cfg3d_v27.json')
WATER_POLY = os.path.join(SCENE_CFG, 'water_poly.json')
SPRITE_DIR = os.path.join(CREWS, 'data', 'assets', 'bird_sprites', 'canary')

SHORES = 'It started where every sea voyage begins, at the shores of civilization.'
CLOSING_SEED = 2024
LINE3 = {'seed': 2024, 'exaggeration': 0.30, 'cfg_weight': 0.40}

STEM_LUFS = -23.0
MASTER_LUFS = -14.0
BED_LUFS = -51.9
MUSIC_LUFS = {'suspense': -35.9, 'nuanced': -37.2}

# ── the tail, all of it v19's except BIRD_DUR ──────────────────────────────
BIRD_IN = 2.0
BIRD_DUR = 11.0
BEAT_S = 0.2
# --no-bird only: shortens the silent wait between the title card and Abel's
# closing line by this much (operator's ask, once the bird itself was gone
# there was no reason to hold the shot empty for the bird's old flight time).
# 3.0 initially, then a further 5.0 cut on the same gap -> 8.0 total.
TAIL_TRIM_S = 8.0
TAIL_FADE_IN_S = 1.1
# 3.0 -> 2.0 (operator: "1 second shorter at the end"). audio_tail_s is 0 in
# this driver, so audio_end == picture_end == total + END_FADE_S exactly —
# this is the only knob that shortens the delivered file's total runtime;
# tail_zoom_overshoot_s only reshapes the camera's interpolation curve up to
# picture_end, it never adds rendered frames past it (see build_scene's own
# `tail_win_t1` comment). Nothing else in the timeline (dialogue, pullout,
# the closing line's placement) depends on END_FADE_S.
END_FADE_S = 2.0
MASTER_FADE_S = 2.0
OVERSHOOT_S = 2.0

# Where the moored ship is, in plate fractions. No longer where the flight has
# to END (see the module header) — this is now the CLOSEST APPROACH target:
# the bird has to visibly pass the boat before it banks away.
SHIP_AT = (0.628, 0.470)
SHIP_TOL = 0.075

STILLS_CARRY = (
    'still_cabin_abel.png',
    'still_cabin_abel.png.wlock_c3345deb',
    'still_cabin_abel.hires.png',
    'still_cabin_abel.hires.png.handfix',
)
TAKES = tuple(f'line_{i:02d}_abel{s}' for i in range(4) for s in ('.wav', '.wav.tune', '_raw.wav', '_raw.wav.take')) + (
    'anchor_00_abel.wav',
    'anchor_00_abel.wav.tune',
)
_AUDIO_TAKES = tuple(f'line_{i:02d}_abel.wav' for i in range(4)) + ('anchor_00_abel.wav',)

# FIVE boxes, and the floor is their MEDIAN — see v22's header for why max
# hands the check to whichever box the encoder happened to be noisiest in.
_STATIC_REGIONS = {
    'right gable': (1170, 40, 1330, 200),
    'left roofline': (200, 195, 420, 300),
    'left houses': (60, 330, 260, 470),
    'right brick': (1180, 230, 1330, 420),
    'left gables': (250, 300, 430, 430),
}


def _canary_px(a: np.ndarray) -> int:
    """The bird's colour in the DELIVERED file, after the grade. See v22's
    header — the blue deficit survives the grade, the plate-space g>=r test
    does not."""
    g, b = a[..., 1], a[..., 2]
    return int(((g - b > 90) & (g > 120)).sum())


def _md5(p):
    import hashlib

    with open(p, 'rb') as fh:
        return hashlib.md5(fh.read(), usedforsecurity=False).hexdigest()


def _cp(s, d, force=False):
    if os.path.isfile(s) and (force or not os.path.isfile(d)):
        shutil.copyfile(s, d)
        return 1
    return 0


def _carry(names, label):
    n = sum(_cp(os.path.join(SRC_DIR, f), os.path.join(OUT_DIR, f)) for f in names)
    _zyg_log.info(f'[run] carried {n} new / {len(names)} {label}')


def _restamp(spec):
    """Re-write the carried markers in the CURRENT key format, so build_scene
    does not answer a stale marker by re-synthesising a picked take."""
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
        _zyg_log.info(f'[run] restamped {fname}')
    _zyg_log.info(f'[run] {n} marker(s) migrated to the current key format')


def _dur(p):
    d, sr = sf.read(p, dtype='float64')
    return len(d) / sr


def _span(p):
    d = sss._read_mono48k(p)
    a, b = sss._pick_island(d, sss._speech_islands(d), 'span')
    return (b - a) / 48000.0


def _grab(video, t, dst):
    subprocess.run(
        [exe('ffmpeg'), '-loglevel', 'error', '-y', '-ss', str(t), '-i', video, '-frames:v', '1', dst], check=True
    )
    return np.asarray(Image.open(dst).convert('RGB'), dtype=np.float32)


def _seq(video, t0, dur, tmp, tag):
    subprocess.run(
        [
            exe('ffmpeg'),
            '-loglevel',
            'error',
            '-y',
            '-ss',
            str(t0),
            '-t',
            str(dur),
            '-i',
            video,
            '-vf',
            'fps=24',
            os.path.join(tmp, f'{tag}_%03d.png'),
        ],
        check=True,
    )
    fs = sorted(f for f in os.listdir(tmp) if f.startswith(tag + '_'))
    return [np.asarray(Image.open(os.path.join(tmp, f)).convert('L'), dtype=np.float32) for f in fs]
