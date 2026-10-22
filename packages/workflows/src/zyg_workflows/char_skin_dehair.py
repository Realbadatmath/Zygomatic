#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""char_skin_dehair.py — take the PAINTED hair out of a baked skin atlas.

THE DEFECT (measured on male_realistic, 2026-09-23). char_photoreal.py bakes
the skin from klein renders of a depth plate, and klein draws a whole person:
eyebrows, moustache, stubble and scalp come back painted INTO the photograph
and get projected into the albedo with the skin. Two things then go wrong.

  1. They are flat. A brow painted on the forehead has no strands, no depth and
     no silhouette, and it reads as a smudge from any angle — which is what an
     operator meant by "they are uv mapped, so they are flat on the characters,
     this makes it look really fake".
  2. They BLOCK the real thing. char_hair.js asks CSPHOTOREAL.browsPainted()
     before it grows brows, precisely so a painted pair and a grown pair do not
     stack. While the paint is there, the grown brows can never appear.

So the paint comes off, and what is underneath is skin. The regions are found
in 3D on the body's own geometry — a brow band measured off the head, the
lower face for moustache and beard, the scalp above the hairline — never by
guessing at pixels in an atlas whose layout is a packed UDIM grid.

Inside a region, hair is separated from skin by being DARKER and less red:
the skin reference is that region's own bright percentile, so a pale face and
a dark one are both handled without a hard threshold. Lips are protected by
their redness and the eyes by staying above them.

    python3 char_skin_dehair.py --body male_realistic
    python3 char_skin_dehair.py --body male_realistic --preview /tmp/dh.png

Writes albedo_nohair.jpg beside albedo.jpg and sets `dehaired` in the manifest,
which is what char_photoreal.js reads to stop suppressing the grown brows.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
PACKS = os.path.join(HERE, 'data', 'assets', 'mesh_packs')
OUT = os.path.join(HERE, 'output', 'photoreal')


def head_frame(P):
    """Head metrics of the baked body, in the bake's own world (z up)."""
    V = P.reshape(-1, 3)
    zTop, zMin = float(V[:, 2].max()), float(V[:, 2].min())
    H = zTop - zMin
    headH = 0.13 * H
    chin = zTop - headH
    band = V[V[:, 2] > chin]
    cx = float((band[:, 0].min() + band[:, 0].max()) * 0.5)
    headW = float(band[:, 0].max() - band[:, 0].min())
    cy = float((band[:, 1].min() + band[:, 1].max()) * 0.5)
    # which way the face looks: the nose is the furthest point out of the head's
    # depth centre in the band between the chin and the brow
    mid = band[(band[:, 2] > chin + 0.22 * headH) & (band[:, 2] < zTop - 0.42 * headH)]
    mid = mid[np.abs(mid[:, 0] - cx) < 0.10 * headW]
    fwd = 1.0
    if len(mid):
        fwd = 1.0 if (mid[:, 1].max() - cy) >= (cy - mid[:, 1].min()) else -1.0
    return {
        'zTop': zTop,
        'zMin': zMin,
        'H': H,
        'headH': headH,
        'chin': chin,
        'cx': cx,
        'cy': cy,
        'headW': headW,
        'fwd': fwd,
    }


def texel_geometry(P, N, UV, man):
    """Per-texel world point and normal for the packed atlas."""
    from zyg_workflows import char_photoreal as CP

    atlas = man['atlas']
    W, H = atlas['width'], atlas['height']
    AUV = CP.atlas_uv(UV, atlas['tiles'], W, H)
    _ids, ys, xs, tid, bary = CP.rasterise(AUV, W, H)
    Pt = (P[tid] * bary[:, :, None]).sum(1)
    Nt = (N[tid] * bary[:, :, None]).sum(1)
    n = np.linalg.norm(Nt, axis=1, keepdims=True)
    Nt = Nt / np.where(n < 1e-9, 1.0, n)
    return ys, xs, Pt, Nt, W, H


def regions(Pt, Nt, F, want):
    """Boolean mask per region, on the texels the rasteriser found.

    Fractions of the head's OWN height, so they hold on any body this bake
    runs on rather than on the one they were tuned against."""
    z, x, _y = Pt[:, 2], Pt[:, 0], Pt[:, 1]
    hh, zt, cx = F['headH'], F['zTop'], F['cx']
    ax = np.abs(x - cx)
    face = (Nt[:, 1] * F['fwd']) > 0.05  # facing the way the nose does
    out = {}
    if 'brows' in want:
        out['brows'] = (z < zt - 0.34 * hh) & (z > zt - 0.55 * hh) & (ax < 0.42 * F['headW']) & face
    if 'beard' in want:
        # jaw, chin, upper lip and the sideburn line: everything below the nose
        # base, plus the cheeks where stubble is painted
        out['beard'] = (
            (z < zt - 0.62 * hh)
            & (z > F['chin'] - 0.06 * hh)
            & (ax < 0.52 * F['headW'])
            & ((Nt[:, 1] * F['fwd']) > -0.35)
        )
    if 'scalp' in want:
        out['scalp'] = z > zt - 0.34 * hh
    return out


def hair_mask(img, ys, xs, sel, red_ref=None, dark_k=0.80, pct=72, red_margin=10.0):
    """Which texels inside a region are painted HAIR rather than skin.

    Not a fixed threshold: the skin reference is the region's own bright
    percentile, so the same rule works on a pale face and a dark one. Lips and
    the inner mouth are protected by redness, which hair does not have."""
    if not sel.any():
        return np.zeros(len(ys), bool), {}
    rgb = img[ys[sel], xs[sel]].astype(np.float32)
    L = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    ref = float(np.percentile(L, pct))
    m = L < dark_k * ref
    # LIPS AND MOUTH ARE NOT HAIR. A percentile taken inside the region is set
    # by whatever dominates it, and in the beard region that is stubble — the
    # first pass smeared the mouth. The reference is the FACE's own skin
    # redness, measured once outside the hairy regions, and anything redder
    # than that by a margin is left alone whatever its luminance.
    red = rgb[:, 0].astype(np.float32) - rgb[:, 1]
    if red_ref is not None:
        m &= red < (red_ref + red_margin)
    full = np.zeros(len(ys), bool)
    full[np.where(sel)[0]] = m
    return full, {
        'skin_ref_L': round(ref, 1),
        'red_ref': None if red_ref is None else round(float(red_ref), 1),
        'texels': int(sel.sum()),
        'hair_texels': int(m.sum()),
        'share': round(float(m.mean()), 4),
    }


def dehair(body='male_realistic', want=('brows', 'beard', 'scalp'), radius=9, preview=None, log=print):
    import cv2
    from PIL import Image

    wd = os.path.join(OUT, body)
    pub = os.path.join(PACKS, 'photoreal', body)
    man_p = os.path.join(pub, 'manifest.json')
    man = json.load(open(man_p))
    src = os.path.join(pub, man.get('albedo', 'albedo.jpg'))
    img = np.asarray(Image.open(src).convert('RGB')).copy()
    z = np.load(os.path.join(wd, 'geom.npz'))
    P, N, UV = z['P'], z['N'], z['UV']
    F = head_frame(P)
    log(f'[dehair] {body}: head zTop {F["zTop"]:.3f} headH {F["headH"]:.3f} headW {F["headW"]:.3f} fwd {F["fwd"]:+.0f}')
    ys, xs, Pt, Nt, W, H = texel_geometry(P, N, UV, man)
    log(f'[dehair] {len(ys):,} texels rasterised into {W}x{H}')

    # the face's own skin redness, from the cheek band: between the brow and
    # the nose base, which carries neither brow nor beard
    z = Pt[:, 2]
    cheek = (z < F['zTop'] - 0.55 * F['headH']) & (z > F['zTop'] - 0.62 * F['headH']) & ((Nt[:, 1] * F['fwd']) > 0.05)
    if cheek.sum() > 200:
        c = img[ys[cheek], xs[cheek]].astype(np.float32)
        red_ref = float(np.median(c[:, 0] - c[:, 1]))
    else:
        red_ref = None
    log(f'[dehair] skin redness reference (R-G) = {red_ref}')

    regs = regions(Pt, Nt, F, want)
    mask = np.zeros((H, W), np.uint8)
    stats = {}
    for name, sel in regs.items():
        hm, st = hair_mask(img, ys, xs, sel, red_ref=red_ref)
        stats[name] = st
        mask[ys[hm], xs[hm]] = 255
        log(
            f'[dehair]   {name}: {st.get("hair_texels", 0):,} of '
            f'{st.get("texels", 0):,} texels ({100 * st.get("share", 0):.1f}%)'
        )

    # close pinholes so a brow is one blob and the inpaint has a clean edge
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2)
    mask = cv2.dilate(mask, k, iterations=1)
    out = cv2.inpaint(img[:, :, ::-1], mask, radius, cv2.INPAINT_TELEA)[:, :, ::-1]

    dst = os.path.join(pub, 'albedo_nohair.jpg')
    # subsampling=0 (4:4:4). The default 4:2:2 halves chroma resolution, and on a
    # SKIN atlas chroma is the signal: freckles, lip edge, the blue cast under
    # the eye. Luma-only detail is not what makes a face read as skin.
    Image.fromarray(out).save(dst, quality=95, subsampling=0)
    man['albedo_nohair'] = 'albedo_nohair.jpg'
    man['dehaired'] = {
        'regions': stats,
        'inpaint_radius': radius,
        'masked_px': int((mask > 0).sum()),
        'note': 'painted brows/beard/scalp removed so char_hair.js can grow real ones; see char_skin_dehair.py',
    }
    with open(man_p, 'w', encoding='utf-8') as fh:
        json.dump(man, fh, indent=1)
    log(f'[dehair] wrote {dst} ({(mask > 0).sum():,} px repainted)')

    if preview:
        before = Image.open(src).convert('RGB')
        tiles = man['atlas']['tiles']
        x0, y0, sz = tiles[0][2], tiles[0][3], tiles[0][4]
        a = before.crop((x0, y0, x0 + sz, y0 + sz)).resize((700, 700))
        b = Image.fromarray(out).crop((x0, y0, x0 + sz, y0 + sz)).resize((700, 700))
        sheet = Image.new('RGB', (1400, 700))
        sheet.paste(a, (0, 0))
        sheet.paste(b, (700, 0))
        sheet.save(preview)
        log(f'[dehair] preview {preview}')
    return man['dehaired']


if __name__ == '__main__':  # the CLI lives in char_skin_dehair_cli
    from zyg_workflows.char_skin_dehair_cli import main as _cli_main

    raise SystemExit(_cli_main())
