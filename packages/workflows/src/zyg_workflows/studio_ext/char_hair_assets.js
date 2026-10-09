// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* char_hair_assets.js — installed hair grooms on the Character Studio body.
   2026-09-23.

   char_hair.js GROWS hair from the clay body's own scalp field, and that is
   still what a head with nothing picked wears. This file owns the other half:
   grooms somebody else MODELLED, which no procedural rule reproduces —
   MakeHuman's hair-card styles and Blender Studio's production strand grooms.
   Picking one suppresses only the part it covers (char_hair.js reads
   CSHAIRASSET.wearing()), so an installed beard still leaves the grown brows
   alone and the operator's hair-colour tool still drives a strand groom.

   THE FIT IS MEASURED, NOT PLACED. A groom carries no offset for this body. It
   is stored in its donor's own frame and mapped onto the frame measured on
   whichever body is standing (CSHAIR.frames):

     cards   (MakeHuman)       head frame — origin at the head band's centre
                               (cx, yTop, zc), one unit = one head width
     strands (Blender Studio)  skull frame — origin at the centre of a sphere
                               fitted to the top of the head band, one unit =
                               its radius

   tools/hair_assets/ measured the donor side the same way at conversion time.
   A groom that lands wrong is a measurement to look at, not a nudge to add.

   Sorts after char_hair.js in the bundle (…hair.js < …hair_assets.js), so the
   suppression hook exists before anything asks for it. */
(function () {
  'use strict';
  if (typeof THREE === 'undefined') return;
  if (typeof CS3 === 'undefined' || typeof CS3_HOOKS === 'undefined') return;

  var A = {
    items: [], packs: [], loaded: 0, loading: false,
    pick: '', group: null, token: 0, err: '',
    root: null, btn: null, menu: null, card: null, open: false, hideT: null
  };
  try { A.pick = localStorage.getItem('cs.hairasset') || ''; } catch (e) { }

  function h(s) {
    return (typeof esc === 'function') ? esc(String(s == null ? '' : s))
                                       : String(s == null ? '' : s);
  }
  function byId(id) {
    for (var i = 0; i < A.items.length; i++) if (A.items[i].id === id) return A.items[i];
    return null;
  }

  /* ── what is worn ───────────────────────────────────────────────────────
     char_hair.js asks this BEFORE it grows anything. An id that is picked but
     not yet in the catalogue still counts as worn for its own part once the
     catalogue lands; until then nothing is suppressed, so the head is never
     bald while a groom is in flight. */
  function wearing() {
    var it = A.pick ? byId(A.pick) : null;
    return { hair: !!(it && it.part === 'hair'),
             beard: !!(it && it.part === 'beard'),
             brows: !!(it && it.part === 'brows') };
  }

  /* ── styles ─────────────────────────────────────────────────────────── */
  var css = ''
    + '.cha-wrap{position:relative;display:inline-flex;align-items:center;margin-left:4px}'
    + '.cha-btn{display:inline-flex;align-items:center;gap:6px;background:rgba(255,255,255,.05);'
    + 'border:1px solid var(--line,#2a2f3a);color:var(--muted,#9aa3b2);border-radius:8px;padding:5px 9px;'
    + 'cursor:pointer;font-size:.74rem;line-height:1;white-space:nowrap}'
    + '.cha-btn:hover,.cha-btn.on{color:var(--acc,#00e5ff);border-color:rgba(0,229,255,.45);background:rgba(0,229,255,.1)}'
    + '.cha-menu{position:absolute;top:calc(100% + 6px);left:0;z-index:60;min-width:320px;max-height:66vh;overflow:auto;'
    + 'background:var(--panel,#151922);border:1px solid var(--line,#2a2f3a);border-radius:10px;'
    + 'box-shadow:0 12px 32px rgba(0,0,0,.55);padding:6px;display:none}'
    + '.cha-menu.on{display:block}'
    + '.cha-sec{font-size:.64rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted,#9aa3b2);padding:8px 8px 4px}'
    + '.cha-sec b{color:var(--acc,#00e5ff);font-weight:600}'
    + '.cha-item{display:flex;align-items:center;gap:10px;padding:6px 8px;border-radius:7px;cursor:pointer;color:var(--fg,#e6e9ef)}'
    + '.cha-item:hover{background:rgba(0,229,255,.1)}'
    + '.cha-item.cur .cha-lb::after{content:"  \\2713";color:var(--acc,#00e5ff)}'
    + '.cha-item .cha-th{width:38px;height:38px;border-radius:6px;object-fit:cover;background:#0b0d12;flex:none}'
    + '.cha-item .cha-lb{font-size:.8rem;font-weight:600}'
    + '.cha-item .cha-sb{font-size:.66rem;color:var(--muted,#9aa3b2);margin-top:2px}'
    + '.cha-card{position:fixed;z-index:61;width:300px;background:var(--panel,#151922);border:1px solid var(--line,#2a2f3a);'
    + 'border-radius:10px;box-shadow:0 12px 32px rgba(0,0,0,.6);padding:8px;display:none;pointer-events:none}'
    + '.cha-card.on{display:block}'
    + '.cha-card img{width:100%;aspect-ratio:1/1.24;object-fit:cover;border-radius:7px;background:#0b0d12;display:block}'
    + '.cha-card .cha-lb{font-size:.82rem;font-weight:700;margin-top:7px}'
    + '.cha-card .cha-sb{font-size:.68rem;color:var(--muted,#9aa3b2);margin-top:3px;line-height:1.35}';
  var st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

  /* ── the chip ───────────────────────────────────────────────────────── */
  function mount() {
    if (A.root) return true;
    var name = document.getElementById('cs-cname');
    var anchor = document.getElementById('csm-wrap');    /* beside the Models chip */
    if (!anchor && (!name || !name.parentNode)) return false;
    var wrap = document.createElement('div'); wrap.className = 'cha-wrap'; wrap.id = 'cha-wrap';
    var btn = document.createElement('button'); btn.className = 'cha-btn'; btn.id = 'cha-btn';
    btn.title = 'Installed hair grooms — MakeHuman hair cards and Blender Studio strand grooms, '
              + 'fitted to this body’s own measured head';
    btn.innerHTML = '<span id="cha-cur">Hair asset</span><span style="font-size:.65rem;opacity:.8">&#9662;</span>';
    var menu = document.createElement('div'); menu.className = 'cha-menu'; menu.id = 'cha-menu';
    wrap.appendChild(btn); wrap.appendChild(menu);
    if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(wrap, anchor.nextSibling);
    else name.parentNode.parentNode.insertBefore(wrap, name.parentNode.nextSibling);
    var card = document.createElement('div'); card.className = 'cha-card'; card.id = 'cha-card';
    document.body.appendChild(card);
    A.root = wrap; A.btn = btn; A.menu = menu; A.card = card;
    btn.addEventListener('click', function (e) { e.stopPropagation(); A.open ? close() : openMenu(); });
    document.addEventListener('click', function (e) { if (A.open && !wrap.contains(e.target)) close(); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && A.open) close(); });
    return true;
  }

  function label() {
    var el = document.getElementById('cha-cur');
    if (!el) return;
    var it = A.pick ? byId(A.pick) : null;
    el.textContent = it ? it.label : (A.pick ? 'Hair asset' : 'Grown hair');
  }

  function render() {
    if (!A.menu) return;
    if (A.err) { A.menu.innerHTML = '<div class="cha-sec">' + h(A.err) + '</div>'; return; }
    if (!A.items.length) { A.menu.innerHTML = '<div class="cha-sec">no grooms installed</div>'; return; }
    var html = '<div class="cha-sec">Grown</div>'
      + '<div class="cha-item' + (A.pick ? '' : ' cur') + '" data-id="">'
      + '<span class="cha-th"></span><div><div class="cha-lb">Grown hair</div>'
      + '<div class="cha-sb">char_hair.js raises strands from this body’s own scalp</div></div></div>';
    for (var p = 0; p < A.packs.length; p++) {
      var pk = A.packs[p];
      html += '<div class="cha-sec">' + h(pk.n)
        + ' · <b>' + h(pk.licence) + '</b>'
        + (pk.attrib ? ' · credit required' : '') + '</div>';
      for (var i = 0; i < A.items.length; i++) {
        var it = A.items[i];
        if (it.pack !== pk.id) continue;
        html += '<div class="cha-item' + (it.id === A.pick ? ' cur' : '') + '" data-id="' + h(it.id) + '">'
          + (it.pv ? '<img class="cha-th" src="' + h(base() + it.pv) + '" alt="">' : '<span class="cha-th"></span>')
          + '<div><div class="cha-lb">' + h(it.label) + '</div><div class="cha-sb">'
          + h(it.part) + ' · ' + (it.kind === 'strands'
              ? (it.strands ? it.strands.toLocaleString() + ' strands' : 'strands')
              : (it.tris ? it.tris.toLocaleString() + ' tris, cards' : 'cards'))
          + '</div></div></div>';
      }
    }
    A.menu.innerHTML = html;
    var els = A.menu.querySelectorAll('.cha-item');
    for (var k = 0; k < els.length; k++) {
      els[k].addEventListener('click', function (e) { e.stopPropagation(); pick(this.getAttribute('data-id')); });
      els[k].addEventListener('mouseenter', function () { hover(this.getAttribute('data-id'), this); });
      els[k].addEventListener('mouseleave', function () { unhover(); });
    }
  }

  function hover(id, el) {
    var it = id ? byId(id) : null;
    if (!it || !A.card) return;
    if (A.hideT) { clearTimeout(A.hideT); A.hideT = null; }
    A.card.innerHTML = (it.pv ? '<img src="' + h(base() + it.pv) + '" alt="">' : '')
      + '<div class="cha-lb">' + h(it.label) + '</div>'
      + '<div class="cha-sb">' + h(it.credit || '') + '</div>'
      + '<div class="cha-sb">' + h(it.licence) + (it.attrib ? ' — attribution required' : '') + '</div>'
      + (it.note ? '<div class="cha-sb">' + h(it.note) + '</div>' : '');
    var r = el.getBoundingClientRect(), mr = A.menu.getBoundingClientRect();
    var left = mr.right + 10;
    if (left + 310 > window.innerWidth) left = Math.max(8, mr.left - 310);
    A.card.style.left = left + 'px';
    A.card.style.top = Math.max(8, Math.min(r.top, window.innerHeight - 460)) + 'px';
    A.card.classList.add('on');
  }
  function unhover() {
    A.hideT = setTimeout(function () { if (A.card) A.card.classList.remove('on'); }, 80);
  }

  function openMenu() { A.open = true; A.btn.classList.add('on'); A.menu.classList.add('on'); refresh(); }
  function close() {
    A.open = false;
    if (A.btn) A.btn.classList.remove('on');
    if (A.menu) A.menu.classList.remove('on');
    if (A.card) A.card.classList.remove('on');
  }

  function pick(id) {
    A.pick = id || '';
    try { localStorage.setItem('cs.hairasset', A.pick); } catch (e) { }
    close(); label();
    build();
    /* the grown hair has to be rebuilt too: what it grows depends on what the
       asset now covers */
    if (typeof window.csHairRebuild === 'function') window.csHairRebuild();
  }

  /* ── the catalogue ──────────────────────────────────────────────────── */
  var BASE = '/inspect/arch-asset/';
  function base() { return BASE; }
  function refresh(force) {
    if (A.loading) return;
    if (!force && A.loaded && Date.now() - A.loaded < 60000) { render(); label(); return; }
    A.loading = true;
    fetch('/inspect/api/studio/char_hair/assets', { cache: 'no-cache' })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        A.loading = false;
        if (!j || !j.ok) { A.err = (j && j.error) || 'hair catalogue unavailable'; render(); return; }
        A.err = '';
        A.items = j.items || []; A.packs = j.packs || [];
        BASE = j.base || BASE;
        A.loaded = Date.now();
        render(); label();
        if (A.pick && !A.group) build();
      })
      .catch(function (e) {
        A.loading = false; A.err = String(e && e.message || e); render();
      });
  }

  /* ── the fit ────────────────────────────────────────────────────────── */
  function dispose() {
    if (!A.group) return;
    if (A.group.parent) A.group.parent.remove(A.group);
    A.group.traverse(function (o) {
      if (!o.isMesh) return;
      if (o.geometry) o.geometry.dispose();
      var ms = Array.isArray(o.material) ? o.material : [o.material];
      for (var i = 0; i < ms.length; i++) if (ms[i] && ms[i].dispose) ms[i].dispose();
    });
    A.group = null;
  }

  function hairColour() {
    /* the operator's own hair-colour tool drives a strand groom; a card groom
       keeps its painted texture, which already carries a colour */
    try {
      if (window.CSHAIR && CS3 && CS3.hairInfo && CS3.hairInfo.color) { /* informational */ }
    } catch (e) { }
    var c = new THREE.Color(0x3b2a1a);
    try {
      var v = (typeof cstVal === 'function') ? cstVal('identity.hair_color') : '';
      var HEX = { 'black': 0x1a1512, 'dark brown': 0x3b2a1a, 'brown': 0x5a3d22,
        'light brown': 0x8b6a45, 'auburn': 0x7a3b1e, 'red': 0xa3441f,
        'blonde': 0xd9b46a, 'blond': 0xd9b46a, 'dark blond': 0xa88a4f,
        'dark blonde': 0xa88a4f, 'grey': 0x8c8c8c, 'gray': 0x8c8c8c,
        'white': 0xe8e6e2, 'silver': 0xcfcfcf, 'ginger': 0xa3441f };
      var hx = HEX[String(v || '').toLowerCase()];
      if (hx !== undefined) c.setHex(hx);
    } catch (e) { }
    if (CS3.renderer && THREE.sRGBEncoding && CS3.renderer.outputEncoding === THREE.sRGBEncoding
        && c.convertSRGBToLinear) c.convertSRGBToLinear();
    return c;
  }

  function build() {
    dispose();
    var it = A.pick ? byId(A.pick) : null;
    if (!it || !CS3.model || !CS3.scene) { if (A.pick && !A.items.length) refresh(true); return; }
    if (typeof THREE.GLTFLoader !== 'function') { A.err = 'GLTFLoader unavailable'; return; }
    var F = (window.CSHAIR && CSHAIR.frames) ? CSHAIR.frames(CS3.model) : null;
    if (!F) return;
    var strands = (it.kind === 'strands');
    if (strands && (!F.skullCentre || !F.skullRadius)) return;
    var origin = strands ? F.skullCentre : F.headOrigin;
    var scale = strands ? F.skullRadius : F.headW;

    var token = ++A.token;
    var url = base() + it.u;
    new THREE.GLTFLoader().load(url, function (g) {
      if (token !== A.token) return;                /* a later pick won the race */
      var root = g.scene || (g.scenes && g.scenes[0]);
      if (!root) return;
      var col = hairColour();
      root.traverse(function (o) {
        if (!o.isMesh) return;
        o.frustumCulled = false;
        if (strands) {
          /* a strand groom ships with no material on purpose: the studio owns
             the colour, so the hair-colour tool still works on it */
          o.material = new THREE.MeshStandardMaterial({
            color: col, roughness: 0.58, metalness: 0, side: THREE.DoubleSide
          });
        } else {
          var ms = Array.isArray(o.material) ? o.material : [o.material];
          for (var i = 0; i < ms.length; i++) {
            var m = ms[i];
            if (!m) continue;
            /* the GLB says MASK; three.js maps that to alphaTest, but be
               explicit so a card never renders as an opaque grey rectangle */
            m.transparent = false;
            m.alphaTest = m.alphaTest || 0.45;
            m.depthWrite = true;
            m.side = THREE.DoubleSide;
          }
        }
      });
      var grp = new THREE.Group();
      grp.name = 'cs-hair-asset';
      grp.add(root);
      grp.scale.setScalar(scale);
      grp.position.copy(origin);
      var parent = (CS3.model && CS3.model.parent) || CS3.scene;
      parent.add(grp);
      A.group = grp;
      if (typeof cs3dLoop === 'function') cs3dLoop();
      var cr = document.getElementById('cs-credit');
      if (cr && it.attrib) cr.title = (cr.title || '') + ' · hair: ' + (it.credit || it.label);
    }, undefined, function (err) {
      if (token !== A.token) return;
      A.err = 'groom load failed: ' + String(err && err.message || err);
      console.warn('char_hair_assets', url, err);
    });
  }

  /* ── hooks ──────────────────────────────────────────────────────────── */
  var pending = 0;
  CS3_HOOKS.push(function (why) {
    if (mount()) { label(); if (!A.loaded) refresh(); }
    if (!A.pick) { dispose(); return; }
    /* the body changed under the groom: refit on the next frame, once */
    if (pending) return;
    pending = setTimeout(function () {
      pending = 0;
      try { build(); } catch (e) { console.warn('char_hair_assets build', why, e); }
    }, 0);
  });
  if (mount()) { label(); refresh(); }

  window.CSHAIRASSET = {
    state: A, wearing: wearing, pick: pick, refresh: refresh,
    build: build, dispose: dispose,
    frames: function () { return (window.CSHAIR && CSHAIR.frames) ? CSHAIR.frames(CS3.model) : null; }
  };
})();
