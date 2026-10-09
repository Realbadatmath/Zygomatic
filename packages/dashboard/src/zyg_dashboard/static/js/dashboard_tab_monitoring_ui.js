// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Dashboard tab: Monitoring UI
 * Active Jobs / Finished Jobs / Planned Jobs / Pending Schedule Requests / Live Tail
 */
(function () {
    'use strict';

    function byId(id) { return document.getElementById(id); }

    function esc(s) {
        if (s == null) return '';
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    function fmtTs(ts) { return ts ? String(ts).replace('T',' ').slice(0,19) : '—'; }

    // Format ISO timestamp → time only: [  17:24:48  ]
    function fmtTime(ts) {
        if (!ts) return '[  --:--:--  ]';
        var s = String(ts).replace('T', ' ');
        var time = s.slice(11, 19) || s.slice(0, 8);
        return '[  ' + time + '  ]';
    }

    // Extract YYYY-MM-DD from ISO timestamp
    function fmtDate(ts) {
        if (!ts) return '';
        return String(ts).replace('T', ' ').slice(0, 10);
    }

    // Render a list of {timestamp, ...} items into a <pre> element grouped by date
    function renderLogGrouped(out, items, lineMapper) {
        if (!items.length) { out.textContent = 'No entries.'; return; }
        var groups = {}; // date → lines[]
        var order  = [];
        items.forEach(function(e) {
            var d = fmtDate(e.timestamp || e.ts || '');
            if (!d) d = 'Unknown Date';
            if (!groups[d]) { groups[d] = []; order.push(d); }
            groups[d].push(lineMapper(e));
        });
        var lines = [];
        order.forEach(function(d) {
            lines.push(d);  // date header
            groups[d].forEach(function(l) { lines.push(l); });
        });
        out.textContent = lines.join('\n');
        out.scrollTop = out.scrollHeight;
    }

    var TAB_LABELS = {
        active: 'Active Jobs', finished: 'Finished Jobs', planned: 'Planned Jobs',
        permission_centre: 'Pending Schedule Requests', live_tail: 'Live Tail'
    };
    var COLS = 6;

    function formatJob(job) {
        var status = job.status || '—';
        var statusColor = status === 'completed' ? '#28a745' : status === 'failed' ? '#dc3545'
                        : status === 'running' ? '#17a2b8' : '#6c757d';
        return '<tr>'
            + '<td>' + esc(job.agent || '—') + '</td>'
            + '<td>' + esc(fmtTs(job.start_time)) + '</td>'
            + '<td>' + esc(fmtTs(job.end_time !== '—' ? job.end_time : null)) + '</td>'
            + '<td>' + esc(job.duration || '—') + '</td>'
            + '<td title="' + esc(job.error_message || '') + '">' + esc((job.error_message && job.error_message !== '—') ? String(job.error_message).slice(0,60)+'…' : '—') + '</td>'
            + '<td>' + esc(job.job_description || '—') + '</td>'
            + '</tr>';
    }

    // ── Pending Schedule Requests — reads from API ─────────────────────────
    function fillPermissionCentre(container) {
        var tbody = byId('dashboard-monitoring-permission-tbody');
        if (!tbody) return;
        tbody.innerHTML = '<tr><td colspan="7" style="padding:16px;color:#888;">Loading…</td></tr>';
        fetch('/api/approvals/queue', {credentials:'same-origin'})
            .then(function(r){ return r.ok ? r.json() : {items:[]}; })
            .catch(function(){ return {items:[]}; })
            .then(function(data) {
                var items = data.items || [];
                if (!items.length) {
                    tbody.innerHTML = '<tr><td colspan="7" style="padding:24px;text-align:center;color:#555;">No schedule requests found.</td></tr>';
                    return;
                }
                var STATUS_C = {completed:'#28a745', running:'#17a2b8', failed:'#dc3545', unknown:'#6c757d', pending:'#fd7e14'};
                tbody.innerHTML = items.map(function(item) {
                    var sc = STATUS_C[item.status] || '#6c757d';
                    var topic = (item.payload && (item.payload.topic || item.payload.pipeline_status)) || '—';
                    return '<tr>'
                        + '<td>' + esc(item.department || '—') + '</td>'
                        + '<td><code title="' + esc(item.id||'') + '">' + esc((item.id||'').slice(0,8)) + '…</code></td>'
                        + '<td><span style="background:' + sc + ';color:#fff;padding:1px 7px;border-radius:10px;font-size:11px;">' + esc(item.status||'—') + '</span></td>'
                        + '<td>' + esc(fmtTs(item.created_at)) + '</td>'
                        + '<td>' + esc(topic) + '</td>'
                        + '<td>' + esc(item.approved_by || '—') + '</td>'
                        + '<td>' + esc(fmtTs(item.approved_at)) + '</td>'
                        + '</tr>';
                }).join('');
            });
    }

    // ── Live Tail ─────────────────────────────────────────────────────────
    var _allRuns     = [];
    var _searchQuery = '';
    var _selectedId  = null;

    function renderRunList() {
        var listEl = byId('live-tail-run-list');
        if (!listEl) return;
        var q = _searchQuery.toLowerCase();
        var runs = _allRuns.filter(function(r) {
            if (!q) return true;
            return (r.id||'').toLowerCase().indexOf(q) !== -1
                || (r.department||'').toLowerCase().indexOf(q) !== -1
                || (r.status||'').toLowerCase().indexOf(q) !== -1;
        });
        if (!runs.length) {
            listEl.innerHTML = '<div style="padding:12px;color:#888;font-size:12px;">No runs match.</div>';
            return;
        }
        var STATUS_C = {completed:'#28a745',failed:'#dc3545',running:'#17a2b8',unknown:'#aaa'};
        listEl.innerHTML = runs.map(function(r) {
            var sc = STATUS_C[r.status] || '#aaa';
            var active = _selectedId === r.id ? 'background:#e8f0fe;border-left:3px solid #1a73e8;' : 'border-left:3px solid transparent;';
            return '<div class="lt-run-item" data-id="' + esc(r.id||'') + '" style="padding:7px 10px;cursor:pointer;border-bottom:1px solid #f0f0f0;' + active + '">'
                + '<div style="font-family:monospace;font-size:11px;color:#333;">' + esc((r.id||'').slice(0,8)) + '…</div>'
                + '<div style="font-size:11px;color:#666;">'
                + '<span style="color:' + sc + ';font-weight:600;">' + esc(r.status||'?') + '</span>'
                + ' &nbsp; ' + esc(r.department||'') + '</div>'
                + '<div style="font-size:10px;color:#aaa;">' + esc(fmtTs(r.started_at)) + '</div>'
                + '</div>';
        }).join('');
        listEl.querySelectorAll('.lt-run-item').forEach(function(el) {
            el.addEventListener('click', function() {
                _selectedId = el.getAttribute('data-id');
                renderRunList();
                fetchEvents(_selectedId);
            });
        });
    }

    function fetchEvents(runId) {
        var out = byId('live-tail-output');
        if (!out || !runId) return;
        out.textContent = 'Loading events for ' + runId + '…';
        fetch('/api/jobs/events?entity_id=' + encodeURIComponent(runId) + '&limit=500', {credentials:'same-origin'})
            .then(function(r){ return r.ok ? r.json() : {items:[]}; })
            .catch(function(){ return {items:[]}; })
            .then(function(d) {
                var items = d.items || [];
                if (!items.length) { out.textContent = 'No events found for ' + runId + '.'; return; }
                renderLogGrouped(out, items, function(e) {
                    var time  = fmtTime(e.timestamp);
                    var etype = (e.event_type || '').toUpperCase().slice(0,22).padEnd(22);
                    var actor = (e.actor || '').slice(0,16).padEnd(16);
                    var py    = e.payload || {};
                    var detail = '';
                    if (py.message)        detail = py.message;
                    else if (py.error)     detail = 'ERROR: ' + py.error;
                    else if (py.topic)     detail = 'topic: ' + py.topic;
                    else if (py.current_stage) detail = 'stage: ' + py.current_stage;
                    else detail = JSON.stringify(py).slice(0,120);
                    return time + '  ' + etype + '  ' + actor + '  ' + detail;
                });
            });
    }

    function loadLiveTailRuns() {
        var countEl = byId('live-tail-count');
        if (countEl) countEl.textContent = 'Loading…';
        fetch('/api/jobs/runs', {credentials:'same-origin'})
            .then(function(r){ return r.ok ? r.json() : {items:[]}; })
            .catch(function(){ return {items:[]}; })
            .then(function(d) {
                _allRuns = (d.items || []).sort(function(a,b){
                    return (b.started_at||'').localeCompare(a.started_at||'');
                });
                if (countEl) countEl.textContent = _allRuns.length + ' runs';
                renderRunList();
                if (!_selectedId && _allRuns.length) {
                    _selectedId = _allRuns[0].id;
                    renderRunList();
                    fetchEvents(_selectedId);
                }
            });
    }

    function buildLiveTailUI(container) {
        var wrap = byId('dashboard-monitoring-live-tail-wrap');
        if (!wrap) return;
        wrap.innerHTML =
            '<div style="display:flex;gap:0;height:520px;border:1px solid #dee2e6;border-radius:6px;overflow:hidden;">'
            // Left panel: searchable run list
            + '<div style="width:240px;min-width:180px;border-right:1px solid #dee2e6;display:flex;flex-direction:column;background:#fafafa;">'
            + '  <div style="padding:8px;border-bottom:1px solid #dee2e6;">'
            + '    <input type="text" id="live-tail-search" placeholder="🔍 Search runs…" style="width:100%;box-sizing:border-box;padding:5px 8px;border:1px solid #ccc;border-radius:4px;font-size:12px;">'
            + '    <div id="live-tail-count" style="font-size:11px;color:#aaa;margin-top:4px;padding-left:2px;">Loading…</div>'
            + '  </div>'
            + '  <div id="live-tail-run-list" style="flex:1;overflow-y:auto;font-size:12px;"></div>'
            + '  <div style="padding:6px 8px;border-top:1px solid #dee2e6;">'
            + '    <button type="button" class="btn btn-secondary" id="live-tail-refresh-list" style="width:100%;font-size:11px;padding:4px;">⟳ Refresh list</button>'
            + '  </div>'
            + '</div>'
            // Right panel: event output
            + '<div style="flex:1;display:flex;flex-direction:column;">'
            + '  <div style="padding:8px 12px;border-bottom:1px solid #dee2e6;display:flex;align-items:center;gap:8px;background:#f8f9fa;">'
            + '    <span style="font-size:12px;color:#555;">Pipeline events — select a run to view timeline</span>'
            + '    <button type="button" class="btn btn-secondary" id="live-tail-refresh-events" style="margin-left:auto;font-size:11px;padding:3px 10px;">⟳ Reload</button>'
            + '  </div>'
            + '  <pre id="live-tail-output" style="flex:1;margin:0;overflow-y:auto;background:#1e1e1e;color:#d4d4d4;padding:12px;font-size:11px;font-family:monospace;white-space:pre-wrap;word-break:break-all;">Select a run from the list.</pre>'
            + '</div>'
            + '</div>';

        var searchEl = byId('live-tail-search');
        if (searchEl) searchEl.addEventListener('input', function() {
            _searchQuery = this.value;
            renderRunList();
        });
        var refreshListBtn = byId('live-tail-refresh-list');
        if (refreshListBtn) refreshListBtn.addEventListener('click', loadLiveTailRuns);
        var refreshEventsBtn = byId('live-tail-refresh-events');
        if (refreshEventsBtn) refreshEventsBtn.addEventListener('click', function() {
            if (_selectedId) fetchEvents(_selectedId);
        });

        loadLiveTailRuns();
    }

    function render(container) {
        if (!container) return;
        container.innerHTML =
            '<div class="dashboard-monitoring">'
            + '<div class="dashboard-monitoring-tabs">'
            + '<button type="button" class="btn dashboard-btn dashboard-monitoring-tab active" data-list="active">Active Jobs</button>'
            + '<button type="button" class="btn dashboard-btn dashboard-monitoring-tab" data-list="finished">Finished Jobs</button>'
            + '<button type="button" class="btn dashboard-btn dashboard-monitoring-tab" data-list="planned">Planned Jobs</button>'
            + '<button type="button" class="btn dashboard-btn dashboard-monitoring-tab" data-list="permission_centre">Pending Schedule Requests</button>'
            + '<button type="button" class="btn dashboard-btn dashboard-monitoring-tab" data-list="live_tail">Live Tail</button>'
            + '</div>'
            + '<h3 class="dashboard-monitoring-title" id="dashboard-monitoring-title">Active Jobs</h3>'
            + '<div class="dashboard-monitoring-list-wrap" id="dashboard-monitoring-list-wrap">'
            + '<table class="dashboard-monitoring-table" id="dashboard-monitoring-table">'
            + '<thead><tr><th>Agent</th><th>Start time</th><th>End time</th><th>Duration</th><th>Error message</th><th>Job Description</th></tr></thead>'
            + '<tbody id="dashboard-monitoring-tbody"></tbody></table>'
            + '<table class="dashboard-monitoring-table" id="dashboard-monitoring-permission-table" style="display:none;">'
            + '<thead><tr><th>Department</th><th>Request ID</th><th>Status</th><th>Submitted At</th><th>Topic</th><th>Approved By</th><th>Approved At</th></tr></thead>'
            + '<tbody id="dashboard-monitoring-permission-tbody"></tbody></table>'
            + '<div id="dashboard-monitoring-live-tail-wrap" style="display:none;"></div>'
            + '</div></div>';

        var tbody    = byId('dashboard-monitoring-tbody');
        var jobTable = byId('dashboard-monitoring-table');
        var permTable = byId('dashboard-monitoring-permission-table');
        var activeTab = 'active';

        function fillList() {
            var liveWrap = byId('dashboard-monitoring-live-tail-wrap');
            if (liveWrap) liveWrap.style.display = activeTab === 'live_tail' ? 'block' : 'none';
            if (activeTab === 'live_tail') {
                if (jobTable) jobTable.style.display = 'none';
                if (permTable) permTable.style.display = 'none';
                buildLiveTailUI(container);
                return;
            }
            if (activeTab === 'permission_centre') {
                if (jobTable) jobTable.style.display = 'none';
                if (permTable) permTable.style.display = 'table';
                fillPermissionCentre(container);
                return;
            }
            if (jobTable) jobTable.style.display = 'table';
            if (permTable) permTable.style.display = 'none';
            fetch('/api/dashboard/monitoring_jobs', {credentials:'same-origin'})
                .then(function(r){ return r.json(); })
                .then(function(data) {
                    var list = data[activeTab] || [];
                    tbody.innerHTML = list.length
                        ? list.map(formatJob).join('')
                        : '<tr><td colspan="' + COLS + '" style="text-align:center;padding:20px;color:#888;">No jobs.</td></tr>';
                })
                .catch(function() {
                    tbody.innerHTML = '<tr><td colspan="' + COLS + '">Failed to load</td></tr>';
                });
        }

        var titleEl = byId('dashboard-monitoring-title');
        container.querySelectorAll('.dashboard-monitoring-tab').forEach(function(btn) {
            btn.addEventListener('click', function() {
                container.querySelectorAll('.dashboard-monitoring-tab').forEach(function(b){ b.classList.remove('active'); });
                this.classList.add('active');
                activeTab = this.getAttribute('data-list');
                if (titleEl) titleEl.textContent = TAB_LABELS[activeTab] || activeTab;
                fillList();
            });
        });
        fillList();

        var openToPlanned = false;
        try { openToPlanned = sessionStorage.getItem('dashboardMonitoringList') === 'planned'; } catch(e){}
        if (openToPlanned) {
            try { sessionStorage.removeItem('dashboardMonitoringList'); } catch(e){}
            var plannedBtn = container.querySelector('.dashboard-monitoring-tab[data-list="planned"]');
            if (plannedBtn) {
                container.querySelectorAll('.dashboard-monitoring-tab').forEach(function(b){ b.classList.remove('active'); });
                plannedBtn.classList.add('active');
                activeTab = 'planned';
                if (titleEl) titleEl.textContent = TAB_LABELS.planned;
                fillList();
            }
        }
    }

    window.DashboardTabMonitoringUI = { render: render };
})();
