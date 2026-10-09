# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_grid_scale.py — the per-DRAWING grid scale (2026-09-07).

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_grid_scale.py

The studio grid is always 300 x 300 cells named A1..KN300, but how many METRES
one cell is belongs to the document (doc.cell_m: 1, 2, 5 or 10). A building keeps
1 m cells; a landscape at 5 m spans 1500 m and at 10 m spans 3 km. This proves
the three sides of that seam agree:

  · THE ASSISTANT — Drawing.cell_m, the module-level _CELL that parse_cell /
    cell_centre / cell_of / block_bounds read, the set_grid_scale tool, and that
    a document WITHOUT cell_m still produces every old number.
  · THE STORE — architecture_studio.save_project / load_project carry cell_m.
  · THE TAB — opening that saved drawing sets AR_CELL_M and rebuilds the grid
    helper at 1500 m, and File > New puts it back to 1 m / 300 m.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402
from zyg_workflows import architecture_studio as ST  # noqa: E402

PROBE_ID = 'zz-grid-scale-probe'

print('python — the assistant')
check('the four allowed cell sizes', A.CELL_SIZES == (1.0, 2.0, 5.0, 10.0), A.CELL_SIZES)
check('the module starts at 1 m', A._CELL == {'m': 1.0, 'origin': -150.0}, A._CELL)

# ── a 5 m drawing ────────────────────────────────────────────────────────────
d5 = A.Drawing({'cell_m': 5, 'objects': []})
check('Drawing({cell_m: 5}).cell_m is 5', d5.cell_m == 5.0, d5.cell_m)
txt = A.call_tool(d5, 'add_hill', {'centre': 'A1', 'radius': 40, 'height': 30})
o = d5.objs[-1]
check(
    'add_hill on A1 at 5 m lands at the centre of a 5 m cell (-750 + 2.5)',
    o['x'] == -747.5 and o['z'] == -747.5,
    (txt, o['x'], o['z']),
)
with A._Scale(5):
    bb = A.block_bounds('A1', 'J10')
    c = A.cell_of(-747.5, -747.5)
    cc = A.cell_centre(*A.parse_cell('A1'))
    far = A.cell_of(747.4, 747.4)
check('block_bounds A1..J10 at 5 m spans 50 x 50 m from the corner', bb == (-750.0, -750.0, -700.0, -700.0), bb)
check("cell_of(-747.5, -747.5) at 5 m is 'A1'", c == 'A1', c)
check('cell_centre(A1) at 5 m is (-747.5, -747.5)', cc == (-747.5, -747.5), cc)
check('the far corner of a 5 m field is KN300', far == 'KN300', far)
check('the module is back at 1 m after the tool call', A._CELL['m'] == 1.0, A._CELL)

# ── set_grid_scale ───────────────────────────────────────────────────────────
r = A.call_tool(d5, 'set_grid_scale', {'metres_per_cell': 10})
check(
    'set_grid_scale is refused on a drawing that already holds objects',
    r == 'refused: the drawing has 1 objects — the cell size is set before drawing; start a new drawing',
    r,
)
check('a refused set_grid_scale leaves the drawing at 5 m', d5.cell_m == 5.0, d5.cell_m)
d0 = A.Drawing({'objects': []})
r = A.call_tool(d0, 'set_grid_scale', {'metres_per_cell': 5})
check('set_grid_scale(5) on an empty drawing', r == 'cells are now 5 m: the field is 1500 x 1500 m, A1..KN300', r)
check('the drawing is now 5 m', d0.cell_m == 5.0, d0.cell_m)
check(
    'to_doc() carries cell_m',
    A.Drawing(d0.to_doc()).cell_m == 5.0 and d0.to_doc()['cell_m'] == 5.0,
    d0.to_doc()['cell_m'],
)
r = A.call_tool(A.Drawing({'objects': []}), 'set_grid_scale', {'metres_per_cell': 3})
check('an unlisted cell size is refused', r == 'refused: the cell size must be 1, 2, 5 or 10 metres', r)
check('set_grid_scale is a declared tool', 'set_grid_scale' in [t['name'] for t in A.TOOL_DEFS])
check(
    'the system prompt tells the model to call it first',
    'set_grid_scale(5) or (10) FIRST on an empty drawing' in A.system_prompt(2.7),
)
# after set_grid_scale the next call really draws at the new size
txt = A.call_tool(d0, 'add_hill', {'centre': 'A1', 'radius': 40, 'height': 30})
check('the call after set_grid_scale(5) draws on the 5 m grid', d0.objs[-1]['x'] == -747.5, (txt, d0.objs[-1]['x']))

# ── a drawing with no cell_m is byte-for-byte the old one ────────────────────
d1 = A.Drawing({'objects': []})
check('no cell_m -> 1 m', d1.cell_m == 1.0, d1.cell_m)
check(
    'a bad cell_m falls back to 1 m',
    A.Drawing({'cell_m': 7}).cell_m == 1.0 and A.Drawing({'cell_m': 'big'}).cell_m == 1.0,
)
txt = A.call_tool(d1, 'add_hill', {'centre': 'A1', 'radius': 8, 'height': 3})
check(
    'add_hill on A1 at 1 m still lands at (-149.5, -149.5)',
    d1.objs[-1]['x'] == -149.5 and d1.objs[-1]['z'] == -149.5,
    (d1.objs[-1]['x'], d1.objs[-1]['z']),
)
check(
    'block_bounds A1..J10 at 1 m still spans 10 x 10 m',
    A.block_bounds('A1', 'J10') == (-150.0, -150.0, -140.0, -140.0),
    A.block_bounds('A1', 'J10'),
)
check("cell_of(-149.5, -149.5) at 1 m is still 'A1'", A.cell_of(-149.5, -149.5) == 'A1', A.cell_of(-149.5, -149.5))
check(
    'cell_centre(A1) at 1 m is still (-149.5, -149.5)',
    A.cell_centre(*A.parse_cell('A1')) == (-149.5, -149.5),
    A.cell_centre(*A.parse_cell('A1')),
)
check("cell_of(0, 0) at 1 m is still 'EU151'", A.cell_of(0, 0) == 'EU151', A.cell_of(0, 0))
check(
    'the module constants are untouched',
    (A.GRID_N, A.CELL_M, A.ORIGIN) == (300, 1.0, -150.0),
    (A.GRID_N, A.CELL_M, A.ORIGIN),
)

print('\npython — the project store')
doc = A.Drawing({'cell_m': 5, 'objects': []}).to_doc()
doc['objects'] = [
    {
        'id': 'o1',
        'kind': 'box',
        'name': 'probe',
        'p': {'w': 20, 'd': 20, 'h': 20},
        'x': -747.5,
        'y': 0,
        'z': -747.5,
        'rx': 0,
        'ry': 0,
        'rz': 0,
        's': 1,
        'mat': 'mat_stone',
        'hidden': False,
        'grp': '',
    }
]
doc['name'] = 'grid scale probe'
sv = ST.save_project(doc, pid=PROBE_ID, name='grid scale probe')
check('save_project wrote the probe', sv.get('ok') and sv.get('id') == PROBE_ID, sv)
back = ST.load_project(sv.get('id') or PROBE_ID)
check(
    'load_project gives cell_m back untouched',
    back.get('doc', {}).get('cell_m') == 5.0,
    back.get('doc', {}).get('cell_m'),
)
check('a Drawing rebuilt from the stored doc is 5 m', A.Drawing(back['doc']).cell_m == 5.0)

print('\nthe tab (headless Chrome)')
_TAB = r"""
(pid) => new Promise((resolve) => {
  const size = () => { const b = new THREE.Box3().setFromObject(AR.grid);
                       const s = b.getSize(new THREE.Vector3()); return Math.round(s.x); };
  const out = {start_m: AR_CELL_M, start_size: size()};
  window.confirm = () => true;
  arOpen(pid);
  let n = 0;
  const t = setInterval(() => {
    if (++n > 200) { clearInterval(t); out.err = 'arOpen never landed'; resolve(out); return; }
    if (AR.objs.length !== 1) return;
    clearInterval(t);
    out.open_m = AR_CELL_M; out.open_o = AR_CELL_O; out.open_field = AR_FIELD;
    out.open_size = size(); out.open_div = AR.grid.geometry.attributes.position.count / 4;
    out.cell_of_corner = arCellName(-747.5, -747.5);
    out.cell_of_centre = arCellName(0, 0);
    out.doc_cell_m = arDocOut().cell_m;
    try { arCellsToggle(); out.cells_on = AR.cells.on; out.cells_span = AR.cells.field.span;
          out.cells_x0 = AR.cells.field.x0; out.cells_w = AR.cells.field.mesh.scale.x;
          arCellsToggle(); } catch (e) { out.cells_err = String(e && e.message || e); }
    arNew();
    out.new_m = AR_CELL_M; out.new_o = AR_CELL_O; out.new_size = size();
    out.new_cell_of_centre = arCellName(0, 0); out.new_doc_cell_m = arDocOut().cell_m;
    resolve(out);
  }, 100);
})
"""


def tab(pid):
    from playwright.sync_api import sync_playwright

    errs = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome', args=['--enable-unsafe-swiftshader', '--disable-gpu-sandbox'])
        page = browser.new_page(viewport={'width': 1400, 'height': 900})
        page.on('pageerror', lambda e: errs.append(str(e)))
        page.on('dialog', lambda d: d.accept())
        page.goto('http://127.0.0.1:8899/inspection.html#architecture', wait_until='domcontentloaded', timeout=120000)
        page.wait_for_function('typeof goToView === "function"', timeout=120000)
        page.evaluate('goToView("architecture")')
        page.wait_for_function('typeof AR !== "undefined" && AR.built', timeout=120000)
        page.evaluate('AR.shadows=false; AR.renderer.shadowMap.enabled=false; AR.sun.castShadow=false;')
        out = page.evaluate(_TAB, pid)
        browser.close()
    out['page_errors'] = errs[:3]
    return out


t = tab(PROBE_ID)
check('no page errors', not t['page_errors'], t['page_errors'])
check(
    'the tab starts at 1 m with a 300 m grid',
    (t['start_m'], t['start_size']) == (1, 300),
    (t['start_m'], t['start_size']),
)
check('opening the 5 m drawing sets AR_CELL_M = 5', t.get('open_m') == 5, t)
check(
    'AR_CELL_O and AR_FIELD follow it (-750, 750)',
    (t.get('open_o'), t.get('open_field')) == (-750, 750),
    (t.get('open_o'), t.get('open_field')),
)
check(
    'the grid helper is rebuilt 1500 m across, still 300 divisions (301 lines an axis)',
    t.get('open_size') == 1500 and t.get('open_div') == 301,
    (t.get('open_size'), t.get('open_div')),
)
check(
    "the tab names (-747.5, -747.5) 'A1' — the same cell the assistant did",
    t.get('cell_of_corner') == 'A1',
    t.get('cell_of_corner'),
)
check('the centre of a 5 m field is still EU151', t.get('cell_of_centre') == 'EU151', t.get('cell_of_centre'))
check('arDocOut() writes cell_m 5 back', t.get('doc_cell_m') == 5, t.get('doc_cell_m'))
check(
    'the Shift+R label overlay still paints 150 cells — 750 m wide at 5 m',
    t.get('cells_on') is True and t.get('cells_span') == 150 and t.get('cells_w') == 750,
    (t.get('cells_err'), t.get('cells_span'), t.get('cells_w'), t.get('cells_x0')),
)
check(
    'File > New puts the grid back to 1 m / 300 m',
    (t.get('new_m'), t.get('new_o'), t.get('new_size'), t.get('new_doc_cell_m')) == (1, -150, 300, 1),
    (t.get('new_m'), t.get('new_o'), t.get('new_size'), t.get('new_doc_cell_m')),
)
check(
    'a 1 m drawing still names (0, 0) EU151 in the tab',
    t.get('new_cell_of_centre') == 'EU151',
    t.get('new_cell_of_centre'),
)

ST.delete_project(PROBE_ID)
check('the probe drawing is cleaned up', not os.path.exists(os.path.join(ST.PROJ_DIR, PROBE_ID + '.json')))

finish()
