# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401  this package is the public face of the former head_fit.py: every name
# the single module defined is re-exported here so no importer needs editing.

"""head_fit.py — from a contact sheet to a GNM head identity, measured.

RUN:
    /usr/bin/python3.12 -m zyg_workflows.geom.head_fit corr            # derive + cache MP468->iBUG68
    /usr/bin/python3.12 -m zyg_workflows.geom.head_fit run [--chars c3345deb5bde,0015c8a3f2e3]
    /usr/bin/python3.12 -m zyg_workflows.geom.head_fit smoke

WHY THIS EXISTS. GNM Head's identity space is only useful to this stack if a
CHARACTER can be driven into it — and until now there was no path at all from a
contact sheet to a GNM identity. gnm_fit.py fits GNM to an already-registered
anny head (mesh-to-mesh ICP); this module fits GNM to PICTURES, through the 478
MediaPipe landmarks the cell grid already stores. The missing link was the
correspondence: GNM ships 68 barycentric landmark anchors (gnm_head.landmark_points)
in the iBUG-68 convention, MediaPipe emits 478 points in its own, and no map
between them exists in either project (grep for 468/478/mediapipe in gnm_*.py:
zero hits, 2026-09-02).

HOW THE CORRESPONDENCE IS DERIVED, NOT GUESSED. `build_correspondence()` takes
MediaPipe's canonical_face_model.obj (468 verts, Apache-2.0) and ICT FaceKit's
neutral mesh, which ships its OWN 68 landmark VERTEX INDICES
(vertex_indices.json:idx_to_landmark_verts) in the same iBUG ordering GNM uses —
verified here, not assumed, by Procrustes between the ICT-68 and GNM-68 point
sets. Both meshes and the MediaPipe canonical share the frame layout (X = subject
left, Y = up, Z = forward; measured, see `_frame_check`). Eight geometric anchors
(nose tip, chin, four eye corners, two mouth corners) are found by extremum
inside the relevant FACEMESH set, a similarity transform is solved from them,
and every remaining iBUG landmark is matched to its nearest MediaPipe vertex
INSIDE the semantically correct FACEMESH set (jawline -> FACE_OVAL, brows ->
the eyebrow sets, nose -> NOSE, eyes -> the eye sets, mouth -> LIPS), greedily
and uniquely. Every landmark carries its own residual in mm, and the jawline is
flagged: iBUG 0-16 are silhouette points in the 2D convention but fixed vertices
in both meshes, so their correspondence is the weakest part of the map and the
fit weights them accordingly (JAW_WEIGHT).

WHAT IS FITTED (per cell): GNM identity (253) + expression (the subset of the
383 that actually moves a landmark) + a global rotation + a pinhole camera
[tz, cx, cy] with f fixed at 1.35*max(W,H) — the same lens convention anny_fit
uses (anny_fit.py:324), adapted to GNM's Y-up/Z-forward frame:
    zc = tz - Z,  x = f*X/zc + cx,  y = f*(-Y)/zc + cy.
f and tz stay degenerate through a monocular fit exactly as they do there; tz
carries scale, and that is why the null below gets its own camera.

THE NULL IS NOT OPTIONAL. Every reported number has a control: the MEAN head
(identity = 0) refitted on the SAME cell with its OWN camera, rotation and
expression. A mean head with a free camera can already put 68 landmarks within a
few px of any face; identity gain is (null RMS - fitted RMS) and nothing else is
ever called identity capacity. Gain is reported on HELD-OUT cells — cells whose
landmarks the joint identity solve never saw — because a per-image identity fit
scores well by construction.

Four-state ledger per cell: fitted / no_face (detector found none) / declined
(too few reliable landmarks, or |yaw| past the profile limit where the fixed
jawline correspondence stops meaning anything) / failed (the solve raised).
"""

from __future__ import annotations

import argparse
import json
import os
import time

from zyg_workflows import paths

# The submodules are imported in the original section order of head_fit.py, so any
# module-level side effect still happens in the order the single file had.
from zyg_workflows.geom.head_fit.corr_map import (
    _HERE,
    _CREWS,
    ICT_DIR,
    CORR_PATH,
    MP_CANON,
    FACEMESH,
    CHAR_MESH,
    OUT_ROOT,
    IBUG_GROUPS,
    JAW,
    JAW_WEIGHT,
    YAW_LIMIT,
    MIN_LANDMARKS,
    EXPR_LANDMARK_MIN_M,
    _CACHE,
    _similarity,
    _frame_check,
    build_correspondence,
    correspondence,
)
from zyg_workflows.geom.head_fit.cell_fit import (
    gnm_landmark_ops,
    _cells,
    _cell_targets,
    _cell_state,
    _project_batch,
    _solve_batch,
    fit_cell,
    landmark_weights,
    fit_character,
    run,
    _require,
    smoke,
)
from zyg_workflows.geom.head_fit.plates import (
    VENV_PY,
    PLATE_ROOT,
    _DRIVER_SCRIPT,
    extract_driver,
    _ict_face_region,
    _pose_ict,
    _raster,
    _plate_pngs,
    expression_plates,
)
from zyg_workflows.geom.head_fit.bridge import (
    GNM_FITS,
    BRIDGE_DIR,
    _anny_head_frame,
    _blend_weights,
    bridge_decision,
    _cli,
)
