# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_draw_guides.py — the proof for the draw_guides family.

Three side-bar icons (Arc, Polygon, Freehand) were placeholders; each is now a
POINTER MODE that produces a guide record. What is proved here:

  · the three icons carry no placeholder mark in the live DOM;
  · arming each mode and driving it with the clicks/moves its tooltip promises
    leaves a guide_arc / guide_poly / guide_path record in the document, whose
    p rebuilds through arGeom into a LINE part of the right size — the arc's
    bbox spans the chord, the square is 4 x 4 m, the stroke is decimated;
  · one arPush per guide, Esc drops a half-finished draft, Enter closes a
    polygon and a typed digit gives a regular n-gon;
  · the three assistant twins draw the same kinds from cell names;
  · the kinds are on the library rail and declared VOID for Blender.

Two browser_eval calls in total (icon_state is one of them).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import (
    assistant,
    browser_eval,
    check,
    finish,  # noqa: E402
    icon_state,
    kinds_of,
    rail_has,
)

import zyg_workflows.arch_assistant_ext.draw_guides as G  # noqa: E402
import zyg_workflows.arch_blender_ext.draw_guides as B  # noqa: E402

ICONS = ['arc', 'poly', 'free']

# ── 1. the icons are no longer placeholders ─────────────────────────────────
st = icon_state(ICONS)
for i in ICONS:
    s = st.get(i) or {}
    check(
        'icon %-5s is in the side bar and is no longer a placeholder (stub=%s dashed=%s tip_placeholder=%s)'
        % (i, s.get('stub'), s.get('dashed'), s.get('tip_placeholder')),
        s.get('exists') and not s.get('stub') and not s.get('dashed') and not s.get('tip_placeholder'),
        s,
    )

# ── 2. drive all three modes in the live tab ────────────────────────────────
r = browser_eval(r"""() => {
  const O = {};
  const E = (b) => ({shiftKey: false, buttons: b || 0});
  const P = (x, z) => ({x: x, z: z, y: 0});
  const last = () => AR.objs[AR.objs.length - 1];
  const shape = (kind, p) => {
    const parts = arGeom(kind, p);
    const g = parts[0].g; g.computeBoundingBox();
    const bb = g.boundingBox;
    return {parts: parts.length, line: !!parts[0].line, verts: g.attributes.position.count,
            size: [bb.max.x - bb.min.x, bb.max.y - bb.min.y, bb.max.z - bb.min.z].map(v => Math.round(v * 1000) / 1000)};
  };
  const node = (rec) => { let lines = 0, meshes = 0;
    rec.node.traverse(o => { if (o.isMesh) meshes++; else if (o.isLine) lines++; });
    return {lines: lines, meshes: meshes}; };

  /* ── Arc: three clicks make one guide_arc ── */
  arCancelDraft(); arToolApply('arc');
  O.arcHint = AR_EXT.modes.arc.hint(null);
  let n0 = AR.objs.length, u0 = AR.undo.length;
  AR_EXT.modes.arc.click(P(0, 0), E(0), null);
  AR_EXT.modes.arc.click(P(6, 0), E(0), null);
  O.arcAfter2 = AR.objs.length - n0;                       /* still drafting: 0 */
  O.arcRubber = !!(AR.rubber && AR.rubber.visible === false) || true;
  AR_EXT.modes.arc.click(P(3, -3), E(0), null);
  const arc = last();
  O.arc = {kind: arc.kind, p: arc.p, x: arc.x, z: arc.z, y: arc.y, mat: arc.mat, name: arc.name,
           made: AR.objs.length - n0, pushes: AR.undo.length - u0, sel: AR.sel.slice()};
  O.arcGeom = shape('guide_arc', arc.p);
  O.arcNode = node(arc);

  /* Esc drops a half-finished arc */
  n0 = AR.objs.length;
  AR_EXT.modes.arc.click(P(30, 30), E(0), null);
  AR_EXT.modes.arc.click(P(34, 30), E(0), null);
  arCancelDraft();
  AR_EXT.modes.arc.click(P(38, 30), E(0), null);           /* a fresh first point, not a third */
  O.arcEscaped = AR.objs.length - n0;                      /* 0 */
  arCancelDraft();

  /* ── Polygon: four clicks + Enter close a square ── */
  arToolApply('poly');
  O.polyHint = AR_EXT.modes.poly.hint(null);
  n0 = AR.objs.length; u0 = AR.undo.length;
  const M = AR_EXT.modes.poly;
  M.click(P(0, 0), E(0), null); M.click(P(4, 0), E(0), null);
  M.click(P(4, 4), E(0), null); M.click(P(0, 4), E(0), null);
  O.polyAfter4 = AR.objs.length - n0;                      /* still drafting: 0 */
  O.polyEnter = M.key({key: 'Enter'});                     /* the mode swallows Enter */
  const poly = last();
  O.poly = {kind: poly.kind, pts: poly.p.pts, x: poly.x, z: poly.z, mat: poly.mat, name: poly.name,
            made: AR.objs.length - n0, pushes: AR.undo.length - u0};
  O.polyGeom = shape('guide_poly', poly.p);
  O.polyNode = node(poly);

  /* clicking the FIRST corner closes it too */
  n0 = AR.objs.length;
  M.click(P(50, 0), E(0), null); M.click(P(53, 0), E(0), null); M.click(P(53, 3), E(0), null);
  M.click(P(50.05, 0), E(0), null);                        /* within 0.25 m of the first */
  O.polyClickClose = {made: AR.objs.length - n0, pts: last().p.pts.length};

  /* a typed digit gives a regular n-gon from centre + rim */
  n0 = AR.objs.length;
  O.polyDigit = M.key({key: '6'});
  O.polyN = AR._drawGuidesN;
  M.click(P(20, 0), E(0), null); M.click(P(23, 0), E(0), null);
  const hex = last();
  O.hex = {kind: hex.kind, n: hex.p.pts.length, x: hex.x, z: hex.z, made: AR.objs.length - n0,
           /* pts[0] and pts[3] are opposite corners, so half that span is the radius */
           r: Math.round(Math.hypot(hex.p.pts[0][0] - hex.p.pts[3][0], hex.p.pts[0][1] - hex.p.pts[3][1]) * 500) / 1000,
           reset: AR._drawGuidesN};
  arCancelDraft();

  /* ── Freehand: moves with the button down, finished by a click ── */
  arToolApply('free');
  O.freeHint = AR_EXT.modes.free.hint(null);
  n0 = AR.objs.length; u0 = AR.undo.length;
  const F = AR_EXT.modes.free;
  /* 61 samples 0.04 m apart: every third one clears the 0.1 m floor, so the
     stroke keeps 21 points 0.12 m apart — every gap at least 0.1 m, none of
     them a sample. */
  for (let i = 0; i <= 60; i++) F.move(P(i * 0.04, 0), E(1), null);
  O.freeDuring = AR.objs.length - n0;                      /* still drawing: 0 */
  F.click(P(2.45, 0), E(0), null);
  const path = last();
  let gmin = 9e9, gmax = 0;
  for (let i = 1; i < path.p.pts.length; i++){
    const g = Math.hypot(path.p.pts[i][0] - path.p.pts[i - 1][0], path.p.pts[i][1] - path.p.pts[i - 1][1]);
    gmin = Math.min(gmin, g); gmax = Math.max(gmax, g);
  }
  O.free = {kind: path.kind, n: path.p.pts.length, first: path.p.pts[0], last: path.p.pts[path.p.pts.length - 1],
            x: path.x, z: path.z, mat: path.mat, name: path.name, gmin: gmin, gmax: gmax,
            made: AR.objs.length - n0, pushes: AR.undo.length - u0};
  O.freeGeom = shape('guide_path', path.p);
  O.freeNode = node(path);

  /* a real pointer RELEASE closes a stroke too (a drag never reaches arClick) */
  n0 = AR.objs.length;
  for (let i = 0; i < 8; i++) F.move(P(60 + i * 0.5, 0), E(1), null);
  AR.renderer.domElement.dispatchEvent(new PointerEvent('pointerup', {bubbles: true}));
  O.freeRelease = {made: AR.objs.length - n0, kind: last().kind, n: last().p.pts.length};

  arCancelDraft(); arToolApply('select');
  O.labels = ['guide_arc', 'guide_poly', 'guide_path'].map(k => arKindLabel(k));
  O.toast = document.getElementById('ar-toast').innerHTML;
  O.docKinds = AR.objs.map(o => o.kind).filter(k => k.indexOf('guide_') === 0);
  return O;
}""")
v = r['value']
check('no page errors while drawing the three guides', not r['errors'], r['errors'])

check(
    'Arc: three clicks make ONE guide_arc record, at the FIRST click, selected, behind one arPush',
    v['arc']['kind'] == 'guide_arc'
    and v['arc']['made'] == 1
    and v['arc']['pushes'] == 1
    and v['arc']['x'] == 0
    and v['arc']['z'] == 0
    and v['arc']['sel']
    and v['arcAfter2'] == 0,
    v['arc'],
)
check(
    'Arc: p holds the three points in the record local frame (x1=z1=0)',
    v['arc']['p'] == {'x1': 0, 'z1': 0, 'x2': 6, 'z2': 0, 'x3': 3, 'z3': -3},
    v['arc']['p'],
)
check(
    'Arc: p rebuilds through arGeom into a LINE of 49 points whose bbox spans the 6 m chord and the 3 m rise',
    v['arcGeom']['line']
    and v['arcGeom']['verts'] == 49
    and abs(v['arcGeom']['size'][0] - 6.0) < 0.02
    and abs(v['arcGeom']['size'][2] - 3.0) < 0.02
    and v['arcGeom']['size'][1] == 0,
    v['arcGeom'],
)
check(
    'Arc: the record draws as lines only — no mesh, so no marker cube',
    v['arcNode']['lines'] == 1 and v['arcNode']['meshes'] == 0,
    v['arcNode'],
)
check('Arc: guides take the guide material', v['arc']['mat'] == 'mat_glass', v['arc']['mat'])
check(
    'Arc: Esc cancels a half-finished arc — the next click starts again, nothing was drawn',
    v['arcEscaped'] == 0,
    v['arcEscaped'],
)
check(
    'Arc: the hint says what to click', 'arc' in v['arcHint'].lower() and 'start' in v['arcHint'].lower(), v['arcHint']
)

check(
    'Polygon: four clicks then Enter make ONE closed guide_poly, behind one arPush',
    v['poly']['kind'] == 'guide_poly'
    and v['poly']['made'] == 1
    and v['poly']['pushes'] == 1
    and v['polyAfter4'] == 0
    and v['polyEnter'] is True,
    v['poly'],
)
check(
    'Polygon: pts are the four corners local to the first one',
    v['poly']['pts'] == [[0, 0], [4, 0], [4, 4], [0, 4]] and v['poly']['x'] == 0 and v['poly']['z'] == 0,
    v['poly'],
)
check(
    'Polygon: it rebuilds as a CLOSED ring of 4 line segments, 4 x 4 m',
    v['polyGeom']['line']
    and v['polyGeom']['verts'] == 8
    and v['polyGeom']['size'][0] == 4
    and v['polyGeom']['size'][2] == 4,
    v['polyGeom'],
)
check(
    'Polygon: the record draws as lines only',
    v['polyNode']['lines'] == 1 and v['polyNode']['meshes'] == 0,
    v['polyNode'],
)
check(
    'Polygon: clicking the FIRST corner closes it as well as Enter',
    v['polyClickClose']['made'] == 1 and v['polyClickClose']['pts'] == 3,
    v['polyClickClose'],
)
check(
    'Polygon: typing 6 sets AR._drawGuidesN, then centre + rim give a regular hexagon of radius 3 m',
    v['polyDigit'] is True
    and v['polyN'] == 6
    and v['hex']['kind'] == 'guide_poly'
    and v['hex']['n'] == 6
    and v['hex']['made'] == 1
    and v['hex']['x'] == 23
    and v['hex']['z'] == 0
    and abs(v['hex']['r'] - 3.0) < 0.01
    and v['hex']['reset'] == 0,
    v['hex'],
)
check(
    'Polygon: the hint offers both the corner-by-corner and the typed regular way',
    'corner' in v['polyHint'].lower() and '3' in v['polyHint'] and '12' in v['polyHint'],
    v['polyHint'],
)

check(
    'Freehand: 61 moves with the button down then a click make ONE guide_path, behind one arPush',
    v['free']['kind'] == 'guide_path' and v['free']['made'] == 1 and v['free']['pushes'] == 1 and v['freeDuring'] == 0,
    v['free'],
)
check(
    'Freehand: the stroke is decimated — 61 samples 0.04 m apart become 21 points, no gap under 0.1 m',
    v['free']['n'] == 21
    and v['free']['first'] == [0, 0]
    and abs(v['free']['last'][0] - 2.4) < 1e-6
    and v['free']['gmin'] >= 0.1 - 1e-9
    and v['free']['gmax'] < 0.2,
    v['free'],
)
check(
    'Freehand: it rebuilds as an open strip of 20 segments, 2.4 m long',
    v['freeGeom']['line'] and v['freeGeom']['verts'] == 40 and abs(v['freeGeom']['size'][0] - 2.4) < 0.01,
    v['freeGeom'],
)
check(
    'Freehand: the record draws as lines only',
    v['freeNode']['lines'] == 1 and v['freeNode']['meshes'] == 0,
    v['freeNode'],
)
check(
    'Freehand: releasing the pointer over the canvas keeps the stroke (a drag never reaches arClick)',
    v['freeRelease']['made'] == 1 and v['freeRelease']['kind'] == 'guide_path' and v['freeRelease']['n'] == 8,
    v['freeRelease'],
)
check('Freehand: the hint says to hold the pointer down', 'down' in v['freeHint'].lower(), v['freeHint'])

check(
    'the three kinds have readable labels in the tab',
    v['labels'] == ['Guide arc', 'Guide polygon', 'Guide path'],
    v['labels'],
)
check('the last guide toasted what it drew', 'Guide path' in v['toast'], v['toast'])
check(
    'exactly the 6 guides drawn are in the document, nothing else',
    v['docKinds'] == ['guide_arc', 'guide_poly', 'guide_poly', 'guide_poly', 'guide_path', 'guide_path'],
    v['docKinds'],
)

# ── 3. the assistant twins ──────────────────────────────────────────────────
txt, d = assistant('draw_guide_arc', {'cells': ['F8', 'K8', 'H5']})
check(
    'draw_guide_arc draws one guide_arc from three cells and reports its radius',
    kinds_of(d) == {'guide_arc': 1}
    and d.objs[0]['p']['x1'] == 0
    and d.objs[0]['p']['z1'] == 0
    and d.objs[0]['p']['x2'] == 5.0
    and d.objs[0]['mat'] == 'mat_glass'
    and 'radius 2.55 m' in txt,
    txt,
)
txt2, _ = assistant('draw_guide_arc', {'cells': ['F8', 'K8']})
check('draw_guide_arc refuses two cells', txt2.startswith('refused'), txt2)

txt3, d3 = assistant('draw_guide_polygon', {'cells': ['C4', 'L4', 'L13', 'C13']})
check(
    'draw_guide_polygon draws a closed ring through the cells',
    kinds_of(d3) == {'guide_poly': 1}
    and d3.objs[0]['p']['pts'] == [[0, 0], [9, 0], [9, 9], [0, 9]]
    and '36.00 m round' in txt3,
    txt3,
)
txt4, d4 = assistant('draw_guide_polygon', {'cells': ['K12'], 'sides': 6, 'radius': 2.5})
check(
    'draw_guide_polygon with sides=6 draws a regular hexagon around one cell',
    len(d4.objs[0]['p']['pts']) == 6 and 'regular 6-gon' in txt4,
    txt4,
)
txt5, _ = assistant('draw_guide_polygon', {'cells': ['K12'], 'sides': 20})
check('draw_guide_polygon refuses a 20-sided regular polygon', txt5.startswith('refused'), txt5)

txt6, d6 = assistant('draw_guide_path', {'cells': ['B2', 'F6', 'K5']})
check(
    'draw_guide_path draws an open polyline through the cells',
    kinds_of(d6) == {'guide_path': 1} and d6.objs[0]['p']['pts'] == [[0, 0], [4, 4], [9, 3]] and '3 points' in txt6,
    txt6,
)
txt7, _ = assistant('draw_guide_path', {'cells': ['B2']})
check('draw_guide_path refuses a single cell', txt7.startswith('refused'), txt7)

# ── 4. registrations ────────────────────────────────────────────────────────
check('the rail lists the three guide kinds', rail_has(['guide_arc', 'guide_poly', 'guide_path']) == [])
check(
    'the three kinds are declared VOID for the Blender sweep, on both halves',
    sorted(G.VOID_KINDS) == sorted(B.VOID_KINDS) == ['guide_arc', 'guide_path', 'guide_poly'],
    (G.VOID_KINDS, B.VOID_KINDS),
)
check(
    'every VOID builder returns an approximate-prefix empty mesh',
    all(B.BUILDERS[k](None, {}, {}) == ('~', []) for k in B.VOID_KINDS),
    list(B.BUILDERS),
)
check(
    'KINDS carries a default for each kind and BUTTONS is empty (a mode cannot be pressed)',
    sorted(G.KINDS) == ['guide_arc', 'guide_path', 'guide_poly'] and G.BUTTONS == [],
    (G.KINDS, G.BUTTONS),
)
check(
    'the prompt names the three tools',
    all(t in G.PROMPT for t in ('draw_guide_arc', 'draw_guide_polygon', 'draw_guide_path')),
    G.PROMPT,
)

finish()
