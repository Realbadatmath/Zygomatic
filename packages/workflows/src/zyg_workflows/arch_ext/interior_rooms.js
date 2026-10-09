// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* interior_rooms — the finishes that turn a shell into rooms: ceiling,
   floor_finish, skirting, raised_floor, suspended_ceiling.

   Local frame (as every kind here): the record's x/z is the CENTRE in plan,
   the piece sits with its BOTTOM at y = 0 and grows up. So a ceiling is
   placed at storey_top - t and a floor_finish at the storey base.

   Sizes are exactly what the parameters say:
     ceiling            w x t x d
     floor_finish       w x t x d
     skirting           len x h x t   (len along +X, t is how far it stands
                                       proud of the wall face)
     raised_floor       w x h x d     (deck plate on top, pedestal grid under)
     suspended_ceiling  w x t x d     (T-bar grid every `tiles` m + tile panels)
*/
(function(){
  function gridLines(span, step){
    /* line offsets from -span/2 to +span/2, `step` apart, always including
       both edges. */
    var s = Math.max(0.1, step), out = [], v = -span / 2;
    while(v < span / 2 - 1e-6){ out.push(v); v += s; }
    out.push(span / 2);
    return out;
  }

  AR_EXT.geom.ceiling = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',6), d=N('d',4), t=Math.max(0.005, N('t',0.1));
    return [{g: k.box(w, t, d, 0, t/2, 0)}];
  };

  AR_EXT.geom.floor_finish = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',6), d=N('d',4), t=Math.max(0.002, N('t',0.02));
    return [{g: k.box(w, t, d, 0, t/2, 0)}];
  };

  AR_EXT.geom.skirting = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var L=Math.max(0.05, N('len',4)), h=Math.max(0.02, N('h',0.1)), t=Math.max(0.002, N('t',0.015));
    return [{g: k.box(L, h, t, 0, h/2, 0)}];
  };

  AR_EXT.geom.raised_floor = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',6), d=N('d',4), h=Math.max(0.05, N('h',0.3)), sp=Math.max(0.2, N('pedestals',0.6));
    var td=Math.min(0.03, h*0.4);                       // the deck plate
    var P=[{g: k.box(w, td, d, 0, h - td/2, 0)}];
    var nx=Math.max(1, Math.round(w/sp)), nz=Math.max(1, Math.round(d/sp));
    if(nx*nz > 900){ nx=Math.min(nx,30); nz=Math.min(nz,30); }
    var ph=h-td, i, j, px, pz;
    for(i=0;i<nx;i++){
      px = -w/2 + w*(i+0.5)/nx;
      for(j=0;j<nz;j++){
        pz = -d/2 + d*(j+0.5)/nz;
        P.push({g: k.box(0.06, ph, 0.06, px, ph/2, pz), sub:'mat_steel'});
      }
    }
    return P;
  };

  AR_EXT.geom.suspended_ceiling = function(p, k){
    var N=function(key,d){ return k.num(p[key], d); };
    var w=N('w',6), d=N('d',4), t=Math.max(0.01, N('t',0.05)), tile=Math.max(0.2, N('tiles',0.6));
    var bt=Math.min(0.024, t*0.5, w*0.2, d*0.2);        // T-bar width on plan
    var xs=gridLines(w, tile), zs=gridLines(d, tile), P=[], i, j;
    for(i=0;i<zs.length;i++){                            // bars running along X
      var zc=Math.max(-d/2+bt/2, Math.min(d/2-bt/2, zs[i]));
      P.push({g: k.box(w, t, bt, 0, t/2, zc), sub:'mat_steel'});
    }
    for(i=0;i<xs.length;i++){                            // bars running along Z
      var xc=Math.max(-w/2+bt/2, Math.min(w/2-bt/2, xs[i]));
      P.push({g: k.box(bt, t, d, xc, t/2, 0), sub:'mat_steel'});
    }
    var tp=t*0.4;
    if((xs.length-1)*(zs.length-1) <= 900){
      for(i=0;i<xs.length-1;i++){
        for(j=0;j<zs.length-1;j++){
          var pw=xs[i+1]-xs[i]-bt, pd=zs[j+1]-zs[j]-bt;
          if(pw<=0.01 || pd<=0.01) continue;
          P.push({g: k.box(pw, tp, pd, (xs[i]+xs[i+1])/2, tp/2, (zs[j]+zs[j+1])/2), sub:'mat_plaster'});
        }
      }
    }
    return P;
  };

  AR_EXT.label.ceiling = 'Ceiling';
  AR_EXT.label.floor_finish = 'Floor finish';
  AR_EXT.label.skirting = 'Skirting';
  AR_EXT.label.raised_floor = 'Raised floor';
  AR_EXT.label.suspended_ceiling = 'Suspended ceiling';
})();
