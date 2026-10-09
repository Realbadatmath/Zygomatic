# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_site_context.py — the proof for the Site context family.

Five icons, each of which used to be a placeholder:

  st_bound  Site boundary (MODE)   corners clicked in, Enter closes, area labelled,
                                   bearings and lengths reported, setback insets
  st_sat    Aerial (SWITCH)        an OSM / Esri tile mosaic under the drawing, in metres
  st_veg    Planting (ACTION)      trees scattered inside the boundary at 3 m spacing
  st_road   Roads (MODE)           a chain of clicks, one road record per leg
  f_img     Underlay (ACTION)      an image on the ground at a width you give in metres

Everything is asserted on the DOCUMENT and on numbers: record counts, metres,
point-in-polygon, pairwise spacing, PNG bytes. Three headless-Chrome passes in
all (icon_state, the four drawing icons, the aerial), which is the budget.

The tile check is a REAL network fetch of a real OSM tile. If it fails it says
NETWORK and fails — a cached-only pass would prove nothing about the route.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, browser_eval, icon_state, server_ext  # noqa: E402

import zyg_workflows.arch_assistant_ext.site_context as SC  # noqa: E402
import zyg_workflows.arch_blender_ext.site_context as SB  # noqa: E402
import zyg_workflows.arch_server_ext.site_context as SS  # noqa: E402

ICONS = ['st_bound', 'st_sat', 'st_veg', 'st_road', 'f_img']

# ── 1. the placeholder mark is gone from all five ────────────────────────────
st = icon_state(ICONS)
for i in ICONS:
    s = st.get(i) or {}
    check(
        '%s is a real icon (exists, no stub flag, no dashed class, no [placeholder] tip)' % i,
        s.get('exists') and not s.get('stub') and not s.get('dashed') and not s.get('tip_placeholder'),
        s,
    )

# ── 2. the four drawing icons, in one live pass ──────────────────────────────
# A 20 x 20 m plot clicked in corner by corner, closed with Enter; then a 5 m
# setback, ten trees, a three-click road and a 2 x 2 px PNG underlay 10 m wide.
DRAW = r"""async () => {
  const out = {errors: []};
  const undo0 = AR.undo.length;
  // — st_bound: arm the mode, click four corners, press Enter —
  arTool('st_bound');
  out.armed = AR.tool;
  const C = [[-10,-10],[10,-10],[10,10],[-10,10]];
  for (const c of C) AR_EXT.modes.st_bound.click({x: c[0], z: c[1], y: 0});
  out.swallowedEnter = AR_EXT.modes.st_bound.key({key: 'Enter'});
  const bs = AR.objs.filter(o => o.kind === 'site_boundary');
  out.boundaries = bs.length;
  if (bs.length) {
    const b = bs[0];
    out.pts = b.p.pts;
    out.closed = b.p.closed;
    out.grp = b.grp;
    out.label = b._scLabel ? b._scLabel.userData.scText : null;
    out.parts = b.node ? b.node.children.filter(n => n.isLine || n.isLineSegments).length : 0;
    out.poly = site_context.boundary();
    out.area = site_context.area();
    out.legs = site_context.legs().map(L => [Number(L.len.toFixed(3)), Number(L.bearing.toFixed(1))]);
    out.sheet = (document.getElementById('ar-sheet') || {}).innerHTML || '';
  }
  // — st_bound {setback: 5}: a second, inset polygon —
  arTool('st_bound', {setback: 5});
  const sb = AR.objs.filter(o => o.kind === 'site_boundary' && o.meta && o.meta.setback);
  out.setbacks = sb.length;
  out.setbackArea = sb.length ? Math.abs(sb[0].p.pts.reduce((a, p, i, A) => {
      const q = A[(i + 1) % A.length]; return a + (p[0] * q[1] - q[0] * p[1]); }, 0) / 2) : 0;
  out.boundaryStillOuter = Math.round(site_context.area());
  // — st_veg {count: 10} —
  arTool('st_veg', {count: 10, inside: 'boundary'});
  const trees = AR.objs.filter(o => o.grp === 'planting');
  out.trees = trees.length;
  out.treeKinds = Array.from(new Set(trees.map(o => o.kind)));
  out.allInside = trees.every(o => site_context.inPoly(o.x, o.z, out.poly));
  let minGap = Infinity;
  for (let i = 0; i < trees.length; i++) for (let j = i + 1; j < trees.length; j++)
    minGap = Math.min(minGap, Math.hypot(trees[i].x - trees[j].x, trees[i].z - trees[j].z));
  out.minGap = isFinite(minGap) ? Number(minGap.toFixed(4)) : null;
  // — st_road: three clicks —
  arTool('st_road');
  out.roadArmed = AR.tool;
  for (const c of [[-20, 0], [0, 0], [0, 20]]) AR_EXT.modes.st_road.click({x: c[0], z: c[1], y: 0});
  AR_EXT.modes.st_road.key({key: 'Enter'});
  const roads = AR.objs.filter(o => o.grp === 'roads');
  out.roads = roads.length;
  out.roadKinds = Array.from(new Set(roads.map(o => o.kind)));
  out.roadLens = roads.map(o => Number(o.p.len.toFixed(3)));
  out.roadW = roads.length ? roads[0].p.w : null;
  // — f_img: a 2 x 2 PNG drawn here, 10 m wide —
  const cv = document.createElement('canvas'); cv.width = 2; cv.height = 2;
  const cx = cv.getContext('2d');
  cx.fillStyle = '#f00'; cx.fillRect(0, 0, 1, 1);
  cx.fillStyle = '#0f0'; cx.fillRect(1, 1, 1, 1);
  const url = cv.toDataURL('image/png');
  out.dataUrlPng = url.slice(0, 22);
  arTool('f_img', {data_url: url, width_m: 10});
  await site_context.settled();
  const mesh = site_context.underlayMesh();
  out.underlay = mesh ? {w: mesh.geometry.parameters.width, d: mesh.geometry.parameters.height,
                         y: Number(mesh.position.y.toFixed(3)),
                         inScene: mesh.parent === AR.scene, hasMap: !!mesh.material.map} : null;
  const e = (AR.doc.ext || {}).site_context || {};
  out.ext = e.underlay ? {width_m: e.underlay.width_m, opacity: e.underlay.opacity,
                          rot: e.underlay.rot, url_ok: e.underlay.data_url === url} : null;
  out.undoSteps = AR.undo.length - undo0;
  return out;
}"""
r = browser_eval(DRAW, doc={'objects': []})
v = r['value']
check('no page errors while the four icons ran', not r['errors'], r['errors'])
check('st_bound arms a pointer mode (AR.tool === "st_bound")', v['armed'] == 'st_bound', v['armed'])
check(
    'four clicks + Enter close ONE site_boundary record (Enter is swallowed by the mode)',
    v['boundaries'] == 1 and v['swallowedEnter'] is True,
    v,
)
check(
    'its p holds the four corners as a closed local point list, and nothing else',
    v['pts'] == [[-10, -10], [10, -10], [10, 10], [-10, 10]] and v['closed'] == 1,
    v['pts'],
)
check(
    'the record is drawn as a LINE (no solid) and grouped as site',
    v['parts'] >= 1 and v['grp'] == 'site',
    (v['parts'], v['grp']),
)
check('the area label says 400 m2 for the 20 x 20 m plot', v['label'] == '400 m\u00b2', v['label'])
check(
    'site_context.boundary() gives other families the WORLD polygon, area 400 m2',
    len(v['poly']) == 4 and abs(v['area'] - 400) < 1e-6,
    (v['poly'], v['area']),
)
check(
    'the survey report gives every leg a length and a bearing clockwise from north',
    v['legs'] == [[20.0, 90.0], [20.0, 180.0], [20.0, 270.0], [20.0, 0.0]],
    v['legs'],
)
check(
    'the sheet that opens shows those bearings and the area',
    'Perimeter' in v['sheet']
    and '80.000 m' in v['sheet']
    and '090\u00b0' in v['sheet']
    and '400 m\u00b2' in v['sheet'],
    v['sheet'][:300],
)
check(
    'a 5 m setback insets a SECOND polygon (10 x 10 = 100 m2) and leaves the boundary alone',
    v['setbacks'] == 1 and abs(v['setbackArea'] - 100) < 0.5 and v['boundaryStillOuter'] == 400,
    (v['setbacks'], v['setbackArea'], v['boundaryStillOuter']),
)
check(
    'st_veg {count: 10} plants exactly 10 trees, grouped as planting',
    v['trees'] == 10 and len(v['treeKinds']) == 1,
    (v['trees'], v['treeKinds']),
)
check('every trunk is inside the boundary polygon (point in polygon)', v['allInside'], v['allInside'])
check('no two trunks are closer than 3 m (min gap %s m)' % v['minGap'], v['minGap'] >= 3.0, v['minGap'])
check('st_road arms a pointer mode', v['roadArmed'] == 'st_road', v['roadArmed'])
check(
    'three road clicks make exactly 2 road records of 20 m each at 6 m wide',
    v['roads'] == 2 and v['roadKinds'] == ['road'] and v['roadLens'] == [20.0, 20.0] and v['roadW'] == 6,
    (v['roads'], v['roadKinds'], v['roadLens'], v['roadW']),
)
check(
    'f_img put a real PNG data-url on a plane 10 m wide (2 x 2 px is square, so 10 x 10 m) at y = -0.02',
    v['dataUrlPng'] == 'data:image/png;base64,'
    and v['underlay']
    and v['underlay']['w'] == 10
    and abs(v['underlay']['d'] - 10) < 1e-9
    and v['underlay']['y'] == -0.02
    and v['underlay']['inScene']
    and v['underlay']['hasMap'],
    v['underlay'],
)
check(
    'the underlay is written to AR.doc.ext.site_context so it reloads with the drawing',
    v['ext'] and v['ext']['width_m'] == 10 and v['ext']['url_ok'] and 0 < v['ext']['opacity'] <= 1,
    v['ext'],
)
check(
    'every edit went behind exactly one arPush: 5 steps (boundary, setback, planting, 2 road legs)',
    v['undoSteps'] == 5,
    v['undoSteps'],
)

# ── 3. st_sat: the server route, the arithmetic, the mosaic, the credit ──────
LAT, LON, Z = 52.37, 4.90, 18
n_t = 2**Z
fx = (LON + 180.0) / 360.0 * n_t
fy = (1.0 - math.asinh(math.tan(math.radians(LAT))) / math.pi) / 2.0 * n_t
TX, TY = int(fx), int(fy)
MPP = 156543.03392804097 * math.cos(math.radians(LAT)) / n_t
SIZE = MPP * 256 * 3
print(
    '  slippy: lat %.2f lon %.2f z%d -> x=%d y=%d ; %.4f m/px, tile %.2f m, 3x3 mosaic %.2f m'
    % (LAT, LON, Z, TX, TY, MPP, MPP * 256, SIZE),
    flush=True,
)

w = server_ext('site_context', 'where', {'lat': LAT, 'lon': LON, 'zoom': Z})
check(
    'the server does the same slippy arithmetic as this test (z=%d x=%d y=%d)' % (Z, TX, TY),
    w.get('x') == TX and w.get('y') == TY and w.get('z') == Z and abs(w.get('mpp', 0) - MPP) < 1e-9,
    w,
)
check(
    'the where route names the ODbL attribution the tiles are shown under',
    'OpenStreetMap contributors' in str(w.get('attribution')),
    w.get('attribution'),
)

t = server_ext('site_context', 'tile', {'z': Z, 'x': TX, 'y': TY, 'source': 'osm'}, method='GET')
if not isinstance(t, dict) or 'bytes' not in t:
    print('  NETWORK: the OSM tile route did not return an image: %r' % (t,), flush=True)
check(
    'NETWORK — the tile route fetches a real OSM tile (z%d/%d/%d) and returns > 1 KB of PNG' % (Z, TX, TY),
    isinstance(t, dict) and len(t.get('bytes') or b'') > 1024 and (t.get('bytes') or b'')[:4] == b'\x89PNG',
    {'mime': t.get('mime'), 'n': len(t.get('bytes') or b''), 'err': t.get('error')},
)
cached = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data',
    'architecture',
    'tiles',
    'osm',
    str(Z),
    '%d_%d.png' % (TX, TY),
)
check(
    'the tile is cached on disk, so the tile server is asked once (%s)' % cached,
    os.path.isfile(cached) and os.path.getsize(cached) > 1024,
    cached,
)
check(
    'the source list is exactly osm + esri, each with the credit its licence demands, '
    'fetched under an identifying User-Agent that names the app and a contact',
    set(SS.SOURCES) == {'osm', 'esri'}
    and 'OpenStreetMap contributors' in SS.SOURCES['osm'][1]
    and 'Esri' in SS.SOURCES['esri'][1]
    and 'ZygomaticArchStudio' in SS.USER_AGENT
    and '@' in SS.USER_AGENT,
    (sorted(SS.SOURCES), SS.USER_AGENT),
)

SAT = r"""async () => {
  const out = {};
  arTool('st_sat', {zoom: 18, source: 'osm'});
  const info = site_context.satInfo();
  out.info = info;
  out.tiles = info ? site_context._sc.sat.children.length : 0;
  out.inScene = info ? site_context._sc.sat.parent === AR.scene : false;
  out.y = info ? Number(site_context._sc.sat.position.y.toFixed(3)) : null;
  const cr = document.getElementById('sc-attrib');
  out.credit = cr ? cr.innerHTML : null;
  out.creditShown = !!(cr && cr.style.display !== 'none' && cr.offsetParent !== null);
  out.ext = JSON.parse(JSON.stringify(((AR.doc.ext || {}).site_context || {}).sat || null));
  out.sun = JSON.parse(JSON.stringify((AR.doc.ext || {}).light_sun || null));
  out.objs = AR.objs.length;                       // an underlay is NOT a record
  // off again: tiles and credit go together
  arTool('st_sat');
  out.offInfo = site_context.satInfo();
  out.offSat = !!site_context._sc.sat;
  const cr2 = document.getElementById('sc-attrib');
  out.offCredit = !!(cr2 && cr2.style.display !== 'none' && (cr2.innerHTML || '').length);
  out.offExt = JSON.parse(JSON.stringify(((AR.doc.ext || {}).site_context || {}).sat || null));
  // a drawing that was SAVED with the aerial on brings it back by itself
  AR.doc.ext = {light_sun: {lat: 52.37, lon: 4.9},
                site_context: {sat: {source: 'esri', zoom: 17, on: true}}};
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  const back = site_context.satInfo();
  out.reloaded = back ? {source: back.source, zoom: back.zoom} : null;
  out.reloadedCredit = (document.getElementById('sc-attrib') || {}).innerHTML || '';
  return out;
}"""
r2 = browser_eval(SAT, doc={'objects': [], 'ext': {'light_sun': {'lat': LAT, 'lon': LON}}})
s = r2['value']
check('no page errors while the aerial went on and off', not r2['errors'], r2['errors'])
check(
    'st_sat reads the geolocation the sun family keeps (doc.ext.light_sun) and does not ask again',
    s['info']
    and abs(s['info']['lat'] - LAT) < 1e-6
    and abs(s['info']['lon'] - LON) < 1e-6
    and s['sun']
    and abs(s['sun']['lat'] - LAT) < 1e-6,
    (s['info'], s['sun']),
)
check(
    'the mosaic is 3 x 3 = 9 tiles on the ground at y = -0.01, in the scene',
    s['tiles'] == 9 and s['inScene'] and s['y'] == -0.01,
    (s['tiles'], s['inScene'], s['y']),
)
check(
    'it is sized in METRES by Web Mercator at this latitude: %.1f m across (got %.1f, within 5%%)'
    % (SIZE, (s['info'] or {}).get('size_m', 0)),
    s['info'] and abs(s['info']['size_m'] - SIZE) < SIZE * 0.05 and abs(s['info']['mpp'] - MPP) < MPP * 0.05,
    s['info'],
)
check('the aerial adds NO record to the drawing — it is an underlay, not geometry', s['objs'] == 0, s['objs'])
check(
    'the ODbL attribution is on screen for exactly as long as the tiles are',
    'OpenStreetMap contributors' in (s['credit'] or '') and s['creditShown'] and not s['offCredit'],
    (s['credit'], s['creditShown'], s['offCredit']),
)
check(
    'pressing it again takes the mosaic away and records that in doc.ext',
    s['offInfo'] is None and not s['offSat'] and s['offExt'] and s['offExt']['on'] is False,
    (s['offInfo'], s['offSat'], s['offExt']),
)
check(
    'doc.ext.site_context.sat = {source, zoom, on} while it is on',
    s['ext'] and s['ext'] == {'source': 'osm', 'zoom': 18, 'on': True},
    s['ext'],
)
check(
    'a drawing opened with the aerial on rebuilds it (esri z17) and credits Esri',
    s['reloaded'] == {'source': 'esri', 'zoom': 17} and 'Esri' in s['reloadedCredit'],
    (s['reloaded'], s['reloadedCredit']),
)

# ── 4. the assistant's twins — the same arithmetic, in words ─────────────────
# A 24 x 25 m plot: at 3 m spacing and 1 m off the edge a dozen trees genuinely
# fit. A 6 x 6 m one does not, and the twin would honestly plant only two.
txt, d = assistant('set_site_boundary', {'cells': ['B2', 'Z2', 'Z27', 'B27'], 'setback': 1})
check(
    'set_site_boundary draws the boundary and the setback, and reports the area',
    len([o for o in d.objs if o['kind'] == 'site_boundary']) == 2 and 'm2' in txt,
    txt,
)
check(
    'the setback record is marked as one, so it is never mistaken for the boundary',
    SC.boundary_of(d) is not None
    and len(SC.boundary_of(d)) == 4
    and [o for o in d.objs if (o.get('meta') or {}).get('setback')],
    txt,
)

txt2, d2 = assistant('plant_site_trees', {'count': 12, 'seed': 7}, drawing=d)
trees = [o for o in d2.objs if o['grp'] == 'planting']
poly = SC.boundary_of(d2)
gaps = [math.hypot(a['x'] - b['x'], a['z'] - b['z']) for i, a in enumerate(trees) for b in trees[i + 1 :]]
check(
    'plant_site_trees scatters the trees it says it did (%d), all inside the boundary' % len(trees),
    len(trees) == 12
    and all(SC.in_poly(o['x'], o['z'], poly) for o in trees)
    and all(o['kind'] == 'tree' for o in trees),
    txt2,
)
check(
    'and never closer than 3 m apart (min %.3f m)' % (min(gaps) if gaps else 0),
    gaps and min(gaps) >= 3.0,
    min(gaps) if gaps else None,
)
txt2b, _ = assistant('plant_site_trees', {'count': 5}, doc={'objects': []})
check('with no boundary it refuses instead of guessing', txt2b.startswith('refused'), txt2b)

txt3, d3 = assistant('draw_road', {'cells': ['A5', 'M5', 'M12'], 'width': 6})
roads = [o for o in d3.objs if o['kind'] == 'road']
check(
    'draw_road chains one road record per leg at the width asked',
    len(roads) == 2 and all(abs(o['p']['w'] - 6) < 1e-9 for o in roads) and all(o['grp'] == 'roads' for o in roads),
    txt3,
)

txt4, d4 = assistant('set_geolocation', {'lat': LAT, 'lon': LON, 'north': 30})
check(
    'set_geolocation writes the SAME doc.ext.light_sun keys the sun family reads',
    d4.ext.get('light_sun', {}).get('lat') == LAT
    and d4.ext['light_sun']['lon'] == LON
    and d4.ext['light_sun']['north'] == 30
    and 'm' in txt4,
    (d4.ext, txt4),
)
txt4b, _ = assistant('set_geolocation', {'lat': 200, 'lon': 0})
check('an impossible latitude is refused', txt4b.startswith('refused'), txt4b)

for icon in ICONS:
    check(
        'the model may press %s (BUTTONS + assist:1)' % icon,
        icon in SC.BUTTONS and assistant('press_button', {'id': icon})[0].startswith('pressed'),
        icon,
    )
check(
    'press_button carries the icon args through to the tab',
    assistant('press_button', {'id': 'st_veg', 'args': {'count': 10}})[1].ui[-1]['args']['args'] == {'count': 10},
)
check(
    'the PROMPT paragraph tells the model the args of every icon and tool',
    all(
        k in SC.PROMPT
        for k in (
            'st_bound',
            'st_sat',
            'st_veg',
            'st_road',
            'f_img',
            'set_site_boundary',
            'plant_site_trees',
            'draw_road',
            'set_geolocation',
            'data_url',
            'width_m',
            'setback',
        )
    ),
    len(SC.PROMPT),
)

# ── 5. the kind is VOID: a line in the tab, nothing in Blender ──────────────
check(
    'site_boundary is declared VOID on both sides, and its Blender builder builds nothing',
    SC.VOID_KINDS == ['site_boundary'] == SB.VOID_KINDS and SB.BUILDERS['site_boundary'](None, {}, {}) == ('~', []),
    (SC.VOID_KINDS, SB.VOID_KINDS),
)

finish()
