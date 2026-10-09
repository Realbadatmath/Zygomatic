# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Super-Browser live Wikipedia research for free-text directives."""

from zyg_workflows.scholarly_research_agent.constants import (
    _hj,
    _zyg_logging,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.scholarly_research_agent')


class _WebContentMixin:
    def _fetch_web_content(self, directive: str, keywords: list) -> tuple:
        """Fetch relevant live web content via Wikipedia for a free-text directive.

        This is the Super Browser capability — live web research instead of academic
        paper APIs. Searches Wikipedia using the directive keywords, fetches full
        article text, and returns it as primary research material.

        Returns:
            (full_text, title, word_count, sources)
            full_text is empty string if web research fails or yields < 200 words.
        """
        import re as _rw
        import urllib.parse as _upw

        _UA = 'ZygomaticDocBot/1.0 (research)'
        _STRIP_RE = _rw.compile(
            r'\n==\s*(References?|Notes?|See also|Bibliography|External links?|'
            r'Further reading|Footnotes?|Citations?|Appendix|Gallery|Sources?)\s*==.*',
            _rw.IGNORECASE | _rw.DOTALL,
        )

        def _wiki_search(query: str, limit: int = 5) -> list:
            url = (
                f'https://en.wikipedia.org/w/api.php?action=opensearch'
                f'&search={_upw.quote(query)}&limit={limit}&format=json'
            )
            try:
                data = _hj.request_json(url, headers={'User-Agent': _UA}, timeout=10)
                return data[1] if len(data) > 1 else []
            except Exception:
                return []

        def _wiki_fetch(title: str) -> str:
            url = (
                f'https://en.wikipedia.org/w/api.php?action=query'
                f'&titles={_upw.quote(title)}&prop=extracts&explaintext=1'
                f'&exsectionformat=plain&redirects=1&format=json'
            )
            try:
                data = _hj.request_json(url, headers={'User-Agent': _UA}, timeout=15)
                for page in data.get('query', {}).get('pages', {}).values():
                    text = page.get('extract', '') or ''
                    if text and page.get('ns', 0) == 0:
                        return _STRIP_RE.sub('', text).strip()
            except Exception as _exc:
                _zyg_log.warning('wikipedia extract fetch failed, continuing without it: %s', _exc)
            return ''

        collected_texts: list = []
        sources_found: list = []
        total_words = 0
        seen_titles: set = set()

        # Build search queries.
        # If Claude identified a clean subject phrase, use it directly as the first query.
        # Otherwise fall back to joining the first 4 keywords.
        claude_subject = getattr(self, '_claude_subject', '')
        if claude_subject:
            kw_phrase = claude_subject
            # Also try individual words of the subject as fallback queries
            subject_words = [w for w in claude_subject.split() if len(w) >= 4]
            search_queries = [claude_subject] + ([' '.join(subject_words[:2])] if len(subject_words) >= 2 else [])
        else:
            kw_phrase = ' '.join(keywords[:4])
            specific_kw = [k for k in reversed(keywords) if len(k) >= 5][:1]
            search_queries = [kw_phrase] + specific_kw

        # Disambiguation-page fallback: "Ancient Egyptian civilization" and "Ancient Egyptian"
        # both resolve to Wikipedia disambiguation/redirect pages with 0 words.
        # After the primary queries, append extra queries built from meaningful words in the
        # directive itself — these are concrete topic words that find real articles.
        _directive_stopwords = {
            'a',
            'an',
            'the',
            'and',
            'or',
            'on',
            'in',
            'of',
            'for',
            'to',
            'with',
            'their',
            'about',
            'from',
            'this',
            'that',
            'create',
            'make',
            'write',
            'documentary',
            'etcetera',
            'etc',
            'story',
            'stories',
            'tale',
            'video',
            'short',
            'lone',
        }
        _narrative_meta = {
            'story',
            'stories',
            'tale',
            'video',
            'short',
            'narrative',
            'documentary',
            'episode',
            'chapter',
            'series',
            'film',
            'movie',
        }
        _directive_words = [
            w.strip('.,;:!?').lower()
            for w in directive.split()
            if len(w.strip('.,;:!?')) >= 5 and w.strip('.,;:!?').lower() not in _directive_stopwords
        ]
        # Build extra queries from directive words + full subject phrase (never bare first word alone).
        _extra_queries = []
        _subject_phrase = claude_subject if claude_subject else kw_phrase
        _meaningful_subject = (
            [w for w in claude_subject.split() if len(w) >= 4]
            if claude_subject
            else [w for w in kw_phrase.split() if len(w) >= 4]
        )
        for _dw in _directive_words[:4]:
            if _dw in _narrative_meta:
                continue
            if _dw in [q.lower() for q in search_queries]:
                continue
            if claude_subject or len(_meaningful_subject) >= 2:
                _extra_queries.append(f'{_subject_phrase} {_dw}')
        search_queries = search_queries + _extra_queries

        for sq in search_queries:
            if self._is_stopped() or total_words >= 3000:
                break
            self._log('INFO', f'[SuperBrowser] Wikipedia search: {sq!r}')
            titles = _wiki_search(sq, limit=5)

            for title in titles:
                if self._is_stopped() or total_words >= 3000:
                    break
                if title in seen_titles:
                    continue
                seen_titles.add(title)

                # Skip fiction/entertainment disambiguation pages — they dilute
                # factual research with plot summaries and production details.
                _FICTION_SUFFIXES = (
                    '(film)',
                    '(movie)',
                    '(TV series)',
                    '(television series)',
                    '(miniseries)',
                    '(mini-series)',
                    '(season)',
                    '(novel)',
                    '(book)',
                    '(video game)',
                    '(game)',
                    '(soundtrack)',
                    '(disambiguation)',
                    '(song)',
                    '(album)',
                    '(manga)',
                    '(anime)',
                )
                _title_lower = title.lower()
                if any(_title_lower.endswith(s.lower()) or f' {s.lower()}' in _title_lower for s in _FICTION_SUFFIXES):
                    self._log('INFO', f'[SuperBrowser] Skipping "{title}" — fiction/media disambiguation')
                    continue

                self._log('INFO', f'[SuperBrowser] Fetching: {title}')
                text = _wiki_fetch(title)
                wc = len(text.split())

                if wc < 500:
                    self._log('INFO', f'[SuperBrowser] Skipping "{title}" — only {wc} words')
                    continue

                # Relevance: when Claude gave a subject phrase, require substantive terms
                # (all words ≥4 chars, or longest ≥5 + another if multiple).
                text_lower = text.lower()
                if claude_subject:
                    check_words = [w.lower() for w in claude_subject.split() if len(w) >= 4]
                    if check_words:
                        if len(check_words) >= 2:
                            if not all(w in text_lower for w in check_words):
                                self._log('INFO', f'[SuperBrowser] Skipping "{title}" — missing subject terms')
                                continue
                        else:
                            long_terms = sorted(
                                [w.lower() for w in claude_subject.split() if len(w) >= 5],
                                key=len,
                                reverse=True,
                            )
                            if long_terms:
                                primary = long_terms[0]
                                others = [w for w in check_words if w != primary]
                                if primary not in text_lower:
                                    self._log('INFO', f'[SuperBrowser] Skipping "{title}" — missing key term')
                                    continue
                                if others and not any(w in text_lower for w in others):
                                    self._log('INFO', f'[SuperBrowser] Skipping "{title}" — missing secondary term')
                                    continue
                            elif check_words[0] not in text_lower:
                                self._log('INFO', f'[SuperBrowser] Skipping "{title}" — missing subject term')
                                continue
                else:
                    _specific = keywords[-1] if keywords else ''
                    if _specific and _specific.lower() not in text_lower:
                        self._log('INFO', f'[SuperBrowser] Skipping "{title}" — missing key term "{_specific}"')
                        continue

                # Cap each article at 2000 words for variety
                words = text.split()
                if len(words) > 2000:
                    target_chars = len(' '.join(words[:2000]))
                    para_idx = text.rfind('\n\n', 0, target_chars + 200)
                    text = text[:para_idx].strip() if para_idx > target_chars // 2 else ' '.join(words[:2000])

                collected_texts.append(f'=== {title} ===\n\n{text}')
                sources_found.append(f'Wikipedia: {title}')
                total_words += len(text.split())
                self._log('INFO', f'[SuperBrowser] ✓ {title}: {len(text.split())} words (running total: {total_words})')

        if not collected_texts:
            return '', '', 0, []

        full_text = '\n\n'.join(collected_texts)
        word_count = len(full_text.split())
        main_title = sources_found[0].replace('Wikipedia: ', '') if sources_found else directive.title()
        return full_text, main_title, word_count, sources_found
