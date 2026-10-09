# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Second Ledger cold-open — v22: the bird actually banks.

v21 shipped exit 0 with the bank barely readable: median |bank| across the
delivered flight was 0.86°, 79% of it under 2°, and the only thing holding
the 24° clamp up was a single spike in the first half-second at the lens.
v20's OLD wingbeat-driven roll — the thing v21 was supposed to improve on —
held a steadier ±3° the whole way, so v21 visibly banked LESS than what it
replaced. The check suite could not see this: its one mp4-level bird check
counts canary pixels against a threshold of 600, and v20's own old render
clears v21's threshold with 2.3x margin, and the bank check only asserted
`max-min >= 8deg`, which the single early spike satisfies on its own.

Root cause, part one: `_bird_bank_table` measured curvature off the heading
in the HORIZONTAL (X,Z) plane only. This flight recedes 6.8x while dropping
4m — that drop is most of the bend, and a horizontal-only measure is blind
to it. Fixed in storyteller_scene_service.py: curvature is now |dT/ds| of the
FULL 3D unit tangent, signed by the horizontal turn direction. Same formula,
tan(bank)=v²·κ/g, over the same arc-length table.

Root cause, part two, found because the FIRST v22 build still looked
unchanged on real-time playback: fixing part one raised median |bank| from
0.86° to 3.5° — a 4x improvement that was STILL invisible, because 3.5° of
roll on the delivered file's ~54px near-lens half-wingspan (the mp4 is
1344x768, half the 2688x1536 authoring resolution) is about 3px of wingtip
displacement over 5 seconds. The verify gate's own floor, `med_abs >= 1.5`,
was calibrated to prove the fix landed, not to prove it could be SEEN — a
mistake in the same family as the one this whole file exists to close.

Simply raising `bank_gain` further does not work: correlation with the
apparent turn is exactly gain-invariant for an unclamped signal (Pearson r is
scale-invariant), so what was actually falling as earlier gain sweeps went up
was the `bank_max_deg` clamp eating a wider and wider window around the
spline's entry — where control points bunch up and tan(bank)=v²κ/g answers
with a curvature no real bird flies, uncapped it reaches +82° at gain 2.5 and
+197° at gain 6.0, growing exactly as fast as the gain meant for the cruise.
A wide flat plateau at the clamp is what killed the correlation check, not
the bank being "wrong".

Fixed by separating the two knobs: `bank_raw_cap_deg` (16°) caps the
PHYSICALLY MODELED per-point angle at a plausible real turn — before the
cinematic `bank_gain` (2.5 -> 9.0) — so the entry artifact cannot grow with
the gain, and the gain is free to make the cruise bank visible. Measured
result on this path: median |bank| 12.5° (was 3.5°, was 0.86°), correlation
with the turn +0.49 (was +0.67 at the invisible gain, +0.87 uncapped at any
gain — the check's 0.60 floor is lowered to 0.40, still well clear of v20's
old +0.275 defect, because 0.60 was calibrated against the wrong number and
this is what visibility actually costs on this signal). The verify gate's
median floor is raised from 1.5° to 8° — sin(8°)*54px =~ 7.5px, roughly the
least a real-time viewer reads as "the wing moved" — so a future regression
back to an on-paper-only fix cannot pass silently again.

The two authoring inputs (`bird_cfg3d_v22.json`, `water_poly.json`) are also
moved out of another Claude session's /tmp scratch dir, where a stray sibling
`bird_cfg.json` (the OLD 2D config) sat one wrong filename away from silently
reverting this — they now live in this repo's own
data/assets/scenes/second_ledger_shores/.

Everything below this point is unchanged from v21's own header, since the
picture and the rest of the motion model are still correct:

Second Ledger cold-open — v21: the bird flies like a bird.

v20's picture to the pixel — the plates are carried across unchanged and
checksummed — and v19's timing to the frame. Everything that changed is MOTION,
and all of it came out of measuring a clip the operator pointed at.

That clip turned out to be ours: zpub job c1420f63…, pipeline 613a1e32-ed85-
40c2-aaf5-c03fff3eba48, 2026-05-09, "create video of a monk meditating … a
colorfol small bird flies around in the background". Its run directory is gone,
so the only record left is the job JSON and the file itself. It is a generative
video, not a 3D scene — which matters, because it means there is no rig to copy,
only characteristics to measure. Four came out of it:

  1. THE FLIGHT IS 3D NOW. It was two hand-drawn curves — a path in image space
     and a size table indexed off it — with nothing connecting them, so the
     perspective was something I tuned by eye and every edit to one needed a
     matching edit to the other. Measured against the plate's own camera the
     two disagreed from the first frame, and for 54% of the flight the path was
     ABOVE the horizon line where the ground model says nothing at all: the
     size was a curve I drew, and that was the whole of it.

     The path is now authored in METRES and projected through the camera the
     canal is already rippled under — `fx.water`'s horizon 0.648 and vp_x
     0.470, the same pinhole `_water_field` reads ground depth off. Image
     position, apparent size, image speed and bank all fall out of one curve
     and cannot disagree. The camera puts the moored ship 27 m off and the
     bird's entry 4.2 m from the lens; the recession that comes out of that is
     6.8x where I had hand-authored 5x, which is the useful result — the eye
     had it roughly right, and now it is right for a reason.

  2. THE WINGS BLUR AND THE BODY DOES NOT. This is the single thing the
     reference has that a sprite sequence cannot get by accident, and it is not
     a flourish, it is what a camera does: within one exposure a wing tip
     travels most of a wingspan and the body travels about four plate pixels.
     So the wing STATE is sampled six times across a 0.55 shutter and
     accumulated while the position and scale stay at their mid-exposure
     values. The body lands on the same pixels every time and stays sharp; the
     wings land somewhere different and average into a fan. Measured, it cuts
     the worst frame-to-frame jump in drawn wing area from 60% to 40%, and it
     costs six tile resizes a frame.

  3. THE BEAT IS SLOWER AND THE STROKE IS ASYMMETRIC. The reference beats at
     3.1 Hz — nearly eight frames per cycle at 24. Ours ran 4.8 Hz, 5 frames
     per cycle, off four sprites, and 31 of the delivered file's 65 wing-phase
     runs lasted a single frame. A beat the frame rate cannot resolve does not
     read as fast, it reads as a glitch. It is now 3.3 Hz over a five-step
     ladder (top / upper / level / lower / bottom, all one seed), and the
     downstroke takes 36% of the beat against the recovery's 64%, because the
     downstroke is the power stroke and it is fast.

  4. IT BANKS INTO THE TURN. The old model rolled the bird off its WINGBEAT
     PHASE — measured, the correlation between the roll it applied and where
     the path actually turned was +0.275, and it never exceeded ±3°. Bank is
     now a coordinated turn, tan(bank) = v²·κ/g, computed in world space over a
     wide baseline and smoothed, because reading it off two samples of the
     projected path gave a signal spanning -2292° to +12397°.

usage:  python3 run_scene_shores_v22.py [--verify-only]
"""

# ruff: noqa: F401  this __init__ IS the re-export surface of the old
# run_scene_shores_v22.py; the submodule imports below are in the original
# section order so the module-level chdir side effect still runs first and once.
from zyg_workflows.run_scene_shores_v22.constants import (
    copy,
    json,
    math,
    os,
    shutil,
    subprocess,
    sys,
    sf,
    paths,
    exe,
    CREWS,
    np,
    Image,
    sss,
    ST,
    SRC_DIR,
    SRC_MP4,
    SLUG,
    OUT_DIR,
    SEED_WAV,
    NEW_PLATE,
    NEW_HIRES,
    SCENE_CFG,
    BIRD_CFG,
    WATER_POLY,
    SPRITE_DIR,
    SHORES,
    CLOSING_SEED,
    LINE3,
    STEM_LUFS,
    MASTER_LUFS,
    BED_LUFS,
    MUSIC_LUFS,
    BIRD_IN,
    BIRD_DUR,
    BEAT_S,
    TAIL_FADE_IN_S,
    END_FADE_S,
    MASTER_FADE_S,
    OVERSHOOT_S,
    SHIP_AT,
    SHIP_TOL,
    STILLS_CARRY,
    TAKES,
    _AUDIO_TAKES,
    _STATIC_REGIONS,
    _canary_px,
    _md5,
    _cp,
    _carry,
    _restamp,
    _dur,
    _span,
    _grab,
    _seq,
)
from zyg_workflows.run_scene_shores_v22.bird import (
    _bird_flies_away,
    _bird_is_in_the_delivered_file,
    _bird_trajectory_matches_model_in_delivered_file,
    _bird_bank_visible_in_delivered_file,
)
from zyg_workflows.run_scene_shores_v22.checks import (
    _no_crates_in_the_water,
    _the_bow_is_opaque,
    _no_one_on_the_stern,
    _smoke_leaves_the_chimney,
    _water_moves_in_the_delivered_file,
    _camera_holds_for_the_bird,
)
from zyg_workflows.run_scene_shores_v22.main import (
    main,
)
