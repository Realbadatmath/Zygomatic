// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* char_models.js — Character Studio: the MODELS dropdown in the header.
   2026-09-20, on the operator's brief: "at Inject Character allow me to
   inject the base 3d model; where it says the name of the base body next
   to Inject Character, add a dropdown button; clicking it shows models
   generated or created based on that 3d model; hovering a model shows a
   preview window with that character."

   The list comes from /inspect/api/studio/char_photoreal/variants: the four
   CC0 base bodies and every model derived from one of them that exists on
   disk (today: the photoreal skins). Nothing here invents an entry.

   Picking a base body stands it in the frame in clay (photoreal off, body
   pinned the way the Base body tool pins it). Picking a derived model stands
   its base body and switches that skin on. The header name follows the pick
   while no character bible is injected; an injected character keeps its
   name, and its body follows its bible as before.

   Sorts BEFORE char_photoreal.js in the bundle (m < p), so the switch is
   reached through window.CSPHOTOREAL at click time, never at load time. */
(function () {
  'use strict';
  if (typeof CS3 === 'undefined' || typeof CS3_HOOKS === 'undefined') return;
  if (typeof cs3dLoadModel !== 'function') return;

  var M = { list: [], open: false, hover: null, loaded: 0, root: null, btn: null,
            menu: null, card: null, hideT: null };

  function h(s) { return (typeof esc === 'function') ? esc(String(s == null ? '' : s)) : String(s == null ? '' : s); }
  function api() {
    return fetch('/inspect/api/studio/char_photoreal/variants', { cache: 'no-cache' })
      .then(function (r) { return r.json(); });
  }

  /* ── styles ─────────────────────────────────────────────────────────── */
  var css = ''
    + '.csm-wrap{position:relative;display:inline-flex;align-items:center;margin-left:4px}'
    + '.csm-btn{display:inline-flex;align-items:center;gap:6px;background:rgba(255,255,255,.05);'
    + 'border:1px solid var(--line,#2a2f3a);color:var(--muted,#9aa3b2);border-radius:8px;padding:5px 9px;'
    + 'cursor:pointer;font-size:.74rem;line-height:1;white-space:nowrap}'
    + '.csm-btn:hover,.csm-btn.on{color:var(--acc,#00e5ff);border-color:rgba(0,229,255,.45);background:rgba(0,229,255,.1)}'
    + '.csm-btn .csm-caret{font-size:.65rem;opacity:.8}'
    + '.csm-menu{position:absolute;top:calc(100% + 6px);left:0;z-index:60;min-width:300px;max-height:64vh;overflow:auto;'
    + 'background:var(--panel,#151922);border:1px solid var(--line,#2a2f3a);border-radius:10px;'
    + 'box-shadow:0 12px 32px rgba(0,0,0,.55);padding:6px;display:none}'
    + '.csm-menu.on{display:block}'
    + '.csm-sec{font-size:.64rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted,#9aa3b2);padding:8px 8px 4px}'
    + '.csm-item{display:flex;align-items:center;gap:10px;padding:6px 8px;border-radius:7px;cursor:pointer;color:var(--fg,#e6e9ef)}'
    + '.csm-item:hover,.csm-item.hot{background:rgba(0,229,255,.1)}'
    + '.csm-item.cur .csm-lb::after{content:"  \\2713";color:var(--acc,#00e5ff)}'
    + '.csm-item .csm-th{width:34px;height:34px;border-radius:6px;object-fit:cover;background:#0b0d12;flex:none}'
    + '.csm-item .csm-lb{font-size:.8rem;font-weight:600}'
    + '.csm-item .csm-sb{font-size:.66rem;color:var(--muted,#9aa3b2);margin-top:2px}'
    + '.csm-item.derived{margin-left:14px;border-left:2px solid rgba(0,229,255,.25)}'
    + '.csm-card{position:fixed;z-index:61;width:300px;background:var(--panel,#151922);border:1px solid var(--line,#2a2f3a);'
    + 'border-radius:10px;box-shadow:0 12px 32px rgba(0,0,0,.6);padding:8px;display:none;pointer-events:none}'
    + '.csm-card.on{display:block}'
    + '.csm-card img{width:100%;aspect-ratio:1/1;object-fit:cover;border-radius:7px;background:#0b0d12;display:block}'
    + '.csm-card .csm-strip{width:100%;margin-top:6px;border-radius:5px;display:block}'
    + '.csm-card .csm-lb{font-size:.82rem;font-weight:700;margin-top:7px}'
    + '.csm-card .csm-sb{font-size:.68rem;color:var(--muted,#9aa3b2);margin-top:3px;line-height:1.35}';
  var st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

  /* ── the chip beside the name ───────────────────────────────────────── */
  function mount() {
    if (M.root) return true;
    var top = document.querySelector('#view-charstudio .cs-top');
    var name = document.getElementById('cs-cname');
    if (!top || !name || !name.parentNode) return false;
    var wrap = document.createElement('div'); wrap.className = 'csm-wrap'; wrap.id = 'csm-wrap';
    var btn = document.createElement('button'); btn.className = 'csm-btn'; btn.id = 'csm-btn';
    btn.title = 'Models built from the base body: pick one to stand it in the frame';
    btn.innerHTML = '<span id="csm-cur">Models</span><span class="csm-caret">&#9662;</span>';
    var menu = document.createElement('div'); menu.className = 'csm-menu'; menu.id = 'csm-menu';
    wrap.appendChild(btn); wrap.appendChild(menu);
    name.parentNode.parentNode.insertBefore(wrap, name.parentNode.nextSibling);
    var card = document.createElement('div'); card.className = 'csm-card'; card.id = 'csm-card';
    document.body.appendChild(card);
    M.root = wrap; M.btn = btn; M.menu = menu; M.card = card;
    btn.addEventListener('click', function (e) { e.stopPropagation(); toggle(); });
    document.addEventListener('click', function (e) {
      if (M.open && !wrap.contains(e.target)) close();
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && M.open) close(); });
    return true;
  }

  function currentId() {
    var body = CS3.modelId || '';
    var pr = window.CSPHOTOREAL && CSPHOTOREAL.state;
    if (pr && pr.on && pr.man && pr.man.body === body) return body + ':photoreal';
    return body;
  }

  function label() {
    var id = currentId(), it = null;
    for (var i = 0; i < M.list.length; i++) if (M.list[i].id === id) it = M.list[i];
    var cur = document.getElementById('csm-cur');
    if (cur) cur.textContent = it ? it.label : 'Models';
    if (typeof CS !== 'undefined' && !CS.loaded) {
      var nm = document.getElementById('cs-cname');
      if (nm && it) nm.textContent = it.kind === 'base' ? 'Base body · ' + it.label : it.label;
    }
  }

  function render() {
    if (!M.menu) return;
    var cur = currentId(), html = '', bases = M.list.filter(function (m) { return m.kind === 'base'; });
    if (!M.list.length) { M.menu.innerHTML = '<div class="csm-sec">no models listed</div>'; return; }
    bases.forEach(function (b) {
      var kids = M.list.filter(function (m) { return m.kind !== 'base' && m.base === b.id; });
      html += '<div class="csm-sec">' + h(b.label) + (kids.length ? ' · ' + kids.length + ' derived' : '') + '</div>';
      [b].concat(kids).forEach(function (m) {
        html += '<div class="csm-item' + (m.kind !== 'base' ? ' derived' : '') + (m.id === cur ? ' cur' : '')
          + '" data-id="' + h(m.id) + '">'
          + (m.preview_url ? '<img class="csm-th" src="' + h(m.preview_url) + '" alt="">' : '<span class="csm-th"></span>')
          + '<div><div class="csm-lb">' + h(m.kind === 'base' ? 'Base body (clay)' : m.label) + '</div>'
          + '<div class="csm-sb">' + h(m.sub || '') + '</div></div></div>';
      });
    });
    M.menu.innerHTML = html;
    var items = M.menu.querySelectorAll('.csm-item');
    for (var i = 0; i < items.length; i++) {
      items[i].addEventListener('mouseenter', function () { hover(this.getAttribute('data-id'), this); });
      items[i].addEventListener('mouseleave', function () { unhover(); });
      items[i].addEventListener('click', function (e) { e.stopPropagation(); pick(this.getAttribute('data-id')); });
    }
  }

  /* ── the hover preview window ───────────────────────────────────────── */
  function hover(id, el) {
    var m = null;
    for (var i = 0; i < M.list.length; i++) if (M.list[i].id === id) m = M.list[i];
    if (!m || !M.card) return;
    if (M.hideT) { clearTimeout(M.hideT); M.hideT = null; }
    M.hover = id;
    M.card.innerHTML = (m.preview_url ? '<img src="' + h(m.preview_url) + '" alt="">' : '')
      + (m.preview2_url && m.preview2_url !== m.preview_url ? '<img class="csm-strip" src="' + h(m.preview2_url) + '" alt="">' : '')
      + '<div class="csm-lb">' + h(m.label) + '</div><div class="csm-sb">' + h(m.sub || '') + '</div>'
      + (m.kind === 'base' ? '<div class="csm-sb">Click to stand the untouched base body in the frame.</div>'
                           : '<div class="csm-sb">Generated from the ' + h(m.base.replace('_', ' ')) + ' base body. Click to stand it in the frame; Compare shows it beside the clay base.</div>');
    var r = el.getBoundingClientRect(), mr = M.menu.getBoundingClientRect();
    var left = mr.right + 10, top = Math.max(8, Math.min(r.top, window.innerHeight - 420));
    if (left + 310 > window.innerWidth) left = Math.max(8, mr.left - 310);
    M.card.style.left = left + 'px'; M.card.style.top = top + 'px';
    M.card.classList.add('on');
  }
  function unhover() {
    M.hideT = setTimeout(function () { M.hover = null; if (M.card) M.card.classList.remove('on'); }, 80);
  }

  /* ── open / close / pick ────────────────────────────────────────────── */
  function toggle() { if (M.open) close(); else open(); }
  function open() {
    if (!M.menu) return;
    M.open = true; M.btn.classList.add('on'); M.menu.classList.add('on');
    refresh(true);
  }
  function close() {
    M.open = false;
    if (M.btn) M.btn.classList.remove('on');
    if (M.menu) M.menu.classList.remove('on');
    if (M.card) M.card.classList.remove('on');
  }
  function refresh(force) {
    if (!force && Date.now() - M.loaded < 15000) { render(); label(); return; }
    api().then(function (j) {
      if (!j || !j.ok) return;
      M.list = j.models || []; M.loaded = Date.now();
      render(); label();
    }).catch(function (e) { console.warn('char_models', e); });
  }
  function pick(id) {
    var m = null;
    for (var i = 0; i < M.list.length; i++) if (M.list[i].id === id) m = M.list[i];
    if (!m) return;
    close();
    var pr = window.CSPHOTOREAL;
    if (m.kind === 'base') {
      if (pr && pr.state.on) pr.setOn(false);
      cs3dLoadModel(m.base, true);
    } else {
      cs3dLoadModel(m.base, true);
      if (pr) { if (pr.state.on) pr.refresh(); else pr.setOn(true); }
    }
    setTimeout(function () { label(); render(); }, 300);
  }

  /* the photoreal skin lands after an async texture load, not on a hook;
     char_photoreal.js stamps the credit line when it does, so follow that */
  (function watchCredit() {
    var cr = document.getElementById('cs-credit');
    if (!cr || !window.MutationObserver) return;
    new MutationObserver(function () { if (M.list.length) { label(); if (M.open) render(); } })
      .observe(cr, { childList: true, characterData: true, subtree: true });
  })();
  CS3_HOOKS.push(function (why) {
    if (!mount()) return;
    if (!M.list.length) refresh(true); else { label(); if (M.open) render(); }
  });
  if (mount()) refresh(true);

  window.CSMODELS = { state: M, open: open, close: close, pick: pick, hover: hover, refresh: refresh };
})();
