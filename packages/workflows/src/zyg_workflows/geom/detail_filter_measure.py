# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""MEASURING THE SEPARATORS IN geom/detail_filter.py AGAINST THE ONE THEY REPLACE.

Everything here is an experiment, not a library. It exists so that the claim "the new
separator is better" is a measured number next to the old measured number, produced by the
same instrument on the same mesh, rather than an argument about filter theory.

TWO EXPERIMENTS, and the second one matters more.

  1. THE WAVELENGTH SWEEP (sweep_all). Synthetic plane waves, exactly the probe
     geom/scan_ingest.py used on itself, so its published 29.5% / 83.0% / selectivity 2.8
     can be put in the same table. Scored at the REAL operating edges -- reject at 0.18 S,
     pass at 0.05 S -- as well as at the 4x/0.25x window scan_ingest scored itself in.
     The 16x window flatters everything; it is reported for comparability only.

  2. THE REAL-FIELD TEST (real_field_test). Plane waves are not what a body does. This
     drives the separators with fields the pipeline actually produces:
        proportion: a genuine anny parameter change, in two flavours --
            IN-BASIS      a phenotype macro move, which the morph separator is built to
                          catch, and which it therefore SHOULD remove almost perfectly;
            OUT-OF-BASIS  a bone-scale limb-length change, a DIFFERENT mechanism that the
                          macro basis does not span. Reporting only the in-basis case
                          would be marking the morph separator's own homework.
        detail:     the real bony relief field from geom/relief.py -- the actual clavicle
                    and malleoli this whole pipeline exists to recover.
     Leakage is then the fraction of a real proportion change that survives, and passage
     is the fraction of the real relief that survives. Those are the quantities the
     pipeline cares about; the sinusoid sweep is a proxy for them.

WHAT WOULD MAKE THESE NUMBERS A LIE, and how each is closed:
  * Scoring the morph separator only on proportion changes it was built from -- closed by
    the out-of-basis flavour above.
  * Probing wavelengths the mesh cannot carry -- closed in detail_filter.probe_floor_m;
    unmeasurable points are recorded as unmeasurable, never as a value.
  * Comparing a new operator against a re-implemented old one that is not the old one --
    closed by detail_filter.umbrella_operator, which is scan_ingest's operator copied
    line for line, driven by scan_ingest's own analytic iteration count.
"""

from __future__ import annotations

import math
import time

import numpy as np

from zyg_workflows.geom import detail_filter as DF

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


LEVEL_DEFAULT = 1


def load_cage(who='female'):
    """The delivered original, exactly as geom/relief_subdiv.py loads it."""
    from zyg_workflows.geom import mesh_skeletons as MS
    from zyg_workflows.geom import relief as RL

    reg = MS._registry()
    p = reg['originals'][who]['params']
    bone_names = [str(n) for n in MS._bone_names(MS._model())]
    v0, faces0, bones, weights = RL.bones_for(
        p['phenotype'], p.get('local_changes') or None, p.get('bone_scales') or None
    )
    v0 = np.asarray(MS._apply_anatomy(v0, faces0, p.get('anatomy_layer') or {}), np.float64)
    faces0 = np.asarray(faces0, np.int64)
    stature = float(v0[:, 2].max() - v0[:, 2].min())
    return {
        'v': v0,
        'faces': faces0,
        'params': p,
        'bones': bones,
        'weights': weights,
        'bone_names': bone_names,
        'stature_m': stature,
        'who': who,
    }


def subdivided(cage, level):
    from zyg_workflows.geom import relief_subdiv as RS

    if level == 0:
        return cage['v'].copy(), cage['faces'].copy()
    v, f, _prov = RS.subdivide(cage['v'], cage['faces'], level)
    return np.asarray(v, np.float64), np.asarray(f, np.int64)


def lift_displacement(cage, d_cage, level):
    """Carry a CAGE displacement to the subdivided surface.

    Catmull-Clark is affine in vertex positions (every new point is a weighted average
    whose weights sum to one), so the subdivided displacement is exactly
    subdivide(v + d) - subdivide(v). Doing it as a difference rather than by interpolating
    d means the answer is the true limit-surface displacement, not a resampling of the
    cage field -- the distinction geom/relief_subdiv.py had to make for the same reason.
    """
    from zyg_workflows.geom import relief_subdiv as RS

    if level == 0:
        return np.asarray(d_cage, np.float64)
    v1, _f1, _p1 = RS.subdivide(cage['v'] + d_cage, cage['faces'], level)
    v0, _f0, _p0 = RS.subdivide(cage['v'], cage['faces'], level)
    return np.asarray(v1, np.float64) - np.asarray(v0, np.float64)


# ----------------------------------------------------------------------------------
# THE FIELDS THE REAL-FIELD TEST DRIVES WITH
# ----------------------------------------------------------------------------------


def morph_basis(cage, macros=True, n_local=0, delta=0.15, verbose=True):
    """Columns spanning what anny can say about a body's PROPORTIONS.

    Each column is a central difference (v(+delta) - v(-delta)) / 2, i.e. the cage
    displacement per unit of one parameter. Central rather than forward because anny's
    macros are not linear and a one-sided difference would carry curvature into the basis.
    """
    from zyg_workflows.geom import relief as RL

    p = cage['params']
    phen = dict(p['phenotype'])
    loc = dict(p.get('local_changes') or {})
    cols, names = [], []

    def build(ph, lc):
        v, _f, _b, _w = RL.bones_for(ph, lc or None, p.get('bone_scales') or None)
        return np.asarray(v, np.float64)

    keys = list(phen.keys()) if macros else []
    if n_local:
        keys += list(loc.keys())[: int(n_local)]

    for k in keys:
        src = phen if k in phen else loc
        base = float(src.get(k, 0.5))
        hi = min(1.0, base + delta)
        lo = max(0.0, base - delta)
        if hi <= lo:
            continue
        a = dict(phen)
        b = dict(loc)
        (a if k in phen else b)[k] = hi
        vp = build(a, b)
        a = dict(phen)
        b = dict(loc)
        (a if k in phen else b)[k] = lo
        vm = build(a, b)
        col = ((vp - vm) / (hi - lo)).reshape(-1)
        nrm = float(np.linalg.norm(col))
        if nrm < 1e-9:
            continue
        cols.append(col / nrm)
        names.append(k)
        if verbose:
            _zyg_log.info('    basis %-22s |dv| = %.4f m/unit' % (k, nrm))
    if not cols:
        raise DF.DetailFilterError('morph basis came out empty')
    return np.stack(cols, 1), names


def proportion_field_in_basis(cage, key=None, delta=0.20):
    """A real proportion change of the kind the morph basis spans."""
    from zyg_workflows.geom import relief as RL

    p = cage['params']
    phen = dict(p['phenotype'])
    k = key or sorted(phen.keys())[0]
    base = float(phen[k])
    tgt = min(1.0, base + delta) if base + delta <= 1.0 else max(0.0, base - delta)
    phen[k] = tgt
    v, _f, _b, _w = RL.bones_for(phen, p.get('local_changes') or None, p.get('bone_scales') or None)
    return np.asarray(v, np.float64) - cage['v'], {'kind': 'phenotype', 'key': k, 'from': base, 'to': tgt}


def proportion_field_out_of_basis(cage, scale=1.06):
    """A real proportion change the macro basis does NOT span: limb length.

    bone_scales lengthens a segment directly. It is proportion by any definition -- it
    moves the upper arm, which is the very quantity scan_ingest's 0.18 S bound is drawn
    from -- but it is a different mechanism from a phenotype macro, so the morph separator
    has to earn this one rather than recognise its own basis vector.
    """
    from zyg_workflows.geom import relief as RL

    p = cage['params']
    bs = dict(p.get('bone_scales') or {})
    touched = []
    for nm in ('upperarm01.L', 'upperarm01.R', 'upperarm02.L', 'upperarm02.R', 'upperleg01.L', 'upperleg01.R'):
        bs[nm] = float(bs.get(nm, 1.0)) * float(scale)
        touched.append(nm)
    v, _f, _b, _w = RL.bones_for(p['phenotype'], p.get('local_changes') or None, bs)
    return np.asarray(v, np.float64) - cage['v'], {'kind': 'bone_scale', 'scale': float(scale), 'bones': touched}


def proportion_field_midscale(cage, frac_S=None, amp_frac=0.02):
    """A CONSTRUCTED mid-scale proportion change, sitting exactly on the band edge.

    WHY THIS FIELD HAS TO EXIST. The two anny-driven proportion fields above are
    body-scale: a phenotype macro or a limb-length change puts nearly all its energy at
    wavelengths far longer than 0.18 S, where any low-pass kills it easily. Scoring only
    on those would let a poor filter look excellent, because it would never be asked the
    hard question. The hard question is a proportion difference AT the boundary -- a
    subject whose hips are wide relative to their waist, whose ribcage is deep for their
    shoulders. That is a girth modulation over roughly a segment length, which is exactly
    where scan_ingest's 0.18 S bound was drawn and exactly where a smooth filter has no
    margin left.

    Constructed, and labelled constructed: a smooth radial (girth) modulation in the
    vertical direction at the proportion edge wavelength. It is a real proportion change
    by definition -- it changes circumferences and nothing else -- but no anny parameter
    produced it, so it carries claim='constructed' in the report and must never be read
    as a measurement of what a real body does.
    """
    v = cage['v']
    S = cage['stature_m']
    lam = float(frac_S or DF.PROPORTION_EDGE_FRAC) * S
    z = v[:, 2]
    r = np.stack([v[:, 0], v[:, 1]], 1)
    rad = np.linalg.norm(r, axis=1)
    hat = np.zeros_like(r)
    nz = rad > 1e-9
    hat[nz] = r[nz] / rad[nz, None]
    amp = float(amp_frac) * float(np.median(rad[nz]))
    scale = amp * np.cos(2.0 * math.pi * z / lam)
    d = np.zeros_like(v)
    d[:, 0] = hat[:, 0] * scale
    d[:, 1] = hat[:, 1] * scale
    return d, {
        'kind': 'constructed_girth_modulation',
        'claim': 'constructed',
        'lambda_m': lam,
        'lambda_frac_S': lam / S,
        'amp_m': amp,
    }


def detail_field(cage):
    """The real bony relief layer -- the thing this pipeline exists to recover."""
    from zyg_workflows.geom import relief as RL

    p = cage['params']
    anat = dict(p.get('anatomy_layer') or {})
    anat['bony_relief'] = float(anat.get('bony_relief', 1.0) or 1.0)
    vr = RL.apply_relief(cage['v'], cage['faces'], anat, phenotype=p['phenotype'], bones=cage['bones'])
    vr = np.asarray(vr, np.float64)
    return vr - cage['v'], {'kind': 'bony_relief', 'amplitude': anat['bony_relief']}


# ----------------------------------------------------------------------------------
# THE SEPARATORS UNDER TEST
# ----------------------------------------------------------------------------------


def build_separators(v_sub, f_sub, stature_m, basis_sub=None, verbose=True):
    S = float(stature_m)
    lam_cut = DF.LEGACY_CUTOFF_FRAC * S
    lam_prop = DF.PROPORTION_EDGE_FRAC * S
    lam_det = DF.DETAIL_EDGE_FRAC * S

    t0 = time.time()
    umb = DF.umbrella_operator(v_sub, f_sub)
    cot = DF.cotan_operator(v_sub, f_sub)
    h = umb['mean_edge_m']
    if verbose:
        _zyg_log.info(
            '  operators built in %.1fs; mean edge %.3f mm; cotan stats %s' % (time.time() - t0, h * 1e3, cot['stats'])
        )

    lmax = DF.lambda_max(cot)
    cot['_lmax'] = lmax
    k_stop = DF.eig_from_wavelength(lam_prop)
    k_pass = DF.eig_from_wavelength(lam_det)
    deg = DF.cheby_degree_for(lmax, k_stop, k_pass)
    if verbose:
        _zyg_log.info('  lambda_max %.4g; band k=[%.1f, %.1f]; chebyshev degree %d' % (lmax, k_stop, k_pass, deg))

    n_it = DF.diffusion_iters_for(h, lam_cut)
    k_pb = DF.eig_from_wavelength(lam_cut)

    seps = {}
    # A1 is the ANALYTIC iteration count. scan_ingest computes this in _lowpass_iters, but
    # it does NOT ship it -- and that distinction cost me a wrong baseline once already.
    seps['A1_umbrella_ANALYTIC_iters'] = (
        lambda F: DF.diffusion_keep(umb, F, n_it),
        {
            'operator': 'umbrella (scan_ingest, uniform weights)',
            'family': 'diffusion',
            'iters': int(n_it),
            'cutoff_m': lam_cut,
            'note': 'NOT the shipped configuration -- analytic count, under-smooths',
        },
    )

    # A2 IS THE SHIPPED CONFIGURATION, and it is the only honest baseline.
    #
    # THE MISTAKE THIS CORRECTS. My first comparison used the analytic iteration count and
    # called it "the baseline". scan_ingest does not run that: geom/scan_ingest.py:1622
    # calls _calibrate_lowpass, which ITERATES until the cutoff wavelength is measured at
    # 0.5 amplitude on the actual mesh -- because the analytic estimate under-smooths badly
    # on an irregular mesh (scan_ingest measured it landing at 0.847 instead of 0.5). The
    # calibrated filter is far more aggressive: 2,969 iterations against an analytic 239 at
    # level 1, and 11,922 at level 2.
    #
    # The direction of the error matters. The analytic count is GENTLER, so it leaks less
    # proportion and scores BETTER -- measured 7.84 legacy selectivity where the shipped
    # calibrated filter scores 1.77. Comparing against it therefore made the thing being
    # replaced look stronger than it is, which is the flattering direction for the
    # incumbent and the unflattering one for the replacement. It still has to be corrected:
    # a baseline that is not what ships is not a baseline.
    n_cal, cal_meta = _calibrate_umbrella(umb, v_sub, h, lam_cut, verbose=verbose)
    seps['A2_umbrella_CALIBRATED_SHIPPED'] = (
        lambda F: DF.diffusion_keep(umb, F, n_cal),
        {
            'operator': 'umbrella (scan_ingest, uniform weights)',
            'family': 'diffusion',
            'iters': int(n_cal),
            'cutoff_m': lam_cut,
            'calibration': cal_meta,
            'note': 'THE SHIPPED CONFIGURATION -- calibrated to response 0.5 on this mesh',
        },
    )

    seps['B_cotan_diffusion'] = (
        lambda F: F - _cotan_diffuse(cot, F, lam_cut, h),
        {
            'operator': 'cotan Laplace-Beltrami',
            'family': 'diffusion',
            'cutoff_m': lam_cut,
            'note': 'isolates the OPERATOR change alone',
        },
    )

    seps['C_cotan_taubin'] = (
        lambda F: DF.taubin_keep(cot, F, k_pb=k_pb, n_pairs=60)[0],
        {'operator': 'cotan', 'family': 'taubin', 'n_pairs': 60, 'k_pb': k_pb},
    )

    seps['D_cotan_chebyshev'] = (
        lambda F: DF.cheby_keep(cot, F, k_stop=k_stop, k_pass=k_pass, degree=deg)[0],
        {
            'operator': 'cotan',
            'family': 'chebyshev',
            'degree': deg,
            'k_stop': k_stop,
            'k_pass': k_pass,
            'degree_capped': bool(deg >= DF.CHEBY_DEGREE_MAX),
        },
    )

    # k_c is the GEOMETRIC MEAN of the two band edges, which is the only choice that does
    # not favour one side: it sits at the midpoint in log-eigenvalue, so the order alone
    # decides how much of each edge is rejected. Picking it nearer either edge would be
    # tuning.
    k_c = math.sqrt(k_stop * k_pass)
    # ORDER 8 IS A CONTROL, NOT A CANDIDATE. A plane-wave probe on a curved, irregular
    # surface is NOT a single Laplace-Beltrami mode -- its energy is spread over a band of
    # eigenvalues -- so even a perfect brick wall cannot score leak 0 / pass 1 on it. As
    # the order rises the filter approaches a brick wall, so whatever the numbers CONVERGE
    # to is the probe's own spectral spread: the measurement ceiling, not a filter result.
    # Without it, "leak 0.084" has nothing to be good or bad against.
    for order in (2, 4, 8):
        seps['F_cotan_butterworth_n%d' % order] = (
            lambda F, o=order: DF.butterworth_keep(cot, F, k_c=k_c, order=o)[0],
            {
                'operator': 'cotan',
                'family': 'butterworth (rational)',
                'order': order,
                'k_c': k_c,
                'lambda_c_m': DF.wavelength_from_eig(k_c),
                'predicted_keep_at_prop_edge': float(DF.butterworth_response(np.array([k_stop]), k_c, order)[0]),
                'predicted_keep_at_detail_edge': float(DF.butterworth_response(np.array([k_pass]), k_c, order)[0]),
            },
        )

    if basis_sub is not None:
        seps['E_morph_projection'] = (
            lambda F: DF.morph_keep(basis_sub, F)[0],
            {'operator': 'none (model subspace)', 'family': 'morph projection', 'm_basis': int(basis_sub.shape[1])},
        )

        # THE TWO-STAGE ARCHITECTURE, measured rather than argued. The morph projection
        # removes proportion without touching relief (its detail passage is ~1.00), so it
        # can only help if it is applied FIRST and the filter then cleans up whatever the
        # model could not express. If the composition does not beat the filter alone, the
        # model stage is not earning its place and should be dropped.
        seps['G_morph_then_butterworth_n2'] = (
            lambda F: DF.butterworth_keep(cot, DF.morph_keep(basis_sub, F)[0], k_c=k_c, order=2)[0],
            {
                'operator': 'cotan',
                'family': 'morph projection -> butterworth',
                'order': 2,
                'k_c': k_c,
                'm_basis': int(basis_sub.shape[1]),
            },
        )

    return seps, {
        'umbrella': umb,
        'cotan': cot,
        'mean_edge_m': h,
        'lmax': lmax,
        'cheby_degree': deg,
        'diffusion_iters': int(n_it),
    }


def _calibrate_umbrella(umb, v, h, lam_cut, target=0.5, max_iters=200000, verbose=True):
    """Iterate until the cutoff wavelength is MEASURED at `target` amplitude on this mesh.

    This mirrors geom/scan_ingest.py's _calibrate_lowpass rather than reimplementing an
    idea of it: the analytic count is a starting guess, and the loop then measures the
    achieved response on the real vertex positions and keeps going. Bisection on the
    iteration count, because the response is monotone in it.
    """
    A = umb['A']

    def response(n):
        vals = []
        for ax in range(3):
            f = np.cos(2.0 * math.pi * v[:, ax] / lam_cut)
            f0 = f - f.mean()
            if float((f0 * f0).mean()) <= 1e-12:
                continue
            y = f.copy()
            for _ in range(int(n)):
                y += 0.5 * (A @ y - y)
            y0 = y - y.mean()
            vals.append(math.sqrt(float((y0 * y0).mean())) / math.sqrt(float((f0 * f0).mean())))
        return float(np.mean(vals)) if vals else 1.0

    lo, hi = 1, max(2, DF.diffusion_iters_for(h, lam_cut))
    r_hi = response(hi)
    grew = 0
    while r_hi > target and hi < max_iters:
        lo, hi = hi, hi * 2
        r_hi = response(hi)
        grew += 1
    while hi - lo > max(1, lo // 50):
        mid = (lo + hi) // 2
        if response(mid) > target:
            lo = mid
        else:
            hi = mid
    r = response(hi)
    if verbose:
        _zyg_log.info(
            '  calibrated umbrella: %d iters -> response %.4f at lam_cut %.1f mm '
            '(analytic guess was %d)' % (hi, r, lam_cut * 1e3, DF.diffusion_iters_for(h, lam_cut))
        )
    return int(hi), {
        'iters': int(hi),
        'achieved_response': r,
        'target': float(target),
        'analytic_guess': int(DF.diffusion_iters_for(h, lam_cut)),
        'doublings': grew,
        'hit_ceiling': bool(hi >= max_iters),
    }


def _cotan_diffuse(cot, F, lam_cut, h):
    """Explicit diffusion on the COTAN operator, cutoff matched to lam_cut.

    Present only to split the two independent changes apart: B vs A is the operator, and
    D vs B is the filter family. Without it a single combined number could not say which
    of the two faults actually mattered.
    """
    lmax = cot.get('_lmax') or DF.lambda_max(cot)
    cot['_lmax'] = lmax
    dt = 0.9 * 2.0 / lmax
    k_cut = DF.eig_from_wavelength(lam_cut)
    n = max(1, int(math.ceil(math.log(0.5) / math.log(max(1.0 - dt * k_cut, 1e-12)))))
    n = min(n, 20000)
    Minv = 1.0 / cot['M']
    K = cot['K']
    Y = np.asarray(F, np.float64).copy()
    for _ in range(n):
        Y -= dt * (Minv[:, None] * (K @ Y))
    return Y


# ----------------------------------------------------------------------------------
# EXPERIMENTS
# ----------------------------------------------------------------------------------


def _rel(a, b):
    """RMS of a relative to RMS of b."""
    na = float(np.sqrt((a * a).sum(1).mean()))
    nb = float(np.sqrt((b * b).sum(1).mean()))
    return na / max(nb, 1e-30)


def run(who='female', level=LEVEL_DEFAULT, n_local=0, verbose=True):
    t_all = time.time()
    cage = load_cage(who)
    S = cage['stature_m']
    if verbose:
        _zyg_log.info('cage %s: %d verts, stature %.4f m' % (who, cage['v'].shape[0], S))

    v_sub, f_sub = subdivided(cage, level)
    if verbose:
        _zyg_log.info('subdiv level %d: %d verts, %d faces' % (level, v_sub.shape[0], f_sub.shape[0]))

    if verbose:
        _zyg_log.info('  building morph basis...')
    B_cage, b_names = morph_basis(cage, n_local=n_local, verbose=verbose)
    B_sub = np.stack(
        [lift_displacement(cage, B_cage[:, i].reshape(-1, 3), level).reshape(-1) for i in range(B_cage.shape[1])], 1
    )
    if verbose:
        _zyg_log.info('  basis: %d columns %s' % (B_sub.shape[1], b_names))

    seps, ctx = build_separators(v_sub, f_sub, S, basis_sub=B_sub, verbose=verbose)

    # ---- experiment 1: the wavelength sweep
    sweeps = {}
    for name, (fn, meta) in seps.items():
        t0 = time.time()
        try:
            sw = DF.sweep(fn, v_sub, S, M=ctx['cotan']['M'], mean_edge_m=ctx['mean_edge_m'])
            sw['meta'] = meta
            sw['elapsed_s'] = time.time() - t0
        except Exception as e:  # noqa: BLE001
            sw = {'error': '%s: %s' % (type(e).__name__, e), 'meta': meta}
        sweeps[name] = sw
        if verbose:
            if 'error' in sw:
                _zyg_log.info('  sweep %-32s ERROR %s' % (name, sw['error']))
            else:
                _zyg_log.info(
                    '  sweep %-32s leak %.4f  pass %.4f  sel %6.2f   (%.0fs)'
                    % (
                        name,
                        sw['operating_leakage'],
                        sw['operating_passage'],
                        sw['operating_selectivity'],
                        sw['elapsed_s'],
                    )
                )

    # ---- experiment 2: real fields
    if verbose:
        _zyg_log.info('  building real fields...')
    d_prop_in, m_in = proportion_field_in_basis(cage)
    d_prop_out, m_out = proportion_field_out_of_basis(cage)
    d_prop_mid, m_mid = proportion_field_midscale(cage)
    d_det, m_det = detail_field(cage)

    fields = {}
    for nm, dc, meta in (
        ('proportion_in_basis', d_prop_in, m_in),
        ('proportion_out_of_basis', d_prop_out, m_out),
        ('proportion_midscale_CONSTRUCTED', d_prop_mid, m_mid),
        ('detail_bony_relief', d_det, m_det),
    ):
        ds = lift_displacement(cage, dc, level)
        rms = float(np.sqrt((ds * ds).sum(1).mean()))
        fields[nm] = {'field': ds, 'meta': meta, 'rms_m': rms, 'rms_frac_S': rms / S}
        if verbose:
            _zyg_log.info('    %-26s rms %8.3f mm  (%.2e S)  %s' % (nm, rms * 1e3, rms / S, meta))

    real = {}
    for name, (fn, meta) in seps.items():
        row = {'meta': meta}
        for nm, rec in fields.items():
            try:
                R = fn(rec['field'])
                if isinstance(R, tuple):
                    R = R[0]
                row[nm] = _rel(R, rec['field'])
            except Exception as e:  # noqa: BLE001
                row[nm] = None
                row.setdefault('errors', {})[nm] = '%s: %s' % (type(e).__name__, e)
        leaks = [
            row.get(k) for k in ('proportion_in_basis', 'proportion_out_of_basis', 'proportion_midscale_CONSTRUCTED')
        ]
        det = row.get('detail_bony_relief')
        if all(x is not None for x in leaks) and det is not None:
            # WORST case, not mean. A separator that is excellent on body-scale proportion
            # and useless at the band edge is a separator that will pass a real subject's
            # hip-to-waist difference straight into the detail layer.
            row['worst_leakage'] = max(leaks)
            row['detail_passage'] = det
            row['real_selectivity'] = det / max(max(leaks), 1e-12)
        real[name] = row
        if verbose:
            f = lambda x: -1.0 if x is None else x
            _zyg_log.info(
                '  real  %-30s in %.4f  out %.4f  MID %.4f  detail %.4f  sel %8.2f'
                % (name, f(leaks[0]), f(leaks[1]), f(leaks[2]), f(det), f(row.get('real_selectivity')))
            )

    ray = DF.rayleigh_check(
        ctx['cotan'], v_sub, [DF.PROPORTION_EDGE_FRAC * S, DF.LEGACY_CUTOFF_FRAC * S, DF.DETAIL_EDGE_FRAC * S]
    )

    return {
        'schema': DF.SCHEMA,
        'who': who,
        'level': int(level),
        'stature_m': S,
        'n_verts_cage': int(cage['v'].shape[0]),
        'n_verts_sub': int(v_sub.shape[0]),
        'mean_edge_m': ctx['mean_edge_m'],
        'lambda_max': ctx['lmax'],
        'cheby_degree': ctx['cheby_degree'],
        'diffusion_iters': ctx['diffusion_iters'],
        'cotan_stats': ctx['cotan']['stats'],
        'rayleigh': ray,
        'basis_names': b_names,
        'band_edges': {
            'proportion_edge_frac_S': DF.PROPORTION_EDGE_FRAC,
            'detail_edge_frac_S': DF.DETAIL_EDGE_FRAC,
            'legacy_cutoff_frac_S': DF.LEGACY_CUTOFF_FRAC,
        },
        'sweep': sweeps,
        'real_field': real,
        'field_stats': {k: {kk: vv for kk, vv in r.items() if kk != 'field'} for k, r in fields.items()},
        'elapsed_s': time.time() - t_all,
    }


def compare(who='female', level=LEVEL_DEFAULT):
    return run(who=who, level=level)


def self_test(level=0, verbose=True):
    """Unit test on a planar grid where the operator's answer is known in closed form.

    The 5-point cotan stencil on a regular grid gives Rayleigh quotient
    (2 - 2 cos(2*pi*h/L)) / h^2, whose ratio to the continuum (2*pi/L)^2 is the standard
    second-order dispersion factor. Matching that to 4 decimals is what says the operator
    is right; matching the continuum exactly would actually be WRONG at finite h.
    """
    n = 81
    h = 1.0 / (n - 1)
    xs = np.linspace(0, 1, n)
    X, Y = np.meshgrid(xs, xs, indexing='ij')
    v = np.stack([X.ravel(), Y.ravel(), np.zeros(n * n)], 1)
    idx = np.arange(n * n).reshape(n, n)
    q = np.stack([idx[:-1, :-1].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel(), idx[:-1, 1:].ravel()], 1)
    op = DF.cotan_operator(v, q)

    rows, ok = [], True
    for lam in (0.5, 0.25, 0.125, 0.0625):
        r = DF.rayleigh_check(op, v, [lam])[0]
        x = 2 * math.pi * h / lam
        theory = (2 - 2 * math.cos(x)) / x**2
        good = abs(r['ratio'] - theory) < 1e-4
        ok = ok and good
        rows.append(
            {
                'lambda_m': lam,
                'lambda_over_h': lam / h,
                'measured_ratio': r['ratio'],
                'dispersion_theory': theory,
                'match': bool(good),
                'axes_used': r['axes_used'],
            }
        )
        if verbose:
            _zyg_log.info(
                '  lam/h %5.1f  ratio %.6f  theory %.6f  %s'
                % (lam / h, r['ratio'], theory, 'OK' if good else 'MISMATCH')
            )
    if verbose:
        _zyg_log.info(
            '  total area %.6f (expect 1.000000); negative cotans %d'
            % (op['stats']['total_area_m2'], op['stats']['n_negative_cotan'])
        )
    return {
        'schema': DF.SCHEMA,
        'test': 'planar_grid_dispersion',
        'passed': bool(ok),
        'rows': rows,
        'stats': op['stats'],
    }
