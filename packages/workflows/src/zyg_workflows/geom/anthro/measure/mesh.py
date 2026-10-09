# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""measure_mesh() — the whole-body pass that fills every table.

Moved verbatim out of the old single-file measure.py (lines 2264-2602); the table
passes themselves live in mesh_tables.py since the 2026-10 function-size split.
"""

import time

import numpy as np

from zyg_workflows.geom.anthro import landmarks as LMK
from zyg_workflows.geom.anthro.measure.constants import SCAN_STEP_FRAC
from zyg_workflows.geom.anthro.measure.topology import _topology
from zyg_workflows.geom.anthro.measure.anchors import (
    _ear_top_frac,
    _limb_axes,
)
from zyg_workflows.geom.anthro.measure.primitives import (
    adducted_copy,
    check_pose_and_frame,
)
from zyg_workflows.geom.anthro.measure import mesh_tables as _tables
from zyg_workflows.geom.anthro.measure.ratios import _ratios


def measure_mesh(v, faces, *, sex=None, landmarks=None, phenotype=None, local_changes=None, name=None):
    """Every measurement this cage can honestly produce, with its provenance.

    Returns {'meta', 'measurements', 'ratios'}.

    measurements maps a name to a record carrying value_mm, kind, landmark, convention,
    iso_class and a note — plus, for anything that came off a plane slice, the loop count,
    the selection rule, the arm-contamination count and the other two girth conventions.
    A value of None is always accompanied by a 'reason'.

    phenotype / local_changes are not decoration: the acromion and trochanterion anchors
    and every limb axis come from anny's own joint-centre regressor, which must be
    evaluated on THIS recipe. Omitting them silently falls back to the neutral body's
    joints, which landmarks.py measured as a 16-19 mm error in acromial height — more than
    a whole ANSUR standard deviation. The meta block records which happened.
    """
    v = np.asarray(v, np.float64)
    faces = np.asarray(faces)
    t_start = time.time()
    pose = check_pose_and_frame(v, faces)

    zmin = float(v[:, 2].min())
    H = float(v[:, 2].max()) - zmin
    topo = _topology(faces)

    if landmarks is None:
        landmarks = LMK.resolve_landmarks(v, faces, phenotype, local_changes)
    coco, coco_src = _tables.resolve_coco(phenotype, local_changes)
    axes = _limb_axes(coco)

    # The arms-down copy every horizontal site is differenced against. Built once; when it
    # cannot be built, every affected record says so instead of quietly reporting no bias.
    pose_ref, pose_ref_info = adducted_copy(v, coco)

    scan = _tables.MeshScan(
        v=v,
        faces=faces,
        zmin=zmin,
        H=H,
        topo=topo,
        landmarks=landmarks,
        axes=axes,
        coco=coco,
        coco_src=coco_src,
        pose=pose,
        pose_ref=pose_ref,
        pose_ref_info=pose_ref_info,
        step=SCAN_STEP_FRAC * H,
        ear_top=_ear_top_frac(v, zmin, H),
        crotch_frac=(landmarks.get('crotch') or {}).get('frac_stature'),
        sex=sex,
        name=name,
        t_start=t_start,
    )

    M: dict = {}
    _tables.height_rows(M, scan)
    _tables.cervicale_row(M, scan)
    _tables.length_rows(M, scan)
    _tables.girth_rows(M, scan)
    _tables.extent_rows(M, scan)
    _tables.volume_rows(M, scan)
    ratios = _ratios(M, H)
    meta = _tables.meta_block(scan)
    _tables.unmeasurable_rows(M)
    return {'meta': meta, 'measurements': M, 'ratios': ratios}
