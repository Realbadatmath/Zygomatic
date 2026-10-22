#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
medusa_sheet_service.py — turn a folder of ready photographs into a canonical
multi-angle CONTACT SHEET (2026-08-07).

This is the "prepare what you already have" counterpart to
contact_sheet_pipeline.py. That module GENERATES 48 angles with the GPU
(~4h26m/character). This one takes photos the operator already has and
*classifies* them into the same canonical angle taxonomy, captions them, QCs
them, and assembles the sheet — CPU only, no GPU, no ComfyUI, no sampling.

ISOLATION CONTRACT (inherited from bp_medusa_training.py — read that file's
docstring first):
    Everything here is path-parameterised by the caller and only ever touches
    directories under lora-datasets/medusa_training/<mdt_*>/. This module must
    NEVER import contact_sheet_pipeline, char_state_service,
    character_bible_service or character_lora_family — those are the modules
    that feed the general workflow character pickers and the zero-public
    library. It writes no state outside the character directory it is given.

HOW ANGLE IS DECIDED (evidence-based, measured 2026-08-07 against a real
48-angle sheet whose intended angle per cell was known):

    Tier 1 — GEOMETRY (authoritative). MediaPipe FaceLandmarker with
    output_facial_transformation_matrixes gives a 4x4 head pose; yaw/pitch/roll
    come straight off its rotation submatrix. Measured on known cells:
    front -> yaw -1.1 deg, "35 deg left" -> -37.4, "35 deg right" -> +36.9,
    "slightly above" -> pitch +17.3, "slightly below" -> -7.7. Deterministic,
    no left/right confusion, ~free on CPU.

    Tier 2 — POSE GEOMETRY (fallback, face not found). MediaPipe pose labels
    landmarks in SUBJECT-anatomical terms, so left/right features swap sides
    when the subject turns away. Two normalised ratios (both divided by
    shoulder span) do the work — this is the blind spot that otherwise makes
    uncommon angles the unaudited corner of a training set:

      ear_dx = (left_ear.x - right_ear.x) / shoulder_span
          SIGN separates hemispheres, MAGNITUDE separates profile from front.
          Measured: front +0.418/+0.414/+0.414/+0.378, verified back views
          -0.329/-0.280/-0.290, profiles +0.184/+0.338/+0.152.
      nose_off = (nose.x - shoulder_midpoint.x) / shoulder_span
          Recovers WHICH profile. Measured: verified left profile -1.857,
          verified right profile +2.225, front view -0.054.

    Guard: when shoulder span collapses (< 0.06 of frame width) the pose is
    degenerate and both ratios explode (one cell produced nose_off = -36.1) —
    that case is forced to unknown rather than trusted.

    Deliberately NOT used: pose landmark `visibility`. MediaPipe reports the
    nose at visibility 0.97 on a verified back-of-head image — it extrapolates
    occluded landmarks instead of reporting them absent.

    Back-hemisphere views are never given a SIDE. The sample contained no
    verified sided back three-quarter to calibrate against, and guessing an
    unvalidatable side would violate the rule below.

    Tier 3 — UNKNOWN (both failed). The cell is flagged for review and gets NO
    angle token in its caption. We never guess an angle: a wrong angle caption
    is worse than an absent one, because it teaches the model the wrong word.

VALIDATION (2026-08-07, against a real 48-cell sheet with known intended
angles): the geometry tier classified every cell it fired on to the angle
ACTUALLY PRESENT in the pixels. Where its answer disagreed with the cell's
intended angle, inspection confirmed the *generator* was at fault, not the
classifier — e.g. two cells intended as "35 left" and "35 right" both rendered
at +43.5 and +45.3 (turned the same way), and a cell intended as a 90 degree
profile rendered at -60.6. That disagreement is therefore a useful QC signal in
its own right, not noise to tune away.

REJECTED APPROACH (do not re-add): the selfie_multiclass segmenter's
face-skin-vs-hair ratio was tried as the no-face discriminator and FAILS. On a
verified back-of-head cell it reported face_skin=0.246 (the highest of the
sample) because it labels lit hair and a light collar as skin. It is trained on
selfies and is not valid for back views.

CAPTIONS are assembled from a FIXED VOCABULARY (see YAW_TERMS/PITCH_TERMS/
FRAMING_TERMS) rather than free VLM prose. Free prose would describe the same
angle twenty different ways across 80 characters and split the concept across
token patterns, making none of them reliably promptable. Only things that
should stay PROMPTABLE are captioned (angle, pitch, framing) — never the traits
that define identity (face structure, hair colour, build), which must bind to
the trigger token instead.
"""

from zyg_workflows.medusa_sheet_service.constants import (
    annotations,
    json,
    math,
    os,
    re,
    threading,
    time,
    Any,
    Callable,
    _zyg_logging,
    _zyg_log,
    _PAGE_NAME_RE,
    _DETECTOR_DIR,
    _FACE_TASK,
    _POSE_TASK,
    _WORKERS,
    _BLUR_VAR_MIN,
    _MIN_EDGE_PX,
    _DUPE_HAMMING_MAX,
    _SHEET_COLS,
    _SHEET_ROWS,
    _CELL_PX,
    _LABEL_PX,
    YAW_BUCKETS,
    YAW_TERMS,
    _POSE_MIN_SHOULDER_SPAN,
    _EAR_DX_BACK_MAX,
    _EAR_DX_PROFILE_MAX,
    _NOSE_OFF_SIDED_MIN,
    PITCH_BUCKETS,
    PITCH_TERMS,
    FRAMING_TERMS,
    COVERAGE_GROUPS,
    COVERAGE_SIDED_PAIRS,
    COVERAGE_FRAMINGS,
    COVERAGE_PITCHES,
    _bucket,
    _tls,
    detectors_available,
    _get_detectors,
    _euler_from_matrix,
)
from zyg_workflows.medusa_sheet_service.analysis import (
    POSE_NOSE,
    POSE_L_SH,
    POSE_R_SH,
    POSE_L_EAR,
    POSE_R_EAR,
    POSE_L_HIP,
    POSE_R_HIP,
    POSE_L_ANK,
    POSE_R_ANK,
    POSE_L_KNEE,
    POSE_R_KNEE,
    _framing_from,
    _dhash,
    _blur_variance,
    analyze_image,
    caption_for,
)
from zyg_workflows.medusa_sheet_service.montage import (
    coverage_report,
    _duplicate_groups,
    _SLOT_ORDER,
    _SHORT,
    build_montage,
)
from zyg_workflows.medusa_sheet_service.runner import (
    _jobs,
    _jobs_lock,
    get_status,
    _set,
    is_running,
    sheet_dir,
    sheet_json_path,
    load_sheet,
    summary_path,
    load_summary,
    build_sheet,
    _queue,
    _queue_cv,
    _pump_started,
    queue_depth,
    forget,
    _pump,
    _ensure_pump,
    start_build,
)


# ── re-export surface ─────────────────────────────────────────────────────────
# Every name below is imported above and not used in this module: this file
# exists so that ``zyg_workflows.medusa_sheet_service.<name>``
# resolves exactly as it did on the pre-split single-file module.
# Nothing does ``import *`` from here.
__all__ = [
    'annotations',
    'json',
    'math',
    'os',
    're',
    'threading',
    'time',
    'Any',
    'Callable',
    '_zyg_logging',
    '_zyg_log',
    '_PAGE_NAME_RE',
    '_DETECTOR_DIR',
    '_FACE_TASK',
    '_POSE_TASK',
    '_WORKERS',
    '_BLUR_VAR_MIN',
    '_MIN_EDGE_PX',
    '_DUPE_HAMMING_MAX',
    '_SHEET_COLS',
    '_SHEET_ROWS',
    '_CELL_PX',
    '_LABEL_PX',
    'YAW_BUCKETS',
    'YAW_TERMS',
    '_POSE_MIN_SHOULDER_SPAN',
    '_EAR_DX_BACK_MAX',
    '_EAR_DX_PROFILE_MAX',
    '_NOSE_OFF_SIDED_MIN',
    'PITCH_BUCKETS',
    'PITCH_TERMS',
    'FRAMING_TERMS',
    'COVERAGE_GROUPS',
    'COVERAGE_SIDED_PAIRS',
    'COVERAGE_FRAMINGS',
    'COVERAGE_PITCHES',
    '_bucket',
    '_tls',
    'detectors_available',
    '_get_detectors',
    '_euler_from_matrix',
    'POSE_NOSE',
    'POSE_L_SH',
    'POSE_R_SH',
    'POSE_L_EAR',
    'POSE_R_EAR',
    'POSE_L_HIP',
    'POSE_R_HIP',
    'POSE_L_ANK',
    'POSE_R_ANK',
    'POSE_L_KNEE',
    'POSE_R_KNEE',
    '_framing_from',
    '_dhash',
    '_blur_variance',
    'analyze_image',
    'caption_for',
    'coverage_report',
    '_duplicate_groups',
    '_SLOT_ORDER',
    '_SHORT',
    'build_montage',
    '_jobs',
    '_jobs_lock',
    'get_status',
    '_set',
    'is_running',
    'sheet_dir',
    'sheet_json_path',
    'load_sheet',
    'summary_path',
    'load_summary',
    'build_sheet',
    '_queue',
    '_queue_cv',
    '_pump_started',
    'queue_depth',
    'forget',
    '_pump',
    '_ensure_pump',
    'start_build',
]
