# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Region relief — the statistic the form predicates actually consume.

Moved verbatim out of the old single-file curvature.py (lines 603-886).
"""

import numpy as np

from zyg_workflows.geom.form.curvature.topology import (
    COLLAR_GAP_FRAC,
    COLLAR_MAX_TILT_DEG,
    COLLAR_WIDTH_FRAC,
    collar,
    mixed_voronoi_area,
    surface_distance,
    vertex_adjacency,
    vertex_normals,
)


# ---------------------------------------------------------------------------------
# region relief — the statistic the form predicates actually consume
# ---------------------------------------------------------------------------------
# HOUSE, CALIBRATED ON A MEASURED NULL — relief_null() reproduces it. 298 patches of
# radius 0.012 of stature seeded at random over the anny neutral's torso and limb skin
# (head, hands, feet and perineum excluded, because no requested landmark lies there and
# their relief is dominated by real features) gave:
#     |relief / stature|  median 3.6e-4   p90 9.9e-4   p95 1.25e-3  p99 2.45e-3  max 9.0e-3
#     |contrast|          median 0.67     p90 1.56     p95 2.16     p99 3.66     max 7.7
#     collar fit rms      median 0.87 mm  p90 1.67 mm  p99 2.60 mm
# So a patch of ORDINARY SKIN on this cage already reads 0.6 mm of relief at the median and
# 2.1 mm at the 95th percentile. The defaults sit at that 95th percentile: they call one
# random patch in twenty a landmark, which is the honest price of the cage's tessellation
# and is stated rather than hidden. A gate that BLOCKS on relief must calibrate against its
# own reference sample under the <1% rule and will want the p99 figures instead; nothing
# here may be inherited into a blocking claim unexamined.
RELIEF_MIN_CONTRAST = 2.0
RELIEF_MIN_FRAC_STATURE = 1.25e-3  # 2.3 mm at 1.85 m, 1.9 mm at 1.52 m
RELIEF_NULL_P99 = {'min_contrast': 3.7, 'min_frac_stature': 2.45e-3}


def region_relief(
    v,
    faces,
    group,
    gap_frac=COLLAR_GAP_FRAC,
    width_frac=COLLAR_WIDTH_FRAC,
    max_tilt_deg=COLLAR_MAX_TILT_DEG,
    stature_m=None,
    areas=None,
    normals=None,
    distances=None,
    min_contrast=RELIEF_MIN_CONTRAST,
    min_frac_stature=RELIEF_MIN_FRAC_STATURE,
):
    """Signed relief of a vertex group against the surface around it, in millimetres.

    THE METHOD, and why each step is there:
      1. collar = the geodesic band [gap, gap+width] around the group, on the same aspect
         of the body (see collar() for why edge-hop rings were measured and rejected).
      2. local frame from a PCA of the COLLAR's positions. Not from vertex normals: those
         are computed on the delivered triangulation and inherit its start-corner
         asymmetry (module docstring, trap four), and a frame that tilts differently on
         the two sides of the body turns a symmetric feature into an asymmetric relief.
         Positions are mirror-symmetric to 0.06 mm on these cages, so a position-only
         frame is not. The frame is oriented outward by agreeing with the collar's mean
         vertex normal; if that mean is short the collar has wrapped, the frame is
         meaningless, and the result is refused rather than reported.
      3. least-squares quadric h = a0 + a1 u + a2 w + a3 u^2 + a4 uw + a5 w^2 fitted to the
         COLLAR ONLY. A plane is not enough — the collar around any landmark on a torso or
         a limb is itself curved, and a plane fit charges that curvature to the feature.
      4. relief = mixed-Voronoi-area-weighted mean of the group's residual against that
         quadric, along the outward frame normal. Area weighting, because the mixed areas
         on this cage span 0.23-1310 mm^2 (measured) and an unweighted mean would let a
         densely tessellated corner of a patch outvote the rest of it.

    READ `collar_fit_rms_mm` BEFORE READING `relief_mm`. It is the reference surface's own
    residual, i.e. how well "the surface around this patch" is even defined here, and it is
    the noise floor the relief has to clear. `contrast` is the ratio of the two and is what
    the verdict is taken on, together with a floor in fractions of stature — so the same
    body at 1.52 m and 1.85 m gives the same verdict, which self_test() proves.
    """
    v = np.asarray(v, np.float64)
    g = np.unique(np.asarray(group, np.int64).ravel())
    if g.size == 0:
        raise ValueError('region_relief needs a non-empty group')
    if g.min() < 0 or g.max() >= len(v):
        raise ValueError('group indexes vertices outside the mesh (0..%d)' % (len(v) - 1))
    S = float(v[:, 2].max() - v[:, 2].min()) if stature_m is None else float(stature_m)
    if S <= 0:
        raise ValueError('stature must be positive, got %r' % (S,))
    ar = mixed_voronoi_area(v, faces) if areas is None else np.asarray(areas, np.float64)
    nvert = vertex_normals(v, faces) if normals is None else np.asarray(normals, np.float64)
    col, cdet = collar(
        v,
        faces,
        g,
        gap_frac=gap_frac,
        width_frac=width_frac,
        stature_m=S,
        normals=nvert,
        max_tilt_deg=max_tilt_deg,
        distances=distances,
        return_detail=True,
    )

    P = v[col]
    c = P.mean(0)
    u_, s_, vt = np.linalg.svd(P - c, full_matrices=False)
    nrm = vt[2]
    e1, e2 = vt[0], vt[1]
    mean_n = nvert[col].mean(0)
    ln = float(np.linalg.norm(mean_n))
    if ln < 0.35:
        raise ValueError(
            'collar mean normal has length %.3f — the collar wraps around the body '
            'rather than lying on one aspect of it, so "outward" is not defined for it '
            'and the sign of the relief would be arbitrary. Narrow the collar or tighten '
            'max_tilt_deg (now %.0f).' % (ln, max_tilt_deg)
        )
    if float(np.dot(nrm, mean_n)) < 0:
        nrm = -nrm
        e2 = -e2

    def _local(pts):
        d = pts - c
        return d.dot(e1), d.dot(e2), d.dot(nrm)

    cu, cw, ch = _local(P)
    M = np.stack([np.ones_like(cu), cu, cw, cu * cu, cu * cw, cw * cw], axis=1)
    coef, *_ = np.linalg.lstsq(M, ch, rcond=None)
    cond = float(np.linalg.cond(M))
    col_res = ch - M.dot(coef)

    gu, gw, gh = _local(v[g])
    Mg = np.stack([np.ones_like(gu), gu, gw, gu * gu, gu * gw, gw * gw], axis=1)
    res = gh - Mg.dot(coef)

    wt = ar[g]
    if wt.sum() <= 0:
        raise ValueError('group has zero total surface area')
    relief = float(np.average(res, weights=wt))
    col_rms = float(np.sqrt(np.average(col_res**2, weights=ar[col])))
    contrast = relief / col_rms if col_rms > 0 else np.inf
    frac = relief / S

    if abs(frac) < min_frac_stature or abs(contrast) < min_contrast:
        verdict = 'flat'
    else:
        verdict = 'protrusion' if relief > 0 else 'depression'

    # EXTRAPOLATION GUARD, and it is not decoration. The quadric is a reference surface
    # only where the collar constrained it. A group vertex that projects OUTSIDE the
    # collar's own footprint in the local (u, w) plane is being compared against a
    # polynomial nobody fitted there, and a quadric extrapolates violently: measured on
    # the FEMALE original, the 7-vertex deltopectoral patch had one vertex project 1.44x
    # beyond the collar and the relief came out -77.7 mm — against a median of -3.3 mm
    # over the same 7 vertices and -8.0 mm on the male — with a healthy-looking collar
    # residual of 1.96 mm and a contrast of -39.6. Nothing in the collar diagnostics
    # catches that; only the footprint does. Compared per angular sector because the
    # collar is not round.
    reach = _footprint_reach(gu, gw, cu, cw)
    if reach > 1.0:
        raise ValueError(
            'group projects %.2fx beyond the collar footprint in the local frame, so its '
            'relief would be read off an extrapolated quadric rather than off a fitted '
            "one (the surface has folded away from the collar's tangent plane). Median "
            'residual over the group is %+.2f mm and the extreme is %+.2f mm — that '
            'spread is the extrapolation, not the anatomy.'
            % (reach, float(np.median(res)) * 1000.0, float(res[np.argmax(np.abs(res))]) * 1000.0)
        )
    return {
        'n_group': int(len(g)),
        'n_collar': int(len(col)),
        'relief_mm': relief * 1000.0,
        'relief_frac_stature': frac,
        'relief_median_mm': float(np.median(res)) * 1000.0,
        'relief_min_mm': float(res.min()) * 1000.0,
        'relief_max_mm': float(res.max()) * 1000.0,
        'collar_fit_rms_mm': col_rms * 1000.0,
        'contrast': float(contrast),
        'verdict': verdict,
        'stature_m': S,
        'centroid': [float(x) for x in v[g].mean(0)],
        'centroid_frac_stature': float((v[g][:, 2].mean() - v[:, 2].min()) / S),
        'frame_normal': [float(x) for x in nrm],
        'collar_normal_agreement': ln,
        'collar_planarity': float(s_[2] / max(s_[1], 1e-30)),
        'fit_condition': cond,
        'group_reach_over_collar': reach,
        'collar_spec': cdet,
        'thresholds': {
            'min_contrast': float(min_contrast),
            'min_frac_stature': float(min_frac_stature),
            'provenance': 'HOUSE',
        },
    }


def _footprint_reach(gu, gw, cu, cw, bins=12):
    """How far the group projects beyond the collar, per angular sector, in the local
    plane. 1.0 means it exactly touches the collar's outer edge somewhere; above 1.0 the
    quadric is being evaluated where nothing constrained it."""
    gr = np.hypot(gu, gw)
    cr = np.hypot(cu, cw)
    ga = np.mod(np.arctan2(gw, gu), 2 * np.pi)
    ca = np.mod(np.arctan2(cw, cu), 2 * np.pi)
    step = 2 * np.pi / bins
    lim = np.zeros(bins)
    for b in range(bins):
        sel = (ca >= b * step) & (ca < (b + 1) * step)
        lim[b] = cr[sel].max() if sel.any() else cr.max()
    return float((gr / np.maximum(lim[np.minimum((ga / step).astype(int), bins - 1)], 1e-12)).max())


def geodesic_ball(v, faces, seeds, radius_frac, stature_m=None):
    """Every vertex within `radius_frac` of stature of a seed set, along the surface."""
    v = np.asarray(v, np.float64)
    S = float(v[:, 2].max() - v[:, 2].min()) if stature_m is None else float(stature_m)
    d = surface_distance(v, faces, seeds)
    idx = np.nonzero(d <= radius_frac * S)[0]
    if idx.size == 0:
        raise ValueError('geodesic ball of %.4f stature around %s is empty' % (radius_frac, np.atleast_1d(seeds)[:5]))
    return idx


def relief_null(v, faces, n=300, radius_frac=0.012, seed=20260806, mask=None, stature_m=None):
    """The distribution of region_relief over RANDOM patches of this body's own skin.

    This is the reference the verdict thresholds are calibrated against, and it exists as
    code so the numbers in RELIEF_MIN_* can be re-derived rather than believed. Restricted
    by default to torso and limb skin: sampling the whole shell instead puts most of the
    seeds on the face and hands, where a 20 mm patch holds 300 vertices and relief runs to
    63 mm because there are real features everywhere — measured, and it inflates the p99 by
    an order of magnitude while saying nothing about the regions this package cares about.
    """
    v = np.asarray(v, np.float64)
    S = float(v[:, 2].max() - v[:, 2].min()) if stature_m is None else float(stature_m)
    zmin = float(v[:, 2].min())
    fz = (v[:, 2] - zmin) / S
    if mask is None:
        from scipy.sparse.csgraph import connected_components

        _, lab = connected_components(vertex_adjacency(faces, len(v)), directed=False)
        m = lab == np.bincount(lab).argmax()
        m &= (fz > 0.075) & (fz < 0.855) & (np.abs(v[:, 0]) < 0.25 * S)
        m &= ~((fz > 0.44) & (fz < 0.53) & (np.abs(v[:, 0]) < 0.036 * S))
    else:
        m = np.asarray(mask, bool)
    pool = np.nonzero(m)[0]
    rng = np.random.default_rng(seed)
    picks = rng.choice(pool, min(int(n), len(pool)), replace=False)
    ar = mixed_voronoi_area(v, faces)
    nv = vertex_normals(v, faces)
    fr, ct, rm, refused = [], [], [], 0
    for s in picks:
        try:
            r = region_relief(v, faces, geodesic_ball(v, faces, [s], radius_frac, S), stature_m=S, areas=ar, normals=nv)
        except ValueError:
            refused += 1
            continue
        fr.append(abs(r['relief_frac_stature']))
        ct.append(abs(r['contrast']))
        rm.append(r['collar_fit_rms_mm'])
    q = (50, 75, 90, 95, 99)
    out = {
        'n': len(fr),
        'refused': refused,
        'radius_frac': radius_frac,
        'seed': seed,
        'stature_m': S,
        'pool': int(len(pool)),
    }
    for name, a in (('abs_relief_frac', fr), ('abs_contrast', ct), ('collar_fit_rms_mm', rm)):
        a = np.array(a)
        out[name] = {
            'median': float(np.median(a)),
            'max': float(a.max()),
            **{'p%d' % k: float(np.percentile(a, k)) for k in q},
        }
    return out


def mirror_residual(v, faces, mirror_map, values):
    """max/RMS |f(i) - f(mirror(i))| for a per-vertex field — the noise floor for any
    left/right comparison made with it.

    Exists because "the left clavicle reads 0.4 mm deeper than the right" is only a
    statement about the BODY if it is bigger than what the delivered triangulation does to
    a perfectly symmetric cage on its own.
    """
    f = np.asarray(values, np.float64)
    j = np.asarray(mirror_map, np.int64)
    if len(j) != len(f):
        raise ValueError('mirror map has %d entries, field has %d' % (len(j), len(f)))
    d = np.abs(f - f[j])
    ok = np.isfinite(d)
    return {
        'max': float(d[ok].max()) if ok.any() else float('nan'),
        'rms': float(np.sqrt((d[ok] ** 2).mean())) if ok.any() else float('nan'),
        'n_finite': int(ok.sum()),
    }
