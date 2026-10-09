// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Dashboard tab: Job Status
 * Four circular progress bars: Running, Completed, Failed, Retried. Click opens dialog with list.
 */
(function () {
    'use strict';

    var BARS = [
        { id: 'running', key: 'running', listKey: 'running_list', label: 'Running' },
        { id: 'completed', key: 'completed', listKey: 'completed_list', label: 'Completed' },
        { id: 'failed', key: 'failed', listKey: 'failed_list', label: 'Failed' },
        { id: 'retried', key: 'retried', listKey: 'retried_list', label: 'Retried' }
    ];

    function renderCircularBar(num, label) {
        var displayNum = typeof num === 'number' ? num : 0;
        var percent = displayNum > 100 ? 100 : displayNum;
        var r = 50;
        var c = 2 * Math.PI * r;
        var offset = c - (percent / 100) * c;
        return '<div class="dashboard-circle-wrap">' +
            '<svg class="dashboard-circle-svg" viewBox="0 0 120 120">' +
            '<circle class="dashboard-circle-bg" cx="60" cy="60" r="' + r + '"/>' +
            '<circle class="dashboard-circle-mover" cx="60" cy="60" r="' + r + '"/>' +
            '<circle class="dashboard-circle-fill" cx="60" cy="60" r="' + r + '" stroke-dasharray="' + c + '" stroke-dashoffset="' + offset + '"/>' +
            '</svg>' +
            '<span class="dashboard-circle-value">' + displayNum + '</span>' +
            '<span class="dashboard-circle-label">' + label + '</span>' +
            '</div>';
    }

    var JOB_COLUMNS = ['Agent', 'Start time', 'End time', 'Duration', 'Errors', 'Job Description'];

    function openDialog(title, items) {
        var list = Array.isArray(items) ? items : [];
        var rows = [];
        for (var i = 0; i < 10; i++) {
            var row = list[i];
            if (row != null && typeof row === 'object') {
                var agent = row.agent || '-';
                var start = row.start_time || '-';
                var end = row.end_time || '-';
                var duration = row.duration || '-';
                var err = row.error_message || '-';
                var desc = row.job_description || '-';
                rows.push('<tr><td>' + agent + '</td><td>' + start + '</td><td>' + end + '</td><td>' + duration + '</td><td>' + err + '</td><td>' + desc + '</td></tr>');
            } else {
                rows.push('<tr><td>&mdash;</td><td>&mdash;</td><td>&mdash;</td><td>&mdash;</td><td>&mdash;</td><td>&mdash;</td></tr>');
            }
        }
        var tableBody = rows.join('');
        var ths = JOB_COLUMNS.map(function (h) { return '<th>' + h + '</th>'; }).join('');
        var html = '<div class="dashboard-dialog-overlay" id="dashboard-job-dialog">' +
            '<div class="dashboard-dialog dashboard-dialog-large">' +
            '<h3>' + title + '</h3>' +
            '<table class="dashboard-dialog-table"><thead><tr>' + ths + '</tr></thead><tbody>' + tableBody + '</tbody></table>' +
            '<button type="button" class="btn dashboard-btn dashboard-dialog-close">Close</button>' +
            '</div></div>';
        var wrap = document.createElement('div');
        wrap.innerHTML = html;
        document.body.appendChild(wrap.firstElementChild);
        var overlay = document.getElementById('dashboard-job-dialog');
        overlay.querySelector('.dashboard-dialog-close').onclick = function () { overlay.remove(); };
        overlay.onclick = function (e) { if (e.target === overlay) overlay.remove(); };
    }

    function escapeHtml(s) {
        if (s == null || s === undefined) return '';
        var str = String(s);
        return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function renderTodaysSchedule(container, today) {
        var wrap = document.createElement('div');
        wrap.className = 'parameter-control-table-wrap';
        wrap.style.marginTop = '24px';
        wrap.innerHTML = '<h3 class="dashboard-monitoring-title" style="text-align:left;margin-bottom:12px;">Today\'s Schedule</h3>' +
            '<div class="job-status-schedule-table-wrap" style="width:100%;overflow-x:auto;overflow-y:visible;">' +
            '<table class="dashboard-table job-status-schedule-table" style="width:100%;">' +
            '<colgroup><col style="width:5%"><col style="width:12%"><col style="width:18%"><col style="width:18%"><col style="width:12%"><col style="width:5%"><col style="width:10%"><col style="width:20%"></colgroup>' +
            '<thead><tr><th>Type</th><th>Agent</th><th>Start</th><th>End</th><th>Device</th><th>%</th><th>Priority</th><th>Status</th></tr></thead>' +
            '<tbody id="job-status-today-tbody"><tr><td colspan="8" style="text-align:center;padding:16px;color:#555;">Loading Data, Please Wait</td></tr></tbody></table></div>';
        container.appendChild(wrap);
        var tbody = document.getElementById('job-status-today-tbody');
        if (!tbody) return;
        Promise.all([
            fetch('/api/gpu/timeline/24h?date=' + today).then(function (r) { return r.json(); }),
            fetch('/api/cpu/timeline/24h?date=' + today).then(function (r) { return r.json(); })
        ]).then(function (results) {
            var gpuData = results[0] || {};
            var cpuData = results[1] || {};
            var gpuEntries = (gpuData.entries || []).filter(function (e) { return e.date === today; });
            var cpuEntries = (cpuData.entries || []).filter(function (e) { return e.date === today; });
            var modelIdToNameGpu = (gpuData.model_id_to_name || {});
            var modelIdToNameCpu = (cpuData.model_id_to_name || {});
            function modelName(type, e) {
                var map = type === 'GPU' ? modelIdToNameGpu : modelIdToNameCpu;
                var id = e.ai_model;
                if (map[id] && map[id].name) return map[id].name;
                return e.model_name || id || '';
            }
            var rows = [];
            gpuEntries.forEach(function (e) {
                var endDate = e.end_date || e.date;
                rows.push('<tr><td>GPU</td><td>' + escapeHtml(e.agent) + '</td><td>' + escapeHtml(e.date + ' ' + (e.start_time || '')) + '</td><td>' + escapeHtml(endDate + ' ' + (e.end_time || '')) + '</td><td>' + escapeHtml(e.gpu_device) + '</td><td>' + escapeHtml(e.gpu_percent) + '</td><td>' + escapeHtml(e.priority) + '</td><td>—</td></tr>');
            });
            cpuEntries.forEach(function (e) {
                var endDate = e.end_date || e.date;
                rows.push('<tr><td>CPU</td><td>' + escapeHtml(e.agent) + '</td><td>' + escapeHtml(e.date + ' ' + (e.start_time || '')) + '</td><td>' + escapeHtml(endDate + ' ' + (e.end_time || '')) + '</td><td>' + escapeHtml(e.cpu_device) + '</td><td>' + escapeHtml(e.cpu_percent) + '</td><td>' + escapeHtml(e.priority) + '</td><td>—</td></tr>');
            });
            var gpuPending = [];
            var cpuPending = [];
            try {
                var gpuRaw = sessionStorage.getItem('gpu_pending_entries');
                if (gpuRaw) gpuPending = JSON.parse(gpuRaw);
                if (!Array.isArray(gpuPending)) gpuPending = [];
                var cpuRaw = sessionStorage.getItem('cpu_pending_entries');
                if (cpuRaw) cpuPending = JSON.parse(cpuRaw);
                if (!Array.isArray(cpuPending)) cpuPending = [];
            } catch (err) {}
            gpuPending.filter(function (e) { return e.date === today; }).forEach(function (e) {
                var endDate = e.end_time && e.start_time && e.end_time <= e.start_time && e.date
                    ? (function () { var d = new Date(e.date); d.setDate(d.getDate() + 1); return d.toISOString().slice(0, 10); })()
                    : (e.date || '');
                rows.push('<tr><td>GPU</td><td>' + escapeHtml(e.agent || '') + '</td><td>' + escapeHtml((e.date || '') + ' ' + (e.start_time || '')) + '</td><td>' + escapeHtml(endDate + ' ' + (e.end_time || '')) + '</td><td>' + escapeHtml(e.gpu_device || '') + '</td><td>' + escapeHtml(e.gpu_percent || '') + '</td><td>' + escapeHtml(e.priority || '') + '</td><td>Awaiting Permission</td></tr>');
            });
            cpuPending.filter(function (e) { return e.date === today; }).forEach(function (e) {
                var endDate = e.end_time && e.start_time && e.end_time <= e.start_time && e.date
                    ? (function () { var d = new Date(e.date); d.setDate(d.getDate() + 1); return d.toISOString().slice(0, 10); })()
                    : (e.date || '');
                rows.push('<tr><td>CPU</td><td>' + escapeHtml(e.agent || '') + '</td><td>' + escapeHtml((e.date || '') + ' ' + (e.start_time || '')) + '</td><td>' + escapeHtml(endDate + ' ' + (e.end_time || '')) + '</td><td>' + escapeHtml(e.cpu_device || '') + '</td><td>' + escapeHtml(e.cpu_percent || '') + '</td><td>' + escapeHtml(e.priority || '') + '</td><td>Awaiting Permission</td></tr>');
            });
            if (rows.length === 0) rows.push('<tr><td colspan="8">No schedule entries for today. Add entries in GPU or CPU Schedule.</td></tr>');
            tbody.innerHTML = rows.join('');
        }).catch(function () {
            tbody.innerHTML = '<tr><td colspan="8">Unable to load today\'s schedule.</td></tr>';
        });
    }

    function render(container) {
        if (!container) return;
        container.innerHTML = '<div class="dashboard-job-status-loading" style="padding:24px;text-align:center;font-size:1rem;color:#555;">Loading Data, Please Wait</div>';
        var today = new Date().toISOString().slice(0, 10);
        fetch('/api/dashboard/job_status').then(function (r) { return r.json(); }).then(function (data) {
            var html = '<div class="dashboard-job-bars">';
            BARS.forEach(function (b) {
                var num = data[b.key] != null ? data[b.key] : 0;
                html += '<div class="dashboard-job-bar-item" data-key="' + b.listKey + '" data-label="' + b.label + '">';
                html += renderCircularBar(num, b.label);
                html += '</div>';
            });
            html += '</div>';
            container.innerHTML = html;

            container.querySelectorAll('.dashboard-job-bar-item').forEach(function (el) {
                el.addEventListener('click', function () {
                    var key = this.getAttribute('data-key');
                    var label = this.getAttribute('data-label');
                    openDialog(label, data[key] || []);
                });
            });

            renderTodaysSchedule(container, today);
        }).catch(function () {
            container.innerHTML = '<p>Failed to load job status.</p>';
        });
    }

    window.DashboardTabJobStatus = { render: render };
})();
