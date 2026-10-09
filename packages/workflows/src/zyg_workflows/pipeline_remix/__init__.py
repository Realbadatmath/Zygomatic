# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401,E402  (this file exists to re-export; the import block below
# is the original one, kept so attribute access like the old module had it works)

"""pipeline_remix.py — the Remix department (2026-08-05).

Cuts highlight clips out of watched YouTube episodes, stacks them over the
SELF-RECORDED GameSim Minecraft b-roll (horizontal split: content on top,
gameplay below), writes + speaks per-clip narration (IndexTTS-2), burns captions,
QC-gates, and delivers to data/output/remix/<pid>/. A second mode builds
long-form 16:9 compilations (8-30 min → mid-roll ads) from proven clips with a
narrated intro / transitions / outro.

Contract (pipeline_envfx_runner shape):
  * NO top-level import of crewai_web_gui — lazy accessors only.
  * Worker thread name 'remix-<pid>' is LOAD-BEARING: it is in the
    _workflow_pipeline_worker_alive needles tuple; renaming it makes kanban
    stamp running jobs 'Stale after restart'.
  * State file data/runtime/pipeline_<pid>_state.json carries department='remix'
    (restore-on-restart + the documentary auto-uploader dept-gate skip).
  * Stage names must keep the KANBAN_STAGE_MAP fragments in bp_pipeline_api.

Cutting policy (measured 2026-08-05): NEVER cut as a separate step — -ss/-to go
on the inputs of the merge command (frame-exact, no mp4 edit-list pre-roll, no
A/V desync). -ss + -stream_loop is broken (loop restarts at the keyframe before
the seek), so b-roll windows are pre-extracted to their own files.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import traceback
import uuid

from zyg_workflows import remix_ingest as RI
from zyg_workflows import paths
from zyg_workflows import provenance_seal as _seal
from zyg_workflows import runtime
from zyg_workflows.net import safe_urlopen
import logging as _zyg_logging
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)

# The sections of the original pipeline_remix.py, imported in their original order
# so module-level side effects still happen in that order, then every name the
# single-file module defined, re-exported so no importer anywhere changes.
from .constants import (
    _CREWS,
    _FONT,
    _OLLAMA,
    _OUT_ROOT,
    _RUNTIME,
    _env_f,
    _env_i,
    _jobs,
    _marker,
    _marker_update,
    _now_iso,
    _nvenc_sem,
)
from .jobs import (
    _Stopped,
    _check_stop,
    _finish,
    _log,
    _mk_job,
    _save_state,
    _stopped,
    _tree_gb,
    _update_stage,
    disk_ok,
)
from .media import (
    _SIL_RE,
    _duration,
    _enc_timeout,
    _fetch_captions,
    _ffprobe,
    _get_transcript,
    _gpu_clear,
    _punct_density,
    _rms_curve,
    _run,
    _silences,
    _whisper_transcribe,
)
from .scoring import (
    _fused_curve,
    _llm_model,
    _llm_spans,
    _norm01,
    _ollama_json,
    _ollama_release,
    _pick_windows,
    _smooth,
    _snap_window,
)
from .render import (
    _AUDIO_ARGS,
    _NORM,
    _SUB_STYLE,
    _build_narration_track,
    _build_srt,
    _encode_nvenc_first,
    _extract_broll_window,
    _fmt_srt_ts,
    _loudnorm_master,
    _narration_script,
    _pane,
    _phash_video,
    _qc_media,
    _render_title_card,
    _render_vertical_clip,
    _render_wide_segment,
    _slug,
    _tts_line,
    _vcodec_nvenc,
    _vcodec_x264,
)
from .clip_pipeline import (
    _run_remix,
    start_remix,
)
from .compilation import (
    _pick_compilation_segments,
    _run_compilation,
    retention_sweep,
    start_compilation,
)
