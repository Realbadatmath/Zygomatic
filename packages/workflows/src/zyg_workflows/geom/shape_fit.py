# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""shape_fit.py — a BOUNDED body-shape solve from a character's own sheet (2026-09-02).

RUN:
    python3 -m zyg_workflows.geom.shape_fit <char_id> --body <registry name> [--cells ...]
                              [--holdout 3] [--iters 400] [--seed 0]

WHAT WAS MISSING. geom.anny_fit solves camera, global rotation and pose. Its body is an
INPUT — since 2026-09-02 the registered recipe, before that a height-only calibration —
and no code anywhere read a body's SHAPE off the drawn sheet. So a character whose art
consistently shows a heavier or longer-limbed build than the registry records had no way
to say so, and every plate carried the declared build regardless.

WHAT THIS SOLVES, AND WHAT IT REFUSES TO SOLVE. Free: the three anny macro axes that are
about build — muscle, weight, proportions — within +-0.3 of the declared values, and
eight `measure-*` locals within +-0.8. FIXED, never fitted: age, height and gender. That
is the same rule geom.phenotype states for the fitter and for the same reason: monocular
evidence cannot separate a short adult from a child, and the bible has already declared
those three. A solver allowed to move them would "explain" a boy as a shrunken man and
report a lower error for it.

WHY BOTH SILHOUETTE AND KEYPOINTS, AND WHY THE LOCALS ARE CAPPED AT 0.8.
Keypoints alone constrain a stick figure: they pin joint centres and say nothing about
girth, so a keypoint-only objective is free to inflate or starve the body at zero cost.
Silhouette alone is a WIDTH metric in one view, and the swayback lesson from the head
work applies verbatim — a solver graded only on how wide the body looks from the front
will dump every unexplained millimetre into the side profile, where nothing is looking.
Two defences, both cheap: the locals are capped so no single morph can run away, and the
receipt renders FRONT AND SIDE before and after. A number that improves while the side
view deforms is a failure this pipeline has already shipped once.

THE OBJECTIVE. Shape is SHARED across a character's cells; camera and global yaw are
per-cell NUISANCE parameters and are re-solved alongside it. Pose is frozen at the value
geom.anny_fit found — this is a shape solve, not a re-fit. Evidence per cell:

  keypoints   real MediaPipe detections only (visibility >= 0.5 AND on canvas), never
              the fitter's synthetic arms-down targets: the prior must not grade itself.
  silhouette  the signed distance field of the person mask (regions.png), sampled at the
              projected mesh's own outline vertices. Signed, so it is two-sided: a body
              too wide and a body too narrow are both penalised. The outline is
              recomputed every iteration by angular binning around the projected
              centroid — an ICP-style correspondence, non-differentiable in the choice
              and differentiable in the positions.

UPPER-MODE CELLS ARE NOT EXCLUDED, THEY ARE CROPPED. Only 6 of abel's 44 cells carry
hips and knees, so a full-mode-only solve would have almost no data. An upper fit's body
below `draw_limit_y` is imagination (geom.body_grid draws nothing there and says why),
so both the mask and the mesh outline are cut at that line and the silhouette term sees
only the part the evidence supports.

TWO NULLS, AND THE GATE. Every number is reported beside:
  null A  the declared body, deltas all zero — literally doing nothing.
  null B  the mean anny body (muscle/weight/proportions 0.5, no locals) at the declared
          age, height and gender.
Both nulls get their per-cell camera and yaw re-solved on the held-out cells exactly as
the fit does, so the comparison is of SHAPE and not of how much nuisance-fitting each arm
was allowed. A third of the cells are held out. The gate: the solve must beat both nulls
on held-out reprojection AND held-out silhouette IoU, or the receipt says the sheet does
not carry shape information beyond the declared build. Not beating the nulls is a result.

OUTPUT IS A CANDIDATE, NOT A BODY. The deltas are written to
`data/assets/mesh_skeletons/candidates/<name>_shape_fit.json` with the measurements
inside. Nothing here touches the registry: reissuing a registered body is the operator's
decision, taken on a printed before/after cage hash.
"""

import argparse
import os
import sys
import time

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from . import char_mesh as _char_mesh

# re-exported: shape_fit_stages reads the cell root as shape_fit.OUT_ROOT
OUT_ROOT = _char_mesh.OUT_ROOT

# The three anny macro axes that are about BUILD. age/height/gender are declared and
# stay out of this list; that is the whole point of the module.
MACRO_AXES = ('muscle', 'weight', 'proportions')
MACRO_BOUND = 0.3
MACRO_RANGE = (0.0, 1.0)

# A SMALL set, chosen because a front-and-side sheet can actually see each one: two
# lengths, four girths, two heights. anny exposes 20 `measure-*` morphs; opening all of
# them to a 2D objective is how a solver finds a body that projects correctly and stands
# up wrong.
LOCAL_AXES = (
    'measure-shoulder-dist-incr',
    'measure-waist-circ-incr',
    'measure-hips-circ-incr',
    'measure-neck-circ-incr',
    'measure-upperarm-circ-incr',
    'measure-thigh-circ-incr',
    'measure-upperleg-height-incr',
    'measure-lowerleg-height-incr',
)
LOCAL_BOUND = 0.8
LOCAL_RANGE = (-1.0, 1.0)

SIL_WEIGHT = 0.6  # px against px — the two terms are in the same unit

# A CELL EARNS ITS SILHOUETTE TERM, MEASURED, and most do not.
#
# The person mask (regions.png) is the CLOTHED character. On a cell whose fit already
# lands on the drawing, the naked body sits a little inside it and the residual is about
# BUILD — measured on abel cell_24: median signed distance -9.4 px, 15% of outline
# points outside. On an upper-mode cell it is not: with only head and shoulders pinned,
# the unobserved body projects wherever the prior leaves it, and the same measurement on
# cell_00 and cell_08 reads +337 and +360 px with 84-86% of the outline outside the mask.
# That is not a shape residual, it is a fit that was never constrained below the neck —
# geom.body_grid refuses to DRAW those regions for the same reason.
#
# Feeding both to one objective lets the second kind dominate: the silhouette term at
# step 0 of the first trial run was ~170 against a keypoint term of ~10, and the solve
# diverged from 13.7 px to 75.2 px train error while "improving" its own loss. So a cell
# contributes silhouette evidence only if, AT THE DECLARED BODY, its outline already
# lies within SIL_QUALIFY_PX of the drawn outline. Everything else contributes keypoints
# only, and the receipt reports how many qualified.
SIL_QUALIFY_PX = 40.0
N_OUTLINE_BINS = 180
SDF_SCALE = 2  # the distance field is sampled at half resolution


# ---------------------------------------------------------------------------------
# bounded parameters
# ---------------------------------------------------------------------------------
def _bounds(declared, bound, rng):
    """The delta interval for one axis: the requested bound, clipped to the axis's own
    valid range so the solve never has to clamp (a clamp at the edge kills the gradient
    and the optimiser then sits there reporting a value it cannot move)."""
    lo = max(-bound, rng[0] - declared)
    hi = min(bound, rng[1] - declared)
    if hi <= lo:  # declared already outside the range
        return 0.0, 0.0
    return lo, hi


def _delta(u, lo, hi):
    import torch

    return lo + (hi - lo) * torch.sigmoid(u)


def _u0(lo, hi):
    """The raw value whose delta is exactly zero — so every solve STARTS at the declared
    body and any movement away from it had to be paid for by the evidence."""
    if hi <= lo:
        return 0.0
    f = min(max((0.0 - lo) / (hi - lo), 1e-4), 1 - 1e-4)
    return float(np.log(f / (1 - f)))


# ---------------------------------------------------------------------------------
# evidence
# ---------------------------------------------------------------------------------
def _sdf(mask, y_limit=None):
    """Signed distance to the person-mask boundary, in ORIGINAL pixels, positive
    outside. Zero on the outline, which is what the silhouette term drives to."""
    m = (mask > 0).astype(np.uint8)
    if y_limit is not None:
        m = m.copy()
        m[int(max(y_limit, 0)) :, :] = 0
    if m.max() == 0:
        return None
    small = cv2.resize(m, (m.shape[1] // SDF_SCALE, m.shape[0] // SDF_SCALE), interpolation=cv2.INTER_NEAREST)
    if small.max() == 0:
        return None
    d_out = cv2.distanceTransform(1 - small, cv2.DIST_L2, 5)
    d_in = cv2.distanceTransform(small, cv2.DIST_L2, 5)
    return ((d_out - d_in) * SDF_SCALE).astype(np.float32)


def _cell_evidence(cell_dir, fit, mesh):
    """(targets Nx2, label list, mask, sdf, y_limit) or None if the cell carries none."""
    from . import keypoints as K

    W, H = mesh['size']
    b = np.asarray(mesh['body_landmarks'], np.float32)
    names = (
        'nose',
        'left_eye',
        'right_eye',
        'left_ear',
        'right_ear',
        'left_shoulder',
        'right_shoulder',
        'left_elbow',
        'right_elbow',
        'left_wrist',
        'right_wrist',
        'left_hip',
        'right_hip',
        'left_knee',
        'right_knee',
        'left_ankle',
        'right_ankle',
    )
    tgt, labels = [], []
    for n in names:
        x, y, v = b[K.P[n]]
        if float(v) >= 0.5 and 0 <= x < W and 0 <= y < H:
            tgt.append([float(x), float(y)])
            labels.append(n)
    if len(tgt) < 6:
        return None
    y_limit = fit.get('draw_limit_y') if fit.get('fit_mode') == 'upper' else None
    rm = cv2.imread(os.path.join(cell_dir, 'regions.png'), cv2.IMREAD_GRAYSCALE)
    mask = (rm > 0).astype(np.uint8) if rm is not None else None
    sdf = _sdf(mask, y_limit) if mask is not None else None
    return np.array(tgt, np.float32), labels, mask, sdf, y_limit


def _outline_idx(xy, n_bins=N_OUTLINE_BINS):
    """Indices of the projected points forming the 2D outline: the farthest point from
    the centroid in each angular bin. Cheap, robust to the mesh being a closed body, and
    recomputed every step so the correspondence follows the shape."""
    c = xy.mean(axis=0)
    d = xy - c
    r = np.hypot(d[:, 0], d[:, 1])
    a = np.arctan2(d[:, 1], d[:, 0])
    bins = np.clip(((a + np.pi) / (2 * np.pi) * n_bins).astype(np.int32), 0, n_bins - 1)
    out = np.full(n_bins, -1, np.int64)
    best = np.zeros(n_bins, np.float32)
    for i in range(len(xy)):
        bi = bins[i]
        if r[i] > best[bi]:
            best[bi] = r[i]
            out[bi] = i
    return out[out >= 0]


# ---------------------------------------------------------------------------------
# the solve
# ---------------------------------------------------------------------------------
def _project(kp3, gaa, cam, rotmat):
    """kp3 (K,3) in body space -> (K,2) pixels, the pinhole model anny_fit v2.1 uses."""
    import torch

    p = kp3 @ rotmat(gaa).T.to(kp3.dtype)
    f, tz, cx, cy = cam[0], cam[1], cam[2], cam[3]
    z = (p[:, 1] + tz).clamp(min=0.25)
    return torch.stack([f * p[:, 0] / z + cx, f * (-p[:, 2]) / z + cy], -1)


def _sample_sdf(sdf_t, xy, W, H):
    """Bilinear sample of the (H/S, W/S) distance field at original-pixel coords."""
    import torch

    gx = (xy[:, 0] / max(W - 1, 1)) * 2 - 1
    gy = (xy[:, 1] / max(H - 1, 1)) * 2 - 1
    g = torch.stack([gx, gy], -1)[None, None]
    v = torch.nn.functional.grid_sample(
        sdf_t[None, None], g, mode='bilinear', padding_mode='border', align_corners=True
    )
    return v[0, 0, 0]


class _Arm:
    """One body hypothesis (the solve, or a null) and the machinery to score it."""

    def __init__(
        self, name, model, phen_declared, local_declared, spec, free_macro=True, free_local=True, override=None
    ):
        import torch

        self.name = name
        self.m = model
        self.spec = spec
        self.phen_declared = dict(phen_declared)
        self.local_declared = dict(local_declared)
        self.override = override  # a fixed body: no free shape at all
        self.u_macro, self.u_local, self.mb, self.lb = [], [], [], []
        if override is None:
            for ax in MACRO_AXES:
                lo, hi = _bounds(float(phen_declared.get(ax, 0.5)), MACRO_BOUND, MACRO_RANGE)
                self.mb.append((lo, hi))
                self.u_macro.append(torch.tensor(_u0(lo, hi), requires_grad=free_macro))
            for ax in LOCAL_AXES:
                lo, hi = _bounds(float(local_declared.get(ax, 0.0)), LOCAL_BOUND, LOCAL_RANGE)
                self.lb.append((lo, hi))
                self.u_local.append(torch.tensor(_u0(lo, hi), requires_grad=free_local))

    def params(self):
        return [u for u in self.u_macro + self.u_local if u.requires_grad]

    def body_kwargs(self):
        import torch
        from . import phenotype as PH

        if self.override is not None:
            phen, loc = dict(self.override[0]), dict(self.override[1])
            return (
                {k: torch.tensor(float(v)) for k, v in phen.items()},
                {k: torch.tensor(float(v)) for k, v in loc.items()},
            )
        phen = {k: torch.tensor(float(v)) for k, v in self.phen_declared.items()}
        for ax, u, (lo, hi) in zip(MACRO_AXES, self.u_macro, self.mb):
            phen[ax] = torch.tensor(float(self.phen_declared.get(ax, 0.5))) + _delta(u, lo, hi)
        loc = {k: torch.tensor(float(v)) for k, v in self.local_declared.items()}
        for ax, u, (lo, hi) in zip(LOCAL_AXES, self.u_local, self.lb):
            loc[ax] = torch.tensor(float(self.local_declared.get(ax, 0.0))) + _delta(u, lo, hi)
        _ = PH  # the spec's bone scales are applied by the caller, not here
        return phen, loc

    def readable(self):
        import torch

        with torch.no_grad():
            phen, loc = self.body_kwargs()
        d_macro = {ax: round(float(phen[ax]) - float(self.phen_declared.get(ax, 0.5)), 4) for ax in MACRO_AXES}
        d_local = {ax: round(float(loc.get(ax, 0.0)) - float(self.local_declared.get(ax, 0.0)), 4) for ax in LOCAL_AXES}
        return {
            'phenotype': {k: round(float(v), 4) for k, v in phen.items()},
            'local_changes': {k: round(float(v), 4) for k, v in loc.items()},
            'delta_macro': d_macro,
            'delta_local': d_local,
        }


def _forward(arm, cells, pose_cache, S44, labels_key, regressors):
    """One forward pass of arm's body -> per-cell 3D keypoints and vertices."""
    import torch

    phen, loc = arm.body_kwargs()
    outs = {}
    for c in cells:
        kw = {'phenotype_kwargs': phen}
        if loc:
            kw['local_changes_kwargs'] = loc
        pose = pose_cache[c['cell']]
        from .anny_fit import _pose44

        R = _pose44(pose)
        if S44 is not None:
            RS = R[..., :3, :3] @ S44[..., :3, :3].to(R.dtype)
            kw['pose_parameters'] = torch.cat([torch.cat([RS, R[..., :3, 3:4]], -1), R[..., 3:4, :]], -2)
        else:
            kw['pose_parameters'] = R
        outs[c['cell']] = arm.m(**kw)
    return outs


OUTLINE_EVERY = 10  # steps between outline correspondence updates
OUTLINE_STRIDE = 2  # every Nth vertex is a candidate outline point


def _cell_loss(out, cell, cam, gaa, regressor, rotmat, use_sil=True, step=0):
    """Weighted keypoint + silhouette loss for one cell.

    The outline correspondence is refreshed every OUTLINE_EVERY steps rather than every
    step: it is an ICP-style assignment and re-deriving it 400 times per cell costs more
    than it buys — the body moves by fractions of a pixel between steps. The POSITIONS
    of the chosen vertices are of course current every step, which is what carries the
    gradient.
    """
    import torch

    kp3 = regressor(out)[0].to(torch.float32)
    pr = _project(kp3, gaa, cam, rotmat)
    kp = torch.nn.functional.smooth_l1_loss(pr, cell['tgt_t'], beta=8.0)
    err_px = float(torch.linalg.norm((pr - cell['tgt_t']).detach(), dim=-1).mean())
    sil = torch.zeros((), dtype=torch.float32)
    if use_sil and cell.get('sdf_t') is not None:
        v = out['vertices'][0].to(torch.float32)
        xy = _project(v, gaa, cam, rotmat)
        idx = cell.get('_outline_idx')
        if idx is None or step % OUTLINE_EVERY == 0:
            with torch.no_grad():
                xyn = xy.detach().numpy()
            cand = np.arange(0, len(xyn), OUTLINE_STRIDE)
            if cell.get('y_limit'):
                cand = cand[xyn[cand, 1] < float(cell['y_limit'])]
            if len(cand) > 50:
                idx = cand[_outline_idx(xyn[cand])]
            else:
                idx = cand
            cell['_outline_idx'] = idx
        if len(idx) > 10:
            d = _sample_sdf(cell['sdf_t'], xy[idx], cell['W'], cell['H'])
            sil = torch.nn.functional.smooth_l1_loss(d, torch.zeros_like(d), beta=8.0)
    return kp + SIL_WEIGHT * sil, err_px, float(sil.detach())


def _solve_nuisance(arm, cells, pose_cache, S44, regressors, iters=150, lr=0.02):
    """Re-solve per-cell camera and global rotation with the body FROZEN.

    Every arm gets this, including the nulls, so the held-out comparison is between
    BODIES and not between how much freedom each arm was given to move the camera.
    """
    import torch
    from .anny_fit import _rotmat

    # The body is FROZEN here, so its forward pass is evaluated once, without a graph.
    # Keeping the graph would mean backward()-ing through the same saved tensors on
    # every step, which torch refuses — and rebuilding it every step would pay for a
    # 13,718-vertex forward that cannot change.
    with torch.no_grad():
        outs = _forward(arm, cells, pose_cache, S44, None, regressors)
        outs = {
            k: {kk: (vv.detach() if hasattr(vv, 'detach') else vv) for kk, vv in v.items()} for k, v in outs.items()
        }
    for c in cells:
        c['cam'] = torch.tensor(c['cam0'], dtype=torch.float32, requires_grad=True)
        c['gaa'] = torch.tensor(c['gaa0'], dtype=torch.float32, requires_grad=True)
    opt = torch.optim.Adam([p for c in cells for p in (c['cam'], c['gaa'])], lr=lr)  # noqa
    for it in range(iters):
        opt.zero_grad()
        total = 0.0
        for c in cells:
            l, _e, _s = _cell_loss(outs[c['cell']], c, c['cam'], c['gaa'], regressors[c['cell']], _rotmat, step=it)
            total = total + l
        total.backward()
        # f is fixed by anny_fit (1.35*max(W,H)); only tz/cx/cy may move
        for c in cells:
            c['cam'].grad[0] = 0.0
        opt.step()
    return outs


def _score(arm, cells, pose_cache, S44, regressors, nuisance_iters=120):
    """Held-out score for one arm: mean reprojection px and silhouette IoU."""
    import torch
    from .anny_fit import _rotmat

    outs = _solve_nuisance(arm, cells, pose_cache, S44, regressors, iters=nuisance_iters)
    errs, ious = [], []
    per_cell = {}
    for c in cells:
        with torch.no_grad():
            _l, e, _s = _cell_loss(outs[c['cell']], c, c['cam'], c['gaa'], regressors[c['cell']], _rotmat)
            iou = _iou(outs[c['cell']], c, c['cam'], c['gaa'], _rotmat, arm.m)
        errs.append(e)
        per_cell[c['cell']] = {'err_px': round(e, 2), 'iou': None if iou is None else round(iou, 4)}
        if iou is not None:
            ious.append(iou)
    return {
        'n_cells': len(cells),
        'median_err_px': round(float(np.median(errs)), 2) if errs else None,
        'mean_err_px': round(float(np.mean(errs)), 2) if errs else None,
        'n_iou_cells': len(ious),
        'median_iou': round(float(np.median(ious)), 4) if ious else None,
        'mean_iou': round(float(np.mean(ious)), 4) if ious else None,
        'per_cell': per_cell,
    }


def _iou(out, cell, cam, gaa, rotmat, model):
    """MEASURED silhouette IoU — a real rasterisation, not the soft term the solver saw.

    The optimiser is graded on a distance field; if it were also SCORED on one, the
    metric would be the objective and could not falsify it. So the score rasterises the
    posed mesh and intersects it with the person mask."""
    import torch

    if cell.get('mask') is None:
        return None
    with torch.no_grad():
        v = out['vertices'][0].to(torch.float32)
        xy = _project(v, gaa, cam, rotmat).numpy()
    faces = model.faces.numpy() if hasattr(model.faces, 'numpy') else np.asarray(model.faces)
    H, W = cell['H'], cell['W']
    img = np.zeros((H, W), np.uint8)
    pts = xy.astype(np.int32)
    for q in faces:
        quad = pts[q]
        if quad[:, 0].max() < 0 or quad[:, 0].min() >= W:
            continue
        if quad[:, 1].max() < 0 or quad[:, 1].min() >= H:
            continue
        cv2.fillConvexPoly(img, quad, 1)
    m = (cell['mask'] > 0).astype(np.uint8)
    if cell.get('y_limit'):
        m = m.copy()
        m[int(cell['y_limit']) :, :] = 0
        img[int(cell['y_limit']) :, :] = 0
    inter = int((img & m).sum())
    union = int((img | m).sum())
    return None if union == 0 else inter / union


def _render_views(arm, model, S44, out_png, label):
    """Front AND side rest renders. The side view is the point: a width-only objective
    improves the front and can wreck the profile, and only looking catches it."""
    import torch
    from .anny_fit import _rotmat

    with torch.no_grad():
        phen, loc = arm.body_kwargs()
        kw = {'phenotype_kwargs': {k: torch.tensor(float(v)) for k, v in phen.items()}}
        if loc:
            kw['local_changes_kwargs'] = {k: torch.tensor(float(v)) for k, v in loc.items()}
    if S44 is not None:
        kw['pose_parameters'] = S44
    with torch.no_grad():
        o = model(**kw)
        v = o['vertices'][0].to(torch.float32).numpy()
    faces = model.faces.numpy() if hasattr(model.faces, 'numpy') else np.asarray(model.faces)
    from .anny_animate import render_depth

    H = W = 520
    tiles = []
    for yaw, nm in ((0.0, 'front'), (np.pi / 2, 'side')):
        R = _rotmat(torch.tensor([0.0, 0.0, float(yaw)])).numpy()
        p = v @ R.T
        span = max(p[:, 2].max() - p[:, 2].min(), 1e-3)
        s = 0.86 * H / span
        cx = W / 2 - 0.5 * (p[:, 0].max() + p[:, 0].min()) * s
        cy = H / 2 + 0.5 * (p[:, 2].max() + p[:, 2].min()) * s
        img = render_depth(v, faces, [s, cx, cy], R, W, H, camera_model='ortho')
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        cv2.putText(img, '%s %s' % (label, nm), (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (60, 255, 140), 1, cv2.LINE_AA)
        tiles.append(img)
    cv2.imwrite(out_png, np.concatenate(tiles, axis=1))
    return out_png


def run(
    char_id,
    body,
    cells=None,
    holdout=3,
    iters=400,
    seed=0,
    lr=0.05,
    nuisance_iters=150,
    batch=10,
    out_dir=None,
    log=print,
):
    """Solve the free shape axes of `char_id`'s sheet against the registry body,
    gate the result on held-out cells and write the candidate document.

    The stages are in shape_fit_stages; this is the order they run in. The import
    is deferred because that module reads this one's constants and primitives.
    """
    import torch

    from . import shape_fit_stages as ST

    t0 = time.time()
    torch.manual_seed(seed)
    rng = np.random.RandomState(seed)

    ctx = ST.resolve_body(char_id, body, log=log, seed=seed, t0=t0)
    ST.collect_cells(ctx, cells)
    ST.qualify_silhouettes(ctx)
    ST.split_cells(ctx, rng, holdout)
    ST.build_arms(ctx)
    ST.train_fit_arm(ctx, rng, iters=iters, lr=lr, batch=batch)
    ST.score_arms(ctx, nuisance_iters=nuisance_iters)

    gate = ST.build_gate(ctx.scores)
    ST.finish_gate(gate, ctx.arms, ctx.name, ctx.arms['fit'].readable())
    return ST.write_candidate(ctx, gate, out_dir)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('char_id')
    ap.add_argument('--body', default='')
    ap.add_argument('--cells', default='')
    ap.add_argument('--holdout', type=int, default=3, help='1/N of cells held out')
    ap.add_argument('--iters', type=int, default=400)
    ap.add_argument('--nuisance-iters', type=int, default=150)
    ap.add_argument('--batch', type=int, default=10, help='train cells per step (0 = full batch)')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--lr', type=float, default=0.05)
    a = ap.parse_args(argv)
    doc = run(
        a.char_id,
        a.body,
        cells=a.cells or None,
        holdout=a.holdout,
        iters=a.iters,
        seed=a.seed,
        lr=a.lr,
        nuisance_iters=a.nuisance_iters,
        batch=a.batch,
    )
    return 0 if doc['gate']['state'] in ('found', 'not_detectable') else 1


if __name__ == '__main__':
    sys.exit(main())
