# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Metrics blueprint HTTP routes — verbatim sections of the former bp_metrics.py."""

import json
import os

from flask import jsonify, request

from zyg_dashboard import paths as _dash_paths
from zyg_dashboard.bp_metrics import _zyg_log, bp
from zyg_dashboard.bp_metrics.dashboard import _compute_metrics_dashboard
from zyg_dashboard.crewai_web_gui import limiter
from zyg_dashboard.gui.controller import controller
from zyg_dashboard.gui.runtime_state import _workflow_jobs
from zyg_dashboard.gui.telemetry import _read_local_telemetry


@bp.route('/api/metrics/character-quality')
def api_character_quality_metrics():
    """Per-run character quality trend (2026-07-18).

    Reads data/runtime/character_quality_metrics.jsonl (one row per completed
    contact-sheet run — see contact_sheet_pipeline._append_quality_metrics) and
    returns the newest rows plus aggregate alerts, so quality regressions are a
    dashboard call instead of an archaeology dig.
    Query: ?limit=N (default 30, max 200).
    """
    path = str(_dash_paths.DATA_DIR / 'runtime' / 'character_quality_metrics.jsonl')
    try:
        limit = max(1, min(200, int(request.args.get('limit', 30))))
    except (TypeError, ValueError):
        limit = 30
    rows: list[dict] = []
    try:
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError as _exc:
                    _zyg_log.debug('skipping unparseable metrics alert row: %s', _exc)
                    continue
    except OSError as _exc:
        _zyg_log.warning('metrics alert log unreadable, no alerts are shown: %s', _exc)
    rows = rows[-limit:]
    alerts = []
    for r in rows:
        if r.get('qc_ran') is False:
            alerts.append({'char_id': r.get('char_id'), 'alert': 'qc_skipped', 'ts': r.get('ts')})
        if (r.get('valve_verdict') or '') in ('fail', 'error'):
            alerts.append({'char_id': r.get('char_id'), 'alert': f'valve_{r["valve_verdict"]}', 'ts': r.get('ts')})
        _dd = r.get('anchor_dedup_max_sim')
        if isinstance(_dd, (int, float)) and _dd > 0.45:
            alerts.append({'char_id': r.get('char_id'), 'alert': f'dedup_sim_{_dd}', 'ts': r.get('ts')})
    _scores = [r.get('qc_mean_score') for r in rows if isinstance(r.get('qc_mean_score'), (int, float))]
    return jsonify(
        {
            'runs': rows,
            'count': len(rows),
            'alerts': alerts,
            'aggregate': {
                'mean_qc_score': round(sum(_scores) / len(_scores), 4) if _scores else None,
                'runs_with_alerts': len({a['char_id'] for a in alerts}),
            },
        }
    )


_METRICS_HUB = {'mod': None, 'mtime': 0.0}


def _metrics_hub_module():
    """metrics_hub, re-imported when its file changes — collector fixes go live without a GUI
    restart (a restart kills running pipelines and crewai-gui allows 3 starts per 15 min)."""
    from zyg_workflows.devreload import maybe_reload

    mod = _METRICS_HUB['mod']
    if mod is None:
        from zyg_dashboard import metrics_hub as mod
    try:
        mtime = os.path.getmtime(mod.__file__)
        if _METRICS_HUB['mod'] is not None and mtime != _METRICS_HUB['mtime']:
            mod = maybe_reload(mod)
        _METRICS_HUB.update(mod=mod, mtime=mtime)
    except Exception as exc:
        _zyg_log.info(f'[METRICS-HUB] reload failed, keeping loaded module: {exc}')
    return mod


@bp.route('/api/metrics/hub/<section>')
@limiter.exempt
def api_metrics_hub(section):
    """Metrics tab v4 (2026-09-11): one section of the hub — overview, pipelines, characters,
    llm, quality, system, agents. ?days=N (0 = all time, default 30), ?fresh=1 skips the
    short server memo. Status rules, test-row exclusion and coverage notes live in
    metrics_hub.py and ship in the payload."""
    try:
        days = max(0, min(3650, int(request.args.get('days', 30))))
    except (TypeError, ValueError):
        days = 30
    fresh = request.args.get('fresh') in ('1', 'true')
    mh = _metrics_hub_module()
    if section not in mh.SECTIONS:
        return jsonify({'success': False, 'message': f'unknown metrics section {section!r}'}), 404
    telemetry = _read_local_telemetry() if section in ('overview', 'system') else None
    try:
        data = mh.section(section, days=days, telemetry=telemetry, fresh=fresh)
    except Exception as exc:
        import traceback

        traceback.print_exc()
        return jsonify({'success': False, 'message': f'metrics_hub.{section} failed: {type(exc).__name__}: {exc}'}), 500
    resp = jsonify(data)
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@bp.route('/api/metrics/analytics/config', methods=['GET', 'POST'])
@limiter.exempt
def api_metrics_analytics_config():
    """Metrics > Analytics assumptions (views per content, RPM, kWh price, active hours).
    GET returns them; POST {key: value} merges and returns the result. Stored in
    data/runtime/analytics_config.json and shipped inside every analytics payload."""
    mh = _metrics_hub_module()
    mod = mh._analytics_mod()
    if request.method == 'POST':
        body = request.get_json(silent=True) or {}
        try:
            cfg = mod.save_config(body)
        except Exception as exc:
            return jsonify({'success': False, 'message': f'{type(exc).__name__}: {exc}'}), 400
        return jsonify({'success': True, 'config': cfg})
    return jsonify({'success': True, 'config': mod.load_config()})


@bp.route('/api/metrics/summary')
@limiter.exempt
def get_metrics_summary():
    """Return a lightweight summary of system metrics for dashboard widgets."""
    total_agents = len(controller.agent_configs)
    active_jobs = sum(1 for j in _workflow_jobs.values() if j.get('status') == 'running')
    completed_jobs = sum(1 for j in _workflow_jobs.values() if j.get('status') == 'completed')
    failed_jobs = sum(1 for j in _workflow_jobs.values() if j.get('status') == 'failed')
    telemetry = _read_local_telemetry()
    return jsonify(
        {
            'total_agents': total_agents,
            'active_jobs': active_jobs,
            'completed_jobs': completed_jobs,
            'failed_jobs': failed_jobs,
            # 2026-09-11: the sampler's keys are cpu_pct_raw / ram_pct / gpus — the old
            # 'cpu' / 'ram' / 'gpu' lookups never matched, so these always read 0 / [].
            'cpu_percent': telemetry.get('cpu_pct_raw', 0),
            'ram_percent': telemetry.get('ram_pct', 0),
            'gpu_percent': [g.get('utilization_pct') for g in (telemetry.get('gpus') or [])],
        }
    )


@bp.route('/api/metrics/all')
def get_metrics_all():
    """Return aggregated metrics — delegates to /api/metrics/dashboard for real data."""
    data = _compute_metrics_dashboard()
    # Flatten all categories into a simple list for backward-compat consumers
    flat = []
    for cat in data.get('categories', []):
        for item in cat.get('items', []):
            flat.append(
                {
                    'name': item.get('label', ''),
                    'value': item.get('value', '—'),
                    'category': cat.get('name', ''),
                    'description': item.get('description', ''),
                }
            )
    return jsonify(flat)


@bp.route('/api/metrics/dashboard')
@limiter.exempt
def get_metrics_dashboard():
    """Return all dashboard metrics grouped by category — Performance, Infrastructure, Cost, Workflow, Hardware."""
    return jsonify(_compute_metrics_dashboard())
