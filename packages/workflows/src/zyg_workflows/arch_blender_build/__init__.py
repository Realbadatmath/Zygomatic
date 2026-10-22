# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: E402
# E402: the submodule imports follow the original top import block and the `_zyg_log`
# binding, kept verbatim from the single-file arch_blender_build.py.  Hoisting them
# cannot be proved here -- the package needs `bpy`, which no venv has -- so the moved
# order stands.
"""Architecture Studio drawing JSON -> Blender .blend (+ optional .glb).

Rebuilds every record of a studio drawing as a parametric mesh (Blender 4.3,
headless).  Frame conversion: studio is X right / Y up / Z toward viewer;
Blender (x, y, z) = (studio x, -studio z, studio y), and the studio's ry
(rotation about the vertical) becomes a rotation about Blender Z.

Usage:
  blender -b --python arch_blender_build.py -- --in DRAWING.json --out OUT.blend [--glb OUT.glb]
"""

import argparse
import json
import math
import os
import sys
import traceback

import bpy
import bmesh
from mathutils import Matrix
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

from zyg_workflows.arch_blender_build.materials import (
    MAT_COLOURS,
    MAT_FALLBACK,
    KIND_DEFAULT_MAT,
    _MATERIALS,
    _LIB_SLOTS,
    lib_def,
    _tex_image,
    get_material_tex,
    GLASS_LOOKS,
    GLASS_PANEL_KINDS,
    GLASS_CLEAR_KINDS,
    GLASS_EEVEE_SPEC,
    WATER_EEVEE_ALPHA,
    glass_look,
    _sock,
    _mat_flag,
    _transparent_surface,
    get_material_glass,
    get_material_water,
    tune_glass_for_eevee,
    get_material,
    VCOL_ATTR,
    get_material_vc,
)
from zyg_workflows.arch_blender_build.kinds import (
    num,
    add_box,
    add_box_c,
    _tag,
    add_cylinder,
    add_sphere,
    add_prism,
    add_dome,
    add_hip,
    PLACEHOLDER_KINDS,
    ext_builders,
    mat_rgb,
    ext_kit,
    build_kind,
)
from zyg_workflows.arch_blender_build.build_scene import (
    cut_holes,
    import_asset,
    adopt_builder_objects,
    RENDER_SKIP_KINDS,
    build,
)
from zyg_workflows.arch_blender_build.cli import (
    main,
)

# Every name below is imported above and NOT used in this module: this package is the
# re-export surface of the split, so the names are its public API.  Nothing does
# ``import *`` from here, so __all__ changes no behaviour -- it tells ruff the imports
# are deliberate.
__all__ = [
    'argparse',
    'json',
    'math',
    'os',
    'sys',
    'traceback',
    'bpy',
    'bmesh',
    'Matrix',
    'MAT_COLOURS',
    'MAT_FALLBACK',
    'KIND_DEFAULT_MAT',
    '_MATERIALS',
    '_LIB_SLOTS',
    'lib_def',
    '_tex_image',
    'get_material_tex',
    'GLASS_LOOKS',
    'GLASS_PANEL_KINDS',
    'GLASS_CLEAR_KINDS',
    'GLASS_EEVEE_SPEC',
    'WATER_EEVEE_ALPHA',
    'glass_look',
    '_sock',
    '_mat_flag',
    '_transparent_surface',
    'get_material_glass',
    'get_material_water',
    'tune_glass_for_eevee',
    'get_material',
    'VCOL_ATTR',
    'get_material_vc',
    'num',
    'add_box',
    'add_box_c',
    '_tag',
    'add_cylinder',
    'add_sphere',
    'add_prism',
    'add_dome',
    'add_hip',
    'PLACEHOLDER_KINDS',
    'ext_builders',
    'mat_rgb',
    'ext_kit',
    'build_kind',
    'cut_holes',
    'import_asset',
    'adopt_builder_objects',
    'RENDER_SKIP_KINDS',
    'build',
    'main',
]

# _LIB_DEFS, _LIB_ROOT, _EXT_BUILDERS are rebound by a `global` statement inside the submodule that owns them
# (a lazy cache). A by-value re-export would freeze them at their pre-load value, so
# the package reads them through the owning submodule on every attribute access.
_ZYG_LAZY = {
    '_LIB_DEFS': 'materials',
    '_LIB_ROOT': 'materials',
    '_EXT_BUILDERS': 'kinds',
}


def __getattr__(name):
    owner = _ZYG_LAZY.get(name)
    if owner is None:
        raise AttributeError('module %r has no attribute %r' % (__name__, name))
    return getattr(globals()[owner], name)
