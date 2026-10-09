// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* analyse_geometry — Analyse ▸ Clash (a_clash), Headroom (a_headroom),
   Guarding (a_guard) and Stair rule (a_stair).

   FOUR CHECKS, TWO FACES. Each one is an ACTION icon that opens a sheet of
   findings, and each one is ALSO pushed onto AR_EXT.analyses — the shared
   registry another family ('Code check', a_code) walks to run every rule in one
   pass:

       AR_EXT.analyses.push({id, label, run(opt) -> {ok, issues, rows}})
       issue = {ids: [recordId...], text: 'what is wrong', severity: 'error'|'warn'}
       rows  = [[key, value], ...]           the numbers behind the verdict

   `run()` NEVER touches the document: no arPush, no records added. The sheet it
   opens carries a `select` button per issue (arSelect on the issue's ids) and a
   red wire box around every offending record, which is removed when the sheet
   closes.

   ONE ARITHMETIC, TWO LANGUAGES. Everything below is computed from the
   RECORDS' PARAMETERS, never from the built meshes, so the identical rule can
   live in arch_assistant_ext/analyse_geometry.py and give the assistant the
   same numbers. dims(), corners(), satDepth(), clipArea() and the four rule
   functions are transliterations of each other; tests_arch_ext/
   test_analyse_geometry.py runs both on one fixture and compares the counts.

   A record's plan shape is the RECTANGLE its size parameters imply, rotated by
   ry — exact for every box-shaped kind (walls, slabs, beams, columns, stairs)
   and an honest outer bound for the round and sculpted ones. Its vertical
   extent is rec.y .. rec.y + h, because every kind in arGeom() builds from
   y = 0 upward: a slab's base is rec.y and its top rec.y + t, a beam's
   underside is rec.y, a stair's flight climbs steps*rise from rec.y.

   Licence: no third-party code; three.js r144 (MIT) is used only for the
   Box3Helper that draws the highlight boxes. */
(function () {
  'use strict';

  /* ── the constants every rule is measured against ───────────────────────── */
  var C = {
    CLASH_EPS: 0.02,      /* a pair must interpenetrate by more than 2 cm on all three axes */
    SLAB_BEAR: 0.05,      /* a wall may share this much y with the slab it stands on, on top of the slab's own thickness */
    CORNER_PAD: 0.05,     /* how close two wall ends must be to read as one corner joint */
    HEAD_MIN: 2.3,        /* Bouwbesluit new-build clear height (NL); 2.0 m is the absolute floor */
    HEAD_ABS: 2.0,
    HEAD_BEARS: 0.05,     /* under this the "soffit" is a floor bearing on its own storey plane, not a ceiling */
    GUARD_H: 1.0,         /* guard height above the walking surface */
    GUARD_GAP: 0.10,      /* the 100 mm sphere rule */
    GUARD_DROP: 1.0,      /* a fall of more than a metre must be guarded */
    EDGE_TOL: 0.15,       /* how far from the edge a guard may stand */
    EDGE_COVER: 0.80,     /* the fraction of the edge it must cover */
    GUARD_BAND: 0.35,     /* the guard's base must sit within this of the walking surface */
    BLONDEL_LO: 0.60,     /* 2*rise + run */
    BLONDEL_HI: 0.65,
    RISE_MAX: 0.185,      /* comfort rise (NL absolute maximum is 0.22) */
    RUN_MIN: 0.22,
    WIDTH_MIN: 0.80,
    STOREY: 2.7,
    STOREY_TOL: 0.02,
    MAX_ISSUES: 300
  };

  function num(v, d) { var f = parseFloat(v); return isFinite(f) ? f : d; }
  /* r2/r3 return STRINGS and keep their trailing zeros, because the Python twin
     formats with '%.2f' / '%.3f' and the two faces must read identically: a
     headroom of exactly 2 m is "2.00 m" on both sides, never "2 m" here. Every
     call site is inside a sentence; comparisons always use the raw number. */
  function r2(v) { return (Math.round(v * 100) / 100).toFixed(2); }
  function r3(v) { return (Math.round(v * 1000) / 1000).toFixed(3); }

  /* ── what a record occupies, from its parameters alone ──────────────────── */
  /* {w, d, h, cu, cv}: w along local +X, d along local +Z, h upward from rec.y,
     (cu, cv) the plan offset of the rectangle's centre in the local frame. */
  var DIMS = {
    wall: function (p) { return [num(p.len, 4), num(p.t, 0.24), num(p.h, 2.7)]; },
    partition: function (p) { return [num(p.len, 4), num(p.t, 0.10), num(p.h, 2.7)]; },
    slab: function (p) { return [num(p.w, 6), num(p.d, 4), num(p.t, 0.22)]; },
    roof_flat: function (p) { return [num(p.w, 8), num(p.d, 6), num(p.t, 0.3)]; },
    beam: function (p) { return [num(p.len, 5), num(p.w, 0.2), num(p.h, 0.4)]; },
    column_rect: function (p) { return [num(p.w, 0.3), num(p.d, 0.3), num(p.h, 3)]; },
    column_round: function (p) { var r = num(p.r, 0.18); return [2 * r, 2 * r, num(p.h, 3)]; },
    footing: function (p) { return [num(p.w, 1), num(p.d, 1), num(p.t, 0.35)]; },
    railing: function (p) { return [num(p.len, 3), num(p.t, 0.04), num(p.h, 1.0)]; },
    ladder: function (p) { return [num(p.w, 0.5), num(p.t, 0.04), num(p.h, 3)]; },
    ramp: function (p) { return [num(p.len, 6), num(p.w, 1.5), num(p.rise, 0.5) + num(p.t, 0.15)]; },
    box: function (p) { return [num(p.w, 1), num(p.d, 1), num(p.h, 1)]; },
    balcony: function (p) { return [num(p.w, 2.4), num(p.d, 1.2), num(p.t, 0.18) + num(p.rail_h, 1.0)]; },
    parapet_cap: function (p) { return [num(p.len, 4), num(p.w, 0.36), num(p.t, 0.08)]; },
    stair_straight: function (p) {
      var n = Math.max(1, Math.round(num(p.steps, 16)));
      return [n * num(p.run, 0.28), num(p.w, 1.0), n * num(p.rise, 0.175)];
    },
    stair_u: function (p) {
      var n = Math.max(2, Math.round(num(p.steps, 16))), w = num(p.w, 1.0), gap = num(p.gap, 0.2);
      return [Math.floor(n / 2) * num(p.run, 0.28) + w, 2 * w + gap, n * num(p.rise, 0.175)];
    },
    stair_winder: function (p) {
      var n = Math.max(3, Math.round(num(p.steps, 16))), run = num(p.run, 0.28), w = num(p.w, 1.0);
      return [n * run, Math.max(w, n * run / 2), n * num(p.rise, 0.175)];
    },
    stair_landing: function (p) { return [num(p.w, 1.2), num(p.d, 1.2), num(p.t, 0.2)]; },
    fire_stair_exterior: function (p) {
      var n = Math.max(1, Math.round(num(p.steps, 16)));
      return [n * num(p.run, 0.26), num(p.w, 1.0), n * num(p.rise, 0.19)];
    }
  };

  function dims(o) {
    var p = o.p || {}, f = DIMS[o.kind], w, d, h, cu = 0, cv = 0, i, xs, zs;
    if (f) { var t = f(p); return { w: Math.abs(t[0]), d: Math.abs(t[1]), h: Math.abs(t[2]), cu: 0, cv: 0 }; }
    if (p.pts && p.pts.length >= 3) {                       /* slab_poly and friends: the bbox of the point list */
      xs = []; zs = [];
      for (i = 0; i < p.pts.length; i++) { xs.push(num(p.pts[i][0], 0)); zs.push(num(p.pts[i][1], 0)); }
      w = Math.max.apply(null, xs) - Math.min.apply(null, xs);
      d = Math.max.apply(null, zs) - Math.min.apply(null, zs);
      cu = (Math.max.apply(null, xs) + Math.min.apply(null, xs)) / 2;
      cv = (Math.max.apply(null, zs) + Math.min.apply(null, zs)) / 2;
    } else if (p.len !== undefined) {
      w = Math.abs(num(p.len, 0)); d = Math.abs(num(p.w, num(p.t, 0.2)));
    } else if (p.span !== undefined) {
      w = Math.abs(num(p.span, 0)); d = Math.abs(num(p.w, 0.2));
    } else if (p.w !== undefined && p.d !== undefined) {
      w = Math.abs(num(p.w, 0)); d = Math.abs(num(p.d, 0));
    } else if (p.rx !== undefined && p.rz !== undefined) {
      w = 2 * Math.abs(num(p.rx, 0)); d = 2 * Math.abs(num(p.rz, 0));
    } else if (p.r_out !== undefined) {
      w = d = 2 * Math.abs(num(p.r_out, 0));
    } else if (p.r !== undefined) {
      w = d = 2 * Math.abs(num(p.r, 0));
    } else if (p.w !== undefined) {
      w = d = Math.abs(num(p.w, 0));
    } else { w = d = 0; }
    h = num(p.h, num(p.t, 0));
    if (p.steps !== undefined && p.rise !== undefined) h = Math.max(1, Math.round(num(p.steps, 1))) * num(p.rise, 0.175);
    if (!(w > 0)) w = 0.5;
    if (!(d > 0)) d = 0.5;
    if (!(h > 0)) h = 0.5;
    return { w: w, d: d, h: Math.abs(h), cu: cu, cv: cv };
  }

  /* the four world corners of a local rectangle. rotation.y = ry maps local +X
     to (cos ry, -sin ry) and local +Z to (sin ry, cos ry) on the plan, so
     dx = u*cos + v*sin and dz = -u*sin + v*cos. The order stays CCW. */
  function rectOf(x, z, ry, cu, cv, w, d) {
    var c = Math.cos(ry || 0), s = Math.sin(ry || 0), hw = w / 2, hd = d / 2;
    var loc = [[cu - hw, cv - hd], [cu + hw, cv - hd], [cu + hw, cv + hd], [cu - hw, cv + hd]];
    var out = [], i, u, v;
    for (i = 0; i < 4; i++) {
      u = loc[i][0]; v = loc[i][1];
      out.push([x + u * c + v * s, z - u * s + v * c]);
    }
    return out;
  }
  function corners(o) { var m = dims(o); return rectOf(o.x || 0, o.z || 0, o.ry || 0, m.cu, m.cv, m.w, m.d); }
  function aabb(pts) {
    var i, x0 = pts[0][0], x1 = x0, z0 = pts[0][1], z1 = z0;
    for (i = 1; i < pts.length; i++) {
      if (pts[i][0] < x0) x0 = pts[i][0]; if (pts[i][0] > x1) x1 = pts[i][0];
      if (pts[i][1] < z0) z0 = pts[i][1]; if (pts[i][1] > z1) z1 = pts[i][1];
    }
    return [x0, z0, x1, z1];
  }

  /* separating-axis test on two convex quads: the smallest penetration depth in
     metres, or -1 when an axis separates them. Exact for rectangles. */
  function satDepth(A, B) {
    var best = Infinity, polys = [A, B], pi, i, j, t, P, ax, az, nx, nz, L, a0, a1, b0, b1, ov;
    for (pi = 0; pi < 2; pi++) {
      P = polys[pi];
      for (i = 0; i < 4; i++) {
        ax = P[(i + 1) % 4][0] - P[i][0]; az = P[(i + 1) % 4][1] - P[i][1];
        nx = -az; nz = ax; L = Math.sqrt(nx * nx + nz * nz);
        if (L < 1e-9) continue;
        nx /= L; nz /= L;
        a0 = Infinity; a1 = -Infinity; b0 = Infinity; b1 = -Infinity;
        for (j = 0; j < 4; j++) { t = A[j][0] * nx + A[j][1] * nz; if (t < a0) a0 = t; if (t > a1) a1 = t; }
        for (j = 0; j < 4; j++) { t = B[j][0] * nx + B[j][1] * nz; if (t < b0) b0 = t; if (t > b1) b1 = t; }
        ov = Math.min(a1, b1) - Math.max(a0, b0);
        if (ov <= 0) return -1;
        if (ov < best) best = ov;
      }
    }
    return best === Infinity ? -1 : best;
  }
  function overlaps(A, B) { return satDepth(A, B) > 0; }

  /* area of A ∩ B (Sutherland–Hodgman clip of A by B's four half-planes). */
  function clipArea(A, B) {
    var out = A.slice(), i, j, p, q, ex, ez, inp, cur, prv, dc, dp;
    function cut(a, b, p0, p1) {
      var r1 = b[0] - a[0], r2 = b[1] - a[1], s1 = p1[0] - p0[0], s2 = p1[1] - p0[1];
      var den = r1 * s2 - r2 * s1;
      if (Math.abs(den) < 1e-12) return a.slice();
      var t = ((p0[0] - a[0]) * s2 - (p0[1] - a[1]) * s1) / den;
      return [a[0] + r1 * t, a[1] + r2 * t];
    }
    for (i = 0; i < 4 && out.length; i++) {
      p = B[i]; q = B[(i + 1) % 4];
      ex = q[0] - p[0]; ez = q[1] - p[1];
      inp = [];
      for (j = 0; j < out.length; j++) {
        cur = out[j]; prv = out[(j + out.length - 1) % out.length];
        dc = ex * (cur[1] - p[1]) - ez * (cur[0] - p[0]);
        dp = ex * (prv[1] - p[1]) - ez * (prv[0] - p[0]);
        if (dc >= 0) { if (dp < 0) inp.push(cut(prv, cur, p, q)); inp.push(cur); }
        else if (dp >= 0) { inp.push(cut(prv, cur, p, q)); }
      }
      out = inp;
    }
    if (out.length < 3) return 0;
    var s = 0;
    for (i = 0; i < out.length; i++) {
      var n = out[(i + 1) % out.length];
      s += out[i][0] * n[1] - n[0] * out[i][1];
    }
    return Math.abs(s) / 2;
  }

  /* ── which records are solids the rules care about ──────────────────────── */
  var NON_SOLID = {
    opening: 1, annotation: 1, dimension: 1, guide_line: 1, guide_circle: 1,
    plane: 1, disc: 1, ground: 1, water: 1, person: 1
  };
  function isVoid(kind) {
    if (NON_SOLID[kind]) return true;
    if (kind.indexOf('sculpt_') === 0 || kind.indexOf('zone') === 0 || kind.indexOf('guide') === 0) return true;
    return typeof arIsOpening === 'function' ? arIsOpening(kind) : false;
  }
  function solids() {
    return AR.objs.filter(function (o) { return !o.hidden && !isVoid(o.kind); });
  }
  var SLABISH = { slab: 1, slab_poly: 1, roof_flat: 1 };
  var SOFFIT = { slab: 1, slab_poly: 1, roof_flat: 1, beam: 1 };
  var DECK = { slab: 1, slab_poly: 1, roof_flat: 1, balcony: 1 };
  function isWall(k) { return k === 'wall' || k === 'partition'; }
  function isStair(o) {
    var p = o.p || {};
    if (p.rise === undefined || p.run === undefined || p.steps === undefined) return false;
    var lb = (typeof arKindLabel === 'function' ? arKindLabel(o.kind) : o.kind) + ' ' + o.kind;
    return /stair/i.test(lb);
  }
  function isGuardKind(o) {
    if (isWall(o.kind) || o.kind === 'balcony') return true;
    var lb = (typeof arKindLabel === 'function' ? arKindLabel(o.kind) : o.kind) + ' ' + o.kind;
    return /rail|balustrade|parapet/i.test(lb);
  }
  function label(o) { return (typeof arKindLabel === 'function' ? arKindLabel(o.kind) : o.kind) + ' ' + o.id; }
  function deckTop(o) {
    var p = o.p || {};
    return (o.y || 0) + (o.kind === 'balcony' ? num(p.t, 0.18) : dims(o).h);
  }

  /* ── 1. clash ───────────────────────────────────────────────────────────── */
  /* Sort-and-sweep on x for the broad phase, then an OBB test (SAT on the two
     plan rectangles plus the y interval) for every surviving pair. Pairs that
     are MEANT to touch are excused: an opening and its host wall (openings are
     not solids at all), two walls that share an end and only overlap by a wall
     thickness, and a slab with anything bearing on it whose shared height is no
     more than the slab's own thickness plus 5 cm. */
  function wallEnds(o) {
    var m = dims(o), c = Math.cos(o.ry || 0), s = Math.sin(o.ry || 0), h = m.w / 2;
    return [[(o.x || 0) - h * c, (o.z || 0) + h * s], [(o.x || 0) + h * c, (o.z || 0) - h * s]];
  }
  function excused(A, B, yov, depth) {
    var a = A.o, b = B.o, i, j, dx, dz;
    if (isWall(a.kind) && isWall(b.kind)) {
      var ea = wallEnds(a), eb = wallEnds(b);
      var ta = dims(a).d, tb = dims(b).d, near = 0.5 * (ta + tb) + C.CORNER_PAD;
      for (i = 0; i < 2; i++) for (j = 0; j < 2; j++) {
        dx = ea[i][0] - eb[j][0]; dz = ea[i][1] - eb[j][1];
        if (Math.sqrt(dx * dx + dz * dz) <= near && depth <= Math.max(ta, tb) + 1e-9) return 'corner joint';
      }
    }
    if (SLABISH[a.kind] !== SLABISH[b.kind]) {              /* exactly one of them is a slab */
      var s = SLABISH[a.kind] ? a : b;
      if (yov <= dims(s).h + C.SLAB_BEAR + 1e-9) return 'bears on the slab';
    }
    return '';
  }

  function runClash(opt) {
    var which = (opt && opt.which) || 'all';
    var recs = solids();
    if (which === 'selection' || which === 'selected') {
      var sel = {}; (AR.sel || []).forEach(function (id) { sel[id] = 1; });
      recs = recs.filter(function (o) { return sel[o.id]; });
    }
    var items = recs.map(function (o) {
      var c = corners(o), bb = aabb(c), m = dims(o);
      return { o: o, c: c, x0: bb[0], z0: bb[1], x1: bb[2], z1: bb[3], y0: o.y || 0, y1: (o.y || 0) + m.h };
    });
    items.sort(function (a, b) { return a.x0 - b.x0; });
    var issues = [], rows = [], act = [], tested = 0, excusedN = 0, i, k, A, B, yov, dep, ex, area;
    for (i = 0; i < items.length; i++) {
      A = items[i];
      act = act.filter(function (E) { return E.x1 > A.x0 + C.CLASH_EPS; });
      for (k = 0; k < act.length; k++) {
        B = act[k];
        if (Math.min(A.z1, B.z1) - Math.max(A.z0, B.z0) <= C.CLASH_EPS) continue;
        yov = Math.min(A.y1, B.y1) - Math.max(A.y0, B.y0);
        if (yov <= C.CLASH_EPS) continue;
        tested++;
        dep = satDepth(A.c, B.c);
        if (dep <= C.CLASH_EPS) continue;
        ex = excused(A, B, yov, dep);
        if (ex) { excusedN++; continue; }
        area = clipArea(A.c, B.c);
        if (issues.length < C.MAX_ISSUES) {
          issues.push({
            ids: [A.o.id, B.o.id], severity: 'error',
            text: label(A.o) + ' &harr; ' + label(B.o) + ' — about ' + r3(area * yov) + ' m&sup3; shared ('
              + r2(dep) + ' m into each other on the plan, ' + r2(yov) + ' m of common height)'
          });
        }
      }
      act.push(A);
    }
    rows.push(['solids tested', items.length]);
    rows.push(['pairs that share a bounding box', tested]);
    rows.push(['pairs excused (corner joints, bearing on a slab)', excusedN]);
    rows.push(['clashes', issues.length ? '<b>' + issues.length + '</b>' : '0']);
    rows.push(['tolerance', C.CLASH_EPS + ' m on every axis; openings and their host walls are never a clash']);
    return { ok: !issues.length, issues: issues, rows: rows };
  }

  /* ── 2. headroom ────────────────────────────────────────────────────────── */
  /* The clear height under every slab, flat roof and beam, and over every tread
     of every stair. A soffit's underside is rec.y; the floor below it is the
     highest slab TOP under it whose footprint it overlaps, and failing that the
     storey plane floor(y / 2.7) * 2.7. An element whose underside sits on that
     floor is a FLOOR, not a ceiling, and is skipped. */
  function runHeadroom(opt) {
    var minH = num(opt && opt.min, C.HEAD_MIN);
    var recs = solids();
    var slabs = recs.filter(function (o) { return SLABISH[o.kind]; });
    var soffits = recs.filter(function (o) { return SOFFIT[o.kind]; });
    var issues = [], rows = [], worst = null, i, j;

    function floorUnder(under, rect, selfId) {
      var best = null;
      for (j = 0; j < slabs.length; j++) {
        var s = slabs[j];
        if (s.id === selfId) continue;
        var top = (s.y || 0) + dims(s).h;
        if (top > under + 1e-6) continue;
        if (!overlaps(rect, corners(s))) continue;
        if (best === null || top > best) best = top;
      }
      return best === null ? Math.floor(under / C.STOREY + 1e-6) * C.STOREY : best;
    }

    for (i = 0; i < soffits.length; i++) {
      var o = soffits[i], under = o.y || 0, rect = corners(o);
      var fl = floorUnder(under, rect, o.id), gap = under - fl;
      if (gap < C.HEAD_BEARS) continue;                     /* it is a floor, not a ceiling */
      if (worst === null || gap < worst[0]) worst = [gap, o];
      if (gap < minH - 1e-9) {
        issues.push({
          ids: [o.id], severity: gap < C.HEAD_ABS ? 'error' : 'warn',
          text: label(o) + ' — ' + r2(gap) + ' m clear under it (floor at ' + r2(fl) + ' m, soffit at '
            + r2(under) + ' m); ' + minH + ' m required'
        });
      }
    }

    var stairs = recs.filter(isStair), sIssues = 0;
    for (i = 0; i < stairs.length; i++) {
      var st = stairs[i], p = st.p || {};
      var n = Math.max(1, Math.round(num(p.steps, 16))), rise = num(p.rise, 0.175);
      var run = num(p.run, 0.28), wd = num(p.w, 1.0);
      var low = null, lowStep = 0, k, treadTop, tr, s2, sy;
      for (k = 0; k < n; k++) {
        treadTop = (st.y || 0) + rise * (k + 1);
        tr = rectOf(st.x || 0, st.z || 0, st.ry || 0, -(n * run) / 2 + run * k + run / 2, 0, run, wd);
        for (j = 0; j < soffits.length; j++) {
          s2 = soffits[j];
          if (s2.id === st.id) continue;
          sy = s2.y || 0;
          if (sy < treadTop + 1e-6) continue;
          if (!overlaps(tr, corners(s2))) continue;
          if (low === null || sy - treadTop < low) { low = sy - treadTop; lowStep = k + 1; }
        }
      }
      if (low === null) { rows.push(['stair ' + st.id, 'nothing built over the flight — no soffit to measure against']); continue; }
      rows.push(['stair ' + st.id + ' (worst at tread ' + lowStep + ')', r2(low) + ' m']);
      if (low < minH - 1e-9) {
        sIssues++;
        issues.push({
          ids: [st.id], severity: low < C.HEAD_ABS ? 'error' : 'warn',
          text: label(st) + ' — only ' + r2(low) + ' m over tread ' + lowStep + '; ' + minH + ' m required'
        });
      }
    }

    rows.unshift(['minimum used', minH + ' m — the Dutch new-build value; 2.0 m is the absolute Bouwbesluit floor']);
    rows.splice(1, 0, ['soffits measured (slabs, flat roofs, beams)', soffits.length]);
    rows.splice(2, 0, ['stairs measured', stairs.length]);
    rows.splice(3, 0, ['lowest ceiling', worst ? r2(worst[0]) + ' m under ' + label(worst[1]) : 'nothing spans a space yet']);
    rows.splice(4, 0, ['too low', issues.length ? '<b>' + issues.length + '</b>' : '0']);
    return { ok: !issues.length, issues: issues, rows: rows };
  }

  /* ── 3. guarding ────────────────────────────────────────────────────────── */
  /* Every deck edge with more than a metre of drop must have a wall, railing,
     balustrade or parapet standing within 0.15 m of it, covering at least 80 %
     of its length and rising at least min_h above the walking surface. A
     balcony guards itself: its own rail_h is the number checked. Separately,
     any railing-like record whose p.gap / p.spacing exceeds max_gap fails the
     100 mm sphere rule. */
  var SIDES = ['north', 'east', 'south', 'west'];           /* local, before ry: -Z, +X, +Z, -X */

  function coverage(p0, p1, guards, top, minH) {
    var L = Math.sqrt((p1[0] - p0[0]) * (p1[0] - p0[0]) + (p1[1] - p0[1]) * (p1[1] - p0[1]));
    if (L < 1e-6) return { frac: 1, ids: [] };
    var ux = (p1[0] - p0[0]) / L, uz = (p1[1] - p0[1]) / L, nx = -uz, nz = ux;
    var iv = [], ids = [], i;
    for (i = 0; i < guards.length; i++) {
      var g = guards[i], gm = dims(g), gy = g.y || 0;
      if (gy < top - C.GUARD_BAND || gy > top + C.GUARD_BAND) continue;
      if (gy + gm.h - top < minH - 1e-9) continue;
      var c = Math.cos(g.ry || 0), s = Math.sin(g.ry || 0), half = gm.w / 2;
      var g0 = [(g.x || 0) - half * c, (g.z || 0) + half * s];
      var g1 = [(g.x || 0) + half * c, (g.z || 0) - half * s];
      var tol = C.EDGE_TOL + gm.d / 2;
      var d0 = (g0[0] - p0[0]) * nx + (g0[1] - p0[1]) * nz;
      var d1 = (g1[0] - p0[0]) * nx + (g1[1] - p0[1]) * nz;
      var lo = 0, hi = 1;
      if (Math.abs(d1 - d0) < 1e-9) { if (Math.abs(d0) > tol) continue; }
      else {
        var sA = (tol - d0) / (d1 - d0), sB = (-tol - d0) / (d1 - d0);
        lo = Math.max(0, Math.min(sA, sB)); hi = Math.min(1, Math.max(sA, sB));
        if (hi <= lo) continue;
      }
      var t0 = ((g0[0] - p0[0]) * ux + (g0[1] - p0[1]) * uz) / L;
      var t1 = ((g1[0] - p0[0]) * ux + (g1[1] - p0[1]) * uz) / L;
      var a = t0 + (t1 - t0) * lo, b = t0 + (t1 - t0) * hi;
      var A = Math.max(0, Math.min(a, b)), B = Math.min(1, Math.max(a, b));
      if (B - A > 1e-6) { iv.push([A, B]); ids.push(g.id); }
    }
    iv.sort(function (a, b) { return a[0] - b[0]; });
    var cov = 0, cur = null;
    for (i = 0; i < iv.length; i++) {
      if (cur === null) cur = [iv[i][0], iv[i][1]];
      else if (iv[i][0] <= cur[1]) cur[1] = Math.max(cur[1], iv[i][1]);
      else { cov += cur[1] - cur[0]; cur = [iv[i][0], iv[i][1]]; }
    }
    if (cur) cov += cur[1] - cur[0];
    return { frac: cov, ids: ids };
  }

  function runGuard(opt) {
    var minH = num(opt && opt.min_h, C.GUARD_H), maxGap = num(opt && opt.max_gap, C.GUARD_GAP);
    var recs = solids();
    var decks = recs.filter(function (o) { return DECK[o.kind]; });
    var slabs = recs.filter(function (o) { return SLABISH[o.kind]; });
    var guards = recs.filter(isGuardKind);
    var issues = [], rows = [], edges = 0, drops = 0, i, j, k;

    for (i = 0; i < decks.length; i++) {
      var o = decks[i], top = deckTop(o), rect = corners(o);
      var lower = 0;                                        /* the ground, unless a slab is nearer */
      for (j = 0; j < slabs.length; j++) {
        var s = slabs[j];
        if (s.id === o.id) continue;
        var st = (s.y || 0) + dims(s).h;
        if (st > top - C.HEAD_BEARS) continue;
        if (!overlaps(rect, corners(s))) continue;
        if (st > lower) lower = st;
      }
      var drop = top - lower;
      if (drop <= C.GUARD_DROP) continue;
      drops++;
      if (o.kind === 'balcony') {                           /* a balcony carries its own balustrade */
        var rh = num((o.p || {}).rail_h, 1.0);
        rows.push([label(o), 'own balustrade ' + r2(rh) + ' m, ' + r2(drop) + ' m drop']);
        if (rh < minH - 1e-9) {
          issues.push({ ids: [o.id], severity: 'error',
            text: label(o) + ' — its balustrade is ' + r2(rh) + ' m over a ' + r2(drop) + ' m drop; ' + minH + ' m required' });
        }
        continue;
      }
      for (k = 0; k < 4; k++) {
        var p0 = rect[k], p1 = rect[(k + 1) % 4];
        var L = Math.sqrt((p1[0] - p0[0]) * (p1[0] - p0[0]) + (p1[1] - p0[1]) * (p1[1] - p0[1]));
        if (L < 0.2) continue;
        /* an edge another deck continues at the same level is not an edge */
        var mx = (p0[0] + p1[0]) / 2, mz = (p0[1] + p1[1]) / 2;
        var ex = (p1[0] - p0[0]) / L, ez = (p1[1] - p0[1]) / L;
        var probe = [[mx + ez * 0.05 - ex * L * 0.45, mz - ex * 0.05 - ez * L * 0.45],
                     [mx + ez * 0.05 + ex * L * 0.45, mz - ex * 0.05 + ez * L * 0.45],
                     [mx + ez * 0.6 + ex * L * 0.45, mz - ex * 0.6 + ez * L * 0.45],
                     [mx + ez * 0.6 - ex * L * 0.45, mz - ex * 0.6 - ez * L * 0.45]];
        var abuts = false;
        for (j = 0; j < decks.length && !abuts; j++) {
          if (decks[j].id === o.id) continue;
          if (Math.abs(deckTop(decks[j]) - top) > C.HEAD_BEARS) continue;
          if (overlaps(probe, corners(decks[j]))) abuts = true;
        }
        if (abuts) continue;
        edges++;
        var cv = coverage(p0, p1, guards, top, minH);
        if (cv.frac < C.EDGE_COVER - 1e-9) {
          issues.push({
            ids: [o.id].concat(cv.ids), severity: 'error',
            text: label(o) + ' ' + SIDES[k] + ' edge — ' + r2(L) + ' m long over a ' + r2(drop)
              + ' m drop, guarded over ' + Math.round(cv.frac * 100) + '% of it (' + minH + ' m guard needed)'
          });
        }
      }
    }

    var gaps = 0;
    for (i = 0; i < guards.length; i++) {
      var g2 = guards[i], gp = g2.p || {};
      if (gp.gap === undefined && gp.spacing === undefined) continue;
      var gv = num(gp.gap, num(gp.spacing, 0));
      if (gv > maxGap + 1e-9) {
        gaps++;
        issues.push({
          ids: [g2.id], severity: 'warn',
          text: label(g2) + ' — ' + Math.round(gv * 1000) + ' mm between members; a '
            + Math.round(maxGap * 1000) + ' mm sphere must not pass through'
        });
      }
    }

    rows.unshift(['gap rule failures', gaps]);
    rows.unshift(['unguarded edges', issues.length - gaps ? '<b>' + (issues.length - gaps) + '</b>' : '0']);
    rows.unshift(['open edges checked', edges]);
    rows.unshift(['decks with more than ' + C.GUARD_DROP + ' m of drop', drops]);
    rows.unshift(['guard height / gap used', minH + ' m, ' + Math.round(maxGap * 1000) + ' mm']);
    rows.push(['guards found', guards.length + ' (walls, railings, balustrades, parapets, balconies)']);
    rows.push(['rule', 'a guard must stand within ' + C.EDGE_TOL + ' m of the edge and cover '
      + Math.round(C.EDGE_COVER * 100) + '% of it']);
    return { ok: !issues.length, issues: issues, rows: rows };
  }

  /* ── 4. stair rule ──────────────────────────────────────────────────────── */
  /* Blondel (2*rise + run in 0.60..0.65 m), rise, run, width, and whether the
     flight actually lands on the next storey. The parameters make every riser
     equal by construction, which is itself reported. */
  function runStair(opt) {
    var recs = solids().filter(isStair);
    var storey = num(opt && opt.storey_h, C.STOREY);
    var issues = [], rows = [], i;
    for (i = 0; i < recs.length; i++) {
      var o = recs[i], p = o.p || {};
      var n = Math.max(1, Math.round(num(p.steps, 16)));
      var rise = num(p.rise, 0.175), run = num(p.run, 0.28), wd = num(p.w, 1.0);
      var bl = 2 * rise + run, climb = n * rise, over = climb - storey;
      var bad = [];
      if (bl < C.BLONDEL_LO - 1e-9 || bl > C.BLONDEL_HI + 1e-9)
        bad.push('2&times;rise+run is ' + r3(bl) + ' m, outside ' + C.BLONDEL_LO + '&ndash;' + C.BLONDEL_HI + ' m');
      if (rise > C.RISE_MAX + 1e-9) bad.push('rise ' + r3(rise) + ' m is over ' + C.RISE_MAX + ' m');
      if (run < C.RUN_MIN - 1e-9) bad.push('run ' + r3(run) + ' m is under ' + C.RUN_MIN + ' m');
      if (wd < C.WIDTH_MIN - 1e-9) bad.push('width ' + r2(wd) + ' m is under ' + C.WIDTH_MIN + ' m');
      var land;
      if (Math.abs(over) <= C.STOREY_TOL) land = 'lands on the next storey';
      else if (over > 0) land = 'does not reach: over by ' + r2(over) + ' m';
      else land = 'does not reach: ' + r2(-over) + ' m short';
      if (Math.abs(over) > C.STOREY_TOL) bad.push(land);
      rows.push([label(o), n + ' &times; ' + r3(rise) + ' / ' + r3(run) + ' m, ' + r2(wd) + ' m wide &mdash; 2R+G '
        + r3(bl) + ' m, climbs ' + r2(climb) + ' m, ' + land + '; every riser equal by construction']);
      if (bad.length) {
        issues.push({ ids: [o.id], severity: bad.length > 1 ? 'error' : 'warn',
          text: label(o) + ' — ' + bad.join('; ') });
      }
    }
    rows.unshift(['flights flagged', issues.length ? '<b>' + issues.length + '</b>' : '0']);
    rows.unshift(['flights checked', recs.length]);
    rows.unshift(['rule', 'Blondel ' + C.BLONDEL_LO + '&ndash;' + C.BLONDEL_HI + ' m, rise &le; ' + C.RISE_MAX
      + ' m, run &ge; ' + C.RUN_MIN + ' m, width &ge; ' + C.WIDTH_MIN + ' m, storey ' + storey + ' m &plusmn; '
      + C.STOREY_TOL + ' m']);
    if (!recs.length) rows.push(['note', 'no stair in the drawing — draw one and press again']);
    return { ok: !issues.length, issues: issues, rows: rows };
  }

  /* ── the shared registry ('Code check' runs every entry) ────────────────── */
  AR_EXT.analyses = AR_EXT.analyses || [];
  var DEFS = [
    { id: 'clash', icon: 'a_clash', label: 'Clash detection', run: runClash },
    { id: 'headroom', icon: 'a_headroom', label: 'Headroom', run: runHeadroom },
    { id: 'guarding', icon: 'a_guard', label: 'Guarding and handrails', run: runGuard },
    { id: 'stair', icon: 'a_stair', label: 'Stair rule', run: runStair }
  ];
  DEFS.forEach(function (D) { AR_EXT.analyses.push({ id: D.id, label: D.label, run: D.run }); });

  /* ── the sheet: findings you can select and see ─────────────────────────── */
  var G = window.ANALYSE_GEOMETRY = { _hl: [], _issues: [] };

  G.clear = function () {
    G._hl.forEach(function (h) { if (h.parent) h.parent.remove(h); if (h.geometry) h.geometry.dispose(); });
    G._hl = [];
    G._issues = [];
  };
  G.pick = function (i) {
    var is = G._issues[i];
    if (!is) return;
    arSelect(is.ids.slice());
    if (typeof arFitIds === 'function') arFitIds(is.ids.slice());
  };
  G.highlight = function (issues) {
    if (!AR.scene || typeof THREE === 'undefined' || !THREE.Box3Helper) return;
    issues.forEach(function (is) {
      is.ids.forEach(function (id) {
        var rec = arFind(id);
        if (!rec || !rec.node) return;
        var b = new THREE.Box3().expandByObject(rec.node);
        if (b.isEmpty()) return;
        var h = new THREE.Box3Helper(b, new THREE.Color(is.severity === 'warn' ? 0xffb648 : 0xff3b3b));
        h.userData.arSkip = 1;
        AR.scene.add(h);
        G._hl.push(h);
      });
    });
  };

  function sheet(def, res) {
    G.clear();
    G._issues = res.issues;
    G.highlight(res.issues);
    var html = '<p style="margin:0 0 8px">' + (res.ok
      ? '<b style="color:#5fd08a">Passed</b> &mdash; nothing to report.'
      : '<b style="color:#ff6b6b">' + res.issues.length + '</b> finding'
        + (res.issues.length === 1 ? '' : 's') + '. Press <i>select</i> to jump to one; the red boxes clear when this sheet closes.')
      + '</p>';
    html += arRows(res.rows);
    if (res.issues.length) {
      html += '<table class="ar-tbl" style="margin-top:10px">' + res.issues.map(function (is, i) {
        return '<tr><td><b style="color:' + (is.severity === 'warn' ? '#ffb648' : '#ff6b6b') + '">'
          + is.severity + '</b> &nbsp;' + is.text + '</td>'
          + '<td style="width:70px;text-align:right"><button onclick="ANALYSE_GEOMETRY.pick(' + i + ')">select</button></td></tr>';
      }).join('') + '</table>';
    }
    arSheet(def.label, html);
    arToast(res.ok ? def.label + ': passed.' : def.label + ': ' + res.issues.length + ' finding'
      + (res.issues.length === 1 ? '' : 's') + '.', res.ok ? '' : 'warn');
  }

  function ask(opt, key, def, question) {
    if (opt && typeof opt === 'object') return num(opt[key], def);
    var v = prompt(question, String(def));
    return v === null ? def : num(v, def);
  }

  AR_EXT.tools.a_clash = {
    assist: 1,
    tip: 'Clash detection — every pair of solids that occupy the same space, with the shared volume; corner joints, openings and things bearing on a slab are excused',
    act: function (opt) { sheet(DEFS[0], runClash(opt && typeof opt === 'object' ? opt : {})); }
  };
  AR_EXT.tools.a_headroom = {
    assist: 1,
    tip: 'Headroom — clear height under every slab, beam and stair soffit against 2.3 m (the Dutch new-build value; 2.0 m is the absolute minimum)',
    act: function (opt) { sheet(DEFS[1], runHeadroom({ min: ask(opt, 'min', C.HEAD_MIN, 'Minimum clear height in metres (2.3 = NL new build, 2.0 = absolute minimum):') })); }
  };
  AR_EXT.tools.a_guard = {
    assist: 1,
    tip: 'Guarding — every deck edge with more than 1 m of drop needs a 1.0 m guard along 80% of it, and no gap a 100 mm sphere passes through',
    act: function (opt) {
      sheet(DEFS[2], runGuard({
        min_h: ask(opt, 'min_h', C.GUARD_H, 'Minimum guard height in metres:'),
        max_gap: ask(opt, 'max_gap', C.GUARD_GAP, 'Largest gap between members in metres (0.1 = the 100 mm sphere):')
      }));
    }
  };
  AR_EXT.tools.a_stair = {
    assist: 1,
    tip: 'Stair check — 2 risers plus a tread should land near 63 cm, rise \u2264 185 mm, run \u2265 220 mm, width \u2265 800 mm, and the flight must reach the next storey',
    act: function (opt) { sheet(DEFS[3], runStair(opt && typeof opt === 'object' ? opt : {})); }
  };

  AR_EXT.ready.push(function () {
    var base = arSheetClose;                                /* the highlights belong to the sheet */
    arSheetClose = function () { G.clear(); base(); };
  });
})();
