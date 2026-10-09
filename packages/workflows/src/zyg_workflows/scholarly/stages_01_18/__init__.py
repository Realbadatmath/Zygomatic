# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stages 1-9 of the scholarly pipeline — topic setup through the time-locked scenes.

A pure move out of `_run_scholarly_pipeline` in `zyg_workflows.pipeline_scholarly`:
the statements, their order and their side effects are the ones the monolith ran.
Only three things changed, and each one is forced by the move:

* a local that crosses a stage boundary is read and written as `ctx.<name>`
  (`zyg_workflows.scholarly.context.RunContext`);
* a local that a nested `def`/`lambda` of the stage closes over is re-bound to a
  plain local at the top of the stage (`topic = ctx.topic`), because a closure
  cannot capture an attribute — the object is the same one;
* `__file__` became `_PKG_DIR`. In the monolith `os.path.dirname(__file__)` was
  the `zyg_workflows` package directory; from this sub-package it would be
  `zyg_workflows/scholarly`, so the two sites that used it got the constant.

The import of `pipeline_scholarly` at the bottom of the import block is why the
monolith imports *this* module lazily, inside the function: a module-level
import in both directions would close the cycle.

See SPLIT_LOG.md for the stage→marker map and the full list of non-mechanical spots.
"""

# ruff: noqa: F401

from ._common import (
    _LLM_LARGE,
    _LLM_SCRIPT,
    _LLM_SMALL,
    _MURCH_MODEL,
    _OLLAMA_BASE_URL,
    _PKG_DIR,
    _SCHOLARLY_SEC_PER_WORD,
    _align_narration_word_timings,
    _bench_replay_get,
    _build_framework_block,
    _classify_subject_type,
    _dsl,
    _llm_client,
    _llm_key,
    _log_prompt,
    _murch_ollama_text,
    _record_token_usage,
    _register_prompt,
    _research_title_matches_directive,
    _scholarly_n_images,
    _title_from_directive,
    _tts_shared,
    _update_marker,
    _zyg_log,
    _zyg_logging,
    exe,
    gui_state,
    json,
    os,
    re,
    requests,
    safe_urlopen,
    time,
    traceback,
)
from .stages_01_02 import stage_01_topic_setup, stage_02_academic_research
from .stage_03_cleaners import _script_cleaners
from .stage_03 import stage_03_script_preparation
from .stage_04 import stage_04_fact_check
from .stage_05 import stage_05_visual_intent_tagging
from .stages_06_07 import (
    stage_06_turning_points_and_emotions,
    stage_07_emotion_curve,
)
from .stage_08 import stage_08_tts_pre_image_pass
from .stage_09 import stage_09_time_locked_scene_descriptions
