# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""gnm_fit.py — Phase 1 of the GNM head bridge: fit GNM identity to each
registered anny head, and MEASURE whether the space can reach them.

RUN:
    /usr/bin/python3.12 -m zyg_workflows.geom.gnm_fit run [--bodies male,female,abel,cornelis]
                                            [--outer 24] [--inner 30] [--no-render]

WHY THIS EXISTS. Replacing a registered body's head with a GNM head (the
neck-seam bridge) is only worth building if GNM's identity space can actually
REPRODUCE the heads we already ship — same person, not a random scan face. This
module answers that with numbers before any mesh is cut. The known hard case is
abel: GNM was built from ~5,000 scan subjects and scan corpora are usually
adults, so a 12-year-old head may sit outside the space. The tell is not just
surface error — it is identity coefficients ramming the documented [-3,3] wall
(`clip_hits`): a fit that only reaches a child by saturating the space has not
really reached it.

WHAT IS FITTED. Free parameters: GNM identity (253) + a similarity transform
(log-scale, rotation, translation). Expression stays zero; jaw/neck/eye joints
stay zero; teeth/eyeball identity components have no correspondence in the fit
region so the L2 prior keeps them near zero (reported, not hidden).

CORRESPONDENCE, STATED EXACTLY. Target = the body rebuilt from its OWN
params.json through mesh_skeletons._build_mesh (the reissue choke point, hand
correction included), cropped to vertices whose skinning weight on
{head, jaw, eye.L, eye.R} exceeds 0.3 — skull + face + ears, no neck, so the
neck-seam question stays out of Phase 1 entirely. Source = GNM vertices in
`skin_exterior` at or above the chin landmark's height (template frame), which
drops GNM's neck/bust flange and every interior component (mouth sock, teeth,
eye interiors — masks straight from the npz's 46 vertex groups). Loss is
symmetric ICP: nearest-neighbour correspondences refreshed every outer
iteration, MSE both directions, Adam on the inside. All CPU torch — the fit is
tiny (253-dim linear model) and must never touch a GPU mid-render.

Outputs per body under data/assets/gnm_head/fits/<body>/: fit.json (identity,
similarity, metrics, provenance), fitted GLB (GNM template frame), turntable
renders. The summary table prints adults and abel side by side; THIS module
draws no go/no-go conclusion in code — the numbers do.
"""

from __future__ import annotations

import argparse
import json
import os
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_CREWS = os.path.dirname(_HERE)
SKEL_ROOT = os.path.join(_CREWS, 'data', 'assets', 'mesh_skeletons')
OUT_ROOT = os.path.join(_CREWS, 'data', 'assets', 'gnm_head', 'fits')

HEAD_BONES = ('head', 'jaw', 'eye.L', 'eye.R')
NECK_BONES = ('neck01', 'neck02', 'neck03')
HEAD_W_MIN = 0.35  # moderate: under-jaw needs LOSS support (see face metric note)
NECK_W_MAX = 0.35  # boundary band participates in the loss, never the metric
CHIN_LANDMARK = 8  # 68-lm convention: jawline bottom (chin)
CHIN_MARGIN_M = 0.0  # cut exactly at the chin landmark: the anny crop has no neck either
COEFF_CLIP = 3.0
CLIP_EDGE = 2.5  # |coeff| beyond this counts as "at the wall"


# ── registry access ──────────────────────────────────────────────────────────


def registry_params(body):
    """(params dict, kind) for a registered body, from registry.json itself —
    the same record reissue trusts."""
    with open(os.path.join(SKEL_ROOT, 'registry.json'), encoding='utf-8') as f:
        reg = json.load(f)
    sections = dict(reg) if not isinstance(reg, dict) else reg
    for section in ('originals', 'derived'):
        entry = (sections.get(section) or {}).get(body)
        if entry:
            return entry['params'], section
    raise KeyError(f'{body!r} not in mesh_skeletons registry')


def anny_head_target(body, n_dense=60000, log=print):
    """(crop_points [M,3], dense_surface_points [n_dense,3], stature_m).

    crop_points are the head-crop VERTICES (used for the reverse ICP term and
    reverse metric). dense_surface_points are uniform samples of the head
    SUBMESH surface — the forward term matches against these, because the anny
    head has only ~3k vertices (~7-10 mm apart): point-to-VERTEX distance
    bottoms out at half that spacing, and the first three fit rounds spent
    their entire error budget measuring the target's sampling gaps (RMS
    13-16 mm on a fit whose profiles overlay within ~2 mm)."""
    import numpy as np
    import trimesh
    from zyg_workflows.geom import mesh_skeletons as MS
    from zyg_workflows.geom import relief as RELIEF

    p, section = registry_params(body)
    v, faces, _applied = MS._build_mesh(p['phenotype'], p.get('local_changes'), params=p)
    m = MS._model()
    # relief.bone_weights returns anny's SPARSE top-K rig: (weights [V,K],
    # bone-indices [V,K]) — its docstring's "dense (V, n_bones)" is aspirational.
    w, bidx = RELIEF.bone_weights(m)
    if w is None:
        raise RuntimeError('anny exposes no skinning weights — cannot crop head')
    labels = [str(b) for b in m.bone_labels]
    head_ids = [labels.index(b) for b in HEAD_BONES if b in labels]
    head_w = (np.asarray(w) * np.isin(np.asarray(bidx), head_ids)).sum(axis=1)
    neck_ids = [labels.index(b) for b in NECK_BONES if b in labels]
    neck_w = (np.asarray(w) * np.isin(np.asarray(bidx), neck_ids)).sum(axis=1)
    # Both crops must AGREE about the bottom edge, or ICP spends its budget on a
    # phantom: the first profiled fit put ALL its worst error in the bottom bands
    # (fw 28 mm rms / 79 max, rev 18-19 rms / 74 max) because head-bone skinning
    # bleeds a collar of neck into the target while the GNM region stops at the
    # chin. Strict head weight + explicit neck exclusion ends the disagreement.
    mask = (head_w > HEAD_W_MIN) & (neck_w < NECK_W_MAX)

    # CANONICALIZE THE FRAME, deterministically, before any optimisation. The
    # anny build is NOT in the GLB's Y-up glTF frame (the male rebuild spans
    # only 0.518 m along Y — that is shoulder breadth, not stature). Leaving
    # the frame to the fitted rotation buries a 90-degree problem inside a
    # coarse ICP; the first plumbing run proved it (RMS 16 mm, rotation stuck).
    # Up axis := the axis with the LARGEST full-body span; sign := the head
    # crop's centroid must sit at the TOP of the body along it.
    spans = v.max(0) - v.min(0)
    up = int(np.argmax(spans))
    stature = float(spans[up])
    head_c = v[mask].mean(0)
    body_c = v.mean(0)
    sign = 1.0 if head_c[up] >= body_c[up] else -1.0
    axes = [0, 1, 2]
    axes.remove(up)

    # rotated frame: (axes[0], up, axes[1]) -> (X, Y, Z); right-handedness is
    # irrelevant to a point-cloud target (no faces cross the fit).
    def canon(a):
        a = np.stack([a[:, axes[0]], sign * a[:, up], a[:, axes[1]]], axis=1)
        return a

    # head SUBMESH: quads whose corners are all in the crop -> triangles
    fq = np.asarray(faces)
    keep = mask[fq].all(axis=1)
    sub_q = fq[keep]
    if sub_q.shape[1] == 4:
        tris = np.concatenate([sub_q[:, [0, 1, 2]], sub_q[:, [0, 2, 3]]], axis=0)
    else:
        tris = sub_q
    sub = trimesh.Trimesh(vertices=v.astype('float64'), faces=tris, process=False)
    dense, _fid = trimesh.sample.sample_surface(sub, int(n_dense), seed=0)

    pts = canon(v[mask].astype('float64'))
    centre = pts.mean(0)
    pts = (pts - centre).astype('float32')
    dense = (canon(np.asarray(dense)) - centre).astype('float32')
    log(
        f'[gnm_fit] {body} ({section}): rebuilt {v.shape[0]} verts, head crop '
        f'{mask.sum()} verts + {len(dense)} surface samples, stature '
        f'{stature:.3f} m (up axis {"XYZ"[up]}{"+" if sign > 0 else "-"})'
    )
    return pts, dense, stature


# ── GNM fit region ───────────────────────────────────────────────────────────

FACE_GROUPS = (
    'forehead_region',
    'left_brow_region',
    'middle_brow_region',
    'right_brow_region',
    'left_temple_region',
    'right_temple_region',
    'left_orbital_region',
    'right_orbital_region',
    'left_zygomatic_region',
    'right_zygomatic_region',
    'nose_region',
    'left_parotid_region',
    'right_parotid_region',
    'left_infraorbital_region',
    'right_infraorbital_region',
    'left_cheek_region',
    'right_cheek_region',
    'upper_lip_region',
    'lower_lip_region',
    'chin_region',
    'ears',
)


def gnm_fit_mask(log=print):
    """(fit_mask, face_mask) booleans [17821].

    fit_mask — skin_exterior at/above chin height: what the LOSS optimises.
    face_mask — the union of GNM's own semantic face regions + ears: what the
    METRIC is scored on. The split exists because every profiled error tail so
    far lived in the crop-boundary band (under-jaw/throat vs anny's neck cut) —
    a property of where the two crops END, not of whether the identity space
    can reproduce the face. Scoring on named facial anatomy makes the go/no-go
    number measure identity capacity and nothing else, and it is stated in
    fit.json rather than silently baked in."""
    import numpy as np
    from zyg_workflows.geom import gnm_head as GH

    GH.load_head()  # populates the module cache GH.vertices_for() reads below
    z = np.load(
        os.path.join(GH.GNM_REPO, 'gnm', 'shape', 'data', 'versions', 'v3_0', 'gnm_head.npz'), allow_pickle=True
    )
    names = [str(n) for n in z['vertex_group_names']]
    groups = np.asarray(z['vertex_groups'])
    skin_ext = groups[names.index('skin_exterior')] > 0.5
    neutral = GH.vertices_for(GH.neutral_params())
    chin_y = float(GH.landmark_points(neutral)[CHIN_LANDMARK][1])
    fit_mask = skin_ext & (neutral[:, 1] >= chin_y - CHIN_MARGIN_M)
    face = np.zeros(len(fit_mask), dtype=bool)
    for gname in FACE_GROUPS:
        face |= groups[names.index(gname)] > 0.5
    face &= fit_mask
    log(f'[gnm_fit] GNM fit region: {int(fit_mask.sum())} verts; face metric region: {int(face.sum())} verts')
    return fit_mask, face


# ── the fit ──────────────────────────────────────────────────────────────────


def _rotmat(rv):
    import roma

    return roma.rotvec_to_rotmat(rv)


def _chunked_nn(a, b, chunk=1024):
    """(min_dist [A], argmin [A]) of pairwise distances a->b without holding
    the full [A,B] matrix (60k dense targets would need GBs)."""
    import torch

    ds, idx = [], []
    for i in range(0, a.shape[0], chunk):
        d = torch.cdist(a[i : i + chunk], b)
        m = d.min(dim=1)
        ds.append(m.values)
        idx.append(m.indices)
    return torch.cat(ds), torch.cat(idx)


def fit_body(body, outer=24, inner=30, prior=1e-3, id_lr=0.05, log=print):
    import numpy as np
    import torch
    from zyg_workflows.geom import gnm_head as GH

    crop_np, dense_np, stature = anny_head_target(body, log=log)
    target = torch.from_numpy(crop_np)  # reverse term + reverse metric
    dense = torch.from_numpy(dense_np)  # forward term + forward metric
    mask_np, face_np = gnm_fit_mask(log=log)
    mask = torch.from_numpy(mask_np)
    face_in_fit = torch.from_numpy(face_np[mask_np])  # face indices inside the fit region
    g = GH.load_head()

    # THE DIFFERENTIABLE FORWARD IS OURS, NOT gnm_pytorch's. Measured 2026-08-21:
    # the shipped torch backend returns vertices with requires_grad=False and no
    # grad_fn even for a requires-grad identity input — backward() raises, and
    # inside an optimiser loop the failure is SILENT: loss still has a graph via
    # the similarity parameters, so Adam fits scale/rotation while identity gets
    # grad=None and never moves. (Exactly the frozen |id|max=0.00 the first two
    # plumbing runs showed.) At ZERO pose the model is purely linear —
    #   v = template + identity @ identity_basis   (expression held at zero) —
    # so the fit uses that form directly, VERIFIED against the numpy backend
    # below on every run, with an explicit raise (never a strippable assert).
    import numpy as np2

    z = np2.load(os.path.join(GH.GNM_REPO, 'gnm', 'shape', 'data', 'versions', 'v3_0', 'gnm_head.npz'))
    template = torch.from_numpy(z['template_vertex_positions'].astype('float32'))
    basis = torch.from_numpy(z['vertex_identity_basis'].astype('float32').reshape(g.identity_dim, -1))

    def gnm_verts(ident):
        return (template.reshape(-1) + ident @ basis).reshape(-1, 3)

    for probe_seed in (1, 2):
        pi = GH.sample_identity(probe_seed)
        ref = GH.vertices_for({**GH.neutral_params(), 'identity': pi})
        mine = gnm_verts(torch.from_numpy(pi)).numpy()
        err = float(np.abs(ref - mine).max())
        if err > 1e-4:
            raise RuntimeError(
                f'linear forward diverges from numpy backend by {err:.2e} m — '
                f'zero-pose linearity assumption is WRONG, do not fit'
            )

    # similarity init: centroid + bbox-height ratio; try yaw 0 and pi, keep better
    with torch.no_grad():
        v0 = gnm_verts(torch.zeros(g.identity_dim))[mask]
        s0 = float((target[:, 1].max() - target[:, 1].min()) / (v0[:, 1].max() - v0[:, 1].min()))

    def make_params(yaw):
        log_s = torch.tensor(float(np.log(s0)), requires_grad=True)
        rv = torch.tensor([0.0, float(yaw), 0.0], requires_grad=True)
        with torch.no_grad():
            R = _rotmat(rv.detach())
            t0 = target.mean(0) - torch.exp(log_s.detach()) * (v0 @ R.T).mean(0)
        t = t0.clone().requires_grad_(True)
        return log_s, rv, t

    def transformed(ident, log_s, rv, t):
        return torch.exp(log_s) * (gnm_verts(ident)[mask] @ _rotmat(rv).T) + t

    def icp_round(ident, log_s, rv, t, opt, n_inner):
        # Robust symmetric ICP round: correspondences AND a 90%-trim mask are
        # frozen per round. Trimming keeps crop-boundary mismatch (anny's crop
        # ends at the skull base; GNM's at the chin margin) from dragging the
        # whole head — the classic ICP failure the first run showed as max 57 mm.
        with torch.no_grad():
            src = transformed(ident, log_s, rv, t)
            fw_d, nn_fw = _chunked_nn(src, dense)  # GNM vert -> SURFACE sample
            rev_d, nn_rev = _chunked_nn(target, src)  # anny vert -> GNM vert
            keep_fw = fw_d <= fw_d.quantile(0.90)
            keep_rev = rev_d <= rev_d.quantile(0.90)
        for _ in range(n_inner):
            opt.zero_grad()
            src = transformed(ident, log_s, rv, t)
            loss = (
                ((src[keep_fw] - dense[nn_fw][keep_fw]) ** 2).sum(-1).mean()
                + ((src[nn_rev][keep_rev] - target[keep_rev]) ** 2).sum(-1).mean()
                + prior * (ident**2).mean()
                + 10.0 * torch.relu(ident.abs() - COEFF_CLIP).pow(2).sum()
            )
            loss.backward()
            opt.step()
        return float(loss)

    best = None
    for yaw in (0.0, np.pi):
        ident = torch.zeros(g.identity_dim, requires_grad=True)
        log_s, rv, t = make_params(yaw)
        opt = torch.optim.Adam([{'params': [ident], 'lr': id_lr}, {'params': [log_s, rv, t], 'lr': 0.03}])
        for _ in range(3):
            last = icp_round(ident, log_s, rv, t, opt, inner)
        if best is None or last < best[0]:
            best = (last, ident, log_s, rv, t, opt, yaw)
    _loss, ident, log_s, rv, t, opt, yaw = best
    log(f'[gnm_fit] {body}: yaw init {"180" if yaw > 1 else "0"} deg won')

    t0 = time.time()
    for _k in range(outer - 3):
        icp_round(ident, log_s, rv, t, opt, inner)

    # metrics — bidirectional surface distance on the fit region, in mm
    with torch.no_grad():
        src = transformed(ident, log_s, rv, t)
        # CONTROL ARM, computed every run and never optional. A fit that scores
        # 5.9 mm means nothing until you know what the MEAN head scores through
        # the same similarity: measured 2026-08-21, the Phase-1 fits beat the
        # mean head by 0.08-0.10 mm, i.e. the identity solve contributed ~1.6%
        # of the reported number and the "GO" verdict was really "any scaled
        # head lands 5-6 mm from any other". Identity capacity is only claimed
        # by identity_gain_mm, never by face_fw_rms_mm alone.
        src_mean = transformed(torch.zeros_like(ident), log_s, rv, t)
        mean_fw = _chunked_nn(src_mean, dense)[0] * 1000.0
        mean_face_rms = float(mean_fw[face_in_fit].pow(2).mean().sqrt())
        fw_all = _chunked_nn(src, dense)[0] * 1000.0
        fw = fw_all[face_in_fit]  # face anatomy only
        rev_all = _chunked_nn(target, src)[0] * 1000.0
        rev = rev_all[rev_all <= rev_all.quantile(0.90)]  # boundary ring trimmed
        both = torch.cat([fw, rev])
        idn = ident.detach().numpy()
    metrics = {
        'rms_mm': float(both.pow(2).mean().sqrt()),
        'p95_mm': float(both.quantile(0.95)),
        'max_mm': float(both.max()),
        'face_fw_rms_mm': float(fw.pow(2).mean().sqrt()),
        'face_fw_p95_mm': float(fw.quantile(0.95)),
        'face_fw_max_mm': float(fw.max()),
        'rev_rms_trim90_mm': float(rev.pow(2).mean().sqrt()),
        'fw_rms_allregion_mm': float(fw_all.pow(2).mean().sqrt()),
        'mean_head_face_rms_mm': mean_face_rms,
        'identity_gain_mm': mean_face_rms - float(fw.pow(2).mean().sqrt()),
        'prior': prior,
        'id_lr': id_lr,
        'identity_l2': float(np.linalg.norm(idn)),
        'clip_hits': int((np.abs(idn) > CLIP_EDGE).sum()),
        'coeff_absmax': float(np.abs(idn).max()),
        'scale': float(torch.exp(log_s.detach()).item()),
        'n_target': int(target.shape[0]),
        'n_source': int(mask.sum()),
        'outer': outer,
        'inner': inner,
        'elapsed_s': round(time.time() - t0, 1),
    }
    log(
        f'[gnm_fit] {body}: FACE rms {metrics["face_fw_rms_mm"]:.2f} / '
        f'p95 {metrics["face_fw_p95_mm"]:.2f} / max {metrics["face_fw_max_mm"]:.2f} mm, '
        f'rev(trim90) {metrics["rev_rms_trim90_mm"]:.2f} mm, '
        f'|id| max {metrics["coeff_absmax"]:.2f}, '
        f'clip_hits {metrics["clip_hits"]}, scale {metrics["scale"]:.3f}'
    )
    log(
        f'[gnm_fit] {body}: CONTROL mean-head face rms '
        f'{metrics["mean_head_face_rms_mm"]:.2f} mm -> identity gain '
        f'{metrics["identity_gain_mm"]:+.2f} mm (|id| L2 {metrics["identity_l2"]:.2f})'
    )

    out_dir = os.path.join(OUT_ROOT, body)
    os.makedirs(out_dir, exist_ok=True)
    fitted = GH.vertices_for({**GH.neutral_params(), 'identity': idn.astype('float32')})
    glb = os.path.join(out_dir, f'gnm_fit_{body}.glb')
    GH.export_glb(glb, fitted)
    doc = {
        'body': body,
        'metrics': metrics,
        'identity': [round(float(x), 5) for x in idn],
        'similarity': {
            'log_scale': float(log_s.detach()),
            'rotvec': [float(x) for x in rv.detach()],
            'translation': [float(x) for x in t.detach()],
        },
        'target': 'rebuilt from registry params via mesh_skeletons._build_mesh, '
        f'head crop = skinning({",".join(HEAD_BONES)}) > {HEAD_W_MIN}',
        'source_mask': 'skin_exterior >= chin landmark y - %.2f m' % CHIN_MARGIN_M,
        'glb': glb,
        'date': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    with open(os.path.join(out_dir, 'fit.json'), 'w', encoding='utf-8') as f:
        json.dump(doc, f, indent=1)
    return doc


def run(
    bodies=('male', 'female', 'abel', 'cornelis'), outer=24, inner=30, prior=1e-3, id_lr=0.05, render=True, log=print
):
    os.makedirs(OUT_ROOT, exist_ok=True)
    docs = []
    for b in bodies:
        try:
            docs.append(fit_body(b, outer=outer, inner=inner, prior=prior, id_lr=id_lr, log=log))
        except Exception as exc:
            log(f'[gnm_fit] {b} FAILED: {type(exc).__name__}: {exc}')
            docs.append({'body': b, 'error': f'{type(exc).__name__}: {exc}'})
    if render:
        from zyg_workflows.geom import gnm_head as GH

        glbs = [d['glb'] for d in docs if d.get('glb')]
        if glbs:
            GH.render_turntables(glbs, OUT_ROOT, views=4, log=log)
    ok = [d for d in docs if 'metrics' in d]
    if ok:
        log('')
        log(
            f'{"body":10s} {"faceRMS":>8s} {"meanhead":>9s} {"gain":>7s} '
            f'{"facep95":>8s} {"|id|L2":>7s} {"|id|max":>8s} {"clip":>5s} {"scale":>6s}'
        )
        for d in ok:
            m = d['metrics']
            log(
                f'{d["body"]:10s} {m["face_fw_rms_mm"]:8.2f} '
                f'{m.get("mean_head_face_rms_mm", float("nan")):9.2f} '
                f'{m.get("identity_gain_mm", float("nan")):+7.2f} '
                f'{m["face_fw_p95_mm"]:8.2f} {m["identity_l2"]:7.2f} '
                f'{m["coeff_absmax"]:8.2f} {m["clip_hits"]:5d} {m["scale"]:6.3f}'
            )
    with open(os.path.join(OUT_ROOT, 'summary.json'), 'w', encoding='utf-8') as f:
        json.dump(docs, f, indent=1)
    return docs


def _cli():
    ap = argparse.ArgumentParser(description='Fit GNM identity to registered anny heads')
    sub = ap.add_subparsers(dest='cmd')
    r = sub.add_parser('run')
    r.add_argument('--bodies', default='male,female,abel,cornelis')
    r.add_argument('--outer', type=int, default=24)
    r.add_argument('--inner', type=int, default=30)
    r.add_argument('--prior', type=float, default=1e-3)
    r.add_argument('--id-lr', type=float, default=0.05)
    r.add_argument('--no-render', action='store_true')
    args = ap.parse_args()
    if args.cmd == 'run':
        run(
            tuple(b.strip() for b in args.bodies.split(',') if b.strip()),
            outer=args.outer,
            inner=args.inner,
            prior=args.prior,
            id_lr=args.id_lr,
            render=not args.no_render,
        )
        return 0
    ap.print_help()
    return 0


if __name__ == '__main__':
    raise SystemExit(_cli())
