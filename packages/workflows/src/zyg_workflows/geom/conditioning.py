# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""conditioning.py — Phase 3: render passes -> ControlNet conditioning maps (2026-08-04).

RUN:
    python3 -m zyg_workflows.geom.conditioning <pass_set_dir> [-o out_dir]

WHAT THIS REPLACES.
arcane_restyle.depth_controlnet_arcane_restyle conditions on a depth map ESTIMATED from the
source image by Depth-Anything. For anything we render, that estimate is unnecessary: the
renderer already knows the depth exactly. This module turns a pass set into the same kind
of conditioning image, and three things follow.

  * accuracy — an estimator guesses relative depth from appearance and gets confused by
    exactly the things this scene is made of: a dark recess reads as "far", so a hatchet
    gash and a dark bark fissure estimate identically. The Z pass distinguishes them by
    construction.
  * NORMALS, which no estimator in this pipeline provides at all. A normal map is what
    tells the sampler a blade is at an angle to the surface rather than lying along it —
    the same distinction the gate measures as embedment.
  * licence — Depth-Anything-V2 Base/Large are CC-BY-NC-4.0 and out under our rules, which
    cost a day's work on 2026-08-03 to pin to the Apache-2.0 Small checkpoint. Rendered
    depth needs no model at all, so for rendered content the exposure disappears rather
    than being managed.

FOUR MAPS, EACH IN THE CONVENTION ITS CONTROLNET EXPECTS:
    depth.png    near = white. Normalised over the object range, not the whole frame,
                 because sky at 1e10 would otherwise crush everything into one value.
    normal.png   camera-space, (n * 0.5 + 0.5) * 255, the ControlNet/normalBAE convention.
    lineart.png  edges from DEPTH AND NORMAL DISCONTINUITY, not from image gradients. An
                 image-space edge detector fires on bark texture and on the boundary
                 between a light and dark patch of the same flat surface; a geometric one
                 fires only where the surface actually turns or steps. That is the
                 difference between drawing the object and drawing its texture.
    segment.png  one flat colour per object index, from IndexOB.

`xinsir/controlnet-union-sdxl-1.0` (Apache-2.0) accepts depth, normal, lineart and
segmentation in a single model, which is why these four are produced together.
"""

import argparse
import os
import sys

import numpy as np

from . import passes_io

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

# Distinct, well-separated colours so a segmentation map is readable by eye as well as by
# the sampler. Index 0 (background) stays black.
SEG_COLOURS = [
    (0, 0, 0),
    (220, 60, 60),
    (60, 200, 220),
    (240, 190, 70),
    (120, 220, 120),
    (180, 120, 240),
    (240, 140, 200),
    (140, 160, 250),
    (200, 200, 200),
    (250, 130, 60),
    (90, 190, 140),
    (200, 90, 150),
    (150, 210, 60),
    (110, 130, 210),
    (230, 210, 130),
    (80, 210, 200),
]


def subject(ps, mask=None):
    """The pixels a conditioning map is ABOUT — `ps.valid` unless a caller narrows it.

    WHY A CALLER WOULD NARROW IT (measured 2026-08-26 on the Pufferball sheet). Every map
    here normalises over its subject, so whatever is in the subject sets the scale. On a
    turntable sheet the GROUND PLANE is a rendered surface and runs to the horizon: the
    creature spans 1.236-1.608 m while the floor spans 1.004-4.429 m, so normalising over
    `ps.valid` spends 89% of the 0-255 range on floor and leaves the creature 27 levels to
    describe its entire form. IndexOB already labels the floor, so this is a lookup, not a
    heuristic — see mesh_control.subject_mask(), which builds the mask BY NAME from the
    asset's own index vocabulary.

    Default is unchanged (`ps.valid`), so every existing caller keeps its behaviour."""
    if mask is None:
        return ps.valid
    return ps.valid & mask


def depth_map(ps, near_white=True, pad=0.02, mask=None, lo=None, hi=None, subject_floor=0):
    """8-bit depth conditioning, normalised over the subject only.

    lo/hi (metres) override the per-image range. A SEQUENCE needs that: normalising each
    frame over its own range makes the depth signal breathe as the subject rotates, and a
    video model reads that breathing as the object changing size. One shared range across
    the sheet holds the scale still. A single still wants the default (per-image contrast).

    subject_floor raises the darkest SUBJECT value so 0 means background and nothing else.
    At the default 0 the farthest subject pixels — anything past the 99th percentile,
    which clips to t=1 — encode to exactly the background value, so the map's implied
    silhouette is eroded at its far edge and depth/matte stop agreeing (measured: 0.22%
    of frame on the Pufferball's front view). Left at 0 by default because the gates that
    have consumed this since 2026-08-04 were tuned on that output; conditioning built for
    a masked subject should pass 1.
    """
    d = ps.depth
    m = subject(ps, mask)
    if not m.any():
        return np.zeros(d.shape, np.uint8)
    p_lo, p_hi = np.percentile(d[m], 1.0), np.percentile(d[m], 99.0)
    lo = p_lo if lo is None else float(lo)
    hi = p_hi if hi is None else float(hi)
    span = max(hi - lo, 1e-6) * (1.0 + pad)
    out = np.clip((d - lo) / span, 0.0, 1.0)
    if near_white:
        out = 1.0 - out
    out = np.rint(out * 255.0)
    if subject_floor:
        out[m] = np.maximum(out[m], float(subject_floor))
    out[~m] = 0.0  # background reads as infinitely far
    return out.astype(np.uint8)


def normal_map(ps, mask=None, cam=None):
    """8-bit normal conditioning in the (n*0.5+0.5) convention.

    `cam` is the camera's 3x3 world rotation (columns = the camera basis in world
    space). Supply it and the normals are rotated into CAMERA space, which is what
    every ControlNet normal checkpoint expects: a surface facing the viewer encodes
    to (128, 128, 255) in every view.

    WITHOUT IT THE MAP IS WORLD-SPACE, which is what Blender's Normal AOV hands you
    and what shipped on the Pufferball sheet. Measured over the subject mask there,
    the camera-facing channel pinned to an extreme and swung view by view — front
    G=27, back G=235, side_left R=232, side_right R=22, top_down B=233 — instead of
    B staying near 255 throughout. A normal ControlNet reads that as a uniformly
    steep surface whose tilt flips as the creature turns.

    `cam` stays optional so existing callers keep the old output byte for byte
    rather than having a convention changed under them.

    Background is (128,128,255) in camera space — a normal pointing at the viewer.
    The world-space path keeps its old flat 128, which is a ZERO-LENGTH normal and
    decodes to nothing; that is another reason to pass `cam`."""
    if ps.normal is None:
        return None
    m = subject(ps, mask)
    n = ps.normal.copy()
    ln = np.linalg.norm(n, axis=2, keepdims=True)
    n = n / np.maximum(ln, 1e-6)
    if cam is not None:
        r = np.asarray(cam, dtype=np.float32).reshape(3, 3)
        n = n @ r  # n_cam = R^T . n_world, row-vector form
    out = ((n * 0.5 + 0.5) * 255.0).clip(0, 255).astype(np.uint8)
    out[~m] = (128, 128, 255) if cam is not None else 128
    return out


def lineart_map(ps, depth_step_mm=11.0, normal_deg=42.0, thickness=1, mask=None):
    """Edges where the GEOMETRY turns or steps — never where the texture merely changes.

    Two detectors, unioned:
      depth step   a jump larger than `depth_step_mm` between neighbouring pixels is an
                   occluding contour or the lip of a cut
      normal turn  an angular change larger than `normal_deg` is a crease — the rim of a
                   gash, the bevel of a blade, a bark fissure edge

    THRESHOLDS ARE SET BY THE DISPLACED BARK, not by taste. At 22 degrees and 6mm the map
    came back as solid white noise: the trunk carries 45mm of real geometric displacement,
    so every fissure wall crosses 22 degrees and the contours of the weapon were buried in
    bark. At 42 degrees only genuine creases survive — cut rims, blade bevels, the deeper
    fissures — and the occluding contour still comes from the depth step, which nothing in
    a texture can produce.
    """
    if cv2 is None:
        return None
    m = subject(ps, mask)
    d = np.where(m, ps.depth, np.nan)
    dm = d * 1000.0
    gx = np.abs(np.diff(dm, axis=1, prepend=dm[:, :1]))
    gy = np.abs(np.diff(dm, axis=0, prepend=dm[:1, :]))
    step = np.nan_to_num(np.maximum(gx, gy), nan=0.0) > depth_step_mm

    turn = np.zeros_like(step)
    if ps.normal is not None:
        n = ps.normal / np.maximum(np.linalg.norm(ps.normal, axis=2, keepdims=True), 1e-6)
        cos_t = np.cos(np.radians(normal_deg))
        for ax in (0, 1):
            sh = np.roll(n, 1, axis=ax)
            dot = (n * sh).sum(axis=2)
            turn |= dot < cos_t
        turn &= m

    edge = (step | turn).astype(np.uint8) * 255
    edge[~m] = 0
    if thickness > 1:
        edge = cv2.dilate(edge, np.ones((thickness, thickness), np.uint8))
    return edge


def segment_map(ps, mask=None):
    """One colour per pass_index.

    The lookup used to be `SEG_COLOURS[i % len(SEG_COLOURS)]`, which is a silent
    trap: with 9 colours, index 9 wraps to SEG_COLOURS[0] — BACKGROUND BLACK. A
    part would have been painted as "nothing there" and every downstream count of
    it would have read zero, which is indistinguishable from the part being
    missing. Overflow raises now; the palette is long enough that it should not."""
    m = subject(ps, mask)
    out = np.zeros((ps.h, ps.w, 3), np.uint8)
    for i in np.unique(ps.index):
        if i <= 0:
            continue
        if int(i) >= len(SEG_COLOURS):
            raise IndexError(
                'pass_index %d has no colour: SEG_COLOURS holds %d. Extend the '
                'palette — wrapping would paint this part as background.' % (int(i), len(SEG_COLOURS))
            )
        out[(ps.index == i) & m] = SEG_COLOURS[int(i)]
    return out


def maps_for(ps, mask=None, lo=None, hi=None, subject_floor=0, cam=None):
    """Every conditioning map for one already-loaded pass set, as arrays."""
    return {
        'depth': depth_map(ps, mask=mask, lo=lo, hi=hi, subject_floor=subject_floor),
        'normal': normal_map(ps, mask=mask, cam=cam),
        'lineart': lineart_map(ps, mask=mask),
        'segment': segment_map(ps, mask=mask),
    }


def write_maps(maps, out_dir, stem=''):
    """Write a map dict to <out_dir>/<stem><name>.png. Returns {name: path}."""
    if cv2 is None:
        return {}
    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    for k, v in maps.items():
        if v is None:
            continue
        p = os.path.join(out_dir, '%s%s.png' % (stem, k))
        cv2.imwrite(p, v if v.ndim == 2 else v[:, :, ::-1])  # cv2 wants BGR
        paths[k] = p
    return paths


def build(pass_dir, out_dir=None, write=True, mask=None):
    """Write every conditioning map for one pass set. Returns {name: path or array}."""
    ps = passes_io.load_set(pass_dir)
    out_dir = out_dir or os.path.join(pass_dir, 'control')
    maps = maps_for(ps, mask)
    if not write or cv2 is None:
        return maps
    return write_maps(maps, out_dir)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('pass_dir')
    ap.add_argument('-o', '--out', default=None)
    a = ap.parse_args(argv)
    paths = build(a.pass_dir, a.out)
    for k, v in sorted(paths.items()):
        print('  %-8s %s' % (k, v))
    return 0


if __name__ == '__main__':
    sys.exit(main())
