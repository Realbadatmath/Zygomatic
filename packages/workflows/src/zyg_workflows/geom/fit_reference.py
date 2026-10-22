# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""fit_reference.py — fit anny's parametric body to an external reference mesh.

    python geom/fit_reference.py --sex female \
        --ref data/assets/mesh_packs/blender_human_base/glb/coll_body_female_realistic.glb \
        [--iters 400] [--out /path/fit_female.json]

Why this exists: matching proportions through scalar silhouette measurements failed
twice — at shoulder level the arms are connected to the torso so slice widths conflate
arm pose with shoulder breadth, and any scalar the objective does not measure becomes
a dumping ground for solver error (the 2026-08-05 swayback).  This fitter instead
minimises true 3D surface distance (trimmed, index-refreshed chamfer) between anny's
cage and a point cloud sampled on the reference body, with gradients flowing through
anny's own differentiable morph stack.

Pose handling: anny's rest pose holds the arms ~10%H higher than the Blender Studio
bodies, so arm/hand/foot vertices are masked out of the loss via skinning weights
(clavicle + shoulder01 stay — they carry shoulder breadth), and reference points with
no kept anny vertex within TRIM_R stay out of the reverse term, which keeps the
reference's lowered arms from dragging our torso sideways.  Legs are close enough to
fit directly (foot-spread delta measured 2-3%H).

Output is a JSON recipe {phenotype, local_changes, fit: {…}} to be baked into
ORIGINAL_PHEN/ORIGINAL_LOCALS in mesh_skeletons.py ONLY after a front+side eye pass.
It never bakes anything itself.
"""

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows.geom import mesh_skeletons as MS  # noqa: E402

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# gender and height are identity, not proportion: gender defines the original, and
# height here is only the FIT-TIME OPERATING POINT (the second-issue axes the recorded
# fits ran at — kept so those runs reproduce exactly). It is NOT the issued axis:
# build_originals re-binary-searches height after the fitted morphs are baked (they
# shorten the body), which landed the third issue at male 0.702148 / female 0.476562.
# The fit itself is height-normalized, so the operating point only nudges morph-vs-
# height interplay second-order.
FIXED_PHEN = {
    'male': {'gender': 0.0, 'height': 0.855469},
    'female': {'gender': 1.0, 'height': 0.680664},
}
# fitted axes, with bounds: age stays adult, muscle/weight stay in the range where
# MakeHuman targets deform cleanly (the ±0.8 lesson applies to macros too).
# Male muscle/weight are pinned apart because chamfer distance cannot tell fat from
# muscle when both put the surface in the same place — an unconstrained male fit
# reached the reference torso with weight 0.75 / muscle 0.35 and read soft; the
# reference (and the operator's spec) is a muscular body, so the prior decides.
PHEN_BOUNDS = {
    'male': {'age': (0.40, 0.65), 'muscle': (0.65, 0.95), 'weight': (0.30, 0.55), 'proportions': (0.0, 1.0)},
    'female': {'age': (0.40, 0.65), 'muscle': (0.20, 0.95), 'weight': (0.25, 0.80), 'proportions': (0.0, 1.0)},
}

# body-global morphs only — face, fingers and single-side detail excluded; l/r pairs
# are tied to one shared parameter so the fit cannot break symmetry.
FIT_MORPHS = [
    'measure-shoulder-dist-incr',
    'torso-vshape-incr',
    'torso-scale-depth-incr',
    'torso-scale-horiz-incr',
    'torso-scale-vert-incr',
    'torso-muscle-pectoral-incr',
    'torso-muscle-dorsi-incr',
    'measure-frontchest-dist-incr',
    'measure-napetowaist-dist-incr',
    'measure-waist-circ-incr',
    'stomach-tone-incr',
    'measure-waisttohip-dist-incr',
    'measure-hips-circ-incr',
    'hip-scale-depth-incr',
    'hip-scale-horiz-incr',
    'buttocks-volume-incr',
    'pelvis-tone-incr',
    'measure-neck-circ-incr',
    'measure-neck-height-incr',
    'neck-scale-depth-incr',
    'head-scale-horiz-incr',
    'head-scale-depth-incr',
    'head-scale-vert-incr',
    'measure-upperleg-height-incr',
    'measure-lowerleg-height-incr',
    'measure-thigh-circ-incr',
    'measure-calf-circ-incr',
    'measure-knee-circ-incr',
    ('l-upperleg-scale-horiz-incr', 'r-upperleg-scale-horiz-incr'),
    ('l-upperleg-scale-depth-incr', 'r-upperleg-scale-depth-incr'),
]
FEMALE_MORPHS = [
    'measure-bust-circ-incr',
    'measure-underbust-circ-incr',
    'breast-dist-incr',
    'breast-point-incr',
    'breast-trans-up',
    'breast-volume-vert-up',
]
LOCAL_BOUND = 0.8  # hard design-range cap — the swayback came from -1.6
TRIM_R = 0.04  # unit-height trim radius for the reverse chamfer term
MASK_BONES = ('upperarm', 'lowerarm', 'wrist', 'hand', 'finger', 'thumb', 'metacarpal', 'foot', 'toe')


def _load_ref_cloud(path, n=30000, seed=7):
    """Largest scene geometry (packs bundle props beside the body), z-up, feet at
    z=0, x/y centred by median, then surface-sampled."""
    import trimesh

    sc = trimesh.load(path, force='scene')
    geos = [g for g in sc.dump() if isinstance(g, trimesh.Trimesh)]
    body = max(geos, key=lambda g: len(g.faces))
    v = np.asarray(body.vertices, np.float64)
    v = np.stack([v[:, 0], -v[:, 2], v[:, 1]], -1)
    v[:, 0] -= np.median(v[:, 0])
    v[:, 1] -= np.median(v[:, 1])
    v[:, 2] -= v[:, 2].min()
    mesh = trimesh.Trimesh(vertices=v, faces=np.asarray(body.faces), process=False)
    pts, _ = trimesh.sample.sample_surface(mesh, n, seed=seed)
    return np.asarray(pts, np.float64)


def _kept_mask(model):
    """True for vertices NOT dominated by masked (arm/hand/foot) bones."""
    import torch

    names = [str(n).lower() for n in MS._bone_names(model)]
    bad = torch.tensor([any(k in nm for k in MASK_BONES) for nm in names])
    w = model.vertex_bone_weights  # (V, 9)
    i = model.vertex_bone_indices  # (V, 9)
    badw = (w * bad[i]).sum(1)
    return (badw < 0.5).numpy()


def fit(sex, ref_path, iters=400, lr=0.03, log_every=50):
    import torch
    from scipy.spatial import cKDTree

    torch.manual_seed(0)
    m = MS._model()
    kept = _kept_mask(m)
    ref = _load_ref_cloud(ref_path)
    ref /= ref[:, 2].max()  # unit height
    ref_t = torch.tensor(ref)
    ref_tree = cKDTree(ref)

    morphs = list(FIT_MORPHS) + (FEMALE_MORPHS if sex == 'female' else [])
    pb = PHEN_BOUNDS[sex]
    raw_p = {k: torch.zeros((), dtype=torch.float64, requires_grad=True) for k in pb}
    raw_l = [torch.zeros((), dtype=torch.float64, requires_grad=True) for _ in morphs]
    dy = torch.zeros((), dtype=torch.float64, requires_grad=True)
    opt = torch.optim.Adam(list(raw_p.values()) + raw_l + [dy], lr=lr)

    def bounded(raw, lo, hi):
        return lo + (hi - lo) * (torch.tanh(raw) + 1.0) / 2.0

    def build():
        phen = dict(FIXED_PHEN[sex])
        for k, (lo, hi) in pb.items():
            phen[k] = bounded(raw_p[k], lo, hi)
        loc = {}
        for spec, raw in zip(morphs, raw_l):
            val = LOCAL_BOUND * torch.tanh(raw)
            for lab in spec if isinstance(spec, tuple) else (spec,):
                loc[lab] = val
        out = m(phenotype_kwargs=phen, local_changes_kwargs=loc)
        return out['vertices'][0]

    kept_t = torch.tensor(kept)
    hist = []
    for it in range(iters):
        opt.zero_grad()
        v = build()
        H = v[:, 2].max() - v[:, 2].min()
        cen = torch.stack([v[:, 0].median(), v[:, 1].median() + dy, v[:, 2].min()])
        vn = (v - cen) / H
        vk = vn[kept_t]
        vk_np = vk.detach().numpy()

        # forward: every kept anny vertex to its nearest reference point
        _, ia = ref_tree.query(vk_np, workers=-1)
        d_a2r = torch.linalg.norm(vk - ref_t[ia], dim=1)
        # reverse: reference points to nearest kept anny vertex, trimmed so the
        # reference's (differently posed) arms and feet never pull the torso
        dr, ir = cKDTree(vk_np).query(ref, workers=-1)
        sel = dr < TRIM_R
        d_r2a = torch.linalg.norm(ref_t[sel] - vk[ir[sel]], dim=1)

        reg = sum(t**2 for t in raw_l) / max(len(raw_l), 1)
        loss = d_a2r.mean() + d_r2a.mean() + 1e-3 * reg
        loss.backward()
        opt.step()
        if it % log_every == 0 or it == iters - 1:
            # distances are in unit-height space — report at the DELIVERED physical
            # height, not anny's fit-time native span (~2.05 m, ~11% larger)
            phys = float(MS.TARGET_HEIGHT_M[sex]) * 1000.0
            mm = float(d_a2r.mean()) * phys
            hist.append(mm)
            _zyg_log.info(
                '  it %3d  a2r %.2f mm  r2a %.2f mm  (kept ref %d/%d)'
                % (it, mm, float(d_r2a.mean()) * phys, int(sel.sum()), len(ref))
            )

    with torch.no_grad():
        phen = {k: round(float(bounded(raw_p[k], *pb[k])), 4) for k in pb}
        loc = {}
        for spec, raw in zip(morphs, raw_l):
            val = round(float(LOCAL_BOUND * math.tanh(float(raw))), 4)
            if abs(val) < 0.02:  # drop numerically idle morphs
                continue
            for lab in spec if isinstance(spec, tuple) else (spec,):
                loc[lab] = val
    return {
        'sex': sex,
        'phenotype': {**FIXED_PHEN[sex], **phen},
        'local_changes': loc,
        'fit': {
            'reference': os.path.relpath(ref_path, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            'iters': iters,
            'mean_mm_history_at_delivered_height': [round(h, 2) for h in hist],
            'masked': 'arms from upperarm01 + hands + feet (skinning-weight mask)',
            'method': 'trimmed index-refreshed chamfer, bounds ±%.1f' % LOCAL_BOUND,
        },
    }


if __name__ == '__main__':  # the CLI lives in fit_reference_cli
    from zyg_workflows.geom.fit_reference_cli import main as _cli_main

    raise SystemExit(_cli_main())
