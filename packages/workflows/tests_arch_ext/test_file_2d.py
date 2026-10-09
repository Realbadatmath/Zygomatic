# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_file_2d.py — the proof that File ▸ 2D/BIM export is real.

Three icons that were placeholders (f_dxf, f_svg, f_ifc), each checked twice:
the live DOM says the placeholder mark is gone, and the thing the tooltip
promises actually happened — to a file, opened again by a different program.

  f_dxf   the tab writes the DXF text itself; the server copy is then READ BACK
          BY EZDXF, which is the only opinion that matters: the layer of every
          entity, the metre unit in the header, the wall count in a plan and the
          3DFACE count in a solid export. Then BLENDER imports that same file.
  f_svg   the drawings_2d sheet, saved as a real .svg that xml.etree parses.
  f_ifc   Blender builds the model and ifcopenshell writes it; a SECOND Blender
          run opens the file cold and counts the IfcWalls.

Where the libraries come from. ezdxf 1.4.4 and ifcopenshell 0.8.5 are not in the
GUI venv and nothing here installs them: both already ship inside Blender's own
Python (ifcopenshell with the Bonsai extension). So every read-back happens in a
Blender subprocess — one run for all four questions, not four runs.

Three browser_eval calls (one of them icon_state) and four Blender runs.
"""

import json
import os
import subprocess
import sys
import tempfile

from defusedxml import ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import (
    BLENDER,
    _BlenderLock,
    assistant,
    browser_eval,  # noqa: E402
    check,
    finish,
    icon_state,
    server_ext,
    tool_names,
)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS = os.path.join(HERE, 'data', 'architecture', 'exports')
IDS = ['f_dxf', 'f_svg', 'f_ifc']

# ── 1. the icons are no longer placeholders ──────────────────────────────────
st = icon_state(IDS)
check(
    'all three icons exist, with no stub flag, no dashed class and no [placeholder] tooltip',
    all(
        st.get(i, {}).get('exists')
        and not st[i].get('stub')
        and not st[i].get('dashed')
        and not st[i].get('tip_placeholder')
        for i in IDS
    ),
    st,
)

# ── 2. f_dxf and f_svg, in the tab, on a drawing with something of everything ─
# two storeys (so a storey filter has something to filter), a wall with two
# openings cut in it, a rotated wall, a guide and a dimension.
r = browser_eval(
    """async () => {
  arNewObj('slab', {w:8, d:6, t:0.3}, 0, 0, 0);
  arNewObj('wall', {len:8, h:2.7, t:0.24,
                    holes:[{u:2, w:0.9, h:2.1, sill:0}, {u:5, w:1.2, h:1.2, sill:0.9}]}, 0, -3, 0);
  const w2 = arNewObj('wall', {len:6, h:2.7, t:0.24}, 4, 0, 0);
  w2.ry = Math.PI/2; arRebuild(w2);
  arNewObj('column_rect', {w:0.3, d:0.3, h:2.7}, 2, 2, 0);
  arNewObj('slab', {w:8, d:6, t:0.3}, 0, 0, 2.7);          /* level 1 */
  arNewObj('guide_arc', {x1:0, z1:0, x2:-3, z2:-3, x3:-0.8787, z3:-2.1213}, -5, 4, 0);
  arNewObj('dim_linear', {x2:8, z2:0, off:0.8, txt:''}, 0, -4.5, 0);

  arTool('f_dxf', {what:'plan', name:'f2dproof'});
  const plan = await AR_EXT.tools.f_dxf._pending;
  arTool('f_dxf', {what:'plan', storey:0, name:'f2dproof'});
  const lvl0 = await AR_EXT.tools.f_dxf._pending;
  arTool('f_dxf', {what:'3d', name:'f2dproof'});
  const solid = await AR_EXT.tools.f_dxf._pending;
  const dxfToast = document.getElementById('ar-toast').innerHTML;

  arTool('f_svg', {kind:'plan', storey:0, name:'f2dproof'});
  const svg = await AR_EXT.tools.f_svg._pending;
  const sheet = document.getElementById('ar-sheet');
  return {plan: plan, lvl0: lvl0, solid: solid, svg: svg,
          objs: AR.objs.length, undo: (AR.undo||[]).length,
          dxfToast: dxfToast,
          sheet: sheet ? (sheet.textContent || '').slice(0, 600) : '',
          copyBtn: /file2dCopySvg/.test(sheet ? sheet.innerHTML : '')};
}""",
    doc={'objects': []},
)
v = r['value'] or {}
plan, lvl0, solid, svg = (v.get('plan') or {}), (v.get('lvl0') or {}), (v.get('solid') or {}), (v.get('svg') or {})
PLAN_PATH = ((plan.get('save') or {}).get('path')) or ''
SOLID_PATH = ((solid.get('save') or {}).get('path')) or ''
SVG_PATH = svg.get('path') or ''
ps, ls, ss = (plan.get('stats') or {}), (lvl0.get('stats') or {}), (solid.get('stats') or {})

check('no page errors while exporting', not r['errors'], r['errors'])
check(
    'f_dxf {what:"plan"} wrote a .dxf the server kept, covering every kind in the drawing',
    plan.get('ok')
    and PLAN_PATH.endswith('.dxf')
    and os.path.isfile(PLAN_PATH)
    and ps.get('walls') == 2
    and ps.get('openings') == 2
    and ps.get('guides') == 1
    and ps.get('annot') == 1
    and ps.get('records') == 7,
    {'plan': plan, 'errors': r['errors']},
)
check(
    'f_dxf {storey:0} exports only the ground floor — the level-1 slab is left out',
    lvl0.get('ok')
    and ls.get('records') == 6
    and ls.get('skipped') == 1
    and ls.get('entities', 0) < ps.get('entities', 0),
    {'level0': ls, 'all': ps},
)
check(
    'f_dxf {what:"3d"} wrote every visible solid as triangles (guides and dimensions excluded)',
    solid.get('ok')
    and SOLID_PATH.endswith('.dxf')
    and os.path.isfile(SOLID_PATH)
    and ss.get('records') == 5
    and ss.get('tris', 0) > 100
    and not ss.get('capped'),
    {'solid': solid},
)
check(
    'the DXF toast names the format, what came out and the server copy',
    'R2000' in (v.get('dxfToast') or '') and 'exports/' in (v.get('dxfToast') or ''),
    (v.get('dxfToast') or '')[-260:],
)
check(
    'f_svg saved the plan as a real .svg file, downloaded and copied to the server',
    svg.get('ok')
    and svg.get('kind') == 'plan'
    and SVG_PATH.endswith('.svg')
    and os.path.isfile(SVG_PATH)
    and svg.get('chars', 0) > 500,
    {'svg': svg},
)
check(
    'the f_svg sheet shows the scale, the sheet size and where the file went, with a clipboard button',
    v.get('copyBtn') and 'server copy' in (v.get('sheet') or '') and 'Copy SVG to clipboard' in (v.get('sheet') or ''),
    (v.get('sheet') or '')[:300],
)
check(
    'exporting is read-only — seven records went in, seven came out and nothing was pushed onto undo',
    v.get('objs') == 7 and not v.get('undo'),
    {'objs': v.get('objs'), 'undo': v.get('undo')},
)

# ── 3. the SVG the tab saved, parsed by something that is not a browser ──────
if SVG_PATH and os.path.isfile(SVG_PATH):
    root = ET.parse(SVG_PATH).getroot()
    n_el = sum(1 for _ in root.iter())
    check(
        'the saved .svg parses as XML, is an <svg> and holds more than ten elements',
        root.tag.endswith('svg') and n_el > 10,
        {'root': root.tag, 'elements': n_el},
    )
else:
    check('the saved .svg parses as XML, is an <svg> and holds more than ten elements', False, SVG_PATH)

# ── 4. f_ifc, pressed in the tab, on the same drawing ───────────────────────
r2 = browser_eval(
    """async () => {
  arNewObj('slab', {w:8, d:6, t:0.3}, 0, 0, 0);
  arNewObj('wall', {len:8, h:2.7, t:0.24}, 0, -3, 0);
  const w2 = arNewObj('wall', {len:6, h:2.7, t:0.24}, 4, 0, 0);
  w2.ry = Math.PI/2; arRebuild(w2);
  arNewObj('column_rect', {w:0.3, d:0.3, h:2.7}, 2, 2, 0);
  arNewObj('slab', {w:8, d:6, t:0.3}, 0, 0, 2.7);
  arNewObj('dim_linear', {x2:8, z2:0, off:0.8, txt:''}, 0, -4.5, 0);
  arTool('f_ifc', {schema:'IFC4'});
  const ifc = await AR_EXT.tools.f_ifc._pending;
  return {ifc: ifc, toast: document.getElementById('ar-toast').innerHTML, objs: AR.objs.length};
}""",
    doc={'objects': []},
    timeout_s=300,
)
v2 = r2['value'] or {}
tab_ifc = v2.get('ifc') or {}
check(
    'f_ifc built the drawing in Blender and wrote an IFC4 file under exports/',
    tab_ifc.get('ok')
    and tab_ifc.get('schema') == 'IFC4'
    and tab_ifc.get('elements', 0) >= 5
    and str(tab_ifc.get('rel') or '').startswith('data/architecture/exports/')
    and os.path.isfile(tab_ifc.get('path') or ''),
    {'ifc': tab_ifc, 'errors': r2['errors']},
)
check(
    'f_ifc typed the objects by what they are — walls, slabs and a column, not one proxy heap',
    (tab_ifc.get('by_class') or {}).get('IfcWall') == 2
    and (tab_ifc.get('by_class') or {}).get('IfcSlab') == 2
    and (tab_ifc.get('by_class') or {}).get('IfcColumn') == 1
    and tab_ifc.get('storeys') == 2,
    tab_ifc.get('by_class'),
)
check(
    'f_ifc leaves notation out of the building model — the dimension is not an element',
    tab_ifc.get('skipped') == 1,
    tab_ifc,
)
check(
    'the IFC toast reports the element count, the classes and the path',
    'IfcWall' in (v2.get('toast') or '') and 'exports/' in (v2.get('toast') or ''),
    (v2.get('toast') or '')[-300:],
)
check('no page errors while exporting IFC', not r2['errors'], r2['errors'])

# ── 5. the ifc route over HTTP, on a five-record drawing of its own ─────────
FIVE = {
    'name': 'file_2d five',
    'units': 'm',
    'objects': [
        {
            'id': 'o1',
            'kind': 'slab',
            'name': 'Ground slab',
            'p': {'w': 6, 'd': 4, 't': 0.3},
            'x': 0,
            'y': 0,
            'z': 0,
            'ry': 0,
            's': 1,
            'mat': 'mat_concrete',
            'hidden': False,
        },
        {
            'id': 'o2',
            'kind': 'wall',
            'name': 'North wall',
            'p': {'len': 6, 'h': 2.7, 't': 0.24},
            'x': 0,
            'y': 0,
            'z': -2,
            'ry': 0,
            's': 1,
            'mat': 'mat_brick',
            'hidden': False,
        },
        {
            'id': 'o3',
            'kind': 'wall',
            'name': 'East wall',
            'p': {'len': 4, 'h': 2.7, 't': 0.24},
            'x': 3,
            'y': 0,
            'z': 0,
            'ry': 1.5707963,
            's': 1,
            'mat': 'mat_brick',
            'hidden': False,
        },
        {
            'id': 'o4',
            'kind': 'column_rect',
            'name': 'Post',
            'p': {'w': 0.3, 'd': 0.3, 'h': 2.7},
            'x': 2,
            'y': 0,
            'z': 1,
            'ry': 0,
            's': 1,
            'mat': 'mat_concrete',
            'hidden': False,
        },
        {
            'id': 'o5',
            'kind': 'slab',
            'name': 'Upper slab',
            'p': {'w': 6, 'd': 4, 't': 0.3},
            'x': 0,
            'y': 2.7,
            'z': 0,
            'ry': 0,
            's': 1,
            'mat': 'mat_concrete',
            'hidden': False,
        },
    ],
}
srv = server_ext('file_2d', 'ifc', {'doc': FIVE, 'name': 'file_2d five', 'schema': 'IFC4'}, timeout_s=300)
IFC_PATH = srv.get('path') or ''
check(
    'the ifc route turns a five-record drawing into five IFC elements on two storeys',
    srv.get('ok')
    and srv.get('elements') == 5
    and srv.get('storeys') == 2
    and srv.get('bytes', 0) > 1000
    and os.path.isfile(IFC_PATH),
    srv,
)

# ── 6. one Blender run: ezdxf reads both DXFs, Blender imports one, ─────────
#     and ifcopenshell opens the IFC cold.
VERIFY = r"""
import collections, json, sys
args = sys.argv[sys.argv.index('--') + 1:]
plan_p, solid_p, ifc_p = args[0], args[1], args[2]
out = {}
import ezdxf
d = ezdxf.readfile(plan_p)
out['ezdxf'] = ezdxf.__version__
out['plan_ver'] = d.dxfversion
out['plan_units'] = d.header.get('$INSUNITS')
out['plan'] = {'%s|%s' % k: n for k, n in
               collections.Counter((e.dxftype(), e.dxf.layer) for e in d.modelspace()).items()}
out['plan_layers'] = sorted(l.dxf.name for l in d.layers)
s = ezdxf.readfile(solid_p)
out['solid'] = {'%s|%s' % k: n for k, n in
                collections.Counter((e.dxftype(), e.dxf.layer) for e in s.modelspace()).items()}
import bpy
out['import_ops'] = [o for o in dir(bpy.ops.import_scene) if 'dxf' in o]
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
try:
    bpy.ops.import_scene.cad2cube_dxf(filepath=plan_p)
    out['blender_objs'] = len(bpy.data.objects)
except Exception as e:
    out['blender_err'] = repr(e)[:200]
import ifcopenshell
f = ifcopenshell.open(ifc_p)
out['ifc'] = {'schema': f.schema,
              'walls': len(f.by_type('IfcWall')), 'slabs': len(f.by_type('IfcSlab')),
              'columns': len(f.by_type('IfcColumn')),
              'storeys': len(f.by_type('IfcBuildingStorey')),
              'units': [u.Name for u in f.by_type('IfcSIUnit')],
              'wall_names': sorted(str(w.Name) for w in f.by_type('IfcWall'))}
print('F2DVER ' + json.dumps(out), flush=True)
"""
ver = {}
if PLAN_PATH and SOLID_PATH and IFC_PATH:
    fd, vp = tempfile.mkstemp(suffix='_f2dverify.py')
    with os.fdopen(fd, 'w') as fh:
        fh.write(VERIFY)
    with _BlenderLock():
        p = subprocess.run(
            [BLENDER, '-b', '--python', vp, '--', PLAN_PATH, SOLID_PATH, IFC_PATH],
            capture_output=True,
            text=True,
            timeout=420,
        )
    os.unlink(vp)
    for ln in (p.stdout or '').splitlines():
        if ln.startswith('F2DVER '):
            ver = json.loads(ln[7:])
    if not ver:
        print('  (verify run said: %s)' % ((p.stderr or p.stdout or '')[-400:],), flush=True)

pl = ver.get('plan') or {}
check(
    'ezdxf reads the plan back as R2000 with $INSUNITS 6 (metres) and every layer declared',
    ver.get('plan_ver') == 'AC1015'
    and ver.get('plan_units') == 6
    and {'WALL', 'SLAB', 'COLUMN', 'OPENING', 'ROOF', 'GUIDE', 'ANNOT', 'OTHER'} <= set(ver.get('plan_layers') or []),
    {'ver': ver.get('plan_ver'), 'units': ver.get('plan_units'), 'layers': ver.get('plan_layers')},
)
check(
    'ezdxf finds every entity on the layer its kind belongs to — 2 walls, 2 openings, 2 slabs, '
    '1 column, 1 guide arc and a dimension drawn as lines and text',
    pl.get('LWPOLYLINE|WALL') == 2
    and pl.get('LWPOLYLINE|OPENING') == 2
    and pl.get('LWPOLYLINE|SLAB') == 2
    and pl.get('LWPOLYLINE|COLUMN') == 1
    and pl.get('ARC|GUIDE') == 1
    and pl.get('LINE|ANNOT') == 3
    and pl.get('TEXT|ANNOT') == 1,
    pl,
)
sol = ver.get('solid') or {}
check(
    "the 3D export is exactly the triangles the tab counted, as 3DFACE, on the kinds' own layers",
    sum(sol.values()) == ss.get('tris')
    and sum(n for k, n in sol.items() if k.startswith('3DFACE|')) == ss.get('tris')
    and {'3DFACE|WALL', '3DFACE|SLAB', '3DFACE|COLUMN'} <= set(sol),
    {'solid': sol, 'tab_tris': ss.get('tris')},
)
check(
    'Blender imports the DXF the tab wrote and gets objects out of it',
    ver.get('blender_objs', 0) > 0,
    {'objs': ver.get('blender_objs'), 'err': ver.get('blender_err'), 'ops': ver.get('import_ops')},
)
ifc_r = ver.get('ifc') or {}
check(
    'ifcopenshell opens the exported .ifc cold and finds the walls, slabs, column and storeys',
    ifc_r.get('schema') == 'IFC4'
    and ifc_r.get('walls') == 2
    and ifc_r.get('slabs') == 2
    and ifc_r.get('columns') == 1
    and ifc_r.get('storeys') == 2,
    ifc_r,
)
check(
    "the model is in metres and keeps the studio's own names on the walls",
    'METRE' in (ifc_r.get('units') or []) and ifc_r.get('wall_names') == ['East wall', 'North wall'],
    ifc_r,
)

# ── 7. the routes on their own: the fences ─────────────────────────────────
bad = server_ext('file_2d', 'save', {'name': 'x', 'ext': 'exe', 'text': 'MZ'})
check(
    'save fences the extension to dxf/svg/ifc', bad.get('code') == 400 and 'ext must be' in str(bad.get('error')), bad
)
empty = server_ext('file_2d', 'save', {'name': 'x', 'ext': 'dxf'})
check('save refuses a payload with no bytes in it', empty.get('code') == 400, empty)
out_of = server_ext('file_2d', 'file', {'path': '/etc/passwd'}, method='GET')
check(
    'the file route is fenced to the exports directory, so a path outside it is a 404',
    out_of.get('code') == 404,
    out_of,
)
climb = server_ext(
    'file_2d', 'file', {'path': os.path.join(EXPORTS, '..', '..', '..', 'kanban_server.py')}, method='GET'
)
check('.. cannot climb out of the exports directory either', climb.get('code') == 404, climb)
got = server_ext('file_2d', 'file', {'path': IFC_PATH}, method='GET')
check(
    'the file route serves the .ifc bytes back for the tab to download',
    isinstance(got.get('bytes'), bytes)
    and got['bytes'].startswith(b'ISO-10303-21')
    and got.get('mime') == 'application/x-step',
    {k: v for k, v in got.items() if k != 'bytes'},
)
lst = server_ext('file_2d', 'list', {}, method='GET')
names = [e['name'] for e in (lst.get('exports') or [])]
check(
    'the list route sees the dxf, svg and ifc this test just made',
    lst.get('ok')
    and any(n.endswith('.dxf') for n in names)
    and any(n.endswith('.svg') for n in names)
    and os.path.basename(IFC_PATH) in names,
    names[:6],
)
no_doc = server_ext('file_2d', 'ifc', {'doc': {'objects': []}})
check(
    'the ifc route refuses an empty drawing rather than running Blender for nothing', no_doc.get('code') == 400, no_doc
)
bad_schema = server_ext('file_2d', 'ifc', {'doc': FIVE, 'schema': 'IFC9'})
check(
    'the ifc route refuses a schema that does not exist',
    bad_schema.get('code') == 400 and 'schema must be' in str(bad_schema.get('error')),
    bad_schema,
)

# ── 8. the assistant twins ────────────────────────────────────────────────
check(
    'both twins are registered as assistant tools',
    all(t in tool_names() for t in ('export_drawing', 'export_ifc')),
    tool_names()[-8:],
)
txt, d = assistant('export_drawing', {'format': 'dxf', 'what': 'plan', 'storey': 0})
check(
    'export_drawing("dxf") presses f_dxf with the arguments it was given',
    d.ui
    and d.ui[-1]['args']['id'] == 'f_dxf'
    and d.ui[-1]['args']['args'] == {'what': 'plan', 'storey': 0}
    and 'AutoCAD' in txt,
    (txt, d.ui),
)
txt2, d2 = assistant('export_drawing', {'format': 'dxf', 'what': '3d'})
check(
    'export_drawing("dxf", "3d") asks for the triangles instead of the footprints',
    d2.ui[-1]['args']['args'] == {'what': '3d'} and '3DFACE' in txt2,
    (txt2, d2.ui),
)
txt3, d3 = assistant('export_drawing', {'format': 'svg', 'what': 'section'})
check(
    'export_drawing("svg") presses f_svg for the drawing that was asked for',
    d3.ui[-1]['args']['id'] == 'f_svg' and d3.ui[-1]['args']['args']['kind'] == 'section',
    (txt3, d3.ui),
)
txt4, _ = assistant('export_drawing', {'format': 'pdf'})
check(
    'export_drawing refuses a format this family cannot write, and names the ones it can',
    txt4.startswith('refused') and 'dxf' in txt4 and 'ifc' in txt4,
    txt4,
)
txt5, _ = assistant('export_ifc', {}, doc={'objects': []})
check('export_ifc refuses an empty drawing without starting Blender', txt5.startswith('refused'), txt5)
txt6, _ = assistant('export_ifc', {'schema': 'IFC9'})
check('export_ifc refuses a schema that does not exist', txt6.startswith('refused'), txt6)
txt7, d7 = assistant('export_ifc', {'schema': 'IFC4'}, doc=FIVE)
check(
    'export_ifc calls the server route itself and reports the path and what came out of it',
    '5 IFC4 elements' in txt7 and 'IfcWall' in txt7 and 'data/architecture/exports/' in txt7 and not d7.ui,
    txt7,
)
txt8, d8 = assistant('press_button', {'id': 'f_ifc', 'args': {'schema': 'IFC2X3'}})
check(
    'the assistant may press all three icons with arguments',
    txt8.startswith('pressed')
    and d8.ui[-1]['args']['id'] == 'f_ifc'
    and d8.ui[-1]['args']['args'] == {'schema': 'IFC2X3'},
    (txt8, d8.ui),
)

import zyg_workflows.arch_assistant_ext.file_2d as AX  # noqa: E402

check(
    'the family declares its three buttons and explains their arguments in the prompt',
    AX.BUTTONS == IDS
    and all(b in AX.PROMPT for b in IDS)
    and 'IfcWall' in AX.PROMPT
    and 'data/architecture/exports/' in AX.PROMPT,
    AX.BUTTONS,
)

finish()
