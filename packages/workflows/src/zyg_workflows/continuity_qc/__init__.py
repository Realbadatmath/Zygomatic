# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""continuity_qc.py — grounded continuity suite (2026-07-30).

Wires the three heavy detectors that were already sitting on disk but were never
wired into any gate:

    GroundingDINO SwinT-OGC  (Apache-2.0)  open-vocabulary box grounding
    SAM2.1 hiera base_plus   (Apache-2.0)  mask propagation inside a context window
    DINOv2 ViT-S/14          (Apache-2.0)  appearance embedding (VBench protocol)

Why it exists: the scene20_v7 post-mortem showed the NCC prop gate is texture-gameable
(a pipe bowl can INFLATE while keeping NCC high because the clay texture is unchanged),
and the comparative-CLIP "kid is not smoking" gate passes whenever *anybody* smokes.
Both failures need boxes, not crops-at-a-fixed-rectangle:

    analyze_clip()      per-object presence / box-IoU / mask-area drift / DINOv2
                        appearance cosine across the 57-frame context-window seams,
                        plus inverse-mask background consistency (set re-derivation).
    action_ownership()  grounded actor boxes vs the action-prop box: the pipe must
                        overlap the MAN, not the BOY, at each draw time.

Everything is SHADOW MODE by default — it reports and writes run_ledger gates, it
never blocks generation. Every entry point is fail-safe: an internal error returns
{'ok': True, 'error': ...} so a broken QC layer can never kill a render.

Contracts used (defensive import, absence is not an error):
    run_ledger.record_gate(run_id, gate, outcome, score=None, tag='')

Device policy: device='auto' takes CUDA only when nvidia-smi reports >= 8 GB free
(the GPU floor rule — a QC pass must never OOM a live render); otherwise CPU.
CPU is ~10x slower but fully supported and is what every number below was measured
on: 448 s wall for a 20 s 832x480 clip at sample_fps=2 (43 sampled frames, 6
windows, 3 props + 2 actor masks), on 24 cores with a Wan render competing for
them. GroundingDINO is ~3.8 s/frame and SAM2 ~2.4 s/frame/object at 1024x1024.

Measured on output/multichar_seated/scene20_v7/pasted17.mp4 (832x480, 17 fps,
341 frames) — see CALIBRATION at the bottom of this file for the numbers the
default thresholds were fitted to.
"""

# The original top import block and the re-export block below are deliberate.

import json
import os
import subprocess
import sys
import time
import logging as _zyg_logging

from zyg_workflows import paths
from zyg_workflows.bin import exe

from zyg_workflows.continuity_qc.models import (
    _HF_REVISION,
    _zyg_log,
    GDINO_WEIGHTS,
    GDINO_CONFIG,
    SAM2_WEIGHTS,
    SAM2_NODE_DIR,
    DINOV2_MODEL_ID,
    CONTEXT_STRIDE_FRAMES,
    DEFAULT_THRESHOLDS,
    _GPU_FLOOR_BYTES,
    _CACHE,
    _SAM2_PKG,
    _free_vram_bytes,
    pick_device,
    _gate,
    _load_gdino,
    _sam2_cfg_for,
    _load_sam2,
    _load_dino,
    available,
    _sample_frames,
    _frames_at_times,
    _caption_and_spans,
    _nms,
    _detect,
    _select_box,
    _iou,
    _containment,
    _sam2_batch,
    _track_window,
    _embed,
    _mask_bbox,
    _crops,
)
from zyg_workflows.continuity_qc.clip import (
    analyze_clip,
    _wget,
    _anchor_cosines,
    _verdict_object,
    _verdict_background,
)
from zyg_workflows.continuity_qc.ownership import (
    action_ownership,
    _V7,
    _V7_OBJECTS,
    _V7_ACTORS,
    _main,
)


# Every name below is imported above and not used in this module: this package
# IS the re-export surface of the pre-split module, so the imports are the
# deliberate public surface, not dead weight.  Nothing does ``import *`` from
# here, so __all__ changes no behaviour.
__all__ = [
    'json',
    'os',
    'subprocess',
    'sys',
    'time',
    '_zyg_logging',
    'paths',
    'exe',
    '_HF_REVISION',
    '_zyg_log',
    'GDINO_WEIGHTS',
    'GDINO_CONFIG',
    'SAM2_WEIGHTS',
    'SAM2_NODE_DIR',
    'DINOV2_MODEL_ID',
    'CONTEXT_STRIDE_FRAMES',
    'DEFAULT_THRESHOLDS',
    '_GPU_FLOOR_BYTES',
    '_CACHE',
    '_SAM2_PKG',
    '_free_vram_bytes',
    'pick_device',
    '_gate',
    '_load_gdino',
    '_sam2_cfg_for',
    '_load_sam2',
    '_load_dino',
    'available',
    '_sample_frames',
    '_frames_at_times',
    '_caption_and_spans',
    '_nms',
    '_detect',
    '_select_box',
    '_iou',
    '_containment',
    '_sam2_batch',
    '_track_window',
    '_embed',
    '_mask_bbox',
    '_crops',
    'analyze_clip',
    '_wget',
    '_anchor_cosines',
    '_verdict_object',
    '_verdict_background',
    'action_ownership',
    '_V7',
    '_V7_OBJECTS',
    '_V7_ACTORS',
    '_main',
]
