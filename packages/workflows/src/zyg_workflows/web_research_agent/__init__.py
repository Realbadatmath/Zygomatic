# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
WebResearchAgent — Full-depth browser research for crime pipeline Stage 2.

Browser waterfall (best → fallback):
  1. Playwright  — best anti-detection, supports Chrome/Firefox/WebKit
  2. Selenium    — fallback, uses undetected_chromedriver

Search engine waterfall (least CAPTCHA-prone first):
  1. DuckDuckGo  — HTML-only endpoint, rarely CAPTCHAs
  2. Bing        — independent index, separate CAPTCHA cycle
  3. Google      — most data but most aggressive CAPTCHA

Sources:
  - DuckDuckGo / Bing / Google Search + Google News
  - Wikipedia (full article + linked pages)
  - CourtListener
  - Justia case law
  - Internet Archive newspapers
  - Murderpedia / true crime archives

Returns structured research bundle with 15,000+ chars of source material.
"""

# web_research_agent.py became this package on 2026-10-07; every section moved verbatim.
# The import path is unchanged, and the original top import block is re-done here so
# attribute accesses like web_research_agent.random still resolve.
# ruff: noqa: E402,F401
import os
import re
import time
import random
import traceback
import threading
import logging as _zyg_logging

# Submodules in the original section order, so anything with a module-level side effect
# still runs in that order.
from zyg_workflows.web_research_agent import constants as constants
from zyg_workflows.web_research_agent import playwright_adapter as playwright_adapter
from zyg_workflows.web_research_agent import browser as browser
from zyg_workflows.web_research_agent import page_helpers as page_helpers
from zyg_workflows.web_research_agent import search_sources as search_sources
from zyg_workflows.web_research_agent import archive_sources as archive_sources
from zyg_workflows.web_research_agent import postprocess as postprocess
from zyg_workflows.web_research_agent import agent as agent
from zyg_workflows.web_research_agent.constants import (
    _CAPTCHA_SIGNALS,
    _COOKIE_BUTTON_TEXTS,
    _PAGE_LOAD_TIMEOUT,
    _PAYWALL_SIGNALS,
    _SOURCE_TIMEOUT,
    _USER_AGENTS,
    _after_load,
    _between_pages,
    _between_searches,
    _between_sites,
    _gauss_delay,
    _micro_pause,
    _reading_pause,
    _zyg_log,
)
from zyg_workflows.web_research_agent.playwright_adapter import _PlaywrightAdapter, _PlaywrightElement
from zyg_workflows.web_research_agent.browser import _BrowserSetupMixin
from zyg_workflows.web_research_agent.page_helpers import _PageHelpersMixin
from zyg_workflows.web_research_agent.search_sources import _SearchEngineSourcesMixin
from zyg_workflows.web_research_agent.archive_sources import _ArchiveSourcesMixin
from zyg_workflows.web_research_agent.postprocess import _PostProcessingMixin
from zyg_workflows.web_research_agent.agent import WebResearchAgent

from types import FunctionType as _FunctionType

# The class body was 1,076 lines in the original file. Its methods now live in mixin
# classes, one per original section banner, and are folded back onto the one and only
# WebResearchAgent here — so the assembled class has exactly the original MRO
# (WebResearchAgent, object) and exactly the original attributes.
WebResearchAgent.__module__ = __name__
for _mx in (
    _BrowserSetupMixin,
    _PageHelpersMixin,
    _SearchEngineSourcesMixin,
    _ArchiveSourcesMixin,
    _PostProcessingMixin,
):
    for _n, _v in vars(_mx).items():
        if _n.startswith('__') and _n.endswith('__'):
            continue
        setattr(WebResearchAgent, _n, _v)
for _n, _v in list(vars(WebResearchAgent).items()):
    if isinstance(_v, _FunctionType):
        _v.__module__ = __name__
        _v.__qualname__ = f'WebResearchAgent.{_n}'
del _mx, _n, _v


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys

    name = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else 'Ted Bundy'
    case = {
        'name': name,
        'case_title': f'{name} Trial',
        'state': 'Unknown',
        'year': '?',
        'court': 'Unknown',
        'crime_category': 'Serial Murder',
        'summary': '',
        'why_narrate': '',
    }

    def _print_log(level, stage, msg):
        print(f'[{level}] {stage}: {msg}')

    agent = WebResearchAgent(case=case, pipeline_id='test', log_fn=_print_log)
    result = agent.run()
    print('\n\n=== RESULT ===')
    print(f'Sources: {result["sources_used"]}')
    print(f'Total chars: {result["total_chars"]}')
    print(f'Timeline entries: {len(result["timeline"])}')
    print(f'Key people: {result["key_people"]}')
    print(f'\nFirst 2000 chars of raw_text:\n{result["raw_text"][:2000]}')
