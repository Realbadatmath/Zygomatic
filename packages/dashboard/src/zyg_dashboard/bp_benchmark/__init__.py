# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: E402, F401
# Pattern A package: bp_benchmark.py was cut at its own section banners into the modules below.
# The original top import block is re-done here so old attribute access (bp_benchmark.os, ...)
# still resolves, the submodules are imported in the original section order, and every
# name the single module defined is re-exported.

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

from zyg_dashboard.bp_benchmark.state import (
    bp,
    _zyg_log,
    _bm_infra_runs,
    _bm_mr_sessions,
    _recent_state_files,
    _is_test_pid,
    _bench_replay_load,
    _bench_replay_get,
    _bm_record,
    _bm_record_pipeline,
)
from zyg_dashboard.bp_benchmark.routes_frequency import (
    api_frequency_data,
    api_frequency_history,
    api_frequency_history_run,
    api_calibrate_get,
    api_calibrate_post,
    api_benchmark_pipeline_history,
    api_benchmark_seeds,
    api_benchmark_run_infra,
    api_benchmark_status,
)
from zyg_dashboard.bp_benchmark.infra_worker import (
    _bm_infra_worker,
)
from zyg_dashboard.bp_benchmark.multirun import (
    _bm_mr_sample,
    _bm_multirun_worker,
    api_benchmark_multirun_start,
    api_benchmark_multirun_status,
    api_benchmark_system,
    api_benchmark,
)
