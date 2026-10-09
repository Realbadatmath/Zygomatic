// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* view_camera — four camera/animation icons of the Architecture Studio, wired
   through the ICON seam (2026-09-07). Nothing in inspection.html was edited.

     v_2pt        SWITCH  two-point perspective: verticals stay vertical
     v_turntable  ACTION  360° orbit recorded to a WebM
     v_walkpath   SWITCH  record a camera route, then play it back
     r_anim       ACTION  the walk path (or a sun sweep) rendered to one WebM

   Only browser APIs and the studio's own globals are used: no library was
   added, three.js stays r144 (THREE.CatmullRomCurve3 is in the core build).
   Video comes out of canvas.captureStream() + MediaRecorder (VP9, VP8 or the
   container default — whichever this browser supports).

   Document state: AR.doc.ext.view_camera = {path: [camState…], anim: {…}} —
   saved with the drawing, round-trips through the assistant.
   Preference: localStorage 'ar.view_camera.two_point'. */
(function () {
  'use strict';

  var VC = window.AR_VIEW_CAMERA = {
    two_point: false,     // the v_2pt latch
    recording: false,     // the v_walkpath latch
    timer: 0,             // the 250 ms key sampler
    busy: 0,              // a recorder is running
    playing: 0,           // a walk path is playing
    lastMime: '',         // the codec MediaRecorder actually gave us
    lastPitch: 0,         // radians the user has orbited below/above level
    PATH_CAP: 600,
    KEY_MS: 250
  };

  /* ── document + preference state ─────────────────────────────────────── */
  function vcRead() {                       // never creates: a read must not dirty the doc
    return (window.AR && AR.doc && AR.doc.ext && AR.doc.ext.view_camera) || {};
  }
  function vcWrite() {                      // only called behind an arPush()
    AR.doc.ext = AR.doc.ext || {};
    AR.doc.ext.view_camera = AR.doc.ext.view_camera || {};
    return AR.doc.ext.view_camera;
  }
  function vcPath() { var p = vcRead().path; return (p && p.length) ? p : []; }
  function vcPref(k, v) {
    try {
      if (v === undefined) return localStorage.getItem('ar.view_camera.' + k);
      localStorage.setItem('ar.view_camera.' + k, String(v));
    } catch (e) { }
    return null;
  }
  function vcClamp(v, lo, hi, d) { var n = arNum(v, d); return Math.max(lo, Math.min(hi, n)); }
  function vcRaf(fn) {
    return (window.requestAnimationFrame || function (cb) { return setTimeout(cb, 16); })(fn);
  }
  function vcDocName() { return String((AR.doc && AR.doc.name) || 'drawing').replace(/[^\w-]+/g, '_').slice(0, 60) || 'drawing'; }

  /* ── 1. v_2pt — two-point perspective ────────────────────────────────────
     Every frame, after OrbitControls has aimed the camera at its target, the
     camera is LEVELLED (tilt 0, so world verticals are parallel to the image
     plane and stay vertical) and the lens is SHIFTED vertically so the target
     the user was actually looking at is still framed — exactly what a
     shift lens, or an architect's two-point construction, does.

     The shift is the y-offset term of the projection matrix, element [9] in
     three's column-major array (b = (top+bottom)/(top-bottom)). For a point at
     camera-space (yc, zc) the ndc y is (e5*yc + e9*zc) / -zc; the original
     target sits at yc = dy, zc = -dh in the levelled frame, so putting it back
     on the centre line needs e9 = e5 * dy/dh = e5 * tan(pitch). */
  function vcTwoPointFrame() {
    if (!VC.two_point || !window.AR || AR.ortho || !AR.camP || !AR.controls) return;
    var cam = AR.camP, t = AR.controls.target;
    var vx = t.x - cam.position.x, vy = t.y - cam.position.y, vz = t.z - cam.position.z;
    var dh = Math.sqrt(vx * vx + vz * vz);
    if (dh < 1e-4) return;                    // straight up or down: no two-point view exists
    VC.lastPitch = Math.atan2(vy, dh);
    cam.up.set(0, 1, 0);
    cam.lookAt(cam.position.x + vx, cam.position.y, cam.position.z + vz);
    cam.updateMatrixWorld();
    var e = cam.projectionMatrix.elements;
    e[9] = e[5] * (vy / dh);
    cam.projectionMatrixInverse.copy(cam.projectionMatrix).invert();
  }
  AR_EXT.ticks.push(vcTwoPointFrame);

  AR_EXT.tools.v_2pt = {
    tog: 1, assist: 1,
    tip: 'Two-point perspective — verticals kept vertical, the way an architectural view is drawn. '
       + 'The camera is levelled and the lens shifted, so the framing does not move. Args: {on: true|false}',
    on: function () { return !!VC.two_point; },
    act: function (opt) {
      var want = (opt && typeof opt === 'object' && opt.on !== undefined) ? !!opt.on : !VC.two_point;
      VC.two_point = want;
      vcPref('two_point', want ? 1 : 0);
      if (!want && AR.camP) {                 // give the straight projection back
        AR.camP.updateProjectionMatrix();
        AR.camP.projectionMatrixInverse.copy(AR.camP.projectionMatrix).invert();
        if (AR.controls) AR.controls.update();
      } else if (want) {
        vcTwoPointFrame();
      }
      arToast('Two-point perspective <b>' + (want ? 'on' : 'off') + '</b>'
        + (want ? ' — verticals stay vertical however far you tilt; the lens shifts instead.' : ' — the camera tilts again.')
        + (want && AR.ortho ? ' The ortho view has no vanishing points, so it takes effect in perspective.' : ''),
        (want && AR.ortho) ? 'warn' : '');
      return want;
    }
  };

  /* ── the WebM recorder shared by v_turntable and r_anim ───────────────── */
  function vcRecorder(fps) {
    var canvas = AR.renderer.domElement;
    var stream = canvas.captureStream(Math.max(1, Math.min(60, Math.round(fps))));
    var cands = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'], mt = '';
    for (var i = 0; i < cands.length; i++) {
      try { if (MediaRecorder.isTypeSupported(cands[i])) { mt = cands[i]; break; } } catch (e) { }
    }
    VC.lastMime = mt || '(default)';
    var rec = mt ? new MediaRecorder(stream, { mimeType: mt }) : new MediaRecorder(stream);
    var chunks = [];
    rec.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
    rec.start(200);
    return {
      stop: function () {
        return new Promise(function (res) {
          var done = function () {
            try { stream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) { }
            res(new Blob(chunks, { type: 'video/webm' }));
          };
          rec.onstop = done;
          if (rec.state === 'inactive') { done(); return; }
          try { rec.requestData(); } catch (e) { }
          rec.stop();
        });
      }
    };
  }

  /* render at the OUTPUT resolution, not the viewport's; returns the undo */
  function vcSizeSet(res) {
    var v = new THREE.Vector2();
    AR.renderer.getSize(v);
    var w0 = Math.round(v.x) || 900, h0 = Math.round(v.y) || 600, asp = w0 / h0;
    var w = Math.round(vcClamp(res, 160, 3840, 1280)); if (w % 2) w += 1;
    var h = Math.round(w / asp); if (h % 2) h += 1; if (h < 64) h = 64;
    AR.renderer.setSize(w, h, false);
    AR.camP.aspect = w / h; AR.camP.updateProjectionMatrix();
    return { w: w, h: h, restore: function () {
      AR.renderer.setSize(w0, h0, false);
      AR.camP.aspect = w0 / h0; AR.camP.updateProjectionMatrix();
    } };
  }

  /* One recording. `frame(f)` (f = 0..1) puts the scene where it belongs for
     that frame; the loop is paced in REAL time at `fps` so the WebM lasts as
     long as it says it does. Resolves with the Blob (also downloaded). */
  function vcRunRecord(o) {
    if (!window.MediaRecorder || !AR.renderer.domElement.captureStream) {
      arToast('This browser cannot record video — MediaRecorder or canvas.captureStream is missing.', 'bad');
      return Promise.reject(new Error('no MediaRecorder'));
    }
    if (VC.busy) { arToast('A recording is already running.', 'warn'); return Promise.reject(new Error('busy')); }
    VC.busy = 1;
    var saved = arCamState(), sunWas = AR.sunHour;
    var toastWas = window.arToast;
    if (o.mute) window.arToast = function () { };      // a sun sweep calls arSunSet ~200 times
    var size = vcSizeSet(o.res);
    var total = Math.max(2, Math.min(3600, Math.round(o.total)));
    var fps = Math.max(1, Math.min(60, Math.round(o.fps)));
    try { o.frame(0); } catch (e) { }
    arRender();
    var rc = vcRecorder(fps);
    return new Promise(function (resolve, reject) {
      var i = 0, stopped = false, t0 = performance.now();
      var wd = setTimeout(function () { end(); }, Math.round(total * 1000 / fps) + 20000);
      function cleanup() {
        clearTimeout(wd);
        if (o.mute) { try { arSunSet(sunWas === undefined ? 14 : sunWas); } catch (e) { } }
        window.arToast = toastWas;             // put the sun back while the toast is still muted
        try { size.restore(); } catch (e) { }
        try { arCamApply(saved); } catch (e) { }
        arHint('');
        VC.busy = 0;
      }
      function end() {
        if (stopped) return; stopped = true;
        rc.stop().then(function (blob) {
          cleanup();
          try { arDownload(blob, o.name); } catch (e) { }
          arToast(o.label + ' written — <b>' + Math.max(1, Math.round(blob.size / 1024)) + ' kB</b> of WebM, '
            + total + ' frames at ' + fps + ' fps, ' + size.w + '&times;' + size.h + '.');
          resolve(blob);
        }, function (err) { cleanup(); reject(err); });
      }
      function step() {
        if (stopped) return;
        try { o.frame(i / total); } catch (e) { }
        arRender();
        arHint(o.hint + ' — <b>' + Math.round(i * 100 / total) + '%</b> (' + (i + 1) + '/' + total + ')');
        i += 1;
        if (i >= total) { end(); return; }
        var wait = (t0 + i * 1000 / fps) - performance.now();
        if (wait > 4) setTimeout(function () { vcRaf(step); }, wait); else vcRaf(step);
      }
      vcRaf(step);
    });
  }

  /* ── 2. v_turntable — 360° orbit, recorded ───────────────────────────── */
  AR_EXT.tools.v_turntable = {
    assist: 1,
    tip: 'Turntable — orbit the model through 360° and write the frames out as one WebM. '
       + 'Args: {seconds: 8, fps: 24, res: 1280}',
    act: function (opt) {
      var o = (opt && typeof opt === 'object') ? opt : null, secs, fps, res;
      if (o) {
        secs = vcClamp(o.seconds, 0.2, 120, 8);
        fps = vcClamp(o.fps, 1, 60, 24);
        res = vcClamp(o.res, 160, 3840, 1280);
      } else {
        var a = prompt('Turntable length in seconds (the camera orbits 360\u00b0 around what it is looking at):', '8');
        if (a === null) return;
        secs = vcClamp(a, 0.2, 120, 8);
        fps = vcClamp(vcPref('fps'), 1, 60, 24);
        res = vcClamp(vcPref('res'), 160, 3840, 1280);
      }
      var tgt = AR.controls.target.clone(), p = AR.cam.position.clone();
      var dx = p.x - tgt.x, dz = p.z - tgt.z, dy = p.y - tgt.y;
      var r = Math.sqrt(dx * dx + dz * dz);
      if (r < 0.05) r = Math.max(1, Math.abs(dy)) * 1.5;      // straight down: back off so the orbit exists
      var a0 = Math.atan2(dz, dx);
      return vcRunRecord({
        res: res, fps: fps, total: secs * fps, mute: false,
        hint: 'Turntable', label: 'Turntable',
        name: vcDocName() + '-turntable.webm',
        frame: function (f) {
          var a = a0 + f * Math.PI * 2;
          AR.cam.position.set(tgt.x + Math.cos(a) * r, tgt.y + dy, tgt.z + Math.sin(a) * r);
          AR.controls.target.copy(tgt);
          AR.controls.update();
        }
      });
    }
  };

  /* ── 3. v_walkpath — record a route, play the camera along it ─────────── */
  function vcKey() {                          // ONE key; exported as _step for the test
    if (!window.AR || !AR.doc) return 0;
    var e = vcWrite(), pa = e.path = e.path || [];
    if (pa.length >= VC.PATH_CAP) { vcStop(); return pa.length; }
    pa.push(arCamState());
    arDirty(true);
    if (VC.recording) arHint('Walk path — <b>recording</b>, ' + pa.length + ' key'
      + (pa.length === 1 ? '' : 's') + '. Move the camera; press <b>Walk path</b> again to stop.');
    return pa.length;
  }
  function vcStart() {
    arPush();                                 // ONE undo step for the whole recording
    var e = vcWrite();
    e.path = [];
    VC.recording = true;
    VC.timer = setInterval(vcKey, VC.KEY_MS);
    vcKey();
    arToast('Walk path <b>recording</b> — move the camera; press <b>Walk path</b> again to stop.');
    arToolsRender();
    return 0;
  }
  function vcStop() {
    if (VC.timer) { clearInterval(VC.timer); VC.timer = 0; }
    VC.recording = false;
    var n = vcPath().length;
    arHint('');
    arToast('Walk path recorded — <b>' + n + '</b> key' + (n === 1 ? '' : 's') + ' ('
      + arFmt(n * VC.KEY_MS / 1000) + ' s). Press again to play it back.');
    arToolsRender();
    return n;
  }
  function vcCurves(path) {
    var P = [], T = [], i;
    for (i = 0; i < path.length; i++) {
      P.push(new THREE.Vector3(path[i].p[0], path[i].p[1], path[i].p[2]));
      T.push(new THREE.Vector3(path[i].t[0], path[i].t[1], path[i].t[2]));
    }
    if (P.length === 1) { P.push(P[0].clone()); T.push(T[0].clone()); }
    return { p: new THREE.CatmullRomCurve3(P), t: new THREE.CatmullRomCurve3(T), n: path.length };
  }
  function vcSeek(c, f) {
    var u = Math.max(0, Math.min(1, f));
    AR.cam.position.copy(c.p.getPoint(u));
    AR.controls.target.copy(c.t.getPoint(u));
    AR.controls.update();
  }
  function vcPlay(path) {
    var c = vcCurves(path), dur = Math.max(500, path.length * VC.KEY_MS), t0 = performance.now();
    VC.playing = 1;
    return new Promise(function (res) {
      function step() {
        var f = Math.min(1, (performance.now() - t0) / dur);
        vcSeek(c, f);
        arHint('Walk path — playing <b>' + Math.round(f * 100) + '%</b>');
        if (f < 1) { vcRaf(step); return; }
        VC.playing = 0;
        arHint('');
        arToast('Walk path played — <b>' + path.length + '</b> keys over ' + arFmt(dur / 1000) + ' s.');
        res(path.length);
      }
      vcRaf(step);
    });
  }
  AR_EXT.tools.v_walkpath = {
    tog: 1, assist: 1,
    tip: 'Walkthrough path — press to record a route through the model (a key every 250 ms), '
       + 'press again to stop, press a third time to fly the camera along it. Args: {mode: "record"|"stop"|"play"|"clear"}',
    on: function () { return !!VC.recording; },
    _step: vcKey,                              // the 250 ms sampler, callable from a test
    act: function (opt) {
      var m = (opt && typeof opt === 'object' && opt.mode) ? String(opt.mode).toLowerCase() : '';
      if (!m) m = VC.recording ? 'stop' : (vcPath().length >= 2 ? 'play' : 'record');
      if (m === 'clear') {
        if (VC.recording) vcStop();
        arPush(); vcWrite().path = []; arDirty(true);
        arToast('Walk path cleared.');
        return 0;
      }
      if (m === 'record') { return VC.recording ? vcStop() : vcStart(); }
      if (m === 'stop') {
        if (!VC.recording) { arToast('No walk path is being recorded.', 'warn'); return vcPath().length; }
        return vcStop();
      }
      if (m === 'play') {
        if (VC.recording) vcStop();
        var path = vcPath();
        if (path.length < 2) {
          arToast('No walk path recorded yet — press <b>Walk path</b> to record one first.', 'warn');
          return 0;
        }
        return vcPlay(path);
      }
      arToast('Walk path: mode must be record, stop, play or clear.', 'warn');
      return 0;
    }
  };

  /* ── 4. r_anim — the walk path, or a sun sweep, rendered to one WebM ──── */
  AR_EXT.tools.r_anim = {
    assist: 1,
    tip: 'Animation render — the recorded walk path, or (without one) a 06:00\u219220:00 sun sweep, '
       + 'written out as one WebM. Args: {res: 1280, fps: 24, seconds: 8, mode: "path"|"sun"}',
    act: function (opt) {
      var o = (opt && typeof opt === 'object') ? opt : null;
      var last = vcRead().anim || {}, res, fps, secs;
      if (o) {
        res = vcClamp(o.res, 160, 3840, last.res || 1280);
        fps = vcClamp(o.fps, 1, 60, last.fps || 24);
        secs = vcClamp(o.seconds, 0.5, 120, last.seconds || 8);
      } else {
        var a = prompt('Animation render — output width in pixels:', String(last.res || 1280));
        if (a === null) return;
        res = vcClamp(a, 160, 3840, 1280);
        fps = vcClamp(last.fps, 1, 60, 24);
        secs = vcClamp(last.seconds, 0.5, 120, 8);
      }
      var path = vcPath();
      var mode = (o && o.mode) ? String(o.mode).toLowerCase() : (path.length >= 2 ? 'path' : 'sun');
      if (mode === 'path' && path.length < 2) {
        arToast('No walk path to render — recording a sun sweep instead. Press <b>Walk path</b> to record a route.', 'warn');
        mode = 'sun';
      }
      arPush();                                 // the settings below live in the document
      var e = vcWrite();
      e.anim = { res: res, fps: fps, seconds: secs, mode: mode };
      arDirty(true);

      if (mode === 'path') {
        var c = vcCurves(path);
        var dur = Math.max(1, path.length * VC.KEY_MS / 1000);   // never ship a sub-second clip
        return vcRunRecord({
          res: res, fps: fps, total: dur * fps, mute: false,
          hint: 'Animation (walk path)', label: 'Walk-path animation',
          name: vcDocName() + '-walk.webm',
          frame: function (f) { vcSeek(c, f); }
        });
      }
      /* the sun sweep: arSunSet toasts on every call, so it is muted for the
         length of the sweep and the hour is put back when it ends */
      return vcRunRecord({
        res: res, fps: fps, total: secs * fps, mute: true,
        hint: 'Animation (sun 06:00\u219220:00)', label: 'Sun-sweep animation',
        name: vcDocName() + '-sun.webm',
        frame: function (f) { arSunSet(6 + f * 14); }
      });
    }
  };

  /* the two-point preference survives a reload */
  AR_EXT.ready.push(function () {
    if (vcPref('two_point') === '1') VC.two_point = true;
  });
})();
