# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tts_service.py — the original top import block, the voice seed pool re-exports and the engine-agnostic tables (lines 9-110 of the pre-split file, verbatim)."""

import json
import os
import re
import shutil
import subprocess
import time
from zyg_workflows import gui_state

# 2026-07-17 batch-2 fix: subproc helpers moved to subproc_registry (direct import —
# main's re-export binds too late for the engine import chain)
from zyg_workflows.subproc_registry import _register_subproc, _finish_subproc
from zyg_workflows.pipeline_config import (
    _DEMONET_TIER1,
    _DEMONET_TIER2,
    _DEMONET_TIER3_TITLE,
    _TITLE_SYNONYMS,
)


# ── voice seed pool ─────────────────────────────────────────────────────────
# Moved to voice_pool.py (2026-08-12) and re-imported here under the SAME private
# names, so every existing caller — including `_tts._voice_seed_for(...)` in
# briefing_video — keeps working unchanged.
#
# The move exists because this module imports Flask and crewai_web_gui at module
# scope, which made the pick unreachable from anything that is not the web app.
# The Voices tab has to answer "which seed does this character's voice id
# actually resolve to?" before it can show a connection, and a second copy of a
# gender-filtered md5 over a manifest is a silent-wrong-answer machine: both
# copies look right until the pool gains a seed. One implementation, two callers.
from zyg_workflows.voice_pool import (
    _SEED_POOL_DIR,
    _voice_seed_for,
)
import logging as _zyg_logging
from zyg_workflows import paths
from zyg_workflows.bin import exe

# The original top import block: these names are re-imported from here by the
# siblings that use them (shared, engines, asr, text), so they stay re-exports.
__all__ = [
    'json',
    'shutil',
    'subprocess',
    'time',
    'gui_state',
    '_register_subproc',
    '_finish_subproc',
    '_DEMONET_TIER1',
    '_DEMONET_TIER2',
    '_DEMONET_TIER3_TITLE',
    '_TITLE_SYNONYMS',
    '_SEED_POOL_DIR',
    '_voice_seed_for',
    'paths',
    'exe',
]

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.tts_service')


# ── text helpers (engine-agnostic) ──────────────────────────────────────────
_TTS_MAX_CHARS = int(os.environ.get('ZYG_TTS_MAX_CHARS', '350'))
# Both cloners render well below spoken-word platform norms; normalize the
# assembled file (run dd36662e measured -26.8 LUFS integrated pre-fix).
_TTS_LOUDNORM = os.environ.get('ZYG_TTS_LOUDNORM', 'I=-16:TP=-1.5:LRA=11')


# ── Roman numerals → spoken words ──────────────────────────────────────────
# Both cloners read "IV" as the letters "eye-vee". This expands the numeral for
# the VOICE ONLY — subtitles are written from pipeline_state['script'], which
# never passes through here, so "Pope Sixtus IV" stays "IV" on screen.
#
# The gate is CONTEXT, not the token. Measured over the scholarly scripts on
# disk, a bare token scan is almost all false positives: I ×197, C ×94, D ×73,
# L ×68, M ×65 — author initials ("B. Rojo-Garibaldi, C. Rangoni, D.L.
# González"), letter-spaced headers ("A R T I C L E I N F O"), and licence
# codes ("CC BY-NC-ND"). Every genuine numeral followed a spelled-out
# capitalised word: "Pope Sixtus IV", "Emperor Theodosius I", "World War II".
# So a numeral is only expanded when the preceding word is a real capitalised
# word of 3+ letters — which also excludes "D." and "C." initials, since those
# end in a period — and the value is in regnal/section range.
_ROMAN_VALUES = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
_ROMAN_CANON = re.compile(r'^(?=[MDCLXVI])M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$')
# Preceded by one of these, English uses a cardinal: "World War Two",
# "Chapter Four" — never "World War the second".
_ROMAN_CARDINAL_BEFORE = frozenset(
    'war wars chapter part book act volume section phase article appendix '
    'episode stage level type class group form mark'.split()
)
_ROMAN_MAX = 99  # regnal and section numerals; above this it is not a numeral

_ORD_UNITS = (
    'zeroth first second third fourth fifth sixth seventh eighth ninth '
    'tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth '
    'seventeenth eighteenth nineteenth'
).split()
_CARD_UNITS = (
    'zero one two three four five six seven eight nine ten eleven '
    'twelve thirteen fourteen fifteen sixteen seventeen eighteen '
    'nineteen'
).split()
_CARD_TENS = {
    20: 'twenty',
    30: 'thirty',
    40: 'forty',
    50: 'fifty',
    60: 'sixty',
    70: 'seventy',
    80: 'eighty',
    90: 'ninety',
}
_ORD_TENS = {
    20: 'twentieth',
    30: 'thirtieth',
    40: 'fortieth',
    50: 'fiftieth',
    60: 'sixtieth',
    70: 'seventieth',
    80: 'eightieth',
    90: 'ninetieth',
}
