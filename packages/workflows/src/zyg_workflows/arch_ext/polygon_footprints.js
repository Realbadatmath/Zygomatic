// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* polygon_footprints — slab_poly: a floor/roof plate whose footprint is ANY
   polygon, with optional holes cut through it (an atrium, a stair void, a
   light well).

   Local frame: the record's x/z is the polygon's origin, bottom at y=0, the
   plate is p.t thick upwards. p.pts is a list of [x, z] in LOCAL metres
   (>= 3, closed automatically); p.holes is a list of the same shape.

   The extrude + rotateX(-PI/2) recipe (the same one curved_walls.js uses)
   maps the shape's +Y to -Z and the extrusion's +Z to +Y, so a local z is fed
   to the shape as -z and the depth becomes the thickness. */
(function(){
  var DEF_PTS=[[-3,-2],[3,-2],[3,2],[-3,2]];
  function isArr(v){ return Object.prototype.toString.call(v)==='[object Array]'; }
  /* [[x,z],...] -> a clean ring of >= 3 finite pairs, or `fallback`. */
  function ring(v, fallback){
    var out=[], i, a, x, z;
    if(isArr(v)){
      for(i=0;i<v.length;i++){
        a=v[i];
        if(!isArr(a) || a.length<2) continue;
        x=Number(a[0]); z=Number(a[1]);
        if(!isFinite(x) || !isFinite(z)) continue;
        out.push([x,z]);
      }
    }
    // a ring written out longhand repeats its first point: drop it
    if(out.length>3 && Math.abs(out[0][0]-out[out.length-1][0])<1e-9
                    && Math.abs(out[0][1]-out[out.length-1][1])<1e-9) out.pop();
    return out.length>=3 ? out : fallback;
  }
  function feed(path, r){
    var i;
    path.moveTo(r[0][0], -r[0][1]);
    for(i=1;i<r.length;i++) path.lineTo(r[i][0], -r[i][1]);
    path.closePath();
  }
  AR_EXT.geom.slab_poly = function(p, k){
    var THREE=k.THREE;
    var N=function(key,d){ return k.num(p[key], d); };
    var t=Math.max(0.01, N('t',0.22));
    var pts=ring(p.pts, DEF_PTS), i, h, hs, pa;
    var sh=new THREE.Shape();
    feed(sh, pts);
    hs = isArr(p.holes) ? p.holes : [];
    for(i=0;i<hs.length;i++){
      h=ring(hs[i], null);
      if(!h) continue;
      pa=new THREE.Path();
      feed(pa, h);
      sh.holes.push(pa);
    }
    var g=new THREE.ExtrudeGeometry(sh, {depth:t, bevelEnabled:false, curveSegments:2});
    g.rotateX(-Math.PI/2);          // extrusion +Z -> +Y (up); shape Y -> -Z
    g.computeVertexNormals();
    return [{g:g}];
  };
  AR_EXT.label.slab_poly = 'Polygon slab';
})();
