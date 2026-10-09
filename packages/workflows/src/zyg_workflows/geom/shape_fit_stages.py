# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""shape_fit_stages — the stages `shape_fit.run` is made of (2026-10-09).

`run` was one 357-line function. It is now an orchestrator over these stages, in
the order it always ran them:

    resolve_body -> collect_cells -> qualify_silhouettes -> split_cells
    -> build_arms -> train_fit_arm -> score_arms
    -> build_gate -> finish_gate -> write_candidate

`RunContext` carries what the stages share (the registry body, the cell pool, the
arms, the scores); everything else is a parameter. Nothing was retuned: the same
cells are skipped for the same reasons, the same log lines go out in the same
order, and the candidate document carries the same keys in the same order.

The judgement is in three PURE functions — `build_gate`, `gate_verdict` and
`saturated_axes` — so the gate can be exercised on plain dictionaries without a
body model, a GPU or torch. tests/test_shape_fit_helpers.py does exactly that.
"""

import glob
import json
import os
import time
from dataclasses import dataclass, field

import numpy as np

from zyg_workflows.geom import shape_fit as SF


@dataclass
class RunContext:
    """One shape solve, as the stages hand it on.

    `m` is the anny body model, `S44` its bone-scale matrix, `spec` the registry
    record the three fixed axes come from. `pool` is the usable cells, `skipped`
    says why the others are not in it, and `arms` holds the fit and the two nulls.
    """

    char_id: str
    name: str
    spec: dict
    m: object
    S44: object
    phen_declared: dict
    local_declared: dict
    root: str
    log: object
    seed: int = 0
    t0: float = 0.0
    pool: list = field(default_factory=list)
    pose_cache: dict = field(default_factory=dict)
    regressors: dict = field(default_factory=dict)
    skipped: dict = field(default_factory=dict)
    train: list = field(default_factory=list)
    hold: list = field(default_factory=list)
    arms: dict = field(default_factory=dict)
    hist: list = field(default_factory=list)
    scores: dict = field(default_factory=dict)
    iters: int = 0
    batch_n: int = 0


def resolve_body(char_id, body, log=print, seed=0, t0=None):
    """The RunContext for a character and a registry body name: the body model,
    its bone scales and the DECLARED phenotype the solve is bounded around.
    Raises SystemExit when neither `body` nor `char_id` names a registered body."""
    from zyg_workflows.geom import phenotype as PH

    name = PH.resolve_body_name(body) or PH.resolve_body_name(char_id)
    if not name:
        raise SystemExit('%r does not resolve to a registered body' % (body or char_id))
    spec = PH.registry_body(name, log=log)
    m = PH.body_model(spec)
    return RunContext(
        char_id=char_id,
        name=name,
        spec=spec,
        m=m,
        S44=PH.bone_scale_matrix(spec, m),
        phen_declared=dict(spec['phenotype_kwargs']),
        local_declared=dict(spec['local_changes']),
        root=os.path.join(SF.OUT_ROOT, char_id),
        log=log,
        seed=seed,
        t0=time.time() if t0 is None else t0,
    )


def cell_refusal(fit, name):
    """Why this cell's fit report cannot be used, or '' when it can.

    THE POSE MUST COME FROM A FIT OF THIS BODY. After the 2026-09-02 refit,
    anny_fit.json is a mix: cells whose source image is drift-quarantined still
    carry their pre-refit report (see fit_body_index.json beside the cells). Those
    poses were solved against a DIFFERENT body — for abel, the anny default adult
    female — so holding them fixed here would ask this solve to explain the sheet
    with someone else's joint angles. Some of them also predate the pinhole camera
    and carry a 3-element orthographic `camera`, which is how the first full run
    found this: IndexError on cam[3].
    """
    if not fit.get('fit_ok') or 'pose_aa' not in fit:
        return 'fit gated or poseless'
    fb = fit.get('body') or {}
    if fb.get('source') != 'registry' or fb.get('name') != name:
        return 'fit carries body %r, not the registry body %r' % (
            fb.get('name') or fb.get('source') or 'none',
            name,
        )
    if fit.get('camera_model') != 'pinhole' or len(fit.get('camera') or []) != 4:
        return 'not a pinhole fit'
    return ''


def collect_cells(ctx, cells=None):
    """Fill ctx.pool / pose_cache / regressors from the character's cell
    directories, recording in ctx.skipped why every rejected cell was rejected.
    `cells` is an optional comma-separated subset of cell names."""
    import torch
    from anny.keypoints import KeypointsRegressor

    dirs = (
        [os.path.join(ctx.root, c.strip()) for c in cells.split(',') if c.strip()]
        if cells
        else sorted(glob.glob(os.path.join(ctx.root, 'cell_*')))
    )
    for d in dirs:
        fp = os.path.join(d, 'anny_fit.json')
        mp = os.path.join(d, 'mesh.json')
        if not (os.path.exists(fp) and os.path.exists(mp)):
            ctx.skipped[os.path.basename(d)] = 'no fit or mesh'
            continue
        fit = json.load(open(fp))
        why = cell_refusal(fit, ctx.name)
        if why:
            ctx.skipped[os.path.basename(d)] = why
            continue
        mesh = json.load(open(mp))
        if not os.path.exists(mesh.get('image', '')):
            ctx.skipped[os.path.basename(d)] = 'source image gone'
            continue
        ev = SF._cell_evidence(d, fit, mesh)
        if ev is None:
            ctx.skipped[os.path.basename(d)] = 'fewer than 6 real keypoints'
            continue
        tgt, labels, mask, sdf, y_limit = ev
        W, H = mesh['size']
        cell = {
            'cell': os.path.basename(d),
            'dir': d,
            'W': W,
            'H': H,
            'tgt_t': torch.tensor(tgt),
            'labels': labels,
            'mask': mask,
            'sdf_t': None if sdf is None else torch.tensor(sdf),
            'y_limit': y_limit,
            'mode': fit.get('fit_mode'),
            'cam0': [float(x) for x in fit['camera']],
            'gaa0': [float(x) for x in fit['global_aa']],
        }
        ctx.pool.append(cell)
        ctx.pose_cache[cell['cell']] = torch.tensor(fit['pose_aa'], dtype=torch.float32)
        ctx.regressors[cell['cell']] = KeypointsRegressor(ctx.m, labels=labels).double()


def qualify_silhouettes(ctx):
    """── does each cell's silhouette carry shape, or only a loose fit? ───────────

    Sets sil_ok / sil_med_abs_px on every pooled cell and DROPS the distance field
    of the cells that do not qualify, so they contribute keypoints only. Raises
    SystemExit when fewer than 6 cells are usable at all."""
    import torch

    from zyg_workflows.geom import phenotype as PH
    from zyg_workflows.geom.anny_fit import _rotmat

    n_sil = 0
    for c in ctx.pool:
        c['sil_ok'], c['sil_med_abs_px'] = False, None
        if c.get('sdf_t') is None:
            continue
        kwq = PH.forward_kwargs(ctx.spec, ctx.pose_cache[c['cell']], model=ctx.m, scale44=ctx.S44)
        with torch.no_grad():
            oq = ctx.m(**kwq)
            v = oq['vertices'][0].to(torch.float32)
            xy = SF._project(v, torch.tensor(c['gaa0']), torch.tensor(c['cam0']), _rotmat)
            xyn = xy.numpy()
            cand = np.arange(0, len(xyn), SF.OUTLINE_STRIDE)
            if c.get('y_limit'):
                cand = cand[xyn[cand, 1] < float(c['y_limit'])]
            if len(cand) <= 50:
                continue
            idx = cand[SF._outline_idx(xyn[cand])]
            vals = SF._sample_sdf(c['sdf_t'], xy[idx], c['W'], c['H']).numpy()
        c['sil_med_abs_px'] = round(float(np.median(np.abs(vals))), 1)
        c['sil_ok'] = c['sil_med_abs_px'] <= SF.SIL_QUALIFY_PX
        if not c['sil_ok']:
            c['sdf_t'] = None  # keypoints only for this cell
        else:
            n_sil += 1
    ctx.log(
        '  silhouette evidence qualified on %d of %d cells (median |sdf| <= %.0f px at '
        'the declared body)' % (n_sil, len(ctx.pool), SF.SIL_QUALIFY_PX)
    )
    if len(ctx.pool) < 6:
        raise SystemExit('only %d usable cells (%s) — too few to hold a third out' % (len(ctx.pool), ctx.skipped))


def split_pool(pool, rng, holdout):
    """(train, hold): a 1/holdout random slice of the pool is held out, never fewer
    than two cells. The permutation comes from the caller's seeded RandomState, so
    the split is reproducible from the seed alone."""
    order = rng.permutation(len(pool))
    n_hold = max(2, len(pool) // holdout)
    return [pool[i] for i in order[n_hold:]], [pool[i] for i in order[:n_hold]]


def split_cells(ctx, rng, holdout):
    """Hold a third of the pool out and say so on the log."""
    ctx.train, ctx.hold = split_pool(ctx.pool, rng, holdout)
    ctx.log(
        '  %d usable cells: %d train, %d held out (seed %d). skipped %d'
        % (len(ctx.pool), len(ctx.train), len(ctx.hold), ctx.seed, len(ctx.skipped))
    )


def build_arms(ctx):
    """The three hypotheses: the free fit, the declared body (doing nothing) and
    the mean anny body at the declared age, height and gender."""
    ctx.arms = {
        'fit': SF._Arm('fit', ctx.m, ctx.phen_declared, ctx.local_declared, ctx.spec),
        'null_declared': SF._Arm(
            'null_declared',
            ctx.m,
            ctx.phen_declared,
            ctx.local_declared,
            ctx.spec,
            override=(ctx.phen_declared, ctx.local_declared),
        ),
        'null_mean_anny': SF._Arm(
            'null_mean_anny',
            ctx.m,
            ctx.phen_declared,
            ctx.local_declared,
            ctx.spec,
            override=(
                {
                    **{k: 0.5 for k in SF.MACRO_AXES},
                    'age': ctx.phen_declared['age'],
                    'height': ctx.phen_declared['height'],
                    'gender': ctx.phen_declared.get('gender', 0.0),
                },
                {},
            ),
        ),
    }


def train_fit_arm(ctx, rng, iters=400, lr=0.05, batch=10):
    """── train the fit arm on the training cells (camera and yaw free alongside) ──

    Two learning rates on purpose: the shape parameters are logits through a
    sigmoid and need a bigger step than the camera, which anny_fit itself refines
    at 0.02.

    MINIBATCH over cells. The shape parameters are shared, so every cell in the
    batch sees the same eleven numbers and a subset is an unbiased gradient
    estimate of the full objective. The cost that forces it is real: one anny
    forward+backward per cell per step, so a 35-cell full-batch solve at 200 steps
    is 7,000 of them. The camera of a cell not in the batch simply does not move
    that step.
    """
    import torch

    from zyg_workflows.geom.anny_fit import _rotmat

    fit_arm = ctx.arms['fit']
    for c in ctx.train:
        c['cam'] = torch.tensor(c['cam0'], dtype=torch.float32, requires_grad=True)
        c['gaa'] = torch.tensor(c['gaa0'], dtype=torch.float32, requires_grad=True)
    opt = torch.optim.Adam(
        [
            {'params': fit_arm.params(), 'lr': lr},
            {'params': [p for c in ctx.train for p in (c['cam'], c['gaa'])], 'lr': 0.02},
        ]
    )
    ctx.iters = iters
    ctx.batch_n = min(batch or len(ctx.train), len(ctx.train))
    for it in range(iters):
        opt.zero_grad()
        sel = (
            [ctx.train[i] for i in rng.choice(len(ctx.train), ctx.batch_n, replace=False)]
            if ctx.batch_n < len(ctx.train)
            else ctx.train
        )
        outs = SF._forward(fit_arm, sel, ctx.pose_cache, ctx.S44, None, ctx.regressors)
        total, errs = 0.0, []
        for c in sel:
            l, e, _s = SF._cell_loss(
                outs[c['cell']], c, c['cam'], c['gaa'], ctx.regressors[c['cell']], _rotmat, step=it
            )
            total = total + l
            errs.append(e)
        total = total / max(len(sel), 1)
        total.backward()
        for c in sel:
            if c['cam'].grad is not None:
                c['cam'].grad[0] = 0.0
        opt.step()
        if it % 40 == 0 or it == iters - 1:
            ctx.hist.append(
                {
                    'iter': it,
                    'loss': round(float(total.detach()), 4),
                    'train_median_err_px': round(float(np.median(errs)), 2),
                }
            )
            ctx.log(
                '    it %3d loss %.4f train median err %.2f px' % (it, float(total.detach()), float(np.median(errs)))
            )


def score_arms(ctx, nuisance_iters=150):
    """── score every arm on the HELD-OUT cells, each with its own nuisance solve ──"""
    for nm, arm in ctx.arms.items():
        ctx.scores[nm] = SF._score(
            arm, ctx.hold, ctx.pose_cache, ctx.S44, ctx.regressors, nuisance_iters=nuisance_iters
        )
        ctx.log(
            '  %-15s held-out median %s px | median IoU %s (n=%d)'
            % (nm, ctx.scores[nm]['median_err_px'], ctx.scores[nm]['median_iou'], ctx.scores[nm]['n_iou_cells'])
        )
    ctx.scores['fit_train'] = SF._score(
        ctx.arms['fit'], ctx.train, ctx.pose_cache, ctx.S44, ctx.regressors, nuisance_iters=nuisance_iters
    )


def beats(x, y, lower_is_better):
    """Whether x wins against y, or None when either number is missing — an
    unmeasurable comparison is not a won one."""
    if x is None or y is None:
        return None
    return (x < y) if lower_is_better else (x > y)


def build_gate(scores):
    """── the gate ────────────────────────────────────────────────────────────────

    The solve must beat BOTH nulls on held-out median reprojection px AND on
    held-out median silhouette IoU. `state` is 'found' when it does,
    'not_detectable' when the IoU comparison was possible and it did not, and
    'unmeasurable' when IoU was unavailable on the held-out cells.
    """
    f, a, b = scores['fit'], scores['null_declared'], scores['null_mean_anny']
    beats_err = all(beats(f['median_err_px'], n['median_err_px'], True) for n in (a, b))
    iou_states = [beats(f['median_iou'], n['median_iou'], False) for n in (a, b)]
    beats_iou = None if any(s is None for s in iou_states) else all(iou_states)
    return {
        'rule': 'held-out cells must beat BOTH nulls on median reprojection px AND median silhouette IoU',
        'beats_both_on_reprojection': bool(beats_err),
        'beats_both_on_iou': beats_iou,
        'state': (
            'found'
            if (beats_err and beats_iou)
            else 'not_detectable'
            if (beats_iou is not None and not (beats_err and beats_iou))
            else 'unmeasurable'
        ),
    }


def gate_verdict(state):
    """The sentence the receipt carries for a gate state."""
    return (
        'the sheet carries shape information beyond the declared build'
        if state == 'found'
        else 'the sheet does NOT carry shape information beyond the declared build — the '
        'solved deltas do not beat doing nothing on held-out cells, so nothing here '
        'should be baked'
        if state == 'not_detectable'
        else 'unmeasurable: silhouette IoU was unavailable on the held-out cells'
    )


def saturated_axes(readable):
    """DID THE SOLVE RUN INTO ITS OWN BOUNDS? An axis sitting on the cap is a
    parameter the evidence wanted to push further, and a solve that saturates and
    still loses to doing nothing is losing for a reason the caps did not cause."""
    sat = {k: v for k, v in list(readable['delta_macro'].items()) if abs(v) >= 0.98 * SF.MACRO_BOUND}
    sat.update({k: v for k, v in readable['delta_local'].items() if abs(v) >= 0.98 * SF.LOCAL_BOUND})
    return sat


def nulls_are_identical(arms):
    """ARE THE TWO NULLS ACTUALLY TWO? For a body whose registered macro axes are
    all 0.5 with no local morphs — abel is exactly that — "the declared body" and
    "the mean anny body at the declared age and height" are the SAME body, and
    reporting them as two nulls would claim two independent tests where there is
    one. Checked, not assumed: the two arms' bodies are compared numerically."""
    import torch

    with torch.no_grad():
        pa, la = arms['null_declared'].body_kwargs()
        pb, lb = arms['null_mean_anny'].body_kwargs()
    return (
        set(pa) == set(pb)
        and all(abs(float(pa[k]) - float(pb[k])) < 1e-9 for k in pa)
        and set(la) == set(lb)
        and all(abs(float(la[k]) - float(lb[k])) < 1e-9 for k in la)
    )


def finish_gate(gate, arms, name, readable):
    """Add to a built gate, in the order the receipt reads them: whether the two
    nulls are one body, which axes saturated, and the verdict."""
    same = nulls_are_identical(arms)
    gate['nulls_are_the_same_body'] = bool(same)
    if same:
        gate['nulls_note'] = (
            'null_declared and null_mean_anny are the SAME body here: %r registers '
            'muscle/weight/proportions at 0.5 with no local morphs, which is the mean '
            'anny body at its declared age and height. This is ONE null reported twice, '
            'not two independent ones.' % name
        )
    gate['saturated_axes'] = saturated_axes(readable)
    gate['verdict'] = gate_verdict(gate['state'])


def render_arms(ctx, out_dir):
    """── renders ─────────────────────────────────────────────────────────────────

    Front AND side rest renders of the declared body, the solve and the mean anny
    null, written under `out_dir`."""
    os.makedirs(out_dir, exist_ok=True)
    return {
        'before': SF._render_views(
            ctx.arms['null_declared'], ctx.m, ctx.S44, os.path.join(out_dir, '%s_before.png' % ctx.name), 'declared'
        ),
        'after': SF._render_views(
            ctx.arms['fit'], ctx.m, ctx.S44, os.path.join(out_dir, '%s_after.png' % ctx.name), 'solved'
        ),
        'null_mean_anny': SF._render_views(
            ctx.arms['null_mean_anny'],
            ctx.m,
            ctx.S44,
            os.path.join(out_dir, '%s_null_mean.png' % ctx.name),
            'mean anny',
        ),
    }


def candidate_doc(ctx, gate, renders, body_rd):
    """The candidate document: what was fixed, what was free, what was solved, the
    evidence it was solved on and the gate's verdict. A CANDIDATE — nothing in it
    has been applied to any registered body."""
    return {
        'kind': 'shape_fit_candidate',
        'written': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'by': 'geom.shape_fit (session S02, mesh identity plan 2026-09-02)',
        'NOT_A_REISSUE': 'This is a CANDIDATE delta measured off the character sheet. '
        "Baking it into the registry is a reissue, which is S04's and "
        "the operator's decision on a printed before/after cage hash. "
        'Nothing in this file has been applied to any registered body.',
        'registry_body': ctx.name,
        'char_id': ctx.char_id,
        'cage_vert_sha256_at_solve_time': ctx.spec.get('cage_vert_sha256_rebuilt'),
        'fixed': {
            'age': ctx.phen_declared['age'],
            'height': ctx.phen_declared['height'],
            'gender': ctx.phen_declared.get('gender'),
            'why': 'declared in the bible; monocular evidence cannot separate a '
            'short adult from a child, so these are never fitted',
        },
        'free': {
            'macro_axes': list(SF.MACRO_AXES),
            'macro_bound': SF.MACRO_BOUND,
            'local_axes': list(SF.LOCAL_AXES),
            'local_bound': SF.LOCAL_BOUND,
        },
        'solved': body_rd,
        'evidence': {
            'cells_total': len(ctx.pool),
            'train': [c['cell'] for c in ctx.train],
            'holdout': [c['cell'] for c in ctx.hold],
            'seed': ctx.seed,
            'skipped': ctx.skipped,
            'silhouette_qualified': {c['cell']: c['sil_med_abs_px'] for c in ctx.pool if c['sil_ok']},
            'silhouette_rejected': {c['cell']: c['sil_med_abs_px'] for c in ctx.pool if not c['sil_ok']},
            'silhouette_qualify_px': SF.SIL_QUALIFY_PX,
            'batch_cells_per_step': ctx.batch_n,
            'iters': ctx.iters,
            'terms': 'real MediaPipe keypoints (>=0.5 visibility, on canvas) '
            'and the signed distance field of regions.png sampled at '
            'the projected mesh outline; upper-mode cells cropped at '
            'draw_limit_y',
            'silhouette_weight': SF.SIL_WEIGHT,
        },
        'scores': {k: {kk: vv for kk, vv in v.items() if kk != 'per_cell'} for k, v in ctx.scores.items()},
        'scores_per_cell': {k: v['per_cell'] for k, v in ctx.scores.items()},
        'nulls': {
            'null_declared': 'the registered body, all deltas zero — doing nothing',
            'null_mean_anny': 'muscle/weight/proportions 0.5, no local morphs, at the declared age, height and gender',
        },
        'gate': gate,
        'renders': renders,
        'history': ctx.hist,
        'seconds': round(time.time() - ctx.t0, 1),
    }


def write_candidate(ctx, gate, out_dir=None):
    """── renders and the candidate file ──────────────────────────────────────────

    Render the three bodies, write the candidate JSON beside the registry's own
    candidates and return the document."""
    renders = render_arms(ctx, out_dir or os.path.join(ctx.root, 'shape_fit'))
    cand_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(SF.__file__))),
        'data',
        'assets',
        'mesh_skeletons',
        'candidates',
    )
    os.makedirs(cand_dir, exist_ok=True)
    cand_path = os.path.join(cand_dir, '%s_shape_fit.json' % ctx.name)
    doc = candidate_doc(ctx, gate, renders, ctx.arms['fit'].readable())
    with open(cand_path, 'w') as fh:
        json.dump(doc, fh, indent=1)
    ctx.log('  candidate -> %s' % cand_path)
    ctx.log('  GATE: %s — %s' % (gate['state'], gate['verdict']))
    return doc
