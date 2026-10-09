# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 by the GUI modularization — extracted from crewai_web_gui.py.
# Source lines: see crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md
# Contract: this module is imported at the BOTTOM of crewai_web_gui.py, after all
# of main's globals exist; `from crewai_web_gui import X` is therefore safe here.
import os
from flask import Blueprint, jsonify, send_from_directory

bp = Blueprint('themes_users', __name__)

from zyg_dashboard.crewai_web_gui import (  # noqa: E402  (late import by design, see contract above)
    BACKGROUNDS_DIR,
    BUTTONS_DIR,
    DASHBOARD_AVAILABLE,
    DEFAULT_BACKGROUND_THEME,
    DEFAULT_BUTTON_THEME,
    SIDEBAR_DIR,
    THEME_CONFIG_PATH,
    USERS_DATA_PATH,
    _theme_version,
    limiter,
)
from zyg_dashboard.gui.runtime_state import _load_json  # noqa: E402  moved by the round-2 gui/ split


@bp.route('/api/dashboard/themes/config')
def dashboard_themes_config():
    if not DASHBOARD_AVAILABLE:
        data = {
            'button_theme': DEFAULT_BUTTON_THEME,
            'background_theme': DEFAULT_BACKGROUND_THEME,
            'apply_buttons_to_tabs': ['all'],
            'apply_background_to_tabs': ['all'],
        }
        data['_version'] = _theme_version(data)
        return jsonify(data)
    data = _load_json(
        THEME_CONFIG_PATH,
        {
            'button_theme': DEFAULT_BUTTON_THEME,
            'background_theme': DEFAULT_BACKGROUND_THEME,
            'apply_buttons_to_tabs': ['all'],
            'apply_background_to_tabs': ['all'],
        },
    )
    data['_version'] = _theme_version(data)
    return jsonify(data)


@bp.route('/api/dashboard/themes/config', methods=['POST'])
def dashboard_themes_config_save():
    # No disk write: theme config is read-only; control plane owns state.
    # When re-enabled: require X-If-Match / If-Match header with _version for optimistic locking.
    return jsonify({'success': False, 'message': 'Theme config is read-only; use control plane.'}), 501


@bp.route('/api/dashboard/themes/buttons/list')
def dashboard_themes_buttons_list():
    if not DASHBOARD_AVAILABLE or not os.path.isdir(BUTTONS_DIR):
        return jsonify([])
    files = [f for f in os.listdir(BUTTONS_DIR) if f.endswith('.html')]
    return jsonify(files)


@bp.route('/api/dashboard/themes/buttons/file/<path:filename>')
def dashboard_themes_buttons_file(filename):
    if not DASHBOARD_AVAILABLE:
        return jsonify({'error': 'Dashboard not available'}), 404
    path = os.path.join(BUTTONS_DIR, filename)
    if not os.path.isfile(path) or not path.startswith(os.path.abspath(BUTTONS_DIR)):
        return jsonify({'error': 'Not found'}), 404
    return send_from_directory(BUTTONS_DIR, filename, mimetype='text/html')


@bp.route('/api/dashboard/themes/backgrounds/list')
def dashboard_themes_backgrounds_list():
    if not DASHBOARD_AVAILABLE or not os.path.isdir(BACKGROUNDS_DIR):
        return jsonify([])
    files = [f for f in os.listdir(BACKGROUNDS_DIR) if f.endswith('.html')]
    return jsonify(files)


@bp.route('/api/dashboard/themes/backgrounds/file/<path:filename>')
def dashboard_themes_backgrounds_file(filename):
    if not DASHBOARD_AVAILABLE:
        return jsonify({'error': 'Dashboard not available'}), 404
    path = os.path.join(BACKGROUNDS_DIR, filename)
    if not os.path.isfile(path) or not os.path.abspath(path).startswith(os.path.abspath(BACKGROUNDS_DIR)):
        return jsonify({'error': 'Not found'}), 404
    return send_from_directory(BACKGROUNDS_DIR, filename, mimetype='text/html')


@bp.route('/api/dashboard/themes/sidebar/list')
def dashboard_themes_sidebar_list():
    if not DASHBOARD_AVAILABLE or not os.path.isdir(SIDEBAR_DIR):
        return jsonify([])
    files = [f for f in os.listdir(SIDEBAR_DIR) if f.endswith('.html')]
    return jsonify(files)


@bp.route('/api/dashboard/themes/sidebar/file/<path:filename>')
def dashboard_themes_sidebar_file(filename):
    if not DASHBOARD_AVAILABLE:
        return jsonify({'error': 'Dashboard not available'}), 404
    path = os.path.join(SIDEBAR_DIR, filename)
    if not os.path.isfile(path) or not os.path.abspath(path).startswith(os.path.abspath(SIDEBAR_DIR)):
        return jsonify({'error': 'Not found'}), 404
    return send_from_directory(SIDEBAR_DIR, filename, mimetype='text/html')


@bp.route('/api/dashboard/users')
def dashboard_users():
    if not DASHBOARD_AVAILABLE:
        return jsonify({'admins': [], 'operators': [], 'ai_operators': [], 'spectators': []})
    return jsonify(_load_json(USERS_DATA_PATH, {'admins': [], 'operators': [], 'ai_operators': [], 'spectators': []}))


@bp.route('/api/dashboard/users', methods=['POST'])
def dashboard_users_save():
    # No disk write: user management is owned by control plane.
    return jsonify({'success': False, 'message': 'User management is read-only; use control plane.'}), 501


@bp.route('/api/dashboard/users/avatar/<user_id>', methods=['POST'])
def dashboard_users_avatar_upload(user_id):
    # No disk write from Flask; control plane or static CDN should handle avatars.
    return jsonify({'success': False, 'message': 'Avatar upload disabled; use control plane.'}), 501


@bp.route('/api/dashboard/blueprint', methods=['POST'])
@limiter.limit('10/hour')
def dashboard_blueprint_create():
    """Create dashboard blueprint (command: bp). Saves to Zygomatic Origin/Blueprint/dashboard_blueprint.md."""
    try:
        import importlib.util

        script_path = os.path.join(os.path.dirname(__file__), 'scripts', 'create_dashboard_blueprint.py')
        spec = importlib.util.spec_from_file_location('create_dashboard_blueprint', script_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        path = mod.save_blueprint()
        return jsonify({'success': True, 'path': path, 'message': 'Blueprint created successfully.'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
