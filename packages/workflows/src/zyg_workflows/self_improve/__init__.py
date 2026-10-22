# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""self_improve.py — THE LOOP: measure → signature → remedy → next-attempt → verify → learn.

2026-07-30.  WHY THIS EXISTS.
--------------------------------------------------------------------------------
Three consecutive renders of scene20 (v7, v8a) were shipped as "Abel is frozen —
the model won't animate him".  That diagnosis was wrong, and it was wrong because
a HUMAN read the clip and guessed.  The truth was only visible in numbers nobody
had lined up side by side:

    region     raw render (vace_static)   after paste_back_keep_regions
    abel_hand         0.254                        0.080     (-68 %)
    a_head            0.150                        0.127
    gate              0.12                         FAIL

The model had animated the hand correctly the whole time.  A POST-PROCESS —
restoring anchor pixels over a static keep-mask whose pinned book box happens to
contain the writing hand — pasted a still hand over every animated frame.

So this module refuses to be told what is wrong.  It MEASURES:

  * every artifact in the run directory's chain (vace_static → pasted17 →
    inked17 → smoked17 → up_out → FINAL), with the SAME gates, and diffs
    consecutive links.  A step whose output measures worse than its input is
    labelled `chain.step_destructive` — derived, never declared.
  * every keep/pin box (named boxes from shot_metadata.json PLUS boxes recovered
    from the black connected components of the mask PNG) is probed on the RAW
    clip for two independent properties:
        - does it CONTAIN MOTION?      (qc_region_flow on the raw clip)
        - is the pin even NECESSARY?   (qc_prop_consistency on the raw clip)
    A keep box that contains motion AND whose prop is already stable without the
    pin is a pin that can only do harm.  That single pair of measurements is the
    v8a root cause, stated without any knowledge of Abel, hands or books.
  * a region-free MOTION-LOSS GRID (raw vs delivered per tile) so the loss is
    found even when nobody has named a region at all.

The signature is evidence.  The VLM report (vlm_report.analyze_render) is the
narrative.  remedy_kb ranks the fix.  plan_next_attempt writes the recipe a
driver consumes verbatim.  verify_attempt re-measures afterwards and tells the
KB whether the remedy actually moved its target metric across its threshold —
that write-back is the only thing in the system that makes it improve.

HOUSE RULES honoured here
  * log_fn callbacks everywhere, never print from library code.
  * lazy imports (cv2/numpy/vlm/remedy_kb) — importing this module is free.
  * fail-safe returns: {'ok': False, 'error': ...}.  Nothing raises across a
    module boundary; a broken analyser must never take a render down.
  * NOTHING here kills, frees or interrupts a render.  watch_active_run returns
    a RECOMMENDATION.  Stopping a 90-minute uninterruptible job is the
    operator's call, always.

MEASUREMENT HAZARD THIS MODULE FIXES (do not remove)
  pipeline_debug's flow gates are calibrated in px/sample at 832x480 @ 17 fps
  with sample_every=4.  The delivered FINAL is 1664x960 @ 24 fps.  Comparing
  them raw inflates the final by 2.0 * (17/24) = 1.41x and would have "proved"
  fixes that did nothing.  Every flow number here also carries `flow_norm`,
  rescaled to the calibration geometry:

      flow_norm = flow_mean * (832/W) * (fps/17) * (4/sample_every)

  Sanity check on real files: FINAL_scene20_v8b measures abel_hand 0.364 px at
  1664x960@24 → norm 0.257, which lands on the raw render's own 0.254.  Gate
  comparisons across geometries use flow_norm.  Always.

CLI
    python3 self_improve.py diagnose <run_dir> [--clip F] [--raw F] [--no-vlm]
                                     [--tier resident] [--params P.json] [--commit]
    python3 self_improve.py plan     <run_dir> [--params P.json] [--commit]
    python3 self_improve.py verify   <prev_dir> <new_dir> [--prev-clip F] [--new-clip F]
    python3 self_improve.py campaign <run_dir> [<run_dir> ...] [--out FILE]
    python3 self_improve.py watch    <run_dir> [--poll 60] [--once]

`--commit` is the only thing that tells the KB a remedy was really ATTEMPTED.
Diagnosing and planning are free: re-reading an old run must never cost a working
rule its confidence.  verify_attempt back-fills the attempt it verifies.

A run directory that holds TWO complete chains (an original and a fix, e.g.
FINAL_scene20_v8.mp4 beside FINAL_scene20_v8b.mp4) is diagnosed on the FIRST by
default and reports the second as an already-tried alternative; pass --clip to
point at a specific one.
"""

import json
import os
import re
import sys
import time
import logging as _zyg_logging

from zyg_workflows.self_improve import base
from zyg_workflows.self_improve import chain
from zyg_workflows.self_improve import measure
from zyg_workflows.self_improve import signature
from zyg_workflows.self_improve import remedies
from zyg_workflows.self_improve import diagnosis
from zyg_workflows.self_improve import planning
from zyg_workflows.self_improve import verify
from zyg_workflows.self_improve import campaign_view
from zyg_workflows.self_improve import watch
from zyg_workflows.self_improve import cli

from zyg_workflows.self_improve.base import (
    _DIR,
    SCHEMA,
    CAL_W,
    CAL_FPS,
    CAL_SAMPLE_EVERY,
    _COVER_FRAC,
    _GRID_COLS,
    _GRID_ROWS,
    _TILE_DROP_FRAC,
    _log_noop,
    _mklog,
    _jsonable,
    _write_json,
    _read_json,
    _write_text,
    clip_geometry,
    norm_factor,
)
from zyg_workflows.self_improve.chain import (
    _CHAIN_SPEC,
    _STEP_FAMILY,
    _CONTRACT_STEP,
    detect_chain,
    keep_boxes_from_mask,
    keep_boxes_from_metadata,
    _box_iou,
    _box_subtract_note,
)
from zyg_workflows.self_improve.measure import (
    _cache_path,
    _cache_key,
    measure_clip,
    motion_loss_map,
    _num_or_none,
    _fact,
    load_qc_spec,
    _find_clip,
    _find_raw,
)
from zyg_workflows.self_improve.signature import (
    build_signature,
    _ledger_view,
)
from zyg_workflows.self_improve.remedies import (
    _FALLBACK_REMEDIES,
    _FallbackKB,
    _kb_singleton,
    kb,
    _kb_call,
    _PATCH_TARGET_HINTS,
    _normalize_remedy,
    kb_match,
    _kb_confidence,
    _kb_writes_ledger,
    _explain,
)
from zyg_workflows.self_improve.diagnosis import (
    _run_vlm,
    diagnose,
    vlm_findings,
    _merge_findings,
    render_next_attempt_md,
)
from zyg_workflows.self_improve.planning import (
    plan_next_attempt,
    _expected_for,
    _run_id_of,
)
from zyg_workflows.self_improve.verify import (
    verify_attempt,
    _expected_belongs,
    _ledger_record_verification,
)
from zyg_workflows.self_improve.campaign_view import (
    campaign,
    _campaign_md,
    _kb_learning_view,
)
from zyg_workflows.self_improve.watch import (
    read_progress,
    read_preview_judge,
    watch_active_run,
)
from zyg_workflows.self_improve.cli import (
    _cli_log,
    main,
)

_zyg_log = _zyg_logging.getLogger(__name__)

# Every name imported above is re-exported, not used here: this package IS the module
# the split replaced, so `__all__` declares the surface instead of a file-level noqa.
__all__ = [
    'json',
    'os',
    're',
    'sys',
    'time',
    'base',
    'chain',
    'measure',
    'signature',
    'remedies',
    'diagnosis',
    'planning',
    'verify',
    'campaign_view',
    'watch',
    'cli',
    '_DIR',
    'SCHEMA',
    'CAL_W',
    'CAL_FPS',
    'CAL_SAMPLE_EVERY',
    '_COVER_FRAC',
    '_GRID_COLS',
    '_GRID_ROWS',
    '_TILE_DROP_FRAC',
    '_log_noop',
    '_mklog',
    '_jsonable',
    '_write_json',
    '_read_json',
    '_write_text',
    'clip_geometry',
    'norm_factor',
    '_CHAIN_SPEC',
    '_STEP_FAMILY',
    '_CONTRACT_STEP',
    'detect_chain',
    'keep_boxes_from_mask',
    'keep_boxes_from_metadata',
    '_box_iou',
    '_box_subtract_note',
    '_cache_path',
    '_cache_key',
    'measure_clip',
    'motion_loss_map',
    '_num_or_none',
    '_fact',
    'load_qc_spec',
    '_find_clip',
    '_find_raw',
    'build_signature',
    '_ledger_view',
    '_FALLBACK_REMEDIES',
    '_FallbackKB',
    '_kb_singleton',
    'kb',
    '_kb_call',
    '_PATCH_TARGET_HINTS',
    '_normalize_remedy',
    'kb_match',
    '_kb_confidence',
    '_kb_writes_ledger',
    '_explain',
    '_run_vlm',
    'diagnose',
    'vlm_findings',
    '_merge_findings',
    'render_next_attempt_md',
    'plan_next_attempt',
    '_expected_for',
    '_run_id_of',
    'verify_attempt',
    '_expected_belongs',
    '_ledger_record_verification',
    'campaign',
    '_campaign_md',
    '_kb_learning_view',
    'read_progress',
    'read_preview_judge',
    'watch_active_run',
    '_cli_log',
    'main',
]
