# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The scholarly research waterfall's stage helpers, unit by unit.

``scholarly_research_agent.run._RunMixin.run`` used to be one 572-line method
whose every step — the DB-cache pick, the live-web first pass, the API sweep,
the browser fallback, the extraction loop with its nested
``_try_extract_candidate`` closure, the Wikipedia last resort and the reporting
bundle — could only be reached by talking to Postgres, three scholarly APIs,
Selenium and Wikipedia at once. Those steps now live in ``run_stages`` as
module-level functions that take the agent explicitly, so a stub agent drives
them here: no DB, no network, no browser, no GPU.

The name is ``..._scholarly`` rather than the brief's ``test_run_helpers.py``
because a parallel task of the same tree had already created that file for a
different ``run.py`` (see the report's notes).
"""

import pytest

from zyg_workflows.scholarly_research_agent import run_stages as ST


class StubAgent:
    """A recording fake of the research agent: no DB, no network, no browser.

    Every ``_db_*``/``_fetch_*`` method answers from a canned attribute and
    appends to :attr:`calls`, so a test can assert both what a stage returned
    and which side effects it fired, in order.
    """

    def __init__(self, topic='history', **kw):
        self.topic = topic
        self.calls = []
        self.logs = []
        self._texts = []
        self._sources_used = []
        self._papers_found = []
        self._queries = kw.get('queries', ['q1'])
        self._directive_kw = kw.get('directive_kw', '')
        self.driver = kw.get('driver', object())
        self._stopped = kw.get('stopped', False)
        self.unused = kw.get('unused', [])
        self.web = kw.get('web', ('', '', 0, []))
        self.api_results = kw.get('api_results', {})
        self.extracted = kw.get('extracted', {})
        self.paywalled = set(kw.get('paywalled', ()))
        self.inserted = []
        self.blacklisted = []
        self.marked_used = []

    # ── logging and control ──────────────────────────────────────────────
    def _log(self, level, message):
        """Record one log line exactly as the agent would emit it."""
        self.logs.append((level, message))

    def _is_stopped(self):
        """Whether the run was asked to stop; constant for a stub."""
        return self._stopped

    # ── database ─────────────────────────────────────────────────────────
    def _db_get_unused(self, topic):
        """The canned unused-essay rows, as fresh dicts per call."""
        self.calls.append(('db_get_unused', topic))
        return [dict(p) for p in self.unused]

    def _db_insert_papers(self, papers):
        """Record an insert of the paper pool."""
        self.calls.append(('db_insert', [p.get('id') for p in papers]))
        self.inserted.append(list(papers))

    def _db_blacklist(self, cid, reason=None):
        """Record a blacklisting with its reason."""
        self.calls.append(('db_blacklist', cid, reason))
        self.blacklisted.append((cid, reason))

    def _db_mark_used(self, cid):
        """Record that an essay was consumed."""
        self.marked_used.append(cid)

    def _score_paper(self, paper):
        """Echo the row's pre-set ``score`` field (default 0)."""
        return paper.get('score', 0)

    def _deduplicate(self, papers):
        """Drop rows whose ``id`` was already seen, keeping the first."""
        seen, out = set(), []
        for p in papers:
            if p.get('id') in seen:
                continue
            seen.add(p.get('id'))
            out.append(p)
        return out

    # ── network ──────────────────────────────────────────────────────────
    def _fetch_web_content(self, topic, directive):
        """The canned (text, title, word_count, sources) web answer."""
        self.calls.append(('fetch_web', topic, directive))
        return self.web

    def _fetch_openalex(self, query):
        """The canned OpenAlex rows for *query*."""
        self.calls.append(('openalex', query))
        return [dict(p) for p in self.api_results.get('openalex', [])]

    def _fetch_semantic_scholar(self, query):
        """The canned Semantic Scholar rows for *query*."""
        self.calls.append(('semanticscholar', query))
        return [dict(p) for p in self.api_results.get('semanticscholar', [])]

    def _fetch_core_api(self, query):
        """The canned CORE rows for *query*."""
        self.calls.append(('core', query))
        return [dict(p) for p in self.api_results.get('core', [])]

    def _is_paywalled_url(self, url):
        """Whether *url* is one of the stub's paywalled URLs."""
        return url in self.paywalled

    def _extract_full_text_html(self, url):
        """The canned HTML extraction for *url*."""
        self.calls.append(('html', url))
        return self.extracted.get(url, '')

    def _extract_full_text_pdf(self, path):
        """The canned PDF extraction, keyed by the last downloaded URL."""
        self.calls.append(('pdf', path))
        return self.extracted.get('pdf', '')

    # ── browser ──────────────────────────────────────────────────────────
    def _setup_browser(self):
        """Record the browser start-up."""
        self.calls.append(('setup_browser',))

    def _teardown_browser(self):
        """Record the browser tear-down."""
        self.calls.append(('teardown_browser',))

    def __getattr__(self, name):
        """Answer every ``_research_*`` scraper with a recording no-op."""
        if not name.startswith('_research_'):
            raise AttributeError(name)

        def scraper():
            self.calls.append((name,))
            self._texts.append('x' * 3000)

        return scraper


def a_paper(pid, score=10, **kw):
    """One candidate row: id, score and whatever fields the test needs.

    ``score`` is what :meth:`StubAgent._score_paper` will echo; ``_score`` is
    the already-scored field the pure helpers read, so a row is usable both
    before and after a scoring pass.
    """
    row = {'id': pid, 'score': score, '_score': score, 'title': f'Paper {pid}', 'abstract': ''}
    row.update(kw)
    return row


# ── prose_gate_metrics ───────────────────────────────────────────────────────


def test_plain_prose_scores_a_full_prose_ratio_and_no_equations():
    """Text without citations or formulas is pure prose: ratio 1.0, density 0."""
    metrics = ST.prose_gate_metrics('the quick brown fox jumped over it', 7)
    assert metrics.cite_hits == 0
    assert metrics.prose_ratio == 1.0
    assert metrics.eq_lines == 0
    assert metrics.eq_density == 0.0


def test_inline_citations_drive_the_prose_ratio_to_zero():
    """Eight words per citation exhausts the ratio — the gate's whole point."""
    text = 'word (Smith, 2019) word [12] word (Jones et al., 2020) word [3]'
    metrics = ST.prose_gate_metrics(text, len(text.split()))
    assert metrics.cite_hits == 4
    assert metrics.prose_ratio == 0.0


def test_a_single_citation_in_long_prose_barely_dents_the_ratio():
    """One hit in 800 words costs exactly 8/800 of the ratio."""
    metrics = ST.prose_gate_metrics('(Smith, 2019) ' + 'word ' * 799, 800)
    assert metrics.cite_hits == 1
    assert metrics.prose_ratio == pytest.approx(1.0 - 8 / 800)


def test_equation_lines_are_counted_and_blank_lines_ignored():
    """Measurement lines count; blank lines never do, but they do dilute."""
    text = 'intro prose\n\nT20 = 1.45 s\nSPL ± 2.3 dB\nsee Fig. 3\ncloser'
    metrics = ST.prose_gate_metrics(text, len(text.split()))
    assert metrics.eq_lines == 3
    assert metrics.eq_density == pytest.approx(3 / 6)


# ── blacklist_verdict ────────────────────────────────────────────────────────


def test_an_abstract_only_hit_is_blacklisted_permanently():
    """Only the abstract was reachable → content_unavailable, never retried."""
    reason, message = ST.blacklist_verdict(True, 9000, 120)
    assert reason == 'content_unavailable'
    assert message == ('Essay only has abstract (120 words) — full text inaccessible, blacklisting permanently')


def test_a_promising_word_estimate_makes_a_short_result_retryable():
    """The estimate promised ≥500 words, so the miss is transient."""
    reason, message = ST.blacklist_verdict(False, 1200, 80)
    assert reason == 'extraction_failure'
    assert 'word_estimate was 1200' in message
    assert 'will retry next run' in message


def test_a_genuinely_short_paper_is_blacklisted_as_too_short():
    """No estimate to excuse it: the paper really is that short."""
    reason, message = ST.blacklist_verdict(False, 120, 80)
    assert reason == 'too_short'
    assert message == 'Essay too short (80 words < 500) — blacklisting permanently'


def test_abstract_only_wins_over_a_high_word_estimate():
    """The ladder's order is preserved: abstract_only is checked first."""
    assert ST.blacklist_verdict(True, 5000, 100)[0] == 'content_unavailable'


# ── cap_essay ────────────────────────────────────────────────────────────────


def test_a_short_essay_passes_through_cap_essay_untouched():
    """Under the cap nothing is rewritten and `capped` stays False."""
    text, words, capped = ST.cap_essay('one two three', 3)
    assert (text, words, capped) == ('one two three', 3, False)


def test_an_essay_exactly_at_the_cap_is_not_capped():
    """The boundary is inclusive — `word_count <= max_words` is a pass."""
    assert ST.cap_essay('x ' * 10, 10, max_words=10)[2] is False


def test_cap_essay_cuts_on_a_nearby_paragraph_boundary():
    """A blank line close to the mark wins: the tail paragraph is dropped."""
    body = 'word ' * 50 + '\n\n' + 'tail ' * 50
    text, words, capped = ST.cap_essay(body, 100, max_words=50)
    assert capped is True
    assert 'tail' not in text
    assert words == 50


def test_cap_essay_falls_back_to_a_hard_word_cut_without_a_boundary():
    """With no paragraph break near the mark the text is cut word-wise."""
    text, words, capped = ST.cap_essay('word ' * 100, 100, max_words=40)
    assert capped is True
    assert words == 40
    assert text == ' '.join(['word'] * 40)


# ── the reporting bundle ─────────────────────────────────────────────────────


def test_papers_found_rows_keeps_pool_order_and_truncates_the_label():
    """One row per paper, in pool order, with the title cut at 60 chars."""
    pool = [
        {'source_api': 'OpenAlex', 'title': 'T' * 80, 'abstract': 'abc', '_score': 7, 'doi': 'd/1'},
        {'source_api': 'CORE', 'title': 'Short', 'abstract': '', '_score': 0, 'doi': ''},
    ]
    rows = ST.papers_found_rows(pool)
    assert [r['source'] for r in rows] == ['OpenAlex', 'CORE']
    assert rows[0] == {'source': 'OpenAlex', 'label': 'T' * 60, 'chars': 3, 'score': 7, 'doi': 'd/1'}
    assert rows[1]['chars'] == 0


def test_papers_found_rows_defaults_every_missing_field():
    """A bare row still produces the five report keys."""
    assert ST.papers_found_rows([{}]) == [{'source': '', 'label': '', 'chars': 0, 'score': 0, 'doi': ''}]


def test_sources_used_labels_are_distinct_and_never_empty():
    """Duplicates collapse and papers without a source_api are skipped."""
    pool = [{'source_api': 'CORE'}, {'source_api': 'CORE'}, {'source_api': ''}, {}]
    assert ST.sources_used_labels(pool) == ['CORE']


# ── the Wikipedia fallback ───────────────────────────────────────────────────


def test_strip_wikipedia_appendix_drops_the_reference_tail():
    """Everything from the first appendix heading onwards is citation noise."""
    article = 'Body text here.\n\n== References ==\n[1] noise\n== See also ==\nmore'
    assert ST.strip_wikipedia_appendix(article) == 'Body text here.'


def test_strip_wikipedia_appendix_matches_headings_case_insensitively():
    """`== further reading ==` is stripped just like the canonical casing."""
    assert ST.strip_wikipedia_appendix('Body.\n== further reading ==\nx') == 'Body.'


def test_strip_wikipedia_appendix_leaves_an_article_without_appendix_alone():
    """No appendix heading → only surrounding whitespace is trimmed."""
    assert ST.strip_wikipedia_appendix('  Just a body.\n== History ==\nmore  ') == ('Just a body.\n== History ==\nmore')


def test_wikipedia_subjects_copies_the_table_before_shuffling():
    """The module-level table must survive the in-place shuffle untouched."""
    before = list(ST.WIKI_SUBJECTS['crime'])
    got = ST.wikipedia_subjects('crime')
    assert sorted(got) == sorted(before)
    assert ST.WIKI_SUBJECTS['crime'] == before


def test_wikipedia_subjects_falls_back_to_the_topic_itself():
    """An unknown topic is its own only subject."""
    assert ST.wikipedia_subjects('bees in amber') == ['bees in amber']


def test_wikipedia_fallback_takes_the_first_article_over_1500_words(monkeypatch):
    """Short articles are logged and skipped until one is long enough."""
    agent = StubAgent(topic='crime')
    monkeypatch.setattr(ST, 'wikipedia_subjects', lambda topic: ['tiny', 'big'])
    monkeypatch.setattr(ST, '_wikipedia_article', lambda s: 'word ' * (10 if s == 'tiny' else 1600))
    text, words, selected = ST.wikipedia_fallback(agent, 'old', 3, None)
    assert words == 1600
    assert text.startswith('word')
    assert selected == {'title': 'big', 'authors': 'Wikipedia', 'abstract': ''}
    assert ('INFO', 'Wikipedia "tiny": only 10 words — trying next') in agent.logs
    assert ('INFO', 'Wikipedia fallback success: big (1600 words)') in agent.logs


def test_wikipedia_fallback_caps_a_huge_article_at_4000_words(monkeypatch):
    """A 9000-word article comes back as exactly MAX_WORDS words."""
    agent = StubAgent(topic='crime')
    monkeypatch.setattr(ST, 'wikipedia_subjects', lambda topic: ['big'])
    monkeypatch.setattr(ST, '_wikipedia_article', lambda s: 'word ' * 9000)
    text, words, _ = ST.wikipedia_fallback(agent, '', 0, None)
    assert words == ST.MAX_WORDS == 4000
    assert len(text.split()) == 4000


def test_wikipedia_fallback_keeps_the_existing_title_and_returns_input_on_failure(monkeypatch):
    """Nothing long enough → the caller's text, count and paper are unchanged."""
    agent = StubAgent(topic='crime')
    monkeypatch.setattr(ST, 'wikipedia_subjects', lambda topic: ['tiny'])
    monkeypatch.setattr(ST, '_wikipedia_article', lambda s: 'word ' * 10)
    paper = {'title': 'Kept'}
    assert ST.wikipedia_fallback(agent, 'old', 3, paper) == ('old', 3, paper)


def test_wiki_selected_fills_in_an_empty_title_from_the_subject():
    """A selected paper with a blank title is named after the article."""
    assert ST._wiki_selected({'title': ''}, 'Babylon')['title'] == 'Babylon'
    assert ST._wiki_selected({'title': 'Real'}, 'Babylon')['title'] == 'Real'


# ── the candidate queue ──────────────────────────────────────────────────────


def test_new_candidate_search_puts_the_selection_first_then_sorts_by_score():
    """The pick leads; the rest follow by descending score, minus the pick."""
    found = ST.Discovery(
        all_papers=[a_paper('a', 1), a_paper('b', 9), a_paper('c', 5)],
        selected=a_paper('a', 1),
        selected_id='a',
    )
    search = ST.new_candidate_search(found)
    assert [p['id'] for p in search.queue] == ['a', 'b', 'c']
    assert search.tried_ids == set()
    assert search.attempt == 0


def test_new_candidate_search_drops_disqualified_papers():
    """A negative score means disqualified — it never enters the queue."""
    found = ST.Discovery(
        all_papers=[a_paper('a', 1), a_paper('bad', -1), a_paper('c', 5)],
        selected=a_paper('a', 1),
        selected_id='a',
    )
    assert [p['id'] for p in ST.new_candidate_search(found).queue] == ['a', 'c']


# ── steps 1-3: discovery ─────────────────────────────────────────────────────


def test_a_warm_db_cache_skips_every_api_call():
    """Five or more unused essays: the best-scoring one is picked offline."""
    agent = StubAgent(unused=[a_paper(str(i), score=i) for i in range(5)])
    found = ST.discover_candidates(agent)
    assert found.selected_id == '4'
    assert [p['id'] for p in found.all_papers] == ['4', '3', '2', '1', '0']
    assert found.bail is False
    assert [c for c in agent.calls if c[0] != 'db_get_unused'] == []
    assert ('INFO', 'DB cache hit: 5 unused essays — skipping API calls') in agent.logs


def test_the_db_cache_pick_filters_out_disqualified_essays():
    """Negative-score rows leave the pool even on the cache path."""
    agent = StubAgent(unused=[a_paper('x', -3)] + [a_paper(str(i), i) for i in range(4)])
    found = ST.discover_candidates(agent)
    assert 'x' not in [p['id'] for p in found.all_papers]
    assert found.selected_id == '3'


def test_a_long_enough_web_answer_short_circuits_the_academic_apis():
    """≥500 words from the live web: no API is queried and the row is ours."""
    agent = StubAgent(directive_kw='roman roads', web=('text ' * 600, 'Roman roads', 600, ['en.wikipedia.org']))
    found = ST.discover_candidates(agent)
    assert found.web_full_text.startswith('text')
    assert found.selected['authors'] == 'Web Research (Wikipedia)'
    assert found.all_papers == []
    assert agent._sources_used == ['en.wikipedia.org']
    assert agent._papers_found == [
        {'source': 'SuperBrowser', 'label': 'Roman roads', 'chars': len('text ' * 600), 'score': 100, 'doi': ''}
    ]
    assert ('openalex', 'q1') not in agent.calls


def test_a_thin_web_answer_falls_through_to_the_apis():
    """Under 500 words the web pass is abandoned with a log line."""
    agent = StubAgent(
        directive_kw='roman roads',
        web=('short', 'Roman roads', 12, []),
        api_results={'openalex': [a_paper('p1', 4)]},
    )
    found = ST.discover_candidates(agent)
    assert found.web_full_text == ''
    assert ('openalex', 'q1') in agent.calls
    assert (
        'INFO',
        '[SuperBrowser] Web research returned only 12 words — falling back to academic APIs',
    ) in agent.logs


def test_no_directive_means_no_web_pass_at_all():
    """Predefined topics go straight to the APIs; `_fetch_web_content` is unused."""
    agent = StubAgent(api_results={'core': [a_paper('p1', 4)]})
    ST.discover_candidates(agent)
    assert [c for c in agent.calls if c[0] == 'fetch_web'] == []


def test_empty_apis_trigger_the_browser_fallback_and_bail():
    """Nothing from any API: the scrapers run in order and the caller bails."""
    agent = StubAgent()
    found = ST.discover_candidates(agent)
    assert found.bail is True
    assert found.selected is None
    assert agent.calls[-1] == ('teardown_browser',)
    assert ('INFO', '▶ Digital Commons (Bepress)') in agent.logs


def test_the_browser_fallback_stops_at_the_text_budget():
    """20 000 characters is enough — the remaining scrapers are not run."""
    agent = StubAgent()
    ST._browser_scrape_fallback(agent)
    scraped = [c[0] for c in agent.calls if c[0].startswith('_research_')]
    assert len(scraped) == 7
    assert scraped[0] == '_research_bepress'
    assert agent._sources_used == [name for name, _ in ST.BROWSER_SOURCES[:7]]


def test_the_browser_is_torn_down_even_when_setup_fails(monkeypatch):
    """The `finally` is what guarantees no leaked Chrome process."""
    agent = StubAgent()

    def boom():
        raise RuntimeError('no display')

    monkeypatch.setattr(agent, '_setup_browser', boom)
    with pytest.raises(RuntimeError):
        ST._browser_scrape_fallback(agent)
    assert ('teardown_browser',) in agent.calls


def test_api_results_are_scored_deduplicated_capped_and_stored():
    """Step 3: dedupe, drop disqualified, sort, cap at 20, insert, re-pick."""
    agent = StubAgent(
        api_results={'openalex': [a_paper('p1', 4), a_paper('p1', 4), a_paper('bad', -2), a_paper('p2', 8)]},
        unused=[a_paper('p2', 8), a_paper('p1', 4)],
    )
    found = ST.discover_candidates(agent)
    assert [p['id'] for p in found.all_papers] == ['p2', 'p1']
    assert found.selected_id == 'p2'
    assert agent.inserted and [p['id'] for p in agent.inserted[0]] == ['p2', 'p1']
    assert ('INFO', 'Qualified papers (≥500w estimate): 2 of 3') in agent.logs


def test_the_api_sweep_stops_once_twenty_candidates_are_in():
    """The second query is never sent after the 20-candidate threshold."""
    agent = StubAgent(queries=['q1', 'q2'], api_results={'openalex': [a_paper(str(i)) for i in range(20)]})
    ST._query_all_apis(agent)
    assert [c for c in agent.calls if c[0] == 'openalex'] == [('openalex', 'q1')]


# ── step 4: extraction ───────────────────────────────────────────────────────


def test_extract_best_text_short_circuits_on_a_web_answer():
    """Web text already in hand: no candidate is ever tried."""
    agent = StubAgent()
    found = ST.Discovery(all_papers=[], selected={'title': 'T'}, web_full_text='word ' * 700)
    out = ST.extract_best_text(agent, found)
    assert out.word_count == 700
    assert out.attempt == 0
    assert agent.calls == []


def test_extract_best_text_accepts_the_first_candidate_over_500_words():
    """The 500-word minimum is met: the candidate becomes the selection."""
    url = 'https://example.org/essay.html'
    agent = StubAgent(extracted={url: 'word ' * 600})
    found = ST.Discovery(
        all_papers=[a_paper('p1', 5, full_text_url=url)],
        selected=a_paper('p1', 5, full_text_url=url),
        selected_id='p1',
    )
    out = ST.extract_best_text(agent, found)
    assert out.word_count == 600
    assert out.selected_id == 'p1'
    assert out.attempt == 1
    assert agent.blacklisted == []
    assert ('INFO', '✓ Essay meets 500-word minimum (600 words)') in agent.logs


def test_a_short_abstract_only_candidate_is_blacklisted_permanently():
    """Falling back to an abstract blacklists the paper as unavailable."""
    agent = StubAgent()
    pick = a_paper('p1', 5, abstract='word ' * 120)
    found = ST.Discovery(all_papers=[pick], selected=pick, selected_id='p1')
    out = ST.extract_best_text(agent, found)
    assert out.word_count == 120
    assert agent.blacklisted == [('p1', 'content_unavailable')]


def test_extraction_stops_when_every_source_is_exhausted():
    """An empty queue with no API or DB refill ends the loop with a warning."""
    agent = StubAgent()
    found = ST.Discovery(all_papers=[], selected=a_paper('p1', 5), selected_id='p1')
    out = ST.extract_best_text(agent, found)
    assert out.word_count == 0
    assert ('WARNING', 'All sources exhausted — no essay reached 500 words') in agent.logs


def test_a_stopped_run_extracts_nothing():
    """`_is_stopped()` is honoured before the first candidate is popped."""
    agent = StubAgent(stopped=True)
    pick = a_paper('p1', 5, abstract='word ' * 600)
    out = ST.extract_best_text(agent, ST.Discovery(all_papers=[pick], selected=pick, selected_id='p1'))
    assert out.full_text == ''
    assert agent.calls == []


# ── try_extract_candidate ────────────────────────────────────────────────────


def test_a_paywalled_pdf_url_is_skipped_before_any_download():
    """Known paywalled domains return 403 every time — never fetch them."""
    agent = StubAgent(paywalled={'https://paywall.test/a.pdf'})
    text, pdf_path, tmp_pdf, abstract_only = ST.try_extract_candidate(
        agent, a_paper('p1', pdf_url='https://paywall.test/a.pdf', abstract='word ' * 50)
    )
    assert pdf_path is None
    assert tmp_pdf is None
    assert abstract_only is True
    assert len(text.split()) == 50
    assert ('INFO', 'Skipping paywalled PDF URL: https://paywall.test/a.pdf') in agent.logs


def test_an_html_full_text_url_is_extracted_without_a_temp_file():
    """The HTML branch never creates a temp PDF to clean up."""
    url = 'https://example.org/essay'
    agent = StubAgent(extracted={url: 'word ' * 400})
    text, pdf_path, tmp_pdf, abstract_only = ST.try_extract_candidate(agent, a_paper('p1', full_text_url=url))
    assert len(text.split()) == 400
    assert (pdf_path, tmp_pdf, abstract_only) == (None, None, False)
    assert ('html', url) in agent.calls


def test_a_thin_extraction_falls_back_to_the_abstract():
    """Under 100 words the abstract wins and `abstract_only` is flagged."""
    url = 'https://example.org/essay'
    agent = StubAgent(extracted={url: 'tiny'})
    text, _, _, abstract_only = ST.try_extract_candidate(agent, a_paper('p1', full_text_url=url, abstract='A' * 9))
    assert text == 'A' * 9
    assert abstract_only is True


def test_a_candidate_with_no_urls_and_no_abstract_yields_nothing():
    """Nothing to extract: empty text and no abstract-only claim."""
    assert ST.try_extract_candidate(StubAgent(), a_paper('p1')) == ('', None, None, False)


def test_a_non_http_scheme_is_never_fetched():
    """A `file://` URL must not reach the downloader or the HTML extractor."""
    agent = StubAgent()
    text, pdf_path, tmp_pdf, _ = ST.try_extract_candidate(agent, a_paper('p1', pdf_url='file:///etc/passwd.pdf'))
    assert (text, pdf_path, tmp_pdf) == ('', None, None)
    assert agent.calls == []


# ── temp-file cleanup ────────────────────────────────────────────────────────


def test_discard_temp_pdf_deletes_the_file(tmp_path):
    """The downloaded temp PDF is removed once it has been read."""
    path = tmp_path / 'a.pdf'
    path.write_bytes(b'%PDF-1.4')
    ST.discard_temp_pdf(str(path))
    assert not path.exists()


def test_discard_temp_pdf_tolerates_none_and_a_missing_path(tmp_path):
    """Both no path at all and an already-deleted file are no-ops."""
    ST.discard_temp_pdf(None)
    ST.discard_temp_pdf(str(tmp_path / 'gone.pdf'))
