# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: E402, F401
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Second Ledger cold-open — v23: the bird flies PAST the ship, not into it.

Three separate notes came back on v22's delivered file, and none of them were
about the bank (that landed — median |bank| 12.5°, correctly mirrored, closed
in v22):

  1. TOO MUCH WING. `bob_bodies: 3.0` amplifies the vertical bounding-flight
     scallop by three body-lengths in the sprite compositor (the only place
     that reads `bob_bodies` at all — `_bird_box` and the polygon-path
     `_draw_bird` both use an implicit 1.0x). At `bound_frac: 0.9` that is a
     peak-to-peak excursion of ~2.7 body-lengths every 1.25s bound cycle —
     which is what "jumps up too much" is. Dropped to `bound_frac: 0.45`,
     `bob_bodies: 1.2` (~3.75x less absolute scallop).
  2. TOO MUCH FLAP. `beats: 3.0` over `flap_frac: 0.72` meant 72% of every
     bound cycle was active wingbeat and only 28% was the closed-wing glide.
     Dropped to `beats: 2.0` / `flap_frac: 0.55` — fewer strokes per burst,
     more glide — while holding wingbeat rate at 2.9 Hz, still inside the
     2.4–4.2 Hz band the reference clip measured (v22's header): the beat
     reads slower without leaving the range a 24 fps small bird reads at.
  3. IT STOPS DEAD AT THE SHIP. This was the real defect, and it was
     deliberate: v20 fixed `SHIP_AT`/`SHIP_TOL` as the flight's *endpoint*
     because "flies towards the boat" was the only note on record. The
     correction is "towards, then LEFT, then off-screen" — the boat is a
     waypoint, not a destination.

Fixing (3) is a path change, not a knob, and it drags two things behind it:

  DURATION. Continuing the flight past the ship at the same 5s costs arc
  length the constant-arc-speed model has to spend somewhere, and spending it
  by rushing the APPROACH (to leave time for the new exit) undoes the "smoother,
  less rushed" note along with it — measured, holding the old 5s meant the
  approach's average speed roughly doubled (4.85 -> 9.5 m/s) to leave room for
  the swing-away. `dur_s` goes to 9.5s instead: the approach still reaches the
  ship in 4.08s (was 5.0s — 18% quicker, not 2x), and the remaining 5.4s is the
  bird banking away and receding off the left edge. More real time over the
  same wingbeat rate is also, directly, "allot more frames" for the same
  motion — each frame's displacement shrinks, which is its own source of
  smoothness independent of the bob/flap fixes above.

  BANK RETUNING. `bank_gain: 9.0` / `bank_raw_cap_deg: 16.0` were fit to v22's
  13-point approach-only path, where the spline's one bad spot (control points
  bunching at the lens) was the only place raw curvature got large and
  everything else needed a 9x push to read. The new swing-away is a real,
  intended hard turn — its own raw (ungained, uncapped) coordinated-turn angle
  peaks near ±50-55° on its own, physically, before any gain is applied
  (measured directly off `_bird_bank_table` with gain=1/cap=huge). Re-applying
  a 9x gain on top of that pins the bank at its clamp for most of the flight
  (measured: 49% of frames at the limit, correlation with the apparent turn
  falls to +0.25 — the same "flat plateau" failure mode v22's own header
  describes, just from the opposite direction: too much curvature this time,
  not too little). Retuned by direct measurement, sweeping gain against the
  same checks v22 introduced: `bank_gain: 3.0`, `bank_raw_cap_deg: 60.0`
  (raised because this path's real turns are legitimately sharper than the
  old entry artifact the 16° cap was sized for), `bank_max_deg: 50.0` (a hair
  above v22's 45, so the swing's genuine peak isn't clipped into the same
  plateau it's meant to avoid). Result: median |bank| 8.84°, correlation
  +0.537, 17% of the flight at the clamp — all inside the same floors v22
  set, with margin, not loosened.

The verify gate changes with the path, in two places:

  - "the flight has to END at the ship" (v20-v22) becomes "the flight's
    CLOSEST APPROACH to the ship is within tolerance" — measured over the
    whole trajectory, not just the last sample.
  - "the bird CROSSES the frame — it is meant to go away, not past" (v22)
    is gated on SCALE now, not banned outright: crossing back across x=0.40
    is only a defect if it happens while the bird still reads as near-size.
    Measured on this path, that crossing happens at t=5.5s with scale
    already down to 0.14 (v22's own "barely shrinks" floor was 0.22) — the
    bird is most of the way to invisible before it re-crosses anything.
  - New: the flight must actually EXIT off the left edge and stay there —
    x < -0.02 (a real margin past the edge, not a graze) for at least the
    final second of screen time. This is the check that would have caught
    v20-v22's "ends at the ship" design in the first place.

The two authoring inputs are unchanged in kind from v22 — `bird_cfg3d_v23.json`
lives in this repo's data/assets/scenes/second_ledger_shores/, `water_poly.json`
is the same file v22 used, unedited.

Everything below the picture and the base motion model (wing shape, blur,
stroke asymmetry, coordinated-turn bank formula) is v22's, and v22 carried v21
and v20 forward unedited in turn — see v22's own header for that history.

usage:  python3 run_scene_shores_v23.py [--verify-only]
"""

# The sections of the single file this package replaces, imported in the original
# section order so every module-level side effect still runs when it used to.
from zyg_workflows.run_scene_shores_v23 import scene_setup
from zyg_workflows.run_scene_shores_v23 import checks
from zyg_workflows.run_scene_shores_v23 import pipeline

# Every name the single module defined, re-bound here so no importer and no
# attribute access anywhere has to change.
from zyg_workflows.run_scene_shores_v23.scene_setup import (
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
from zyg_workflows.run_scene_shores_v23.checks import (
    _bird_bank_visible_in_delivered_file,
    _bird_flies_away,
    _bird_is_in_the_delivered_file,
    _bird_trajectory_matches_model_in_delivered_file,
    _camera_holds_for_the_bird,
    _no_crates_in_the_water,
    _no_one_on_the_stern,
    _smoke_leaves_the_chimney,
    _the_bow_is_opaque,
    _water_moves_in_the_delivered_file,
)
from zyg_workflows.run_scene_shores_v23.pipeline import (
    main,
)
