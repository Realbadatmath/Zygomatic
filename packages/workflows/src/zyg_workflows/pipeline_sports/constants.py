# ruff: noqa: F401  the original module's top import block lives here; siblings re-import from it
# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The original top import block, the channel/copy constants, the job-log
helpers and the spoken-name transform (verbatim from pipeline_sports.py)."""

from __future__ import annotations

import os
import shutil
import threading
import traceback
import re as _re_sp
from datetime import datetime, timezone

from zyg_workflows import briefing_jobs as BJ
from zyg_workflows import briefing_video as BV
from zyg_workflows import sports_ingest as SI

CHANNELS = {
    'tokitoki': {'label': 'TokiToki', 'theme': 'tokitoki', 'voice_key': 'tokitoki_voice'},
    'arena': {'label': 'Arena', 'theme': 'arena', 'voice_key': 'arena_voice'},
}

OUTRO_LINE = (
    'Feel free to join our telegram, there we share free betting tips as '
    'well. Please like and subscribe, see you next time.'
)

DISCLAIMER = (
    'DISCLAIMER: 18+ only. This is entertainment and analysis, not a '
    'guarantee of any outcome. Odds shown were the best available at the '
    'time of recording and will have moved — always check your own '
    'bookmaker before placing anything. Never stake money you cannot '
    'afford to lose. Gambling can be addictive; if it stops being fun, '
    'stop. Help: begambleaware.org'
)

ATTRIBUTION = (
    'Odds data: The Odds API. Team badges and player artwork: '
    'TheSportsDB (thesportsdb.com) — used unmodified. '
    'Charts rendered locally.'
)


def _log(pid, level, stage, msg):
    BJ.log(pid, level, stage, msg, tag='SPORTS')


def _stage(pid, stage, pct=None):
    BJ.update_stage(pid, stage, pct, tag='SPORTS')


def _kickoff_local(bet) -> str:
    try:
        dt = datetime.strptime((bet.get('commence_time') or '')[:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
        return dt.astimezone(SI._LOCAL_TZ).strftime('%a %-d %b %H:%M')
    except Exception:
        return ''


def _entity_label(bet, side) -> str:
    ent = bet.get(f'{side}_entity') or {}
    return ent.get('display') or bet.get(side) or ''


# ── spoken names (2026-08-07) ───────────────────────────────────────────────
# The first episode's audio called SC Telstar "a South Carolina team" (the
# cloner expanded the raw odds-API prefix "SC") and mangled "NEC" on its first
# mention into a club that does not exist. Narration therefore speaks CLEANED
# names: the TheSportsDB display form ("Telstar", "Tigre"), trailing Roman
# numerals as numbers, and short ALL-CAPS abbreviations letter-spaced so the
# engine spells them instead of inventing a word. Boards, panels and chapter
# titles keep the official spelling — this transform is for the voice only.

_ROMAN_SPOKEN = {'II': 'two', 'III': 'three', 'IV': 'four'}
_SPEAK_AS_WORD = {'ADO'}  # pronounced as a word, not spelled


def _speechify(name: str) -> str:
    parts = (name or '').split()
    out = []
    for i, w in enumerate(parts):
        if w in _ROMAN_SPOKEN and i == len(parts) - 1:
            out.append(_ROMAN_SPOKEN[w])
        elif w.isupper() and w.isalpha() and 2 <= len(w) <= 3 and w not in _SPEAK_AS_WORD:
            out.append(' '.join(w))
        else:
            out.append(w)
    return ' '.join(out)


def _speech_label(bet, side) -> str:
    return _speechify(_entity_label(bet, side))


def _display_selection(bet) -> str:
    """Selection under its display name (screen text): 'SC Telstar' → 'Telstar'."""
    sel = bet.get('selection') or ''
    if sel == bet.get('home'):
        return _entity_label(bet, 'home')
    if sel == bet.get('away'):
        return _entity_label(bet, 'away')
    return sel


def _speech_selection(bet) -> str:
    sel = bet.get('selection') or ''
    if sel == bet.get('home'):
        return _speech_label(bet, 'home')
    if sel == bet.get('away'):
        return _speech_label(bet, 'away')
    return sel  # 'Draw'


def _speech_sub(bet, text: str) -> str:
    """Swap raw odds-API team names inside a measured driver for spoken forms."""
    for side in ('home', 'away'):
        raw = bet.get(side) or ''
        if raw and raw in (text or ''):
            text = text.replace(raw, _speech_label(bet, side))
    return text
