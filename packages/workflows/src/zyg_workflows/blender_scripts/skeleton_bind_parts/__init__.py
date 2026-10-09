# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""skeleton_bind, section by section — see ``.constants`` for the file docstring.

The submodules are re-imported below in the ORIGINAL section order of
skeleton_bind.py; every top-level name the old module defined, public and
underscore alike, is re-exported here so ``skeleton_bind.X`` resolves
unchanged.  ``LAST_FIT`` is the one name a by-value copy would break
(attach_skeleton rebinds it); it lives in ``.entry`` and the shim resolves
it there on every access.
"""

# ruff: noqa: F401

from .constants import (  # noqa: I001
    annotations,
    json,
    math,
    os,
    sys,
    tempfile,
    bpy,
    Matrix,
    Quaternion,
    Vector,
    HERE,
    CREWS,
    SKELETON_BLEND,
    BASE_BODY_RIG_DIR,
    PIECE_PREFIX,
    SOURCE_CREDIT,
    SUBSURF_LEVELS,
    TRI_BUDGET_HIGH,
    TRI_BUDGET_TARGET,
    TRI_FLOOR,
    AXIS_SCALE_CLAMP,
    INSIDE_MARGIN,
    EXTRA_MESHES,
)

from .entry import (  # noqa: I001
    LAST_FIT,
)

from .piece_map import (  # noqa: I001
    _MIDLINE_MAP,
    _SIDED_MAP,
    FINGERS,
    PHALANX_ROWS,
    TRUNK_BONES,
    LIMB_GROUPS,
    _ABSORBED,
    _split_piece,
    bone_for_piece,
)

from .linalg import (  # noqa: I001
    _outer,
    _affine,
    _rotation_between,
    _frame,
    _segment_matrix,
)

from .loading import (  # noqa: I001
    _link,
    load_skeleton_pieces,
    _origins,
    _mesh_height,
)

from .placement import (  # noqa: I001
    _bone_world,
    _mean,
    _limb_frames,
    TRUNK_ANCHORS,
    _skin_columns,
    _trunk_depth_offset,
    STUB_GROUPS,
    LIMB_ORDER,
    SOCKET_GROUPS,
    SOCKET_TOL,
    _centroid,
    _far_axis,
    _slab_frame,
    _group_verts,
    compute_placement,
)

from .body_boxes import (  # noqa: I001
    _body_boxes,
    _body_points,
    _raw_group_points,
    _body_bvh,
    _column_overflow,
    _surface_depth,
    _collapsed_adjacency,
    _neighbour_box,
)

from .tuck import (  # noqa: I001
    TUCK_UNITS,
    TUCK_MARGIN,
    TUCK_MIN_CLEAR,
    TUCK_PASSES,
    TUCK_SCALE_FLOOR,
    TUCK_STEPS,
    TUCK_BAND,
    TUCK_STRIDE,
    TUCK_PUSH_UNITS,
    TUCK_PUSH_MAX,
    TUCK_PUSH_SKIRT,
    AXIS_NAME,
    _silhouette_columns,
    _skin_depth_columns,
    _probes,
    _clearance,
    _d_interval,
    _tuck_band,
    _tuck_field,
    _apply_field,
    _tuck_push,
    _tuck_trunk,
    _piece_box,
)

from .entry import (  # noqa: I001
    attach_skeleton,
    _harden_weights,
    _render,
    main,
)

__all__ = [
    'annotations',
    'json',
    'math',
    'os',
    'sys',
    'tempfile',
    'bpy',
    'Matrix',
    'Quaternion',
    'Vector',
    'HERE',
    'CREWS',
    'SKELETON_BLEND',
    'BASE_BODY_RIG_DIR',
    'PIECE_PREFIX',
    'SOURCE_CREDIT',
    'SUBSURF_LEVELS',
    'TRI_BUDGET_HIGH',
    'TRI_BUDGET_TARGET',
    'TRI_FLOOR',
    'AXIS_SCALE_CLAMP',
    'INSIDE_MARGIN',
    'EXTRA_MESHES',
    'LAST_FIT',
    '_MIDLINE_MAP',
    '_SIDED_MAP',
    'FINGERS',
    'PHALANX_ROWS',
    'TRUNK_BONES',
    'LIMB_GROUPS',
    '_ABSORBED',
    '_split_piece',
    'bone_for_piece',
    '_outer',
    '_affine',
    '_rotation_between',
    '_frame',
    '_segment_matrix',
    '_link',
    'load_skeleton_pieces',
    '_origins',
    '_mesh_height',
    '_bone_world',
    '_mean',
    '_limb_frames',
    'TRUNK_ANCHORS',
    '_skin_columns',
    '_trunk_depth_offset',
    'STUB_GROUPS',
    'LIMB_ORDER',
    'SOCKET_GROUPS',
    'SOCKET_TOL',
    '_centroid',
    '_far_axis',
    '_slab_frame',
    '_group_verts',
    'compute_placement',
    '_body_boxes',
    '_body_points',
    '_raw_group_points',
    '_body_bvh',
    '_column_overflow',
    '_surface_depth',
    '_collapsed_adjacency',
    '_neighbour_box',
    'TUCK_UNITS',
    'TUCK_MARGIN',
    'TUCK_MIN_CLEAR',
    'TUCK_PASSES',
    'TUCK_SCALE_FLOOR',
    'TUCK_STEPS',
    'TUCK_BAND',
    'TUCK_STRIDE',
    'TUCK_PUSH_UNITS',
    'TUCK_PUSH_MAX',
    'TUCK_PUSH_SKIRT',
    'AXIS_NAME',
    '_silhouette_columns',
    '_skin_depth_columns',
    '_probes',
    '_clearance',
    '_d_interval',
    '_tuck_band',
    '_tuck_field',
    '_apply_field',
    '_tuck_push',
    '_tuck_trunk',
    '_piece_box',
    'attach_skeleton',
    '_harden_weights',
    '_render',
    'main',
]
