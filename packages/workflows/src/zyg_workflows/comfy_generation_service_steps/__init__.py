# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
comfy_generation_service_steps.py
=================================
The ordered steps of :func:`comfy_generation_service.generate_still`, extracted
verbatim so the orchestrator stays readable.

This is a PURE MOVE: every step keeps the inputs, outputs, side effects and
ordering it had inside the single 1,329-line function. Nothing here is meant to
be called from outside ``comfy_generation_service``; the public entry point is
still ``generate_still``.

The parent module is imported lazily inside each step (``_svc()``) rather than
at module scope: the service imports this module, so a top-level import would
be a cycle — and going through the module object also keeps the service's
monkeypatchable globals (``_comfy``, ``_bible``, the ``ZYG_*`` constants) live
rather than snapshotting them at import time.
"""

from __future__ import annotations

# ── comfy_generation_service_steps.py became comfy_generation_service_steps/ ──
# Pattern A: the import path `zyg_workflows.comfy_generation_service_steps` is unchanged and
# every name the single file defined — public and underscore — is re-exported below from the
# module that now holds it, in the original section order. The parent service keeps reaching
# the steps through this module object (`_steps.<step>`), so nothing in it needs editing.

import logging
import os
import shutil
from dataclasses import dataclass, field
from typing import Any, Callable

from .preflight import (  # noqa: F401
    _zyg_log,
    _svc,
    StillRenderCtx,
    flux_licence_paused,
    compose_prompts,
    resolve_unet_and_sampling,
    stage_medusa_base_lora,
    stage_character_lora_for_family,
    select_workflow,
    qwen_edit_resolution_cap,
)
from .graph_config import (  # noqa: F401
    configure_detailer_passes,
    apply_prompt_and_sampler,
    apply_model_nodes,
    apply_face_detailer_patch,
    apply_hand_detailer_patch,
)
from .overrides import (  # noqa: F401
    _set_node13_lora,
    _cond_scale,
    apply_workflow_overrides,
    _branch_flux_img2img,
    _branch_flux_character_ipadapter,
    _branch_flux_pulid_cell,
    _branch_klein_refcontrol,
    _branch_klein_edit,
    _branch_qwen_edit_angle,
    _branch_flux_pose_ipa_cell,
    _branch_flux_pose_instantid_cell,
    _branch_flux_pose_ipa_i2i_cell,
    _branch_medusa_base,
    _branch_flux_character_instantid,
)
from .submit import (  # noqa: F401
    log_submission,
    submit_render,
    save_render_output,
    apply_render_time_restyle,
    run_hand_fixer_stage,
    hand_fix_render_crop,
)


# Every name below is imported above and not used in this module: this package
# IS the re-export surface of the pre-split module, so the imports are the
# deliberate public surface, not dead weight.  Nothing does ``import *`` from
# here, so __all__ changes no behaviour.
__all__ = [
    'logging',
    'os',
    'shutil',
    'dataclass',
    'field',
    'Any',
    'Callable',
    '_zyg_log',
    '_svc',
    'StillRenderCtx',
    'flux_licence_paused',
    'compose_prompts',
    'resolve_unet_and_sampling',
    'stage_medusa_base_lora',
    'stage_character_lora_for_family',
    'select_workflow',
    'qwen_edit_resolution_cap',
    'configure_detailer_passes',
    'apply_prompt_and_sampler',
    'apply_model_nodes',
    'apply_face_detailer_patch',
    'apply_hand_detailer_patch',
    '_set_node13_lora',
    '_cond_scale',
    'apply_workflow_overrides',
    '_branch_flux_img2img',
    '_branch_flux_character_ipadapter',
    '_branch_flux_pulid_cell',
    '_branch_klein_refcontrol',
    '_branch_klein_edit',
    '_branch_qwen_edit_angle',
    '_branch_flux_pose_ipa_cell',
    '_branch_flux_pose_instantid_cell',
    '_branch_flux_pose_ipa_i2i_cell',
    '_branch_medusa_base',
    '_branch_flux_character_instantid',
    'log_submission',
    'submit_render',
    'save_render_output',
    'apply_render_time_restyle',
    'run_hand_fixer_stage',
    'hand_fix_render_crop',
]
