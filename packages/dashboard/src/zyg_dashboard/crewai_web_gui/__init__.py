#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""crewai_web_gui.py — the CrewAI Web GUI: a web interface onto the agent hierarchy.

THIS DASHBOARD IS A LEGACY UI. ALL STATE IS OWNED BY THE CONTROL PLANE API.
Flask: render HTML, serve static, proxy to FastAPI. No auth, no JSON writes.

The listening address is ``zyg_workflows.paths.BIND_HOST`` and defaults to
``127.0.0.1``: the dashboard is loopback-only unless LAN exposure is asked for
explicitly by setting ``BIND_HOST=0.0.0.0`` in the environment.

The import order below is load-bearing, which is what the E402 suppressions record:
PYTORCH_CUDA_ALLOC_CONF has to be set before any CUDA memory operation, the
``__main__`` module alias before anything the bp_* blueprints import back, the venv
site-packages path before the third-party imports, and the bp_* blueprint imports stay
at the very bottom of the file because each of them does ``from
zyg_dashboard.crewai_web_gui import ...`` — ``app`` and the module globals must already
exist by then.

This module is also the shared namespace for that circular contract: names imported
here and not used here are re-exports, read off this module by the bp_* blueprints and
the pipelines (``from zyg_dashboard.crewai_web_gui import X`` and
``getattr(_main_mod, 'X')``). ``__all__`` at the bottom of the file declares them.
"""

# ruff: noqa: F401  this package IS the shared namespace of the circular blueprint
# contract described above: every name below is a re-export, none is used here.

# ── 2026-10-06 wave-1 split: crewai_web_gui.py became this package ───────────
# The 5,102-line module was cut at its own section banners into twelve modules,
# each one a VERBATIM contiguous move; packages/dashboard/docs/
# crewai_web_gui_split_map.md is the name -> module table. The import path did not
# change, so no importer anywhere needed editing.
#
# The order of the re-export block below IS the original top-to-bottom order of
# the file, and it is load-bearing twice over: the module-level side effects (the
# telemetry sampler thread, the three runtime.register calls, the blueprint
# registrations) have to run in that order, and each `from .mod import (...)`
# binds its names on THIS module before the next module is imported — which is
# what lets `registration` (the original bottom block) and the bp_* modules it
# imports read every global defined above them off zyg_dashboard.crewai_web_gui.

from zyg_dashboard.crewai_web_gui._bootstrap import (  # noqa: E402
    atexit,
    glob,
    hashlib,
    hmac,
    html_module,
    importlib,
    json,
    _zyg_logging,
    os,
    secrets,
    shutil,
    _stat_mod,
    sys,
    threading,
    time,
    uuid,
    timedelta,
    _zyg_log,
    gui_state,
    runtime,
    exe,
    BIND_HOST,
    ZYG_DASHBOARD_URL,
    ZYG_OLLAMA_URL,
    ZYG_REDIS_URL,
    tmp_dir,
    _VENV_SP,
    _ROOT_ENV,
    requests,
    Flask,
    render_template,
    request,
    jsonify,
    send_from_directory,
    redirect,
    session,
    url_for,
    get_remote_address,
    apply_cors,
    _CHANNEL_VOICES_PATH,
    _CHAR_DEFAULT_MODEL_FAMILY,
    _CLIPFARM_STAGES,
    _FLUX_PERF_TELEMETRY_PATH,
    _RUNTIME_DIR,
    _VOICE_LIBRARY_PATH,
    _caveman_kw,
    _dsl,
    _agent_log,
    _char_gen_jobs,
    _contact_sheet_jobs,
    _creature_gen_jobs,
    _load_json,
    _reconcile_stale_workflow_jobs,
    _runtime_path,
    _save_json,
    _workflow_jobs,
    _workflow_pipeline_worker_alive,
    _start_crime_pipeline_internal,
    _start_scholarly_pipeline_internal,
    API_ADAPTER_AVAILABLE,
    API_DEV_MODE,
    API_DEV_TOKEN,
    BACKEND_DEBUG,
    LOGIN_DEBUG,
    PAGE_LOAD_DEBUG,
    SESSION_VALIDITY_TOKEN,
    _backend_debug,
    _get_cpu_bar_mapping,
    _get_gpu_bar_mapping,
    _login_debug,
    _page_load_debug,
    _read_local_telemetry,
    _TELEMETRY_CACHE,
    api_get_agents,
    create_approval,
    get_active_schedule,
    get_approval_queue,
    get_integrity_gate,
    get_job_runs,
    get_schedule_pause_state,
    get_schedule_requests,
    get_security_controls,
    get_telemetry,
    set_schedule_pause,
    submit_schedule_request,
    terminate_job_run,
    update_security_control,
    ZoneInfo,
    _AMS_TZ,
    _ams_iso,
    _ams_now,
    _parse_iso_to_ams,
    AGENT_ZERO_CONFIG_PATH,
    ZERO_AUDIT_PATH,
    ZERO_TASK_STATE_PATH,
    _ZERO_PUBLIC_TOKEN,
    _zero_audit_log,
    _zero_load_config,
    block_spectator_mutation,
    _dotenv_path,
    _bootstrap_hf_token_from_env_file,
    _NVENC_SEM,
    _KB_THREAD_STAGGER_S,
    _POSTPROC_SEM,
    _GPU_PIPELINE_LOCK,
    app,
    require_flask_secret,
    _env_path,
    _rate_limit_key,
    limiter,
)

# Bound on only one branch of a try/except or an `if` in _bootstrap, exactly as they
# were in the single file — when the import they sit behind fails, the original
# module had no such attribute either. Copied across only if present, so a soft
# absence stays soft instead of becoming an ImportError here.
for _opt_name in (
    '_load_dotenv',
    '_llm_audit',
    '_cpu_cap',
    '_env_mode',
):
    _opt_mod = sys.modules['zyg_dashboard.crewai_web_gui._bootstrap']
    if hasattr(_opt_mod, _opt_name):
        globals()[_opt_name] = getattr(_opt_mod, _opt_name)

from zyg_dashboard.crewai_web_gui.security import (  # noqa: E402
    ratelimit_handler,
    _ensure_csrf_token,
    _require_csrf,
    _LOOPBACK_ADDRS,
    _LOOPBACK_ONLY_PREFIXES,
    _is_loopback,
    require_login,
    DATA_DIR,
    REPO_ROOT,
    DOCS_DIR,
    _BENCH_REPLAY_CACHE_PATH,
    _BENCHMARK_PATH,
    _benchmark_lock,
    _bm_infra_lock,
    _bm_mr_lock,
    _error_log_lock,
    _push_error_log,
    _NARRATOR_OUTRO,
    _DEMONET_TIER2,
    _TITLE_SYNONYMS,
    _SENSITIVE_TOPIC_KEYWORDS,
    LEGACY_JSON_ARCHIVE,
    _load_canonical_json,
    _get_gpu_models,
    _get_cpu_models,
)

from zyg_dashboard.crewai_web_gui.pages import (  # noqa: E402
    SCHEDULE_DIR,
    GPU_SCHEDULE_FILE,
    CPU_SCHEDULE_FILE,
    DualTimelineOrchestrator,
    _skill_sandbox,
    orchestrator,
    _zyg_workflows_pkg,
    mapping_path,
    spec,
    ai_model_agent_mapping,
    CPU_MODELS,
    GPU_MODELS,
    filter_schedule_by_model_type,
    _load_all_tools,
    _get_all_tools,
    Agent,
    Crew,
    CrewAILLM,
    CrewAIController,
    OLLAMA_AVAILABLE,
    Ollama,
    Process,
    Task,
    _ControlPlaneUnavailable,
    _HEAVY_REASONING_KEYWORDS,
    _OLLAMA_BASE_URL,
    _PREFERRED_MODELS,
    _pick_model_for_agent,
    _pick_ollama_model,
    controller,
    login_page,
    _render_dashboard_tab,
    index,
    _first_list,
    _AGENT_FACES_BASE,
    _AGENT_FACE_EXTENSIONS,
    _restore_jobs_from_disk,
    _APPROVAL_REQ_FILE,
    _APPROVAL_STORE_FILE,
    _SAFETY_THRESHOLDS_PATH,
)

# Bound on only one branch of a try/except or an `if` in pages, exactly as they
# were in the single file — when the import they sit behind fails, the original
# module had no such attribute either. Copied across only if present, so a soft
# absence stays soft instead of becoming an ImportError here.
for _opt_name in ('_here',):
    _opt_mod = sys.modules['zyg_dashboard.crewai_web_gui.pages']
    if hasattr(_opt_mod, _opt_name):
        globals()[_opt_name] = getattr(_opt_mod, _opt_name)

from zyg_dashboard.crewai_web_gui.hardware import (  # noqa: E402
    _apply_gpu_power_limit,
    _SUBPROC_REGISTRY,
    _SUBPROC_LOCK,
    _SUBPROC_SYNTHETIC_COUNTER,
    _FLUX_LORA_DIR,
    _FLUX_LORA_ENABLED,
    _FLUX_LORA_PATH,
    _FLUX_LORA_SCALE,
    _STYLE_LORA_DIR,
    _STYLE_LORA_CONFIG,
    _VALID_VISUAL_STYLES,
    _LUT_DIR,
    _STYLE_LUT_MAP,
    _DEFAULT_LUT,
    _apply_color_grade,
)

from zyg_dashboard.crewai_web_gui.pipelines import (  # noqa: E402
    _start_video_pipeline_internal,
    _start_manga_pipeline_internal,
    _start_creature_pipeline_internal,
    _BOOK_PNG,
    _BOOK_FONT,
    _start_storyteller_pipeline_internal,
)

from zyg_dashboard.crewai_web_gui.contact_sheet import (  # noqa: E402
    _contact_sheet_mark_manifest_approved,
    _contact_sheet_mark_declined,
    _contact_sheet_push_review_pending,
    _contact_sheet_parse_start_payload,
    _contact_sheet_launch_run,
)

# Bound on only one branch of a try/except or an `if` in contact_sheet, exactly as they
# were in the single file — when the import they sit behind fails, the original
# module had no such attribute either. Copied across only if present, so a soft
# absence stays soft instead of becoming an ImportError here.
for _opt_name in ('_CHAR_DEFAULT_MODEL_FAMILY',):
    _opt_mod = sys.modules['zyg_dashboard.crewai_web_gui.contact_sheet']
    if hasattr(_opt_mod, _opt_name):
        globals()[_opt_name] = getattr(_opt_mod, _opt_name)

from zyg_dashboard.crewai_web_gui.telemetry_gpu import (  # noqa: E402
    _start_clipfarm_internal,
    _METRICS_PIPELINE_LABELS,
    _LOG_ROTATE_MAX_BYTES,
    _LOG_ROTATE_KEEP,
    _log_rotate_last_check,
    _rotate_runtime_logs,
    _GPU_PROC_LABELS,
    _GPU_PROC_PATTERNS,
    _gpu_proc_label,
    _gpu_processes,
)

from zyg_dashboard.crewai_web_gui.telemetry_proc import (  # noqa: E402
    _PROC_LABELS,
    _PROC_EXTRA_PATTERNS,
    _proc_label,
    _PROC_CPU_PREV,
    _PROC_PREV_TS,
    _PROC_SAMPLE_EVERY,
    _DISK_SAMPLE_EVERY,
    _sample_top_processes,
    _sample_disks,
    _telemetry_sampler_loop,
    _telemetry_thread,
)

from zyg_dashboard.crewai_web_gui.zero import (  # noqa: E402
    CANONICAL_LLMS,
    DEPENDENCIES_CONFIG,
    get_agent_config,
    _zero_agent_legacy_shape,
    _ZERO_TOPICS_PENDING,
    _ZERO_TOPICS_PENDING_PATH,
    _ZERO_TOPICS_TTL,
    _SPORTS_KEYWORD_BLOCKLIST,
    _ZERO_TOPIC_POOLS_PATH,
    _ZERO_POOL_LABELS,
    _ZERO_POOL_PICK_COUNT,
    _ZERO_BATCH_SCHEDULE_PATH,
    _ZERO_PUB_TIMES,
    _ZERO_BATCH_LOCK,
    _ZERO_KANBAN_PATH,
    _ZERO_AUTO_MODE_PATH,
    _ZERO_KANBAN_LOCK,
    _zero_claim_batch_slot,
)

from zyg_dashboard.crewai_web_gui.claude_clips import (  # noqa: E402
    _halt_all_pipeline_activity,
    _clear_pipeline_halt,
    _ASSETS_SFX_DIR,
    _ASSETS_REACTION_DIR,
    _YT_UPLOAD_SCRIPT,
    _YT_VENV_PYTHON,
    _YT_TOKEN_FILE,
    _ccl_re,
    _ccl_json,
    _ccl_threading,
    _CCL_OUTPUT_BASE,
    _TOKEN_USAGE_LOCK,
    _TOKEN_USAGE_PATH,
    _CONTEXT_LEDGER_PATH,
    _MODEL_CTX_WINDOWS,
    _CCL_AR_VF,
)

from zyg_dashboard.crewai_web_gui.theme import (  # noqa: E402
    sanitize_filename,
    agent_configs,
    get_agent_name_by_id,
    _build_agent_seed_to_config,
    _AGENT_SEED_TO_CONFIG,
    _resolve_agent_display_name,
    _MODEL_ID_TO_NAME,
    get_model_name_by_id,
    _resolve_ai_models_display,
    _root_icon_probe,
    test_gradients,
    BUTTONS_DIR,
    BACKGROUNDS_DIR,
    SIDEBAR_DIR,
    THEME_CONFIG_PATH,
    USERS_DATA_PATH,
    ERROR_LOGS_DATA_PATH,
    JOB_STATUS_DATA_PATH,
    MONITORING_JOBS_PATH,
    SAFETY_THRESHOLDS_PATH,
    SAFETY_AUDIT_LOG_PATH,
    AVATARS_DIR,
    DEFAULT_BUTTON_THEME,
    DEFAULT_BACKGROUND_THEME,
    LANGUAGES_DIR,
    LANGUAGE_LINKS_FILE,
    DASHBOARD_AVAILABLE,
    _theme_version,
    _add_cache_headers,
    _SCHOLARLY_SMOKE_MAX_IMAGES,
    _SMOKE_SCRIPTS,
    _HF_ENV_PATH,
    _CDR_OK,
    _SV_STATUS_FILE,
    _TSTORE_FILE,
    _CLIPS_OUTPUT_DIR,
)

# Bound on only one branch of a try/except or an `if` in theme, exactly as they
# were in the single file — when the import they sit behind fails, the original
# module had no such attribute either. Copied across only if present, so a soft
# absence stays soft instead of becoming an ImportError here.
for _opt_name in (
    'init_safety_audit',
    '_dc_dir',
    '_dc_project_root',
    '_dc_layouts',
    '_cdr',
    '_cdr_e_str',
):
    _opt_mod = sys.modules['zyg_dashboard.crewai_web_gui.theme']
    if hasattr(_opt_mod, _opt_name):
        globals()[_opt_name] = getattr(_opt_mod, _opt_name)

# Bound BEFORE registration.py imports the blueprints. Six blueprint modules
# (bp_assets_media/base, bp_integrity_ops/constants, bp_integrity_ops_steps/constants,
# bp_metrics/__init__, aggregate, dashboard) import these workflow-level names back off
# THIS package at module level; a package that is still initialising only serves the
# names already on it, and registration re-exports them only once it has finished.
# In the single-file crewai_web_gui.py these imports opened the bottom block, ahead of
# the blueprints, so this restores that order. They are left out of the registration
# import list below for that reason (ruff F811), not because registration lost them.
from zyg_workflows.vram_manager import _comfy_vram_used_mb, _gpu_work_active, _release_pipeline_vram  # noqa: E402,F401
from zyg_workflows.char_state_service import _char_reload_jobs_from_disk, _char_state_path  # noqa: E402,F401
from zyg_workflows.stage_runner import _register_prompt  # noqa: E402,F401

from zyg_dashboard.crewai_web_gui.registration import (  # noqa: E402
    _vram_manager,
    _comfy_idle_vram_sweeper_loop,
    _evict_all_ollama_models,
    _startup_vram_sweep,
    _workflow_job_gpu_active,
    _subproc_registry,
    _kill_all_subprocs,
    _char_state_service,
    _bg_contact_sheet_pipeline,
    _char_derive_pipeline_stage,
    _char_library_trained_at,
    _char_lora_output_ready,
    _char_lora_train_families,
    _char_mark_done,
    _char_mark_error,
    _char_params_from_bible,
    _char_preview_png_names,
    _char_reconcile_job_state,
    _char_render_style,
    _char_save_state,
    _char_stage_end,
    _char_stage_start,
    _char_train_lora_for_family,
    _contact_sheet_derive_stage,
    _contact_sheet_emit,
    _contact_sheet_reload_jobs_from_disk,
    _contact_sheet_resume_run,
    _contact_sheet_save_state,
    _contact_sheet_state_path,
    _contact_sheet_worker_alive,
    _creature_derive_pipeline_stage,
    _creature_reload_jobs_from_disk,
    _creature_save_state,
    _creature_state_path,
    _have_usable_char_preview,
    _normalize_char_model_family,
    _render_char_preview_images,
    _resolve_char_model_family,
    _stage_runner,
    _check_workflow_health,
    _load_workflow_overrides,
    _pipeline_common,
    _normalize_pipeline_options,
    _parse_pipeline_model_family,
    _pipeline_current_stage_from_job,
    _resolve_pipeline_public_status,
    _run_creature_training,
    _pipeline_clipfarm,
    _run_clipfarm_pipeline,
    _pipeline_crime,
    _run_crime_pipeline,
    _pipeline_video,
    _run_video_pipeline,
    _pipeline_scholarly,
    _run_scholarly_pipeline,
    _pipeline_storyteller,
    _run_storyteller_pipeline,
    _bp_storyteller,
    _bp_zero,
    _bp_storyteller_daily,
    _bp_pipeline_api,
    _bp_medusa,
    _bp_medusa_training,
    _bp_medusa_models,
    _bp_remix,
    _bp_remixai,
    _bp_market,
    _bp_sports,
    _bp_schedule,
    _bp_themes_users,
    _bp_skill_sandbox,
    _bp_safety,
    _bp_zero_public_store,
    _safety_error_logs_fn,
    _safety_job_status_fn,
    _safety_schedule_pause_fn,
    _safety_telemetry_fn,
    _ZPUB_PENDING_LOCK,
    _zpub_pending_load,
    _zpub_pending_save,
    _bp_dashboard_pages,
    _bp_timeline_legacy,
    _bp_jobs_audit,
    _encode_utils,
    _tts_service,
    _narrator_voice_service,
    _bp_voices,
    _bp_auth,
    _bp_claude_clip,
    _bp_metrics,
    _bp_benchmark,
    _bp_assets_media,
    _bp_integrity_ops,
    _bp_creator_nexus,
    _bp_control_settings,
    _bp_agents_api,
    _bp_kidsmusic,
    _bp_kidseries,
    _bp_char2d,
    _bp_melody_daily,
    _bp_jackmona_daily,
    _bp_preempt,
    _bp_approval_queue,
    _bp_movement,
    _bp_picture_studio,
    _download_assets_background,
    _bench_replay_get,
    _bm_record,
    _bm_record_pipeline,
    _record_token_usage,
    get_dependencies_status,
    _preempt_bank,
    _cq_for_crf,
    _ffmpeg_popen_nvenc_first,
    _ffmpeg_run_nvenc_first,
    _kb_encode_wait_seconds,
    _nvenc_vcodec_args,
    _x264_vcodec_args,
    _get_narrator_voice,
    _vid_to_channel_id,
    _bleep_audio_in_clip,
    _mask_bad_words,
    _sanitize_title,
    _synthesise_tts,
    _tts_shared,
)


# ── re-export surface ────────────────────────────────────────────────────────
# Every name below is imported above and NOT used in this module: it is read off this
# module by the bp_* blueprints and the pipelines, either with
# ``from zyg_dashboard.crewai_web_gui import X`` or with ``getattr(_main_mod, 'X')``.
# Several were left here on purpose by the 2026-07/08 modularization passes ("kept at
# the old definition site") so that callers did not have to move with the code.
# Declaring them is what makes the re-export deliberate rather than an unused import;
# nothing does ``import *`` from here, so __all__ changes no behaviour.
__all__ = [
    '_CHANNEL_VOICES_PATH',
    '_CLIPFARM_STAGES',
    '_FLUX_PERF_TELEMETRY_PATH',
    '_VOICE_LIBRARY_PATH',
    'atexit',
    '_bleep_audio_in_clip',
    '_caveman_kw',
    '_ccl_json',
    '_ccl_threading',
    '_cdr',
    '_char_derive_pipeline_stage',
    '_char_library_trained_at',
    '_char_lora_output_ready',
    '_char_lora_train_families',
    '_char_mark_done',
    '_char_mark_error',
    '_char_params_from_bible',
    '_char_preview_png_names',
    '_char_reconcile_job_state',
    '_char_render_style',
    '_char_stage_end',
    '_char_stage_start',
    '_char_state_path',
    '_char_state_service',
    '_char_train_lora_for_family',
    '_check_workflow_health',
    '_contact_sheet_derive_stage',
    '_contact_sheet_emit',
    '_contact_sheet_resume_run',
    '_contact_sheet_worker_alive',
    '_cq_for_crf',
    '_creature_derive_pipeline_stage',
    '_creature_reload_jobs_from_disk',
    '_dsl',
    '_encode_utils',
    '_ffmpeg_popen_nvenc_first',
    '_ffmpeg_run_nvenc_first',
    '_get_narrator_voice',
    'glob',
    '_have_usable_char_preview',
    '_kb_encode_wait_seconds',
    '_load_workflow_overrides',
    '_mask_bad_words',
    '_narrator_voice_service',
    '_normalize_char_model_family',
    '_nvenc_vcodec_args',
    '_parse_iso_to_ams',
    '_pipeline_clipfarm',
    '_pipeline_common',
    '_pipeline_crime',
    '_pipeline_scholarly',
    '_pipeline_storyteller',
    '_pipeline_video',
    '_register_prompt',
    '_render_char_preview_images',
    '_resolve_char_model_family',
    '_run_crime_pipeline',
    '_safety_error_logs_fn',
    '_safety_job_status_fn',
    '_safety_schedule_pause_fn',
    '_safety_telemetry_fn',
    '_sanitize_title',
    '_skill_sandbox',
    '_stage_runner',
    '_subproc_registry',
    '_synthesise_tts',
    '_tts_service',
    '_tts_shared',
    '_vid_to_channel_id',
    '_vram_manager',
    '_workflow_job_gpu_active',
    '_workflow_pipeline_worker_alive',
    '_x264_vcodec_args',
    'api_get_agents',
    'create_approval',
    'get_active_schedule',
    'get_approval_queue',
    'get_dependencies_status',
    'get_integrity_gate',
    'get_job_runs',
    'get_schedule_pause_state',
    'get_schedule_requests',
    'get_security_controls',
    'get_telemetry',
    'hmac',
    'html_module',
    'require_flask_secret',
    'set_schedule_pause',
    'submit_schedule_request',
    'terminate_job_run',
    'update_security_control',
]
