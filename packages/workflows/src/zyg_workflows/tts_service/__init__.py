# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401, E402  # this module IS the re-export namespace of the pre-split tts_service.py.

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).

import json
import os
import re
import shutil
import subprocess
import time
from zyg_workflows import gui_state

# 2026-07-17 batch-2 fix: subproc helpers moved to subproc_registry (direct import —
# main's re-export binds too late for the engine import chain)
from zyg_workflows.subproc_registry import _register_subproc, _finish_subproc
from zyg_workflows.pipeline_config import (
    _DEMONET_TIER1,
    _DEMONET_TIER2,
    _DEMONET_TIER3_TITLE,
    _TITLE_SYNONYMS,
)


# ── voice seed pool ─────────────────────────────────────────────────────────
# Moved to voice_pool.py (2026-08-12) and re-imported here under the SAME private
# names, so every existing caller — including `_tts._voice_seed_for(...)` in
# briefing_video — keeps working unchanged.
#
# The move exists because this module imports Flask and crewai_web_gui at module
# scope, which made the pick unreachable from anything that is not the web app.
# The Voices tab has to answer "which seed does this character's voice id
# actually resolve to?" before it can show a connection, and a second copy of a
# gender-filtered md5 over a manifest is a silent-wrong-answer machine: both
# copies look right until the pool gains a seed. One implementation, two callers.
from zyg_workflows.voice_pool import (  # noqa: E402  (kept alongside the other late imports)
    _SEED_POOL_DIR,
    _voice_seed_for,
)
import logging as _zyg_logging
from zyg_workflows import paths
from zyg_workflows.bin import exe

from .constants import (
    _zyg_log,
    _TTS_MAX_CHARS,
    _TTS_LOUDNORM,
    _ROMAN_VALUES,
    _ROMAN_CANON,
    _ROMAN_CARDINAL_BEFORE,
    _ROMAN_MAX,
    _ORD_UNITS,
    _CARD_UNITS,
    _CARD_TENS,
    _ORD_TENS,
)
from .text import (
    _roman_to_int,
    _int_to_cardinal,
    _int_to_ordinal,
    _expand_roman_numerals,
    _tts_clean_text,
    _tts_split_sentences,
    _tts_chunk_text,
    _tts_trim_edge_silence,
)
from .engines import (
    _INDEXTTS_DIR,
    _INDEXTTS_PY,
    _INDEXTTS_WORKER,
    _CHATTERBOX_DIR,
    _CHATTERBOX_PY,
    _CHATTERBOX_WORKER,
    _TTS_TASKSET_CORES,
    _TTS_WORKER_THREADS,
    _tts_worker_env,
    _tts_run_worker,
    _tts_batch_file,
    _GPU_PROBE,
    _gpu_usable,
    _tts_timeout_for,
    _indextts_segments,
    _chatterbox_installed,
    _chatterbox_segments,
    _TTS_SEG_NAME_RE,
    _tts_segment_indices,
    _tts_loudnorm_targets,
    _tts_measure_loudness,
    _tts_assemble,
)
from .asr import (
    _ASR_NUM_WORDS,
    _asr_tokens,
    _asr_similarity,
    _asr_inserted_run,
    _asr_missing_names,
    _tts_asr_read_back,
)
from .shared import (
    _tts_shared,
    _mask_bad_words,
    _sanitize_title,
    _bleep_audio_in_clip,
    _selected_voice_id,
    _synthesise_tts,
)
