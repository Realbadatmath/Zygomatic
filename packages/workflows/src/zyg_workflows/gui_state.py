# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared mutable pipeline/GPU state (2026-07-17 modularization).

Every name here was previously a module-global in crewai_web_gui.py that was
REBOUND at runtime via `global` statements. Cross-module code must read/write
these ONLY as gui_state.<name> attributes (from-imports would go stale).
crewai_web_gui.py assigns the real initial values at its original code positions;
the defaults below only cover reads that happen before those lines run.

2026-10-05 layering: moved from `zyg_dashboard` to `zyg_workflows`. Despite the
name, this is the pipeline/GPU state the pipelines own, not GUI state, and the
base library may not import the dashboard. `zyg_dashboard.gui_state` is now a
shim that aliases this very module, so both paths share one set of rebindings.
"""

_ALL_TOOLS = None
_CALIBRATION = None
_CHAR_GEN_BACKFILL_DONE = None
_CHAR_GEN_RELOAD_DONE = None
_CHAR_PREVIEW_SWEEP = None
_CN_PIPE_CACHE = None
_CONTACT_SHEET_RELOAD_DONE = None
_CREATURE_GEN_RELOAD_DONE = None
_FLUX_DEV_PIPELINE_CACHE = None
_FLUX_PIPELINE_CACHE = None
_PREVIEW_FACE_YOLO = None
_PREVIEW_HAND_YOLO = None
_TELEMETRY_LOG_PIPELINE_ID = None
_ZERO_RAM_GATE_HOLDING = None
_bench_replay_cache = None
_hw_block_active = None
_hw_block_reason = None
_pipeline_stop_flag = None
