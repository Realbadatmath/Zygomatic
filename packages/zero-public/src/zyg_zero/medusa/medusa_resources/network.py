# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Polite fetching, robots.txt and saving a decoded image.

Moved verbatim out of medusa_resources.py (original lines 1041-1248).
"""

import io
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

from .config import (
    IMAGE_EXTS,
    IMPORTABLE_EXTS,
    MAX_IMAGE_BYTES,
    MAX_PAGE_BYTES,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    USER_AGENT,
    _ROBOTS,
    _ROBOTS_LOCK,
)
from .urls import _safe_leaf

try:
    from PIL import Image
except Exception:  # pragma: no cover - PIL is present on this box (12.2.0)
    Image = None

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__package__ or 'medusa_resources')


# ── Network ─────────────────────────────────────────────────────────────────
def _urlopen_http(url, headers, timeout):
    """GET *url* with *headers*, refusing every scheme but http/https.

    The addresses handled here come from operator input and from scraped pages, so a bare
    ``urlopen`` would happily follow ``file://`` and read a local file. This is the audit
    :func:`zyg_workflows.net.safe_urlopen` performs; that function cannot be used directly
    because these call sites need a :class:`~urllib.request.Request` carrying headers, so
    this is the single reviewed URL open of the module.
    """
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in ('http', 'https'):
        raise ValueError(f'refusing to open {scheme or "scheme-less"} URL: {url}')
    req = urllib.request.Request(url, headers=headers)  # noqa: S310  scheme checked above
    return urllib.request.urlopen(req, timeout=timeout)  # nosec B310  # noqa: S310  scheme checked above


def _load_robots(scheme, netloc):
    """Fetch and parse robots.txt with our real UA.

    RobotFileParser.read() would treat a 403 on robots.txt as "disallow
    everything", which is the wrong call here — plenty of CDNs 403 unknown
    agents on that path. Unreachable/absent robots.txt means "no rules stated",
    so allow.
    """
    parser = urllib.robotparser.RobotFileParser()
    try:
        with _urlopen_http(f'{scheme}://{netloc}/robots.txt', {'User-Agent': USER_AGENT}, 15) as resp:
            body = resp.read(512 * 1024).decode('utf-8', 'replace')
        parser.parse(body.splitlines())
    except Exception:
        parser.allow_all = True
    return parser


def _robots_allows(url):
    parts = urllib.parse.urlsplit(url)
    key = (parts.scheme, parts.netloc)
    with _ROBOTS_LOCK:
        parser = _ROBOTS.get(key)
    if parser is None:
        parser = _load_robots(parts.scheme, parts.netloc)
        with _ROBOTS_LOCK:
            _ROBOTS[key] = parser
    try:
        return parser.can_fetch(USER_AGENT, url)
    except Exception:
        return True


def _fetch(url, referer):
    """One GET. Returns (bytes, content_type). Raises on failure."""
    headers = {
        'User-Agent': USER_AGENT,
        'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Sec-Fetch-Dest': 'image',
        'Sec-Fetch-Mode': 'no-cors',
        'Sec-Fetch-Site': 'cross-site',
    }
    if referer:
        headers['Referer'] = referer  # a lot of CDNs hotlink-block without it
    with _urlopen_http(url, headers, REQUEST_TIMEOUT) as resp:
        data = resp.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError(f'larger than {MAX_IMAGE_BYTES // (1024 * 1024)}MB')
        return data, (resp.headers.get('Content-Type') or '').split(';')[0].strip().lower()


def _fetch_page(url, referer):
    """GET a typed address without assuming it is an image.

    Returns (bytes, content_type, charset). Used only for addresses the
    operator typed, so it accepts HTML as well and lets the caller branch.
    """
    headers = {
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,image/*;q=0.8,*/*;q=0.5',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    if referer:
        headers['Referer'] = referer
    with _urlopen_http(url, headers, REQUEST_TIMEOUT) as resp:
        data = resp.read(MAX_PAGE_BYTES + 1)
        if len(data) > MAX_PAGE_BYTES:
            raise ValueError('response larger than the read cap')
        raw_ctype = resp.headers.get('Content-Type') or ''
        charset = 'utf-8'
        if 'charset=' in raw_ctype.lower():
            charset = raw_ctype.lower().split('charset=', 1)[1].split(';')[0].strip() or 'utf-8'
        return data, raw_ctype.split(';')[0].strip().lower(), charset


def _fetch_with_retry(url, referer, delay, cancelled):
    """_fetch plus backoff on 429/5xx. Returns (bytes, ctype) or raises."""
    attempt = 0
    while True:
        try:
            return _fetch(url, referer)
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if not retryable or attempt >= MAX_RETRIES:
                raise
            wait = delay * (2**attempt)
            after = exc.headers.get('Retry-After') if exc.headers else None
            if after:
                try:
                    wait = max(wait, min(float(after), 120.0))
                except ValueError as _exc:
                    _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt >= MAX_RETRIES:
                raise
            wait = delay * (2**attempt)
        attempt += 1
        waited = 0.0
        while waited < wait:
            if cancelled():
                raise RuntimeError('cancelled')
            time.sleep(0.25)
            waited += 0.25


# ── Saving ──────────────────────────────────────────────────────────────────
def _decode_image(data):
    """Validate bytes as a real image and fingerprint it.

    Returns (pillow_format, width, height, dhash) or (None, 0, 0, 0).

    Decoding down to a 9x8 grey thumbnail IS the validation — a truncated body
    or an HTML error page wearing a .jpg name raises here. That is stricter
    than Image.verify(), which only inspects the header, and it produces the
    perceptual hash in the same pass.

    The hash is a 64-bit dHash (each bit = "is this pixel brighter than the one
    to its right"). It survives rescaling and re-encoding, which is exactly
    what is needed to notice that /thumbs/07.jpg and /full/07.jpg are one
    photograph — sha256 cannot, because the bytes genuinely differ.
    """
    if Image is None:
        return None, 0, 0, 0
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = (probe.format or '').upper()
            width, height = probe.size
            probe.draft('L', (64, 64))  # JPEG fast path; no-op elsewhere
            small = probe.convert('L').resize((9, 8), Image.LANCZOS)
        pixels = list(small.getdata())
        bits = 0
        for row in range(8):
            base = row * 9
            for col in range(8):
                bits = (bits << 1) | (1 if pixels[base + col] > pixels[base + col + 1] else 0)
        return fmt, width, height, bits
    except Exception:
        return None, 0, 0, 0


def _hamming(a, b):
    return bin(a ^ b).count('1')


def _write_image(set_dir, data, fmt, name_hint, taken):
    """Write one image, transcoding anything Training cannot read into PNG.

    Returns (filename, bytes_written) or (None, 0).
    """
    stem = os.path.splitext(_safe_leaf(name_hint) or 'image')[0] or 'image'
    fmt_ext = {
        'JPEG': '.jpg',
        'PNG': '.png',
        'WEBP': '.webp',
        'GIF': '.gif',
        'AVIF': '.avif',
        'BMP': '.bmp',
        'TIFF': '.tif',
        'MPO': '.jpg',
    }.get(fmt or '', '')
    ext = fmt_ext or (os.path.splitext(_safe_leaf(name_hint))[1].lower())
    if ext not in IMAGE_EXTS:
        ext = '.jpg'

    payload = data
    if ext not in IMPORTABLE_EXTS:
        # Downloaded fine but Training's importer only reads png/jpg/jpeg/webp,
        # so convert rather than leave a picture that silently never imports.
        if Image is None:
            return None, 0
        try:
            with Image.open(io.BytesIO(data)) as src:
                frame = src.convert('RGBA' if src.mode in ('RGBA', 'LA', 'P') else 'RGB')
                buf = io.BytesIO()
                frame.save(buf, format='PNG', optimize=True)
                payload = buf.getvalue()
            ext = '.png'
        except Exception:
            return None, 0

    name = f'{stem}{ext}'
    n = 1
    while name.lower() in taken:
        n += 1
        name = f'{stem}-{n}{ext}'
    taken.add(name.lower())

    with open(os.path.join(set_dir, name), 'wb') as handle:
        handle.write(payload)
    return name, len(payload)
