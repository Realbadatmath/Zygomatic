# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401, E402
"""Named steps lifted out of ``bp_pipeline_api``'s two giant route bodies.

2026-10-05 quality pass. ``kanban_status`` had grown to 1,135 lines and
``api_pipeline_test`` to 572, both of them a single flat route body holding the
whole kanban card-title taxonomy and the whole health-check suite inline. The
move is PURE: every block below is the same code, in the same order, with the
values it used to read from the enclosing scope passed in as explicit
arguments, so the same inputs still produce the same payload. The route
functions in ``bp_pipeline_api`` keep their public signatures — callers and
``tests/test_kanban_multi_department.py`` depend on them — and the blocks those
tests read as source text (the active-job pick, ``concurrent_runs``,
``_other_runs``, the live payload dict) deliberately stayed behind there.

This module is import-safe on its own: it imports only ``zyg_workflows``, never
``crewai_web_gui``, so it cannot take part in the GUI's bottom-of-file circular
import. Everything the GUI owns (``_workflow_jobs``, ``_runtime_path``,
``_RUNTIME_DIR``, the LoRA constants, ``_runtime_payload``) arrives as a
parameter.
"""

# The original top import block, re-done so old attribute accesses on this
# module (``_steps.os``, ``_steps.json``, …) still resolve.
import json
import logging as _zyg_logging
import os

from zyg_workflows import paths
from zyg_workflows.bin import exe
from zyg_workflows.char_state_service import (
    _char_derive_pipeline_stage,
    _contact_sheet_derive_stage,
    _creature_derive_pipeline_stage,
    _normalize_char_model_family,
)
from zyg_workflows.pipeline_common import _parse_pipeline_model_family

# The sections, in their original order, so module-level side effects still
# run in the order the single file ran them in.
from .stage_maps import (
    _zyg_log,
    _FLUX_SCHNELL_DIR,
    _COMFY_CHECKPOINTS_DIR,
    _REALESRGAN_WEIGHTS,
    _SPORTS_VIDEO_STATUS,
    _HOME_DIR,
    _HF_HOME_DEFAULT,
    _MEL_WIRED_CHILDREN,
    _MEL_WIRED_CINEMATIC,
    KANBAN_STAGE_MAP_DOCUMENTARY,
    KANBAN_STAGE_MAP_VIDEO,
    KANBAN_STAGE_MAP_MANGA,
    KANBAN_STAGE_MAP_STORYTELLER_SDXL,
    KANBAN_STAGE_MAP_STORYTELLER_FLUX,
    KANBAN_STAGE_MAP_CLIPFARM,
    KANBAN_STAGE_MAP_ENVIRONMENTS,
    KANBAN_STAGE_MAP_EFFECTS,
    KANBAN_STAGE_MAP_WARDROBE,
    KANBAN_STAGE_MAP_KIDSMUSIC,
    KANBAN_STAGE_MAP_REMIX_AI,
    KANBAN_STAGE_MAP_REMIX,
    KANBAN_STAGE_MAP_FINANCE,
    KANBAN_STAGE_MAP_SPORTSBET,
    KANBAN_STAGE_MAP_ASSETLIB,
    _step_stage_map_for_department,
)

from .kanban_steps import (
    _step_debug_event_lines,
    _step_hydrate_job_caches,
    _step_pick_contact_sheet_job,
    _step_contact_sheet_payload,
    _step_pick_char_job,
    _step_char_payload,
    _step_pick_creature_job,
    _step_creature_payload,
    _step_creature_stage_and_cards,
    _step_standalone_video_payload,
    _normalize_timeline_status,
    _step_timeline_lookup,
    _step_resolve_board_cards,
    _step_peer_run,
    _step_live_tail,
    _step_sports_video_status,
)

from .health_checks import (
    _chk_anthropic,
    _chk_anthropic_key_only,
    _chk_flux_weights,
    _chk_wan_service,
    _chk_tts,
    _chk_mediapipe,
    _chk_ffmpeg,
    _chk_yolo,
    _chk_cv2,
    _chk_diffusers,
    _chk_cuda,
    _chk_character_bible,
    _chk_comfy_generation,
    _chk_consistency_qa,
    _chk_flux_fill_service,
    _chk_object_track_service,
    _chk_rife_service,
    _chk_audio_service,
    _chk_musicgen_service,
    _chk_output_dir,
    _chk_lora_weights,
    _chk_wan_weights,
    _chk_vllm,
    _chk_snac,
    _chk_ipadapter_weights,
    _chk_controlnet_weights,
    _chk_disk_space,
    _chk_ram,
    _chk_controlnet_service,
    _chk_ipadapter_service,
    _chk_esrgan_model,
    _chk_soundfile,
    pipeline_test_tasks,
)
