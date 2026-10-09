// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* scene_shot — the Architecture Studio's shot bridge: put effects and actors in
   the drawing, press Draft, watch the clip, press Full.

     r_anim      ACTION       opens the Shot sheet (shot picker, effects, actors,
                              camera key, Build / Draft / Full, the job log and
                              the finished clip with its placement boxes drawn over it)
     v_walkpath  pointer MODE click ground points to lay an actor's path; the
                              keys are spaced evenly over the shot's frames

   Nothing in inspection.html was edited. Everything that touches disk or
   Blender goes to arch_server_ext/scene_shot.py over
   /inspect/api/architecture/ext/scene_shot/<op>.

   BOTH ids already carried a registration from arch_ext/view_camera.js (the
   WebM recorder and the camera-route recorder), and the bundle is concatenated
   in FILE-NAME order, so a plain assignment here would be silently overwritten
   by view_camera.js. So the registration happens in AR_EXT.ready (after every
   file is loaded) and CHAINS: a call that carries view_camera's own arguments
   ({res, fps, seconds, mode:'path'|'sun'} for r_anim, {mode:'record'|'stop'|
   'play'|'clear'} for v_walkpath) is handed straight back to it, and its `on`
   latch and `_step` sampler are kept. A person clicking the icon, or an
   explicit {shot:...} / {mode:'actor_path'}, gets the shot bridge.

   Studio rules: no record is ever auto-selected; the only sprite this file can
   draw in the viewport (the path-point numbers) is behind SSH.labels, which
   starts OFF. */
(function () {
  'use strict';
  var EXT = window.AR_EXT;
  var API = '/inspect/api/architecture/ext/scene_shot/';
  var VC_ANIM = {res: 1, fps: 1, seconds: 1};                 /* view_camera's r_anim args */
  var VC_WALK = {record: 1, stop: 1, play: 1, clear: 1};      /* view_camera's v_walkpath modes */

  var SH = {
    shot: null,          /* the shot record being edited */
    shots: [],           /* the list op's rows */
    packs: [],           /* volume packs from /inspect/api/vfx/assets */
    proxies: [],         /* actors_available */
    motions: [],         /* the motion library */
    job: null,           /* the running/last job */
    poll: 0,             /* its setTimeout handle */
    actor: '',           /* the actor v_walkpath is laying a path for */
    pts: [],             /* the points clicked so far, studio {x, y, z} */
    marks: null,         /* the THREE.Group holding their markers */
    labels: false,       /* point-number sprites: a switch, and it starts OFF */
    media: ''            /* 'draft' | 'full' — which clip the sheet is showing */
  };
  window.SSH = SH;

  /* ── talking to the family's server half ────────────────────────────── */
  function post(op, body) {
    return fetch(API + op, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body || {})
    }).then(function (r) {
      return r.json().catch(function () { return {error: 'the server did not answer JSON (' + r.status + ')'}; });
    });
  }
  function ask(op, body) {                    /* like post, but an error is a throw */
    return post(op, body).then(function (d) {
      if (d && d.error) throw new Error(d.error);
      return d;
    });
  }
  function fail(e) {
    arToast('<b>Shot</b>: ' + esc(String((e && e.message) || e)), 'bad');
    throw e;
  }
  function nOf(v, d) { var f = parseFloat(v); return isFinite(f) ? f : d; }
  function isArgs(o) { return !!o && typeof o === 'object'; }
  function fmt(n) { return (Math.round(nOf(n, 0) * 1000) / 1000).toString(); }

  /* ── the drawing this shot is of ────────────────────────────────────── */
  function selPoint() {
    /* "at selection": the selected record's own x, y, z in the studio frame */
    if (!AR.sel || !AR.sel.length) return null;
    for (var i = 0; i < AR.objs.length; i++) {
      if (AR.objs[i].id === AR.sel[0]) {
        return {x: nOf(AR.objs[i].x, 0), y: nOf(AR.objs[i].y, 0), z: nOf(AR.objs[i].z, 0)};
      }
    }
    return null;
  }
  function camKey(f) {
    var p = AR.cam.position, t = AR.controls.target;
    return {f: nOf(f, 1), p: [p.x, p.y, p.z], t: [t.x, t.y, t.z],
            fov: (AR.camP && AR.camP.fov) || 50};
  }

  /* ── the catalogues the sheet offers ────────────────────────────────── */
  function loadCatalogues() {
    var jobs = [];
    if (!SH.packs.length) {
      jobs.push(fetch('/inspect/api/vfx/assets').then(function (r) { return r.json(); })
        .then(function (d) {
          SH.packs = (d.files || []).filter(function (x) { return x.k === 'volume'; })
            .map(function (x) { return {f: x.f, n: x.n || x.f, g: x.g || ''}; });
        }).catch(function () { SH.packs = []; }));
    }
    if (!SH.proxies.length) {
      jobs.push(post('actors_available', {}).then(function (d) { SH.proxies = d.actors || []; })
        .catch(function () { SH.proxies = []; }));
    }
    if (!SH.motions.length) {
      jobs.push(post('motions', {}).then(function (d) { SH.motions = d.motions || []; })
        .catch(function () { SH.motions = []; }));
    }
    return Promise.all(jobs);
  }

  function options(items, value, none) {
    var html = none ? '<option value="">' + esc(none) + '</option>' : '';
    for (var i = 0; i < items.length; i++) {
      var v = items[i][0], lb = items[i][1];
      html += '<option value="' + esc(String(v)) + '"' + (String(v) === String(value) ? ' selected' : '') + '>'
            + esc(String(lb)) + '</option>';
    }
    return html;
  }
  function packOpts(v) {
    return options(SH.packs.map(function (p) { return [p.f, (p.g ? p.g + ' \u2014 ' : '') + p.n]; }), v, 'pick a pack\u2026');
  }
  function proxyOpts(v) {
    return options(SH.proxies.map(function (p) { return [p.id, p.id + ' (' + fmt(p.height_m) + ' m)']; }), v, 'no proxy');
  }
  function motionOpts(v) {
    return options(SH.motions.map(function (m) { return [m.id, m.label + ' \u2014 ' + m.id]; }), v, 'still');
  }

  /* ── the sheet ──────────────────────────────────────────────────────── */
  var IN = 'background:#1b1f27;border:1px solid #2a323d;color:inherit;border-radius:5px;padding:2px 5px;font:inherit';
  function num(id, v, step, w) {
    return '<input id="' + id + '" type="number" step="' + (step || 0.1) + '" value="' + esc(String(v))
         + '" style="width:' + (w || 62) + 'px;' + IN + '">';
  }
  function btn(label, call, extra) {
    return '<button onclick="' + call + '" style="' + IN + ';cursor:pointer;padding:3px 9px;'
         + (extra || '') + '">' + label + '</button>';
  }

  function effectRows() {
    var fx = (SH.shot && SH.shot.effects) || [], out = '', i;
    for (i = 0; i < fx.length; i++) {
      var e = fx[i];
      var where = e.rel
        ? ('relative to <b>' + esc(String(e.rel.to)) + '</b> \u2014 right ' + fmt(e.rel.dx)
           + ' m, up ' + fmt(e.rel.dy) + ' m, back ' + fmt(e.rel.dz) + ' m')
        : ('at ' + (e.p || []).map(fmt).join(', '));
      out += '<tr class="ssh-fx" data-id="' + esc(String(e.id)) + '"><td>' + esc(String(e.id)) + '</td>'
           + '<td>' + esc(String(e.pack || '')) + '</td><td>' + fmt(e.size_m) + ' m</td>'
           + '<td>' + where + '</td>'
           + '<td>' + btn('remove', "SSH_fxRemove('" + esc(String(e.id)) + "')") + '</td></tr>';
    }
    if (!out) out = '<tr><td colspan="5">no effects in this shot yet</td></tr>';
    return out;
  }

  function actorRows() {
    var ac = (SH.shot && SH.shot.actors) || [], out = '', i;
    for (i = 0; i < ac.length; i++) {
      var a = ac[i];
      out += '<tr class="ssh-actor" data-id="' + esc(String(a.id)) + '"><td>' + esc(String(a.id)) + '</td>'
           + '<td>' + esc(String(a.char_id || '')) + '</td><td>' + esc(String(a.proxy || '\u2014')) + '</td>'
           + '<td>' + fmt(a.height_m) + ' m</td><td>' + esc(String(a.motion || 'still')) + '</td>'
           + '<td>' + ((a.path || []).length) + ' key' + (((a.path || []).length === 1) ? '' : 's') + '</td>'
           + '<td>' + btn('walk path', "SSH_pathArm('" + esc(String(a.id)) + "')")
           + ' ' + btn('remove', "SSH_actorRemove('" + esc(String(a.id)) + "')") + '</td></tr>';
    }
    if (!out) out = '<tr><td colspan="7">no actors in this shot yet</td></tr>';
    return out;
  }

  function jobLine() {
    var j = SH.job;
    if (!j) return '<span style="color:#9aa4b2">no Blender job has run in this tab yet.</span>';
    var tail = (j.log && j.log.length) ? j.log[j.log.length - 1] : '';
    return '<b>' + esc(j.kind) + '</b> ' + esc(j.state) + ' \u00b7 ' + fmt(j.seconds) + ' s'
         + (j.error ? ' \u2014 <span style="color:#ff8f8f">' + esc(j.error) + '</span>' : '')
         + (tail ? '<br><code style="font-size:.7rem;color:#9aa4b2">' + esc(String(tail).slice(0, 160)) + '</code>' : '');
  }

  function sheet() {
    var s = SH.shot;
    var shotOpts = options(SH.shots.map(function (r) { return [r.id, r.name + ' (' + r.frames + ' f)']; }),
                           s ? s.id : '', 'pick a shot\u2026');
    var head = '<div class="sh">Shot</div>'
      + '<p><select id="ssh-shot" onchange="SSH_open(this.value)" style="' + IN + '">' + shotOpts + '</select> '
      + btn('new shot from this drawing', 'SSH_new()') + '</p>';
    if (!s) {
      arSheet('Shot', head + '<p style="font-size:.72rem;color:#9aa4b2">Pick a shot, or make one from the drawing '
        + 'that is open. A shot is the drawing plus a camera, the actors walking through it and the VFX volumes '
        + 'standing in it.</p>');
      return;
    }
    var body = head
      + '<div class="sh">' + esc(s.name || s.id) + '</div>'
      + arRows([['frames', s.frames + ' at ' + s.fps + ' fps'],
                ['resolution', (s.resolution || []).join(' \u00d7 ')],
                ['drawing', '<code style="font-size:.7rem">' + esc(String(s.drawing).split('/').pop()) + '</code>'],
                ['camera keys', ((s.camera && s.camera.keys) || []).map(function (k) { return 'f' + k.f; }).join(', ')]])

      + '<div class="sh">Effects</div>'
      + '<table class="ar-tbl"><tr><th>id</th><th>pack</th><th>size</th><th>where</th><th></th></tr>'
      + effectRows() + '</table>'
      + '<p style="margin:6px 0 0">'
      + '<select id="ssh-fx-pack" style="' + IN + '">' + packOpts('') + '</select> '
      + num('ssh-fx-size', 1.5, 0.1) + ' m '
      + '<select id="ssh-fx-mode" onchange="SSH_fxMode()" style="' + IN + '">'
      + '<option value="sel">at selection</option><option value="rel">relative to actor</option></select> '
      + '<span id="ssh-fx-rel" style="display:none">'
      + '<select id="ssh-fx-to" style="' + IN + '">'
      + options(((s.actors || []).map(function (a) { return [a.id, a.id]; })), '', 'camera') + '</select> '
      + 'right ' + num('ssh-fx-dx', 1) + ' m, up ' + num('ssh-fx-dy', 0) + ' m, back ' + num('ssh-fx-dz', 2) + ' m'
      + '</span> ' + btn('add effect', 'SSH_fxAdd()') + '</p>'

      + '<div class="sh">Actors</div>'
      + '<table class="ar-tbl"><tr><th>id</th><th>char_id</th><th>proxy</th><th>height</th><th>motion</th>'
      + '<th>path</th><th></th></tr>' + actorRows() + '</table>'
      + '<p style="margin:6px 0 0">id <input id="ssh-a-id" value="" style="width:80px;' + IN + '"> '
      + 'char_id <input id="ssh-a-char" value="" style="width:110px;' + IN + '"> '
      + '<select id="ssh-a-proxy" onchange="SSH_proxyPick()" style="' + IN + '">' + proxyOpts('') + '</select> '
      + num('ssh-a-h', 1.7, 0.01) + ' m '
      + '<select id="ssh-a-motion" style="' + IN + '">' + motionOpts('') + '</select> '
      + btn('add actor', 'SSH_actorAdd()') + '</p>'

      + '<div class="sh">Camera</div>'
      + '<p>' + btn('use the current view as a key at frame', 'SSH_camKey()')
      + ' ' + num('ssh-cam-f', 1, 1, 54) + '</p>'

      + '<div class="sh">Render</div>'
      + '<p>' + btn('Build', 'SSH_run(\'build\')') + ' ' + btn('Draft', 'SSH_run(\'draft\')')
      + ' ' + btn('Full', 'SSH_run(\'full\')')
      + ' &nbsp; <span style="font-size:.72rem;color:#9aa4b2">Draft rebuilds the .blend first if the shot '
      + 'changed since it was built.</span></p>'
      + '<p id="ssh-job" style="font-size:.74rem">' + jobLine() + '</p>'
      + '<div id="ssh-media" style="position:relative;margin-top:8px"></div>';
    arSheet('Shot \u00b7 ' + esc(s.id), body);
    if (SH.media) showMedia(SH.media);
  }

  /* ── the clip, with the placement boxes drawn over it ───────────────── */
  function showMedia(kind) {
    var host = document.getElementById('ssh-media');
    if (!host || !SH.shot) return;
    SH.media = kind;
    var src = API + 'media?id=' + encodeURIComponent(SH.shot.id) + '&kind=' + encodeURIComponent(kind);
    host.innerHTML = '<video id="ssh-video" src="' + src + '" controls muted playsinline '
      + 'style="max-width:100%;display:block;border-radius:6px;background:#111"></video>'
      + '<canvas id="ssh-boxes" style="position:absolute;left:0;top:0;pointer-events:none"></canvas>'
      + '<p style="font-size:.72rem;color:#9aa4b2;margin:4px 0 0" id="ssh-boxes-note">'
      + esc(kind) + ' clip \u2014 loading the placement boxes\u2026</p>';
    post('placement', {id: SH.shot.id, kind: kind}).then(function (d) {
      var note = document.getElementById('ssh-boxes-note');
      if (d.error) { if (note) note.textContent = d.error; return; }
      var pl = d.placement, v = document.getElementById('ssh-video'), cv = document.getElementById('ssh-boxes');
      if (!v || !cv) return;
      if (note) {
        note.innerHTML = esc(kind) + ' clip \u2014 ' + pl.n_frames + ' frames, '
          + (pl.effects || []).length + ' effect box' + (((pl.effects || []).length === 1) ? '' : 'es')
          + ' and ' + (pl.actors || []).length + ' actor mark' + (((pl.actors || []).length === 1) ? '' : 's')
          + ' drawn over it.';
      }
      function paint() {
        var w = v.clientWidth, h = v.clientHeight;
        if (!w || !h) return;
        cv.width = w; cv.height = h; cv.style.width = w + 'px'; cv.style.height = h + 'px';
        var g = cv.getContext('2d'), sx = w / pl.width, sy = h / pl.height;
        g.clearRect(0, 0, w, h);
        var i = Math.max(0, Math.min(pl.frames.length - 1,
                Math.round((v.currentTime || 0) * (pl.fps || 24))));
        var fr = pl.frames[i], id;
        g.lineWidth = 1.5; g.font = '11px system-ui, sans-serif';
        for (id in fr.effects || {}) {
          var e = fr.effects[id];
          if (!e.on_screen || !e.bbox_px) continue;
          g.strokeStyle = '#ffb454'; g.fillStyle = '#ffb454';
          g.strokeRect(e.bbox_px[0] * sx, e.bbox_px[1] * sy,
                       (e.bbox_px[2] - e.bbox_px[0]) * sx, (e.bbox_px[3] - e.bbox_px[1]) * sy);
          g.fillText(id, e.bbox_px[0] * sx + 2, Math.max(10, e.bbox_px[1] * sy - 3));
        }
        for (id in fr.actors || {}) {
          var a = fr.actors[id];
          if (!a.on_screen || !a.ground_px) continue;
          g.strokeStyle = '#7fd4ff'; g.fillStyle = '#7fd4ff';
          g.beginPath(); g.arc(a.ground_px[0] * sx, a.ground_px[1] * sy, 4, 0, Math.PI * 2); g.stroke();
          g.fillText(id, a.ground_px[0] * sx + 6, a.ground_px[1] * sy - 4);
        }
      }
      v.addEventListener('loadedmetadata', paint);
      v.addEventListener('timeupdate', paint);
      v.addEventListener('seeked', paint);
      SH._paint = paint;
      paint();
    });
  }

  /* ── the sheet's buttons (family-prefixed globals, as the house does) ── */
  window.SSH_open = function (id) {
    if (!id) { SH.shot = null; SH.media = ''; sheet(); return Promise.resolve(null); }
    return ask('get', {id: id}).then(function (d) {
      SH.shot = d.shot; SH.media = '';
      /* park it as the CURRENT shot: tools in other studios (the VFX Studio's
         "Place in 3D scene") add to whatever the operator has open here */
      post('set_current', {id: id});
      if ((d.errors || []).length) arToast('Shot <b>' + esc(id) + '</b>: ' + esc(d.errors.join('; ')), 'warn');
      sheet();
      return d.shot;
    }).catch(fail);
  };

  window.SSH_new = function (id, name) {
    var sid = id || prompt('A name for the new shot (letters, digits, - and _):', 'shot_1');
    if (!sid) return Promise.resolve(null);
    return ask('new', {id: String(sid), name: name || String(sid), doc: arDocOut(), camera: camKey(1)})
      .then(function (d) {
        SH.shot = d.shot; SH.media = '';
        arToast('Shot <b>' + esc(d.shot.id) + '</b> made from this drawing \u2014 ' + d.shot.frames + ' frames.');
        return refreshList().then(sheet).then(function () { return d.shot; });
      }).catch(fail);
  };

  window.SSH_fxMode = function () {
    var m = document.getElementById('ssh-fx-mode'), r = document.getElementById('ssh-fx-rel');
    if (m && r) r.style.display = (m.value === 'rel') ? '' : 'none';
  };

  window.SSH_fxAdd = function () {
    if (!SH.shot) return Promise.resolve(null);
    var pack = (document.getElementById('ssh-fx-pack') || {}).value || '';
    if (!pack) { arToast('Pick a volume pack first.', 'warn'); return Promise.resolve(null); }
    var fx = {pack: pack, size_m: nOf((document.getElementById('ssh-fx-size') || {}).value, 1.5), start_frame: 1};
    if (((document.getElementById('ssh-fx-mode') || {}).value) === 'rel') {
      fx.rel = {to: (document.getElementById('ssh-fx-to') || {}).value || 'camera',
                dx: nOf((document.getElementById('ssh-fx-dx') || {}).value, 0),
                dy: nOf((document.getElementById('ssh-fx-dy') || {}).value, 0),
                dz: nOf((document.getElementById('ssh-fx-dz') || {}).value, 0)};
    } else {
      var p = selPoint();
      if (!p) { arToast('Select the object the effect stands at, or place it relative to an actor.', 'warn'); return Promise.resolve(null); }
      fx.p = [p.x, p.y, p.z];
    }
    return ask('add_effect', {id: SH.shot.id, effect: fx}).then(function (d) {
      SH.shot = d.shot; sheet();
      arToast('Effect <b>' + esc(d.shot.effects[d.shot.effects.length - 1].id) + '</b> added.');
      return d.shot;
    }).catch(fail);
  };

  window.SSH_fxRemove = function (fid) {
    if (!SH.shot) return Promise.resolve(null);
    return ask('remove_effect', {id: SH.shot.id, effect_id: fid})
      .then(function (d) { SH.shot = d.shot; sheet(); return d.shot; }).catch(fail);
  };

  window.SSH_proxyPick = function () {
    var v = (document.getElementById('ssh-a-proxy') || {}).value || '', i;
    for (i = 0; i < SH.proxies.length; i++) {
      if (SH.proxies[i].id !== v) continue;
      var h = document.getElementById('ssh-a-h'), m = document.getElementById('ssh-a-motion');
      var idf = document.getElementById('ssh-a-id');
      if (h && SH.proxies[i].height_m) h.value = SH.proxies[i].height_m;
      if (m && SH.proxies[i].motion) m.value = SH.proxies[i].motion;
      if (idf && !idf.value) idf.value = v;
    }
  };

  window.SSH_actorAdd = function (spec) {
    if (!SH.shot) return Promise.resolve(null);
    var a = isArgs(spec) ? spec : {
      id: ((document.getElementById('ssh-a-id') || {}).value || '').trim(),
      char_id: ((document.getElementById('ssh-a-char') || {}).value || '').trim(),
      proxy: (document.getElementById('ssh-a-proxy') || {}).value || '',
      height_m: nOf((document.getElementById('ssh-a-h') || {}).value, 1.7),
      motion: (document.getElementById('ssh-a-motion') || {}).value || ''
    };
    var p = selPoint() || {x: 0, y: 0, z: 0};
    a.path = a.path || [{f: 1, p: [p.x, p.y, p.z], ry: 180}];
    return ask('add_actor', {id: SH.shot.id, actor: a}).then(function (d) {
      SH.shot = d.shot; sheet();
      arToast('Actor <b>' + esc(d.shot.actors[d.shot.actors.length - 1].id) + '</b> added \u2014 press '
            + '<b>walk path</b> and click the ground to lay their route.');
      return d.shot;
    }).catch(fail);
  };

  window.SSH_actorRemove = function (aid) {
    if (!SH.shot) return Promise.resolve(null);
    return ask('remove_actor', {id: SH.shot.id, actor_id: aid})
      .then(function (d) { SH.shot = d.shot; sheet(); return d.shot; }).catch(fail);
  };

  window.SSH_camKey = function (f) {
    if (!SH.shot) return Promise.resolve(null);
    var fr = (f === undefined) ? nOf((document.getElementById('ssh-cam-f') || {}).value, 1) : nOf(f, 1);
    return ask('set_camera_key', {id: SH.shot.id, key: camKey(fr)}).then(function (d) {
      SH.shot = d.shot; sheet();
      arToast('Camera key at frame <b>' + fmt(fr) + '</b> \u2014 '
            + d.shot.camera.keys.length + ' key' + (d.shot.camera.keys.length === 1 ? '' : 's') + ' now.');
      return d.shot;
    }).catch(fail);
  };

  window.SSH_run = function (kind, opt) {
    if (!SH.shot) { arToast('Pick a shot first.', 'warn'); return Promise.resolve(null); }
    var body = {id: SH.shot.id};
    if (kind === 'draft' && isArgs(opt) && opt.frames) body.frames = opt.frames;
    return ask(kind, body).then(function (d) {
      SH.job = d.job;
      arHint('<b>' + esc(kind) + '</b> running on ' + esc(SH.shot.id) + '\u2026');
      pollJob();
      return d.job;
    }).catch(fail);
  };

  function pollJob() {
    if (SH.poll) { clearTimeout(SH.poll); SH.poll = 0; }
    if (!SH.job) return;
    post('job', {jid: SH.job.id}).then(function (d) {
      if (d.error) { arHint(''); return; }
      SH.job = d.job;
      var line = document.getElementById('ssh-job');
      if (line) line.innerHTML = jobLine();
      if (d.job.state === 'running' || d.job.state === 'queued') {
        SH.poll = setTimeout(pollJob, 2000);
        return;
      }
      arHint('');
      if (d.job.state === 'failed') { arToast('<b>' + esc(d.job.kind) + '</b> failed: ' + esc(d.job.error), 'bad'); return; }
      arToast('<b>' + esc(d.job.kind) + '</b> finished in ' + fmt(d.job.seconds) + ' s.');
      if (d.job.kind === 'draft' || d.job.kind === 'full') showMedia(d.job.kind);
    });
  }
  window.SSH_poll = pollJob;

  function refreshList() {
    return post('list', {}).then(function (d) { SH.shots = d.shots || []; return SH.shots; })
      .catch(function () { return SH.shots; });
  }

  function openSheet(opt) {
    return loadCatalogues().then(refreshList).then(function () {
      var want = isArgs(opt) && opt.shot ? String(opt.shot)
               : (SH.shot ? SH.shot.id : (SH.shots.length === 1 ? SH.shots[0].id : ''));
      if (want) return window.SSH_open(want);
      sheet();
      return null;
    });
  }

  /* ── v_walkpath as a pointer MODE: click the ground, lay the path ────── */
  function marksGroup() {
    if (!SH.marks) {
      SH.marks = new THREE.Group();
      SH.marks.name = 'ssh-path';
      AR.scene.add(SH.marks);
    }
    return SH.marks;
  }
  function clearMarks() {
    if (!SH.marks) return;
    while (SH.marks.children.length) {
      var m = SH.marks.children.pop();
      if (m.geometry) m.geometry.dispose();
      if (m.material) m.material.dispose();
      SH.marks.remove(m);
    }
  }
  function addMark(p, n) {
    var g = marksGroup();
    var dot = new THREE.Mesh(new THREE.SphereGeometry(0.12, 10, 8),
                             new THREE.MeshBasicMaterial({color: 0x7fd4ff}));
    dot.position.set(p.x, p.y + 0.12, p.z);
    g.add(dot);
    if (SH.pts.length > 1) {
      var a = SH.pts[SH.pts.length - 2];
      var line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(
        [new THREE.Vector3(a.x, a.y + 0.12, a.z), new THREE.Vector3(p.x, p.y + 0.12, p.z)]),
        new THREE.LineBasicMaterial({color: 0x7fd4ff}));
      g.add(line);
    }
    /* the only sprite this file can draw, and it is behind a switch that starts OFF */
    if (SH.labels && typeof arLabelSprite === 'function') {
      var s = arLabelSprite(String(n));
      if (s) { s.position.set(p.x, p.y + 0.45, p.z); g.add(s); }
    }
  }

  function pathFrames() {
    var n = SH.pts.length;
    var frames = (SH.shot && SH.shot.frames) || 49;
    if (n < 2) return [1];
    var out = [], i;
    for (i = 0; i < n; i++) out.push(Math.round(1 + i * (frames - 1) / (n - 1)));
    return out;
  }

  function pathCommit() {
    if (!SH.shot || !SH.actor || SH.pts.length < 1) return Promise.resolve(null);
    var fs = pathFrames(), keys = [], i;
    for (i = 0; i < SH.pts.length; i++) {
      var p = SH.pts[i], ry = 180;
      if (i < SH.pts.length - 1) {
        var q = SH.pts[i + 1];
        /* heading: ry = 0 faces (0,0,-1), positive ry turns counter-clockwise from above */
        ry = Math.atan2(-(q.x - p.x), -(q.z - p.z)) * 180 / Math.PI;
      } else if (i > 0) {
        /* the last point keeps the heading it arrived with */
        ry = keys[keys.length - 1].ry;
      }
      keys.push({f: fs[i], p: [p.x, p.y, p.z], ry: Math.round(ry * 100) / 100});
    }
    var actors = (SH.shot.actors || []).map(function (a) {
      return (a.id === SH.actor) ? Object.assign({}, a, {path: keys}) : a;
    });
    var shot = Object.assign({}, SH.shot, {actors: actors});
    return ask('save', {shot: shot}).then(function (d) {
      SH.shot = d.shot;
      arToast('Walk path for <b>' + esc(SH.actor) + '</b>: ' + keys.length + ' key'
            + (keys.length === 1 ? '' : 's') + ' over frames ' + fs[0] + '\u2013' + fs[fs.length - 1] + '.');
      sheet();
      return d.shot;
    }).catch(fail);
  }

  window.SSH_pathArm = function (aid) {
    if (!SH.shot) return null;
    SH.actor = aid || ((SH.shot.actors || [])[0] || {}).id || '';
    if (!SH.actor) { arToast('Add an actor first, then lay their path.', 'warn'); return null; }
    SH.pts = [];
    clearMarks();
    arToolApply('v_walkpath');
    arToast('Click the ground where <b>' + esc(SH.actor) + '</b> walks. <b>Esc</b> ends the path.');
    return SH.actor;
  };

  EXT.modes.v_walkpath = {
    hint: function () {
      if (!SH.actor) return 'Walk path \u2014 open <b>Shot</b> and press <b>walk path</b> on an actor first.';
      var n = SH.pts.length, fs = pathFrames();
      return 'Walk path for <b>' + esc(SH.actor) + '</b> \u2014 ' + n + ' point' + (n === 1 ? '' : 's')
        + (n > 1 ? (', frames ' + fs[0] + '\u2013' + fs[fs.length - 1] + ' (' + Math.round((fs[1] - fs[0])) + ' apart)') : '')
        + '. Click the ground to add another \u00b7 <b>Esc</b> ends and saves.';
    },
    click: function (P) {
      if (!P) return;
      if (!SH.actor) { arToast('Open <b>Shot</b> and press <b>walk path</b> on an actor first.', 'warn'); return; }
      var p = {x: P.x, y: nOf(P.y, 0), z: P.z};
      SH.pts.push(p);
      addMark(p, SH.pts.length);
      arDraftHint();
    },
    cancel: function () {
      if (!SH.actor || !SH.pts.length) { clearMarks(); return; }
      var n = SH.pts.length;
      pathCommit();
      SH.pts = [];
      clearMarks();
      SH.actor = '';
      if (n) arHint('');
    },
    key: function (e) {
      if (e && e.key === 'Enter') { EXT.modes.v_walkpath.cancel(); return true; }
      return false;
    }
  };

  /* ── the two icons, chained behind whatever already holds them ───────── */
  EXT.ready.push(function () {
    var prevAnim = EXT.tools.r_anim, prevWalk = EXT.tools.v_walkpath;

    EXT.tools.r_anim = Object.assign({}, prevAnim, {
      assist: 1,
      tip: 'Shot \u2014 the drawing as a Blender scene: VFX volumes, actors and a camera, drafted in seconds '
         + 'and then rendered full. Args: {shot: "id"} opens one; view_camera\u2019s {res, fps, mode:"path"|"sun"} '
         + 'still renders a WebM of the view.',
      act: function (opt) {
        var vcArgs = isArgs(opt) && (VC_ANIM[Object.keys(opt)[0]] || opt.mode === 'path' || opt.mode === 'sun'
                     || opt.res !== undefined || opt.fps !== undefined || opt.seconds !== undefined);
        if (vcArgs && prevAnim && prevAnim.act) return prevAnim.act(opt);
        return openSheet(opt);
      }
    });

    var walkMode = EXT.modes.v_walkpath;
    EXT.tools.v_walkpath = Object.assign({}, prevWalk, {
      assist: 1,
      tip: 'Walk path \u2014 click ground points to lay the selected actor\u2019s route through the shot. '
         + 'Args: {mode: "actor_path", actor: "id"}; view_camera\u2019s {mode: "record"|"stop"|"play"|"clear"} '
         + 'still records the camera route.',
      on: function () {
        if (AR.tool === 'v_walkpath' && SH.actor) return true;
        return !!(prevWalk && prevWalk.on && prevWalk.on());
      },
      act: function (opt) {
        var m = isArgs(opt) && opt.mode ? String(opt.mode).toLowerCase() : '';
        if (m && VC_WALK[m] && prevWalk && prevWalk.act) return prevWalk.act(opt);
        if (!m && prevWalk && prevWalk.act && !SH.shot) return prevWalk.act(opt);
        return window.SSH_pathArm(isArgs(opt) ? opt.actor : undefined);
      }
    });
    if (walkMode) EXT.modes.v_walkpath = walkMode;
  });
})();
