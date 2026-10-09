# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_measure_annotations.py — proves Measure ▸ Dimension,
Protractor and Label are real (2026-09-07).

Two browser openings: icon_state for the three ids, and ONE evaluation that
drives all three pointer modes through their own click(), checks the records and
the values they measure, checks the line geometry each kind builds, then runs
arTick() to prove the text sprites exist, name their records, redraw only when
the text changes, grow by 64 px per line, and disappear with the record.
The assistant twins and the library rail are checked in-process, no server.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import assistant, browser_eval, check, finish, icon_state, rail_has, tool_names  # noqa: E402

IDS = ['dim', 'angle', 'text']

# ── the icons ────────────────────────────────────────────────────────────────
st = icon_state(IDS)
for i in IDS:
    check(
        'icon %s exists and is no longer a placeholder (no stub, no dashed border, no [placeholder] tip)' % i,
        st.get(i, {}).get('exists')
        and not st[i].get('stub')
        and not st[i].get('dashed')
        and not st[i].get('tip_placeholder'),
        st.get(i),
    )

# ── the tab: drive the three modes, then the sprites ─────────────────────────
r = browser_eval("""() => {
  const out = {};
  AR.objs.slice().forEach(o => arRemove(o));
  const P = (x, z) => ({x: x, z: z, y: 0});

  out.armed = [];
  arToolApply('dim');
  out.armed.push(AR.tool);
  AR_EXT.modes.dim.click(P(0, 0), {}, null);
  out.midHint = AR_EXT.modes.dim.hint(AR.draft);
  AR_EXT.modes.dim.click(P(5, 0), {}, null);

  arToolApply('angle');
  out.armed.push(AR.tool);
  AR_EXT.modes.angle.click(P(10, 0), {}, null);
  AR_EXT.modes.angle.click(P(12, 0), {}, null);
  AR_EXT.modes.angle.click(P(10, -2), {}, null);

  arToolApply('text');
  out.armed.push(AR.tool);
  AR_EXT.modes.text.click(P(20, 0), {text: 'Kitchen'}, null);
  AR_EXT.modes.text.click(P(22, 0), {}, null);            /* prompt() answers its default */

  const dim = AR.objs.find(o => o.kind === 'dim_linear');
  const ang = AR.objs.find(o => o.kind === 'dim_angle');
  const labs = AR.objs.filter(o => o.kind === 'label_text');
  out.kinds = AR.objs.map(o => o.kind);
  out.dimP = dim ? dim.p : null;
  out.dimAt = dim ? [dim.x, dim.y, dim.z] : null;
  out.dimValue = dim ? measure_annotations_value(dim).toFixed(3) : null;
  out.dimLabel = dim ? measure_annotations_label(dim) : null;
  out.angP = ang ? ang.p : null;
  out.angValue = ang ? measure_annotations_value(ang).toFixed(3) : null;
  out.angLabel = ang ? measure_annotations_label(ang) : null;
  out.labTxts = labs.map(o => o.p.txt);
  out.labSize = labs.length ? labs[0].p.size : null;
  out.names = AR.objs.map(o => o.name);
  out.undo = AR.undo.length;

  /* geometry: real line parts through arGeom, never the unknown-kind marker cube */
  const gd = arGeom('dim_linear', dim.p), ga = arGeom('dim_angle', ang.p), gl = arGeom('label_text', labs[0].p);
  out.parts = {dim_linear: gd.length, dim_angle: ga.length, label_text: gl.length};
  out.allLines = [gd, ga, gl].every(g => g.every(pt => pt.line === 1 && pt.g
                                    && pt.g.attributes.position.count >= 2));
  out.arcPts = ga[2].g.attributes.position.count;
  out.labels = ['dim_linear', 'dim_angle', 'label_text'].map(k => arKindLabel(k));
  out.dimMeshes = 0;
  dim.node.traverse(m => { if (m.isMesh) out.dimMeshes++; });

  /* the text sprites — created by the tick hook, not by arRebuild */
  out.spritesBeforeTick = 0;
  AR.scene.traverse(o => { if (o.isSprite && o.userData && o.userData.arAnnId) out.spritesBeforeTick++; });
  arTick();
  const spr = [];
  AR.scene.traverse(o => { if (o.isSprite && o.userData && o.userData.arAnnId) spr.push(o); });
  out.spriteIds = spr.map(s => s.userData.arAnnId).sort();
  out.recIds = AR.objs.map(o => o.id).sort();
  out.inScene = spr.every(s => s.parent === AR.scene);
  out.notInNode = spr.every(s => !AR.objs.some(o => o.node && o.node.getObjectById(s.id)));
  const ds = spr.find(s => s.userData.arAnnId === dim.id);
  const ls = spr.find(s => s.userData.arAnnId === labs[0].id);
  out.dimSpriteText = ds.userData.arAnnText;
  out.dimSpritePos = [ds.position.x, ds.position.y, ds.position.z].map(v => Math.round(v * 1000) / 1000);
  out.labSpriteText = ls.userData.arAnnText;
  out.labSpritePos = [ls.position.x, ls.position.y, ls.position.z].map(v => Math.round(v * 1000) / 1000);
  out.depthTest = ds.material.depthTest;
  out.order = ds.renderOrder;
  out.atten = ds.material.sizeAttenuation;
  out.spriteH = Math.round(ds.scale.y * 1000) / 1000;
  out.canvas1 = ds.material.map.image.height;

  /* the canvas is redrawn when the text changes, and only then */
  const tex0 = ds.material.map;
  arTick();
  out.texStable = ds.material.map === tex0;
  dim.p.txt = 'SPAN';
  arTick();
  out.texRedrawn = ds.material.map !== tex0;
  out.overrideText = ds.userData.arAnnText;
  dim.p.txt = '';
  arTick();
  out.backToMetres = ds.userData.arAnnText;

  /* 64 px per line */
  labs[0].p.txt = 'Kitchen\\nlevel 0';
  arTick();
  out.canvas2 = ls.material.map.image.height;

  /* the record goes, the sprite goes with it */
  const gone = labs[1].id;
  arRemove(labs[1]);
  arTick();
  out.afterRemove = 0;
  out.spritesLeft = 0;
  AR.scene.traverse(o => { if (o.isSprite && o.userData && o.userData.arAnnId) {
    out.spritesLeft++; if (o.userData.arAnnId === gone) out.afterRemove++; } });
  out.recsLeft = AR.objs.length;
  return out;
}""")
v = r['value']
check('no page errors while driving the three modes', not r['errors'] and not r['console'], (r['errors'], r['console']))
check('dim/angle/text arm as pointer modes (AR.tool latched)', v['armed'] == ['dim', 'angle', 'text'], v['armed'])
check(
    'two dim clicks made one dim_linear, three angle clicks one dim_angle, two text clicks two label_text',
    v['kinds'] == ['dim_linear', 'dim_angle', 'label_text', 'label_text'],
    v['kinds'],
)
check(
    'the dimension stores parameters only: local end + offset + txt',
    v['dimP'] == {'x2': 5, 'z2': 0, 'off': 0.6, 'txt': ''} and v['dimAt'] == [0, 0, 0],
    v['dimP'],
)
check(
    'a 5 m pair measures 5.000 m and labels itself "5 m"',
    v['dimValue'] == '5.000' and v['dimLabel'] == '5 m',
    (v['dimValue'], v['dimLabel']),
)
check(
    'a right angle measures 90 degrees and labels itself "90°"',
    v['angValue'] == '90.000' and v['angLabel'] == '90\u00b0',
    (v['angValue'], v['angLabel']),
)
check(
    'the angle stores the vertex-local arms and the arc radius',
    v['angP'] == {'x1': 2, 'z1': 0, 'x2': 0, 'z2': -2, 'r': 1},
    v['angP'],
)
check(
    'the label takes its note from opt.text, and from prompt() when a person clicks',
    v['labTxts'] == ['Kitchen', 'Note'] and v['labSize'] == 0.35,
    (v['labTxts'], v['labSize']),
)
check(
    'each annotation is named for what it says in the outliner',
    v['names'][0] == 'Dimension 5 m' and v['names'][1] == 'Angle 90\u00b0' and v['names'][2] == 'Label: Kitchen',
    v['names'],
)
check('one undo step was pushed per annotation (4 records, 4 pushes)', v['undo'] == 4, v['undo'])
check(
    'arGeom builds 5 line parts for a dimension (line, 2 extension lines, 2 ticks), '
    '3 for an angle (2 rays + arc), 1 for a label',
    v['parts'] == {'dim_linear': 5, 'dim_angle': 3, 'label_text': 1},
    v['parts'],
)
check(
    'every part is a line with real vertices — no marker cube, no mesh',
    v['allLines'] and v['dimMeshes'] == 0,
    (v['allLines'], v['dimMeshes']),
)
check('the angle arc is 24 segments (48 line vertices)', v['arcPts'] == 48, v['arcPts'])
check('the three kinds have their own labels', v['labels'] == ['Dimension', 'Angle', 'Label'], v['labels'])
check('no sprite exists until the tick hook runs', v['spritesBeforeTick'] == 0, v['spritesBeforeTick'])
check(
    'after one arTick every annotation record has a sprite, and the sprite names its record',
    v['spriteIds'] == v['recIds'],
    (v['spriteIds'], v['recIds']),
)
check(
    'the sprites hang on AR.scene, never on rec.node (arDisposeNode would kill them)',
    v['inScene'] and v['notInNode'],
    (v['inScene'], v['notInNode']),
)
check(
    'the dimension sprite reads "5 m" and sits at the midpoint of the offset dimension line',
    v['dimSpriteText'] == '5 m' and v['dimSpritePos'] == [2.5, 0.02, 0.6],
    (v['dimSpriteText'], v['dimSpritePos']),
)
check(
    'the label sprite reads the note and sits on its point, 0.02 m up',
    v['labSpriteText'] == 'Kitchen' and v['labSpritePos'] == [20, 0.02, 0],
    (v['labSpriteText'], v['labSpritePos']),
)
check(
    'sprites draw over the model: depthTest off, renderOrder 10, sizeAttenuation on',
    v['depthTest'] is False and v['order'] == 10 and v['atten'] is True,
    (v['depthTest'], v['order'], v['atten']),
)
check('the sprite is scaled to p.size metres tall (0.35 by default)', v['spriteH'] == 0.35, v['spriteH'])
check('one line of text is one 64 px band on the canvas (plus padding)', 64 <= v['canvas1'] < 128, v['canvas1'])
check('a second line adds exactly 64 px', v['canvas2'] - v['canvas1'] == 64, (v['canvas1'], v['canvas2']))
check('the canvas is NOT redrawn while the text is unchanged', v['texStable'], v['texStable'])
check(
    'p.txt overrides the measured text and redraws the canvas',
    v['texRedrawn'] and v['overrideText'] == 'SPAN' and v['backToMetres'] == '5 m',
    (v['texRedrawn'], v['overrideText'], v['backToMetres']),
)
check(
    'arRemove + arTick takes the sprite away with the record',
    v['afterRemove'] == 0 and v['spritesLeft'] == 3 and v['recsLeft'] == 3,
    (v['afterRemove'], v['spritesLeft'], v['recsLeft']),
)

# ── the library rail ─────────────────────────────────────────────────────────
check(
    'the rail lists the three annotation kinds',
    rail_has(['dim_linear', 'dim_angle', 'label_text']) == [],
    rail_has(['dim_linear', 'dim_angle', 'label_text']),
)

# ── the assistant twins ──────────────────────────────────────────────────────
names = tool_names()
check(
    'the assistant has all four twins',
    all(n in names for n in ('add_dimension', 'add_angle', 'add_label', 'list_annotations')),
    [n for n in ('add_dimension', 'add_angle', 'add_label', 'list_annotations') if n not in names],
)

txt, d = assistant('add_dimension', {'cell_from': 'C4', 'cell_to': 'G4', 'offset': 1.2})
o = d.objs[-1]
check(
    'add_dimension draws a dim_linear spanning the two cell centres',
    o['kind'] == 'dim_linear'
    and abs(o['p']['x2'] - 4.0) < 1e-6
    and abs(o['p']['z2']) < 1e-9
    and o['p']['off'] == 1.2
    and '4.000 m' in txt,
    (txt, o),
)

txt2, d = assistant('add_angle', {'vertex_cell': 'F6', 'cell_a': 'H6', 'cell_b': 'F8'}, drawing=d)
o2 = d.objs[-1]
check(
    'add_angle draws a dim_angle and reports 90 degrees for a right angle',
    o2['kind'] == 'dim_angle' and '90.00 degrees' in txt2 and o2['p']['r'] == 1.0,
    (txt2, o2),
)

txt3, d = assistant('add_label', {'cell': 'E5', 'text': 'Kitchen'}, drawing=d)
o3 = d.objs[-1]
check(
    'add_label pins the note to the cell',
    o3['kind'] == 'label_text' and o3['p']['txt'] == 'Kitchen' and o3['p']['size'] == 0.35 and 'E5' in txt3,
    (txt3, o3),
)

txt4, _ = assistant('add_label', {'cell': 'E5', 'text': '   '}, drawing=d)
check('an empty label is refused, not drawn', txt4.startswith('refused') and len(d.objs) == 3, txt4)

txt5, _ = assistant('list_annotations', {}, drawing=d)
check(
    'list_annotations reports every annotation with the value it measures',
    '3 annotation(s)' in txt5 and '4.000 m' in txt5 and '90.00 degrees' in txt5 and 'Kitchen' in txt5,
    txt5,
)

txt6, _ = assistant('add_dimension', {'cell_from': 'C4', 'cell_to': 'C4'})
check('a zero-length dimension is refused', txt6.startswith('refused'), txt6)

txt7, d7 = assistant('list_annotations', {})
check(
    'list_annotations on an empty drawing says so and draws nothing',
    txt7 == 'no annotations on the drawing' and not d7.objs,
    txt7,
)

import importlib.util  # noqa: E402

from zyg_workflows import arch_assistant as A  # noqa: E402

M = A.EXT_MODULES['measure_annotations']
_spec = importlib.util.spec_from_file_location(
    'blender_measure_annotations',
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'arch_blender_ext', 'measure_annotations.py'
    ),
)
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)
check(
    'the three kinds are declared VOID on both Python halves',
    sorted(M.VOID_KINDS) == sorted(B.VOID_KINDS) == ['dim_angle', 'dim_linear', 'label_text']
    and all(B.BUILDERS[k](None, {}, None) == ('~', []) for k in B.VOID_KINDS),
    (M.VOID_KINDS, B.VOID_KINDS),
)
check('the family declares no pressable buttons (the three icons are pointer modes)', M.BUTTONS == [], M.BUTTONS)

finish()
