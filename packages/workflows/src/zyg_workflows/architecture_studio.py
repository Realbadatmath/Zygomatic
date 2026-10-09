# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Architecture Studio — the library and the project store behind the
Inspection SPA's Architecture Studio tab (2026-09-01).

The tab has three columns: a left rail (the library, drawn with the Sfx
Studio's list idiom), a 3D drawing viewport in the middle (three.js/WebGL2,
so the drawing itself runs on the local GPU — this module never touches it),
and a right-hand icon rail of drawing tools.

This module owns only what has to survive a page reload:

  * the LIBRARY — the catalogue the left rail lists. Three of its four
    sections are a fixed catalogue of things you can insert (building
    elements, primitives, materials); the fourth is whatever drawings are
    on disk. The catalogue is declared here rather than in the page so the
    browser and any future non-browser caller read the same list, and so a
    new element is one entry, not a markup edit.

  * the PROJECT STORE — one JSON document per drawing under
    data/architecture/projects/. A document is the scene as the client
    models it: a flat list of objects, each with a kind, a transform and
    its own parameters. Nothing here interprets those parameters; the
    client's geometry factory does. That keeps a saved drawing readable
    and re-openable even after the factory grows new options.

Deliberately NOT here: geometry, meshes, rendering, CSG. The viewport is a
GPU program; this is a filing cabinet with a catalogue in the front.
"""

from __future__ import annotations

import json
import os
import re
import time
import unicodedata

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))
ARCH_DIR = os.path.join(HERE, 'data', 'architecture')
HERE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJ_DIR = os.path.join(ARCH_DIR, 'projects')
TRASH_DIR = os.path.join(ARCH_DIR, 'trash')

# A drawing is text, but a big one is a lot of text. 24 MB is roughly a
# 60,000-object scene at the document's ~400 bytes an object — far past
# anything hand-drawn, and small enough that a runaway client cannot fill
# the disk in one POST.
MAX_DOC_BYTES = 24 * 1024 * 1024

# ── the catalogue ───────────────────────────────────────────────────────────
# Every leaf carries the `kind` the client's geometry factory switches on and
# the default parameters it starts from. `u` is the unit each dimension is in
# — metres throughout; the studio has one world scale and no other.
#
# Sections mirror the rail's three levels: section (h4) → group (bold row) →
# item (leaf). A group with one item still gets a group, so the tree never
# changes shape depending on how full it is.

ELEMENTS = [
    (
        'Walls & openings',
        [
            (
                'wall',
                'Wall',
                {'len': 4.0, 'h': 2.7, 't': 0.24},
                'Straight wall. Doors and windows dropped on it cut a real hole.',
            ),
            ('partition', 'Partition', {'len': 3.0, 'h': 2.5, 't': 0.10}, 'Thin internal wall.'),
            ('door', 'Door', {'w': 0.9, 'h': 2.1, 't': 0.06}, 'Leaf + frame. Snap it to a wall to cut the opening.'),
            ('double_door', 'Double door', {'w': 1.6, 'h': 2.1, 't': 0.06}, 'Two leaves in one frame.'),
            (
                'window',
                'Window',
                {'w': 1.2, 'h': 1.4, 'sill': 0.9, 't': 0.06},
                'Frame + glazing. Snap it to a wall to cut the opening.',
            ),
            (
                'opening',
                'Void opening',
                {'w': 1.0, 'h': 2.1, 'sill': 0.0},
                'A hole with nothing in it — a pass-through or a doorway with no door.',
            ),
        ],
    ),
    (
        'Structure',
        [
            ('column_rect', 'Column (rect)', {'w': 0.3, 'd': 0.3, 'h': 3.0}, 'Rectangular column.'),
            ('column_round', 'Column (round)', {'r': 0.18, 'h': 3.0}, 'Circular column.'),
            ('beam', 'Beam', {'len': 5.0, 'w': 0.2, 'h': 0.4}, 'Rectangular beam.'),
            ('slab', 'Slab', {'w': 6.0, 'd': 4.0, 't': 0.22}, 'Floor or ceiling slab.'),
            ('footing', 'Pad footing', {'w': 1.0, 'd': 1.0, 't': 0.35}, 'Isolated pad foundation.'),
            (
                'truss',
                'Truss',
                {'span': 8.0, 'h': 1.2, 'bays': 6, 'w': 0.12},
                'Parametric king-post truss — chords, posts and diagonals.',
            ),
        ],
    ),
    (
        'Circulation',
        [
            (
                'stair_straight',
                'Stair (straight)',
                {'steps': 16, 'rise': 0.175, 'run': 0.28, 'w': 1.0},
                'Straight flight.',
            ),
            (
                'stair_l',
                'Stair (L-shaped)',
                {'steps_a': 8, 'steps_b': 8, 'rise': 0.175, 'run': 0.28, 'w': 1.0},
                'Two flights with a quarter landing.',
            ),
            (
                'stair_spiral',
                'Stair (spiral)',
                {'steps': 18, 'rise': 0.19, 'r_in': 0.15, 'r_out': 1.1, 'sweep': 360},
                'Helical flight around a newel.',
            ),
            (
                'ramp',
                'Ramp',
                {'len': 6.0, 'w': 1.5, 'rise': 0.5, 't': 0.15},
                'Sloped slab — the rise/len ratio is the gradient.',
            ),
            ('railing', 'Railing', {'len': 3.0, 'h': 1.0, 'posts': 5, 't': 0.04}, 'Posts with a top rail.'),
            ('ladder', 'Ladder', {'h': 3.0, 'w': 0.5, 'rungs': 10, 't': 0.04}, 'Two stiles, N rungs.'),
        ],
    ),
    (
        'Roofs',
        [
            ('roof_flat', 'Flat roof', {'w': 8.0, 'd': 6.0, 't': 0.3}, 'Flat deck.'),
            (
                'roof_gable',
                'Gable roof',
                {'w': 8.0, 'd': 6.0, 'h': 2.4, 'over': 0.4},
                'Two pitches meeting at a ridge.',
            ),
            ('roof_hip', 'Hip roof', {'w': 8.0, 'd': 6.0, 'h': 2.4, 'over': 0.4}, 'Four pitches meeting at a ridge.'),
            ('roof_shed', 'Shed roof', {'w': 6.0, 'd': 4.0, 'h': 1.6, 'over': 0.3}, 'Single pitch.'),
            ('roof_dome', 'Dome', {'r': 3.0, 'h': 2.4}, 'Hemispherical shell.'),
            ('roof_vault', 'Barrel vault', {'w': 4.0, 'd': 8.0, 'h': 2.0}, 'Half-cylinder vault.'),
        ],
    ),
    (
        'Site',
        [
            ('pad', 'Ground pad', {'w': 20.0, 'd': 20.0, 't': 0.2}, 'A flat plot to build on.'),
            ('road', 'Road', {'len': 20.0, 'w': 6.0, 't': 0.08}, 'Paved strip.'),
            ('path', 'Path', {'len': 10.0, 'w': 1.2, 't': 0.05}, 'Narrow paved strip.'),
            ('tree', 'Tree', {'h': 6.0, 'r_can': 2.0, 'r_trunk': 0.18}, 'Trunk + canopy — a scale cue.'),
            ('bollard', 'Bollard', {'h': 0.9, 'r': 0.09}, 'Street furniture.'),
            ('person', 'Scale figure', {'h': 1.75}, '1.75 m human — the only honest scale check.'),
        ],
    ),
]

PRIMITIVES = [
    (
        'Solids',
        [
            ('box', 'Box', {'w': 1.0, 'd': 1.0, 'h': 1.0}, 'Rectangular prism.'),
            ('cylinder', 'Cylinder', {'r': 0.5, 'h': 1.0, 'seg': 32}, 'Circular prism.'),
            ('sphere', 'Sphere', {'r': 0.5, 'seg': 32}, 'Sphere.'),
            ('cone', 'Cone', {'r': 0.5, 'h': 1.0, 'seg': 32}, 'Cone.'),
            ('pyramid', 'Pyramid', {'r': 0.7, 'h': 1.0, 'sides': 4}, 'N-sided pyramid.'),
            ('torus', 'Torus', {'r': 0.5, 'rt': 0.15, 'seg': 32}, 'Ring.'),
            ('wedge', 'Wedge', {'w': 1.0, 'd': 1.0, 'h': 1.0}, 'Half a box, cut on the diagonal.'),
            ('capsule', 'Capsule', {'r': 0.3, 'h': 1.0, 'seg': 24}, 'Cylinder with domed ends.'),
        ],
    ),
    (
        'Flat',
        [
            ('plane', 'Plane', {'w': 2.0, 'd': 2.0}, 'Single-sided flat quad.'),
            ('disc', 'Disc', {'r': 1.0, 'seg': 48}, 'Flat circle.'),
        ],
    ),
]

# Materials are appearance only — colour, roughness, metalness, opacity. They
# carry no cost, no supplier and no thickness, and nothing downstream reads
# them as a specification.
MATERIALS = [
    (
        'Structure',
        [
            ('mat_concrete', 'Concrete', {'col': '#9a9a94', 'rough': 0.92, 'metal': 0.0}, ''),
            ('mat_brick', 'Brick', {'col': '#9c5a44', 'rough': 0.95, 'metal': 0.0}, ''),
            ('mat_blockwork', 'Blockwork', {'col': '#8f8f88', 'rough': 0.96, 'metal': 0.0}, ''),
            ('mat_stone', 'Stone', {'col': '#8b8578', 'rough': 0.88, 'metal': 0.0}, ''),
            ('mat_steel', 'Steel', {'col': '#8d939b', 'rough': 0.35, 'metal': 0.9}, ''),
            ('mat_timber', 'Timber', {'col': '#b07a44', 'rough': 0.8, 'metal': 0.0}, ''),
        ],
    ),
    (
        'Finish',
        [
            ('mat_plaster', 'Plaster', {'col': '#e8e4dc', 'rough': 0.9, 'metal': 0.0}, ''),
            ('mat_paint_white', 'Paint (white)', {'col': '#f2f2f0', 'rough': 0.7, 'metal': 0.0}, ''),
            ('mat_paint_dark', 'Paint (charcoal)', {'col': '#33343a', 'rough': 0.7, 'metal': 0.0}, ''),
            ('mat_glass', 'Glass', {'col': '#a8d8e8', 'rough': 0.05, 'metal': 0.0, 'op': 0.28}, ''),
            ('mat_roof_tile', 'Roof tile', {'col': '#7d4030', 'rough': 0.9, 'metal': 0.0}, ''),
            ('mat_zinc', 'Zinc', {'col': '#767c82', 'rough': 0.45, 'metal': 0.75}, ''),
        ],
    ),
    (
        'Site',
        [
            ('mat_grass', 'Grass', {'col': '#5e7d43', 'rough': 1.0, 'metal': 0.0}, ''),
            ('mat_asphalt', 'Asphalt', {'col': '#3c3d40', 'rough': 0.95, 'metal': 0.0}, ''),
            ('mat_gravel', 'Gravel', {'col': '#8a8578', 'rough': 1.0, 'metal': 0.0}, ''),
            ('mat_water', 'Water', {'col': '#2f6f8f', 'rough': 0.08, 'metal': 0.1, 'op': 0.6}, ''),
        ],
    ),
    (
        'Landscape',
        [
            (
                'mat_rock',
                'Rock',
                {'col': '#6e6a63', 'rough': 0.95, 'metal': 0.0},
                'Bare rock: cliffs, boulders, mountain sides.',
            ),
            ('mat_snow', 'Snow', {'col': '#f4f6f8', 'rough': 0.6, 'metal': 0.0}, 'Snow caps above the snow line.'),
            ('mat_sand', 'Sand', {'col': '#d9c48f', 'rough': 1.0, 'metal': 0.0}, 'Beaches, dunes, ripe wheat.'),
            (
                'mat_soil',
                'Soil',
                {'col': '#5a4632', 'rough': 1.0, 'metal': 0.0},
                'Bare earth: river beds, ploughed fields, forest floor.',
            ),
            (
                'mat_foliage',
                'Foliage',
                {'col': '#3f6b2e', 'rough': 1.0, 'metal': 0.0},
                'Dense leaf mass: forests, hedgerows, crops.',
            ),
        ],
    ),
]

SECTION_DESC = {
    'projects': 'Saved drawings. Click one to open it in the viewport.',
    'elements': 'Parametric building parts. Click to drop one at the cursor.',
    'primitives': 'Plain solids for massing and blocking out.',
    'materials': 'Appearance presets. Click to arm the paint tool, then click an object.',
    'assets': 'CC0 models from the mesh packs. Click to drop one at the cursor.',
}


def _leaf(kind, name, params, note, section):
    return {'id': f'{section}:{kind}', 'kind': kind, 'n': name, 'p': dict(params), 'note': note}


def _catalogue_section(key, label, groups):
    out = []
    for gname, items in groups:
        out.append({'g': gname, 'items': [_leaf(k, n, p, note, key) for (k, n, p, note) in items]})
    return {
        'key': key,
        'label': label,
        'desc': SECTION_DESC.get(key, ''),
        'groups': out,
        'count': sum(len(g['items']) for g in out),
    }


# ── project store ───────────────────────────────────────────────────────────

_SLUG_BAD = re.compile(r'[^a-z0-9]+')


def _slug(name: str) -> str:
    s = unicodedata.normalize('NFKD', str(name or '')).encode('ascii', 'ignore').decode()
    s = _SLUG_BAD.sub('-', s.lower()).strip('-')
    return s[:60] or 'drawing'


def _ensure_dirs():
    os.makedirs(PROJ_DIR, exist_ok=True)
    os.makedirs(TRASH_DIR, exist_ok=True)


def _proj_path(pid: str) -> str:
    """Resolve a project id to a path inside PROJ_DIR, or raise.

    The id reaches us from the browser, so it is validated as a slug rather
    than joined and hoped over: no separators, no dots, nothing that can walk
    out of the projects folder.
    """
    pid = str(pid or '')
    if not pid or pid != _slug(pid):
        raise ValueError('bad project id')
    return os.path.join(PROJ_DIR, pid + '.json')


def _read_doc(path: str):
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _doc_summary(pid: str, doc: dict, path: str) -> dict:
    objs = doc.get('objects') or []
    kinds = {}
    for o in objs:
        k = str(o.get('kind') or '?')
        kinds[k] = kinds.get(k, 0) + 1
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    return {
        'id': pid,
        'n': doc.get('name') or pid,
        'objects': len(objs),
        'kinds': kinds,
        'm': mtime,
        'created': doc.get('created') or '',
        'units': doc.get('units') or 'm',
        'bytes': os.path.getsize(path) if os.path.exists(path) else 0,
    }


def list_projects() -> list:
    _ensure_dirs()
    out = []
    for fn in os.listdir(PROJ_DIR):
        if not fn.endswith('.json'):
            continue
        path = os.path.join(PROJ_DIR, fn)
        doc = _read_doc(path)
        if doc is None:
            # A file that will not parse is still a fact about the folder —
            # listing it as broken beats silently hiding the user's drawing.
            out.append(
                {
                    'id': fn[:-5],
                    'n': fn[:-5],
                    'objects': 0,
                    'kinds': {},
                    'm': os.path.getmtime(path),
                    'broken': True,
                    'created': '',
                    'units': 'm',
                    'bytes': os.path.getsize(path),
                }
            )
            continue
        out.append(_doc_summary(fn[:-5], doc, path))
    out.sort(key=lambda r: -r['m'])
    return out


def library() -> dict:
    """The whole left rail in one call: saved drawings + the fixed catalogue."""
    projects = list_projects()
    proj_section = {
        'key': 'projects',
        'label': 'Projects',
        'desc': SECTION_DESC['projects'],
        'count': len(projects),
        'groups': [
            {
                'g': 'Saved drawings',
                'items': [
                    {
                        'id': 'proj:' + p['id'],
                        'kind': 'project',
                        'n': p['n'],
                        'p': {'pid': p['id']},
                        'note': (
                            'unreadable file'
                            if p.get('broken')
                            else f'{p["objects"]} object' + ('' if p['objects'] == 1 else 's')
                        ),
                        'm': p['m'],
                        'broken': bool(p.get('broken')),
                    }
                    for p in projects
                ],
            }
        ],
    }
    mats = _catalogue_section('materials', 'Materials', MATERIALS)
    # The CC0 PBR surfaces join the SAME section as the flat presets rather
    # than getting one of their own: both answer "what is this made of", and
    # the paint tool arms them identically. The presets stay first — a massing
    # study wants a grey box, not a photograph of concrete.
    surf = _surfaces_groups()
    if surf:
        mats['groups'].extend(surf)
        mats['count'] = sum(len(g['items']) for g in mats['groups'])

    sections = [
        proj_section,
        _catalogue_section('elements', 'Building elements', ELEMENTS),
        _catalogue_section('primitives', 'Primitives', PRIMITIVES),
        mats,
    ]
    _merge_extensions(sections)
    # The Assets rail is a SEPARATE module and a soft dependency: a broken or
    # absent mesh-pack tree costs the rail its assets section, never the tab.
    assets = _assets_section()
    if assets:
        sections.append(assets)
    return {
        'ok': True,
        'sections': sections,
        'defaults': {'grid': 0.25, 'wall_h': 2.7, 'wall_t': 0.24, 'units': 'm'},
    }


def _surfaces_groups():
    """The CC0 PBR groups, or None. Soft dependency, same rule as the assets
    rail: a broken surface catalogue costs the rail its textures, never the tab."""
    try:
        from zyg_workflows import architecture_materials as _am

        return _am.catalogue().get('groups') or None
    except Exception:
        return None


def _merge_extensions(sections: list) -> None:
    """arch_ext/*.json (2026-09-06): each file adds GROUPS of leaves to a rail
    section — an existing one by key ('elements', 'primitives') or a new one.
    Shape: {"section_key": "elements", "section_label": "Building elements",
            "groups": [{"g": "Curved walls",
                        "items": [[kind, name, {params}, note], ...]}]}
    A broken file costs its own groups, never the rail."""
    import glob

    for f in sorted(glob.glob(os.path.join(HERE_DIR, 'arch_ext', '*.json'))):
        try:
            with open(f, encoding='utf-8') as fh:
                ext = json.load(fh)
            key = str(ext.get('section_key') or 'extensions')
            sec = next((x for x in sections if x['key'] == key), None)
            if sec is None:
                sec = {
                    'key': key,
                    'label': str(ext.get('section_label') or key.title()),
                    'desc': SECTION_DESC.get(key, ''),
                    'groups': [],
                    'count': 0,
                }
                sections.append(sec)
            for g in ext.get('groups') or []:
                items = [
                    _leaf(
                        str(it[0]),
                        str(it[1]),
                        it[2] if len(it) > 2 and isinstance(it[2], dict) else {},
                        str(it[3]) if len(it) > 3 else '',
                        key,
                    )
                    for it in (g.get('items') or [])
                    if isinstance(it, (list, tuple)) and len(it) >= 2
                ]
                if items:
                    sec['groups'].append({'g': str(g.get('g') or os.path.basename(f)), 'items': items})
            sec['count'] = sum(len(g['items']) for g in sec['groups'])
        except Exception as e:  # noqa: BLE001
            _zyg_log.info(f'[architecture_studio] extension {os.path.basename(f)} skipped: {e!r}')


def _assets_section():
    try:
        from zyg_workflows import architecture_assets as _aa

        cat = _aa.catalogue()
    except Exception:
        return None
    if not cat.get('groups'):
        return None
    return {
        'key': 'assets',
        'label': 'Assets',
        'desc': SECTION_DESC['assets'],
        'count': cat['count'],
        'groups': cat['groups'],
        'packs': cat['packs'],
        'refused': cat['refused'],
    }


def load_project(pid: str) -> dict:
    path = _proj_path(pid)
    doc = _read_doc(path)
    if doc is None:
        return {'error': 'no such drawing (or it will not parse)'}
    doc['id'] = pid
    return {'ok': True, 'doc': doc}


def save_project(doc: dict, pid: str = '', name: str = '') -> dict:
    """Write a drawing. Returns its id — which may differ from the one asked
    for, when the name is new or the requested slug is taken by another
    drawing under Save As."""
    _ensure_dirs()
    if not isinstance(doc, dict):
        return {'error': 'the drawing must be an object'}
    objs = doc.get('objects')
    if not isinstance(objs, list):
        return {'error': 'the drawing has no objects[] list'}

    name = str(name or doc.get('name') or '').strip() or 'Untitled drawing'
    pid = str(pid or '').strip()
    if pid:
        try:
            _proj_path(pid)
        except ValueError:
            pid = ''
    if not pid:
        base = _slug(name)
        pid = base
        i = 2
        while os.path.exists(os.path.join(PROJ_DIR, pid + '.json')):
            pid = f'{base}-{i}'
            i += 1

    now = time.strftime('%Y-%m-%dT%H:%M:%S')
    prev = _read_doc(os.path.join(PROJ_DIR, pid + '.json')) or {}
    out = dict(doc)
    out['name'] = name
    out['id'] = pid
    out['units'] = doc.get('units') or 'm'
    out['created'] = prev.get('created') or doc.get('created') or now
    out['saved'] = now
    out['schema'] = 1

    body = json.dumps(out, separators=(',', ':'))
    if len(body.encode('utf-8')) > MAX_DOC_BYTES:
        return {'error': f'drawing is over the {MAX_DOC_BYTES // (1024 * 1024)} MB limit'}

    path = os.path.join(PROJ_DIR, pid + '.json')
    tmp = path + '.tmp'
    # Write-then-rename: a crash mid-save must not leave a half-written
    # drawing where a whole one used to be.
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write(body)
    os.replace(tmp, path)
    return {'ok': True, 'id': pid, 'name': name, 'saved': now, 'objects': len(objs)}


def delete_project(pid: str) -> dict:
    """Move a drawing to data/architecture/trash/. Never unlinks: a drawing is
    hand-made work and a mis-click must be recoverable."""
    _ensure_dirs()
    path = _proj_path(pid)
    if not os.path.exists(path):
        return {'error': 'no such drawing'}
    stamp = time.strftime('%Y%m%d-%H%M%S')
    os.replace(path, os.path.join(TRASH_DIR, f'{pid}.{stamp}.json'))
    return {'ok': True, 'id': pid, 'trashed': True}


def rename_project(pid: str, name: str) -> dict:
    path = _proj_path(pid)
    doc = _read_doc(path)
    if doc is None:
        return {'error': 'no such drawing'}
    name = str(name or '').strip()
    if not name:
        return {'error': 'a drawing needs a name'}
    doc['name'] = name
    doc['saved'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, separators=(',', ':'))
    os.replace(tmp, path)
    return {'ok': True, 'id': pid, 'name': name}


# ── server-side ops of the icon families (2026-09-07) ──────────────────────
# arch_server_ext/<family>.py exports ROUTES = {op: fn(payload: dict, method: str)}.
# fn returns a dict (sent as JSON; {'error':..., 'code':...} sets the status) or
# a tuple (bytes, mime, filename) that the server sends as a download. Modules
# are reloaded when their file changes, so a family lands without a restart.
_EXT_DIR = os.path.join(HERE, 'arch_server_ext')
_EXT_MODS: dict = {}
_EXT_NAME = re.compile(r'^[a-z0-9_]{1,48}$')


def ext_module(family: str):
    if not _EXT_NAME.match(family or ''):
        raise ValueError('bad family name')
    path = os.path.join(_EXT_DIR, family + '.py')
    if not os.path.isfile(path):
        return None
    mtime = os.path.getmtime(path)
    hit = _EXT_MODS.get(family)
    if hit and hit[0] == mtime:
        return hit[1]
    import importlib.util

    spec = importlib.util.spec_from_file_location('arch_server_ext.' + family, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _EXT_MODS[family] = (mtime, mod)
    return mod


def ext_families() -> dict:
    """{family: [ops]} for every arch_server_ext/*.py that imports."""
    out: dict = {}
    if not os.path.isdir(_EXT_DIR):
        return out
    for f in sorted(os.listdir(_EXT_DIR)):
        if not f.endswith('.py') or f.startswith('_'):
            continue
        fam = f[:-3]
        try:
            mod = ext_module(fam)
            out[fam] = sorted((getattr(mod, 'ROUTES', {}) or {}).keys())
        except Exception as e:  # noqa: BLE001
            out[fam] = ['ERROR: %s' % (str(e)[:120],)]
    return out


def ext_dispatch(method: str, rest: str, payload: dict):
    """'<family>/<op>' -> the op's result. Unknown family/op -> {'error', 'code': 404}."""
    parts = (rest or '').strip('/').split('/')
    if len(parts) == 1 and parts[0] == '':
        return {'ok': True, 'families': ext_families()}
    if len(parts) != 2:
        return {'error': 'use /ext/<family>/<op>', 'code': 404}
    fam, op = parts
    if not _EXT_NAME.match(fam) or not _EXT_NAME.match(op):
        return {'error': 'bad family or op name', 'code': 404}
    mod = ext_module(fam)
    if mod is None:
        return {'error': f'no server extension {fam}', 'code': 404}
    fn = (getattr(mod, 'ROUTES', {}) or {}).get(op)
    if fn is None:
        return {'error': f'{fam} has no op {op}', 'code': 404}
    return fn(payload if isinstance(payload, dict) else {}, method)
