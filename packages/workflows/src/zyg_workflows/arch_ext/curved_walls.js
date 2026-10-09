// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* curved_walls — wall_arc (an arc of wall around a centre) and wall_ring (a
   full circle). Local frame: the record's x/z is the CENTRE of the circle,
   bottom at y=0, height p.h. Angles in degrees on the plan: 0 = +X, 90 = -Z
   (north = up in the top view), so a point at θ is (r cosθ, -r sinθ) — the
   same handedness as the record's ry. The wall is centred on the radius:
   inner face r - t/2, outer face r + t/2. Built as an extruded THREE.Shape so
   the faces are true arcs, not a chain of boxes. */
(function(){
  function arcGeom(k, r, a0, a1, h, t, seg){
    var THREE=k.THREE;
    var ri=Math.max(0.05, r-t/2), ro=r+t/2;
    var s0=a0*Math.PI/180, s1=a1*Math.PI/180;        // rotateX(-90°) below maps shape +Y to -Z: that IS the plan convention, no extra flip
    var cw = s1 < s0;                                  // absarc wants to know which way round
    var sh=new THREE.Shape();
    sh.absarc(0,0,ro, s0, s1, cw);
    sh.absarc(0,0,ri, s1, s0, !cw);
    sh.closePath();
    var g=new THREE.ExtrudeGeometry(sh, {depth:h, bevelEnabled:false, curveSegments:Math.max(4, seg)});
    g.rotateX(-Math.PI/2);          // extrusion +Z -> +Y (up); shape Y -> -Z
    g.computeVertexNormals();
    return g;
  }
  AR_EXT.geom.wall_arc = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var r=N('r',5), a0=N('a0',0), a1=N('a1',90), h=N('h',2.7), t=N('t',0.24), seg=Math.round(N('seg',24));
    if(Math.abs(a1-a0)<0.5) a1=a0+0.5;
    if(Math.abs(a1-a0)>=360) a1=a0+359.9;
    return [{g: arcGeom(k, r, a0, a1, h, t, seg)}];
  };
  AR_EXT.geom.wall_ring = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var r=N('r',5), h=N('h',2.7), t=N('t',0.24), seg=Math.round(N('seg',48));
    return [{g: arcGeom(k, r, 0, 359.99, h, t, seg)}];
  };
  AR_EXT.label.wall_arc = 'Curved wall';
  AR_EXT.label.wall_ring = 'Round wall';
})();
