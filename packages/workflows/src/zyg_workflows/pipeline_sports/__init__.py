# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_sports.py — the TokiToki and Arena betting departments (2026-08-06).

Two channels × five sub-channels (MMA / Tennis / Soccer / Basketball / NFL), all
built by the same code path — operator spec: "all their subchannels need to be
build in the same way, then we can modify them a tiny bit later". The only things
that differ today are the board look and the voice, both of which are one settings
row each (`THEMES['tokitoki']` vs `THEMES['arena']`, `tokitoki_voice` vs
`arena_voice`), so "modify them a tiny bit later" stays a config change.

EPISODE (operator spec)
  opening board listing every selected match, held 5-10 s under
  "Welcome to <channel>, let's hop right in, our matches for today are: …"
  → one chapter per match, three panels each so the team or fighter being talked
    about is the one on screen:
        matchup card → the side we are backing → the other side / the risk
  → the fixed outro line.

D+2: every episode is built for the whole local calendar day two days out. See
sports_ingest.window_for.
"""

from __future__ import annotations

from zyg_workflows.pipeline_sports.constants import (
    ATTRIBUTION,
    BJ,
    BV,
    CHANNELS,
    DISCLAIMER,
    OUTRO_LINE,
    SI,
    _ROMAN_SPOKEN,
    _SPEAK_AS_WORD,
    _display_selection,
    _entity_label,
    _kickoff_local,
    _log,
    _re_sp,
    _speech_label,
    _speech_selection,
    _speech_sub,
    _speechify,
    _stage,
    datetime,
    os,
    shutil,
    threading,
    timezone,
    traceback,
)
from zyg_workflows.pipeline_sports.scripts import (
    _PCT_RE,
    _board_rows,
    _chapter_title,
    _display_leg,
    _facts_for,
    _form_facts,
    _form_score,
    _injury_facts,
    _nearest_team,
    _overview_script,
    _parlay_rows,
    _parlay_script,
    _pct_misattributions,
    _role_flip,
    _role_flips,
    _speech_final,
    _speech_leg,
    _team_variants,
    _template_scripts,
    _welcome_script,
    _write_scripts,
)
from zyg_workflows.pipeline_sports.pipeline import (
    _description_intro,
    _run,
    retention_sweep,
    start_episode,
)

# Re-export surface: every name below is imported above and not used in this
# module. Nothing does ``import *`` from here, so __all__ changes no behaviour;
# it declares the inherited namespace public so ruff does not read it as dead.
__all__ = [
    'ATTRIBUTION',
    'BJ',
    'BV',
    'CHANNELS',
    'DISCLAIMER',
    'OUTRO_LINE',
    'SI',
    '_ROMAN_SPOKEN',
    '_SPEAK_AS_WORD',
    '_display_selection',
    '_entity_label',
    '_kickoff_local',
    '_log',
    '_re_sp',
    '_speech_label',
    '_speech_selection',
    '_speech_sub',
    '_speechify',
    '_stage',
    'datetime',
    'os',
    'shutil',
    'threading',
    'timezone',
    'traceback',
    '_PCT_RE',
    '_board_rows',
    '_chapter_title',
    '_display_leg',
    '_facts_for',
    '_form_facts',
    '_form_score',
    '_injury_facts',
    '_nearest_team',
    '_overview_script',
    '_parlay_rows',
    '_parlay_script',
    '_pct_misattributions',
    '_role_flip',
    '_role_flips',
    '_speech_final',
    '_speech_leg',
    '_team_variants',
    '_template_scripts',
    '_welcome_script',
    '_write_scripts',
    '_description_intro',
    '_run',
    'retention_sweep',
    'start_episode',
]
