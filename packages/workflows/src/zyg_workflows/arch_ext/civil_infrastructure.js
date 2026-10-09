// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* civil_infrastructure — bridges, tunnels, dams and waterfront works.

   Ten kinds, all in the record's LOCAL frame (origin at the record's x/z,
   bottom at y=0, +X = the record's length direction after ry, +Y up):

     bridge_deck   len x (t + edge) x w   slab with a parapet along each edge
     bridge_pier   w x h x d              a plain pier
     bridge_arch   span x (rise + t) x w  a parabolic arch band under a deck
     tunnel        len x h x w            an arched bore, OPEN at both ends
     culvert       len x 2(r+t) x 2(r+t)  a round pipe, open at both ends
     dam           len x h x t_base       trapezoid section, upstream face vertical
     quay_wall     len x h x t            a plain wall
     jetty         len x h x w            deck on posts every `posts` metres
     embankment    len x h x w            triangular dyke
     sluice        (w+2t) x h x 2t        two piers with a gate between them

   `w`/`t_base`/`r` are OUTSIDE dimensions — the bbox is exactly what the
   parameters say, which is what tests_arch_ext/test_civil_infrastructure.py
   asserts. Hollow kinds (tunnel, culvert) are built as open tubes: side
   quads only, no end caps, so you can look through them. */
(function(){
  /* an open tube: `loop` is a CLOSED profile [[across, up], ...] in the
     record's Z/Y plane, swept along X from -len/2 to +len/2. Ends stay open. */
  function tubeGeom(k, loop, len){
    var THREE=k.THREE, n=loop.length, pos=[], idx=[], i, j, hx=len/2;
    for(i=0;i<n;i++) pos.push(-hx, loop[i][1], loop[i][0]);
    for(i=0;i<n;i++) pos.push( hx, loop[i][1], loop[i][0]);
    for(i=0;i<n;i++){ j=(i+1)%n; idx.push(i, j, n+j, i, n+j, n+i); }
    var g=new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos,3));
    g.setIndex(idx); g.computeVertexNormals(); return g;
  }
  /* a solid band between two polylines `outer` and `inner` (same length,
     points [[x, up], ...]) swept along Z by depth — the arch ring. */
  function bandGeom(k, outer, inner, depth){
    var THREE=k.THREE, n=outer.length, pos=[], idx=[], i, hz=depth/2;
    function push(p, z){ pos.push(p[0], p[1], z); }
    for(i=0;i<n;i++) push(outer[i], -hz);        // 0        .. n-1
    for(i=0;i<n;i++) push(inner[i], -hz);        // n        .. 2n-1
    for(i=0;i<n;i++) push(outer[i],  hz);        // 2n       .. 3n-1
    for(i=0;i<n;i++) push(inner[i],  hz);        // 3n       .. 4n-1
    for(i=0;i<n-1;i++){
      idx.push(i, i+1, 2*n+i+1, i, 2*n+i+1, 2*n+i);                       // extrados
      idx.push(n+i, 3*n+i, 3*n+i+1, n+i, 3*n+i+1, n+i+1);                 // intrados
      idx.push(i, n+i, n+i+1, i, n+i+1, i+1);                             // near cap
      idx.push(2*n+i, 2*n+i+1, 3*n+i+1, 2*n+i, 3*n+i+1, 3*n+i);           // far cap
    }
    idx.push(0, 2*n, 3*n, 0, 3*n, n);                                     // springing ends
    idx.push(n-1, 2*n-1, 4*n-1, n-1, 4*n-1, 3*n-1);
    var g=new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos,3));
    g.setIndex(idx); g.computeVertexNormals(); return g;
  }
  function circleLoop(r, cy, seg){
    var pts=[], i;
    for(i=0;i<seg;i++){ var a=2*Math.PI*i/seg; pts.push([Math.cos(a)*r, cy+Math.sin(a)*r]); }
    return pts;
  }
  /* the horseshoe: vertical legs to the springing, a semicircle of radius w/2
     over them; the wall is t thick, so the bore is (w-2t) wide. */
  function tunnelLoop(w, h, t, seg){
    var ro=w/2, ri=Math.max(0.05, ro-t), yc=Math.max(0.0, h-ro), pts=[], i, a;
    pts.push([-ro, 0]);
    for(i=0;i<=seg;i++){ a=Math.PI*(1-i/seg); pts.push([Math.cos(a)*ro, yc+Math.sin(a)*ro]); }
    pts.push([ro, 0]);
    pts.push([ri, 0]);
    for(i=seg;i>=0;i--){ a=Math.PI*(1-i/seg); pts.push([Math.cos(a)*ri, yc+Math.sin(a)*ri]); }
    pts.push([-ri, 0]);
    return pts;
  }

  AR_EXT.geom.bridge_deck = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var L=N('len',20), w=N('w',8), t=N('t',0.8), e=N('edge',0.5), P=[];
    P.push({g: k.box(L, t, w, 0, t/2, 0)});
    if(e > 0.01){
      P.push({g: k.box(L, e, 0.3, 0, t+e/2, -(w/2-0.15))});
      P.push({g: k.box(L, e, 0.3, 0, t+e/2,  (w/2-0.15))});
    }
    return P;
  };
  AR_EXT.geom.bridge_pier = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',2), dd=N('d',6), h=N('h',8);
    return [{g: k.box(w, h, dd, 0, h/2, 0)}];
  };
  AR_EXT.geom.bridge_arch = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var span=N('span',20), rise=N('rise',5), w=N('w',8), t=N('t',1.0);
    var seg=Math.max(4, Math.round(N('seg',20))), outer=[], inner=[], i;
    for(i=0;i<=seg;i++){
      var x=-span/2 + span*i/seg, u=2*x/span, y=rise*(1-u*u);
      inner.push([x, y]); outer.push([x, y+t]);
    }
    return [{g: bandGeom(k, outer, inner, w)}];
  };
  AR_EXT.geom.tunnel = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var L=N('len',20), w=N('w',8), h=Math.max(N('h',6), N('w',8)/2+0.05), t=N('t',0.5);
    return [{g: tubeGeom(k, tunnelLoop(w, h, t, Math.max(4, Math.round(N('seg',12)))), L)}];
  };
  AR_EXT.geom.culvert = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var L=N('len',10), r=N('r',1), t=N('t',0.2), seg=Math.max(6, Math.round(N('seg',24)));
    return [{g: tubeGeom(k, circleLoop(r+t, r+t, seg), L)},
            {g: tubeGeom(k, circleLoop(r,   r+t, seg), L)}];
  };
  AR_EXT.geom.dam = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var L=N('len',40), h=N('h',20), tb=N('t_base',15), tt=Math.min(N('t_top',4), N('t_base',15));
    var g=k.prism([[-tb/2,0],[tb/2,0],[-tb/2+tt,h],[-tb/2,h]], L);
    g.rotateY(Math.PI/2); return [{g:g}];
  };
  AR_EXT.geom.quay_wall = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var L=N('len',20), h=N('h',4), t=N('t',1.2);
    return [{g: k.box(L, h, t, 0, h/2, 0)}];
  };
  AR_EXT.geom.jetty = function(p, k){
    var THREE=k.THREE, N=function(key,d){ return k.num(p[key], d); };
    var L=N('len',12), w=N('w',2.5), h=N('h',1.5), sp=Math.max(1.0, N('posts',3)), P=[], i;
    var dt=Math.min(0.2, h/3);
    P.push({g: k.box(L, dt, w, 0, h-dt/2, 0)});
    var n=Math.max(1, Math.round(L/sp));
    for(i=0;i<=n;i++){
      var x=-L/2 + L*i/n, x2=Math.max(-L/2+0.12, Math.min(L/2-0.12, x));
      var g=new THREE.CylinderGeometry(0.12,0.12,h-dt,10);
      g.translate(x2, (h-dt)/2, -(w/2-0.2)); P.push({g:g});
      var g2=new THREE.CylinderGeometry(0.12,0.12,h-dt,10);
      g2.translate(x2, (h-dt)/2, (w/2-0.2)); P.push({g:g2});
    }
    return P;
  };
  AR_EXT.geom.embankment = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var L=N('len',20), w=N('w',9), h=N('h',3);
    var g=k.prism([[-w/2,0],[w/2,0],[0,h]], L);
    g.rotateY(Math.PI/2); return [{g:g}];
  };
  AR_EXT.geom.sluice = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',6), h=N('h',5), gh=Math.min(N('gate_h',3), N('h',5)), t=N('t',1.0), P=[];
    P.push({g: k.box(t, h, 2*t, -(w/2+t/2), h/2, 0)});
    P.push({g: k.box(t, h, 2*t,  (w/2+t/2), h/2, 0)});
    P.push({g: k.box(w, gh, t/2, 0, gh/2, 0), sub:'mat_steel'});
    return P;
  };

  AR_EXT.label.bridge_deck = 'Bridge deck';
  AR_EXT.label.bridge_pier = 'Bridge pier';
  AR_EXT.label.bridge_arch = 'Bridge arch';
  AR_EXT.label.tunnel      = 'Tunnel';
  AR_EXT.label.culvert     = 'Culvert';
  AR_EXT.label.dam         = 'Dam';
  AR_EXT.label.quay_wall   = 'Quay wall';
  AR_EXT.label.jetty       = 'Jetty';
  AR_EXT.label.embankment  = 'Embankment';
  AR_EXT.label.sluice      = 'Sluice';
})();
