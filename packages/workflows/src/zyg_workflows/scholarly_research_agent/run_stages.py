# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The stages of the scholarly `run()` waterfall, one function per step.

`run.py` keeps the orchestrator; every step it used to inline lives here as a
module-level function that takes the agent explicitly (`agent` is the former
`self`) or, where the step is pure, plain values. The import direction is
one-way — this module imports only `constants`, never `run` — so the package
graph stays acyclic.
"""

import tempfile
from dataclasses import dataclass, field

from zyg_workflows.scholarly_research_agent.constants import (
    _between_sites,
    _hj,
    _up,
    _ur,
    _zyg_logging,
    os,
    random,
    re,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.scholarly_research_agent')

MIN_WORDS = 500
WIKI_MIN_WORDS = 1500
MAX_WORDS = 4000

# Inline citation patterns: (Author, Year), (Author et al., Year), [1]
_CITE_RE = re.compile(
    r'\([A-Z][a-z]+(?:\s+et\s+al\.?)?,?\s+\d{4}\w?\)|'
    r'\[[0-9]{1,3}\]',
)

# Equation/measurement density: lines that look like formulas or data
# e.g. "T20 = 1.45 s", "SPL ± 2.3 dB", "f = 500 Hz", "Fig. 3", "Table 2"
_EQ_RE = re.compile(
    r'=\s*[\d\-+]|'  # assignments with numbers: T = 1.45
    r'±|\bHz\b|\bdB\b|\bkHz\b|\bms\b|\bm²\b|\bm³\b|'
    r'\bFig\.\s*\d|\bTable\s*\d|\bEq\.\s*\d|\bEquation\s*\d|'
    r'\b\d+\.\d+\s*(s|m|Hz|dB|kHz|mm|cm|kg|Pa|N|W)\b',
    re.IGNORECASE,
)

# Wikipedia subjects per predefined topic, for the last-resort fallback.
WIKI_SUBJECTS = {
    'history': [
        # Greek world
        'Alexander the Great',
        'Battle of Thermopylae',
        'Peloponnesian War',
        'Athenian democracy',
        'Battle of Marathon',
        'Trojan War',
        'Pericles',
        'Ancient Olympic Games',
        # Roman world
        'Julius Caesar',
        'Roman Empire',
        'Augustus',
        'Punic Wars',
        'Hannibal',
        'Fall of the Western Roman Empire',
        'Roman army',
        'Roman gladiator',
        'Colosseum',
        # Egypt and Near East
        'Cleopatra',
        'Ramesses II',
        'Ancient Egypt',
        'Tutankhamun',
        'Cyrus the Great',
        'Babylon',
        'Sumer',
        'Assyrian Empire',
        # Mongols and Central Asia
        'Genghis Khan',
        'Attila the Hun',
        'Timur',
        'Mongol Empire',
        'Kublai Khan',
        # Vikings and Norse
        'Viking Age',
        'Leif Erikson',
        'Norse mythology',
        # Medieval Europe
        'Black Death',
        'Crusades',
        'Hundred Years War',
        'Joan of Arc',
        'Charlemagne',
        'Byzantine Empire',
        'Ottoman Empire',
        'Norman conquest of England',
        'Saladin',
        'Battle of Hastings',
        'Feudalism',
        # Pre-Columbian Americas
        'Maya civilization',
        'Aztec Empire',
        'Inca Empire',
        'Spanish conquest of the Aztec Empire',
        'Spanish conquest of the Inca Empire',
        # Asia
        'Silk Road',
        'Qin Shi Huang',
        'Han dynasty',
        'Samurai',
        'Edo period',
        'Tokugawa shogunate',
        # Other
        'Sparta',
        'Ancient Carthage',
        'Macedon',
    ],
    'crime': ['criminology', 'organized crime', 'criminal justice'],
    'war': ['World War II', 'Napoleonic Wars', 'Cold War'],
    'technology': ['artificial intelligence', 'industrial revolution', 'internet'],
    'psychology': ['cognitive psychology', 'behavioral economics', 'human psychology'],
}

# Browser scrapers, in the order the API-less fallback walks them. Each entry
# names the `_research_*` method of the agent to call.
BROWSER_SOURCES = (
    ('Digital Commons (Bepress)', '_research_bepress'),
    ('CORE (browser)', '_research_core'),
    ('SSRN', '_research_ssrn'),
    ('DSpace MIT', '_research_dspace'),
    ('DukeSpace', '_research_dukespace'),
    ('eScholarship', '_research_escholarship'),
    ('DigitalCommons UNL', '_research_digitalcommons'),
    ('ScholarWorks UMass', '_research_scholarworks'),
    ('H-Net Reviews', '_research_hnet'),
    ('Inquiries Journal', '_research_inquiries'),
)

BROWSER_TEXT_BUDGET = 20000


@dataclass
class Discovery:
    """What steps 1-3 found: the paper pool and the first pick.

    `web_full_text` is non-empty only when the Super Browser answered the
    directive directly; `bail` means the browser-scraping fallback ran and the
    caller must return the minimal `_build_output` bundle without a paper.
    """

    all_papers: list
    selected: dict | None
    selected_id: object = None
    web_full_text: str = ''
    bail: bool = False


@dataclass
class CandidateSearch:
    """Mutable state of the extraction loop: the queue and what it has tried."""

    queue: list
    tried_ids: set
    attempt: int = 0
    api_queries_done: set = field(default_factory=set)
    api_exhausted: bool = False


@dataclass
class Extraction:
    """The text step 4 settled on, and the candidate it came from."""

    full_text: str
    word_count: int
    selected: dict | None
    selected_id: object = None
    pdf_path: str | None = None
    tmp_pdf: str | None = None
    attempt: int = 0


@dataclass(frozen=True)
class ProseMetrics:
    """Citation and equation density of an extracted essay."""

    cite_hits: int
    prose_ratio: float
    eq_lines: int
    eq_density: float


# ── Step 1-3: find candidate papers ──────────────────────────────────────────


def discover_candidates(agent) -> Discovery:
    """Run steps 1-3 (DB cache → live web → the three APIs) and pick a paper.

    Returns the `Discovery` the rest of the waterfall works from; `bail=True`
    means the APIs were empty and the browser fallback has already scraped
    whatever it could into `agent._texts`.
    """
    unused = agent._db_get_unused(agent.topic)
    if len(unused) >= 5:
        return _cached_pick(agent, unused)

    web = _web_first_pass(agent)
    if web is not None:
        return web

    combined = _query_all_apis(agent)
    if not combined:
        _browser_scrape_fallback(agent)
        return Discovery(all_papers=[], selected=None, bail=True)
    return _qualify_and_store(agent, combined)


def _cached_pick(agent, unused) -> Discovery:
    """Step 1: score, filter and sort the cached essays, then take the best."""
    agent._log('INFO', f'DB cache hit: {len(unused)} unused essays — skipping API calls')
    # Sort cached by score, filter out disqualified
    for p in unused:
        p['_score'] = agent._score_paper(p)
    unused = [p for p in unused if p.get('_score', 0) >= 0]
    unused.sort(key=lambda x: x.get('_score', 0), reverse=True)
    selected = unused[0] if unused else None
    return Discovery(
        all_papers=unused,
        selected=selected,
        selected_id=selected.get('id') if selected else None,
    )


def _web_first_pass(agent) -> Discovery | None:
    """Step 1.5: live web research for a free-text directive.

    For user-specified topics (not predefined categories), search the live web
    FIRST via Wikipedia. This avoids returning unrelated academic papers and
    directly answers the user's actual directive. Returns None when there is no
    directive, the run was stopped, or the web returned too little text.
    """
    if not agent._directive_kw or agent._is_stopped():
        return None
    agent._log('INFO', '[SuperBrowser] Trying live web research for free-text directive')
    text, title, words, sources = agent._fetch_web_content(agent.topic, agent._directive_kw)
    if words < MIN_WORDS:
        agent._log(
            'INFO',
            f'[SuperBrowser] Web research returned only {words} words — falling back to academic APIs',
        )
        return None
    agent._log(
        'INFO',
        f'[SuperBrowser] ✓ Web research yielded {words} words from {len(sources)} sources — skipping academic APIs',
    )
    agent._sources_used = sources
    agent._papers_found = [
        {
            'source': 'SuperBrowser',
            'label': title[:60],
            'chars': len(text),
            'score': 100,
            'doi': '',
        }
    ]
    return Discovery(
        all_papers=[],
        selected={
            'title': title,
            'authors': 'Web Research (Wikipedia)',
            'abstract': '',
            'full_text_url': '',
            'pdf_url': '',
        },
        web_full_text=text,
    )


def _query_all_apis(agent) -> list:
    """Step 2: call all 3 APIs across the topic's queries until 20 candidates."""
    combined = []
    for query in agent._queries:
        if agent._is_stopped():
            break
        agent._log('INFO', f'Querying APIs for: {query}')

        oa_results = agent._fetch_openalex(query)
        agent._log('INFO', f'OpenAlex: {len(oa_results)} results')

        ss_results = agent._fetch_semantic_scholar(query)
        agent._log('INFO', f'Semantic Scholar: {len(ss_results)} results')

        core_results = agent._fetch_core_api(query)
        agent._log('INFO', f'CORE: {len(core_results)} results')

        combined += oa_results + ss_results + core_results

        # Stop querying once we have enough candidates
        if len(combined) >= 20:
            break
    return combined


def _browser_scrape_fallback(agent) -> None:
    """Scrape the legacy repositories when every API returned nothing.

    Appends into `agent._texts` / `agent._sources_used` and always tears the
    browser down again; stops early at the text budget or on a stop request.
    """
    agent._log('WARNING', 'All APIs returned 0 results — falling back to browser scraping')
    try:
        agent._setup_browser()
        if agent.driver:
            for src_name, src_attr in BROWSER_SOURCES:
                if agent._is_stopped():
                    break
                agent._log('INFO', f'▶ {src_name}')
                try:
                    getattr(agent, src_attr)()
                    agent._sources_used.append(src_name)
                except Exception as _be:
                    agent._log('WARNING', f'{src_name} failed: {_be}')
                _between_sites()
                if sum(len(t) for t in agent._texts) >= BROWSER_TEXT_BUDGET:
                    break
    finally:
        agent._teardown_browser()


def _qualify_and_store(agent, combined) -> Discovery:
    """Step 3: score, deduplicate and store the API results, then pick one."""
    for p in combined:
        p['_score'] = agent._score_paper(p)
    combined = agent._deduplicate(combined)
    # Only keep papers that passed the 1000-word minimum
    qualified = [p for p in combined if p.get('_score', 0) >= 0]
    qualified.sort(key=lambda x: x.get('_score', 0), reverse=True)
    all_papers = qualified[:20]
    agent._log('INFO', f'Qualified papers (≥500w estimate): {len(all_papers)} of {len(combined)}')

    agent._db_insert_papers(all_papers)

    # Pick best unused (already filtered by score above)
    unused_after = agent._db_get_unused(agent.topic)
    for p in unused_after:
        p['_score'] = agent._score_paper(p)
    unused_after = [p for p in unused_after if p.get('_score', 0) >= 0]
    unused_after.sort(key=lambda x: x.get('_score', 0), reverse=True)
    selected = unused_after[0] if unused_after else None
    return Discovery(
        all_papers=all_papers,
        selected=selected,
        selected_id=selected.get('id') if selected else None,
    )


# ── Step 4: extract full text ────────────────────────────────────────────────


def new_candidate_search(found: Discovery) -> CandidateSearch:
    """The initial queue: the selected paper first, then the rest by score."""
    remaining = [p for p in found.all_papers if p.get('id') != found.selected_id and p.get('_score', 0) >= 0]
    remaining.sort(key=lambda x: x.get('_score', 0), reverse=True)
    return CandidateSearch(queue=[found.selected] + remaining, tried_ids=set())


def extract_best_text(agent, found: Discovery) -> Extraction:
    """Step 4: walk the candidate queue until one yields text.

    Web research already having delivered text short-circuits the whole loop.
    A candidate under 500 words is blacklisted with a reason and its temp PDF
    deleted, and — as in the original waterfall — any non-empty extraction ends
    the search, so the queue is only walked on while extraction returns nothing
    at all. The returned `Extraction` holds the last text seen either way.
    """
    out = Extraction(
        full_text=found.web_full_text,
        word_count=len(found.web_full_text.split()) if found.web_full_text else 0,
        selected=found.selected,
        selected_id=found.selected_id,
    )
    if out.full_text:
        # Web research already provided content — skip PDF/HTML extraction
        return out

    search = new_candidate_search(found)
    while not agent._is_stopped():
        if out.full_text:
            # An attempt that produced *any* text ends the search, even when it
            # fell short of 500 words — the Wikipedia fallback takes over then.
            break
        if not search.queue and not _refill_queue(agent, search):
            break
        candidate = search.queue.pop(0)
        cid = candidate.get('id')
        if cid in search.tried_ids:
            continue
        search.tried_ids.add(cid)
        search.attempt += 1
        agent._log('INFO', f'Selected essay (attempt {search.attempt}): {candidate.get("title", "")[:80]} (id={cid})')

        out.full_text, out.pdf_path, out.tmp_pdf, abstract_only = try_extract_candidate(agent, candidate)
        out.word_count = len(out.full_text.split())
        agent._log('INFO', f'Full text extracted: {out.word_count} words')

        # The prose-ratio gate's metrics, computed exactly where they always
        # were; no rung of it ever consumed them (`_reject_reason` stayed None).
        prose_gate_metrics(out.full_text, out.word_count)

        if out.word_count >= MIN_WORDS:
            out.selected = candidate
            out.selected_id = cid
            agent._log('INFO', f'✓ Essay meets 500-word minimum ({out.word_count} words)')
            break
        reason, message = blacklist_verdict(abstract_only, candidate.get('word_estimate', 0), out.word_count)
        agent._log('WARNING', message)
        if cid:
            agent._db_blacklist(cid, reason=reason)
        discard_temp_pdf(out.tmp_pdf)
        out.tmp_pdf = None

    out.attempt = search.attempt
    return out


def _refill_queue(agent, search: CandidateSearch) -> bool:
    """Refill the candidate queue from the APIs, then from the DB cache.

    Returns True when `search.queue` holds candidates again and False when
    every source is exhausted, which stops the extraction loop.
    """
    if not search.api_exhausted:
        # Try re-querying APIs with any queries not yet tried
        fresh = []
        for query in agent._queries:
            if query in search.api_queries_done:
                continue
            if agent._is_stopped():
                break
            agent._log('INFO', f'Re-querying APIs for more candidates: {query}')
            search.api_queries_done.add(query)
            fresh += agent._fetch_openalex(query)
            fresh += agent._fetch_semantic_scholar(query)
            fresh += agent._fetch_core_api(query)
        if fresh:
            for p in fresh:
                p['_score'] = agent._score_paper(p)
            fresh = agent._deduplicate(fresh)
            fresh = [p for p in fresh if p.get('_score', 0) >= 0 and p.get('id') not in search.tried_ids]
            fresh.sort(key=lambda x: x.get('_score', 0), reverse=True)
            agent._db_insert_papers(fresh)
            search.queue = fresh
            agent._log('INFO', f'Refilled candidate queue with {len(search.queue)} new papers')
        else:
            search.api_exhausted = True
    # After APIs exhausted, check DB for any remaining unused entries
    if search.queue:
        return True
    cached = [p for p in agent._db_get_unused(agent.topic) if p.get('id') not in search.tried_ids]
    if not cached:
        agent._log('WARNING', 'All sources exhausted — no essay reached 500 words')
        return False
    for p in cached:
        p['_score'] = agent._score_paper(p)
    cached.sort(key=lambda x: x.get('_score', 0), reverse=True)
    search.queue = cached
    agent._log('INFO', f'Pulled {len(search.queue)} candidates from DB cache')
    return True


def try_extract_candidate(agent, candidate) -> tuple:
    """Try to extract full text from one candidate.

    Returns (full_text, pdf_path, tmp_pdf, abstract_only). abstract_only=True
    means we fell back to the abstract — the paper has no accessible full text
    and should be blacklisted permanently (content_unavailable), not retried.
    """
    text, pdf_path, tmp_pdf = '', None, None
    abstract_only = False
    pdf_url = candidate.get('pdf_url') or ''
    full_text_url = candidate.get('full_text_url') or ''

    # Skip PDF download for known paywalled domains — they return 403 every time
    if pdf_url and agent._is_paywalled_url(pdf_url):
        agent._log('INFO', f'Skipping paywalled PDF URL: {pdf_url[:60]}')
        pdf_url = ''
    if full_text_url and full_text_url.endswith('.pdf') and agent._is_paywalled_url(full_text_url):
        agent._log('INFO', f'Skipping paywalled full-text URL: {full_text_url[:60]}')
        full_text_url = ''

    if pdf_url and pdf_url.endswith('.pdf') and _up.urlsplit(pdf_url).scheme in ('http', 'https'):
        text, pdf_path, tmp_pdf = _download_pdf_text(
            agent, pdf_url, start_kind='PDF', ctype_label='PDF URL', probe_kind='pdf'
        )
    elif full_text_url and _up.urlsplit(full_text_url).scheme in ('http', 'https'):
        if full_text_url.endswith('.pdf'):
            text, pdf_path, tmp_pdf = _download_pdf_text(
                agent, full_text_url, start_kind='PDF URL', ctype_label='full_text_url', probe_kind='full-text'
            )
        else:
            agent._log('INFO', f'Extracting text from HTML: {full_text_url[:60]}')
            text = agent._extract_full_text_html(full_text_url)

    # Fallback to abstract only if nothing else worked
    if not text or len(text.split()) < 100:
        abstract = candidate.get('abstract') or ''
        if abstract:
            agent._log('INFO', f'Falling back to abstract ({len(abstract.split())} words)')
            text = abstract
            abstract_only = True  # flag: no accessible full text, only abstract
    return text, pdf_path, tmp_pdf, abstract_only


def _download_pdf_text(agent, url, *, start_kind, ctype_label, probe_kind) -> tuple:
    """Download one PDF URL into a temp file and extract its text.

    The three labels are what the two original call sites (`pdf_url` and
    `full_text_url`) differed by, nothing else. Returns (text, pdf_path,
    tmp_pdf): `tmp_pdf` is the temp file that was created — so the caller can
    delete it — even when nothing could be downloaded, while `pdf_path` is
    None unless the download itself succeeded.
    """
    agent._log('INFO', f'Extracting text from {start_kind}: {url[:60]}')
    handle = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    tmp_pdf = handle.name
    handle.close()
    text, pdf_path = '', None
    try:
        # HEAD check: verify server actually returns a PDF before downloading
        try:
            # scheme audit: the caller already restricted `url` to http/https.
            head_req = _ur.Request(url, method='HEAD', headers={'User-Agent': 'Mozilla/5.0'})  # noqa: S310  # nosec B310
            with _ur.urlopen(head_req, timeout=10) as resp:  # noqa: S310  # nosec B310
                ctype = resp.headers.get('Content-Type', '')
            if 'pdf' not in ctype.lower() and 'octet-stream' not in ctype.lower():
                agent._log('WARNING', f'{ctype_label} returned Content-Type={ctype!r} — skipping: {url[:60]}')
                url = ''
        except Exception as _exc:
            _zyg_log.warning('%s content-type probe failed, downloading %s unchecked: %s', probe_kind, url, _exc)
        if url:
            with open(tmp_pdf, 'wb') as _fh:
                _fh.write(_hj.request(url, timeout=60))
            pdf_path = tmp_pdf
            text = agent._extract_full_text_pdf(tmp_pdf)
    except Exception as _pe:
        agent._log('WARNING', f'PDF download failed: {_pe}')
    return text, pdf_path, tmp_pdf


def prose_gate_metrics(full_text, word_count) -> ProseMetrics:
    """Citation- and equation-density of an essay, as the prose gate measures it.

    `prose_ratio` falls to 0 once inline citations account for every eighth
    word; `eq_density` is the share of non-blank lines that read like a formula
    or a measurement.
    """
    cite_hits = len(_CITE_RE.findall(full_text))
    prose_ratio = 1.0 - min((cite_hits * 8) / max(word_count, 1), 1.0)
    lines = full_text.splitlines()
    eq_lines = sum(1 for ln in lines if ln.strip() and _EQ_RE.search(ln))
    return ProseMetrics(cite_hits, prose_ratio, eq_lines, eq_lines / max(len(lines), 1))


def blacklist_verdict(abstract_only, word_estimate, word_count) -> tuple:
    """Why a candidate under 500 words is rejected: (reason, log line).

    'content_unavailable' — only the abstract was reachable, so the full paper
    is paywalled or gone and must never be retried; 'extraction_failure' — the
    word estimate promised ≥500 words, so the miss is transient and retryable;
    'too_short' — the paper genuinely is that short.
    """
    if abstract_only:
        return (
            'content_unavailable',
            f'Essay only has abstract ({word_count} words) — full text inaccessible, blacklisting permanently',
        )
    if word_estimate >= MIN_WORDS:
        return (
            'extraction_failure',
            f'Essay too short ({word_count} words < 500) — extraction failure '
            f'(word_estimate was {word_estimate}), will retry next run',
        )
    return 'too_short', f'Essay too short ({word_count} words < 500) — blacklisting permanently'


def discard_temp_pdf(path) -> None:
    """Delete a temp PDF if it is still there; a failed unlink is only logged."""
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError as _exc:
            _zyg_log.debug('temp pdf %s cleanup skipped: %s', path, _exc)


# ── Wikipedia fallback ───────────────────────────────────────────────────────


def wikipedia_subjects(topic) -> list:
    """The Wikipedia subjects to try for `topic`, shuffled, as a fresh list."""
    subjects = list(WIKI_SUBJECTS.get(topic, [topic]))
    random.shuffle(subjects)
    return subjects


def strip_wikipedia_appendix(text) -> str:
    """Drop the reference/appendix tail of an article — garbled citation noise."""
    return re.split(
        r'\n==\s*(References|Notes|See also|Bibliography|External links|Further reading|Footnotes|Citations)\s*==',
        text,
        flags=re.IGNORECASE,
    )[0].strip()


def _wikipedia_article(subject) -> str:
    """Fetch one article's plain-text extract with its appendix stripped."""
    url = (
        f'https://en.wikipedia.org/w/api.php?action=query'
        f'&titles={_up.quote(subject)}&prop=extracts&explaintext=1'
        f'&exsectionformat=plain&redirects=1&format=json'
    )
    data = _hj.request_json(url, headers={'User-Agent': 'ScholarlyBot/1.0'}, timeout=15)
    pages = data.get('query', {}).get('pages', {})
    text = ''
    for page in pages.values():
        text = page.get('extract', '') or ''
        break
    return strip_wikipedia_appendix(text)


def _capped_wiki_text(text, words) -> tuple:
    """The article text capped at 4000 words: (text, word_count)."""
    if words <= MAX_WORDS:
        return text, words
    return ' '.join(text.split()[:MAX_WORDS]), MAX_WORDS


def _wiki_selected(selected, subject) -> dict:
    """The paper record for a Wikipedia hit: titled after the article at worst."""
    if selected:
        selected['title'] = selected.get('title', '') or subject
        return selected
    return {'title': subject, 'authors': 'Wikipedia', 'abstract': ''}


def wikipedia_fallback(agent, full_text, word_count, selected) -> tuple:
    """Fetch a full Wikipedia article for the topic when no essay was long enough.

    Walks the topic's subjects in random order and takes the first one with at
    least 1500 words. Returns (full_text, word_count, selected) unchanged when
    nothing qualified.
    """
    agent._log('INFO', 'Attempting Wikipedia fallback for full text')
    for subject in wikipedia_subjects(agent.topic):
        if agent._is_stopped():
            break
        try:
            text = _wikipedia_article(subject)
            words = len(text.split())
            if words >= WIKI_MIN_WORDS:
                full_text, word_count = _capped_wiki_text(text, words)
                selected = _wiki_selected(selected, subject)
                agent._log('INFO', f'Wikipedia fallback success: {subject} ({word_count} words)')
                break
            agent._log('INFO', f'Wikipedia "{subject}": only {words} words — trying next')
        except Exception as _we:
            agent._log('WARNING', f'Wikipedia fallback failed for "{subject}": {_we}')
    return full_text, word_count, selected


# ── Step 6: the reporting bundle ─────────────────────────────────────────────


def papers_found_rows(all_papers) -> list:
    """The `papers_found` report rows for the paper pool, in pool order."""
    return [
        {
            'source': p.get('source_api', ''),
            'label': p.get('title', '')[:60],
            'chars': len(p.get('abstract', '')),
            'score': p.get('_score', 0),
            'doi': p.get('doi', ''),
        }
        for p in all_papers
    ]


def sources_used_labels(all_papers) -> list:
    """The distinct, non-empty `source_api` labels of the paper pool."""
    return list({p.get('source_api', '') for p in all_papers if p.get('source_api')})


def cap_essay(full_text, word_count, max_words=MAX_WORDS) -> tuple:
    """Cap the essay at `max_words`, on a paragraph boundary when one is near.

    Returns (full_text, word_count, capped); `capped` is False and the text
    untouched when it was already short enough.
    """
    if word_count <= max_words:
        return full_text, word_count, False
    words = full_text.split()
    # Find a paragraph boundary near the 4000-word mark
    target_char = len(' '.join(words[:max_words]))
    para_idx = full_text.rfind('\n\n', 0, target_char + 300)
    if para_idx > target_char // 2:
        full_text = full_text[:para_idx].strip()
    else:
        full_text = ' '.join(words[:max_words])
    return full_text, len(full_text.split()), True
