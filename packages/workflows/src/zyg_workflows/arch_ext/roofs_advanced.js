// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* roofs_advanced — the ten roof shapes the base catalogue has no case for:
   mansard, gambrel, butterfly, sawtooth, pyramid, cone, onion, half-hip,
   curved (barrel) and a flat deck with a glazed strip.

   Local frame for every kind here: the record's x/z is the CENTRE of the
   footprint, the eave/base sits at y=0 (roofs are placed at storey*2.7, on top
   of the walls), w runs along +X, d along +Z, and `over` is the overhang added
   on ALL FOUR sides — so the bounding box is (w+2*over) x h x (d+2*over).

   The pitched shapes are extruded sections. arPrismG(profile, len) puts the
   profile in XY and extrudes along Z, so `g.rotateY(Math.PI/2)` (the same trick
   roof_gable uses) sends the profile's X to the world Z and the extrusion to
   the world X: profile = the section ACROSS the depth, len = w+2*over.
   roof_sawtooth is the exception — its teeth run along X, so its section is
   already in XY and it is extruded along Z with no rotation.

   Butterfly and sawtooth are built as SEVERAL convex prisms rather than one
   polygon: arPrismG caps with a triangle fan from vertex 0, which is only
   correct for a convex profile, and both of those sections are concave. */
(function(){
  var PI = Math.PI;

  /* the onion's silhouette as (radius factor, height factor); the widest ring
     is exactly 1.0 so the bulb's bounding box is 2r across. */
  var ONION = [[0.72,0.00],[0.90,0.12],[1.00,0.30],[0.93,0.50],[0.72,0.68],[0.44,0.83],[0.18,0.93],[0.00,1.00]];

  AR_EXT.geom.roof_mansard = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',8), d=N('d',6), h=N('h',3), o=N('over',0.4);
    var br=Math.min(0.9, Math.max(0.1, N('break',0.6)));
    var De=d/2+o, yb=h*br, Db=De*0.72, Dr=De*0.16;
    var g=k.prism([[-De,0],[De,0],[Db,yb],[Dr,h],[-Dr,h],[-Db,yb]], w+2*o);
    g.rotateY(PI/2); return [{g:g}];
  };

  AR_EXT.geom.roof_gambrel = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',8), d=N('d',6), h=N('h',3), o=N('over',0.4);
    var br=Math.min(0.9, Math.max(0.1, N('break',0.6)));
    var De=d/2+o, yb=h*br, Db=De*0.55;
    var g=k.prism([[-De,0],[De,0],[Db,yb],[0,h],[-Db,yb]], w+2*o);
    g.rotateY(PI/2); return [{g:g}];
  };

  AR_EXT.geom.roof_butterfly = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',8), d=N('d',6), h=N('h',1.2), o=N('over',0.4);
    var De=d/2+o, T=Math.min(0.2, Math.max(0.02, h*0.35)), L=w+2*o;
    var a=k.prism([[-De,h-T],[0,0],[0,T],[-De,h]], L);      // the two slabs meet
    var b=k.prism([[0,0],[De,h-T],[De,h],[0,T]], L);        // in the valley at y=0
    a.rotateY(PI/2); b.rotateY(PI/2);
    return [{g:a},{g:b}];
  };

  AR_EXT.geom.roof_sawtooth = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',12), d=N('d',8), h=N('h',1.8), nb=Math.max(1, Math.round(N('bays',4)));
    var bw=w/nb, x0=-w/2, out=[], i;
    for(i=0;i<nb;i++){
      var xa=x0+bw*i, xb=xa+bw;                              /* ramp up, then the glazed drop */
      out.push({g: k.prism([[xa,0],[xb,0],[xb,h],[xa,Math.min(0.1,h*0.1)]], d)});
    }
    return out;
  };

  AR_EXT.geom.roof_pyramid = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',6), d=N('d',6), h=N('h',3), o=N('over',0.4);
    var W=w/2+o, D=d/2+o;
    var v=[-W,0,-D,  W,0,-D,  W,0,D,  -W,0,D,  0,h,0];
    var f=[0,1,4, 1,2,4, 2,3,4, 3,0,4, 0,2,1, 0,3,2];
    var g=new k.THREE.BufferGeometry();
    g.setAttribute('position', new k.THREE.Float32BufferAttribute(v,3));
    g.setIndex(f); g.computeVertexNormals(); return [{g:g}];
  };

  AR_EXT.geom.roof_half_hip = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',8), d=N('d',6), h=N('h',2.8), o=N('over',0.4);
    var clip=Math.min(1, Math.max(0, N('clip',0.5)));
    var W=w/2+o, D=d/2+o;
    /* clip 0 = a plain gable (the ridge runs out to the eave, the end face is
       vertical); clip 1 = a full hip (the same ridge roof_hip uses). */
    var rxh=Math.max(0.001, W-D), rx=W - clip*(W-rxh);
    var v=[-W,0,-D,  W,0,-D,  W,0,D,  -W,0,D,  -rx,h,0,  rx,h,0];
    var f=[0,1,5, 0,5,4, 2,3,4, 2,4,5, 1,2,5, 3,0,4];
    var g=new k.THREE.BufferGeometry();
    g.setAttribute('position', new k.THREE.Float32BufferAttribute(v,3));
    g.setIndex(f); g.computeVertexNormals(); return [{g:g}];
  };

  AR_EXT.geom.roof_curved = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',8), d=N('d',6), h=N('h',2), o=N('over',0.3);
    var D=d/2+o, arc=[], i;
    for(i=0;i<=28;i++){ var t=-1+2*i/28; arc.push([D*t, h*Math.sqrt(Math.max(0,1-t*t))]); }
    var g=k.prism(arc, w+2*o);        /* the closing edge (D,0)->(-D,0) is the soffit */
    g.rotateY(PI/2); return [{g:g}];
  };

  AR_EXT.geom.roof_cone = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var r=N('r',3), h=N('h',3), o=N('over',0.3);
    var g=new k.THREE.ConeGeometry(Math.max(0.05, r+o), h, 48);
    g.translate(0, h/2, 0); return [{g:g}];
  };

  AR_EXT.geom.roof_onion = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var r=N('r',2.5), h=N('h',3.5), sp=Math.max(0, N('spire',2));
    var pts=[], i;
    for(i=0;i<ONION.length;i++) pts.push(new k.THREE.Vector2(ONION[i][0]*r, ONION[i][1]*h));
    var out=[{g: new k.THREE.LatheGeometry(pts, 48)}];
    if(sp>0.01){
      var s=new k.THREE.ConeGeometry(Math.max(0.02, r*0.08), sp, 12);
      s.translate(0, h+sp/2, 0); out.push({g:s});
    }
    return out;
  };

  AR_EXT.geom.roof_skylight_strip = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',8), d=N('d',6), h=N('h',0.3);
    var gt=Math.min(0.08, h*0.5);                    /* the glass is INSET in the deck */
    return [{g: k.box(w, h, d, 0, h/2, 0)},
            {g: k.box(w*0.8, gt, d*0.3, 0, h-gt/2, 0), sub:'mat_glass'}];
  };

  AR_EXT.label.roof_mansard = 'Mansard roof';
  AR_EXT.label.roof_gambrel = 'Gambrel roof';
  AR_EXT.label.roof_butterfly = 'Butterfly roof';
  AR_EXT.label.roof_sawtooth = 'Sawtooth roof';
  AR_EXT.label.roof_pyramid = 'Pyramid roof';
  AR_EXT.label.roof_cone = 'Conical roof';
  AR_EXT.label.roof_onion = 'Onion dome';
  AR_EXT.label.roof_half_hip = 'Half-hip roof';
  AR_EXT.label.roof_curved = 'Barrel roof';
  AR_EXT.label.roof_skylight_strip = 'Rooflight deck';
})();
