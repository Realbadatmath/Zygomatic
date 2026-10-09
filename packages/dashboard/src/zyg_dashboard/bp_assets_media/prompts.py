# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Prompt registry endpoints, channel data and the sports-video status proxy.

Moved verbatim out of bp_assets_media.py (original lines 1672-1870).
"""

import json

from flask import jsonify, request

from zyg_dashboard.cors import apply_cors
from zyg_dashboard.gui.runtime_state import _runtime_path

from zyg_dashboard.bp_assets_media.base import (
    _CDR_OK,
    _SV_STATUS_FILE,
    _cdr,
    _cdr_e_str,
    _register_prompt,
    bp,
)


@bp.route('/api/asset_manager/prompts')
def api_asset_manager_prompts():
    """Return registered prompts from the prompt registry.

    Query params:
      ?category=<cat>       — filter by category
      ?include_retired=true — include retired/old versions in main list
      ?name=<name>          — return only entries matching this name (for version chain)

    Each active template entry has a 'version_history' array of all prior versions
    (sorted oldest→newest) so the UI can show the full change trail.
    """
    reg_path = _runtime_path('prompt_registry.json')
    try:
        with open(reg_path) as _prf:
            reg = json.load(_prf)
        all_prompts = list(reg.get('prompts', {}).values())
    except Exception:
        all_prompts = []

    cat_filter = request.args.get('category', '').strip()
    name_filter = request.args.get('name', '').strip()
    inc_retired = request.args.get('include_retired', 'false').lower() in ('true', '1')

    if cat_filter:
        all_prompts = [p for p in all_prompts if p.get('category') == cat_filter]
    if name_filter:
        all_prompts = [p for p in all_prompts if p.get('name') == name_filter]

    # Build id→entry map for parent chain lookups
    by_id = {p['id']: p for p in all_prompts}

    # Build version_history for each active entry: walk parent_id chain
    for p in all_prompts:
        if not p.get('active', True):
            continue
        chain = []
        cur_id = p.get('parent_id', '')
        visited = set()
        while cur_id and cur_id not in visited:
            visited.add(cur_id)
            anc = by_id.get(cur_id)
            if not anc:
                # Try full registry in case entry was filtered out
                try:
                    with open(reg_path) as _rf2:
                        _full = json.load(_rf2)
                    anc = _full.get('prompts', {}).get(cur_id)
                except Exception:
                    anc = None
            if not anc:
                break
            chain.append(
                {
                    'id': anc['id'],
                    'version': anc.get('version', '?'),
                    'created_at': anc.get('created_at', ''),
                    'retired_at': anc.get('retired_at', ''),
                    'created_by': anc.get('created_by', 'system'),
                    'change_notes': anc.get('change_notes', ''),
                    'use_count': anc.get('use_count', 0),
                    'prompt_text': anc.get('prompt_text', ''),
                }
            )
            cur_id = anc.get('parent_id', '')
        chain.reverse()  # oldest first
        p['version_history'] = chain

    # Return active only (or all if include_retired)
    visible = all_prompts if inc_retired else [p for p in all_prompts if p.get('active', True)]

    # Sort: most used first, then by name alphabetically
    visible.sort(
        key=lambda p: (
            -(p.get('use_count', 0)),
            p.get('name', ''),
        )
    )

    categories = sorted({p.get('category', '') for p in all_prompts if p.get('category')})
    return jsonify({'count': len(visible), 'prompts': visible, 'categories': categories})


@bp.route('/api/prompt_registry/update', methods=['POST'])
def api_prompt_registry_update():
    """Edit a prompt template from the UI, creating a new version.

    POST JSON: { "prompt_id": "pt_...", "new_text": "...", "change_notes": "..." }
    Finds the entry, reads its metadata, then calls _register_prompt() with
    the new text which will retire the old entry and create v+1.
    Returns { "success": true, "new_prompt_id": "pt_..." }
    """
    data = request.get_json(silent=True) or {}
    prompt_id = data.get('prompt_id', '').strip()
    new_text = data.get('new_text', '').strip()
    change_notes = data.get('change_notes', '').strip()

    if not prompt_id or not new_text:
        return jsonify({'success': False, 'error': 'prompt_id and new_text required'}), 400

    reg_path = _runtime_path('prompt_registry.json')
    try:
        with open(reg_path) as _prf:
            reg = json.load(_prf)
        entry = reg.get('prompts', {}).get(prompt_id)
    except Exception:
        entry = None

    if not entry:
        return jsonify({'success': False, 'error': 'Prompt not found'}), 404
    if not entry.get('active', True):
        return jsonify({'success': False, 'error': 'Cannot edit a retired version — revert it first'}), 400

    # If text is unchanged, nothing to do
    if entry.get('prompt_text', '') == new_text:
        return jsonify({'success': True, 'new_prompt_id': prompt_id, 'changed': False})

    new_id = _register_prompt(
        category=entry.get('category', ''),
        name=entry.get('name', ''),
        function_desc=entry.get('function_desc', ''),
        prompt_text=new_text,
        created_by='user',
        change_notes=change_notes or 'Manual edit via dashboard',
    )
    return jsonify({'success': True, 'new_prompt_id': new_id, 'changed': True})


@bp.route('/api/prompt_registry/revert', methods=['POST'])
def api_prompt_registry_revert():
    """Revert to an older version of a prompt template.

    POST JSON: { "prompt_id": "pt_..." }  — the OLD (retired) version to restore.
    Reads the old entry and calls _register_prompt() with its text + change_notes.
    The currently active version is retired; the old text becomes the new active v+1.
    Returns { "success": true, "new_prompt_id": "pt_..." }
    """
    data = request.get_json(silent=True) or {}
    old_id = data.get('prompt_id', '').strip()

    if not old_id:
        return jsonify({'success': False, 'error': 'prompt_id required'}), 400

    reg_path = _runtime_path('prompt_registry.json')
    try:
        with open(reg_path) as _prf:
            reg = json.load(_prf)
        entry = reg.get('prompts', {}).get(old_id)
    except Exception:
        entry = None

    if not entry:
        return jsonify({'success': False, 'error': 'Prompt not found'}), 404

    new_id = _register_prompt(
        category=entry.get('category', ''),
        name=entry.get('name', ''),
        function_desc=entry.get('function_desc', ''),
        prompt_text=entry.get('prompt_text', ''),
        created_by='revert',
        change_notes=f'Reverted to v{entry.get("version", "?")} (id={old_id[:10]})',
    )
    return jsonify({'success': True, 'new_prompt_id': new_id})


@bp.route('/api/channel-data/groups')
def api_channel_data_groups():
    """Return channel group metadata for the UI sidebar."""
    if not _CDR_OK:
        return jsonify({'error': _cdr_e_str}), 500
    return jsonify({'groups': _cdr.CHANNEL_GROUPS})


@bp.route('/api/channel-data/<channel_key>')
def api_channel_data_fetch(channel_key):
    """Fetch live data for one channel. Returns standard result dict."""
    if not _CDR_OK:
        return jsonify({'status': 'error', 'error': _cdr_e_str}), 500
    if channel_key not in _cdr.REGISTRY:
        return jsonify({'status': 'error', 'error': f'Unknown channel: {channel_key}'}), 404
    try:
        result = _cdr.REGISTRY[channel_key]()
        return jsonify(result)
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e), 'channel': channel_key, 'item_count': 0, 'items': []}), 500


@bp.route('/api/sports-video/status')
def sv_status_proxy():
    try:
        with open(_SV_STATUS_FILE) as _f:
            data = json.load(_f)
    except FileNotFoundError:
        data = {'state': 'idle', 'step': None, 'progress': 0, 'total_rendered': 0, 'history': []}
    except Exception as _e:
        return jsonify({'state': 'error', 'last_error': str(_e)}), 500
    resp = jsonify(data)
    apply_cors(resp, request)
    return resp
