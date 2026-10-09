#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401
"""VFX Studio effect stack — the toolbox that MODIFIES a library asset.

The Studio could browse the effects library and measure a clip; it could not
change one.  This module is the missing half: an ordered stack of operations
applied to a plate, a sprite or a rendered volume element, previewed a frame at
a time and baked into a new library row.

THREE THINGS LIVE IN ONE PLACE ON PURPOSE.  Every operation declares, in the
same record: its parameter schema, its icon, and the ffmpeg fragment it
compiles to.  The Architecture Studio keeps its icons in the page and its
behaviour in the page too, so the pair cannot drift.  Here the behaviour is
server-side (ffmpeg) and the picture is client-side, and a registry split
across two files is a registry that goes out of step the first time someone
adds an op to one of them.  So the page renders the rail FROM this registry --
`/inspect/api/vfx/fx/ops` -- and holds no op list of its own.

WHY FFMPEG AND NOT A SHADER.  A browser filter is a preview, not a deliverable:
it cannot write a ProRes 4444 master, it cannot hold 16-bit, and it cannot be
re-run headlessly over a 1531-second plate.  ffmpeg 6.1 carries 562 filters,
which is most of a compositor's second row, and the same graph that renders the
preview frame renders the bake -- so what you approve is what you get.  The
compiled graph is readable at /inspect/api/vfx/fx/chain: a receipt, not a
claim ([[feedback_measure_before_claim]]).

ALPHA IS THE WHOLE POINT and it is the easiest thing to lose.  The chain runs
in RGBA from head to tail, every intermediate is `format=rgba`, and the writers
pin the only two containers that carry a matte -- VP9 `yuva420p` in WebM and
ProRes 4444 in MOV.  h264 has no alpha channel at all; offering it for an
element would hand back a black box that looks like a successful render
([[project_vfx_volume_elements]]).

PARAMETERS ARE VALIDATED, NOT TRUSTED.  A filter argument is not a shell
argument -- everything here runs through subprocess lists -- but `lut3d` takes
a FILE, `geq` takes an expression, and a filtergraph is a parser.  So every
value is coerced to its declared type, clamped to its declared range, enums must
be members, colours must match #rrggbb, and file parameters resolve inside one
whitelisted directory or fail.  An out-of-schema key is dropped, never passed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import logging as _zyg_logging

from zyg_workflows.vfx_fx.constants import (
    _zyg_log,
    HERE,
    DATA,
    LIBS,
    RUNTIME,
    PRESETS,
    LUTDIR,
    JOBLOG,
    FFMPEG,
    FFPROBE,
    DERIVED_PACK,
)
from zyg_workflows.vfx_fx import registry
from zyg_workflows.vfx_fx.registry import (
    f,
    i,
    b,
    e,
    c,
    s,
    OPS,
    _SEEN,
    _op,
    hexc,
    _n,
    _q,
)
from zyg_workflows.vfx_fx import transform
from zyg_workflows.vfx_fx.transform import (
    _fx_move,
    _fx_scale2d,
    _fx_rot,
    _fx_tile,
)
from zyg_workflows.vfx_fx import colour
from zyg_workflows.vfx_fx.colour import (
    _fx_curves,
    _fx_lut3d,
)
from zyg_workflows.vfx_fx import matte
from zyg_workflows.vfx_fx.matte import (
    _alpha_op,
)
from zyg_workflows.vfx_fx import blur
from zyg_workflows.vfx_fx import light
from zyg_workflows.vfx_fx.light import (
    _bright_pass,
    _fx_glow,
    _fx_streak,
    _fx_halation,
    _fx_lightwrap,
    _fx_flicker,
)
from zyg_workflows.vfx_fx import time_ops
from zyg_workflows.vfx_fx import distort
from zyg_workflows.vfx_fx.distort import (
    _fx_turb,
    _fx_ripple,
    _fx_kaleido,
)
from zyg_workflows.vfx_fx import dock
from zyg_workflows.vfx_fx.dock import (
    _act,
)
from zyg_workflows.vfx_fx import repair
from zyg_workflows.vfx_fx import chain
from zyg_workflows.vfx_fx.chain import (
    OP_BY_ID,
    validate,
    normalise_stack,
    _LBL,
    compile_chain,
    _PROBE_CACHE,
    probe,
    _libpath,
    source_ctx,
    VIEWS,
    SCOPES,
    PREVIEW_MAX,
    build_graph,
    preview_cmd,
    preview_frame,
    chain_text,
)
from zyg_workflows.vfx_fx import render
from zyg_workflows.vfx_fx.render import (
    FORMATS,
    JOBS,
    _JOBS_LOCK,
    _slug,
    _quality_args,
    start_render,
    _render_worker,
    _register,
    job_status,
    recent_jobs,
)
from zyg_workflows.vfx_fx import presets
from zyg_workflows.vfx_fx.presets import (
    BUILTIN_PRESETS,
    load_presets,
    save_preset,
    delete_preset,
    ops_payload,
)
