# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""vfx_analyzer.py — the VFX Library's frame-by-frame scanner.

Feed it a video (2D anime, 3D/CG, or live action). It extracts EVERY frame in
the requested window, takes ~100 deterministic readings per frame, finds the
subjects, runs every registered detector over the sequence, and writes a run log
that states — for every entry in the taxonomy — whether it was FOUND, NOT FOUND,
UNMEASURABLE, or NOT DETECTABLE.

Why four states and not two
---------------------------
"Not found" and "could not look" are different facts, and collapsing them is how
an analyzer starts lying. MediaPipe cannot see a drawn anime leg; if that came
back as "no kick detected" the log would read as evidence of absence. So:

    found          a detector ran and its evidence crossed the threshold
    not_found      a detector ran, evidence stayed BELOW threshold — the best
                   score it saw is recorded, so the threshold can be calibrated
                   against frames a human has eyeballed
    unmeasurable   the detector ran but its precondition failed (no subject
                   found, tier unavailable, stylised input) — NOT an absence
    not_detectable no detector exists for this taxonomy entry today; the entry
                   is still listed, because a known blind spot beats a silence

The cadence contract
--------------------
Animation is shot on 2s and 3s. Before any temporal metric is taken, the run
builds a cadence map from perceptual hashes and finds the UNIQUE cels; pair
metrics and velocities are only ever computed between consecutive unique cels
and divided by the REAL elapsed time. Skip this and every motion reading on an
anime clip is diluted with structural zeros.

The curiosity channel
---------------------
After detection, any region of residual (non-camera) motion that no detector
claimed is tracked, cropped, and — if a VLM is available — identified and
logged as an unknown observation. The things the taxonomy does not name are
exactly the things worth reading in the log.

Public API (the kanban server routes to these):
    library()                      -> registered media
    register_upload(tmp, name)     -> {media_id, ...}
    delete_media(media_id)
    probe(media_id)
    start_run(media_id, opts)      -> job id
    job(jid) / jobs()              -> live progress
    runs(media_id=None) / run(rid) -> finished runs
    report(rid) / frames(rid) / events(rid) / unknowns(rid) / log_text(rid)
    taxonomy() / capability()
"""

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import traceback

import numpy as np
import logging as _zyg_logging
from zyg_workflows import paths
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


# ruff: noqa: E402
# E402: library.py, scan.py and scan_stages.py do `from zyg_workflows.vfx_analyzer import
# _zyg_log`, so `_zyg_log` above must be bound before the section imports below run.
# This module also keeps the original docstring and top import block so that every old
# `vfx_analyzer.<name>` attribute access still resolves; the surface is in __all__ below.

# 2026-10-07 modularization: the 1,296-line vfx_analyzer.py became this package, cut at
# its own section banners. The submodules are imported in the single file's section
# order, so module-level side effects still happen in that order.
from zyg_workflows.vfx_analyzer.constants import (
    _HERE,
    ROOT,
    MEDIA_DIR,
    RUNS_DIR,
    TAXONOMY_PATH,
    FFMPEG,
    FFPROBE,
    OLLAMA,
    VLM_MODEL,
    VIDEO_EXT,
    MAX_WINDOW_S,
    DEFAULT_WINDOW_S,
    _ID_RE,
    _RUN_RE,
    _JOBS,
    _JOBS_LOCK,
    _JOB_KEEP,
    _TAX,
    _ensure_dirs,
    _read_json,
    _write_json,
    _safe_media_dir,
    _safe_run_dir,
    taxonomy,
)
from zyg_workflows.vfx_analyzer.capability import (
    capability,
    _free_vram_mb,
    _vlm_available,
    FULL_FRAME_ONLY,
    vlm_ask,
)
from zyg_workflows.vfx_analyzer.library import (
    _hash_file,
    register_upload,
    _probe_file,
    library,
    get_media,
    media_path,
    delete_media,
    _run_ids,
    runs,
    run,
    _jsonl,
    frames,
    events,
    unknowns,
    log_text,
    frame_image_path,
    crop_image_path,
    features,
    delete_run,
)
from zyg_workflows.vfx_analyzer.scan import (
    _job_set,
    _job_log,
    _prune_jobs,
    job,
    jobs,
    cancel,
    start_run,
    _extract,
    _worker,
    _thin_landmarks,
    _segment_shots,
    _build_ledger,
)


# The re-exported surface of the pre-split module, in import order: every name
# here exists only so that `<this module>.<name>` keeps resolving for importers.
__all__ = [
    'base64',
    'hashlib',
    'json',
    'os',
    're',
    'shutil',
    'subprocess',
    'threading',
    'time',
    'traceback',
    'np',
    'paths',
    'exe',
    '_HERE',
    'ROOT',
    'MEDIA_DIR',
    'RUNS_DIR',
    'TAXONOMY_PATH',
    'FFMPEG',
    'FFPROBE',
    'OLLAMA',
    'VLM_MODEL',
    'VIDEO_EXT',
    'MAX_WINDOW_S',
    'DEFAULT_WINDOW_S',
    '_ID_RE',
    '_RUN_RE',
    '_JOBS',
    '_JOBS_LOCK',
    '_JOB_KEEP',
    '_TAX',
    '_ensure_dirs',
    '_read_json',
    '_write_json',
    '_safe_media_dir',
    '_safe_run_dir',
    'taxonomy',
    'capability',
    '_free_vram_mb',
    '_vlm_available',
    'FULL_FRAME_ONLY',
    'vlm_ask',
    '_hash_file',
    'register_upload',
    '_probe_file',
    'library',
    'get_media',
    'media_path',
    'delete_media',
    '_run_ids',
    'runs',
    'run',
    '_jsonl',
    'frames',
    'events',
    'unknowns',
    'log_text',
    'frame_image_path',
    'crop_image_path',
    'features',
    'delete_run',
    '_job_set',
    '_job_log',
    '_prune_jobs',
    'job',
    'jobs',
    'cancel',
    'start_run',
    '_extract',
    '_worker',
    '_thin_landmarks',
    '_segment_shots',
    '_build_ledger',
]
