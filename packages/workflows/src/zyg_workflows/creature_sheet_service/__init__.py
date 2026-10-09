# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
creature_sheet_service.py
=========================
Multi-angle reference sheet for a CREATURE — from one or more reference images,
or from scratch (text brief) — with every stage judging what it produced.

Built 2026-08-25 to replace the May-2026 creature path, which rendered 20
independent FLUX.1-dev txt2img stills (each angle a fresh invention of the
model, no identity link between cells, no QC at all, and FLUX.1-dev is paused
under the licence gate). Shape mirrors the human contact-sheet pipeline:

    anchor  →  per-cell camera-rotation EDITS of the anchor  →  QC  →  regen  →  sheet

  * Anchor (reference mode): the operator's image(s). The best-framed one is
    the identity anchor; when it is a partial view (a face close-up) a FULL-BODY
    anchor is derived from it by a Qwen edit and judged against the source.
  * Anchor (scratch mode): FLUX.2 klein-4B txt2img (Apache-2.0), best-of-N
    seeds, each judged against the brief.
  * Rotations: Qwen-Image-Edit-2509 + the dx8152 multiple-angles LoRA
    (`qwen_edit_angle` graph, the same engine the human sheet uses). Identity
    comes from EDITING the anchor, so it cannot drift the way txt2img does.
  * Per-cell QC, three independent judges, all recorded per cell:
      1. structural  — blank/black frame, unchanged-vs-anchor (phash), duplicates
      2. identity    — DINOv2 CLS cosine vs the anchor the cell was edited from
                       (creature_identity; ArcFace is useless on non-humans)
      3. semantic    — Qwen3-VL binary checklist on a REFERENCE|CANDIDATE strip
                       (creature_judge): same creature, one subject, no human,
                       no text, anatomy intact, viewpoint matches.
    A failed cell is regenerated with new seeds (ladder); the best candidate
    by (judge pass, DINO score) wins; an unrepaired cell stays ON the sheet
    marked EXCLUDED and out of the training set — the operator sees exactly
    what would train.

Everything the run used is Apache-2.0 / MIT tooling; nothing routes through
FLUX.1-dev. Outputs live under ``<dataset_dir>/contact_sheet/`` (cells,
strips, report) with ``sheet.png`` also copied to the dataset root so the
existing creature-image route can serve it. Training tiles are written by the
caller into ``<dataset_dir>/training/`` (SimpleTuner rglobs recursively, so the
working files must not sit beside the tiles).
"""
# ruff: noqa: E402,F401  # a Pattern A package: the __init__ re-exports the old surface

from __future__ import annotations

# The original top import block, re-done so old attribute accesses on the module
# (creature_sheet_service.os, .json, ._cid, …) still resolve.
import json
import os
import shutil
import time
from typing import Any, Callable

from zyg_workflows import creature_identity as _cid
from zyg_workflows import creature_judge as _cj
import logging as _zyg_logging

# The section modules, in the ORIGINAL section order, then every name the old
# module defined (public and underscore alike).
from . import base, images, comfy, build, build_anchors, build_cells, tiles
from .base import _zyg_log
from .base import SHEET_DIRNAME, SHEET_FILENAME, REPORT_FILENAME, CELL_SIZE, MAX_REGEN, SCRATCH_ANCHOR_SEEDS
from .base import _KEEP, SOFT_FLAGS, LOCKED_VIEW_EXEMPT, MAX_REGEN_SOFT, CONFORM_SEEDS, SIDE_TOWARD_BACK
from .base import _SIDE_TEXT_Q, _SIDE_TEXT_BACK, keep_sentence, anchor_locks, _file_sig, _text_sig
from .base import _mirror, _opposite, side_instruction, ANGLES, COMPACT_IDS, angle_plan
from .base import sheet_dir, sheet_path, report_path, load_report, _split_flags, caption_mode
from .base import _score_key
from .images import (
    _prepare_reference,
    _crop_letterbox_image,
    strip_letterbox,
    structural_check,
    make_strip,
    stitch_sheet,
)
from .comfy import _NEG, _edit, _txt2img, conform_instruction, check_anchor_agreement, conform_variants
from .comfy import conform_anchor
from .build import build_sheet
from .tiles import training_tiles, reclassify

# Tests and callers patch this module's attributes (monkeypatch.setattr(css,
# '_edit', …)). The patched name is read through the *section module's* globals,
# which a plain setattr on the package would not reach, so every attribute write
# is propagated to the section modules that hold that name.
import sys as _sys
from types import ModuleType as _ModuleType

_SECTIONS = (base, images, comfy, build, build_anchors, build_cells, tiles)


class _CreatureSheetModule(_ModuleType):
    def __setattr__(self, name, value):
        _ModuleType.__setattr__(self, name, value)
        for _m in self.__dict__.get('_SECTIONS') or ():
            if name in _m.__dict__:
                setattr(_m, name, value)

    def __delattr__(self, name):
        for _m in self.__dict__.get('_SECTIONS') or ():
            if name in _m.__dict__:
                delattr(_m, name)
        _ModuleType.__delattr__(self, name)


_sys.modules[__name__].__class__ = _CreatureSheetModule
