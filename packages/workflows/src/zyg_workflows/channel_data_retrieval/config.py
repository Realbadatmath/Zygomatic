# ruff: noqa: F401  (this module inherits the original top import block)
# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
channel_data_retrieval.py
=========================
Multi-source data retrieval for all Creator Nexus channels (sports excluded).

Each public fetch_* function returns a standard result dict:
    {
        'channel':    str   — channel key
        'label':      str   — human label
        'source':     str   — active sources used (comma-separated)
        'status':     'ok' | 'error'
        'error':      str | None
        'item_count': int
        'items':      list[dict]  — each item: title, link, summary, published, image
        'fetched_at': ISO-8601 UTC string
    }

REGISTRY maps every channel key to its fetcher:
    from zyg_workflows.channel_data_retrieval import REGISTRY
    result = REGISTRY['fin_crypto']()
"""

from __future__ import annotations

import json
import re
import ssl
import tempfile
import urllib.parse as _up
import urllib.request as _ur
from datetime import datetime, timezone

# The feeds are third-party XML, so the billion-laughs/external-entity hardening is not optional.
from defusedxml.ElementTree import fromstring as xml_fromstring

from zyg_workflows import paths
from zyg_workflows.contact import contact_email
import logging as _zyg_logging

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.channel_data_retrieval')


# ─── Shared config ─────────────────────────────────────────────────────────────

_UA = f'ZygomaticsNexusDataPipeline/1.0 (contact: {contact_email()})'
_TIMEOUT = 14
_MAX_ITEMS = 20
_SSL_CTX = ssl.create_default_context()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok(channel: str, label: str, source: str, items: list) -> dict:
    return {
        'channel': channel,
        'label': label,
        'source': source,
        'status': 'ok',
        'error': None,
        'item_count': len(items),
        'items': items,
        'fetched_at': _now(),
    }


def _err(channel: str, label: str, source: str, error: str) -> dict:
    return {
        'channel': channel,
        'label': label,
        'source': source,
        'status': 'error',
        'error': error,
        'item_count': 0,
        'items': [],
        'fetched_at': _now(),
    }


# ─── Image helpers ─────────────────────────────────────────────────────────────

_IMG_EXT_RE = re.compile(r'\.(jpe?g|png|webp|gif)(\?.*)?$', re.I)
_BAD_IMG_RE = re.compile(r'[/_-](ads?|banner|pixel|tracking|favicon|logo|avatar|placeholder|spacer|1x1)[/_.]', re.I)
_BAD_IMG_HOSTS = frozenset(
    [
        'doubleclick.net',
        'googlesyndication.com',
        'googletagmanager.com',
        'google-analytics.com',
        'adservice.google.com',
        'amazon-adsystem.com',
    ]
)


def _looks_like_image(url: str) -> bool:
    return bool(_IMG_EXT_RE.search(url.split('?')[0]))


def _validate_image_url(url: str) -> str:
    """Return url if it looks like a valid editorial image, else empty string."""
    if not url or not url.startswith('http'):
        return ''
    if _BAD_IMG_RE.search(url):
        return ''
    try:
        host = _up.urlparse(url).netloc.lower()
        if any(bad in host for bad in _BAD_IMG_HOSTS):
            return ''
    except Exception as _exc:
        _zyg_log.debug('image host check skipped, URL not parsable: %s', _exc)
    return url


def _extract_image(item_el, desc_raw: str) -> str:
    """
    Extract the best image URL from an RSS item/entry element.
    Four passes in priority order:
      1. <enclosure type="image/...">       — standard RSS image attachment
      2. <content> (from media:content)      — modern feeds (after namespace strip)
      3. <thumbnail> (from media:thumbnail)  — BBC and others
      4. <img src="..."> in description HTML — WordPress/Electrek style
    """
    # Pass 1: <enclosure>
    enc = item_el.find('enclosure')
    if enc is not None and enc.get('type', '').startswith('image/'):
        url = _validate_image_url(enc.get('url', ''))
        if url:
            return url

    # Pass 2: <content> (media:content after ns-strip)
    for el in item_el.findall('content'):
        mid = el.get('medium', '')
        typ = el.get('type', '')
        url = el.get('url', '')
        if url and (mid == 'image' or typ.startswith('image/') or _looks_like_image(url)):
            url = _validate_image_url(url)
            if url:
                return url

    # Pass 3: <thumbnail> (media:thumbnail after ns-strip)
    thumb = item_el.find('thumbnail')
    if thumb is not None:
        url = _validate_image_url(thumb.get('url', ''))
        if url:
            return url

    # Pass 4: first <img src> inside description HTML
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc_raw)
    if m:
        url = _validate_image_url(m.group(1))
        if url:
            return url

    return ''


# ─── RSS / HTTP helpers ────────────────────────────────────────────────────────


def _checked_url(url: str) -> str:
    """Return *url* unchanged once its scheme is http or https.

    Feed and API URLs come from the registry and from caller payloads, so they are untrusted:
    ``urlopen`` would follow a ``file://`` or custom scheme straight out of them. Both Requests
    below are built from a URL that has been through here, which is the audit S310 asks for.
    """
    if _up.urlsplit(url).scheme not in ('http', 'https'):
        raise ValueError(f'refusing non-http(s) feed URL: {url[:120]!r}')
    return url


def _get(url: str, timeout: int = _TIMEOUT) -> bytes:
    req = _ur.Request(  # noqa: S310  _checked_url rejects other schemes
        _checked_url(url),
        headers={
            'User-Agent': _UA,
            'Accept': 'application/json, application/xml, text/xml, */*',
            'Accept-Encoding': 'identity',
        },
    )
    return _ur.urlopen(req, timeout=timeout, context=_SSL_CTX).read()  # nosec B310  # noqa: S310  req holds the checked URL


def _strip_ns(raw: bytes) -> bytes:
    """Strip XML namespace declarations and prefixes so ElementTree parses any RSS/Atom feed."""
    raw = re.sub(rb'\s+xmlns(?::\w+)?=["\'][^"\']*["\']', b'', raw)
    raw = re.sub(rb'<(/?)\w+:([a-zA-Z])', rb'<\1\2', raw)
    raw = re.sub(rb'\b\w+:([a-zA-Z]\w*=)', rb'\1', raw)
    return raw


def _fetch_rss(url: str, max_items: int = _MAX_ITEMS) -> list[dict]:
    """Parse RSS 2.0 or Atom feed → list of {title, link, summary, published, image}."""
    req = _ur.Request(  # noqa: S310  _checked_url rejects other schemes
        _checked_url(url),
        headers={
            'User-Agent': _UA,
            'Accept': 'application/rss+xml, application/atom+xml, text/xml, */*',
            'Accept-Encoding': 'identity',
        },
    )
    raw = _ur.urlopen(req, timeout=_TIMEOUT, context=_SSL_CTX).read()  # nosec B310  # noqa: S310  req holds the checked URL
    raw = _strip_ns(raw)
    root = xml_fromstring(raw)
    items: list[dict] = []

    # RSS 2.0
    for item in root.findall('.//item')[:max_items]:
        desc_raw = item.findtext('description') or ''
        desc_text = re.sub(r'<[^>]+>', '', desc_raw).strip()[:300]
        items.append(
            {
                'title': (item.findtext('title') or '').strip(),
                'link': (item.findtext('link') or '').strip(),
                'summary': desc_text,
                'published': (item.findtext('pubDate') or '').strip(),
                'image': _extract_image(item, desc_raw),
            }
        )

    # Atom fallback
    if not items:
        for entry in root.findall('.//entry')[:max_items]:
            link_el = entry.find('link')
            desc_raw = entry.findtext('summary') or ''
            items.append(
                {
                    'title': (entry.findtext('title') or '').strip(),
                    'link': link_el.get('href', '') if link_el is not None else '',
                    'summary': re.sub(r'<[^>]+>', '', desc_raw).strip()[:300],
                    'published': (entry.findtext('updated') or entry.findtext('published') or '').strip(),
                    'image': _extract_image(entry, desc_raw),
                }
            )

    return items


def _wiki_search(query: str, n: int = 15) -> list[dict]:
    """Wikipedia fulltext search → list of {title, summary, link, published, image}."""
    url = (
        'https://en.wikipedia.org/w/api.php?action=query&list=search'
        f'&srsearch={_up.quote(query)}&srlimit={n}&format=json'
    )
    data = json.loads(_get(url))
    out = []
    for r in data.get('query', {}).get('search', []):
        out.append(
            {
                'title': r.get('title', ''),
                'summary': re.sub(r'<[^>]+>', '', r.get('snippet', '')).strip(),
                'link': f'https://en.wikipedia.org/wiki/{_up.quote(r["title"].replace(" ", "_"))}',
                'published': '',
                'image': '',
            }
        )
    return out


def _fetch_multi(
    sources: list[tuple],
    keywords: list[str] | None = None,
    max_items: int = _MAX_ITEMS,
) -> tuple[list[dict], list[str], list[str]]:
    """
    Fetch from multiple (name, url) sources, combining until max_items reached.
    Deduplicates by link URL. Optionally filters items to those matching any keyword.
    Returns (items, used_source_names, errors).
    """
    seen: set[str] = set()
    items: list[dict] = []
    errors: list[str] = []
    used: list[str] = []

    for src_name, url in sources:
        if len(items) >= max_items:
            break
        try:
            fetched = _fetch_rss(url, max_items=max_items)
            added = 0
            for item in fetched:
                if len(items) >= max_items:
                    break
                link = item.get('link', '') or item.get('title', '')
                if link in seen:
                    continue
                if keywords:
                    text = (item.get('title', '') + ' ' + item.get('summary', '')).lower()
                    if not any(k in text for k in keywords):
                        continue
                seen.add(link)
                items.append(item)
                added += 1
            if added > 0 and src_name not in used:
                used.append(src_name)
        except Exception as e:
            errors.append(f'{src_name}: {e}')

    return items, used, errors
