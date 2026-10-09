/**
 * Agent Zero v2 — pending manual-permission requests.
 *
 * Ported from Static/js/dashboard_agent_zero.js (state ~20-30, polling and
 * blinking ~1470-1590, decision ~1592-1633, request cards ~1635-1746).
 *
 * Plugs into the new Zero window through window.AgentZeroUI only: it never
 * touches the window's internals. Loads safely before or after zero_chat.js —
 * it waits for the hook object with a short poll (max 10 s).
 */
(function () {
    'use strict';

    var HOOK_POLL_MS = 150;
    var HOOK_POLL_MAX_MS = 10000;
    var PENDING_POLL_MS = 20000;
    var BLINK_HALF_CYCLE_MS = 900;
    var CARD_ID_PREFIX = 'zero-request-';
    var GEAR_ID = 'zero-pending-requests';

    var UI = null;                       // window.AgentZeroUI once resolved
    var _pendingManualCount = 0;
    var _pendingPollInterval = null;
    var _pendingListCache = [];          // latest fetched pending list
    var _renderedIds = {};               // request id -> card element
    var _blinkInterval = null;           // shared JS blink loop (both buttons in sync)
    var _blinkHigh = false;              // current blink phase
    var _gearLabel = '';
    var _styleInjected = false;

    function byId(id) { return document.getElementById(id); }

    function escapeHtml(s) {
        if (s == null || s === undefined) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function csrfHeaders() {
        var csrf = (typeof getCsrfToken === 'function') ? getCsrfToken() : '';
        var h = { 'Content-Type': 'application/json' };
        if (csrf) h['X-CSRF-Token'] = csrf;
        return h;
    }

    // ── Styles (the badge + blink class the old dialog relied on) ───────────
    function injectStyles() {
        if (_styleInjected) return;
        _styleInjected = true;
        var style = document.createElement('style');
        style.id = 'zero-requests-styles';
        style.textContent =
            '.zpub-pending-badge{position:absolute;top:-6px;right:-6px;background:#dc2626;color:#fff;border-radius:50%;width:18px;height:18px;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;pointer-events:none;}' +
            '@keyframes zpub-tab-blink{0%,100%{opacity:1}50%{opacity:0.25}}' +
            '.agent-zero-tab-blink{animation:zpub-tab-blink 0.9s ease-in-out infinite !important;}';
        document.head.appendChild(style);
    }

    // ── Shared JS blink loop — sidebar button and minimized tab in sync ────
    function _sidebarBtn() { return byId('dashboard-sidebar-agent-zero'); }
    function _minimizedTab() { return byId('agent-zero-minimized'); }

    function _applyBlinkFrame(high) {
        var sidebarBtn = _sidebarBtn();
        var tab = _minimizedTab();
        // Soft blue-gray brightening — same palette as the buttons, just more saturated
        var bgHighSidebar = 'rgba(148,168,210,0.55)';
        var bgHighTab     = 'linear-gradient(140deg,#bfcde6,#96aece)';
        var borderHigh    = '#8facd4';
        var shadowSidebar = '0 0 10px rgba(140,165,210,0.4)';
        var shadowTab     = '0 -4px 16px rgba(120,148,195,0.45)';
        if (sidebarBtn) {
            sidebarBtn.style.background  = high ? bgHighSidebar : '';
            sidebarBtn.style.borderColor = high ? borderHigh    : '';
            sidebarBtn.style.color       = '';   // keep default text colour always
            sidebarBtn.style.boxShadow   = high ? shadowSidebar : '';
        }
        if (tab && tab.style.display !== 'none') {
            tab.style.background  = high ? bgHighTab   : '';
            tab.style.borderColor = high ? borderHigh  : '';
            tab.style.color       = '';   // keep default text colour always
            tab.style.boxShadow   = high ? shadowTab   : '';
        }
    }

    function _startBlinkLoop() {
        if (_blinkInterval) return;
        _blinkHigh = false;
        _blinkInterval = setInterval(function () {
            _blinkHigh = !_blinkHigh;
            _applyBlinkFrame(_blinkHigh);
        }, BLINK_HALF_CYCLE_MS);  // 900ms per half-cycle → 1.8s full blink cycle
    }

    function _stopBlinkLoop() {
        if (_blinkInterval) { clearInterval(_blinkInterval); _blinkInterval = null; }
        _blinkHigh = false;
        _applyBlinkFrame(false);  // reset both to normal colours
    }

    // ── Badges on the sidebar button and the minimized tab ─────────────────
    function _setBadgeOn(el, count) {
        if (!el) return;
        var badge = el.querySelector('.zpub-pending-badge');
        if (count > 0) {
            if (!badge) {
                badge = document.createElement('span');
                badge.className = 'zpub-pending-badge';
                el.appendChild(badge);
            }
            badge.textContent = count;
            badge.style.display = 'flex';
        } else if (badge) {
            badge.style.display = 'none';
        }
    }

    function _setPendingCount(count, pendingList) {
        _pendingManualCount = count;
        _pendingListCache = pendingList || [];

        var sidebarBtn = _sidebarBtn();
        var tab = _minimizedTab();

        if (count > 0) {
            if (sidebarBtn) sidebarBtn.style.display = 'block';
            _setBadgeOn(sidebarBtn, count);
            if (tab) {
                tab.style.position = 'fixed';
                tab.style.bottom = '0';
                tab.style.zIndex = '99998';
                _setBadgeOn(tab, count);
            }
            _startBlinkLoop();
        } else {
            if (sidebarBtn) sidebarBtn.style.display = 'none';
            _setBadgeOn(sidebarBtn, 0);
            _setBadgeOn(tab, 0);
            _stopBlinkLoop();
        }

        if (UI && UI.setBadge) { try { UI.setBadge(count); } catch (_) {} }
        _updateGearLabel(count);
    }

    // ── Polling ────────────────────────────────────────────────────────────
    function _fetchPending() {
        return fetch('/api/zero_public/pending', { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; });
    }

    function _pollPendingManual() {
        if (window._serverRestarting) return;
        _fetchPending()
            .then(function (data) {
                if (!data) return;
                var count = data.count || 0;
                var list  = (data.pending || []).filter(function (r) { return r.status === 'pending'; });
                _setPendingCount(count, list);
                _syncCards(list);
            })
            .catch(function () {});
    }

    function _startPendingPoll() {
        if (_pendingPollInterval) return;
        _pollPendingManual();
        _pendingPollInterval = setInterval(_pollPendingManual, PENDING_POLL_MS);
        window._agentZeroPendingPollInterval = _pendingPollInterval;
    }

    function _stopPendingPoll() {
        if (_pendingPollInterval) { clearInterval(_pendingPollInterval); _pendingPollInterval = null; }
        window._agentZeroPendingPollInterval = null;
    }

    // ── Request card rendering ─────────────────────────────────────────────
    function _cardId(reqId) { return CARD_ID_PREFIX + reqId; }

    function _deltaHtml(req) {
        // Delivered-vs-selected disclosure (2026-07-20): the anchor gate ships
        // the closest face FLUX could render and syncs to it, so surface the
        // deltas on the contact-sheet review card before the operator commits.
        var html = '';
        var deltas = req.attribute_deltas || [];
        if (!deltas.length) return html;
        var hard = deltas.filter(function (d) { return !d.advisory; });
        var adv  = deltas.filter(function (d) { return d.advisory; });
        function _row(d) {
            return escapeHtml(d.label) + ': <b>' + escapeHtml(String(d.delivered)) +
                   '</b> (you selected ' + escapeHtml(String(d.selected)) + ')';
        }
        if (hard.length) {
            html += '<b style="color:#dc2626">⚠ Delivered differs from selection:</b><br>' +
                    hard.map(function (d) { return '&nbsp;&nbsp;• ' + _row(d); }).join('<br>') + '<br>';
        }
        if (adv.length) {
            html += '<b style="color:#b45309">Advisory (FLUX can\'t reliably hit these):</b><br>' +
                    adv.map(function (d) { return '&nbsp;&nbsp;• ' + _row(d); }).join('<br>') + '<br>';
        }
        return html;
    }

    function _reviewHtml(req, pipeline) {
        var html = '';
        // Clickable review link (2026-07-21): build a real link from the card's
        // char_id to the main-app image route — a logged-in dashboard session is
        // authorized for /api/internal/ without a token. char_id is
        // regex-validated, so it is safe to interpolate directly.
        var cid = req.char_id || '';
        if ((pipeline === 'contact_sheet_review' || pipeline === 'contact_sheet') &&
            /^[a-f0-9]{12}$/.test(cid)) {
            var sheetUrl = '/api/internal/storyteller/contact-sheet/image/' + cid;
            var linkStyle = 'color:#2563eb;text-decoration:underline;font-weight:600';
            // Default the primary review link to the TRAINING-SET sheet
            // (2026-07-22): it shows exactly the tiles that train — the
            // QC-excluded distortion tiles are absent, so the operator reviews
            // what the LoRA actually learns. The full 48-angle sheet is kept as
            // a secondary link.
            html +=
                '<b>Review sheet:</b> ' +
                '<a href="' + sheetUrl + '?variant=training" target="_blank" rel="noopener" style="' + linkStyle + '">🖼 open review sheet (what trains)</a>' +
                ' &nbsp;·&nbsp; <a href="' + sheetUrl + '" target="_blank" rel="noopener" style="' + linkStyle + '">full 48-angle sheet</a>' +
                ' &nbsp;·&nbsp; <a href="' + sheetUrl + '?variant=training&download=1" target="_blank" rel="noopener" style="' + linkStyle + '">⬇ download</a>' +
                '<br>';
        }
        // Creature sheet review (2026-08-26): the creature gate parks a run
        // whose whole deliverable is one sheet, so the card links straight at
        // it. creature_id is 12-hex-validated server-side.
        var crid = req.creature_id || '';
        if (pipeline === 'creature_review' && /^[a-f0-9]{12}$/.test(crid)) {
            var crUrl = '/api/internal/creature/' + crid + '/sheet';
            var crStyle = 'color:#2563eb;text-decoration:underline;font-weight:600';
            var rep = req.sheet_report || {};
            html +=
                '<b>Review sheet:</b> ' +
                '<a href="' + crUrl + '" target="_blank" rel="noopener" style="' + crStyle + '">\uD83D\uDDBC open creature sheet</a>' +
                ' &nbsp;\u00b7&nbsp; <a href="' + crUrl + '?download=1" target="_blank" rel="noopener" style="' + crStyle + '">\u2b07 download</a>' +
                '<br>';
            if (rep.cell_count) {
                html += '<b>Cells:</b> ' + escapeHtml(String(rep.pass_count)) + '/' +
                    escapeHtml(String(rep.cell_count)) + ' pass' +
                    (rep.judged_any ? '' : ' <span style="color:#b45309">(judge offline \u2014 structural + DINO only)</span>') +
                    '<br>';
            }
        }
        // Style-calibration preview links (2026-07-26): clickable links to a
        // character's sweep/preview grids, served by the contact-sheet image
        // route's ?preview= handler. cid is 12-hex-validated.
        var _pvs = req.preview_images || [];
        if (_pvs.length && /^[a-f0-9]{12}$/.test(cid)) {
            var _pbase = '/api/internal/storyteller/contact-sheet/image/' + cid + '?preview=';
            var _pstyle = 'color:#a855f7;text-decoration:underline;font-weight:600';
            html += '<b>Style preview:</b> ' + _pvs.map(function (p) {
                var _n = (typeof p === 'string') ? p : (p.name || '');
                var _l = (typeof p === 'string') ? p : (p.label || p.name || '');
                return '<a href="' + _pbase + encodeURIComponent(_n) + '" target="_blank" rel="noopener" style="' + _pstyle + '">🎨 ' + escapeHtml(_l) + '</a>';
            }).join(' &nbsp;·&nbsp; ') + '<br>';
        }
        return html;
    }

    function _cardHtml(req) {
        var label    = req.label || req.token || 'unknown';
        var url      = req.invite_url || '';
        var prompt   = req.prompt ? req.prompt.substring(0, 120) : '—';
        var pipeline = req.pipeline || 'unknown';
        var reqAt    = req.requested_at ? req.requested_at.replace('T', ' ').substring(0, 16) : '';
        var btn = 'display:inline-block;margin:4px 8px 4px 0;padding:6px 12px;border-radius:7px;' +
                  'border:1px solid #7a8bb3;background:linear-gradient(140deg,#e8ecf7,#dde3f4);' +
                  'cursor:pointer;font-size:13px;font-weight:500;color:#0d1117;';
        return '' +
            '<div><strong>Zero:</strong> <span style="color:#dc2626">Pending request</span></div>' +
            '<b>User:</b> ' + escapeHtml(label) + '<br>' +
            (url ? '<b>URL:</b> <code style="font-size:0.85em">' + escapeHtml(url) + '</code><br>' : '') +
            '<b>Pipeline:</b> ' + escapeHtml(pipeline) + '<br>' +
            '<b>Prompt:</b> ' + escapeHtml(prompt) + '<br>' +
            _reviewHtml(req, pipeline) +
            _deltaHtml(req) +
            '<b>Requested:</b> ' + escapeHtml(reqAt) +
            '<div class="zero-request-actions" style="display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;">' +
            '<button type="button" data-action="allow"   style="' + btn + '">✅ Allow</button>' +
            '<button type="button" data-action="queue"   style="' + btn + '">🕐 Queue</button>' +
            '<button type="button" data-action="decline" style="' + btn + '">❌ Decline</button>' +
            '</div>' +
            '<div class="zero-request-note" style="margin-top:6px;font-size:12px;color:#555;"></div>';
    }

    function _renderCard(req) {
        if (!UI || !UI.appendSystemCard) return;
        var id = _cardId(req.id);
        if (_renderedIds[req.id]) return;
        var el;
        try {
            el = UI.appendSystemCard(_cardHtml(req), { id: id, kind: 'request' });
        } catch (_) {
            return;
        }
        if (!el) return;
        _renderedIds[req.id] = el;
        var btns = el.querySelectorAll('.zero-request-actions button');
        Array.prototype.forEach.call(btns, function (b) {
            b.onclick = function () { _decidePending(req.id, b.getAttribute('data-action'), el); };
        });
    }

    function _removeCard(reqId) {
        var el = _renderedIds[reqId];
        delete _renderedIds[reqId];
        if (UI && UI.removeSystemCard) {
            try { UI.removeSystemCard(_cardId(reqId)); return; } catch (_) {}
        }
        if (el && el.parentNode) el.parentNode.removeChild(el);
    }

    function _syncCards(pendingList) {
        var live = {};
        (pendingList || []).forEach(function (req) {
            live[req.id] = true;
            _renderCard(req);
        });
        Object.keys(_renderedIds).forEach(function (id) {
            if (!live[id]) _removeCard(id);
        });
    }

    function _decidePending(reqId, action, cardEl) {
        var label = action === 'allow' ? 'Allowing' : action === 'queue' ? 'Queuing' : 'Declining';
        var note = cardEl ? cardEl.querySelector('.zero-request-note') : null;
        if (note) note.innerHTML = '<em>' + label + ' request…</em>';
        var btns = cardEl ? cardEl.querySelectorAll('.zero-request-actions button') : [];
        Array.prototype.forEach.call(btns, function (b) { b.disabled = true; });

        fetch('/api/zero_public/pending/' + reqId + '/decide', {
            method: 'POST',
            credentials: 'same-origin',
            headers: csrfHeaders(),
            body: JSON.stringify({ action: action }),
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.ok) {
                    _removeCard(reqId);
                    _pollPendingManual();
                } else {
                    Array.prototype.forEach.call(btns, function (b) { b.disabled = false; });
                    if (note) note.innerHTML = '<span style="color:#dc2626">Error — ' + escapeHtml(data.error || 'unknown error') + '</span>';
                }
            })
            .catch(function (err) {
                Array.prototype.forEach.call(btns, function (b) { b.disabled = false; });
                if (note) note.innerHTML = '<span style="color:#dc2626">Request failed: ' + escapeHtml(String(err)) + '</span>';
            });
    }

    // ── Gear item ──────────────────────────────────────────────────────────
    function _scrollToCards() {
        if (window.AgentZero && window.AgentZero.open) {
            try { window.AgentZero.open(); } catch (_) {}
        }
        var ids = Object.keys(_renderedIds);
        if (!ids.length) {
            _pollPendingManual();
            return;
        }
        var el = _renderedIds[ids[0]];
        if (el && el.scrollIntoView) el.scrollIntoView({ block: 'start', behavior: 'smooth' });
    }

    function _gearText(count) { return 'Pending requests (' + count + ')'; }

    function _updateGearLabel(count) {
        var text = _gearText(count);
        if (text === _gearLabel) return;
        _gearLabel = text;
        if (!UI) return;
        // No setGearLabel hook exists, so re-register the same id with the new
        // label and let the window replace it; also patch the live node if the
        // window renders the label as plain text.
        try { UI.registerGearItem(GEAR_ID, text, _scrollToCards, { dot: count > 0 }); } catch (_) {}
        if (UI.setGearDot) { try { UI.setGearDot(GEAR_ID, count > 0); } catch (_) {} }
    }

    // ── Boot ───────────────────────────────────────────────────────────────
    function start(ui) {
        UI = ui;
        injectStyles();
        try { UI.registerGearItem(GEAR_ID, _gearText(0), _scrollToCards, { dot: false }); } catch (_) {}
        _gearLabel = _gearText(0);
        if (UI.onOpen) {
            try { UI.onOpen(function () { _pollPendingManual(); }); } catch (_) {}
        }
        _startPendingPoll();
        window.addEventListener('beforeunload', function () {
            _stopPendingPoll();
            _stopBlinkLoop();
        });
    }

    function waitForUI() {
        var waited = 0;
        (function poll() {
            if (window.AgentZeroUI) { start(window.AgentZeroUI); return; }
            waited += HOOK_POLL_MS;
            if (waited >= HOOK_POLL_MAX_MS) return;   // new window not present — stay silent
            setTimeout(poll, HOOK_POLL_MS);
        })();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', waitForUI);
    } else {
        waitForUI();
    }
})();
