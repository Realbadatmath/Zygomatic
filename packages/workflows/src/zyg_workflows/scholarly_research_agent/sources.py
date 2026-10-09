# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""OpenAlex / Semantic Scholar / CORE API sources, scoring and dedup."""

from zyg_workflows.scholarly_research_agent.constants import (
    _hj,
    _up,
    _zyg_logging,
    contact_email,
    time,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.scholarly_research_agent')


class _SourcesMixin:
    # ── API Sources ───────────────────────────────────────────────────────────

    def _fetch_openalex(self, query: str) -> list:
        """Fetch papers from OpenAlex API. Uses Unpaywall to resolve real PDF URLs by DOI."""
        results = []
        _backoffs = [5, 15, 45]
        for _attempt in range(3):
            try:
                q_enc = _up.quote(query)
                _mail = contact_email()
                url = (
                    f'https://api.openalex.org/works?search={q_enc}'
                    f'&filter=is_oa:true&per_page=10'
                    f'&mailto={_up.quote(_mail)}'
                )
                data = _hj.request_json(url, headers={'User-Agent': f'ScholarlyBot/1.0 mailto:{_mail}'}, timeout=20)
                for work in data.get('results', []):
                    title = work.get('title') or ''
                    authors = ', '.join(
                        a.get('author', {}).get('display_name', '')
                        for a in work.get('authorships', [])[:5]
                        if a.get('author', {}).get('display_name')
                    )
                    abstract = self._reconstruct_abstract(work.get('abstract_inverted_index') or {})
                    oa_info = work.get('open_access') or {}
                    oa_url = oa_info.get('oa_url') or ''
                    doi = (work.get('doi') or '').replace('https://doi.org/', '')
                    license_ = oa_info.get('license') or ''
                    landing = (work.get('primary_location') or {}).get('landing_page_url') or ''

                    # Prefer direct PDF links; resolve via Unpaywall if we only have a DOI
                    pdf_url = oa_url if oa_url and oa_url.endswith('.pdf') else ''
                    full_url = oa_url or landing or ''

                    # Try Unpaywall for a better PDF URL when we have a DOI but no direct PDF
                    if doi and not pdf_url:
                        try:
                            _uw_url = f'https://api.unpaywall.org/v2/{doi}?email={_up.quote(_mail)}'
                            _uw_data = _hj.request_json(_uw_url, headers={'User-Agent': 'ScholarlyBot/1.0'}, timeout=10)
                            _best = _uw_data.get('best_oa_location') or {}
                            _uw_pdf = _best.get('url_for_pdf') or ''
                            if _uw_pdf:
                                pdf_url = _uw_pdf
                                full_url = _uw_pdf
                        except Exception as _exc:
                            _zyg_log.warning(
                                'unpaywall lookup for %s failed, keeping the original pdf url: %s', doi, _exc
                            )

                    # word_estimate from abstract length (abstract ≈ 5-10% of full paper)
                    word_est = max(len(abstract.split()) * 12, 1200) if abstract else 0
                    results.append(
                        {
                            'title': title,
                            'authors': authors,
                            'abstract': abstract,
                            'full_text_url': full_url,
                            'pdf_url': pdf_url,
                            'doi': doi,
                            'license': license_,
                            'source_api': 'openalex',
                            'word_estimate': word_est,
                        }
                    )
                break  # success
            except Exception as e:
                if '429' in str(e):
                    _wait = _backoffs[min(_attempt, len(_backoffs) - 1)]
                    self._log('WARNING', f'OpenAlex 429 — retry {_attempt + 1}/3 in {_wait}s')
                    time.sleep(_wait)
                else:
                    self._log('WARNING', f'OpenAlex API error: {e}')
                    break
        return results

    # Known paywalled domains — skip direct PDF download for these unless no other URL exists
    _PAYWALL_DOMAINS = {
        'cambridge.org',
        'oup.com',
        'academic.oup.com',
        'springer.com',
        'link.springer.com',
        'wiley.com',
        'onlinelibrary.wiley.com',
        'tandfonline.com',
        'jstor.org',
        'elsevier.com',
        'sciencedirect.com',
        'sagepub.com',
        'journals.sagepub.com',
        'nature.com',
        'science.org',
        'cell.com',
        'bmj.com',
        'thelancet.com',
        'annualreviews.org',
        'degruyter.com',
        'brill.com',
        'emerald.com',
        'mitpressjournals.org',
        'uchicago.edu',
        'press.uchicago.edu',
        'ucpress.edu',
        'online.ucpress.edu',
        'pnas.org',
        'royalsocietypublishing.org',
        'iopscience.iop.org',
        'aps.org',
        'journals.aps.org',
    }

    def _is_paywalled_url(self, url: str) -> bool:
        """Return True if the URL's domain is a known paywall."""
        if not url:
            return False
        try:
            from urllib.parse import urlparse

            domain = urlparse(url).netloc.lower().removeprefix('www.')
            return any(domain == pw or domain.endswith('.' + pw) for pw in self._PAYWALL_DOMAINS)
        except Exception:
            return False

    def _fetch_semantic_scholar(self, query: str) -> list:
        """Fetch papers from Semantic Scholar API. Skips immediately on 429 — no retry wait."""
        results = []
        for _attempt in range(3):
            try:
                q_enc = _up.quote(query)
                fields = 'title,authors,abstract,tldr,openAccessPdf,year,externalIds'
                url = f'https://api.semanticscholar.org/graph/v1/paper/search?query={q_enc}&fields={fields}&limit=10'
                data = _hj.request_json(url, headers={'User-Agent': 'ScholarlyBot/1.0'}, timeout=20)
                for paper in data.get('data', []):
                    title = paper.get('title') or ''
                    authors = ', '.join(a.get('name', '') for a in paper.get('authors', [])[:5])
                    abstract = paper.get('abstract') or ''
                    tldr = (paper.get('tldr') or {}).get('text') or ''
                    if tldr and len(abstract) < 100:
                        abstract = tldr
                    pdf_info = paper.get('openAccessPdf') or {}
                    pdf_url = pdf_info.get('url') or ''
                    ext_ids = paper.get('externalIds') or {}
                    doi = ext_ids.get('DOI') or ''
                    full_url = pdf_url or ''
                    word_est = max(len(abstract.split()) * 12, 1200) if abstract else 0
                    results.append(
                        {
                            'title': title,
                            'authors': authors,
                            'abstract': abstract,
                            'full_text_url': full_url,
                            'pdf_url': pdf_url,
                            'doi': doi,
                            'license': '',
                            'source_api': 'semantic_scholar',
                            'word_estimate': word_est,
                        }
                    )
                break  # success
            except Exception as e:
                if '429' in str(e):
                    self._log('WARNING', 'Semantic Scholar 429 — skipping (rate limited), using other sources')
                    break  # skip immediately, rely on OpenAlex + CORE
                else:
                    self._log('WARNING', f'Semantic Scholar API error: {e}')
                    break
        return results

    def _fetch_core_api(self, query: str) -> list:
        """Fetch papers from CORE API with corrected PDF URL format."""
        results = []
        _backoffs = [5, 15, 45]
        for _attempt in range(3):
            try:
                q_enc = _up.quote(query)
                url = f'https://api.core.ac.uk/v3/search/works/?q={q_enc}&limit=10'
                data = _hj.request_json(url, headers={'User-Agent': 'ScholarlyBot/1.0'}, timeout=20)
                for work in data.get('results', []):
                    title = work.get('title') or ''
                    authors_raw = work.get('authors') or []
                    if isinstance(authors_raw, list):
                        authors = ', '.join(
                            a.get('name', '') if isinstance(a, dict) else str(a) for a in authors_raw[:5]
                        )
                    else:
                        authors = str(authors_raw)
                    abstract = work.get('abstract') or ''
                    doi = work.get('doi') or ''
                    license_ = work.get('license') or ''

                    # CORE new URL format: use downloadUrl directly if present,
                    # otherwise construct from identifiers (oai field)
                    full_url = work.get('downloadUrl') or work.get('fullTextUrl') or ''
                    pdf_url = ''

                    # Prefer direct PDF links
                    if full_url and full_url.endswith('.pdf'):
                        pdf_url = full_url
                    elif not full_url:
                        # Try constructing from CORE id
                        core_id = work.get('id')
                        if core_id:
                            full_url = f'https://core.ac.uk/download/pdf/{core_id}.pdf'
                            pdf_url = full_url

                    # word estimate: use fullTextIdentifier word count if available,
                    # else estimate from abstract
                    full_text_len = work.get('fullTextLength') or 0
                    if full_text_len:
                        word_est = full_text_len // 6  # ~6 chars per word
                    else:
                        word_est = max(len(abstract.split()) * 12, 1200) if abstract else 0

                    results.append(
                        {
                            'title': title,
                            'authors': authors,
                            'abstract': abstract,
                            'full_text_url': full_url,
                            'pdf_url': pdf_url,
                            'doi': doi,
                            'license': license_,
                            'source_api': 'core',
                            'word_estimate': word_est,
                        }
                    )
                break  # success
            except Exception as e:
                if '429' in str(e):
                    _wait = _backoffs[min(_attempt, len(_backoffs) - 1)]
                    self._log('WARNING', f'CORE 429 — retry {_attempt + 1}/3 in {_wait}s')
                    time.sleep(_wait)
                else:
                    self._log('WARNING', f'CORE API error: {e}')
                    break
        return results

    def _reconstruct_abstract(self, abstract_inverted_index: dict) -> str:
        """Reconstruct abstract text from OpenAlex inverted index format."""
        if not abstract_inverted_index:
            return ''
        try:
            word_positions = []
            for word, positions in abstract_inverted_index.items():
                for pos in positions:
                    word_positions.append((pos, word))
            word_positions.sort(key=lambda x: x[0])
            return ' '.join(w for _, w in word_positions)
        except Exception:
            return ''

    # Science/STEM terms that should be rejected when topic is narrative history
    _HISTORY_REJECT_TERMS = [
        'ice core',
        'ice sheet',
        'glacier',
        'paleoclimate',
        'isotope',
        'geochemical',
        'geochemistry',
        'atmospheric lead',
        'pb)',
        'ppm',
        'ppb',
        'spectroscopy',
        'chromatography',
        'mass spectrometry',
        'carbon dating',
        'radiocarbon',
        'climate change',
        'global warming',
        'temperature proxy',
        'dendrochronology',
        'pollen record',
        'sediment core',
        'stratigraphy',
        'geology',
        'mineralogy',
        'molecular biology',
        'genomics',
        'proteomics',
        'biochemistry',
        'phylogeograph',
        'phylogenetic',
        'phylogeny',
        'ancient dna',
        'adna',
        'whole genome',
        'genome sequenc',
        'dna sequenc',
        'genome assembly',
        'snp',
        'snps',
        'allele',
        'haplogroup',
        'haplotype',
        'variant calling',
        'bioinformatics',
        'sequence alignment',
        'nucleotide',
        'mitochondrial dna',
        'clinical trial',
        'randomized controlled',
        'p-value',
        'confidence interval',
        'regression analysis',
        'meta-analysis',
        'epidemiology',
        'pathogen',
        'satellite imagery',
        'remote sensing',
        'gis mapping',
        # Evolutionary / behavioural ecology papers — history-adjacent but citation-dense, no narrative
        'operational sex ratio',
        'reproductive success',
        'mate choice',
        'mating strategy',
        'fitness cost',
        'life history theory',
        'behavioral ecology',
        'behavioural ecology',
        'sexual selection',
        'parental investment',
        'kin selection',
        'inclusive fitness',
        'evolutionary anthropolog',
        'evolutionary psychology',
        'human behavioral ecology',
        'ethnographic data',
        'cross-cultural sample',
        'standard cross-cultural',
        'variance in reproductive',
        'polygyny threshold',
        'resource defense polygyny',
        'inter-male competition',
        'male-male competition',
        'intrasexual competition',
        'natural selection pressure',
        'coalitionary killing',
        'lethal raiding',
        # Statistics-heavy social science
        'logistic regression',
        'multivariate analysis',
        'structural equation',
        'bayesian model',
        'monte carlo',
        'ordinary least squares',
        'fixed effects model',
        'instrumental variable',
        'difference-in-differences',
        'panel data',
        # Acoustics / signal processing / physics papers — appear in history journals
        # (ancient theatres, medieval bells, etc.) but are measurement papers, not narrative
        'acoustics',
        'reverberation time',
        'sound pressure level',
        'impulse response',
        'signal-to-noise',
        'frequency response',
        'room acoustics',
        'acoustic measurement',
        'sound absorption',
        'sound diffusion',
        'decibel',
        'octave band',
        'finite element',
        'computational fluid',
        'numerical simulation',
        'ray tracing',
        'wave equation',
        'fourier transform',
        'spectral analysis',
        'resonance frequency',
        'loudness level',
        'speech intelligibility',
        'noise reduction coefficient',
        'architectural acoustics',
        'open-air theatre acoustics',
        'theatre acoustics',
        # Engineering / materials science
        'tensile strength',
        'compressive strength',
        'shear modulus',
        'youngs modulus',
        'thermal conductivity',
        'viscosity',
        'porosity',
        'permeability',
        'scanning electron microscopy',
        'x-ray diffraction',
        'neutron diffraction',
        # Astronomy / astrophysics camouflaged as history
        'stellar evolution',
        'radioactive decay',
        'half-life',
        'luminosity',
        'spectral class',
        'redshift',
        'parsec',
        'light-year distance',
    ]

    # Strong topic-relevance terms — papers without ANY of these get penalised for history
    _HISTORY_REQUIRE_TERMS = [
        'war',
        'battle',
        'empire',
        'conquest',
        'king',
        'queen',
        'dynasty',
        'emperor',
        'army',
        'soldier',
        'warrior',
        'knight',
        'siege',
        'invasion',
        'civilization',
        'ancient',
        'medieval',
        'century',
        'historical',
        'history',
        'ruler',
        'kingdom',
        'rebellion',
        'revolution',
        'political',
        'power',
        'trade route',
        'expedition',
        'culture',
        'society',
        'plague',
        'migration',
        'religion',
        'myth',
        'legend',
        'rome',
        'greece',
        'egypt',
        'china',
        'mongol',
        'viking',
        'ottoman',
        'byzantine',
        'aztec',
        'inca',
        'mesopotamia',
        'babylon',
        'persia',
        'macedon',
        'carthage',
        # expanded — matches new query topics
        'pharaoh',
        'pyramid',
        'republic',
        'senate',
        'crusade',
        'crusader',
        'feudal',
        'samurai',
        'shogunate',
        'shogun',
        'barbarian',
        'nomad',
        'sultan',
        'caliph',
        'gladiator',
        'sparta',
        'athen',
        'hun',
        'norse',
        'sumer',
        'assyria',
        'akkad',
        'colonial',
        'tribe',
        'clan',
        'chieftain',
        'warlord',
        'citadel',
        'fortress',
        'chariot',
        'cavalry',
        'infantry',
        'general',
        'admiral',
        'fleet',
        'galley',
        'mesoamerica',
        'maya',
        'inca',
        'aztec',
        'toltec',
        'olmec',
        'pre-columbian',
        'shogunate',
        'samurai',
        'tokugawa',
        'edo',
        'feudal japan',
        'macedonian',
        'ptolemaic',
        'ayyubid',
        'carolingian',
        'plantagenet',
        'hun',
        'timurid',
        'mughal',
        'safavid',
        'abbasid',
        'umayyad',
    ]

    def _score_paper(self, paper: dict) -> int:
        """Score a paper dict for quality. Papers with word_estimate < 500 are disqualified."""
        if paper.get('word_estimate', 0) < 500:
            return -1  # disqualified — too short

        title = (paper.get('title') or '').lower()
        abstract = (paper.get('abstract') or '').lower()
        combined = title + ' ' + abstract

        # For history topic: reject science/STEM papers that sneak through
        if self.topic == 'history':
            for bad in self._HISTORY_REJECT_TERMS:
                if bad in combined:
                    return -1  # disqualified — science paper, not narrative history

            # Penalise papers with zero narrative history keywords
            if not any(req in combined for req in self._HISTORY_REQUIRE_TERMS):
                return -1  # disqualified — no history relevance at all

        score = 0
        full_url = paper.get('full_text_url') or paper.get('pdf_url') or ''
        if full_url:
            score += 3
        if len(abstract) >= 300:
            score += 2
        wc = paper.get('word_estimate', 0)
        if 500 <= wc <= 4000:
            score += 4  # sweet spot — good source material
        elif 4000 < wc <= 7000:
            score += 2  # acceptable — will be truncated
        elif wc > 7000:
            score += 1  # long — will be truncated
        if paper.get('doi'):
            score += 1

        # Bonus for strong narrative history keywords in title
        if self.topic == 'history':
            _title_hits = sum(1 for t in self._HISTORY_REQUIRE_TERMS if t in title)
            score += min(_title_hits, 3)

        # Relevance bonus for free-text directive topics: prefer papers that mention
        # the user's actual subject keywords in their title or abstract.
        if self._directive_kw:
            kw_hits = sum(1 for kw in self._directive_kw if kw in combined)
            score += min(kw_hits * 2, 8)

        return score

    def _deduplicate(self, papers: list) -> list:
        """Deduplicate papers by DOI or lowercase title."""
        seen_dois = set()
        seen_titles = set()
        unique = []
        for p in papers:
            doi = (p.get('doi') or '').strip()
            title = (p.get('title') or '').strip().lower()
            if doi and doi in seen_dois:
                continue
            if not doi and title and title in seen_titles:
                continue
            if doi:
                seen_dois.add(doi)
            if title:
                seen_titles.add(title)
            unique.append(p)
        return unique
