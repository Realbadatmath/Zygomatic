# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""movement_studio.py — Movement Studio option surface: the full VACE motion console.

Same shape as video_studio.py and voice_studio.py: a declarative RACKS spec the
GUI builds its icon bars from, ACTIONS for the non-parameter buttons,
sanitize() clamping whatever a caller sends, compose_prompt() building the exact
motion sentence the render will use, and render_kwargs() mapping the whole dial
state onto generate_vace_static_clip()'s signature.

── 2026-09-02: why this file exists ──────────────────────────────────────────
Movement Studio shipped (2026-08-31) with EIGHT motion presets and two frame
counts. Everything else generate_vace_static_clip exposes — the shift lever this
project spent a fortnight measuring, the two VACE pin percentages, the context
window set, the LoRA chain, the mask region count, the identity ref seat — was
hard-coded in bp_movement._run_job. That is a console with one knob on it.

DISCIPLINE — no inert levers. Every key below reaches something real, and the
comment on it names WHAT:
  * generate_vace_static_clip kwargs → steps/cfg/shift/seed/num_frames/width/
    height/vace_*/neutral_control/n_regions/interpolate/extra_negative/loras/
    ref_images_paths/context_*/fuse_method/pin_regions
  * prompt builder                   → compose_prompt() below, whose output IS
    the motion_prompt the render submits (never a second, prettier copy)
  * process environment              → the five ZYG_* switches wan_vace_service
    reads at graph-build time, applied per job under bp_movement's one-job lock
    and restored afterwards (see _ENV_KEYS)
Options that could NOT be wired against this stack were left OUT rather than
drawn as placeholders — see MISSING at the bottom of this file.

The ACTION LIBRARY (ACTIONS_LIB) is the other half of the ask: the eight canned
motions became forty, each with its own icon, each a real prompt string. That
list is the "movement library" the rest of the console modifies.
"""

import json
import os
import logging as _zyg_logging
from zyg_workflows import paths

from zyg_workflows.movement_studio.options import (
    HERE,
    _OUT_ROOT,
    _PRESET_DIR,
    _LORA_ROOT,
    _lora_options,
    _lora2_options,
    _object_options,
    _plate_view_options,
    _SHOTS_ROOT,
    _plateset_options,
    RESOLUTIONS,
)
from zyg_workflows.movement_studio.actions_lib import (
    ACTIONS_LIB,
    _ACTION_BY_ID,
    action_prompt,
)
from zyg_workflows.movement_studio import racks_bar_motion
from zyg_workflows.movement_studio import racks_bar_language
from zyg_workflows.movement_studio import racks_rail
from zyg_workflows.movement_studio.params import (
    RACKS,
    ACTIONS,
    _PARAMS,
    defaults,
    sanitize,
    nondefault,
)
from zyg_workflows.movement_studio.prompt import (
    _SPEED,
    _INTENSITY,
    _AMPLITUDE,
    _STYLE,
    _EASING,
    _REPEAT,
    _HOLD_START,
    _HOLD_END,
    _DIRECTION,
    _DISTANCE,
    _FACING,
    _SCALE,
    _GROUND,
    _LEAD,
    _HEAD,
    _GAZE,
    _MOUTH,
    _HANDS,
    _POSTURE,
    _BREATH,
    _WEIGHT,
    _clauses,
    _decorate,
    compose_prompt,
)
from zyg_workflows.movement_studio.render import (
    lora_chain,
    _pin_regions,
    plateset_dir,
    plateset_meta,
    still_for,
    render_kwargs,
)
from zyg_workflows.movement_studio.plates import (
    _PLATE_DIR,
    _PLATE_KINDS,
    _plate_log,
    resolve_view,
    build_plate,
    _typed_box,
    auto_box,
    prop_plates,
    plate_chip,
)
from zyg_workflows.movement_studio.control import (
    _is_frame_dir,
    control_kwargs,
    _ENV_KEYS,
    env_overrides,
)
from zyg_workflows.movement_studio.presets import (
    presets,
    _safe_name,
    preset_load,
    preset_save,
    preset_delete,
    spec,
)

_zyg_log = _zyg_logging.getLogger(__name__)


# ── re-export surface ─────────────────────────────────────────────────────────
# Every name below is imported above and not used in this module: this file
# exists so that ``zyg_workflows.movement_studio.<name>``
# resolves exactly as it did on the pre-split single-file module.
# Nothing does ``import *`` from here.
__all__ = [
    'json',
    'os',
    'paths',
    'HERE',
    '_OUT_ROOT',
    '_PRESET_DIR',
    '_LORA_ROOT',
    '_lora_options',
    '_lora2_options',
    '_object_options',
    '_plate_view_options',
    '_SHOTS_ROOT',
    '_plateset_options',
    'RESOLUTIONS',
    'ACTIONS_LIB',
    '_ACTION_BY_ID',
    'action_prompt',
    'racks_bar_motion',
    'racks_bar_language',
    'racks_rail',
    'RACKS',
    'ACTIONS',
    '_PARAMS',
    'defaults',
    'sanitize',
    'nondefault',
    '_SPEED',
    '_INTENSITY',
    '_AMPLITUDE',
    '_STYLE',
    '_EASING',
    '_REPEAT',
    '_HOLD_START',
    '_HOLD_END',
    '_DIRECTION',
    '_DISTANCE',
    '_FACING',
    '_SCALE',
    '_GROUND',
    '_LEAD',
    '_HEAD',
    '_GAZE',
    '_MOUTH',
    '_HANDS',
    '_POSTURE',
    '_BREATH',
    '_WEIGHT',
    '_clauses',
    '_decorate',
    'compose_prompt',
    'lora_chain',
    '_pin_regions',
    'plateset_dir',
    'plateset_meta',
    'still_for',
    'render_kwargs',
    '_PLATE_DIR',
    '_PLATE_KINDS',
    '_plate_log',
    'resolve_view',
    'build_plate',
    '_typed_box',
    'auto_box',
    'prop_plates',
    'plate_chip',
    '_is_frame_dir',
    'control_kwargs',
    '_ENV_KEYS',
    'env_overrides',
    'presets',
    '_safe_name',
    'preset_load',
    'preset_save',
    'preset_delete',
    'spec',
]
