// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* light_sun — a real sun for Architecture Studio (2026-09-07).
   Wires Light ▸ Date (l_date), Light ▸ North (l_north), Light ▸ Location (l_geo),
   Site ▸ Geolocate (st_geo) and Site ▸ North arrow (st_north), and takes over the
   existing Light ▸ Time (l_time / arSunSet) so a time of day is a real sun height.

   THE ARITHMETIC is the NOAA Solar Calculator's, i.e. Jean Meeus, *Astronomical
   Algorithms* (2nd ed., 1998) ch. 7 (Julian day), 22 (obliquity), 25 (solar
   coordinates), 28 (equation of time), in the low-accuracy form published at
   gml.noaa.gov/grad/solcalc/calcdetails.html — about 0.01 deg on the declination,
   under a minute on the equation of time. No library: fifteen polynomials and one
   spherical triangle. The SAME algorithm is written again in
   arch_assistant_ext/light_sun.py so the model and the viewport share one truth;
   tests_arch_ext/test_light_sun.py proves they agree to 0.5 deg.
   `elevation` is the true geometric altitude of the sun's centre (what casts a
   shadow); sunrise/sunset use the conventional -0.833 deg, so they match an almanac.

   FRAMES. `azimuth` is the compass bearing of the sun, clockwise from TRUE north.
   AR.doc.ext.light_sun.north is how many degrees CLOCKWISE of the drawing's -Z
   (the top view's "up") true north lies at, so the sun's bearing inside the drawing
   is azimuth + north, and a bearing b is the direction (sin b, 0, -cos b).

   STATE: AR.doc.ext.light_sun = {date, hour, lat, lon, tz, north} — saved with the
   drawing, round-tripped through the assistant. Defaults: Amsterdam, 21 June,
   time zone from the browser. */
(function(){
  'use strict';

  var LS_DEF = {date: '2026-06-21', lat: 52.37, lon: 4.90, tz: null, north: 0, hour: 14};

  /* ── solar position ─────────────────────────────────────────────────── */
  function lsParseDate(v){
    var m = /^\s*(-?\d{1,6})[-\/](\d{1,2})[-\/](\d{1,2})\s*$/.exec(String(v === undefined || v === null ? '' : v));
    if(!m) return null;
    var y = parseInt(m[1], 10), mo = parseInt(m[2], 10), d = parseInt(m[3], 10);
    if(!(mo >= 1 && mo <= 12) || !(d >= 1 && d <= 31)) return null;
    var days = [31, ((y % 4 === 0 && y % 100 !== 0) || y % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    if(d > days[mo - 1]) return null;
    var p2 = function(n){ return (n < 10 ? '0' : '') + n; };
    return (y < 0 ? '-' : '') + String(Math.abs(y)) + '-' + p2(mo) + '-' + p2(d);
  }

  function lsJulianDay(y, m, d, hourUtc){
    if(m <= 2){ y -= 1; m += 12; }
    var a = Math.floor(y / 100), b = 2 - a + Math.floor(a / 4);
    return Math.floor(365.25 * (y + 4716)) + Math.floor(30.6001 * (m + 1)) + d + b - 1524.5 + hourUtc / 24;
  }

  var D2R = Math.PI / 180, R2D = 180 / Math.PI;
  function clamp1(v){ return v < -1 ? -1 : (v > 1 ? 1 : v); }

  /* declination (deg) and equation of time (minutes) for Julian century t */
  function lsSunTerms(t){
    var l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360;
    if(l0 < 0) l0 += 360;
    var m = 357.52911 + t * (35999.05029 - 0.0001537 * t);
    var e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t);
    var mr = m * D2R;
    var c = Math.sin(mr) * (1.914602 - t * (0.004817 + 0.000014 * t))
          + Math.sin(2 * mr) * (0.019993 - 0.000101 * t)
          + Math.sin(3 * mr) * 0.000289;
    var trueLong = l0 + c;
    var omega = 125.04 - 1934.136 * t;
    var appLong = trueLong - 0.00569 - 0.00478 * Math.sin(omega * D2R);
    var eps0 = 23 + (26 + ((21.448 - t * (46.815 + t * (0.00059 - t * 0.001813)))) / 60) / 60;
    var eps = eps0 + 0.00256 * Math.cos(omega * D2R);
    var decl = Math.asin(clamp1(Math.sin(eps * D2R) * Math.sin(appLong * D2R))) * R2D;
    var y = Math.tan(eps / 2 * D2R); y = y * y;
    var l0r = l0 * D2R;
    var eot = 4 * R2D * (y * Math.sin(2 * l0r) - 2 * e * Math.sin(mr)
                         + 4 * e * y * Math.sin(mr) * Math.cos(2 * l0r)
                         - 0.5 * y * y * Math.sin(4 * l0r) - 1.25 * e * e * Math.sin(2 * mr));
    return {decl: decl, eot: eot};
  }

  /* the whole model: local clock hour -> elevation/azimuth/sunrise/noon/sunset */
  function light_sunCalc(date, hour, lat, lon, tz){
    var ds = lsParseDate(date) || LS_DEF.date, p = ds.split('-');
    var y = parseInt(p[0], 10), mo = parseInt(p[1], 10), dd = parseInt(p[2], 10);
    hour = +hour; lat = +lat; lon = +lon; tz = +tz;
    var jd = lsJulianDay(y, mo, dd, hour - tz), t = (jd - 2451545) / 36525;
    var s = lsSunTerms(t), decl = s.decl, eot = s.eot;
    var tst = (hour * 60 + eot + 4 * lon - 60 * tz) % 1440;
    if(tst < 0) tst += 1440;
    var ha = tst / 4 - 180; if(ha < -180) ha += 360;
    var latr = lat * D2R, declr = decl * D2R, har = ha * D2R;
    var cosZ = clamp1(Math.sin(latr) * Math.sin(declr) + Math.cos(latr) * Math.cos(declr) * Math.cos(har));
    var zen = Math.acos(cosZ) * R2D, el = 90 - zen, sinZ = Math.sin(zen * D2R), az;
    if(Math.abs(sinZ) < 1e-9 || Math.abs(Math.cos(latr)) < 1e-9){
      az = lat >= 0 ? 180 : 0;
    }else{
      var x = Math.acos(clamp1((Math.sin(latr) * cosZ - Math.sin(declr)) / (Math.cos(latr) * sinZ))) * R2D;
      az = ha > 0 ? (x + 180) % 360 : (540 - x) % 360;
    }
    var noon = (720 - 4 * lon - eot + 60 * tz) / 60;
    var rise = null, set = null, len = null, den = Math.cos(latr) * Math.cos(declr);
    if(Math.abs(den) > 1e-9){
      var ch = Math.cos(90.833 * D2R) / den - Math.tan(latr) * Math.tan(declr);
      if(ch >= -1 && ch <= 1){
        var ha0 = Math.acos(ch) * R2D;
        rise = noon - ha0 / 15; set = noon + ha0 / 15; len = 2 * ha0 / 15;
      }
    }
    if(len === null) len = (lat * decl) > 0 ? 24 : 0;
    return {elevation: el, azimuth: az, zenith: zen, declination: decl, eot: eot,
            hour_angle: ha, noon: noon, sunrise: rise, sunset: set, day_length: len};
  }

  /* unit vector from the site towards the sun, in the studio's (x, y, z) */
  function light_sunDir(az, el, north){
    var b = (az + (north || 0)) * D2R, e = el * D2R, ce = Math.cos(e);
    return {x: ce * Math.sin(b), y: Math.sin(e), z: -ce * Math.cos(b)};
  }

  function light_sunHM(h){
    if(h === null || h === undefined || !isFinite(h)) return '\u2014';
    h = ((h % 24) + 24) % 24;
    var m = Math.round(h * 60), p2 = function(n){ return (n < 10 ? '0' : '') + n; };
    return p2(Math.floor(m / 60) % 24) + ':' + p2(m % 60);
  }

  /* ── the drawing's site ─────────────────────────────────────────────── */
  function lsTzGuess(){
    try{ return -(new Date()).getTimezoneOffset() / 60; }catch(e){ return 2; }
  }

  function light_sunSite(){
    if(!AR.doc) AR.doc = {ext: {}};
    if(!AR.doc.ext || typeof AR.doc.ext !== 'object') AR.doc.ext = {};
    var cur = AR.doc.ext.light_sun;
    var out = {date: LS_DEF.date, lat: LS_DEF.lat, lon: LS_DEF.lon,
               tz: lsTzGuess(), north: 0, hour: LS_DEF.hour};
    if(cur && typeof cur === 'object'){
      if(lsParseDate(cur.date)) out.date = lsParseDate(cur.date);
      if(isFinite(+cur.lat)) out.lat = Math.max(-90, Math.min(90, +cur.lat));
      if(isFinite(+cur.lon)) out.lon = Math.max(-180, Math.min(180, +cur.lon));
      if(isFinite(+cur.tz)) out.tz = Math.max(-14, Math.min(14, +cur.tz));
      if(isFinite(+cur.north)) out.north = ((+cur.north % 360) + 360) % 360;
    }
    if(AR.sunHour !== undefined && isFinite(+AR.sunHour)) out.hour = +AR.sunHour;
    return out;
  }

  /* the ONLY writer of the document's site. The hour is not part of it: it is a
     view setting (AR.sunHour, the studio's own), so moving the sun through the day
     never touches the drawing and never fills the undo ring. Every caller is an
     icon that has already called arPush(). */
  function light_sunStore(st){
    if(!AR.doc.ext || typeof AR.doc.ext !== 'object') AR.doc.ext = {};
    AR.doc.ext.light_sun = {date: st.date, lat: st.lat, lon: st.lon, tz: st.tz, north: st.north};
    AR._lsSig = JSON.stringify(AR.doc.ext.light_sun);
  }

  /* ── applying it to the scene ───────────────────────────────────────── */
  function light_sunApply(hour){
    var st = light_sunSite();
    if(hour !== undefined && hour !== null && isFinite(+hour)) st.hour = Math.max(0, Math.min(24, +hour));
    AR.sunHour = st.hour;
    var s = light_sunCalc(st.date, st.hour, st.lat, st.lon, st.tz);
    AR._lightSun = s; AR._lightSite = st;
    /* read-only on the document: applying the sun is a view change, not an edit */
    AR._lsSig = JSON.stringify((AR.doc && AR.doc.ext && AR.doc.ext.light_sun) || null);
    if(!AR.sun || !AR.scene) return s;

    var b = (typeof arBounds === 'function') ? arBounds(false) : {c: new THREE.Vector3(0, 0, 0), r: 30};
    var d = light_sunDir(s.azimuth, s.elevation, st.north);
    var R = Math.max(45, b.r * 1.6);
    AR.sun.target.position.copy(b.c); AR.sun.target.updateMatrixWorld();
    AR.sun.position.set(b.c.x + d.x * R, b.c.y + d.y * R, b.c.z + d.z * R);

    /* intensity by elevation: 0 below the horizon (night), and the low-sun
       reddening the studio already used for its fake arc */
    var up = Math.max(0, Math.sin(s.elevation * D2R));
    AR.sun.intensity = s.elevation <= 0 ? 0 : 1.35 * Math.pow(up, 0.6);
    var low = Math.max(0, 1 - up * 1.6);
    AR.sun.color = new THREE.Color().setHSL(0.09, 0.55 * low + 0.05, 0.55);

    /* the sky dims with the sun. arSkyCycle only cycles a palette, so the base
       colour is read back from it and scaled — never accumulated. */
    try{
      var base = (typeof AR_SKIES !== 'undefined' && AR_SKIES[AR.skyIx || 0])
        ? AR_SKIES[AR.skyIx || 0].c : (AR._fogCol === undefined ? 0x9fbdd8 : AR._fogCol);
      var f = s.elevation <= 0 ? 0.26 : (0.26 + 0.74 * Math.pow(up, 0.45));
      var col = new THREE.Color(base).multiplyScalar(f);
      if(AR.scene.background && AR.scene.background.isColor) AR.scene.background = col;
      if(AR.scene.fog) AR.scene.fog.color = col.clone();
    }catch(e){}

    if(typeof arShadowFit === 'function') arShadowFit();
    lsArrowSync();

    if(s.elevation <= 0){
      if(!AR._lsNightToast){
        AR._lsNightToast = 1;
        arToast('The sun is <b>below the horizon</b> at ' + light_sunHM(st.hour) + ' on ' + st.date
                + ' — night, so there are no shadows. Sunrise ' + light_sunHM(s.sunrise)
                + ', sunset ' + light_sunHM(s.sunset) + '.', 'warn');
      }
    }else{
      AR._lsNightToast = 0;
    }
    return s;
  }

  /* ── the north arrow (st_north) ─────────────────────────────────────── */
  function lsLabelSprite(){
    var c = document.createElement('canvas'); c.width = c.height = 64;
    var g = c.getContext('2d');
    g.fillStyle = 'rgba(0,0,0,0)'; g.fillRect(0, 0, 64, 64);
    g.font = 'bold 46px system-ui, sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.lineWidth = 6; g.strokeStyle = 'rgba(10,12,16,0.85)'; g.strokeText('N', 32, 34);
    g.fillStyle = '#f4f7fb'; g.fillText('N', 32, 34);
    var tex = new THREE.CanvasTexture(c);
    var sp = new THREE.Sprite(new THREE.SpriteMaterial({map: tex, transparent: true, depthTest: false}));
    sp.renderOrder = 9;
    return sp;
  }

  function lsHalf(pts, col){
    var sh = new THREE.Shape();
    sh.moveTo(pts[0][0], pts[0][1]);
    for(var i = 1; i < pts.length; i++) sh.lineTo(pts[i][0], pts[i][1]);
    sh.closePath();
    var m = new THREE.Mesh(new THREE.ShapeGeometry(sh),
                           new THREE.MeshBasicMaterial({color: col, side: THREE.DoubleSide,
                                                        depthTest: false, transparent: true, opacity: 0.95}));
    m.rotation.x = -Math.PI / 2;   /* the shape's +Y becomes the world's -Z */
    m.renderOrder = 8;
    return m;
  }

  function lsArrowMake(){
    if(AR._lsArrow) return AR._lsArrow;
    var g = new THREE.Group();
    g.name = 'light_sun north arrow';
    /* a classic north point: a dark half and a light half meeting on the axis */
    g.add(lsHalf([[0, 1], [0, 0], [-0.30, -0.42]], 0x12161c));
    g.add(lsHalf([[0, 1], [0.30, -0.42], [0, 0]], 0xe8eef6));
    var sp = lsLabelSprite(); sp.position.set(0, 0.05, -1.34); sp.scale.set(0.5, 0.5, 0.5);
    g.add(sp); g._lsLabel = sp;
    g.visible = false;
    AR._lsArrow = g;
    AR.scene.add(g);
    return g;
  }

  function lsArrowSync(){
    var g = AR._lsArrow;
    if(!g || !g.visible) return;
    var st = light_sunSite();
    var b = (typeof arBounds === 'function') ? arBounds(false) : {c: new THREE.Vector3(0, 0, 0), r: 30};
    var L = Math.max(1.4, Math.min(60, b.r * 0.16));
    g.scale.set(L, L, L);
    g.position.set(b.c.x + b.r * 1.05, (AR.level || 0) + 0.06, b.c.z - b.r * 1.05);
    g.rotation.y = -st.north * D2R;      /* rotating -Z clockwise by `north` */
    if(g._lsLabel) g._lsLabel.scale.set(0.5, 0.5, 0.5);
  }

  function lsArrowShow(on){
    var g = lsArrowMake();
    g.visible = !!on;
    lsArrowSync();
    if(typeof arToolsRender === 'function') arToolsRender();
    return g.visible;
  }

  /* ── the server op (Nominatim place names) ──────────────────────────── */
  function light_sunGeocode(place){
    return fetch('/inspect/api/architecture/ext/light_sun/geocode',
                 {method: 'POST', headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({place: String(place || '')})})
      .then(function(r){ return r.json(); })
      .catch(function(e){ return {ok: false, error: String(e)}; });
  }

  /* ── the icons ──────────────────────────────────────────────────────── */
  function lsAsk(opt, field, question, dflt){
    if(opt && typeof opt === 'object' && opt[field] !== undefined && opt[field] !== null) return String(opt[field]);
    return prompt(question, dflt);
  }

  function lsApplyToast(st, extra){
    var s = light_sunApply();
    arToast(extra + ' Sun now <b>' + s.elevation.toFixed(1) + '\u00b0</b> high, bearing <b>'
            + s.azimuth.toFixed(1) + '\u00b0</b> from true north.');
    return s;
  }

  AR_EXT.tools.l_date = {
    assist: 1,
    tip: 'Date — the season sets how high the sun ever gets. A December shadow is not a June shadow',
    act: function(opt){
      var st = light_sunSite();
      var v = lsAsk(opt, 'date', 'Date of the sun study (YYYY-MM-DD) — the season sets how high the sun gets:', st.date);
      if(v === null || v === undefined) return;
      var ds = lsParseDate(v);
      if(!ds){ arToast('<b>' + esc(String(v)) + '</b> is not a date — write it as YYYY-MM-DD.', 'bad'); return; }
      arPush();
      st.date = ds; light_sunStore(st);
      var s = light_sunApply();
      arToast('Date <b>' + ds + '</b> \u2014 sunrise <b>'
              + light_sunHM(s.sunrise) + '</b>, solar noon ' + light_sunHM(s.noon) + ', sunset <b>'
              + light_sunHM(s.sunset) + '</b> (' + s.day_length.toFixed(2) + ' h of daylight). Sun '
              + s.elevation.toFixed(1) + '\u00b0 high.');
      if(typeof arDirty === 'function') arDirty(true);
    }
  };

  AR_EXT.tools.l_north = {
    assist: 1,
    tip: 'North angle — which way the drawing faces. Every sun study is wrong until this is set',
    act: function(opt){
      var st = light_sunSite();
      var v = lsAsk(opt, 'north', 'North angle in degrees \u2014 how far CLOCKWISE of the plan\u2019s "up" (-Z) true north lies:',
                    String(st.north));
      if(v === null || v === undefined) return;
      var n = parseFloat(v);
      if(!isFinite(n)){ arToast('<b>' + esc(String(v)) + '</b> is not an angle \u2014 give degrees, 0\u2013360.', 'bad'); return; }
      arPush();
      st.north = ((n % 360) + 360) % 360; light_sunStore(st);
      lsArrowSync();
      lsApplyToast(st, 'True north is <b>' + st.north.toFixed(1) + '\u00b0</b> clockwise of the plan\u2019s up.');
      if(typeof arDirty === 'function') arDirty(true);
    }
  };

  function lsSetLatLon(opt, who, allowPlace){
    var st = light_sunSite();
    var lat = null, lon = null, tz = null;
    if(opt && typeof opt === 'object' && (opt.lat !== undefined || opt.lon !== undefined)){
      lat = parseFloat(opt.lat); lon = parseFloat(opt.lon);
      if(opt.tz !== undefined && isFinite(parseFloat(opt.tz))) tz = parseFloat(opt.tz);
    }else{
      var place = (opt && typeof opt === 'object' && opt.place !== undefined) ? String(opt.place) : null;
      if(place === null){
        var q = allowPlace ? 'Site \u2014 a place name, or "lat, lon" in degrees:' : 'Site latitude and longitude, as "lat, lon" in degrees:';
        var v = prompt(q, st.lat + ', ' + st.lon);
        if(v === null || v === undefined) return null;
        var m = /^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$/.exec(v);
        if(m){ lat = parseFloat(m[1]); lon = parseFloat(m[2]); }
        else if(allowPlace) place = v;
        else { arToast('Give the site as <b>lat, lon</b> in degrees, e.g. 52.37, 4.90.', 'bad'); return null; }
      }
      if(lat === null && place !== null){
        var name = String(place).trim();
        if(!name){ arToast('No place given.', 'warn'); return null; }
        arToast('Looking up <b>' + esc(name) + '</b> \u2026');
        AR._lsGeoP = light_sunGeocode(name).then(function(r){
          if(!r || !r.ok){
            arToast('Could not find <b>' + esc(name) + '</b>' + (r && r.error ? ' \u2014 ' + esc(String(r.error)) : '') + '.', 'bad');
            return r;
          }
          var s2 = light_sunSite();
          arPush();
          s2.lat = r.lat; s2.lon = r.lon;
          if(isFinite(+r.tz)) s2.tz = +r.tz;
          light_sunStore(s2);
          var sol = light_sunApply();
          arToast('Site: <b>' + esc(r.name || name) + '</b> \u2014 <b>' + r.lat.toFixed(4) + ', ' + r.lon.toFixed(4)
                  + '</b>. Sun ' + sol.elevation.toFixed(1) + '\u00b0 high, bearing ' + sol.azimuth.toFixed(1)
                  + '\u00b0. Coordinates \u00a9 OpenStreetMap contributors, ODbL.');
          if(typeof arDirty === 'function') arDirty(true);
          return r;
        });
        return null;
      }
    }
    if(!isFinite(lat) || !isFinite(lon)){
      arToast('Give the site as <b>lat, lon</b> in degrees, e.g. 52.37, 4.90.', 'bad');
      return null;
    }
    arPush();
    st.lat = Math.max(-90, Math.min(90, lat));
    st.lon = Math.max(-180, Math.min(180, lon));
    if(tz !== null) st.tz = Math.max(-14, Math.min(14, tz));
    light_sunStore(st);
    lsApplyToast(st, who + ': <b>' + st.lat.toFixed(4) + ', ' + st.lon.toFixed(4) + '</b> (UTC'
                 + (st.tz >= 0 ? '+' : '') + st.tz + ').');
    if(typeof arDirty === 'function') arDirty(true);
    return st;
  }

  AR_EXT.tools.l_geo = {
    assist: 1,
    tip: 'Site latitude and longitude — the sun path is a function of where the building is',
    act: function(opt){ lsSetLatLon(opt, 'Site', false); }
  };

  AR_EXT.tools.st_geo = {
    assist: 1,
    tip: 'Pin the drawing to a real coordinate, which is what makes the sun and the site true — a place name or lat, lon',
    act: function(opt){ lsSetLatLon(opt, 'Site', true); }
  };

  AR_EXT.tools.st_north = {
    assist: 1, tog: 1,
    tip: 'A north point on the drawing itself, which every plan needs before it is issued',
    on: function(){ return !!(AR._lsArrow && AR._lsArrow.visible); },
    act: function(){
      var on = lsArrowShow(!(AR._lsArrow && AR._lsArrow.visible));
      var st = light_sunSite();
      arToast(on ? ('North arrow <b>on</b> \u2014 pointing ' + st.north.toFixed(1)
                    + '\u00b0 clockwise of the plan\u2019s up.') : 'North arrow <b>off</b>.');
    }
  };

  /* ── wiring ─────────────────────────────────────────────────────────── */
  AR_EXT.ready.push(function(){
    /* l_time keeps working, but every hour now goes through the solar model */
    var base = arSunSet;
    arSunSet = function(h){
      var v = Math.max(0, Math.min(24, arNum(h, 14)));
      AR.sunHour = v;
      try{ light_sunApply(v); }
      catch(e){ base(v); }                 /* never leave the studio without a sun */
    };

    lsArrowMake();
    var cur = (AR.doc && AR.doc.ext) ? AR.doc.ext.light_sun : null;
    if(cur && typeof cur === 'object'){
      if(isFinite(+cur.north)) lsArrowShow(true);   /* a drawing that knows its north shows it */
      light_sunApply();
    }
    AR._lsSig = JSON.stringify((AR.doc && AR.doc.ext) ? AR.doc.ext.light_sun : null);
  });

  /* a drawing opened from disk, or a document the assistant sent back, carries
     its own site: notice the change and re-apply. Throttled — arBounds walks
     every record. */
  var tick = 0;
  AR_EXT.ticks.push(function(){
    if((++tick % 20) !== 0) return;
    if(!AR.doc || !AR.doc.ext) return;
    var sig = JSON.stringify(AR.doc.ext.light_sun || null);
    if(sig === AR._lsSig) { lsArrowSync(); return; }
    AR._lsSig = sig;
    if(AR.doc.ext.light_sun){
      if(AR._lsArrow && !AR._lsArrow.visible && isFinite(+AR.doc.ext.light_sun.north)) lsArrowShow(true);
      light_sunApply();
    }
  });

  /* the family's globals, for the assistant, the tests and the other icons */
  window.light_sunCalc = light_sunCalc;
  window.light_sunApply = light_sunApply;
  window.light_sunDir = light_sunDir;
  window.light_sunSite = light_sunSite;
  window.light_sunStore = light_sunStore;
  window.light_sunHM = light_sunHM;
  window.light_sunGeocode = light_sunGeocode;
})();
