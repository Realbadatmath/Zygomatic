# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kanban/http_cache.py — gzip caches for JSON payloads and static files.

Split verbatim out of ``kanban_server.py`` (lines 3638-3686) on 2026-10-06; the handler
re-imports every name from here, so ``zyg_dashboard.kanban_server.<name>`` still resolves.
"""

import gzip
import threading

# ── response compression (2026-09-05) ──────────────────────────────────────
# Every tab polls its own payload on a 5 s clock (startAutoRefresh in
# inspection.html), so an UNCHANGED library was re-serialised and re-sent every
# 5 s per open tab. Measured on Music Studio, whose rail carries the 66k
# instruments library: 21,088,454 B a poll, 1.25 core-seconds per 20 s, and a
# 21 MB parse on the browser's main thread each time. Two changes fix it
# together: the body is hashed and served conditionally (an unchanged library
# costs a 304 with no body at all), and what does get sent is gzipped — that
# payload compresses to 4% of itself.
#
# gzip output is memoised on the etag rather than recomputed per client: the
# etag IS the content hash, so one compression serves every tab holding that
# version, and a payload that has not changed is never compressed twice.
_JSON_GZ = {}  # etag -> gzipped body
_JSON_GZ_MAX = 8  # payloads, not requests: a handful of live tabs
_JSON_GZ_MIN = 1400  # under a packet pair, compressing costs more
_JSON_GZ_LOCK = threading.Lock()
_JSON_MEMO = {}  # memo_key -> (payload object, body, etag)

# .html/.js/.css are served no-cache (see _Handler.end_headers) so the page can
# never go stale — which means inspection.html is re-fetched in full on every
# load. It is 1.9 MB of inline JS and CSS and compresses to 547 KB. Memoised on
# (mtime, size), so it is compressed once per edit rather than once per load.
_STATIC_GZ = {}  # abs path -> ((mtime, size), gzipped bytes)
_STATIC_GZ_LOCK = threading.Lock()
_STATIC_GZ_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.svg': 'image/svg+xml',
}


def _gz_cached(etag, body):
    """gzip(body), memoised on the caller's etag."""
    with _JSON_GZ_LOCK:
        hit = _JSON_GZ.get(etag)
    if hit is not None:
        return hit
    gz = gzip.compress(body, 6)
    with _JSON_GZ_LOCK:
        # A flat clear rather than an LRU: the dict holds at most a few live
        # payloads, and losing them costs one recompression each.
        if len(_JSON_GZ) >= _JSON_GZ_MAX:
            _JSON_GZ.clear()
        _JSON_GZ[etag] = gz
    return gz
