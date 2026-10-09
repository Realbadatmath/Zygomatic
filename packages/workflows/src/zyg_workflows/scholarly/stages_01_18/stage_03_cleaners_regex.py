# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The regex cleaners stage 3 runs over a raw source text, as free functions.

Every pattern here used to be compiled inside the closures `_script_cleaners`
returned, so none of it was reachable from a test. The bodies are unchanged —
the nested `def`s became module-level functions, the regexes they rebuilt on
every call became module constants, and the one long pipeline became the
orchestrator `_regex_clean` plus the five phase functions it calls in order:

    _normalize_spaced_headings → _strip_front_matter → _strip_boilerplate
    → _strip_structural_noise → _keep_prose_sentences

`_strip_citation_header` (phase 0a) and `_strip_llm_preamble` (used on the LLM
reply, not the source) stay separate entry points because stage 3 hands both
to its caller.
"""

from __future__ import annotations

import re

# ── _strip_citation_header patterns ─────────────────────────────────────────
# Citation lines: heavy use of 'and', commas, periods between names, year patterns
_CITATION_LINE_RE = re.compile(
    r'^(?:[A-Z][a-z]+,\s+[A-Z]\..*\band\b|'  # "Smith, J. and Jones, K."
    r'[A-Z][a-z]+\s+[A-Z]\.\s+and\s+|'  # "Smith J. and"
    r'\w+\s+\(\d{4}\)|'  # "something (2017)"
    r'Access from the|http|www\.|doi:|DOI:|'
    r'GeoHealth|pp\.\s*\d|Vol\.|Issue\s+\d|'
    r'Submitted|Accepted|Received|Published|Copyright|'
    r'University of|Institute of|Journal of)'
)
# Multilingual cover-page / institutional header keywords that mark non-prose lines.
# These are common in European university theses and conference proceedings.
_COVER_PAGE_RE = re.compile(
    r'(?i)^(?:'
    # Spanish/Portuguese academic header keywords
    r'FACULTAD\b|DEPARTAMENTO\b|TRABAJO\s+DE\s+FIN|TRABAJO\s+FIN|'
    r'GRADO\b|TRABAJO\s+DE\s+GRADO|UNIVERSIDAD\s+DE|UNIVERSITAT\b|'
    r'TUTOR\s*:|AUTOR\s*:|DIRECTORA?\s*:|V[ºo]\s*B[ºo]|'
    # French/Belgian academic header keywords
    r'FACULT[ÉE]\b|D[ÉE]PARTEMENT\b|UNIVERSIT[ÉE]\b|MASTER\b.*MENTION|'
    r'LICENCE\b|M[ÉE]MOIRE\s+DE|TH[ÈE]SE\s+DE|DIRECTEUR\s+DE|'
    # German academic header keywords
    r'HOCHSCHULE\b|FACHBEREICH\b|BACHELORARBEIT\b|MASTERARBEIT\b|'
    r'DIPLOMARBEIT\b|ERSTGUTACHTER|ZWEITGUTACHTER|BETREUER\b|'
    # Italian academic header keywords
    r'FACOLT[AÀ]\b|DIPARTIMENTO\b|CORSO\s+DI\s+LAUREA|TESI\s+DI\s+LAUREA|'
    r'RELATORE\b|CORRELATORE\b|LAUREANDO\b|'
    # Generic cross-language cover page patterns
    r'[A-Z]{3,}\s+de\s+[A-Z]|'  # "FACULTAD de FILOSOFÍA"
    r'Grado\s+en\s+[A-Z]|'  # "Grado en Estudios"
    r'\[V[ºo]\s*B[ºo]\b|'  # "[Vº Bº del tutor]"
    r'20\d\d\s*[-–]\s*20\d\d|'  # year range "2015 - 2016"
    r'(?:Tutor|Supervisor|Adviser|Director)\s*:|'
    r'(?:Student|Candidate|Candidate\'s?\s+name)\s*:|'
    r'core\.ac\.uk\b'
    r')'
)
# Journal/publisher banner lines — appear at top of ScienceDirect, Elsevier,
# Springer, PLOS etc. PDFs. They pass the prose check (>40% lowercase) but
# are not narrative. Must be skipped BEFORE the prose test runs.
_JOURNAL_HEADER_RE = re.compile(
    r'(?i)^(?:'
    r'Contents\s+lists?\s+available\b|'  # "Contents lists available at ScienceDirect"
    r'journal\s+homepage\s*:|'  # "journal homepage: www.cell.com/..."
    r'Research\s+article\b|'  # "Research article"
    r'Original\s+(?:research|article|paper)\b|'
    r'Review\s+article\b|'
    r'ScienceDirect\b|'
    r'Elsevier\b|'
    r'Springer\b.*\d{4}|'
    r'Available\s+online\s+at\b|'
    r'brought\s+to\s+you\s+by\s+CORE|'
    r'(?:Heliyon|PLOS\s+ONE|PLoS|PNAS|Nature|Lancet|Cell)\s+\d+|'  # "Heliyon 7 (2021)"
    r'\w+\s+\d+\s*\(\d{4}\)\s*[a-zA-Z]?\d+\b|'  # "Journal 7 (2021) e06580"
    r'(?:©|\(c\))\s*20\d\d\b|'  # "© 2021"
    r'Open\s+access\s+article\b|'
    r'This\s+is\s+an\s+open\s+access\b'
    r')'
)


def _is_prose_header_line(stripped: str) -> bool:
    """True when a non-empty stripped line reads as the start of real prose.

    A prose line starts with a capital, is longer than 40 characters, is more
    than 40% lowercase, and matches no citation pattern.
    """
    return bool(
        len(stripped) > 40
        and stripped[0].isupper()
        and sum(1 for c in stripped if c.islower()) / len(stripped) > 0.40
        and not _CITATION_LINE_RE.match(stripped)
        and not re.match(r'^[A-Z][a-z]+,\s+[A-Z][a-z]*\.?\s+(?:and|&)', stripped)
    )


def _first_prose_line(lines: list[str]) -> int:
    """Index of the first line of `lines` that reads as prose, else 0.

    Blank lines and lines matching the cover-page, citation or journal banner
    patterns are skipped; the scan stops at the first prose line.
    """
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # Skip any line that matches cover-page, citation, or journal banner patterns
        if _COVER_PAGE_RE.match(stripped):
            continue
        if _JOURNAL_HEADER_RE.match(stripped):
            continue
        if _is_prose_header_line(stripped):
            return i
    return 0


def _strip_citation_header(text: str) -> str:
    """Strip academic citation header from top of text.
    Detects patterns like: 'Author, A. and Author, B. (Year) Title. Journal...'
    Also strips multilingual university cover pages (Spanish, French, German, etc.)
    These come from raw PDF extraction where the header is the bibliographic record."""
    lines = text.splitlines()
    # Find the first line that looks like real prose (not a citation/author list)
    _first_prose = _first_prose_line(lines)
    if _first_prose > 0:
        return '\n'.join(lines[_first_prose:])
    return text


# ── phase 0b: two-column PDF spaced-letter section headings ─────────────────
#    ScienceDirect/Elsevier extract headers letter-by-letter with spaces:
#    "A B S T R A C T" → "ABSTRACT", "A R T I C L E I N F O" → "ARTICLEINFO"
#    Must run before the abstract-strip regex so it can find "ABSTRACT".
_SPACED_HEADINGS = (
    ('ABSTRACT', r'\bA\s+B\s+S\s+T\s+R\s+A\s+C\s+T\b'),
    ('ARTICLEINFO', r'\bA\s+R\s+T\s+I\s+C\s+L\s+E\s+I\s+N\s+F\s+O\b'),
    ('KEYWORDS', r'\bK\s+E\s+Y\s+W\s+O\s+R\s+D\s+S\b'),
    ('INTRODUCTION', r'\bI\s+N\s+T\s+R\s+O\s+D\s+U\s+C\s+T\s+I\s+O\s+N\b'),
    ('CONCLUSION', r'\bC\s+O\s+N\s+C\s+L\s+U\s+S\s+I\s+O\s+N\b'),
    ('DISCUSSION', r'\bD\s+I\s+S\s+C\s+U\s+S\s+S\s+I\s+O\s+N\b'),
    ('RESULTS', r'\bR\s+E\s+S\s+U\s+L\s+T\s+S\b'),
    ('METHODS', r'\bM\s+E\s+T\s+H\s+O\s+D\s+S\b'),
)


def _normalize_spaced_headings(text: str) -> str:
    """Collapse letter-by-letter PDF section headings back into one word.

    Takes the text after the citation header is gone, returns it with every
    `_SPACED_HEADINGS` pattern replaced by its compact form.
    """
    for _sh_compact, _sh_spaced in _SPACED_HEADINGS:
        text = re.sub(_sh_spaced, _sh_compact, text, flags=re.IGNORECASE)
    return text


# ── phase 2: where the narrative starts ─────────────────────────────────────
_INTRO_MARKERS = [
    # Case-insensitive "Introduction" as a standalone section header (after newline or period)
    r'[\n.][\s]*(?i:Introduction)\s*[:\n]+\s*[A-Z]',
    r'[\n.][\s]*(?i:Introduction)\s+[A-Z]',  # "Introduction The…"
    # Numbered section "1. Introduction" — works inline OR after newline
    # (?<!\w) ensures we don't match "101. Introduction" or "Reintroduction"
    r'(?<!\w)1[\.:]\s+(?i:Introduction)\b',
    r'[\n.][\s]*(?i:Preface)\s*[\n:]+\s*[A-Z]',
    r'[\n.][\s]*(?i:Foreword)\s*[\n:]+\s*[A-Z]',
    r'[\n\s](?:Chapter|CHAPTER)\s+(?:I|1|One)\b',
]


def _find_intro_pos(text: str) -> int:
    """Offset in `text` where the narrative begins, or -1 when nothing matches.

    Tries the `_INTRO_MARKERS` section headers first; failing that, falls back
    to the first run of ≥15 words that reads as prose (front matter is
    typically short bursts of names, numbers and foreign-language text).
    """
    _intro_pos = -1
    for _pat in _INTRO_MARKERS:
        _m = re.search(_pat, text)
        if _m:
            _intro_pos = _m.start()
            break
    # If no header marker, find first run of ≥10 English words in a row
    # (front matter is typically short bursts of names/numbers/Polish text)
    if _intro_pos < 0:
        for _para in re.split(r'\n{2,}|\. {2,}', text):
            _para = _para.strip()
            if (
                len(_para) >= 80
                and _para[0].isupper()
                and sum(1 for c in _para if c.islower()) / max(len(_para), 1) > 0.45
                and len(_para.split()) >= 15
            ):
                _intro_pos = text.find(_para)
                break
    return _intro_pos


def _strip_front_matter(text: str) -> str:
    """Drop everything before the narrative: hyphen hints, back matter, abstract.

    Takes the heading-normalised text and returns it with soft hyphens
    repaired, Wikipedia/academic back-matter sections cut off, the
    abstract and keyword sections removed, and the lead-in before the
    introduction marker trimmed away.
    """
    # ── 0. Repair soft hyphens from PDF typesetting (­ = U+00AD line-break hints)
    text = re.sub(r'\u00ad\s*', '', text)  # remove soft hyphen + any trailing space, rejoin split words

    # ── 1. Strip Wikipedia / academic section headers and everything after them
    text = re.split(
        r'\n==\s*(References|Notes|See also|Bibliography|External links|Further reading|Footnotes|Citations)\s*==',
        text,
        flags=re.IGNORECASE,
    )[0]

    # ── 2. Strip PDF front matter — everything before the first real prose paragraph.
    #    Real prose: a sentence-starting paragraph with ≥10 words and ≥40% lowercase.
    #    Also handles flat (newline-free) PDF extracts via keyword search.
    # Strip ABSTRACT / RESUMEN / RÉSUMÉ sections entirely — they are not narrative content.
    # Must run BEFORE intro-marker search so the abstract isn't mistaken for prose.
    text = re.sub(
        r'(?im)^(?:ABSTRACT|Abstract|RESUMEN|RÉSUMÉ|SOMMAIRE|ZUSAMMENFASSUNG)(?:[\s:.\-—]+).*?'
        r'(?=\n(?:INTRODUCTION|Introduction|CHAPTER|Chapter|1\.|1\s+INTRODUCTION|Keywords?:|'
        r'KEYWORDS:|Index\s+Terms?:|(?:[A-Z][a-z]{3,}\s){2,}[A-Z][a-z]{3,})|$)',
        '',
        text,
        flags=re.DOTALL,
    )
    # Strip KEYWORDS / INDEX TERMS sections (short list not suitable for narration)
    text = re.sub(r'(?im)^(?:Keywords?|Index\s+Terms?|KEY\s*WORDS)\s*:.*?(?=\n\n|\Z)', '', text, flags=re.DOTALL)

    _intro_pos = _find_intro_pos(text)
    if _intro_pos > 0:
        text = text[_intro_pos:].lstrip()
    return text


# ── phase 3-13: line and inline boilerplate ─────────────────────────────────
def _is_garbled(line: str) -> bool:
    """True when a line is garbled PDF encoding: ≥12 chars and <35% lowercase."""
    stripped = line.strip()
    if len(stripped) < 12:
        return False
    _lc = sum(1 for c in stripped if c.islower())
    return _lc / len(stripped) < 0.35


def _strip_boilerplate(text: str) -> str:
    """Remove acknowledgements, footnotes, citations and publisher contact lines.

    Takes the text with its front matter gone and returns it with rules 3-13
    applied in their original order, ending with the garbled-line filter and
    the whitespace collapse.
    """
    # ── 3. Strip acknowledgements sentence (single-line — never cross paragraph boundaries)
    text = re.sub(r'I would like to (?:extend|express|thank)[^\n]*\n?', '', text)
    # Strip *** section dividers
    text = re.sub(r'\*{3,}[^\n]*', '', text)
    # Strip funding/grant notices
    text = re.sub(r'(?s)This (?:book|work|study) was written as part of a research project.*?(?=\n{2,}|\Z)', '', text)
    text = re.sub(r'Decision number DEC-\S+[^\n]*', '', text)

    # ── 4. Strip spaced-letter abbreviations / Polish publisher series names
    #    e.g. "B Y Z A N T I N A L O D Z I E N S I A" or "C H A P T E R I"
    text = re.sub(r'(?:[A-Z] ){3,}[A-Z]\b', '', text)

    # ── 5. Strip inline footnote number superscripts attached to words (e.g. "Panium2,")
    text = re.sub(r'(?<=[a-zA-Z])\d{1,2}(?=[,\.\s;:\)])', '', text)

    # ── 6. Strip spaced-letter academic author names in footnotes
    #    e.g. "R.C. B l o c k l e y, Fragmentary..." or "M. K u l i k o w s k i"
    text = re.sub(r'(?:[A-Z]\.\s*)+[A-Z]\s+(?:[a-z]\s+){2,}[a-z]+[,\.].*', '', text)

    # ── 7. Strip full footnote lines: start with digit + capital author name + year
    #    e.g. "1 M. Kulikowski, Notitia Dignitatum, Hi 49, 2000, p. 358"
    text = re.sub(r'(?im)^\d{1,2}\s+[A-Z][a-z\.]+.*\d{4}.*$', '', text)

    # ── 8. Remove inline citations: (Author, 2001), [1], [1,2,3]
    text = re.sub(r'\([A-Z][a-z]+(?:\s+et\s+al\.?)?,\s*\d{4}[a-z]?\)', '', text)
    text = re.sub(r'\[\d+(?:,\s*\d+)*\]', '', text)

    # ── 9. Remove figure/table references
    text = re.sub(r'(?i)\b(see\s+)?(Figure|Fig\.?|Table|Chart)\s*\d+', '', text)

    # ── 10. Remove publisher/contact boilerplate
    text = re.sub(r'(?im)^(?:ISBN|www\.|e-mail:|phone:|fax:|cell phone:).*$', '', text)
    text = re.sub(r'[\w\.\-]+@[\w\.\-]+\.\w+', '', text)  # email addresses
    text = re.sub(r'https?://\S+', '', text)  # URLs
    text = re.sub(r'©[^\n]*', '', text)  # copyright lines

    # ── 11. Remove section header remnants and superscripts
    text = re.sub(
        r'(?im)^(Abstract|Keywords|References|Bibliography|Contents):.*?(?=\n\n|\Z)',
        '',
        text,
        flags=re.DOTALL,
    )
    text = re.sub(r'[¹²³⁴⁵⁶⁷⁸⁹⁰]', '', text)
    text = re.sub(r'\[edit\]', '', text)

    # ── 12. Strip garbled PDF encoding lines (>65% non-lowercase)
    text = '\n'.join(ln for ln in text.splitlines() if not _is_garbled(ln))

    # ── 13. Collapse excess whitespace
    return re.sub(r'\n{3,}', '\n\n', text)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ── Layer A: targeted structural patterns missed by rules 1-13 ──────────
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# A2. Verbatim publisher/repository banners (whole phrases, not just keywords)
_BANNER_PHRASES = [
    r'Contents\s+lists\s+available\s+at\s+\S+',
    r'journal\s+homepage\s*:\s*\S+',
    r'Research\s+article\b',
    r'brought\s+to\s+you\s+by\s+CORE',
    r'View\s+metadata,?\s+citation\s+and\s+similar\s+papers',
    r'provided\s+by\s+Repositorio\s+\S+',
    r'provided\s+by\s+[A-Za-z\s]+(?:University|Repository|Institute)[^\n]*',
    r'Published\s+by\s+Elsevier\b[^\n]*',
    r'Published\s+by\s+[A-Z][a-zA-Z\s]+(?:Press|Ltd|Inc|GmbH|BV)[^\n]*',
    r'Open\s+access\s+article\s+under\s+the\s+CC\b[^\n]*',
    r'This\s+is\s+an\s+open\s+access\s+article[^\n]*',
    r'Received\s+\d+\s+\w+\s+\d{4}[^\n]*',  # "Received 24 November 2020..."
    r'doi\s*:\s*10\.\d{4,}[^\s]*',
    r'10\.\d{4,}/[^\s]+',  # bare DOI
    r'\bA\s+R\s+T\s+I\s+C\s+L\s+E\s+I\s+N\s+F\s+O\b',
    r'\bA\s+B\s+S\s+T\s+R\s+A\s+C\s+T\b',
]


def _is_address_fragment(seg: str) -> bool:
    """True when a segment is a postal address fragment rather than prose.

    A4. Address lines — postal codes give these away. European: 5-digit code +
    city. US: city, State 2-letter + 5-digit. Only strip the segment if it ALSO
    lacks a verb (so "In 1945, Berlin 10115 fell" stays).
    """
    _has_postal = bool(re.search(r'\b\d{4,5}\b', seg))
    _has_verb = bool(
        re.search(
            r'\b(?:was|were|is|are|had|have|has|did|became|found|shows?|made|'
            r'known|said|lived|died|ruled|fought|built|created|used|called|'
            r'described|introduced|represents?|enables?|indicates?|seems?|'
            r'suggests?|developed|appeared|dominated|conquered|established)\b',
            seg,
            re.IGNORECASE,
        )
    )
    return _has_postal and not _has_verb


def _drop_address_fragments(text: str) -> str:
    """Drop address-like sentences paragraph by paragraph.

    Applied per paragraph to avoid killing large prose blocks that contain
    numbers; returns the text rebuilt from the kept segments.
    """
    _paras = text.split('\n\n')
    _cleaned_paras = []
    for _para in _paras:
        _segs = [s.strip() for s in re.split(r'(?<=[.!?])\s+', _para) if s.strip()]
        _kept = [s for s in _segs if not _is_address_fragment(s)]
        _cleaned_paras.append(' '.join(_kept))
    return '\n\n'.join(p for p in _cleaned_paras if p.strip())


def _strip_structural_noise(text: str) -> str:
    """Apply Layer A: journal codes, banners, affiliations, bare section labels.

    Takes the de-boilerplated text and returns it with rules A1-A7 applied in
    their original order.
    """
    # A1. Journal volume/issue/page codes: "Heliyon 7 (2021) e06580", "Vol. 12 No. 3 (2019)"
    text = re.sub(r'\b[A-Za-z]+\s+\d+\s*\(\d{4}\)\s*[a-zA-Z]?\d+\b', '', text)
    text = re.sub(r'\bVol(?:ume)?\.?\s*\d+[,\s]+(?:No\.?\s*\d+[,\s]+)?\(\d{4}\)', '', text, flags=re.IGNORECASE)

    # A2. Verbatim publisher/repository banners (whole phrases, not just keywords)
    for _bp in _BANNER_PHRASES:
        text = re.sub(_bp, '', text, flags=re.IGNORECASE)

    # A3. Affiliation superscript markers attached to names: "Cartwright d,e,∗ a Posgrado"
    #     Pattern: word followed by single-letter,digit combos with commas and ∗
    text = re.sub(r'(?<=[A-Za-z])\s+[a-z,∗†‡§]+\s+[a-z]\s+(?=[A-Z][a-z])', ' ', text)

    # A4. Address lines, per paragraph
    text = _drop_address_fragments(text)

    # A5. Standalone section numbers / bare alphanumeric labels on their own
    #     e.g. "1.", "2.", "4c.", "iii.", "(a)" at start of a segment
    text = re.sub(r'(?m)^\s*(?:\d{1,2}\.?\s*){1,2}\s*$', '', text)
    text = re.sub(r'(?m)^\s*[ivxlIVXL]{1,5}\.?\s*$', '', text)  # Roman numerals alone
    text = re.sub(r'(?m)^\s*\([a-z]\)\s*$', '', text)  # "(a)", "(b)" alone

    # A6. "Corresponding author at:" lines that split across sentence boundaries
    text = re.sub(r'\*?\s*Corresponding\s+author\s+at:[^\n]*\n?', '', text, flags=re.IGNORECASE)

    # A7. "et al." name fragments left after citation stripping: "González et al. Heliyon 7"
    return re.sub(r'[A-Z][a-z\-]+(?:,\s*[A-Z][a-z\-]+)*(?:\s+et\s+al\.?)\s*[^\n]*', '', text)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ── Layer B: sentence quality gate — last line of defence ────────────────
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Split everything into individual sentence-ish segments and evaluate each.
# Strategy is tiered by length — crucially it never inspects name content:
#
#   < 6 words  → always DROP  (bare fragments, labels, single names)
#   6–14 words → require a prose verb  (catches "University of Granada, Spain")
#   ≥ 15 words → require ≥ 3 English function words
#                (real prose is always rich in function words; foreign-language
#                 affiliation blocks in Italian/Spanish have very few English ones)
#
# "Alexander the Great conquered Persia in 334 BC."  → 9 words, has verb → KEPT
# "Rojo-Garibaldi, C. Rangoni, D.L."                 → 4 words            → DROP
# "04510, Mexico b Istituto per la Microelettronica…" → 60 words, 0 English
#                                                        function words     → DROP

_PROSE_VERBS_B = re.compile(
    r'\b(?:was|were|is|are|am|be|been|being|'
    r'had|have|has|did|do|does|'
    r'became|found|show(?:ed|s|n)?|made|known|said|believed|written|'
    r'built|lived|died|ruled|fought|created|appeared|described|'
    r'introduc(?:ed|es)?|represents?|enables?|indicates?|seems?|suggests?|'
    r'developed|dominated|conquered|established|declared|argued|'
    r'wrote|published|claimed|proposed|demonstrated|discovered|'
    r'allowed|led|brought|gave|took|came|went|used|called|named|'
    r'considered|regarded|noted|observed|stated|reported|'
    r'produced|formed|supported|included|continued|remained|fell|'
    r'began|ended|passed|spread|changed|played|held|reached|left|'
    r'sent|lost|won|saw|thought|knew|understood|learned|'
    r'discuss(?:ed|es)?|follow(?:ed|s)?|provid(?:ed|es)?|'
    r'present(?:ed|s)?|refer(?:red|s)?|explain(?:ed|s)?|'
    r'continu(?:ed|es)?|extend(?:ed|s)?|contain(?:ed|s)?|'
    r'compar(?:ed|es)?|add(?:ed|s)?|connect(?:ed|s)?|'
    r'mean(?:s|t)?|require(?:d|s)?|need(?:ed|s)?|'
    r'constitut(?:ed|es)?|calculat(?:ed|es)?|represents?|'
    r'show(?:s|ed|n)?|tell|told|find|gives?|sees?|'
    r'keep|kept|read|reads?|write|writes?|makes?|takes?|gets?)\b',
    re.IGNORECASE,
)

# Common English function words — present in almost every English prose sentence;
# absent from raw address/affiliation blocks written in Italian, Spanish, Latin etc.
_FUNC_WORD_B = re.compile(
    r'\b(?:the|a|an|in|of|to|and|that|which|for|with|by|from|this|'
    r'these|their|its|at|or|but|on|as|it|not|into|about|than|'
    r'through|after|before|between|under|over|also|only|such|more|'
    r'most|other|when|where|while|although|because|however|therefore|'
    r'both|each|every|any|all|some|so|if|then|thus|hence|yet|still|'
    r'already|often|always|never|very|just|even|those|them|they|'
    r'he|she|we|our|us|his|her|my|your)\b',
    re.IGNORECASE,
)


def _is_prose_sentence(seg: str) -> bool:
    """True when a sentence-ish segment passes the Layer B quality gate.

    Under 6 words always fails; under 45% alphabetic characters always fails;
    6-14 words need a `_PROSE_VERBS_B` match; 15 or more need at least three
    `_FUNC_WORD_B` matches.
    """
    words = seg.split()
    wc = len(words)
    # Always drop very short fragments
    if wc < 6:
        return False
    # Reject if >55% of characters are non-alphabetic
    _alpha = sum(1 for c in seg if c.isalpha())
    if _alpha / max(len(seg), 1) < 0.45:
        return False
    if wc < 15:
        # Short segments: require a known prose verb
        return bool(_PROSE_VERBS_B.search(seg))
    # Long segments (≥15 words): require ≥3 English function words
    # All real English prose easily passes this; multilingual affiliation
    # blocks typically score 0–1.
    return len(_FUNC_WORD_B.findall(seg)) >= 3


def _keep_prose_sentences(text: str) -> str:
    """Rebuild the text paragraph-by-paragraph from its prose sentences only.

    Takes the Layer A output and returns the stripped join of the paragraphs
    that still hold at least one `_is_prose_sentence` segment.
    """
    _final_paras = []
    for _para in text.split('\n\n'):
        _para = _para.strip()
        if not _para:
            continue
        _sents = [s.strip() for s in re.split(r'(?<=[.!?])\s+', _para) if s.strip()]
        _good = [s for s in _sents if _is_prose_sentence(s)]
        if _good:
            _final_paras.append(' '.join(_good))
    return '\n\n'.join(_final_paras).strip()


def _wiped_out_content(result: str, original_text: str) -> bool:
    """True when cleaning kept less than 10% of the original word count.

    Safety check for non-English / Cyrillic essays: the threshold is 10%
    because mathematical/technical papers legitimately have ~15% prose
    sentences, and an empty string crashes TTS.
    """
    _orig_wc = len(original_text.split()) if original_text else 0
    return _orig_wc > 0 and len(result.split()) < max(50, _orig_wc * 0.10)


def _regex_clean(text: str, original_text: str = None) -> str:
    """Run the whole regex cleaning pipeline over a raw source text.

    `original_text` defaults to `text` and is only used by the safety check: if
    the five phases wipe out more than 90% of the words, the original is
    returned stripped instead of a near-empty script.
    """
    if original_text is None:
        original_text = text
    # ── 0a. Strip citation header (author lists, bibliographic records at top of PDFs)
    text = _strip_citation_header(text)
    text = _normalize_spaced_headings(text)
    text = _strip_front_matter(text)
    text = _strip_boilerplate(text)
    text = _strip_structural_noise(text)
    result = _keep_prose_sentences(text)

    # ── Safety: if cleaning wiped out most content (e.g. non-English / Cyrillic essay),
    #    return the original rather than an empty string that crashes TTS.
    if _wiped_out_content(result, original_text):
        return original_text.strip()
    return result


_PREAMBLE_PATTERNS = [
    r'^here\s+is\s+(the\s+)?(cleaned|edited|full|complete).*?(?:essay|text)[:\s]*\n?',
    r'^(cleaned|edited)\s+(essay\s+)?text[:\s]*\n?',
    r'^certainly[!,.].*?\n',
    r'^sure[!,.].*?\n',
    r'^of\s+course[!,.].*?\n',
    r'^i\'ve\s+(cleaned|edited|removed).*?\n',
    r'^\[note:.*?\]\s*\n?',
    r'^note:.*?\n',
]


def _strip_llm_preamble(text: str) -> str:
    """Strip a chat assistant's lead-in ("Here is the cleaned essay:") from a reply."""
    for pat in _PREAMBLE_PATTERNS:
        text = re.sub(pat, '', text, flags=re.IGNORECASE | re.MULTILINE)
    return text.strip()
