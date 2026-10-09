// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Metrics tab v14 (2026-10-08)
 * Overview | Analytics | Pipelines | Characters | LLM & costs | Quota | Quality | System |
 * Agents | Agent Zero | Test Data | Capabilities | Lineage
 *
 * Data: GET /api/metrics/hub/<section>?days=N (metrics_hub.py). Status rules, test-row
 * exclusion and source coverage are decided there and shipped in the payload; this file
 * only draws. Charts are inline SVG built after insertion so they can measure their
 * container, and every chart carries a table twin. Payload strings are escaped (esc) in
 * markup and set with textContent in tooltips.
 */
(function () {
    'use strict';

    var RANGE_KEY = 'zyg.metrics.range';
    var TAB_KEY = 'zyg.metrics.tab';
    var TABS = ['overview', 'analytics', 'pipelines', 'characters', 'llm', 'quota', 'quality', 'system', 'agents', 'zero', 'test_data', 'mechanics', 'capabilities', 'stack_lineage', 'expansion'];
    var TAB_LABELS = { overview: 'Overview', analytics: 'Analytics', pipelines: 'Pipelines', characters: 'Characters', llm: 'LLM & costs', quota: 'Quota',
        quality: 'Quality', system: 'System', agents: 'Agents', zero: 'Agent Zero', test_data: 'Test Data', mechanics: 'Mechanics', capabilities: 'Capabilities',
        stack_lineage: 'Lineage', expansion: 'Expansion' };
    var POLL_MS = { system: 15000, overview: 60000, quota: 60000, analytics: 30000, zero: 30000, test_data: 30000, capabilities: 60000, expansion: 120000 };
    // Tabs the time range actually changes. `capabilities` is not one: its collector
    // ignores ?days= (a capability sheet is what is true now, not a series), so showing
    // the picker there offered a control that did nothing.
    // `stack_lineage` ignores ?days= for the same reason as `capabilities`: a lineage is
    // everything up to now, not a window, so the range picker would do nothing.
    // `expansion` is a census of what is on disk now, so the range picker would do nothing there either.
    var NO_RANGE = { capabilities: true, mechanics: true, stack_lineage: true, expansion: true };
    function rangeApplies(tab) { return !NO_RANGE[tab]; }

    // Mechanics (2026-09-30) came in from its own dashboard tab. Its markup ships with the
    // page (_panel_mechanics.html, nested in #metrics-content-mechanics) and
    // dashboard_tab_mechanics.js fills it, so there is no /api/metrics/hub/mechanics to
    // fetch: this subtab is mounted, not loaded. Its render() binds with addEventListener,
    // so it must run exactly once.
    var LOCAL = { mechanics: true };
    var _mounted = {};
    var _mountTries = {};
    function mountLocal(tab) {
        if (!LOCAL[tab] || _mounted[tab]) return;
        var mod = tab === 'mechanics' ? window.DashboardTabMechanics : null;
        if (!mod || !mod.render) {
            // dashboard_tab_mechanics.js is a later `defer` script than this one, so on a
            // first paint straight into Mechanics it may not be parsed yet. Wait for it
            // instead of leaving the panel unbound; give up after a second.
            _mountTries[tab] = (_mountTries[tab] || 0) + 1;
            if (_mountTries[tab] <= 20) setTimeout(function () { mountLocal(tab); }, 50);
            return;
        }
        _mounted[tab] = true;          // render() binds with addEventListener: once only
        mod.render(byId('panel-mechanics'));
    }

    // Categorical slots in fixed order (dataviz reference palette, validated on #fff: worst adjacent
    // CVD dE 9.1, normal-vision 19.6). Colour follows the entity, never its rank.
    var SLOT = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7'];
    var OTHER = '#a9a79f';
    var FAMILY_COLOR = { scholarly: SLOT[0], kidsmusic: SLOT[1], characters: SLOT[2], remix_ai: SLOT[3],
        tokitoki: SLOT[4], storyteller: SLOT[5], crime: SLOT[6], other: OTHER };
    var PROVIDER_COLOR = { anthropic_api: SLOT[0], local: SLOT[1], claude_code: SLOT[2], openai_api: SLOT[3], other: OTHER };
    var DEVICE_COLOR = { gpu: SLOT[0], cpu: SLOT[1] };
    // Status colours are reserved for state and always ship with an icon + label.
    var STATUS = {
        completed: { color: '#0ca30c', ink: '#fff', icon: '✓', label: 'Completed' },
        failed: { color: '#d03b3b', ink: '#fff', icon: '✕', label: 'Failed' },
        open: { color: '#2a78d6', ink: '#fff', icon: '▸', label: 'In progress' },
        stale: { color: '#fab219', ink: '#3d2a00', icon: '!', label: 'Stale' },
        cancelled: { color: '#bdbbb3', ink: '#2b2a27', icon: '–', label: 'Cancelled' },
        unknown: { color: '#e3e1da', ink: '#52514e', icon: '?', label: 'Unrecorded' }
    };
    var STATUS_ORDER = ['completed', 'failed', 'open', 'stale', 'cancelled', 'unknown'];
    var SEVERITY = {
        critical: { color: '#d03b3b', ink: '#fff', icon: '✕', label: 'Critical' },
        serious: { color: '#ec835a', ink: '#fff', icon: '!', label: 'Serious' },
        warning: { color: '#fab219', ink: '#3d2a00', icon: '!', label: 'Warning' },
        good: { color: '#0ca30c', ink: '#fff', icon: '✓', label: 'OK' },
        neutral: { color: '#e3e1da', ink: '#52514e', icon: '–', label: '' }
    };
    var SERVICE_STATE = {
        ok: ['good', 'Running'], orphan: ['critical', 'Orphaned'], failed: ['critical', 'Failed'],
        degraded: ['serious', 'Port closed'], down: ['serious', 'Down'], starting: ['warning', 'Starting'],
        stopped: ['neutral', 'Stopped'], unknown: ['warning', 'Unknown']
    };

    var _range = 30;
    var _tab = 'overview';
    var _cache = {};
    var _inflight = {};
    var _charts = [];
    var _tips = [];
    var _pollTimer = null;
    var _bound = false;
    var _stamp = {};        // tab:range -> fingerprint of the last payload seen

    // ── formatting ───────────────────────────────────────────────────────────
    function byId(id) { return document.getElementById(id); }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }
    function store(key, value) {
        try {
            if (value === undefined) return localStorage.getItem(key);
            localStorage.setItem(key, value);
        } catch (e) { /* storage blocked: conveniences only */ }
        return null;
    }
    function n0(v) { return v == null ? '—' : Number(v).toLocaleString(); }
    function compact(v) {
        if (v == null) return '—';
        v = Number(v);
        var a = Math.abs(v);
        if (a >= 1e9) return (v / 1e9).toFixed(1) + 'B';
        if (a >= 1e6) return (v / 1e6).toFixed(1) + 'M';
        if (a >= 1e4) return Math.round(v / 1e3) + 'K';
        if (a >= 1e3) return (v / 1e3).toFixed(1) + 'K';
        return String(Math.round(v * 100) / 100);
    }
    function usd(v) {
        if (v == null) return '—';
        v = Number(v);
        if (v === 0) return '$0';
        if (Math.abs(v) < 0.01) return '$' + v.toFixed(4);
        if (Math.abs(v) < 100) return '$' + v.toFixed(2);
        return '$' + Math.round(v).toLocaleString();
    }
    function pad2(x) { return (x < 10 ? '0' : '') + x; }
    function dur(s) {
        if (s == null) return '—';
        s = Number(s);
        if (s < 1) return '<1s';
        if (s < 60) return Math.round(s) + 's';
        if (s < 3600) return Math.floor(s / 60) + 'm ' + pad2(Math.round(s % 60)) + 's';
        if (s < 86400) return Math.floor(s / 3600) + 'h ' + pad2(Math.floor((s % 3600) / 60)) + 'm';
        return (s / 86400).toFixed(1) + 'd';
    }
    function when(iso) { return iso ? String(iso).replace('T', ' ').slice(0, 16) : '—'; }
    function agoSeconds(s) {
        if (s == null) return '—';
        if (s < 90) return 'just now';
        if (s < 5400) return Math.round(s / 60) + ' min ago';
        if (s < 129600) return Math.round(s / 3600) + ' h ago';
        return Math.round(s / 86400) + ' d ago';
    }
    function ago(iso) {
        var t = iso ? Date.parse(iso) : NaN;
        return isNaN(t) ? '—' : agoSeconds((Date.now() - t) / 1000);
    }
    function pct(v, digits) {
        if (v == null || isNaN(v)) return '—';
        v = Number(v);
        return v.toFixed(digits != null ? digits : (Math.abs(v) < 10 && v % 1 ? 1 : 0)) + '%';
    }
    function rangeLabel() { return _range ? 'last ' + _range + ' days' : 'all time'; }
    function plural(n, one, many) { return n0(n) + ' ' + (Number(n) === 1 ? one : (many || one + 's')); }

    // ── components (HTML strings) ────────────────────────────────────────────
    function tile(label, value, sub, detail) {
        var inner = '<div class="mh-tile-label">' + esc(label) + '</div>' +
            '<div class="mh-tile-value">' + esc(value == null ? '—' : value) + '</div>' +
            (sub ? '<div class="mh-tile-sub">' + esc(sub) + '</div>' : '');
        // A tile with a detail token is a real button: click or Enter opens the rows behind it.
        if (!detail) return '<div class="mh-tile">' + inner + '</div>';
        return '<button type="button" class="mh-tile mh-tile-click" data-qdetail="' + esc(detail) + '">' +
            inner + '<span class="mh-tile-go" aria-hidden="true">details →</span></button>';
    }
    function card(title, body, aside, cls) {
        return '<section class="mh-card' + (cls ? ' ' + cls : '') + '"><header class="mh-card-head"><h4>' + title + '</h4>' +
            (aside ? '<span class="mh-card-aside">' + esc(aside) + '</span>' : '') + '</header>' + body + '</section>';
    }
    function table(cols, rows, empty) {
        if (!rows.length) return '<p class="mh-empty">' + esc(empty || 'Nothing recorded in this range.') + '</p>';
        return '<div class="mh-table-wrap"><table class="mh-table"><thead><tr>' +
            cols.map(function (c) { return '<th' + (c.r ? ' class="num"' : '') + '>' + esc(c.t) + '</th>'; }).join('') +
            '</tr></thead><tbody>' + rows.map(function (r) {
                // A row is either an array of (trusted) cell HTML, or {cells, detail} — the
                // detail token makes the whole row clickable and the first cell a button.
                var cells = r, token = null;
                if (r && !Array.isArray(r)) { cells = r.cells || []; token = r.detail || null; }
                return '<tr' + (token ? ' class="mh-row-click" data-qdetail="' + esc(token) + '"' : '') + '>' +
                    cells.map(function (cell, i) {
                        var html = (cell && typeof cell === 'object') ? cellHtml(cell) : cell;
                        if (token && i === 0) {
                            html = '<button type="button" class="mh-rowbtn" data-qdetail="' + esc(token) + '">' +
                                html + '</button>';
                        }
                        return '<td' + (cols[i] && cols[i].r ? ' class="num"' : '') + '>' + html + '</td>';
                    }).join('') + '</tr>';
            }).join('') + '</tbody></table></div>';
    }

    // A detail-payload cell: "text", or {v, tone, muted, sub, detail}. Everything here is
    // server data, so every piece is escaped — unlike the trusted cell HTML above.
    function cellHtml(c) {
        if (c == null) return '<span class="mh-muted">—</span>';
        if (typeof c !== 'object') return esc(c === '' ? '—' : c);
        var text = (c.v == null || c.v === '') ? '—' : String(c.v);
        var html = c.tone ? sevPill(c.tone, text) : c.muted ? '<span class="mh-muted">' + esc(text) + '</span>' : esc(text);
        if (c.sub) html += ' <em class="mh-muted">' + esc(c.sub) + '</em>';
        if (c.detail) html = '<button type="button" class="mh-rowbtn" data-qdetail="' + esc(c.detail) + '">' + html + '</button>';
        return html;
    }

    // A table from a detail payload: same look as table(), but the cells are data.
    function detailTable(t) {
        var cols = t.columns || [];
        if (!t.rows || !t.rows.length) return '<p class="mh-empty">' + esc(t.empty || 'Nothing recorded.') + '</p>';
        return table(cols, t.rows.map(function (r) {
            var cells = Array.isArray(r) ? r : (r.cells || []);
            var out = cells.map(cellHtml);
            return (!Array.isArray(r) && r.detail) ? { cells: out, detail: r.detail } : out;
        }));
    }
    function mark(def, label, extra) {
        return '<span class="mh-pill"><i style="background:' + def.color + ';color:' + def.ink + '">' + def.icon + '</i>' +
            esc(label) + (extra ? ' <em>' + esc(extra) + '</em>' : '') + '</span>';
    }
    function pill(status, extra) { var s = STATUS[status] || STATUS.unknown; return mark(s, s.label, extra); }
    function sevPill(sev, label) { var s = SEVERITY[sev] || SEVERITY.warning; return mark(s, label || s.label); }
    function swatch(color) { return '<span class="mh-swatch" style="background:' + color + '"></span>'; }
    function note(text) { return '<p class="mh-note">' + esc(text) + '</p>'; }
    function notes(list) {
        return (list && list.length) ? '<ul class="mh-notes">' + list.map(function (t) { return '<li>' + esc(t) + '</li>'; }).join('') + '</ul>' : '';
    }
    function fact(label, value, sub) {
        return '<div><dt>' + esc(label) + '</dt><dd>' + esc(value) + (sub ? '<small>' + esc(sub) + '</small>' : '') + '</dd></div>';
    }
    function clip(text, title) { return '<span class="mh-clip" title="' + esc(title || text) + '">' + esc(text) + '</span>'; }
    function tipAttr(title, rows) {
        _tips.push({ title: title, rows: rows || [] });
        return ' data-tip="' + (_tips.length - 1) + '" tabindex="0"';
    }
    function propBar(parts, title) {
        var total = parts.reduce(function (a, p) { return a + (p.v || 0); }, 0);
        if (!total) return '<div class="mh-prop mh-prop-empty" aria-label="no data"></div>';
        var shown = parts.filter(function (p) { return p.v; });
        return '<div class="mh-prop" role="img" aria-label="' + esc(title + ': ' + shown.map(function (p) { return p.label + ' ' + p.v; }).join(', ')) + '">' +
            shown.map(function (p) {
                return '<span style="flex-grow:' + p.v + ';background:' + p.color + '"' +
                    tipAttr(title, [{ color: p.color, value: n0(p.v) + ' · ' + pct(p.v / total * 100), label: p.label }]) + '></span>';
            }).join('') + '</div>';
    }
    function statusBar(counts, title) {
        return propBar(STATUS_ORDER.map(function (s) { return { v: counts[s] || 0, color: STATUS[s].color, label: STATUS[s].label }; }), title);
    }
    function meter(label, value, max, text, sub, warnAt, critAt) {
        var p = max ? Math.max(0, Math.min(100, value / max * 100)) : 0;
        var sev = p >= (critAt || 90) ? 'crit' : p >= (warnAt || 80) ? 'warn' : 'ok';
        return '<div class="mh-meter-row"><div class="mh-meter-head"><span>' + esc(label) + '</span><strong>' + esc(text) + '</strong></div>' +
            '<div class="mh-meter mh-meter-' + sev + '" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + p.toFixed(0) + '" aria-label="' + esc(label) + '">' +
            '<span style="width:' + p.toFixed(1) + '%"></span></div>' +
            (sub ? '<div class="mh-meter-sub">' + esc(sub) + '</div>' : '') + '</div>';
    }
    function chart(spec) {
        _charts.push(spec);
        var i = _charts.length - 1;
        var multi = spec.series.length > 1;
        var legend = multi ? '<div class="mh-legend">' + spec.series.map(function (s) {
            return '<span>' + swatch(s.color) + esc(s.label) + '</span>';
        }).join('') + '</div>' : '';
        var totals = spec.keys.map(function (k, j) { return spec.series.reduce(function (a, s) { return a + (s.values[j] || 0); }, 0); });
        var cols = [{ t: spec.bucket === 'week' ? 'Week of' : 'Day' }].concat(spec.series.map(function (s) { return { t: s.label, r: true }; }));
        if (multi) cols.push({ t: 'Total', r: true });
        var rows = [];
        for (var j = spec.keys.length - 1; j >= 0; j--) {
            if (!totals[j] && spec.skipEmptyRows !== false) continue;
            var row = [esc(spec.keys[j])].concat(spec.series.map(function (s) { return esc(spec.fmt(s.values[j] || 0)); }));
            if (multi) row.push(esc(spec.fmt(totals[j])));
            // The table twin is the keyboard route into a column's detail.
            rows.push(spec.detailKey ? { cells: row, detail: spec.detailKey(j) } : row);
        }
        var empty = !totals.some(function (t) { return t > 0; });
        return legend + (empty ? '<p class="mh-empty">Nothing recorded in this range.</p>' :
            '<div class="mh-chart" data-chart="' + i + '" style="height:' + (spec.height || 200) + 'px"></div>') +
            '<details class="mh-twin"><summary>Table view</summary>' + table(cols, rows) + '</details>';
    }

    // ── SVG column chart ─────────────────────────────────────────────────────
    var SVGNS = 'http://www.w3.org/2000/svg';
    function svgEl(name, attrs, parent) {
        var e = document.createElementNS(SVGNS, name);
        for (var k in attrs) { if (Object.prototype.hasOwnProperty.call(attrs, k)) e.setAttribute(k, attrs[k]); }
        if (parent) parent.appendChild(e);
        return e;
    }
    function niceMax(v, integer) {
        if (!(v > 0)) return integer ? 4 : 1;
        var p = Math.pow(10, Math.floor(Math.log10(v)));
        var m = v / p;
        var steps = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
        var nice = steps.filter(function (s) { return s >= m - 1e-9; })[0] * p;
        if (integer) { nice = Math.max(4, Math.ceil(nice)); if (nice % 2) nice += 1; }
        return nice;
    }
    function topRounded(x, y, w, h, r) {
        r = Math.min(r, w / 2, h);
        return 'M' + x + ',' + (y + h) + 'V' + (y + r) + 'Q' + x + ',' + y + ' ' + (x + r) + ',' + y +
            'H' + (x + w - r) + 'Q' + (x + w) + ',' + y + ' ' + (x + w) + ',' + (y + r) + 'V' + (y + h) + 'Z';
    }
    function dayTitle(key, bucket) {
        var d = new Date(key + 'T12:00:00');
        if (isNaN(d)) return key;
        var s = d.toLocaleDateString(undefined, { weekday: bucket === 'week' ? undefined : 'short', day: 'numeric', month: 'short', year: 'numeric' });
        return bucket === 'week' ? 'Week of ' + s : s;
    }
    function drawColumns(host, spec) {
        host.textContent = '';
        var W = Math.max(280, host.clientWidth);
        var H = host.clientHeight || spec.height || 200;
        var padL = 52, padR = 8, padT = 10, padB = 28;
        var pw = W - padL - padR, ph = H - padT - padB, n = spec.keys.length;
        if (!n || pw <= 0 || ph <= 0) return;
        var totals = spec.keys.map(function (k, j) { return spec.series.reduce(function (a, s) { return a + (s.values[j] || 0); }, 0); });
        var max = niceMax(Math.max.apply(null, totals), spec.integer);
        var svg = svgEl('svg', { width: W, height: H, viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': spec.title || 'chart' }, host);
        [0, 0.5, 1].forEach(function (f) {
            var y = Math.round(padT + ph - f * ph) + 0.5;
            svgEl('line', { x1: padL, x2: W - padR, y1: y, y2: y, stroke: f === 0 ? '#c3c2b7' : '#e6e5df', 'stroke-width': 1 }, svg);
            var t = svgEl('text', { x: padL - 8, y: y + 4, 'text-anchor': 'end', 'class': 'mh-axis' }, svg);
            t.textContent = (spec.fmtAxis || compact)(max * f);
        });
        var band = pw / n;
        var bw = Math.max(1, Math.min(24, band * 0.72));
        var every = Math.max(1, Math.ceil(70 / band));
        for (var j = 0; j < n; j++) {
            var x = padL + j * band + (band - bw) / 2;
            var base = padT + ph;
            var g = svgEl('g', { 'class': 'mh-col' }, svg);
            var visible = spec.series.filter(function (s) { return (s.values[j] || 0) > 0; });
            for (var k = 0; k < visible.length; k++) {
                var h = visible[k].values[j] / max * ph;
                var top = base - h;
                if (k === visible.length - 1) {
                    svgEl('path', { d: topRounded(x, top, bw, Math.max(h, 1.5), 4), fill: visible[k].color }, g);
                } else {
                    var gap = h > 4 ? 2 : 0;   // 2px surface gap between stacked segments
                    svgEl('rect', { x: x, y: top + gap, width: bw, height: Math.max(h - gap, 1), fill: visible[k].color }, g);
                }
                base = top;
            }
            if (j % every === 0) {
                var lbl = svgEl('text', { x: padL + j * band + band / 2, y: H - 8, 'text-anchor': 'middle', 'class': 'mh-axis' }, svg);
                lbl.textContent = spec.keys[j].slice(5);
            }
            var hit = svgEl('rect', { x: padL + j * band, y: padT, width: band, height: ph, fill: 'transparent',
                'class': 'mh-hit' + (spec.detailKey ? ' mh-hit-click' : '') }, g);
            if (spec.detailKey) hit.__detail = spec.detailKey(j);
            hit.__tip = (function (j) {
                return function () {
                    var rows = spec.series.map(function (s) { return { color: s.color, value: spec.fmt(s.values[j] || 0), label: s.label }; });
                    if (spec.series.length > 1) rows.push({ color: null, value: spec.fmt(totals[j]), label: 'Total' });
                    return { title: dayTitle(spec.keys[j], spec.bucket), rows: rows };
                };
            })(j);
        }
    }
    function drawCharts(panel) {
        panel.querySelectorAll('.mh-chart[data-chart]').forEach(function (host) {
            var spec = _charts[+host.getAttribute('data-chart')];
            if (spec) drawColumns(host, spec);
        });
    }

    // ── tooltip ──────────────────────────────────────────────────────────────
    function tipEl() {
        var t = byId('mh-tooltip');
        if (!t) {
            t = document.createElement('div');
            t.id = 'mh-tooltip';
            t.className = 'mh-tip';
            t.hidden = true;
            t.setAttribute('role', 'tooltip');
            document.body.appendChild(t);
        }
        return t;
    }
    function showTip(data, x, y) {
        var t = tipEl();
        t.textContent = '';
        var h = document.createElement('div');
        h.className = 'mh-tip-title';
        h.textContent = data.title;
        t.appendChild(h);
        data.rows.forEach(function (r) {
            var row = document.createElement('div');
            row.className = 'mh-tip-row';
            var key = document.createElement('i');
            if (r.color) key.style.background = r.color;
            row.appendChild(key);
            var v = document.createElement('strong');
            v.textContent = r.value;
            row.appendChild(v);
            var l = document.createElement('span');
            l.textContent = r.label;
            row.appendChild(l);
            t.appendChild(row);
        });
        t.hidden = false;
        var vw = window.innerWidth, vh = window.innerHeight;
        var w = t.offsetWidth, ht = t.offsetHeight;
        var left = x + 14, top = y + 14;
        if (left + w > vw - 8) left = x - w - 14;
        if (top + ht > vh - 8) top = y - ht - 14;
        t.style.left = Math.max(8, left) + 'px';
        t.style.top = Math.max(8, top) + 'px';
    }
    function hideTip() { var t = byId('mh-tooltip'); if (t) t.hidden = true; }
    function tipFor(target) {
        if (!target || !target.closest) return null;
        if (target.__tip) return target.__tip();
        var el = target.closest('[data-tip]');
        return el ? _tips[+el.getAttribute('data-tip')] : null;
    }

    // ── section renderers ────────────────────────────────────────────────────
    function familySeries(series) {
        return series.map(function (s) { return { id: s.id, label: s.label, color: FAMILY_COLOR[s.id] || OTHER, values: s.values }; });
    }
    function runsTable(rows, empty) {
        return table([{ t: 'Started' }, { t: 'Pipeline' }, { t: 'Title / id' }, { t: 'Status' }, { t: 'Duration', r: true }],
            rows.map(function (r) {
                return [esc(when(r.started)), swatch(FAMILY_COLOR[r.family] || OTHER) + esc(r.label), clip(r.title || r.id, r.id),
                    pill(r.status, r.inferred ? 'inferred' : ''), esc(dur(r.duration_s))];
            }), empty);
    }

    function renderOverview(d) {
        var k = d.kpis || {}, gpu = k.gpu || {}, disk = k.disk;
        var runsSub = (k.success_rate != null ? pct(k.success_rate) + ' success of ' + k.decided + ' decided' : 'no decided runs') +
            (k.stale ? ' · ' + k.stale + ' stale' : '') + (k.unknown ? ' · ' + k.unknown + ' unrecorded' : '');
        var html = '<div class="mh-tiles">' +
            tile('Runs', n0(k.runs), runsSub) +
            tile('API spend (est.)', usd(k.api_cost_usd), usd(k.api_cost_all_time_usd) + ' all time · list price') +
            tile('LLM calls', n0(k.llm_calls), n0(k.local_calls) + ' local · ' + n0(k.llm_errors) + ' errors') +
            tile('Gate pass rate', k.gate_outcomes ? pct(k.gate_pass_rate) : '—', n0(k.gate_outcomes) + ' attributed outcomes · ' + n0(k.gate_unattributed) + ' unattributed') +
            tile('Silent fallbacks', n0(k.fallbacks), k.top_fallback ? 'most: ' + k.top_fallback : 'none recorded') +
            tile('Services', (k.services_ok != null ? k.services_ok + ' / ' + k.services_counted : '—'),
                (k.services_orphan ? k.services_orphan + ' orphaned · ' : '') + (k.services_failed ? k.services_failed + ' failed · ' : '') + 'running of expected') +
            tile('Disk free', disk ? disk.free_gb + ' GB' : '—', disk ? disk.used_pct + '% used on ' + disk.mount : '') +
            tile('GPU now', gpu.capacity_pct != null ? pct(gpu.capacity_pct) : '—',
                gpu.memory_used_mb != null ? 'VRAM ' + (gpu.memory_used_mb / 1024).toFixed(1) + ' / ' + Math.round(gpu.memory_total_mb / 1024) + ' GB · ' + Math.round(gpu.power_w || 0) + ' W' : 'telemetry unavailable') +
            '</div>';

        var att = d.attention || [];
        html += card('Needs attention', att.length ? '<ul class="mh-attention">' + att.map(function (a) {
            return '<li>' + sevPill(a.severity) + '<div><strong>' + esc(a.title) + '</strong>' + (a.detail ? '<span>' + esc(a.detail) + '</span>' : '') + '</div>' +
                (a.tab ? '<button type="button" class="mh-link" data-goto="' + esc(a.tab) + '">' + esc(TAB_LABELS[a.tab] || a.tab) + ' →</button>' : '') + '</li>';
        }).join('') + '</ul>' : '<p class="mh-empty">' + pill('completed') + ' Nothing flagged by the attention rules.</p>',
            att.length + (att.length === 1 ? ' item' : ' items'));

        var dr = d.daily_runs || { keys: [], series: [], bucket: 'day' };
        html += card('Runs started per ' + esc(dr.bucket) + ', by pipeline', chart({
            keys: dr.keys, bucket: dr.bucket, integer: true, fmt: n0, title: 'Runs started per ' + dr.bucket,
            series: familySeries(dr.series)
        }), (d.excluded_test_runs || 0) + ' test runs excluded');

        html += '<div class="mh-grid-2">' +
            card('Recent runs', runsTable(d.recent || [])) +
            card('Data sources', table([{ t: 'Source' }, { t: 'Last write' }, { t: 'Age', r: true }, { t: 'Files', r: true }],
                (d.freshness || []).map(function (f) {
                    return [clip(f.source, f.path), esc(when(f.last_write)), esc(agoSeconds(f.age_s)), n0(f.files)];
                })), 'where these numbers come from') +
            '</div>';
        return html;
    }

    function renderPipelines(d) {
        var t = d.totals || {};
        var decided = (t.completed || 0) + (t.failed || 0);
        var html = '<div class="mh-tiles">' +
            tile('Runs', n0(t.runs), 'started, ' + rangeLabel()) +
            tile('Success', decided ? pct(t.completed / decided * 100) : '—', n0(t.completed) + ' completed of ' + n0(decided) + ' decided') +
            tile('Failed', n0(t.failed), 'recorded or inferred') +
            tile('Stale', n0(t.stale), 'no end and no state write for 12 h+') +
            tile('Unrecorded', n0(t.unknown), 'ended without an outcome') +
            tile('In progress', n0(t.open), 'state written in the last 12 h') +
            '</div>';
        html += '<div class="mh-legend mh-status-legend">' + STATUS_ORDER.map(function (s) { return pill(s); }).join('') + '</div>';
        var kinds = d.kinds || [];
        html += kinds.length ? '<div class="mh-pipe-grid">' + kinds.map(function (k) {
            var c = k.counts || {};
            var stages = k.stages || [];
            return '<section class="mh-card mh-pipe"><header class="mh-card-head"><h4>' + swatch(FAMILY_COLOR[k.family] || OTHER) + esc(k.label) + '</h4>' +
                '<span class="mh-card-aside">' + plural(k.total, 'run') + '</span></header>' +
                statusBar(c, k.label) +
                '<dl class="mh-facts">' +
                fact('Success', k.success_rate != null ? pct(k.success_rate) : '—', k.decided + ' decided') +
                fact('Completed', n0(c.completed), pct(c.completed / k.total * 100) + ' of all runs' + (k.inferred ? ' · ' + k.inferred + ' inferred' : '')) +
                fact('Duration p50', dur(k.p50_s), k.timed_runs ? 'p90 ' + dur(k.p90_s) + ' · ' + k.timed_runs + ' timed' : 'no timings recorded') +
                fact('Last run', ago(k.last_started), k.last_status ? (STATUS[k.last_status] || STATUS.unknown).label : '') +
                (k.api_cost_usd ? fact('API spend', usd(k.api_cost_usd), 'estimated') : '') +
                '</dl>' +
                (stages.length ? '<details class="mh-twin"><summary>Stage timings (' + stages.length + ')</summary>' +
                    table([{ t: 'Stage' }, { t: 'Runs', r: true }, { t: 'p50', r: true }, { t: 'Mean', r: true }, { t: 'Failed', r: true }],
                        stages.map(function (s) {
                            return [esc(s.name), n0(s.runs), esc(dur(s.p50_s)), esc(dur(s.avg_s)), s.failed ? '<b class="mh-bad">' + n0(s.failed) + '</b>' : '0'];
                        })) + '</details>' : '') +
                '</section>';
        }).join('') + '</div>' : '<p class="mh-empty">No runs started in this range.</p>';

        html += card('Runs started per ' + esc((d.daily || {}).bucket || 'day'), chart({
            keys: (d.daily || {}).keys || [], bucket: (d.daily || {}).bucket, integer: true, fmt: n0,
            title: 'Runs started', series: familySeries((d.daily || {}).series || [])
        }));

        var stale = d.stale_claims || [];
        html += card('Still claiming to be in progress', stale.length ? note('These records say running or paused but have not written state for 12 h or more. They are listed across all time, because anything that trusts the recorded status still treats them as live.') +
            table([{ t: 'Started' }, { t: 'Pipeline' }, { t: 'Id' }, { t: 'Recorded' }, { t: 'Last write' }, { t: 'Stage' }],
                stale.map(function (r) {
                    return [esc(when(r.started)), swatch(FAMILY_COLOR[r.family] || OTHER) + esc(r.label), clip(r.id.slice(0, 12), r.id),
                        esc(r.status_raw), esc(ago(r.last_write)), clip(r.current_stage || '—')];
                })) : '<p class="mh-empty">' + pill('completed') + ' No run is stuck claiming to be in progress.</p>', plural(stale.length, 'run'));

        html += '<div class="mh-grid-2">' +
            card('Recent failures', table([{ t: 'Started' }, { t: 'Pipeline' }, { t: 'Title / id' }, { t: 'Error' }],
                (d.recent_failures || []).map(function (r) {
                    return [esc(when(r.started)), swatch(FAMILY_COLOR[r.family] || OTHER) + esc(r.label), clip(r.title || r.id, r.id), clip(r.error || (r.inferred ? '(inferred from stored error)' : '—'))];
                }), 'No failed runs in this range.')) +
            card('Recent runs', runsTable(d.recent || [])) + '</div>';

        var extra = [];
        if (d.excluded_test_runs) extra.push(d.excluded_test_runs + ' test / smoke runs excluded.');
        if (d.excluded_synthesized) extra.push(d.excluded_synthesized + ' records synthesized from character bibles excluded (not observed runs).');
        (d.unreadable || []).forEach(function (u) { extra.push('Unreadable state file: ' + u.file + ' — ' + u.error); });
        html += card('How statuses are decided', notes((d.status_rules || []).concat(extra)));
        return html;
    }

    function renderCharacters(d) {
        var c = d.characters || {}, l = d.lora || {}, cs = d.contact_sheets || {}, cr = d.creatures || {};
        var html = '<div class="mh-tiles">' +
            tile('Character runs', n0(c.total), c.success_rate != null ? pct(c.success_rate) + ' success · ' + n0(c.failed) + ' failed' : 'no decided runs') +
            tile('Median run time', dur(c.p50_s), c.timed_runs ? 'p90 ' + dur(c.p90_s) + ' · ' + c.timed_runs + ' timed' : 'no timed runs') +
            tile('LoRA trainings', n0(l.attempts), l.attempts ? pct(l.success_rate) + ' completed' : 'none in range') +
            tile('FLUX LoRA p50', dur(l.flux_p50_s), l.flux_runs + ' runs') +
            tile('SDXL LoRA p50', dur(l.sdxl_p50_s), l.sdxl_runs + ' runs') +
            tile('Contact sheets', n0(cs.total), cs.cells_total ? n0(cs.cells_done) + ' / ' + n0(cs.cells_total) + ' cells' : (cs.failed ? cs.failed + ' failed' : '')) +
            tile('Creatures', n0(cr.total), cr.failed ? cr.failed + ' failed' : '') +
            '</div>';
        html += notes(d.notes);
        html += '<div class="mh-grid-2">' +
            card('Character runs by status', !c.total ? '<p class="mh-empty">No observed character runs in this range.</p>' :
                statusBar(c, 'Character runs') + '<div class="mh-legend mh-status-legend">' +
                STATUS_ORDER.filter(function (s) { return c[s]; }).map(function (s) { return pill(s, n0(c[s])); }).join('') + '</div>' +
                table([{ t: 'Model family' }, { t: 'Runs', r: true }], Object.keys(c.model_families || {}).map(function (m) { return [esc(m), n0(c.model_families[m])]; })) +
                table([{ t: 'Render source' }, { t: 'Runs', r: true }], Object.keys(c.render_modes || {}).map(function (m) { return [esc(m), n0(c.render_modes[m])]; }))) +
            card('Stage timings (completed stages)', table([{ t: 'Stage' }, { t: 'Runs', r: true }, { t: 'p50', r: true }, { t: 'p90', r: true }],
                (d.stages || []).map(function (s) { return [esc(s.name), n0(s.runs), esc(dur(s.p50_s)), esc(dur(s.p90_s))]; }))) +
            '</div>';
        html += card('Recent character jobs', table([{ t: 'Started' }, { t: 'Kind' }, { t: 'Name / id' }, { t: 'Model' }, { t: 'Status' }, { t: 'Duration', r: true }],
            (d.recent || []).map(function (r) {
                return [esc(when(r.started)), esc(r.label), clip(r.title || r.id, r.id), esc(r.model_family || '—'), pill(r.status, r.inferred ? 'inferred' : ''), esc(dur(r.duration_s))];
            })));
        var q = d.quality || {};
        var alerts = (q.alerts || []).length ? '<ul class="mh-attention">' + q.alerts.map(function (a) {
            return '<li>' + sevPill('warning') + '<div><strong>' + esc(a.alert) + '</strong><span>' + esc(a.char_id) + ' · ' + esc(when(a.ts)) + '</span></div></li>';
        }).join('') + '</ul>' : '';
        html += card('Contact-sheet quality log', alerts +
            table([{ t: 'Time' }, { t: 'Character' }, { t: 'QC ran' }, { t: 'QC mean', r: true }, { t: 'Valve' }, { t: 'Dedup sim', r: true }],
                (q.rows || []).map(function (r) {
                    return [esc(when(r.ts)), esc(r.char_id), esc(r.qc_ran == null ? '—' : r.qc_ran ? 'yes' : 'no'), esc(r.qc_mean_score == null ? '—' : r.qc_mean_score),
                        esc(r.valve_verdict || '—'), esc(r.anchor_dedup_max_sim == null ? '—' : r.anchor_dedup_max_sim)];
                }), 'No rows in character_quality_metrics.jsonl.'),
            q.last_write ? 'all time · last write ' + when(q.last_write) : 'no rows');
        return html;
    }

    function renderLlm(d) {
        var t = d.totals || {}, a = d.all_time || {}, cov = d.coverage || {}, daily = d.daily || { keys: [], calls: [], spend_usd: [] };
        var html = '<div class="mh-tiles">' +
            tile('API spend (est.)', usd(t.api_cost_usd), usd(a.api_cost_usd) + ' all time since ' + when(a.first).slice(0, 10)) +
            tile('API calls', n0(t.api_calls), t.unpriced_calls ? t.unpriced_calls + ' without a price' : 'Anthropic + OpenAI') +
            tile('Local calls', n0(t.local_calls), 'Ollama, logged helper only') +
            tile('Tokens in / out', compact(t.tokens_in) + ' / ' + compact(t.tokens_out), 'all providers') +
            tile('Errors', n0(t.errors), t.calls ? pct(t.errors / t.calls * 100, 1) + ' of ' + n0(t.calls) + ' calls' : '') +
            tile('Claude Code (login)', n0(t.claude_code_calls), usd(t.claude_code_cost_usd) + ' API-equivalent, not billed to the key') +
            '</div>';
        html += '<div class="mh-grid-2">' +
            card('Calls per ' + esc(daily.bucket) + ', by provider', chart({
                keys: daily.keys, bucket: daily.bucket, integer: true, fmt: n0, title: 'LLM calls',
                series: (daily.calls || []).map(function (s) { return { id: s.id, label: s.label, color: PROVIDER_COLOR[s.id] || OTHER, values: s.values }; })
            })) +
            card('Estimated API spend per ' + esc(daily.bucket), chart({
                keys: daily.keys, bucket: daily.bucket, fmt: usd, fmtAxis: usd, title: 'Estimated API spend',
                series: [{ id: 'spend', label: 'Estimated API spend', color: SLOT[0], values: daily.spend_usd || [] }]
            }), 'list price, no cache discount') +
            '</div>';
        html += card('By model', table([{ t: 'Provider' }, { t: 'Model' }, { t: 'Calls', r: true }, { t: 'Errors', r: true }, { t: 'Tokens in', r: true },
            { t: 'Tokens out', r: true }, { t: 'Cost', r: true }, { t: 'Basis' }, { t: 'p50', r: true }, { t: 'p95', r: true }],
            (d.by_model || []).map(function (m) {
                return [swatch(PROVIDER_COLOR[m.provider] || OTHER) + esc(m.provider_label), esc(m.model), n0(m.calls), m.errors ? '<b class="mh-bad">' + n0(m.errors) + '</b>' : '0',
                    esc(compact(m.tokens_in)), esc(compact(m.tokens_out)), esc(m.cost_usd == null ? '—' : usd(m.cost_usd)), esc(m.basis), esc(m.p50_s == null ? '—' : m.p50_s + 's'), esc(m.p95_s == null ? '—' : m.p95_s + 's')];
            })));
        html += '<div class="mh-grid-2">' +
            card('By pipeline and stage', table([{ t: 'Pipeline' }, { t: 'Stage' }, { t: 'Calls', r: true }, { t: 'Tokens', r: true }, { t: 'API cost', r: true }],
                (d.by_stage || []).map(function (s) { return [esc(s.pipeline), clip(s.stage), n0(s.calls), esc(compact(s.tokens)), esc(usd(s.api_cost_usd))]; })), 'top 30') +
            card('Errors', table([{ t: 'Provider' }, { t: 'Message' }, { t: 'Count', r: true }, { t: 'Last' }],
                (d.errors || []).map(function (e) { return [esc(e.provider), clip(e.message), n0(e.count), esc(when(e.last))]; }), 'No failed calls in this range.')) +
            '</div>';
        html += card('Recent calls', table([{ t: 'Time' }, { t: 'Provider' }, { t: 'Model' }, { t: 'Pipeline' }, { t: 'Stage' }, { t: 'In', r: true }, { t: 'Out', r: true }, { t: 'Cost', r: true }, { t: 'Latency', r: true }],
            (d.recent || []).map(function (r) {
                return [esc(when(r.ts)), esc(r.provider), esc(r.model) + (r.error ? ' <b class="mh-bad" title="' + esc(r.error) + '">error</b>' : ''), esc(r.pipeline), clip(r.stage),
                    esc(compact(r.tokens_in)), esc(compact(r.tokens_out)), esc(r.cost_usd == null ? '—' : usd(r.cost_usd)), esc(r.elapsed_s == null ? '—' : Math.round(r.elapsed_s * 10) / 10 + 's')];
            })), 'newest 40, metadata only');
        html += card('Coverage', '<dl class="mh-facts">' +
            fact('Context ledger rows', n0(cov.context_ledger_rows), 'token reports, permanent') +
            fact('LLM audit rows', n0(cov.llm_audit_rows), 'since ' + when(cov.audit_cutover)) +
            fact('Duplicates dropped', n0(cov.duplicate_ledger_rows_dropped), 'ledger copies of audited calls') +
            fact('Test calls excluded', n0(cov.excluded_test_calls), 'smoke / gatecheck / route probes') +
            '</dl>' + notes(cov.notes) +
            '<details class="mh-twin"><summary>Prices used (per 1M tokens)</summary>' +
            table([{ t: 'Model prefix' }, { t: 'Input', r: true }, { t: 'Output', r: true }], (d.pricing || []).map(function (p) {
                return [esc(p.model_prefix), esc(usd(p.input_per_mtok)), esc(usd(p.output_per_mtok))];
            })) + '</details>' +
            (d.caveman ? '<details class="mh-twin"><summary>Caveman-tagged calls</summary><dl class="mh-facts">' +
                fact('Tagged calls', n0(d.caveman.tagged_calls), 'avg completion ' + n0(d.caveman.avg_completion_tagged)) +
                fact('Untagged calls', n0(d.caveman.untagged_calls), 'avg completion ' + n0(d.caveman.avg_completion_untagged)) +
                '</dl>' + note(d.caveman.note) + '</details>' : ''));
        return html;
    }

    function renderQuality(d) {
        var g = d.gates || {}, f = d.fallbacks || {}, rc = d.receipts || {};
        // Every number and verdict below carries the token for the rows it was computed
        // from; clicking one asks the same endpoint for them (?detail=<token>).
        var html = '<div class="mh-tiles">' +
            tile('Gate pass rate', (g.pass + g.fail) ? pct(g.pass_rate) : '—', 'attributed runs only', 'tile:pass_rate') +
            tile('Attributed outcomes', n0((g.pass || 0) + (g.fail || 0)), n0(g.pass) + ' pass · ' + n0(g.fail) + ' fail', 'tile:attributed') +
            tile('Unattributed rows', n0((g.unattributed_pass || 0) + (g.unattributed_fail || 0)), n0(g.unattributed_pass) + ' pass · ' + n0(g.unattributed_fail) + ' fail · not pooled', 'tile:unattributed') +
            tile('Test rows excluded', n0(g.excluded_test), 'pytest, self-test, synthetic ids', 'tile:test_rows') +
            tile('Silent fallbacks', n0(f.total), n0(f.total_all_time) + ' all time', 'tile:fallbacks') +
            tile('Runs with gate receipts', n0(rc.runs), rangeLabel(), 'tile:receipt_runs') +
            '</div>' +
            '<p class="mh-note mh-drill-hint">Every tile, row and column here opens the rows it was ' +
            'counted from — click one, or tab to it and press Enter.</p>';
        var fams = g.families || [];
        html += card('Gate families', fams.length ? table([{ t: 'Gate' }, { t: 'Attributed runs' }, { t: 'Pass rate', r: true }, { t: 'Pass / fail', r: true },
            { t: 'Unattributed pass / fail', r: true }, { t: 'Test rows', r: true }, { t: 'Last seen' }],
            fams.map(function (x) {
                var bar = (x.pass + x.fail) ? propBar([{ v: x.pass, color: STATUS.completed.color, label: 'Pass' }, { v: x.fail, color: STATUS.failed.color, label: 'Fail' }], x.family) :
                    '<span class="mh-muted">no attributed outcomes</span>';
                return { detail: x.detail, cells: [esc(x.family), bar, esc(x.pass_rate == null ? '—' : pct(x.pass_rate)), n0(x.pass) + ' / ' + n0(x.fail) + (x.shadow_fail ? ' <em class="mh-muted">+' + x.shadow_fail + ' shadow</em>' : ''),
                    (x.unattributed_pass + x.unattributed_fail) ? n0(x.unattributed_pass) + ' / ' + n0(x.unattributed_fail) : '—', x.test_rows ? n0(x.test_rows) : '—', esc(when(x.last))] };
            })) : '<p class="mh-empty">No gate outcomes recorded in this range.</p>', fams.length + ' families');
        var gd = g.daily || { keys: [], pass: [], fail: [] };
        var dayKey = function (j) { return 'day:' + gd.keys[j]; };
        html += '<div class="mh-grid-2">' +
            card('Attributed gate outcomes per ' + esc(gd.bucket || 'day'), chart({
                keys: gd.keys, bucket: gd.bucket, integer: true, fmt: n0, title: 'Gate outcomes', detailKey: dayKey,
                series: [{ id: 'pass', label: 'Pass', color: STATUS.completed.color, values: gd.pass || [] },
                    { id: 'fail', label: 'Fail', color: STATUS.failed.color, values: gd.fail || [] }]
            })) +
            card('Silent fallbacks per ' + esc(gd.bucket || 'day'), chart({
                keys: gd.keys, bucket: gd.bucket, integer: true, fmt: n0, title: 'Silent fallbacks', detailKey: dayKey,
                series: [{ id: 'fallbacks', label: 'Fallbacks', color: SEVERITY.serious.color, values: f.daily || [] }]
            }), f.excluded_test ? f.excluded_test + ' test rows excluded' : '') +
            '</div>';
        html += card('Fallbacks by component', table([{ t: 'Component' }, { t: 'Expected → actual' }, { t: 'In range', r: true }, { t: 'All time', r: true }, { t: 'Unattributed', r: true }, { t: 'Last' }],
            (f.components || []).map(function (c) {
                return { detail: c.detail, cells: [clip(c.component), clip(c.expected + ' → ' + c.actual), c.count ? '<b>' + n0(c.count) + '</b>' : '0', n0(c.count_all_time), n0(c.unattributed), esc(when(c.last))] };
            }), 'No fallbacks recorded.'));
        html += '<div class="mh-grid-2">' +
            card('Pipeline gate receipts', table([{ t: 'Gate' }, { t: 'Ran', r: true }, { t: 'Did not run', r: true }, { t: 'Reasons' }],
                (rc.gates || []).map(function (x) {
                    return { detail: x.detail, cells: [esc(x.gate), n0(x.ran), x.not_ran ? '<b class="mh-bad">' + n0(x.not_ran) + '</b>' : '0',
                        clip(Object.keys(x.reasons || {}).map(function (r) { return r + ' ×' + x.reasons[r]; }).join('; ') || '—')] };
                }), 'No run in this range filed gate receipts.') +
                (Object.keys(d.vlm_gate_stats || {}).length ? '<details class="mh-twin" open><summary>VLM gate totals</summary>' +
                    table([{ t: 'Counter' }, { t: 'Total', r: true }], Object.keys(d.vlm_gate_stats).map(function (key) {
                        return { detail: 'vlm:' + key, cells: [esc(key.replace(/_/g, ' ')), n0(d.vlm_gate_stats[key])] };
                    })) + '</details>' : '')) +
            card('Recent debug-run verdicts', table([{ t: 'Time' }, { t: 'Run' }, { t: 'Verdict' }, { t: 'Failed checks', r: true }, { t: 'Blocking' }, { t: 'Degradations', r: true }],
                (d.debug_runs || []).map(function (r) {
                    var v = r.blocked ? sevPill('critical', 'Blocked') : r.ok ? pill('completed') : r.ok === false ? sevPill('warning', 'Checks failed') : pill('unknown');
                    return { detail: r.detail, cells: [esc(when(r.ts)), clip(r.name || r.run_id, r.run_id), v, n0(r.failed_checks), clip((r.blocking || []).join(', ') || '—'), n0(r.degradations)] };
                }), 'No production debug runs recorded.'), 'all time, test runs excluded') +
            '</div>';
        html += card('How these are counted', notes(d.notes));
        return html;
    }

    function renderSystem(d) {
        var t = d.telemetry || {}, gpu = (d.gpus || [])[0] || {};
        var meters = '';
        if (t.available) {
            meters += meter('CPU', t.cpu_pct || 0, 100, pct(t.cpu_pct), (t.cpu_cores_busy != null ? t.cpu_cores_busy + ' cores busy' : '') + (t.cpu_temp_c != null ? ' · ' + Math.round(t.cpu_temp_c) + '°C' : ''));
            meters += meter('RAM', t.ram_used_mb || 0, t.ram_total_mb || 1, (t.ram_used_mb / 1024).toFixed(1) + ' / ' + Math.round(t.ram_total_mb / 1024) + ' GB', pct(t.ram_pct) + ' used');
        }
        if (gpu.memory_total_mb) {
            meters += meter('GPU capacity', gpu.capacity_pct || 0, 100, pct(gpu.capacity_pct), 'duty ' + pct(gpu.utilization_pct) + ' × clock ' + pct(gpu.clock_pct) + (gpu.temperature_c != null ? ' · ' + Math.round(gpu.temperature_c) + '°C' : ''));
            meters += meter('VRAM', gpu.memory_used_mb || 0, gpu.memory_total_mb, (gpu.memory_used_mb / 1024).toFixed(1) + ' / ' + Math.round(gpu.memory_total_mb / 1024) + ' GB', '');
            meters += meter('GPU power', gpu.power_w || 0, gpu.power_limit_w || 450, Math.round(gpu.power_w || 0) + ' / ' + Math.round(gpu.power_limit_w || 0) + ' W', '', 85, 97);
        }
        (d.disks || []).forEach(function (x) {
            meters += meter('Disk ' + x.mount, x.used_pct || 0, 100, x.free_gb + ' GB free', pct(x.used_pct) + ' of ' + x.total_gb + ' GB used');
        });
        var cq = d.comfy_queue || {}, ol = d.ollama || {}, st = d.session_tree || {}, stq = st.queue || {};
        var html = '<div class="mh-grid-2">' +
            card('Hardware now', meters || '<p class="mh-empty">Telemetry sampler not available.</p>', 'sampled every 2 s, refreshes every 15 s') +
            card('Queues', '<dl class="mh-facts mh-facts-wide">' +
                fact('ComfyUI queue', cq._error ? 'unreachable' : n0(cq.running) + ' running · ' + n0(cq.pending) + ' pending', cq._error || ':8188/queue') +
                fact('Ollama models loaded', ol._error ? 'unreachable' : n0((ol.models || []).length), ol._error || ((ol.models || []).map(function (m) { return m.name + ' ' + compact(m.vram_mb) + ' MB'; }).join(', ') || 'none resident')) +
                fact('Session Tree slots', st._error ? 'unreachable' : n0(stq.light_used) + ' / ' + n0(stq.light_slots) + ' light · ' + n0(stq.heavy_used) + ' / ' + n0(stq.heavy_slots) + ' heavy',
                    st._error || (n0(st.waiting) + ' waiting')) +
                '</dl>' +
                '<details class="mh-twin" open><summary>GPU processes (' + (gpu.processes || []).length + ')</summary>' +
                table([{ t: 'PID', r: true }, { t: 'Process' }, { t: 'VRAM', r: true }, { t: 'SM', r: true }], (gpu.processes || []).map(function (p) {
                    return [esc(p.pid), clip(p.label || '—'), esc(p.vram_mb == null ? '—' : compact(p.vram_mb) + ' MB'), esc(p.sm_pct == null ? '—' : pct(p.sm_pct))];
                }), 'No GPU processes reported.') + '</details>') +
            '</div>';
        var svc = d.services || [];
        html += card('Services', table([{ t: 'Service' }, { t: 'Unit' }, { t: 'Port', r: true }, { t: 'State' }, { t: 'Since' }, { t: 'Restarts', r: true }, { t: 'Detail' }],
            svc.map(function (s) {
                var m = SERVICE_STATE[s.state] || SERVICE_STATE.unknown;
                return [esc(s.label), esc(s.unit ? s.unit + (s.scope === 'user' ? ' (user)' : '') : '— (no unit)'), esc(s.port || '—'), sevPill(m[0], m[1]),
                    esc(when(s.since)), esc(s.restarts == null ? '—' : s.restarts), clip(s.detail + (s.owner && s.owner.cmd ? ' · ' + s.owner.cmd + ' · up ' + dur(s.owner.age_s) : '') || '—')];
            })), 'systemd + port ownership (cgroup)');
        var hp = d.health_probe || {};
        html += card('Health probe events', (hp.error ? note('Cannot read the probe log: ' + hp.error) : '') +
            '<div class="mh-legend">' + sevPill('serious', n0(hp.restarts) + ' restarts') + sevPill('warning', n0(hp.strikes) + ' strikes') + '</div>' +
            table([{ t: 'Time' }, { t: 'Kind' }, { t: 'Unit' }, { t: 'Event' }], (hp.events || []).slice(0, 40).map(function (e) {
                return [esc(when(e.ts)), esc(e.kind), esc(e.unit || '—'), clip(e.text)];
            }), 'No probe events in this range — the log is event-only, so silence means healthy.'),
            'event-only log · last write ' + when(hp.log_last_write));
        return html;
    }

    function renderAgents(d) {
        var t = d.totals || {}, st = d.session_tree || {}, q = st.queue || {}, daily = d.daily || { keys: [], series: [] };
        var html = '<div class="mh-tiles">' +
            tile('Agent sessions', n0(t.sessions), rangeLabel()) +
            tile('Agent-hours', n0(t.agent_hours), 'wall clock, all sessions') +
            tile('GPU sessions', n0(t.gpu_sessions), t.sessions ? pct(t.gpu_sessions / t.sessions * 100) + ' of sessions' : '') +
            tile('Peak VRAM', t.peak_vram_mb ? (t.peak_vram_mb / 1024).toFixed(1) + ' GB' : '—', 'highest single session') +
            tile('Median session', dur(t.p50_duration_s), n0(t.recovered) + ' recovered after restart') +
            tile('Session Tree', st._error ? 'unreachable' : n0(q.light_used) + ' / ' + n0(q.light_slots), st._error ? '' : 'light slots · heavy ' + n0(q.heavy_used) + ' / ' + n0(q.heavy_slots) + ' · ' + n0(st.waiting) + ' waiting') +
            '</div>';
        html += card('Agent-hours per ' + esc(daily.bucket || 'day'), chart({
            keys: daily.keys, bucket: daily.bucket, fmt: function (v) { return (Math.round(v * 10) / 10) + ' h'; }, fmtAxis: function (v) { return compact(v) + ' h'; },
            title: 'Agent-hours', series: (daily.series || []).map(function (s) { return { id: s.id, label: s.label, color: DEVICE_COLOR[s.id] || OTHER, values: s.values }; })
        }), 'ledger since ' + when(d.ledger_first));
        function sessionRows(rows) {
            return rows.map(function (r) {
                return [esc(when(r.start)), esc(r.name || '—'), esc(dur(r.duration_s)), esc(r.device || '—'), esc(r.peak_vram_mb ? (r.peak_vram_mb / 1024).toFixed(1) + ' GB' : '—'),
                    esc(r.peak_cpu_cores == null ? '—' : r.peak_cpu_cores), clip((r.kinds || []).join(', ') || '—')];
            });
        }
        var cols = [{ t: 'Started' }, { t: 'Session' }, { t: 'Duration', r: true }, { t: 'Device' }, { t: 'Peak VRAM', r: true }, { t: 'Peak cores', r: true }, { t: 'Process kinds' }];
        html += '<div class="mh-grid-2">' + card('Longest sessions', table(cols, sessionRows(d.longest || []))) +
            card('Recent sessions', table(cols, sessionRows(d.recent || []))) + '</div>';
        html += card('Process kinds', table([{ t: 'Kind' }, { t: 'Sessions', r: true }], Object.keys(d.kinds || {}).map(function (k) { return [esc(k), n0(d.kinds[k])]; })) + notes(d.notes));
        return html;
    }

    // ── Agent Zero: the per-turn ledger of Agent Zero v2 (agent_zero/metrics.py) ──
    // Every row of data/runtime/zero_metrics.jsonl is one finished turn, whatever its
    // outcome. api_usd is API-EQUIVALENT money, never money spent: a subscription turn
    // spends the Claude Code seat and a local Ollama turn costs nothing, so the price is
    // there only to compare Agent Zero with a hosted provider.
    var ZERO_RISK = { read: 'neutral', act: 'warning', danger: 'critical' };
    var ZERO_PROVIDER_COLOR = { subscription: SLOT[2], anthropic: SLOT[0], ollama: SLOT[1] };
    function zeroMs(v) { return v == null ? '—' : Number(v) < 1000 ? Math.round(v) + ' ms' : dur(Number(v) / 1000); }
    // ts is an ISO string in the turn ledger and an epoch float in the install log.
    function zeroWhen(v) { return typeof v === 'number' ? localTs(v) : when(v); }
    function zeroSeries(daily, id, label, color) {
        var found = (daily.series || []).filter(function (s) { return s.id === id; })[0] || {};
        return { id: id, label: label, color: color, values: found.values || [] };
    }
    function renderZero(d) {
        var t = d.totals || {}, b = d.budget || {}, cfg = b.config || {}, mtr = b.meter || {};
        var perTurn = cfg.per_turn || {}, perDay = cfg.per_day || {}, perWeek = cfg.per_week || {};
        var sel = d.selected || {}, daily = d.daily || { keys: [], series: [] }, block = b.last_block || null;
        var html = '<div class="mh-tiles">' +
            tile('Turns', n0(t.turns), plural(t.sessions, 'session') + ' · ' + rangeLabel()) +
            tile('Input tokens', compact(t.input_tokens), 'cache read ' + compact(t.cache_read)) +
            tile('Output tokens', compact(t.output_tokens), 'cache write ' + compact(t.cache_write)) +
            tile('API-equivalent $', usd(t.api_usd), 'what API billing would charge; subscription turns cost quota, not dollars') +
            tile('Subscription / API / Local turns', n0(t.subscription_turns) + ' / ' + n0(t.api_turns) + ' / ' + n0(t.local_turns),
                'Claude Code seat · hosted API · local Ollama') +
            tile('Tool calls', n0(t.tool_calls), 'errors ' + n0(t.tool_errors) + ' · danger ' + n0(t.danger_calls) + ' · confirmations ' + n0(t.confirmations)) +
            '</div>';
        html += '<div class="mh-tiles">' +
            tile('Median latency', zeroMs(t.p50_latency_ms), 'p95 ' + zeroMs(t.p95_latency_ms) + ' · whole turn, tool calls included') +
            tile('Time to first token', zeroMs(t.p50_ttft_ms), 'p50, to the first text delta') +
            tile('Budget blocks', n0(t.budget_blocks), block ? 'last: ' + block.reason : 'no turn was ever refused') +
            tile('Errors', n0(t.errors), 'cancelled ' + n0(t.cancelled)) +
            tile('Compactions', n0(t.compactions), 'history folded into a rolling summary') +
            tile('Installs', n0(t.installs), 'Ollama pulls in this range') +
            '</div>';
        var hardDay = perDay.hard_tokens || 0, softDay = perDay.soft_tokens || 0;
        var meters = meter('Tokens today', b.day_tokens || 0, hardDay, compact(b.day_tokens) + ' / ' + compact(hardDay),
            'Amsterdam day ' + (b.day || '—') + ' · warns at ' + compact(softDay) + ' · ' + usd(b.day_api_usd) + ' API-equivalent',
            hardDay ? softDay / hardDay * 100 : 80, 100);
        var shareCap = perWeek.zero_share_cap_pct;
        meters += meter('Agent Zero\'s share of the Claude week', b.zero_share_pct || 0, shareCap || 100,
            (b.zero_share_pct == null ? 'not sampled yet' : pct(b.zero_share_pct, 1)) + ' of ' + pct(shareCap, 0),
            'Zero\'s API-equivalent as a share of this login\'s week; cached, never scanned per turn', 75, 100);
        var reserve = perWeek.meter_reserve_pct;
        meters += meter('Claude\'s own weekly meter', mtr.seven_day_pct || 0, reserve || 100,
            (mtr.seven_day_pct == null ? 'unknown' : pct(mtr.seven_day_pct, 0)) + ' of the ' + pct(reserve, 0) + ' reserve',
            mtr.ok ? 'subscription turns stop above the reserve' : 'no meter sample: unknown counts as allowed', 75, 100);
        var fable = (mtr.scoped || {}).fable;
        if (fable != null) {
            meters += meter('Fable weekly limit', fable, perWeek.fable_cap_pct || 100,
                pct(fable, 0) + ' of ' + pct(perWeek.fable_cap_pct, 0), 'applied only when the selected model is a Fable model', 75, 100);
        }
        html += card('Budget now', meters + '<dl class="mh-facts mh-facts-wide">' +
            fact('Selected model', (sel.provider || '—') + ' · ' + (sel.model || '—'), 'data/agent_zero.json') +
            fact('Override turns left', n0(b.override_turns_left), 'an explicit grant is the only way past a ceiling') +
            fact('Per-turn ceilings', compact(perTurn.max_context_tokens) + ' context · ' + n0(perTurn.max_tool_calls) + ' tools · ' + compact(perTurn.max_output_tokens) + ' output',
                'a turn over a ceiling is refused, never trimmed') +
            fact('Turns today', n0(b.day_turns) + ' / ' + n0(perDay.max_turns), block ? 'last block ' + zeroWhen(block.ts) : 'no block recorded') +
            '</dl>', b.summary_line || '');
        html += '<div class="mh-grid-2">' +
            card('Tokens per day', chart({ keys: daily.keys, bucket: daily.bucket, fmt: compact, fmtAxis: compact, title: 'Tokens per day',
                series: [zeroSeries(daily, 'input', 'Input tokens', SLOT[0]), zeroSeries(daily, 'output', 'Output tokens', SLOT[1])] })) +
            card('Turns and API-$ per day', chart({ keys: daily.keys, bucket: daily.bucket, title: 'Turns and API-equivalent dollars',
                fmt: function (v) { return (Math.round(Number(v) * 100) / 100).toLocaleString(); },
                fmtAxis: function (v) { return (Math.round(Number(v) * 100) / 100).toLocaleString(); },
                series: [zeroSeries(daily, 'turns', 'Turns', SLOT[2]), zeroSeries(daily, 'api_usd', 'API-equivalent $', SLOT[3])] }),
                'two units on one axis — read the table twin for the exact numbers') +
            '</div>';
        html += card('By model', table([{ t: 'Provider' }, { t: 'Model' }, { t: 'Turns', r: true }, { t: 'Input', r: true }, { t: 'Output', r: true },
            { t: 'API $', r: true }, { t: 'p50 latency', r: true }, { t: 'Tool calls', r: true }, { t: 'Errors', r: true }],
            (d.by_model || []).map(function (m) {
                return [swatch(ZERO_PROVIDER_COLOR[m.provider] || OTHER) + esc(m.provider || '—'), clip(m.model || '—'), n0(m.turns),
                    esc(compact(m.input_tokens)), esc(compact(m.output_tokens)), esc(usd(m.api_usd)), esc(zeroMs(m.p50_latency_ms)),
                    n0(m.tool_calls), m.errors ? sevPill('serious', n0(m.errors)) : '0'];
            }), 'No turn recorded in this range.'), 'one row per provider/model pair');
        html += '<div class="mh-grid-2">' +
            card('By tool', table([{ t: 'Tool' }, { t: 'Risk' }, { t: 'Calls', r: true }, { t: 'Errors', r: true }, { t: 'p50', r: true }],
                (d.by_tool || []).map(function (x) {
                    return [clip(x.name), sevPill(ZERO_RISK[x.risk] || 'warning', x.risk || 'read'), n0(x.calls),
                        x.errors ? sevPill('serious', n0(x.errors)) : '0', esc(zeroMs(x.p50_ms))];
                }), 'No tool was executed in this range.'), 'the tool audit log, failures included') +
            card('Installs', table([{ t: 'When' }, { t: 'Model' }, { t: 'Status' }, { t: 'Seconds', r: true }, { t: 'Error' }],
                (d.installs || []).slice().reverse().map(function (i) {
                    return [esc(zeroWhen(i.ts)), clip(i.model || '—'), esc(i.status || '—'), esc(i.seconds == null ? '—' : i.seconds), clip(i.error || '—')];
                }), 'No Ollama install in this range.')) +
            '</div>';
        var turnCols = [{ t: 'When' }, { t: 'Session' }, { t: 'Model' }, { t: 'In', r: true }, { t: 'Out', r: true },
            { t: 'Latency', r: true }, { t: 'Tools', r: true }, { t: 'Stop reason' }];
        html += card('Recent turns', table(turnCols, (d.recent_turns || []).map(function (r) {
            return [esc(zeroWhen(r.ts)), esc(String(r.session_id || '—').slice(0, 8)), clip(r.model || '—'), esc(compact(r.input_tokens)),
                esc(compact(r.output_tokens)), esc(zeroMs(r.latency_ms)), n0(r.tool_calls),
                r.error ? sevPill('critical', r.stop_reason || 'error') : esc(r.stop_reason || '—')];
        })), 'newest first');
        html += card('Recent errors', table([{ t: 'When' }, { t: 'Model' }, { t: 'Stop reason' }, { t: 'Error' }],
            (d.recent_errors || []).map(function (r) {
                return [esc(zeroWhen(r.ts)), clip(r.model || '—'), esc(r.stop_reason || '—'), clip(r.error || '—')];
            }), 'No turn failed in this range.'));
        html += card('How these numbers are made', notes(d.notes), (d.sources || []).join(' · '));
        return html;
    }

    // ── quota: Claude's own meter + the two costs (quota_meter.py) ───────────
    function money(v, cur) {
        if (v == null) return '—';
        v = Number(v);
        var s = Math.abs(v) < 0.01 && v !== 0 ? v.toFixed(4) : Math.abs(v) < 100 ? v.toFixed(2) : Math.round(v).toLocaleString();
        return (cur === 'EUR' ? '€' : cur === 'USD' ? '$' : (cur || '') + ' ') + s;
    }
    function untilText(ts) {
        if (!ts) return '—';
        var s = ts - Date.now() / 1000;
        if (s <= 0) return 'now';
        var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
        return h >= 48 ? Math.floor(h / 24) + 'd ' + (h % 24) + 'h' : h ? h + 'h ' + pad2(m) + 'm' : m + 'm';
    }
    function localTs(ts) {
        if (!ts) return '—';
        var d = new Date(ts * 1000);
        return d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' }) + ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
    }
    var LANE_PROD = SLOT[2], LANE_INFRA = SLOT[0];
    var LANE_NAME = { production: 'workflow', session_tree: 'session tree', interactive: 'interactive' };
    // The production/infrastructure split of the Claude Code share. It hangs directly under
    // "Claude Code on this machine" because it divides exactly that number and nothing else:
    // other surfaces leave no transcript here, so they can never be attributed to a lane.
    function laneFacts(w, cur) {
        var L = w.lanes || {}, sides = L.sides || {};
        var prod = sides.production || {}, infra = sides.infrastructure || {};
        if (prod.pct == null && infra.pct == null) return '';
        var bar = propBar([{ label: 'Production workflows', v: prod.api_usd || 0, color: LANE_PROD },
                           { label: 'Building infrastructure', v: infra.api_usd || 0, color: LANE_INFRA }],
            'production vs infrastructure, share of the work on this machine');
        return '<div class="mh-lane-split">' + bar + '</div>' +
            fact('↳ Production workflows', (prod.pct == null ? '—' : pct(prod.pct, 0)) + ' · ' + money(prod.subscription_eur, cur),
                'pipelines producing content, and the trees that built content') +
            fact('↳ Building infrastructure', (infra.pct == null ? '—' : pct(infra.pct, 0)) + ' · ' + money(infra.subscription_eur, cur),
                'operator sessions, and the trees that built the stack');
    }
    // Every lane the week was spent in, production first. A tree row keeps its slug so the
    // operator can tell at a glance which side each one was filed under, and correct it:
    // the keyword lists behind that call are `lanes` in data/runtime/quota_config.json.
    function laneCard(w, cur) {
        var L = w.lanes || {}, all = L.rows || [];
        if (!all.length) return '';
        var byLane = L.by_lane || {};
        var rows = all.map(function (r) {
            var u = r.usage || {};
            var what = r.lane === 'interactive' ? clip(shortCwd(r.label), r.label)
                : r.tree ? clip(r.tree, r.tree) : esc(r.label);
            return [swatch(r.side === 'production' ? LANE_PROD : LANE_INFRA) +
                    esc(r.side === 'production' ? 'production' : 'infrastructure'),
                esc(LANE_NAME[r.lane] || r.lane), what, n0(r.sessions), n0(u.messages),
                esc(usd(r.api_usd)), r.share == null ? '—' : pct(r.share * 100, 1),
                esc(money(r.subscription_eur, cur))];
        });
        var aside = ['workflows ' + pct((byLane.production || {}).pct || 0, 1),
                     'session trees ' + pct((byLane.session_tree || {}).pct || 0, 1),
                     'interactive ' + pct((byLane.interactive || {}).pct || 0, 1)].join(' · ') +
            (L.unclassified_api_usd ? ' · ' + usd(L.unclassified_api_usd) + ' unclassified' : '');
        return card('Production workflows vs infrastructure — this Claude week',
            table([{ t: 'Side' }, { t: 'Lane' }, { t: 'What' }, { t: 'Sessions', r: true }, { t: 'Messages', r: true },
                   { t: 'API $', r: true }, { t: 'Share', r: true }, { t: 'Subscription ' + cur, r: true }],
                rows, 'No transcript in this week yet.'),
            aside);
    }
    // A working directory is only interesting from the project folder down.
    function shortCwd(cwd) {
        if (!cwd) return 'unknown';
        var parts = String(cwd).split('/').filter(Boolean);
        return parts.length <= 2 ? cwd : '…/' + parts.slice(-2).join('/');
    }
    function renderQuota(d) {
        var cfg = d.config || {}, cur = cfg.currency || 'EUR', w = d.week || {}, s = d.sample, st = d.status || {};
        var sess = w.session || {}, rng = d.range || {}, hist = d.history || { labels: [], seven_day_pct: [], five_hour_pct: [] };
        var util = w.utilization_pct, sUtil = sess.utilization_pct;
        var rateVerdict = w.subscription_cheaper == null ? 'no sample yet'
            : w.subscription_cheaper ? 'subscription is the cheaper way to buy this week\'s work'
            : 'API billing would have been cheaper this week';
        var html = '';
        if (!s) html += '<p class="mh-banner">No sample of Claude\'s meter yet' + (st.last_error ? ': ' + esc(st.last_error) : '') + '. Utilization and subscription columns stay empty until the first successful fetch.</p>';
        else if (st.last_error) html += '<p class="mh-banner">Last live fetch failed: ' + esc(st.last_error) + ' — showing the sample from ' + esc(localTs(s.ts)) + '.</p>';
        html += '<div class="mh-tiles">' +
            tile('Week used', util == null ? '—' : pct(util, 0), util == null ? '' : 'resets in ' + untilText(w.resets_at) + ' · ' + localTs(w.resets_at)) +
            tile('Session used (5 h)', sUtil == null ? '—' : pct(sUtil, 0), sUtil == null ? '' : 'resets in ' + untilText(sess.resets_at) + ' · ' + usd(sess.api_usd) + ' API-equivalent in this window') +
            tile('Subscription used this week', money(w.consumed, cur), 'of ' + money(w.weekly_price, cur) + ' per week · ' + money(w.price_per_pct, cur) + ' per % point') +
            tile('Remaining this week', money(w.remaining, cur), w.projected_utilization_pct == null ? '' : 'straight-line projection: ' + pct(w.projected_utilization_pct, 0) + ' at week end') +
            tile('API-equivalent this week', usd(w.api_usd), '≈ ' + money(w.api_eur, cur) + ' at ' + cfg.eur_per_usd + ' ' + cur + '/$ · what API billing would have charged') +
            tile('Effective rate', w.eur_per_api_usd == null ? '—' : money(w.eur_per_api_usd, cur) + ' / API-$', rateVerdict + (w.eur_per_api_usd == null ? '' : ' · API would be ' + cfg.eur_per_usd + ' ' + cur + ' / $')) +
            '</div>';
        var meters = '';
        if (s) {
            meters += meter('Current week (all models)', util || 0, 100, pct(util, 0), 'window ' + localTs(w.window_started_at) + ' → ' + localTs(w.resets_at) + ' · ' + pct((w.elapsed_fraction || 0) * 100, 0) + ' of the week elapsed', 75, 90);
            meters += meter('Current session (5 h)', sUtil || 0, 100, pct(sUtil, 0), 'resets ' + localTs(sess.resets_at), 75, 90);
            (s.scoped || []).forEach(function (x) { meters += meter('Weekly limit — ' + (x.name || x.kind), x.pct || 0, 100, pct(x.pct, 0), x.resets_at ? 'resets ' + localTs(x.resets_at) : '', 75, 90); });
        }
        var surf = s && s.surfaces ? Object.keys(s.surfaces).map(function (k) { return { label: k.replace('_', ' '), v: s.surfaces[k] }; }).filter(function (p) { return p.v; }) : [];
        html += '<div class="mh-grid-2">' +
            card('Claude\'s meter', meters || '<p class="mh-empty">No sample yet.</p>',
                s ? 'sampled ' + ago(new Date(s.ts * 1000).toISOString()) + ' · ' + esc(st.tier || s.tier || '') : '') +
            card('Where this week went', (surf.length ? propBar(surf.map(function (p, i) { return { label: p.label, v: p.v, color: SLOT[i % SLOT.length] }; }), 'share of the weekly meter by surface') +
                '<div class="mh-legend">' + surf.map(function (p, i) { return '<span>' + swatch(SLOT[i % SLOT.length]) + esc(p.label + ' ' + pct(p.v, 0)) + '</span>'; }).join('') + '</div>' : '<p class="mh-empty">No surface split in the sample.</p>') +
                '<dl class="mh-facts">' +
                fact('Claude Code on this machine', money(w.consumed_claude_code, cur), 'split by model below') +
                laneFacts(w, cur) +
                fact('Other surfaces', money(w.consumed_other_surfaces, cur), 'claude.ai chats, Cowork — same meter, no transcript here') +
                fact('Plan', esc(cfg.plan_label || ''), money(cfg.subscription_price, cur) + ' per ' + (cfg.billing === 'days' ? cfg.billing_days + ' days' : 'calendar month') + ' = ' + money(w.weekly_price, cur) + ' per Claude week') +
                '</dl>') +
            '</div>';
        var rows = (w.models || []).map(function (m, i) {
            var u = m.usage || {};
            return [swatch(SLOT[i % SLOT.length]) + esc(m.model), n0(u.messages), esc(compact(u.input)), esc(compact(u.output)),
                esc(compact((u.cache_5m || 0) + (u.cache_1h || 0))), esc(compact(u.cache_read)), esc(usd(m.api_usd)), esc(money(m.api_eur, cur)),
                m.share == null ? '—' : pct(m.share * 100, 1), esc(money(m.subscription_eur, cur))];
        });
        if (w.consumed_other_surfaces) rows.push([swatch(OTHER) + 'other surfaces', '—', '—', '—', '—', '—', '—', '—', '—', esc(money(w.consumed_other_surfaces, cur))]);
        html += card('By model — this Claude week', table([{ t: 'Model' }, { t: 'Messages', r: true }, { t: 'Input', r: true }, { t: 'Output', r: true },
            { t: 'Cache write', r: true }, { t: 'Cache read', r: true }, { t: 'API $', r: true }, { t: 'API ' + cur, r: true }, { t: 'Share', r: true }, { t: 'Subscription ' + cur, r: true }],
            rows, 'No transcript in this week yet.'),
            (w.unpriced_models && w.unpriced_models.length ? 'no price for ' + w.unpriced_models.join(', ') + ' · ' : '') + 'subscription = week used × weekly price × share of API-equivalent');
        html += laneCard(w, cur);
        // history: one point per hour (last sample of the hour)
        var hk = [], hs = [], hf = [], seenHour = {};
        (hist.ts || []).forEach(function (t, i) {
            var dt = new Date(t * 1000);
            var key = dt.getFullYear() + '-' + pad2(dt.getMonth() + 1) + '-' + pad2(dt.getDate()) + 'T' + pad2(dt.getHours()) + ':00';
            if (seenHour[key] == null) { seenHour[key] = hk.length; hk.push(key); hs.push(0); hf.push(0); }
            hs[seenHour[key]] = hist.seven_day_pct[i] || 0;
            hf[seenHour[key]] = hist.five_hour_pct[i] || 0;
        });
        var daily = rng.daily || { keys: [], by_model: {} };
        var models = Object.keys(daily.by_model || {});
        html += '<div class="mh-grid-2">' +
            card('Meter over time', chart({ keys: hk, bucket: 'hour', fmt: function (v) { return pct(v, 0); }, fmtAxis: function (v) { return pct(v, 0); }, title: 'utilization', skipEmptyRows: false,
                series: [{ id: 'week', label: 'Week', color: SLOT[0], values: hs }, { id: 'session', label: 'Session', color: SLOT[1], values: hf }] }),
                (st.samples || 0) + ' samples, hourly points') +
            card('API-equivalent per day, by model', chart({ keys: daily.keys || [], bucket: 'day', fmt: usd, fmtAxis: usd, title: 'API-equivalent',
                series: models.map(function (m, i) { return { id: m, label: m, color: SLOT[i % SLOT.length], values: daily.by_model[m] }; }) }),
                'last ' + rng.days + ' days · ' + usd(rng.api_usd) + ' total') +
            '</div>';
        var ir = d.implied_rates || [];
        html += '<div class="mh-grid-2">' +
            card('Does the split hold?', '<dl class="mh-facts">' +
                fact('% of week per API-$ (whole week)', w.pct_per_api_usd == null ? '—' : w.pct_per_api_usd.toFixed(4), 'the constant the per-model split assumes') +
                fact('Between samples', ir.length ? ir.slice(-8).map(function (r) { return r.pct_per_usd.toFixed(3); }).join(' · ') : '—', 'last intervals with movement: a steady value means the meter charges models like the price list') +
                '</dl>' + (ir.length ? '<details class="mh-twin"><summary>Intervals</summary>' + table([{ t: 'From' }, { t: 'To' }, { t: 'Δ week %', r: true }, { t: 'API $', r: true }, { t: '% per $', r: true }],
                    ir.slice().reverse().map(function (r) { return [esc(localTs(r.from)), esc(localTs(r.to)), esc(r.delta_pct), esc(usd(r.api_usd)), esc(r.pct_per_usd.toFixed(3))]; })) + '</details>' : '')) +
            card('Sources', '<dl class="mh-facts">' +
                fact('Transcripts', n0((d.scan || {}).files), n0((d.scan || {}).messages) + ' messages · ' + n0((d.scan || {}).parsed_now) + ' parsed now · ' + n0((d.scan || {}).from_cache) + ' from cache') +
                fact('Meter samples', n0(st.samples), st.last_ok ? 'last ok ' + localTs(st.last_ok) : 'none yet') +
                fact('Last fetch error', st.last_error ? esc(st.last_error) : 'none', st.last_error_ts ? localTs(st.last_error_ts) : '') +
                '</dl>' + notes(d.notes || []) +
                '<details class="mh-twin"><summary>Prices used (USD per 1M tokens)</summary>' +
                table([{ t: 'Model prefix' }, { t: 'Input', r: true }, { t: 'Output', r: true }, { t: 'Cache write 5m', r: true }, { t: 'Cache write 1h', r: true }, { t: 'Cache read', r: true }],
                    (d.pricing || []).map(function (p) { return [esc(p.model_prefix), esc(usd(p.input)), esc(usd(p.output)), esc(usd(p.cache_write_5m)), esc(usd(p.cache_write_1h)), esc(usd(p.cache_read))]; })) +
                (d.legacy_cli ? note('Installed CLI ' + d.legacy_cli.version + ': ' + d.legacy_cli.note) : '') + '</details>') +
            '</div>';
        return html;
    }

    var RENDER = { overview: renderOverview, analytics: function (d) { return window.DashboardAnalytics ? window.DashboardAnalytics.html(d) : '<p class="mh-banner">dashboard_analytics.js did not load.</p>'; }, pipelines: renderPipelines, characters: renderCharacters, llm: renderLlm,
        quota: renderQuota, quality: renderQuality, system: renderSystem, agents: renderAgents, zero: renderZero,
        test_data: function (d) { return window.DashboardTestData ? window.DashboardTestData.html(d) : '<p class="mh-banner">dashboard_testdata.js did not load.</p>'; },
        capabilities: function (d) { return window.DashboardCapabilities ? window.DashboardCapabilities.html(d) : '<p class="mh-banner">dashboard_capabilities.js did not load.</p>'; },
        stack_lineage: function (d) { return window.DashboardLineage ? window.DashboardLineage.html(d) : '<p class="mh-banner">dashboard_lineage.js did not load.</p>'; },
        expansion: function (d) { return window.DashboardExpansion ? window.DashboardExpansion.html(d) : '<p class="mh-banner">dashboard_expansion.js did not load.</p>'; } };

    // Tabs whose board owns its own DOM: the module renders and mounts, and an unchanged
    // data_version on a poll keeps the DOM so an open page/board is not closed underneath.
    function boardOf(tab) {
        if (tab === 'analytics') return window.DashboardAnalytics || null;
        if (tab === 'test_data') return window.DashboardTestData || null;
        if (tab === 'capabilities') return window.DashboardCapabilities || null;
        if (tab === 'stack_lineage') return window.DashboardLineage || null;
        if (tab === 'expansion') return window.DashboardExpansion || null;
        return null;
    }

    // ── "Checked" indicator (every tab) ───────────────────────────────
    // One badge in the metrics header, written on every paint and every poll, so all
    // eleven subtabs say when they were last read — not only the three that ship their
    // own board. "Updated" is claimed only when the payload actually moved: analytics,
    // test_data and capabilities ship a data_version, and the rest are fingerprinted
    // from the payload with generated_at/compute_ms dropped, so a server recompute that
    // returns the same numbers still reads "Checked".
    function fingerprint(data) {
        if (!data) return '';
        if (data.data_version) return String(data.data_version);
        var str;
        try {
            str = JSON.stringify(data, function (k, v) {
                return (k === 'generated_at' || k === 'compute_ms') ? undefined : v;
            });
        } catch (e) { return ''; }
        if (!str) return '';
        var h = 5381;
        for (var i = 0; i < str.length; i++) h = (((h * 33) ^ str.charCodeAt(i)) >>> 0);
        return h.toString(16);
    }
    // A failed read must not leave the last good time standing as if it were fresh.
    function liveFailed(tab, err) {
        var live = byId('metrics-live');
        var el = byId('metrics-live-text');
        if (!live || !el) return;
        var now = new Date();
        var hhmmss = pad2(now.getHours()) + ':' + pad2(now.getMinutes()) + ':' + pad2(now.getSeconds());
        el.textContent = 'Check failed ' + hhmmss;
        live.classList.remove('mh-live-idle', 'mh-live-flash');
        live.classList.add('mh-live-stale');
        live.setAttribute('title', TAB_LABELS[tab] + ' could not be read at ' + hhmmss + ': ' + ((err && err.message) || err));
    }
    // A subtab with no hub endpoint still owes the operator a time: it is the same shared
    // badge, it just reports when the panel was last drawn rather than last read.
    function localStamp(tab) {
        var live = byId('metrics-live');
        var el = byId('metrics-live-text');
        if (!live || !el) return;
        var now = new Date();
        var hhmmss = pad2(now.getHours()) + ':' + pad2(now.getMinutes()) + ':' + pad2(now.getSeconds());
        el.textContent = 'Checked ' + hhmmss;
        live.classList.remove('mh-live-idle', 'mh-live-stale', 'mh-live-flash');
        live.setAttribute('title', TAB_LABELS[tab] + ' drawn at ' + hhmmss +
            '\nthis subtab reads its own sources — use its Scan buttons');
    }
    function liveStamp(tab, key, data) {
        var live = byId('metrics-live');
        var el = byId('metrics-live-text');
        if (!live || !el) return;
        var fp = fingerprint(data);
        var changed = !!(fp && _stamp[key] && _stamp[key] !== fp);
        if (fp) _stamp[key] = fp;
        var now = new Date();
        var hhmmss = pad2(now.getHours()) + ':' + pad2(now.getMinutes()) + ':' + pad2(now.getSeconds());
        el.textContent = (changed ? 'Updated ' : 'Checked ') + hhmmss;
        live.classList.remove('mh-live-idle');
        live.classList.remove('mh-live-stale');
        var ms = POLL_MS[tab];
        live.setAttribute('title', TAB_LABELS[tab] + ' checked at ' + hhmmss +
            (ms ? '\nre-read every ' + Math.round(ms / 1000) + ' s' : '\nno automatic poll — use Refresh') +
            (data && data.generated_at ? '\nserver read ' + when(data.generated_at) : '') +
            (fp ? '\ndata version ' + fp : '') +
            (data && data.compute_ms != null ? '\ncomputed in ' + n0(data.compute_ms) + ' ms' : ''));
        live.classList.remove('mh-live-flash');
        if (changed) {
            void live.offsetWidth;                       // restart the flash on a repeat change
            live.classList.add('mh-live-flash');
            setTimeout(function () { live.classList.remove('mh-live-flash'); }, 1800);
        }
    }

    // ── detail overlay: the rows behind one Quality number or verdict ────────
    // The tab ships a token with every number and verdict it draws; this asks the same
    // section endpoint for the rows behind that token (?detail=<token>) and draws them.
    // A detail can link on to another one, so the overlay keeps a back stack.
    var _detailToken = null;
    var _detailStack = [];
    var _detailCache = {};
    var _detailReturn = null;

    function detailOverlay() {
        var ov = byId('mh-overlay');
        if (ov) return ov;
        ov = document.createElement('div');
        ov.id = 'mh-overlay';
        ov.className = 'mh-overlay';
        ov.setAttribute('role', 'dialog');
        ov.setAttribute('aria-modal', 'true');
        ov.setAttribute('aria-label', 'Metric detail');
        document.body.appendChild(ov);
        ov.addEventListener('click', function (e) {
            if (e.target === ov || e.target.closest('[data-qclose]')) { closeDetail(); return; }
            if (e.target.closest('[data-qback]')) { backDetail(); return; }
            var link = e.target.closest('[data-qdetail]');
            if (link) openDetail(link.getAttribute('data-qdetail'), 'push');
        });
        return ov;
    }

    function openDetail(token, mode) {
        if (!token) return;
        var ov = detailOverlay();
        if (!_detailToken) _detailReturn = document.activeElement;
        if (mode === 'push' && _detailToken) _detailStack.push(_detailToken);
        else if (mode !== 'back') _detailStack = [];
        _detailToken = token;
        document.body.classList.add('mh-overlay-open');
        hideTip();
        var key = token + ':' + _range;
        if (_detailCache[key]) { paintDetail(_detailCache[key]); return; }
        paintDetail({ loading: true, title: 'Reading the rows behind it…' });
        fetch('/api/metrics/hub/quality?days=' + _range + '&detail=' + encodeURIComponent(token),
            { credentials: 'same-origin', cache: 'no-store' })
            .then(function (r) {
                return r.json().then(function (j) { return { ok: r.ok, status: r.status, body: j }; },
                    function () { return { ok: false, status: r.status, body: null }; });
            })
            .then(function (res) {
                var doc = res.body && res.body.detail;
                if (!doc) throw new Error((res.body && res.body.message) || ('HTTP ' + res.status));
                if (!doc.ok) throw new Error(doc.error || 'the hub found no rows behind that number');
                _detailCache[key] = doc;
                if (_detailToken === token) paintDetail(doc);
            })
            .catch(function (err) {
                if (_detailToken !== token) return;
                paintDetail({ title: 'Could not open that detail', error: err.message || String(err) });
            });
    }

    function backDetail() {
        var prev = _detailStack.pop();
        if (prev == null) { closeDetail(); return; }
        openDetail(prev, 'back');
    }

    function closeDetail() {
        var ov = byId('mh-overlay');
        if (ov) ov.remove();
        document.body.classList.remove('mh-overlay-open');
        _detailToken = null;
        _detailStack = [];
        hideTip();
        if (_detailReturn && _detailReturn.focus) { try { _detailReturn.focus(); } catch (e) { /* gone */ } }
        _detailReturn = null;
    }

    function paintDetail(doc) {
        var ov = byId('mh-overlay');
        if (!ov) return;
        ov.innerHTML = detailHtml(doc);
        ov.scrollTop = 0;
        var first = ov.querySelector('[data-qback], [data-qclose]');
        if (first) first.focus();
    }

    function detailHtml(d) {
        var head = '<header class="mh-detail-head"><div><h3>' + esc(d.title || 'Detail') + '</h3>' +
            (d.subtitle ? '<p>' + esc(d.subtitle) + '</p>' : '') + '</div>' +
            '<div class="mh-detail-actions">' +
            (_detailStack.length ? '<button type="button" class="mh-detail-btn" data-qback>← Back</button>' : '') +
            '<button type="button" class="mh-detail-btn" data-qclose>Close ✕</button></div></header>';
        var body;
        if (d.loading) body = '<p class="mh-empty">Loading…</p>';
        else if (d.error) body = '<p class="mh-banner">' + esc(d.error) + '</p>';
        else {
            var facts = (d.facts && d.facts.length) ? '<dl class="mh-facts mh-facts-wide">' +
                d.facts.map(function (x) { return fact(x.label, x.value, x.sub); }).join('') + '</dl>' : '';
            var tables = (d.tables || []).map(function (t) {
                var n = (t.rows || []).length;
                var aside = t.limited ? 'showing the newest ' + n0(n) + ' of ' + n0(t.total)
                    : (t.total ? plural(t.total, 'row') : '');
                return card(esc(t.title), (t.note ? note(t.note) : '') + detailTable(t), aside);
            }).join('');
            body = (d.window ? '<p class="mh-detail-window">Window: ' + esc(d.window) + '</p>' : '') + facts + tables +
                ((d.notes && d.notes.length) ? card('How this is counted', notes(d.notes)) : '');
        }
        return '<div class="mh-detail">' + head + '<div class="mh-detail-body">' + body + '</div></div>';
    }

    // ── loading, tabs, polling ────────────────────────────────────────────────
    function isVisible() { var p = byId('panel-metrics'); return !!(p && p.offsetParent !== null); }

    function paint(tab, panel, data, key) {
        // Analytics (2026-09-18) / Test Data (2026-09-22): the module owns the board. Same
        // data_version on a poll -> keep the DOM (an open board stays open), just note the check.
        var board = boardOf(tab);
        if (board) {
            if (panel.getAttribute('data-key') === key && board.same(panel, data)) {
                board.touch(panel, data);
                liveStamp(tab, key, data);
                panel.classList.remove('mh-refreshing');
                schedulePoll(tab);
                return;
            }
        }
        _charts = [];
        _tips = [];
        var html;
        try {
            html = RENDER[tab](data);
        } catch (e) {
            console.error('[metrics] render ' + tab, e);
            html = '<p class="mh-banner">Could not draw ' + esc(TAB_LABELS[tab]) + ': ' + esc(e.message) + '</p>';
        }
        panel.innerHTML = html;
        panel.setAttribute('data-key', key);
        panel.classList.remove('mh-refreshing');
        drawCharts(panel);
        if (board) board.mount(panel, data);
        liveStamp(tab, key, data);
        var meta = byId('metrics-generated-at');
        // The compute time lives in the indicator's hover title now, not on the header line.
        if (meta) meta.textContent = 'Updated ' + when(data.generated_at) +
            (rangeApplies(tab) ? ' · ' + rangeLabel() : '');
        schedulePoll(tab);
    }

    function load(tab, force, fresh) {
        var panel = byId('metrics-content-' + tab);
        if (!panel) return;
        if (LOCAL[tab]) { mountLocal(tab); localStamp(tab); return; }
        var key = tab + ':' + _range;
        if (_cache[key] && !force) { paint(tab, panel, _cache[key], key); return; }
        if (panel.getAttribute('data-key') && panel.childElementCount) panel.classList.add('mh-refreshing');
        else panel.innerHTML = '<p class="mh-empty">Loading…</p>';
        if (_inflight[key]) return;
        _inflight[key] = true;
        fetch('/api/metrics/hub/' + tab + '?days=' + _range + (fresh ? '&fresh=1' : ''), { credentials: 'same-origin', cache: 'no-store' })
            .then(function (r) {
                return r.json().then(function (j) { return { ok: r.ok, status: r.status, body: j }; },
                    function () { return { ok: false, status: r.status, body: null }; });
            })
            .then(function (res) {
                delete _inflight[key];
                if (!res.ok || !res.body || res.body.success === false) {
                    throw new Error((res.body && res.body.message) || ('HTTP ' + res.status));
                }
                _cache[key] = res.body;
                if (_tab === tab && tab + ':' + _range === key) paint(tab, panel, res.body, key);
            })
            .catch(function (e) {
                delete _inflight[key];
                if (_tab !== tab) return;
                panel.classList.remove('mh-refreshing');
                panel.innerHTML = '<p class="mh-banner">Could not load ' + esc(TAB_LABELS[tab]) + ': ' + esc(e.message || e) + '</p>';
                liveFailed(tab, e);
            });
    }

    function schedulePoll(tab) {
        clearTimeout(_pollTimer);
        var ms = POLL_MS[tab];
        if (!ms) return;
        _pollTimer = setTimeout(function () {
            if (_tab !== tab) return;
            if (document.hidden || !isVisible()) { schedulePoll(tab); return; }
            load(tab, true, false);
        }, ms);
    }

    function showTab(tab) {
        if (TABS.indexOf(tab) < 0) tab = 'overview';
        _tab = tab;
        store(TAB_KEY, tab);
        clearTimeout(_pollTimer);
        hideTip();
        closeDetail();
        TABS.forEach(function (t) { var b = t !== tab && boardOf(t); if (b) b.close(); });
        document.querySelectorAll('#panel-metrics .metrics-subtab').forEach(function (btn) {
            var on = btn.getAttribute('data-metric') === tab;
            btn.classList.toggle('active', on);
            btn.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        document.querySelectorAll('#panel-metrics .metrics-panel').forEach(function (p) {
            var on = p.id === 'metrics-content-' + tab;
            p.style.display = on ? 'block' : 'none';
            p.classList.toggle('active', on);
        });
        var rangeEl = byId('metrics-range');
        if (rangeEl) rangeEl.style.display = rangeApplies(tab) ? '' : 'none';
        if (LOCAL[tab]) {
            var meta = byId('metrics-generated-at');
            if (meta) meta.textContent = TAB_LABELS[tab] + ' — functionality status, scan and diagnostics';
        }
        load(tab, false, false);
    }

    function syncRange() {
        document.querySelectorAll('#metrics-range [data-days]').forEach(function (b) {
            b.setAttribute('aria-pressed', +b.getAttribute('data-days') === _range ? 'true' : 'false');
        });
    }

    function refreshAll() {
        _cache = {};
        _detailCache = {};
        load(_tab, true, true);
    }

    function bind(panel) {
        panel.querySelectorAll('.metrics-subtab').forEach(function (btn) {
            btn.addEventListener('click', function () { showTab(this.getAttribute('data-metric')); });
        });
        var range = byId('metrics-range');
        if (range) range.addEventListener('click', function (e) {
            var b = e.target.closest('[data-days]');
            if (!b) return;
            _range = +b.getAttribute('data-days');
            closeDetail();
            store(RANGE_KEY, String(_range));
            syncRange();
            load(_tab, false, false);
        });
        var ref = byId('metrics-refresh-btn');
        if (ref) ref.addEventListener('click', refreshAll);
        panel.addEventListener('click', function (e) {
            var go = e.target.closest('[data-goto]');
            if (go) { showTab(go.getAttribute('data-goto')); return; }
            var det = e.target.closest && e.target.closest('[data-qdetail]');
            if (det) { openDetail(det.getAttribute('data-qdetail'), 'root'); return; }
            if (e.target && e.target.__detail) { openDetail(e.target.__detail, 'root'); return; }
        });
        // Escape closes the overlay wherever focus ended up inside it.
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && byId('mh-overlay')) { e.stopPropagation(); closeDetail(); }
        });
        function onMove(e) {
            var data = tipFor(e.target);
            if (data) showTip(data, e.clientX, e.clientY); else hideTip();
        }
        panel.addEventListener('pointermove', onMove);
        panel.addEventListener('pointerleave', hideTip);
        panel.addEventListener('focusin', function (e) {
            var data = tipFor(e.target);
            if (!data) return;
            var r = e.target.getBoundingClientRect();
            showTip(data, r.left + r.width / 2, r.bottom);
        });
        panel.addEventListener('focusout', hideTip);
        var resizeTimer = null;
        window.addEventListener('resize', function () {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(function () {
                var active = byId('metrics-content-' + _tab);
                if (active && isVisible()) {
                    drawCharts(active);
                    var b = boardOf(_tab);
                    if (b) b.redraw(active);
                }
            }, 150);
        });
    }

    function init() {
        var panel = byId('panel-metrics');
        if (!panel) return;
        if (!_bound) {
            _bound = true;
            var r = parseInt(store(RANGE_KEY), 10);
            if ([0, 7, 30, 90].indexOf(r) >= 0) _range = r;
            var t = store(TAB_KEY);
            if (t && TABS.indexOf(t) >= 0) _tab = t;
            // ?view=<subtab> wins over the remembered one: /mechanics redirects to
            // /metrics?view=mechanics, so an old bookmark still lands on Mechanics.
            try {
                var v = new URLSearchParams(window.location.search).get('view');
                if (v && TABS.indexOf(v) >= 0) _tab = v;
            } catch (e) { /* no URLSearchParams: fall back to the remembered subtab */ }
            syncRange();
            bind(panel);
        }
        // Only fetch when the Metrics panel is actually on screen (the panel is in every
        // dashboard page; the old script loaded an 11.7 s endpoint on each of them).
        if (isVisible()) showTab(_tab);
    }

    function render(container) { if (container) init(); }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();

    window.DashboardTabMetrics = { render: render, init: init, refresh: refreshAll };
})();
