#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The bottom registration block: every blueprint, and every engine re-export.

Lines 4560-4865 of the original module, verbatim, and still the LAST thing the
package imports. Every module named here does ``from zyg_dashboard.crewai_web_gui
import ...`` back, so ``app`` and all the module globals above have to exist
already; the package ``__init__`` therefore re-exports the eleven modules above
this one before it imports this one.
"""

# Verbatim move: the original import order is load-bearing, and every name here is read
# back off zyg_dashboard.crewai_web_gui by the bp_* blueprints.  The late imports that
# stayed at their old definition sites carry their own per-line E402 suppressions.

from zyg_dashboard.crewai_web_gui._bootstrap import app, runtime

# ── 2026-07-17 heavy-tranche registration (engine) ────────────────────────────
from zyg_workflows import vram_manager as _vram_manager  # noqa: E402  bottom registration block: these modules import this one back
from zyg_workflows.vram_manager import (  # noqa: E402  bottom registration block: these modules import this one back
    _comfy_idle_vram_sweeper_loop,
    _comfy_vram_used_mb,
    _evict_all_ollama_models,
    _gpu_work_active,
    _release_pipeline_vram,
    _startup_vram_sweep,
    _workflow_job_gpu_active,
)
from zyg_workflows import subproc_registry as _subproc_registry  # noqa: E402  bottom registration block: these modules import this one back
from zyg_workflows.subproc_registry import _kill_all_subprocs  # noqa: E402  bottom registration block: these modules import this one back
from zyg_workflows import char_state_service as _char_state_service  # noqa: E402  bottom registration block: these modules import this one back
from zyg_workflows.char_state_service import (  # noqa: E402  bottom registration block: these modules import this one back
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
    _char_reload_jobs_from_disk,
    _char_render_style,
    _char_save_state,
    _char_stage_end,
    _char_stage_start,
    _char_state_path,
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
)
from zyg_workflows import stage_runner as _stage_runner  # noqa: E402  bottom registration block: these modules import this one back
from zyg_workflows.stage_runner import _check_workflow_health, _load_workflow_overrides, _register_prompt  # noqa: E402  bottom registration block: these modules import this one back
from zyg_workflows import pipeline_common as _pipeline_common  # noqa: E402  bottom registration block: these modules import this one back
from zyg_workflows.pipeline_common import (  # noqa: E402  bottom registration block: these modules import this one back
    _normalize_pipeline_options,
    _parse_pipeline_model_family,
    _pipeline_current_stage_from_job,
    _resolve_pipeline_public_status,
    _run_creature_training,
)
from zyg_workflows import pipeline_clipfarm as _pipeline_clipfarm  # noqa: E402  bottom registration block: these modules import this one back
from zyg_workflows.pipeline_clipfarm import _run_clipfarm_pipeline  # noqa: E402  bottom registration block: these modules import this one back
from zyg_workflows import pipeline_crime as _pipeline_crime  # noqa: E402  bottom registration block: these modules import this one back
from zyg_workflows.pipeline_crime import _run_crime_pipeline  # noqa: E402  bottom registration block: these modules import this one back
from zyg_workflows import pipeline_video as _pipeline_video  # noqa: E402  bottom registration block: these modules import this one back
from zyg_workflows.pipeline_video import _run_video_pipeline  # noqa: E402  bottom registration block: these modules import this one back
from zyg_workflows import pipeline_scholarly as _pipeline_scholarly  # noqa: E402  bottom registration block: these modules import this one back
from zyg_workflows.pipeline_scholarly import _run_scholarly_pipeline  # noqa: E402,F401  re-export: gui/scholarly.py reads it back off this module
from zyg_workflows import pipeline_storyteller as _pipeline_storyteller  # noqa: E402  bottom registration block: these modules import this one back
from zyg_workflows.pipeline_storyteller import _run_storyteller_pipeline  # noqa: E402  bottom registration block: these modules import this one back


# ── 2026-07-17 heavy-tranche registration (engine) ────────────────────────────
from zyg_dashboard import bp_storyteller as _bp_storyteller  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_storyteller.bp)
from zyg_dashboard import bp_zero as _bp_zero  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_zero.bp)
# Agent Zero v2 (2026-10-08): chat agent, model picker, budget, MCP bridge (blueprint
# 'zero_v2'). The package is self-contained -- it reaches the host only through
# agent_zero/_host.py -- so importing it here starts no thread and pulls in no model.
from zyg_dashboard import agent_zero as _agent_zero  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_agent_zero.bp)
# 2026-07-25: Storyteller daily-serial auto-batcher (sibling of the Zero/Documentary
# auto-mode). Import starts its once-per-day watcher daemon (single process).
from zyg_dashboard import bp_storyteller_daily as _bp_storyteller_daily  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_storyteller_daily.bp)
from zyg_dashboard import bp_pipeline_api as _bp_pipeline_api  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_pipeline_api.bp)
# ── 2026-07-26 Medusa: dedicated adult-women swimwear character workflow ───────
# Self-contained (own approval queue + kanban status). Reuses the stock FLUX
# contact-sheet/LoRA engine as a black box via medusa_pipeline; touches no
# existing workflow code path.
from zyg_dashboard import bp_medusa as _bp_medusa  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_medusa.bp)
# ── 2026-08-06 Medusa Training: upload-your-own-photos LoRA training ─────────
# Self-contained, /api/medusa/training/* (inherits bp_medusa's localhost-only
# auth bypass). Storage lives in dedicated medusa_training/ roots, physically
# disjoint from lora-{datasets,outputs}/storyteller_chars — see the isolation
# contract in bp_medusa_training.py's module docstring. Touches no existing
# workflow code path; the only shared code it calls is the generic,
# path-parameterized LoraTrainerService.
from zyg_dashboard import bp_medusa_training as _bp_medusa_training  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_medusa_training.bp)
# ── 2026-09-18 Medusa Models: BASE-model LoRA training, one per model family ──
# /api/medusa/models/* (same localhost-only bypass). Inherits the Training
# isolation contract and adds medusa_model_lora's: a base adapter changes the
# MODEL, so unlike a character LoRA it is not opt-in by construction. Storage is
# a third dedicated root (medusa_models/), ids are a third shape (mdm_<12hex>),
# and a trained adapter attaches ONLY via a thread-local inside a Medusa worker,
# into node 14 of a <family>_medusa_base graph nothing else names. Adults-only
# attestation is enforced before training and before activation (medusa_age_gate,
# no env override). Touches no existing workflow code path.
from zyg_dashboard import bp_medusa_models as _bp_medusa_models  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_medusa_models.bp)
# ── 2026-08-05 Remix: channel-watch → clip → narrate → split-screen dept ──────
# Import starts the remix-watcher + remix-cleaner daemons (single process,
# use_reloader=False). pipeline_remix itself is imported lazily by bp_remix and
# the /api/internal/pipeline/start dispatcher — no bottom import needed for it.
from zyg_dashboard import bp_remix as _bp_remix  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_remix.bp)

# ── 2026-08-29 Remix Ai: study a popular AI video → build an original one ─────
# Keyword sweep → download → analyse (frames/transcript/soundtrack/title) →
# regenerate (script/title/images) → narrate → Ken Burns → replace soundtrack.
# Import starts the remixai-sweeper + remixai-cleaner daemons (single process,
# use_reloader=False); auto mode is OFF by default so nothing runs until the
# operator flips it on /remix-ai. pipeline_remixai is imported lazily by the
# blueprint and by the /api/internal/pipeline/start dispatcher.
from zyg_dashboard import bp_remixai as _bp_remixai  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_remixai.bp)

# ── 2026-08-06 Briefing departments ──────────────────────────────────────────
# Stockmarket + Cryptodaily (/markets) and TokiToki + Arena (/betting). Both
# imports start their daily scheduler + delivery cleaner daemons; auto mode is
# OFF by default, so importing them schedules nothing until the operator flips it
# on in the console. The pipelines themselves (pipeline_market / pipeline_sports)
# are imported lazily by the blueprints and by the /api/internal/pipeline/start
# dispatcher, exactly like pipeline_remix.
from zyg_dashboard import bp_market as _bp_market  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_market.bp)
from zyg_dashboard import bp_sports as _bp_sports  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_sports.bp)

# ── 2026-07-17 modularization: blueprint registration ─────────────────────────
# These modules from-import crewai_web_gui's globals; import them only here,
# after everything above is defined.
from zyg_dashboard import bp_schedule as _bp_schedule  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_schedule.bp)
from zyg_dashboard import bp_themes_users as _bp_themes_users  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_themes_users.bp)
from zyg_dashboard import bp_skill_sandbox as _bp_skill_sandbox  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_skill_sandbox.bp)
from zyg_dashboard import bp_safety as _bp_safety  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_safety.bp)
from zyg_dashboard import bp_zero_public_store as _bp_zero_public_store  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_zero_public_store.bp)
from zyg_dashboard.bp_safety import (  # noqa: E402  bottom registration block: these modules import this one back
    _safety_error_logs_fn,
    _safety_job_status_fn,
    _safety_schedule_pause_fn,
    _safety_telemetry_fn,
)  # names main still uses (request-time only — no thread callers, verified)
from zyg_dashboard.bp_zero_public_store import (  # noqa: E402  bottom registration block: these modules import this one back
    _ZPUB_PENDING_LOCK,
    _zpub_pending_load,
    _zpub_pending_save,
)  # names main still uses (request-time only — no thread callers, verified)


# ── 2026-07-17 modularization: blueprint registration ─────────────────────────
# These modules from-import crewai_web_gui's globals; import them only here,
# after everything above is defined.
from zyg_dashboard import bp_dashboard_pages as _bp_dashboard_pages  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_dashboard_pages.bp)
from zyg_dashboard import bp_timeline_legacy as _bp_timeline_legacy  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_timeline_legacy.bp)
from zyg_dashboard import bp_jobs_audit as _bp_jobs_audit  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_jobs_audit.bp)


# ── 2026-07-17 heavy-tranche registration ─────────────────────────────────────
from zyg_workflows import encode_utils as _encode_utils  # noqa: E402  bottom registration block: these modules import this one back
from zyg_workflows import tts_service as _tts_service  # noqa: E402  bottom registration block: these modules import this one back
from zyg_workflows import narrator_voice_service as _narrator_voice_service  # noqa: E402  bottom registration block: these modules import this one back
from zyg_dashboard import bp_voices as _bp_voices  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_voices.bp)
from zyg_dashboard import bp_auth as _bp_auth  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_auth.bp)
from zyg_dashboard import bp_claude_clip as _bp_claude_clip  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_claude_clip.bp)
from zyg_dashboard import bp_metrics as _bp_metrics  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_metrics.bp)
from zyg_dashboard import bp_benchmark as _bp_benchmark  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_benchmark.bp)
from zyg_dashboard import bp_assets_media as _bp_assets_media  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_assets_media.bp)
from zyg_dashboard import bp_integrity_ops as _bp_integrity_ops  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_integrity_ops.bp)
from zyg_nexus import bp_creator_nexus as _bp_creator_nexus  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_creator_nexus.bp)
from zyg_dashboard import bp_control_settings as _bp_control_settings  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_control_settings.bp)
from zyg_dashboard import bp_agents_api as _bp_agents_api  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_agents_api.bp)
# Children's Music workflow (2026-08-29)
from zyg_dashboard import bp_kidsmusic as _bp_kidsmusic  # noqa: E402  bottom registration block

app.register_blueprint(_bp_kidsmusic.bp)
# Children's series x10 (2026-09-06)
from zyg_dashboard import bp_kidseries as _bp_kidseries  # noqa: E402  bottom registration block

app.register_blueprint(_bp_kidseries.bp)
# 2D Character Basics I (2026-09-16)
from zyg_dashboard import bp_char2d as _bp_char2d  # noqa: E402  bottom registration block

app.register_blueprint(_bp_char2d.bp)
# ── 2026-09-01 Melody daily auto-batcher ─────────────────────────────────────
# The "Melody" toggle on the Approval Queue board: five children's songs a day,
# one at a time. Sibling of the Zero/Documentary auto-mode and the Storyteller
# daily serial; import starts its watcher daemon (single process,
# use_reloader=False). Off by default, so importing it schedules nothing.
from zyg_dashboard import bp_melody_daily as _bp_melody_daily  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_melody_daily.bp)
# ── 2026-10-02 Life of Jack / Life of Mona — two series, one episode each a day
# The operator's standing children's-music production: two songs a night, every
# episode about one of two recurring children and nothing else. Same contract as
# the melody batcher above (watcher starts on import, off until the toggle is on);
# what each episode IS comes from kids_series_people, which keeps the ledger.
from zyg_dashboard import bp_jackmona_daily as _bp_jackmona_daily  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_jackmona_daily.bp)
# ── 2026-09-20 Pre-Emptive generation + the rebuilt Approval Queue board ─────
# bp_preempt: the bank builder (brain runs that record every text Claude call,
# song briefs pre-picked locally); its watcher starts on import, off by default.
# bp_approval_queue: one board payload + play/pause/abort + per-card settings.
from zyg_dashboard import bp_preempt as _bp_preempt  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_preempt.bp)
from zyg_dashboard import bp_approval_queue as _bp_approval_queue  # noqa: E402  bottom registration block: these modules import this one back

app.register_blueprint(_bp_approval_queue.bp)
# Movement Studio (2026-08-31)
from zyg_dashboard import bp_movement as _bp_movement  # noqa: E402  bottom registration block

app.register_blueprint(_bp_movement.bp)
# Picture Studio advanced editing (2026-08-31)
from zyg_dashboard import bp_picture_studio as _bp_picture_studio  # noqa: E402  bottom registration block

app.register_blueprint(_bp_picture_studio.bp)
from zyg_dashboard.bp_assets_media import _download_assets_background  # noqa: E402  bottom registration block: these modules import this one back
from zyg_dashboard.bp_benchmark import _bench_replay_get, _bm_record, _bm_record_pipeline  # noqa: E402  bottom registration block: these modules import this one back
from zyg_dashboard.bp_claude_clip import _record_token_usage  # noqa: E402  bottom registration block: these modules import this one back
from zyg_dashboard.bp_integrity_ops import get_dependencies_status  # noqa: E402  bottom registration block: these modules import this one back
from zyg_dashboard import preempt_bank as _preempt_bank  # noqa: E402  bottom registration block

# The remaining runtime hooks: they live in blueprints / the VRAM manager, so
# they can only be registered now that those modules are imported.
runtime.register(
    gpu_work_active=_gpu_work_active,
    record_token_usage=_record_token_usage,
    bm_record=_bm_record,
    bm_record_pipeline=_bm_record_pipeline,
    bench_replay_get=_bench_replay_get,
    download_assets_background=_download_assets_background,
    preempt_bank=_preempt_bank,
)
from zyg_workflows.encode_utils import (  # noqa: E402  bottom registration block: these modules import this one back
    _cq_for_crf,
    _ffmpeg_popen_nvenc_first,
    _ffmpeg_run_nvenc_first,
    _kb_encode_wait_seconds,
    _nvenc_vcodec_args,
    _x264_vcodec_args,
)
from zyg_workflows.narrator_voice_service import _get_narrator_voice, _vid_to_channel_id  # noqa: E402  bottom registration block: these modules import this one back
from zyg_workflows.tts_service import (  # noqa: E402  bottom registration block: these modules import this one back
    _bleep_audio_in_clip,
    _mask_bad_words,
    _sanitize_title,
    _synthesise_tts,
    _tts_shared,
)


# ── re-export surface ────────────────────────────────────────────────────────
# Every name below is imported above and NOT used in this module: it is read off it by
# ``zyg_dashboard.crewai_web_gui.__init__`` and from there by the bp_* blueprints.
# Declaring them is what makes the re-export deliberate rather than an unused import;
# nothing does ``import *`` from here, so __all__ changes no behaviour.
__all__ = [
    '_vram_manager',
    '_comfy_idle_vram_sweeper_loop',
    '_comfy_vram_used_mb',
    '_evict_all_ollama_models',
    '_release_pipeline_vram',
    '_startup_vram_sweep',
    '_workflow_job_gpu_active',
    '_subproc_registry',
    '_kill_all_subprocs',
    '_char_state_service',
    '_bg_contact_sheet_pipeline',
    '_char_derive_pipeline_stage',
    '_char_library_trained_at',
    '_char_lora_output_ready',
    '_char_lora_train_families',
    '_char_mark_done',
    '_char_mark_error',
    '_char_params_from_bible',
    '_char_preview_png_names',
    '_char_reconcile_job_state',
    '_char_reload_jobs_from_disk',
    '_char_render_style',
    '_char_save_state',
    '_char_stage_end',
    '_char_stage_start',
    '_char_state_path',
    '_char_train_lora_for_family',
    '_contact_sheet_derive_stage',
    '_contact_sheet_emit',
    '_contact_sheet_reload_jobs_from_disk',
    '_contact_sheet_resume_run',
    '_contact_sheet_save_state',
    '_contact_sheet_state_path',
    '_contact_sheet_worker_alive',
    '_creature_derive_pipeline_stage',
    '_creature_reload_jobs_from_disk',
    '_creature_save_state',
    '_creature_state_path',
    '_have_usable_char_preview',
    '_normalize_char_model_family',
    '_render_char_preview_images',
    '_resolve_char_model_family',
    '_stage_runner',
    '_check_workflow_health',
    '_load_workflow_overrides',
    '_register_prompt',
    '_pipeline_common',
    '_normalize_pipeline_options',
    '_parse_pipeline_model_family',
    '_pipeline_current_stage_from_job',
    '_resolve_pipeline_public_status',
    '_run_creature_training',
    '_pipeline_clipfarm',
    '_run_clipfarm_pipeline',
    '_pipeline_crime',
    '_run_crime_pipeline',
    '_pipeline_video',
    '_run_video_pipeline',
    '_pipeline_scholarly',
    '_pipeline_storyteller',
    '_run_storyteller_pipeline',
    '_safety_error_logs_fn',
    '_safety_job_status_fn',
    '_safety_schedule_pause_fn',
    '_safety_telemetry_fn',
    '_ZPUB_PENDING_LOCK',
    '_zpub_pending_load',
    '_zpub_pending_save',
    '_encode_utils',
    '_tts_service',
    '_narrator_voice_service',
    'get_dependencies_status',
    '_cq_for_crf',
    '_ffmpeg_popen_nvenc_first',
    '_ffmpeg_run_nvenc_first',
    '_kb_encode_wait_seconds',
    '_nvenc_vcodec_args',
    '_x264_vcodec_args',
    '_get_narrator_voice',
    '_vid_to_channel_id',
    '_bleep_audio_in_clip',
    '_mask_bad_words',
    '_sanitize_title',
    '_synthesise_tts',
    '_tts_shared',
]
