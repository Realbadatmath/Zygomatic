# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""bp_remix.py — Remix routes + the channel watcher and disk-cleaner daemons.

Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals
exist). Lazy `from crewai_web_gui import …` inside functions only.

Threads (house pattern, bp_zero.py:1175 shape — sleep FIRST, try/except per tick):
  remix-watcher  — polls the registered channels' RSS feeds (cache-busted UULF,
                   default every 600 s; 60 s polling buys nothing — YouTube's own
                   feed-publish lag has a measured median of 132 s), snapshots
                   viewCounts (≈1-2 % of Data API quota, search.list never used),
                   and — when auto mode is ON — starts remix jobs for top
                   candidates while the GPU is free.
  remix-cleaner  — every 30 min: deletes finished job dirs older than 72 h
                   (operator spec 2026-08-05: 3-day upload window), sweeps
                   crashed-job source/work residue. Sources are already deleted
                   at clip creation by the pipeline itself.

Narration compliance note (research 2026-08-05): NO platform or statute defines a
percentage of narration that makes reused content safe. YouTube's bar is
qualitative ("significant original commentary… meaningful difference"), and the
10 %/30-second fair-use "rules" are documented myths. The `narration_min_pct`
setting (default 12 %) is OUR engineering floor so every clip carries recurring
spoken commentary (hook + mid-clip insight(s) + outro), which is the one signal
all three platforms name first. It reduces risk; it does not guarantee outcomes.
"""

import os
import threading
import time

from flask import Blueprint, jsonify, render_template, request, send_from_directory

from zyg_workflows import pipeline_remix as PR
from zyg_workflows import remix_ingest as RI
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


bp = Blueprint('remix', __name__)

# Read-only probe of the restart governor's flag. The path is a cross-process contract with
# zygomatic-workflows/scripts/zygomatic-health-probe.sh (which creates the file) and with
# zyg_workflows.voice_studio; nothing here ever writes it, so it cannot be a temp-file hijack.
_MAINT_FLAG = '/var/tmp/zygomatic-maintenance.flag'  # nosec B108  # noqa: S108  shared flag the health probe owns, only read here
_AUTO_STATE = os.path.join(RI._RUNTIME, 'remix_auto_state.json')
_WATCH_STATE = os.path.join(RI._RUNTIME, 'remix_watcher_state.json')


def _flag_on(name, default='1'):
    return str(os.environ.get(name, default)).strip().lower() not in ('0', 'false', 'no', 'off')


# ── page ─────────────────────────────────────────────────────────────────────


@bp.route('/remix')
def remix_page():
    from zyg_dashboard.appcore import _ensure_csrf_token
    from flask import session

    _ensure_csrf_token()
    return render_template('remix_manage.html', csrf_token=session.get('_csrf_token', ''))


# ── channels ─────────────────────────────────────────────────────────────────


@bp.route('/api/remix/channels', methods=['GET'])
def api_channels():
    wm = RI.watermarks()
    out = []
    for c in RI.channels():
        rec = dict(c)
        w = wm.get(c.get('channel_id')) or {}
        rec['checked_at'] = w.get('checked_at') or ''
        rec['consecutive_errors'] = w.get('consecutive_errors') or 0
        out.append(rec)
    return jsonify({'channels': out})


@bp.route('/api/remix/channels', methods=['POST'])
def api_channels_add():
    data = request.get_json(silent=True) or {}
    r = RI.add_channel(
        (data.get('input') or '').strip(),
        clipping_permission=bool(data.get('clipping_permission', True)),
        notes=(data.get('notes') or '').strip(),
    )
    return (jsonify(r), 400) if r.get('error') else jsonify(r)


@bp.route('/api/remix/channels/<channel_id>', methods=['DELETE'])
def api_channels_del(channel_id):
    return jsonify({'removed': RI.remove_channel(channel_id)})


@bp.route('/api/remix/channels/<channel_id>/toggle', methods=['POST'])
def api_channels_toggle(channel_id):
    data = request.get_json(silent=True) or {}
    return jsonify(RI.toggle_channel(channel_id, field=(data.get('field') or 'enabled')))


# ── candidates / jobs ────────────────────────────────────────────────────────


@bp.route('/api/remix/candidates')
def api_candidates():
    return jsonify({'candidates': RI.ranked_candidates(limit=30)})


@bp.route('/api/remix/run', methods=['POST'])
def api_run():
    data = request.get_json(silent=True) or {}
    r = PR.start_remix(
        source_url=(data.get('url') or '').strip(),
        video_id=(data.get('video_id') or '').strip(),
        force=bool(data.get('force')),
    )
    return (jsonify(r), 409 if r.get('error') == 'pipeline_busy' else 400) if r.get('error') else jsonify(r)


@bp.route('/api/remix/compile', methods=['POST'])
def api_compile():
    data = request.get_json(silent=True) or {}
    r = PR.start_compilation(
        clip_ids=data.get('clip_ids') or [],
        target_minutes=data.get('minutes'),
        title=(data.get('title') or '').strip(),
        force=bool(data.get('force')),
    )
    return (jsonify(r), 409 if r.get('error') == 'pipeline_busy' else 400) if r.get('error') else jsonify(r)


# ── settings / status / library ──────────────────────────────────────────────


@bp.route('/api/remix/settings', methods=['GET'])
def api_settings():
    return jsonify(RI.settings())


@bp.route('/api/remix/settings', methods=['POST'])
def api_settings_post():
    return jsonify(RI.update_settings(request.get_json(silent=True) or {}))


@bp.route('/api/remix/status')
def api_status():
    import shutil as _sh
    from zyg_dashboard.appcore import _workflow_jobs

    active = None
    for pid, j in _workflow_jobs.items():
        if j.get('department') == 'remix' and j.get('status') == 'running':
            active = {
                'job_id': pid,
                'mode': j.get('mode'),
                'current_stage': j.get('current_stage'),
                'progress_pct': j.get('progress_pct'),
                'started': j.get('started'),
            }
            break
    busy_other = any(j.get('status') == 'running' and j.get('department') != 'remix' for j in _workflow_jobs.values())
    du = _sh.disk_usage('/')
    ws = RI._load(_WATCH_STATE, {})
    auto = RI._load(_AUTO_STATE, {})
    ok, why = PR.disk_ok()
    return jsonify(
        {
            'active_job': active,
            'other_pipeline_busy': busy_other,
            'watcher': ws,
            'auto_state': auto,
            'disk': {'free_gb': round(du.free / 1e9, 1), 'ok': ok, 'detail': why},
            'settings': RI.settings(),
        }
    )


@bp.route('/api/remix/clips')
def api_clips():
    clips = list(reversed((RI.library().get('clips') or [])[-200:]))
    for c in clips:
        c['file_exists'] = bool(c.get('file')) and os.path.isfile(c.get('file') or '')
        if c.get('file'):
            c['file_name'] = os.path.basename(c['file'])
    return jsonify({'clips': clips})


@bp.route('/api/remix/media/<pid>/<path:fname>')
def api_media(pid, fname):
    """Serve a finished deliverable. NEVER serves source/ or work/ (third-party
    episode downloads must not be listable/streamable — containment enforced)."""
    root = os.path.realpath(os.path.join(PR._OUT_ROOT, pid))
    if not root.startswith(os.path.realpath(PR._OUT_ROOT) + os.sep):
        return jsonify({'error': 'bad path'}), 400
    target = os.path.realpath(os.path.join(root, fname))
    if (
        not target.startswith(root + os.sep)
        or (os.sep + 'source' + os.sep) in target
        or (os.sep + 'work' + os.sep) in target
    ):
        return jsonify({'error': 'bad path'}), 400
    return send_from_directory(root, fname)


# ── the watcher daemon ───────────────────────────────────────────────────────


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
    if started >= int(s.get('max_auto_per_day') or 6):
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


def _watcher_tick():
    if _maintenance_active():
        return
    new_total = 0
    for c in RI.channels():
        if not c.get('enabled'):
            continue
        entries = RI.rss_poll(c['channel_id'])
        if entries is None:
            n = RI.note_poll_error(c['channel_id'])
            if n in (3, 10):
                _zyg_log.info(f'[REMIX-WATCHER] channel {c.get("name")} failing ({n} consecutive poll errors)')
            continue
        fresh = RI.note_seen(c['channel_id'], entries)
        new_total += len(fresh)
        for e in fresh:
            _zyg_log.info(f'[REMIX-WATCHER] new upload on {c.get("name")}: {e["title"][:70]}')
        time.sleep(1.0)  # stagger channels — never a burst against the origin
    RI.refresh_stats()
    RI._save(
        _WATCH_STATE,
        {
            'last_tick': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'new_videos_last_tick': new_total,
            'channels': len([c for c in RI.channels() if c.get('enabled')]),
        },
    )
    ok, why = _auto_start_ok()
    if ok:
        cands = RI.ranked_candidates(limit=1)
        if cands:
            r = PR.start_remix(video_id=cands[0]['video_id'])
            if r.get('job_id'):
                _note_auto_start()
                _zyg_log.info(f'[REMIX-WATCHER] auto-started remix {r["job_id"]} for {cands[0]["title"][:60]!r}')


def _watcher_loop():
    while True:
        time.sleep(max(60, int(RI.settings().get('poll_sec') or 600)))
        try:
            _watcher_tick()
        except Exception as e:  # one bad tick must never kill the thread
            _zyg_log.info(f'[REMIX-WATCHER] tick error: {e}')


def _cleaner_loop():
    while True:
        time.sleep(1800)
        try:
            if not _maintenance_active():
                PR.retention_sweep(log=lambda m: print(m, flush=True))
        except Exception as e:
            _zyg_log.info(f'[REMIX-CLEANER] error: {e}')


if _flag_on('ZYG_REMIX_WATCHER', '1'):
    threading.Thread(target=_watcher_loop, daemon=True, name='remix-watcher').start()
    threading.Thread(target=_cleaner_loop, daemon=True, name='remix-cleaner').start()
