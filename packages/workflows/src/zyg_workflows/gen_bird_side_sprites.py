#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Generate the SIDE-PROFILE sprite ladder for the Second Ledger canary.

Companion to the REAR-view set in data/assets/bird_sprites/canary/ (rendered
2026-08-30, FLUX.2 klein-4B, seed 4041 — see that directory's sprites.json
note). That set can only ROLL in 2D, because a rear view has no way to show
YAW: a bird turning to fly off at an angle should show more of one wing and
less of the other, and a flat rotation of a fixed back-view cannot produce
that. Measured on the delivered v24 render, this shot's real 3D heading
relative to the camera swings from ~5-9 deg (cruise, genuinely near-boresight,
where the rear view is correct) out to ~58-80 deg at the entry and the
swing-away exit — i.e. most of the time the bank reads as a turn, the bird is
actually closer to SIDE-ON to the camera than dead-away from it. This set
gives the renderer something honest to show there.

Same species description as `_CANARY`/the rear set's note (wild-type Serinus
canaria: olive mantle, olive-brown wing-coverts with a pale bar, near-black
primaries, bright orange-yellow face, pale cream belly), same seed (4041, so
this reads as the same individual bird, not a different one glued on), same
5-elevation-plus-glide ladder as the rear set (rear_up/upper/level/lower/down
+ rear_glide) so `_bird_phase_at`'s nearest-elev lookup has the same
resolution on both views.

Authored facing: head/beak toward screen-LEFT (banking that way), because
that is the sign this shot's yaw is at every point where |yaw| is large
(measured: negative throughout — see run_scene_shores_v25.py's header). A
future shot that turns the other way mirrors this set at render time
(storyteller_scene_service._draw_bird_sprite does that automatically off the
sign of pose['yaw']) rather than needing a second render.

usage: python3 gen_bird_side_sprites.py [--only PHASE] [--seed N]
"""

import logging as _zyg_logging
import math
import os
import sys

from zyg_workflows.paths import ZYG_CREWS_ROOT

CREWS = str(ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
if os.path.isdir(CREWS):  # absent on a bare checkout (CI, a fresh clone)
    os.chdir(CREWS)

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from zyg_workflows import storyteller_scene_service as sss  # noqa: E402,F401 — loads ../../.env (ZYG_USE_COMFYUI etc.)

_zyg_log = _zyg_logging.getLogger(__name__)

OUT_DIR = os.path.join(CREWS, 'data', 'assets', 'bird_sprites', 'canary_side')
SEED = 4041
SIZE = 1024

SPECIES = (
    'a Serinus canaria (domestic canary), wild-type streaky yellow-green '
    'plumage: darker olive mantle, olive-brown wing coverts crossed by a '
    'pale wing bar, near-black primary flight feathers, a bright '
    'orange-yellow face, a pale cream belly and pale rump'
)
STYLE = (
    'clean digital illustration, flat cel-shaded colour, sharp crisp '
    'silhouette edge, isolated alone on a plain flat solid pale grey-blue '
    'background, studio product shot, no perch, no branch, no ground, no '
    'shadow, no other objects, no text'
)
NEG = (
    'rear view, back view, viewed from behind, facing away from camera, '
    'facing right, front view, human, person, hand, text, letters, '
    'watermark, logo, second bird, duplicate, extra wings, extra limbs, '
    'deformed anatomy, melted, blurry, cropped, perch, branch, nest, cage'
)

# elev matches the rear ladder exactly, one txt2img call each, same seed.
PHASES = {
    'side_up': (
        1.0,
        f'{SPECIES}, seen in SIDE PROFILE flying to the left, '
        'both wings raised fully upward above the body at the very '
        'top of the upstroke, wingtips near-vertical, head and beak '
        'pointing left, body banked and streamlined, {STYLE}',
    ),
    'side_upper': (
        0.5,
        f'{SPECIES}, seen in SIDE PROFILE flying to the left, '
        'both wings raised partway up, midway through the '
        'upstroke, head and beak pointing left, body banked, '
        '{STYLE}',
    ),
    'side_level': (
        0.0,
        f'{SPECIES}, seen in SIDE PROFILE flying to the '
        'left, both wings spread level with the body, mid-stroke, '
        'head and beak pointing left, body banked, {STYLE}',
    ),
    'side_lower': (
        -0.5,
        f'{SPECIES}, seen in SIDE PROFILE flying to the '
        'left, both wings lowered partway down, midway through '
        'the downstroke, head and beak pointing left, body '
        'banked, {STYLE}',
    ),
    'side_down': (
        -1.0,
        f'{SPECIES}, seen in SIDE PROFILE flying to the '
        'left, both wings swept fully downward below the body at '
        'the bottom of the downstroke, head and beak pointing '
        'left, body banked, {STYLE}',
    ),
    'side_glide': (
        None,
        f'{SPECIES}, seen in SIDE PROFILE gliding to the '
        'left, both wings folded and tucked close against the '
        'body, streamlined dart shape, head and beak pointing '
        'left, body banked, {STYLE}',
    ),
}


def _flood_key(im: Image.Image, tol: int = 22) -> Image.Image:
    """Alpha-key the flat backdrop by flood-filling from the four corners.

    No such utility survives in the repo from whichever script made the rear
    set (see the sprites.json note vs. the actual repo — it wasn't saved).
    Rebuilt from what the rear PNGs' own pixels show: near-uniform corner
    colour, alpha 0 there, a feathered (not hard-binary) edge at the
    silhouette boundary. cv2.floodFill from each corner (fast, C-side BFS)
    with a per-step tolerance so a soft gradient backdrop still keys out in
    one connected region, then a small blur of the resulting mask before it
    becomes alpha, so the cutout edge is soft the same way the rear set's is
    (measured: 224 distinct alpha levels there, not 2).
    """
    import cv2

    bgr = cv2.cvtColor(np.asarray(im.convert('RGB')), cv2.COLOR_RGB2BGR)
    h, w = bgr.shape[:2]
    mask = np.zeros((h + 2, w + 2), dtype=np.uint8)
    flags = cv2.FLOODFILL_MASK_ONLY | (255 << 8) | cv2.FLOODFILL_FIXED_RANGE
    for sx, sy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        cv2.floodFill(bgr.copy(), mask, (sx, sy), 0, loDiff=(tol, tol, tol), upDiff=(tol, tol, tol), flags=flags)
    bg = mask[1:-1, 1:-1] > 0
    from PIL import ImageFilter

    alpha = Image.fromarray((~bg * 255).astype(np.uint8), 'L')
    alpha = alpha.filter(ImageFilter.GaussianBlur(1.2))
    out = im.convert('RGBA')
    out.putalpha(alpha)
    return out


def _measure_body(im: Image.Image) -> tuple:
    """(head_h, anchor, span, diag) for a SIDE-view sprite.

    The rear set's body_w/anchor come from the yellow-green BODY CORE blob
    (bright lemon breast, _CANARY['body']/['breast']) because in a REAR view
    that blob's WIDTH is phase-invariant (the torso doesn't change size
    through a wingbeat, only the wings do) and IS the bird's transverse
    diameter — the same axis the camera sees head-on. A SIDE view has no
    such patch: measured directly off the actual rendered pixels (not the
    `_CANARY` constants, which are the OLD vector-drawn bird's palette and do
    not match what klein actually painted here), the torso reads as olive
    (~140,140,20) blending into cream belly, with no separate bright-yellow
    body stripe distinct from the wing colour the way the rear set has one.

    What IS phase-invariant in a side view is the HEAD — the wingbeat moves
    the wings, not the face — and the face is a solid, saturated patch
    (measured: R>220 and B<15 isolates it cleanly, the connected-component
    filter drops a thin stray belly/wing boundary highlight that the same
    colour gate also catches). Its HEIGHT stands in for the same "short-axis
    diameter" role body_w plays for the rear set: in a side view, vertical
    extent is dorsal-ventral thickness, the one axis a rear view and a side
    view measure the same way (both look at the bird roughly level, so up-
    down in the image is up-down on the bird either way — only the OTHER
    image axis differs, transverse for rear vs fore-aft for side). This
    function returns the raw head-blob height; converting it into a `body_w`
    that is size-CONSISTENT with the rear set's is a separate calibration
    step (see `_calibrate`) done once across the whole ladder, not per-phase.
    """
    from scipy import ndimage

    a = np.asarray(im.convert('RGB'), dtype=np.float32)
    al = np.asarray(im.split()[-1], dtype=np.float32)
    r, _g, b = a[..., 0], a[..., 1], a[..., 2]
    core = (al > 128) & (r > 220) & (b < 15)
    lbl, n = ndimage.label(core)
    if n == 0:
        ys, xs = np.where(al > 128)
        head_h = float(ys.max() - ys.min())
        anchor = (float(xs.mean()), float(ys.mean()))
    else:
        sizes = ndimage.sum(core, lbl, range(1, n + 1))
        best = 1 + int(np.argmax(sizes))
        ys, xs = np.where(lbl == best)
        head_h = float(ys.max() - ys.min())
        anchor = (float(xs.mean()), float(ys.mean()))
    oy, ox = np.where(al > 24)
    span = float(ox.max() - ox.min()) if len(ox) else float(im.width)
    height = float(oy.max() - oy.min()) if len(oy) else float(im.height)
    diag = float(math.hypot(span, height))
    return head_h, anchor, span, diag


# rear_glide, from the already-shipped, already-tuned canary/sprites.json —
# the one rear phase where wings are tucked, so its own full-image diagonal
# is close to being JUST the torso, the same regime the side set's glide
# phase is in.
_REAR_GLIDE_BODY_W = 115.11627906976744
_REAR_GLIDE_DIAG = math.hypot(429.0, 691.0)


def _calibrate(manifest: dict) -> None:
    """Rescale every phase's placeholder body_w (= its raw head-blob height)
    onto the REAR set's scale, so a side sprite and a rear sprite of the same
    `body_frac` render at the same apparent size instead of popping when the
    renderer cross-fades between them.

    The head blob is phase-invariant (proven by construction: only the wings
    move) but its ABSOLUTE size is in this set's own pixels, not the rear
    set's. Anchor the conversion on the one pose both ladders share a shape
    for — wings tucked, glide — where the whole sprite's bounding diagonal is
    close to being the bird's own body: require
    body_w_side_glide / diag_side_glide == body_w_rear_glide / diag_rear_glide,
    solve for the one scale factor `k` that satisfies it, then apply that
    SAME k to every phase's head_h (not a per-phase ratio — the head blob
    already carries whatever per-phase variation is real; recomputing k per
    phase would just be measuring the same head twice).
    """
    have = {n: r for n, r in manifest['phases'].items() if r.get('_head_h')}
    if len(have) < len(PHASES):
        _zyg_log.info(
            f'[gen] only {len(have)}/{len(PHASES)} phases measured — '
            f'body_w left as raw head_h until the whole ladder exists; '
            f're-run without --only'
        )
        return
    # The head-blob height genuinely varies per phase (measured: 90-180px, a
    # 2x spread) — partly real (more of the bright breast is exposed in some
    # poses than others) but too wide to use per-phase: the REAR set's own
    # body_w stays inside a MUCH tighter band (108.65-135.42, ~1.25x) across
    # every phase including its own glide, because it deliberately measures a
    # patch that does NOT depend on wing pose. Collapsing to one shared
    # MEDIAN across all 6 phases is the closest equivalent here — it is what
    # makes body_w phase-invariant BY CONSTRUCTION, the same guarantee the
    # rear set has, rather than one this set's raw per-phase measurement
    # happens to approximate. Without this, cycling the wingbeat would pump
    # the bird's apparent size the same way anchoring on the raw bbox would
    # have — the exact defect body_w was invented to avoid.
    head_hs = sorted(r['_head_h'] for r in have.values())
    n = len(head_hs)
    shared_head_h = head_hs[n // 2] if n % 2 else 0.5 * (head_hs[n // 2 - 1] + head_hs[n // 2])
    g = manifest['phases']['side_glide']
    target_body_w_glide = g['_diag'] * (_REAR_GLIDE_BODY_W / _REAR_GLIDE_DIAG)
    k = target_body_w_glide / shared_head_h
    for rec in have.values():
        rec['body_w'] = shared_head_h * k
    _zyg_log.info(
        f'[gen] shared head_h (median of {n}) = {shared_head_h:.1f}px, '
        f'calibrated against rear_glide: k={k:.4f} -> body_w={shared_head_h * k:.1f} '
        f'for every phase'
    )


if __name__ == '__main__':  # the CLI lives in gen_bird_side_sprites_cli
    from zyg_workflows.gen_bird_side_sprites_cli import main as _cli_main

    raise SystemExit(_cli_main())
