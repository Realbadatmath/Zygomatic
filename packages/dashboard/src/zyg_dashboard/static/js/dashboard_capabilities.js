// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* dashboard_capabilities.js v1 — Metrics > Capabilities (2026-09-27).
 *
 * Left rail = the workflow, step by step. Click a step and its DATA SHEETS open in the
 * board on the right: rows are the models/tools in that step, columns are what a test
 * asked of them. Right-click a step (or a row) for Inspect, which opens the evidence
 * behind the sheet — the inputs, the pictures and every model's raw answer — in its own
 * page, so the board itself stays data sheets and nothing else.
 *
 * Every number, label, unit and state comes from capabilities_hub.py. This file only
 * draws, so the sheet, the tooltip and the Inspect page cannot disagree with each other.
 *
 * Payload contract (see capabilities_hub.section_capabilities):
 *   groups[] rail[] sheets{step -> {matrices[], coverage, notes, limitations, sources}}
 *   states{} grades{} statuses{}      ← the vocabulary, served, never hardcoded here
 * Side calls on the same endpoint:
 *   ?inspect=<step>   the evidence document
 *   ?asset=<id>       one registered picture as a data URI (lazy, on scroll)
 */
(function () {
    'use strict';

    var ENDPOINT = '/api/metrics/hub/capabilities';
    var _data = null, _panel = null, _sel = null, _q = '';
    var _inspect = null;                  // step id of the open Inspect page
    var _vert = true;                     // column headers on their side (see cap-vert)
    var _inspectRow = null;               // row id the open Inspect page is scoped to
    var _searchOpen = false;              // the filter box is behind a search icon
    var _insCache = {}, _assetCache = {}, _assetInflight = {};
    // A step now asks hundreds of questions, so the full set of sheets is ~1 MB. The poll
    // carries the rail; a sheet is fetched the first time its step is opened and kept
    // against the payload's data_version.
    var _sheetCache = {}, _sheetInflight = {};
    var _io = null;                       // IntersectionObserver for lazy pictures

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }
    function attr(s) { return esc(s); }
    function dict(base, over) {
        var out = {}, k;
        for (k in base) if (Object.prototype.hasOwnProperty.call(base, k)) out[k] = base[k];
        for (k in over) if (Object.prototype.hasOwnProperty.call(over, k)) out[k] = over[k];
        return out;
    }
    function n0(v) { return v == null ? '—' : Number(v).toLocaleString(); }
    function when(iso) { return iso ? String(iso).replace('T', ' ').slice(0, 16) : '—'; }

    // ── value formatting ─────────────────────────────────────────────────────
    // Units come from the payload's column definition, never guessed from the number.
    function fmt(v, unit) {
        if (v == null || v === '') return '';
        var n = Number(v);
        if (isNaN(n)) return String(v);
        switch (unit) {
            case 'pct': return round(n, 1) + ' %';
            case 'ratio': return n.toFixed(2);
            case 'x': return round(n, 2) + '×';
            case 'ms': return round(n, 0) + ' ms';
            case 's': return round(n, n < 10 ? 1 : 0) + ' s';
            case 'min': return round(n, 1) + ' min';
            case 'h': return round(n, 1) + ' h';
            case 'mb': return round(n, 1) + ' MB';
            case 'gb': return round(n, 1) + ' GB';
            case 'usd': return '$' + round(n, 2);
            case 'eur': return '€' + round(n, 2);
            case 'fps': return round(n, 0) + ' fps';
            case 'cents': return round(n, 1) + ' cents';
            case 'int': case 'count': return n0(Math.round(n));
            case 'tokens': return n >= 1e6 ? round(n / 1e6, 1) + ' M' : n0(Math.round(n));
            case 'text': return '';
            default: return round(n, 2) + (unit && unit !== 'number' ? ' ' + unit : '');
        }
    }
    function round(n, d) {
        var f = Math.pow(10, d);
        return String(Math.round(n * f) / f);
    }

    // ── vocabulary lookups (served, not hardcoded) ───────────────────────────
    function stateMeta(id) { return (_data && _data.states && _data.states[id]) || { label: id, tone: 'neutral', icon: '·' }; }
    function gradeMeta(id) { return (_data && _data.grades && _data.grades[id]) || null; }
    function statusMeta(id) { return (_data && _data.statuses && _data.statuses[id]) || { label: id, tone: 'neutral' }; }
    function ratingMeta(id) { return (_data && _data.ratings && _data.ratings[id]) || { label: id, tone: 'neutral', hint: '' }; }
    function sheetOf(step) { return _sheetCache[sheetKey(step)] || null; }
    function sheetKey(step) { return ((_data && _data.data_version) || '?') + '|' + step; }

    function ensureSheet(step, then) {
        var key = sheetKey(step);
        if (_sheetCache[key]) { if (then) then(); return; }
        if (_sheetInflight[key]) return;
        _sheetInflight[key] = true;
        fetch(ENDPOINT + '?sheet=' + encodeURIComponent(step), { credentials: 'same-origin', cache: 'no-store' })
            .then(function (r) { return r.json(); })
            .then(function (j) {
                delete _sheetInflight[key];
                _sheetCache[key] = j && j.sheet ? j.sheet : { missing: true };
                if (_sel === step) { if (then) then(); else paintBoard(); }
            })
            .catch(function (err) {
                delete _sheetInflight[key];
                _sheetCache[key] = { error: String(err && err.message || err) };
                if (_sel === step) paintBoard();
            });
    }

    function paintBoard() {
        var board = document.getElementById('cap-board');
        if (board) board.innerHTML = boardHtml();
    }
    function railOf(step) {
        var r = (_data && _data.rail) || [];
        for (var i = 0; i < r.length; i++) if (r[i].id === step) return r[i];
        return null;
    }

    // ═══════════════════════════════════════════════════════ the left rail ══
    function railHtml() {
        var byGroup = {};
        (_data.rail || []).forEach(function (e) { (byGroup[e.group] = byGroup[e.group] || []).push(e); });
        var q = _q.trim().toLowerCase();
        var out = (_data.groups || []).map(function (g) {
            var items = (byGroup[g.id] || []).filter(function (e) {
                return !q || (e.label + ' ' + e.hint + ' ' + e.id).toLowerCase().indexOf(q) >= 0;
            });
            if (!items.length) return '';
            return '<div class="cap-railgroup"><h4>' + esc(g.label) + '</h4>' +
                items.map(railItemHtml).join('') + '</div>';
        }).join('');
        return out || '<p class="cap-railempty">No step matches “' + esc(_q) + '”.</p>';
    }

    function railItemHtml(e) {
        var st = statusMeta(e.status);
        var pct = e.coverage && e.coverage.cells ? e.coverage.pct : 0;
        return '<button type="button" class="cap-rail-item' + (e.id === _sel ? ' active' : '') +
            '" data-cap-step="' + attr(e.id) + '" role="tab" aria-selected="' + (e.id === _sel) + '"' +
            ' title="' + attr(e.hint + ' — right-click for Inspect') + '">' +
            '<span class="cap-dot cap-tone-' + attr(st.tone) + '" aria-hidden="true"></span>' +
            '<span class="cap-rail-body"><span class="cap-rail-label">' + esc(e.label) + '</span>' +
            '<span class="cap-rail-meta">' + n0(e.tools) + ' tool' + (e.tools === 1 ? '' : 's') +
            ' · ' + esc(st.label) + (e.coverage && e.coverage.cells ? ' · ' + round(pct, 0) + '% answered' : '') +
            '</span></span>' +
            '<span class="cap-bar" aria-hidden="true"><i style="width:' + Math.max(0, Math.min(100, pct)) + '%"></i></span>' +
            '</button>';
    }

    // ═════════════════════════════════════════════════════ the sheet board ══
    // The hub omits an unanswered cell rather than shipping thousands of identical
    // objects, so an absent cell IS the "not tested" answer.
    function cellHtml(cell, colUnit) {
        cell = cell || {};
        var st = stateMeta(cell.state || 'untested');
        var g = cell.grade ? gradeMeta(cell.grade) : null;
        var val = cell.text || fmt(cell.value, colUnit);
        var tipRows = [st.label];
        if (g) tipRows.push(g.label + ' — ' + g.hint);
        if (cell.note) tipRows.push(cell.note);
        var soft = cell.grade && ['measured', 'receipt'].indexOf(cell.grade) < 0;
        return '<td class="cap-cell cap-tone-' + attr(st.tone) + (soft ? ' cap-soft' : '') + '"' +
            ' data-cap-tip="' + attr(tipRows.join('\n')) + '" tabindex="0">' +
            '<span class="cap-ico" aria-hidden="true">' + esc(st.icon) + '</span>' +
            (val ? '<span class="cap-val">' + esc(val) + '</span>' : '') +
            (cell.grade ? '<span class="cap-grade cap-grade-' + attr(cell.grade) + '">' +
                esc(cell.grade.slice(0, 1).toUpperCase()) + '</span>' : '') +
            '<span class="cap-sr">' + esc(st.label) + (g ? ', ' + esc(g.label) : '') + '</span>' +
            '</td>';
    }

    // The rating rides next to the name, pinned beside the row head, because a score you
    // have to scroll to is a score nobody reads. The hub computes it from this row's own
    // answered cells (capabilities_hub._row_rating) — this only prints it, so the number
    // and the cells it came from cannot drift apart. `answered/asked` sits under the score
    // on purpose: it is the part that says how much the score is worth.
    function ratingHtml(r) {
        var rt = r.rating;
        if (!rt || !rt.answered) {
            return '<td class="cap-rating cap-rate-none" data-cap-tip="' +
                attr('Not rated\nNo question on this sheet has an answer for this row yet — an ' +
                     'untested row has no score, not a zero.') + '" tabindex="0">' +
                '<span class="cap-rate-score">—</span>' +
                '<span class="cap-rate-cov">not tested</span>' +
                '<span class="cap-sr">not rated</span></td>';
        }
        var b = ratingMeta(rt.band);
        var g = gradeMeta(rt.grade);
        var soft = rt.thin || rt.measured < rt.answered;
        var tip = [b.label + ' — ' + round(rt.score, 0) + ' out of 100',
                   b.hint,
                   rt.answered + ' of ' + n0(rt.asked) + ' questions answered, ' +
                       rt.measured + ' of them measured or on a receipt',
                   'yes 1 · partly ½ · no 0, flipped where the question wants a "no"',
                   g ? 'weakest evidence on it: ' + g.label : '',
                   rt.thin ? 'Provisional — under a quarter of this sheet is answered for this row.' : '']
                  .filter(Boolean).join('\n');
        return '<td class="cap-rating cap-tone-' + attr(b.tone) + (soft ? ' cap-rate-soft' : '') +
            '" data-cap-tip="' + attr(tip) + '" tabindex="0">' +
            '<span class="cap-rate-score">' + esc(round(rt.score, 0)) +
            (rt.thin ? '<i title="provisional">*</i>' : '') + '</span>' +
            '<span class="cap-rate-band">' + esc(b.label) + '</span>' +
            '<span class="cap-rate-cov">' + rt.answered + '/' + n0(rt.asked) + '</span>' +
            '<span class="cap-sr">' + esc(b.label) + ', ' + esc(round(rt.score, 0)) +
            ' out of 100, from ' + rt.answered + ' of ' + n0(rt.asked) + ' questions</span></td>';
    }

    function matrixHtml(m, step, lead) {
        if (!m.columns.length || !m.rows.length) {
            return '<div class="cap-sheet"><p class="mh-note">This sheet has no rows yet.</p></div>';
        }
        var grouped = m.columns.some(function (c) { return c.group; });
        var head = '';
        if (grouped) {
            var spans = [], last = null;
            m.columns.forEach(function (c) {
                var g = c.group || '';
                if (last && last.g === g) last.n++;
                else { last = { g: g, n: 1 }; spans.push(last); }
            });
            head += '<tr class="cap-grouprow"><th class="cap-rowhead"></th>' +
                '<th class="cap-rating cap-rate-groupgap"></th>' +
                spans.map(function (s) {
                    // A one-column band has ~30 px to print its name in, so the band is
                    // clipped and the full name is carried in the tooltip.
                    return '<th colspan="' + s.n + '" class="cap-groupcell" data-cap-tip="' +
                        attr(s.g + ' — ' + s.n + ' question' + (s.n === 1 ? '' : 's')) + '">' +
                        esc(s.g) + '</th>';
                }).join('') + '</tr>';
        }
        head += '<tr><th class="cap-rowhead">Model / tool</th>' +
            '<th class="cap-rating" data-cap-tip="' +
            attr('Rating — this row\'s own answered cells, scored the way each question wants ' +
                 'them answered (yes 1, partly \u00bd, no 0; flipped where a "no" is the good ' +
                 'answer).\nUntested and not-applicable cells are left out, so a gap earns ' +
                 'nothing. The fraction under the score is how many questions it rests on.') +
            '">Rating</th>' + m.columns.map(function (c) {
            return '<th class="cap-colhead" data-cap-tip="' + attr(c.label + (c.hint ? '\n' + c.hint : '') +
                (c.unit && c.unit !== 'text' ? '\nunit: ' + c.unit : '')) + '">' +
                '<span>' + esc(c.label) + '</span>' +
                (!_vert && c.hint ? '<em>' + esc(c.hint) + '</em>' : '') + '</th>';
        }).join('') + '</tr>';

        var body = m.rows.map(function (r) {
            var meta = [r.role, r.licence ? 'licence: ' + r.licence : '', r.where, r.note]
                .filter(Boolean).join('\n');
            return '<tr class="cap-row' + (r.retired ? ' cap-retired' : '') + '" data-cap-row="' + attr(r.id) + '"' +
                ' data-cap-step="' + attr(step) + '">' +
                '<th class="cap-rowhead">' +
                '<span class="cap-rowline" data-cap-tip="' + attr(meta) + '">' +
                '<span class="cap-rowlabel">' + esc(r.label) + (r.retired ? ' <i>retired</i>' : '') + '</span>' +
                '<button type="button" class="cap-rowinspect" data-cap-inspect="' + attr(step) + '" ' +
                'data-cap-inspect-row="' + attr(r.id) + '" aria-label="Inspect ' + attr(r.label) + '" ' +
                'title="Inspect ' + attr(r.label) + ' — the inputs and raw answers behind this row">' +
                inspectIcon() + '</button></span>' +
                (r.role ? '<em>' + esc(r.role) + '</em>' : '') +
                '</th>' +
                ratingHtml(r) +
                m.columns.map(function (c) { return cellHtml(r.cells[c.id] || {}, c.unit); }).join('') +
                '</tr>';
        }).join('');

        return '<div class="cap-sheet">' +
            (m.title ? '<div class="cap-sheet-head"><h4>' + esc(m.title) + '</h4>' +
                (m.hint ? '<p>' + esc(m.hint) + '</p>' : '') +
                '<span class="cap-sheet-size">' + n0(m.columns.length) + ' questions</span>' +
                (lead || '') + '</div>' : '') +
            '<div class="cap-tablewrap"><table class="cap-matrix' + (_vert ? ' cap-vert' : '') +
            '"><thead>' + head + '</thead><tbody>' +
            body + '</tbody></table></div>' +
            (m.note ? '<p class="mh-note">' + esc(m.note) + '</p>' : '') +
            '</div>';
    }

    // The legend used to sit as a bar above every sheet. It is the same 9 rows on all 50
    // steps, so it crowded the board for no new information — it now lives behind the key
    // icon in the toolbar: hover to read it, click to pin it open.
    function legendHtml() {
        var states = Object.keys(_data.states || {}).map(function (k) {
            var s = _data.states[k];
            return '<li><i class="cap-tone-' + attr(s.tone) + '">' + esc(s.icon) + '</i>' +
                '<span><b>' + esc(s.label) + '</b></span></li>';
        }).join('');
        var grades = Object.keys(_data.grades || {}).map(function (k) {
            var g = _data.grades[k];
            return '<li><i class="cap-grade cap-grade-' + attr(k) + '">' +
                esc(k.slice(0, 1).toUpperCase()) + '</i><span><b>' + esc(g.label) + '</b>' +
                '<em>' + esc(g.hint) + '</em></span></li>';
        }).join('');
        var bands = Object.keys(_data.ratings || {}).map(function (k) {
            var b = _data.ratings[k];
            return '<li><i class="cap-rate-swatch cap-tone-' + attr(b.tone) + '">' + esc(b.min) + '+</i>' +
                '<span><b>' + esc(b.label) + '</b><em>' + esc(b.hint) + '</em></span></li>';
        }).join('');
        return '<div class="cap-key-pop" id="cap-key-pop" role="tooltip">' +
            '<div class="cap-key-col"><h5>State — what the cell says</h5><ul>' + states + '</ul></div>' +
            '<div class="cap-key-col"><h5>Rating — the row read back to you</h5><ul>' + bands + '</ul>' +
            '<p>Scored over the questions this sheet <b>answered</b> for that row only: yes 1, ' +
            'partly &frac12;, no 0, flipped where a &ldquo;no&rdquo; is the good answer. The ' +
            'fraction under it is how many questions it rests on; <b>*</b> means under a ' +
            'quarter of the sheet, so the score is provisional.</p></div>' +
            '<div class="cap-key-col"><h5>How we know — the grade on the cell</h5><ul>' + grades + '</ul>' +
            '<p>Only <b>Measured here</b> and <b>Production receipt</b> count as answered. ' +
            'A cell reading &ldquo;can do&rdquo; on a vendor claim is a claim, not a capability.</p>' +
            '</div></div>';
    }

    // Three bars lying the way the column headers do — the icon IS the state, so the
    // button needs no label. title/aria-label carry the words for hover and screen readers.
    function flipIcon(vert) {
        var bars = vert
            ? '<rect x="3" y="2" width="2.6" height="12" rx="1.3"/>' +
              '<rect x="8" y="2" width="2.6" height="12" rx="1.3"/>' +
              '<rect x="13" y="2" width="2.6" height="12" rx="1.3"/>'
            : '<rect x="2" y="3" width="12" height="2.6" rx="1.3"/>' +
              '<rect x="2" y="8" width="12" height="2.6" rx="1.3"/>' +
              '<rect x="2" y="13" width="12" height="2.6" rx="1.3"/>';
        return '<svg viewBox="0 0 18 18" width="14" height="14" aria-hidden="true" fill="currentColor">' +
            bars + '</svg>';
    }
    function searchIcon() {
        return '<svg viewBox="0 0 18 18" width="14" height="14" aria-hidden="true" fill="none" ' +
            'stroke="currentColor" stroke-width="2"><circle cx="8" cy="8" r="5"/>' +
            '<path d="M12 12l4 4" stroke-linecap="round"/></svg>';
    }
    function inspectIcon() {
        return '<svg viewBox="0 0 18 18" width="12" height="12" aria-hidden="true" fill="none" ' +
            'stroke="currentColor" stroke-width="1.9"><circle cx="7.5" cy="7.5" r="4.5"/>' +
            '<path d="M11 11l4.5 4.5" stroke-linecap="round"/></svg>';
    }

    function laneHtml(title, items, open) {
        if (!items.length) return '';
        return '<details class="cap-lane"' + (open ? ' open' : '') + '>' +
            '<summary class="cap-lane-head"><h4>' + esc(title) + '</h4>' +
            '<b>' + items.length + '</b></summary>' +
            '<div class="cap-lane-body">' + items.join('') + '</div></details>';
    }
    function noteCard(text) { return '<div class="cap-note">' + esc(text) + '</div>'; }

    // The DEFAULT TEST behind the sheet: what a new model in this step is run through. The
    // lane says how many questions it answers and how (probe / derive / lookup / wiring / na),
    // its content hash (cells from another hash are another test), and what blocks it.
    function fmtTok(v) {
        v = Number(v) || 0;
        if (v >= 1e6) return (v / 1e6).toFixed(v >= 1e7 ? 0 : 1) + 'M';
        if (v >= 1e3) return Math.round(v / 1e3) + 'k';
        return String(Math.round(v));
    }
    function fmtMin(v) {
        v = Number(v) || 0;
        if (v >= 90) return (v / 60).toFixed(1) + ' h';
        return Math.round(v) + ' min';
    }
    function budgetHtml(b) {
        if (!b || typeof b !== 'object') return '';
        var tot = b.total || {};
        var perRow = n0(b.calls) + ' calls · ' + fmtTok(b.tokens_in) + ' in / ' + fmtTok(b.tokens_out) + ' out tokens · ' +
            fmtMin(b.minutes) + ' wall (' + fmtMin(b.gpu_minutes) + ' GPU) · operator ' + fmtMin(b.operator_minutes);
        var all = 'all ' + n0(b.rows) + ' rows: ' + fmtTok(tot.tokens_in) + ' in / ' + fmtTok(tot.tokens_out) + ' out · ' +
            fmtMin(tot.minutes) + ' wall (' + fmtMin(tot.gpu_minutes) + ' GPU) · operator ' + fmtMin(tot.operator_minutes);
        var tokNote = b.tokens_note ? '<div class="cap-note">' + esc(b.tokens_note) + '</div>' : '';
        return '<div class="cap-note"><b>Expected cost</b> per row: ' + esc(perRow) + '<br>' + esc(all) + '</div>' +
            tokNote + (b.note ? '<div class="cap-note">' + esc(b.note) + '</div>' : '');
    }

    function testLane(t) {
        if (!t || !t.present) return '';
        var d = t.dispositions || {}, parts = [];
        ['probe', 'derive', 'lookup', 'wiring', 'na'].forEach(function (k) {
            if (d[k]) parts.push(n0(d[k]) + ' ' + k);
        });
        var head = '<div class="cap-note"><b>' + esc(t.title || t.module) + '</b> · version ' + esc(t.version || '—') +
            ' · hash <code>' + esc(t.hash || '—') + '</code> · ' + esc(t.module || '') + '</div>';
        var facts = '<div class="cap-note">' + n0(t.columns) + ' questions, every one with a disposition: ' + esc(parts.join(', ')) +
            ' · ' + n0(t.probes) + ' probes, ' + n0(t.operator_checks) + ' blind operator checks · rows: ' +
            esc((t.rows || []).join(', ')) + '</div>';
        // What the test is expected to COST before anyone runs it (per row, and summed over the
        // rows): calls, tokens, wall minutes, GPU minutes, blind operator minutes. An estimate —
        // the note carries the arithmetic; it is not part of the hash.
        var budget = budgetHtml(t.budget);
        var blocked = (t.blocked || []).length
            ? '<div class="cap-note">Blocked until a key is verified: <b>' + esc(t.blocked.join(', ')) +
              '</b> — the runner writes these untested "key unverified".</div>' : '';
        var errs = (t.errors || []).length
            ? '<div class="cap-note mh-banner">' + esc(t.errors.join(' · ')) + '</div>' : '';
        var items = [head, facts, budget, blocked, errs].filter(Boolean);
        return '<details class="cap-lane"' + (t.ok ? '' : ' open') + '>' +
            '<summary class="cap-lane-head"><h4>Default test' + (t.ok ? '' : ' — INVALID') + '</h4>' +
            '<b>' + esc(t.hash || '') + '</b></summary>' +
            '<div class="cap-lane-body">' + items.join('') + '</div></details>';
    }

    function boardHtml() {
        if (!_sel) return '<div class="cap-placeholder"><h3>Pick a step on the left</h3>' +
            '<p>Each step opens its capability sheets: the rows are the models and tools wired into that ' +
            'step of the workflow, the columns are what a test asked of them.</p>' +
            '<p class="mh-note">Right-click a step for <b>Inspect</b> — the inputs, pictures and raw ' +
            'answers behind its sheet.</p></div>';

        var e = railOf(_sel), sh = sheetOf(_sel);
        if (!sh) {
            ensureSheet(_sel);
            if (e && !e.has_sheet) {
                return '<div class="cap-placeholder"><h3>' + esc(e.label) + '</h3>' +
                    '<p>No capability sheet has been recorded for this step yet, so there is nothing ' +
                    'measured to show. Record one with <code>capabilities_hub.record_sheet()</code>.</p></div>';
            }
            return '<p class="mh-empty">Loading ' + esc(e ? e.label : _sel) + '…</p>';
        }
        if (sh.error) return '<p class="mh-banner">Could not load this sheet: ' + esc(sh.error) + '</p>';
        if (sh.missing) {
            return '<div class="cap-placeholder"><h3>' + esc(e ? e.label : _sel) + '</h3>' +
                '<p>The hub has no sheet for this step.</p></div>';
        }
        var cov = sh.coverage || {};
        // Facts and verdict sit INSIDE the first sheet. The old header block above the
        // board repeated the sheet's own title and restated its question, so the operator
        // read the same sentence twice before reaching any data.
        var lead = '<dl class="cap-facts">' +
            '<dt>Tools</dt><dd>' + n0(sh.rows_n) + '</dd>' +
            '<dt>Answered</dt><dd>' + n0(cov.measured_cells) + ' of ' + n0(cov.cells) +
            ' <b>(' + round(cov.pct || 0, 0) + '%)</b></dd>' +
            '<dt>Tested</dt><dd>' + esc(when(sh.tested_at)) + '</dd>' +
            '</dl>' +
            (sh.verdict ? '<p class="cap-verdict">' + esc(sh.verdict) + '</p>' : '');

        var stepLabel = (e && e.label) || sh.title;
        var sheets = sh.matrices.map(function (m, i) {
            return matrixHtml(i === 0 ? dict(m, { title: stepLabel }) : m, _sel, i === 0 ? lead : '');
        }).join('');

        var lanes =
            testLane(sh.default_test) +
            laneHtml('What this sheet means', (sh.notes || []).map(noteCard), false) +
            laneHtml('What it cannot say', (sh.limitations || []).map(noteCard), false) +
            laneHtml('Tests worth running next', (sh.next_tests || []).map(noteCard), false);

        var sources = (sh.sources || []).length
            ? '<details class="cap-lane"><summary class="cap-lane-head"><h4>Sources</h4>' +
              '<b>' + sh.sources.length + '</b></summary>' +
              '<div class="cap-lane-body"><div class="mh-table-wrap">' +
              '<table class="mh-table"><thead><tr><th>Source</th><th>Where</th><th>Note</th></tr></thead><tbody>' +
              sh.sources.map(function (s) {
                  return '<tr><td>' + esc(s.label || s.id) + '</td><td class="cap-path">' + esc(s.path) +
                      '</td><td>' + esc(s.note || '') + '</td></tr>';
              }).join('') + '</tbody></table></div></div></details>'
            : '';

        var errs = (sh.errors || []).length
            ? '<p class="mh-banner">This sheet did not fully validate: ' + esc(sh.errors.join('; ')) + '</p>'
            : '';

        return errs + sheets +
            ((lanes || sources) ? '<div class="cap-about">' + lanes + sources + '</div>' : '');
    }

    // ═════════════════════════════════════════════════════════════ shell ════
    function html(d) {
        _data = d;
        if (!_sel || !railOf(_sel)) _sel = (d.rail && d.rail.length) ? d.rail[0].id : null;
        var t = d.totals || {};
        var summary = n0(t.steps) + ' workflow steps · ' + n0(t.tools) + ' models and tools · ' +
            n0(t.measured_cells) + ' of ' + n0(t.cells) + ' questions answered\n' +
            n0(t.tested) + ' benched · ' + n0(t.partial) + ' with some answers · ' +
            n0(t.untested) + ' with none';
        return '<div class="cap-toolbar">' +
            // The scan time moved to the metrics header's shared "Checked HH:MM:SS"
            // badge (dashboard_tab_metrics.js); the sheet summary keeps this slot.
            '<div class="cap-toolbar-left">' +
            '<span class="cap-sum"><b>' + esc(n0(t.measured_cells)) + '</b> of <b>' +
            esc(n0(t.cells)) + '</b> questions answered</span>' +
            '</div>' +
            '<div class="cap-toolbar-right">' +
            '<span class="cap-keywrap"><button type="button" class="cap-iconbtn" id="cap-key" ' +
            'aria-expanded="false" aria-label="How to read a sheet">\u26bf<span>Legend</span></button>' +
            legendHtml() + '</span>' +
            '<button type="button" class="cap-iconbtn cap-iconbtn-sq" id="cap-flip" ' +
            'aria-pressed="' + _vert + '" aria-label="Column headers: ' +
            (_vert ? 'on their side' : 'flat') + '" title="Column headers are ' +
            (_vert ? 'on their side — click for flat' : 'flat — click to turn them on their side') +
            '">' + flipIcon(_vert) + '</button>' +
            '<span class="cap-searchwrap' + ((_searchOpen || _q) ? ' cap-open' : '') + '">' +
            '<button type="button" class="cap-iconbtn cap-iconbtn-sq" id="cap-searchbtn" ' +
            'aria-label="Filter workflow steps" title="Filter workflow steps">' + searchIcon() + '</button>' +
            '<input type="search" class="cap-search" id="cap-search" placeholder="Filter steps…" ' +
            'value="' + attr(_q) + '" aria-label="Filter workflow steps">' +
            '</span>' +
            '</div></div>' +
            '<div class="cap-wrap">' +
            '<div class="cap-railcol">' +
            '<div class="cap-railhead"><span>The workflow</span>' +
            '<button type="button" class="cap-iconbtn cap-iconbtn-round" id="cap-help" ' +
            'data-cap-tip="' + attr(summary) + '" aria-label="What is on this tab">?</button></div>' +
            '<nav class="cap-rail" role="tablist" aria-label="Workflow steps" id="cap-rail">' +
            railHtml() + '</nav></div>' +
            '<section class="cap-board" id="cap-board" role="tabpanel">' + boardHtml() + '</section>' +
            '</div>';
    }

    function repaintRail() {
        var rail = document.getElementById('cap-rail');
        if (rail) rail.innerHTML = railHtml();
    }

    function repaint() {
        if (!_panel || !_data) return;
        var rail = document.getElementById('cap-rail');
        var board = document.getElementById('cap-board');
        var flip = document.getElementById('cap-flip');
        if (rail) rail.innerHTML = railHtml();
        if (board) board.innerHTML = boardHtml();
        if (flip) {
            flip.innerHTML = flipIcon(_vert);
            flip.setAttribute('aria-pressed', String(_vert));
            flip.setAttribute('aria-label', 'Column headers: ' + (_vert ? 'on their side' : 'flat'));
            flip.setAttribute('title', 'Column headers are ' +
                (_vert ? 'on their side — click for flat' : 'flat — click to turn them on their side'));
        }
    }

    function select(step) {
        if (!step || step === _sel) return;
        _sel = step;
        repaintRail();
        ensureSheet(step);
        paintBoard();
        var board = document.getElementById('cap-board');
        if (board) board.scrollTop = 0;
    }

    // ══════════════════════════════════════════════════════ context menu ════
    function closeMenu() {
        var m = document.getElementById('cap-menu');
        if (m) m.remove();
    }
    function openMenu(x, y, step, rowId) {
        closeMenu();
        var e = railOf(step);
        var sh = sheetOf(step);
        var row = rowId && sh && sh.matrices[0].rows.filter(function (r) { return r.id === rowId; })[0];
        var m = document.createElement('div');
        m.className = 'cap-menu';
        m.id = 'cap-menu';
        m.setAttribute('role', 'menu');
        m.innerHTML = '<div class="cap-menu-head">' + esc(row ? row.label : (e ? e.label : step)) + '</div>' +
            '<button type="button" role="menuitem" data-cap-inspect="' + attr(step) + '"' +
            (rowId ? ' data-cap-inspect-row="' + attr(rowId) + '"' : '') + '>Inspect' +
            '<em>' + (row ? 'this tool\'s inputs and raw answers' :
                'inputs, pictures and raw answers from the test') + '</em></button>';
        document.body.appendChild(m);
        var r = m.getBoundingClientRect();
        m.style.left = Math.min(x, window.innerWidth - r.width - 8) + 'px';
        m.style.top = Math.min(y, window.innerHeight - r.height - 8) + 'px';
        var first = m.querySelector('button');
        if (first) first.focus();
    }

    // ═══════════════════════════════════════════════════════ Inspect page ═══
    function openInspect(step, rowId) {
        closeMenu();
        _inspect = step;
        _inspectRow = rowId || null;
        var ov = document.getElementById('cap-overlay');
        if (!ov) {
            ov = document.createElement('div');
            ov.className = 'cap-overlay';
            ov.id = 'cap-overlay';
            document.body.appendChild(ov);
            ov.addEventListener('click', function (ev) {
                if (ev.target === ov || ev.target.closest('[data-cap-close]')) closeInspect();
            });
            ov.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') closeInspect(); });
        }
        document.body.style.overflow = 'hidden';
        if (_insCache[step]) { paintInspect(_insCache[step]); return; }
        ov.innerHTML = '<div class="cap-page"><p class="mh-empty">Loading the evidence…</p></div>';
        fetch(ENDPOINT + '?inspect=' + encodeURIComponent(step), { credentials: 'same-origin', cache: 'no-store' })
            .then(function (r) { return r.json(); })
            .then(function (j) {
                var doc = j && j.inspect;
                if (!doc || !doc.ok) throw new Error((doc && doc.error) || 'the hub returned no document');
                _insCache[step] = doc;
                if (_inspect === step) paintInspect(doc);
            })
            .catch(function (err) {
                if (_inspect !== step) return;
                var o = document.getElementById('cap-overlay');
                if (o) o.innerHTML = '<div class="cap-page"><div class="cap-page-head"><h3>Inspect</h3>' +
                    '<button type="button" class="cap-btn" data-cap-close>Close ✕</button></div>' +
                    '<p class="mh-banner">Could not load the evidence: ' + esc(err.message || err) + '</p></div>';
            });
    }

    function closeInspect() {
        var ov = document.getElementById('cap-overlay');
        if (ov) ov.remove();
        document.body.style.overflow = '';
        _inspect = null;
        _inspectRow = null;
        if (_io) { _io.disconnect(); _io = null; }
    }

    function picHtml(assetId, label, note, cls) {
        if (!assetId) return '';
        return '<figure class="cap-pic ' + (cls || '') + '" data-cap-asset="' + attr(assetId) + '">' +
            '<div class="cap-pic-slot"><span class="cap-pic-wait">picture loads when it scrolls into view</span></div>' +
            '<figcaption>' + esc(label || '') + (note ? '<em>' + esc(note) + '</em>' : '') + '</figcaption>' +
            '</figure>';
    }

    function answerCell(res) {
        var cls = res.ok === true ? 'good' : (res.ok === false ? 'critical' : 'neutral');
        var mark = res.ok === true ? '✓' : (res.ok === false ? '✕' : '·');
        return '<td class="cap-ans cap-tone-' + cls + '" data-cap-tip="' + attr(res.detail || '') + '">' +
            '<b>' + esc(res.answer == null ? 'no answer' : res.answer) + '</b> ' +
            '<span class="cap-ico">' + mark + '</span>' +
            (res.sec != null ? '<span class="cap-sec">' + fmt(res.sec, 's') + '</span>' : '') +
            '</td>';
    }

    function trialsHtml(doc) {
        if (!doc.trials.length) return '';
        var rows = doc.trials[0].results.map(function (r) { return { id: r.row, label: r.label }; });
        if (_inspectRow) {
            var only = rows.filter(function (r) { return r.id === _inspectRow; });
            // A row can exist on the sheet without being in the bench (a tool added after
            // the run). Say so rather than silently showing every model instead.
            if (!only.length) {
                return '<div class="cap-sheet"><div class="cap-sheet-head"><h4>Every question, every answer</h4></div>' +
                    '<p class="mh-note">' + esc(rowLabel(doc)) + ' was not part of this run, so it has no ' +
                    'answers here. <button type="button" class="cap-piclink" data-cap-scope="all">Show every ' +
                    'model that was</button>.</p></div>';
            }
            rows = only;
        }
        var keep = {};
        rows.forEach(function (r) { keep[r.id] = true; });
        var head = '<tr><th>Asked</th><th>Of</th><th>Expected</th>' +
            rows.map(function (r) { return '<th>' + esc(r.label) + '</th>'; }).join('') + '</tr>';
        var body = doc.trials.map(function (t) {
            var pics = (t.assets || []).map(function (a) {
                return '<button type="button" class="cap-piclink" data-cap-show="' + attr(a) + '">picture</button>';
            }).join(' ');
            return '<tr><td class="cap-qtext"><b>' + esc(t.id) + '</b> ' + esc(t.input) + '</td>' +
                '<td class="cap-qmeta">' + esc(t.picture) + '<em>' + esc(t.crop) + '</em>' + pics + '</td>' +
                '<td class="cap-qexp">' + esc(t.expected == null ? 'not scored' : t.expected) + '</td>' +
                t.results.filter(function (r) { return keep[r.row]; }).map(answerCell).join('') + '</tr>';
        }).join('');
        return '<div class="cap-sheet"><div class="cap-sheet-head"><h4>Every question, every answer</h4>' +
            '<p>The raw output of the run. Hover an answer to read the model\'s own reason.' +
            (_inspectRow ? ' Scoped to <b>' + esc(rows[0].label) + '</b> — ' +
                '<button type="button" class="cap-piclink" data-cap-scope="all">show every model</button>.' : '') +
            '</p></div>' +
            '<div class="cap-tablewrap cap-tablewrap-tall"><table class="cap-matrix cap-trials"><thead>' +
            head + '</thead><tbody>' + body + '</tbody></table></div></div>';
    }

    function rowLabel(doc) {
        var t = (doc.trials || [])[0];
        var hit = t && t.results.filter(function (r) { return r.row === _inspectRow; })[0];
        if (hit) return hit.label;
        var sh = sheetOf(doc.step), m = sh && sh.matrices[0];
        var r = m && m.rows.filter(function (x) { return x.id === _inspectRow; })[0];
        return (r && r.label) || _inspectRow;
    }

    function paintInspect(doc) {
        var ov = document.getElementById('cap-overlay');
        if (!ov) return;
        var head = '<div class="cap-page-head"><div><h3>Inspect — ' + esc(doc.title || doc.label) +
            (_inspectRow ? ' <span class="cap-scope">' + esc(rowLabel(doc)) +
                ' <button type="button" data-cap-scope="all" aria-label="Show every model">\u00d7</button></span>' : '') +
            '</h3>' +
            (doc.question ? '<p>' + esc(doc.question) + '</p>' : '') +
            (doc.verdict ? '<p class="cap-verdict">' + esc(doc.verdict) + '</p>' : '') + '</div>' +
            '<button type="button" class="cap-btn" data-cap-close>Close ✕</button></div>';

        if (doc.empty) {
            ov.innerHTML = '<div class="cap-page">' + head +
                '<p class="mh-note">' + esc(doc.reason) + '</p>' +
                ((doc.sources || []).length ? sourcesTable(doc.sources) : '') + '</div>';
            focusClose(ov);
            return;
        }

        var method = '<div class="cap-about cap-about-open">' +
            laneHtml('What was run',
                (doc.method || []).map(noteCard).concat(
                    doc.command ? ['<div class="cap-note"><pre class="mh-pre">' + esc(doc.command) + '</pre></div>'] : []), true) +
            laneHtml('Conditions',
                Object.keys(doc.environment || {}).map(function (k) {
                    return '<div class="cap-note"><b>' + esc(k) + '</b> ' + esc(String(doc.environment[k])) + '</div>';
                }), true) +
            laneHtml('What it cannot say',
                (doc.limitations || []).map(noteCard), true) +
            '</div>';

        var inputs = (doc.inputs || []).length
            ? '<div class="cap-sheet"><div class="cap-sheet-head"><h4>Inputs — what the models were shown</h4>' +
              '<p>Ground truth was written down before any model ran.</p></div>' +
              '<div class="cap-gallery">' + doc.inputs.map(function (i) {
                  return picHtml(i.asset, i.label, i.truth);
              }).join('') + '</div></div>'
            : '';

        var assets = (doc.assets || []).length
            ? '<details class="mh-twin"><summary>Every picture in this test (' + n0(doc.assets.length) + ')</summary>' +
              '<div class="cap-gallery cap-gallery-small">' + doc.assets.map(function (a) {
                  return a.exists ? picHtml(a.id, a.label, '')
                      : '<figure class="cap-pic cap-pic-missing"><div class="cap-pic-slot">file is gone</div>' +
                        '<figcaption>' + esc(a.label) + '</figcaption></figure>';
              }).join('') + '</div></details>'
            : '';

        var outputs = (doc.outputs || []).length
            ? '<div class="cap-sheet"><div class="cap-sheet-head"><h4>Outputs on disk</h4></div>' +
              '<div class="mh-table-wrap"><table class="mh-table"><thead><tr><th>File</th><th>Where</th></tr></thead><tbody>' +
              doc.outputs.map(function (o) {
                  return '<tr><td>' + esc(o.label) + '</td><td class="cap-path">' + esc(o.path) + '</td></tr>';
              }).join('') + '</tbody></table></div></div>'
            : '';

        var raw = doc.raw
            ? '<details class="mh-twin"><summary>Raw aggregate from the run</summary><pre class="mh-pre">' +
              esc(JSON.stringify(doc.raw, null, 1)) + '</pre></details>'
            : '';

        ov.innerHTML = '<div class="cap-page">' + head +
            (doc.summary ? '<p class="cap-summary">' + esc(doc.summary) + '</p>' : '') +
            method + inputs + trialsHtml(doc) + outputs + assets +
            ((doc.sources || []).length ? sourcesTable(doc.sources) : '') + raw + '</div>';

        bindLazyPictures(ov);
        focusClose(ov);
    }

    function focusClose(ov) {
        var btn = ov.querySelector('[data-cap-close]');
        if (btn) btn.focus();
    }

    function sourcesTable(sources) {
        return '<details class="mh-twin"><summary>Sources</summary><div class="mh-table-wrap">' +
            '<table class="mh-table"><thead><tr><th>Source</th><th>Where</th><th>Note</th></tr></thead><tbody>' +
            sources.map(function (s) {
                return '<tr><td>' + esc(s.label || s.id) + '</td><td class="cap-path">' + esc(s.path) +
                    '</td><td>' + esc(s.note || '') + '</td></tr>';
            }).join('') + '</tbody></table></div></details>';
    }

    // ── lazy pictures ────────────────────────────────────────────────────────
    // Pictures arrive as data URIs on the section endpoint, one call each, and only when
    // the tile scrolls into view: the whole bench is 18 MB of PNG and the board must not
    // pay for it just because the page opened.
    function bindLazyPictures(root) {
        if (_io) _io.disconnect();
        if (!window.IntersectionObserver) {
            root.querySelectorAll('[data-cap-asset]').forEach(loadPicture);
            return;
        }
        _io = new IntersectionObserver(function (entries) {
            entries.forEach(function (en) {
                if (!en.isIntersecting) return;
                _io.unobserve(en.target);
                loadPicture(en.target);
            });
        }, { root: root, rootMargin: '300px' });
        root.querySelectorAll('[data-cap-asset]').forEach(function (fig) { _io.observe(fig); });
    }

    function loadPicture(fig) {
        var id = fig.getAttribute('data-cap-asset');
        var slot = fig.querySelector('.cap-pic-slot');
        if (!id || !slot || fig.__capLoaded) return;
        fig.__capLoaded = true;
        if (_assetCache[id]) { slot.innerHTML = imgTag(_assetCache[id], fig); return; }
        slot.innerHTML = '<span class="cap-pic-wait">loading…</span>';
        if (_assetInflight[id]) return;
        _assetInflight[id] = true;
        fetch(ENDPOINT + '?asset=' + encodeURIComponent(id), { credentials: 'same-origin', cache: 'no-store' })
            .then(function (r) { return r.json(); })
            .then(function (j) {
                delete _assetInflight[id];
                var a = j && j.asset;
                if (!a || !a.ok) throw new Error((a && a.error) || 'not served');
                _assetCache[id] = a;
                document.querySelectorAll('[data-cap-asset="' + id + '"] .cap-pic-slot')
                    .forEach(function (s) { s.innerHTML = imgTag(a); });
            })
            .catch(function (err) {
                delete _assetInflight[id];
                fig.__capLoaded = false;
                slot.innerHTML = '<span class="cap-pic-wait cap-pic-err">' + esc(err.message || err) + '</span>';
            });
    }
    function imgTag(a) {
        return '<img src="' + attr(a.data_uri) + '" alt="" loading="lazy" ' +
            'data-cap-tip="' + attr(a.path) + '">';
    }

    function showPicture(id) {
        // From a trial row: scroll the gallery tile into view and load it now.
        var fig = document.querySelector('[data-cap-asset="' + id + '"]');
        if (fig) {
            fig.scrollIntoView({ block: 'center', behavior: 'smooth' });
            loadPicture(fig);
            fig.classList.add('cap-pic-flash');
            setTimeout(function () { fig.classList.remove('cap-pic-flash'); }, 1400);
        }
    }

    // ══════════════════════════════════════════════════════════ tooltips ════
    function tipEl() {
        var t = document.getElementById('cap-tip');
        if (!t) {
            t = document.createElement('div');
            t.id = 'cap-tip';
            t.className = 'cap-tip';
            document.body.appendChild(t);
        }
        return t;
    }
    function moveTip(ev) {
        var host = ev.target.closest && ev.target.closest('[data-cap-tip]');
        var t = document.getElementById('cap-tip');
        if (!host) { if (t) t.style.display = 'none'; return; }
        var text = host.getAttribute('data-cap-tip');
        if (!text) { if (t) t.style.display = 'none'; return; }
        t = tipEl();
        t.textContent = text;                       // textContent: never parse a payload string
        t.style.display = 'block';
        var w = t.offsetWidth, h = t.offsetHeight;
        t.style.left = Math.min(ev.clientX + 14, window.innerWidth - w - 10) + 'px';
        t.style.top = Math.max(8, Math.min(ev.clientY + 16, window.innerHeight - h - 10)) + 'px';
    }
    function hideTip() {
        var t = document.getElementById('cap-tip');
        if (t) t.style.display = 'none';
    }

    // ═══════════════════════════════════════════════════ board lifecycle ════
    // No-op hook: the shared header badge is written by dashboard_tab_metrics.js.
    function liveText(d, changed) {
        var el = document.getElementById('cap-live-text');
        var live = document.getElementById('cap-live');
        if (!el) return;
        var now = new Date();
        function p2(x) { return (x < 10 ? '0' : '') + x; }
        var hhmm = p2(now.getHours()) + ':' + p2(now.getMinutes());
        // Short on the bar, full detail on hover: the data version and the build time are
        // for diagnosing a stale board, not for reading every 60 s.
        el.textContent = (changed ? 'Updated ' : 'Last scan ') + hhmm;
        if (live) {
            live.setAttribute('data-cap-tip',
                'checked at ' + hhmm + ':' + p2(now.getSeconds()) +
                '\ndata version ' + d.data_version +
                '\ncomputed in ' + n0(d.compute_ms) + ' ms');
        }
        if (live && changed) {
            live.classList.add('cap-live-flash');
            setTimeout(function () { live.classList.remove('cap-live-flash'); }, 1800);
        }
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
        if (changed) { _insCache = {}; _sheetCache = {}; }   // the store moved under us
        if (_sel) ensureSheet(_sel, paintBoard);
        liveText(data, changed);
        if (!panel.__capBound) {
            panel.__capBound = true;
            panel.addEventListener('click', function (ev) {
                if (ev.target.closest('#cap-flip')) {
                    _vert = !_vert;
                    repaint();
                    return;
                }
                var keyBtn = ev.target.closest('#cap-key');
                if (keyBtn) {
                    var wrap = keyBtn.closest('.cap-keywrap');
                    var pinned = wrap.classList.toggle('cap-pinned');
                    keyBtn.setAttribute('aria-expanded', String(pinned));
                    // :focus-within keeps the legend open for keyboard users, which would
                    // also hold it open after a mouse click unpinned it — so drop focus.
                    if (!pinned) keyBtn.blur();
                    return;
                }
                if (!ev.target.closest('#cap-key-pop')) {
                    var open = panel.querySelector('.cap-keywrap.cap-pinned');
                    if (open) {
                        open.classList.remove('cap-pinned');
                        var b = open.querySelector('#cap-key');
                        if (b) b.setAttribute('aria-expanded', 'false');
                    }
                }
                var sb = ev.target.closest('#cap-searchbtn');
                if (sb) {
                    var wrap = sb.closest('.cap-searchwrap');
                    var box = wrap.querySelector('#cap-search');
                    _searchOpen = !wrap.classList.contains('cap-open');
                    wrap.classList.toggle('cap-open', _searchOpen);
                    if (_searchOpen) { box.focus(); box.select(); }
                    else if (_q) { _q = ''; box.value = ''; repaintRail(); }
                    return;
                }
                var ins = ev.target.closest('[data-cap-inspect]');
                if (ins) {
                    ev.preventDefault();
                    openInspect(ins.getAttribute('data-cap-inspect'),
                        ins.getAttribute('data-cap-inspect-row'));
                    return;
                }
                var item = ev.target.closest('[data-cap-step]');
                if (item && item.classList.contains('cap-rail-item')) { select(item.getAttribute('data-cap-step')); }
            });
            panel.addEventListener('contextmenu', function (ev) {
                var item = ev.target.closest('.cap-rail-item') || ev.target.closest('[data-cap-row]');
                if (!item) return;
                ev.preventDefault();
                var step = item.getAttribute('data-cap-step');
                var rowId = item.getAttribute('data-cap-row');
                if (item.classList.contains('cap-rail-item')) select(step);
                openMenu(ev.clientX, ev.clientY, step, rowId);
            });
            panel.addEventListener('pointermove', moveTip);
            panel.addEventListener('pointerleave', hideTip);
            var t = null;
            panel.addEventListener('input', function (ev) {
                if (!ev.target.matches('#cap-search')) return;
                _q = ev.target.value;
                clearTimeout(t);
                t = setTimeout(repaintRail, 160);
            });
            panel.addEventListener('keydown', function (ev) {
                var item = ev.target.closest('.cap-rail-item');
                if (item && (ev.key === 'Enter' || ev.key === ' ')) {
                    ev.preventDefault();
                    select(item.getAttribute('data-cap-step'));
                }
            });
        }
        if (!document.__capGlobal) {
            document.__capGlobal = true;
            document.addEventListener('click', function (ev) {
                var ins = ev.target.closest('#cap-menu [data-cap-inspect]');
                if (ins) {
                    openInspect(ins.getAttribute('data-cap-inspect'),
                        ins.getAttribute('data-cap-inspect-row'));
                    return;
                }
                if (!ev.target.closest('#cap-menu')) closeMenu();
                var show = ev.target.closest('[data-cap-show]');
                if (show) { ev.preventDefault(); showPicture(show.getAttribute('data-cap-show')); return; }
                if (ev.target.closest('[data-cap-scope]')) {
                    ev.preventDefault();
                    _inspectRow = null;
                    if (_inspect && _insCache[_inspect]) paintInspect(_insCache[_inspect]);
                }
            });
            document.addEventListener('keydown', function (ev) {
                if (ev.key !== 'Escape') return;
                if (document.getElementById('cap-menu')) { closeMenu(); return; }
                if (document.getElementById('cap-overlay')) closeInspect();
            });
            document.addEventListener('scroll', closeMenu, true);
            document.addEventListener('pointermove', function (ev) {
                if (ev.target.closest && ev.target.closest('#cap-overlay')) moveTip(ev);
            });
        }
        if (_inspect && _insCache[_inspect]) paintInspect(_insCache[_inspect]);
    }

    function close() {
        closeMenu();
        closeInspect();
        hideTip();
    }
    function redraw() { /* no canvas charts on this board — nothing to redraw */ }

    window.DashboardCapabilities = {
        html: html, mount: mount, same: same, touch: touch,
        redraw: redraw, close: close, open: openInspect
    };
})();
