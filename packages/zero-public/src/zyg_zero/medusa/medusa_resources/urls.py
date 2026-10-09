# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Small path/slug helpers and the one-photograph-many-URLs variant collapse.

Moved verbatim out of medusa_resources.py (original lines 203-516, 1772-1777).
"""

import json
import os
import re
import urllib.parse

from .config import IMAGE_EXTS, META_DIR, RESOURCES_ROOT


# ── Small helpers ───────────────────────────────────────────────────────────
def _slugify(name, fallback='set', strip_ext=True):
    """Filesystem-safe, lowercase folder name.

    strip_ext is for UPLOADED FILENAMES only (page.mhtml -> page). Leave it off
    for anything else: splitext on a host or a typed name eats everything after
    the last dot, so "127.0.0.1-gallery" would become "127.0.0".
    """
    stem = os.path.basename(name or '')
    if strip_ext:
        stem = os.path.splitext(stem)[0]
    stem = urllib.parse.unquote(stem)
    slug = re.sub(r'[^a-zA-Z0-9._-]+', '-', stem).strip('-._').lower()
    slug = re.sub(r'-{2,}', '-', slug)[:60].strip('-._')
    return slug or fallback


def _safe_leaf(name):
    """One path component, no traversal, no dotfile, no separators."""
    leaf = os.path.basename((name or '').replace('\\', '/'))
    leaf = re.sub(r'[^a-zA-Z0-9._-]+', '-', leaf).strip('-.')
    return leaf[:120]


def _set_dir(set_name):
    """Resolve a set folder, confined to RESOURCES_ROOT. None if it escapes."""
    leaf = _safe_leaf(set_name)
    if not leaf:
        return None
    path = os.path.realpath(os.path.join(RESOURCES_ROOT, leaf))
    if path != RESOURCES_ROOT and not path.startswith(RESOURCES_ROOT + os.sep):
        return None
    return path


def _folder_for_name(name):
    """ "Agatha Vega" -> "Agatha-Vega".

    Case is kept because this folder name IS the character name the Training
    tab shows. Spaces are not: every path in this module round-trips through
    _safe_leaf, which would rewrite a space to "-" on the way back in and then
    fail to find the folder again.
    """
    return _safe_leaf(re.sub(r'\s+', '-', (name or '').strip())) or ''


def _claim_set_dir(folder, merge):
    """Claim the folder for a character. Returns (path, appended_to_existing).

    With merge on, a second gallery of the same character lands in the folder
    that character already has, instead of spawning Agatha-Vega-2 — which is
    the point of naming folders after people rather than after page titles.
    """
    if merge and folder:
        existing = _set_dir(folder)
        if existing and existing != RESOURCES_ROOT and os.path.isdir(existing) and _read_manifest(existing) is not None:
            return existing, True
    return _unique_set_dir(folder or 'set'), False


def _unique_set_dir(slug):
    """Claim <root>/<slug>, or <slug>-2, -3 … if taken. Returns the path."""
    os.makedirs(RESOURCES_ROOT, exist_ok=True)
    candidate = slug
    n = 1
    while True:
        path = os.path.join(RESOURCES_ROOT, candidate)
        try:
            os.makedirs(path)
            return path
        except FileExistsError:
            n += 1
            candidate = f'{slug}-{n}'[:70]
            if n > 999:
                raise


def _ext_of(url):
    path = urllib.parse.urlsplit(url).path
    return os.path.splitext(path)[1].lower()


def _looks_like_image(url):
    return _ext_of(url) in IMAGE_EXTS


# ── One photograph, many URLs ───────────────────────────────────────────────
# A gallery shows each picture three to five times: a thumbnail in <img src>,
# the full-size behind the <a href> wrapping it, and one or more srcset widths.
# Those are DIFFERENT BYTES, so the sha256 dedup cannot see they are one photo.
# _variant_key strips the size markers so they collapse to a single key, and
# only the best-ranked member of each group is fetched — the rest are kept as
# fallbacks in case it 404s. This is both the duplicate fix and the single
# biggest speed-up: it removes most of the downloads.
_SIZE_DIR_RE = re.compile(
    r'^(?:thumbs?|tn|small|sm|med|medium|large|lg|xl|big|full|orig(?:inal)?|'
    r'preview|previews|sizes?|resized?|scaled|cache|w\d{2,4}|h\d{2,4}|'
    r's\d{2,4}|\d{2,4}(?:x\d{2,4})?)$',
    re.I,
)
_SIZE_IN_NAME_RE = re.compile(
    r'(?:[-_](?:\d{2,4}x\d{2,4}|thumbs?|tn|small|sm|med|medium|large|lg|xl|'
    r'big|full|orig(?:inal)?|preview|scaled|\d{2,4}w|w\d{2,4})|@[\d.]+x)+$',
    re.I,
)
_SIZE_HINT_RE = re.compile(r'(\d{2,4})\s*[xX]\s*(\d{2,4})|[-_/](?:w|width|s)(\d{2,4})|[-_]w?(\d{3,4})(?=\.|$)', re.I)
# Trailing width markers: 0019-01_1200.jpg, 0019-01_w800.jpg, shot-1800.jpg.
# A bare number is only treated as a width if it IS a plausible width — a frame
# number must never be stripped, or every frame in a set collapses into one
# group and the set comes back as a single picture.
_TRAILING_NUM_RE = re.compile(r'[-_](w)?(\d{2,4})$', re.I)
_COMMON_WIDTHS = frozenset(
    (
        100,
        120,
        150,
        160,
        180,
        200,
        220,
        240,
        250,
        260,
        280,
        300,
        320,
        340,
        360,
        375,
        400,
        420,
        450,
        480,
        500,
        540,
        560,
        600,
        640,
        680,
        720,
        750,
        768,
        800,
        850,
        900,
        960,
        1000,
        1024,
        1080,
        1100,
        1120,
        1140,
        1200,
        1280,
        1366,
        1400,
        1440,
        1500,
        1536,
        1600,
        1680,
        1700,
        1800,
        1920,
        2000,
        2048,
        2400,
        2560,
        3000,
        3200,
        3840,
    )
)


def _strip_size_suffix(stem):
    """Drop trailing _1200 / -w800 / _1800 style width markers from a stem."""
    while True:
        match = _TRAILING_NUM_RE.search(stem)
        if not match:
            return stem
        if not match.group(1) and int(match.group(2)) not in _COMMON_WIDTHS:
            return stem  # a frame number, not a width
        stem = stem[: match.start()]


_BIG_WORDS_RE = re.compile(r'full|orig|large|big|hi-?res|xl|source|master', re.I)
_SMALL_WORDS_RE = re.compile(r'thumb|tn\b|small|tiny|mini|icon|preview|low', re.I)

# How much weight each collector gets when picking a group's best member. The
# <a href> around a thumbnail is the full-size file — prefer it over the <img>.
_HOW_RANK = {'link': 4, 'script': 3, 'srcset': 2, 'head': 2, 'img': 1, 'css': 0, 'typed': 5}


def _variant_key(url):
    """Collapse the size-variants of one photograph onto a single key."""
    parts = urllib.parse.urlsplit(url)
    segments = [s for s in parts.path.split('/') if s]
    filename = segments.pop() if segments else ''
    segments = [s for s in segments if not _SIZE_DIR_RE.match(s)]
    stem, ext = os.path.splitext(filename)
    stem = _strip_size_suffix(_SIZE_IN_NAME_RE.sub('', stem))
    # Query strings on image URLs are nearly always ?w=/?h=/?resize= — dropping
    # them is what makes ?w=300 and ?w=1200 land on the same key.
    return parts.netloc.lower() + '/' + '/'.join(segments) + '/' + stem.lower() + ext.lower()


def _variant_rank(url, how):
    """Bigger is better. Guesses which member of a group is the full-size one."""
    largest = 0
    for match in _SIZE_HINT_RE.finditer(url):
        for group in match.groups():
            if group:
                largest = max(largest, int(group))
    score = largest
    if _BIG_WORDS_RE.search(url):
        score += 4000
    if _SMALL_WORDS_RE.search(url):
        score -= 4000
    return (score, _HOW_RANK.get(how, 1), len(url))


def _collapse_variants(candidates):
    """candidates: [(url, referer, how)] -> [[preferred, …fallbacks]].

    Order of first appearance is preserved so the folder still reads in page
    order.
    """
    groups, order = {}, []
    for url, referer, how in candidates:
        key = _variant_key(url)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((url, referer, how))
    out = []
    for key in order:
        members = sorted(groups[key], key=lambda m: _variant_rank(m[0], m[2]), reverse=True)
        out.append(members)
    return out


def _excluded(url, words):
    """The first excluded word this URL contains, or "" if it is fine."""
    if not words:
        return ''
    low = url.lower()
    for word in words:
        if word and word in low:
            return word
    return ''


def _origin(url):
    """scheme://host/ — the default Referer for a typed address."""
    parts = urllib.parse.urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return ''
    return f'{parts.scheme}://{parts.netloc}/'


def _split_urls(raw):
    """Pull http(s) addresses out of a pasted blob.

    One per line is the documented shape, but whitespace splits too so a copied
    column of links works. Blank lines and #-comments are ignored. Commas are
    NOT separators — they are legal inside a URL.
    """
    out, seen = [], set()
    for token in (raw or '').split():
        token = token.strip().strip('<>"\'')
        if token.startswith('#'):
            continue
        if token.lower().startswith(('http://', 'https://')) and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _slug_from_url(url):
    """Auto-name a typed-address set after its host and last useful segment."""
    parts = urllib.parse.urlsplit(url)
    host = (parts.netloc or '').split(':')[0]
    if host.startswith('www.'):
        host = host[4:]
    tail = [seg for seg in parts.path.split('/') if seg]
    # For a direct picture link the filename says nothing about the set, so
    # step up to the folder it sits in.
    if tail and _looks_like_image(url):
        tail = tail[:-1]
    stem = os.path.splitext(tail[-1])[0] if tail else ''
    return _slugify(f'{host}-{stem}' if stem else host, 'urls', strip_ext=False)


def _best_from_srcset(value):
    """Pick the highest-resolution candidate out of a srcset attribute."""
    best, best_w = None, -1.0
    for part in value.split(','):
        bits = part.strip().split()
        if not bits:
            continue
        width = 1.0
        if len(bits) > 1:
            desc = bits[-1].lower()
            try:
                if desc.endswith('w'):
                    width = float(desc[:-1])
                elif desc.endswith('x'):
                    width = float(desc[:-1]) * 1000.0
            except ValueError:
                width = 1.0
        if width > best_w:
            best, best_w = bits[0], width
    return best


def _read_manifest(set_dir):
    try:
        with open(os.path.join(set_dir, META_DIR, 'manifest.json'), encoding='utf-8') as handle:
            return json.load(handle)
    except Exception:
        return None
