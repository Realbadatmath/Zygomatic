# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: E402, F401  # the re-export block IS this module; the shim below it needs sys.


"""wan_video_service.py — Wan2.1-I2V-14B-480P image-to-video clip generation.

Generates short (~3.8 s) video clips by animating the FLUX-generated still
images produced by Stage 2.  Uses the I2V (image-to-video) variant so each
clip visually matches its source FLUX frame — correct lighting, composition,
and characters — rather than re-imagining the scene from text alone.

    Wan2.1-I2V-14B-480P      ~28 GB VRAM  (bfloat16)
    ─────────────────────────────────────
    Combined                  ~39 GB  →  fits in 48 GB (RTX 4090 / A6000)

Clips are written to:
    {out_dir}/wan_clips/wan_{idx:03d}.mp4

A manifest is saved to:
    {out_dir}/wan_clips/wan_manifest.json

The manifest maps each clip back to its source FLUX image path so Stage 6 can
substitute the live video in place of the static image in the slideshow.
"""

# wan_video_service.py, split at its own section banners. The sections are imported in the original
# declaration order, so every module-level side effect still runs in that order, and the
# first module carries the original top import block verbatim — re-exported here, so
# attribute access such as wan_video_service.os keeps resolving.

from zyg_workflows.wan_video_service.constants import (
    gc,
    json,
    os,
    shutil,
    subprocess,
    threading,
    time,
    exe,
    _comfy,
    _zyg_logging,
    _zyg_log,
    _MODEL_ID,
    _DEFAULT_N_CLIPS,
    _CLIP_FRAMES,
    _CLIP_FPS,
    _OUTPUT_FPS,
    _N_CHAINED,
    SEC_PER_SUBCLIP,
    _SEC_PER_SUBCLIP,
    VIDEO_SHORT_PRESETS,
    n_chained_for_scene_duration,
    effective_wan_scene_duration_sec,
    final_trim_target_sec,
    _WIDTH,
    _HEIGHT,
    _WAN_COMFY_MODEL,
    _WAN_ATTENTION,
    _WAN22,
    _WAN_LIGHTNING,
    _WAN22_BOUNDARY_FRACTION,
    _LIGHTNING_HIGH_LORA,
    _LIGHTNING_LOW_LORA,
    _INFER_STEPS,
    _GUIDANCE,
    _MOTION_FREEZE_THRESH,
    _T2V_MODEL_ID,
    _HUMAN_SUBJECT_KW,
    _MOTION_BY_EMOTION,
    _SCENE_MOTION_HINTS,
    _EMOTION_PRIORITY,
    _CAMERA_BY_SHOT,
    _STATIC_SHOT_NEG,
    _CINEMATIC_WAN_SUFFIX,
)
from zyg_workflows.wan_video_service.api import (
    _pipe,
    _pipe_lock,
    _t2v_pipe,
    _t2v_pipe_lock,
    generate,
    _load_pipe,
    _unload_pipe,
    _load_t2v_pipe,
    _unload_t2v_pipe,
)
from zyg_workflows.wan_video_service.helpers import (
    _generate_via_comfyui,
    _color_match_to,
    _extract_last_frame,
    _submit_wan_clip,
    _build_prompt,
    _stitch_clips,
    _compute_motion_score,
    _save_video,
    _interpolate_clip,
)

import sys as _sys
from types import ModuleType as _ModuleType

from zyg_workflows.wan_video_service import constants, api, helpers  # noqa: F401

_SECTIONS = (
    constants,
    api,
    helpers,
)


class _SplitModule(_ModuleType):
    """Writes an attribute set on the package through to the section that defines it.

    Before the split a `setattr(wan_video_service, name, value)` — which the smoke
    scripts and tests both do — was seen by every function in the file, because there
    was only one module dict. Rebinding only the package attribute would leave the
    section modules reading the original value, so the patch is forwarded.
    """

    def __setattr__(self, name, value):
        _ModuleType.__setattr__(self, name, value)
        for _m in self.__dict__.get('_SECTIONS') or ():
            if name in _m.__dict__:
                setattr(_m, name, value)

    def __delattr__(self, name):
        _ModuleType.__delattr__(self, name)
        for _m in self.__dict__.get('_SECTIONS') or ():
            if name in _m.__dict__:
                delattr(_m, name)


_sys.modules[__name__].__class__ = _SplitModule
