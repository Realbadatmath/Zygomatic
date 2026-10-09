// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* char_dress.js — Character Studio 3D: skin, eyes, height/build, headwear and
   eyewear on the CC0 base body.  (2026-09-18, skin made ONE colour 2026-09-19)

   One hook on CS3_HOOKS. Everything it draws lives under CS3.dress and is
   thrown away and rebuilt on every run. The body itself is never re-uploaded:
   it gets ONE plain skin material for the whole figure, the eyes their own.
   Hair, beard and brows are char_hair.js's CS3.hair — this file never touches
   that group.

   2026-09-19: the wardrobe bands are gone. The first build painted a grey top,
   a darker bottom and brown shoes into the body's vertex colours, with the
   band edges following whatever triangles crossed the cut height — and the
   operator read that, rightly, as a body with three skin colours and ragged
   seams. The body is skin, all of it, in the bible's one skin tone; clothing
   is for a real garment mesh, not for paint. Headwear and eyewear stay because
   they are their own meshes.

   Values come from cstVal(), i.e. staged-else-saved, so a field the operator
   has typed but not written shows on the body immediately. With no character
   loaded every value falls back to a default and the base body stands there in
   neutral skin.

   Every builder takes a CONTEXT so a second figure can be dressed the same way
   from another character's values (the Compare view does this):
     ctx = {model: THREE.Object3D, store: {dress, height, ...}, val: fn(path),
            main: bool}
   The default context is the studio's own: CS3.model / CS3 / cstVal, and only
   the main context re-frames the camera when the height changes. */
(function(){
  if(typeof THREE==='undefined') return;
  if(typeof CS3==='undefined' || typeof CS3_HOOKS==='undefined') return;

  /* ── the bible's words → colours ──────────────────────────────────────── */
  var SKIN = {fair:'#f1d5c2', light:'#e8c3a8', medium:'#d3a486', olive:'#c09a72',
              tan:'#b07f58', dark:'#7a5238', deep:'#4d2f1f'};
  var SKIN_DEF = '#e8c3a8';
  var EYE  = {brown:'#4a2c17', blue:'#4f7fb8', green:'#4e7a4a', hazel:'#7f6a3a',
              amber:'#b47a2b', grey:'#7d8288', 'grey-blue':'#6a8399'};
  var EYE_DEF = '#4a2c17';
  /* the spec's choices are 'slender build', 'average build', … — match the word */
  var BUILD = {slender:0.93, athletic:1.05, muscular:1.12, heavy:1.18, average:1.0};
  var TOP_DEF='#6b7280', STEEL='#8d949c';

  /* band edges, as a fraction of the body's own (unscaled) height */
  var H_NECK=0.80, H_CHIN=0.865;

  /* ── small helpers ─────────────────────────────────────────────────────── */
  function pageVal(path){
    try{
      if(typeof cstVal!=='function') return '';
      var v=cstVal(path);
      return (v===null||v===undefined) ? '' : String(v);
    }catch(e){ return ''; }
  }
  function mainCtx(){ return {model:CS3.model, store:CS3, val:pageVal, main:true}; }
  function word(ctx, path){ return String(ctx.val(path)||'').trim().toLowerCase(); }
  function okHex(s){ return /^#[0-9a-fA-F]{6}$/.test(s); }
  /* The renderer is set to sRGB output, and in r144 a THREE.Color built from a
     hex is taken as LINEAR when it lands on material.color. Every swatch above
     is an sRGB hex, so it has to be converted on the way in or the gamma curve
     lifts every mid-tone towards white: that is the near-white face of the
     first build. Only when the renderer really is in sRGB mode, so a plain
     (linear-output) renderer still gets the raw swatch. */
  function srgb(hex){
    var c=new THREE.Color(hex);
    if(CS3.renderer && THREE.sRGBEncoding && CS3.renderer.outputEncoding===THREE.sRGBEncoding
       && c.convertSRGBToLinear) c.convertSRGBToLinear();
    return c;
  }
  function colourField(ctx, path, dflt){
    var s=String(ctx.val(path)||'').trim();
    return srgb(okHex(s)?s.toLowerCase():dflt);
  }
  function under(o, name){
    for(var p=o; p; p=p.parent){ if(p.name===name) return true; }
    return false;
  }
  /* the skin tone as a colour — shared with char_hair, which shades the brows
     from it */
  function skinColour(ctx){
    ctx = ctx || mainCtx();
    return srgb(SKIN[word(ctx,'identity.skin_tone')] || SKIN_DEF);
  }

  /* ── which mesh is the body ────────────────────────────────────────────── */
  function bodyMesh(root){
    var best=null, n=-1;
    root.traverse(function(o){
      if(!o.isMesh || !o.geometry || !o.geometry.attributes || !o.geometry.attributes.position) return;
      if(under(o,'CS3_DRESS') || under(o,'CS3_HAIR') || under(o,'cs-hair')) return;
      if(/eye[lr]$/i.test(o.name||'')) return;
      var c=o.geometry.attributes.position.count;
      if(c>n){ n=c; best=o; }
    });
    return best;
  }

  /* ── measure the body ONCE per model, in root-local (unscaled) space ─────
     inv(root.matrixWorld) · mesh.matrixWorld cancels whatever scale this file
     has already put on the root, so the numbers below never drift as the
     height field is dragged. Cached on the context's store, keyed by the
     mesh, so a second figure never reads the first one's numbers. */
  function metrics(ctx){
    var root=ctx.model, store=ctx.store;
    var mesh=bodyMesh(root);
    if(!mesh) return null;
    var key=mesh.uuid;
    if(store._dressKey===key && store._dressBase){ store._dressBase.mesh=mesh; return store._dressBase; }

    root.updateMatrixWorld(true);
    var mat=new THREE.Matrix4().multiplyMatrices(
      new THREE.Matrix4().copy(root.matrixWorld).invert(), mesh.matrixWorld);
    var pos=mesh.geometry.attributes.position, n=pos.count;
    var P=new Float32Array(n*3), v=new THREE.Vector3(), i;
    var minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity,minZ=Infinity,maxZ=-Infinity;
    for(i=0;i<n;i++){
      v.set(pos.getX(i),pos.getY(i),pos.getZ(i)).applyMatrix4(mat);
      P[i*3]=v.x; P[i*3+1]=v.y; P[i*3+2]=v.z;
      if(v.x<minX)minX=v.x; if(v.x>maxX)maxX=v.x;
      if(v.y<minY)minY=v.y; if(v.y>maxY)maxY=v.y;
      if(v.z<minZ)minZ=v.z; if(v.z>maxZ)maxZ=v.z;
    }
    var H=Math.max(1e-6, maxY-minY), yChin=minY+H_CHIN*H;

    /* the head band: everything above the chin */
    var hx0=Infinity,hx1=-Infinity,hz0=Infinity,hz1=-Infinity, head=[];
    for(i=0;i<n;i++){
      if(P[i*3+1]<yChin) continue;
      head.push(i);
      var x=P[i*3], z=P[i*3+2];
      if(x<hx0)hx0=x; if(x>hx1)hx1=x; if(z<hz0)hz0=z; if(z>hz1)hz1=z;
    }
    if(!head.length){ hx0=minX; hx1=maxX; hz0=minZ; hz1=maxZ; }
    var headCx=(hx0+hx1)/2, headCz=(hz0+hz1)/2;
    var headW=Math.max(hx1-hx0, 1e-4), headH=Math.max(maxY-yChin, 1e-4);

    /* WHICH WAY IS THE FRONT? glTF is Y-up but says nothing about the facing.
       The TOES decide it: the foot band's z centroid sits forward of the shin's
       by the length of the toes. Measured on coll_body_male_realistic that is
       +0.06 of a unit — huge, and signed the right way. The nose is only the
       fallback: a face carries several times as many vertices as the back of a
       skull, so every count-based head test can be talked out of the answer
       (this file shipped one for an hour and it chose the occiput). */
    var front=0, fz=0, fn=0, sz=0, sn=0;
    for(i=0;i<n;i++){
      var fh=(P[i*3+1]-minY)/H;
      if(fh<0.05){ fz+=P[i*3+2]; fn++; }
      else if(fh>=0.10 && fh<0.20){ sz+=P[i*3+2]; sn++; }
    }
    if(fn && sn){
      var dzf=(fz/fn)-(sz/sn);
      if(Math.abs(dzf)>1e-5) front = dzf>0 ? 1 : -1;
    }
    if(!front){
      var far=0;
      for(i=0;i<head.length;i++){
        var dz=P[head[i]*3+2]-headCz;
        if(Math.abs(dz)>far){ far=Math.abs(dz); front = dz<0 ? -1 : 1; }
      }
    }
    if(!front) front=1;

    store._dressBase={mesh:mesh, P:P, n:n, H:H, minY:minY, maxY:maxY,
            cx:(minX+maxX)/2, cz:(minZ+maxZ)/2,
            headCx:headCx, headCz:headCz, headW:headW, headH:headH,
            yTop:maxY, yChin:yChin, front:front};
    store._dressKey=key;
    return store._dressBase;
  }

  /* ── 1, 2: skin and eyes — ONE material each, no vertex paint ──────────── */
  function paint(ctx, m){
    var root=ctx.model, store=ctx.store;
    var skin=skinColour(ctx);
    var eyeC=srgb(EYE[word(ctx,'identity.eye_color')] || EYE_DEF);

    if(!store._skinMat){
      store._skinMat=new THREE.MeshStandardMaterial({color:0xffffff, roughness:0.8, metalness:0});
      /* 2026-09-20: pores + creases at close range (char_eyes.js), nil at full-body distance */
      if(window.CSEYES && CSEYES.skinMicro) CSEYES.skinMicro(store._skinMat);
    }
    if(!store._eyeMat) store._eyeMat=new THREE.MeshStandardMaterial(
      {color:0xffffff, roughness:0.35, metalness:0});
    store._skinMat.color.copy(skin);
    store._eyeMat.color.copy(eyeC);
    store._skinMat.vertexColors=false;
    store._skinMat.needsUpdate=true;

    /* 2026-09-19: real eyes (sclera, iris, pupil, wet clear coat) come from
       char_eyes.js when it is in the bundle; the flat iris-coloured sphere is
       only the fallback for a bundle without it */
    var realEyes=0;
    if(window.CSEYES && CSEYES.applyFor){
      try{ realEyes=CSEYES.applyFor(root, store, ctx.val('identity.eye_color')); }
      catch(e){ console.warn('char_dress eyes', e); realEyes=0; }
    }
    root.traverse(function(o){
      if(!o.isMesh || !o.material) return;
      if(under(o,'CS3_DRESS') || under(o,'CS3_HAIR') || under(o,'cs-hair')) return;
      if(under(o,'cs-eye') || under(o,'cs-lashes')) return;   /* cornea, tear film, lashes (2026-09-20) */
      if(/eye[lr]$/i.test(o.name||'')){ if(!realEyes) o.material=store._eyeMat; return; }
      /* the body, and teeth, tongue, whatever else the bundle carries: skin */
      o.material=store._skinMat;
      /* a colour attribute left by an older build would still be uploaded
         with the geometry; the material ignores it now, but drop it anyway
         so a later vertexColors flip cannot bring the bands back */
      if(o.geometry && o.geometry.attributes && o.geometry.attributes.color)
        o.geometry.deleteAttribute('color');
    });
  }

  /* ── 3: height and build ───────────────────────────────────────────────── */
  function applyScale(ctx, m){
    var root=ctx.model, store=ctx.store;
    var hv=parseFloat(ctx.val('identity.height_m'));
    var target=(isFinite(hv) && hv>=0.6 && hv<=2.5) ? hv : m.H;
    var sy=target/m.H, b=1.0, bb=word(ctx,'identity.body_build');
    for(var k in BUILD){ if(BUILD.hasOwnProperty(k) && bb.indexOf(k)>=0){ b=BUILD[k]; break; } }
    var mm=parseFloat(ctx.val('identity.muscle_mass'));
    if(isFinite(mm) && mm>50) b*=1+0.06*Math.min(1,(mm-50)/50);
    var sx=sy*b;
    root.scale.set(sx, sy, sx);
    /* feet on y=0, bbox centred in x/z — the same standing rule cs3dLoadModel used */
    root.position.set(-m.cx*sx, -m.minY*sy, -m.cz*sx);
    root.updateMatrixWorld(true);
    var moved=Math.abs((store.height||0)-target)>1e-4;
    store.height=target;
    if(ctx.main && moved && typeof cs3dFrame==='function') cs3dFrame();
  }

  /* ── 5, 6, 7: the CS3.dress group ──────────────────────────────────────── */
  function clearDress(store){
    var g=store.dress;
    if(g){
      if(g.parent) g.parent.remove(g);
      g.traverse(function(o){
        if(!o.isMesh) return;
        if(o.geometry) o.geometry.dispose();
        if(o.material && o.material.dispose) o.material.dispose();
      });
    }
    store.dress=null;
  }

  function buildDress(ctx, m){
    var g=new THREE.Group(); g.name='CS3_DRESS';
    ctx.store.dress=g; ctx.model.add(g);
    headwear(ctx, g, m);
    eyewear(ctx, g, m);
  }

  function dome(r, theta){ return new THREE.SphereGeometry(r,28,18,0,Math.PI*2,0,theta); }

  function headwear(ctx, g, m){
    var kind=word(ctx,'wardrobe.headwear');
    if(!kind || kind==='none') return;
    var W=m.headW, HH=m.headH, cx=m.headCx, cz=m.headCz, yTop=m.yTop, f=m.front;
    var R=0.5*W, cy=yTop-R;                       /* the skull, as a sphere */
    var base=colourField(ctx,'wardrobe.colour_top', TOP_DEF).multiplyScalar(0.6);
    var cloth=new THREE.MeshStandardMaterial({color:base, roughness:0.8, metalness:0});
    var steel=new THREE.MeshStandardMaterial({color:srgb(STEEL), roughness:0.35, metalness:0.5});

    function add(geo, mat, x, y, z, rx, ry, rz){
      var o=new THREE.Mesh(geo, mat||cloth);
      o.position.set(x,y,z);
      if(rx||ry||rz) o.rotation.set(rx||0, ry||0, rz||0);
      g.add(o); return o;
    }
    function crown(r, theta, mat, yScale){
      var o=add(dome(r, theta), mat, cx, cy, cz);
      if(yScale && yScale!==1) o.scale.set(1,yScale,1);
      return {mesh:o, rimY:cy + r*Math.cos(theta)*(yScale||1), rimR:r*Math.sin(theta)};
    }
    function visor(w, depth, y, mat){
      add(new THREE.BoxGeometry(w, 0.03*W, depth), mat, cx, y, cz + f*(0.42*W + 0.5*depth));
    }

    if(kind==='cap'){
      var cp=crown(0.56*W, 0.42*Math.PI);
      visor(0.95*W, 0.50*W, cp.rimY);
    }else if(kind==='flat cap'){
      var fc=crown(0.60*W, 0.38*Math.PI, null, 0.70);
      visor(1.02*W, 0.72*W, fc.rimY);
    }else if(kind==='hat' || kind==='wide-brim hat'){
      var br=(kind==='hat') ? 0.75*W : 1.15*W;
      var ht=crown(0.58*W, 0.50*Math.PI);
      add(new THREE.TorusGeometry(br, 0.04*W, 10, 40), null, cx, ht.rimY, cz, Math.PI/2, 0, 0);
    }else if(kind==='beanie'){
      crown(0.56*W, 0.55*Math.PI);
    }else if(kind==='hood'){
      var dark=new THREE.MeshStandardMaterial(
        {color:base.clone().multiplyScalar(0.6), roughness:0.9, metalness:0});
      crown(0.56*W*1.04, 0.62*Math.PI, dark);
    }else if(kind==='helmet'){
      crown(0.58*W, 0.55*Math.PI, steel);
    }else if(kind==='crown'){
      var cyC=yTop-0.06*HH;
      add(new THREE.TorusGeometry(0.52*W, 0.035*W, 10, 36), null, cx, cyC, cz, Math.PI/2, 0, 0);
      for(var i=0;i<8;i++){
        var a=i*Math.PI/4;
        add(new THREE.ConeGeometry(0.06*W, 0.22*W, 10), null,
            cx+Math.cos(a)*0.52*W, cyC+0.11*W, cz+Math.sin(a)*0.52*W);
      }
    }else if(kind==='veil' || kind==='headscarf'){
      var yS=m.minY + H_NECK*m.H;                 /* the shoulder line */
      var hgt=Math.max(1e-3, yTop-yS);
      var soft=new THREE.MeshStandardMaterial(
        {color:base, roughness:0.95, metalness:0, transparent:true, opacity:0.85,
         side:THREE.DoubleSide});
      add(new THREE.ConeGeometry(0.95*W, hgt, 28, 1, true), soft, cx, yS+hgt/2, cz);
    }
  }

  function eyewear(ctx, g, m){
    var kind=word(ctx,'accessories.eyewear');
    if(!kind || kind==='none') return;
    var W=m.headW, HH=m.headH, cx=m.headCx, cz=m.headCz, yTop=m.yTop, f=m.front;
    var ey=yTop-0.42*HH, zf=cz + f*0.5*W;
    var frame=new THREE.MeshStandardMaterial({color:srgb(0x2a2a2e), roughness:0.4, metalness:0.3});
    var glass=new THREE.MeshStandardMaterial({color:srgb(0x14141a), roughness:0.2, metalness:0.1,
                                              transparent:true, opacity:0.85,
                                              side:THREE.DoubleSide});
    function add(geo, mat, x, y, z, rx, ry, rz){
      var o=new THREE.Mesh(geo, mat||frame);
      o.position.set(x,y,z);
      if(rx||ry||rz) o.rotation.set(rx||0, ry||0, rz||0);
      g.add(o); return o;
    }
    var r = (kind==='pince-nez') ? 0.12*W : (kind==='goggles' ? 0.20*W : 0.16*W);
    var dx = (kind==='pince-nez') ? 0.14*W : 0.20*W;
    var flat = (kind==='glasses' || kind==='sunglasses') ? 0.8 : 1.0;
    var sides = (kind==='monocle') ? [1] : [-1, 1];

    for(var i=0;i<sides.length;i++){
      var x=cx + sides[i]*dx;
      var ring=add(new THREE.TorusGeometry(r, 0.022*W, 10, 28), frame, x, ey, zf);
      if(flat!==1) ring.scale.set(1, flat, 1);
      if(kind==='sunglasses'){
        var lens=add(new THREE.CircleGeometry(r*0.98, 24), glass, x, ey, zf - f*0.006*W);
        if(flat!==1) lens.scale.set(1, flat, 1);
      }
    }
    if(kind!=='monocle'){
      /* bridge across the nose */
      add(new THREE.CylinderGeometry(0.016*W, 0.016*W, 2*dx, 10), frame,
          cx, ey+0.02*W, zf, 0, 0, Math.PI/2);
    }
    if(kind==='glasses' || kind==='round glasses' || kind==='sunglasses'){
      /* temples, back to the ears */
      var zBack=cz - f*0.45*W, zMid=(zf+zBack)/2, len=Math.abs(zf-zBack);
      for(i=0;i<2;i++){
        add(new THREE.CylinderGeometry(0.014*W, 0.014*W, len, 8), frame,
            cx + (i?1:-1)*(dx + r*0.92), ey, zMid, Math.PI/2, 0, 0);
      }
    }
    if(kind==='goggles'){
      add(new THREE.TorusGeometry(0.54*W, 0.03*W, 8, 36), frame, cx, ey, cz, Math.PI/2, 0, 0);
    }
  }

  /* ── the hook ──────────────────────────────────────────────────────────── */
  function runFor(ctx){
    if(!ctx || !ctx.model) return;
    var root=ctx.model, store=ctx.store;
    if(store.dress && store.dress.parent!==root) store.dress=null;   /* left on an old body */
    clearDress(store);
    var m=metrics(ctx);
    if(!m) return;
    paint(ctx, m);
    applyScale(ctx, m);
    buildDress(ctx, m);
  }
  function run(why){
    if(!CS3 || CS3.failed || !CS3.model) return;
    runFor(mainCtx());
    if(typeof cs3dLoop==='function') cs3dLoop();
  }

  CS3_HOOKS.push(function(why){
    try{ run(why); }catch(e){ console.warn('char_dress', why, e); }
  });
  if(CS3.model){ try{ run('init'); }catch(e){ console.warn('char_dress init', e); } }

  window.CSDRESS = {run:run, runFor:runFor, skinColour:skinColour, srgb:srgb,
                    base:function(){ return CS3._dressBase; }};
})();
