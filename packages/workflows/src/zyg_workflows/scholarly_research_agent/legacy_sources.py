# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Legacy browser-scraping repository sources (fallback only)."""

from zyg_workflows.scholarly_research_agent.constants import (
    _between_pages,
    _sb_fetch,
    _up,
)


class _LegacySourcesMixin:
    # ── Legacy browser-based sources (kept as fallback) ───────────────────────

    def _research_bepress(self):
        try:
            for discipline in self._disciplines[:2]:
                if self._is_stopped():
                    return
                url = f'https://network.bepress.com/{discipline}/'
                result = _sb_fetch(url)
                if not result or not result.get('ok'):
                    continue
                links = [l for l in result.get('links', []) if 'viewcontent' in l][:3]
                for href in links:
                    if self._is_stopped():
                        return
                    page = _sb_fetch(href)
                    if page and page.get('text') and len(page['text']) > 500:
                        self._add_text('Digital Commons (Bepress)', page['text'], href[:60])
                    _between_pages()
        except Exception as e:
            self._log('WARNING', f'Bepress scrape failed: {e}')

    def _research_core(self):
        try:
            for query in self._queries[:2]:
                if self._is_stopped():
                    return
                url = f'https://core.ac.uk/search?q={_up.quote(query)}'
                result = _sb_fetch(url)
                if not result or not result.get('ok'):
                    continue
                links = [l for l in result.get('links', []) if '/works/' in l][:3]
                for href in links:
                    if self._is_stopped():
                        return
                    page = _sb_fetch(href)
                    if page and page.get('text') and len(page['text']) > 500:
                        self._add_text('CORE', page['text'], href[:60])
                    _between_pages()
        except Exception as e:
            self._log('WARNING', f'CORE browser scrape failed: {e}')

    def _research_ssrn(self):
        try:
            for query in self._queries[:1]:
                if self._is_stopped():
                    return
                url = f'https://papers.ssrn.com/sol3/results.cfm?txtWords={_up.quote(query)}'
                result = _sb_fetch(url)
                if not result or not result.get('ok'):
                    continue
                links = [l for l in result.get('links', []) if '/abstract=' in l or '/sol3/papers.cfm' in l][:3]
                for href in links:
                    if self._is_stopped():
                        return
                    page = _sb_fetch(href)
                    if page and page.get('text') and len(page['text']) > 200:
                        self._add_text('SSRN', page['text'], href[:60])
                    _between_pages()
        except Exception as e:
            self._log('WARNING', f'SSRN scrape failed: {e}')

    def _research_dspace(self):
        try:
            for query in self._queries[:1]:
                url = f'https://dspace.mit.edu/discover?query={_up.quote(query)}'
                result = _sb_fetch(url)
                if not result or not result.get('ok'):
                    continue
                links = [l for l in result.get('links', []) if '/handle/' in l][:3]
                for href in links:
                    if self._is_stopped():
                        return
                    page = _sb_fetch(href)
                    if page and page.get('text') and len(page['text']) > 500:
                        self._add_text('DSpace MIT', page['text'], href[:60])
                    _between_pages()
        except Exception as e:
            self._log('WARNING', f'DSpace scrape failed: {e}')

    def _research_dukespace(self):
        try:
            url = f'https://dukespace.lib.duke.edu/dspace/discover?query={_up.quote(self._queries[0])}'
            result = _sb_fetch(url)
            if not result or not result.get('ok'):
                return
            links = [l for l in result.get('links', []) if '/handle/' in l][:2]
            for href in links:
                if self._is_stopped():
                    return
                page = _sb_fetch(href)
                if page and page.get('text') and len(page['text']) > 500:
                    self._add_text('DukeSpace', page['text'], href[:60])
                _between_pages()
        except Exception as e:
            self._log('WARNING', f'DukeSpace scrape failed: {e}')

    def _research_escholarship(self):
        try:
            url = f'https://escholarship.org/search?q={_up.quote(self._queries[0])}'
            result = _sb_fetch(url)
            if not result or not result.get('ok'):
                return
            links = [l for l in result.get('links', []) if '/content/' in l][:2]
            for href in links:
                if self._is_stopped():
                    return
                page = _sb_fetch(href)
                if page and page.get('text') and len(page['text']) > 500:
                    self._add_text('eScholarship', page['text'], href[:60])
                _between_pages()
        except Exception as e:
            self._log('WARNING', f'eScholarship scrape failed: {e}')

    def _research_digitalcommons(self):
        try:
            url = f'https://digitalcommons.unl.edu/do/search/?q={_up.quote(self._queries[0])}'
            result = _sb_fetch(url)
            if not result or not result.get('ok'):
                return
            links = [l for l in result.get('links', []) if 'viewcontent' in l][:2]
            for href in links:
                if self._is_stopped():
                    return
                page = _sb_fetch(href)
                if page and page.get('text') and len(page['text']) > 500:
                    self._add_text('DigitalCommons UNL', page['text'], href[:60])
                _between_pages()
        except Exception as e:
            self._log('WARNING', f'DigitalCommons UNL scrape failed: {e}')

    def _research_scholarworks(self):
        try:
            url = f'https://scholarworks.umass.edu/do/search/?q={_up.quote(self._queries[0])}'
            result = _sb_fetch(url)
            if not result or not result.get('ok'):
                return
            links = [l for l in result.get('links', []) if 'viewcontent' in l][:2]
            for href in links:
                if self._is_stopped():
                    return
                page = _sb_fetch(href)
                if page and page.get('text') and len(page['text']) > 500:
                    self._add_text('ScholarWorks UMass', page['text'], href[:60])
                _between_pages()
        except Exception as e:
            self._log('WARNING', f'ScholarWorks scrape failed: {e}')

    def _research_hnet(self):
        try:
            url = f'https://networks.h-net.org/search/node/{_up.quote(self._queries[0])}'
            result = _sb_fetch(url)
            if not result or not result.get('ok'):
                return
            links = result.get('links', [])[:3]
            for href in links:
                if self._is_stopped():
                    return
                page = _sb_fetch(href)
                if page and page.get('text') and len(page['text']) > 300:
                    self._add_text('H-Net Reviews', page['text'], href[:60])
                _between_pages()
        except Exception as e:
            self._log('WARNING', f'H-Net scrape failed: {e}')

    def _research_inquiries(self):
        try:
            url = f'https://www.inquiriesjournal.com/search?q={_up.quote(self._queries[0])}'
            result = _sb_fetch(url)
            if not result or not result.get('ok'):
                return
            links = [l for l in result.get('links', []) if '/articles/' in l][:3]
            for href in links:
                if self._is_stopped():
                    return
                page = _sb_fetch(href)
                if page and page.get('text') and len(page['text']) > 300:
                    self._add_text('Inquiries Journal', page['text'], href[:60])
                _between_pages()
        except Exception as e:
            self._log('WARNING', f'Inquiries Journal scrape failed: {e}')
