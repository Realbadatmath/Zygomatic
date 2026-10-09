// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* dashboard_expansion.js v1 — Metrics > Expansion (2026-10-04).
 *
 * A census of the program ITSELF: every structural file that runs the whole thing —
 * folders, files per kind and extension, bytes and lines per script / page / stylesheet /
 * config, Python structure, the systemd units per component — plus the prompts the
 * models are driven with and the training data generation is conditioned on. Nothing
 * the program produces is in here; what was excluded is listed with the rule that
 * excluded it.
 *
 * Every number comes from expansion_hub.py; this file only draws, filters and sorts.
 *
 * Payload contract (see expansion_hub.build):
 *   data_version scanned_at scan{} totals{} by_kind[] by_ext[] components[] folders[]
 *   files[{p,c,k,e,b,l,bl,cm,d,cl,r,m,u,pl}] largest[] newest[] structure{}
 *   prompts{groups[],file_rows[],code_rows[],…} training{roots[],totals{}}
 *   services[] excluded[{reason,count,paths[]}] skipped[] rules{} notes[] limitations[]
 */
(function () {
    'use strict';

    var _data = null, _panel = null;
    var _kind = 'all', _comp = 'all', _q = '', _ext = 'all', _shown = 300;
    var _sort = { files: ['l', -1], folders: ['lines', -1] };

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }
    function n0(v) { return (v == null || isNaN(v)) ? '—' : Number(v).toLocaleString('en-GB'); }
    function pct(v) { return (v == null || isNaN(v)) ? '—' : Number(v).toFixed(1) + ' %'; }
    function bytes(b) {
        if (b == null || isNaN(b)) return '—';
        if (b < 1024) return n0(b) + ' B';
        if (b < 1048576) return (b / 1024).toFixed(1) + ' KB';
        if (b < 1073741824) return (b / 1048576).toFixed(1) + ' MB';
        return (b / 1073741824).toFixed(2) + ' GB';
    }
    function plural(n, one, many) { return n0(n) + ' ' + (Number(n) === 1 ? one : (many || one + 's')); }
    function when(ts) {
        if (!ts) return '';
        var d = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts);
        if (isNaN(d)) return String(ts);
        var p = function (x) { return (x < 10 ? '0' : '') + x; };
        return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
    }

    // Kind colours: fixed categorical slots in the dashboard's validated order (see
    // dashboard_tab_metrics.js). Colour follows the kind, never its rank.
    var KIND_COLOR = { code: '#2a78d6', config: '#eb6834', prompt: '#1baf7a', docs: '#eda100', table: '#8a63d2', asset: '#898781', other: '#bdbbb3' };
    var KIND_SHORT = { code: 'Code', config: 'Config', prompt: 'Prompts', docs: 'Docs', table: 'Tables', asset: 'GUI assets', other: 'Other' };

    function tile(lab, val, sub) {
        return '<div class="mh-tile"><div class="mh-tile-label">' + esc(lab) + '</div>' +
            '<div class="mh-tile-value">' + esc(val) + '</div>' +
            (sub ? '<div class="mh-tile-sub">' + esc(sub) + '</div>' : '') + '</div>';
    }
    function card(title, body, aside, cls, id) {
        return '<section class="mh-card' + (cls ? ' ' + cls : '') + '"' + (id ? ' id="' + id + '"' : '') + '><header class="mh-card-head">' +
            '<h4>' + esc(title) + '</h4>' + (aside ? '<span class="mh-card-aside">' + esc(aside) + '</span>' : '') +
            '</header>' + body + '</section>';
    }
    function kindPill(k) {
        return '<span class="exp-kind"><i style="background:' + (KIND_COLOR[k] || KIND_COLOR.other) + '"></i>' + esc(KIND_SHORT[k] || k) + '</span>';
    }
    function th(label, key, num, table) {
        var s = _sort[table];
        var on = s && s[0] === key;
        return '<th class="' + (num ? 'num ' : '') + 'exp-sortable' + (on ? ' on' : '') + '" data-sort="' + esc(key) + '" data-table="' + table + '" tabindex="0" ' +
            'title="Sort by ' + esc(label) + '">' + esc(label) + (on ? '<span class="exp-dir">' + (s[1] < 0 ? '▼' : '▲') + '</span>' : '') + '</th>';
    }

    // ── kind strip: one stacked bar of lines + one of files, with a table twin ──
    function kindStrip(d) {
        var kinds = d.by_kind || [];
        var tl = (d.totals || {}).lines || 1, tf = (d.totals || {}).files || 1, tb = (d.totals || {}).bytes || 1;
        function bar(key, total, fmt) {
            return '<div class="exp-stack" role="img" aria-label="' + esc(key) + ' by kind">' + kinds.map(function (k) {
                var w = 100 * k[key] / total;
                return '<span style="width:' + w.toFixed(2) + '%;background:' + KIND_COLOR[k.kind] + '" title="' +
                    esc(KIND_SHORT[k.kind] + ': ' + fmt(k[key]) + ' (' + w.toFixed(1) + ' %)') + '"></span>';
            }).join('') + '</div>';
        }
        var legend = '<div class="exp-legend">' + kinds.map(function (k) {
            return '<span><i style="background:' + KIND_COLOR[k.kind] + '"></i>' + esc(KIND_SHORT[k.kind]) + ' <em>' + pct(k.share_lines) + ' of lines</em></span>';
        }).join('') + '</div>';
        var rows = kinds.map(function (k) {
            return '<tr><td>' + kindPill(k.kind) + ' <span class="exp-muted">' + esc(k.label) + '</span></td>' +
                '<td class="num">' + n0(k.files) + '</td><td class="num">' + pct(100 * k.files / tf) + '</td>' +
                '<td class="num">' + n0(k.lines) + '</td><td class="num">' + pct(k.share_lines) + '</td>' +
                '<td class="num">' + bytes(k.bytes) + '</td><td class="num">' + pct(100 * k.bytes / tb) + '</td></tr>';
        }).join('');
        return '<div class="exp-strips">' +
            '<div class="exp-strip"><h5>Lines, by kind</h5>' + bar('lines', tl, n0) + '</div>' +
            '<div class="exp-strip"><h5>Files, by kind</h5>' + bar('files', tf, n0) + '</div>' +
            '<div class="exp-strip"><h5>Bytes, by kind</h5>' + bar('bytes', tb, bytes) + '</div>' +
            '</div>' + legend +
            '<div class="exp-tablewrap"><table class="exp-table"><thead><tr><th>Kind</th><th class="num">Files</th><th class="num">Share</th>' +
            '<th class="num">Lines</th><th class="num">Share</th><th class="num">Bytes</th><th class="num">Share</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
    }

    // ── per extension ────────────────────────────────────────────────────────
    function extTable(d) {
        var rows = (d.by_ext || []).map(function (e) {
            return '<tr><td><code>' + esc(e.ext) + '</code></td><td>' + kindPill(e.kind) + '</td>' +
                '<td class="num">' + n0(e.files) + '</td><td class="num">' + n0(e.lines) + '</td><td class="num">' + bytes(e.bytes) + '</td>' +
                '<td class="num">' + n0(e.min_lines) + '</td><td class="num">' + n0(e.median_lines) + '</td><td class="num">' + n0(e.max_lines) + '</td>' +
                '<td class="exp-path" title="' + esc(e.largest) + '">' + esc(e.largest) + '</td></tr>';
        }).join('');
        return '<div class="exp-tablewrap exp-scroll"><table class="exp-table"><thead><tr><th>Extension</th><th>Kind</th><th class="num">Files</th>' +
            '<th class="num">Lines</th><th class="num">Bytes</th><th class="num">Min lines</th><th class="num">Median</th><th class="num">Max</th><th>Largest file</th></tr></thead><tbody>' +
            rows + '</tbody></table></div>';
    }

    // ── components + services ────────────────────────────────────────────────
    function componentsTable(d) {
        var rows = (d.components || []).map(function (c) {
            return '<tr' + (c.missing ? ' class="exp-missing"' : '') + '><td><strong>' + esc(c.label) + '</strong>' +
                (c.missing ? ' <em class="exp-muted">(root not found)</em>' : '') + '<br><code class="exp-root">' + esc(c.root) + '</code></td>' +
                '<td class="num">' + n0(c.dirs) + '</td><td class="num">' + n0(c.files) + '</td><td class="num">' + n0(c.lines) + '</td><td class="num">' + bytes(c.bytes) + '</td>' +
                '<td class="num">' + n0(c.py) + '</td><td class="num">' + n0(c.js) + '</td><td class="num">' + n0(c.html) + '</td><td class="num">' + n0(c.json) + '</td>' +
                '<td>' + (c.services || []).map(function (s) { return '<span class="exp-unit">' + esc(s) + '</span>'; }).join(' ') + '</td></tr>';
        }).join('');
        return '<div class="exp-tablewrap"><table class="exp-table"><thead><tr><th>Component (root)</th><th class="num">Folders</th><th class="num">Files</th>' +
            '<th class="num">Lines</th><th class="num">Bytes</th><th class="num">.py</th><th class="num">.js</th><th class="num">.html</th><th class="num">.json</th><th>Run by</th></tr></thead><tbody>' +
            rows + '</tbody></table></div>';
    }
    function servicesTable(d) {
        var compName = {};
        (d.components || []).forEach(function (c) { compName[c.id] = c.label; });
        var rows = (d.services || []).map(function (s) {
            var st = s.state || 'unknown';
            var cls = st.indexOf('active (running)') === 0 ? 'exp-st-ok' : (st.indexOf('failed') >= 0 ? 'exp-st-bad' : 'exp-st-off');
            var who = s.component ? compName[s.component] || s.component : (s.third_party ? 'third-party engine' : 'not part of the program');
            return '<tr' + (s.component ? '' : ' class="exp-muted-row"') + '><td><code>' + esc(s.unit) + '</code> <span class="exp-scope">' + esc(s.scope) + '</span></td>' +
                '<td><span class="exp-st ' + cls + '">' + esc(st) + '</span></td><td>' + esc(who) + '</td>' +
                '<td class="exp-path" title="' + esc(s.exec) + '">' + esc(s.exec) + '</td></tr>';
        }).join('');
        return '<div class="exp-tablewrap exp-scroll"><table class="exp-table"><thead><tr><th>Unit</th><th>State</th><th>Component</th><th>ExecStart</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
    }

    // ── folders ──────────────────────────────────────────────────────────────
    function folderRows(d) {
        var s = _sort.folders;
        var rows = (d.folders || []).filter(function (r) {
            if (_comp !== 'all' && r.comp !== _comp) return false;
            return r.depth > 0;
        }).slice();
        rows.sort(function (a, b) {
            var x = a[s[0]], y = b[s[0]];
            if (typeof x === 'string') return s[1] * x.localeCompare(y);
            return s[1] * ((x || 0) - (y || 0));
        });
        var compName = {};
        (d.components || []).forEach(function (c) { compName[c.id] = c.label; });
        return rows.map(function (r) {
            var k = r.kinds || {};
            return '<tr class="exp-depth-' + r.depth + '"><td><code>' + esc(r.folder) + '</code>' +
                (_comp === 'all' ? ' <span class="exp-scope">' + esc(compName[r.comp] || r.comp) + '</span>' : '') + '</td>' +
                '<td class="num">' + n0(r.dirs) + '</td><td class="num">' + n0(r.files) + '</td><td class="num">' + n0(r.lines) + '</td><td class="num">' + bytes(r.bytes) + '</td>' +
                '<td class="num">' + n0(k.code || 0) + '</td><td class="num">' + n0(k.config || 0) + '</td><td class="num">' + n0(k.prompt || 0) + '</td>' +
                '<td class="num">' + n0(k.docs || 0) + '</td><td class="num">' + n0(k.asset || 0) + '</td><td class="exp-muted">' + esc(r.top_exts) + '</td></tr>';
        }).join('') || '<tr><td colspan="11" class="exp-empty">No folder matches.</td></tr>';
    }
    function foldersTable(d) {
        return '<div class="exp-tablewrap exp-scroll"><table class="exp-table" id="exp-folders"><thead><tr>' +
            th('Folder (depth 1 and 2)', 'folder', false, 'folders') + th('Sub-folders', 'dirs', true, 'folders') + th('Files', 'files', true, 'folders') +
            th('Lines', 'lines', true, 'folders') + th('Bytes', 'bytes', true, 'folders') +
            '<th class="num">Code</th><th class="num">Config</th><th class="num">Prompts</th><th class="num">Docs</th><th class="num">Assets</th><th>Top extensions</th>' +
            '</tr></thead><tbody>' + folderRows(d) + '</tbody></table></div>';
    }

    // ── every file ───────────────────────────────────────────────────────────
    function fileFilter(f) {
        if (_kind !== 'all' && f.k !== _kind) return false;
        if (_comp !== 'all' && f.c !== _comp) return false;
        if (_ext !== 'all' && f.e !== _ext) return false;
        if (_q && f.p.toLowerCase().indexOf(_q) < 0) return false;
        return true;
    }
    function fileRows(d) {
        var s = _sort.files;
        var rows = (d.files || []).filter(fileFilter);
        rows.sort(function (a, b) {
            var x = a[s[0]], y = b[s[0]];
            if (typeof x === 'string' || typeof y === 'string') return s[1] * String(x || '').localeCompare(String(y || ''));
            return s[1] * ((x || 0) - (y || 0));
        });
        var total = rows.length, sumL = 0, sumB = 0;
        rows.forEach(function (r) { sumL += r.l; sumB += r.b; });
        var html = rows.slice(0, _shown).map(function (f) {
            var extra = f.e === 'py' ? (n0(f.d) + ' def · ' + n0(f.cl) + ' class' + (f.r ? ' · ' + n0(f.r) + ' routes' : '') + (f.pl ? ' · ' + n0(f.pl) + ' prompt lit.' : '')) :
                (f.k === 'prompt' && f.u != null ? plural(f.u, 'prompt') : (f.d != null ? n0(f.d) + ' fn' : ''));
            return '<tr><td class="exp-path" title="' + esc(f.p) + '">' + esc(f.p) + '</td><td>' + kindPill(f.k) + '</td><td><code>' + esc(f.e) + '</code></td>' +
                '<td class="num">' + n0(f.l) + '</td><td class="num">' + n0(f.bl) + '</td><td class="num">' + n0(f.cm) + '</td><td class="num">' + bytes(f.b) + '</td>' +
                '<td class="exp-muted exp-nowrap">' + esc(extra) + '</td><td class="exp-nowrap exp-muted">' + esc(when(f.m)) + '</td></tr>';
        }).join('') || '<tr><td colspan="9" class="exp-empty">No file matches.</td></tr>';
        return { html: html, total: total, lines: sumL, bytes: sumB, shown: Math.min(_shown, total) };
    }
    function filesCard(d) {
        var exts = {};
        (d.files || []).forEach(function (f) { exts[f.e] = (exts[f.e] || 0) + 1; });
        var extOpts = Object.keys(exts).sort(function (a, b) { return exts[b] - exts[a]; }).map(function (e) {
            return '<option value="' + esc(e) + '"' + (_ext === e ? ' selected' : '') + '>' + esc(e) + ' (' + exts[e] + ')</option>';
        }).join('');
        var kinds = ['all'].concat((d.by_kind || []).map(function (k) { return k.kind; }));
        var kindChips = kinds.map(function (k) {
            return '<button type="button" class="exp-chip' + (_kind === k ? ' on' : '') + '" data-kind="' + esc(k) + '">' +
                (k === 'all' ? 'All kinds' : '<i style="background:' + KIND_COLOR[k] + '"></i>' + esc(KIND_SHORT[k])) + '</button>';
        }).join('');
        var compChips = '<button type="button" class="exp-chip' + (_comp === 'all' ? ' on' : '') + '" data-comp="all">All components</button>' +
            (d.components || []).filter(function (c) { return !c.missing; }).map(function (c) {
                return '<button type="button" class="exp-chip' + (_comp === c.id ? ' on' : '') + '" data-comp="' + esc(c.id) + '">' + esc(c.label) + ' <em>' + n0(c.files) + '</em></button>';
            }).join('');
        var r = fileRows(d);
        var controls = '<div class="exp-controls"><div class="exp-chips">' + kindChips + '</div><div class="exp-chips">' + compChips + '</div>' +
            '<div class="exp-tools"><label class="exp-search"><span aria-hidden="true">⌕</span><input type="search" id="exp-q" value="' + esc(_q) +
            '" placeholder="search a path…" aria-label="Filter files by path"></label>' +
            '<label class="exp-select">Extension <select id="exp-ext"><option value="all">any</option>' + extOpts + '</select></label>' +
            '<span class="exp-count" id="exp-count"></span></div></div>';
        var table = '<div class="exp-tablewrap exp-scroll exp-files"><table class="exp-table" id="exp-files-table"><thead><tr>' +
            th('Path', 'p', false, 'files') + th('Kind', 'k', false, 'files') + th('Ext', 'e', false, 'files') + th('Lines', 'l', true, 'files') +
            th('Blank', 'bl', true, 'files') + th('Comment', 'cm', true, 'files') + th('Bytes', 'b', true, 'files') + '<th>Structure</th>' + th('Modified', 'm', false, 'files') +
            '</tr></thead><tbody>' + r.html + '</tbody></table></div>' +
            '<div class="exp-more"><button type="button" class="exp-btn" id="exp-more"' + (r.shown >= r.total ? ' disabled' : '') + '>Show 300 more</button></div>';
        return controls + table;
    }
    function countText(r) {
        return n0(r.shown) + ' of ' + plural(r.total, 'file') + ' shown · ' + plural(r.lines, 'line') + ' · ' + bytes(r.bytes) + (r.total === (_data.files || []).length ? ' — no filter' : ' in this filter');
    }

    // ── python structure ─────────────────────────────────────────────────────
    function structureTiles(d) {
        var s = d.structure || {};
        return '<div class="mh-tiles exp-tiles">' +
            tile('Python modules', n0(s.py_modules), plural(s.py_lines, 'line') + ' · ' + bytes(s.py_bytes)) +
            tile('Functions', n0(s.functions), plural(s.classes, 'class', 'classes')) +
            tile('HTTP routes', n0(s.routes), plural(s.blueprints, 'blueprint module')) +
            tile('Entry points', n0(s.entry_points), 'modules with a __main__ block') +
            tile('Test modules', n0(s.tests), plural(s.test_lines, 'line') + ' · ' + n0(s.capability_tests) + ' capability tests') +
            tile('JavaScript', n0(s.js_files), plural(s.js_lines, 'line') + ' · ' + n0(s.js_functions) + ' functions/arrows') +
            tile('HTML pages & templates', n0(s.html_files), plural(s.html_lines, 'line') + ' · ' + n0(s.templates) + ' under templates/ · ' + n0(s.html_includes) + ' includes') +
            tile('Stylesheets', n0(s.css_files), plural(s.css_lines, 'line')) +
            tile('Shell scripts', n0(s.shell_scripts), n0(s.sql_migrations) + ' alembic migrations') +
            tile('ComfyUI graphs', n0(s.comfy_workflows), n0(s.blender_scripts) + ' blender-side python files') +
            '</div>';
    }

    // ── prompts ──────────────────────────────────────────────────────────────
    function promptsCard(d) {
        var p = d.prompts || {};
        var tiles = '<div class="mh-tiles exp-tiles">' +
            tile('Prompt files', n0(p.files), plural(p.units, 'prompt unit') + ' · ' + plural(p.lines, 'line') + ' · ' + bytes(p.bytes)) +
            tile('Prompt literals in code', n0(p.in_code_literals), 'in ' + plural(p.in_code_files, 'python file') + ' · ' + n0(p.in_code_chars) + ' characters · ' + plural(p.in_code_lines, 'line')) +
            (p.groups || []).map(function (g) { return tile(g.group, n0(g.units), plural(g.files, 'file') + ' · ' + plural(g.lines, 'line')); }).join('') +
            '</div>';
        var fileRowsHtml = (p.file_rows || []).map(function (f) {
            return '<tr><td class="exp-path" title="' + esc(f.path) + '">' + esc(f.path) + '</td><td><code>' + esc(f.ext) + '</code></td>' +
                '<td class="num">' + n0(f.units) + '</td><td class="exp-muted">' + esc(f.rule) + '</td><td class="num">' + n0(f.lines) + '</td><td class="num">' + bytes(f.bytes) + '</td></tr>';
        }).join('');
        var codeRowsHtml = (p.code_rows || []).map(function (f) {
            return '<tr><td class="exp-path" title="' + esc(f.path) + '">' + esc(f.path) + '</td><td class="num">' + n0(f.literals) + '</td>' +
                '<td class="num">' + n0(f.chars) + '</td><td class="num">' + n0(f.lines) + '</td><td class="num">' + n0(f.file_lines) + '</td>' +
                '<td class="num">' + pct(f.file_lines ? 100 * f.lines / f.file_lines : 0) + '</td></tr>';
        }).join('');
        return tiles +
            '<details class="exp-twin" open><summary>Prompt files — ' + plural(p.files, 'file') + '</summary>' +
            '<div class="exp-tablewrap exp-scroll"><table class="exp-table"><thead><tr><th>File</th><th>Ext</th><th class="num">Prompts</th><th>Counted as</th><th class="num">Lines</th><th class="num">Bytes</th></tr></thead><tbody>' +
            fileRowsHtml + '</tbody></table></div></details>' +
            '<details class="exp-twin"><summary>Prompt literals inside Python — ' + plural(p.in_code_files, 'file') + ' (AST, not grep)</summary>' +
            '<div class="exp-tablewrap exp-scroll"><table class="exp-table"><thead><tr><th>Python file</th><th class="num">Literals</th><th class="num">Characters</th><th class="num">Prompt lines</th><th class="num">File lines</th><th class="num">Share</th></tr></thead><tbody>' +
            codeRowsHtml + '</tbody></table></div></details>';
    }

    // ── training data ────────────────────────────────────────────────────────
    function trainingCard(d) {
        var t = d.training || {};
        var tot = t.totals || {};
        var tiles = '<div class="mh-tiles exp-tiles">' +
            tile('Datasets', n0(tot.datasets), 'first-level folders under the training roots, backups excluded') +
            tile('Size on disk', bytes(tot.bytes), plural(tot.files, 'file')) +
            tile('Images', n0(tot.images), plural(tot.captions, 'caption')) +
            tile('Audio clips', n0(tot.audio), plural(tot.video, 'video clip')) +
            tile('Manifests', n0(tot.manifests), 'json / toml / yaml / csv / md beside the samples') +
            '</div>';
        var sections = (t.roots || []).map(function (r) {
            if (!r.present) return '<p class="exp-empty">' + esc(r.label) + ': <code>' + esc(r.root) + '</code> is not on this box.</p>';
            var rows = (r.datasets || []).map(function (s) {
                return '<tr' + (s.backup ? ' class="exp-muted-row"' : '') + '><td><code>' + esc(s.name) + '</code>' + (s.backup ? ' <em class="exp-muted">backup / quarantine, not counted as a dataset</em>' : '') + '</td>' +
                    '<td class="num">' + n0(s.files) + '</td><td class="num">' + bytes(s.bytes) + '</td><td class="num">' + n0(s.images) + '</td><td class="num">' + n0(s.captions) + '</td>' +
                    '<td class="num">' + n0(s.audio) + '</td><td class="num">' + n0(s.video) + '</td><td class="num">' + n0(s.manifests) + '</td><td class="num">' + n0(s.other) + '</td>' +
                    '<td class="exp-nowrap exp-muted">' + esc(s.newest) + '</td></tr>';
            }).join('');
            return '<h5 class="exp-h5">' + esc(r.label) + ' <code class="exp-root">' + esc(r.root) + '</code></h5><p class="exp-note">' + esc(r.note) + ' — ' + plural(r.files, 'file') + ', ' + bytes(r.bytes) + '.</p>' +
                '<div class="exp-tablewrap"><table class="exp-table"><thead><tr><th>Dataset</th><th class="num">Files</th><th class="num">Bytes</th><th class="num">Images</th><th class="num">Captions</th>' +
                '<th class="num">Audio</th><th class="num">Video</th><th class="num">Manifests</th><th class="num">Other</th><th>Newest file</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
        }).join('');
        return tiles + sections;
    }

    // ── excluded ─────────────────────────────────────────────────────────────
    function excludedCard(d) {
        var ex = (d.excluded || []).map(function (e) {
            return '<details class="exp-twin"><summary>' + plural(e.count, 'folder') + ' — ' + esc(e.reason) + '</summary><ul class="exp-paths">' +
                e.paths.map(function (p) { return '<li><code>' + esc(p) + '</code></li>'; }).join('') + '</ul></details>';
        }).join('');
        var sk = '<div class="exp-tablewrap"><table class="exp-table"><thead><tr><th>Skipped files inside the structural tree</th><th class="num">Files</th><th class="num">Bytes</th></tr></thead><tbody>' +
            (d.skipped || []).map(function (s) { return '<tr><td>' + esc(s.reason) + '</td><td class="num">' + n0(s.files) + '</td><td class="num">' + bytes(s.bytes) + '</td></tr>'; }).join('') +
            '</tbody></table></div>';
        var rules = d.rules || {};
        var ruleTxt = '<details class="exp-twin"><summary>The rules</summary><dl class="exp-rules">' +
            '<dt>Pruned folder names</dt><dd>' + esc((rules.prune_dirs || []).join(', ')) + '</dd>' +
            '<dt>Kept under the crews data root</dt><dd>' + esc(JSON.stringify(rules.crews_data_keep || {})) + '</dd>' +
            '<dt>Skipped extensions</dt><dd>' + Object.keys(rules.skip_ext || {}).map(function (k) { return '<b>' + esc(k) + '</b>: ' + esc(rules.skip_ext[k].join(' ')); }).join('<br>') + '</dd>' +
            '<dt>GUI asset folders</dt><dd>' + esc((rules.asset_dirs || []).join(', ')) + '</dd>' +
            '<dt>Prompt name pattern</dt><dd><code>' + esc(rules.prompt_name) + '</code></dd>' +
            '<dt>Training roots</dt><dd>' + esc((rules.training_roots || []).join(' · ')) + '</dd>' +
            '<dt>Hand-listed files inside pruned trees</dt><dd>' + esc((rules.extra_files || []).join(' · ')) + '</dd></dl></details>';
        return ex + sk + ruleTxt;
    }

    // ── the page ─────────────────────────────────────────────────────────────
    function html(d) {
        _data = d;
        var t = d.totals || {};
        var sc = d.scan || {};
        var tiles = '<div class="mh-tiles exp-tiles">' +
            tile('Structural files', n0(t.files), plural(t.dirs, 'folder') + ' · ' + plural(t.components, 'component')) +
            tile('Lines of text', n0(t.lines), n0(t.blank) + ' blank · ' + n0(t.comment) + ' comment') +
            tile('Size on disk', bytes(t.bytes), 'structural files only') +
            tile('Python files', n0(t.py), n0(t.js) + ' js · ' + n0(t.html) + ' html · ' + n0(t.css) + ' css') +
            tile('JSON files', n0(t.json), n0(t.yaml) + ' yaml · ' + n0(t.md) + ' md · ' + n0(t.sh) + ' sh') +
            tile('Services', n0(t.services), n0(t.services_active) + ' active · systemd user + system') +
            tile('Prompts', n0(t.prompt_units), plural(t.prompt_files, 'file') + ' + ' + n0(t.prompt_literals) + ' literals in code') +
            tile('Training data', bytes(t.training_bytes), plural(t.training_datasets, 'dataset') + ' · ' + plural(t.training_files, 'file')) +
            tile('Excluded', n0(t.excluded_dirs) + ' folders', n0(t.skipped_files) + ' generated / binary files skipped inside the tree (' + bytes(t.skipped_bytes) + ')') +
            '</div>';
        var largest = '<div class="exp-tablewrap exp-scroll"><table class="exp-table"><thead><tr><th>#</th><th>File</th><th>Kind</th><th class="num">Lines</th><th class="num">Bytes</th></tr></thead><tbody>' +
            (d.largest || []).map(function (f, i) {
                return '<tr><td class="num">' + (i + 1) + '</td><td class="exp-path" title="' + esc(f.path) + '">' + esc(f.path) + '</td><td>' + kindPill(f.kind) + '</td><td class="num">' + n0(f.lines) + '</td><td class="num">' + bytes(f.bytes) + '</td></tr>';
            }).join('') + '</tbody></table></div>';
        var newest = '<div class="exp-tablewrap exp-scroll"><table class="exp-table"><thead><tr><th>File</th><th class="num">Lines</th><th>Modified</th></tr></thead><tbody>' +
            (d.newest || []).map(function (f) {
                return '<tr><td class="exp-path" title="' + esc(f.path) + '">' + esc(f.path) + '</td><td class="num">' + n0(f.lines) + '</td><td class="exp-nowrap exp-muted">' + esc(f.mtime) + '</td></tr>';
            }).join('') + '</tbody></table></div>';
        var foot = card('How this is counted',
            '<ul class="mh-notes">' + (d.notes || []).map(function (n) { return '<li>' + esc(n) + '</li>'; }).join('') + '</ul>' +
            '<h6 class="exp-foot-h">Limits</h6><ul class="mh-notes">' + (d.limitations || []).map(function (n) { return '<li>' + esc(n) + '</li>'; }).join('') + '</ul>' +
            '<p class="exp-note">Scanned ' + esc(d.scanned_at) + ' — walk ' + n0(sc.walk_ms) + ' ms, ' + n0(sc.files_read) + ' files read, ' + n0(sc.files_from_cache) +
            ' from the cache at <code>' + esc(sc.cache_path) + '</code>. CLI: <code>python3 expansion_hub.py [--fresh]</code>.</p>', '', 'exp-foot');

        return '<div class="exp">' + tiles +
            card('What the program is made of', kindStrip(d), 'structural files by kind — lines, files and bytes') +
            card('Components and what runs them', componentsTable(d) + '<h5 class="exp-h5">Systemd units</h5>' + servicesTable(d),
                plural(t.components, 'component') + ' read off ' + plural((d.services || []).length, 'service unit')) +
            card('Python, JavaScript and pages', structureTiles(d), 'regex counts at line start — see Limits') +
            card('Folders', foldersTable(d), 'every folder at depth 1 and 2 under each component, totals include everything below it', 'exp-folders-card') +
            card('Every file', filesCard(d), 'lines, blank, comment and bytes for each structural file', 'exp-files-card') +
            card('Largest files by lines', largest, 'top 40') +
            card('Most recently changed', newest, 'top 25 by mtime') +
            card('Prompts for the models', promptsCard(d), 'prompt files + prompt literals inside the Python code', 'exp-prompts-card') +
            card('Training data used structurally', trainingCard(d), 'LoRA datasets and TTS voice seeds — counted, never read', 'exp-training-card') +
            card('What was excluded, and why', excludedCard(d), plural(t.excluded_dirs, 'folder') + ' pruned · ' + plural(t.skipped_files, 'file') + ' skipped', 'exp-excluded-card') +
            foot + '</div>';
    }

    // ── interaction ──────────────────────────────────────────────────────────
    function refreshFiles() {
        if (!_panel || !_data) return;
        var tb = _panel.querySelector('#exp-files-table tbody');
        var r = fileRows(_data);
        if (tb) tb.innerHTML = r.html;
        var c = _panel.querySelector('#exp-count');
        if (c) c.textContent = countText(r);
        var more = _panel.querySelector('#exp-more');
        if (more) more.disabled = r.shown >= r.total;
        _panel.querySelectorAll('#exp-files-table th.exp-sortable').forEach(function (h) {
            var on = h.getAttribute('data-sort') === _sort.files[0];
            h.classList.toggle('on', on);
            var dir = h.querySelector('.exp-dir');
            if (dir) dir.remove();
            if (on) h.insertAdjacentHTML('beforeend', '<span class="exp-dir">' + (_sort.files[1] < 0 ? '▼' : '▲') + '</span>');
        });
    }
    function refreshFolders() {
        if (!_panel || !_data) return;
        var tb = _panel.querySelector('#exp-folders tbody');
        if (tb) tb.innerHTML = folderRows(_data);
        _panel.querySelectorAll('#exp-folders th.exp-sortable').forEach(function (h) {
            var on = h.getAttribute('data-sort') === _sort.folders[0];
            h.classList.toggle('on', on);
            var dir = h.querySelector('.exp-dir');
            if (dir) dir.remove();
            if (on) h.insertAdjacentHTML('beforeend', '<span class="exp-dir">' + (_sort.folders[1] < 0 ? '▼' : '▲') + '</span>');
        });
    }
    function chipRow(el, attr, value) {
        el.parentNode.querySelectorAll('.exp-chip').forEach(function (b) { b.classList.toggle('on', b.getAttribute(attr) === value); });
    }
    function sortBy(table, key) {
        var s = _sort[table];
        if (s[0] === key) s[1] = -s[1];
        else _sort[table] = [key, (key === 'p' || key === 'k' || key === 'e' || key === 'folder') ? 1 : -1];
        if (table === 'files') { _shown = 300; refreshFiles(); } else refreshFolders();
    }

    // ── board lifecycle ──────────────────────────────────────────────────────
    function same(panel, data) { return !!(_data && data && _data.data_version === data.data_version); }
    function touch(panel, data) {
        if (data && _data) { _data.generated_at = data.generated_at; _data.compute_ms = data.compute_ms; }
    }
    function mount(panel, data) {
        _panel = panel;
        _data = data;
        refreshFiles();
        if (panel.__expBound) return;
        panel.__expBound = true;
        panel.addEventListener('click', function (ev) {
            var k = ev.target.closest('.exp-chip[data-kind]');
            if (k) { _kind = k.getAttribute('data-kind'); chipRow(k, 'data-kind', _kind); _shown = 300; refreshFiles(); return; }
            var c = ev.target.closest('.exp-chip[data-comp]');
            if (c) { _comp = c.getAttribute('data-comp'); chipRow(c, 'data-comp', _comp); _shown = 300; refreshFiles(); refreshFolders(); return; }
            var h = ev.target.closest('th.exp-sortable');
            if (h) { sortBy(h.getAttribute('data-table'), h.getAttribute('data-sort')); return; }
            var m = ev.target.closest('#exp-more');
            if (m) { _shown += 300; refreshFiles(); }
        });
        panel.addEventListener('keydown', function (ev) {
            if (ev.key !== 'Enter' && ev.key !== ' ') return;
            var h = ev.target.closest && ev.target.closest('th.exp-sortable');
            if (h) { ev.preventDefault(); sortBy(h.getAttribute('data-table'), h.getAttribute('data-sort')); }
        });
        panel.addEventListener('input', function (ev) {
            if (ev.target.id === 'exp-q') { _q = String(ev.target.value || '').toLowerCase().trim(); _shown = 300; refreshFiles(); }
        });
        panel.addEventListener('change', function (ev) {
            if (ev.target.id === 'exp-ext') { _ext = ev.target.value; _shown = 300; refreshFiles(); }
        });
    }
    function close() { }
    function redraw() { }

    window.DashboardExpansion = { html: html, mount: mount, same: same, touch: touch, close: close, redraw: redraw };
})();
