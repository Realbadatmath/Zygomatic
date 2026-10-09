// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Dashboard tab: Approval Queue — Zero Production Queue
 *
 * Rebuilt 2026-09-20 as a kanban of WORKFLOW cards served by ONE endpoint
 * (bp_approval_queue.py — see scratchpad/approval_queue_contract.md):
 *
 *   Production Queue    [5-hour ▮▮▮░ 41%] [7-day ▮▮░░ 32%] [QUOTA HOLD — …]   [Refresh]
 *   ┌ Workflows ─┐ ┌ Calendar / production ──────────────────────────────┐
 *   │ ● Docu   ▶⏸⏹│ │  the panel takes the rest of the page and can be     │
 *   │ ▪ Story  ▶⏸⏹│ │  dragged to any size by the grip in its corner ──┐   │
 *   │ ▪ Melody ▶⏸⏹│ │                                                  ◢   │
 *   └────────────┘ └─────────────────────────────────────────────────────┘
 *
 * A card carries a name, a state pill and its ▶ ⏸ ⏹ buttons (enabled per
 * `workflow.actions`) — nothing else. Clicking it opens a DIALOG with what the
 * workflow does, its status chips, its state note, the preempt targets, the item
 * board, the settings form and the recent-activity list; Esc, ✕ or a click
 * outside closes it.
 *
 * Polling: GET /api/approval_queue/board every 15 s; the board is only
 * redrawn when its signature changed (no flicker). The open dialog, dirty
 * settings forms, in-flight actions and inline errors live in module-level
 * objects keyed by workflow id, so a poll never collapses a card nor wipes an
 * unsaved form (the dirty form's DOM node is transplanted into the new render).
 *
 * 2026-09-22 (v7): the board takes the whole page (everything right of the sidebar) and a
 * PANEL sits beside the cards — a 7/14/28-day calendar of what production is planned, or the
 * same window as production numbers (items, hours expected vs real, token cost, the share of
 * the machine each workflow took). The icon above the panel switches calendar ⇄ production;
 * the window can be anchored anywhere from a year back to 28 days ahead. Everything it draws
 * comes from /api/approval_queue/calendar (production_calendar.py) — nothing is computed here.
 *
 * 2026-09-28 (v12): the panel no longer opens at a stored pixel height. Its body is measured
 * after every render and on every window resize (fitPanel) and given a max-height that reaches
 * the bottom of the viewport, so the board opens as big as the window allows and anything longer
 * scrolls inside the panel — a scrollbar on its right — instead of pushing the page down. The
 * grip still pins a height by hand (double-click = back to the fit); a height saved by v11 is
 * dropped once, `zq.cal` now carries `v:2`.
 *
 * 2026-09-22 (v11): the five state columns are gone and the cards are a slim strip down the
 * left, so the panel gets the rest of the page; its bottom-right grip drags panel width and
 * body height (kept in localStorage `zq.cal`, double-click resets). A poll cannot redraw the
 * panel while the grip is down, and the drag is scaled by the ratio the element reports —
 * this GUI runs at html{zoom:.67}, where pointer coords and rects are screen px.
 *
 * Endpoints:  GET  /api/approval_queue/board
 *             GET  /api/approval_queue/calendar?view=&anchor=&days=
 *             POST /api/approval_queue/<wf>/action          {action}
 *             POST /api/approval_queue/<wf>/settings        {key: value, …}
 *             POST /api/approval_queue/<wf>/item/<id>/action {action:"delete"}  (preempt only)
 * Previous versions: *.bak-preempt-20260920 (three toggles + per-channel boards),
 * *.bak-calendar-20260922 (five state columns + expand-in-place),
 * *.bak-calspace-20260922 (the same, just before the dialog/strip rebuild).
 */
(function () {
    'use strict';

    var BOARD_URL = '/api/approval_queue/board';
    var CAL_URL   = '/api/approval_queue/calendar';
    var POLL_MS   = 15000;
    var CAL_POLL_MS = 60000;      // the calendar moves in days, not seconds

    var _refreshTimer = null;
    var _lastSig   = null;   // skip the 15 s re-render when nothing moved (no flicker)
    var _container = null;
    var _board     = null;   // last board payload (server truth, patched locally after a save/action)
    var _dialog    = null;   // wf id whose detail dialog is open (one at a time, survives polls)
    var _dirty     = {};     // wf id -> true while its settings form has unsaved edits
    var _pending   = {};     // wf id -> true while an action POST is in flight
    var _errors    = {};     // wf id -> inline error text shown on the card
    var _saveMsg   = {};     // wf id -> {ok:bool, text} next to "Save settings"
    var _fetchErr  = '';     // last poll failure (shown in the header, board kept)

    // ── side panel (calendar / production overview) ──────────────────────────
    var _cal      = null;    // last calendar payload
    var _calView  = 'calendar';
    var _calDays  = 7;
    var _calAnchor = '';     // '' = today; an ISO date pins the window
    var _calSel   = '';      // the day whose detail strip is open
    var _calErr   = '';
    var _calBusy  = false;
    var _calTimer = null;
    var _calOpen  = true;    // the panel can be folded away to give the cards the full width
    var _calW     = 0;       // px the operator dragged the panel to (0 = the layout decides)
    var _calH     = 0;       // px height of the panel body            (0 = AUTO: fit to the window)
    var _sizing   = false;   // true while the corner grip is down: no poll may redraw under it
    var _grab     = null;    // {x0,y0,w0,h0,scale} of the drag in progress
    var _fitH     = 0;       // last measured auto height (CSS px) — drawn straight into the
                             // next render so the panel never flashes at full length first
    var _tapAt    = 0;       // ms of the last grip press that did NOT drag (double-press = reset)
    var _tapXY    = null;    // where that press landed, so a press elsewhere is not a double-press
    var _fitTimer = null;    // debounce for the window-resize re-fit
    var PREF_V    = 2;       // pref schema; a v1 blob's dragged height is dropped (auto is the default now)
    var FIT_GAP   = 26;      // CSS px left under the panel so the page itself never has to scroll
    var FIT_MIN   = 320;     // CSS px: never squeeze the panel below this, however short the window

    function prefLoad() {
        try {
            var raw = window.localStorage.getItem('zq.cal');
            if (!raw) return;
            var p = JSON.parse(raw);
            if (p && (p.view === 'calendar' || p.view === 'production')) _calView = p.view;
            if (p && (p.days === 7 || p.days === 14 || p.days === 28)) _calDays = p.days;
            if (p && p.open === false) _calOpen = false;
            if (p && Number(p.w) > 0) _calW = Math.round(Number(p.w));
            // A height saved before the auto-fit (v1) is dropped: the panel now sizes itself
            // to the window, and only a fresh drag pins it again.
            if (p && Number(p.v) >= 2 && Number(p.h) > 0) _calH = Math.round(Number(p.h));
        } catch (e) { /* private window / blocked storage: the defaults stand */ }
    }

    function prefSave() {
        try {
            window.localStorage.setItem('zq.cal', JSON.stringify(
                {v: PREF_V, view: _calView, days: _calDays, open: _calOpen, w: _calW, h: _calH}));
        } catch (e) { /* nothing here is worth failing a render over */ }
    }

    // ── helpers ──────────────────────────────────────────────────────────────
    function esc(s) {
        if (s == null) return '';
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    function fmtTs(ts) {
        if (!ts) return '';
        return String(ts).replace('T', ' ').slice(0, 16);
    }

    /** "23 days ago" / "4 h ago" — so a finished batch cannot masquerade as live work. */
    function ageLabel(ts) {
        if (!ts) return '';
        var t = Date.parse(String(ts));
        if (isNaN(t)) return '';
        var mins = Math.floor((Date.now() - t) / 60000);
        if (mins < 2)    return 'just now';
        if (mins < 60)   return mins + ' min ago';
        if (mins < 1440) return Math.floor(mins / 60) + ' h ago';
        var d = Math.floor(mins / 1440);
        return d + (d === 1 ? ' day ago' : ' days ago');
    }

    /** Server accents go into style attributes: only a 6-digit hex colour is trusted. */
    function colorOk(c) {
        return /^#[0-9a-fA-F]{6}$/.test(String(c || '')) ? String(c) : '#7a8290';
    }

    function closest(node, sel, root) {
        var n = node;
        while (n && n !== root && n.nodeType === 1) {
            var m = n.matches || n.msMatchesSelector || n.webkitMatchesSelector;
            if (m && m.call(n, sel)) return n;
            n = n.parentNode;
        }
        return null;
    }

    function findWf(id) {
        var list = (_board && _board.workflows) || [];
        for (var i = 0; i < list.length; i++) if (list[i] && list[i].id === id) return list[i];
        return null;
    }

    function patchWorkflow(wf) {
        if (!wf || !wf.id || !_board) return;
        var list = _board.workflows || (_board.workflows = []);
        for (var i = 0; i < list.length; i++) {
            if (list[i] && list[i].id === wf.id) { list[i] = wf; return; }
        }
        list.push(wf);
    }

    /** Elements carrying data-wf="<id>" (ids are server strings — compare, don't build selectors). */
    function byWf(root, sel, id) {
        var els = root ? root.querySelectorAll(sel) : [];
        for (var i = 0; i < els.length; i++) if (els[i].getAttribute('data-wf') === id) return els[i];
        return null;
    }

    /** Board signature without the per-request timestamps, else every poll would "change". */
    function sigOf(board) {
        try {
            var q = {}, src = (board && board.quota) || {};
            Object.keys(src).forEach(function (k) { if (k !== 'sampled_at') q[k] = src[k]; });
            return JSON.stringify({quota: q, workflows: (board && board.workflows) || []});
        } catch (e) { return null; }
    }

    function postJson(url, payload) {
        return fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload || {})
        }).then(function (r) {
            return r.text().then(function (txt) {
                var body = null;
                try { body = txt ? JSON.parse(txt) : null; } catch (e) { body = null; }
                var ok = !!r.ok && !(body && body.ok === false);
                var error = ok ? '' : ((body && (body.error || body.message))
                                       || ('HTTP ' + r.status + (txt && !body ? ' · ' + txt.slice(0, 120) : '')));
                return {ok: ok, status: r.status, body: body, error: String(error)};
            });
        }).catch(function (e) {
            return {ok: false, status: 0, body: null, error: String((e && e.message) || e)};
        });
    }

    // ── vocab ────────────────────────────────────────────────────────────────
    var STATES = [
        {key:'off',       label:'Off',       color:'#9aa0aa'},
        {key:'waiting',   label:'Waiting',   color:'#7a8290'},
        {key:'running',   label:'Running',   color:'#1f8ea8'},
        {key:'paused',    label:'Paused',    color:'#b5761f'},
        {key:'attention', label:'Attention', color:'#c0392b'}
    ];
    var STATE_BY = {};
    STATES.forEach(function (s) { STATE_BY[s.key] = s; });

    function stateOf(wf) {
        if (STATE_BY[wf.state]) return wf.state;
        return wf.enabled ? 'waiting' : 'off';
    }

    var COL_COLORS = {
        scheduled:    '#7a8290',
        in_production:'#1f8ea8',
        done:         '#2e8b57',
        failed:       '#c0392b',
        blocked:      '#b5761f',
        building:     '#1f8ea8',
        ready:        '#2e8b57',
        claimed:      '#6b5cc4',
        consumed:     '#7a8290'
    };

    // ── styles ───────────────────────────────────────────────────────────────
    var CSS = [
        '@keyframes zq-pulse{0%,100%{opacity:1}50%{opacity:.3}}',
        '.zq-pulse{animation:zq-pulse 1.4s ease-in-out infinite}',
        /* The shared .container caps every tab at 1400px. The queue is a board: it takes
           everything right of the sidebar while it is the visible tab (the :has() guard). */
        '.dashboard-main > .container:has(> #panel-approval_queue.active){max-width:none;padding:0;}',
        '#panel-approval_queue{padding:16px 18px 24px;}',
        '.zq-root{color:#2f3440;max-width:none;margin:0;}',
        '.zq-main{display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap;}',
        /* The cards are a slim strip down the left — a name, a state and its buttons; every
           number, note and setting lives in the card's dialog. The calendar takes the rest. */
        '.zq-left{flex:0 0 250px;min-width:0;}',
        '.zq-side{flex:1 1 560px;min-width:0;max-width:none;position:sticky;top:10px;}',
        '.zq-side.zq-side-shut{flex:0 0 42px;min-width:42px;max-width:42px;}',
        /* Dragged by the corner grip: the width is then the operator\'s, not the layout\'s
           (an oversized panel wraps under the strip instead of overflowing the page). */
        '.zq-side.zq-side-set{flex:0 0 auto;position:static;}',
        '@media (max-width:1100px){.zq-left{flex:1 1 100%;}.zq-side{flex:1 1 100%;position:static;}}',
        '.zq-head{display:flex;align-items:flex-end;gap:16px;margin:0 0 18px;flex-wrap:wrap;}',
        '.zq-head .zq-title{flex:1 1 240px;min-width:200px;}',
        '.zq-head .zq-quota{flex:0 1 auto;min-width:0;max-width:100%;}',
        '.zq-head .zq-btn{flex:0 0 auto;}',
        '.zq-head h3{margin:0 0 4px;text-align:left;}',
        '.zq-sub{font-size:11.5px;color:#6d7280;}',
        '.zq-sub code{color:#4a5060;font-size:11px;background:#eeece8;border:1px solid #ddd9d2;border-radius:4px;padding:1px 5px;}',
        '.zq-sub .zq-err{color:#c0392b;}',
        '.zq-spacer{margin-left:auto;}',
        '.zq-btn{background:linear-gradient(180deg,#fdfdfd,#e9e7e2);color:#3a4050;border:1px solid #c9c5bd;',
        '  border-radius:8px;padding:6px 15px;font-size:11.5px;font-weight:600;cursor:pointer;',
        '  box-shadow:0 1px 2px rgba(0,0,0,.06);transition:background .15s;}',
        '.zq-btn:hover{background:linear-gradient(180deg,#fff,#f2f0ec);}',
        '.zq-btn:disabled{opacity:.5;cursor:progress;}',
        '.zq-muted{color:#9aa0aa;}',

        /* quota strip */
        '.zq-quota{display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding-bottom:4px;}',
        '.zq-meter{min-width:150px;}',
        '.zq-meter-l{display:flex;justify-content:space-between;font-size:10px;font-weight:700;text-transform:uppercase;',
        '  letter-spacing:.09em;color:#6d7280;margin-bottom:4px;}',
        '.zq-meter-l b{font-size:11px;letter-spacing:0;}',
        '.zq-meter-r{font-size:10px;color:#9aa0aa;margin-top:4px;white-space:nowrap;}',
        '.zq-bar{height:7px;border-radius:999px;background:#e6e3dd;overflow:hidden;}',
        '.zq-bar i{display:block;height:100%;border-radius:999px;background:#2e8b57;transition:width .3s;}',
        '.zq-hold{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#fff;line-height:1.4;',
        '  background:#c0392b;border-radius:6px;padding:5px 10px;box-shadow:0 1px 2px rgba(0,0,0,.15);min-width:0;}',
        '.zq-hold span{text-transform:none;letter-spacing:.02em;font-weight:500;}',

        /* workflow strip — the five state columns are gone; the pill carries the state */
        '.zq-strip{display:flex;flex-direction:column;gap:9px;}',
        '.zq-strip-h{display:flex;align-items:center;gap:7px;font-size:10px;font-weight:700;text-transform:uppercase;',
        '  letter-spacing:.10em;color:#6d7280;padding-bottom:8px;border-bottom:2px solid #e2ded7;}',
        '.zq-count{margin-left:auto;background:#fff;border:1px solid #ddd9d2;color:#6d7280;',
        '  border-radius:9px;padding:1px 7px;font-size:10px;letter-spacing:.02em;font-weight:600;}',

        /* workflow card */
        '.zq-wcard{background:#fff;border:1px solid #d8d4cd;border-left:4px solid #7a8290;border-radius:10px;overflow:hidden;',
        '  box-shadow:0 1px 3px rgba(60,55,45,.08);}',
        '.zq-wbody{padding:9px 11px 8px;cursor:pointer;transition:background .15s;position:relative;}',
        '.zq-more{margin-left:auto;font-size:10px;color:#9aa0aa;white-space:nowrap;}',
        '.zq-wbody:hover{background:#fdfcfa;}',
        '.zq-wtop{display:flex;align-items:flex-start;gap:8px;padding-right:16px;}',
        '.zq-wtop .zq-led{margin-top:5px;}',
        '.zq-led{width:9px;height:9px;border-radius:50%;flex:0 0 9px;}',
        '.zq-name{font-size:13.5px;font-weight:700;color:#2f3440;letter-spacing:.01em;flex:1 1 auto;min-width:0;line-height:1.4;}',
        '.zq-pill{display:inline-block;font-size:9px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;',
        '  border-radius:4px;padding:2px 6px;border:1px solid;white-space:nowrap;margin-left:8px;vertical-align:1.5px;line-height:1.3;}',
        '.zq-caret{position:absolute;top:11px;right:12px;color:#b0b4bc;font-size:12px;}',
        '.zq-desc{font-size:11.5px;color:#7b8090;margin-top:5px;line-height:1.45;}',
        '.zq-chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;}',
        '.zq-chip{font-size:10.5px;border-radius:999px;padding:2px 10px;background:#f4f3f0;',
        '  border:1px solid #ddd9d2;color:#6d7280;white-space:nowrap;}',
        '.zq-chip b{font-weight:700;}',
        '.zq-chip.idle{color:#a5a9b2;border-style:dashed;background:transparent;}',
        '.zq-snote{font-size:11px;color:#6d7280;margin-top:8px;line-height:1.5;padding:6px 9px;',
        '  background:#f7f6f3;border-radius:6px;border:1px solid #eeece8;}',
        '.zq-acts{display:flex;align-items:center;gap:6px;margin-top:10px;font-size:10.5px;}',
        '.zq-ib{width:32px;height:26px;border-radius:7px;border:1px solid #c9c5bd;color:#3a4050;font-size:12px;',
        '  background:linear-gradient(180deg,#fdfdfd,#e9e7e2);cursor:pointer;box-shadow:0 1px 2px rgba(0,0,0,.06);padding:0;}',
        '.zq-ib:hover{background:linear-gradient(180deg,#fff,#f2f0ec);}',
        '.zq-ib.play{color:#2e8b57;} .zq-ib.pause{color:#b5761f;} .zq-ib.abort{color:#c0392b;}',
        '.zq-ib:disabled{opacity:.32;cursor:not-allowed;color:#6d7280;box-shadow:none;}',
        '.zq-cerr{margin-top:8px;font-size:11px;color:#c0392b;background:#fdf1ef;border:1px solid #f1c9c3;',
        '  border-radius:6px;padding:5px 9px;line-height:1.45;}',

        /* preempt targets */
        '.zq-tgts{margin-top:10px;}',
        '.zq-tgt{margin-top:8px;}',
        '.zq-tgt-h{display:flex;justify-content:space-between;gap:8px;font-size:11px;font-weight:600;color:#2f3440;margin-bottom:4px;}',
        '.zq-tgt-h span:last-child{color:#7b8090;font-weight:500;white-space:nowrap;}',
        '.zq-tgt-note{font-size:10.5px;color:#7b8090;margin-top:4px;}',
        '.zq-tgt-cur{font-size:10.5px;color:#1f8ea8;margin-top:3px;line-height:1.4;}',
        '.zq-tgt-info{font-size:10px;color:#9aa0aa;margin-top:4px;line-height:1.45;font-style:italic;}',

        /* expanded body */
        '.zq-wx{border-top:1px solid #e2ded7;background:#fbfaf8;padding:12px 14px 14px;}',
        '.zq-bnote{font-size:11px;color:#8a8f9b;margin-bottom:10px;}',
        '.zq-sec{background:#fff;border:1px solid #e2ded7;border-radius:10px;margin-bottom:12px;overflow:hidden;}',
        '.zq-sec:last-child{margin-bottom:0;}',
        '.zq-sec-h{display:flex;align-items:center;gap:9px;font-size:10px;font-weight:700;text-transform:uppercase;',
        '  letter-spacing:.10em;padding:8px 14px;background:#f5f4f1;border-bottom:1px solid #e2ded7;color:#6d7280;}',
        '.zq-sec-b{padding:12px 14px;}',
        '.zq-wx-grid{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-start;}',
        '.zq-wx-grid .zq-sec{margin-bottom:0;}',
        '.zq-wx-grid .zq-sec.zq-sec-set{flex:3 1 340px;}',
        '.zq-wx-grid .zq-sec.zq-sec-hist{flex:2 1 260px;}',

        /* item board (inside an expanded card) */
        '.zq-cols{display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap;padding:12px 14px 14px;}',
        '.zq-col{flex:1 1 150px;min-width:150px;}',
        '.zq-col-h{display:flex;align-items:center;gap:7px;font-size:10px;font-weight:700;text-transform:uppercase;',
        '  letter-spacing:.09em;padding-bottom:7px;margin-bottom:10px;border-bottom:2px solid;}',
        '.zq-col-h .zq-count{background:#f4f3f0;}',
        '.zq-item{background:#fbfaf8;border:1px solid #e2ded7;border-left:3px solid;border-radius:8px;',
        '  padding:9px 11px;margin-bottom:8px;box-shadow:0 1px 2px rgba(60,55,45,.05);}',
        '.zq-item-t{font-size:11.5px;font-weight:600;color:#2f3440;line-height:1.4;}',
        '.zq-item-t .zq-no{color:#9aa0aa;font-size:10px;font-weight:600;margin-right:5px;}',
        '.zq-flags{display:flex;flex-wrap:wrap;gap:4px;margin-top:5px;}',
        '.zq-flag{font-size:9px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#6d7280;',
        '  background:#eeece8;border:1px solid #ddd9d2;border-radius:4px;padding:1px 5px;}',
        '.zq-meta{font-size:10px;color:#8a8f9b;margin-top:5px;line-height:1.6;}',
        '.zq-meta .zq-mono{font-family:ui-monospace,Menlo,Consolas,monospace;color:#a5a9b2;}',
        '.zq-meta .zq-err{color:#c0392b;}',
        '.zq-item-f{margin-top:5px;font-size:10px;}',
        '.zq-del{color:#c0392b;text-decoration:none;opacity:.7;}',
        '.zq-del:hover{opacity:1;text-decoration:underline;}',
        '.zq-empty{color:#b0b4bc;font-size:11px;font-style:italic;padding:9px 2px;border:1px dashed #ddd9d2;',
        '  border-radius:8px;text-align:center;}',

        /* settings form */
        '.zq-fields{display:flex;flex-wrap:wrap;gap:10px 16px;}',
        '.zq-field{flex:1 1 170px;min-width:150px;}',
        '.zq-field > label{display:block;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#6d7280;margin-bottom:4px;}',
        '.zq-field-bool{display:flex;align-items:flex-start;padding-top:19px;}',
        '.zq-check{display:flex;align-items:center;gap:8px;font-size:11.5px;font-weight:600;color:#2f3440;cursor:pointer;line-height:1.3;}',
        '.zq-check input{margin:0;width:15px;height:15px;}',
        '.zq-input{width:100%;box-sizing:border-box;font-size:12px;color:#2f3440;background:#fff;border:1px solid #c9c5bd;',
        '  border-radius:7px;padding:5px 8px;font-family:inherit;}',
        '.zq-input:focus{outline:2px solid #7a8bb3;outline-offset:1px;}',
        '.zq-help{font-size:10px;color:#9aa0aa;margin-top:3px;line-height:1.4;}',
        '.zq-saverow{display:flex;align-items:center;gap:10px;margin-top:12px;padding-top:10px;border-top:1px solid #eeece8;}',
        '.zq-savemsg{font-size:11px;color:#9aa0aa;}',
        '.zq-savemsg.ok{color:#2e8b57;font-weight:600;}',
        '.zq-savemsg.bad{color:#c0392b;font-weight:600;}',
        '.zq-savemsg.pend{color:#b5761f;}',

        /* ── side panel: calendar / production overview ── */
        '.zq-pan{background:#f5f4f1;border:1px solid #e2ded7;border-radius:12px;overflow:hidden;position:relative;}',
        /* bottom-right corner grip: drag = size the panel, double-click = back to the layout */
        '.zq-grip{position:absolute;right:0;bottom:0;width:20px;height:20px;cursor:nwse-resize;z-index:4;',
        '  background:linear-gradient(135deg,transparent 0 44%,#c2bdb4 44% 53%,transparent 53% 66%,',
        '  #c2bdb4 66% 75%,transparent 75%);}',
        '.zq-grip:hover{background:linear-gradient(135deg,transparent 0 44%,#6d7280 44% 53%,transparent 53% 66%,',
        '  #6d7280 66% 75%,transparent 75%);}',
        'body.zq-resizing{cursor:nwse-resize;user-select:none;}',
        '.zq-pan-h{display:flex;align-items:center;gap:8px;padding:9px 11px;background:#efedE8;',
        '  border-bottom:1px solid #e2ded7;flex-wrap:wrap;}',
        '.zq-pan-t{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.10em;color:#4a5060;}',
        '.zq-pan-sub{font-size:10.5px;color:#8a8f9b;margin-left:2px;}',
        '.zq-pan-b{padding:11px;box-sizing:border-box;overscroll-behavior:contain;'
        + 'scrollbar-width:thin;scrollbar-color:#c3bfb7 transparent;}',
        '.zq-pan-b::-webkit-scrollbar{width:10px;height:10px;}',
        '.zq-pan-b::-webkit-scrollbar-thumb{background:#c3bfb7;border-radius:999px;border:3px solid #f6f4f0;}',
        '.zq-pan-b::-webkit-scrollbar-track{background:transparent;}',
        '.zq-vbtn{width:30px;height:26px;border-radius:7px;border:1px solid #c9c5bd;font-size:13px;line-height:1;',
        '  background:linear-gradient(180deg,#fdfdfd,#e9e7e2);color:#3a4050;cursor:pointer;padding:0;',
        '  box-shadow:0 1px 2px rgba(0,0,0,.06);}',
        '.zq-vbtn:hover{background:linear-gradient(180deg,#fff,#f2f0ec);}',
        '.zq-vbtn.on{background:linear-gradient(180deg,#e8ecf7,#c3cee4);border-color:#9aa7c4;color:#25304a;}',
        '.zq-vbtn:disabled{opacity:.35;cursor:not-allowed;}',
        '.zq-seg{display:inline-flex;gap:0;border:1px solid #c9c5bd;border-radius:7px;overflow:hidden;}',
        '.zq-seg button{border:0;border-left:1px solid #d6d2ca;background:linear-gradient(180deg,#fdfdfd,#e9e7e2);',
        '  color:#3a4050;font-size:10.5px;font-weight:600;padding:5px 9px;cursor:pointer;font-family:inherit;}',
        '.zq-seg button:first-child{border-left:0;}',
        '.zq-seg button.on{background:linear-gradient(180deg,#e8ecf7,#c3cee4);color:#25304a;}',
        '.zq-pan-sp{margin-left:auto;}',

        /* calendar grid */
        '.zq-cal{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:6px;}',
        '.zq-dow{font-size:9px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:#9aa0aa;',
        '  text-align:center;padding-bottom:2px;}',
        '.zq-day{background:#fff;border:1px solid #e2ded7;border-radius:9px;padding:6px 7px 7px;min-height:96px;',
        '  cursor:pointer;display:flex;flex-direction:column;gap:4px;box-shadow:0 1px 2px rgba(60,55,45,.05);}',
        '.zq-day:hover{border-color:#b9b3a9;}',
        '.zq-day.wknd{background:#faf9f6;}',
        '.zq-day.past{background:#f7f6f3;}',
        '.zq-day.today{border-color:#1f8ea8;box-shadow:0 0 0 2px #1f8ea826;}',
        '.zq-day.sel{border-color:#4a5060;box-shadow:0 0 0 2px #4a506022;}',
        '.zq-day-h{display:flex;align-items:baseline;gap:5px;}',
        '.zq-day-n{font-size:13px;font-weight:700;color:#2f3440;line-height:1;}',
        '.zq-day-d{font-size:9.5px;color:#9aa0aa;text-transform:uppercase;letter-spacing:.06em;}',
        '.zq-day-x{margin-left:auto;font-size:9px;font-weight:700;color:#6d7280;}',
        '.zq-prow{display:flex;align-items:center;gap:4px;font-size:10px;color:#4a5060;line-height:1.35;}',
        '.zq-pdot{width:7px;height:7px;border-radius:50%;flex:0 0 7px;}',
        '.zq-prow b{font-weight:700;}',
        '.zq-prow.ghost{color:#a8adb6;}',
        '.zq-prow.ghost .zq-pdot{background:transparent!important;border:1px dashed #b7bcc4;}',
        '.zq-day-f{margin-top:auto;display:flex;flex-wrap:wrap;gap:4px;font-size:9px;color:#8a8f9b;padding-top:3px;',
        '  border-top:1px dashed #eceae5;}',
        '.zq-tag{border-radius:4px;padding:1px 4px;background:#f2f1ed;border:1px solid #e4e1db;white-space:nowrap;}',
        '.zq-tag.good{color:#2e8b57;border-color:#2e8b5733;background:#2e8b570d;}',
        '.zq-tag.bad{color:#c0392b;border-color:#c0392b33;background:#c0392b0d;}',
        '.zq-tag.warm{color:#b5761f;border-color:#b5761f33;background:#b5761f0d;}',
        '.zq-tag.cool{color:#1f8ea8;border-color:#1f8ea833;background:#1f8ea80d;}',
        '.zq-day-e{font-size:9px;color:#b0b4bc;font-style:italic;}',

        /* production table */
        '.zq-sum{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:10px;}',
        '.zq-sum-c{flex:1 1 140px;min-width:132px;background:#fff;border:1px solid #e2ded7;border-left:3px solid;',
        '  border-radius:9px;padding:7px 9px;}',
        '.zq-sum-n{display:flex;align-items:center;gap:6px;font-size:11px;font-weight:700;color:#2f3440;}',
        '.zq-sum-n .zq-mini{margin-left:auto;font-size:8.5px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;',
        '  color:#9aa0aa;border:1px solid #e0ddd6;border-radius:4px;padding:0 4px;}',
        '.zq-sum-v{font-size:16px;font-weight:700;color:#2f3440;margin-top:3px;line-height:1.1;}',
        '.zq-sum-v small{font-size:10px;font-weight:600;color:#8a8f9b;margin-left:3px;}',
        '.zq-sum-l{font-size:9.5px;color:#8a8f9b;margin-top:2px;line-height:1.4;}',
        '.zq-tbl{width:100%;border-collapse:collapse;font-size:10.5px;background:#fff;border:1px solid #e2ded7;',
        '  border-radius:9px;overflow:hidden;}',
        '.zq-tbl th{font-size:9px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:#6d7280;',
        '  background:#f5f4f1;padding:5px 7px;text-align:right;border-bottom:1px solid #e2ded7;white-space:nowrap;}',
        '.zq-tbl th:first-child,.zq-tbl td:first-child{text-align:left;}',
        '.zq-tbl td{padding:4px 7px;text-align:right;border-top:1px solid #f1efeb;color:#4a5060;white-space:nowrap;}',
        '.zq-tbl tr.fut td{color:#9aa0aa;font-style:italic;}',
        '.zq-tbl tr.today td{background:#1f8ea80a;font-weight:600;}',
        '.zq-tbl tr.sel td{background:#4a50600d;}',
        '.zq-tbl tbody tr{cursor:pointer;}',
        '.zq-tbl tbody tr:hover td{background:#faf9f6;}',
        '.zq-tbl tfoot td{border-top:2px solid #e2ded7;font-weight:700;color:#2f3440;background:#f7f6f3;}',
        '.zq-tbl .dim{color:#a8adb6;}',
        '.zq-up{color:#c0392b;} .zq-dn{color:#2e8b57;}',

        /* day detail + notes */
        '.zq-det{margin-top:10px;background:#fff;border:1px solid #e2ded7;border-radius:9px;padding:9px 11px;}',
        '.zq-det-h{display:flex;align-items:center;gap:8px;font-size:11px;font-weight:700;color:#2f3440;margin-bottom:6px;}',
        '.zq-det-h .zq-close{margin-left:auto;color:#9aa0aa;text-decoration:none;font-size:12px;}',
        '.zq-det-g{display:flex;flex-wrap:wrap;gap:8px;}',
        '.zq-det-w{flex:1 1 170px;min-width:160px;border-left:3px solid;padding-left:8px;}',
        '.zq-det-w b{font-size:10.5px;color:#2f3440;}',
        '.zq-det-w div{font-size:10px;color:#6d7280;line-height:1.5;}',
        '.zq-det-w .zq-titles{color:#9aa0aa;font-style:italic;}',
        '.zq-notes{margin-top:9px;font-size:9.5px;color:#9aa0aa;line-height:1.5;}',
        '.zq-notes summary{cursor:pointer;color:#8a8f9b;font-weight:600;}',
        '.zq-notes ul{margin:5px 0 0;padding-left:15px;}',
        '.zq-notes li{margin-bottom:3px;}',
        '.zq-rules{margin:0 0 10px;padding:8px 10px;background:#f7f6f3;border:1px solid #eeece8;border-radius:7px;}',
        '.zq-rules b{display:block;font-size:9px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;',
        '  color:#8a8f9b;margin-bottom:4px;}',
        '.zq-rules ul{margin:0;padding-left:15px;}',
        '.zq-rules li{font-size:10.5px;color:#6d7280;line-height:1.5;}',

        /* ── card dialog: everything a card used to print on its face ── */
        '.zq-modal{position:fixed;inset:0;z-index:9400;background:rgba(28,24,20,.44);display:flex;',
        '  align-items:flex-start;justify-content:center;padding:26px 18px;}',
        '.zq-modal-w{background:#fbfaf8;border:1px solid #cfcac2;border-left:5px solid #7a8290;border-radius:12px;',
        '  width:100%;max-width:1180px;max-height:calc(88vh / var(--ui-zoom,1));display:flex;flex-direction:column;',
        '  overflow:hidden;box-shadow:0 14px 44px rgba(30,26,20,.30);}',
        '.zq-modal-h{display:flex;align-items:center;gap:9px;padding:11px 13px;background:#f3f1ed;',
        '  border-bottom:1px solid #e2ded7;flex-wrap:wrap;}',
        '.zq-modal-h .zq-name{flex:0 1 auto;font-size:14px;}',
        '.zq-modal-h .zq-acts{margin:0 0 0 auto;}',
        '.zq-mclose{width:28px;height:26px;border-radius:7px;border:1px solid #c9c5bd;color:#3a4050;font-size:12px;',
        '  background:linear-gradient(180deg,#fdfdfd,#e9e7e2);cursor:pointer;padding:0;margin-left:4px;}',
        '.zq-mclose:hover{background:linear-gradient(180deg,#fff,#f2f0ec);}',
        '.zq-modal-b{padding:12px 14px 14px;overflow:auto;}',
        '.zq-modal-b .zq-wx{border-top:0;background:transparent;padding:0;}',

        /* history */
        '.zq-hist{list-style:none;margin:0;padding:0;}',
        '.zq-hist li{display:flex;gap:10px;font-size:11px;padding:5px 0;border-top:1px solid #f1efeb;line-height:1.45;}',
        '.zq-hist li:first-child{border-top:0;padding-top:0;}',
        '.zq-hist .zq-hts{color:#a5a9b2;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:10px;white-space:nowrap;padding-top:1px;}',
        '.zq-hist .zq-hev{font-weight:600;color:#2f3440;}',
        '.zq-hist .zq-hdt{color:#7b8090;}'
    ].join('');

    // ── small builders ───────────────────────────────────────────────────────
    function chip(label, n, color, strong) {
        if (!n) return '';
        return '<span class="zq-chip"' + (color ? ' style="color:' + color + ';border-color:' + color + '44;"' : '') + '>'
             + (strong ? '<b>' + esc(n) + '</b>' : esc(n)) + ' ' + esc(label) + '</span>';
    }

    function chipsFor(counts) {
        counts = counts || {};
        var total = 0;
        Object.keys(counts).forEach(function (k) { total += Number(counts[k]) || 0; });
        var out = chip('generating',    counts.in_production, COL_COLORS.in_production, true)
                + chip('queued',        counts.scheduled,     null, false)
                + chip('done',          counts.done,          COL_COLORS.done, false)
                + chip('failed',        counts.failed,        COL_COLORS.failed, false)
                + chip('awaiting LoRA', counts.blocked,       COL_COLORS.blocked, false);
        if (!out) out = '<span class="zq-chip idle">' + (total ? 'nothing running' : 'no batch today') + '</span>';
        return out;
    }

    function meter(label, pct, resetsAt) {
        var has = pct != null && pct !== '' && !isNaN(Number(pct));
        var p = has ? Math.max(0, Math.min(100, Number(pct))) : 0;
        var color = p >= 90 ? '#c0392b' : (p >= 70 ? '#b5761f' : '#2e8b57');
        return '<div class="zq-meter" title="' + esc(label) + ' quota window">'
             + '<div class="zq-meter-l"><span>' + esc(label) + '</span><b style="color:' + color + ';">' + (has ? Math.round(p) + '%' : '—') + '</b></div>'
             + '<div class="zq-bar"><i style="width:' + p + '%;background:' + color + ';"></i></div>'
             + '<div class="zq-meter-r">' + (resetsAt ? 'resets ' + esc(fmtTs(resetsAt)) : '&nbsp;') + '</div>'
             + '</div>';
    }

    function quotaStrip(q) {
        q = q || {};
        var hold = q.hold
            ? '<span class="zq-hold">Quota hold' + (q.hold_reason ? ' — <span>' + esc(q.hold_reason) + '</span>' : '') + '</span>'
            : '';
        return '<div class="zq-quota">'
             + meter('5-hour', q.five_hour_pct, q.five_hour_resets_at)
             + meter('7-day',  q.seven_day_pct, q.seven_day_resets_at)
             + hold
             + '</div>';
    }

    function flagChip(f) { return '<span class="zq-flag">' + esc(f) + '</span>'; }

    /** One card in a mini status column of an expanded workflow. */
    function itemCard(wf, e) {
        var status = e.status || 'scheduled';
        var c = COL_COLORS[status] || COL_COLORS.scheduled;
        var meta = '';
        (Array.isArray(e.lines) ? e.lines : []).forEach(function (l) { meta += esc(l) + '<br>'; });
        if (e.error)       meta += '<span class="zq-err">' + esc(e.error) + '</span><br>';
        if (e.pipeline_id) meta += '<span class="zq-mono">' + esc(String(e.pipeline_id).slice(0, 8)) + '…</span>';
        var flags = (Array.isArray(e.flags) ? e.flags : []).map(flagChip).join('');
        var canDelete = (wf.item_actions || []).indexOf('delete') >= 0 && (status === 'ready' || status === 'failed');
        var del = canDelete
            ? '<a href="#" class="zq-del" data-wf="' + esc(wf.id) + '" data-item="' + esc(e.id) + '" title="Remove this entry from the bank">✕ delete</a>'
            : '';
        return '<div class="zq-item" style="border-left-color:' + c + ';">'
             + '<div class="zq-item-t">' + (e.no ? '<span class="zq-no">' + esc(e.no) + '</span>' : '') + esc(e.title || '—') + '</div>'
             + (flags ? '<div class="zq-flags">' + flags + '</div>' : '')
             + (meta ? '<div class="zq-meta">' + meta + '</div>' : '')
             + (del ? '<div class="zq-item-f">' + del + '</div>' : '')
             + '</div>';
    }

    function itemColumn(wf, key) {
        var color = COL_COLORS[key] || COL_COLORS.scheduled;
        var label = (wf.column_labels || {})[key] || key;
        var rows = (Array.isArray(wf.items) ? wf.items : []).filter(function (e) { return (e.status || 'scheduled') === key; });
        var cards = rows.map(function (e) { return itemCard(wf, e); }).join('') || '<div class="zq-empty">empty</div>';
        return '<div class="zq-col">'
             + '<div class="zq-col-h" style="color:' + color + ';border-bottom-color:' + color + ';">'
             +   esc(label) + '<span class="zq-count">' + rows.length + '</span>'
             + '</div>' + cards + '</div>';
    }

    function settingField(wf, s) {
        var key = esc(s.key);
        var id = 'zq-set-' + esc(wf.id) + '-' + key;
        var orig = esc(JSON.stringify(s.value === undefined ? null : s.value));
        var common = ' data-key="' + key + '" data-type="' + esc(s.type || 'text') + '" data-orig="' + orig + '"';
        var help = s.help ? '<div class="zq-help">' + esc(s.help) + '</div>' : '';
        var ctl;
        if (s.type === 'bool') {
            ctl = '<label class="zq-check"><input type="checkbox" id="' + id + '"' + common + (s.value ? ' checked' : '') + '>'
                + '<span>' + esc(s.label || s.key) + '</span></label>';
            return '<div class="zq-field zq-field-bool"><div>' + ctl + help + '</div></div>';
        }
        if (s.type === 'select') {
            ctl = '<select class="zq-input" id="' + id + '"' + common + '>'
                + (Array.isArray(s.options) ? s.options : []).map(function (o) {
                      var v = Array.isArray(o) ? o[0] : o;
                      var l = Array.isArray(o) ? (o[1] != null ? o[1] : o[0]) : o;
                      return '<option value="' + esc(v) + '"' + (String(v) === String(s.value) ? ' selected' : '') + '>' + esc(l) + '</option>';
                  }).join('')
                + '</select>';
        } else {
            var attrs = '';
            if (s.min  != null) attrs += ' min="'  + esc(s.min)  + '"';
            if (s.max  != null) attrs += ' max="'  + esc(s.max)  + '"';
            if (s.step != null) attrs += ' step="' + esc(s.step) + '"';
            ctl = '<input class="zq-input" type="' + (s.type === 'number' ? 'number' : 'text') + '" id="' + id + '"'
                + ' value="' + esc(s.value == null ? '' : s.value) + '"' + attrs + common + '>';
        }
        return '<div class="zq-field"><label for="' + id + '">' + esc(s.label || s.key) + '</label>' + ctl + help + '</div>';
    }

    function fieldValue(el) {
        var t = el.getAttribute('data-type');
        if (t === 'bool') return !!el.checked;
        if (t === 'number') {
            if (el.value === '') return null;
            var n = Number(el.value);
            return isNaN(n) ? null : n;
        }
        return el.value;
    }

    function settingsPanel(wf) {
        var list = Array.isArray(wf.settings) ? wf.settings : [];
        var msg = _saveMsg[wf.id] || null;
        var body = list.length
            ? '<div class="zq-fields">' + list.map(function (s) { return settingField(wf, s); }).join('') + '</div>'
            : '<div class="zq-empty">no settings</div>';
        var row = list.length
            ? '<div class="zq-saverow">'
              + '<button type="button" class="zq-btn zq-save" data-wf="' + esc(wf.id) + '">Save settings</button>'
              + '<span class="zq-savemsg' + (msg ? (msg.ok ? ' ok' : ' bad') : '') + '">' + (msg ? esc(msg.text) : '') + '</span>'
              + '</div>'
            : '';
        // The start gates are the box's rules, not a setting — they are stated, never offered.
        var rules = Array.isArray(wf.rules) && wf.rules.length
            ? '<div class="zq-rules"><b>Start rules (fixed)</b><ul>'
              + wf.rules.map(function (r) { return '<li>' + esc(r) + '</li>'; }).join('') + '</ul></div>'
            : '';
        return '<div class="zq-settings zq-sec-b" data-wf="' + esc(wf.id) + '">' + rules + body + row + '</div>';
    }

    function historyList(wf) {
        // The server sends the audit tail newest first (contract); string-sorting
        // ISO stamps with mixed offsets would misorder them, so keep its order.
        var rows = (Array.isArray(wf.history) ? wf.history : []).slice(0, 8);
        if (!rows.length) return '<div class="zq-sec-b"><div class="zq-empty">no recent events</div></div>';
        return '<div class="zq-sec-b"><ul class="zq-hist">' + rows.map(function (h) {
            return '<li><span class="zq-hts">' + esc(fmtTs(h.ts)) + '</span>'
                 + '<span><span class="zq-hev">' + esc(h.event) + '</span>'
                 + (h.detail ? ' <span class="zq-hdt">' + esc(h.detail) + '</span>' : '') + '</span></li>';
        }).join('') + '</ul></div>';
    }

    function targetRow(t) {
        var pct = Math.max(0, Math.min(100, Number(t.pct) || 0));
        var cur = t.current && typeof t.current === 'object' ? t.current : null;
        var num = (t.ready != null && t.target != null) ? esc(t.ready) + ' / ' + esc(t.target) : Math.round(pct) + '%';
        return '<div class="zq-tgt">'
             + '<div class="zq-tgt-h"><span>' + esc(t.label || t.id) + '</span><span>' + num + '</span></div>'
             + '<div class="zq-bar"><i style="width:' + pct + '%;"></i></div>'
             + (t.note ? '<div class="zq-tgt-note">' + esc(t.note) + '</div>' : '')
             + (cur ? '<div class="zq-tgt-cur">⟳ ' + esc(cur.topic || cur.pipeline_id || 'building')
                    + (cur.stage ? ' <span class="zq-muted">— ' + esc(cur.stage) + '</span>' : '') + '</div>' : '')
             + (t.info ? '<div class="zq-tgt-info">' + esc(t.info) + '</div>' : '')
             + '</div>';
    }

    /**
     * The body of a card's dialog. A card face carries a name, a state and its buttons and
     * nothing else, so everything it used to print — what the workflow does, its chips, the
     * state note, the bank targets — is the first thing in here, above items and settings.
     */
    function expandedBody(wf) {
        var cols = (Array.isArray(wf.columns) ? wf.columns : []).map(function (k) { return itemColumn(wf, k); }).join('');
        var nItems = Array.isArray(wf.items) ? wf.items.length : 0;
        var targets = (Array.isArray(wf.targets) ? wf.targets : []).map(targetRow).join('');
        return '<div class="zq-wx">'
             + (wf.desc ? '<div class="zq-desc" style="margin-top:0;">' + esc(wf.desc) + '</div>' : '')
             + '<div class="zq-chips">' + chipsFor(wf.counts) + '</div>'
             + (wf.state_note ? '<div class="zq-snote">' + esc(wf.state_note) + '</div>' : '')
             + (targets ? '<div class="zq-tgts" style="margin-bottom:12px;">' + targets + '</div>' : '')
             + (wf.batch_note ? '<div class="zq-bnote" style="margin-top:10px;">' + esc(wf.batch_note) + '</div>' : '')
             + '<div class="zq-sec"><div class="zq-sec-h">Items<span class="zq-count">' + nItems + '</span></div>'
             +   (cols ? '<div class="zq-cols">' + cols + '</div>' : '<div class="zq-sec-b"><div class="zq-empty">no item columns</div></div>')
             + '</div>'
             + '<div class="zq-wx-grid">'
             +   '<div class="zq-sec zq-sec-set"><div class="zq-sec-h">Settings</div>' + settingsPanel(wf) + '</div>'
             +   '<div class="zq-sec zq-sec-hist"><div class="zq-sec-h">Recent activity</div>' + historyList(wf) + '</div>'
             + '</div>'
             + '</div>';
    }

    /** ▶ ⏸ ⏹ — the same three buttons on the card face and in its dialog header. */
    function actionButtons(wf) {
        var actions = Array.isArray(wf.actions) ? wf.actions : [];
        var pend    = !!_pending[wf.id];
        var idAttr  = esc(wf.id);
        function ib(a, glyph, title) {
            var on = actions.indexOf(a) >= 0 && !pend;
            return '<button type="button" class="zq-ib zq-act ' + a + '" data-wf="' + idAttr + '" data-action="' + a + '"'
                 + ' title="' + title + (on ? '' : ' (not available now)') + '"' + (on ? '' : ' disabled') + '>' + glyph + '</button>';
        }
        return ib('play', '▶', 'Play') + ib('pause', '⏸', 'Pause') + ib('abort', '⏹', 'Abort')
             + (pend ? '<span class="zq-muted">working…</span>' : '');
    }

    /** The open card's dialog: its name, its state, its buttons, then the detail body. */
    function cardDialog() {
        var wf = _dialog ? findWf(_dialog) : null;
        if (!wf) return '';
        var accent = colorOk(wf.accent);
        var st     = STATE_BY[stateOf(wf)];
        var err    = _errors[wf.id] ? '<div class="zq-cerr" style="margin:0 0 10px;">' + esc(_errors[wf.id]) + '</div>' : '';
        return '<div class="zq-modal" data-wf="' + esc(wf.id) + '">'
             + '<div class="zq-modal-w" style="border-left-color:' + accent + ';">'
             +   '<div class="zq-modal-h">'
             +     '<span class="zq-led' + (wf.busy ? ' zq-pulse' : '') + '" style="background:'
             +       (wf.enabled ? accent : '#c9c5bd') + ';"></span>'
             +     '<span class="zq-name">' + esc(wf.name || wf.id)
             +       '<span class="zq-pill" style="background:' + st.color + '18;color:' + st.color
             +       ';border-color:' + st.color + '4d;">' + st.label + '</span></span>'
             +     '<div class="zq-acts" style="margin-top:0;">' + actionButtons(wf) + '</div>'
             +     '<button type="button" class="zq-mclose" title="Close (Esc)">✕</button>'
             +   '</div>'
             +   '<div class="zq-modal-b">' + err + expandedBody(wf) + '</div>'
             + '</div></div>';
    }

    /** One workflow card: a name, its state and its buttons. Everything else is a click away. */
    function wfCard(wf) {
        var accent = colorOk(wf.accent);
        var st     = STATE_BY[stateOf(wf)];
        var idAttr = esc(wf.id);
        var led  = '<span class="zq-led' + (wf.busy ? ' zq-pulse' : '') + '" style="background:'
                 + (wf.enabled ? accent : '#c9c5bd') + ';"></span>';
        var pill = '<span class="zq-pill" style="background:' + st.color + '18;color:' + st.color
                 + ';border-color:' + st.color + '4d;">' + st.label + '</span>';
        var err  = _errors[wf.id] ? '<div class="zq-cerr">' + esc(_errors[wf.id]) + '</div>' : '';

        return '<div class="zq-wcard" data-wf="' + idAttr + '" style="border-left-color:' + accent + ';">'
             + '<div class="zq-wbody" data-wf="' + idAttr + '" title="Open the details and settings of this workflow">'
             +   '<div class="zq-wtop">' + led + '<span class="zq-name">' + esc(wf.name || wf.id) + pill + '</span></div>'
             +   '<div class="zq-acts">' + actionButtons(wf) + '<span class="zq-more">details ▸</span></div>'
             +   err
             + '</div></div>';
    }

    /** All the cards, one under the other: the state is on the pill, not in a column. */
    function workflowStrip(wfs) {
        return '<div class="zq-strip-h">Workflows<span class="zq-count">' + wfs.length + '</span></div>'
             + '<div class="zq-strip">'
             + (wfs.map(wfCard).join('') || '<div class="zq-empty">no workflows</div>')
             + '</div>';
    }

    // ── side panel: calendar + production overview ───────────────────────────
    // Everything below only FORMATS what /api/approval_queue/calendar sent. No number is
    // derived here, so the table, the grid and the day detail cannot disagree with each other
    // or with production_calendar.py.

    function fmtH(h) {
        if (h == null || h === '') return '—';
        var v = Number(h);
        if (isNaN(v)) return '—';
        if (v === 0) return '0';
        if (v < 1) return Math.round(v * 60) + ' min';
        return (v < 10 ? v.toFixed(1) : Math.round(v)) + ' h';
    }

    function fmtTok(n) {
        var v = Number(n || 0);
        if (!v) return '0';
        if (v >= 1e6) return (v / 1e6).toFixed(v >= 1e7 ? 0 : 1) + ' M';
        if (v >= 1e3) return Math.round(v / 1e3) + ' k';
        return String(v);
    }

    function fmtUsd(v) {
        if (v == null) return '—';
        var n = Number(v);
        if (isNaN(n)) return '—';
        if (n === 0) return '$0';
        return '$' + (n < 10 ? n.toFixed(2) : Math.round(n));
    }

    function fmtPct(v) { return (v == null || v === '' || isNaN(Number(v))) ? '—' : Math.round(Number(v)) + '%'; }

    /** Signed delta against the estimate: over the estimate is red, under it green. */
    function deltaTag(pct) {
        if (pct == null || pct === '' || isNaN(Number(pct))) return '';
        var v = Math.round(Number(pct));
        return '<span class="' + (v > 0 ? 'zq-up' : 'zq-dn') + '">' + (v > 0 ? '+' : '') + v + '%</span>';
    }

    function shiftDate(iso, n) {
        var p = String(iso || '').split('-');
        var d = new Date(Date.UTC(+p[0], (+p[1] || 1) - 1, +p[2] || 1));
        d.setUTCDate(d.getUTCDate() + n);
        return d.toISOString().slice(0, 10);
    }

    function calMeta(id) {
        var list = (_cal && _cal.summary) || [];
        for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
        return {id: id, name: id, accent: '#7a8290', unit: 'item'};
    }

    function unitWord(m, n) {
        var u = m.unit || 'item';
        return n === 1 ? u : (u === 'brain run' ? 'brain runs' : u + 's');
    }

    var JUMPS = [
        ['0', 'Today'], ['-7', '1 week back'], ['-28', '4 weeks back'], ['-91', '3 months back'],
        ['-182', '6 months back'], ['-365', '1 year back'], ['7', 'Next week'], ['21', 'In 3 weeks']
    ];

    function calHeader() {
        var r = (_cal && _cal.range) || {};
        var label = r.start ? esc(r.start) + ' → ' + esc(r.end) : '…';
        var isCal = _calView === 'calendar';
        var seg = '<span class="zq-seg">'
                + [7, 14, 28].map(function (d) {
                      return '<button type="button" class="zq-cwin' + (d === _calDays ? ' on' : '') + '" data-days="' + d + '">' + d + ' d</button>';
                  }).join('')
                + '</span>';
        var jump = '<select class="zq-vbtn zq-jump" style="width:auto;padding:0 5px;font-size:10.5px;" title="Jump the window">'
                 + '<option value="">Jump…</option>'
                 + JUMPS.map(function (j) { return '<option value="' + j[0] + '">' + esc(j[1]) + '</option>'; }).join('')
                 + '</select>';
        return '<div class="zq-pan-h">'
             + '<button type="button" class="zq-vbtn zq-cview" title="' + (isCal ? 'Switch to the production overview' : 'Switch back to the calendar') + '">'
             +   (isCal ? '📊' : '📅') + '</button>'
             + '<span class="zq-pan-t">' + (isCal ? 'Calendar' : 'Production') + '</span>'
             + '<span class="zq-pan-sub">' + label + (_calBusy ? ' · loading…' : '') + '</span>'
             + '<span class="zq-pan-sp"></span>'
             + seg
             + '<button type="button" class="zq-vbtn zq-cnav" data-dir="-1" title="Earlier window"' + (r.can_back === false ? ' disabled' : '') + '>‹</button>'
             + '<button type="button" class="zq-vbtn zq-ctoday" title="Back to today">•</button>'
             + '<button type="button" class="zq-vbtn zq-cnav" data-dir="1" title="Later window"' + (r.can_fwd === false ? ' disabled' : '') + '>›</button>'
             + jump
             + '<button type="button" class="zq-vbtn zq-cfold" title="Fold the panel away">✕</button>'
             + '</div>';
    }

    /** One day cell: what is planned, and — once the day has happened — what came of it. */
    function dayCell(c) {
        var cls = 'zq-day' + (c.weekend ? ' wknd' : '') + (c.is_past ? ' past' : '')
                + (c.is_today ? ' today' : '') + (c.date === _calSel ? ' sel' : '');
        var rows = '', order = ['documentary', 'storyteller', 'melody', 'preempt'];
        order.forEach(function (id) {
            var w = (c.workflows || {})[id];
            if (!w) return;
            var n = (w.planned || 0) + (w.potential || 0);
            if (!n) return;
            var m = calMeta(id);
            rows += '<div class="zq-prow' + (w.active ? '' : ' ghost') + '" title="' + esc(m.name + ' — ' + (w.plan_why || '')
                  + (w.active ? '' : ' (switched off: this is what the rule would queue)')
                  + (w.unit_min ? ' · ' + w.unit_min + ' min each, ' + (w.unit_basis || '') : '')) + '">'
                  + '<span class="zq-pdot" style="background:' + colorOk(m.accent) + ';"></span>'
                  + '<b>' + n + '</b> ' + esc(unitWord(m, n)) + '</div>';
        });
        if (!rows) rows = '<div class="zq-day-e">nothing scheduled</div>';
        var tags = '';
        if (c.hours_potential && !c.planned_total) {
            // Nothing is switched on for this day: what the rule WOULD cost, as a ghost. Over
            // 100 % means the full schedule does not fit in a day — say that, don't just print it.
            var over = (c.system_pct_potential || 0) > 100;
            tags += '<span class="zq-tag ' + (over ? 'warm' : 'dim') + '" title="If these workflows were switched on">'
                  + 'would take ≈ ' + fmtH(c.hours_potential) + ' · '
                  + (over ? 'more than a day (' + fmtPct(c.system_pct_potential) + ')' : fmtPct(c.system_pct_potential) + ' of the day')
                  + '</span>';
        }
        if (c.is_future) {
            if (c.hours_expected) tags += '<span class="zq-tag cool">≈ ' + fmtH(c.hours_expected) + '</span>';
            if (c.system_pct_expected) tags += '<span class="zq-tag' + (c.system_pct_expected > 100 ? ' warm' : '') + '">'
                + (c.system_pct_expected > 100 ? 'more than a day (' + fmtPct(c.system_pct_expected) + ')'
                                               : fmtPct(c.system_pct_expected) + ' of the day') + '</span>';
            if (c.tokens_expected) tags += '<span class="zq-tag">≈ ' + fmtTok(c.tokens_expected) + ' tok</span>';
        } else {
            if (c.produced_total) tags += '<span class="zq-tag good">✓ ' + c.produced_total + '</span>';
            if (c.failed_total)   tags += '<span class="zq-tag bad">✗ ' + c.failed_total + '</span>';
            if (c.hours)          tags += '<span class="zq-tag">' + fmtH(c.hours) + ' real'
                                        + (c.hours_delta_pct != null ? ' · ' + deltaTag(c.hours_delta_pct) : '') + '</span>';
            if (c.system_pct)     tags += '<span class="zq-tag">' + fmtPct(c.system_pct) + ' of the day</span>';
            if (!c.started_total && !c.produced_total) tags += '<span class="zq-tag dim">nothing ran</span>';
        }
        var badge = c.planned_total ? c.planned_total : (c.potential_total ? '(' + c.potential_total + ')' : '');
        return '<div class="' + cls + '" data-day="' + esc(c.date) + '" title="' + esc(c.date) + '">'
             + '<div class="zq-day-h"><span class="zq-day-n">' + c.dom + '</span>'
             +   '<span class="zq-day-d">' + esc(c.dow) + (c.dom === 1 ? ' ' + esc(c.month) : '') + '</span>'
             +   '<span class="zq-day-x">' + esc(String(badge)) + '</span></div>'
             + rows
             + (tags ? '<div class="zq-day-f">' + tags + '</div>' : '')
             + '</div>';
    }

    function calGrid() {
        var days = (_cal && _cal.days_list) || [];
        if (!days.length) return '<div class="zq-empty">no days in this window</div>';
        return '<div class="zq-cal">' + days.map(dayCell).join('') + '</div>';
    }

    /** Per-workflow tiles: what the window holds and what one item costs at recent medians. */
    function prodSummary() {
        var list = (_cal && _cal.summary) || [];
        var t = (_cal && _cal.totals) || {};
        var cards = list.map(function (w) {
            // A switched-off workflow has no plan — what its rule WOULD queue is said as such.
            var planned = (w.planned || 0) + (w.potential || 0);
            var planWord = w.planned ? ' planned' : (w.potential ? ' if switched on' : ' planned');
            return '<div class="zq-sum-c" style="border-left-color:' + colorOk(w.accent) + ';">'
                 + '<div class="zq-sum-n">' + esc(w.name)
                 +   '<span class="zq-mini">' + (w.enabled ? (w.paused ? 'paused' : 'on') : 'off') + '</span></div>'
                 + '<div class="zq-sum-v">' + (w.completed || 0) + '<small>done</small>'
                 +   ' <span style="color:#9aa0aa;font-size:12px;">/ ' + planned + esc(planWord) + '</span></div>'
                 + '<div class="zq-sum-l">' + (w.started ? fmtH(w.hours) + ' real vs ' + fmtH(w.expected_hours_for_started) + ' expected'
                                                     : (w.potential_hours ? 'would take ≈ ' + fmtH(w.potential_hours) : 'nothing ran'))
                 +   (w.hours_delta_pct != null ? ' (' + deltaTag(w.hours_delta_pct) + ')' : '') + '<br>'
                 +   fmtUsd(w.cost_usd) + ' · ' + fmtTok(w.tokens) + ' tok · ' + fmtPct(w.system_pct) + ' of the box<br>'
                 +   '<span title="' + esc(w.unit_basis || '') + '">one ' + esc(w.unit || 'item') + ' ≈ '
                 +   (w.unit_min != null ? w.unit_min + ' min' : 'no timed run') + ' · ' + fmtTok(w.unit_tokens) + ' tok · '
                 +   fmtUsd(w.unit_cost_usd) + (w.success_rate != null ? ' · ' + fmtPct(w.success_rate * 100) + ' finish' : '') + '</span>'
                 + '</div></div>';
        }).join('');
        var board = '<div class="zq-sum-c" style="border-left-color:#4a5060;">'
            + '<div class="zq-sum-n">Window total<span class="zq-mini">' + (t.past_days || 0) + ' past / ' + (t.future_days || 0) + ' ahead</span></div>'
            + '<div class="zq-sum-v">' + (t.produced || 0) + '<small>done</small>'
            +   ' <span style="color:#9aa0aa;font-size:12px;">/ ' + ((t.planned || 0) + (t.potential || 0))
            +   (t.planned ? ' planned' : ' if switched on') + '</span></div>'
            + '<div class="zq-sum-l">' + fmtH(t.hours) + ' real vs ' + fmtH(t.hours_expected_started) + ' expected<br>'
            +   fmtUsd(t.cost_usd) + ' API · ' + fmtTok(t.tokens) + ' tok · ' + fmtTok(t.subscription_tokens) + ' subscription<br>'
            +   fmtPct(t.system_pct) + ' of the days measured'
            +   (t.gpu_share_pct != null ? ' · ' + fmtPct(t.gpu_share_pct) + ' of GPU-busy time' : '')
            + '</div></div>';
        return '<div class="zq-sum">' + cards + board + '</div>';
    }

    function prodTable() {
        var days = (_cal && _cal.days_list) || [];
        var t = (_cal && _cal.totals) || {};
        var head = ['Day', 'Plan', 'Start', 'Done', 'Fail', 'Exp h', 'Real h', 'Δ', 'Sys %', 'Tokens', 'API $'];
        var rows = days.map(function (c) {
            var cls = (c.is_future ? 'fut' : '') + (c.is_today ? ' today' : '') + (c.date === _calSel ? ' sel' : '');
            var plan = (c.planned_total || 0) + (c.potential_total ? ' <span class="dim">(' + c.potential_total + ')</span>' : '');
            var cells = [
                '<b>' + esc(c.dow) + '</b> ' + esc(c.date.slice(5)),
                plan,
                c.is_future ? '—' : (c.started_total || 0),
                c.is_future ? (c.workflows && Object.keys(c.workflows).length ? '<span class="dim">≈' + Math.round(Object.keys(c.workflows).reduce(function (a, k) { return a + (c.workflows[k].expected_completed || 0); }, 0)) + '</span>' : '—') : (c.produced_total || 0),
                c.is_future ? '—' : (c.failed_total || 0),
                (c.is_future ? c.hours_expected : c.hours_expected_started)
                    ? fmtH(c.is_future ? c.hours_expected : c.hours_expected_started)
                    : (c.hours_potential ? '<span class="dim">(' + fmtH(c.hours_potential) + ')</span>' : '—'),
                c.is_future ? '—' : fmtH(c.hours),
                c.is_future ? '—' : (deltaTag(c.hours_delta_pct) || '—'),
                c.is_future ? '<span class="dim">≈' + fmtPct(c.system_pct_expected || c.system_pct_potential) + '</span>' : fmtPct(c.system_pct),
                c.is_future ? '<span class="dim">≈' + fmtTok(c.tokens_expected || c.tokens_potential) + '</span>' : fmtTok(c.tokens),
                c.is_future ? '<span class="dim">≈' + fmtUsd(c.cost_expected_usd || c.cost_potential_usd) + '</span>' : fmtUsd(c.cost_usd)
            ];
            return '<tr class="' + cls + '" data-day="' + esc(c.date) + '"><td>' + cells.join('</td><td>') + '</td></tr>';
        }).join('');
        var foot = ['<b>' + (t.days || 0) + ' days</b>', (t.planned || 0) + (t.potential ? ' <span class="dim">(' + t.potential + ')</span>' : ''),
                    t.started || 0, t.produced || 0, t.failed || 0,
                    fmtH((t.hours_expected || 0) + (t.hours_expected_started || 0)), fmtH(t.hours),
                    '', fmtPct(t.system_pct), fmtTok((t.tokens || 0) + (t.expected_tokens || 0)),
                    fmtUsd((t.cost_usd || 0) + (t.expected_cost_usd || 0))];
        return '<table class="zq-tbl"><thead><tr><th>' + head.join('</th><th>') + '</th></tr></thead>'
             + '<tbody>' + rows + '</tbody>'
             + '<tfoot><tr><td>' + foot.join('</td><td>') + '</td></tr></tfoot></table>';
    }

    /** The selected day, workflow by workflow — the cell is too small for this. */
    function dayDetail() {
        if (!_calSel) return '';
        var days = (_cal && _cal.days_list) || [], c = null;
        for (var i = 0; i < days.length; i++) if (days[i].date === _calSel) c = days[i];
        if (!c) return '';
        var parts = Object.keys(c.workflows || {}).map(function (id) {
            var w = c.workflows[id], m = calMeta(id);
            var n = (w.planned || 0) + (w.potential || 0);
            var lines = '<div>' + n + ' ' + esc(unitWord(m, n)) + ' planned' + (w.active ? '' : ' <i>(workflow off)</i>')
                      + (w.plan_why ? ' — ' + esc(w.plan_why) : '') + '</div>';
            if (c.is_future) {
                lines += '<div>≈ ' + fmtH(w.expected_hours) + (w.band_hours ? ' (' + fmtH(w.band_hours[0]) + '–' + fmtH(w.band_hours[1]) + ')' : '')
                       + ' · ≈ ' + fmtTok(w.expected_tokens) + ' tok · ≈ ' + fmtUsd(w.expected_cost_usd) + '</div>'
                       + '<div>' + (w.expected_completed != null ? '≈ ' + w.expected_completed + ' finish at the recent success rate' : 'no success rate on record') + '</div>';
            } else {
                lines += '<div>' + (w.started || 0) + ' started · ' + (w.completed || 0) + ' done · ' + (w.failed || 0) + ' failed'
                       + (w.open ? ' · ' + w.open + ' open' : '') + '</div>'
                       + '<div>' + fmtH(w.hours) + ' real vs ' + fmtH(w.expected_hours_for_started) + ' expected'
                       + (w.hours_delta_pct != null ? ' (' + deltaTag(w.hours_delta_pct) + ')' : '')
                       + (w.hours_missing ? ' · ' + w.hours_missing + ' with no duration' : '') + '</div>'
                       + '<div>' + fmtTok(w.tokens) + ' tok · ' + fmtUsd(w.cost_usd) + ' · ' + fmtPct(w.busy_hours ? w.busy_hours / 24 * 100 : 0) + ' of the day</div>';
                if (w.titles && w.titles.length) lines += '<div class="zq-titles">' + w.titles.map(esc).join(' · ') + '</div>';
            }
            if (!w.active && w.expected_hours) {
                lines += '<div class="zq-titles">switched off — the same rule would take ≈ ' + fmtH(w.expected_hours)
                       + ' and ≈ ' + fmtTok(w.expected_tokens) + ' tokens</div>';
            }
            lines += '<div class="zq-titles" title="' + esc(w.unit_basis || '') + '">unit ≈ ' + (w.unit_min != null ? w.unit_min + ' min' : 'unknown') + '</div>';
            return '<div class="zq-det-w" style="border-left-color:' + colorOk(m.accent) + ';"><b>' + esc(m.name) + '</b>' + lines + '</div>';
        }).join('');
        var mach = c.machine
            ? fmtH(c.machine.measured_h) + ' measured, ' + fmtH(c.machine.busy_h) + ' GPU-busy'
              + (c.machine.gpu_mean != null ? ' · GPU mean ' + c.machine.gpu_mean + '%' : '')
              + (c.machine.kwh ? ' · ' + c.machine.kwh + ' kWh' : '') + ' — ' + esc(c.machine.basis)
            : 'no machine utilisation recorded for this day';
        return '<div class="zq-det"><div class="zq-det-h">' + esc(c.dow) + ' ' + esc(c.date)
             + (c.is_future ? ' — planned' : (c.is_today ? ' — today so far' : ' — as it happened'))
             + '<a href="#" class="zq-close" title="Close">✕</a></div>'
             + '<div class="zq-det-g">' + (parts || '<div class="zq-empty">nothing on this day</div>') + '</div>'
             + '<div class="zq-notes">' + mach + '</div></div>';
    }

    function calNotes() {
        var n = (_cal && _cal.notes) || [];
        var t = (_cal && _cal.totals) || {};
        var src = (_cal && _cal.sources) || {};
        if (!n.length) return '';
        return '<details class="zq-notes"><summary>How these numbers are made</summary><ul>'
             + n.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('')
             + (t.gpu_share_basis ? '<li>' + esc(t.gpu_share_basis) + '</li>' : '')
             + ((_cal && _cal.plan_meta && _cal.plan_meta.plan_basis) ? '<li>' + esc(_cal.plan_meta.plan_basis) + '</li>' : '')
             + '<li>Read from ' + (src.runs || 0) + ' runs and ' + (src.llm_rows || 0) + ' LLM calls on the ledger, '
             + (src.machine_days || 0) + ' days with a utilisation record.</li>'
             + '</ul></details>';
    }

    function calPanel() {
        if (!_calOpen) {
            return '<div class="zq-side zq-side-shut"><div class="zq-pan">'
                 + '<button type="button" class="zq-vbtn zq-cfold" title="Show the calendar panel" '
                 + 'style="width:40px;height:40px;font-size:15px;border:0;background:none;">📅</button></div></div>';
        }
        var body;
        if (_calErr && !_cal) {
            body = '<div class="zq-cerr">Calendar failed to load: ' + esc(_calErr) + '</div>';
        } else if (!_cal) {
            body = '<div class="zq-empty">loading…</div>';
        } else if (_calView === 'production') {
            body = prodSummary() + prodTable() + dayDetail() + calNotes();
        } else {
            body = calGrid() + dayDetail() + calNotes();
        }
        // A width the operator dragged wins over the layout. The height is AUTO by default:
        // fitPanel() gives the body a max-height that reaches the bottom of the window, so the
        // panel opens as big as the page allows and scrolls inside itself instead of pushing
        // the page down. A height the operator dragged pins it and wins over the fit.
        var sideCls = 'zq-side' + (_calW > 0 ? ' zq-side-set' : '');
        var sideSty = _calW > 0 ? ' style="width:' + _calW + 'px;"' : '';
        var bodySty = _calH > 0 ? ' style="height:' + _calH + 'px;overflow:auto;"'
                    : (_fitH > 0 ? ' style="max-height:' + _fitH + 'px;overflow:auto;"' : '');
        return '<div class="' + sideCls + '"' + sideSty + '>'
             + '<div class="zq-pan">' + calHeader()
             + '<div class="zq-pan-b"' + bodySty + '>' + (_calErr && _cal ? '<div class="zq-cerr">' + esc(_calErr) + '</div>' : '') + body + '</div>'
             + '<div class="zq-grip" title="Drag to resize the panel · double-click to fit it to the window"></div>'
             + '</div></div>';
    }

    // ── the panel sizes itself to the window ─────────────────────────
    // The body gets a max-height that reaches the bottom of the viewport, so the panel opens
    // as tall as the page allows and a long production table scrolls INSIDE it (scrollbar on
    // the right) instead of running off the bottom of the page. Re-measured after every
    // render and on every window resize / zoom change, so it always matches the window.
    //
    // Screen px vs CSS px — this GUI runs at html{zoom:.67}, and which space a measurement
    // comes back in depends on the browser build (this Chrome reports rects and innerHeight in
    // the zoomed layout space, older ones in screen px). So the measurement is divided by the
    // scale the element itself reports (rect.height / offsetHeight), never by a hard-coded
    // factor: the fit is then right either way. Same rule as the grip below.

    /** Lowest bottom edge the panel may reach: the window, or a SCROLLING ancestor.
     *  Only overflow auto/scroll counts — `.zq-pan` is overflow:hidden to clip its own rounded
     *  corners and its height comes from this very body, so reading its bottom would pin the
     *  panel to the size it already has (the first cut of this did, and fitted 320 px). */
    function fitBottom(el) {
        var bottom = window.innerHeight || document.documentElement.clientHeight || 0;
        for (var n = el.parentNode; n && n.nodeType === 1 && n !== document.body; n = n.parentNode) {
            var ov;
            try { ov = window.getComputedStyle(n).overflowY; } catch (e) { ov = 'visible'; }
            if (ov === 'auto' || ov === 'scroll') {
                var rb = n.getBoundingClientRect().bottom;
                if (rb > 0 && rb < bottom) bottom = rb;
            }
        }
        return bottom;
    }

    function fitPanel() {
        if (_sizing) return;                       // the grip owns the size while it is down
        if (!_container || !document.contains(_container)) return;
        var body = _container.querySelector('.zq-pan-b');
        if (!body) return;
        if (_calH > 0) {                           // a dragged height wins, it just keeps its scroller
            body.style.height = _calH + 'px';
            body.style.maxHeight = '';
            body.style.overflow = 'auto';
            return;
        }
        var r = body.getBoundingClientRect();
        var scale = (body.offsetHeight > 0 && r.height > 0) ? (r.height / body.offsetHeight) : 1;
        if (!(scale > 0.2 && scale < 5)) scale = 1;
        var avail = Math.round((fitBottom(body) - r.top) / scale) - FIT_GAP;
        if (!isFinite(avail)) return;
        avail = Math.max(FIT_MIN, avail);
        if (avail === _fitH && body.style.maxHeight === avail + 'px') return;
        _fitH = avail;
        body.style.height = '';
        body.style.maxHeight = avail + 'px';
        body.style.overflow = 'auto';
    }

    function onResize() {
        if (_fitTimer) clearTimeout(_fitTimer);
        _fitTimer = setTimeout(function () { _fitTimer = null; fitPanel(); }, 120);
    }

    // ── page ─────────────────────────────────────────────────────────────────
    function renderBoard(container, data) {
        if (_sizing) return;          // a poll must not pull the panel out from under the grip
        data = data || {};
        var wfs = Array.isArray(data.workflows) ? data.workflows.filter(function (w) { return w && w.id != null; }) : [];
        var running = wfs.filter(function (w) { return stateOf(w) === 'running'; }).length;
        var sub = wfs.length + ' workflow' + (wfs.length === 1 ? '' : 's')
                + ' · <b>' + running + '</b> running'
                + (data.ts ? ' · board ' + esc(fmtTs(data.ts)) : '')
                + (data.quota && data.quota.sampled_at ? ' · quota sampled ' + esc(fmtTs(data.quota.sampled_at)) : '')
                + (_fetchErr ? ' · <span class="zq-err">last poll failed: ' + esc(_fetchErr) + '</span>' : '');

        var html =
            '<style>' + CSS + '</style>'
          + '<div class="parameter-control-table-wrap zq-root">'
          + '<div class="zq-head">'
          +   '<div class="zq-title">'
          +     '<h3 class="dashboard-monitoring-title">Production Queue</h3>'
          +     '<div class="zq-sub">' + sub + '</div>'
          +   '</div>'
          +   quotaStrip(data.quota)
          +   '<div class="zq-spacer"></div>'
          +   '<button id="zkb-refresh" type="button" class="zq-btn">↻ Refresh</button>'
          + '</div>'
          + '<div class="zq-main">'
          +   '<div class="zq-left">' + workflowStrip(wfs) + '</div>'
          +   calPanel()
          + '</div>'
          + cardDialog()
          + '</div>';

        // Keep every DIRTY settings form: lift its node out before the redraw
        // and drop it back into the fresh card, focus and caret included.
        var keep = {}, focusEl = null, sel = null, active = document.activeElement;
        var oldModal = container.querySelector('.zq-modal-b');
        var oldPanB  = container.querySelector('.zq-pan-b');
        var modalTop = oldModal ? oldModal.scrollTop : 0;
        var panTop   = oldPanB ? oldPanB.scrollTop : 0;
        Object.keys(_dirty).forEach(function (id) {
            if (!_dirty[id]) return;
            var panel = byWf(container, '.zq-settings', id);
            if (!panel) { _dirty[id] = false; return; }
            keep[id] = panel;
            if (active && panel.contains(active)) {
                focusEl = active;
                try { sel = [active.selectionStart, active.selectionEnd]; } catch (e) { sel = null; }
            }
        });

        container.innerHTML = html;

        Object.keys(keep).forEach(function (id) {
            var slot = byWf(container, '.zq-settings', id);
            if (slot && slot.parentNode) slot.parentNode.replaceChild(keep[id], slot);
            else _dirty[id] = false;                // card no longer expanded/present: nothing to keep
        });
        if (focusEl && document.contains(focusEl)) {
            try {
                focusEl.focus();
                if (sel && sel[0] != null) focusEl.setSelectionRange(sel[0], sel[1]);
            } catch (e) { /* number inputs refuse setSelectionRange */ }
        }
        var nb = container.querySelector('.zq-modal-b');
        if (nb && modalTop) nb.scrollTop = modalTop;
        var np = container.querySelector('.zq-pan-b');
        if (np && panTop) np.scrollTop = panTop;
        fitPanel();                               // the panel always ends at the bottom of the window
    }

    // ── interactions (delegated once per container: no stale closures) ───────
    /** A click on a card opens its dialog; only one is ever open. */
    function openCard(id) {
        if (!findWf(id) || _dialog === id) return;
        if (_dialog) closeCard(true);
        _dialog = id;
        renderBoard(_container, _board);
    }

    function closeCard(silent) {
        if (!_dialog) return;
        _dirty[_dialog] = false;
        delete _saveMsg[_dialog];
        _dialog = null;
        if (!silent) renderBoard(_container, _board);
    }

    function doAction(id, action) {
        var wf = findWf(id);
        if (!wf || _pending[id]) return;
        if ((wf.actions || []).indexOf(action) < 0) return;
        if (action === 'abort') {
            var q = 'Abort “' + (wf.name || id) + '”?\n'
                  + (id === 'preempt'
                        ? 'The current brain run is stopped; the bank (ready entries) is kept.'
                        : 'The running item is stopped and the remaining scheduled items are marked failed.');
            if (!window.confirm(q)) return;
        }
        _pending[id] = true;
        _errors[id] = '';
        renderBoard(_container, _board);
        postJson('/api/approval_queue/' + encodeURIComponent(id) + '/action', {action: action})
            .then(function (res) {
                _pending[id] = false;
                if (!res.ok) {
                    _errors[id] = action + ': ' + res.error;
                    renderBoard(_container, _board);
                    return;
                }
                if (res.body && res.body.workflow) patchWorkflow(res.body.workflow);
                return reload(_container, true);
            });
    }

    function doDelete(wfId, itemId) {
        var wf = findWf(wfId);
        if (!wf || _pending[wfId]) return;
        var it = null;
        (wf.items || []).forEach(function (e) { if (e && String(e.id) === String(itemId)) it = e; });
        var label = it ? ((it.no ? it.no + ' ' : '') + (it.title || itemId)) : itemId;
        if (!window.confirm('Delete “' + label + '” from the bank?')) return;
        _errors[wfId] = '';
        postJson('/api/approval_queue/' + encodeURIComponent(wfId) + '/item/' + encodeURIComponent(itemId) + '/action', {action: 'delete'})
            .then(function (res) {
                if (!res.ok) {
                    _errors[wfId] = 'delete ' + label + ': ' + res.error;
                    renderBoard(_container, _board);
                    return;
                }
                return reload(_container, true);
            });
    }

    function setMsg(panel, cls, text) {
        var m = panel && panel.querySelector('.zq-savemsg');
        if (!m) return;
        m.className = 'zq-savemsg' + (cls ? ' ' + cls : '');
        m.textContent = text || '';
    }

    function doSave(id) {
        var wf = findWf(id);
        var panel = byWf(_container, '.zq-settings', id);
        if (!wf || !panel) return;
        var btn = panel.querySelector('.zq-save');
        var inputs = panel.querySelectorAll('[data-key]');
        var changed = {}, n = 0;
        for (var i = 0; i < inputs.length; i++) {
            var el = inputs[i], v = fieldValue(el), o;
            try { o = JSON.parse(el.getAttribute('data-orig')); } catch (e) { o = undefined; }
            if (JSON.stringify(v) !== JSON.stringify(o)) { changed[el.getAttribute('data-key')] = v; n++; }
        }
        if (!n) {
            _dirty[id] = false;
            setMsg(panel, '', 'no changes');
            return;
        }
        if (btn) btn.disabled = true;
        setMsg(panel, 'pend', 'saving…');
        postJson('/api/approval_queue/' + encodeURIComponent(id) + '/settings', changed)
            .then(function (res) {
                if (!res.ok) {                           // keep the form (still dirty) so the value can be corrected
                    if (btn) btn.disabled = false;
                    setMsg(panel, 'bad', res.error);
                    return;
                }
                _dirty[id] = false;
                _saveMsg[id] = {ok: true, text: 'saved'};
                if (res.body && res.body.workflow) patchWorkflow(res.body.workflow);
                else if (res.body && Array.isArray(res.body.settings)) wf.settings = res.body.settings;
                _lastSig = sigOf(_board);                // the next poll compares against what we just drew
                renderBoard(_container, _board);
                setTimeout(function () {
                    if (_saveMsg[id] && _saveMsg[id].text === 'saved') {
                        delete _saveMsg[id];
                        if (!_dirty[id]) setMsg(byWf(_container, '.zq-settings', id), '', '');
                    }
                }, 6000);
            });
    }

    function loadCal(force) {
        var q = CAL_URL + '?view=' + encodeURIComponent(_calView) + '&days=' + _calDays
              + (_calAnchor ? '&anchor=' + encodeURIComponent(_calAnchor) : '');
        _calBusy = true;
        return fetch(q, {credentials: 'same-origin'})
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                if (!data || data.ok === false) throw new Error((data && data.error) || 'bad payload');
                _calBusy = false;
                _calErr = '';
                _cal = data;
                // The server clamps the window (a year back, 28 days ahead); follow what it
                // returned, so the arrows cannot walk past the edge and lose their place.
                _calAnchor = (data.range && data.range.start) || _calAnchor;
                if (_calSel) {
                    var seen = false, list = data.days_list || [];
                    for (var i = 0; i < list.length; i++) if (list[i].date === _calSel) seen = true;
                    if (!seen) _calSel = '';
                }
                renderBoard(_container, _board);
            })
            .catch(function (err) {
                _calBusy = false;
                _calErr = String((err && err.message) || err);
                renderBoard(_container, _board);
            });
    }

    function calSet(changes, reload) {
        if ('view' in changes)   _calView = changes.view;
        if ('days' in changes)   _calDays = changes.days;
        if ('anchor' in changes) _calAnchor = changes.anchor;
        if ('open' in changes)   _calOpen = changes.open;
        if ('sel' in changes)    _calSel = changes.sel;
        prefSave();
        if (reload) loadCal(true);
        else renderBoard(_container, _board);
    }

    function onCalClick(t, root) {
        var el = closest(t, '.zq-cview', root);
        if (el) { calSet({view: _calView === 'calendar' ? 'production' : 'calendar'}, true); return true; }
        el = closest(t, '.zq-cfold', root);
        if (el) { calSet({open: !_calOpen}, false); return true; }
        el = closest(t, '.zq-cwin', root);
        if (el) { calSet({days: Number(el.getAttribute('data-days')) || 7}, true); return true; }
        el = closest(t, '.zq-cnav', root);
        if (el) {
            var dir = Number(el.getAttribute('data-dir')) || 1;
            var start = (_cal && _cal.range && _cal.range.start) || (_cal && _cal.today) || '';
            if (!start) return true;
            calSet({anchor: shiftDate(start, dir * _calDays)}, true);
            return true;
        }
        el = closest(t, '.zq-ctoday', root);
        if (el) { calSet({anchor: ''}, true); return true; }
        el = closest(t, '.zq-close', root);
        if (el) { calSet({sel: ''}, false); return true; }
        el = closest(t, '[data-day]', root);
        if (el) {
            var d = el.getAttribute('data-day');
            calSet({sel: d === _calSel ? '' : d}, false);
            return true;
        }
        return false;
    }

    function onClick(ev) {
        var root = _container, t = ev.target, el;
        if (!root || !t) return;
        if (closest(t, '.zq-grip', root)) { ev.preventDefault(); return; }   // the grip drags, it never clicks
        if (closest(t, '.zq-side', root)) {
            if (onCalClick(t, root)) { ev.preventDefault(); return; }
        }
        if (closest(t, '.zq-mclose', root)) { ev.preventDefault(); closeCard(); return; }
        if (t.classList && t.classList.contains('zq-modal')) { closeCard(); return; }   // click outside the card
        el = closest(t, '.zq-act', root);
        if (el) { ev.preventDefault(); doAction(el.getAttribute('data-wf'), el.getAttribute('data-action')); return; }
        el = closest(t, '.zq-del', root);
        if (el) { ev.preventDefault(); doDelete(el.getAttribute('data-wf'), el.getAttribute('data-item')); return; }
        el = closest(t, '.zq-save', root);
        if (el) { ev.preventDefault(); doSave(el.getAttribute('data-wf')); return; }
        if (closest(t, '#zkb-refresh', root)) { reload(root, true); loadCal(true); return; }
        el = closest(t, '.zq-wbody', root);
        if (el) openCard(el.getAttribute('data-wf'));
    }

    function onKey(ev) {
        if (ev.key === 'Escape' && _dialog && _container && document.contains(_container)) closeCard();
    }

    // ── the calendar panel's corner grip ────────────────────────────────────
    // This GUI runs at html{zoom:.67}: rects and pointer coordinates are in screen px while
    // the width we write is in CSS px. The drag is therefore divided by the scale the element
    // itself reports (rect.width / offsetWidth), never by a hard-coded factor.
    function gripDown(ev) {
        if (!_container || ev.button) return;
        var grip = closest(ev.target, '.zq-grip', _container);
        if (!grip) return;
        // Double-press = reset. It cannot be a dblclick listener: gripDown preventDefault()s the
        // pointerdown (else the drag selects text), and that suppresses the compatibility mouse
        // events — click and dblclick never arrive on the grip. So the pair is timed here, and
        // only presses that did not drag count.
        if (_tapAt && (Date.now() - _tapAt) < 450 && _tapXY
            && Math.abs(ev.clientX - _tapXY[0]) < 8 && Math.abs(ev.clientY - _tapXY[1]) < 8) {
            _tapAt = 0; _tapXY = null;
            ev.preventDefault();
            gripResetNow();
            return;
        }
        var side = closest(grip, '.zq-side', _container);
        var body = _container.querySelector('.zq-pan-b');
        if (!side || !body) return;
        var r = side.getBoundingClientRect();
        var scale = (side.offsetWidth > 0 && r.width > 0) ? (r.width / side.offsetWidth) : 1;
        if (!(scale > 0.2 && scale < 5)) scale = 1;
        _grab = {x0: ev.clientX, y0: ev.clientY, w0: side.offsetWidth, h0: body.offsetHeight,
                 scale: scale, side: side, body: body};
        _sizing = true;
        ev.preventDefault();
        document.body.classList.add('zq-resizing');
        window.addEventListener('pointermove', gripMove, true);
        window.addEventListener('pointerup', gripUp, true);
        window.addEventListener('pointercancel', gripUp, true);
    }

    function gripMove(ev) {
        if (!_grab) return;
        _grab.moved = true;
        _calW = Math.max(360, Math.min(6000, Math.round(_grab.w0 + (ev.clientX - _grab.x0) / _grab.scale)));
        _calH = Math.max(220, Math.min(6000, Math.round(_grab.h0 + (ev.clientY - _grab.y0) / _grab.scale)));
        _grab.side.className = 'zq-side zq-side-set';
        _grab.side.style.width = _calW + 'px';
        _grab.body.style.height = _calH + 'px';
        _grab.body.style.overflow = 'auto';
        ev.preventDefault();
    }

    function gripUp() {
        var still = !!(_grab && !_grab.moved);
        _tapAt = still ? Date.now() : 0;
        _tapXY = still ? [_grab.x0, _grab.y0] : null;
        window.removeEventListener('pointermove', gripMove, true);
        window.removeEventListener('pointerup', gripUp, true);
        window.removeEventListener('pointercancel', gripUp, true);
        document.body.classList.remove('zq-resizing');
        _grab = null;
        _sizing = false;
        prefSave();
        renderBoard(_container, _board);
    }

    /** Double-click the grip: back to the layout width and the auto height (fit to the window).
     *  The first click of the pair ends a (zero-length) drag, and gripUp re-renders, so by the
     *  time dblclick fires its target is the OLD grip node — detached from the container. The
     *  hit test therefore reads the node's own class instead of walking up to _container. */
    function gripResetNow() {
        _calW = 0; _calH = 0; _fitH = 0;
        prefSave();
        renderBoard(_container, _board);
    }

    function gripReset(ev) {
        var t = ev.target;
        if (!_container || !t || t.nodeType !== 1) return;
        var onGrip = (t.classList && t.classList.contains('zq-grip'))
                  || !!closest(t, '.zq-grip', _container)
                  || !!(t.closest && t.closest('.zq-grip'));
        if (!onGrip) return;
        gripResetNow();
    }

    function onInput(ev) {
        if (ev.target && ev.target.classList && ev.target.classList.contains('zq-jump')) {
            var v = ev.target.value;
            if (v !== '') {
                var today = (_cal && _cal.today) || '';
                calSet({anchor: (Number(v) === 0 || !today) ? '' : shiftDate(today, Number(v))}, true);
            }
            return;
        }
        var panel = closest(ev.target, '.zq-settings', _container);
        if (!panel) return;
        var id = panel.getAttribute('data-wf');
        _dirty[id] = true;
        delete _saveMsg[id];
        setMsg(panel, 'pend', 'unsaved changes');
    }

    function wire(container) {
        if (container._zqWired) return;
        container._zqWired = true;
        container.addEventListener('click',  onClick);
        container.addEventListener('input',  onInput);
        container.addEventListener('change', onInput);
        container.addEventListener('pointerdown', gripDown, true);
        container.addEventListener('dblclick', gripReset, true);
        document.addEventListener('keydown', onKey);
        window.addEventListener('resize', onResize);
        if (window.visualViewport) window.visualViewport.addEventListener('resize', onResize);
    }

    function reload(container, force) {
        return fetch(BOARD_URL, {credentials: 'same-origin'})
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                if (!data || typeof data !== 'object') throw new Error('bad payload');
                var hadErr = !!_fetchErr;
                _fetchErr = '';
                // The tab re-polls every 15 s; re-writing innerHTML when nothing
                // changed makes the whole board blink, so only redraw on a real change.
                var sig = sigOf(data);
                if (!force && !hadErr && sig && sig === _lastSig) return;
                _lastSig = sig;
                _board = data;
                renderBoard(container, data);
            })
            .catch(function (err) {
                var msg = String((err && err.message) || err);
                var changed = msg !== _fetchErr;
                _fetchErr = msg;
                if (_board) { if (changed || force) renderBoard(container, _board); }
                else container.innerHTML = '<div style="padding:24px;color:#c0392b;">Failed to load queue (' + esc(msg) + ')</div>';
            });
    }

    function render(container) {
        if (!container) return;
        if (_refreshTimer) { clearInterval(_refreshTimer); _refreshTimer = null; }
        if (_calTimer) { clearInterval(_calTimer); _calTimer = null; }
        _container = container;
        prefLoad();
        wire(container);
        _lastSig = null;
        reload(container, true);
        loadCal(true);
        _refreshTimer = setInterval(function () { reload(container); }, POLL_MS);
        _calTimer = setInterval(function () { loadCal(true); }, CAL_POLL_MS);
    }

    window.DashboardTabApprovalQueue = {render: render};
})();
