// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* drawings_sheet — the sheet layer over the 2D drawing generator (2026-09-08).
   Wires dc_sheet, dc_title, dc_rev, dc_pdf, dc_print. Nothing in
   inspection.html was edited; the family composes the drawings that
   drawings_2d produces onto a real paper page.

   DEPENDS ON drawings_2d: window.drawings2d.svg(kind, opts) ->
   {svg, w_mm, h_mm, scale, bounds, title}. Its own settings stay in
   AR.doc.ext.drawings_2d; ours are AR.doc.ext.drawings_sheet.

   CONTRACT
     window.drawings_sheet = {
       compose(opt) -> {svg, pdf, w_mm, h_mm, size, orient, views, name, ...},
       last, settings(), download(), setTitle(k, v), addRev(note, by),
       delRev(i), composeFromForm()
     }
   Units: the page is paper MILLIMETRES throughout (viewBox 0 0 w_mm h_mm,
   width="<w>mm"), and every drawing is nested at its own 1:1 mm size, so a
   plan drawn at 1:100 is still 1:100 on the page.

   TWO BODIES, ONE PAGE. `res.svg` places each drawing in a nested <svg>
   viewport and keeps drawings_2d's <pattern> hatch — that is what a browser
   and a person see. `res.pdf` is the same page with the viewports flattened to
   <g transform> and the pattern fills expanded into clipped hatch LINES,
   because svglib (the PDF converter) drops pattern fills and mis-scales a
   nested <svg> viewport by 0.75. Both come out of one composition. */
(function () {
  'use strict';

  var FAM = 'drawings_sheet';
  var EXT_BASE = '/inspect/api/architecture/ext/drawings_sheet/';

  /* ISO A sizes, PORTRAIT [w, h] in mm */
  var PAPER = { A4: [210, 297], A3: [297, 420], A2: [420, 594], A1: [594, 841] };
  var BORDER = 10;          /* page border, mm            */
  var TB_W = 180, TB_H = 60;/* title block, mm            */
  var GAP = 6;              /* between viewports, mm      */
  var CAP_H = 7;            /* caption strip under a view */
  var REV_ROW = 5;          /* revision table row, mm     */
  var TITLE_KEYS = ['project', 'client', 'drawn', 'checked', 'date', 'number', 'notes'];
  var MAX_HATCH = 4000;     /* hatch lines per expanded shape */

  function J(o) { return JSON.parse(JSON.stringify(o)); }
  function N(v, d) { v = parseFloat(v); return isFinite(v) ? v : d; }
  function R(v) { return Math.round(v * 1000) / 1000; }
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function today() { var d = new Date(); return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()); }
  function esq(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function slug(s) {
    return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 48);
  }
  function bytes(n) {
    return n < 1024 ? n + ' B' : (n < 1048576 ? (n / 1024).toFixed(1) + ' kB' : (n / 1048576).toFixed(2) + ' MB');
  }

  var DEF = {
    size: 'A3', orient: 'landscape', layout: 'auto',
    views: [{ kind: 'plan', storey: 0 }],
    title: { project: '', client: '', drawn: '', checked: '', date: '', number: '', notes: '' },
    revisions: []
  };

  /* ── the document-level setup: AR.doc.ext.drawings_sheet ───────────────── */
  function settings() {
    var doc = (window.AR && AR.doc) ? AR.doc : null;
    if (!doc) return J(DEF);
    if (!doc.ext || typeof doc.ext !== 'object') doc.ext = {};
    var s = doc.ext[FAM];
    if (!s || typeof s !== 'object') { s = J(DEF); doc.ext[FAM] = s; }
    if (!PAPER[s.size]) s.size = DEF.size;
    if (['landscape', 'portrait'].indexOf(s.orient) < 0) s.orient = DEF.orient;
    if (['auto', 'grid'].indexOf(s.layout) < 0) s.layout = DEF.layout;
    if (!Array.isArray(s.views) || !s.views.length) s.views = J(DEF.views);
    s.views = s.views.filter(function (v) { return v && typeof v === 'object'; });
    if (!s.views.length) s.views = J(DEF.views);
    if (!s.title || typeof s.title !== 'object') s.title = J(DEF.title);
    TITLE_KEYS.forEach(function (k) {
      if (typeof s.title[k] !== 'string') s.title[k] = (k === 'date' ? today() : '');
    });
    if (!s.title.date) s.title.date = today();
    if (!Array.isArray(s.revisions)) s.revisions = [];
    s.revisions = s.revisions.filter(function (r) { return r && typeof r === 'object'; });
    s.revisions.forEach(function (r, i) {
      if (typeof r.rev !== 'string' || !r.rev) r.rev = revLetter(i);
      if (typeof r.date !== 'string') r.date = today();
      if (typeof r.note !== 'string') r.note = '';
      if (typeof r.by !== 'string') r.by = '';
    });
    return s;
  }

  function revLetter(i) {
    var s = '';
    i = Math.max(0, i | 0);
    do { s = String.fromCharCode(65 + (i % 26)) + s; i = Math.floor(i / 26) - 1; } while (i >= 0);
    return s;
  }
  function paper(size, orient) {
    var p = PAPER[size] || PAPER.A3;
    return orient === 'portrait' ? [p[0], p[1]] : [p[1], p[0]];
  }

  /* ── small SVG emitters (paper mm) ─────────────────────────────────────── */
  function tx(x, y, str, size, anchor) {
    return '<text x="' + R(x) + '" y="' + R(y) + '" font-size="' + R(size)
      + '" font-family="Helvetica, Arial, sans-serif" text-anchor="' + (anchor || 'start')
      + '" fill="#000000">' + esq(str) + '</text>';
  }
  function ln(x1, y1, x2, y2, w) {
    return '<path d="M' + R(x1) + ' ' + R(y1) + 'L' + R(x2) + ' ' + R(y2)
      + '" fill="none" stroke="#000000" stroke-width="' + (w || 0.25) + '"/>';
  }
  function bxo(x, y, w, h, sw, fill) {
    return '<rect x="' + R(x) + '" y="' + R(y) + '" width="' + R(w) + '" height="' + R(h)
      + '" fill="' + (fill || 'none') + '" stroke="#000000" stroke-width="' + (sw || 0.35) + '"/>';
  }
  function cell(x, y, label, val) {
    return tx(x + 1.6, y + 3.6, label, 1.9) + tx(x + 1.6, y + 9.4, val || '\u2014', 3.2);
  }

  /* ── the hatch expander (for svglib: <pattern> fills come out empty) ─────
     Every shape filled with drawings_2d's `url(#d2hatch)` is replaced by the
     SAME shape unfilled plus a <clipPath> of itself and a <g> of 45 degree
     lines at the pattern's 2 mm spacing, clipped to it. clipPath IS supported
     by svglib, so the poche survives into the PDF. */
  function ptsOf(el, name) {
    var out = [], m, re;
    if (name === 'polygon' || name === 'polyline') {
      m = /points="([^"]*)"/.exec(el);
      if (!m) return out;
      m[1].trim().split(/\s+/).forEach(function (p) {
        var a = p.split(',');
        if (a.length === 2 && isFinite(+a[0]) && isFinite(+a[1])) out.push([+a[0], +a[1]]);
      });
      return out;
    }
    m = /\sd="([^"]*)"/.exec(el);
    if (!m) return out;
    re = /[ML]\s*(-?[\d.]+)[\s,]+(-?[\d.]+)/g;
    var g;
    while ((g = re.exec(m[1]))) out.push([+g[1], +g[2]]);
    return out;
  }
  function hatchLines(pts) {
    var x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9, i;
    for (i = 0; i < pts.length; i++) {
      if (pts[i][0] < x0) x0 = pts[i][0];
      if (pts[i][0] > x1) x1 = pts[i][0];
      if (pts[i][1] < y0) y0 = pts[i][1];
      if (pts[i][1] > y1) y1 = pts[i][1];
    }
    if (!(x1 > x0) && !(y1 > y0)) return '';
    var step = 2, out = [], n = 0;
    var cA = Math.floor((x0 + y0) / step) * step, cB = Math.ceil((x1 + y1) / step) * step;
    for (var c = cA; c <= cB && n < MAX_HATCH; c += step, n++) {
      /* the chord of x + y = c across the bounding box */
      var ax = Math.max(x0, c - y1), ay = c - ax;
      var bx = Math.min(x1, c - y0), by = c - bx;
      if (ax > bx) continue;
      if (ay < y0 || by > y1) continue;
      out.push('<path d="M' + R(ax) + ' ' + R(ay) + 'L' + R(bx) + ' ' + R(by)
        + '" fill="none" stroke="#000000" stroke-width="0.13"/>');
    }
    return out.join('');
  }
  function expandHatch(inner, tag) {
    var n = 0;
    return inner.replace(/<(polygon|path)\b[^>]*\/>/g, function (el, nm) {
      if (el.indexOf('url(#d2hatch)') < 0) return el;
      var pts = ptsOf(el, nm);
      var flat = el.replace('url(#d2hatch)', 'none');
      if (pts.length < 3) return flat;
      var id = 'dsclip_' + tag + '_' + (n++);
      var solid = el.replace(/fill="[^"]*"/, 'fill="#000000"')
        .replace(/stroke="[^"]*"/, 'stroke="none"')
        .replace(/stroke-width="[^"]*"/, 'stroke-width="0"');
      return '<clipPath id="' + id + '">' + solid + '</clipPath>' + flat
        + '<g clip-path="url(#' + id + ')">' + hatchLines(pts) + '</g>';
    });
  }

  /* ── one drawing from drawings_2d ──────────────────────────────────────── */
  function viewSvg(v) {
    var D2 = window.drawings2d;
    var k = String((v && v.kind) || 'plan').toLowerCase(), o = {};
    if (k === 'plan') o.storey = Math.round(N(v.storey, 0));
    else if (k === 'elevation' || k === 'elev') o.elev = String(v.elev || 'front');
    else { o.dir = (v.dir === 'z' || v.z != null) ? 'z' : 'x'; if (v[o.dir] != null) o[o.dir] = N(v[o.dir], 0); }
    return D2.svg(k, o);
  }
  function innerOf(svg) {
    var i = svg.indexOf('>'), j = svg.lastIndexOf('</svg>');
    return (i < 0 || j < 0) ? '' : svg.slice(i + 1, j);
  }
  function uniq(inner, tag) {
    return inner.split('d2hatch').join('d2hatch_' + tag).split('d2bg').join('d2bg_' + tag);
  }
  function shortTitle(t) { return String(t || 'Drawing').replace(/\s+\u2014\s+1:\d+\s*$/, ''); }

  /* ── the title block: 180 x 60 mm, bottom right ────────────────────────── */
  function titleBlock(s, W, H, drawTitle, scales) {
    var x = W - BORDER - TB_W, y = H - BORDER - TB_H, t = s.title, o = [];
    var rows = [0, 12, 24, 36, 48, 60];
    var rev = s.revisions.length ? s.revisions[s.revisions.length - 1].rev : '\u2014';
    o.push(bxo(x, y, TB_W, TB_H, 0.5, '#ffffff'));
    for (var i = 1; i < rows.length - 1; i++) o.push(ln(x, y + rows[i], x + TB_W, y + rows[i], 0.25));
    /* the wordmark strip */
    o.push(tx(x + 3, y + 8.4, 'ZYGOMATIC', 5.4));
    o.push(tx(x + TB_W - 3, y + 8.4, 'ARCHITECTURE STUDIO', 2.6, 'end'));
    /* project | client */
    o.push(ln(x + 120, y + rows[1], x + 120, y + rows[2], 0.25));
    o.push(cell(x, y + rows[1], 'PROJECT', t.project));
    o.push(cell(x + 120, y + rows[1], 'CLIENT', t.client));
    /* drawing title (+ notes) */
    o.push(cell(x, y + rows[2], 'DRAWING TITLE', drawTitle));
    if (t.notes) o.push(tx(x + 1.6, y + rows[2] + 11.4, t.notes, 2.1));
    /* scale | date | revision */
    o.push(ln(x + 60, y + rows[3], x + 60, y + rows[5], 0.25));
    o.push(ln(x + 120, y + rows[3], x + 120, y + rows[5], 0.25));
    o.push(cell(x, y + rows[3], 'SCALE', scales));
    o.push(cell(x + 60, y + rows[3], 'DATE', t.date));
    o.push(cell(x + 120, y + rows[3], 'REVISION', rev));
    /* drawn | checked | number */
    o.push(cell(x, y + rows[4], 'DRAWN', t.drawn));
    o.push(cell(x + 60, y + rows[4], 'CHECKED', t.checked));
    o.push(cell(x + 120, y + rows[4], 'DRAWING No', t.number));
    return o.join('');
  }

  /* ── the revision table, growing upward from the title block ───────────── */
  function revHeight(s) { return s.revisions.length ? REV_ROW * (s.revisions.length + 1) : 0; }
  function revTable(s, W, H) {
    var revs = s.revisions;
    if (!revs.length) return '';
    var h = revHeight(s), x = W - BORDER - TB_W, y = H - BORDER - TB_H - h;
    var cols = [0, 12, 44, 150, TB_W], o = [bxo(x, y, TB_W, h, 0.35, '#ffffff')], i;
    for (i = 1; i <= revs.length; i++) o.push(ln(x, y + REV_ROW * i, x + TB_W, y + REV_ROW * i, 0.18));
    for (i = 1; i < cols.length - 1; i++) o.push(ln(x + cols[i], y, x + cols[i], y + h, 0.18));
    ['REV', 'DATE', 'DESCRIPTION', 'BY'].forEach(function (t, k) { o.push(tx(x + cols[k] + 1.2, y + 3.6, t, 2.0)); });
    revs.slice().reverse().forEach(function (r, k) {
      var ry = y + REV_ROW * (k + 1) + 3.6;
      [r.rev, r.date, r.note, r.by].forEach(function (t, c) { o.push(tx(x + cols[c] + 1.2, ry, t, 2.4)); });
    });
    return o.join('');
  }

  /* ── compose ───────────────────────────────────────────────────────────── */
  function compose(opt) {
    var D2 = window.drawings2d;
    if (!D2 || typeof D2.svg !== 'function') {
      arToast('The 2D drawing generator (drawings_2d) is not loaded, so there is nothing to lay out.', 'bad');
      return null;
    }
    opt = (opt && typeof opt === 'object') ? opt : {};
    var s = settings();
    arPush();
    if (opt.size && PAPER[String(opt.size).toUpperCase()]) s.size = String(opt.size).toUpperCase();
    if (opt.orient) s.orient = String(opt.orient) === 'portrait' ? 'portrait' : 'landscape';
    if (opt.layout) s.layout = String(opt.layout) === 'grid' ? 'grid' : 'auto';
    if (Array.isArray(opt.views) && opt.views.length) s.views = J(opt.views);
    s = settings();
    arDirty(true);

    var pp = paper(s.size, s.orient), W = pp[0], H = pp[1];
    var bandH = TB_H + revHeight(s) + 4;
    var cx0 = BORDER + 2, cy0 = BORDER + 2;
    var availW = W - 2 * BORDER - 4, availH = H - 2 * BORDER - 4 - bandH;

    var items = s.views.map(function (v, i) {
      var r = viewSvg(v);
      return { v: v, r: r, area: r.w_mm * r.h_mm, ord: i };
    });
    /* largest first, left to right, wrapping */
    var order = items.slice().sort(function (a, b) { return b.area - a.area || a.ord - b.ord; });
    var cx = cx0, cy = cy0, rowH = 0, placed = [];
    order.forEach(function (it, n) {
      var f = 1, tries = 0;
      while ((it.r.w_mm * f > availW || it.r.h_mm * f + CAP_H > availH) && tries < 4) { f /= 2; tries++; }
      var w = it.r.w_mm * f, h = it.r.h_mm * f;
      if (cx > cx0 && cx + w > cx0 + availW) { cx = cx0; cy += rowH + GAP; rowH = 0; }
      it.x = cx; it.y = cy; it.w = w; it.h = h; it.f = f; it.tag = 'v' + n;
      cx += w + GAP; rowH = Math.max(rowH, h + CAP_H);
      placed.push(it);
    });

    var bodyN = [], bodyG = [];
    placed.forEach(function (it) {
      var raw = innerOf(it.r.svg);
      var nested = uniq(raw, it.tag);
      var flat = uniq(expandHatch(raw, it.tag), it.tag);
      var eff = Math.round(it.r.scale / it.f);
      var cap = shortTitle(it.r.title) + ' \u2014 1:' + eff
        + (it.f < 1 ? '  (halved ' + Math.round(Math.log(1 / it.f) / Math.LN2) + '\u00d7 to fit the sheet)' : '');
      var frame = bxo(it.x, it.y, it.w, it.h, 0.13) + tx(it.x, it.y + it.h + 4.4, cap, 3);
      bodyN.push('<svg x="' + R(it.x) + '" y="' + R(it.y) + '" width="' + R(it.w) + '" height="' + R(it.h)
        + '" viewBox="0 0 ' + R(it.r.w_mm) + ' ' + R(it.r.h_mm) + '" data-view="' + it.tag + '">'
        + nested + '</svg>' + frame);
      bodyG.push('<g transform="translate(' + R(it.x) + ',' + R(it.y) + ') scale(' + R(it.f) + ')" data-view="'
        + it.tag + '">' + flat + '</g>' + frame);
      it.eff = eff;
    });

    var drawTitle = placed.map(function (it) { return shortTitle(it.r.title); }).join(' + ');
    var seen = {}, scales = [];
    placed.forEach(function (it) { if (!seen[it.eff]) { seen[it.eff] = 1; scales.push('1:' + it.eff); } });
    var blocks = revTable(s, W, H) + titleBlock(s, W, H, drawTitle, scales.join(', '));
    var chrome = '<rect x="0" y="0" width="' + R(W) + '" height="' + R(H) + '" fill="#ffffff" stroke="none"/>'
      + bxo(BORDER, BORDER, W - 2 * BORDER, H - 2 * BORDER, 0.5);
    var head = '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="' + R(W) + 'mm" height="' + R(H)
      + 'mm" viewBox="0 0 ' + R(W) + ' ' + R(H) + '">';

    var res = {
      svg: head + chrome + bodyN.join('') + blocks + '</svg>',
      pdf: head + chrome + bodyG.join('') + blocks + '</svg>',
      w_mm: W, h_mm: H, size: s.size, orient: s.orient,
      title_line: drawTitle, scales: scales.join(', '),
      rev: s.revisions.length ? s.revisions[s.revisions.length - 1].rev : '',
      views: placed.map(function (it) {
        return {
          kind: String(it.v.kind || 'plan'), title: it.r.title, scale: it.r.scale, eff: it.eff,
          reduced: it.f < 1, x_mm: R(it.x), y_mm: R(it.y), w_mm: R(it.w), h_mm: R(it.h)
        };
      }),
      name: slug(s.title.number || s.title.project || (AR.doc && AR.doc.name) || 'sheet') || 'sheet'
    };
    SH.last = res;
    return res;
  }

  /* ── the preview sheet a person reads ──────────────────────────────────── */
  function preview(res) {
    if (!res) return;
    var shrunk = res.svg.replace('<svg ', '<svg style="width:100%;height:auto;display:block" ');
    arSheet('Sheet \u2014 ' + res.size + ' ' + res.orient,
      '<div style="max-height:52vh;overflow:auto;background:#fff;padding:6px;border-radius:4px">' + shrunk + '</div>'
      + arRows([
        ['paper', res.size + ' ' + res.orient + ' \u2014 ' + res.w_mm + ' \u00d7 ' + res.h_mm + ' mm'],
        ['views', res.views.map(function (v) {
          return esc(v.title) + ' \u2014 1:' + v.eff + (v.reduced ? ' <b>reduced to fit</b>' : '');
        }).join('<br>') || '\u2014'],
        ['title', esc(res.title_line || '\u2014')],
        ['revision', res.rev ? esc(res.rev) : '\u2014']])
      + '<div style="margin-top:8px"><button onclick="drawings_sheet.download()">Download SVG</button> '
      + '<button onclick="arTool(\'dc_pdf\')">PDF</button> '
      + '<button onclick="arTool(\'dc_print\')">Print</button></div>');
  }

  /* ── the public object ─────────────────────────────────────────────────── */
  var SH = window.drawings_sheet = window.drawings_sheet || {};
  SH.settings = settings;
  SH.compose = compose;
  SH.paper = paper;
  SH.revLetter = revLetter;
  SH._expandHatch = expandHatch;
  SH._PAPER = PAPER;
  SH.download = function () {
    var res = SH.last || compose({});
    if (!res) return;
    arDownload(new Blob([res.svg], { type: 'image/svg+xml' }), res.name + '-' + res.size + '.svg');
    arToast('Sheet saved as <b>' + esc(res.name + '-' + res.size + '.svg') + '</b>.');
  };
  SH.current = function () { return SH.last || compose({}); };

  /* the option form of dc_sheet */
  SH.VIEW_CHOICES = [
    ['plan0', 'Plan \u2014 ground storey', { kind: 'plan', storey: 0 }],
    ['plan1', 'Plan \u2014 first storey', { kind: 'plan', storey: 1 }],
    ['elev_front', 'Elevation \u2014 front', { kind: 'elevation', elev: 'front' }],
    ['elev_back', 'Elevation \u2014 back', { kind: 'elevation', elev: 'back' }],
    ['elev_left', 'Elevation \u2014 left', { kind: 'elevation', elev: 'left' }],
    ['elev_right', 'Elevation \u2014 right', { kind: 'elevation', elev: 'right' }],
    ['sect_x', 'Section \u2014 through the middle on x', { kind: 'section', dir: 'x' }],
    ['sect_z', 'Section \u2014 through the middle on z', { kind: 'section', dir: 'z' }]
  ];
  function sameView(a, b) {
    return String(a.kind || '') === String(b.kind || '')
      && String(a.storey == null ? '' : a.storey) === String(b.storey == null ? '' : b.storey)
      && String(a.elev || '') === String(b.elev || '')
      && String(a.dir || '') === String(b.dir || '');
  }
  function picker() {
    var s = settings();
    var boxes = SH.VIEW_CHOICES.map(function (c) {
      var on = s.views.some(function (v) { return sameView(v, c[2]); });
      return '<label style="display:block;margin:2px 0"><input type="checkbox" class="ds-view" value="' + c[0] + '"'
        + (on ? ' checked' : '') + '> ' + c[1] + '</label>';
    }).join('');
    var sizes = Object.keys(PAPER).map(function (k) {
      return '<option value="' + k + '"' + (s.size === k ? ' selected' : '') + '>' + k + ' ('
        + PAPER[k][0] + ' \u00d7 ' + PAPER[k][1] + ' mm)</option>';
    }).join('');
    var ors = ['landscape', 'portrait'].map(function (k) {
      return '<option value="' + k + '"' + (s.orient === k ? ' selected' : '') + '>' + k + '</option>';
    }).join('');
    arSheet('Sheet layout', arRows([
      ['paper size', '<select id="ds-size">' + sizes + '</select>'],
      ['orientation', '<select id="ds-orient">' + ors + '</select>'],
      ['drawings on the sheet', boxes]])
      + '<div style="margin-top:8px"><button onclick="drawings_sheet.composeFromForm()">Compose the sheet</button></div>');
  }
  SH.composeFromForm = function () {
    var picked = [];
    Array.prototype.forEach.call(document.querySelectorAll('input.ds-view'), function (el) {
      if (!el.checked) return;
      SH.VIEW_CHOICES.forEach(function (c) { if (c[0] === el.value) picked.push(J(c[2])); });
    });
    var sz = document.getElementById('ds-size'), or = document.getElementById('ds-orient');
    if (!picked.length) { arToast('Tick at least one drawing to put on the sheet.', 'warn'); return; }
    var res = compose({ size: sz ? sz.value : null, orient: or ? or.value : null, views: picked });
    preview(res);
    return res;
  };

  /* the title block form */
  SH.setTitle = function (k, v) {
    if (TITLE_KEYS.indexOf(k) < 0) return;
    var s = settings();
    arPush(); s.title[k] = String(v == null ? '' : v); arDirty(true);
    arToast('Title block: ' + k + ' = ' + esc(s.title[k] || '\u2014') + '.');
  };
  function titleForm() {
    var s = settings();
    arSheet('Title block', arRows(TITLE_KEYS.map(function (k) {
      return [k, '<input type="text" value="' + esq(s.title[k]) + '" style="width:22em"'
        + ' onchange="drawings_sheet.setTitle(\'' + k + '\', this.value)">'];
    }))
      + '<div style="margin-top:8px"><button onclick="drawings_sheet.recompose()">Re-compose the sheet</button></div>');
  }
  SH.recompose = function () { var r = compose({}); preview(r); return r; };

  /* revisions */
  SH.addRev = function (note, by) {
    var s = settings();
    arPush();
    var r = { rev: revLetter(s.revisions.length), date: today(), note: String(note == null ? '' : note), by: String(by == null ? '' : by) };
    s.revisions.push(r); arDirty(true);
    arToast('Revision <b>' + esc(r.rev) + '</b> added \u2014 ' + esc(r.note || 'no description') + '.');
    return r;
  };
  SH.delRev = function (i) {
    var s = settings();
    i = i | 0;
    if (i < 0 || i >= s.revisions.length) return;
    arPush();
    var gone = s.revisions.splice(i, 1)[0];
    s.revisions.forEach(function (r, k) { r.rev = revLetter(k); });
    arDirty(true);
    arToast('Revision ' + esc(gone.rev) + ' deleted; the letters were renumbered.');
    revList();
  };
  function revList() {
    var s = settings();
    var rows = s.revisions.map(function (r, i) {
      return '<tr><td>' + esc(r.rev) + '</td><td>' + esc(r.date) + '</td><td>' + esc(r.note)
        + '</td><td>' + esc(r.by) + '</td><td><button class="ds-rev-del" onclick="drawings_sheet.delRev(' + i
        + ')">Delete</button></td></tr>';
    }).join('');
    arSheet('Revisions', '<table class="ar-tbl"><tr><td>rev</td><td>date</td><td>description</td><td>by</td><td></td></tr>'
      + (rows || '<tr><td colspan="5">No revisions yet.</td></tr>') + '</table>'
      + '<div style="margin-top:8px"><button onclick="drawings_sheet.recompose()">Re-compose the sheet</button></div>');
  }
  SH.revList = revList;

  /* ── PDF ───────────────────────────────────────────────────────────────── */
  SH.pdf = function (opt) {
    var res = (opt && typeof opt === 'object' && (opt.size || opt.orient || opt.views))
      ? compose(opt) : (SH.last || compose({}));
    if (!res) return Promise.reject(new Error('nothing to export'));
    var fname = res.name + '-' + res.size + '.pdf';
    return fetch(EXT_BASE + 'pdf', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ svg: res.pdf, w_mm: res.w_mm, h_mm: res.h_mm, name: res.name + '-' + res.size })
    }).then(function (r) {
      if (!r.ok) return r.text().then(function (t) { throw new Error(t.slice(0, 200)); });
      return r.blob();
    }).then(function (b) {
      arDownload(b, fname);
      arToast('Vector PDF <b>' + esc(fname) + '</b> \u2014 ' + res.size + ' ' + res.orient
        + ', ' + bytes(b.size) + '.');
      return b;
    })['catch'](function (e) {
      arToast('PDF export failed: ' + esc(String((e && e.message) || e)), 'bad');
      throw e;
    });
  };

  /* ── print ─────────────────────────────────────────────────────────────── */
  function printDoc(res) {
    return '<!DOCTYPE html><html><head><meta charset="utf-8"><title>'
      + esq(res.title_line || 'Sheet') + '</title><style>@page { size: ' + res.w_mm + 'mm ' + res.h_mm
      + 'mm; margin: 0 } html, body { margin: 0; padding: 0; background: #fff } svg { display: block }'
      + '</style></head><body>' + res.svg + '</body></html>';
  }
  SH.print = function () {
    var res = SH.last || compose({});
    if (!res) return null;
    var html = printDoc(res), w = null;
    try { w = window.open('', '_blank'); } catch (e) { w = null; }
    if (w && w.document) {
      try {
        w.document.open(); w.document.write(html); w.document.close();
        var go = function () { try { w.focus(); w.print(); } catch (e2) { } };
        if (w.document.readyState === 'complete') setTimeout(go, 60); else w.onload = go;
        arToast('Printing the ' + res.size + ' ' + res.orient + ' sheet in a <b>new window</b> \u2014 print at 100 % '
          + '(no page scaling) for a true ' + res.scales + ' drawing.');
        return { path: 'window', w_mm: res.w_mm, h_mm: res.h_mm };
      } catch (e3) { w = null; }
    }
    /* headless / popup-blocked: the same page in a frame on the stage */
    var stage = document.getElementById('ar-stage') || document.body;
    var old = stage.querySelector('iframe.ds-print');
    if (old && old.parentNode) old.parentNode.removeChild(old);
    var f = document.createElement('iframe');
    f.className = 'ds-print';
    f.setAttribute('data-paper', res.w_mm + 'x' + res.h_mm);
    f.style.cssText = 'position:absolute;left:-10000px;top:0;width:' + res.w_mm + 'mm;height:' + res.h_mm + 'mm;border:0';
    stage.appendChild(f);
    var d = f.contentDocument || (f.contentWindow && f.contentWindow.document);
    if (d) { d.open(); d.write(html); d.close(); }
    setTimeout(function () { try { f.contentWindow.focus(); f.contentWindow.print(); } catch (e4) { } }, 80);
    arToast('The new window was blocked, so the ' + res.size + ' ' + res.orient
      + ' sheet is printing from an <b>embedded frame</b> \u2014 print at 100 % for a true '
      + res.scales + ' drawing.');
    return { path: 'iframe', w_mm: res.w_mm, h_mm: res.h_mm };
  };

  /* ── the five icons ────────────────────────────────────────────────────── */
  AR_EXT.tools.dc_sheet = {
    assist: 1,
    tip: 'Sheet layout \u2014 several drawings, each at its own scale, on one ISO page with a border and a title block',
    act: function (opt) {
      if (opt && typeof opt === 'object') {
        var res = compose(opt);
        preview(res);
        return res ? { size: res.size, orient: res.orient, w_mm: res.w_mm, h_mm: res.h_mm, views: res.views } : null;
      }
      picker();
      return null;
    }
  };
  AR_EXT.tools.dc_title = {
    assist: 1,
    tip: 'Title block \u2014 project, client, drawing title, scale, date, drawn/checked, drawing number and revision',
    act: function (opt) {
      if (opt && typeof opt === 'object') {
        var s = settings();
        arPush();
        TITLE_KEYS.forEach(function (k) { if (opt[k] != null) s.title[k] = String(opt[k]); });
        settings(); arDirty(true);
        arToast('Title block updated \u2014 <b>' + esc(s.title.project || '(no project)') + '</b>'
          + (s.title.number ? ', drawing ' + esc(s.title.number) : '') + '.');
        return J(s.title);
      }
      titleForm();
      return J(settings().title);
    }
  };
  AR_EXT.tools.dc_rev = {
    assist: 1,
    tip: 'Revisions \u2014 the revision table on the sheet: what changed since the last issue, and by whom',
    act: function (opt) {
      var added = null;
      if (opt && typeof opt === 'object') {
        if (opt.add && typeof opt.add === 'object') added = SH.addRev(opt.add.note, opt.add.by);
        else if (opt.note != null) added = SH.addRev(opt.note, opt.by);
        if (opt.list) revList();
      } else {
        var note = prompt('What changed in this revision? (blank just lists them)', '');
        if (note != null && String(note).trim() !== '') {
          var by = prompt('Revised by (initials)?', settings().title.drawn || '');
          added = SH.addRev(note, by == null ? '' : by);
        }
      }
      revList();
      return added ? J(added) : J(settings().revisions);
    }
  };
  AR_EXT.tools.dc_pdf = {
    assist: 1,
    tip: 'PDF \u2014 export the composed sheet as a true-size vector PDF',
    act: function (opt) { return SH.pdf(opt); }
  };
  AR_EXT.tools.dc_print = {
    assist: 1,
    tip: 'Print \u2014 send the composed sheet to paper at a true scale (the page is set to the paper size, no scaling)',
    act: function () { return SH.print(); }
  };
})();
