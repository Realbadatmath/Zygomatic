#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401
"""Picture Studio toolbox — the half that MODIFIES a picture in the library.

Picture Studio used to be a gallery: a rail of character names on the left, a
grid of thumbnails on the right, and three edit tools (upscale / inpaint /
remove-background) hung off the lightbox.  You could LOOK at every picture the
pipeline had made and do three things to one.  This module is the missing half
— the same shape Creature Studio settled on ([[creature_fx]]), pointed at
BOTH libraries instead of one:

  * inject a subject from the CHARACTER library or the CREATURE library,
  * pick one of its images onto a preview stage,
  * build an ordered STACK of operations over it, and
  * bake the result beside the subject, never over the source.

THREE THINGS LIVE IN ONE RECORD, the ruling creature_fx.py and vfx_fx.py both
settled on: every op declares its parameter schema, its icon and what it
compiles to.  The page renders all three bars FROM this registry
(`/inspect/api/picture/fx/ops`) and holds no tool list of its own, so adding an
op here is the whole job.

FOUR CLASSES OF OP, AND THE PAGE SAYS WHICH.  The distinction is the one thing
that would otherwise mislead, so it is marked in the tooltip, in the icon pip
and in the banner over the picture:

  cls 'pix'   Pillow.  Instant, exact, and the preview IS the result.
  cls 'svc'   a model that is not a diffusion edit — ESRGAN upscale, u2net
              matting, a mask repair.  Deterministic in intent but it needs
              seconds-to-minutes and a GPU, so it cannot be previewed: it runs
              in the render job and the banner says it is not in the picture.
  cls 'edit'  a Qwen-Image-Edit clause.  Minutes on the 4090, and no preview
              can show it without running it.
  cls 'act'   a bar button: no stack row, an action.

THE SOURCE IS NEVER WRITTEN TO.  Bakes land in `<subject>/picture_studio/`,
a directory of its own, with a JSON sidecar each carrying the whole recipe —
source, stack, instruction, seeds, measurements, inherited licence — because a
bake you cannot reproduce is a bake you do not have.

LICENCE IS INHERITED, NEVER RE-ASSERTED.  A creature's licence verdict comes
from creature_fx.licence_of() verbatim; a FLUX.1-dev subject's generative
renders are refused outright, exactly as they are there, because the channel is
monetised ([[project_licence_gate]]).  Deterministic pixel ops on what is
already on disk still run: they mint no new model output.

SCOPE IS RE-VALIDATED HERE.  Characters carry the medusa/default origin split
that kanban_server._serve_image enforces, and this module writes as well as
reads, so it keeps its own copy of that check rather than trusting the caller —
the same fail-closed duplication bp_picture_studio.py and bp_medusa.py already
establish across a process boundary.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
import uuid

from zyg_workflows import creature_fx as cfx
from zyg_workflows import paths
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

from zyg_workflows.picture_fx.constants import (  # noqa: E402
    BAKE_DIR,
    CHAR_CATS,
    CHAR_ID_RE,
    CHARS_ROOT,
    DATA,
    HERE,
    IMG_EXT,
    JOBDIR,
    LIBS,
    NAME_RE,
    PRESETS,
    PREVIEW_MAX,
    RUNTIME,
)
from zyg_workflows.picture_fx.subject import (  # noqa: E402
    bake_dir,
    cat_dir,
    cat_label,
    _char_dir,
    _char_licence,
    _char_name,
    check_scope,
    _family_evidence,
    _FAMILY_TOKEN,
    images,
    is_medusa,
    licence_of,
    _listdir_images,
    _medusa_id_set,
    _MEDUSA_IDS,
    resolve,
    subject_dir,
)
from zyg_workflows.picture_fx.pixel_tone import (  # noqa: E402
    b,
    c,
    e,
    f,
    _filt,
    i,
    _keep_alpha,
    _lut,
    _pil,
    _px_auto,
    _px_balance,
    _px_bleach,
    _px_bloom,
    _px_border,
    _px_cartoon,
    _px_chanswap,
    _px_chroma,
    _px_clarity,
    _px_cross,
    _px_curve,
    _px_dither,
    _px_duotone,
    _px_equalize,
    _px_faded,
    _px_halation,
    _px_highlights,
    _px_invert,
    _px_motion,
    _px_pixelate,
    _px_round,
    _px_scanlines,
    _px_sepia,
    _px_shadows,
    _px_sketch,
    _px_solarize,
    _px_splittone,
    _px_threshold,
    _px_tiltshift,
    _px_vibrance,
    _rgb,
    _rgba,
    s,
    _tone_lut,
)
from zyg_workflows.picture_fx.pixel_frame import (  # noqa: E402
    _aspect_of,
    _px_alpha_choke,
    _px_alpha_feather,
    _px_alpha_invert,
    _px_aspect,
    _px_dropshadow,
    _px_extend,
    _px_glow,
    _px_ground_grad,
    _px_letterbox,
    _px_longedge,
    _px_mirror_half,
    _px_outline,
    _px_straighten,
)
from zyg_workflows.picture_fx.registry import (  # noqa: E402
    _act,
    _amt,
    _ASPECTS,
    colour_word,
    _edit,
    _op,
    OPS,
    _pick,
    _pix,
    _SEEN,
    _svc,
)
from zyg_workflows.picture_fx import ops_frame_light as _ops_frame_light  # noqa: E402
from zyg_workflows.picture_fx import ops_colour_detail as _ops_colour_detail  # noqa: E402
from zyg_workflows.picture_fx import ops_grade_matte as _ops_grade_matte  # noqa: E402
from zyg_workflows.picture_fx import ops_retouch_subject as _ops_retouch_subject  # noqa: E402
from zyg_workflows.picture_fx.ops_scene_style import (  # noqa: E402
    _style,
)
from zyg_workflows.picture_fx.ops_dock import (  # noqa: E402
    OP_BY_ID,
)
from zyg_workflows.picture_fx.engine import (  # noqa: E402
    apply_pixels,
    chain_text,
    _checkerboard,
    _comp_public,
    compile_stack,
    _ctx,
    delete_bake,
    facts,
    _KEEP_DROPS,
    keep_sentence,
    list_bakes,
    _NEG_BASE,
    normalise_stack,
    _open,
    _png,
    preview_frame,
    read_recipe,
    _slug,
    validate,
    _write_bake,
)
from zyg_workflows.picture_fx.render import (  # noqa: E402
    apply_action,
    delete_preset,
    _JOB_KEEP,
    job_status,
    _JOBLOCK,
    JOBS,
    load_presets,
    _log,
    _measure_pair,
    ops_payload,
    _phash,
    _PRESET_LOCK,
    _prune_jobs,
    recent_jobs,
    _render_worker,
    _run_edit,
    _run_masked_repair,
    _run_service,
    save_preset,
    _set,
    _sha,
    start_render,
    _tmpdir,
)
