// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* analyse_planning — Analyse ▸ Escape route (a_egress), Accessibility (a_access),
   Occupancy (a_occupancy) and Compartments (a_fire).

   FOUR ANALYSES, ONE ROOM FINDER. Everything below reads the drawing and reports;
   nothing here edits a record, so nothing here calls arPush(). The one thing an
   analysis draws is the worst escape route, a temporary THREE.Line on AR.scene
   that is removed when the sheet closes (arSheetClose is wrapped in AR_EXT.ready).

   window.analyse_planning.rooms(storey) is THE room finder, written once and
   reused by all four:
     · zone records first — kind 'zone', p.pts a LOCAL polygon [[x, z], ...]
       around the record's x/z, p.name / p.use / rec.name / rec.meta;
     · otherwise closed wall loops per storey: the centre-lines of 'wall' and
       'partition' records, endpoints and crossings snapped to 5 cm, noded, then
       every bounded face of the planar graph. AREAS ARE TO WALL CENTRE-LINES,
       not to the clear internal face — say so wherever a number is shown.
   A room is {key, name, use, storey, y, poly [{x, z} world], area, doors [ids],
   compartment, rec}. Its name/use/compartment come from the zone record, or from
   any record standing INSIDE the loop that carries meta.room / meta.use /
   meta.compartment (an annotation pin is the natural one), or from the family's
   own defaults in AR.doc.ext.analyse_planning.

   The four runs are registered on the shared AR_EXT.analyses registry
   ({id, label, run(opt) -> {ok, issues, rows}}) so Code check (a_code) can call
   them all in one pass; a_fire already calls a_egress through it.

   HONEST APPROXIMATIONS, stated in every sheet:
     · a door-to-door leg is a STRAIGHT LINE across the room that connects them —
       no obstacle avoidance, no 0.5 m wall offset;
     · the first leg of an escape route is the room's farthest polygon CORNER to
       its door, which is the worst point of a convex room and an under-estimate
       of a re-entrant one;
     · a wall is EXTERIOR where it has a room on one side only, tested by
       sampling t/2 + 0.15 m either side of the door / wall midpoint;
     · a door's clear width is p.w minus a 0.05 m frame.

   The Python twin arch_assistant_ext/analyse_planning.py is the SAME arithmetic
   with the same 5 cm snap (it nodes the centre-lines with shapely instead of by
   hand) and must agree with this file. Change one and you have two rule books. */
(function () {
  'use strict';

  var SNAP = 0.05;          /* wall endpoint / crossing snap, metres — the Python twin uses the same */
  var MIN_AREA = 0.5;       /* a face under this is a sliver of the noding, not a room */
  var GRID = 0.1;           /* inscribed-circle sample grid, metres */
  var SIDE = 0.15;          /* how far past a wall face a side sample sits */
  var MAX_WALLS = 600;      /* past this the O(n^2) noding is not worth the wait */

  var AP = (window.analyse_planning = window.analyse_planning || {});
  AR_EXT.analyses = AR_EXT.analyses || [];

  var WALL_KINDS = {wall: 1, partition: 1};
  var DOOR_KINDS = {door: 1, double_door: 1};

  /* m² per person — NL Bouwbesluit-ish. 0 means "not an occupied room" (n/a).
     Editable per drawing in the Occupancy sheet: AR.doc.ext.analyse_planning.rates. */
  var RATES = {office: 10, meeting: 2, retail: 3, residential: 20, bedroom: 12, bedrooms: 12,
               classroom: 2, corridor: 0, circulation: 0, assembly: 1, storage: 30};
  var RATE_DEFAULT = 10;

  /* ── small maths ─────────────────────────────────────────────────────── */
  function N(v, d) { var f = parseFloat(v); return isFinite(f) ? f : d; }
  function storeyH() { return N(window.AR && AR.defaults && AR.defaults.wall_h, 2.7) || 2.7; }
  function storeyOf(y) { return Math.round(N(y, 0) / storeyH()); }
  function dist(a, b) { return Math.sqrt((a.x - b.x) * (a.x - b.x) + (a.z - b.z) * (a.z - b.z)); }
  function key(x, z) { return Math.round(x / SNAP) + '_' + Math.round(z / SNAP); }
  function unkey(k) { var p = k.split('_'); return {x: parseInt(p[0], 10) * SNAP, z: parseInt(p[1], 10) * SNAP}; }

  function shoelace(poly) {
    var s = 0;
    for (var i = 0; i < poly.length; i++) {
      var a = poly[i], b = poly[(i + 1) % poly.length];
      s += a.x * b.z - b.x * a.z;
    }
    return s / 2;                        /* SIGNED */
  }

  function inPoly(x, z, poly) {
    var hit = false;
    for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      var a = poly[i], b = poly[j];
      if ((a.z > z) !== (b.z > z) && x < (b.x - a.x) * (z - a.z) / (b.z - a.z) + a.x) hit = !hit;
    }
    return hit;
  }

  function distSeg(x, z, a, b) {
    var dx = b.x - a.x, dz = b.z - a.z, L2 = dx * dx + dz * dz;
    var t = L2 <= 1e-12 ? 0 : ((x - a.x) * dx + (z - a.z) * dz) / L2;
    t = t < 0 ? 0 : (t > 1 ? 1 : t);
    var px = a.x + t * dx, pz = a.z + t * dz;
    return Math.sqrt((x - px) * (x - px) + (z - pz) * (z - pz));
  }

  function distEdges(x, z, poly) {
    var best = 1e9;
    for (var i = 0; i < poly.length; i++) {
      var d = distSeg(x, z, poly[i], poly[(i + 1) % poly.length]);
      if (d < best) best = d;
    }
    return best;
  }

  /* largest inscribed circle: a 0.1 m grid of the interior, distance to the
     nearest edge, then four halving hill-climb rounds around the best sample. */
  function inCircle(poly) {
    var x0 = 1e9, x1 = -1e9, z0 = 1e9, z1 = -1e9, i;
    for (i = 0; i < poly.length; i++) {
      if (poly[i].x < x0) x0 = poly[i].x;
      if (poly[i].x > x1) x1 = poly[i].x;
      if (poly[i].z < z0) z0 = poly[i].z;
      if (poly[i].z > z1) z1 = poly[i].z;
    }
    var step = GRID, best = {x: (x0 + x1) / 2, z: (z0 + z1) / 2, r: 0};
    var nx = Math.max(1, Math.floor((x1 - x0) / step)), nz = Math.max(1, Math.floor((z1 - z0) / step));
    if (nx * nz > 400000) { step = Math.sqrt((x1 - x0) * (z1 - z0) / 400000); nx = Math.max(1, Math.floor((x1 - x0) / step)); nz = Math.max(1, Math.floor((z1 - z0) / step)); }
    for (i = 0; i < nx; i++) {
      var px = x0 + (i + 0.5) * step;
      for (var j = 0; j < nz; j++) {
        var pz = z0 + (j + 0.5) * step;
        if (!inPoly(px, pz, poly)) continue;
        var d = distEdges(px, pz, poly);
        if (d > best.r) best = {x: px, z: pz, r: d};
      }
    }
    var s = step;
    for (var k = 0; k < 4; k++) {
      s /= 2;
      for (var a = -1; a <= 1; a++) for (var b = -1; b <= 1; b++) {
        if (!a && !b) continue;
        var qx = best.x + a * s, qz = best.z + b * s;
        if (!inPoly(qx, qz, poly)) continue;
        var dd = distEdges(qx, qz, poly);
        if (dd > best.r) best = {x: qx, z: qz, r: dd};
      }
    }
    return best;
  }

  /* ── records ─────────────────────────────────────────────────────────── */
  function objs() { return (window.AR && AR.objs) || []; }

  function isDoor(rec) { return !!(DOOR_KINDS[rec.kind] || /door/.test(rec.kind)); }

  /* a wall's centre-line. Local +X maps to world (cos ry, -sin ry) — the studio
     builds a wall from two clicks with ry = atan2(-(bz - az), bx - ax). */
  function wallSeg(w) {
    var L = N(w.p && w.p.len, 4), ry = N(w.ry, 0), c = Math.cos(ry), s = Math.sin(ry);
    return {rec: w, id: w.id, t: N(w.p && w.p.t, 0.24), h: N(w.p && w.p.h, 2.7),
            a: {x: w.x - L / 2 * c, z: w.z + L / 2 * s},
            b: {x: w.x + L / 2 * c, z: w.z - L / 2 * s},
            dir: {x: c, z: -s}, nrm: {x: s, z: c}};
  }

  function wallsOn(storey) {
    var out = [];
    objs().forEach(function (o) {
      if (!WALL_KINDS[o.kind] || o.hidden) return;
      if (storey !== undefined && storey !== null && storeyOf(o.y) !== storey) return;
      if (N(o.p && o.p.len, 0) <= 0) return;
      out.push(wallSeg(o));
    });
    return out;
  }

  /* ── the wall-loop room finder ───────────────────────────────────────── */
  function segInter(p, q) {                 /* proper intersection of two centre-lines */
    var r = {x: p.b.x - p.a.x, z: p.b.z - p.a.z}, s = {x: q.b.x - q.a.x, z: q.b.z - q.a.z};
    var den = r.x * s.z - r.z * s.x;
    if (Math.abs(den) < 1e-9) return null;
    var qp = {x: q.a.x - p.a.x, z: q.a.z - p.a.z};
    var t = (qp.x * s.z - qp.z * s.x) / den, u = (qp.x * r.z - qp.z * r.x) / den;
    if (t < -1e-6 || t > 1 + 1e-6 || u < -1e-6 || u > 1 + 1e-6) return null;
    return {x: p.a.x + t * r.x, z: p.a.z + t * r.z};
  }

  function loopRooms(storey) {
    var segs = wallsOn(storey);
    if (!segs.length || segs.length > MAX_WALLS) return [];
    var nodes = {}, order = [], i, j;
    function node(x, z) { var k = key(x, z); if (!nodes[k]) { nodes[k] = unkey(k); order.push(k); } return k; }
    for (i = 0; i < segs.length; i++) { node(segs[i].a.x, segs[i].a.z); node(segs[i].b.x, segs[i].b.z); }
    for (i = 0; i < segs.length; i++) for (j = i + 1; j < segs.length; j++) {
      var X = segInter(segs[i], segs[j]);
      if (X) node(X.x, X.z);
    }
    /* node every centre-line: split it at every graph node that lies on it */
    var adj = {};
    function link(ka, kb, wid) {
      if (ka === kb) return;
      var A = nodes[ka], B = nodes[kb];
      if (!adj[ka]) adj[ka] = [];
      if (!adj[kb]) adj[kb] = [];
      if (!adj[ka].some(function (e) { return e.to === kb; })) adj[ka].push({to: kb, ang: Math.atan2(B.z - A.z, B.x - A.x), wall: wid});
      if (!adj[kb].some(function (e) { return e.to === ka; })) adj[kb].push({to: ka, ang: Math.atan2(A.z - B.z, A.x - B.x), wall: wid});
    }
    for (i = 0; i < segs.length; i++) {
      var sg = segs[i], A = nodes[node(sg.a.x, sg.a.z)], B = nodes[node(sg.b.x, sg.b.z)];
      var L = dist(A, B);
      if (L < SNAP) continue;
      var on = [];
      for (var oi = 0; oi < order.length; oi++) {
        var P = nodes[order[oi]];
        if (distSeg(P.x, P.z, A, B) > SNAP) continue;
        var tt = ((P.x - A.x) * (B.x - A.x) + (P.z - A.z) * (B.z - A.z)) / (L * L);
        if (tt < -1e-6 || tt > 1 + 1e-6) continue;
        on.push({k: order[oi], t: tt});
      }
      on.sort(function (p, q) { return p.t - q.t; });
      for (j = 0; j + 1 < on.length; j++) link(on[j].k, on[j + 1].k, sg.id);
    }
    for (var k in adj) adj[k].sort(function (p, q) { return p.ang - q.ang; });

    /* every bounded face: at each node take the neighbour one step CLOCKWISE
       from the edge we arrived on. Interior faces come out with a POSITIVE
       shoelace, the outer boundary with a negative one. */
    var seen = {}, faces = [];
    for (var oi2 = 0; oi2 < order.length; oi2++) {
      var u0 = order[oi2], lst0 = adj[u0];
      if (!lst0) continue;
      for (var e = 0; e < lst0.length; e++) {
        if (seen[u0 + '>' + lst0[e].to]) continue;
        var cyc = [], cu = u0, cv = lst0[e].to, guard = 0;
        while (!seen[cu + '>' + cv] && guard++ < 8000) {
          seen[cu + '>' + cv] = 1;
          cyc.push(cu);
          var lst = adj[cv], ix = 0;
          for (var q2 = 0; q2 < lst.length; q2++) if (lst[q2].to === cu) { ix = q2; break; }
          var w = lst[(ix - 1 + lst.length) % lst.length].to;
          cu = cv; cv = w;
        }
        if (cyc.length >= 3) faces.push(cyc);
      }
    }
    var out = [];
    faces.forEach(function (cyc) {
      var poly = cyc.map(function (k2) { return nodes[k2]; });
      var ar = shoelace(poly);
      if (ar > MIN_AREA) out.push({poly: poly, area: ar});
    });
    return out;
  }

  /* ── zone records ────────────────────────────────────────────────────── */
  function zoneRooms(storey) {
    var out = [];
    objs().forEach(function (o) {
      if (o.kind !== 'zone' || o.hidden) return;
      if (storey !== undefined && storey !== null && storeyOf(o.y) !== storey) return;
      var pts = o.p && o.p.pts;
      if (!pts || pts.length < 3) return;
      var c = Math.cos(N(o.ry, 0)), s = Math.sin(N(o.ry, 0));
      var poly = pts.map(function (q) {
        var lx = N(q[0], 0), lz = N(q[1], 0);
        return {x: o.x + lx * c + lz * s, z: o.z - lx * s + lz * c};
      });
      if (shoelace(poly) < 0) poly.reverse();
      out.push({poly: poly, area: Math.abs(shoelace(poly)), rec: o});
    });
    return out;
  }

  /* ── name / use / compartment for a room ─────────────────────────────── */
  function tagComp(meta) {
    if (!meta) return null;
    if (meta.compartment) return String(meta.compartment);
    var tags = meta.tags;
    if (typeof tags === 'string') tags = tags.split(/[,\s]+/);
    if (Object.prototype.toString.call(tags) === '[object Array]') {
      for (var i = 0; i < tags.length; i++) {
        var t = String(tags[i]);
        if (/^comp:/i.test(t)) return t.slice(5);
      }
    }
    return null;
  }

  function markerIn(room, storey) {
    var hit = null;
    objs().forEach(function (o) {
      if (hit || o.hidden) return;
      if (WALL_KINDS[o.kind] || o.kind === 'zone') return;
      if (typeof arIsOpening === 'function' && arIsOpening(o.kind)) return;
      if (storey !== undefined && storey !== null && storeyOf(o.y) !== storey) return;
      var m = o.meta || {};
      if (!m.use && !m.room && !m.compartment && !m.tags) return;
      if (inPoly(o.x, o.z, room.poly)) hit = o;
    });
    return hit;
  }

  /* THE room finder — zone records if the drawing has them, else wall loops. */
  AP.rooms = function (storey) {
    var storeys = [];
    if (storey === undefined || storey === null) {
      var seen = {};
      objs().forEach(function (o) {
        if (o.hidden) return;
        if (!WALL_KINDS[o.kind] && o.kind !== 'zone') return;
        var s = storeyOf(o.y);
        if (!seen[s]) { seen[s] = 1; storeys.push(s); }
      });
      storeys.sort(function (a, b) { return a - b; });
    } else storeys = [storey];

    var out = [], n = 0, ext = AP.ext();
    storeys.forEach(function (st) {
      var zs = zoneRooms(st), found = zs.length ? zs : loopRooms(st);
      found.forEach(function (f) {
        var rec = f.rec || markerIn(f, st);
        var meta = (rec && rec.meta) || {};
        var pp = (f.rec && f.rec.p) || {};
        var nm = pp.name || meta.room || (f.rec ? f.rec.name : (rec ? rec.name : '')) || ('Room ' + (n + 1));
        var use = String(pp.use || meta.use || ext.default_use || 'office').toLowerCase();
        out.push({key: 'r' + (n++), name: String(nm), use: use, storey: st, y: st * storeyH(),
                  poly: f.poly, area: Math.abs(f.area), doors: [],
                  compartment: tagComp(meta), rec: rec || null,
                  source: zs.length ? 'zone' : 'wall loop'});
      });
    });
    /* every room now knows its doors (below fills them in) */
    AP.attachDoors(out);
    return out;
  };

  /* ── doors: host wall, the rooms either side, exit or not ────────────── */
  function hostWall(door) {
    var best = null, bestD = 1e9;
    wallsOn(storeyOf(door.y)).forEach(function (w) {
      var h = w.h;
      if (door.y < w.rec.y - 0.05 || door.y > w.rec.y + h - 0.05) return;
      var dx = door.x - w.rec.x, dz = door.z - w.rec.z, ry = N(w.rec.ry, 0);
      var c = Math.cos(ry), s = Math.sin(ry);
      var lx = dx * c - dz * s, lz = dx * s + dz * c;   /* into the wall's own frame */
      var L = N(w.rec.p && w.rec.p.len, 4);
      if (Math.abs(lx) > L / 2 + 0.001) return;
      var d = Math.abs(lz);
      if (d > w.t / 2 + 0.45) return;
      if (d < bestD) { bestD = d; best = w; }
    });
    return best;
  }

  function sidesOf(pt, wall, rooms) {
    var off = wall.t / 2 + SIDE, out = [];
    [1, -1].forEach(function (sgn) {
      var x = pt.x + sgn * off * wall.nrm.x, z = pt.z + sgn * off * wall.nrm.z, hit = null;
      for (var i = 0; i < rooms.length; i++) if (inPoly(x, z, rooms[i].poly)) { hit = rooms[i]; break; }
      out.push(hit);
    });
    return out;
  }

  function taggedExit(rec) {
    var m = rec.meta || {}, tags = m.tags;
    if (typeof tags === 'string') tags = tags.split(/[,\s]+/);
    if (Object.prototype.toString.call(tags) === '[object Array]') {
      for (var i = 0; i < tags.length; i++) if (/^exit$/i.test(String(tags[i]).trim())) return true;
    }
    return /exit|uitgang/i.test(String(rec.name || '')) || /exit|uitgang/i.test(String(m.role || ''));
  }

  AP.attachDoors = function (rooms) {
    var out = [];
    objs().forEach(function (o) {
      if (!isDoor(o) || o.hidden) return;
      var w = hostWall(o);
      if (!w) return;
      var st = storeyOf(o.y);
      var mine = rooms.filter(function (r) { return r.storey === st; });
      var sides = sidesOf({x: o.x, z: o.z}, w, mine);
      var rs = [];
      if (sides[0]) rs.push(sides[0]);
      if (sides[1] && sides[1] !== sides[0]) rs.push(sides[1]);
      var d = {id: o.id, rec: o, mid: {x: o.x, z: o.z}, wall: w, storey: st, rooms: rs,
               w: N(o.p && o.p.w, 0.9), clear: Math.max(0, N(o.p && o.p.w, 0.9) - 0.05),
               exterior: rs.length <= 1, exit: false};
      d.exit = d.exterior || taggedExit(o);
      rs.forEach(function (r) { r.doors.push(d); });
      out.push(d);
    });
    AP._doors = out;
    return out;
  };

  /* The doors of the room list actually in hand, deduplicated by record id.
     The analyses take an optional opt.rooms, which may come from an earlier
     AP.rooms() pass, so reading the AP._doors cache would mix door sets; the
     Python twin builds its list the same way, off the rooms it was given. */
  function doorsOf(rooms) {
    var seen = {}, out = [];
    (rooms || []).forEach(function (r) {
      (r.doors || []).forEach(function (d) {
        if (seen[d.id]) return;
        seen[d.id] = 1;
        out.push(d);
      });
    });
    return out;
  }

  AP.ext = function () {
    if (!window.AR) return {};
    AR.doc = AR.doc || {};
    AR.doc.ext = AR.doc.ext || {};
    AR.doc.ext.analyse_planning = AR.doc.ext.analyse_planning || {};
    return AR.doc.ext.analyse_planning;
  };

  AP.rates = function (over) {
    var r = {}, k;
    for (k in RATES) r[k] = RATES[k];
    var saved = AP.ext().rates;
    if (saved) for (k in saved) r[k] = N(saved[k], r[k]);
    if (over) for (k in over) r[String(k).toLowerCase()] = N(over[k], RATE_DEFAULT);
    return r;
  };

  /* ── the drawn route (temporary; dropped when the sheet closes) ───────── */
  AP.clearRoute = function () {
    if (AP._route && window.AR && AR.scene) {
      AR.scene.remove(AP._route);
      if (AP._route.geometry) AP._route.geometry.dispose();
      if (AP._route.material) AP._route.material.dispose();
    }
    AP._route = null;
  };

  AP.drawRoute = function (pts, y) {
    AP.clearRoute();
    if (!pts || pts.length < 2 || !window.THREE || !AR.scene) return;
    var v = [];
    pts.forEach(function (p) { v.push(p.x, y + 1.1, p.z); });
    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(v), 3));
    AP._route = new THREE.Line(g, new THREE.LineBasicMaterial({color: 0xff5a3c, transparent: true, opacity: 0.95, depthTest: false}));
    AP._route.renderOrder = 999;
    AP._route.name = 'analyse_planning:route';
    AR.scene.add(AP._route);
    if (typeof arRender === 'function') arRender();
  };

  /* ── a_egress ────────────────────────────────────────────────────────── */
  function farCorner(room, pt) {
    var best = room.poly[0], bd = -1;
    room.poly.forEach(function (v) { var d = dist(v, pt); if (d > bd) { bd = d; best = v; } });
    return {pt: best, d: bd};
  }

  AP.egress = function (opt) {
    var max = N(opt && opt.max, 30);
    var rooms = (opt && opt.rooms) || AP.rooms(opt && opt.storey);
    var doors = doorsOf(rooms);
    /* Dijkstra over the DOORS: a leg between two doors of one room is the
       straight line between their midpoints; every exit door starts at 0. */
    var D = {}, prev = {}, byId = {};
    doors.forEach(function (d) { byId[d.id] = d; D[d.id] = d.exit ? 0 : Infinity; });
    var todo = doors.slice();
    while (todo.length) {
      todo.sort(function (a, b) { return D[a.id] - D[b.id]; });
      var cur = todo.shift();
      if (!isFinite(D[cur.id])) break;
      cur.rooms.forEach(function (r) {
        r.doors.forEach(function (o) {
          if (o.id === cur.id) return;
          var nd = D[cur.id] + dist(cur.mid, o.mid);
          if (nd < D[o.id] - 1e-9) { D[o.id] = nd; prev[o.id] = cur.id; }
        });
      });
    }
    var rows = [], issues = [], worst = null;
    rooms.forEach(function (r) {
      var best = null;
      r.doors.forEach(function (d) {
        if (!isFinite(D[d.id])) return;
        var fc = farCorner(r, d.mid), tot = fc.d + D[d.id];
        if (!best || tot < best.total) best = {door: d, first: fc, total: tot};
      });
      r.travel = best ? best.total : null;
      r.route = best;
      if (!best) {
        issues.push({ids: r.rec ? [r.rec.id] : [], severity: 'fail',
                     text: r.name + ' (' + r.area.toFixed(1) + ' m²) has NO route to an exit — ' +
                           (r.doors.length ? 'its doors reach no exit door' : 'it has no door at all')});
        rows.push([r.name + ' <span style="opacity:.6">st' + r.storey + '</span>', 'no exit reachable']);
        return;
      }
      rows.push([r.name + ' <span style="opacity:.6">st' + r.storey + '</span>',
                 best.total.toFixed(2) + ' m via ' + best.door.id + (best.door.exit ? ' (an exit)' : '')]);
      if (!worst || best.total > worst.total) worst = {room: r, total: best.total, route: best, exit: best.door};
      if (best.total > max) {
        issues.push({ids: [best.door.id].concat(r.rec ? [r.rec.id] : []), severity: 'fail',
                     text: r.name + ': ' + best.total.toFixed(2) + ' m to an exit, over the ' + max + ' m limit'});
      }
    });
    /* the worst room's route, corner -> door -> door -> ... -> exit */
    var pts = null;
    if (worst) {
      pts = [worst.route.first.pt, worst.route.door.mid];
      var at = worst.route.door.id, guard = 0;
      while (prev[at] && guard++ < 200) { at = prev[at]; pts.push(byId[at].mid); }
    }
    return {ok: !issues.length, id: 'a_egress', label: 'Escape route', max: max,
            rooms: rooms.length, exits: doors.filter(function (d) { return d.exit; }).length,
            worst: worst ? {room: worst.room.name, m: worst.total} : null,
            route: pts, route_y: worst ? worst.room.y : 0, issues: issues, rows: rows,
            note: 'Door-to-door legs are straight lines across the connecting room and the first leg is ' +
                  'the room\'s farthest corner to its door — an honest approximation, not a routed walk.'};
  };

  /* ── a_access ────────────────────────────────────────────────────────── */
  AP.access = function (opt) {
    var turn = N(opt && opt.turn, 1.5), dw = N(opt && opt.door_w, 0.85);
    var rooms = (opt && opt.rooms) || AP.rooms(opt && opt.storey);
    var doors = doorsOf(rooms);
    var rows = [], issues = [];
    rooms.forEach(function (r) {
      var c = inCircle(r.poly), dia = 2 * c.r;
      r.turn = dia;
      rows.push([r.name + ' <span style="opacity:.6">st' + r.storey + '</span>',
                 'turning circle ' + dia.toFixed(2) + ' m' + (dia + 1e-9 < turn ? ' — too small' : '')]);
      if (dia + 1e-9 < turn) {
        /* same sentence as the Python twin's accessibility_check, so the two
           engines report one issue text and not two paraphrases of it. */
        issues.push({ids: r.rec ? [r.rec.id] : [], severity: 'fail',
                     text: r.name + ': ' + dia.toFixed(2) + ' m turning circle, under ' + turn + ' m'});
      }
    });
    doors.forEach(function (d) {
      rows.push([d.id + ' ' + (d.rec.name || 'Door'), 'clear width ' + d.clear.toFixed(2) + ' m' + (d.clear <= dw ? ' — too narrow' : '')]);
      if (d.clear <= dw) {
        issues.push({ids: [d.id], severity: 'fail',
                     text: d.id + ': ' + d.clear.toFixed(2) + ' m clear (' + d.w.toFixed(2) +
                           ' m leaf less a 0.05 m frame) is not over the ' + dw + ' m minimum'});
      }
    });
    /* level changes between rooms that share a door, with no ramp near it */
    var ramps = objs().filter(function (o) { return /ramp/.test(o.kind) && !o.hidden; });
    doors.forEach(function (d) {
      if (d.rooms.length < 2) return;
      var dy = Math.abs(d.rooms[0].y - d.rooms[1].y);
      if (dy <= 0.02) return;
      var near = ramps.some(function (o) { return dist({x: o.x, z: o.z}, d.mid) <= 3.0; });
      if (near) return;
      issues.push({ids: [d.id], severity: 'fail',
                   text: d.rooms[0].name + ' and ' + d.rooms[1].name + ' differ by ' + dy.toFixed(3) +
                         ' m at ' + d.id + ' with no ramp record within 3 m'});
      rows.push([d.id + ' level change', dy.toFixed(3) + ' m, no ramp']);
    });
    return {ok: !issues.length, id: 'a_access', label: 'Accessibility', turn: turn, door_w: dw,
            rooms: rooms.length, doors: doors.length, issues: issues, rows: rows,
            note: 'The turning circle is the largest circle inside the room polygon clear of every wall ' +
                  '(0.1 m grid, then four halving refinements); a door\'s clear width is its leaf less a 0.05 m frame.'};
  };

  /* ── a_occupancy ─────────────────────────────────────────────────────── */
  AP.occupancy = function (opt) {
    var rates = AP.rates(opt && opt.rates);
    var rooms = (opt && opt.rooms) || AP.rooms(opt && opt.storey);
    var rows = [], issues = [], perStorey = {}, total = 0;
    rooms.forEach(function (r) {
      var rate = rates[r.use] !== undefined ? rates[r.use] : RATE_DEFAULT;
      var persons = rate > 0 ? Math.ceil(r.area / rate) : 0;
      r.persons = persons; r.rate = rate;
      total += persons;
      perStorey[r.storey] = (perStorey[r.storey] || 0) + persons;
      var mm = /corridor|circulation/.test(r.use) ? 0.006 : 0.010;
      var need = persons * mm;
      var clear = 0;
      r.doors.forEach(function (d) { clear += d.clear; });
      r.exit_width = clear; r.exit_width_needed = need;
      rows.push([r.name + ' <span style="opacity:.6">st' + r.storey + ' · ' + r.use + '</span>',
                 r.area.toFixed(1) + ' m² ÷ ' + (rate > 0 ? rate + ' m²/p = <b>' + persons + '</b> persons' : 'n/a (circulation)') +
                 (persons ? ' · doors ' + clear.toFixed(2) + ' m clear, needs ' + need.toFixed(3) + ' m' : '')]);
      if (persons > 0 && clear < need - 1e-9) {
        issues.push({ids: r.doors.map(function (d) { return d.id; }).concat(r.rec ? [r.rec.id] : []), severity: 'fail',
                     text: r.name + ': ' + persons + ' persons need ' + need.toFixed(3) + ' m of clear door width, has ' + clear.toFixed(2) + ' m'});
      }
    });
    var st = Object.keys(perStorey).sort(function (a, b) { return a - b; });
    st.forEach(function (s) { rows.push(['<b>storey ' + s + '</b>', '<b>' + perStorey[s] + ' persons</b>']); });
    rows.push(['<b>building</b>', '<b>' + total + ' persons</b>']);
    return {ok: !issues.length, id: 'a_occupancy', label: 'Occupancy', total: total,
            per_storey: perStorey, rates: rates, rooms: rooms.length, issues: issues, rows: rows,
            note: 'Persons = ceil(area / m² per person); a rate of 0 is circulation and counts nobody. ' +
                  'ASSUMED exit width 10 mm per person overall, 6 mm per person for corridors — edit the ' +
                  'rates below and they are kept with the drawing.'};
  };

  /* ── a_fire ──────────────────────────────────────────────────────────── */
  AP.fire = function (opt) {
    var maxArea = N(opt && opt.max_area, 1000), maxLen = N(opt && opt.max_len, 60);
    var rooms = (opt && opt.rooms) || AP.rooms(opt && opt.storey);
    var eg = AP.egress({max: maxLen, rooms: rooms});          /* the shared registry's own arithmetic */
    var doors = doorsOf(rooms);
    var comps = {}, order = [];
    rooms.forEach(function (r) {
      var c = r.compartment || ('storey ' + r.storey);
      r.comp = c;
      if (!comps[c]) { comps[c] = {id: c, area: 0, rooms: [], travel: 0}; order.push(c); }
      comps[c].area += r.area;
      comps[c].rooms.push(r);
      if (r.travel && r.travel > comps[c].travel) comps[c].travel = r.travel;
    });
    var rows = [], issues = [];
    order.forEach(function (c) {
      var C = comps[c];
      rows.push(['compartment <b>' + c + '</b>',
                 C.rooms.length + ' rooms, ' + C.area.toFixed(1) + ' m² (max ' + maxArea + '), longest travel ' +
                 (C.travel ? C.travel.toFixed(2) + ' m' : 'n/a') + ' (max ' + maxLen + ')']);
      if (C.area > maxArea) {
        issues.push({ids: C.rooms.map(function (r) { return r.rec ? r.rec.id : ''; }).filter(Boolean), severity: 'fail',
                     text: 'compartment ' + c + ' is ' + C.area.toFixed(1) + ' m², over the ' + maxArea + ' m² limit'});
      }
      if (C.travel > maxLen) {
        issues.push({ids: [], severity: 'fail',
                     text: 'compartment ' + c + ': longest travel ' + C.travel.toFixed(2) + ' m, over the ' + maxLen + ' m limit'});
      }
    });
    /* walls that carry a compartment line */
    var compWalls = [], byStorey = {};
    rooms.forEach(function (r) { (byStorey[r.storey] = byStorey[r.storey] || []).push(r); });
    Object.keys(byStorey).forEach(function (s) {
      wallsOn(parseInt(s, 10)).forEach(function (w) {
        var mid = {x: (w.a.x + w.b.x) / 2, z: (w.a.z + w.b.z) / 2};
        var sides = sidesOf(mid, w, byStorey[s]);
        if (!sides[0] || !sides[1]) return;
        if (sides[0].comp === sides[1].comp) return;
        var thin = w.t < 0.1, glass = w.rec.mat === 'mat_glass';
        compWalls.push({id: w.id, comps: [sides[0].comp, sides[1].comp], t: w.t, mat: w.rec.mat, weak: thin || glass});
        rows.push(['wall ' + w.id, 'compartment line ' + sides[0].comp + ' | ' + sides[1].comp +
                   ', ' + (w.t * 1000).toFixed(0) + ' mm ' + w.rec.mat.replace('mat_', '') + (thin || glass ? ' — too light' : '')]);
        if (thin || glass) {
          issues.push({ids: [w.id], severity: 'fail',
                       text: 'wall ' + w.id + ' carries the ' + sides[0].comp + '|' + sides[1].comp + ' compartment line but is ' +
                             (glass ? 'glass' : (w.t * 1000).toFixed(0) + ' mm thick') + ' — a compartment wall wants mass (ASSUMED: ≥ 100 mm and not glazed)'});
        }
      });
    });
    var fireDoors = [];
    doors.forEach(function (d) {
      if (d.rooms.length < 2) return;
      if (d.rooms[0].comp === d.rooms[1].comp) return;
      fireDoors.push(d.id);
      rows.push(['door ' + d.id, 'between ' + d.rooms[0].comp + ' and ' + d.rooms[1].comp + ' — FIRE DOOR NEEDED']);
      issues.push({ids: [d.id], severity: 'warn',
                   text: 'door ' + d.id + ' joins compartments ' + d.rooms[0].comp + ' and ' + d.rooms[1].comp + ' — a fire door is needed'});
    });
    return {ok: !issues.filter(function (i) { return i.severity === 'fail'; }).length,
            id: 'a_fire', label: 'Compartments', max_area: maxArea, max_len: maxLen,
            compartments: order.map(function (c) { return {id: c, area: comps[c].area, rooms: comps[c].rooms.length, travel: comps[c].travel}; }),
            compartment_walls: compWalls, fire_doors: fireDoors, rooms: rooms.length,
            issues: issues, rows: rows,
            note: 'Rooms are grouped by meta.compartment (or a "comp:X" tag), else one compartment per storey. ' +
                  'ASSUMED a compartment wall is at least 100 mm thick and not glazed. Travel distances come ' +
                  'from Escape route through the shared analyses registry.'};
  };

  /* ── sheets ──────────────────────────────────────────────────────────── */
  function issueHtml(issues) {
    if (!issues.length) return '<p style="color:#7fd67f;margin:6px 0">No issues found.</p>';
    return '<table class="ar-tbl">' + issues.map(function (i) {
      var col = i.severity === 'fail' ? '#ff8b6b' : '#ffc86b';
      return '<tr><td style="color:' + col + ';white-space:nowrap">' + esc(i.severity) +
             (i.ids && i.ids.length ? ' <span style="opacity:.6">' + esc(i.ids.join(' ')) + '</span>' : '') +
             '</td><td>' + esc(i.text) + '</td></tr>';
    }).join('') + '</table>';
  }

  function head(res, extra) {
    return '<p style="margin:2px 0 8px"><b>' + esc(res.label) + '</b> — ' + res.rooms + ' room' +
           (res.rooms === 1 ? '' : 's') + (extra ? ', ' + extra : '') + '. ' +
           '<span style="opacity:.65">' + esc(res.note) + '</span></p>';
  }

  function show(title, res, extra) {
    if (!res.rooms) {
      arSheet(title, '<p>No rooms found. Rooms come from <b>zone</b> records (p.pts), or from closed loops of ' +
                     'wall and partition centre-lines — draw a closed room first.</p>');
      return res;
    }
    arSheet(title, head(res, extra) + issueHtml(res.issues) + arRows(res.rows));
    var bad = res.issues.filter(function (i) { return i.severity === 'fail'; }).length;
    arToast('<b>' + esc(res.label) + '</b>: ' + res.rooms + ' rooms, ' +
            (bad ? bad + ' issue' + (bad === 1 ? '' : 's') : 'no issues') + '.', bad ? 'warn' : '');
    return res;
  }

  function ask(opt, k, q, d) {
    if (opt && typeof opt === 'object') return N(opt[k], d);
    return N(prompt(q, String(d)), d);
  }

  /* the rates table, editable, kept in AR.doc.ext.analyse_planning.rates */
  AP.setRate = function (use, v) {
    var e = AP.ext();
    e.rates = e.rates || {};
    e.rates[String(use).toLowerCase()] = N(v, RATE_DEFAULT);
    if (typeof arDirty === 'function') arDirty(true);
    AP.runOccupancy({});
  };

  function ratesHtml(rates) {
    var ks = Object.keys(rates).sort();
    return '<p style="margin:10px 0 4px"><b>m² per person</b> (edit — kept with the drawing in ' +
           '<code>doc.ext.analyse_planning.rates</code>; 0 = circulation, nobody counted)</p>' +
           '<table class="ar-tbl">' + ks.map(function (k) {
             return '<tr><td>' + esc(k) + '</td><td><input type="number" step="0.5" min="0" value="' + rates[k] +
                    '" style="width:6em" onchange="analyse_planning.setRate(\'' + esc(k) + '\', this.value)"></td></tr>';
           }).join('') + '</table>';
  }

  /* ── the four runs, shared by the icons, the registry and a_code ──────── */
  AP.runEgress = function (opt) {
    var res = AP.egress({max: ask(opt, 'max', 'Maximum travel distance to an exit (m)?', 30), storey: opt && opt.storey});
    show('Escape route', res, res.exits + ' exit door' + (res.exits === 1 ? '' : 's') +
         (res.worst ? ', worst ' + res.worst.room + ' at ' + res.worst.m.toFixed(2) + ' m' : ''));
    if (res.route) AP.drawRoute(res.route, res.route_y);
    return res;
  };
  AP.runAccess = function (opt) {
    var res = AP.access({turn: ask(opt, 'turn', 'Turning circle diameter (m)?', 1.5),
                         door_w: ask(opt, 'door_w', 'Minimum clear door width (m)?', 0.85),
                         storey: opt && opt.storey});
    return show('Accessibility', res, res.doors + ' door' + (res.doors === 1 ? '' : 's'));
  };
  AP.runOccupancy = function (opt) {
    var res = AP.occupancy({rates: opt && typeof opt === 'object' ? opt.rates : null, storey: opt && opt.storey});
    if (!res.rooms) return show('Occupancy', res);
    arSheet('Occupancy', head(res, res.total + ' persons in total') + issueHtml(res.issues) +
            arRows(res.rows) + ratesHtml(res.rates));
    arToast('<b>Occupancy</b>: ' + res.total + ' persons over ' + res.rooms + ' rooms.');
    return res;
  };
  AP.runFire = function (opt) {
    var res = AP.fire({max_area: ask(opt, 'max_area', 'Largest compartment floor area (m²)?', 1000),
                       max_len: ask(opt, 'max_len', 'Longest travel distance in a compartment (m)?', 60),
                       storey: opt && opt.storey});
    return show('Compartments', res, res.compartments.length + ' compartment' +
                (res.compartments.length === 1 ? '' : 's') + ', ' + res.fire_doors.length + ' fire door(s) needed');
  };

  /* ── registrations ───────────────────────────────────────────────────── */
  AR_EXT.tools.a_egress = {
    assist: 1, tip: 'Travel distance to an exit — the number a floor plan lives or dies by',
    act: function (opt) { AP.runEgress(opt); }
  };
  AR_EXT.tools.a_access = {
    assist: 1, tip: 'Wheelchair clearances — a 1.5 m turning circle and the door widths around it',
    act: function (opt) { AP.runAccess(opt); }
  };
  AR_EXT.tools.a_occupancy = {
    assist: 1, tip: 'Occupancy load — people per area by function, which is what sets the exit widths',
    act: function (opt) { AP.runOccupancy(opt); }
  };
  AR_EXT.tools.a_fire = {
    assist: 1, tip: 'Fire compartments — which walls are rated, and where a compartment line is broken',
    act: function (opt) { AP.runFire(opt); }
  };

  /* the shared registry a_code (Compliance report) reads: run() never opens a
     sheet and never draws, so a whole pass costs one call each. */
  AR_EXT.analyses.push({id: 'a_egress', label: 'Escape route', run: function (o) { return AP.egress(o || {}); }});
  AR_EXT.analyses.push({id: 'a_access', label: 'Accessibility', run: function (o) { return AP.access(o || {}); }});
  AR_EXT.analyses.push({id: 'a_occupancy', label: 'Occupancy', run: function (o) { return AP.occupancy(o || {}); }});
  AR_EXT.analyses.push({id: 'a_fire', label: 'Compartments', run: function (o) { return AP.fire(o || {}); }});

  AR_EXT.ready.push(function () {
    var base = arSheetClose;                 /* the drawn route belongs to the sheet */
    arSheetClose = function () { AP.clearRoute(); base(); };
  });
})();
