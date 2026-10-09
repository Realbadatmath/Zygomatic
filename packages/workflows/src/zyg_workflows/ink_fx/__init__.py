# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ink_fx.py — programmatic write-on ink compositing (2026-07-30, v3 2026-07-31).

No video model renders letters appearing at a nib (documented universal failure) — the
motion-graphics write-on technique is the only real answer: pre-render finished 'hand-
writing' (period-appropriate script TEXTURE — squiggly strokes that read as writing
without being legible gibberish), then reveal it progressively inside the pinned page
region at writing pace. With the book pinned (paste-back), the page is screen-static,
so the reveal needs no tracking.

    make_script_texture(w, h, lines, seed)              -> PIL image (ink on transparent)
    composite_write_on(clip, out, page_box, start_s, end_s, fps, lines) -> out|None
    composite_write_on_quad(clip, out, page_quad, ...)  -> out|None   (v2, 2026-07-30)

v2 (composite_write_on_quad) exists because scene20 v7 forensics showed v1's
axis-aligned page_box overspraying strokes onto the TABLE and floating them without
page perspective or lighting: v2 takes the ACTUAL page corner quad, builds the script
in rectified page space, perspective-warps it into the frame, clips to the page
polygon, and multiply-blends so ink brightness follows local page luminance.

v3 (2026-07-31) — WHY, from forensics on FINAL_scene20_v8b.mp4 (operator: "the ink
reads as painted ON SCREEN, not in the book"):

  * The composited page measured Laplacian variance 728.2 against the raw render's
    222.4 — 3.27x TOO SHARP — and per-pixel temporal sigma 0.80 against the raw
    render's 3.94 — 4.9x TOO TEMPORALLY DEAD.  A razor-sharp, frozen element inside
    a soft, boiling diffusion render is the classic sticker tell.  That is the
    primary cause, ahead of the fixed quad (three independent measurements put the
    page's real rigid drift at only 1-4px across all 341 frames).
    Fixes: the `a_done` cache is GONE (it froze alpha bit-for-bit once the reveal
    completed); the frame-space blur is auto-calibrated by bisection so
    lapvar(inked)/lapvar(raw) lands in [0.95, 1.20] instead of a fixed sigma 0.5;
    per-frame grain rides on the ALPHA (never on the frame, or the paper gets
    noised twice); and the page homography is rebuilt every frame with sub-pixel
    jitter drawn from SMOOTH 1-D noise (white noise reads as a buzzing sticker,
    smooth noise reads as a hand-held camera / breathing page).
    NOTE: deleting the cache is necessary but NOT sufficient — with grain and
    jitter both off the recomputed alpha is bit-identical, so the temporal-sigma
    ratio only recovers when `grain`/`jitter` are on.

  * `composite_write_on_quad` clipped alpha to the page polygon only, so anything
    IN FRONT of the page inside that polygon was ignored — and the writing hand
    covers ~31% of the page box on every frame, i.e. about a third of every stroke
    was landing on flesh.  v3 propagates a SAM2.1 video matte (hand+cuff and the
    quill as SEPARATE objects — one box for both leaks onto the sleeve and drops
    the thin quill — plus negative points on bare paper) and multiplies the alpha
    by (1 - matte) right before the blend.  Composite at render resolution BEFORE
    upscale/interpolation so matte and frames share one coordinate system.
    The matte is cached to <out_dir>/ink_matte.npz so reruns are cheap.
    SAM2 is entirely optional: if it is unavailable the module logs LOUDLY and
    composites without occlusion rather than failing the pipeline.

  * The cheap, risk-free half of the planar-tracker idea ships as
    `page_rigid_drift_px()` — a TRIPWIRE, not a tracker. Measured on scene20 v8:
    max 1.38px / median 0.50px of rigid page drift across all 341 frames, which is
    why the fixed quad stays and no mesh warp is applied. If a future run widens the
    generate mask and the page really starts to move, the readout says so instead of
    the ink silently smearing.

`stats_out` (optional dict) receives the composite-integrity trio measured on the
run itself — sharpness ratio, temporal-sigma ratio, matte violation — so callers can
gate on the RATIO (never on absolute values; they are scene-dependent).

Measured on output/multichar_seated/scene20_v8/vace_static.mp4 (832x480, 17fps, 341f,
page_quad from shot_metadata.json, lines=5, 5.0-12.5s), v2 -> v3:
    sharpness ratio         3.987 -> 1.019   (gate <= 1.30)
    temporal sigma ratio    0.934 -> 1.036   (gate >= 0.60)   on-ink 0.803 -> 1.143
    matte violation         0.413 -> 0.0009  (gate <= 0.005)
    qc_region_flow a_hand   0.233 -> 0.254   (raw render 0.254 — v3 costs NO motion,
                                              and gives back the 8% v2's frozen ink
                                              was damping)
"""

# ruff: noqa: E402,F401
import glob
import json
import os
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import logging as _zyg_logging
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)

from zyg_workflows.ink_fx import tunables as tunables
from zyg_workflows.ink_fx import write_on as write_on
from zyg_workflows.ink_fx import stats_jitter as stats_jitter
from zyg_workflows.ink_fx import occlusion as occlusion
from zyg_workflows.ink_fx import compositor as compositor

from zyg_workflows.ink_fx.tunables import INK_SAM2_ENABLED as INK_SAM2_ENABLED
from zyg_workflows.ink_fx.tunables import INK_AUTO_BLUR as INK_AUTO_BLUR
from zyg_workflows.ink_fx.tunables import SHARPNESS_TARGET as SHARPNESS_TARGET
from zyg_workflows.ink_fx.tunables import TEMPORAL_TARGET as TEMPORAL_TARGET
from zyg_workflows.ink_fx.tunables import BLUR_SIGMA_RANGE as BLUR_SIGMA_RANGE
from zyg_workflows.ink_fx.tunables import GRAIN_MUL_SIGMA as GRAIN_MUL_SIGMA
from zyg_workflows.ink_fx.tunables import GRAIN_ADD_SIGMA as GRAIN_ADD_SIGMA
from zyg_workflows.ink_fx.tunables import JITTER_PX as JITTER_PX
from zyg_workflows.ink_fx.tunables import JITTER_SCALE as JITTER_SCALE
from zyg_workflows.ink_fx.tunables import JITTER_CORR_FRAMES as JITTER_CORR_FRAMES
from zyg_workflows.ink_fx.write_on import _log_noop as _log_noop
from zyg_workflows.ink_fx.write_on import make_script_texture as make_script_texture
from zyg_workflows.ink_fx.write_on import composite_write_on as composite_write_on
from zyg_workflows.ink_fx.write_on import _reveal_lines_mask as _reveal_lines_mask
from zyg_workflows.ink_fx.write_on import _ink_tint as _ink_tint
from zyg_workflows.ink_fx.stats_jitter import _gray as _gray
from zyg_workflows.ink_fx.stats_jitter import _lap_var as _lap_var
from zyg_workflows.ink_fx.stats_jitter import _smooth_series as _smooth_series
from zyg_workflows.ink_fx.stats_jitter import _jitter_warp as _jitter_warp
from zyg_workflows.ink_fx.stats_jitter import _build_alpha as _build_alpha
from zyg_workflows.ink_fx.stats_jitter import _blend as _blend
from zyg_workflows.ink_fx.stats_jitter import _auto_blur_sigma as _auto_blur_sigma
from zyg_workflows.ink_fx.stats_jitter import _temporal_ratio as _temporal_ratio
from zyg_workflows.ink_fx.stats_jitter import _auto_grain_scale as _auto_grain_scale
from zyg_workflows.ink_fx.occlusion import _box_iou as _box_iou
from zyg_workflows.ink_fx.occlusion import _box_overlap_area as _box_overlap_area
from zyg_workflows.ink_fx.occlusion import _seed_boxes_gdino as _seed_boxes_gdino
from zyg_workflows.ink_fx.occlusion import _paper_points as _paper_points
from zyg_workflows.ink_fx.occlusion import _sam2_images_cpu as _sam2_images_cpu
from zyg_workflows.ink_fx.occlusion import _matte_device as _matte_device
from zyg_workflows.ink_fx.occlusion import _matte_signature as _matte_signature
from zyg_workflows.ink_fx.occlusion import occlusion_matte as occlusion_matte
from zyg_workflows.ink_fx.compositor import page_rigid_drift_px as page_rigid_drift_px
from zyg_workflows.ink_fx.compositor import composite_write_on_quad as composite_write_on_quad
