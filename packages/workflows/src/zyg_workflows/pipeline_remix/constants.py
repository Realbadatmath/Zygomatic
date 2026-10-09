# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_remix.constants — paths, env helpers and the lazy runtime accessors.

Lines 53-111 of the original pipeline_remix.py, moved verbatim
(2026-10-06 split). No logic changed.
"""

from __future__ import annotations

import logging as _zyg_logging
import os

from zyg_workflows import paths
from zyg_workflows import runtime

# Bound by assignment (never `from . import`), to __package__ — which IS the
# old module's own __name__, whichever route it is imported by. The logger a
# moved line writes to must not be renamed by the move.
_zyg_log = _zyg_logging.getLogger(__package__)


# _CREWS was pipeline_remix.py's own directory — the zyg_workflows package directory.
_CREWS = str(paths.PKG_DIR)
_RUNTIME = str(paths.DATA_DIR / 'runtime')
_OUT_ROOT = str(paths.DATA_DIR / 'output' / 'remix')

_FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
_OLLAMA = os.environ.get('OLLAMA_HOST_URL', paths.ZYG_OLLAMA_URL)


def _env_f(name, default):
    try:
        return float(os.environ.get(name, str(default)) or default)
    except ValueError:
        return float(default)


def _env_i(name, default):
    try:
        return int(os.environ.get(name, str(default)) or default)
    except ValueError:
        return int(default)


# ── runtime accessors ────────────────────────────────────────────────────────
# Read through `runtime` at call time, never bound at import: the dashboard
# registers its implementations after this module is imported.


def _jobs():
    return runtime.workflow_jobs


def _now_iso():
    return runtime.ams_iso()


def _nvenc_sem():
    return runtime.NVENC_SEM


def _marker(label, pid):
    try:
        from zyg_workflows.subproc_registry import _register_marker

        return _register_marker(label, pipeline_id=pid, status='pipeline')
    except Exception:
        return None


def _marker_update(mid, status=None, label=None):
    if mid is None:
        return
    try:
        from zyg_workflows.subproc_registry import _update_marker

        _update_marker(mid, status=status, label=label)
    except Exception as _exc:
        _zyg_log.debug('subprocess marker update skipped: %s', _exc)
