# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# This __init__ re-exports every name of the former single-file module.
# ruff: noqa: F401

"""video_studio.py — Video Studio tab backend: a full Wan2.1/2.2 I2V console.

Same shape as voice_studio.py: a declarative RACKS parameter spec the GUI
builds its panel from, sanitize() clamping whatever a caller sends, and a
threaded job queue polled by the client (start_render() -> job id -> job()).

Unlike the storyteller pipeline's wan_video_service.generate(), which batches
N candidate FLUX frames pulled from a scene's metadata, this is one operator,
one injected clip/portrait, one prompt, one clip — so it drives
wan_video_service's per-sub-clip primitive (_submit_wan_clip) directly instead
of the scene-batch entry point.

── 2026-09-02: full option surface ───────────────────────────────────────────
The rail used to carry 9 knobs (prompt/shot/mood/static + steps/cfg/shift/
seed/duration). Everything the ComfyUI wan graphs and the ffmpeg finishing
chain actually expose is now a first-class parameter, and every parameter
carries an ``icon`` + ``place`` so the GUI can render it as an icon in the
right rail (creative), the left rail (engine) or the bottom bar (post / QC)
instead of a scrolling form.

DISCIPLINE — no inert levers. Every key below reaches something real:
  * graph nodes    → node 1/7 loader, 11 image-encode, 20 text, 30/31 sampler,
                     40 decode, 45 CreateVideo, 50 SaveVideo, 6/8/9 LoRA
  * prompt builder → wan_video_service._build_prompt(meta, visual_style)
  * ffmpeg finish  → _post_process() below (one filtergraph + optional
                     stabilise pre-pass and loop post-pass)
  * QC             → wan_video_service._compute_motion_score + reseeded retry
Options that could NOT be wired against this stack were deliberately left out
rather than shipped as placeholders — see MISSING at the bottom of this file.

── 2026-10-06: one file became a package ─────────────────────────────────────
6336 lines in one module is not reviewable. The sections are now modules, each
holding its old lines verbatim, and this __init__ re-exports every name the
single file exposed, so ``from zyg_workflows import video_studio`` and
``video_studio.<anything>`` are unchanged:

  options.py        the choice lists scanned off disk      (old 67-178)
  spec.py           RACKS / ACTIONS / sanitize             (old 179-4001)
  prompts.py        the prompt builder                     (old 4002-4162)
  ffmpeg_finish.py  grade, stabilise, loop, side exports   (old 4163-5130)
  render_jobs.py    the job registry and the render gate   (old 5131-5189)
  assembly.py       the shot assembly job + the Wan graph  (old 5306-6302)
  presets.py        presets and the two start_render()s    (old 5190-5305)
"""

import hashlib  # noqa: F401 — re-exported: the pre-split module had it
import json  # noqa: F401 — re-exported: the pre-split module had it
import math  # noqa: F401 — re-exported: the pre-split module had it
import os
import shutil  # noqa: F401 — re-exported: the pre-split module had it
import subprocess  # noqa: F401 — re-exported: the pre-split module had it
import threading  # noqa: F401 — re-exported: the pre-split module had it
import time  # noqa: F401 — re-exported: the pre-split module had it

from zyg_workflows import wan_video_service as _wan  # noqa: F401 — re-exported: the pre-split module had it
from zyg_workflows import paths
from zyg_workflows import provenance_seal as _seal  # noqa: F401 — re-exported: the pre-split module had it
from zyg_workflows.bin import exe  # noqa: F401 — re-exported: the pre-split module had it

try:
    from zyg_workflows import _comfy_client as _comfy  # noqa: F401 — re-exported: the pre-split module had it
except ImportError:
    _comfy = None
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# The zyg_workflows directory — one level up now that video_studio is a package.
# The value is the same as when this was video_studio.py, and output/ and the
# preset/LUT directories under it are the same directories as before.
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_ROOT = os.path.realpath(os.path.join(HERE, 'output', 'video_studio'))
_PRESET_DIR = os.path.join(_OUT_ROOT, '_presets')
_LUT_DIR = os.path.join(_OUT_ROOT, '_luts')
_FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
_LORA_ROOT = str(paths.ZYG_COMFY_LORA_DIR)


# ─────────────────────────────────────────────────────── the module's surface
# Every name the single-file video_studio.py exposed, re-exported from the
# module it now lives in. Nothing is renamed; callers see no difference.
from .options import (  # noqa: E402 — below the constants the modules import from here
    PATHWAYS,
    RESOLUTIONS,
    _BED_CATS,
    _BED_MAX,
    _BED_WORDS,
    _DEF_PATHWAY,
    _ambience_options,
    _lora_options,
    _lut_options,
    _vfx_element_options,  # noqa: F401 — re-export, not a use
)
from .spec import (  # noqa: E402 — below the constants the modules import from here
    ACTIONS,
    RACKS,
    _PARAMS,
    defaults,
    nondefault,
    sanitize,  # noqa: F401 — re-export, not a use
)
from .prompts import (  # noqa: E402 — below the constants the modules import from here
    _MOTION_AMOUNT_TOKENS,
    _MOTION_SUBJECT_TOKENS,
    _STYLE_TOKENS,
    compose_link_prompts,
    compose_prompt,  # noqa: F401 — re-export, not a use
)
from .ffmpeg_finish import (  # noqa: E402 — below the constants the modules import from here
    _CONTAINER_EXT,
    _GRADES,
    _VCODEC,
    _WM_POS,
    _audio_spec,
    _bloom_pass,
    _color_match_filter,
    _detect,
    _esc_dt,
    _grade_chain,
    _loop_pass,
    _motion_series,
    _post_process,
    _probe,
    _run_ff,
    _side_exports,
    _stabilize,  # noqa: F401 — re-export, not a use
)
from .render_jobs import (  # noqa: E402 — below the constants the modules import from here
    _JOBS,
    _JOBS_LOCK,
    _JOB_KEEP,
    _RENDER_GATE,
    _job_log,
    _job_set,
    _prune_jobs,
    job,
    jobs,  # noqa: F401 — re-export, not a use
)
from .assembly import (  # noqa: E402 — below the constants the modules import from here
    _CACHE_NODES,
    _MEDIA_ROOT,
    _NODE_DEFAULTS,
    _assemble_worker,
    _augment_graph,
    _enable_comfy,
    _graph_overrides,
    _node,
    _prepare_shotlist,
    _render_one,
    _render_worker,
    _resolve_shot_path,
    _submit,
    start_assemble,  # noqa: F401 — re-export, not a use
)
from .presets import (  # noqa: E402 — below the constants the modules import from here
    _INJECT_FRAME_DIR,
    _extract_at,
    preset_delete,
    preset_load,
    preset_save,
    presets,
    start_render,
    start_render_from_video,  # noqa: F401 — re-export, not a use
)


# ────────────────────────────────────────────────────────────────── MISSING
# 2026-09-03. The gaps are no longer only a comment: every one of them is also
# a marked cell in the NOT BUILT rack, so the absence is visible in the GUI
# rather than only to somebody reading this file. Kept here with the reasons:
#
#  * ControlNet / VACE pose-and-depth control.  A different graph
#    (Wan2_1-VACE_module) with its own control-plate discipline — it belongs in
#    the Movement tab, which already has the plate tooling.
#  * Face restore.  Per-frame, and it would fight the identity LoRA it is meant
#    to preserve.  It does not ship without a measurement first.
#  * LLM prompt extension.  WanVideoPromptExtender is installed but wants its
#    own local LLM, and every LLM call in this project has to go through the
#    logged SDK path.
#
# 2026-09-14 — four of the entries above were built and are no longer missing:
#  * Audio (bed, SFX cues, ducking, LUFS) — the AUDIO rack, through
#    video_audio.build_track, which is a caller of audio_mix and NOT a second
#    loudness path.
#  * AI super-resolution and AI frame interpolation — the FINISH rack's AI
#    upscale select and interp_mode=rife, through video_finish.esrgan_clip
#    (33-frame ComfyUI batches, so VRAM stays flat) and
#    video_finish.rife_2x (rife-ncnn-vulkan, which IS installed now).
#  * Matte / key — superseded by the OVERLAY rack: alpha elements are
#    composited from a placement record rather than segmented per frame.
#  * Multi-shot timeline — the SHOTS rack and the Assemble shots action, on
#    video_assembly.assemble.  The console is still single-shot at RENDER
#    time; assembly is a separate job over clips that already exist.
#
# NO LONGER MISSING, and worth recording because the old note here said the
# opposite: first-last-frame conditioning IS available — the installed
# WanVideoImageToVideoEncode has an ``end_image`` input (plus
# ``fun_or_fl2v_model``, ``augment_empty_frames`` and ``tiled_vae``). The
# 2026-09-02 note claiming the wrapper had no end_image input was measured
# against an older wrapper; it is wired now, in the SOURCE rack.
