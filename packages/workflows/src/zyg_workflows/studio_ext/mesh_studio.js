// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* ── mesh_studio.js ── Mesh Studio: the three bars, the stage, the picker ────
   2026-09-18.

   The tab's markup and CSS are in inspection.html (task 14); the tool list is
   in mesh_studio.py behind GET /inspect/api/studio/mesh/ops (tasks 4+5). This
   file is the only thing that joins them, and it is deliberately the same code
   Creature Studio runs — ctLoadOps / ctToolHtml / ctRailHtml / ctRenderBars /
   ctDockRender / ctBarsApply / ctKnobs, renamed into an `msh` namespace rather
   than shared, for the reason the CSS was cloned: a layout decision tuned for
   one studio's kit must not silently move another's.

   HONESTY, WHICH IS THE WHOLE POINT OF THIS TAB TODAY.
   All 186 registry options are ph:true — not one of them runs. Each is drawn
   with FOUR independent tells so an unbuilt option can never be mistaken for a
   broken one:
     1. dashed border + amber pip   (.msh-tool.ph, from the page's CSS)
     2. ' [placeholder]' at the end of its tooltip
     3. a sheet on click whose first line says it is not built
     4. the knobs in that sheet are live and record into MS.stack — so the
        operator can state what they wanted and copy it out as a recipe, which
        is the only useful thing an unbuilt option can do.

   THE LIVE PARTS, and none of them is a registry op:
     · the picker (#msh-picker) — the old card board, rendered into a modal off
       the same /mesh/api/list, clicking a card OPENS the mesh here
     · the stage — the record's render sheet (2D) and a three.js orbit rig (3D)
       over its mesh3d .bin, or its .glb for a prop
     · the header — name, kind, counts, anthro/licence chip
     · 'Board' in the header — the old tab, whole, in a panel, so nothing it
       offered was lost when it became a picker
     · mshEnter / mshLeave — load once, render, and stop the render loop off-tab

   Bars, and why each family is where it is:
     LEFT   what the mesh IS          Topology Transform Shape Rig Weights UV
                                      Material Texture Fit           (98 icons)
     RIGHT  the session               Library Import Session          (30 icons)
     FOOT   what is DONE to it, four rows
                                      Measure Export Render Pipeline View (58) */

(function () {
  'use strict';
  if (typeof esc !== 'function' || typeof withScope !== 'function') return;

  /* ── state ────────────────────────────────────────────────────────────── */
  var MS = window.MS = {
    ops: null, byId: {}, sections: [],   // the registry
    stack: [], sel: -1,                  // what the operator asked for (nothing runs)
    rec: null, name: '', idx: -1,        // the open mesh
    view: 0, mode: '3d', wire: true,     // the stage
    bars: true, dock: true, panel: '',
    pickSel: -1, toastT: 0, entered: false
  };
  try {
    MS.bars = localStorage.getItem('msh.bars') !== '0';
    MS.dock = localStorage.getItem('msh.dock') !== '0';
  } catch (e) {}

  function el(id) { return document.getElementById(id); }

  function mshToast(msg, warn) {
    var t = el('msh-toast'); if (!t) return;
    t.textContent = msg; t.classList.toggle('warn', !!warn); t.style.display = 'block';
    clearTimeout(MS.toastT);
    MS.toastT = setTimeout(function () { t.style.display = 'none'; }, 5200);
  }
  function mshIcon(o) {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"'
      + ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (o.svg || '') + '</svg>';
  }

  /* ── the registry ─────────────────────────────────────────────────────── */
  function mshLoadOps() {
    if (MS.ops) return Promise.resolve(MS.ops);
    return fetch('/inspect/api/studio/mesh/ops', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.error) throw new Error(d.error);
        MS.ops = d; MS.sections = d.sections || []; MS.byId = {};
        MS.sections.forEach(function (s) {
          s.items.forEach(function (o) { MS.byId[o.id] = o; });
        });
        mshRenderBars();
        return d;
      })
      .catch(function (e) {
        ['msh-tools', 'msh-left'].forEach(function (id) {
          var h = el(id);
          if (h) h.innerHTML = '<div class="crst-note warn">Toolbox unavailable — '
            + esc(e.message || String(e)) + '</div>';
        });
      });
  }

  /* Which bar a family is DRAWN on. The registry's `bar` says which FAMILY an
     op belongs to — 'side' is the mesh, 'dock' is the session — and these two
     objects are the only place that turns a family into an edge. Flip a value
     and the bars move, with nothing else to keep in step; mesh_studio.py stays
     the only place a tool is declared. */
  var MSH_PLACE = { side: 'left', dock: 'rail' };
  /* …and where a SECTION overrides its family. The cut is by question, not by
     family: Library/Import answer "which mesh am I working on", which is the
     session's question, so they sit on the right with Session. Measure/Export/
     Render/Pipeline/View answer "what is done to it" and go to the foot, where
     four rows of 44px cells cost no stage height. Leaving all 128 'side' ops on
     the left rail would be 19 rows of scroll with the foot half empty. */
  var MSH_PLACE_SEC = {
    Library: 'rail', Import: 'rail',
    Export: 'bar', Render: 'bar', Pipeline: 'bar', View: 'bar', Measure: 'bar'
  };
  function mshPlaceOf(s) { return MSH_PLACE_SEC[s.sec] || MSH_PLACE[s.bar] || 'bar'; }
  /* REGISTRY ORDER, unsorted — unlike Creature Studio, which draws a visiting
     section after the bar's own family. Here the registry's order already reads
     correctly on every edge (Library → Import → Session on the right; Measure →
     Export → Render → Pipeline → View along the foot), so re-sorting by family
     would only move Session above the two sections that say which mesh you are
     on. Section order is therefore a property of mesh_studio_ops/'s filenames,
     which is where it belongs. */
  function mshGroups(place) {
    return (MS.sections || []).filter(function (s) { return mshPlaceOf(s) === place; });
  }

  function mshCount(id) {
    var n = 0; for (var i = 0; i < MS.stack.length; i++) if (MS.stack[i].op === id) n++;
    return n;
  }
  function mshToolHtml(o) {
    var n = mshCount(o.id);
    /* every tip in the registry opens with its own label, so prefixing it again
       gave "Decimate — Decimate — reduce the triangle count" */
    var tip = (o.tip.indexOf(o.lb) === 0 ? o.tip : o.lb + ' — ' + o.tip)
      + (o.ph ? '  [placeholder: declared, not built — clicking opens a sheet that says so]' : '');
    return '<div class="msh-tool' + (o.ph ? ' ph' : '') + (o.needs === 'gpu' ? ' gen' : '') + '"'
      + ' data-msh="' + o.id + '" role="button" onclick="mshTool(\'' + o.id + '\')"'
      + ' title="' + esc(tip) + '">'
      + mshIcon(o) + '<span class="lb">' + esc(o.lb) + '</span>'
      + (n ? '<span class="ct">' + n + '</span>' : '') + '</div>';
  }
  function mshRailHtml(place) {
    return mshGroups(place).map(function (s) {
      return '<div class="msh-grp">' + esc(s.sec) + '</div>' + s.items.map(mshToolHtml).join('');
    }).join('');
  }
  function mshRenderBars() {
    if (!MS.ops) return;
    var host = el('msh-tools'); if (host) host.innerHTML = mshRailHtml('rail');
    var left = el('msh-left'); if (left) left.innerHTML = mshRailHtml('left');
    var rn = 0, ln = 0;
    mshGroups('rail').forEach(function (s) { rn += s.items.length; });
    mshGroups('left').forEach(function (s) { ln += s.items.length; });
    var c = el('msh-toolcount'); if (c) c.textContent = rn + ' session';
    var lc = el('msh-leftcount'); if (lc) lc.textContent = ln + ' body tools';
    var tc = el('msh-count');
    if (tc) tc.textContent = MS.ops.counts.total + ' options · '
      + MS.ops.counts.built + ' built · ' + MS.ops.counts.placeholder + ' placeholders';
    mshDockRender(); mshBarsApply();
  }
  /* the foot is the same registry read along the bottom: same ids, same
     handler, rendered from mshRenderBars() so there is no second truth. Each
     group is a BLOCK — caption on top, its icons in FOUR rows under it. */
  function mshDockRender() {
    var host = el('msh-dock'); if (!host || !MS.ops) return;
    host.innerHTML = '<div class="msh-bargrid">'
      + mshGroups('bar').map(function (s) {
          return '<div class="msh-bgrp"><div class="msh-bsec">' + esc(s.sec) + '</div>'
               + '<div class="msh-bgrid">' + s.items.map(mshToolHtml).join('') + '</div></div>';
        }).join('') + '</div>';
    mshBarWheel();
  }
  /* a mouse wheel does nothing to a horizontally-scrolling box by default, so
     anything past the right edge of the foot would look like it is not there */
  function mshBarWheel() {
    var bar = el('msh-dock'); if (!bar || bar._wheel) return; bar._wheel = 1;
    bar.addEventListener('wheel', function (e) {
      if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;
      bar.scrollLeft += e.deltaY; e.preventDefault();
    }, { passive: false });
  }
  function mshFlash(id) {
    Array.prototype.forEach.call(document.querySelectorAll('.msh-tool[data-msh="' + id + '"]'),
      function (x) {
        x.classList.add('flash');
        setTimeout(function () { x.classList.remove('flash'); }, 420);
      });
  }

  /* ── the two switches ─────────────────────────────────────────────────── */
  function mshBarsApply() {
    var col = el('msh-toolcol'), a = el('msh-arrow'), lcol = el('msh-leftcol');
    if (col) col.classList.toggle('hid', !MS.bars);
    /* the left column carries no switch of its own — it folds with the other
       two, from the one arrow, or it could be hidden with no way back */
    if (lcol) lcol.classList.toggle('hid', !MS.bars);
    if (a) {
      a.innerHTML = MS.bars ? '&#9654;' : '&#9664;';
      a.classList.toggle('on', !MS.bars);
      a.setAttribute('aria-expanded', MS.bars ? 'true' : 'false');
    }
    mshDockApply();
  }
  function mshDockApply() {
    var d = el('msh-dock'), g = el('msh-grip'); if (!d || !g) return;
    d.classList.toggle('off', !MS.dock || !MS.bars);
    g.classList.toggle('on', MS.dock);
    g.innerHTML = MS.dock ? '&#9662;' : '&#9652;';
    g.setAttribute('aria-expanded', MS.dock ? 'true' : 'false');
  }

  /* ── the sheet ────────────────────────────────────────────────────────── */
  var PH_BANNER =
    '<div class="crst-note warn" style="border:1px dashed var(--warn);border-radius:8px;'
    + 'padding:8px 10px;margin-bottom:11px">'
    + '<b>Not built yet</b> — this option is a placeholder. The knobs below record what you '
    + 'asked for and <b>nothing runs</b>. Copy the stack as a recipe if you want the request '
    + 'to survive this page.</div>';

  function mshPanelOpen(kind, arg) {
    MS.panel = kind; MS.panelArg = arg || {};
    var p = el('msh-panel'), bd = el('msh-panel-bd'),
        ti = el('msh-panel-title'), ico = el('msh-panel-ico');
    if (!p || !bd) return;
    p.classList.add('on');
    /* the old board is a three-lane grid; 430px would put one card per row */
    p.style.width = (kind === 'board') ? 'min(920px, 78vw)' : '';
    if (kind === 'board') { ti.textContent = 'Mesh board'; if (ico) ico.innerHTML = '';
                            mshPanelBoard(bd); return; }
    if (kind === 'stack') { ti.textContent = 'Recipe — ' + MS.stack.length + ' asked for';
                            if (ico) ico.innerHTML = ''; mshPanelStack(bd); return; }
    var o = MS.byId[MS.panelArg.op]; if (!o) { mshPanelClose(); return; }
    ti.textContent = o.lb + ' · ' + o.sec;
    if (ico) ico.innerHTML = mshIcon(o);
    mshPanelOp(bd, MS.panelArg.i);
  }
  function mshPanelOp(bd, i) {
    var r = MS.stack[i], o = MS.byId[r.op];
    var h = (o.ph ? PH_BANNER : '')
      + '<div class="crst-h"><span>' + esc(o.lb) + '</span><span class="sp"></span>'
      + '<span class="sc">' + esc(o.sec) + (o.needs ? ' · needs ' + esc(o.needs) : '') + '</span></div>'
      + '<div class="crst-note">' + esc(o.tip) + '</div>'
      + mshKnobs(i)
      + '<div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">'
      + '<button class="crst-btn pri" onclick="mshRecipeCopy()">Copy as recipe</button>'
      + '<button class="crst-btn" onclick="mshPanelOpen(\'stack\')">Recipe ('
      + MS.stack.length + ')</button>'
      + '<button class="crst-btn" onclick="mshDrop(' + i + ')">Remove</button></div>';
    bd.innerHTML = h;
  }
  function mshPanelStack(bd) {
    var h = '<div class="crst-h"><span>What you have asked for</span>'
      + '<span class="n">' + MS.stack.length + '</span></div>';
    if (!MS.stack.length) {
      h += '<div class="crst-note">Nothing yet. Click any option in any of the three bars. '
        + 'Every one of them is a placeholder, so what you build here is a written request, '
        + 'not a result.</div>';
    } else {
      h += MS.stack.map(function (r, i) {
        var o = MS.byId[r.op] || { lb: r.op, svg: '', sec: '' };
        return '<div class="msh-row' + (i === MS.sel ? ' sel' : '') + '"'
          + ' onclick="mshSelect(' + i + ')">'
          + '<span class="ix">' + (i + 1) + '</span>' + mshIcon(o)
          + '<span class="nm">' + esc(o.lb) + '</span>'
          + '<span style="flex:1"></span>'
          + '<span class="sc">' + esc(o.sec) + '</span></div>';
      }).join('');
      if (MS.sel >= 0 && MS.stack[MS.sel]) h += mshKnobs(MS.sel);
    }
    h += '<div style="display:flex;gap:8px;margin-top:12px">'
      + '<button class="crst-btn pri" onclick="mshRecipeCopy()">Copy as recipe</button>'
      + '<button class="crst-btn" onclick="mshStackClear()">Clear</button></div>';
    bd.innerHTML = h;
  }
  /* the ctKnobs idiom, on the identical param shape mesh_studio.py ships
     (k/lb/t/df/mn/mx/st/opts) — which is why no new widget code was needed */
  function mshKnobs(i) {
    var r = MS.stack[i], o = MS.byId[r.op]; if (!o) return '';
    if (!(o.params || []).length)
      return '<div class="crst-note">No knobs — it is on or it is not.</div>';
    var h = '';
    (o.params || []).forEach(function (q) {
      var v = r.p[q.k], id = 'mshk-' + i + '-' + q.k;
      h += '<div class="msh-knob"><span class="kl" title="' + esc(q.tip || '') + '">'
        + esc(q.lb) + '</span>';
      if (q.t === 'f' || q.t === 'i') {
        h += '<input type="range" min="' + q.mn + '" max="' + q.mx + '" step="' + (q.st || 1) + '"'
          + ' value="' + v + '" oninput="mshSet(' + i + ',\'' + q.k + '\',this.value,1)">'
          + '<input type="number" id="' + id + '" min="' + q.mn + '" max="' + q.mx + '"'
          + ' step="' + (q.st || 1) + '" value="' + v + '"'
          + ' onchange="mshSet(' + i + ',\'' + q.k + '\',this.value)">';
      } else if (q.t === 'b') {
        h += '<input type="checkbox"' + (v ? ' checked' : '')
          + ' onchange="mshSet(' + i + ',\'' + q.k + '\',this.checked)">';
      } else if (q.t === 'e') {
        h += '<select onchange="mshSet(' + i + ',\'' + q.k + '\',this.value)">'
          + (q.opts || []).map(function (x) {
              return '<option' + (x === v ? ' selected' : '') + '>' + esc(x) + '</option>';
            }).join('') + '</select>';
      } else if (q.t === 'c') {
        h += '<input type="color" value="' + esc(v) + '"'
          + ' onchange="mshSet(' + i + ',\'' + q.k + '\',this.value)">';
      } else {
        h += '<input type="text" class="wide" value="' + esc(v == null ? '' : v) + '"'
          + ' placeholder="' + esc(q.tip || '') + '"'
          + ' onchange="mshSet(' + i + ',\'' + q.k + '\',this.value)">';
      }
      h += '</div>';
    });
    return h;
  }

  /* ── clicking an option ───────────────────────────────────────────────── */
  function mshTool(id) {
    var o = MS.byId[id]; if (!o) return;
    mshFlash(id);
    if (id === 'ss_help') { mshHelp(); return; }
    var p = {};
    (o.params || []).forEach(function (q) { p[q.k] = q.df; });
    MS.stack.push({ op: id, p: p });
    MS.sel = MS.stack.length - 1;
    mshRenderBars();
    mshPanelOpen('op', { op: id, i: MS.sel });
  }
  function mshSelect(i) { MS.sel = i; mshPanelOpen('stack'); }
  function mshSet(i, k, v, live) {
    var r = MS.stack[i]; if (!r) return;
    if (typeof v === 'string' && v !== '' && !isNaN(v) && typeof r.p[k] === 'number') v = parseFloat(v);
    r.p[k] = v;
    var o = MS.byId[r.op], q = (o.params || []).filter(function (x) { return x.k === k; })[0];
    if (q && (q.t === 'f' || q.t === 'i') && live) {
      var n = el('mshk-' + i + '-' + k); if (n) n.value = v;
    }
  }
  function mshDrop(i) {
    MS.stack.splice(i, 1);
    MS.sel = Math.min(MS.sel, MS.stack.length - 1);
    mshRenderBars(); mshPanelOpen('stack');
  }
  function mshStackClear() { MS.stack = []; MS.sel = -1; mshRenderBars(); mshPanelOpen('stack'); }
  function mshPanelClose() {
    if (MS.panel === 'board') mshBoardHome();
    MS.panel = '';
    var p = el('msh-panel'); if (p) { p.classList.remove('on'); p.style.width = ''; }
  }

  function mshRecipe() {
    return {
      studio: 'mesh', built: 0,
      note: 'Every entry is a PLACEHOLDER — nothing in this recipe has run or can run yet.',
      mesh: MS.rec ? { name: MS.name, kind: (MS.rec.params || {}).kind || MS.rec.kind || '',
                       sha256: MS.rec.sha256 || '' } : null,
      asked: MS.stack.map(function (r) {
        var o = MS.byId[r.op] || {};
        return { op: r.op, label: o.lb || r.op, section: o.sec || '', params: r.p, built: false };
      })
    };
  }
  function mshRecipeCopy() {
    var txt = JSON.stringify(mshRecipe(), null, 2);
    var done = function () { mshToast('Recipe on the clipboard — ' + MS.stack.length + ' option(s), none of them built.'); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(txt).then(done, function () { mshCopyFallback(txt, done); });
    } else { mshCopyFallback(txt, done); }
  }
  function mshCopyFallback(txt, done) {
    var t = document.createElement('textarea');
    t.value = txt; t.style.cssText = 'position:fixed;left:-9999px;top:0';
    document.body.appendChild(t); t.select();
    var ok = false; try { ok = document.execCommand('copy'); } catch (e) {}
    document.body.removeChild(t);
    if (ok) done(); else mshToast('Could not reach the clipboard.', true);
  }

  /* ── the help sheet ───────────────────────────────────────────────────── */
  function mshHelp() {
    var c = (MS.ops && MS.ops.counts) || { total: 0, built: 0, placeholder: 0 };
    var ln = 0, rn = 0, bn = 0;
    mshGroups('left').forEach(function (s) { ln += s.items.length; });
    mshGroups('rail').forEach(function (s) { rn += s.items.length; });
    mshGroups('bar').forEach(function (s) { bn += s.items.length; });
    alert('MESH STUDIO\n\n'
      + 'The tab was a scrolling board of skeleton cards. It is a studio now, on\n'
      + 'Creature Studio\u2019s shape \u2014 three bars around a stage \u2014 because a mesh is\n'
      + 'something you OPEN and work on, not a list you read. The board itself is\n'
      + 'not gone: it is the picker, and the whole of it is still one click away\n'
      + 'under \u201cBoard\u201d in the header.\n\n'
      + 'THREE BARS, cut by question:\n'
      + '  LEFT   what the MESH IS \u2014 topology, transform, shape, rig, weights,\n'
      + '         UV, material, texture, fit (' + ln + ' options)\n'
      + '  RIGHT  the SESSION \u2014 which mesh you are on: library, import, and the\n'
      + '         session itself (' + rn + ' options)\n'
      + '  FOOT   what is DONE to it \u2014 measure, export, render, pipeline, view\n'
      + '         (' + bn + ' options, four rows)\n\n'
      + 'WHAT IS BUILT: ' + c.built + ' of ' + c.total + ' listed options are live \u2014 every one is a\n'
      + 'placeholder: dashed, amber pip, [placeholder] in the tooltip, and a sheet\n'
      + 'on click that says so. They are listed because a complete, honest list of\n'
      + 'what a mesh studio needs is worth more than five working knobs \u2014 but only\n'
      + 'if you can never mistake an unbuilt option for a broken one.\n\n'
      + 'WHAT DOES WORK, and none of it is one of those options:\n'
      + '  \u00b7 Open mesh \u2014 the old card board as a picker: originals, derived\n'
      + '    bodies, props and creatures, all from one place\n'
      + '  \u00b7 the stage \u2014 the mesh\u2019s issued render sheet, and a real orbit rig\n'
      + '    over its geometry (drag to turn, wheel to zoom at the pointer,\n'
      + '    right-click to set the centre it turns around)\n'
      + '  \u00b7 the header \u2014 name, kind, vertex/triangle counts, and the anthro\n'
      + '    gate verdict or the licence chip, whichever the record answers to\n'
      + '  \u00b7 Board \u2014 the old tab whole: lanes, integrity line, GNM head fits\n\n'
      + 'THE KNOBS ARE REAL EVEN THOUGH THE OPTIONS ARE NOT. Clicking an option\n'
      + 'opens its parameters and records them in a stack; \u201cCopy as recipe\u201d puts\n'
      + 'that stack on the clipboard as JSON, each entry marked built:false. That\n'
      + 'is the one useful thing an unbuilt option can do \u2014 let you state exactly\n'
      + 'what you wanted of it.');
  }

  /* ── the header ───────────────────────────────────────────────────────── */
  function mshCounts(rec) {
    if (typeof isProp === 'function' && isProp(rec)) {
      var g = rec.geometry || {};
      return (g.vertices || 0).toLocaleString() + ' verts / '
           + (g.triangles || 0).toLocaleString() + ' tris'
           + (g.parts ? ' · ' + g.parts + ' parts' : '');
    }
    var p = rec.params || {}, m = p.measured || {}, m3 = p.measured_mesh3d || {};
    var s = 'cage ' + ((m.vertices || 0).toLocaleString()) + ' verts';
    if (m3.vertices) s += ' · display ' + m3.vertices.toLocaleString();
    if (m.height_m) s = m.height_m.toFixed(3) + ' m · ' + s;
    return s;
  }
  function mshHeader() {
    var n = el('msh-cname'), s = el('msh-csub');
    if (!n || !s) return;
    if (!MS.rec) {
      n.textContent = 'Mesh Studio';
      s.innerHTML = 'No mesh open.';
      return;
    }
    var rec = MS.rec, p = rec.params || {};
    var kind = p.kind || rec.kind || (rec.root === 'props' ? 'prop' : 'mesh');
    var chip = (rec.licence && rec.licence.id)
      ? meshLicChip(rec)
      : (typeof anthroChip === 'function' ? anthroChip(rec) : '');
    n.textContent = MS.name;
    s.innerHTML = esc(String(kind).toLowerCase()) + ' &middot; ' + mshCounts(rec)
      + ' &middot; ' + chip;
  }

  /* ── the stage ────────────────────────────────────────────────────────── */
  function mshStageRender() {
    var st = el('msh-stage'), h3 = el('msh-3d'), empty = el('msh-empty'), hint = el('msh-hint');
    if (!st) return;
    if (!MS.rec) {
      st.innerHTML = '';
      if (h3) h3.style.display = 'none';
      if (empty) empty.style.display = 'flex';
      if (hint) hint.textContent = '';
      msh3dStop();
      return;
    }
    if (empty) empty.style.display = 'none';
    /* the 2D sheet is drawn whether or not the 3D is on top of it: it is
       instant, and it is what the operator sees while 33 MB of geometry is
       still on the wire. */
    var pv = MS.rec.previews || [];
    var src = (typeof meshThumbSrc === 'function') ? meshThumbSrc(MS.rec, MS.view) : '';
    st.innerHTML = src ? '<img src="' + src + '" alt="">'
                       : '<div class="crst-note">No render sheet for this mesh.</div>';
    if (MS.mode === '3d' && mshGeomSrc(MS.rec)) {
      if (h3) h3.style.display = 'block';
      msh3dShow();
      if (hint) hint.textContent = 'drag to turn · wheel to zoom at the pointer · right-click = centre · '
        + pv.length + ' sheet view(s) behind the 3D';
    } else {
      if (h3) h3.style.display = 'none';
      msh3dStop();
      if (hint) hint.textContent = pv.length
        ? ('view ' + (MS.view + 1) + ' of ' + pv.length) : '';
    }
  }
  function mshSetMode(m) { MS.mode = m; mshStageRender(); }
  function mshStep(d) {
    var pv = (MS.rec && MS.rec.previews) || [];
    if (!pv.length) return;
    MS.view = (MS.view + d + pv.length) % pv.length;
    MS.mode = '2d'; mshStageRender();
  }

  /* what geometry this record has, and in which form. A prop registered with a
     .glb gets the .glb (it carries its materials); everything else gets the
     ZM3D .bin, which is the form every record in the registry has. */
  function mshGeomSrc(rec) {
    if (!rec) return null;
    var root = (rec.root === 'props') ? '&root=props' : '';
    var ver = (typeof meshVer === 'function') ? meshVer(rec) : '';
    if (rec.root === 'props' && rec.glb && rec.dir)
      return { kind: 'glb',
               url: withScope('/mesh/img?p=' + encodeURIComponent(rec.dir + '/' + rec.glb)
                              + '&v=' + ver + root) };
    if (rec.mesh3d && /\.bin$/.test(rec.mesh3d))
      return { kind: 'bin',
               url: withScope('/mesh/img?p=' + encodeURIComponent(rec.mesh3d)
                              + '&v=' + ver + root) };
    return null;
  }

  /* ── the orbit rig ────────────────────────────────────────────────────────
     Its own renderer in #msh-3d, not MV3's: MV3 is bound to #mv-3d inside the
     old full-screen viewer, and two rigs sharing one WebGL context is how you
     get a black stage the moment the other tab is opened. The geometry path is
     the page's own — mv3dParseBin() is called, not re-implemented. */
  var M3 = window.MSH3 = {
    renderer: null, scene: null, camera: null, controls: null,
    mesh: null, lines: null, model: null, raf: 0, loadedKey: '', loading: '', cache: {}
  };
  function msh3dEnsure() {
    if (M3.renderer) return true;
    if (typeof THREE === 'undefined' || !THREE.WebGLRenderer) return false;
    var host = el('msh-3d'); if (!host) return false;
    /* #msh-3d has no CSS rule of its own, so its height is 0 and the renderer
       would be sized 0x0 — give it the absolute box its sibling stage has */
    host.style.cssText = 'position:absolute;inset:0;background:#0a0c10;display:block';
    M3.renderer = new THREE.WebGLRenderer({ antialias: true });
    M3.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    host.appendChild(M3.renderer.domElement);
    M3.scene = new THREE.Scene();
    M3.scene.background = new THREE.Color(0x0a0c10);
    M3.camera = new THREE.PerspectiveCamera(32, 1, 0.01, 60);
    M3.camera.up.set(0, 0, 1);
    M3.controls = new THREE.OrbitControls(M3.camera, M3.renderer.domElement);
    M3.controls.enableDamping = true; M3.controls.dampingFactor = 0.08;
    /* 2026-09-20: the page's shared rig extras (zyg3dInstall, beside cs3dWheel
       in inspection.html): wheel = zoom toward the pointer (the hint below
       promised this; OrbitControls' own dolly kept the centre fixed), and a
       right-click sets the orbit centre, as in the Character Studio. */
    if (window.zyg3dInstall) zyg3dInstall(M3, { wheel: true });
    M3.scene.add(new THREE.HemisphereLight(0xdde4ee, 0x30353d, 0.35));
    /* key + fill ride WITH the camera so every orbit angle is lit — world-fixed
       lights leave the far side of a body unreadably dark */
    var d1 = new THREE.DirectionalLight(0xffffff, 1.0); d1.position.set(0.85, 0.3, 0.3);
    var d2 = new THREE.DirectionalLight(0x9fb4cc, 0.3); d2.position.set(-0.7, -0.2, 0.1);
    M3.camera.add(d1); M3.camera.add(d2); M3.scene.add(M3.camera);
    window.addEventListener('resize', msh3dSize);
    return true;
  }
  function msh3dSize() {
    if (!M3.renderer) return;
    var host = el('msh-3d'); if (!host) return;
    var w = host.clientWidth || 800, h = host.clientHeight || 600;
    M3.renderer.setSize(w, h);
    M3.camera.aspect = w / h; M3.camera.updateProjectionMatrix();
  }
  function msh3dMsg(t) {
    var host = el('msh-3d'); if (!host) return;
    var m = host.querySelector('.mv3d-msg');
    if (!t) { if (m) m.parentNode.removeChild(m); return; }
    if (!m) { m = document.createElement('div'); m.className = 'mv3d-msg'; host.appendChild(m); }
    m.textContent = t;
  }
  function msh3dKey(rec) {
    return MS.name + '@' + (rec.visuals_updated || (rec.params || {}).built || rec.sha256 || '');
  }
  function msh3dShow() {
    if (!msh3dEnsure()) { msh3dMsg('three.js unavailable'); return; }
    msh3dSize();
    var rec = MS.rec, src = mshGeomSrc(rec); if (!src) return;
    var key = msh3dKey(rec);
    if (M3.loadedKey === key) { msh3dLoop(); return; }
    if (M3.cache[key]) { msh3dBuildBin(key, M3.cache[key]); msh3dLoop(); return; }
    if (M3.loading === key) return;
    M3.loading = key; msh3dMsg('loading geometry…');
    if (src.kind === 'glb') { msh3dLoadGlb(key, src.url); return; }
    fetch(src.url)
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.arrayBuffer(); })
      .then(function (buf) { return mv3dParseBin(buf); })
      .then(function (d) {
        M3.cache = {}; M3.cache[key] = d;          /* one mesh at a time: 33 MB each */
        M3.loading = ''; msh3dMsg('');
        if (MS.rec && msh3dKey(MS.rec) === key) { msh3dBuildBin(key, d); msh3dLoop(); }
      })
      .catch(function (e) {
        M3.loading = ''; msh3dMsg('geometry load failed: ' + (e.message || e));
      });
  }
  function msh3dLoadGlb(key, url) {
    if (!THREE.GLTFLoader) { M3.loading = ''; msh3dMsg('GLTFLoader unavailable'); return; }
    new THREE.GLTFLoader().load(url, function (g) {
      M3.loading = ''; msh3dMsg('');
      if (!MS.rec || msh3dKey(MS.rec) !== key) return;
      msh3dClear();
      M3.model = g.scene;
      M3.scene.add(M3.model);
      msh3dFrame(new THREE.Box3().setFromObject(M3.model));
      M3.loadedKey = key; msh3dLoop();
    }, null, function (e) {
      M3.loading = ''; msh3dMsg('GLB load failed: ' + (e && (e.message || e.type) || e));
    });
  }
  function msh3dClear() {
    ['mesh', 'lines'].forEach(function (k) {
      if (M3[k]) {
        M3.scene.remove(M3[k]);
        if (M3[k].geometry) M3[k].geometry.dispose();
        if (M3[k].material) M3[k].material.dispose();
        M3[k] = null;
      }
    });
    if (M3.model) { M3.scene.remove(M3.model); M3.model = null; }
  }
  function msh3dBuildBin(key, d) {
    msh3dClear();
    var pos = (d.v instanceof Float32Array) ? d.v : new Float32Array(d.v);
    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setIndex(new THREE.BufferAttribute(
      (d.tri instanceof Uint32Array) ? d.tri : new Uint32Array(d.tri), 1));
    g.computeVertexNormals();
    M3.mesh = new THREE.Mesh(g, new THREE.MeshStandardMaterial({
      color: 0xcdc8c0, roughness: 0.85, metalness: 0.0,
      polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 }));
    M3.scene.add(M3.mesh);
    if (d.edge && d.edge.length) {
      var ge = new THREE.BufferGeometry();
      ge.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      ge.setIndex(new THREE.BufferAttribute(
        (d.edge instanceof Uint32Array) ? d.edge : new Uint32Array(d.edge), 1));
      /* the TRUE quad edges the exporter wrote, not triangulation diagonals —
         opaque, because blending washes the line into the clay under it */
      M3.lines = new THREE.LineSegments(ge, new THREE.LineBasicMaterial({ color: 0x29e0dc }));
      M3.lines.visible = MS.wire;
      M3.scene.add(M3.lines);
    }
    g.computeBoundingBox();
    msh3dFrame(g.boundingBox);
    M3.loadedKey = key;
  }
  function msh3dFrame(bb) {
    var c = new THREE.Vector3(); bb.getCenter(c);
    var h = Math.max(bb.max.z - bb.min.z, 1e-4);
    M3.camera.position.set(c.x, c.y - 2.1 * h, c.z + 0.12 * h);
    M3.camera.near = h / 100; M3.camera.far = h * 40;
    M3.camera.updateProjectionMatrix();
    M3.controls.minDistance = h * 0.03;
    M3.controls.maxDistance = h * 8;
    M3.controls.target.copy(c);
    M3.controls.update();
  }
  function msh3dWire() {
    MS.wire = !MS.wire;
    if (M3.lines) M3.lines.visible = MS.wire;
    mshToast(MS.wire ? 'Quad grid on.' : 'Quad grid off.');
  }
  function msh3dLoop() {
    if (M3.raf || !M3.renderer) return;
    (function tick() {
      M3.raf = requestAnimationFrame(tick);
      M3.controls.update();
      M3.renderer.render(M3.scene, M3.camera);
    })();
  }
  function msh3dStop() { if (M3.raf) { cancelAnimationFrame(M3.raf); M3.raf = 0; } }

  /* ── the picker: the old board, in a modal ────────────────────────────── */
  function mshOpenPicker() {
    var m = el('msh-picker'); if (!m) return;
    m.classList.add('on');
    var q = el('msh-iq'); if (q) q.value = '';
    MS.pickSel = -1;
    mshPickerSel();
    if (typeof MESH_SEQ !== 'undefined' && MESH_SEQ.length) { mshPickerRender(); return; }
    /* the board fills MESH_SEQ, and meshCardHtml reads it by index — so the
       picker waits for the page's own load rather than keeping a second list */
    el('msh-iboard').innerHTML = '<div style="color:var(--muted);font-size:.8rem">Loading&hellip;</div>';
    if (typeof loadMesh === 'function') loadMesh();
    var tries = 0;
    (function poll() {
      if (typeof MESH_SEQ !== 'undefined' && MESH_SEQ.length) { mshPickerRender(); return; }
      if (++tries > 40) {
        el('msh-iboard').innerHTML =
          '<div style="color:var(--bad);font-size:.8rem">Could not load the mesh registry.</div>';
        return;
      }
      setTimeout(poll, 150);
    })();
  }
  function mshPickerClose() {
    var m = el('msh-picker'); if (m) m.classList.remove('on');
  }
  function mshPickerRender() {
    var board = el('msh-iboard'); if (!board) return;
    if (typeof MESH_SEQ === 'undefined' || !MESH_SEQ.length) return;
    var qe = el('msh-iq'), q = (qe && qe.value || '').toLowerCase();
    var keep = {};
    MESH_SEQ.forEach(function (it, i) {
      if (!q || String(it.name).toLowerCase().indexOf(q) >= 0) keep[i] = 1;
    });
    var lanes = { orig: [], male: [], female: [], props: [] };
    MESH_SEQ.forEach(function (it, i) {
      if (!keep[i]) return;
      if (it.isOriginal) lanes.orig.push(i);
      else if (it.rec.root === 'props') lanes.props.push(i);
      else if (((it.rec.params || {}).base === 'female')) lanes.female.push(i);
      else lanes.male.push(i);
    });
    var n = Object.keys(keep).length;
    var c = el('msh-icount'); if (c) c.textContent = n;
    board.innerHTML = n ? ('<div class="mesh-board">'
      + meshLaneHtml('ORIGINALS', 'immutable templates &mdash; hash-verified', lanes.orig,
                     'No originals.')
      + meshLaneHtml('MALE BASE', 'characters derived from the male original', lanes.male)
      + meshLaneHtml('FEMALE BASE', 'characters derived from the female original', lanes.female)
      + meshLaneHtml('PROPS &amp; CREATURES', 'built geometry &mdash; licence on the card',
                     lanes.props, 'Nothing registered yet.')
      + '</div>')
      : '<div style="color:var(--muted);font-size:.8rem">No mesh matches that filter.</div>';
    /* meshCardHtml writes onclick="mvOpen(i)" — the full-screen viewer, which is
       the one thing this picker must NOT do. The index is read back off that
       attribute and the handler replaced, so the card markup stays shared. */
    Array.prototype.forEach.call(board.querySelectorAll('.mesh-card'), function (card) {
      var m = /mvOpen\((\d+)\)/.exec(card.getAttribute('onclick') || '');
      if (!m) return;
      var i = +m[1];
      card.setAttribute('onclick', '');
      card.onclick = function (ev) { ev.stopPropagation(); mshPickerPick(i, card); };
      if (i === MS.pickSel) card.style.outline = '2px solid var(--acc)';
    });
  }
  function mshPickerPick(i, card) {
    MS.pickSel = i;
    Array.prototype.forEach.call(document.querySelectorAll('#msh-iboard .mesh-card'),
      function (c) { c.style.outline = ''; });
    if (card) card.style.outline = '2px solid var(--acc)';
    mshPickerSel();
  }
  function mshPickerSel() {
    var s = el('msh-isel'), go = el('msh-igo');
    var it = (MS.pickSel >= 0 && typeof MESH_SEQ !== 'undefined') ? MESH_SEQ[MS.pickSel] : null;
    if (s) s.textContent = it ? it.name : 'No mesh selected.';
    if (go) go.disabled = !it;
  }
  function mshPickerApply() {
    if (MS.pickSel < 0) return;
    var it = MESH_SEQ[MS.pickSel]; if (!it) return;
    mshPickerClose();
    mshOpen(MS.pickSel);
  }
  function mshOpen(i) {
    var it = MESH_SEQ[i]; if (!it) return;
    MS.idx = i; MS.rec = it.rec; MS.name = it.name; MS.view = 0;
    MS.mode = mshGeomSrc(it.rec) ? '3d' : '2d';
    M3.loadedKey = '';
    mshHeader(); mshStageRender(); mshRenderBars();
    mshToast('Opened ' + it.name + '. Every option in the three bars is a placeholder — '
      + 'the stage, the picker and the board are what is live.');
  }

  /* ── 'Board': the old tab, whole, in a panel ──────────────────────────── */
  function mshPanelBoard(bd) {
    var lib = el('msh-library');
    if (!lib) { bd.innerHTML = '<div class="crst-note">The board markup is missing.</div>'; return; }
    bd.innerHTML = '<div class="crst-note">The mesh tab as it was before it became a studio — '
      + 'the same lanes, the same integrity line, the same GNM head fits, filled by the same '
      + 'loadMesh(). Nothing it offered was lost when it became a picker.</div>';
    /* the live node is MOVED, not copied: loadMesh() keeps writing into these
       exact ids, and a copy would go stale the moment a derive finished */
    lib.style.display = 'block';
    bd.appendChild(lib);
    if (typeof loadMesh === 'function') loadMesh();
  }
  function mshBoardHome() {
    var lib = el('msh-library'), home = el('view-mesh');
    if (lib && home && lib.parentNode !== home) { lib.style.display = 'none'; home.appendChild(lib); }
    else if (lib) lib.style.display = 'none';
  }
  /* the header button that opens it. Not a registry op and deliberately not one:
     it is this studio's way back to the surface it replaced. */
  function mshHeaderButtons() {
    var top = document.querySelector('#view-mesh .cs-top');
    if (!top || el('msh-boardbtn')) return;
    var mk = function (id, label, title, fn) {
      var b = document.createElement('button');
      b.id = id; b.className = 'crst-btn'; b.textContent = label; b.title = title;
      b.style.marginLeft = '8px';
      b.onclick = fn;
      return b;
    };
    var cnt = el('msh-count');
    var host = cnt && cnt.parentNode ? cnt.parentNode : top;
    var ref = cnt ? cnt.nextSibling : null;
    [ mk('msh-boardbtn', 'Board', 'The old mesh tab, whole: lanes, integrity line, GNM head fits',
         function () { mshPanelOpen('board'); }),
      mk('msh-recbtn', 'Recipe', 'What you have asked the placeholder options for',
         function () { mshPanelOpen('stack'); }),
      mk('msh-3dbtn', '2D / 3D', 'Switch between the issued render sheet and the orbit rig',
         function () { mshSetMode(MS.mode === '3d' ? '2d' : '3d'); }),
      mk('msh-wirebtn', 'Grid', 'Show / hide the quad grid on the 3D mesh', msh3dWire),
      mk('msh-helpbtn', 'Help', 'What this studio is, and what of it is actually built', mshHelp)
    ].forEach(function (b) { host.insertBefore(b, ref); });
  }

  /* ── tab enter / leave ────────────────────────────────────────────────── */
  function mshEnter() {
    mshHeaderButtons();
    mshLoadOps();
    mshHeader();
    mshStageRender();
    if (MS.rec && MS.mode === '3d') msh3dLoop();
    MS.entered = true;
  }
  function mshLeave() { msh3dStop(); }

  /* Esc closes the sheet, then the picker — the same order Creature Studio uses */
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    var v = el('view-mesh');
    if (!v || v.style.display === 'none') return;
    var pick = el('msh-picker');
    if (pick && pick.classList.contains('on')) { mshPickerClose(); return; }
    if (MS.panel) mshPanelClose();
  });

  /* ── publish: the page's stubs are REPLACED, not wrapped ──────────────── */
  window.mshTool = mshTool;
  window.mshSelect = mshSelect;
  window.mshSet = mshSet;
  window.mshDrop = mshDrop;
  window.mshStackClear = mshStackClear;
  window.mshRecipeCopy = mshRecipeCopy;
  window.mshPanelOpen = mshPanelOpen;
  window.mshPanelClose = mshPanelClose;
  window.mshHelp = mshHelp;
  window.mshOpenPicker = mshOpenPicker;
  window.mshPickerClose = mshPickerClose;
  window.mshPickerRender = mshPickerRender;
  window.mshPickerApply = mshPickerApply;
  window.mshOpen = mshOpen;
  window.mshSetMode = mshSetMode;
  window.mshStep = mshStep;
  window.msh3dWire = msh3dWire;
  window.mshEnter = mshEnter;
  window.mshLeave = mshLeave;
  window.mshBarsToggle = function () {
    MS.bars = !MS.bars;
    try { localStorage.setItem('msh.bars', MS.bars ? '1' : '0'); } catch (e) {}
    mshBarsApply();
  };
  window.mshDockToggle = function () {
    MS.dock = !MS.dock;
    try { localStorage.setItem('msh.dock', MS.dock ? '1' : '0'); } catch (e) {}
    mshDockApply();
  };

  /* the bundle loads after switchView() may already have run for #mesh */
  var v = el('view-mesh');
  if (v && v.style.display && v.style.display !== 'none') mshEnter();
})();
