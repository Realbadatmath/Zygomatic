# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Second Ledger cold-open — v25: the bird can actually TURN now, not just
roll a fixed rear view — plus a residual bank-clamp bug fixed at the entry.

v24 shipped exit 0 — bank single-signed, correlated +0.699 with the apparent
screen turn, no more 2-second hold-while-flat — and the operator watched the
delivered file and reported it STILL "doesn't fly smooth and in a curve" and
STILL "flies sidewards/backwards to the left." Re-verified from scratch
rather than trusting the v24 checks: independently re-tracked the delivered
file's own canary pixels (not `_bird_pose`'s predictions) at 0.2s resolution
across the WHOLE flight, and composited every tracked position onto one
frame. The PATH is smooth and non-reversing — that part was never broken.
What v24 could not fix, because it never touched it, is HOW the bird looks
while banking:

  THE ROOT CAUSE (found by reading the renderer, not just tracing pixels):
  `_draw_bird_sprite` draws a REAR-view sprite and applies `pose['bank']` as
  a plain 2D `Image.rotate()` — see its own (accurate, and previously
  accepted) docstring: "a rear view is the one where roll is visible as roll
  rather than as yaw." That is true, and also the whole problem: nothing in
  this renderer ever changes WHICH view is drawn based on heading, so a bird
  that is actually turning away from the camera — which should show more of
  one wing and progressively more of its SIDE — instead only ever shows you
  its back, tilted. Exposing the yaw the model already computes and had been
  discarding (`_bird_bank_table`'s own `th`, kept only to sign the roll) and
  checking it against this shot's own path: yaw sits near 0deg (genuinely
  boresight, rear view is correct) through the ~1s cruise, but reaches
  -50deg at the very entry and -55 to -79deg through the turn and the whole
  swing-away exit — MOST of the flight's runtime, the bird is closer to
  side-on to the camera than dead-away from it, and a rolled rear view can
  only ever look like sliding sideways there, no matter how well-tuned the
  bank NUMBER is against the path's curvature. Retuning bank (v22, v23, v24,
  three rounds) could not have fixed this — it was never a curve-shape
  problem, it is a "wrong picture drawn" problem underneath the curve.

  THE FIX: a second, SIDE-view sprite ladder (`gen_bird_side_sprites.py`,
  `data/assets/bird_sprites/canary_side/`, same seed 4041 and elevation
  ladder as the rear set, so it reads as the same bird and resolves through
  the same `_bird_phase_at`), cross-faded in by `_draw_bird_sprite` as
  `|yaw|` grows (`yaw_side_lo_deg`/`yaw_side_hi_deg`, default 25/65 — plain
  rear below 25, plain side above 65, premultiplied-alpha cross-dissolve
  between). Below yaw=25 (the whole cruise) this is bit-for-bit the old
  rear-only render; a bird cfg with no `sprites_side` set is unaffected. The
  new ladder is authored facing screen-left, matching the sign this shot's
  yaw actually holds through the turn (measured, not assumed); a future shot
  turning the other way mirrors it at render time off the sign of `yaw`
  rather than needing a second render. `body_w` across the side ladder is
  calibrated to the REAR set's own scale via the one pose both ladders
  render similarly (glide, wings tucked) so cross-fading does not pop the
  bird's apparent size.

  A SECOND, SMALLER BUG surfaced while reading `_bird_bank_table` end to end
  for the yaw work: the entry (first ~0.6s) had bank pinned FLAT at the
  +48deg clamp the whole time, decoupled from the real on-screen curvature —
  the exact "clamp plateau" failure class v22 diagnosed and (thought it had)
  fixed, just never actually closed at the entry, and made slightly worse
  when v23/v24 raised `bank_raw_cap_deg` 60->70 for the exit's sake (which
  raises this artifact's ceiling too, since it is the same raw signal).
  Measured directly: v24's shipped entry holds a ~70deg direction change over
  about 1m of arc between hand-authored control points — a spline artifact,
  not a turn a real bird could fly. Fixed with `bank_entry_settle_frac: 0.06`
  (default 0.0, i.e. off, for every cfg before this one), which tapers the
  raw curvature signal up from zero over the first 6% of arc-length instead
  of letting the clamp answer for it; entry bank now peaks at +14deg and
  decays smoothly, matching the real (modest, decreasing) on-screen turn
  measured off the delivered v24 file. `bank_gain` nudged 3.0->3.1, swept and
  re-measured, to hold the v22-era median-|bank| floor (8deg) the taper alone
  would have narrowly missed (7.93deg) — everything else (correlation 0.69,
  range, clamp fraction, roll rate) moves inside a fraction of a degree.

Nothing about the PATH, the wingbeat, the duration, or the ship-pass/exit
gate logic changed from v24 — this version is the picture the same curve
gets drawn with, not a new curve. `bird_cfg3d_v25.json` is v24's config plus
`sprites_side` and `bank_entry_settle_frac`; `water_poly.json` is still v22's.

usage:  python3 run_scene_shores_v25.py [--verify-only]
"""

# ruff: noqa: F401  this __init__ IS the re-export surface of the old
# run_scene_shores_v25.py; the submodule imports below are in the original
# section order so the module-level chdir side effect still runs first and once.
from zyg_workflows.run_scene_shores_v25.constants import (
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
from zyg_workflows.run_scene_shores_v25.bird import (
    _bird_flies_away,
    _bird_is_in_the_delivered_file,
    _bird_trajectory_matches_model_in_delivered_file,
    _bird_bank_visible_in_delivered_file,
)
from zyg_workflows.run_scene_shores_v25.checks import (
    _no_crates_in_the_water,
    _the_bow_is_opaque,
    _no_one_on_the_stern,
    _smoke_leaves_the_chimney,
    _water_moves_in_the_delivered_file,
    _camera_holds_for_the_bird,
)
from zyg_workflows.run_scene_shores_v25.main import (
    main,
)
