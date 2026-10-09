# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The cage deformation layers: toe and lip declash, _apply_anatomy(),
bony relief and Catmull-Clark subdivision.

Moved verbatim out of the old single-file mesh_skeletons.py (lines 1172-1655).
"""

import os

import numpy as np

from zyg_workflows.geom.mesh_skeletons.spec import DISPLAY_SUBDIV

from zyg_workflows.geom.mesh_skeletons.rig import _bone_names, _model, _rig_for

from zyg_workflows.geom.mesh_skeletons.abs_definition import _apply_abs_definition


# ---------------------------------------------------------------------------------------
# toe declash — the female original's little toe crosses INTO its fourth toe
# ---------------------------------------------------------------------------------------
TOE_DECLASH_KEY = 'toe_declash'
_TOE_GROUPS = {}


# ---------------------------------------------------------------------------------
# lip declash — abel's mouth crumples into itself
# ---------------------------------------------------------------------------------
LIP_DECLASH_KEY = 'lip_declash'
# HOUSE. Umbrella smoothing is only stable in small steps, so the declared value is a
# PER-PASS weight and the pass count is fixed here. Eight is the smallest count at which
# the per-pass weight needed on abel stays below 0.5, which is the classical stability
# edge for an explicit umbrella step; fewer passes need a bigger step and start to shrink
# the lip rather than unfold it.
LIP_DECLASH_PASSES = 8
_LIP_GROUP = {}
_ADJ = {}


def _vertex_adjacency(faces):
    """{vertex -> neighbour indices} over the quad cage, built once per face array.

    Quad EDGES only (0-1, 1-2, 2-3, 3-0) and not the diagonals: an umbrella step over
    diagonals as well would smooth across the quad rather than along the surface grid.
    """
    key = id(faces)
    hit = _ADJ.get(key)
    if hit is not None:
        return hit
    f = np.asarray(faces)
    pairs = []
    n = f.shape[1]
    for i in range(n):
        pairs.append(f[:, [i, (i + 1) % n]])
    e = np.concatenate(pairs, axis=0)
    e = np.concatenate([e, e[:, ::-1]], axis=0)
    order = np.argsort(e[:, 0], kind='stable')
    e = e[order]
    starts = np.searchsorted(e[:, 0], np.arange(int(f.max()) + 2))
    adj = [np.unique(e[starts[i] : starts[i + 1], 1]) for i in range(len(starts) - 1)]
    _ADJ.clear()
    _ADJ[key] = adj
    return adj


def _lip_weight_group():
    """Per-vertex weight of the ORBICULARIS ORIS ring, computed once.

    The group is named from the rig's own anatomy (every bone whose label starts with
    `oris`), not from where abel happens to self-intersect — a group cut around the
    defect would be circular and would not transfer to another body. MEASURED: the oris
    ring is 880 vertices and covers all 42 vertices involved in abel's 14 lip
    intersections, so nothing the layer needs to reach falls outside it.

    Using the WEIGHT rather than the index set is what makes the smoothing fade to zero
    at the edge of the mouth: a vertex the ring barely owns barely moves, so no crease
    can appear at the boundary. Same reasoning as _toe_weight_groups.
    """
    if _LIP_GROUP:
        return _LIP_GROUP['w']
    m = _model()
    names = [str(n) for n in _bone_names(m)]
    W = np.asarray(m.vertex_bone_weights.detach().cpu().numpy(), np.float64)
    I = np.asarray(m.vertex_bone_indices.detach().cpu().numpy(), np.int64)
    w = np.zeros(len(W), np.float64)
    cols = {bi for bi, nm in enumerate(names) if nm.lower().startswith('oris')}
    if not cols:
        raise RuntimeError(
            'this rig has no bone named oris*; the lip declash is written against '
            "MakeHuman's orbicularis oris ring and cannot identify the mouth without it"
        )
    for k in range(I.shape[1]):
        w += np.where(np.isin(I[:, k], list(cols)), W[:, k], 0.0)
    _LIP_GROUP['w'] = np.clip(w, 0.0, 1.0)
    return _LIP_GROUP['w']


def _apply_lip_declash(v, faces, anatomy):
    """Unfold a mouth that crumples into itself, by minimal local smoothing.

    THE DEFECT, MEASURED on derived/abel 2026-08-08. He is the only one of the four
    issued bodies with any self-intersection at all, and after the toe declash cleared
    his 4 toe pairs, 14 remain — every one of them on the orbicularis oris ring,
    perfectly mirror-symmetric (7 left, 7 right), interpenetrating by 0.25-1.50 mm inside
    a band 41 mm wide, 4 mm deep and 2 mm TALL.

    THE CAUSE IS THE AGE MACRO, not a morph and not the mesh. Swept with every local
    change removed, intra-component pairs go 164 at age 1.0 y, 90 at 5.8 y, 18 at 12.0 y
    (his) and ZERO at 17.8 y and above. abel carries no local morphs at all, so there is
    nothing to back off.

    WHY SMOOTHING AND NOT A PUSH-APART. The obvious fix for two interpenetrating sheets
    is to displace them along their normals, and that was measured and rejected: the 14
    pairs' face normals sit between 57.9 and 137.0 degrees apart (median 85.6, only 6 of
    14 actually opposing) and several are almost purely LATERAL (|n_x| up to 0.93). That
    is not two sheets meeting, it is a crumpled fold at the oral commissures, and a
    normal-direction push has no consistent direction to push in. A fold is what umbrella
    smoothing removes.

    NO EXISTING CONTROL DOES IT, measured before building this. All 29 of anny's
    mouth/lip/chin local morphs were swept at +/-0.2 and +/-0.5: the best
    (mouth-scale-vert-incr at +0.5) takes 14 pairs to 8, several make it WORSE
    (mouth-lowerlip-volume-incr +0.5 gives 46), and none reaches zero.

    `lip_declash` is the per-pass umbrella weight, applied LIP_DECLASH_PASSES times and
    scaled per vertex by the oris ring's own skinning weight; absent or <= 0 returns the
    input array unchanged, so no body that does not declare it can move. The displacement
    is symmetrised through relief.mirror_map for the same reason the toe layer is: the
    cage's own neighbourhoods are not mirror-exact and this package has been caught by
    that before.
    """
    s = float((anatomy or {}).get(LIP_DECLASH_KEY) or 0.0)
    if s <= 0.0:
        _apply_lip_declash.last_declash = {
            'lip_declash': 0.0,
            'status': 'absent',
            'reason': 'anatomy carries no %r' % LIP_DECLASH_KEY,
        }
        return v
    from zyg_workflows.geom import relief as RELIEF

    P = np.asarray(v, np.float64).copy()
    P0 = P.copy()
    w = _lip_weight_group()
    adj = _vertex_adjacency(faces)
    moving = np.where(w > 1e-6)[0]
    for _ in range(LIP_DECLASH_PASSES):
        upd = P[moving].copy()
        for j, i in enumerate(moving):
            nb = adj[i]
            if len(nb) == 0:
                continue
            upd[j] = P[i] + s * w[i] * (P[nb].mean(0) - P[i])
        P[moving] = upd
    D = P - P0
    stature = float(np.ptp(P0[:, 2]))
    mate, _pd = RELIEF.mirror_map(P0, RELIEF.MIRROR_TOL_FRAC * stature)
    D, _have = RELIEF.symmetrise_field(D, mate)
    out = P0 + D
    ok = mate >= 0
    resid = float(np.abs(D[ok][:, 1:] - D[mate[ok]][:, 1:]).max()) * 1000.0 if ok.any() else float('nan')
    _apply_lip_declash.last_declash = {
        'lip_declash': s,
        'status': 'applied',
        'passes': LIP_DECLASH_PASSES,
        'n_vertices_moved': int((np.linalg.norm(D, axis=1) > 1e-9).sum()),
        'max_move_mm': float(np.linalg.norm(D, axis=1).max()) * 1000.0,
        'mirror_residual_mm': resid,
        'group': 'orbicularis oris ring (bones oris*), %d vertices' % int((w > 0).sum()),
    }
    return out


_apply_lip_declash.last_declash = None


def _toe_weight_groups():
    """{('L'|'R', digit): per-vertex skinning weight of that toe}, computed once.

    Skinning weights are a property of the rig, not of a recipe — they are topology-fixed
    and do not enter _vert_sha — so this is measured once per process and reused. Using
    the weights (rather than a z/y box) is what makes the layer fade to nothing at the
    metatarsal heads: at the toe base the toe bones own almost none of the vertex, so the
    displacement there is almost zero and no crease can appear at the join.
    """
    if _TOE_GROUPS:
        return _TOE_GROUPS
    m = _model()
    names = [str(n) for n in _bone_names(m)]
    W = np.asarray(m.vertex_bone_weights.detach().cpu().numpy(), np.float64)
    I = np.asarray(m.vertex_bone_indices.detach().cpu().numpy(), np.int64)
    per = {}
    for bi, nm in enumerate(names):
        low = nm.lower()
        if not low.startswith('toe'):
            continue
        digit = int(low[3])
        side = 'L' if low.endswith('.l') else 'R'
        per.setdefault((side, digit), np.zeros(len(W)))
        for c in range(W.shape[1]):
            hit = I[:, c] == bi
            if hit.any():
                per[(side, digit)][hit] += W[hit, c]
    for k in per:
        _TOE_GROUPS[k] = np.clip(per[k], 0.0, 1.0)
    return _TOE_GROUPS


def _apply_toe_declash(v, faces, anatomy):
    """Slim each toe toward its own long axis so the shell stops crossing itself.

    THE DEFECT, measured, not assumed. originals/female fails t1_self_intersection with
    20 robust intra-component quad pairs, ALL of them toe4 x toe5, both feet, penetrating
    by 1.4-4.0 mm, at 0.0076-0.0107 of stature. It is not caused by any fitted morph: at
    the neutral macros with no local changes at all the count is unchanged, and a gender
    sweep on the bare template gives 0 pairs at gender 0.0 and 20-36 pairs at every value
    from 0.25 to 1.0. The little toe crossing into the fourth is anny's female-side gender
    target, and originals/male passes only because it sits at gender 0.0. So the fix
    cannot be "back off a morph" — there is no morph to back off.

    WHAT THIS DOES. Each toe's vertices are contracted toward the line through the toe's
    own centroid parallel to the toe's long axis (anny's toes point along -y, so the axis
    IS y and the contraction is in x/z), by `scale * w`, where w is that toe's skinning
    weight. Both members of a crossing pair shrink, so the gap opens from both sides and
    neither toe has to be translated: foot breadth cannot grow, and the toe tips stay
    where they are along the foot's length. `scale` is a fraction, carried per character
    in anatomy_layer[%r]; absent or <= 0 returns the input array unchanged, so no body
    that does not declare it can move.

    SYMMETRY. The centroid of every RIGHT toe is taken as the mirror of its LEFT partner
    (cx -> -cx, cz shared) rather than measured independently, so the two feet are the
    same expression evaluated on the same numbers; the displacement field is then run
    through relief.mirror_map/symmetrise_field as well and the residual is recorded in
    last_declash['mirror_residual_mm']. Two independent defences, one measured, because
    the cage's own vertex normals are not mirror-symmetric and this package has been
    caught by that once already.
    """ % TOE_DECLASH_KEY
    scale = float((anatomy or {}).get(TOE_DECLASH_KEY) or 0.0)
    if scale <= 0.0:
        # cleared, not left stale — see _apply_abs_definition for the same reason
        _apply_toe_declash.last_declash = {
            'toe_declash': 0.0,
            'status': 'absent',
            'reason': 'anatomy carries no %r' % TOE_DECLASH_KEY,
        }
        return v
    from zyg_workflows.geom import relief as RELIEF

    P64 = np.asarray(v, np.float64)
    groups = _toe_weight_groups()
    D = np.zeros_like(P64)
    digits = sorted({d for (_s, d) in groups})
    centroids = {}
    for d in digits:
        wl = groups.get(('L', d))
        if wl is None:
            continue
        sel = np.nonzero(wl > 0.5)[0]
        if not len(sel):
            continue
        cx = float(P64[sel, 0].mean())
        cz = float(P64[sel, 2].mean())
        centroids[d] = (cx, cz)
    for (side, d), w in sorted(groups.items()):
        if d not in centroids:
            continue
        cx, cz = centroids[d]
        if side == 'R':
            cx = -cx  # mirror partner, not an independent measurement
        act = np.nonzero(w > 0.0)[0]
        if not len(act):
            continue
        f = (scale * w[act])[:, None]
        ref = np.stack([np.full(len(act), cx), np.zeros(len(act)), np.full(len(act), cz)], axis=1)
        delta = P64[act] - ref
        delta[:, 1] = 0.0  # never move a toe along its own length
        D[act] -= f * delta

    stature = max(float(P64[:, 2].max() - P64[:, 2].min()), 1e-6)
    mate, _pair_dist = RELIEF.mirror_map(P64, RELIEF.MIRROR_TOL_FRAC * stature)
    Dsym, _have = RELIEF.symmetrise_field(D, mate)
    resid_m = RELIEF.field_mirror_residual_m(Dsym, mate) or 0.0
    raw_resid_m = RELIEF.field_mirror_residual_m(D, mate) or 0.0

    out = np.asarray(v).copy()
    write = np.nonzero(np.abs(Dsym).max(axis=1) > 0.0)[0]
    out[write] = (P64[write] + Dsym[write]).astype(out.dtype)
    moved = np.linalg.norm(np.asarray(out, np.float64) - P64, axis=1)
    _apply_toe_declash.last_declash = {
        'toe_declash': scale,
        'toes': int(len(groups)),
        'displaced_vertices': int((moved > 1e-9).sum()),
        'max_displacement_mm': float(1e3 * moved.max()),
        'unpaired_vertices': int((mate < 0).sum()),
        # BOTH numbers, deliberately: the second is what the mirror-by-construction
        # achieved on its own, the first is what survives after the symmetriser. If the
        # two differ the construction is not carrying the symmetry and should be fixed
        # rather than papered over.
        'mirror_residual_mm': float(1e3 * resid_m),
        'mirror_residual_before_symmetrise_mm': float(1e3 * raw_resid_m),
    }
    return out


_apply_toe_declash.last_declash = None


def _apply_anatomy(v, faces, anatomy, phenotype=None, local_changes=None, bone_scales=None, params=None):
    """THE DISPLACEMENT STACK. Everything that sculpts the cage after the morph solve
    and before export, in one place, in a fixed order, for every caller.

    Three layers, each gated on its own key in the character's anatomy_layer and each a
    no-op (returning the INPUT ARRAY) when its key is absent or <= 0:

      1. abs_definition  rectus relief                    _apply_abs_definition
      2. bony_relief     subcutaneous bone landmarks      geom/relief.py
      3. toe_declash     stops the female toes crossing   _apply_toe_declash

    WHY THEY ARE ALL IN HERE rather than composed at the two or three build sites. About
    two dozen call sites across geom/anthro and geom/form rebuild a character with
    `_build_mesh(...)` then `_apply_anatomy(v, faces, params['anatomy_layer'])` — that
    pair IS the delivered cage, and the cage hash check in _rebuild_from_params proves it.
    A layer wired in anywhere else would produce a body the gates never see, i.e. exactly
    the split-brain this package exists to prevent. Adding the layers here means every
    one of those callers measures the mesh that ships, with no edit to any of them.

    THE RIG. geom/relief.py anchors to bone positions, which depend on the recipe, and
    `anatomy` alone does not carry one. Callers that have the phenotype should pass it;
    callers that do not are served from the cache _build_mesh fills on its way past (the
    rig for the exact vertex array it produced), so the common
    `_build_mesh(...) -> _apply_anatomy(...)` pair needs no second forward pass and no
    edit. If neither is available AND the character actually asks for bony_relief, this
    RAISES: guessing a skeleton would silently sculpt landmarks onto the wrong bones.
    """
    # THE RIG IS RESOLVED FIRST, BEFORE ANY LAYER RUNS. The cache is keyed on the bytes
    # of the array _build_mesh produced, and layer 1 returns a NEW array for any body
    # carrying abs_definition — so looking the rig up after it has run misses on exactly
    # the bodies that have an abs layer and hits on the ones that do not. That is not a
    # theory: it is what happened, and it turned t5_digit_chains / t5_phalanx_ratio /
    # t5_child_hand from `fail` into `error` on originals/male while leaving the female
    # alone, because geom/form/hands.py builds and then applies in two statements.
    rig = None
    if _relief_requested(anatomy):
        rig = _rig_for(v, phenotype, local_changes, bone_scales, params)
    v = _apply_abs_definition(v, faces, anatomy)
    if rig is not None:
        v = _apply_bony_relief(v, faces, anatomy, rig)
    v = _apply_toe_declash(v, faces, anatomy)
    # LAST in the stack on purpose: it is a repair of whatever the layers above left
    # behind, so it has to see their output. Its own key gates it, so a body that does
    # not declare lip_declash is byte-identical with it present.
    v = _apply_lip_declash(v, faces, anatomy)
    return v


def _relief_requested(anatomy):
    return float((anatomy or {}).get('bony_relief') or 0.0) > 0.0 and _bony_relief_enabled()


def _bony_relief_enabled():
    """ZYG_BONY_RELIEF, DEFAULT ON.

    On means "honour anatomy_layer['bony_relief']". The flag is a per-process rollback
    lever, not a feature switch: with ZYG_BONY_RELIEF=0 every cage in the repo is
    byte-identical to the pre-2026-08-06 geometry no matter what its anatomy_layer says.
    Off-values match _anthro_enabled() so there is one convention.

    WHO ACTUALLY CARRIES THE KEY, 2026-08-07: nobody in ORIGINAL_ANATOMY — the fifth issue
    dropped it from both originals (the rationale is measured out beside that dict).
    derived/abel and derived/cornelis never carried it. The FOURTH-issue originals still
    sitting on disk under data/assets/mesh_skeletons/originals DO carry it in their
    params.json and will keep applying it until they are re-issued from the tables above;
    that is the immutability contract working as designed, not a bug. An earlier version
    of this docstring claimed no issued character carried the key, which was wrong from
    the moment the fourth issue shipped.
    """
    return os.environ.get('ZYG_BONY_RELIEF', '1').strip().lower() not in ('0', 'false', 'no', 'off', '')


def _apply_bony_relief(v, faces, anatomy, rig):
    """geom/relief.py, wired into the stack. See that module for the measurements.

    `rig` is resolved by the caller against the PRE-LAYER vertex array — see
    _apply_anatomy for why that ordering is load-bearing.
    """
    if not _relief_requested(anatomy):
        return v
    from zyg_workflows.geom import relief as RELIEF

    return RELIEF.apply_relief(
        v,
        faces,
        anatomy,
        phenotype=rig['phenotype'],
        bones=rig['bones'],
        weights=rig['weights'],
        bone_names=rig['bone_names'],
    )


def _subdivide(v, f, levels=DISPLAY_SUBDIV, seed_cage=None):
    """Catmull-Clark subdivision of a quad mesh, tracking which subdivided edges lie ON
    original cage edges (so the display can overlay the true control grid).

    Returns (verts float32 (V,3), quads int64 (F,4), cage_edges int64 (E,2)).
    Standard rules: face point = face mean; interior edge point = (ends + adjacent face
    points)/4; interior vertex -> (Q + 2R + (n-3)P)/n; boundary edges/verts use the
    curve rules (midpoint / (M1 + 6P + M2)/8). Original vertex indices are preserved at
    the head of each level's vertex array, which is what makes cage tracking exact.

    seed_cage: pass a previously-tracked cage edge array to continue subdividing an
    ALREADY-subdivided mesh while keeping the original cage grid (without it, every
    edge of the input is treated as cage).
    """
    v = v.astype(np.float64)
    f = f.astype(np.int64)
    if seed_cage is not None:
        cage = set((int(a), int(b)) if a < b else (int(b), int(a)) for a, b in seed_cage)
    else:
        cage = set()
        for quad in f:
            for i in range(4):
                a, b = int(quad[i]), int(quad[(i + 1) % 4])
                cage.add((a, b) if a < b else (b, a))
    for _ in range(max(0, int(levels))):
        V, F = len(v), len(f)
        fp = v[f].mean(axis=1)
        edges = {}
        e_of_face = np.empty((F, 4), np.int64)
        for fi in range(F):
            q = f[fi]
            for i in range(4):
                a, b = int(q[i]), int(q[(i + 1) % 4])
                key = (a, b) if a < b else (b, a)
                rec = edges.get(key)
                if rec is None:
                    rec = edges[key] = [len(edges), []]
                rec[1].append(fi)
                e_of_face[fi, i] = rec[0]
        E = len(edges)
        ep = np.zeros((E, 3))
        emid = np.zeros((E, 3))
        eb = np.zeros(E, bool)
        ekey = np.empty((E, 2), np.int64)
        for (a, b), (eid, fl) in edges.items():
            ekey[eid] = (a, b)
            emid[eid] = (v[a] + v[b]) / 2.0
            if len(fl) == 2:
                ep[eid] = (v[a] + v[b] + fp[fl[0]] + fp[fl[1]]) / 4.0
            else:
                ep[eid] = emid[eid]
                eb[eid] = True
        vf_sum = np.zeros((V, 3))
        vf_cnt = np.zeros(V)
        for fi in range(F):
            for vv in f[fi]:
                vf_sum[vv] += fp[fi]
                vf_cnt[vv] += 1
        ve_sum = np.zeros((V, 3))
        ve_cnt = np.zeros(V)
        vb_sum = np.zeros((V, 3))
        vb_cnt = np.zeros(V)
        for eid in range(E):
            a, b = ekey[eid]
            ve_sum[a] += emid[eid]
            ve_sum[b] += emid[eid]
            ve_cnt[a] += 1
            ve_cnt[b] += 1
            if eb[eid]:
                vb_sum[a] += emid[eid]
                vb_sum[b] += emid[eid]
                vb_cnt[a] += 1
                vb_cnt[b] += 1
        newv = v.copy()
        n = ve_cnt
        interior = (vb_cnt == 0) & (n >= 3)
        nn = n[interior, None]
        Q = vf_sum[interior] / np.maximum(vf_cnt[interior, None], 1)
        R = ve_sum[interior] / nn
        newv[interior] = (Q + 2.0 * R + (nn - 3.0) * v[interior]) / nn
        bnd = vb_cnt == 2
        newv[bnd] = (vb_sum[bnd] + 6.0 * v[bnd]) / 8.0
        verts = np.concatenate([newv, fp, ep])
        fpi = V + np.arange(F)
        epi = V + F + np.arange(E)
        newf = np.empty((F * 4, 4), np.int64)
        k = 0
        for fi in range(F):
            q = f[fi]
            e = e_of_face[fi]
            for i in range(4):
                newf[k] = (q[i], epi[e[i]], fpi[fi], epi[e[(i - 1) % 4]])
                k += 1
        newcage = set()
        for (a, b), (eid, _fl) in edges.items():
            if (a, b) in cage:
                mi = int(epi[eid])
                newcage.add((a, mi) if a < mi else (mi, a))
                newcage.add((b, mi) if b < mi else (mi, b))
        v, f, cage = verts, newf, newcage
    ce = np.array(sorted(cage), np.int64) if cage else np.zeros((0, 2), np.int64)
    return v.astype(np.float32), f, ce
