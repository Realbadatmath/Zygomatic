# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).
import json
from zyg_workflows.pipeline_config import (
    _CHANNEL_VOICES_PATH,
    _INTROS_FEMALE_PATH,
    _INTROS_GENERAL_PATH,
    _INTRO_CATEGORY_KEYWORDS,
    _INTRO_FEMALE_KEYWORDS,
    _VOICE_LIBRARY_PATH,
)
from zyg_workflows.runtime import _VOICE_LOCK
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_vid_to_channel_id: dict = {}


def _pick_narrator_intro(vid_id: str, transcript_text: str, clip_title: str = '') -> str:
    """Pick the best category-matched intro line from the library.
    Uses female library if channel is assigned a female voice profile, else general.
    Returns a fallback line if no match or files missing."""
    import random as _rr

    _FALLBACK_INTROS = [
        'Get ready, we are about to lose some braincells.',
        'Pay attention, the information in this clip is invaluable.',
        'Borderline — watch this.',
        "Nightlife is awesome, let's take a look.",
        "Watch closely. You'll miss it if you blink.",
        'Nobody in that room saw this coming.',
        'Everything changed in three seconds.',
    ]
    try:
        # Determine if female voice is assigned for this channel
        channel_id = _vid_to_channel_id.get(vid_id, '')
        _is_female = False
        try:
            with open(_CHANNEL_VOICES_PATH) as _cf:
                _ch_cfg = json.load(_cf)
            _profile_id = _ch_cfg.get('channels', {}).get(channel_id, {}).get('profile_id', '')
            with open(_VOICE_LIBRARY_PATH) as _vf:
                _lib = json.load(_vf)
            _is_female = _lib.get('voices', {}).get(_profile_id, {}).get('gender', '') == 'female'
        except Exception as _exc:
            _zyg_log.warning('channel voice config unreadable, assuming a male narrator: %s', _exc)

        # Build combined searchable text from title + transcript excerpt
        _search = (clip_title + ' ' + transcript_text[:2000]).lower()

        # Try female categories first if female voice
        if _is_female:
            best_cat, best_score = None, 0
            for cat, kws in _INTRO_FEMALE_KEYWORDS.items():
                sc = sum(1 for kw in kws if kw in _search)
                if sc > best_score:
                    best_score, best_cat = sc, cat
            if best_cat and best_score > 0:
                try:
                    with open(_INTROS_FEMALE_PATH) as _ff:
                        _fem = json.load(_ff)
                    lines = _fem.get(best_cat, [])
                    if lines:
                        return _rr.choice(lines)
                except Exception as _exc:
                    _zyg_log.warning('female intro lines unreadable, falling back to the general set: %s', _exc)

        # General categories
        best_cat, best_score = None, 0
        for cat, kws in _INTRO_CATEGORY_KEYWORDS.items():
            sc = sum(1 for kw in kws if kw in _search)
            if sc > best_score:
                best_score, best_cat = sc, cat
        if best_cat and best_score > 0:
            try:
                with open(_INTROS_GENERAL_PATH) as _gf:
                    _gen = json.load(_gf)
                lines = _gen.get(best_cat, [])
                if lines:
                    return _rr.choice(lines)
            except Exception as _exc:
                _zyg_log.warning('general intro lines unreadable, using the built-in fallback intros: %s', _exc)
    except Exception as _exc:
        _zyg_log.warning('intro selection failed, using a built-in fallback intro: %s', _exc)
    return _rr.choice(_FALLBACK_INTROS)


def _get_narrator_voice(vid_id: str = '') -> tuple:
    """Return (voice_name, rate, pitch) for the channel that owns vid_id.
    Auto-assigns a voice to new channels and persists the choice.
    Falls back to a safe default if anything goes wrong."""
    _DEFAULT = ('en-US-ChristopherNeural', '+0%', '+0Hz')
    try:
        # Load voice library
        with open(_VOICE_LIBRARY_PATH) as _vf:
            _lib = json.load(_vf)
        voices = _lib.get('voices', {})

        # Load channel assignments
        with open(_CHANNEL_VOICES_PATH) as _cf:
            _ch_cfg = json.load(_cf)
        assignments = _ch_cfg.get('channels', {})

        # Map vid_id → channel_id using approved_clips state (populated at pipeline start)
        channel_id = _vid_to_channel_id.get(vid_id, '')

        if channel_id and channel_id in assignments:
            profile_id = assignments[channel_id].get('profile_id', '')
        else:
            # Auto-assign: try to find the channel in assignments by name fallback,
            # or assign default profile and persist it
            profile_id = _lib.get('auto_select_rules', {}).get('default', 'male_midage_authoritative')
            if channel_id and channel_id not in assignments:
                _auto_assign_voice(channel_id, profile_id, _ch_cfg)

        voice_entry = voices.get(profile_id, voices.get('male_midage_authoritative', {}))
        return (
            voice_entry.get('voice', _DEFAULT[0]),
            voice_entry.get('rate', _DEFAULT[1]),
            voice_entry.get('pitch', _DEFAULT[2]),
        )
    except Exception:
        return _DEFAULT


def _auto_assign_voice(channel_id: str, profile_id: str, existing_cfg: dict):
    """Persist a new channel→voice assignment. Thread-safe."""
    with _VOICE_LOCK:
        try:
            # Re-read in case another thread wrote since we loaded
            with open(_CHANNEL_VOICES_PATH) as _cf:
                _cfg = json.load(_cf)
            if channel_id not in _cfg.get('channels', {}):
                _cfg.setdefault('channels', {})[channel_id] = {
                    'channel_name': channel_id,
                    'profile_id': profile_id,
                    'assigned_at': 'auto',
                    'reason': 'Auto-assigned by pipeline (no manual override set)',
                }
                with open(_CHANNEL_VOICES_PATH, 'w') as _cf2:
                    json.dump(_cfg, _cf2, indent=2)
        except Exception as _exc:
            _zyg_log.warning(
                'auto-assigned voice for channel %s not persisted, it will be re-chosen next run: %s', channel_id, _exc
            )
