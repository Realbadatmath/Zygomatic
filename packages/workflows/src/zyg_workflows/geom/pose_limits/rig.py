# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Rig enumeration, rotation utilities, rig state and the anatomical frame.

Moved verbatim out of the old single-file pose_limits.py (lines 746-1142).
"""

from zyg_workflows.geom.pose_limits.base import MS, SCHEMA, _set_threads, np
from zyg_workflows.geom.pose_limits.printed import CERVICAL_MAPPING_NOTE, CERVICAL_RIG_JOINTS


# ---------------------------------------------------------------------------------
# rig enumeration — the first deliverable, and a hard precondition for four of the gates
# ---------------------------------------------------------------------------------
# The bone families this module needs, and the gate that dies without each.
RIG_REQUIREMENTS = {
    'wrist': ('wrist.L', 'wrist.R'),
    'hand_rays': ('finger2-1.L', 'finger3-1.L', 'finger5-1.L', 'finger1-3.L'),
    'forearm': ('lowerarm01.L', 'lowerarm02.L', 'lowerarm01.R', 'lowerarm02.R'),
    'upper_arm': ('upperarm01.L', 'upperarm02.L', 'upperarm01.R', 'upperarm02.R'),
    'shoulder_girdle': ('clavicle.L', 'shoulder01.L', 'clavicle.R', 'shoulder01.R'),
    'cervical': ('neck01', 'neck02', 'neck03', 'head'),
    'thorax': ('spine01', 'spine02', 'spine03', 'spine04', 'spine05'),
    'leg': ('upperleg01.L', 'upperleg02.L', 'lowerleg01.L', 'lowerleg02.L', 'foot.L'),
    'pelvis': ('pelvis.L', 'pelvis.R'),
    'eyes': ('eye.L', 'eye.R'),
}

# Bones the plan warned might be missing. Each absence disables a specific claim, and the
# claim is named so the absence is a finding rather than a silent gap.
RIG_EXPECTED_ABSENT = {
    'scapula': 'scapular rotation (AFS p.90) and every scapular-border claim',
    'rib': 'the costal margin and the subcostal angle',
    'patella': 'the patella as a rigid body; it exists here only as a skin patch',
    'radius': 'radius-rolls-around-ulna pronation (AFS p.149)',
    'ulna': 'the ulnar border strip and the olecranon as a bone',
}


def bone_roster():
    """(names, parents) for the live rig, from the model itself. No hard-coded list."""
    m = MS._model()
    names = [str(n) for n in MS._bone_names(m)]
    parents = [int(p) for p in m.bone_parents]
    return names, parents


def rig_report():
    """What this rig actually has, and what every absence costs.

    This is deliberately the cheapest thing in the file to run and the first thing main()
    prints, because four of the six gates are decided by it before any mesh is touched.
    """
    names, parents = bone_roster()
    low = [n.lower() for n in names]
    present, missing = {}, {}
    for family, wanted in RIG_REQUIREMENTS.items():
        have = [b for b in wanted if b in names]
        present[family] = have
        if len(have) != len(wanted):
            missing[family] = [b for b in wanted if b not in names]
    absent = {}
    for key, cost in RIG_EXPECTED_ABSENT.items():
        hits = [n for n, l in zip(names, low) if key in l]
        absent[key] = {'bones': hits, 'absent': not hits, 'disables': cost}
    stems = MS._bone_stems(names)
    return {
        'schema': SCHEMA,
        'n_bones': len(names),
        'bone_names': names,
        'bone_parents': parents,
        'bone_stems': stems,
        'families_present': present,
        'families_incomplete': missing,
        'expected_absent': absent,
        'cervical_chain': list(CERVICAL_RIG_JOINTS),
        'cervical_mapping_note': CERVICAL_MAPPING_NOTE,
        'verdict': (
            '163-bone MakeHuman-derived rig: clavicle, spine01-05, neck01-03, '
            'lowerarm01/02, lowerleg01/02 and pelvis ARE present; scapula, ribs, '
            "patella, radius and ulna are NOT. The plan's warning is confirmed "
            'in every particular.'
        ),
    }


# ---------------------------------------------------------------------------------
# rotation utilities. Nothing here has a parameter.
# ---------------------------------------------------------------------------------
def rotmat(axis_angle):
    """Rodrigues, batched. axis_angle (..,3) -> (..,3,3)."""
    a = np.asarray(axis_angle, np.float64)
    th = np.linalg.norm(a, axis=-1, keepdims=True)
    k = a / np.clip(th, 1e-15, None)
    K = np.zeros(a.shape[:-1] + (3, 3))
    K[..., 0, 1], K[..., 0, 2] = -k[..., 2], k[..., 1]
    K[..., 1, 0], K[..., 1, 2] = k[..., 2], -k[..., 0]
    K[..., 2, 0], K[..., 2, 1] = -k[..., 1], k[..., 0]
    return np.eye(3) + np.sin(th)[..., None] * K + (1.0 - np.cos(th))[..., None] * (K @ K)


def nearest_rotation(R):
    """The proper rotation closest to R (polar decomposition by SVD). No free parameter.

    THIS IS NOT COSMETIC. anny's bone_poses come back orthonormal only to about 1e-7 —
    MEASURED on the neutral, max |R - R_rest| = 6.1e-8 for upperarm01 on a pose that does
    not touch it, with the two matrices otherwise BIT-IDENTICAL. Feeding that straight to
    an arccos trace formula converts the non-orthonormality into a fake rotation: because
    arccos is vertical at 1, a trace defect of 1.4e-7 reads as 0.021 DEGREES. That is what
    made the first run of t5_pronation_isolation report 3.05e-2 deg of humerus rotation
    under a forearm-only drive, on a forward-kinematic rig where the true answer is
    identically zero. Projecting first removes the whole artefact and changes no real
    angle by more than 1e-7 deg.
    """
    U, _, Vt = np.linalg.svd(np.asarray(R, np.float64))
    d = np.sign(np.linalg.det(U @ Vt))
    return U @ np.diag([1.0, 1.0, d]) @ Vt


def rot_angle_deg(R):
    """The magnitude of a rotation, in degrees. Frame-free."""
    tr = float(np.clip((np.trace(nearest_rotation(R)) - 1.0) * 0.5, -1.0, 1.0))
    return float(np.degrees(np.arccos(tr)))


def unit(v):
    v = np.asarray(v, np.float64)
    n = np.linalg.norm(v)
    return v / n if n > 1e-15 else v


def signed_angle_deg(a, b, axis):
    """Signed angle from a to b about `axis`, right-hand rule. Frame-free."""
    a, b, ax = unit(a), unit(b), unit(axis)
    a = unit(a - (a @ ax) * ax)
    b = unit(b - (b @ ax) * ax)
    return float(np.degrees(np.arctan2(np.cross(a, b) @ ax, a @ b)))


def swing_twist(R, axis):
    """Decompose R into (swing, twist) about `axis`. Returns (R_swing, twist_deg).

    Standard quaternion swing-twist. The twist is the rotation about `axis` and the swing
    is everything else; the two compose as R = R_swing @ R_twist. No free parameter.
    """
    R = nearest_rotation(R)
    ax = unit(axis)
    # rotation matrix -> quaternion (w, x, y, z), branch-stable
    tr = np.trace(R)
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2.0
        q = np.array([0.25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s])
    else:
        i = int(np.argmax(np.diag(R)))
        j, k = (i + 1) % 3, (i + 2) % 3
        s = np.sqrt(max(1e-30, 1.0 + R[i, i] - R[j, j] - R[k, k])) * 2.0
        q = np.zeros(4)
        q[0] = (R[k, j] - R[j, k]) / s
        q[i + 1] = 0.25 * s
        q[j + 1] = (R[j, i] + R[i, j]) / s
        q[k + 1] = (R[k, i] + R[i, k]) / s
    w, v = q[0], q[1:]
    proj = (v @ ax) * ax
    tw = np.array([w, proj[0], proj[1], proj[2]])
    n = np.linalg.norm(tw)
    if n < 1e-12:  # 180-degree swing: the twist is undefined
        return R.copy(), 0.0
    tw = tw / n
    twist_deg = float(np.degrees(2.0 * np.arctan2(np.linalg.norm(tw[1:]) * np.sign(tw[1:] @ ax), tw[0])))
    Rt = rotmat(ax * np.radians(twist_deg))
    return R @ Rt.T, twist_deg


def kabsch(P, Q):
    """Optimal rotation taking P onto Q about their centroids. No free parameter.

    Reflections are excluded the standard way (flip the least singular direction), so this
    always returns a proper rotation.
    """
    P = np.asarray(P, np.float64)
    Q = np.asarray(Q, np.float64)
    pc, qc = P.mean(0), Q.mean(0)
    H = (P - pc).T @ (Q - qc)
    U, S, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    D = np.diag([1.0, 1.0, d])
    R = Vt.T @ D @ U.T
    return R, qc - R @ pc


# ---------------------------------------------------------------------------------
# rig state: one forward pass, everything a gate could want
# ---------------------------------------------------------------------------------
_RIG = {}


def _model_index():
    if 'idx' not in _RIG:
        names, parents = bone_roster()
        _RIG['names'] = names
        _RIG['parents'] = parents
        _RIG['idx'] = {n: i for i, n in enumerate(names)}
    return _RIG['idx']


def bone_index(name):
    idx = _model_index()
    if name not in idx:
        raise KeyError('this rig has no bone %r. rig_report() lists all %d.' % (name, len(idx)))
    return idx[name]


def pose_from_local(deltas):
    """{bone_name: axis_angle_in_that_bone's_own_rest_frame} -> (n_bones,3).

    THE FRAME MATTERS AND IS NOT OBVIOUS. anny's pose parameterization is 'local-bone'
    with bone_orientation 'blender-rootidentity', which means each bone's rest pose carries
    a real rotation whose +Y column is the bone's own head->tail direction. A delta of
    (0, t, 0) is therefore a pure TWIST about the bone's long axis, and a delta about any
    perpendicular local axis is a swing. Callers that want a world-space axis should use
    local_axis() to convert.
    """
    names, _ = bone_roster()
    aa = np.zeros((len(names), 3))
    for bone, v in (deltas or {}).items():
        aa[bone_index(bone)] = np.asarray(v, np.float64)
    return aa


def rig_state(phenotype, local_changes=None, pose_aa=None):
    """One posed rig. Everything downstream reads this record and nothing else.

    The REST state is always obtained by running the same forward pass with an identity
    pose rather than by reading rest_bone_heads directly, because anny's 'local-bone'
    parameterization pre-multiplies every posed quantity by a translation to the root and
    the rest arrays are not translated. Comparing the two directly would put a constant
    offset into every distance in this file. Running rest through the same path removes
    that whole class of error by construction.
    """
    _set_threads()
    import torch

    m = MS._model()
    names, _ = bone_roster()
    aa = np.zeros((len(names), 3)) if pose_aa is None else np.asarray(pose_aa, np.float64)
    if aa.shape != (len(names), 3):
        raise ValueError('pose_aa must be (%d,3) for this rig, got %s' % (len(names), (aa.shape,)))
    M = np.tile(np.eye(4), (len(names), 1, 1))
    M[:, :3, :3] = rotmat(aa)
    kw = {
        'phenotype_kwargs': dict(phenotype),
        'return_bone_ends': True,
        'pose_parameters': torch.as_tensor(M[None], dtype=torch.float64),
    }
    if local_changes:
        kw['local_changes_kwargs'] = dict(local_changes)
    with torch.no_grad():
        o = m(**kw)
    heads = o['bone_heads'][0].numpy().astype(np.float64)
    tails = o['bone_tails'][0].numpy().astype(np.float64)
    poses = o['bone_poses'][0].numpy().astype(np.float64)
    return {
        'names': names,
        'heads': heads,
        'tails': tails,
        'R': poses[:, :3, :3].copy(),
        'rest_R': o['rest_bone_poses'][0].numpy()[:, :3, :3].astype(np.float64),
        # REST bone positions come back in anny's untranslated frame while the posed
        # ones are pre-translated to the root. They are kept anyway and used only for
        # DIRECTIONS, where the constant offset cancels — see anatomical_frame().
        'rest_heads': o['rest_bone_heads'][0].numpy().astype(np.float64),
        'rest_tails': o['rest_bone_tails'][0].numpy().astype(np.float64),
        'v': o['vertices'][0].numpy().astype(np.float64),
        'pose_aa': aa,
    }


def rig_numerical_floor(phenotype, local_changes=None):
    """MEASURED: how close to zero this rig can express "did not move".

    Every gate in this file that asserts an exact zero has to say what zero costs to
    measure, the same way geom/form/curvature states the cage's relief null before it
    claims a landmark. Three numbers, all measured, none tunable:
      reproducibility_deg   the largest apparent rotation between two INDEPENDENT
                            evaluations of the same rest pose. This is pure numerical
                            reproducibility and must be ~0 or the rig is not deterministic.
      orthonormality        max |R R^T - I| over all 163 bone poses at rest.
      angle_floor_deg       the largest apparent rotation the orthonormality defect alone
                            can manufacture, i.e. what an unprojected trace formula would
                            have reported for a bone that did not move.
    """
    a = rig_state(phenotype, local_changes, None)
    b = rig_state(phenotype, local_changes, None)
    n = len(a['names'])
    repro = max(rot_angle_deg(a['R'][i] @ b['R'][i].T) for i in range(n))
    orth = max(float(np.abs(a['R'][i] @ a['R'][i].T - np.eye(3)).max()) for i in range(n))
    raw = 0.0
    for i in range(n):
        M = a['R'][i] @ b['R'][i].T
        tr = float(np.clip((np.trace(M) - 1.0) * 0.5, -1.0, 1.0))
        raw = max(raw, float(np.degrees(np.arccos(tr))))
    return {
        'reproducibility_deg': repro,
        'orthonormality_max_abs': orth,
        'unprojected_angle_floor_deg': raw,
        'note': 'gates in this file project to the nearest rotation before measuring '
        'an angle, so the working floor is reproducibility_deg, not '
        'unprojected_angle_floor_deg.',
    }


def local_axis(state, bone, world_axis):
    """A world-space direction expressed in a bone's own REST frame, which is where anny
    wants a delta rotation. Uses the rest orientation, not the posed one, because that is
    the frame the delta is defined in."""
    return state['rest_R'][bone_index(bone)].T @ unit(world_axis)


# The long axis of ANY bone, expressed in that bone's own rest frame. anny's rest poses
# are built by anny.utils.kinematics.get_bone_poses, which aligns +Y with head->tail and
# then applies the bone roll — so this is exactly (0,1,0) for all 163 bones and is not an
# approximation. Every decomposition of a joint delta in this file is taken about it.
_LONG = np.array([0.0, 1.0, 0.0])


def _joint_ref_axes(state, bone, ref_a, ref_b):
    """Two world reference directions carried into a bone's rest frame and orthogonalised
    against its long axis, so a delta of identity decomposes to exactly zero."""
    Rr = state['rest_R'][bone_index(bone)]
    a = Rr.T @ unit(ref_a)
    b = Rr.T @ unit(ref_b)
    ex = a - (a @ _LONG) * _LONG
    if np.linalg.norm(ex) < 1e-9:  # ref_a lies along the bone
        ex = b - (b @ _LONG) * _LONG
    ex = unit(ex)
    ey = b - (b @ _LONG) * _LONG - (b @ ex) * ex
    if np.linalg.norm(ey) < 1e-9:
        ey = np.cross(_LONG, ex)
    return ex, unit(ey)


def joint_delta(state, bone):
    """The rotation of `bone` relative to its parent, expressed in `bone`'s rest frame.

    Recovered from world bone poses, which makes it independent of how the pose was
    authored — it reads a retargeted pose, a fitted pose and a hand-driven pose the same
    way. Identity at rest by construction.

    Derivation, so the algebra is checkable: anny composes pose_c = transform_p @ rest_c @
    delta_c with transform_p = pose_p @ rest_p^-1, so
        R(delta_c) = R(rest_c)^T R(rest_p) R(pose_p)^T R(pose_c).
    """
    i = bone_index(bone)
    p = _RIG['parents'][i]
    Rr, Rp = state['rest_R'], state['R']
    if p < 0:
        return Rr[i].T @ Rp[i]
    return Rr[i].T @ Rr[p] @ Rp[p].T @ Rp[i]


# ---------------------------------------------------------------------------------
# anatomical frame, measured from the rig rather than assumed
# ---------------------------------------------------------------------------------
def anatomical_frame(state):
    """(superior, anterior, subject_left) unit vectors, derived from rig geometry only.

    superior      the spine chain, pelvis -> neck base.
    subject_left  eye.L minus eye.R. The rig names its own sides; nothing is inferred
                  from a coordinate sign.
    anterior      completes a right-handed frame from those two, then checked against the
                  eyes' offset from the head bone axis so the sign is measured, not
                  assumed. The check value ships in the record.

    THE FRAME IS READ OFF THE REST POSE, ALWAYS, AND THAT IS NOT A DETAIL. Reading it off
    the POSED bones is what this did first and it produced a sign inversion that only
    appeared at large angles: a neck driven to 120 degrees of extension carries the eyes
    round with it, the measured 'anterior' follows them, and the same rotation then reads
    as 120 degrees of FLEXION. MEASURED before the fix: a +15 deg drive at the head bone
    reported -15 while a +30 deg drive at all four cervical joints reported +30. The
    reference frame belongs to the BODY, not to the pose; joint_delta already expresses
    every rotation in a rest frame, so the directions it is decomposed against must be
    rest directions too.
    """
    h = state['rest_heads']
    sup = unit(
        h[bone_index('neck01')]
        - h[bone_index('pelvis.L')]
        - (h[bone_index('pelvis.R')] - h[bone_index('pelvis.L')]) * 0.5
    )
    left = h[bone_index('eye.L')] - h[bone_index('eye.R')]
    left = unit(left - (left @ sup) * sup)
    ant = np.cross(sup, left)
    eye_mid = 0.5 * (h[bone_index('eye.L')] + h[bone_index('eye.R')])
    off = eye_mid - h[bone_index('head')]
    check = float(off @ ant)
    if check < 0:
        ant, check = -ant, -check
    return {
        'superior': sup,
        'anterior': unit(ant),
        'subject_left': left,
        'eye_forward_offset_m': check,
        'read_from': 'rest pose',
        'note': 'measured from the rig AT REST; the eyes lie %.4f m anterior of the '
        'head bone origin, which fixes the anterior sign' % check,
    }
