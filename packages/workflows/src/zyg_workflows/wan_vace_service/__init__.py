# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""wan_vace_service.py — VACE masked-control generation: the IN-MODEL set-lock.

Second-generation fix for locked-camera set morphing (2026-07-29 research): instead of
compositing after the fact (wan_setlock), VACE re-asserts the still's structure EVERY frame
inside the model. The still is fed as (a) the per-frame control content, (b) the reference
image, and a character MASK marks where generation is allowed:
    mask WHITE (1) = generate here  (the characters, their motion envelope)
    mask BLACK (0) = keep control content  (walls, furniture, props — pinned per frame)
Background is re-derived from the still every frame — no drift, no push-in, by construction.

Models (Apache-2.0, Kijai repacks): Wan2_1-T2V-14B fp8 base + Wan2_1-VACE_module_14B fp8
attached via WanVideoVACEModelSelect → WanVideoModelLoader.extra_model.

Public API:
    build_char_mask(still_path, out_path, n_regions=2, boxes=None)  -> mask png path
    build_motion_envelope_mask(motion_clip, out_path, ...)          -> mask png path (A3)
    preflight_mask_gates(mask_path, ...)                            -> (ok, reason)   (C3)
    clip_prompt_beats(prompt, limit=None, tag=..., log_fn=None)     -> per-beat clipped str
    beat_window_map(num_frames, context_frames, context_overlap, num_beats, has_ref=True)
                                                                    -> schedule report dict
    assert_no_dead_beats(...)                                       -> map, or raises
    pin_regions_from_meta(meta, level=0.65, keys=('candle_box',))   -> pin_regions list
    build_graded_pin_mask(mask_path, out_path, pin_regions=[...])   -> png path or None
    build_mask_sequence(mask_path, out_dir, num_frames, size)       -> (dir, union, n)
    build_control_sequence(still_fit, mask_dir, out_dir, ...)       -> dir or None
    generate_vace_static_clip(still_path, prompt, out_dir, ...)     -> clip path or None
"""

import sys as _sys
from types import ModuleType as _ModuleType

# Pattern A package: every name the single-file module defined is re-exported here,
# in its original declaration order, so `wan_vace_service.<anything>` still resolves
# (including the top import block: .base holds `os`, `math`, `shutil`, `Image`,
# `ImageDraw`, `ImageFilter`, `exe`, `_QCBlocked` and `_zyg_logging`).
from zyg_workflows.wan_vace_service.base import (
    os,
    math,
    shutil,
    Image,
    ImageDraw,
    ImageFilter,
    exe,
    _QCBlocked,
    _zyg_logging,
    _zyg_log,
    _HERE,
    _T2V_MODEL,
    _VACE_MODULE,
    _static_neg,
    _log_noop,
    _env_flag,
    _env_int,
    _env_float,
)
from zyg_workflows.wan_vace_service.beats import (
    _BEAT_SEP,
    beat_char_limit,
    _clip_one,
    clip_prompt_beats,
    clip_negative,
    beat_window_map,
    assert_no_dead_beats,
)
from zyg_workflows.wan_vace_service.masks import (
    build_char_mask,
    _mask_stats,
    _disk,
    _binmorph,
    _components,
    _clip_temporal_std,
    _envelope_from_std,
    _feather_and_crush,
    build_motion_envelope_mask,
    _default_max_white,
    preflight_mask_gates,
)
from zyg_workflows.wan_vace_service.probe import (
    generate_vace_with_probe,
    paste_back_keep_regions,
    generate_vace_clip_from_frames,
)
from zyg_workflows.wan_vace_service.graded_pin import (
    PIN_WHOLE_MASK,
    _PIN_NEUTRAL,
    _PIN_FEATHER_PX,
    _resolve_pin_regions,
    pin_regions_from_meta,
    _feather_ramp,
    build_graded_pin_mask,
)
from zyg_workflows.wan_vace_service.sequences import (
    _SEQ_EXT,
    _VID_EXT,
    _MASK_GLOBS,
    is_mask_sequence,
    _seq_source_frames,
    build_mask_sequence,
    build_control_sequence,
    _CTRL_GLOBS,
    control_frames_in,
    build_control_from_dir,
    paint_control_frame,
    paint_control_sequence,
    stamp_control_channel,
)
from zyg_workflows.wan_vace_service.static_clip import (
    generate_vace_static_clip,
)

_SECTION_NAMES = ('base', 'beats', 'masks', 'graded_pin', 'sequences', 'static_clip', 'probe')


# ---------------------------------------------------------------------------
# Live attribute patching across the split.
#
# wan_prop_restore.py:399-416 does `V._static_neg = _neg_with_prop`, calls
# generate_vace_clip_from_frames and restores it. In the single-file module that
# one assignment reached every caller, because caller and callee shared one
# __dict__. Split across modules it would only rebind the package attribute and
# the section modules would keep their own binding, so the patch would silently
# do nothing. This ModuleType subclass writes a patched name through into every
# section module that already holds it, which restores the old semantics
# exactly. Must stay the last statement in this file.
# ---------------------------------------------------------------------------


class _WanVaceServiceModule(_ModuleType):
    """Package module whose attribute writes propagate to the section modules."""

    def __setattr__(self, name, value):
        _ModuleType.__setattr__(self, name, value)
        for _section in self.__dict__.get('_SECTIONS') or ():
            if name in _section.__dict__:
                _section.__dict__[name] = value

    def __delattr__(self, name):
        for _section in self.__dict__.get('_SECTIONS') or ():
            _section.__dict__.pop(name, None)
        _ModuleType.__delattr__(self, name)


_SECTIONS = tuple(_sys.modules[f'{__name__}.{_n}'] for _n in _SECTION_NAMES)

_sys.modules[__name__].__class__ = _WanVaceServiceModule


# The re-exported surface of the pre-split module, in import order: every name
# here exists only so that `<this module>.<name>` keeps resolving for importers.
__all__ = [
    'os',
    'math',
    'shutil',
    'Image',
    'ImageDraw',
    'ImageFilter',
    'exe',
    '_QCBlocked',
    '_zyg_logging',
    '_zyg_log',
    '_HERE',
    '_T2V_MODEL',
    '_VACE_MODULE',
    '_static_neg',
    '_log_noop',
    '_env_flag',
    '_env_int',
    '_env_float',
    '_BEAT_SEP',
    'beat_char_limit',
    '_clip_one',
    'clip_prompt_beats',
    'clip_negative',
    'beat_window_map',
    'assert_no_dead_beats',
    'build_char_mask',
    '_mask_stats',
    '_disk',
    '_binmorph',
    '_components',
    '_clip_temporal_std',
    '_envelope_from_std',
    '_feather_and_crush',
    'build_motion_envelope_mask',
    '_default_max_white',
    'preflight_mask_gates',
    'generate_vace_with_probe',
    'paste_back_keep_regions',
    'generate_vace_clip_from_frames',
    'PIN_WHOLE_MASK',
    '_PIN_NEUTRAL',
    '_PIN_FEATHER_PX',
    '_resolve_pin_regions',
    'pin_regions_from_meta',
    '_feather_ramp',
    'build_graded_pin_mask',
    '_SEQ_EXT',
    '_VID_EXT',
    '_MASK_GLOBS',
    'is_mask_sequence',
    '_seq_source_frames',
    'build_mask_sequence',
    'build_control_sequence',
    '_CTRL_GLOBS',
    'control_frames_in',
    'build_control_from_dir',
    'paint_control_frame',
    'paint_control_sequence',
    'stamp_control_channel',
    'generate_vace_static_clip',
]
