# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""Thumbnails, the JSON library index and the scan job."""

import hashlib
import json
import os
import threading
import time

from .constants import FFMPEG, FFPROBE, LIBRARY_PATH, MIN_VIDEO_BYTES, SKIP_DIRS, THUMB_DIR, VIDEO_EXTS, _ams_iso, _lock
from .naming import _AD_IMAGE_RE, _POSTER_NAME_RE, detect_episode, parse_release_name
from .probing import _playback_plan, _run, probe
from .prefs import (
    _embedded_subs,
    _external_subs,
    chapters_of,
    display_series,
    pick_default_audio,
    pick_default_sub,
    prefs_for,
    show_key,
)

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_zero.zpub_cinema')


# ── Thumbnails ────────────────────────────────────────────────────────────────
def _folder_artwork(video_path: str) -> str | None:
    """A real poster shipped in the folder, or None.

    Name-gated on purpose — see the module docstring: on this corpus the
    poster-SHAPED images are the tracker adverts.
    """
    vdir = os.path.dirname(video_path)
    try:
        names = sorted(os.listdir(vdir))
    except OSError:
        return None
    for name in names:
        if os.path.splitext(name)[1].lower() not in ('.jpg', '.jpeg', '.png', '.webp'):
            continue
        full = os.path.join(vdir, name)
        if not os.path.isfile(full):
            continue
        if _AD_IMAGE_RE.search(name):
            continue
        if _POSTER_NAME_RE.match(os.path.splitext(name)[0]):
            return full
    return None


def thumb_path(item_id: str) -> str:
    return os.path.join(THUMB_DIR, f'{item_id}.jpg')


def _frame_score(path: str) -> tuple[float, int]:
    """``(mean_luma, jpeg_bytes)`` for a candidate frame. ``(-1, 0)`` if unreadable."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return (-1.0, 0)
    rc, out, _e = _run(
        [
            FFPROBE,
            '-v',
            'error',
            '-f',
            'lavfi',
            '-i',
            f'movie={_lavfi_escape(path)},signalstats',
            '-show_entries',
            'frame_tags=lavfi.signalstats.YAVG',
            '-of',
            'csv=p=0',
        ],
        timeout=30,
    )
    if rc != 0:
        return (-1.0, size)
    try:
        return (float((out.strip().splitlines() or ['0'])[0]), size)
    except ValueError:
        return (-1.0, size)


def _lavfi_escape(path: str) -> str:
    """Escape a path for use inside a lavfi filtergraph argument."""
    return path.replace('\\', '\\\\').replace(':', '\\:').replace("'", "\\'")


# A frame darker than this is a fade/black gap, not a preview. Measured on this
# corpus: fixed-offset grabs returned YAVG 17 (Deadpool) and 16 (Thunderbolts) —
# solid black cards. ffmpeg's own `thumbnail` filter did NOT fix it: it picks the
# most REPRESENTATIVE frame of a ~4 s window, so inside a dark scene it faithfully
# returns a dark frame (measured 16.5 / 16.8 — no better than the fixed offset).
# Searching WIDELY across the running time is what actually finds a lit frame.
_THUMB_DARK_FLOOR = 24.0
_THUMB_BLOWN_CEIL = 235.0
_THUMB_GOOD_LUMA = 45.0
_THUMB_GOOD_BYTES = 9000
_THUMB_FRACTIONS = (0.48, 0.28, 0.62, 0.18, 0.38, 0.72, 0.08)


def build_thumb(item: dict, force: bool = False) -> str | None:
    """Produce the card thumbnail. Returns the cached jpg path, or None.

    Folder artwork wins when it passes the advert denylist; otherwise frames are
    sampled across the running time and scored on brightness + detail, because a
    single fixed offset lands on a black frame often enough to matter.
    """
    dest = thumb_path(item['id'])
    if not force and os.path.isfile(dest) and os.path.getsize(dest) > 512:
        return dest
    src = item.get('path')
    if not src or not os.path.isfile(src):
        return None

    art = _folder_artwork(src)
    if art:
        rc, _o, _e = _run(
            [FFMPEG, '-v', 'error', '-y', '-i', art, '-vf', 'scale=480:-2', '-q:v', '4', dest], timeout=60
        )
        if rc == 0 and os.path.isfile(dest) and os.path.getsize(dest) > 512:
            return dest

    duration = float(item.get('duration') or 0)
    if duration > 60:
        offsets = [duration * f for f in _THUMB_FRACTIONS]
    else:
        offsets = [max(1.0, duration * 0.5), 2.0]

    tmp = dest + '.cand.jpg'
    best_path, best_key = None, None
    try:
        for off in offsets:
            rc, _o, _e = _run(
                [
                    FFMPEG,
                    '-v',
                    'error',
                    '-y',
                    '-ss',
                    f'{max(0.0, off):.2f}',
                    '-i',
                    src,
                    '-frames:v',
                    '1',
                    '-vf',
                    'scale=480:-2',
                    '-q:v',
                    '4',
                    tmp,
                ],
                timeout=90,
            )
            if rc != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) < 512:
                continue
            luma, size = _frame_score(tmp)
            usable = _THUMB_DARK_FLOOR <= luma <= _THUMB_BLOWN_CEIL
            # Rank usable frames by detail (JPEG bytes at fixed quality); an
            # unusable frame only ever beats another unusable one, on brightness.
            key = (1 if usable else 0, size if usable else 0, luma)
            if best_key is None or key > best_key:
                best_key = key
                try:
                    os.replace(tmp, dest)
                except OSError:
                    break
                best_path = dest
            if usable and luma >= _THUMB_GOOD_LUMA and size >= _THUMB_GOOD_BYTES:
                break  # clearly good — stop searching
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return best_path


# ── Library index ─────────────────────────────────────────────────────────────
def _blank_library() -> dict:
    return {'version': 1, 'updated_at': None, 'roots': [], 'items': {}, 'series_names': {}}


def load_library() -> dict:
    with _lock:
        try:
            with open(LIBRARY_PATH, encoding='utf-8') as f:
                lib = json.load(f)
            if not isinstance(lib, dict) or 'items' not in lib:
                return _blank_library()
            lib.setdefault('roots', [])
            lib.setdefault('series_names', {})
            lib.setdefault('version', 1)
            return lib
        except (OSError, ValueError):
            return _blank_library()


def save_library(lib: dict) -> None:
    with _lock:
        lib['updated_at'] = _ams_iso()
        tmp = LIBRARY_PATH + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(lib, f, indent=1)
            os.replace(tmp, LIBRARY_PATH)
        except OSError as exc:
            _zyg_log.info(f'[Cinema] library save failed: {exc}')


def item_id_for(path: str) -> str:
    return hashlib.sha1(os.path.realpath(path).encode('utf-8', 'replace'), usedforsecurity=False).hexdigest()[:16]


def _walk_videos(root: str, max_files: int = 20000):
    """Yield candidate video paths under ``root``, skipping junk directories."""
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith('.')]
        for name in filenames:
            if os.path.splitext(name)[1].lower() not in VIDEO_EXTS:
                continue
            full = os.path.join(dirpath, name)
            try:
                size = os.path.getsize(full)
            except OSError as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
                continue
            if size < MIN_VIDEO_BYTES:
                continue
            if 'sample' in name.lower() and size < 400 * 1024 * 1024:
                continue
            yield full, size
            seen += 1
            if seen >= max_files:
                return


def build_item(path: str, size: int, existing: dict | None = None) -> dict | None:
    """Probe one video into a library entry. Reuses ``existing`` when unchanged."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    mtime = int(st.st_mtime)
    iid = item_id_for(path)

    if existing and existing.get('size') == size and existing.get('mtime') == mtime and existing.get('duration'):
        # File untouched — only re-read the sidecar subtitles, which are cheap
        # and are the thing most likely to have been added since the last scan.
        item = dict(existing)
        item['subs'] = _external_subs(path) + [s for s in existing.get('subs', []) if s.get('kind') == 'embedded']
        # Entries indexed before chapters were read at all carry no key; a
        # chapters-only ffprobe is cheap, so backfill instead of re-probing.
        if 'chapters' not in item:
            item['chapters'] = chapters_of(path)
        pref = prefs_for(item)
        item['default_sub'] = pick_default_sub(item['subs'], pref)
        item['default_audio'] = pick_default_audio(item.get('audio') or [], pref)
        return item

    info = probe(path)
    if not info or not info.get('video'):
        return None
    plan = _playback_plan(path, info)
    subs = _external_subs(path) + _embedded_subs(info)
    ep = detect_episode(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    title, year = parse_release_name(stem)
    if (not title or len(title) < 3) and os.path.dirname(path):
        title, year2 = parse_release_name(os.path.basename(os.path.dirname(path)))
        year = year or year2

    v = info.get('video') or {}
    item = {
        'id': iid,
        'kind': 'episode' if ep else 'movie',
        'path': path,
        'folder': os.path.dirname(path),
        'filename': os.path.basename(path),
        'title': title,
        'year': year,
        'size': size,
        'mtime': mtime,
        'duration': info.get('duration') or 0,
        'width': v.get('width') or 0,
        'height': v.get('height') or 0,
        'vcodec': v.get('codec') or '',
        'acodec': (info.get('audio') or [{}])[0].get('codec', '') if info.get('audio') else '',
        'audio': info.get('audio') or [],
        'subs': subs,
        'chapters': info.get('chapters') or [],
        'direct': plan['direct'],
        'video_copy': plan['video_copy'],
        'audio_copy': plan['audio_copy'],
        'transcode_reason': plan['reason'],
        'added_at': (existing or {}).get('added_at') or _ams_iso(),
    }
    if ep:
        item.update(ep)
        item['title'] = ep['series']
    # After the episode fields land: the show's own overrides are keyed on the
    # series name, so resolving prefs any earlier would read the movie defaults.
    pref = prefs_for(item)
    item['default_sub'] = pick_default_sub(subs, pref)
    item['default_audio'] = pick_default_audio(item.get('audio') or [], pref)
    return item


# ── Scan job ──────────────────────────────────────────────────────────────────
_scans: dict[str, dict] = {}
_scan_lock = threading.Lock()


def scan_status(scan_id: str) -> dict | None:
    with _scan_lock:
        s = _scans.get(scan_id)
        return dict(s) if s else None


def start_scan(root: str, replace: bool = False) -> dict:
    """Kick off a background scan of ``root``. Returns ``{scan_id}`` or an error."""
    root = os.path.abspath(os.path.expanduser(root))
    if not os.path.isdir(root):
        return {'error': f'Not a folder: {root}'}
    with _scan_lock:
        for sid, s in _scans.items():
            if s.get('state') == 'running':
                return {'error': 'A scan is already running', 'scan_id': sid}
        scan_id = hashlib.sha1(f'{root}{time.time()}'.encode(), usedforsecurity=False).hexdigest()[:12]
        _scans[scan_id] = {
            'scan_id': scan_id,
            'root': root,
            'state': 'running',
            'found': 0,
            'added': 0,
            'updated': 0,
            'skipped': 0,
            'total': 0,
            'current': '',
            'started_at': _ams_iso(),
            'finished_at': None,
            'error': None,
        }

    def _work():
        lib = load_library()
        items = lib.get('items') or {}
        added = updated = skipped = 0
        try:
            files = list(_walk_videos(root))
            with _scan_lock:
                _scans[scan_id]['total'] = len(files)
            # (basename, size) collisions are duplicate copies of one release —
            # the Documents corpus carries Amores Perros twice at 3 GB each.
            seen_sig: dict[tuple, str] = {}
            for iid, it in items.items():
                seen_sig.setdefault((it.get('filename', ''), it.get('size', 0)), iid)

            for i, (path, size) in enumerate(files, 1):
                with _scan_lock:
                    _scans[scan_id]['current'] = os.path.basename(path)
                    _scans[scan_id]['found'] = i
                iid = item_id_for(path)
                sig = (os.path.basename(path), size)
                if sig in seen_sig and seen_sig[sig] != iid:
                    skipped += 1
                    continue
                prev = items.get(iid)
                item = build_item(path, size, prev)
                if not item:
                    skipped += 1
                    continue
                items[iid] = item
                seen_sig[sig] = iid
                if prev:
                    updated += 1
                else:
                    added += 1
                with _scan_lock:
                    _scans[scan_id]['added'] = added
                    _scans[scan_id]['updated'] = updated
                    _scans[scan_id]['skipped'] = skipped
                if i % 5 == 0:
                    lib['items'] = items
                    save_library(lib)

            # Drop entries whose file disappeared.
            gone = [iid for iid, it in items.items() if not os.path.isfile(it.get('path', ''))]
            for iid in gone:
                items.pop(iid, None)

            roots = lib.get('roots') or []
            if root not in roots:
                roots.append(root)
            lib['roots'] = roots
            lib['items'] = items
            save_library(lib)

            with _scan_lock:
                _scans[scan_id].update(state='done', finished_at=_ams_iso(), removed=len(gone), current='')
        except Exception as exc:  # noqa: BLE001 - report, never crash
            with _scan_lock:
                _scans[scan_id].update(state='failed', error=str(exc), finished_at=_ams_iso())

        # Thumbnails last: the board is usable before they exist.
        # One try PER ITEM. Wrapping the whole loop meant the first failing
        # title silently skipped every remaining one (measured: 7 of 12 built).
        for it in list(items.values()):
            try:
                build_thumb(it)
            except Exception as exc:  # noqa: BLE001
                _zyg_log.info(f'[Cinema] thumb failed for {it.get("title")}: {exc}')
            with _scan_lock:
                if scan_id in _scans:
                    _scans[scan_id]['current'] = f'thumbnail: {it.get("title", "")}'
        with _scan_lock:
            if scan_id in _scans:
                _scans[scan_id]['current'] = ''
                _scans[scan_id]['thumbs_done'] = True

    threading.Thread(target=_work, daemon=True, name=f'cinema-scan-{scan_id}').start()
    return {'scan_id': scan_id}


def set_series_name(current: str, name: str) -> dict:
    """Name (or un-name) the series currently shown as ``current``.

    Applies to the folder of every item in that group, so one rename covers a
    show split over several folders and any episode added to them afterwards.
    """
    name = ' '.join(str(name or '').split())[:120]
    with _lock:
        lib = load_library()
        items = list((lib.get('items') or {}).values())
        names = lib.setdefault('series_names', {})
        key = show_key(current)
        folders = {
            it.get('folder')
            for it in items
            if it.get('kind') == 'episode' and show_key(display_series(it, names)) == key
        }
        folders.discard(None)
        folders.discard('')
        if not folders:
            return {'error': f'No series matching {current!r}'}
        for folder in folders:
            if name:
                names[folder] = name
            else:
                names.pop(folder, None)
        save_library(lib)
        return {'name': name, 'folders': sorted(folders)}
