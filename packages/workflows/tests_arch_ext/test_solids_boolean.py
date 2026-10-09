# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_solids_boolean.py — proof for the solids_boolean family.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_solids_boolean.py

Three icons (bool_u, bool_s, bool_i) and one new kind ('csg'). What is proved:

  · the three icons are no longer placeholders in the LIVE tab (no stub flag,
    no dashed class, no "[placeholder]" tooltip);
  · each one really cuts — the arithmetic of the result is checked as a bbox,
    not as a picture: union spans both boxes, intersect is the overlap alone,
    subtract is the first box minus the overlap, and a subtract of a strictly
    interior box keeps the outer bbox while adding faces (a cavity);
  · two selected objects become exactly ONE record of kind 'csg' whose p keeps
    both operands' PARAMETERS (a drawing stores parameters, never geometry);
  · subtract order is selection order, the assistant's {a, b} args are honoured,
    one arPush() means one undo brings both operands back, the >20000-triangle
    cap refuses instead of hanging, and the WeakMap cache makes a rebuild free;
  · the assistant may press all three icons and has a server-side twin
    (boolean()) that makes the same record;
  · the rail lists the kind and Blender builds it.

Two browser_eval calls (icon_state is the first, the behaviour batch the
second), well inside the brief's budget of three.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import (
    check,
    finish,
    assistant,
    blender_kinds,  # noqa: E402
    browser_eval,
    icon_state,
    rail_has,
    tool_names,
)

IDS = ['bool_u', 'bool_s', 'bool_i']

# ── 1. the icons stopped being placeholders ──────────────────────────────────
st = icon_state(IDS)
for i in IDS:
    s = st.get(i) or {}
    check(
        '%s is a real icon (exists, no stub flag, no dashed class, no [placeholder] tip)' % i,
        s.get('exists') and not s.get('stub') and not s.get('dashed') and not s.get('tip_placeholder'),
        s,
    )

# ── 2. what the three icons actually do ──────────────────────────────────────
JS = r"""() => {
  const R = {};
  const clear = () => { AR.objs.slice().forEach(arRemove); AR.sel = []; };
  const mk = (x, y, p) => arNewObj('box', p || {w:2, h:2, d:2}, x, 0, y);
  const tris = r => { let n = 0; r.node.traverse(m => {
      if (m.isMesh && m.geometry && m.geometry.attributes.position)
        n += (m.geometry.index ? m.geometry.index.count : m.geometry.attributes.position.count) / 3; });
    return Math.round(n); };
  const rd = v => Math.round(v * 1000) / 1000;
  const box = r => { r.node.updateMatrixWorld(true);
    const b = new THREE.Box3().expandByObject(r.node), s = b.getSize(new THREE.Vector3());
    return {min: [rd(b.min.x), rd(b.min.y), rd(b.min.z)], size: [rd(s.x), rd(s.y), rd(s.z)]}; };
  const shot = () => { const rest = AR.objs.slice(), r = rest[0];
    const o = {n: rest.length, id: r && r.id, kind: r && r.kind, sel: AR.sel.slice(),
               p: r && r.kind === 'csg' ? JSON.parse(JSON.stringify(r.p)) : null,
               tris: r ? tris(r) : 0, name: r && r.name, mat: r && r.mat,
               ms: r && r.meta ? r.meta.csg_ms : null};
    if (r) { const b = box(r); o.min = b.min; o.size = b.size; }
    return o; };
  /* A = 2x2x2 at the origin: x -1..1, y 0..2, z -1..1.
     B = 2x2x2 at x=+1:       x  0..2, y 0..2, z -1..1.  Overlap = x 0..1. */
  const two = () => { clear(); const a = mk(0, 0), b = mk(1, 0); arSelect([a.id, b.id]); return [a, b]; };

  two(); arTool('bool_u');  R.union     = shot();
  two(); arTool('bool_s');  R.subtract  = shot();
  two(); arTool('bool_i');  R.intersect = shot();

  /* B strictly INSIDE A (x -0.6..0.6, y 0.4..1.6, z -0.6..0.6): the subtract
     keeps A's bounding box and hollows it, so faces go UP, not down. */
  clear();
  { const a = mk(0, 0), b = mk(0, 0.4, {w:1.2, h:1.2, d:1.2});
    arSelect([a.id, b.id]); arTool('bool_s'); R.hollow = shot(); }

  /* two solids that do not touch: the intersection is genuinely empty */
  clear();
  { const a = mk(0, 0), b = mk(6, 0); arSelect([a.id, b.id]); arTool('bool_i'); R.empty = shot(); }

  /* ONE selected object: refuse, change nothing, say why */
  clear();
  { const a = mk(0, 0); arSelect([a.id]); arTool('bool_u');
    R.refuse = {n: AR.objs.length, kind: AR.objs[0].kind,
                toast: document.getElementById('ar-toast').innerHTML}; }

  /* the assistant's form: nothing selected, ids passed as args, order honoured */
  clear();
  { const a = mk(0, 0), b = mk(1, 0); arSelect([]);
    arTool('bool_s', {a: b.id, b: a.id});          /* B minus A, the mirror of R.subtract */
    R.args = shot(); }

  /* ONE arPush(), called BEFORE the edit: one undo brings both operands back */
  clear();
  { const a = mk(0, 0), b = mk(1, 0); arSelect([a.id, b.id]); arTool('bool_s');
    const after = AR.objs.length; arUndo();
    R.undo = {after: after, back: AR.objs.length, kinds: AR.objs.map(o => o.kind)}; }

  /* the >20000-triangle cap refuses rather than hanging the tab */
  clear();
  { const a = arNewObj('sphere', {r: 1, seg: 210}, 0, 0, 0), b = mk(0, 0);
    R.capTris = tris(a);
    arSelect([a.id, b.id]); arTool('bool_u');
    R.cap = {n: AR.objs.length, kinds: AR.objs.map(o => o.kind),
             toast: document.getElementById('ar-toast').innerHTML}; }

  /* the WeakMap cache: a rebuild of an unchanged record does not re-cut */
  clear();
  { const a = mk(0, 0), b = mk(1, 0); arSelect([a.id, b.id]); arTool('bool_s');
    const rec = AR.objs[0], first = AR_SOLIDS_BOOLEAN.lastMs;
    arRebuild(rec); const second = AR_SOLIDS_BOOLEAN.lastMs;
    rec.p.op = 'union'; arRebuild(rec); const third = AR_SOLIDS_BOOLEAN.lastMs;
    R.cache = {first: first, second: second, third: third, tris: tris(rec)}; }

  clear();
  return R;
}"""
r = browser_eval(JS)
v = r['value'] or {}
check('no page errors while the three icons ran', not r['errors'], r['errors'])

u = v.get('union') or {}
check(
    'Union replaces both solids with ONE csg record',
    u.get('n') == 1 and u.get('kind') == 'csg' and (u.get('p') or {}).get('op') == 'union',
    u,
)
check(
    'Union spans both boxes (bbox 3 x 2 x 2 from x=-1)', u.get('size') == [3, 2, 2] and u.get('min') == [-1, 0, -1], u
)
check('Union is real geometry, not the 12-triangle marker cube', (u.get('tris') or 0) > 12, u)
check('the result is selected and keeps operand A material', u.get('sel') == [u.get('id')], u)

s = v.get('subtract') or {}
check(
    'Subtract leaves ONE csg record with op=subtract',
    s.get('n') == 1 and s.get('kind') == 'csg' and (s.get('p') or {}).get('op') == 'subtract',
    s,
)
check(
    'Subtract is the FIRST box minus the overlap (bbox 1 x 2 x 2 from x=-1)',
    s.get('size') == [1, 2, 2] and s.get('min') == [-1, 0, -1],
    s,
)
check(
    'the csg record stores the operands as PARAMETERS, b relative to a',
    ((s.get('p') or {}).get('a') or {}).get('kind') == 'box'
    and ((s.get('p') or {}).get('a') or {}).get('p') == {'w': 2, 'h': 2, 'd': 2}
    and ((s.get('p') or {}).get('b') or {}).get('x') == 1
    and ((s.get('p') or {}).get('a') or {}).get('x') == 0,
    s.get('p'),
)
check('the cut was measured onto the record (meta.csg_ms)', isinstance(s.get('ms'), int), s.get('ms'))

it = v.get('intersect') or {}
check(
    'Intersect keeps only the shared volume (bbox 1 x 2 x 2 from x=0)',
    it.get('n') == 1
    and (it.get('p') or {}).get('op') == 'intersect'
    and it.get('size') == [1, 2, 2]
    and it.get('min') == [0, 0, -1],
    it,
)

h = v.get('hollow') or {}
check(
    'subtracting a strictly interior box keeps the outer bbox and adds faces (a cavity)',
    h.get('n') == 1 and h.get('size') == [2, 2, 2] and h.get('min') == [-1, 0, -1] and (h.get('tris') or 0) > 12,
    h,
)

e = v.get('empty') or {}
check(
    'two solids that do not overlap intersect to nothing (an empty result, not a marker cube)',
    e.get('n') == 1 and e.get('kind') == 'csg' and e.get('tris') == 0,
    e,
)

rf = v.get('refuse') or {}
check(
    'with one object selected the icon refuses and changes nothing',
    rf.get('n') == 1 and rf.get('kind') == 'box' and 'Select two solids' in (rf.get('toast') or ''),
    rf,
)

ag = v.get('args') or {}
check(
    'arTool(id, {a, b}) honours the given order (B minus A -> bbox 1 x 2 x 2 from x=1)',
    ag.get('n') == 1 and ag.get('kind') == 'csg' and ag.get('size') == [1, 2, 2] and ag.get('min') == [1, 0, -1],
    ag,
)

un = v.get('undo') or {}
check(
    'one arPush() before the edit: one undo brings both operands back',
    un.get('after') == 1 and un.get('back') == 2 and un.get('kinds') == ['box', 'box'],
    un,
)

cp = v.get('cap') or {}
check(
    'an operand over 20000 triangles is refused, both objects survive',
    (v.get('capTris') or 0) > 20000
    and cp.get('n') == 2
    and cp.get('kinds') == ['sphere', 'box']
    and 'Too heavy to cut' in (cp.get('toast') or ''),
    {'capTris': v.get('capTris'), 'cap': cp},
)

ca = v.get('cache') or {}
check(
    'the WeakMap cache makes an unchanged rebuild free, and a changed op re-cuts',
    ca.get('second') == 0 and (ca.get('third') or 0) > 0 and (ca.get('tris') or 0) > 12,
    ca,
)
print(
    '  ..   CSG time: subtract %s ms, union %s ms, intersect %s ms, cached rebuild %s ms'
    % (s.get('ms'), u.get('ms'), it.get('ms'), ca.get('second')),
    flush=True,
)

# ── 3. the assistant: buttons + the server-side twin ─────────────────────────
for i in IDS:
    txt, d = assistant('press_button', {'id': i, 'args': {'a': 'o1', 'b': 'o2'}})
    check(
        'the assistant may press %s and its args reach the tab' % i,
        txt.startswith('pressed')
        and d.ui[-1]['args']['id'] == i
        and d.ui[-1]['args'].get('args') == {'a': 'o1', 'b': 'o2'},
        txt,
    )

check('the boolean() twin is registered as a tool', 'boolean' in tool_names(), tool_names()[-6:])

DOC = {
    'objects': [
        {'id': 'o1', 'kind': 'box', 'p': {'w': 2, 'h': 2, 'd': 2}, 'x': 0, 'y': 0, 'z': 0, 'mat': 'mat_timber'},
        {'id': 'o2', 'kind': 'cylinder', 'p': {'r': 0.6, 'h': 3}, 'x': 0.5, 'y': -0.5, 'z': 0},
    ]
}
txt, d = assistant('boolean', {'op': 'subtract', 'which_a': 'o1', 'which_b': 'o2'}, doc=DOC)
res = [o for o in d.objs if o['kind'] == 'csg']
check(
    'boolean() replaces both operands with one csg record',
    len(d.objs) == 1 and len(res) == 1 and res[0]['p']['op'] == 'subtract',
    (txt, d.objs),
)
check(
    'boolean() keeps both operands as parameters, b relative to a',
    res
    and res[0]['p']['a']['kind'] == 'box'
    and res[0]['p']['b']['kind'] == 'cylinder'
    and res[0]['p']['b']['x'] == 0.5
    and res[0]['p']['b']['y'] == -0.5
    and res[0]['p']['a']['x'] == 0,
    res and res[0]['p'],
)
check(
    'boolean() puts the result at operand a and keeps its material and selects it',
    res and res[0]['x'] == 0 and res[0]['y'] == 0 and res[0]['mat'] == 'mat_timber' and d.selected == [res[0]['id']],
    res and res[0],
)

txt2, d2 = assistant('boolean', {'op': 'union', 'which_a': 'o1', 'which_b': 'o1'}, doc=DOC)
check('boolean() refuses the same object on both sides', txt2.startswith('refused'), txt2)
txt3, _ = assistant('boolean', {'op': 'diff', 'which_a': 'o1', 'which_b': 'o2'}, doc=DOC)
check('boolean() refuses an op it does not have', txt3.startswith('refused'), txt3)
txt4, _ = assistant('boolean', {'op': 'union', 'which_a': 'o9', 'which_b': 'o2'}, doc=DOC)
check('boolean() refuses an operand that matches nothing', txt4.startswith('refused'), txt4)

# ── 4. the rail and Blender ──────────────────────────────────────────────────
check('the library rail lists the csg kind', rail_has(['csg']) == [], rail_has(['csg']))

DEFAULT_P = {
    'op': 'subtract',
    'a': {'kind': 'box', 'p': {'w': 2, 'h': 2, 'd': 2}, 'x': 0, 'y': 0, 'z': 0, 's': 1},
    'b': {'kind': 'cylinder', 'p': {'r': 0.6, 'h': 3, 'seg': 32}, 'x': 0, 'y': -0.5, 'z': 0, 's': 1},
}
bl = blender_kinds([{'kind': 'csg', 'p': DEFAULT_P}])
bc = bl.get('csg') or {}
check(
    'Blender builds the csg kind: a 2 m cube with a bore cut through it',
    bc.get('polys', 0) > 6
    and bc.get('size')
    and abs(bc['size'][0] - 2) < 0.05
    and abs(bc['size'][1] - 2) < 0.05
    and abs(bc['size'][2] - 2) < 0.05,
    bl,
)

finish()
