#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""char_photoreal — the context objects and the per-view half of ``stage_bake``.

Extracted from ``bake.py`` (2026-10-09) without a behaviour change: every log
line, every side effect and their order are the ones the single 598-line
function had. The per-view state that used to live in its closures travels in
the two context objects :class:`BakeGeom` and :class:`BakeAnchors`."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import logging as _zyg_logging

from zyg_workflows.char_photoreal.constants import (
    BAD_DARK_L,
    BAD_DARK_OPEN_M,
    BAD_NEUTRAL_RB,
    BAD_WHITE_CHROMA,
    BAD_WHITE_L,
    DETAIL_KINDS,
    EYE_RADIUS,
    FEATHER_M,
    FEATHER_M_VIEW,
    GAIN_OF,
    HAND_RADIUS,
    HAND_TONE_PRIORITY,
    LOOSE_Z_TOL,
    PRIORITY,
)
from zyg_workflows.char_photoreal.plates import Cam, _sample_nearest, load_geom, work_dir
from zyg_workflows.char_photoreal.renders import _photo_foreground
from zyg_workflows.char_photoreal.atlas import (
    _bilinear,
    _partner,
    _symmetrise,
    atlas_uv,
    rasterise,
    tile_grid,
)

_zyg_log = _zyg_logging.getLogger(__package__)


# ── context objects ──────────────────────────────────────────────────────────


@dataclass
class BakeGeom:
    """Mesh, cameras and the rasterised atlas of one body.

    ``ys``/``xs`` are the atlas pixel of each rasterised texel, ``tid``/``bary``
    its triangle and barycentric coordinates, and ``Pt``/``Nt`` its world point
    and unit normal.
    """

    wd: str
    P: np.ndarray
    N: np.ndarray
    UV: np.ndarray
    cams: dict
    tiles: list
    W: int
    H: int
    AUV: np.ndarray
    ids: np.ndarray
    ys: np.ndarray
    xs: np.ndarray
    tid: np.ndarray
    bary: np.ndarray
    Pt: np.ndarray
    Nt: np.ndarray


@dataclass
class BakeAnchors:
    """The blender report's hand/eye centres and head extent, in world metres."""

    hand_c: dict = field(default_factory=dict)
    eye_c: dict = field(default_factory=dict)
    head_top_z: float = 0.0
    head_h: float = 0.0


@dataclass
class ViewProjection:
    """One view's projection of the atlas texels and the visibility tests on it.

    ``vis`` is the strict test (two-sided depth, eroded mask, good pixels),
    ``vis_loose`` the old one-sided fallback; ``nbad`` counts the texels the
    bad-pixel test took away from ``vis``.
    """

    cam: Any
    u: np.ndarray
    vv: np.ndarray
    z: np.ndarray
    inside: np.ndarray
    cosang: np.ndarray
    m_px: np.ndarray
    er: np.ndarray
    ztol: np.ndarray
    vis: np.ndarray
    vis_loose: np.ndarray
    Lraw: np.ndarray
    nbad: int = 0


# ── setup ────────────────────────────────────────────────────────────────────


def load_bake_geometry(body, log) -> BakeGeom:
    """Load the body's mesh and cameras and rasterise the UDIM atlas.

    Returns the :class:`BakeGeom` every later stage reads; logs the tile grid
    and the rasterisation time exactly as the original stage did.
    """
    wd = work_dir(body)
    P, N, UV = load_geom(body)
    cams = json.load(open(os.path.join(wd, 'cameras.json')))
    tiles, W, H = tile_grid(UV)
    log(
        f'[bake] {len(tiles)} UDIM tiles -> {W}x{H} atlas, cells '
        + ', '.join(sorted(set(f'{sz}px' for *_, sz in tiles)))
    )
    AUV = atlas_uv(UV, tiles, W, H)
    t0 = time.time()
    ids, ys, xs, tid, bary = rasterise(AUV, W, H)
    log(f'[bake] rasterised {len(ys)} texels in {time.time() - t0:.1f}s')
    Pt = (P[tid] * bary[..., None]).sum(1)  # world point per texel
    Nt = (N[tid] * bary[..., None]).sum(1)
    Nt /= np.maximum(np.linalg.norm(Nt, axis=1, keepdims=True), 1e-9)
    return BakeGeom(
        wd=wd,
        P=P,
        N=N,
        UV=UV,
        cams=cams,
        tiles=tiles,
        W=W,
        H=H,
        AUV=AUV,
        ids=ids,
        ys=ys,
        xs=xs,
        tid=tid,
        bary=bary,
        Pt=Pt,
        Nt=Nt,
    )


def load_anchors(wd) -> BakeAnchors:
    """Read the hand/eye centres and the head extent from ``blender_report.json``.

    An unreadable or absent report is not fatal: the stage then bakes without
    hand and eye zones, which is what the warning says.
    """
    anchors = BakeAnchors()
    try:
        rep_ = json.load(open(os.path.join(wd, 'blender_report.json')))
        anchors.hand_c = {k: np.array(v, np.float64) for k, v in rep_.get('hand_c', {}).items()}
        anchors.eye_c = {k: np.array(v, np.float64) for k, v in rep_.get('eye_c', {}).items()}
        anchors.head_top_z = float(rep_.get('hi', [0, 0, 0])[2])
        anchors.head_h = float(rep_.get('head_h', 0.0))
    except (OSError, ValueError) as _exc:
        _zyg_log.warning('blender_report.json unreadable, continuing without hand/eye anchors: %s', _exc)
    return anchors


def gain_depth(vid, views) -> int:
    """Count the GAIN_OF hops from ``vid`` up to a view outside ``views``.

    Sorting the views by this depth bakes a parent before its children, so a
    child can inherit a gain that is already matched (capped at 12 hops).
    """
    d, cur = 0, vid
    while cur in GAIN_OF and GAIN_OF[cur] in views and d < 12:
        cur = GAIN_OF[cur]
        d += 1
    return d


# ── per view ─────────────────────────────────────────────────────────────────


def load_view_image(wd, vid, cams, log):
    """Read one view's render, symmetrised with its mirror partner's.

    Returns the RGB array at the camera's size, or None (with a log line) when
    the view was never rendered.
    """
    import cv2
    from PIL import Image

    img_p = os.path.join(wd, 'renders', f'{vid}.png')
    if not os.path.isfile(img_p):
        log(f'[bake] {vid}: no render, skipped')
        return None
    img = np.asarray(Image.open(img_p).convert('RGB'))
    if img.shape[0] != cams['size']:
        img = cv2.resize(img, (cams['size'], cams['size']), interpolation=cv2.INTER_AREA)
    pvid = _partner(vid, cams['views'])
    pp = os.path.join(wd, 'renders', f'{pvid}.png')
    if os.path.isfile(pp):
        pimg = np.asarray(Image.open(pp).convert('RGB'))
        if pimg.shape[0] != cams['size']:
            pimg = cv2.resize(pimg, (cams['size'], cams['size']), interpolation=cv2.INTER_AREA)
        img = _symmetrise(img, pimg)
    return img


def project_view(vid, img, geom) -> ViewProjection:
    """Project every atlas texel into one view and run the depth/mask tests.

    Visibility is the texel's own depth against the view's Z pass (both ways,
    so a finger side projecting into a gap is rejected too) inside the eroded,
    median-rounded intersection of the plate mask and the photo's foreground.
    """
    import cv2

    cams, Pt, Nt = geom.cams, geom.Pt, geom.Nt
    v = cams['views'][vid]
    z_img = np.load(os.path.join(geom.wd, 'plates', f'{vid}_z.npy'))
    cam = Cam(v, cams['size'])
    u, vv, z = cam.project(Pt)
    S = cams['size']
    inside = (u >= 1) & (u < S - 2) & (vv >= 1) & (vv < S - 2) & (z > 0)
    to_cam = cam.t - Pt
    to_cam /= np.linalg.norm(to_cam, axis=1, keepdims=True)
    cosang = (Nt * to_cam).sum(1)
    # visibility: the texel's own depth against the Z pass, and away from
    # silhouettes (eroded mask) so a background pixel never bleeds onto skin
    mask = np.isfinite(z_img).astype(np.uint8)
    # ...AND the photo's own figure: the render follows the plate to within
    # a few pixels, not exactly, and wherever it falls short the plate's
    # silhouette covers studio background. Measured on the first bake: grey
    # bands across the face and torso. Skin is warm (R > B by a margin),
    # the backdrop is neutral, so a chroma test separates them; eroded so
    # the anti-aliased edge never samples grey.
    fgp = _photo_foreground(img)
    er = cv2.erode(mask & fgp, np.ones((9, 9), np.uint8))
    # 2026-09-22: the eroded mask's 1-px stair-steps (1.7 mm each on a
    # body photo) were the jagged ownership edge at the hip; a median
    # rounds them off before the distance transform is taken
    er = cv2.medianBlur(er, 5)
    m_px = z / cam.f  # metres per photo pixel at the texel
    # DEPTH TEST (2026-09-22). The plate IS the geometry, so a visible
    # texel's depth equals the Z pass to a fraction of a mm; the old
    # 30 mm tolerance was meant for photo/plate drift, which is an
    # image-space matter the foreground mask already handles, and it let
    # every head photo paint 16 mm THROUGH the lids and lips and the
    # body photos paint a finger onto the finger behind it (measured:
    # 91 % of the near-black island texels were covered by a photo pixel
    # that was black because it showed something else). Now: the texel
    # must lie within tol of the NEAREST Z-pass sample in a 3x3 window
    # (the window absorbs grazing-angle rounding, up to a pixel of
    # surface slope) with tol = 5 mm + 3 px of depth at this view's scale.
    # ...and in BOTH directions: a texel NEARER than the Z pass by more
    # than tol is a finger side projecting into the gap between the
    # fingers, where the plate shows the thigh behind — the mask closing
    # bridged that gap and the photo pixel there is the dark gap or the
    # grey backdrop (the black caps and white chunks on the fingers).
    zfill = np.nan_to_num(z_img, nan=1e9).astype(np.float32)
    zmin3 = cv2.erode(zfill, np.ones((3, 3), np.uint8))
    zmax3 = cv2.dilate(zfill, np.ones((3, 3), np.uint8))
    zs = _sample_nearest(zmin3, u, vv)
    zx = _sample_nearest(zmax3, u, vv)
    ztol = 0.005 + 3.0 * m_px
    vis = inside & (cosang > 0.15) & (z - zs < ztol) & (zx - z < ztol) & (_sample_nearest(er, u, vv) > 0)
    zn = _sample_nearest(zfill, u, vv)
    vis_loose = inside & (cosang > 0.15) & (np.abs(zn - z) < LOOSE_Z_TOL) & (_sample_nearest(er, u, vv) > 0)
    return ViewProjection(
        cam=cam,
        u=u,
        vv=vv,
        z=z,
        inside=inside,
        cosang=cosang,
        m_px=m_px,
        er=er,
        ztol=ztol,
        vis=vis,
        vis_loose=vis_loose,
        Lraw=img.astype(np.float32).mean(2),
    )


def reject_bad_pixels(vid, img, proj, geom, anchors) -> None:
    """Take the near-black, neutral and blown-out photo pixels off a view.

    Mutates ``proj.vis``, ``proj.vis_loose`` and ``proj.nbad`` in place: the
    strict test drops all three classes, the loose one keeps shadow but never
    backdrop or a specular chunk.
    """
    import cv2

    u, vv, inside, m_px = proj.u, proj.vv, proj.inside, proj.m_px
    # BAD PIXELS (2026-09-22): skin albedo is never near-black, and the
    # backdrop / a specular chunk is near-white and neutral. A photo
    # pixel like that is background, deep shadow (the armpit, between the
    # fingers where the mask closing bridged the gap) or a highlight, and
    # is not a contribution: the texel becomes a hole for the inpaint if
    # no other view holds it. (The base mesh has no eyeballs — the socket
    # is an inward-facing island the studio's own eye meshes sit in —
    # so a pupil painted there is not kept either.)
    # Near-black is judged per pixel and then OPENED 3x3, so a stubble
    # dot or a pore (1-2 px) stays and only a dark REGION goes (per-pixel
    # the rule speckled the ownership over the jaw; judged on a blurred
    # photo at L < 45 it threw away the whole shaded side of every head
    # photo and the head_back gain was matched over 8k texels instead
    # of 211k). Neutral = not warm: the backdrop is grey-blue, skin has
    # R - B > 16 (the foreground rule), so a bridged gap fails R - B.
    imf = cv2.GaussianBlur(img, (0, 0), 1.5).astype(np.float32)
    Lraw = proj.Lraw
    chroma = imf.max(2) - imf.min(2)
    # the opening is ~2.5 mm at this photo's scale (3 px on a body
    # photo, 9 on a head photo): a dark REGION is a gap, an armpit, a
    # nostril; dense stubble under the jaw in a 0.6 mm/px torso photo
    # is not (a 3 px opening there cut it into 3 mm blocks, measured)
    # (6 mm since the two-sided depth test took over the finger gaps:
    # at 2.5 mm the crotch shadow went too and came back as flat blocks)
    k_open = int(np.clip(round(BAD_DARK_OPEN_M / max(float(np.median(m_px[inside])), 1e-5)), 3, 15)) | 1
    bad_dark = (
        cv2.morphologyEx((Lraw < BAD_DARK_L).astype(np.uint8), cv2.MORPH_OPEN, np.ones((k_open, k_open), np.uint8)) > 0
    )
    if vid.split('_')[0] in ('head', 'eye'):
        # a head or eye photo's dark regions are the socket crease, the
        # nostrils and the pupil on the socket interior — real cavities
        # at 0.1-0.25 mm/px, not bridged gaps; rejecting them filled
        # the skin round the eye and the nostrils with flat tone in
        # 2 mm blocks (measured on the head az 0 shot). The two-sided
        # depth test already stops the through-the-lid painting.
        bad_dark[:] = False
    bad_neutral = (imf[..., 0] - imf[..., 2]) < BAD_NEUTRAL_RB  # the backdrop through a bridged gap
    bad_white = (imf.mean(2) > BAD_WHITE_L) & (chroma < BAD_WHITE_CHROMA)
    badm = cv2.dilate((bad_dark | bad_neutral | bad_white).astype(np.uint8), np.ones((3, 3), np.uint8))
    badt = _sample_nearest(badm, u, vv) > 0
    hand_c = anchors.hand_c
    if hand_c and vid not in hand_c:
        # inside the hand zone a body/torso/legs photo shows the hand as
        # a 40 px smudge in shadow: its dark pixels (finger undersides,
        # L < 60) and its bright slivers (an edge-on finger, L > 200) are
        # not skin colour there — the hand photo and the tone fill are
        dh = np.min([np.linalg.norm(geom.Pt - c_, axis=1) for c_ in hand_c.values()], axis=0)
        Lt_ = _sample_nearest(Lraw, u, vv)
        badt |= (dh < HAND_RADIUS[0]) & ((Lt_ < 60) | (Lt_ > 200))
    proj.nbad = int((proj.vis & badt).sum())
    proj.vis = proj.vis & ~badt
    # the loose test keeps shadow (bad_dark) but never backdrop or a white chunk
    badl = _sample_nearest(cv2.dilate((bad_neutral | bad_white).astype(np.uint8), np.ones((3, 3), np.uint8)), u, vv) > 0
    proj.vis_loose = proj.vis_loose & ~badl


def view_weights(vid, img, proj, geom, anchors, probe):
    """Build one view's colour and its four weight fields over the atlas.

    Returns ``(ref, feather_px)`` where ``ref`` is the eight-element list the
    blend reads: colour, detail weight, facing cosine, tone weight, the mask
    feather, the loose detail and tone weights, and the plain coverage.
    """
    import cv2

    Pt, S = geom.Pt, geom.cams['size']
    cam, u, vv, z = proj.cam, proj.u, proj.vv, proj.z
    inside, cosang, m_px, er = proj.inside, proj.cosang, proj.m_px, proj.er
    vis, vis_loose = proj.vis, proj.vis_loose
    dens = (cam.f / z) ** 2  # pixels per metre, squared
    # cos^10: the squarest view WINS a texel rather than sharing it. With
    # cos^2 eight head photos, each a few pixels off the plate in its own
    # way, blended into a ghosted mouth and doubled nostrils (measured on
    # the first bake); a steep facing weight keeps each region one photo.
    wbase = np.clip(cosang, 0, 1) ** 4 * dens * PRIORITY.get(vid, 1.0)
    w = np.where(vis, wbase, 0.0)
    # ease the weight down toward the silhouette: a smoothstep over
    # FEATHER_M metres (15 mm on a body photo, 2026-09-22) of the distance
    # to the eroded mask's edge, sampled bilinearly. The old 12 px linear
    # ramp did not reach the tone band at all, so where body_front's
    # mask ended at the hip its tone stopped dead on the mask's
    # stair-steps and the three-quarter view's tone began.
    feather_m = FEATHER_M_VIEW.get(vid, FEATHER_M.get(vid.split('_')[0], 0.015))
    feather_px = np.clip(feather_m / np.maximum(m_px, 1e-6), 3.0, 200.0)
    # the mask's contour is smoothed at the FEATHER scale before the
    # distance transform (2026-09-22): the chroma foreground test cuts
    # ragged 5-10 px bites out of the figure where the flank is in
    # bluish shadow, and a feather that follows those bites drew the
    # hip handover as a sawtooth. Blur-and-threshold, never growing
    # beyond the eroded mask.
    sig = float(np.clip(np.median(feather_px[inside]) / 2.0, 1.5, 12.0)) if inside.any() else 3.0
    er_s = ((cv2.GaussianBlur(er.astype(np.float32), (0, 0), sig) > 0.5) & (er > 0)).astype(np.uint8)
    dt = cv2.distanceTransform(er_s, cv2.DIST_L2, 5).astype(np.float32)
    # ...and the FRAME border counts as a mask edge (2026-09-22): a zoom
    # frame cuts through the body and klein's content at its edge is
    # unreliable (legs_front painted L 163 at its top edge where the
    # perineum is L 25-75 in every other photo — a pale chunk)
    yy_, xx_ = np.mgrid[0:S, 0:S]
    dt = np.minimum(dt, np.minimum(np.minimum(xx_, S - 1 - xx_), np.minimum(yy_, S - 1 - yy_)).astype(np.float32))
    t = np.clip(_bilinear(dt[..., None], u, vv)[:, 0] / feather_px, 0, 1)
    edge = t * t * (3.0 - 2.0 * t)
    # the DETAIL weight takes the feather cubed: after the per-texel
    # normalisation and cubing of the two-band blend a 30:1 priority
    # contrast puts the detail handover where the feather is ~1/27000,
    # i.e. on the mask's last pixel (the stepped hairy/smooth edge at
    # the hip, measured: torso_front's mask edge, dt 0..3 px); cubed,
    # the handover sits mid-feather where the distance field is smooth
    w = w * edge
    if probe and vid in ('torso_front', 'body_fr', 'body_fl'):
        probe('dtmm:' + vid, geom.ys, geom.xs, _bilinear(dt[..., None], u, vv)[:, 0] * m_px * 1000.0)
    zone = np.ones(len(Pt))
    if vid in anchors.hand_c:
        d = np.linalg.norm(Pt - anchors.hand_c[vid], axis=1)
        r0, r1 = HAND_RADIUS
        zone = np.clip((r1 - d) / (r1 - r0), 0, 1)
    if vid in anchors.eye_c:
        d = np.linalg.norm(Pt - anchors.eye_c[vid], axis=1)
        r0, r1 = EYE_RADIUS
        zone = np.clip((r1 - d) / (r1 - r0), 0, 1)
    w = w * zone
    w_loose = np.where(vis_loose, wbase, 0.0) * edge * zone
    # tone weight (2026-09-22): plain facing weight, feathered at the
    # mask edge like the detail weight, no priority and no density so two
    # photos hand their tone over across their whole overlap. A detail
    # view keeps a token weight — EXCEPT a hand view inside its radius:
    # the hand's tone from the body photos is a 40 px dark-red smudge
    # (measured L 110 against a 126 forearm), so the hand photo owns the
    # tone there too, fading out over HAND_RADIUS.
    kind = vid.split('_')[0]
    wl = np.where(vis, np.clip(cosang, 0, 1) ** 2, 0.0) * edge * zone
    wl *= HAND_TONE_PRIORITY if kind == 'hand' else (1e-3 if kind in DETAIL_KINDS else 1.0)
    wl_loose = (
        np.where(vis_loose, np.clip(cosang, 0, 1) ** 2, 0.0) * edge * zone * (1e-3 if kind in DETAIL_KINDS else 1.0)
    )
    col = _bilinear(img, u, vv)
    # colour gain matched to the primary view over the texels both see
    # ...over texels BOTH views see squarely. Measured on body_left: the
    # texels a profile shares with the front view are the front's
    # silhouette strip, seen at grazing angle where the photo's edge is
    # dark — a mean over them read 120 against 200 and clamped the gain.
    # So: both facing well, both weights healthy, median not mean.
    # A single number per view is not enough either: the photos carry a
    # left/right lighting gradient of their own, so one view is brighter
    # on one flank and darker on the other. The correction is a smooth
    # FIELD over the atlas: the ratio primary/view on shared texels,
    # binned at 1/8 resolution, Gaussian-blurred (sigma ~ 100 texels),
    # falling back to the global median ratio where support is thin.
    # this view's plain feathered coverage (facing, mask feather, zone; no
    # kind factor) — what TONE_YIELD_VIEWS yield their tone to
    cov = (np.where(vis_loose | vis, np.clip(cosang, 0, 1) ** 2, 0.0) * edge * zone).astype(np.float32)
    ref = [
        col.astype(np.float32),
        w.astype(np.float32),
        cosang.astype(np.float32),
        wl.astype(np.float32),
        edge.astype(np.float32),
        w_loose.astype(np.float32),
        wl_loose.astype(np.float32),
        cov,
    ]
    return ref, feather_px


def bake_view(vid, geom, anchors, log, probe):
    """Bake one view's contribution, or None when it contributes nothing.

    Returns ``(ref, stats)`` — the eight-element blend record and the
    ``per_view`` entry (texel and rejected-pixel counts).
    """
    img = load_view_image(geom.wd, vid, geom.cams, log)
    if img is None:
        return None
    proj = project_view(vid, img, geom)
    reject_bad_pixels(vid, img, proj, geom, anchors)
    if not proj.vis.any():
        log(f'[bake] {vid}: nothing visible, skipped')
        return None
    ref, feather_px = view_weights(vid, img, proj, geom, anchors, probe)
    w = ref[1]
    stats = {'texels': int((w > 0).sum()), 'bad_pixels': proj.nbad}
    log(
        f'[bake] {vid:11s} texels {int((w > 0).sum()):8d}  rejected bad pixels {proj.nbad:7d}  '
        f'feather {float(np.median(feather_px[proj.vis])):.0f} px  '
        f'ztol {float(np.median(proj.ztol[proj.vis])) * 1000:.1f} mm'
    )
    return ref, stats
