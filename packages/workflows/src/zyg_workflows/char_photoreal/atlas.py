#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""char_photoreal — the atlas section, verbatim lines 1294-1461, 1483-1546 of the original module."""

from __future__ import annotations

import numpy as np

from zyg_workflows.char_photoreal.constants import TILE
from zyg_workflows.char_photoreal.renders import _photo_foreground


# ── the atlas ──────────────────────────────────────────────────────────────
def tile_grid(UV, big=2048, small=TILE, width=8192):
    """The UDIM tiles this mesh uses (Blender convention, v up) and where each
    goes in the atlas. 2026-09-20: cells are no longer one size — the mirror
    pair with the most faces (the head halves, 13 466 triangles each) gets a
    `big` cell so the face has 0.2 mm texels instead of 0.4, the rest stay
    `small`. Shelf packing at a fixed width: the two big cells top-left, small
    cells fill the space right of them, then full rows below.
    Returns (tiles, W, H) with tiles = [(tu, tv, x0, y0, size), ...]."""
    # geom.npz holds Blender's own loop UVs: v UP, tiles at integer steps —
    # NOT glTF's flipped v. (The first bake flipped here and the browser,
    # which flips the glTF v back to Blender's, missed 36 871 of 66 298
    # vertices and drew the rest upside down.)
    c = UV.mean(1)
    t = np.floor(c).astype(int)
    keys, counts = np.unique(t, axis=0, return_counts=True)
    order = np.argsort(-counts)
    keys = [tuple(int(x) for x in keys[i]) for i in order]
    bigs = []
    if (
        len(keys) >= 2
        and (keys[0][0], keys[0][1] + 2) == keys[1]
        or len(keys) >= 2
        and (keys[1][0], keys[1][1] + 2) == keys[0]
    ):
        bigs = keys[:2]
    smalls = [k for k in keys if k not in bigs]
    tiles = []
    x = 0
    for k in bigs:
        tiles.append((k[0], k[1], x, 0, big))
        x += big
    slots = []
    if bigs:
        for y in range(0, big, small):
            for xx in range(x, width, small):
                slots.append((xx, y))
    y = big if bigs else 0
    while len(slots) < len(smalls):
        for xx in range(0, width, small):
            slots.append((xx, y))
        y += small
    for k, (xx, yy) in zip(smalls, slots):
        tiles.append((k[0], k[1], xx, yy, small))
    W = width if (bigs or len(smalls) * small >= width) else len(smalls) * small
    H = max(y0 + sz for _, _, _, y0, sz in tiles)
    return tiles, W, H


def atlas_uv(UV, tiles, W, H):
    """Per-corner atlas UV in [0,1] (v up), from Blender-convention UDIM UVs."""
    c = UV.mean(1)
    t = np.floor(c).astype(int)
    lut = {(tu, tv): (x0, y0, sz) for tu, tv, x0, y0, sz in tiles}
    out = np.zeros_like(UV)
    for i in range(len(UV)):
        x0, y0, sz = lut[(int(t[i, 0]), int(t[i, 1]))]
        local = UV[i] - t[i]
        out[i, :, 0] = (x0 + local[:, 0] * sz) / W
        out[i, :, 1] = 1.0 - (y0 + (1.0 - local[:, 1]) * sz) / H
    return out


def _cell_slice(x0, y0, sz):
    return (slice(y0, y0 + sz), slice(x0, x0 + sz))


def _seam_mask(P, AUV, W, H, tol=0.002):
    """Texels on the body's mid-line seam: every triangle edge whose two
    endpoints both lie within `tol` of the sagittal plane, drawn into the
    atlas. Twin texels of this seam are the SAME world points."""
    import cv2

    xm = 0.5 * (P[..., 0].min() + P[..., 0].max())
    on = np.abs(P[..., 0] - xm) < tol
    px = np.stack([AUV[..., 0] * W, (1.0 - AUV[..., 1]) * H], -1)
    seam = np.zeros((H, W), np.uint8)
    n = 0
    for a, b in ((0, 1), (1, 2), (2, 0)):
        sel = on[:, a] & on[:, b]
        for i in np.nonzero(sel)[0]:
            cv2.line(seam, tuple(np.round(px[i, a]).astype(int)), tuple(np.round(px[i, b]).astype(int)), 1, 1)
            n += 1
    return seam, n


def _seam_twins(seam, tiles):
    """(ya, xa, yb, xb) index arrays: seam texels in tile v and their twins
    in tile v+2 (identical local UVs, same cell size within a pair)."""
    cell = {(tu, tv): (x0, y0, sz) for tu, tv, x0, y0, sz in tiles}
    YA, XA, YB, XB = [], [], [], []
    for (tu, tv), (x0, y0, sz) in cell.items():
        if tv >= 2 or (tu, tv + 2) not in cell:
            continue
        x1, y1, sz1 = cell[(tu, tv + 2)]
        if sz1 != sz:
            continue
        ys_, xs_ = np.nonzero(seam[_cell_slice(x0, y0, sz)])
        YA.append(ys_ + y0)
        XA.append(xs_ + x0)
        YB.append(ys_ + y1)
        XB.append(xs_ + x1)
    if not YA:
        return None
    return tuple(np.concatenate(a) for a in (YA, XA, YB, XB))


def _seam_report(img, twins, log, label):
    """Mean |RGB difference| between seam twins — the number that must be
    ~0 for the mid-line to be invisible. Logged at every bake stage since
    2026-09-20, when a 12-level split down the face turned out to be made by
    the pair equalisation itself."""
    if twins is None:
        return None
    ya, xa, yb, xb = twins
    d = np.abs(img[ya, xa].astype(np.float32) - img[yb, xb].astype(np.float32))
    v = float(d.mean())
    log(
        f'[bake] seam twins after {label:9s}: mean |dRGB| {v:.1f} over {len(ya)} texels (p90 {np.percentile(d.mean(1), 90):.1f})'
    )
    return round(v, 2)


def rasterise(AUV, W, H):
    """Triangle id per texel (-1 = none) and barycentrics, drawn with cv2."""
    import cv2

    ids = np.full((H, W), -1, np.int32)
    px = np.empty_like(AUV)
    px[..., 0] = AUV[..., 0] * W
    px[..., 1] = (1.0 - AUV[..., 1]) * H
    # draw in order; a tiny dilation per triangle would double-cover, so keep
    # exact and pad the islands afterwards
    for i in range(len(px)):
        cv2.fillConvexPoly(ids, np.round(px[i]).astype(np.int32), int(i), lineType=cv2.LINE_8)
    ys, xs = np.nonzero(ids >= 0)
    tid = ids[ys, xs]
    p = px[tid]  # (n,3,2)
    x = xs + 0.5
    y = ys + 0.5
    x0, y0 = p[:, 0, 0], p[:, 0, 1]
    x1, y1 = p[:, 1, 0], p[:, 1, 1]
    x2, y2 = p[:, 2, 0], p[:, 2, 1]
    det = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    det = np.where(np.abs(det) < 1e-12, 1e-12, det)
    l0 = ((y1 - y2) * (x - x2) + (x2 - x1) * (y - y2)) / det
    l1 = ((y2 - y0) * (x - x2) + (x0 - x2) * (y - y2)) / det
    l2 = 1.0 - l0 - l1
    bary = np.clip(np.stack([l0, l1, l2], 1), 0, 1)
    bary /= bary.sum(1, keepdims=True)
    return ids, ys, xs, tid, bary


def _bilinear(img, u, v):
    H, W = img.shape[:2]
    u = np.clip(u, 0, W - 1.001)
    v = np.clip(v, 0, H - 1.001)
    x0 = np.floor(u).astype(int)
    y0 = np.floor(v).astype(int)
    fx = (u - x0)[:, None]
    fy = (v - y0)[:, None]
    a = img[y0, x0].astype(np.float64)
    b = img[y0, x0 + 1].astype(np.float64)
    c = img[y0 + 1, x0].astype(np.float64)
    d = img[y0 + 1, x0 + 1].astype(np.float64)
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def _partner(vid, views):
    """The view mirrored about the body's sagittal plane: same kind, same
    elevation, azimuth negated. az 0 / 180 are their own partner."""
    v = views[vid]
    if vid.endswith('_l') and vid[:-2] + '_r' in views:
        return vid[:-2] + '_r'
    if vid.endswith('_r') and vid[:-2] + '_l' in views:
        return vid[:-2] + '_l'
    want = (-v['az']) % 360
    for k, o in views.items():
        if k.split('_')[0] == vid.split('_')[0] and o['el'] == v['el'] and (o['az'] % 360) == want:
            return k
    return vid


def _symmetrise(img, partner_img, sigma=40):
    """Even out the photo's OWN left/right lighting with its mirror partner.
    Every klein photo is lit from image-left however flat the prompt; the
    partner view, flipped horizontally, is the same body lit from the other
    side (the mesh is symmetric to a few mm). Only the LOW-FREQUENCY ratio is
    taken from the partner, so this photo keeps its own detail — no second
    photo is blended in, nothing ghosts. Measured: the face mid-line step of
    26 levels came from exactly this asymmetry."""
    import cv2

    fg = _photo_foreground(img).astype(np.float32)
    pf = np.ascontiguousarray(partner_img[:, ::-1])
    fgp = _photo_foreground(pf).astype(np.float32)

    def lp(im, f):
        num = cv2.GaussianBlur(im.astype(np.float32) * f[..., None], (0, 0), sigma)
        den = cv2.GaussianBlur(f, (0, 0), sigma)
        return num / np.maximum(den, 1e-3)[..., None], den

    la, da = lp(img, fg)
    lb, db = lp(pf, fgp)
    ok = (da > 0.05) & (db > 0.05)
    ratio = np.where(ok[..., None], np.clip(lb / np.maximum(la, 1.0), 0.5, 2.0), 1.0)
    corr = 0.5 * (1.0 + ratio)
    out = img.astype(np.float32) * corr
    return np.clip(out, 0, 255).astype(np.uint8)


def _pad_islands(tex8, island, fill, rounds=24):
    """Grow each island's colour outward by `rounds` texels with a NORMALISED
    blur (only filled texels vote), so mip-mapping never pulls the backdrop
    across a seam. The first bake blurred against black and drew a dark ring."""
    import cv2

    col = tex8.astype(np.float32)
    have = island.astype(np.float32)
    col *= have[..., None]
    k = np.ones((3, 3), np.float32)
    for _ in range(rounds):
        num = cv2.filter2D(col, -1, k)
        den = cv2.filter2D(have, -1, k)
        grow = (den > 0) & (have == 0)
        col[grow] = num[grow] / den[grow][:, None]
        have[grow] = 1.0
    out = np.clip(col, 0, 255).astype(np.uint8)
    out[have == 0] = fill
    return out
