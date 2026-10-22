# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging as _zyg_logging
import random
import threading
import time
import traceback

from zyg_workflows.web_research_agent.constants import _SOURCE_TIMEOUT, _USER_AGENTS, _between_sites

_zyg_log = _zyg_logging.getLogger('zyg_workflows.web_research_agent')

# ── Main agent class ──────────────────────────────────────────────────────────


class WebResearchAgent:
    """
    Browser research agent. Tries Playwright first (best anti-detection),
    falls back to Selenium (undetected_chromedriver).
    Search engines: DuckDuckGo → Bing → Google (least to most CAPTCHA-prone).
    Returns structured research bundle for the crime narration pipeline.
    """

    def __init__(self, case: dict, pipeline_id: str = '', log_fn=None, stop_event=None):
        self.case = case
        self.case_name = case.get('name', 'Unknown')
        self.pipeline_id = pipeline_id
        self._log_fn = log_fn or (lambda level, stage, msg: _zyg_log.info(f'[{level}] {stage}: {msg}'))
        self.driver = None
        self._browser_engine = None  # 'playwright' | 'selenium'
        self._shutdown = False  # set True when teardown begins; threads check this
        self._stop_event = stop_event  # threading.Event — set by pipeline stop/emergency stop
        self._ua = random.choice(_USER_AGENTS)
        self._display = None  # Xvfb handle if needed
        self._texts = []  # accumulated text blocks
        self._timeline = []  # {date, event}
        self._key_people = {'prosecutors': [], 'defense': [], 'judges': [], 'victims': [], 'other': []}
        self._sources_used = []

    def _is_stopped(self):
        """Return True if the pipeline stop flag has been set externally."""
        return self._shutdown or (self._stop_event is not None and self._stop_event.is_set())

    def _log(self, level, msg):
        self._log_fn(level, 'Stage 2 / Browser', msg)

    # ── Main run ──────────────────────────────────────────────────────────────

    def run(self) -> dict:
        """
        Launch browser, run all sources with timeouts, compile and return
        structured research bundle.
        """
        start_time = time.time()
        self._log('INFO', f'Starting full-depth research for: {self.case_name}')

        # Source pipeline — each wrapped in timeout thread
        sources = [
            ('Google Search', self._research_google),
            ('DuckDuckGo Search', self._research_duckduckgo),
            ('Bing Search', self._research_bing),
            ('Google News', self._research_google_news),
            ('Wikipedia', self._research_wikipedia),
            ('CourtListener', self._research_courtlistener),
            ('Justia', self._research_justia),
            ('Archive.org Newspapers', self._research_archive_newspapers),
            ('True Crime Archives', self._research_true_crime_archives),
        ]

        try:
            self._setup_browser()
            self._log('INFO', f'Browser engine: {self._browser_engine}')

            for source_name, source_fn in sources:
                # Check stop before every source
                if self._is_stopped():
                    self._log('WARNING', 'Stop signal received — aborting research')
                    break
                self._log('INFO', f'▶ {source_name}')
                try:
                    if self._browser_engine == 'playwright':
                        # Playwright sync API is greenlet-bound — must NOT cross threads.
                        # Its internal page timeout already limits hung operations.
                        source_fn()
                        self._sources_used.append(source_name)
                    else:
                        # Selenium is thread-safe; use threading for per-source timeout.
                        t = threading.Thread(target=source_fn, daemon=True)
                        t.start()
                        t.join(timeout=_SOURCE_TIMEOUT)
                        if t.is_alive():
                            self._log('WARNING', f'{source_name}: timeout ({_SOURCE_TIMEOUT}s) — moving on')
                        else:
                            self._sources_used.append(source_name)
                except Exception as e:
                    self._log('WARNING', f'{source_name} crashed: {e}\n{traceback.format_exc()[-300:]}')

                _between_sites()

        except Exception as e:
            self._log('WARNING', f'Browser session error: {e}')
        finally:
            self._teardown_browser()

        # Compile all text
        combined = '\n'.join(self._texts)
        total_chars = len(combined)
        elapsed = round(time.time() - start_time, 1)

        self._log(
            'INFO', f'Research complete: {total_chars} chars from {len(self._sources_used)} sources in {elapsed}s'
        )

        # Build structured output
        timeline = self._extract_timeline(combined)
        key_people = self._extract_key_people(combined)

        # Build the raw_text for the LLM — structured so Stage 3 uses it well
        raw_sections = []
        case = self.case
        raw_sections.append(
            f'CASE: {case.get("case_title", self.case_name)}\n'
            f'STATE: {case.get("state", "?")} | YEAR: {case.get("year", "?")} | '
            f'COURT: {case.get("court", "?")}\n'
            f'CRIME CATEGORY: {case.get("crime_category", "?")}\n'
            f'CASE SUMMARY: {case.get("summary", "")}\n'
        )
        if timeline:
            raw_sections.append('TIMELINE:\n' + '\n'.join(f'  {t["date"]}: {t["event"]}' for t in timeline[:25]))
        if any(key_people.values()):
            raw_sections.append(
                'KEY PEOPLE:\n'
                + '\n'.join(f'  {role.upper()}: {", ".join(names)}' for role, names in key_people.items() if names)
            )
        raw_sections.append(combined[:20000])  # cap at 20k chars to not overwhelm LLM

        result = {
            'case_name': self.case_name,
            'sources_used': self._sources_used,
            'total_chars': total_chars,
            'elapsed_s': elapsed,
            'timeline': timeline,
            'key_people': key_people,
            'raw_text': '\n\n'.join(raw_sections),
        }

        return result
