// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* dashboard_lineage.js v1 — Metrics > Lineage (2026-10-04).
 *
 * One card per model and tool the program has ever used, answering four things in the
 * same place: what it was for, what went wrong with it, what the thing that replaced it
 * actually fixed, and what is still wrong today. The lanes down the page are the chains
 * (image, video, voice, music, ASR, judges, LLM, mesh, vision, infra).
 *
 * Every string, date, count and chain comes from stack_lineage_hub.py, which derives
 * "what the upgrade fixed" from the PREDECESSOR's own issue list — so a card can never
 * claim a fix the thing it replaced does not record. This file only draws.
 *
 * Payload contract (see stack_lineage_hub.build):
 *   totals{} status_counts{} state_counts{} grade_counts{} labels{} span{}
 *   timeline[{month, adopted, ended, found, fixed, events[]}]
 *   lanes[{lane, label, note, counts, chains[{ids,names}], entities[]}]
 *   open_issues[]  problems[]  notes[]  limitations[]  store{}
 * An entity carries: id name kind role status status_label in_stack licence adopted
 *   ended where summary replaced_names[] replaced_by_names[] issues[] issue_counts{}
 *   solved_for[] sources[].
 */
(function () {
    'use strict';

    var _data = null, _panel = null;
    var _lane = 'all', _status = 'all', _q = '', _openOnly = false, _expand = false;

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }
    function n0(v) { return (v == null || isNaN(v)) ? '—' : Number(v).toLocaleString('en-GB'); }
    function plural(n, one, many) { return n0(n) + ' ' + (Number(n) === 1 ? one : (many || one + 's')); }

    // Status always ships with an icon AND a label, never colour alone. These are the
    // dashboard's reserved status steps, not chart-series colours.
    var ST = {
        live: { c: '#0ca30c', ink: '#fff', i: '✓' },
        fallback: { c: '#2a78d6', ink: '#fff', i: '↳' },
        gated_off: { c: '#fab219', ink: '#3d2a00', i: '!' },
        paused: { c: '#fab219', ink: '#3d2a00', i: '‖' },
        broken: { c: '#d03b3b', ink: '#fff', i: '✕' },
        retired: { c: '#bdbbb3', ink: '#2b2a27', i: '–' },
        removed: { c: '#898781', ink: '#fff', i: '✕' },
        rejected: { c: '#ec835a', ink: '#fff', i: '⊘' },
        candidate: { c: '#e3e1da', ink: '#52514e', i: '?' },
        unrecorded: { c: '#e3e1da', ink: '#52514e', i: '?' }
    };
    var IS = {
        open: { c: '#d03b3b', ink: '#fff', i: '✕' },
        unmeasured: { c: '#fab219', ink: '#3d2a00', i: '?' },
        mitigated: { c: '#2a78d6', ink: '#fff', i: '↷' },
        accepted: { c: '#898781', ink: '#fff', i: '=' },
        solved: { c: '#0ca30c', ink: '#fff', i: '✓' }
    };
    // Categorical slots in the dashboard's fixed, validated order (see
    // dashboard_tab_metrics.js). Colour follows the entity, never its rank.
    var SLOT = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100'];

    function label(kind, key) {
        var m = (_data && _data.labels && _data.labels[kind]) || {};
        return m[key] || key;
    }
    function pill(def, text, extra) {
        return '<span class="lin-pill"><i style="background:' + def.c + ';color:' + def.ink + '">' + def.i + '</i>' +
            esc(text) + (extra ? ' <em>' + esc(extra) + '</em>' : '') + '</span>';
    }
    function statusPill(e) { return pill(ST[e.status] || ST.unrecorded, e.status_label || e.status); }
    function statePill(state) { return pill(IS[state] || IS.unmeasured, label('state', state)); }
    function gradeChip(g) {
        return '<span class="lin-grade lin-grade-' + esc(g) + '" title="How we know: ' +
            esc(label('grade', g)) + '">' + esc(g) + '</span>';
    }
    function tile(lab, val, sub) {
        return '<div class="mh-tile"><div class="mh-tile-label">' + esc(lab) + '</div>' +
            '<div class="mh-tile-value">' + esc(val) + '</div>' +
            (sub ? '<div class="mh-tile-sub">' + esc(sub) + '</div>' : '') + '</div>';
    }
    function card(title, body, aside, cls) {
        return '<section class="mh-card' + (cls ? ' ' + cls : '') + '"><header class="mh-card-head">' +
            '<h4>' + title + '</h4>' + (aside ? '<span class="mh-card-aside">' + esc(aside) + '</span>' : '') +
            '</header>' + body + '</section>';
    }
    function dates(e) {
        if (e.adopted && e.ended) return e.adopted + ' → ' + e.ended;
        if (e.adopted) return 'since ' + e.adopted;
        if (e.ended) return 'until ' + e.ended;
        return 'undated';
    }

    // ── the two month strips ─────────────────────────────────────────────────
    // Two measures of different kinds (tools, then problems) are two charts, never two
    // axes on one. Both carry a legend, a hover title per bar and a table twin.
    function strip(title, months, series, note) {
        var max = 1;
        months.forEach(function (m) {
            series.forEach(function (s) { max = Math.max(max, m[s.key] || 0); });
        });
        var H = 104, bars = series.length;
        var cols = months.map(function (m) {
            var inner = series.map(function (s, i) {
                var v = m[s.key] || 0;
                var h = Math.round(v / max * (H - 18));
                return '<span class="lin-bar" style="height:' + Math.max(v ? 3 : 0, h) + 'px;background:' + s.color +
                    '" title="' + esc(m.month + ' · ' + s.label + ': ' + v) + '">' +
                    (v ? '<em>' + v + '</em>' : '') + '</span>';
            }).join('');
            return '<div class="lin-col" style="--bars:' + bars + '"><div class="lin-bars">' + inner + '</div>' +
                '<div class="lin-col-key">' + esc(m.month.slice(5)) + '</div></div>';
        }).join('');
        var legend = '<div class="lin-legend">' + series.map(function (s) {
            return '<span><i style="background:' + s.color + '"></i>' + esc(s.label) + '</span>';
        }).join('') + '</div>';
        var rows = months.map(function (m) {
            return '<tr><td>' + esc(m.month) + '</td>' + series.map(function (s) {
                return '<td class="num">' + n0(m[s.key] || 0) + '</td>';
            }).join('') + '</tr>';
        }).join('');
        var twin = '<details class="lin-twin"><summary>Table view</summary><table class="lin-table"><thead><tr><th>Month</th>' +
            series.map(function (s) { return '<th class="num">' + esc(s.label) + '</th>'; }).join('') +
            '</tr></thead><tbody>' + rows + '</tbody></table></details>';
        return '<div class="lin-strip"><h5>' + esc(title) + '</h5>' + legend +
            '<div class="lin-plot" style="height:' + H + 'px">' + cols + '</div>' +
            (note ? '<p class="lin-note">' + esc(note) + '</p>' : '') + twin + '</div>';
    }

    // ── open-issue board ─────────────────────────────────────────────────────
    function openTable(list) {
        if (!list.length) return '<p class="lin-empty">Nothing open — which would be the first time.</p>';
        return '<div class="lin-tablewrap"><table class="lin-table lin-open-table"><thead><tr>' +
            '<th>Model / tool</th><th>Lane</th><th>State</th><th>How we know</th><th>Found</th><th>What is still wrong</th>' +
            '</tr></thead><tbody>' + list.map(function (i) {
                return '<tr class="lin-jump" data-goto="' + esc(i.entity) + '" tabindex="0">' +
                    '<td><strong>' + esc(i.entity_name) + '</strong>' +
                    (i.in_stack ? '' : ' <em class="lin-muted">(not in the stack)</em>') + '</td>' +
                    '<td>' + esc(i.lane_label) + '</td>' +
                    '<td>' + statePill(i.state) + '</td>' +
                    '<td>' + gradeChip(i.grade) + '</td>' +
                    '<td class="lin-nowrap">' + esc(i.found || '—') + '</td>' +
                    '<td class="lin-issue-text">' + esc(i.text) +
                    (i.evidence ? ' <span class="lin-src">' + esc(i.evidence) + '</span>' : '') + '</td></tr>';
            }).join('') + '</tbody></table></div>';
    }

    // ── one entity ───────────────────────────────────────────────────────────
    function issueList(items) {
        return '<ul class="lin-issues">' + items.map(function (i) {
            var by = i.by && _data.names ? _data.names[i.by] : null;
            var when = i.state === 'solved' ? (i.fixed || '') : (i.found || '');
            return '<li class="lin-issue lin-is-' + esc(i.state) + '">' +
                '<span class="lin-issue-head">' + statePill(i.state) + gradeChip(i.grade) +
                (when ? '<span class="lin-when">' + esc(when) + '</span>' : '') +
                (by ? '<span class="lin-by">by ' + esc(by) + '</span>' : '') + '</span>' +
                '<span class="lin-issue-text">' + esc(i.text) +
                (i.evidence ? ' <span class="lin-src">' + esc(i.evidence) + '</span>' : '') + '</span></li>';
        }).join('') + '</ul>';
    }

    function entityCard(e) {
        var open = (e.issues || []).filter(function (i) { return i.state === 'open' || i.state === 'unmeasured'; });
        var fixed = (e.issues || []).filter(function (i) { return i.state === 'solved'; });
        var carried = (e.issues || []).filter(function (i) { return i.state === 'mitigated' || i.state === 'accepted'; });
        var head = '<header class="lin-card-head"><h5>' + esc(e.name) +
            '<span class="lin-kind">' + esc(e.kind) + '</span></h5>' + statusPill(e) + '</header>';
        var meta = '<div class="lin-meta">' +
            (e.role ? '<span class="lin-role">' + esc(e.role) + '</span>' : '') +
            '<span class="lin-nowrap">' + esc(dates(e)) + '</span>' +
            (e.licence ? '<span title="Licence as read, not as assumed">⚖ ' + esc(e.licence) + '</span>' : '') +
            (e.where ? '<span class="lin-where" title="Where it runs">' + esc(e.where) + '</span>' : '') +
            '</div>';
        var chain = '';
        if ((e.replaced_names || []).length || (e.replaced_by_names || []).length) {
            chain = '<div class="lin-lineage">' +
                (e.replaced_names.length ? '<span><b>took over from</b> ' + esc(e.replaced_names.join(', ')) + '</span>' : '') +
                (e.replaced_by_names.length ? '<span><b>replaced by</b> ' + esc(e.replaced_by_names.join(', ')) + '</span>' : '') +
                '</div>';
        }
        var blocks = '';
        if (open.length) {
            blocks += '<div class="lin-block lin-block-open"><h6>Still wrong today <span>' + open.length + '</span></h6>' +
                issueList(open) + '</div>';
        } else if ((e.issues || []).length) {
            blocks += '<p class="lin-clear">Nothing recorded as still open.</p>';
        } else {
            blocks += '<p class="lin-clear lin-clear-none">No problems recorded — which is not the same as none.</p>';
        }
        var rest = '';
        if (fixed.length) {
            rest += '<div class="lin-block lin-block-fixed"><h6>Fixed <span>' + fixed.length + '</span></h6>' + issueList(fixed) + '</div>';
        }
        if ((e.solved_for || []).length) {
            rest += '<div class="lin-block lin-block-gave"><h6>What this upgrade fixed for what came before <span>' +
                e.solved_for.length + '</span></h6><ul class="lin-issues">' + e.solved_for.map(function (s) {
                    return '<li class="lin-issue lin-is-solved"><span class="lin-issue-head">' +
                        '<span class="lin-for">' + esc(s.entity_name) + '</span>' + gradeChip(s.grade) +
                        (s.fixed ? '<span class="lin-when">' + esc(s.fixed) + '</span>' : '') + '</span>' +
                        '<span class="lin-issue-text">' + esc(s.text) +
                        (s.evidence ? ' <span class="lin-src">' + esc(s.evidence) + '</span>' : '') + '</span></li>';
                }).join('') + '</ul></div>';
        }
        if (carried.length) {
            rest += '<div class="lin-block lin-block-carry"><h6>Worked around or paid for on purpose <span>' +
                carried.length + '</span></h6>' + issueList(carried) + '</div>';
        }
        if ((e.sources || []).length) {
            rest += '<p class="lin-sources">Evidence: ' + e.sources.map(function (s) {
                return '<span class="lin-src">' + esc(s) + '</span>';
            }).join(' ') + '</p>';
        }
        // The summary says what is folded away, so a card with nothing but its sources
        // does not advertise "0 fixes".
        var bits = [];
        if (fixed.length) bits.push(plural(fixed.length, 'fix', 'fixes'));
        if (carried.length) bits.push(plural(carried.length, 'trade-off'));
        if ((e.solved_for || []).length) bits.push('fixed ' + plural(e.solved_for.length, 'problem') + ' for what came before');
        if (!bits.length) bits.push('evidence');
        var tail = rest ? '<details class="lin-more"' + (_expand ? ' open' : '') + '><summary>' +
            esc(bits.join(' · ')) + '</summary>' + rest + '</details>' : '';
        return '<article class="lin-card lin-st-' + esc(e.status) + '" id="lin-' + esc(e.id) + '" ' +
            'data-id="' + esc(e.id) + '" data-lane="' + esc(e.lane) + '" data-status="' + esc(e.status) + '" ' +
            'data-open="' + open.length + '" data-hay="' + esc((e.name + ' ' + (e.role || '') + ' ' + (e.licence || '') +
                ' ' + (e.summary || '') + ' ' + (e.issues || []).map(function (i) { return i.text; }).join(' ')).toLowerCase()) + '">' +
            head + meta + '<p class="lin-sum">' + esc(e.summary || '') + '</p>' + chain + blocks + tail + '</article>';
    }

    function laneSection(l) {
        var chains = (l.chains || []).slice(0, 6).map(function (c) {
            return '<div class="lin-chain">' + c.names.map(function (nm, i) {
                return '<button type="button" class="lin-chain-step" data-goto="' + esc(c.ids[i]) + '">' + esc(nm) + '</button>';
            }).join('<span class="lin-arrow" aria-hidden="true">→</span>') + '</div>';
        }).join('');
        return '<section class="lin-lane" data-lane="' + esc(l.lane) + '">' +
            '<header class="lin-lane-head"><h4>' + esc(l.label) + '</h4>' +
            '<span class="lin-lane-counts">' + plural(l.counts.entities, 'tool') + ' · ' +
            l.counts.in_stack + ' in the stack · ' + plural(l.counts.open, 'open problem') + ' · ' +
            plural(l.counts.solved, 'fix') + '</span></header>' +
            (l.note ? '<p class="lin-lane-note">' + esc(l.note) + '</p>' : '') +
            (chains ? '<div class="lin-chains">' + chains + '</div>' : '') +
            '<div class="lin-cards">' + l.entities.map(entityCard).join('') + '</div></section>';
    }

    // ── the page ─────────────────────────────────────────────────────────────
    function html(d) {
        _data = d;
        // id -> name, so an issue's "by" can be printed without the server repeating it.
        _data.names = {};
        (d.lanes || []).forEach(function (l) {
            (l.entities || []).forEach(function (e) { _data.names[e.id] = e.name; });
        });
        var t = d.totals || {};
        var banner = (d.problems && d.problems.length) ?
            '<p class="mh-banner">The store has ' + plural(d.problems.length, 'problem') +
            ' — run <code>python3 stack_lineage_hub.py check</code>: ' + esc(d.problems.slice(0, 3).join(' · ')) + '</p>' : '';

        var tiles = '<div class="mh-tiles lin-tiles">' +
            tile('Models & tools', n0(t.entities), (d.span && d.span.first ? d.span.first + ' → ' + d.span.last : '') + ' · ' + plural(t.lanes, 'lane')) +
            tile('In the stack now', n0(t.in_stack), (d.status_counts.live || 0) + ' live · ' + (d.status_counts.gated_off || 0) + ' installed but off · ' + (d.status_counts.paused || 0) + ' paused') +
            tile('Replaced or deleted', n0(t.gone), (d.status_counts.retired || 0) + ' retired · ' + (d.status_counts.removed || 0) + ' removed from disk') +
            tile('Measured and refused', n0(t.refused), 'the incumbent won, or the licence did') +
            tile('Problems fixed', n0(t.solved), 'each one read off the predecessor it belonged to') +
            tile('Still wrong today', n0(t.open), (d.state_counts.unmeasured || 0) + ' of them never measured') +
            tile('Carried on purpose', n0(t.carried), (d.state_counts.mitigated || 0) + ' worked around · ' + (d.state_counts.accepted || 0) + ' accepted costs') +
            tile('Measured, not claimed', n0(d.grade_counts.measured) + ' / ' + n0(t.issues), (d.grade_counts.licence || 0) + ' licence reads · ' + (d.grade_counts.vendor || 0) + ' vendor claims') +
            '</div>';

        var months = d.timeline || [];
        var strips = '<div class="lin-strips">' +
            strip('Tools adopted and retired, by month', months,
                [{ key: 'adopted', label: 'Adopted', color: SLOT[0] }, { key: 'ended', label: 'Retired or removed', color: SLOT[1] }],
                'Counted on the date in the record. Nothing before 2026-05-08 is recorded on this box.') +
            strip('Problems recorded and fixed, by month', months,
                [{ key: 'found', label: 'Recorded', color: SLOT[1] }, { key: 'fixed', label: 'Fixed', color: SLOT[2] }],
                'A problem is counted in the month it was written down, and a fix in the month it landed.') +
            '</div>';

        var laneChips = '<button type="button" class="lin-chip' + (_lane === 'all' ? ' on' : '') + '" data-lane="all">All lanes</button>' +
            (d.lanes || []).map(function (l) {
                return '<button type="button" class="lin-chip' + (_lane === l.lane ? ' on' : '') + '" data-lane="' + esc(l.lane) + '">' +
                    esc(l.label) + ' <em>' + l.counts.entities + '</em></button>';
            }).join('');
        var statusChips = ['all'].concat(Object.keys(ST).filter(function (s) { return (d.status_counts || {})[s]; }))
            .map(function (s) {
                return '<button type="button" class="lin-chip lin-chip-st' + (_status === s ? ' on' : '') + '" data-status="' + esc(s) + '">' +
                    (s === 'all' ? 'Any state' : esc(label('status', s)) + ' <em>' + d.status_counts[s] + '</em>') + '</button>';
            }).join('');

        var controls = '<div class="lin-controls">' +
            '<div class="lin-chips">' + laneChips + '</div>' +
            '<div class="lin-chips lin-chips-2">' + statusChips + '</div>' +
            '<div class="lin-tools">' +
            '<label class="lin-search"><span aria-hidden="true">⌕</span>' +
            '<input type="search" id="lin-q" value="' + esc(_q) + '" placeholder="search a model, a licence, a defect…" ' +
            'aria-label="Filter models and tools"></label>' +
            '<label class="lin-toggle"><input type="checkbox" id="lin-openonly"' + (_openOnly ? ' checked' : '') +
            '> only what is still wrong</label>' +
            '<button type="button" class="lin-btn" id="lin-expand">' + (_expand ? 'Collapse histories' : 'Expand histories') + '</button>' +
            '</div><p class="lin-count" id="lin-count"></p></div>';

        var openCard = card('Still wrong today, ranked by what you can act on',
            openTable(d.open_issues || []),
            plural((d.open_issues || []).length, 'open problem') + ' · in-stack first, then measured over reasoned, then newest',
            'lin-opencard');

        var foot = card('How to read this tab',
            '<ul class="mh-notes">' + (d.notes || []).map(function (n) { return '<li>' + esc(n) + '</li>'; }).join('') +
            '</ul><h6 class="lin-foot-h">Limits</h6><ul class="mh-notes">' +
            (d.limitations || []).map(function (n) { return '<li>' + esc(n) + '</li>'; }).join('') + '</ul>' +
            '<p class="lin-note">Store: <code>' + esc((d.store || {}).path || '') + '</code> — ' +
            ((d.store || {}).files || []).map(function (f) { return '<span class="lin-src">' + esc(f) + '</span>'; }).join(' ') +
            '. Dated chart: <code>' + esc((d.store || {}).chart || '') + '</code>. ' +
            'Add a row the day a swap goes live, then run <code>python3 stack_lineage_hub.py check</code>.</p>',
            '', 'lin-foot');

        return '<div class="lin">' + banner + tiles + strips + controls + openCard +
            '<div class="lin-lanes">' + (d.lanes || []).map(laneSection).join('') + '</div>' + foot + '</div>';
    }

    // ── filtering ────────────────────────────────────────────────────────────
    function applyFilters() {
        if (!_panel) return;
        var shown = 0, hidden = 0;
        _panel.querySelectorAll('.lin-card').forEach(function (c) {
            var ok = (_lane === 'all' || c.getAttribute('data-lane') === _lane) &&
                (_status === 'all' || c.getAttribute('data-status') === _status) &&
                (!_openOnly || +c.getAttribute('data-open') > 0) &&
                (!_q || c.getAttribute('data-hay').indexOf(_q) >= 0);
            c.classList.toggle('lin-hide', !ok);
            if (ok) shown++; else hidden++;
        });
        _panel.querySelectorAll('.lin-lane').forEach(function (l) {
            var any = l.querySelector('.lin-card:not(.lin-hide)');
            l.classList.toggle('lin-hide', !any);
        });
        var c = _panel.querySelector('#lin-count');
        if (c) {
            c.textContent = hidden ? (shown + ' of ' + (shown + hidden) + ' shown') :
                (shown + ' shown — no filter');
        }
    }
    function chipRow(el, attrName, value) {
        el.parentNode.querySelectorAll('.lin-chip').forEach(function (b) {
            b.classList.toggle('on', b.getAttribute(attrName) === value);
        });
    }
    function goTo(id) {
        var el = _panel && _panel.querySelector('#lin-' + (window.CSS && CSS.escape ? CSS.escape(id) : id));
        if (!el) return;
        // A jump into a hidden card would scroll to nothing, so clear the filters first.
        if (el.classList.contains('lin-hide')) {
            _lane = 'all'; _status = 'all'; _openOnly = false; _q = '';
            var q = _panel.querySelector('#lin-q'); if (q) q.value = '';
            var o = _panel.querySelector('#lin-openonly'); if (o) o.checked = false;
            _panel.querySelectorAll('.lin-chip').forEach(function (b) {
                b.classList.toggle('on', b.getAttribute('data-lane') === 'all' || b.getAttribute('data-status') === 'all');
            });
            applyFilters();
        }
        var more = el.querySelector('.lin-more');
        if (more) more.open = true;
        el.scrollIntoView({ block: 'center', behavior: 'smooth' });
        el.classList.add('lin-flash');
        setTimeout(function () { el.classList.remove('lin-flash'); }, 1600);
    }

    // ── board lifecycle ──────────────────────────────────────────────────────
    function same(panel, data) { return !!(_data && data && _data.data_version === data.data_version); }
    function touch(panel, data) {
        if (data && _data) { _data.generated_at = data.generated_at; _data.compute_ms = data.compute_ms; }
    }
    function mount(panel, data) {
        _panel = panel;
        _data = data;
        applyFilters();
        if (panel.__linBound) return;
        panel.__linBound = true;
        panel.addEventListener('click', function (ev) {
            var lane = ev.target.closest('.lin-chip[data-lane]');
            if (lane) { _lane = lane.getAttribute('data-lane'); chipRow(lane, 'data-lane', _lane); applyFilters(); return; }
            var st = ev.target.closest('.lin-chip[data-status]');
            if (st) { _status = st.getAttribute('data-status'); chipRow(st, 'data-status', _status); applyFilters(); return; }
            var exp = ev.target.closest('#lin-expand');
            if (exp) {
                _expand = !_expand;
                panel.querySelectorAll('.lin-more').forEach(function (m) { m.open = _expand; });
                exp.textContent = _expand ? 'Collapse histories' : 'Expand histories';
                return;
            }
            var jump = ev.target.closest('[data-goto]');
            if (jump) { goTo(jump.getAttribute('data-goto')); }
        });
        panel.addEventListener('keydown', function (ev) {
            if (ev.key !== 'Enter' && ev.key !== ' ') return;
            var row = ev.target.closest && ev.target.closest('tr.lin-jump');
            if (row) { ev.preventDefault(); goTo(row.getAttribute('data-goto')); }
        });
        panel.addEventListener('input', function (ev) {
            if (ev.target.id === 'lin-q') { _q = String(ev.target.value || '').toLowerCase().trim(); applyFilters(); }
        });
        panel.addEventListener('change', function (ev) {
            if (ev.target.id === 'lin-openonly') { _openOnly = !!ev.target.checked; applyFilters(); }
        });
    }
    function close() { }
    function redraw() { }

    window.DashboardLineage = { html: html, mount: mount, same: same, touch: touch, close: close, redraw: redraw };
})();
