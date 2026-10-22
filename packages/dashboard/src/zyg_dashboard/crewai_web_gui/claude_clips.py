#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The halt switch, the GUI-backed runtime hooks, the Claude collaboration layer.

Lines 3756-4043 of the original module, verbatim: ``_halt_all_pipeline_activity``
and ``_clear_pipeline_halt``, the ``runtime.register`` call that replaces the
pipelines' headless halt/session defaults, the SFX and reaction-clip asset
directories, the YouTube upload paths and the Claude collaboration layer
constants (output base, token-usage ledger, context windows, aspect-ratio filter
map, ``sanitize_filename``).
"""

# Verbatim move: every name here is read back off zyg_dashboard.crewai_web_gui by the
# bp_* blueprints.

# Aliased stdlib re-exports for the Claude collaboration layer: bp_claude_clip.py and
# theme.py read these three off this module, and crewai_web_gui/__init__.py re-exports
# them, so they are part of this module's surface rather than local helpers.
import re as _ccl_re
import json as _ccl_json
import threading as _ccl_threading
from zyg_dashboard import paths as _dash_paths
from zyg_dashboard.crewai_web_gui._bootstrap import (
    ZYG_REDIS_URL,
    _char_gen_jobs,
    _creature_gen_jobs,
    _workflow_jobs,
    _zero_audit_log,
    _zyg_log,
    gui_state,
    os,
    runtime,
    threading,
)
from zyg_dashboard.crewai_web_gui.security import _ensure_csrf_token
from zyg_workflows.char_state_service.char_state import _char_save_state
from zyg_workflows.char_state_service.creature import _creature_save_state
from zyg_workflows.subproc_registry import _kill_all_subprocs
from zyg_workflows.vram_manager import _evict_all_ollama_models, _release_pipeline_vram


# ── re-export surface ────────────────────────────────────────────────────────
# Every name below is imported above and NOT used in this module: it is read off this
# module by its importers. Declaring them is what makes the re-export deliberate rather
# than an unused import; nothing does ``import *`` from here, so __all__ changes no
# behaviour.
__all__ = [
    '_ccl_re',
    '_ccl_json',
    '_ccl_threading',
]


def _halt_all_pipeline_activity(reason: str = 'Stopped by user') -> dict:
    """Halt every running pipeline (workflow, creature, character), subprocesses, Comfy, VRAM."""
    pass  # (global stmt removed: names moved to gui_state)
    from zyg_workflows import pipeline_control as _pc

    gui_state._pipeline_stop_flag = True
    _pc.request_halt(reason)

    stopped: list[dict] = []

    def _stop_registry(registry: dict, job_type: str, save_fn=None, id_keys=('pipeline_id', 'creature_id', 'char_id')):
        for jid, job in list(registry.items()):
            if job.get('status') != 'running':
                continue
            job['status'] = 'stopped'
            job['error'] = reason
            job['current_stage'] = None
            ev = job.get('stop_event')
            if ev is None:
                ev = threading.Event()
                job['stop_event'] = ev
            ev.set()
            stopped.append({'id': jid, 'type': job_type})
            if save_fn:
                try:
                    save_fn(jid)
                except Exception as _exc:
                    _zyg_log.warning('state of %s job %s not saved after the stop: %s', job_type, jid, _exc)

    _stop_registry(_workflow_jobs, 'workflow')
    _stop_registry(_creature_gen_jobs, 'creature', _creature_save_state, ('creature_id',))
    _stop_registry(_char_gen_jobs, 'character', _char_save_state, ('char_id',))

    comfy_interrupted = False
    try:
        from zyg_workflows import _comfy_client as _cc_halt

        if _cc_halt.server_reachable(timeout_s=1.0):
            # Operator HALT is the one place a GLOBAL interrupt is wanted:
            # _comfy_client.interrupt_execution() now declines to touch
            # another client's job unless forced.
            comfy_interrupted = _cc_halt.interrupt_execution(force_global=True)
            _cc_halt.free_vram()
    except Exception as _exc:
        _zyg_log.warning('comfy interrupt/free_vram failed during halt, its job may keep running: %s', _exc)

    killed_pids = _kill_all_subprocs()

    try:
        _release_pipeline_vram('halt', log_fn=lambda m: _zyg_log.info(f'[HALT] {m}'), wait_comfy=False)
    except Exception as _exc:
        _zyg_log.warning('pipeline vram not released during halt: %s', _exc)

    ollama_evicted: list = []
    try:
        ollama_evicted = _evict_all_ollama_models(log_fn=lambda m: _zyg_log.info(f'[HALT] {m}'))
    except Exception as _exc:
        _zyg_log.warning('ollama models not evicted during halt, their vram stays held: %s', _exc)

    workers_stopped = 0
    try:
        from zyg_workflows import scholarly_stills_backend as _ssb_halt

        _fw = _ssb_halt.ScholarlyFluxWorker.get()
        if _fw.is_running_or_starting():
            _fw.emergency_stop(log_fn=lambda m: _zyg_log.info(f'[HALT] {m}'))
            workers_stopped = 1
    except Exception as _exc:
        _zyg_log.warning('scholarly flux worker not stopped during halt: %s', _exc)

    # Persist halt into Redis so zero_public_server stops dequeuing new jobs even
    # after a Flask restart.  Also drain any already-queued job_ids so they don't
    # run after the user clears the halt and resumes.
    queue_drained = 0
    try:
        import redis as _redis_halt

        _redis_url_h = os.environ.get('REDIS_URL', ZYG_REDIS_URL)
        _rh = _redis_halt.from_url(_redis_url_h, decode_responses=True, socket_connect_timeout=2)
        _rh.set('zpub:halted', '1')
        queue_drained = _rh.llen('zpub:queue')
        if queue_drained:
            _rh.delete('zpub:queue')
        _zyg_log.info(f'[HALT] zpub:halted set; drained {queue_drained} queued job(s) from Redis')
    except Exception as _rh_e:
        _zyg_log.info(f'[HALT] Redis halt-key warning (non-fatal): {_rh_e}')

    return {
        'stopped_jobs': stopped,
        'killed_pids': killed_pids,
        'comfy_interrupted': comfy_interrupted,
        'ollama_evicted': len(ollama_evicted),
        'workers_stopped': workers_stopped,
    }


def _clear_pipeline_halt() -> None:
    """Clear manual stop so a new pipeline run can proceed."""
    pass  # (global stmt removed: names moved to gui_state)
    from zyg_workflows import pipeline_control as _pc

    gui_state._pipeline_stop_flag = False
    _pc.clear_halt()
    # Also clear the Redis halt key so zero_public_server resumes dequeuing.
    try:
        import redis as _redis_clr

        _redis_url_c = os.environ.get('REDIS_URL', ZYG_REDIS_URL)
        _rc = _redis_clr.from_url(_redis_url_c, decode_responses=True, socket_connect_timeout=2)
        _rc.delete('zpub:halted')
    except Exception as _exc:
        _zyg_log.warning('redis halt key not cleared, zero public keeps refusing jobs: %s', _exc)


# The GUI-backed hooks the pipelines call through zyg_workflows.runtime. Their
# headless defaults (no session, no Redis halt key) are replaced here.
runtime.register(
    ensure_csrf_token=_ensure_csrf_token,
    zero_audit_log=_zero_audit_log,
    clear_pipeline_halt=_clear_pipeline_halt,
)


# 2026-07-17 heavy-tranche: zero_stop moved to bp_zero.py


# 2026-07-17 heavy-tranche: zero_stop_reset moved to bp_zero.py


# 2026-07-17 heavy-tranche: api_subprocesses moved to bp_pipeline_api.py


# 2026-07-17 heavy-tranche: get_subprocess_by_pid moved to bp_pipeline_api.py


# 2026-07-17 heavy-tranche: get_scp_config moved to bp_assets_media.py


# 2026-07-17 heavy-tranche: patch_scp_config moved to bp_assets_media.py


# ── Asset auto-downloader ─────────────────────────────────────────────────────
_ASSETS_SFX_DIR = str(_dash_paths.DATA_DIR / 'assets' / 'sfx')
_ASSETS_REACTION_DIR = str(_dash_paths.DATA_DIR / 'assets' / 'reaction_clips')

# 2026-07-17 heavy-tranche: _parse_sfx_catalogue moved to bp_assets_media.py

# 2026-07-17 heavy-tranche: _parse_reaction_catalogue moved to bp_assets_media.py

# 2026-07-17 heavy-tranche: _download_assets_background moved to bp_assets_media.py


# 2026-07-17 heavy-tranche: trigger_asset_download moved to bp_assets_media.py


# 2026-07-17 heavy-tranche: asset_status moved to bp_assets_media.py


# 2026-07-17 heavy-tranche: asset_preview moved to bp_assets_media.py


# 2026-07-17 heavy-tranche: api_rfd_clips moved to bp_assets_media.py


# 2026-07-17 heavy-tranche: api_scholarly_imagery moved to bp_assets_media.py


# 2026-07-17 heavy-tranche: api_scholarly_imagery_thumb moved to bp_assets_media.py


# ── Pipeline Stage Timeline API ───────────────────────────────────────────────
# 2026-07-17 heavy-tranche: api_pipeline_timeline moved to bp_pipeline_api.py


# 2026-07-17 heavy-tranche: api_pipeline_timeline_download moved to bp_pipeline_api.py


# 2026-07-17 heavy-tranche: api_pipeline_murch_debug moved to bp_pipeline_api.py


# 2026-07-17 heavy-tranche: api_pipeline_active moved to bp_pipeline_api.py


# 2026-07-17 heavy-tranche: api_pipeline_test moved to bp_pipeline_api.py


# 2026-07-17 heavy-tranche: api_scholarly_videos moved to bp_assets_media.py


# 2026-07-17 heavy-tranche: api_output_new_videos moved to bp_assets_media.py


_YT_UPLOAD_SCRIPT = os.path.expanduser('~/zygomatics-zero/youtube/upload.py')
_YT_VENV_PYTHON = os.path.expanduser('~/zygomatics-zero/venv/bin/python')
# noqa below: this is the PATH of the OAuth token file, not a token. The credential
# itself lives in that pickle, outside the tree, and is never read in this module.
_YT_TOKEN_FILE = os.path.expanduser('~/zygomatics-zero/youtube/token.pickle')  # noqa: S105  a file path, not a secret


# 2026-07-17 heavy-tranche: api_youtube_channel_videos moved to bp_assets_media.py


# 2026-07-17 heavy-tranche: api_marketing_upload moved to bp_assets_media.py


# 2026-07-17 heavy-tranche: api_voices moved to bp_voices.py


# 2026-07-17 heavy-tranche: api_voices_channel_assignments moved to bp_voices.py


# 2026-07-17 heavy-tranche: api_voices_assign moved to bp_voices.py


# 2026-07-17 heavy-tranche: api_voices_play moved to bp_voices.py


# 2026-07-17 heavy-tranche: api_sources moved to bp_voices.py


# 2026-07-17 heavy-tranche: api_court_cases moved to bp_voices.py


# 2026-07-17 heavy-tranche: api_asset_manager_prompts moved to bp_assets_media.py


# 2026-07-17 heavy-tranche: api_prompt_registry_update moved to bp_assets_media.py


# 2026-07-17 heavy-tranche: api_prompt_registry_revert moved to bp_assets_media.py


# ══════════════════════════════════════════════════════════════════════════════
# CLAUDE COLLABORATION LAYER
#   Phase 1 → analyze_video_for_claude()   → analysis_bundle.json
#   Phase 3 → execute_claude_clip_plan()   → rendered clips
#             execute_sfx_plan()           → SFX-mixed clips
#             execute_caption_plan()       → captioned clips
# ══════════════════════════════════════════════════════════════════════════════

# (_ccl_re / _ccl_json / _ccl_threading, this section's aliased stdlib re-exports, are
# imported with the rest of the import block at the top of the file.)

# Never made here: importing a module must not touch the filesystem. Both render
# entry points already create it at the write site — bp_claude_clip.py's
# _render_clip_direct() and execute_claude_clip_plan() each `os.makedirs` the output
# directory they derived from this base, and makedirs creates the parents.
_CCL_OUTPUT_BASE = str(_dash_paths.DATA_DIR / 'output' / 'claude_clips')


# Token usage log — in-memory list + persisted to data/runtime/token_usage.json
# 2026-07-17 heavy-tranche: _TOKEN_USAGE_LOG moved to bp_claude_clip.py
_TOKEN_USAGE_LOCK = threading.Lock()
_TOKEN_USAGE_PATH = str(_dash_paths.DATA_DIR / 'runtime' / 'token_usage.json')
# Context ledger — permanent JSONL, never rotated, survives months/years
_CONTEXT_LEDGER_PATH = str(_dash_paths.DATA_DIR / 'runtime' / 'context_ledger.jsonl')

_MODEL_CTX_WINDOWS = {
    'gpt-4o': 128_000,
    'gpt-4o-mini': 128_000,
    'o1': 128_000,
    'o1-mini': 128_000,
    'claude-sonnet-4-6': 200_000,
    'claude-sonnet-4': 200_000,
    'claude-3-7-sonnet': 200_000,
    'claude-3-5-sonnet': 200_000,
    'claude-3-5-haiku': 200_000,
    'claude-3-opus': 200_000,
    'claude-3-haiku': 200_000,
    'claude-opus': 200_000,
    'claude-sonnet': 200_000,
    'claude-haiku': 200_000,
    'gemini-1.5-pro': 1_000_000,
    'gemini-1.5-flash': 1_000_000,
    'gemini-2-flash': 1_000_000,
    'llama3:70b': 8_000,
    'mistral:7b': 8_000,
    'qwen3.6:35b-a3b': 262_000,
    'gpt-oss:20b': 128_000,
    'qwen3.5:9b': 262_000,
}

# 2026-07-17 heavy-tranche: _record_token_usage moved to bp_claude_clip.py

# Aspect-ratio ffmpeg video-filter map
_CCL_AR_VF = {
    '9:16': 'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30',
    '1:1': 'scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080,fps=30',
    '16:9': 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30',
}
