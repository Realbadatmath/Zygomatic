# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""file_3d — the assistant half of the File ▸ 3D interchange family (2026-09-07).

Five icons cross the boundary of the tab with a FILE: f_glb and f_stl write one,
f_import and f_pc read one, f_link reads another drawing. The model cannot click
a file picker, so each tool here answers the same question a different way:

  * export_model  — a press. Only the tab holds the built meshes, so the export
    has to happen there; the icon downloads the file AND keeps a copy under
    data/architecture/exports/, which is the copy anything else can open.
  * import_mesh / link_drawing — real records. A `mesh_file` or a `link` record
    is nothing but PARAMETERS (an id and a scale; a project id), so the drawing
    tool can write them server-side and let the tab's async loader swap the real
    meshes in when the bytes land. That is one arithmetic, not two.

The ids import_mesh takes are the ones arch_server_ext.file_3d.upload minted —
the first 16 hex of the file's content hash, or a name given at upload time
(`sample`, `sample_cloud` ship with the family). An unknown id is refused with
the list of what this machine actually has, because guessing at a hash is not a
thing a model should be asked to do.

Standard library only. No new packages.
"""

from __future__ import annotations

from zyg_workflows.arch_assistant import Drawing, cell_centre, parse_cell, _num

# Parameters only, never geometry: an id says which bytes, a scale says how big,
# and everything else is the tab's business.
KINDS = {
    'mesh_file': {'id': 'sample', 'ext': 'glb', 'sx': 1, 'name': ''},
    'point_cloud': {'id': 'sample_cloud', 'ext': 'xyz', 'size': 0.03, 'n': 0},
    'link': {'pid': '', 'name': ''},
}
OPENINGS: list = []

BUTTONS = ['f_glb', 'f_stl', 'f_import', 'f_pc', 'f_link']

FORMATS = ('glb', 'gltf', 'stl')

PROMPT = (
    'File ▸ 3D interchange: export_model("glb"|"stl") exports everything VISIBLE — glTF for a web '
    'viewer or a game engine, binary STL in METRES for a 3D print — downloading it and keeping a '
    'copy under data/architecture/exports/. import_mesh(id, cell, scale) places an uploaded mesh '
    'file (.glb/.gltf/.obj/.stl) as ONE record of kind mesh_file: it draws a glass crate at once '
    'and swaps the real mesh in when the file has parsed. link_drawing(pid, cell) references '
    "another saved drawing as one record of kind link, rebuilt from that drawing's own parameters "
    '(press_button "f_link" with {"reload": true} to re-fetch it after it changed, or with no args '
    'to open the sheet of linkable drawings). A survey point cloud is the kind point_cloud, placed '
    'by press_button "f_pc" {id, cell, size}: up to two million points, vertex colours kept. '
    'The five icons take press_button args: f_glb {binary, name}, f_stl {name}, '
    'f_import {id|data_b64, name, cell, scale}, f_pc {id|data_b64, name, cell, size}, '
    'f_link {pid, cell} | {reload: true}. The ids "sample" (a small .glb) and "sample_cloud" '
    '(a 5,000-point .xyz) ship with the studio and are always there to demonstrate with.'
)


def _srv():
    """The server half, loaded the way the route dispatcher loads it — so the
    assistant and the tab agree about which files exist."""
    import importlib
    import os
    import sys

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if here not in sys.path:
        sys.path.insert(0, here)
    return importlib.import_module('zyg_workflows.arch_server_ext.file_3d')


def _press(d, bid, args=None):
    cmd = {'cmd': 'tool', 'args': {'id': bid}}
    if isinstance(args, dict) and args:
        cmd['args']['args'] = args
    d.ui.append(cmd)


def _credits(d, path: str = '') -> str:
    """The licence follows the file (2026-09-11).

    A drawing that has had real floor plans placed in it carries CC BY material,
    so every file it is exported into is a derivative that owes the attribution
    line. The line is written out beside the export: `<export>.credits.txt` for a
    file this process wrote, and `credits.txt` in the exports directory for a
    press, whose stamped name only the tab ever learns. Returns the tail to
    append to the reply, or ''.
    """
    if not (getattr(d, 'ext', None) or {}).get('attributions'):
        return ''
    try:
        import os
        from zyg_workflows import arch_assistant as A

        mod = (getattr(A, 'EXT_MODULES', None) or {}).get('floor_plans')
        text = (mod.credits_text(d) if mod else '') or ''
        if not text.strip():
            return ''
        out = (str(path) + '.credits.txt') if path else os.path.join(_srv().EXPORT_DIR, 'credits.txt')
        os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
        with open(out, 'w', encoding='utf-8') as f:
            f.write(text.rstrip('\n') + '\n')
    except Exception:  # noqa: BLE001 — credits never break an export
        return ''
    return ' + credits.txt'


def _at(cell):
    """A cell name -> the centre of that cell, or the origin when none is given."""
    c = str(cell or '').strip()
    if not c:
        return 0.0, 0.0
    return cell_centre(*parse_cell(c))


def _imports():
    try:
        return (_srv().list_({}, 'GET') or {}).get('imports') or []
    except Exception:  # noqa: BLE001
        return []


def _known(fid):
    """(path, ext) of an uploaded file, or (None, '')."""
    try:
        r = _srv().info({'id': fid}, 'GET') or {}
    except Exception:  # noqa: BLE001
        return None, ''
    if r.get('error'):
        return None, ''
    return r.get('path'), str(r.get('ext') or '')


def _id_help(want):
    have = [r['id'] for r in _imports() if str(r.get('name', '')).lower().endswith(want)]
    if not have:
        return 'nothing of that sort has been uploaded to this machine yet'
    return 'uploaded ids are: ' + ', '.join(sorted(set(have))[:20])


# ── the tools ────────────────────────────────────────────────────────────────


def t_export_model(d: Drawing, a, format='glb', name=''):
    fmt = str(format or 'glb').strip().lower().lstrip('.')
    if fmt not in FORMATS:
        return 'refused: format must be one of ' + '/'.join(FORMATS)
    args = {}
    if name:
        args['name'] = str(name).strip()[:60]
    if fmt == 'gltf':
        args['binary'] = False
    _press(d, 'f_stl' if fmt == 'stl' else 'f_glb', args)
    if fmt == 'stl':
        return (
            'exporting everything visible as a binary .stl in METRES (a slicer reads STL as '
            'millimetres by convention, so scale by 1000 for a full-size print) — it downloads '
            'and a copy is kept under data/architecture/exports/' + _credits(d)
        )
    return (
        f'exporting everything visible as .{"glb" if fmt == "glb" else "gltf"} — flattened '
        f"materials with the albedo map embedded, the drawing's own names on the objects — "
        f'it downloads and a copy is kept under data/architecture/exports/' + _credits(d)
    )


def t_import_mesh(d: Drawing, a, id='', cell='', scale=1.0, name=''):
    fid = str(id or '').strip().lower()
    if not fid:
        return 'refused: import_mesh needs the id of an uploaded file — ' + _id_help('.glb')
    path, ext = _known(fid)
    if path is None:
        return f'refused: no uploaded file with id "{fid[:40]}" — ' + _id_help('.glb')
    if ext not in ('glb', 'gltf', 'obj', 'stl'):
        return (
            f'refused: "{fid}" is a .{ext} — import_mesh takes a mesh (.glb, .gltf, .obj or '
            f'.stl); a point cloud goes in through press_button "f_pc"'
        )
    try:
        x, z = _at(cell)
    except ValueError as e:
        return f'refused: {e}'
    s = _num(scale, 1.0)
    if not (0.001 <= s <= 1000):
        return 'refused: scale must be between 0.001 and 1000'
    rec = d.new(
        'mesh_file',
        {'id': fid, 'ext': ext, 'sx': round(s, 4), 'name': str(name or fid).strip()[:60]},
        x,
        z,
        0.0,
        name=str(name or 'Imported mesh').strip()[:60] or 'Imported mesh',
    )
    d.selected = [rec['id']]
    where = f' at {cell}' if cell else ' at the origin'
    return (
        f'placed {fid}.{ext} as one mesh_file record {rec["id"]}{where}'
        + (f', scaled ×{s:g}' if s != 1 else '')
        + ' — the tab shows a glass crate until the file has parsed, then the real mesh'
    )


def t_link_drawing(d: Drawing, a, pid='', cell='', name=''):
    p = str(pid or '').strip()
    if not p:
        return 'refused: link_drawing needs the id of a saved drawing (list_drawings shows them)'
    try:
        from zyg_workflows import architecture_studio as st

        doc = st.load_project(p)
    except Exception as e:  # noqa: BLE001
        return f'could not read the drawing "{p[:40]}": {e}'
    if not isinstance(doc, dict) or doc.get('error') or not doc.get('doc'):
        return f'refused: no saved drawing with id "{p[:40]}"'
    linked = doc['doc']
    try:
        x, z = _at(cell)
    except ValueError as e:
        return f'refused: {e}'
    nm = str(name or linked.get('name') or p).strip()[:60]
    rec = d.new('link', {'pid': p, 'name': nm}, x, z, 0.0, name=('Link: ' + nm)[:60])
    d.selected = [rec['id']]
    n = len(linked.get('objects') or [])
    where = f' at {cell}' if cell else ' at the origin'
    return (
        f'linked the drawing "{nm}" ({p}) as one reference record {rec["id"]}{where} — its '
        f'{n} object' + ('' if n == 1 else 's') + " are rebuilt from that drawing's own "
        'parameters, so press_button "f_link" {"reload": true} shows it again after it changes'
    )


TOOLS = [
    (
        {
            'name': 'export_model',
            'description': 'Export everything VISIBLE in the drawing as a 3D file: "glb" (or "gltf") for a web viewer, a game engine or another modeller, "stl" for a 3D print. The file downloads and a copy is kept on the server under data/architecture/exports/. Use it when the user asks for a glTF/GLB/STL, a printable model, or a file to hand to someone else.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'format': {'type': 'string', 'enum': list(FORMATS), 'description': 'glb (default), gltf or stl'},
                    'name': {'type': 'string', 'description': 'base file name; defaults to the drawing name'},
                },
                'required': [],
            },
        },
        t_export_model,
    ),
    (
        {
            'name': 'import_mesh',
            'description': 'Place an already-uploaded mesh file (.glb, .gltf, .obj or .stl) into the drawing as ONE block, for a piece of context that will not be modelled. Takes the file id minted when it was uploaded ("sample" is a small model that always exists). Use it when the user says "drop that model in" or names a file they have imported.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'id': {'type': 'string', 'description': 'the uploaded file id'},
                    'cell': {'type': 'string', 'description': 'grid cell like C4; defaults to the origin'},
                    'scale': {'type': 'number', 'description': 'scale factor, default 1'},
                    'name': {'type': 'string'},
                },
                'required': ['id'],
            },
        },
        t_import_mesh,
    ),
    (
        {
            'name': 'link_drawing',
            'description': "Reference another saved drawing into this one as a single record, rebuilt from that drawing's own parameters rather than copied. Use it for a site context model, a neighbouring block or a shared core that someone else owns. Takes the saved drawing id.",
            'input_schema': {
                'type': 'object',
                'properties': {
                    'pid': {'type': 'string', 'description': 'the saved drawing id'},
                    'cell': {'type': 'string', 'description': 'grid cell like C4; defaults to the origin'},
                    'name': {'type': 'string'},
                },
                'required': ['pid'],
            },
        },
        t_link_drawing,
    ),
]

EXAMPLES = [
    {
        'ask': 'give me a glb of this so I can put it on the website',
        'calls': [{'tool': 'export_model', 'args': {'format': 'glb'}}],
    },
    {'ask': 'I want to 3D print the massing', 'calls': [{'tool': 'export_model', 'args': {'format': 'stl'}}]},
    {
        'ask': 'drop the sample model into C4 at half size',
        'calls': [{'tool': 'import_mesh', 'args': {'id': 'sample', 'cell': 'C4', 'scale': 0.5}}],
    },
    {
        'ask': 'bring the survey cloud in',
        'calls': [{'tool': 'press_button', 'args': {'id': 'f_pc', 'args': {'id': 'sample_cloud', 'size': 0.04}}}],
    },
    {
        'ask': 'reference the site context drawing next to this one',
        'calls': [{'tool': 'link_drawing', 'args': {'pid': 'site-context', 'cell': 'D5'}}],
    },
    {
        'ask': 'the linked drawing changed, show me the new version',
        'calls': [{'tool': 'press_button', 'args': {'id': 'f_link', 'args': {'reload': True}}}],
    },
    {
        'ask': 'let me pick a mesh off my disk to import',
        'calls': [{'tool': 'press_button', 'args': {'id': 'f_import'}}],
    },
]
