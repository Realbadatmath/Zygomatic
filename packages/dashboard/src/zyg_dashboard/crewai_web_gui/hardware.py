#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Calibration limits, the GPU power limit, the model and LoRA configuration tables.

Lines 1183-1539 of the original module, verbatim: ``_apply_gpu_power_limit`` and
its application on startup, the subprocess-registry and VRAM-manager re-export
markers, the FLUX pipeline caches, the documentary-cinematic style LoRA switch and
the visual-style LoRA table with its licence provenance.
"""

# ruff: noqa: E402,F401  verbatim move: the original import order is load-bearing,
# and every name here is read back off zyg_dashboard.crewai_web_gui by the bp_* blueprints.

from zyg_dashboard.crewai_web_gui._bootstrap import _agent_log, _backend_debug, _zyg_log, exe, gui_state, runtime
from zyg_dashboard.crewai_web_gui.security import _push_error_log


def _apply_gpu_power_limit(watts: float) -> str:
    """Set GPU 0 hardware power limit via nvidia-smi --power-limit.
    Tries sudo -n first (passwordless sudoers), then direct (root).
    Returns '' on success or error message string."""
    import subprocess as _sp

    # required=False: an unresolved name keeps today's behaviour (subprocess raises
    # FileNotFoundError, the loop below catches it) instead of escaping this function,
    # which must return a message rather than raise.
    _nvsmi = exe('nvidia-smi', required=False) or 'nvidia-smi'
    _sudo = exe('sudo', required=False) or 'sudo'
    cmd_base = [_nvsmi, '--power-limit', str(int(watts)), '--id=0']
    for cmd in ([_sudo, '-n'] + cmd_base, cmd_base):
        try:
            _r = _sp.run(cmd, capture_output=True, text=True, timeout=10)
            if _r.returncode == 0:
                _backend_debug(f'GPU power limit set to {int(watts)}W via nvidia-smi')
                return ''
        except Exception as _exc:
            _zyg_log.debug('power-limit attempt %s failed, trying the next form: %s', cmd[0], _exc)
            continue
    # Both attempts failed — return last stderr
    try:
        _r = _sp.run(cmd_base, capture_output=True, text=True, timeout=10)
        msg = _r.stderr.strip() or _r.stdout.strip() or f'exit {_r.returncode}'
        _backend_debug(
            f'GPU power limit: insufficient permissions ({msg}). Add to sudoers: zygomatic ALL=(ALL) NOPASSWD: /usr/bin/nvidia-smi'
        )
        return msg
    except Exception as e:
        return str(e)


# Apply the calibrated power limit immediately on startup
_apply_gpu_power_limit(gui_state._CALIBRATION['max_gpu_watts'])

# ── Subprocess registry — tracks every ffmpeg/worker PID so stop can kill them ──
from zyg_workflows.runtime import SUBPROC_REGISTRY as _SUBPROC_REGISTRY  # noqa: E402,F401  kept at the old definition site
from zyg_workflows.runtime import SUBPROC_LOCK as _SUBPROC_LOCK  # noqa: E402,F401  kept at the old definition site
from zyg_workflows.runtime import SUBPROC_SYNTHETIC_COUNTER as _SUBPROC_SYNTHETIC_COUNTER  # noqa: E402,F401  kept at the old definition site

# 2026-07-17 heavy-tranche: _register_subproc moved to subproc_registry.py

# 2026-07-17 heavy-tranche: _register_marker moved to subproc_registry.py

# 2026-07-17 heavy-tranche: _update_marker moved to subproc_registry.py
# 2026-07-17 heavy-tranche: _finish_subproc moved to subproc_registry.py

# 2026-07-17 heavy-tranche: _kill_all_subprocs moved to subproc_registry.py


# 2026-07-17 heavy-tranche: _subproc_monitor_loop moved to subproc_registry.py


# 2026-07-17 heavy-tranche: _subproc_monitor_thread moved to subproc_registry.py
# 2026-07-17 heavy-tranche: lines 1927-1927 moved to subproc_registry.py


# 2026-10-05 layering: _ollama_semaphore moved to zyg_workflows.runtime

# Cached FLUX.1-schnell pipeline instance — reused across pipeline runs to avoid reload overhead
gui_state._FLUX_PIPELINE_CACHE = None

# Cached FLUX.1-dev pipeline — used by Storyteller Stage 3.5 and Stage 1d for higher quality
gui_state._FLUX_DEV_PIPELINE_CACHE = None

# 2026-10-05 layering: _char_gen_jobs moved to zyg_workflows.runtime

# 2026-10-05 layering: _creature_gen_jobs moved to zyg_workflows.runtime

# 2026-10-05 layering: _contact_sheet_jobs moved to zyg_workflows.runtime
# 2026-10-05 layering: _CONTACT_SHEET_STATE_FMT moved to zyg_workflows.pipeline_config

# 2026-10-05 layering: _CHAR_STATE_FILENAME_FMT moved to zyg_workflows.pipeline_config


# 2026-07-17 heavy-tranche: _char_state_path moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_save_state moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_stage_start moved to char_state_service.py


# 2026-07-17 heavy-tranche: _char_stage_end moved to char_state_service.py


# 2026-07-17 heavy-tranche: _contact_sheet_state_path moved to char_state_service.py


# 2026-07-17 heavy-tranche: _contact_sheet_save_state moved to char_state_service.py


# 2026-07-17 heavy-tranche: _contact_sheet_emit moved to char_state_service.py


# 2026-07-17 heavy-tranche: _contact_sheet_stage_start moved to char_state_service.py


# 2026-07-17 heavy-tranche: _contact_sheet_stage_end moved to char_state_service.py


# 2026-07-17 heavy-tranche: _contact_sheet_derive_stage moved to char_state_service.py


# 2026-07-17 heavy-tranche: _contact_sheet_worker_alive moved to char_state_service.py


# 2026-07-17 heavy-tranche: _contact_sheet_close_running_timeline moved to char_state_service.py


# 2026-07-17 heavy-tranche: _contact_sheet_orphan_stale_running_job moved to char_state_service.py


# 2026-07-17 heavy-tranche: _contact_sheet_reload_jobs_from_disk moved to char_state_service.py


# 2026-07-17 heavy-tranche: _bg_contact_sheet_pipeline moved to char_state_service.py


# 2026-07-17 heavy-tranche: _contact_sheet_release_vram_on_done moved to char_state_service.py


# 2026-07-17 heavy-tranche: _contact_sheet_release_run_vram moved to char_state_service.py


# 2026-07-17 heavy-tranche: _contact_sheet_resume_run moved to char_state_service.py


# Cached FluxControlNetPipeline — wraps _FLUX_PIPELINE_CACHE with pose conditioning.
# Loaded after FLUX components are on VRAM; total ~30 GB / 48 GB (T5-XXL stays in CPU RAM).
gui_state._CN_PIPE_CACHE = None

# ── documentary-cinematic style LoRA ─────────────────────────────────────────
# The path was wrong: checkpoint-6000/ does not exist. SimpleTuner left the final
# weights at the ROOT of lora-weights/, so every scholarly run since has logged
# "lora_dir LoRA file not found" and rendered with no style LoRA at all.
#
# Fixing the path alone would be a licence regression, so it is OFF by default.
# The LoRA's own README declares base_model "black-forest-labs/FLUX.1-dev",
# license "other" — non-commercial. Renders run on FLUX.1-schnell (Apache-2.0)
# specifically so published episodes stay commercially clean, and a LoRA is
# charged with its BASE model's licence. Loading this one puts a non-commercial
# derivative into monetised output. Opt in only for internal, non-published work:
#   ZYG_FLUX_STYLE_LORA=1
from zyg_workflows.pipeline_config import _FLUX_LORA_DIR  # noqa: E402,F401  kept at the old definition site
from zyg_workflows.pipeline_config import _FLUX_LORA_ENABLED  # noqa: E402,F401  kept at the old definition site
from zyg_workflows.pipeline_config import _FLUX_LORA_PATH  # noqa: E402,F401  kept at the old definition site

# Trained lora_alpha=64 / lora_rank=128 → effective strength 0.5. The export
# carries no alpha keys, so a loader assumes alpha=rank and the nominal scale IS
# the effective one — 0.5 reproduces training, the previous 0.75 was 1.5x it.
from zyg_workflows.pipeline_config import _FLUX_LORA_SCALE  # noqa: E402,F401  kept at the old definition site

# ── Visual Style LoRA config ─────────────────────────────────────────────────
# Each style maps to a LoRA file + scale + prompt prefix/suffix injected into FLUX.
# 'lora' = filename in _STYLE_LORA_DIR, or None for prompt-only styles.
#
# 2026-08-27 — EVERY FILE IN _STYLE_LORA_DIR WAS DELETED ON LICENCE GROUNDS.
# The 'lora' keys below are deliberately LEFT IN PLACE: pipeline_video guards the
# load with os.path.exists() and degrades to the prefix/suffix/claude_hint text,
# which is where most of each style's direction already lived. Keeping the key
# documents the slot a cleared replacement plugs into. Expect one
# "Style LoRA file not found" WARNING per render until one is wired.
#
# What was removed, and why — identified by exact filename + byte-size match
# against the source repo, not by assumption:
#   anime / art / disney / mjv6 / realism / scenery
#       -> XLabs-AI/flux-lora-collection, license_name = flux-1-dev-non-commercial-license
#   3d_render_lora  -> goofyai/3D_Render_for_flux; repo tags itself apache-2.0 but the
#       file's own header says modelspec.architecture = flux-1-dev/lora. An uploader's
#       tag does not override the base model's terms, so it was treated as NC.
#   filmic_lora     -> header ss_output_name = flux_dev_flmft5, FLUX tensor layout.
#   style_lora      -> header modelspec.architecture = flux-1-dev/lora (the amateurphoto
#       LoRA staged under a second name).
#   style_arcane    -> trained on sd_xl_base_0.9_half. SDXL 0.9 is the SDXL RESEARCH
#       licence, NOT the OpenRAIL++-M of SDXL 1.0: it grants use "solely for your
#       non-commercial research purposes" and separately bars using the Software
#       "or any data produced by the Software" for "any commercial or production
#       purposes" — an OUTPUT restriction, which is why it mattered more than the rest.
#
# Verified Apache-2.0/MIT replacements on the Qwen-Image base (licence read from the
# HF API, not recalled). All are LoRAs for Qwen, so they need the Qwen render path,
# not the retired FLUX one:
#   realism   -> flymy-ai/qwen-image-realism-lora            (apache-2.0)
#   anime     -> prithivMLmods/Qwen-Image-Anime-LoRA         (apache-2.0)
#                alfredplpl/qwen-image-modern-anime-lora     (apache-2.0)
#                autoweeb/Qwen-Image-Edit-2509-Photo-to-Anime (mit)
#   disney    -> furaidosu/masha2d-cartoon-qwen-image-lora   (apache-2.0)
#   art/scenery/filmic -> dx8152/Qwen-Image-Edit-2511-Style-Transfer (apache-2.0)
#                         strangerzonehf/Qwen-Image-Edit-LoRA-Collection (apache-2.0)
#   NO cleanly-licensed ARCANE LoRA was found. Every candidate was either a FLUX-dev
#   derivative wearing an openrail++ tag (the 3d_render trap again) or carried no
#   licence at all. Arcane needs either a Qwen style-transfer reference image you own,
#   or a LoRA trained in-house on licensed material.
from zyg_workflows.pipeline_config import _STYLE_LORA_DIR  # noqa: E402,F401  kept at the old definition site
from zyg_workflows.pipeline_config import _STYLE_LORA_CONFIG  # noqa: E402  kept at the old definition site

_VALID_VISUAL_STYLES = frozenset(_STYLE_LORA_CONFIG.keys())
# ─────────────────────────────────────────────────────────────────────────────


# 2026-10-05 layering: _LargeModelLock moved to zyg_workflows.runtime


# 2026-10-05 layering: _large_llm_semaphore moved to zyg_workflows.runtime

# 2026-10-05 layering: _MODEL_VRAM_GB moved to zyg_workflows.pipeline_config
# 2026-10-05 layering: _LARGE_MODEL_THRESHOLD_GB moved to zyg_workflows.pipeline_config


# 2026-07-17 heavy-tranche: _get_free_vram_gb moved to vram_manager.py


# 2026-07-17 heavy-tranche: _wait_for_vram moved to vram_manager.py


# 2026-07-17 heavy-tranche: _ensure_comfy_offload_env moved to vram_manager.py


# 2026-07-17 heavy-tranche: _deep_unload_flux_pipeline_cache moved to vram_manager.py


# 2026-07-17 heavy-tranche: _evict_all_ollama_models moved to vram_manager.py


# 2026-07-17 heavy-tranche: _ollama_loaded_vram_mb moved to vram_manager.py


# 2026-07-17 heavy-tranche: _release_pipeline_vram moved to vram_manager.py


# 2026-07-17 heavy-tranche: _stop_secondary_flask_dashboards moved to vram_manager.py


# 2026-07-17 heavy-tranche: _enforce_gpu_exclusivity_before_stage35 moved to vram_manager.py


# 2026-07-17 heavy-tranche: _workflow_job_gpu_active moved to vram_manager.py


# 2026-07-17 heavy-tranche: _char_gen_worker_alive moved to vram_manager.py


# 2026-07-17 heavy-tranche: _gpu_work_active moved to vram_manager.py


# 2026-07-17 heavy-tranche: _comfy_server_pid moved to vram_manager.py


# 2026-07-17 heavy-tranche: _comfy_vram_used_mb moved to vram_manager.py


# 2026-07-17 heavy-tranche: _startup_vram_sweep moved to vram_manager.py


# 2026-07-17 heavy-tranche: _comfy_idle_vram_sweeper_loop moved to vram_manager.py


# 2026-07-17 heavy-tranche: _wait_for_hardware_headroom moved to vram_manager.py


# 2026-07-17 heavy-tranche: _wait_ollama_unload moved to vram_manager.py


# 2026-07-17 heavy-tranche: _read_safety_thresholds moved to vram_manager.py


# 2026-07-17 heavy-tranche: _check_hardware_now moved to vram_manager.py


# 2026-07-17 heavy-tranche: _hw_monitor_loop moved to vram_manager.py


# 2026-10-05 layering: _AGENT_LOG_LOCK moved to zyg_workflows.runtime


# 2026-10-05 layering: _agent_log moved to zyg_workflows.runtime


runtime.register(agent_log=_agent_log, push_error_log=_push_error_log)


# 2026-07-17 heavy-tranche: _log_prompt moved to stage_runner.py


# ── Documentary Framework Helpers ────────────────────────────────────────────

# 2026-07-17 heavy-tranche: _classify_subject_type moved to stage_runner.py


# 2026-07-17 heavy-tranche: _build_framework_block moved to stage_runner.py


# 2026-07-17 heavy-tranche: _register_prompt moved to stage_runner.py


# 2026-07-17 heavy-tranche: _run_stage_agent moved to stage_runner.py


# 2026-10-05 layering: _PUBLISH_STAGE_NAME moved to zyg_workflows.pipeline_config
# 2026-10-05 layering: _UPLOAD_AGENTS moved to zyg_workflows.pipeline_config


# 2026-07-17 heavy-tranche: _pf_agents_active moved to stage_runner.py


# 2026-07-17 heavy-tranche: _pf_agents_done moved to stage_runner.py


# 2026-07-17 heavy-tranche: _stage_preflight moved to stage_runner.py


# 2026-07-17 heavy-tranche: _build_task_desc moved to stage_runner.py


# 2026-07-17 heavy-tranche: _load_workflow_overrides moved to stage_runner.py


# 2026-07-17 heavy-tranche: _check_workflow_health moved to stage_runner.py


# 2026-07-17 heavy-tranche: _scp_output_to_windows moved to stage_runner.py


# 2026-07-17 heavy-tranche: _run_clipfarm_pipeline moved to pipeline_clipfarm.py


# 2026-07-17 heavy-tranche: _run_crime_pipeline moved to pipeline_crime.py

from zyg_workflows.color_grade import _LUT_DIR  # noqa: E402,F401  kept at the old definition site

from zyg_workflows.color_grade import _STYLE_LUT_MAP  # noqa: E402,F401  kept at the old definition site

# documentary visual_style falls through to the documentary pipeline; for video
# pipeline with no explicit style, default to cinematic.
from zyg_workflows.color_grade import _DEFAULT_LUT  # noqa: E402,F401  kept at the old definition site


from zyg_workflows.color_grade import _apply_color_grade  # noqa: E402,F401  kept at the old definition site


# 2026-07-17 heavy-tranche: _parse_pipeline_model_family moved to pipeline_common.py


# 2026-07-17 heavy-tranche: _resolve_video_timing moved to pipeline_common.py


# 2026-07-17 heavy-tranche: _normalize_pipeline_options moved to pipeline_common.py


# 2026-10-06 round-2 split: _start_scholarly_pipeline_internal and its
# _start_crime_pipeline_internal alias moved to zyg_dashboard.gui.scholarly
