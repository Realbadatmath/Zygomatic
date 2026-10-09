// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* drawings_2d — the 2D drawing generator behind the Drawings dock group
   (2026-09-08). Wires dc_plan, dc_elev, dc_sect, dc_scale, dc_dim, dc_hatch,
   dc_lw. Everything is produced from the records themselves; nothing in
   inspection.html was edited.

   CONTRACT (the drawings_sheet and file_2d families build on this):
     window.drawings2d = {
       svg(kind, opts) -> {svg, w_mm, h_mm, scale, bounds, title},
       settings()      -> AR.doc.ext.drawings_2d (created with defaults),
       last            -> the last result,
       download()      -> saves `last` as an .svg file
     }
   Units: the generator works in plan METRES, the SVG viewBox is in paper MM
   (1 m = 1000/scale mm), and every stroke width / text height is a paper mm,
   so a print at 100 % comes out true to scale. */
(function () {
  'use strict';

  var FAM = 'drawings_2d';
  var MARGIN_M = 2.0;                     /* paper margin, in MODEL metres, so it scales with `scale` */
  var DEF = {
    scale: 100,
    lw: { cut: 0.5, proj: 0.25, hidden: 0.13, thin: 0.13 },
    hatch: 'ansi31', hatch_cut: true,
    dim: { text_mm: 2.5, arrow: 'tick', unit: 'm', decimals: 2 },
    storey: 0, cut_h: 1.2, elev: 'front',
    section: { x: null, z: null, dir: 'x' }
  };
  var HATCHES = ['ansi31', 'concrete', 'none'];
  var ARROWS = ['tick', 'arrow', 'dot'];
  var ELEVS = ['front', 'back', 'left', 'right'];

  function J(o) { return JSON.parse(JSON.stringify(o)); }
  function N(v, d) { v = parseFloat(v); return isFinite(v) ? v : d; }
  function R(v) { return Math.round(v * 1000) / 1000; }
  function xesc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function storeyH() { return (window.AR && AR.defaults && N(AR.defaults.wall_h, 2.7)) || 2.7; }

  /* ── settings: AR.doc.ext.drawings_2d, created with the defaults ───────── */
  function settings() {
    var doc = (window.AR && AR.doc) ? AR.doc : null;
    if (!doc) return J(DEF);
    if (!doc.ext || typeof doc.ext !== 'object') doc.ext = {};
    var s = doc.ext[FAM];
    if (!s || typeof s !== 'object') { s = J(DEF); doc.ext[FAM] = s; }
    if (!isFinite(s.scale) || s.scale <= 0) s.scale = DEF.scale;
    if (!s.lw || typeof s.lw !== 'object') s.lw = J(DEF.lw);
    ['cut', 'proj', 'hidden', 'thin'].forEach(function (k) {
      if (!isFinite(s.lw[k]) || s.lw[k] <= 0) s.lw[k] = DEF.lw[k];
    });
    if (HATCHES.indexOf(s.hatch) < 0) s.hatch = DEF.hatch;
    if (typeof s.hatch_cut !== 'boolean') s.hatch_cut = true;
    if (!s.dim || typeof s.dim !== 'object') s.dim = J(DEF.dim);
    if (!isFinite(s.dim.text_mm) || s.dim.text_mm <= 0) s.dim.text_mm = DEF.dim.text_mm;
    if (ARROWS.indexOf(s.dim.arrow) < 0) s.dim.arrow = DEF.dim.arrow;
    if (['m', 'mm'].indexOf(s.dim.unit) < 0) s.dim.unit = DEF.dim.unit;
    if (!isFinite(s.dim.decimals) || s.dim.decimals < 0) s.dim.decimals = DEF.dim.decimals;
    if (!isFinite(s.storey)) s.storey = 0;
    if (!isFinite(s.cut_h)) s.cut_h = DEF.cut_h;
    if (ELEVS.indexOf(s.elev) < 0) s.elev = DEF.elev;
    if (!s.section || typeof s.section !== 'object') s.section = J(DEF.section);
    if (['x', 'z'].indexOf(s.section.dir) < 0) s.section.dir = 'x';
    return s;
  }

  function dimText(m, s) {
    if (s.dim.unit === 'mm') return String(Math.round(m * 1000));
    return Math.abs(m).toFixed(Math.max(0, Math.min(4, Math.round(s.dim.decimals))));
  }

  /* ── the display list (view coordinates in METRES) ─────────────────────── */
  function Draw() { this.it = []; this.b = [1e9, -1e9, 1e9, -1e9]; }
  Draw.prototype.grow = function (pts) {
    var b = this.b, i, p;
    for (i = 0; i < pts.length; i++) {
      p = pts[i];
      if (!p || !isFinite(p[0]) || !isFinite(p[1])) continue;
      if (p[0] < b[0]) b[0] = p[0];
      if (p[0] > b[1]) b[1] = p[0];
      if (p[1] < b[2]) b[2] = p[1];
      if (p[1] > b[3]) b[3] = p[1];
    }
  };
  Draw.prototype.add = function (o) {
    this.it.push(o);
    if (o.bnd !== false && o.pts) this.grow(o.pts);
    return o;
  };
  Draw.prototype.poly = function (pts, cls, fill, dk) { return this.add({ t: 'poly', pts: pts, cls: cls, fill: fill, dk: dk }); };
  Draw.prototype.pl = function (pts, cls, dash, dk) { return this.add({ t: 'pl', pts: pts, cls: cls, dash: dash, dk: dk }); };
  Draw.prototype.line = function (a, b, cls, dash, dk) { return this.add({ t: 'pl', pts: [a, b], cls: cls, dash: dash, dk: dk }); };
  Draw.prototype.text = function (x, y, str, size, anchor, rot) {
    return this.add({ t: 'text', pts: [[x, y]], x: x, y: y, s: str, size: size, anchor: anchor, rot: rot, bnd: false });
  };

  /* ── emitting the SVG ─────────────────────────────────────────────────── */
  function penOf(cls, s) {
    if (cls === 'cut') return s.lw.cut;
    if (cls === 'proj') return s.lw.proj;
    if (cls === 'hidden') return s.lw.hidden;
    return s.lw.thin;
  }
  function defsFor(s) {
    if (s.hatch === 'none' || !s.hatch_cut) return '';
    var g = '<pattern id="d2hatch" patternUnits="userSpaceOnUse" width="2" height="2" '
      + 'patternTransform="rotate(45)"><rect x="0" y="0" width="2" height="2" fill="#ffffff"/>'
      + '<path d="M0 0 V2" stroke="#000000" stroke-width="0.13" fill="none"/>';
    if (s.hatch === 'concrete') g += '<circle cx="1.35" cy="1.0" r="0.17" fill="#000000"/>';
    g += '</pattern>';
    return '<defs>' + g + '</defs>';
  }
  function cutFill(s) { return (s.hatch === 'none' || !s.hatch_cut) ? '#ffffff' : 'url(#d2hatch)'; }

  function emitOne(o, s, X, Y, MM) {
    var cls = o.cls || 'thin', sw = R(penOf(cls, s)), f = o.fill || 'none';
    var dk = o.dk ? ' data-kind="' + xesc(o.dk) + '"' : '';
    var dash = o.dash ? ' stroke-dasharray="' + o.dash + '"' : '';
    var P = function (pts) { return pts.map(function (p) { return X(p[0]) + ',' + Y(p[1]); }).join(' '); };
    switch (o.t) {
      case 'poly':
        return '<polygon class="' + cls + '"' + dk + ' points="' + P(o.pts) + '" fill="' + f
          + '" stroke="' + (o.nostroke ? 'none' : '#000000') + '" stroke-width="' + (o.nostroke ? 0 : sw) + '"' + dash + '/>';
      case 'pl':
        return '<polyline class="' + cls + '"' + dk + ' points="' + P(o.pts) + '" fill="none"'
          + ' stroke="#000000" stroke-width="' + sw + '"' + dash + '/>';
      case 'arc':
        return '<path class="' + cls + '"' + dk + ' d="M' + X(o.a[0]) + ' ' + Y(o.a[1]) + 'A' + MM(o.r) + ' '
          + MM(o.r) + ' 0 ' + o.large + ' ' + o.sweep + ' ' + X(o.c[0]) + ' ' + Y(o.c[1])
          + '" fill="none" stroke="#000000" stroke-width="' + sw + '"/>';
      case 'loops': {
        var d = o.loops.map(function (lp) {
          return 'M' + lp.map(function (p, i) { return (i ? 'L' : '') + X(p[0]) + ' ' + Y(p[1]); }).join('') + 'Z';
        }).join('');
        return '<path class="' + cls + '"' + dk + ' d="' + d + '" fill-rule="evenodd" fill="' + f
          + '" stroke="#000000" stroke-width="' + sw + '"/>';
      }
      case 'circle':
        return '<circle class="' + cls + '"' + dk + ' cx="' + X(o.cx) + '" cy="' + Y(o.cy) + '" r="' + MM(o.r)
          + '" fill="' + f + '" stroke="#000000" stroke-width="' + sw + '"' + dash + '/>';
      case 'tri':
        return '<path class="' + cls + '"' + dk + ' d="M' + P(o.pts).replace(/ /g, 'L').replace(/,/g, ' ')
          + 'Z" fill="#000000" stroke="none"/>';
      case 'text': {
        var sz = R(N(o.size, s.dim.text_mm)), x = X(o.x), y = Y(o.y);
        var tr = o.rot ? ' transform="rotate(' + o.rot + ' ' + x + ' ' + y + ')"' : '';
        return '<text class="txt" x="' + x + '" y="' + y + '" font-size="' + sz
          + '" font-family="Helvetica, Arial, sans-serif" text-anchor="' + (o.anchor || 'middle')
          + '" fill="#000000"' + tr + '>' + xesc(o.s) + '</text>';
      }
      default: return '';
    }
  }

  function svgOut(dr, s, title) {
    var k = 1000 / s.scale, b = dr.b.slice();
    if (b[0] > b[1] || b[2] > b[3]) b = [-5, 5, -5, 5];
    var W = (b[1] - b[0] + 2 * MARGIN_M) * k, H = (b[3] - b[2] + 2 * MARGIN_M) * k;
    var X = function (v) { return R((v - b[0] + MARGIN_M) * k); };
    var Y = function (v) { return R((v - b[2] + MARGIN_M) * k); };
    var MM = function (v) { return R(v * k); };
    var body = dr.it.map(function (o) { return emitOne(o, s, X, Y, MM); }).join('');
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="' + R(W) + 'mm" height="' + R(H)
      + 'mm" viewBox="0 0 ' + R(W) + ' ' + R(H) + '">' + defsFor(s)
      + '<rect id="d2bg" x="0" y="0" width="' + R(W) + '" height="' + R(H) + '" fill="#ffffff" stroke="none"/>'
      + body + '</svg>';
    return {
      svg: svg, w_mm: W, h_mm: H, scale: s.scale, title: title,
      bounds: { minx: b[0], maxx: b[1], miny: b[2], maxy: b[3] }
    };
  }

  /* ── dimension strings ────────────────────────────────────────────────── */
  function ticks(dr, s, x, y, vertical) {
    var t = mmv(s, 1.4);
    if (s.dim.arrow === 'dot') { dr.add({ t: 'circle', cx: x, cy: y, r: mmv(s, 0.5), cls: 'thin', fill: '#000000', bnd: false }); return; }
    if (s.dim.arrow === 'arrow') {
      var a = mmv(s, 2.2), w = mmv(s, 0.7);
      var pts = vertical ? [[x, y], [x - w, y + a], [x + w, y + a]] : [[x, y], [x + a, y - w], [x + a, y + w]];
      dr.add({ t: 'tri', pts: pts, cls: 'thin', bnd: false });
      return;
    }
    dr.add({ t: 'pl', pts: [[x - t, y + t], [x + t, y - t]], cls: 'thin', bnd: false });
  }
  function mmv(s, mm) { return mm * s.scale / 1000; }   /* paper mm -> model metres */

  function dimH(dr, s, x0, x1, yMeas, yDim, txt) {
    var g = mmv(s, 1.0);
    dr.add({ t: 'pl', pts: [[x0, yMeas + (yDim > yMeas ? g : -g)], [x0, yDim + (yDim > yMeas ? g : -g)]], cls: 'thin', bnd: false });
    dr.add({ t: 'pl', pts: [[x1, yMeas + (yDim > yMeas ? g : -g)], [x1, yDim + (yDim > yMeas ? g : -g)]], cls: 'thin', bnd: false });
    dr.add({ t: 'pl', pts: [[x0, yDim], [x1, yDim]], cls: 'thin', bnd: false });
    ticks(dr, s, x0, yDim, false); ticks(dr, s, x1, yDim, false);
    dr.text((x0 + x1) / 2, yDim - mmv(s, 1.2), txt == null ? dimText(x1 - x0, s) : txt, s.dim.text_mm, 'middle', 0);
  }
  function dimV(dr, s, y0, y1, xMeas, xDim, txt) {
    var g = mmv(s, 1.0);
    dr.add({ t: 'pl', pts: [[xMeas + (xDim > xMeas ? g : -g), y0], [xDim + (xDim > xMeas ? g : -g), y0]], cls: 'thin', bnd: false });
    dr.add({ t: 'pl', pts: [[xMeas + (xDim > xMeas ? g : -g), y1], [xDim + (xDim > xMeas ? g : -g), y1]], cls: 'thin', bnd: false });
    dr.add({ t: 'pl', pts: [[xDim, y0], [xDim, y1]], cls: 'thin', bnd: false });
    ticks(dr, s, xDim, y0, true); ticks(dr, s, xDim, y1, true);
    dr.add({
      t: 'text', x: xDim - mmv(s, 1.2), y: (y0 + y1) / 2, s: txt == null ? dimText(Math.abs(y1 - y0), s) : txt,
      size: s.dim.text_mm, anchor: 'middle', rot: -90, bnd: false
    });
  }

  /* ── record helpers ───────────────────────────────────────────────────── */
  function recs() {
    return (window.AR && AR.objs ? AR.objs : []).filter(function (o) { return o && !o.hidden && o.node; });
  }
  function box3(rec) {
    rec.node.updateMatrixWorld(true);
    var b = new THREE.Box3();
    b.expandByObject(rec.node);
    return b;
  }
  function rotPts(cx, cz, w, d, ry) {           /* oriented rectangle -> VIEW points (vx = x, vy = -z) */
    var c = Math.cos(ry || 0), sn = Math.sin(ry || 0), out = [];
    [[-w / 2, -d / 2], [w / 2, -d / 2], [w / 2, d / 2], [-w / 2, d / 2]].forEach(function (l) {
      var wx = cx + l[0] * c + l[1] * sn, wz = cz - l[0] * sn + l[1] * c;
      out.push([wx, -wz]);
    });
    return out;
  }
  function isOpening(kind) {
    return kind === 'door' || kind === 'double_door' || kind === 'window' || kind === 'opening'
      || !!(window.AR_EXT && AR_EXT.openings && AR_EXT.openings[kind]);
  }

  window.drawings2d = window.drawings2d || {};
  var D2 = window.drawings2d;
  D2.settings = settings;
  D2._DEF = DEF;
  D2._Draw = Draw;
  D2._svgOut = svgOut;
  D2._dimH = dimH;
  D2._dimV = dimV;
  D2._mmv = mmv;
  D2._dimText = dimText;
  D2._recs = recs;
  D2._box3 = box3;
  D2._rotPts = rotPts;
  D2._isOpening = isOpening;
  D2._cutFill = cutFill;
  D2._storeyH = storeyH;
  D2._N = N;
})();

/* ── PLAN ─────────────────────────────────────────────────────────────────
   Cut the model at y = storey*2.7 + cut_h. Solids that straddle the cut give
   their footprint as a CUT polygon (heavy pen + hatch); solids wholly below
   the cut and above the storey floor are projected with the light pen. */
(function () {
  'use strict';
  var D2 = window.drawings2d;
  var N = D2._N, mmv = D2._mmv, rotPts = D2._rotPts, box3 = D2._box3;

  function wallHoles(rec, cutLocal) {
    var hs = (rec.p && rec.p.holes) || [];
    return hs.filter(function (h) {
      var sill = N(h.sill, 0), hh = N(h.h, 2.1);
      return cutLocal > sill && cutLocal < sill + hh;
    }).slice().sort(function (a, b) { return N(a.u, 0) - N(b.u, 0); });
  }

  function wallPiers(rec, cutLocal) {
    var len = N(rec.p.len, 4), t = N(rec.p.t, rec.kind === 'partition' ? 0.10 : 0.24);
    var hs = wallHoles(rec, cutLocal), out = [], cur = 0, i;
    for (i = 0; i < hs.length; i++) {
      var a = Math.max(cur, N(hs[i].u, 0) - N(hs[i].w, 1) / 2), b = Math.min(len, N(hs[i].u, 0) + N(hs[i].w, 1) / 2);
      if (b <= a) continue;
      if (a > cur + 1e-4) out.push([cur, a]);
      cur = b;
    }
    if (cur < len - 1e-4) out.push([cur, len]);
    return out.map(function (seg) {
      var w = seg[1] - seg[0], mid = (seg[0] + seg[1]) / 2 - len / 2;
      var c = Math.cos(rec.ry || 0), sn = Math.sin(rec.ry || 0);
      return rotPts(rec.x + mid * c, rec.z - mid * sn, w, t, rec.ry || 0);
    });
  }

  function footprint(rec) {
    var p = rec.p || {}, k = rec.kind;
    if (k === 'column_round') return { circle: { cx: rec.x, cy: -rec.z, r: N(p.r, 0.18) } };
    if (k === 'column_rect' || k === 'footing') return { poly: rotPts(rec.x, rec.z, N(p.w, 0.3), N(p.d, 0.3), rec.ry) };
    if (k === 'beam') return { poly: rotPts(rec.x, rec.z, N(p.len, 5), N(p.w, 0.2), rec.ry) };
    if (p.w != null && p.d != null) return { poly: rotPts(rec.x, rec.z, N(p.w, 1), N(p.d, 1), rec.ry) };
    if (p.len != null && p.t != null) return { poly: rotPts(rec.x, rec.z, N(p.len, 1), N(p.t, 0.24), rec.ry) };
    var b = box3(rec);                                   /* anything else: the world bbox projected to XZ */
    return { poly: [[b.min.x, -b.min.z], [b.max.x, -b.min.z], [b.max.x, -b.max.z], [b.min.x, -b.max.z]], weak: 1 };
  }

  function doorSwing(dr, s, rec, host) {
    var w = N(rec.p.w, rec.kind === 'double_door' ? 1.6 : 0.9);
    var ry = host ? (host.ry || 0) : (rec.ry || 0);
    var ax = Math.cos(ry), az = -Math.sin(ry);            /* along the wall, world XZ */
    var px = Math.sin(ry), pz = Math.cos(ry);             /* across the wall */
    var leaves = rec.kind === 'double_door' ? [[-1, w / 2], [1, w / 2]] : [[-1, w]];
    leaves.forEach(function (lf) {
      var sgn = lf[0], r = lf[1];
      var hx = rec.x + ax * sgn * (w / 2), hz = rec.z + az * sgn * (w / 2);
      var cl = [hx - ax * sgn * r, -(hz - az * sgn * r)];  /* shut position (view) */
      var op = [hx + px * r, -(hz + pz * r)];              /* open position (view) */
      var h = [hx, -hz];
      var zs = (cl[0] - h[0]) * (op[1] - h[1]) - (cl[1] - h[1]) * (op[0] - h[0]);
      dr.add({ t: 'pl', pts: [h, op], cls: 'thin', dk: rec.kind });
      dr.add({ t: 'arc', a: cl, c: op, r: r, large: 0, sweep: zs > 0 ? 1 : 0, cls: 'thin', dk: rec.kind, pts: [cl, op, h] });
    });
  }

  function windowLines(dr, s, rec, host) {
    var w = N(rec.p.w, 1.2), t = host ? N(host.p.t, 0.24) : 0.24;
    var ry = host ? (host.ry || 0) : (rec.ry || 0);
    var ax = Math.cos(ry), az = -Math.sin(ry), px = Math.sin(ry), pz = Math.cos(ry);
    [-t / 2, 0, t / 2].forEach(function (off) {
      var cx = rec.x + px * off, cz = rec.z + pz * off;
      dr.add({
        t: 'pl', cls: 'thin', dk: rec.kind,
        pts: [[cx - ax * w / 2, -(cz - az * w / 2)], [cx + ax * w / 2, -(cz + az * w / 2)]]
      });
    });
  }

  function stairPlan(dr, s, rec) {
    var p = rec.p || {}, steps = Math.max(1, Math.round(N(p.steps, N(p.steps_a, 16))));
    var run = N(p.run, 0.28), w = N(p.w, 1.0), L = steps * run;
    var ry = rec.ry || 0, ax = Math.cos(ry), az = -Math.sin(ry), px = Math.sin(ry), pz = Math.cos(ry);
    var pt = function (lx, lz) { return [rec.x + ax * lx + px * lz, -(rec.z + az * lx + pz * lz)]; };
    dr.poly([pt(-L / 2, -w / 2), pt(L / 2, -w / 2), pt(L / 2, w / 2), pt(-L / 2, w / 2)], 'proj', 'none', rec.kind);
    for (var i = 1; i < steps; i++) {
      var lx = -L / 2 + run * i;
      dr.add({ t: 'pl', pts: [pt(lx, -w / 2), pt(lx, w / 2)], cls: 'thin', dk: 'tread' });
    }
    dr.add({ t: 'pl', pts: [pt(-L / 2 + run * 0.6, 0), pt(L / 2 - run * 0.6, 0)], cls: 'thin', dk: 'up' });
    var tipL = L / 2 - run * 0.6, h = Math.min(run, w / 3);
    dr.add({ t: 'pl', pts: [pt(tipL - h, -h / 2), pt(tipL, 0), pt(tipL - h, h / 2)], cls: 'thin', dk: 'up' });
    dr.text(pt(-L / 2 + run * 0.6, 0)[0], pt(-L / 2 + run * 0.6, 0)[1] - mmv(s, 1.0), 'UP', s.dim.text_mm * 0.8, 'middle', 0);
  }

  function zonePlan(dr, s, rec) {
    var w = N(rec.p.w, 4), d = N(rec.p.d, 3);
    var pts = rotPts(rec.x, rec.z, w, d, rec.ry);
    dr.poly(pts, 'thin', 'none', rec.kind).dash = String(mmv(s, 2)) + ' ' + String(mmv(s, 1.2));
    dr.text(rec.x, -rec.z, rec.name || 'Zone', s.dim.text_mm, 'middle', 0);
    dr.text(rec.x, -rec.z + mmv(s, 3.2), (w * d).toFixed(1) + ' m\u00b2', s.dim.text_mm * 0.85, 'middle', 0);
  }

  /* the annotation records of measure_annotations, drawn AS THEY ARE — their
     own parameters, not a guess: dim_linear p{x2, z2, off, txt} (x2/z2 is the
     delta from the record's point, in its LOCAL frame), dim_angle
     p{x1, z1, x2, z2, r} (two rays from the record's point) and label_text
     p{txt, size}. `measure_annotations_label(rec)` is that family's own text
     when it is loaded; the arithmetic below is the fallback, not a second
     opinion. */
  function local2view(rec, lx, lz) {
    var c = Math.cos(rec.ry || 0), sn = Math.sin(rec.ry || 0);
    return [rec.x + lx * c + lz * sn, -(rec.z - lx * sn + lz * c)];
  }
  function annoText(rec, dflt) {
    var p = rec.p || {};
    if (p.txt != null && String(p.txt) !== '') return String(p.txt);
    if (typeof window.measure_annotations_label === 'function') {
      try { return window.measure_annotations_label(rec); } catch (e) { /* fall through */ }
    }
    return dflt;
  }

  function annotation(dr, s, rec) {
    var k = rec.kind, p = rec.p || {};
    if (k === 'label_text') {
      var sz = Math.max(0.05, N(p.size, 0.35)), o = local2view(rec, 0, 0);
      dr.add({ t: 'pl', pts: [local2view(rec, -sz / 2, 0), local2view(rec, sz / 2, 0)], cls: 'thin', dk: k });
      dr.add({ t: 'pl', pts: [local2view(rec, 0, -sz / 2), local2view(rec, 0, sz / 2)], cls: 'thin', dk: k });
      dr.text(o[0], o[1] - mmv(s, 1.4), annoText(rec, rec.name || ''), s.dim.text_mm, 'middle', 0);
      return true;
    }
    if (k === 'dim_linear') {
      var x2 = N(p.x2, 5), z2 = N(p.z2, 0), off = N(p.off, 0.6);
      var L = Math.hypot(x2, z2) || 1e-6, ux = x2 / L, uz = z2 / L;
      var ox = -uz * off, oz = ux * off, e = 1.12;
      var a = local2view(rec, ox, oz), b = local2view(rec, x2 + ox, z2 + oz);
      dr.add({ t: 'pl', pts: [a, b], cls: 'thin', dk: k });
      dr.add({ t: 'pl', pts: [local2view(rec, 0, 0), local2view(rec, ox * e, oz * e)], cls: 'thin', dk: k });
      dr.add({ t: 'pl', pts: [local2view(rec, x2, z2), local2view(rec, x2 + ox * e, z2 + oz * e)], cls: 'thin', dk: k });
      ticks2(dr, s, a, b); ticks2(dr, s, b, a);
      dr.text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - mmv(s, 1.2), annoText(rec, D2._dimText(L, s)),
              s.dim.text_mm, 'middle', 0);
      return true;
    }
    if (k === 'dim_angle') {
      var x1 = N(p.x1, 1), z1 = N(p.z1, 0), X2 = N(p.x2, 0), Z2 = N(p.z2, -1), r = Math.max(0.05, N(p.r, 1));
      var a1 = Math.atan2(z1, x1), a2 = Math.atan2(Z2, X2), d = a2 - a1;
      while (d > Math.PI) d -= 2 * Math.PI;
      while (d < -Math.PI) d += 2 * Math.PI;
      dr.add({ t: 'pl', pts: [local2view(rec, 0, 0), local2view(rec, x1, z1)], cls: 'thin', dk: k });
      dr.add({ t: 'pl', pts: [local2view(rec, 0, 0), local2view(rec, X2, Z2)], cls: 'thin', dk: k });
      var arc = [], i;
      for (i = 0; i <= 24; i++) {
        var t = a1 + d * (i / 24);
        arc.push(local2view(rec, Math.cos(t) * r, Math.sin(t) * r));
      }
      dr.add({ t: 'pl', pts: arc, cls: 'thin', dk: k });
      var mid = local2view(rec, Math.cos(a1 + d / 2) * r * 1.3, Math.sin(a1 + d / 2) * r * 1.3);
      dr.text(mid[0], mid[1], annoText(rec, (Math.abs(d) * 180 / Math.PI).toFixed(0) + '\u00b0'),
              s.dim.text_mm, 'middle', 0);
      return true;
    }
    return false;
  }

  /* a 45 degree drafting tick at `at`, leaning along the line at -> away */
  function ticks2(dr, s, at, away) {
    var dx = away[0] - at[0], dy = away[1] - at[1], L = Math.hypot(dx, dy) || 1;
    var ux = dx / L, uy = dy / L, tx = ux - uy, ty = uy + ux, tn = Math.hypot(tx, ty) || 1;
    var h = mmv(s, 1.4);
    dr.add({ t: 'pl', cls: 'thin', bnd: false,
             pts: [[at[0] - tx / tn * h, at[1] - ty / tn * h], [at[0] + tx / tn * h, at[1] + ty / tn * h]] });
  }

  D2._plan = function (s, opt) {
    var dr = new D2._Draw();
    var H = D2._storeyH(), storey = Math.round(N(opt && opt.storey, s.storey));
    var base = storey * H, cut = base + N(s.cut_h, 1.2);
    var all = D2._recs(), openings = [], i, rec, b;
    for (i = 0; i < all.length; i++) {
      rec = all[i];
      if (annotation(dr, s, rec)) continue;
      if (D2._isOpening(rec.kind)) { openings.push(rec); continue; }
      if (/^zone/.test(rec.kind)) { zonePlan(dr, s, rec); continue; }
      b = box3(rec);
      if (b.isEmpty()) continue;
      if (b.min.y > cut - 1e-6 || b.max.y < base - 1e-6) continue;          /* not on this storey */
      if (/^stair/.test(rec.kind)) { stairPlan(dr, s, rec); continue; }
      var isCut = b.min.y <= cut && b.max.y > cut;
      if (rec.kind === 'wall' || rec.kind === 'partition') {
        var piers = wallPiers(rec, cut - (rec.y || 0));
        piers.forEach(function (pp) { dr.poly(pp, isCut ? 'cut' : 'proj', isCut ? D2._cutFill(s) : 'none', rec.kind); });
        continue;
      }
      var fp = footprint(rec);
      if (fp.circle) {
        dr.add({
          t: 'circle', cx: fp.circle.cx, cy: fp.circle.cy, r: fp.circle.r, cls: isCut ? 'cut' : 'proj',
          fill: isCut ? D2._cutFill(s) : 'none', dk: rec.kind,
          pts: [[fp.circle.cx - fp.circle.r, fp.circle.cy - fp.circle.r], [fp.circle.cx + fp.circle.r, fp.circle.cy + fp.circle.r]]
        });
      } else {
        dr.poly(fp.poly, isCut ? 'cut' : (fp.weak ? 'thin' : 'proj'), isCut ? D2._cutFill(s) : 'none', rec.kind);
      }
    }
    openings.forEach(function (o) {
      var oy = o.y || 0, sill = oy + N(o.p.sill, o.kind === 'window' ? 0.9 : 0), top = sill + N(o.p.h, 2.1);
      if (cut < sill || cut > top) return;
      var host = o.p && o.p.host ? arFind(o.p.host) : null;
      if (o.kind === 'window') windowLines(dr, s, o, host); else doorSwing(dr, s, o, host);
    });

    var bb = dr.b;
    if (bb[0] <= bb[1]) {
      D2._dimH(dr, s, bb[0], bb[1], bb[3], bb[3] + 0.9, null);
      D2._dimV(dr, s, bb[2], bb[3], bb[0], bb[0] - 0.9, null);
      /* north arrow (rotated by the sun family's north, when it is set) */
      var north = 0, ls = (window.AR && AR.doc && AR.doc.ext && AR.doc.ext.light_sun) || null;
      if (ls && isFinite(ls.north)) north = N(ls.north, 0);
      var nx = bb[1] - 0.4, ny = bb[2] - 1.1, r = mmv(s, 4);
      var rot = function (dx, dy) {
        var a = north * Math.PI / 180, c = Math.cos(a), sn = Math.sin(a);
        return [nx + dx * c - dy * sn, ny + dx * sn + dy * c];
      };
      dr.add({ t: 'pl', pts: [rot(0, -r), rot(r * 0.42, r * 0.55), rot(0, r * 0.2), rot(-r * 0.42, r * 0.55), rot(0, -r)], cls: 'thin', dk: 'north', bnd: false });
      dr.text(rot(0, -r - mmv(s, 1.6))[0], rot(0, -r - mmv(s, 1.6))[1], 'N', s.dim.text_mm, 'middle', 0);
      dr.text(bb[0], bb[3] + 1.65, 'PLAN \u2014 storey ' + storey + ' \u2014 1:' + s.scale, s.dim.text_mm * 1.2, 'start', 0);
    }
    return D2._svgOut(dr, s, 'Plan \u2014 storey ' + storey + ' \u2014 1:' + s.scale);
  };
})();

/* ── ELEVATION and SECTION ────────────────────────────────────────────────
   Elevation: every visible solid's world-space edges (EdgesGeometry 30°)
   projected orthographically, records painted far-to-near, each record's
   projected convex hull filled white before its own edges — the painter's
   algorithm, not a true hidden-line remover, but honest and it reads.
   Section: the real intersection of each straddling record's world triangles
   with the plane, chained into closed loops and poch\u00e9d; everything beyond
   the plane drawn as an elevation. */
(function () {
  'use strict';
  var D2 = window.drawings2d;
  var N = D2._N, mmv = D2._mmv, box3 = D2._box3;
  var MAXREC = 400;

  var PROJ = {
    front: { u: function (x, y, z) { return x; }, far: function (x, y, z) { return z; } },
    back: { u: function (x, y, z) { return -x; }, far: function (x, y, z) { return -z; } },
    right: { u: function (x, y, z) { return -z; }, far: function (x, y, z) { return -x; } },
    left: { u: function (x, y, z) { return z; }, far: function (x, y, z) { return x; } }
  };

  function hull(pts) {
    if (pts.length < 3) return pts.slice();
    var p = pts.slice().sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
    var cr = function (o, a, b) { return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]); };
    var lo = [], up = [], i;
    for (i = 0; i < p.length; i++) { while (lo.length >= 2 && cr(lo[lo.length - 2], lo[lo.length - 1], p[i]) <= 0) lo.pop(); lo.push(p[i]); }
    for (i = p.length - 1; i >= 0; i--) { while (up.length >= 2 && cr(up[up.length - 2], up[up.length - 1], p[i]) <= 0) up.pop(); up.push(p[i]); }
    lo.pop(); up.pop();
    return lo.concat(up);
  }

  /* world-space edge segments of one record, projected to [ [u,v], [u,v] ] */
  function edges2d(rec, P) {
    var out = [];
    rec.node.updateMatrixWorld(true);
    rec.node.traverse(function (m) {
      if (!m.isMesh || !m.geometry || !m.geometry.attributes || !m.geometry.attributes.position) return;
      var g = null, e = null;
      try {
        g = m.geometry.clone(); g.applyMatrix4(m.matrixWorld);
        e = new THREE.EdgesGeometry(g, 30);
        var a = e.attributes.position.array;
        for (var i = 0; i + 5 < a.length; i += 6) {
          out.push([[P.u(a[i], a[i + 1], a[i + 2]), -a[i + 1]],
                    [P.u(a[i + 3], a[i + 4], a[i + 5]), -a[i + 4]]]);
        }
      } catch (x) { /* a degenerate part contributes nothing */ }
      if (e && e.dispose) e.dispose();
      if (g && g.dispose) g.dispose();
    });
    return out;
  }

  /* triangle × plane -> segments in the section's own (u, v) */
  function cutSegs(rec, axis, c, P) {
    var out = [], tmp = new THREE.Vector3();
    rec.node.updateMatrixWorld(true);
    rec.node.traverse(function (m) {
      if (!m.isMesh || !m.geometry || !m.geometry.attributes || !m.geometry.attributes.position) return;
      var pos = m.geometry.attributes.position, idx = m.geometry.index, n = pos.count, i;
      var w = new Float64Array(n * 3);
      for (i = 0; i < n; i++) {
        tmp.set(pos.getX(i), pos.getY(i), pos.getZ(i)).applyMatrix4(m.matrixWorld);
        w[i * 3] = tmp.x; w[i * 3 + 1] = tmp.y; w[i * 3 + 2] = tmp.z;
      }
      var cnt = idx ? idx.count : n;
      for (i = 0; i + 2 < cnt; i += 3) {
        var T = idx ? [idx.getX(i), idx.getX(i + 1), idx.getX(i + 2)] : [i, i + 1, i + 2];
        var d = [0, 0, 0], q;
        for (q = 0; q < 3; q++) d[q] = (axis === 'x' ? w[T[q] * 3] : w[T[q] * 3 + 2]) - c;
        var hits = [];
        for (q = 0; q < 3; q++) {
          var q2 = (q + 1) % 3, d1 = d[q], d2 = d[q2];
          if ((d1 < 0 && d2 > 0) || (d1 > 0 && d2 < 0)) {
            var t = d1 / (d1 - d2), j1 = T[q] * 3, j2 = T[q2] * 3;
            var X = w[j1] + (w[j2] - w[j1]) * t, Y = w[j1 + 1] + (w[j2 + 1] - w[j1 + 1]) * t,
                Z = w[j1 + 2] + (w[j2 + 2] - w[j1 + 2]) * t;
            hits.push([P.u(X, Y, Z), -Y]);
          }
        }
        if (hits.length === 2) out.push(hits);
      }
    });
    return out;
  }

  function chain(segs) {
    var tol = 1e-4, key = function (p) { return Math.round(p[0] / tol) + '_' + Math.round(p[1] / tol); };
    var map = {}, used = {}, out = [], i, j;
    for (i = 0; i < segs.length; i++) {
      var ka = key(segs[i][0]), kb = key(segs[i][1]);
      if (ka === kb) { used[i] = 1; continue; }
      (map[ka] = map[ka] || []).push({ i: i, rev: false });
      (map[kb] = map[kb] || []).push({ i: i, rev: true });
    }
    for (i = 0; i < segs.length; i++) {
      if (used[i]) continue;
      used[i] = 1;
      var loop = [segs[i][0], segs[i][1]], guard = 0, closed = false;
      while (guard++ < 20000) {
        var list = map[key(loop[loop.length - 1])] || [], nx = null;
        for (j = 0; j < list.length; j++) if (!used[list[j].i]) { nx = list[j]; break; }
        if (!nx) break;
        used[nx.i] = 1;
        loop.push(nx.rev ? segs[nx.i][0] : segs[nx.i][1]);
        if (key(loop[loop.length - 1]) === key(loop[0])) { closed = true; break; }
      }
      if (closed && loop.length >= 4) { loop.pop(); out.push(loop); }
    }
    return out;
  }

  /* the shared elevation painter: `list` is already far-to-near */
  function paint(dr, s, list, P) {
    list.forEach(function (rec) {
      var segs = edges2d(rec, P);
      if (!segs.length) return;
      var pts = [];
      segs.forEach(function (sg) { pts.push(sg[0], sg[1]); });
      var h = hull(pts);
      if (h.length >= 3) dr.add({ t: 'poly', pts: h, cls: 'thin', fill: '#ffffff', nostroke: 1, dk: rec.kind });
      segs.forEach(function (sg) { dr.add({ t: 'pl', pts: sg, cls: 'proj', dk: rec.kind }); });
    });
  }

  function openingRects(dr, s, list, P) {
    list.forEach(function (o) {
      var w = N(o.p.w, 1), h = N(o.p.h, 2.1);
      var sill = (o.y || 0) + N(o.p.sill, o.kind === 'window' ? 0.9 : 0);
      var u = P.u(o.x, 0, o.z);
      dr.poly([[u - w / 2, -sill], [u + w / 2, -sill], [u + w / 2, -(sill + h)], [u - w / 2, -(sill + h)]],
              'proj', 'none', o.kind);
    });
  }

  /* level lines + the storey dimension chain, shared by elevation and section */
  function levels(dr, s, lo, hi, top) {
    var H = D2._storeyH(), marks = [0], k = 1;
    while (k * H < top - 1e-6 && k < 60) { marks.push(k * H); k++; }
    if (top > marks[marks.length - 1] + 1e-6) marks.push(top);
    marks.forEach(function (y) {
      dr.add({ t: 'pl', pts: [[lo - 0.3, -y], [hi + 0.3, -y]], cls: 'hidden', dash: String(mmv(s, 3)) + ' ' + String(mmv(s, 1.5)), dk: 'level', bnd: false });
      dr.text(hi + 0.4, -y - mmv(s, 0.8), '+' + y.toFixed(2), s.dim.text_mm * 0.85, 'start', 0);
    });
    for (var i = 1; i < marks.length; i++) D2._dimV(dr, s, -marks[i - 1], -marks[i], lo, lo - 0.9, D2._dimText(marks[i] - marks[i - 1], s));
    if (marks.length > 2) D2._dimV(dr, s, 0, -top, hi, hi + 1.7, D2._dimText(top, s));
  }

  D2._elevation = function (s, opt) {
    var dr = new D2._Draw();
    var view = String((opt && opt.elev) || s.elev || 'front');
    var P = PROJ[view] || PROJ.front;
    var all = D2._recs().slice(0, MAXREC), solids = [], openings = [], top = 0, i;
    for (i = 0; i < all.length; i++) {
      var rec = all[i];
      if (D2._isOpening(rec.kind)) { openings.push(rec); continue; }
      var b = box3(rec);
      if (b.isEmpty()) continue;
      if (b.max.y > top) top = b.max.y;
      solids.push({ r: rec, far: P.far((b.min.x + b.max.x) / 2, 0, (b.min.z + b.max.z) / 2) });
    }
    solids.sort(function (a, b) { return b.far - a.far; });
    paint(dr, s, solids.map(function (o) { return o.r; }), P);
    openingRects(dr, s, openings, P);
    var bb = dr.b;
    if (bb[0] <= bb[1]) {
      dr.add({ t: 'pl', pts: [[bb[0] - 0.3, 0], [bb[1] + 0.3, 0]], cls: 'cut', dk: 'ground', bnd: false });
      levels(dr, s, bb[0], bb[1], top);
      dr.text(bb[0], bb[3] + 1.65, 'ELEVATION \u2014 ' + view + ' \u2014 1:' + s.scale, s.dim.text_mm * 1.2, 'start', 0);
    }
    return D2._svgOut(dr, s, 'Elevation \u2014 ' + view + ' \u2014 1:' + s.scale);
  };

  D2._section = function (s, opt) {
    var dr = new D2._Draw();
    opt = opt || {};
    var dir = String(opt.dir || (opt.z != null ? 'z' : (opt.x != null ? 'x' : (s.section.dir || 'x'))));
    if (dir !== 'x' && dir !== 'z') dir = 'x';
    var all = D2._recs().slice(0, MAXREC);
    var c = N(dir === 'x' ? opt.x : opt.z, N(dir === 'x' ? s.section.x : s.section.z, NaN));
    if (!isFinite(c)) {                                    /* no plane given: cut through the middle */
      var lo = 1e9, hi = -1e9;
      all.forEach(function (r) {
        var b = box3(r); if (b.isEmpty()) return;
        lo = Math.min(lo, dir === 'x' ? b.min.x : b.min.z);
        hi = Math.max(hi, dir === 'x' ? b.max.x : b.max.z);
      });
      c = lo > hi ? 0 : (lo + hi) / 2;
    }
    var P = dir === 'x' ? { u: function (x, y, z) { return z; }, far: function (x, y, z) { return -x; } }
                        : { u: function (x, y, z) { return x; }, far: function (x, y, z) { return -z; } };
    var beyond = [], top = 0, i;
    for (i = 0; i < all.length; i++) {
      var rec = all[i], b = box3(rec);
      if (b.isEmpty()) continue;
      if (b.max.y > top) top = b.max.y;
      var mn = dir === 'x' ? b.min.x : b.min.z, mx = dir === 'x' ? b.max.x : b.max.z;
      if (mn < c && mx > c) {
        if (D2._isOpening(rec.kind)) continue;             /* an opening is a void: it makes no poch\u00e9 */
        var segs = cutSegs(rec, dir, c, P);
        var loops = chain(segs);
        if (loops.length) dr.add({ t: 'loops', loops: loops, cls: 'cut', fill: D2._cutFill(s), dk: rec.kind, pts: [].concat.apply([], loops) });
        else segs.forEach(function (sg) { dr.add({ t: 'pl', pts: sg, cls: 'cut', dk: rec.kind }); });
      } else if (mx <= c) {
        beyond.push({ r: rec, far: P.far((b.min.x + b.max.x) / 2, 0, (b.min.z + b.max.z) / 2) });
      }
    }
    beyond.sort(function (a, b) { return b.far - a.far; });
    var solids = beyond.filter(function (o) { return !D2._isOpening(o.r.kind); }).map(function (o) { return o.r; });
    var cutItems = dr.it.slice();
    dr.it = [];
    paint(dr, s, solids, P);                               /* the far half first, so the poch\u00e9 sits on top */
    openingRects(dr, s, beyond.filter(function (o) { return D2._isOpening(o.r.kind); }).map(function (o) { return o.r; }), P);
    dr.it = dr.it.concat(cutItems);
    var bb = dr.b;
    if (bb[0] <= bb[1]) {
      dr.add({ t: 'pl', pts: [[bb[0] - 0.3, 0], [bb[1] + 0.3, 0]], cls: 'cut', dk: 'ground', bnd: false });
      levels(dr, s, bb[0], bb[1], top);
      dr.text(bb[0], bb[3] + 1.65, 'SECTION \u2014 ' + dir + ' = ' + c.toFixed(2) + ' \u2014 1:' + s.scale,
              s.dim.text_mm * 1.2, 'start', 0);
    }
    var res = D2._svgOut(dr, s, 'Section \u2014 ' + dir + ' = ' + c.toFixed(2) + ' \u2014 1:' + s.scale);
    res.plane = { dir: dir, at: c };
    return res;
  };
})();

/* ── the public API and the seven icons ───────────────────────────────── */
(function () {
  'use strict';
  var D2 = window.drawings2d, N = D2._N;

  D2.svg = function (kind, opts) {
    var s = D2.settings(), k = String(kind || 'plan');
    var res = k === 'elevation' || k === 'elev' ? D2._elevation(s, opts || {})
            : k === 'section' || k === 'sect' ? D2._section(s, opts || {})
            : D2._plan(s, opts || {});
    D2.last = res;
    return res;
  };
  D2.download = function () {
    if (!D2.last) { arToast('No drawing to save yet.', 'warn'); return; }
    var nm = (D2.last.title || 'drawing').replace(/[^\w]+/g, '_').replace(/^_|_$/g, '');
    arDownload(new Blob([D2.last.svg], { type: 'image/svg+xml' }), nm + '.svg');
  };
  function sheet(res) {
    var b = res.bounds;
    arSheet(res.title,
      '<div style="max-height:56vh;overflow:auto;background:#fff;padding:6px;border-radius:4px">' + res.svg + '</div>'
      + arRows([['scale', '1:' + res.scale],
                ['sheet', res.w_mm.toFixed(1) + ' \u00d7 ' + res.h_mm.toFixed(1) + ' mm'],
                ['extent', (b.maxx - b.minx).toFixed(2) + ' \u00d7 ' + (b.maxy - b.miny).toFixed(2) + ' m'],
                ['pens (mm)', 'cut ' + D2.settings().lw.cut + ' \u00b7 proj ' + D2.settings().lw.proj],
                ['hatch', D2.settings().hatch]])
      + '<div style="margin-top:8px"><button onclick="drawings2d.download()">Download SVG</button></div>');
  }
  function ask(opt, key, q, dflt) {
    if (opt && typeof opt === 'object' && opt[key] != null) return opt[key];
    var a = prompt(q, String(dflt));
    return a == null ? null : a;
  }

  D2.setDim = function (k, v) {
    var s = D2.settings();
    arPush();
    if (k === 'text_mm' || k === 'decimals') s.dim[k] = N(v, s.dim[k]);
    else s.dim[k] = String(v);
    D2.settings(); arDirty(true);
    arToast('Dimension style: ' + k + ' = ' + s.dim[k] + '.');
  };
  D2.setLw = function (k, v) {
    var s = D2.settings();
    arPush(); s.lw[k] = N(v, s.lw[k]); D2.settings(); arDirty(true);
    arToast('Line weight: ' + k + ' = ' + s.lw[k] + ' mm.');
  };

  AR_EXT.tools.dc_plan = {
    assist: 1, tip: 'Floor plan — cut the model at the storey height and put it on a sheet, to scale',
    act: function (opt) {
      var s = D2.settings();
      var v = ask(opt, 'storey', 'Plan of which storey? (0 = ground)', s.storey);
      if (v === null) return;
      var res = D2.svg('plan', { storey: Math.round(N(v, s.storey)) });
      sheet(res);
      return res.svg;
    }
  };
  AR_EXT.tools.dc_elev = {
    assist: 1, tip: 'Elevation from a chosen direction, dimensioned and to scale',
    act: function (opt) {
      var s = D2.settings();
      var v = ask(opt, 'elev', 'Elevation from which side? front, back, left or right', s.elev);
      if (v === null) return;
      var res = D2.svg('elevation', { elev: String(v) });
      sheet(res);
      return res.svg;
    }
  };
  AR_EXT.tools.dc_sect = {
    assist: 1, tip: 'Section through the section plane, with the cut faces poch\u00e9d',
    act: function (opt) {
      var s = D2.settings(), o = {};
      if (opt && typeof opt === 'object') {
        o = { dir: opt.dir, x: opt.x, z: opt.z };
      } else {
        var d = prompt('Section along which axis? x (a plane at x = c) or z', s.section.dir);
        if (d === null) return;
        var c = prompt('Cut the plane at which coordinate (m)? blank = through the middle',
                       String(N(d === 'z' ? s.section.z : s.section.x, '')));
        o.dir = d === 'z' ? 'z' : 'x';
        if (c !== null && String(c).trim() !== '') o[o.dir] = parseFloat(c);
      }
      var res = D2.svg('section', o);
      sheet(res);
      return res.svg;
    }
  };
  AR_EXT.tools.dc_scale = {
    assist: 1, tip: 'Drawing scale — 1:20, 1:50, 1:100, 1:200, 1:500; the SVG is sized in mm so a print is true to scale',
    act: function (opt) {
      var s = D2.settings();
      var v = ask(opt, 'scale', 'Drawing scale 1: (20, 50, 100, 200, 500)', s.scale);
      if (v === null) return;
      var n = Math.round(N(v, 0));
      if (!(n > 0)) { arToast('A scale is a number like 100 (for 1:100).', 'warn'); return; }
      arPush(); s.scale = n; arDirty(true);
      arToast('Drawing scale <b>1:' + n + '</b> \u2014 1 m prints as ' + (1000 / n).toFixed(1) + ' mm.');
      return n;
    }
  };
  AR_EXT.tools.dc_dim = {
    assist: 1, tip: 'Dimension style — arrowheads, text height, units and decimals',
    act: function (opt) {
      var s = D2.settings();
      if (opt && typeof opt === 'object') {
        arPush();
        if (opt.text_mm != null) s.dim.text_mm = N(opt.text_mm, s.dim.text_mm);
        if (opt.arrow != null) s.dim.arrow = String(opt.arrow);
        if (opt.unit != null) s.dim.unit = String(opt.unit);
        if (opt.decimals != null) s.dim.decimals = Math.round(N(opt.decimals, s.dim.decimals));
        D2.settings(); arDirty(true);
        arToast('Dimension style: ' + s.dim.text_mm + ' mm text, ' + s.dim.arrow + ', ' + s.dim.unit + '.');
        return s.dim;
      }
      var sel = function (k, opts) {
        return '<select onchange="drawings2d.setDim(\'' + k + '\', this.value)">'
          + opts.map(function (o) { return '<option value="' + o + '"' + (s.dim[k] === o ? ' selected' : '') + '>' + o + '</option>'; }).join('')
          + '</select>';
      };
      arSheet('Dimension style', arRows([
        ['text height (mm)', '<input type="number" step="0.1" min="0.5" value="' + s.dim.text_mm
          + '" style="width:6em" onchange="drawings2d.setDim(\'text_mm\', this.value)">'],
        ['arrowhead', sel('arrow', ['tick', 'arrow', 'dot'])],
        ['unit', sel('unit', ['m', 'mm'])],
        ['decimals', '<input type="number" step="1" min="0" max="4" value="' + s.dim.decimals
          + '" style="width:6em" onchange="drawings2d.setDim(\'decimals\', this.value)">']
      ]));
      return s.dim;
    }
  };
  AR_EXT.tools.dc_hatch = {
    assist: 1, tog: 1,
    tip: 'Hatch of the cut solids — ANSI31, concrete, or none. Click to cycle',
    on: function () { return D2.settings().hatch !== 'none'; },
    act: function (opt) {
      var s = D2.settings(), order = ['ansi31', 'concrete', 'none'], v;
      if (opt && typeof opt === 'object' && opt.hatch != null) v = String(opt.hatch);
      else v = order[(order.indexOf(s.hatch) + 1) % order.length];
      if (order.indexOf(v) < 0) { arToast('Hatch must be ansi31, concrete or none.', 'warn'); return; }
      arPush(); s.hatch = v; arDirty(true);
      arToast('Cut hatch: <b>' + v + '</b>.');
      return v;
    }
  };
  AR_EXT.tools.dc_lw = {
    assist: 1, tip: 'Line weights — the cut heavy, the seen light (pen widths in mm)',
    act: function (opt) {
      var s = D2.settings();
      if (opt && typeof opt === 'object') {
        arPush();
        ['cut', 'proj', 'hidden', 'thin'].forEach(function (k) { if (opt[k] != null) s.lw[k] = N(opt[k], s.lw[k]); });
        D2.settings(); arDirty(true);
        arToast('Pens (mm): cut ' + s.lw.cut + ', proj ' + s.lw.proj + ', hidden ' + s.lw.hidden + ', thin ' + s.lw.thin + '.');
        return s.lw;
      }
      arSheet('Line weights (mm)', arRows(['cut', 'proj', 'hidden', 'thin'].map(function (k) {
        return [k, '<input type="number" step="0.01" min="0.01" value="' + s.lw[k]
          + '" style="width:6em" onchange="drawings2d.setLw(\'' + k + '\', this.value)">'];
      })));
      return s.lw;
    }
  };
})();
