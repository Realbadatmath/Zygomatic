# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_site_terrain.py — proves Site ▸ Terrain, Contours and
Cut and fill are wired for real.

Three icons, three proofs each: the placeholder mark is gone in the live DOM,
the icon does what its tooltip promises (a record appears, a LineSegments
appears and goes again, a sheet of volumes opens), and the assistant's
server-side twin agrees about the numbers. Two browser_eval calls plus the one
icon_state makes — the budget the brief sets.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import assistant, browser_eval, check, finish, icon_state  # noqa: E402

IDS = ['st_terrain', 'st_contour', 'st_cutfill']

# ── 1. the icons are no longer placeholders ──────────────────────────────────
st = icon_state(IDS)
for i in IDS:
    s = st.get(i, {})
    check(
        '%s is in the dock and no longer a placeholder (stub/dashed/[placeholder] all gone)' % i,
        s.get('exists') and not s.get('stub') and not s.get('dashed') and not s.get('tip_placeholder'),
        s,
    )

# ── 2. st_terrain lays the ground, places a sculpt, and st_contour draws ─────
R1 = browser_eval(
    """async () => {
  const frame = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  const out = {};
  const undo0 = AR.undo.length;

  arTool('st_terrain');                                  /* empty drawing → lay the ground */
  out.grounds = AR.objs.filter(o => o.kind === 'ground').length;
  const g = AR.objs.filter(o => o.kind === 'ground')[0];
  out.groundP = g ? {w: g.p.w, d: g.p.d, res: g.p.res} : null;
  out.toast = document.getElementById('ar-toast').innerHTML;
  out.pushedForGround = AR.undo.length - undo0;
  arUndo();                                              /* one arPush → one undo step */
  out.groundsAfterUndo = AR.objs.filter(o => o.kind === 'ground').length;
  arTool('st_terrain');                                  /* lay it again */
  out.on = AR_EXT.tools.st_terrain.on();

  arTool('st_terrain', {kind: 'sculpt_peak', cell: 'C4'});   /* opt {kind, cell} */
  const c4 = AR.objs.filter(o => o.kind === 'sculpt_peak')[0];
  out.cellSculpt = c4 ? {x: Math.round(c4.x * 100) / 100, z: Math.round(c4.z * 100) / 100, p: c4.p} : null;
  out.cellExpected = AR_EXT.site_terrain.cellCentre('C4');

  arTool('st_terrain', {kind: 'sculpt_peak'});               /* on the ground itself */
  out.sculpts = AR.objs.filter(o => o.kind === 'sculpt_peak').length;
  await frame(); await frame();                              /* arGroundRefresh coalesces on rAF */
  let maxY = -1e9;
  const gr = AR.objs.filter(o => o.kind === 'ground')[0];
  gr.node.traverse(m => { if (m.isMesh && m.geometry && m.geometry.attributes.position) {
    const a = m.geometry.attributes.position;
    for (let i = 0; i < a.count; i++) maxY = Math.max(maxY, a.getY(i));
  }});
  out.groundMaxY = Math.round(maxY * 1000) / 1000;

  /* the Terrain sheet on a second press: ten sculpts, each with a place button */
  arTool('st_terrain');
  const sh = document.getElementById('ar-sheet');
  out.sheetTitle = sh.querySelector('.hd span').textContent;
  out.sheetOpen = sh.style.display !== 'none';
  out.sheetPlaceBtns = sh.querySelectorAll('button[onclick^="siteTerrainArm"]').length;
  out.sheetGroundInputs = sh.querySelectorAll('input[onclick], input[onchange]').length;

  /* a place button arms the rail's own placement path */
  siteTerrainArm('sculpt_cut');
  out.armed = {tool: AR.tool, kind: AR.place && AR.place.kind, hasLen: !!(AR.place && AR.place.p.len)};
  arTool('select');

  /* contours */
  arTool('st_contour', {interval: 1});
  out.contourOn = AR_EXT.tools.st_contour.on();
  let seg = null, sprites = 0;
  AR.scene.traverse(o => { if (o.isLineSegments && o.name === 'site_terrain_contours') seg = o;
                           if (o.isSprite && o.parent && o.parent.name === 'site_terrain_contour_group') sprites++; });
  out.contourVerts = seg ? seg.geometry.attributes.position.count : 0;
  out.contourColoured = !!(seg && seg.geometry.attributes.color);
  out.contourSprites = sprites;
  out.contourInfo = AR._stContourInfo;
  out.docExt = AR.doc.ext && AR.doc.ext.site_terrain;

  arTool('st_contour');                                       /* off */
  let still = 0;
  AR.scene.traverse(o => { if (o.isLineSegments && o.name === 'site_terrain_contours') still++; });
  out.contourAfterOff = still;
  out.contourOffState = AR_EXT.tools.st_contour.on();
  return out;
}""",
    doc={'objects': []},
)
V = R1['value']
check('no page errors while pressing Terrain and Contours', not R1['errors'], R1['errors'])
check(
    'st_terrain on an empty drawing creates exactly one ground record, 200 x 200 m',
    V['grounds'] == 1 and V['groundP']['w'] == 200 and V['groundP']['d'] == 200,
    V['groundP'],
)
check(
    'it says out loud how to sculpt what it just laid',
    'Ground laid' in V['toast'] and 'sculpt' in V['toast'],
    V['toast'],
)
check(
    'the ground went behind ONE arPush (undo takes it back)',
    V['pushedForGround'] == 1 and V['groundsAfterUndo'] == 0,
    V,
)
check('st_terrain latches on() while a ground exists', V['on'] is True, V['on'])
check(
    'opt {kind, cell} places that sculpt at that cell',
    V['cellSculpt']
    and abs(V['cellSculpt']['x'] - V['cellExpected']['x']) < 0.01
    and abs(V['cellSculpt']['z'] - V['cellExpected']['z']) < 0.01
    and V['cellSculpt']['p']['r'] == 40
    and V['cellSculpt']['p']['h'] == 30,
    V['cellSculpt'],
)
check(
    'a sculpt on the ground lifts the ground mesh (max vertex y > 0.5 m)',
    V['sculpts'] == 2 and V['groundMaxY'] > 0.5,
    {'sculpts': V['sculpts'], 'maxY': V['groundMaxY']},
)
check(
    'a second press opens the Terrain sheet with a place button for all ten sculpts',
    V['sheetOpen'] and V['sheetTitle'] == 'Terrain' and V['sheetPlaceBtns'] == 10 and V['sheetGroundInputs'] >= 9,
    {k: V[k] for k in ('sheetTitle', 'sheetOpen', 'sheetPlaceBtns', 'sheetGroundInputs')},
)
check(
    "a place button arms arTool('place') with the kind and its defaults",
    V['armed'] == {'tool': 'place', 'kind': 'sculpt_cut', 'hasLen': True},
    V['armed'],
)
check(
    'st_contour {interval:1} draws ONE LineSegments with more than 100 vertices',
    V['contourOn'] is True and V['contourVerts'] > 100 and V['contourColoured'],
    {'on': V['contourOn'], 'verts': V['contourVerts'], 'col': V['contourColoured']},
)
check(
    'every major (5th) level is labelled once with a sprite',
    V['contourSprites'] >= 1 and V['contourSprites'] == V['contourInfo']['majors'],
    {'sprites': V['contourSprites'], 'info': V['contourInfo']},
)
check('the interval is remembered per drawing in AR.doc.ext.site_terrain', V['docExt'] == {'interval': 1}, V['docExt'])
check(
    'pressing st_contour again removes the lines and unlatches',
    V['contourAfterOff'] == 0 and not V['contourOffState'],
    V,
)

# ── 3. st_cutfill: volumes, the sheet, and the balance button ────────────────
#  a modest 3 m peak on a 200 m ground; two 10 x 10 m slabs over its summit,
#  one at y 0 (all cut) and one at y 5, above everything (all fill).
DOC = {
    'objects': [
        {
            'id': 'g1',
            'kind': 'ground',
            'name': 'Ground',
            'mat': 'mat_grass',
            'p': {
                'w': 200,
                'd': 200,
                'res': 100,
                'seed': 1,
                'base': 0,
                'amp': 1.5,
                'snow_h': 60,
                'water_h': -0.15,
                'grass_max_slope': 32,
            },
            'x': 0,
            'z': 0,
            'y': 0,
        },
        {
            'id': 'p1',
            'kind': 'sculpt_peak',
            'name': 'Peak',
            'p': {'r': 40, 'h': 3, 'rug': 0.45, 'seed': 1, 'feather': 8},
            'x': 0,
            'z': 0,
            'y': 0,
        },
        {'id': 'sa', 'kind': 'slab', 'name': 'Slab low', 'p': {'w': 10, 'd': 10, 't': 0.2}, 'x': 0, 'z': 0, 'y': 0},
        {'id': 'sb', 'kind': 'slab', 'name': 'Slab high', 'p': {'w': 10, 'd': 10, 't': 0.2}, 'x': 0, 'z': 0, 'y': 5},
    ]
}
R2 = browser_eval(
    """async () => {
  const out = {};
  arSelect(['sa']);
  const undo0 = AR.undo.length;
  arTool('st_cutfill', {which: 'selection'});
  const a = AR._stCutFill;
  out.low = {cut: Math.round(a.cut * 10) / 10, fill: Math.round(a.fill * 10) / 10,
             rows: a.rows.length, trucks: a.trucks, base: a.rows[0].base};
  out.readOnly = AR.undo.length - undo0;                 /* a report never pushes */
  const sh = document.getElementById('ar-sheet');
  out.sheetTitle = sh.querySelector('.hd span').textContent;
  out.sheetRows = sh.querySelectorAll('table.ar-tbl tr').length;
  out.sheetText = sh.querySelector('.bd').textContent;
  out.hasBalanceBtn = !!sh.querySelector('button[onclick^="siteTerrainBalance"]');

  arSelect(['sb']);
  arTool('st_cutfill', {which: 'selection'});
  const b = AR._stCutFill;
  out.high = {cut: Math.round(b.cut * 10) / 10, fill: Math.round(b.fill * 10) / 10};

  arTool('st_cutfill', {which: 'all'});
  out.all = {rows: AR._stCutFill.rows.length};

  /* balance: put the low slab where cut equals fill, behind one arPush */
  arSelect(['sa']);
  arTool('st_cutfill', {which: 'selection'});
  const u1 = AR.undo.length;
  siteTerrainBalance();
  const rec = arFind('sa');
  out.balanced = {y: rec.y, pushed: AR.undo.length - u1};
  const bal = AR._stCutFill;
  out.balancedNet = Math.round(bal.net * 100) / 100;
  out.balancedCut = Math.round(bal.cut * 10) / 10;

  /* flatten under buildings: one level pad per footprint, one arPush */
  const u2 = AR.undo.length;
  siteTerrainFlatten();
  const pads = AR.objs.filter(o => o.kind === 'sculpt_flat');
  out.pads = pads.length;
  out.padPushed = AR.undo.length - u2;
  out.padP = pads[0] ? pads[0].p : null;
  out.padFor = pads[0] ? pads[0].meta.site_terrain_pad_for : null;

  /* the ground's own parameters are editable from the sheet */
  siteTerrainGroundSet('amp', 4);
  out.amp = arFind('g1').p.amp;
  return out;
}""",
    doc=DOC,
)
W = R2['value']
check('no page errors while reporting cut and fill', not R2['errors'], R2['errors'])
check(
    'a slab at y 0 over the peak is all cut and no fill',
    W['low']['cut'] > 0 and W['low']['fill'] < 0.01 and W['low']['base'] == 0,
    W['low'],
)
check(
    'a slab at y 5, above the whole landform, is all fill and no cut',
    W['high']['fill'] > W['high']['cut'] and W['high']['cut'] < 0.01 and W['high']['fill'] > 0,
    W['high'],
)
check(
    'the report opens a sheet with a row per slab and the totals in m3',
    W['sheetTitle'] == 'Cut and fill'
    and W['sheetRows'] >= 5
    and 'total cut' in W['sheetText']
    and 'truck loads' in W['sheetText'],
    {'title': W['sheetTitle'], 'rows': W['sheetRows']},
)
check('truck loads are the volume at 8 m3 a load', W['low']['trucks'] == -(-W['low']['cut'] // 8), W['low'])
check('a read-only report never pushes an undo step', W['readOnly'] == 0, W['readOnly'])
check("which:'all' covers both slabs", W['all']['rows'] == 2, W['all'])
check(
    'balance moves the slab to the level where cut equals fill, behind one arPush',
    W['balanced']['pushed'] == 1
    and 0 < W['balanced']['y'] < 5
    and abs(W['balancedNet']) < 0.5
    and W['balancedCut'] > 0,
    W,
)
check(
    'flatten under buildings adds one level pad per footprint, behind one arPush',
    W['pads'] == 2
    and W['padPushed'] == 1
    and W['padP']['w'] == 14
    and W['padP']['d'] == 14
    and W['padFor'] in ('sa', 'sb'),
    W,
)
check('the sheet edits the ground itself (base roll amp -> 4)', W['amp'] == 4, W['amp'])

# ── 4. the assistant twins, on the same document ─────────────────────────────
txt, d = assistant('ensure_ground', {'size': 200})
check('ensure_ground lays the one ground', [o['kind'] for o in d.objs].count('ground') == 1, txt)
txt2, _ = assistant('ensure_ground', {}, drawing=d)
check(
    'ensure_ground is idempotent — it never makes a second ground',
    'already has its ground' in txt2 and [o['kind'] for o in d.objs].count('ground') == 1,
    txt2,
)

txt3, d3 = assistant('contours', {'interval': 1}, doc=DOC)
check(
    'contours reports a length per level from the Python heightfield',
    txt3.startswith('contours at 1 m') and ' m: ' in txt3 and ' m of line in all' in txt3,
    txt3[:220],
)
TALL = {'objects': [dict(o, p=dict(o['p'], h=30)) if o['id'] == 'p1' else o for o in DOC['objects']]}
txt3a, _ = assistant('contours', {'interval': 1}, doc=TALL)
check(
    'every fifth level is called out as major',
    '5 m (major):' in txt3a and '10 m (major):' in txt3a and '4 m:' in txt3a,
    txt3a[:220],
)
txt3b, _ = assistant('contours', {'interval': 0}, doc=DOC)
check('a non-positive interval is refused', txt3b.startswith('refused'), txt3b)
txt3c, _ = assistant('contours', {'interval': 1}, doc={'objects': []})
check('contours without a ground is refused', txt3c.startswith('refused'), txt3c)

txt4, _ = assistant('cut_fill', {'which': 'all'}, doc=DOC)
check(
    'cut_fill reports cut, fill, net and truck loads',
    'total cut' in txt4 and 'total fill' in txt4 and 'truck load' in txt4,
    txt4[:220],
)
txt5, _ = assistant('cut_fill', {'which': ['sa']}, doc=DOC)
txt6, _ = assistant('cut_fill', {'which': ['sb']}, doc=DOC)


def _tot(t, key):
    seg = t.split('total ' + key + ' ', 1)[1]
    return float(seg.split(' ', 1)[0])


py_low_cut, py_low_fill = _tot(txt5, 'cut'), _tot(txt5, 'fill')
py_high_cut, py_high_fill = _tot(txt6, 'cut'), _tot(txt6, 'fill')
check(
    'Python agrees the y-0 slab is cut and the y-5 slab is fill',
    py_low_cut > py_low_fill and py_high_fill > py_high_cut,
    {'low': (py_low_cut, py_low_fill), 'high': (py_high_cut, py_high_fill)},
)
check(
    'Python and the tab agree on the y-0 slab within 10 %',
    abs(py_low_cut - W['low']['cut']) <= 0.10 * max(py_low_cut, W['low']['cut']),
    {'python': py_low_cut, 'tab': W['low']['cut']},
)
txt7, _ = assistant('cut_fill', {'which': 'all'}, doc={'objects': []})
check('cut_fill without a ground is refused', txt7.startswith('refused'), txt7)

from zyg_workflows import arch_assistant as A  # noqa: E402

check(
    'the three icons are declared pressable by the assistant',
    all(i in A.EXT_BUTTONS for i in IDS),
    sorted(A.EXT_BUTTONS),
)
for i in IDS:
    t, dd = assistant('press_button', {'id': i, 'args': {'which': 'all'}})
    check('the assistant may press %s' % i, t.startswith('pressed') and dd.ui[-1]['args']['id'] == i, t)

finish()
