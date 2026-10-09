// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* quantities — the Quantities dock family (2026-09-07).

   Seven icons, one engine. `window.quantities` (alias `window.arQuantities`)
   owns the arithmetic; every icon is a thin press on top of it, so the volume
   the cost estimate prices and the volume the CSV writes are the same number
   computed once.

   HOW A VOLUME IS MEASURED. Not from a bounding box and not from a second copy
   of the parameter arithmetic: from the geometry the studio actually builds.
   arGeom(kind, p) is asked for the record's parts and each closed part is
   integrated as the sum of signed tetrahedra over its triangles
   (V = Σ a·(b×c)/6, exact for a closed mesh), the surface area as the sum of
   the triangles. That is why a wall with a door in it reports the wall MINUS
   the door: the hole is really cut out of the mesh, so it is really missing
   from the integral. Line-only parts (kind 'opening', guides) contribute 0.
   A record's uniform scale s multiplies volume by s³ and area by s².

   MASS is volume × density, from the table below, keyed on the WORD in the
   material id — so the 460 acg_* surfaces price themselves by their category
   ('acg_bricks_02' is brick) without a 460-line table.

   UNITS AND PRECISION are a DISPLAY wrapper around the studio's arFmt, put on
   in AR_EXT.ready. Nothing in the document changes: the properties panel is
   run with the plain metre formatter restored, so its inputs keep writing
   metres whatever the page is showing. Volumes and areas stay m³/m² (a
   cubic millimetre is not a useful number); the unit applies to lengths.

   Nothing here edits inspection.html. Registrations only, plus wrappers put on
   writable page globals inside AR_EXT.ready. */
(function () {
  'use strict';

  var LS_UNITS = 'ar.quantities.units';
  var LS_DEC = 'ar.quantities.decimals';

  /* kg/m³ by material word. 'other' is the honest default: a surface we cannot
     name is 1000, and the report says how much volume fell into it. */
  var DENSITY = {concrete: 2400, brick: 1800, timber: 600, glass: 2500, plaster: 1200,
                 steel: 7850, asphalt: 2300, soil: 1500, tile: 2000, other: 1000};

  /* EUR. Editable in the cost sheet, stored per drawing in AR.doc.ext.quantities.rates.
     A material is priced per m³ when it has a per_m3 rate, per m² when it has a
     per_m2 one — plaster and glass are surfaces, concrete and brick are solids,
     so nothing is charged twice. */
  var DEFAULT_RATES = {
    per_m3: {concrete: 180, brick: 220, timber: 650, steel: 2400, asphalt: 120, tile: 900, soil: 45},
    per_m2: {glass: 350, plaster: 25},
    per_item: {door: 450, window: 600, column: 300}
  };

  var UNIT_ORDER = ['m', 'mm', 'ft'];
  var DEC_ORDER = [null, 0, 1, 2, 3];          /* null = the studio's own adaptive format */
  var SNAP = 0.05;                             /* 5 cm: how close two wall ends must be to be one corner */

  /* A DIAGRAM is not a material. Several families draw real, closed meshes that
     mean something other than "stuff you buy": a zone is a 5 cm slab over the
     floor it labels, a grid line and a dimension are drawn so you can see them.
     Integrating those would put a 4 x 4 m zone into the take-off as 0.8 m³ of
     whatever colour its use happens to be, and the cost sheet would then charge
     for it. They are counted and named in the reports instead, never priced.
     This list is the same one arch_assistant_ext/quantities.py excludes, which
     is why the tab and the assistant's twin agree on a drawing that has zones. */
  var DIAGRAM = {zone: 1, gridline: 1, annotation: 1, dimension: 1,
                 label_text: 1, markup_note: 1, site_boundary: 1};
  var DIAGRAM_PREFIX = /^(guide_|dim_|sculpt_)/;
  function isDiagram(kind) {
    return !!DIAGRAM[kind] || DIAGRAM_PREFIX.test(String(kind || ''));
  }

  var S = {units: 'm', dec: null, rates: null, last: null, lastCsv: null};

  /* ── material words ──────────────────────────────────────────────────── */
  function matWord(id) {
    var s = String(id || '').toLowerCase();
    if (/concrete|cement|screed/.test(s)) return 'concrete';
    if (/brick|blockwork|masonry/.test(s)) return 'brick';
    if (/timber|wood|plank|oak|pine|birch|bamboo/.test(s)) return 'timber';
    if (/glass|glazing|glaz/.test(s)) return 'glass';
    if (/plaster|render|stucco|paint/.test(s)) return 'plaster';
    if (/steel|metal|iron|alu|copper|brass|zinc/.test(s)) return 'steel';
    if (/asphalt|tarmac|bitumen/.test(s)) return 'asphalt';
    if (/grass|soil|earth|dirt|gravel|sand|mud/.test(s)) return 'soil';
    if (/tile|ceramic|terracotta|slate/.test(s)) return 'tile';
    return 'other';
  }
  function density(id) { return DENSITY[matWord(id)] || DENSITY.other; }
  function matName(id) {
    return (window.AR && AR.matDefs && AR.matDefs[id] && AR.matDefs[id].n) || String(id || '—');
  }

  /* ── volume and area of one built part ───────────────────────────────── */
  function partVA(g) {
    var pos = g && g.getAttribute && g.getAttribute('position');
    if (!pos || !pos.count) return null;
    var idx = g.getIndex ? g.getIndex() : null;
    var n = idx ? idx.count : pos.count, V = 0, A = 0, i;
    for (i = 0; i + 2 < n; i += 3) {
      var i0 = idx ? idx.getX(i) : i, i1 = idx ? idx.getX(i + 1) : i + 1, i2 = idx ? idx.getX(i + 2) : i + 2;
      var ax = pos.getX(i0), ay = pos.getY(i0), az = pos.getZ(i0);
      var bx = pos.getX(i1), by = pos.getY(i1), bz = pos.getZ(i1);
      var cx = pos.getX(i2), cy = pos.getY(i2), cz = pos.getZ(i2);
      V += (ax * (by * cz - bz * cy) + ay * (bz * cx - bx * cz) + az * (bx * cy - by * cx)) / 6;
      var ux = bx - ax, uy = by - ay, uz = bz - az, vx = cx - ax, vy = cy - ay, vz = cz - az;
      var nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
      A += Math.sqrt(nx * nx + ny * ny + nz * nz) / 2;
    }
    return {v: Math.abs(V), a: A};
  }

  function storeyOf(y) {
    var h = (window.AR && AR.defaults && AR.defaults.wall_h) || 2.7;
    return Math.round((y || 0) / h);
  }

  /* ── the take-off ────────────────────────────────────────────────────────
     An array of one row per visible record, carrying byMat / byKind / totals
     as properties of the array (so `takeoff()` really is "rows"). */
  function takeoff() {
    var rows = [], byMat = {}, byKind = {},
        totals = {vol: 0, area: 0, mass: 0, net: 0, records: 0, unknown: 0, diagram: 0};
    (window.AR ? AR.objs : []).forEach(function (o) {
      if (o.hidden) return;
      if (isDiagram(o.kind)) { totals.diagram++; return; }   /* counted, never priced */
      var s = o.s || 1, parts = [];
      try { parts = arGeom(o.kind, o.p) || []; } catch (e) { parts = []; }
      var per = {}, vol = 0, area = 0;
      parts.forEach(function (pt) {
        if (!pt || !pt.g || pt.line) return;
        var r = partVA(pt.g);
        try { pt.g.dispose(); } catch (e) { /* a geometry we made only to measure */ }
        if (!r) return;
        var m = pt.sub || o.mat, v = r.v * s * s * s, a = r.a * s * s;
        vol += v; area += a;
        per[m] = per[m] || {v: 0, a: 0};
        per[m].v += v; per[m].a += a;
      });
      var net = 0;
      if (o.kind === 'wall' || o.kind === 'partition') {
        var L = arNum(o.p.len, 4), H = arNum(o.p.h, 2.7);
        net = L * H;
        (o.p.holes || []).forEach(function (h) { net -= arNum(h.w, 0) * arNum(h.h, 0); });
        net = Math.max(0, net) * s * s;
      }
      var mass = 0;
      Object.keys(per).forEach(function (m) {
        mass += per[m].v * density(m);
        var e = byMat[m] || (byMat[m] = {mat: m, n: 0, vol: 0, area: 0, mass: 0});
        e.n++; e.vol += per[m].v; e.area += per[m].a; e.mass += per[m].v * density(m);
        if (matWord(m) === 'other') totals.unknown += per[m].v;
      });
      var k = byKind[o.kind] || (byKind[o.kind] = {kind: o.kind, n: 0, vol: 0, area: 0, net: 0});
      k.n++; k.vol += vol; k.area += area; k.net += net;
      totals.vol += vol; totals.area += area; totals.mass += mass; totals.net += net; totals.records++;
      rows.push({id: o.id, name: o.name || arKindLabel(o.kind), kind: o.kind, mat: o.mat,
                 storey: storeyOf(o.y), vol: vol, area: area, net: net, mass: mass});
    });
    rows.byMat = byMat; rows.byKind = byKind; rows.totals = totals;
    return rows;
  }

  /* ── display units ───────────────────────────────────────────────────── */
  function gcd(a, b) { return b ? gcd(b, a % b) : a; }
  function feetInches(v, denom) {
    var neg = v < 0; v = Math.abs(v);
    var totIn = v / 0.0254, ft = Math.floor(totIn / 12), inch = totIn - ft * 12;
    var whole = Math.floor(inch), frac = Math.round((inch - whole) * denom);
    if (frac >= denom) { frac = 0; whole++; }
    if (whole >= 12) { whole -= 12; ft++; }
    var out = ft + "' " + whole;
    if (frac > 0) { var g = gcd(frac, denom); out += ' ' + (frac / g) + '/' + (denom / g); }
    return (neg ? '-' : '') + out + '"';
  }
  function unitLabel() { return S.units === 'ft' ? 'ft-in' : S.units; }
  function precLabel() { return S.dec === null ? 'auto' : String(S.dec); }
  function currency() { return S.units === 'ft' ? {sym: '$', code: 'USD'} : {sym: '\u20ac', code: 'EUR'}; }

  /* ── per-drawing / per-browser storage ───────────────────────────────── */
  function ext(make) {
    if (!window.AR || !AR.doc) return null;
    if (!AR.doc.ext || typeof AR.doc.ext !== 'object') { if (!make) return null; AR.doc.ext = {}; }
    if (!AR.doc.ext.quantities) { if (!make) return null; AR.doc.ext.quantities = {}; }
    return AR.doc.ext.quantities;
  }
  function rates() {
    var e = ext(false), r = e && e.rates;
    if (!S.rates) S.rates = JSON.parse(JSON.stringify(DEFAULT_RATES));
    if (r && typeof r === 'object') {
      ['per_m3', 'per_m2', 'per_item'].forEach(function (g) {
        if (r[g] && typeof r[g] === 'object') {
          Object.keys(r[g]).forEach(function (k) {
            var v = parseFloat(r[g][k]);
            if (isFinite(v)) S.rates[g][k] = v;
          });
        }
      });
    }
    return S.rates;
  }
  function saveExt(patch) {
    if (window.arPush) arPush();                 /* ONE push, before the change */
    var e = ext(true);
    if (e) Object.keys(patch).forEach(function (k) { e[k] = patch[k]; });
    if (window.arDirty) arDirty(true);
  }

  /* ── HTML helpers ────────────────────────────────────────────────────── */
  function cell(v) { return typeof v === 'string' ? esc(v) : esc(String(v)); }
  function table(headers, rows, foot) {
    var h = '<table class="ar-tbl"><tr>' + headers.map(function (x) {
      return '<td style="color:var(--muted)"><b>' + cell(x) + '</b></td>'; }).join('') + '</tr>';
    h += rows.map(function (r) {
      return '<tr>' + r.map(function (x) { return '<td>' + cell(x) + '</td>'; }).join('') + '</tr>'; }).join('');
    if (foot) h += '<tr>' + foot.map(function (x) { return '<td><b>' + cell(x) + '</b></td>'; }).join('') + '</tr>';
    return h + '</table>';
  }
  function n2(v) { return (Math.round(v * 100) / 100).toFixed(2); }
  function n3(v) { return (Math.round(v * 1000) / 1000).toFixed(3); }
  function header(extra) {
    return '<div class="ar-note">Lengths are shown in <b>' + unitLabel() + '</b> at ' + precLabel()
      + ' decimals; areas and volumes stay m&sup2;/m&sup3;. The properties panel always writes metres.'
      + (extra ? ' ' + extra : '') + '</div>';
  }

  /* ── the four reports ────────────────────────────────────────────────── */
  function repVolume() {
    var t = takeoff(), by = t.byMat;
    var keys = Object.keys(by).sort(function (a, b) { return by[b].vol - by[a].vol; });
    var rows = keys.map(function (m) {
      return [matName(m), by[m].n, n3(by[m].vol), n3(by[m].mass / 1000)];
    });
    return {name: 'volume', title: 'Volume and mass by material',
            headers: ['material', 'count', 'volume m\u00b3', 'mass t'], rows: rows,
            foot: ['total', t.totals.records, n3(t.totals.vol), n3(t.totals.mass / 1000)],
            note: header('Volumes are integrated from the built mesh, so a wall reports itself minus its openings; '
                         + 'net wall face area is ' + n2(t.totals.net) + ' m&sup2;.'
                         + (t.totals.unknown > 0.0005 ? ' ' + n3(t.totals.unknown)
                            + ' m\u00b3 fell into the default 1000 kg/m\u00b3 bucket.' : '')
                         + (t.totals.diagram ? ' ' + t.totals.diagram + ' diagram object'
                            + (t.totals.diagram === 1 ? ' (a zone, grid line, dimension or guide) is'
                               : 's (zones, grid lines, dimensions, guides) are')
                            + ' drawn but not material, so ' + (t.totals.diagram === 1 ? 'it is' : 'they are')
                            + ' left out of the quantities.' : '')),
            take: t};
  }

  function costRows() {
    var t = takeoff(), R = rates(), by = t.byMat, cur = currency(), rows = [], total = 0;
    Object.keys(by).sort().forEach(function (m) {
      var w = matWord(m), e = by[m];
      var r3 = R.per_m3[w], r2 = R.per_m2[w];
      if (isFinite(r3) && r3 && e.vol > 1e-9) {
        var a3 = e.vol * r3; total += a3;
        rows.push([matName(m), n3(e.vol), 'm\u00b3', n2(r3), n2(a3)]);
      }
      if (isFinite(r2) && r2 && e.area > 1e-9) {
        var a2 = e.area * r2; total += a2;
        rows.push([matName(m), n2(e.area), 'm\u00b2', n2(r2), n2(a2)]);
      }
    });
    var items = {door: 0, window: 0, column: 0};
    (window.AR ? AR.objs : []).forEach(function (o) {
      if (o.hidden) return;
      if (o.kind === 'door' || o.kind === 'double_door') items.door++;
      else if (/^window/.test(o.kind)) items.window++;
      else if (/^column/.test(o.kind)) items.column++;
    });
    Object.keys(items).forEach(function (k) {
      var r = R.per_item[k];
      if (items[k] && isFinite(r) && r) {
        var amt = items[k] * r; total += amt;
        rows.push([k, items[k], 'item', n2(r), n2(amt)]);
      }
    });
    return {rows: rows, total: total, cur: cur, take: t};
  }

  function repCost() {
    var c = costRows(), R = rates();
    var inputs = '<div class="sh">Rate card (' + c.cur.code + ') — edit and save into this drawing</div>'
      + ['per_m3', 'per_m2', 'per_item'].map(function (g) {
        return '<div class="ar-note">' + g + '</div>' + Object.keys(R[g]).sort().map(function (k) {
          return '<div class="ar-prow"><label>' + esc(k) + '</label>'
            + '<input type="number" step="1" data-qrate="' + esc(g) + '|' + esc(k) + '" value="' + esc(String(R[g][k])) + '"></div>';
        }).join('');
      }).join('')
      + '<div class="ar-prow"><label></label><button onclick="quantities.saveRates()">Save rates into the drawing</button></div>';
    return {name: 'cost', title: 'Cost estimate (' + c.cur.code + ')',
            headers: ['item', 'quantity', 'unit', 'rate ' + c.cur.sym, 'amount ' + c.cur.sym],
            rows: c.rows, foot: ['total', '', '', '', n2(c.total)],
            extraHtml: inputs, total: c.total,
            note: header('The rate card is ' + c.cur.code + ' because the unit system is '
                         + unitLabel() + '. Quantities come from the same take-off the Volume sheet shows.')};
  }

  function repDoors() {
    var rows = [];
    (window.AR ? AR.objs : []).forEach(function (o) {
      if (o.hidden || !arIsOpening(o.kind)) return;
      var p = o.p || {};
      rows.push({sortS: storeyOf(o.y), sortH: String(p.host || ''),
                 r: [o.id, o.name || arKindLabel(o.kind), arKindLabel(o.kind),
                     arFmt(arNum(p.w, 0)) + ' \u00d7 ' + arFmt(arNum(p.h, 0)),
                     arFmt(arNum(p.sill, 0)), String(p.host || '\u2014'),
                     storeyOf(o.y), matName(o.mat)]});
    });
    rows.sort(function (a, b) { return (a.sortS - b.sortS) || (a.sortH < b.sortH ? -1 : a.sortH > b.sortH ? 1 : 0); });
    return {name: 'doors', title: 'Door and window schedule',
            headers: ['id', 'name', 'kind', 'w \u00d7 h', 'sill', 'host wall', 'storey', 'material'],
            rows: rows.map(function (x) { return x.r; }),
            foot: ['total', rows.length, '', '', '', '', '', ''],
            note: header('Sorted by storey then host wall. An opening with no host is not standing in a wall.')};
  }

  /* ── rooms ───────────────────────────────────────────────────────────────
     Zones if the drawing has them (a zone is a declared room), otherwise the
     bounded faces of the wall graph: snap the wall ends onto a 5 cm grid,
     sort the edges around every node by angle and walk each face by always
     taking the next edge clockwise from the one we came in on. In (x, -z) that
     walk gives every enclosed face a positive signed area and the outside a
     negative one, so the outer face drops out by arithmetic rather than by a
     guess about which loop is the building. */
  function shoelace(pts) {
    var s = 0, n = pts.length, i;
    for (i = 0; i < n; i++) {
      var a = pts[i], b = pts[(i + 1) % n];
      s += a[0] * b[1] - b[0] * a[1];
    }
    return s / 2;
  }
  function perim(pts) {
    var s = 0, n = pts.length, i;
    for (i = 0; i < n; i++) {
      var a = pts[i], b = pts[(i + 1) % n];
      s += Math.hypot(b[0] - a[0], b[1] - a[1]);
    }
    return s;
  }

  function roomsFromWalls() {
    var byStorey = {};
    (window.AR ? AR.objs : []).forEach(function (o) {
      if (o.hidden || (o.kind !== 'wall' && o.kind !== 'partition')) return;
      var s = o.s || 1, L = arNum(o.p.len, 4) * s, ry = o.ry || 0;
      if (L < 0.01) return;
      var dx = (L / 2) * Math.cos(ry), dz = -(L / 2) * Math.sin(ry);   /* node.rotation.y: +X -> (cos, -sin) */
      var k = storeyOf(o.y);
      (byStorey[k] = byStorey[k] || []).push([[o.x - dx, o.z - dz], [o.x + dx, o.z + dz]]);
    });
    var out = [];
    Object.keys(byStorey).forEach(function (sk) {
      var segs = byStorey[sk], nodes = {}, adj = {};
      var key = function (p) {
        return Math.round(p[0] / SNAP) + '_' + Math.round(p[1] / SNAP);
      };
      segs.forEach(function (sg) {
        var ka = key(sg[0]), kb = key(sg[1]);
        if (ka === kb) return;
        if (!nodes[ka]) { nodes[ka] = [Math.round(sg[0][0] / SNAP) * SNAP, Math.round(sg[0][1] / SNAP) * SNAP]; adj[ka] = {}; }
        if (!nodes[kb]) { nodes[kb] = [Math.round(sg[1][0] / SNAP) * SNAP, Math.round(sg[1][1] / SNAP) * SNAP]; adj[kb] = {}; }
        adj[ka][kb] = 1; adj[kb][ka] = 1;
      });
      /* neighbours of every node, sorted by angle in the (x, -z) plane */
      var order = {};
      Object.keys(adj).forEach(function (k) {
        order[k] = Object.keys(adj[k]).sort(function (a, b) {
          return Math.atan2(-(nodes[a][1] - nodes[k][1]), nodes[a][0] - nodes[k][0])
               - Math.atan2(-(nodes[b][1] - nodes[k][1]), nodes[b][0] - nodes[k][0]);
        });
      });
      var seen = {}, faces = [];
      Object.keys(adj).forEach(function (u) {
        Object.keys(adj[u]).forEach(function (v0) {
          if (seen[u + '>' + v0]) return;
          var loop = [], a = u, b = v0, guard = 0;
          while (guard++ < 4000) {
            if (seen[a + '>' + b]) break;
            seen[a + '>' + b] = 1;
            loop.push(a);
            var ring = order[b], i = ring.indexOf(a);
            if (i < 0) break;
            var nxt = ring[(i - 1 + ring.length) % ring.length];    /* next one clockwise */
            a = b; b = nxt;
            if (a === u && b === v0) break;
          }
          if (loop.length >= 3) faces.push(loop);
        });
      });
      faces.forEach(function (loop) {
        var pts = loop.map(function (k) { return [nodes[k][0], -nodes[k][1]]; });   /* (x, -z) */
        var A = shoelace(pts);
        if (A > 0.05) out.push({storey: parseInt(sk, 10), area: A, perim: perim(pts), use: ''});
      });
    });
    out.sort(function (a, b) { return (a.storey - b.storey) || (b.area - a.area); });
    return out;
  }

  function roomsFromZones() {
    var out = [];
    (window.AR ? AR.objs : []).forEach(function (o) {
      if (o.hidden || o.kind !== 'zone') return;
      var pts = (o.p && o.p.pts) || [];
      if (!Array.isArray(pts) || pts.length < 3) return;
      var q = pts.map(function (p) { return [arNum(p[0], 0), -arNum(p[1], 0)]; });
      out.push({storey: storeyOf(o.y), area: Math.abs(shoelace(q)), perim: perim(q),
                use: String((o.p && o.p.use) || ''), name: o.name || ''});
    });
    out.sort(function (a, b) { return (a.storey - b.storey) || (b.area - a.area); });
    return out;
  }

  function hasZones() {
    return (window.AR ? AR.objs : []).some(function (o) { return o.kind === 'zone' && !o.hidden; });
  }

  function rooms() {
    var zoned = hasZones();
    var list = zoned ? roomsFromZones() : roomsFromWalls();
    return {method: zoned ? 'zone records' : 'closed wall loops', rooms: list};
  }

  function repRooms() {
    var r = rooms();
    var rows = [['method', r.method + (r.method === 'closed wall loops'
      ? ' (no zone records in this drawing; wall ends snapped at ' + (SNAP * 100) + ' cm)'
      : ''), '', '', '']];
    r.rooms.forEach(function (x, i) {
      rows.push([x.name || ('Room ' + (i + 1)), x.storey, n2(x.area), n2(x.perim), x.use || '\u2014']);
    });
    return {name: 'rooms', title: 'Room schedule',
            headers: ['room', 'storey', 'area m\u00b2', 'perimeter m', 'use'], rows: rows,
            foot: ['total', r.rooms.length, n2(r.rooms.reduce(function (s, x) { return s + x.area; }, 0)), '', ''],
            note: header('The first row says which method produced these rooms.'), roomsList: r.rooms};
  }

  function repBom() {
    var by = {};
    (window.AR ? AR.objs : []).forEach(function (o) {
      var k = o.kind + '|' + o.mat;
      by[k] = by[k] || {kind: o.kind, mat: o.mat, n: 0, hid: 0};
      by[k].n++; if (o.hidden) by[k].hid++;
    });
    var t = takeoff(), volByKind = t.byKind;
    var rows = Object.keys(by).sort().map(function (k) {
      var e = by[k];
      return [arKindLabel(e.kind), matName(e.mat), e.n, e.hid,
              n3((volByKind[e.kind] ? volByKind[e.kind].vol : 0))];
    });
    return {name: 'bom', title: 'Bill of materials',
            headers: ['kind', 'material', 'count', 'hidden', 'volume m\u00b3 (kind total)'], rows: rows,
            foot: ['total', '', (window.AR ? AR.objs.length : 0), '', n3(t.totals.vol)],
            note: header('Re-derived from the records, not scraped from the Bill of materials sheet.')};
  }

  var REPORTS = {volume: repVolume, cost: repCost, doors: repDoors, rooms: repRooms, bom: repBom};

  function show(rep) {
    S.last = rep;
    arSheet(rep.title, rep.note + table(rep.headers, rep.rows, rep.foot) + (rep.extraHtml || ''));
    return rep;
  }

  /* ── CSV ─────────────────────────────────────────────────────────────── */
  function sep() {
    var l = String((navigator && (navigator.language || navigator.userLanguage)) || 'en').toLowerCase();
    return (/^(nl|de)/.test(l)) ? ';' : ',';
  }
  function csvOf(rep) {
    var d = sep();
    var q = function (v) {
      var s = String(v === undefined || v === null ? '' : v).replace(/<[^>]*>/g, '');
      s = s.replace(/&sup2;/g, '2').replace(/&sup3;/g, '3').replace(/&middot;/g, '.').replace(/&mdash;|&ndash;/g, '-');
      return (s.indexOf(d) >= 0 || s.indexOf('"') >= 0 || /[\r\n]/.test(s))
        ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    /* header + the rows, and NOT the sheet's totals line: a spreadsheet sums
       its own column, and a stray total inside the data is what breaks it. */
    var lines = [rep.headers.map(q).join(d)];
    rep.rows.forEach(function (r) { lines.push(r.map(q).join(d)); });
    return '\ufeff' + lines.join('\r\n') + '\r\n';
  }

  /* ── the arFmt / arHud / arPanel wrappers ────────────────────────────── */
  var baseFmt = null;
  function metres(v) { return baseFmt ? baseFmt(v) : String(v); }

  function refresh() {
    try { if (window.arHud) arHud(); } catch (e) { /* the HUD is optional */ }
    try { if (window.arPanel) arPanel(); } catch (e) { /* so is the panel */ }
    var sh = document.getElementById('ar-sheet');
    if (S.last && sh && sh.style.display !== 'none') {
      var f = REPORTS[S.last.name];
      if (f) show(f());
    }
  }

  AR_EXT.ready.push(function () {
    /* remembered preferences: the browser's, then the drawing's */
    try {
      var u = localStorage.getItem(LS_UNITS);
      if (UNIT_ORDER.indexOf(u) >= 0) S.units = u;
      var d = localStorage.getItem(LS_DEC);
      if (d !== null && d !== '' && d !== 'auto') S.dec = Math.max(0, Math.min(3, parseInt(d, 10) || 0));
    } catch (e) { /* private browsing */ }
    var e0 = ext(false);
    if (e0) {
      if (UNIT_ORDER.indexOf(e0.units) >= 0) S.units = e0.units;
      if (e0.decimals === null || (typeof e0.decimals === 'number')) S.dec = e0.decimals;
    }

    baseFmt = arFmt;
    arFmt = function (v) {
      var x = (typeof v === 'number') ? v : parseFloat(v);
      if (!isFinite(x)) return baseFmt(v);
      if (S.units === 'mm') return String(Math.round(x * 1000));
      if (S.units === 'ft') return feetInches(x, (S.dec === null || S.dec <= 1) ? 8 : 16);
      return (S.dec === null) ? baseFmt(x) : x.toFixed(S.dec);
    };

    var baseHud = arHud;
    arHud = function () {
      baseHud();
      var el = document.getElementById('ar-hud');
      if (!el) return;
      el.innerHTML += '<span>units <b>' + unitLabel() + '</b></span>'
        + '<span>dp <b>' + precLabel() + '</b></span>';
    };

    /* The panel's number inputs are the document, not a display: run the base
       with the plain metre formatter so they keep reading and writing metres,
       then label them with the unit they are in. */
    var basePanel = arPanel;
    arPanel = function () {
      var f = arFmt;
      arFmt = metres;
      try { basePanel(); } finally { arFmt = f; }
      if (S.units === 'm' && S.dec === null) return;
      var bd = document.getElementById('ar-panel-bd');
      if (!bd) return;
      Array.prototype.forEach.call(bd.querySelectorAll('.ar-prow label'), function (lb) {
        var t = lb.textContent;
        if (/^(x|y \(height\)|z|rotation.*|scale)$/i.test(t) || /^(len|h|t|w|d|r|sill|span|tick)$/.test(t)) {
          lb.textContent = t + ' (m)';
        }
      });
      var note = document.createElement('div');
      note.className = 'ar-note';
      note.innerHTML = 'The page is displaying <b>' + unitLabel() + '</b>; these fields are and stay <b>metres</b>.';
      bd.insertBefore(note, bd.firstChild);
    };

    refresh();
  });

  /* the drawing may arrive from the assistant with its own units/decimals */
  AR_EXT.ticks.push(function () {
    var e = ext(false);
    if (!e) return;
    var dirty = false;
    if (UNIT_ORDER.indexOf(e.units) >= 0 && e.units !== S.units) { S.units = e.units; dirty = true; }
    if ((e.decimals === null || typeof e.decimals === 'number') && e.decimals !== S.dec) {
      S.dec = (e.decimals === null) ? null : Math.max(0, Math.min(3, e.decimals | 0));
      dirty = true;
    }
    if (dirty) { S.rates = null; refresh(); }
  });

  /* ── the public engine ───────────────────────────────────────────────── */
  var API = {
    takeoff: takeoff,
    density: density,
    matWord: matWord,
    densities: DENSITY,
    defaultRates: DEFAULT_RATES,
    rates: rates,
    rooms: rooms,
    report: function (name) { var f = REPORTS[name]; return f ? f() : null; },
    reports: REPORTS,
    show: show,
    csvOf: csvOf,
    get last() { return S.last; },
    get lastCsv() { return S.lastCsv; },
    get units() { return S.units; },
    get decimals() { return S.dec; },
    setUnits: function (u) {
      if (UNIT_ORDER.indexOf(u) < 0) return false;
      S.units = u;
      try { localStorage.setItem(LS_UNITS, u); } catch (e) { /* private browsing */ }
      saveExt({units: u});
      refresh();
      return true;
    },
    setDecimals: function (d) {
      S.dec = (d === null) ? null : Math.max(0, Math.min(3, parseInt(d, 10) || 0));
      try { localStorage.setItem(LS_DEC, S.dec === null ? 'auto' : String(S.dec)); } catch (e) { /* ignore */ }
      saveExt({decimals: S.dec});
      refresh();
      return S.dec;
    },
    setRates: function (patch) {
      var R = rates();
      if (patch && typeof patch === 'object') {
        ['per_m3', 'per_m2', 'per_item'].forEach(function (g) {
          if (patch[g] && typeof patch[g] === 'object') {
            Object.keys(patch[g]).forEach(function (k) {
              var v = parseFloat(patch[g][k]);
              if (isFinite(v)) R[g][k] = v;
            });
          }
        });
      }
      saveExt({rates: JSON.parse(JSON.stringify(R))});
      return R;
    },
    saveRates: function () {
      var R = rates(), n = 0;
      Array.prototype.forEach.call(document.querySelectorAll('[data-qrate]'), function (inp) {
        var parts = inp.getAttribute('data-qrate').split('|'), v = parseFloat(inp.value);
        if (parts.length === 2 && isFinite(v) && R[parts[0]]) { R[parts[0]][parts[1]] = v; n++; }
      });
      saveExt({rates: JSON.parse(JSON.stringify(R))});
      arToast('Rate card saved into this drawing (' + n + ' rates).');
      show(repCost());
    },
    exportCsv: function (name) {
      var which = (name && REPORTS[name]) ? name : null;
      var rep = which ? REPORTS[which]() : (S.last || repVolume());
      var text = csvOf(rep);
      S.lastCsv = {name: rep.name, text: text, sep: sep(),
                   lines: text.trim().split('\r\n').length,
                   filename: 'quantities-' + rep.name + '.csv'};
      arDownload(new Blob([text], {type: 'text/csv;charset=utf-8'}), S.lastCsv.filename);
      return S.lastCsv;
    }
  };
  window.quantities = API;
  window.arQuantities = API;

  /* ── the seven icons ─────────────────────────────────────────────────── */
  AR_EXT.tools.q_volume = {
    assist: 1,
    act: function () { show(repVolume()); }
  };

  AR_EXT.tools.q_cost = {
    assist: 1,
    act: function (opt) {
      if (opt && typeof opt === 'object' && opt.rates) API.setRates(opt.rates);
      var rep = show(repCost());
      arToast('Estimate: ' + rep.foot[4] + ' ' + currency().code + '.');
    }
  };

  AR_EXT.tools.q_doors = {
    assist: 1,
    act: function () { show(repDoors()); }
  };

  AR_EXT.tools.q_rooms = {
    assist: 1,
    act: function () { show(repRooms()); }
  };

  AR_EXT.tools.q_csv = {
    assist: 1,
    act: function (opt) {
      var name = (opt && typeof opt === 'object') ? String(opt.report || 'last')
        : String(prompt('Export which report as CSV — volume, cost, doors, rooms, bom or last?', 'last') || 'last');
      name = name.trim().toLowerCase();
      if (name !== 'last' && !REPORTS[name]) { arToast('No report called <b>' + esc(name) + '</b>.', 'bad'); return; }
      var out = API.exportCsv(name === 'last' ? null : name);
      arToast('Wrote <b>' + esc(out.filename) + '</b> (' + out.lines
        + ' lines, "' + out.sep + '" separated).');
    }
  };

  AR_EXT.tools.q_units = {
    assist: 1, tog: 1,
    on: function () { return S.units !== 'm'; },
    act: function (opt) {
      var u = (opt && typeof opt === 'object' && opt.units) ? String(opt.units)
        : UNIT_ORDER[(UNIT_ORDER.indexOf(S.units) + 1) % UNIT_ORDER.length];
      if (!API.setUnits(u)) { arToast('Units must be m, mm or ft.', 'bad'); return; }
      arToast('Display units: <b>' + unitLabel() + '</b> — the HUD, hints, sheets and reports follow. '
        + 'The properties panel still reads and writes <b>metres</b>.');
    }
  };

  AR_EXT.tools.q_prec = {
    assist: 1, tog: 1,
    on: function () { return S.dec !== null; },
    act: function (opt) {
      var d;
      if (opt && typeof opt === 'object' && opt.decimals !== undefined && opt.decimals !== null) d = opt.decimals;
      else if (opt && typeof opt === 'object' && opt.decimals === null) d = null;
      else d = DEC_ORDER[(DEC_ORDER.indexOf(S.dec) + 1) % DEC_ORDER.length];
      API.setDecimals(d);
      arToast('Display precision: <b>' + precLabel() + '</b>'
        + (S.units === 'mm' ? ' — millimetres are shown whole.'
           : S.units === 'ft' ? ' — inches to the nearest 1/' + ((S.dec === null || S.dec <= 1) ? 8 : 16) + '".'
           : ' decimal' + (S.dec === 1 ? '' : 's') + ' on a metre.')
        + ' The model is unchanged.');
    }
  };
}());
