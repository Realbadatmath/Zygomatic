#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Second Ledger cold-open — v24: the swing-away is one clean curve, not two
mismatched ones stitched together.

v23 fixed the jump and the "stops dead at the ship" defect, and shipped exit
0 — but the operator watched the delivered file and reported the bird now
flies "backwards and sidewards to the left" after the boat. That was real,
and it survived every v22-era numeric gate (bank range, median, correlation,
clamp-time) because those gates measure the SAME kind of thing v23's own path
broke in a way none of them happen to catch. Frame-by-frame, not just on
paper, is what actually found it (extracted + cropped delivered frames,
`_bird_pose` traced alongside them):

  THE ROOT CAUSE: `_bird_bank_table`'s bank comes from real 3D curvature —
  correct in general, but this camera is FIXED, and the rear-view sprite
  ladder (`_draw_bird_sprite`'s docstring: "these are REAR views... the only
  silhouette that reads as receding") has no way to show YAW, only ROLL. v23's
  extension path picked world-space waypoints without checking what they'd
  actually look like PROJECTED: measured directly off the shipped path, bank
  held at -45° for a full 2 SECONDS (t=3.8-5.9s) while the apparent on-screen
  turn during that same stretch was near zero (`turn_raw` ~0.01, two orders
  of magnitude under the bank) — the model was insisting on a hard bank while
  the screen trajectory was already most of the way to a straight diagonal
  line. That mismatch (hold a hard bank, then relax it back toward level
  while the screen path just keeps drifting left at constant velocity) is
  what "flies backwards and sidewards" was describing: the turn the bank
  claims to be doing isn't the turn the pixels are doing. Root of THAT: the
  hand-picked world waypoints had no relationship to the incoming SCREEN-space
  tangent at the ship, so the projected path had a kink there — an abrupt
  bend from "still climbing, barely drifting" (the approach's actual screen
  tangent at the ship, measured off the 13-point path alone: (tx,ty) =
  (-0.157, -0.988), i.e. 99% vertical) to "already sliding diagonally left,"
  with nothing continuous connecting them.

  THE FIX: author the swing-away directly in SCREEN SPACE, not world space,
  so continuity is guaranteed by construction instead of hoped for. A cubic
  Bezier starts at the ship's actual screen position with the APPROACH'S OWN
  measured tangent (so there is no kink to begin with — the bird keeps doing
  what it was already doing, then gradually bends), curves to a final
  tangent pointing left, and lands off-screen. Depth (Z, hence scale) is
  assigned along this curve separately and inverse-projected back through the
  SAME camera to get `path3d` control points — so the model's real-3D-
  curvature bank now has something to agree with, because the projected
  curve was designed to have real, continuous, single-direction curvature
  throughout, not stitched from unrelated waypoints. Measured result: bank
  goes single-signed the instant it starts turning and STAYS that sign for
  the rest of the flight (no back-and-forth), correlation with the apparent
  turn +0.699 (was +0.537 — and that number was flattering v23, since a
  Pearson correlation over the whole flight doesn't reveal a 2-second
  hold-while-flat-on-screen stretch the way tracing the two series side by
  side does).

  `dur_s` moves to 11.0s (from 9.5s) — the approach still reaches the ship at
  3.62s (was 5.0s in v20-v22; 4.08s in v23), and the extra time buys the new
  curve room to bend gradually instead of snapping through a tight radius.
  `bank_gain: 9.0→3.0` (v22) `→3.0` (unchanged from v23), `bank_raw_cap_deg`
  60→70, `bank_max_deg` 50→48 — retuned by the same sweep-and-measure method
  as v22/v23, against this new path.

The v23 fixes for the OTHER two notes are untouched: `bound_frac: 0.45` /
`bob_bodies: 1.2` (less "jump"), `beats: 2.0` / `flap_frac: 0.55` (less
flapping, more glide, same 2.9 Hz beat rate).

Gate changes from v23: none of the v22/v23 gate LOGIC changed (closest-
approach-to-ship, scale-gated frame-crossing, exit-and-stay-off-screen) — only
the numbers a longer, gentler curve produces. `dur_s` band widens to 9-13s to
admit 11.0s.

The two authoring inputs: `bird_cfg3d_v24.json` lives in this repo's
data/assets/scenes/second_ledger_shores/, `water_poly.json` is v22's,
unedited.

Everything below the picture and the base motion model (wing shape, blur,
stroke asymmetry, coordinated-turn bank formula) is v22's/v23's, carried
forward unedited — see v22's and v23's own headers for that history.

usage:  python3 run_scene_shores_v24.py [--verify-only]
"""

# ruff: noqa: F401, E402

from zyg_workflows.run_scene_shores_v24.constants import (
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
from zyg_workflows.run_scene_shores_v24.bird_flight import (
    _bird_flies_away,
)
from zyg_workflows.run_scene_shores_v24.gates import (
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
from zyg_workflows.run_scene_shores_v24.main import (
    main,
)


if __name__ == '__main__':
    raise SystemExit(main())
