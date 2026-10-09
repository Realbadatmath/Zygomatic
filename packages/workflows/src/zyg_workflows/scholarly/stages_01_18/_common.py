# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared imports, logger and package-directory constant for the stage modules.

The import block, the logger name and `_PKG_DIR` are the ones
`scholarly/stages_01_18.py` carried before it became this package: every stage
module pulls what it needs from here, so the names stay bound exactly once.
"""

# ruff: noqa: F401  # this module IS the original import block; every name is re-exported

import json
import logging as _zyg_logging
import os
import re
import time
import traceback

import requests

from zyg_workflows import gui_state
from zyg_workflows.murch_engine import (
    MURCH_LLM_MODEL as _MURCH_MODEL,
    _ollama_response_text as _murch_ollama_text,
)
from zyg_workflows.bin import exe
from zyg_workflows.net import safe_urlopen
from zyg_workflows.pipeline_common import _align_narration_word_timings
from zyg_workflows.pipeline_config import _OLLAMA_BASE_URL, _dsl
from zyg_workflows.runtime import _bench_replay_get, _record_token_usage
from zyg_workflows.stage_runner import (
    _build_framework_block,
    _classify_subject_type,
    _log_prompt,
    _register_prompt,
)
from zyg_workflows.subproc_registry import _update_marker
from zyg_workflows.subscription_llm import (
    MODEL_LARGE as _LLM_LARGE,
    MODEL_SCRIPT as _LLM_SCRIPT,
    MODEL_SMALL as _LLM_SMALL,
    anthropic_client as _llm_client,
    api_key_or_login as _llm_key,
)
from zyg_workflows.tts_service import _tts_shared

# Same logger name the statements had in pipeline_scholarly, so the
# 'suppressed ...' debug lines of a run keep landing under one name.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_scholarly')

# What `os.path.dirname(__file__)` meant to these statements before the move:
# the zyg_workflows package directory — two levels above this module, which sits
# one directory deeper than the pre-split `scholarly/stages_01_18.py` did.
_PKG_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Imported last and read lazily by the stages above: `pipeline_scholarly` does
# not import this module at module level, so this direction is not a cycle.
from zyg_workflows.pipeline_scholarly import (  # noqa: E402
    _SCHOLARLY_SEC_PER_WORD,
    _research_title_matches_directive,
    _scholarly_n_images,
    _title_from_directive,
)
