# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GUI script, part 1: tab wiring, the age dropdown, the angle picker and the approval queue.

Moved verbatim out of medusa_server.py (lines 1319-1611); reassembled in html.py.
"""

JS_CORE = """<script>
  // Sidebar footer: the address this page was actually reached on.
  (function(){
    var el = document.getElementById('sidebarHost');
    if (el) el.textContent = location.host;
  })();

  const tabs   = document.querySelectorAll('.tab');
  const panels = document.querySelectorAll('.panel');
  const title  = document.getElementById('contentTitle');

  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const name = tab.dataset.tab;

      tabs.forEach(t => t.classList.toggle('active', t === tab));
      panels.forEach(p => p.classList.toggle('active', p.dataset.panel === name));

      title.innerHTML = '<span class="dot"></span>' + tab.dataset.title;
    });
  });

  // Age dropdown: 18-75, populated here rather than hardcoded as 58 <option>
  // tags inline (same auto-fill convention as every other Character Studio
  // field — blank = let the engine's auto-roll pick it).
  (function(){
    var sel = document.getElementById('m_age');
    if (!sel) return;
    for (var a = 18; a <= 75; a++) {
      var o = document.createElement('option');
      o.value = String(a); o.textContent = String(a);
      sel.appendChild(o);
    }
  })();

  // ── Angle picker ──
  // The catalog is served by the generator itself (:5000 /api/medusa/angles),
  // never hard-coded here: a second copy of the angle list in the front end is
  // a picker that quietly stops matching what the cells actually render.
  var ANG = { angles: [], presets: [], anchorId: 'a1', sel: {}, ready: false };

  function angSelectedIds() {
    return ANG.angles.map(function (a) { return a.id; })
                     .filter(function (id) { return ANG.sel[id]; });
  }

  function angRenderCount() {
    var el = document.getElementById('ang_count');
    if (!el) return;
    if (!ANG.ready) { el.textContent = '—'; return; }
    var ids = angSelectedIds();
    var n = ids.length;
    var forced = n && ids.indexOf(ANG.anchorId) === -1;   // anchor is added server-side
    var total = n + (forced ? 1 : 0);
    if (!n) {
      el.className = 'ang-count warn';
      el.textContent = 'no angles selected — the full 48 will be rendered';
      return;
    }
    el.className = 'ang-count';
    var mins = total * 5;
    el.textContent = total + ' angle' + (total === 1 ? '' : 's') +
      (forced ? ' (incl. the front anchor)' : '') +
      ' · ' + Math.ceil(total / 6) + ' sheet' + (Math.ceil(total / 6) === 1 ? '' : 's') +
      ' · ~' + (mins >= 60 ? (mins / 60).toFixed(1) + ' h' : mins + ' min') + ' of cells';
  }

  function angRenderPresets() {
    var box = document.getElementById('ang_presets');
    if (!box) return;
    var cur = angSelectedIds().join(',');
    box.innerHTML = ANG.presets.map(function (p) {
      var on = p.ids.slice().sort().join(',') === angSelectedIds().slice().sort().join(',');
      return '<button type="button" class="ang-preset' + (on ? ' on' : '') +
             '" data-preset="' + secEsc(p.key) + '">' + secEsc(p.title) + '</button>';
    }).join('') + '<button type="button" class="ang-preset" data-preset="__none">Clear</button>';
    box.querySelectorAll('[data-preset]').forEach(function (b) {
      b.addEventListener('click', function () {
        var key = b.getAttribute('data-preset');
        ANG.sel = {};
        if (key !== '__none') {
          var p = ANG.presets.filter(function (x) { return x.key === key; })[0];
          if (p) p.ids.forEach(function (id) { ANG.sel[id] = true; });
        }
        angSyncBoxes();
        angRenderPresets();
        angRenderCount();
      });
    });
  }

  function angSyncBoxes() {
    document.querySelectorAll('#ang_groups input[data-angle]').forEach(function (cb) {
      cb.checked = !!ANG.sel[cb.getAttribute('data-angle')];
    });
  }

  function angRenderGroups() {
    var box = document.getElementById('ang_groups');
    if (!box) return;
    var order = [], byGroup = {};
    ANG.angles.forEach(function (a) {
      if (!byGroup[a.group]) { byGroup[a.group] = []; order.push(a.group); }
      byGroup[a.group].push(a);
    });
    box.innerHTML = order.map(function (g) {
      var rows = byGroup[g].map(function (a) {
        var isAnchor = a.id === ANG.anchorId;
        return '<label class="ang-cell' + (isAnchor ? ' anchor' : '') + '">' +
                 '<input type="checkbox" data-angle="' + secEsc(a.id) + '">' +
                 '<span class="ang-id">' + secEsc(a.id) + '</span>' +
                 '<span>' + secEsc(a.label) + (isAnchor ? ' — identity anchor, always rendered first' : '') + '</span>' +
               '</label>';
      }).join('');
      return '<div class="ang-group">' +
               '<div class="ang-group-head">' +
                 '<span class="ang-group-name">' + secEsc(g) +
                   '<span>' + byGroup[g].length + ' angles</span></span>' +
                 '<button type="button" class="ang-group-all" data-group="' + secEsc(g) + '">All / none</button>' +
               '</div>' +
               '<div class="ang-cells">' + rows + '</div>' +
             '</div>';
    }).join('');
    box.querySelectorAll('input[data-angle]').forEach(function (cb) {
      cb.addEventListener('change', function () {
        var id = cb.getAttribute('data-angle');
        if (cb.checked) ANG.sel[id] = true; else delete ANG.sel[id];
        angRenderPresets();
        angRenderCount();
      });
    });
    box.querySelectorAll('[data-group]').forEach(function (b) {
      b.addEventListener('click', function () {
        var g = b.getAttribute('data-group');
        var ids = byGroup[g].map(function (a) { return a.id; });
        var allOn = ids.every(function (id) { return ANG.sel[id]; });
        ids.forEach(function (id) { if (allOn) delete ANG.sel[id]; else ANG.sel[id] = true; });
        angSyncBoxes();
        angRenderPresets();
        angRenderCount();
      });
    });
    angSyncBoxes();
  }

  function angLoad() {
    var box = document.getElementById('ang_groups');
    if (!box) return;
    fetch('/api/medusa/angles')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || !d.ok || !d.angles || !d.angles.length) {
          throw new Error((d && d.error) || 'no angle catalog');
        }
        ANG.angles = d.angles;
        ANG.presets = d.presets || [];
        ANG.anchorId = d.anchor_id || 'a1';
        ANG.ready = true;
        var def = ANG.presets.filter(function (p) { return p.key === (d.default_preset || 'extended'); })[0];
        (def ? def.ids : ANG.angles.map(function (a) { return a.id; }))
          .forEach(function (id) { ANG.sel[id] = true; });
        angRenderGroups();
        angRenderPresets();
        angRenderCount();
      })
      .catch(function (err) {
        box.innerHTML = '<div class="ang-err">Angle catalog unavailable (' + secEsc(String(err)) +
                        ') — the run will use the full 48-angle sheet.</div>';
        box.classList.add('open');
        var c = document.getElementById('ang_count');
        if (c) { c.className = 'ang-count warn'; c.textContent = '48 angles (default)'; }
      });
  }

  (function () {
    var t = document.getElementById('ang_toggle');
    if (!t) return;
    t.addEventListener('click', function () {
      var g = document.getElementById('ang_groups');
      var open = g.classList.toggle('open');
      t.textContent = open ? 'Hide angles' : 'Choose angles';
    });
    angLoad();
  })();

  // ── Character Studio → crews approval queue (:5000) ──
  const mBtn = document.getElementById('m_generate');
  if (mBtn) {
    mBtn.addEventListener('click', () => {
      const val = id => { const el = document.getElementById(id); return el ? el.value.trim() : ''; };
      const body = {
        name: val('m_name'),
        age: val('m_age'),
        hair_color: val('m_hair'),
        eye_color: val('m_eyes'),
        skin_tone: val('m_skin'),
        ethnic_heritage: val('m_heritage'),
        char_prompt: val('m_prompt'),
      };
      Object.keys(body).forEach(k => { if (!body[k]) delete body[k]; });
      // Angle plan. Sent as ids in catalog order; the server validates them
      // and falls back to the full 48 when the selection is empty/unusable.
      if (ANG.ready) {
        var angIds = angSelectedIds();
        if (angIds.length) { body.angle_set = 'custom'; body.angle_ids = angIds; }
      }

      const out = document.getElementById('m_result');
      out.className = 'studio-result';
      out.textContent = 'Submitting…';
      mBtn.disabled = true;

      fetch('/api/generate_character', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
        .then(r => r.json().then(d => ({ ok: r.ok, d })))
        .then(({ ok, d }) => {
          mBtn.disabled = false;
          if (ok && d.ok) {
            out.classList.add('good');
            var nSel = ANG.ready ? angSelectedIds().length : 0;
            var nAng = nSel ? (nSel + (angSelectedIds().indexOf(ANG.anchorId) === -1 ? 1 : 0)) : 48;
            out.innerHTML = 'Queued for operator approval — <strong>' +
              (d.label || d.char_id || 'request') + '</strong>.<br>' +
              'Approve it in <strong>Pending Approvals</strong> below to start the run (' +
              nAng + ' angle' + (nAng === 1 ? '' : 's') + ').';
            mLoadPending();
          } else {
            out.classList.add('bad');
            out.textContent = 'Error: ' + ((d && d.error) || 'unknown');
          }
        })
        .catch(err => {
          mBtn.disabled = false;
          out.classList.add('bad');
          out.textContent = 'Request failed: ' + err;
        });
    });
  }

  // ── Operator approval queue (proxied to crews :5000) ──
  function mRenderPending(rows) {
    const box = document.getElementById('m_pending');
    if (!box) return;
    if (!rows || !rows.length) { box.innerHTML = '<div class="appr-empty">No pending requests.</div>'; return; }
    box.innerHTML = rows.map(r =>
      '<div class="appr-row">' +
        '<span class="appr-label">' + secEsc(r.label || r.char_id) + '</span>' +
        '<span class="appr-actions">' +
          '<button class="btn-appr" data-allow="' + secEsc(r.id) + '">Approve</button>' +
          '<button class="btn-decline" data-decline="' + secEsc(r.id) + '">Decline</button>' +
        '</span>' +
      '</div>'
    ).join('');
    box.querySelectorAll('[data-allow]').forEach(b =>
      b.addEventListener('click', () => mDecide(b.getAttribute('data-allow'), 'allow')));
    box.querySelectorAll('[data-decline]').forEach(b =>
      b.addEventListener('click', () => mDecide(b.getAttribute('data-decline'), 'decline')));
  }
  function mLoadPending() {
    fetch('/api/medusa/pending')
      .then(r => r.json())
      .then(d => mRenderPending(d.pending || []))
      .catch(() => {
        const box = document.getElementById('m_pending');
        if (box) box.innerHTML = '<div class="appr-empty">Crews API (:5000) unreachable.</div>';
      });
  }
  function mDecide(id, action) {
    fetch('/api/medusa/pending/' + id + '/decide', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action })
    }).then(() => mLoadPending()).catch(() => mLoadPending());
  }
  const mRefresh = document.getElementById('m_refresh');
  if (mRefresh) mRefresh.addEventListener('click', mLoadPending);
  mLoadPending();

  // Lazy-load the medusa-scoped inspection SPA (served by :8899) on first open.
  var _inspTab = document.querySelector('.tab[data-tab="inspection"]');
  if (_inspTab) _inspTab.addEventListener('click', function(){
    var f = document.getElementById('insp-frame');
    if (f && !f.src) f.src = 'http://' + location.hostname + ':8899/inspection.html?scope=medusa';
  });

  // secEsc: generic HTML-escape helper — used below by the Training tab (kept
  // on removal of the Security tab 2026-08-06; everything else that tab used
  // was Security-only and removed with it).
  function secEsc(s){ return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];}); }

"""
