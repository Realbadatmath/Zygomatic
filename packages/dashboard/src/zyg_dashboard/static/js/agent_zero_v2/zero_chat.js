/**
 * Agent Zero v2 — the chat window.
 *
 * A Claude-Code-like panel for the dashboard: free-text conversation, streaming
 * assistant with markdown, collapsible tool-call cards, a model selector, a
 * sessions drawer, a budget pill and a keyboard-first composer. There are no
 * preset option buttons anywhere; everything is typed.
 *
 * Dependencies (plain globals, no bundler): zero_markdown.js and
 * zero_chat_transcript.js (window.ZeroMarkdown / window.ZeroTranscript) plus
 * static/css/agent_zero_v2.css, which ensureStylesheet() injects if the page did
 * not already link it. Backend: /api/zero/v2/*.
 *
 * Exports: window.AgentZero (user actions) and window.AgentZeroUI (hooks for the
 * sibling modules: model picker, request inbox, …).
 */
(function () {
    'use strict';

    var W = window;
    var API = '/api/zero/v2';
    var LS_SESSION = 'zero_v2_session';
    var MAX_TA_PX = 200;          // ~8 lines at the composer's line-height
    var SLASH = [
        { cmd: '/new', help: 'start a new chat' },
        { cmd: '/sessions', help: 'toggle the sessions drawer' },
        { cmd: '/model', help: 'pick the model' },
        { cmd: '/budget', help: 'show the token budget' },
        { cmd: '/clear', help: 'clear this view (local only)' },
        { cmd: '/help', help: 'list the commands' }
    ];

    function greetingText(name) {
        return 'Hi ' + String(name || 'there') + ', how can I help you?';
    }

    var S = {
        built: false,
        sessionId: null,
        sessionTitle: '',
        turnId: null,
        es: null,
        esRetry: 0,
        lastSeq: 0,
        streaming: false,
        msg: null,
        turnStart: 0,
        models: null,
        modelLabel: '',
        budget: null,
        lastUserText: '',
        pendingImage: null,
        badge: 0,
        maximised: false,
        gearItems: [],
        openCbs: [],
        sessionCbs: [],
        createPromise: null,
        recognition: null,
        listening: false,
        slashIdx: 0
    };

    var D = {};   // DOM handles

    // ------------------------------------------------------------------ utils
    /**
     * zero_chat_transcript.js is loaded AFTER this file, so the transcript root
     * cannot be handed over at build() time — do it on first use instead.
     */
    function T() {
        var t = W.ZeroTranscript;
        if (t && D.transcript && t.getRoot() !== D.transcript) t.setRoot(D.transcript);
        return t;
    }

    function el(tag, cls, text) {
        var n = document.createElement(tag);
        if (cls) n.className = cls;
        if (text != null) n.textContent = String(text);
        return n;
    }

    function btn(cls, text, title, onClick) {
        var b = el('button', cls, text);
        b.type = 'button';
        if (title) b.title = title;
        b.addEventListener('click', onClick);
        return b;
    }

    function csrfToken() {
        if (typeof W.getCsrfToken === 'function') {
            try { return W.getCsrfToken() || ''; } catch (_) { /* fall through */ }
        }
        var meta = document.querySelector('meta[name="csrf-token"]');
        return (meta && meta.getAttribute('content')) || '';
    }

    function api(method, path, body) {
        var opts = { method: method, credentials: 'same-origin', headers: {} };
        if (method !== 'GET') {
            opts.headers['X-CSRF-Token'] = csrfToken();
            if (body !== undefined) {
                opts.headers['Content-Type'] = 'application/json';
                opts.body = JSON.stringify(body);
            }
        }
        return fetch(API + path, opts).then(function (r) {
            return r.text().then(function (txt) {
                var data = {};
                if (txt) {
                    try { data = JSON.parse(txt); } catch (_) { data = { error: txt }; }
                }
                return { ok: r.ok, status: r.status, data: data || {} };
            });
        }).catch(function (err) {
            return { ok: false, status: 0, data: { error: String(err && err.message || err) } };
        });
    }

    function asArray(v) {
        if (!v) return [];
        if (Object.prototype.toString.call(v) === '[object Array]') return v;
        return [];
    }

    function sessionList(data) {
        return asArray(data.sessions).concat(asArray(data.items)).concat(asArray(data));
    }

    function sessionIdOf(data) {
        if (!data) return null;
        if (typeof data === 'string') return data;
        return data.id || data.session_id || (data.session && (data.session.id || data.session.session_id)) || null;
    }

    function pickNum(obj, names) {
        for (var i = 0; i < names.length; i++) {
            if (obj && obj[names[i]] != null && !isNaN(Number(obj[names[i]]))) return Number(obj[names[i]]);
        }
        return null;
    }

    function fmtNum(n) {
        var v = Number(n || 0);
        if (v >= 1000000) return Math.round(v / 100000) / 10 + 'M';
        if (v >= 1000) return Math.round(v / 100) / 10 + 'k';
        return String(Math.round(v));
    }

    function userName() {
        return W.DASHBOARD_USER_NAME || W.DASHBOARD_USER_ID || '';
    }

    function closePops() {
        var pops = document.querySelectorAll('.az-pop');
        for (var i = 0; i < pops.length; i++) {
            if (pops[i].parentNode) pops[i].parentNode.removeChild(pops[i]);
        }
    }

    function popover(anchor, build) {
        closePops();
        var pop = el('div', 'az-pop');
        build(pop, function () { closePops(); });
        document.body.appendChild(pop);
        var r = anchor.getBoundingClientRect();
        var left = Math.max(8, Math.min(r.left, W.innerWidth - pop.offsetWidth - 8));
        var top = r.bottom + 6;
        if (top + pop.offsetHeight > W.innerHeight - 8) top = Math.max(8, r.top - pop.offsetHeight - 6);
        pop.style.left = left + 'px';
        pop.style.top = top + 'px';
        setTimeout(function () {
            document.addEventListener('mousedown', function off(e) {
                if (pop.contains(e.target)) return;
                document.removeEventListener('mousedown', off);
                if (pop.parentNode) pop.parentNode.removeChild(pop);
            });
        }, 0);
        return pop;
    }

    function ensureStylesheet() {
        if (document.querySelector('link[href*="agent_zero_v2.css"]')) return;
        var link = el('link');
        link.rel = 'stylesheet';
        link.href = '/static/css/agent_zero_v2.css';
        document.head.appendChild(link);
    }

    // ------------------------------------------------------------------- DOM
    function buildHeader() {
        var h = el('div', 'az-header');
        h.appendChild(el('span', 'az-title', 'Zero'));

        D.sessTitle = el('span', 'az-session-title', 'New chat');
        D.sessTitle.title = 'Click to rename this chat';
        D.sessTitle.addEventListener('click', renamePrompt);
        h.appendChild(D.sessTitle);

        h.appendChild(btn('az-hbtn', 'New chat', 'Start a new chat', function () { newSession(); }));
        D.sessBtn = btn('az-hbtn', 'Sessions', 'Show saved chats', toggleDrawer);
        h.appendChild(D.sessBtn);
        D.modelBtn = btn('az-hbtn', 'Model', 'Choose the model', openModelPicker);
        h.appendChild(D.modelBtn);
        D.budgetPill = btn('az-budget-pill', 'budget', 'Token budget', openBudget);
        h.appendChild(D.budgetPill);
        D.gearBtn = btn('az-hbtn az-hbtn-icon', '⚙', 'Extras', openGear);
        h.appendChild(D.gearBtn);
        h.appendChild(btn('az-hbtn az-hbtn-icon', '⤢', 'Maximise (Ctrl+Shift+Z)', toggleMaximise));
        h.appendChild(btn('az-hbtn az-hbtn-icon', '–', 'Minimise (Esc)', minimize));
        h.appendChild(btn('az-hbtn az-hbtn-icon', '×', 'Close', close));

        h.addEventListener('mousedown', startDrag);
        return h;
    }

    function buildDrawer() {
        var d = el('div', 'az-drawer');
        d.appendChild(el('div', 'az-drawer-head', 'Chats'));
        D.sessList = el('div', 'az-drawer-list');
        d.appendChild(D.sessList);
        return d;
    }

    function buildComposer() {
        var c = el('div', 'az-composer');

        D.attachRow = el('div', 'az-attach-row');
        D.attachImg = el('img');
        D.attachImg.alt = 'attachment';
        D.attachRow.appendChild(D.attachImg);
        D.attachRow.appendChild(btn('az-btn', '× remove', 'Remove the attachment', clearAttachment));
        c.appendChild(D.attachRow);

        var row = el('div', 'az-input-row');
        D.fileInput = el('input');
        D.fileInput.type = 'file';
        D.fileInput.accept = 'image/*';
        D.fileInput.style.display = 'none';
        D.fileInput.addEventListener('change', function () {
            if (D.fileInput.files && D.fileInput.files[0]) readImage(D.fileInput.files[0]);
            D.fileInput.value = '';
        });
        row.appendChild(D.fileInput);
        row.appendChild(btn('az-cbtn', '📎', 'Attach an image', function () { D.fileInput.click(); }));

        D.ta = el('textarea', 'az-textarea');
        D.ta.placeholder = 'Ask Zero anything…  (Enter to send, Shift+Enter for a newline, / for commands)';
        D.ta.rows = 1;
        D.ta.addEventListener('input', onInput);
        D.ta.addEventListener('keydown', onComposerKey);
        D.ta.addEventListener('paste', onPaste);
        row.appendChild(D.ta);

        D.micBtn = btn('az-cbtn', '🎤', 'Hold to talk', function () {});
        D.micBtn.addEventListener('mousedown', startListening);
        D.micBtn.addEventListener('mouseup', stopListening);
        D.micBtn.addEventListener('mouseleave', stopListening);
        row.appendChild(D.micBtn);

        D.sendBtn = btn('az-cbtn az-send', 'Send', 'Send (Enter)', onSendClick);
        row.appendChild(D.sendBtn);
        c.appendChild(row);

        var hint = el('div', 'az-hint');
        D.hintLeft = el('span', null, 'Enter sends · Shift+Enter newline · / commands');
        D.hintRight = el('span', 'az-hint-right', '');
        hint.appendChild(D.hintLeft);
        hint.appendChild(D.hintRight);
        c.appendChild(hint);
        return c;
    }

    function buildTab() {
        var tab = el('div');
        tab.id = 'agent-zero-minimized';
        tab.appendChild(el('span', 'az-tab-label', 'Zero'));
        D.badge = el('span', 'az-tab-badge', '0');
        tab.appendChild(D.badge);
        tab.addEventListener('click', function () { open(); });
        makeTabDraggable(tab);
        return tab;
    }

    function build() {
        if (S.built) return;
        S.built = true;
        ensureStylesheet();

        D.overlay = el('div');
        D.overlay.id = 'agent-zero-overlay';
        D.overlay.addEventListener('mousedown', function (e) {
            if (e.target === D.overlay) minimize();
        });

        D.win = el('div');
        D.win.id = 'agent-zero-window';
        D.win.appendChild(buildHeader());

        var body = el('div', 'az-body');
        D.drawer = buildDrawer();
        body.appendChild(D.drawer);

        var main = el('div', 'az-main');
        D.transcript = el('div', 'az-transcript');
        main.appendChild(D.transcript);
        main.appendChild(buildComposer());
        body.appendChild(main);
        D.win.appendChild(body);

        D.overlay.appendChild(D.win);
        document.body.appendChild(D.overlay);

        D.tab = buildTab();
        document.body.appendChild(D.tab);
        setVisible(false, false);

        centerWindow();
        bindDropZone();
        refreshModels();
        refreshBudget();
    }

    function centerWindow() {
        var w = Math.min(960, W.innerWidth - 40);
        var h = Math.min(700, W.innerHeight - 40);
        D.win.style.width = w + 'px';
        D.win.style.height = h + 'px';
        D.win.style.left = Math.max(20, Math.round((W.innerWidth - w) / 2)) + 'px';
        D.win.style.top = Math.max(20, Math.round((W.innerHeight - h) / 2)) + 'px';
    }

    // ------------------------------------------------------- drag / maximise
    function startDrag(e) {
        if (e.target.closest('button') || e.target === D.sessTitle) return;
        if (S.maximised) return;
        var r = D.win.getBoundingClientRect();
        var ox = e.clientX - r.left;
        var oy = e.clientY - r.top;
        e.preventDefault();

        function move(ev) {
            var left = Math.max(0, Math.min(W.innerWidth - r.width, ev.clientX - ox));
            var top = Math.max(0, Math.min(W.innerHeight - 40, ev.clientY - oy));
            D.win.style.left = left + 'px';
            D.win.style.top = top + 'px';
        }
        function up() {
            document.removeEventListener('mousemove', move);
            document.removeEventListener('mouseup', up);
            document.body.style.userSelect = '';
        }
        document.body.style.userSelect = 'none';
        document.addEventListener('mousemove', move);
        document.addEventListener('mouseup', up);
    }

    function makeTabDraggable(tabEl) {
        tabEl.addEventListener('mousedown', function (e) {
            if (e.button !== 0) return;
            var r = tabEl.getBoundingClientRect();
            var startX = e.clientX;
            var startLeft = r.left;
            var moved = false;

            function move(ev) {
                if (!moved && Math.abs(ev.clientX - startX) < 5) return;
                moved = true;
                var left = Math.max(0, Math.min(W.innerWidth - r.width, startLeft + (ev.clientX - startX)));
                tabEl.style.left = left + 'px';
                tabEl.style.transform = 'none';
            }
            function up() {
                document.removeEventListener('mousemove', move);
                document.removeEventListener('mouseup', up);
                document.body.style.userSelect = '';
            }
            document.body.style.userSelect = 'none';
            document.addEventListener('mousemove', move);
            document.addEventListener('mouseup', up);
        });
    }

    function toggleMaximise() {
        build();
        S.maximised = !S.maximised;
        D.win.classList.toggle('az-maximised', S.maximised);
        if (!S.maximised) centerWindow();
    }

    // ----------------------------------------------------------- open/close
    /**
     * The window's visibility is carried by BOTH a class (for the stylesheet) and
     * an inline display value, because the iframe hotkey bridge in
     * templates/enhanced_dashboard.html tests `overlay.style.display === 'flex'`
     * and `minimized.style.display !== 'none'`. Keep the two in sync.
     */
    function setVisible(overlayOn, tabOn) {
        D.overlay.classList.toggle('az-open', overlayOn);
        D.overlay.style.display = overlayOn ? 'flex' : 'none';
        D.tab.classList.toggle('az-open', tabOn);
        D.tab.style.display = tabOn ? 'inline-flex' : 'none';
    }

    function open() {
        build();
        setVisible(true, false);
        if (!S.sessionId) {
            var stored = null;
            try { stored = localStorage.getItem(LS_SESSION); } catch (_) { stored = null; }
            if (stored) loadSession(stored);
            else newSession(true);
        }
        setTimeout(function () { if (D.ta) D.ta.focus(); }, 30);
        S.openCbs.forEach(function (cb) { try { cb(); } catch (_) {} });
    }

    function close() {
        if (!S.built) return;
        setVisible(false, false);
        closePops();
        hideSlash();
    }

    function minimize() {
        build();
        setVisible(false, true);
        closePops();
        hideSlash();
    }

    function toggle() {
        build();
        if (D.overlay.classList.contains('az-open')) minimize();
        else open();
    }

    function isOpen() {
        return S.built && D.overlay.classList.contains('az-open');
    }

    // -------------------------------------------------------------- sessions
    function setSessionTitle(title) {
        S.sessionTitle = title || 'New chat';
        if (D.sessTitle) D.sessTitle.textContent = S.sessionTitle;
    }

    function rememberSession(id) {
        S.sessionId = id || null;
        try {
            if (id) localStorage.setItem(LS_SESSION, id);
            else localStorage.removeItem(LS_SESSION);
        } catch (_) { /* private mode */ }
        S.sessionCbs.forEach(function (cb) { try { cb(id); } catch (_) {} });
    }

    function showGreeting() {
        var name = userName();
        if (name) {
            T().greeting(greetingText(name));
            return;
        }
        api('GET', '/greeting').then(function (res) {
            var g = res.ok && (res.data.greeting || res.data.text);
            T().greeting(g || greetingText(res.data && res.data.name));
        });
    }

    /**
     * One in-flight create at a time: opening the window kicks a create off and
     * the user can hit Enter before it lands — without this both would POST.
     */
    function createSession() {
        if (S.createPromise) return S.createPromise;
        S.createPromise = api('POST', '/sessions', {}).then(function (res) {
            S.createPromise = null;
            if (!res.ok) {
                T().banner('error', 'Could not create a chat: ' + (res.data.error || res.status), []);
                return null;
            }
            var id = sessionIdOf(res.data);
            rememberSession(id);
            if (res.data && res.data.title) setSessionTitle(res.data.title);
            refreshSessions();
            return id;
        });
        return S.createPromise;
    }

    function newSession(quiet) {
        build();
        stopStream();
        S.createPromise = null;
        rememberSession(null);
        setSessionTitle('New chat');
        T().clear();
        showGreeting();
        if (!quiet && D.ta) D.ta.focus();
        return createSession();
    }

    function ensureSession() {
        if (S.sessionId) return Promise.resolve(S.sessionId);
        return createSession();
    }

    function loadSession(id) {
        build();
        stopStream();
        return api('GET', '/sessions/' + encodeURIComponent(id)).then(function (res) {
            if (!res.ok) {
                rememberSession(null);
                T().clear();
                setSessionTitle('New chat');
                showGreeting();
                return;
            }
            var s = res.data.session || res.data;
            rememberSession(sessionIdOf(s) || id);
            setSessionTitle(s.title);
            T().clear();
            var messages = asArray(s.messages);
            if (!messages.length) showGreeting();
            else T().renderMessages(messages);
            refreshSessions();
        });
    }

    function renamePrompt() {
        if (!S.sessionId) return;
        var next = W.prompt('Rename this chat', S.sessionTitle || '');
        if (next == null) return;
        setSessionTitle(next.trim() || 'New chat');
        api('POST', '/sessions/' + encodeURIComponent(S.sessionId) + '/rename', { title: S.sessionTitle })
            .then(refreshSessions);
    }

    function toggleDrawer() {
        build();
        var on = D.drawer.classList.toggle('az-open');
        D.sessBtn.classList.toggle('az-on', on);
        if (on) refreshSessions();
    }

    function sessionRow(s) {
        var id = sessionIdOf(s);
        var row = el('div', 'az-sess' + (id === S.sessionId ? ' az-cur' : ''));
        var main = el('div', 'az-sess-main');
        main.appendChild(el('div', 'az-sess-title', s.title || 'Untitled chat'));
        var meta = [];
        if (s.updated_at || s.updated) meta.push(String(s.updated_at || s.updated).replace('T', ' ').slice(0, 16));
        var turns = s.turns != null ? s.turns : s.turn_count;
        if (turns != null) meta.push(turns + ' turns');
        main.appendChild(el('div', 'az-sess-meta', meta.join(' · ')));
        main.addEventListener('click', function () { loadSession(id); });
        row.appendChild(main);
        row.appendChild(btn('az-sess-del', '×', 'Delete this chat', function (e) {
            e.stopPropagation();
            if (!W.confirm('Delete "' + (s.title || 'Untitled chat') + '"?')) return;
            api('DELETE', '/sessions/' + encodeURIComponent(id)).then(function () {
                if (id === S.sessionId) newSession(true);
                refreshSessions();
            });
        }));
        return row;
    }

    function refreshSessions() {
        if (!S.built || !D.drawer.classList.contains('az-open')) return;
        api('GET', '/sessions').then(function (res) {
            D.sessList.textContent = '';
            var list = res.ok ? sessionList(res.data) : [];
            if (!list.length) {
                D.sessList.appendChild(el('div', 'az-empty', 'No saved chats yet.'));
                return;
            }
            list.forEach(function (s) { D.sessList.appendChild(sessionRow(s)); });
        });
    }

    // ---------------------------------------------------------------- models
    function modelLabelFrom(data) {
        var sel = data.selected;
        var providers = asArray(data.providers);
        var wantModel = typeof sel === 'string' ? sel : (sel && (sel.model || sel.id)) || '';
        var wantProv = (sel && sel.provider) || '';
        for (var i = 0; i < providers.length; i++) {
            var p = providers[i];
            if (wantProv && p.id !== wantProv) continue;
            var models = asArray(p.models);
            for (var j = 0; j < models.length; j++) {
                if (models[j].id === wantModel) {
                    return (models[j].label || models[j].id) + ' · ' + (p.kind || p.label || p.id);
                }
            }
        }
        if (wantModel) return String(wantModel) + (wantProv ? ' · ' + wantProv : '');
        return 'Model';
    }

    function setModelLabel(text) {
        S.modelLabel = text || 'Model';
        if (D.modelBtn) D.modelBtn.textContent = S.modelLabel;
    }

    function refreshModels() {
        return api('GET', '/models').then(function (res) {
            if (!res.ok) {
                setModelLabel('Model');
                return null;
            }
            S.models = res.data;
            setModelLabel(modelLabelFrom(res.data));
            return res.data;
        });
    }

    function selectModel(providerId, modelId) {
        return api('POST', '/models/select', { provider: providerId, model: modelId }).then(function (res) {
            if (!res.ok) T().toast('Could not switch model (' + res.status + ')');
            return refreshModels();
        });
    }

    function modelFallbackPopover(anchor) {
        popover(anchor, function (pop, dismiss) {
            pop.appendChild(el('h4', null, 'Model'));
            var sel = el('select');
            var providers = asArray(S.models && S.models.providers);
            if (!providers.length) {
                pop.appendChild(el('div', 'az-empty', 'No providers reported.'));
                return;
            }
            providers.forEach(function (p) {
                var group = el('optgroup');
                group.label = (p.label || p.id) + (p.status ? ' (' + p.status + ')' : '');
                asArray(p.models).forEach(function (m) {
                    var opt = el('option', null,
                        (m.label || m.id) + (m.installed === false ? ' — not installed' : '') +
                        (m.fit ? ' · ' + m.fit : ''));
                    opt.value = p.id + '\u0000' + m.id;
                    group.appendChild(opt);
                });
                sel.appendChild(group);
            });
            sel.addEventListener('change', function () {
                var bits = sel.value.split('\u0000');
                dismiss();
                selectModel(bits[0], bits[1]);
            });
            pop.appendChild(sel);
            if (S.models && S.models.machine) {
                var m = S.models.machine;
                pop.appendChild(el('div', 'az-pop-hint',
                    [m.gpu, m.vram_gb != null ? m.vram_gb + ' GB VRAM' : null].filter(Boolean).join(' · ')));
            }
        });
    }

    function openModelPicker() {
        if (W.AgentZeroModels && typeof W.AgentZeroModels.open === 'function') {
            W.AgentZeroModels.open(D.modelBtn);
            return;
        }
        if (!S.models) {
            refreshModels().then(function () { modelFallbackPopover(D.modelBtn); });
            return;
        }
        modelFallbackPopover(D.modelBtn);
    }

    // ---------------------------------------------------------------- budget
    function budgetBlocked(b) {
        var st = (b && b.state) || {};
        return st.blocked === true || st.state === 'blocked' || st.status === 'blocked';
    }

    function renderBudgetPill() {
        if (!D.budgetPill) return;
        var b = S.budget || {};
        var st = b.state || {};
        var cfg = b.config || {};
        var day = pickNum(st, ['day_tokens', 'tokens_today', 'today_tokens', 'day_total_tokens']);
        var cap = pickNum(cfg, ['day_hard_cap_tokens', 'hard_cap_tokens', 'day_token_cap', 'day_tokens_hard']);
        var week = pickNum(st, ['week_pct', 'week_percent', 'week_used_pct']);
        var bits = [];
        if (day != null) bits.push(fmtNum(day) + (cap != null ? '/' + fmtNum(cap) : ''));
        if (week != null) bits.push('wk ' + Math.round(week) + '%');
        D.budgetPill.textContent = bits.length ? bits.join(' · ') : 'budget';
        D.budgetPill.classList.toggle('az-blocked', budgetBlocked(b));
    }

    function refreshBudget() {
        return api('GET', '/budget').then(function (res) {
            if (res.ok) S.budget = res.data;
            renderBudgetPill();
            return S.budget;
        });
    }

    function overrideBudget(turns) {
        return api('POST', '/budget/override', { turns: turns || 10 }).then(function (res) {
            if (!res.ok) T().toast('Override refused (' + res.status + ')');
            return refreshBudget();
        });
    }

    function openBudget() {
        refreshBudget().then(function () {
            popover(D.budgetPill, function (pop, dismiss) {
                pop.appendChild(el('h4', null, 'Token budget'));
                var b = S.budget || {};
                if (b.doc) pop.appendChild(el('div', 'az-pop-hint', String(b.doc)));
                pop.appendChild(el('pre', 'az-tool-pre', JSON.stringify(b.state || {}, null, 2)));
                var blocked = budgetBlocked(b);
                var row = btn('az-btn az-btn-primary', 'Allow 10 more turns',
                    blocked ? 'Raise the cap for 10 turns' : 'Only available while the budget blocks turns',
                    function () { dismiss(); overrideBudget(10); });
                row.disabled = !blocked;
                pop.appendChild(row);
            });
        });
    }

    // ------------------------------------------------------------ gear menu
    function openGear() {
        popover(D.gearBtn, function (pop, dismiss) {
            pop.appendChild(el('h4', null, 'Extras'));
            if (!S.gearItems.length) {
                pop.appendChild(el('div', 'az-empty', 'Nothing registered yet.'));
                return;
            }
            S.gearItems.forEach(function (item) {
                var row = btn('az-pop-row', item.label + (item.dot ? ' •' : ''), '', function () {
                    dismiss();
                    try { item.onClick(); } catch (err) { T().toast('Failed: ' + err.message); }
                });
                row.dataset.gearId = item.id;
                pop.appendChild(row);
            });
        });
    }

    // ------------------------------------------------------------- composer
    function autoGrow() {
        D.ta.style.height = 'auto';
        D.ta.style.height = Math.min(D.ta.scrollHeight, MAX_TA_PX) + 'px';
    }

    function clearAttachment() {
        S.pendingImage = null;
        D.attachRow.classList.remove('az-open');
        D.attachImg.removeAttribute('src');
    }

    function readImage(file) {
        if (!file || !/^image\//.test(file.type)) return;
        var fr = new FileReader();
        fr.onload = function () {
            var url = String(fr.result || '');
            S.pendingImage = url.replace(/^data:[^,]*,/, '');
            D.attachImg.src = url;
            D.attachRow.classList.add('az-open');
        };
        fr.readAsDataURL(file);
    }

    function onPaste(e) {
        var items = (e.clipboardData && e.clipboardData.items) || [];
        for (var i = 0; i < items.length; i++) {
            if (items[i].kind === 'file' && /^image\//.test(items[i].type)) {
                readImage(items[i].getAsFile());
                e.preventDefault();
                return;
            }
        }
    }

    function bindDropZone() {
        ['dragenter', 'dragover'].forEach(function (t) {
            D.win.addEventListener(t, function (e) {
                e.preventDefault();
                D.win.classList.add('az-drop');
            });
        });
        ['dragleave', 'drop'].forEach(function (t) {
            D.win.addEventListener(t, function (e) {
                e.preventDefault();
                D.win.classList.remove('az-drop');
                if (t === 'drop' && e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) {
                    readImage(e.dataTransfer.files[0]);
                }
            });
        });
    }

    // --- speech (ported from dashboard_agent_zero.js) -----------------------
    function initSpeechRecognition() {
        if (S.recognition) return;
        if (!('webkitSpeechRecognition' in W) && !('SpeechRecognition' in W)) return;
        var Rec = W.SpeechRecognition || W.webkitSpeechRecognition;
        var rec = new Rec();
        rec.continuous = true;
        rec.interimResults = true;
        rec.lang = 'en-US';
        rec.onresult = function (e) {
            var last = e.results.length - 1;
            var transcript = e.results[last][0].transcript;
            if (e.results[last].isFinal && transcript && D.ta) {
                D.ta.value = (D.ta.value + ' ' + transcript).trim();
                autoGrow();
            }
        };
        S.recognition = rec;
    }

    function startListening() {
        initSpeechRecognition();
        if (!S.recognition || S.listening) return;
        try {
            S.recognition.start();
            S.listening = true;
            D.micBtn.classList.add('az-listening');
            D.micBtn.title = 'Listening… release to stop';
        } catch (_) { /* already started */ }
    }

    function stopListening() {
        if (!S.recognition || !S.listening) return;
        try { S.recognition.stop(); } catch (_) {}
        S.listening = false;
        D.micBtn.classList.remove('az-listening');
        D.micBtn.title = 'Hold to talk';
    }

    // --- slash command popup ----------------------------------------------
    function slashMatches() {
        var v = D.ta.value;
        if (v.charAt(0) !== '/' || /\s/.test(v)) return [];
        return SLASH.filter(function (c) { return c.cmd.indexOf(v) === 0; });
    }

    function hideSlash() {
        if (D.slashPop && D.slashPop.parentNode) D.slashPop.parentNode.removeChild(D.slashPop);
        D.slashPop = null;
    }

    function showSlash() {
        var items = slashMatches();
        hideSlash();
        if (!items.length) return;
        if (S.slashIdx >= items.length) S.slashIdx = 0;
        var pop = el('div', 'az-pop az-slash');
        items.forEach(function (c, i) {
            var row = el('div', 'az-pop-row' + (i === S.slashIdx ? ' az-sel' : ''));
            row.appendChild(document.createTextNode(c.cmd));
            row.appendChild(el('span', 'az-pop-hint', c.help));
            row.addEventListener('mousedown', function (e) {
                e.preventDefault();
                runSlash(c.cmd);
            });
            pop.appendChild(row);
        });
        document.body.appendChild(pop);
        var r = D.ta.getBoundingClientRect();
        pop.style.left = r.left + 'px';
        pop.style.top = Math.max(8, r.top - pop.offsetHeight - 6) + 'px';
        D.slashPop = pop;
    }

    function runSlash(cmd) {
        hideSlash();
        D.ta.value = '';
        autoGrow();
        if (cmd === '/new') { newSession(); return true; }
        if (cmd === '/sessions') { toggleDrawer(); return true; }
        if (cmd === '/model') { openModelPicker(); return true; }
        if (cmd === '/budget') { openBudget(); return true; }
        if (cmd === '/clear') { T().clear(); showGreeting(); return true; }
        if (cmd === '/help') {
            T().banner('info', SLASH.map(function (c) { return c.cmd + ' — ' + c.help; }).join('   ·   '), []);
            return true;
        }
        return false;
    }

    function onInput() {
        autoGrow();
        S.slashIdx = 0;
        if (D.ta.value.charAt(0) === '/') showSlash();
        else hideSlash();
    }

    function onComposerKey(e) {
        var items = slashMatches();
        if (D.slashPop && items.length) {
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault();
                S.slashIdx = (S.slashIdx + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length;
                showSlash();
                return;
            }
            if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)) {
                e.preventDefault();
                runSlash(items[S.slashIdx].cmd);
                return;
            }
            if (e.key === 'Escape') {
                e.preventDefault();
                hideSlash();
                return;
            }
        }
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            submit();
        }
    }

    function onSendClick() {
        if (S.streaming) cancelTurn();
        else submit();
    }

    function setStreaming(on) {
        S.streaming = on;
        if (!D.sendBtn) return;
        D.sendBtn.textContent = on ? 'Stop' : 'Send';
        D.sendBtn.classList.toggle('az-stop', on);
        D.sendBtn.title = on ? 'Stop this turn' : 'Send (Enter)';
        D.hintRight.textContent = '';
        if (on) {
            var sp = el('span', 'az-spinner');
            D.hintRight.appendChild(sp);
            D.hintRight.appendChild(document.createTextNode(' thinking…'));
        }
    }

    function submit() {
        var text = D.ta.value.trim();
        if (!text && !S.pendingImage) return;
        if (text.charAt(0) === '/' && !/\s/.test(text) && runSlash(text)) return;
        D.ta.value = '';
        autoGrow();
        hideSlash();
        send(text);
    }

    // ------------------------------------------------------------ turn/stream
    function stopStream() {
        if (S.es) {
            try { S.es.close(); } catch (_) {}
            S.es = null;
        }
        S.turnId = null;
        S.lastSeq = 0;
        S.esRetry = 0;
        if (S.msg && T()) T().finish(S.msg);
        S.msg = null;
        setStreaming(false);
    }

    function cancelTurn() {
        if (!S.turnId) { setStreaming(false); return; }
        var id = S.turnId;
        api('POST', '/turns/' + encodeURIComponent(id) + '/cancel', {}).then(function () {
            T().toast('Turn cancelled');
        });
        stopStream();
    }

    function onDone(payload) {
        var msg = S.msg;
        if (msg && T()) T().finish(msg);
        if (S.es) { try { S.es.close(); } catch (_) {} S.es = null; }
        S.turnId = null;
        S.msg = null;
        setStreaming(false);
        if (payload && payload.stop_reason === 'max_tool_calls') {
            T().banner('warn', 'Stopped: the tool-call limit for one turn was reached.', []);
        }
        refreshBudget();
        refreshSessions();
    }

    function onConfirm(payload) {
        var msg = S.msg;
        T().confirmCard(msg, payload, function (approve) {
            api('POST', '/sessions/' + encodeURIComponent(S.sessionId) + '/confirm',
                { confirm_id: payload.confirm_id, approve: !!approve }).then(function (res) {
                if (!res.ok) {
                    T().banner('error', 'Confirm failed: ' + (res.data.error || res.status), []);
                    return;
                }
                var tid = res.data.turn_id;
                if (!tid) { setStreaming(false); return; }
                // The continuation streams into a NEW assistant message.
                S.msg = T().addAssistant();
                startStream(tid, S.msg);
            });
        });
    }

    function onError(payload) {
        var kind = (payload && payload.kind) || 'backend';
        T().banner(kind === 'budget' ? 'budget' : 'error',
            (payload && payload.message) || 'The turn failed.',
            [{ label: 'Retry', primary: true, once: true, onClick: retryLast }]);
        onDone(null);
    }

    function retryLast() {
        if (!S.lastUserText) return;
        send(S.lastUserText, true);
    }

    function onEvent(type, ev) {
        var payload = {};
        if (ev && ev.data) {
            try { payload = JSON.parse(ev.data); } catch (_) { payload = { text: ev.data }; }
        }
        if (ev && ev.lastEventId) {
            var seq = Number(ev.lastEventId);
            if (!isNaN(seq)) S.lastSeq = seq;
        }
        S.esRetry = 0;
        var msg = S.msg;
        if (type === 'text_delta') T().appendDelta(msg, payload.text);
        else if (type === 'thinking') T().appendThinking(msg, payload.text);
        else if (type === 'tool_call') T().toolCall(msg, payload);
        else if (type === 'tool_result') T().toolResult(msg, payload);
        else if (type === 'usage') T().usageLine(msg, payload, Date.now() - S.turnStart);
        else if (type === 'confirm') onConfirm(payload);
        else if (type === 'error') onError(payload);
        else if (type === 'done') onDone(payload);
    }

    function startStream(turnId, msg) {
        if (S.es) { try { S.es.close(); } catch (_) {} S.es = null; }
        S.turnId = turnId;
        S.msg = msg;
        S.turnStart = S.turnStart || Date.now();
        setStreaming(true);
        connectStream();
    }

    function connectStream() {
        var url = API + '/turns/' + encodeURIComponent(S.turnId) + '/events?from=' + S.lastSeq;
        var es;
        try {
            es = new EventSource(url, { withCredentials: true });
        } catch (err) {
            T().banner('error', 'Cannot open the event stream: ' + err.message, []);
            setStreaming(false);
            return;
        }
        S.es = es;
        ['text_delta', 'thinking', 'tool_call', 'tool_result', 'usage', 'confirm', 'error', 'done']
            .forEach(function (t) {
                es.addEventListener(t, function (ev) { onEvent(t, ev); });
            });
        es.onerror = function () {
            if (!S.streaming || S.es !== es) return;
            try { es.close(); } catch (_) {}
            S.es = null;
            S.esRetry += 1;
            if (S.esRetry > 5) {
                T().banner('error', 'Lost the connection to the turn stream.',
                    [{ label: 'Retry', primary: true, once: true, onClick: retryLast }]);
                setStreaming(false);
                return;
            }
            setTimeout(function () {
                if (S.streaming && S.turnId) connectStream();
            }, 500 * S.esRetry);
        };
    }

    function budgetBanner(data) {
        var msg = (data && data.error) || 'The token budget is exhausted.';
        T().banner('budget', msg, [
            { label: 'Allow 10 more turns', primary: true, once: true, onClick: function () { overrideBudget(10); } },
            { label: 'Details', onClick: openBudget }
        ]);
        S.budget = (data && data.budget) ? { state: data.budget } : S.budget;
        renderBudgetPill();
    }

    function send(text, isRetry) {
        build();
        if (S.streaming) {
            T().toast('a turn is still running');
            return Promise.resolve(null);
        }
        var body = { message: String(text == null ? '' : text) };
        var image = S.pendingImage;
        if (image) body.image_b64 = image;
        S.lastUserText = body.message;
        var greet = D.transcript.querySelector('.az-greeting');
        if (greet && greet.parentNode) greet.parentNode.removeChild(greet);
        if (!isRetry) T().addUser(body.message, image);
        clearAttachment();
        setStreaming(true);
        S.turnStart = Date.now();

        return ensureSession().then(function (sid) {
            if (!sid) {
                setStreaming(false);
                T().banner('error', 'No chat session — the backend refused to create one.', []);
                return null;
            }
            return api('POST', '/sessions/' + encodeURIComponent(sid) + '/turn', body).then(function (res) {
                if (res.status === 429) {
                    setStreaming(false);
                    budgetBanner(res.data);
                    return null;
                }
                if (res.status === 409) {
                    setStreaming(false);
                    T().toast('a turn is still running');
                    return null;
                }
                if (!res.ok || !res.data.turn_id) {
                    setStreaming(false);
                    T().banner('error', 'Could not start the turn: ' + (res.data.error || res.status),
                        [{ label: 'Retry', primary: true, once: true, onClick: retryLast }]);
                    return null;
                }
                S.msg = T().addAssistant();
                startStream(res.data.turn_id, S.msg);
                return res.data.turn_id;
            });
        });
    }

    // ------------------------------------------------------------- keyboard
    function typingTarget(target) {
        if (!target) return false;
        var tag = (target.tagName || '').toUpperCase();
        return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable === true;
    }

    function initHotkeys() {
        document.addEventListener('keydown', function (e) {
            if (e.ctrlKey && e.shiftKey && (e.key === 'Z' || e.key === 'z')) {
                e.preventDefault();
                if (!isOpen()) open();
                toggleMaximise();
                return;
            }
            if (e.key === 'Escape' && isOpen()) {
                if (D.slashPop) { hideSlash(); return; }
                minimize();
                return;
            }
            if (e.ctrlKey || e.metaKey || e.altKey) return;
            if (!e.key || e.key.toLowerCase() !== 'z') return;
            if (typingTarget(e.target || document.activeElement)) return;
            e.preventDefault();
            toggle();
        });
    }

    function initSidebarButton() {
        var b = document.getElementById('dashboard-sidebar-agent-zero');
        if (!b) return;
        b.style.display = '';
        if (b.dataset.azV2Bound) return;
        b.dataset.azV2Bound = '1';
        b.addEventListener('click', function () { open(); });
    }

    // -------------------------------------------------------------- exports
    function setBadge(count) {
        build();
        S.badge = Math.max(0, Number(count) || 0);
        D.badge.textContent = String(S.badge);
        D.badge.classList.toggle('az-open', S.badge > 0);
        D.tab.classList.toggle('az-alert', S.badge > 0);
    }

    window.AgentZero = {
        open: open,
        close: close,
        toggle: toggle,
        minimize: minimize,
        send: function (text) { return send(text); },
        newSession: function () { return newSession(); },
        loadSession: function (id) { return loadSession(id); },
        currentSession: function () {
            return { id: S.sessionId, title: S.sessionTitle, streaming: S.streaming };
        }
    };

    window.AgentZeroUI = {
        registerGearItem: function (id, label, onClick, opts) {
            var o = opts || {};
            var existing = S.gearItems.filter(function (i) { return i.id === id; })[0];
            if (existing) {
                existing.label = label;
                existing.onClick = onClick;
                existing.dot = !!o.dot;
                return;
            }
            S.gearItems.push({ id: id, label: label, onClick: onClick, dot: !!o.dot });
        },
        setGearDot: function (id, on) {
            S.gearItems.forEach(function (i) { if (i.id === id) i.dot = !!on; });
            if (D.gearBtn) D.gearBtn.classList.toggle('az-hbtn-dot', S.gearItems.some(function (i) { return i.dot; }));
        },
        appendSystemCard: function (html, opts) {
            build();
            return T().systemCard(html, opts);
        },
        removeSystemCard: function (id) {
            if (T()) T().removeSystemCard(id);
        },
        setBadge: setBadge,
        onOpen: function (cb) { if (typeof cb === 'function') S.openCbs.push(cb); },
        onSessionChange: function (cb) { if (typeof cb === 'function') S.sessionCbs.push(cb); },
        getWindowEl: function () { build(); return D.win; },
        getTranscriptEl: function () { build(); return D.transcript; },
        setModelLabel: setModelLabel,
        refreshModels: refreshModels
    };

    function init() {
        build();
        initHotkeys();
        initSidebarButton();
        W.addEventListener('resize', function () {
            if (!S.built || S.maximised) return;
            var r = D.win.getBoundingClientRect();
            if (r.right > W.innerWidth || r.bottom > W.innerHeight) centerWindow();
        });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
}());
