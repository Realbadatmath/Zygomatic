# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""bp_market.py — Stockmarket + Cryptodaily routes, the daily scheduler and the
delivery cleaner.

Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals
exist). Lazy `from crewai_web_gui import …` inside functions only.

Threads (house pattern, bp_remix.py shape — sleep FIRST, try/except per tick):
  market-scheduler — every 60 s: if auto mode is on and the local clock has
                     passed a channel's run_at and that channel has not built
                     today, start its episode. Gated on no-other-pipeline,
                     GPU idle, free RAM, disk, and the maintenance flag. auto
                     mode ships OFF (operator decision 2026-08-06).
  market-cleaner   — every 30 min: delete delivered episodes older than the TTL
                     (default 72 h — the operator's 3-day rule).
"""

import os
import threading
import time

from flask import Blueprint, jsonify, render_template, request, send_from_directory

from zyg_workflows import briefing_jobs as BJ
from zyg_workflows import market_ingest as MI
from zyg_workflows import pipeline_market as PM
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


bp = Blueprint('market', __name__)

# Read-only probe of the restart governor's flag. The path is a cross-process contract with
# zygomatic-workflows/scripts/zygomatic-health-probe.sh (which creates the file) and with
# zyg_workflows.voice_studio; nothing here ever writes it, so it cannot be a temp-file hijack.
_MAINT_FLAG = '/var/tmp/zygomatic-maintenance.flag'  # nosec B108  # noqa: S108  shared flag the health probe owns, only read here
_SCHED_STATE = os.path.join(MI._RUNTIME, 'market_schedule_state.json')


def _flag_on(name, default='1'):
    return str(os.environ.get(name, default)).strip().lower() not in ('0', 'false', 'no', 'off')


# ── page ─────────────────────────────────────────────────────────────────────


@bp.route('/markets')
def markets_page():
    from zyg_dashboard.appcore import _ensure_csrf_token
    from flask import session

    _ensure_csrf_token()
    return render_template('market_manage.html', csrf_token=session.get('_csrf_token', ''))


# ── run / status ─────────────────────────────────────────────────────────────


@bp.route('/api/market/run', methods=['POST'])
def api_run():
    data = request.get_json(silent=True) or {}
    dept = (data.get('department') or '').strip().lower()
    if dept not in PM.CHANNELS:
        return jsonify({'error': 'department must be "stocks" or "crypto"'}), 400
    r = PM._start(dept, force=bool(data.get('force')))
    if r.get('error'):
        return jsonify(r), 409 if r['error'] == 'pipeline_busy' else 400
    return jsonify(r)


@bp.route('/api/market/status')
def api_status():
    import shutil as _sh
    from zyg_dashboard.appcore import _workflow_jobs

    active, others = [], False
    for pid, j in _workflow_jobs.items():
        if j.get('status') != 'running':
            continue
        if j.get('department') in PM.CHANNELS:
            active.append(
                {
                    'job_id': pid,
                    'department': j.get('department'),
                    'current_stage': j.get('current_stage'),
                    'progress_pct': j.get('progress_pct'),
                    'started': j.get('started'),
                }
            )
        else:
            others = True
    du = _sh.disk_usage('/')
    gates = {d: dict(zip(('ok', 'detail'), BJ.disk_ok(d))) for d in PM.CHANNELS}
    return jsonify(
        {
            'active_jobs': active,
            'other_pipeline_busy': others,
            'disk': {'free_gb': round(du.free / 1e9, 1)},
            'gates': gates,
            'schedule': MI._load(_SCHED_STATE, {}),
            'settings': MI.settings(),
            'universe_size': len(MI.universe()),
        }
    )


@bp.route('/api/market/settings', methods=['GET'])
def api_settings():
    return jsonify(MI.settings())


@bp.route('/api/market/settings', methods=['POST'])
def api_settings_post():
    return jsonify(MI.update_settings(request.get_json(silent=True) or {}))


# ── episodes ─────────────────────────────────────────────────────────────────


def _episodes(dept):
    root = BJ.out_root(dept)
    out = []
    if not os.path.isdir(root):
        return out
    for pid in sorted(os.listdir(root), reverse=True):
        d = os.path.join(root, pid)
        ep = MI._load(os.path.join(d, 'episode.json'), None)
        if not ep:
            continue
        vid = ep.get('video') or ''
        ep['file_name'] = os.path.basename(vid)
        ep['file_exists'] = bool(vid) and os.path.isfile(vid)
        try:
            age_h = (time.time() - os.path.getmtime(vid)) / 3600.0
            ep['age_hours'] = round(age_h, 1)
            ep['deletes_in_hours'] = round(max(0.0, float(ep.get('ttl_hours') or 72) - age_h), 1)
        except OSError:
            ep['age_hours'] = None
        out.append(ep)
    return out[:60]


@bp.route('/api/market/episodes')
def api_episodes():
    return jsonify({d: _episodes(d) for d in PM.CHANNELS})


@bp.route('/api/market/media/<dept>/<pid>/<path:fname>')
def api_media(dept, pid, fname):
    if dept not in PM.CHANNELS:
        return jsonify({'error': 'bad department'}), 400
    root = os.path.realpath(os.path.join(BJ.out_root(dept), pid))
    base = os.path.realpath(BJ.out_root(dept))
    if not root.startswith(base + os.sep):
        return jsonify({'error': 'bad path'}), 400
    target = os.path.realpath(os.path.join(root, fname))
    if not target.startswith(root + os.sep) or (os.sep + 'work' + os.sep) in target:
        return jsonify({'error': 'bad path'}), 400
    return send_from_directory(root, fname)


# ── ice box ──────────────────────────────────────────────────────────────────


@bp.route('/api/market/icebox')
def api_icebox():
    return jsonify({'items': MI.icebox()})


@bp.route('/api/market/icebox/used', methods=['POST'])
def api_icebox_used():
    d = request.get_json(silent=True) or {}
    return jsonify({'ok': MI.icebox_mark_used((d.get('channel') or ''), (d.get('symbol') or ''))})


@bp.route('/api/market/icebox/delete', methods=['POST'])
def api_icebox_delete():
    d = request.get_json(silent=True) or {}
    return jsonify({'ok': MI.icebox_delete((d.get('channel') or ''), (d.get('symbol') or ''))})


@bp.route('/api/market/history')
def api_history():
    return jsonify({'picks': MI.history(limit=200)})


@bp.route('/api/market/preview/<dept>')
def api_preview(dept):
    """Screen without building a video — how the operator sanity-checks a change
    to the settings before spending 20 minutes of GPU on it."""
    if dept not in PM.CHANNELS:
        return jsonify({'error': 'bad department'}), 400
    kind = PM.CHANNELS[dept]['kind']
    try:
        n = int(request.args.get('n') or 8)
    except ValueError:
        n = 8
    picks = MI.screen(kind, want=max(1, min(n, 15)))
    return jsonify({'picks': [{k: v for k, v in p.items() if k not in ('bars_tail', 'overlays')} for p in picks]})


# ── daily scheduler ──────────────────────────────────────────────────────────


def _maintenance_active() -> bool:
    try:
        return os.path.isfile(_MAINT_FLAG) and (time.time() - os.path.getmtime(_MAINT_FLAG)) < 900
    except OSError:
        return False


def _free_ram_gb() -> float:
    try:
        import psutil

        return psutil.virtual_memory().available / 1e9
    except Exception:
        return 999.0


def auto_gate(dept) -> 'tuple[bool, str]':
    s = MI.settings()
    if not s.get('auto_mode'):
        return False, 'auto mode off'
    if _maintenance_active():
        return False, 'maintenance flag set'
    if BJ.pipeline_busy():
        return False, 'another pipeline is running'
    try:
        from zyg_workflows import vram_manager

        if vram_manager._gpu_work_active():
            return False, 'GPU work active'
    except Exception as _exc:
        _zyg_log.warning('gpu activity check failed, not treating the GPU as busy: %s', _exc)
    min_ram = float(os.environ.get('ZYG_BATCH_MIN_FREE_RAM_GB', '24') or 24)
    if _free_ram_gb() < min_ram:
        return False, f'free RAM below {min_ram:.0f} GB'
    ok, why = BJ.disk_ok(dept)
    if not ok:
        return False, f'disk gate: {why}'
    return True, 'ok'


def _due(dept, now) -> bool:
    s = MI.settings()
    at = str(s.get(f'{dept}_run_at') or '').strip()
    try:
        hh, mm = [int(x) for x in at.split(':')[:2]]
    except Exception:
        return False
    st = MI._load(_SCHED_STATE, {})
    today = time.strftime('%Y-%m-%d', now)
    if (st.get(dept) or {}).get('last_run_date') == today:
        return False
    return (now.tm_hour, now.tm_min) >= (hh, mm)


def _note_run(dept, job_id):
    st = MI._load(_SCHED_STATE, {})
    st[dept] = {
        'last_run_date': time.strftime('%Y-%m-%d'),
        'last_job': job_id,
        'at': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    MI._save(_SCHED_STATE, st)


def _scheduler_tick():
    now = time.localtime()
    for dept in PM.CHANNELS:
        if not _due(dept, now):
            continue
        ok, why = auto_gate(dept)
        if not ok:
            _zyg_log.info(f'[MARKET-SCHED] {dept} is due but held: {why}')
            # Not marked as run — it retries on the next tick until the gate opens
            # or the day rolls over. A blocked GPU should delay the episode, not
            # cancel it.
            continue
        r = PM._start(dept)
        if r.get('job_id'):
            _note_run(dept, r['job_id'])
            _zyg_log.info(f'[MARKET-SCHED] started {dept} episode {r["job_id"]}')
        else:
            _zyg_log.info(f'[MARKET-SCHED] {dept} start refused: {r.get("error")}')


def _scheduler_loop():
    while True:
        time.sleep(60)
        try:
            _scheduler_tick()
        except Exception as e:
            _zyg_log.info(f'[MARKET-SCHED] tick error: {e}')


def _cleaner_loop():
    while True:
        time.sleep(1800)
        try:
            if not _maintenance_active():
                PM.retention_sweep(log=lambda m: _zyg_log.info(m))
        except Exception as e:
            _zyg_log.info(f'[MARKET-CLEANER] error: {e}')


if _flag_on('ZYG_MARKET_SCHEDULER', '1'):
    threading.Thread(target=_scheduler_loop, daemon=True, name='market-scheduler').start()
    threading.Thread(target=_cleaner_loop, daemon=True, name='market-cleaner').start()
