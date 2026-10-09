# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The measurement collectors of _compute_metrics_dashboard().

Each function below is one of the former bp_metrics.py's banner-delimited blocks,
lifted out of the 947-line _compute_metrics_dashboard() at its original four-space
indent so the moved code is byte-for-byte what it was; the parameters and the
returned tuples are exactly that block's inbound and outbound locals.
"""

import json
import os

from zyg_workflows import gui_state

from zyg_dashboard.bp_metrics import _recent_state_files, _zyg_log
from zyg_dashboard.bp_metrics.aggregate import _metrics_normalize_stage
from zyg_dashboard.crewai_web_gui import _METRICS_PIPELINE_LABELS
from zyg_dashboard.gui.runtime_state import _runtime_path
from zyg_dashboard.gui.timeutil import _parse_iso_to_ams


def _collect_pipeline_state(runtime_dir):
    # ── Pipeline state stats ──────────────────────────────────────────────────
    state_files = _recent_state_files(os.path.join(runtime_dir, 'pipeline_*_state.json'))
    total_runs = len(state_files)
    completed_runs = 0
    durations: list[float] = []
    jobs_by_date: dict[str, int] = {}
    stage_totals: dict[str, list[float]] = {}
    pipelines_by_dept: dict[str, dict] = {}
    recent_story_runs: list[dict] = []

    for sf in state_files:
        try:
            with open(sf) as _f:
                ps = json.load(_f)
            dept = (ps.get('department') or 'unknown').strip().lower() or 'unknown'
            pb = pipelines_by_dept.setdefault(
                dept,
                {
                    'id': dept,
                    'label': _METRICS_PIPELINE_LABELS.get(dept, dept.replace('_', ' ').title()),
                    'total': 0,
                    'completed': 0,
                    'failed': 0,
                    'running': 0,
                    'durations': [],
                    'stages': {},
                },
            )
            pb['total'] += 1
            _pstatus = (ps.get('status') or '').lower()
            if _pstatus == 'failed' or _pstatus == 'error':
                pb['failed'] += 1
            elif _pstatus == 'running':
                pb['running'] += 1
            date = (ps.get('started') or '')[:10]
            if date:
                jobs_by_date[date] = jobs_by_date.get(date, 0) + 1
            _dur_s = None
            if ps.get('started') and ps.get('ended'):
                completed_runs += 1
                pb['completed'] += 1
                try:
                    _s = _parse_iso_to_ams(ps['started'])
                    _e = _parse_iso_to_ams(ps['ended'])
                    if _s and _e:
                        _dur_s = (_e - _s).total_seconds()
                        durations.append(_dur_s)
                        pb['durations'].append(_dur_s)
                except Exception as _exc:
                    _zyg_log.debug('run start/end timestamps unparseable, duration skipped: %s', _exc)
            recent_story_runs.append(
                {
                    'id': (ps.get('pipeline_id') or '')[:12],
                    'type': dept,
                    'label': _METRICS_PIPELINE_LABELS.get(dept, dept),
                    'status': _pstatus or 'unknown',
                    'started': ps.get('started') or '',
                    'duration_s': _dur_s,
                    'topic': (ps.get('scholarly_topic') or ps.get('topic') or '')[:48],
                }
            )
            for st in ps.get('stage_timeline') or []:
                sname = _metrics_normalize_stage(st.get('name', ''))
                elapsed = st.get('elapsed_s')
                if elapsed is not None:
                    stage_totals.setdefault(sname, []).append(float(elapsed))
                    pb['stages'].setdefault(sname, []).append(float(elapsed))
        except Exception as _exc:
            _zyg_log.debug('skipping pipeline state that could not be aggregated: %s', _exc)
    recent_story_runs.sort(key=lambda x: x.get('started') or '', reverse=True)
    recent_story_runs = recent_story_runs[:10]

    avg_duration_s = round(sum(durations) / len(durations)) if durations else 0
    avg_jobs_per_day = round(sum(jobs_by_date.values()) / max(len(jobs_by_date), 1), 1) if jobs_by_date else 0
    success_rate = round(completed_runs / total_runs * 100, 1) if total_runs else 0

    return (
        avg_duration_s,
        avg_jobs_per_day,
        completed_runs,
        pipelines_by_dept,
        recent_story_runs,
        stage_totals,
        success_rate,
        total_runs,
    )


def _collect_flux_perf():
    # ── FLUX perf telemetry ───────────────────────────────────────────────────
    flux_s_per_image = 0.0
    try:
        _fp = _runtime_path('flux_perf_telemetry.json')
        if os.path.exists(_fp):
            with open(_fp) as _f:
                flux_s_per_image = float(json.load(_f).get('estimate_s_per_image', 0))
    except Exception as _exc:
        _zyg_log.debug('flux perf telemetry unavailable: %s', _exc)

    return flux_s_per_image


def _collect_token_cost():
    # ── Token / API cost stats ────────────────────────────────────────────────
    _MODEL_PRICING = {
        'claude-sonnet-4-6': (3.0, 15.0),
        'claude-sonnet-4-5': (3.0, 15.0),
        'claude-haiku': (0.25, 1.25),
        'claude-haiku-4-5': (0.25, 1.25),
        'gpt-4o': (5.0, 15.0),
        'gpt-4o-mini': (0.15, 0.60),
    }
    tok_entries: list[dict] = []
    try:
        _tp = _runtime_path('token_usage.json')
        if os.path.exists(_tp):
            with open(_tp) as _f:
                tok_entries = json.load(_f)
    except Exception as _exc:
        _zyg_log.warning('token usage log unreadable, api cost stats stay zero: %s', _exc)

    total_cost = 0.0
    cost_by_model: dict[str, float] = {}
    calls_by_model: dict[str, int] = {}
    tokens_by_model: dict[str, int] = {}
    cost_by_pipeline: dict[str, float] = {}
    cost_by_pipeline_type: dict[str, float] = {}
    calls_by_pipeline_type: dict[str, int] = {}
    for e in tok_entries:
        m = e.get('model', 'unknown')
        pt_type = (e.get('pipeline_type') or 'unknown').strip().lower() or 'unknown'
        prompt_t = int(e.get('prompt_tokens', 0))
        ct = int(e.get('completion_tokens', 0))
        pricing = next((v for k, v in _MODEL_PRICING.items() if m.lower().startswith(k)), None)
        cost = (prompt_t * pricing[0] + ct * pricing[1]) / 1_000_000 if pricing else 0.0
        total_cost += cost
        cost_by_model[m] = cost_by_model.get(m, 0.0) + cost
        calls_by_model[m] = calls_by_model.get(m, 0) + 1
        tokens_by_model[m] = tokens_by_model.get(m, 0) + prompt_t + ct
        cost_by_pipeline_type[pt_type] = cost_by_pipeline_type.get(pt_type, 0.0) + cost
        calls_by_pipeline_type[pt_type] = calls_by_pipeline_type.get(pt_type, 0) + 1
        pid = e.get('pipeline_id', '') or e.get('vid_id', '')
        if pid:
            cost_by_pipeline[pid] = cost_by_pipeline.get(pid, 0.0) + cost

    pipeline_costs = [v for v in cost_by_pipeline.values() if v > 0]
    avg_cost_per_run = sum(pipeline_costs) / len(pipeline_costs) if pipeline_costs else 0.0

    return (
        avg_cost_per_run,
        calls_by_model,
        calls_by_pipeline_type,
        cost_by_model,
        cost_by_pipeline_type,
        pipeline_costs,
        tok_entries,
        tokens_by_model,
        total_cost,
    )


def _collect_wattage(runtime_dir, avg_duration_s, _fmt_s):
    # ── Wattage: read gpu_power_w from telemetry CSVs during FLUX Stage 4 ─────
    # New CSVs (after this code change) include gpu_power_w from nvmlDeviceGetPowerUsage.
    # For old CSVs without the column, fall back to TDP × utilisation% estimate.
    GPU_TDP_W = gui_state._CALIBRATION.get('max_gpu_watts', 450)
    _watt_run_samples: list[float] = []  # avg watts per FLUX run
    _runs_with_real_power = 0  # runs using nvml gpu_power_w column

    try:
        import csv as _csv_watt_mod

        for _sf in _recent_state_files(os.path.join(runtime_dir, 'pipeline_*_state.json')):
            try:
                with open(_sf) as _f:
                    _ps_w = json.load(_f)
                _pid_w = _ps_w.get('pipeline_id', '')
                _csv_p = os.path.join(runtime_dir, f'telemetry_{_pid_w}.csv')
                if not os.path.exists(_csv_p):
                    continue
                _s4_start_w = _s4_end_w = None
                for _st in _ps_w.get('stage_timeline') or []:
                    if 'Stage 4' in _st.get('name', '') and 'WAN' not in _st.get('name', ''):
                        _s4_start_w = _st.get('started_at')
                        _s4_end_w = _st.get('ended_at')
                if not _s4_start_w or not _s4_end_w:
                    continue
                _ts_s4_start = _parse_iso_to_ams(_s4_start_w)
                _ts_s4_end = _parse_iso_to_ams(_s4_end_w)
                if not _ts_s4_start or not _ts_s4_end:
                    continue
                with open(_csv_p) as _cf_w:
                    _s4_rows = list(_csv_watt_mod.DictReader(_cf_w))
                _run_watts: list[float] = []
                _run_has_real_power = False
                for _row_w in _s4_rows:
                    try:
                        _ts_w = _parse_iso_to_ams(_row_w.get('timestamp', ''))
                        if _ts_w is None or not (_ts_s4_start <= _ts_w <= _ts_s4_end):
                            continue
                        _pw = _row_w.get('gpu_power_w', '')
                        if _pw:
                            _run_watts.append(float(_pw))
                            _run_has_real_power = True
                        else:
                            _util_pct = float(_row_w.get('gpu_util_pct') or 0)
                            _run_watts.append(GPU_TDP_W * _util_pct / 100)
                    except Exception as _exc:
                        _zyg_log.debug('skipping telemetry row with unusable power numbers: %s', _exc)
                if len(_run_watts) >= 10:
                    _watt_run_samples.append(sum(_run_watts) / len(_run_watts))
                    if _run_has_real_power:
                        _runs_with_real_power += 1
            except Exception as _exc:
                _zyg_log.debug('skipping run whose power telemetry could not be read: %s', _exc)
    except Exception as _exc:
        _zyg_log.warning('gpu power telemetry scan failed, watt estimates stay unset: %s', _exc)

    if _watt_run_samples:
        _avg_w_during_flux = sum(_watt_run_samples) / len(_watt_run_samples)
        watt_hours_per_run = round(_avg_w_during_flux * (avg_duration_s or 0) / 3600, 1)
        _watt_value = f'{watt_hours_per_run} Wh'
        if _runs_with_real_power > 0:
            _watt_desc = (
                f'Avg {_avg_w_during_flux:.0f}W GPU draw during FLUX (pynvml measured, '
                f'{_runs_with_real_power} runs) × {_fmt_s(avg_duration_s)} avg run duration'
            )
        else:
            _watt_desc = (
                f'Avg {_avg_w_during_flux:.0f}W GPU draw during FLUX '
                f'(TDP×util% from {len(_watt_run_samples)} runs) × {_fmt_s(avg_duration_s)} avg run. '
                f'Future runs will use pynvml real watts.'
            )
    else:
        watt_hours_per_run = round(GPU_TDP_W * (avg_duration_s or 0) / 3600, 1)
        _watt_value = f'~{watt_hours_per_run} Wh'
        _watt_desc = (
            f'RTX 4090 {GPU_TDP_W}W TDP × avg {_fmt_s(avg_duration_s)} per run '
            f'(no telemetry data yet — will measure on next run)'
        )

    return _watt_value, _watt_desc


def _collect_vram(runtime_dir):
    # ── GPU VRAM stats — measured from real telemetry CSVs during FLUX Stage 4 ─
    _vram_peaks_mb: list[float] = []
    _vram_avgs_mb: list[float] = []
    _vram_total_mb_observed = 0.0
    try:
        import csv as _csv_mod

        for _sf in _recent_state_files(os.path.join(runtime_dir, 'pipeline_*_state.json')):
            try:
                with open(_sf) as _f:
                    _ps = json.load(_f)
                _pid = _ps.get('pipeline_id', '')
                _csv_path = os.path.join(runtime_dir, f'telemetry_{_pid}.csv')
                if not os.path.exists(_csv_path):
                    continue
                # Find Stage 4 (FLUX) time window
                _s4_start = _s4_end = None
                for _st in _ps.get('stage_timeline') or []:
                    if 'Stage 4' in _st.get('name', '') and 'WAN' not in _st.get('name', ''):
                        _s4_start = _st.get('started_at')
                        _s4_end = _st.get('ended_at')
                if not _s4_start:
                    continue
                _ts_start = _parse_iso_to_ams(_s4_start)
                _ts_end = _parse_iso_to_ams(_s4_end) if _s4_end else None
                if not _ts_start:
                    continue
                with open(_csv_path) as _cf:
                    _rows = list(_csv_mod.DictReader(_cf))
                _s4_vram: list[float] = []
                for _row in _rows:
                    try:
                        _ts = _parse_iso_to_ams(_row.get('timestamp', ''))
                        if _ts is None:
                            continue
                        _vm = float(_row.get('gpu_mem_used_mb') or 0)
                        if _vm == 0:
                            continue
                        _vt = float(_row.get('gpu_mem_total_mb') or 0)
                        if _vt > _vram_total_mb_observed:
                            _vram_total_mb_observed = _vt
                        if _ts_end and _ts_start <= _ts <= _ts_end:
                            _s4_vram.append(_vm)
                    except Exception as _exc:
                        _zyg_log.debug('skipping telemetry row with unusable vram numbers: %s', _exc)
                if len(_s4_vram) >= 20:  # only count runs with meaningful data
                    _vram_peaks_mb.append(max(_s4_vram))
                    _vram_avgs_mb.append(sum(_s4_vram) / len(_s4_vram))
            except Exception as _exc:
                _zyg_log.debug('skipping run whose vram telemetry could not be read: %s', _exc)
    except Exception as _exc:
        _zyg_log.warning('gpu vram telemetry scan failed, vram estimates stay unset: %s', _exc)

    _flux_peak_avg_gb = round(sum(_vram_peaks_mb) / len(_vram_peaks_mb) / 1024, 1) if _vram_peaks_mb else None
    _flux_peak_max_gb = round(max(_vram_peaks_mb) / 1024, 1) if _vram_peaks_mb else None
    _flux_avg_gb = round(sum(_vram_avgs_mb) / len(_vram_avgs_mb) / 1024, 1) if _vram_avgs_mb else None
    _vram_total_gb = round(_vram_total_mb_observed / 1024, 1) if _vram_total_mb_observed else None
    _flux_runs_counted = len(_vram_peaks_mb)

    # Build GPU memory card values from real measurements
    if _flux_peak_avg_gb and _vram_total_gb:
        _gpu_mem_value = f'{_flux_avg_gb} GB avg / {_flux_peak_avg_gb} GB peak'
        _gpu_mem_desc = (
            f'Measured across {_flux_runs_counted} FLUX generation runs on {_vram_total_gb} GB GPU. '
            f'Max peak observed: {_flux_peak_max_gb} GB. '
            f'int8-quanto quantisation keeps model below GPU capacity.'
        )
    else:
        _gpu_mem_value = '—'
        _gpu_mem_desc = 'No telemetry data yet — run a pipeline to measure VRAM usage.'

    return _gpu_mem_value, _gpu_mem_desc
