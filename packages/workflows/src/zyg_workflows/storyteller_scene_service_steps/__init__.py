# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: E402, F401  # the re-export block IS this module; the shim below it needs sys.


"""storyteller_scene_service_steps.py — the stages of build_scene, one per step.

A pure extraction of storyteller_scene_service.build_scene's body, which had
grown to 1,254 lines in a single function. Every `_step_*` below is the block
that used to sit under the matching `# N ──` banner, with the locals it read
passed in explicitly and the ones the next stage needs returned; nothing was
reordered, no default changed, no call dropped.

The scene helpers the steps call still live in the service module and are
reached through `_svc()`, which imports it on use — the same pattern
comfy_generation_service_steps uses, so the service's monkeypatchable globals
stay live and no import order can turn this into a cycle.
"""

# storyteller_scene_service_steps.py, split at its own section banners. The sections are imported in the original
# declaration order, so every module-level side effect still runs in that order, and the
# first module carries the original top import block verbatim — re-exported here, so
# attribute access such as storyteller_scene_service_steps.os keeps resolving.

from zyg_workflows.storyteller_scene_service_steps.stills import (
    annotations,
    json,
    logging,
    math,
    os,
    shutil,
    subprocess,
    time,
    Any,
    np,
    Image,
    ImageEnhance,
    ImageFilter,
    _seal,
    exe,
    _zyg_log,
    _svc,
    _GateReceipts,
    _free_comfy_vram,
    _step_stills,
    _step_wardrobe_lock,
    _step_prop_edit,
    _step_hand_repair,
    _step_derived_stills,
)
from zyg_workflows.storyteller_scene_service_steps.timeline import (
    _line_voice,
    _line_wav,
    _step_voice_lines,
    _at_time,
    _step_timeline,
)
from zyg_workflows.storyteller_scene_service_steps.audio import (
    _step_stem,
    _bed_track,
    _music_cues,
    _step_master,
)
from zyg_workflows.storyteller_scene_service_steps.frames import (
    _window_view,
    _shot_frame,
    _frame_head_reveal,
    _frames_context,
    _step_frames,
    _step_encode,
    _scene_state,
)

import sys as _sys
from types import ModuleType as _ModuleType

from zyg_workflows.storyteller_scene_service_steps import stills, timeline, audio, frames  # noqa: F401

_SECTIONS = (
    stills,
    timeline,
    audio,
    frames,
)


class _SplitModule(_ModuleType):
    """Writes an attribute set on the package through to the section that defines it.

    Before the split a `setattr(storyteller_scene_service_steps, name, value)` — which the smoke
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
