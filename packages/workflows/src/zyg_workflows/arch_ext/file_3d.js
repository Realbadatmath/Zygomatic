// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* file_3d — File ▸ 3D interchange (2026-09-07).
   Wires five dock icons that were placeholders: f_glb (Export glTF),
   f_stl (Export STL), f_import (Import mesh), f_pc (Point cloud),
   f_link (Link model). Nothing in inspection.html was edited.

   THE ONE IDEA. Everything here is a file crossing the boundary of the tab,
   and the tab cannot see a file. So both directions go through the server
   extension arch_server_ext/file_3d.py: an export is downloaded to the user
   AND copied to data/architecture/exports/ (so Blender, a test, or the next
   pipeline stage can open the very bytes the browser made); an import is
   uploaded to data/architecture/imports/ under a content id and then fetched
   back by URL. The drawing stores that id and a scale — never geometry.

   THE ONE AWKWARDNESS. arGeom is synchronous and a mesh file is not. The
   studio already solved this once for pack assets (`case 'asset'` in arGeom +
   arAssetLoad): return a placeholder crate now, fetch, then swap the real
   children in. The three kinds here do the same, and because arRebuild only
   knows to kick off that fetch for kind 'asset', we wrap arRebuild — function
   declarations of the page are writable globals.

   Vendored (MIT, three.js r144 examples/js, in vendor/three/):
     GLTFExporter.js  STLExporter.js  OBJLoader.js  STLLoader.js
   GLTFLoader.js is already loaded by the page. */
(function(){
'use strict';

var EXT_BASE = '/inspect/api/architecture/ext/file_3d/';
var F3D_MAX_POINTS = 2000000;          /* past this a cloud is decimated by stride */

/* per-id caches: one fetch and one parse per file, clones per placement */
var f3dMeshCache  = new Map();         /* id -> {p: Promise<THREE.Object3D>} */
var f3dCloudCache = new Map();         /* id -> {p: Promise<{pos, col, n}>}  */
var f3dLinkCache  = new Map();         /* pid -> {p: Promise, doc: {...}}    */
var f3dScripts    = {};                /* file -> Promise, loaded once       */

window.f3dCaches = {mesh: f3dMeshCache, cloud: f3dCloudCache, link: f3dLinkCache};

/* ── vendored three modules, loaded on first use ─────────────────────────── */
function f3dScript(global, file){
  if(window.THREE && THREE[global]) return Promise.resolve(THREE[global]);
  if(f3dScripts[file]) return f3dScripts[file];
  f3dScripts[file] = new Promise(function(res, rej){
    var s = document.createElement('script');
    s.src = 'vendor/three/' + file;
    s.onload = function(){
      if(window.THREE && THREE[global]) res(THREE[global]);
      else rej(new Error(file + ' loaded but THREE.' + global + ' is missing'));
    };
    s.onerror = function(){ rej(new Error('could not load vendor/three/' + file)); };
    document.head.appendChild(s);
  });
  return f3dScripts[file];
}
function f3dExporterGLTF(){ return f3dScript('GLTFExporter', 'GLTFExporter.js'); }
function f3dExporterSTL(){  return f3dScript('STLExporter',  'STLExporter.js'); }
function f3dLoaderOBJ(){    return f3dScript('OBJLoader',    'OBJLoader.js'); }
function f3dLoaderSTL(){    return f3dScript('STLLoader',    'STLLoader.js'); }

/* ── small helpers ───────────────────────────────────────────────────────── */
function f3dOpt(opt, key, dflt, question){
  /* the SAME icon serves a person and the assistant: an args object answers
     exactly, a click asks. */
  if(opt && typeof opt === 'object' && opt[key] !== undefined && opt[key] !== null) return opt[key];
  if(question === undefined) return dflt;
  var a = prompt(question, dflt === undefined || dflt === null ? '' : String(dflt));
  return a === null ? null : a;
}
function f3dNum(v, d){ var n = parseFloat(v); return isFinite(n) ? n : d; }
function f3dSlug(s){ return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 48) || 'drawing'; }
function f3dDocName(){ return f3dSlug((AR.doc && AR.doc.name) || 'drawing'); }
function f3dBytes(n){ return n < 1024 ? n + ' B' : (n < 1048576 ? (n / 1024).toFixed(1) + ' kB' : (n / 1048576).toFixed(2) + ' MB'); }
function f3dExt(name){ return String(name || '').toLowerCase().split('?')[0].split('.').pop(); }

function f3dPost(op, body){
  return fetch(EXT_BASE + op, {method: 'POST', headers: {'Content-Type': 'application/json'},
                               body: JSON.stringify(body || {})})
    .then(function(r){ return r.json(); });
}
function f3dB64(buf){
  /* btoa on a 10 MB string throws in some engines; chunk it. */
  var b = new Uint8Array(buf), s = '', CH = 0x8000;
  for(var i = 0; i < b.length; i += CH) s += String.fromCharCode.apply(null, b.subarray(i, i + CH));
  return btoa(s);
}

/* Visible, real records — the set every export means by "the drawing".
   Guides and openings are notation, not matter: a 3D print of an opening is a
   3D print of nothing, and a guide line has no volume to slice. */
function f3dExportable(){
  return AR.objs.filter(function(o){
    return !o.hidden && o.node && o.kind !== 'opening' && String(o.kind).indexOf('guide_') !== 0
           && String(o.kind).indexOf('sculpt_') !== 0;
  });
}

/* A flat export material: colour + albedo map only. A glTF viewer and a slicer
   both want one PBR material per surface, not the studio's section-clipped,
   wireframe-toggled live material — and carrying the normal/rough maps would
   quadruple a 3 MB file for something no massing study needs. */
var f3dMatCache = null;
function f3dFlatMat(src){
  f3dMatCache = f3dMatCache || new Map();
  var key = src ? (src.uuid || 'x') : 'none';
  if(f3dMatCache.has(key)) return f3dMatCache.get(key);
  var m = new THREE.MeshStandardMaterial({
    color: src && src.color ? src.color.clone() : new THREE.Color(0x9a9a94),
    roughness: src && src.roughness !== undefined ? src.roughness : 0.9,
    metalness: src && src.metalness !== undefined ? src.metalness : 0.0,
    map: src && src.map ? src.map : null,
    vertexColors: !!(src && src.vertexColors),
    transparent: !!(src && src.transparent),
    opacity: src && src.opacity !== undefined ? src.opacity : 1,
    side: THREE.FrontSide
  });
  m.name = (src && src.name) || (src && src.userData && src.userData.arId) || 'studio';
  f3dMatCache.set(key, m);
  return m;
}

/* The scene an exporter sees: clones of the visible records' nodes, named with
   the drawing's own names, materials flattened. Cloned rather than exported in
   place because the live nodes carry the selection outline, the section
   clipping planes and the wire material — none of which belongs in a file. */
function f3dExportGroup(){
  var root = new THREE.Group();
  root.name = (AR.doc && AR.doc.name) || 'drawing';
  var recs = f3dExportable(), meshes = 0, tris = 0, used = 0;
  f3dMatCache = new Map();
  recs.forEach(function(rec){
    var g = new THREE.Group();
    g.name = (rec.name || arKindLabel(rec.kind) || rec.kind) + ' [' + rec.id + ']';
    g.userData = {studio_id: rec.id, studio_kind: rec.kind, studio_material: rec.mat};
    var any = false;
    rec.node.traverse(function(o){
      if(!o.isMesh || !o.geometry || !o.geometry.attributes || !o.geometry.attributes.position) return;
      if(o.userData && o.userData.arPlaceholder) return;   /* a crate waiting for its file is not the model */
      var mesh = new THREE.Mesh(o.geometry, f3dFlatMat(o.material));
      /* the node's own local matrix, so a nested import keeps its layout */
      o.updateMatrixWorld(true);
      mesh.matrixAutoUpdate = false;
      mesh.matrix.copy(o.matrixWorld).premultiply(new THREE.Matrix4().copy(rec.node.matrixWorld).invert());
      mesh.matrix.decompose(mesh.position, mesh.quaternion, mesh.scale);
      mesh.matrixAutoUpdate = true;
      mesh.name = g.name + (any ? ' part' : '');
      g.add(mesh);
      meshes++;
      var gg = o.geometry;
      tris += gg.index ? gg.index.count / 3 : gg.attributes.position.count / 3;
      any = true;
    });
    if(!any) return;
    rec.node.updateMatrixWorld(true);
    g.position.set(rec.x, rec.y, rec.z);
    g.rotation.set(rec.rx || 0, rec.ry || 0, rec.rz || 0);
    var s = rec.s || 1; g.scale.set(s, s, s);
    root.add(g);
    used++;
  });
  return {group: root, objects: used, meshes: meshes, tris: Math.round(tris)};
}

/* Download AND keep a copy server-side. Both, always: the download is for the
   person, the server copy is what anything else in this system can reach. */
function f3dDeliver(bytes, ext, base, extra){
  var blob = new Blob([bytes], {type: ext === 'glb' ? 'model/gltf-binary' : 'model/stl'});
  var fname = base + '.' + ext;
  arDownload(blob, fname);
  return f3dPost('save', {name: base, ext: ext, data_b64: f3dB64(bytes.buffer || bytes)})
    .then(function(r){
      if(r && r.ok){
        arToast(extra + ' — downloaded <b>' + esc(fname) + '</b> (' + f3dBytes(r.bytes)
                + ') and kept a copy at <code>' + esc(r.rel) + '</code>.');
      } else {
        arToast(extra + ' — downloaded <b>' + esc(fname) + '</b>, but the server copy failed: '
                + esc((r && r.error) || 'no answer') + '.', 'warn');
      }
      return r || {};
    })
    .catch(function(e){
      arToast('Downloaded <b>' + esc(fname) + '</b>, but the server copy failed: ' + esc(e.message || e) + '.', 'warn');
      return {error: String(e && e.message || e)};
    });
}

/* ── f_glb — export .glb ─────────────────────────────────────────────────── */
function f3dExportGLB(opt){
  var binary = f3dOpt(opt, 'binary', true);
  binary = !(binary === false || binary === 'false' || binary === 0);
  var base = f3dSlug(f3dOpt(opt, 'name', f3dDocName()));
  var built = f3dExportGroup();
  if(!built.objects){ arToast('Nothing visible to export — the drawing is empty or everything is hidden.', 'warn'); return Promise.resolve(null); }
  arToast('Exporting ' + built.objects + ' object' + (built.objects === 1 ? '' : 's') + ' as glTF…');
  var pending = f3dExporterGLTF().then(function(Exporter){
    return new Promise(function(res, rej){
      new Exporter().parse(built.group, res, rej,
        {binary: binary, embedImages: true, onlyVisible: true, truncateDrawRange: false});
    });
  }).then(function(out){
    var bytes = binary ? new Uint8Array(out) : new TextEncoder().encode(JSON.stringify(out));
    return f3dDeliver(bytes, binary ? 'glb' : 'gltf', base,
                      built.objects + ' object' + (built.objects === 1 ? '' : 's') + ', '
                      + built.meshes + ' mesh' + (built.meshes === 1 ? '' : 'es') + ', '
                      + built.tris.toLocaleString() + ' triangles')
      .then(function(r){ return {ok: true, objects: built.objects, meshes: built.meshes, tris: built.tris, save: r}; });
  }).catch(function(e){
    arToast('glTF export failed: ' + esc(e.message || e), 'bad');
    return {error: String(e && e.message || e)};
  });
  AR_EXT.tools.f_glb._pending = pending;
  return pending;
}

/* ── f_stl — export binary .stl ──────────────────────────────────────────── */
function f3dExportSTL(opt){
  var base = f3dSlug(f3dOpt(opt, 'name', f3dDocName()));
  var built = f3dExportGroup();
  if(!built.objects){ arToast('Nothing visible to export — the drawing is empty or everything is hidden.', 'warn'); return Promise.resolve(null); }
  var pending = f3dExporterSTL().then(function(Exporter){
    /* STL has no unit: a slicer reads the numbers and calls them millimetres by
       convention. We write METRES — the studio's one world scale — so a 12 m
       wall is 12 units. Scale by 1000 in the slicer for a full-size print. */
    var dv = new Exporter().parse(built.group, {binary: true});
    var bytes = dv instanceof DataView ? new Uint8Array(dv.buffer, dv.byteOffset, dv.byteLength)
                                       : new TextEncoder().encode(String(dv));
    var tris = dv instanceof DataView ? dv.getUint32(80, true) : built.tris;
    return f3dDeliver(bytes, 'stl', base,
                      built.objects + ' object' + (built.objects === 1 ? '' : 's') + ', '
                      + tris.toLocaleString() + ' triangles, binary STL in METRES')
      .then(function(r){ return {ok: true, objects: built.objects, tris: tris, save: r}; });
  }).catch(function(e){
    arToast('STL export failed: ' + esc(e.message || e), 'bad');
    return {error: String(e && e.message || e)};
  });
  AR_EXT.tools.f_stl._pending = pending;
  return pending;
}

/* ── parsing an imported mesh ────────────────────────────────────────────── */
function f3dFetchBuffer(id){
  return fetch(EXT_BASE + 'file?id=' + encodeURIComponent(id)).then(function(r){
    if(!r.ok) return r.text().then(function(t){ throw new Error('file ' + id + ': ' + t.slice(0, 120)); });
    return r.arrayBuffer();
  });
}
/* A glb that names its textures by relative path — "Textures/colormap.png" — is
   the ordinary case in every free asset pack, and parse() has no directory to
   resolve them against. r144 answers a failed image with null and then sets
   .encoding on it, which throws and loses the whole model over a missing
   picture. Point every unresolvable URI at one blank pixel instead: the mesh
   arrives, the material keeps its colour, and nothing throws. */
var F3D_BLANK = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAA'
              + 'C0lEQVR42mP8Xw8AAoMBgDTD2qgAAAAASUVORK5CYII=';
function f3dLoadingManager(){
  var m = new THREE.LoadingManager();
  m.setURLModifier(function(url){
    var u = String(url || '');
    return (/^(data:|blob:|https?:|\/)/).test(u) ? u : F3D_BLANK;
  });
  return m;
}
function f3dParseMesh(id, ext){
  ext = String(ext || 'glb').toLowerCase();
  return f3dFetchBuffer(id).then(function(buf){
    if(ext === 'glb' || ext === 'gltf'){
      if(!THREE.GLTFLoader) throw new Error('GLTFLoader missing');
      return new Promise(function(res, rej){
        new THREE.GLTFLoader(f3dLoadingManager())
          .parse(buf, '', function(g){ res(g.scene || (g.scenes && g.scenes[0])); }, rej);
      });
    }
    if(ext === 'obj'){
      return f3dLoaderOBJ().then(function(L){ return new L().parse(new TextDecoder().decode(buf)); });
    }
    if(ext === 'stl' || ext === 'ply'){
      return f3dLoaderSTL().then(function(L){
        var geo = new L().parse(buf);
        geo.computeVertexNormals();
        return new THREE.Mesh(geo, new THREE.MeshStandardMaterial({color: 0xb9b6ad, roughness: 0.85}));
      });
    }
    throw new Error('no loader for .' + ext);
  });
}
function f3dMeshScene(id, ext){
  var hit = f3dMeshCache.get(id);
  if(!hit){ hit = {p: f3dParseMesh(id, ext)}; f3dMeshCache.set(id, hit); }
  return hit.p;
}

/* ── parsing a point cloud ───────────────────────────────────────────────── */
function f3dParseXYZ(text){
  /* "x y z [r g b]" per line, whitespace or comma separated; # is a comment.
     Colours are 0..1 floats or 0..255 ints — both appear in the wild. */
  var lines = text.split('\n'), pos = [], col = [], any = false;
  for(var i = 0; i < lines.length; i++){
    var L = lines[i];
    if(!L || L.charCodeAt(0) === 35) continue;              /* '#' */
    var f = L.trim().split(/[\s,]+/);
    if(f.length < 3) continue;
    var x = parseFloat(f[0]), y = parseFloat(f[1]), z = parseFloat(f[2]);
    if(!isFinite(x) || !isFinite(y) || !isFinite(z)) continue;
    pos.push(x, y, z);
    if(f.length >= 6){
      var r = parseFloat(f[3]), g = parseFloat(f[4]), b = parseFloat(f[5]);
      if(isFinite(r) && isFinite(g) && isFinite(b)){
        var sc = (r > 1 || g > 1 || b > 1) ? 1 / 255 : 1;
        col.push(r * sc, g * sc, b * sc); any = true;
      } else { col.push(1, 1, 1); }
    } else { col.push(1, 1, 1); }
  }
  return {pos: pos, col: any ? col : null, n: pos.length / 3};
}
function f3dParsePLY(buf){
  /* ASCII and binary_little_endian, vertex element only — a survey cloud has
     no faces, and a PLY mesh belongs in f_import, not here. */
  var head = new TextDecoder().decode(new Uint8Array(buf, 0, Math.min(buf.byteLength, 8192)));
  var end = head.indexOf('end_header');
  if(end < 0) throw new Error('not a PLY (no end_header)');
  var hdrEnd = head.indexOf('\n', end) + 1;
  var hdr = head.slice(0, hdrEnd).split('\n');
  var fmt = 'ascii', n = 0, props = [], inVert = false;
  var SZ = {char: 1, uchar: 1, int8: 1, uint8: 1, short: 2, ushort: 2, int16: 2, uint16: 2,
            int: 4, uint: 4, int32: 4, uint32: 4, float: 4, float32: 4, double: 8, float64: 8};
  hdr.forEach(function(line){
    var t = line.trim().split(/\s+/);
    if(t[0] === 'format') fmt = t[1];
    else if(t[0] === 'element'){ inVert = (t[1] === 'vertex'); if(inVert) n = parseInt(t[2], 10) || 0; }
    else if(t[0] === 'property' && inVert && t[1] !== 'list') props.push({type: t[1], name: t[2]});
  });
  var ix = {}, off = 0, stride = 0;
  props.forEach(function(p){ ix[p.name] = {off: off, type: p.type}; off += SZ[p.type] || 4; });
  stride = off;
  var pos = [], col = [], any = false;
  var need = ['x', 'y', 'z'];
  for(var k = 0; k < need.length; k++) if(!ix[need[k]]) throw new Error('PLY has no ' + need[k] + ' property');
  var hasC = !!(ix.red && ix.green && ix.blue);
  function rd(dv, base, p){
    var o = base + p.off, t = p.type;
    if(t === 'float' || t === 'float32') return dv.getFloat32(o, true);
    if(t === 'double' || t === 'float64') return dv.getFloat64(o, true);
    if(t === 'uchar' || t === 'uint8') return dv.getUint8(o);
    if(t === 'char' || t === 'int8') return dv.getInt8(o);
    if(t === 'short' || t === 'int16') return dv.getInt16(o, true);
    if(t === 'ushort' || t === 'uint16') return dv.getUint16(o, true);
    if(t === 'uint' || t === 'uint32') return dv.getUint32(o, true);
    return dv.getInt32(o, true);
  }
  if(fmt === 'ascii'){
    var body = new TextDecoder().decode(new Uint8Array(buf, hdrEnd)).split('\n');
    for(var i = 0, got = 0; i < body.length && got < n; i++){
      var f = body[i].trim().split(/\s+/);
      if(f.length < props.length) continue;
      var pi = props.map(function(p){ return p.name; });
      pos.push(parseFloat(f[pi.indexOf('x')]), parseFloat(f[pi.indexOf('y')]), parseFloat(f[pi.indexOf('z')]));
      if(hasC){
        var isF = ix.red.type === 'float' || ix.red.type === 'float32';
        var sc = isF ? 1 : 1 / 255;
        col.push(parseFloat(f[pi.indexOf('red')]) * sc, parseFloat(f[pi.indexOf('green')]) * sc,
                 parseFloat(f[pi.indexOf('blue')]) * sc);
        any = true;
      } else col.push(1, 1, 1);
      got++;
    }
  } else {
    var dv = new DataView(buf), base = hdrEnd;
    for(var j = 0; j < n && base + stride <= buf.byteLength; j++, base += stride){
      pos.push(rd(dv, base, ix.x), rd(dv, base, ix.y), rd(dv, base, ix.z));
      if(hasC){
        var isFl = ix.red.type === 'float' || ix.red.type === 'float32';
        var s2 = isFl ? 1 : 1 / 255;
        col.push(rd(dv, base, ix.red) * s2, rd(dv, base, ix.green) * s2, rd(dv, base, ix.blue) * s2);
        any = true;
      } else col.push(1, 1, 1);
    }
  }
  return {pos: pos, col: any ? col : null, n: pos.length / 3};
}
function f3dParseCloud(id, ext){
  ext = String(ext || 'xyz').toLowerCase();
  return f3dFetchBuffer(id).then(function(buf){
    var c = (ext === 'ply') ? f3dParsePLY(buf) : f3dParseXYZ(new TextDecoder().decode(buf));
    if(!c.n) throw new Error('no points in the file');
    if(c.n > F3D_MAX_POINTS){
      /* every k-th point, so the decimated cloud still covers the whole survey
         rather than being the first two million points of it */
      var step = Math.ceil(c.n / F3D_MAX_POINTS), P = [], C = c.col ? [] : null;
      for(var i = 0; i < c.n; i += step){
        P.push(c.pos[i * 3], c.pos[i * 3 + 1], c.pos[i * 3 + 2]);
        if(C) C.push(c.col[i * 3], c.col[i * 3 + 1], c.col[i * 3 + 2]);
      }
      c = {pos: P, col: C, n: P.length / 3, decimated: true, was: c.n};
    }
    return c;
  });
}
function f3dCloud(id, ext){
  var hit = f3dCloudCache.get(id);
  if(!hit){ hit = {p: f3dParseCloud(id, ext)}; f3dCloudCache.set(id, hit); }
  return hit.p;
}

/* ── the linked drawing ──────────────────────────────────────────────────── */
function f3dLinkDoc(pid){
  var hit = f3dLinkCache.get(pid);
  if(!hit){
    hit = {p: fetch('/inspect/api/architecture/project?id=' + encodeURIComponent(pid))
              .then(function(r){ return r.json(); })
              .then(function(j){
                if(!j || !j.ok || !j.doc) throw new Error((j && j.error) || 'no such drawing');
                hit.doc = j.doc;
                return j.doc;
              })};
    f3dLinkCache.set(pid, hit);
  }
  return hit.p;
}
/* The linked drawing's records, built through the SAME arGeom the host uses and
   baked into the link record's own frame. One record, many parts: a reference
   model is context, not forty objects in the outliner. */
function f3dLinkParts(pid){
  var hit = f3dLinkCache.get(pid);
  if(!hit || !hit.doc) return null;
  var out = [], m = new THREE.Matrix4(), e = new THREE.Euler(), q = new THREE.Quaternion();
  var objs = hit.doc.objects || [], cap = 0;
  for(var i = 0; i < objs.length && cap < 4000; i++){
    var o = objs[i];
    if(!o || o.hidden) continue;
    if(o.kind === 'link' || o.kind === 'opening') continue;   /* no nested links; an opening is a void */
    var parts;
    try{ parts = arGeom(o.kind, o.p || {}); }catch(err){ continue; }
    if(!parts || !parts.length) continue;
    e.set(o.rx || 0, o.ry || 0, o.rz || 0);
    q.setFromEuler(e);
    var s = o.s || 1;
    m.compose(new THREE.Vector3(o.x || 0, o.y || 0, o.z || 0), q, new THREE.Vector3(s, s, s));
    for(var j = 0; j < parts.length; j++){
      var pt = parts[j];
      if(!pt.g || pt.line || pt.ph) continue;                 /* lines and crates are not the model */
      pt.g.applyMatrix4(m);
      out.push({g: pt.g, sub: pt.sub || o.mat || 'mat_concrete'});
      cap++;
    }
  }
  return out;
}

/* ── geometry: the placeholder every async kind starts as ────────────────── */
function f3dCrate(p, k, w, h, d){
  return [{g: k.box(k.num(p.bw, w), k.num(p.bh, h), k.num(p.bd, d), 0, k.num(p.bh, h) / 2, 0),
           sub: 'mat_glass', ph: 1}];
}
AR_EXT.geom.mesh_file = function(p, k){
  var s = k.num(p.sx, 1);
  return f3dCrate(p, k, 1.0 * s, 1.0 * s, 1.0 * s);
};
AR_EXT.geom.point_cloud = function(p, k){
  return f3dCrate(p, k, 4, 0.2, 4);
};
AR_EXT.geom.link = function(p, k){
  var parts = f3dLinkParts(String(p.pid || ''));
  if(parts && parts.length) return parts;
  return f3dCrate(p, k, 6, 3, 6);
};
AR_EXT.label.mesh_file  = 'Imported mesh';
AR_EXT.label.point_cloud = 'Point cloud';
AR_EXT.label.link       = 'Linked drawing';

/* ── the async half: swap the real thing in when the bytes land ──────────── */
function f3dDropPlaceholders(rec){
  rec.node.children.slice().forEach(function(c){
    if(c.userData && c.userData.arPlaceholder){
      rec.node.remove(c);
      if(c.geometry) c.geometry.dispose();
    }
  });
}
function f3dFail(rec, why){
  rec.f3dErr = String(why || 'load failed');
  if(!AR._f3dToast){ AR._f3dToast = 1;
    arToast('Could not load one imported file (' + esc(rec.f3dErr) + ') — it is showing as a placeholder.', 'warn');
    setTimeout(function(){ AR._f3dToast = 0; }, 4000); }
}
function f3dLoad(rec){
  if(!rec || !rec.node) return null;
  var p = rec.p || {}, pending = null;
  if(rec.kind === 'mesh_file'){
    var id = String(p.id || '');
    if(!id){ f3dFail(rec, 'no file id'); return null; }
    pending = f3dMeshScene(id, p.ext || f3dExt(p.name) || 'glb').then(function(scene){
      if(!rec.node || rec.kind !== 'mesh_file') return;       /* deleted or retyped mid-flight */
      var inst = scene.clone(true), sx = f3dNum(p.sx, 1) || 1;
      inst.scale.set(sx, sx, sx);
      inst.traverse(function(o){
        o.userData.arId = rec.id;
        o.userData.arShared = 1;                              /* buffers belong to the cache */
        if(o.isMesh){ o.castShadow = true; o.receiveShadow = true; o.userData.sub = 'mesh_file'; }
      });
      f3dDropPlaceholders(rec);
      rec.node.add(inst);
      rec.f3dOk = true;
      rec.f3dErr = '';
    }).catch(function(e){ f3dFail(rec, e && e.message || e); });
  } else if(rec.kind === 'point_cloud'){
    var cid = String(p.id || '');
    if(!cid){ f3dFail(rec, 'no file id'); return null; }
    pending = f3dCloud(cid, p.ext || f3dExt(p.name) || 'xyz').then(function(c){
      if(!rec.node || rec.kind !== 'point_cloud') return;
      var geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(c.pos, 3));
      var mat = {size: Math.max(0.002, f3dNum(p.size, 0.03)), sizeAttenuation: true};
      if(c.col){ geo.setAttribute('color', new THREE.Float32BufferAttribute(c.col, 3)); mat.vertexColors = true; }
      else { mat.color = 0x9fd3e0; }
      var pts = new THREE.Points(geo, new THREE.PointsMaterial(mat));
      if(f3dNum(p.zup, 0)) pts.rotation.x = -Math.PI / 2;     /* a survey delivered Z-up */
      pts.userData.arId = rec.id;
      pts.userData.sub = 'point_cloud';
      f3dDropPlaceholders(rec);
      rec.node.add(pts);
      rec.p.n = c.n;                                          /* a parameter, not geometry */
      rec.f3dOk = true;
      rec.f3dErr = '';
      if(c.decimated) arToast('Point cloud decimated from ' + c.was.toLocaleString() + ' to '
                              + c.n.toLocaleString() + ' points (the 2 M ceiling).', 'warn');
    }).catch(function(e){ f3dFail(rec, e && e.message || e); });
  } else if(rec.kind === 'link'){
    var pid = String(p.pid || '');
    if(!pid){ f3dFail(rec, 'no drawing id'); return null; }
    if(f3dLinkCache.has(pid) && f3dLinkCache.get(pid).doc) return null;   /* already built from cache */
    pending = f3dLinkDoc(pid).then(function(doc){
      if(!rec.node || rec.kind !== 'link') return;
      if(!rec.p.name) rec.p.name = String(doc.name || pid).slice(0, 60);
      /* every link on this drawing pointing at the same document */
      AR.objs.forEach(function(o){ if(o.kind === 'link' && String((o.p || {}).pid) === pid) arRebuild(o); });
      rec.f3dOk = true;
      rec.f3dErr = '';
      arSelSync();
    }).catch(function(e){ f3dFail(rec, e && e.message || e); });
  }
  if(pending) rec._load = pending;
  return pending;
}
window.f3dLoad = f3dLoad;

/* ── placing an imported file ────────────────────────────────────────────── */
function f3dPlace(kind, p, cell){
  var x = 0, z = 0;
  if(cell && typeof cell === 'string'){
    /* the cell grid the assistant speaks: A1 = the first cell, AR_CELL_M wide */
    var m = /^([A-Za-z]+)\s*(\d+)$/.exec(cell.trim());
    if(m){
      var col = 0, L = m[1].toUpperCase();
      for(var i = 0; i < L.length; i++) col = col * 26 + (L.charCodeAt(i) - 64);
      x = (col - 1) * AR_CELL_M + AR_CELL_M / 2;
      z = (parseInt(m[2], 10) - 1) * AR_CELL_M + AR_CELL_M / 2;
    }
  } else if(AR.controls && AR.controls.target){
    x = AR.controls.target.x; z = AR.controls.target.z;
  }
  arPush();
  var rec = arNewObj(kind, p, x, z, AR.level || 0);
  if(p.name) rec.name = String(p.name).slice(0, 60);
  arSelect([rec.id]);
  arOutliner(); arPanel(); arHud(); arDirty(true);
  return rec;
}

/* A file picker for a person; data_b64 / id / path for the assistant. */
function f3dPickFile(accept){
  return new Promise(function(res){
    var inp = document.createElement('input');
    inp.type = 'file'; inp.accept = accept; inp.style.display = 'none';
    inp.onchange = function(){
      var f = inp.files && inp.files[0];
      document.body.removeChild(inp);
      if(!f){ res(null); return; }
      var fr = new FileReader();
      fr.onload = function(){ res({name: f.name, data_b64: f3dB64(fr.result)}); };
      fr.onerror = function(){ res(null); };
      fr.readAsArrayBuffer(f);
    };
    document.body.appendChild(inp);
    inp.click();
  });
}

/* id | {data_b64,name} | {path} -> {id, ext} on the server. One helper for both
   f_import and f_pc: an import is an import whether it becomes a mesh or a
   cloud, and only the parser downstream differs. */
function f3dResolve(opt, accept){
  var id = opt && typeof opt === 'object' ? (opt.id || '') : '';
  if(id) return Promise.resolve({ok: true, id: String(id), ext: String((opt && opt.ext) || '') || null});
  var b64 = opt && typeof opt === 'object' ? (opt.data_b64 || opt.data || '') : '';
  var name = (opt && typeof opt === 'object' && opt.name) || (opt && typeof opt === 'object' && opt.path) || '';
  if(b64) return f3dPost('upload', {name: name || 'upload', data_b64: b64, ext: opt.ext || f3dExt(name)});
  if(opt && typeof opt === 'object' && opt.path)
    return Promise.resolve({error: 'a server path is not readable from the tab — pass data_b64 or an id'});
  return f3dPickFile(accept).then(function(f){
    if(!f) return {error: 'cancelled'};
    return f3dPost('upload', {name: f.name, data_b64: f.data_b64, ext: f3dExt(f.name)});
  });
}

/* ── f_import — a mesh file as one record ────────────────────────────────── */
function f3dImportMesh(opt){
  var pending = f3dResolve(opt, '.glb,.gltf,.obj,.stl')
    .then(function(r){
      if(!r || !r.ok){
        if(r && r.error === 'cancelled') return null;
        arToast('Import failed: ' + esc((r && r.error) || 'no answer'), 'bad');
        return null;
      }
      var name = (opt && opt.name) || r.id;
      var rec = f3dPlace('mesh_file', {id: r.id, ext: r.ext || 'glb',
                                       sx: f3dNum(opt && opt.scale !== undefined ? opt.scale : (opt && opt.sx), 1) || 1,
                                       name: String(name).slice(0, 60)},
                         opt && opt.cell);
      return (rec._load || Promise.resolve()).then(function(){
        var tris = 0, meshes = 0;
        rec.node.traverse(function(o){
          if(o.isMesh && o.geometry && o.geometry.attributes && o.geometry.attributes.position && !(o.userData || {}).arPlaceholder){
            meshes++;
            tris += o.geometry.index ? o.geometry.index.count / 3 : o.geometry.attributes.position.count / 3;
          }
        });
        if(rec.f3dErr) arToast('Imported <b>' + esc(rec.name) + '</b> as a placeholder — ' + esc(rec.f3dErr) + '.', 'warn');
        else arToast('Imported <b>' + esc(rec.name) + '</b> (' + rec.id + '): ' + meshes + ' mesh'
                     + (meshes === 1 ? '' : 'es') + ', ' + Math.round(tris).toLocaleString()
                     + ' triangles, from <code>' + esc(r.id) + '.' + esc(r.ext || 'glb') + '</code>.');
        return rec;
      });
    })
    .catch(function(e){ arToast('Import failed: ' + esc(e.message || e), 'bad'); return null; });
  AR_EXT.tools.f_import._pending = pending;
  return pending;
}

/* ── f_pc — a survey point cloud ─────────────────────────────────────────── */
function f3dImportCloud(opt){
  var pending = f3dResolve(opt, '.xyz,.ply,.pts')
    .then(function(r){
      if(!r || !r.ok){
        if(r && r.error === 'cancelled') return null;
        arToast('Point cloud import failed: ' + esc((r && r.error) || 'no answer'), 'bad');
        return null;
      }
      var rec = f3dPlace('point_cloud', {id: r.id, ext: r.ext || 'xyz',
                                         size: f3dNum(opt && opt.size, 0.03) || 0.03, n: 0,
                                         zup: (opt && opt.zup) ? 1 : 0,
                                         name: String((opt && opt.name) || r.id).slice(0, 60)},
                         opt && opt.cell);
      return (rec._load || Promise.resolve()).then(function(){
        var pts = null;
        rec.node.traverse(function(o){ if(o.isPoints) pts = o; });
        if(!pts) arToast('Point cloud <b>' + esc(rec.name) + '</b> did not load: ' + esc(rec.f3dErr || 'no points') + '.', 'warn');
        else arToast('Point cloud <b>' + esc(rec.name) + '</b> (' + rec.id + '): '
                     + pts.geometry.attributes.position.count.toLocaleString() + ' points'
                     + (pts.geometry.attributes.color ? ', with colour' : '') + '. Model the retrofit against it.');
        return rec;
      });
    })
    .catch(function(e){ arToast('Point cloud import failed: ' + esc(e.message || e), 'bad'); return null; });
  AR_EXT.tools.f_pc._pending = pending;
  return pending;
}

/* ── f_link — reference another saved drawing ────────────────────────────── */
function f3dLinkSheet(){
  return api('/inspect/api/architecture').then(function(d){
    var sec = ((d && d.sections) || []).filter(function(s){ return s.key === 'projects'; })[0];
    var items = [];
    ((sec && sec.groups) || []).forEach(function(g){ (g.items || []).forEach(function(it){ items.push(it); }); });
    var mine = AR.doc && AR.doc.id;
    var rows = items.filter(function(it){ return (it.p || {}).pid !== mine && !it.broken; }).map(function(it){
      var pid = (it.p || {}).pid;
      return ['<b>' + esc(it.n) + '</b><br><span class="dim">' + esc(it.note || '') + '</span>',
              '<button class="ar-btn" onclick="arTool(\'f_link\', {pid: ' + JSON.stringify(pid) + '})">Link</button>'];
    });
    var head = '<p>Reference another saved drawing into this one. The linked drawing is rebuilt from its own '
             + 'parameters, so re-linking after it changes shows the change.</p>'
             + '<p><button class="ar-btn" onclick="arTool(\'f_link\', {reload: 1})">Reload links</button></p>';
    arSheet('Link model', head + (rows.length ? arRows(rows)
            : '<p class="dim">No other saved drawings on this machine yet — save one first.</p>'));
    return rows.length;
  });
}
function f3dLink(opt){
  if(opt && opt.reload){
    f3dLinkCache.clear();
    var waits = [];
    /* arRebuild is wrapped to kick f3dLoad, which leaves its promise on rec._load;
       the reload is not finished until the re-fetched documents have been built,
       so hand that back rather than a promise of the count alone. */
    AR.objs.forEach(function(o){ if(o.kind === 'link'){ arRebuild(o); if(o._load) waits.push(o._load); } });
    var done = Promise.all(waits).then(function(){
      arSelSync();
      arToast('Cleared the link cache and rebuilt ' + waits.length + ' linked drawing'
              + (waits.length === 1 ? '' : 's') + '.');
      return waits.length;
    });
    AR_EXT.tools.f_link._pending = done;
    return done;
  }
  var pid = opt && typeof opt === 'object' ? String(opt.pid || '') : '';
  if(!pid){ var s = f3dLinkSheet(); AR_EXT.tools.f_link._pending = s; return s; }
  if(AR.doc && AR.doc.id && pid === AR.doc.id){
    arToast('A drawing cannot link itself.', 'warn');
    return Promise.resolve(null);
  }
  var rec = f3dPlace('link', {pid: pid, name: String((opt && opt.name) || pid).slice(0, 60)}, opt && opt.cell);
  var pending = (rec._load || Promise.resolve()).then(function(){
    var tris = 0;
    rec.node.traverse(function(o){
      if(o.isMesh && o.geometry && o.geometry.attributes && o.geometry.attributes.position && !(o.userData || {}).arPlaceholder)
        tris += o.geometry.index ? o.geometry.index.count / 3 : o.geometry.attributes.position.count / 3;
    });
    var hit = f3dLinkCache.get(pid), n = hit && hit.doc ? (hit.doc.objects || []).length : 0;
    rec.name = 'Link: ' + (rec.p.name || pid);
    if(rec.f3dErr) arToast('Could not link <b>' + esc(pid) + '</b>: ' + esc(rec.f3dErr) + '.', 'bad');
    else arToast('Linked <b>' + esc(rec.p.name || pid) + '</b> (' + rec.id + '): ' + n + ' object'
                 + (n === 1 ? '' : 's') + ', ' + Math.round(tris).toLocaleString()
                 + ' triangles, as one reference record. Press again with Reload links after it changes.');
    arOutliner(); arPanel();
    return rec;
  });
  AR_EXT.tools.f_link._pending = pending;
  return pending;
}

/* ── registrations ───────────────────────────────────────────────────────── */
AR_EXT.tools.f_glb = {
  assist: 1,
  tip: 'Export .glb — the format a web viewer and a game engine both read. Downloads it and keeps a copy under data/architecture/exports/',
  act: function(opt){ return f3dExportGLB(opt); }
};
AR_EXT.tools.f_stl = {
  assist: 1,
  tip: 'Export .stl for a 3D print of the massing model — binary STL of everything visible, in metres. Downloads it and keeps a server copy',
  act: function(opt){ return f3dExportSTL(opt); }
};
AR_EXT.tools.f_import = {
  assist: 1,
  tip: 'Import an .obj, .glb, .gltf or .stl as a single block, for a piece of context you will not model',
  act: function(opt){ return f3dImportMesh(opt); }
};
AR_EXT.tools.f_pc = {
  assist: 1,
  tip: 'Import a survey point cloud (.xyz, .pts, .ply) and model the retrofit against it — up to 2 million points, vertex colours kept',
  act: function(opt){ return f3dImportCloud(opt); }
};
AR_EXT.tools.f_link = {
  assist: 1,
  tip: 'Reference another saved drawing into this one and keep it up to date — one record, rebuilt from the linked drawing\u2019s own parameters',
  act: function(opt){ return f3dLink(opt); }
};

AR_EXT.ready.push(function(){
  /* arRebuild kicks off the pack-asset fetch for kind 'asset' only. The three
     kinds here need the same treatment, and the seam for that is the writable
     global: every later arRebuild in the page reaches this one. */
  var base = arRebuild;
  arRebuild = function(rec){
    base(rec);
    if(rec && (rec.kind === 'mesh_file' || rec.kind === 'point_cloud' || rec.kind === 'link')) f3dLoad(rec);
  };
  /* a drawing loaded from disk arrives already built, so sweep it once */
  setTimeout(function(){
    AR.objs.forEach(function(o){
      if((o.kind === 'mesh_file' || o.kind === 'point_cloud' || o.kind === 'link') && !o.f3dOk) f3dLoad(o);
    });
  }, 0);
});
})();
