# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
murch_engine.py — Cinematic editing intelligence inspired by Walter Murch's "In the Blink of an Eye"

Implements the 4-layer plan:
  Layer 1 — Better Data      : cascading emotion scorer, arc smoothing, Whisper timestamps
  Layer 2 — Smarter Images   : scene type classifier, shot grammar, counterpoint mode, seed anchoring
  Layer 3 — Better Cuts      : saliency focal points, composition constraints, xfade transitions, RMS rhythm
  Layer 4 — Feedback Loop    : post-render LLM self-evaluation

All public functions return (result, debug_log) where debug_log is a list of dicts:
  {'ts': ISO, 'fn': function_name, 'level': 'DEBUG'|'INFO'|'WARN'|'ERROR', 'msg': str, 'data': any}

This lets the pipeline record every decision made for full traceability.
"""

from __future__ import annotations
import os
import re
import json
import time
import hashlib
import difflib
import logging
import traceback
from datetime import datetime, timezone
from typing import Any

from zyg_workflows.net import safe_urlopen
from zyg_workflows import paths
import logging as _zyg_logging

# This __init__ re-exports the pre-split module namespace
# and imports the section modules below the original top import block.
# Section modules, imported in the original section order so that module-level
# side effects still run in the order murch_engine.py ran them.
from zyg_workflows.murch_engine.base import (
    MURCH_LLM_MODEL,
    _MURCH_RUNTIME_DIR,
    _ollama_response_text,
    _log_ollama_prompt,
    _ts,
    _dbg,
    logger,
)
from zyg_workflows.murch_engine.emotion import (
    _EMOTION_KEYWORDS,
    _NEGATION_WORDS,
    _EMOTION_ANCHOR_TEXTS,
    _ST_MODEL,
    _EMOTION_ANCHORS,
    _load_st_model,
    _get_emotion_anchors,
    _keyword_score,
    _embedding_score,
    _llm_score,
    _cascade_score_sentence,
    _ollama_llm_available,
    extract_emotion_curve,
)
from zyg_workflows.murch_engine.arc import (
    smooth_emotion_curve,
    detect_arc_turning_points,
    get_arc_zone,
)
from zyg_workflows.murch_engine.alignment import (
    script_words_from_narration,
    alignment_coverage,
    align_script_to_word_timings,
    _forced_align_words,
    extract_word_timestamps_whisper,
)
from zyg_workflows.murch_engine.images import (
    _SCENE_TYPE_KEYWORDS,
    _SCENE_WEIGHT_PROFILES,
    classify_scene_type,
    _SHOT_GRAMMAR_SEQUENCE,
    _SHOT_GRAMMAR_STATE,
    get_shot_type_grammar,
    _CONSECUTIVE_ILLUSTRATIVE,
    should_apply_counterpoint,
    reset_counterpoint_state,
    _COUNTERPOINT_PROMPTS,
    build_counterpoint_prompt,
    _ENTITY_SEEDS,
    get_entity_seed,
    reset_entity_seeds,
)
from zyg_workflows.murch_engine.cuts import (
    extract_focal_point,
    extract_focal_points_batch,
    _ZONE_COORDS,
    _COMPOSITION_CONSTRAINTS,
    get_composition_constraint,
    _TRANSITION_TABLE,
    _SHOT_TRANSITION_OVERRIDES,
    _HARD_CUT_EMOTIONS,
    _DEFAULT_TRANSITION,
    _shot_tightness,
    get_transition,
    build_xfade_filter_graph,
    extract_audio_rhythm,
)
from zyg_workflows.murch_engine.feedback import (
    self_evaluate_sequence,
    run_full_murch_pass,
)

_zyg_log = _zyg_logging.getLogger(__name__)


# ── re-export surface ─────────────────────────────────────────────────────────
# Every name below is imported above and not used in this module: this file
# exists so that ``zyg_workflows.murch_engine.<name>``
# resolves exactly as it did on the pre-split single-file module.
# Nothing does ``import *`` from here.
__all__ = [
    'os',
    're',
    'json',
    'time',
    'hashlib',
    'difflib',
    'logging',
    'traceback',
    'datetime',
    'timezone',
    'Any',
    'safe_urlopen',
    'paths',
    'MURCH_LLM_MODEL',
    '_MURCH_RUNTIME_DIR',
    '_ollama_response_text',
    '_log_ollama_prompt',
    '_ts',
    '_dbg',
    'logger',
    '_EMOTION_KEYWORDS',
    '_NEGATION_WORDS',
    '_EMOTION_ANCHOR_TEXTS',
    '_ST_MODEL',
    '_EMOTION_ANCHORS',
    '_load_st_model',
    '_get_emotion_anchors',
    '_keyword_score',
    '_embedding_score',
    '_llm_score',
    '_cascade_score_sentence',
    '_ollama_llm_available',
    'extract_emotion_curve',
    'smooth_emotion_curve',
    'detect_arc_turning_points',
    'get_arc_zone',
    'script_words_from_narration',
    'alignment_coverage',
    'align_script_to_word_timings',
    '_forced_align_words',
    'extract_word_timestamps_whisper',
    '_SCENE_TYPE_KEYWORDS',
    '_SCENE_WEIGHT_PROFILES',
    'classify_scene_type',
    '_SHOT_GRAMMAR_SEQUENCE',
    '_SHOT_GRAMMAR_STATE',
    'get_shot_type_grammar',
    '_CONSECUTIVE_ILLUSTRATIVE',
    'should_apply_counterpoint',
    'reset_counterpoint_state',
    '_COUNTERPOINT_PROMPTS',
    'build_counterpoint_prompt',
    '_ENTITY_SEEDS',
    'get_entity_seed',
    'reset_entity_seeds',
    'extract_focal_point',
    'extract_focal_points_batch',
    '_ZONE_COORDS',
    '_COMPOSITION_CONSTRAINTS',
    'get_composition_constraint',
    '_TRANSITION_TABLE',
    '_SHOT_TRANSITION_OVERRIDES',
    '_HARD_CUT_EMOTIONS',
    '_DEFAULT_TRANSITION',
    '_shot_tightness',
    'get_transition',
    'build_xfade_filter_graph',
    'extract_audio_rhythm',
    'self_evaluate_sequence',
    'run_full_murch_pass',
]
