# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Primitives, the self-test and the module command line.

Moved verbatim out of the old single-file curvature.py (lines 887-1113).
"""

import numpy as np

from zyg_workflows.geom.form.curvature.topology import (
    DELIVERED_DIAGONAL,
    _face_edges,
    _require,
    curvature,
    delivered_triangles,
)
from zyg_workflows.geom.form.curvature.relief import (
    RELIEF_MIN_CONTRAST,
    RELIEF_MIN_FRAC_STATURE,
    mirror_residual,
    region_relief,
    relief_null,
)


# ---------------------------------------------------------------------------------
# primitives and self-test
# ---------------------------------------------------------------------------------
def _quad_grid(nx, ny, fz):
    """(V,3) and (F,4) for a height field z = fz(x, y) over [-1,1]^2. Open boundary."""
    xs = np.linspace(-1, 1, nx)
    ys = np.linspace(-1, 1, ny)
    X, Y = np.meshgrid(xs, ys, indexing='ij')
    V = np.stack([X.ravel(), Y.ravel(), fz(X, Y).ravel()], axis=1)
    i = np.arange(nx * ny).reshape(nx, ny)
    F = np.stack([i[:-1, :-1].ravel(), i[1:, :-1].ravel(), i[1:, 1:].ravel(), i[:-1, 1:].ravel()], axis=1)
    return V, F


def _cube_sphere(n=16, r=1.0):
    """Closed all-quad sphere: a subdivided cube projected outward. All quads, no poles,
    no boundary — which a UV sphere cannot give without triangle caps."""
    t = np.linspace(-1, 1, n + 1)
    verts, index = [], {}

    def vid(p):
        key = tuple(np.round(p, 9))
        if key not in index:
            index[key] = len(verts)
            verts.append(np.array(p, np.float64))
        return index[key]

    faces = []
    for axis in range(3):
        for s in (-1.0, 1.0):
            # (a, b, axis) is a cyclic triple, so traversing +a then +b gives a normal
            # along +axis. On the s = -1 face outward is -axis, so that quad is reversed.
            a, b = (axis + 1) % 3, (axis + 2) % 3
            corners = ((0, 0), (1, 0), (1, 1), (0, 1))
            if s < 0:
                corners = corners[::-1]
            for i in range(n):
                for j in range(n):
                    quad = []
                    for du, dv in corners:
                        p = [0.0, 0.0, 0.0]
                        p[axis] = s
                        p[a] = t[i + du]
                        p[b] = t[j + dv]
                        quad.append(vid(p))
                    faces.append(quad)
    V = np.array(verts)
    V = r * V / np.linalg.norm(V, axis=1, keepdims=True)
    F = np.array(faces, np.int64)
    tris = delivered_triangles(F)
    de = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    _, cnt = np.unique(np.sort(de, axis=1), axis=0, return_counts=True)
    vol = np.einsum('ij,ij->i', V[tris[:, 0]], np.cross(V[tris[:, 1]], V[tris[:, 2]])).sum() / 6.0
    if not (cnt == 2).all() or vol <= 0:
        raise AssertionError(
            'cube-sphere primitive is not a closed outward-wound quad '
            'mesh (edge counts %s, signed volume %.4f) — the sign test '
            'it exists to run would be meaningless' % (np.bincount(cnt).tolist(), vol)
        )
    return V, F


def self_test(verbose=True):
    """Prove the sign convention and the scale invariance rather than assert them.

    A sphere must be uniformly convex at +1/R, a plane must be zero, a saddle must be
    mixed with a shape index near zero, and a real character scaled uniformly must give an
    identical stature-normalised relief. Raises AssertionError with the measured numbers
    on any failure.
    """
    out = {}

    # The cube-sphere carries 8 valence-3 vertices where a cube corner was, and those are
    # the only places the discrete estimate is poor: measured H*R = 1.994 there against
    # 0.978-1.02 everywhere else, and the shape index bottoms out at 0.609. That is the
    # PRIMITIVE's defect (an irregular vertex star), not the operator's — the medians
    # converge, 1.0074 -> 1.0021 -> 1.0005 in mean H*R for n = 8, 16, 32 — so the test
    # asserts on the median and on uniform convexity, and reports the corners separately.
    for R in (1.0, 0.25):
        V, F = _cube_sphere(16, R)
        c = curvature(V, F)
        H, K = c['mean_H'], c['gaussian_K']
        si = c['shape_index']
        val = np.bincount(_face_edges(F).ravel(), minlength=len(V))
        corner = val == 3
        out['sphere_R%g' % R] = {
            'H_expected': 1.0 / R,
            'H_median_x_R': float(np.median(H) * R),
            'H_mean_x_R': float(H.mean() * R),
            'H_min_x_R': float(H.min() * R),
            'frac_convex': float((H > 0).mean()),
            'K_median_x_R2': float(np.median(K) * R * R),
            'shape_index_median': float(np.nanmedian(si)),
            'shape_index_min': float(np.nanmin(si)),
            'valence3_vertices': int(corner.sum()),
            'H_x_R_at_valence3': float(np.median(H[corner]) * R),
            'H_x_R_max_elsewhere': float(H[~corner].max() * R),
            'H_norm_median': float(np.median(c['mean_H_norm'])),
        }
        _require((H > 0).all(), 'sphere R=%g is not uniformly convex: H_min=%.4f' % (R, H.min()))
        _require(abs(np.median(H) * R - 1) < 0.01, 'sphere R=%g median H*R = %.4f, expected 1' % (R, np.median(H) * R))
        _require(
            (np.nan_to_num(si, nan=1.0) > 0.5).all(),
            'sphere has a vertex reading as saddle or worse: shape index min %.3f' % np.nanmin(si),
        )

    V, F = _quad_grid(31, 31, lambda X, Y: np.zeros_like(X))
    c = curvature(V, F, stature_m=1.0)
    interior = np.isfinite(c['mean_H'])
    out['plane'] = {
        'H_absmax': float(np.abs(c['mean_H'][interior]).max()),
        'K_absmax': float(np.abs(c['gaussian_K'][interior]).max()),
        'n_interior': int(interior.sum()),
        'n_boundary': int(len(c['boundary_vertices'])),
    }
    _require(
        np.abs(c['mean_H'][interior]).max() < 1e-9,
        'plane is not flat: |H|max = %.3e' % np.abs(c['mean_H'][interior]).max(),
    )

    V, F = _quad_grid(41, 41, lambda X, Y: 0.5 * (X * X - Y * Y))
    c = curvature(V, F, stature_m=1.0)
    interior = np.isfinite(c['gaussian_K'])
    si = c['shape_index'][interior]
    out['saddle'] = {
        'K_max': float(c['gaussian_K'][interior].max()),
        'frac_K_negative': float((c['gaussian_K'][interior] < 0).mean()),
        'shape_index_at_centre': float(c['shape_index'][int(np.argmin(np.abs(V[:, 0]) + np.abs(V[:, 1])))]),
        'frac_H_positive': float((c['mean_H'][interior] > 0).mean()),
    }
    _require(
        (c['gaussian_K'][interior] < 0).all(),
        'saddle has non-negative Gaussian curvature somewhere: K_max=%.4f' % c['gaussian_K'][interior].max(),
    )
    _require(
        abs(out['saddle']['shape_index_at_centre']) < 0.05,
        'saddle centre shape index %.3f, expected ~0' % out['saddle']['shape_index_at_centre'],
    )
    _require(
        0.2 < out['saddle']['frac_H_positive'] < 0.8,
        'saddle mean curvature is not mixed: %.2f positive' % out['saddle']['frac_H_positive'],
    )

    # scale invariance on a bump, at the two statures that actually ship
    V, F = _quad_grid(41, 41, lambda X, Y: 0.10 * np.exp(-8.0 * (X * X + Y * Y)))
    grp = np.nonzero(np.abs(V[:, 0]) + np.abs(V[:, 1]) < 0.25)[0]
    r_small = region_relief(V * (1.52 / 2.0), F, grp, stature_m=1.52, gap_frac=0.02, width_frac=0.05)
    r_big = region_relief(V * (1.85 / 2.0), F, grp, stature_m=1.85, gap_frac=0.02, width_frac=0.05)
    out['scale_bump'] = {
        'relief_mm_at_1.52': r_small['relief_mm'],
        'relief_mm_at_1.85': r_big['relief_mm'],
        'frac_at_1.52': r_small['relief_frac_stature'],
        'frac_at_1.85': r_big['relief_frac_stature'],
        'frac_rel_diff': abs(r_small['relief_frac_stature'] - r_big['relief_frac_stature'])
        / abs(r_big['relief_frac_stature']),
        'verdict_1.52': r_small['verdict'],
        'verdict_1.85': r_big['verdict'],
    }
    _require(
        out['scale_bump']['frac_rel_diff'] < 1e-9,
        'stature-normalised relief is not scale invariant: %.3e' % out['scale_bump']['frac_rel_diff'],
    )
    _require(
        r_small['verdict'] == r_big['verdict'] == 'protrusion',
        'the same bump at two statures got verdicts %r and %r' % (r_small['verdict'], r_big['verdict']),
    )

    if verbose:
        for k in sorted(out):
            print(
                '  %-14s %s' % (k, {kk: (round(vv, 6) if isinstance(vv, float) else vv) for kk, vv in out[k].items()})
            )
    return out


def main(argv=None):
    print('=== curvature self-test on primitives ===')
    self_test()

    from zyg_workflows.geom import mesh_skeletons as MS
    from zyg_workflows.geom.anthro import landmarks as LM

    reg = MS._registry()
    print('\n=== curvature on the four issued characters (delivered %s triangulation) ===' % DELIVERED_DIAGONAL)
    mir = LM._mirror(None)
    v0, f0, _ = MS._build_mesh(LM.REF_MALE, None)
    nul = relief_null(np.asarray(v0, np.float64), f0)
    print(
        "\n=== measured relief null over the neutral's torso+limb skin "
        '(n=%d, refused %d, radius %.3f of stature) ===' % (nul['n'], nul['refused'], nul['radius_frac'])
    )
    for k in ('abs_relief_frac', 'abs_contrast', 'collar_fit_rms_mm'):
        print(
            '   %-18s median %.4g  p90 %.4g  p95 %.4g  p99 %.4g  max %.4g'
            % (k, nul[k]['median'], nul[k]['p90'], nul[k]['p95'], nul[k]['p99'], nul[k]['max'])
        )
    print(
        '   shipped defaults: min_frac_stature %.3g (null p95 %.3g), min_contrast %.3g '
        '(null p95 %.3g)'
        % (RELIEF_MIN_FRAC_STATURE, nul['abs_relief_frac']['p95'], RELIEF_MIN_CONTRAST, nul['abs_contrast']['p95'])
    )
    for sec in ('originals', 'derived'):
        for name in reg.get(sec, {}):
            p = reg[sec][name]['params']
            v, faces, _ = MS._build_mesh(p['phenotype'], p.get('local_changes') or None, p.get('bone_scales') or None)
            v = MS._apply_anatomy(v, faces, p.get('anatomy_layer') or {})
            v = np.asarray(v, np.float64)
            c = curvature(v, faces)
            H = c['mean_H']
            print(
                '%-9s stature %.3f  H 1/m [%.1f, %.1f] median %.2f | H*S median %.2f '
                '| convex %.1f%% | umbilic-clamped %d | mirror(H*S) max %.4f rms %.5f'
                % (
                    name,
                    c['stature_m'],
                    H.min(),
                    H.max(),
                    np.median(H),
                    np.median(c['mean_H_norm']),
                    100 * (H > 0).mean(),
                    len(c['umbilic_clamped']),
                    mirror_residual(v, faces, mir, c['mean_H_norm'])['max'],
                    mirror_residual(v, faces, mir, c['mean_H_norm'])['rms'],
                )
            )
    return 0
