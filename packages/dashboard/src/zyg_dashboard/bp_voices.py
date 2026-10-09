# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).
import json
import os
from flask import (
    Blueprint,
    jsonify,
    request,
)
from zyg_workflows.tts_service import _tts_shared

bp = Blueprint('voices', __name__)

from zyg_dashboard.crewai_web_gui import (  # noqa: E402  late: crewai_web_gui imports this blueprint at its bottom, so `bp` must exist first
    _CHANNEL_VOICES_PATH,
    _VOICE_LIBRARY_PATH,
)
from zyg_dashboard.gui.runtime_state import _runtime_path  # noqa: E402  moved by the round-2 gui/ split


@bp.route('/api/voices')
def api_voices():
    """Return all narrator voice profiles."""
    try:
        with open(_VOICE_LIBRARY_PATH) as _f:
            lib = json.load(_f)
        voices = lib.get('voices', {})
        return jsonify({'voices': list(voices.values())})
    except Exception as e:
        return jsonify({'voices': [], 'error': str(e)})


@bp.route('/api/voices/channel-assignments')
def api_voices_channel_assignments():
    """Return current channel→voice assignments."""
    try:
        with open(_CHANNEL_VOICES_PATH) as _f:
            cfg = json.load(_f)
        assignments = cfg.get('channels', {})
        ch_path = _runtime_path('clipfarm_channels.json')
        channels = []
        if os.path.exists(ch_path):
            with open(ch_path) as _f2:
                channels = json.load(_f2)
        return jsonify({'assignments': assignments, 'channels': channels})
    except Exception as e:
        return jsonify({'assignments': {}, 'channels': [], 'error': str(e)})


@bp.route('/api/voices/assign', methods=['POST'])
def api_voices_assign():
    """Assign a voice profile to a channel."""
    data = request.get_json(force=True) or {}
    channel_id = data.get('channel_id', '')
    profile_id = data.get('profile_id', '')
    channel_name = data.get('channel_name', '')
    if not channel_id or not profile_id:
        return jsonify({'success': False, 'error': 'channel_id and profile_id required'}), 400
    try:
        with open(_CHANNEL_VOICES_PATH) as _f:
            cfg = json.load(_f)
        cfg.setdefault('channels', {})[channel_id] = {
            'channel_name': channel_name,
            'profile_id': profile_id,
            'assigned_at': 'manual',
            'reason': 'Manually assigned via Voices settings',
        }
        with open(_CHANNEL_VOICES_PATH, 'w') as _f:
            json.dump(cfg, _f, indent=2)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@bp.route('/api/voices/play', methods=['POST'])
def api_voices_play():
    """Generate TTS preview: IndexTTS-2 primary, Chatterbox fallback."""
    import tempfile as _tmp_vp
    from flask import send_file as _send_file_vp

    data = request.get_json(force=True) or {}
    profile_id = data.get('profile_id', '')
    text = 'Alignment is not mixing guava with petrol and expecting gravy.'
    try:
        try:
            with open(_VOICE_LIBRARY_PATH) as _f:
                lib = json.load(_f)
        except FileNotFoundError:
            lib = {}  # no library on this installation — every profile is absent
        voices = lib.get('voices', {})
        profile = voices.get(profile_id)
        if not profile:
            return jsonify({'error': 'Voice profile not found'}), 404

        # Previews mirror production: IndexTTS-2 primary, Chatterbox fallback,
        # cloning the same seed-pool voice the pipelines would use.
        voice_name = profile.get('voice', 'en-GB-RyanNeural')
        _tmp_fd, tmp = _tmp_vp.mkstemp(suffix='.mp3')
        os.close(_tmp_fd)
        _ok, _ = _tts_shared(text, tmp, 'Voice preview', log_fn=None, voice_id=voice_name)

        if _ok and os.path.isfile(tmp) and os.path.getsize(tmp) > 500:
            return _send_file_vp(tmp, mimetype='audio/mpeg', as_attachment=False)
        return jsonify({'error': 'TTS preview failed (IndexTTS-2 + Chatterbox)'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/sources')
def api_sources():
    """Return all asset sources."""
    sources_path = _runtime_path('asset_sources.json')
    try:
        with open(sources_path) as _f:
            data = json.load(_f)
        return jsonify(data)
    except Exception as e:
        return jsonify({'sources': [], 'error': str(e)})


@bp.route('/api/court-cases')
def api_court_cases():
    """Return court cases database."""
    cases_path = _runtime_path('court_cases.json')
    try:
        with open(cases_path) as _f:
            data = json.load(_f)
        return jsonify(data)
    except Exception as e:
        return jsonify({'cases': [], 'error': str(e)})
