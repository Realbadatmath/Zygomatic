# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""file_3d — the server half of the File ▸ 3D interchange family (2026-09-07).

The tab can build a .glb or a .stl in memory and hand it to the user as a
download, but a download lands in ~/Downloads where nothing else in this system
can see it — and a test cannot look at it at all. So every export ALSO gets a
copy on the server, under data/architecture/exports/, and every import is
uploaded to data/architecture/imports/ and then fetched back by URL. That one
decision is what makes the whole family provable: `blender -b` can open the glb
the browser just made, and a point cloud too big for a JSON payload is a file
with a stable id rather than a base64 string living in the drawing.

ROUTES
  save   POST {name, data_b64, ext}     -> {ok, path, bytes, name}
         Store an export. `ext` is fenced to glb/stl/obj/ply; the name is
         slugged and stamped, so a save never overwrites a previous one.
  upload POST {name, data_b64}          -> {ok, id, path, bytes, ext}
         Store an import under a content-addressed id. Re-uploading identical
         bytes returns the SAME id, so twenty placements of one chair are one
         file and one parse.
  file   GET  ?id=<id>                  -> (bytes, mime, filename)
         Serve an imported file back to the tab. The id is the only thing the
         drawing stores; where the bytes live is this machine's business.
  list   GET                            -> {ok, imports: [...], exports: [...]}

Standard library only (base64, hashlib, os, re, time). No new packages.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCH_DIR = os.path.join(HERE, 'data', 'architecture')
EXPORT_DIR = os.path.join(ARCH_DIR, 'exports')
IMPORT_DIR = os.path.join(ARCH_DIR, 'imports')

# A mesh interchange file is big; a runaway POST is bigger. 200 MB is past any
# drawing this studio can make and small enough that one call cannot fill the
# disk. (The HTTP layer caps the read at ~24 MB before we ever see it — this is
# the second fence, not the first.)
MAX_BYTES = 200 * 1024 * 1024

# Fenced on the way in, not on the way out: an extension decides which parser
# the tab reaches for and which importer Blender calls, so an unknown one is a
# refusal rather than a guess.
EXPORT_EXT = ('glb', 'stl', 'obj', 'ply')
IMPORT_EXT = ('glb', 'gltf', 'obj', 'stl', 'ply', 'xyz', 'pts')
MIME = {
    'glb': 'model/gltf-binary',
    'gltf': 'model/gltf+json',
    'obj': 'text/plain; charset=utf-8',
    'stl': 'model/stl',
    'ply': 'application/octet-stream',
    'xyz': 'text/plain; charset=utf-8',
    'pts': 'text/plain; charset=utf-8',
}

_ID_RE = re.compile(r'^[a-z0-9_-]{1,64}$')


def _slug(s: str, default: str = 'drawing') -> str:
    s = re.sub(r'[^a-z0-9]+', '-', str(s or '').strip().lower()).strip('-')
    return (s or default)[:48]


def _ensure() -> None:
    os.makedirs(EXPORT_DIR, exist_ok=True)
    os.makedirs(IMPORT_DIR, exist_ok=True)


def _decode(payload: dict):
    """base64 -> bytes, or ({'error'}, None). Accepts a data: URL as well, because
    that is what a FileReader hands the tab without a second conversion."""
    raw = payload.get('data_b64') or payload.get('data') or ''
    if not isinstance(raw, str) or not raw:
        return None, {'error': 'no data_b64 in the payload', 'code': 400}
    if raw.startswith('data:'):
        raw = raw.split(',', 1)[-1]
    try:
        data = base64.b64decode(raw, validate=False)
    except Exception as e:  # noqa: BLE001
        return None, {'error': 'data_b64 will not decode: %s' % (str(e)[:120],), 'code': 400}
    if not data:
        return None, {'error': 'the file is empty', 'code': 400}
    if len(data) > MAX_BYTES:
        return None, {'error': 'over the %d MB limit' % (MAX_BYTES // (1024 * 1024),), 'code': 400}
    return data, None


def _ext_of(payload: dict, name: str, allowed: tuple, default: str) -> str:
    ext = str(payload.get('ext') or '').strip().lower().lstrip('.')
    if not ext:
        ext = os.path.splitext(name)[1].lower().lstrip('.')
    return ext if ext in allowed else default


def save(payload, method):
    """Keep a copy of an export the browser just built."""
    _ensure()
    data, err = _decode(payload)
    if err:
        return err
    name = str(payload.get('name') or '')
    ext = _ext_of(payload, name, EXPORT_EXT, '')
    if not ext:
        return {'error': 'ext must be one of %s' % (', '.join(EXPORT_EXT),), 'code': 400}
    stamp = time.strftime('%Y%m%d-%H%M%S')
    path = os.path.join(EXPORT_DIR, '%s-%s.%s' % (_slug(name), stamp, ext))
    n = 2
    while os.path.exists(path):  # two exports in one second
        path = os.path.join(EXPORT_DIR, '%s-%s-%d.%s' % (_slug(name), stamp, n, ext))
        n += 1
    tmp = path + '.tmp'
    with open(tmp, 'wb') as fh:
        fh.write(data)
    os.replace(tmp, path)
    return {
        'ok': True,
        'path': path,
        'rel': os.path.relpath(path, HERE).replace(os.sep, '/'),
        'bytes': len(data),
        'ext': ext,
        'name': os.path.basename(path),
    }


def upload(payload, method):
    """Store a mesh or a point cloud to import. The id is the first 16 hex of the
    content hash, so the same bytes are the same id however often they arrive."""
    _ensure()
    data, err = _decode(payload)
    if err:
        return err
    name = str(payload.get('name') or '')
    ext = _ext_of(payload, name, IMPORT_EXT, '')
    if not ext:
        return {'error': 'the file must be one of %s' % (', '.join(IMPORT_EXT),), 'code': 400}
    fid = str(payload.get('id') or '').strip().lower()
    if fid and not _ID_RE.match(fid):
        fid = ''
    if not fid:
        fid = hashlib.sha256(data).hexdigest()[:16]
    path = os.path.join(IMPORT_DIR, '%s.%s' % (fid, ext))
    if not os.path.exists(path):
        tmp = path + '.tmp'
        with open(tmp, 'wb') as fh:
            fh.write(data)
        os.replace(tmp, path)
    return {
        'ok': True,
        'id': fid,
        'ext': ext,
        'path': path,
        'bytes': len(data),
        'rel': os.path.relpath(path, HERE).replace(os.sep, '/'),
    }


def _find(fid: str):
    if not _ID_RE.match(fid or ''):
        return None
    for ext in IMPORT_EXT:
        p = os.path.join(IMPORT_DIR, '%s.%s' % (fid, ext))
        if os.path.isfile(p):
            return p
    return None


def file(payload, method):
    """The bytes of one imported file, by id. A download tuple, so the tab can
    fetch it as an ArrayBuffer and parse it with the loader for its extension."""
    fid = str(payload.get('id') or '').strip().lower()
    path = _find(fid)
    if path is None:
        return {'error': 'no imported file with id %r' % (fid[:64],), 'code': 404}
    ext = os.path.splitext(path)[1].lstrip('.').lower()
    with open(path, 'rb') as fh:
        data = fh.read()
    return (data, MIME.get(ext, 'application/octet-stream'), os.path.basename(path))


def info(payload, method):
    """Where an imported file lives on disk — what Blender's twin needs, and what
    a test needs to point `bpy.ops.import_scene.gltf` at."""
    fid = str(payload.get('id') or '').strip().lower()
    path = _find(fid)
    if path is None:
        return {'error': 'no imported file with id %r' % (fid[:64],), 'code': 404}
    return {
        'ok': True,
        'id': fid,
        'path': path,
        'bytes': os.path.getsize(path),
        'ext': os.path.splitext(path)[1].lstrip('.').lower(),
    }


def _listing(d: str, cap: int = 200):
    if not os.path.isdir(d):
        return []
    out = []
    for fn in os.listdir(d):
        if fn.endswith('.tmp'):
            continue
        p = os.path.join(d, fn)
        if os.path.isfile(p):
            out.append(
                {
                    'name': fn,
                    'id': os.path.splitext(fn)[0],
                    'bytes': os.path.getsize(p),
                    'm': os.path.getmtime(p),
                    'path': p,
                }
            )
    out.sort(key=lambda r: -r['m'])
    return out[:cap]


def list_(payload, method):
    _ensure()
    return {
        'ok': True,
        'imports': _listing(IMPORT_DIR),
        'exports': _listing(EXPORT_DIR),
        'import_dir': IMPORT_DIR,
        'export_dir': EXPORT_DIR,
    }


ROUTES = {'save': save, 'upload': upload, 'file': file, 'info': info, 'list': list_}
