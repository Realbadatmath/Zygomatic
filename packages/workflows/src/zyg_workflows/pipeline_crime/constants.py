# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).
import json
import os
import threading
import requests

from zyg_workflows import gui_state, paths

from zyg_workflows import runtime as _runtime
from zyg_workflows.pipeline_common import _align_narration_word_timings, _normalize_word_timings_for_subs
from zyg_workflows.net import safe_urlopen
from zyg_workflows import provenance_seal as _seal
from zyg_workflows.stage_runner import (
    _build_framework_block,
    _classify_subject_type,
    _log_prompt,
    _register_prompt,
    _scp_output_to_windows,
)
from zyg_workflows.subproc_registry import _finish_subproc, _register_marker, _register_subproc, _update_marker
from zyg_workflows.tts_service import _mask_bad_words, _tts_shared
from zyg_workflows.vram_manager import _hw_monitor_loop, _wait_for_vram, _wait_ollama_unload
from zyg_workflows.pipeline_config import (
    _CHANNEL_VOICES_PATH,
    _LARGE_MODEL_THRESHOLD_GB,
    _MODEL_VRAM_GB,
    _RUNTIME_DIR,
    _VOICE_LIBRARY_PATH,
    _caveman_kw,
    _dsl,
)
from zyg_workflows.runtime import (
    _agent_log,
    _ams_iso,
    _ams_now,
    _large_llm_semaphore,
    _ollama_semaphore,
    _parse_iso_to_ams,
    _push_error_log,
    _runtime_path,
    workflow_jobs as _workflow_jobs,
)
import logging as _zyg_logging
from zyg_workflows.bin import exe


# ruff: noqa: F401  this module IS the original top import block; its siblings and the
# package __init__ re-import every name from here, so nothing above is unused.

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_crime')


# Use crewai.LLM directly — it wraps LiteLLM and talks to Ollama via the
# 'ollama/model' prefix. Bound the way the GUI bound it (this module read these
# two names off the GUI module until the 2026-10-05 layering split).
try:
    from crewai import LLM as Ollama

    try:
        safe_urlopen(paths.ZYG_OLLAMA_URL + '/api/tags', timeout=3)
        OLLAMA_AVAILABLE = True
    except Exception:
        OLLAMA_AVAILABLE = False
except ImportError:
    Ollama = None
    OLLAMA_AVAILABLE = False

# Read off the GUI module, which never defined it — so it has always been None.
topic = None
