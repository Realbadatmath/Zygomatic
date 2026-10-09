// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Metrics > Analytics (2026-09-18) — a kanban of analytic cards.
 *
 * Data: GET /api/metrics/hub/analytics?days=N (analytics_hub.py). Every number, forecast
 * and scenario is computed there and shipped in the payload; this file draws and never
 * computes an analytic. dashboard_tab_metrics.js owns the fetch/poll cycle and calls
 * html()/mount()/same()/touch()/redraw()/close() from here.
 *
 * Board: four lanes (Production · Cost & income · Capacity & system · Quality) of cards,
 * each with a headline, a 7-day delta and a preview graph (history + trend + scenario).
 * Clicking a card opens its own board: three kanban lanes (Historical · Now · Future) of
 * facts, the full chart with a crosshair tooltip, the table twin, the assumptions and
 * the sources. Colour follows the entity (fixed slots per series id), never rank.
 */
(function () {
    'use strict';

    var SLOT = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7'];
    var OTHER = '#a9a79f';
    var COLOR = {
        scholarly: SLOT[0], kidsmusic: SLOT[1], characters: SLOT[2], assets: SLOT[2], remix_ai: SLOT[3], tokitoki: SLOT[4],
        storyteller: SLOT[5], crime: SLOT[6], video: SLOT[3], manga: SLOT[4], clipfarm: SLOT[6], stocks: SLOT[2],
        local: SLOT[1], api: SLOT[0], claude_code: SLOT[2], other: OTHER,
        busy: SLOT[0], gpu_hours: SLOT[6], coverage: OTHER, run_hours: SLOT[0], success: SLOT[2], seven_day: SLOT[0], kwh: SLOT[3]
    };
    var TREND = '#52514e';       // dashed, with a grey band
    var SCENARIO = '#0b0b0b';    // dash-dot
    var LANE_DOT = { historical: '#a9a79f', current: '#2a78d6', future: '#52514e' };

    var _data = null;
    var _panel = null;
    var _open = null;            // card id of the open board
    var _hosts = [];             // [{host, chart, opts}] for redraw
    var _lastCheck = null;

    // ── formatting ───────────────────────────────────────────────────────────
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }
    function pad2(x) { return (x < 10 ? '0' : '') + x; }
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
        if (v == null || isNaN(v)) return '—';
        v = Number(v);
        if (v === 0) return '$0';
        if (Math.abs(v) < 0.01) return '$' + v.toFixed(4);
        if (Math.abs(v) < 100) return '$' + v.toFixed(2);
        return '$' + Math.round(v).toLocaleString();
    }
    function eur(v) {
        if (v == null || isNaN(v)) return '—';
        v = Number(v);
        if (Math.abs(v) < 100) return '€' + v.toFixed(2);
        return '€' + Math.round(v).toLocaleString();
    }
    function dur(s) {
        if (s == null || isNaN(s)) return '—';
        s = Number(s);
        if (s < 1) return '<1s';
        if (s < 60) return Math.round(s) + 's';
        if (s < 3600) return Math.floor(s / 60) + 'm ' + pad2(Math.round(s % 60)) + 's';
        if (s < 86400) return Math.floor(s / 3600) + 'h ' + pad2(Math.floor((s % 3600) / 60)) + 'm';
        return (s / 86400).toFixed(1) + 'd';
    }
    function pct(v, d) { return (v == null || isNaN(v)) ? '—' : Number(v).toFixed(d != null ? d : (Math.abs(v) < 10 && v % 1 ? 1 : 0)) + '%'; }
    function hours(v) { return (v == null || isNaN(v)) ? '—' : (Math.round(v * 100) / 100) + ' h'; }
    function kwh(v) { return (v == null || isNaN(v)) ? '—' : (Math.round(v * 100) / 100) + ' kWh'; }
    function minutes(v) { return (v == null || isNaN(v)) ? '—' : (Math.round(v * 10) / 10) + ' min'; }
    function num(v) { return (v == null || isNaN(v)) ? '—' : Number(Math.round(v * 100) / 100).toLocaleString(); }
    function fmt(v, f) {
        if (v == null) return '—';
        switch (f) {
            case 'usd': return usd(v);
            case 'eur': return eur(v);
            case 'dur': return dur(v);
            case 'pct': return pct(v);
            case 'hours': return hours(v);
            case 'kwh': return kwh(v);
            case 'min': return minutes(v);
            case 'int': return n0(Math.round(v));
            case 'text': return String(v);
            default: return num(v);
        }
    }
    function axisFmt(unit) {
        switch (unit) {
            case 'usd': return function (v) { return Math.abs(v) >= 1000 ? '$' + compact(v) : usd(v); };
            case 'eur': return function (v) { return '€' + compact(v); };
            case 'pct': return function (v) { return pct(v, 0); };
            case 'hours': return function (v) { return compact(v) + ' h'; };
            case 'kwh': return function (v) { return compact(v) + ' kWh'; };
            case 'min': return function (v) { return compact(v) + ' m'; };
            default: return compact;
        }
    }
    function valFmt(unit) {
        switch (unit) {
            case 'usd': return usd;
            case 'eur': return eur;
            case 'pct': return function (v) { return pct(v, 1); };
            case 'hours': return hours;
            case 'kwh': return kwh;
            case 'min': return minutes;
            case 'int': return function (v) { return n0(Math.round(v)); };
            default: return num;
        }
    }
    function when(iso) { return iso ? String(iso).replace('T', ' ').slice(0, 16) : '—'; }
    function agoSeconds(s) {
        if (s == null) return '—';
        if (s < 90) return 'just now';
        if (s < 5400) return Math.round(s / 60) + ' min ago';
        if (s < 129600) return Math.round(s / 3600) + ' h ago';
        return Math.round(s / 86400) + ' d ago';
    }
    function keyTitle(key, bucket) {
        var d = new Date(key + 'T12:00:00');
        if (isNaN(d)) return key;
        var s = d.toLocaleDateString(undefined, { weekday: bucket === 'week' ? undefined : 'short', day: 'numeric', month: 'short', year: 'numeric' });
        return bucket === 'week' ? 'Week of ' + s : s;
    }
    function color(id, i) { return COLOR[id] || SLOT[i % SLOT.length]; }

    // ── payload helpers ──────────────────────────────────────────────────────
    function cardById(id) {
        var cs = (_data && _data.cards) || [];
        for (var i = 0; i < cs.length; i++) if (cs[i].id === id) return cs[i];
        return null;
    }
    function forecastOf(chart, id) {
        var fs = chart.forecast || [];
        for (var i = 0; i < fs.length; i++) if (fs[i].id === id || (id === 'trend' && fs[i].style !== 'scenario' && fs[i].id !== 'scenario')) return fs[i];
        return null;
    }
    function totals(chart) {
        return chart.keys.map(function (k, j) {
            var t = null;
            (chart.series || []).forEach(function (s) { if (s.values[j] != null) t = (t || 0) + s.values[j]; });
            return t;
        });
    }

    // ── board html ───────────────────────────────────────────────────────────
    function deltaHtml(d) {
        if (!d || d.pct == null) return '';
        var up = d.pct > 0, flat = Math.abs(d.pct) < 0.05;
        var good = flat ? null : (d.good_when === 'up' ? up : !up);
        var cls = flat ? 'an-delta-flat' : (good ? 'an-delta-good' : 'an-delta-bad');
        return '<span class="an-delta ' + cls + '"><i>' + (flat ? '→' : (up ? '▲' : '▼')) + '</i>' + esc((d.pct > 0 ? '+' : '') + d.pct + '%') +
            '</span><span class="an-delta-label">' + esc(d.label) + '</span>';
    }
    function cardHtml(c) {
        var h = c.headline || {};
        var legend = (c.chart.series || []).slice(0, 4).map(function (s, i) {
            return '<span><i style="background:' + color(s.id, i) + '"></i>' + esc(s.label) + '</span>';
        }).join('');
        return '<article class="an-card" data-an-card="' + esc(c.id) + '" tabindex="0" role="button" aria-label="' + esc(c.title + ' — open board') + '">' +
            '<div class="an-card-head"><div><div class="an-card-title">' + esc(c.title) + '</div><div class="an-card-q">' + esc(c.question) + '</div></div>' +
            (c.assumption ? '<span class="an-tag" title="rests on stated assumptions — edit them in the board">assumption</span>' : '') + '</div>' +
            '<div class="an-headline"><div class="an-headline-value">' + esc(fmt(h.value, h.fmt)) + '</div><div><div class="an-headline-label">' + esc(h.label) + '</div>' +
            (h.sub ? '<div class="an-headline-sub">' + esc(h.sub) + '</div>' : '') + '</div></div>' +
            '<div class="an-headline" style="margin-top:4px">' + deltaHtml(c.delta) + '</div>' +
            '<div class="an-preview" data-an-preview="' + esc(c.id) + '"></div>' +
            (legend ? '<div class="an-legend-mini">' + legend + '</div>' : '') +
            '<div class="an-card-foot"><span>' + esc((c.chart.bucket === 'week' ? 'weekly' : 'daily') + ' · ' + (c.chart.forecast && c.chart.forecast.length ? 'with forecast' : 'history')) + '</span><span class="an-open">open board ›</span></div>' +
            '</article>';
    }
    function html(d) {
        var lanes = d.lanes || [];
        var sc = d.scenario || {};
        var cfg = d.config || {};
        var out = '<div class="an-toolbar"><div class="an-toolbar-left">' +
            // The check time, the data version and the compute time now live in the
            // metrics header's one "Checked HH:MM:SS" badge (dashboard_tab_metrics.js),
            // which every subtab shares; the board no longer prints its own.
            '<span class="an-scenario">Approval Queue at full tilt: <b>' + esc(num(sc.per_day)) + '</b> items/day needing <b>' + esc(hours(sc.hours_per_day)) + '</b> = <b>' + esc(pct(sc.utilisation_pct, 0)) + '</b> of a ' + esc(num(cfg.active_hours_per_day)) + ' h day' +
            ((sc.missing_unit_times || []).length ? ' · no unit time yet for ' + esc(sc.missing_unit_times.join(', ')) : '') + '</span>' +
            '</div><div class="an-toolbar-left"><span>Assumptions: ' + esc(n0(cfg.views_per_content)) + ' views/content · $' + esc(cfg.rpm_usd) + ' RPM · €' + esc(cfg.kwh_price_eur) + '/kWh</span>' +
            '<button type="button" class="an-btn" data-an-open="income">Edit assumptions</button></div></div>';
        out += '<div class="an-board">';
        lanes.forEach(function (l) {
            var cards = (d.cards || []).filter(function (c) { return c.lane === l.id; });
            out += '<section class="an-lane"><div class="an-lane-head"><h4>' + esc(l.label) + '</h4><span>' + cards.length + ' card' + (cards.length === 1 ? '' : 's') + '</span></div>' +
                cards.map(cardHtml).join('') + '</section>';
        });
        out += '</div>';
        out += '<details class="mh-twin" style="margin-top:12px"><summary>Sources &amp; coverage</summary>' + sourcesHtml(d) + '</details>';
        return out;
    }
    function sourcesHtml(d) {
        var cov = d.coverage || {};
        return '<div class="mh-table-wrap"><table class="mh-table an-sources"><thead><tr><th>Source</th><th>Path</th><th class="num">Files</th><th>Last write</th><th>Age</th></tr></thead><tbody>' +
            (d.sources || []).map(function (s) {
                return '<tr><td>' + esc(s.source) + '</td><td>' + esc(s.path) + '</td><td class="num">' + esc(n0(s.files)) + '</td><td>' + esc(when(s.last_write)) + '</td><td>' + esc(agoSeconds(s.age_s)) + '</td></tr>';
            }).join('') + '</tbody></table></div>' +
            '<p class="mh-note">' + esc('Runs ' + n0(cov.runs) + ' (' + n0(cov.content_runs) + ' content, ' + n0(cov.completed_content) + ' completed) · excluded ' + n0(cov.excluded_test_runs) + ' test and ' + n0(cov.excluded_synthesized) + ' synthesized records · LLM rows ' + n0(cov.llm_rows) +
                ' · sampler days ' + n0(cov.sysusage_days) + ' · telemetry CSV days ' + n0(cov.telemetry_days) + '. Forecasts: OLS trend over the last ' + n0(d.trend_days) + ' days, ' + n0(d.horizon_days) + '-day horizon, 80 % band.') + '</p>';
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
        return 'M' + x + ',' + (y + h) + 'V' + (y + r) + 'Q' + x + ',' + y + ' ' + (x + r) + ',' + y + 'H' + (x + w - r) + 'Q' + (x + w) + ',' + y + ' ' + (x + w) + ',' + (y + r) + 'V' + (y + h) + 'Z';
    }

    /**
     * Draws chart (payload spec) into host. opts.preview draws the compact card graph.
     * x = history keys followed by forecast keys (one axis, forecast region shaded);
     * y = one unit (chart.y). Series: columns (stacked/grouped) or lines; lines[] overlay in
     * the same unit; ceiling; forecast[] = dashed lines (+ band) into the forecast region.
     */
    function drawChart(host, chart, opts) {
        opts = opts || {};
        host.textContent = '';
        var preview = !!opts.preview;
        var W = Math.max(preview ? 120 : 320, host.clientWidth);
        var H = host.clientHeight || (preview ? 78 : 340);
        var padL = preview ? 2 : 58, padR = preview ? 2 : 12, padT = preview ? 4 : 12, padB = preview ? 2 : 30;
        var keys = chart.keys || [];
        var fcs = (chart.forecast || []).filter(function (f) { return f.keys && f.keys.length; });
        var fkeys = [];
        fcs.forEach(function (f) { f.keys.forEach(function (k) { if (fkeys.indexOf(k) < 0) fkeys.push(k); }); });
        fkeys.sort();
        var allKeys = keys.concat(fkeys.filter(function (k) { return keys.indexOf(k) < 0; }));
        var n = allKeys.length;
        var pw = W - padL - padR, ph = H - padT - padB;
        if (!n || pw <= 0 || ph <= 0) return;
        var xIdx = {};
        allKeys.forEach(function (k, i) { xIdx[k] = i; });
        var band = pw / n;
        var xc = function (i) { return padL + i * band + band / 2; };
        var series = chart.series || [];
        var lines = chart.lines || [];
        var isCols = chart.kind === 'columns';
        var stacked = isCols && chart.stacked !== false && series.length > 1;

        // y extent
        var maxV = 0;
        var tot = totals(chart);
        if (isCols) {
            if (stacked) tot.forEach(function (t) { if (t != null) maxV = Math.max(maxV, t); });
            else series.forEach(function (s) { s.values.forEach(function (v) { if (v != null) maxV = Math.max(maxV, v); }); });
        } else {
            series.forEach(function (s) { s.values.forEach(function (v) { if (v != null) maxV = Math.max(maxV, v); }); });
        }
        lines.forEach(function (s) { s.values.forEach(function (v) { if (v != null) maxV = Math.max(maxV, v); }); });
        fcs.forEach(function (f) { (f.hi || f.values).forEach(function (v) { if (v != null) maxV = Math.max(maxV, v); }); });
        if (chart.ceiling && chart.ceiling.value != null && !preview) maxV = Math.max(maxV, chart.ceiling.value);
        if (chart.y === 'pct') maxV = Math.max(maxV, 100);
        var max = niceMax(maxV);
        var yc = function (v) { return padT + ph - (v / max) * ph; };
        var svg = svgEl('svg', { width: W, height: H, viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': chart.title || 'chart' }, host);

        // forecast region
        if (fkeys.length) {
            var fx0 = padL + (keys.length) * band;
            svgEl('rect', { x: fx0, y: padT, width: pw - keys.length * band, height: ph, fill: 'rgba(11,11,11,0.035)' }, svg);
            if (!preview) {
                var ft = svgEl('text', { x: fx0 + 6, y: padT + 12, 'class': 'an-axis' }, svg);
                ft.textContent = 'forecast · next ' + fkeys.length + (chart.bucket === 'week' ? ' weeks' : ' days');
            }
        }
        // grid + y axis
        var gridF = preview ? [0, 1] : [0, 0.25, 0.5, 0.75, 1];
        var af = axisFmt(chart.y);
        gridF.forEach(function (f) {
            var y = Math.round(yc(max * f)) + 0.5;
            svgEl('line', { x1: padL, x2: W - padR, y1: y, y2: y, stroke: f === 0 ? '#c3c2b7' : '#e6e5df', 'stroke-width': 1 }, svg);
            if (!preview) {
                var t = svgEl('text', { x: padL - 8, y: y + 4, 'text-anchor': 'end', 'class': 'an-axis' }, svg);
                t.textContent = af(max * f);
            }
        });
        // ceiling
        if (chart.ceiling && chart.ceiling.value != null && !preview) {
            var cy = Math.round(yc(Math.min(max, chart.ceiling.value))) + 0.5;
            svgEl('line', { x1: padL, x2: W - padR, y1: cy, y2: cy, stroke: '#d03b3b', 'stroke-width': 1, 'stroke-dasharray': '2 4' }, svg);
            var ct = svgEl('text', { x: W - padR, y: cy - 4, 'text-anchor': 'end', 'class': 'an-axis' }, svg);
            ct.textContent = chart.ceiling.label + ' ' + valFmt(chart.y)(chart.ceiling.value);
        }
        // columns
        var bw = Math.max(1, Math.min(preview ? 8 : 26, band * 0.72));
        if (isCols) {
            var vis = series.filter(function (s) { return s.values.some(function (v) { return v; }); });
            keys.forEach(function (k, j) {
                var i = xIdx[k];
                if (stacked) {
                    var base = padT + ph, x = xc(i) - bw / 2;
                    var seg = vis.filter(function (s) { return (s.values[j] || 0) > 0; });
                    seg.forEach(function (s, si) {
                        var h = (s.values[j] / max) * ph, top = base - h;
                        var col = color(s.id, series.indexOf(s));
                        if (si === seg.length - 1) svgEl('path', { d: topRounded(x, top, bw, Math.max(h, 1.5), 4), fill: col }, svg);
                        else { var gap = h > 4 ? 2 : 0; svgEl('rect', { x: x, y: top + gap, width: bw, height: Math.max(h - gap, 1), fill: col }, svg); }
                        base = top;
                    });
                } else {
                    var gw = Math.max(1, (bw - 2 * (vis.length - 1)) / Math.max(1, vis.length));
                    vis.forEach(function (s, si) {
                        var v = s.values[j];
                        if (v == null || v <= 0) return;
                        var h = (v / max) * ph;
                        svgEl('path', { d: topRounded(xc(i) - bw / 2 + si * (gw + 2), padT + ph - h, gw, Math.max(h, 1.5), 3), fill: color(s.id, series.indexOf(s)) }, svg);
                    });
                }
            });
        }
        // line helper
        function linePath(vals, keyList, dashed, col, width, cls) {
            var d = '', pen = false;
            keyList.forEach(function (k, j) {
                var v = vals[j];
                if (v == null) { pen = false; return; }
                var i = xIdx[k];
                if (i == null) return;
                d += (pen ? 'L' : 'M') + xc(i).toFixed(1) + ',' + yc(v).toFixed(1);
                pen = true;
            });
            if (!d) return null;
            var attrs = { d: d, fill: 'none', stroke: col, 'stroke-width': width || 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' };
            if (dashed) attrs['stroke-dasharray'] = dashed;
            if (cls) attrs['class'] = cls;
            return svgEl('path', attrs, svg);
        }
        function markers(vals, keyList, col) {
            if (preview) return;
            keyList.forEach(function (k, j) {
                var v = vals[j];
                if (v == null) return;
                var i = xIdx[k];
                var lonely = (j === 0 || vals[j - 1] == null) && (j === keyList.length - 1 || vals[j + 1] == null);
                if (lonely || n <= 45) svgEl('circle', { cx: xc(i), cy: yc(v), r: lonely ? 4 : 3, fill: col, stroke: '#fff', 'stroke-width': 2 }, svg);
            });
        }
        if (!isCols) {
            series.forEach(function (s, si) {
                var col = color(s.id, si);
                if (series.length === 1 && chart.kind !== 'line-only') {
                    // single series: soft area under the line
                    var area = '', pen = false, lastX = null;
                    keys.forEach(function (k, j) {
                        var v = s.values[j];
                        if (v == null) { if (pen && lastX != null) area += 'L' + lastX + ',' + yc(0).toFixed(1) + 'Z'; pen = false; return; }
                        var x = xc(xIdx[k]).toFixed(1);
                        area += (pen ? 'L' : 'M' + x + ',' + yc(0).toFixed(1) + 'L') + x + ',' + yc(v).toFixed(1);
                        lastX = x; pen = true;
                    });
                    if (pen && lastX != null) area += 'L' + lastX + ',' + yc(0).toFixed(1) + 'Z';
                    if (area) svgEl('path', { d: area, fill: col, 'fill-opacity': 0.12 }, svg);
                }
                linePath(s.values, keys, null, col, preview ? 1.5 : 2);
                markers(s.values, keys, col);
            });
        } else if (preview && stacked) {
            // preview of a stacked chart: a total line on top for legibility
            linePath(tot, keys, null, '#52514e', 1);
        }
        lines.forEach(function (s, si) {
            linePath(s.values, keys, s.style === 'thin' ? '1 3' : null, color(s.id, si + series.length), s.style === 'thin' ? 1.5 : 2);
            if (s.style !== 'thin') markers(s.values, keys, color(s.id, si + series.length));
        });
        // forecasts: connect from the last history point
        fcs.forEach(function (f) {
            var scen = f.style === 'scenario' || f.id === 'scenario';
            var col = scen ? SCENARIO : (f.id in COLOR ? COLOR[f.id] : TREND);
            var fk = f.keys, fv = f.values;
            if (!scen && f.lo && f.hi) {
                var up = '', down = '';
                fk.forEach(function (k, j) {
                    var i = xIdx[k];
                    if (i == null || f.hi[j] == null) return;
                    up += (up ? 'L' : 'M') + xc(i).toFixed(1) + ',' + yc(Math.min(max, f.hi[j])).toFixed(1);
                    down = 'L' + xc(i).toFixed(1) + ',' + yc(Math.max(0, f.lo[j])).toFixed(1) + down;
                });
                if (up) svgEl('path', { d: up + down + 'Z', fill: col, 'fill-opacity': 0.10 }, svg);
            }
            var startVals = [], startKeys = [];
            if (!scen || true) {
                // bridge from the last known history value of the matching entity (or total)
                var hist = null;
                if (f.id in COLOR) { series.forEach(function (s) { if (s.id === f.id) hist = s.values; }); }
                if (!hist) hist = (isCols ? tot : (series[0] ? series[0].values : null));
                if (hist) {
                    for (var j = keys.length - 1; j >= 0; j--) if (hist[j] != null) { startKeys = [keys[j]]; startVals = [hist[j]]; break; }
                }
            }
            linePath(startVals.concat(fv), startKeys.concat(fk), scen ? '6 3 1.5 3' : '5 4', col, preview ? 1.5 : 2);
        });
        // x labels
        if (!preview) {
            var every = Math.max(1, Math.ceil(64 / band));
            allKeys.forEach(function (k, i) {
                if (i % every) return;
                var t = svgEl('text', { x: xc(i), y: H - 10, 'text-anchor': 'middle', 'class': 'an-axis' }, svg);
                t.textContent = k.slice(5);
            });
            // crosshair + hit areas
            var cross = svgEl('g', { 'class': 'an-crosshair' }, svg);
            var vline = svgEl('line', { x1: 0, x2: 0, y1: padT, y2: padT + ph, stroke: 'rgba(11,11,11,0.35)', 'stroke-width': 1, 'stroke-dasharray': '3 3', visibility: 'hidden' }, cross);
            var dots = [];
            allKeys.forEach(function (k, i) {
                var hit = svgEl('rect', { x: padL + i * band, y: padT, width: band, height: ph, fill: 'transparent' }, svg);
                hit.style.cursor = 'crosshair';
                hit.addEventListener('pointerenter', function (ev) { showAt(i, ev); });
                hit.addEventListener('pointermove', function (ev) { moveTip(ev); });
                hit.addEventListener('pointerleave', function () { hideTip(); vline.setAttribute('visibility', 'hidden'); dots.forEach(function (d) { d.remove(); }); dots = []; });
            });
            var vf = valFmt(chart.y);
            function showAt(i, ev) {
                var k = allKeys[i];
                var isF = i >= keys.length;
                var j = isF ? -1 : i;
                var rows = [];
                dots.forEach(function (d) { d.remove(); }); dots = [];
                function dot(v, col) { if (v == null) return; dots.push(svgEl('circle', { cx: xc(i), cy: yc(Math.min(max, v)), r: 4.5, fill: col, stroke: '#fff', 'stroke-width': 2 }, cross)); }
                if (!isF) {
                    series.forEach(function (s, si) { var v = s.values[j]; if (v != null && !(isCols && series.length > 2 && !v)) { rows.push({ color: color(s.id, si), value: vf(v), label: s.label }); if (!isCols) dot(v, color(s.id, si)); } });
                    if (isCols && series.length > 1 && tot[j] != null) rows.push({ color: null, value: vf(tot[j]), label: 'Total' });
                    lines.forEach(function (s, si) { var v = s.values[j]; if (v != null) { rows.push({ color: color(s.id, si + series.length), value: vf(v), label: s.label }); dot(v, color(s.id, si + series.length)); } });
                    (chart.extra_series || []).forEach(function (s) { var v = s.values[j]; if (v != null) rows.push({ color: OTHER, value: vf(v), label: s.label }); });
                }
                fcs.forEach(function (f) {
                    var fj = f.keys.indexOf(k);
                    if (fj < 0) return;
                    var scen = f.style === 'scenario' || f.id === 'scenario';
                    var col = scen ? SCENARIO : (f.id in COLOR ? COLOR[f.id] : TREND);
                    var v = f.values[fj];
                    if (v == null) return;
                    rows.push({ color: col, value: vf(v) + (f.lo && f.hi ? '  (' + vf(f.lo[fj]) + ' – ' + vf(f.hi[fj]) + ')' : ''), label: f.label + (scen || /trend/i.test(f.label) ? '' : ' · trend') });
                    dot(v, col);
                });
                if (chart.ceiling && chart.ceiling.value != null) rows.push({ color: '#d03b3b', value: vf(chart.ceiling.value), label: chart.ceiling.label });
                vline.setAttribute('x1', xc(i)); vline.setAttribute('x2', xc(i)); vline.setAttribute('visibility', 'visible');
                showTip({ title: keyTitle(k, chart.bucket) + (isF ? ' · forecast' : ''), rows: rows }, ev.clientX, ev.clientY);
            }
        }
    }

    // ── tooltip ──────────────────────────────────────────────────────────────
    function tipEl() {
        var t = document.getElementById('an-tooltip');
        if (!t) {
            t = document.createElement('div');
            t.id = 'an-tooltip';
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
        t.style.zIndex = 10060;
        moveTip({ clientX: x, clientY: y });
    }
    function moveTip(ev) {
        var t = tipEl();
        if (t.hidden) return;
        var vw = window.innerWidth, vh = window.innerHeight;
        var w = t.offsetWidth, ht = t.offsetHeight;
        var left = ev.clientX + 16, top = ev.clientY + 16;
        if (left + w > vw - 8) left = ev.clientX - w - 16;
        if (top + ht > vh - 8) top = ev.clientY - ht - 16;
        t.style.left = Math.max(4, left) + 'px';
        t.style.top = Math.max(4, top) + 'px';
    }
    function hideTip() { var t = document.getElementById('an-tooltip'); if (t) t.hidden = true; }

    // ── previews ─────────────────────────────────────────────────────────────
    function drawPreviews(panel) {
        _hosts = _hosts.filter(function (h) { return !h.preview; });
        panel.querySelectorAll('[data-an-preview]').forEach(function (host) {
            var c = cardById(host.getAttribute('data-an-preview'));
            if (!c) return;
            var spec = c.chart;
            if (spec.kind !== 'columns' && spec.series.length > 3) spec = Object.assign({}, spec, { series: spec.series.slice(0, 3) });
            drawChart(host, spec, { preview: true });
            _hosts.push({ host: host, chart: spec, opts: { preview: true }, preview: true });
        });
    }

    // ── the open board ───────────────────────────────────────────────────────
    function factHtml(f) {
        return '<div class="an-fact"><div class="an-fact-label">' + esc(f.label) + '</div><div class="an-fact-value">' + esc(fmt(f.value, f.fmt)) + '</div>' +
            (f.sub ? '<div class="an-fact-sub">' + esc(f.sub) + '</div>' : '') + '</div>';
    }
    function laneHtml(id, label, facts) {
        return '<section class="an-kanban-lane"><h5><i style="background:' + LANE_DOT[id] + '"></i>' + esc(label) + ' <span style="font-weight:400;text-transform:none;letter-spacing:0">' + (facts || []).length + '</span></h5>' +
            ((facts || []).length ? facts.map(factHtml).join('') : '<p class="an-empty-lane">Nothing measurable yet.</p>') + '</section>';
    }
    function legendHtml(chart) {
        var items = (chart.series || []).map(function (s, i) { return '<span><i class="' + (chart.kind === 'columns' ? 'an-sw-col' : '') + '" style="background:' + color(s.id, i) + '"></i>' + esc(s.label) + '</span>'; });
        (chart.lines || []).forEach(function (s, i) { items.push('<span><i style="background:' + color(s.id, i + (chart.series || []).length) + '"></i>' + esc(s.label) + '</span>'); });
        (chart.extra_series || []).forEach(function (s) { items.push('<span><i class="an-sw-col" style="background:' + OTHER + '"></i>' + esc(s.label) + ' (table)</span>'); });
        (chart.forecast || []).forEach(function (f) {
            var scen = f.style === 'scenario' || f.id === 'scenario';
            var col = scen ? SCENARIO : (f.id in COLOR ? COLOR[f.id] : TREND);
            items.push('<span><i class="an-sw-dash" style="color:' + col + '"></i>' + esc(f.label + (scen ? ' (scenario)' : ' (trend' + (f.r2 != null ? ', r² ' + f.r2 : '') + ')')) + '</span>');
        });
        if (chart.ceiling) items.push('<span><i class="an-sw-dash" style="color:#d03b3b"></i>' + esc(chart.ceiling.label) + '</span>');
        return items.length > 1 ? '<div class="an-legend">' + items.join('') + '</div>' : '';
    }
    function tableHtml(chart) {
        var keys = chart.keys || [];
        var cols = [chart.bucket === 'week' ? 'Week of' : 'Day'];
        var allS = (chart.series || []).concat(chart.lines || [], chart.extra_series || []);
        allS.forEach(function (s) { cols.push(s.label); });
        var vf = valFmt(chart.y);
        var rows = [];
        for (var j = keys.length - 1; j >= 0; j--) {
            var vals = allS.map(function (s) { return s.values[j]; });
            if (!vals.some(function (v) { return v; })) continue;
            rows.push('<tr><td>' + esc(keys[j]) + '</td>' + vals.map(function (v) { return '<td class="num">' + esc(v == null ? '—' : vf(v)) + '</td>'; }).join('') + '</tr>');
        }
        (chart.forecast || []).forEach(function (f) {
            var scen = f.style === 'scenario' || f.id === 'scenario';
            rows.push('<tr><td colspan="' + cols.length + '"><strong>' + esc(f.label) + (scen ? '' : ' — ' + (f.method || 'trend') + (f.slope_per_day != null ? ' · slope ' + f.slope_per_day + '/day' : '') + (f.r2 != null ? ' · r² ' + f.r2 : '')) + '</strong></td></tr>');
            f.keys.forEach(function (k, i) {
                rows.push('<tr><td>' + esc(k) + '</td><td class="num" colspan="' + (cols.length - 1) + '">' + esc(vf(f.values[i])) + (f.lo ? ' (' + esc(vf(f.lo[i])) + ' – ' + esc(vf(f.hi[i])) + ')' : '') + '</td></tr>');
            });
        });
        return '<div class="mh-table-wrap"><table class="mh-table"><thead><tr>' + cols.map(function (c, i) { return '<th' + (i ? ' class="num"' : '') + '>' + esc(c) + '</th>'; }).join('') + '</tr></thead><tbody>' + rows.join('') + '</tbody></table></div>';
    }
    function factTableHtml(t) {
        if (!t || !t.rows || !t.rows.length) return '';
        return '<div class="mh-table-wrap"><table class="mh-table"><thead><tr>' + t.cols.map(function (c, i) { return '<th' + (i ? ' class="num"' : '') + '>' + esc(c) + '</th>'; }).join('') + '</tr></thead><tbody>' +
            t.rows.map(function (r) {
                return '<tr>' + r.map(function (cell, i) {
                    var v = (cell && typeof cell === 'object') ? fmt(cell.v, cell.fmt) : (typeof cell === 'number' ? num(cell) : cell);
                    return '<td' + (i ? ' class="num"' : '') + '>' + esc(v == null ? '—' : v) + '</td>';
                }).join('') + '</tr>';
            }).join('') + '</tbody></table></div>';
    }
    function assumptionsHtml(cfg) {
        return '<div class="an-assump">' +
            '<label>Views per content (floor)<input type="number" min="0" step="100" data-an-cfg="views_per_content" value="' + esc(cfg.views_per_content) + '"></label>' +
            '<label>RPM — $ per 1 000 views<input type="number" min="0" step="0.1" data-an-cfg="rpm_usd" value="' + esc(cfg.rpm_usd) + '"></label>' +
            '<label>€ per kWh<input type="number" min="0" step="0.01" data-an-cfg="kwh_price_eur" value="' + esc(cfg.kwh_price_eur) + '"></label>' +
            '<label>Active hours per day<input type="number" min="1" max="24" step="1" data-an-cfg="active_hours_per_day" value="' + esc(cfg.active_hours_per_day) + '"></label>' +
            '<div><button type="button" class="an-btn an-btn-primary" id="an-cfg-save">Save &amp; recompute</button></div>' +
            '<div class="an-assump-msg" id="an-cfg-msg">EUR/USD ' + esc(cfg.eur_per_usd) + ' comes from quota_config.json. Stored in data/runtime/analytics_config.json.</div></div>';
    }
    function boardHtml(c) {
        var ch = c.chart;
        var sec = ch.secondary ? '<div class="an-chart-card"><h4>' + esc(ch.secondary.label) + '</h4><div class="an-chart an-chart-small" data-an-chart="secondary"></div></div>' : '';
        var line = ch.line ? '<div class="an-chart-card"><h4>' + esc(ch.line.label) + '</h4><div class="an-chart an-chart-small" data-an-chart="line"></div></div>' : '';
        return '<div class="an-sheet" role="dialog" aria-modal="true" aria-label="' + esc(c.title) + '">' +
            '<div class="an-sheet-head"><div><h3>' + esc(c.title) + '</h3><p>' + esc(c.question) + '</p></div>' +
            '<div class="an-sheet-actions"><span class="an-live" id="an-live-board"><i></i>live</span><button type="button" class="an-btn" data-an-close>Close ✕</button></div></div>' +
            '<div class="an-kanban">' + laneHtml('historical', 'Historical', c.facts.historical) + laneHtml('current', 'Now', c.facts.current) + laneHtml('future', 'Future', c.facts.future) + '</div>' +
            '<div class="an-chart-card"><h4>' + esc(ch.title) + '</h4>' + legendHtml(ch) + '<div class="an-chart" data-an-chart="main"></div>' +
            '<details class="mh-twin"><summary>Table view</summary>' + tableHtml(ch) + '</details></div>' +
            (sec || line ? '<div class="an-grid-2">' + sec + line + '</div>' : '') +
            (c.table ? '<div class="an-chart-card"><h4>Breakdown</h4>' + factTableHtml(c.table) + '</div>' : '') +
            (c.id === 'income' ? '<div class="an-chart-card"><h4>Real views (YouTube Data API, channels with a saved account)</h4><div id="an-real-views" class="mh-note">Loading…</div></div>' : '') +
            '<div class="an-chart-card"><h4>Assumptions</h4>' + assumptionsHtml(_data.config || {}) + '</div>' +
            '<div class="an-chart-card"><h4>How this is measured</h4><ul class="mh-notes">' + (c.notes || []).map(function (t) { return '<li>' + esc(t) + '</li>'; }).join('') + '</ul>' +
            '<details class="mh-twin"><summary>Sources &amp; coverage</summary>' + sourcesHtml(_data) + '</details></div>' +
            '</div>';
    }
    function drawBoardCharts(overlay, c) {
        _hosts = _hosts.filter(function (h) { return h.preview; });
        var main = overlay.querySelector('[data-an-chart="main"]');
        if (main) { drawChart(main, c.chart); _hosts.push({ host: main, chart: c.chart, opts: {} }); }
        var sec = overlay.querySelector('[data-an-chart="secondary"]');
        if (sec && c.chart.secondary) {
            var spec = { kind: c.chart.secondary.kind || 'columns', bucket: c.chart.bucket, keys: c.chart.keys, y: c.chart.secondary.y, series: [{ id: 'secondary', label: c.chart.secondary.label, values: c.chart.secondary.values }] };
            drawChart(sec, spec); _hosts.push({ host: sec, chart: spec, opts: {} });
        }
        var ln = overlay.querySelector('[data-an-chart="line"]');
        if (ln && c.chart.line) {
            var spec2 = { kind: 'line', bucket: c.chart.bucket, keys: c.chart.keys, y: c.chart.y, series: [{ id: 'cumulative', label: c.chart.line.label, values: c.chart.line.values }] };
            drawChart(ln, spec2); _hosts.push({ host: ln, chart: spec2, opts: {} });
        }
    }
    function openBoard(id) {
        var c = cardById(id);
        if (!c) return;
        close();
        _open = id;
        var ov = document.createElement('div');
        ov.className = 'an-overlay';
        ov.id = 'an-overlay';
        ov.innerHTML = boardHtml(c);
        document.body.appendChild(ov);
        document.body.style.overflow = 'hidden';
        ov.addEventListener('click', function (e) {
            if (e.target === ov || e.target.closest('[data-an-close]')) { close(); return; }
            if (e.target.id === 'an-cfg-save') saveConfig(ov);
        });
        ov.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
        drawBoardCharts(ov, c);
        if (id === 'income') loadRealViews(ov);
        var btn = ov.querySelector('[data-an-close]');
        if (btn) btn.focus();
    }
    function rerenderBoard() {
        var ov = document.getElementById('an-overlay');
        var c = _open && cardById(_open);
        if (!ov || !c) return;
        var scroll = ov.scrollTop;
        var openTwins = Array.prototype.map.call(ov.querySelectorAll('details[open]'), function (d) { return d.querySelector('summary') && d.querySelector('summary').textContent; });
        ov.innerHTML = boardHtml(c);
        drawBoardCharts(ov, c);
        ov.querySelectorAll('details').forEach(function (d) { var s = d.querySelector('summary'); if (s && openTwins.indexOf(s.textContent) >= 0) d.open = true; });
        ov.scrollTop = scroll;
        if (_open === 'income') loadRealViews(ov);
        flash(ov.querySelector('#an-live-board'));
    }
    function close() {
        var ov = document.getElementById('an-overlay');
        if (ov) ov.remove();
        document.body.style.overflow = '';
        hideTip();
        _open = null;
        _hosts = _hosts.filter(function (h) { return h.preview; });
    }

    // ── assumptions ──────────────────────────────────────────────────────────
    function saveConfig(ov) {
        var body = {};
        ov.querySelectorAll('[data-an-cfg]').forEach(function (inp) { var v = parseFloat(inp.value); if (!isNaN(v)) body[inp.getAttribute('data-an-cfg')] = v; });
        var msg = ov.querySelector('#an-cfg-msg');
        if (msg) msg.textContent = 'Saving…';
        function done(ok, text) {
            if (msg) msg.textContent = ok ? 'Saved — recomputing.' : ('Could not save: ' + text);
            if (ok && window.DashboardTabMetrics && window.DashboardTabMetrics.refresh) window.DashboardTabMetrics.refresh();
        }
        fetch('/api/metrics/analytics/config', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
            .then(function (r) { if (r.ok) return r.json().then(function () { done(true); }); throw new Error('HTTP ' + r.status); })
            .catch(function () {
                // Route not registered until the GUI restarts: the hot path accepts ?set= on the section itself.
                fetch('/api/metrics/hub/analytics?days=30&fresh=1&set=' + encodeURIComponent(JSON.stringify(body)), { credentials: 'same-origin', cache: 'no-store' })
                    .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); done(true); })
                    .catch(function (e) { done(false, e.message); });
            });
    }

    // ── real views (income board) ────────────────────────────────────────────
    function loadRealViews(ov) {
        var host = ov.querySelector('#an-real-views');
        if (!host) return;
        fetch('/api/youtube/channel-videos', { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!host.isConnected) return;
                var vids = d.videos || d.items || [];
                if (!vids.length) { host.textContent = d.error || 'No channel with a saved YouTube account returned videos.'; return; }
                var views = vids.map(function (v) { return Number(v.views != null ? v.views : (v.viewCount || (v.statistics && v.statistics.viewCount) || 0)); });
                var total = views.reduce(function (a, b) { return a + b; }, 0);
                var avg = total / vids.length;
                var cfg = _data.config || {};
                host.innerHTML = '<div class="an-kanban" style="margin:0">' +
                    factHtml({ label: 'Videos with real stats', value: vids.length, fmt: 'int', sub: d.channelTitle || d.channel || '' }) +
                    factHtml({ label: 'Average views per video', value: Math.round(avg), fmt: 'int', sub: 'vs the ' + n0(cfg.views_per_content) + ' assumed per content' }) +
                    factHtml({ label: 'Total views', value: total, fmt: 'int', sub: 'at $' + cfg.rpm_usd + ' RPM ≈ ' + usd(total / 1000 * cfg.rpm_usd) + ' gross' }) + '</div>' +
                    '<p class="mh-note">' + esc('Only the channel matching the saved token is measured (Data API, no Analytics scope). These are real counts; the card above is the assumed floor.') + '</p>';
            })
            .catch(function (e) { if (host.isConnected) host.textContent = 'Real views unavailable: ' + e.message; });
    }

    // ── live badge ───────────────────────────────────────────────────────────
    function flash(el) {
        if (!el) return;
        el.classList.add('an-live-flash');
        setTimeout(function () { el.classList.remove('an-live-flash'); }, 1800);
    }
    // Kept as a no-op hook: the shared header badge is written by paint() in
    // dashboard_tab_metrics.js for every tab, this one included.
    function liveText(d, changed) { }

    // ── public API (called by dashboard_tab_metrics.js) ──────────────────────
    function same(panel, data) { return !!(_data && data && _data.data_version === data.data_version); }
    function touch(panel, data) { _lastCheck = Date.now(); if (data) { _data.generated_at = data.generated_at; _data.compute_ms = data.compute_ms; } liveText(_data, false); }
    function mount(panel, data) {
        var changed = !!(_data && data && _data.data_version !== data.data_version);
        _data = data;
        _panel = panel;
        drawPreviews(panel);
        liveText(data, changed);
        if (!panel.__anBound) {
            panel.__anBound = true;
            panel.addEventListener('click', function (e) {
                var b = e.target.closest('[data-an-open]');
                if (b) { openBoard(b.getAttribute('data-an-open')); return; }
                var card = e.target.closest('[data-an-card]');
                if (card) openBoard(card.getAttribute('data-an-card'));
            });
            panel.addEventListener('keydown', function (e) {
                var card = e.target.closest('[data-an-card]');
                if (card && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); openBoard(card.getAttribute('data-an-card')); }
            });
        }
        if (_open) rerenderBoard();
    }
    function redraw() {
        _hosts.forEach(function (h) { if (h.host.isConnected) drawChart(h.host, h.chart, h.opts); });
    }

    window.DashboardAnalytics = { html: html, mount: mount, same: same, touch: touch, redraw: redraw, close: close, open: openBoard };
})();
