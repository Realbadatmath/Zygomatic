# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""bp_kidseries.py — launch + status routes for the ten children's series.

Why a dedicated blueprint rather than reusing /api/internal/pipeline/start: the
Kids Series menu lives in the :8899 inspection page, which is a different origin
with no dashboard session, and the internal-API bypass in `require_login` is
keyed on ZERO_PUBLIC_TOKEN — which is not set on this box (both .env files are
empty), so that hop currently 503s.  These routes are therefore LOCALHOST-ONLY,
the same shape bp_kidsmusic.py already uses: the kanban server is same-host, an
external caller still gets 401.

GENERIC BY CONSTRUCTION.  Nothing here names a series.  Every route resolves
through kids_series_common.discover(), which re-globs pipeline_kids_*.py on
every call, so a new runner appears on the board without an edit to this file
and without a restart.

Additive.  Registers only /api/internal/kidseries/*.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


bp = Blueprint('kidseries', __name__)


def _local_only():
    return request.remote_addr in ('127.0.0.1', '::1')


def _series_row(slug, mod):
    """One series as the menu wants it: its SERIES dict plus its STAGES.

    Defensive about every field: a runner still being written must not 500 the
    list route for the other nine.
    """
    meta = dict(getattr(mod, 'SERIES', {}) or {})
    meta['slug'] = meta.get('slug') or slug
    meta['stages'] = list(getattr(mod, 'STAGES', []) or [])
    return meta


@bp.route('/api/internal/kidseries/list', methods=['GET'])
def ks_list():
    """Every series that honours the contract, and what could not be loaded.

    Read-only, so it is not localhost-gated — the same rule bp_kidsmusic gives
    its status route.
    """
    try:
        from zyg_workflows import kids_series_common as _ks
    except Exception as e:  # noqa: BLE001
        return jsonify(
            {'series': [], 'errors': [{'file': 'kids_series_common.py', 'error': f'{type(e).__name__}: {e}'[:300]}]}
        )
    try:
        found = _ks.discover()
    except Exception as e:  # noqa: BLE001
        return jsonify({'series': [], 'errors': [{'file': 'discover()', 'error': f'{type(e).__name__}: {e}'[:300]}]})
    rows = [_series_row(slug, mod) for slug, mod in sorted(found.items())]
    return jsonify({'series': rows, 'errors': _ks.discover_errors()})


@bp.route('/api/internal/kidseries/start', methods=['POST'])
def ks_start():
    if not _local_only():
        return jsonify({'error': 'localhost only'}), 401
    data = request.get_json(silent=True) or {}
    slug = str(data.get('series') or data.get('slug') or '').strip()
    if not slug:
        return jsonify({'error': 'a series slug is required'}), 400

    from zyg_workflows import kids_series_common as _ks

    known = _ks.discover()
    if slug not in known:
        return jsonify(
            {'error': f'unknown kids series {slug}', 'known': sorted(known), 'discover_errors': _ks.discover_errors()}
        ), 400

    # One pipeline at a time, same rule the main dispatcher enforces — two
    # episodes would fight over ComfyUI's single submit lock and over the 20 GB
    # IndexTTS-2 needs.
    try:
        from zyg_dashboard.appcore import _workflow_jobs

        running = [pid for pid, j in _workflow_jobs.items() if j.get('status') == 'running']
        if running:
            return jsonify({'error': 'pipeline_busy', 'running_id': running[0]}), 409
    except Exception as _exc:  # noqa: BLE001 — never block on the check
        _zyg_log.warning('busy check failed, starting the episode anyway: %s', _exc)

    info = _ks.start_series(
        slug,
        episode=data.get('episode'),
        pipeline_options=data.get('pipeline_options'),
        test_mode=bool(data.get('test_mode')),
    )
    if info.get('error'):
        return jsonify(info), 400
    try:
        from zyg_dashboard.appcore import _zero_audit_log

        _zero_audit_log(
            'kidseries_start', {'series': slug, 'episode': info.get('episode'), 'test_mode': info.get('test_mode')}
        )
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('kidseries start audit entry could not be written: %s', _exc)
    return jsonify(info)


@bp.route('/api/internal/kidseries/status', methods=['GET'])
def ks_status():
    """Live view of the current/last children's-series jobs, for the menu's
    progress strip.  Read-only, so it is not localhost-gated."""
    try:
        from zyg_dashboard.appcore import _workflow_jobs
    except Exception:  # noqa: BLE001
        return jsonify({'jobs': []})
    try:
        from zyg_workflows import kids_series_common as _ks

        _found = _ks.discover()
    except Exception:  # noqa: BLE001 — status must not 500
        _found = {}
    out = []
    for pid, j in _workflow_jobs.items():
        dept = str(j.get('department') or '')
        if not dept.startswith('kids_'):
            continue
        _mod = _found.get(dept[5:])
        out.append(
            {
                'job_id': pid,
                'status': j.get('status'),
                'department': dept,
                'slug': dept[5:],
                'stage': j.get('current_stage'),
                'started': j.get('started'),
                'error': (j.get('error') or '')[:400],
                'series': j.get('kids_series') or {},
                # debug_events are dicts (the kanban_status contract) — flatten to
                # display lines here so the menu does not have to know the shape.
                'log': [
                    f'{e.get("ts", "")} {e.get("msg", "")}' if isinstance(e, dict) else str(e)
                    for e in (j.get('debug_events') or [])[-60:]
                ],
                'timeline': [
                    {
                        'name': e.get('name'),
                        'status': e.get('status'),
                        'started_at': e.get('started_at'),
                        'ended_at': e.get('ended_at'),
                    }
                    for e in (j.get('stage_timeline') or [])
                ],
                # Per job, from its own module: the board's columns for this series.
                'stages': list(getattr(_mod, 'STAGES', []) or []) if _mod else [],
            }
        )
    out.sort(key=lambda r: r.get('started') or '', reverse=True)
    return jsonify({'jobs': out[:8]})


@bp.route('/api/internal/kidseries/stop', methods=['POST'])
def ks_stop():
    if not _local_only():
        return jsonify({'error': 'localhost only'}), 401
    jid = str((request.get_json(silent=True) or {}).get('job_id') or '')
    try:
        from zyg_dashboard.appcore import _workflow_jobs

        j = _workflow_jobs.get(jid)
        if not j or not str(j.get('department') or '').startswith('kids_'):
            return jsonify({'error': 'unknown job'}), 404
        ev = j.get('stop_event')
        if ev is not None:
            ev.set()
        return jsonify(
            {
                'ok': True,
                'job_id': jid,
                'note': 'halt requested — the run stops before the next GPU stage; CPU stages already in flight finish',
            }
        )
    except Exception as e:  # noqa: BLE001
        return jsonify({'error': f'{type(e).__name__}: {e}'[:200]}), 500
