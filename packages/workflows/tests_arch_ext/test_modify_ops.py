# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_modify_ops.py — proves the three Modify icons Offset,
Fillet and Follow me are wired for real (arch_ext/modify_ops.js), that their
assistant twins do the same arithmetic (arch_assistant_ext/modify_ops.py), and
that the new `sweep` kind builds in the tab, shows in the rail and builds in
Blender (arch_blender_ext/modify_ops.py).

Two browser page loads only: icon_state() is one, and ONE browser_eval carries
every behavioural check. The modes are driven with click(null, {rec: ...}) —
the harness has no pointer, and the JS header documents that seam.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import (
    assistant,
    blender_kinds,
    browser_eval,
    check,  # noqa: E402
    finish,
    icon_state,
    kinds_of,
    rail_has,
    tool_names,
)

IDS = ['offset', 'fillet', 'follow']

# ── 1. the icons stopped being placeholders ─────────────────────────────────
st = icon_state(IDS)
for i in IDS:
    s = st.get(i) or {}
    check(
        '%s is a real icon (exists, no stub flag, no dashed border, no [placeholder] tip)' % i,
        s.get('exists') and not s.get('stub') and not s.get('dashed') and not s.get('tip_placeholder'),
        s,
    )

# ── 2. everything the three modes actually do, in ONE page ──────────────────
JS = r"""() => {
  const out = {errors: []};
  const wall = (x0, z0, x1, z1, p) => {
    const L = Math.hypot(x1 - x0, z1 - z0);
    const w = arNewObj('wall', Object.assign({len: L, h: 2.7, t: 0.24}, p || {}),
                       (x0 + x1) / 2, (z0 + z1) / 2, 0);
    w.ry = Math.atan2(-(z1 - z0), (x1 - x0)); arApplyTransform(w); return w;
  };
  const line = (x0, z0, x1, z1) => {
    const L = Math.hypot(x1 - x0, z1 - z0);
    const g = arNewObj('guide_line', {len: L}, (x0 + x1) / 2, (z0 + z1) / 2, 0);
    g.ry = Math.atan2(-(z1 - z0), (x1 - x0)); arApplyTransform(g); return g;
  };
  const ends = r => { const L = r.p.len / 2, dx = Math.cos(r.ry), dz = -Math.sin(r.ry);
    return [[r.x - dx * L, r.z - dz * L], [r.x + dx * L, r.z + dz * L]]; };
  const wipe = () => { AR.objs.slice().forEach(o => arRemove(o)); };

  /* the three ids are pointer MODES, and arming one must latch */
  arTool('offset'); out.armed_offset = AR.tool;
  arTool('fillet'); out.armed_fillet = AR.tool;
  arTool('follow'); out.armed_follow = AR.tool;
  out.hints = IDS_PLACEHOLDER.map(i => (AR_EXT.modes[i] && AR_EXT.modes[i].hint) ? AR_EXT.modes[i].hint(null) : '');
  arTool('select');

  /* ── OFFSET ───────────────────────────────────────────────────────────── */
  wipe();
  const u0 = AR.undo.length;
  const w1 = wall(-3, 0, 3, 0);                        /* along +X, ry = 0 */
  w1.meta = {layer: 'Party walls', tag: 'fire'};       /* per-record user data must survive the copy */
  AR_EXT.modes.offset.click(null, {rec: w1, distance: 1});
  const c1 = AR.objs[AR.objs.length - 1];
  out.offset_axis = {kind: c1.kind, x: c1.x, z: c1.z, len: c1.p.len, ry: c1.ry,
                     d: Math.hypot(c1.x - w1.x, c1.z - w1.z), sel: AR.sel.slice(),
                     pushed: AR.undo.length - u0,
                     meta: c1.meta, meta_shared: c1.meta === w1.meta};

  const w2 = wall(0, 0, 4 * Math.cos(0.7), -4 * Math.sin(0.7));   /* a wall at ry = 0.7 */
  AR_EXT.modes.offset.click(null, {rec: w2, distance: -2});
  const c2 = AR.objs[AR.objs.length - 1];
  const dxv = c2.x - w2.x, dzv = c2.z - w2.z, dirx = Math.cos(w2.ry), dirz = -Math.sin(w2.ry);
  out.offset_rot = {d: Math.hypot(dxv, dzv), dot: dxv * dirx + dzv * dirz, ry_same: Math.abs(c2.ry - w2.ry) < 1e-9};

  const ci = arNewObj('guide_circle', {r: 5}, 2, 2, 0);
  AR_EXT.modes.offset.click(null, {rec: ci, distance: 1.5});
  const c3 = AR.objs[AR.objs.length - 1];
  out.offset_circle = {kind: c3.kind, r: c3.p.r, x: c3.x, z: c3.z};

  const gp = arNewObj('guide_poly', {pts: [[-2, -2], [2, -2], [2, 2], [-2, 2]], closed: 1}, 0, 0, 0);
  AR_EXT.modes.offset.click(null, {rec: gp, distance: 0.5});
  const c4 = AR.objs[AR.objs.length - 1];
  out.offset_poly = {kind: c4.kind, pts: c4.p.pts, orig: gp.p.pts};

  const junk = arNewObj('slab', {w: 2, d: 2, t: 0.2}, 30, 30, 0);
  const before = AR.objs.length;
  AR_EXT.modes.offset.click(null, {rec: junk, distance: 1});
  out.offset_refuses = {added: AR.objs.length - before,
                        toast: document.getElementById('ar-toast').innerHTML};

  /* ── FILLET, sharp ─────────────────────────────────────────────────────── */
  wipe();
  let A = wall(0, 0, 10, 0), B = wall(11, 1, 11, 11);   /* corners 1 m apart: both must extend */
  const u1 = AR.undo.length;
  AR_EXT.modes.fillet.click(null, {rec: A});
  AR_EXT.modes.fillet.click(null, {rec: B, radius: 0});
  const ea = ends(A), eb = ends(B);
  let best = 1e9, bp = null;
  for (const p of ea) for (const q of eb) { const dd = Math.hypot(p[0] - q[0], p[1] - q[1]); if (dd < best) { best = dd; bp = [p, q]; } }
  out.fillet_sharp = {gap: best, corner: bp, lenA: A.p.len, lenB: B.p.len,
                      farA: ea.find(p => Math.hypot(p[0], p[1]) < 1e-6) || null,
                      farB: eb.find(p => Math.hypot(p[0] - 11, p[1] - 11) < 1e-6) || null,
                      arcs: AR.objs.filter(o => o.kind === 'wall_arc').length,
                      pushed: AR.undo.length - u1};

  /* ── FILLET, radius 1 ──────────────────────────────────────────────────── */
  wipe();
  A = wall(0, 0, 10, 0); B = wall(11, 1, 11, 11);
  const u2 = AR.undo.length;
  AR_EXT.modes.fillet.click(null, {rec: A});
  AR_EXT.modes.fillet.click(null, {rec: B, radius: 1});
  const arc = AR.objs.find(o => o.kind === 'wall_arc');
  const ea2 = ends(A), eb2 = ends(B);
  /* ExtrudeGeometry (curved_walls' wall_arc) is NOT indexed, so count positions too */
  let tris = 0; if (arc && arc.node) arc.node.traverse(m => { if (m.isMesh && m.geometry)
    tris += m.geometry.index ? m.geometry.index.count / 3
          : (m.geometry.attributes.position ? m.geometry.attributes.position.count / 3 : 0); });
  out.fillet_round = {
    have_wall_arc_geom: !!(AR_EXT.geom && AR_EXT.geom.wall_arc),
    arc: arc ? {x: arc.x, z: arc.z, r: arc.p.r, a0: arc.p.a0, a1: arc.p.a1, h: arc.p.h, tris: tris} : null,
    lenA: A.p.len, lenB: B.p.len,
    /* the arc's two ends, from its own parameters, must land on the wall ends */
    endA: arc ? [arc.x + arc.p.r * Math.cos(arc.p.a0 * Math.PI / 180), arc.z - arc.p.r * Math.sin(arc.p.a0 * Math.PI / 180)] : null,
    endB: arc ? [arc.x + arc.p.r * Math.cos(arc.p.a1 * Math.PI / 180), arc.z - arc.p.r * Math.sin(arc.p.a1 * Math.PI / 180)] : null,
    tipA: ea2[1], tipB: eb2[1], pushed: AR.undo.length - u2, sel: AR.sel.length};

  /* the sharp fallback: hide wall_arc from the mode and fillet again */
  wipe();
  const keep = AR_EXT.geom.wall_arc; delete AR_EXT.geom.wall_arc;
  /* the warn toast is overwritten by the final one, so collect every toast of the phase */
  const said = [], realToast = window.arToast;
  window.arToast = function(){ said.push(String(arguments[0])); return realToast.apply(this, arguments); };
  const A2 = wall(0, 0, 10, 0), B2 = wall(11, 1, 11, 11);
  AR_EXT.modes.fillet.click(null, {rec: A2});
  AR_EXT.modes.fillet.click(null, {rec: B2, radius: 1});
  window.arToast = realToast;
  out.fillet_fallback = {arcs: AR.objs.filter(o => o.kind === 'wall_arc').length,
                         gap: Math.hypot(ends(A2)[1][0] - ends(B2)[1][0], ends(A2)[1][1] - ends(B2)[1][1]),
                         toasts: said};
  AR_EXT.geom.wall_arc = keep;

  /* a radius bigger than the walls: the corner stays SHARP and NEITHER wall may
     be left half pulled back (the earlier version shortened A, then found B too
     short and gave up, leaving a gap) */
  wipe();
  const said2 = [], realToast2 = window.arToast;
  window.arToast = function(){ said2.push(String(arguments[0])); return realToast2.apply(this, arguments); };
  const A3 = wall(0, 0, 10, 0), B3 = wall(11, 1, 11, 11);
  AR_EXT.modes.fillet.click(null, {rec: A3});
  AR_EXT.modes.fillet.click(null, {rec: B3, radius: 20});
  window.arToast = realToast2;
  out.fillet_toobig = {arcs: AR.objs.filter(o => o.kind === 'wall_arc').length,
                       lenA: A3.p.len, lenB: B3.p.len,
                       gap: Math.hypot(ends(A3)[1][0] - ends(B3)[1][0], ends(A3)[1][1] - ends(B3)[1][1]),
                       toasts: said2};

  /* a wall that would collapse onto the corner must be refused BEFORE anything
     moves: no undo step and the OTHER wall untouched too (the earlier version
     evaluated both trims, so the second wall was moved and then disowned) */
  wipe();
  const A4 = wall(11, 0, 11, 0);                    /* degenerate: both ends on the corner */
  const B4 = wall(11, 1, 11, 11);
  const beforeB = {len: B4.p.len, x: B4.x, z: B4.z};
  const u4 = AR.undo.length;
  AR_EXT.modes.fillet.click(null, {rec: A4});
  AR_EXT.modes.fillet.click(null, {rec: B4, radius: 0});
  out.fillet_collapse = {pushed: AR.undo.length - u4,
                         b_same: B4.p.len === beforeB.len && B4.x === beforeB.x && B4.z === beforeB.z,
                         b: {len: B4.p.len, x: B4.x, z: B4.z}, was: beforeB,
                         toast: document.getElementById('ar-toast').innerHTML};

  /* ── FOLLOW ME ─────────────────────────────────────────────────────────── */
  wipe();
  const l1 = line(0, 0, 4, 0), l2 = line(4, 0, 4, 3), l3 = line(4, 3, 8, 3);
  const u3 = AR.undo.length;
  AR_EXT.modes.follow.click(null, {rec: l1, w: 0.3, h: 0.4});
  const sw = AR.objs.find(o => o.kind === 'sweep');
  let legs = 0, sz = null, mny = null;
  if (sw && sw.node) {
    sw.node.traverse(m => { if (m.isMesh && m.geometry) legs++; });
    const bb = new THREE.Box3().expandByObject(sw.node), s = bb.getSize(new THREE.Vector3());
    sz = [s.x, s.y, s.z].map(v => Math.round(v * 1000) / 1000);
    mny = Math.round(bb.min.y * 1000) / 1000;
  }
  out.follow = sw ? {x: sw.x, z: sw.z, pts: sw.p.pts, w: sw.p.w, h: sw.p.h, closed: sw.p.closed,
                     meshes: legs, size: sz, min_y: mny, label: arKindLabel('sweep'),
                     pushed: AR.undo.length - u3, sel: AR.sel.slice()} : null;

  /* a closed path: the sweep must carry closed:1 and one more leg */
  wipe();
  const s1 = line(0, 0, 4, 0), s2 = line(4, 0, 4, 4), s3 = line(4, 4, 0, 4), s4 = line(0, 4, 0, 0);
  AR_EXT.modes.follow.click(null, {rec: s1, w: 0.2, h: 0.2});
  const sw2 = AR.objs.find(o => o.kind === 'sweep');
  let legs2 = 0; if (sw2 && sw2.node) sw2.node.traverse(m => { if (m.isMesh && m.geometry) legs2++; });
  out.follow_closed = sw2 ? {pts: sw2.p.pts.length, closed: sw2.p.closed, meshes: legs2} : null;

  /* a wall is a path too */
  wipe();
  const wp = wall(0, 0, 6, 0);
  AR_EXT.modes.follow.click(null, {rec: wp, w: 0.25, h: 0.1});
  const sw3 = AR.objs.find(o => o.kind === 'sweep');
  out.follow_wall = sw3 ? {pts: sw3.p.pts, w: sw3.p.w, h: sw3.p.h} : null;

  wipe();
  return out;
}""".replace('IDS_PLACEHOLDER', repr(IDS).replace("'", '"'))

r = browser_eval(JS)
v = r['value']
check(
    'no page errors while driving the three modes',
    not r['errors'] and not r['console'],
    (r['errors'], r['console'][:3]),
)
check(
    'the three ids arm as pointer modes (AR.tool latches on each)',
    v['armed_offset'] == 'offset' and v['armed_fillet'] == 'fillet' and v['armed_follow'] == 'follow',
    v['armed_offset'],
)
check('each mode gives its own hint line', all(len(h) > 20 for h in v['hints']), v['hints'])

o = v['offset_axis']
check(
    'offset: one parallel wall copy, exactly the distance away, same length and rotation',
    o['kind'] == 'wall'
    and abs(o['d'] - 1) < 1e-6
    and abs(o['x']) < 1e-9
    and abs(o['z'] - 1) < 1e-9
    and abs(o['len'] - 6) < 1e-9
    and abs(o['ry']) < 1e-9,
    o,
)
check('offset selects the new record and pushed exactly one undo step', len(o['sel']) == 1 and o['pushed'] == 1, o)
check(
    'the offset copy carries the original record meta, as its own object',
    o['meta'] == {'layer': 'Party walls', 'tag': 'fire'} and not o['meta_shared'],
    o,
)
o2 = v['offset_rot']
check(
    'offset moves along the wall NORMAL, not some other vector (perpendicular, |d| = 2, angle kept)',
    abs(o2['d'] - 2) < 1e-6 and abs(o2['dot']) < 1e-6 and o2['ry_same'],
    o2,
)
o3 = v['offset_circle']
check(
    'offset of a guide circle grows its radius and keeps its centre',
    o3['kind'] == 'guide_circle' and abs(o3['r'] - 6.5) < 1e-9 and abs(o3['x'] - 2) < 1e-9 and abs(o3['z'] - 2) < 1e-9,
    o3,
)
o4 = v['offset_poly']
check(
    'offset of a point list outsets the polygon by the distance (2 m square -> 2.5 m)',
    len(o4['pts']) == 4
    and all(abs(abs(c) - 2.5) < 1e-4 for p in o4['pts'] for c in p)
    and o4['orig'] == [[-2, -2], [2, -2], [2, 2], [-2, 2]],
    o4,
)
o5 = v['offset_refuses']
check(
    'offset refuses a record with no edge, adds nothing and says why',
    o5['added'] == 0 and 'offset' in o5['toast'].lower(),
    o5,
)

f = v['fillet_sharp']
check(
    'fillet radius 0: the two walls now share the corner within 1 cm',
    f['gap'] < 0.01 and abs(f['corner'][0][0] - 11) < 1e-6 and abs(f['corner'][0][1]) < 1e-6,
    f,
)
check(
    'fillet radius 0 extends both walls and leaves both far ends where they were',
    abs(f['lenA'] - 11) < 1e-6 and abs(f['lenB'] - 11) < 1e-6 and f['farA'] and f['farB'],
    f,
)
check('fillet radius 0 makes no arc and pushed exactly one undo step', f['arcs'] == 0 and f['pushed'] == 1, f)

g = v['fillet_round']
check(
    'fillet radius 1 added ONE wall_arc with real geometry (curved_walls is loaded)',
    g['have_wall_arc_geom'] and g['arc'] and abs(g['arc']['r'] - 1) < 1e-9 and g['arc']['tris'] > 4,
    g,
)
check(
    'the arc sits at the fillet centre (10, 1) and spans the 90 deg turn',
    g['arc']
    and abs(g['arc']['x'] - 10) < 1e-4
    and abs(g['arc']['z'] - 1) < 1e-4
    and abs(abs(g['arc']['a1'] - g['arc']['a0']) - 90) < 1e-3,
    g,
)
check(
    'both walls were pulled back by the tangent length r/tan(theta/2) = 1 m',
    abs(g['lenA'] - 10) < 1e-4 and abs(g['lenB'] - 10) < 1e-4,
    g,
)
check(
    'the arc ends land on the trimmed wall ends (a continuous, rounded corner)',
    g['arc'] and math.dist(g['endA'], g['tipA']) < 0.01 and math.dist(g['endB'], g['tipB']) < 0.01,
    g,
)
check(
    'fillet radius 1 still pushed exactly one undo step and selected wall+wall+arc',
    g['pushed'] == 1 and g['sel'] == 3,
    g,
)

fb = v['fillet_fallback']
check(
    'without curved_walls the fillet falls back to a SHARP corner and toasts why',
    fb['arcs'] == 0 and fb['gap'] < 0.01 and any('curved_walls' in t for t in fb['toasts']),
    fb,
)

tb = v['fillet_toobig']
check(
    'a radius bigger than the walls leaves a SHARP corner with NEITHER wall half pulled back',
    tb['arcs'] == 0
    and tb['gap'] < 0.01
    and abs(tb['lenA'] - 11) < 1e-6
    and abs(tb['lenB'] - 11) < 1e-6
    and any('bigger than the walls' in t for t in tb['toasts']),
    tb,
)
fc = v['fillet_collapse']
check(
    'a wall that would collapse onto the corner is refused before anything moves (no undo step, other wall untouched)',
    fc['pushed'] == 0 and fc['b_same'] and 'collapse' in fc['toast'].lower(),
    fc,
)

s = v['follow']
check(
    'follow me walked the guide-line chain: 4 points, 3 legs, one mesh per leg',
    s and len(s['pts']) == 4 and s['meshes'] == 3 and s['closed'] == 0,
    s,
)
check(
    'the sweep sits at the path centroid and stores the path LOCAL to it',
    s
    and abs(s['x'] - 4) < 1e-6
    and abs(s['z'] - 1.5) < 1e-6
    and s['pts'] == [[-4, -1.5], [0, -1.5], [0, 1.5], [4, 1.5]],
    s,
)
check(
    'the sweep geometry is the profile carried along the path (8 x 0.4 x 3.3 m, base at y=0)',
    s
    and abs(s['size'][0] - 8) < 1e-3
    and abs(s['size'][1] - 0.4) < 1e-3
    and abs(s['size'][2] - 3.3) < 1e-3
    and abs(s['min_y']) < 1e-3,
    s,
)
check(
    'the sweep kind has a label and follow pushed exactly one undo step',
    s and s['label'] == 'Swept profile' and s['pushed'] == 1 and len(s['sel']) == 1,
    s,
)
sc = v['follow_closed']
check(
    'a closed chain gives closed:1 and one leg per side (4 points, 4 meshes)',
    sc and sc['pts'] == 4 and sc['closed'] == 1 and sc['meshes'] == 4,
    sc,
)
sw = v['follow_wall']
check(
    'a wall is a path too: its two ends become the sweep',
    sw and sw['pts'] == [[-3, 0], [3, 0]] and abs(sw['w'] - 0.25) < 1e-9 and abs(sw['h'] - 0.1) < 1e-9,
    sw,
)

# ── 3. the assistant twins ──────────────────────────────────────────────────
names = tool_names()
check(
    'the three twins are assistant tools',
    all(n in names for n in ('offset_wall', 'fillet_walls', 'sweep_profile')),
    [n for n in ('offset_wall', 'fillet_walls', 'sweep_profile') if n not in names],
)

DOC = {
    'objects': [
        {'id': 'o1', 'kind': 'wall', 'p': {'len': 10, 'h': 2.7, 't': 0.24}, 'x': 5, 'z': 0, 'y': 0, 'ry': 0},
        {
            'id': 'o2',
            'kind': 'wall',
            'p': {'len': 10, 'h': 2.7, 't': 0.24},
            'x': 11,
            'z': 6,
            'y': 0,
            'ry': -math.pi / 2,
        },
    ]
}
txt, d = assistant('offset_wall', {'which': ['o1'], 'distance': 1}, doc=DOC)
new = [o for o in d.objs if o['id'] in d.added]
check(
    'offset_wall drops one copy exactly 1 m along the wall normal',
    len(new) == 1
    and abs(new[0]['x'] - 5) < 1e-6
    and abs(new[0]['z'] - 1) < 1e-6
    and abs(new[0]['p']['len'] - 10) < 1e-9,
    (txt, new),
)
txt, _ = assistant('offset_wall', {'which': 'all', 'distance': 0}, doc=DOC)
check('offset_wall refuses a zero distance', txt.startswith('refused'), txt)

META_DOC = {'objects': [dict(DOC['objects'][0], meta={'layer': 'Party walls'})]}
txt, d = assistant('offset_wall', {'which': ['o1'], 'distance': 1}, doc=META_DOC)
cp = [o for o in d.objs if o['id'] in d.added][0]
check(
    'offset_wall carries record meta onto the copy, as its own dict',
    cp['meta'] == {'layer': 'Party walls'} and cp['meta'] is not d.find('o1')['meta'],
    (txt, cp),
)

txt, d = assistant('fillet_walls', {'wall_a': 'o1', 'wall_b': 'o2', 'radius': 0}, doc=DOC)
A, B = d.find('o1'), d.find('o2')


def _ends(r):
    L = r['p']['len'] / 2
    dx, dz = math.cos(r['ry']), -math.sin(r['ry'])
    return [(r['x'] - dx * L, r['z'] - dz * L), (r['x'] + dx * L, r['z'] + dz * L)]


gap = min(math.dist(p, q) for p in _ends(A) for q in _ends(B))
check(
    'fillet_walls (radius 0) brings the two walls to one corner within 1 cm',
    gap < 0.01 and abs(A['p']['len'] - 11) < 1e-4 and abs(B['p']['len'] - 11) < 1e-4,
    (txt, gap, A, B),
)
txt, d = assistant('fillet_walls', {'wall_a': 'o1', 'wall_b': 'o2', 'radius': 1}, doc=DOC)
arcs = [o for o in d.objs if o['kind'] == 'wall_arc']
check(
    'fillet_walls (radius 1) adds one wall_arc at (10, 1) and trims both walls to 10 m',
    len(arcs) == 1
    and abs(arcs[0]['x'] - 10) < 1e-4
    and abs(arcs[0]['z'] - 1) < 1e-4
    and abs(arcs[0]['p']['r'] - 1) < 1e-9
    and abs(d.find('o1')['p']['len'] - 10) < 1e-4
    and abs(d.find('o2')['p']['len'] - 10) < 1e-4,
    (txt, arcs),
)
txt, _ = assistant('fillet_walls', {'wall_a': 'o1', 'wall_b': 'o1'}, doc=DOC)
check('fillet_walls refuses one wall twice', txt.startswith('refused'), txt)

txt, d = assistant('fillet_walls', {'wall_a': 'o1', 'wall_b': 'o2', 'radius': 20}, doc=DOC)
check(
    'fillet_walls with a radius bigger than the walls says so and leaves both at the sharp corner',
    'left sharp' in txt
    and not [o for o in d.objs if o['kind'] == 'wall_arc']
    and abs(d.find('o1')['p']['len'] - 11) < 1e-4
    and abs(d.find('o2')['p']['len'] - 11) < 1e-4,
    txt,
)

DEGEN = {
    'objects': [
        {'id': 'o1', 'kind': 'wall', 'p': {'len': 0, 'h': 2.7, 't': 0.24}, 'x': 11, 'z': 0, 'y': 0, 'ry': 0},
        {
            'id': 'o2',
            'kind': 'wall',
            'p': {'len': 10, 'h': 2.7, 't': 0.24},
            'x': 11,
            'z': 6,
            'y': 0,
            'ry': -math.pi / 2,
        },
    ]
}
txt, d = assistant('fillet_walls', {'wall_a': 'o1', 'wall_b': 'o2'}, doc=DEGEN)
check(
    'fillet_walls refuses a collapsing wall WITHOUT having moved the other one',
    txt.startswith('refused') and abs(d.find('o2')['p']['len'] - 10) < 1e-9 and abs(d.find('o2')['z'] - 6) < 1e-9,
    (txt, d.find('o2')),
)

txt, d = assistant('sweep_profile', {'cells': ['C4', 'L4', 'L13'], 'width': 0.3, 'height': 0.15})
sweeps = [o for o in d.objs if o['kind'] == 'sweep']
check(
    'sweep_profile adds one sweep with 3 path points and the profile given',
    kinds_of(d).get('sweep') == 1
    and len(sweeps[0]['p']['pts']) == 3
    and abs(sweeps[0]['p']['w'] - 0.3) < 1e-9
    and abs(sweeps[0]['p']['h'] - 0.15) < 1e-9,
    (txt, sweeps),
)
txt, _ = assistant('sweep_profile', {'cells': ['C4']})
check('sweep_profile refuses a path of one cell', txt.startswith('refused'), txt)

check('the rail lists the sweep kind', rail_has(['sweep']) == [], rail_has(['sweep']))

# ── 4. Blender builds the sweep ─────────────────────────────────────────────
bl = blender_kinds(
    [{'kind': 'sweep', 'p': {'pts': [[-4, -1.5], [0, -1.5], [0, 1.5], [4, 1.5]], 'w': 0.3, 'h': 0.4, 'closed': 0}}]
)
b = bl.get('sweep') or {}
check(
    'blender builds the sweep: 3 boxes (18 faces, 24 verts) sized 8 x 0.4 x 3.3 m, base at 0',
    b.get('polys') == 18
    and b.get('verts') == 24
    and b.get('size')
    and abs(b['size'][0] - 8) < 1e-2
    and abs(b['size'][1] - 0.4) < 1e-2
    and abs(b['size'][2] - 3.3) < 1e-2
    and b.get('min_y') is not None
    and abs(b['min_y']) < 1e-3,
    b,
)

finish()
