# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""expansion_hub.py — the Metrics > Expansion collector (:5000/metrics, subtab Expansion).
2026-10-04.

What this tab answers: how big is the program ITSELF — the structural material that runs
the whole thing — counted file by file. Folders, files per kind and per extension, bytes
and lines for every script / page / stylesheet / config, Python structure (modules,
functions, classes, routes, tests, entry points), the systemd units that run each
component, plus the two kinds of non-code material the models are driven with:

  * prompts — prompt files, agent persona configs, ComfyUI workflow graphs, VLM judge
    checklists, character briefs, the prompt registry, AND prompt literals found inside
    the Python code (AST, not grep);
  * training data — the LoRA datasets and the TTS voice seeds that generation is
    conditioned on, counted per dataset (images, captions, audio, manifests).

Everything the program PRODUCES is excluded: output folders, runtime state, logs,
rendered media, mesh/sound/VFX libraries, weights, caches, venvs, node_modules,
backups, worktree and archive copies, third-party engines. Every pruned directory is
listed in the payload with the rule that pruned it, so an exclusion is a visible claim,
never a silent one ([[feedback_measure_before_claim]]).

How the tree is found
---------------------
The primary component is the tree this file lives in (``ZYG_LEGACY_ROOT``). The
other components are read off the systemd units (user + system): every unit whose
WorkingDirectory / ExecStart points under the operator's home and is not a known
third-party engine (ComfyUI, Applio, Postgres, venvs) is a component —
so a new service appears here the day its unit is written, with no edit to this file.
Loose launcher scripts named in ExecStart (``~/kanban_server_start.sh`` …) are counted
in a "launchers" component of their own.

Line counts are cached per file by (mtime_ns, size) in
``data/runtime/expansion_cache.json``; a scan re-reads only changed files. The CLI
``python3 expansion_hub.py [--fresh] [--json]`` prints the summary (or the full payload).
"""

# ruff: noqa: F401,E402

# ── expansion_hub.py became expansion_hub/ ───────────────────────────────────
# Pattern A: the import path `zyg_dashboard.expansion_hub` is unchanged and every name the
# single file defined — public and underscore — is re-exported below from the module that
# now holds it. The submodules are imported in the original section order, so module-level
# work (the classification tables, the compiled regexes) still runs in that order.

import ast
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import time
import warnings
import logging as _zyg_logging

from zyg_workflows.bin import exe

# An importlib reload of expansion_hub (metrics_hub.dispatch's hot-reload, armed only by
# ZYG_DEV_RELOAD=1) re-executes only this __init__.py; the submodules would come back from
# sys.modules unchanged and edited collector code would be silently ignored. Dropping them
# first makes the reload reload the whole thing, exactly as it did when expansion_hub was
# one file.
_stale = [_m for _m in list(sys.modules) if _m.startswith(__name__ + '.')]
while _stale:
    del sys.modules[_stale.pop()]
del _stale

from .constants import (  # noqa: F401
    _zyg_log,
    HERE,
    ROOT,
    HOME,
    CREWS_DATA,
    CACHE_PATH,
    TRAINING_ROOTS,
    EXTRA_FILES,
    CODE_EXT,
    CONFIG_EXT,
    DOCS_EXT,
    TABLE_EXT,
    ASSET_EXT,
    ASSET_DIRS,
    NOLINE_EXT,
    SKIP_EXT,
    _SKIP_BY_EXT,
    HARD_PRUNE,
    OUTPUT_PRUNE,
    CONTENT_PRUNE,
    DATA_PRUNE,
    CREWS_DATA_KEEP,
    THIRD_PARTY_ROOTS,
    PROMPT_NAME,
    _PROMPT_DIRS,
    ROUTE_RE,
    DEF_RE,
    CLASS_RE,
    MAIN_RE,
    JS_FN_RE,
    SCAN_TTL_S,
    _LAST,
)
from .helpers import (  # noqa: F401
    _iso,
    _ext,
    RUNTIME_FILE,
    _is_backup_name,
    _kind_of,
    KIND_LABEL,
    KIND_ORDER,
    _unit_files,
    _parse_unit,
    _exec_paths,
    _unit_states,
    _third_party,
    discover_components,
    _prune_reason,
)
from .reading import (  # noqa: F401
    _load_cache,
    _save_cache,
    _string_like,
    _str_len,
    _collect_strings,
    _prompt_literals,
    _prompt_units,
    _read_file,
    _walk_component,
    _add_file,
    _walk_training,
)
from .aggregation import (  # noqa: F401
    _agg,
    _folder_rows,
    _version,
    build,
    section_expansion,
)
