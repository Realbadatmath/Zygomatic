# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401  this module inherits the pre-split file's top import
# block verbatim; its siblings re-import from here, so nothing is unused.


import logging as _zyg_logging
import json
import os
import sys
import threading
import uuid
from flask import (
    Blueprint,
    jsonify,
    request,
    send_file,
    session,
)
from zyg_workflows import paths
from zyg_workflows.bin import exe
from zyg_dashboard import paths as dashboard_paths
from zyg_dashboard.cors import apply_cors

# root_path kept from the pre-split module: it lived directly in zyg_dashboard/,
# so Blueprint(__name__) resolved it to the package directory, not to this one.
bp = Blueprint('integrity_ops', __name__, root_path=str(dashboard_paths.PKG_DIR))
from zyg_dashboard.gui.runtime_state import _load_json, _runtime_path, _workflow_jobs  # noqa: E402
from zyg_dashboard.gui.telemetry import _read_local_telemetry  # noqa: E402
from zyg_dashboard.gui.timeutil import _ams_iso, _ams_now, _parse_iso_to_ams  # noqa: E402
from zyg_dashboard.gui.zero_store import _zero_audit_log, block_spectator_mutation  # noqa: E402
from zyg_dashboard.crewai_web_gui import (  # noqa: E402
    CANONICAL_LLMS,
    DEPENDENCIES_CONFIG,
    _HF_ENV_PATH,
    _SMOKE_SCRIPTS,
    _comfy_vram_used_mb,
    _gpu_work_active,
    _release_pipeline_vram,
    _require_csrf,
    importlib,
    limiter,
)
from zyg_dashboard import crewai_web_gui as _main_mod  # noqa: E402  late: crewai_web_gui imports this blueprint at its bottom, so `bp` must exist first
from zyg_dashboard import bp_integrity_ops_steps as _steps  # noqa: E402  same contract: needs crewai_web_gui's globals

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_integrity_ops')


# runtime-conditional names (bound in main inside try/except — tolerant binding,
# matching the original graceful-degradation semantics):
API_ADAPTER_AVAILABLE = getattr(_main_mod, 'API_ADAPTER_AVAILABLE', None)
DASHBOARD_AVAILABLE = getattr(_main_mod, 'DASHBOARD_AVAILABLE', None)
ERROR_LOGS_DATA_PATH = getattr(_main_mod, 'ERROR_LOGS_DATA_PATH', None)
LANGUAGES_DIR = getattr(_main_mod, 'LANGUAGES_DIR', None)
LANGUAGE_LINKS_FILE = getattr(_main_mod, 'LANGUAGE_LINKS_FILE', None)
_OLLAMA_BASE_URL = getattr(_main_mod, '_OLLAMA_BASE_URL', None)
get_security_controls = getattr(_main_mod, 'get_security_controls', None)
get_telemetry = getattr(_main_mod, 'get_telemetry', None)
update_security_control = getattr(_main_mod, 'update_security_control', None)


_smoke_runs: dict = {}  # run_id → {script, status, output_lines, proc, started}


# P-03 (2026-08-25): state-file listings newest-first by MTIME with smoke /
# gatecheck ids dropped. The integrity gate's "last pipeline" showed
# gatecheck-f7c09de4 (started 08-20, never ended) as RUNNING for five days
# because 'g' sorts above every hex digit. Lazy import — pipeline_common loads
# before this blueprint but after the modules it depends on.
def _recent_state_files(pattern, limit=0):
    from zyg_workflows.pipeline_common import recent_state_files

    return recent_state_files(pattern, limit=limit)


def _is_test_pid(pid) -> bool:
    from zyg_workflows.pipeline_common import is_test_pipeline_id

    return is_test_pipeline_id(pid)


# ── Smoke-run ledger persistence (P-01 latent, 2026-08-25) ───────────────────
# _smoke_runs lived only in this dict, so a GUI restart — which a smoke can
# itself cause (vram_manager kills every other crewai_web_gui.py process) —
# lost every result. Written on launch and on completion, loaded at import.
_SMOKE_RUNS_PATH = _runtime_path('smoke_runs.json')
_SMOKE_RUNS_KEEP = 50  # newest entries kept on disk
_SMOKE_RUNS_OUTPUT_TAIL = 400  # output lines kept per persisted entry
_SMOKE_RUNS_LOCK = threading.Lock()


def _smoke_runs_persist() -> None:
    try:
        with _SMOKE_RUNS_LOCK:
            runs = sorted(_smoke_runs.values(), key=lambda r: r.get('started') or '', reverse=True)[:_SMOKE_RUNS_KEEP]
            payload = {}
            for r in runs:
                e = {k: v for k, v in r.items() if k != 'proc'}
                e['output'] = list(r.get('output') or [])[-_SMOKE_RUNS_OUTPUT_TAIL:]
                payload[str(r.get('run_id'))] = e
            tmp = _SMOKE_RUNS_PATH + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump(payload, fh, indent=1, default=str)
            os.replace(tmp, _SMOKE_RUNS_PATH)
    except Exception as _spe:
        _zyg_log.info(f'[SMOKE-TEST] could not persist smoke_runs.json: {_spe}')


def _smoke_runs_load() -> None:
    try:
        if not os.path.isfile(_SMOKE_RUNS_PATH):
            return
        with open(_SMOKE_RUNS_PATH, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return
        for rid, e in data.items():
            if not isinstance(e, dict) or rid in _smoke_runs:
                continue
            e.setdefault('run_id', rid)
            e.setdefault('pipeline', '')
            e.setdefault('status', 'unknown')
            e.setdefault('output', [])
            e.setdefault('exit_code', None)
            e.setdefault('finished', None)
            e.setdefault('started', '')
            if e.get('status') == 'running':
                # Its streaming thread died with the previous GUI process, and
                # the child (same cgroup, KillMode=control-group) went with it.
                e['status'] = 'interrupted'
                e['finished'] = e.get('finished') or _ams_iso()
                e['output'].append('[runner] GUI restarted while this smoke was running — result lost')
            _smoke_runs[rid] = e
    except Exception as _sle:
        _zyg_log.info(f'[SMOKE-TEST] could not load smoke_runs.json: {_sle}')


_smoke_runs_load()
