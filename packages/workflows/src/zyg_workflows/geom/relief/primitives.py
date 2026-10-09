# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""primitives — a verbatim section of the pre-split relief.py.

The module docstring that documented the whole layer lives in the package
__init__.py; nothing in this file was rewritten, renamed or retuned.
"""

import numpy as np  # noqa: F401

from zyg_workflows.geom.relief.constants import (  # noqa: F401
    FALLOFF_FRAC,
)


# ---------------------------------------------------------------------------------
# mesh primitives that must be mirror-stable
# ---------------------------------------------------------------------------------


def newell_vertex_normals(v, faces):
    """Area-weighted vertex normals from CYCLIC-INVARIANT Newell face normals.

    mesh_skeletons._vertex_normals builds each quad's normal from corners (0,1,2) only.
    On this cage 10265 of 13710 mirrored quads are stored starting at a different corner
    and quads are non-planar (median warp 0.33 mm, max 11.1 mm), so that estimator gives a
    quad and its mirror image different directions AND different areas: max
    |n - mirror(n_partner)| = 1.168. The Newell normal sums over all four edges and is
    therefore invariant to which corner the quad starts at; measured residual 2.4e-3.

    _vertex_normals is deliberately left alone — it is shared, hash-pinned geometry with
    its own callers. This module simply does not use it.
    """
    v = np.asarray(v, np.float64)
    faces = np.asarray(faces)
    n = np.zeros((len(v), 3), np.float64)
    k = faces.shape[1]
    fn = np.zeros((len(faces), 3), np.float64)
    for a in range(k):
        b = (a + 1) % k
        pa, pb = v[faces[:, a]], v[faces[:, b]]
        fn[:, 0] += (pa[:, 1] - pb[:, 1]) * (pa[:, 2] + pb[:, 2])
        fn[:, 1] += (pa[:, 2] - pb[:, 2]) * (pa[:, 0] + pb[:, 0])
        fn[:, 2] += (pa[:, 0] - pb[:, 0]) * (pa[:, 1] + pb[:, 1])
    for a in range(k):
        np.add.at(n, faces[:, a], fn)
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)


def mirror_map(v, tol_m):
    """Mutual nearest-neighbour pairing of each vertex with its x-negated image.

    Returns (mate, dist): mate[i] is the partner index or -1. Only MUTUAL pairs survive
    (i -> j -> i); a one-way match would symmetrise i against j while j symmetrises
    against somebody else, which is not a symmetry. Midline vertices pair with themselves,
    which is what drives their x-displacement to exactly zero.

    Deterministic: stable z-sort, np.argmin (lowest index on ties), fixed loop order. The
    z-slab prune is exact where it matters — a winner found within `win` IS the global
    nearest, and a winner beyond `win` is beyond `tol_m` too, so it is refused either way.
    """
    P = np.asarray(v, np.float64)
    win = 20.0 * tol_m
    order = np.argsort(P[:, 2], kind='stable')
    zs = P[order, 2]

    def nearest(idx):
        q = P[idx].copy()
        q[:, 0] *= -1.0
        lo = np.searchsorted(zs, q[:, 2] - win, 'left')
        hi = np.searchsorted(zs, q[:, 2] + win, 'right')
        mate = np.full(len(idx), -1, np.int64)
        dist = np.full(len(idx), np.inf)
        for k in range(len(idx)):
            a, b = int(lo[k]), int(hi[k])
            if b <= a:
                continue
            d2 = ((P[order[a:b]] - q[k]) ** 2).sum(axis=1)
            j = int(np.argmin(d2))
            mate[k] = order[a + j]
            dist[k] = float(np.sqrt(d2[j]))
        return mate, dist

    allv = np.arange(len(P), dtype=np.int64)
    m1, d1 = nearest(allv)
    ok = d1 <= tol_m
    back = np.full(len(P), -1, np.int64)
    if ok.any():
        b2, _ = nearest(m1[ok])
        good = np.nonzero(ok)[0]
        ok[good[b2 != good]] = False
    back[ok] = m1[ok]
    return back, d1


def symmetrise_field(D, mate):
    """Each vertex's displacement becomes the mean of its own and its partner's x-negated
    one. Exact against BOTH candidate asymmetry mechanisms at once (a selection that is
    not mirror-closed, and a direction field that is not mirror-symmetric)."""
    Ds = D.copy()
    have = np.nonzero(mate >= 0)[0]
    if len(have):
        M = D[mate[have]].copy()
        M[:, 0] *= -1.0
        Ds[have] = 0.5 * (D[have] + M)
    return Ds, have


def field_mirror_residual_m(D, mate):
    """Max |D - mirror(D_partner)| over paired vertices, in metres. 0 for a field that is
    exactly mirror-symmetric."""
    have = np.nonzero(mate >= 0)[0]
    if not len(have):
        return None
    R = D[mate[have]].copy()
    R[:, 0] *= -1.0
    return float(np.abs(D[have] - R).max())


def _check_falloff_inside_collar():
    """The one structural guarantee this module makes about its own measurability: the
    displacement is exactly zero everywhere the probe's collar can reach, so the layer
    cannot inflate its own contrast by lifting its own reference surface."""
    from zyg_workflows.geom.form import ridge as RD

    if not FALLOFF_FRAC < RD.RIDGE_GAP_FRAC:
        raise RuntimeError(
            'relief.FALLOFF_FRAC (%.5f) is not strictly inside ridge.RIDGE_GAP_FRAC '
            '(%.5f). The collar every relief measurement is taken against would then sit '
            'on skin THIS LAYER displaced, and every contrast it reports would be partly '
            'self-inflicted. Shrink FALLOFF_FRAC; do not widen the gap.' % (FALLOFF_FRAC, RD.RIDGE_GAP_FRAC)
        )
    return {
        'falloff_frac': FALLOFF_FRAC,
        'ridge_gap_frac': RD.RIDGE_GAP_FRAC,
        'collar_outer_frac': RD.RIDGE_GAP_FRAC + RD.RIDGE_WIDTH_FRAC,
    }


# ---------------------------------------------------------------------------------
# the rig, in the frame the cage is actually in
# ---------------------------------------------------------------------------------


def bone_frame(model, out):
    """Posed bone head/tail positions, in the SAME frame as out['vertices'].

    THE FRAME IS THE WHOLE PROBLEM. anny returns rest_bone_heads/tails together with a
    rest pose and a delivered pose, and the delivered CAGE (out['vertices']) is not the
    rest cage — they differ by up to 216 mm. Using the rest positions puts clavicle.L at
    0.910 of stature, which is in the neck; the posed positions put it at 0.802, which is
    the clavicle. The transform is pose @ rest^-1, applied to the rest endpoints.

    Verified on originals/male: every posed endpoint lands 19-87 mm inside the surface
    (a joint centre is supposed to be inside), and every bone's own posed segment lies
    inside the height span of its own SKINNING territory. verify_bone_frame() re-checks
    both on every call, because a silently wrong frame is a silently wrong skeleton.
    """
    import numpy as _np

    H = _np.asarray(out['rest_bone_heads'][0].detach().cpu().numpy(), _np.float64)
    T = _np.asarray(out['rest_bone_tails'][0].detach().cpu().numpy(), _np.float64)
    P = _np.asarray(out['bone_poses'][0].detach().cpu().numpy(), _np.float64)
    R = _np.asarray(out['rest_bone_poses'][0].detach().cpu().numpy(), _np.float64)
    M = P @ _np.linalg.inv(R)
    Hp = (M[:, :3, :3] @ H[:, :, None])[:, :, 0] + M[:, :3, 3]
    Tp = (M[:, :3, :3] @ T[:, :, None])[:, :, 0] + M[:, :3, 3]
    from zyg_workflows.geom import mesh_skeletons as MS

    names = [str(n) for n in MS._bone_names(model)]
    return {nm: (Hp[i].copy(), Tp[i].copy()) for i, nm in enumerate(names)}


def bone_weights(model):
    """Per-vertex, per-bone skinning weight as a dense (V, n_bones) array, or None.

    The rig is a property of the model, not of a character's parameters. Weights do not
    enter mesh_skeletons._vert_sha (it hashes rest-cage vertices only), so reading them
    costs nothing a determinism check can see.
    """
    try:
        w = np.asarray(model.vertex_bone_weights.detach().cpu().numpy(), np.float64)
        i = np.asarray(model.vertex_bone_indices.detach().cpu().numpy(), np.int64)
    except Exception:  # noqa: BLE001
        return None, None
    return w, i


def bones_for(phenotype, local_changes=None, bone_scales=None):
    """One forward pass -> (vertices, faces, bones, weights). For callers that do not
    already hold an anny output. mesh_skeletons._build_mesh throws the bone block away, so
    a caller wiring this layer in either passes its own model output to bone_frame() or
    pays for one extra evaluation here; the recipe is deterministic, so the two agree."""
    import torch
    from zyg_workflows.geom import mesh_skeletons as MS

    m = MS._model()
    kw = {'phenotype_kwargs': dict(phenotype)}
    if local_changes:
        kw['local_changes_kwargs'] = dict(local_changes)
    if bone_scales:
        pose, _ = MS._scale44(m, bone_scales)
        kw['pose_parameters'] = pose
    with torch.no_grad():
        out = m(**kw)
    v = out['vertices'][0].to(torch.float32).numpy()
    faces = m.faces.numpy() if hasattr(m.faces, 'numpy') else np.asarray(m.faces)
    return v, faces, bone_frame(m, out), bone_weights(m)


def verify_bone_frame(v, bones, weights, model_bone_names, stature_m, used):
    """Is this bone dict really in the cage's frame? Two independent checks per bone.

    (1) DEPTH. The posed endpoint must lie within 0.10 of stature of the surface. A joint
        centre is inside the body; one that is 300 mm from the nearest vertex is in a
        different coordinate system.
    (2) OWN TERRITORY. The bone's posed segment must lie inside the height span of the
        vertices its OWN skinning weights claim. This is the check that catches the
        rest-frame error: rest clavicle.L sits at 0.910 of stature while the vertices it
        skins span 0.766-0.839, so the frame is refused instead of silently sculpting a
        clavicle into the neck.

    Returns a per-bone record. A failure is reported, never swallowed.
    """
    v = np.asarray(v, np.float64)
    S = float(stature_m)
    z0 = float(v[:, 2].min())
    W, I = weights if weights is not None else (None, None)
    recs = {}
    for nm in used:
        if nm not in bones:
            recs[nm] = {'ok': False, 'why': 'bone %r is not on this rig' % nm}
            continue
        h, t = bones[nm]
        dh = float(np.linalg.norm(v - h, axis=1).min())
        dt = float(np.linalg.norm(v - t, axis=1).min())
        rec = {
            'ok': True,
            'depth_head_m': dh,
            'depth_tail_m': dt,
            'head_frac_stature': (h[2] - z0) / S,
            'tail_frac_stature': (t[2] - z0) / S,
        }
        if max(dh, dt) > 0.10 * S:
            rec['ok'] = False
            rec['why'] = (
                'endpoint is %.1f mm from the nearest cage vertex (limit %.1f '
                'mm) — this is not the cage frame' % (1e3 * max(dh, dt), 1e3 * 0.10 * S)
            )
        if W is not None and nm in model_bone_names:
            bi = model_bone_names.index(nm)
            terr = (W * (I == bi)).sum(axis=1) > 0.15
            rec['territory_verts'] = int(terr.sum())
            if terr.any():
                lo = float((v[terr, 2].min() - z0) / S)
                hi = float((v[terr, 2].max() - z0) / S)
                rec['territory_frac_stature'] = [lo, hi]
                mid = 0.5 * (rec['head_frac_stature'] + rec['tail_frac_stature'])
                if not (lo - 0.02 <= mid <= hi + 0.02):
                    rec['ok'] = False
                    rec['why'] = (
                        "the bone's own skinning territory spans %.3f-%.3f of "
                        'stature but its posed midpoint is at %.3f — the bone '
                        'positions are not in the same frame as the cage' % (lo, hi, mid)
                    )
        recs[nm] = rec
    return recs
