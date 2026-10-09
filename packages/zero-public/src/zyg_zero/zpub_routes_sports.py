# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 by the GUI modularization (split out of zero_public_server.py).
# Source line refs: crews_modularization_backups_20260717/originals/zero_public_server.py

import json
import logging as _zyg_logging
import subprocess as _sv_sp
import threading
from datetime import datetime
from pathlib import Path as _SvPath

from flask import (
    Blueprint,
    jsonify,
    request,
)

from zyg_zero import settings

bp = Blueprint('zpub_sports', __name__)


# ── Sports-video pipeline API ─────────────────────────────────────────────────
_zyg_log = _zyg_logging.getLogger(__name__)


_SV_DIR = _SvPath(settings.ZYG_SPORTS_VIDEO_DIR)


@bp.route('/api/sports-video/status')
def sv_pipeline_status():
    sf = _SV_DIR / 'status.json'
    try:
        return jsonify(json.loads(sf.read_text()))
    except FileNotFoundError:
        return jsonify({'state': 'idle', 'step': None, 'progress': 0, 'total_rendered': 0, 'history': []})
    except Exception as _e:
        return jsonify({'state': 'error', 'last_error': str(_e)}), 500


@bp.route('/api/sports-video/tournaments')
def sv_tournaments():
    sport = request.args.get('sport', 'football')
    date = request.args.get('date', datetime.utcnow().strftime('%Y-%m-%d'))
    try:
        import sys as _svt_sys

        if str(_SV_DIR / 'scripts') not in _svt_sys.path:
            _svt_sys.path.insert(0, str(_SV_DIR / 'scripts'))
        if str(_SV_DIR) not in _svt_sys.path:
            _svt_sys.path.insert(0, str(_SV_DIR))
        from scripts.betlab_query import get_tournaments

        tours = get_tournaments(sport, date)
    except Exception as _e:
        return jsonify({'error': str(_e), 'tournaments': []}), 500
    return jsonify({'tournaments': tours})


@bp.route('/api/sports-video/trigger', methods=['POST'])
def sv_pipeline_trigger():
    import sys as _sv_sys

    body = request.get_json(silent=True) or {}
    sport = (body.get('sport') or 'football').strip()
    date = body.get('date') or datetime.utcnow().strftime('%Y-%m-%d')
    tournament = body.get('tournament') or None
    test_mode = bool(body.get('test'))

    suffix = '_test' if test_mode else ''
    data_dir = _SV_DIR / 'data'
    data_file = data_dir / f'{sport}_{date}{suffix}.json'

    # Pull fresh data from betlab.db
    try:
        if str(_SV_DIR / 'scripts') not in _sv_sys.path:
            _sv_sys.path.insert(0, str(_SV_DIR / 'scripts'))
        if str(_SV_DIR) not in _sv_sys.path:
            _sv_sys.path.insert(0, str(_SV_DIR))
        from scripts.betlab_query import write_data_json

        match_data = write_data_json(sport, date, data_file, tournament=tournament, test_mode=test_mode)
    except Exception as _bq_err:
        return jsonify({'error': f'betlab query failed: {_bq_err}'}), 500

    if not match_data.get('selections'):
        return jsonify(
            {
                'error': (
                    f"No matches found in betlab.db for sport='{sport}' "
                    f'on {date}. Check that your scraper has run for this date.'
                )
            }
        ), 404

    match_count = len(match_data['selections'])

    def _run_pipeline():
        _sv_sp.run(['python3', str(_SV_DIR / 'orchestrator.py'), '--data', str(data_file)], cwd=str(_SV_DIR))

    t = threading.Thread(target=_run_pipeline, daemon=True)
    t.start()
    return jsonify(
        {
            'ok': True,
            'sport': sport,
            'date': date,
            'test': test_mode,
            'data_file': str(data_file),
            'match_count': match_count,
        }
    )


@bp.route('/api/sports-video/videos')
def sv_pipeline_videos():
    output_dir = _SV_DIR / 'output'
    videos = []
    for mp4 in sorted(output_dir.rglob('*.mp4'), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
        try:
            sz = round(mp4.stat().st_size / 1_048_576, 1)
            run_parts = mp4.stem.split('_')
            sport_tag = run_parts[0] if run_parts else 'unknown'
            videos.append(
                {
                    'name': mp4.name,
                    'path': str(mp4),
                    'size_mb': sz,
                    'sport': sport_tag,
                    'modified': mp4.stat().st_mtime,
                }
            )
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return jsonify({'videos': videos})
