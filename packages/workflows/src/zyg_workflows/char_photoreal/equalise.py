#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""char_photoreal — the equalise section, verbatim lines 1547-1968 of the original module."""

from __future__ import annotations

import numpy as np

from zyg_workflows.char_photoreal.constants import DETAIL_HUE_BRIGHT, DETAIL_RATIO, HAND_RADIUS
from zyg_workflows.char_photoreal.atlas import _cell_slice


class Vox:
    """Low-pass filtering of per-texel quantities IN WORLD SPACE (2026-09-20).
    Every low-pass in UV space stops at an island border, so tones stepped
    wherever two islands meet: the mid-line (13.8 levels), the hips, the
    collarbones, the ear. Here texel values are scattered into a 2.5 mm
    voxel grid over the body, blurred in 3D (mask-normalised), and read back
    at the texel's own point — one continuous field over the whole skin, and
    the two seam twins, being one point, read one value."""

    def __init__(self, P_all, res=0.0025, pad=0.03):
        self.res = res
        self.lo = P_all.min(0) - pad
        self.shape = tuple(int(x) for x in (np.ceil((P_all.max(0) + pad - self.lo) / res).astype(int) + 1))
        self.n = int(np.prod(self.shape))

    def index(self, Pt):
        i = np.floor((Pt - self.lo) / self.res).astype(np.int64)
        i = np.clip(i, 0, np.array(self.shape) - 1)
        return np.ravel_multi_index(i.T, self.shape), i

    def lowpass(self, Pt, val, w, sigma_m, at=None, min_den=0.05):
        """Blurred `val` (n,) or (n,k) weighted by `w`, sigma in metres,
        sampled at `at` (default: Pt). Returns (values, support) — support
        is the blurred weight, ~0 where nothing was scattered nearby."""
        from scipy.ndimage import gaussian_filter

        flat, _ = self.index(Pt)
        v = val if val.ndim == 2 else val[:, None]
        s = sigma_m / self.res
        den = np.bincount(flat, weights=w, minlength=self.n).astype(np.float32).reshape(self.shape)
        den = gaussian_filter(den, s)
        out = []
        for c in range(v.shape[1]):
            num = np.bincount(flat, weights=v[:, c] * w, minlength=self.n).astype(np.float32).reshape(self.shape)
            out.append(gaussian_filter(num, s))
        num = np.stack(out, -1)
        lp = num / np.maximum(den, 1e-6)[..., None]
        _, j = self.index(Pt if at is None else at)
        r = lp[j[:, 0], j[:, 1], j[:, 2]]
        sup = den[j[:, 0], j[:, 1], j[:, 2]]
        return (r if val.ndim == 2 else r[:, 0]), sup


def _equalise_mirror(col, Pt, xm, vox, log, sigma_m=0.026, clip=(0.7, 1.4), zone=None, bias=0.5, label=''):
    """Mirror-symmetric tone (replaces the per-cell _equalise_pairs): each
    texel's ~26 mm tone is compared with the tone at its mirror point across
    the sagittal plane and both are pulled to their geometric mean. Computed
    in 3D, so it is continuous across every island border and is exactly 1
    on the mid-line (a point is its own mirror).
    `zone` (0..1 per texel) fades the correction out; `bias` > 0.5 moves the
    darker side further than the brighter (both still meet: a side at
    log-gap d moves by bias*d if darker, (1-bias)*d if brighter)."""
    lp, sup = vox.lowpass(Pt, col, np.ones(len(Pt)), sigma_m)
    Pm = Pt.copy()
    Pm[:, 0] = 2 * xm - Pm[:, 0]
    lpm, supm = vox.lowpass(Pt, col, np.ones(len(Pt)), sigma_m, at=Pm)
    ok = (sup > 0.05) & (supm > 0.05)
    g = np.ones_like(col)
    ratio = np.maximum(lpm[ok], 1.0) / np.maximum(lp[ok], 1.0)
    expo = np.where(ratio > 1.0, bias, 1.0 - bias)  # darker side (ratio > 1) moves more
    g[ok] = np.clip(ratio**expo, *clip)
    if zone is not None:
        g = 1.0 + (g - 1.0) * zone[:, None]
    before = float(np.abs(lp[ok] - lpm[ok]).mean())
    out = np.clip(col * g, 0, 255)
    lp2, _ = vox.lowpass(Pt, out, np.ones(len(Pt)), sigma_m)
    lp2m, _ = vox.lowpass(Pt, out, np.ones(len(Pt)), sigma_m, at=Pm)
    sel = ok if zone is None else (ok & (zone > 0.5))
    after = float(np.abs(lp2[sel] - lp2m[sel]).mean())
    before = float(np.abs(lp[sel] - lpm[sel]).mean())
    log(
        f'[bake] mirror tone gap ({label or f"{sigma_m * 1000:.0f} mm"}, |L-R|): {before:.1f} -> {after:.1f} over {int(sel.sum())} texels'
    )
    return out, [round(before, 2), round(after, 2)]


def _equalise_hands(
    col, Pt, hand_c, vox, log, r_ref=(0.20, 0.28), sigma_m=0.02, clip=(0.6, 1.8), sigma_hue=0.006, hue_clip=(0.8, 1.25)
):
    """2026-09-22. klein paints hands dark and red in every body photo, and
    the hand photo's own lighting gradient runs across the wrist; the two
    together left the hands at L 110 against a 126 forearm and redder by
    10 levels. Here the ~20 mm tone of everything within HAND_RADIUS is
    pulled, per channel, to the forearm's mean tone just above the wrist
    (r_ref metres from the hand centre), with the correction feathered from
    full at HAND_RADIUS[0] to none at HAND_RADIUS[1]. Detail (creases,
    nails, veins) rides on top untouched; only the broad tone moves."""
    if not hand_c:
        return col, {}
    lp, sup = vox.lowpass(Pt, col, np.ones(len(Pt)), sigma_m)
    out = col.copy()
    rep = {}
    r0, r1 = HAND_RADIUS
    for k, hc in hand_c.items():
        d = np.linalg.norm(Pt - hc, axis=1)
        refm = (d >= r_ref[0]) & (d < r_ref[1]) & (sup > 0.05)
        if refm.sum() < 500:
            log(f'[bake] hands: {k} has no forearm reference, left as is')
            continue
        ref = lp[refm].mean(0)
        # the correction is full over the whole hand zone (the body photos'
        # dark wrist left a 6-level dip at 0.14-0.20 m when it faded there)
        # and feathers out INTO the reference band, where it is ~1 anyway
        inside = (d < r_ref[1]) & (sup > 0.05)
        s = np.clip((r_ref[1] - d[inside]) / (r_ref[1] - r1), 0, 1)
        s = s * s * (3 - 2 * s)
        g = np.clip(ref / np.maximum(lp[inside], 1.0), *clip)
        g = 1.0 + (g - 1.0) * s[:, None]
        L = lambda c: float((c @ np.array([0.299, 0.587, 0.114])))
        hand = d < 0.10
        b_hand = L(col[hand].mean(0))
        out[inside] = np.clip(col[inside] * g, 0, 255)
        # HUE at a finer scale (2026-09-22): klein's lit finger sides are
        # pale AND grey (specular) over ~10 mm, inside the 20 mm tone, so
        # the per-channel pin above left them olive (a* 8 where the forearm
        # is 14). Here each channel's share of the 6 mm mean is pulled to
        # the forearm's; the 6 mm luminance is untouched (mean-normalised)
        lp6, sup6 = vox.lowpass(Pt[inside], out[inside], np.ones(int(inside.sum())), sigma_hue)
        dir_ref = ref / max(ref.mean(), 1.0)
        dir6 = lp6 / np.maximum(lp6.mean(1, keepdims=True), 1.0)
        gh = np.clip(dir_ref[None, :] / np.maximum(dir6, 0.2), *hue_clip)
        gh = np.where((sup6 > 0.05)[:, None], 1.0 + (gh - 1.0) * s[:, None], 1.0)
        out[inside] = np.clip(out[inside] * gh, 0, 255)
        a_hand = L(out[hand].mean(0))
        wrist = (d >= 0.13) & (d < 0.17)
        rep[k] = {
            'forearm_L': round(L(ref), 1),
            'hand_L': [round(b_hand, 1), round(a_hand, 1)],
            'hand_rgb': [round(float(x), 1) for x in out[hand].mean(0)],
            'wrist_L': round(L(out[wrist].mean(0)), 1),
        }
        log(
            f'[bake] hands: {k} L {b_hand:.1f} -> {a_hand:.1f} against forearm {L(ref):.1f} '
            f'(wrist band {L(out[wrist].mean(0)):.1f}), {int(inside.sum())} texels'
        )
    return out, rep


def _detail_ratio(col, lp):
    """The high band of the two-band blend: this view's colour over its
    own 12 mm tone, per channel, clamped to DETAIL_RATIO. Its BRIGHT side is
    hue-protected (2026-09-22): klein's highlights on the fingers are
    specular — brighter AND greyer than the skin round them (a* 7 where the
    hand is 14) — and carried in as a ratio they turned the pinned hand tone
    olive; a highlight may lighten the tone but may shift its hue by at most
    DETAIL_HUE_BRIGHT. Darker detail (freckles, creases, lips, nails) is
    pigment and keeps its full colour."""
    r = np.clip(col / np.maximum(lp, 8.0), *DETAIL_RATIO)
    rl = r.mean(1, keepdims=True)
    resid = r / np.maximum(rl, 1e-6)
    lo, hi = DETAIL_HUE_BRIGHT
    resid = np.where(rl > 1.0, np.clip(resid, lo, hi), resid)
    return rl * resid


def _nearest_fill(tex8, have):
    """Every texel where `have` is 0 takes the colour of the nearest texel
    where it is 1 (Voronoi dilation over the whole atlas)."""
    import cv2

    have = (np.asarray(have) > 0).astype(np.uint8)
    if have.all():
        return tex8.copy()
    _, lab = cv2.distanceTransformWithLabels(1 - have, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    ys_, xs_ = np.nonzero(have)
    lut_y = np.zeros(int(lab.max()) + 1, np.int32)
    lut_x = np.zeros(int(lab.max()) + 1, np.int32)
    ids = lab[ys_, xs_]
    lut_y[ids] = ys_
    lut_x[ids] = xs_
    return tex8[lut_y[lab], lut_x[lab]]


def _desheen3d(col, Pt, vox, log, s_mm=6.0, l_mm=80.0, floor=0.72, dead=0.97):
    """Highlight-only local flattening in 3D (replaces the per-cell
    _desheen): where the ~6 mm luminance exceeds the ~80 mm luminance beyond
    a 3 % dead zone the texel is darkened by that ratio; never lightened."""
    L = col.mean(1)
    w = np.ones(len(Pt))
    ls, _ = vox.lowpass(Pt, L, w, s_mm / 1000.0)
    ll, _ = vox.lowpass(Pt, L, w, l_mm / 1000.0)
    corr = np.clip((ll / np.maximum(ls, 1.0)) / dead, floor, 1.0)
    log(
        f'[bake] desheen3d: {int((corr < 0.98).sum())} texels darkened (sheen on ridges), sigmas {s_mm:.0f}/{l_mm:.0f} mm'
    )
    return np.clip(col * corr[:, None], 0, 255)


def _tile_texel_m(P, AUV, tiles, W, H):
    """Metres per texel of each atlas cell: world triangle area over atlas
    triangle area, summed per cell."""
    tw = {}
    c = AUV.mean(1)
    px = np.stack([AUV[..., 0] * W, (1.0 - AUV[..., 1]) * H], -1)
    a_w = 0.5 * np.linalg.norm(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), axis=1)
    e1 = px[:, 1] - px[:, 0]
    e2 = px[:, 2] - px[:, 0]
    a_p = 0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
    cx = c[:, 0] * W
    cy = (1.0 - c[:, 1]) * H
    for _tu, _tv, x0, y0, sz in tiles:
        m = (cx >= x0) & (cx < x0 + sz) & (cy >= y0) & (cy < y0 + sz)
        if m.any() and a_p[m].sum() > 0:
            tw[(x0, y0, sz)] = float(np.sqrt(a_w[m].sum() / a_p[m].sum()))
    return tw


def _desheen(tex8, island, tiles, texel_m, log, s_mm=6.0, l_mm=80.0, strength=1.0, floor=0.72, dead=0.97):
    """2026-09-20. klein lights every photo, and along a ridge (sternum,
    spine, collarbones) that is a broad SHEEN 1-2 cm wide that the delight,
    which only sees body-scale shading, leaves in the albedo — on the model
    it read as a painted bright stripe down the mid-line (measured with a
    colour-coded atlas: real texel content, not a seam). Highlight-only
    local flattening: where the ~6 mm luminance exceeds the ~80 mm luminance
    beyond a 3 % dead zone the texel is darkened by that ratio; nothing is
    ever lightened, so nipples, the navel, creases and freckles keep their
    tone. Blurs are island-normalised and sized in millimetres per cell.
    Mirror-pair cells (identical local UVs) share ONE correction field, the
    geometric mean of the two, so the mid-line seam twins stay equal
    (measured: a per-cell correction moved them from 3.4 to 5.7 levels)."""
    import cv2

    out = tex8.astype(np.float32)
    touched = 0
    cell = {(tu, tv): (x0, y0, sz) for tu, tv, x0, y0, sz in tiles}

    def corr_of(x0, y0, sz):
        tm = texel_m.get((x0, y0, sz))
        sl = _cell_slice(x0, y0, sz)
        f = island[sl].astype(np.float32)
        if not tm or f.sum() < 500:
            return None, sl, f
        L = out[sl].mean(2)

        def lp(sig):
            num = cv2.GaussianBlur(L * f, (0, 0), sig)
            den = cv2.GaussianBlur(f, (0, 0), sig)
            return num / np.maximum(den, 1e-3)

        ss = max(2.0, s_mm / 1000.0 / tm)
        sl_ = max(ss * 2.0, l_mm / 1000.0 / tm)
        ratio = lp(sl_) / np.maximum(lp(ss), 1.0)
        c = np.clip(ratio / dead, floor, 1.0) ** strength
        return np.where(f > 0, c, 1.0), sl, f

    done = set()
    for (tu, tv), (_x0, _y0, sz) in sorted(cell.items()):
        if (tu, tv) in done:
            continue
        group = [(tu, tv)]
        twin = (tu, tv + 2) if tv < 2 else (tu, tv - 2)
        if twin in cell and cell[twin][2] == sz:
            group.append(twin)
        cs = [corr_of(*cell[k]) for k in group]
        if any(c[0] is None for c in cs):
            for k, (c, sl, f) in zip(group, cs):
                done.add(k)
                if c is not None:
                    touched += int(((c < 0.98) & (f > 0)).sum())
                    out[sl] = np.clip(out[sl] * c[..., None], 0, 255)
            continue
        c = cs[0][0] if len(cs) == 1 else np.sqrt(cs[0][0] * cs[1][0])
        for k, (_, sl, f) in zip(group, cs):
            done.add(k)
            touched += int(((c < 0.98) & (f > 0)).sum())
            out[sl] = np.clip(out[sl] * c[..., None], 0, 255)
    log(f'[bake] desheen: {touched} texels darkened (sheen on ridges), sigmas {s_mm:.0f}/{l_mm:.0f} mm, pair-shared')
    return np.clip(out, 0, 255).astype(np.uint8)


def _equalise_pairs(tex8, island, tiles, log, sigma=64, clip=(0.7, 1.4), dseam=None, ramp_px=48):
    """2026-09-20. The mirrored halves are UDIM rows v and v+2 with IDENTICAL
    local UVs, so texel (x, y) of one tile is the mirror twin of texel (x, y)
    of the other. Measured on the 09-20 atlas: the left half was 20-35
    luminance levels brighter than the right in EVERY body tile (109 vs 144
    on the head tile) — the side photos differ in exposure and each flank is
    painted by its own side view. Skin albedo is symmetric to first order;
    freckles are high-frequency and stay. So the LOW-FREQUENCY colour of each
    pair is set to the pair's geometric mean, with a blur NORMALISED by the
    island mask (the old _equalise_halves blurred against the padding and
    overshot at island edges). Returns the atlas and a (before, after) list of
    per-pair median luminance differences for the log."""
    import cv2

    cell = {(tu, tv): (x0, y0, sz) for tu, tv, x0, y0, sz in tiles}
    out = tex8.astype(np.float32)
    report = []
    for (tu, tv), (x0, y0, sz) in sorted(cell.items()):
        if tv >= 2 or (tu, tv + 2) not in cell:
            continue
        x1, y1, sz1 = cell[(tu, tv + 2)]
        if sz1 != sz:
            continue
        sl0 = _cell_slice(x0, y0, sz)
        sl1 = _cell_slice(x1, y1, sz)
        A, B = out[sl0], out[sl1]
        fa, fb = island[sl0].astype(np.float32), island[sl1].astype(np.float32)
        f = fa * fb  # twins both on skin
        if f.sum() < 500:
            continue

        def lp(img, _f=f):
            num = cv2.GaussianBlur(img * _f[..., None], (0, 0), sigma)
            den = cv2.GaussianBlur(_f, (0, 0), sigma)
            return num / np.maximum(den, 1e-3)[..., None], den

        la, da = lp(A)
        lb, db = lp(B)
        both = (da > 0.02) & (db > 0.02)
        target = np.sqrt(np.maximum(la, 1.0) * np.maximum(lb, 1.0))
        ga = np.where(both[..., None], np.clip(target / np.maximum(la, 1.0), *clip), 1.0)
        gb = np.where(both[..., None], np.clip(target / np.maximum(lb, 1.0), *clip), 1.0)
        if dseam is not None:
            # 2026-09-20: a gain on the seam itself splits twin texels that
            # were equal (measured 12 levels down the face). The gain is 1
            # ON the seam and reaches full strength `ramp_px` texels away:
            # a soft residual gradient there, never a step.
            r = np.clip(dseam[sl0] / float(ramp_px), 0, 1)
            r = r * r * (3 - 2 * r)
            ga = ga ** r[..., None]
            r = np.clip(dseam[sl1] / float(ramp_px), 0, 1)
            r = r * r * (3 - 2 * r)
            gb = gb ** r[..., None]
        m = f > 0
        before = float(np.median(A[m].mean(1)) - np.median(B[m].mean(1)))
        A2 = np.clip(A * ga, 0, 255)
        B2 = np.clip(B * gb, 0, 255)
        after = float(np.median(A2[m].mean(1)) - np.median(B2[m].mean(1)))
        out[sl0][fa > 0] = A2[fa > 0]
        out[sl1][fb > 0] = B2[fb > 0]
        report.append((tu, tv, round(before, 1), round(after, 1)))
    log(
        '[bake] mirrored-pair luminance gap (right - left), before -> after: '
        + ', '.join(f'u{tu}:{b:+.0f}->{a:+.0f}' for tu, tv, b, a in report)
    )
    return np.clip(out, 0, 255).astype(np.uint8), report


def _equalise_halves(tex, filled, tiles, cols, rows, sigma=48):
    """The body's two halves are separate UDIM rows (v and v+2) with near-
    mirror layouts (measured: local UV within 0.04). Whatever lit one flank
    more than the other survives per-view matching as a step down the
    mid-line. So the LOW-FREQUENCY colour of each tile pair is set to their
    average — detail stays per side, the lighting difference goes."""
    import cv2

    T = tex.shape[0] // rows
    cell = {(tu, tv): (col, row) for tu, tv, col, row in tiles}
    out = tex.copy()
    done = 0
    for (tu, tv), (c0, r0) in cell.items():
        if tv >= 2 or (tu, tv + 2) not in cell:
            continue
        c1, r1 = cell[(tu, tv + 2)]
        sl0 = (slice(r0 * T, (r0 + 1) * T), slice(c0 * T, (c0 + 1) * T))
        sl1 = (slice(r1 * T, (r1 + 1) * T), slice(c1 * T, (c1 + 1) * T))
        A, B = tex[sl0], tex[sl1]
        fa, fb = filled[sl0].astype(np.float32), filled[sl1].astype(np.float32)

        def lp(img, f):
            num = cv2.GaussianBlur(img.astype(np.float32) * f[..., None], (0, 0), sigma)
            den = cv2.GaussianBlur(f, (0, 0), sigma)
            return num / np.maximum(den, 1e-3)[..., None], den

        la, da = lp(A, fa)
        lb, db = lp(B, fb)
        both = (da > 0.05) & (db > 0.05)
        target = 0.5 * (la + lb)
        ga = np.where(both[..., None], target / np.maximum(la, 1.0), 1.0)
        gb = np.where(both[..., None], target / np.maximum(lb, 1.0), 1.0)
        out[sl0] = np.clip(A * np.clip(ga, 0.5, 2.0), 0, 255)
        out[sl1] = np.clip(B * np.clip(gb, 0.5, 2.0), 0, 255)
        done += 1
    return out


def _sh_basis(n):
    """Spherical-harmonic terms EVEN in x. The photos are symmetrised about
    the sagittal plane upstream, so a term odd in x can only fit mesh or
    photo noise — and measured, it did: 175 vs 144 at 3 cm either side of
    the face mid-line with the odd terms in, 162 vs 157 without."""
    x, y, z = n[:, 0], n[:, 1], n[:, 2]
    return np.stack([np.ones_like(x), y, z, y * z, x * x - y * y, 3 * z * z - 1], 1)


def _smooth_normals(Nt, ys, xs, covered, H, W, sigma=20):
    """Texel normals blurred over the atlas islands (mask-normalised
    Gaussian, sigma in texels ~ 12 mm on a body tile), renormalised. Creases
    keep their photographic shading; only the body-scale lighting gradient
    reaches the delight."""
    import cv2

    img = np.zeros((H, W, 3), np.float32)
    f = np.zeros((H, W), np.float32)
    img[ys[covered], xs[covered]] = Nt[covered].astype(np.float32)
    f[ys[covered], xs[covered]] = 1.0
    num = cv2.GaussianBlur(img, (0, 0), sigma)
    den = cv2.GaussianBlur(f, (0, 0), sigma)
    sm = num / np.maximum(den, 1e-3)[..., None]
    n = sm[ys[covered], xs[covered]].astype(np.float64)
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    raw = Nt[covered]
    n = np.where(ln > 0.2, n / np.maximum(ln, 1e-9), raw)
    return n


def _delight(col, n, log, strength=1.0):
    """Divide a normal-dependent shading term out of the blended colours."""
    lum = col.mean(1)
    ok = lum > 8
    B = _sh_basis(n)
    coef, *_ = np.linalg.lstsq(B[ok], np.log(lum[ok] + 1.0), rcond=None)
    pred = np.exp(B @ coef)
    shade = pred / np.mean(pred[ok])
    shade = np.clip(shade, 0.6, 1.6)
    corr = 1.0 / (shade**strength)
    out = np.clip(col * corr[:, None], 0, 255)
    resid = np.std(np.log(lum[ok] + 1.0) - (B[ok] @ coef))
    log(f'[bake] delight: shading range {shade.min():.2f}..{shade.max():.2f}, residual log-lum std {resid:.3f}')
    return out, [round(float(c), 4) for c in coef]
