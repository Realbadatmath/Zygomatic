# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The job runner and the set listing.

Moved verbatim out of medusa_resources.py (original lines 1251-1771, 1780-1822).
"""

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse

from .config import (
    DEFAULT_DELAY,
    DEFAULT_EXCLUDE_WORDS,
    DEFAULT_MIN_BYTES,
    DEFAULT_MIN_EDGE,
    DEFAULT_STOP_PHRASES,
    DEFAULT_WORKERS,
    IMAGE_EXTS,
    MAX_FILES_PER_SET,
    MAX_PAGE_BYTES,
    MAX_RECORDED_ERRORS,
    MAX_SEED_PAGES,
    MAX_WORKERS,
    META_DIR,
    PHASH_DISTANCE,
    RESOURCES_ROOT,
    _JOBS,
    _JOBS_LOCK,
    _JOB_SEQ,
)
from .urls import _collapse_variants, _excluded, _looks_like_image, _origin, _read_manifest
from .parsing import _parse_html, _parse_mhtml
from .network import _decode_image, _fetch_page, _fetch_with_retry, _hamming, _robots_allows, _write_image

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__package__ or 'medusa_resources')


# ── Job runner ──────────────────────────────────────────────────────────────
def _new_job(set_name, set_dir, source, opts):
    """Register a job. set_dir is None for a planner, which owns no folder."""
    with _JOBS_LOCK:
        _JOB_SEQ[0] += 1
        job_id = f'job{_JOB_SEQ[0]:04d}'
        _JOBS[job_id] = {
            'id': job_id,
            'set': set_name,
            'dir': set_dir,
            'source': source,
            'state': 'queued',
            'message': 'queued',
            'total': 0,
            'done': 0,
            'saved': 0,
            'embedded': 0,
            'skipped': 0,
            'failed': 0,
            'bytes': 0,
            'upgraded': 0,
            'variants': 0,
            'excluded': 0,
            'errors': [],
            'cancel': False,
            'character': '',
            'appended': False,
            'started': time.time(),
            'finished': None,
            'opts': opts,
        }
    return job_id


def _job_update(job_id, **fields):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job:
            job.update(fields)


def _job_error(job_id, url, reason, counts=True):
    """Record a reason against the job.

    counts=False for things already tallied as `skipped` (robots, wrong type,
    undecodable) — otherwise one declined URL shows up in BOTH the skipped and
    the failed column and the numbers stop adding up. `failed` means the
    request genuinely went wrong; `skipped` means we declined it on purpose.
    """
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        if counts:
            job['failed'] += 1
        if len(job['errors']) < MAX_RECORDED_ERRORS:
            job['errors'].append({'url': url[:300], 'reason': str(reason)[:200]})


def _cancelled(job_id):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return bool(job and job['cancel'])


def _write_manifest(job_id, records):
    with _JOBS_LOCK:
        job = dict(_JOBS.get(job_id) or {})
    set_dir = job.get('dir')
    if not set_dir:
        return
    meta = os.path.join(set_dir, META_DIR)
    os.makedirs(meta, exist_ok=True)
    payload = {
        'set': job.get('set'),
        'source': job.get('source'),
        'created': job.get('started'),
        'finished': job.get('finished'),
        'state': job.get('state'),
        'options': job.get('opts'),
        'counts': {
            k: job.get(k)
            for k in ('total', 'saved', 'embedded', 'skipped', 'failed', 'bytes', 'upgraded', 'variants', 'excluded')
        },
        'parsing': job.get('parse_stats', []),
        'errors': job.get('errors', []),
        'files': records,
    }
    tmp = os.path.join(meta, 'manifest.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2)
    os.replace(tmp, os.path.join(meta, 'manifest.json'))


def _consider(ctx, data, source, origin):
    """Validate → dedupe → write one picture. True if it was kept.

    The single funnel for all three ways bytes arrive (embedded in an MHTML,
    fetched from a URL a page named, fetched from a URL the operator typed), so
    the size filters and the dedup cannot drift apart between them.
    """
    job_id = ctx['job']
    if len(data) < ctx['min_bytes']:
        _bump(job_id, 'skipped')
        return False
    fmt, width, height, phash = _decode_image(data)
    if fmt is None:
        _bump(job_id, 'skipped')
        _job_error(job_id, source, 'not a decodable image', counts=False)
        return False
    if min(width, height) < ctx['min_edge']:
        _bump(job_id, 'skipped')
        return False
    digest = hashlib.sha256(data).hexdigest()
    hint = os.path.basename(urllib.parse.urlsplit(source).path) or 'image'
    pixels = width * height
    replaced = None

    # Everything past here mutates shared state, so it is serialised — the
    # download workers run concurrently but only one may claim a hash, a
    # fingerprint or a filename at a time.
    with ctx['lock']:
        if digest in ctx['hashes']:
            _bump(job_id, 'skipped')
            return False

        if ctx['dedup_similar']:
            for kept in ctx['records']:
                if _hamming(phash, kept['phash']) > PHASH_DISTANCE:
                    continue
                # Same photograph at a different size. Keep the bigger one.
                if pixels <= kept['w'] * kept['h']:
                    _bump(job_id, 'skipped')
                    return False
                replaced = kept
                break

        name, written = _write_image(ctx['dir'], data, fmt, hint, ctx['taken'])
        if not name:
            _bump(job_id, 'skipped')
            return False
        ctx['hashes'].add(digest)
        if replaced is not None:
            try:
                os.remove(os.path.join(ctx['dir'], replaced['file']))
            except OSError as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            ctx['records'].remove(replaced)
            _bump(job_id, 'bytes', -replaced['bytes'])
            _bump(job_id, 'saved', -1)
            _bump(job_id, 'upgraded')
        ctx['records'].append(
            {
                'file': name,
                'source': source,
                'origin': origin,
                'bytes': written,
                'w': width,
                'h': height,
                'phash': phash,
            }
        )
    _bump(job_id, 'saved')
    if origin == 'embedded':
        _bump(job_id, 'embedded')
    _bump(job_id, 'bytes', written)
    return True


def _seed_existing(ctx):
    """Fingerprint pictures already in the folder.

    Only matters when appending a second gallery to a character's existing
    folder: without this the dedup starts empty and re-adds what is already
    there under a -2 name.
    """
    for name in _set_images(ctx['dir']):
        try:
            with open(os.path.join(ctx['dir'], name), 'rb') as handle:
                data = handle.read()
        except OSError as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
        fmt, width, height, phash = _decode_image(data)
        if fmt is None:
            continue
        ctx['hashes'].add(hashlib.sha256(data).hexdigest())
        ctx['records'].append(
            {
                'file': name,
                'source': '(already in the folder)',
                'origin': 'existing',
                'bytes': len(data),
                'w': width,
                'h': height,
                'phash': phash,
            }
        )


def _sleep_politely(job_id, seconds):
    """Wait between requests, staying responsive to Cancel."""
    waited = 0.0
    while waited < seconds:
        if _cancelled(job_id):
            raise RuntimeError('cancelled')
        time.sleep(min(0.25, seconds - waited))
        waited += 0.25


def _run_job(job_id, page_paths, seed_urls=(), preparsed=None):
    """Turn one job's inputs into a folder of pictures.

    Inputs are only ever what the operator named: pages they saved and
    uploaded, and/or addresses they typed. A typed address that turns out to be
    a page is read ONCE for the pictures on it — links it holds to OTHER pages
    are never followed, and no path is ever guessed or enumerated. That one-hop
    rule is the whole difference between this and a crawler. Do not relax it.
    """
    with _JOBS_LOCK:
        job = dict(_JOBS[job_id])
    opts = job['opts']
    delay = max(0.0, float(opts.get('delay', DEFAULT_DELAY)))
    workers = max(1, min(MAX_WORKERS, int(opts.get('workers', DEFAULT_WORKERS))))
    respect_robots = bool(opts.get('respect_robots', True))
    deep_scan = bool(opts.get('deep_scan', False))
    drop_junk = bool(opts.get('drop_junk', True))
    collapse_variants = bool(opts.get('collapse_variants', True))
    stop_phrases = opts.get('stop_phrases')
    if stop_phrases is None:
        stop_phrases = DEFAULT_STOP_PHRASES
    exclude_words = opts.get('exclude_words')
    if exclude_words is None:
        exclude_words = DEFAULT_EXCLUDE_WORDS
    base_override = (opts.get('base_url') or '').strip()

    ctx = {
        'job': job_id,
        'dir': job['dir'],
        'taken': {n.lower() for n in os.listdir(job['dir'])},
        'hashes': set(),
        'records': [],
        'lock': threading.Lock(),
        'dedup_similar': bool(opts.get('dedup_similar', True)),
        'min_bytes': max(0, int(opts.get('min_bytes', DEFAULT_MIN_BYTES))),
        'min_edge': max(0, int(opts.get('min_edge', DEFAULT_MIN_EDGE))),
    }

    candidates = []  # (image url, referer, how)
    seen_urls = set()
    found_stats = []  # per-page parse stats, surfaced in the manifest

    excluded_hits = {}  # word -> how many addresses it kept out

    def enqueue(url, referer, how):
        if url in seen_urls:
            return
        seen_urls.add(url)
        # Checked here rather than at download time so an excluded address
        # costs nothing at all — no request is ever made for it.
        word = _excluded(url, exclude_words)
        if word:
            excluded_hits[word] = excluded_hits.get(word, 0) + 1
            _bump(job_id, 'excluded')
            return
        candidates.append((url, referer, how))

    def take(items, referer):
        for item in items:
            enqueue(item['url'], referer, item['how'])

    def note(stats, where):
        stats = dict(stats)
        stats['source'] = where
        found_stats.append(stats)
        if stats.get('cut'):
            _job_error(
                job_id,
                where,
                f'stopped at "{stats["cut"]["phrase"]}" (line '
                f'{stats["cut"]["line"]}) — {stats["dropped_after_cut"]} '
                f'pictures after it were left alone',
                counts=False,
            )
        if stats.get('junk_block_count'):
            _job_error(job_id, where, f'skipped {stats["junk_block_count"]} related/sponsored block(s)', counts=False)

    try:
        _job_update(job_id, state='parsing', message='reading input…')
        if job.get('appended'):
            _job_update(job_id, message='checking what is already in the folder…')
            _seed_existing(ctx)

        # Pages already read by the planner (typed addresses): push them through
        # enqueue() so the exclusion list and the dedup still apply.
        if preparsed:
            for url, referer, how in preparsed.get('items', []):
                enqueue(url, referer, how)
            found_stats.extend(preparsed.get('stats', []))

        # ── 1. pages the operator uploaded ──
        for page_path in page_paths:
            if os.path.splitext(page_path)[1].lower() in ('.mhtml', '.mht'):
                embedded, docs, base = _parse_mhtml(page_path)
                base = base_override or base
                for part in embedded:
                    if _cancelled(job_id):
                        raise RuntimeError('cancelled')
                    word = _excluded(part['loc'] or '', exclude_words)
                    if word:
                        excluded_hits[word] = excluded_hits.get(word, 0) + 1
                        _bump(job_id, 'excluded')
                        continue
                    _consider(ctx, part['bytes'], part['loc'] or 'mhtml-part', 'embedded')
                for text, loc in docs:
                    items, _, stats = _parse_html(text, base or loc, deep_scan, stop_phrases, drop_junk)
                    take(items, base or loc)
                    note(stats, os.path.basename(page_path))
            else:
                with open(page_path, 'rb') as handle:
                    text = handle.read(MAX_PAGE_BYTES).decode('utf-8', 'replace')
                items, base, stats = _parse_html(text, base_override, deep_scan, stop_phrases, drop_junk)
                take(items, base)
                note(stats, os.path.basename(page_path))

        # ── 2. addresses the operator typed (skipped when a planner already
        # read them, which is the normal path for the address box) ──
        # A direct picture link is queued as-is. Anything else is read once,
        # and only for the pictures it shows.
        pages_to_read = []
        for raw in seed_urls or ():
            if _looks_like_image(raw):
                enqueue(raw, base_override or _origin(raw), 'typed')
            else:
                pages_to_read.append(raw)

        if len(pages_to_read) > MAX_SEED_PAGES:
            _job_error(
                job_id, '', f'{len(pages_to_read)} addresses to read; only the first {MAX_SEED_PAGES} were opened'
            )
            pages_to_read = pages_to_read[:MAX_SEED_PAGES]

        for index, page_url in enumerate(pages_to_read):
            if _cancelled(job_id):
                raise RuntimeError('cancelled')
            _job_update(job_id, message=f'reading address {index + 1}/{len(pages_to_read)}')
            try:
                if respect_robots and not _robots_allows(page_url):
                    _bump(job_id, 'skipped')
                    _job_error(job_id, page_url, 'skipped by robots.txt', counts=False)
                    continue
                data, ctype, charset = _fetch_page(page_url, base_override or _origin(page_url))
                if ctype.startswith('image/'):
                    # A typed address with no extension that turned out to BE
                    # the picture — already in hand, don't fetch it twice.
                    _consider(ctx, data, page_url, 'fetched')
                elif ctype in ('text/html', 'application/xhtml+xml', 'text/plain', ''):
                    items, _, stats = _parse_html(
                        data.decode(charset, 'replace'), page_url, deep_scan, stop_phrases, drop_junk
                    )
                    take(items, page_url)
                    note(stats, page_url)
                else:
                    _job_error(job_id, page_url, f'not a picture or a page ({ctype})')
            except urllib.error.HTTPError as exc:
                _job_error(
                    job_id, page_url, f'HTTP {exc.code}' + (' (needs a session)' if exc.code in (401, 403) else '')
                )
            except Exception as exc:
                _job_error(job_id, page_url, f'{exc.__class__.__name__}: {exc}')
            if delay and index < len(pages_to_read) - 1:
                _sleep_politely(job_id, delay)

        # ── 3. collapse the size-variants, then fetch one per photograph ──
        for word, count in sorted(excluded_hits.items(), key=lambda kv: -kv[1]):
            _job_error(
                job_id, '', f'{count} address(es) skipped for containing "{word}" — never requested', counts=False
            )

        if collapse_variants:
            queued = _collapse_variants(candidates)
            saved_requests = len(candidates) - len(queued)
            if saved_requests:
                _bump(job_id, 'variants', saved_requests)
                _job_error(
                    job_id,
                    '',
                    f'{len(candidates)} addresses collapsed to {len(queued)} '
                    f'pictures — {saved_requests} were the same photograph at '
                    f'another size (thumbnail / srcset / full-size)',
                    counts=False,
                )
        else:
            queued = [[item] for item in candidates]

        if len(queued) > MAX_FILES_PER_SET:
            _job_error(job_id, '', f'input named {len(queued)} pictures; capped at {MAX_FILES_PER_SET}')
            queued = queued[:MAX_FILES_PER_SET]

        workers = min(workers, max(1, len(queued)))
        _job_update(
            job_id,
            total=len(queued),
            state='downloading',
            message=(
                f'{len(queued)} pictures to fetch{"" if workers == 1 else f", {workers} at a time"}'
                if queued
                else 'nothing left to fetch'
            ),
        )

        # Worker pool. Each worker spaces ITS OWN requests by `delay`, so the
        # aggregate rate is workers/delay — 2 workers at the 2s default is one
        # request a second, which is well inside what a browser opening a
        # gallery does. Raising workers is the knob that actually helps: image
        # transfers are transfer-bound, not delay-bound.
        next_index = [0]
        index_lock = threading.Lock()
        stop = threading.Event()

        def worker():
            while not stop.is_set():
                with index_lock:
                    index = next_index[0]
                    if index >= len(queued):
                        return
                    next_index[0] += 1
                if _cancelled(job_id):
                    stop.set()
                    return
                group = queued[index]
                _job_update(
                    job_id,
                    done=index,
                    message=f'{index + 1}/{len(queued)} · '
                    f'{os.path.basename(urllib.parse.urlsplit(group[0][0]).path)[:48]}',
                )

                # Try the best-ranked variant; fall through to the smaller ones
                # only if it actually fails, so the usual case is one request.
                for attempt, (url, referer, _how) in enumerate(group):
                    try:
                        if respect_robots and not _robots_allows(url):
                            _bump(job_id, 'skipped')
                            _job_error(job_id, url, 'skipped by robots.txt', counts=False)
                            break
                        data, ctype = _fetch_with_retry(
                            url, referer, delay or 1.0, lambda: _cancelled(job_id) or stop.is_set()
                        )
                        if ctype and not ctype.startswith('image/'):
                            _bump(job_id, 'skipped')
                            _job_error(job_id, url, f'not an image ({ctype})', counts=False)
                            break
                        _consider(ctx, data, url, 'fetched')
                        break
                    except RuntimeError:
                        stop.set()
                        return
                    except Exception as exc:
                        last = attempt == len(group) - 1
                        reason = (
                            f'HTTP {exc.code}' + (' (needs a session)' if exc.code in (401, 403) else '')
                            if isinstance(exc, urllib.error.HTTPError)
                            else f'{exc.__class__.__name__}: {exc}'
                        )
                        # Only the final failure of a group counts — falling back
                        # to a smaller variant is a recovery, not a failure.
                        _job_error(job_id, url, reason, counts=last)
                        if delay and not last:
                            try:
                                _sleep_politely(job_id, delay)
                            except RuntimeError:
                                stop.set()
                                return

                if delay:
                    try:
                        _sleep_politely(job_id, delay)
                    except RuntimeError:
                        stop.set()
                        return

        pool = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
        for thread in pool:
            thread.start()
        for thread in pool:
            thread.join()
        if _cancelled(job_id):
            raise RuntimeError('cancelled')

        with _JOBS_LOCK:
            snapshot = dict(_JOBS[job_id])
        _job_update(job_id, parse_stats=found_stats)
        _job_update(
            job_id,
            done=len(queued),
            state='done',
            finished=time.time(),
            message=f'{snapshot["saved"]} pictures in {snapshot["set"]}',
        )
    except RuntimeError:
        _job_update(job_id, state='cancelled', finished=time.time(), message='cancelled')
    except Exception as exc:
        _job_update(job_id, state='error', finished=time.time(), message=f'{exc.__class__.__name__}: {exc}')
    finally:
        try:
            _write_manifest(job_id, ctx['records'])
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)


def _bump(job_id, field, amount=1):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job:
            job[field] = job.get(field, 0) + amount
            return job[field]
    return 0


# ── Set listing ─────────────────────────────────────────────────────────────


def _set_images(set_dir):
    try:
        return sorted(
            entry.name
            for entry in os.scandir(set_dir)
            if entry.is_file() and os.path.splitext(entry.name)[1].lower() in IMAGE_EXTS
        )
    except OSError:
        return []


def _list_sets():
    """Only folders this module created — the import root holds other things."""
    out = []
    try:
        names = sorted(os.listdir(RESOURCES_ROOT))
    except OSError:
        return out
    for name in names:
        set_dir = os.path.join(RESOURCES_ROOT, name)
        if name.startswith('.') or not os.path.isdir(set_dir):
            continue  # .incoming staging and .meta/.thumbs are not sets
        manifest = _read_manifest(set_dir)
        if manifest is None:
            continue
        images = _set_images(set_dir)
        counts = manifest.get('counts') or {}
        out.append(
            {
                'set': name,
                'path': set_dir,
                'images': len(images),
                'bytes': counts.get('bytes', 0),
                'source': manifest.get('source'),
                'state': manifest.get('state'),
                'created': manifest.get('created'),
                'skipped': counts.get('skipped', 0),
                'failed': counts.get('failed', 0),
                'preview': images[:8],
            }
        )
    out.sort(key=lambda row: row.get('created') or 0, reverse=True)
    return out
