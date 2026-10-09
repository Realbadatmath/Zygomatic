// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* reference_model — the icon rail beside the assistant, and the sheet behind
   its one icon (2026-09-23).

   The operator asked for "a list with icons against the right side of the AI
   assistant, for now only one icon: clicking it lets me add images as a
   reference model". So this adds a RAIL — a column that can hold many icons —
   and fills it with one. Adding the second is one entry in RAIL_TOOLS.

   What the rail is for, and why it is not in the dock: the dock is the
   session's option surface and scrolls sideways past 190 icons; this column
   belongs to the CHAT. It appears and disappears with the assistant panel,
   because everything on it is something you hand the assistant.

   The one icon opens the reference-model sheet: a name, the pictures, the ROLE
   of each picture (which direction it was seen from) and the measured
   dimensions. Those last two are not decoration. A photograph cannot fix a
   size — depth and scale trade off exactly along every ray — so a reference
   with no measured length can only ever produce the right SHAPE, and the sheet
   says so in as many words rather than letting a wrong size look like a right
   one.

   Nothing in inspection.html was edited. The rail is appended to #ar-stage and
   follows AR.assist.open through a wrapper on arAssistRender; the sheet is the
   studio's own arSheet(). Server side: arch_server_ext/reference_model.py.

   Only the tab's own globals are used (AR, AR_EXT, arSheet, arSheetClose,
   arToast, arIcon, esc). No new libraries. */
(function () {
  'use strict';

  var API = '/inspect/api/architecture/ext/reference_model/';
  var RAIL_ID = 'ar-refrail';
  var MAX_EDGE = 4096;          /* the server caps at the same number */
  var S = {models: [], roles: [], current: '', sheet: false, busy: 0};

  /* ── the rail's icons. One, for now; the column exists for the next. ──── */
  var RAIL_TOOLS = [
    {id: 'refmodel', lb: 'Reference model',
     tip: 'Reference model — park photographs and measured plans of a real thing (a ship, a bridge, a lamp post) '
        + 'and the assistant builds it in Blender from them',
     svg: '<path d="M3.2 7.4h11.4v9.2H3.2z"/><path d="M6.6 4.6h11.4v9.2"/>'
        + '<path d="M3.2 14.2l3.3-3 2.4 2.1 2.6-3.1 3.1 4.4"/><circle cx="11.4" cy="9.4" r="1.15"/>'},
  ];

  function post(op, body) {
    return fetch(API + op, {method: 'POST', headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify(body || {})})
      .then(function (r) { return r.json(); });
  }
  function E(s) { return (window.esc ? esc(s) : String(s === null || s === undefined ? '' : s)
    .replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; })); }
  function toast(m, c) { if (window.arToast) arToast(E(m), c); }
  function cur() { for (var i = 0; i < S.models.length; i++) if (S.models[i].id === S.current) return S.models[i]; return null; }
  function num(v) { var f = parseFloat(v); return (isFinite(f) && f > 0) ? f : 0; }
  function datumStr(i) {
    var d = i.datum;
    return (d && d.length === 2 && (d[0] !== 0.5 || d[1] !== 0.5)) ? (d[0] + ',' + d[1]) : '';
  }
  function roleLabel(id) { for (var i = 0; i < S.roles.length; i++) if (S.roles[i].id === id) return S.roles[i].label; return id; }

  /* ── style ──────────────────────────────────────────────────────────────
     The rail sits immediately right of the 362 px chat panel at left:12, so
     its left edge is 12 + 362 + 8. The option strip and the HUD already move
     right when the chat opens (.ar-chat, left:386); with the rail up they have
     to clear it too, which is what .ar-refrail-on does. Same idiom, one class
     further — not a new mechanism. */
  function style() {
    if (document.getElementById('refm-css')) return;
    var st = document.createElement('style');
    st.id = 'refm-css';
    st.textContent =
      '#' + RAIL_ID + '{position:absolute;left:382px;top:62px;z-index:7;display:none;flex-direction:column;'
        + 'gap:7px;align-items:center;padding:7px 6px;border:1px solid var(--line);border-radius:12px;'
        + 'background:#15171d;box-shadow:0 18px 44px rgba(0,0,0,.5);}'
      + '#' + RAIL_ID + '.on{display:flex;}'
      + '#' + RAIL_ID + ' .ar-tool{position:relative;}'
      + '#' + RAIL_ID + ' .ar-tool .badge{position:absolute;right:-3px;top:-3px;min-width:15px;height:15px;'
        + 'border-radius:8px;background:var(--acc);color:#04222a;font-size:.52rem;font-weight:700;'
        + 'line-height:15px;text-align:center;padding:0 3px;pointer-events:none;}'
      + '#' + RAIL_ID + ' .cap{font-size:.5rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);'
        + 'margin-bottom:1px;}'
      + '.ar-stage.ar-chat.ar-refrail-on .ar-opts{left:444px;}'
      + '.ar-stage.ar-chat.ar-refrail-on .ar-hud{left:444px;}'
      /* the sheet */
      + '.refm-row{display:flex;gap:6px;align-items:center;margin:0 0 7px;}'
      + '.refm-row .sp{flex:1;}'
      + '.refm select,.refm input,.refm textarea{background:var(--panel2);border:1px solid var(--line);'
        + 'color:var(--txt);border-radius:7px;padding:4px 6px;font:inherit;font-size:.68rem;}'
      + '.refm input,.refm select{min-width:0;}'
      + '.refm textarea{width:100%;resize:vertical;min-height:46px;}'
      + '.refm button{border:1px solid var(--line);background:transparent;color:var(--muted);border-radius:7px;'
        + 'padding:3px 9px;height:24px;cursor:pointer;font-size:.64rem;line-height:1;}'
      + '.refm button:hover{color:var(--txt);border-color:var(--acc);}'
      + '.refm button.go{border-color:var(--acc);color:var(--acc);background:rgba(0,229,255,.12);font-weight:600;}'
      + '.refm .sh{margin:13px 0 5px;font-size:.58rem;letter-spacing:.11em;text-transform:uppercase;'
        + 'color:var(--muted);border-top:1px solid var(--line);padding-top:8px;}'
      + '.refm .dims{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;}'
      /* grid items size to min-content by default, which pushed the third
         column past the sheet edge and clipped the height field */
      + '.refm .dims label{display:flex;flex-direction:column;gap:2px;font-size:.56rem;'
        + 'color:var(--muted);min-width:0;}'
      + '.refm .dims input{width:100%;box-sizing:border-box;}'
      + '.refm .warn{font-size:.62rem;color:var(--warn);line-height:1.4;margin:6px 0 0;}'
      + '.refm .ok{font-size:.62rem;color:var(--muted);line-height:1.4;margin:6px 0 0;}'
      + '.refm .drop{border:1px dashed var(--line);border-radius:10px;padding:12px 10px;text-align:center;'
        + 'font-size:.64rem;color:var(--muted);cursor:pointer;}'
      + '.refm .drop.hot{border-color:var(--acc);color:var(--acc);background:rgba(0,229,255,.07);}'
      + '.refm .pic{display:flex;gap:8px;padding:7px 0;border-top:1px solid var(--line);}'
      + '.refm .pic img{width:78px;height:58px;object-fit:cover;border-radius:6px;border:1px solid var(--line);'
        + 'background:#0c0e12;flex:0 0 auto;}'
      + '.refm .pic .col{flex:1;min-width:0;display:flex;flex-direction:column;gap:4px;}'
      + '.refm .pic .nm{font-size:.58rem;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}'
      + '.refm .pic select,.refm .pic input{font-size:.62rem;padding:3px 5px;}'
      + '.refm .asset img{width:100%;border-radius:8px;border:1px solid var(--line);display:block;margin-top:6px;}'
      /* the inspection set is TEN 1600px renders: at full sheet width that is a
         scroll, not a set you can read at a glance. Two up, click for full size. */
      + '.refm .insp{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:6px;}'
      /* an audit finding is a DEFECT, not a note: it reads red, next to the
         pictures it was measured off */
      + '.refm .bad{font-size:.62rem;color:#ff9c8a;line-height:1.4;margin:4px 0 0;}'
      + '.refm .insp a{display:block;text-decoration:none;min-width:0;}'
      + '.refm .insp img{width:100%;margin:0;}'
      + '.refm .insp span{display:block;font-size:.55rem;color:var(--muted);margin-top:2px;'
        + 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}';
    document.head.appendChild(st);
  }

  /* ── the rail ───────────────────────────────────────────────────────────── */
  function ensureRail() {
    var stage = document.getElementById('ar-stage');
    if (!stage) return null;
    var el = document.getElementById(RAIL_ID);
    if (!el) {
      el = document.createElement('div');
      el.id = RAIL_ID;
      stage.appendChild(el);
    }
    return el;
  }

  function railHtml() {
    return '<div class="cap">REF</div>' + RAIL_TOOLS.map(function (t) {
      var badge = '';
      if (t.id === 'refmodel') {
        var c = cur();
        var n = c && c.images ? c.images.length : 0;
        if (n) badge = '<span class="badge">' + n + '</span>';
      }
      return '<div class="ar-tool' + (S.sheet && t.id === 'refmodel' ? ' on' : '') + '" data-reftool="' + t.id + '"'
        + ' role="button" title="' + E(t.lb) + ' — ' + t.tip.replace(/"/g, '&quot;') + '">'
        + (window.arIcon ? arIcon(t)
           : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" '
             + 'stroke-linecap="round" stroke-linejoin="round">' + t.svg + '</svg>')
        + badge + '</div>';
    }).join('');
  }

  function railSync() {
    var el = ensureRail();
    if (!el) return;
    var open = !!(window.AR && AR.assist && AR.assist.open);
    el.innerHTML = railHtml();
    el.classList.toggle('on', open);
    if (AR && AR.host) AR.host.classList.toggle('ar-refrail-on', open);
    if (!open && S.sheet) closeSheet();
  }

  /* ── loading ────────────────────────────────────────────────────────────── */
  function load() {
    return post('list', {}).then(function (d) {
      if (!d || !d.ok) throw new Error((d && d.error) || 'the reference store did not answer');
      S.models = d.models || [];
      S.roles = d.roles || [];
      S.current = d.current || (S.models.length ? S.models[0].id : '');
      return d;
    });
  }

  /* ── the sheet ──────────────────────────────────────────────────────────── */
  function openSheet() {
    style();
    load().then(function () {
      S.sheet = true;
      if (window.arSheet) arSheet('Reference model', shell());
      paint();
      bind();
      railSync();
    }).catch(function (e) { toast('Reference models: ' + (e.message || e), 'bad'); });
  }
  function closeSheet() {
    S.sheet = false;
    if (window.arSheetClose) arSheetClose();
    unbind();
    railSync();
  }

  function shell() {
    return '<div class="refm" id="refm">'
      + '<div class="refm-row">'
      +   '<select id="refm-pick" style="flex:1" title="Which reference model to work on"></select>'
      +   '<button onclick="refmNew()" title="Start a new reference model">new</button>'
      +   '<button onclick="refmDelete()" title="Delete this reference model and all its pictures">del</button>'
      + '</div>'
      + '<div id="refm-body"></div>'
      + '</div>';
  }

  function paint() {
    var pick = document.getElementById('refm-pick');
    if (pick) {
      pick.innerHTML = S.models.length
        ? S.models.map(function (m) {
            return '<option value="' + m.id + '"' + (m.id === S.current ? ' selected' : '') + '>'
              + E(m.name) + ' · ' + (m.images ? m.images.length : 0) + '</option>'; }).join('')
        : '<option value="">— no reference models yet —</option>';
      pick.onchange = function () { refmSetCurrent(pick.value); };
    }
    var body = document.getElementById('refm-body');
    if (!body) return;
    var m = cur();
    if (!m) {
      body.innerHTML = '<p class="ok">A reference model is a folder of pictures of one real thing, plus the few '
        + 'numbers that turn pictures into geometry. Press <b>new</b> to start one.</p>';
      return;
    }
    var warn = m.measurable ? ''
      : '<p class="warn">Nothing is measured yet. One real dimension is the whole difference between a shape and '
        + 'a building: without it the assistant can only give you the right shape at a size nobody can check.</p>';
    body.innerHTML =
        '<div class="sh">What it is</div>'
      + '<div class="refm-row"><input id="refm-name" style="flex:2" value="' + E(m.name) + '" placeholder="name">'
      +   '<input id="refm-subject" style="flex:1" value="' + E(m.subject || '') + '" placeholder="ship, bridge…"></div>'
      + '<div class="dims">'
      +   '<label>length m<input id="refm-length_m" value="' + (num(m.length_m) || '') + '" placeholder="0"></label>'
      +   '<label>width m<input id="refm-beam_m" value="' + (num(m.beam_m) || '') + '" placeholder="0"></label>'
      +   '<label>height m<input id="refm-height_m" value="' + (num(m.height_m) || '') + '" placeholder="0"></label>'
      + '</div>' + warn
      + '<textarea id="refm-notes" placeholder="What it is, what the plans are, anything the pictures do not say."'
      +   ' style="margin-top:7px">' + E(m.notes || '') + '</textarea>'
      + '<div class="refm-row" style="margin-top:6px"><span class="sp"></span>'
      +   '<button onclick="refmSave()" class="go">save</button></div>'
      + '<div class="sh">Pictures <span style="text-transform:none;letter-spacing:0">'
      +   '— the ROLE is which direction it was seen from</span></div>'
      + '<div class="drop" id="refm-drop">Drop pictures here, paste them, or <b>click to choose</b><br>'
      +   '<span style="opacity:.75">jpeg, png or webp</span></div>'
      + '<div id="refm-list"></div>'
      + '<div class="sh">Asset</div><div id="refm-asset"></div>';
    pics();
    asset();
  }

  function pics() {
    var host = document.getElementById('refm-list');
    var m = cur();
    if (!host || !m) return;
    if (!m.images || !m.images.length) {
      host.innerHTML = '<p class="ok">No pictures yet. A measured elevation or plan is worth a dozen photographs: '
        + 'it is the one kind of picture that says where the camera stood.</p>';
      return;
    }
    host.innerHTML = m.images.map(function (i) {
      return '<div class="pic"><img src="' + i.thumb + '" alt="" loading="lazy">'
        + '<div class="col">'
        +   '<div class="nm" title="' + E(i.name || i.id) + '">' + E(i.name || i.id)
        +     ' · ' + (i.w || '?') + '×' + (i.h || '?') + '</div>'
        +   '<select title="' + E(roleLabel(i.role)) + '"'
        +     ' onchange="refmSetRole(\'' + i.id + '\', this.value)">'
        +     S.roles.map(function (r) {
                return '<option value="' + r.id + '"' + (r.id === i.role ? ' selected' : '') + '>'
                  + E(r.short || r.label) + '</option>'; }).join('')
        +   '</select>'
        +   '<input value="' + E(i.note || '') + '" placeholder="note (bow to the right, 1:100…)"'
        +     ' onchange="refmSetNote(\'' + i.id + '\', this.value)">'
        +   '<div style="display:flex;gap:6px;align-items:center">'
        +     '<input style="width:74px" value="' + (num(i.span_m) || '') + '" placeholder="m across"'
        +       ' title="How many metres the WHOLE width of this picture covers. A plate is rarely cropped to'
        +       ' the subject\'s ends, so this is usually not the same as its length."'
        +       ' onchange="refmSetSpan(\'' + i.id + '\', this.value)">'
        +     '<input style="width:74px" value="' + datumStr(i) + '" placeholder="datum u,v"'
        +       ' title="Where the model\'s ORIGIN sits IN this picture, as two fractions from its'
        +       ' bottom-left corner — e.g. 0.48,0.06 for a keel just above the bottom edge, amidships.'
        +       ' Blank means the middle. A plate is almost never drawn with the subject centred, and a'
        +       ' centred plate lines up one way and floats the other."'
        +       ' onchange="refmSetDatum(\'' + i.id + '\', this.value)">'
        +     '<label style="display:flex;gap:4px;align-items:center;font-size:.58rem;color:var(--muted);'
        +       'cursor:pointer" title="This plate reads the other way round — lay it out mirrored. The file'
        +       ' itself is never changed (its lettering will read backwards in a check render; the geometry'
        +       ' is what matters).">'
        +       '<input type="checkbox"' + (i.flip ? ' checked' : '') + ' style="width:auto"'
        +       ' onchange="refmSetFlip(\'' + i.id + '\', this.checked)">mirror</label>'
        +   '</div>'
        + '</div>'
        + '<button style="align-self:flex-start" title="Remove this picture"'
        +   ' onclick="refmDelImage(\'' + i.id + '\')">&times;</button></div>';
    }).join('');
  }

  function asset() {
    var host = document.getElementById('refm-asset');
    var m = cur();
    if (!host || !m) return;
    var a = m.asset;
    host.innerHTML = (a && a.glb
      ? '<div class="asset"><p class="ok">Built ' + E(a.built) + ' — '
          + (a.dims ? a.dims[0] + ' × ' + a.dims[1] + ' × ' + a.dims[2] + ' m, ' : '')
          + (a.tris || 0) + ' triangles.<br>The assistant can drop it into the drawing with '
          + '<b>place_reference_asset</b>.</p>'
          + (a.preview_url ? '<img src="' + a.preview_url + '&t=' + Date.now() + '" alt="">' : '')
          + ((a.check_urls || []).length
             ? '<p class="ok" style="margin-top:9px">The CHECK overlays — blue is the built geometry, the lines '
               + 'underneath are your plan, in the plan\'s own view. Where they disagree, the geometry is wrong.</p>'
               + a.check_urls.map(function (c) {
                   return '<img src="' + c.url + '&t=' + Date.now() + '" alt="" title="' + E(c.title) + '">'; }).join('')
             : '')
          + ((a.inspect_urls || []).length
             ? '<p class="ok" style="margin-top:9px">The INSPECTION set — the ' + a.inspect_urls.length
               + ' pictures taken when the build finished: standpoints around it, cut planes, and views from '
               + 'INSIDE with a 1.75 m figure for scale. Hover for what each camera measured; click for full size.</p>'
               + (a.sheet_url
                  ? '<a href="' + a.sheet_url + '" target="_blank" title="all of them on one sheet">'
                    + '<img src="' + a.sheet_url + '&t=' + Date.now() + '" alt=""></a>'
                  : '')
               + '<div class="insp">'
               + a.inspect_urls.map(function (c) {
                   return '<a href="' + c.url + '" target="_blank" title="'
                     + E(c.title + (c.note ? ' — ' + c.note : '')) + '">'
                     + '<img src="' + c.url + '&t=' + Date.now() + '" alt="">'
                     + '<span>' + E(c.title) + '</span></a>'; }).join('')
               + '</div>'
             : '')
          + ((a.portfolio_sheets || []).length || (a.portfolio_urls || []).length
             ? '<p class="ok" style="margin-top:9px">The PORTFOLIO — ' + (a.portfolio_urls || []).length
               + ' pictures taken when the build finished: right round it, the orthographic set, a cut at six '
               + 'stations, a plan cut and two views from inside EVERY deck, two raking shots for curve '
               + 'fairness, and close lenses on bow, stern, entry, cabin lights and decks. The contact sheets '
               + 'come first; hover a thumb for what its camera measured.'
               + (a.portfolio_dir ? '<br>On disk: <code>' + E(a.portfolio_dir) + '</code> — open '
                                    + '<code>index.html</code> in it for all of them at full size.' : '')
               + '</p>'
               + (a.audit_findings || []).map(function (f) {
                   return '<p class="bad" style="margin-top:4px">' + E(f) + '</p>'; }).join('')
               + (a.portfolio_sheets || []).map(function (c) {
                   return '<a href="' + c.url + '" target="_blank" title="' + E(c.title) + '">'
                     + '<img src="' + c.url + '&t=' + Date.now() + '" alt=""></a>'; }).join('')
               + '<div class="insp">'
               + (a.portfolio_urls || []).map(function (c) {
                   return '<a href="' + c.url + '" target="_blank" title="'
                     + E(c.title + (c.note ? ' — ' + c.note : '')) + '">'
                     + '<img src="' + c.url + '&t=' + Date.now() + '" alt="" loading="lazy">'
                     + '<span>' + E(c.title) + '</span></a>'; }).join('')
               + '</div>'
             : '')
          + ((a.portfolio_notes || []).length
             ? a.portfolio_notes.map(function (c) {
                 return '<p class="ok" style="margin-top:6px">' + E(c.title) + ': no picture — ' + E(c.note) + '</p>';
               }).join('')
             : '')
          + ((a.inspect_notes || []).length
             ? a.inspect_notes.map(function (c) {
                 return '<p class="ok" style="margin-top:6px">' + E(c.title) + ': no picture — ' + E(c.note) + '</p>';
               }).join('')
             : '')
          + '</div>'
      : '<p class="ok">Nothing built yet.</p>')
      + '<div class="refm-row" style="margin-top:8px"><span class="sp"></span>'
      + '<button class="go" onclick="refmAsk()" title="Write the request into the chat box — it is not sent,'
      + ' so nothing is spent until you press Send">ask the assistant to build it</button></div>';
  }

  /* ── actions ────────────────────────────────────────────────────────────── */
  window.refmOpen = function () { if (S.sheet) closeSheet(); else openSheet(); };

  window.refmSetCurrent = function (id) {
    post('set_current', {m: id || ''}).then(function () { S.current = id || ''; paint(); railSync(); });
  };

  window.refmNew = function () {
    var name = window.prompt('What is it? (a name for this reference model)', 'New reference');
    if (name === null) return;
    name = String(name).trim();
    if (!name) return;
    post('create', {name: name}).then(function (d) {
      if (!d || !d.ok) { toast((d && d.error) || 'could not create it', 'bad'); return; }
      return load().then(function () { S.current = d.current; paint(); railSync(); });
    });
  };

  window.refmDelete = function () {
    var m = cur();
    if (!m) return;
    if (!window.confirm('Delete "' + m.name + '" and all ' + (m.images || []).length + ' of its pictures?')) return;
    post('delete', {m: m.id}).then(function () {
      return load().then(function () { paint(); railSync(); toast('Reference model deleted'); });
    });
  };

  window.refmSave = function () {
    var m = cur();
    if (!m) return;
    var g = function (k) { var el = document.getElementById('refm-' + k); return el ? el.value : ''; };
    post('update', {m: m.id, name: g('name'), subject: g('subject'), notes: g('notes'),
                    length_m: g('length_m'), beam_m: g('beam_m'), height_m: g('height_m')})
      .then(function (d) {
        if (!d || !d.ok) { toast((d && d.error) || 'save failed', 'bad'); return; }
        return load().then(function () { paint(); railSync(); toast('Saved'); });
      });
  };

  window.refmSetRole = function (iid, role) {
    var m = cur(); if (!m) return;
    post('set_image', {m: m.id, i: iid, role: role}).then(function () {
      return load().then(function () { pics(); });
    });
  };
  window.refmSetNote = function (iid, note) {
    var m = cur(); if (!m) return;
    post('set_image', {m: m.id, i: iid, note: note}).then(function () { return load(); });
  };
  window.refmSetSpan = function (iid, v) {
    var m = cur(); if (!m) return;
    post('set_image', {m: m.id, i: iid, span_m: v}).then(function () { return load(); });
  };
  window.refmSetDatum = function (iid, v) {
    var m = cur(); if (!m) return;
    post('set_image', {m: m.id, i: iid, datum: String(v || '0.5,0.5')}).then(function () { return load(); });
  };
  window.refmSetFlip = function (iid, on) {
    var m = cur(); if (!m) return;
    post('set_image', {m: m.id, i: iid, flip: !!on}).then(function () { return load(); });
  };
  window.refmDelImage = function (iid) {
    var m = cur(); if (!m) return;
    post('del_image', {m: m.id, i: iid}).then(function () {
      return load().then(function () { paint(); railSync(); });
    });
  };

  window.refmAsk = function () {
    var m = cur();
    if (!m) return;
    var box = document.getElementById('ar-assist-in');
    if (!box) { toast('Open the assistant panel first', 'warn'); return; }
    box.value = 'Build the reference model "' + m.name + '" as a Blender asset. Look at its pictures first, '
      + 'then build it and show me the overlay against the plans.';
    closeSheet();
    box.focus();
    toast('Request written into the chat box — press Send when you are ready');
  };

  /* ── uploading ──────────────────────────────────────────────────────────
     Downscaled in the browser before it leaves: the POST body is JSON, the
     server caps it at 24 MB, and a phone photograph is 8 MB of detail no plan
     reading will ever use. A PNG small enough to survive stays a PNG — a line
     drawing re-encoded as JPEG gets exactly the ringing you are trying to
     trace against. */
  function shrink(file) {
    return new Promise(function (res, rej) {
      var fr = new FileReader();
      fr.onerror = function () { rej(new Error('could not read ' + file.name)); };
      fr.onload = function () {
        var url = String(fr.result);
        var im = new Image();
        im.onerror = function () { rej(new Error(file.name + ' is not a picture this browser can read')); };
        im.onload = function () {
          var k = Math.min(1, MAX_EDGE / Math.max(im.width, im.height));
          if (k >= 1 && url.length < 9000000) { res(url); return; }
          var c = document.createElement('canvas');
          c.width = Math.max(1, Math.round(im.width * k));
          c.height = Math.max(1, Math.round(im.height * k));
          var g = c.getContext('2d');
          if (/^data:image\/png/.test(url)) { g.clearRect(0, 0, c.width, c.height); }
          else { g.fillStyle = '#fff'; g.fillRect(0, 0, c.width, c.height); }
          g.drawImage(im, 0, 0, c.width, c.height);
          var keepPng = /^data:image\/png/.test(url) && c.width * c.height < 3200000;
          res(c.toDataURL(keepPng ? 'image/png' : 'image/jpeg', 0.92));
        };
        im.src = url;
      };
      fr.readAsDataURL(file);
    });
  }

  function upload(files) {
    var m = cur();
    if (!m) { toast('Make a reference model first', 'warn'); return; }
    var list = [];
    for (var i = 0; i < files.length; i++) if (/^image\//.test(files[i].type)) list.push(files[i]);
    if (!list.length) { toast('Those were not pictures', 'warn'); return; }
    S.busy++;
    var done = 0, failed = 0;
    /* one at a time: the body carries the picture, and four 8 MB POSTs at once
       is how you find the request cap the hard way */
    var next = function (n) {
      if (n >= list.length) {
        S.busy--;
        return load().then(function () {
          paint(); railSync();
          toast(done + ' picture' + (done === 1 ? '' : 's') + ' added'
            + (failed ? ', ' + failed + ' refused' : ''), failed ? 'warn' : '');
        });
      }
      var f = list[n];
      return shrink(f)
        .then(function (url) { return post('add_image', {m: m.id, data: url, filename: f.name}); })
        .then(function (d) {
          if (d && d.ok) done++; else { failed++; toast((d && d.error) || ('could not add ' + f.name), 'bad'); }
        })
        .catch(function (e) { failed++; toast(e.message || String(e), 'bad'); })
        .then(function () { return next(n + 1); });
    };
    next(0);
  }

  /* ── binding ────────────────────────────────────────────────────────────── */
  var _input = null, _paste = null;
  function bind() {
    var drop = document.getElementById('refm-drop');
    if (drop) {
      if (!_input) {
        _input = document.createElement('input');
        _input.type = 'file';
        _input.multiple = true;
        _input.accept = 'image/png,image/jpeg,image/webp';
        _input.style.display = 'none';
        document.body.appendChild(_input);
        _input.addEventListener('change', function () { upload(_input.files); _input.value = ''; });
      }
      drop.onclick = function () { _input.click(); };
      drop.ondragover = function (e) { e.preventDefault(); drop.classList.add('hot'); };
      drop.ondragleave = function () { drop.classList.remove('hot'); };
      drop.ondrop = function (e) {
        e.preventDefault();
        drop.classList.remove('hot');
        if (e.dataTransfer && e.dataTransfer.files) upload(e.dataTransfer.files);
      };
    }
    if (!_paste) {
      _paste = function (e) {
        if (!S.sheet || !e.clipboardData) return;
        var items = e.clipboardData.files;
        if (items && items.length) { e.preventDefault(); upload(items); }
      };
      document.addEventListener('paste', _paste);
    }
  }
  function unbind() { /* the paste listener is cheap and gated on S.sheet */ }

  /* ── wiring ─────────────────────────────────────────────────────────────
     The rail follows the chat panel, so it is hung off arAssistRender rather
     than polled: one wrapper, and every open/close/toggle path already goes
     through it. */
  AR_EXT.ready.push(function () {
    if (window.AR && AR._refmWired) return;
    if (window.AR) AR._refmWired = 1;
    style();
    var base = window.arAssistRender;
    if (typeof base === 'function') {
      window.arAssistRender = function () { base.apply(this, arguments); try { railSync(); } catch (e) {} };
    }
    var el = ensureRail();
    if (el) {
      el.addEventListener('click', function (e) {
        var t = e.target.closest ? e.target.closest('[data-reftool]') : null;
        if (!t) return;
        if (t.getAttribute('data-reftool') === 'refmodel') window.refmOpen();
      });
    }
    /* the sheet's close button is the studio's own, so notice when it goes */
    var baseClose = window.arSheetClose;
    if (typeof baseClose === 'function') {
      window.arSheetClose = function () {
        baseClose.apply(this, arguments);
        if (S.sheet) { S.sheet = false; railSync(); }
      };
    }
    railSync();
  });
})();
