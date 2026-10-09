/**
 * ZeroMarkdown — escape-first markdown renderer for the Agent Zero v2 chat window.
 *
 * Contract: window.ZeroMarkdown.render(text) -> HTML string that is safe to assign
 * to innerHTML. Every character that comes from the model or the server is passed
 * through esc() before any tag is produced, so user text can never emit a tag.
 * Fenced code blocks are lifted out first (so their contents are never parsed as
 * markdown) and re-inserted at the end as already-escaped <pre><code> nodes.
 */
(function () {
    'use strict';

    // Sentinel used for placeholder tokens. Stripped from the input first, so a
    // crafted message can never forge a placeholder and smuggle raw HTML in.
    var SENT = '\u0001';
    var TOKEN_RE = /\u0001([CI])(\d+)\u0001/g;
    var LIST_RE = /^([ \t]*)([-*+]|\d+[.)])[ \t]+(.*)$/;
    var HR_RE = /^[ \t]*(-{3,}|\*{3,}|_{3,})[ \t]*$/;
    var QUOTE_RE = /^[ \t]*&gt;[ \t]?/;
    var ROW_RE = /^[ \t]*\|.*\|[ \t]*$/;
    var SEP_RE = /^[ \t]*\|[\s:|-]*-[\s:|-]*\|[ \t]*$/;

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function codeBlockHtml(lang, code) {
        var label = esc(String(lang || '').slice(0, 24)) || 'code';
        return '<div class="az-code">' +
            '<div class="az-code-bar"><span class="az-code-lang">' + label + '</span>' +
            '<button type="button" class="az-code-copy" data-copy="1">Copy</button></div>' +
            '<pre class="az-code-pre"><code>' + esc(code) + '</code></pre></div>';
    }

    // --- stage 1: lift fenced code blocks out of the raw text ------------------
    function extractFences(text, store) {
        var lines = text.split('\n');
        var out = [];
        var i = 0;
        while (i < lines.length) {
            var m = /^[ \t]*`{3,}[ \t]*([A-Za-z0-9_+#.\-]*)[ \t]*$/.exec(lines[i]);
            if (!m) {
                out.push(lines[i]);
                i += 1;
                continue;
            }
            var lang = m[1];
            var buf = [];
            i += 1;
            while (i < lines.length && !/^[ \t]*`{3,}[ \t]*$/.test(lines[i])) {
                buf.push(lines[i]);
                i += 1;
            }
            if (i < lines.length) i += 1;
            store.push(codeBlockHtml(lang, buf.join('\n')));
            out.push(SENT + 'C' + (store.length - 1) + SENT);
        }
        return out.join('\n');
    }

    // --- stage 2: inline spans (run on already-escaped text) -------------------
    function extractInlineCode(text, store) {
        return text.replace(/`+([^`\n]+?)`+/g, function (all, body) {
            store.push('<code class="az-icode">' + body + '</code>');
            return SENT + 'I' + (store.length - 1) + SENT;
        });
    }

    function inline(s) {
        s = s.replace(/\*\*\*([^*\n]+)\*\*\*/g, '<strong><em>$1</em></strong>');
        s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
        s = s.replace(/(^|[\s(\[])\*([^*\n]+)\*(?=$|[\s).,;:!?\]])/g, '$1<em>$2</em>');
        s = s.replace(/(^|[\s(\[])_([^_\n]+)_(?=$|[\s).,;:!?\]])/g, '$1<em>$2</em>');
        s = s.replace(/~~([^~\n]+)~~/g, '<del>$1</del>');
        // Links: the url is taken from escaped text, so quotes are already &quot;
        // and the scheme is pinned to http/https by the pattern itself.
        s = s.replace(/\[([^\]\n]*)\]\((https?:\/\/[^\s)]+)\)/gi, function (all, label, url) {
            return '<a class="az-md-link" href="' + url + '" target="_blank" rel="noopener noreferrer">' +
                (label || url) + '</a>';
        });
        return s;
    }

    // --- stage 3: block structure ---------------------------------------------
    function cells(line) {
        var s = line.trim().replace(/^\|/, '').replace(/\|$/, '');
        return s.split('|').map(function (c) { return c.trim(); });
    }

    function tableHtml(rows) {
        var h = '<table class="az-md-table"><thead><tr>';
        rows[0].forEach(function (c) { h += '<th>' + inline(c) + '</th>'; });
        h += '</tr></thead><tbody>';
        rows.slice(1).forEach(function (r) {
            h += '<tr>';
            r.forEach(function (c) { h += '<td>' + inline(c) + '</td>'; });
            h += '</tr>';
        });
        return h + '</tbody></table>';
    }

    function listHtml(items, ordered) {
        var tag = ordered ? 'ol' : 'ul';
        var h = '<' + tag + ' class="az-md-list">';
        items.forEach(function (it) {
            h += '<li>' + inline(it.text) + it.child + '</li>';
        });
        return h + '</' + tag + '>';
    }

    function indentOf(ws) {
        return ws.replace(/\t/g, '  ').length;
    }

    function parseList(lines, start, baseIndent) {
        var items = [];
        var ordered = null;
        var i = start;
        while (i < lines.length) {
            var m = LIST_RE.exec(lines[i]);
            if (!m) break;
            var ind = indentOf(m[1]);
            if (ind < baseIndent) break;
            if (ind > baseIndent) {
                var sub = parseList(lines, i, ind);
                if (items.length) items[items.length - 1].child = sub.html;
                i = sub.next;
                continue;
            }
            var isOrdered = /\d/.test(m[2].charAt(0));
            if (ordered === null) ordered = isOrdered;
            else if (ordered !== isOrdered) break;
            items.push({ text: m[3], child: '' });
            i += 1;
        }
        return { html: listHtml(items, !!ordered), next: i };
    }

    function isStructural(line) {
        return /^[ \t]*$/.test(line) ||
            /^#{1,6}[ \t]+/.test(line) ||
            LIST_RE.test(line) ||
            QUOTE_RE.test(line) ||
            HR_RE.test(line) ||
            ROW_RE.test(line) ||
            line.indexOf(SENT) === 0;
    }

    function renderBlocks(lines) {
        var out = [];
        var i = 0;
        while (i < lines.length) {
            var line = lines[i];
            if (/^[ \t]*$/.test(line)) { i += 1; continue; }
            if (line.indexOf(SENT) === 0 && /^\u0001C\d+\u0001$/.test(line.trim())) {
                out.push(line.trim());
                i += 1;
                continue;
            }
            if (HR_RE.test(line)) { out.push('<hr class="az-md-hr">'); i += 1; continue; }
            var h = /^(#{1,6})[ \t]+(.*)$/.exec(line);
            if (h) {
                var lv = h[1].length;
                out.push('<h' + lv + ' class="az-md-h az-md-h' + lv + '">' + inline(h[2]) + '</h' + lv + '>');
                i += 1;
                continue;
            }
            if (QUOTE_RE.test(line)) {
                var q = [];
                while (i < lines.length && QUOTE_RE.test(lines[i])) {
                    q.push(lines[i].replace(QUOTE_RE, ''));
                    i += 1;
                }
                out.push('<blockquote class="az-md-quote">' + renderBlocks(q) + '</blockquote>');
                continue;
            }
            if (ROW_RE.test(line) && i + 1 < lines.length && SEP_RE.test(lines[i + 1])) {
                var rows = [cells(line)];
                i += 2;
                while (i < lines.length && ROW_RE.test(lines[i])) {
                    rows.push(cells(lines[i]));
                    i += 1;
                }
                out.push(tableHtml(rows));
                continue;
            }
            if (LIST_RE.test(line)) {
                var lst = parseList(lines, i, indentOf(LIST_RE.exec(line)[1]));
                out.push(lst.html);
                i = lst.next;
                continue;
            }
            var para = [line];
            i += 1;
            while (i < lines.length && !isStructural(lines[i])) {
                para.push(lines[i]);
                i += 1;
            }
            out.push('<p class="az-md-p">' + inline(para.join('\n')).replace(/\n/g, '<br>') + '</p>');
        }
        return out.join('');
    }

    function render(text) {
        var raw = String(text == null ? '' : text).replace(/\r\n?/g, '\n');
        raw = raw.replace(/[\u0000\u0001]/g, '');
        var blocks = [];
        var spans = [];
        var withFences = extractFences(raw, blocks);
        var escaped = extractInlineCode(esc(withFences), spans);
        var html = renderBlocks(escaped.split('\n'));
        return html.replace(TOKEN_RE, function (all, kind, idx) {
            var store = kind === 'C' ? blocks : spans;
            var item = store[Number(idx)];
            return item === undefined ? '' : item;
        });
    }

    window.ZeroMarkdown = { render: render, escape: esc };
}());
