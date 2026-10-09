# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""HTML/MHTML page parsing and naming a folder after the character on the page.

Moved verbatim out of medusa_resources.py (original lines 519-757, 760-1038).
"""

import os
import re
import email
import email.parser
import urllib.parse

from html.parser import HTMLParser

from .config import DEFAULT_STOP_PHRASES, MAX_PAGE_BYTES, _ABS_IMG_RE, _CSS_URL_RE, _JUNK_BLOCK_RE, _SAVED_FROM_RE
from .urls import _best_from_srcset, _looks_like_image

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__package__ or 'medusa_resources')


# ── Page parsing ────────────────────────────────────────────────────────────
class _ImageRefParser(HTMLParser):
    """Collects candidate image URLs (and a <base href>) from a saved page.

    Deliberately greedy about <a href> too: gallery pages almost always show a
    small thumbnail wrapped in a link to the full-size file, and the link is the
    picture actually worth keeping.
    """

    _SRC_ATTRS = (
        'src',
        'data-src',
        'data-original',
        'data-lazy-src',
        'data-lazy',
        'data-url',
        'data-image',
        'data-full',
        'data-large',
        'data-hires',
        'data-hi-res',
        'data-echo',
    )

    # Elements that never nest, so they must not move the depth counter that
    # drives junk-block suppression.
    _VOID = frozenset(
        ('img', 'br', 'hr', 'input', 'meta', 'link', 'source', 'area', 'base', 'col', 'embed', 'param', 'track', 'wbr')
    )

    # HTMLParser hands the BODY of these to handle_data as if it were page
    # text. A stop phrase must never be matched inside them: a real page's
    # inline JavaScript mentions "advertisement", "sponsor" and "related" all
    # over the place, and matching one cuts the document above the gallery and
    # collects nothing at all. (Measured: without this, a live metarthunter
    # gallery cut at line 80 on "advertis" and returned 0 pictures.)
    _QUIET = frozenset(('script', 'style', 'noscript', 'template', 'svg'))

    def __init__(self, stop_phrases=(), drop_junk=True):
        super().__init__(convert_charrefs=True)
        self.items = []  # {url, how, pos}
        self._seen = set()
        self._quiet = 0
        self.base_href = None
        self.cut_pos = None  # first stop-phrase position; None = no cut
        self.cut_reason = ''
        self._stop = tuple(p.lower() for p in stop_phrases if p)
        self._drop_junk = drop_junk
        self._depth = 0
        self._junk_from = None  # depth at which the junk block opened
        self.junk_blocks = []  # what was suppressed, for the preview

    @property
    def in_junk(self):
        return self._junk_from is not None

    def _add(self, raw, how):
        raw = (raw or '').strip()
        if not raw or raw.startswith(('data:', 'javascript:', 'about:', '#')):
            return
        if self.in_junk:
            return
        if raw not in self._seen:
            self._seen.add(raw)
            self.items.append({'url': raw, 'how': how, 'pos': self.getpos()})

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or '') for k, v in attrs}

        if tag in self._QUIET:
            self._quiet += 1

        if tag not in self._VOID:
            self._depth += 1
            # A block whose id/class advertises it as related/sponsored/etc is
            # suppressed wholesale — that is where "pictures we don't want"
            # live even when no stop-phrase heading precedes them.
            if self._drop_junk and not self.in_junk:
                label = f'{tag} {a.get("id", "")} {a.get("class", "")}'
                if tag in ('footer', 'aside') or _JUNK_BLOCK_RE.search(label):
                    self._junk_from = self._depth
                    self.junk_blocks.append(
                        {'tag': tag, 'id': a.get('id', '')[:60], 'class': a.get('class', '')[:80], 'pos': self.getpos()}
                    )

        if tag == 'base':
            if a.get('href') and not self.base_href:
                self.base_href = a['href'].strip()
            return

        if tag in ('img', 'source', 'image'):
            for key in self._SRC_ATTRS + ('xlink:href', 'href'):
                if a.get(key):
                    self._add(a[key], 'img')
            for key in ('srcset', 'data-srcset'):
                if a.get(key):
                    self._add(_best_from_srcset(a[key]), 'srcset')
        elif tag == 'a':
            if a.get('href') and _looks_like_image(a['href']):
                self._add(a['href'], 'link')
        elif tag == 'link':
            rel = a.get('rel', '').lower()
            if a.get('href') and (
                'image' in a.get('as', '').lower()
                or 'image_src' in rel
                or ('preload' in rel and _looks_like_image(a['href']))
            ):
                self._add(a['href'], 'head')
        elif tag == 'meta':
            prop = (a.get('property') or a.get('name') or '').lower()
            if a.get('content') and prop in (
                'og:image',
                'og:image:url',
                'og:image:secure_url',
                'twitter:image',
                'twitter:image:src',
            ):
                self._add(a['content'], 'head')

        if 'url(' in a.get('style', ''):
            for match in _CSS_URL_RE.finditer(a['style']):
                self._add(match.group(2), 'css')

    def handle_endtag(self, tag):
        if tag in self._QUIET:
            self._quiet = max(0, self._quiet - 1)
        if tag in self._VOID:
            return
        if self.in_junk and self._depth <= self._junk_from:
            self._junk_from = None
        self._depth = max(0, self._depth - 1)

    def handle_startendtag(self, tag, attrs):
        # <div/> style self-closing: run the attribute logic without letting it
        # open a block that never closes.
        depth_before, junk_before = self._depth, self._junk_from
        self.handle_starttag(tag, attrs)
        self._depth, self._junk_from = depth_before, junk_before

    def handle_data(self, data):
        """Watch the visible text for the heading that ends the wanted run.

        Text inside an already-suppressed junk block is ignored: a promo strip
        headed "Our Partners" is excised in place, and must NOT also end the
        document — otherwise one sponsored box above the gallery would cut the
        whole page to nothing.
        """
        if self.cut_pos is not None or not self._stop or self.in_junk or self._quiet:
            return
        flat = ' '.join(data.split()).lower()
        # A section boundary is a HEADING, so it is short. Requiring that stops
        # a phrase buried in a paragraph of prose from ending the document.
        if not flat or len(flat) > 60:
            return
        for phrase in self._stop:
            if phrase in flat:
                self.cut_pos = self.getpos()
                self.cut_reason = phrase
                return


def _abs_offset(text, pos):
    """(line, col) from HTMLParser.getpos() -> absolute index into text."""
    line, col = pos
    index = 0
    for _ in range(max(0, line - 1)):
        newline = text.find('\n', index)
        if newline < 0:
            return len(text)
        index = newline + 1
    return min(len(text), index + col)


def _parse_html(text, base_url, deep_scan=False, stop_phrases=None, drop_junk=True):
    """Find the pictures a page shows, in document order.

    Returns (items, base_url, cut) where each item is
    {url, how, pos} and `how` says where it came from (img / srcset / link /
    head / css / script) so a preview can explain the count. Only the run
    BEFORE the first stop phrase is returned: a gallery page is typically
    "<character> …wanted pictures… / Related Galleries …unwanted… / Free sites
    …unwanted…", and everything past that first heading is somebody else's set.
    """
    if stop_phrases is None:
        stop_phrases = DEFAULT_STOP_PHRASES
    parser = _ImageRefParser(stop_phrases, drop_junk)
    try:
        parser.feed(text)
        parser.close()
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)

    if not base_url:
        base_url = parser.base_href or ''
    if not base_url:
        found = _SAVED_FROM_RE.search(text[:8192])
        if found and found.group('url').lower().startswith('http'):
            base_url = found.group('url')

    cut_index = len(text)
    cut = None
    if parser.cut_pos is not None:
        cut_index = _abs_offset(text, parser.cut_pos)
        cut = {'phrase': parser.cut_reason, 'line': parser.cut_pos[0]}

    candidates = [item for item in parser.items if parser.cut_pos is None or item['pos'] < parser.cut_pos]
    dropped_after_cut = len(parser.items) - len(candidates)

    if deep_scan:
        # Gallery pages sometimes carry the real full-size URLs inside a JSON
        # blob in a <script>, where no tag parser will ever see them (JSON
        # escapes the slashes, hence the unescape). This is also the single
        # biggest source of over-collection — the same blob often lists every
        # OTHER gallery on the site — so it is off by default and still bound
        # by the cut.
        for match in _ABS_IMG_RE.finditer(text[:cut_index].replace('\\/', '/')):
            candidates.append({'url': match.group(0), 'how': 'script', 'pos': parser.cut_pos or (0, 0)})

    out, seen = [], set()
    for item in candidates:
        try:
            absolute = urllib.parse.urljoin(base_url, item['url']) if base_url else item['url']
        except ValueError as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
        absolute = absolute.split('#', 1)[0]
        if not absolute.lower().startswith(('http://', 'https://')):
            continue
        if absolute not in seen:
            seen.add(absolute)
            out.append({'url': absolute, 'how': item['how']})

    stats = {
        'cut': cut,
        'dropped_after_cut': dropped_after_cut,
        'junk_blocks': parser.junk_blocks[:20],
        'junk_block_count': len(parser.junk_blocks),
    }
    return out, base_url, stats


# ── Naming a folder after the character on the page ─────────────────────────
# One folder == one character (medusa_import/README.txt), so the folder wants
# the model's name, not the gallery's headline. Three signals, strongest first,
# all present on a real gallery page:
#   1. <a href=".../model/agatha-vega/">Agatha Vega</a>      the model link
#   2. <h1>Agatha Vega in Met Art set To The Side</h1>       name leads the h1
#   3. <title>Agatha Vega Nude in … at Metart Hunter</title> name leads the title
# A candidate whose slug also appears in the page's own URL is trusted far more
# than one that does not — that cross-check is what makes this reliable rather
# than a guess.
_MODEL_HREF_RE = re.compile(
    r'/(?:model|models|star|stars|pornstar|pornstars|actress|actresses|girl|'
    r'girls|babe|babes|performer|performers|profile)/[^/]+',
    re.I,
)
_NAME_SHAPE_RE = re.compile(r"^[A-Z][\w'’.-]*(?:\s+[A-Z][\w'’.-]*){0,3}$")
# "Agatha Vega in Met Art set …", "Agatha Vega Nude in …", "Agatha Vega -- …"
_NAME_LEAD_RE = re.compile(
    r"^\s*([A-Z][\w'’.-]+(?:\s+[A-Z][\w'’.-]+){0,2})\s+"
    r'(?:in|nude|naked|at|for|poses|posing|strips|by|-|–|—|\|)\b'
)
_NOT_A_NAME = frozenset(
    (
        'home',
        'gallery',
        'galleries',
        'video',
        'videos',
        'photo',
        'photos',
        'model',
        'models',
        'star',
        'stars',
        'pornstar',
        'pornstars',
        'girl',
        'girls',
        'babe',
        'babes',
        'sign up',
        'log in',
        'login',
        'join',
        'join now',
        'member',
        'members',
        'category',
        'categories',
        'tag',
        'tags',
        'search',
        'next',
        'previous',
        'prev',
        'more',
        'all',
        'new',
        'newest',
        'popular',
        'top rated',
        'most viewed',
        'related galleries',
        'free sites',
        'live cams',
        'webcams',
        'premium',
        'sites',
        'site',
        'porn',
        'sex',
        'nude',
        'naked',
        'picture',
        'pictures',
        'image',
        'images',
        'set',
        'sets',
        'album',
        'albums',
    )
)


def _clean_name(raw):
    """Normalise a candidate to a person-shaped name, or "" if it is not one."""
    name = ' '.join((raw or '').split())
    name = name.strip(' \t\r\n-–—|:•·,."\'“”‘’()[]')
    if not (3 <= len(name) <= 40) or any(ch.isdigit() for ch in name):
        return ''
    if name.lower() in _NOT_A_NAME:
        return ''
    if name.isupper() or name.islower():
        name = name.title()  # AGATHA VEGA / agatha vega -> Agatha Vega
    if not _NAME_SHAPE_RE.match(name):
        return ''
    if any(word.lower() in _NOT_A_NAME for word in name.split()):
        return ''
    return name


def _name_slug(name):
    return re.sub(r'[^a-z0-9]+', '-', (name or '').lower()).strip('-')


class _NameParser(HTMLParser):
    """Pulls the model link, the h1 and the title out of a gallery page."""

    _CAPTURE = ('a', 'h1', 'title')

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.model_links = []
        self.headings = []
        self.title = ''
        self.og_title = ''
        self._open = []  # [(tag, href, [text parts])]

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or '') for k, v in attrs}
        if tag == 'meta':
            prop = (a.get('property') or a.get('name') or '').lower()
            if prop in ('og:title', 'twitter:title') and not self.og_title:
                self.og_title = a.get('content', '')
            return
        if tag in self._CAPTURE:
            self._open.append([tag, a.get('href', ''), []])

    def handle_data(self, data):
        for frame in self._open:
            frame[2].append(data)

    def handle_endtag(self, tag):
        for index in range(len(self._open) - 1, -1, -1):
            if self._open[index][0] == tag:
                _, href, parts = self._open.pop(index)
                text = ' '.join(''.join(parts).split())
                if tag == 'a' and href and _MODEL_HREF_RE.search(href):
                    self.model_links.append((href, text))
                elif tag == 'h1':
                    self.headings.append(text)
                elif tag == 'title' and not self.title:
                    self.title = text
                del self._open[index:]
                return


def _model_key(href):
    """Canonical identity for a model: host + /model/<slug>, no trailing slash.

    THE anchor text is decoration; the href is the identity. Measured on four
    femjoyhunter galleries of one person: the link text read "Amina A",
    "Amina", "Amina" and "Amina V", but every one of them pointed at
    /model/amina-a/. Grouping on the text split her across three folders;
    grouping on the href does not.
    """
    parts = urllib.parse.urlsplit(href)
    path = parts.path.rstrip('/')
    if not path:
        return ''
    host = parts.netloc.lower()
    if host.startswith('www.'):
        host = host[4:]
    return host + path.lower()


def _extract_name(text, page_url=''):
    """Best guess at the character this page is about.

    Returns (name, how_it_was_found, identity_key). The key is the model page
    the gallery links to when there is one — that is what folders group on, so
    a site that spells the same person three ways still lands in one folder.
    ("", "", "") when nothing usable was found.
    """
    parser = _NameParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)

    url_slug = _name_slug(urllib.parse.urlsplit(page_url).path)
    scored = {}

    def offer(raw, base, why):
        name = _clean_name(raw)
        if not name:
            return
        score = base
        words = len(name.split())
        score += 15 if words == 2 else (8 if words == 3 else -12 if words == 1 else 0)
        slug = _name_slug(name)
        # The decisive signal: the page's own address names the same person.
        if slug and url_slug and slug in url_slug:
            score += 60
        if score > scored.get(name, (-1, ''))[0]:
            scored[name] = (score, why)

    # A model link is the site telling you who this is, so it SETTLES the
    # question — it is not scored against headings and titles. Scoring it let
    # the per-page URL bonus flip the answer: on /amina-in-delicate-dare/ the
    # anchor text "Amina" scored above the canonical slug "amina-a" purely
    # because that page's own address happened to say "amina", which is how one
    # model ended up as Amina-A, Amina and Amina-V.
    key = ''
    for href, label in parser.model_links:
        tail = [s for s in urllib.parse.urlsplit(href).path.split('/') if s]
        canonical = _clean_name(tail[-1].replace('-', ' ').replace('_', ' ').title() if tail else '')
        if canonical:
            return canonical, 'model link address', _model_key(href)
        # Slug unusable (a numeric id, say) — fall back to the anchor text but
        # still take the identity from the address.
        if _clean_name(label):
            offer(label, 100, 'model link')
            if not key:
                key = _model_key(href)
    for heading in parser.headings:
        lead = _NAME_LEAD_RE.match(heading)
        offer(lead.group(1) if lead else heading, 55, 'page heading')
    for source, why in ((parser.og_title, 'og:title'), (parser.title, 'page title')):
        if source:
            lead = _NAME_LEAD_RE.match(source)
            offer(lead.group(1) if lead else source, 45, why)

    if not scored:
        return '', '', ''
    best = max(scored.items(), key=lambda kv: kv[1][0])
    return best[0], best[1][1], key


def _name_from_page_file(path):
    """_extract_name for an uploaded .html / .mhtml."""
    try:
        if os.path.splitext(path)[1].lower() in ('.mhtml', '.mht'):
            _, docs, base = _parse_mhtml(path)
            for doc_text, loc in docs:
                name, why, key = _extract_name(doc_text, base or loc)
                if name:
                    return name, why, key
            return '', '', ''
        with open(path, 'rb') as handle:
            raw = handle.read(MAX_PAGE_BYTES).decode('utf-8', 'replace')
        found = _SAVED_FROM_RE.search(raw[:8192])
        return _extract_name(raw, found.group('url') if found else '')
    except Exception:
        return '', '', ''


def _parse_mhtml(path):
    """Split an MHTML archive into (embedded images, html docs, base url).

    Embedded parts are the whole point: Chrome's "Webpage, Single File" bakes
    every displayed picture into the archive, so those need no network at all.
    """
    with open(path, 'rb') as handle:
        message = email.parser.BytesParser().parse(handle)

    base = message.get('Snapshot-Content-Location') or message.get('Content-Location') or ''
    embedded, docs = [], []

    for part in message.walk():
        if part.is_multipart():
            continue
        ctype = (part.get_content_type() or '').lower()
        try:
            payload = part.get_payload(decode=True)
        except Exception:
            payload = None
        if not payload:
            continue
        location = part.get('Content-Location') or ''
        if ctype.startswith('image/'):
            embedded.append({'bytes': payload, 'ctype': ctype, 'loc': location})
        elif ctype in ('text/html', 'application/xhtml+xml'):
            charset = part.get_content_charset() or 'utf-8'
            docs.append((payload.decode(charset, 'replace'), location))

    return embedded, docs, base
