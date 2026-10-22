# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The blueprint itself and the agent-roster endpoints — bp_agents_api part 1.

Holds the original module's import block, so ``bp``, ``limiter``, ``controller``
and every shared helper are bound here, once, and the sibling sections import
them from this module.
"""

# The original import block is re-exported to the siblings.

import logging as _zyg_logging
import json
import os
import time
from flask import (
    Blueprint,
    jsonify,
    request,
    send_from_directory,
    session,
)
from zyg_dashboard.cors import apply_cors

# root_path kept from the pre-split module: Flask derives it from this module's
# own directory, which is the package directory the single file's root_path was.
bp = Blueprint('agents_api', __name__)
from zyg_dashboard.gui.runtime_state import _load_json, _runtime_path, _workflow_jobs  # noqa: E402
from zyg_dashboard.gui.telemetry import _backend_debug, _get_cpu_bar_mapping, _get_gpu_bar_mapping  # noqa: E402
from zyg_dashboard.gui.zero_store import _zero_load_config  # noqa: E402
from zyg_dashboard.crewai_web_gui import (  # noqa: E402
    _AGENT_FACES_BASE,
    _AGENT_FACE_EXTENSIONS,
    _CLIPFARM_STAGES,
    _first_list,
    _get_all_tools,
    _load_canonical_json,
    _resolve_agent_display_name,
    _resolve_ai_models_display,
    _zero_agent_legacy_shape,
    get_agent_name_by_id,
    get_model_name_by_id,
    html_module,
    limiter,
)

# `controller` lives in gui/controller.py, but that module instantiates it at import
# time and reaches back into crewai_web_gui, so it must be imported only once
# crewai_web_gui is loaded (above) — never before it.
from zyg_dashboard.gui.controller import controller  # noqa: E402
from zyg_dashboard import crewai_web_gui as _main_mod  # noqa: E402  late: crewai_web_gui imports this blueprint at its bottom, so `bp` must exist first


# ── re-export surface ──
# Every name below is imported above and NOT used in this module; it is here so
# importers keep resolving it through this module. Nothing does ``import *`` from
# here, so __all__ changes no behaviour -- it is how ruff is told these are public.
__all__ = [
    'json',
    'time',
    'request',
    'apply_cors',
    '_runtime_path',
    '_workflow_jobs',
    '_get_cpu_bar_mapping',
    '_zero_load_config',
    '_CLIPFARM_STAGES',
    '_get_all_tools',
    '_load_canonical_json',
    'get_model_name_by_id',
    'html_module',
]

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_agents_api')


# runtime-conditional names (bound in main inside try/except — tolerant binding,
# matching the original graceful-degradation semantics):
API_ADAPTER_AVAILABLE = getattr(_main_mod, 'API_ADAPTER_AVAILABLE', None)
USERS_DATA_PATH = getattr(_main_mod, 'USERS_DATA_PATH', None)
api_get_agents = getattr(_main_mod, 'api_get_agents', None)
get_active_schedule = getattr(_main_mod, 'get_active_schedule', None)


def _agent_api_to_legacy_shape(api_item, local_config=None):
    """Transform control-plane agent schema to legacy UI shape. Merges with local agent_configs for role, backstory, goal when API omits them."""
    raw_name = api_item.get('name') or api_item.get('id', '') or ''
    api_id = api_item.get('id')
    # Resolve display name: use config name when API returns seed placeholder (Agent 001, agent-001)
    name = _resolve_agent_display_name(raw_name, api_id) or raw_name
    # Resolve local config: by display name, numeric id, or seed id
    cfg = local_config
    if cfg is None and controller.agent_configs:
        cfg = controller.agent_configs.get(name)
        if cfg is None and api_id:
            resolved_name = get_agent_name_by_id(str(api_id))
            if resolved_name:
                cfg = controller.agent_configs.get(resolved_name)
        if cfg is None and raw_name != name:
            cfg = controller.agent_configs.get(name)
    base = {
        'id': api_id,
        'name': name,
        'role': api_item.get('role') or (cfg.get('role', '') if cfg else ''),
        'goal': api_item.get('description') or api_item.get('goal') or (cfg.get('goal', '') if cfg else ''),
        'backstory': api_item.get('backstory') or (cfg.get('backstory', '') if cfg else ''),
        'department': api_item.get('department') or (cfg.get('department', '') if cfg else ''),
        'tier': api_item.get('tier') if api_item.get('tier') is not None else (cfg.get('tier', 0) if cfg else 0),
        'primary_task': api_item.get('primary_task') or (cfg.get('primary_task', '') if cfg else ''),
        'tools': api_item.get('tools')
        if isinstance(api_item.get('tools'), list)
        else (cfg.get('tools', []) if cfg else []),
        'skills': api_item.get('capabilities', [])
        if isinstance(api_item.get('capabilities'), list)
        else (cfg.get('skills', []) if cfg else []),
        'max_concurrent_tasks': api_item.get('max_concurrent_tasks')
        if api_item.get('max_concurrent_tasks') is not None
        else (cfg.get('max_concurrent_tasks', 1) if cfg else 1),
        'current_tasks': api_item.get('current_tasks')
        if api_item.get('current_tasks') is not None
        else (cfg.get('current_tasks', 0) if cfg else 0),
        'supervisor': api_item.get('supervisor') or (cfg.get('supervisor') or '') if cfg else '',
        'subordinates': api_item.get('subordinates')
        if isinstance(api_item.get('subordinates'), list)
        else (cfg.get('subordinates', []) if cfg else []),
        'ai_models': _first_list(
            api_item.get('ai_models'), api_item.get('capabilities'), cfg.get('ai_models', []) if cfg else []
        ),
        'ai_models_display': _resolve_ai_models_display(
            _first_list(
                api_item.get('ai_models'), api_item.get('capabilities'), cfg.get('ai_models', []) if cfg else []
            )
        ),
        'gpu_schedule': api_item.get('gpu_schedule')
        if api_item.get('gpu_schedule') is not None
        else (cfg.get('gpu_schedule') if cfg else None),
        'production_workflow': _first_list(
            api_item.get('production_workflow'), cfg.get('production_workflow', []) if cfg else []
        ),
        'tasks': _first_list(api_item.get('tasks'), cfg.get('tasks', []) if cfg else []),
        'performance_metrics': _first_list(
            api_item.get('performance_metrics'), cfg.get('performance_metrics', []) if cfg else []
        ),
        'collaboration_protocols': _first_list(
            api_item.get('collaboration_protocols'), cfg.get('collaboration_protocols', []) if cfg else []
        ),
        'capabilities': _first_list(
            api_item.get('capabilities'), cfg.get('capabilities', cfg.get('skills', [])) if cfg else []
        ),
        'permissions': _first_list(
            api_item.get('permissions'),
            cfg.get('permissions', cfg.get('capabilities', cfg.get('skills', []))) if cfg else [],
        ),
    }
    return base


@bp.route('/api/agents')
@limiter.exempt
def get_agents():
    """API endpoint: from control plane when available. If adapter unreachable (status 0/503), fail closed with 503."""
    token = session.get('api_token')
    if API_ADAPTER_AVAILABLE:
        data = api_get_agents(token)
        if data.get('error'):
            st = data.get('status', 0)
            if st == 401:
                return jsonify({'error': data.get('error')}), 401
            if st == 0 or st == 503:
                return jsonify({'error': 'Control plane unavailable'}), 503
        items = data.get('items') or []
        if items:
            agent_list = [_agent_api_to_legacy_shape(a) for a in items]
            api_names = {(a.get('name') or a.get('id') or '') for a in agent_list}
            # Merge in local agents not in control-plane response (e.g. new workflow box agents)
            if controller.agent_configs:
                for name, config in controller.agent_configs.items():
                    if name not in api_names:
                        ai_models = config.get('ai_models', [])
                        agent_list.append(
                            {
                                'id': config.get('id') or name,
                                'name': name,
                                'role': config.get('role', ''),
                                'goal': config.get('goal', ''),
                                'backstory': config.get('backstory', ''),
                                'department': config.get('department', ''),
                                'tier': config.get('tier', 0),
                                'primary_task': config.get('primary_task', ''),
                                'tools': config.get('tools', []),
                                'skills': config.get('skills', []),
                                'max_concurrent_tasks': config.get('max_concurrent_tasks', 1),
                                'current_tasks': config.get('current_tasks', 0),
                                'supervisor': config.get('supervisor', ''),
                                'subordinates': config.get('subordinates', []),
                                'production_workflow': config.get('production_workflow', []),
                                'tasks': config.get('tasks', []),
                                'performance_metrics': config.get('performance_metrics', []),
                                'ai_models': ai_models,
                                'ai_models_display': _resolve_ai_models_display(ai_models),
                                'capabilities': config.get('capabilities', config.get('skills', [])),
                                'gpu_schedule': config.get('gpu_schedule', None),
                            }
                        )
            # Append Zero (from agent_zero.json, not agents.json)
            if not any(a.get('name') == 'Zero' for a in agent_list):
                agent_list.append(_zero_agent_legacy_shape())
            return jsonify(agent_list)
        # Control plane returned no agents: fall back to local agent_configurations for biography/role
        if controller.agent_configs:
            agent_list = []
            for name, config in controller.agent_configs.items():
                ai_models = config.get('ai_models', [])
                agent_list.append(
                    {
                        'id': config.get('id') or name,
                        'name': name,
                        'role': config.get('role', ''),
                        'goal': config.get('goal', ''),
                        'backstory': config.get('backstory', ''),
                        'department': config.get('department', ''),
                        'tier': config.get('tier', 0),
                        'primary_task': config.get('primary_task', ''),
                        'tools': config.get('tools', []),
                        'skills': config.get('skills', []),
                        'max_concurrent_tasks': config.get('max_concurrent_tasks', 1),
                        'current_tasks': config.get('current_tasks', 0),
                        'supervisor': config.get('supervisor', ''),
                        'subordinates': config.get('subordinates', []),
                        'production_workflow': config.get('production_workflow', []),
                        'tasks': config.get('tasks', []),
                        'performance_metrics': config.get('performance_metrics', []),
                        'ai_models': ai_models,
                        'ai_models_display': _resolve_ai_models_display(ai_models),
                        'capabilities': config.get('capabilities', config.get('skills', [])),
                        'gpu_schedule': config.get('gpu_schedule', None),
                    }
                )
            agent_list.append(_zero_agent_legacy_shape())
            return jsonify(agent_list)
    agent_list = []
    for name, config in controller.agent_configs.items():
        ai_models = config.get('ai_models', [])
        agent_list.append(
            {
                'id': name,
                'name': name,
                'role': config['role'],
                'goal': config['goal'],
                'backstory': config['backstory'],
                'department': config.get('department', ''),
                'tier': config.get('tier', 0),
                'primary_task': config.get('primary_task', ''),
                'tools': config.get('tools', []),
                'skills': config.get('skills', []),
                'max_concurrent_tasks': config.get('max_concurrent_tasks', 1),
                'current_tasks': config.get('current_tasks', 0),
                'supervisor': config.get('supervisor', ''),
                'subordinates': config.get('subordinates', []),
                'ai_models': ai_models,
                'ai_models_display': _resolve_ai_models_display(ai_models),
                'gpu_schedule': config.get('gpu_schedule', None),
            }
        )
    agent_list.append(_zero_agent_legacy_shape())
    return jsonify(agent_list)


@bp.route('/api/agents/tier1')
def get_tier1_agents():
    """API endpoint to get all GPU-capable agents (Tier 1). Uses data/agents.json or agent_model_bar_mapping."""
    gpu_agent_names = set()
    try:
        gpu_mapping = _get_gpu_bar_mapping()
        canonical_gpu_models = set()
        for agent_data in gpu_mapping.values():
            for model in agent_data.get('models', []):
                canonical_gpu_models.add(model['model'])
        for name, agent_data in gpu_mapping.items():
            models = [m['model'] for m in agent_data.get('models', [])]
            if any(m in canonical_gpu_models for m in models):
                gpu_agent_names.add(name)
    except Exception as e:
        _backend_debug(f'Error loading GPU mapping for tier1 agents: {e}')
        # Fallback: agents with tier == 1 in config
        gpu_agent_names = {name for name, config in controller.agent_configs.items() if config.get('tier') == 1}

    agent_list = []
    for name, config in controller.agent_configs.items():
        if name in gpu_agent_names:
            ai_models = config.get('ai_models', [])
            agent_list.append(
                {
                    'name': name,
                    'role': config['role'],
                    'goal': config['goal'],
                    'backstory': config['backstory'],
                    'department': config.get('department', ''),
                    'tier': config.get('tier', 0),
                    'primary_task': config.get('primary_task', ''),
                    'tools': config.get('tools', []),
                    'skills': config.get('skills', []),
                    'max_concurrent_tasks': config.get('max_concurrent_tasks', 1),
                    'current_tasks': config.get('current_tasks', 0),
                    'supervisor': config.get('supervisor', ''),
                    'subordinates': config.get('subordinates', []),
                    'ai_models': ai_models,
                    'ai_models_display': _resolve_ai_models_display(ai_models),
                    'gpu_schedule': config.get('gpu_schedule', None),
                }
            )
    return jsonify(agent_list)


@bp.route('/api/agents/department/<department>')
def get_department_agents(department):
    """API endpoint to get all agents in a specific department"""
    agent_list = []
    for name, config in controller.agent_configs.items():
        if config.get('department') == department:
            ai_models = config.get('ai_models', [])
            agent_list.append(
                {
                    'name': name,
                    'role': config['role'],
                    'goal': config['goal'],
                    'backstory': config['backstory'],
                    'department': config.get('department', ''),
                    'tier': config.get('tier', 0),
                    'primary_task': config.get('primary_task', ''),
                    'tools': config.get('tools', []),
                    'skills': config.get('skills', []),
                    'max_concurrent_tasks': config.get('max_concurrent_tasks', 1),
                    'current_tasks': config.get('current_tasks', 0),
                    'supervisor': config.get('supervisor', ''),
                    'subordinates': config.get('subordinates', []),
                    'ai_models': ai_models,
                    'ai_models_display': _resolve_ai_models_display(ai_models),
                    'gpu_schedule': config.get('gpu_schedule', None),
                }
            )
    return jsonify(agent_list)


def _get_agents_list():
    """Return full agent list (same source as get_agents). Used by assigned-to filter. Includes Zero from agent_zero.json."""
    token = session.get('api_token')
    if API_ADAPTER_AVAILABLE:
        data = api_get_agents(token)
        if data.get('error'):
            return None, data.get('status', 503)
        items = data.get('items') or []
        agent_list = [_agent_api_to_legacy_shape(a) for a in items]
        if not any(a.get('name') == 'Zero' for a in agent_list):
            agent_list.append(_zero_agent_legacy_shape())
        return agent_list, None
    agent_list = []
    for name, config in controller.agent_configs.items():
        ai_models = config.get('ai_models', [])
        agent_list.append(
            {
                'id': name,
                'name': name,
                'role': config['role'],
                'goal': config['goal'],
                'backstory': config['backstory'],
                'department': config.get('department', ''),
                'tier': config.get('tier', 0),
                'primary_task': config.get('primary_task', ''),
                'tools': config.get('tools', []),
                'skills': config.get('skills', []),
                'max_concurrent_tasks': config.get('max_concurrent_tasks', 1),
                'current_tasks': config.get('current_tasks', 0),
                'supervisor': config.get('supervisor', ''),
                'subordinates': config.get('subordinates', []),
                'ai_models': ai_models,
                'ai_models_display': _resolve_ai_models_display(ai_models),
                'gpu_schedule': config.get('gpu_schedule', None),
            }
        )
    agent_list.append(_zero_agent_legacy_shape())
    return agent_list, None


def _find_agent_face_path(identifier):
    """Look for agent face image by id or name. Returns (path, mimetype) or (None, None)."""
    if not identifier or not isinstance(identifier, str):
        return None, None
    ident = identifier.strip()
    if not ident or '..' in ident or '/' in ident or '\\' in ident:
        return None, None
    if not os.path.isdir(_AGENT_FACES_BASE):
        return None, None
    # Try: exact identifier, id_with_underscores, id_with_no_spaces
    candidates = [ident, ident.replace(' ', '_'), ident.replace(' ', '')]
    seen = set()
    for c in candidates:
        if not c or c in seen:
            continue
        seen.add(c)
        for ext in _AGENT_FACE_EXTENSIONS:
            fn = c + ext
            path = os.path.join(_AGENT_FACES_BASE, fn)
            if os.path.isfile(path):
                mime = 'image/png' if ext == '.png' else ('image/jpeg' if ext in ('.jpg', '.jpeg') else 'image/webp')
                return path, mime
    return None, None


@bp.route('/api/agents/face/<path:identifier>')
def get_agent_face(identifier):
    """Serve agent face image from Agent Appearences/Faces. Falls back to 404; frontend uses placeholder."""
    import urllib.parse

    decoded = urllib.parse.unquote(identifier)
    path, mimetype = _find_agent_face_path(decoded)
    if path and mimetype:
        return send_from_directory(_AGENT_FACES_BASE, os.path.basename(path), mimetype=mimetype)
    return jsonify({'error': 'Agent face not found'}), 404


@bp.route('/api/agents/assigned-to/<user_id>')
def get_agents_assigned_to_user(user_id):
    """Return agents assigned to a user. Admin sees all. Users with assigned_agents in dashboard_users.json get filtered set."""
    users_data = _load_json(USERS_DATA_PATH, {'admins': [], 'operators': [], 'ai_operators': [], 'spectators': []})
    all_users = (
        (users_data.get('admins') or [])
        + (users_data.get('operators') or [])
        + (users_data.get('ai_operators') or [])
        + (users_data.get('spectators') or [])
    )
    user_id_lower = (user_id or '').strip().lower()
    if not user_id_lower:
        return jsonify([])

    def user_matches(u):
        uid = (u.get('id') or '').strip().lower()
        uname = (u.get('name') or '').strip().lower()
        return uid == user_id_lower or uname == user_id_lower or user_id_lower in uid or user_id_lower in uname

    matched_user = next((u for u in all_users if user_matches(u)), None)
    admins = [u.get('id') or u.get('name') for u in (users_data.get('admins') or []) if u.get('id') or u.get('name')]
    is_admin = matched_user and (
        (matched_user.get('id') or matched_user.get('name') or '') in admins or matched_user.get('role') == 'admin'
    )
    if matched_user and is_admin:
        agent_list, err = _get_agents_list()
        if err:
            return jsonify({'error': 'Control plane unavailable'}), 503 if err == 0 else err
        return jsonify(agent_list or [])
    assigned = (matched_user.get('assigned_agents') or matched_user.get('agents') or []) if matched_user else []
    if isinstance(assigned, str):
        assigned = [a.strip() for a in assigned.split(',') if a.strip()]
    if not assigned and matched_user:
        return jsonify([])
    if not assigned:
        agent_list, err = _get_agents_list()
        if err:
            return jsonify({'error': 'Control plane unavailable'}), 503 if err == 0 else err
        return jsonify(agent_list or [])
    agent_names = set(a.strip() for a in assigned if a.strip())
    agent_list, err = _get_agents_list()
    if err:
        return jsonify({'error': 'Control plane unavailable'}), 503 if err == 0 else err
    return jsonify([a for a in (agent_list or []) if (a.get('name') or '') in agent_names])
