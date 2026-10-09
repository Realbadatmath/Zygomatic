# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Module-level configuration constants, env switches and angle tables.

Moved verbatim out of the old single-file contact_sheet_pipeline.py (lines 32-311).
"""

from __future__ import annotations

import os
from zoneinfo import ZoneInfo
import logging as _zyg_logging

from zyg_workflows import paths


_zyg_log = _zyg_logging.getLogger(__name__)


_AMS = ZoneInfo('Europe/Amsterdam')
_DATASET_ROOT = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')
_OUTPUT_ROOT = str(paths.ZYG_LORA_OUTPUTS / 'storyteller_chars')

# Multi-sheet: 2×3 per run × 4 runs (classic, 24 angles) or × 8 runs (extended, 48
# angles — reconstruction-grade yaw/pitch rings + ortho turnaround for 3D work).
DUAL_SHEET_ROWS = 2
DUAL_SHEET_COLS = 3
ANGLE_SET_DEFAULT = os.environ.get('ZYG_CONTACT_SHEET_ANGLE_SET', 'extended').strip().lower()
_CLASSIC_PARTS = ('a', 'b', 'c', 'd')
_EXTENDED_PARTS = ('a', 'b', 'c', 'd', 'e', 'f', 'g', 'h')

# 2026-07-31: the per-cell sheet writer names parts by INDEX
# (``chr(ord('a') + si)``), so a run can emit a part beyond _EXTENDED_PARTS —
# c3345deb5bde carries contact_sheet_master_i.png. Scan the whole lowercase
# alphabet when probing for parts on disk so a 9th/10th sheet is found without
# another edit here. Order is alphabetical => deterministic "first part".
_MASTER_SHEET_PART_SCAN = tuple(chr(c) for c in range(ord('a'), ord('z') + 1))

# 2026-07-31: a character built by the 48-angle pipeline may have ONLY
# contact_sheet_master_<x>.png parts and no monolithic contact_sheet_master.png.
# Treating that as "no contact sheet" made library_preview_urls emit
# preview_url=None, which the public wizard read as "needs a preview" and
# answered with a destructive GPU sweep that overwrote real portraits with a
# generic non-LoRA render. Parts now count. Set
# ZYG_MASTER_SHEET_PARTS_COUNT=0 to restore the monolithic-only predicate.
MULTI_PART_SHEET_COUNTS = os.environ.get(
    'ZYG_MASTER_SHEET_PARTS_COUNT',
    '1',
).strip().lower() not in ('0', 'false', 'no')

# 2026-07-31 (contract D): previews written by the legitimate renderer carry a
# sibling ``<slot>.meta.json``. A preview PNG with no sidecar has UNVERIFIED
# provenance (it may be sweep debris), so it is only used when nothing
# sidecar-backed exists. Set ZYG_PREVIEW_REQUIRE_PROVENANCE=0 to rank previews
# by filename order alone, as before.
PREVIEW_PROVENANCE_PREFERRED = os.environ.get(
    'ZYG_PREVIEW_REQUIRE_PROVENANCE',
    '1',
).strip().lower() not in ('0', 'false', 'no')

# 2026-07-31: both image routes validate ^[a-f0-9]{12}$ before serving, so a
# slug dataset dir (abel_van_haren) can only ever produce a library row whose
# images 404. Skip them. Set ZYG_CONTACT_SHEET_LIBRARY_STRICT_IDS=0 to list them
# again.
LIBRARY_STRICT_CHAR_IDS = os.environ.get(
    'ZYG_CONTACT_SHEET_LIBRARY_STRICT_IDS',
    '1',
).strip().lower() not in ('0', 'false', 'no')

# 2026-07-31: an operator-declined run, or one whose QC safety valve returned
# 'fail', is not a finished character — the library used to show it as fully
# trained purely because safetensors existed on disk. Set
# ZYG_LIBRARY_GATE_DECLINED=0 to report lora_ready from disk alone.
LIBRARY_GATE_DECLINED = os.environ.get(
    'ZYG_LIBRARY_GATE_DECLINED',
    '1',
).strip().lower() not in ('0', 'false', 'no')

_CHAR_ID_RE_SRC = r'^[a-f0-9]{12}$'


def is_servable_char_id(char_id: str) -> bool:
    """True when *char_id* passes the ^[a-f0-9]{12}$ check both image routes
    apply (2026-07-31) — i.e. its images can actually be served."""
    try:
        import re as _re_cid

        return bool(_re_cid.match(_CHAR_ID_RE_SRC, (char_id or '').strip()))
    except Exception:
        return False


def _normalize_angle_set(angle_set: str | None) -> str:
    s = (angle_set or ANGLE_SET_DEFAULT).strip().lower()
    if s in ('corpus', 'training_corpus', 'dataset'):
        return 'corpus'
    # 'custom' (2026-09-16): the operator picked HOW MANY angles and WHICH ones
    # — the label list travels on the job as angle_ids / angle_labels. Per-cell
    # mode only; see custom_angle_labels_for_job().
    if s in ('custom', 'selected', 'manual', 'pick'):
        return 'custom'
    return 'classic' if s in ('classic', '24', 'legacy', 'small') else 'extended'


def sheet_parts_for(angle_set: str | None = None) -> tuple[str, ...]:
    # 'corpus' keeps the extended parts — the corpus plan is a SUPERSET of the
    # 48 extended angles, and parts only drive preview-page probing. 'custom'
    # likewise: its plan is a SUBSET, so probing simply finds fewer pages.
    return _CLASSIC_PARTS if _normalize_angle_set(angle_set) == 'classic' else _EXTENDED_PARTS


# Corpus mode (2026-08-09): 70-240 cells per character, exported as a LoRA
# training corpus. Cell budget from job['corpus_cells'] or the env; derived
# (relight/close-up CROP) cells are capped so the corpus stays generation-heavy.
CORPUS_CELLS_DEFAULT = int(os.environ.get('ZYG_SHEET_CORPUS_CELLS', '96'))
CORPUS_CELLS_MIN = 70
CORPUS_CELLS_MAX = 240
CORPUS_DERIVED_MAX_FRAC = float(os.environ.get('ZYG_SHEET_CORPUS_DERIVED_FRAC', '0.35'))


DUAL_SHEET_PARTS = sheet_parts_for(None)
DUAL_SHEET_COUNT = len(DUAL_SHEET_PARTS)
DUAL_SHEET_TOTAL_ANGLES = DUAL_SHEET_ROWS * DUAL_SHEET_COLS * DUAL_SHEET_COUNT
DEFAULT_ROWS = int(os.environ.get('ZYG_CONTACT_SHEET_ROWS', str(DUAL_SHEET_ROWS)))
DEFAULT_COLS = int(os.environ.get('ZYG_CONTACT_SHEET_COLS', str(DUAL_SHEET_COLS)))
# Legacy single-sheet 3×6 (set ZYG_CONTACT_SHEET_MODE=single_canvas + ROWS=3).
LEGACY_SINGLE_ROWS = 3
LEGACY_SINGLE_COLS = 6
DEFAULT_GUTTER = int(os.environ.get('ZYG_CONTACT_SHEET_GUTTER', '8'))
DEFAULT_CELL_W = int(os.environ.get('ZYG_CONTACT_SHEET_CELL_W', '512'))
DEFAULT_CELL_H = int(os.environ.get('ZYG_CONTACT_SHEET_CELL_H', '640'))
# Single-canvas pipeline: generate at 1080p, upscale, export tiles at training resolution.
CANVAS_GEN_W = int(os.environ.get('ZYG_CONTACT_SHEET_CANVAS_W', '1920'))
CANVAS_GEN_H = int(os.environ.get('ZYG_CONTACT_SHEET_CANVAS_H', '1080'))
EXPORT_CELL_W = int(os.environ.get('ZYG_CONTACT_SHEET_EXPORT_CELL_W', '640'))
EXPORT_CELL_H = int(os.environ.get('ZYG_CONTACT_SHEET_EXPORT_CELL_H', '720'))
UPSCALE_FACTOR = int(os.environ.get('ZYG_CONTACT_SHEET_UPSCALE_FACTOR', '2'))
# Tier-1 dual-sheet identity: lock sheet B to sheet A via face anchor + optional img2img fallback.
SHEET_B_ANCHOR_ENABLED = os.environ.get('ZYG_CONTACT_SHEET_SHEET_B_ANCHOR', '1').lower() not in (
    '0',
    'false',
    'no',
)
SHEET_B_I2I_DENOISE = float(os.environ.get('ZYG_CONTACT_SHEET_SHEET_B_I2I_DENOISE', '0.52'))
SHEET_B_IPA_SCALE = float(os.environ.get('ZYG_CONTACT_SHEET_SHEET_B_IPA_SCALE', '0.72'))
SHEET_B_USE_IPA = os.environ.get('ZYG_CONTACT_SHEET_SHEET_B_IPA', '1').lower() not in ('0', 'false', 'no')
CONTACT_SHEET_HAND_FIXER = os.environ.get('ZYG_CONTACT_SHEET_HAND_FIXER', '0').lower() in (
    '1',
    'true',
    'yes',
)
# Identity QC (ArcFace drift gate) — score tiles vs sheet-A anchor after tile_crop,
# regenerate drifted frontal cells per-cell, exclude hard failures from the dataset.
IDQC_MAX_RETRIES = int(os.environ.get('ZYG_CONTACT_SHEET_IDQC_MAX_RETRIES', '2'))
IDQC_REGEN_IPA_SCALE = float(os.environ.get('ZYG_CONTACT_SHEET_IDQC_REGEN_IPA_SCALE', '0.80'))
IDQC_EXCLUDE_FAILED = os.environ.get('ZYG_CONTACT_SHEET_IDQC_EXCLUDE_FAILED', '1').lower() not in (
    '0',
    'false',
    'no',
)
# InstantID repair escalation is OFF by default — its ComfyUI workflow submits a
# 400 "outputs failed validation" on this box, so it never ran and just wasted a
# retry. Qwen anchor re-edit replaced it. Flip to 1 only once the workflow is fixed.
_INSTANTID_REGEN_ENABLED = os.environ.get('ZYG_CONTACT_SHEET_INSTANTID_REGEN', '0').lower() in (
    '1',
    'true',
    'yes',
    'on',
)
# A regenerated tile must clear the LoRA train floor to count as a real repair —
# a 0.32-ish "pass" is too weak to add to the dataset (fix F).
IDQC_REGEN_MIN_SCORE = float(os.environ.get('ZYG_CONTACT_SHEET_IDQC_REGEN_MIN_SCORE', '0.42'))
# A mislabeled_angle tile (wrong yaw for its label) with strong identity is a
# good photo of the person at the wrong angle — keep it in the LoRA dataset with
# an angle-neutral caption rather than discarding the coverage (fix C).
IDQC_MISLABEL_KEEP_SCORE = float(os.environ.get('ZYG_CONTACT_SHEET_IDQC_MISLABEL_KEEP', '0.42'))
# LoRA flywheel — after v1 trains, generate hard angles (backs, crown, low/high)
# with the LoRA itself, QC them, extend the dataset, retrain as v2.
FLYWHEEL_ENABLED = os.environ.get('ZYG_CONTACT_SHEET_FLYWHEEL', '1').lower() not in (
    '0',
    'false',
    'no',
)
# LoRA training master switch — back ON since 2026-07-18. It was frozen
# 2026-07-16 after the Kira Dunn ghost-face batch trained unseen; every
# guardrail that motivated the freeze now exists: fail-closed identity QC,
# the dataset-review approval gate before training, and the post-training
# QC safety valve. Set ZYG_CONTACT_SHEET_LORA_TRAINING=0 to freeze again.
LORA_TRAINING_ENABLED = os.environ.get(
    'ZYG_CONTACT_SHEET_LORA_TRAINING',
    '1',
).strip().lower() in ('1', 'true', 'yes', 'on')
# First-pass best-of-N — default 2 since 2026-07-18 (was 1): every non-anchor
# cell generates two seeds and keeps the ArcFace-best candidate, the
# generate-then-filter margin the consistency research ranked highly. Roughly
# doubles sheet-generation GPU time; ZYG_CONTACT_SHEET_BEST_OF=1 restores
# single-shot timing.
CONTACT_SHEET_BEST_OF = max(1, int(os.environ.get('ZYG_CONTACT_SHEET_BEST_OF', '2')))
EXPANSION_COUNT = int(os.environ.get('ZYG_CONTACT_SHEET_EXPANSION_COUNT', '16'))
EXPANSION_W = int(os.environ.get('ZYG_CONTACT_SHEET_EXPANSION_W', '768'))
EXPANSION_H = int(os.environ.get('ZYG_CONTACT_SHEET_EXPANSION_H', '1152'))
# Quality floor for the LoRA-v2 flywheel: a scored expansion tile below this
# is too weak an identity to train on (it would pull v2 toward drift). Faceless
# back views (no_face_expected, unscored) always pass — they add angle coverage.
EXPANSION_MIN_SCORE = float(os.environ.get('ZYG_CONTACT_SHEET_EXPANSION_MIN_SCORE', '0.42'))

# Six angles per sheet (2×3 grid) — spread yaw across sheets A–B, lighting/body on C–D.
SHEET_A_ANGLES = [
    'camera straight on, front view head and shoulders, neutral expression, eyes to camera',
    'camera rotated 35 degrees left, three-quarter left view head and shoulders',
    'camera rotated 35 degrees right, three-quarter right view head and shoulders',
    'camera rotated 90 degrees left, left profile view, side of face visible',
    'camera rotated 90 degrees right, right profile view, side of face visible',
    'camera from behind above, back of head showing hair, shoulders visible',
]
SHEET_B_ANGLES = [
    'camera slightly above, slight upward angle front view head and shoulders',
    'camera slightly below, slight downward angle front view head and shoulders',
    'camera straight on, front view natural smile, teeth visible, head and shoulders',
    'camera rotated 35 degrees left, three-quarter left soft smile',
    'camera rotated 35 degrees right, three-quarter right soft smile',
    'camera straight on, front close-up face fill frame, detailed eyes skin pores',
]
SHEET_C_ANGLES = [
    'camera straight on, front view warm golden hour lighting on face',
    'camera rotated 35 degrees left, soft studio key light from left',
    'camera rotated 35 degrees right, soft studio key light from right',
    'camera straight on, front view cool neutral lighting, head and shoulders',
    'camera straight on, medium shot chest up, front view',
    'camera rotated 35 degrees left, medium shot chest up',
]
SHEET_D_ANGLES = [
    'camera rotated 35 degrees right, medium shot chest up',
    'camera rotated 35 degrees left, close-up face, freckles visible',
    'camera rotated 35 degrees right, close-up natural smile',
    'camera straight on, wide medium shot upper body front view',
    'camera rotated 30 degrees left, three-quarter walking pose medium shot',
    'camera straight on, dramatic rim light on face and hair',
]

# Extended sheets E–H: true viewpoint coverage for 3D reconstruction — full-body
# yaw ring, high/low pitch ring, fine head-yaw ring, crown/chin + ortho turnaround.
# Geometry views keep neutral pose/lighting; style variety stays on sheets B–D.
SHEET_E_ANGLES = [
    'camera straight on, full body front view, standing A-pose, whole figure head to feet',
    'camera rotated 45 degrees left, full body three-quarter left view, standing A-pose',
    'camera rotated 45 degrees right, full body three-quarter right view, standing A-pose',
    'camera rotated 90 degrees left, full body left profile view, standing A-pose',
    'camera rotated 90 degrees right, full body right profile view, standing A-pose',
    'camera from directly behind, full body back view, standing A-pose, outfit back detail',
]
SHEET_F_ANGLES = [
    'camera high angle 30 degrees above eye level, front view head and shoulders',
    'camera high angle 30 degrees above, three-quarter left view upper body',
    'camera high angle 30 degrees above, three-quarter right view upper body',
    'camera low angle 20 degrees below eye level, front view upper body',
    'camera low angle 20 degrees below, three-quarter left view upper body',
    'camera low angle 20 degrees below, three-quarter right view upper body',
]
SHEET_G_ANGLES = [
    'camera rotated 20 degrees left, near-frontal left view head and shoulders',
    'camera rotated 20 degrees right, near-frontal right view head and shoulders',
    'camera rotated 60 degrees left, strong three-quarter left view head and shoulders',
    'camera rotated 60 degrees right, strong three-quarter right view head and shoulders',
    'camera rotated 120 degrees left, back three-quarter left view, ear and jaw edge visible',
    'camera rotated 120 degrees right, back three-quarter right view, ear and jaw edge visible',
]
SHEET_H_ANGLES = [
    'camera directly overhead, top-down view of head crown and hair parting, shoulders visible',
    'camera slightly below chin level, upward view, jawline and neck detail visible',
    'camera straight behind at head height, back of head close view, hairline and hair texture',
    'camera straight on, full body front view, T-pose arms straight out, flat even lighting',
    'camera from directly behind, full body back view, T-pose arms straight out, flat even lighting',
    'camera rotated 90 degrees left, full body left profile, T-pose arms straight out, flat lighting',
]

SHEET_ANGLES_BY_PART: dict[str, list[str]] = {
    'a': SHEET_A_ANGLES,
    'b': SHEET_B_ANGLES,
    'c': SHEET_C_ANGLES,
    'd': SHEET_D_ANGLES,
    'e': SHEET_E_ANGLES,
    'f': SHEET_F_ANGLES,
    'g': SHEET_G_ANGLES,
    'h': SHEET_H_ANGLES,
}


def contact_sheet_angle_labels(angle_set: str | None = None) -> list[str]:
    labels: list[str] = []
    for part in sheet_parts_for(angle_set):
        labels.extend(SHEET_ANGLES_BY_PART[part])
    return labels


CONTACT_SHEET_ANGLE_LABELS = contact_sheet_angle_labels(None)
