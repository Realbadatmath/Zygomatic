# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Video Studio, assembly job and the ComfyUI render engine.

Moved verbatim (lines 5306-6302 of the old single-file module). Two things
that the old file kept under one banner and that share the graph helpers:

  * the multi-shot assembly job (_prepare_shotlist, _assemble_worker,
    start_assemble), and
  * the Wan graph itself — _NODE_DEFAULTS, _node, _augment_graph,
    _graph_overrides, _submit, _render_one and _render_worker, the thread
    start_render() spawns.
"""

# ruff: noqa: F401, E402 — this package IS the re-export surface of the old
# single file: every name it defined must stay an attribute of the same
# import path, and the submodule imports sit below the shared top block.

import json
import math
import os
import shutil
import threading
import time

from zyg_workflows import wan_video_service as _wan

from .. import HERE, _comfy, _OUT_ROOT, _zyg_log
from ..ffmpeg_finish import _audio_spec, _color_match_filter, _detect, _motion_series, _post_process
from ..options import PATHWAYS
from ..prompts import compose_link_prompts, compose_prompt
from ..render_jobs import _JOBS, _JOBS_LOCK, _job_log, _job_set, _prune_jobs, _RENDER_GATE, job
from ..spec import nondefault, sanitize

from .assembly_job import (
    _MEDIA_ROOT,
    _resolve_shot_path,
    _prepare_shotlist,
    _assemble_worker,
    start_assemble,
)

from .graph import (
    _NODE_DEFAULTS,
    _node,
    _CACHE_NODES,
    _augment_graph,
    _graph_overrides,
)

from .render import (
    _submit,
    _render_one,
    _enable_comfy,
    _render_worker,
)
