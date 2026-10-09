# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""blender_power — hands the assistant Blender itself (2026-09-06).

NO new kinds. Four tools, all of them two-stage:

  1. the CURRENT parametric drawing (`d.to_doc()`) is written to a temp JSON and
     built headless with `blender -b --python arch_blender_build.py -- --in X
     --out Y.blend` — exactly the command `arch_assistant.start_blender` uses,
     into the same `data/architecture/blender/` folder.  The built .blend is
     cached per document signature, so four tools in a row cost one build.
  2. a SECOND headless Blender opens that .blend and runs a generated script:
     the model's own bpy code (`blender_run`), a framed Workbench/EEVEE render
     (`blender_render`), a file export (`blender_export`) or a measurement
     table (`blender_measure`).

Pictures come back as a TUPLE `(text, data_url)` — `arch_assistant`'s loop turns
the second element into an image the model can see — and are also appended to
`d.images` so the user sees them in the chat.

Blender edits are a ONE-WAY street: they change the .blend, never the
parametric drawing.  Nothing here creates studio records.
"""

# This package is the former single-file module blender_power.py, cut at its own
# section banners.  Import path, names and module-level execution order are
# unchanged; every section below is a verbatim move.
# ruff: noqa: F401

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.blender_power.constants import (
    base64,
    hashlib,
    json,
    math,
    os,
    re,
    subprocess,
    time,
    Drawing,
    MAX_OBJECTS,
    _num,
    parse_cell,
    cell_centre,
    cell_of,
    surface_top,
    deck_tops,
    ground_height,
    BSTORE,
    _zyg_logging,
    _zyg_log,
    HERE,
    BLEND_DIR,
    RENDER_DIR,
    BUILDER,
    BLENDER,
    BUILD_TIMEOUT,
    PASS_TIMEOUT,
    _env_int,
    HERO_TIMEOUT,
    BP_CY_SAMPLES,
    HERO_VIEWS,
    HERO_H,
    HERO_W,
    HERO_FOCAL_MM,
    HERO_OFF_AXIS_DEG,
    HERO_DIST_K,
    HERO_DIST_MAX_K,
    HERO_HEADROOM,
    HERO_SUN_MIN,
    HERO_JPEG_W,
    HERO_JPEG_Q,
    HERO_GROUND_M,
    HERO_GROUND_MAT,
    HERO_EV,
    HERO_EV_VIEW,
    KINDS,
    OPENINGS,
    VIEWS,
    ORTHO_VIEWS,
    ENGINES,
    TOOL_ENGINES,
    SECTION_AXES,
    PRESENT_VIEWS,
    APPROACH_M,
    APPROACH_FOCAL_MM,
    LOBBY_INSIDE_M,
    LOBBY_LOOK_M,
    LOBBY_AIM_H_M,
    LOBBY_FOCAL_MM,
    LOBBY_EYE_M,
    LOBBY_CLEAR_M,
    LOBBY_STEP_M,
    LOBBY_MIN_INSIDE_M,
    BLANK_VIEW_N,
    MODEL_VIEWS,
    THUMB_W,
    THUMB_Q,
    THUMB_MAX_BYTES,
    PRESENT_CHECKLIST,
    SKY_RGB,
    SUN_ENERGY,
    SUN_ANGLE_DEG,
    SUN_ELEV_DEG,
    SUN_AZIM_DEG,
    EYE_HEIGHT_M,
    EYE_FOV_DEG,
    FOCAL_DEFAULT_MM,
    FOCAL_RANGE_MM,
    SENSOR_MM,
    SHIFT_MAX,
    LOOK_HEIGHT_M,
    EXPOSURE_EV,
    FORMATS,
    PROMPT,
)
from zyg_workflows.arch_assistant_ext.blender_power.build import (
    _blender_ok,
    _slug,
    _doc_sig,
    _build,
)
from zyg_workflows.arch_assistant_ext.blender_power.frame_script import (
    _FRAME,
)
from zyg_workflows.arch_assistant_ext.blender_power.second_pass import (
    _FRAMED,
    _MEASURE,
    _EXPORT,
    _sun_hour,
    hero_samples,
    _second_pass,
    _data_url,
    Reply,
    _thumb_jpeg,
    _between,
    _tail,
)
from zyg_workflows.arch_assistant_ext.blender_power.tools import (
    t_blender_run,
    _compass,
    _stand_note,
    _frame_camera,
    _camera_sentence,
    _ext,
    _entrance_door,
    _door_axis,
    _bounds,
    _envelope,
    _section_at,
    _section_cam,
    t_blender_render,
)
from zyg_workflows.arch_assistant_ext.blender_power.present import (
    present_sig,
    _persp_cam,
    _framed,
    _void_count,
    _present_shots,
    _sun_xz,
    _hero_free,
    _hero_points,
    _hero_ndc,
    _hero_cam,
    _hero_shot,
    t_present,
)
from zyg_workflows.arch_assistant_ext.blender_power.portfolio import (
    REF_BUILDER,
    PORTFOLIO_TIMEOUT,
    PORTFOLIO_CHECKLIST,
    _pf_store,
    t_portfolio,
)
from zyg_workflows.arch_assistant_ext.blender_power.hero_render import (
    PICTURE_URL,
    _hero_jpeg,
    hero_render,
    hero_images,
    t_blender_export,
    t_blender_measure,
    TOOLS,
    _EX_BEVEL,
    _EX_POOL,
    _EX_FINS,
    _EX_CAMERA,
    EXAMPLES,
)
