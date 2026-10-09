# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_display_helpers.py — the proof for the six Display icons
wired by arch_ext/display_helpers.js (d_bbox, d_ground, d_labels, d_colorby,
d_transp, d_backface).

Two browser passes only: one icon_state read, and one batched behavioural run
against a three-record drawing on two storeys with one tagged object. Every
assertion is on the document, on THREE's own numbers or on the state object —
never on pixels, because the harness renders with software GL.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, browser_eval, icon_state  # noqa: E402

IDS = ['d_bbox', 'd_ground', 'd_labels', 'd_colorby', 'd_transp', 'd_backface']

# three records, two storeys (0 and 2.7 m), one of them tagged
DOC = {
    'objects': [
        {
            'id': 'o1',
            'kind': 'slab',
            'name': 'Ground slab',
            'p': {'w': 4, 'd': 4, 't': 0.2},
            'x': 0,
            'y': 0,
            'z': 0,
            'mat': 'mat_concrete',
            'meta': {'tags': ['A']},
        },
        {
            'id': 'o2',
            'kind': 'wall',
            'name': 'North wall',
            'p': {'len': 4, 'h': 2.7, 't': 0.24},
            'x': 0,
            'y': 0,
            'z': 2,
            'mat': 'mat_brick',
            'meta': {},
        },
        {
            'id': 'o3',
            'kind': 'slab',
            'name': 'Upper slab',
            'p': {'w': 4, 'd': 4, 't': 0.2},
            'x': 0,
            'y': 2.7,
            'z': 0,
            'mat': 'mat_glass',
            'meta': {},
        },
    ]
}

# ── 1. the placeholder mark is gone for all six ──────────────────────────────
st = icon_state(IDS)
for i in IDS:
    s = st.get(i) or {}
    check(
        '%s exists, no stub flag, no dashed class, no [placeholder] tip' % i,
        s.get('exists') and not s.get('stub') and not s.get('dashed') and not s.get('tip_placeholder'),
        s,
    )

# ── 2. one batched behavioural pass ──────────────────────────────────────────
JS = r"""() => {
  const R = {}, S = () => display_helpers_info(), tick = () => arTick();
  const firstMeshCol = (id) => { const r = arFind(id); let c = null;
    r.node.traverse(o => { if (o.isMesh && c === null) c = '#' + o.material.color.getHexString(); }); return c; };
  const wearsPreset = (id) => { const r = arFind(id); let ok = true, seen = 0;
    r.node.traverse(o => { if (o.isMesh && !o.userData.sub) { seen++; if (o.material !== arMat(r.mat)) ok = false; } });
    return ok && seen > 0; };
  const trisOf = (ids) => { let t = 0; ids.forEach(id => { const r = arFind(id);
    r.node.traverse(o => { if (o.isMesh && o.geometry) { const g = o.geometry;
      t += g.index ? g.index.count / 3 : g.attributes.position.count / 3; } }); }); return t; };
  const toast = () => document.getElementById('ar-toast').innerHTML;

  R.visible_records = AR.objs.filter(o => o.node && !o.hidden).length;

  /* ── d_bbox ── */
  arTool('d_bbox', {on: true}); tick();
  R.bbox_count = S().boxes; R.bbox_state = S().state.bbox; R.bbox_toast = toast();
  arSelect(['o2']); tick();
  R.bbox_colors = S().box_colors.slice().sort().join(',');

  /* ── d_colorby ── */
  arTool('d_colorby', {by: 'storey'}); tick();
  R.col_by = S().state.colorby; R.col_legend = S().legend;
  R.col_s0 = firstMeshCol('o1'); R.col_s1 = firstMeshCol('o3');
  arTool('d_colorby', {by: 'tag'}); tick();
  R.col_tagged = firstMeshCol('o1'); R.col_untagged = firstMeshCol('o2');
  arTool('d_colorby', {by: 'off'}); tick();
  R.col_off = S().state.colorby; R.col_legend_off = S().legend;
  R.col_restored = wearsPreset('o1') && wearsPreset('o2') && wearsPreset('o3');
  arTool('d_colorby'); tick();                       /* no args = cycle: off -> material */
  R.col_cycled = S().state.colorby;
  arTool('d_colorby', {by: 'off'}); tick();

  /* ── d_labels ── */
  arTool('d_labels', {on: true}); tick();
  R.lbl_on = S().labels; R.lbl_state = S().state.labels;
  arTool('d_labels', {on: false}); tick();
  R.lbl_off = S().labels;

  /* ── d_ground: with shadows ON, our switch beats t_sun's coupling ── */
  AR.shadows = true; AR.renderer.shadowMap.enabled = true; AR.sun.castShadow = true;
  AR.ground.visible = true;                          /* what t_sun's act does */
  arTool('d_ground', {on: false}); tick();
  R.gnd_off = S().ground_visible;
  AR.ground.visible = true; tick();                  /* t_sun tries to bring it back */
  R.gnd_still_off = S().ground_visible;
  arTool('d_ground', {on: true}); tick();
  R.gnd_on = S().ground_visible; R.gnd_state = S().state.ground;

  /* ── d_transp ── */
  const glass = arMat('mat_glass');
  arTool('d_transp', {mode: 'sorted'}); tick();
  R.tq_sorted = S().state.transp; R.tq_depthwrite = glass.depthWrite; R.tq_sort_objects = S().sort_objects;
  arTool('d_transp', {mode: 'dithered'}); tick();
  R.tq_dithered = S().state.transp;
  R.tq_alphamap = !!glass.alphaMap; R.tq_alphatest = glass.alphaTest;
  R.tq_checker = glass.alphaMap ? [glass.alphaMap.image.width, glass.alphaMap.image.height] : null;
  arTool('d_transp', {mode: 'fast'}); tick();
  R.tq_fast_alphamap = !!glass.alphaMap; R.tq_fast_depthwrite = glass.depthWrite;

  /* ── d_backface ── */
  arTool('d_backface', {mode: 'cull'}); tick();
  const mats = Object.keys(AR.matCache).map(k => AR.matCache[k]);
  R.bf_mats = mats.length;
  R.bf_all_front = mats.length > 0 && mats.every(m => m.side === THREE.FrontSide);
  arSelect(['o1', 'o2']);
  arTool('d_backface', {mode: 'normals'}); tick();
  R.bf_mode = S().state.backface;
  R.bf_tris = trisOf(['o1', 'o2']); R.bf_verts = S().normal_verts;
  R.bf_all_double = Object.keys(AR.matCache).every(k => AR.matCache[k].side === THREE.DoubleSide);
  arTool('d_backface', {mode: 'double'}); tick();
  R.bf_cleared = S().normal_verts;

  /* ── the state is per drawing, in AR.doc.ext ── */
  R.doc_ext = JSON.parse(JSON.stringify(AR.doc.ext.display_helpers || {}));

  /* ── a removed record loses its box ── */
  arSelect([]);
  arRemove(arFind('o3')); tick();
  R.bbox_after_remove = S().boxes; R.records_left = AR.objs.length;
  arTool('d_bbox', {on: false}); tick();
  R.bbox_final = S().boxes;
  return R;
}"""

r = browser_eval(JS, doc=DOC)
v = r['value'] or {}
check('no page errors through the whole pass', not r['errors'], r['errors'])

check(
    'd_bbox draws one helper per visible record (3)',
    v.get('visible_records') == 3 and v.get('bbox_count') == 3 and v.get('bbox_state') is True,
    v,
)
check(
    'd_bbox colours the selection amber (#ffb020) and the rest grey (#4a5060)',
    v.get('bbox_colors') == '#4a5060,#4a5060,#ffb020',
    v.get('bbox_colors'),
)
check(
    'd_bbox drops the helper of a removed record after a tick',
    v.get('bbox_after_remove') == 2 and v.get('records_left') == 2,
    v,
)
check('d_bbox off removes every helper', v.get('bbox_final') == 0, v)

check(
    'd_colorby storey gives the two storeys different mesh colours',
    v.get('col_s0') and v.get('col_s1') and v.get('col_s0') != v.get('col_s1'),
    [v.get('col_s0'), v.get('col_s1')],
)
check(
    'd_colorby shows a legend while a colouring is active, and takes it away at off',
    v.get('col_legend') is True and v.get('col_legend_off') is False,
    v,
)
check(
    'd_colorby tag separates the tagged object from the grey untagged one',
    v.get('col_tagged') != v.get('col_untagged') and v.get('col_untagged') == '#808080',
    [v.get('col_tagged'), v.get('col_untagged')],
)
check(
    'd_colorby off restores each mesh to arMat(rec.mat) identity',
    v.get('col_off') == 'off' and v.get('col_restored') is True,
    v,
)
check('d_colorby with no args cycles off -> material', v.get('col_cycled') == 'material', v.get('col_cycled'))

check(
    'd_labels puts one sprite over every visible record and takes them away again',
    v.get('lbl_on') == 3 and v.get('lbl_state') is True and v.get('lbl_off') == 0,
    v,
)

check(
    'd_ground hides the plane with shadows ON, and holds it hidden against t_sun',
    v.get('gnd_off') is False and v.get('gnd_still_off') is False,
    v,
)
check('d_ground on shows it again and the state is explicit', v.get('gnd_on') is True and v.get('gnd_state') is True, v)

check(
    "d_transp 'sorted' sets depthWrite false on the glass material and sorts the renderer",
    v.get('tq_sorted') == 'sorted' and v.get('tq_depthwrite') is False and v.get('tq_sort_objects') is True,
    v,
)
check(
    "d_transp 'dithered' puts an 8x8 checkerboard alphaMap on the glass with alphaTest 0.5",
    v.get('tq_dithered') == 'dithered'
    and v.get('tq_alphamap') is True
    and v.get('tq_alphatest') == 0.5
    and v.get('tq_checker') == [8, 8],
    v,
)
check(
    "d_transp 'fast' takes the alphaMap off and gives glass depthWrite back",
    v.get('tq_fast_alphamap') is False and v.get('tq_fast_depthwrite') is True,
    v,
)

check(
    "d_backface 'cull' sets side FrontSide on every cached material",
    v.get('bf_all_front') is True and (v.get('bf_mats') or 0) >= 3,
    v,
)
check(
    "d_backface 'normals' draws tris x 2 vertices for the selection, and goes back to DoubleSide",
    v.get('bf_mode') == 'normals'
    and v.get('bf_tris', 0) > 0
    and v.get('bf_verts') == v.get('bf_tris', 0) * 2
    and v.get('bf_all_double') is True,
    v,
)
check("d_backface 'double' clears the normals lines", v.get('bf_cleared') == 0, v)

check(
    'every setting is kept per drawing in AR.doc.ext.display_helpers',
    (v.get('doc_ext') or {}).get('colorby') == 'off'
    and (v.get('doc_ext') or {}).get('transp') == 'fast'
    and (v.get('doc_ext') or {}).get('ground') is True
    and set(v.get('doc_ext') or {}) == {'bbox', 'ground', 'labels', 'colorby', 'transp', 'backface'},
    v.get('doc_ext'),
)

# ── 3. the assistant may press all six, with args ────────────────────────────
from zyg_workflows import arch_assistant as A  # noqa: E402

check(
    'all six ids are declared pressable (EXT_BUTTONS)',
    all(i in A.EXT_BUTTONS for i in IDS),
    sorted(A.EXT_BUTTONS & set(IDS)),
)
txt, d = assistant('press_button', {'id': 'd_colorby', 'args': {'by': 'storey'}})
check(
    'the assistant presses d_colorby with its argument',
    txt.startswith('pressed')
    and d.ui[-1]['args']['id'] == 'd_colorby'
    and d.ui[-1]['args'].get('args') == {'by': 'storey'},
    (txt, d.ui[-1:]),
)
txt2, d2 = assistant('press_button', {'id': 'd_backface', 'args': {'mode': 'cull'}})
check(
    'the assistant presses d_backface with its argument',
    txt2.startswith('pressed') and d2.ui[-1]['args'].get('args') == {'mode': 'cull'},
    (txt2, d2.ui[-1:]),
)
PROMPTS = '\n'.join(A.EXT_PROMPTS)
check(
    'the prompt paragraph names every icon and its argument',
    all(i in PROMPTS for i in IDS) and '"by"' in PROMPTS and '"mode"' in PROMPTS and '"on"' in PROMPTS,
    [i for i in IDS if i not in PROMPTS],
)

finish()
