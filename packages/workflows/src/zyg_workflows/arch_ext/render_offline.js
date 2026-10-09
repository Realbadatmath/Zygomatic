// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* render_offline — the Render section's four offline/immersive icons, wired for real.

     r_ray      Ray trace   ACTION  a Blender CYCLES still of the current view, denoised
     r_denoise  Denoise     SWITCH  the denoiser flag r_ray sends (AR.doc.ext.render_offline.denoise)
     r_pano     360 pano    ACTION  an equirectangular panorama from a point in the model
     r_vr       Stereo/VR   SWITCH  a side-by-side stereo pair (THREE.StereoCamera) + a WebXR probe

   Nothing in inspection.html was edited. r_ray is the only one that leaves the
   browser: it POSTs the document and the camera to
   /inspect/api/architecture/ext/render_offline/render, which drives
   arch_server_ext/render_offline_blender.py through arch_blender_build.

   Every act() returns a Promise where there is something to wait for, so the
   assistant (and the tests) can await the blob instead of guessing.
   three.js is r144: StereoCamera, WebGLRenderTarget and readRenderTargetPixels
   are all core, so no module is vendored for this family. */
(function () {
  'use strict';
  var EXT = window.AR_EXT;

  /* ── shared helpers (module-private: nothing of ours reaches the page) ──── */
  function nOf(v, d) { var f = parseFloat(v); return (isFinite(f) ? f : d); }
  function isArgs(o) { return !!o && typeof o === 'object'; }

  function settings() {                        /* read-only: never creates the key */
    return (window.AR && AR.doc && AR.doc.ext && AR.doc.ext.render_offline) || {};
  }
  function denoiseOn() { var e = settings(); return e.denoise === undefined ? true : !!e.denoise; }

  function camPayload() {
    /* the studio camera as the server wants it: studio coordinates, a vertical
       fov in degrees, and for an ortho view the visible HALF height. */
    var ortho = !!AR.ortho, p = AR.cam.position, t = AR.controls.target;
    var top = AR.camO ? Math.abs(AR.camO.top) / (AR.camO.zoom || 1) : 10;
    return { p: [p.x, p.y, p.z], t: [t.x, t.y, t.z],
             fov: (AR.camP && AR.camP.fov) || 50, ortho: ortho ? 1 : 0, top: top };
  }

  function sheetImage(title, blob, rows) {
    var url = URL.createObjectURL(blob);
    arSheet(title, '<img src="' + url + '" alt="' + esc(title) + '" style="max-width:100%;display:block;'
      + 'border-radius:6px;background:#111">' + (rows && rows.length ? arRows(rows) : ''));
    setTimeout(function () { URL.revokeObjectURL(url); }, 600000);
    return url;
  }

  /* ── r_ray — "Ray-traced still — real reflections, refraction and soft
        shadows, minutes not milliseconds" ─────────────────────────────────── */
  EXT.tools.r_ray = {
    assist: 1,
    tip: 'Ray-traced still — Blender Cycles on the server renders this exact view with real reflections, '
       + 'refraction and soft shadows (10-60 s), then it downloads and opens in a sheet',
    act: function (opt) {
      var samples = 64, width = 1280, height = 720, view = 'current', denoise = denoiseOn();
      if (isArgs(opt)) {
        samples = Math.round(nOf(opt.samples, 64));
        width = Math.round(nOf(opt.width, 1280));
        height = Math.round(nOf(opt.height, 720));
        if (opt.denoise !== undefined) denoise = !!opt.denoise;
        if (opt.view) view = String(opt.view);
      } else {
        var a = prompt('Ray trace this view with Blender Cycles — samples, width, height\n'
                     + '(64 samples at 1280x720 takes about 10-60 s)', '64, 1280, 720');
        if (a === null) return null;
        var bits = String(a).split(/[,\sx]+/).filter(function (s) { return s !== ''; });
        samples = Math.round(nOf(bits[0], 64));
        width = Math.round(nOf(bits[1], 1280));
        height = Math.round(nOf(bits[2], 720));
      }
      if (!AR.objs.length) { arToast('Nothing to ray trace — the drawing is empty.', 'warn'); return null; }
      if (view !== 'current') arView(view);
      var body = { doc: arDocOut(), camera: camPayload(), samples: samples,
                   width: width, height: height, denoise: denoise ? 1 : 0 };
      var t0 = Date.now();
      arHint('<b>Ray tracing</b> ' + width + '&times;' + height + ' at ' + samples + ' samples'
           + (denoise ? ', denoised' : '') + ' &mdash; Blender Cycles, 10-60 s&hellip;');
      return fetch('/inspect/api/architecture/ext/render_offline/render', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
      }).then(function (r) {
        if (!r.ok || (r.headers.get('content-type') || '').indexOf('image/png') < 0) {
          return r.text().then(function (t) {
            var msg = t;
            try { msg = JSON.parse(t).error || t; } catch (e) { /* not JSON: show the body */ }
            throw new Error(String(msg).slice(0, 240));
          });
        }
        return r.blob();
      }).then(function (blob) {
        var secs = ((Date.now() - t0) / 1000).toFixed(1);
        arHint('');
        sheetImage('Ray trace &middot; Cycles', blob,
          [['Size', width + ' \u00d7 ' + height], ['Samples', String(samples)],
           ['Denoise', denoise ? 'on' : 'off'], ['Time', secs + ' s'],
           ['File', Math.round(blob.size / 1024) + ' KB']]);
        arDownload(blob, 'raytrace.png');
        arToast('Ray trace done in ' + secs + ' s &mdash; raytrace.png downloaded.');
        return blob;
      }).catch(function (e) {
        arHint('');
        arToast('<b>Ray trace</b> failed: ' + esc(String(e && e.message || e)), 'bad');
        throw e;
      });
    }
  };

  /* ── r_denoise — "Denoise — clean up a short ray-traced sample instead of
        paying for a long one" ─────────────────────────────────────────────── */
  EXT.tools.r_denoise = {
    tog: 1, assist: 1,
    tip: 'Denoise — OpenImageDenoise cleans up a short Cycles sample, so 64 samples look like 1000. '
       + 'The flag rides with every Ray trace and is saved with the drawing',
    on: denoiseOn,
    act: function (opt) {
      var want = isArgs(opt) && opt.on !== undefined ? !!opt.on : !denoiseOn();
      arPush();                                  /* ONE push, BEFORE the change */
      AR.doc.ext = AR.doc.ext || {};
      AR.doc.ext.render_offline = AR.doc.ext.render_offline || {};
      AR.doc.ext.render_offline.denoise = want ? 1 : 0;
      arDirty(true);
      arToast('Denoise <b>' + (want ? 'on' : 'off') + '</b> &mdash; ray traces will '
            + (want ? 'be cleaned up by OpenImageDenoise.' : 'keep their raw sampling noise.'));
      return want;
    }
  };

  /* ── r_pano — "360 degree panorama from a point in the model" ───────────── */
  var SRGB = null;
  function srgbLut() {                            /* linear byte -> sRGB byte, once */
    if (SRGB) return SRGB;
    SRGB = new Uint8Array(256);
    for (var i = 0; i < 256; i++) {
      var c = i / 255;
      c = c <= 0.0031308 ? c * 12.92 : 1.055 * Math.pow(c, 1 / 2.4) - 0.055;
      SRGB[i] = Math.max(0, Math.min(255, Math.round(c * 255)));
    }
    return SRGB;
  }

  function panoPoint(eye) {
    /* the camera's own position, unless something is selected: then the centre
       of the selection, standing at eye height on the drawing plane. */
    if (AR.sel && AR.sel.length) {
      var b = arBounds(true);
      return new THREE.Vector3(b.c.x, (AR.level || 0) + eye, b.c.z);
    }
    return AR.cam.position.clone();
  }

  function panoRender(size, eye) {
    var W = Math.max(64, Math.min(4096, Math.round(size / 2) * 2)), H = W >> 1;
    var f = Math.max(16, Math.round(W / 4));
    var P = panoPoint(eye);
    var r = AR.renderer, sc = AR.scene;
    var rt = new THREE.WebGLRenderTarget(f, f, {
      minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter,
      format: THREE.RGBAFormat, type: THREE.UnsignedByteType
    });
    /* r144 encodes for the render target's own texture, not the canvas: without
       this the six faces come back linear and the panorama is muddy */
    var linear = true;
    try { rt.texture.encoding = r.outputEncoding; linear = (r.outputEncoding === THREE.LinearEncoding); }
    catch (e) { /* older/newer build: fall back to the LUT below */ }
    var cam = new THREE.PerspectiveCamera(90, 1, 0.05, 8000);
    cam.position.copy(P);
    var dirs = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]];
    var ups = [[0, -1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1], [0, -1, 0], [0, -1, 0]];
    var faces = [], i;
    var prevRT = r.getRenderTarget();
    for (i = 0; i < 6; i++) {
      cam.up.set(ups[i][0], ups[i][1], ups[i][2]);
      cam.lookAt(P.x + dirs[i][0], P.y + dirs[i][1], P.z + dirs[i][2]);
      cam.updateMatrixWorld(true);
      r.setRenderTarget(rt);
      r.render(sc, cam);
      var buf = new Uint8Array(f * f * 4);
      r.readRenderTargetPixels(rt, 0, 0, f, f, buf);
      faces.push(buf);
    }
    r.setRenderTarget(prevRT);
    rt.dispose();

    /* stitch: one output pixel -> a direction -> the cube face it falls on
       (the OpenGL face/uv convention the six cameras above were aimed for) */
    var lut = linear ? srgbLut() : null;
    var out = new Uint8ClampedArray(W * H * 4);
    for (var j = 0; j < H; j++) {
      var lat = Math.PI * 0.5 - (j + 0.5) / H * Math.PI;
      var cl = Math.cos(lat), sl = Math.sin(lat);
      for (i = 0; i < W; i++) {
        var lon = (i + 0.5) / W * 2 * Math.PI - Math.PI;
        var dx = cl * Math.sin(lon), dy = sl, dz = -cl * Math.cos(lon);
        var ax = Math.abs(dx), ay = Math.abs(dy), az = Math.abs(dz), fi, uc, vc, ma;
        if (ax >= ay && ax >= az) { ma = ax; if (dx > 0) { fi = 0; uc = -dz; vc = -dy; } else { fi = 1; uc = dz; vc = -dy; } }
        else if (ay >= az) { ma = ay; if (dy > 0) { fi = 2; uc = dx; vc = dz; } else { fi = 3; uc = dx; vc = -dz; } }
        else { ma = az; if (dz > 0) { fi = 4; uc = dx; vc = -dy; } else { fi = 5; uc = -dx; vc = -dy; } }
        var px = (uc / ma + 1) * 0.5 * f | 0, py = (vc / ma + 1) * 0.5 * f | 0;
        if (px < 0) px = 0; if (px >= f) px = f - 1;
        if (py < 0) py = 0; if (py >= f) py = f - 1;
        var b = faces[fi], s = ((f - 1 - py) * f + px) * 4, d = (j * W + i) * 4;
        if (lut) { out[d] = lut[b[s]]; out[d + 1] = lut[b[s + 1]]; out[d + 2] = lut[b[s + 2]]; }
        else { out[d] = b[s]; out[d + 1] = b[s + 1]; out[d + 2] = b[s + 2]; }
        out[d + 3] = 255;
      }
    }
    var cv = document.createElement('canvas');
    cv.width = W; cv.height = H;
    cv.getContext('2d').putImageData(new ImageData(out, W, H), 0, 0);
    return { canvas: cv, W: W, H: H, face: f, point: P };
  }

  EXT.tools.r_pano = {
    assist: 1,
    tip: '360\u00b0 panorama \u2014 six cube faces from the camera (or from the selection at eye height) '
       + 'stitched into a 2:1 equirectangular PNG you can hand someone as the inside of the model',
    act: function (opt) {
      var size = 2048, eye = 1.65;
      if (isArgs(opt)) { size = Math.round(nOf(opt.size, 2048)); eye = nOf(opt.eye, 1.65); }
      else {
        var a = prompt('360\u00b0 panorama \u2014 width in pixels (the height is half of it)', '2048');
        if (a === null) return null;
        size = Math.round(nOf(a, 2048));
      }
      arHint('<b>360\u00b0 panorama</b> &mdash; rendering six faces&hellip;');
      var got = panoRender(size, eye);
      arRender();                                 /* put the canvas back the way it was */
      return new Promise(function (res, rej) {
        got.canvas.toBlob(function (blob) {
          arHint('');
          if (!blob) { arToast('<b>360 pano</b> failed: the canvas produced no PNG.', 'bad'); rej(new Error('no blob')); return; }
          sheetImage('360\u00b0 panorama &middot; equirectangular', blob,
            [['Size', got.W + ' \u00d7 ' + got.H], ['Cube face', got.face + ' px'],
             ['From', arFmt(got.point.x) + ', ' + arFmt(got.point.y) + ', ' + arFmt(got.point.z)],
             ['File', Math.round(blob.size / 1024) + ' KB']]);
          arDownload(blob, 'panorama-360.png');
          arToast('360\u00b0 panorama ' + got.W + '\u00d7' + got.H + ' downloaded.');
          res(blob);
        }, 'image/png');
      });
    }
  };

  /* ── r_vr — "Stereo pair or WebXR — walk the model at eye height" ───────── */
  var vrOn = false, stereo = null, prevRender = null, eyeSep = 0.064, lastFrame = null;

  function stereoRender() {
    var r = AR.renderer, cam = AR.camP || AR.cam;
    var sz = r.getSize(new THREE.Vector2());
    var w = Math.floor(sz.x / 2), h = Math.floor(sz.y);
    if (w < 2 || h < 2) { r.render(AR.scene, AR.cam); return; }
    stereo.eyeSep = eyeSep;
    cam.updateMatrixWorld();
    stereo.update(cam);
    /* what the frame actually was, so that the two eyes can be checked as
       NUMBERS — a software-GL screenshot proves nothing about a 64 mm parallax */
    var pl = new THREE.Vector3().setFromMatrixPosition(stereo.cameraL.matrixWorld);
    var pr = new THREE.Vector3().setFromMatrixPosition(stereo.cameraR.matrixWorld);
    lastFrame = { w: w, h: h, sep: pl.distanceTo(pr),
                  left: [pl.x, pl.y, pl.z], right: [pr.x, pr.y, pr.z],
                  halves: [[0, 0, w, h], [w, 0, sz.x - w, h]] };
    r.setScissorTest(true);
    r.setScissor(0, 0, w, h); r.setViewport(0, 0, w, h);
    r.render(AR.scene, stereo.cameraL);
    r.setScissor(w, 0, sz.x - w, h); r.setViewport(w, 0, sz.x - w, h);
    r.render(AR.scene, stereo.cameraR);
    r.setScissorTest(false);
    r.setViewport(0, 0, sz.x, sz.y);
  }

  function xrButton() {
    /* UNTESTED on this box: it has no WebXR runtime, so navigator.xr is absent
       and only the "no headset" line below is ever seen here. */
    if (!navigator.xr || !navigator.xr.isSessionSupported) {
      return '<div style="opacity:.7">No WebXR runtime in this browser &mdash; the side-by-side pair '
           + 'above is the headset-free way to look at it (cross your eyes, or use a phone holder).</div>';
    }
    return '<button id="ro-xr" class="ar-btn" onclick="(function(b){'
         + 'navigator.xr.requestSession(\'immersive-vr\').then(function(s){ AR.renderer.xr.enabled=true; '
         + 'AR.renderer.xr.setSession(s); b.textContent=\'in the headset\'; })'
         + '.catch(function(e){ b.textContent=\'WebXR refused: \'+e.message; });})(this)">'
         + 'Enter WebXR</button>';
  }

  EXT.tools.r_vr = {
    tog: 1, assist: 1,
    tip: 'Stereo / VR \u2014 splits the canvas into a left and a right eye 64 mm apart (THREE.StereoCamera); '
       + 'offers a WebXR session when the browser has one',
    on: function () { return vrOn; },
    /* read-only: what the last stereo frame was (the two eye positions, their
       separation and the two scissor rectangles). Read by the family test. */
    state: function () { return { on: vrOn, eye_sep: eyeSep, last: lastFrame }; },
    act: function (opt) {
      var want = isArgs(opt) && opt.on !== undefined ? !!opt.on : !vrOn;
      if (isArgs(opt) && opt.eye_sep !== undefined) eyeSep = Math.max(0.005, Math.min(0.25, nOf(opt.eye_sep, 0.064)));
      if (want && !vrOn) {
        if (!THREE.StereoCamera) { arToast('This three.js build has no StereoCamera.', 'bad'); return false; }
        stereo = stereo || new THREE.StereoCamera();
        prevRender = EXT.render || null;          /* whatever a post-processing family left here */
        EXT.render = stereoRender;
        vrOn = true;
        arSheet('Stereo / VR', arRows([['Mode', 'side-by-side, left eye | right eye'],
                                       ['Eye separation', (eyeSep * 1000).toFixed(0) + ' mm'],
                                       ['Camera', 'the perspective camera, orbit as usual']])
                             + xrButton());
        arHint('<b>Stereo</b> on &mdash; left eye left, right eye right. Press <b>Stereo / VR</b> again for one image.');
        arRender();
      } else if (!want && vrOn) {
        EXT.render = prevRender;                  /* the SAME function object, not null */
        prevRender = null;
        vrOn = false;
        var r = AR.renderer, sz = r.getSize(new THREE.Vector2());
        r.setScissorTest(false);
        r.setViewport(0, 0, sz.x, sz.y);
        arSheetClose();
        arHint('');
        arRender();
      }
      return vrOn;
    }
  };
}());
