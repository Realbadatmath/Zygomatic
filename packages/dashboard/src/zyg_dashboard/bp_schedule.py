# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 by the GUI modularization — extracted from crewai_web_gui.py.
# Source lines: see crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md
# Contract: this module is imported at the BOTTOM of crewai_web_gui.py, after all
# of main's globals exist; `from crewai_web_gui import X` is therefore safe here.
import logging as _zyg_logging
import os
from flask import Blueprint, jsonify, request, send_from_directory

bp = Blueprint('schedule', __name__)

from zyg_dashboard.gui.runtime_state import (  # noqa: E402  (late import by design, see contract above)
    _char_gen_jobs,
    _contact_sheet_jobs,
    _creature_gen_jobs,
    _workflow_jobs,
)

_zyg_log = _zyg_logging.getLogger(__name__)


def _serve_schedule_page():
    # no-store: the page is one self-contained file that changes often; a stale
    # cached copy after a deploy left users with dead tabs (2026-07-15).
    resp = send_from_directory(
        os.path.join(os.path.dirname(__file__), 'templates'),
        'resource_schedule.html',
    )
    resp.headers['Cache-Control'] = 'no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp


@bp.route('/gpu_schedule.html')
def gpu_schedule():
    # Unified schedule page (2026-07-15 modernization); scope derived from URL.
    # Legacy templates kept on disk: gpu_schedule.html / cpu_schedule.html.
    return _serve_schedule_page()


@bp.route('/cpu_schedule.html')
def cpu_schedule():
    return _serve_schedule_page()


# ── Unified schedule API (2026-07-15) ────────────────────────────────────────
# Aggregates live pipeline runs + projected scheduled work + manual entries.
# Pipeline windows are RESERVED: manual entries overlapping them are rejected.


def _schedule_registries() -> dict:
    """Hand the in-memory job registries to schedule_service (freshest state);
    the service also sweeps data/runtime/*.json for orphans."""

    def _training_statuses():
        out = []
        try:
            from zyg_workflows import lora_trainer_service as _lts_ss

            for _cid, _j in list(_lts_ss._training_jobs.items()):
                out.append(
                    {
                        'char_id': _cid,
                        'step': getattr(_j, 'step', 0),
                        'total_steps': getattr(_j, 'total_steps', 0),
                        'done': bool(getattr(_j, 'done', False)),
                        'failed': bool(getattr(_j, 'failed', False)),
                        'model_family': getattr(_j, 'model_family', 'flux'),
                    }
                )
        except Exception as _exc:
            _zyg_log.debug('lora training job list unavailable: %s', _exc)
        return out

    return {
        'workflow_jobs': _workflow_jobs,
        'contact_sheet_jobs': _contact_sheet_jobs,
        'char_gen_jobs': _char_gen_jobs,
        'creature_jobs': _creature_gen_jobs,
        'training_status_fn': _training_statuses,
    }


def _schedule_scope() -> str:
    scope = (request.args.get('scope') or 'gpu').strip().lower()
    return scope if scope in ('gpu', 'cpu') else 'gpu'


@bp.route('/api/schedule/meta')
def api_schedule_meta():
    from zyg_dashboard import schedule_service as _ss

    return jsonify(_ss.meta_payload(_schedule_scope()))


@bp.route('/api/schedule/live')
def api_schedule_live():
    from zyg_dashboard import schedule_service as _ss

    return jsonify(_ss.live_payload(_schedule_scope(), _schedule_registries()))


@bp.route('/api/schedule/upcoming')
def api_schedule_upcoming():
    from zyg_dashboard import schedule_service as _ss

    window = (request.args.get('window') or '24h').strip().lower()
    if window not in ('24h', '7d', '28d', 'month', '1y'):
        window = '24h'
    return jsonify(
        _ss.upcoming_payload(
            _schedule_scope(),
            window,
            start_day=request.args.get('date'),
            registries=_schedule_registries(),
        )
    )


@bp.route('/api/schedule/add_entry', methods=['POST'])
def api_schedule_add_entry():
    from zyg_dashboard import schedule_service as _ss

    payload = request.get_json(silent=True) or {}
    ok, result = _ss.add_manual_entry(
        _schedule_scope(),
        payload,
        _schedule_registries(),
    )
    if not ok:
        code = 409 if result.get('conflicts') else 400
        return jsonify({'success': False, **result}), code
    return jsonify({'success': True, **result})


@bp.route('/api/schedule/delete_entry', methods=['POST'])
def api_schedule_delete_entry():
    from zyg_dashboard import schedule_service as _ss

    payload = request.get_json(silent=True) or {}
    ok, result = _ss.delete_manual_entry(
        _schedule_scope(),
        str(payload.get('id') or ''),
        str(payload.get('date') or ''),
    )
    return jsonify({'success': True, **result}) if ok else (jsonify({'success': False, **result}), 404)


@bp.route('/api/schedule/telemetry_window')
def api_schedule_telemetry_window():
    """min/avg/max RAM + VRAM over a time window, from the per-run 1s
    telemetry CSVs (data/runtime/telemetry_<pipeline>.csv)."""
    from zyg_dashboard import schedule_service as _ss

    return jsonify(
        _ss.telemetry_window_stats(
            request.args.get('from', ''),
            request.args.get('to', ''),
        )
    )
