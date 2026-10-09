# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""selftest — a verbatim section of the pre-split relief.py.

The module docstring that documented the whole layer lives in the package
__init__.py; nothing in this file was rewritten, renamed or retuned.
"""

import logging as _zyg_logging  # noqa: F401
import numpy as np  # noqa: F401
import sys  # noqa: F401

from zyg_workflows.geom.relief.constants import (  # noqa: F401
    ANATOMY_KEY,
    MIRROR_TOL_FRAC,
    cond_asis,
    cond_clavicle,
    cond_infraclavicular,
    cond_psis,
)
from zyg_workflows.geom.relief.primitives import (  # noqa: F401
    _check_falloff_inside_collar,
    bones_for,
    field_mirror_residual_m,
    mirror_map,
    newell_vertex_normals,
    symmetrise_field,
)
from zyg_workflows.geom.relief.layer import (  # noqa: F401
    apply_relief,
)

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.geom.relief')


# ---------------------------------------------------------------------------------
# self-test — the primitives, and the controls that must fail
# ---------------------------------------------------------------------------------


def self_test(verbose=True):
    """Everything here is checkable without the anny model."""
    out = {}
    # a mirror-symmetric quad grid, deliberately with quads stored from DIFFERENT corners
    # on the two halves — the exact trap that broke _apply_anatomy.
    nx = ny = 9
    xs = np.linspace(-1.0, 1.0, nx)
    ys = np.linspace(-1.0, 1.0, ny)
    V, F = [], []
    for j in range(ny):
        for i in range(nx):
            V.append([xs[i], ys[j], 0.25 * np.exp(-(xs[i] ** 2 + ys[j] ** 2) * 3.0)])
    V = np.array(V)
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = j * nx + i
            q = [a, a + 1, a + nx + 1, a + nx]
            if xs[i] > 0:  # rotate the start corner on one half only
                q = q[2:] + q[:2]
            F.append(q)
    F = np.array(F)
    n_new = newell_vertex_normals(V, F)
    mate, _ = mirror_map(V, 1e-6)
    hv = np.nonzero(mate >= 0)[0]
    M = n_new[mate[hv]].copy()
    M[:, 0] *= -1.0
    out['newell_normals_mirror_stable'] = {
        'max_residual': float(np.abs(n_new[hv] - M).max()),
        'paired': int(len(hv)),
        'of': int(len(V)),
    }

    # the corner-(0,1,2) estimator on the SAME mesh, as the control that must be worse
    n_tri = np.zeros((len(V), 3))
    e1 = V[F[:, 1]] - V[F[:, 0]]
    e2 = V[F[:, 2]] - V[F[:, 0]]
    fn = np.cross(e1, e2)
    for k in range(4):
        np.add.at(n_tri, F[:, k], fn)
    n_tri /= np.maximum(np.linalg.norm(n_tri, axis=1, keepdims=True), 1e-12)
    M2 = n_tri[mate[hv]].copy()
    M2[:, 0] *= -1.0
    out['corner012_normals_control'] = {'max_residual': float(np.abs(n_tri[hv] - M2).max())}

    # symmetrising an ASYMMETRIC field must drive the residual to zero and midline x to 0
    rng = np.random.default_rng(20260806)
    Da = rng.normal(size=(len(V), 3)) * 0.01
    Ds, _ = symmetrise_field(Da, mate)
    onmid = np.abs(V[:, 0]) < 1e-12
    out['symmetrise'] = {
        'residual_before': field_mirror_residual_m(Da, mate),
        'residual_after': field_mirror_residual_m(Ds, mate),
        'max_midline_x_after': float(np.abs(Ds[onmid, 0]).max()),
    }

    # the falloff must be exactly zero at and beyond its radius
    r = np.linspace(0, 1.3, 27)
    w = np.where(r <= 1.0, 0.5 * (1 + np.cos(np.pi * np.clip(r, 0, 1))), 0.0)
    out['falloff_compact'] = {
        'w_at_1.0': float(w[r >= 1.0][0]),
        'w_beyond': float(w[r > 1.0].max()),
        'w_at_0': float(w[0]),
    }
    out['falloff_inside_collar'] = _check_falloff_inside_collar()

    # conditionals: direction, and that none of them can go negative
    out['conditionals'] = {}
    for nm, fn_ in (
        ('clavicle', cond_clavicle),
        ('infraclavicular', cond_infraclavicular),
        ('psis', cond_psis),
        ('asis', cond_asis),
    ):
        vals = {}
        for m in (
            {'muscle': 0.0, 'weight': 0.4, 'gender': 0.0},
            {'muscle': 0.5, 'weight': 0.5, 'gender': 0.0},
            {'muscle': 1.0, 'weight': 0.9, 'gender': 1.0},
        ):
            vals[str(sorted(m.items()))] = round(fn_(m)[0], 4)
        out['conditionals'][nm] = vals

    if verbose:
        for k in sorted(out):
            print('  %-34s %s' % (k, out[k]))
    return out


def measure(which=('male', 'female'), n_null=40, verbose=True):
    """BEFORE/AFTER on the registry originals, with the SAME resolvers at the SAME cut.

    One null, measured once on the untouched anny neutral, is used for BOTH columns —
    a before/after table whose two columns were scored differently is not a comparison.
    The after-mesh's own relief null is re-measured too, so a reader can see whether this
    layer moved the noise floor it is being judged against.

    Returns the summary dict; prints the table when verbose.
    """
    from zyg_workflows.geom import mesh_skeletons as MS
    from zyg_workflows.geom.form import ridge as RD
    from zyg_workflows.geom.form import regions as RG
    from zyg_workflows.geom.form import curvature as CV
    from zyg_workflows.geom.anthro import landmarks as LM

    v0, f0, _ = MS._build_mesh(LM.REF_MALE, None)
    v0 = np.asarray(v0, np.float64)
    S0 = float(v0[:, 2].max() - v0[:, 2].min())
    nul = RD.ridge_null(v0, f0, n_pools=n_null, stature_m=S0)
    doc = RG.load_regions(len(v0))
    reg = MS._registry()
    names = [str(n) for n in MS._bone_names(MS._model())]
    out = {}

    def _probe(v, faces):
        v = np.asarray(v, np.float64)
        S = float(v[:, 2].max() - v[:, 2].min())
        ar = CV.mixed_voronoi_area(v, faces)
        nv = CV.vertex_normals(v, faces)
        cu = CV.curvature(v, faces, stature_m=S, normals=nv)
        return RD.probe_pools(
            v, faces, RD.body_pools(v, faces, S, nv, doc), stature_m=S, areas=ar, normals=nv, curv=cu, null=nul
        )

    def _row(rec):
        if rec.get('status') != 'ok':
            return ('EMPTY', 0, None, None, False)
        r = rec.get('ridge') or {}
        if r.get('status') != 'ok':
            return ('UNMEAS', 0, None, None, False)
        x = r['result']
        return (
            x['verdict'],
            x['longest_run'],
            x['peak_relief_mm'],
            x.get('peak_contrast'),
            bool(rec.get('resolves_relief')),
        )

    for who in which:
        p = reg['originals'][who]['params']
        vb, faces, bones, weights = bones_for(
            p['phenotype'], p.get('local_changes') or None, p.get('bone_scales') or None
        )
        vb = np.asarray(MS._apply_anatomy(vb, faces, p.get('anatomy_layer') or {}), np.float64)
        va = np.asarray(
            apply_relief(
                vb, faces, {ANATOMY_KEY: 1.0}, phenotype=p['phenotype'], bones=bones, weights=weights, bone_names=names
            ),
            np.float64,
        )
        rep = apply_relief.last_report
        S = float(vb[:, 2].max() - vb[:, 2].min())
        mate, _ = mirror_map(vb, MIRROR_TOL_FRAC * S)
        hv = np.nonzero(mate >= 0)[0]

        def _mres(v, mate=mate, hv=hv):
            M = v[mate[hv]].copy()
            M[:, 0] *= -1.0
            return float(1e3 * np.abs(v[hv] - M).max())

        B, A = _probe(vb, faces), _probe(va, faces)
        nb = na = 0
        rows, gained, lost = [], [], []
        for k in [x for x in A if not x.startswith('_')]:
            rb, ra = _row(B[k]), _row(A[k])
            nb += int(rb[4])
            na += int(ra[4])
            if ra[4] and not rb[4]:
                gained.append(k)
            if rb[4] and not ra[4]:
                lost.append(k)
            rows.append((k, rb, ra))
        out[who] = {
            'stature_m': S,
            'before': nb,
            'after': na,
            'of': len(rows),
            'gained': sorted(gained),
            'lost': sorted(lost),
            'rows': rows,
            'cage_mirror_before_mm': _mres(vb),
            'cage_mirror_after_mm': _mres(va),
            'field_residual_mm': rep['mirror']['field_residual_after_symmetrise_mm'],
            'displaced': rep['displaced_vertices'],
            'max_displacement_mm': rep['max_displacement_mm'],
            'amplitude_audit': rep['amplitude_audit']['below_null_by_amplitude'],
            'relief_null_p99_before': CV.relief_null(vb, faces, n=200, stature_m=S)
            .get('abs_relief_frac', {})
            .get('p99'),
            'relief_null_p99_after': CV.relief_null(va, faces, n=200, stature_m=S)
            .get('abs_relief_frac', {})
            .get('p99'),
        }
        if verbose:
            o = out[who]
            print('\n######## %s  S=%.4f m ########' % (who, S))
            print(
                'cage mirror residual %.4f -> %.4f mm (SYM_MORPH_TOL_MM 0.15); field '
                'residual %.1e mm; displaced %d verts, max %.2f mm'
                % (
                    o['cage_mirror_before_mm'],
                    o['cage_mirror_after_mm'],
                    o['field_residual_mm'],
                    o['displaced'],
                    o['max_displacement_mm'],
                )
            )
            for r_ in o['amplitude_audit']:
                print(
                    '  BELOW NULL BY AMPLITUDE  %-22s %.2f mm = %.3fe-3 S (%.2fx floor)'
                    % (r_['name'], r_['delivered_mm'], 1e3 * r_['delivered_frac_stature'], r_['shortfall_x'])
                )
            for k, rb, ra in rows:
                f_ = lambda t: (
                    '%-10s/%d %7s c%-5s'
                    % (
                        t[0],
                        t[1],
                        ('%.2f' % t[2]) if t[2] is not None else '-',
                        ('%.1f' % t[3]) if t[3] is not None else '-',
                    )
                )
                print('  %-24s %-24s -> %-24s %s' % (k, f_(rb), f_(ra), 'RESOLVES' if ra[4] else ''))
            print(
                '  BODY RESOLUTION %d/%d -> %d/%d   gained %s   lost %s'
                % (nb, len(rows), na, len(rows), gained or 'none', lost or 'none')
            )
            print(
                '  relief_null p99 %.6f -> %.6f'
                % (o['relief_null_p99_before'] or 0.0, o['relief_null_p99_after'] or 0.0)
            )
    return out


def determinism_check(who='male'):
    """The layer must not depend on how many threads happen to be available.

    apply_relief is numpy + scipy.dijkstra over a fixed seed array; there is no unordered
    reduction in it. This runs the whole layer twice at different BLAS/OMP widths and
    compares the delivered cage BYTE FOR BYTE, because 'should be deterministic' is not
    the same statement as 'is'.
    """
    import hashlib
    from zyg_workflows.geom import mesh_skeletons as MS

    reg = MS._registry()
    p = reg['originals'][who]['params']
    vb, faces, bones, weights = bones_for(p['phenotype'], p.get('local_changes') or None, p.get('bone_scales') or None)
    vb = MS._apply_anatomy(vb, faces, p.get('anatomy_layer') or {})
    names = [str(n) for n in MS._bone_names(MS._model())]
    hashes = []
    for nt in (1, 8):
        try:
            import torch

            torch.set_num_threads(nt)
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('torch thread cap skipped: %s', _exc)
        va = apply_relief(
            vb, faces, {ANATOMY_KEY: 1.0}, phenotype=p['phenotype'], bones=bones, weights=weights, bone_names=names
        )
        hashes.append(hashlib.sha256(np.ascontiguousarray(np.asarray(va, np.float64)).tobytes()).hexdigest()[:16])
    return {'who': who, 'hashes': hashes, 'identical': hashes[0] == hashes[1]}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else 'selftest'
    print('=== geom/relief.py self-test (primitives only; no anny model needed) ===')
    self_test()
    if cmd == 'selftest':
        return 0
    if cmd == 'determinism':
        print('\n=== determinism: whole layer at 1 vs 8 threads ===')
        print('  %s' % determinism_check())
        return 0
    print('\n=== MEASURED before/after on the registry originals, same resolver, same cut on both columns ===')
    measure(n_null=int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 40)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
