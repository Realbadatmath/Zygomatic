/**
 * ZeroTranscript — everything that draws inside the Agent Zero v2 transcript.
 *
 * Loaded AFTER zero_chat.js; zero_chat.js only reaches for window.ZeroTranscript
 * at runtime (after DOMContentLoaded), so the order costs nothing.
 *
 * Safety rule for this file: the only string ever handed to innerHTML is the
 * output of ZeroMarkdown.render() (escape-first, see zero_markdown.js) or a
 * string this file built itself from escaped pieces. Model/server text always
 * goes through textContent or ZeroMarkdown.
 */
(function () {
    'use strict';

    var W = window;
    var RENDER_MS = 400;

    function esc(s) {
        return (W.ZeroMarkdown && W.ZeroMarkdown.escape)
            ? W.ZeroMarkdown.escape(s)
            : String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
                return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
            });
    }

    function md(text) {
        return W.ZeroMarkdown ? W.ZeroMarkdown.render(text) : '<p>' + esc(text) + '</p>';
    }

    function el(tag, cls, text) {
        var n = document.createElement(tag);
        if (cls) n.className = cls;
        if (text != null) n.textContent = String(text);
        return n;
    }

    function pretty(value) {
        if (value == null) return '';
        if (typeof value === 'string') return value;
        try {
            return JSON.stringify(value, null, 2);
        } catch (_) {
            return String(value);
        }
    }

    function num(n) {
        var v = Number(n || 0);
        if (v >= 1000) return (v / 1000).toFixed(1).replace(/\.0$/, '') + 'k';
        return String(Math.round(v));
    }

    // -----------------------------------------------------------------------
    var root = null;
    var autoScroll = true;

    function atBottom() {
        if (!root) return true;
        return root.scrollHeight - root.scrollTop - root.clientHeight < 60;
    }

    function scroll(force) {
        if (!root) return;
        if (!force && !autoScroll) return;
        root.scrollTop = root.scrollHeight;
    }

    function onRootClick(e) {
        var copy = e.target.closest ? e.target.closest('.az-code-copy') : null;
        if (copy) {
            var box = copy.closest('.az-code');
            var pre = box && box.querySelector('code');
            var txt = pre ? pre.textContent : '';
            var done = function () {
                copy.textContent = 'Copied';
                setTimeout(function () { copy.textContent = 'Copy'; }, 1200);
            };
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(txt).then(done, function () {});
            } else {
                var ta = el('textarea');
                ta.value = txt;
                document.body.appendChild(ta);
                ta.select();
                try { document.execCommand('copy'); done(); } catch (_) {}
                document.body.removeChild(ta);
            }
            return;
        }
        var head = e.target.closest ? e.target.closest('.az-tool-head') : null;
        if (head && head.parentNode) head.parentNode.classList.toggle('az-expanded');
    }

    /** Idempotent: zero_chat.js calls this lazily on first use (it is loaded first). */
    function setRoot(node) {
        if (root === node || !node) return;
        root = node;
        if (node._azBound) return;
        node._azBound = true;
        node.addEventListener('click', onRootClick);
        node.addEventListener('scroll', function () { autoScroll = atBottom(); });
    }

    function clear() {
        if (root) root.textContent = '';
        autoScroll = true;
    }

    function add(node) {
        var keep = autoScroll;
        if (root) root.appendChild(node);
        if (keep) scroll(true);
        return node;
    }

    // --- user message -------------------------------------------------------
    function addUser(text, imageB64) {
        var wrap = el('div', 'az-msg az-msg-user');
        var bubble = el('div', 'az-bubble');
        bubble.appendChild(document.createTextNode(String(text == null ? '' : text)));
        if (imageB64) {
            var img = el('img', 'az-thumb');
            img.src = 'data:image/png;base64,' + String(imageB64).replace(/^data:[^,]*,/, '');
            img.alt = 'attachment';
            bubble.appendChild(img);
        }
        wrap.appendChild(bubble);
        return add(wrap);
    }

    // --- assistant message --------------------------------------------------
    function addAssistant() {
        var wrap = el('div', 'az-msg az-msg-assistant');
        var msg = {
            el: wrap,
            parts: [],
            cur: null,
            tools: {},
            startedAt: Date.now(),
            usageEl: null
        };
        add(wrap);
        return msg;
    }

    function newTextPart(msg) {
        var node = el('div', 'az-md');
        msg.el.appendChild(node);
        msg.cur = { node: node, raw: '', timer: null, lastRender: 0 };
        msg.parts.push(msg.cur);
        return msg.cur;
    }

    function renderPart(part) {
        part.lastRender = Date.now();
        part.node.innerHTML = md(part.raw); // ZeroMarkdown output only — escape-first
    }

    function schedule(part) {
        if (part.timer) return;
        var wait = Math.max(0, RENDER_MS - (Date.now() - part.lastRender));
        part.timer = setTimeout(function () {
            part.timer = null;
            renderPart(part);
            scroll(false);
        }, wait);
    }

    function appendDelta(msg, text) {
        if (!text) return;
        var part = msg.cur || newTextPart(msg);
        part.raw += String(text);
        schedule(part);
    }

    function closeTextPart(msg) {
        if (!msg.cur) return;
        var part = msg.cur;
        msg.cur = null;
        if (part.timer) { clearTimeout(part.timer); part.timer = null; }
        if (part.raw) renderPart(part);
        else if (part.node.parentNode) part.node.parentNode.removeChild(part.node);
    }

    function appendThinking(msg, text) {
        closeTextPart(msg);
        var last = msg.el.lastChild;
        if (last && last.classList && last.classList.contains('az-thinking')) {
            last.textContent += String(text || '');
        } else {
            msg.el.appendChild(el('div', 'az-thinking', String(text || '')));
        }
        scroll(false);
    }

    // --- tool cards ---------------------------------------------------------
    function argHint(args) {
        if (!args || typeof args !== 'object') return '';
        var keys = Object.keys(args);
        if (!keys.length) return '';
        var v = args[keys[0]];
        if (v == null || typeof v === 'object') return '';
        var s = String(v);
        return s.length > 48 ? s.slice(0, 45) + '…' : s;
    }

    function buildToolCard(call) {
        var card = el('div', 'az-tool');
        card.dataset.toolId = String(call.id == null ? '' : call.id);
        var head = el('div', 'az-tool-head');
        head.appendChild(el('span', 'az-tool-gear', '⚙'));
        var hint = argHint(call.args);
        head.appendChild(el('span', 'az-tool-name', String(call.name || 'tool') + (hint ? ' ' + hint : '')));
        var ms = el('span', 'az-tool-ms', '…');
        head.appendChild(ms);
        var flag = el('span', 'az-tool-flag az-run', '•');
        head.appendChild(flag);
        card.appendChild(head);

        var body = el('div', 'az-tool-body');
        body.appendChild(el('h5', null, 'Arguments'));
        body.appendChild(el('pre', 'az-tool-pre', pretty(call.args) || '{}'));
        card.appendChild(body);

        card._az = { ms: ms, flag: flag, body: body };
        return card;
    }

    function toolCall(msg, call) {
        closeTextPart(msg);
        var card = buildToolCard(call);
        msg.el.appendChild(card);
        msg.tools[String(call.id)] = card;
        scroll(false);
        return card;
    }

    function toolResult(msg, res) {
        var card = msg.tools[String(res.id)];
        if (!card) {
            card = toolCall(msg, { id: res.id, name: res.name, args: null });
        }
        var parts = card._az;
        parts.ms.textContent = '· ' + Math.round(Number(res.ms || 0)) + ' ms';
        parts.flag.className = 'az-tool-flag ' + (res.ok ? 'az-ok' : 'az-err');
        parts.flag.textContent = res.ok ? '✓' : '✗';
        parts.body.appendChild(el('h5', null, res.ok ? 'Result' : 'Error'));
        parts.body.appendChild(el('pre', 'az-tool-pre', pretty(res.text)));
        if (!res.ok) card.classList.add('az-expanded');
        scroll(false);
        return card;
    }

    // --- confirm card -------------------------------------------------------
    function confirmCard(msg, payload, onDecide) {
        var host = msg ? msg.el : root;
        closeTextPart(msg || { cur: null });
        var card = el('div', 'az-confirm');
        card.appendChild(el('div', 'az-confirm-title', 'Confirm: ' + String(payload.name || 'action')));
        card.appendChild(el('div', 'az-confirm-risk', 'risk: ' + String(payload.risk || 'act')));
        card.appendChild(el('pre', 'az-tool-pre', pretty(payload.args) || '{}'));
        var btns = el('div', 'az-confirm-btns');
        var yes = el('button', 'az-btn az-btn-primary', 'Approve');
        var no = el('button', 'az-btn', 'Deny');
        yes.type = 'button';
        no.type = 'button';
        function decide(approve) {
            yes.disabled = true;
            no.disabled = true;
            card.appendChild(el('div', 'az-confirm-risk', approve ? 'approved' : 'denied'));
            if (typeof onDecide === 'function') onDecide(approve, payload);
        }
        yes.addEventListener('click', function () { decide(true); });
        no.addEventListener('click', function () { decide(false); });
        btns.appendChild(yes);
        btns.appendChild(no);
        card.appendChild(btns);
        if (host) host.appendChild(card);
        scroll(true);
        return card;
    }

    // --- usage line / finish ------------------------------------------------
    function usageLine(msg, usage, elapsedMs) {
        var u = usage || {};
        var bits = [
            'in ' + num(u.input_tokens),
            'out ' + num(u.output_tokens)
        ];
        if (u.cache_read) bits.push('cache ' + num(u.cache_read));
        if (elapsedMs != null) bits.push((Number(elapsedMs) / 1000).toFixed(1) + ' s');
        if (u.model) bits.push(String(u.model));
        if (u.cost_usd != null && Number(u.cost_usd) > 0) bits.push('$' + Number(u.cost_usd).toFixed(4));
        else if (u.cost_usd === 0) bits.push('subscription');
        var line = msg && msg.usageEl ? msg.usageEl : el('div', 'az-usage');
        line.textContent = bits.join(' · ');
        if (msg && !msg.usageEl) {
            msg.usageEl = line;
            msg.el.appendChild(line);
        }
        scroll(false);
        return line;
    }

    function finish(msg) {
        if (!msg) return;
        closeTextPart(msg);
        msg.parts.forEach(function (p) {
            if (p.timer) { clearTimeout(p.timer); p.timer = null; }
            if (p.raw) renderPart(p);
        });
        if (!msg.el.childNodes.length) {
            msg.el.appendChild(el('div', 'az-usage', '(no output)'));
        }
        scroll(false);
    }

    // --- banners / system cards --------------------------------------------
    function banner(kind, text, actions) {
        var b = el('div', 'az-banner az-banner-' + (kind || 'info'));
        b.appendChild(el('span', 'az-banner-text', String(text == null ? '' : text)));
        (actions || []).forEach(function (a) {
            var btn = el('button', 'az-btn' + (a.primary ? ' az-btn-primary' : ''), a.label);
            btn.type = 'button';
            btn.addEventListener('click', function () {
                if (a.once) btn.disabled = true;
                a.onClick(b);
            });
            b.appendChild(btn);
        });
        return add(b);
    }

    /**
     * Sibling-module hook. `html` is trusted: it comes from another dashboard
     * module (never from the network). Callers that have server text must pass
     * it through ZeroMarkdown.escape() themselves.
     */
    function systemCard(html, opts) {
        var o = opts || {};
        var kind = o.kind === 'warn' ? 'warn' : (o.kind === 'request' ? 'request' : 'info');
        var card = el('div', 'az-banner az-banner-' + kind);
        var inner = el('div', 'az-banner-text');
        inner.innerHTML = String(html == null ? '' : html); // trusted module HTML
        card.appendChild(inner);
        if (o.id) card.dataset.cardId = String(o.id);
        return add(card);
    }

    function removeSystemCard(id) {
        if (!root || !id) return;
        var node = root.querySelector('[data-card-id="' + String(id).replace(/"/g, '') + '"]');
        if (node && node.parentNode) node.parentNode.removeChild(node);
    }

    /** `text` is composed by zero_chat.js (it owns the greeting wording). */
    function greeting(text) {
        var wrap = el('div', 'az-msg az-msg-assistant az-greeting');
        var body = el('div', 'az-md');
        body.innerHTML = md(String(text == null ? '' : text));
        wrap.appendChild(body);
        return add(wrap);
    }

    function toast(text) {
        var t = el('div', 'az-toast', String(text == null ? '' : text));
        document.body.appendChild(t);
        setTimeout(function () {
            if (t.parentNode) t.parentNode.removeChild(t);
        }, 2600);
    }

    // --- replaying a stored session ----------------------------------------
    function blocks(content) {
        if (content == null) return [];
        if (typeof content === 'string') return [{ type: 'text', text: content }];
        if (Object.prototype.toString.call(content) === '[object Array]') return content;
        return [];
    }

    function renderMessages(messages) {
        var cards = {};
        (messages || []).forEach(function (m) {
            var bs = blocks(m.content);
            if (m.role === 'user') {
                var text = bs.filter(function (b) { return b.type === 'text'; })
                    .map(function (b) { return b.text || ''; }).join('\n').trim();
                var image = bs.filter(function (b) { return b.type === 'image'; })[0];
                var results = bs.filter(function (b) { return b.type === 'tool_result'; });
                if (text || image) addUser(text, image ? image.data : null);
                results.forEach(function (r) {
                    var card = cards[String(r.tool_use_id)];
                    if (!card) return;
                    card._az.ms.textContent = '';
                    card._az.flag.className = 'az-tool-flag ' + (r.is_error ? 'az-err' : 'az-ok');
                    card._az.flag.textContent = r.is_error ? '✗' : '✓';
                    card._az.body.appendChild(el('h5', null, r.is_error ? 'Error' : 'Result'));
                    card._az.body.appendChild(el('pre', 'az-tool-pre', pretty(r.content)));
                });
                return;
            }
            var msg = addAssistant();
            bs.forEach(function (b) {
                if (b.type === 'text' && b.text) {
                    appendDelta(msg, b.text);
                } else if (b.type === 'tool_use') {
                    var card = toolCall(msg, { id: b.id, name: b.name, args: b.input });
                    cards[String(b.id)] = card;
                } else if (b.type === 'thinking' && b.text) {
                    appendThinking(msg, b.text);
                }
            });
            finish(msg);
            if (m.usage) usageLine(msg, m.usage, m.elapsed_ms);
        });
        scroll(true);
    }

    W.ZeroTranscript = {
        setRoot: setRoot,
        getRoot: function () { return root; },
        clear: clear,
        scroll: scroll,
        addUser: addUser,
        addAssistant: addAssistant,
        appendDelta: appendDelta,
        appendThinking: appendThinking,
        toolCall: toolCall,
        toolResult: toolResult,
        confirmCard: confirmCard,
        usageLine: usageLine,
        finish: finish,
        banner: banner,
        systemCard: systemCard,
        removeSystemCard: removeSystemCard,
        greeting: greeting,
        toast: toast,
        renderMessages: renderMessages,
        escape: esc
    };
}());
