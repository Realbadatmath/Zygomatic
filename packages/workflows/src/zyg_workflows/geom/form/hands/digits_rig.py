# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The digit-chain pack: its rollback flag, the foot roster, the two radiographic
surveys, and rig access for the pack.

Moved verbatim out of the old single-file hands.py (lines 2070-2443).
"""

import json
import math
import os
import numpy as np

from zyg_workflows.geom.form.hands.rig import (
    DIGIT_BONES,
    _model,
)


# =================================================================================
# THE DIGIT-CHAIN PACK — t5_digit_chains, t5_phalanx_ratio, and the child-hand
# directions. Everything below this line is about the SKELETON, not the skin.
#
# WHY IT LIVES IN A DIFFERENT SPACE FROM EVERYTHING ABOVE, AND THIS IS THE FIRST THING
# TO UNDERSTAND ABOUT THIS SECTION. anny delivers its mesh POSED. Measured on the
# neutral: out['vertices'] and out['rest_vertices'] differ by up to 64.6 mm, and
# out['bone_poses'] is not out['rest_bone_poses']. So a cage vertex and a
# `rest_bone_head` are NOT in the same frame — an MCP ring centroid sits 3.2-8.3 mm from
# the POSED rig joint (which is the number resolve_hand's mcp_ring_note quotes) and
# 89-92 mm from the REST one. Reading a rest bone head against a delivered vertex would
# be off by half a hand and would look like a catastrophic anatomy defect that is purely
# a frame error.
#
# The pack sidesteps that entirely by measuring LENGTHS, |tail - head|, which are
# invariant under the rigid per-bone pose: measured on the neutral, the largest change
# in any finger or toe bone length between rest and delivered pose is 1.7e-5 mm. The
# lengths are nevertheless taken through the POSED transform anyway, because a
# `bone_scales` recipe is delivered as pose_parameters carrying a scale in the 3x3 block
# (mesh_skeletons._scale44), so a rest-space read would silently ignore an operator's
# --bone-scale and report the unscaled skeleton.
#
# WHAT IS GATED AND WHAT IS NOT.
#   * t5_digit_chains is integer counts and exact chain continuity on the rig roster,
#     parsed by regex from the 163 bone names rather than read off DIGIT_BONES, because
#     a hand-typed table cannot verify itself.
#   * t5_phalanx_ratio is gated against TWO INDEPENDENT RADIOGRAPHIC SURVEYS, never
#     against our own cage, and never against the book: the book's number is CANON and a
#     MEASURED source exists for exactly this quantity, so the book is carried as a
#     second opinion with severity capped at 'report'.
#   * The foot has no gated ratio. No normative per-toe phalanx length table was found;
#     see DIGIT_UNRESOLVED. The numbers are measured and reported.
# =================================================================================


def _env_flag(name, default=True):
    v = os.environ.get(name)
    if v is None:
        return bool(default)
    return str(v).strip().lower() not in ('0', 'false', 'no', 'off', '')


# ROLLBACK. ZYG_HAND_DIGIT_GATES=0 removes the whole pack from check_hand_mesh and
# check_digits without a code edit; the five Monte-Carlo form predicates are untouched
# either way. Default ON.
DIGIT_GATES_FLAG = 'ZYG_HAND_DIGIT_GATES'

# ---------------------------------------------------------------------------------
# The foot, as anny's rig actually names it.
#
# ENUMERATED FROM THE RIG, and the numbering trap here is the MIRROR IMAGE of the hand's.
# In the hand, `finger1-1` is the thumb METACARPAL and `metacarpal1..4` belong to the
# index..little fingers. In the foot there is no metatarsal bone at all — the shank runs
# lowerleg02 -> foot -> toeN-1, one bone for the entire tarsus and metatarsus — so
# `toe1-1` could a priori be either the hallux metatarsal (matching the hand's
# finger1-1) or the hallux proximal phalanx. Which it is decides whether the hallux has
# 2 phalanges (correct) or 1 (a defect), so it is settled by measurement, not by analogy:
# see metapodial_test(). Measured on the neutral, toe1-1's head sits 12.54 mm off the
# line through the toe2-5 proximal heads — 0.449 of its own length — while foot's tail
# sits 81.63 mm off the same line. The hand's finger1-1 head sits 66.86 mm off the
# equivalent finger line, 2.099 of its own length, and 0.19 mm from metacarpal1's head.
# So finger1-1 starts where the metacarpals start and toe1-1 starts at the MTP line:
# finger1-1 IS a metapodial, toe1-1 IS a phalanx.
# ---------------------------------------------------------------------------------
TOE_BONES = {
    'hallux': ('toe1-1', 'toe1-2', None),
    'toe2': ('toe2-1', 'toe2-2', 'toe2-3'),
    'toe3': ('toe3-1', 'toe3-2', 'toe3-3'),
    'toe4': ('toe4-1', 'toe4-2', 'toe4-3'),
    'toe5': ('toe5-1', 'toe5-2', 'toe5-3'),
}
TOES = ('hallux', 'toe2', 'toe3', 'toe4', 'toe5')
LESSER_TOES = ('toe2', 'toe3', 'toe4', 'toe5')
FOOT_BONE = 'foot'
SHANK_BONE = 'lowerleg02'

# The counts AFS p.179 / p.188 asserts, restated as what a rig can be asked. Each entry
# is (what, expected integer, whether the anny rig can answer it at all).
SKELETAL_COUNTS = (
    ('digits_per_hand', 5, True),
    ('phalanges_thumb', 2, True),
    ('phalanges_per_finger', 3, True),
    ('phalanges_per_hand', 14, True),
    ('metacarpals_per_hand', 5, True),
    ('carpals_per_hand', 8, False),
    ('digits_per_foot', 5, True),
    ('phalanges_hallux', 2, True),
    ('phalanges_per_lesser_toe', 3, True),
    ('phalanges_per_foot', 14, True),
    ('metatarsals_per_foot', 5, False),
    ('cuneiforms_per_foot', 3, False),
)


# ---------------------------------------------------------------------------------
# EXTERNAL REFERENCE — two independent radiographic surveys of the human hand.
#
# Neither is ours, neither was chosen after looking at our numbers, and they were
# located and transcribed before any anny ratio was compared against them.
# ---------------------------------------------------------------------------------
# Buryanov, A. & Kotiuk, V. (2010) "Proportions of Hand Segments", Int. J. Morphol.
# 28(3):755-758, Table I. n=66 adult patients, 19-78 y, Ukrainian (European) hospital
# sample, anteroposterior radiographs at 100% scale verified against a radiopaque ruler
# on every fifth patient. Values are mm, arithmetic mean +/- SD, for the RIGHT hand
# (the paper states left-right difference was within 0.5%).
#   tip        = soft tissue of the finger tip above the apex of the distal phalanx
#   distal/middle/proximal = interarticular bone lengths of the phalanges
#   metapodial = metacarpal
BK2010 = {
    'thumb': {
        'tip': (5.67, 0.61),
        'distal': (21.67, 1.60),
        'middle': None,
        'proximal': (31.57, 3.13),
        'metapodial': (46.22, 3.94),
    },
    'index': {
        'tip': (3.84, 0.59),
        'distal': (15.82, 2.26),
        'middle': (22.38, 2.51),
        'proximal': (39.78, 4.94),
        'metapodial': (68.12, 6.27),
    },
    'middle': {
        'tip': (3.95, 0.61),
        'distal': (17.40, 1.85),
        'middle': (26.33, 3.00),
        'proximal': (44.63, 3.81),
        'metapodial': (64.60, 5.38),
    },
    'ring': {
        'tip': (3.95, 0.60),
        'distal': (17.30, 2.22),
        'middle': (25.65, 3.29),
        'proximal': (41.37, 3.87),
        'metapodial': (58.00, 5.06),
    },
    'little': {
        'tip': (3.73, 0.62),
        'distal': (15.96, 2.45),
        'middle': (18.11, 2.54),
        'proximal': (32.74, 2.77),
        'metapodial': (53.69, 4.36),
    },
}
BK2010_SOURCE = (
    'Buryanov & Kotiuk 2010, Int. J. Morphol. 28(3):755-758, Table I '
    '(n=66 adults 19-78 y, AP radiographs, interarticular bone lengths '
    'plus finger-tip soft tissue), MEASURED'
)

# Hamilton, R. & Dunsmuir, R.A. (2002) "Radiographic assessment of the relative lengths
# of the bones of the fingers of the human hand", J. Hand Surg. 27B(6):546-548. n=197.
# THIS IS THE CONVENTION-EXACT SOURCE for what the rig reports: the authors determined
# the centres of rotation of the finger joints by dissecting cadaveric hands and then
# measured the distances between those joint centres on radiographs, which is precisely
# |bone_tail - bone_head| on a rig.
#
# TUPLE ORDER IS (proximal, middle, distal-to-tip) — MCP-PIP : PIP-DIP : DIP-tip. This
# comment used to state the REVERSE order ("distal-to-tip : PIP-DIP : MCP-PIP") while
# HD2002_SOURCE two lines below stated it correctly and _ratio_band unpacked it
# correctly, so the file contradicted itself on a MEASURED evidence record. CORRECTED
# 2026-08-08, after the wrong order was read off this comment and used to compute a
# nonsense mid/prox of 1.30 (it is 1.3/2.3 = 0.5652). Nothing indexing this table
# changed; only the comment was wrong. The physical check that settles it in one line:
# the proximal phalanx is the LONGEST of the three, so the 2.3 is the proximal.
HD2002 = {'index': (2.3, 1.3, 1.0), 'middle': (2.3, 1.3, 1.0), 'ring': (2.3, 1.3, 1.0), 'little': (2.0, 1.0, 1.0)}
HD2002_SOURCE = (
    'Hamilton & Dunsmuir 2002, J. Hand Surg. 27B(6):546-548 (n=197, '
    'distances between joint centres of rotation established by cadaveric '
    'dissection): index/middle/ring 2.3 : 1.3 : 1, little 2 : 1 : 1, '
    'proximal : middle : distal-to-tip. MEASURED, and the only source in '
    "the pack measured in the rig's own convention."
)

# AFS p.178. The book states the same rule twice: as a 75-percent rule (each segment is
# three quarters of the one before) and as an integer 9-and-a-quarter-parts rule
# (4 : 3 : 2.25). THE TWO FORMS ARE ALGEBRAICALLY IDENTICAL — 3/4 = 0.75 and
# 2.25/3 = 0.75 — so they are ONE claim stated twice, not two pieces of evidence. What
# the repetition does buy is the exclusion of a transcription error, which is why it is
# worth carrying at all. CANON, and there is a MEASURED source for this exact quantity,
# so it may not block.
AFS_P178_PARTS = (4.0, 3.0, 2.25)
AFS_P178_SOURCE = (
    'AFS p.178, stated twice — as "each segment is 75% of the previous" '
    'and as an integer 4 : 3 : 2.25 of 9.25 parts. The two forms are the '
    'same number (3/4 = 2.25/3 = 0.75); the repetition excludes a '
    'transcription error, it does not corroborate the value. CANON.'
)

# The one ordering that survives every convention and every source, so it is gated as a
# sign test with nothing to tune: within a finger the proximal phalanx is longer than
# the middle one. True in BK2010 for all four fingers (ratios 0.553-0.620) and in
# HD2002 (1.3 < 2.3, 1 < 2).
#
# THE COMPLEMENTARY ORDERING IS **NOT** GATED, and the reason is measured. The rig's
# distal segment runs from the DIP joint centre to the FLESHY finger tip, not to the end
# of the bone — measured on the neutral, the nearest cage vertex to the distal bone tail
# is 1.07-3.01 mm away and the skin extends only -1.13 to +1.78 mm past the tail along
# the bone axis, i.e. the tail sits on the skin. Under that convention "the middle
# phalanx is longer than the distal segment" is FALSE in real hands: BK2010's little
# finger gives (15.96 + 3.73) / 18.11 = 1.087 and HD2002's little finger gives exactly
# 1.0. Gating it would fail a correct little finger.
ORDERING_GATED = ('proximal_longer_than_middle',)


def _ratio_band(digit, kind):
    """(centre, half_width, detail) for one finger ratio, from the two surveys only.

    CENTRE is the mean of the two independent surveys' values for that finger. HALF
    WIDTH is 3 x an SD propagated from BK2010's published length SDs TREATING THE TWO
    LENGTHS AS INDEPENDENT, which is deliberately and knowably too wide: within one
    subject a long proximal phalanx goes with a long middle phalanx, and that positive
    correlation cancels in a ratio, so the true SD of the ratio is smaller than this. A
    band that is too wide is the safe error for a gate — it can only fail to catch, it
    cannot false-fail — and the amount of slack is stated rather than hidden.

    NOTHING HERE IS FITTED TO ANY ANNY MESH. If our rig falls outside, that is the
    finding.
    """
    b = BK2010[digit]
    if kind == 'mid_over_prox':
        num, den = b['middle'], b['proximal']
        if num is None:
            return None
        bk = num[0] / den[0]
        rel = math.sqrt((num[1] / num[0]) ** 2 + (den[1] / den[0]) ** 2)
        p, m, _d = HD2002[digit]
        hd = m / p
    elif kind == 'dist_over_mid':
        if b['middle'] is None:
            return None
        # DIP joint centre -> fleshy tip, so the finger-tip soft tissue is part of the
        # numerator. This is what the rig measures; see ORDERING_GATED.
        nv = b['distal'][0] + b['tip'][0]
        ns = math.sqrt(b['distal'][1] ** 2 + b['tip'][1] ** 2)
        den = b['middle']
        bk = nv / den[0]
        rel = math.sqrt((ns / nv) ** 2 + (den[1] / den[0]) ** 2)
        p, m, d = HD2002[digit]
        hd = d / m
    else:
        raise ValueError('unknown ratio kind %r' % (kind,))
    centre = 0.5 * (bk + hd)
    sd = bk * rel
    return {
        'centre': centre,
        'half_width': 3.0 * sd,
        'sd_propagated': sd,
        'buryanov_kotiuk_2010': bk,
        'hamilton_dunsmuir_2002': hd,
        'source_spread': abs(bk - hd),
        'band': [centre - 3.0 * sd, centre + 3.0 * sd],
        'canon_afs_p178': (
            AFS_P178_PARTS[1] / AFS_P178_PARTS[0] if kind == 'mid_over_prox' else AFS_P178_PARTS[2] / AFS_P178_PARTS[1]
        ),
    }


# ---------------------------------------------------------------------------------
# Rig access for the pack. rig() above deliberately resolves only the hand bones and
# raises on anything it does not know, so the foot is served by its own cache rather
# than by widening that function's contract.
# ---------------------------------------------------------------------------------
_BONEW = {}
_SKEL = {}


def _bone_weight(name):
    """Total rig weight of one named bone over the cage. Topology-fixed, so cached."""
    if name in _BONEW:
        return _BONEW[name]
    MS = _model()
    m = MS._model()
    idx = {str(n): i for i, n in enumerate(MS._bone_names(m))}
    if name not in idx:
        raise RuntimeError('anny rig has no bone %r' % (name,))
    vbi = m.vertex_bone_indices.detach().cpu().numpy()
    vbw = m.vertex_bone_weights.detach().cpu().numpy()
    w = np.zeros(int(vbi.shape[0]), np.float64)
    j = idx[name]
    for k in range(vbi.shape[1]):
        w += np.where(vbi[:, k] == j, vbw[:, k], 0.0)
    _BONEW[name] = w
    return w


def skeleton(phenotype, local_changes=None, bone_scales=None, apply_hand_correction=True, params=None):
    """Bone heads and tails for one parameter recipe, in BOTH frames.

    Returns {'names', 'index', 'rest_head', 'rest_tail', 'head', 'tail',
             'pose_is_identity', 'max_length_change_mm'} where head/tail are in the
    DELIVERED (posed) frame — the frame the shipped cage lives in — and rest_* are
    anny's rest skeleton. `max_length_change_mm` is the largest difference between a
    hand/foot bone's rest length and its posed length, which is 0 unless a bone_scales
    recipe is in play, and is reported so that a caller can never be surprised by one.

    apply_hand_correction — the phalanx correction (geom.anthro.hand_correction) is
    composed into bone_scales by DEFAULT, because this function and
    mesh_skeletons._build_mesh are two doors onto the same body and a correction applied
    at one of them only would give the gate a different skeleton from the delivered cage.
    That is the split-brain failure this pipeline has already been bitten by twice. The
    solver passes False, because it is what computes the correction and would otherwise
    be chasing its own tail.
    """
    import torch

    MS = _model()
    m = MS._model()
    hc_rec = None
    if apply_hand_correction:
        from zyg_workflows.geom.anthro import hand_correction as HC

        bone_scales, hc_rec = HC.effective_scales(phenotype, local_changes, bone_scales, params)
    key = json.dumps(
        [dict(phenotype), dict(local_changes or {}), dict(bone_scales or {}), bool(apply_hand_correction)],
        sort_keys=True,
    )
    if key in _SKEL:
        return _SKEL[key]
    kw = {'phenotype_kwargs': dict(phenotype)}
    if local_changes:
        kw['local_changes_kwargs'] = dict(local_changes)
    if bone_scales:
        pose, _applied = MS._scale44(m, bone_scales)
        kw['pose_parameters'] = pose
    with torch.no_grad():
        out = m(**kw)
    names = [str(n) for n in MS._bone_names(m)]
    idx = {n: i for i, n in enumerate(names)}
    RH = out['rest_bone_heads'][0].numpy().astype(np.float64)
    RT = out['rest_bone_tails'][0].numpy().astype(np.float64)
    BP = out['bone_poses'][0].numpy().astype(np.float64)
    RP = out['rest_bone_poses'][0].numpy().astype(np.float64)
    n = len(names)
    H = np.zeros_like(RH)
    T = np.zeros_like(RT)
    for j in range(n):
        M = BP[j] @ np.linalg.inv(RP[j])
        H[j] = M[:3, :3] @ RH[j] + M[:3, 3]
        T[j] = M[:3, :3] @ RT[j] + M[:3, 3]
    watch = []
    for tbl in (DIGIT_BONES, TOE_BONES):
        for bones in tbl.values():
            watch += [b for b in bones if b]
    dmax = 0.0
    for b in sorted(set(watch)):
        for s in ('L', 'R'):
            j = idx.get('%s.%s' % (b, s))
            if j is None:
                continue
            dmax = max(dmax, abs(float(np.linalg.norm(T[j] - H[j])) - float(np.linalg.norm(RT[j] - RH[j]))))
    doc = {
        'names': names,
        'index': idx,
        'rest_head': RH,
        'rest_tail': RT,
        'head': H,
        'tail': T,
        'pose_is_identity': bool(np.allclose(BP, RP)),
        'max_length_change_mm': dmax * 1000.0,
        # what actually shaped this skeleton, so a reader never has to infer it from
        # the numbers. None means the correction was not applied on this call.
        'hand_correction': hc_rec,
    }
    _SKEL[key] = doc
    return doc


def _blen(sk, bone, side):
    j = sk['index']['%s.%s' % (bone, side)]
    return float(np.linalg.norm(sk['tail'][j] - sk['head'][j]))
