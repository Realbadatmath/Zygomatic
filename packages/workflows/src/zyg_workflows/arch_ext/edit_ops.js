// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* edit_ops — Edit ▸ Align, Distribute, History, Purge unused (2026-09-07).

   Four dock icons of the Edit section that were placeholders until this file
   registered them through the ICON seam. Nothing in inspection.html was edited.

     e_align    align the selection's edges/centres/faces to a reference object
     e_dist     distribute the selection evenly between the two outermost objects
     e_history  the undo ring as a labelled LIST you can jump into
     e_purge    report and remove what nothing in the drawing refers to any more

   Every geometric decision is taken on the WORLD bounding box of the record's
   node (THREE.Box3.setFromObject), so a rotated wall, a lathe dome and a slab
   all answer the same question the same way.  The assistant's server-side twins
   in arch_assistant_ext/edit_ops.py repeat the same arithmetic on the plan
   footprint, which is why the two agree to within a few centimetres.

   Licence: this file is part of the Zygomatic repository; it uses only the
   studio's own globals and three.js r144 (MIT), already vendored.
*/
(function () {
  'use strict';

  /* ── little geometry helpers ─────────────────────────────────────────── */
  var AXIS_OF = {left: 'x', right: 'x', centerx: 'x',
                 back: 'z', front: 'z', centerz: 'z',
                 bottom: 'y', top: 'y', face: '*'};
  var MODE_LIST = 'left, right, centerx, back, front, centerz, top, bottom, face';

  function eoBox(rec) {
    if (!rec || !rec.node) return null;
    var b = new THREE.Box3();
    b.setFromObject(rec.node);
    return b.isEmpty() ? null : b;
  }
  function eoLo(b, a) { return a === 'x' ? b.min.x : a === 'y' ? b.min.y : b.min.z; }
  function eoHi(b, a) { return a === 'x' ? b.max.x : a === 'y' ? b.max.y : b.max.z; }
  function eoMid(b, a) { return (eoLo(b, a) + eoHi(b, a)) / 2; }
  function eoSize(b, a) { return eoHi(b, a) - eoLo(b, a); }
  function eoShift(rec, a, d) {
    var v = (a === 'x' ? rec.x : a === 'y' ? rec.y : rec.z) + d;
    v = Math.round(v * 1e6) / 1e6;
    if (a === 'x') rec.x = v; else if (a === 'y') rec.y = v; else rec.z = v;
  }
  function eoItems() {
    var out = [];
    arSelRecs().forEach(function (r) {
      var b = eoBox(r);
      if (b) out.push({r: r, b: b});
    });
    return out;
  }
  function eoAsk(opt, key, dflt, question) {
    if (opt && typeof opt === 'object') {
      var v = opt[key];
      return (v === undefined || v === null || v === '') ? dflt : String(v).trim().toLowerCase();
    }
    var a = prompt(question, dflt);
    if (a === null) return null;
    a = String(a).trim().toLowerCase();
    return a || dflt;
  }
  function eoAfter(recs) {
    recs.forEach(arApplyTransform);
    arSyncHoles();
    arSelSync(); arPanel(); arHud(); arDirty(true);
  }

  /* ── e_align ─────────────────────────────────────────────────────────── */
  function eoAlign(opt) {
    var items = eoItems();
    if (items.length < 2) { arToast('Align needs at least two objects selected.', 'warn'); return; }
    var mode = eoAsk(opt, 'mode', localStorage.getItem('ar.edit_ops.mode') || 'left',
                     'Align the selection — ' + MODE_LIST);
    if (mode === null) return;
    if (!AXIS_OF[mode]) { arToast('Unknown align mode <b>' + esc(mode) + '</b> — use ' + MODE_LIST + '.', 'bad'); return; }
    var to = eoAsk(opt, 'to', 'last', 'Align to which object — last, first or selection?');
    if (to === null) return;
    if (to !== 'first' && to !== 'selection') to = 'last';
    localStorage.setItem('ar.edit_ops.mode', mode);

    var ref = null, refBox;
    if (to === 'selection') {
      refBox = new THREE.Box3();
      items.forEach(function (it) { refBox.union(it.b); });
    } else {
      var pick = (to === 'first') ? items[0] : items[items.length - 1];
      ref = pick.r; refBox = pick.b;
    }

    var ax = AXIS_OF[mode], plan = [];
    items.forEach(function (it) {
      if (ref && it.r === ref) return;
      var a = ax, d;
      if (mode === 'face') {
        /* no pointer: the axis on which the two centres differ most IS the
           axis the face faces; the near side of the mover meets the near
           side of the reference, so the two boxes end up touching. */
        var best = 'x', bd = -1;
        ['x', 'y', 'z'].forEach(function (k) {
          var v = Math.abs(eoMid(it.b, k) - eoMid(refBox, k));
          if (v > bd) { bd = v; best = k; }
        });
        a = best;
        d = (eoMid(it.b, a) >= eoMid(refBox, a))
          ? (eoHi(refBox, a) - eoLo(it.b, a))
          : (eoLo(refBox, a) - eoHi(it.b, a));
      } else if (mode === 'left' || mode === 'back' || mode === 'bottom') {
        d = eoLo(refBox, a) - eoLo(it.b, a);
      } else if (mode === 'right' || mode === 'front' || mode === 'top') {
        d = eoHi(refBox, a) - eoHi(it.b, a);
      } else {
        d = eoMid(refBox, a) - eoMid(it.b, a);
      }
      if (isFinite(d) && Math.abs(d) > 1e-9) plan.push({r: it.r, a: a, d: d});
    });

    if (!plan.length) { arToast('Already aligned — nothing moved.'); return; }
    arPush();
    plan.forEach(function (m) { eoShift(m.r, m.a, m.d); });
    eoAfter(plan.map(function (m) { return m.r; }));
    arToast('Aligned <b>' + plan.length + '</b> object' + (plan.length === 1 ? '' : 's')
            + ' — ' + esc(mode) + ' to the ' + esc(to) + ' selected.');
  }

  /* ── e_dist ──────────────────────────────────────────────────────────── */
  function eoDistribute(opt) {
    var items = eoItems();
    if (items.length < 3) { arToast('Distribute needs at least three objects selected.', 'warn'); return; }
    var axis = eoAsk(opt, 'axis', localStorage.getItem('ar.edit_ops.axis') || 'auto',
                     'Distribute along which axis — x, z or auto?');
    if (axis === null) return;
    if (axis !== 'x' && axis !== 'z') {
      var sx = 0, sz = 0, cx = [], cz = [];
      items.forEach(function (it) { cx.push(eoMid(it.b, 'x')); cz.push(eoMid(it.b, 'z')); });
      sx = Math.max.apply(null, cx) - Math.min.apply(null, cx);
      sz = Math.max.apply(null, cz) - Math.min.apply(null, cz);
      axis = (sz > sx) ? 'z' : 'x';
    }
    localStorage.setItem('ar.edit_ops.axis', axis);

    var a = axis;
    items.sort(function (p, q) { return eoMid(p.b, a) - eoMid(q.b, a); });
    var n = items.length;
    var span = eoLo(items[n - 1].b, a) - eoHi(items[0].b, a);   /* clear space between the outer two */
    var bulk = 0;
    for (var i = 1; i < n - 1; i++) bulk += eoSize(items[i].b, a);
    var gap = (span - bulk) / (n - 1);                          /* the CAD convention: equal EDGE gaps */

    var plan = [], cursor = eoHi(items[0].b, a);
    for (var j = 1; j < n - 1; j++) {
      var want = cursor + gap;
      var d = want - eoLo(items[j].b, a);
      if (isFinite(d) && Math.abs(d) > 1e-9) plan.push({r: items[j].r, a: a, d: d});
      cursor = want + eoSize(items[j].b, a);
    }
    if (!plan.length) { arToast('Already evenly spaced — nothing moved.'); return; }
    arPush();
    plan.forEach(function (m) { eoShift(m.r, m.a, m.d); });
    eoAfter(plan.map(function (m) { return m.r; }));
    arToast('Distributed <b>' + n + '</b> objects along ' + a.toUpperCase()
            + ' — gap ' + arFmt(gap) + ' m'
            + (gap < 0 ? ' <b>(they overlap: the outer two are closer than the rest are wide)</b>' : '') + '.');
  }

  /* ── e_history: a label per undo snapshot ────────────────────────────── */
  function eoParse(s) { try { return JSON.parse(s) || []; } catch (e) { return []; } }
  function eoKinds(list) {
    var seen = {}, out = [];
    list.forEach(function (o) {
      var k = arKindLabel(o.kind) || o.kind;
      if (!seen[k]) { seen[k] = 1; out.push(k); }
    });
    return out.slice(0, 3).join('/') + (out.length > 3 ? '…' : '');
  }
  function eoDiff(prevJson, nextJson) {
    var A = eoParse(prevJson), B = eoParse(nextJson);
    var ma = {}, mb = {};
    A.forEach(function (o) { ma[o.id] = o; });
    B.forEach(function (o) { mb[o.id] = o; });
    var added = [], removed = [], changed = [];
    B.forEach(function (o) {
      if (!ma[o.id]) added.push(o);
      else if (JSON.stringify(ma[o.id]) !== JSON.stringify(o)) changed.push(o);
    });
    A.forEach(function (o) { if (!mb[o.id]) removed.push(o); });
    var parts = [];
    if (added.length) parts.push('+' + added.length + ' ' + eoKinds(added));
    if (removed.length) parts.push('\u2212' + removed.length + ' ' + eoKinds(removed));
    if (changed.length) parts.push(changed.length + ' changed (' + eoKinds(changed) + ')');
    return parts.length ? parts.join(', ') : 'no change';
  }
  function eoHistSync() {
    var h = AR._edit_opsHist = AR._edit_opsHist || [];
    while (h.length > AR.undo.length) h.shift();          /* the ring shifted its oldest away */
    while (h.length < AR.undo.length) h.unshift({t: 0, label: 'earlier edit'});
    return h;
  }
  function eoClock(t) {
    if (!t) return '';
    var d = new Date(t);
    return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2)
         + ':' + ('0' + d.getSeconds()).slice(-2);
  }
  function eoHistSheet() {
    var h = eoHistSync(), rows = [];
    var live = h.length ? eoDiff(AR.undo[AR.undo.length - 1], arSnapshot()) : 'no change';
    rows.push(['<b>current state</b> &mdash; ' + esc(live),
               '<span class="mut">' + AR.objs.length + ' object' + (AR.objs.length === 1 ? '' : 's') + '</span>']);
    for (var k = h.length - 1; k >= 0; k--) {
      var back = h.length - k;
      rows.push(['<a href="#" onclick="edit_ops_histGo(' + back + ');return false;">' + esc(h[k].label) + '</a>',
                 esc(eoClock(h[k].t)) + ' &middot; back ' + back + ' step' + (back === 1 ? '' : 's')]);
    }
    if (!h.length) rows.push(['nothing to undo yet', 'the drawing is at its opening state']);
    arSheet('Undo history',
            '<p class="mut">Newest first. Clicking a row runs that many real undos, so Redo still works.</p>'
            + arRows(rows));
  }
  window.edit_ops_histGo = function (back) {
    back = Math.max(0, Math.min(AR.undo.length, Math.round(Number(back) || 0)));
    for (var i = 0; i < back; i++) arUndo();
    arSyncHoles(); arHud();
    eoHistSheet();
    arToast('Jumped back <b>' + back + '</b> step' + (back === 1 ? '' : 's') + '.');
  };
  function eoHistory(opt) {
    if (opt && typeof opt === 'object' && opt.back !== undefined && opt.back !== null && opt.back !== '') {
      window.edit_ops_histGo(opt.back);
      return;
    }
    eoHistSheet();
  }

  /* ── e_purge ─────────────────────────────────────────────────────────── */
  function eoBag() {
    var e = (AR.doc && AR.doc.ext) || {};
    var om = (e.organise_model && typeof e.organise_model === 'object') ? e.organise_model : null;
    return {
      comps: (om && om.components) || e.components || null,
      compHost: (om && om.components) ? om : ((e.components) ? e : null),
      sets: (om && om.sets) || e.sets || e.selection_sets || null,
      setHost: (om && om.sets) ? om : (e.sets ? e : (e.selection_sets ? e : null)),
      setKey: (om && om.sets) ? 'sets' : (e.sets ? 'sets' : 'selection_sets'),
      layers: (om && om.layers) || e.layers || null,
      layerHost: (om && om.layers) ? om : (e.layers ? e : null)
    };
  }
  function eoKeysOf(bagv) {
    if (!bagv) return [];
    if (Array.isArray(bagv)) return bagv.map(function (v, i) { return String((v && (v.name || v.id)) || i); });
    if (typeof bagv === 'object') return Object.keys(bagv);
    return [];
  }
  function eoDropKey(host, key, name) {
    var v = host[key];
    if (Array.isArray(v)) host[key] = v.filter(function (e, i) { return String((e && (e.name || e.id)) || i) !== name; });
    else if (v && typeof v === 'object') delete v[name];
  }
  function eoEntry(bagv, name) {
    if (Array.isArray(bagv)) {
      for (var i = 0; i < bagv.length; i++) {
        if (String((bagv[i] && (bagv[i].name || bagv[i].id)) || i) === name) return bagv[i];
      }
      return null;
    }
    return (bagv && typeof bagv === 'object') ? bagv[name] : null;
  }
  function eoWallDist(o, w) {
    var len = arNum(w.p.len, 4), t = arNum(w.p.t, 0.24), h = arNum(w.p.h, 2.7);
    if (o.y < w.y - 0.05 || o.y > w.y + h - 0.05) return 1e9;
    var c = Math.cos(-(w.ry || 0)), s = Math.sin(-(w.ry || 0));
    var dx = o.x - w.x, dz = o.z - w.z;
    var lx = dx * c - dz * s, lz = dx * s + dz * c;
    var ox = Math.max(0, Math.abs(lx) - len / 2), oz = Math.max(0, Math.abs(lz) - t / 2);
    return Math.sqrt(ox * ox + oz * oz);
  }
  function eoTexOf(m) {
    var out = [];
    Object.keys(m).forEach(function (k) { if (m[k] && m[k].isTexture) out.push(m[k]); });
    return out;
  }
  function eoPurge(opt) {
    var args = (opt && typeof opt === 'object') ? opt : null;

    /* 1. materials nothing in the drawing refers to. A record's node is asked
       as well as its `mat` field, because a geometry part may carry its own
       `sub` material (glass in a window, tile on a roof). Hidden records COUNT
       as users: their meshes still hold the material object, and disposing it
       under them would be a bug dressed as a tidy-up. */
    var used = {};
    AR.objs.forEach(function (o) {
      if (o.mat) used[o.mat] = 1;
      if (!o.node) return;
      o.node.traverse(function (m) {
        if (!m.material) return;
        var ms = Array.isArray(m.material) ? m.material : [m.material];
        ms.forEach(function (mm) { if (mm && mm.userData && mm.userData.arId) used[mm.userData.arId] = 1; });
      });
    });
    var freedMats = [];
    Object.keys(AR.matCache).forEach(function (k) {
      if (used[k.split('|')[0]]) return;
      var m = AR.matCache[k];
      delete AR.matCache[k];
      freedMats.push(k);
      try { m.dispose(); } catch (e) { /* already gone */ }
    });
    var keep = {};
    Object.keys(AR.matCache).forEach(function (k) {
      eoTexOf(AR.matCache[k]).forEach(function (t) { keep[t.uuid] = 1; });
    });
    var freedTex = 0;
    AR.texCache = AR.texCache || {};
    Object.keys(AR.texCache).forEach(function (k) {
      var t = AR.texCache[k];
      if (!t || keep[t.uuid]) return;
      delete AR.texCache[k];
      freedTex++;
      try { t.dispose(); } catch (e) { /* already gone */ }
    });

    /* 2. component definitions with no instance, selection sets naming only
       gone ids, layers with no members and no lock/hidden state. */
    var bag = eoBag(), live = {};
    AR.objs.forEach(function (o) { live[o.id] = o; });
    var compNames = [], setNames = [], layerNames = [];
    eoKeysOf(bag.comps).forEach(function (name) {
      var n = 0;
      AR.objs.forEach(function (o) {
        var m = o.meta || {};
        if (m.component === name || m.comp === name) n++;
      });
      if (!n) compNames.push(name);
    });
    eoKeysOf(bag.sets).forEach(function (name) {
      var e = eoEntry(bag.sets, name);
      var ids = (e && (e.ids || e.objects)) || (Array.isArray(e) ? e : []);
      if (!ids.length) return;
      var alive = ids.filter(function (i) { return live[i]; });
      if (!alive.length) setNames.push(name);
    });
    eoKeysOf(bag.layers).forEach(function (name) {
      var e = eoEntry(bag.layers, name) || {};
      if (e.lock || e.locked || e.hidden) return;
      var n = 0;
      AR.objs.forEach(function (o) { if ((o.meta || {}).layer === name) n++; });
      if (!n) layerNames.push(name);
    });
    if (compNames.length && bag.compHost) compNames.forEach(function (n) { eoDropKey(bag.compHost, 'components', n); });
    if (setNames.length && bag.setHost) setNames.forEach(function (n) { eoDropKey(bag.setHost, bag.setKey, n); });
    if (layerNames.length && bag.layerHost) layerNames.forEach(function (n) { eoDropKey(bag.layerHost, 'layers', n); });

    /* 3. orphan openings — a door whose wall was deleted. arSyncHoles is the
       studio's own host finder, so it decides, not us; the 0.5 m rule is the
       second opinion the brief asks for. */
    arSyncHoles();
    var walls = AR.objs.filter(function (o) { return o.kind === 'wall' || o.kind === 'partition'; });
    var orphans = AR.objs.filter(function (o) {
      if (!arIsOpening(o.kind)) return false;
      if (o.p && o.p.host) return false;
      for (var i = 0; i < walls.length; i++) if (eoWallDist(o, walls[i]) <= 0.5) return false;
      return true;
    });
    var deleted = 0;
    if (orphans.length) {
      var go = args ? !!args.orphans
        : confirm('Delete ' + orphans.length + ' orphan opening' + (orphans.length === 1 ? '' : 's')
                  + ' — the wall each one was cut into is gone?');
      if (go) {
        arPush();                                   /* the only branch that changes records */
        orphans.forEach(arRemove);
        deleted = orphans.length;
        AR.sel = AR.sel.filter(function (i) { return !!arFind(i); });
        arSyncHoles(); arSelSync(); arOutliner(); arPanel(); arHud(); arDirty(true);
      }
    }

    var rows = [
      ['materials freed', '<b>' + freedMats.length + '</b>' + (freedMats.length ? ' &mdash; ' + esc(freedMats.join(', ')) : '')],
      ['textures freed', String(freedTex)],
      ['materials still in use', String(Object.keys(AR.matCache).length)],
      ['component definitions with no instance', compNames.length ? '<b>' + compNames.length + '</b> removed &mdash; ' + esc(compNames.join(', ')) : '0'],
      ['selection sets naming only deleted objects', setNames.length ? '<b>' + setNames.length + '</b> removed &mdash; ' + esc(setNames.join(', ')) : '0'],
      ['empty unlocked layers', layerNames.length ? '<b>' + layerNames.length + '</b> removed &mdash; ' + esc(layerNames.join(', ')) : '0'],
      ['orphan openings (host wall gone)', '<b>' + orphans.length + '</b>' + (deleted ? ' &mdash; ' + deleted + ' deleted' : (orphans.length ? ' &mdash; kept, press again to confirm' : ''))]
    ];
    orphans.forEach(function (o) {
      rows.push(['&nbsp;&nbsp;orphan ' + esc(o.id),
                 esc(arKindLabel(o.kind)) + ' &ldquo;' + esc(o.name) + '&rdquo; at '
                 + arFmt(o.x) + ', ' + arFmt(o.z)]);
    });
    rows.push(['empty groups', 'implicit &mdash; a group with no members does not exist as a record']);
    arSheet('Purge unused', arRows(rows));
    arToast('Purge: <b>' + freedMats.length + '</b> materials, <b>' + freedTex + '</b> textures, '
            + '<b>' + (compNames.length + setNames.length + layerNames.length) + '</b> definitions, '
            + '<b>' + orphans.length + '</b> orphan opening' + (orphans.length === 1 ? '' : 's')
            + (deleted ? ' (deleted)' : '') + '.');
  }

  /* ── the history wrappers: labels parallel to AR.undo ────────────────── */
  AR_EXT.ready.push(function () {
    if (AR._edit_opsWrapped) return;
    AR._edit_opsWrapped = 1;
    AR._edit_opsHist = AR._edit_opsHist || [];
    AR._edit_opsRedo = AR._edit_opsRedo || [];

    var basePush = arPush, baseUndo = arUndo, baseRedo = arRedo,
        baseNew = arNew, baseOpen = arOpen;

    arPush = function () {
      if (AR._quiet) { basePush(); return; }               /* a quiet push is not a push */
      var prev = AR.undo.length ? AR.undo[AR.undo.length - 1] : null;
      var now = arSnapshot();
      basePush();
      var h = AR._edit_opsHist;
      h.push({t: Date.now(),
              label: (prev === null) ? ('opened \u2014 ' + eoParse(now).length + ' objects') : eoDiff(prev, now)});
      AR._edit_opsRedo.length = 0;
      while (h.length > AR.undo.length) h.shift();
    };
    arUndo = function () {
      var had = AR.undo.length;
      baseUndo();
      if (had && AR.undo.length < had && AR._edit_opsHist.length) {
        AR._edit_opsRedo.push(AR._edit_opsHist.pop());
      }
    };
    arRedo = function () {
      var had = AR.undo.length;
      baseRedo();
      if (AR.undo.length > had) {
        AR._edit_opsHist.push(AR._edit_opsRedo.pop() || {t: Date.now(), label: 'redone edit'});
      }
    };
    arNew = function () { AR._edit_opsHist.length = 0; AR._edit_opsRedo.length = 0; return baseNew.apply(null, arguments); };
    arOpen = function () { AR._edit_opsHist.length = 0; AR._edit_opsRedo.length = 0; return baseOpen.apply(null, arguments); };
  });

  /* ── registrations ───────────────────────────────────────────────────── */
  AR_EXT.tools.e_align = {
    assist: 1, act: eoAlign,
    tip: 'Align the selection &mdash; left/right/centerx (X), back/front/centerz (Z), top/bottom (Y) '
       + 'or face (butt against the reference). Reference = the last object selected; '
       + 'args {mode, to:last|first|selection}'
  };
  AR_EXT.tools.e_dist = {
    assist: 1, act: eoDistribute,
    tip: 'Distribute the selection evenly between the two outermost objects &mdash; equal EDGE gaps, '
       + 'the outer two stay put. Needs three or more; args {axis:x|z|auto}'
  };
  AR_EXT.tools.e_history = {
    assist: 1, act: eoHistory,
    tip: 'Undo history as a list &mdash; every snapshot labelled with what changed and when; '
       + 'click a row to jump back to that state (real undos, so Redo still works). Args {back:n}'
  };
  AR_EXT.tools.e_purge = {
    assist: 1, act: eoPurge,
    tip: 'Purge unused &mdash; materials and textures nothing refers to, component definitions with no '
       + 'instance, dead selection sets, empty layers, and openings whose host wall is gone. '
       + 'Args {orphans:true} also deletes the orphan openings'
  };
})();
