# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The umbrella entry point over the digit pack, and its synthetic lesion recipe.

Moved verbatim out of the old single-file hands.py (lines 3328-3387, 3516-3588).
"""

import numpy as np

from zyg_workflows.geom.form.hands.rig import (
    SCHEMA,
    FINGERS,
    DIGIT_BONES,
    _side,
)
from zyg_workflows.geom.form.hands.unresolved import (
    DIGIT_UNRESOLVED,
)
from zyg_workflows.geom.form.hands.digits_rig import (
    _env_flag,
    DIGIT_GATES_FLAG,
    _ratio_band,
    skeleton,
    _blen,
)
from zyg_workflows.geom.form.hands.digit_chains import (
    check_digit_chains,
    check_phalanx_ratio,
)
from zyg_workflows.geom.form.hands.child_hand import (
    check_child_hand,
)


# ---------------------------------------------------------------------------------
# The umbrella entry point
# ---------------------------------------------------------------------------------
def check_digits(
    phenotype, local_changes=None, bone_scales=None, anatomy=None, sides=('L', 'R'), with_mesh=True, params=None
):
    """All three digit predicates for one character, both hands and both feet.

    Takes PARAMETERS, not vertices, on purpose: the skeleton and the cage have to come
    out of the same recipe or the verdict is about two different bodies. check_hand_mesh
    keeps its (v, faces, side) signature and gains an optional params= passthrough.

    `params` carries the phalanx correction the body was ISSUED with. Everything below is
    threaded the same dict so the mesh half and the skeleton half of this pack cannot end
    up on different hands — the same reason the whole function takes a recipe rather than
    a vertex array.
    """
    if not _env_flag(DIGIT_GATES_FLAG, True):
        return {
            'schema': SCHEMA,
            'basis': 'rig',
            'disabled': True,
            'why': '%s is set to off' % DIGIT_GATES_FLAG,
            'predicates': {},
        }
    from zyg_workflows.geom import mesh_skeletons as MS

    v = faces = None
    if with_mesh:
        v, faces, _ = MS._build_mesh(phenotype, local_changes or None, bone_scales or None, params=params)
        v = np.asarray(
            MS._apply_anatomy(
                v,
                faces,
                anatomy or {},
                phenotype=phenotype,
                local_changes=local_changes or None,
                bone_scales=bone_scales or None,
                params=params,
            ),
            np.float64,
        )
    out = {
        'schema': SCHEMA,
        'basis': 'rig',
        'sides': {},
        'unresolved': list(DIGIT_UNRESOLVED),
        'hand_correction': (params or {}).get('hand_correction'),
        'rollback_flag': {'name': DIGIT_GATES_FLAG, 'default': '1 (on)'},
    }
    for s in sides:
        S = _side(s)
        out['sides'][S] = {
            'digit_chains': check_digit_chains(phenotype, local_changes, bone_scales, S, params=params),
            'phalanx_ratio': check_phalanx_ratio(phenotype, local_changes, bone_scales, S, v, faces, params=params),
            'child_hand': check_child_hand(phenotype, local_changes, bone_scales, S, anatomy, params=params),
        }
    return out


# ---------------------------------------------------------------------------------
# Synthetic lesion for the digit pack — a gate that has never failed anything is not
# calibrated. This one moves the interphalangeal joints along the finger WITHOUT
# changing the finger's total length, which is exactly the defect class the pack exists
# to catch and exactly the one no length gate in geom.anthro can see.
# ---------------------------------------------------------------------------------
def phalanx_scale_recipe(phenotype, local_changes=None, targets=None, factor=1.0):
    """A bone_scales recipe that moves the interphalangeal joints and NOTHING ELSE.

    Every finger is driven to a chosen (mid/prox, dist/mid) pair while its TOTAL length,
    its metacarpal and its MCP position are all left exactly where they were. That is
    the whole point: it is precisely the defect class no gate in geom.anthro can see,
    because `hand_length` is wrist_ring -> dactylion and does not care where the knuckles
    inside it fall.

    `targets` maps finger -> (mid_over_prox, dist_over_mid); `factor` multiplies both,
    so factor=1 with targets=the survey means is a REPAIR and factor=1.4 is a lesion.
    With targets=None the finger's own current ratios are used, so factor alone drives.

    The construction relies on a property of mesh_skeletons._scale44 that is MEASURED
    here rather than assumed: a bone scale propagates multiplicatively down the
    kinematic chain, and it does not move the scaled bone's own head. Verified on the
    neutral — finger2-1 x1.4 with finger2-2 x0.5 gives proximal 37.0784 mm
    (= 26.4846 x 1.4), middle 16.6380 (= 23.7685 x 1.4 x 0.5) and distal 18.9564
    (= 27.0806 x 1.4 x 0.5) to 4 dp, with the MCP and the metacarpal length both moving
    0.000000 mm.

    THE EXACTNESS ABOVE HOLDS BECAUSE THIS RECIPE SCALES UNIFORMLY, and only because of
    that. `bs[...] = a` is a bare scalar, which _scale44 expands to (a, a, a); an
    isotropic scale multiplies every direction by the same factor, so a child bone's
    length scales by the parent's factor no matter which way the child points.

    UNDER AN ANISOTROPIC SCALE IT IS FALSE, measured 2026-08-08 on this same neutral:
    finger2-1 scaled on LOCAL Y ALONE by 1.5 gives its own length x1.500000 but the
    middle phalanx x1.481045 and the distal x1.451370, and the deviation grows with
    distance from 1.0 (x0.6 -> child x0.623644; x2.0 -> child x1.965804). The cause is
    geometric and visible in the rig: consecutive bone axes within a finger differ by
    7.6 to 25.6 degrees, so a scale along the PARENT's Y is not a scale along the
    CHILD's axis. Anything reaching for a closed form under a Y-only scale — as
    geom.anthro.hand_correction must, because it has to lengthen a phalanx without
    fattening it — has to SOLVE instead, and that is why that module iterates.

    With per-bone scales a, b, c on the proximal, middle and distal phalanges the
    segment lengths become a*p, a*b*m and a*b*c*d, so b = rm*p/m and c = rd*m/d hit the
    target ratios and a = (p+m+d) / (p + b*m + b*c*d) restores the original total.
    """
    # apply_hand_correction=False: this builds a LESION recipe, and it has to be measured
    # against the uncorrected rig it will be composed with, not against a hand the
    # correction has already moved.
    sk = skeleton(phenotype, local_changes, None, apply_hand_correction=False)
    bs = {}
    for n, d in zip((2, 3, 4, 5), FINGERS):
        for S in ('L', 'R'):
            p, mm, dd = [_blen(sk, b, S) for b in DIGIT_BONES[d][1:]]
            if targets is None:
                rm, rd = mm / p, dd / mm
            else:
                rm, rd = targets[d]
            rm, rd = rm * factor, rd * factor
            b = rm * p / mm
            c = rd * mm / dd
            a = (p + mm + dd) / (p + b * mm + b * c * dd)
            bs['finger%d-1.%s' % (n, S.lower())] = a
            bs['finger%d-2.%s' % (n, S.lower())] = b
            bs['finger%d-3.%s' % (n, S.lower())] = c
    return bs


def survey_mean_targets():
    """{finger: (mid/prox, dist/mid)} at the mean of the two radiographic series."""
    return {d: (_ratio_band(d, 'mid_over_prox')['centre'], _ratio_band(d, 'dist_over_mid')['centre']) for d in FINGERS}
