# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Scholarly FLUX A/B benchmark — in-process diffusers vs ComfyUI + realistic concurrent load.

Modes (``ZYG_BENCH_PARITY``):
  - ``0`` (default): fast smoke — txt2img Comfy, optional CN on diffusers.
  - ``1``: production parity — character bible + ControlNet pose on BOTH backends,
    Comfy ``flux_pose_ipa_cell``, per-slot VRAM clear (``ZYG_COMFY_CLEAR_VRAM_BETWEEN_SLOTS``).

Production default is hardcoded diffusers (``scholarly_stills_backend``).
Comfy leg mirrors ``ZYG_SCHOLARLY_COMFY_IMAGES=1`` curation only (~6.5× slower).

Mode 3 — Realistic Concurrent (``ZYG_BENCH_REALISTIC=1``):
  Simulates N full documentary pipelines competing for SCHOLARLY_GPU_LOCK.
  Uses real FLUX load/unload per pipeline (current production pattern).
  Numbers derived from benchmark_telemetry.json (12-pipeline sample):
    Pre-Stage-3.5: ~118s  (research 4s + script 88s + tagging 21s + emotion 5s)
    Images/pipeline: ~28  (328 images / ~12 pipelines with successful FLUX)
    Per-image isolated: 17.06s (parity benchmark 2026-06-03)
  Tracks VRAM free after every load/teardown to measure fragmentation.

  ZYG_BENCH_REALISTIC=1 \\
    [ZYG_BENCH_N_PIPELINES=6]          default: 6 \\
    [ZYG_BENCH_STAGGER_S=30]           default: 30 (current production stagger) \\
    [ZYG_BENCH_IMAGES_PER_PIPELINE=28] default: 28 (from telemetry) \\
    [ZYG_BENCH_PRE_FLUX_S=118]         default: 118 (from telemetry) \\
    ../.venv/bin/python scripts/scholarly_flux_ab_benchmark.py

Mode 4 — Persistent Worker (``ZYG_BENCH_PERSISTENT=1``):
  Same load as Mode 3 but with a single shared FLUX worker (proposed fix).
  Load once → queue all N*M image jobs → single worker generates → unload once.
  Eliminates repeated VRAM load/teardown cycles. Compare directly against Mode 3.

  ZYG_BENCH_PERSISTENT=1 \\
    [ZYG_BENCH_N_PIPELINES=6] [ZYG_BENCH_STAGGER_S=30] \\
    [ZYG_BENCH_IMAGES_PER_PIPELINE=28] [ZYG_BENCH_PRE_FLUX_S=118] \\
    ../.venv/bin/python scripts/scholarly_flux_ab_benchmark.py

Usage:
  cd "${ZYG_CREWS_ROOT:-$HOME/Zygomatic Full/agents/crews}"
  ../.venv/bin/python scripts/scholarly_flux_ab_benchmark.py

  # Production-parity A/B (recommended before enabling Comfy default):
  ZYG_BENCH_PARITY=1 \\
    ../.venv/bin/python scripts/scholarly_flux_ab_benchmark.py

  # Optional overrides (defaults: char 1a2b6cfc0f93 + bundled pose skeleton):
  ZYG_BENCH_CHAR_ID=<char_id> ZYG_BENCH_POSE_SKELETON=/path/to/skeleton.png \\
    ZYG_BENCH_PARITY=1 ../.venv/bin/python scripts/scholarly_flux_ab_benchmark.py

Output: data/runtime/scholarly_flux_ab_<timestamp>.json
"""

# ruff: noqa: F401,E402  # re-export surface: every name the pre-split script defined

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import logging as _zyg_logging

from zyg_workflows import paths

from .bench_assets import (
    _zyg_log,
    _CREWS,
    _FLUX_PATH,
    _OUT_ROOT,
    _STEPS,
    _CFG,
    _H,
    _W,
    _PARITY,
    _REALISTIC,
    _PERSISTENT,
    _REALISTIC_N_PIPELINES,
    _REALISTIC_STAGGER_S,
    _REALISTIC_IMAGES,
    _REALISTIC_PRE_FLUX_S,
    _PARITY_SUBJ_KEY,
    _BENCH_DEFAULT_CHAR_ID,
    _BENCH_POSE_SKELETON_ASSET,
    BENCH_SLOTS,
    _log,
    _stop_flask_dashboards_for_benchmark,
    _gpu_exclusivity_sweep,
    _REF_IMAGE_NAMES,
    _char_reference_image,
    _resolve_bench_char_id,
    _find_bench_reference,
    _load_bench_bible,
    _ensure_bench_pose_skeleton_asset,
    _stage_pose_image,
    _qa_score,
)
from .slots import (
    _build_diffusers_prompt,
    _load_diffusers_stack,
    _load_pose_pil,
    _run_diffusers_slot,
    _run_comfy_slot,
    _teardown_diffusers,
    _summarize_rows,
    _vram_free_gb,
)
from .concurrency import _run_realistic_concurrent, _run_persistent_worker
from .cli import main
