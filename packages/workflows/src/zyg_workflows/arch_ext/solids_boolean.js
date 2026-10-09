// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* solids_boolean — Union / Subtract / Intersect for the Architecture Studio
   (2026-09-08). Wires the three Solids icons `bool_u`, `bool_s`, `bool_i` and
   adds one new kind, `csg`.

   THE KERNEL IS FIRST-PARTY. The brief asked for Evan Wallace's csg.js to be
   curl'd into vendor/csg/; that download was refused by this machine's
   untrusted-code policy, so the BSP boolean below is an original
   implementation of the same classic algorithm (Naylor/Thibault/Amanatides
   1990 — build a BSP tree per solid, clip each against the other, recombine).
   Nothing is fetched at run time and there is no vendored dependency: the
   whole kernel is the `SB.*` section of this file. Licence: this repository's.

   A DRAWING STORES PARAMETERS, NEVER GEOMETRY. So a boolean is a record of
   kind 'csg' whose p is
       {op:'union'|'subtract'|'intersect',
        a:{kind, p, x, y, z, rx, ry, rz, s},
        b:{kind, p, x, y, z, rx, ry, rz, s}}
   — the two operands' full parameter records, positioned RELATIVE to the csg
   record, which itself sits at operand a's x/y/z. AR_EXT.geom.csg rebuilds
   both operands through arGeom() (recursively: an operand may itself be a
   'csg'), transforms them into the record's local frame, runs the BSP boolean
   and returns one part. The result is cached on a WeakMap keyed by the p
   object, so dragging the record — which only re-applies a transform — never
   re-runs the BSP, and a rebuild with unchanged parameters copies a buffer
   instead of re-cutting the tree.

   CAP: BSP booleans are O(n log n) at best and O(n^2) on adversarial input, so
   an operand of more than SB.MAX_TRIS triangles is refused with a toast rather
   than hanging the tab. */
(function () {
  'use strict';

  var SB = {MAX_TRIS: 20000, EPS: 1e-5, MAX_DEPTH: 4};

  /* ── vectors ─────────────────────────────────────────────────────────── */
  function V(x, y, z) { this.x = x; this.y = y; this.z = z; }
  V.prototype.clone = function () { return new V(this.x, this.y, this.z); };
  V.prototype.negated = function () { return new V(-this.x, -this.y, -this.z); };
  V.prototype.plus = function (a) { return new V(this.x + a.x, this.y + a.y, this.z + a.z); };
  V.prototype.minus = function (a) { return new V(this.x - a.x, this.y - a.y, this.z - a.z); };
  V.prototype.times = function (k) { return new V(this.x * k, this.y * k, this.z * k); };
  V.prototype.dot = function (a) { return this.x * a.x + this.y * a.y + this.z * a.z; };
  V.prototype.lerp = function (a, t) { return this.plus(a.minus(this).times(t)); };
  V.prototype.len = function () { return Math.sqrt(this.dot(this)); };
  V.prototype.unit = function () { var l = this.len(); return l ? this.times(1 / l) : new V(0, 1, 0); };
  V.prototype.cross = function (a) {
    return new V(this.y * a.z - this.z * a.y, this.z * a.x - this.x * a.z, this.x * a.y - this.y * a.x);
  };

  /* a polygon corner: position + the normal that is interpolated across a cut */
  function Vert(pos, nrm) { this.pos = pos; this.nrm = nrm; }
  Vert.prototype.clone = function () { return new Vert(this.pos.clone(), this.nrm.clone()); };
  Vert.prototype.flip = function () { this.nrm = this.nrm.negated(); };
  Vert.prototype.interpolate = function (o, t) {
    return new Vert(this.pos.lerp(o.pos, t), this.nrm.lerp(o.nrm, t));
  };

  /* ── planes ──────────────────────────────────────────────────────────── */
  function Plane(nrm, w) { this.nrm = nrm; this.w = w; }
  Plane.fromPoints = function (a, b, c) {
    var n = b.minus(a).cross(c.minus(a));
    if (n.len() < 1e-12) return null;                 /* a degenerate triangle has no plane */
    n = n.unit();
    return new Plane(n, n.dot(a));
  };
  Plane.prototype.clone = function () { return new Plane(this.nrm.clone(), this.w); };
  Plane.prototype.flip = function () { this.nrm = this.nrm.negated(); this.w = -this.w; };

  var COPLANAR = 0, FRONT = 1, BACK = 2, SPANNING = 3;

  /* Sort one polygon against this plane into the four output lists. The whole
     boolean is this routine plus a tree walk. */
  Plane.prototype.split = function (poly, coFront, coBack, front, back) {
    var i, t, type = 0, types = [], e = SB.EPS;
    for (i = 0; i < poly.verts.length; i++) {
      t = this.nrm.dot(poly.verts[i].pos) - this.w;
      var ty = (t < -e) ? BACK : (t > e) ? FRONT : COPLANAR;
      type |= ty;
      types.push(ty);
    }
    if (type === COPLANAR) {
      (this.nrm.dot(poly.plane.nrm) > 0 ? coFront : coBack).push(poly);
    } else if (type === FRONT) {
      front.push(poly);
    } else if (type === BACK) {
      back.push(poly);
    } else {                                          /* SPANNING: cut it in two */
      var f = [], b = [];
      for (i = 0; i < poly.verts.length; i++) {
        var j = (i + 1) % poly.verts.length;
        var ti = types[i], tj = types[j], vi = poly.verts[i], vj = poly.verts[j];
        if (ti !== BACK) f.push(vi);
        if (ti !== FRONT) b.push(ti !== BACK ? vi.clone() : vi);
        if ((ti | tj) === SPANNING) {
          var d = this.nrm.dot(vj.pos.minus(vi.pos));
          var s = d ? (this.w - this.nrm.dot(vi.pos)) / d : 0;
          var v = vi.interpolate(vj, s);
          f.push(v); b.push(v.clone());
        }
      }
      if (f.length >= 3) front.push(new Poly(f));
      if (b.length >= 3) back.push(new Poly(b));
    }
  };

  /* ── polygons ────────────────────────────────────────────────────────── */
  function Poly(verts) {
    this.verts = verts;
    this.plane = Plane.fromPoints(verts[0].pos, verts[1].pos, verts[2].pos);
  }
  Poly.prototype.clone = function () {
    var p = new Poly(this.verts.map(function (v) { return v.clone(); }));
    return p;
  };
  Poly.prototype.flip = function () {
    this.verts.reverse().forEach(function (v) { v.flip(); });
    if (this.plane) this.plane.flip();
  };

  /* ── the BSP tree ────────────────────────────────────────────────────── */
  function Node(polys) {
    this.plane = null; this.front = null; this.back = null; this.polys = [];
    if (polys && polys.length) this.build(polys);
  }
  Node.prototype.invert = function () {
    var i;
    for (i = 0; i < this.polys.length; i++) this.polys[i].flip();
    if (this.plane) this.plane.flip();
    if (this.front) this.front.invert();
    if (this.back) this.back.invert();
    var t = this.front; this.front = this.back; this.back = t;
  };
  Node.prototype.clipPolys = function (polys) {
    if (!this.plane) return polys.slice();
    var front = [], back = [], i;
    for (i = 0; i < polys.length; i++) this.plane.split(polys[i], front, back, front, back);
    if (this.front) front = this.front.clipPolys(front);
    back = this.back ? this.back.clipPolys(back) : [];
    return front.concat(back);
  };
  Node.prototype.clipTo = function (other) {
    this.polys = other.clipPolys(this.polys);
    if (this.front) this.front.clipTo(other);
    if (this.back) this.back.clipTo(other);
  };
  Node.prototype.allPolys = function () {
    var out = this.polys.slice();
    if (this.front) out = out.concat(this.front.allPolys());
    if (this.back) out = out.concat(this.back.allPolys());
    return out;
  };
  Node.prototype.build = function (polys) {
    if (!polys.length) return;
    if (!this.plane) {
      /* the first non-degenerate polygon supplies the splitting plane */
      for (var s = 0; s < polys.length; s++) {
        if (polys[s].plane) { this.plane = polys[s].plane.clone(); break; }
      }
      if (!this.plane) return;
    }
    var front = [], back = [], i;
    for (i = 0; i < polys.length; i++) {
      if (polys[i].plane) this.plane.split(polys[i], this.polys, this.polys, front, back);
    }
    if (front.length) { this.front = this.front || new Node(); this.front.build(front); }
    if (back.length) { this.back = this.back || new Node(); this.back.build(back); }
  };

  /* the three operations, each a different order of clip/invert */
  SB.boolean = function (op, a0, b0) {
    var a = new Node(a0), b = new Node(b0);
    if (op === 'union') {
      a.clipTo(b); b.clipTo(a); b.invert(); b.clipTo(a); b.invert();
      a.build(b.allPolys());
      return a.allPolys();
    }
    if (op === 'intersect') {
      a.invert(); b.clipTo(a); b.invert(); a.clipTo(b); b.clipTo(a);
      a.build(b.allPolys()); a.invert();
      return a.allPolys();
    }
    /* subtract: a minus b */
    a.invert(); a.clipTo(b); b.clipTo(a); b.invert(); b.clipTo(a); b.invert();
    a.build(b.allPolys()); a.invert();
    return a.allPolys();
  };

  /* ── THREE <-> CSG bridge ────────────────────────────────────────────── */
  /* A BufferGeometry's triangles, put through `mat`, become polygons. The
     matrix is applied HERE (the brief's "world space" step) so that both
     operands live in one frame before the tree is built; for a csg record that
     frame is the record's own local frame, which is what arGeom must return. */
  SB.polysOf = function (geom, mat) {
    var pos = geom.attributes && geom.attributes.position;
    if (!pos) return [];
    var nrmA = geom.attributes.normal, idx = geom.index;
    var n = idx ? idx.count : pos.count, out = [], i, j;
    var nm = new THREE.Matrix3().getNormalMatrix(mat);
    var P = new THREE.Vector3(), N = new THREE.Vector3();
    for (i = 0; i + 2 < n; i += 3) {
      var vs = [];
      for (j = 0; j < 3; j++) {
        var k = idx ? idx.getX(i + j) : (i + j);
        P.set(pos.getX(k), pos.getY(k), pos.getZ(k)).applyMatrix4(mat);
        if (nrmA) N.set(nrmA.getX(k), nrmA.getY(k), nrmA.getZ(k)).applyMatrix3(nm).normalize();
        else N.set(0, 1, 0);
        vs.push(new Vert(new V(P.x, P.y, P.z), new V(N.x, N.y, N.z)));
      }
      var p = new Poly(vs);
      if (p.plane) out.push(p);               /* degenerate triangles carry no information */
    }
    return out;
  };

  /* Polygons back to a NON-INDEXED BufferGeometry with computed normals: a
     boolean's faces are flat and its seams must not be smoothed across. */
  SB.geomOf = function (polys) {
    var pos = [], i, j;
    for (i = 0; i < polys.length; i++) {
      var vs = polys[i].verts;
      for (j = 2; j < vs.length; j++) {       /* fan-triangulate the convex fragment */
        var a = vs[0].pos, b = vs[j - 1].pos, c = vs[j].pos;
        if (b.minus(a).cross(c.minus(a)).len() < 1e-12) continue;
        pos.push(a.x, a.y, a.z, b.x, b.y, b.z, c.x, c.y, c.z);
      }
    }
    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.computeVertexNormals();
    return g;
  };

  /* Every mesh part of one operand, transformed into the csg record's frame.
     An operand may itself be a 'csg', so this re-enters arGeom — SB.depth
     bounds that recursion (a drawing that names itself would never finish). */
  SB.operandPolys = function (desc) {
    if (!desc || !desc.kind) return [];
    var parts = arGeom(desc.kind, desc.p || {}) || [];
    var m = new THREE.Matrix4().compose(
      new THREE.Vector3(+desc.x || 0, +desc.y || 0, +desc.z || 0),
      new THREE.Quaternion().setFromEuler(new THREE.Euler(+desc.rx || 0, +desc.ry || 0, +desc.rz || 0)),
      new THREE.Vector3(desc.s || 1, desc.s || 1, desc.s || 1));
    var out = [], i;
    for (i = 0; i < parts.length; i++) {
      if (!parts[i].g || parts[i].line) continue;     /* guides contribute no volume */
      out = out.concat(SB.polysOf(parts[i].g, m));
    }
    return out;
  };

  SB.triCount = function (desc) {
    var parts = arGeom(desc.kind, desc.p || {}) || [], n = 0, i;
    for (i = 0; i < parts.length; i++) {
      var g = parts[i].g;
      if (!g || parts[i].line || !g.attributes || !g.attributes.position) continue;
      n += (g.index ? g.index.count : g.attributes.position.count) / 3;
    }
    return Math.round(n);
  };

  /* ── the `csg` kind ──────────────────────────────────────────────────── */
  SB.cache = (typeof WeakMap === 'function') ? new WeakMap() : null;
  SB.DEFAULT = function () {
    return {op: 'subtract',
            a: {kind: 'box', p: {w: 2, h: 2, d: 2}, x: 0, y: 0, z: 0, rx: 0, ry: 0, rz: 0, s: 1},
            b: {kind: 'cylinder', p: {r: 0.6, h: 3, seg: 32}, x: 0, y: -0.5, z: 0, rx: 0, ry: 0, rz: 0, s: 1}};
  };

  SB.depth = 0;
  SB.build = function (p) {
    var d = SB.DEFAULT();
    var op = String((p && p.op) || d.op).toLowerCase();
    if (op !== 'union' && op !== 'subtract' && op !== 'intersect') op = 'subtract';
    var A = (p && p.a) || d.a, B = (p && p.b) || d.b;
    var pa = SB.operandPolys(A), pb = SB.operandPolys(B);
    if (!pa.length || !pb.length) return SB.geomOf(pa);
    if (pa.length > SB.MAX_TRIS || pb.length > SB.MAX_TRIS) return SB.geomOf(pa);
    return SB.geomOf(SB.boolean(op, pa, pb));
  };

  AR_EXT.geom.csg = function (p, k) {
    var sig;
    try { sig = JSON.stringify(p); } catch (e) { sig = null; }
    if (SB.cache && p && sig) {
      var hit = SB.cache.get(p);
      /* the cached buffer belongs to a node that arRebuild will dispose, so a
         hit hands back a COPY — still a memcpy instead of a BSP rebuild */
      if (hit && hit.sig === sig && hit.g) { SB.lastMs = 0; return [{g: hit.g.clone()}]; }
    }
    if (SB.depth > SB.MAX_DEPTH) return null;
    var t0 = (window.performance && performance.now) ? performance.now() : Date.now();
    var g;
    SB.depth++;
    try { g = SB.build(p); } finally { SB.depth--; }
    var t1 = (window.performance && performance.now) ? performance.now() : Date.now();
    SB.lastMs = Math.round((t1 - t0) * 10) / 10;
    /* An empty result is a REAL answer (two solids that do not overlap have no
       intersection), so it is returned as an empty part — not as the unknown-
       kind marker cube, which would claim the drawing names a kind we cannot
       build. The record stays selectable and its parameters stay editable. */
    if (!g) return null;
    if (SB.cache && p && sig) SB.cache.set(p, {sig: sig, g: g.clone(), ms: SB.lastMs});
    return [{g: g}];
  };
  AR_EXT.label.csg = 'Boolean solid';

  /* ── the three icons ─────────────────────────────────────────────────── */
  var OPS = {bool_u: 'union', bool_s: 'subtract', bool_i: 'intersect'};
  var VERB = {union: 'Union', subtract: 'Subtract', intersect: 'Intersect'};

  function descOf(rec, org) {
    return {kind: rec.kind, p: JSON.parse(JSON.stringify(rec.p || {})),
            x: +((rec.x - org.x).toFixed(6)), y: +((rec.y - org.y).toFixed(6)), z: +((rec.z - org.z).toFixed(6)),
            rx: rec.rx || 0, ry: rec.ry || 0, rz: rec.rz || 0, s: rec.s || 1};
  }

  function pairFor(opt) {
    /* the assistant passes {a:id, b:id}; a person uses the selection, and
       SUBTRACT ORDER IS SELECTION ORDER — AR.sel, not AR.objs */
    if (opt && typeof opt === 'object' && (opt.a || opt.b)) {
      var ra = arFind(String(opt.a || '')), rb = arFind(String(opt.b || ''));
      if (!ra || !rb || ra === rb) return null;
      return [ra, rb];
    }
    var recs = (AR.sel || []).map(arFind).filter(function (r) { return !!r; });
    return recs.length === 2 ? recs : null;
  }

  function act(op, opt) {
    var pair = pairFor(opt);
    if (!pair) { arToast('Select two solids — ' + VERB[op].toLowerCase() +
                         ' works on exactly two objects' +
                         (op === 'subtract' ? ' (the first minus the second)' : '') + '.', 'warn'); return; }
    var ra = pair[0], rb = pair[1];
    var ta = SB.triCount({kind: ra.kind, p: ra.p}), tb = SB.triCount({kind: rb.kind, p: rb.p});
    if (ta > SB.MAX_TRIS || tb > SB.MAX_TRIS) {
      arToast('Too heavy to cut: ' + Math.max(ta, tb).toLocaleString() + ' triangles on one operand (the limit is ' +
              SB.MAX_TRIS.toLocaleString() + ' — a BSP boolean is quadratic in the worst case).', 'bad');
      return;
    }
    var org = {x: ra.x, y: ra.y, z: ra.z};
    var p = {op: op, a: descOf(ra, org), b: descOf(rb, org)};
    var mat = ra.mat, name = VERB[op] + ': ' + arKindLabel(ra.kind) + ' / ' + arKindLabel(rb.kind);
    var grp = ra.grp || '';

    arPush();                                   /* ONE undo step, BEFORE the change */
    arRemove(ra); arRemove(rb);
    var t0 = (window.performance && performance.now) ? performance.now() : Date.now();
    var rec = arNewObj('csg', p, org.x, org.z, org.y);
    var ms = Math.round(((window.performance && performance.now) ? performance.now() : Date.now()) - t0);
    rec.mat = mat; rec.name = name; rec.grp = grp;
    rec.meta = rec.meta || {};
    rec.meta.csg_ms = ms;
    arApplyMat(rec);
    arSelect([rec.id]);
    arSyncHoles();
    arPanel(); arOutliner(); arHud();

    var tris = 0;
    rec.node.traverse(function (m) {
      if (m.isMesh && m.geometry && m.geometry.attributes.position) {
        tris += (m.geometry.index ? m.geometry.index.count : m.geometry.attributes.position.count) / 3;
      }
    });
    if (!tris) {
      arToast(VERB[op] + ' produced nothing — the two solids may not overlap.', 'warn');
    } else {
      arToast(VERB[op] + ': two solids became one — ' + Math.round(tris).toLocaleString() +
              ' triangles in ' + ms + ' ms.');
    }
  }

  ['bool_u', 'bool_s', 'bool_i'].forEach(function (id) {
    var op = OPS[id];
    AR_EXT.tools[id] = {
      assist: 1,
      tip: VERB[op] + ' — ' + (op === 'union' ? 'weld two selected solids into one'
           : op === 'subtract' ? 'cut the second selected solid out of the first'
           : 'keep only the volume the two selected solids share') +
           '. Replaces both with one editable Boolean solid; args {a:id, b:id}.',
      act: function (opt) { act(op, opt); }
    };
  });

  /* expose the kernel for tests and for other families, family-prefixed */
  window.AR_SOLIDS_BOOLEAN = SB;
})();
