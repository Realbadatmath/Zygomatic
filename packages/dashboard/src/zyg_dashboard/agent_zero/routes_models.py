# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""HTTP surface of Agent Zero v2's model picker (``/api/zero/v2/models...``).

Thin JSON wrappers around :mod:`agent_zero.models`: no logic lives here beyond
turning a ``ValueError`` from the registry into a 400 (or 409 while an install is
already running). Authentication is the dashboard's: the host's ``before_request``
login gate covers every route of this blueprint, so nothing is re-implemented here.
"""

from __future__ import annotations

import logging

from flask import jsonify, request

from . import bp, models

_log = logging.getLogger(__name__)


def _body() -> dict:
    """The request's JSON body, tolerant of a missing or malformed one."""
    return request.get_json(silent=True) or {}


@bp.route('/api/zero/v2/models', methods=['GET'])
def zero_v2_models():
    """The whole Select Model payload (CONTRACT B)."""
    return jsonify(models.list_models())


@bp.route('/api/zero/v2/models/select', methods=['POST'])
def zero_v2_models_select():
    """Persist the operator's choice of provider + model."""
    body = _body()
    try:
        selected = models.set_selection(
            str(body.get('provider') or ''),
            str(body.get('model') or ''),
            allow_custom=bool(body.get('allow_custom')),
        )
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    return jsonify({'ok': True, 'selected': selected})


@bp.route('/api/zero/v2/models/install', methods=['POST'])
def zero_v2_models_install():
    """Start an Ollama pull. 202 with a job id, or 400/409 with the reason."""
    body = _body()
    try:
        started = models.start_install(str(body.get('model') or ''), confirm=body.get('confirm') is True)
    except ValueError as exc:
        message = str(exc)
        status = 409 if 'already running' in message else 400
        return jsonify({'ok': False, 'error': message}), status
    return jsonify({'ok': True, **started}), 202


@bp.route('/api/zero/v2/models/install/<job_id>', methods=['GET'])
def zero_v2_models_install_status(job_id):
    """Progress of one install job."""
    job = models.install_status(job_id)
    if job is None:
        return jsonify({'ok': False, 'error': f'unknown job: {job_id}'}), 404
    return jsonify({'ok': True, 'job': job})


@bp.route('/api/zero/v2/models/machine', methods=['GET'])
def zero_v2_models_machine():
    """GPU / RAM / disk / Ollama version of this box."""
    return jsonify(models.machine())


@bp.route('/api/zero/v2/providers/<provider>/key', methods=['POST'])
def zero_v2_provider_key_set(provider):
    """Store an API key for a provider. The key is never echoed back."""
    try:
        result = models.set_provider_key(provider, str(_body().get('key') or ''))
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except OSError as exc:
        _log.warning('agent_zero: cannot write the provider key store (%s)', exc)
        return jsonify({'ok': False, 'error': 'cannot write the key store'}), 500
    return jsonify({'ok': True, 'suffix': result['suffix']})


@bp.route('/api/zero/v2/providers/<provider>/key', methods=['DELETE'])
def zero_v2_provider_key_clear(provider):
    """Forget a provider's stored API key."""
    try:
        result = models.clear_provider_key(provider)
    except OSError as exc:
        _log.warning('agent_zero: cannot write the provider key store (%s)', exc)
        return jsonify({'ok': False, 'error': 'cannot write the key store'}), 500
    return jsonify({'ok': True, 'cleared': result['cleared']})
