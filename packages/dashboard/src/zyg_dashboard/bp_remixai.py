# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""bp_remixai.py — Remix Ai routes + the sweeper and cleaner daemons (2026-08-29).

Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals
exist). Lazy `from crewai_web_gui import …` inside functions only.

Threads (house pattern, bp_remix.py shape — sleep FIRST, try/except per tick):
  remixai-sweeper  — runs the keyword sweep on the settings cadence (default
                     3600 s; view velocity does not move fast enough to justify
                     tighter), then auto-starts a job when auto mode is ON and
                     every gate is clear.
  remixai-cleaner  — every 30 min: retention sweep over data/output/remix_ai/.

Media route: deliverables ONLY. work/ is never listable or streamable — while a
job is mid-flight that directory holds the downloaded third-party source, and
putting it behind a LAN URL would be publishing someone else's video.
"""

import os
import threading
import time

from flask import Blueprint, jsonify, render_template, request, send_from_directory

from zyg_workflows import pipeline_remixai as PR
from zyg_workflows import remixai_ingest as RI
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


bp = Blueprint('remixai', __name__)

# Read-only probe of the restart governor's flag. The path is a cross-process contract with
# zygomatic-workflows/scripts/zygomatic-health-probe.sh (which creates the file) and with
# zyg_workflows.voice_studio; nothing here ever writes it, so it cannot be a temp-file hijack.
_MAINT_FLAG = '/var/tmp/zygomatic-maintenance.flag'  # nosec B108  # noqa: S108  shared flag the health probe owns, only read here
_AUTO_STATE = os.path.join(RI._RUNTIME, 'remixai_auto_state.json')
_SWEEP_STATE = os.path.join(RI._RUNTIME, 'remixai_sweeper_state.json')


def _flag_on(name, default='1'):
    return str(os.environ.get(name, default)).strip().lower() not in ('0', 'false', 'no', 'off')


# ── page ─────────────────────────────────────────────────────────────────────


@bp.route('/remix-ai')
def remixai_page():
    from zyg_dashboard.appcore import _ensure_csrf_token
    from flask import session

    _ensure_csrf_token()
    return render_template('remixai_manage.html', csrf_token=session.get('_csrf_token', ''))


# ── settings + search terms ─────────────────────────────────────────────────


@bp.route('/api/remixai/settings', methods=['GET'])
def api_settings():
    return jsonify(RI.settings())


@bp.route('/api/remixai/settings', methods=['POST'])
def api_settings_post():
    return jsonify(RI.save_settings(request.get_json(silent=True) or {}))


@bp.route('/api/remixai/terms', methods=['GET'])
def api_terms():
    return jsonify({'terms': RI.settings().get('terms') or []})


@bp.route('/api/remixai/terms', methods=['POST'])
def api_terms_add():
    t = ((request.get_json(silent=True) or {}).get('term') or '').strip()
    if not t:
        return jsonify({'error': 'empty term'}), 400
    s = RI.settings()
    terms = list(s.get('terms') or [])
    if t.lower() in [x.lower() for x in terms]:
        return jsonify({'error': 'term already present', 'terms': terms}), 400
    terms.append(t)
    return jsonify(RI.save_settings({'terms': terms[:40]}))


@bp.route('/api/remixai/terms', methods=['DELETE'])
def api_terms_del():
    t = ((request.get_json(silent=True) or {}).get('term') or '').strip().lower()
    s = RI.settings()
    terms = [x for x in (s.get('terms') or []) if x.lower() != t]
    return jsonify(RI.save_settings({'terms': terms}))


# ── discovery ────────────────────────────────────────────────────────────────


@bp.route('/api/remixai/sweep', methods=['POST'])
def api_sweep():
    """Run the keyword sweep now. Synchronous by design — a sweep is a handful of
    flat searches plus up to 40 metadata probes, and the operator clicked a button
    that should answer with the list it just built."""
    try:
        res = RI.sweep(log=lambda m: _zyg_log.info(f'[REMIXAI-SWEEP] {m}'))
    except Exception as e:
        return jsonify({'error': str(e)[:300]}), 500
    return jsonify(
        {
            'candidates': res.get('candidates') or [],
            'terms': res.get('terms') or {},
            'dropped': res.get('dropped') or {},
            'skipped_seen': res.get('skipped_seen') or 0,
            'ts': res.get('ts'),
        }
    )


@bp.route('/api/remixai/candidates')
def api_candidates():
    sw = RI.last_sweep()
    led = RI.seen()
    out = []
    for c in (sw.get('candidates') or [])[:30]:
        rec = dict(c)
        rec['state'] = (led.get(c['video_id']) or {}).get('state') or 'swept'
        out.append(rec)
    return jsonify({'candidates': out, 'swept_at': sw.get('ts') or 0})


# ── jobs ─────────────────────────────────────────────────────────────────────


@bp.route('/api/remixai/run', methods=['POST'])
def api_run():
    data = request.get_json(silent=True) or {}
    r = PR.start_remix_ai(
        video_id=(data.get('video_id') or '').strip(),
        directive=(data.get('directive') or '').strip(),
        force=bool(data.get('force')),
    )
    if r.get('error'):
        return jsonify(r), 409 if r['error'] == 'pipeline_busy' else 400
    return jsonify(r)


@bp.route('/api/remixai/stop', methods=['POST'])
def api_stop():
    pid = ((request.get_json(silent=True) or {}).get('pipeline_id') or '').strip()
    r = PR.stop_remix_ai(pid)
    return (jsonify(r), 400) if r.get('error') else jsonify(r)


@bp.route('/api/remixai/status')
def api_status():
    import shutil as _sh
    from zyg_dashboard.appcore import _workflow_jobs

    active = None
    for pid, j in _workflow_jobs.items():
        if j.get('department') == PR.DEPARTMENT and j.get('status') == 'running':
            active = {
                'job_id': pid,
                'pipeline_id': pid,
                'current_stage': j.get('current_stage'),
                'progress_pct': j.get('progress_pct'),
                'started': j.get('started'),
                'stage_timeline': j.get('stage_timeline') or [],
                'recent': (j.get('debug_events') or [])[-25:],
            }
            break
    busy_other = any(
        j.get('status') == 'running' and j.get('department') != PR.DEPARTMENT for j in _workflow_jobs.values()
    )
    du = _sh.disk_usage('/')
    ok, why = PR.disk_ok()
    return jsonify(
        {
            'active_job': active,
            'other_pipeline_busy': busy_other,
            'sweeper': RI._load(_SWEEP_STATE, {}),
            'auto_state': RI._load(_AUTO_STATE, {}),
            'disk': {'free_gb': round(du.free / 1e9, 1), 'ok': ok, 'detail': why},
            'settings': RI.settings(),
            'stages': PR.STAGES,
        }
    )


@bp.route('/api/remixai/library')
def api_library():
    lib = RI.library()[:200]
    for r in lib:
        r['file_exists'] = bool(r.get('path')) and os.path.isfile(r.get('path') or '')
        if r.get('path'):
            r['file_name'] = os.path.basename(r['path'])
    return jsonify({'items': lib})


@bp.route('/api/remixai/media/<pid>/<path:fname>')
def api_media(pid, fname):
    """Serve a finished deliverable. NEVER serves work/ — mid-flight that folder
    holds the downloaded third-party source."""
    root = os.path.realpath(os.path.join(PR._OUT_ROOT, pid))
    base = os.path.realpath(PR._OUT_ROOT)
    if not root.startswith(base + os.sep):
        return jsonify({'error': 'bad path'}), 400
    target = os.path.realpath(os.path.join(root, fname))
    if not target.startswith(root + os.sep) or (os.sep + 'work' + os.sep) in target:
        return jsonify({'error': 'bad path'}), 400
    if not os.path.isfile(target):
        return jsonify({'error': 'not found'}), 404
    return send_from_directory(root, fname)


# ── daemons ──────────────────────────────────────────────────────────────────


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


def _auto_start_ok() -> tuple:
    s = RI.settings()
    if not s.get('auto_mode'):
        return False, 'auto mode off'
    try:
        from zyg_dashboard.appcore import _workflow_jobs

        if any(j.get('status') == 'running' for j in _workflow_jobs.values()):
            return False, 'another pipeline is running'
    except Exception:
        return False, 'GUI registries unavailable'
    try:
        from zyg_workflows import vram_manager

        if vram_manager._gpu_work_active():
            return False, 'GPU work active'
    except Exception as _exc:
        _zyg_log.warning('gpu activity check failed, not treating the GPU as busy: %s', _exc)
    min_ram = float(os.environ.get('ZYG_BATCH_MIN_FREE_RAM_GB', '24') or 24)
    if _free_ram_gb() < min_ram:
        return False, f'free RAM below {min_ram:.0f} GB'
    auto = RI._load(_AUTO_STATE, {})
    today = time.strftime('%Y-%m-%d')
    started = int(auto.get('started') or 0) if auto.get('date') == today else 0
    if started >= int(s.get('daily_cap') or 4):
        return False, 'daily auto cap reached'
    ok, why = PR.disk_ok()
    if not ok:
        return False, f'disk gate: {why}'
    return True, 'ok'


def _note_auto_start():
    today = time.strftime('%Y-%m-%d')
    auto = RI._load(_AUTO_STATE, {})
    if auto.get('date') != today:
        auto = {'date': today, 'started': 0}
    auto['started'] = int(auto.get('started') or 0) + 1
    auto['last_start'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    RI._save(_AUTO_STATE, auto)


def _sweeper_tick():
    if _maintenance_active():
        return
    res = RI.sweep(log=lambda m: _zyg_log.info(f'[REMIXAI-SWEEPER] {m}'))
    cands = res.get('candidates') or []
    RI._save(
        _SWEEP_STATE,
        {
            'last_tick': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'candidates_found': len(cands),
            'top': (cands[0].get('title', '')[:80] if cands else ''),
            'terms': len(RI.settings().get('terms') or []),
        },
    )
    ok, why = _auto_start_ok()
    if not ok:
        return
    led = RI.seen()
    nxt = next((c for c in cands if (led.get(c['video_id']) or {}).get('state') != 'worked'), None)
    if not nxt:
        return
    r = PR.start_remix_ai(video_id=nxt['video_id'])
    if r.get('pipeline_id'):
        _note_auto_start()
        _zyg_log.info(f'[REMIXAI-SWEEPER] auto-started {r["pipeline_id"]} for {nxt.get("title", "")[:60]!r}')


def _sweeper_loop():
    while True:
        time.sleep(max(300, int(RI.settings().get('sweep_sec') or 3600)))
        try:
            _sweeper_tick()
        except Exception as e:  # one bad tick must never kill the thread
            _zyg_log.info(f'[REMIXAI-SWEEPER] tick error: {e}')


def _cleaner_loop():
    while True:
        time.sleep(1800)
        try:
            if not _maintenance_active():
                PR.retention_sweep(log=lambda m: _zyg_log.info(f'[REMIXAI-CLEANER] {m}'))
        except Exception as e:
            _zyg_log.info(f'[REMIXAI-CLEANER] error: {e}')


if _flag_on('ZYG_REMIXAI_SWEEPER', '1'):
    threading.Thread(target=_sweeper_loop, daemon=True, name='remixai-sweeper').start()
    threading.Thread(target=_cleaner_loop, daemon=True, name='remixai-cleaner').start()
