# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_debug.py — run-scoped tracing + auto-QC for the generation pipelines.

Born from the 2026-07-29 frozen-VACE incident: defects (a static control video, an
anti-static negative prompt, overexposed malformed hands in the anchor still) sailed
through every stage because nothing recorded what was ACTUALLY submitted and nothing
measured outputs per-region. This module gives every run a durable evidence trail:

    from zyg_workflows.pipeline_debug import DebugRun
    dbg = DebugRun(out_dir)                        # creates <out_dir>/debug/
    dbg.stage('base_plate', params={...})          # start a stage
    dbg.record_graph('base_plate', graph_dict)     # EXACT comfy graph submitted
    dbg.record_prompts('wan', positive=..., negative=...)
    dbg.snapshot('base_plate', image_path)         # thumbnail an intermediate
    dbg.qc_still('final_still', still_path, char_regions=[...])
    dbg.qc_clip('wan', clip_path, char_regions=[...], still_path=...)
    dbg.finish(ok=True)                            # writes report.json + report.html

Every stage call is fail-safe (a broken debug layer must never break generation).
QC verdicts use measured thresholds:
  still: clipped-highlight % per region, hand count via hand_yolov8s, identity embed
  clip : per-region MEAN consecutive-frame delta (char regions must MOVE >= 1.5,
         background must stay < 1.0), global camera-drift, color drift vs first frame
The bad old metric (ffmpeg freezedetect "motion score") is NOT used here — it counts
texture shimmer as motion and green-lit a frozen clip.

2026-07-30 — run_ledger wiring (silent-degrade ledger + execution provenance):
  * every DebugRun owns a run_id (env ZYG_RUN_ID if set, else generated AND exported
    for the duration of the run) so a record_fallback() buried in audio_mix or
    zyg_whisper lands in THIS run without any signature plumbing;
  * stage() closes out the previous stage into run_ledger.stages with its measured
    wall_s / vram_peak_mb / device / model_id / dtype (the cheap fingerprints that
    expose a CPU-path degrade: 6x slower at 1/3 the VRAM);
  * finish() writes every QC check into run_ledger.gates (run_id, gate, outcome,
    score, taxonomy tag) — that is the cross-run table the ghost-face pattern
    (17/49 bad cells, every per-run gate PASSING) needs to be visible at all;
  * the manifest and report.html grew a 'degradations' section listing every
    silent fallback logged under this run_id;
  * the nvidia-smi shell-out was replaced by NVML (nvidia-ml-py, BSD) with a
    graceful nvidia-smi fallback.
All of it is fail-safe: no ledger error may ever break generation.
"""

# ruff: noqa: F401

import json
import os
import time
import logging as _zyg_logging
from zyg_workflows import paths
from zyg_workflows.bin import exe

# The submodules in the order the sections stood in the original pipeline_debug.py.
# None of them has an order-sensitive import-time side effect (only constants, dict
# literals, defs and a getLogger call), so this order is documentation as much as it
# is a guarantee — but run_report must come before the gate modules: it defines
# DebugRun and the active-run registry that gates_v7._record_qc reads back.
from . import common
from . import run_record
from . import run_clip_qc
from . import run_report
from . import gates_v7
from . import gates_prop
from . import gates_frame
from . import gates_motion
from . import gates_charbal_detect
from . import gates_charbal
from . import gates_beats
from . import gates_regression
from . import cli

from .common import (
    _THUMB_W,
    _now,
    _LEDGER,
    _ledger,
    _CONTRACT,
    _contract,
    _vram_mb,
    _SCORE_KEYS,
    _check_score,
    _zyg_log,
    _CLIP,
    _clip_embed,
    identity_similarity,
    _detect_hands,
    _jsonable,
)
from .run_record import (
    _DebugRunRecord,
)
from .run_clip_qc import (
    _DebugRunClipQC,
)
from .run_report import (
    DebugRun,
    _CREWS,
    make_ab_video,
    _Null,
    set_active,
    get_active,
)
from .gates_v7 import (
    _REGION_FLOW_MIN,
    _REGION_FLOW_MIN_HEAD,
    _REGION_CHURN_MAX,
    _PROP_NCC_MIN,
    _CONTEXT_STRIDE_FRAMES,
    _gate_thr,
    _sampled_gray_frames,
    _record_qc,
    qc_region_flow,
    qc_prop_consistency,
)
from .gates_prop import (
    _PROP_SCALE_LOG_MAX,
    _PROP_SCALE_INLIER_MIN,
    _PROP_SCALE_MIN_INLIERS,
    _PROP_AREA_RATIO_MAX,
    _PROP_CANON_TOL,
    _PROP_RIDGE_FLICKER_MAX,
    _PROP_RIDGE_FLOOR,
    _PROP_MIN_BLOB_FRAC,
    _PROP_MIN_COVERAGE,
    _BORDER_EXCESS_MIN,
    _BORDER_RATIO_MIN,
    _BORDER_PERSIST_MIN,
    _BORDER_INSET_PX,
    _FX_NOISE_RATIO_LO,
    _FX_NOISE_RATIO_HI,
    _FX_FLICKER_RATIO_MAX,
    _FX_SAT_RATIO_MIN,
    _sampled_bgr_frames,
    _prop_white_blob,
    _prop_ridges,
    _prop_scale_pair,
    qc_prop_geometry,
)
from .gates_frame import (
    qc_frame_border,
    qc_fx_grain,
)
from .gates_motion import (
    _MOTION_REVERSALS_MAX,
    _MOTION_NET_PATH_MIN,
    _MOTION_COHERENCE_FLOOR,
    _MOTION_BALANCE_RATIO_MAX,
    _MOTION_STEP_CALIBRATED,
    _MOTION_WIN_S,
    _region_flow_vectors,
    _motion_vector_stats,
    qc_motion_quality,
    qc_motion_balance,
)
from .gates_charbal_detect import (
    _CHARBAL_FLOW_STEP,
    _CHARBAL_DIR_STEP,
    _CHARBAL_FACE_FLOW_MIN,
    _CHARBAL_FACE_RATIO_MAX,
    _CHARBAL_FACE_FILL_MIN,
    _CHARBAL_BOX_AREA_MAX,
    _CHARBAL_VERIFY_FRAMES,
    _BEAT_EVEN_SHARE_FRAC,
    _REGRESSION_TOLERANCE,
    _REGRESSION_FLOOR,
    _perpix_stats,
    _box_area,
    _box_inter,
    _valid_box,
    locate_character_faces,
    _charbal_normalize,
    _detector_face_boxes_for,
)
from .gates_charbal import (
    qc_character_balance,
)
from .gates_beats import (
    _BEAT_SUBORDINATORS,
    _BEAT_LEADING_PREPS,
    _beat_text,
    _beat_aliases,
    _beat_split,
    _beat_strip_lead_phrase,
    qc_beat_prominence,
)
from .gates_regression import (
    _REGRESSION_WORSE_WHEN,
    qc_regression_vs,
)
from .cli import (
    _cli_auto_chars,
    _cli_main,
)


def __getattr__(name):
    """`_ACTIVE` is the one name that cannot be re-exported by value: set_active()
    rebinds it in run_report, and a `from .run_report import _ACTIVE` here would freeze
    pipeline_debug._ACTIVE at None forever. Forward it instead, so the package attribute
    stays as live as the module attribute was."""
    if name == '_ACTIVE':
        return run_report._ACTIVE
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
