# ruff: noqa: F401,E402
# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Second Ledger cold-open — v26: the operator watched v25 and reported three
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

usage:  python3 run_scene_shores_v26.py [--verify-only]
"""

from zyg_workflows.run_scene_shores_v26.constants import (
    BEAT_S,
    BED_LUFS,
    BIRD_CFG,
    BIRD_DUR,
    BIRD_IN,
    CLOSING_SEED,
    CREWS,
    END_FADE_S,
    Image,
    LINE3,
    MASTER_FADE_S,
    MASTER_LUFS,
    MUSIC_LUFS,
    NEW_HIRES,
    NEW_PLATE,
    OUT_DIR,
    OVERSHOOT_S,
    SCENE_CFG,
    SEED_WAV,
    SHIP_AT,
    SHIP_TOL,
    SHORES,
    SLUG,
    SPRITE_DIR,
    SRC_DIR,
    SRC_MP4,
    ST,
    STEM_LUFS,
    STILLS_CARRY,
    TAIL_FADE_IN_S,
    TAKES,
    WATER_POLY,
    _AUDIO_TAKES,
    _STATIC_REGIONS,
    _canary_px,
    _carry,
    _cp,
    _dur,
    _grab,
    _md5,
    _restamp,
    _seq,
    _span,
    copy,
    exe,
    json,
    math,
    np,
    os,
    paths,
    sf,
    shutil,
    sss,
    subprocess,
    sys,
)
from zyg_workflows.run_scene_shores_v26.bird_flight import (
    _bird_flies_away,
)
from zyg_workflows.run_scene_shores_v26.delivered_checks import (
    _bird_bank_visible_in_delivered_file,
    _bird_is_in_the_delivered_file,
    _bird_trajectory_matches_model_in_delivered_file,
    _camera_holds_for_the_bird,
    _no_crates_in_the_water,
    _no_one_on_the_stern,
    _smoke_leaves_the_chimney,
    _the_bow_is_opaque,
    _water_moves_in_the_delivered_file,
)
from zyg_workflows.run_scene_shores_v26.main import (
    main,
)
