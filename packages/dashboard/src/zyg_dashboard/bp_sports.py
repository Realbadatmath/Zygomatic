# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""bp_sports.py — TokiToki + Arena routes, the daily scheduler and the cleaner.

Contract: imported only at the BOTTOM of crewai_web_gui.py. Lazy
`from crewai_web_gui import …` inside functions only.

Threads (bp_remix.py shape — sleep FIRST, try/except per tick):
  sports-scheduler — every 60 s. When auto mode is on and a channel's run_at has
                     passed, it builds that channel's ENABLED categories one at a
                     time (never in parallel: the pipelines are mutually exclusive
                     anyway, and the Odds-API credit ledger is shared). Each
                     category is marked done for the day on its own, so a category
                     with no D+2 fixtures does not block the other four.
  sports-cleaner   — every 30 min: 72 h delivery TTL.
"""

import os
import threading
import time

from flask import Blueprint, jsonify, render_template, request, send_from_directory

from zyg_workflows import briefing_jobs as BJ
from zyg_workflows import pipeline_sports as PS
from zyg_workflows import sports_ingest as SI
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


bp = Blueprint('sports', __name__)

# Read-only probe of the restart governor's flag. The path is a cross-process contract with
# zygomatic-workflows/scripts/zygomatic-health-probe.sh (which creates the file) and with
# zyg_workflows.voice_studio; nothing here ever writes it, so it cannot be a temp-file hijack.
_MAINT_FLAG = '/var/tmp/zygomatic-maintenance.flag'  # nosec B108  # noqa: S108  shared flag the health probe owns, only read here
_SCHED_STATE = os.path.join(SI._RUNTIME, 'sports_schedule_state.json')


def _flag_on(name, default='1'):
    return str(os.environ.get(name, default)).strip().lower() not in ('0', 'false', 'no', 'off')


# ── page ─────────────────────────────────────────────────────────────────────


@bp.route('/betting')
def betting_page():
    from zyg_dashboard.appcore import _ensure_csrf_token
    from flask import session

    _ensure_csrf_token()
    return render_template('sports_manage.html', csrf_token=session.get('_csrf_token', ''))


# ── run / status ─────────────────────────────────────────────────────────────


@bp.route('/api/sports/run', methods=['POST'])
def api_run():
    data = request.get_json(silent=True) or {}
    dept = (data.get('department') or '').strip().lower()
    cat = (data.get('category') or '').strip().lower()
    r = PS.start_episode(dept, cat, force=bool(data.get('force')), pipeline_options=data.get('options') or {})
    if r.get('error'):
        return jsonify(r), 409 if r['error'] == 'pipeline_busy' else 400
    return jsonify(r)


@bp.route('/api/sports/status')
def api_status():
    import shutil as _sh
    from zyg_dashboard.appcore import _workflow_jobs

    active, others = [], False
    for pid, j in _workflow_jobs.items():
        if j.get('status') != 'running':
            continue
        if j.get('department') in PS.CHANNELS:
            active.append(
                {
                    'job_id': pid,
                    'department': j.get('department'),
                    'category': j.get('sub_channel'),
                    'current_stage': j.get('current_stage'),
                    'progress_pct': j.get('progress_pct'),
                    'started': j.get('started'),
                }
            )
        else:
            others = True
    du = _sh.disk_usage('/')
    utc_from, utc_to, day = SI.window_for()
    ok, why = SI.credits_ok()
    return jsonify(
        {
            'active_jobs': active,
            'other_pipeline_busy': others,
            'disk': {'free_gb': round(du.free / 1e9, 1)},
            'gates': {d: dict(zip(('ok', 'detail'), BJ.disk_ok(d))) for d in PS.CHANNELS},
            'target_day': day,
            'window_utc': [utc_from.isoformat(), utc_to.isoformat()],
            'credits': {'ok': ok, 'detail': why, **SI.quota()},
            'schedule': SI._load(_SCHED_STATE, {}),
            'settings': SI.settings(),
            'categories': {k: v['label'] for k, v in SI.CATEGORIES.items()},
        }
    )


@bp.route('/api/sports/settings', methods=['GET'])
def api_settings():
    return jsonify(SI.settings())


@bp.route('/api/sports/settings', methods=['POST'])
def api_settings_post():
    return jsonify(SI.update_settings(request.get_json(silent=True) or {}))


@bp.route('/api/sports/fixtures/<category>')
def api_fixtures(category):
    """The free half of the research: what is even on in the D+2 window.

    Uses only /events (0 credits) so the operator can check the schedule as often
    as they like without touching the monthly ledger.
    """
    if category not in SI.CATEGORIES:
        return jsonify({'error': 'unknown category'}), 400
    evs = SI.fetch_events(category)
    _f, _t, day = SI.window_for()
    return jsonify(
        {
            'day': day,
            'count': len(evs),
            'keys': sorted({e['sport_key'] for e in evs}),
            'fixtures': [
                {
                    'home': e.get('home_team'),
                    'away': e.get('away_team'),
                    'at': e.get('commence_time'),
                    'league': e.get('sport_title') or e['sport_key'],
                }
                for e in evs[:80]
            ],
        }
    )


@bp.route('/api/sports/preview/<department>/<category>')
def api_preview(department, category):
    """Full research (COSTS ODDS CREDITS) without building a video."""
    if department not in PS.CHANNELS or category not in SI.CATEGORIES:
        return jsonify({'error': 'unknown department/category'}), 400
    res = SI.research(category, want=12)
    for b in res.get('bets') or []:
        b['kickoff_local'] = PS._kickoff_local(b)
    return jsonify(res)


# ── episodes ─────────────────────────────────────────────────────────────────


def _episodes(dept):
    root = BJ.out_root(dept)
    out = []
    if not os.path.isdir(root):
        return out
    for cat in sorted(os.listdir(root)):
        cdir = os.path.join(root, cat)
        if not os.path.isdir(cdir):
            continue
        for pid in sorted(os.listdir(cdir), reverse=True):
            ep = SI._load(os.path.join(cdir, pid, 'episode.json'), None)
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
    return sorted(out, key=lambda e: e.get('built_at', ''), reverse=True)[:80]


@bp.route('/api/sports/episodes')
def api_episodes():
    return jsonify({d: _episodes(d) for d in PS.CHANNELS})


@bp.route('/api/sports/media/<dept>/<cat>/<pid>/<path:fname>')
def api_media(dept, cat, pid, fname):
    if dept not in PS.CHANNELS or cat not in SI.CATEGORIES:
        return jsonify({'error': 'bad department/category'}), 400
    root = os.path.realpath(os.path.join(BJ.out_root(dept, cat), pid))
    base = os.path.realpath(BJ.out_root(dept, cat))
    if not root.startswith(base + os.sep):
        return jsonify({'error': 'bad path'}), 400
    target = os.path.realpath(os.path.join(root, fname))
    if not target.startswith(root + os.sep) or (os.sep + 'work' + os.sep) in target:
        return jsonify({'error': 'bad path'}), 400
    return send_from_directory(root, fname)


# ── ice box ──────────────────────────────────────────────────────────────────


@bp.route('/api/sports/icebox')
def api_icebox():
    return jsonify({'items': SI.icebox()})


@bp.route('/api/sports/icebox/used', methods=['POST'])
def api_icebox_used():
    d = request.get_json(silent=True) or {}
    return jsonify({'ok': SI.icebox_mark_used((d.get('channel') or ''), (d.get('event_id') or ''))})


@bp.route('/api/sports/icebox/delete', methods=['POST'])
def api_icebox_delete():
    d = request.get_json(silent=True) or {}
    return jsonify({'ok': SI.icebox_delete((d.get('channel') or ''), (d.get('event_id') or ''))})


@bp.route('/api/sports/history')
def api_history():
    return jsonify({'bets': SI.history(limit=200)})


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
    s = SI.settings()
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
    ok, why = SI.credits_ok()
    if not ok:
        return False, f'odds api: {why}'
    return True, 'ok'


def _due(dept, now) -> bool:
    at = str(SI.settings().get(f'{dept}_run_at') or '').strip()
    try:
        hh, mm = [int(x) for x in at.split(':')[:2]]
    except Exception:
        return False
    return (now.tm_hour, now.tm_min) >= (hh, mm)


def _pending_categories(dept) -> list:
    s = SI.settings()
    enabled = [c for c in (s.get('categories_enabled') or []) if c in SI.CATEGORIES]
    st = SI._load(_SCHED_STATE, {})
    today = time.strftime('%Y-%m-%d')
    done = (st.get(dept) or {}).get(today) or {}
    return [c for c in enabled if c not in done]


def _note_run(dept, category, job_id, note=''):
    st = SI._load(_SCHED_STATE, {})
    today = time.strftime('%Y-%m-%d')
    d = st.setdefault(dept, {})
    # keep only the last 5 days so the file cannot grow without bound
    for k in [k for k in d if k < today][:-4]:
        d.pop(k, None)
    d.setdefault(today, {})[category] = {'job': job_id, 'note': note, 'at': time.strftime('%H:%M:%S')}
    SI._save(_SCHED_STATE, st)


def _scheduler_tick():
    now = time.localtime()
    for dept in PS.CHANNELS:
        if not _due(dept, now):
            continue
        pending = _pending_categories(dept)
        if not pending:
            continue
        ok, why = auto_gate(dept)
        if not ok:
            _zyg_log.info(f'[SPORTS-SCHED] {dept} is due but held: {why}')
            return  # one message per tick, not one per category
        cat = pending[0]
        r = PS.start_episode(dept, cat)
        if r.get('job_id'):
            _note_run(dept, cat, r['job_id'])
            _zyg_log.info(f'[SPORTS-SCHED] started {dept}/{cat} episode {r["job_id"]}')
        elif r.get('error') == 'pipeline_busy':
            return  # try again next tick; do NOT mark the day done
        else:
            # A genuine refusal (no fixtures, filters emptied the card) is a
            # finished answer for today — mark it so the scheduler stops retrying
            # a category that simply is not playing.
            _note_run(dept, cat, '', note=str(r.get('error'))[:200])
            _zyg_log.info(f'[SPORTS-SCHED] {dept}/{cat} skipped: {r.get("error")}')
        return  # one episode per tick — they are mutually exclusive


def _scheduler_loop():
    while True:
        time.sleep(60)
        try:
            _scheduler_tick()
        except Exception as e:
            _zyg_log.info(f'[SPORTS-SCHED] tick error: {e}')


def _cleaner_loop():
    while True:
        time.sleep(1800)
        try:
            if not _maintenance_active():
                PS.retention_sweep(log=lambda m: _zyg_log.info(m))
                SI.sweep_odds_cache()
        except Exception as e:
            _zyg_log.info(f'[SPORTS-CLEANER] error: {e}')


if _flag_on('ZYG_SPORTS_SCHEDULER', '1'):
    threading.Thread(target=_scheduler_loop, daemon=True, name='sports-scheduler').start()
    threading.Thread(target=_cleaner_loop, daemon=True, name='sports-cleaner').start()
