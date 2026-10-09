# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""vlm_report.py — the autonomous local-LLM defect reporter (2026-07-30).

WHAT THIS IS. Point it at a finished render and it produces an operator-facing
diagnosis with NO human in the interpretation loop: a local Qwen3-VL judge looks
at the render, local pixel metrics measure it, and a local LLM writes the report.
Nothing here asks a person "does this look wrong to you?" — that is the whole
point. The same clip in gives the same analysis out, on this machine, offline.

WHY IT IS BUILT THE WAY IT IS — five measured facts, each of which killed a
simpler design during the 2026-07-30 scene20 validation session:

  1. THE CROP RULE. On the full 832x480 frame the judge answered "is a hand
     cupping the pipe bowl?" WRONG on 2/2 defective frames; on the region crop it
     answered right on 5/5. The offending hand is ~100 px wide in a 832x480 frame
     — below what the vision tower resolves. So this module NEVER sends a bare
     frame as the primary evidence: it derives inspection CROPS (from authored
     pins and from GroundingDINO detections that track the object as it moves),
     upscales each to >= MIN_CROP_PX on the long edge, saves them to <out>/crops/
     and judges those. The operator can open the crop folder and see exactly what
     the judge saw — the analysis is auditable, not a black box.

  2. THE JUDGE HAS BLIND SPOTS, AND THEY MUST BE ADMITTED. It scored 0/7 on the
     confirmed ink-on-hand defect and it is documented-weak on temporal defects
     (frozen limbs, seam morphing — TempCompass). Those belong to pixel metrics.
     So every finding in this report carries source: 'vlm' | 'pixel' | 'both'.
     A 'vlm'-only clean bill on ink_containment is explicitly reported as
     UNRELIABLE, and a frozen region can only ever be found by 'pixel'. Fusing
     without attribution would be a lie of omission.

  3. NEGATIVELY-PHRASED QUESTIONS FAIL. Four models answered "is the pipe
     absent?" wrong while their own free-text reason contradicted their answer.
     This module therefore does not invent questions: it consumes the calibrated,
     positively-phrased checklist DATA in config/vlm_checklists.json through
     vlm_inspector, and only decides WHICH CROP each item is asked about
     (ITEM_TARGETS below). Wording stays owned by the checklist.

  4. QWEN3-VL BBOXES ARE RELATIVE 0-1000, AND THEY ARE RELATIVE TO THE CROP.
     vlm_worker.parse_bbox already normalizes 0-1000 -> 0..1 of the image it was
     shown. That image is a CROP, so a box is meaningless to an operator until it
     is mapped back to the full frame. The maths (see _remap_bbox) is:
         full_x = cx0 + bx * (cx1 - cx0)
         full_y = cy0 + by * (cy1 - cy0)
     where (cx0,cy0,cx1,cy1) is the crop's own fractional box in the full frame
     and (bx,by) is the judge's 0..1 crop-relative coordinate. Upscaling the crop
     does not enter the maths because it is uniform and fraction-preserving.
     Localization passes send exactly ONE crop, because vlm_worker grounds on
     images[0] — with a multi-crop set the box would silently belong to the first
     crop instead of the failing one.

  5. THE GPU IS SHARED. Every GPU step goes through comfy_offload: GPU work is
     refused outright while ComfyUI is sampling (freeing VRAM mid-sample kills an
     uninterruptible 90-minute render), and the boundary-tier synthesis takes the
     card via comfy_offload.gpu_exclusive so ComfyUI is offloaded rather than
     squeezed.

TIER SPLIT (deliberate, not a shortcut). Per-crop binary judging runs on the
RESIDENT tier (Qwen3-VL-8B-Instruct-FP8) because that is the tier the crop rule
was validated on (5/5) and because inspection needs MANY short calls — measured
here at 10.7 s to load + ~2-11 s/question. The final SYNTHESIS runs on the
BOUNDARY tier (Qwen3-VL-32B-Instruct-FP8) — one call, one load, the strongest
local reasoner writing the operator-facing prose. `tier` selects the synthesis
tier; `inspect_tier` selects the judging tier.

K-ENSEMBLE. vlm_inspector.inspect_frames(k=N) already runs the worker N times and
majority-votes in _aggregate (it does NOT pass the worker's own --k flag through,
so this is the "call it k times and vote" branch of the contract, done inside the
inspector rather than reimplemented here). Only CRITICAL items pay for it: each
target is split into a critical call at k=k_critical and a major call at k=1.

SELF-IMPROVEMENT. Two loops, both local and both persistent:
  * run_ledger — every finding is written back as a gate, and the previous runs'
    gate history plus run_ledger.trends() are fed INTO the synthesis prompt, so
    the LLM is told "this gate has failed 4 of the last 6 runs" and can say so.
  * a lessons file (data/runtime/vlm_report_lessons.jsonl) — the cause the LLM
    named for each failure is appended, and prior lessons for the same scene are
    replayed into the next synthesis. The loop therefore accumulates diagnoses
    across runs instead of restarting cold every time.

API
    analyze_render(clip_path, shot_metadata_path=None, out_dir=None,
                   char_regions=None, checklist='scene20_binary', tier='boundary',
                   beat_times=None, k_critical=3, log_fn=None, ...)
      -> {'ok','verdict','findings',[...],'report_md','report_json','crops_dir',
          'model','elapsed_s', ...}
    CLI: python3 vlm_report.py <clip> [--meta ...] [--out ...] [--tier ...]

Fail-safe contract (house rule): no entry point raises across the module
boundary. Every failure returns {'ok': False, 'error': ...} with whatever partial
evidence survived, because a broken reporter must never be mistaken for a clean
render — but it must also never take a pipeline down.

Env knobs:
  ZYG_VLM_REPORT_MIN_CROP_PX   crop long-edge upscale floor (default 512)
  ZYG_VLM_REPORT_CONTINUITY    "1" -> also run continuity_qc.analyze_clip
                               (SAM2 + DINOv2; measured 448 s CPU / minutes GPU
                               for a 20 s clip — opt-in, it is the expensive one)
  ZYG_VLM_REPORT_GROUND        "0" -> skip GroundingDINO, pins only
  ZYG_VLM_REPORT_MAXLOC        max crops localized per failing item (default 6)
  ZYG_VLM_REPORT_SYNTH_TOKENS  synthesis max_new_tokens (default 1700)
  ZYG_NATIVE_FPS / ZYG_CONTEXT_STRIDE  render-recipe geometry for seam times
"""

# ruff: noqa: E402, F401
# Pattern-A package: the original module docstring, top import block and every
# top-level name it defined are re-exported here, and the section modules are
# imported in the original section order so module-level side effects still run
# in that order. `from zyg_workflows import vlm_report` is unchanged.

import json
import os
import subprocess
import sys
import threading
import time
import logging as _zyg_logging
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)

from zyg_workflows.vlm_report.constants import (
    _DIR,
    NATIVE_FPS,
    CONTEXT_STRIDE_FRAMES,
    MIN_CROP_PX,
    MAX_LOCALIZE_FRAMES,
    SYNTH_TOKENS,
    SYNTH_WAIT_S,
    LESSONS_PATH,
    PIN_HALF,
    BOX_PAD,
    GROUND_PROMPTS,
    ROLE_PIN_ANCHOR,
    PERSON_SIDE,
    PERSON_FALLBACK,
    MAX_OBJECT_AREA,
    MAX_PERSON_AREA,
    MAX_HAND_AREA,
    ITEM_TARGETS,
    ITEM_REQUIRES_VISIBLE,
    ROLE_SHOWS,
    ITEM_BEAT_SCOPED,
    item_answerable_on,
    first_answerable_target,
    VLM_CLASS,
    VLM_UNRELIABLE_PASS,
    SEVERITY_ORDER,
    STATUS_ORDER,
)
from zyg_workflows.vlm_report.util import (
    _mklog,
    _c01,
    _pad_box,
    _box_ok,
    _iou,
    _area,
    _union,
    _median_box,
    _stable_box,
    _pick_candidate,
    _VramWatch,
    _probe,
    _default_times,
    _seam_pairs,
    _decode_times,
)
from zyg_workflows.vlm_report.targets import (
    _pin_targets,
    _ground_targets,
    _hand_side_targets,
    _merge_targets,
    _crop_name,
    _make_crops,
)
from zyg_workflows.vlm_report.inspection import (
    _checklist_doc,
    _write_subset_checklist,
    _ChecklistPath,
    _remap_bbox,
    _inspect,
    _run_inspection,
    _flow_regions,
    _pixel_metrics,
)
from zyg_workflows.vlm_report.fusion import (
    _release_judges,
    _release_detectors,
    _new_finding,
    _fuse,
    _verdict_of,
    RELATED_GATE_PREFIXES,
    _prior_context,
    _append_lessons,
    _ledger_write,
)
from zyg_workflows.vlm_report.synthesis import (
    _SYNTH_RUNNER,
    _fmt_metric_table,
    _synthesis_prompt,
    _run_synthesis,
)
from zyg_workflows.vlm_report.markdown_report import _write_markdown
from zyg_workflows.vlm_report.entry import analyze_render, _cli
