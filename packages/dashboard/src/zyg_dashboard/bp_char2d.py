# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""bp_char2d.py — launch route for the '2D Character Basics I' workflow.

Why a dedicated blueprint rather than reusing /api/internal/pipeline/start
directly: the Run button lives in the :8899 inspection/kanban page, which is a
different origin with no dashboard session, and the internal-API bypass in
`require_login` is keyed on ZERO_PUBLIC_TOKEN — which is not set on this box.
These routes are therefore LOCALHOST-ONLY, the same shape bp_kidsmusic uses:
the kanban server is same-host, an external caller still gets 401.

The route carries NO policy of its own. It normalises the body and calls
`bp_pipeline_api.api_internal_pipeline_start` inside a test_request_context, so
the busy-check, the directive rules and the job registry all stay in the one
dispatcher — a second copy of them here is a second thing to drift.

Additive. Registers only /api/internal/char2d/*.
"""

from __future__ import annotations

import os

from flask import Blueprint, current_app, jsonify, request

bp = Blueprint('char2d', __name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
_OUT_ROOT = os.path.realpath(os.path.join(_HERE, 'output', 'char2d'))


def _local_only():
    return request.remote_addr in ('127.0.0.1', '::1')


@bp.route('/api/internal/char2d/spec', methods=['GET'])
def c2d_spec():
    """The vocabulary the Run prompt is built from: stages, views, gestures."""
    import glob
    from zyg_workflows import pipeline_char2d as _c2

    gestures = sorted(
        os.path.basename(p)[:-5]
        for p in glob.glob(os.path.join(_c2.GESTURE_DIR, '*.json'))
        if not os.path.basename(p).startswith('00_idle')
    )
    briefs = sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(_c2.BRIEF_DIR, '*.json')))
    return jsonify(
        {
            'stages': list(_c2.STAGES),
            'views': list(_c2.VIEWS),
            'gesture_views': list(_c2.GESTURE_VIEWS),
            'gestures': gestures,
            'briefs': briefs,
            'hair_cuts': ['bob', 'short', 'long'],
            'directive_example': 'Mika, 0.2, 19, 1.68, bob, #f5cfb5 #2a1a12 #3b5fa3 #2b2f3a',
            'out_root': _OUT_ROOT,
        }
    )


@bp.route('/api/internal/char2d/start', methods=['POST'])
def c2d_start():
    if not _local_only():
        return jsonify({'error': 'localhost only'}), 401
    data = request.get_json(silent=True) or {}
    brief = data.get('brief')
    directive = str(data.get('directive') or '').strip()
    if not directive and not isinstance(brief, dict):
        return jsonify({'error': 'a character brief is required'}), 400

    payload = {
        'pipeline_type': 'char2d',
        'directive': directive,
        'brief': brief if isinstance(brief, dict) else None,
        'pipeline_options': data.get('pipeline_options') or {},
    }

    from zyg_dashboard import bp_pipeline_api as _api

    with current_app.test_request_context(
        '/api/internal/pipeline/start', method='POST', json=payload, environ_base={'REMOTE_ADDR': '127.0.0.1'}
    ):
        resp = _api.api_internal_pipeline_start()
    # The dispatcher returns either a Response or the (Response, code) pair.
    if isinstance(resp, tuple):
        body, code = resp[0], resp[1]
    else:
        body, code = resp, 200
    return body, code
