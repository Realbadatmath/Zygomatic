# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging as _zyg_logging
import random
import re
import time

from zyg_workflows.web_research_agent.constants import (
    _after_load,
    _between_pages,
    _between_searches,
    _micro_pause,
    _reading_pause,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.web_research_agent')


class _SearchEngineSourcesMixin:
    """Sources 1-2: Google, DuckDuckGo, Bing and Google News, moved verbatim."""

    # ── Source 1: Google Search ───────────────────────────────────────────────

    def _research_google(self):
        """Search Google and visit top organic results."""
        if self._shutdown or not self.driver:
            return
        self._log('INFO', '── Google Search starting')
        queries = [
            f'"{self.case_name}" trial verdict',
            f'"{self.case_name}" evidence testimony witnesses',
            f'"{self.case_name}" crime case history',
        ]

        visited_domains = set()

        for qi, query in enumerate(queries):
            try:
                if qi > 0:
                    _between_searches()

                from selenium.webdriver.common.by import By
                from selenium.webdriver.common.keys import Keys
                from selenium.webdriver.support.ui import WebDriverWait
                from selenium.webdriver.support import expected_conditions as EC
                import urllib.parse as _up_g

                # Strategy 1: URL-based search — bypasses search box entirely,
                # no interactability issues, no consent wall blocking input.
                _encoded = _up_g.quote(query)
                _search_url = f'https://www.google.com/search?q={_encoded}&hl=en&gl=us'
                if not self._safe_get(_search_url):
                    continue

                _after_load()
                self._accept_cookies()
                _micro_pause()

                if self._detect_captcha():
                    self._log('WARNING', 'Google CAPTCHA detected — skipping query')
                    time.sleep(max(5.0, random.gauss(45, 10)))
                    continue

                # Extract organic result links (skip ads, videos, maps)
                result_links = []
                try:
                    results = self.driver.find_elements(By.CSS_SELECTOR, 'div.g a[href]')
                    for el in results:
                        href = el.get_attribute('href') or ''
                        if (
                            href.startswith('http')
                            and 'google.com' not in href
                            and 'youtube.com' not in href
                            and 'facebook.com' not in href
                            and 'twitter.com' not in href
                            and 'instagram.com' not in href
                        ):
                            domain = re.sub(r'https?://(www\.)?', '', href).split('/')[0]
                            if domain not in visited_domains:
                                result_links.append((href, domain))
                except Exception as _exc:
                    _zyg_log.debug('google result scan failed, falling back to the search box: %s', _exc)

                # If URL search gave no results (rare — consent redirect),
                # fall back to typing in the search box with explicit wait.
                if not result_links:
                    try:
                        self._safe_get('https://www.google.com')
                        _after_load()
                        self._accept_cookies()
                        box = WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((By.NAME, 'q')))
                        self._human_type(box, query)
                        time.sleep(max(0.1, random.gauss(0.8, 0.2)))
                        box.send_keys(Keys.RETURN)
                        _after_load()
                        results = self.driver.find_elements(By.CSS_SELECTOR, 'div.g a[href]')
                        for el in results:
                            href = el.get_attribute('href') or ''
                            if href.startswith('http') and 'google.com' not in href:
                                domain = re.sub(r'https?://(www\.)?', '', href).split('/')[0]
                                if domain not in visited_domains:
                                    result_links.append((href, domain))
                    except Exception as _fb_e:
                        self._log('WARNING', f'Google fallback search failed: {_fb_e}')

                self._log('INFO', f'Google query {qi + 1}: {len(result_links)} links found')

                # Visit top 4 unique results per query
                visited_this_query = 0
                for url, domain in result_links:
                    if visited_this_query >= 4:
                        break
                    try:
                        _between_pages()
                        if not self._safe_get(url):
                            continue
                        self._accept_cookies()
                        _reading_pause()

                        if self._detect_captcha():
                            self._log('WARNING', f'CAPTCHA on {domain} — skipping')
                            continue
                        if self._detect_paywall():
                            self._log('INFO', f'Paywall on {domain} — skipping')
                            continue

                        self._human_scroll(1800, 6)
                        text = self._extract_body_text(8000)
                        if text and len(text) > 400:
                            self._add_text('google', text, label=domain)
                            visited_domains.add(domain)
                            visited_this_query += 1
                    except Exception as e:
                        self._log('WARNING', f'Failed visiting {domain}: {e}')

            except Exception as e:
                self._log('WARNING', f'Google query {qi + 1} failed: {e}')

    # ── Source 1b: DuckDuckGo (CAPTCHA-resistant fallback for Google) ─────────

    def _research_duckduckgo(self):
        """Search DuckDuckGo HTML interface — no JS required, CAPTCHA-resistant."""
        if self._shutdown or not self.driver:
            return
        self._log('INFO', '── DuckDuckGo Search starting')
        from selenium.webdriver.common.by import By
        import urllib.parse as _up_ddg

        queries = [
            f'{self.case_name} trial verdict evidence',
            f'{self.case_name} crime case history',
        ]
        visited_domains: set = set()
        for query in queries:
            try:
                if self._shutdown:
                    break
                _encoded = _up_ddg.quote(query)
                url = f'https://html.duckduckgo.com/html/?q={_encoded}'
                if not self._safe_get(url):
                    continue
                _after_load()
                result_links = []
                try:
                    for el in self.driver.find_elements(By.CSS_SELECTOR, 'a.result__a'):
                        href = el.get_attribute('href') or ''
                        if href.startswith('http') and 'duckduckgo.com' not in href:
                            domain = re.sub(r'https?://(www\.)?', '', href).split('/')[0]
                            if domain not in visited_domains:
                                result_links.append((href, domain))
                except Exception as _exc:
                    _zyg_log.debug('duckduckgo result scan failed, no links from this query: %s', _exc)
                for url, domain in result_links[:4]:
                    try:
                        _between_pages()
                        if not self._safe_get(url):
                            continue
                        self._accept_cookies()
                        _reading_pause()
                        if self._detect_captcha() or self._detect_paywall():
                            continue
                        self._human_scroll(1800, 6)
                        text = self._extract_body_text(8000)
                        if text and len(text) > 400:
                            self._add_text('duckduckgo', text, label=domain)
                            visited_domains.add(domain)
                    except Exception as e:
                        self._log('WARNING', f'DuckDuckGo: failed visiting {domain}: {e}')
                _between_searches()
            except Exception as e:
                self._log('WARNING', f'DuckDuckGo query failed: {e}')

    # ── Source 1c: Bing (secondary fallback) ──────────────────────────────────

    def _research_bing(self):
        """Search Bing — less aggressive CAPTCHA than Google."""
        if self._shutdown or not self.driver:
            return
        self._log('INFO', '── Bing Search starting')
        from selenium.webdriver.common.by import By
        import urllib.parse as _up_bing

        queries = [
            f'{self.case_name} crime trial verdict',
            f'{self.case_name} arrest evidence conviction',
        ]
        visited_domains: set = set()
        for query in queries:
            try:
                if self._shutdown:
                    break
                _encoded = _up_bing.quote(query)
                url = f'https://www.bing.com/search?q={_encoded}&setlang=en'
                if not self._safe_get(url):
                    continue
                _after_load()
                result_links = []
                try:
                    for el in self.driver.find_elements(By.CSS_SELECTOR, 'li.b_algo h2 a, .b_algo .b_title a'):
                        href = el.get_attribute('href') or ''
                        if href.startswith('http') and 'bing.com' not in href and 'microsoft.com' not in href:
                            domain = re.sub(r'https?://(www\.)?', '', href).split('/')[0]
                            if domain not in visited_domains:
                                result_links.append((href, domain))
                except Exception as _exc:
                    _zyg_log.debug('bing result scan failed, no links from this query: %s', _exc)
                for url, domain in result_links[:4]:
                    try:
                        _between_pages()
                        if not self._safe_get(url):
                            continue
                        self._accept_cookies()
                        _reading_pause()
                        if self._detect_captcha() or self._detect_paywall():
                            continue
                        self._human_scroll(1800, 6)
                        text = self._extract_body_text(8000)
                        if text and len(text) > 400:
                            self._add_text('bing', text, label=domain)
                            visited_domains.add(domain)
                    except Exception as e:
                        self._log('WARNING', f'Bing: failed visiting {domain}: {e}')
                _between_searches()
            except Exception as e:
                self._log('WARNING', f'Bing query failed: {e}')

    # ── Source 2: Google News ─────────────────────────────────────────────────

    def _research_google_news(self):
        """Search Google News for timeline coverage."""
        if self._shutdown or not self.driver:
            return
        self._log('INFO', '── Google News starting')
        try:
            query = f'{self.case_name} trial arrest verdict sentencing'
            url = f'https://news.google.com/search?q={query.replace(" ", "+")}&hl=en-US&gl=US&ceid=US:en'

            if not self._safe_get(url):
                return

            _after_load()
            self._accept_cookies()
            self._human_scroll(2000, 8)
            _reading_pause()

            if self._detect_captcha():
                self._log('WARNING', 'Google News CAPTCHA — skipping')
                return

            # Extract article titles and snippets
            from selenium.webdriver.common.by import By

            articles = self.driver.find_elements(By.CSS_SELECTOR, 'article')
            news_text = []
            for art in articles[:20]:
                try:
                    txt = art.text.strip()
                    if len(txt) > 50:
                        news_text.append(txt)
                except Exception as _exc:
                    _zyg_log.debug('one news article could not be read, skipping it: %s', _exc)

            if news_text:
                combined = '\n\n'.join(news_text[:15])
                self._add_text('google_news', combined)

            # Also visit top 3 news articles directly
            news_links = self._get_links('article a[href]', limit=6)
            visited = 0
            for href, title in news_links:
                if visited >= 3:
                    break
                try:
                    _between_pages()
                    # Google News wraps URLs — follow redirect
                    if 'news.google.com/articles' in href or 'news.google.com/rss' in href:
                        self._safe_get(href)
                        # Wait for redirect
                        time.sleep(3)
                        href = self.driver.current_url

                    if not self._safe_get(href):
                        continue
                    self._accept_cookies()
                    if self._detect_paywall():
                        continue
                    self._human_scroll(1500, 5)
                    text = self._extract_body_text(6000)
                    if text and len(text) > 300:
                        self._add_text('google_news_article', text, label=title[:40])
                        visited += 1
                except Exception as e:
                    self._log('WARNING', f'News article failed: {e}')

        except Exception as e:
            self._log('WARNING', f'Google News failed: {e}')
