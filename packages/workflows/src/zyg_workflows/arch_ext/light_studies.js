// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* light_studies — the three sun icons, wired for real (2026-09-08).

   l_study    (Light ▸ Sun study)  ACTION  — sweep the day, render every hour and
                                             assemble ALL the frames into ONE captioned
                                             contact sheet (PNG), downloaded and opened
                                             in a sheet. act() resolves with the blob.
   l_solar    (Light ▸ Sun hours)  SWITCH  — the sun-hours MAP: how many hours of the
                                             chosen day each surface sees direct sun,
                                             painted onto the model as a per-vertex
                                             colour on a clone of every visible mesh.
   a_sunhours (Analyse ▸ Sun hours) ACTION — the same arithmetic as a READ-ONLY report:
                                             a table (record, name, kind, average, min,
                                             max) plus a CSV download. No paint.

   ONE arithmetic, three faces: lsCompute() below is the whole model, and the map, the
   report and the assistant's server-side twin all read it (the twin is a coarser copy
   in arch_assistant_ext/light_studies.py — the model cannot run WebGL).

   THE SUN. The hour is set with arSunSet(h) and the direction is then READ back off
   AR.sun.position: whatever solar model the studio has at the time (the built-in arc
   today, a real ephemeris once a light_sun family lands) is the model this family uses.
   Nothing here depends on that family existing. A sun whose normalised height is below
   0.08 is under the horizon and contributes no hour.

   LIT. A triangle is lit at an hour when (a) the sun is up, (b) the triangle faces it
   (its outward normal has a positive dot with the sun direction — the underside of a
   slab cannot see the sun), and (c) no OTHER record's mesh stands between its centroid
   and the sun. A record never shades itself: the ray skips its own meshes.

   THE DOCUMENT IS NOT EDITED. All three icons are read-only, so none of them calls
   arPush(): the map hides the originals through rec.node.visible (never rec.hidden,
   which IS document state) and puts them back when the switch goes off. The only thing
   written is the analysis result, on AR.doc.ext.light_studies.last — which the undo
   ring does not hold anyway (arSnapshot keeps AR.objs).
*/
(function(){
  var CAP = 60000;                       /* triangles above which we go per-record */
  var CHUNK = 320;                       /* samples per setTimeout slice — the UI breathes */
  /* the 5-step ramp: blue (no sun) -> yellow -> red (the most hours in the sweep) */
  var RAMP = [[0.13, 0.33, 0.86], [0.16, 0.70, 0.76], [0.94, 0.88, 0.22],
              [0.95, 0.56, 0.13], [0.86, 0.15, 0.15]];

  var LS = {on: false, busy: false, clones: [], hidden: [], last: null};
  window.lightStudies = LS;              /* the family's one global, prefixed */

  function lsNum(v, d){ var f = parseFloat(v); return isFinite(f) ? f : d; }
  function lsRgb(c){ return 'rgb(' + Math.round(c[0]*255) + ',' + Math.round(c[1]*255) + ',' + Math.round(c[2]*255) + ')'; }
  function lsHhmm(h){
    var hh = Math.floor(h), mm = Math.round((h - hh) * 60);
    if(mm >= 60){ hh++; mm -= 60; }
    return (hh < 10 ? '0' : '') + hh + ':' + (mm < 10 ? '0' : '') + mm;
  }
  function lsRamp(v, maxH){
    var f = maxH > 0 ? Math.max(0, Math.min(1, v / maxH)) : 0;
    return RAMP[Math.max(0, Math.min(4, Math.floor(f * 4.999)))];
  }

  /* ── the day ─────────────────────────────────────────────────────────── */
  function lsHours(o){
    var a = lsNum(o.from, 6), b = lsNum(o.to, 20), s = Math.max(0.25, lsNum(o.step, 2));
    if(b < a){ var t = a; a = b; b = t; }
    var out = [];
    for(var h = a; h <= b + 1e-6 && out.length < 32; h += s) out.push(Math.round(h * 100) / 100);
    if(!out.length) out.push(12);
    return out;
  }
  /* Set each hour through the studio's own sun, read the direction back, put the
     hour the operator had back afterwards. */
  function lsSunDirs(hours){
    var prev = (typeof AR.sunHour === 'number') ? AR.sunHour : 14, out = [];
    for(var i = 0; i < hours.length; i++){
      arSunSet(hours[i]);
      var d = AR.sun.position.clone().normalize();
      out.push({h: hours[i], dir: d, up: d.y > 0.08});
    }
    arSunSet(prev);
    return out;
  }

  /* ── the meshes ──────────────────────────────────────────────────────── */
  function lsMeshesOf(rec){
    var out = [];
    if(!rec.node) return out;
    rec.node.updateMatrixWorld(true);
    rec.node.traverse(function(m){
      if(m.isMesh && m.geometry && m.geometry.attributes && m.geometry.attributes.position && !m.userData.lsClone) out.push(m);
    });
    return out;
  }
  /* every visible record's meshes — the occluders, whatever the report is about */
  function lsAllMeshes(){
    var out = [];
    AR.objs.forEach(function(o){ if(!o.hidden && o.node) out = out.concat(lsMeshesOf(o)); });
    return out;
  }
  function lsTriCount(m){
    var g = m.geometry;
    return g.index ? g.index.count / 3 : g.attributes.position.count / 3;
  }
  /* world-space centroid + outward normal per triangle, in the SAME order that
     BufferGeometry.toNonIndexed() lays the vertices out, so the paint lines up */
  function lsTriSamples(m){
    var g = m.geometry, pos = g.attributes.position, idx = g.index, mw = m.matrixWorld;
    var n = idx ? idx.count / 3 : pos.count / 3, out = new Array(n);
    var a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
    var ab = new THREE.Vector3(), ac = new THREE.Vector3();
    for(var t = 0; t < n; t++){
      var i0 = idx ? idx.getX(t * 3) : t * 3,
          i1 = idx ? idx.getX(t * 3 + 1) : t * 3 + 1,
          i2 = idx ? idx.getX(t * 3 + 2) : t * 3 + 2;
      a.fromBufferAttribute(pos, i0).applyMatrix4(mw);
      b.fromBufferAttribute(pos, i1).applyMatrix4(mw);
      c.fromBufferAttribute(pos, i2).applyMatrix4(mw);
      ab.subVectors(b, a); ac.subVectors(c, a);
      out[t] = {c: new THREE.Vector3((a.x + b.x + c.x) / 3, (a.y + b.y + c.y) / 3, (a.z + b.z + c.z) / 3),
                n: new THREE.Vector3().crossVectors(ab, ac).normalize()};
    }
    return out;
  }
  /* the coarse fallback above the triangle cap: the record's bounding box, top
     face and four sides — the same five points the Python twin uses */
  function lsBoxSamples(rec){
    var box = new THREE.Box3().setFromObject(rec.node);
    if(box.isEmpty()) return [];
    var c = box.getCenter(new THREE.Vector3()), e = 0.02;
    return [{c: new THREE.Vector3(c.x, box.max.y + e, c.z), n: new THREE.Vector3(0, 1, 0)},
            {c: new THREE.Vector3(box.max.x + e, c.y, c.z), n: new THREE.Vector3(1, 0, 0)},
            {c: new THREE.Vector3(box.min.x - e, c.y, c.z), n: new THREE.Vector3(-1, 0, 0)},
            {c: new THREE.Vector3(c.x, c.y, box.max.z + e), n: new THREE.Vector3(0, 0, 1)},
            {c: new THREE.Vector3(c.x, c.y, box.min.z - e), n: new THREE.Vector3(0, 0, -1)}];
  }

  /* ── the one arithmetic ──────────────────────────────────────────────── */
  /* opt: {date?, from, to, step, ids?}   paint: build the vertex-coloured clones
     Resolves {hours, sun_hours, max, coarse, rows:[{id,name,kind,avg,min,max,n}], date} */
  function lsCompute(opt, paint, onProgress){
    var o = (opt && typeof opt === 'object') ? opt : {};
    var hours = lsHours(o);
    var suns = lsSunDirs(hours).filter(function(s){ return s.up; });
    var occ = lsAllMeshes();
    var want = null;
    if(o.ids && o.ids.length){ want = {}; o.ids.forEach(function(i){ want[i] = 1; }); }

    var subj = [];
    AR.objs.forEach(function(rec){
      if(rec.hidden || !rec.node) return;
      if(want && !want[rec.id]) return;
      var ms = lsMeshesOf(rec);
      if(ms.length) subj.push({rec: rec, meshes: ms});
    });

    var total = 0;
    subj.forEach(function(r){ r.meshes.forEach(function(m){ total += lsTriCount(m); }); });
    var coarse = total > CAP;

    var work = subj.map(function(r){
      var mine = {};
      r.meshes.forEach(function(m){ mine[m.uuid] = 1; });
      return {rec: r.rec, meshes: r.meshes,
              targets: occ.filter(function(m){ return !mine[m.uuid]; }),
              groups: coarse ? [{mesh: null, s: lsBoxSamples(r.rec)}]
                             : r.meshes.map(function(m){ return {mesh: m, s: lsTriSamples(m)}; })};
    });

    var counts = work.map(function(w){ return w.groups.map(function(g){ return new Float32Array(g.s.length); }); });
    var totalS = 0;
    work.forEach(function(w){ w.groups.forEach(function(g){ totalS += g.s.length; }); });

    return new Promise(function(resolve, reject){
      var ray = new THREE.Raycaster(); ray.far = 1e5;
      var org = new THREE.Vector3();
      var wi = 0, gi = 0, si = 0, done = 0, nSun = suns.length;
      function step(){
        try{
          var n = 0;
          while(n < CHUNK && wi < work.length){
            var w = work[wi], g = w.groups[gi];
            if(!g || si >= g.s.length){
              gi++; si = 0;
              if(gi >= w.groups.length){ wi++; gi = 0; }
              continue;
            }
            var sm = g.s[si], hit = 0;
            for(var k = 0; k < nSun; k++){
              var d = suns[k].dir;
              if(sm.n && sm.n.dot(d) <= 1e-4) continue;      /* faces away: self-shaded */
              org.copy(sm.c).addScaledVector(d, 0.02);
              ray.set(org, d);
              if(!ray.intersectObjects(w.targets, false).length) hit++;
            }
            counts[wi][gi][si] = hit;
            si++; n++; done++;
          }
          if(wi < work.length){
            if(onProgress && totalS) onProgress(done, totalS);
            setTimeout(step, 0);                              /* let the UI breathe */
            return;
          }
          resolve(lsFinish(work, counts, hours, suns, coarse, paint, String(o.date || '')));
        }catch(e){ reject(e); }
      }
      setTimeout(step, 0);
    });
  }

  function lsFinish(work, counts, hours, suns, coarse, paint, date){
    var maxH = Math.max(1, suns.length), rows = [];
    for(var i = 0; i < work.length; i++){
      var sum = 0, cnt = 0, mn = Infinity, mx = -Infinity;
      counts[i].forEach(function(arr){
        for(var j = 0; j < arr.length; j++){ var v = arr[j]; sum += v; cnt++; if(v < mn) mn = v; if(v > mx) mx = v; }
      });
      rows.push({id: work[i].rec.id, name: work[i].rec.name || arKindLabel(work[i].rec.kind), kind: work[i].rec.kind,
                 avg: Math.round((cnt ? sum / cnt : 0) * 100) / 100,
                 min: mn === Infinity ? 0 : mn, max: mx === -Infinity ? 0 : mx, n: cnt});
    }
    if(paint) lsPaint(work, counts, maxH);
    return {hours: hours, sun_hours: suns.map(function(s){ return s.h; }), max: maxH,
            coarse: coarse, rows: rows, date: date};
  }

  /* ── the paint: a vertex-coloured clone over every record ────────────── */
  function lsClone(mesh, perTri, maxH, flat){
    var src = mesh.geometry;
    var g = src.index ? src.toNonIndexed() : src.clone();
    var pc = g.attributes.position.count, col = new Float32Array(pc * 3);
    for(var t = 0; t * 3 < pc; t++){
      var c = lsRamp(perTri ? perTri[t] : flat, maxH);
      for(var k = 0; k < 3; k++){
        var b = (t * 3 + k) * 3;
        col[b] = c[0]; col[b + 1] = c[1]; col[b + 2] = c[2];
      }
    }
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
    var cm = new THREE.Mesh(g, new THREE.MeshBasicMaterial({vertexColors: true}));
    cm.matrixAutoUpdate = false;
    cm.matrix.copy(mesh.matrixWorld);
    cm.userData.lsClone = 1;
    cm.userData.lsSrc = mesh;
    AR.scene.add(cm);
    LS.clones.push(cm);
  }
  function lsPaint(work, counts, maxH){
    lsUnpaint();
    for(var i = 0; i < work.length; i++){
      var w = work[i];
      for(var gi = 0; gi < w.groups.length; gi++){
        var g = w.groups[gi], arr = counts[i][gi];
        if(g.mesh){ lsClone(g.mesh, arr, maxH, 0); continue; }
        var sum = 0;                                    /* coarse: one flat colour per record */
        for(var j = 0; j < arr.length; j++) sum += arr[j];
        var avg = arr.length ? sum / arr.length : 0;
        w.meshes.forEach(function(m){ lsClone(m, null, maxH, avg); });   // eslint-disable-line no-loop-func
      }
    }
  }
  function lsUnpaint(){
    LS.clones.forEach(function(c){
      AR.scene.remove(c);
      if(c.geometry) c.geometry.dispose();
      if(c.material) c.material.dispose();
    });
    LS.clones = [];
  }

  /* ── the legend, bottom-left, above the HUD ──────────────────────────── */
  function lsLegend(maxH, show){
    var st = document.getElementById('ar-stage'); if(!st) return;
    var el = document.getElementById('ls-legend');
    if(!show){ if(el) el.style.display = 'none'; return; }
    if(!el){ el = document.createElement('div'); el.id = 'ls-legend'; st.appendChild(el); }
    el.style.cssText = 'position:absolute;left:12px;bottom:46px;z-index:5;background:rgba(20,22,28,.88);'
      + 'border:1px solid rgba(255,255,255,.14);border-radius:9px;padding:7px 10px;font-size:.66rem;'
      + 'color:#d8dbe2;pointer-events:none;backdrop-filter:blur(6px);line-height:1.35;';
    var bars = '';
    for(var i = 0; i < 5; i++){
      var lo = Math.round(maxH * i / 5 * 10) / 10, hi = Math.round(maxH * (i + 1) / 5 * 10) / 10;
      bars += '<div style="display:flex;align-items:center;gap:7px">'
        + '<span style="width:18px;height:9px;border-radius:2px;display:inline-block;background:' + lsRgb(RAMP[i]) + '"></span>'
        + '<span>' + lo + '&ndash;' + hi + ' h</span></div>';
    }
    el.innerHTML = '<div style="font-weight:600;margin-bottom:3px">Direct sun hours</div>' + bars;
    el.style.display = 'block';
  }

  /* ── the table both reports show ─────────────────────────────────────── */
  function lsTable(res){
    var h = '<table class="ar-tbl"><tr><th>record</th><th>name</th><th>kind</th>'
      + '<th>avg h</th><th>min</th><th>max</th></tr>';
    res.rows.forEach(function(r){
      h += '<tr><td>' + esc(r.id) + '</td><td>' + esc(String(r.name)) + '</td><td>' + esc(arKindLabel(r.kind))
        + '</td><td><b>' + r.avg + '</b></td><td>' + r.min + '</td><td>' + r.max + '</td></tr>';
    });
    h += '</table><div style="margin-top:7px;font-size:.66rem;opacity:.75">'
      + 'hours swept: ' + esc(res.hours.join(', ')) + ' &middot; above the horizon: '
      + (res.sun_hours.length ? esc(res.sun_hours.join(', ')) : 'none') + ' (max ' + res.max + ' h)'
      + (res.date ? ' &middot; date ' + esc(res.date) : '')
      + (res.coarse ? ' &middot; <b>coarse</b>: over ' + CAP.toLocaleString()
                    + ' triangles, so five bounding-box points per record' : ' &middot; per triangle')
      + '</div>';
    return h;
  }
  function lsSave(res){
    if(!AR.doc.ext || typeof AR.doc.ext !== 'object') AR.doc.ext = {};
    var e = AR.doc.ext.light_studies || (AR.doc.ext.light_studies = {});
    var hrs = {};
    res.rows.forEach(function(r){ hrs[r.id] = r.avg; });
    e.last = {date: res.date, hours: hrs};
    LS.last = res;
  }

  /* ── l_solar: the map ────────────────────────────────────────────────── */
  function lsSolarOn(opt){
    if(LS.busy) return Promise.resolve(null);
    var o = (opt && typeof opt === 'object') ? opt : {};
    /* the map sweeps every hour by default — it is a map, not a filmstrip */
    var q = {date: o.date, from: o.from, to: o.to, step: lsNum(o.step, 1), ids: o.ids};
    LS.busy = true; LS.on = true;
    arHint('Sun-hours map &mdash; computing&hellip;');
    return lsCompute(q, true, function(d, t){
      arHint('Sun-hours map &mdash; <b>' + Math.round(d / t * 100) + '%</b> (' + d + ' of ' + t + ' samples)');
    }).then(function(res){
      /* only the records that got a painted clone go invisible: a map asked for a
         subset (opt.ids) must not make the rest of the drawing disappear */
      LS.hidden = [];
      res.rows.forEach(function(row){
        var r = arFind(row.id);
        if(r && r.node && !r.hidden){ LS.hidden.push(r.id); r.node.visible = false; }
      });
      lsLegend(res.max, true);
      lsSave(res);
      arSheet('Sun hours &mdash; map', lsTable(res));
      arHint('Sun-hours map <b>on</b> &mdash; ' + res.rows.length + ' object'
        + (res.rows.length === 1 ? '' : 's') + ', 0&ndash;' + res.max + ' h. Press <b>Sun hours</b> again to put the model back.');
      arToast('Sun-hours map: <b>' + res.rows.length + '</b> object' + (res.rows.length === 1 ? '' : 's')
        + ' painted, 0&ndash;' + res.max + ' h.');
      LS.busy = false; arToolsRender();
      return res;
    }).catch(function(e){
      LS.busy = false; LS.on = false; lsUnpaint(); lsLegend(0, false); arToolsRender();
      arToast('Sun-hours map failed: ' + esc(String((e && e.message) || e)), 'bad');
      return null;
    });
  }
  function lsSolarOff(){
    lsUnpaint();
    LS.hidden.forEach(function(id){ var r = arFind(id); if(r && r.node) r.node.visible = !r.hidden; });
    LS.hidden = [];
    LS.on = false;
    lsLegend(0, false);
    arSheetClose();
    arHint('');
    arToast('Sun-hours map off &mdash; the model is back.');
    arToolsRender();
    return Promise.resolve(null);
  }

  /* ── l_study: the contact sheet ──────────────────────────────────────── */
  function lsLoadImg(url){
    return new Promise(function(res, rej){
      var im = new Image();
      im.onload = function(){ res(im); };
      im.onerror = function(){ rej(new Error('a frame did not decode')); };
      im.src = url;
    });
  }
  function lsStudy(opt){
    var o;
    if(opt && typeof opt === 'object'){ o = opt; }
    else {
      var a = prompt('Sun study — sweep the day. Hours as "from,to,step":', '6,20,2');
      if(a === null) return Promise.resolve(null);
      var pp = String(a).split(/[,\s]+/).filter(function(s){ return s !== ''; });
      o = {from: lsNum(pp[0], 6), to: lsNum(pp[1], 20), step: lsNum(pp[2], 2)};
    }
    var res = Math.max(160, Math.min(2048, lsNum(o.res, 640)));
    var hours = lsHours(o);
    var prev = (typeof AR.sunHour === 'number') ? AR.sunHour : 14;
    var shots = [];
    for(var i = 0; i < hours.length; i++){
      arSunSet(hours[i]);
      arRender();
      var url = arShot(res, 0.85);
      if(url) shots.push({h: hours[i], url: url, el: Math.round(AR.sun.position.clone().normalize().y * 100) / 100});
    }
    arSunSet(prev);                                       /* the operator's hour comes back */
    if(!shots.length) return Promise.reject(new Error('the viewport gave no frames'));
    return Promise.all(shots.map(function(s){
      return lsLoadImg(s.url).then(function(im){ return {h: s.h, el: s.el, im: im}; });
    })).then(function(fr){
      var cols = Math.min(4, fr.length), rows = Math.ceil(fr.length / cols);
      var cw = fr[0].im.width, ch = fr[0].im.height, cap = 28, pad = 8, head = 34;
      var W = pad + cols * (cw + pad), H = head + rows * (ch + cap + pad);
      var cv = document.createElement('canvas'); cv.width = W; cv.height = H;
      var g = cv.getContext('2d');
      g.fillStyle = '#12141a'; g.fillRect(0, 0, W, H);
      g.fillStyle = '#e8eaf0'; g.font = '600 15px system-ui,-apple-system,sans-serif';
      g.fillText('Sun study — ' + (AR.doc.name || 'drawing') + (o.date ? ' — ' + o.date : '')
        + ' — ' + fr.length + ' hours (' + lsHhmm(hours[0]) + '–' + lsHhmm(hours[hours.length - 1]) + ')', pad, 22);
      fr.forEach(function(f, i){
        var cx = pad + (i % cols) * (cw + pad), cy = head + Math.floor(i / cols) * (ch + cap + pad);
        g.drawImage(f.im, cx, cy, cw, ch);
        g.strokeStyle = 'rgba(255,255,255,.22)'; g.lineWidth = 1;
        g.strokeRect(cx + 0.5, cy + 0.5, cw - 1, ch - 1);
        g.fillStyle = '#1b1e26'; g.fillRect(cx, cy + ch, cw, cap);
        g.fillStyle = f.el > 0.08 ? '#d7dbe4' : '#7d8494';
        g.font = '600 14px ui-monospace,SFMono-Regular,monospace';
        g.fillText(lsHhmm(f.h) + (f.el > 0.08 ? '' : '  (below the horizon)'), cx + 8, cy + ch + 19);
      });
      return new Promise(function(done){
        var url = cv.toDataURL('image/png');
        cv.toBlob(function(b){
          arSheet('Sun study &mdash; ' + fr.length + ' hours',
            '<img id="ls-study-img" alt="sun study contact sheet" src="' + url
            + '" style="width:100%;display:block;border-radius:6px">'
            + '<div style="margin-top:7px;font-size:.66rem;opacity:.75">' + esc(hours.join(', ')) + ' h &middot; '
            + W + '&times;' + H + ' px' + (b ? ' &middot; ' + Math.round(b.size / 1024) + ' kB' : '') + '</div>');
          if(b) arDownload(b, (AR.doc.name || 'drawing').replace(/[^\w-]+/g, '_') + '_sun_study.png');
          arToast('Sun study: <b>' + fr.length + '</b> frames on one contact sheet, downloaded.');
          done(b);
        }, 'image/png');
      });
    });
  }

  /* ── a_sunhours: the report ──────────────────────────────────────────── */
  function lsReport(opt){
    var o = (opt && typeof opt === 'object') ? opt : {};
    var which = String(o.which || (AR.sel && AR.sel.length ? 'selection' : 'all'));
    var ids = null;
    if(Array.isArray(o.ids) && o.ids.length) ids = o.ids.slice();
    else if(which !== 'all' && AR.sel && AR.sel.length) ids = AR.sel.slice();
    var q = {date: o.date, from: o.from, to: o.to, step: lsNum(o.step, 1), ids: ids};
    arHint('Sun hours &mdash; computing&hellip;');
    return lsCompute(q, false, function(d, t){
      arHint('Sun hours &mdash; <b>' + Math.round(d / t * 100) + '%</b> (' + d + ' of ' + t + ' samples)');
    }).then(function(res){
      lsSave(res);
      arSheet('Sun hours &mdash; ' + (ids ? 'selection' : 'whole drawing'), lsTable(res));
      var csv = 'record,name,kind,avg_direct_sun_hours,min_hours,max_hours,samples\n'
        + res.rows.map(function(r){
            return [r.id, '"' + String(r.name).replace(/"/g, '""') + '"', r.kind, r.avg, r.min, r.max, r.n].join(',');
          }).join('\n') + '\n';
      arDownload(new Blob([csv], {type: 'text/csv'}),
        (AR.doc.name || 'drawing').replace(/[^\w-]+/g, '_') + '_sun_hours.csv');
      arHint('');
      arToast('Sun hours: <b>' + res.rows.length + '</b> record' + (res.rows.length === 1 ? '' : 's')
        + ' over ' + res.sun_hours.length + ' daylight hour' + (res.sun_hours.length === 1 ? '' : 's') + ' — CSV downloaded.');
      return res;
    }).catch(function(e){
      arHint('');
      arToast('Sun hours failed: ' + esc(String((e && e.message) || e)), 'bad');
      return null;
    });
  }

  /* ── the clones follow the records, and the originals stay hidden ────── */
  AR_EXT.ticks.push(function(){
    if(!LS.on) return;
    for(var i = 0; i < LS.clones.length; i++){
      var c = LS.clones[i], s = c.userData.lsSrc;
      if(s) c.matrix.copy(s.matrixWorld);
    }
    for(var j = 0; j < LS.hidden.length; j++){
      var r = arFind(LS.hidden[j]);
      if(r && r.node && r.node.visible) r.node.visible = false;
    }
  });

  /* ── the icons ───────────────────────────────────────────────────────── */
  AR_EXT.tools.l_study = {
    assist: 1,
    tip: 'Sun study — sweep the day, render the shadow at every hour and write the frames out as one captioned contact sheet (PNG)',
    act: function(opt){
      return lsStudy(opt).catch(function(e){
        arToast('Sun study failed: ' + esc(String((e && e.message) || e)), 'bad');
        return null;
      });
    }
  };
  AR_EXT.tools.l_solar = {
    tog: 1, assist: 1,
    tip: 'Sun-hours map — how many hours of the day each surface sees direct sun, painted onto the model (blue none → red the most)',
    on: function(){ return !!LS.on; },
    act: function(opt){ return LS.on ? lsSolarOff() : lsSolarOn(opt); }
  };
  AR_EXT.tools.a_sunhours = {
    assist: 1,
    tip: 'Direct sun hours on a facade or a garden across a chosen day — a table for the selection (or the whole drawing) and a CSV',
    act: function(opt){ return lsReport(opt); }
  };
})();
