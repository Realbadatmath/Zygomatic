#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""scene_shot_run.py — one shot.json in, one final.mp4 out.

This is the assembler for the Blender scene bridge: the operator's six questions
(where is the city, where is the camera, where are the VFX, where is the actor,
what does the video engine do with all that, and what does it look like cut
together) are answered by seven stages that already exist as separate tools.
This module is the only place that knows the ORDER, the caching rule and the
composite.

    "…/agents/.venv/bin/python" scene_shot_run.py \
        data/architecture/shots/<id>/shot.json \
        [--engine vace|animate] [--skip-video] [--draft-only] [--force STAGE,…]

STAGES — each idempotent, each skipped when its outputs are newer than its
inputs, each writing a line into ``<shot_dir>/receipt.json``:

  1 validate   scene_shot.load + validate + resolve_positions -> shot.resolved.json
  2 build      blender_scripts/scene_build.py                 -> scene.blend
  3 draft      blender_scripts/scene_render.py --mode draft   -> draft/draft.mp4
  4 plates     scene_plates_export.py then scene_plates.build -> plates_raw/, plates/
  5 video      VACE (movement_studio scene_plateset path) or Wan-Animate
               (wan_animate_service.animate_from_plateset)    -> video/<engine>_take<N>/
  6 vfx        scene_render.py --mode full --effects-only 1   -> full/effects_alpha.mov
  7 composite  ffmpeg: engine clip + the alpha element        -> final.mp4, final_strip.png

WHY THE VFX ARE A SEPARATE LAYER. The video engine resamples the actor region of
a Blender beauty plate; it has never seen the volumes, and asking it to keep them
would be asking it to re-invent a Cycles render. So the volumes are rendered ONCE
in Cycles with the geometry as a holdout, come out as ProRes 4444 with a real
alpha, and are laid over the engine's output. The honest cost of that choice is
recorded in the docs: the VFX are not lit by, and do not light, the engine's
picture.

Locks. Every headless Blender launch holds the flock on
``/tmp/claude-1000/arch_ext_blender.lock`` (two at once SIGBUS the Bonsai
add-on). The two stages that put a model or a path tracer on the GPU — 5 and 6 —
additionally hold ``geom.pose_track.gpu_lock``.
"""

from __future__ import annotations

# ruff: noqa: F401  this module inherits the pre-split top import block: its
# siblings re-import those names from here.

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from zyg_workflows import paths
from zyg_workflows.bin import exe
import logging as _zyg_logging

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.scene_shot_run')


HERE = str(paths.PKG_DIR)

BLENDER = '/usr/local/bin/blender'
BLENDER_LOCK = os.path.join(tempfile.gettempdir(), 'claude-1000', 'arch_ext_blender.lock')
SCRIPTS = os.path.join(HERE, 'blender_scripts')

SCHEMA = 'zyg.scene_shot_run/1'
STAGE_ORDER = ('validate', 'build', 'draft', 'plates', 'video', 'vfx', 'composite')


def _log(msg):
    _zyg_log.info(msg)


# ── subject resolution ───────────────────────────────────────────────────────
# The identity seats (still / prompt binding / Wan LoRA / VACE refs) a shot's
# actor fills. This used to be imported from the dashboard's Movement Studio
# blueprint (``bp_movement._resolve_character``) — the forbidden direction, and
# unnecessary: resolving a character is library work on canon_service and the
# dataset tree, with no Flask in it. It lives here so the headless shot runner
# and tools/recipe_probe.py share one resolver.

CHARS_ROOT = os.path.realpath(paths.ZYG_STORYTELLER_CHARS)
LORA_ROOT = str(paths.ZYG_COMFY_ROOT / 'models' / 'loras')
_CHAR_ID_RE = re.compile(r'^[A-Za-z0-9_]{6,24}$')
_IMG_EXT = ('.png', '.jpg', '.jpeg', '.webp')


def _images_in(d, prefix=None, limit=8):
    """Sorted image paths directly under one directory — the pool the extra
    identity refs are drawn from. Never recurses: a ref must be a portrait of the
    subject, and the first thing a recursive walk finds under a character folder
    is training crops."""
    try:
        names = sorted(
            n for n in os.listdir(d) if n.lower().endswith(_IMG_EXT) and (not prefix or n.startswith(prefix))
        )
    except OSError:
        return []
    return [os.path.join(d, n) for n in names[:limit]]


def resolve_character(sid):
    """``{'still', 'binding', 'lora', 'refs'}`` for a storyteller character, or None.

    None means "not a usable subject": a malformed id, a path outside the dataset
    root, or no canon portrait on disk.
    """
    if not _CHAR_ID_RE.match(sid):
        return None
    d = os.path.realpath(os.path.join(CHARS_ROOT, sid))
    if not (d.startswith(CHARS_ROOT + os.sep) and os.path.isdir(d)):
        return None
    from zyg_workflows import canon_service as CS

    still = CS.canon_portrait(sid)
    if not still or not os.path.isfile(still):
        return None
    lora = None
    for cand in (f'wan_chars/wan_char_{sid}_t2v.safetensors', f'wan_chars/wan_char_{sid}.safetensors'):
        if os.path.isfile(os.path.join(LORA_ROOT, cand)):
            lora = cand
            break
    # ref candidates, best first. build_vace_ref is the one purpose-built for this
    # seat (white-background bust, per the VACE user guide) — the raw contact-sheet
    # cells behind it are a busier fallback, not an equal.
    refs = []
    try:
        vr = CS.build_vace_ref(sid)
        if vr and os.path.isfile(vr):
            refs.append(vr)
    except Exception as _exc:  # noqa: BLE001 — a missing ref is not a failed render
        _zyg_log.debug('vace ref unavailable for %s, rendering without it: %s', sid, _exc)
    for cells in (os.path.join(d, 'arcane_instantid'), os.path.join(d, 'contact_sheet', 'cells')):
        refs.extend(x for x in _images_in(cells, 'cell_', limit=4) if x not in refs)
    return {'still': still, 'binding': CS.canon_prompt_binding(sid), 'lora': lora, 'refs': refs}
