# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Vocabulary, the anny hand rig roster, the house constants, the geometry helpers
and the hand frame.

Moved verbatim out of the old single-file hands.py (lines 155-558).
"""

import math
import os
import numpy as np


SCHEMA = 'geom.form.hands/1'

# ---------------------------------------------------------------------------------
# Vocabulary. Deliberately identical between the mesh path and the image path so that a
# mesh verdict and a render verdict can be put side by side without a translation table.
# ---------------------------------------------------------------------------------
PREDICATES = ('knuckle_arch', 'middle_finger_ratio', 'webbing', 'thumb_opposition', 'dorsal_over_palmar')

# The digit-chain pack (t5_digit_chains / t5_phalanx_ratio, plus the child-hand
# directions). DELIBERATELY A SECOND TUPLE and not appended to PREDICATES, because
# PREDICATES is the vocabulary the mesh path and the IMAGE path share, and none of these
# three can be read off MediaPipe's 21 points: a phalanx ratio needs the joint centres of
# a skeleton, not a landmark regressor's guess at them. Growing PREDICATES would also
# break every consumer that iterates it expecting an image record to exist for each name.
DIGIT_PREDICATES = ('digit_chains', 'phalanx_ratio', 'child_hand')

# statuses, matching geom.anthro.gates so a form registry can consume these unchanged
PASS = 'pass'  # noqa: S105  gate status constant, not a secret
WARN = 'warn'
FAIL = 'fail'
REPORT = 'report'
UNMEASURABLE = 'unmeasurable'
NOT_IMPLEMENTABLE = 'not_implementable'
# The quantity computed cleanly but the answer has no consistent sign across the sites
# it was measured at — a 2-up-2-down split over four fingers is not a direction, it is
# the absence of one, and averaging it into a verdict would manufacture confidence.
# Same word geom.anthro.landmarks uses for a landmark it declines to place.
UNRESOLVED = 'unresolved'
ERROR = 'error'

# A published SURVEY of real people: a named series, with a sample size, measured on
# bodies that are not ours. Nothing else is MEASURED. In particular a number printed in a
# book is NOT MEASURED however many times the book is right — see CANON below — and a
# census of our own cage is NOT MEASURED either, it is HOUSE. `_rec` enforces this: a
# record tagged MEASURED whose source names no sample size raises rather than shipping.
MEASURED = 'MEASURED'
HOUSE = 'HOUSE'
# Artist canon: a number printed in an anatomy-for-artists text, which is a drawing
# convention distilled from observation, not a survey. RANKED BELOW MEASURED.
#
# THE CAP IS CONDITIONAL, and the condition is the whole point: a CANON threshold may
# never block-fail a quantity FOR WHICH A MEASURED SOURCE EXISTS — there it is carried on
# the record as a second opinion and capped at 'report' (`canon_severity_cap`, which
# phalanx_ratio sets over AFS p.178 because two radiographic series cover that exact
# ratio). Where no survey covers the quantity at all there is no source for the book to be
# overruled BY, and the cap would not be conservatism, it would be a quantity nobody
# gates. Those keep the severity their own evidence earns: child_hand is CANON at 'warn'
# (three direction tests, no survey of child knuckle relief exists) and digit_chains is
# CANON at 'block' (integer bone counts, no survey counts phalanges, and its subject is
# OUR BONE ROSTER rather than a proportion of a person).
CANON = 'CANON'

DIGITS = ('thumb', 'index', 'middle', 'ring', 'little')
FINGERS = ('index', 'middle', 'ring', 'little')
WEBS = (('index', 'middle'), ('middle', 'ring'), ('ring', 'little'))

# PACKAGE SPLIT 2026-10-06: this section was geom/form/hands.py and is now
# geom/form/hands/rig.py — one directory deeper — so the dirname chain takes one more
# step to resolve to the same directory, and FORM_REFERENCE_DIR / SAMPLE_FILE come out
# identical to what the single file computed.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
FORM_REFERENCE_DIR = os.path.join(_ROOT, 'data', 'assets', 'form_reference')
SAMPLE_FILE = os.path.join(FORM_REFERENCE_DIR, 'hands_morph_sample_v1.json')

# The anny cage this file was written against. A different vertex count means a different
# topology, and every rig-derived index set below would be silently wrong.
CAGE_VERTS = 13718

# ---------------------------------------------------------------------------------
# The hand skeleton, as anny's rig actually names it.
#
# ENUMERATED, NOT GUESSED. The rig carries 163 bones; the hand is 20 per side and the
# naming is MakeHuman's, which does not match the anatomy word-for-word: `finger1-1` is
# the thumb METACARPAL (the thumb therefore has no `metacarpal*` bone of its own), and
# `metacarpal1..4` are the metacarpals of the index, middle, ring and little fingers, so
# `metacarpalN` feeds `finger(N+1)-1`. That off-by-one is verified at import by
# _verify_rig(), which checks each metacarpal's tail against the next digit's proximal
# head rather than trusting the numbering.
#
# Per digit: (base bone whose TAIL is the MCP, proximal phalanx, middle phalanx, distal
# phalanx). The thumb has two phalanges, not three, so its fourth slot is None and its
# `finger1-3` sits in the middle slot; the code always addresses the last non-None entry
# as "distal".
# ---------------------------------------------------------------------------------
DIGIT_BONES = {
    'thumb': ('finger1-1', 'finger1-2', 'finger1-3', None),
    'index': ('metacarpal1', 'finger2-1', 'finger2-2', 'finger2-3'),
    'middle': ('metacarpal2', 'finger3-1', 'finger3-2', 'finger3-3'),
    'ring': ('metacarpal3', 'finger4-1', 'finger4-2', 'finger4-3'),
    'little': ('metacarpal4', 'finger5-1', 'finger5-2', 'finger5-3'),
}
FOREARM_BONE = 'lowerarm02'
WRIST_BONE = 'wrist'

# HOUSE. A vertex counts as belonging to a joint ring when the rig gives it at least this
# much weight on BOTH bones. 0.02 was chosen because it is the lowest threshold at which
# every one of the ten rings (5 digits x 2 sides) has more than 50 vertices, which is what
# makes the centroid stable; the value is reported in every frame record.
RING_W_MIN = 0.02
# HOUSE. A vertex "belongs to" a bone for segment masks at this weight. 0.5 is the
# majority rule and puts every cage vertex in at most one segment.
SEGMENT_W_MIN = 0.5
# HOUSE. Faces admitted to the inter-digital plane cut. Lower than SEGMENT_W_MIN because
# the web itself is exactly the region the rig splits between two digits, so a majority
# rule would delete the surface the cut is looking for.
WEB_FACE_W_MIN = 0.30
# HOUSE. Half-width of the mid-sagittal slab a finger's dorsal/palmar profile is taken in,
# as a fraction of the finger's own lateral extent.
RIDGE_SLAB_FRAC = 0.30
RIDGE_BINS = 14
# HOUSE. Below this ratio between the two minor principal axes of a digit's distal block,
# the cross-section is too round for its dorso-palmar axis to be identified at all, and
# thumb_opposition returns unmeasurable instead of a number. Measured range on the four
# issued characters: 1.13-1.39.
DP_AXIS_MIN_ANISOTROPY = 1.05

_RIG = {}
_RING = {}


def _side(side):
    s = str(side).strip().lower()
    if s in ('l', 'left'):
        return 'L'
    if s in ('r', 'right'):
        return 'R'
    raise ValueError('side must be left/right (or L/R); got %r' % (side,))


def _model():
    from zyg_workflows.geom import mesh_skeletons as MS

    return MS


def rig():
    """{'names', 'index', 'weights': {bone: (V,) float64}} for the hand bones only.

    The blend weights are a property of the TOPOLOGY, not of any one body: anny stores
    them as a fixed (13718, 9) index/weight table, so they are resolved once per process
    and then applied to any cage of the right size. That is what lets check_hand_mesh take
    (v, faces) alone and still speak about named bones.
    """
    if _RIG:
        return _RIG
    MS = _model()
    m = MS._model()
    names = [str(n) for n in MS._bone_names(m)]
    idx = {n: i for i, n in enumerate(names)}
    vbi = m.vertex_bone_indices.detach().cpu().numpy()
    vbw = m.vertex_bone_weights.detach().cpu().numpy()
    nv = int(vbi.shape[0])
    if nv != CAGE_VERTS:
        raise RuntimeError(
            'anny cage has %d vertices, this module was written against %d. Every '
            'rig-derived index set here would be silently wrong on a different topology.' % (nv, CAGE_VERTS)
        )
    wanted = set()
    for bones in DIGIT_BONES.values():
        wanted.update(b for b in bones if b)
    wanted.update((WRIST_BONE, FOREARM_BONE))
    weights = {}
    row = np.arange(nv)
    for b in sorted(wanted):
        for s in ('L', 'R'):
            nm = '%s.%s' % (b, s)
            if nm not in idx:
                raise RuntimeError(
                    'anny rig has no bone %r. The roster this module was written against '
                    'is the 163-bone MakeHuman rig; it now reads: %s' % (nm, ', '.join(names))
                )
            w = np.zeros(nv, np.float64)
            j = idx[nm]
            for k in range(vbi.shape[1]):
                np.add.at(w, row, np.where(vbi[:, k] == j, vbw[:, k], 0.0))
            weights[nm] = w
    _RIG.update({'names': names, 'index': idx, 'weights': weights, 'n_bones': len(names)})
    return _RIG


def verify_rig():
    """Prove the metacarpal-to-digit mapping from the rig itself, not from the numbering.

    Returns a list of {'digit', 'base', 'proximal', 'gap_mm'} records. A base bone whose
    TAIL is not the proximal phalanx's HEAD is not the bone that carries that digit's MCP,
    and the whole file would be measuring the wrong joint.
    """
    import torch

    MS = _model()
    m = MS._model()
    idx = rig()['index']
    with torch.no_grad():
        out = m(
            phenotype_kwargs={
                'gender': 0.0,
                'age': 0.5,
                'muscle': 0.5,
                'weight': 0.5,
                'height': 0.5,
                'proportions': 0.5,
            }
        )
    H = out['rest_bone_heads'][0].numpy().astype(np.float64)
    T = out['rest_bone_tails'][0].numpy().astype(np.float64)
    rows = []
    for d, bones in DIGIT_BONES.items():
        base, prox = bones[0], bones[1]
        for s in ('L', 'R'):
            gap = float(np.linalg.norm(T[idx['%s.%s' % (base, s)]] - H[idx['%s.%s' % (prox, s)]]))
            rows.append({'digit': d, 'side': s, 'base': base, 'proximal': prox, 'gap_mm': round(gap * 1000.0, 6)})
    bad = [r for r in rows if r['gap_mm'] > 1e-6]
    if bad:
        raise RuntimeError(
            'the rig does not confirm the metacarpal-to-digit mapping this module '
            'assumes: %r. MakeHuman numbers metacarpal1..4 for the index..little '
            'fingers, so metacarpalN must feed finger(N+1)-1.' % bad
        )
    return rows


def _ring_idx(side, a, b):
    """Topology-fixed vertex ring the rig skins across the a->b joint, with blend weights.

    The weight is min(w_a, w_b): a vertex the rig splits evenly between the two bones sits
    ON the joint, a vertex the rig gives to one of them sits on a shaft. Cached, because
    the answer depends only on the cage topology.
    """
    key = (side, a, b)
    if key in _RING:
        return _RING[key]
    w = rig()['weights']
    wa, wb = w['%s.%s' % (a, side)], w['%s.%s' % (b, side)]
    sel = np.nonzero((wa > RING_W_MIN) & (wb > RING_W_MIN))[0]
    if len(sel) < 8:
        raise RuntimeError(
            'the %s->%s.%s joint ring has only %d cage vertices at weight>%g; a centroid '
            'over that few is not a stable anchor and this module will not pretend '
            'otherwise' % (a, b, side, len(sel), RING_W_MIN)
        )
    _RING[key] = (sel, np.minimum(wa[sel], wb[sel]))
    return _RING[key]


def _segment_idx(side, bones):
    w = rig()['weights']
    tot = np.zeros(CAGE_VERTS)
    for b in bones:
        tot += w['%s.%s' % (b, side)]
    return np.nonzero(tot > SEGMENT_W_MIN)[0]


def _joint(v, side, a, b):
    sel, wt = _ring_idx(side, a, b)
    return np.average(v[sel], axis=0, weights=wt)


def _unit(x):
    n = float(np.linalg.norm(x))
    if n <= 0:
        raise ValueError('cannot normalise a zero-length vector')
    return np.asarray(x, np.float64) / n


def _line_residuals(P):
    """Perpendicular distance of each point from its own total-least-squares line."""
    P = np.asarray(P, np.float64)
    c = P.mean(0)
    X = P - c
    _, _, vt = np.linalg.svd(X, full_matrices=False)
    d = vt[0]
    return np.linalg.norm(X - np.outer(X @ d, d), axis=1)


def _line_angle(a, b):
    """Unsigned angle in degrees between two DIRECTIONS treated as lines (0..90)."""
    return float(np.degrees(np.arccos(min(1.0, abs(float(np.dot(_unit(a), _unit(b))))))))


def _vec_angle(a, b):
    """Signed-free angle in degrees between two vectors treated as arrows (0..180)."""
    return float(np.degrees(np.arccos(max(-1.0, min(1.0, float(np.dot(_unit(a), _unit(b))))))))


def _principal_axes(P):
    P = np.asarray(P, np.float64)
    Y = P - P.mean(0)
    _, s, vt = np.linalg.svd(Y, full_matrices=False)
    return vt, s / math.sqrt(max(len(P), 1))


def _triangulate(faces):
    """The DELIVERED triangulation. mesh_skeletons._export_glb ships the quads split
    [0,1,2] + [0,2,3]; any intersection computed on a different split is a result about a
    surface we do not ship."""
    faces = np.asarray(faces)
    if faces.shape[1] == 3:
        return faces
    return np.concatenate([faces[:, [0, 1, 2]], faces[:, [0, 2, 3]]])


def _plane_cut(v, tris, point, normal):
    """Exact plane-mesh intersection points: every edge of `tris` the plane crosses."""
    f = (v - point) @ normal
    E = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    E = np.unique(np.sort(E, axis=1), axis=0)
    fa, fb = f[E[:, 0]], f[E[:, 1]]
    cr = np.nonzero((fa > 0) != (fb > 0))[0]
    if not len(cr):
        return np.zeros((0, 3))
    t = fa[cr] / (fa[cr] - fb[cr])
    return v[E[cr, 0]] + t[:, None] * (v[E[cr, 1]] - v[E[cr, 0]])


# ---------------------------------------------------------------------------------
# Hand frame
# ---------------------------------------------------------------------------------
def resolve_hand(v, faces, side):
    """Anchors for one hand: joints, tips, the palm plane and its palmar sign.

    THE PALMAR SIGN IS MEASURED, NOT ASSUMED, and it is not taken from the thumb's
    orientation — which would make thumb_opposition circular. It is taken from the thumb's
    POSITION: Gray's Anatomy (1918) records the first metacarpal as lying in a different
    plane from the other four, anterior (palmar) to them. On this cage that is a 10x
    separation, measured on the male original: the thumb MCP sits 22.2 mm off the plane
    fitted through the wrist ring and the four finger MCPs while no finger MCP is more
    than 2.1 mm off it. The margin travels in the record as `palmar_sign_margin`, and if
    it ever collapses the caller can see that the sign is no longer safe.
    """
    from zyg_workflows.geom.anthro import landmarks as LMK

    S = _side(side)
    v = np.asarray(v, np.float64)
    if len(v) != CAGE_VERTS:
        raise ValueError('expected the %d-vertex anny cage, got %d vertices' % (CAGE_VERTS, len(v)))
    J = {}
    for d, bones in DIGIT_BONES.items():
        base, prox, mid, dist = bones
        J[(d, 'mcp')] = _joint(v, S, base, prox)
        J[(d, 'pip')] = _joint(v, S, prox, mid)
        if dist:
            J[(d, 'dip')] = _joint(v, S, mid, dist)
        last = dist or mid
        seg = _segment_idx(S, [last])
        anchor = J[(d, 'dip')] if dist else J[(d, 'pip')]
        J[(d, 'tip')] = v[seg[int(np.argmax(np.linalg.norm(v[seg] - anchor, axis=1)))]]
    J[('wrist', 'joint')] = _joint(v, S, FOREARM_BONE, WRIST_BONE)

    pts = np.array([J[('wrist', 'joint')]] + [J[(d, 'mcp')] for d in FINGERS])
    c0 = pts.mean(0)
    _, s, vt = np.linalg.svd(pts - c0, full_matrices=False)
    n = vt[2]
    t_off = float(np.dot(J[('thumb', 'mcp')] - c0, n))
    if t_off < 0:
        n, t_off = -n, -t_off  # +n now points PALMAR
    f_off = max(abs(float(np.dot(J[(d, 'mcp')] - c0, n))) for d in FINGERS)

    # Hand length uses geom.anthro's own landmarks so that this layer and the metric layer
    # cannot disagree about how long the hand is. measure.py flags this convention
    # survey_comparable=False (the ring centroid sits proximal to the stylion line where
    # survey hand length starts); the flag is carried here rather than re-litigated.
    lmk = LMK.resolve_landmarks(v, faces)
    lo = S.lower()
    wr = lmk.get('wrist_ring_%s' % lo) or {}
    dc = lmk.get('dactylion_%s' % lo) or {}
    if wr.get('point') is not None and dc.get('point') is not None:
        wr_pt = np.asarray(wr['point'], np.float64)
        dact = np.asarray(dc['point'], np.float64)
        hl = float(np.linalg.norm(dact - wr_pt))
        hl_src = (
            'geom.anthro.landmarks wrist_ring_%s -> dactylion_%s, the same chord '
            'measure.py calls hand_length (survey_comparable=False: the ring '
            'centroid sits proximal to the stylion line)' % (lo, lo)
        )
    else:
        wr_pt, dact = J[('wrist', 'joint')], J[('middle', 'tip')]
        hl = float(np.linalg.norm(dact - wr_pt))
        hl_src = (
            'FALLBACK: geom.anthro.landmarks did not resolve wrist_ring_%s or '
            'dactylion_%s, so hand length is the rig wrist joint to the middle '
            'fingertip and is NOT the measure.py convention' % (lo, lo)
        )
    return {
        'side': S,
        'joints': J,
        'palm_centre': c0,
        'palmar_normal': n,
        'palm_planarity_m': float(s[2] / math.sqrt(len(pts))),
        'palmar_sign_margin': {
            'thumb_mcp_offset_m': t_off,
            'max_finger_mcp_offset_m': f_off,
            'ratio': (t_off / f_off) if f_off > 0 else float('inf'),
        },
        'wrist_point': wr_pt,
        'dactylion': dact,
        'hand_length_m': hl,
        'hand_length_source': hl_src,
        'ring_weight_min': RING_W_MIN,
        'mcp_ring_note': (
            'an MCP here is the weighted centroid of the cage ring the rig skins across '
            'the metacarpal-to-phalanx joint, NOT the rig joint centre. Measured offset '
            'from the rig joint on the neutral male: thumb 1.5 mm, index 5.8 mm, middle '
            '6.5 mm, ring 5.5 mm, little 5.9 mm. The calibration measures every predicate '
            'through this same estimator, so the thresholds are in its units.'
        ),
    }
