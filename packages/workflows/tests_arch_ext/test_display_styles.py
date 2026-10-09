# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_display_styles.py — proves the six Display switches.

Three browser launches: icon_state (the placeholder marks are gone), one big
evaluation that drives every switch on a textured wall and a glass window and
reads the LIVE materials and the LIVE overlay objects back, and one that opens
a drawing whose doc.ext already asks for a style and checks the tab honours it
without anything being pressed.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, browser_eval, icon_state  # noqa: E402

IDS = ['d_tex', 'd_shaded', 'd_mono', 'd_hidden', 'd_edges', 'd_sketchy']

DOC = {
    'objects': [
        {
            'id': 'w1',
            'kind': 'wall',
            'p': {'len': 4, 'h': 2.7, 't': 0.24, 'holes': []},
            'x': 0,
            'y': 0,
            'z': 0,
            'name': 'Test wall',
        },
        {
            'id': 'n1',
            'kind': 'window',
            'p': {'w': 1.2, 'h': 1.4, 'sill': 0.9},
            'x': 0,
            'y': 0,
            'z': 0,
            'mat': 'mat_glass',
            'name': 'Test window',
        },
    ]
}

# ── 1. the icons stopped being placeholders ──────────────────────────────────
st = icon_state(IDS)
for i in IDS:
    s = st.get(i, {})
    check(
        '%s is wired: exists, no stub flag, no dashed border, no [placeholder] tip' % i,
        s.get('exists') and not s.get('stub') and not s.get('dashed') and not s.get('tip_placeholder'),
        s,
    )

# ── 2. every switch, on the live document ────────────────────────────────────
BIG = r"""() => {
  const R = {};
  const acg = Object.keys(AR.matDefs).find(k => k.startsWith('acg_'));
  R.acg = acg || null;
  const wall = AR.objs.find(o => o.kind === 'wall');
  const win  = AR.objs.find(o => o.kind === 'window');
  R.have = !!(wall && win);
  if (!R.have || !acg) return R;
  wall.mat = acg; arApplyMat(wall); arApplyUV(wall);
  arMat('mat_glass');

  const matOf = r => { let m = null; r.node.traverse(o => { if (o.isMesh && !m) m = o.material; }); return m; };
  const hex = m => '#' + m.color.getHexString();
  const count = r => { let mesh = 0, solid = 0, dash = 0;
    r.node.traverse(o => {
      if (o.isMesh) mesh++;
      else if (o.isLineSegments && o.userData && o.userData.dsOverlay) {
        if (o.material.isLineDashedMaterial) dash++; else solid++; } });
    return {mesh: mesh, solid: solid, dash: dash}; };
  const ovHash = r => { let h = 0; r.node.traverse(o => {
      if (o.isLineSegments && o.userData && o.userData.dsOverlay && !o.material.isLineDashedMaterial) {
        const p = o.geometry.attributes.position.array;
        for (let i = 0; i < Math.min(p.length, 90); i++) h = (Math.imul(h, 31) + Math.round(p[i] * 1e5)) | 0; } });
    return h; };
  const ons = () => ({tex: AR_EXT.tools.d_tex.on(), shaded: AR_EXT.tools.d_shaded.on(),
                      mono: AR_EXT.tools.d_mono.on(), hidden: AR_EXT.tools.d_hidden.on(),
                      edges: AR_EXT.tools.d_edges.on(), sketchy: AR_EXT.tools.d_sketchy.on()});

  arTool('d_tex', {on: true});
  R.plain = {map: !!matOf(wall).map, state: JSON.parse(JSON.stringify(arDisplayStyles())), on: ons()};

  /* d_tex --------------------------------------------------------------- */
  arTool('d_tex', {on: false});
  let m = matOf(wall);
  R.texOff = {map: !!m.map, normal: !!m.normalMap, col: hex(m), on: ons(),
              stashed: !!(m.userData._maps && m.userData._maps.map),
              defCol: (AR.matDefs[acg] || {}).col || null};
  arTool('d_tex', {on: true});
  m = matOf(wall);
  R.texOn = {map: !!m.map, normal: !!m.normalMap, col: hex(m), on: ons()};

  /* d_shaded ------------------------------------------------------------ */
  arTool('d_shaded', {on: true});
  m = matOf(wall);
  R.shaded = {col: hex(m), rough: m.roughness, map: !!m.map, on: ons(),
              style: arDisplayStyles().style};

  /* d_mono -------------------------------------------------------------- */
  arTool('d_mono', {on: true});
  const cols = {}; let nonGlassOk = true;
  Object.keys(AR.matCache).forEach(k => {
    const c = '#' + AR.matCache[k].color.getHexString();
    cols[k] = c;
    if (k.split('|')[0] !== 'mat_glass' && c !== '#f2f2f0') nonGlassOk = false; });
  R.mono = {cols: cols, nonGlassOk: nonGlassOk, n: Object.keys(cols).length,
            glassCached: !!AR.matCache['mat_glass'],
            glassOp: AR.matCache['mat_glass'] ? AR.matCache['mat_glass'].opacity : null,
            glassTransparent: AR.matCache['mat_glass'] ? AR.matCache['mat_glass'].transparent : null,
            on: ons(), style: arDisplayStyles().style};

  /* d_hidden ------------------------------------------------------------ */
  arTool('d_hidden', {on: true});
  arTick();
  m = matOf(wall);
  let dashOk = true, solidOk = true;
  wall.node.traverse(o => {
    if (!(o.isLineSegments && o.userData && o.userData.dsOverlay)) return;
    if (o.material.isLineDashedMaterial) {
      if (o.material.depthTest !== false || !o.geometry.attributes.lineDistance
          || o.material.dashSize !== 0.15 || o.material.gapSize !== 0.1) dashOk = false;
    } else if (o.material.depthTest !== true) solidOk = false; });
  R.hidden = {counts: count(wall), col: hex(m), rough: m.roughness, metal: m.metalness,
              dashOk: dashOk, solidOk: solidOk, on: ons(), style: arDisplayStyles().style,
              override: AR.scene.overrideMaterial === null, sun: !!AR.sun, hemi: !!AR.hemi};

  /* d_edges alone ------------------------------------------------------- */
  arTool('d_hidden', {on: false});
  arTool('d_edges', {on: true, weight: 1});
  arTick();
  R.edges = {counts: count(wall), on: ons(), weight: arDisplayStyles().weight,
             style: arDisplayStyles().style, map: !!matOf(wall).map};
  arTool('d_edges', {on: true, weight: 2});
  arTick();
  R.edges2 = {counts: count(wall), weight: arDisplayStyles().weight};
  arTool('d_edges', {on: true, weight: 1});
  arTick();

  /* d_sketchy ----------------------------------------------------------- */
  /* the wall's own material is a textured one, so its colour is white and
     desaturating white is a no-op — measure the face wash on a coloured preset */
  const sat = () => { const h = {h: 0, s: 0, l: 0}; arMat('mat_brick').color.getHSL(h); return h.s; };
  const plainCol = '#' + arMat('mat_brick').color.getHexString(), plainSat = sat();
  arTool('d_sketchy', {on: true});
  arTick();
  R.sketchy = {counts: count(wall), on: ons(), col: '#' + arMat('mat_brick').color.getHexString(),
               plainCol: plainCol, sat: sat(), plainSat: plainSat,
               opacity: (() => { let o2 = null; wall.node.traverse(o => {
                 if (o.isLineSegments && o.userData && o.userData.dsOverlay && o2 === null) o2 = o.material.opacity; });
                 return o2; })()};
  const h1 = ovHash(wall);
  arRebuild(wall);                       /* a new rec.node: the tick hook must notice */
  arTick();
  R.reseed = {h1: h1, h2: ovHash(wall), counts: count(wall)};

  /* overlays are dropped with the record --------------------------------- */
  arTool('d_sketchy', {on: false});
  const extra = arNewObj('slab', {w: 2, d: 2, t: 0.2}, 8, 0, 0);
  arTick();
  R.extraBefore = {counts: count(extra), tracked: arDisplayStylesOverlays().indexOf(extra.id) >= 0};
  const eid = extra.id;
  arRemove(extra);
  arTick();
  R.extraAfter = {tracked: arDisplayStylesOverlays().indexOf(eid) >= 0,
                  wall: count(wall), ids: arDisplayStylesOverlays()};

  /* off again ------------------------------------------------------------ */
  arTool('d_edges', {on: false});
  arTick();
  R.edgesOff = {counts: count(wall), on: ons(), overlays: arDisplayStylesOverlays().length};
  arTool('d_tex', {on: true});
  arTick();
  R.back = {map: !!matOf(wall).map, col: hex(matOf(wall)), on: ons(),
            state: JSON.parse(JSON.stringify(arDisplayStyles()))};
  return R;
}"""

r = browser_eval(BIG, doc=DOC)
v = r['value'] or {}
check('the test document built a textured wall and a glass window', v.get('have') and v.get('acg'), v.get('acg'))

t0, t1 = v.get('texOff', {}), v.get('texOn', {})
check(
    'd_tex off nulls the maps on the live material and paints the preset colour',
    t0.get('map') is False and t0.get('normal') is False and t0.get('col') == (t0.get('defCol') or '').lower(),
    t0,
)
check('d_tex off stashes the maps on m.userData._maps', t0.get('stashed') is True, t0)
check('d_tex on restores the very same maps', t1.get('map') is True and t1.get('normal') is True, t1)
check(
    'd_tex on() follows the state',
    t0.get('on', {}).get('tex') is False and t1.get('on', {}).get('tex') is True,
    [t0.get('on'), t1.get('on')],
)

sh = v.get('shaded', {})
check(
    'd_shaded paints every material neutral grey at roughness 0.85 with the maps off',
    sh.get('col') == '#9a9a94' and abs((sh.get('rough') or 0) - 0.85) < 1e-6 and sh.get('map') is False,
    sh,
)
check(
    'd_shaded on() is true and the other styles went off',
    sh.get('style') == 'shaded'
    and sh.get('on', {}).get('shaded') is True
    and sh.get('on', {}).get('mono') is False
    and sh.get('on', {}).get('hidden') is False
    and sh.get('on', {}).get('tex') is False,
    sh.get('on'),
)

mo = v.get('mono', {})
check(
    'd_mono makes every non-glass material #f2f2f0',
    mo.get('nonGlassOk') is True and (mo.get('n') or 0) >= 2,
    mo.get('cols'),
)
check(
    'd_mono leaves the glass transparent (opacity < 1)',
    mo.get('glassCached') is True and (mo.get('glassOp') or 1) < 1 and mo.get('glassTransparent') is True,
    mo,
)
check(
    'd_mono is mutually exclusive with shaded and hidden',
    mo.get('style') == 'mono'
    and mo.get('on', {}).get('mono') is True
    and mo.get('on', {}).get('shaded') is False
    and mo.get('on', {}).get('hidden') is False,
    mo.get('on'),
)

hi = v.get('hidden', {})
hc = hi.get('counts', {})
check(
    'd_hidden adds TWO LineSegments per mesh, one of them dashed',
    (hc.get('mesh') or 0) > 0 and hc.get('solid') == hc.get('mesh') and hc.get('dash') == hc.get('mesh'),
    hc,
)
check(
    'the dashed pass is depth-test-off with line distances and .15/.1 dashes, the solid pass depth-tested',
    hi.get('dashOk') is True and hi.get('solidOk') is True,
    hi,
)
check(
    'd_hidden makes the faces white and flat, and keeps the lights (no scene overrideMaterial)',
    hi.get('col') == '#ffffff'
    and hi.get('rough') == 1
    and hi.get('metal') == 0
    and hi.get('override') is True
    and hi.get('sun') is True
    and hi.get('hemi') is True,
    hi,
)
check(
    'd_hidden on() is true, forces the edges on and turns the other styles off',
    hi.get('style') == 'hidden'
    and hi.get('on', {}).get('hidden') is True
    and hi.get('on', {}).get('edges') is True
    and hi.get('on', {}).get('mono') is False
    and hi.get('on', {}).get('shaded') is False,
    hi.get('on'),
)

ed, ed2 = v.get('edges', {}), v.get('edges2', {})
ec = ed.get('counts', {})
check(
    'd_edges alone adds exactly one EdgesGeometry overlay per mesh and no dashed pass',
    (ec.get('mesh') or 0) > 0 and ec.get('solid') == ec.get('mesh') and ec.get('dash') == 0,
    ec,
)
check(
    'd_edges on() is true and it left the face style alone (textures back on)',
    ed.get('on', {}).get('edges') is True and ed.get('style') == 'textured' and ed.get('map') is True,
    ed,
)
check(
    'd_edges weight 2 draws the outline twice (WebGL has no line width)',
    ed2.get('weight') == 2 and ed2.get('counts', {}).get('solid') == 2 * (ec.get('mesh') or 0),
    ed2,
)

sk = v.get('sketchy', {})
skc = sk.get('counts', {})
check(
    'd_sketchy doubles the outline overlay and draws it at 0.6 opacity',
    skc.get('solid') == 2 * (ec.get('mesh') or 0)
    and skc.get('dash') == 0
    and abs((sk.get('opacity') or 0) - 0.6) < 1e-6,
    sk,
)
check(
    'd_sketchy desaturates the faces by 30 % and reads on()',
    sk.get('col') != sk.get('plainCol')
    and (sk.get('plainSat') or 0) > 0
    and abs((sk.get('sat') or 0) - (sk.get('plainSat') or 0) * 0.7) < 1e-3
    and sk.get('on', {}).get('sketchy') is True
    and sk.get('on', {}).get('edges') is True,
    sk,
)
rs = v.get('reseed', {})
check(
    'the wobble is seeded per record: a rebuilt node gets an identical overlay back',
    rs.get('h1') == rs.get('h2')
    and rs.get('h1') not in (0, None)
    and rs.get('counts', {}).get('solid') == skc.get('solid'),
    rs,
)

eb, ea = v.get('extraBefore', {}), v.get('extraAfter', {})
check(
    'a new record gets its own overlay on the next tick',
    eb.get('tracked') is True and (eb.get('counts', {}).get('solid') or 0) >= 1,
    eb,
)
check(
    'removing a record removes its overlay after arTick()',
    ea.get('tracked') is False and (ea.get('wall', {}).get('solid') or 0) >= 1,
    ea,
)

eo = v.get('edgesOff', {})
check(
    'switching the edges off drops every overlay',
    eo.get('counts', {}).get('solid') == 0
    and eo.get('counts', {}).get('dash') == 0
    and eo.get('overlays') == 0
    and eo.get('on', {}).get('edges') is False,
    eo,
)
bk = v.get('back', {})
check(
    'pressing Textures on is the way home: maps back, plain state',
    bk.get('map') is True
    and bk.get('col') == '#ffffff'
    and bk.get('state', {}).get('style') == 'textured'
    and bk.get('state', {}).get('tex') == 1,
    bk,
)
check('no page errors while driving the six switches', not r['errors'], r['errors'])

# ── 3. a drawing that carries its own style is honoured at load time ─────────
LOAD = r"""() => {
  const wall = AR.objs.find(o => o.kind === 'wall');
  const matOf = r => { let m = null; r.node.traverse(o => { if (o.isMesh && !m) m = o.material; }); return m; };
  arTick();
  let solid = 0;
  wall.node.traverse(o => { if (o.isLineSegments && o.userData && o.userData.dsOverlay) solid++; });
  return {state: JSON.parse(JSON.stringify(arDisplayStyles())),
          col: '#' + matOf(wall).color.getHexString(), map: !!matOf(wall).map, solid: solid,
          on: {mono: AR_EXT.tools.d_mono.on(), edges: AR_EXT.tools.d_edges.on(),
               tex: AR_EXT.tools.d_tex.on()},
          out: arDocOut().ext};
}"""
LOAD_DOC = {
    'objects': DOC['objects'],
    'ext': {'display_styles': {'style': 'mono', 'tex': 0, 'edges': 1, 'sketchy': 0, 'weight': 2}},
}
r2 = browser_eval(LOAD, doc=LOAD_DOC)
w = r2['value'] or {}
check(
    'a loaded drawing gets its saved style applied without anything being pressed',
    w.get('state', {}).get('style') == 'mono' and w.get('col') == '#f2f2f0' and w.get('map') is False,
    w,
)
check(
    'the loaded edge setting drew the outlines too (weight 2 = two passes)',
    (w.get('solid') or 0) >= 2
    and w.get('on', {}).get('edges') is True
    and w.get('on', {}).get('mono') is True
    and w.get('on', {}).get('tex') is False,
    w,
)
check(
    'the style round-trips back out through arDocOut().ext',
    (w.get('out') or {}).get('display_styles', {}).get('style') == 'mono'
    and (w.get('out') or {}).get('display_styles', {}).get('weight') == 2,
    w.get('out'),
)
check('no page errors on the load path', not r2['errors'], r2['errors'])

# ── 4. the assistant may press all six, with args ───────────────────────────
for i in IDS:
    txt, d = assistant('press_button', {'id': i, 'args': {'on': True}})
    check(
        'assistant may press %s with args' % i,
        txt.startswith('pressed') and d.ui[-1]['args']['id'] == i and d.ui[-1]['args'].get('args') == {'on': True},
        txt,
    )
txt, d = assistant('press_button', {'id': 'd_edges', 'args': {'on': True, 'weight': 3}})
check('the weight travels with the press', d.ui[-1]['args']['args'] == {'on': True, 'weight': 3}, d.ui[-1])

txt, d = assistant('get_state', {}, doc={'objects': [], 'ext': {'display_styles': {'style': 'hidden', 'edges': 1}}})
check(
    'the assistant reads and writes back doc.ext.display_styles',
    d.ext.get('display_styles', {}).get('style') == 'hidden'
    and d.to_doc()['ext']['display_styles']['style'] == 'hidden',
    d.to_doc().get('ext'),
)

import zyg_workflows.arch_assistant_ext.display_styles as DSX  # noqa: E402

check(
    'BUTTONS declares all six ids and the prompt says the args',
    sorted(DSX.BUTTONS) == sorted(IDS) and 'weight' in DSX.PROMPT and '"on": true' in DSX.PROMPT,
    DSX.BUTTONS,
)

finish()
