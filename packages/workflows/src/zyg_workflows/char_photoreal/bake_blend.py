#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""char_photoreal — ``stage_bake``'s two-band blend and finishing passes.

Extracted from ``bake.py`` (2026-10-09) without a behaviour change. The detail
band is winner-takes-most, the tone band blends linearly; then the atlas is
delit, mirror-equalised, desheened, hand-pinned, hole-filled and padded."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

import numpy as np

from zyg_workflows.char_photoreal.constants import (
    TILE,
    TONE_MIN_SUPPORT,
    TONE_YIELD_VIEWS,
)
from zyg_workflows.char_photoreal.atlas import (
    _seam_mask,
    _seam_report,
    _seam_twins,
)
from zyg_workflows.char_photoreal.equalise import (
    _delight,
    _desheen3d,
    _detail_ratio,
    _equalise_hands,
    _equalise_mirror,
    _nearest_fill,
    _smooth_normals,
)


@dataclass
class BlendWeights:
    """The per-texel weight envelopes every view's blend is measured against."""

    wmax: np.ndarray
    wlin: np.ndarray
    wbmax: np.ndarray
    cov_others: np.ndarray
    soft: np.ndarray
    wmax_l: np.ndarray


@dataclass
class BlendBands:
    """The accumulated detail (high-band ratio) and tone (low-band) sums.

    The plain names are the strict pass, the ``2`` names the loose fallback;
    ``winner`` is the index into ``contrib`` of the view carrying the detail.
    """

    acc: np.ndarray
    wsum: np.ndarray
    acc2: np.ndarray
    wsum2: np.ndarray
    acc_lp: np.ndarray
    wls: np.ndarray
    acc_lp2: np.ndarray
    wls2: np.ndarray
    winner: np.ndarray


def blend_weights(contrib, n_texels) -> BlendWeights:
    """Reduce the per-view weights to the envelopes the blend normalises by.

    TWO-BAND blend (2026-09-20). Detail: winner-takes-most — weights
    normalised per texel and cubed, so where two photos overlap the squarer one
    carries ~all of the high frequencies. Tone: the low frequencies are blended
    with the LINEAR weights instead, so two photos that disagree in tone hand
    over smoothly across their whole overlap.
    """
    wmax = np.zeros(n_texels, np.float32)
    wlin = np.zeros(n_texels, np.float64)
    wbmax = np.zeros(n_texels, np.float32)
    for _, w, _, _, edge, _, _, _ in contrib:
        np.maximum(wmax, w, out=wmax)
        wlin += w
        np.maximum(wbmax, w / np.maximum(edge, 1e-6), out=wbmax)
    # TONE YIELD (2026-09-22): a three-quarter body photo is rim-lit along
    # its flank (body_fr L 172-208 on the hip crest where torso_right and
    # body_front read 128-161) and that tone made the crest pale. Such a
    # view keeps its DETAIL but hands its TONE weight over wherever any
    # other view covers the texel: wl *= 1 - max feathered coverage of the
    # others; it keeps the tone only where nothing else sees the skin.
    cov_others = np.zeros(n_texels, np.float32)
    for _, _, _, vid, _, _, _, cov in contrib:
        if vid not in TONE_YIELD_VIEWS:
            np.maximum(cov_others, cov, out=cov_others)
    cov_others = np.clip(cov_others, 0.0, 1.0)
    # LINEAR zone (2026-09-22): where a view that matters (a fifth of the
    # strongest unfeathered weight) is inside its own mask feather, the
    # detail band blends linearly by the feathered weights instead of
    # winner-takes-most — the cubed handover sat on the last pixel of
    # torso_front's mask at the hip, a sawtooth of hairy against smooth
    soft = np.zeros(n_texels, np.float32)
    for _, w, _, _, edge, _, _, _ in contrib:
        matters = (w / np.maximum(edge, 1e-6)) >= 0.2 * wbmax
        np.maximum(soft, np.where(matters & (w > 0), 1.0 - edge, 0.0), out=soft)
    wmax_l = np.zeros(n_texels, np.float32)
    for _, _, _, _, _, w2, _, _ in contrib:
        np.maximum(wmax_l, w2, out=wmax_l)
    return BlendWeights(wmax=wmax, wlin=wlin, wbmax=wbmax, cov_others=cov_others, soft=soft, wmax_l=wmax_l)


def blend_contributions(contrib, geom, weights, vox, log) -> BlendBands:
    """Accumulate every view's high band (a ratio) and low band (its tone field).

    Each view's tone is its own colour low-passed over the skin in 3D (12 mm),
    so the value is the same on both sides of every island border and both seam
    twins; the high band is the colour over that tone, which keeps the hue
    where an offset carried a pale sliver in as grey.
    """
    ys, Pt = geom.ys, geom.Pt
    wmax, wlin, cov_others, soft, wmax_l = (
        weights.wmax,
        weights.wlin,
        weights.cov_others,
        weights.soft,
        weights.wmax_l,
    )
    acc = np.zeros((len(ys), 3), np.float64)
    wsum = np.zeros(len(ys), np.float64)
    acc2 = np.zeros((len(ys), 3), np.float64)
    wsum2 = np.zeros(len(ys), np.float64)
    acc_lp2 = np.zeros((len(ys), 3), np.float64)
    wls2 = np.zeros(len(ys), np.float64)
    acc_lp = np.zeros((len(ys), 3), np.float64)
    wls = np.zeros(len(ys), np.float64)
    winner = np.full(len(ys), -1, np.int16)  # per-texel view that carries the detail
    wwin = np.zeros(len(ys), np.float32)
    t0 = time.time()
    for vi, (col, w, wl, vid, _edge, w2, wl2, _) in enumerate(contrib):
        has = w > 0
        if not has.any():
            continue
        if vid in TONE_YIELD_VIEWS:
            wl = wl * (1.0 - cov_others)
            wl2 = wl2 * (1.0 - cov_others)
            log(f'[bake] tone yield {vid}: tone weight kept on {float((wl > 1e-3 * wl.max()).mean()):.3f} of the atlas')
        # this view's tone field, blurred over the SKIN in 3D (12 mm) — the
        # same value on both sides of every island border and both seam twins
        lp = np.zeros((len(ys), 3), np.float32)
        lp[has], _ = vox.lowpass(Pt[has], col[has], np.ones(int(has.sum())), 0.012)
        wn = (1.0 - soft) * np.where(wmax > 0, w / np.maximum(wmax, 1e-30), 0.0) ** 3 + soft * np.where(
            wlin > 0, w / np.maximum(wlin, 1e-30), 0.0
        )
        # the high band is a RATIO to the view's own tone (2026-09-22),
        # clamped: an offset (col - lp) added to the blended tone carried
        # the photo's pale slivers in as grey (the olive fingers), and an
        # ear-rim highlight as white chunks; a ratio keeps the hue
        acc += _detail_ratio(col, lp) * wn[:, None]
        wsum += wn
        # LOOSE fallback: texels this view passes only under the old test
        has2 = (w2 > 0) & ~has
        if has2.any():
            # its tone there: this view's own colours (strict and loose)
            # low-passed at the loose texels — the shadow it shows, blended
            both_ = has | has2
            lp2 = np.zeros((len(ys), 3), np.float32)
            lp2[has2], _ = vox.lowpass(Pt[both_], col[both_], np.ones(int(both_.sum())), 0.012, at=Pt[has2])
            wn2 = np.where(has2, w2 / np.maximum(wmax_l, 1e-30), 0.0) ** 3
            acc2 += _detail_ratio(col, lp2) * wn2[:, None]
            wsum2 += wn2
            acc_lp2 += lp2 * np.where(has2, wl2, 0.0)[:, None]
            wls2 += np.where(has2, wl2, 0.0)
        better = w > wwin
        winner[better] = vi
        wwin[better] = w[better]
        # tone: the per-view tone weight (facing, mask feather, zone, hand
        # ownership — see the per-view loop), no priority, no pixel density
        acc_lp += lp * wl[:, None]
        wls += wl
    log(f'[bake] tone fields in {time.time() - t0:.0f}s')
    return BlendBands(
        acc=acc,
        wsum=wsum,
        acc2=acc2,
        wsum2=wsum2,
        acc_lp=acc_lp,
        wls=wls,
        acc_lp2=acc_lp2,
        wls2=wls2,
        winner=winner,
    )


def resolve_blend(bands, weights, contrib, geom, probe, log):
    """Turn the accumulated bands into one colour per covered texel.

    Returns ``(blend, covered)``. The TONE takes strict and loose
    contributions alike (2026-09-22): a view that sees a texel in shadow still
    knows its tone, and leaving it out lit the perineum into a pale chunk; the
    DETAIL stays strict, with the loose band as the only fallback.
    """
    ys, xs = geom.ys, geom.xs
    acc, wsum, acc2, wsum2 = bands.acc, bands.wsum, bands.acc2, bands.wsum2
    acc_lp, wls, acc_lp2, wls2 = bands.acc_lp, bands.wls, bands.acc_lp2, bands.wls2
    strict = (wsum > 0) & (wls > 0)
    loose = ~strict & (wsum2 > 0) & (wls2 > 0)
    covered = strict | loose
    # a texel whose only STRICT tone is a detail view's token weight (the
    # body photos round it were rejected as shadow) takes the LOOSE tone —
    # the shadow they show — not the detail view's own; measured: legs_front
    # paints L 175 at the top edge of its frame where every body photo has
    # the perineum at L 20-58, and alone it made a pale chunk there
    weak = strict & (wls < TONE_MIN_SUPPORT) & (wls2 > 0)
    if probe:
        probe('winner', ys, xs, bands.winner, [c[3] for c in contrib])
        probe('soft', ys, xs, weights.soft)
    log(
        f'[bake] covered {covered.mean():.3f} of rasterised texels '
        f'(strict {strict.mean():.3f}, loose fallback {loose.mean():.4f})'
    )
    tone = np.zeros((len(ys), 3), np.float64)
    ratio = np.ones((len(ys), 3), np.float64)
    tone[covered] = (acc_lp[covered] + acc_lp2[covered]) / (wls[covered] + wls2[covered])[:, None]
    ratio[strict] = acc[strict] / wsum[strict, None]
    ratio[loose] = acc2[loose] / wsum2[loose, None]
    log(
        f'[bake] tone from strict+loose; loose-only detail on {int(loose.sum())} texels, '
        f'weak strict tone on {int(weak.sum())}'
    )
    blend = np.clip(tone[covered] * ratio[covered], 0, 255)
    if probe:
        probe('blend', ys[covered], xs[covered], blend)
    return blend, covered


# ── the finishing passes ─────────────────────────────────────────────────────


def covered_image(vals, geom, covered):
    """Paint per-texel values into a full-size atlas image at the covered texels."""
    im = np.zeros((geom.H, geom.W, 3), np.uint8)
    im[geom.ys[covered], geom.xs[covered]] = np.clip(vals, 0, 255).astype(np.uint8)
    return im


def polish_atlas(blend, covered, geom, anchors, vox, xm, probe, log):
    """Delight, mirror-equalise, desheen and pin the hands, reporting the seam.

    Returns ``(tex8, blend, sh, pair_gap, seam_log, hand_log)``. The hand pin
    runs LAST: the desheen darkens every finger as a ridge (measured -10
    levels on the hands), so it must not come after this.
    """
    seam, nseg = _seam_mask(geom.P, geom.AUV, geom.W, geom.H)
    twins = _seam_twins(seam, geom.tiles)
    log(f'[bake] mid-line seam: {nseg} edges, {int(seam.sum())} texels')
    seam_log = {'blend': _seam_report(covered_image(blend, geom, covered), twins, log, 'blend')}
    # DELIGHT: a NORMAL-dependent gain; it sees only the low-frequency normal
    # (fed the raw texel normal it painted a bright band along every crease).
    blend, sh = _delight(blend, _smooth_normals(geom.Nt, geom.ys, geom.xs, covered, geom.H, geom.W), log, strength=0.7)
    if probe:
        probe('delight', geom.ys[covered], geom.xs[covered], blend)
    seam_log['delight'] = _seam_report(covered_image(blend, geom, covered), twins, log, 'delight')
    blend, pair_gap = _equalise_mirror(blend, geom.Pt[covered], xm, vox, log)
    # a second, FINE mirror pass on the head only (2026-09-22): klein lights
    # every photo from image-left and the delight is even in x by design, so
    # the 26 mm pass left the eye sockets 10 levels apart and a nose-side
    # shadow on one cheek. 7 mm is the scale of that shading; the pass is
    # biased toward the brighter side (a shadow is the defect), and fades out
    # below the chin so the body keeps its 26 mm result.
    head_h, head_top_z = anchors.head_h, anchors.head_top_z
    head_zone = np.clip((geom.Pt[covered, 2] - (head_top_z - 1.15 * head_h)) / 0.06, 0, 1) if head_h else None
    if head_zone is not None:
        # twice: one pass left the nose flanks 13 levels apart (the mirror
        # of a steep flank lands a voxel off; a second pass converges)
        for pass_ in (1, 2):
            blend, head_gap = _equalise_mirror(
                blend,
                geom.Pt[covered],
                xm,
                vox,
                log,
                sigma_m=0.007,
                clip=(0.75, 1.35),
                zone=head_zone,
                bias=0.65,
                label=f'head 7 mm #{pass_}',
            )
            pair_gap = pair_gap + head_gap
    seam_log['equalise'] = _seam_report(covered_image(blend, geom, covered), twins, log, 'equalise')
    if probe:
        probe('equalise', geom.ys[covered], geom.xs[covered], blend)
    blend = _desheen3d(blend, geom.Pt[covered], vox, log)
    seam_log['desheen'] = _seam_report(covered_image(blend, geom, covered), twins, log, 'desheen')
    if probe:
        probe('desheen', geom.ys[covered], geom.xs[covered], blend)
    blend, hand_log = _equalise_hands(blend, geom.Pt[covered], anchors.hand_c, vox, log)
    seam_log['hands'] = _seam_report(covered_image(blend, geom, covered), twins, log, 'hands')
    if probe:
        probe('hands', geom.ys[covered], geom.xs[covered], blend)
    return covered_image(blend, geom, covered), blend, sh, pair_gap, seam_log, hand_log


def fill_holes(tex8, blend, covered, island, geom, vox, probe, log):
    """Fill the holes inside the islands, then pad the atlas outside them.

    A hole takes the SKIN TONE AROUND IT IN 3D (12 -> 30 -> 60 mm low-pass of
    the covered texels, read at the hole's own points), never a neighbour
    island's colour. Returns the padded atlas image.
    """
    ys, xs, Pt = geom.ys, geom.xs, geom.Pt
    filled = np.zeros((geom.H, geom.W), np.uint8)
    filled[ys[covered], xs[covered]] = 1
    # holes inside islands (nothing valid saw them): fill by inpainting from
    # the surrounding skin. 2026-09-22: the inpaint used to run on an image
    # that was BLACK outside the covered texels, so every hole touching an
    # island border was filled from black — the dark caps on the fingertips
    # and toes. Now the covered texels are first grown over the whole atlas
    # (nearest texel), then the holes are inpainted on top of that.
    hole = (island == 1) & (filled == 0)
    tex8 = _nearest_fill(tex8, filled)
    if hole.any():
        # the fill is the SKIN TONE AROUND THE HOLE IN 3D (12 -> 30 -> 60 mm
        # low-pass of the covered texels, read at the hole's own points): an
        # armpit, a finger gap or the mouth cavity takes the tone of the
        # skin round it, never a neighbour island's colour or a dark crease
        # that happened to be nearest in the atlas (TELEA did that:
        # (6,0) 0.56 % near-black from one crease)
        hidx = np.nonzero(~covered)[0]
        fillc = np.zeros((len(hidx), 3), np.float32)
        need = np.ones(len(hidx), bool)
        for sig in (0.012, 0.03, 0.06):
            if not need.any():
                break
            v_, sup_ = vox.lowpass(Pt[covered], blend, np.ones(int(covered.sum())), sig, at=Pt[hidx[need]])
            ok_ = sup_ > 0.02
            sel = np.nonzero(need)[0][ok_]
            fillc[sel] = v_[ok_]
            need[sel] = False
        keep = ~need
        tex8[ys[hidx[keep]], xs[hidx[keep]]] = np.clip(fillc[keep], 0, 255).astype(np.uint8)
        log(
            f'[bake] filled {int(hole.sum())} hole texels ({hole.sum() / max(island.sum(), 1) * 100:.2f} % of island) '
            f'from the 3D skin tone, {int(need.sum())} by the nearest texel'
        )
    if probe:
        probe('inpaint', ys, xs, tex8[ys, xs])
    # pad: every texel outside an island takes the colour of the NEAREST
    # island texel (a straight dilation, 2026-09-22), so mip-mapping never
    # pulls a backdrop across a seam and the padding never differs from the
    # edge it continues — the old normalised blur ran the edge colours
    # together into streaks and a fill tone beyond 24 texels.
    pad = _nearest_fill(tex8, island)
    if probe:
        probe('pad', ys, xs, pad[ys, xs])
    return pad


def write_bake_manifest(body, geom, pad, per_view, covered, sh, pair_gap, seam_log, hand_log, log):
    """Save the padded albedo next to the body's manifest and return the manifest."""
    from PIL import Image

    out_p = os.path.join(geom.wd, 'albedo.png')
    Image.fromarray(pad).save(out_p)
    man = {
        'body': body,
        'atlas': {
            'tile': TILE,
            'width': geom.W,
            'height': geom.H,
            'tiles': [list(t) for t in geom.tiles],
            'cells': 'tu, tv, x0, y0, size (px; y0 from the top)',
            'uv_convention': 'blender: v up; glTF v = 1 - v',
        },
        'views': per_view,
        'coverage': round(float(covered.mean()), 4),
        'delight_sh': sh,
        'pair_gap': pair_gap,
        'seam': seam_log,
        'hands': hand_log,
        'renders': 'output/photoreal/%s/renders' % body,
        'built': time.strftime('%Y-%m-%d %H:%M:%S'),
    }
    with open(os.path.join(geom.wd, 'manifest.json'), 'w', encoding='utf-8') as fh:
        json.dump(man, fh, indent=1)
    log(f'[bake] wrote {out_p}')
    return man
