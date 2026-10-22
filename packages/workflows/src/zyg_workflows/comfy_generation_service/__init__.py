# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
comfy_generation_service.py
=============================
ComfyUI execution subsystem for character-locked still generation.

Scholarly Stage 3.5 production default is **in-process diffusers**
(``scholarly_stills_backend.SCHOLARLY_PRODUCTION_BACKEND``). This module is
used for Comfy only when ``ZYG_SCHOLARLY_COMFY_IMAGES=1`` (heavy character
curation / HandFixer) or when ``ZYG_COMFY_PRIMARY=1`` routes non-scholarly work.

Falls back to diffusers when Comfy is disabled, unreachable, or errors.
"""

# Pattern A package split of the former 2,456-line comfy_generation_service.py.
# Submodules are listed in the original section order and every public and underscore
# name the single module defined is re-exported, so the import path
# zyg_workflows.comfy_generation_service is unchanged for every importer.

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
import time as _time_cb
from typing import Any, Callable

from zyg_workflows import comfy_generation_service_steps as _steps
from zyg_workflows import paths
from zyg_workflows.bin import exe

from zyg_workflows.comfy_generation_service import constants as constants
from zyg_workflows.comfy_generation_service.constants import (
    _HF_REVISION,
    _neg_log,
    _zyg_log,
    _comfy,
    _bible,
    _cqa,
    _FLUX_DEV,
    _FLUX_SCHNELL,
    _SDXL_TRAIN_REPO_ID,
    _SDXL_ALIGNED_CKPT,
    _SDXL_FALLBACK_CKPT,
    _SDXL_ANIMATED_CKPT,
    _SDXL_IMG2IMG_DENOISE,
    _CHAR_DRIFT_MIN,
    _CHAR_DRIFT_ANIMATED,
    _PREVIEW_LORA_SCALE,
    _PREVIEW_SDXL_STEPS,
    _SKIN_PORE_FACE_WILDCARD,
    _PREVIEW_FACE_PORE_DENOISE,
    _SMILE_FACE_WILDCARD,
    _HAND_DETAIL_WILDCARD,
    _COMFY_ROOT,
    _COMFY_LORA_DIR,
    _IPA_SCALE_DEFAULT,
    _log_default,
)
from zyg_workflows.comfy_generation_service import backend as backend
from zyg_workflows.comfy_generation_service.backend import (
    _clear_vram_between_slots_enabled,
    _gpu_used_mb_total,
    clear_vram_between_slots,
    is_primary_backend,
    _CB_LOCK,
    _CB_TRIP_AFTER,
    _CB_OPEN_SECONDS,
    _CB_RESTART_COOLDOWN_S,
    _CB_WEDGE_SIGNATURES,
    _cb_consec_failures,
    _cb_open_until,
    _cb_last_auto_restart,
    _cb_record_success,
    _cb_record_failure,
    is_available,
)
from zyg_workflows.comfy_generation_service import capabilities as capabilities
from zyg_workflows.comfy_generation_service.capabilities import (
    pick_scholarly_anatomy_workflow,
    has_flux_ipadapter,
    has_pulid_flux,
    qwen_edit_unet,
    qwen_t2i_unet,
    has_qwen_t2i,
    klein_t2i_unet,
    klein_is_distilled,
    klein_text_encoder,
    klein_vae,
    _KLEIN_CONTROL_LORA,
    klein_control_lora_name,
    klein_control_lora_scale,
    has_klein_refcontrol,
    has_klein_t2i,
    _graph_is_klein,
    klein_missing_parts,
    has_qwen_hand_inpaint,
    qwen_edit_angles_lora_name,
    has_qwen_edit_angles,
    _UNION_CN_FILE,
    _POSE_DIR,
    has_flux_union_pose_controlnet,
    pose_locked_stack_ready,
    pose_map_path,
)
from zyg_workflows.comfy_generation_service import flux_graph as flux_graph
from zyg_workflows.comfy_generation_service.flux_graph import (
    _flux_rewire_without_lora,
    _trim_prompt_at_clause,
    _split_flux_dual_prompt,
    _workflow_uses_flux_clip_encode,
    _patch_flux_sampler,
    has_instantid,
    has_face_detailer,
    _sam_model_path,
    _face_yolo_path,
    _hand_yolo_path,
    _HAND_YOLO_URL,
    ensure_hand_yolo_weights,
    sam_face_stack_ready,
    hand_detailer_stack_ready,
)
from zyg_workflows.comfy_generation_service import hand_fixer as hand_fixer
from zyg_workflows.comfy_generation_service.hand_fixer import (
    _FLUX_FILL_UNET,
    _HAND_FIXER_STEPS,
    _HAND_FIXER_GUIDANCE,
    _HAND_FIXER_PROMPT,
    hand_fixer_enabled,
    _flux_fill_unet_path,
    hand_fixer_stack_ready,
    _hand_boxes_for_fix,
    apply_hand_fixer_pass,
    _apply_hand_fixer_pass_inner,
    _maybe_recover_sharpness_after_inpaint,
    _patch_workflow_sam_loader,
    _strip_face_detailer,
    _strip_hand_detailer,
)
from zyg_workflows.comfy_generation_service import prompts as prompts
from zyg_workflows.comfy_generation_service.prompts import (
    build_locked_prompt,
    _resize_init_for_latent,
    _dedupe_negative_clauses,
    build_locked_negative_prompt,
)
from zyg_workflows.comfy_generation_service import style as style
from zyg_workflows.comfy_generation_service.style import (
    _resolve_unet,
    _normalize_model_family,
    ensure_sdxl_comfy_checkpoint,
    _render_style_from_package,
    _is_photoreal_render_style,
    _restyle_profile_from_package,
    _RESTYLE_POS_STRIP,
    _RESTYLE_NEG_STRIP,
    _NONHUMAN_NEG_STRIP,
    _ALPHA_CACHE,
    lora_has_alpha,
    default_lora_scale,
    _strip_clause_tokens,
    _append_render_style_negatives,
    _lora_path_matches_model_family,
)
from zyg_workflows.comfy_generation_service import workflows as workflows
from zyg_workflows.comfy_generation_service.workflows import (
    _resolve_checkpoint_sdxl,
    _workflow_template_exists,
    _stage_style_lora,
    _char_id_from_lora_path,
    _stage_character_lora,
    _pick_workflow,
    _drift_threshold_for_package,
)
from zyg_workflows.comfy_generation_service import generate as generate
from zyg_workflows.comfy_generation_service.generate import (
    _NEG_LOGGED_ONCE,
    _post_save,
    generate_still,
)
from zyg_workflows.comfy_generation_service import preview as preview
from zyg_workflows.comfy_generation_service.preview import (
    try_generate_still_with_fallback,
    generate_character_preview_still,
)

# ── re-export surface ────────────────────────────────────────────────────────
# Every name above is imported for re-export, not for use in this file: the
# pipelines and the character services read them off this module with
# ``from zyg_workflows.comfy_generation_service import X``, which is what keeps
# the import path of the pre-split single module unchanged. Declaring them is
# what makes the re-export deliberate rather than an unused import; nothing does
# ``import *`` from here, so __all__ changes no behaviour.
__all__ = [
    'logging',
    'os',
    're',
    'shutil',
    'subprocess',
    'threading',
    '_time_cb',
    'Any',
    'Callable',
    '_steps',
    'paths',
    'exe',
    'constants',
    '_HF_REVISION',
    '_neg_log',
    '_zyg_log',
    '_comfy',
    '_bible',
    '_cqa',
    '_FLUX_DEV',
    '_FLUX_SCHNELL',
    '_SDXL_TRAIN_REPO_ID',
    '_SDXL_ALIGNED_CKPT',
    '_SDXL_FALLBACK_CKPT',
    '_SDXL_ANIMATED_CKPT',
    '_SDXL_IMG2IMG_DENOISE',
    '_CHAR_DRIFT_MIN',
    '_CHAR_DRIFT_ANIMATED',
    '_PREVIEW_LORA_SCALE',
    '_PREVIEW_SDXL_STEPS',
    '_SKIN_PORE_FACE_WILDCARD',
    '_PREVIEW_FACE_PORE_DENOISE',
    '_SMILE_FACE_WILDCARD',
    '_HAND_DETAIL_WILDCARD',
    '_COMFY_ROOT',
    '_COMFY_LORA_DIR',
    '_IPA_SCALE_DEFAULT',
    '_log_default',
    'backend',
    '_clear_vram_between_slots_enabled',
    '_gpu_used_mb_total',
    'clear_vram_between_slots',
    'is_primary_backend',
    '_CB_LOCK',
    '_CB_TRIP_AFTER',
    '_CB_OPEN_SECONDS',
    '_CB_RESTART_COOLDOWN_S',
    '_CB_WEDGE_SIGNATURES',
    '_cb_consec_failures',
    '_cb_open_until',
    '_cb_last_auto_restart',
    '_cb_record_success',
    '_cb_record_failure',
    'is_available',
    'capabilities',
    'pick_scholarly_anatomy_workflow',
    'has_flux_ipadapter',
    'has_pulid_flux',
    'qwen_edit_unet',
    'qwen_t2i_unet',
    'has_qwen_t2i',
    'klein_t2i_unet',
    'klein_is_distilled',
    'klein_text_encoder',
    'klein_vae',
    '_KLEIN_CONTROL_LORA',
    'klein_control_lora_name',
    'klein_control_lora_scale',
    'has_klein_refcontrol',
    'has_klein_t2i',
    '_graph_is_klein',
    'klein_missing_parts',
    'has_qwen_hand_inpaint',
    'qwen_edit_angles_lora_name',
    'has_qwen_edit_angles',
    '_UNION_CN_FILE',
    '_POSE_DIR',
    'has_flux_union_pose_controlnet',
    'pose_locked_stack_ready',
    'pose_map_path',
    'flux_graph',
    '_flux_rewire_without_lora',
    '_trim_prompt_at_clause',
    '_split_flux_dual_prompt',
    '_workflow_uses_flux_clip_encode',
    '_patch_flux_sampler',
    'has_instantid',
    'has_face_detailer',
    '_sam_model_path',
    '_face_yolo_path',
    '_hand_yolo_path',
    '_HAND_YOLO_URL',
    'ensure_hand_yolo_weights',
    'sam_face_stack_ready',
    'hand_detailer_stack_ready',
    'hand_fixer',
    '_FLUX_FILL_UNET',
    '_HAND_FIXER_STEPS',
    '_HAND_FIXER_GUIDANCE',
    '_HAND_FIXER_PROMPT',
    'hand_fixer_enabled',
    '_flux_fill_unet_path',
    'hand_fixer_stack_ready',
    '_hand_boxes_for_fix',
    'apply_hand_fixer_pass',
    '_apply_hand_fixer_pass_inner',
    '_maybe_recover_sharpness_after_inpaint',
    '_patch_workflow_sam_loader',
    '_strip_face_detailer',
    '_strip_hand_detailer',
    'prompts',
    'build_locked_prompt',
    '_resize_init_for_latent',
    '_dedupe_negative_clauses',
    'build_locked_negative_prompt',
    'style',
    '_resolve_unet',
    '_normalize_model_family',
    'ensure_sdxl_comfy_checkpoint',
    '_render_style_from_package',
    '_is_photoreal_render_style',
    '_restyle_profile_from_package',
    '_RESTYLE_POS_STRIP',
    '_RESTYLE_NEG_STRIP',
    '_NONHUMAN_NEG_STRIP',
    '_ALPHA_CACHE',
    'lora_has_alpha',
    'default_lora_scale',
    '_strip_clause_tokens',
    '_append_render_style_negatives',
    '_lora_path_matches_model_family',
    'workflows',
    '_resolve_checkpoint_sdxl',
    '_workflow_template_exists',
    '_stage_style_lora',
    '_char_id_from_lora_path',
    '_stage_character_lora',
    '_pick_workflow',
    '_drift_threshold_for_package',
    'generate',
    '_NEG_LOGGED_ONCE',
    '_post_save',
    'generate_still',
    'preview',
    'try_generate_still_with_fallback',
    'generate_character_preview_still',
]
