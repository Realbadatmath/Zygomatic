# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_edit_ops.py — proves the four Edit icons wired by
arch_ext/edit_ops.js are real and do what their tooltips promise:

  e_align    edges coincide with the reference's after the press
  e_dist     the gaps between EDGES are equal to the millimetre
  e_history  the undo ring is a labelled list, and {back:n} really rewinds n edits
  e_purge    unused materials, dead definitions and orphan openings are found,
             and only deleted when asked

plus the assistant twins (align_objects / distribute_objects), whose numbers
must agree with the tab's to within 5 cm.

Three browser_eval calls in total (icon_state is the first of them).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import assistant, browser_eval, check, finish, icon_state  # noqa: E402

IDS = ['e_align', 'e_dist', 'e_history', 'e_purge']

# ── 1. the placeholder mark is gone in the live DOM ─────────────────────────
st = icon_state(IDS)
for i in IDS:
    s = st.get(i) or {}
    check(
        '%s is a real icon (exists, no stub flag, no dashed class, no [placeholder] tip)' % i,
        s.get('exists') and not s.get('stub') and not s.get('dashed') and not s.get('tip_placeholder'),
        s,
    )

# ── 2. align + distribute in the live tab ───────────────────────────────────
r1 = browser_eval("""() => {
  const bx = r => { const b = new THREE.Box3(); b.setFromObject(r.node);
                    return {x0:b.min.x, x1:b.max.x, y0:b.min.y, y1:b.max.y, z0:b.min.z, z1:b.max.z}; };
  const out = {errors: []};

  /* three slabs at x 0, 7 and 20, all different sizes */
  const A = arNewObj('slab', {w:2, d:2, t:0.2}, 0, 0, 0);
  const B = arNewObj('slab', {w:1, d:2, t:0.2}, 7, 0, 0);
  const C = arNewObj('slab', {w:4, d:2, t:0.2}, 20, 0, 0);
  arSelect([A.id, B.id, C.id]);
  const u0 = AR.undo.length;
  arTool('e_dist', {axis: 'x'});
  const a1 = bx(A), b1 = bx(B), c1 = bx(C);
  out.dist = {gap1: b1.x0 - a1.x1, gap2: c1.x0 - b1.x1, outerA: A.x, outerC: C.x, midX: B.x,
              pushed: AR.undo.length - u0};

  /* align: every min-x onto the FIRST selected object's min-x */
  B.x = 3.3; C.x = 14.1; arApplyTransform(B); arApplyTransform(C);
  arTool('e_align', {mode: 'left', to: 'first'});
  out.left = [bx(A).x0, bx(B).x0, bx(C).x0];

  /* align: top, on stacked boxes of different heights */
  const D = arNewObj('box', {w:1, d:1, h:1}, 0, 8, 0);
  const E = arNewObj('box', {w:1, d:1, h:3}, 3, 8, 0);
  E.y = 1.5; arApplyTransform(E);
  arSelect([E.id, D.id]);                       /* D is last -> D is the reference */
  arTool('e_align', {mode: 'top', to: 'last'});
  out.top = [bx(D).y1, bx(E).y1, E.y];

  /* face: E sits to the +X side of D, so E's -X face butts onto D's +X face */
  E.x = 9; E.y = 0; arApplyTransform(E);
  arSelect([E.id, D.id]);
  arTool('e_align', {mode: 'face', to: 'last'});
  out.face = {eMinX: bx(E).x0, dMaxX: bx(D).x1};

  /* two selected objects are the minimum; one is refused with a toast */
  arSelect([A.id]);
  arTool('e_align', {mode: 'left'});
  out.tooFew = document.getElementById('ar-toast').innerHTML;
  arSelect([A.id, B.id]);
  arTool('e_dist', {axis: 'x'});
  out.tooFewDist = document.getElementById('ar-toast').innerHTML;
  return out;
}""")
v = r1['value']
check('no page errors while aligning and distributing', not r1['errors'], r1['errors'])
check(
    'e_dist gives equal EDGE gaps (within 1 mm) and leaves the outer two alone',
    abs(v['dist']['gap1'] - v['dist']['gap2']) < 0.001
    and abs(v['dist']['outerA'] - 0) < 1e-6
    and abs(v['dist']['outerC'] - 20) < 1e-6,
    v['dist'],
)
check(
    'e_dist put the middle slab where the arithmetic says (edge gap 8 m, centre 9.5)',
    abs(v['dist']['midX'] - 9.5) < 0.001 and abs(v['dist']['gap1'] - 8.0) < 0.001,
    v['dist'],
)
check('e_dist pushed exactly one undo step', v['dist']['pushed'] == 1, v['dist'])
check(
    "e_align {mode:'left', to:'first'} makes every min x equal the first's",
    max(v['left']) - min(v['left']) < 1e-6,
    v['left'],
)
check(
    "e_align {mode:'top'} lifts the stacked box so the tops coincide", abs(v['top'][0] - v['top'][1]) < 1e-6, v['top']
)
check(
    "e_align {mode:'face'} butts the mover's near face onto the reference's",
    abs(v['face']['eMinX'] - v['face']['dMaxX']) < 1e-6,
    v['face'],
)
check('align refuses a single object with a warning, not a silent no-op', 'at least two' in v['tooFew'], v['tooFew'])
check('distribute refuses two objects with a warning', 'at least three' in v['tooFewDist'], v['tooFewDist'])

# ── 3. history + purge in the live tab ──────────────────────────────────────
r2 = browser_eval("""() => {
  const out = {};
  /* three edits, each behind its own arPush */
  arPush(); arNewObj('slab', {w:2, d:2, t:0.2}, 0, 0, 0);
  arPush(); arNewObj('slab', {w:2, d:2, t:0.2}, 5, 0, 0);
  arPush(); const c = arNewObj('slab', {w:2, d:2, t:0.2}, 10, 0, 0);
  arTool('e_history');
  const sheet = document.getElementById('ar-sheet');
  out.sheetOpen = sheet && sheet.style.display !== 'none';
  out.rows = (sheet.innerHTML.match(/<tr>/g) || []).length;
  out.labelled = /\\+1 /.test(sheet.innerHTML);
  out.stamped = /\\d\\d:\\d\\d:\\d\\d/.test(sheet.innerHTML);
  out.undo = AR.undo.length;
  out.hist = AR._edit_opsHist.length;
  arTool('e_history', {back: 2});
  out.afterBack = AR.objs.length;
  out.redoable = AR.redo.length;
  arRedo(); arRedo();
  out.afterRedo = AR.objs.length;
  out.histAfterRedo = AR._edit_opsHist.length;
  arSheetClose();

  /* purge: a door whose wall is deleted, a material no record uses, and
     definitions with nothing behind them */
  const w = arNewObj('wall', {len: 4, h: 2.7, t: 0.24}, 40, 0, 0);
  const dr = arNewObj('door', {w: 0.9, h: 2.1}, 40, 0, 0);
  arSyncHoles();
  out.hosted = dr.p.host === w.id;
  arRemove(w); arSyncHoles();
  arMat('mat_glass');
  out.glassCached = !!AR.matCache['mat_glass'];
  AR.doc.ext = {organise_model: {components: {chair: {n: 'Chair'}},
                                 sets: {gone: {ids: ['zz1', 'zz2']}},
                                 layers: {empty: {}, kept: {lock: true}}}};
  const u0 = AR.undo.length;
  arTool('e_purge', {});                       /* report only: no orphans flag */
  const s1 = document.getElementById('ar-sheet').innerHTML;
  out.purgeSheet = !!document.getElementById('ar-sheet') &&
                   document.getElementById('ar-sheet').style.display !== 'none';
  out.reportsOrphan = /orphan/i.test(s1);
  out.orphanId = s1.indexOf(dr.id) >= 0;
  out.doorStillThere = !!arFind(dr.id);
  out.glassGone = !AR.matCache['mat_glass'];
  out.pushedByReport = AR.undo.length - u0;
  const om = AR.doc.ext.organise_model;
  out.comps = Object.keys(om.components);
  out.sets = Object.keys(om.sets);
  out.layers = Object.keys(om.layers);
  arTool('e_purge', {orphans: true});
  out.doorGone = !arFind(dr.id);
  out.pushedByDelete = AR.undo.length - u0;
  return out;
}""")
h = r2['value']
check('no page errors while listing history and purging', not r2['errors'], r2['errors'])
check(
    'e_history opens a sheet listing the undo ring (>= 3 rows for 3 edits)',
    h['sheetOpen'] and h['rows'] >= 3 and h['hist'] == h['undo'] == 3,
    h,
)
check('every row is labelled with what changed and stamped with the time', h['labelled'] and h['stamped'], h)
check('e_history {back:2} rewinds two edits — the drawing is back to one object', h['afterBack'] == 1, h)
check(
    'the jump used real undos, so Redo brings all three back',
    h['redoable'] == 2 and h['afterRedo'] == 3 and h['histAfterRedo'] == 3,
    h,
)
check('the door was hosted by the wall before the wall went', h['hosted'], h)
check(
    'e_purge opens a sheet that reports the orphan opening by id',
    h['purgeSheet'] and h['reportsOrphan'] and h['orphanId'],
    h,
)
check(
    'a report-only purge deletes no records and pushes no undo step',
    h['doorStillThere'] and h['pushedByReport'] == 0,
    h,
)
check(
    'e_purge frees the material no record uses (mat_glass leaves AR.matCache)', h['glassCached'] and h['glassGone'], h
)
check('e_purge drops the component definition with no instance', h['comps'] == [], h)
check('e_purge drops the selection set naming only deleted ids', h['sets'] == [], h)
check('e_purge drops the empty layer and keeps the locked one', h['layers'] == ['kept'], h)
check('e_purge {orphans:true} deletes the orphan door behind one arPush', h['doorGone'] and h['pushedByDelete'] == 1, h)

# ── 4. the assistant twins ──────────────────────────────────────────────────
DOC = {
    'objects': [
        {'id': 'o1', 'kind': 'slab', 'p': {'w': 2, 'd': 2, 't': 0.2}, 'x': 0, 'y': 0, 'z': 0},
        {'id': 'o2', 'kind': 'slab', 'p': {'w': 1, 'd': 2, 't': 0.2}, 'x': 7, 'y': 0, 'z': 0},
        {'id': 'o3', 'kind': 'slab', 'p': {'w': 4, 'd': 2, 't': 0.2}, 'x': 20, 'y': 0, 'z': 0},
    ]
}

txt, d = assistant('distribute_objects', {'which': 'all', 'axis': 'x'}, doc=DOC)
mid = d.find('o2')
check(
    'distribute_objects moved the middle slab to the same x the tab did (within 5 cm)',
    abs(mid['x'] - v['dist']['midX']) < 0.05
    and abs(d.find('o1')['x'] - 0) < 1e-6
    and abs(d.find('o3')['x'] - 20) < 1e-6,
    (txt, mid['x'], v['dist']['midX']),
)

txt2, d2 = assistant('align_objects', {'which': 'all', 'mode': 'left', 'to': 'first'}, doc=DOC)
xs = [(o['x'] - abs(o['p']['w']) / 2) for o in d2.objs]
check(
    "align_objects moves x so every min x equals the first object's",
    max(xs) - min(xs) < 1e-6 and abs(d2.find('o2')['x'] + 0.5) < 1e-6,
    (txt2, xs),
)

txt3, d3 = assistant(
    'align_objects',
    {'which': 'all', 'mode': 'top', 'to': 'last'},
    doc={
        'objects': [
            {'id': 'o1', 'kind': 'box', 'p': {'w': 1, 'd': 1, 'h': 1}, 'x': 0, 'y': 0, 'z': 0},
            {'id': 'o2', 'kind': 'box', 'p': {'w': 1, 'd': 1, 'h': 3}, 'x': 3, 'y': 0, 'z': 0},
        ]
    },
)
check(
    'align_objects top matches the tab: the shorter box rises so the tops coincide',
    abs(d3.find('o1')['y'] - 2.0) < 1e-6 and abs(d3.find('o2')['y']) < 1e-6,
    (txt3, d3.objs),
)

txt4, _ = assistant('align_objects', {'which': 'all', 'mode': 'sideways'}, doc=DOC)
check('align_objects refuses an unknown mode', txt4.startswith('refused'), txt4)
txt5, _ = assistant('distribute_objects', {'which': 'o1'}, doc=DOC)
check('distribute_objects refuses fewer than three objects', txt5.startswith('refused'), txt5)

from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
check('the model may press all four icons (EXT_BUTTONS)', all(i in A.EXT_BUTTONS for i in IDS), sorted(A.EXT_BUTTONS))
txt6, d6 = assistant('press_button', {'id': 'e_history', 'args': {'back': 2}})
check(
    'press_button carries {back:2} to e_history',
    txt6.startswith('pressed')
    and d6.ui[-1]['args']['id'] == 'e_history'
    and d6.ui[-1]['args'].get('args') == {'back': 2},
    (txt6, d6.ui),
)

finish()
