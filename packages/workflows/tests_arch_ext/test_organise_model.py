# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_organise_model.py — proof for the Organise family's five
icons (o_comp, o_browse, o_levels, o_gridlines, o_zones, o_zone_labels) and its three kinds
(component, gridline, zone).

Three engines have to agree:
  · the ASSISTANT (arch_assistant_ext/organise_model.py): make_component,
    place_component, add_storeys, draw_grid, add_zone produce the records the
    prompt promises, and BUTTONS names the six icons;
  · the TAB (arch_ext/organise_model.js): each icon is no longer a placeholder
    and does its tooltip's job — a component swallows the selection and keeps
    its bounding box, a definition edit rebuilds EVERY instance, the browser
    sheet lists them, a storey's "go" moves the drawing plane, the grid action
    makes gridline records, a zone carries its own area, and the room
    labels are OFF until the Room-labels switch is pressed (2026-09-12);
  · BLENDER (arch_blender_ext/organise_model.py): component and zone build
    meshes with faces (gridline is a declared VOID).

Budget: three browser_eval calls (icon_state is one of them), one Blender run.
"""

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

IDS = ['o_comp', 'o_browse', 'o_levels', 'o_gridlines', 'o_zones', 'o_zone_labels']

# ── the assistant half ──────────────────────────────────────────────────────
import zyg_workflows.arch_assistant_ext.organise_model as OM  # noqa: E402

check('BUTTONS names all six icons', OM.BUTTONS == IDS, OM.BUTTONS)
check(
    'the five server-side twins are registered assistant tools',
    all(t in tool_names() for t in ('make_component', 'place_component', 'add_storeys', 'draw_grid', 'add_zone')),
    [t for t in ('make_component', 'place_component', 'add_storeys', 'draw_grid', 'add_zone') if t not in tool_names()],
)
check('gridline is declared a VOID kind (a line on the plan, no solid)', OM.VOID_KINDS == ['gridline'], OM.VOID_KINDS)

WALLS = {
    'objects': [
        {'id': 'o1', 'kind': 'wall', 'p': {'len': 4, 'h': 2.7, 't': 0.24}, 'x': -2, 'y': 0, 'z': 0},
        {'id': 'o2', 'kind': 'wall', 'p': {'len': 4, 'h': 2.7, 't': 0.24}, 'x': 2, 'y': 0, 'z': 0},
    ]
}
txt, d = assistant('make_component', {'which': 'all', 'name': 'bay'}, doc=WALLS)
k = kinds_of(d)
comp = [o for o in d.objs if o['kind'] == 'component']
check(
    'make_component swallows the two walls into one component of 2 children',
    k.get('component') == 1 and not k.get('wall') and len(comp[0]['p']['children']) == 2,
    (txt, k),
)
check(
    'the definition is shared state in doc.ext.organise_model.components',
    len(d.ext['organise_model']['components']['bay']) == 2,
    d.ext.get('organise_model'),
)
check(
    'the component sits at the selection centre (0, 0, 0)',
    abs(comp[0]['x']) < 1e-6 and abs(comp[0]['z']) < 1e-6 and abs(comp[0]['y']) < 1e-6,
    comp[0],
)

txt2, d = assistant('place_component', {'name': 'bay', 'cell': 'F4'}, drawing=d)
check(
    'place_component drops a second instance of the same definition',
    kinds_of(d).get('component') == 2 and len(OM._instances(d, 'bay')) == 2,
    txt2,
)
txt2b, _ = assistant('place_component', {'name': 'nope', 'cell': 'F4'}, drawing=d)
check('an unknown component name is refused', txt2b.startswith('refused'), txt2b)

txt3, d3 = assistant('add_storeys', {'storeys': [{'name': 'First', 'h': 3.0}]}, doc={'objects': []})
sts = d3.ext['organise_model']['storeys']
check(
    'add_storeys stacks First on Ground at 2.7 m and keeps its own 3.0 m height',
    len(sts) == 2 and sts[1]['name'] == 'First' and abs(sts[1]['el'] - 2.7) < 1e-6 and abs(sts[1]['h'] - 3.0) < 1e-6,
    (txt3, sts),
)
check('the answer warns that the dock arrows still step 2.7 m', '2.7 m' in txt3, txt3)

txt4, d4 = assistant(
    'draw_grid', {'letters': 'A-C', 'numbers': '1-3', 'dx': 5, 'dz': 5, 'origin_cell': 'A1'}, doc={'objects': []}
)
gl = [o for o in d4.objs if o['kind'] == 'gridline']
check(
    'draw_grid A-C x 1-3 makes 6 gridline records in group "grid"',
    len(gl) == 6 and all(o['grp'] == 'grid' for o in gl),
    (txt4, len(gl)),
)
check(
    'a lettered line runs along +Z (ry = -pi/2) and a numbered one along +X',
    abs([o for o in gl if o['p']['label'] == 'A'][0]['ry'] + 3.14159265 / 2) < 1e-4
    and abs([o for o in gl if o['p']['label'] == '1'][0]['ry']) < 1e-9,
    [(o['p']['label'], o['ry']) for o in gl],
)

txt5, d5 = assistant(
    'add_zone', {'cells': ['C3', 'G3', 'G7', 'C7'], 'name': 'Hall', 'use': 'circulation'}, doc={'objects': []}
)
zn = [o for o in d5.objs if o['kind'] == 'zone']
check(
    'add_zone makes one zone record of 4 plan points, 16 m2 by shoelace',
    len(zn) == 1 and len(zn[0]['p']['pts']) == 4 and abs(OM._shoelace(zn[0]['p']['pts']) - 16.0) < 1e-6,
    (txt5, zn[0]['p'] if zn else None),
)
check('the tool answer states the same area', '16.00 m2' in txt5, txt5)

check(
    'the rail lists all three new kinds',
    rail_has(['component', 'gridline', 'zone']) == [],
    rail_has(['component', 'gridline', 'zone']),
)

# ── the tab: the icons are real ─────────────────────────────────────────────
st = icon_state(IDS)
check(
    'all six icons exist and are no longer placeholders (no stub, no dashed, no [placeholder] tip)',
    all(
        v.get('exists') and not v.get('stub') and not v.get('dashed') and not v.get('tip_placeholder')
        for v in st.values()
    ),
    st,
)
check(
    'o_zone_labels is a switch in the Organise group and starts OFF',
    st['o_zone_labels'].get('on') is False and st['o_zone_labels'].get('section') == 'Organise',
    st['o_zone_labels'],
)

# ── the tab: the icons DO their tooltips' jobs ──────────────────────────────
JS = r"""() => {
  const R = v => Math.round(v * 1000) / 1000;
  /* GEOMETRY only: a label sprite is a child of the record's node and would
     otherwise be measured as part of the thing it labels */
  const bbox = recs => { const b = new THREE.Box3();
    recs.forEach(r => { if (!r.node) return; r.node.updateWorldMatrix(true, true);
      r.node.traverse(m => { if ((m.isMesh || m.isLine || m.isLineSegments) && m.geometry) b.expandByObject(m); }); });
    return {s: b.getSize(new THREE.Vector3()).toArray().map(R), c: b.getCenter(new THREE.Vector3()).toArray().map(R)}; };
  const out = {};

  /* ── o_comp: two walls become ONE component ─────────────────────────── */
  const w1 = arNewObj('wall', {len: 4, h: 2.7, t: 0.24}, -2, 0, 0);
  const w2 = arNewObj('wall', {len: 4, h: 2.7, t: 0.24},  2, 0, 0);
  out.union = bbox([w1, w2]);
  arSelect([w1.id, w2.id]);
  arTool('o_comp', {name: 'bay'});
  const comps = () => AR.objs.filter(o => o.kind === 'component' && o.p.name === 'bay');
  out.compN = comps().length;
  out.wallsLeft = AR.objs.filter(o => o.kind === 'wall').length;
  out.kids = out.compN ? comps()[0].p.children.length : 0;
  out.compBox = out.compN ? bbox([comps()[0]]) : null;
  out.defKids = (((AR.doc.ext || {}).organise_model || {}).components || {}).bay
                ? AR.doc.ext.organise_model.components.bay.length : 0;

  /* ── o_browse: the browser arms Place with the definition ───────────── */
  arTool('o_browse');
  const sheet = document.getElementById('ar-sheet');
  out.sheet1 = {open: sheet && sheet.style.display === 'flex',
                title: sheet ? (sheet.querySelector('.hd span') || {}).textContent : '',
                bay: sheet ? /<b>bay<\/b>/.test(sheet.innerHTML) : false,
                one: sheet ? /1 instance</.test(sheet.innerHTML) : false,
                rows: sheet ? sheet.querySelectorAll('table.ar-tbl tr').length : 0,
                buttons: sheet ? [].map.call(sheet.querySelectorAll('button'), b => b.textContent) : []};
  organise_model.place('bay');                 /* the sheet's "Place another" */
  out.armed = {tool: AR.tool, kind: (AR.place || {}).kind, name: (AR.place || {}).n,
               kids: ((AR.place || {}).p || {}).children.length};
  /* the click handler's own line, so the second instance is placed the way a click places it */
  const inst2 = arNewObj(AR.place.kind, AR.place.p, 20, 0, 0);
  arApplyTransform(inst2);
  arTool('select');
  out.instN = comps().length;

  /* ── o_comp {edit}: change a child of instance 2, rebuild BOTH ───────── */
  inst2.p.children[0].p.len = 6;
  arRebuild(inst2);
  arTool('o_comp', {edit: 'bay', from: inst2.id});
  out.lens = comps().map(o => o.p.children[0].p.len);
  out.defLen = AR.doc.ext.organise_model.components.bay[0].p.len;
  out.firstBox = bbox([comps()[0]]);

  /* ── o_browse again: select all instances, then explode one ─────────── */
  arTool('o_browse');
  organise_model.selectAll('bay');
  out.selAll = AR.sel.length;
  out.sheet2instances = /2 instances</.test(document.getElementById('ar-sheet').innerHTML);
  organise_model.explode(comps()[0].id);
  out.afterExplode = {comps: comps().length, walls: AR.objs.filter(o => o.kind === 'wall').length};
  arSheetClose();

  /* ── o_levels: add a 3.0 m storey and go to it ───────────────────────── */
  arSetLevel(0);
  arTool('o_levels', {action: 'add', name: 'First', height: 3.0});
  const S = () => AR.doc.ext.organise_model.storeys;
  out.storeys = S().map(s => [s.name, s.el, s.h]);
  const lsheet = document.getElementById('ar-sheet');
  out.storeySheet = {open: lsheet.style.display === 'flex',
                     rows: lsheet.querySelectorAll('table.ar-tbl tr').length,
                     says27: /2\.70 m/.test(lsheet.innerHTML)};
  arTool('o_levels', {action: 'set', name: 'First'});
  out.levelAfterGo = AR.level;
  out.storeyAt = [organise_model.storeyAt(0), organise_model.storeyAt(3), organise_model.storeyAt(5.6)];
  arTool('o_levels', {action: 'remove', name: 'First'});
  out.storeysAfterRemove = S().length;
  arSheetClose();
  arSetLevel(0);

  /* ── o_gridlines: the whole grid, then one more line by the MODE ─────── */
  const before = AR.objs.length;
  arTool('o_gridlines', {letters: 'A-C', numbers: '1-3', dx: 5, dy: 5, origin: 'A1'});
  const gls = () => AR.objs.filter(o => o.kind === 'gridline');
  out.grid = {n: gls().length, added: AR.objs.length - before,
              labels: gls().map(o => o.p.label), grp: gls()[0].grp,
              armed: AR.tool};
  const A = gls().filter(o => o.p.label === 'A')[0], one = gls().filter(o => o.p.label === '1')[0];
  out.gridGeom = {aLen: R(A.p.len), aRy: R(A.ry), aAxis: A.p.axis,
                  oneLen: R(one.p.len), oneRy: R(one.ry), oneAxis: one.p.axis,
                  aSpanZ: bbox([A]).s[2], oneSpanX: bbox([one]).s[0],
                  lines: (() => { let n = 0; A.node.traverse(m => { if (m.isLine || m.isLineSegments) n++; }); return n; })(),
                  meshes: (() => { let n = 0; A.node.traverse(m => { if (m.isMesh) n++; }); return n; })()};
  AR_EXT.modes.o_gridlines.click({x: 0, z: 0});
  AR_EXT.modes.o_gridlines.click({x: 0, z: 12});          /* prompt answers its default */
  out.gridAfterMode = gls().length;
  out.modeLine = R(gls()[gls().length - 1].p.len);
  organise_model.labels();
  out.gridLabel = (() => { let t = null; A.node.traverse(m => { if (m.userData && m.userData.orgLabel) t = m.userData.orgText; }); return t; })();

  /* the tooltip promises columns SNAP to the grid: the family's own hook.
     A runs along +Z (ends at z0-2.5 and z0+12.5), 1 runs along +X at z0;
     they cross at A's x and 1's z, which is the origin cell's centre. */
  const gx = A.x, gz = one.z, endZ = A.z - A.p.len / 2;
  const sw = on => { const s = AR.precision_snaps;
    if (s) Object.keys(s.on).forEach(k => { s.on[k] = (k === on); }); return !!s; };
  out.prLoaded = sw('pr_end');
  if (window.arPrecisionSnapsRadius) arPrecisionSnapsRadius(0.5);
  out.snapEnd = arExtSnap({x: gx + 0.2, z: endZ + 0.2, y: 0});
  out.snapEndWant = [R(gx), R(endZ)];
  sw('pr_int');
  out.snapInt = arExtSnap({x: gx + 0.2, z: gz - 0.2, y: 0});
  out.snapIntWant = [R(gx), R(gz)];
  sw('pr_mid');                                   /* midpoint off => end must NOT snap */
  out.snapEndOff = arExtSnap({x: gx + 0.2, z: endZ + 0.2, y: 0});
  sw('pr_cen');
  if (window.arPrecisionSnapsRadius) arPrecisionSnapsRadius(0);
  arTool('select');

  /* ── o_zones: a 4 x 4 room, by args and by the MODE ──────────────────── */
  arTool('o_zones', {pts: [[0, 0], [4, 0], [4, 4], [0, 4]], name: 'Hall', use: 'circulation'});
  const zs = () => AR.objs.filter(o => o.kind === 'zone');
  const z = zs()[0];
  out.zone = {n: zs().length, pts: z.p.pts.length, name: z.p.name, use: z.p.use,
              area: R(organise_model.zoneArea(z)), label: organise_model.zoneLabel(z),
              box: bbox([z]).s, grp: z.grp, centre: [R(z.x), R(z.z)]};
  const spriteOf = rec => { let t = null; rec.node.traverse(m => { if (m.userData && m.userData.orgLabel) t = m.userData.orgText; }); return t; };
  organise_model.labels();
  out.zoneLabelDefault = spriteOf(z);                     /* OFF by default: no sprite */
  out.roomLabelsDefault = organise_model.roomLabels();
  arTool('o_zone_labels');                                 /* the switch, on */
  out.roomLabelsOn = !!(AR.doc.ext.organise_model && AR.doc.ext.organise_model.labels);
  out.zoneLabelSprite = spriteOf(z);
  arTool('o_zone_labels');                                 /* and off again */
  out.zoneLabelAfterOff = spriteOf(z);
  out.roomLabelsAfterOff = organise_model.roomLabels();
  arTool('o_zone_labels', {on: true});                     /* by args, as the assistant presses it */
  out.zoneLabelByArgs = spriteOf(z);
  arTool('o_zones');                                       /* no args: arm the mode */
  out.zoneArmed = AR.tool;
  [[10, 10], [16, 10], [16, 16], [10, 16]].forEach(p => AR_EXT.modes.o_zones.click({x: p[0], z: p[1]}));
  AR_EXT.modes.o_zones.key({key: 'Enter'});                /* prompts answer their defaults */
  out.zonesAfterMode = zs().length;
  out.modeZoneArea = zs().length > 1 ? R(organise_model.zoneArea(zs()[zs().length - 1])) : null;
  arTool('select');

  /* undo is armed: every edit pushed once before it happened */
  out.undoDepth = AR.undo ? AR.undo.length : (AR._undo ? AR._undo.length : -1);
  return out;
}"""
r = browser_eval(JS)
v = r['value']
check('no page errors while the five icons ran', not r['errors'], r['errors'])

check(
    'o_comp: the selection became ONE component of 2 children and the walls are gone',
    v['compN'] == 1 and v['wallsLeft'] == 0 and v['kids'] == 2 and v['defKids'] == 2,
    v,
)
check(
    "o_comp: the component's bounding box equals the two walls' union",
    v['compBox']
    and all(abs(a - b) < 0.01 for a, b in zip(v['compBox']['s'], v['union']['s']))
    and all(abs(a - b) < 0.01 for a, b in zip(v['compBox']['c'], v['union']['c'])),
    (v['compBox'], v['union']),
)
check(
    'o_browse: the sheet opens and lists bay with its instance and children counts',
    v['sheet1']['open'] and v['sheet1']['bay'] and v['sheet1']['one'] and v['sheet1']['rows'] >= 2,
    v['sheet1'],
)
check(
    'o_browse: "Place another" arms the Place tool with the definition',
    v['armed']['tool'] == 'place'
    and v['armed']['kind'] == 'component'
    and v['armed']['name'] == 'bay'
    and v['armed']['kids'] == 2,
    v['armed'],
)
check('a second instance shares the name', v['instN'] == 2, v['instN'])
check(
    '"Edit definition" rewrites the definition AND rebuilds every instance',
    v['lens'] == [6, 6] and v['defLen'] == 6,
    (v['lens'], v['defLen']),
)
check(
    'the rebuilt first instance really grew with the new child (its 4 m wall is now 6 m: 8 m -> 9 m)',
    abs(v['firstBox']['s'][0] - 9) < 0.05,
    v['firstBox'],
)
check(
    'o_browse: "Select all instances" selects both, and the sheet counts them',
    v['selAll'] == 2 and v['sheet2instances'],
    (v['selAll'], v['sheet2instances']),
)
check(
    'o_browse: "Explode" puts the children back as records',
    v['afterExplode'] == {'comps': 1, 'walls': 2},
    v['afterExplode'],
)

check(
    'o_levels: First stacks at 2.7 m and keeps its own 3.0 m height',
    v['storeys'] == [['Ground', 0, 2.7], ['First', 2.7, 3]],
    v['storeys'],
)
check(
    'o_levels: the sheet lists the storeys and says the dock arrows step 2.7 m',
    v['storeySheet']['open'] and v['storeySheet']['rows'] >= 3 and v['storeySheet']['says27'],
    v['storeySheet'],
)
check('o_levels: "go" puts the drawing plane on First at 2.7 m', abs(v['levelAfterGo'] - 2.7) < 1e-6, v['levelAfterGo'])
check(
    'storeyAt(y) names the storey a height falls in (and is exported for other families)',
    v['storeyAt'] == ['Ground', 'First', 'First'],
    v['storeyAt'],
)
check('o_levels: a storey can be removed again', v['storeysAfterRemove'] == 1, v['storeysAfterRemove'])

check(
    'o_gridlines: A-C x 1-3 makes exactly 6 gridline records in group "grid"',
    v['grid']['n'] == 6
    and v['grid']['added'] == 6
    and v['grid']['grp'] == 'grid'
    and sorted(v['grid']['labels']) == ['1', '2', '3', 'A', 'B', 'C'],
    v['grid'],
)
check(
    'o_gridlines: the action leaves the MODE armed for one more line',
    v['grid']['armed'] == 'o_gridlines',
    v['grid']['armed'],
)
check(
    'a gridline is a wall-like segment: p.len + ry, lettered along +Z, numbered along +X',
    v['gridGeom']['aAxis'] == 'z'
    and abs(v['gridGeom']['aRy'] + 1.571) < 0.002
    and v['gridGeom']['oneAxis'] == 'x'
    and abs(v['gridGeom']['oneRy']) < 1e-6
    and abs(v['gridGeom']['aLen'] - 15) < 1e-6
    and abs(v['gridGeom']['oneLen'] - 15) < 1e-6,
    v['gridGeom'],
)
check(
    'a gridline draws LINES and no solid (a VOID kind), spanning its own length',
    v['gridGeom']['lines'] >= 1
    and v['gridGeom']['meshes'] == 0
    and abs(v['gridGeom']['aSpanZ'] - 15) < 0.01
    and abs(v['gridGeom']['oneSpanX'] - 15) < 0.01,
    v['gridGeom'],
)
check(
    'o_gridlines MODE: two clicks add one more labelled 12 m line',
    v['gridAfterMode'] == 7 and abs(v['modeLine'] - 12) < 1e-6,
    (v['gridAfterMode'], v['modeLine']),
)
check('a gridline carries its label as a sprite', v['gridLabel'] == 'A', v['gridLabel'])
check(
    'o_gridlines keeps its tooltip: a grid line END snaps (Endpoint on)',
    v['snapEnd'].get('snap') == 'endpoint'
    and abs(v['snapEnd']['x'] - v['snapEndWant'][0]) < 1e-4
    and abs(v['snapEnd']['z'] - v['snapEndWant'][1]) < 1e-4,
    (v['snapEnd'], v['snapEndWant']),
)
check(
    'two grid lines CROSS and that crossing snaps (Intersection on)',
    v['snapInt'].get('snap') == 'intersection'
    and abs(v['snapInt']['x'] - v['snapIntWant'][0]) < 1e-4
    and abs(v['snapInt']['z'] - v['snapIntWant'][1]) < 1e-4,
    (v['snapInt'], v['snapIntWant']),
)
check(
    'the grid snap obeys the Precision switches: Endpoint off, no endpoint snap',
    v['prLoaded'] and not v['snapEndOff'].get('snap'),
    v['snapEndOff'],
)

check(
    'o_zones: 4 points make one zone record over 4 corners, group "zones"',
    v['zone']['n'] == 1
    and v['zone']['pts'] == 4
    and v['zone']['name'] == 'Hall'
    and v['zone']['use'] == 'circulation'
    and v['zone']['grp'] == 'zones',
    v['zone'],
)
check(
    'o_zone_labels: room labels are OFF by default — a new zone draws no name sprite',
    v['zoneLabelDefault'] is None and v['roomLabelsDefault'] is False,
    (v['zoneLabelDefault'], v['roomLabelsDefault']),
)
check(
    'o_zone_labels: pressing the switch stamps doc.ext.organise_model.labels and names the room',
    v['roomLabelsOn'] is True and v['zoneLabelSprite'] == v['zone']['label'],
    (v['roomLabelsOn'], v['zoneLabelSprite']),
)
check(
    'o_zone_labels: pressing it again removes the sprite and clears the flag',
    v['zoneLabelAfterOff'] is None and v['roomLabelsAfterOff'] is False,
    (v['zoneLabelAfterOff'], v['roomLabelsAfterOff']),
)
check(
    "o_zone_labels: {on:true} by args (the assistant's press) turns them on without toggling",
    v['zoneLabelByArgs'] == v['zone']['label'],
    v['zoneLabelByArgs'],
)
check(
    'o_zones: the label reads the shoelace area — 16 m2 for a 4 x 4 room',
    abs(v['zone']['area'] - 16) < 1e-6
    and '16 m\u00b2' in v['zone']['label']
    and v['zoneLabelSprite'] == v['zone']['label'],
    (v['zone']['area'], v['zone']['label']),
)
check(
    'o_zones: the polygon is really extruded 4 x 4 x 0.05 and pickable',
    abs(v['zone']['box'][0] - 4) < 0.01
    and abs(v['zone']['box'][2] - 4) < 0.01
    and abs(v['zone']['box'][1] - 0.05) < 0.01,
    v['zone']['box'],
)
check(
    'o_zones MODE: clicking four corners and pressing Enter closes a 6 x 6 room',
    v['zoneArmed'] == 'o_zones' and v['zonesAfterMode'] == 2 and abs(v['modeZoneArea'] - 36) < 1e-6,
    (v['zoneArmed'], v['zonesAfterMode'], v['modeZoneArea']),
)

# ── Blender ─────────────────────────────────────────────────────────────────
bl = blender_kinds(
    [
        # the two walls are kept apart: touching boxes are welded by the builder's
        # remove_doubles, and 12 clean faces are a plainer proof than 11 welded ones
        {
            'kind': 'component',
            'p': {
                'name': 'bay',
                'children': [
                    {'kind': 'wall', 'p': {'len': 4, 'h': 2.7, 't': 0.24}, 'x': -3, 'y': 0, 'z': 0, 'ry': 0, 's': 1},
                    {'kind': 'wall', 'p': {'len': 4, 'h': 2.7, 't': 0.24}, 'x': 3, 'y': 0, 'z': 0, 'ry': 0, 's': 1},
                ],
            },
        },
        {
            'kind': 'zone',
            'p': {'pts': [[-2, -2], [2, -2], [2, 2], [-2, 2]], 'name': 'Hall', 'use': 'circulation', 'h': 0.05},
        },
    ]
)
c = bl.get('component', {})
check(
    'Blender builds a component as its two children: 12 faces, 10 m wide, 2.7 m tall',
    c.get('polys', 0) == 12
    and c.get('verts', 0) == 16
    and abs((c.get('size') or [0, 0, 0])[0] - 10) < 0.01
    and abs((c.get('size') or [0, 0, 0])[1] - 2.7) < 0.01
    and abs((c.get('size') or [0, 0, 0])[2] - 0.24) < 0.01,
    c,
)
import re as _re  # noqa: E402

import zyg_workflows  # noqa: E402

# 2026-10: arch_blender_build.py became a package; RENDER_SKIP_KINDS is defined in
# its build_scene submodule (and re-exported from the package __init__).
_RSK_SRC = os.path.join(os.path.dirname(zyg_workflows.__file__), 'arch_blender_build', 'build_scene.py')
with open(_RSK_SRC, encoding='utf-8') as _fh:
    _RSK = (_re.search(r'RENDER_SKIP_KINDS\s*=\s*frozenset\(\{([^}]*)\}\)', _fh.read()) or [None, ''])[1]
check(
    'a zone is a plan annotation: the render build skips it (2026-09-16: its 0.05 m prism inside the slab '
    'z-fought the ceiling as a black band in every Cycles lobby frame)',
    'zone' not in bl and "'zone'" in _RSK,
    (list(bl), _RSK),
)
check(
    'gridline is skipped by Blender on purpose (a VOID kind)',
    'gridline' not in bl and 'gridline' in OM.VOID_KINDS,
    list(bl),
)

# the two RAIL DEFAULTS, straight out of KINDS: dropping either from the rail
# must give what its kind promises — a component a body, a gridline none.
bl2 = blender_kinds(
    [
        {'kind': 'component', 'p': OM.KINDS['component']},
        {'kind': 'gridline', 'p': OM.KINDS['gridline']},
    ]
)
c2 = bl2.get('component', {})
check(
    'the KINDS default of a component carries a child, so an empty one still has a body',
    OM.KINDS['component']['children'] and c2.get('polys', 0) > 0,
    (OM.KINDS['component'], c2),
)
g2 = bl2.get('gridline', {})
check('the gridline builder adds nothing: 0 polygons, not the generic fallback cuboid', g2.get('polys', 0) == 0, g2)

finish()
