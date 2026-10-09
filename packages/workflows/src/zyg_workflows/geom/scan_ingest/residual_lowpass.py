# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The umbrella low-pass operator and its self-calibration, for STAGE e.

Moved out of `residual.py` on 2026-10-09, unchanged. These are the primitives
`stage_residual` builds on: the valence-normalised adjacency operator, the heat-kernel
iteration estimate and its guard, the diffusion step itself, and the measurement loop
that calibrates the estimate against what the operator really does on THIS mesh.

`residual.py` re-exports all seven names, so `zyg_workflows.geom.scan_ingest`'s existing
import block keeps resolving.
"""

import math

import numpy as np

from zyg_workflows.geom.scan_ingest.constants import (
    CALIBRATION_MAX_ROUNDS,
    CALIBRATION_TOL,
    LOWPASS_ALPHA,
    LOWPASS_ITER_GUARD_MULT,
    LOWPASS_ITER_HARD_CAP,
    ScanIngestError,
)


def _adjacency(nv, faces):
    """Sparse valence-normalised umbrella operator A (rows sum to 1) over the mesh graph."""
    from scipy.sparse import coo_matrix

    faces = np.asarray(faces)
    n = faces.shape[1]
    I, J = [], []
    for i in range(n):
        a, b = faces[:, i], faces[:, (i + 1) % n]
        I.append(a)
        J.append(b)
        I.append(b)
        J.append(a)
    I = np.concatenate(I)
    J = np.concatenate(J)
    W = np.ones(len(I))
    A = coo_matrix((W, (I, J)), shape=(nv, nv)).tocsr()
    A.data[:] = 1.0
    deg = np.asarray(A.sum(axis=1)).ravel()
    deg[deg == 0] = 1.0
    from scipy.sparse import diags

    return diags(1.0 / deg) @ A


def _lowpass_iters(h, lam_cut, alpha=LOWPASS_ALPHA, target=0.5):
    """How many umbrella-diffusion steps put wavelength lam_cut at `target` amplitude.

    On a locally regular graph with mean edge length h, the neighbour average of a mode
    cos(2*pi*x/lam) returns cos(2*pi*h/lam) times the mode, so one step of
    x <- x + alpha*(A x - x) multiplies that mode by

        mu(lam) = 1 - alpha * (1 - cos(2*pi*h/lam))

    and n steps by mu^n. Solving mu^n = target gives n. This is the standard heat-kernel
    argument and it is an APPROXIMATION on an irregular mesh — which is why
    stage_residual then MEASURES the achieved attenuation at lam_cut on the actual mesh
    and reports it instead of trusting this number.
    """
    x = 2.0 * math.pi * h / lam_cut
    mu = 1.0 - alpha * (1.0 - math.cos(x))
    if not (0.0 < mu < 1.0):
        raise ScanIngestError(
            'the requested cutoff wavelength %.4g m is not representable on a mesh with '
            'mean edge %.4g m (per-step gain %.4f). The mesh cannot carry it: raise the '
            'subdivision level rather than the cutoff.' % (lam_cut, h, mu)
        )
    n = int(math.ceil(math.log(target) / math.log(mu)))
    return max(1, min(n, _iter_ceiling(n))), mu


def _iter_ceiling(analytic_n):
    """The iteration guard for a mesh whose analytic estimate is `analytic_n`.

    Scales with the mesh so it cannot bind on a legitimate resolution (see
    LOWPASS_ITER_GUARD_MULT), and is still bounded absolutely so a degenerate mesh cannot
    ask for an unbounded run."""
    return int(min(LOWPASS_ITER_HARD_CAP, max(1, LOWPASS_ITER_GUARD_MULT * int(max(1, analytic_n)))))


def _smooth(A, x, iters, alpha=LOWPASS_ALPHA):
    """`iters` umbrella-diffusion steps. `x` may be (n,) or (n, k) — a matrix of k fields is
    smoothed in ONE pass of sparse matvecs rather than k passes, which is what makes the
    converged iteration counts at subdivision 2 and 3 affordable."""
    y = np.asarray(x, np.float64).copy()
    for _ in range(iters):
        y += alpha * (A @ y - y)
    return y


def _rms0(x):
    """RMS about the mean, column-wise on a 2-D array."""
    x = np.asarray(x, np.float64)
    return np.sqrt(((x - x.mean(axis=0, keepdims=True)) ** 2).mean(axis=0))


def _probe_response(A, P, lam, iters):
    """What the low-pass AND the residual do to a wavelength-lam sinusoid, on THIS mesh.

    Returns (lowpass_ratio, per_axis_lowpass, residual_ratio, per_axis_residual).

    BOTH are measured, and the second is not derivable from the first. `1 - lowpass_ratio`
    is what this module used to report as the amplitude kept by the residual, and that
    identity holds only if the low-pass output is a scalar multiple of its input. On an
    irregular mesh it is not: the operator changes the shape of the field as well as its
    amplitude, so f - g retains more than the amplitude arithmetic suggests. MEASURED on the
    level-1 female cage at the calibrated 2,969 iterations, at 4x the cutoff (537.6 mm —
    unambiguously a proportion), `1 - r` reads 0.295 while the residual really carries 0.549.
    Reporting the algebra instead of the measurement understated proportion leakage by 1.86x.

    Averaged over the three coordinate directions because the mesh is anisotropic: the
    umbrella operator's effective step along any one axis is shorter than the mean edge
    length, which is exactly why the analytic iteration count under-smooths.
    """
    F = np.cos(2.0 * math.pi * np.asarray(P, np.float64)[:, :3] / lam)  # (n, 3)
    G = _smooth(A, F, iters)
    den = np.maximum(_rms0(F), 1e-12)
    lp = _rms0(G) / den
    rs = _rms0(F - G) / den
    return (float(lp.mean()), [float(x) for x in lp], float(rs.mean()), [float(x) for x in rs])


def _calibrate_lowpass(A, P, h, lam_cut, target=0.5):
    """Iteration count that puts lam_cut at `target` amplitude ON THIS MESH.

    _lowpass_iters gives the heat-kernel estimate; MEASURED on the subdivided female cage
    that estimate left the cutoff wavelength at 0.847 amplitude instead of 0.5, i.e. it
    under-smoothed by a large factor, because the graph's effective step along any single
    axis is shorter than the mean edge length. Attenuation is only APPROXIMATELY geometric
    in the iteration count, so the obvious one-shot correction n' = n*ln(target)/ln(r) is
    not enough: MEASURED on the subdivided female cage it moved 0.840 to 0.732, still well
    short of 0.5. The secant-style step is therefore REPEATED until the measured response
    is within CALIBRATION_TOL of the target, and the number of rounds taken is reported.

    This is calibrating a filter against its own stated cutoff using a synthetic sinusoid
    on the mesh — it is NOT moving a threshold to make an asset pass. No scan data enters
    it. The cutoff wavelength itself (RESIDUAL_CUTOFF_FRAC) never moves; only the iteration
    count needed to realise it does.
    """
    n0, mu = _lowpass_iters(h, lam_cut, target=target)
    ceiling = _iter_ceiling(n0)
    r0, _, _, _ = _probe_response(A, P, lam_cut, n0)
    n, r = n0, r0
    rounds, history = 0, [{'iterations': n0, 'response': r0}]
    while rounds < CALIBRATION_MAX_ROUNDS and abs(r - target) > CALIBRATION_TOL:
        if not (0.0 < r < 1.0):
            break
        n_next = int(max(1, min(ceiling, round(n * math.log(target) / math.log(r)))))
        if n_next == n:
            break
        n = n_next
        r, per_axis, _, _ = _probe_response(A, P, lam_cut, n)
        rounds += 1
        history.append({'iterations': n, 'response': r})
    r1, per_axis, res1, res_axis = _probe_response(A, P, lam_cut, n)
    return n, {
        'analytic_iterations': n0,
        'analytic_per_step_gain': mu,
        'analytic_response_at_cutoff': r0,
        'calibrated_iterations': n,
        'calibrated_response_at_cutoff': r1,
        'calibrated_response_per_axis': per_axis,
        'calibrated_residual_at_cutoff': res1,
        'calibrated_residual_per_axis': res_axis,
        'target_response_at_cutoff': target,
        'calibration_rounds': rounds,
        'calibration_history': history,
        'iteration_ceiling': int(ceiling),
        'iteration_ceiling_rule': 'LOWPASS_ITER_GUARD_MULT x the analytic estimate '
        'for THIS mesh (%d x %d), capped at %d' % (LOWPASS_ITER_GUARD_MULT, n0, LOWPASS_ITER_HARD_CAP),
        'converged': bool(abs(r1 - target) <= CALIBRATION_TOL),
        'hit_iteration_ceiling': bool(n >= ceiling),
    }
