# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The stages of `fit_sex()`, lifted out of its six closures.

`fit_sex()` is now the call order and nothing else: build the run, snapshot the
delivered mesh, take the steering decision, alternate the inner surface fit with
measured lever steps, assert the contract, emit the record. Everything those
steps do lives here.

The closures shared eighteen enclosing locals (the reference cloud and its two
KD-trees, the band statistics, the morph bounds, the three recipe dicts that the
inner fit mutates in place), so they are passed as one `FitSexRun`; `phen`,
`locs` and `n_meas` are the mutable fields, exactly the three names the original
rebound or incremented inside its closures.

Nothing here changes the objective, the iteration counts, the printed lines or
their order. torch and scipy are imported inside the stages that need them, as
the original imported them at the top of `fit_sex()`.
"""

from dataclasses import dataclass, field

from .core import (
    math,
    os,
    np,
    FR,
    MS,
    reference,
    SCHEMA,
    INNER_TARGET,
    TARGET_Z,
    RATIO_Z_TOL,
    OUTER_TOL_MM,
    _OUTER_TOL_SOURCE,
    PRIMARY,
    HOLD,
    OUTER,
    LOCKED_SUBSTRINGS,
    FREE_PHEN,
    FREE_LOCALS,
    HELD_HEAD,
    ANATOMY_DROPPED,
    REF_GLB,
    FD_STEP,
    crotch_index,
    crotch_frac,
    cloud_crotch_frac,
    _atanh_of,
    delivered_mesh,
    measure_ratios,
    ratio_z,
    _assert_locked,
    declared_levers,
    _assert_held,
)
from zyg_workflows import paths

from . import fit as _fit

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


@dataclass
class FitSexRun:
    """One `fit_sex()` solve: the recipe under repair plus the fixed reference it is fitted to.

    `phen`, `locs` and `anat` are the live recipe — the inner fit writes its
    solved values straight back into them and `phen` is rebound to whatever the
    delivered mesh reports, which is why they live here rather than being passed
    around by value. `n_meas` counts delivered-mesh measurements, the number the
    record reports as `measured_evaluations`.
    """

    sex: str
    phen: dict
    locs: dict
    anat: dict
    iters: int
    rounds: int
    lr: float
    verbose: bool
    freeze_inner: bool
    ref_obj: object
    model: object
    kept: object
    ref: object
    ref_path: str
    ref_crotch: float
    ref_crotch_z: float
    ref_upper: object
    ref_upper_t: object
    ref_upper_tree: object
    ref_full_tree: object
    band0: dict
    mu0: float
    sd0: float
    target_value: float
    target_h: float
    lb: float
    pb: dict
    n_meas: int = field(default=1)


def build_run(sex, phen0, locals0, anat0, iters, rounds, lr, verbose, freeze_inner):
    """Assert the locks, load and normalise the reference cloud, and pack the shared context.

    In: the sex, the issued recipe (phenotype / local_changes / anatomy) and the
    solver settings. Out: a `FitSexRun` whose dicts are fresh copies, so the
    caller's recipe is never mutated. Prints the reference's own leg proportion
    when verbose — the axis the chamfer objective is not allowed to see.
    """
    import torch

    # only PARAMETER names go through _assert_locked; a ratio name like
    # foot_length_over_stature is a measurement, not a lever, and must not trip it
    _assert_locked(FREE_PHEN, FREE_LOCALS, declared_levers(sex))
    _assert_held(sex)

    torch.manual_seed(0)
    ref_obj = reference()
    m = MS._model()
    kept = FR._kept_mask(m)
    ref_path = os.path.join(str(paths.PKG_DIR), REF_GLB[sex])
    ref = FR._load_ref_cloud(ref_path)
    ref /= ref[:, 2].max()
    # THE REFERENCE'S OWN LEG PROPORTION, measured with the landmark table's crotch rule
    ref_crotch = cloud_crotch_frac(ref)
    band0 = ref_obj.band(INNER_TARGET, sex)
    mu0, sd0 = float(band0['mean']), float(band0['sd'])
    ref_crotch_z = (ref_crotch - mu0) / sd0
    if verbose:
        _zyg_log.info(
            '  %s reference cloud crotch_height_over_stature %.4f (z %+.2f) — the axis '
            'this objective is NOT allowed to see' % (sex, ref_crotch, ref_crotch_z)
        )
    ref_upper = ref[ref[:, 2] >= ref_crotch]

    from scipy.spatial import cKDTree

    return FitSexRun(
        sex=sex,
        phen=dict(phen0),
        locs=dict(locals0),
        anat=dict(anat0),
        iters=iters,
        rounds=rounds,
        lr=lr,
        verbose=verbose,
        freeze_inner=freeze_inner,
        ref_obj=ref_obj,
        model=m,
        kept=kept,
        ref=ref,
        ref_path=ref_path,
        ref_crotch=ref_crotch,
        ref_crotch_z=ref_crotch_z,
        ref_upper=ref_upper,
        ref_upper_t=torch.tensor(ref_upper),
        ref_upper_tree=cKDTree(ref_upper),
        ref_full_tree=cKDTree(ref),
        band0=band0,
        mu0=mu0,
        sd0=sd0,
        target_value=mu0 + TARGET_Z * sd0,
        target_h=float(MS.TARGET_HEIGHT_M[sex]),
        lb=FR.LOCAL_BOUND,
        pb=FR.PHEN_BOUNDS[sex],
    )


# ===========================================================================
# the chamfer, both variants
# ===========================================================================


def terms_at(run, v_np, dy_val, upper_only, msk):
    """Both chamfer terms of `v_np` at one antero-posterior offset `dy_val`.

    In: the delivered vertices, the offset, which variant (upper-only or full
    body) and the boolean vertex mask to charge. Out: (forward, reverse) mean
    distance in unit-height coordinates.
    """
    from scipy.spatial import cKDTree

    H = float(v_np[:, 2].max() - v_np[:, 2].min())
    cen = np.array([np.median(v_np[:, 0]), np.median(v_np[:, 1]) + dy_val, v_np[:, 2].min()])
    vn = (v_np - cen) / H
    vk = vn[msk]
    rr, tree, rt = (
        (run.ref_upper, run.ref_upper_tree, run.ref_upper) if upper_only else (run.ref, run.ref_full_tree, run.ref)
    )
    _, ia = tree.query(vk, workers=-1)
    fwd = float(np.linalg.norm(vk - rr[ia], axis=1).mean())
    dr, ir = cKDTree(vk).query(rt, workers=-1)
    selr = dr < FR.TRIM_R
    rev = float(np.linalg.norm(rt[selr] - vk[ir[selr]], axis=1).mean())
    return fwd, rev


def chamfer_terms(run, v_np, upper_only):
    """fit_reference carries a free antero-posterior offset `dy` because anny's origin
    and the Blender body's are not the same point; reporting a distance at dy=0 would
    charge this fit for a registration error it never had. dy is re-solved here by a
    coarse-then-fine 1-D scan on the SAME objective, for every snapshot and for each
    variant separately, so before and after are compared on equal terms."""
    msk = run.kept.copy()
    if upper_only:
        zmin = float(v_np[:, 2].min())
        H = float(v_np[:, 2].max()) - zmin
        msk = msk & (((v_np[:, 2] - zmin) / H) >= crotch_frac(v_np))
    best = (None, None, None, 0.0)
    grid = np.linspace(-0.06, 0.06, 25)
    for _ in range(3):
        for d in grid:
            f, r = terms_at(run, v_np, float(d), upper_only, msk)
            if best[0] is None or f + r < best[0]:
                best = (f + r, f, r, float(d))
        step = float(grid[1] - grid[0])
        grid = np.linspace(best[3] - step, best[3] + step, 9)
    return best[1], best[2]


def snapshot(run, tag, want_ratios=True):
    """Build the delivered mesh at the current recipe and measure everything reportable.

    In: the run and a tag for the trail. Out: (phenotype, vertices, faces, record,
    measurements) — the record always carries both chamfer variants in mm at
    delivered stature, and the ratio report plus the leg-constraint readings when
    `want_ratios`.
    """
    p, v, faces, achieved = delivered_mesh(run.sex, run.phen, run.locs, run.anat)
    vd = v.astype(np.float64)
    fwd_u, rev_u = chamfer_terms(run, vd, True)
    fwd_f, rev_f = chamfer_terms(run, vd, False)
    rec = {
        'tag': tag,
        'height_axis': p['height'],
        'stature_m': achieved,
        'chamfer_upper_fwd_mm': fwd_u * run.target_h * 1000.0,
        'chamfer_upper_rev_mm': rev_u * run.target_h * 1000.0,
        'chamfer_full_fwd_mm': fwd_f * run.target_h * 1000.0,
        'chamfer_full_rev_mm': rev_f * run.target_h * 1000.0,
        'cage_vert_sha256': MS._vert_sha(v),
    }
    M = None
    if want_ratios:
        M = measure_ratios(run.sex, v, faces, p, run.locs)
        rec['ratios'] = _fit.report_ratios(run.sex, M, run.ref_obj)
        rec['crotch_z'] = rec['ratios'][INNER_TARGET]['z']
        rec['crotch_frac'] = rec['ratios'][INNER_TARGET]['value']
        hh = (M['measurements'].get('head_height_vertex_menton') or {}).get('value_mm')
        if hh:
            rec['head_height_vertex_menton_mm'] = hh
            rec['head_count_CONSEQUENCE'] = achieved * 1000.0 / hh
    return p, v, faces, rec, M


# ===========================================================================
# the torch inner loop
# ===========================================================================


def inner_mesh(run, torch, raw_p, raw_l):
    """The differentiable cage at the current unconstrained parameters.

    `raw_p`/`raw_l` are atanh-space tensors; each is mapped back into its own box
    with tanh so the optimiser never has to respect a bound. Out: the vertex
    tensor the loss is read off.
    """
    p = {kk: vv for kk, vv in run.phen.items()}
    for k in FREE_PHEN:
        lo, hi = run.pb[k]
        p[k] = lo + (hi - lo) * (torch.tanh(raw_p[k]) + 1.0) / 2.0
    lc = {kk: vv for kk, vv in run.locs.items()}
    for k in FREE_LOCALS:
        lc[k] = run.lb * torch.tanh(raw_l[k])
    return run.model(phenotype_kwargs=p, local_changes_kwargs=lc)['vertices'][0]


def inner_loss(run, torch, cKDTree, v, dy, K):
    """The neutralised chamfer plus `K` times the squared leg-ratio residual.

    THE NEUTRALISATION: everything below the crotch leaves the objective. The
    selection is discrete and so is recomputed from the detached mesh each
    iteration, exactly like the chamfer's own nearest-neighbour indices.
    """
    H = v[:, 2].max() - v[:, 2].min()
    zmin = v[:, 2].min()
    cen = torch.stack([v[:, 0].median(), v[:, 1].median() + dy, zmin])
    vn = (v - cen) / H
    v_np = v.detach().numpy()
    cf_np = crotch_frac(v_np)
    upper = run.kept & (((v_np[:, 2] - float(v_np[:, 2].min())) / float(v_np[:, 2].max() - v_np[:, 2].min())) >= cf_np)
    upper_t = torch.tensor(upper)
    vk = vn[upper_t]
    vk_np = vk.detach().numpy()
    _, ia = run.ref_upper_tree.query(vk_np, workers=-1)
    d_a2r = torch.linalg.norm(vk - run.ref_upper_t[ia], dim=1)
    dr, ir = cKDTree(vk_np).query(run.ref_upper, workers=-1)
    selr = dr < FR.TRIM_R
    d_r2a = torch.linalg.norm(run.ref_upper_t[selr] - vk[ir[selr]], dim=1)
    # the ratio, built the way the landmark table builds it: the index comes
    # from the detached mesh (a discrete choice cannot carry a gradient), the
    # value is read in torch so the length that vertex sits at does.
    ci = crotch_index(v_np)
    cf = (v[ci, 2] - zmin) / H
    zres = (cf - run.target_value) / run.sd0
    return d_a2r.mean() + d_r2a.mean() + K * zres**2


def inner_writeback(run, raw_p, raw_l):
    """Round the solved atanh-space parameters back into `run.phen` and `run.locs`."""
    import torch

    with torch.no_grad():
        for k in FREE_PHEN:
            lo, hi = run.pb[k]
            run.phen[k] = round(float(lo + (hi - lo) * (math.tanh(float(raw_p[k])) + 1.0) / 2.0), 4)
        for k in FREE_LOCALS:
            run.locs[k] = round(float(run.lb * math.tanh(float(raw_l[k]))), 4)


def inner(run, K):
    """Re-solve the surface fit and the leg constraint at the current lever values.

    Calibrates the height axis for the current recipe, runs `run.iters` Adam steps
    on `inner_loss` at constraint weight `K`, then writes the result back into the
    recipe. A no-op when `freeze_inner` — that is how the caller declines an
    improvement the do-no-harm guard refused.
    """
    if run.freeze_inner:
        return
    import torch
    from scipy.spatial import cKDTree

    hv, _ = MS._calibrate_height({**run.phen, 'height': run.phen.get('height', 0.5)}, run.target_h, locals_=run.locs)
    run.phen['height'] = round(float(hv), 6)
    raw_p = {}
    for k in FREE_PHEN:
        lo, hi = run.pb[k]
        raw_p[k] = torch.tensor(_atanh_of(run.phen.get(k, 0.5), lo, hi), dtype=torch.float64, requires_grad=True)
    raw_l = {}
    for k in FREE_LOCALS:
        raw_l[k] = torch.tensor(
            _atanh_of(run.locs.get(k, 0.0), -run.lb, run.lb), dtype=torch.float64, requires_grad=True
        )
    dy = torch.zeros((), dtype=torch.float64, requires_grad=True)
    opt = torch.optim.Adam(list(raw_p.values()) + list(raw_l.values()) + [dy], lr=run.lr)

    for _it in range(run.iters):
        opt.zero_grad()
        v = inner_mesh(run, torch, raw_p, raw_l)
        loss = inner_loss(run, torch, cKDTree, v, dy, K)
        loss.backward()
        opt.step()

    inner_writeback(run, raw_p, raw_l)


# ===========================================================================
# the outer, measured loop
# ===========================================================================


def outer_targets(sex, steered, levers):
    """The (ratio, role) list the outer least squares solves.

    In: the ratios `steer_decision()` released and the levers it released them
    through. Out: every steered ratio as PRIMARY plus this sex's HOLD ratios, or
    an empty list when no lever is released at all.
    """
    if not levers:
        return []
    return [(n, PRIMARY) for n in steered] + [(n, HOLD) for n in OUTER[sex]['hold']]


def residual(run, M, tgts):
    """The signed z-distance of every outer target from TARGET_Z, and its tolerance.

    In: a measurement record and the (ratio, role) targets. Out: two arrays —
    `TARGET_Z - z` per target, and OUTER_TOL_MM expressed in that ratio's own
    standard deviations at delivered stature.
    """
    r, tol = [], []
    for name, _role in tgts:
        z, _x, _mu, sd, _b = ratio_z(M, run.sex, name, run.ref_obj)
        r.append(TARGET_Z - z)
        tol.append(OUTER_TOL_MM / (sd * run.target_h * 1000.0))
    return np.array(r), np.array(tol)


def jacobian(run, tgts, levers, r):
    """Finite-difference d(target z)/d(lever), ON THE REAL MEASUREMENT.

    Re-estimated every round: these responses are not linear over the ~1.0 morph
    units the male's lever has to travel. Each probe is a side-effect-free
    delivered-mesh measurement and is counted in `run.n_meas`.
    """
    J = np.zeros((len(tgts), len(levers)))
    for j, k in enumerate(levers):
        cur = float(run.locs.get(k, 0.0))
        step = FD_STEP if cur + FD_STEP <= run.lb else -FD_STEP
        probe = dict(run.locs)
        probe[k] = cur + step
        pp, vv, ff, _rec, Mp = _fit.snapshot_at(run.sex, run.phen, probe, run.anat, run.ref_obj)
        run.n_meas += 1
        rp, _t = residual(run, Mp, tgts)
        J[:, j] = (r - rp) / step  # d(z)/d(lever)
    return J


def damp_factor(step_vec, cur_values, lb):
    """The one factor the whole lever step is scaled by so no lever leaves the morph box.

    The morph cap is a design range, not a preference: past +/-0.8 MakeHuman targets
    bend anatomy instead of scaling it (the swayback). So the step is scaled down
    UNIFORMLY until every lever lands inside the box, rather than clipping one lever
    and letting the others take a step that no longer solves anything.

    In: the least-squares step, the levers' current values in the same order, and
    the box half-width. Out: a factor in 0.0..1.0.
    """
    damp = 1.0
    for j, cur in enumerate(cur_values):
        want = cur + step_vec[j]
        if abs(want) > lb and step_vec[j]:
            damp = min(damp, max(0.0, (math.copysign(lb, want) - cur) / step_vec[j]))
    return damp


def apply_lever_step(locs, levers, step_vec, damp, lb):
    """Move every lever by its damped step, clamped to the box and rounded to 4 decimals.

    Mutates and returns `locs`, which is the live local_changes dict of the run.
    """
    for j, k in enumerate(levers):
        cur = float(locs.get(k, 0.0))
        locs[k] = round(float(max(-lb, min(lb, cur + damp * step_vec[j]))), 4)
    return locs


# ===========================================================================
# the verbose trace
# ===========================================================================


def print_before(run, before, receipt, levers):
    """The pre-fit block: the measured baseline, both chamfers, and the steering receipt."""
    _zyg_log.info(
        '  %s BEFORE: height axis %.6f -> %.4fm  crotch %.5f (z %+.3f)'
        % (run.sex, before['height_axis'], before['stature_m'], before['crotch_frac'], before['crotch_z'])
    )
    _zyg_log.info(
        '    chamfer upper fwd %.2f rev %.2f mm | full-body fwd %.2f rev %.2f mm'
        % (
            before['chamfer_upper_fwd_mm'],
            before['chamfer_upper_rev_mm'],
            before['chamfer_full_fwd_mm'],
            before['chamfer_full_rev_mm'],
        )
    )
    for rec in receipt:
        _zyg_log.info(
            '    candidate %-42s z %+.3f p%-5.1f  %s'
            % (
                rec['ratio'],
                rec['z'],
                rec['percentile'],
                'STEERED via %s' % ', '.join(rec['levers'])
                if rec['steered']
                else 'not steered — ' + ' | '.join(rec['refused_because']),
            )
        )
    if not levers:
        _zyg_log.info(
            '    no lever is released on this body: no candidate is outside its '
            'band by more than the build resolution and its own pose bias. Only '
            'the leg constraint and the neutralised surface fit run.'
        )


def print_round(rnd, mid, tgts, r, tol):
    """One round's line: the leg residual, every outer target with its tolerance, both chamfers."""
    _zyg_log.info(
        '    round %d: crotch z %+.3f | %s | chamfer upper %.2f/%.2f full '
        '%.2f/%.2f mm'
        % (
            rnd,
            mid['crotch_z'],
            ' '.join('%s z %+.3f (tol %.3f)' % (n.split('_over_')[0], -r[i], tol[i]) for i, (n, _ro) in enumerate(tgts))
            or 'no outer target',
            mid['chamfer_upper_fwd_mm'],
            mid['chamfer_upper_rev_mm'],
            mid['chamfer_full_fwd_mm'],
            mid['chamfer_full_rev_mm'],
        )
    )


def print_levers(locs, levers, damp, lb):
    """The post-step line: where every lever landed, and by how much the step was damped."""
    _zyg_log.info(
        '      levers -> %s%s'
        % (
            ', '.join('%s %.4f' % (k, locs[k]) for k in levers),
            '' if damp >= 1.0 else '  (step damped x%.3f by the +/-%.1f cap)' % (damp, lb),
        )
    )


def print_regressions(regressions):
    """One GUARD line per survey-comparable ratio that left its band over the fit."""
    for g in regressions:
        _zyg_log.info(
            '    GUARD: %s left its band, %.4f (p%.1f) -> %.4f (p%.1f), band '
            '%.4f..%.4f'
            % (
                g['ratio'],
                g['before'],
                g['percentile_before'],
                g['after'],
                g['percentile_after'],
                g['band'][0],
                g['band'][1],
            )
        )


# ===========================================================================
# the loop, the assertions and the record
# ===========================================================================


def run_outer_loop(run, tgts, levers):
    """Alternate the inner fit with a damped Gauss-Newton step on the outer levers.

    In: the run and its outer targets/levers. Out: (K, trail, stepped) — the final
    constraint weight, one trail record per round, and whether the budget ran out
    immediately after a lever step (which the caller must repair).
    """
    K = 1.0
    trail = []
    stepped = False
    for rnd in range(run.rounds):
        # 1. the surface fit + the leg constraint, at the current lever values
        inner(run, K)
        _p, _v, _f, mid, M = snapshot(run, 'round%d.inner' % rnd)
        run.phen = _p
        run.n_meas += 1
        if abs(mid['crotch_z'] - TARGET_Z) > RATIO_Z_TOL and not run.freeze_inner:
            K *= 8.0
            if run.verbose:
                _zyg_log.info(
                    '    round %d: crotch residual %.3f sd > tol %.3f — raising the '
                    'constraint weight to %.0f' % (rnd, abs(mid['crotch_z'] - TARGET_Z), RATIO_Z_TOL, K)
                )
            inner(run, K)
            _p, _v, _f, mid, M = snapshot(run, 'round%d.inner.K%d' % (rnd, K))
            run.phen = _p
            run.n_meas += 1

        # 2. the measured constraints, on the DELIVERED mesh
        r, tol = residual(run, M, tgts)
        prim = [i for i, (_n, role) in enumerate(tgts) if role == PRIMARY]
        done = all(abs(r[i]) <= tol[i] for i in prim)
        mid['outer_residual_z'] = {tgts[i][0]: float(-r[i]) for i in range(len(tgts))}
        mid['outer_tol_z'] = {tgts[i][0]: float(tol[i]) for i in range(len(tgts))}
        mid['levers'] = {k: run.locs.get(k, 0.0) for k in levers}
        trail.append(mid)
        stepped = False
        if run.verbose:
            print_round(rnd, mid, tgts, r, tol)
        if done:
            break

        # 3. the finite-difference jacobian, then damped Gauss-Newton least squares
        #    over PRIMARY + HOLD together
        J = jacobian(run, tgts, levers, r)
        step_vec, _res, _rank, _sv = np.linalg.lstsq(J, r, rcond=None)
        damp = damp_factor(step_vec, [float(run.locs.get(k, 0.0)) for k in levers], run.lb)
        apply_lever_step(run.locs, levers, step_vec, damp, run.lb)
        stepped = True
        if run.verbose:
            print_levers(run.locs, levers, damp, run.lb)
    return K, trail, stepped


def result_problems(sex, after, tgts, r, tol, ref_obj):
    """One message per outer target that missed its contract; empty when all of them held.

    A PRIMARY target must have reached the population mean within its tolerance; a
    HOLD target must still be inside its p5-p95 band.
    """
    problems = []
    for i, (name, role) in enumerate(tgts):
        z = -r[i]
        b = ref_obj.band(name, sex)
        if role == PRIMARY and abs(z - TARGET_Z) > tol[i]:
            problems.append('%s is PRIMARY and did not reach the mean: z %+.3f, tol %.3f' % (name, z, tol[i]))
        if role == HOLD:
            x = after['ratios'][name]['value']
            lo, hi = float(b['lo']), float(b['hi'])
            if not (lo <= x <= hi):
                problems.append(
                    '%s is a HOLD target and left the p5-p95 band: %.4f not in %.4f..%.4f' % (name, x, lo, hi)
                )
    return problems


def check_result(run, after, M, tgts):
    """Raise unless the leg constraint and every outer target held on the DELIVERED mesh.

    Checked in the original's order: the leg constraint first, so a body whose
    crotch never reached the mean is refused before the outer targets are even
    measured. Out: the final (residual, tolerance) arrays, which the record reports.
    """
    if abs(after['crotch_z'] - TARGET_Z) > RATIO_Z_TOL:
        raise RuntimeError(
            '%s: the leg constraint was NOT met on the DELIVERED mesh — crotch z %+.3f, '
            'tolerance %.3f. The recipe is not written. Raise the iteration counts or '
            'widen the free set; do not move RATIO_Z_TOL.' % (run.sex, after['crotch_z'], RATIO_Z_TOL)
        )
    r, tol = residual(run, M, tgts)
    problems = result_problems(run.sex, after, tgts, r, tol, run.ref_obj)
    if problems:
        raise RuntimeError('%s: %s. The recipe is not written.' % (run.sex, '; '.join(problems)))
    return r, tol


def build_record(run, tgts, levers, receipt, before, after, trail, tol, regressions, K):
    """The returned record: the re-fitted recipe, every declared contract, and the receipts.

    `height` is deliberately NOT part of the emitted phenotype: build_originals()
    re-solves it by binary search against TARGET_HEIGHT_M after these morphs are
    baked, and a stale value in the table would be a number nobody uses.
    """
    out_phen = {k: vv for k, vv in run.phen.items() if k not in ('gender', 'height')}
    return {
        'schema': SCHEMA,
        'sex': run.sex,
        'phenotype': out_phen,
        'local_changes': dict(run.locs),
        'anatomy': dict(run.anat),
        'anatomy_dropped': list(ANATOMY_DROPPED),
        'free_phenotype': list(FREE_PHEN),
        'free_locals': list(FREE_LOCALS),
        'outer_levers_released': levers,
        'outer_targets': [{'ratio': n, 'role': ro} for n, ro in tgts],
        'steer_decision': receipt,
        'steer_tests': (
            '1 survey_comparable AND numerator provenance MEASURED AND not '
            'at_window_endpoint; 2 outside p5-p95; 3 band excess > OUTER_TOL_MM '
            '(%.1f mm, %s); 4 band excess > |a_pose_bias_mm| reported by the measurement'
            % (OUTER_TOL_MM, _OUTER_TOL_SOURCE)
        ),
        'held_head': dict(HELD_HEAD),
        'locked_substrings': list(LOCKED_SUBSTRINGS),
        'inner_target': {
            'ratio': INNER_TARGET,
            'z': TARGET_Z,
            'value': run.target_value,
            'mean': run.mu0,
            'sd': run.sd0,
            'source': run.band0['source'],
            'tolerance_z': RATIO_Z_TOL,
        },
        'outer_tolerance': {
            'mm': OUTER_TOL_MM,
            'source': _OUTER_TOL_SOURCE,
            'z': {tgts[i][0]: float(tol[i]) for i in range(len(tgts))},
        },
        'reference': os.path.relpath(run.ref_path, str(paths.PKG_DIR)),
        'reference_crotch_frac': run.ref_crotch,
        'reference_crotch_z': run.ref_crotch_z,
        'chamfer_neutralisation': (
            'every vertex below OUR crotch and every reference point below the '
            "REFERENCE's own crotch (%.4f, z %+.2f) is dropped from both chamfer terms; "
            'leg length is governed by the ANSUR constraint alone' % (run.ref_crotch, run.ref_crotch_z)
        ),
        'before': before,
        'after': after,
        'trail': trail,
        'constraint_weight_final': K,
        'measured_evaluations': run.n_meas,
        'inner_refit_ran': not run.freeze_inner,
        'band_regressions': regressions,
        'guard': (
            'no survey-comparable MEASURED ratio that was inside its p5-p95 band before the fit is outside it after'
            if not regressions
            else 'VIOLATED — see band_regressions'
        ),
    }
