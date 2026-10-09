# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""file_manage_setup — the disk half of the File/Setup icon family (2026-09-07).

Nine icons about the LIFE of a drawing and the SETUP of the studio:
f_tmpl, f_ver, f_auto, f_archive (File) and p_prefs, p_theme, p_perf, p_help,
p_about (Setup). Everything here is what the browser cannot do for itself:
template documents, a version shelf, a ZIP issue package and the facts the
About sheet reports.

Storage
  data/architecture/projects/<id>.json   drawings (architecture_studio owns it)
  data/architecture/versions/<pid>/<stamp>.json   one kept save, newest 50
  data/architecture/exports/                      whatever other families wrote

A TEMPLATE is an ordinary drawing whose ext.file_manage_setup.template is true,
so it is saved, listed, opened and deleted by the machinery that already
exists; nothing about it is a second kind of file.

Standard library only (json, os, time, zipfile) — PSF licence.
"""

from __future__ import annotations

import io
import json
import os
import re
import time
import zipfile
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCH_DIR = os.path.join(HERE, 'data', 'architecture')
VER_DIR = os.path.join(ARCH_DIR, 'versions')
EXPORT_DIR = os.path.join(ARCH_DIR, 'exports')
FAMILY = 'file_manage_setup'
KEEP_VERSIONS = 50
STAMP_RE = re.compile(r'^\d{8}-\d{6}-\d{3}$')


def _studio():
    from zyg_workflows import architecture_studio

    return architecture_studio


def _pid(pid) -> str:
    """A project id, validated the same way architecture_studio validates it —
    a slug and nothing else, so no payload can walk out of the folder."""
    st = _studio()
    pid = str(pid or '').strip()
    if not pid or pid != st._slug(pid):
        raise ValueError('bad drawing id')
    return pid


def _ver_dir(pid: str, make: bool = False) -> str:
    d = os.path.join(VER_DIR, _pid(pid))
    if make:
        os.makedirs(d, exist_ok=True)
    return d


def _stamp() -> str:
    t = time.time()
    return time.strftime('%Y%m%d-%H%M%S', time.localtime(t)) + '-%03d' % (int(t * 1000) % 1000)


def _read(path):
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, separators=(',', ':'))
    os.replace(tmp, path)


# ── templates ────────────────────────────────────────────────────────────────
def _is_template(doc: dict) -> bool:
    ext = doc.get('ext') if isinstance(doc, dict) else None
    fam = (ext or {}).get(FAMILY) if isinstance(ext, dict) else None
    return bool(isinstance(fam, dict) and fam.get('template'))


def _mark_template(doc: dict) -> dict:
    out = dict(doc or {})
    ext = dict(out.get('ext') or {})
    fam = dict(ext.get(FAMILY) or {})
    fam['template'] = True
    ext[FAMILY] = fam
    out['ext'] = ext
    return out


def _rec(oid, kind, p, x=0.0, z=0.0, y=0.0, ry=0.0, mat='mat_concrete', name=''):
    return {
        'id': oid,
        'kind': kind,
        'name': name or kind,
        'p': p,
        'x': float(x),
        'y': float(y),
        'z': float(z),
        'rx': 0,
        'ry': float(ry),
        'rz': 0,
        's': 1,
        'mat': mat,
        'hidden': False,
        'grp': '',
        'meta': {},
    }


def _seed_docs():
    """The two templates the studio ships with, so 'new from template' is never
    an empty list. A4 at 1:100 is 21 x 29.7 m — a site plan you can actually
    print. The row house is the smallest complete building: four walls, a
    slab, a door, two windows and a gable roof."""
    half = 3.14159265358979 / 2
    a4 = {
        'name': 'Empty A4 site',
        'units': 'm',
        'schema': 1,
        'cell_m': 1,
        'objects': [
            _rec(
                'o1',
                'slab',
                {'w': 21.0, 'd': 29.7, 't': 0.2},
                0,
                0,
                -0.2,
                mat='mat_grass',
                name='A4 site 21 x 29.7 m (1:100)',
            )
        ],
    }
    w, d, h, t = 5.4, 8.0, 2.7, 0.24
    row = {
        'name': 'Row house 5.4 m',
        'units': 'm',
        'schema': 1,
        'cell_m': 1,
        'objects': [
            _rec(
                'o1', 'slab', {'w': w + t, 'd': d + t, 't': 0.22}, 0, 0, -0.22, mat='mat_concrete', name='Ground slab'
            ),
            _rec('o2', 'wall', {'len': w, 'h': h, 't': t}, 0, -d / 2, 0, 0, 'mat_brick', 'Front wall'),
            _rec('o3', 'wall', {'len': w, 'h': h, 't': t}, 0, d / 2, 0, 0, 'mat_brick', 'Back wall'),
            _rec('o4', 'wall', {'len': d, 'h': h, 't': t}, -w / 2, 0, 0, half, 'mat_brick', 'Party wall west'),
            _rec('o5', 'wall', {'len': d, 'h': h, 't': t}, w / 2, 0, 0, half, 'mat_brick', 'Party wall east'),
            _rec('o6', 'door', {'w': 0.9, 'h': 2.1}, 0, -d / 2, 0, 0, 'mat_timber', 'Front door'),
            _rec('o7', 'window', {'w': 1.2, 'h': 1.4, 'sill': 0.9}, -1.4, d / 2, 0, 0, 'mat_glass', 'Rear window west'),
            _rec('o8', 'window', {'w': 1.2, 'h': 1.4, 'sill': 0.9}, 1.4, d / 2, 0, 0, 'mat_glass', 'Rear window east'),
            _rec(
                'o9',
                'roof_gable',
                {'w': w + 0.8, 'd': d + 0.8, 'h': 2.0, 'over': 0.4},
                0,
                0,
                h,
                0,
                'mat_roof_tile',
                'Gable roof',
            ),
        ],
    }
    return [('tmpl-empty-a4-site', a4), ('tmpl-row-house-5-4-m', row)]


def _seed_if_empty() -> int:
    st = _studio()
    have = 0
    for row in st.list_projects():
        doc = _read(os.path.join(st.PROJ_DIR, row['id'] + '.json'))
        if doc and _is_template(doc):
            have += 1
    if have >= 2:
        return have
    made = 0
    for pid, doc in _seed_docs():
        if os.path.exists(os.path.join(st.PROJ_DIR, pid + '.json')):
            continue
        r = st.save_project(_mark_template(doc), pid=pid, name=doc['name'])
        if r.get('ok'):
            made += 1
    return have + made


def templates(payload, method):
    """[{id, name, objects}] — every drawing flagged as a template."""
    _seed_if_empty()
    st = _studio()
    out = []
    for row in st.list_projects():
        doc = _read(os.path.join(st.PROJ_DIR, row['id'] + '.json'))
        if not doc or not _is_template(doc):
            continue
        out.append(
            {
                'id': row['id'],
                'name': doc.get('name') or row['id'],
                'objects': len(doc.get('objects') or []),
                'm': row['m'],
            }
        )
    out.sort(key=lambda r: r['name'].lower())
    return {'ok': True, 'templates': out}


def save_template(payload, method):
    """Write the posted document as a template."""
    doc = payload.get('doc')
    name = str(payload.get('name') or '').strip()
    if not isinstance(doc, dict) or not isinstance(doc.get('objects'), list):
        return {'error': 'save_template needs a doc with an objects[] list', 'code': 400}
    if not name:
        return {'error': 'a template needs a name', 'code': 400}
    r = _studio().save_project(_mark_template(doc), pid=str(payload.get('id') or ''), name=name)
    if r.get('error'):
        r.setdefault('code', 400)
    return r


def open_template(payload, method):
    """The template's document, for opening as a NEW untitled drawing. Accepts
    an id or a name."""
    _seed_if_empty()
    want_id = str(payload.get('id') or '').strip()
    want_name = str(payload.get('name') or '').strip().lower()
    st = _studio()
    for row in st.list_projects():
        doc = _read(os.path.join(st.PROJ_DIR, row['id'] + '.json'))
        if not doc or not _is_template(doc):
            continue
        if (
            (want_id and row['id'] == want_id)
            or (want_name and str(doc.get('name') or '').lower() == want_name)
            or (not want_id and not want_name)
        ):
            doc['id'] = row['id']
            return {'ok': True, 'id': row['id'], 'name': doc.get('name') or row['id'], 'doc': doc}
    return {'error': 'no such template', 'code': 404}


# ── versions ─────────────────────────────────────────────────────────────────
def _prune(d: str):
    files = sorted(f for f in os.listdir(d) if f.endswith('.json'))
    for f in files[:-KEEP_VERSIONS] if len(files) > KEEP_VERSIONS else []:
        try:
            os.remove(os.path.join(d, f))
        except OSError as _exc:
            _zyg_log.debug('snapshot pruning skipped a file: %s', _exc)


def snapshot(payload, method):
    """Keep a copy of a drawing as it is now. Called after every successful
    save and by the autosave timer; it never touches the named save."""
    try:
        pid = _pid(payload.get('pid'))
    except ValueError as e:
        return {'error': str(e), 'code': 400}
    doc = payload.get('doc')
    if not isinstance(doc, dict) or not isinstance(doc.get('objects'), list):
        return {'error': 'snapshot needs a doc with an objects[] list', 'code': 400}
    d = _ver_dir(pid, make=True)
    stamp = _stamp()
    _write(
        os.path.join(d, stamp + '.json'),
        {
            'stamp': stamp,
            'label': str(payload.get('label') or '')[:60],
            'saved': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'doc': doc,
        },
    )
    _prune(d)
    return {
        'ok': True,
        'pid': pid,
        'stamp': stamp,
        'objects': len(doc.get('objects') or []),
        'n': len([f for f in os.listdir(d) if f.endswith('.json')]),
    }


def _ver_rows(pid: str):
    d = _ver_dir(pid)
    if not os.path.isdir(d):
        return []
    rows = []
    for f in sorted(os.listdir(d), reverse=True):
        if not f.endswith('.json'):
            continue
        path = os.path.join(d, f)
        v = _read(path) or {}
        rows.append(
            {
                'stamp': v.get('stamp') or f[:-5],
                'label': v.get('label') or '',
                'saved': v.get('saved') or '',
                'objects': len((v.get('doc') or {}).get('objects') or []),
                'bytes': os.path.getsize(path),
            }
        )
    return rows


def versions(payload, method):
    """action = list | restore | label | delete."""
    try:
        pid = _pid(payload.get('pid'))
    except ValueError as e:
        return {'error': str(e), 'code': 400}
    action = str(payload.get('action') or 'list').strip().lower()
    if action == 'list':
        return {'ok': True, 'pid': pid, 'versions': _ver_rows(pid), 'keep': KEEP_VERSIONS}
    stamp = str(payload.get('stamp') or '').strip()
    if not STAMP_RE.match(stamp):
        return {'error': 'that is not a version stamp', 'code': 400}
    path = os.path.join(_ver_dir(pid), stamp + '.json')
    v = _read(path)
    if v is None:
        return {'error': 'no such version', 'code': 404}
    if action == 'restore':
        return {'ok': True, 'pid': pid, 'stamp': stamp, 'label': v.get('label') or '', 'doc': v.get('doc') or {}}
    if action == 'label':
        v['label'] = str(payload.get('label') or '')[:60]
        _write(path, v)
        return {'ok': True, 'pid': pid, 'stamp': stamp, 'label': v['label']}
    if action == 'delete':
        os.remove(path)
        return {'ok': True, 'pid': pid, 'stamp': stamp, 'deleted': True}
    return {'error': 'action must be list, restore, label or delete', 'code': 400}


def diff(payload, method):
    """What changed between a kept version and the document posted with it —
    counted by record id, so the version list can say what a restore costs."""
    try:
        pid = _pid(payload.get('pid'))
    except ValueError as e:
        return {'error': str(e), 'code': 400}
    stamp = str(payload.get('stamp') or '').strip()
    if not STAMP_RE.match(stamp):
        return {'error': 'that is not a version stamp', 'code': 400}
    v = _read(os.path.join(_ver_dir(pid), stamp + '.json'))
    if v is None:
        return {'error': 'no such version', 'code': 404}
    old = {str(o.get('id')): o for o in ((v.get('doc') or {}).get('objects') or [])}
    cur_doc = payload.get('doc')
    if not isinstance(cur_doc, dict):
        cur_doc = (_studio().load_project(pid) or {}).get('doc') or {}
    new = {str(o.get('id')): o for o in (cur_doc.get('objects') or [])}
    keys = ('kind', 'p', 'x', 'y', 'z', 'rx', 'ry', 'rz', 's', 'mat', 'hidden', 'name', 'grp')
    changed = [k for k in old if k in new and any(old[k].get(f) != new[k].get(f) for f in keys)]
    return {
        'ok': True,
        'pid': pid,
        'stamp': stamp,
        'added': sorted(set(new) - set(old)),
        'removed': sorted(set(old) - set(new)),
        'changed': sorted(changed),
        'counts': {
            'added': len(set(new) - set(old)),
            'removed': len(set(old) - set(new)),
            'changed': len(changed),
            'old': len(old),
            'new': len(new),
        },
    }


# ── archive ──────────────────────────────────────────────────────────────────
def archive(payload, method):
    """One issue package: the drawing, every version kept for it, and every
    file under data/architecture/exports/ whose name starts with its slug."""
    try:
        pid = _pid(payload.get('pid'))
    except ValueError as e:
        return {'error': str(e), 'code': 400}
    st = _studio()
    doc = payload.get('doc')
    if not isinstance(doc, dict) or not isinstance(doc.get('objects'), list):
        got = st.load_project(pid)
        if got.get('error'):
            return {'error': got['error'], 'code': 404}
        doc = got['doc']
    slug = st._slug(doc.get('name') or pid)
    n_obj = len(doc.get('objects') or [])
    kinds: dict = {}
    for o in doc.get('objects') or []:
        k = str(o.get('kind') or '?')
        kinds[k] = kinds.get(k, 0) + 1

    vers = _ver_rows(pid)
    vdir = _ver_dir(pid)
    exports = []
    if os.path.isdir(EXPORT_DIR):
        for fn in sorted(os.listdir(EXPORT_DIR)):
            p = os.path.join(EXPORT_DIR, fn)
            if os.path.isfile(p) and fn.lower().startswith(slug.lower()):
                exports.append(fn)

    readme = [
        'Architecture Studio issue package',
        '',
        'drawing      : %s' % (doc.get('name') or pid),
        'id           : %s' % pid,
        'objects      : %d' % n_obj,
        'kinds        : %s' % (', '.join('%s x%d' % (k, v) for k, v in sorted(kinds.items())) or 'none'),
        'versions kept: %d' % len(vers),
        'exports      : %d' % len(exports),
        'packaged     : %s' % time.strftime('%Y-%m-%d %H:%M:%S'),
        '',
        'The drawing JSON holds PARAMETERS, not geometry: every object is',
        'rebuilt from its p{} by the studio, by Blender and by the assistant.',
        'versions/ is the shelf of kept saves, newest last.',
        '',
    ]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('README.txt', '\n'.join(readme))
        z.writestr('%s.json' % slug, json.dumps(doc, indent=1))
        for v in vers:
            p = os.path.join(vdir, v['stamp'] + '.json')
            if os.path.isfile(p):
                z.write(p, 'versions/%s.json' % v['stamp'])
        for fn in exports:
            z.write(os.path.join(EXPORT_DIR, fn), 'exports/' + fn)
    data = buf.getvalue()
    return (data, 'application/zip', slug + '.zip')


# ── about ────────────────────────────────────────────────────────────────────
def _vendor_licences():
    out = []
    vend = os.path.join(HERE, 'vendor')
    if not os.path.isdir(vend):
        return out
    for root, _dirs, files in os.walk(vend):
        for fn in files:
            if re.match(r'^(licen[cs]e|copying)', fn, re.I):
                rel = os.path.relpath(os.path.join(root, fn), HERE)
                first = ''
                try:
                    with open(os.path.join(root, fn), 'r', encoding='utf-8', errors='replace') as fh:
                        for line in fh:
                            line = line.strip()
                            if line:
                                first = line[:120]
                                break
                except OSError as _exc:
                    _zyg_log.debug('drawing first line unreadable: %s', _exc)
                out.append({'file': rel, 'first_line': first})
    out.sort(key=lambda r: r['file'])
    return out


def about(payload, method):
    """What this engine is, right now — read off the files, not off a note."""
    st = _studio()
    page = os.path.join(HERE, 'inspection.html')
    try:
        mt = os.path.getmtime(page)
    except OSError:
        mt = 0.0
    js = []
    jsdir = os.path.join(HERE, 'arch_ext')
    if os.path.isdir(jsdir):
        js = sorted(f[:-3] for f in os.listdir(jsdir) if f.endswith('.js'))
    tools, kinds, names = 0, 0, []
    try:
        from zyg_workflows import arch_assistant as A

        A.load_extensions()
        tools = len(A.TOOL_DEFS)
        kinds = len(A.KINDS)
        names = sorted(t['name'] for t in A.TOOL_DEFS)
    except Exception as e:  # noqa: BLE001
        names = ['(assistant not importable: %s)' % (str(e)[:80],)]
    packs, lic_sum = [], {}
    try:
        from zyg_workflows import architecture_assets as AA

        for p in AA.packs():
            lic = p.get('licence') or '?'
            row = lic_sum.setdefault(lic, {'licence': lic, 'packs': 0, 'items': 0, 'attrib': 0})
            row['packs'] += 1
            row['items'] += int(p.get('count') or 0)
            row['attrib'] += 1 if p.get('attrib') else 0
        packs = sorted(lic_sum.values(), key=lambda r: -r['packs'])
    except Exception as e:  # noqa: BLE001
        packs = [{'licence': 'unreadable: %s' % (str(e)[:60],), 'packs': 0, 'items': 0, 'attrib': 0}]
    return {
        'ok': True,
        'mtime': mt,
        'built': time.strftime('%Y-%m-%d %H:%M', time.localtime(mt)) if mt else '',
        'families': st.ext_families(),
        'js_families': js,
        'tools': tools,
        'kinds': kinds,
        'assistant_tools': names,
        'licences': _vendor_licences(),
        'packs': packs,
    }


ROUTES = {
    'templates': templates,
    'save_template': save_template,
    'open_template': open_template,
    'versions': versions,
    'snapshot': snapshot,
    'diff': diff,
    'archive': archive,
    'about': about,
}
