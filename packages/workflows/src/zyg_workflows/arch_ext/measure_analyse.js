// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* measure_analyse — the two kinds the analysis tools draw.

   annotation: a pin. A thin pole from y=0 to y=h with a ball of radius r
   centred on its top, so the record's bounding box is h + r tall and 2r wide.
   The pin carries no text geometry — the label is the record's NAME, which the
   outliner and the Properties panel already show.

   dimension: a measured guide line. The line itself is a `line:1` part, the
   same trick guide_line uses in arGeom, running along local +X from -len/2 to
   +len/2 with the record's x/z at its MIDPOINT; the two end ticks are thin
   boxes across the line (local Z) so the record still owns real triangles and
   reads as an object, not as a stray edge. Rotate with ry to measure any
   direction — the assistant's dimension() tool sets it from the two cells. */
(function(){
  AR_EXT.geom.annotation = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var THREE=k.THREE;
    var h=Math.max(0.2, N('h',1.5)), r=Math.max(0.02, N('r',0.15));
    var pole=new THREE.CylinderGeometry(r*0.18, r*0.18, h, 10);
    pole.translate(0, h/2, 0);
    var ball=new THREE.SphereGeometry(r, 16, 12);
    ball.translate(0, h, 0);
    return [{g: pole}, {g: ball, sub: 'mat_paint_dark'}];
  };
  AR_EXT.geom.dimension = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var THREE=k.THREE;
    var L=Math.max(0.05, N('len',5)), t=Math.max(0.02, N('tick',0.3));
    var g=new THREE.BufferGeometry().setFromPoints(
      [new THREE.Vector3(-L/2,0,0), new THREE.Vector3(L/2,0,0)]);
    return [{g: g, line: 1},
            {g: k.box(0.03, 0.03, t, -L/2, 0, 0)},
            {g: k.box(0.03, 0.03, t,  L/2, 0, 0)}];
  };
  AR_EXT.label.annotation = 'Annotation pin';
  AR_EXT.label.dimension = 'Dimension line';
})();
