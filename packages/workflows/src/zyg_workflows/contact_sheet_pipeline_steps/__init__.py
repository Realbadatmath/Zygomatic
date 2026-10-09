# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Steps of the contact sheet pipeline.

A pure structural split of the long functions in `contact_sheet_pipeline`:
each coherent block became a named `step_*` function with explicit arguments,
and the state a group of blocks shares — the locals the old inline code reached
through `nonlocal` — travels in one dataclass (`CellRun`, `AnchorCtx`). No gate,
threshold, prompt, log line or order changed.

`run_anchor_gates` calls the cell-00 gates in the order they had inline:
  face extraction -> style gate -> skin luminance gate -> cross-character dedup
  -> attribute compliance -> dedup re-check -> structure compliance
  -> side-profile anchor -> full-body outfit anchor
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from typing import Any, Callable
import logging as _zyg_logging

from zyg_workflows import contact_sheet_pipeline as _csp
from zyg_workflows import provenance_seal as _seal

_zyg_log = _zyg_logging.getLogger(__name__)

# ruff: noqa: E402,F401
# The submodules are imported in the original section order of the pre-split file.
from .anchor_ctx import AnchorCtx, _reinstall_anchor, _anchor_style_check, _dedup_candidates, _dedup_most_similar
from .anchor_identity_gates import step_anchor_face, step_style_gate, step_skin_luminance_gate
from .anchor_dedup_gate import step_dedup_gate
from .anchor_attribute_gate import step_attribute_gate, _attr_sync_verdict, step_dedup_recheck
from .anchor_structure_gates import step_structure_gate, step_profile_anchor, step_body_anchor, run_anchor_gates
from .cell_plan import CellRun, step_engine_gate, step_build_cell_plan, step_cell_conditioning
from .cell_generation import (
    step_identity_locks,
    step_cells_dir,
    step_resume_cell,
    step_cell_prompt,
    step_cell_gen_kwargs,
    step_closeup_crop,
    run_cell0_gates,
)
from .sheet_finalize import (
    step_finalize_sheet,
    step_expansion_manifest,
    scaled_budget,
    needs_regen,
    step_regen_circuit_breaker,
)
from .regen_qc import step_vlm_judge, step_regen_drifted
from .dataset_qc import step_texture_qc, step_dataset_exclusions, step_drift_gate, step_qc_summary
from .pipeline_steps import (
    _MANIFEST_RESERVED,
    PIPELINE_STAGE_ORDER,
    emit_log,
    skip_before,
    park_for_operator,
    step_idqc_preflight,
    step_persist_sheet_manifest,
    step_sheet_approval,
    step_qc_backstop,
    step_qc_pass_rate_valve,
)
from .pipeline_training import (
    step_captions,
    step_dataset_review,
    step_lora_training,
    step_lora_flywheel,
    _step_sdxl_flywheel_refine,
    step_checkpoint_sweep,
    step_qc_safety_valve,
    step_finish_bible,
)
