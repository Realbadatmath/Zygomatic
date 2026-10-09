// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* structure_frames — the load-bearing skeleton: steel profiles (beam_i,
   column_h), frames (portal_frame, arch_beam, bracing_x, cantilever) and the
   two masonry/timber members that go with them (buttress, pergola).

   Local frame, as everywhere: the record's origin is the BASE CENTRE, bottom
   at y=0, up = +Y, length runs along +X, depth along Z. Everything here is
   composed from arBoxG (k.box) except the buttress, which is a tapered prism,
   and the sloping members, which are boxes rotated about Z. */
(function(){
  /* a rectangular member (section sw x sd) between two points in the XY
     plane at z=0 — the rafters, the arch voussoirs and the braces. */
  function memberXY(k, ax, ay, bx, by, sw, sd){
    var dx=bx-ax, dy=by-ay, L=Math.sqrt(dx*dx+dy*dy);
    if(L<1e-5) return null;
    var g=new k.THREE.BoxGeometry(L, Math.max(sw,1e-4), Math.max(sd,1e-4));
    g.rotateZ(Math.atan2(dy, dx));
    g.translate((ax+bx)/2, (ay+by)/2, 0);
    return g;
  }

  /* ── beam_i: an I profile extruded along x (bottom flange, top flange, web) ── */
  AR_EXT.geom.beam_i = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var L=N('len',5), h=N('h',0.4), w=N('w',0.2), tf=N('tf',0.02), tw=N('tw',0.012);
    tf=Math.max(0.004, Math.min(tf, h/2-0.002)); tw=Math.max(0.003, Math.min(tw, w));
    return [{g:k.box(L, tf, w, 0, tf/2, 0)},
            {g:k.box(L, tf, w, 0, h-tf/2, 0)},
            {g:k.box(L, h-2*tf, tw, 0, h/2, 0)}];
  };

  /* ── column_h: the same profile stood upright, flanges facing ±z ── */
  AR_EXT.geom.column_h = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var h=N('h',3), w=N('w',0.3), d=N('d',0.3), tf=N('tf',0.02), tw=N('tw',0.012);
    tf=Math.max(0.004, Math.min(tf, d/2-0.002)); tw=Math.max(0.003, Math.min(tw, w));
    return [{g:k.box(w, h, tf, 0, h/2, -(d/2-tf/2))},
            {g:k.box(w, h, tf, 0, h/2,  (d/2-tf/2))},
            {g:k.box(tw, h, d-2*tf, 0, h/2, 0)}];
  };

  /* ── portal_frame: two columns at ±span/2 and two rafters to the apex ──
     Overall x = span + w, y = h + rise (plus the rafter's own half depth). */
  AR_EXT.geom.portal_frame = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var span=Math.max(0.5, N('span',12)), h=Math.max(0.3, N('h',6)), rise=N('rise',1.5);
    var w=N('w',0.25), d=N('d',0.5), P=[];
    P.push({g:k.box(w, h, d, -span/2, h/2, 0)});
    P.push({g:k.box(w, h, d,  span/2, h/2, 0)});
    if(Math.abs(rise) < 1e-4){
      P.push({g:k.box(span, w, d, 0, h+w/2, 0)});
    }else{
      P.push({g:memberXY(k, -span/2, h, 0, h+rise, w, d)});
      P.push({g:memberXY(k,  span/2, h, 0, h+rise, w, d)});
    }
    return P.filter(function(x){ return x.g; });
  };

  /* ── arch_beam: a segmental arch of `seg` straight boxes ──
     Springs from (±span/2, 0), apex at (0, rise). */
  AR_EXT.geom.arch_beam = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var span=Math.max(0.5, N('span',6)), rise=Math.max(0.05, N('rise',1.5));
    var w=N('w',0.25), d=N('d',0.5), seg=Math.max(3, Math.round(N('seg',16))), P=[], i;
    var R=(span*span/4 + rise*rise)/(2*rise), cy=rise-R;
    var a=Math.asin(Math.min(1, (span/2)/R));
    function pt(t){ var th=(Math.PI/2+a) + (-2*a)*t; return [R*Math.cos(th), cy + R*Math.sin(th)]; }
    for(i=0;i<seg;i++){
      var A=pt(i/seg), B=pt((i+1)/seg);
      P.push({g:memberXY(k, A[0], A[1], B[0], B[1], w, d)});
    }
    return P.filter(function(x){ return x.g; });
  };

  /* ── buttress: a wedge with its back flat against the wall (z = -d/2),
     `d` deep at the bottom, `top` deep at the top, `w` wide along x. ── */
  AR_EXT.geom.buttress = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var h=Math.max(0.2, N('h',3)), w=N('w',0.6), d=Math.max(0.1, N('d',1.2));
    var tp=Math.max(0.02, Math.min(N('top',0.3), d));
    /* profile in (u, v) with u = -z, walked counter-clockwise */
    var g=k.prism([[d/2, 0], [d/2, h], [d/2-tp, h], [-d/2, 0]], Math.max(w,1e-4));
    g.rotateY(Math.PI/2);              /* (u, v, ±w/2) -> (±w/2, v, -u) */
    g.computeVertexNormals();
    return [{g:g}];
  };

  /* ── bracing_x: two diagonal bars across a w x h bay ── */
  AR_EXT.geom.bracing_x = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=Math.max(0.2, N('w',4)), h=Math.max(0.2, N('h',2.7)), t=N('t',0.08);
    return [{g:memberXY(k, -w/2, 0, w/2, h, t, t)},
            {g:memberXY(k, -w/2, h, w/2, 0, t, t)}].filter(function(x){ return x.g; });
  };

  /* ── pergola: four posts, two edge beams along x, `beams` rafters along z ── */
  AR_EXT.geom.pergola = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=Math.max(0.5, N('w',4)), d=Math.max(0.5, N('d',3)), h=Math.max(0.6, N('h',2.4));
    var po=Math.max(0.04, N('post',0.12)), nb=Math.max(2, Math.round(N('beams',6)));
    var P=[], i, ph=Math.max(0.1, h-2.5*po);
    for(i=0;i<4;i++){
      P.push({g:k.box(po, ph, po, (i<2?-1:1)*(w/2-po/2), ph/2, (i%2?-1:1)*(d/2-po/2))});
    }
    P.push({g:k.box(w, 1.5*po, po, 0, h-po-0.75*po, -(d/2-po/2))});
    P.push({g:k.box(w, 1.5*po, po, 0, h-po-0.75*po,  (d/2-po/2))});
    for(i=0;i<nb;i++){
      var x=-w/2+po/2 + (w-po)*(nb>1 ? i/(nb-1) : 0.5);
      P.push({g:k.box(po, po, d, x, h-po/2, 0)});
    }
    return P;
  };

  /* ── cantilever: a beam fixed at x=0 and projecting +x ── */
  AR_EXT.geom.cantilever = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var L=Math.max(0.2, N('len',3)), w=N('w',0.3), h=N('h',0.5);
    return [{g:k.box(L, h, w, L/2, h/2, 0)}];
  };

  AR_EXT.label.beam_i = 'I-beam';
  AR_EXT.label.column_h = 'H column';
  AR_EXT.label.portal_frame = 'Portal frame';
  AR_EXT.label.arch_beam = 'Arch beam';
  AR_EXT.label.buttress = 'Buttress';
  AR_EXT.label.bracing_x = 'X bracing';
  AR_EXT.label.pergola = 'Pergola';
  AR_EXT.label.cantilever = 'Cantilever';
})();
