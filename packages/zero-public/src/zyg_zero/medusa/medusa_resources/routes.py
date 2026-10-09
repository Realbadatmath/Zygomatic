# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Flask routes of the Resources tab and install().

Moved verbatim out of medusa_resources.py (original lines 1825-2341).
"""

import os
import shutil
import threading
import time
import urllib.error
import urllib.parse

from flask import jsonify, request, send_file

from . import bp
from .config import (
    DEFAULT_DELAY,
    DEFAULT_EXCLUDE_WORDS,
    DEFAULT_MIN_BYTES,
    DEFAULT_MIN_EDGE,
    DEFAULT_STOP_PHRASES,
    DEFAULT_WORKERS,
    MAX_FILES_PER_SET,
    MAX_SEED_PAGES,
    MAX_WORKERS,
    META_DIR,
    PAGE_EXTS,
    PHASH_DISTANCE,
    RESOURCES_ROOT,
    THUMB_DIR,
    THUMB_PX,
    _JOBS,
    _JOBS_LOCK,
)
from .urls import (
    _claim_set_dir,
    _excluded,
    _folder_for_name,
    _looks_like_image,
    _origin,
    _read_manifest,
    _safe_leaf,
    _set_dir,
    _slug_from_url,
    _slugify,
    _split_urls,
)
from .parsing import _extract_name, _name_from_page_file, _parse_html
from .network import _fetch_page, _robots_allows
from .jobs import _cancelled, _job_error, _job_update, _list_sets, _new_job, _run_job, _set_images, _sleep_politely

try:
    from PIL import Image
except Exception:  # pragma: no cover - PIL is present on this box (12.2.0)
    Image = None


# ── Routes ──────────────────────────────────────────────────────────────────
@bp.route('/api/resources/config', methods=['GET'])
def api_resources_config():
    return jsonify(
        {
            'ok': True,
            'root': RESOURCES_ROOT,
            'defaults': {
                'delay': DEFAULT_DELAY,
                'workers': DEFAULT_WORKERS,
                'min_bytes': DEFAULT_MIN_BYTES,
                'min_edge': DEFAULT_MIN_EDGE,
                'respect_robots': True,
                'deep_scan': False,
                'drop_junk': True,
                'collapse_variants': True,
                'dedup_similar': True,
                'phash_distance': PHASH_DISTANCE,
                'merge_by_name': True,
                'stop_phrases': list(DEFAULT_STOP_PHRASES),
                'exclude_words': list(DEFAULT_EXCLUDE_WORDS),
            },
            'max_workers': MAX_WORKERS,
            'accepts': sorted(PAGE_EXTS),
            'max_files_per_set': MAX_FILES_PER_SET,
        }
    )


@bp.route('/api/resources/upload', methods=['POST'])
def api_resources_upload():
    """Accept saved pages and start one extraction job per set.

    One uploaded page == one folder, unless `merge_as` is given, in which case
    every page in this batch lands in that single folder (the paginated-gallery
    case: five saved pages, one character).
    """
    files = [f for f in request.files.getlist('pages') if f and f.filename]
    if not files:
        return jsonify({'ok': False, 'error': 'no pages in request (field "pages")'}), 400

    form = request.form
    opts = _opts_from(form.get)
    merge_as = _folder_for_name(form.get('merge_as') or '')

    rejected = []
    accepted = []
    for storage in files:
        if os.path.splitext(storage.filename)[1].lower() not in PAGE_EXTS:
            rejected.append(storage.filename)
            continue
        accepted.append(storage)
    if not accepted:
        return jsonify({'ok': False, 'error': 'no .html/.mhtml files in the upload', 'rejected': rejected}), 400

    merge_by_name = opts.get('merge_by_name', True)
    started = []
    # Uploads are staged here first: the folder is named after the character on
    # the page, which cannot be known until the page has been read.
    staging = os.path.join(RESOURCES_ROOT, '.incoming')
    os.makedirs(staging, exist_ok=True)

    def claim(folder, entries, name):
        """entries: [(staged path, original filename)] — the staging name has a
        pid/timestamp prefix to keep concurrent uploads apart; only the
        operator's own filename should survive into .meta."""
        set_dir, appended = _claim_set_dir(folder, merge_by_name)
        meta = os.path.join(set_dir, META_DIR)
        os.makedirs(meta, exist_ok=True)
        landed = []
        for temp, original in entries:
            leaf = _safe_leaf(original) or 'page.html'
            dest = os.path.join(meta, leaf)
            n = 1
            while os.path.exists(dest):
                n += 1
                stem, ext = os.path.splitext(leaf)
                dest = os.path.join(meta, f'{stem}-{n}{ext}')
            shutil.move(temp, dest)
            landed.append(dest)
        job_id = _new_job(os.path.basename(set_dir), set_dir, ', '.join(os.path.basename(p) for p in landed), opts)
        _job_update(job_id, character=name, appended=appended)
        threading.Thread(target=_run_job, args=(job_id, landed), daemon=True).start()
        started.append({'job': job_id, 'set': os.path.basename(set_dir), 'character': name, 'appended': appended})

    try:
        staged = []
        for index, storage in enumerate(accepted):
            temp = os.path.join(
                staging, f'{os.getpid()}-{time.time_ns()}-{index}-' + (_safe_leaf(storage.filename) or 'page.html')
            )
            storage.save(temp)
            name, _why, key = _name_from_page_file(temp)
            staged.append((temp, name, storage.filename, key))

        if merge_as:
            # An explicit folder name wins over anything read off the pages.
            claim(merge_as, [(t, f) for t, _n, f, _k in staged], staged[0][1] if staged else '')
        else:
            # One folder per character; pages naming the same person share it.
            order, buckets, names, folders = [], {}, {}, {}
            for temp, name, original, key in staged:
                folder = _folder_for_name(name) or _slugify(original, strip_ext=True)
                group = key or folder  # identity first, folder second
                if group not in buckets:
                    buckets[group] = []
                    names[group] = name
                    folders[group] = folder
                    order.append(group)
                buckets[group].append((temp, original))
            for group in order:
                claim(folders[group], buckets[group], names[group])
    except Exception as exc:
        return jsonify({'ok': False, 'error': f'{exc.__class__.__name__}: {exc}', 'started': started}), 500

    return jsonify({'ok': True, 'started': started, 'rejected': rejected, 'root': RESOURCES_ROOT})


def _as_float(raw, fallback, low, high):
    try:
        return min(high, max(low, float(raw)))
    except (TypeError, ValueError):
        return fallback


def _parse_phrases(raw):
    """Operator-supplied stop phrases. None (absent) keeps the defaults; an
    empty string means "don't cut anywhere", which is a real choice."""
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        items = [str(p) for p in raw]
    else:
        items = str(raw).replace(',', '\n').split('\n')
    return tuple(p.strip().lower() for p in items if p.strip())


def _opts_from(getter):
    """Build the job options dict from a form's or a JSON body's .get."""

    def flag(key, default=True):
        value = getter(key)
        if value is None:
            return default
        return value not in (0, False, '0', 'false', 'off', 'no', '')

    return {
        'delay': _as_float(getter('delay'), DEFAULT_DELAY, 0.0, 60.0),
        'workers': int(_as_float(getter('workers'), DEFAULT_WORKERS, 1, MAX_WORKERS)),
        'min_bytes': int(_as_float(getter('min_bytes'), DEFAULT_MIN_BYTES, 0, 5e7)),
        'min_edge': int(_as_float(getter('min_edge'), DEFAULT_MIN_EDGE, 0, 10000)),
        'respect_robots': flag('respect_robots'),
        'collapse_variants': flag('collapse_variants'),
        'merge_by_name': flag('merge_by_name'),
        'dedup_similar': flag('dedup_similar'),
        # Off by default: the script blob is the single biggest source of
        # pictures that are not actually on the page.
        'deep_scan': flag('deep_scan', False),
        'drop_junk': flag('drop_junk'),
        'stop_phrases': _parse_phrases(getter('stop_phrases')),
        'exclude_words': _parse_phrases(getter('exclude_words')),
        'base_url': str(getter('base_url') or '').strip(),
    }


@bp.route('/api/resources/fetch-urls', methods=['POST'])
def api_resources_fetch_urls():
    """Fetch a list of addresses the operator typed into the Resources tab.

    Explicit and finite by construction: exactly the addresses in the box, plus
    the pictures shown on any of them that is a page. Nothing is enumerated,
    no path is guessed, and no link to another page is followed — see
    _run_job's one-hop rule.
    """
    body = request.get_json(silent=True) or {}
    raw = body.get('urls')
    if isinstance(raw, list):
        raw = '\n'.join(str(item) for item in raw)
    urls = _split_urls(raw)

    if not urls:
        return jsonify({'ok': False, 'error': 'no http:// or https:// addresses in the box'}), 400
    if len(urls) > MAX_FILES_PER_SET:
        return jsonify({'ok': False, 'error': f'{len(urls)} addresses pasted; the cap is {MAX_FILES_PER_SET}'}), 400

    opts = _opts_from(body.get)
    opts['set_name'] = str(body.get('set_name') or '').strip()

    # The folder is named after the character on the page, so it cannot be
    # decided until the page has been read. A planner job does that first and
    # then starts one extraction per character it finds.
    planner_id = _new_job('', None, f'{len(urls)} typed address' + ('' if len(urls) == 1 else 'es'), opts)
    _job_update(planner_id, state='planning', message='reading the addresses…')
    threading.Thread(target=_plan_typed_urls, args=(planner_id, urls, opts), daemon=True).start()
    return jsonify(
        {
            'ok': True,
            'urls': len(urls),
            'root': RESOURCES_ROOT,
            'started': [{'job': planner_id, 'set': '(naming from the pages…)'}],
        }
    )


def _plan_typed_urls(planner_id, urls, opts):
    """Read each typed page once, name it after the character on it, then start
    one extraction per character.

    Splitting here rather than inside _run_job is what lets a batch of four
    gallery addresses covering two people land in two correctly-named folders,
    while three galleries of the same person land in one.
    """
    delay = max(0.0, float(opts.get('delay', DEFAULT_DELAY)))
    respect_robots = bool(opts.get('respect_robots', True))
    deep_scan = bool(opts.get('deep_scan', False))
    drop_junk = bool(opts.get('drop_junk', True))
    merge = bool(opts.get('merge_by_name', True))
    stop_phrases = opts.get('stop_phrases')
    if stop_phrases is None:
        stop_phrases = DEFAULT_STOP_PHRASES
    override = _folder_for_name(opts.get('set_name') or '')
    fallback = override or (_slug_from_url(urls[0]) if urls else 'set')

    direct = [u for u in urls if _looks_like_image(u)]
    pages = [u for u in urls if not _looks_like_image(u)]
    if len(pages) > MAX_SEED_PAGES:
        _job_error(planner_id, '', f'{len(pages)} addresses to read; only the first {MAX_SEED_PAGES} were opened')
        pages = pages[:MAX_SEED_PAGES]

    # Keyed by the character's IDENTITY (their model page when the site has
    # one), NOT by the folder name — a site that spells one person three ways
    # must still produce one folder.
    groups = {}

    def group_for(key, folder, name):
        if key not in groups:
            groups[key] = {'folder': folder, 'name': name, 'items': [], 'stats': [], 'pages': []}
        return groups[key]

    try:
        _job_update(planner_id, state='parsing', total=len(pages), message=f'reading {len(pages)} address(es)…')
        for index, page_url in enumerate(pages):
            if _cancelled(planner_id):
                raise RuntimeError('cancelled')
            _job_update(planner_id, done=index, message=f'reading {index + 1}/{len(pages)} · {page_url[:60]}')
            try:
                if respect_robots and not _robots_allows(page_url):
                    _job_error(planner_id, page_url, 'skipped by robots.txt', counts=False)
                    continue
                data, ctype, charset = _fetch_page(page_url, _origin(page_url))
                if ctype.startswith('image/'):
                    direct.append(page_url)
                    continue
                if ctype and ctype not in ('text/html', 'application/xhtml+xml', 'text/plain'):
                    _job_error(planner_id, page_url, f'not a picture or a page ({ctype})')
                    continue
                text = data.decode(charset, 'replace')
                items, base, stats = _parse_html(text, page_url, deep_scan, stop_phrases, drop_junk)
                name, why, key = _extract_name(text, page_url)
                folder = override or _folder_for_name(name) or fallback
                stats = dict(stats, source=page_url, character=name, named_by=why)
                bucket = group_for(override or key or folder, folder, name)
                bucket['pages'].append(page_url)
                bucket['stats'].append(stats)
                bucket['items'].extend((item['url'], page_url, item['how']) for item in items)
                if name:
                    _job_error(
                        planner_id, page_url, f'“{name}” (from the {why}) → folder {bucket["folder"]}', counts=False
                    )
                else:
                    _job_error(
                        planner_id,
                        page_url,
                        f'no character name found on the page — falling back to {folder}',
                        counts=False,
                    )
            except urllib.error.HTTPError as exc:
                _job_error(
                    planner_id, page_url, f'HTTP {exc.code}' + (' (needs a session)' if exc.code in (401, 403) else '')
                )
            except Exception as exc:
                _job_error(planner_id, page_url, f'{exc.__class__.__name__}: {exc}')
            if delay and index < len(pages) - 1:
                _sleep_politely(planner_id, delay)

        if direct:
            bucket = group_for(fallback, fallback, '')
            bucket['items'].extend((u, _origin(u), 'typed') for u in direct)

        started, children = [], []
        for bucket in groups.values():
            set_dir, appended = _claim_set_dir(bucket['folder'], merge)
            meta = os.path.join(set_dir, META_DIR)
            os.makedirs(meta, exist_ok=True)
            with open(os.path.join(meta, 'urls.txt'), 'a', encoding='utf-8') as handle:
                handle.write('\n'.join(bucket['pages'] or [u for u, _r, _h in bucket['items']]) + '\n')
            source = f'{len(bucket["pages"]) or len(bucket["items"])} typed address' + (
                '' if (len(bucket['pages']) or len(bucket['items'])) == 1 else 'es'
            )
            job_id = _new_job(os.path.basename(set_dir), set_dir, source, opts)
            _job_update(job_id, character=bucket['name'], appended=appended)
            threading.Thread(
                target=_run_job,
                args=(job_id, [], (), {'items': bucket['items'], 'stats': bucket['stats']}),
                daemon=True,
            ).start()
            started.append(os.path.basename(set_dir) + (' (added to)' if appended else ''))
            children.append({'job': job_id, 'set': os.path.basename(set_dir)})

        _job_update(planner_id, children=children)
        _job_update(
            planner_id,
            state='done',
            done=len(pages),
            finished=time.time(),
            message=('→ ' + ', '.join(started)) if started else 'nothing to extract',
        )
    except RuntimeError:
        _job_update(planner_id, state='cancelled', finished=time.time(), message='cancelled')
    except Exception as exc:
        _job_update(planner_id, state='error', finished=time.time(), message=f'{exc.__class__.__name__}: {exc}')


@bp.route('/api/resources/preview', methods=['POST'])
def api_resources_preview():
    """Dry run: what WOULD be fetched from one page, and where each came from.

    Downloads nothing but the page itself. This is the tool for "it found more
    pictures than are on the page" — the breakdown by `how` and by folder shows
    which collector is responsible, and the cut/junk counts show what the
    section filter already removed.
    """
    body = request.get_json(silent=True) or {}
    opts = _opts_from(body.get)
    stop_phrases = opts['stop_phrases']
    if stop_phrases is None:
        stop_phrases = DEFAULT_STOP_PHRASES

    urls = _split_urls(
        body.get('urls') if isinstance(body.get('urls'), str) else '\n'.join(str(u) for u in (body.get('urls') or []))
    )
    if not urls:
        return jsonify({'ok': False, 'error': 'no address to preview'}), 400
    page_url = urls[0]

    try:
        if _looks_like_image(page_url):
            return jsonify(
                {
                    'ok': True,
                    'page': page_url,
                    'direct': True,
                    'items': [{'url': page_url, 'how': 'typed'}],
                    'by_how': {'typed': 1},
                    'by_folder': {},
                    'stats': {},
                }
            )
        data, ctype, charset = _fetch_page(page_url, _origin(page_url))
    except urllib.error.HTTPError as exc:
        return jsonify(
            {'ok': False, 'error': f'HTTP {exc.code}' + (' (needs a session)' if exc.code in (401, 403) else '')}
        ), 502
    except Exception as exc:
        return jsonify({'ok': False, 'error': f'{exc.__class__.__name__}: {exc}'}), 502

    if not ctype.startswith(('text/html', 'application/xhtml', 'text/plain')) and ctype:
        return jsonify({'ok': False, 'error': f'not a page ({ctype})'}), 400

    text = data.decode(charset, 'replace')
    kept, base, stats = _parse_html(text, page_url, opts['deep_scan'], stop_phrases, opts['drop_junk'])
    # The same page with every filter off — the difference between the two is
    # the answer to "why did it find so many?".
    unfiltered, _, _ = _parse_html(text, page_url, True, (), False)

    exclude_words = opts['exclude_words']
    if exclude_words is None:
        exclude_words = DEFAULT_EXCLUDE_WORDS
    excluded = {}
    survivors = []
    for item in kept:
        word = _excluded(item['url'], exclude_words)
        if word:
            excluded[word] = excluded.get(word, 0) + 1
        else:
            survivors.append(item)
    kept = survivors
    stats = dict(stats, excluded=excluded)

    by_how, by_folder = {}, {}
    for item in kept:
        by_how[item['how']] = by_how.get(item['how'], 0) + 1
        folder = urllib.parse.urlsplit(item['url']).path.rsplit('/', 1)[0] or '/'
        by_folder[folder] = by_folder.get(folder, 0) + 1

    character, named_by, model_key = _extract_name(text, page_url)
    return jsonify(
        {
            'ok': True,
            'page': page_url,
            'base': base,
            'character': character,
            'named_by': named_by,
            'model_key': model_key,
            'folder': _folder_for_name(character) or _slug_from_url(page_url),
            'kept': len(kept),
            'unfiltered': len(unfiltered),
            'by_how': by_how,
            'by_folder': dict(sorted(by_folder.items(), key=lambda kv: -kv[1])[:12]),
            'stats': stats,
            'items': kept[:400],
        }
    )


@bp.route('/api/resources/jobs', methods=['GET'])
def api_resources_jobs():
    with _JOBS_LOCK:
        jobs = [{k: v for k, v in job.items() if k not in ('cancel', 'dir')} for job in _JOBS.values()]
    jobs.sort(key=lambda j: j.get('started') or 0, reverse=True)
    return jsonify({'ok': True, 'jobs': jobs[:40], 'sets': _list_sets(), 'root': RESOURCES_ROOT})


@bp.route('/api/resources/jobs/<job_id>/cancel', methods=['POST'])
def api_resources_cancel(job_id):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return jsonify({'ok': False, 'error': 'no such job'}), 404
        job['cancel'] = True
    return jsonify({'ok': True})


@bp.route('/api/resources/sets', methods=['GET'])
def api_resources_sets():
    return jsonify({'ok': True, 'sets': _list_sets(), 'root': RESOURCES_ROOT})


@bp.route('/api/resources/sets/<set_name>', methods=['GET'])
def api_resources_set(set_name):
    set_dir = _set_dir(set_name)
    if not set_dir or not os.path.isdir(set_dir):
        return jsonify({'ok': False, 'error': 'no such set'}), 404
    manifest = _read_manifest(set_dir) or {}
    return jsonify(
        {
            'ok': True,
            'set': os.path.basename(set_dir),
            'path': set_dir,
            'images': _set_images(set_dir),
            'errors': manifest.get('errors', []),
            'counts': manifest.get('counts', {}),
        }
    )


@bp.route('/api/resources/sets/<set_name>', methods=['DELETE'])
def api_resources_delete_set(set_name):
    set_dir = _set_dir(set_name)
    if not set_dir or set_dir == RESOURCES_ROOT or not os.path.isdir(set_dir):
        return jsonify({'ok': False, 'error': 'no such set'}), 404
    if _read_manifest(set_dir) is None:
        # Refuse to delete a folder Resources did not create — the import root
        # is shared with hand-placed character folders.
        return jsonify({'ok': False, 'error': 'not a Resources set (no .meta/manifest.json)'}), 400
    try:
        shutil.rmtree(set_dir)
    except OSError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500
    return jsonify({'ok': True})


@bp.route('/api/resources/sets/<set_name>/image/<image_name>', methods=['GET'])
def api_resources_image(set_name, image_name):
    set_dir = _set_dir(set_name)
    leaf = _safe_leaf(image_name)
    if not set_dir or not leaf:
        return jsonify({'ok': False, 'error': 'bad path'}), 400
    path = os.path.join(set_dir, leaf)
    if not os.path.isfile(path):
        return jsonify({'ok': False, 'error': 'no such image'}), 404
    return send_file(path)


@bp.route('/api/resources/sets/<set_name>/thumb/<image_name>', methods=['GET'])
def api_resources_thumb(set_name, image_name):
    """256px preview, generated once and cached in the set's .thumbs folder."""
    set_dir = _set_dir(set_name)
    leaf = _safe_leaf(image_name)
    if not set_dir or not leaf:
        return jsonify({'ok': False, 'error': 'bad path'}), 400
    source = os.path.join(set_dir, leaf)
    if not os.path.isfile(source):
        return jsonify({'ok': False, 'error': 'no such image'}), 404
    if Image is None:
        return send_file(source)

    thumb_dir = os.path.join(set_dir, THUMB_DIR)
    thumb = os.path.join(thumb_dir, os.path.splitext(leaf)[0] + '.jpg')
    try:
        if not os.path.isfile(thumb) or os.path.getmtime(thumb) < os.path.getmtime(source):
            os.makedirs(thumb_dir, exist_ok=True)
            with Image.open(source) as src:
                src.draft('RGB', (THUMB_PX * 2, THUMB_PX * 2))
                frame = src.convert('RGB')
                frame.thumbnail((THUMB_PX, THUMB_PX), Image.LANCZOS)
                frame.save(thumb, format='JPEG', quality=82)
    except Exception:
        return send_file(source)
    return send_file(thumb, mimetype='image/jpeg')


def install(app):
    """Register the Resources blueprint on a Flask app."""
    os.makedirs(RESOURCES_ROOT, exist_ok=True)
    app.register_blueprint(bp)
    return bp
