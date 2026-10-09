# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""bp_benchmark — blueprint, module state and the benchmark recorders.

Moved verbatim out of bp_benchmark.py; see the package __init__ for the full rationale.
"""

# ruff: noqa: F401
# F401: this module inherits the original top import block; the siblings re-import what they use

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).
import logging as _zyg_logging
import json
import os
import re
from flask import (
    Blueprint,
    jsonify,
    request,
)
from zyg_workflows import gui_state
from zyg_workflows.bin import exe

bp = Blueprint('benchmark', __name__)
from zyg_dashboard.gui.runtime_state import _runtime_path, _workflow_jobs  # noqa: E402
from zyg_dashboard.gui.scholarly import _start_scholarly_pipeline_internal  # noqa: E402
from zyg_dashboard.gui.telemetry import _TELEMETRY_CACHE, _backend_debug  # noqa: E402
from zyg_dashboard.gui.timeutil import _ams_iso, _parse_iso_to_ams  # noqa: E402
from zyg_dashboard.crewai_web_gui import (  # noqa: E402
    _BENCHMARK_PATH,
    _BENCH_REPLAY_CACHE_PATH,
    _FLUX_PERF_TELEMETRY_PATH,
    _apply_gpu_power_limit,
    _benchmark_lock,
    _bm_infra_lock,
    _bm_mr_lock,
)

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_benchmark')


_bm_infra_runs: dict = {}


_bm_mr_sessions: dict = {}


# P-03 (2026-08-25): state-file listings newest-first by MTIME with smoke /
# gatecheck ids dropped (they used to sort to the top by filename and seed the
# replay/duration models with 3-still silent runs). Lazy import: pipeline_common
# imports THIS module at its top, so a module-level import would be circular.
def _recent_state_files(pattern, limit=0):
    from zyg_workflows.pipeline_common import recent_state_files

    return recent_state_files(pattern, limit=limit)


def _is_test_pid(pid) -> bool:
    from zyg_workflows.pipeline_common import is_test_pipeline_id

    return is_test_pipeline_id(pid)


def _bench_replay_load() -> dict:
    """Load bench_replay_cache.json into memory (once). Returns {} on any error."""
    pass  # (global stmt removed: names moved to gui_state)
    if gui_state._bench_replay_cache:
        return gui_state._bench_replay_cache
    try:
        import json as _jbr

        with open(_BENCH_REPLAY_CACHE_PATH, 'r', encoding='utf-8') as _fbr:
            gui_state._bench_replay_cache = _jbr.load(_fbr)
    except Exception:
        gui_state._bench_replay_cache = {}
    return gui_state._bench_replay_cache


def _bench_replay_get(key: str):
    """Return cached value for key, or None if replay is off or key missing."""
    if not os.environ.get('ZYG_BENCH_REPLAY', '').strip():
        return None
    return _bench_replay_load().get(key)


def _bm_record(tool: str, elapsed_s: float, count: int = 1) -> None:
    """Record a benchmark timing sample for a tool.

    tool:      e.g. 'flux_dev', 'flux_schnell', 'tts', 'claude', 'blender', 'lora'
    elapsed_s: wall-clock seconds for this run
    count:     number of units processed (images, characters, steps, etc.)
    """
    try:
        with _benchmark_lock:
            data: dict = {}
            if os.path.exists(_BENCHMARK_PATH):
                try:
                    with open(_BENCHMARK_PATH) as _bm_f:
                        data = json.load(_bm_f)
                except Exception:
                    data = {}
            entry = data.get(
                tool, {'total_elapsed': 0.0, 'total_count': 0, 'last_elapsed': 0.0, 'last_count': 0, 'last_ts': ''}
            )
            entry['total_elapsed'] = round(entry['total_elapsed'] + elapsed_s, 2)
            entry['total_count'] = entry['total_count'] + count
            entry['last_elapsed'] = round(elapsed_s, 2)
            entry['last_count'] = count
            entry['last_ts'] = _ams_iso(timespec='seconds')
            data[tool] = entry
            with open(_BENCHMARK_PATH, 'w') as _bm_w:
                json.dump(data, _bm_w, indent=2)
    except Exception as _exc:
        _zyg_log.warning('benchmark record for %s not persisted: %s', tool, _exc)


def _bm_record_pipeline(job: dict, pipeline_id: str = '') -> None:
    """Record completed pipeline run into benchmark_telemetry.json.

    Captures total wall-clock time per department and per-stage timings for
    stages not already benchmarked individually (FLUX image generation is
    already recorded per-image by _bm_record() during generation, so it is
    skipped here to avoid double-counting).

    ``pipeline_id`` (optional, 2026-08-25 P-03) falls back to job['pipeline_id'];
    smoke / gatecheck / test ids are a NO-OP — a 3-still silent run is not a
    benchmark sample.

    Safe to call from any pipeline thread — wraps everything in try/except.
    """
    try:
        _pid = str(pipeline_id or (job or {}).get('pipeline_id') or '')
        if _is_test_pid(_pid):
            _zyg_log.info(f'[BENCHMARK] test run {_pid} — not recorded')
            return
        dept = re.sub(r'[^a-z0-9]+', '_', (job.get('department') or 'unknown').lower()).strip('_')
        started = job.get('started') or ''
        ended = job.get('ended') or job.get('completed_at') or _ams_iso()

        # ── Total pipeline elapsed ────────────────────────────────────────
        total_s = None
        try:
            _s = _parse_iso_to_ams(started)
            _e = _parse_iso_to_ams(ended)
            if _s and _e:
                total_s = round((_e - _s).total_seconds(), 1)
        except Exception as _exc:
            _zyg_log.debug('pipeline start/end timestamps unparseable, total elapsed skipped: %s', _exc)

        if total_s and total_s > 0:
            _bm_record(f'pipeline_{dept}_total', total_s, count=1)

        # ── Per-stage timings ─────────────────────────────────────────────
        # Skip FLUX generation stages — already benchmarked per image during run.
        _FLUX_STAGE_KEYWORDS = ('3.5', 'image generation', 'flux', 'comfy')
        for entry in job.get('stage_timeline') or []:
            if entry.get('status') != 'completed':
                continue
            elapsed = entry.get('elapsed_s')
            if not elapsed or elapsed <= 0:
                continue
            stage_raw = (entry.get('name') or '').lower()
            if any(k in stage_raw for k in _FLUX_STAGE_KEYWORDS):
                continue
            # "Stage 2: Script Generation" → "stage_2_script_generation"
            clean = re.sub(r'[^a-z0-9]+', '_', stage_raw).strip('_')
            _bm_record(f'stage_{dept}_{clean}', elapsed, count=1)

        # ── Scholarly extras ──────────────────────────────────────────────
        if dept == 'scholarly':
            # Aggregate FLUX timing at pipeline level (cross-run analysis without
            # touching per-image records written during generation).
            flux_s = job.get('flux_gen_elapsed_s') or 0
            n_flux = job.get('flux_images') or 0
            if n_flux > 0 and flux_s > 0:
                _bm_record('pipeline_scholarly_flux_aggregate', float(flux_s), count=int(n_flux))
            tts_dur = job.get('tts_duration') or 0
            if tts_dur > 0:
                _bm_record('pipeline_scholarly_tts_output_s', float(tts_dur), count=1)

        # ── Clipfarm / crime extras ───────────────────────────────────────
        if dept in ('crime', 'clipfarm'):
            try:
                pid = job.get('pipeline_id') or ''
                state_file = _runtime_path(f'pipeline_{pid}_state.json') if pid else ''
                if state_file and os.path.exists(state_file):
                    with open(state_file) as _sf:
                        _st = json.load(_sf)
                    n_clips = len(_st.get('processed_clips') or [])
                    if n_clips > 0 and total_s:
                        _bm_record(f'pipeline_{dept}_clips', total_s, count=n_clips)
            except Exception as _exc:
                _zyg_log.debug('clip count for the %s benchmark unavailable: %s', dept, _exc)

    except Exception as _exc:
        _zyg_log.warning('pipeline benchmark recording failed for %s: %s', pipeline_id, _exc)
