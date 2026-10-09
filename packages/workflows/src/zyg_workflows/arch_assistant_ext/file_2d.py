# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""file_2d — the assistant half of the File ▸ 2D/BIM export family (2026-09-08).

Three icons take the drawing OUT of the studio in a format somebody else's
software reads: f_dxf (a CAD plan or a triangulated solid), f_svg (the 2D
drawings sheet as a vector file) and f_ifc (a BIM model, written by Blender).

Two of those exports can only happen in the tab, because only the tab holds
the built geometry: the DXF's plan footprints come from the same arithmetic
the 2D drawings use, and the SVG IS the drawings sheet. So `export_drawing`
is a press — it returns the press_button args and lets the icon do the work,
downloading the file and keeping a copy under data/architecture/exports/.

The IFC is the other way round. It is written by a headless Blender that
builds the scene from the document JSON, so the assistant can call the server
route directly with `d.to_doc()` and hand back the path and the element counts
without the tab being involved at all. That is why `export_ifc` is a real
function and not a press: the answer is a fact about a file on disk, and a
model that has just been asked for a BIM model should be able to say how many
walls came out of it.

Standard library only. No new packages.
"""

from __future__ import annotations

from zyg_workflows.arch_assistant import Drawing

# This family adds no record kinds and no openings: it reads the drawing and
# writes a file, it never draws anything.
KINDS: dict = {}
OPENINGS: list = []

BUTTONS = ['f_dxf', 'f_svg', 'f_ifc']

FORMATS = ('dxf', 'svg', 'ifc')
SCHEMAS = ('IFC4', 'IFC2X3', 'IFC4X3')
DXF_WHAT = ('plan', '3d')
SVG_KINDS = ('plan', 'elevation', 'section')

PROMPT = (
    'File - 2D/BIM export: export_drawing("dxf"|"svg"|"ifc", what) writes the drawing out. "dxf" what="plan" is '
    'an AutoCAD R2000 plan, one layer per kind; what="3d" is every visible mesh as 3DFACEs; "svg" is the 2D '
    'sheet; "ifc" runs Blender for IFC4 — walls as IfcWall, each in its IfcBuildingStorey, in metres, and '
    'export_ifc() does that one from here in ~10 s. Everything keeps a copy under data/architecture/exports/. '
    'Icons f_dxf, f_svg, f_ifc. explain("file export") has the detail.'
)


def _srv():
    """The server half, loaded the way the route dispatcher loads it — so the
    assistant and the tab write into the same exports directory."""
    import importlib
    import os
    import sys

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if here not in sys.path:
        sys.path.insert(0, here)
    return importlib.import_module('zyg_workflows.arch_server_ext.file_2d')


def _press(d, bid, args=None):
    cmd = {'cmd': 'tool', 'args': {'id': bid}}
    if isinstance(args, dict) and args:
        cmd['args']['args'] = args
    d.ui.append(cmd)


def _credits(d, path: str = '') -> str:
    """The licence follows the file (2026-09-11).

    A drawing that has had real floor plans placed in it carries CC BY material,
    so every file it is exported into is a derivative that owes the attribution
    line. Rather than trust a credits panel nobody opens, the line is written out
    beside the export: `<export>.credits.txt` for a file this process wrote, and
    `credits.txt` in the exports directory for a press, whose stamped name only
    the tab ever learns. Returns the tail to append to the reply, or ''.
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


def _storey(v):
    """A storey number, or None for 'every level'. 0 is a real answer."""
    if v is None or v == '':
        return None
    try:
        return int(round(float(v)))
    except (TypeError, ValueError) as _exc:
        raise ValueError('storey must be a whole number (0 is the ground floor)') from _exc


# ── the tools ────────────────────────────────────────────────────────────────


def t_export_drawing(d: Drawing, a, format='dxf', what='plan', storey=None):
    fmt = str(format or 'dxf').strip().lower().lstrip('.')
    if fmt not in FORMATS:
        return 'refused: format must be one of ' + '/'.join(FORMATS)
    try:
        st = _storey(storey)
    except ValueError as e:
        return f'refused: {e}'
    w = str(what or '').strip().lower()

    if fmt == 'ifc':
        # The IFC needs no press — but say so rather than silently doing
        # something else, so the model learns which tool owns it.
        return t_export_ifc(d, a)

    if fmt == 'svg':
        kind = w if w in SVG_KINDS else 'plan'
        args = {'kind': kind}
        if st is not None:
            args['storey'] = st
        _press(d, 'f_svg', args)
        where = f' of level {st}' if st is not None else ''
        return (
            f'saving the {kind}{where} as a vector .svg — it downloads, a copy is kept under '
            f'data/architecture/exports/, and the sheet offers it on the clipboard' + _credits(d)
        )

    if w not in DXF_WHAT:
        w = 'plan'
    args = {'what': w}
    if st is not None:
        args['storey'] = st
    _press(d, 'f_dxf', args)
    if w == '3d':
        return (
            'exporting every visible mesh as 3DFACE triangles in one AutoCAD R2000 .dxf, '
            'in metres, one layer per kind — it downloads and a copy is kept under '
            'data/architecture/exports/' + _credits(d)
        )
    where = f' of level {st}' if st is not None else ''
    return (
        f'exporting the plan{where} as an AutoCAD R2000 .dxf — footprints as closed polylines '
        f'on a layer per kind, openings, guides and dimensions each on their own — it downloads '
        f'and a copy is kept under data/architecture/exports/' + _credits(d)
    )


def t_export_ifc(d: Drawing, a, schema='IFC4', name=''):
    sch = str(schema or 'IFC4').strip().upper()
    if sch not in SCHEMAS:
        return 'refused: schema must be one of ' + '/'.join(SCHEMAS)
    doc = d.to_doc()
    if not (doc.get('objects') or []):
        return 'refused: the drawing is empty — there is nothing to put in an IFC model'
    try:
        r = _srv().ifc({'doc': doc, 'schema': sch, 'name': str(name or d.name or 'Drawing').strip()[:80]}, 'POST')
    except Exception as e:  # noqa: BLE001
        return f'the IFC export failed: {type(e).__name__}: {e}'
    if not isinstance(r, dict) or r.get('error') or not r.get('ok'):
        err = (r or {}).get('error') if isinstance(r, dict) else 'no answer'
        return f'the IFC export failed: {err}'
    by = r.get('by_class') or {}
    counts = ', '.join(f'{n}× {c}' for c, n in sorted(by.items(), key=lambda kv: -kv[1])) or 'nothing'
    skipped = int(r.get('skipped') or 0)
    tail = ''
    if skipped:
        tail = (
            f' ({skipped} guide/annotation record{"" if skipped == 1 else "s"} left out — '
            f'they are notation, not building)'
        )
    return (
        f'wrote {r.get("elements", 0)} {sch} elements across {r.get("storeys", 0)} storey'
        + ('' if r.get('storeys') == 1 else 's')
        + f' to {r.get("rel") or r.get("path")} ({int(r.get("bytes") or 0):,} bytes): {counts}'
        + tail
        + _credits(d, str(r.get('path') or ''))
        + ' — press_button "f_ifc" downloads it in the browser'
    )


TOOLS = [
    (
        {
            'name': 'export_drawing',
            'description': 'Export the drawing as a file another program reads: "dxf" for AutoCAD/CAD (what="plan" for a layered 2D plan, what="3d" for triangulated solids), "svg" for the 2D drawings sheet as vector art (what="plan", "elevation" or "section"), "ifc" for a BIM model. The file downloads and a copy is kept on the server under data/architecture/exports/. Use it when the user asks for a DXF, a CAD file, an SVG, a drawing to send someone, or something to open in AutoCAD/Illustrator.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'format': {'type': 'string', 'enum': list(FORMATS), 'description': 'dxf (default), svg or ifc'},
                    'what': {
                        'type': 'string',
                        'description': 'for dxf: "plan" (default) or "3d"; for svg: "plan", "elevation" or "section"',
                    },
                    'storey': {
                        'type': 'number',
                        'description': 'export only this level (0 is the ground floor); omit for every level',
                    },
                },
                'required': [],
            },
        },
        t_export_drawing,
    ),
    (
        {
            'name': 'export_ifc',
            'description': 'Write the drawing as an IFC BIM model (IFC4 by default) and report where it went. Runs Blender headlessly to build the real geometry, then types every object by what it is — walls become IfcWall, slabs IfcSlab, columns IfcColumn, roofs IfcRoof — and files each one in the IfcBuildingStorey its height puts it in, in metres. Takes roughly ten seconds. Use it when the user asks for IFC, BIM, a Revit/ArchiCAD/Solibri file, or a model for a consultant or a clash check.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'schema': {
                        'type': 'string',
                        'enum': list(SCHEMAS),
                        'description': 'IFC4 (default), IFC2X3 for older software, or IFC4X3',
                    },
                    'name': {
                        'type': 'string',
                        'description': 'project name inside the file; defaults to the drawing name',
                    },
                },
                'required': [],
            },
        },
        t_export_ifc,
    ),
]

EXAMPLES = [
    {
        'ask': 'give me a dxf of the plan',
        'calls': [{'tool': 'export_drawing', 'args': {'format': 'dxf', 'what': 'plan'}}],
    },
    {
        'ask': 'export the ground floor only as CAD',
        'calls': [{'tool': 'export_drawing', 'args': {'format': 'dxf', 'what': 'plan', 'storey': 0}}],
    },
    {
        'ask': 'I need the solids in dxf for the engineer',
        'calls': [{'tool': 'export_drawing', 'args': {'format': 'dxf', 'what': '3d'}}],
    },
    {
        'ask': 'save the section as an svg',
        'calls': [{'tool': 'export_drawing', 'args': {'format': 'svg', 'what': 'section'}}],
    },
    {'ask': 'send this to the BIM consultant', 'calls': [{'tool': 'export_ifc', 'args': {}}]},
    {
        'ask': 'their software is old, can you do IFC2X3',
        'calls': [{'tool': 'export_ifc', 'args': {'schema': 'IFC2X3'}}],
    },
    {'ask': 'download the ifc in the browser', 'calls': [{'tool': 'press_button', 'args': {'id': 'f_ifc'}}]},
]
