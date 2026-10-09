# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.asset_library_service.audio_meta — verbatim from asset_library_service.py lines 456-620.

the audio license-metadata sidecar: its lock, the strict/fail-safe
loaders and the atomic single/batch writers
"""

import json
import os
import threading
import logging as _zyg_logging
from zyg_workflows.asset_library_service import catalog as _zyg_catalog

# Bound by ASSIGNMENT, never by `from … import`: CPython 3.12 refuses the
# method-call optimisation for an import-bound global, so `NAME.attr(...)`
# inside the moved code would compile to different bytecode than it did in
# the single-file asset_library_service.py.
_CATEGORIES = _zyg_catalog._CATEGORIES
_HERE = _zyg_catalog._HERE
_audio_dir = _zyg_catalog._audio_dir

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.asset_library_service')


# ── audio license-metadata sidecar ────────────────────────────────────────────
# Known meta fields (others are merged too, but never allowed to clobber the
# structural record keys id/file/size):
#   source_url, license_id, commercial_ok (True/False/None=unknown),
#   attribution_required (bool), attribution (str), download_account,
#   added_date, banned (bool), notes


def _audio_meta_path(cat):
    return os.path.join(_HERE, 'data', 'runtime', f'asset_library_{cat}_meta.json')


# Serializes sidecar read-modify-write across threads; cross-PROCESS writers
# are serialized by fcntl.flock on <sidecar>.lock inside set_audio_meta.
_AUDIO_META_LOCK = threading.Lock()


def _load_audio_meta_strict(cat):
    """(files_dict, ok). ok=False ONLY when the sidecar EXISTS but cannot be
    read/parsed into the expected shape — writers must treat that as CORRUPT
    and never rewrite the license book from {} (that would silently destroy
    every other file's provenance). A missing sidecar is ({}, True)."""
    p = _audio_meta_path(cat)
    if not os.path.exists(p):
        return {}, True
    try:
        with open(p, 'r', encoding='utf-8') as f:
            doc = json.load(f)
        files = doc.get('files') if isinstance(doc, dict) else None
        if isinstance(files, dict):
            return files, True
    except (OSError, ValueError) as _exc:
        _zyg_log.warning('audio meta unreadable, reported as absent: %s', _exc)
    return {}, False


def _load_audio_meta(cat):
    """The whole sidecar as {filename: meta_dict}. Fail-safe empty dict —
    READ path only; set_audio_meta uses the strict loader above."""
    files, _ok = _load_audio_meta_strict(cat)
    return files


def get_audio_meta(cat, file_id):
    """License/provenance meta for one audio file. {} when none recorded."""
    m = _load_audio_meta(cat).get(str(file_id or ''))
    return dict(m) if isinstance(m, dict) else {}


def set_audio_meta(cat, file_id, meta):
    """MERGE meta into ONE file's dict and write the sidecar atomically.
    Thin wrapper over set_audio_meta_many — see it for the locking, corruption
    and pruning rules."""
    fid = str(file_id or '').strip()
    if not fid or os.path.basename(fid) != fid or not isinstance(meta, dict):
        return False
    return set_audio_meta_many(cat, {fid: meta})


def set_audio_meta_many(cat, items):
    """MERGE MANY {file_id: meta} into the per-file dicts and write the sidecar
    atomically (unique mkstemp tmp + os.replace — a crashed writer must never
    truncate the license book, and two concurrent writers must never share a
    tmp path). The whole load-modify-write is serialized by _AUDIO_META_LOCK
    (threads) plus fcntl.flock on <sidecar>.lock (processes). A sidecar that
    exists but cannot be parsed is quarantined to <sidecar>.corrupt-<ts> and the
    write is REFUSED (returns False) — merging into {} would rewrite the license
    book with only these entries, silently destroying every other file's
    provenance. Opportunistically prunes entries whose audio file no longer
    exists, EXCEPT tombstones carrying a 'deleted' stamp (license history must
    survive).

    2026-09-02: the BATCH form exists because the single-file form is O(n) per
    call — it re-reads, re-prunes and re-writes the entire book every time. At
    2,800 files that was invisible; ingesting the instruments library (66k)
    one-at-a-time meant rewriting a 90 MB json 66,000 times. One call per 500
    files turns that back into something linear.
    """
    info = _CATEGORIES.get(cat)
    if not info or info.get('kind') != 'audio' or not isinstance(items, dict):
        return False
    clean = {}
    for fid, meta in items.items():
        fid = str(fid or '').strip()
        if not fid or os.path.basename(fid) != fid or not isinstance(meta, dict):
            return False
        clean[fid] = meta
    if not clean:
        return True
    p = _audio_meta_path(cat)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
    except OSError:
        return False
    with _AUDIO_META_LOCK:
        lock_fd = None
        try:
            import fcntl

            lock_fd = os.open(p + '.lock', os.O_CREAT | os.O_RDWR, 0o644)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        except Exception:
            # flock infra unavailable — degrade to thread-lock-only rather
            # than refusing every write (fail-safe)
            if lock_fd is not None:
                try:
                    os.close(lock_fd)
                except OSError as _exc:
                    _zyg_log.debug('closing the stale lock fd skipped: %s', _exc)
                lock_fd = None
        try:
            files, ok = _load_audio_meta_strict(cat)
            if not ok:
                import time

                try:
                    os.replace(p, p + f'.corrupt-{int(time.time())}')
                except OSError as _exc:
                    _zyg_log.warning('quarantining the corrupt audio meta failed: %s', _exc)
                return False
            d = _audio_dir(cat)
            for fid, meta in clean.items():
                cur = files.get(fid)
                cur = dict(cur) if isinstance(cur, dict) else {}
                cur.update(meta)
                if 'deleted' in cur and 'deleted' not in meta and os.path.isfile(os.path.join(d, fid)):
                    # file re-ingested under a tombstoned name — clear the stamp
                    cur.pop('deleted', None)
                files[fid] = cur
            try:
                present = set(os.listdir(d))
                files = {
                    k: v
                    for k, v in files.items()
                    if k in clean or k in present or (isinstance(v, dict) and v.get('deleted'))
                }
            except OSError as _exc:
                _zyg_log.warning('audio directory listing failed, stale entries kept in the meta: %s', _exc)
            import tempfile

            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p), prefix=os.path.basename(p) + '.')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump({'version': 1, 'category': cat, 'files': files}, f, indent=2)
                os.replace(tmp, p)
                return True
            except OSError:
                try:
                    os.remove(tmp)
                except OSError as _exc:
                    _zyg_log.debug('temporary meta file removal skipped: %s', _exc)
                return False
        finally:
            if lock_fd is not None:
                try:
                    import fcntl

                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except Exception as _exc:
                    _zyg_log.debug('releasing the audio meta lock failed: %s', _exc)
                try:
                    os.close(lock_fd)
                except OSError as _exc:
                    _zyg_log.debug('closing the audio meta lock fd skipped: %s', _exc)
