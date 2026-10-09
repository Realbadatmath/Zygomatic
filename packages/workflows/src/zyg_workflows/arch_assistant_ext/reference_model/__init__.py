# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# ruff: noqa: F401

"""reference_model — the assistant's door to the REFERENCE MODELS (2026-09-23).

The operator drops photographs and plans of a real thing into the icon rail
beside the chat panel; these four tools let the assistant look at them and
build the thing in Blender.

    list_reference_models()     what references exist, what is measured on them
    view_reference(...)         LOOK at the pictures — up to 3 come back as
                                pictures, not as descriptions
    build_reference_asset(...)  run a bpy script in an EMPTY scene with the
                                reference material laid out, save .blend + .glb,
                                and render the result OVER its own plans
    place_reference_asset(...)  drop the built asset into the drawing on a cell

WHY A SEPARATE TOOL FROM ``blender_run``

``blender_run`` opens the DRAWING's .blend. An asset is not part of the
drawing: it has its own origin, its own real size, and it must survive being
placed a hundred times. So this starts from a factory-empty scene, hands the
script the references as geometry (``ref_plane``), and ends with a file.

WHY THE CHECK RENDER IS NOT OPTIONAL-BY-DEFAULT

A model built from pictures is a guess until it is put back against the
pictures. The build renders the asset over each plan it used, in the plan's own
view, as a translucent overlay — so the difference between what was drawn and
what was asked for is a thing you can see rather than a thing you assert. That
is the same measurement the studio's own design checks are built on.

WHAT IT REFUSES TO PRETEND

One photograph cannot fix a size: depth and scale trade off exactly along every
ray. If a reference carries no measured length, every reply here says so, and
the asset is reported as "right shape, unverified size". It is not rounded up
into a claim.
"""

from zyg_workflows.arch_assistant_ext.reference_model.helpers import (
    annotations,
    base64,
    glob,
    json,
    os,
    re,
    shutil,
    subprocess,
    sys,
    time,
    R,
    MAX_OBJECTS,
    Drawing,
    _num,
    cell_centre,
    cell_name,
    parse_cell,
    place_height,
    _zyg_logging,
    ZYG_TMP_DIR,
    tmp_dir,
    HERE,
    _zyg_log,
    KINDS,
    OPENINGS,
    BLENDER,
    BUILDER,
    BUILD_TIMEOUT,
    MAX_SCRIPT,
    WORK_DIR,
    LOCK_PATH,
    THUMB_W,
    THUMB_MAX,
    PROMPT,
    EXAMPLES,
    Reply,
    _BlenderLock,
    INSPECT_N,
    PORTFOLIO_N,
    PORTFOLIO_CHECKLIST,
    INSPECT_CHECKLIST,
    _resolve,
    _thumb,
    _contact_sheet,
    _portfolio_folder,
    _audit_text,
    _scale_note,
)
from zyg_workflows.arch_assistant_ext.reference_model.build import (
    t_list_reference_models,
    t_view_reference,
    _write_pack,
    t_build_reference_asset,
)
from zyg_workflows.arch_assistant_ext.reference_model.views import (
    t_view_build_script,
    t_portfolio_reference_asset,
    t_place_reference_asset,
    _materials,
    _VIEWS,
    TOOLS,
)
