// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Dashboard tab: Error Logs
 * Circular progress bars: AI model fails, GPU memory overflows, Timeouts, API errors, Test System (placeholder).
 * Click bar opens dialog with data.
 */
(function () {
    'use strict';

    var BARS = [
        { id: 'ai_model_fails', label: 'AI model fails', script: 'ai_model_fails' },
        { id: 'gpu_memory_overflows', label: 'GPU Overflow', script: 'gpu_memory_overflows' },
        { id: 'timeouts', label: 'Timeouts', script: 'timeouts' },
        { id: 'api_errors', label: 'API errors', script: 'api_errors' },
        { id: 'high_risk_errors', label: 'High Risk Errors', script: 'high_risk_errors' },
        { id: 'medium_risk_errors', label: 'Medium Risk Errors', script: 'medium_risk_errors' },
        { id: 'low_risk_errors', label: 'Low Risk Errors', script: 'low_risk_errors' }
    ];

    function byId(id) { return document.getElementById(id); }

    function renderCircularBar(percent, label) {
        var p = Math.min(100, Math.max(0, percent));
        var r = 50;
        var c = 2 * Math.PI * r;
        var offset = c - (p / 100) * c;
        return '<div class="dashboard-circle-wrap">' +
            '<svg class="dashboard-circle-svg" viewBox="0 0 120 120">' +
            '<circle class="dashboard-circle-bg" cx="60" cy="60" r="' + r + '"/>' +
            '<circle class="dashboard-circle-mover" cx="60" cy="60" r="' + r + '"/>' +
            '<circle class="dashboard-circle-fill" cx="60" cy="60" r="' + r + '" stroke-dasharray="' + c + '" stroke-dashoffset="' + offset + '"/>' +
            '</svg>' +
            '<span class="dashboard-circle-value">' + Math.round(p) + '</span>' +
            '<span class="dashboard-circle-label">' + label + '</span>' +
            '</div>';
    }

    var ERROR_COLUMNS = ['Error-ID', 'Timestamp', 'Type', 'Message', 'Details'];
    var groupBy = ''; // '' | 'agent' | 'model' | 'error_type'

    function getGroupKey(row) {
        if (typeof row !== 'object' || row === null) return '—';
        if (groupBy === 'agent')      return (row.agent || '—') + '';
        if (groupBy === 'model')      return (row.model || '—') + '';
        if (groupBy === 'error_type') return (row.level || row.type || '—') + '';
        return '—';
    }

    function rowFields(row, title) {
        /* API schema: {ts, msg, level, stage, pipeline_id} */
        if (typeof row !== 'object' || row === null) {
            return {errorId: '—', ts: '—', type: title || '—', msg: String(row || '—'), details: '—'};
        }
        var errorId = (row.pipeline_id || row.error_id || row.id || '—');
        if (errorId.length > 20) errorId = errorId.slice(0, 8) + '…';
        var ts      = (row.ts || row.timestamp || '—');
        if (ts !== '—') ts = String(ts).replace('T', ' ').slice(0, 19);
        var type    = (row.level || row.type || title || '—');
        var msg     = (row.msg || row.message || JSON.stringify(row));
        var details = (row.stage || row.details || '—');
        return {errorId: errorId, ts: ts, type: type, msg: msg, details: details};
    }

    function openDialog(title, items) {
        var list = Array.isArray(items) ? items : [];
        var rows = [];
        if (groupBy) {
            var groups = {};
            list.forEach(function (row) {
                var key = getGroupKey(row);
                if (!groups[key]) groups[key] = [];
                groups[key].push(row);
            });
            var keys = Object.keys(groups).sort();
            var maxGroups = 15;
            var maxPerGroup = 8;
            for (var g = 0; g < Math.min(keys.length, maxGroups); g++) {
                var k = keys[g];
                var grp = groups[k];
                rows.push('<tr class="dashboard-error-group-header"><td colspan="5" style="background:#f0f0f0;font-weight:700;padding:6px 10px;"><strong>' + k + '</strong> (' + grp.length + ')</td></tr>');
                for (var j = 0; j < Math.min(grp.length, maxPerGroup); j++) {
                    var f = rowFields(grp[j], title);
                    rows.push('<tr><td><code title="' + f.errorId + '">' + f.errorId + '</code></td><td style="white-space:nowrap;">' + f.ts + '</td><td>' + f.type + '</td><td style="word-break:break-word;max-width:340px;">' + f.msg + '</td><td>' + f.details + '</td></tr>');
                }
            }
        } else {
            for (var i = 0; i < list.length; i++) {
                var f = rowFields(list[i], title);
                rows.push('<tr><td><code title="' + f.errorId + '">' + f.errorId + '</code></td><td style="white-space:nowrap;">' + f.ts + '</td><td>' + f.type + '</td><td style="word-break:break-word;max-width:340px;">' + f.msg + '</td><td>' + f.details + '</td></tr>');
            }
            if (!rows.length) rows.push('<tr><td colspan="5" style="text-align:center;padding:20px;color:#888;">No entries.</td></tr>');
        }
        var tableBody = rows.join('');
        var ths = ERROR_COLUMNS.map(function (h) { return '<th>' + h + '</th>'; }).join('');
        var html = '<div class="dashboard-dialog-overlay" id="dashboard-error-dialog">' +
            '<div class="dashboard-dialog dashboard-dialog-large dashboard-dialog-light">' +
            '<h3>' + title + '</h3>' +
            '<div class="parameter-control-table-wrap"><table class="dashboard-table" style="width:100%;"><thead><tr>' + ths + '</tr></thead><tbody>' + tableBody + '</tbody></table></div>' +
            '<button type="button" class="btn dashboard-btn dashboard-dialog-close">Close</button>' +
            '</div></div>';
        var wrap = document.createElement('div');
        wrap.innerHTML = html;
        document.body.appendChild(wrap.firstElementChild);
        var overlay = document.getElementById('dashboard-error-dialog');
        overlay.querySelector('.dashboard-dialog-close').onclick = function () { overlay.remove(); };
        overlay.onclick = function (e) { if (e.target === overlay) overlay.remove(); };
    }

    var BARS_ROW1 = BARS.slice(0, 4);
    var BARS_ROW2 = BARS.slice(4, 7);

    function render(container) {
        if (!container) return;
        fetch('/api/dashboard/error_logs').then(function (r) { return r.json(); }).then(function (data) {
            function barHtml(bars) {
                var h = '';
                bars.forEach(function (b) {
                    var list = data[b.id] || [];
                    var count = list.length;
                    var percent = count > 20 ? 100 : count * 5;
                    h += '<div class="dashboard-error-bar-item" data-key="' + b.id + '">';
                    h += renderCircularBar(percent, b.label);
                    h += '</div>';
                });
                return h;
            }
            var html = '<div class="dashboard-error-groupby">' +
                '<span class="dashboard-error-groupby-label">Group by:</span>' +
                '<label><input type="radio" name="groupby" value=""' + (groupBy === '' ? ' checked' : '') + '> None</label>' +
                '<label><input type="radio" name="groupby" value="agent"' + (groupBy === 'agent' ? ' checked' : '') + '> Agent</label>' +
                '<label><input type="radio" name="groupby" value="model"' + (groupBy === 'model' ? ' checked' : '') + '> Model</label>' +
                '<label><input type="radio" name="groupby" value="error_type"' + (groupBy === 'error_type' ? ' checked' : '') + '> Error Type</label>' +
                '</div>' +
                '<div class="dashboard-error-bars-wrapper">' +
                '<div class="dashboard-error-bars dashboard-error-bars-row1">' + barHtml(BARS_ROW1) + '</div>' +
                '<div class="dashboard-error-bars dashboard-error-bars-row2">' + barHtml(BARS_ROW2) + '</div>' +
                '</div>' +
                '<div class="dashboard-error-spacer"></div>' +
                '<div class="dashboard-test-system-buttons">' +
                '<button type="button" class="btn dashboard-btn dashboard-test-system-btn" id="dashboard-test-system-btn">Test System</button>' +
                '<button type="button" class="btn dashboard-btn dashboard-stress-test-btn" id="dashboard-stress-test-btn">Stress Test</button>' +
                '</div>';
            container.innerHTML = html;

            container.querySelectorAll('input[name="groupby"]').forEach(function (el) {
                el.addEventListener('change', function () { groupBy = this.value; });
            });

            container.querySelectorAll('.dashboard-error-bar-item').forEach(function (el) {
                el.addEventListener('click', function () {
                    var key = this.getAttribute('data-key');
                    var label = BARS.find(function (b) { return b.id === key; });
                    openDialog((label && label.label) || key, data[key] || []);
                });
            });

            var testSystemBtn = document.getElementById('dashboard-test-system-btn');
            if (testSystemBtn) testSystemBtn.addEventListener('click', function () { /* placeholder */ });
            var stressTestBtn = document.getElementById('dashboard-stress-test-btn');
            if (stressTestBtn) stressTestBtn.addEventListener('click', function () { /* placeholder */ });
        }).catch(function () {
            container.innerHTML = '<p>Failed to load error logs.</p>';
        });
    }

    window.DashboardTabErrorLogs = { render: render };
})();
