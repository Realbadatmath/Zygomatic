# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""file_2d — the server half of the File ▸ 2D/BIM interchange family (2026-09-08).

Three icons were placeholders: f_dxf (Export DXF), f_svg (Export SVG),
f_ifc (Export IFC). Two of them the browser can do on its own — a DXF is text
and an SVG is already text — so the tab writes those bytes and this module only
keeps the copy that anything else on this machine can open. The third cannot be
done in a browser at all: IFC is a building model, not a drawing, and the only
IFC writer on this machine lives inside Blender (the Bonsai extension ships
ifcopenshell in Blender's own site-packages). So `ifc` runs Blender headless
against arch_server_ext/file_2d_ifc.py, which rebuilds the drawing the way
arch_assistant.start_blender does and then walks the built meshes into
IfcWall / IfcSlab / IfcColumn / … entities.

ROUTES
  save POST {name, data_b64|text, ext}  -> {ok, path, rel, bytes, name, ext}
       Keep a copy of an export the browser just built. `ext` is fenced to
       dxf/svg/ifc and the file is stamped, so a save never overwrites.
  ifc  POST {doc, name, schema}         -> {ok, path, rel, bytes, elements, by_class, storeys}
       Build the drawing in Blender and write an .ifc under exports/.
  file GET  ?path=<path>|?name=<name>   -> (bytes, mime, filename)
       Serve one exported file back to the tab, fenced to the exports dir.
  list GET                              -> {ok, exports: [...], export_dir}

Standard library only here; the IFC work happens inside Blender's own Python
(ifcopenshell 0.8.5, LGPL-3.0, shipped with the Bonsai extension — it is
executed as a separate process, never imported into this one).
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
import time

from zyg_workflows.paths import ZYG_TMP_DIR, tmp_dir

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCH_DIR = os.path.join(HERE, 'data', 'architecture')
EXPORT_DIR = os.path.join(ARCH_DIR, 'exports')
IFC_SCRIPT = os.path.join(HERE, 'arch_server_ext', 'file_2d_ifc.py')
BLENDER = os.environ.get('BLENDER_BIN', '/usr/local/bin/blender')

# A DXF of a whole site in 3DFACE mode is tens of megabytes of text; 200 MB is
# past anything this studio can draw and small enough that one POST cannot fill
# the disk. (The HTTP layer caps the body at ~24 MB first — this is the second
# fence, not the first.)
MAX_BYTES = 200 * 1024 * 1024

EXPORT_EXT = ('dxf', 'svg', 'ifc')
MIME = {'dxf': 'image/vnd.dxf', 'svg': 'image/svg+xml', 'ifc': 'application/x-step'}
SCHEMAS = ('IFC4', 'IFC2X3', 'IFC4X3')

# Blender loads ~40 extensions here before it runs a line of ours; a build plus
# an IFC write of a large drawing is minutes, not seconds.
IFC_TIMEOUT_S = 600


class _BlenderLock:
    """Blender runs are SERIALISED across processes — copied from
    arch_ext_harness so a route can hold it without importing the test kit.
    Twenty-four family tests finishing at once each launched two headless
    Blenders; under that load the Bonsai extension's import crashed with SIGBUS."""

    # Every holder of this lock derives the path the same way, so they still meet in one file;
    # tmp_dir() creates the directory owner-only instead of the old world-writable /tmp path.
    PATH = str(ZYG_TMP_DIR / 'arch_ext_blender.lock')

    def __enter__(self):
        import fcntl

        tmp_dir()
        self.fh = open(self.PATH, 'w')
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        import fcntl

        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


def _slug(s: str, default: str = 'drawing') -> str:
    s = re.sub(r'[^a-z0-9]+', '-', str(s or '').strip().lower()).strip('-')
    return (s or default)[:48]


def _ensure() -> None:
    os.makedirs(EXPORT_DIR, exist_ok=True)


def _stamped(name: str, ext: str) -> str:
    stamp = time.strftime('%Y%m%d-%H%M%S')
    path = os.path.join(EXPORT_DIR, '%s-%s.%s' % (_slug(name), stamp, ext))
    n = 2
    while os.path.exists(path):  # two exports in one second
        path = os.path.join(EXPORT_DIR, '%s-%s-%d.%s' % (_slug(name), stamp, n, ext))
        n += 1
    return path


def _write(path: str, data: bytes) -> None:
    tmp = path + '.tmp'
    with open(tmp, 'wb') as fh:
        fh.write(data)
    os.replace(tmp, path)


def _bytes_of(payload: dict):
    """{data_b64|data|text} -> bytes, or (None, error). A DXF and an SVG are
    text, so `text` saves the tab one base64 round trip; a data: URL is accepted
    because that is what a FileReader hands over without a second conversion."""
    txt = payload.get('text')
    if isinstance(txt, str) and txt:
        data = txt.encode('utf-8')
    else:
        raw = payload.get('data_b64') or payload.get('data') or ''
        if not isinstance(raw, str) or not raw:
            return None, {'error': 'no text and no data_b64 in the payload', 'code': 400}
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


def save(payload, method):
    """Keep a copy of a .dxf, .svg or .ifc the browser just built."""
    _ensure()
    data, err = _bytes_of(payload)
    if err:
        return err
    name = str(payload.get('name') or '')
    ext = str(payload.get('ext') or '').strip().lower().lstrip('.')
    if not ext:
        ext = os.path.splitext(name)[1].lower().lstrip('.')
    if ext not in EXPORT_EXT:
        return {'error': 'ext must be one of %s' % (', '.join(EXPORT_EXT),), 'code': 400}
    path = _stamped(name, ext)
    _write(path, data)
    return {
        'ok': True,
        'path': path,
        'rel': os.path.relpath(path, HERE).replace(os.sep, '/'),
        'bytes': len(data),
        'ext': ext,
        'name': os.path.basename(path),
    }


def _fenced(payload: dict):
    """The one exported file a caller may read, or None. Everything is resolved
    and then compared against the exports directory: a path that climbs out with
    .. or a symlink is not an export, whatever it is called."""
    want = str(payload.get('path') or '').strip()
    if not want:
        nm = str(payload.get('name') or '').strip()
        if not nm or '/' in nm or '\\' in nm:
            return None
        want = os.path.join(EXPORT_DIR, nm)
    real = os.path.realpath(want)
    root = os.path.realpath(EXPORT_DIR)
    if not (real == root or real.startswith(root + os.sep)):
        return None
    if not os.path.isfile(real):
        return None
    if os.path.splitext(real)[1].lstrip('.').lower() not in EXPORT_EXT:
        return None
    return real


def file(payload, method):
    """The bytes of one exported file, so the tab can download the .ifc Blender
    just wrote without the server ever handing out a path it did not make."""
    path = _fenced(payload)
    if path is None:
        return {'error': 'no exported file there (exports only, and only .dxf/.svg/.ifc)', 'code': 404}
    with open(path, 'rb') as fh:
        data = fh.read()
    ext = os.path.splitext(path)[1].lstrip('.').lower()
    return (data, MIME.get(ext, 'application/octet-stream'), os.path.basename(path))


def list_(payload, method):
    _ensure()
    out = []
    for fn in sorted(os.listdir(EXPORT_DIR)):
        if fn.endswith('.tmp') or os.path.splitext(fn)[1].lstrip('.').lower() not in EXPORT_EXT:
            continue
        p = os.path.join(EXPORT_DIR, fn)
        if os.path.isfile(p):
            out.append(
                {
                    'name': fn,
                    'path': p,
                    'bytes': os.path.getsize(p),
                    'm': os.path.getmtime(p),
                    'ext': os.path.splitext(fn)[1].lstrip('.').lower(),
                }
            )
    out.sort(key=lambda r: -r['m'])
    return {'ok': True, 'exports': out[:200], 'export_dir': EXPORT_DIR}


def ifc(payload, method):
    """Build the drawing in Blender and write it out as IFC.

    The drawing JSON goes to a temp file, Blender runs file_2d_ifc.py against it
    (which imports arch_blender_build by path and calls build() — the same
    geometry the .blend and the .glb are made of), and the script prints one
    JSON line. Serialised behind the shared Blender lock.
    """
    _ensure()
    doc = payload.get('doc')
    if not isinstance(doc, dict) or not isinstance(doc.get('objects'), list) or not doc['objects']:
        return {'error': 'nothing to export — the drawing is empty', 'code': 400}
    if not os.path.exists(BLENDER):
        return {'error': 'Blender not found at %s' % (BLENDER,), 'code': 500}
    if not os.path.exists(IFC_SCRIPT):
        return {'error': 'arch_server_ext/file_2d_ifc.py is missing', 'code': 500}
    schema = str(payload.get('schema') or 'IFC4').strip().upper()
    if schema not in SCHEMAS:
        return {'error': 'schema must be one of %s' % (', '.join(SCHEMAS),), 'code': 400}
    name = str(payload.get('name') or doc.get('name') or 'drawing')
    out_path = _stamped(name, 'ifc')
    tmp = tempfile.mkdtemp(prefix='arch_f2d_')
    src = os.path.join(tmp, 'doc.json')
    with open(src, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh)
    cmd = [
        BLENDER,
        '-b',
        '--python',
        IFC_SCRIPT,
        '--',
        '--in',
        src,
        '--out',
        out_path,
        '--schema',
        schema,
        '--name',
        name[:80],
    ]
    try:
        with _BlenderLock():
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=IFC_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {'error': 'the IFC build did not finish inside %d s' % (IFC_TIMEOUT_S,), 'code': 504}
    info = {}
    for line in (p.stdout or '').splitlines():
        if line.startswith('IFCOUT '):
            try:
                info = json.loads(line[7:])
            except Exception:  # noqa: BLE001
                info = {}
    if not info.get('ok'):
        why = info.get('error') or (p.stderr or p.stdout or '')[-400:] or 'blender exit %d' % p.returncode
        return {'error': 'the IFC build failed: %s' % (str(why)[:400],), 'code': 500}
    if not os.path.isfile(out_path):
        return {'error': 'the IFC build reported success but wrote no file', 'code': 500}
    return {
        'ok': True,
        'path': out_path,
        'rel': os.path.relpath(out_path, HERE).replace(os.sep, '/'),
        'name': os.path.basename(out_path),
        'bytes': os.path.getsize(out_path),
        'elements': int(info.get('elements') or 0),
        'by_class': info.get('by_class') or {},
        'storeys': int(info.get('storeys') or 0),
        'schema': schema,
        'skipped': int(info.get('skipped') or 0),
    }


ROUTES = {'save': save, 'ifc': ifc, 'file': file, 'list': list_}
