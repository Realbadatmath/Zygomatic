// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* share_collab — the Share dock group, wired for real (2026-09-07).

   Six icons that were placeholders: Share link (c_link), Markup (c_note),
   Issues (c_issues), Compare (c_compare), Change log (c_log), Present
   (c_present). Nothing in inspection.html was edited to make them real: the
   ICON seam (AR_EXT.tools / AR_EXT.modes / AR_EXT.geom / AR_EXT.ticks /
   AR_EXT.ready) is the whole contract.

   Where the state lives, and why:
     · a SHARE is a copy on the server (arch_server_ext/share_collab.py), not a
       pointer at the author's live drawing — a link that changes under the
       person reading it is not a link.
     · a MARKUP NOTE is a record of kind `markup_note`: it belongs to the
       drawing, moves with Save/Open/undo, and is a void in Blender.
     · ISSUES, the CHANGE LOG and the stored VIEWS are AR.doc.ext.share_collab
       — document-level state, saved with the drawing and round-tripped
       through the assistant.
   Every edit of the document goes behind ONE arPush() called first; the
   read-only sheets (Issues ▸ list, Change log, Compare) never push.

   Three.js is r144, nothing extra is vendored: the note labels are
   THREE.Sprite over a canvas, the ghosts are meshes built through arGeom. */
(function () {
  'use strict';

  var DEF_COL = '#ffcc00';          /* the markup yellow */
  var ISSUE_COL = '#ff5544';        /* an issue pin is not a friendly note */
  var DEF_SIZE = 0.4;
  var TWEEN_MS = 1200;              /* the Present cross-fade between views */

  /* module state that is NOT part of the drawing: sprites, ghosts, the
     presentation. None of it is saved; all of it is rebuilt from the doc. */
  var ST = {sprites: new Map(), ghosts: null, playing: null, stop: false, bars: null};

  /* ── the markup pin: a cone under a bead ─────────────────────────────── */
  AR_EXT.geom.markup_note = function (p, k) {
    var T = k.THREE, s = Math.max(0.05, k.num(p.size, DEF_SIZE));
    var cone = new T.ConeGeometry(s * 0.30, s * 1.5, 12);
    cone.rotateX(Math.PI);                       /* tip down, onto the point */
    cone.translate(0, s * 0.75, 0);
    var bead = new T.SphereGeometry(s * 0.36, 16, 12);
    bead.translate(0, s * 1.75, 0);
    return [{g: cone}, {g: bead, sub: 'mat_plaster'}];
  };
  AR_EXT.label.markup_note = 'Markup note';

  /* ── document state ──────────────────────────────────────────────────── */
  function extRead() {                            /* never mutates: for reports */
    var e = (AR.doc && AR.doc.ext && AR.doc.ext.share_collab) || {};
    return {issues: Array.isArray(e.issues) ? e.issues : [],
            log: Array.isArray(e.log) ? e.log : [],
            views: Array.isArray(e.views) ? e.views : []};
  }
  function extWrite() {                           /* for edits, behind arPush() */
    AR.doc.ext = AR.doc.ext || {};
    var e = AR.doc.ext.share_collab;
    if (!e || typeof e !== 'object') { e = AR.doc.ext.share_collab = {}; }
    if (!Array.isArray(e.issues)) e.issues = [];
    if (!Array.isArray(e.log)) e.log = [];
    if (!Array.isArray(e.views)) e.views = [];
    return e;
  }
  function logAdd(who, what) {
    var e = extWrite();
    e.log.push({t: new Date().toISOString(), who: who, what: String(what).slice(0, 300)});
    if (e.log.length > 500) e.log.splice(0, e.log.length - 500);
    return e.log[e.log.length - 1];
  }
  function post(op, body) {
    return fetch('/inspect/api/architecture/ext/share_collab/' + op,
      {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})})
      .then(function (r) { return r.json(); });
  }

  /* ── cells (the inverse of arCellName, which the tab does not publish) ── */
  function cellXZ(txt) {
    var s = String(txt || '').trim().toUpperCase().replace(/\s+/g, '');
    var m = /^([A-Z]{1,2})(\d{1,3})$/.exec(s);
    if (!m) return null;
    var c = 0, i;
    for (i = 0; i < m[1].length; i++) c = c * 26 + (m[1].charCodeAt(i) - 64);
    c -= 1;
    var r = parseInt(m[2], 10) - 1;
    if (c < 0 || r < 0 || c >= AR_CELL_N || r >= AR_CELL_N) return null;
    return {x: AR_CELL_O + (c + 0.5) * AR_CELL_M, z: AR_CELL_O + (r + 0.5) * AR_CELL_M};
  }

  /* ── note sprites: my own Map, synced every frame ────────────────────── */
  function spriteFor(txt, col, size) {
    var f = 30, pad = 10, cv = document.createElement('canvas'), g = cv.getContext('2d');
    var font = '600 ' + f + 'px system-ui, -apple-system, Segoe UI, sans-serif';
    g.font = font;
    var w = Math.min(900, Math.ceil(g.measureText(txt).width) + pad * 2), h = f + pad * 2;
    cv.width = Math.max(24, w); cv.height = h;
    g = cv.getContext('2d');
    g.font = font; g.textBaseline = 'middle';
    g.fillStyle = 'rgba(16,18,22,0.86)';
    g.fillRect(0, 0, cv.width, cv.height);
    g.strokeStyle = col || DEF_COL; g.lineWidth = 3;
    g.strokeRect(1.5, 1.5, cv.width - 3, cv.height - 3);
    g.fillStyle = '#f4f6fa';
    g.fillText(txt, pad, h / 2 + 1);
    var tex = new THREE.CanvasTexture(cv);
    var sp = new THREE.Sprite(new THREE.SpriteMaterial({map: tex, transparent: true, depthTest: false, depthWrite: false}));
    sp.renderOrder = 999;
    var sc = Math.max(0.1, size || DEF_SIZE) * 1.9;
    sp.scale.set(sc * cv.width / cv.height, sc, 1);
    sp.userData.shareCollab = 1;
    return sp;
  }
  function dropSprite(sp) {
    AR.scene.remove(sp);
    if (sp.material) { if (sp.material.map) sp.material.map.dispose(); sp.material.dispose(); }
  }
  function syncSprites() {
    if (!AR.scene) return;
    var seen = {};
    AR.objs.forEach(function (o) {
      if (o.kind !== 'markup_note') return;
      seen[o.id] = 1;
      var txt = String((o.p && o.p.txt) || ''), col = String((o.p && o.p.col) || DEF_COL);
      var size = arNum(o.p && o.p.size, DEF_SIZE);
      var sp = ST.sprites.get(o.id);
      if (sp && (sp.userData.txt !== txt || sp.userData.col !== col || sp.userData.size !== size)) {
        dropSprite(sp); ST.sprites.delete(o.id); sp = null;
      }
      if (!sp) {
        sp = spriteFor(txt || '(empty note)', col, size);
        sp.userData.txt = txt; sp.userData.col = col; sp.userData.size = size; sp.userData.arId = o.id;
        AR.scene.add(sp); ST.sprites.set(o.id, sp);
      }
      sp.visible = !o.hidden;
      sp.position.set(o.x, o.y + size * 2.6, o.z);
    });
    ST.sprites.forEach(function (sp, id) {
      if (!seen[id]) { dropSprite(sp); ST.sprites.delete(id); }
    });
  }
  AR_EXT.ticks.push(syncSprites);

  /* place one pin. The CALLER owns the arPush(). */
  function pinAt(x, z, y, txt, col) {
    var rec = arNewObj('markup_note', {txt: String(txt).slice(0, 300), col: col || DEF_COL, size: DEF_SIZE}, x, z, y);
    rec.name = 'Note: ' + String(txt).slice(0, 40);
    rec.mat = 'mat_plaster'; arApplyMat(rec);
    return rec;
  }
  function centreOf(ids) {
    var box = new THREE.Box3(), any = false;
    ids.forEach(function (id) {
      var r = arFind(id);
      if (r && r.node && !r.hidden) { box.expandByObject(r.node); any = true; }
    });
    if (any && !box.isEmpty()) {
      var c = box.getCenter(new THREE.Vector3());
      return {x: c.x, y: box.max.y, z: c.z};
    }
    var sx = 0, sy = 0, sz = 0, n = 0;
    ids.forEach(function (id) { var r = arFind(id); if (r) { sx += r.x; sy += r.y; sz += r.z; n++; } });
    return n ? {x: sx / n, y: sy / n, z: sz / n} : {x: 0, y: AR.level, z: 0};
  }

  /* ══ c_link — a read-only link to this drawing ═══════════════════════ */
  function makeShare(days) {
    return post('share', {doc: arDocOut(), name: AR.doc.name || 'Shared drawing',
                          expires_days: days, origin: location.origin});
  }
  function copyLink(url) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(url).then(function () { return true; })
          .catch(function () { prompt('Copy this share link:', url); return false; });
      }
    } catch (e) { /* no clipboard in this context: the prompt is the fallback */ }
    prompt('Copy this share link:', url);
    return Promise.resolve(false);
  }
  function shareBanner(on, name) {
    var st = document.getElementById('ar-stage');
    var el = document.getElementById('ar-share-banner');
    if (!on) { if (el && el.parentNode) el.parentNode.removeChild(el); return null; }
    if (!st) return null;
    if (!el) {
      el = document.createElement('div');
      el.id = 'ar-share-banner';
      el.style.cssText = 'position:absolute;left:50%;top:12px;transform:translateX(-50%);z-index:60;'
        + 'padding:6px 14px;border-radius:14px;background:' + DEF_COL + ';color:#171717;'
        + 'font:600 12px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;box-shadow:0 3px 12px rgba(0,0,0,.4);'
        + 'pointer-events:none;white-space:nowrap';
      st.appendChild(el);
    }
    el.innerHTML = 'Shared copy — <b>Save as</b> to keep' + (name ? ' &middot; ' + esc(name) : '');
    return el;
  }
  function loadShared(token) {
    return fetch('/inspect/api/architecture/ext/share_collab/shared?t=' + encodeURIComponent(token))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) {
          shareBanner(false);
          arToast('That share link ' + (d.expired ? 'has expired' : 'could not be opened') + '.', 'bad');
          return d;
        }
        var doc = d.doc || {};
        arInjectDoc(doc.objects || [], {sync: true});
        /* read-only: no project id (so Save asks for a name), every record
           locked (so nothing is picked or dragged), and a banner saying so. */
        AR.doc = {id: '', name: d.name || 'Shared drawing',
                  ext: (doc.ext && typeof doc.ext === 'object') ? doc.ext : {}};
        AR.objs.forEach(function (o) { o.lock = true; });
        AR.sel = []; AR.undo = []; AR.redo = [];
        arSelSync(); arOutliner(); arPanel(); arDocName(); arHud(); arDirty(false);
        shareBanner(true, d.name || '');
        arToast('Opened the shared copy <b>' + esc(d.name || '') + '</b> — '
          + AR.objs.length + ' objects, read-only. <b>Save as</b> to keep it.');
        return d;
      });
  }
  AR_EXT.tools.c_link = {
    assist: 1,
    tip: 'A read-only link to this drawing on this machine, for someone on the LAN — copied to the clipboard',
    act: function (opt) {
      var days = 30;
      if (opt && typeof opt === 'object' && opt.expires_days !== undefined && opt.expires_days !== null) {
        days = Number(opt.expires_days);
        if (!isFinite(days) || days < 0) days = 30;
      }
      return makeShare(days).then(function (d) {
        if (!d.ok) { arToast('Share failed: ' + esc(String(d.error || 'unknown')), 'bad'); return d; }
        return copyLink(d.url).then(function (copied) {
          arToast('Share link ' + (copied ? 'copied to the clipboard' : 'ready') + ': <b>' + esc(d.url) + '</b> — '
            + d.objects + ' objects, read-only, '
            + (d.expires_days ? ('expires in ' + arFmt(d.expires_days) + ' day' + (d.expires_days === 1 ? '' : 's')) : 'no expiry') + '.');
          return d;
        });
      });
    },
    _loadShared: loadShared,
    _share: makeShare,
    _banner: shareBanner
  };

  /* ══ c_note — pin a comment to a point ═══════════════════════════════ */
  AR_EXT.modes.c_note = {
    click: function (P, e, g) {
      var pt = P || (g ? {x: g.x, z: g.z, y: AR.level} : null);
      if (!pt) { arToast('Click on the drawing plane to pin a note there.', 'warn'); return; }
      var txt = prompt('Note text:', 'Note');
      if (!txt) return;
      arPush();
      var rec = pinAt(pt.x, pt.z, (pt.y === undefined ? AR.level : pt.y), txt, DEF_COL);
      logAdd('operator', 'markup "' + String(txt).slice(0, 80) + '" at ' + (arCellName(pt.x, pt.z) || arFmt(pt.x) + ', ' + arFmt(pt.z)));
      arDirty(true); arOutliner(); arPanel(); arHud();
      arToast('Note pinned at <b>' + esc(arCellName(rec.x, rec.z) || (arFmt(rec.x) + ', ' + arFmt(rec.z))) + '</b>.');
    },
    move: function () { },
    hint: function () { return 'Markup — click a point to pin a comment there. <b>Esc</b> stops.'; },
    cancel: function () { }
  };
  AR_EXT.tools.c_note = {
    assist: 1, tog: 1,
    tip: 'Pin a comment to a point in the model — click a point, type the note',
    on: function () { return AR.tool === 'c_note'; },
    act: function (opt) {
      var o = (opt && typeof opt === 'object') ? opt : null;
      if (o && (o.text !== undefined || o.cell !== undefined)) {
        var txt = String(o.text === undefined ? '' : o.text).trim();
        if (!txt) { arToast('A markup needs some text.', 'warn'); return null; }
        var at = o.cell ? cellXZ(o.cell) : null;
        if (o.cell && !at) { arToast('“' + esc(String(o.cell)) + '” is not a cell name.', 'bad'); return null; }
        if (!at) {
          var b = arBounds(AR.sel.length > 0);
          at = {x: b.c.x, z: b.c.z};
        }
        arPush();
        var rec = pinAt(at.x, at.z, arNum(o.y, AR.level), txt, o.col || DEF_COL);
        logAdd('assistant', 'markup "' + txt.slice(0, 80) + '" at ' + (arCellName(rec.x, rec.z) || 'the drawing centre'));
        arDirty(true); arOutliner(); arPanel(); arHud();
        arToast('Note pinned at <b>' + esc(arCellName(rec.x, rec.z) || (arFmt(rec.x) + ', ' + arFmt(rec.z))) + '</b>.');
        return rec;
      }
      if (AR.tool === 'c_note') { arToolApply('select'); arHint('Markup off.'); return null; }
      arToolApply('c_note');
      return null;
    },
    _pin: pinAt
  };

  /* ══ c_issues — the list of open markups ═════════════════════════════ */
  function openCount() {
    return extRead().issues.filter(function (i) { return i.status !== 'closed'; }).length;
  }
  function issueAdd(title, ids) {
    var sel = (Array.isArray(ids) && ids.length) ? ids.slice() : AR.sel.slice();
    if (!sel.length) { arToast('Select the objects the issue is about first.', 'warn'); return null; }
    var t = (title === undefined || title === null || !String(title).trim())
      ? prompt('What is the issue?', 'Issue') : String(title);
    if (!t) return null;
    t = String(t).trim().slice(0, 200);
    arPush();
    var e = extWrite();
    var n = e.issues.reduce(function (a, i) { return Math.max(a, i.n || 0); }, 0) + 1;
    var c = centreOf(sel);
    var pin = pinAt(c.x, c.z, c.y, '#' + n + ' ' + t, ISSUE_COL);
    var iss = {n: n, title: t, ids: sel, status: 'open', created: new Date().toISOString(),
               by: 'operator', pin: pin.id};
    e.issues.push(iss);
    logAdd('operator', 'issue #' + n + ' opened: ' + t);
    arDirty(true); arOutliner(); arPanel(); arHud();
    arToast('Issue <b>#' + n + '</b> opened on ' + sel.length + ' object' + (sel.length === 1 ? '' : 's')
      + ' — <b>' + openCount() + '</b> open of ' + e.issues.length + '.');
    return iss;
  }
  function issueSet(n, status) {
    var e = extRead(), num = Number(n);
    var iss = e.issues.filter(function (i) { return i.n === num; })[0];
    if (!iss) { arToast('No issue #' + esc(String(n)) + ' in this drawing.', 'warn'); return null; }
    if (iss.status === status) { arToast('Issue #' + num + ' is already ' + status + '.'); return iss; }
    arPush();
    var live = extWrite().issues.filter(function (i) { return i.n === num; })[0];
    live.status = status;
    logAdd('operator', 'issue #' + num + ' ' + (status === 'closed' ? 'closed' : 'reopened') + ': ' + live.title);
    arDirty(true);
    arToast('Issue <b>#' + num + '</b> ' + status + ' — <b>' + openCount() + '</b> still open of ' + e.issues.length + '.');
    return live;
  }
  function issueSheet() {
    var e = extRead();
    if (!e.issues.length) {
      arSheet('Issues', '<div class="ar-empty">No issues yet. Select what the issue is about and press '
        + '<b>Issues</b> again with a title, or use the assistant\'s add_issue.</div>');
      return 0;
    }
    var rows = e.issues.slice().sort(function (a, b) { return (a.status === b.status) ? a.n - b.n : (a.status === 'closed' ? 1 : -1); })
      .map(function (i) {
        var go = '<button onclick="shareCollabIssueGo(' + i.n + ')">go</button>';
        var tg = i.status === 'closed'
          ? '<button onclick="shareCollabIssueSet(' + i.n + ',\'open\')">reopen</button>'
          : '<button onclick="shareCollabIssueSet(' + i.n + ',\'closed\')">close</button>';
        return ['<b>#' + i.n + '</b> ' + esc(i.title),
                esc(i.status) + ' &middot; ' + (i.ids || []).length + ' object'
                + (((i.ids || []).length) === 1 ? '' : 's') + ' &middot; ' + go + ' ' + tg];
      });
    arSheet('Issues — ' + openCount() + ' open of ' + e.issues.length, arRows(rows));
    return e.issues.length;
  }
  window.shareCollabIssueGo = function (n) {
    var iss = extRead().issues.filter(function (i) { return i.n === Number(n); })[0];
    if (!iss) return;
    var ids = (iss.ids || []).filter(function (id) { return !!arFind(id); });
    if (!ids.length) { arToast('The objects issue #' + n + ' was about are gone.', 'warn'); return; }
    arFitIds(ids); arSelect(ids);
  };
  window.shareCollabIssueSet = function (n, status) { issueSet(n, status); issueSheet(); };
  AR_EXT.tools.c_issues = {
    assist: 1,
    tip: 'The list of open markups, with what is still unresolved — add one from the selection, go to it, close it',
    act: function (opt) {
      var o = (opt && typeof opt === 'object') ? opt : {};
      var a = String(o.action || 'list').toLowerCase();
      if (a === 'add') { var r = issueAdd(o.title, o.ids); issueSheet(); return r; }
      if (a === 'close' || a === 'closed') { var c = issueSet(o.n !== undefined ? o.n : o.ids, 'closed'); issueSheet(); return c; }
      if (a === 'reopen' || a === 'open') { var p = issueSet(o.n !== undefined ? o.n : o.ids, 'open'); issueSheet(); return p; }
      if (a === 'status') { var s = issueSet(o.n !== undefined ? o.n : o.ids, o.status === 'closed' ? 'closed' : 'open'); issueSheet(); return s; }
      var n = issueSheet();
      arToast('Issues: <b>' + openCount() + '</b> open of ' + n + '.');
      return n;
    },
    _add: issueAdd, _set: issueSet
  };

  /* ══ c_compare — this drawing against another save ═══════════════════ */
  function pKey(p) {
    var k = Object.keys(p || {}).sort(), o = {};
    k.forEach(function (x) { o[x] = p[x]; });
    return JSON.stringify(o);
  }
  function diffDocs(cur, other) {
    var A = {}, B = {}, added = [], removed = [], changed = [];
    cur.forEach(function (o) { A[o.id] = o; });
    other.forEach(function (o) { B[o.id] = o; });
    cur.forEach(function (o) { if (!B[o.id]) added.push(o); });
    other.forEach(function (o) { if (!A[o.id]) removed.push(o); });
    Object.keys(A).forEach(function (id) {
      var a = A[id], b = B[id];
      if (!b) return;
      var f = [];
      if (pKey(a.p) !== pKey(b.p)) f.push('p');
      ['x', 'y', 'z', 'ry'].forEach(function (k) {
        if (Math.abs(arNum(a[k], 0) - arNum(b[k], 0)) > 1e-6) f.push(k);
      });
      if (String(a.mat || '') !== String(b.mat || '')) f.push('mat');
      if (f.length) changed.push({id: id, kind: a.kind, name: a.name || a.kind, fields: f});
    });
    return {added: added, removed: removed, changed: changed};
  }
  function ghostsClear() {
    if (!ST.ghosts) return;
    ST.ghosts.traverse(function (o) { if (o.geometry) o.geometry.dispose(); });
    if (ST.ghosts.parent) ST.ghosts.parent.remove(ST.ghosts);
    if (ST.ghostMat) { ST.ghostMat.dispose(); ST.ghostMat = null; }
    ST.ghosts = null;
  }
  function ghostsShow(res) {
    ghostsClear();
    var grp = new THREE.Group();
    grp.name = 'share_collab_ghosts';
    ST.ghostMat = new THREE.MeshStandardMaterial({color: 0xff3322, transparent: true, opacity: 0.35,
                                                  roughness: 0.85, metalness: 0, depthWrite: false});
    res.removed.forEach(function (o) {
      var parts = [];
      try { parts = arGeom(o.kind, o.p || {}) || []; } catch (e) { parts = []; }
      var g = new THREE.Group();
      parts.forEach(function (pt) {
        if (!pt.g || pt.line) return;
        g.add(new THREE.Mesh(pt.g, ST.ghostMat));
      });
      if (!g.children.length) return;
      g.position.set(arNum(o.x, 0), arNum(o.y, 0), arNum(o.z, 0));
      g.rotation.set(arNum(o.rx, 0), arNum(o.ry, 0), arNum(o.rz, 0));
      var s = arNum(o.s, 1); g.scale.set(s, s, s);
      grp.add(g);
    });
    res.added.forEach(function (o) {
      var rec = arFind(o.id);
      if (!rec || !rec.node) return;
      var box = new THREE.Box3().setFromObject(rec.node);
      if (box.isEmpty()) return;
      grp.add(new THREE.Box3Helper(box, new THREE.Color(0x22dd55)));
    });
    AR.scene.add(grp);
    ST.ghosts = grp;
    return grp;
  }
  function compareSheet(name, res) {
    function list(items, label) {
      if (!items.length) return '<tr><td>' + label + '</td><td>none</td></tr>';
      return items.slice(0, 200).map(function (o, i) {
        var what = o.fields ? (esc(o.name || o.id) + ' — ' + o.fields.join(', ')) : esc((o.name || o.kind || '?') + ' (' + o.id + ')');
        return '<tr><td>' + (i ? '' : label) + '</td><td>' + what + '</td></tr>';
      }).join('');
    }
    /* the ONE sheet the ghosts belong to: the arSheet wrapper below clears them
       for every other sheet, so this call says so out loud. */
    ST.opening = 1;
    try {
      arSheet('Compare with ' + esc(name),
        '<table class="ar-tbl">'
        + '<tr><td>added here (green outline)</td><td><b>' + res.added.length + '</b></td></tr>'
        + list(res.added, 'added')
        + '<tr><td>removed since (red ghosts)</td><td><b>' + res.removed.length + '</b></td></tr>'
        + list(res.removed, 'removed')
        + '<tr><td>changed</td><td><b>' + res.changed.length + '</b></td></tr>'
        + list(res.changed, 'changed')
        + '</table>');
    } finally { ST.opening = 0; }
  }
  function compareWith(pid, stamp) {
    return post('other', {pid: pid, stamp: stamp || ''}).then(function (d) {
      if (!d.ok) { arToast('Compare failed: ' + esc(String(d.error || 'unknown')), 'bad'); return d; }
      var res = diffDocs(arDocOut().objects, (d.doc && d.doc.objects) || []);
      res.name = d.name || pid;
      ghostsShow(res);
      compareSheet(res.name, res);
      arToast('Compared with <b>' + esc(res.name) + '</b>: <b>+' + res.added.length + '</b> added, <b>&minus;'
        + res.removed.length + '</b> removed, <b>' + res.changed.length + '</b> changed. Closing the sheet clears the ghosts.');
      return res;
    });
  }
  function compareList() {
    return post('others', {}).then(function (d) {
      var rows = [];
      (d.drawings || []).forEach(function (p) {
        if (p.pid === AR.doc.id) return;             /* comparing with itself proves nothing */
        rows.push(['<b>' + esc(p.n) + '</b>', p.objects + ' objects &middot; '
          + '<button onclick="shareCollabCompare(\'' + esc(p.pid) + '\',\'\')">compare</button>']);
        (p.versions || []).forEach(function (v) {
          rows.push(['&nbsp;&nbsp;version ' + esc(v.stamp), '<button onclick="shareCollabCompare(\''
            + esc(p.pid) + '\',\'' + esc(v.stamp) + '\')">compare</button>']);
        });
      });
      if (!rows.length) {
        arSheet('Compare', '<div class="ar-empty">No other saved drawing to compare with — save this one under a second name first.</div>');
        return 0;
      }
      arSheet('Compare with…', arRows(rows));
      return rows.length;
    });
  }
  window.shareCollabCompare = function (pid, stamp) { compareWith(pid, stamp); };
  AR_EXT.tools.c_compare = {
    assist: 1,
    tip: 'Two saves side by side: what was added, removed (red ghosts) and changed since another drawing or version',
    act: function (opt) {
      var o = (opt && typeof opt === 'object') ? opt : {};
      if (o.pid) return compareWith(String(o.pid), String(o.stamp || ''));
      if (o.stamp && AR.doc.id) return compareWith(AR.doc.id, String(o.stamp));
      return compareList();
    },
    _ghosts: function () { return ST.ghosts; },
    _diff: diffDocs
  };

  /* ══ c_log — what changed and when ═══════════════════════════════════ */
  function logSheet() {
    var e = extRead();
    var head = '<div style="margin:0 0 8px"><button onclick="shareCollabLogCsv()">download CSV</button> '
      + '<button onclick="shareCollabLogClear()">clear</button></div>';
    if (!e.log.length) {
      arSheet('Change log', head + '<div class="ar-empty">Nothing logged yet. Saves, assistant injections and issues write themselves here.</div>');
      return 0;
    }
    var rows = e.log.slice().reverse().map(function (r) {
      return [esc(String(r.t || '').replace('T', ' ').slice(0, 19)) + ' &middot; ' + esc(r.who || '?'), esc(r.what || '')];
    });
    arSheet('Change log — ' + e.log.length + ' entr' + (e.log.length === 1 ? 'y' : 'ies'), head + arRows(rows));
    return e.log.length;
  }
  window.shareCollabLogCsv = function () {
    var e = extRead();
    var q = function (s) { return '"' + String(s === undefined ? '' : s).replace(/"/g, '""') + '"'; };
    var csv = ['when,who,what'].concat(e.log.map(function (r) {
      return [q(r.t), q(r.who), q(r.what)].join(',');
    })).join('\n');
    arDownload(new Blob([csv], {type: 'text/csv'}),
      (AR.doc.name || 'drawing').replace(/[^\w-]+/g, '_') + '_changelog.csv');
    arToast('Change log downloaded — ' + e.log.length + ' entries.');
  };
  window.shareCollabLogClear = function () {
    if (!extRead().log.length) { arToast('The change log is already empty.'); return; }
    arPush();
    extWrite().log = [];
    arDirty(true);
    logSheet();
    arToast('Change log cleared. <b>Ctrl+Z</b> puts it back.');
  };
  AR_EXT.tools.c_log = {
    assist: 1,
    tip: 'What changed in this drawing and when — saves, assistant injections and issues, written as they happen',
    act: function () { return logSheet(); },
    _add: logAdd
  };

  /* ══ c_present — a slideshow of stored views ═════════════════════════ */
  function viewAdd(name) {
    var e0 = extRead();
    var nm = (name === undefined || name === null || !String(name).trim())
      ? prompt('Name for this view:', 'View ' + (e0.views.length + 1)) : String(name);
    if (!nm) return null;
    nm = String(nm).trim().slice(0, 80);
    arPush();
    var e = extWrite();
    var v = {name: nm, cam: arCamState(), notes: ''};
    e.views.push(v);
    logAdd('operator', 'view "' + nm + '" stored');
    arDirty(true);
    arToast('View <b>' + esc(nm) + '</b> stored — ' + e.views.length + ' in the presentation.');
    return v;
  }
  function viewRemove(name) {
    var e = extRead(), nm = String(name === undefined ? '' : name).trim();
    var i = -1;
    e.views.forEach(function (v, j) { if (i < 0 && v.name === nm) i = j; });
    if (i < 0 && /^\d+$/.test(nm)) i = parseInt(nm, 10) - 1;
    if (i < 0 || i >= e.views.length) { arToast('No stored view called “' + esc(nm) + '”.', 'warn'); return null; }
    arPush();
    var gone = extWrite().views.splice(i, 1)[0];
    logAdd('operator', 'view "' + (gone && gone.name) + '" removed');
    arDirty(true);
    arToast('View <b>' + esc(gone.name) + '</b> removed.');
    return gone;
  }
  function viewSheet() {
    var e = extRead();
    var head = '<div style="margin:0 0 8px"><button onclick="shareCollabViewAdd()">add this view</button> '
      + '<button onclick="shareCollabPlay()">play</button></div>';
    if (!e.views.length) {
      arSheet('Present', head + '<div class="ar-empty">No stored views yet. Point the camera where you want it and press <b>add this view</b>.</div>');
      return 0;
    }
    var rows = e.views.map(function (v, i) {
      var n = esc(v.name);
      return ['<b>' + (i + 1) + '.</b> ' + n,
        '<button onclick="shareCollabViewGo(' + i + ')">go</button> '
        + '<button onclick="shareCollabViewRename(' + i + ')">rename</button> '
        + '<button onclick="shareCollabViewRemove(' + i + ')">remove</button>'];
    });
    arSheet('Present — ' + e.views.length + ' view' + (e.views.length === 1 ? '' : 's'), head + arRows(rows));
    return e.views.length;
  }
  function tweenTo(cam, ms) {
    return new Promise(function (resolve) {
      if (!cam || !cam.p || !cam.t) { resolve(false); return; }
      var p0 = AR.cam.position.clone(), t0 = AR.controls.target.clone();
      var p1 = new THREE.Vector3().fromArray(cam.p), t1 = new THREE.Vector3().fromArray(cam.t);
      var t = performance.now();
      (function step() {
        var k = Math.min(1, (performance.now() - t) / Math.max(1, ms));
        var e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;   /* ease in-out */
        AR.cam.position.lerpVectors(p0, p1, e);
        AR.controls.target.lerpVectors(t0, t1, e);
        AR.controls.update();
        if (k < 1 && !ST.stop) { requestAnimationFrame(step); return; }
        arCamApply(cam);                       /* land on the exact stored state */
        resolve(true);
      })();
    });
  }
  function play(seconds) {
    var e = extRead();
    if (!e.views.length) {
      arToast('No stored views to present — add one with the camera where you want it.', 'warn');
      return Promise.resolve(0);
    }
    if (ST.playing) { ST.stop = true; return ST.playing; }
    var hold = Math.max(0, isFinite(seconds) ? Number(seconds) : 4);
    ST.stop = false;
    ST.bars = AR.bars;
    if (AR.bars) arBarsToggle();               /* presenter mode: no panels */
    arSheetClose();
    var i = 0;
    var p = new Promise(function (resolve) {
      function step() {
        if (ST.stop || i >= e.views.length) { done(); resolve(i); return; }
        var v = e.views[i++];
        tweenTo(v.cam, TWEEN_MS).then(function () {
          if (ST.stop) { done(); resolve(i); return; }
          arHint('Presenting <b>' + esc(v.name) + '</b> — ' + i + ' / ' + e.views.length + '. <b>Esc</b> stops.');
          setTimeout(step, hold * 1000);
        });
      }
      function done() {
        ST.playing = null; ST.stop = false;
        if (ST.bars && !AR.bars) arBarsToggle();   /* the bars come back exactly as they were */
        ST.bars = null;
        arHint('Presentation finished — ' + i + ' of ' + e.views.length + ' views.');
      }
      step();
    });
    ST.playing = p;
    return p;
  }
  window.shareCollabViewAdd = function () { viewAdd(); viewSheet(); };
  window.shareCollabViewGo = function (i) {
    var v = extRead().views[i];
    if (!v) return;
    arCamPush(); arCamApply(v.cam);
    arToast('View <b>' + esc(v.name) + '</b>.');
  };
  window.shareCollabViewRemove = function (i) {
    var v = extRead().views[i];
    if (v) { viewRemove(v.name); viewSheet(); }
  };
  window.shareCollabViewRename = function (i) {
    var e0 = extRead(), v = e0.views[i];
    if (!v) return;
    var nm = prompt('Rename this view:', v.name);
    if (!nm) return;
    arPush();
    extWrite().views[i].name = String(nm).trim().slice(0, 80);
    logAdd('operator', 'view renamed to "' + String(nm).trim().slice(0, 80) + '"');
    arDirty(true); viewSheet();
  };
  window.shareCollabPlay = function (s) { return play(s === undefined ? 4 : s); };
  AR_EXT.tools.c_present = {
    assist: 1,
    tip: 'Presenter mode — the bars go away and the camera steps through the stored views; Esc stops',
    act: function (opt) {
      var o = (opt && typeof opt === 'object') ? opt : {};
      var a = String(o.action || 'list').toLowerCase();
      if (a === 'add') { var v = viewAdd(o.name); viewSheet(); return v; }
      if (a === 'play') return play(o.seconds === undefined ? 4 : Number(o.seconds));
      if (a === 'remove') { var r = viewRemove(o.name); viewSheet(); return r; }
      return viewSheet();
    },
    _play: play, _add: viewAdd
  };

  /* ── the wrappers, once the engine exists ────────────────────────────── */
  AR_EXT.ready.push(function () {
    /* (a) every SAVE writes a log line — appended BEFORE the base call so it
       is inside the document that gets written, with the record-count delta
       against the previous save. */
    var baseSave = arSave;
    arSave = function (asNew) {
      try {
        var e = extWrite(), n = AR.objs.length;
        var prev = (typeof e.lastSaveN === 'number') ? e.lastSaveN : null;
        e.lastSaveN = n;
        logAdd('operator', 'save: ' + n + ' objects'
          + (prev === null ? ' (first save)' : ' (' + (n - prev >= 0 ? '+' : '') + (n - prev) + ' since the last save)'));
      } catch (err) { console.error('share_collab save log', err); }
      return baseSave(asNew);
    };

    /* (b) every assistant INJECTION writes one — object counts before and
       after, plus what was asked for. arAssistApply already opened an undo
       step, so this lands inside it without a push of its own. */
    var baseApply = arAssistApply;
    arAssistApply = function (res, done) {
      var before = AR.objs.length, ask = '';
      try {
        var h = (AR.assist && AR.assist.hist) || [];
        for (var i = h.length - 1; i >= 0; i--) {
          if (h[i] && h[i].role === 'user') { ask = String(h[i].text || ''); break; }
        }
      } catch (e) { /* no history is not an error */ }
      return baseApply(res, function (n) {
        try {
          logAdd('assistant', 'injection: ' + before + ' → ' + AR.objs.length + ' objects'
            + (ask ? ' — "' + ask.slice(0, 120) + '"' : ''));
        } catch (e) { console.error('share_collab assist log', e); }
        if (done) done(n);
      });
    };

    /* (c) closing the sheet drops Compare's ghosts — they belong to the report,
       not to the drawing. Opening a DIFFERENT sheet over it is closing it too:
       there is one sheet, so whoever takes it takes the viewport back. */
    var baseClose = arSheetClose;
    arSheetClose = function () { ghostsClear(); return baseClose(); };
    var baseSheet = arSheet;
    arSheet = function (title, html) { if (!ST.opening) ghostsClear(); return baseSheet(title, html); };

    /* (d) Esc stops a presentation. AR_EXT.keys cannot bind Escape, so the
       loop polls a flag this listener sets. */
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && ST.playing) { ST.stop = true; }
    });

    /* (e) honour /inspection.html#architecture&share=<token>: open the shared
       copy read-only. Nothing else about the hash is touched or persisted. */
    var m = /[#&?]share=([0-9a-fA-F]{12})\b/.exec(location.hash || '');
    if (m) { setTimeout(function () { loadShared(m[1].toLowerCase()); }, 0); }
  });
})();
