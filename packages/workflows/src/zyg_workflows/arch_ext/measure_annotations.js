// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* measure_annotations — Measure ▸ Dimension (dim), Protractor (angle) and
   Label (text) as real annotation RECORDS that stay on the drawing (2026-09-07).

   Three pointer modes, three new kinds, and the one thing a drawing needs that
   a BufferGeometry cannot carry: TEXT. A part is a geometry, so the numbers and
   the notes are THREE.Sprites (CanvasTexture: white text on a dark rounded
   pill) kept in a map beside the records and synced by an AR_EXT.ticks hook —
   created when a record of ours appears, redrawn only when its text changes,
   moved with the record, and removed when the record is gone. They are added to
   AR.scene, never to rec.node: arDisposeNode would dispose the texture with the
   lines and the drawing would go blank of numbers on the next rebuild.

   Kinds (parameters only — never geometry):
     dim_linear  p {x2, z2, off, txt}   value = hypot(x2, z2) metres
     dim_angle   p {x1, z1, x2, z2, r}  value = the angle between the two rays, degrees
     label_text  p {txt, size}          the note itself
   All three are VOID in Blender (arch_blender_ext/measure_annotations.py):
   a dimension is a statement about the building, not part of it. */
(function () {
  var KIND = {dim_linear: 1, dim_angle: 1, label_text: 1};
  var SPR = {};                       /* rec.id -> THREE.Sprite, ours alone */
  var PX = 64;                        /* canvas pixels per line of text */
  var Y = 0.02;                       /* annotation lines float just off the plane */

  function num(v, d) { v = parseFloat(v); return isFinite(v) ? v : d; }
  function r3(v) { return Math.round(v * 1000) / 1000; }

  /* ── the value each kind measures ─────────────────────────────────────── */
  function value(rec) {
    var p = (rec && rec.p) || {};
    if (rec.kind === 'dim_linear') return Math.hypot(num(p.x2, 0), num(p.z2, 0));
    if (rec.kind === 'dim_angle') {
      var a1 = Math.atan2(num(p.z1, 0), num(p.x1, 1));
      var a2 = Math.atan2(num(p.z2, 0), num(p.x2, 1));
      var d = a2 - a1;
      while (d > Math.PI) d -= 2 * Math.PI;
      while (d < -Math.PI) d += 2 * Math.PI;
      return Math.abs(d) * 180 / Math.PI;
    }
    return 0;
  }
  function label(rec) {
    var p = (rec && rec.p) || {};
    if (rec.kind === 'label_text') return String(p.txt === undefined || p.txt === null ? '' : p.txt);
    if (p.txt) return String(p.txt);                        /* an operator's override wins */
    if (rec.kind === 'dim_linear') return arFmt(value(rec)) + ' m';
    return arFmt(value(rec)) + '\u00b0';
  }
  window.measure_annotations_value = value;
  window.measure_annotations_label = label;

  /* ── geometry: line parts, like a real drawing ────────────────────────── */
  function seg(T, pts) { return new T.BufferGeometry().setFromPoints(pts); }

  AR_EXT.geom.dim_linear = function (p, k) {
    var T = k.THREE, x2 = k.num(p.x2, 5), z2 = k.num(p.z2, 0), off = k.num(p.off, 0.6);
    var L = Math.hypot(x2, z2) || 1e-6, ux = x2 / L, uz = z2 / L;
    var nx = -uz, nz = ux;                                  /* left perpendicular on the plan */
    var ox = nx * off, oz = nz * off;
    var V = function (x, z) { return new T.Vector3(x, Y, z); };
    /* extension lines run a little PAST the dimension line, as a drafter draws them */
    var e = 1.12;
    var tk = 0.15 / 2, tx = ux + nx, tz = uz + nz, tn = Math.hypot(tx, tz) || 1;
    tx /= tn; tz /= tn;                                     /* the 45 degree tick direction */
    return [
      {g: seg(T, [V(ox, oz), V(x2 + ox, z2 + oz)]), line: 1},                       /* the dimension line */
      {g: seg(T, [V(0, 0), V(ox * e, oz * e)]), line: 1},                           /* extension line, start */
      {g: seg(T, [V(x2, z2), V(x2 + ox * e, z2 + oz * e)]), line: 1},               /* extension line, end */
      {g: seg(T, [V(ox - tx * tk, oz - tz * tk), V(ox + tx * tk, oz + tz * tk)]), line: 1},
      {g: seg(T, [V(x2 + ox - tx * tk, z2 + oz - tz * tk), V(x2 + ox + tx * tk, z2 + oz + tz * tk)]), line: 1}
    ];
  };

  AR_EXT.geom.dim_angle = function (p, k) {
    var T = k.THREE, x1 = k.num(p.x1, 1), z1 = k.num(p.z1, 0), x2 = k.num(p.x2, 0), z2 = k.num(p.z2, -1);
    var r = Math.max(0.05, k.num(p.r, 1));
    var V = function (x, z) { return new T.Vector3(x, Y, z); };
    var a1 = Math.atan2(z1, x1), a2 = Math.atan2(z2, x2), d = a2 - a1;
    while (d > Math.PI) d -= 2 * Math.PI;
    while (d < -Math.PI) d += 2 * Math.PI;
    var pts = [], SEG = 24;
    for (var i = 0; i < SEG; i++) {
      var t0 = a1 + d * (i / SEG), t1 = a1 + d * ((i + 1) / SEG);
      pts.push(V(Math.cos(t0) * r, Math.sin(t0) * r), V(Math.cos(t1) * r, Math.sin(t1) * r));
    }
    return [
      {g: seg(T, [V(0, 0), V(x1, z1)]), line: 1},           /* the two rays */
      {g: seg(T, [V(0, 0), V(x2, z2)]), line: 1},
      {g: seg(T, pts), line: 1}                             /* the arc between them, 24 segments */
    ];
  };

  AR_EXT.geom.label_text = function (p, k) {
    var T = k.THREE, s = Math.max(0.05, k.num(p.size, 0.35));
    /* a small leader: a cross on the point the note is about, and a stub up to
       the sprite that floats 0.02 m above it */
    return [{g: seg(T, [new T.Vector3(-s / 2, 0.001, 0), new T.Vector3(s / 2, 0.001, 0),
                        new T.Vector3(0, 0.001, -s / 2), new T.Vector3(0, 0.001, s / 2),
                        new T.Vector3(0, 0, 0), new T.Vector3(0, Y, 0)]), line: 1}];
  };

  AR_EXT.label.dim_linear = 'Dimension';
  AR_EXT.label.dim_angle = 'Angle';
  AR_EXT.label.label_text = 'Label';

  /* ── the text sprites ─────────────────────────────────────────────────── */
  function pill(g, x, y, w, h, r) {
    g.beginPath();
    g.moveTo(x + r, y);
    g.lineTo(x + w - r, y); g.quadraticCurveTo(x + w, y, x + w, y + r);
    g.lineTo(x + w, y + h - r); g.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    g.lineTo(x + r, y + h); g.quadraticCurveTo(x, y + h, x, y + h - r);
    g.lineTo(x, y + r); g.quadraticCurveTo(x, y, x + r, y);
    g.closePath();
  }
  function canvasFor(txt) {
    var lines = String(txt === undefined || txt === null ? '' : txt).split('\n');
    if (!lines.length) lines = [''];
    var font = '600 ' + Math.round(PX * 0.62) + 'px system-ui, "Segoe UI", Arial, sans-serif';
    var c = document.createElement('canvas'), g = c.getContext('2d');
    g.font = font;
    var w = 8;
    for (var i = 0; i < lines.length; i++) w = Math.max(w, g.measureText(lines[i]).width);
    var padX = Math.round(PX * 0.42), padY = Math.round(PX * 0.16);
    c.width = Math.ceil(w) + padX * 2;
    c.height = lines.length * PX + padY * 2;
    g = c.getContext('2d');                                 /* resizing cleared the state */
    g.font = font; g.textBaseline = 'middle'; g.textAlign = 'center';
    g.fillStyle = 'rgba(12,18,24,0.86)';
    pill(g, 1, 1, c.width - 2, c.height - 2, Math.min((c.height - 2) / 2, PX * 0.42));
    g.fill();
    g.strokeStyle = 'rgba(0,229,255,0.8)'; g.lineWidth = 2; g.stroke();
    g.fillStyle = '#ffffff';
    for (var j = 0; j < lines.length; j++) g.fillText(lines[j], c.width / 2, padY + PX * (j + 0.5));
    return c;
  }
  function texFor(txt) {
    var t = new THREE.CanvasTexture(canvasFor(txt));
    t.minFilter = THREE.LinearFilter;
    t.needsUpdate = true;
    return t;
  }
  function makeSprite(rec) {
    var txt = label(rec);
    var m = new THREE.SpriteMaterial({map: texFor(txt), transparent: true, depthTest: false,
                                      depthWrite: false, sizeAttenuation: true});
    var sp = new THREE.Sprite(m);
    sp.renderOrder = 10;
    sp.userData.arAnnId = rec.id;          /* the sprite names the record it belongs to */
    sp.userData.arAnnKind = rec.kind;
    sp.userData.arAnnText = txt;
    AR.scene.add(sp);
    SPR[rec.id] = sp;
    return sp;
  }
  function dropSprite(id) {
    var sp = SPR[id];
    if (!sp) return;
    if (sp.parent) sp.parent.remove(sp);
    if (sp.material) {
      if (sp.material.map) sp.material.map.dispose();
      sp.material.dispose();
    }
    delete SPR[id];
  }
  /* the sprite's world position: the record's own point, 0.02 m up, plus (for a
     dimension) the midpoint of the offset dimension line, in the record's frame */
  function place(sp, rec) {
    var lx = 0, lz = 0, p = rec.p || {};
    if (rec.kind === 'dim_linear') {
      var x2 = num(p.x2, 0), z2 = num(p.z2, 0), off = num(p.off, 0.6);
      var L = Math.hypot(x2, z2) || 1e-6;
      lx = x2 / 2 + (-z2 / L) * off;
      lz = z2 / 2 + (x2 / L) * off;
    }
    var s = rec.s || 1, a = rec.ry || 0, c = Math.cos(a), si = Math.sin(a);
    sp.position.set(rec.x + (lx * c + lz * si) * s, (rec.y || 0) + Y, rec.z + (-lx * si + lz * c) * s);
  }
  function sizeUp(sp, rec) {
    var h = Math.max(0.05, num((rec.p || {}).size, 0.35)) * (rec.s || 1);
    var im = sp.material.map && sp.material.map.image;
    var ar = im && im.height ? im.width / im.height : 3;
    sp.scale.set(h * ar, h, 1);
  }

  AR_EXT.ticks.push(function () {
    if (!AR.scene || !AR.objs) return;
    var live = {}, i, rec, sp;
    for (i = 0; i < AR.objs.length; i++) {
      rec = AR.objs[i];
      if (!KIND[rec.kind]) continue;
      live[rec.id] = 1;
      sp = SPR[rec.id] || makeSprite(rec);
      var txt = label(rec);
      if (sp.userData.arAnnText !== txt) {                  /* redraw only on a real change */
        sp.userData.arAnnText = txt;
        if (sp.material.map) sp.material.map.dispose();
        sp.material.map = texFor(txt);
        sp.material.needsUpdate = true;
      }
      sizeUp(sp, rec);
      place(sp, rec);
      sp.visible = !rec.hidden;
    }
    for (var id in SPR) if (!live[id]) dropSprite(id);      /* the record is gone: so is its text */
  });

  /* ── the three pointer modes ──────────────────────────────────────────── */
  var S = {dim: null, angle: null};

  function P3(P) { return {x: P.x, z: P.z, y: P.y}; }
  function rubber(a, b) {
    if (!AR.rubber) return;
    AR.rubber.geometry.setFromPoints([new THREE.Vector3(a.x, a.y + 0.01, a.z),
                                      new THREE.Vector3(b.x, a.y + 0.01, b.z)]);
    AR.rubber.visible = true;
  }
  function land(rec, what) {
    arSelect([rec.id]);
    arPanel();
    arOutliner();
    arToast(what);
  }

  AR_EXT.modes.dim = {
    tip: 'Dimension — click two points; the measurement stays on the drawing as an object you can move, edit and delete',
    click: function (P) {
      if (!P) return;
      if (!S.dim) { S.dim = P3(P); arHint(this.hint()); return; }
      var a = S.dim, dx = P.x - a.x, dz = P.z - a.z, L = Math.hypot(dx, dz);
      if (L < 1e-4) { arToast('A dimension needs two different points.', 'warn'); return; }
      arPush();
      var rec = arNewObj('dim_linear', {x2: r3(dx), z2: r3(dz), off: 0.6, txt: ''}, a.x, a.z, a.y);
      rec.name = 'Dimension ' + arFmt(L) + ' m';
      S.dim = null;
      if (AR.rubber) AR.rubber.visible = false;
      land(rec, 'Dimension <b>' + arFmt(L) + ' m</b> added.');
      arHint(this.hint());
    },
    move: function (P) {
      if (!S.dim || !P) { if (!S.dim && AR.rubber) AR.rubber.visible = false; return; }
      rubber(S.dim, P);
      arHint('<b>' + Math.hypot(P.x - S.dim.x, P.z - S.dim.z).toFixed(3) + ' m</b> — click the second point.');
    },
    hint: function () { return S.dim ? 'Click the second point of the dimension.' : 'Click the first point of the dimension.'; },
    cancel: function () { S.dim = null; }
  };

  AR_EXT.modes.angle = {
    tip: 'Protractor — click the vertex then two points; the angle stays on the drawing as an object',
    click: function (P) {
      if (!P) return;
      if (!S.angle) { S.angle = {v: P3(P), a: null}; arHint(this.hint()); return; }
      if (!S.angle.a) { S.angle.a = P3(P); arHint(this.hint()); return; }
      var v = S.angle.v, A = S.angle.a;
      var x1 = A.x - v.x, z1 = A.z - v.z, x2 = P.x - v.x, z2 = P.z - v.z;
      if (Math.hypot(x1, z1) < 1e-4 || Math.hypot(x2, z2) < 1e-4) {
        arToast('The two arms must not sit on the vertex.', 'warn'); return;
      }
      arPush();
      var rec = arNewObj('dim_angle', {x1: r3(x1), z1: r3(z1), x2: r3(x2), z2: r3(z2), r: 1.0}, v.x, v.z, v.y);
      rec.name = 'Angle ' + arFmt(value(rec)) + '\u00b0';
      S.angle = null;
      if (AR.rubber) AR.rubber.visible = false;
      land(rec, 'Angle <b>' + arFmt(value(rec)) + '&deg;</b> added.');
      arHint(this.hint());
    },
    move: function (P) {
      if (!S.angle || !P) { if (!S.angle && AR.rubber) AR.rubber.visible = false; return; }
      rubber(S.angle.a || S.angle.v, P);
    },
    hint: function () {
      if (!S.angle) return 'Click the vertex of the angle.';
      return S.angle.a ? 'Click the second arm.' : 'Click the first arm.';
    },
    cancel: function () { S.angle = null; }
  };

  AR_EXT.modes.text = {
    tip: 'Label — click a point and type the note; it stays on the drawing, pinned to that point',
    /* a person is asked; the assistant (or a test) passes the note on the event
       object as `text`, so the same code path serves both */
    click: function (P, e) {
      if (!P) return;
      var txt = (e && typeof e.text === 'string' && e.text) ? e.text : prompt('Label text', 'Note');
      if (txt === null || txt === undefined) return;
      txt = String(txt).trim();
      if (!txt) return;
      arPush();
      var rec = arNewObj('label_text', {txt: txt, size: 0.35}, P.x, P.z, P.y);
      rec.name = 'Label: ' + txt.slice(0, 40);
      land(rec, 'Label <b>' + esc(txt) + '</b> pinned.');
    },
    hint: function () { return 'Click the point the note is about.'; },
    cancel: function () {}
  };
})();
