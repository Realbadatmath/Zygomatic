# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""vlm_inspector.py — local VLM checklist judging of render output (2026-07-30).

The visual half of the QC battery: pipeline_debug measures PIXELS (flow, churn,
NCC, identity embeddings), this module asks a local Apache-2.0 Qwen3-VL judge
BINARY questions about what is actually in the frame ("is a hand covering the
pipe bowl?"). The two are complementary and deliberately non-overlapping —
temporal defects stay with the pixel metrics (video-LLMs fail temporal
perception; TempCompass), semantic/prompt-adherence defects are where the VLM
is strongest (Spotlight arXiv:2511.18102).

DESIGN RULES BAKED IN HERE (all evidence-backed, 2026-07-30 research pass):
  * Checklists are DATA (config/vlm_checklists.json), one atomic yes/no question
    per failure class — never an open "find the errors" prompt (open prompts
    match ~13% of human-found errors; per-class decomposition ~doubles a local
    8B judge to frontier parity).
  * The judge is a REJECT-ONLY second opinion. It can never override a pixel
    gate, and every failure path returns a fail-safe pass so a broken judge can
    never break a render.
  * TWO TIERS. 'boundary' = the strongest quantized judge, run ALONE at pipeline
    pause points behind comfy_offload.gpu_exclusive (ComfyUI is offloaded, then
    lazily reloads on the next job, ~1-3 min swap). 'resident'/'cpu' = a small
    judge that never threatens the render's ~33 GB.
  * NEVER while ComfyUI is sampling. Any GPU tier refuses (gracefully, skipped)
    when comfy_offload.comfy_is_sampling() is True — freeing or squeezing VRAM
    mid-sample kills an uninterruptible 90-minute render.
  * The model itself runs in an ISOLATED venv (models/vlm_judge/.venv) as a
    subprocess, exactly like models/diarization — transformers/bitsandbytes
    never touch the production venv, and vLLM is disqualified for residency
    (it preallocates GPU memory).

Typical use::

    from zyg_workflows import vlm_inspector as VLM
    res = VLM.inspect_clip(probe_clip, [0.5, 2.0, 4.0], checklist='scene20_binary',
                           tier='boundary', ref_images=refs, log_fn=log)
    if res['criticals']:
        ...   # reject
    box = res['bboxes'].get('hand_covers_bowl')   # feed region repair

Env knobs:
  ZYG_VLM                 "0" disables every inspection (returns skipped)
  ZYG_VLM_HOME            override models/vlm_judge
  ZYG_VLM_BOUNDARY_MODEL  repo id for the boundary tier
  ZYG_VLM_RESIDENT_MODEL  repo id for the resident/cpu tier
  ZYG_VLM_BOUNDARY_QUANT / ZYG_VLM_RESIDENT_QUANT   worker --quantization value
  ZYG_VLM_STRICT          "1" -> 'major' failures are fatal too
  ZYG_VLM_K               k-ensemble repeats per inspection (default 1)
  ZYG_VLM_TIMEOUT         worker subprocess timeout seconds (per tier default)
  ZYG_VLM_CPU_WHEN_BUSY   "1" -> downshift to CPU instead of skipping while
                          ComfyUI samples (slow; off by default)
  ZYG_VLM_QPAYLOAD        "list" (default) or "dict" — questions-file shape
  ZYG_VLM_KEEP_FRAMES     "1" -> keep the extracted frame tempdir for forensics
"""

# The package re-exports the pre-split module namespace (declared in __all__ below).

import atexit
import collections
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import logging as _zyg_logging
from zyg_workflows import paths
from zyg_workflows.bin import exe

from zyg_workflows.vlm_inspector import base
from zyg_workflows.vlm_inspector import judge_server
from zyg_workflows.vlm_inspector import api

from zyg_workflows.vlm_inspector.base import (
    _zyg_log,
    _DIR,
    VLM_HOME,
    _VLM_PY,
    _VLM_WORKER,
    _MODELS_JSON,
    _CHECKLIST_PATH,
    BOUNDARY_MODEL,
    RESIDENT_MODEL,
    CPU_MODEL,
    TIER_ORDER,
    TIERS,
    _ANSWER_YES,
    _ANSWER_NO,
    _mklog,
    _enabled,
    _strict,
    _skipped,
    available,
    _models_json,
    _as_model_id,
    model_for,
    _quant_for,
    _timeout_for,
    load_checklist,
    _select_items,
    _questions_payload,
    _norm_answer,
)
from zyg_workflows.vlm_inspector.judge_server import (
    _PERSIST_DEFAULT_TIERS,
    _SERVERS,
    _SERVERS_LOCK,
    _persist_enabled,
    _JudgeServer,
    _get_server,
    _retire_server,
    shutdown_workers,
    _run_worker,
    _aggregate,
)
from zyg_workflows.vlm_inspector.api import (
    _downshift,
    inspect_frames,
    _execute,
    _clip_duration_s,
    extract_frames,
    inspect_clip,
    summarize,
)


# The re-exported surface of the pre-split module, in import order: every name
# here exists only so that `<this module>.<name>` keeps resolving for importers.
__all__ = [
    'atexit',
    'collections',
    'json',
    'os',
    'queue',
    'subprocess',
    'sys',
    'tempfile',
    'threading',
    'time',
    '_zyg_logging',
    'paths',
    'exe',
    'base',
    'judge_server',
    'api',
    '_zyg_log',
    '_DIR',
    'VLM_HOME',
    '_VLM_PY',
    '_VLM_WORKER',
    '_MODELS_JSON',
    '_CHECKLIST_PATH',
    'BOUNDARY_MODEL',
    'RESIDENT_MODEL',
    'CPU_MODEL',
    'TIER_ORDER',
    'TIERS',
    '_ANSWER_YES',
    '_ANSWER_NO',
    '_mklog',
    '_enabled',
    '_strict',
    '_skipped',
    'available',
    '_models_json',
    '_as_model_id',
    'model_for',
    '_quant_for',
    '_timeout_for',
    'load_checklist',
    '_select_items',
    '_questions_payload',
    '_norm_answer',
    '_PERSIST_DEFAULT_TIERS',
    '_SERVERS',
    '_SERVERS_LOCK',
    '_persist_enabled',
    '_JudgeServer',
    '_get_server',
    '_retire_server',
    'shutdown_workers',
    '_run_worker',
    '_aggregate',
    '_downshift',
    'inspect_frames',
    '_execute',
    '_clip_duration_s',
    'extract_frames',
    'inspect_clip',
    'summarize',
]
