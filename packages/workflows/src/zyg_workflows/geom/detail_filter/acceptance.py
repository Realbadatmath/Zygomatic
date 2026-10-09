# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The model-based separator and the acceptance test (sweep, transfer curve, CLI).

Verbatim from the single-file geom/detail_filter.py: lines 868-1086 — THE
MODEL-BASED SEPARATOR, THE ACCEPTANCE TEST and main().
"""

from __future__ import annotations

import argparse
import json
import math
import numpy as np
import logging as _zyg_logging

from zyg_workflows.geom.detail_filter.operators import (
    DETAIL_EDGE_FRAC,
    DetailFilterError,
    LEGACY_CUTOFF_FRAC,
    LEGACY_SWEEP_MULTIPLES,
    PROPORTION_EDGE_FRAC,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.geom.detail_filter')


# ----------------------------------------------------------------------------------
# THE MODEL-BASED SEPARATOR
# ----------------------------------------------------------------------------------


def morph_keep(basis, X, ridge=0.0):
    """Remove everything the morph basis can express. What is left is not proportion.

    `basis` is (nv*3, m): each column is the cage displacement produced by moving one
    anny parameter. Those columns SPAN proportion by construction -- they are the only
    ways this model knows how to change a body's shape. So the least-squares projection

        X_keep = X - B (B^T B)^-1 B^T X

    removes proportion exactly, with no transition band and no cutoff, because there is no
    frequency axis involved. The price is that it removes whatever else the basis happens
    to span too, which is why sweep() measures it on the same probes as the filters instead
    of taking the argument on trust.

    ridge > 0 adds Tikhonov damping for a rank-deficient basis (anny's macros are not
    independent -- gender and muscle both move the shoulders).
    """
    X = np.asarray(X, np.float64)
    flat = X.ndim == 1
    x = X.reshape(-1) if flat else X.reshape(-1)
    B = np.asarray(basis, np.float64)
    if B.shape[0] != x.shape[0]:
        raise DetailFilterError('basis rows %d != field size %d' % (B.shape[0], x.shape[0]))
    G = B.T @ B
    if ridge:
        G = G + float(ridge) * np.eye(G.shape[0]) * float(np.trace(G) / max(G.shape[0], 1))
    coef, *_ = np.linalg.lstsq(G, B.T @ x, rcond=None)
    r = x - B @ coef
    return (r if flat else r.reshape(X.shape)), {
        'm_basis': int(B.shape[1]),
        'ridge': float(ridge),
        'coef_norm': float(np.linalg.norm(coef)),
    }


# ----------------------------------------------------------------------------------
# THE ACCEPTANCE TEST
# ----------------------------------------------------------------------------------

PROBE_LIVE_FRAC = 1e-6  # see _probe_is_live
NYQUIST_EDGES_PER_WAVE = 2.5  # see probe_floor_m


def _probe_is_live(energy, M):
    """Is this probe actually varying, or is the mesh flat along this axis?

    THE TRAP THIS CLOSES, found by unit-testing on a planar grid. The probe is
    cos(2*pi*p[ax]/lambda) evaluated at vertex positions. If the mesh has no extent along
    axis `ax` the probe is CONSTANT, the mean subtraction annihilates it, and the ratio
    becomes 0/0. Guarded with max(den, tiny) it silently returns 0 -- and averaging that
    structural zero into the other two axes scales every reported number by 2/3 without
    any warning. Measured: a flat grid reported a Rayleigh ratio of 0.665 where the
    stencil was verified exact at 1.0000, purely from this.

    A body is not flat in any direction so this never fires in production, which is
    exactly why it has to be a hard skip with a reported axis list rather than a fudge:
    the one place it DOES fire is the unit test that proves the operator correct.
    """
    return float(energy) > PROBE_LIVE_FRAC * float(M.sum())


def probe_floor_m(mean_edge_m):
    """Shortest wavelength this mesh can carry a probe at.

    Below ~2.5 samples per wavelength the probe is aliased: its Rayleigh quotient exceeds
    lambda_max, so it sits OUTSIDE the Chebyshev domain [0, lambda_max] and the three-term
    recurrence diverges (measured: a 1.6-sample probe returned -1.4e20). That is not a
    filter defect, it is a question the mesh cannot be asked. Probing there and reporting
    the result would be reporting noise as a transfer function.
    """
    return float(NYQUIST_EDGES_PER_WAVE) * float(mean_edge_m)


def _probe_kept(sep, v, lam, M=None, mean_edge_m=None):
    """Fraction of a wavelength-lam plane wave that SURVIVES the separator.

    Same instrument as scan_ingest._probe_response, so old and new numbers are comparable:
    a cosine at vertex positions, three axes, RMS ratio. Area-weighted when a mass matrix
    is available, because an unweighted RMS over an irregular mesh over-counts dense
    regions -- which is FAULT 1 leaking into the measurement of FAULT 1.
    """
    if mean_edge_m is not None and lam < probe_floor_m(mean_edge_m):
        raise DetailFilterError(
            'lambda=%.5g m is below the probe floor %.5g m (%.2f edges per wavelength at '
            'mean edge %.5g m). The mesh cannot carry this probe; subdivide or drop the '
            'point rather than reporting an aliased number.'
            % (lam, probe_floor_m(mean_edge_m), lam / mean_edge_m, mean_edge_m)
        )
    out, used = [], []
    for ax in range(3):
        f = np.cos(2.0 * math.pi * v[:, ax] / lam)
        F = np.zeros((v.shape[0], 3), np.float64)
        F[:, ax] = f  # a displacement along that axis
        a = F[:, ax] - f.mean()
        w = None if M is None else M / M.sum()
        den2 = float((a * a).mean()) if w is None else float((w * a * a).sum())
        if not _probe_is_live(den2 * (1.0 if M is None else M.sum()), M if M is not None else np.ones(v.shape[0])):
            continue
        R = sep(F)
        if isinstance(R, tuple):
            R = R[0]
        b = R[:, ax] - R[:, ax].mean()
        num2 = float((b * b).mean()) if w is None else float((w * b * b).sum())
        out.append(math.sqrt(num2) / math.sqrt(den2))
        used.append(ax)
    if not out:
        raise DetailFilterError('no live probe axis at lambda=%g m' % lam)
    return float(np.mean(out)), [float(x) for x in out], used


def sweep(sep, v, stature_m, M=None, extra_multiples=(), mean_edge_m=None):
    """Measure a separator at the operating edges AND at scan_ingest's kinder window.

    OPERATING_* is the number that decides usability: reject at 0.18 S, pass at 0.05 S,
    a factor of 3.6. LEGACY_* reproduces the 4x/0.25x window scan_ingest scored itself in
    so the comparison is like for like. Reporting only the legacy window would flatter
    every separator here, including the one being replaced.
    """
    S = float(stature_m)
    lam_prop = PROPORTION_EDGE_FRAC * S
    lam_det = DETAIL_EDGE_FRAC * S
    lam_cut = LEGACY_CUTOFF_FRAC * S

    pts = {
        'proportion_edge_0.18S': lam_prop,
        'detail_edge_0.05S': lam_det,
        'legacy_cutoff_0.08S': lam_cut,
        'legacy_4x': lam_cut * LEGACY_SWEEP_MULTIPLES[0],
        'legacy_0.25x': lam_cut * LEGACY_SWEEP_MULTIPLES[1],
    }
    for m in extra_multiples:
        pts['x%.3g' % m] = lam_cut * float(m)

    res, skipped = {}, {}
    for name, lam in pts.items():
        try:
            kept, per_axis, used = _probe_kept(sep, v, lam, M=M, mean_edge_m=mean_edge_m)
        except DetailFilterError as e:
            # A point the mesh cannot carry is recorded as unmeasurable, never as a value.
            skipped[name] = {'lambda_m': float(lam), 'reason': str(e)}
            continue
        res[name] = {'lambda_m': float(lam), 'kept': kept, 'per_axis': per_axis, 'axes_used': used}
    missing = [k for k in ('proportion_edge_0.18S', 'detail_edge_0.05S', 'legacy_4x', 'legacy_0.25x') if k not in res]
    if missing:
        raise DetailFilterError(
            'the mesh cannot carry these scoring points: %s. Raise the '
            'subdivision level; do not score without them.' % missing
        )

    leak = res['proportion_edge_0.18S']['kept']
    pas = res['detail_edge_0.05S']['kept']
    lk4 = res['legacy_4x']['kept']
    lk025 = res['legacy_0.25x']['kept']
    return {
        'points': res,
        'unmeasurable': skipped,
        'operating_leakage': leak,
        'operating_passage': pas,
        'operating_selectivity': pas / max(leak, 1e-12),
        'legacy_leakage_4x': lk4,
        'legacy_passage_0.25x': lk025,
        'legacy_selectivity': lk025 / max(lk4, 1e-12),
    }


def transfer_curve(sep, v, stature_m, M=None, n=24, lo_frac=0.01, hi_frac=0.60, mean_edge_m=None):
    """The whole response, not just the edges, so the shape can be looked at."""
    S = float(stature_m)
    lams = np.geomspace(lo_frac * S, hi_frac * S, int(n))
    out = []
    for lam in lams:
        try:
            kept, _, used = _probe_kept(sep, v, float(lam), M=M, mean_edge_m=mean_edge_m)
        except DetailFilterError as _exc:
            _zyg_log.debug('transfer curve probe skipped at this wavelength: %s', _exc)
            continue
        out.append({'lambda_m': float(lam), 'lambda_frac_S': float(lam / S), 'kept': kept, 'axes_used': used})
    return out


def _jsonable(o):
    if isinstance(o, dict):
        return {k: _jsonable(x) for k, x in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(x) for x in o]
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    return o


def main(argv=None):
    ap = argparse.ArgumentParser(prog='geom.detail_filter')
    ap.add_argument('cmd', choices=['selftest', 'compare'])
    ap.add_argument('--who', default='female')
    ap.add_argument('--level', type=int, default=1)
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv)
    if a.cmd == 'selftest':
        from zyg_workflows.geom.detail_filter_measure import self_test

        r = self_test(level=a.level)
    else:
        from zyg_workflows.geom.detail_filter_measure import compare

        r = compare(who=a.who, level=a.level)
    txt = json.dumps(_jsonable(r), indent=2)
    if a.out:
        with open(a.out, 'w') as fh:
            fh.write(txt)
    print(txt)
    return 0
