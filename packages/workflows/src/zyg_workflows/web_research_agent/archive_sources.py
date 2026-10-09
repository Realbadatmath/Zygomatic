# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging as _zyg_logging

from zyg_workflows.web_research_agent.constants import (
    _after_load,
    _between_pages,
    _between_sites,
    _reading_pause,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.web_research_agent')


class _ArchiveSourcesMixin:
    """Sources 3-7: Wikipedia, CourtListener, Justia, Internet Archive, true crime."""

    # ── Source 3: Wikipedia (full depth) ─────────────────────────────────────

    def _research_wikipedia(self):
        """Full Wikipedia article scrape including linked pages."""
        if self._shutdown or not self.driver:
            return
        self._log('INFO', '── Wikipedia starting')
        try:
            wiki_title = self.case_name.replace(' ', '_')
            url = f'https://en.wikipedia.org/wiki/{wiki_title}'

            if not self._safe_get(url):
                return

            _after_load()
            self._accept_cookies()

            # Check we landed on the right page
            if 'Wikipedia does not have an article' in self.driver.page_source:
                # Try search
                search_url = f'https://en.wikipedia.org/w/index.php?search={self.case_name.replace(" ", "+")}'
                self._safe_get(search_url)
                _after_load()

            # Scroll through full article
            self._human_scroll(6000, 15)
            _reading_pause()

            # Extract main article text (full, no char limit here)
            from selenium.webdriver.common.by import By

            full_text = ''
            try:
                content = self.driver.find_element(By.ID, 'mw-content-text')
                full_text = content.text
            except Exception:
                full_text = self._extract_body_text(20000)

            if full_text:
                self._add_text('wikipedia_main', full_text[:15000])

            # Extract section links to follow (trial, murder, conviction etc.)
            sub_links = []
            try:
                toc_links = self.driver.find_elements(By.CSS_SELECTOR, '#toc a, .toc a, .vector-toc a')
                for link in toc_links:
                    txt = link.text.lower()
                    if any(
                        kw in txt
                        for kw in [
                            'trial',
                            'murder',
                            'crime',
                            'arrest',
                            'conviction',
                            'sentenc',
                            'victim',
                            'evidence',
                            'verdict',
                            'appeal',
                            'execution',
                            'death',
                        ]
                    ):
                        href = link.get_attribute('href') or ''
                        if href:
                            sub_links.append(href)
            except Exception as _exc:
                _zyg_log.debug('reference-link scan failed, continuing without them: %s', _exc)

            # Follow internal Wikipedia links on the page — victims, co-defendants, etc.
            followed = 0
            try:
                body_links = self.driver.find_elements(By.CSS_SELECTOR, '#mw-content-text a[href^="/wiki/"]')
                candidate_links = []
                for link in body_links[:80]:
                    try:
                        href = link.get_attribute('href') or ''
                        txt = link.text.strip()
                        # Skip meta pages, files, categories
                        if (
                            href
                            and txt
                            and len(txt) > 3
                            and '/wiki/File:' not in href
                            and '/wiki/Category:' not in href
                            and '/wiki/Wikipedia:' not in href
                            and '/wiki/Help:' not in href
                            and '/wiki/Template:' not in href
                            and href not in [self.driver.current_url]
                        ):
                            # Prioritize links containing victim names, prosecutor names, etc.
                            candidate_links.append((href, txt))
                    except Exception as _exc:
                        _zyg_log.debug('one wikipedia link could not be inspected, skipping it: %s', _exc)

                # Follow up to 4 most relevant internal links
                for href, txt in candidate_links[:4]:
                    if followed >= 4:
                        break
                    try:
                        _between_pages()
                        self._safe_get(href)
                        _after_load()
                        self._human_scroll(2000, 6)
                        sub_text = self._extract_body_text(6000)
                        if sub_text and len(sub_text) > 300:
                            self._add_text('wikipedia_subpage', sub_text, label=txt[:40])
                            followed += 1
                    except Exception as _exc:
                        _zyg_log.debug('wikipedia subpage %s not harvested: %s', href, _exc)

            except Exception as e:
                self._log('WARNING', f'Wikipedia sub-links failed: {e}')

        except Exception as e:
            self._log('WARNING', f'Wikipedia failed: {e}')

    # ── Source 4: CourtListener ───────────────────────────────────────────────

    def _research_courtlistener(self):
        """Search CourtListener for actual case opinions and docket entries."""
        if self._shutdown or not self.driver:
            return
        self._log('INFO', '── CourtListener starting')
        try:
            query = self.case_name.replace(' ', '+')
            url = f'https://www.courtlistener.com/?q={query}&type=o&order_by=score+desc'

            if not self._safe_get(url):
                return

            _after_load()
            self._accept_cookies()
            self._human_scroll(1500, 5)

            # Get result links
            from selenium.webdriver.common.by import By

            result_links = self._get_links('h3 a, .case-name a, td.name a', limit=5)

            visited = 0
            for href, title in result_links:
                if visited >= 3:
                    break
                try:
                    _between_pages()
                    if not self._safe_get(href):
                        continue
                    _after_load()
                    self._human_scroll(3000, 10)

                    # CourtListener shows full opinion text
                    text = ''
                    try:
                        opinion_el = self.driver.find_element(By.ID, 'opinion-content')
                        text = opinion_el.text
                    except Exception:
                        text = self._extract_body_text(10000)

                    if text and len(text) > 300:
                        self._add_text('courtlistener', text[:10000], label=title[:50])
                        visited += 1
                except Exception as e:
                    self._log('WARNING', f'CourtListener result failed: {e}')

        except Exception as e:
            self._log('WARNING', f'CourtListener failed: {e}')

    # ── Source 5: Justia case law ─────────────────────────────────────────────

    def _research_justia(self):
        """Search Justia for case law and legal summaries."""
        if self._shutdown or not self.driver:
            return
        self._log('INFO', '── Justia starting')
        try:
            query = self.case_name.replace(' ', '+')
            url = f'https://law.justia.com/cases/?q={query}'

            if not self._safe_get(url):
                return

            _after_load()
            self._accept_cookies()
            self._human_scroll(1500, 5)

            result_links = self._get_links('h2 a, h3 a, .case-name a', limit=4)

            visited = 0
            for href, title in result_links:
                if visited >= 2:
                    break
                try:
                    _between_pages()
                    if not self._safe_get(href):
                        continue
                    _after_load()
                    self._human_scroll(2500, 8)
                    text = self._extract_body_text(8000)
                    if text and len(text) > 300:
                        self._add_text('justia', text, label=title[:50])
                        visited += 1
                except Exception as e:
                    self._log('WARNING', f'Justia result failed: {e}')

        except Exception as e:
            self._log('WARNING', f'Justia failed: {e}')

    # ── Source 6: Internet Archive newspaper search ───────────────────────────

    def _research_archive_newspapers(self):
        """Search Internet Archive for contemporary newspaper coverage."""
        if self._shutdown or not self.driver:
            return
        self._log('INFO', '── Archive.org newspapers starting')
        try:
            query = self.case_name.replace(' ', '+')
            url = f'https://archive.org/search?query={query}+trial&and[]=mediatype%3Atexts&and[]=subject%3A%22newspaper%22'

            if not self._safe_get(url):
                return

            _after_load()
            self._human_scroll(1000, 4)

            result_links = self._get_links('.item-ia a[href^="/details/"]', limit=6)

            visited = 0
            for href, title in result_links:
                if visited >= 2:
                    break
                try:
                    _between_pages()
                    full_url = f'https://archive.org{href}' if href.startswith('/') else href
                    if not self._safe_get(full_url):
                        continue
                    _after_load()
                    self._human_scroll(1500, 5)
                    text = self._extract_body_text(5000)
                    if text and len(text) > 300:
                        self._add_text('archive_newspapers', text, label=title[:50])
                        visited += 1
                except Exception as e:
                    self._log('WARNING', f'Archive.org item failed: {e}')

        except Exception as e:
            self._log('WARNING', f'Archive.org failed: {e}')

    # ── Source 7: Murderpedia / true crime archives ───────────────────────────

    def _research_true_crime_archives(self):
        """Murderpedia and similar public-record true crime archives."""
        if self._shutdown or not self.driver:
            return
        self._log('INFO', '── True crime archives starting')

        # Murderpedia
        try:
            last_name = self.case_name.split()[-1].lower()
            url = f'https://murderpedia.org/male.{last_name[0].upper()}/{last_name[0]}/{last_name}.htm'
            if self._safe_get(url):
                _after_load()
                if '404' not in self.driver.title.lower() and self.last_name_in_page():
                    self._human_scroll(3000, 10)
                    text = self._extract_body_text(8000)
                    if text and len(text) > 400:
                        self._add_text('murderpedia', text)
                    else:
                        # Try search
                        search_url = f'https://murderpedia.org/search.htm#q={self.case_name.replace(" ", "+")}'
                        if self._safe_get(search_url):
                            _after_load()
                            self._human_scroll(1000, 4)
                            text = self._extract_body_text(5000)
                            if text and len(text) > 300:
                                self._add_text('murderpedia', text)
        except Exception as e:
            self._log('WARNING', f'Murderpedia failed: {e}')

        # Oyez.org (Supreme Court only — still worth a check)
        try:
            _between_sites()
            query = self.case_name.replace(' ', '%20')
            url = f'https://www.oyez.org/cases?filter={query}'
            if self._safe_get(url):
                _after_load()
                self._human_scroll(1000, 4)
                text = self._extract_body_text(5000)
                if text and len(text) > 300 and self.case_name.split()[-1].lower() in text.lower():
                    self._add_text('oyez', text)
        except Exception as e:
            self._log('WARNING', f'Oyez failed: {e}')

        # Criminalminds / crimelibrary via Wayback Machine
        try:
            _between_sites()
            query = self.case_name.replace(' ', '+')
            url = f'https://web.archive.org/web/*/http://www.crimelibrary.com/notorious_murders/*{query}*'
            if self._safe_get(url):
                _after_load()
                self._human_scroll(1000, 4)
                links = self._get_links('a.result-url', limit=4)
                for href, title in links[:2]:
                    try:
                        _between_pages()
                        self._safe_get(href)
                        _after_load()
                        self._human_scroll(2000, 6)
                        text = self._extract_body_text(6000)
                        if text and len(text) > 400:
                            self._add_text('crimelibrary_archive', text, label=title[:40])
                    except Exception as _exc:
                        _zyg_log.debug('archive page %s not harvested: %s', href, _exc)
        except Exception as e:
            self._log('WARNING', f'CrimeLibrary archive failed: {e}')

    def last_name_in_page(self):
        """Quick check if the person's last name appears on current page."""
        last = self.case_name.split()[-1].lower()
        return last in self.driver.page_source.lower()
