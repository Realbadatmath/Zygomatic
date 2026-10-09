# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The crime department pipeline — ``_run_crime_pipeline``, as a package.

Was pipeline_crime.py (2,159 lines), one 2,085-line function. Split at its own stage
banners; the import path and every module attribute are unchanged:

* :mod:`.constants` — the original header and top import block, logger included
* :mod:`.stages_1_2` — Stage 1 case selection, Stage 2 document research
* :mod:`.stage3_script` — Stage 3 narration script (Haiku/Claude/GPT/Ollama + fallback)
* :mod:`.stage3b_to_6b` — Stage 3b tags, Stage 4 TTS, Stage 5, Stage 6a SRT, Stage 6b doc cards
* :mod:`.stage6_segments` — Stage 6c segment renderers and person info-box clips
* :mod:`.stage6_assembly` — Stage 6d timeline, concat, fallback card, loudnorm
* :mod:`.pipeline` — the orchestrator that calls the stages in the original order

Contract, unchanged: imported only at the BOTTOM of crewai_web_gui.py.
"""

# ruff: noqa: F401  the package re-exports the single module's whole namespace

from . import constants
from .constants import (
    OLLAMA_AVAILABLE,
    Ollama,
    _CHANNEL_VOICES_PATH,
    _LARGE_MODEL_THRESHOLD_GB,
    _MODEL_VRAM_GB,
    _RUNTIME_DIR,
    _VOICE_LIBRARY_PATH,
    _agent_log,
    _align_narration_word_timings,
    _ams_iso,
    _ams_now,
    _build_framework_block,
    _caveman_kw,
    _classify_subject_type,
    _dsl,
    _finish_subproc,
    _hw_monitor_loop,
    _large_llm_semaphore,
    _log_prompt,
    _mask_bad_words,
    _normalize_word_timings_for_subs,
    _ollama_semaphore,
    _parse_iso_to_ams,
    _push_error_log,
    _register_marker,
    _register_prompt,
    _register_subproc,
    _runtime,
    _runtime_path,
    _scp_output_to_windows,
    _seal,
    _tts_shared,
    _update_marker,
    _wait_for_vram,
    _wait_ollama_unload,
    _workflow_jobs,
    _zyg_log,
    _zyg_logging,
    exe,
    gui_state,
    json,
    os,
    paths,
    requests,
    safe_urlopen,
    threading,
    topic,
)
from . import stages_1_2, stage3_script, stage3b_to_6b, stage6_segments, stage6_assembly, pipeline
from .pipeline import _run_crime_pipeline
