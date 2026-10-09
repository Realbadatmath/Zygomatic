# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""share_collab — the server half of the Share dock group (2026-09-07).

Three things the browser cannot do on its own:

  · `share`  writes a read-only COPY of the drawing under a random token into
    data/architecture/shares/<token>.json, so a link handed to someone on the
    LAN keeps working after the author has moved on with their own drawing.
  · `shared` hands that copy back to whoever opens the link, and refuses it
    once it has expired (404) — the expiry is a fact of the file, not of the
    client that asks.
  · `others` / `other` list and read the OTHER saved drawings (and their
    versions, if the file_manage_setup family ever writes any) so Compare can
    diff the drawing in the tab against one on disk.

Only the standard library is used. Tokens are `secrets.token_hex(6)` — 12 hex
characters, 48 bits: enough that a link cannot be guessed on a LAN, short
enough to read down a telephone.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time

from zyg_workflows import architecture_studio as AS
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


SHARE_DIR = os.path.join(AS.ARCH_DIR, 'shares')
VERSION_DIR = os.path.join(AS.ARCH_DIR, 'versions')
_TOKEN_RE = re.compile(r'^[0-9a-f]{12}$')
_STAMP_RE = re.compile(r'^[0-9A-Za-z_-]{1,40}$')
MAX_DAYS = 3650


def _now() -> float:
    return time.time()


def _share_path(token: str) -> str:
    """A token resolves to a path inside SHARE_DIR or not at all — it arrives
    from a URL, so it is validated as 12 hex characters rather than joined and
    hoped over."""
    token = str(token or '').strip().lower()
    if not _TOKEN_RE.match(token):
        raise ValueError('bad share token')
    return os.path.join(SHARE_DIR, token + '.json')


def share(payload, method):
    """Store a copy of `doc` and answer {ok, token, url, expires}."""
    doc = payload.get('doc')
    if not isinstance(doc, dict) or not isinstance(doc.get('objects'), list):
        return {'error': 'share needs a doc with an objects[] list', 'code': 400}
    try:
        days = float(payload.get('expires_days', 30) or 0)
    except (TypeError, ValueError):
        days = 30.0
    days = max(0.0, min(MAX_DAYS, days))
    name = str(payload.get('name') or doc.get('name') or 'Shared drawing')[:120]
    os.makedirs(SHARE_DIR, exist_ok=True)
    token = secrets.token_hex(6)
    while os.path.exists(os.path.join(SHARE_DIR, token + '.json')):
        token = secrets.token_hex(6)
    created = _now()
    rec = {
        'token': token,
        'name': name,
        'created': created,
        'expires': (created + days * 86400.0) if days else 0.0,
        'expires_days': days,
        'objects': len(doc['objects']),
        'doc': doc,
    }
    with open(os.path.join(SHARE_DIR, token + '.json'), 'w', encoding='utf-8') as fh:
        json.dump(rec, fh)
    path = '/inspection.html#architecture&share=' + token
    origin = str(payload.get('origin') or '').rstrip('/')
    return {
        'ok': True,
        'token': token,
        'url': (origin + path) if origin else path,
        'name': name,
        'objects': len(doc['objects']),
        'expires': rec['expires'],
        'expires_days': days,
    }


def shared(payload, method):
    """Hand back a shared copy: {ok, doc, name, created, expires}."""
    try:
        path = _share_path(payload.get('t') or payload.get('token'))
    except ValueError as e:
        return {'error': str(e), 'code': 404}
    if not os.path.exists(path):
        return {'error': 'no such share (it may have been deleted)', 'code': 404}
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            rec = json.load(fh)
    except (OSError, ValueError):
        return {'error': 'that share will not parse', 'code': 404}
    exp = float(rec.get('expires') or 0)
    if exp and _now() > exp:
        return {'error': 'that share link has expired', 'code': 404, 'expired': True}
    return {
        'ok': True,
        'token': rec.get('token'),
        'name': rec.get('name') or 'Shared drawing',
        'created': rec.get('created'),
        'expires': exp,
        'doc': rec.get('doc') or {'objects': []},
    }


def _versions(pid: str) -> list:
    """The saved versions of one drawing, newest first. The versions folder is
    another family's to write; when it is absent this is simply []."""
    d = os.path.join(VERSION_DIR, pid)
    if not os.path.isdir(d):
        return []
    out = []
    for fn in sorted(os.listdir(d)):
        if not fn.endswith('.json'):
            continue
        p = os.path.join(d, fn)
        try:
            out.append({'stamp': fn[:-5], 'm': os.path.getmtime(p), 'bytes': os.path.getsize(p)})
        except OSError as _exc:
            _zyg_log.debug('share snapshot skipped, stat failed: %s', _exc)
            continue
    out.sort(key=lambda r: -r['m'])
    return out


def others(payload, method):
    """Everything Compare can be pointed at: saved drawings + their versions."""
    drawings = []
    for p in AS.list_projects():
        drawings.append(
            {'pid': p['id'], 'n': p['n'], 'objects': p['objects'], 'm': p['m'], 'versions': _versions(p['id'])}
        )
    return {'ok': True, 'drawings': drawings, 'versions_dir': os.path.isdir(VERSION_DIR)}


def other(payload, method):
    """One drawing (or one of its versions) as {ok, doc, name}."""
    pid = str(payload.get('pid') or '').strip()
    stamp = str(payload.get('stamp') or '').strip()
    if not pid:
        return {'error': 'other needs a pid', 'code': 400}
    if stamp:
        if not _STAMP_RE.match(stamp) or pid != AS._slug(pid):
            return {'error': 'bad version stamp', 'code': 404}
        path = os.path.join(VERSION_DIR, pid, stamp + '.json')
        if not os.path.exists(path):
            return {'error': 'no such version', 'code': 404}
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            return {'error': 'that version will not parse', 'code': 404}
        # file_manage_setup wraps the drawing: {stamp, label, saved, doc}. A
        # bare doc is accepted too, so a version written any other way still
        # compares.
        doc = raw.get('doc') if isinstance(raw, dict) and isinstance(raw.get('doc'), dict) else raw
        if not isinstance(doc, dict):
            return {'error': 'that version holds no drawing', 'code': 404}
        return {'ok': True, 'doc': doc, 'name': f'{doc.get("name") or pid} @ {stamp}', 'pid': pid, 'stamp': stamp}
    try:
        r = AS.load_project(pid)
    except ValueError as e:
        return {'error': str(e), 'code': 404}
    if r.get('error'):
        r['code'] = 404
        return r
    doc = r['doc']
    return {'ok': True, 'doc': doc, 'name': doc.get('name') or pid, 'pid': pid, 'stamp': ''}


ROUTES = {'share': share, 'shared': shared, 'others': others, 'other': other}
