# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.patella_skin — the extensor-mechanism skinning correction (the patellar ligament).

WHAT IS BROKEN, MEASURED
------------------------
`geom.pose_limits.t5_patellar_ligament` asserts the one invariance AFS p.208 prints: the
patellar ligament holds the patella at a fixed distance from the tibial tuberosity through
the whole knee range. On the shipped rig it does not hold — measured drift 10.17 % to
27.32 % across the five bodies. The cause is not a mesh defect and not a morph: it is the
SKINNING SOLVE. The `patella` surface patch published by geom.form.regions is weighted

    upperleg02.{L,R}  0.8202      lowerleg01.{L,R}  0.1798

so 82 % of the kneecap's skin rides the FEMUR while the tibial tuberosity patch rides the
TIBIA (lowerleg01 0.9501 / lowerleg02 0.0417 / upperleg02 0.0082). Two patches on opposite
sides of a hinge cannot hold a fixed distance. There is no patella bone in the 163-bone rig
and this module does not invent one.

WHY THE CORRECT ANSWER IS "THE SHANK", AND WHY THERE IS NO MIDDLE
-----------------------------------------------------------------
Anatomically the patella is a sesamoid in the extensor mechanism: it is tethered distally
to the tibial tuberosity by an inextensible ligament and glides over the femoral condyles.
Its POSITION therefore tracks the tibia; only its tilt is shared with the femur. LBS cannot
separate those two, so the position is the thing to get right.

The admissible weight is not a matter of taste — it is forced by the algebra of linear
blend skinning, and the derivation is written out here because it is the reason this module
does not offer a gentler option. With only `lowerleg01` driven, the femur's transform is the
identity, so a patella vertex with femur weight w lands at

    p'(w) = w * p  +  (1 - w) * (R (p - knee) + knee)

Write u_i = p_i - knee and v = tuberosity_centroid - knee. The patch centroid separation is

    D(R) = a + R b,     a = mean_i(w_i u_i) - e_f v,     b = mean_i((1-w_i) u_i) - (1-e_f) v

with e_f = 0.0082 the tuberosity's own residual femur share. |D(I)| = d0 by construction,
and |D(R)| ranges over [ ||a|-|b|| , |a|+|b| ] as R sweeps. So the drift is governed by |a|,
and |a| cannot be cancelled by clever per-vertex bookkeeping: every u_i in the patch has the
same sign of anterior offset (measured, neutral body: u_i.y ranges -37.4 mm to -62.0 mm, all
negative), so mean_i(w_i u_i) has magnitude at least 37 mm * mean(w). Holding |D| inside 2 %
of d0 = 124.3 mm needs |a| of order 1 mm, i.e.

    mean femur weight over the patella patch  <=  ~0.03      (from 0.82)

There is no weighting that keeps the femur as majority owner and passes. "Skin the kneecap
to the shin" is the only answer the geometry admits, and it is also the anatomy.

WHAT THIS MODULE DOES
---------------------
It redirects a FRACTION t(v) of each vertex's upperleg02 weight to lowerleg01, same side:

    t = 1                      on the patella region (the kneecap patch itself)
    t = smoothstep falloff     over `rings` rings of cage neighbours outward
    t = 0                      beyond

Two properties make that field the right shape rather than a blunt stamp:

* It acts on the femur weight that is ALREADY THERE. Below the patella there is almost no
  femur weight left, so the field is a no-op over the ligament and tuberosity — exactly
  where the skin already tracks the tibia. Above the patella the femur owns nearly
  everything, so that is where the transition lands: in the suprapatellar region, which is
  where the extensor mechanism's kinematic discontinuity actually is (quadriceps tendon
  above, patella below). The asymmetry is produced by the anatomy of the existing solve,
  not hand-placed.
* Weight is MOVED, never created: every row still sums to what it summed to before, so no
  vertex changes at rest beyond LBS's own reassociation noise (measured below).

RING DISTANCE, NOT A RADIUS, AND WHY — THE MIRROR TRAP
------------------------------------------------------
The falloff is indexed by CAGE GRAPH DISTANCE from the patella patch, never by a metric
radius and never by a vertex normal. The cage's vertex normals are structurally
non-mirror-symmetric (max |n - mirror(n)| = 1.168 measured), and any field built from them
or from a signed coordinate would give the two legs different weights and put a real
asymmetry into every posed body. A graph ring index is an integer read off the topology, so
the L and R fields are identical by construction, with no floating-point path at all. The
residual is measured anyway rather than asserted — see `mirror_residual_mm`.

WHAT THE GATE SAYS AFTERWARDS, AND WHY IT IS NOT A PASS
-------------------------------------------------------
`t5_patellar_ligament` carries a vacuity guard: `trivial = (top_p == top_t)`, and when the
two patches' TOP skin owner is the same bone it downgrades the verdict to `report` on the
grounds that a distance between two patches driven by one bone is invariant by
construction and tests nothing. That guard fires here — after the correction both patches
are topped by `lowerleg01` — so the row goes

    fail (drift 10.17-27.32 %)   ->   report (drift 0.62-1.13 %)

and NOT to pass. The guard is right to fire and this module does not try to dodge it: any
weighting that satisfies the invariance makes the tibia the majority owner (see the algebra
above), so on this rig "the ligament is modelled" and "the gate can still discriminate" are
mutually exclusive. What the guard cannot see is that the invariance is not quite by
construction even so — the residual 0.62-1.13 % is real, and it is the tuberosity patch's
own 0.82 % femur contamination, which this module deliberately does NOT clean up because
that patch is the measurement's reference.

DETERMINISM: THIS IS FREE
-------------------------
`mesh_skeletons._vert_sha` hashes rest-cage vertices rounded to 4 dp of a metre (0.1 mm
quanta). Skinning weights do not enter it, and the rest cage is produced with an identity
pose where every bone transform is the identity, so moving weight between bones changes the
result only through floating-point reassociation of (v - h) + h. Measured, that is 7.5e-6 mm
— eight orders below the hash quantum. `verify_cage_unchanged()` re-derives the sha for a
given recipe with and without the correction and returns the pair rather than claiming it.
"""

import os

import numpy as np

from zyg_workflows.geom import mesh_skeletons as MS

SCHEMA = 'geom.patella_skin/1'

# --- the two ends of the transfer ------------------------------------------------------
# NOT a tunable pair: `upperleg02` is the bone the measurement found holding 82 % of the
# kneecap, and `lowerleg01` is the bone the tuberosity patch is already 95 % skinned to.
# Changing either would be changing which bones this rig calls femur and tibia.
FEMUR_BONE = 'upperleg02.%s'
TIBIA_BONE = 'lowerleg01.%s'

# The patch the correction is anchored on. A FROZEN vertex group published by
# geom.form.regions, not a set chosen here.
PATELLA_REGION = 'patella'

# How far the transition is spread, in cage rings. This is a SMOOTHING width and it is NOT
# an acceptance threshold: the patch core is t = 1 for every value of it, so the ligament
# verdict does not depend on it and it cannot be moved to make a gate pass. Two measured
# facts fix it, neither of them a preference.
#
# (1) THE CEILING IS 2, and the reason is external to any shape metric: at 3 the field
#     reaches the tibial tuberosity — the patch t5_patellar_ligament measures AGAINST.
#     Measured overlap with geom.form.regions' tuberosity vertex set:
#         rings 0/1/2 -> 0 vertices     rings 3 -> 3 vertices     rings 4 -> 7 vertices
#     and the drift changes exactly where the overlap starts (male 0.7786 % at rings 0, 1
#     and 2 — bit-identical — then 0.6569 % at rings 3). A correction that edits the
#     measurement's own reference is a correction marking its own homework, so 2 is the
#     largest width that provably does not.
# (2) WITHIN 0..2, 2 CREASES LEAST. Anterior knee band (male 228 edges / female 272),
#     count of edges whose dihedral moves more than 60 deg from rest, base solve = 0
#     everywhere:
#         male    60 deg  90 deg  120 deg      female   60 deg  90 deg  120 deg
#         r0        7      17      21          r0        17      22      32
#         r1        3       7      16          r1         3      19      30
#         r2        1       5      11          r2         1       8      15
#     Monotone in favour of 2 at every angle on both bodies. The worst-single-triangle
#     area ratio does NOT agree at male 120 deg (r1 0.132 vs r2 0.058) and that
#     disagreement is reported rather than dropped; the fold count is preferred because it
#     is a count over the band and not one triangle.
FALLOFF_RINGS = 2

# Default OFF. This is not a threshold and nothing about the gate changes with it: with the
# flag off t5_patellar_ligament still FAILs and still prints the true 10.17-27.32 % drift.
# It is off because the trade this module makes is genuinely two-sided and the measurement
# says so — see MEASURED_COST below. Turn it on with ZYG_PATELLA_TRACKING=1.
FLAG = 'ZYG_PATELLA_TRACKING'

# WHAT THE CORRECTION COSTS, MEASURED. Kept next to the code that causes it.
#
# FREE, verified not asserted:
#   * rest cage byte-identical. `verify_cage_unchanged` rebuilds originals/male and
#     originals/female through the issuer's own path (_build_mesh -> _apply_anatomy ->
#     float32 -> _vert_sha) with and without the correction: both reproduce the registry's
#     recorded cage_vert_sha256 exactly, and the two hashes are equal. Largest per-vertex
#     difference 2.98e-5 mm against a 0.1 mm hash quantum.
#   * rest silhouette unchanged: max |dv| over all 13 718 vertices is 1.28e-5 mm (male) /
#     7.26e-6 mm (female), and every knee-band triangle keeps area ratio 1.0000.
#   * zero new asymmetry: under symmetric bilateral knee flexion at 60 and 120 deg the
#     mirror residual is 0.0599 mm (male) / 0.0014 mm (female) BOTH with and without the
#     correction — delta +0.0000 mm, against integrity.SYM_MORPH_TOL_MM = 0.15.
#
# NOT FREE:
#   * the correction displaces anterior-knee skin as soon as the knee bends at all, and by
#     more than the ligament error it removes. At the fitted pose library's own maximum
#     knee flexion (26.0 deg, abel; cornelis 18.0 deg; 174 knees, none above 30 deg) the
#     defect being removed is 9.9 mm (male) / 15.8 mm (female) of patella-to-tuberosity
#     distance error, while the skin moves 52.4 mm (male) / 36.3 mm (female). Even at
#     10 deg it is 4.7 mm of error removed against 20.3 mm of skin moved.
#   * creasing from ~60 deg upward, where the base solve has none (table above).
#
# ROOT CAUSE OF THE TRADE, and it is not in this file: geom.form.regions' `patella` patch
# is about twice the height of a patella. Measured, top and bottom relative to the rig's
# knee pivot: neutral +62.5 .. -18.8 mm, male +101.5 .. +6.0 mm, female +49.1 .. -31.3 mm —
# 0.048 to 0.052 x stature tall, against roughly 0.024 x stature for a real patella, and on
# the male not one of its 19 vertices reaches the pivot. Roughly its upper half is
# suprapatellar thigh, and that half has the longest lever arm, so it is the part that
# moves most. Skin the true kneecap to the shank and the trade largely disappears; skin
# THIS patch to the shank — which is what the gate's quantity forces, see the module
# docstring — and the suprapatellar half comes with it. Tightening the region, or pointing
# the gate at a kneecap sub-patch, is the fix that has no cost. Neither is done here.
#
# ---------------------------------------------------------------------------------
# 2026-08-08: THE TIGHTENING WAS DONE, AND THE SENTENCE ABOVE — "the fix that has no
# cost" — IS NOT TRUE. It is left standing because it was the reasoning at the time and
# the correction to it is the useful part.
#
# geom.form.regions' patella band_frac went 0.030 -> 0.024, chosen by relief contrast
# alone (a sharp interior argmax, 3.062 -> 6.095; everything below 0.024 collapses to
# flat), a criterion that never looks at ligament drift. It IS an improvement, measured
# at 26 deg of knee flexion, the fitted pose library's own maximum:
#     skin moved   male 54.8 -> 40.8 mm,  female 36.4 -> 26.9 mm,  abel 45.7 -> 34.8 mm
#     drift with the correction on: 0.67-1.20 % on all five bodies, unchanged
# a ~25 % reduction in collateral for no loss of correction.
#
# BUT THE COST DOES NOT GO AWAY, because band width was never the whole cause. Of the
# ~50 vertices the correction still moves more than 1 mm, most are ABOVE the knee pivot —
# male 38 of 50, abel 39 of 49, cornelis 30 of 51, female 26 of 51 — reaching 140 mm
# above it on the male, which is mid-thigh and far outside a 58 mm patch. Two things
# cause that and neither is the band:
#   * THE ANCHOR IS ABOVE THE JOINT. The patch is cut from MakeHuman's
#     `measure-knee-circ-incr` girth ring, which sits at 0.299 of stature — higher than
#     the rig's knee pivot. Measured after the tightening, patch extent relative to the
#     pivot: male +77.8 .. +9.3 mm and abel +70.9 .. +15.6 mm with ZERO of their 15
#     vertices below the pivot at all; female +29.5 .. -29.5 and cornelis +51.0 .. -16.6
#     do straddle it. No band_frac can move a patch below its own ring, so on male-type
#     bodies the anterior knee patch is suprapatellar BY CONSTRUCTION on this cage.
#   * THE FALLOFF REACHES FURTHER THAN THE PATCH. Two rings of cage neighbours spread
#     outward from a patch that is already high, and the thigh is what is outward-and-up.
# The fix that would actually have no cost is a patch anchored on the JOINT LINE rather
# than on the knee girth ring — the same anchor_kind tibial_tuberosity already uses
# ('joint_line_sector'). That is a new region, not a parameter change, and it is not done
# here either. The flag therefore STAYS DEFAULT OFF, on measurement rather than on
# caution.
MEASURED_COST = 'see the comment block above FALLOFF_RINGS'

# Set on the model object once applied, so a second call is a no-op instead of transferring
# the remaining femur weight a second time. A partial-ring field is NOT idempotent under
# repeated application, so this guard is load-bearing, not hygiene.
_APPLIED_ATTR = '_zyg_patella_tracking'


def enabled():
    """Whether the wiring point should call apply_patellar_tracking(). Default OFF."""
    return os.environ.get(FLAG, '0').strip().lower() not in ('', '0', 'false', 'no', 'off')


# ---------------------------------------------------------------------------------------
# cage topology
# ---------------------------------------------------------------------------------------
def _quads(model):
    f = model.faces
    f = f.numpy() if hasattr(f, 'numpy') else np.asarray(f)
    return np.asarray(f, np.int64)


def _adjacency(model):
    """Undirected vertex adjacency of the quad cage, as a list of int arrays."""
    q = _quads(model)
    n = int(model.vertex_bone_weights.shape[0])
    pairs = np.concatenate([q[:, [0, 1]], q[:, [1, 2]], q[:, [2, 3]], q[:, [3, 0]]], 0)
    pairs = np.concatenate([pairs, pairs[:, ::-1]], 0)
    order = np.argsort(pairs[:, 0], kind='stable')
    pairs = pairs[order]
    starts = np.searchsorted(pairs[:, 0], np.arange(n + 1))
    return [np.unique(pairs[starts[i] : starts[i + 1], 1]) for i in range(n)]


def _ring_index(model, seed, rings):
    """Graph distance 0..rings from `seed`, as {vertex: ring}. Integers only — no
    coordinate and no normal enters this, which is what makes the two legs identical."""
    adj = _adjacency(model)
    out = {int(v): 0 for v in seed}
    frontier = [int(v) for v in seed]
    for k in range(1, int(rings) + 1):
        nxt = []
        for v in frontier:
            for w in adj[v]:
                w = int(w)
                if w not in out:
                    out[w] = k
                    nxt.append(w)
        frontier = nxt
        if not frontier:
            break
    return out


def _smoothstep_falloff(k, rings):
    """t(0) = 1, t(rings + 1) = 0, C1 in between. A cosine or a cubic would both do; the
    cubic smoothstep is used because it is the same curve the rest of geom/form uses."""
    if rings <= 0:
        return 1.0 if k == 0 else 0.0
    s = float(k) / float(rings + 1)
    return float(1.0 - (3.0 * s * s - 2.0 * s * s * s))


# ---------------------------------------------------------------------------------------
# the region, and the bones
# ---------------------------------------------------------------------------------------
def _region(side):
    from zyg_workflows.geom.form import regions as RG

    doc = RG.load_regions()
    rec = doc['regions'].get(PATELLA_REGION)
    if rec is None:
        raise RuntimeError('geom.form.regions publishes no region %r' % PATELLA_REGION)
    if rec.get('status') != 'resolved':
        raise RuntimeError('region %r is %s, not resolved' % (PATELLA_REGION, rec.get('status')))
    idx = rec['vertex_idx_l' if side.lower() == 'l' else 'vertex_idx_r']
    if not idx:
        raise RuntimeError('region %r has no vertices on side %r' % (PATELLA_REGION, side))
    return np.asarray(idx, np.int64)


def _bone_index(model, name):
    names = MS._bone_names(model)
    if name not in names:
        raise RuntimeError('this rig has no bone %r; it has %d bones' % (name, len(names)))
    return names.index(name)


# ---------------------------------------------------------------------------------------
# snapshot / restore — so a caller can measure against the untouched solve
# ---------------------------------------------------------------------------------------
def snapshot(model=None):
    m = MS._model() if model is None else model
    return {
        'w': m.vertex_bone_weights.detach().clone(),
        'i': m.vertex_bone_indices.detach().clone(),
        'applied': getattr(m, _APPLIED_ATTR, None),
    }


def restore(snap, model=None):
    import torch

    m = MS._model() if model is None else model
    with torch.no_grad():
        m.vertex_bone_weights.copy_(snap['w'])
        m.vertex_bone_indices.copy_(snap['i'])
    if snap.get('applied') is None:
        if hasattr(m, _APPLIED_ATTR):
            delattr(m, _APPLIED_ATTR)
    else:
        setattr(m, _APPLIED_ATTR, snap['applied'])


def is_applied(model=None):
    m = MS._model() if model is None else model
    return getattr(m, _APPLIED_ATTR, None)


# ---------------------------------------------------------------------------------------
# THE CORRECTION
# ---------------------------------------------------------------------------------------
def apply_patellar_tracking(model=None, rings=FALLOFF_RINGS, sides=('l', 'r')):
    """Redirect the extensor-mechanism skin from the femur to the tibia, in place.

    Returns the record of what it did — per side, how much weight moved, on how many
    vertices, and the resulting patch ownership. Idempotent: a second call returns the
    first call's record with `reapplied=False` and touches nothing.

    NOTHING about the cage changes. This edits `vertex_bone_weights` /
    `vertex_bone_indices` on the shared model only; the rest cage is produced with an
    identity pose, where the transfer is a floating-point no-op (measured 7.5e-6 mm,
    against a hash quantum of 0.1 mm — see verify_cage_unchanged()).
    """
    import torch

    m = MS._model() if model is None else model
    prev = getattr(m, _APPLIED_ATTR, None)
    if prev is not None:
        return dict(prev, reapplied=False)

    W = m.vertex_bone_weights
    I = m.vertex_bone_indices
    n_slots = int(W.shape[1])
    rec = {'schema': SCHEMA, 'rings': int(rings), 'sides': [], 'reapplied': True}

    for side in sides:
        S = 'L' if side.lower() == 'l' else 'R'
        femur = _bone_index(m, FEMUR_BONE % S)
        tibia = _bone_index(m, TIBIA_BONE % S)
        seed = _region(side)
        ringmap = _ring_index(m, seed, rings)

        moved = 0.0
        touched = 0
        no_slot = []
        with torch.no_grad():
            for v, k in sorted(ringmap.items()):
                t = _smoothstep_falloff(k, rings)
                if t <= 0.0:
                    continue
                row_i = I[v].tolist()
                row_w = W[v]
                # every column that is this side's femur (anny may list a bone once, but
                # summing over columns costs nothing and cannot be wrong)
                cols_f = [c for c in range(n_slots) if int(row_i[c]) == femur and float(row_w[c]) > 0.0]
                if not cols_f:
                    continue
                take = sum(float(row_w[c]) * t for c in cols_f)
                if take <= 0.0:
                    continue
                # find the destination BEFORE touching anything: a transfer that cannot be
                # completed must leave the row exactly as it was, not partially drained.
                cols_t = [c for c in range(n_slots) if int(row_i[c]) == tibia]
                if cols_t:
                    dest = cols_t[0]
                else:
                    free = [c for c in range(n_slots) if float(row_w[c]) == 0.0]
                    if not free:
                        no_slot.append(int(v))
                        continue
                    dest = free[0]
                    I[v, dest] = tibia
                for c in cols_f:
                    row_w[c] = float(row_w[c]) * (1.0 - t)
                row_w[dest] = float(row_w[dest]) + take
                moved += take
                touched += 1

        if no_slot:
            raise RuntimeError(
                'patella transfer needed a free influence slot on %d vertices (%s...) and '
                'the rig has %d. Weight would have been destroyed; refusing.' % (len(no_slot), no_slot[:5], n_slots)
            )

        rec['sides'].append(
            {
                'side': S,
                'seed_vertices': int(len(seed)),
                'vertices_touched': touched,
                'weight_moved': round(float(moved), 6),
                'ring_histogram': {
                    str(k): int(sum(1 for x in ringmap.values() if x == k)) for k in range(int(rings) + 1)
                },
            }
        )

    setattr(m, _APPLIED_ATTR, rec)
    return rec


# ---------------------------------------------------------------------------------------
# evidence
# ---------------------------------------------------------------------------------------
def ownership(model=None, region=PATELLA_REGION, side='l'):
    """What the rig's own skinning says drives a patch, after whatever has been applied."""
    from zyg_workflows.geom import pose_limits as PL

    idx, _ = PL._region_group(region, side)
    return PL._patch_ownership(idx)


def mirror_residual_mm(phenotype, local_changes=None, model=None, pose_aa=None):
    """MEASURED left-right residual of the posed body, in mm.

    The field is built from an integer ring index so the two sides CANNOT diverge by
    construction, but a construction nobody measures is a claim. This mirrors x, matches
    each vertex to its nearest mirrored partner ONCE on the untouched rest cage, and then
    reports the residual of the corrected body under that fixed pairing. Compare against
    geom.anthro.integrity.SYM_MORPH_TOL_MM (0.15 mm).
    """
    from zyg_workflows.geom import pose_limits as PL
    from scipy.spatial import cKDTree

    st = PL.rig_state(phenotype, local_changes, pose_aa)
    v = st['v']
    mir = v * np.array([-1.0, 1.0, 1.0])
    tree = cKDTree(v)
    d, j = tree.query(mir, k=1)
    return {
        'max_mm': float(1000.0 * np.abs(v[j] - mir).max()),
        'rms_mm': float(1000.0 * np.sqrt(((v[j] - mir) ** 2).sum(1).mean())),
        'pairing_max_mm': float(1000.0 * d.max()),
    }


def verify_cage_unchanged(phenotype, local_changes=None, anatomy_layer=None, model=None, rings=FALLOFF_RINGS):
    """Re-derive the exported cage sha with and without the correction. Returns both.

    This does not assert anything. It builds the mesh through the SAME path the issuer
    uses — `_build_mesh` -> `_apply_anatomy` -> float32 -> `_vert_sha` — once with the
    correction restored away and once with it applied, and hands back the two hashes and
    the largest per-vertex difference in mm so the caller can see for itself.

    `anatomy_layer` MUST be passed if the recipe has one (originals/male carries
    {'abs_definition': 1.7}); skipping it reproduces a different cage and the sha will not
    match the registry's, which would make this evidence look like a failure it is not.
    """
    m = MS._model() if model is None else model
    snap = snapshot(m)

    def build():
        v, faces, _ = MS._build_mesh(phenotype, local_changes)
        if anatomy_layer:
            v = MS._apply_anatomy(v, faces, anatomy_layer)
        return np.asarray(v)

    try:
        restore({'w': snap['w'], 'i': snap['i'], 'applied': None}, m)
        v0 = build()
        sha0 = MS._vert_sha(v0)
        apply_patellar_tracking(m, rings=rings)
        v1 = build()
        sha1 = MS._vert_sha(v1)
    finally:
        restore(snap, m)
    return {
        'sha_without': sha0,
        'sha_with': sha1,
        'equal': sha0 == sha1,
        'max_abs_delta_mm': float(1000.0 * np.abs(np.asarray(v1, np.float64) - np.asarray(v0, np.float64)).max()),
    }


def report(bodies=None):
    """Re-derive every number this module claims. Nothing here is cached or quoted."""
    from zyg_workflows.geom import pose_limits as PL

    m = MS._model()
    snap = snapshot(m)
    reg = MS._registry()
    chars = {c['name']: c for c in PL.characters()}
    if bodies is None:
        bodies = [n for n in chars if n != 'anny-neutral'] + ['anny-neutral']
    out = {'schema': SCHEMA, 'rings': FALLOFF_RINGS, 'flag': FLAG, 'enabled': enabled(), 'bodies': []}
    try:
        for nm in bodies:
            c = chars[nm]
            restore({'w': snap['w'], 'i': snap['i'], 'applied': None}, m)
            before = PL.t5_patellar_ligament(c['phenotype'], c['local_changes'], side='l')
            apply_patellar_tracking(m)
            after = PL.t5_patellar_ligament(c['phenotype'], c['local_changes'], side='l')
            restore(snap, m)
            row = {
                'body': nm,
                'before': {
                    'status': before['status'],
                    'max_abs_drift': before['observed']['max_abs_drift'],
                    'rows': before['detail']['rows'],
                    'ownership': before['detail']['patella_skin_ownership'],
                },
                'after': {
                    'status': after['status'],
                    'max_abs_drift': after['observed']['max_abs_drift'],
                    'rows': after['detail']['rows'],
                    'ownership': after['detail']['patella_skin_ownership'],
                },
            }
            p = (reg.get('originals', {}).get(nm) or reg.get('derived', {}).get(nm) or {}).get('params')
            if p:
                v = verify_cage_unchanged(c['phenotype'], c['local_changes'], anatomy_layer=p.get('anatomy_layer'))
                row['cage'] = dict(
                    v,
                    registry_sha=p.get('cage_vert_sha256'),
                    reproduces_registry=(v['sha_with'] == p.get('cage_vert_sha256')),
                )
            out['bodies'].append(row)
    finally:
        restore(snap, m)
    return out


if __name__ == '__main__':
    import json

    print(json.dumps(report(), indent=1, default=float))
