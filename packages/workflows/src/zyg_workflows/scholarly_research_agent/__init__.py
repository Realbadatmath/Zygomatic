# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
ScholarlyResearchAgent — Stage 2 replacement for the Scholarly pipeline.

API-first architecture: OpenAlex → Semantic Scholar → CORE (no browser needed).
Postgres (the shared `essays` table) caches results to avoid redundant API calls.
Falls back to browser scraping if all APIs return 0 results.
"""

from types import FunctionType as _FunctionType

from zyg_workflows.scholarly_research_agent import constants as _m_constants
from zyg_workflows.scholarly_research_agent.constants import (
    os,
    re,
    time,
    random,
    pgdb,
    contact_email,
    dict_row,
    _up,
    _ur,
    _hj,
    _USER_AGENTS,
    _PlaywrightAdapter,
    _PAGE_LOAD_TIMEOUT,
    _between_pages,
    _between_sites,
    _VF_RESOLVER,
    _zyg_logging,
    _zyg_log,
    _AGENT_DIR,
    _DATA_DIR,
    _IMG_BASE,
    _BROWSER_SANDBOX_BASE,
    _sb_fetch,
    _sb_search,
    _TOPIC_DISCIPLINES,
    _TOPIC_QUERIES,
)
from zyg_workflows.scholarly_research_agent.directive import (
    _DIRECTIVE_NOISE_WORDS,
    _extract_keywords,
    _claude_extract_subject,
)
from zyg_workflows.scholarly_research_agent.core import ScholarlyResearchAgent
from zyg_workflows.scholarly_research_agent.sources import _SourcesMixin
from zyg_workflows.scholarly_research_agent.extraction import _ExtractionMixin
from zyg_workflows.scholarly_research_agent.legacy_sources import _LegacySourcesMixin
from zyg_workflows.scholarly_research_agent.run import _RunMixin
from zyg_workflows.scholarly_research_agent.web_content import _WebContentMixin

# ── re-export surface ────────────────────────────────────────────────────────
# Every name above that this file does not itself use, in import order: they are
# read OFF the package by callers that still say
# ``from zyg_workflows.scholarly_research_agent import ScholarlyResearchAgent, os, …``
# or reach them as attributes, exactly as they could on the pre-split module.
# Declaring them is what makes the re-export deliberate rather than an unused
# import; nothing does ``import *`` from here, so __all__ changes no behaviour.
__all__ = [
    'os',
    're',
    'time',
    'random',
    'pgdb',
    'contact_email',
    'dict_row',
    '_up',
    '_ur',
    '_hj',
    '_USER_AGENTS',
    '_PlaywrightAdapter',
    '_PAGE_LOAD_TIMEOUT',
    '_between_pages',
    '_between_sites',
    '_VF_RESOLVER',
    '_zyg_logging',
    '_zyg_log',
    '_AGENT_DIR',
    '_DATA_DIR',
    '_IMG_BASE',
    '_BROWSER_SANDBOX_BASE',
    '_sb_fetch',
    '_sb_search',
    '_TOPIC_DISCIPLINES',
    '_TOPIC_QUERIES',
    '_DIRECTIVE_NOISE_WORDS',
    '_extract_keywords',
    '_claude_extract_subject',
    'ScholarlyResearchAgent',
]

# `_VisualFrameworkResolver` is bound only when the optional import succeeded — in the
# original single-file module it was a soft, possibly-absent attribute. Keep it that way.
if hasattr(_m_constants, '_VisualFrameworkResolver'):
    _VisualFrameworkResolver = _m_constants._VisualFrameworkResolver

# The class body was 2,172 lines in the original file. Its methods now live in mixin
# classes, one per original section banner, and are folded back onto the one and only
# ScholarlyResearchAgent here — so the assembled class has exactly the original MRO
# (ScholarlyResearchAgent, object) and exactly the original attributes.
ScholarlyResearchAgent.__module__ = __name__
for _mx in (
    _SourcesMixin,
    _ExtractionMixin,
    _LegacySourcesMixin,
    _RunMixin,
    _WebContentMixin,
):
    for _n, _v in vars(_mx).items():
        if _n.startswith('__') and _n.endswith('__'):
            continue
        setattr(ScholarlyResearchAgent, _n, _v)
for _n, _v in list(vars(ScholarlyResearchAgent).items()):
    if isinstance(_v, _FunctionType):
        _v.__module__ = __name__
        _v.__qualname__ = f'ScholarlyResearchAgent.{_n}'
del _mx, _n, _v
