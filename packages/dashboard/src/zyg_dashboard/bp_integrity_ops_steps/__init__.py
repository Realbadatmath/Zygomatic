# ruff: noqa: F401,E402
# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Integrity-gate steps — the check bodies extracted from `api_integrity_gate`.

Pure move out of `bp_integrity_ops.api_integrity_gate` (2026-10-05): every nested
check closure became a module-level `_step_*` function taking explicit arguments,
the check table became `build_tasks()`, and the orchestration tail became
`run_checks()` / `job_stats()` / `circuit_breaker()` / `last_pipeline()` /
`summary()`. No check changed its logic, its order in the table, or its
pass/warn/fail wording.

Same contract as `bp_integrity_ops`: imported only once `crewai_web_gui` has built
its globals, i.e. from `bp_integrity_ops`, which `crewai_web_gui` imports at its
bottom.

Every check is cheap: file stats, local HTTP, cached imports; no model loads and
no billed API calls (the endpoint refreshes every 20 s).
"""

from zyg_dashboard.bp_integrity_ops_steps.constants import (
    _COMFY_MODELS,
    _COMFY_ROOT,
    _FLUX_DEV_GLOBS,
    _FLUX_DEV_HF_REPOS,
    _GPU_HOLDER_LABELS,
    _HF_HUB,
    _RUNTIME_DIR,
    _SDXL_CHECKPOINTS,
    _STYLE_LORA_DIR,
    _cf_ig,
    _comfy_files,
    _env_on,
    _first_model,
    _g,
    _gpu_work_active,
    _hf_weight_files,
    _main_mod,
    _qwen_t2i_unet,
    _runtime_path,
    _shu_ig,
    _zyg_log,
    _zyg_logging,
    exe,
    functools,
    json,
    os,
    paths,
    re,
    subprocess,
)
from zyg_dashboard.bp_integrity_ops_steps.steps_stack import (
    _step_ace_step,
    _step_anatomy_repair,
    _step_anthropic_api,
    _step_asr_whisper,
    _step_comfyui_server,
    _step_diarizer,
    _step_esrgan,
    _step_flux_schnell,
    _step_hand_fixer,
    _step_hw_cuda_driver,
    _step_hw_disk,
    _step_hw_ram,
    _step_hw_vram,
    _step_infra_audio_svc,
    _step_klein,
    _step_ollama_model_check,
    _step_ollama_service,
    _step_qwen_edit,
    _step_qwen_t2i,
    _step_rife,
    _step_sageattention,
    _step_sdxl,
    _step_tts_engines,
    _step_wan22,
    _step_wan_animate,
    _step_wan_i2v,
    _step_wan_vace,
)
from zyg_dashboard.bp_integrity_ops_steps.steps_gates import (
    _step_antelopev2_absent,
    _step_audiogen_absent,
    _step_bg_remove,
    _step_cinematic_lora,
    _step_cv2_pkg,
    _step_era_gate_chk,
    _step_flux_dev_absent,
    _step_hand_qc,
    _step_identity_qc,
    _step_ipadapter_weights,
    _step_licence_gate,
    _step_mediapipe_pkg,
    _step_object_tracking,
    _step_restoration_qc_chk,
    _step_sam3,
    _step_sam3d_body,
    _step_style_loras_absent,
    _step_typography_gate,
    _step_vlm_judge,
)
from zyg_dashboard.bp_integrity_ops_steps.table import (
    _chk,
    _step_infra_ffmpeg,
    _step_infra_output_dir,
    _step_llm_audit_chk,
    build_tasks,
    circuit_breaker,
    job_stats,
    last_pipeline,
    run_checks,
    summary,
)
