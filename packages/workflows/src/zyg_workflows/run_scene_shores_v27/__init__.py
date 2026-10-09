# ruff: noqa: E402,F401  (re-export shim: the package IS the old module)
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

# Pattern A split of run_scene_shores_v27.py: every section below was moved VERBATIM into its own
# module. The submodules are imported in the ORIGINAL SECTION ORDER so that
# module-level side effects run exactly as they did in the single file.

from zyg_workflows.run_scene_shores_v27.constants import (
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
    NO_BIRD,
    BLUE_WATER,
    ST,
    SRC_DIR,
    SRC_MP4,
    SLUG,
    OUT_DIR,
    SEED_WAV,
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
    TAIL_TRIM_S,
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
from zyg_workflows.run_scene_shores_v27 import constants as _s  # noqa: E402

for _n in ('NEW_HIRES', 'NEW_PLATE'):
    if hasattr(_s, _n):
        globals()[_n] = getattr(_s, _n)
del _s, _n

from zyg_workflows.run_scene_shores_v27.bird_flight import (
    _bird_flies_away,
)

from zyg_workflows.run_scene_shores_v27.checks import (
    _bird_is_in_the_delivered_file,
    _bird_trajectory_matches_model_in_delivered_file,
    _bird_bank_visible_in_delivered_file,
    _no_crates_in_the_water,
    _the_bow_is_opaque,
    _no_one_on_the_stern,
    _smoke_leaves_the_chimney,
    _water_moves_in_the_delivered_file,
    _camera_holds_for_the_bird,
)

from zyg_workflows.run_scene_shores_v27.driver import (
    main,
)
