# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""run_logbook.py — per-run append-only logbook, config/metric diff, resumable checkpoints.

2026-08-01. Born from the scene20 v11→v12 incident, which cost a full deliverable and
most of a day for reasons that were ORGANISATIONAL, not technical:

  * the v12 driver was copied from v11.  Its OUT directory was changed, its output
    FILENAME constant was not.  v12 therefore wrote FINAL_scene20_v11.mp4 into
    scene20_v12/, and the operator compared two files both believing they were v11.
    Nothing in the pipeline objected, because nothing was checking that version,
    directory and filename agree.  gate_version_consistency() now does, at config
    time, before the 90 minutes are spent.
  * once the run finished, answering "what actually changed between v11 and v12?"
    meant re-reading the driver, the service, and four JSON blobs by hand.  The real
    answer was ONE environment variable (ZYG_VACE_DIFFDIFF 0 → 1) and it took a day
    to state with confidence.  compare_runs() states it in one command, with the
    metric movement printed next to it.
  * a crash or an abort after the render meant re-rendering the render.  90 minutes
    of GPU to recover a 40-second composite step.  record_checkpoint()/resume_from()
    make the last good artifact addressable.

Design rules, all consequences of the above:

  ONE KEY, ONE RUN.  Everything (jsonl name, LOGBOOK.md location, index row,
  checkpoint manifest) hangs off a single run_key.  Derive the version, the
  directory and the output filename from it and the v12 class of bug is unwritable.

  APPEND-ONLY.  data/runtime/logbook/<run_key>.jsonl is only ever appended to; the
  human-readable <run_dir>/LOGBOOK.md is a rendering of it and may be rebuilt at any
  time.  A torn last line is skipped on read, never repaired in place.

  ATOMIC.  Every whole-file write is tmp + fsync + os.replace, with a .bak of the
  previous version kept, so a crash mid-write leaves the old file intact and a
  corrupt manifest still has two fallbacks (the .bak, then the jsonl itself).

  FAIL-SAFE.  A broken logbook must NEVER break a render.  Every recording call
  returns a bool/dict and swallows its own exceptions through log_fn.  Only the CLI
  read paths (compare/list/show) surface errors.

  NO SQLITE HERE.  run_ledger.py owns the cross-run sqlite ledger (gate pass-rate
  drift, silent degrades).  This module owns the per-run narrative and the two-run
  diff, and mirrors into run_ledger where the two overlap.  Retro-ingest does NOT
  mirror — backdated rows stamped with today's ts would poison trends() z-scores.

API:
    start_run(run_dir, version=..., driver_file=..., run_id=...)   -> run handle dict
    record_config(run, env=..., render_kwargs=..., beats=..., beat_map=...,
                  mask_path=..., ref_images=..., loras=..., final_name=...)
    record_stage(run, stage, wall_s=..., vram_mb=..., status=...)
    record_metrics(run, metrics, source=...)
    record_gates(run, gates, verdict=...)
    record_checkpoint(run_dir, stage, artifact_path, meta=...)
    resume_from(run_dir)                     -> last COMPLETED stage + its artifact
    finish_run(run, ok=..., final_path=...)
    compare_runs(run_a, run_b)               -> config delta + metric delta
    format_compare(cmp)                      -> two-column markdown table
    list_runs()                              -> newest-first index
    ingest_run_dir(run_dir, ...)             -> retro-populate from a finished run

CLI:
    python3 run_logbook.py list
    python3 run_logbook.py compare <runA> <runB>
    python3 run_logbook.py show <run>
    python3 run_logbook.py resume <run_dir>
    python3 run_logbook.py ingest <run_dir> [--version vNN] [--driver path]
"""

# ruff: noqa: E402, F401
# Pattern A package: run_logbook.py was split at its own section banners into plumbing.py, recording.py, reading.py, compare.py, report.py.
# The import path is unchanged, the original top import block is re-done below so
# attribute access on the module keeps working, the submodules are imported in the
# original section order, and every public and underscore name is re-exported.

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import logging as _zyg_logging

from zyg_workflows.run_logbook.plumbing import (
    BEAT_CHAR_LIMIT,
    CHECKPOINT_NAME,
    CHECKPOINT_SCHEMA,
    INDEX_PATH,
    KNOWN_ZYG_KEYS,
    LOGBOOK_DIR,
    LOGBOOK_NAME,
    SCHEMA,
    _CREWS,
    _RUNTIME,
    _append_jsonl,
    _atomic_write,
    _file_facts,
    _handle,
    _log_noop,
    _now,
    _read_json,
    _read_jsonl,
    _safe_key,
    _sha256,
    _zyg_log,
    jsonl_path,
    resolve_run,
)
from zyg_workflows.run_logbook.recording import (
    _beat_records,
    _config_gates,
    _emit,
    finish_run,
    gate_version_consistency,
    mask_stats,
    record_config,
    record_gates,
    record_metrics,
    record_stage,
    snapshot_env,
    start_run,
)
from zyg_workflows.run_logbook.reading import (
    _load_checkpoints,
    checkpoint_path,
    list_runs,
    load_run,
    record_checkpoint,
    resume_from,
)
from zyg_workflows.run_logbook.compare import (
    _CONFIG_SKIP_SUFFIX,
    _METRIC_TIERS,
    _cell,
    _config_flat,
    _fnum,
    _metric_tier,
    _run_meta,
    compare_runs,
    flatten,
    format_compare,
)
from zyg_workflows.run_logbook.report import (
    _ingest_metrics,
    _main,
    format_list,
    ingest_run_dir,
    write_logbook_md,
)

import sys as _sys
from types import ModuleType as _ModuleType

_SECTIONS = tuple(_sys.modules[__name__ + '.' + _n] for _n in ('plumbing', 'recording', 'reading', 'compare', 'report'))


class _SplitModule(_ModuleType):
    """Keep `setattr(run_logbook, name, value)` behaving as it did on the single module.

    Live code patches a name on this module and restores it afterwards (geom/
    relief_subdiv's mirror_map_override is one such patch), and the moved code resolves
    those names through its own section's globals — so a write here has to reach every
    section that holds the name, exactly as rebinding one module global used to.
    """

    def __setattr__(self, name, value):
        _ModuleType.__setattr__(self, name, value)
        for _m in self.__dict__.get('_SECTIONS') or ():
            if name in _m.__dict__:
                _ModuleType.__setattr__(_m, name, value)

    def __delattr__(self, name):
        _ModuleType.__delattr__(self, name)
        for _m in self.__dict__.get('_SECTIONS') or ():
            if name in _m.__dict__:
                _ModuleType.__delattr__(_m, name)


# Must be the last statement: from here on, every attribute write fans out.
_sys.modules[__name__].__class__ = _SplitModule
