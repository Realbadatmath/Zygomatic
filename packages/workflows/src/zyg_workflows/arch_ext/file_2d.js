// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* file_2d — File ▸ 2D and BIM interchange (2026-09-08).
   Wires three dock icons that were placeholders: f_dxf (Export DXF),
   f_svg (Export SVG), f_ifc (Export IFC). Nothing in inspection.html was
   edited; the DXF is written here, in the tab, from the records themselves.

   THE ONE IDEA. A DXF is TEXT. There is no library to vendor and no server to
   wait for: the browser already holds the records and the built meshes, so it
   can spell out SECTION/HEADER/TABLES/ENTITIES/EOF itself. What it cannot do
   is put the bytes anywhere this system can see them, so — exactly as file_3d
   does for .glb and .stl — every export is BOTH downloaded to the person AND
   copied to data/architecture/exports/ through arch_server_ext/file_2d.py.
   That copy is what a test opens with ezdxf and what Blender imports.

   THE THREE FORMATS, and why they are not the same job:
     · f_dxf  lines and faces. Written here. 'plan' = the footprint of every
              record as a closed LWPOLYLINE on its kind's layer at the record's
              own elevation (a wall is its rotated rectangle, and each opening
              in it is a second closed polyline on OPENING); guides come out as
              LINE / CIRCLE / ARC and dimensions as LINE + TEXT. '3d' = every
              visible mesh's world triangles as 3DFACE entities.
              DXF R2000 (AC1015) ASCII with $INSUNITS 6 — metres. R12 would be
              the older lingua franca, but LWPOLYLINE is not an R12 entity and
              a reader that is strict about that loses every layer.
     · f_svg  the drawing, not the model. The generator is drawings_2d's
              (window.drawings2d.svg) — this family only makes it a FILE and
              tells you where it landed.
     · f_ifc  building OBJECTS, which a browser cannot make: IFC needs
              ifcopenshell, and the only copy on this machine is inside
              Blender. So the tab POSTs the document and the server runs
              Blender against arch_server_ext/file_2d_ifc.py.

   Frame: DXF X = studio x, DXF Y = -studio z, DXF Z = studio y (up) — the same
   right-handed Z-up frame arch_blender_build uses, so a DXF and a .blend of one
   drawing land on top of each other. */
(function () {
  'use strict';

  var EXT_BASE = '/inspect/api/architecture/ext/file_2d/';
  /* A 3DFACE per triangle is ~200 bytes of text. Past this the file stops being
     something AutoCAD will open and starts being a denial of service on the
     person who asked for it; we stop and say so rather than hang the tab. */
  var F2D_MAX_TRIS = 150000;

  var F2D_LAYERS = [['WALL', 1], ['SLAB', 2], ['COLUMN', 3], ['OPENING', 4],
                    ['ROOF', 5], ['GUIDE', 6], ['ANNOT', 7], ['OTHER', 7]];

  function N(v, d) { var n = parseFloat(v); return isFinite(n) ? n : d; }
  function f2dSlug(s) {
    return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 48) || 'drawing';
  }
  function f2dDocName() { return f2dSlug((window.AR && AR.doc && AR.doc.name) || 'drawing'); }
  function f2dBytes(n) {
    return n < 1024 ? n + ' B' : (n < 1048576 ? (n / 1024).toFixed(1) + ' kB' : (n / 1048576).toFixed(2) + ' MB');
  }
  function f2dStoreyH() { return (window.AR && AR.defaults && N(AR.defaults.wall_h, 2.7)) || 2.7; }

  /* The same icon serves a person and the assistant: an args object answers
     exactly, a click asks. Returns null only when a person cancelled. */
  function f2dOpt(opt, key, dflt, question) {
    if (opt && typeof opt === 'object' && opt[key] !== undefined && opt[key] !== null) return opt[key];
    if (question === undefined) return dflt;
    var a = prompt(question, dflt === undefined || dflt === null ? '' : String(dflt));
    return a === null ? null : a;
  }
  function f2dPost(op, body) {
    return fetch(EXT_BASE + op, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                  body: JSON.stringify(body || {}) })
      .then(function (r) { return r.json(); });
  }

  /* ── which layer a kind belongs on ───────────────────────────────────── */
  function f2dLayerOf(kind) {
    var k = String(kind || '');
    if (k === 'wall' || k === 'partition' || k.indexOf('wall_') === 0) return 'WALL';
    if (k === 'slab' || k === 'floor' || k === 'ceiling' || k.indexOf('slab_') === 0) return 'SLAB';
    if (k === 'column' || k === 'beam' || k === 'footing' || k === 'pile'
        || k.indexOf('column_') === 0 || k.indexOf('beam_') === 0) return 'COLUMN';
    if (k === 'door' || k === 'window' || k === 'opening' || k.indexOf('door_') === 0
        || k.indexOf('window_') === 0 || (window.AR_EXT && AR_EXT.openings && AR_EXT.openings[k])) return 'OPENING';
    if (k === 'roof' || k.indexOf('roof_') === 0) return 'ROOF';
    if (k.indexOf('guide_') === 0) return 'GUIDE';
    if (k.indexOf('dim_') === 0 || k.indexOf('label_') === 0 || k === 'zone') return 'ANNOT';
    return 'OTHER';
  }

  /* ── the DXF writer: group code, then value, one per line ─────────────── */
  function f2dWriter() {
    var out = [], h = 0x100;
    function g(c, v) { out.push(String(c)); out.push(String(v)); }
    function nm(v) { v = parseFloat(v); return (isFinite(v) ? v : 0).toFixed(6); }
    /* R2000 wants a handle on every entity and table record; a duplicate or a
       missing one and ezdxf refuses the file outright. */
    function H() { h += 1; g(5, h.toString(16).toUpperCase()); }
    function ent(type, layer, subclass) {
      g(0, type); H(); g(100, 'AcDbEntity'); g(8, layer || 'OTHER');
      if (subclass) g(100, subclass);
    }
    var W = {
      n: 0,
      header: function () {
        g(0, 'SECTION'); g(2, 'HEADER');
        g(9, '$ACADVER'); g(1, 'AC1015');
        g(9, '$INSUNITS'); g(70, 6);           /* 6 = metres, the studio's one unit */
        g(9, '$HANDSEED'); g(5, 'FFFFFF');
        g(0, 'ENDSEC');
        g(0, 'SECTION'); g(2, 'TABLES');
        g(0, 'TABLE'); g(2, 'LAYER'); H(); g(70, F2D_LAYERS.length);
        F2D_LAYERS.forEach(function (L) {
          g(0, 'LAYER'); H();
          g(100, 'AcDbSymbolTableRecord'); g(100, 'AcDbLayerTableRecord');
          g(2, L[0]); g(70, 0); g(62, L[1]); g(6, 'CONTINUOUS');
        });
        g(0, 'ENDTAB'); g(0, 'ENDSEC');
        g(0, 'SECTION'); g(2, 'ENTITIES');
        return W;
      },
      /* pts = [[x, y], …] already in the DXF frame; elev is the z of the plane */
      poly: function (pts, layer, elev, closed) {
        if (!pts || pts.length < 2) return W;
        ent('LWPOLYLINE', layer, 'AcDbPolyline');
        g(90, pts.length); g(70, closed === false ? 0 : 1); g(38, nm(elev || 0));
        pts.forEach(function (p) { g(10, nm(p[0])); g(20, nm(p[1])); });
        W.n++;
        return W;
      },
      line: function (a, b, layer) {
        ent('LINE', layer, 'AcDbLine');
        g(10, nm(a[0])); g(20, nm(a[1])); g(30, nm(a[2] || 0));
        g(11, nm(b[0])); g(21, nm(b[1])); g(31, nm(b[2] || 0));
        W.n++;
        return W;
      },
      circle: function (c, r, layer) {
        ent('CIRCLE', layer, 'AcDbCircle');
        g(10, nm(c[0])); g(20, nm(c[1])); g(30, nm(c[2] || 0)); g(40, nm(r));
        W.n++;
        return W;
      },
      arc: function (c, r, a0, a1, layer) {
        ent('ARC', layer, 'AcDbCircle');
        g(10, nm(c[0])); g(20, nm(c[1])); g(30, nm(c[2] || 0)); g(40, nm(r));
        g(100, 'AcDbArc'); g(50, nm(a0)); g(51, nm(a1));
        W.n++;
        return W;
      },
      text: function (p, height, s, layer) {
        ent('TEXT', layer, 'AcDbText');
        g(10, nm(p[0])); g(20, nm(p[1])); g(30, nm(p[2] || 0)); g(40, nm(height));
        g(1, String(s == null ? '' : s).replace(/[\r\n]+/g, ' ').slice(0, 250));
        g(100, 'AcDbText');
        W.n++;
        return W;
      },
      face: function (a, b, c, layer) {
        ent('3DFACE', layer, 'AcDbFace');
        g(10, nm(a[0])); g(20, nm(a[1])); g(30, nm(a[2]));
        g(11, nm(b[0])); g(21, nm(b[1])); g(31, nm(b[2]));
        g(12, nm(c[0])); g(22, nm(c[1])); g(32, nm(c[2]));
        g(13, nm(c[0])); g(23, nm(c[1])); g(33, nm(c[2]));   /* 4th vertex = the 3rd: a triangle */
        W.n++;
        return W;
      },
      end: function () { g(0, 'ENDSEC'); g(0, 'EOF'); return out.join('\n') + '\n'; }
    };
    return W;
  }

  /* ── the studio frame -> the DXF frame ────────────────────────────────── */
  /* a point in the record's LOCAL plan frame -> [X, Y] in the DXF's.
     The rotation is drawings_2d's local2view, so the two drawings agree. */
  function f2dL2W(rec, lx, lz) {
    var c = Math.cos(rec.ry || 0), s = Math.sin(rec.ry || 0);
    return [rec.x + lx * c + lz * s, -(rec.z - lx * s + lz * c)];
  }
  function f2dRect(rec, w, d) {
    var hw = w / 2, hd = d / 2;
    return [f2dL2W(rec, -hw, -hd), f2dL2W(rec, hw, -hd), f2dL2W(rec, hw, hd), f2dL2W(rec, -hw, hd)];
  }
  function f2dAabb(rec) {
    var b = new THREE.Box3().setFromObject(rec.node);
    if (!isFinite(b.min.x) || b.isEmpty()) return null;
    return [[b.min.x, -b.max.z], [b.max.x, -b.max.z], [b.max.x, -b.min.z], [b.min.x, -b.min.z]];
  }
  /* The plan footprint of one record: its own parameters when it has them (a
     rotated rectangle is the truth for a wall, an axis-aligned box is not), the
     world bounding box otherwise. */
  function f2dFootprint(rec) {
    var p = rec.p || {}, k = String(rec.kind || '');
    if (k === 'wall' || k === 'partition') return f2dRect(rec, N(p.len, 4), N(p.t, k === 'partition' ? 0.10 : 0.24));
    if (isFinite(p.w) && isFinite(p.d)) return f2dRect(rec, +p.w, +p.d);
    if (isFinite(p.r)) return f2dRect(rec, 2 * p.r, 2 * p.r);
    return f2dAabb(rec);
  }
  function f2dVisible() {
    return (window.AR && AR.objs ? AR.objs : []).filter(function (o) { return o && !o.hidden && o.node; });
  }
  function f2dStoreyOf(rec) { return Math.round(N(rec.y, 0) / f2dStoreyH()); }

  /* ── guides, dimensions, labels: notation, drawn as what it is ────────── */
  function f2dGuide(w, rec) {
    var p = rec.p || {}, y = N(rec.y, 0), i;
    if (rec.kind === 'guide_poly' || rec.kind === 'guide_path') {
      var pts = Array.isArray(p.pts) ? p.pts : [];
      if (pts.length < 2) return 0;
      var v = pts.map(function (q) { return f2dL2W(rec, N(q[0], 0), N(q[1], 0)); });
      for (i = 0; i + 1 < v.length; i++) w.line([v[i][0], v[i][1], y], [v[i + 1][0], v[i + 1][1], y], 'GUIDE');
      if (rec.kind === 'guide_poly') w.line([v[v.length - 1][0], v[v.length - 1][1], y], [v[0][0], v[0][1], y], 'GUIDE');
      return v.length;
    }
    if (rec.kind === 'guide_arc') {
      /* three points through the arc -> the circle they share; collinear points
         have no circle, and then the honest entity is the chord. */
      var a = f2dL2W(rec, N(p.x1, 0), N(p.z1, 0)), b = f2dL2W(rec, N(p.x2, 0), N(p.z2, 0)),
          c = f2dL2W(rec, N(p.x3, 0), N(p.z3, 0));
      var dd = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]));
      if (Math.abs(dd) < 1e-9) { w.line([a[0], a[1], y], [b[0], b[1], y], 'GUIDE'); return 1; }
      var ux = ((a[0] * a[0] + a[1] * a[1]) * (b[1] - c[1]) + (b[0] * b[0] + b[1] * b[1]) * (c[1] - a[1])
                + (c[0] * c[0] + c[1] * c[1]) * (a[1] - b[1])) / dd;
      var uz = ((a[0] * a[0] + a[1] * a[1]) * (c[0] - b[0]) + (b[0] * b[0] + b[1] * b[1]) * (a[0] - c[0])
                + (c[0] * c[0] + c[1] * c[1]) * (b[0] - a[0])) / dd;
      var r = Math.hypot(a[0] - ux, a[1] - uz), D = 180 / Math.PI;
      var t0 = Math.atan2(a[1] - uz, a[0] - ux) * D, t2 = Math.atan2(c[1] - uz, c[0] - ux) * D;
      var t1 = Math.atan2(b[1] - uz, b[0] - ux) * D;
      /* DXF arcs always run counter-clockwise from 50 to 51: order the ends so
         the middle point is inside the sweep. */
      function inside(s, e, m) { var S = ((e - s) % 360 + 360) % 360, M = ((m - s) % 360 + 360) % 360; return M <= S; }
      if (inside(t0, t2, t1)) w.arc([ux, uz, y], r, t0, t2, 'GUIDE');
      else w.arc([ux, uz, y], r, t2, t0, 'GUIDE');
      return 1;
    }
    return 0;
  }
  function f2dAnnoText(rec, dflt) {
    var p = rec.p || {};
    if (p.txt != null && String(p.txt) !== '') return String(p.txt);
    if (typeof window.measure_annotations_label === 'function') {
      try { return window.measure_annotations_label(rec); } catch (e) { /* fall through */ }
    }
    return dflt;
  }
  function f2dAnnotation(w, rec) {
    var p = rec.p || {}, y = N(rec.y, 0), k = String(rec.kind || ''), i;
    if (k === 'dim_linear') {
      var x2 = N(p.x2, 5), z2 = N(p.z2, 0), off = N(p.off, 0.6);
      var L = Math.hypot(x2, z2) || 1e-6, ux = x2 / L, uz = z2 / L;
      var ox = -uz * off, oz = ux * off, e = 1.12;
      var a = f2dL2W(rec, ox, oz), b = f2dL2W(rec, x2 + ox, z2 + oz);
      w.line([a[0], a[1], y], [b[0], b[1], y], 'ANNOT');                                   /* the dimension line */
      var s0 = f2dL2W(rec, 0, 0), s1 = f2dL2W(rec, ox * e, oz * e);
      var e0 = f2dL2W(rec, x2, z2), e1 = f2dL2W(rec, x2 + ox * e, z2 + oz * e);
      w.line([s0[0], s0[1], y], [s1[0], s1[1], y], 'ANNOT');                               /* extension lines */
      w.line([e0[0], e0[1], y], [e1[0], e1[1], y], 'ANNOT');
      w.text([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 0.06, y], 0.25,
             f2dAnnoText(rec, L.toFixed(2) + ' m'), 'ANNOT');
      return 4;
    }
    if (k === 'dim_angle') {
      var x1 = N(p.x1, 1), z1 = N(p.z1, 0), X2 = N(p.x2, 0), Z2 = N(p.z2, -1), r = Math.max(0.05, N(p.r, 1));
      var o = f2dL2W(rec, 0, 0), r1 = f2dL2W(rec, x1, z1), r2 = f2dL2W(rec, X2, Z2);
      w.line([o[0], o[1], y], [r1[0], r1[1], y], 'ANNOT');
      w.line([o[0], o[1], y], [r2[0], r2[1], y], 'ANNOT');
      var a1 = Math.atan2(z1, x1), a2 = Math.atan2(Z2, X2), dv = a2 - a1, arcp = [];
      while (dv > Math.PI) dv -= 2 * Math.PI;
      while (dv < -Math.PI) dv += 2 * Math.PI;
      for (i = 0; i <= 24; i++) {
        var t = a1 + dv * (i / 24);
        arcp.push(f2dL2W(rec, Math.cos(t) * r, Math.sin(t) * r));
      }
      w.poly(arcp, 'ANNOT', y, false);
      var mid = f2dL2W(rec, Math.cos(a1 + dv / 2) * r * 1.3, Math.sin(a1 + dv / 2) * r * 1.3);
      w.text([mid[0], mid[1], y], 0.25, f2dAnnoText(rec, (Math.abs(dv) * 180 / Math.PI).toFixed(0) + '\u00b0'), 'ANNOT');
      return 5;
    }
    if (k === 'label_text') {
      var sz = Math.max(0.05, N(p.size, 0.35)), c0 = f2dL2W(rec, -sz / 2, 0), c1 = f2dL2W(rec, sz / 2, 0);
      var c2 = f2dL2W(rec, 0, -sz / 2), c3 = f2dL2W(rec, 0, sz / 2), at = f2dL2W(rec, 0, 0);
      w.line([c0[0], c0[1], y], [c1[0], c1[1], y], 'ANNOT');
      w.line([c2[0], c2[1], y], [c3[0], c3[1], y], 'ANNOT');
      w.text([at[0], at[1] + sz * 0.6, y], Math.max(0.1, sz), f2dAnnoText(rec, rec.name || ''), 'ANNOT');
      return 3;
    }
    return 0;
  }

  /* ── the plan DXF ─────────────────────────────────────────────────────── */
  function f2dPlanDxf(storey) {
    var w = f2dWriter().header(), stats = { records: 0, walls: 0, openings: 0, guides: 0, annot: 0, skipped: 0 };
    f2dVisible().forEach(function (rec) {
      if (storey !== null && f2dStoreyOf(rec) !== storey) { stats.skipped++; return; }
      var k = String(rec.kind || ''), y = N(rec.y, 0);
      if (k.indexOf('guide_') === 0) { if (f2dGuide(w, rec)) { stats.guides++; stats.records++; } return; }
      if (k.indexOf('dim_') === 0 || k === 'label_text') {
        if (f2dAnnotation(w, rec)) { stats.annot++; stats.records++; }
        return;
      }
      var pts = f2dFootprint(rec);
      if (!pts) { stats.skipped++; return; }
      w.poly(pts, f2dLayerOf(k), y, true);
      stats.records++;
      if (k === 'wall' || k === 'partition') {
        stats.walls++;
        /* each opening cut into the wall, as its own closed polyline on OPENING
           — the hole is where a door schedule and a setting-out drawing both
           look, so it cannot be implied by the wall outline. */
        var p = rec.p || {}, L = N(p.len, 4), t = N(p.t, k === 'partition' ? 0.10 : 0.24);
        (Array.isArray(p.holes) ? p.holes : []).forEach(function (ho) {
          if (!ho || typeof ho !== 'object') return;
          var hw = N(ho.w, 0);
          if (hw <= 0) return;
          var a = Math.max(-L / 2, -L / 2 + N(ho.u, 0) - hw / 2), b = Math.min(L / 2, -L / 2 + N(ho.u, 0) + hw / 2);
          if (b <= a) return;
          w.poly([f2dL2W(rec, a, -t / 2), f2dL2W(rec, b, -t / 2), f2dL2W(rec, b, t / 2), f2dL2W(rec, a, t / 2)],
                 'OPENING', y, true);
          stats.openings++;
        });
      }
    });
    stats.entities = w.n;
    return { text: w.end(), stats: stats };
  }

  /* ── the 3D DXF: every visible mesh's world triangles as 3DFACE ───────── */
  function f2dSolidDxf() {
    var w = f2dWriter().header(), stats = { records: 0, meshes: 0, tris: 0, capped: false };
    var A = new THREE.Vector3(), B = new THREE.Vector3(), C = new THREE.Vector3();
    var recs = f2dVisible().filter(function (o) {
      var k = String(o.kind || '');
      return k.indexOf('guide_') !== 0 && k.indexOf('dim_') !== 0 && k !== 'label_text' && k !== 'opening';
    });
    for (var ri = 0; ri < recs.length && !stats.capped; ri++) {
      var rec = recs[ri], layer = f2dLayerOf(rec.kind), any = false;
      rec.node.updateMatrixWorld(true);
      var meshes = [];
      rec.node.traverse(function (m) { if (m.isMesh && m.geometry && m.visible) meshes.push(m); });
      for (var mi = 0; mi < meshes.length && !stats.capped; mi++) {
        var m = meshes[mi], g = m.geometry, pos = g.attributes && g.attributes.position;
        if (!pos) continue;
        var idx = g.index, count = idx ? idx.count : pos.count;
        stats.meshes++;
        any = true;
        for (var i = 0; i + 2 < count; i += 3) {
          if (stats.tris >= F2D_MAX_TRIS) { stats.capped = true; break; }
          var ia = idx ? idx.getX(i) : i, ib = idx ? idx.getX(i + 1) : i + 1, ic = idx ? idx.getX(i + 2) : i + 2;
          A.fromBufferAttribute(pos, ia).applyMatrix4(m.matrixWorld);
          B.fromBufferAttribute(pos, ib).applyMatrix4(m.matrixWorld);
          C.fromBufferAttribute(pos, ic).applyMatrix4(m.matrixWorld);
          w.face([A.x, -A.z, A.y], [B.x, -B.z, B.y], [C.x, -C.z, C.y], layer);
          stats.tris++;
        }
      }
      if (any) stats.records++;
    }
    stats.entities = w.n;
    return { text: w.end(), stats: stats };
  }

  /* ── download AND keep a server copy. Both, always ────────────────────── */
  function f2dDeliver(text, ext, base, mime) {
    var fname = base + '.' + ext;
    arDownload(new Blob([text], { type: mime }), fname);
    return f2dPost('save', { name: base, ext: ext, text: text })
      .then(function (r) { return r || {}; })
      .catch(function (e) { return { error: String((e && e.message) || e) }; });
  }

  /* ── f_dxf ────────────────────────────────────────────────────────────── */
  function f2dExportDxf(opt) {
    var what = f2dOpt(opt, 'what', 'plan', 'Export the plan footprints or the 3D mesh? plan / 3d');
    if (what === null) return Promise.resolve(null);
    what = String(what).trim().toLowerCase() === '3d' ? '3d' : 'plan';
    var storey = null;
    if (what === 'plan') {
      var sv = f2dOpt(opt, 'storey', '', 'Which storey? (0 = ground; blank = every storey)');
      if (sv === null) return Promise.resolve(null);
      if (String(sv).trim() !== '') storey = Math.round(N(sv, 0));
    }
    if (!f2dVisible().length) {
      arToast('Nothing visible to export \u2014 the drawing is empty or everything is hidden.', 'warn');
      return Promise.resolve(null);
    }
    var built = what === '3d' ? f2dSolidDxf() : f2dPlanDxf(storey);
    var s = built.stats;
    if (!s.entities) {
      arToast('Nothing landed on that storey \u2014 no DXF was written.', 'warn');
      return Promise.resolve(null);
    }
    var base = f2dSlug(f2dOpt(opt, 'name', f2dDocName())) + (what === '3d' ? '-3d' : '-plan')
             + (storey === null ? '' : '-l' + storey);
    var pending = f2dDeliver(built.text, 'dxf', base, 'image/vnd.dxf').then(function (r) {
      var what_txt = what === '3d'
        ? (s.tris.toLocaleString() + ' triangles as 3DFACE from ' + s.records + ' object'
           + (s.records === 1 ? '' : 's') + (s.capped ? ' (capped at ' + F2D_MAX_TRIS.toLocaleString() + ')' : ''))
        : (s.records + ' footprint' + (s.records === 1 ? '' : 's') + ', ' + s.walls + ' wall'
           + (s.walls === 1 ? '' : 's') + ', ' + s.openings + ' opening' + (s.openings === 1 ? '' : 's')
           + ', ' + s.guides + ' guide' + (s.guides === 1 ? '' : 's') + ', ' + s.annot + ' annotation'
           + (s.annot === 1 ? '' : 's'));
      if (r && r.ok) {
        arToast('DXF (' + what + ', R2000, metres): ' + what_txt + ' \u2014 downloaded <b>' + esc(base + '.dxf')
                + '</b> (' + f2dBytes(r.bytes) + ') and kept a copy at <code>' + esc(r.rel) + '</code>.');
      } else {
        arToast('DXF (' + what + '): ' + what_txt + ' \u2014 downloaded <b>' + esc(base + '.dxf')
                + '</b>, but the server copy failed: ' + esc((r && r.error) || 'no answer') + '.', 'warn');
      }
      return { ok: true, what: what, storey: storey, stats: s, save: r || {},
               path: (r && r.path) || '', bytes: (r && r.bytes) || built.text.length };
    });
    AR_EXT.tools.f_dxf._pending = pending;
    return pending;
  }

  /* ── f_svg ────────────────────────────────────────────────────────────── */
  /* the sheet's clipboard button; the SVG never leaves the tab for this */
  window.file2dCopySvg = function () {
    var s = (window.drawings2d && drawings2d.last && drawings2d.last.svg) || '';
    if (!s) { arToast('No drawing to copy \u2014 make one first.', 'warn'); return; }
    var done = function () { arToast('The SVG source is on the clipboard (' + f2dBytes(s.length) + ').'); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(s).then(done, function () { file2dCopyFallback(s, done); });
    } else { file2dCopyFallback(s, done); }
  };
  window.file2dCopyFallback = function (s, done) {
    var ta = document.createElement('textarea');
    ta.value = s; ta.style.position = 'fixed'; ta.style.left = '-9999px';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); done(); } catch (e) { arToast('Could not reach the clipboard.', 'bad'); }
    document.body.removeChild(ta);
  };

  function f2dExportSvg(opt) {
    if (!window.drawings2d || typeof drawings2d.svg !== 'function') {
      arToast('The 2D drawing generator (drawings_2d) is not loaded \u2014 no SVG to export.', 'bad');
      return Promise.resolve(null);
    }
    var kind = f2dOpt(opt, 'kind', 'plan', 'Export which drawing? plan, elevation or section');
    if (kind === null) return Promise.resolve(null);
    kind = String(kind).trim().toLowerCase();
    if (['plan', 'elevation', 'elev', 'section', 'sect'].indexOf(kind) < 0) kind = 'plan';
    var o = {};
    if (opt && typeof opt === 'object') {
      if (opt.storey !== undefined && opt.storey !== null) o.storey = Math.round(N(opt.storey, 0));
      if (opt.elev) o.elev = String(opt.elev);
      if (opt.dir) o.dir = String(opt.dir);
      if (opt.x !== undefined && opt.x !== null) o.x = N(opt.x, 0);
      if (opt.z !== undefined && opt.z !== null) o.z = N(opt.z, 0);
    }
    var res;
    try { res = drawings2d.svg(kind, o); } catch (e) {
      arToast('The drawing generator failed: ' + esc((e && e.message) || e), 'bad');
      return Promise.resolve({ error: String((e && e.message) || e) });
    }
    if (!res || !res.svg) { arToast('The drawing generator returned nothing.', 'bad'); return Promise.resolve(null); }
    var base = f2dSlug(f2dOpt(opt, 'name', f2dDocName() + '-' + (res.title || kind)));
    var pending = f2dDeliver(res.svg, 'svg', base, 'image/svg+xml').then(function (r) {
      var b = res.bounds || {};
      arSheet(res.title || ('SVG \u2014 ' + kind),
        '<div style="max-height:46vh;overflow:auto;background:#fff;padding:6px;border-radius:4px">' + res.svg + '</div>'
        + arRows([['drawing', kind],
                  ['scale', '1:' + res.scale],
                  ['sheet', N(res.w_mm, 0).toFixed(1) + ' \u00d7 ' + N(res.h_mm, 0).toFixed(1) + ' mm'],
                  ['extent', (N(b.maxx, 0) - N(b.minx, 0)).toFixed(2) + ' \u00d7 '
                             + (N(b.maxy, 0) - N(b.miny, 0)).toFixed(2) + ' m'],
                  ['downloaded', esc(base + '.svg')],
                  ['server copy', r && r.ok ? '<code>' + esc(r.rel) + '</code> (' + f2dBytes(r.bytes) + ')'
                                            : '<b>failed</b>: ' + esc((r && r.error) || 'no answer')]])
        + '<div style="margin-top:8px"><button onclick="file2dCopySvg()">Copy SVG to clipboard</button></div>');
      if (r && r.ok) arToast('SVG: downloaded <b>' + esc(base + '.svg') + '</b> and kept a copy at <code>'
                             + esc(r.rel) + '</code>.');
      else arToast('SVG downloaded, but the server copy failed: ' + esc((r && r.error) || 'no answer') + '.', 'warn');
      return { ok: true, kind: kind, title: res.title, scale: res.scale, chars: res.svg.length,
               path: (r && r.path) || '', rel: (r && r.rel) || '', save: r || {} };
    });
    AR_EXT.tools.f_svg._pending = pending;
    return pending;
  }

  /* ── f_ifc ────────────────────────────────────────────────────────────── */
  function f2dExportIfc(opt) {
    var schema = String(f2dOpt(opt, 'schema', 'IFC4') || 'IFC4').trim().toUpperCase();
    if (['IFC4', 'IFC2X3', 'IFC4X3'].indexOf(schema) < 0) schema = 'IFC4';
    var doc = arDocOut();
    if (!doc || !(doc.objects || []).length) {
      arToast('Nothing to export \u2014 the drawing is empty.', 'warn');
      return Promise.resolve(null);
    }
    arToast('Building the IFC in Blender \u2014 ' + doc.objects.length + ' record'
            + (doc.objects.length === 1 ? '' : 's') + ', this takes a few seconds\u2026');
    var pending = f2dPost('ifc', { doc: doc, name: (AR.doc && AR.doc.name) || 'drawing', schema: schema })
      .then(function (r) {
        if (!r || !r.ok) {
          arToast('IFC export failed: ' + esc((r && r.error) || 'no answer') + '.', 'bad');
          return r || { error: 'no answer' };
        }
        var by = Object.keys(r.by_class || {}).sort().map(function (k) {
          return k + ' \u00d7 ' + r.by_class[k];
        }).join(', ');
        arToast('IFC (' + esc(r.schema) + '): <b>' + r.elements + '</b> building element'
                + (r.elements === 1 ? '' : 's') + ' on ' + r.storeys + ' storey' + (r.storeys === 1 ? '' : 's')
                + (by ? ' \u2014 ' + esc(by) : '') + ' \u2014 written to <code>' + esc(r.rel) + '</code> ('
                + f2dBytes(r.bytes) + ').');
        /* the file was made on the server, so the download is a fetch back */
        return fetch(EXT_BASE + 'file?path=' + encodeURIComponent(r.path))
          .then(function (resp) { return resp.ok ? resp.blob() : null; })
          .then(function (blob) { if (blob) arDownload(blob, r.name); return r; })
          .catch(function () { return r; });
      })
      .catch(function (e) {
        arToast('IFC export failed: ' + esc((e && e.message) || e), 'bad');
        return { error: String((e && e.message) || e) };
      });
    AR_EXT.tools.f_ifc._pending = pending;
    return pending;
  }

  /* ── registrations ────────────────────────────────────────────────────── */
  AR_EXT.tools.f_dxf = {
    assist: 1,
    tip: 'Export plans and sections as DXF, for whoever is still in AutoCAD \u2014 R2000 ASCII in metres, '
       + 'one layer per kind; {what:"plan"} writes footprints, walls and their openings, guides and dimensions, '
       + '{what:"3d"} writes every visible mesh as 3DFACE. Downloads it and keeps a copy under data/architecture/exports/',
    act: function (opt) { return f2dExportDxf(opt); }
  };
  AR_EXT.tools.f_svg = {
    assist: 1,
    tip: 'Export the current drawing as vector SVG lines instead of pixels \u2014 the plan, elevation or section '
       + 'that Drawings makes, saved as a file: it downloads, a copy is kept under data/architecture/exports/, '
       + 'and the sheet has a Copy to clipboard button',
    act: function (opt) { return f2dExportSvg(opt); }
  };
  AR_EXT.tools.f_ifc = {
    assist: 1,
    tip: 'Export IFC \u2014 the drawing as building objects, which is what a consultant will ask for: walls, slabs, '
       + 'columns, doors and windows on real building storeys, built in Blender with ifcopenshell and written '
       + 'under data/architecture/exports/',
    act: function (opt) { return f2dExportIfc(opt); }
  };
})();
