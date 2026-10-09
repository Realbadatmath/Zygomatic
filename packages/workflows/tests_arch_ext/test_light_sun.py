# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_light_sun.py — proves the light_sun family.

Five icons stop being placeholders (l_date, l_north, l_geo, st_geo, st_north)
and each one is shown DOING what its tooltip promises: a date that changes the
sunrise/sunset it reports, a north angle that turns both the sun and the arrow,
a latitude/longitude that moves the sun path, a place name resolved through
OpenStreetMap, and a north arrow that appears in the scene and rotates.

The solar model is checked against reality first, because a wrong sun that
compiles is worse than no sun: the Amsterdam sunrise/sunset it computes for the
June solstice are the almanac's 05:18 / 22:06 CEST, the equinox day is 12 h,
and the JS copy of the algorithm agrees with the Python one to well under half
a degree on three dates.

Two browser_eval calls: icon_state (one) and one batched function (two).
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, browser_eval, icon_state, server_ext  # noqa: E402
from zyg_workflows.arch_assistant_ext.light_sun import solar_position, hm, direction  # noqa: E402

IDS = ['l_date', 'l_north', 'l_geo', 'st_geo', 'st_north']
LAT, LON = 52.37, 4.90

# ── 1. the icons are wired ───────────────────────────────────────────────────
st = icon_state(IDS)
check(
    'all five icons exist, and none is a placeholder any more (no stub flag, no dashed border, no [placeholder] tip)',
    all(
        st.get(i, {}).get('exists')
        and not st[i].get('stub')
        and not st[i].get('dashed')
        and not st[i].get('tip_placeholder')
        for i in IDS
    ),
    st,
)

# ── 2. the solar model against reality ───────────────────────────────────────
jun = solar_position('2026-06-21', 12.0, LAT, LON, 2.0)
check(
    "Amsterdam 21 June: sunrise/sunset are the almanac's 05:18 / 22:06 CEST",
    hm(jun['sunrise']) == '05:18' and hm(jun['sunset']) == '22:06',
    (hm(jun['sunrise']), hm(jun['sunset'])),
)
check(
    'and solar noon is 13:42 CEST, 1 h 42 m after the clock noon (4.90 E, zone meridian 30 E)',
    hm(jun['noon']) == '13:42',
    hm(jun['noon']),
)

noon_jun = solar_position('2026-06-21', jun['noon'], LAT, LON, 2.0)
check(
    'the June solstice maximum altitude is 90 - lat + obliquity = 61.1 deg (elevation 60.4 +/- 1 as briefed)',
    abs(noon_jun['elevation'] - 61.07) < 0.2 and abs(noon_jun['elevation'] - 60.4) <= 1.0,
    noon_jun['elevation'],
)
check(
    'and the sun stands due south there (azimuth 180 +/- 0.5)',
    abs(noon_jun['azimuth'] - 180.0) < 0.5,
    noon_jun['azimuth'],
)

dec = solar_position('2026-12-21', 12.0, LAT, LON, 1.0)
check(
    'Amsterdam 21 December at 12:00 CET: elevation 14.5 +/- 1 deg as briefed',
    abs(dec['elevation'] - 14.5) <= 1.0,
    dec['elevation'],
)
noon_dec = solar_position('2026-12-21', dec['noon'], LAT, LON, 1.0)
check(
    'the December solstice maximum is 90 - lat - obliquity = 14.2 deg',
    abs(noon_dec['elevation'] - 14.19) < 0.2,
    noon_dec['elevation'],
)

eq = solar_position('2026-03-20', 12.0, LAT, LON, 1.0)
check('equinox sanity: 2026-03-20 is 12 h long +/- 0.3', abs(eq['day_length'] - 12.0) < 0.3, eq['day_length'])

pole = solar_position('2026-06-21', 0.0, 78.0, 15.0, 1.0)
check(
    'polar day is handled: Svalbard on the solstice never sets and is never below the horizon',
    pole['day_length'] == 24.0 and pole['sunrise'] is None and pole['elevation'] > 0,
    (pole['day_length'], pole['sunrise'], pole['elevation']),
)

d = direction(180.0, 30.0, 0.0)
check(
    "a bearing of 180 deg with north=0 puts the sun at +Z (the studio's south)",
    abs(d[0]) < 1e-9 and abs(d[2] - math.cos(math.radians(30))) < 1e-9 and d[1] > 0,
    d,
)
d90 = direction(180.0, 30.0, 90.0)
check(
    'the north angle rotates that direction 90 deg in plan: +Z becomes -X',
    abs(d90[2]) < 1e-9 and abs(d90[0] + math.cos(math.radians(30))) < 1e-9,
    d90,
)

# ── 3. the assistant twins ───────────────────────────────────────────────────
txt, dr = assistant('set_sun_model', {'date': '2026-06-21', 'hour': 12, 'lat': LAT, 'lon': LON, 'tz': 2, 'north': 30})
check(
    'set_sun_model stores the site in the drawing (doc.ext.light_sun, the five briefed keys)',
    dr.ext.get('light_sun') == {'date': '2026-06-21', 'lat': LAT, 'lon': LON, 'tz': 2.0, 'north': 30.0},
    dr.ext.get('light_sun'),
)
check(
    'set_sun_model returns the elevation and azimuth it computed',
    'elevation 55.13 deg' in txt and 'azimuth 136.20 deg' in txt,
    txt,
)
check('set_sun_model tells the tab to re-apply the sun', dr.ui and dr.ui[-1]['cmd'] == 'sun', dr.ui)
check(
    'the site survives a round trip through the assistant Drawing',
    dr.to_doc()['ext'].get('light_sun', {}).get('north') == 30.0,
    dr.to_doc()['ext'],
)

txt2, _ = assistant('sun_position', {'date': '2026-12-21', 'hour': 12}, drawing=dr)
check(
    "sun_position reads the drawing's site and reports sunrise/noon/sunset and the day length",
    'Sunrise 09:48' in txt2 and 'sunset 17:29' in txt2 and 'day length 7.68 h' in txt2,
    txt2,
)
check(
    'sun_position is read-only (the date it was asked about is not stored)',
    dr.ext['light_sun']['date'] == '2026-06-21',
    dr.ext['light_sun'],
)
txt3, _ = assistant('sun_position', {'date': 'not a date'}, drawing=dr)
check('a bad date is refused, not guessed', txt3.startswith('refused'), txt3)

# ── 4. the server op: a place name -> a coordinate (Nominatim, ODbL) ─────────
g = server_ext('light_sun', 'geocode', {'place': 'Rotterdam'})
check(
    'geocode resolves a place name to a coordinate (Rotterdam ~ 51.92, 4.48)',
    g.get('ok') and abs(g['lat'] - 51.92) < 0.2 and abs(g['lon'] - 4.48) < 0.2,
    g,
)
check('and it names its source: OpenStreetMap, ODbL', 'ODbL' in str(g.get('attribution')), g.get('attribution'))
g2 = server_ext('light_sun', 'geocode', {'place': ''})
check('an empty place is an honest error, not a coordinate', g2.get('ok') is False and g2.get('error'), g2)

# ── 5. the icons in the live tab ─────────────────────────────────────────────
JS = """
async () => {
  const R = {}, T = () => document.getElementById('ar-toast').innerHTML;
  const norm = v => { const h = Math.hypot(v.x, v.z); return {x: v.x / h, z: v.z / h, el: v.el}; };
  const dirOf = () => { const d = AR.sun.position.clone().sub(AR.sun.target.position);
    return {el: Math.atan2(d.y, Math.hypot(d.x, d.z)) * 180 / Math.PI, x: d.x, z: d.z, len: d.length()}; };

  arNewObj('slab', {w: 20, d: 20, t: 0.3}, 0, 0, 0);
  let pushes = 0; const bp = arPush; arPush = function(){ pushes++; return bp(); };

  /* l_geo — site latitude and longitude */
  arTool('l_geo', {lat: 52.37, lon: 4.90, tz: 2});
  R.geo = JSON.parse(JSON.stringify(AR.doc.ext.light_sun)); R.geoToast = T();

  /* l_north — the drawing's north angle */
  arTool('l_north', {north: 0}); R.north0 = AR.doc.ext.light_sun.north;

  /* l_date — the season */
  arTool('l_date', {date: '2026-06-21'});
  R.date = AR.doc.ext.light_sun.date; R.dateToast = T();
  arTool('l_date', {date: 'the ides of March'}); R.badDateToast = T();
  R.dateKept = AR.doc.ext.light_sun.date;

  /* the shared arithmetic, straight out of the JS copy */
  R.calc = [['2026-06-21', 12, 2], ['2026-12-21', 12, 1], ['2026-03-20', 12, 1]].map(function(c){
    const s = light_sunCalc(c[0], c[1], 52.37, 4.90, c[2]);
    return {date: c[0], hour: c[1], tz: c[2], el: s.elevation, az: s.azimuth,
            rise: s.sunrise, set: s.sunset, len: s.day_length, noon: s.noon};
  });

  /* the scene: the light really moves, and the shadow frustum is refitted */
  arSunSet(13.708);                       /* solar noon in Amsterdam on 21 June */
  R.noon = dirOf(); R.noonI = AR.sun.intensity;
  R.tgt = [AR.sun.target.position.x, AR.sun.target.position.y, AR.sun.target.position.z];
  const b = arBounds(false); R.bnd = [b.c.x, b.c.y, b.c.z, b.r];
  R.frustum = AR.sun.shadow.camera.right;

  arSunSet(6);  R.i6 = AR.sun.intensity;  R.el6 = dirOf().el;
  arSunSet(22); R.i22 = AR.sun.intensity; R.el22 = dirOf().el; R.nightToast = T();

  /* l_north again: 90 deg turns the sun 90 deg in plan and leaves its height */
  arSunSet(13.708); const before = norm(dirOf());
  arTool('l_north', {north: 90}); const after = norm(dirOf());
  R.rot = {before: before, after: after, stored: AR.doc.ext.light_sun.north, toast: T()};

  /* st_north: the arrow */
  R.arrowBefore = !!(AR._lsArrow && AR._lsArrow.visible);
  arTool('st_north');
  const gr = AR._lsArrow; gr.updateMatrixWorld(true);
  const q = gr.getWorldQuaternion(new THREE.Quaternion());
  const t90 = new THREE.Vector3(0, 0, -1).applyQuaternion(q);
  R.arrow90 = {vis: gr.visible, x: t90.x, z: t90.z, kids: gr.children.length,
               on: AR_EXT.tools.st_north.on(), pos: [gr.position.x, gr.position.z], sc: gr.scale.x,
               sprite: gr.children.filter(c => c.isSprite).length};
  arTool('l_north', {north: 0}); gr.updateMatrixWorld(true);
  const t0 = new THREE.Vector3(0, 0, -1).applyQuaternion(gr.getWorldQuaternion(new THREE.Quaternion()));
  R.arrow0 = {x: t0.x, z: t0.z};
  arTool('st_north'); R.arrowOff = AR._lsArrow.visible; R.offOn = AR_EXT.tools.st_north.on();
  arTool('st_north');

  /* st_geo: a place NAME through the server op, then plain coordinates */
  arTool('st_geo', {place: 'Rotterdam'});
  R.place = await AR._lsGeoP;
  R.placeToast = T(); R.placeSite = JSON.parse(JSON.stringify(AR.doc.ext.light_sun));
  arTool('st_geo', {lat: 48.8566, lon: 2.3522, tz: 1});
  R.stGeo = JSON.parse(JSON.stringify(AR.doc.ext.light_sun)); R.stGeoToast = T();

  arPush = bp; R.pushes = pushes;
  R.docExt = JSON.parse(JSON.stringify(arDocOut().ext));
  return R;
}
"""
r = browser_eval(JS)
v = r['value']
check('no page errors while the five icons ran', not r['errors'], r['errors'])

check(
    'l_geo wrote the site into the drawing (doc.ext.light_sun, the five briefed keys)',
    v['geo'] == {'date': '2026-06-21', 'lat': 52.37, 'lon': 4.9, 'tz': 2, 'north': 0},
    v['geo'],
)
check('l_geo says where it put the site', '52.3700, 4.9000' in v['geoToast'], v['geoToast'])

check(
    'l_date set the date and toasted the sunrise and sunset it computed (05:18 / 22:06)',
    v['date'] == '2026-06-21' and '05:18' in v['dateToast'] and '22:06' in v['dateToast'],
    v['dateToast'],
)
check(
    'l_date refuses a date it cannot read and keeps the old one',
    'not a date' in v['badDateToast'] and v['dateKept'] == '2026-06-21',
    (v['badDateToast'], v['dateKept']),
)

jsjun, jsdec, jseq = v['calc']
pyjun = solar_position('2026-06-21', 12, LAT, LON, 2)
pydec = solar_position('2026-12-21', 12, LAT, LON, 1)
pyeq = solar_position('2026-03-20', 12, LAT, LON, 1)
gaps = [
    abs(jsjun['el'] - pyjun['elevation']),
    abs(jsjun['az'] - pyjun['azimuth']),
    abs(jsdec['el'] - pydec['elevation']),
    abs(jsdec['az'] - pydec['azimuth']),
    abs(jseq['el'] - pyeq['elevation']),
    abs(jseq['az'] - pyeq['azimuth']),
]
check(
    'the JS and Python copies of the NOAA model agree to 0.5 deg on three dates',
    max(gaps) < 0.5,
    {
        'max_gap_deg': max(gaps),
        'gaps': gaps,
        'js': [round(jsjun['el'], 3), round(jsdec['el'], 3), round(jseq['el'], 3)],
        'py': [round(pyjun['elevation'], 3), round(pydec['elevation'], 3), round(pyeq['elevation'], 3)],
    },
)
check(
    'and on the day length too (equinox 12 h in both)',
    abs(jseq['len'] - pyeq['day_length']) < 0.01 and abs(jseq['len'] - 12.0) < 0.3,
    (jseq['len'], pyeq['day_length']),
)

check(
    'AR.sun really points at the computed altitude: 61.1 deg above the horizon at solar noon',
    abs(v['noon']['el'] - 61.07) < 1.0,
    v['noon'],
)
check(
    'and it hangs due south of the drawing at noon (x ~ 0, z > 0)',
    abs(v['noon']['x']) < 0.5 and v['noon']['z'] > 1,
    v['noon'],
)
_fr = max(45.0, v['bnd'][3] * 1.2)  # what arShadowFit sizes the frustum to
check(
    'the sun target is the drawing centre and arShadowFit refitted the shadow frustum to it',
    abs(v['tgt'][0] - v['bnd'][0]) < 1e-6
    and abs(v['tgt'][2] - v['bnd'][2]) < 1e-6
    and abs(v['frustum'] - _fr) < 1e-6
    and abs(v['noon']['len'] - max(45.0, _fr * 1.6)) < 1e-3,
    {'target': v['tgt'], 'bounds': v['bnd'], 'frustum': v['frustum'], 'dist': v['noon']['len']},
)

check(
    'arSunSet(6) still works and June at 06:00 is daylight (sun 4.2 deg up, intensity > 0.2)',
    v['i6'] > 0.2 and abs(v['el6'] - 4.216) < 0.5,
    {'intensity': v['i6'], 'elevation': v['el6']},
)
check(
    'at 22:00 the June sun has just set: intensity 0 and the elevation is below the horizon',
    v['i22'] == 0 and v['el22'] < 0,
    {'intensity': v['i22'], 'elevation': v['el22']},
)
check('and it says so once, in a toast', 'below the horizon' in v['nightToast'], v['nightToast'])

rot = v['rot']
check(
    'l_north 90 rotates the sun 90 deg in plan ((x, z) -> (-z, x)) and stores the angle',
    abs(rot['after']['x'] + rot['before']['z']) < 0.02
    and abs(rot['after']['z'] - rot['before']['x']) < 0.02
    and rot['stored'] == 90,
    rot,
)
check(
    'and it keeps the sun at the same height (a north angle turns the drawing, not the sky)',
    abs(rot['after']['el'] - rot['before']['el']) < 0.01,
    (rot['before']['el'], rot['after']['el']),
)
check('l_north says what it did', '90.0' in rot['toast'] and 'north' in rot['toast'].lower(), rot['toast'])

check(
    'st_north was off, and pressing it puts a north arrow group (two halves + an N sprite) in the scene',
    v['arrowBefore'] is False
    and v['arrow90']['vis']
    and v['arrow90']['kids'] == 3
    and v['arrow90']['sprite'] == 1
    and v['arrow90']['on'],
    v['arrow90'],
)
check(
    "the arrow points at true north: at north = 90 it points +X (east of the plan's up)",
    abs(v['arrow90']['x'] - 1) < 1e-6 and abs(v['arrow90']['z']) < 1e-6,
    v['arrow90'],
)
check(
    "and it turns back to -Z (the plan's up) when north goes to 0",
    abs(v['arrow0']['z'] + 1) < 1e-6 and abs(v['arrow0']['x']) < 1e-6,
    v['arrow0'],
)
check(
    'the arrow sits off the drawing and is scaled to it, and the switch latches off again',
    v['arrow90']['sc'] > 1 and abs(v['arrow90']['pos'][0]) > 1 and v['arrowOff'] is False and v['offOn'] is False,
    {'scale': v['arrow90']['sc'], 'pos': v['arrow90']['pos'], 'off': v['arrowOff']},
)

check(
    'st_geo resolved the place NAME "Rotterdam" through the server op and moved the site there',
    v['place'].get('ok') and abs(v['placeSite']['lat'] - 51.92) < 0.2 and abs(v['placeSite']['lon'] - 4.48) < 0.2,
    {'answer': v['place'], 'site': v['placeSite']},
)
check(
    'and its toast credits OpenStreetMap under the ODbL',
    'ODbL' in v['placeToast'] and 'OpenStreetMap' in v['placeToast'],
    v['placeToast'],
)
check(
    'st_geo also takes plain coordinates (Paris, UTC+1)',
    v['stGeo']['lat'] == 48.8566 and v['stGeo']['lon'] == 2.3522 and v['stGeo']['tz'] == 1,
    v['stGeo'],
)

check(
    'every document edit went behind exactly one arPush (7 site changes, 7 pushes; '
    'moving the sun through the day pushes nothing)',
    v['pushes'] == 7,
    v['pushes'],
)
check(
    'and the site is written into the saved document',
    v['docExt'].get('light_sun', {}).get('lat') == 48.8566,
    v['docExt'],
)

finish()
