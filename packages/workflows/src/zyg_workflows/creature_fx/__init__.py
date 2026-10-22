# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Creature Studio toolbox — the half that MODIFIES a creature in the library.

Creature Studio could show you a creature and turn it around.  It could not
change one.  This module is the missing half: an ordered STACK of operations
over one of the creature's own images, compiled to two things at once —

  * a PIXEL chain (Pillow), deterministic, previewed live, and
  * an EDIT INSTRUCTION for Qwen-Image-Edit-2509, which is how every other
    stage of the creature pipeline changes a creature ([[creature_sheet_service]]).

...and baked into a DERIVED image beside the creature, never over it.

THREE THINGS LIVE IN ONE RECORD, the ruling vfx_fx.py settled: every op
declares its parameter schema, its icon, and what it compiles to.  The page
renders both bars FROM this registry (`/inspect/api/creature/fx/ops`) and holds
no tool list of its own, so adding an op here is the whole job.

WHY TWO CLASSES OF OP AND WHY THE PAGE SAYS WHICH.  A crop is arithmetic: it
runs in 40 ms, it is exact, and previewing it is free.  "Give it a longer tail"
is a 41 GB diffusion model's opinion, it takes minutes on the 4090, and no
preview can show it without running it.  Pretending both are the same knob is
the lie this toolbox refuses to tell — so a generative op carries a `~` pip in
the rail, the preview banner counts how many of them are NOT in the picture you
are looking at, and the receipt at /fx/chain prints the exact sentence that
will be sent.  Deterministic ops preview live and are the picture.

THE RENDER IS THE BAKE.  There is no proxy pass: the edit runs at the cell size
the sheet pipeline uses, with the graph the sheet pipeline uses, so what comes
back is what lands.  A 512px "preview" of a diffusion edit is not a smaller
version of the result, it is a different result ([[project_vfx_effect_toolbox]]).

WHAT A BAKE IS MEASURED AGAINST, EVERY TIME.  A generative edit that quietly
returns a different creature is the failure mode of this whole pipeline, and it
looks exactly like a success.  So every rendered candidate is scored by DINOv2
identity against the creature's own anchor (creature_identity, the same model
and the same bands the sheet QC uses) and by a structural change check against
its source; both numbers ride in the sidecar and on the card.  Best-of-N picks
on those numbers, not on order ([[feedback_measure_before_claim]]).

LICENCE IS INHERITED, NEVER RE-ASSERTED.  A derived image copies the creature's
train_family, its licence verdict and its commercial flag verbatim, plus what it
was derived from and the full recipe.  A klein creature's edits are Apache-2.0;
a FLUX.1-dev creature's edits are the same non-commercial exposure the source is
and the studio refuses to render them at all ([[project_licence_gate]]).

THE SOURCE IS NEVER WRITTEN TO.  Bakes land in `<dataset>/studio/`, a category
of their own, with a JSON sidecar each.  Promoting one to hero / anchor lock /
training tile is a separate, explicit act with its own dock icon — because those
three writes change what the NEXT sheet and the NEXT training run are made of.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import threading
import time
import urllib.parse
import uuid
import logging as _zyg_logging

from zyg_workflows import paths

from zyg_workflows.creature_fx.base import (
    _zyg_log,
    HERE,
    DATA,
    RUNTIME,
    PRESETS,
    JOBDIR,
    DS_ROOT,
    OUT_ROOT,
    PROP_ROOT,
    PACKS_ROOT,
    BASE_PACK,
    BASE_PACK_DIR,
    BASES_JSON,
    GEN_PREVIEWS,
    ID_RE,
    NAME_RE,
    IMG_EXT,
    CATS,
    STUDIO_CAT,
    FLUX1_FAMILIES,
    LICENCES,
    PREVIEW_MAX,
    CELL_PX,
    f,
    i,
    b,
    e,
    c,
    s,
    OPS,
    _SEEN,
    _op,
    _edit,
    _pix,
    _act,
    _amt,
    _pick,
)
from zyg_workflows.creature_fx import ops_form
from zyg_workflows.creature_fx import ops_appendages
from zyg_workflows.creature_fx import ops_face
from zyg_workflows.creature_fx import ops_surface
from zyg_workflows.creature_fx.ops_colour import (
    _NAMED,
    colour_word,
    _colclause,
)
from zyg_workflows.creature_fx import ops_condition
from zyg_workflows.creature_fx import ops_gear
from zyg_workflows.creature_fx import ops_pose
from zyg_workflows.creature_fx.ops_camera import (
    _MESH_VIEWS,
    _MESH_VIEW_WORDS,
)
from zyg_workflows.creature_fx import ops_scene
from zyg_workflows.creature_fx import ops_style
from zyg_workflows.creature_fx.ops_pixel import (
    _pil,
    _px_crop,
    _px_scale,
    _px_rot,
    _px_pad,
    _px_enh,
    _px_gamma,
    _px_levels,
    _px_temp,
    _px_tint,
    _px_hue,
    _px_blur,
    _px_usm,
    _px_median,
    _px_vig,
    _px_grain,
    _px_post,
    _px_mono,
    _px_bg,
    _px_flat,
    _px_trim,
    _px_square,
    _px_flip,
    _rgb,
    _rgba,
    _apply_rgb_lut,
)
from zyg_workflows.creature_fx import ops_measure
from zyg_workflows.creature_fx.ops_dock import (
    OP_BY_ID,
)
from zyg_workflows.creature_fx.resolve import (
    _cdir,
    _catdir,
    resolve_image,
    _manifest,
    licence_of,
    _imglist,
    _anchor_path,
    _under,
    mesh_glb_path,
    creature_mesh,
    _asset_url,
    _base_preview,
    base_creatures,
    BASE_CREATURES,
    creature_facts,
    comfy_up,
    _COMFY,
    _ensure_comfy_env,
    _studio_dir,
    _slug,
    list_bakes,
    read_recipe,
    _write_bake,
)
from zyg_workflows.creature_fx.compiler import (
    validate,
    normalise_stack,
    _KEEP_BASE,
    _NEG_BASE,
    _KEEP_DROPS,
    keep_sentence,
    _changing,
    compile_stack,
    apply_pixels,
)
from zyg_workflows.creature_fx.preview import (
    _open,
    _png,
    _checkerboard,
    preview_frame,
    chain_text,
    _ctx,
)
from zyg_workflows.creature_fx.measurement import (
    _tmp_png,
    _phash,
    _hamm,
    measure,
)
from zyg_workflows.creature_fx.render import (
    JOBS,
    _JOBLOCK,
    _job,
    _set,
    job_status,
    recent_jobs,
    start_render,
    _log,
    _render_worker,
    _sha,
    _mesh_control_depth,
    _run_edit,
    _strip_bars,
    _measure_pair,
)
from zyg_workflows.creature_fx.writes import (
    _read_json,
    _write_json,
    _bake_path,
    apply_action,
    pipeline_commands,
)
from zyg_workflows.creature_fx.presets import (
    load_presets,
    save_preset,
    delete_preset,
    ops_payload,
    _BANDS,
)

__all__ = [
    'hashlib',
    'io',
    'json',
    'os',
    're',
    'shutil',
    'threading',
    'time',
    'urllib',
    'uuid',
    '_zyg_logging',
    'paths',
    '_zyg_log',
    'HERE',
    'DATA',
    'RUNTIME',
    'PRESETS',
    'JOBDIR',
    'DS_ROOT',
    'OUT_ROOT',
    'PROP_ROOT',
    'PACKS_ROOT',
    'BASE_PACK',
    'BASE_PACK_DIR',
    'BASES_JSON',
    'GEN_PREVIEWS',
    'ID_RE',
    'NAME_RE',
    'IMG_EXT',
    'CATS',
    'STUDIO_CAT',
    'FLUX1_FAMILIES',
    'LICENCES',
    'PREVIEW_MAX',
    'CELL_PX',
    'f',
    'i',
    'b',
    'e',
    'c',
    's',
    'OPS',
    '_SEEN',
    '_op',
    '_edit',
    '_pix',
    '_act',
    '_amt',
    '_pick',
    'ops_form',
    'ops_appendages',
    'ops_face',
    'ops_surface',
    '_NAMED',
    'colour_word',
    '_colclause',
    'ops_condition',
    'ops_gear',
    'ops_pose',
    '_MESH_VIEWS',
    '_MESH_VIEW_WORDS',
    'ops_scene',
    'ops_style',
    '_pil',
    '_px_crop',
    '_px_scale',
    '_px_rot',
    '_px_pad',
    '_px_enh',
    '_px_gamma',
    '_px_levels',
    '_px_temp',
    '_px_tint',
    '_px_hue',
    '_px_blur',
    '_px_usm',
    '_px_median',
    '_px_vig',
    '_px_grain',
    '_px_post',
    '_px_mono',
    '_px_bg',
    '_px_flat',
    '_px_trim',
    '_px_square',
    '_px_flip',
    '_rgb',
    '_rgba',
    '_apply_rgb_lut',
    'ops_measure',
    'OP_BY_ID',
    '_cdir',
    '_catdir',
    'resolve_image',
    '_manifest',
    'licence_of',
    '_imglist',
    '_anchor_path',
    '_under',
    'mesh_glb_path',
    'creature_mesh',
    '_asset_url',
    '_base_preview',
    'base_creatures',
    'BASE_CREATURES',
    'creature_facts',
    'comfy_up',
    '_COMFY',
    '_ensure_comfy_env',
    'validate',
    'normalise_stack',
    '_KEEP_BASE',
    '_NEG_BASE',
    '_KEEP_DROPS',
    'keep_sentence',
    '_changing',
    'compile_stack',
    'apply_pixels',
    '_open',
    '_png',
    '_checkerboard',
    'preview_frame',
    'chain_text',
    '_ctx',
    '_tmp_png',
    '_phash',
    '_hamm',
    'measure',
    '_studio_dir',
    '_slug',
    'list_bakes',
    'read_recipe',
    '_write_bake',
    'JOBS',
    '_JOBLOCK',
    '_job',
    '_set',
    'job_status',
    'recent_jobs',
    'start_render',
    '_log',
    '_render_worker',
    '_sha',
    '_mesh_control_depth',
    '_run_edit',
    '_strip_bars',
    '_measure_pair',
    '_read_json',
    '_write_json',
    '_bake_path',
    'apply_action',
    'pipeline_commands',
    'load_presets',
    'save_preset',
    'delete_preset',
    'ops_payload',
    '_BANDS',
]
