// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* stairs_vertical — the vertical-circulation kinds: stair_u, stair_winder,
   stair_landing, elevator_shaft, elevator_car, escalator and
   fire_stair_exterior.

   Local frame (as everywhere): the record's x/z is the origin in plan, the
   bottom sits at y = 0, +Y is up. Plan angles are the record's own ry, so a
   direction θ points at (cos θ, −sin θ) in (x, z) — the same handedness
   THREE's rotateY(θ) gives a geometry.

   Every stair is a stack of step boxes run × w × rise, exactly like the
   built-in stair_straight in arGeom(): step i spans y = rise·i … rise·(i+1),
   so a flight of `steps` steps is exactly steps·rise tall — the number the
   assistant's add_stair solves for. */
(function(){
  function num(k, p, key, d){ return k.num(p[key], d); }

  /* GUARDING (2026-09-10, every open edge since 2026-09-12). A flight with an
     open long edge is a fall, so `rails: 1` (the assistant's add_stair always
     sets it) hangs a 1.0 m balustrade — 0.04 m posts about every metre plus a
     top rail — along EVERY open edge: both long edges of both flights (the well
     side included: the void is a 0.2 m gap, not a landing, so an unguarded
     inner edge is the same fall as the outer one) and both ends of the landing.
     The rail adds RAIL_H to the record's bounding box, which is how the tests
     tell rails:1 from rails:0; in plan it stays inside the treads, so the
     footprint does not grow.

     Every rail part carries sub:'mat_steel', because the record's own material
     is the TREADS (dark concrete on the live tower) and a dark rail against a
     dark tread is invisible from the well — the defect the operator reported. */
  var RAIL_H=1.0, POST=0.04, BAR=0.06, POST_SPACING=1.0;

  /* One raked rail over a flight: `n` steps of run x rise climbing from
     (x0, 0) in direction `sign`, on the rail line z = zr. The walking line is
     the TOP of each step, so post i stands on rise*(i+1). */
  function flightRail(k, P, n, rise, run, x0, sign, zr, y0){
    var every=Math.max(1, Math.round(POST_SPACING/Math.max(0.05, run)));
    var i, xs=[], ys=[];
    for(i=0;i<n;i+=every){
      var xi=x0+sign*(run*i+run/2), yi=y0+rise*(i+1);
      P.push({g:k.box(POST, RAIL_H, POST, xi, yi+RAIL_H/2, zr), sub:'mat_steel'});
      xs.push(xi); ys.push(yi+RAIL_H);
    }
    var xe=x0+sign*(run*(n-1)+run/2), ye=y0+rise*n+RAIL_H;   // always end on the last step
    xs.push(xe); ys.push(ye);
    var dx=xs[xs.length-1]-xs[0], dy=ys[ys.length-1]-ys[0];
    var L=Math.sqrt(dx*dx+dy*dy)+BAR;
    var g=k.box(L, BAR, BAR, 0, 0, 0);
    g.rotateZ(Math.atan2(dy, dx));
    g.translate((xs[0]+xs[xs.length-1])/2, (ys[0]+ys[ys.length-1])/2, zr);
    P.push({g:g, sub:'mat_steel'});
  }

  /* A rail over an arbitrary walking line [[x, y, z], ...] (the winder): a post
     every `every` treads and a bar between consecutive posts, pitched about Z
     and swung about Y. */
  function snakeRail(k, P, line, every){
    var pts=[], i;
    for(i=0;i<line.length;i+=every) pts.push(line[i]);
    if(pts[pts.length-1]!==line[line.length-1]) pts.push(line[line.length-1]);
    for(i=0;i<pts.length;i++) P.push({g:k.box(POST, RAIL_H, POST, pts[i][0], pts[i][1]+RAIL_H/2, pts[i][2]), sub:'mat_steel'});
    for(i=0;i+1<pts.length;i++){
      var a=pts[i], b=pts[i+1];
      var dx=b[0]-a[0], dy=b[1]-a[1], dz=b[2]-a[2];
      var flat=Math.sqrt(dx*dx+dz*dz), L=Math.sqrt(flat*flat+dy*dy)+BAR;
      var g=k.box(L, BAR, BAR, 0, 0, 0);
      g.rotateZ(Math.atan2(dy, flat));
      g.rotateY(Math.atan2(-dz, dx));
      g.translate((a[0]+b[0])/2, (a[1]+b[1])/2+RAIL_H-BAR/2, (a[2]+b[2])/2);
      P.push({g:g, sub:'mat_steel'});
    }
  }

  /* A level rail along the outer edge of a landing: from z=za to z=zb at x=xr. */
  function edgeRail(k, P, xr, za, zb, ytop){
    var L=Math.abs(zb-za), zc=(za+zb)/2, n=Math.max(2, Math.round(L/POST_SPACING)+1), i;
    for(i=0;i<n;i++) P.push({g:k.box(POST, RAIL_H, POST, xr, ytop+RAIL_H/2, za+(zb-za)*i/(n-1)), sub:'mat_steel'});
    P.push({g:k.box(BAR, BAR, L+BAR, xr, ytop+RAIL_H-BAR/2, zc), sub:'mat_steel'});
  }

  /* The mirror of edgeRail: a level rail along one END of a landing, from x=xa
     to x=xb at the fixed z=zr. A U stair's landing has two of them — the two
     short sides that look down the well and over the flight below. */
  function edgeRailX(k, P, zr, xa, xb, ytop){
    var L=Math.abs(xb-xa), xc=(xa+xb)/2, n=Math.max(2, Math.round(L/POST_SPACING)+1), i;
    for(i=0;i<n;i++) P.push({g:k.box(POST, RAIL_H, POST, xa+(xb-xa)*i/(n-1), ytop+RAIL_H/2, zr), sub:'mat_steel'});
    P.push({g:k.box(L+BAR, BAR, BAR, xc, ytop+RAIL_H-BAR/2, zr), sub:'mat_steel'});
  }

  /* stair_u — two flights back to back around a landing. Flight A climbs
     along +X at z = −(w+gap)/2, the landing caps it, flight B returns along
     −X at z = +(w+gap)/2. Total width across = 2w + gap; total height =
     steps·rise (the landing occupies the last step's height band, it does not
     add one) — plus the rail when p.rails is set. */
  AR_EXT.geom.stair_u = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var ns=Math.max(2, Math.round(N('steps',16))), rise=N('rise',0.175), run=N('run',0.28);
    var w=N('w',1.0), gap=N('gap',0.2);
    var na=Math.floor(ns/2), nb=ns-na, dz=(w+gap)/2;
    var x0=-(na*run+w)/2, P=[], i;
    for(i=0;i<na;i++) P.push({g:k.box(run, rise, w, x0+run*i+run/2, rise*i+rise/2, -dz)});
    P.push({g:k.box(w, rise, 2*w+gap, x0+na*run+w/2, rise*na-rise/2, 0)});   // landing
    var xb=x0+na*run;
    for(i=0;i<nb;i++) P.push({g:k.box(run, rise, w, xb-run*i-run/2, rise*(na+i)+rise/2, dz)});
    if(N('rails',0)>0.5){
      var xl0=x0+na*run, xl1=x0+na*run+w-POST/2;                           // the landing's x span
      flightRail(k, P, na, rise, run, x0, 1, -(dz+w/2-POST/2), 0);          // outer edge of flight A
      flightRail(k, P, na, rise, run, x0, 1, -(gap/2+POST/2), 0);           // WELL edge of flight A
      flightRail(k, P, nb, rise, run, xb, -1, dz+w/2-POST/2, rise*na);      // outer edge of flight B
      flightRail(k, P, nb, rise, run, xb, -1, gap/2+POST/2, rise*na);       // WELL edge of flight B
      edgeRail(k, P, xl1, -(w+gap/2), w+gap/2, rise*na);                    // landing's outer edge
      edgeRailX(k, P, -(w+gap/2-POST/2), xl0, xl1, rise*na);                // landing's two ends
      edgeRailX(k, P,  (w+gap/2-POST/2), xl0, xl1, rise*na);
    }
    return P;
  };

  /* stair_winder — flight, a fan of `steps/4` winder treads that swing the
     direction round by `turn` degrees, then the second flight. The winders
     are the flight's own boxes rotated about Y: an approximation of a true
     wedge (Blender prefixes the object with '~' for that reason). */
  AR_EXT.geom.stair_winder = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var ns=Math.max(3, Math.round(N('steps',16))), rise=N('rise',0.175), run=N('run',0.28);
    var w=N('w',1.0), turn=N('turn',90);
    var nw=Math.max(1, Math.round(ns/4));
    if(nw>ns-2) nw=Math.max(1, ns-2);
    var n1=Math.floor((ns-nw)/2), n2=ns-nw-n1;
    var P=[], i, ang=0, cx=0, cz=0, idx=0, line=[];
    function tread(a){
      var g=k.box(run, rise, w, 0, 0, 0);
      g.rotateY(a);
      var tx=cx+Math.cos(a)*run/2, tz=cz-Math.sin(a)*run/2;
      g.translate(tx, rise*idx+rise/2, tz);
      P.push({g:g});
      /* the rail line runs along the outer edge: local +Z of a tread turned by
         `a` points at (sin a, cos a) in world (x, z). */
      var e=w/2-POST/2;
      line.push([tx+Math.sin(a)*e, rise*(idx+1), tz+Math.cos(a)*e]);
      cx+=Math.cos(a)*run; cz-=Math.sin(a)*run; idx++;
    }
    for(i=0;i<n1;i++) tread(ang);
    var da=turn*Math.PI/180/nw;
    for(i=0;i<nw;i++){ ang+=da; tread(ang); }
    for(i=0;i<n2;i++) tread(ang);
    if(N('rails',0)>0.5) snakeRail(k, P, line, Math.max(1, Math.round(POST_SPACING/Math.max(0.05, run))));
    return P;
  };

  /* stair_landing — a plain slab w (X) × d (Z) × t thick, top at y = t. */
  AR_EXT.geom.stair_landing = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',1.2), d=N('d',1.2), t=N('t',0.15);
    return [{g:k.box(w, t, d, 0, t/2, 0)}];
  };

  /* elevator_shaft — four thin walls of thickness t, open at the top; the
     OUTSIDE of the walls is the w × d envelope, so the bbox is exactly
     w × h × d.

     p.doors is the list of STOREY NUMBERS the shaft serves (absolute, so
     p.doors[0] is the storey the record's own base sits on) and p.sh the storey
     height: each one gets a two-leaf door on the p.door_side face, recessed into
     the wall so the shaft's bbox is still w × h × d. The length above the last
     door is the overrun — the same box carrying on, which is what a motor room
     over the top deck looks like. */
  var DOOR_H=2.1, DOOR_MARGIN=0.4, DOOR_DEEP=0.05, DOOR_GROOVE=0.04;

  AR_EXT.geom.elevator_shaft = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',1.8), d=N('d',2.0), h=N('h',8.1), t=Math.min(N('t',0.2), Math.min(w,d)/3);
    var P=[{g:k.box(w, h, t, 0, h/2, -(d-t)/2)},
           {g:k.box(w, h, t, 0, h/2,  (d-t)/2)},
           {g:k.box(t, h, d-2*t, -(w-t)/2, h/2, 0)},
           {g:k.box(t, h, d-2*t,  (w-t)/2, h/2, 0)}];
    var doors=(p && p.doors) || [], sh=N('sh', 2.7);
    var side=String((p && p.door_side) || 'south');
    if(doors.length && sh>0.1){
      /* the record has no ry of its own, so local -Z is north and +X east */
      var alongX=(side==='south'||side==='north');
      var face=alongX ? w : d;                     /* the width of that face */
      var lw=Math.max(0.2, face-DOOR_MARGIN);      /* the two leaves together */
      var leaf=(lw-DOOR_GROOVE)/2;
      var sgn=(side==='south'||side==='east') ? 1 : -1;
      var span=alongX ? d : w;                     /* across the face */
      var inset=Math.max(0, Math.min(t-DOOR_DEEP, DOOR_DEEP));
      var off=sgn*(span/2 - inset - DOOR_DEEP/2);  /* set back into the wall */
      var s0=doors[0];
      for(var i=0;i<doors.length;i++){
        var base=(doors[i]-s0)*sh;
        if(base+DOOR_H > h+0.01) continue;         /* never a door above the shaft */
        for(var j=-1;j<=1;j+=2){
          var c=j*(leaf+DOOR_GROOVE)/2, cy=base+DOOR_H/2;
          P.push(alongX ? {g:k.box(leaf, DOOR_H, DOOR_DEEP, c, cy, off)}
                        : {g:k.box(DOOR_DEEP, DOOR_H, leaf, off, cy, c)});
        }
      }
    }
    return P;
  };

  /* elevator_car — floor, ceiling, back and two sides; door = 1 leaves the
     +X face open (that is the side the doors are on). */
  AR_EXT.geom.elevator_car = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',1.6), d=N('d',1.8), h=N('h',2.2), door=N('door',1), t=0.06;
    var P=[{g:k.box(w, t, d, 0, t/2, 0)},
           {g:k.box(w, t, d, 0, h-t/2, 0)},
           {g:k.box(t, h-2*t, d, -(w-t)/2, h/2, 0)},
           {g:k.box(w-2*t, h-2*t, t, 0, h/2, -(d-t)/2)},
           {g:k.box(w-2*t, h-2*t, t, 0, h/2,  (d-t)/2)}];
    if(door<0.5) P.push({g:k.box(t, h-2*t, d, (w-t)/2, h/2, 0)});
    return P;
  };

  /* escalator — the sloping truss plus its two balustrades. The run follows
     from the rise and the pitch: L = rise / tan(angle). */
  AR_EXT.geom.escalator = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var rise=N('rise',2.7), w=N('w',1.0), angle=N('angle',30), rh=N('rail_h',0.9);
    var a=Math.max(5, Math.min(60, angle))*Math.PI/180;
    var L=rise/Math.tan(a), t=0.4;
    var P=[{g:k.prism([[-L/2,0],[L/2,rise],[L/2,rise+t],[-L/2,t]], w)}];
    var i, zs=[-(w/2-0.04), (w/2-0.04)];
    for(i=0;i<2;i++){
      var g=k.prism([[-L/2,t],[L/2,rise+t],[L/2,rise+t+rh],[-L/2,t+rh]], 0.08);
      g.translate(0, 0, zs[i]);
      P.push({g:g});
    }
    return P;
  };

  /* fire_stair_exterior — a switchback bolted to a facade: per storey one
     straight flight of round(h/rise) steps plus a 0.15 m landing box w × w,
     the direction alternating each storey. Height = storeys · h exactly. */
  AR_EXT.geom.fire_stair_exterior = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var ns=Math.max(1, Math.round(N('storeys',3))), sh=N('h',2.7);
    var w=N('w',1.2), run=N('run',0.28), rise=N('rise',0.18);
    var nst=Math.max(2, Math.round(sh/Math.max(0.05, rise))), r=sh/nst;
    var Lf=nst*run, ox=-Lf/2, P=[], s, i;
    for(s=0;s<ns;s++){
      var up=(s%2===0);
      for(i=0;i<nst;i++){
        var xi=up ? (run*i+run/2) : (Lf-run*i-run/2);
        P.push({g:k.box(run, r, w, ox+xi, s*sh+r*i+r/2, 0)});
      }
      var lx=up ? (Lf+w/2) : (-w/2);
      P.push({g:k.box(w, 0.15, w, ox+lx, (s+1)*sh-0.075, 0)});
    }
    return P;
  };

  AR_EXT.label.stair_u = 'U stair';
  AR_EXT.label.stair_winder = 'Winder stair';
  AR_EXT.label.stair_landing = 'Stair landing';
  AR_EXT.label.elevator_shaft = 'Lift shaft';
  AR_EXT.label.elevator_car = 'Lift car';
  AR_EXT.label.escalator = 'Escalator';
  AR_EXT.label.fire_stair_exterior = 'Fire escape stair';
})();
