# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""briefing_video.py — the shared "briefing episode" renderer behind Stockmarket,
Cryptodaily, TokiToki and Arena (2026-08-06).

Standalone: no crewai_web_gui import. matplotlib is imported lazily with the Agg
backend so importing this module never touches a display or a GPU.

EPISODE SHAPE (operator spec, identical for every channel)
  1. an opening BOARD chart, made locally, listing everything researched this
     episode, held on screen for `board_seconds` while the welcome line is spoken;
  2. then item by item — each item's own chart/photo on screen for exactly as long
     as its narration runs;
  3. the fixed outro line over an outro card.

CHAPTERS
`mm:ss Title` lines in description.txt are what YouTube turns into the segmented
playbar. YouTube's own rules are enforced here rather than hoped for: the first
chapter must be at 00:00, there must be at least three, and each must run at
least 10 s — `_build_chapters` pads or merges until all three hold, and the QC
gate fails the episode if they somehow do not.

WHY SEGMENT-PER-PANEL
Each panel gets its own TTS call and its own still, and the video is assembled by
concatenating per-panel clips that were all encoded with identical parameters
(`-c copy` concat). That means a panel is on screen for exactly the audio that
describes it — which is the whole "show their picture while speaking about them"
requirement — and it means one bad panel can be re-rendered without touching the
rest of the episode.
"""

from __future__ import annotations

# ruff: noqa: F401,E402  # this file is the re-export surface of the split
# module: every top-level name briefing_video.py defined is re-bound here, so no
# importer anywhere needs editing.  The submodules are imported in the original
# section order, so their module-level side effects still run in that order.

import sys as _sys
from types import ModuleType as _ModuleType

# An importlib reload of this package re-executes only this file; the submodules
# would be handed back from sys.modules unchanged, so a reload would no longer
# re-read the environment the way reloading the single briefing_video.py did.  Drop
# them first, so a reload really does re-execute every moved section.
for _m in [_m for _m in _sys.modules if _m.startswith(__name__ + '.')]:
    del _sys.modules[_m]

# base.py — top imports, themes, ffmpeg helpers, matplotlib scaffolding
from zyg_workflows.briefing_video.base import (
    FPS,
    H,
    THEMES,
    W,
    _AUDIO_ARGS,
    _CREWS,
    _FONT_BOLD,
    _NVENC_PROBE,
    _dur,
    _fig,
    _fit,
    _fit_px,
    _fit_px_auto,
    _header,
    _nvenc_available,
    _panel,
    _paste,
    _plt,
    _rule,
    _run,
    _save,
    _seal,
    _uniform_size,
    _vcodec,
    _wrap,
    _zyg_log,
    _zyg_logging,
    exe,
    json,
    os,
    re,
    shutil,
    subprocess,
    textwrap,
    theme,
    time,
)

# charts.py — chart 1 (the opening board) and chart 2 (the price chart)
from zyg_workflows.briefing_video.charts import (
    render_board,
    render_price_chart,
)

# cards.py — chart 3: the matchup card, the entity focus cards, the parlay sheet, the generic card
from zyg_workflows.briefing_video.cards import (
    _entity_block,
    _initials_disc,
    render_card,
    render_entity_focus,
    render_matchup,
    render_parlay_sheet,
)

# tts.py — TTS, the ASR read-back gate, speak_batch
from zyg_workflows.briefing_video.tts import (
    _ASR_NUM_WORDS,
    _asr_read_back_gate,
    _asr_similarity,
    _asr_tokens,
    _indextts_call,
    _slugkey,
    seed_path,
    speak,
    speak_batch,
)

# assemble.py — segment render + concat, chapters, the QC gate
from zyg_workflows.briefing_video.assemble import (
    _build_chapters,
    _concat,
    _ffmetadata,
    _loudnorm,
    _render_segment,
    _ts,
    qc,
)

# episode.py — render_episode and the retention sweep
from zyg_workflows.briefing_video.episode import (
    _SEAL_PIPELINE,
    render_episode,
    retention_sweep,
)

_SECTIONS = tuple(
    _sys.modules[f'{__name__}.{_m}']
    for _m in (
        'base',
        'charts',
        'cards',
        'tts',
        'assemble',
        'episode',
    )
)


class _SplitModule(_ModuleType):
    """briefing_video.py was ONE module, so `setattr(mod, name, value)` — pytest's
    monkeypatch, and the restore-after-call patching some callers do — rebound the
    single global every function read.  The readers are now sibling modules with
    their own globals, which a write to the package attribute would not reach, so
    the write is mirrored into every section whose namespace holds that name.
    """

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for _m in self.__dict__.get('_SECTIONS') or ():
            if name in _m.__dict__:
                _m.__dict__[name] = value

    def __delattr__(self, name):
        super().__delattr__(name)
        for _m in self.__dict__.get('_SECTIONS') or ():
            _m.__dict__.pop(name, None)


# last statement: from here on every attribute write to this package fans out
_sys.modules[__name__].__class__ = _SplitModule
