# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Anatomical landmarks on the anny 13,718-vertex cage — and an honest record of which
ones are not there at all.

WHY THIS MODULE EXISTS
Every anthropometric ratio is a quotient of two landmark heights, so a landmark that is
5% off silently poisons every gate downstream. The trap is not arithmetic, it is
DEFINITION: "shoulder width" is biacromial or bideltoid or a circumference; "waist" is the
rib-iliac midpoint or the iliac crest or the narrowest coronal section, sites that differ
by up to 10cm in the same person; "leg length" is four different landmarks. So every
landmark here carries the landmark it claims to be, the anchor that produced it, whether
that anchor is ISO-defined / vendor-shipped / ours, and a confidence. Nothing is named
after a survey landmark unless it IS that landmark.

THE SECOND TRAP is guessing vertex numbers. Hard-coded indices are unfalsifiable and rot
the moment the cage changes. Every anchor here is either (a) the support of a NAMED
MakeHuman morph target — the vertex set that target displaces, which is MakeHuman's own
statement about where an anatomical region is — or (b) a coordinate extremum with a
stated geometric definition, or (c) a vertex list shipped by anny itself. Where neither
exists, the landmark is reported UNRESOLVED rather than approximated. Five of the
requested landmarks are unresolved and that is the most useful thing this file says:
this cage has no vertebra prominens, no costal margin, no iliac crest, no radial styloid
and no lateral malleolus. Asking it for those numbers gets you a fabricated body.

THE THIRD TRAP is pose. The cage stands in an A-pose (measured: the hands sit at 0.53 of
stature with a half-span of 0.55m against a 1.69m body). ANSUR arm-landmark HEIGHTS —
wrist 0.4825 of stature — are taken with the arms hanging. Any height of an arm or hand
landmark from this cage is a pose coordinate and must never be compared to those tables.
The affected landmarks say so in their note.

WHAT ISO CONFORMANCE WOULD AND WOULD NOT MEAN HERE
ISO 20685-1 Table 4 bounds a MEAN difference over a validation sample, not a per-mesh
error, and per-mesh 4mm "accuracy" is meaningless anyway next to 14-19mm of diurnal
stature variation in a real person. Nothing in this module claims ISO conformance.
'anchor_kind': 'iso' means only that the landmark NAME and its anatomical definition come
from ISO 7250-1, and that we resolve it by that definition rather than by proxy.

Frame is established by measurement, not assumption — see frame_report(). Measured on
anny 0.5: +x is the subject's LEFT, +y is POSTERIOR, +z is SUPERIOR (an LPS frame), feet
at z minimum, and the cage is bilaterally symmetric to 0.017mm.
"""

import json
import os
import sys

import numpy as np

# ruff: noqa: F401  this module inherits the pre-split top import block and its siblings
# re-import those names from here.

from zyg_workflows import paths as _paths
from zyg_workflows.geom import mesh_skeletons as MS

# Topology the supports are indexed against. A different cage invalidates every index in
# this file, so we refuse rather than return silently-wrong vertices.
CAGE_VERTS = 13718
CAGE_FACES = 13710

# The reference phenotype MS._morph_support probes at. Repeated here because a few
# targets (nipple-*, breast-*) have EXACTLY zero displacement at gender=0.0 and must be
# probed at the female reference instead — measured, not assumed: nipple-size-incr moves
# 0 vertices at gender 0.0 and 32 vertices at gender 1.0.
REF_MALE = {'gender': 0.0, 'age': 0.5, 'muscle': 0.5, 'weight': 0.5, 'height': 0.5, 'proportions': 0.5}
REF_FEMALE = dict(REF_MALE, gender=1.0)

# ---------------------------------------------------------------------------------
# MEASURED reference distribution.
# ANSUR II (2012) public-release microdata, computed from the files on disk on
# 2026-08-05 by this module's own loader: n=4082 US Army males, n=1986 females, all
# linear columns in MILLIMETRES, expressed as mean and SD of landmark height / stature.
# These are a US military sample: fit, young, and NOT a general-population reference.
# They bound plausibility, they do not define a target.
#
# NOTE ON THE BRIEFING NUMBERS: the values circulated with this task for three of these
# landmarks do not reproduce from the microdata. Measured here: knee (mid-patella)
# .2780 not .2665, tibiale .2665 not .2500, lateral malleolus .0415 not .0439. The
# briefing's ".2665 knee" is in fact the tibiale figure. All other briefing values
# (cervicale .8639, acromion .8203, crotch .4815, wrist .4825, trochanterion .5128,
# buttock .5054, omphalion .6014, tenth rib .6380) reproduce exactly.
# ---------------------------------------------------------------------------------
REFERENCE_FRACTIONS = {
    #                        male (mean, sd)     female (mean, sd)   ansur column
    'cervicale': ((0.8639, 0.0066), (0.8570, 0.0068), 'cervicaleheight'),
    'acromion': ((0.8203, 0.0096), (0.8198, 0.0087), 'acromialheight'),
    'suprasternale': ((0.8191, 0.0071), (0.8164, 0.0071), 'suprasternaleheight'),
    'thelion': ((0.7351, 0.0105), (0.7194, 0.0140), 'chestheight'),
    'tenth_rib': ((0.6380, 0.0120), (0.6485, 0.0111), 'tenthribheight'),
    'iliocristale': ((0.6044, 0.0128), (0.6113, 0.0129), 'iliocristaleheight'),
    'omphalion': ((0.6014, 0.0129), (0.6017, 0.0135), 'waistheightomphalion'),
    'trochanterion': ((0.5128, 0.0152), (0.5190, 0.0144), 'trochanterionheight'),
    'buttock': ((0.5054, 0.0164), (0.5118, 0.0156), 'buttockheight'),
    'stylion': ((0.4825, 0.0123), (0.4877, 0.0122), 'wristheight'),
    'crotch': ((0.4815, 0.0141), (0.4802, 0.0151), 'crotchheight'),
    'patella_mid': ((0.2780, 0.0092), (0.2756, 0.0090), 'kneeheightmidpatella'),
    'tibiale': ((0.2665, 0.0081), (0.2687, 0.0084), 'tibialheight'),
    'malleolus_lat': ((0.0415, 0.0029), (0.0385, 0.0028), 'lateralmalleolusheight'),
}

# MEASURED, ANSUR II, per-subject mean of (cervicale - suprasternale)/stature. This is
# the only defensible route to a cervicale height on this cage (see the cervicale entry):
# apply it to our resolved suprasternale. It is a HOUSE substitution, not a measurement.
CERVICALE_OVER_SUPRASTERNALE = {'male': (0.0448, 0.0065), 'female': (0.0405, 0.0071)}


# ---------------------------------------------------------------------------------
# cached, topology-fixed anchors
# ---------------------------------------------------------------------------------
_CACHE = {}


def _support(label, thresh=3e-4, ref='male'):
    """(idx, weight) of a named MakeHuman target's displacement support, or None.

    Delegates to MS._morph_support for the male reference so the two share one cache.
    Returns None instead of raising when the support is empty — an empty support at the
    male reference is a real fact about gender-conditioned targets, not a failure.
    """
    key = ('sup', label, thresh, ref)
    if key in _CACHE:
        return _CACHE[key]
    got = None
    if ref == 'male':
        try:
            got = MS._morph_support(label, thresh)
        except RuntimeError:
            got = None
    else:
        phen = REF_FEMALE if ref == 'female' else dict(ref)
        v0, _, _ = MS._build_mesh(phen, None)
        v1, _, _ = MS._build_mesh(phen, {label: 1.0})
        d = np.linalg.norm(v1.astype(np.float64) - v0.astype(np.float64), axis=1)
        idx = np.nonzero(d > thresh)[0]
        if len(idx):
            got = (idx, (d[idx] / max(d[idx].max(), 1e-9)) ** 0.5)
    _CACHE[key] = got
    return got


def _support_core(label, frac, thresh=3e-4, ref='male'):
    """Support restricted to vertices displaced at least `frac` of the peak.

    Several targets (hips-circ, buttocks-volume, waist-circ) touch the whole body because
    they translate everything below them; only the high-displacement core is a ring. The
    plain support of measure-hips-circ-incr is 13,716 of 13,718 vertices and is useless
    as an anchor; its 0.8-core is 102 vertices spanning 0.475-0.536 of stature.
    """
    key = ('core', label, frac, thresh, ref)
    if key in _CACHE:
        return _CACHE[key]
    phen = REF_MALE if ref == 'male' else REF_FEMALE
    v0, _, _ = MS._build_mesh(phen, None)
    v1, _, _ = MS._build_mesh(phen, {label: 1.0})
    d = np.linalg.norm(v1.astype(np.float64) - v0.astype(np.float64), axis=1)
    if d.max() <= 0:
        _CACHE[key] = None
        return None
    idx = np.nonzero(d >= frac * d.max())[0]
    _CACHE[key] = (idx, d[idx] / d.max())
    return _CACHE[key]


def _anny_waist_ring():
    """The 46-vertex waist ring anny itself ships (anny.anthropometry).

    Included because it is the only landmark on this cage defined by the model vendor
    rather than inferred by us — and because it is the girth-convention warning made
    concrete: anny sums straight chords around this ring, an INSCRIBED POLYLINE, which
    underestimates a taut tape. Do not compare a number taken around this ring to a
    survey waist circumference without switching to plane-slice + convex hull.
    """
    if 'anny_waist' in _CACHE:
        return _CACHE['anny_waist']
    from anny.anthropometry import BASE_MESH_WAIST_VERTICES as ring

    m = MS._model()
    base = m.base_mesh_vertex_indices.detach().cpu().numpy().tolist()
    idx = np.array([base.index(i) for i in ring], np.int64)
    _CACHE['anny_waist'] = idx
    return idx


def _coco(phenotype=None, local_changes=None):
    """anny's shipped COCO keypoint regressor evaluated on one recipe.

    These are JOINT CENTRES (a linear blend of vertices that lands inside the body), not
    surface landmarks — they are used here only where a joint centre is the right anchor:
    the glenohumeral centre for acromion, the femoral-head centre for trochanterion.
    """
    import torch
    from anny.keypoints import KeypointsRegressor

    m = MS._model()
    if 'coco_reg' not in _CACHE:
        _CACHE['coco_reg'] = KeypointsRegressor(m, [], 'coco')
    kr = _CACHE['coco_reg']
    kw = {'phenotype_kwargs': dict(phenotype or REF_MALE)}
    if local_changes:
        kw['local_changes_kwargs'] = dict(local_changes)
    with torch.no_grad():
        pts = kr(m(**kw))[0].numpy()
    return dict(zip(kr.labels, pts))


# ---------------------------------------------------------------------------------
# frame
# ---------------------------------------------------------------------------------
def _axis_probe():
    """Measure which mesh axis is up / front / left from oriented morph targets."""
    if 'axes' in _CACHE:
        return _CACHE['axes']
    v0, _, _ = MS._build_mesh(REF_MALE, None)
    out = {}
    for label in ('head-trans-up', 'nose-trans-forward', 'l-hand-trans-out', 'r-hand-trans-out'):
        v1, _, _ = MS._build_mesh(REF_MALE, {label: 1.0})
        d = v1.astype(np.float64) - v0.astype(np.float64)
        moved = np.nonzero(np.linalg.norm(d, axis=1) > 3e-4)[0]
        out[label] = {
            'n': int(len(moved)),
            'mean_disp_mm': np.round(d[moved].mean(0) * 1000, 2).tolist(),
            'support_centroid_mm': np.round(v0[moved].mean(0) * 1000, 1).tolist(),
        }
    _CACHE['axes'] = out
    return out


def frame_report(v, faces):
    """What was MEASURED about the coordinate frame — never assumed."""
    v = np.asarray(v, np.float64)
    _check_topology(v, faces)
    probe = _axis_probe()
    up = int(np.argmax(np.abs(probe['head-trans-up']['mean_disp_mm'])))
    up_sign = int(np.sign(probe['head-trans-up']['mean_disp_mm'][up]))
    front = int(np.argmax(np.abs(probe['nose-trans-forward']['mean_disp_mm'])))
    front_sign = int(np.sign(probe['nose-trans-forward']['mean_disp_mm'][front]))
    # The lateral axis is the ANTISYMMETRIC one, not the largest component: measured,
    # l-hand-trans-out displaces (+13.07, -20.49, -19.45) mm, so its biggest component
    # is y and a largest-component test names the wrong axis. Only x flips sign between
    # the l- and r- targets, and that is what "lateral" means.
    dl = np.array(probe['l-hand-trans-out']['mean_disp_mm'])
    dr = np.array(probe['r-hand-trans-out']['mean_disp_mm'])
    lat = int(np.argmax(np.abs(dl - dr)))
    left_sign = int(np.sign(dl[lat]))
    if len({up, front, lat}) != 3:
        raise RuntimeError(
            'axis probe is degenerate: up=%d front=%d lateral=%d — the '
            'oriented morph targets did not resolve to three distinct '
            'axes' % (up, front, lat)
        )

    from scipy.spatial import cKDTree

    mir = v.copy()
    mir[:, lat] *= -1
    d, j = cKDTree(v).query(mir)
    e_left = np.zeros(3)
    e_left[lat] = left_sign
    e_ant = np.zeros(3)
    e_ant[front] = front_sign
    e_sup = np.zeros(3)
    e_sup[up] = up_sign

    zmin = float(v[:, up].min())
    H = float(v[:, up].max()) - zmin
    hand = _support('l-hand-fingers-length-incr')
    hand_fz = float(((v[hand[0], up] - zmin) / H).mean()) if hand else float('nan')

    return {
        'axis_probe': probe,
        'up_axis': 'xyz'[up],
        'up_sign': up_sign,
        'anterior_axis': 'xyz'[front],
        'anterior_sign': front_sign,
        'subject_left_axis': 'xyz'[lat],
        'subject_left_sign': left_sign,
        'convention': '%s%s left, %s%s posterior, %s%s superior'
        % ('+-'[left_sign < 0], 'xyz'[lat], '+-'[front_sign > 0], 'xyz'[front], '+-'[up_sign < 0], 'xyz'[up]),
        'handedness': 'right-handed (det[left, posterior, superior] = %+d)'
        % int(round(float(np.linalg.det(np.stack([e_left, -e_ant, e_sup])))))
        if float(np.linalg.det(np.stack([e_left, -e_ant, e_sup]))) > 0
        else 'left-handed',
        'ground_plane': 'z = %.4f (mesh minimum; feet are lowest)' % zmin,
        'stature_m': round(H, 4),
        'bilateral_symmetry_max_residual_mm': round(float(d.max()) * 1000, 4),
        'mirror_map_involutive': bool((j[j] == np.arange(len(v))).all()),
        'outward_normals': bool(MS._vertex_normals(v, faces)[int(np.argmax(v[:, up])), up] * up_sign > 0),
        'pose': 'A-pose — hand support centroid sits at %.3f of stature with a half-span '
        'of %.3f m; ARM AND HAND LANDMARK HEIGHTS ARE POSE COORDINATES and are '
        'not comparable to standing-posture survey heights' % (hand_fz, float(np.abs(v[:, lat]).max())),
    }


def _check_topology(v, faces):
    if len(v) != CAGE_VERTS:
        raise ValueError(
            'landmarks are indexed against the %d-vertex anny cage; got %d '
            '— every vertex index in this module is invalid for that mesh' % (CAGE_VERTS, len(v))
        )
    f = np.asarray(faces)
    if f.shape != (CAGE_FACES, 4):
        raise ValueError('expected the %d-quad anny cage, got faces %s' % (CAGE_FACES, (f.shape,)))
