// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Dashboard tab: Job Lifecycle
 * Surfaces job_run state linked to schedule requests. Strict states: queued → claimed → running → completed | failed | cancelled | timed_out.
 */
(function () {
    'use strict';

    var RUN_STATES = ['queued', 'claimed', 'running', 'completed', 'failed', 'cancelled', 'timed_out'];
    var STATUS_COLORS = {
        queued: '#6c757d',
        claimed: '#fd7e14',
        running: '#17a2b8',
        completed: '#28a745',
        failed: '#dc3545',
        cancelled: '#6c757d',
        timed_out: '#dc3545'
    };

    function byId(id) { return document.getElementById(id); }

    function escapeHtml(s) {
        if (s == null || s === undefined) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function getStatusColor(status) {
        var s = (status || '').toLowerCase();
        return STATUS_COLORS[s] || '#6c757d';
    }

    function renderRows(runs, specById, filterStatus, searchQuery) {
        var tbody = byId('job-lifecycle-tbody');
        if (!tbody) return;
        var filtered = filterStatus ? runs.filter(function(r){ return (r.status||'').toLowerCase() === filterStatus; }) : runs;
        if (searchQuery) {
            var q = searchQuery.toLowerCase();
            filtered = filtered.filter(function(r){
                return (r.id||'').toLowerCase().indexOf(q) !== -1
                    || (r.status||'').toLowerCase().indexOf(q) !== -1
                    || (r.worker_id||'').toLowerCase().indexOf(q) !== -1
                    || (r.error_message||'').toLowerCase().indexOf(q) !== -1;
            });
        }
        var rows = [];
        filtered.forEach(function(r) {
            var spec = specById[r.job_spec_id] || {};
            var statusColor = getStatusColor(r.status);
            var worker = r.worker_id ? escapeHtml((r.worker_id||'').slice(0, 32)) : '—';
            var lease  = r.lease_expires_at ? escapeHtml(r.lease_expires_at.slice(0,19)) : '—';
            // completed_at: use value if set, else show '—' but note it for completed status
            var completedDisplay = r.completed_at ? escapeHtml(r.completed_at.slice(0,19)) : '—';
            var errDisplay = r.error_message ? escapeHtml(r.error_message.slice(0,50)) : '—';
            rows.push(
                '<tr>'
                + '<td><code title="' + escapeHtml(r.id||'') + '">' + escapeHtml((r.id||'').slice(0,8)) + '…</code></td>'
                + '<td><code title="' + escapeHtml(spec.schedule_request_id||r.job_spec_id||'') + '">' + escapeHtml((spec.schedule_request_id||r.job_spec_id||'').slice(0,8)) + '…</code></td>'
                + '<td style="color:' + statusColor + ';font-weight:600;">' + escapeHtml(r.status||'—') + '</td>'
                + '<td title="' + escapeHtml(r.worker_id||'') + '" style="font-size:11px;">' + worker + '</td>'
                + '<td style="font-size:11px;white-space:nowrap;" title="' + escapeHtml(r.lease_expires_at||'') + '">' + lease + '</td>'
                + '<td style="font-size:11px;white-space:nowrap;">' + escapeHtml((r.started_at||'—').slice(0,19)) + '</td>'
                + '<td style="font-size:11px;white-space:nowrap;">' + completedDisplay + '</td>'
                + '<td title="' + escapeHtml(r.error_message||'') + '" style="font-size:11px;color:' + (r.error_message ? '#dc3545' : '#555') + ';">' + errDisplay + '</td>'
                + '</tr>'
            );
        });
        if (rows.length === 0) {
            var msg = filterStatus ? 'No runs with status "' + filterStatus + '".' : (searchQuery ? 'No runs match "' + searchQuery + '".' : 'No job runs.');
            tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:24px;color:#555;">' + escapeHtml(msg) + '</td></tr>';
        } else {
            tbody.innerHTML = rows.join('');
        }
        var countEl = byId('job-lifecycle-count');
        if (countEl) countEl.textContent = filtered.length + ' of ' + runs.length + ' runs shown';
    }

    function render(container) {
        if (!container) return;
        container.innerHTML =
            '<div class="parameter-control-table-wrap">' +
            '<h3 class="dashboard-monitoring-title">Job Lifecycle</h3>' +
            '<p style="color:#555;margin-bottom:12px;">Job specs (approved schedule) and their runs. Strict states: <strong>queued</strong> → <strong>claimed</strong> → <strong>running</strong> → <strong>completed</strong> | <strong>failed</strong> | <strong>cancelled</strong> | <strong>timed_out</strong>.</p>' +
            '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px;">' +
            '  <input type="text" id="job-lifecycle-search" placeholder="🔍 Search ID, status, worker, error…" style="padding:6px 10px;border:1px solid #ccc;border-radius:6px;font-size:12px;width:280px;">' +
            '  <span id="job-lifecycle-count" style="font-size:12px;color:#888;"></span>' +
            '  <button type="button" class="btn btn-secondary" id="job-lifecycle-reload" style="font-size:12px;padding:4px 12px;margin-left:auto;">⟳ Reload</button>' +
            '</div>' +
            '<div id="job-lifecycle-loading">Loading…</div>' +
            '<div id="job-lifecycle-tabs" style="margin-bottom:10px;display:flex;gap:6px;flex-wrap:wrap;"></div>' +
            '<table class="dashboard-table" style="width:100%;"><thead><tr>' +
            '<th>Run ID</th><th>Schedule Request</th><th>Status</th><th>Worker</th>' +
            '<th>Lease expires</th><th>Started</th><th>Completed</th><th>Error</th>' +
            '</tr></thead><tbody id="job-lifecycle-tbody"></tbody></table>' +
            '<div id="job-lifecycle-error" style="display:none;color:#c00;margin-top:12px;"></div>' +
            '</div>';

        var tabsEl        = byId('job-lifecycle-tabs');
        var currentFilter = null;
        var currentSearch = '';

        var searchEl = byId('job-lifecycle-search');
        if (searchEl) searchEl.addEventListener('input', function() {
            currentSearch = this.value.trim();
            renderRows(window._jobLifecycleRuns||[], window._jobLifecycleSpecById||{}, currentFilter, currentSearch);
        });

        function buildTabs() {
            var html = '<button type="button" class="btn dashboard-btn job-lifecycle-tab' + (!currentFilter ? ' active' : '') + '" data-status="">All</button>';
            RUN_STATES.forEach(function(s) {
                html += '<button type="button" class="btn dashboard-btn job-lifecycle-tab' + (currentFilter === s ? ' active' : '') + '" data-status="' + escapeHtml(s) + '">' + escapeHtml(s) + '</button>';
            });
            tabsEl.innerHTML = html;
            tabsEl.querySelectorAll('.job-lifecycle-tab').forEach(function(btn) {
                btn.onclick = function() {
                    currentFilter = btn.getAttribute('data-status') || null;
                    buildTabs();
                    renderRows(window._jobLifecycleRuns||[], window._jobLifecycleSpecById||{}, currentFilter, currentSearch);
                };
            });
        }

        function load() {
            var loading = byId('job-lifecycle-loading');
            var errEl   = byId('job-lifecycle-error');
            if (loading) { loading.style.display = 'block'; loading.textContent = 'Loading…'; }
            if (errEl)   errEl.style.display = 'none';

            fetch('/api/jobs/runs/expire-leases', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:'{}'})
                .then(function() {
                    return Promise.all([
                        fetch('/api/jobs/specs', {credentials:'same-origin'}).then(function(r){ return r.ok ? r.json() : {items:[]}; }),
                        fetch('/api/jobs/runs',  {credentials:'same-origin'}).then(function(r){ return r.ok ? r.json() : {items:[]}; })
                    ]);
                })
                .then(function(results) {
                    var specs = results[0].items || [];
                    var runs  = results[1].items || [];
                    if (loading) loading.style.display = 'none';
                    var specById = {};
                    specs.forEach(function(s){ specById[s.id] = s; });
                    window._jobLifecycleRuns    = runs;
                    window._jobLifecycleSpecById = specById;
                    buildTabs();
                    renderRows(runs, specById, currentFilter, currentSearch);
                })
                .catch(function(err) {
                    if (loading) loading.style.display = 'none';
                    if (errEl) { errEl.style.display='block'; errEl.textContent = err.message||'Failed to load'; }
                });
        }

        buildTabs();
        load();

        var reloadBtn = byId('job-lifecycle-reload');
        if (reloadBtn) reloadBtn.addEventListener('click', load);
    }

    window.DashboardTabJobLifecycle = { render: render };
})();
