# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from zyg_workflows.geom.head_fit.corr_map import (
    CHAR_MESH,
    EXPR_LANDMARK_MIN_M,
    JAW,
    JAW_WEIGHT,
    OUT_ROOT,
    YAW_LIMIT,
    _CACHE,
    correspondence,
    json,
    os,
    time,
)

# ── GNM landmark forward (linear, 68 points only) ────────────────────────────


def gnm_landmark_ops():
    """(template68 [68,3], id68 [253,68,3], ex68 [E,68,3], ex_keep [E]) — the
    linear GNM forward evaluated at the 68 barycentric landmark anchors only.
    17,821 vertices are never built during a landmark fit. ex_keep names the
    expression components that move a landmark at all (EXPR_LANDMARK_MIN_M);
    the rest are unidentifiable from 68 points and are not free parameters."""
    if 'lmops' in _CACHE:
        return _CACHE['lmops']
    import numpy as np
    from zyg_workflows.geom import gnm_head as GH

    z = np.load(os.path.join(GH.GNM_REPO, 'gnm', 'shape', 'data', 'versions', 'v3_0', 'gnm_head.npz'))
    idx, w = GH.landmarks_68()
    idx = np.asarray(idx)
    w = np.asarray(w)[..., None]
    tpl = (z['template_vertex_positions'][idx] * w).sum(1).astype('float32')
    idb = (z['vertex_identity_basis'][:, idx] * w[None]).sum(2).astype('float32')
    exb = (z['expression_basis'][:, idx] * w[None]).sum(2).astype('float32')
    keep = np.where(np.abs(exb).reshape(exb.shape[0], -1).max(1) > EXPR_LANDMARK_MIN_M)[0]
    _CACHE['lmops'] = (tpl, idb, exb[keep], keep)
    return _CACHE['lmops']


# ── the per-cell fit ─────────────────────────────────────────────────────────


def _cells(char_id):
    d = os.path.join(CHAR_MESH, char_id)
    return sorted(os.path.join(d, c) for c in os.listdir(d) if c.startswith('cell_'))


def _cell_targets(cell_dir):
    """(target68 [68,2] px, W, H, yaw) or (None, reason)."""
    import numpy as np

    with open(os.path.join(cell_dir, 'mesh.json'), encoding='utf-8') as f:
        mesh = json.load(f)
    if not mesh.get('face') or not mesh.get('face_landmarks'):
        return None, 'no_face'
    lm = np.asarray(mesh['face_landmarks'], np.float32)
    if lm.shape[0] < 468:
        return None, 'no_face'
    W, H = mesh['size']
    yaw = mesh.get('face_yaw')
    m = correspondence()['mp468_to_ibug68']
    return (lm[m][:, :2].astype('float32'), int(W), int(H), (float(yaw) if yaw is not None else None)), None


def _cell_state(target, W, H, yaw, tpl, seed_yaw):
    """Per-cell free parameters, ALL O(1) by construction.

    The first version of this solver put cx, cy (hundreds of px) and tz (~1 m)
    in one Adam group and diverged to 127 px rms: a 0.02 step is a rounding
    error for a principal point and a bolt for a depth. Everything is
    normalised instead —
        tz  = tz0 * exp(log_tz)         tz0 from GNM's own inter-ocular metres
                                        against the detected inter-ocular px
        cx  = cx0 + dc[0] * f           cx0 chosen so the INITIAL projection
        cy  = cy0 + dc[1] * f           centroid lands on the target centroid
    — so one learning rate is right for every parameter, and the residual is
    divided by f, which makes the loss the same number on any image size.
    """
    import numpy as np
    import torch

    F_PX = 1.35 * max(W, H)
    io_m = float(np.linalg.norm(tpl[36] - tpl[45]))
    io_px = float(np.linalg.norm(target[36] - target[45])) or 40.0
    tz0 = max(0.15, F_PX * io_m / io_px)
    # centroid-matching principal point at the seed pose, identity/expression 0
    import roma

    R0 = roma.rotvec_to_rotmat(torch.tensor([0.0, float(seed_yaw), 0.0])).numpy()
    p0 = tpl @ R0.T
    zc0 = np.maximum(tz0 - p0[:, 2], 0.05)
    cx0 = float(target[:, 0].mean() - (F_PX * p0[:, 0] / zc0).mean())
    cy0 = float(target[:, 1].mean() - (F_PX * (-p0[:, 1]) / zc0).mean())
    return {
        'T': torch.from_numpy(np.ascontiguousarray(target)),
        'F': F_PX,
        'tz0': tz0,
        'cx0': cx0,
        'cy0': cy0,
        'log_tz': torch.zeros(1, requires_grad=True),
        'dc': torch.zeros(2, requires_grad=True),
        'rv': torch.tensor([0.0, float(seed_yaw), 0.0], requires_grad=True),
    }


def _project_batch(ident, expr, st, tpl_t, idb_t, exb_t):
    """Project 68 GNM landmarks into N cells at once.

    Vectorised deliberately: the per-cell Python loop this replaced took ~54 s
    for ONE cell, which is ~25 min for a 27-cell joint solve and ~75 min for the
    three solves a character needs. Identity is SHARED across the batch (that is
    the whole point of the joint solve); expression, rotation, depth and
    principal point are per cell.

    Returns (uv [N,68,2] px, zc [N,68] m).
    """
    import torch
    import roma

    v = (tpl_t.reshape(-1) + ident @ idb_t).reshape(68, 3)  # [68,3]
    v = v.unsqueeze(0) + (expr @ exb_t).reshape(-1, 68, 3)  # [N,68,3]
    R = roma.rotvec_to_rotmat(st['rv'])  # [N,3,3]
    p = torch.einsum('nkj,nij->nki', v, R)
    tz = st['tz0'] * torch.exp(st['log_tz'])  # [N]
    zc = (tz.unsqueeze(1) - p[..., 2]).clamp(min=0.05)  # [N,68]
    f = st['F'].unsqueeze(1)
    x = f * p[..., 0] / zc + (st['cx0'] + st['dc'][:, 0] * st['F']).unsqueeze(1)
    y = f * (-p[..., 1]) / zc + (st['cy0'] + st['dc'][:, 1] * st['F']).unsqueeze(1)
    return torch.stack([x, y], -1), zc


def _solve_batch(
    cells,
    identity=None,
    fit_identity=True,
    seed_yaw=0.0,
    iters=(250, 600),
    id_prior=1.0,
    ex_prior=1.0,
    jaw_weight=None,
    log=None,
):
    """The one solver. `cells` is a list of (name, target68, W, H, yaw).

    ONE identity is shared across every cell in the list — a single-cell call is
    just the joint solve with a list of one, which is why the per-cell fit and
    the character fit cannot drift apart. `fit_identity=False` freezes
    `identity` (zero = the mean-head NULL) and leaves camera, rotation and
    expression exactly as free as the fitted arm, so the two arms differ in
    identity and in nothing else.

    Stage 0 solves camera + rotation with identity and expression pinned at
    zero; stage 1 releases them. Returns (identity_np, [per-cell report]).

    THE PRIORS ARE NOT MAGIC NUMBERS. The objective is a MAP estimate:
        sum_i w_i * ||proj_i - target_i||^2 / (2 sigma_px^2)
            + id_prior * 0.5 * ||identity||^2
            + ex_prior * 0.5 * ||expression||^2
    GNM's coefficient spaces are documented as unit-normal with a [-3,3] range,
    so 0.5*||c||^2 IS the negative log prior at id_prior = ex_prior = 1 and
    nothing has to be tuned. sigma_px is the landmark noise floor, taken per
    cell from the MEASURED correspondence residual (5.17 mm rms) converted to
    px through that cell's own initial depth — an image where the head is 200 px
    tall gets a looser sigma than one where it fills the frame, automatically.
    An earlier version divided the residual by f and hand-picked the weights;
    the expression prior then outweighed the data term by ~150x and expression
    came back at L2 0.001 on every cell, i.e. silently disabled.
    """
    import numpy as np
    import torch

    tpl, idb, exb, _keep = gnm_landmark_ops()
    # raw weights: 1.0 per reliable landmark, JAW_WEIGHT on the jawline. NOT
    # normalised to sum 1 — that would divide the data term by 68 and let the
    # unit-normal priors dominate, which is the bug this replaced.
    w_np = landmark_weights(jaw_weight)
    w = torch.from_numpy(w_np).reshape(1, 68, 1)
    tpl_t = torch.from_numpy(tpl)
    idb_t = torch.from_numpy(idb.reshape(idb.shape[0], -1))
    exb_t = torch.from_numpy(exb.reshape(exb.shape[0], -1))
    corr_mm = float(correspondence()['residual_rms_mm'])

    states = [_cell_state(t, W, H, y, tpl, (y if y is not None else seed_yaw)) for _nm, t, W, H, y in cells]
    N = len(states)
    st = {
        'T': torch.stack([c['T'] for c in states]),  # [N,68,2]
        'F': torch.tensor([c['F'] for c in states], dtype=torch.float32),
        'tz0': torch.tensor([c['tz0'] for c in states], dtype=torch.float32),
        'cx0': torch.tensor([c['cx0'] for c in states], dtype=torch.float32),
        'cy0': torch.tensor([c['cy0'] for c in states], dtype=torch.float32),
        'log_tz': torch.zeros(N, requires_grad=True),
        'dc': torch.zeros(N, 2, requires_grad=True),
        'rv': torch.stack([c['rv'] for c in states]).detach().requires_grad_(True),
    }
    mmpp0 = st['tz0'] / st['F'] * 1000.0
    sigma = torch.clamp(corr_mm / mmpp0, min=2.0)  # [N]

    if identity is None:
        ident = torch.zeros(idb.shape[0], requires_grad=fit_identity)
    else:
        ident = torch.from_numpy(np.asarray(identity, 'float32')).clone()
        ident.requires_grad_(bool(fit_identity))
    expr = torch.zeros(N, exb.shape[0], requires_grad=True)
    zero_id = torch.zeros(idb.shape[0])

    groups = [{'params': [st['rv'], st['dc'], st['log_tz']], 'lr': 0.02}, {'params': [expr], 'lr': 0.02}]
    if fit_identity:
        groups.append({'params': [ident], 'lr': 0.03})
    opt = torch.optim.Adam(groups)
    for stage, n in enumerate(iters):
        for _ in range(n):
            opt.zero_grad()
            use_id = ident if stage >= 1 else zero_id
            use_ex = expr if stage >= 1 else torch.zeros_like(expr)
            pr, _zc = _project_batch(use_id, use_ex, st, tpl_t, idb_t, exb_t)
            data = (w * (pr - st['T']) ** 2).sum(dim=(1, 2)) / (2 * sigma**2)
            loss = data.sum()
            if stage >= 1:
                loss = loss + ex_prior * 0.5 * (expr**2).sum()
                if fit_identity:
                    loss = loss + id_prior * 0.5 * (ident**2).sum()
            loss.backward()
            opt.step()
        if log:
            log(
                f'[head_fit]   stage {stage}: {N} cells, data '
                f'{float(data.sum()):.1f}, |id| max {float(ident.abs().max()):.2f}'
            )

    reps = []
    with torch.no_grad():
        pr, zc = _project_batch(ident, expr, st, tpl_t, idb_t, exb_t)
        err = torch.linalg.norm(pr - st['T'], dim=2)  # [N,68]
        wsum = float(w.sum())
        for i, (nm, _t, W, H, yaw) in enumerate(cells):
            e = err[i]
            mmpp = float(zc[i].mean() / st['F'][i] * 1000.0)
            rms = float((e**2).mean().sqrt())
            reps.append(
                {
                    'cell': nm,
                    'state': 'fitted',
                    'yaw': yaw,
                    'size': [W, H],
                    'rms_px': rms,
                    'weighted_rms_px': float(((w.reshape(68) * e**2).sum() / wsum).sqrt()),
                    'sigma_px': float(sigma[i]),
                    'p95_px': float(e.quantile(0.95)),
                    'max_px': float(e.max()),
                    'nojaw_rms_px': float((e[17:] ** 2).mean().sqrt()),
                    'mm_per_px': mmpp,
                    'rms_mm': rms * mmpp,
                    'nojaw_rms_mm': float((e[17:] ** 2).mean().sqrt()) * mmpp,
                    'rotvec': [round(float(x), 4) for x in st['rv'][i]],
                    'tz_m': float(st['tz0'][i] * torch.exp(st['log_tz'][i])),
                    'f_px': float(st['F'][i]),
                    'principal_px': [
                        float(st['cx0'][i] + st['dc'][i, 0] * st['F'][i]),
                        float(st['cy0'][i] + st['dc'][i, 1] * st['F'][i]),
                    ],
                    'expression_l2': float(torch.linalg.norm(expr[i])),
                }
            )
    return ident.detach().numpy().copy(), reps


def fit_cell(cell_dir, fit_identity=True, identity=None, jaw_weight=None, log=print):
    """Fit one cell. Returns a four-state record: fitted / no_face / declined /
    failed — never a silent success."""
    name = os.path.basename(cell_dir)
    got, reason = _cell_targets(cell_dir)
    if got is None:
        return {'cell': name, 'state': 'no_face', 'reason': reason}
    target, W, H, yaw = got
    if yaw is not None and abs(yaw) > YAW_LIMIT:
        return {
            'cell': name,
            'state': 'declined',
            'reason': f'|yaw| {abs(yaw):.2f} rad past the {YAW_LIMIT} limit — '
            'the fixed jawline correspondence stops meaning anything',
        }
    try:
        idn, reps = _solve_batch(
            [(name, target, W, H, yaw)], identity=identity, fit_identity=fit_identity, jaw_weight=jaw_weight
        )
    except Exception as exc:
        return {'cell': name, 'state': 'failed', 'reason': f'{type(exc).__name__}: {exc}'}
    rec = dict(reps[0])
    rec['identity'] = [round(float(x), 5) for x in idn]
    return rec


def landmark_weights(jaw_weight=None):
    """Per-landmark fit weight: jawline at `jaw_weight` (default JAW_WEIGHT),
    everything else 1.0."""
    import numpy as np

    w = np.ones(68, dtype='float32')
    w[JAW] = JAW_WEIGHT if jaw_weight is None else float(jaw_weight)
    return w


def fit_character(char_id, holdout_every=3, jaw_weight=None, log=print):
    """Joint GNM identity over a character's frontal + three-quarter cells, then
    the held-out evaluation against the mean-head null.

    Three solves, in this order and never fewer:
      1. JOINT   — one identity shared over the TRAIN cells, per-cell camera,
                   rotation and expression free.
      2. HELD-OUT FIT — that identity frozen onto cells it never saw; only
                   camera, rotation and expression are solved.
      3. HELD-OUT NULL — identity ZERO on the same held-out cells, with exactly
                   the same freedoms. This is what "doing nothing" scores, and
                   identity gain is the difference. Nothing else is ever
                   reported as identity capacity.
    """
    import numpy as np

    t0 = time.time()
    ledger = {'fitted': [], 'no_face': [], 'declined': [], 'failed': []}
    usable = []
    for cd in _cells(char_id):
        nm = os.path.basename(cd)
        got, reason = _cell_targets(cd)
        if got is None:
            ledger['no_face'].append(nm)
            continue
        target, W, H, yaw = got
        if yaw is not None and abs(yaw) > YAW_LIMIT:
            ledger['declined'].append(nm)
            continue
        usable.append((nm, target, W, H, yaw))
    if len(usable) < 4:
        return {
            'summary': {
                'character': char_id,
                'error': f'only {len(usable)} usable cells',
                'ledger': {k: len(v) for k, v in ledger.items()},
            }
        }
    train = [c for i, c in enumerate(usable) if i % holdout_every]
    test = [c for i, c in enumerate(usable) if not i % holdout_every]
    ledger['fitted'] = [c[0] for c in usable]
    log(
        f'[head_fit] {char_id}: {len(usable)} usable cells '
        f'({len(train)} train / {len(test)} held out), '
        f'{len(ledger["no_face"])} no_face, {len(ledger["declined"])} declined'
    )

    idn, train_rep = _solve_batch(train, fit_identity=True, jaw_weight=jaw_weight)
    _z, test_fit = _solve_batch(test, identity=idn, fit_identity=False, jaw_weight=jaw_weight)
    _z, test_null = _solve_batch(test, identity=np.zeros_like(idn), fit_identity=False, jaw_weight=jaw_weight)

    rows = []
    for a, b in zip(test_fit, test_null):
        rows.append(
            {
                'cell': a['cell'],
                'yaw': a['yaw'],
                'fit_rms_px': a['rms_px'],
                'null_rms_px': b['rms_px'],
                'fit_rms_mm': a['rms_mm'],
                'null_rms_mm': b['rms_mm'],
                'fit_nojaw_mm': a['nojaw_rms_mm'],
                'null_nojaw_mm': b['nojaw_rms_mm'],
                'gain_px': b['rms_px'] - a['rms_px'],
                'gain_mm': b['rms_mm'] - a['rms_mm'],
                'mm_per_px': a['mm_per_px'],
            }
        )

    def rms(xs):
        return float(np.sqrt(np.mean(np.asarray(xs, dtype='float64') ** 2)))

    summary = {
        'character': char_id,
        'jaw_weight': JAW_WEIGHT if jaw_weight is None else float(jaw_weight),
        'n_usable': len(usable),
        'n_train': len(train),
        'n_test': len(test),
        'ledger': {k: len(v) for k, v in ledger.items()},
        'train_rms_px': rms([r['rms_px'] for r in train_rep]),
        'heldout_fit_rms_px': rms([r['fit_rms_px'] for r in rows]),
        'heldout_null_rms_px': rms([r['null_rms_px'] for r in rows]),
        'heldout_fit_rms_mm': rms([r['fit_rms_mm'] for r in rows]),
        'heldout_null_rms_mm': rms([r['null_rms_mm'] for r in rows]),
        'identity_gain_px': rms([r['null_rms_px'] for r in rows]) - rms([r['fit_rms_px'] for r in rows]),
        'identity_gain_mm': rms([r['null_rms_mm'] for r in rows]) - rms([r['fit_rms_mm'] for r in rows]),
        # THE HEADLINE NUMBERS ARE THE NO-JAW ONES. With JAW_WEIGHT at 0 the
        # jawline is not in the objective, so an all-68 rms is dominated by 17
        # landmarks the fit was never asked to move (and which the two head
        # models disagree about by 35 mm anyway). Both are reported so the
        # difference is visible rather than chosen silently.
        'heldout_fit_nojaw_mm': rms([r['fit_nojaw_mm'] for r in rows]),
        'heldout_null_nojaw_mm': rms([r['null_nojaw_mm'] for r in rows]),
        'identity_gain_nojaw_mm': rms([r['null_nojaw_mm'] for r in rows]) - rms([r['fit_nojaw_mm'] for r in rows]),
        'identity_gain_nojaw_pct': 100.0
        * (1.0 - rms([r['fit_nojaw_mm'] for r in rows]) / max(rms([r['null_nojaw_mm'] for r in rows]), 1e-9)),
        'cells_improved': int(sum(1 for r in rows if r['gain_px'] > 0)),
        'cells_improved_nojaw': int(sum(1 for r in rows if r['null_nojaw_mm'] > r['fit_nojaw_mm'])),
        'identity_l2': float(np.linalg.norm(idn)),
        'coeff_absmax': float(np.abs(idn).max()),
        'saturated_2p5': int((np.abs(idn) > 2.5).sum()),
        'saturated_3p0': int((np.abs(idn) >= 2.999).sum()),
        'n_identity_dims': int(len(idn)),
        'n_expression_dims_free': int(gnm_landmark_ops()[2].shape[0]),
        'n_expression_dims_total': 383,
        'holdout_every': holdout_every,
        'correspondence_rms_mm': correspondence()['residual_rms_mm'],
        'elapsed_s': round(time.time() - t0, 1),
    }
    doc = {
        'summary': summary,
        'identity': [round(float(x), 5) for x in idn],
        'heldout': rows,
        'train': train_rep,
        'ledger_cells': ledger,
        'date': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    out_dir = os.path.join(OUT_ROOT, char_id)
    os.makedirs(out_dir, exist_ok=True)
    tag = '' if jaw_weight is None else f'_jaw{jaw_weight:g}'
    with open(os.path.join(out_dir, f'fit{tag}.json'), 'w', encoding='utf-8') as f:
        json.dump(doc, f, indent=1)
    from zyg_workflows.geom import gnm_head as GH

    GH.export_glb(
        os.path.join(out_dir, f'gnm_headfit_{char_id}{tag}.glb'),
        GH.vertices_for({**GH.neutral_params(), 'identity': idn.astype('float32')}),
    )
    log(
        f'[head_fit] {char_id}: HELD-OUT (no-jaw) fit '
        f'{summary["heldout_fit_nojaw_mm"]:.2f} mm  NULL(mean head) '
        f'{summary["heldout_null_nojaw_mm"]:.2f} mm  -> gain '
        f'{summary["identity_gain_nojaw_mm"]:+.2f} mm '
        f'({summary["identity_gain_nojaw_pct"]:.0f}%, '
        f'{summary["cells_improved_nojaw"]}/{len(rows)} cells improved)'
    )
    log(
        f'[head_fit] {char_id}: all-68 fit {summary["heldout_fit_rms_mm"]:.2f} mm vs '
        f'null {summary["heldout_null_rms_mm"]:.2f} mm (jaw carried, not fitted); '
        f'|id|max {summary["coeff_absmax"]:.2f}, sat>2.5 {summary["saturated_2p5"]}, '
        f'|id|L2 {summary["identity_l2"]:.2f}'
    )
    return doc


def run(chars=None, holdout_every=3, jaw_weight=None, log=print):
    os.makedirs(OUT_ROOT, exist_ok=True)
    if not chars:
        chars = sorted(os.listdir(CHAR_MESH))
    docs = []
    for c in chars:
        try:
            docs.append(fit_character(c, holdout_every=holdout_every, jaw_weight=jaw_weight, log=log))
        except Exception as exc:
            log(f'[head_fit] {c} FAILED: {type(exc).__name__}: {exc}')
            docs.append({'character': c, 'error': f'{type(exc).__name__}: {exc}'})
    tag = '' if jaw_weight is None else f'_jaw{jaw_weight:g}'
    with open(os.path.join(OUT_ROOT, f'summary{tag}.json'), 'w', encoding='utf-8') as f:
        json.dump([d.get('summary', d) for d in docs], f, indent=1)
    log('')
    log(
        f'{"character":14s} {"jawW":>5s} {"held":>5s} {"fitMM":>7s} {"nullMM":>7s} '
        f'{"gainMM":>7s} {"gain%":>6s} {"impr":>6s} {"|id|max":>8s} {"sat":>4s}'
    )
    for d in docs:
        s = d.get('summary')
        if not s or 'heldout_fit_nojaw_mm' not in s:
            continue
        log(
            f'{s["character"]:14s} {s["jaw_weight"]:5.2f} {s["n_test"]:5d} '
            f'{s["heldout_fit_nojaw_mm"]:7.2f} {s["heldout_null_nojaw_mm"]:7.2f} '
            f'{s["identity_gain_nojaw_mm"]:+7.2f} {s["identity_gain_nojaw_pct"]:6.1f} '
            f'{s["cells_improved_nojaw"]:3d}/{s["n_test"]:<2d} '
            f'{s["coeff_absmax"]:8.2f} {s["saturated_2p5"]:4d}'
        )
    log(
        '(fitMM/nullMM are held-out landmark rms over iBUG 17-67 — the landmarks '
        'the objective actually uses; NULL is the mean head with its own camera.)'
    )
    return docs


def _require(cond: object, msg: str) -> None:
    """Raise :class:`RuntimeError` when *cond* is falsy — an ``assert`` that survives ``-O``."""
    if not cond:
        raise RuntimeError(msg)


def smoke(log=print):
    import numpy as np

    c = correspondence()
    _require(len(c['mp468_to_ibug68']) == 68, 'map is not 68 long')
    _require(len(set(c['mp468_to_ibug68'])) == 68, 'map is not injective')
    _require(c['ibug_ordering_check']['verdict'] == 'same ordering', 'ICT/GNM 68 disagree')
    tpl, idb, exb, keep = gnm_landmark_ops()
    _require(tpl.shape == (68, 3) and idb.shape == (253, 68, 3), 'landmark ops broken')
    _require(0 < exb.shape[0] <= 383, 'expression selection broken')
    from zyg_workflows.geom import gnm_head as GH

    ref = GH.landmark_points(GH.vertices_for(GH.neutral_params()))
    _require(np.abs(ref - tpl).max() < 1e-5, 'landmark template diverges from gnm_head')
    pi = GH.sample_identity(3)
    ref2 = GH.landmark_points(GH.vertices_for({**GH.neutral_params(), 'identity': pi}))
    mine = tpl + np.tensordot(pi, idb, axes=(0, 0))
    err = float(np.abs(ref2 - mine).max())
    _require(err < 1e-5, f'linear landmark forward diverges by {err:.2e} m')
    log(
        f'[head_fit] SMOKE PASS — 68-map injective, corr rms '
        f'{c["residual_rms_mm"]} mm, {exb.shape[0]}/383 expression dims move a '
        f'landmark, linear forward matches gnm_head to {err:.2e} m'
    )
    return True
