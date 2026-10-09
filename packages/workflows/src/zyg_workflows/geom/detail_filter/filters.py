# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Spectrum/wavelength conversion, the target response and the filter families.

Verbatim from the single-file geom/detail_filter.py: lines 329-866 — SPECTRUM <->
WAVELENGTH, THE TARGET RESPONSE and FILTER FAMILIES.
"""

from __future__ import annotations

import math
import time
import numpy as np
from scipy.sparse import diags

from zyg_workflows.geom.detail_filter.operators import (
    CHEBY_DEGREE_MAX,
    CHEBY_DEGREE_MIN,
    CHEBY_DEGREE_SAFETY,
    DetailFilterError,
    LMAX_ITERS,
    LMAX_MARGIN,
    LMAX_TOL,
)

from zyg_workflows.geom.detail_filter.acceptance import _probe_is_live


# ----------------------------------------------------------------------------------
# SPECTRUM <-> WAVELENGTH
# ----------------------------------------------------------------------------------


def eig_from_wavelength(lam_m):
    """Laplace-Beltrami eigenvalue of a plane wave of wavelength lam_m (metres).

    -div grad cos(2*pi*x/L) = (2*pi/L)^2 cos(2*pi*x/L). Only meaningful for the cotan
    operator; the umbrella operator has no length scale in it at all.
    """
    return (2.0 * math.pi / float(lam_m)) ** 2


def wavelength_from_eig(k):
    k = float(k)
    if k <= 0:
        return float('inf')
    return 2.0 * math.pi / math.sqrt(k)


def rayleigh_check(op, v, wavelengths_m):
    """Does the operator actually put a wavelength where the theory says?

    Measures the Rayleigh quotient f'Kf / f'Mf for a plane wave at each wavelength and
    compares it to (2*pi/L)^2. This is the one assumption the whole wavelength-to-
    eigenvalue mapping rests on, so it is MEASURED on the real mesh rather than asserted.
    A ratio near 1 means a wavelength means what we say it means. Averaged over the three
    coordinate directions because a body is not isotropic.
    """
    K, M = op['K'], op['M']
    out = []
    for lam in wavelengths_m:
        per_axis, used = [], []
        for ax in range(3):
            f = np.cos(2.0 * math.pi * v[:, ax] / lam)
            f = f - (M * f).sum() / M.sum()  # drop the constant mode
            den = float((M * f * f).sum())
            if not _probe_is_live(den, M):
                continue  # see _probe_is_live
            per_axis.append(float(f @ (K @ f)) / den)
            used.append(ax)
        if not per_axis:
            raise DetailFilterError(
                'no axis carries a live probe at lambda=%g m -- the geometry is degenerate '
                'in every direction at this wavelength' % lam
            )
        meas = float(np.mean(per_axis))
        pred = eig_from_wavelength(lam)
        out.append(
            {
                'lambda_m': float(lam),
                'measured_eig': meas,
                'predicted_eig': pred,
                'ratio': meas / pred,
                'per_axis': [float(x) for x in per_axis],
                'axes_used': used,
            }
        )
    return out


def lambda_max(op, iters=LMAX_ITERS, tol=LMAX_TOL, seed=0):
    """Largest eigenvalue of the symmetrised operator, by power iteration.

    The Chebyshev domain must CONTAIN the spectrum: too large only costs degree, too small
    makes the three-term recurrence diverge. Hence LMAX_MARGIN on the way out.
    """
    Lsym = op['Lsym']
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(op['nv'])
    x /= np.linalg.norm(x)
    lam = 0.0
    for _ in range(iters):
        y = Lsym @ x
        ny = float(np.linalg.norm(y))
        if ny <= 0:
            break
        x = y / ny
        new = float(x @ (Lsym @ x))
        if abs(new - lam) <= tol * max(abs(new), 1e-30):
            lam = new
            break
        lam = new
    return float(lam) * LMAX_MARGIN


# ----------------------------------------------------------------------------------
# THE TARGET RESPONSE
# ----------------------------------------------------------------------------------


def band_response(k, k_pass, k_stop, sharpness=1.0):
    """Desired KEEP fraction as a function of Laplace-Beltrami eigenvalue.

    Long wavelength = small eigenvalue = proportion = reject (0).
    Short wavelength = large eigenvalue = detail = keep (1).
    Raised cosine in log-eigenvalue between the two edges, because a hard step rings
    (Gibbs) at any finite polynomial degree and the ringing lands in the passband as
    negative gain -- which would subtract real relief.

    k_stop  eigenvalue at PROPORTION_EDGE_FRAC * S   (reject at and below)
    k_pass  eigenvalue at DETAIL_EDGE_FRAC * S       (keep at and above)
    """
    k = np.asarray(k, np.float64)
    lo, hi = float(k_stop), float(k_pass)
    if not (hi > lo > 0):
        raise DetailFilterError('band edges must satisfy 0 < k_stop < k_pass, got %g %g' % (lo, hi))
    out = np.zeros_like(k)
    out[k >= hi] = 1.0
    mid = (k > lo) & (k < hi)
    if np.any(mid):
        t = (np.log(k[mid]) - math.log(lo)) / (math.log(hi) - math.log(lo))
        t = np.clip(t, 0.0, 1.0) ** float(sharpness)
        out[mid] = 0.5 - 0.5 * np.cos(math.pi * t)
    return out


def cheby_degree_for(lmax, k_stop, k_pass, safety=CHEBY_DEGREE_SAFETY):
    """Degree needed to resolve a transition of width (k_pass - k_stop) inside [0, lmax].

    A degree-d Chebyshev expansion on [0, lmax] resolves features of width ~ lmax/d, and
    the transition here sits at the very bottom of the spectrum -- on a subdivided body
    mesh the band edges are a fraction of a percent of lmax.

    THIS ESTIMATE IS MEASURED TO BE ABOUT 20x TOO CONSERVATIVE, and the number it returns
    should be read as an upper bound rather than a requirement. At subdivision level 1 it
    asks for degree 58,767; the sweep at that degree and at the capped 3,000 returned
    IDENTICAL numbers to four decimals -- leak 0.0896, pass 0.8492, selectivity 9.48 -- for
    3,649 s against 26 s. The formula assumes BRICK-WALL resolution, and band_response()
    deliberately is not one: its raised-cosine transition is smooth in log-eigenvalue, and
    a smooth target needs far fewer terms than a step. CHEBY_DEGREE_MAX is therefore doing
    real work rather than compromising accuracy, and hitting the cap is not a warning.

    That measurement also retires a claim this module made earlier. "Polynomial filters
    cannot scale here, degree ~179,000 at level 2, infeasible" was wrong twice over: wrong
    on hardware (a 4090 does 179,000 fp64 SpMVs in ~46 s) AND wrong on the degree, which
    was never needed. Butterworth is still the better separator -- 10.62 against 9.48 on
    the same probe -- but that gap is a property of the two filters, NOT of the degree cap,
    which is what this run was written to find out.
    """
    width = max(float(k_pass) - float(k_stop), 1e-12)
    d = int(math.ceil(safety * float(lmax) / width))
    return int(min(max(d, CHEBY_DEGREE_MIN), CHEBY_DEGREE_MAX))


def cheby_coeffs(response_fn, degree, lmax, n_quad=None):
    """Chebyshev coefficients of response_fn on [0, lmax]."""
    n = int(n_quad or max(4 * degree, 256))
    j = np.arange(n)
    theta = math.pi * (j + 0.5) / n
    x = np.cos(theta)  # in [-1, 1]
    k = 0.5 * lmax * (x + 1.0)  # mapped to [0, lmax]
    g = np.asarray(response_fn(k), np.float64)
    c = np.empty(degree + 1)
    for m in range(degree + 1):
        c[m] = (2.0 / n) * float(np.sum(g * np.cos(m * theta)))
    return c


def cheby_apply_torch(op, X, coeffs, lmax, device='cuda', dtype='float64'):
    """Chebyshev evaluation on the GPU. Same maths as cheby_apply, different hardware.

    WHY THIS EXISTS — it refutes a claim I made. I rejected the polynomial route with
    "degree ~11,000 at cage level and ~178,000 at subdivision level 2, infeasible". That
    was a CPU judgement stated as a structural one.

    THE SPEEDUP NUMBER WAS ALSO WRONG, AND ITS CORRECTION IS INSTRUCTIVE. First measured
    at 46.4x — on a SYNTHETIC banded matrix with random +/-40 column offsets. Re-measured
    on the REAL cotan operator at level 2 (219,368 verts, 1,568,260 nnz, 7.1 per row):
    GPU 242.6 us against CPU 2,486 us, so **10.2x**, not 46x. The GPU time barely moved
    (242.6 vs 260 us); the CPU time fell 5x, because the real operator inherits the mesh's
    vertex ordering and therefore has cache locality that my randomised synthetic matrix
    destroyed. A synthetic benchmark had quietly handicapped the baseline.

    10.2x is still decisive for this purpose — degree 179,000 is ~44 s on the GPU against
    ~7.4 min on the CPU — so the conclusion survives. But never quote a speedup measured on
    a stand-in matrix: sparsity PATTERN, not just density, sets sparse-matvec throughput.

    FP64 IS NOT OPTIONAL HERE. The 4090 runs fp64 ARITHMETIC at 1/64 rate, which sounds
    disqualifying and is not: SpMV is memory-bandwidth-bound, not FLOP-bound, so fp64
    costs about 2x (twice the bytes moved) rather than 64x. A 179,000-term three-term
    recurrence in fp32 would accumulate error well past anything the sweep could trust,
    so the cheap-looking option is the wrong one.

    The recurrence is sequential in degree — T_{k+1} needs T_k and T_{k-1} — so the
    parallelism is entirely inside each SpMV. That is fine; it is where the work is.
    """
    import torch

    X = np.asarray(X, np.float64)
    flat = X.ndim == 1
    Xm = X.reshape(-1, 1) if flat else X

    dev = torch.device(device)
    dt = getattr(torch, dtype)
    K = op['K'].tocsr()
    Kt = torch.sparse_csr_tensor(
        torch.as_tensor(K.indptr.astype(np.int64)),
        torch.as_tensor(K.indices.astype(np.int64)),
        torch.as_tensor(K.data.astype(np.float64)),
        size=K.shape,
        device=dev,
        dtype=dt,
    )
    minv = torch.as_tensor(op['Minv_sqrt'], device=dev, dtype=dt).unsqueeze(1)
    sq = torch.as_tensor(op['sqrtM'], device=dev, dtype=dt).unsqueeze(1)
    a = 0.5 * float(lmax)

    def shifted(Y, minv=minv, Kt=Kt):
        return (minv * (Kt @ (minv * Y))) / a - Y

    G = sq * torch.as_tensor(Xm, device=dev, dtype=dt)
    T0 = G
    T1 = shifted(G)
    out = 0.5 * float(coeffs[0]) * T0 + float(coeffs[1]) * T1
    for m in range(2, len(coeffs)):
        T2 = 2.0 * shifted(T1) - T0
        out = out + float(coeffs[m]) * T2
        T0, T1 = T1, T2
    R = (out / sq).cpu().numpy()
    del shifted, Kt, minv, sq, T0, T1, G, out
    torch.cuda.empty_cache()
    return R.ravel() if flat else R


def cheby_keep_torch(op, X, k_stop, k_pass, degree=None, sharpness=1.0, device='cuda'):
    lmax = op.get('_lmax') or lambda_max(op)
    op['_lmax'] = lmax
    d = int(degree or cheby_degree_for(lmax, k_stop, k_pass))
    fn = lambda k: band_response(k, k_pass=k_pass, k_stop=k_stop, sharpness=sharpness)
    c = cheby_coeffs(fn, d, lmax)
    R = cheby_apply_torch(op, X, c, lmax, device=device)
    return R, {'degree': d, 'lmax': float(lmax), 'device': device, 'backend': 'torch'}


def cheby_apply(op, X, coeffs, lmax):
    """Evaluate p(L) X where p is the Chebyshev series `coeffs` on [0, lmax].

    Works in the symmetrised variable so the recurrence sees a symmetric operator with a
    real spectrum: p(M^-1 K) X = M^-1/2 p(M^-1/2 K M^-1/2) M^1/2 X.
    """
    X = np.asarray(X, np.float64)
    flat = X.ndim == 1
    Xm = X.reshape(-1, 1) if flat else X

    Lsym = op['Lsym']
    a = 0.5 * float(lmax)

    def shifted(Y):
        return (Lsym @ Y) / a - Y

    G = op['sqrtM'][:, None] * Xm  # to the symmetric variable
    T0 = G
    T1 = shifted(G)
    out = 0.5 * coeffs[0] * T0 + coeffs[1] * T1
    for m in range(2, len(coeffs)):
        T2 = 2.0 * shifted(T1) - T0
        out = out + coeffs[m] * T2
        T0, T1 = T1, T2
    R = op['Minv_sqrt'][:, None] * out  # back to the function variable
    return R.ravel() if flat else R


# ----------------------------------------------------------------------------------
# FILTER FAMILIES  (each returns the KEPT part -- the detail residual -- not the low-pass)
# ----------------------------------------------------------------------------------


def diffusion_keep(op, X, iters, alpha=0.5):
    """BASELINE. scan_ingest's separator: residual = x - umbrella_lowpass(x).

    Present so every number in the report has the thing it replaces sitting next to it.
    """
    A = op['A']
    Y = np.asarray(X, np.float64).copy()
    for _ in range(int(iters)):
        Y += alpha * (A @ Y - Y)
    return np.asarray(X, np.float64) - Y


def diffusion_iters_for(mean_edge_m, lam_cut_m, alpha=0.5, target=0.5):
    """scan_ingest's analytic iteration count, reproduced for the baseline."""
    x = 2.0 * math.pi * float(mean_edge_m) / float(lam_cut_m)
    mu = 1.0 - alpha * (1.0 - math.cos(x))
    if not (0.0 < mu < 1.0):
        raise DetailFilterError('cutoff %g m not representable at mean edge %g m' % (lam_cut_m, mean_edge_m))
    return max(1, int(math.ceil(math.log(target) / math.log(mu))))


def taubin_stability(lmax, lam, mu, n_probe=4096):
    """Largest |per-pair gain| over [0, lmax]. Must be <= 1 or the cascade diverges.

    MEASURED, not derived, because the derivation is where this went wrong the first time.
    Bounding lam and mu SEPARATELY by the usual 2/lmax is NOT sufficient: the pair gain is
    the PRODUCT (1 - lam*k)(1 - mu*k), which for mu < 0 behaves like lam*|mu|*k^2 at large
    k and therefore grows without bound. On a normalised umbrella operator (spectrum [0,2])
    that never bites, which is why the textbook form omits it. On an unnormalised cotan
    operator whose spectrum reaches 2.3e7 it bites immediately -- measured: a configuration
    that passed the separate bounds returned 1.9e13 where 1.0 was the maximum possible.
    """
    k = np.linspace(0.0, float(lmax), int(n_probe))
    g = (1.0 - float(lam) * k) * (1.0 - float(mu) * k)
    return float(np.max(np.abs(g)))


def taubin_keep(op, X, k_pb, n_pairs, lam=None):
    """Taubin lambda|mu. residual = x - taubin_lowpass(x).

    Per lambda/mu PAIR a mode at eigenvalue k is multiplied by (1 - lam*k)(1 - mu*k), with
    mu < 0 chosen so the product is 1 at k = k_pb. The pair count then sets STEEPNESS while
    k_pb sets the CUTOFF -- the two independent knobs the diffusion family does not have.

    lam is bounded by stability: |1 - lam*k| <= 1 over the whole spectrum requires
    lam <= 2/lmax, and the same for |mu|. Chosen automatically from lambda_max unless given.
    """
    lmax = op.get('_lmax') or lambda_max(op)
    op['_lmax'] = lmax
    if lam is None:
        lam = 0.9 * 2.0 / lmax
    lam = float(lam)
    denom = (1.0 / lam) - float(k_pb)
    if denom <= 0:
        raise DetailFilterError('k_pb=%g is too large for lam=%g (needs k_pb < 1/lam=%g)' % (k_pb, lam, 1.0 / lam))
    mu = -1.0 / denom
    gain = taubin_stability(lmax, lam, mu)
    if gain > 1.0 + 1e-9:
        raise DetailFilterError(
            'Taubin is unstable on this operator: max per-pair gain %.4g over [0, %.4g] '
            '(lam=%.4g, mu=%.4g). The pair transfer (1-lam*k)(1-mu*k) grows like '
            'lam*|mu|*k^2, so no (lam, mu) is stable when the spectrum reaches this far. '
            'That is a property of the MESH -- triangle areas here span ~4 orders of '
            'magnitude (fingers and toes against the torso) -- not of the cutoff. Use a '
            'rational filter (butterworth_keep), whose response does not depend on the '
            'top of the spectrum at all.' % (gain, lmax, lam, mu)
        )

    X = np.asarray(X, np.float64)
    Y = X.copy()
    Minv = 1.0 / op['M']
    K = op['K']

    def step(Z, c):
        return Z - c * (Minv[:, None] * (K @ Z))  # L = M^-1 K, applied as -c*L

    for _ in range(int(n_pairs)):
        Y = step(Y, lam)
        Y = step(Y, mu)
    return X - Y, {'lam': lam, 'mu': mu, 'k_pb': float(k_pb), 'n_pairs': int(n_pairs), 'lmax': float(lmax)}


def cheby_keep(op, X, k_stop, k_pass, degree=None, sharpness=1.0):
    """Chebyshev band separator: applies the KEEP response directly.

    Unlike the other two this does not compute a low-pass and subtract -- the desired
    response IS the keep fraction, so the polynomial is fitted to it. That also means the
    short-wavelength end can be shaped later (see keep_with_noise_reject) without a second
    pass.
    """
    lmax = op.get('_lmax') or lambda_max(op)
    op['_lmax'] = lmax
    d = int(degree or cheby_degree_for(lmax, k_stop, k_pass))
    fn = lambda k: band_response(k, k_pass=k_pass, k_stop=k_stop, sharpness=sharpness)
    c = cheby_coeffs(fn, d, lmax)
    R = cheby_apply(op, X, c, lmax)
    return R, {
        'degree': d,
        'lmax': float(lmax),
        'k_stop': float(k_stop),
        'k_pass': float(k_pass),
        'sharpness': float(sharpness),
    }


def butterworth_keep(op, X, k_c, order=4, solver='splu'):
    """RATIONAL band separator. The one that actually works on this mesh.

    keep(k) = (k/k_c)^(2n) / (1 + (k/k_c)^(2n))          [Butterworth high-pass]

    WHY RATIONAL RATHER THAN POLYNOMIAL, and this is the whole point of this function.
    A degree-d polynomial filter on [0, lambda_max] resolves features of width
    lambda_max/d, so the degree needed scales with the RATIO of the spectrum's top to the
    transition width. On this mesh that ratio is catastrophic: triangle areas run from
    0.06 mm^2 in the toes to 669 mm^2 in the torso, so lambda_max = 2.3e7 at cage level
    while the band edges sit at k = 432 and 5595. The transition is 1e-4 of the domain,
    the required degree is ~11,000 at cage level and ~178,000 at subdivision level 2, and
    Taubin is not merely expensive but unstable there (see taubin_stability).

    A rational filter has no such dependence. Its sharpness comes from the ORDER, its
    position from k_c, and lambda_max does not enter the response at all -- the same
    order gives the same curve whether the spectrum stops at 10^3 or 10^8. Order 4 puts
    the 0.18 S proportion edge and the 0.05 S detail edge (a ratio of 12.96 in eigenvalue)
    about 4.5 decades apart in gain.

    Realised by partial fractions rather than by squaring the operator. 1/(1 + z^(2n)) has
    2n simple poles on the unit circle with residue -p_j/(2n), so

        H(A) b = Re[ 2 * sum_{Im p_j > 0} (-p_j / 2n) * (A/k_c - p_j I)^-1 b ]

    which is n COMPLEX SPARSE SOLVES with A's own sparsity pattern. Forming A^2 instead
    would give a 2-ring stencil and roughly 7x the fill, for the same answer.

    Works in the symmetrised variable A = M^-1/2 K M^-1/2 so the shifted systems are
    complex symmetric with a real spectrum underneath.
    """
    X = np.asarray(X, np.float64)
    flat = X.ndim == 1
    Xm = X.reshape(-1, 1) if flat else X
    n = int(order)
    kc = float(k_c)

    facs, cache_hit, t_fac = _bw_factors(op, kc, n, solver)

    B = (op['sqrtM'][:, None] * Xm).astype(np.complex128)
    acc = np.zeros_like(B)
    t0 = time.time()
    for res, soln in facs:
        # ONE call for ALL columns. SuperLU.solve accepts a 2-D right-hand side, so the
        # three probe axes are three RHS against one factorisation rather than three
        # separate triangular solves.
        acc = acc + res * soln(B)
    t_solve = time.time() - t0

    LP = (2.0 * acc).real  # low-pass in the symmetric var
    LP = op['Minv_sqrt'][:, None] * LP  # back to the function variable
    R = Xm - LP  # keep = x - lowpass(x)
    R = R.ravel() if flat else R
    return R, {
        'order': n,
        'k_c': kc,
        'n_solves': len(facs),
        'lambda_c_m': wavelength_from_eig(kc),
        'solver': solver,
        'factor_cache_hit': cache_hit,
        'factor_s': t_fac,
        'solve_s': t_solve,
        'n_rhs': int(B.shape[1]),
    }


def _bw_factors(op, kc, n, solver):
    """Factorise once per (operator, k_c, order, solver); reuse for every right-hand side.

    THE DEFECT THIS FIXES, which was mine. The shifted systems (A/k_c - p_j I) depend only
    on the OPERATOR, the cutoff and the order -- never on the field being filtered. The
    first version built and factorised them inside the per-call pole loop, so a sweep that
    applies the separator at 5 wavelengths x 3 axes paid 15 factorisations per pole where
    ONE was needed: 60 for order 4 instead of 4. Measured cost of that mistake: the
    level-1 order-4 sweep took 2,917 s, and sparse LU factorisation is essentially all of
    it -- the triangular solves that follow are cheap and were being thrown away every
    time. It also hid the true production cost, because a real ingest applies the filter
    ONCE, not fifteen times, so the sweep timing was never the number to plan around.

    The cache lives ON THE OPERATOR DICT rather than in a module-level table keyed by id().
    That is deliberate: a module cache keyed on id() can hand back the factors of a freed
    operator whose address has been reused, which would silently filter with the wrong
    matrix and produce plausible, wrong numbers. Hanging it on the object makes the
    lifetime of the cache exactly the lifetime of the thing it describes.
    """
    from scipy.sparse.linalg import splu, gmres

    store = op.setdefault('_bw_factors', {})
    key = (round(float(kc), 12), int(n), str(solver))
    if key in store:
        return store[key], True, 0.0

    t0 = time.time()
    Dl = diags(op['Minv_sqrt'])
    A = (Dl @ op['K'].tocsc() @ Dl).tocsc() / float(kc)
    I = diags(np.ones(op['nv'], dtype=np.complex128)).tocsc()

    facs = []
    for j in range(2 * n):
        p = np.exp(1j * math.pi * (2 * j + 1) / (2 * n))
        if p.imag <= 1e-15:  # conjugate pairs: keep upper half
            continue
        res = -p / (2.0 * n)
        Msys = (A.astype(np.complex128) - p * I).tocsc()
        if solver == 'splu':
            lu = splu(Msys)
            facs.append((res, lu.solve))
        else:

            def _mk(M):
                def _s(Bm):
                    return np.stack([gmres(M, Bm[:, c], rtol=1e-10, maxiter=2000)[0] for c in range(Bm.shape[1])], 1)

                return _s

            facs.append((res, _mk(Msys)))
    store[key] = facs
    return facs, False, time.time() - t0


def clear_factor_cache(op):
    """Drop cached LU factors. They are the largest thing the operator holds -- fill-in on
    a 219k complex system runs to gigabytes -- so a long-lived operator that has finished
    filtering should release them rather than carry them to the next stage."""
    n = len(op.get('_bw_factors', {}))
    op['_bw_factors'] = {}
    return n


def butterworth_lowpass(op, X, k_c, order=2, solver='splu'):
    """The LOW-PASS half of butterworth_keep, exposed on its own.

    geom/scan_ingest.py needs the low-pass rather than the residual because it applies
    COVERAGE-NORMALISED (Knutsson-Westin) smoothing: it pushes the masked field AND the
    mask through the same operator and divides, so an uncovered vertex contributes no
    weight instead of contributing the weight of a zero. Subtracting inside the filter
    would destroy that structure — the normalisation has to happen between the low-pass and
    the subtraction, not after it. Returning `keep` and asking the caller to reconstruct
    the low-pass would also be lossy, hence a separate entry point rather than a flag.
    """
    X = np.asarray(X, np.float64)
    flat = X.ndim == 1
    Xm = X.reshape(-1, 1) if flat else X
    facs, cache_hit, t_fac = _bw_factors(op, float(k_c), int(order), solver)
    B = (op['sqrtM'][:, None] * Xm).astype(np.complex128)
    acc = np.zeros_like(B)
    for res, soln in facs:
        acc = acc + res * soln(B)
    LP = op['Minv_sqrt'][:, None] * (2.0 * acc).real
    return (LP.ravel() if flat else LP), {
        'order': int(order),
        'k_c': float(k_c),
        'factor_cache_hit': cache_hit,
        'factor_s': t_fac,
        'n_rhs': int(B.shape[1]),
    }


def butterworth_response(k, k_c, order):
    """The KEEP gain of butterworth_keep, in closed form, for checking the measurement."""
    z = np.asarray(k, np.float64) / float(k_c)
    p = z ** (2 * int(order))
    return p / (1.0 + p)
