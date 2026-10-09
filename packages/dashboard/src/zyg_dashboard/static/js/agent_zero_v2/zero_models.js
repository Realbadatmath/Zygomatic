/**
 * Agent Zero v2 — "Select Model" picker.
 *
 * One anchored dropdown panel listing every LLM the operator can use, grouped by how it is
 * paid for: Subscription (the Claude Code login), API (provider keys) and Local (Ollama on
 * this machine). Shows live per-provider status, a search box, inline API-key entry, and for
 * a local model that is not installed a confirmation dialog with the requirements measured
 * against this machine, followed by an auto-download with a progress bar.
 *
 * Public API: window.AgentZeroModels = { open(anchorEl), close(), refresh(), current() }.
 * Host hooks (task 10): window.AgentZeroUI.setModelLabel(text) / .refreshModels().
 * If those hooks are missing the panel still works: it attaches to document.body and logs once.
 *
 * Backend (agent_zero/routes_models.py):
 *   GET    /api/zero/v2/models
 *   POST   /api/zero/v2/models/select            {provider, model}
 *   POST   /api/zero/v2/models/install           {model, confirm:true} -> 202 {job_id}
 *   GET    /api/zero/v2/models/install/<job_id>  -> {status, status_text, pct, total, completed, error}
 *   POST   /api/zero/v2/providers/<id>/key       {key}
 *   DELETE /api/zero/v2/providers/<id>/key
 *
 * Vanilla JS IIFE. No inline handlers (event delegation only), every interpolated value escaped.
 */
(function () {
    'use strict';

    // ── constants ──────────────────────────────────────────────────────────────
    var API = '/api/zero/v2';
    var CACHE_MS = 20000;          // provider chips refresh on open, cached 20 s
    var POLL_MS = 1500;            // install job poll interval
    var PANEL_W = 420;
    var DISK_HEADROOM_GB = 2;      // install needs download size + 2 GB free

    // ── module state ───────────────────────────────────────────────────────────
    var _data = null;              // last GET /models payload
    var _fetchedAt = 0;
    var _panel = null;             // panel root element
    var _anchor = null;            // the Model button we hang under
    var _search = '';
    var _expanded = {};            // providerId -> bool (API group chevrons)
    var _keyEditor = null;         // providerId whose key editor is open
    var _rowError = {};            // providerId|model -> inline error text
    var _selected = null;          // {provider, model}
    var _dialog = null;            // install dialog root
    var _dialogCtx = null;         // {provider, model, jobId, phase}
    var _pollTimer = null;
    var _inflight = null;          // in-flight GET promise (dedupe)
    var _hookWarned = false;
    var _docBound = false;

    // ── small helpers ──────────────────────────────────────────────────────────
    var ESC_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

    function esc(value) {
        return String(value === null || value === undefined ? '' : value).replace(/[&<>"']/g, function (c) {
            return ESC_MAP[c];
        });
    }

    function num(value) {
        var n = parseFloat(value);
        return isFinite(n) ? n : 0;
    }

    function fmtGb(value) {
        var n = num(value);
        if (n >= 100) return String(Math.round(n));
        return (Math.round(n * 10) / 10).toFixed(1).replace(/\.0$/, '');
    }

    function log(message) {
        if (window.console && console.warn) console.warn('[zero_models] ' + message);
    }

    function getCsrf() {
        if (typeof window.getCsrfToken === 'function') {
            try { return window.getCsrfToken() || ''; } catch (e) { /* fall through */ }
        }
        var el = document.getElementById('csrf-token');
        if (el) return el.value || el.getAttribute('data-csrf') || '';
        var meta = document.querySelector('meta[name="csrf-token"]');
        if (meta) return meta.getAttribute('content') || '';
        var cookies = (document.cookie || '').split(';');
        for (var i = 0; i < cookies.length; i++) {
            var c = cookies[i].trim();
            if (c.indexOf('csrf_token=') === 0) return decodeURIComponent(c.slice(11));
        }
        return '';
    }

    function api(method, path, body) {
        var opts = { method: method, credentials: 'same-origin', headers: {} };
        if (method !== 'GET') {
            opts.headers['Content-Type'] = 'application/json';
            var token = getCsrf();
            if (token) opts.headers['X-CSRF-Token'] = token;
            if (body !== undefined) opts.body = JSON.stringify(body || {});
        }
        return fetch(path, opts).then(function (res) {
            return res.text().then(function (text) {
                var data = null;
                try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
                if (!res.ok) {
                    var msg = (data && (data.error || data.message)) || text || ('HTTP ' + res.status);
                    var err = new Error(String(msg));
                    err.status = res.status;
                    err.data = data;
                    throw err;
                }
                return data || {};
            });
        });
    }

    // ── host hooks (task 10), degrade gracefully ───────────────────────────────
    function hostUi() {
        return window.AgentZeroUI || null;
    }

    function warnHooksOnce() {
        if (_hookWarned) return;
        _hookWarned = true;
        log('window.AgentZeroUI.setModelLabel/refreshModels not found — panel attached to document.body, header label not updated');
    }

    function setModelLabel(text) {
        var ui = hostUi();
        if (ui && typeof ui.setModelLabel === 'function') {
            try { ui.setModelLabel(text); return; } catch (e) { log('setModelLabel threw: ' + e); }
        }
        warnHooksOnce();
    }

    function askHostRefresh() {
        var ui = hostUi();
        if (ui && typeof ui.refreshModels === 'function') {
            try { ui.refreshModels(); return; } catch (e) { log('refreshModels threw: ' + e); }
        }
        warnHooksOnce();
    }

    function panelHost() {
        // Hooks present or not, the panel lives on document.body (absolute, page coords).
        if (!hostUi()) warnHooksOnce();
        return document.body;
    }

    // ── CSS, injected once, everything scoped under .az-models- ────────────────
    var CSS = [
        '.az-models-panel{position:absolute;z-index:4200;width:' + PANEL_W + 'px;max-height:70vh;overflow:auto;',
        'box-sizing:border-box;padding:0;border-radius:10px;font-family:var(--az-font,inherit);font-size:12.5px;',
        'color:var(--az-fg,#e8edf5);background:var(--az-panel-bg,#131821);border:1px solid var(--az-border,#2a3342);',
        'box-shadow:0 18px 44px rgba(0,0,0,.55);}',
        '.az-models-search{position:sticky;top:0;z-index:2;padding:10px;background:var(--az-panel-bg,#131821);',
        'border-bottom:1px solid var(--az-border,#2a3342);}',
        '.az-models-search input{width:100%;box-sizing:border-box;padding:7px 9px;border-radius:7px;font:inherit;',
        'color:var(--az-fg,#e8edf5);background:var(--az-input-bg,#0c1017);border:1px solid var(--az-border,#2a3342);}',
        '.az-models-search input:focus{outline:none;border-color:var(--az-accent,#4c8dff);}',
        '.az-models-group{padding:8px 0 10px;border-bottom:1px solid var(--az-border-soft,#1e2635);}',
        '.az-models-group:last-child{border-bottom:none;}',
        '.az-models-grouphead{display:flex;align-items:center;gap:8px;padding:4px 10px 6px;',
        'font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--az-muted,#8b97ab);}',
        '.az-models-chip{display:inline-block;padding:2px 7px;border-radius:999px;font-size:10.5px;line-height:1.5;',
        'border:1px solid var(--az-border,#2a3342);color:var(--az-muted,#8b97ab);background:var(--az-chip-bg,#0f141d);',
        'text-transform:none;letter-spacing:0;white-space:normal;}',
        '.az-models-chip.ok{color:var(--az-ok,#4ad88f);border-color:rgba(74,216,143,.4);}',
        '.az-models-chip.warn{color:var(--az-warn,#f0b35a);border-color:rgba(240,179,90,.4);}',
        '.az-models-chip.bad{color:var(--az-bad,#ff6b6b);border-color:rgba(255,107,107,.4);}',
        '.az-models-prow{display:flex;align-items:center;gap:7px;padding:5px 10px;}',
        '.az-models-chev{flex:0 0 auto;width:18px;height:18px;padding:0;border:none;border-radius:4px;cursor:pointer;',
        'color:var(--az-muted,#8b97ab);background:transparent;font:inherit;line-height:18px;text-align:center;}',
        '.az-models-chev:hover{color:var(--az-fg,#e8edf5);background:var(--az-hover,#1b2230);}',
        '.az-models-pname{flex:1 1 auto;font-weight:600;}',
        '.az-models-link{padding:2px 6px;border:1px solid var(--az-border,#2a3342);border-radius:6px;cursor:pointer;',
        'font:inherit;font-size:10.5px;color:var(--az-muted,#8b97ab);background:transparent;}',
        '.az-models-link:hover{color:var(--az-fg,#e8edf5);border-color:var(--az-accent,#4c8dff);}',
        '.az-models-keyrow{display:flex;gap:6px;padding:0 10px 7px 35px;}',
        '.az-models-keyrow input{flex:1 1 auto;min-width:0;padding:5px 7px;border-radius:6px;font:inherit;',
        'color:var(--az-fg,#e8edf5);background:var(--az-input-bg,#0c1017);border:1px solid var(--az-border,#2a3342);}',
        '.az-models-row{display:flex;align-items:flex-start;gap:8px;width:100%;box-sizing:border-box;padding:6px 10px 6px 35px;',
        'border:none;border-left:2px solid transparent;background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer;}',
        '.az-models-row:hover{background:var(--az-hover,#1b2230);}',
        '.az-models-row.sel{border-left-color:var(--az-accent,#4c8dff);background:var(--az-hover,#1b2230);}',
        '.az-models-row.off{cursor:not-allowed;opacity:.55;}',
        '.az-models-row.seed{opacity:.45;cursor:not-allowed;}',
        '.az-models-rowmain{flex:1 1 auto;min-width:0;}',
        '.az-models-label{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
        '.az-models-meta{display:block;margin-top:2px;font-size:10.5px;color:var(--az-muted,#8b97ab);}',
        '.az-models-badge{flex:0 0 auto;max-width:170px;padding:1px 6px;border-radius:5px;font-size:10px;',
        'border:1px solid var(--az-border,#2a3342);color:var(--az-muted,#8b97ab);}',
        '.az-models-badge.ok{color:var(--az-ok,#4ad88f);border-color:rgba(74,216,143,.4);}',
        '.az-models-badge.warn{color:var(--az-warn,#f0b35a);border-color:rgba(240,179,90,.4);}',
        '.az-models-badge.bad{color:var(--az-bad,#ff6b6b);border-color:rgba(255,107,107,.4);}',
        '.az-models-sub{padding:7px 10px 2px 35px;font-size:10px;letter-spacing:.08em;text-transform:uppercase;',
        'color:var(--az-muted,#8b97ab);}',
        '.az-models-empty,.az-models-note{padding:6px 10px 6px 35px;font-size:11px;color:var(--az-muted,#8b97ab);}',
        '.az-models-err{padding:4px 10px 6px 35px;font-size:11px;color:var(--az-bad,#ff6b6b);}',
        '.az-models-overlay{position:fixed;inset:0;z-index:4300;display:flex;align-items:center;justify-content:center;',
        'background:rgba(4,7,12,.62);}',
        '.az-models-dialog{width:480px;max-width:92vw;max-height:86vh;overflow:auto;box-sizing:border-box;padding:16px 18px;',
        'border-radius:12px;font-family:var(--az-font,inherit);font-size:12.5px;color:var(--az-fg,#e8edf5);',
        'background:var(--az-panel-bg,#131821);border:1px solid var(--az-border,#2a3342);box-shadow:0 22px 60px rgba(0,0,0,.6);}',
        '.az-models-dialog h3{margin:0 0 10px;font-size:14.5px;}',
        '.az-models-reqs{width:100%;border-collapse:collapse;margin:0 0 10px;}',
        '.az-models-reqs td{padding:5px 6px;border-bottom:1px solid var(--az-border-soft,#1e2635);vertical-align:top;}',
        '.az-models-reqs td.mark{width:18px;text-align:center;}',
        '.az-models-reqs tr.bad td{color:var(--az-bad,#ff6b6b);}',
        '.az-models-reqs td.det{color:var(--az-muted,#8b97ab);font-size:11px;}',
        '.az-models-bar{height:8px;margin:8px 0 4px;border-radius:999px;overflow:hidden;background:var(--az-input-bg,#0c1017);',
        'border:1px solid var(--az-border,#2a3342);}',
        '.az-models-bar > i{display:block;height:100%;width:0;background:var(--az-accent,#4c8dff);transition:width .25s linear;}',
        '.az-models-prog{font-size:11px;color:var(--az-muted,#8b97ab);}',
        '.az-models-acts{display:flex;justify-content:flex-end;gap:8px;margin-top:12px;}',
        '.az-models-btn{padding:6px 12px;border-radius:7px;border:1px solid var(--az-border,#2a3342);cursor:pointer;',
        'font:inherit;color:var(--az-fg,#e8edf5);background:var(--az-chip-bg,#0f141d);}',
        '.az-models-btn.primary{color:#07111f;background:var(--az-accent,#4c8dff);border-color:var(--az-accent,#4c8dff);}',
        '.az-models-btn[disabled]{opacity:.45;cursor:not-allowed;}',
        '.az-models-toast{position:fixed;left:50%;bottom:34px;z-index:4400;transform:translateX(-50%);padding:9px 16px;',
        'border-radius:8px;font-family:var(--az-font,inherit);font-size:12.5px;color:var(--az-fg,#e8edf5);',
        'background:var(--az-panel-bg,#131821);border:1px solid var(--az-ok,#4ad88f);box-shadow:0 12px 30px rgba(0,0,0,.5);}'
    ].join('');

    function injectCss() {
        if (document.getElementById('zero-models-css')) return;
        var style = document.createElement('style');
        style.id = 'zero-models-css';
        style.textContent = CSS;
        (document.head || document.documentElement).appendChild(style);
    }

    // ── data shaping ───────────────────────────────────────────────────────────
    function providersOfKind(kind) {
        var list = (_data && _data.providers) || [];
        var out = [];
        for (var i = 0; i < list.length; i++) {
            if ((list[i] || {}).kind === kind) out.push(list[i]);
        }
        return out;
    }

    function machine() {
        return (_data && _data.machine) || {};
    }

    function matchesSearch(model) {
        if (!_search) return true;
        var q = _search.toLowerCase();
        var id = String((model && model.id) || '').toLowerCase();
        var label = String((model && model.label) || '').toLowerCase();
        return id.indexOf(q) !== -1 || label.indexOf(q) !== -1;
    }

    function visibleModels(provider) {
        var out = [];
        var list = (provider && provider.models) || [];
        for (var i = 0; i < list.length; i++) {
            if (matchesSearch(list[i])) out.push(list[i]);
        }
        return out;
    }

    function isSelected(providerId, modelId) {
        return !!(_selected && _selected.provider === providerId && _selected.model === modelId);
    }

    function shortName(model) {
        var hay = String((model.id || '') + ' ' + (model.label || ''));
        var m = hay.match(/(opus|sonnet|haiku|fable)/i);
        return m ? m[1].toLowerCase() : (model.label || model.id || '');
    }

    function modelMeta(model) {
        var bits = [];
        if (num(model.size_gb)) bits.push(fmtGb(model.size_gb) + ' GB');
        if (num(model.context)) bits.push(Math.round(num(model.context) / 1000) + 'k ctx');
        if (model.vision) bits.push('👁 vision');
        if (model.tools) bits.push('🛠 tools');
        if (num(model.price_in) || num(model.price_out)) {
            bits.push('$' + num(model.price_in) + '/' + num(model.price_out) + ' per Mtok');
        }
        return bits.join(' · ');
    }

    // Which requirement a backend `fit.reasons` entry is about.
    function reasonHits(reason, key) {
        var text = String(reason || '').toLowerCase();
        if (key === 'vram') return /vram|gpu/.test(text);
        if (key === 'ram') return /(^|[^v])ram\b|system memory|host memory/.test(text);
        if (key === 'disk') return /disk|space|storage/.test(text);
        if (key === 'size') return /size|download/.test(text);
        return false;
    }

    function reasonsFor(model, key) {
        var reasons = ((model.fit || {}).reasons) || [];
        var out = [];
        for (var i = 0; i < reasons.length; i++) {
            if (reasonHits(reasons[i], key)) out.push(String(reasons[i]));
        }
        return out;
    }

    function fitBadge(model) {
        var fit = model.fit || {};
        var reasons = fit.reasons || [];
        if (fit.ok) {
            var busy = [];
            for (var i = 0; i < reasons.length; i++) {
                if (/busy|in use|free now|currently/i.test(String(reasons[i]))) busy.push(String(reasons[i]));
            }
            if (busy.length) return { cls: 'warn', text: 'fits, VRAM busy now', title: busy.join('; ') };
            return { cls: 'ok', text: 'fits', title: 'fits on this machine' };
        }
        var why = reasons.length ? reasons.join('; ') : 'requirements not met';
        return { cls: 'bad', text: 'does not fit: ' + why, title: why };
    }

    // ── group chips ────────────────────────────────────────────────────────────
    function subscriptionChip(provider) {
        if (!provider) return { cls: 'bad', text: 'no login: run claude login' };
        if (provider.status === 'ready') {
            var names = [];
            var list = provider.models || [];
            for (var i = 0; i < list.length; i++) names.push(shortName(list[i]));
            return { cls: 'ok', text: 'Claude Code login ✓ ' + (names.join('/') || '—') };
        }
        return { cls: 'bad', text: provider.status_text || 'no login: run claude login' };
    }

    function localChip(provider) {
        var mach = machine();
        if (provider && provider.status === 'offline') {
            return { cls: 'bad', text: provider.status_text || 'Ollama offline' };
        }
        var bits = ['Ollama ' + (mach.ollama_version || '?')];
        bits.push(fmtGb(mach.vram_free_gb) + ' GB VRAM free');
        bits.push(fmtGb(mach.disk_free_gb) + ' GB disk free');
        return { cls: provider ? 'ok' : 'warn', text: bits.join(' · ') };
    }

    function apiChip(provider) {
        if (provider.status === 'ready') return { cls: 'ok', text: '● key set' };
        if (provider.status === 'no_key') return { cls: 'warn', text: '○ no key' };
        return { cls: 'bad', text: provider.status_text || provider.status || 'unavailable' };
    }

    // ── rendering ──────────────────────────────────────────────────────────────
    function rowHtml(provider, model, opts) {
        opts = opts || {};
        var classes = ['az-models-row'];
        if (isSelected(provider.id, model.id)) classes.push('sel');
        if (opts.seed) classes.push('seed');
        else if (opts.disabled) classes.push('off');
        var meta = opts.meta !== undefined ? opts.meta : modelMeta(model);
        var parts = [];
        parts.push('<button type="button" class="' + classes.join(' ') + '"');
        parts.push(' data-act="' + esc(opts.act || 'select') + '"');
        parts.push(' data-provider="' + esc(provider.id) + '" data-model="' + esc(model.id) + '"');
        if (opts.seed || opts.disabled) parts.push(' disabled');
        if (opts.title) parts.push(' title="' + esc(opts.title) + '"');
        parts.push('>');
        parts.push('<span class="az-models-rowmain">');
        parts.push('<span class="az-models-label">' + esc(model.label || model.id) + '</span>');
        if (meta) parts.push('<span class="az-models-meta">' + esc(meta) + '</span>');
        parts.push('</span>');
        if (opts.badge) {
            parts.push('<span class="az-models-badge ' + esc(opts.badge.cls) + '" title="' + esc(opts.badge.title || '') + '">');
            parts.push(esc(opts.badge.text) + '</span>');
        }
        parts.push('</button>');
        var html = parts.join('');
        var errKey = provider.id + '|' + model.id;
        if (_rowError[errKey]) html += '<div class="az-models-err">' + esc(_rowError[errKey]) + '</div>';
        return html;
    }

    function groupHeadHtml(title, chip) {
        var html = '<div class="az-models-grouphead"><span>' + esc(title) + '</span>';
        if (chip) html += '<span class="az-models-chip ' + esc(chip.cls) + '">' + esc(chip.text) + '</span>';
        return html + '</div>';
    }

    function subscriptionGroupHtml() {
        var provider = providersOfKind('subscription')[0] || null;
        var html = '<div class="az-models-group">' + groupHeadHtml('Subscription', subscriptionChip(provider));
        if (!provider) {
            html += '<div class="az-models-empty">No subscription provider reported.</div>';
            return html + '</div>';
        }
        var ready = provider.status === 'ready';
        var models = visibleModels(provider);
        if (!models.length) {
            html += '<div class="az-models-empty">' + esc(_search ? 'No match in this group.' : 'No models.') + '</div>';
        }
        for (var i = 0; i < models.length; i++) {
            html += rowHtml(provider, models[i], {
                disabled: !ready,
                title: ready ? 'Use ' + (models[i].label || models[i].id) + ' on the Claude Code login'
                             : (provider.status_text || 'no login: run claude login')
            });
        }
        if (_rowError[provider.id]) html += '<div class="az-models-err">' + esc(_rowError[provider.id]) + '</div>';
        return html + '</div>';
    }

    function apiProviderHtml(provider) {
        var chip = apiChip(provider);
        var hasKey = provider.status === 'ready';
        var open = !!_expanded[provider.id] || !!_search;
        var html = '<div class="az-models-prow">';
        html += '<button type="button" class="az-models-chev" data-act="toggle" data-provider="' + esc(provider.id) + '"';
        html += ' title="' + esc(open ? 'Collapse' : 'Expand') + '">' + (open ? '▾' : '▸') + '</button>';
        html += '<span class="az-models-pname">' + esc(provider.label || provider.id) + '</span>';
        html += '<span class="az-models-chip ' + esc(chip.cls) + '" title="' + esc(provider.status_text || '') + '">';
        html += esc(chip.text) + '</span>';
        if (hasKey) {
            html += '<button type="button" class="az-models-link" data-act="key-remove" data-provider="' + esc(provider.id) + '">Remove</button>';
        } else {
            html += '<button type="button" class="az-models-link" data-act="key-add" data-provider="' + esc(provider.id) + '">Add key…</button>';
        }
        html += '</div>';
        if (_keyEditor === provider.id) {
            html += '<div class="az-models-keyrow">';
            html += '<input type="password" autocomplete="off" spellcheck="false" data-keyinput="' + esc(provider.id) + '"';
            html += ' placeholder="' + esc((provider.label || provider.id) + ' API key') + '">';
            html += '<button type="button" class="az-models-link" data-act="key-save" data-provider="' + esc(provider.id) + '">Save</button>';
            html += '<button type="button" class="az-models-link" data-act="key-cancel" data-provider="' + esc(provider.id) + '">Cancel</button>';
            html += '</div>';
        }
        if (_rowError[provider.id]) html += '<div class="az-models-err">' + esc(_rowError[provider.id]) + '</div>';
        if (!open) return html;
        var models = visibleModels(provider);
        if (!models.length) {
            html += '<div class="az-models-empty">' + esc(_search ? 'No match.' : 'No models reported.') + '</div>';
            return html;
        }
        for (var i = 0; i < models.length; i++) {
            var model = models[i];
            var seed = !hasKey && !!model.seed;
            html += rowHtml(provider, model, {
                seed: seed,
                disabled: !hasKey,
                title: seed ? 'list refreshes when a key is set'
                            : (hasKey ? 'Use ' + (model.label || model.id)
                                      : (provider.status_text || 'no key set for this provider'))
            });
        }
        return html;
    }

    function apiGroupHtml() {
        var providers = providersOfKind('api');
        var keyed = 0;
        for (var i = 0; i < providers.length; i++) {
            if (providers[i].status === 'ready') keyed++;
        }
        var chip = providers.length
            ? { cls: keyed ? 'ok' : 'warn', text: keyed + ' of ' + providers.length + ' keyed' }
            : { cls: 'warn', text: 'no providers' };
        var html = '<div class="az-models-group">' + groupHeadHtml('API', chip);
        if (!providers.length) html += '<div class="az-models-empty">No API providers reported.</div>';
        for (var j = 0; j < providers.length; j++) html += apiProviderHtml(providers[j]);
        return html + '</div>';
    }

    function localGroupHtml() {
        var provider = providersOfKind('local')[0] || null;
        var html = '<div class="az-models-group">' + groupHeadHtml('Local', localChip(provider));
        if (!provider) {
            html += '<div class="az-models-empty">Ollama not reachable on this machine.</div>';
            return html + '</div>';
        }
        var models = visibleModels(provider);
        var installed = [];
        var available = [];
        for (var i = 0; i < models.length; i++) {
            if (models[i].installed) installed.push(models[i]);
            else available.push(models[i]);
        }
        var offline = provider.status === 'offline';
        html += '<div class="az-models-sub">Installed</div>';
        if (!installed.length) {
            html += '<div class="az-models-empty">' + esc(_search ? 'No match.' : 'No models installed yet.') + '</div>';
        }
        for (var j = 0; j < installed.length; j++) {
            html += rowHtml(provider, installed[j], {
                disabled: offline,
                title: offline ? (provider.status_text || 'Ollama offline')
                               : 'Use ' + (installed[j].label || installed[j].id) + ' locally'
            });
        }
        html += '<div class="az-models-sub">Available to install</div>';
        if (!available.length) {
            html += '<div class="az-models-empty">' + esc(_search ? 'No match.' : 'Nothing else to offer.') + '</div>';
        }
        for (var k = 0; k < available.length; k++) {
            var model = available[k];
            var badge = fitBadge(model);
            html += rowHtml(provider, model, {
                act: 'install',
                badge: badge,
                disabled: offline,
                title: offline ? (provider.status_text || 'Ollama offline')
                               : 'Install ' + (model.label || model.id) + ' — ' + badge.text
            });
        }
        if (_rowError[provider.id]) html += '<div class="az-models-err">' + esc(_rowError[provider.id]) + '</div>';
        return html + '</div>';
    }

    function bodyHtml() {
        if (!_data) return '<div class="az-models-empty">Loading models…</div>';
        return subscriptionGroupHtml() + apiGroupHtml() + localGroupHtml();
    }

    function renderPanel() {
        if (!_panel) return;
        var list = _panel.querySelector('[data-role="list"]');
        if (!list) {
            _panel.innerHTML =
                '<div class="az-models-search"><input type="search" data-role="search" placeholder="Search models…"' +
                ' autocomplete="off" spellcheck="false" value="' + esc(_search) + '"></div>' +
                '<div data-role="list">' + bodyHtml() + '</div>';
        } else {
            list.innerHTML = bodyHtml();
        }
        position();
    }

    function position() {
        if (!_panel) return;
        var top = 80;
        var left = 20;
        if (_anchor && _anchor.getBoundingClientRect) {
            var r = _anchor.getBoundingClientRect();
            var sx = window.pageXOffset || document.documentElement.scrollLeft || 0;
            var sy = window.pageYOffset || document.documentElement.scrollTop || 0;
            top = r.bottom + sy + 6;
            left = r.left + sx;
            var maxLeft = sx + (window.innerWidth || PANEL_W) - PANEL_W - 12;
            if (left > maxLeft) left = Math.max(sx + 8, maxLeft);
        }
        _panel.style.top = Math.round(top) + 'px';
        _panel.style.left = Math.round(left) + 'px';
    }

    // ── fetching ───────────────────────────────────────────────────────────────
    function fetchModels(force) {
        var fresh = _data && (Date.now() - _fetchedAt) < CACHE_MS;
        if (!force && fresh) return Promise.resolve(_data);
        if (_inflight) return _inflight;
        _inflight = api('GET', API + '/models').then(function (data) {
            _data = data || {};
            _fetchedAt = Date.now();
            if (_data.selected && _data.selected.model) {
                _selected = { provider: _data.selected.provider, model: _data.selected.model };
            }
            _inflight = null;
            return _data;
        }).catch(function (err) {
            _inflight = null;
            throw err;
        });
        return _inflight;
    }

    // ── selection ──────────────────────────────────────────────────────────────
    function findProvider(providerId) {
        var list = (_data && _data.providers) || [];
        for (var i = 0; i < list.length; i++) {
            if (list[i] && list[i].id === providerId) return list[i];
        }
        return null;
    }

    function findModel(providerId, modelId) {
        var provider = findProvider(providerId);
        var list = (provider && provider.models) || [];
        for (var i = 0; i < list.length; i++) {
            if (list[i] && list[i].id === modelId) return list[i];
        }
        return null;
    }

    function selectModel(providerId, modelId, silent) {
        var errKey = providerId + '|' + modelId;
        delete _rowError[errKey];
        return api('POST', API + '/models/select', { provider: providerId, model: modelId }).then(function () {
            _selected = { provider: providerId, model: modelId };
            if (_data) _data.selected = { provider: providerId, model: modelId };
            var provider = findProvider(providerId);
            var model = findModel(providerId, modelId);
            var label = (model && (model.label || model.id)) || modelId;
            var kind = (provider && provider.kind) || 'api';
            setModelLabel(label + ' · ' + kind);
            askHostRefresh();
            if (!silent) close();
            return true;
        }).catch(function (err) {
            _rowError[errKey] = err.message || 'select failed';
            renderPanel();
            return false;
        });
    }

    // ── API keys ───────────────────────────────────────────────────────────────
    function saveKey(providerId) {
        if (!_panel) return;
        var input = null;
        var candidates = _panel.querySelectorAll('input[data-keyinput]');
        for (var i = 0; i < candidates.length; i++) {
            if (candidates[i].getAttribute('data-keyinput') === providerId) {
                input = candidates[i];
                break;
            }
        }
        if (!input) input = _panel.querySelector('input[type="password"]');
        var value = input ? String(input.value || '').trim() : '';
        delete _rowError[providerId];
        if (!value) {
            _rowError[providerId] = 'Paste a key first.';
            renderPanel();
            return;
        }
        api('POST', API + '/providers/' + encodeURIComponent(providerId) + '/key', { key: value }).then(function () {
            _keyEditor = null;
            _expanded[providerId] = true;
            return fetchModels(true);
        }).then(function () {
            renderPanel();
        }).catch(function (err) {
            _rowError[providerId] = err.message || 'could not save the key';
            renderPanel();
        });
    }

    function removeKey(providerId) {
        delete _rowError[providerId];
        api('DELETE', API + '/providers/' + encodeURIComponent(providerId) + '/key').then(function () {
            return fetchModels(true);
        }).then(function () {
            renderPanel();
        }).catch(function (err) {
            _rowError[providerId] = err.message || 'could not remove the key';
            renderPanel();
        });
    }

    // ── install dialog ─────────────────────────────────────────────────────────
    function requirementRows(model) {
        var mach = machine();
        var size = num(model.size_gb);
        var rows = [];
        rows.push({
            key: 'size',
            label: 'Download size',
            value: fmtGb(size) + ' GB',
            detail: 'pulled from the Ollama registry'
        });
        rows.push({
            key: 'vram',
            label: 'VRAM needed',
            value: fmtGb(model.vram_gb) + ' GB',
            detail: 'this GPU: ' + fmtGb(mach.vram_total_gb) + ' GB total, ' + fmtGb(mach.vram_free_gb) + ' GB free now'
        });
        rows.push({
            key: 'ram',
            label: 'RAM',
            value: '~' + fmtGb(model.ram_gb) + ' GB',
            detail: 'this machine: ' + fmtGb(mach.ram_total_gb) + ' GB (' + fmtGb(mach.ram_avail_gb) + ' GB available)'
        });
        rows.push({
            key: 'disk',
            label: 'Disk free',
            value: fmtGb(mach.disk_free_gb) + ' GB',
            detail: 'needs ' + fmtGb(size + DISK_HEADROOM_GB) + ' GB (download + ' + DISK_HEADROOM_GB + ' GB)'
        });
        var fitOk = !!((model.fit || {}).ok);
        for (var i = 0; i < rows.length; i++) {
            var hits = reasonsFor(model, rows[i].key);
            rows[i].ok = fitOk ? true : hits.length === 0;
            if (hits.length) rows[i].detail = hits.join('; ');
        }
        return rows;
    }

    function dialogHtml(model) {
        var fit = model.fit || {};
        var reasons = (fit.reasons || []).join('; ');
        var mach = machine();
        var rows = requirementRows(model);
        var html = '<div class="az-models-dialog" role="dialog" aria-modal="true">';
        html += '<h3>Install ' + esc(model.label || model.id) + '?</h3>';
        html += '<table class="az-models-reqs">';
        for (var i = 0; i < rows.length; i++) {
            html += '<tr class="' + (rows[i].ok ? 'ok' : 'bad') + '">';
            html += '<td class="mark">' + (rows[i].ok ? '✓' : '✗') + '</td>';
            html += '<td>' + esc(rows[i].label) + '</td>';
            html += '<td>' + esc(rows[i].value) + '</td>';
            html += '<td class="det">' + esc(rows[i].detail) + '</td>';
            html += '</tr>';
        }
        html += '</table>';
        html += '<div class="az-models-prog">Downloads go to the Ollama models folder on / (' +
                esc(fmtGb(mach.disk_free_gb)) + ' GB free today).</div>';
        if (!fit.ok && reasons) {
            html += '<div class="az-models-err" style="padding-left:0">Does not fit: ' + esc(reasons) + '</div>';
        }
        html += '<div data-role="progress" style="display:none">';
        html += '<div class="az-models-bar"><i data-role="bar"></i></div>';
        html += '<div class="az-models-prog" data-role="progtext"></div></div>';
        html += '<div class="az-models-err" data-role="dlgerr" style="display:none;padding-left:0"></div>';
        html += '<div class="az-models-acts">';
        html += '<button type="button" class="az-models-btn" data-act="dlg-cancel">Cancel</button>';
        html += '<button type="button" class="az-models-btn primary" data-act="dlg-go" data-role="go"';
        if (!fit.ok) html += ' disabled title="' + esc(reasons || 'does not fit on this machine') + '"';
        html += '>Download &amp; install</button>';
        html += '</div></div>';
        return html;
    }

    function openInstallDialog(providerId, modelId) {
        var model = findModel(providerId, modelId);
        if (!model) return;
        closeDialog();
        injectCss();
        _dialogCtx = { provider: providerId, model: modelId, jobId: null, phase: 'confirm' };
        _dialog = document.createElement('div');
        _dialog.className = 'az-models-overlay';
        _dialog.innerHTML = dialogHtml(model);
        _dialog.addEventListener('click', onDialogClick);
        document.body.appendChild(_dialog);
    }

    function closeDialog() {
        if (_pollTimer) {
            clearTimeout(_pollTimer);
            _pollTimer = null;
        }
        if (_dialog) {
            _dialog.removeEventListener('click', onDialogClick);
            if (_dialog.parentNode) _dialog.parentNode.removeChild(_dialog);
        }
        _dialog = null;
        _dialogCtx = null;
    }

    function dialogError(message) {
        if (!_dialog) return;
        var box = _dialog.querySelector('[data-role="dlgerr"]');
        if (!box) return;
        box.textContent = String(message || 'install failed');
        box.style.display = '';
        var go = _dialog.querySelector('[data-role="go"]');
        if (go) {
            go.disabled = false;
            go.textContent = 'Retry';
        }
    }

    function showProgress(pct, text) {
        if (!_dialog) return;
        var wrap = _dialog.querySelector('[data-role="progress"]');
        var bar = _dialog.querySelector('[data-role="bar"]');
        var label = _dialog.querySelector('[data-role="progtext"]');
        if (wrap) wrap.style.display = '';
        if (bar) bar.style.width = Math.max(0, Math.min(100, num(pct))) + '%';
        if (label) label.textContent = String(text || '');
    }

    function progressText(job) {
        var bits = [];
        if (job.status_text) bits.push(String(job.status_text));
        var total = num(job.total);
        var completed = num(job.completed);
        if (total) bits.push(fmtGb(completed) + ' / ' + fmtGb(total) + ' GB');
        bits.push(Math.round(num(job.pct)) + '%');
        return bits.join(' · ');
    }

    function startInstall() {
        if (!_dialogCtx) return;
        var ctx = _dialogCtx;
        var go = _dialog ? _dialog.querySelector('[data-role="go"]') : null;
        if (go) {
            go.disabled = true;
            go.textContent = 'Installing…';
        }
        var box = _dialog ? _dialog.querySelector('[data-role="dlgerr"]') : null;
        if (box) box.style.display = 'none';
        ctx.phase = 'running';
        showProgress(0, 'starting…');
        api('POST', API + '/models/install', { model: ctx.model, confirm: true }).then(function (res) {
            if (!_dialogCtx || _dialogCtx !== ctx) return;
            ctx.jobId = (res && res.job_id) || null;
            if (!ctx.jobId) {
                dialogError('backend did not return a job id');
                return;
            }
            pollInstall(ctx);
        }).catch(function (err) {
            if (!_dialogCtx || _dialogCtx !== ctx) return;
            dialogError(err.message || 'install refused');
        });
    }

    function pollInstall(ctx) {
        if (!_dialogCtx || _dialogCtx !== ctx || !ctx.jobId) return;
        api('GET', API + '/models/install/' + encodeURIComponent(ctx.jobId)).then(function (job) {
            if (!_dialogCtx || _dialogCtx !== ctx) return;
            job = job || {};
            showProgress(job.pct, progressText(job));
            if (job.status === 'done') {
                finishInstall(ctx);
                return;
            }
            if (job.status === 'error') {
                dialogError(job.error || job.status_text || 'install failed');
                return;
            }
            _pollTimer = setTimeout(function () { pollInstall(ctx); }, POLL_MS);
        }).catch(function (err) {
            if (!_dialogCtx || _dialogCtx !== ctx) return;
            dialogError(err.message || 'lost track of the install job');
        });
    }

    function finishInstall(ctx) {
        showProgress(100, 'installed · selecting…');
        fetchModels(true).then(function () {
            return selectModel(ctx.provider, ctx.model, true);
        }).then(function (ok) {
            closeDialog();
            if (ok) toast('Installed and selected');
            close();
        }).catch(function (err) {
            dialogError(err.message || 'installed, but could not select the model');
        });
    }

    function toast(message) {
        injectCss();
        var el = document.createElement('div');
        el.className = 'az-models-toast';
        el.textContent = String(message || '');
        document.body.appendChild(el);
        setTimeout(function () {
            if (el.parentNode) el.parentNode.removeChild(el);
        }, 3200);
    }

    // ── events ─────────────────────────────────────────────────────────────────
    function onDialogClick(ev) {
        var btn = ev.target && ev.target.closest ? ev.target.closest('[data-act]') : null;
        if (!btn || !_dialog || !_dialog.contains(btn)) {
            if (ev.target === _dialog) closeDialog();   // overlay click
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        var act = btn.getAttribute('data-act');
        if (act === 'dlg-cancel') closeDialog();
        else if (act === 'dlg-go') startInstall();
    }

    function onPanelClick(ev) {
        var el = ev.target && ev.target.closest ? ev.target.closest('[data-act]') : null;
        if (!el) return;
        ev.preventDefault();
        ev.stopPropagation();
        var act = el.getAttribute('data-act');
        var providerId = el.getAttribute('data-provider') || '';
        var modelId = el.getAttribute('data-model') || '';
        if (act === 'toggle') {
            _expanded[providerId] = !_expanded[providerId];
            renderPanel();
        } else if (act === 'key-add') {
            _keyEditor = providerId;
            delete _rowError[providerId];
            renderPanel();
            var input = _panel && _panel.querySelector('input[type="password"]');
            if (input) input.focus();
        } else if (act === 'key-cancel') {
            _keyEditor = null;
            renderPanel();
        } else if (act === 'key-save') {
            saveKey(providerId);
        } else if (act === 'key-remove') {
            removeKey(providerId);
        } else if (act === 'install') {
            openInstallDialog(providerId, modelId);
        } else if (act === 'select') {
            selectModel(providerId, modelId, false);
        }
    }

    function onPanelInput(ev) {
        var input = ev.target;
        if (!input || input.getAttribute('data-role') !== 'search') return;
        _search = String(input.value || '').trim();
        var list = _panel && _panel.querySelector('[data-role="list"]');
        if (list) list.innerHTML = bodyHtml();
    }

    function onPanelKeydown(ev) {
        if (ev.key !== 'Enter') return;
        var input = ev.target;
        if (!input || input.type !== 'password') return;
        var row = input.closest ? input.closest('.az-models-keyrow') : null;
        var save = row ? row.querySelector('[data-act="key-save"]') : null;
        var providerId = save ? save.getAttribute('data-provider') : '';
        if (providerId) {
            ev.preventDefault();
            saveKey(providerId);
        }
    }

    function onDocKeydown(ev) {
        if (ev.key !== 'Escape') return;
        if (_dialog) {
            closeDialog();
            return;
        }
        close();
    }

    function onDocMousedown(ev) {
        if (_dialog) return;
        if (!_panel) return;
        var t = ev.target;
        if (_panel.contains(t)) return;
        if (_anchor && _anchor.contains && _anchor.contains(t)) return;
        close();
    }

    function bindDoc() {
        if (_docBound) return;
        _docBound = true;
        document.addEventListener('keydown', onDocKeydown, true);
        document.addEventListener('mousedown', onDocMousedown, true);
        window.addEventListener('resize', position);
    }

    function unbindDoc() {
        if (!_docBound) return;
        _docBound = false;
        document.removeEventListener('keydown', onDocKeydown, true);
        document.removeEventListener('mousedown', onDocMousedown, true);
        window.removeEventListener('resize', position);
    }

    // ── public API ─────────────────────────────────────────────────────────────
    function open(anchorEl) {
        injectCss();
        if (_panel) {
            close();
        }
        _anchor = anchorEl || null;
        _search = '';
        _keyEditor = null;
        _rowError = {};
        _panel = document.createElement('div');
        _panel.className = 'az-models-panel';
        _panel.setAttribute('role', 'listbox');
        _panel.addEventListener('click', onPanelClick);
        _panel.addEventListener('input', onPanelInput);
        _panel.addEventListener('keydown', onPanelKeydown);
        panelHost().appendChild(_panel);
        renderPanel();
        bindDoc();
        var search = _panel.querySelector('[data-role="search"]');
        if (search) search.focus();
        fetchModels(false).then(function () {
            renderPanel();
        }).catch(function (err) {
            if (!_panel) return;
            var list = _panel.querySelector('[data-role="list"]');
            if (list) list.innerHTML = '<div class="az-models-err" style="padding-left:10px">' +
                esc(err.message || 'could not load models') + '</div>';
        });
    }

    function close() {
        unbindDoc();
        if (_panel) {
            _panel.removeEventListener('click', onPanelClick);
            _panel.removeEventListener('input', onPanelInput);
            _panel.removeEventListener('keydown', onPanelKeydown);
            if (_panel.parentNode) _panel.parentNode.removeChild(_panel);
        }
        _panel = null;
        _anchor = null;
    }

    function refresh() {
        return fetchModels(true).then(function (data) {
            if (_panel) renderPanel();
            return data;
        });
    }

    function current() {
        if (!_selected) return null;
        return { provider: _selected.provider, model: _selected.model };
    }

    window.AgentZeroModels = {
        open: open,
        close: close,
        refresh: refresh,
        current: current
    };
})();
