# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_light_lamps_env.py — proof for the Lighting family.

Three icons that were placeholders (l_hdri, l_lamp, l_ies) and three new kinds
(light_point, light_spot, light_area). What is proved here:

  · the icons carry no stub flag, no dashed class, no [placeholder] tooltip;
  · l_hdri really loads a Radiance file through RGBELoader and PMREM and leaves
    a TEXTURE in AR.scene.environment (act() returns a Promise the harness
    awaits), and 'off' puts it back;
  · l_lamp places a record in the cell it was given AND a real THREE light of
    the matching class appears in AR.scene at the record's position after a
    tick — and vanishes when the record does;
  · l_ies parses IESNA LM-63 in the browser, returns n_v x n_h candela values,
    writes p.ies and a plausible beam angle onto the selected spot, and opens
    the polar-plot sheet;
  · the server ext serves the .hdr as image/vnd.radiance and fences the name;
  · the assistant's twins do the same job on a Drawing, and its Python parser
    agrees with the browser's JS parser to the candela.

4 browser_eval calls (icon_state is the 4th), 1 blender_kinds.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import (
    assistant,
    blender_kinds,
    browser_eval,  # noqa: E402
    check,
    finish,
    icon_state,
    rail_has,
    server_ext,
)

ICONS = ['l_hdri', 'l_lamp', 'l_ies']
SKY = 'moonless_golf'
IES = '007cfb11e343e2f42e3b476be4ab684e'  # BEGA narrow LED downlight, 321 lm, 9 W
IES_WIDE = '02a7562c650498ebb301153dbbf59207'  # BEGA wide floodlight, 37 x 37 angles

# ── the server ext: the two libraries on disk ────────────────────────────────
L = server_ext('light_lamps_env', 'list', {})
names = [i['name'] for i in (L.get('items') or [])]
check(
    'the HDRI library lists three CC0 skies with their licence',
    L.get('ok') and len(names) >= 3 and SKY in names and 'polyhaven.com/license' in (L.get('licence') or ''),
    L,
)
check(
    'every sky is a real 1k HDRI (> 500 kB on disk)',
    all(i['kb'] > 500 for i in L['items']),
    [(i['name'], i['kb']) for i in L['items']],
)

H = server_ext('light_lamps_env', 'hdri', {'name': SKY}, method='GET')
check(
    'GET hdri?name= returns Radiance bytes (> 100 kB, image/vnd.radiance, #?RADIANCE header)',
    len(H.get('bytes') or b'') > 100 * 1024
    and H.get('mime') == 'image/vnd.radiance'
    and (H.get('bytes') or b'')[:10] == b'#?RADIANCE',
    {'mime': H.get('mime'), 'bytes': len(H.get('bytes') or b''), 'head': (H.get('bytes') or b'')[:12]},
)
F = server_ext('light_lamps_env', 'hdri', {'name': '../../../etc/passwd'})
check('a name outside the library is a 404, never a path', F.get('code') == 404, F)

IL = server_ext('light_lamps_env', 'ies_list', {})
ies_names = [i['name'] for i in (IL.get('items') or [])]
check('the IES library lists two MIT profiles', IL.get('ok') and IES in ies_names and IES_WIDE in ies_names, IL)
IT = server_ext('light_lamps_env', 'ies', {'name': IES}, method='GET')
check(
    'GET ies?name= returns the LM-63 text',
    (IT.get('bytes') or b'').startswith(b'IESNA') and 'text/plain' in (IT.get('mime') or ''),
    IT.get('mime'),
)
PY = server_ext('light_lamps_env', 'ies_info', {'name': IES}).get('photometry') or {}
check(
    'the server parses the profile: 73x1 angles, 9 W, ~321 lm (the file declares "321 lm")',
    PY.get('n_v') == 73
    and PY.get('n_h') == 1
    and PY.get('watts') == 9.0
    and 315 <= PY.get('lumens', 0) <= 330
    and 10 <= PY.get('beam_angle', 0) <= 60,
    PY,
)

check(
    'the three lamp kinds are on the library rail',
    not rail_has(['light_point', 'light_spot', 'light_area']),
    rail_has(['light_point', 'light_spot', 'light_area']),
)

# ── the tab, call 1: l_lamp places, the light follows, deleting removes it ───
r1 = browser_eval(
    """() => {
  const out = {};
  /* every press goes through arTool — the path a click takes. arTool returns
     nothing, so what act() answered is read back with lleLast(id). */
  arTool('l_lamp', {kind: 'light_spot', cell: 'D5', storey: 0, watts: 24, colour: '#ff0000'});
  const res = lleLast('l_lamp');
  out.place = res;
  const rec = arFind(res.id);
  out.rec = {kind: rec.kind, x: rec.x, y: rec.y, z: rec.z, p: rec.p, cell: arCellName(rec.x, rec.z)};
  arTick();                                    /* the ticks hook makes/moves the real lights */
  const lit = [];
  AR.scene.traverse(o => { if (o.isLight && o.userData && o.userData.lle) lit.push(
    {type: o.type, id: o.userData.arId, pos: [o.position.x, o.position.y, o.position.z],
     angle: o.angle, dist: o.distance, col: o.color.getHexString(),
     tgt: o.target ? [o.target.position.x, o.target.position.y, o.target.position.z] : null}); });
  out.lights = lit;
  /* a second kind, and the marker geometry really is geometry */
  arTool('l_lamp', {kind: 'area', cell: 'F7', storey: 1});
  const p2 = lleLast('l_lamp');
  arTick();
  let n = 0, tris = 0;
  AR.scene.traverse(o => { if (o.isLight && o.userData && o.userData.lle) n++; });
  arFind(p2.id).node.traverse(m => { if (m.isMesh && m.geometry) tris += m.geometry.index
    ? m.geometry.index.count / 3 : m.geometry.attributes.position.count / 3; });
  out.two = {n: n, kind: arFind(p2.id).kind, y: arFind(p2.id).y, tris: tris,
             label: arKindLabel('light_area'), types: []};
  AR.scene.traverse(o => { if (o.isLight && o.userData && o.userData.lle) out.two.types.push(o.type); });
  /* remove the record -> the light goes with it */
  arRemove(arFind(res.id)); arTick();
  let after = [];
  AR.scene.traverse(o => { if (o.isLight && o.userData && o.userData.lle) after.push(o.userData.arId); });
  out.after_remove = after;
  /* clicking the icon with no args ARMS the rail's placement mechanism */
  arTool('l_lamp');
  out.armed = {res: lleLast('l_lamp'), tool: AR.tool, place: AR.place ? {kind: AR.place.kind, p: AR.place.p} : null};
  out.errors_none = true;
  return out;
}""",
    doc={'objects': []},
)
v = r1['value']
check(
    'l_lamp placed a light_spot in the cell it was given, under storey 0\u2019s ceiling',
    v['rec']['kind'] == 'light_spot' and v['rec']['cell'] == 'D5' and abs(v['rec']['y'] - 2.4) < 1e-6,
    v['rec'],
)
check(
    'the icon\u2019s args reached the record (24 W, red)',
    v['rec']['p']['w'] == 24 and v['rec']['p']['col'] == '#ff0000',
    v['rec']['p'],
)
sp = [l for l in v['lights'] if l['id'] == v['place']['id']]
check(
    'after arTick a real THREE SpotLight exists at the record\u2019s position',
    len(sp) == 1
    and sp[0]['type'] == 'SpotLight'
    and abs(sp[0]['pos'][0] - v['rec']['x']) < 1e-6
    and abs(sp[0]['pos'][1] - v['rec']['y']) < 1e-6
    and abs(sp[0]['pos'][2] - v['rec']['z']) < 1e-6,
    sp,
)
check(
    'the spot carries the record\u2019s colour, range and cone, and aims 2 m below itself',
    sp
    and sp[0]['col'] == 'ff0000'
    and abs(sp[0]['dist'] - 12) < 1e-6
    and abs(sp[0]['angle'] - 35 * 3.141592653589793 / 180) < 1e-6
    and abs(sp[0]['tgt'][1] - (v['rec']['y'] - 2)) < 1e-6,
    sp,
)
check(
    'a second lamp of another kind gives a second light of the matching class, with real marker geometry',
    v['two']['n'] == 2
    and 'RectAreaLight' in v['two']['types']
    and v['two']['tris'] > 0
    and abs(v['two']['y'] - (2.7 + 2.4)) < 1e-6
    and v['two']['label'] == 'Area light',
    v['two'],
)
check(
    'removing the record removes its light',
    v['place']['id'] not in v['after_remove'] and len(v['after_remove']) == 1,
    v['after_remove'],
)
check(
    'l_lamp with no args arms the rail\u2019s place tool with a point light',
    v['armed']['tool'] == 'place'
    and v['armed']['place']['kind'] == 'light_point'
    and v['armed']['place']['p']['w'] == 12,
    v['armed'],
)
check('no page errors while placing lamps', not r1['errors'], r1['errors'])

# ── the tab, call 2: l_hdri really loads a sky ───────────────────────────────
r2 = browser_eval(
    """() => {
  /* act() answers a promise; arTool swallows it, lleLast hands it back to await */
  arTool('l_hdri', {name: '%s'});
  return Promise.resolve(lleLast('l_hdri')).then(res => {
    const e = AR.scene.environment;
    const on = {res: res, isTexture: !!(e && e.isTexture), envClass: e ? e.constructor.name : null,
                mapping: e ? e.mapping : null, w: e ? e.image && e.image.width : 0,
                doc: JSON.parse(JSON.stringify(AR.doc.ext.light_lamps_env || {})),
                lit: !!AR_EXT.tools.l_hdri.on(),
                toast: document.getElementById('ar-toast').innerHTML};
    arTool('l_hdri', {name: 'off'});
    return Promise.resolve(lleLast('l_hdri')).then(() => {
      on.off = {env: AR.scene.environment, hdri: (AR.doc.ext.light_lamps_env || {}).hdri,
                lit: !!AR_EXT.tools.l_hdri.on()};
      arTool('l_hdri');                                        /* no args: cycle on from off */
      return Promise.resolve(lleLast('l_hdri')).then(cyc => {
        on.cycled = {res: cyc, hdri: (AR.doc.ext.light_lamps_env || {}).hdri,
                     isTexture: !!(AR.scene.environment && AR.scene.environment.isTexture)};
        return on;
      });
    });
  });
}"""
    % SKY
)
w = r2['value']
check(
    'l_hdri loaded the .hdr through RGBELoader + PMREM into AR.scene.environment as a texture',
    w['isTexture'] and w['res']['hdri'] == SKY and (w['w'] or 0) > 0,
    {k: w[k] for k in ('res', 'isTexture', 'envClass', 'w')},
)
check(
    'the sky is remembered in AR.doc.ext.light_lamps_env and the icon latches on',
    w['doc'].get('hdri') == SKY and w['lit'] is True,
    {'doc': w['doc'], 'lit': w['lit']},
)
check('the toast names the sky and its licence', 'Moonless' in w['toast'] and 'CC0' in w['toast'], w['toast'])
check(
    'l_hdri {name:"off"} drops the environment and unlatches',
    w['off']['env'] is None and w['off']['hdri'] is None and w['off']['lit'] is False,
    w['off'],
)
check(
    'pressing l_hdri with no args cycles a sky back on',
    bool(w['cycled']['hdri']) and w['cycled']['isTexture'],
    w['cycled'],
)
check('no page errors while loading the sky', not r2['errors'], r2['errors'])

# ── the tab, call 3: l_ies parses, plots and applies ─────────────────────────
r3 = browser_eval(
    """() => {
  const rec = arNewObj('light_spot', {w: 20, r: 12, angle: 35, pen: 0.3, col: '#ffe9c4'}, 3, 4, 2.4);
  arSelect([rec.id]);
  arTool('l_ies', {name: '%s'});
  return Promise.resolve(lleLast('l_ies')).then(res => {
    arTick();
    let ang = null;
    AR.scene.traverse(o => { if (o.isLight && o.userData && o.userData.arId === rec.id) ang = o.angle; });
    const sheet = document.getElementById('ar-sheet');
    const html = sheet ? sheet.innerHTML : '';
    /* the wide profile too: 37 x 37 = 1369 candela values through the same parser */
    return fetch('/inspect/api/architecture/ext/light_lamps_env/ies?name=%s')
      .then(r => r.text()).then(txt => {
        const ph = llePhotometry(txt);
        return {res: res, p: JSON.parse(JSON.stringify(rec.p)), lightAngle: ang,
                sheet: {open: !!(sheet && sheet.offsetParent !== null), svg: (html.match(/<svg/g) || []).length,
                        rows: (html.match(/beam \\(half intensity\\)/g) || []).length,
                        peak: /peak intensity/.test(html)},
                wide: {n_v: ph.n_v, n_h: ph.n_h, cd: ph.cd.length, beam: ph.beam_angle,
                       lumens: ph.lumens, watts: ph.watts, peak: ph.peak_cd}};
      });
  });
}"""
    % (IES, IES_WIDE)
)
u = r3['value']
check(
    'l_ies parsed the profile in the browser: 73 x 1 = 73 candela values',
    u['res']['n_v'] == 73 and u['res']['n_h'] == 1 and u['res']['cd'] == 73,
    u['res'],
)
check(
    'it applied the measured beam to the selected spot (p.ies set, angle plausible 10-60\u00b0)',
    u['p']['ies'] == IES and 10 <= u['p']['angle'] <= 60 and abs(u['p']['angle'] - 27.2) < 0.5,
    u['p'],
)
check(
    'the record also took the luminaire\u2019s flux, peak intensity and input power',
    315 <= u['p']['ies_lm'] <= 330 and u['p']['ies_cd'] == 337 and u['p']['w'] == 9,
    u['p'],
)
check(
    'the live SpotLight followed the new angle after a tick',
    abs(u['lightAngle'] - u['p']['angle'] * 3.141592653589793 / 180) < 1e-9,
    {'light': u['lightAngle'], 'p': u['p']['angle']},
)
check(
    'the polar plot sheet opened with the SVG curve and the numbers',
    u['sheet']['open'] and u['sheet']['svg'] == 1 and u['sheet']['rows'] == 1 and u['sheet']['peak'],
    u['sheet'],
)
check(
    'the JS parser handles the 37 x 37 profile too: 1369 candela values',
    u['wide']['n_v'] == 37 and u['wide']['n_h'] == 37 and u['wide']['cd'] == 37 * 37,
    u['wide'],
)
check(
    'the browser\u2019s LM-63 arithmetic equals the server\u2019s to the candela (73 x 1 sample)',
    abs(u['res']['beam_angle'] - PY['beam_angle']) < 1e-6 and abs(u['res']['lumens'] - PY['lumens']) < 0.05,
    {
        'js': {'beam': u['res']['beam_angle'], 'lm': u['res']['lumens']},
        'py': {'beam': PY['beam_angle'], 'lm': PY['lumens']},
    },
)
check('no page errors while reading the profile', not r3['errors'], r3['errors'])

# ── the icons themselves ─────────────────────────────────────────────────────
st = icon_state(ICONS)
check(
    'l_hdri / l_lamp / l_ies are real icons: no stub flag, no dashed class, no [placeholder] tooltip',
    all(
        st[i].get('exists') and not st[i].get('stub') and not st[i].get('dashed') and not st[i].get('tip_placeholder')
        for i in ICONS
    ),
    st,
)

# ── the assistant's twins ────────────────────────────────────────────────────
txt, d = assistant('place_light', {'kind': 'spot', 'cell': 'D5', 'storey': 0, 'watts': 24})
rec = d.objs[-1]
check(
    'place_light drops a light_spot at the very cell centre the ICON used for D5, on that storey',
    rec['kind'] == 'light_spot'
    and abs(rec['x'] - v['rec']['x']) < 1e-6
    and abs(rec['z'] - v['rec']['z']) < 1e-6
    and abs(rec['x'] - -146.5) < 1e-6
    and abs(rec['z'] - -145.5) < 1e-6
    and abs(rec['y'] - 2.4) < 1e-6
    and rec['p']['w'] == 24,
    (txt, rec, v['rec']),
)
txt2, d = assistant('set_ies', {'which': 'all', 'name': IES}, drawing=d)
check(
    'set_ies gives that spot the profile the icon would, from the same parser',
    d.objs[-1]['p']['ies'] == IES
    and abs(d.objs[-1]['p']['angle'] - u['p']['angle']) < 1e-9
    and d.objs[-1]['p']['ies_lm'] == u['p']['ies_lm'],
    (txt2, d.objs[-1]['p']),
)
txt3, _ = assistant('set_ies', {'which': 'all', 'name': 'nope'})
check('an unknown profile is refused, not guessed', txt3.startswith('refused'), txt3)
txt4, d4 = assistant('list_hdri', {})
check('list_hdri names the skies and their licence', SKY in txt4 and 'CC0' in txt4, txt4)
txt5, d5 = assistant('set_hdri', {'name': SKY}, drawing=d4)
check(
    'set_hdri writes doc.ext and asks the tab to press l_hdri with the name',
    d5.ext['light_lamps_env']['hdri'] == SKY
    and d5.to_doc()['ext']['light_lamps_env']['hdri'] == SKY
    and d5.ui[-1] == {'cmd': 'tool', 'args': {'id': 'l_hdri', 'args': {'name': SKY}}},
    (txt5, d5.ui[-1]),
)
txt6, _ = assistant('press_button', {'id': 'l_lamp', 'args': {'kind': 'light_point', 'cell': 'C4'}})
check('the model may press l_lamp with args', txt6.startswith('pressed'), txt6)

# ── Blender ──────────────────────────────────────────────────────────────────
B = blender_kinds([{'kind': 'light_point', 'p': {'w': 12, 'r': 8, 'col': '#ffe9c4'}}])
check(
    'light_point builds a marker mesh in Blender',
    (B.get('light_point') or {}).get('polys', 0) > 0,
    B.get('light_point'),
)

finish()
