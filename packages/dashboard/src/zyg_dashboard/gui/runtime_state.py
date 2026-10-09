#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The dashboard's runtime-state seam: the job registries, the runtime directory
and the two small JSON read/write helpers.

Moved verbatim out of crewai_web_gui.py (2026-10-06 round-2 split). The job
registries themselves are owned by ``zyg_workflows.runtime`` since the 2026-10-05
layering pass — the pipelines mutate them without importing the dashboard, and
the names here are the very same dict objects. This module is the dashboard-side
import site, plus the ``_RUNTIME_DIR`` mkdir that used to sit mid-file.
"""

# ruff: noqa: F401  every name here is a re-export read off this module (and off crewai_web_gui)

import json
import os

# 2026-10-05 layering: _RUNTIME_DIR moved to zyg_workflows.pipeline_config
from zyg_workflows.pipeline_config import _RUNTIME_DIR

# The job registries are owned by zyg_workflows.runtime: the pipelines mutate them
# without importing the dashboard, and these names are the very same dict objects.
from zyg_workflows.runtime import (
    _char_gen_jobs,
    _contact_sheet_jobs,
    _creature_gen_jobs,
    _runtime_path,
    _workflow_pipeline_worker_alive,
)
from zyg_workflows.runtime import reconcile_stale_workflow_jobs as _reconcile_stale_workflow_jobs
from zyg_workflows.runtime import workflow_jobs as _workflow_jobs

from zyg_dashboard.gui.telemetry import _backend_debug


def _ensure_runtime_dir() -> str:
    """Create the dashboard's runtime directory and return it.

    Called from the first write, never at import: a module that makes a
    directory when it is merely imported breaks a bare CI runner.
    """
    os.makedirs(_RUNTIME_DIR, exist_ok=True)
    return _RUNTIME_DIR


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, data):
    try:
        _ensure_runtime_dir()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        _backend_debug(f'Dashboard save error {path}: {e}')
        return False
