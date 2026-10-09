// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Metrics > Test Data (2026-09-22) — a kanban of the tests that were performed.
 *
 * Data: GET /api/metrics/hub/test_data?days=N (test_data_hub.py). One card per recorded
 * test, each carrying its own graph; clicking a card opens that test's page — the same
 * graph full size with a crosshair tooltip and a table twin, plus what the test asked,
 * how it was run, what it found and what it cannot say. This file only draws: every
 * number, unit and label is decided in the collector, so card, chart, tooltip and table
 * cannot disagree. dashboard_tab_metrics.js owns the fetch/poll cycle and calls
 * html()/mount()/same()/touch()/redraw()/close() from here.
 */
(function () {
    'use strict';

    // Categorical slots in fixed order (dataviz reference palette). Colour follows the
    // series id, never its rank; status colour is reserved for state and always carries
    // an icon and a word.
    var SLOT = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7'];
    var TONE = {
        good: { bg: '#0ca30c', ink: '#fff', soft: '#e7f6e7', line: '#0ca30c' },
        critical: { bg: '#d03b3b', ink: '#fff', soft: '#fbeaea', line: '#d03b3b' },
        warning: { bg: '#fab219', ink: '#3d2a00', soft: '#fff6dc', line: '#e09400' },
        open: { bg: '#2a78d6', ink: '#fff', soft: '#e8f0fb', line: '#2a78d6' },
        neutral: { bg: '#e3e1da', ink: '#52514e', soft: '#f2f1ec', line: '#a9a79f' }
    };
    var REF_COLOR = { limit: '#d03b3b', null: '#52514e', baseline: '#52514e', target: '#0ca30c' };

    var _data = null;
    var _panel = null;
    var _open = null;      // id of the open test page
    var _hosts = [];       // [{host, chart, opts}] redrawn on resize
    var _filter = { status: 'all', q: '' };

    // ── formatting ───────────────────────────────────────────────────────────
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }
    function pad2(x) { return (x < 10 ? '0' : '') + x; }
    function n0(v) { return v == null ? '—' : Number(v).toLocaleString(); }
    function sig(v) {
        if (v == null || isNaN(v)) return '—';
        v = Number(v);
        var a = Math.abs(v);
        if (a === 0) return '0';
        if (a >= 1000) return Math.round(v).toLocaleString();
        if (a >= 100) return String(Math.round(v * 10) / 10);
        if (a >= 1) return String(Math.round(v * 100) / 100);
        if (a >= 0.01) return String(Math.round(v * 1000) / 1000);
        return String(Number(v.toPrecision(2)));
    }
    function compact(v) {
        if (v == null || isNaN(v)) return '—';
        v = Number(v);
        var a = Math.abs(v);
        if (a >= 1e9) return (v / 1e9).toFixed(1) + 'B';
        if (a >= 1e6) return (v / 1e6).toFixed(1) + 'M';
        if (a >= 1e4) return Math.round(v / 1e3) + 'K';
        if (a >= 1e3) return (v / 1e3).toFixed(1) + 'K';
        return sig(v);
    }
    var SUFFIX = { ms: ' ms', s: ' s', min: ' min', h: ' h', b: ' B', kb: ' kB', mb: ' MB', gb: ' GB',
        fps: ' fps', hz: ' Hz', c: ' °C', w: ' W', kwh: ' kWh', px: ' px', tokens: ' tok', count: '', score: '' };
    function fmt(v, unit) {
        if (v == null || v === '') return '—';
        if (typeof v === 'string' && isNaN(Number(v))) return v;
        var u = unit || 'number';
        if (u === 'text') return String(v);
        var num = Number(v);
        if (isNaN(num)) return String(v);
        if (u === 'int') return Math.round(num).toLocaleString();
        if (u === 'pct') return sig(num) + '%';
        if (u === 'ratio') return sig(num);
        if (u === 'x') return sig(num) + '×';
        if (u === 'usd') return (num < 0 ? '-$' : '$') + sig(Math.abs(num));
        if (u === 'eur') return '€' + sig(num);
        if (u === 'tokens') return compact(num) + ' tok';
        if (Object.prototype.hasOwnProperty.call(SUFFIX, u)) return sig(num) + SUFFIX[u];
        if (u === 'number') return sig(num);
        return sig(num) + ' ' + u;                       // an unknown unit is printed as text
    }
    function axisFmt(unit, step) {
        var dec = null;
        if (step != null && step > 0 && step < 1000) {
            dec = step >= 10 ? 0 : step >= 1 ? 1 : step >= 0.1 ? 2 : 3;
        }
        function base(v) {
            if (dec == null || Math.abs(v) >= 10000) return compact(v);
            return Number(v).toFixed(dec);
        }
        return function (v) {
            if (unit === 'pct') return base(v) + '%';
            if (unit === 'usd') return '$' + base(v);
            if (unit === 'eur') return '€' + base(v);
            if (unit === 'tokens') return compact(v);
            return base(v);
        };
    }
    function dur(s) {
        if (s == null || isNaN(s)) return '—';
        s = Number(s);
        if (s < 90) return sig(s) + ' s';
        if (s < 5400) return Math.round(s / 60) + ' min';
        return (Math.round(s / 360) / 10) + ' h';
    }
    function ago(s) {
        if (s == null) return '—';
        if (s < 90) return 'just now';
        if (s < 5400) return Math.round(s / 60) + ' min ago';
        if (s < 172800) return Math.round(s / 3600) + ' h ago';
        return Math.round(s / 86400) + ' d ago';
    }
    function when(iso) { return iso ? String(iso).replace('T', ' ').slice(0, 16) : '—'; }
    function tone(t) { return TONE[t] || TONE.neutral; }
    function color(s, i) { return s && s.color ? s.color : SLOT[i % SLOT.length]; }

    function cardById(id) {
        var cs = (_data && _data.cards) || [];
        for (var i = 0; i < cs.length; i++) if (cs[i].id === id) return cs[i];
        return null;
    }
    function statusMeta(id) {
        var st = (_data && _data.statuses) || {};
        return st[id] || { label: id || 'unknown', tone: 'neutral', icon: '·' };
    }
    function chip(statusId) {
        var m = statusMeta(statusId), t = tone(m.tone);
        return '<span class="td-chip" style="background:' + t.soft + ';color:' + (m.tone === 'neutral' ? '#52514e' : t.line) +
            ';border-color:' + t.line + '33"><i style="background:' + t.bg + ';color:' + t.ink + '">' + esc(m.icon) + '</i>' + esc(m.label) + '</span>';
    }

    // ── SVG chart ────────────────────────────────────────────────────────────
    var SVGNS = 'http://www.w3.org/2000/svg';
    function svgEl(name, attrs, parent) {
        var e = document.createElementNS(SVGNS, name);
        for (var k in attrs) if (Object.prototype.hasOwnProperty.call(attrs, k) && attrs[k] != null) e.setAttribute(k, attrs[k]);
        if (parent) parent.appendChild(e);
        return e;
    }
    function niceMax(v) {
        if (!(v > 0)) return 1;
        var p = Math.pow(10, Math.floor(Math.log10(v)));
        var m = v / p;
        var steps = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
        for (var i = 0; i < steps.length; i++) if (steps[i] >= m - 1e-9) return steps[i] * p;
        return 10 * p;
    }
    function topRounded(x, y, w, h, r) {
        r = Math.min(r, w / 2, h);
        return 'M' + x + ',' + (y + h) + 'V' + (y + r) + 'Q' + x + ',' + y + ' ' + (x + r) + ',' + y +
            'H' + (x + w - r) + 'Q' + (x + w) + ',' + y + ' ' + (x + w) + ',' + (y + r) + 'V' + (y + h) + 'Z';
    }
    function axisOf(chart, which) { return which === 'y2' ? (chart.y2 || chart.y) : chart.y; }

    /**
     * Draws one chart spec (test_data_hub record schema) into host.
     * x: index bands for category/time or for columns; a linear scale for numeric x on
     * line/scatter/area. y: one scale per axis (y, optional y2). Series may carry lo/hi
     * (drawn as a band), refs are horizontal rules, vrefs vertical ones.
     * opts.preview draws the compact card graph (no axes, no tooltip).
     */
    function drawChart(host, chart, opts) {
        opts = opts || {};
        host.textContent = '';
        if (!chart || !chart.x || !chart.x.values || !chart.x.values.length) {
            host.innerHTML = '<p class="mh-note" style="margin:0">No graph in this record.</p>';
            return;
        }
        var preview = !!opts.preview;
        var W = Math.max(preview ? 120 : 320, host.clientWidth);
        var H = host.clientHeight || (preview ? 78 : 340);
        var xs = chart.x.values;
        var n = xs.length;
        var series = (chart.series || []).filter(function (s) { return s.values && s.values.length; });
        var hasY2 = !!chart.y2 && series.some(function (s) { return s.axis === 'y2'; });
        var xTitle = !preview && chart.x.label ? 16 : 0;
        var padL = preview ? 2 : 60, padR = preview ? 2 : (hasY2 ? 60 : 14), padT = preview ? 5 : 14,
            padB = preview ? 3 : (30 + xTitle);
        var pw = W - padL - padR, ph = H - padT - padB;
        if (pw <= 0 || ph <= 0) return;

        var isCols = chart.kind === 'columns';
        var numericX = chart.x.type === 'number' && !isCols;
        var band = pw / n;
        var xmin = 0, xmax = 0;
        if (numericX) {
            xmin = Math.min.apply(null, xs); xmax = Math.max.apply(null, xs);
            if (xmax === xmin) { xmax = xmin + 1; }
        }
        function xc(i) {
            if (n === 1) return padL + pw / 2;          // a one-sample test sits in the middle, not on the axis
            return numericX ? padL + ((xs[i] - xmin) / (xmax - xmin)) * pw : padL + i * band + band / 2;
        }

        // y scales (one per axis; a stacked column chart stacks on its own axis)
        function extent(axis) {
            var mx = 0, mn = 0, any = false;
            var sel = series.filter(function (s) { return (s.axis === 'y2' ? 'y2' : 'y') === axis; });
            if (isCols && chart.stacked && axis === 'y') {
                for (var j = 0; j < n; j++) {
                    var t = 0;
                    sel.forEach(function (s) { if (s.values[j] != null) { t += s.values[j]; any = true; } });
                    mx = Math.max(mx, t);
                }
            } else {
                sel.forEach(function (s) {
                    (s.hi || s.values).forEach(function (v) { if (v != null) { mx = Math.max(mx, v); any = true; } });
                    (s.lo || s.values).forEach(function (v) { if (v != null) { mn = Math.min(mn, v); any = true; } });
                });
            }
            (chart.refs || []).forEach(function (r) { if ((r.axis || 'y') === axis) { mx = Math.max(mx, r.value); mn = Math.min(mn, r.value); } });
            var ax = axisOf(chart, axis) || {};
            if (ax.unit === 'pct' && mx <= 100) mx = Math.max(mx, 100);
            if (ax.max != null) mx = ax.max;
            if (ax.min != null) mn = ax.min;
            else mn = Math.min(0, mn);
            if (!any && ax.max == null) mx = 1;
            var top = ax.max != null ? mx : niceMax(mx - Math.min(0, mn)) + Math.min(0, mn);
            if (top <= mn) top = mn + 1;
            return { min: mn, max: top };
        }
        var EY = { y: extent('y') };
        if (hasY2) EY.y2 = extent('y2');
        function yc(v, axis) {
            var e = EY[axis === 'y2' ? 'y2' : 'y'];
            return padT + ph - ((v - e.min) / (e.max - e.min)) * ph;
        }

        var svg = svgEl('svg', { width: W, height: H, viewBox: '0 0 ' + W + ' ' + H, role: 'img',
            'aria-label': chart.title || 'test graph' }, host);

        // grid + y axis
        var gridF = preview ? [0, 1] : [0, 0.25, 0.5, 0.75, 1];
        var step = (EY.y.max - EY.y.min) / 4;
        var af = axisFmt((chart.y || {}).unit, step);
        gridF.forEach(function (f) {
            var val = EY.y.min + (EY.y.max - EY.y.min) * f;
            var y = Math.round(yc(val, 'y')) + 0.5;
            svgEl('line', { x1: padL, x2: W - padR, y1: y, y2: y, stroke: f === 0 ? '#c3c2b7' : '#e6e5df', 'stroke-width': 1 }, svg);
            if (preview) return;
            var t = svgEl('text', { x: padL - 8, y: y + 4, 'text-anchor': 'end', 'class': 'td-axis' }, svg);
            t.textContent = af(val);
            if (hasY2) {
                var v2 = EY.y2.min + (EY.y2.max - EY.y2.min) * f;
                var t2 = svgEl('text', { x: W - padR + 8, y: y + 4, 'class': 'td-axis' }, svg);
                t2.textContent = axisFmt(chart.y2.unit, (EY.y2.max - EY.y2.min) / 4)(v2);
            }
        });
        if (!preview && chart.y && chart.y.label) {
            var yt = svgEl('text', { x: 12, y: padT + ph / 2, 'class': 'td-axis-title',
                transform: 'rotate(-90 12 ' + (padT + ph / 2) + ')', 'text-anchor': 'middle' }, svg);
            yt.textContent = chart.y.label + (chart.y.unit && chart.y.unit !== 'number' ? ' (' + chart.y.unit + ')' : '');
        }
        if (!preview && hasY2 && chart.y2.label) {
            var y2t = svgEl('text', { x: W - 10, y: padT + ph / 2, 'class': 'td-axis-title',
                transform: 'rotate(90 ' + (W - 10) + ' ' + (padT + ph / 2) + ')', 'text-anchor': 'middle' }, svg);
            y2t.textContent = chart.y2.label + (chart.y2.unit && chart.y2.unit !== 'number' ? ' (' + chart.y2.unit + ')' : '');
        }

        // vertical reference lines
        (chart.vrefs || []).forEach(function (r) {
            var i = xs.indexOf(numericX ? Number(r.at) : String(r.at));
            if (i < 0) return;
            var x = Math.round(xc(i)) + 0.5;
            svgEl('line', { x1: x, x2: x, y1: padT, y2: padT + ph, stroke: '#a9a79f', 'stroke-width': 1, 'stroke-dasharray': '3 3' }, svg);
            if (preview || !r.label) return;
            var vt = svgEl('text', { x: x + 4, y: padT + 11, 'class': 'td-axis' }, svg);
            vt.textContent = r.label;
        });

        // bands (lo/hi) behind everything
        series.forEach(function (s, si) {
            if (!s.lo || !s.hi) return;
            var ax = s.axis === 'y2' ? 'y2' : 'y';
            var up = '', down = '';
            for (var j = 0; j < n; j++) {
                if (s.hi[j] == null || s.lo[j] == null) continue;
                up += (up ? 'L' : 'M') + xc(j).toFixed(1) + ',' + yc(s.hi[j], ax).toFixed(1);
                down = 'L' + xc(j).toFixed(1) + ',' + yc(s.lo[j], ax).toFixed(1) + down;
            }
            if (up) svgEl('path', { d: up + down + 'Z', fill: color(s, si), 'fill-opacity': 0.13 }, svg);
        });

        // columns
        var bw = Math.max(1, Math.min(preview ? 9 : 30, band * 0.72));
        if (isCols) {
            var cols = series.filter(function (s) { return (s.kind || 'columns') !== 'line'; });
            for (var j = 0; j < n; j++) {
                if (chart.stacked) {
                    var base = yc(Math.max(0, EY.y.min), 'y'), x0 = xc(j) - bw / 2;
                    var seg = cols.filter(function (s) { return (s.values[j] || 0) > 0; });
                    seg.forEach(function (s, si) {
                        var h = (s.values[j] / (EY.y.max - EY.y.min)) * ph, top = base - h;
                        var col = color(s, series.indexOf(s));
                        if (si === seg.length - 1) svgEl('path', { d: topRounded(x0, top, bw, Math.max(h, 1.5), 4), fill: col }, svg);
                        else svgEl('rect', { x: x0, y: top + (h > 4 ? 2 : 0), width: bw, height: Math.max(h - (h > 4 ? 2 : 0), 1), fill: col }, svg);
                        base = top;
                    });
                } else {
                    var gw = Math.max(1, (bw - 2 * (cols.length - 1)) / Math.max(1, cols.length));
                    cols.forEach(function (s, si) {
                        var v = s.values[j];
                        if (v == null) return;
                        var ax = s.axis === 'y2' ? 'y2' : 'y';
                        var zero = yc(Math.max(EY[ax].min, 0), ax), top = yc(v, ax);
                        var h = Math.abs(zero - top);
                        svgEl('path', { d: topRounded(xc(j) - bw / 2 + si * (gw + 2), Math.min(zero, top), gw, Math.max(h, 1.5), 3),
                            fill: color(s, series.indexOf(s)) }, svg);
                    });
                }
            }
        }

        function linePath(s, si) {
            var ax = s.axis === 'y2' ? 'y2' : 'y';
            var col = color(s, si), d = '', pen = false;
            for (var j = 0; j < n; j++) {
                var v = s.values[j];
                if (v == null) { pen = false; continue; }
                d += (pen ? 'L' : 'M') + xc(j).toFixed(1) + ',' + yc(v, ax).toFixed(1);
                pen = true;
            }
            if (!d) return;
            var attrs = { d: d, fill: 'none', stroke: col, 'stroke-width': preview ? 1.6 : 2,
                'stroke-linejoin': 'round', 'stroke-linecap': 'round' };
            if (s.style === 'dashed') attrs['stroke-dasharray'] = '5 4';
            if (s.style === 'dotted') attrs['stroke-dasharray'] = '1 3';
            if (s.style === 'thin') attrs['stroke-width'] = preview ? 1 : 1.5;
            svgEl('path', attrs, svg);
        }
        function dots(s, si, r) {
            var ax = s.axis === 'y2' ? 'y2' : 'y';
            var col = color(s, si);
            for (var j = 0; j < n; j++) {
                var v = s.values[j];
                if (v == null) continue;
                var lonely = (j === 0 || s.values[j - 1] == null) && (j === n - 1 || s.values[j + 1] == null);
                if (preview && !lonely && n > 3) continue;
                if (!preview && !lonely && n > 60) continue;
                svgEl('circle', { cx: xc(j), cy: yc(v, ax), r: r || (lonely ? 4 : 3), fill: col,
                    stroke: '#fff', 'stroke-width': preview ? 0 : 2 }, svg);
            }
        }
        if (isCols) {
            series.forEach(function (s, si) {
                if ((s.kind || 'columns') === 'columns') return;
                if (s.kind === 'scatter') { dots(s, si, preview ? 1.8 : 3.5); return; }
                linePath(s, si);
                dots(s, si);
            });
        }
        if (!isCols) {
            series.forEach(function (s, si) {
                var kind = s.kind || chart.kind;
                var ax = s.axis === 'y2' ? 'y2' : 'y';
                if (kind === 'scatter') { dots(s, si, preview ? 1.8 : 3.5); return; }
                if (kind === 'area' || (series.length === 1 && chart.kind === 'area')) {
                    var area = '', pen = false, lastX = null, zero = yc(Math.max(EY[ax].min, 0), ax);
                    for (var j = 0; j < n; j++) {
                        var v = s.values[j];
                        if (v == null) { if (pen && lastX != null) area += 'L' + lastX + ',' + zero.toFixed(1) + 'Z'; pen = false; continue; }
                        var x = xc(j).toFixed(1);
                        area += (pen ? 'L' : 'M' + x + ',' + zero.toFixed(1) + 'L') + x + ',' + yc(v, ax).toFixed(1);
                        lastX = x; pen = true;
                    }
                    if (pen && lastX != null) area += 'L' + lastX + ',' + zero.toFixed(1) + 'Z';
                    if (area) svgEl('path', { d: area, fill: color(s, si), 'fill-opacity': 0.12 }, svg);
                }
                linePath(s, si);
                dots(s, si);        // sparse series and lonely points draw in previews too
            });
        }

        // horizontal reference rules (limit / null / target)
        (chart.refs || []).forEach(function (r) {
            var ax = r.axis === 'y2' ? 'y2' : 'y';
            if (r.value < EY[ax].min || r.value > EY[ax].max) return;
            var y = Math.round(yc(r.value, ax)) + 0.5;
            var col = REF_COLOR[r.kind] || '#52514e';
            svgEl('line', { x1: padL, x2: W - padR, y1: y, y2: y, stroke: col, 'stroke-width': 1, 'stroke-dasharray': '2 4' }, svg);
            if (preview || !r.label) return;
            var t = svgEl('text', { x: W - padR - 2, y: y - 5, 'text-anchor': 'end', 'class': 'td-axis', fill: col }, svg);
            t.textContent = r.label + ' ' + fmt(r.value, (axisOf(chart, ax) || {}).unit);
        });

        if (preview) return;

        // x labels + title
        var every = Math.max(1, Math.ceil(64 / (numericX ? pw / Math.max(1, n - 1) : band)));
        xs.forEach(function (k, i) {
            if (i % every && i !== n - 1) return;
            var t = svgEl('text', { x: xc(i), y: H - 12 - xTitle, 'text-anchor': 'middle', 'class': 'td-axis' }, svg);
            var lbl = chart.x.type === 'time' ? String(k).replace('T', ' ').slice(0, 16) : String(k);
            t.textContent = lbl.length > 14 ? lbl.slice(0, 13) + '…' : lbl;
        });
        if (chart.x.label) {
            var xt = svgEl('text', { x: padL + pw / 2, y: H - 2, 'text-anchor': 'middle', 'class': 'td-axis-title' }, svg);
            xt.textContent = chart.x.label + (chart.x.unit ? ' (' + chart.x.unit + ')' : '');
        }

        // crosshair: one overlay, nearest x point by pixel distance
        var cross = svgEl('g', { 'class': 'td-crosshair' }, svg);
        var vline = svgEl('line', { x1: 0, x2: 0, y1: padT, y2: padT + ph, stroke: 'rgba(11,11,11,0.35)',
            'stroke-width': 1, 'stroke-dasharray': '3 3', visibility: 'hidden' }, cross);
        var marks = [];
        var hit = svgEl('rect', { x: padL, y: padT, width: pw, height: ph, fill: 'transparent' }, svg);
        hit.style.cursor = 'crosshair';
        hit.addEventListener('pointermove', function (ev) {
            var box = svg.getBoundingClientRect();
            var px = (ev.clientX - box.left) * (W / box.width);
            var best = 0, bd = Infinity;
            for (var i = 0; i < n; i++) { var d = Math.abs(xc(i) - px); if (d < bd) { bd = d; best = i; } }
            showAt(best, ev);
        });
        hit.addEventListener('pointerleave', function () {
            hideTip(); vline.setAttribute('visibility', 'hidden');
            marks.forEach(function (m) { m.remove(); }); marks = [];
        });
        function showAt(i, ev) {
            marks.forEach(function (m) { m.remove(); }); marks = [];
            var rows = [], total = 0, anyTotal = false;
            series.forEach(function (s, si) {
                var v = s.values[i];
                if (v == null) return;
                var ax = s.axis === 'y2' ? 'y2' : 'y';
                var unit = (axisOf(chart, ax) || {}).unit;
                var txt = fmt(v, unit);
                if (s.lo && s.hi && s.lo[i] != null && s.hi[i] != null) txt += '  (' + fmt(s.lo[i], unit) + ' – ' + fmt(s.hi[i], unit) + ')';
                rows.push({ color: color(s, si), value: txt, label: s.label + (ax === 'y2' ? ' · right axis' : '') });
                total += v; anyTotal = true;
                marks.push(svgEl('circle', { cx: xc(i), cy: yc(v, ax), r: 4.5, fill: color(s, si), stroke: '#fff', 'stroke-width': 2 }, cross));
            });
            if (isCols && chart.stacked && series.length > 1 && anyTotal) rows.push({ color: null, value: fmt(total, (chart.y || {}).unit), label: 'Total' });
            (chart.refs || []).forEach(function (r) {
                rows.push({ color: REF_COLOR[r.kind] || '#52514e', value: fmt(r.value, (axisOf(chart, r.axis) || {}).unit), label: r.label || r.kind });
            });
            vline.setAttribute('x1', xc(i)); vline.setAttribute('x2', xc(i)); vline.setAttribute('visibility', 'visible');
            var head = (chart.x.label ? chart.x.label + ' ' : '') + (chart.x.type === 'time' ? String(xs[i]).replace('T', ' ').slice(0, 16) : xs[i]);
            showTip({ title: head, rows: rows }, ev.clientX, ev.clientY);
        }
    }

    // ── tooltip ──────────────────────────────────────────────────────────────
    function tipEl() {
        var t = document.getElementById('td-tooltip');
        if (!t) {
            t = document.createElement('div');
            t.id = 'td-tooltip';
            t.className = 'mh-tip';
            t.hidden = true;
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
        (data.rows || []).forEach(function (r) {
            var row = document.createElement('div');
            row.className = 'mh-tip-row';
            if (r.color) {
                var sw = document.createElement('i');
                sw.style.background = r.color;
                row.appendChild(sw);
            }
            var v = document.createElement('b');
            v.textContent = r.value;
            var l = document.createElement('span');
            l.textContent = r.label;
            row.appendChild(v);
            row.appendChild(l);
            t.appendChild(row);
        });
        t.hidden = false;
        t.style.zIndex = 10060;          // above .td-overlay (10040)
        moveTip({ clientX: x, clientY: y });
    }
    function moveTip(ev) {
        var t = document.getElementById('td-tooltip');
        if (!t || t.hidden) return;
        var vw = window.innerWidth, vh = window.innerHeight;
        var w = t.offsetWidth, h = t.offsetHeight;
        var left = ev.clientX + 16, top = ev.clientY + 16;
        if (left + w > vw - 8) left = ev.clientX - w - 16;
        if (top + h > vh - 8) top = ev.clientY - h - 16;
        t.style.left = Math.max(4, left) + 'px';
        t.style.top = Math.max(4, top) + 'px';
    }
    function hideTip() { var t = document.getElementById('td-tooltip'); if (t) t.hidden = true; }

    // ── board html ───────────────────────────────────────────────────────────
    function visible(cards) {
        var q = (_filter.q || '').toLowerCase();
        return cards.filter(function (c) {
            if (_filter.status !== 'all' && c.status !== _filter.status) return false;
            if (!q) return true;
            return (c.title + ' ' + c.question + ' ' + (c.tags || []).join(' ') + ' ' + c.verdict).toLowerCase().indexOf(q) >= 0;
        });
    }
    function cardHtml(c) {
        var h = c.headline || {};
        var legend = ((c.chart && c.chart.series) || []).slice(0, 4).map(function (s, i) {
            return '<span><i style="background:' + color(s, i) + '"></i>' + esc(s.label) + '</span>';
        }).join('');
        var val = h.value != null && h.value !== '' ? fmt(h.value, h.fmt) : '';
        return '<article class="td-card td-tone-' + esc(c.status_tone || 'neutral') + '" data-td-card="' + esc(c.id) + '" tabindex="0" role="button" aria-label="' + esc(c.title + ' — open this test') + '">' +
            '<div class="td-card-head"><div class="td-card-title">' + esc(c.title) + '</div>' + chip(c.status) + '</div>' +
            (c.question ? '<div class="td-card-q">' + esc(c.question) + '</div>' : '') +
            (val ? '<div class="td-headline"><div class="td-headline-value">' + esc(val) + '</div><div><div class="td-headline-label">' + esc(h.label) + '</div>' +
                (h.sub ? '<div class="td-headline-sub">' + esc(h.sub) + '</div>' : '') + '</div></div>' : '') +
            '<div class="td-preview" data-td-preview="' + esc(c.id) + '"></div>' +
            (legend ? '<div class="td-legend-mini">' + legend + '</div>' : '') +
            ((c.tags || []).length ? '<div class="td-tags">' + c.tags.map(function (t) { return '<span>' + esc(t) + '</span>'; }).join('') + '</div>' : '') +
            '<div class="td-card-foot"><span title="' + esc(when(c.run_at)) + '">' + esc(ago(c.age_s)) +
            (c.duration_s != null ? ' · ran ' + esc(dur(c.duration_s)) : '') + '</span><span class="td-open">open test ›</span></div>' +
            '</article>';
    }
    function html(d) {
        var s = d.summary || {};
        var st = d.statuses || {};
        var counts = s.by_status || {};
        var chips = ['all'].concat(Object.keys(st).filter(function (k) { return counts[k]; }));
        var out = '<div class="td-toolbar"><div class="td-toolbar-left">' +
            // Check time / data version / compute time: the metrics header's shared
            // "Checked HH:MM:SS" badge, not here (dashboard_tab_metrics.js).
            '<span class="td-sum"><b>' + esc(n0(s.tests)) + '</b> test' + (s.tests === 1 ? '' : 's') + ' in range' +
            (s.hidden_by_range ? ' · <b>' + esc(n0(s.hidden_by_range)) + '</b> older hidden by the range' : '') +
            (s.pass_rate_pct != null ? ' · pass rate <b>' + esc(fmt(s.pass_rate_pct, 'pct')) + '</b> of ' + esc(n0(s.decided)) + ' decided' : '') +
            (s.last_run_at ? ' · last run ' + esc(when(s.last_run_at)) : '') + '</span></div>' +
            '<div class="td-toolbar-left"><span class="td-filters">' + chips.map(function (k) {
                var lbl = k === 'all' ? 'All' : (st[k] ? st[k].label : k);
                var cnt = k === 'all' ? (s.tests || 0) : counts[k];
                return '<button type="button" class="td-fbtn' + (_filter.status === k ? ' active' : '') + '" data-td-status="' + esc(k) + '">' +
                    esc(lbl) + ' <b>' + esc(n0(cnt)) + '</b></button>';
            }).join('') + '</span>' +
            '<input type="search" class="td-search" id="td-search" placeholder="filter tests…" value="' + esc(_filter.q) + '"></div></div>';

        if (!(d.cards || []).length) {
            out += '<div class="td-empty-board"><h4>No test recorded yet</h4>' +
                '<p>A card appears here the moment a test is recorded. One JSON file per test in <code>' + esc((d.store || {}).dir || '') + '</code>, written by <code>test_data_hub.record({…})</code> — each record carries the test\'s question, method, result and its own graph.</p></div>';
            out += '<details class="mh-twin" style="margin-top:12px"><summary>How this board works</summary>' + howHtml(d) + '</details>';
            return out;
        }

        var cards = visible(d.cards || []);
        out += '<div class="td-board">';
        (d.lanes || []).forEach(function (l) {
            var mine = cards.filter(function (c) { return c.lane === l.id; });
            if (!mine.length && !l.core && !(d.cards || []).some(function (c) { return c.lane === l.id; })) return;
            out += '<section class="td-lane"><div class="td-lane-head"><div><h4>' + esc(l.label) + '</h4>' +
                (l.hint ? '<span class="td-lane-hint">' + esc(l.hint) + '</span>' : '') + '</div>' +
                '<span>' + mine.length + '</span></div>' +
                (mine.length ? mine.map(cardHtml).join('') : '<p class="td-empty-lane">no test here' + (_filter.status !== 'all' || _filter.q ? ' in this filter' : ' yet') + '</p>') +
                '</section>';
        });
        out += '</div>';
        out += '<details class="mh-twin" style="margin-top:12px"><summary>Store &amp; how this board works</summary>' + howHtml(d) + '</details>';
        return out;
    }
    function howHtml(d) {
        var store = d.store || {};
        return '<div class="mh-table-wrap"><table class="mh-table"><thead><tr><th>Source</th><th>Path</th><th class="num">Files</th><th>Last write</th></tr></thead><tbody>' +
            (d.sources || []).map(function (s) {
                return '<tr><td>' + esc(s.source) + '</td><td>' + esc(s.path) + '</td><td class="num">' + esc(n0(s.files)) + '</td><td>' + esc(when(s.last_write)) + '</td></tr>';
            }).join('') + '</tbody></table></div>' +
            '<ul class="mh-notes">' + (d.how || []).map(function (t) { return '<li>' + esc(t) + '</li>'; }).join('') + '</ul>' +
            '<p class="mh-note">' + esc('Store ' + n0(store.files) + ' record files, ' + n0(Math.round((store.bytes || 0) / 1024)) + ' kB.') + '</p>';
    }

    // ── the test page (one card) ─────────────────────────────────────────────
    function factHtml(f) {
        return '<div class="td-fact"><div class="td-fact-label">' + esc(f.label) + '</div>' +
            '<div class="td-fact-value">' + esc(fmt(f.value, f.fmt)) + '</div>' +
            (f.sub ? '<div class="td-fact-sub">' + esc(f.sub) + '</div>' : '') + '</div>';
    }
    function laneHtml(cls, label, items) {
        return '<section class="td-kanban-lane"><h5><i class="' + cls + '"></i>' + esc(label) + '</h5>' +
            (items && items.length ? items.join('') : '<p class="td-empty-lane">nothing recorded</p>') + '</section>';
    }
    function textFact(label, value, sub) {
        if (!value) return '';
        return '<div class="td-fact"><div class="td-fact-label">' + esc(label) + '</div>' +
            '<div class="td-fact-text">' + esc(value) + '</div>' + (sub ? '<div class="td-fact-sub">' + esc(sub) + '</div>' : '') + '</div>';
    }
    function legendHtml(ch) {
        if (!ch) return '';
        var items = (ch.series || []).map(function (s, i) {
            var swatch = (s.kind || ch.kind) === 'columns' ? 'td-sw-col' : (s.style === 'dashed' || s.style === 'dotted' ? 'td-sw-dash' : '');
            return '<span><i class="' + swatch + '" style="background:' + color(s, i) + ';color:' + color(s, i) + '"></i>' + esc(s.label) +
                (s.axis === 'y2' ? ' <em>(right axis)</em>' : '') + (s.lo && s.hi ? ' <em>(band = lo–hi)</em>' : '') + '</span>';
        });
        (ch.refs || []).forEach(function (r) {
            items.push('<span><i class="td-sw-dash" style="background:' + (REF_COLOR[r.kind] || '#52514e') + ';color:' + (REF_COLOR[r.kind] || '#52514e') + '"></i>' + esc(r.label || r.kind) + '</span>');
        });
        return items.length ? '<div class="td-legend">' + items.join('') + '</div>' : '';
    }
    function chartTableHtml(ch) {
        if (!ch) return '';
        var head = '<tr><th>' + esc(ch.x.label || 'x') + '</th>' + (ch.series || []).map(function (s) {
            return '<th class="num">' + esc(s.label) + '</th>';
        }).join('') + '</tr>';
        var rows = ch.x.values.map(function (k, j) {
            return '<tr><td>' + esc(k) + '</td>' + (ch.series || []).map(function (s) {
                var unit = ((s.axis === 'y2' ? ch.y2 : ch.y) || {}).unit;
                var cell = fmt(s.values[j], unit);
                if (s.lo && s.hi && s.lo[j] != null) cell += ' (' + fmt(s.lo[j], unit) + '–' + fmt(s.hi[j], unit) + ')';
                return '<td class="num">' + esc(cell) + '</td>';
            }).join('') + '</tr>';
        }).join('');
        return '<div class="mh-table-wrap"><table class="mh-table"><thead>' + head + '</thead><tbody>' + rows + '</tbody></table></div>';
    }
    function recordTableHtml(t) {
        if (!t || !(t.columns || []).length) return '';
        return '<div class="mh-table-wrap"><table class="mh-table"><thead><tr>' +
            t.columns.map(function (c) { return '<th' + (c.r ? ' class="num"' : '') + '>' + esc(c.t) + '</th>'; }).join('') +
            '</tr></thead><tbody>' + (t.rows || []).map(function (r) {
                return '<tr>' + r.map(function (cell, i) {
                    return '<td' + (t.columns[i] && t.columns[i].r ? ' class="num"' : '') + '>' + esc(cell) + '</td>';
                }).join('') + '</tr>';
            }).join('') + '</tbody></table></div>' + (t.note ? '<p class="mh-note">' + esc(t.note) + '</p>' : '');
    }
    function pageHtml(c) {
        var result = [];
        if (c.headline && c.headline.value != null && c.headline.value !== '') {
            result.push('<div class="td-fact td-fact-lead"><div class="td-fact-label">' + esc(c.headline.label || 'Result') + '</div>' +
                '<div class="td-fact-value">' + esc(fmt(c.headline.value, c.headline.fmt)) + '</div>' +
                (c.headline.sub ? '<div class="td-fact-sub">' + esc(c.headline.sub) + '</div>' : '') + '</div>');
        }
        result = result.concat((c.facts || []).map(factHtml));
        var method = [];
        if (c.method && c.method.length) method.push('<div class="td-fact"><div class="td-fact-label">Method</div><ol class="td-steps">' +
            c.method.map(function (m) { return '<li>' + esc(m) + '</li>'; }).join('') + '</ol></div>');
        if (c.command) method.push('<div class="td-fact"><div class="td-fact-label">Command</div><pre class="mh-pre">' + esc(c.command) + '</pre></div>');
        method.push(textFact('Ran', when(c.run_at), (c.duration_s != null ? 'took ' + dur(c.duration_s) : '') + (c.run_by ? ' · ' + c.run_by : '')));
        if (c.environment && Object.keys(c.environment).length) {
            method.push('<div class="td-fact"><div class="td-fact-label">Environment</div><dl class="td-env">' +
                Object.keys(c.environment).map(function (k) {
                    return '<dt>' + esc(k) + '</dt><dd>' + esc(String(c.environment[k])) + '</dd>';
                }).join('') + '</dl></div>');
        }
        var caveats = [];
        if (c.null_model) caveats.push(textFact('Null / baseline', c.null_model));
        (c.limitations || []).forEach(function (l) { caveats.push(textFact('Limitation', l)); });
        if (c.errors && c.errors.length) caveats.push(textFact('Record problems', c.errors.join('; '), 'this record did not fully validate'));

        var extra = (c.charts || []).map(function (ch, i) {
            return '<div class="td-chart-card"><h4>' + esc(ch.title || ('Chart ' + (i + 2))) + '</h4>' + legendHtml(ch) +
                '<div class="td-chart td-chart-small" data-td-chart="extra-' + i + '"></div>' +
                '<details class="mh-twin"><summary>Table view</summary>' + chartTableHtml(ch) + '</details></div>';
        }).join('');

        return '<div class="td-sheet" role="dialog" aria-modal="true" aria-label="' + esc(c.title) + '">' +
            '<div class="td-sheet-head"><div><h3>' + esc(c.title) + ' ' + chip(c.status) + '</h3>' +
            (c.question ? '<p>' + esc(c.question) + '</p>' : '') +
            (c.verdict ? '<p class="td-verdict">' + esc(c.verdict) + '</p>' : '') + '</div>' +
            '<div class="td-sheet-actions"><span class="td-live"><i></i>live</span><button type="button" class="td-btn" data-td-close>Close ✕</button></div></div>' +
            '<div class="td-kanban">' + laneHtml('td-dot-result', 'Result', result) + laneHtml('td-dot-method', 'How it was run', method) +
            laneHtml('td-dot-caveat', 'What it cannot say', caveats) + '</div>' +
            (c.chart ? '<div class="td-chart-card"><h4>' + esc(c.chart.title || 'Measurements') + '</h4>' + legendHtml(c.chart) +
                '<div class="td-chart" data-td-chart="main"></div>' +
                (c.chart.note ? '<p class="mh-note">' + esc(c.chart.note) + '</p>' : '') +
                '<details class="mh-twin"><summary>Table view</summary>' + chartTableHtml(c.chart) + '</details></div>'
                : '<div class="td-chart-card"><p class="mh-note">This record has no graph.</p></div>') +
            extra +
            (c.table ? '<div class="td-chart-card"><h4>Breakdown</h4>' + recordTableHtml(c.table) + '</div>' : '') +
            ((c.notes || []).length ? '<div class="td-chart-card"><h4>Notes</h4><ul class="mh-notes">' +
                c.notes.map(function (t) { return '<li>' + esc(t) + '</li>'; }).join('') + '</ul></div>' : '') +
            '<div class="td-chart-card"><h4>Record</h4>' +
            '<dl class="td-env"><dt>id</dt><dd>' + esc(c.id) + '</dd><dt>lane</dt><dd>' + esc(c.lane) + '</dd>' +
            '<dt>tags</dt><dd>' + esc((c.tags || []).join(', ') || '—') + '</dd>' +
            '<dt>file</dt><dd>' + esc(c.file || '—') + '</dd><dt>recorded</dt><dd>' + esc(when(c.recorded_at)) + '</dd></dl>' +
            ((c.sources || []).length ? '<details class="mh-twin" open><summary>Sources</summary><div class="mh-table-wrap"><table class="mh-table"><thead><tr><th>Source</th><th>Path</th><th>Note</th></tr></thead><tbody>' +
                c.sources.map(function (s) { return '<tr><td>' + esc(s.source) + '</td><td>' + esc(s.path) + '</td><td>' + esc(s.note) + '</td></tr>'; }).join('') +
                '</tbody></table></div></details>' : '') +
            (c.raw ? '<details class="mh-twin"><summary>Raw measurements in the record</summary><pre class="mh-pre">' + esc(JSON.stringify(c.raw, null, 1)) + '</pre></details>' : '') +
            '</div></div>';
    }
    function drawPageCharts(ov, c) {
        _hosts = _hosts.filter(function (h) { return h.opts && h.opts.preview; });
        var main = ov.querySelector('[data-td-chart="main"]');
        if (main && c.chart) { drawChart(main, c.chart, {}); _hosts.push({ host: main, chart: c.chart, opts: {} }); }
        (c.charts || []).forEach(function (ch, i) {
            var host = ov.querySelector('[data-td-chart="extra-' + i + '"]');
            if (!host) return;
            drawChart(host, ch, {});
            _hosts.push({ host: host, chart: ch, opts: {} });
        });
    }
    function openTest(id) {
        var c = cardById(id);
        if (!c) return;
        close();
        _open = id;
        var ov = document.createElement('div');
        ov.className = 'td-overlay';
        ov.id = 'td-overlay';
        ov.innerHTML = pageHtml(c);
        document.body.appendChild(ov);
        document.body.style.overflow = 'hidden';
        ov.addEventListener('click', function (e) {
            if (e.target === ov || e.target.closest('[data-td-close]')) close();
        });
        ov.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
        ov.addEventListener('pointermove', moveTip);
        drawPageCharts(ov, c);
        var btn = ov.querySelector('[data-td-close]');
        if (btn) btn.focus();
    }
    function rerenderPage() {
        var ov = document.getElementById('td-overlay');
        var c = _open && cardById(_open);
        if (!ov) return;
        if (!c) { close(); return; }
        var scroll = ov.scrollTop;
        var openTwins = Array.prototype.map.call(ov.querySelectorAll('details[open]'), function (d) {
            return d.querySelector('summary') && d.querySelector('summary').textContent;
        });
        ov.innerHTML = pageHtml(c);
        drawPageCharts(ov, c);
        ov.querySelectorAll('details').forEach(function (d) {
            var s = d.querySelector('summary');
            if (s && openTwins.indexOf(s.textContent) >= 0) d.open = true;
        });
        ov.scrollTop = scroll;
    }
    function close() {
        var ov = document.getElementById('td-overlay');
        if (ov) ov.remove();
        document.body.style.overflow = '';
        hideTip();
        _open = null;
        _hosts = _hosts.filter(function (h) { return h.opts && h.opts.preview; });
    }

    // ── previews, live badge, public API ─────────────────────────────────────
    function drawPreviews(panel) {
        _hosts = _hosts.filter(function (h) { return !(h.opts && h.opts.preview); });
        panel.querySelectorAll('[data-td-preview]').forEach(function (host) {
            var c = cardById(host.getAttribute('data-td-preview'));
            if (!c || !c.chart) { host.innerHTML = '<p class="td-nochart">no graph in this record</p>'; return; }
            drawChart(host, c.chart, { preview: true });
            _hosts.push({ host: host, chart: c.chart, opts: { preview: true } });
        });
    }
    // No-op hook: the shared header badge is written by dashboard_tab_metrics.js.
    function liveText(d, changed) { }
    function repaintBoard() {
        if (!_panel || !_data) return;
        _panel.innerHTML = html(_data);
        drawPreviews(_panel);
        liveText(_data, false);
        var s = document.getElementById('td-search');
        if (s && _filter.q) { s.focus(); s.setSelectionRange(s.value.length, s.value.length); }
    }

    function same(panel, data) { return !!(_data && data && _data.data_version === data.data_version); }
    function touch(panel, data) {
        if (data && _data) { _data.generated_at = data.generated_at; _data.compute_ms = data.compute_ms; }
        liveText(_data || data, false);
    }
    function mount(panel, data) {
        var changed = !!(_data && data && _data.data_version !== data.data_version);
        _data = data;
        _panel = panel;
        drawPreviews(panel);
        liveText(data, changed);
        if (!panel.__tdBound) {
            panel.__tdBound = true;
            panel.addEventListener('click', function (e) {
                var f = e.target.closest('[data-td-status]');
                if (f) { _filter.status = f.getAttribute('data-td-status'); repaintBoard(); return; }
                var card = e.target.closest('[data-td-card]');
                if (card) openTest(card.getAttribute('data-td-card'));
            });
            panel.addEventListener('keydown', function (e) {
                var card = e.target.closest('[data-td-card]');
                if (card && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); openTest(card.getAttribute('data-td-card')); }
            });
            var t = null;
            panel.addEventListener('input', function (e) {
                if (!e.target.matches('#td-search')) return;
                _filter.q = e.target.value;
                clearTimeout(t);
                t = setTimeout(repaintBoard, 180);
            });
            panel.addEventListener('pointermove', moveTip);
        }
        if (_open) rerenderPage();
    }
    function redraw() {
        _hosts.forEach(function (h) { if (h.host.isConnected) drawChart(h.host, h.chart, h.opts); });
    }

    window.DashboardTestData = { html: html, mount: mount, same: same, touch: touch, redraw: redraw, close: close, open: openTest };
})();
