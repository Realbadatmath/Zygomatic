// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Dashboard tab: Audit
 * Who changed what. Admin only. Proxies to control plane /audit.
 */
(function () {
    'use strict';

    function byId(id) { return document.getElementById(id); }

    function escapeHtml(s) {
        if (s == null || s === undefined) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function formatPayload(payload) {
        if (!payload || typeof payload !== 'object') return '—';
        var str = JSON.stringify(payload);
        return str.length > 120 ? str.slice(0, 120) + '…' : str;
    }

    function buildQuery(actor, action, objectType) {
        var q = [];
        if (actor) q.push('actor=' + encodeURIComponent(actor));
        if (action) q.push('action=' + encodeURIComponent(action));
        if (objectType) q.push('object_type=' + encodeURIComponent(objectType));
        return q.length ? '?' + q.join('&') : '';
    }

    function render(container) {
        if (!container) return;
        container.innerHTML =
            '<div class="parameter-control-table-wrap">' +
            '<h3 class="dashboard-monitoring-title">Audit Log</h3>' +
            '<p style="color:#555;margin-bottom:12px;">Who changed what. Admin only. Append-only, tamper-evident. <button type="button" class="btn btn-secondary" id="audit-event-explorer-btn" style="margin-left:8px;">Event Explorer (Replay chain)</button></p>' +
            '<div id="audit-event-explorer-wrap" style="display:none;margin-bottom:16px;padding:12px;background:#f8f9fa;border-radius:8px;border:1px solid #e0e0e0;">' +
            '<strong>Event stream</strong> — entity_type, entity_id, event_type filters. <a href="#" id="audit-event-explorer-close" style="float:right;">Close</a>' +
            '<div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:8px;align-items:center;">' +
            '<input type="text" id="events-filter-entity-id" placeholder="entity_id (e.g. run-123)" style="padding:6px 10px;border-radius:6px;border:1px solid #ccc;width:140px;">' +
            '<input type="text" id="events-filter-event-type" placeholder="event_type" style="padding:6px 10px;border-radius:6px;border:1px solid #ccc;width:140px;">' +
            '<button type="button" class="btn btn-secondary" id="events-apply">Load</button>' +
            '</div><div id="events-loading" style="display:none;margin:8px 0;">Loading…</div>' +
            '<table class="dashboard-table" style="width:100%;margin-top:8px;"><thead><tr><th>Timestamp</th><th>Entity</th><th>Event Type</th><th>Actor</th><th>Payload</th></tr></thead><tbody id="events-tbody"></tbody></table></div>' +
            '<div class="dashboard-audit-filters" style="margin-bottom:12px;display:flex;flex-wrap:wrap;gap:8px;align-items:center;">' +
            '<input type="text" id="audit-filter-actor" placeholder="Filter by actor" style="padding:6px 10px;border-radius:6px;border:1px solid #ccc;">' +
            '<input type="text" id="audit-filter-action" placeholder="Filter by action" style="padding:6px 10px;border-radius:6px;border:1px solid #ccc;">' +
            '<input type="text" id="audit-filter-object-type" placeholder="Filter by object type" style="padding:6px 10px;border-radius:6px;border:1px solid #ccc;">' +
            '<button type="button" class="btn dashboard-btn" id="audit-apply-filters">Apply</button>' +
            '<button type="button" class="btn btn-secondary" id="audit-clear-filters">Clear</button>' +
            '</div>' +
            '<div id="audit-loading">Loading…</div>' +
            '<table class="dashboard-table" style="width:100%;"><thead><tr><th>ID</th><th>Timestamp</th><th>Actor</th><th>Action</th><th>Object Type</th><th>Object ID</th><th>Payload</th></tr></thead><tbody id="audit-tbody"></tbody></table>' +
            '<div id="audit-pagination" style="margin-top:12px;color:#666;"></div>' +
            '</div>';

        function load(offset) {
            offset = offset || 0;
            var actor = byId('audit-filter-actor') && byId('audit-filter-actor').value.trim();
            var action = byId('audit-filter-action') && byId('audit-filter-action').value.trim();
            var objectType = byId('audit-filter-object-type') && byId('audit-filter-object-type').value.trim();
            var q = '?limit=50&offset=' + offset;
            if (actor) q += '&actor=' + encodeURIComponent(actor);
            if (action) q += '&action=' + encodeURIComponent(action);
            if (objectType) q += '&object_type=' + encodeURIComponent(objectType);

            var loading = byId('audit-loading');
            if (loading) loading.style.display = 'block';
            var tbody = byId('audit-tbody');
            if (tbody) tbody.innerHTML = '';

            fetch('/api/audit' + q)
                .then(function (r) {
                    if (!r.ok) {
                        return r.json()
                            .then(function (d) { throw new Error(d.error || d.message || 'Failed to load audit (' + r.status + ')'); })
                            .catch(function () { throw new Error('Failed to load audit (' + r.status + ')'); });
                    }
                    return r.json();
                })
                .then(function (data) {
                    if (loading) loading.style.display = 'none';
                    var items = data.items || [];
                    var total = data.total || 0;
                    if (!tbody) return;
                    if (!items.length) {
                        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:24px;color:#555;">No audit entries.</td></tr>';
                        return;
                    }
                    tbody.innerHTML = items.map(function (e) {
                        return '<tr>' +
                            '<td>' + escapeHtml(e.id) + '</td>' +
                            '<td>' + escapeHtml(e.timestamp || '—') + '</td>' +
                            '<td><code>' + escapeHtml(e.actor || '—') + '</code></td>' +
                            '<td>' + escapeHtml(e.action || '—') + '</td>' +
                            '<td>' + escapeHtml(e.object_type || '—') + '</td>' +
                            '<td>' + escapeHtml(e.object_id || '—') + '</td>' +
                            '<td title="' + escapeHtml(formatPayload(e.payload)) + '">' + escapeHtml(formatPayload(e.payload)) + '</td>' +
                            '</tr>';
                    }).join('');

                    var pagination = byId('audit-pagination');
                    if (pagination && total > 50) {
                        var page = Math.floor(offset / 50) + 1;
                        var totalPages = Math.ceil(total / 50);
                        var prev = offset > 0 ? '<button type="button" class="btn btn-secondary audit-paginate" data-offset="' + (offset - 50) + '">Previous</button>' : '';
                        var next = offset + 50 < total ? '<button type="button" class="btn btn-secondary audit-paginate" data-offset="' + (offset + 50) + '">Next</button>' : '';
                        pagination.innerHTML = prev + ' Page ' + page + ' / ' + totalPages + ' ' + next;
                        pagination.querySelectorAll('.audit-paginate').forEach(function (btn) {
                            btn.addEventListener('click', function () {
                                load(parseInt(btn.getAttribute('data-offset'), 10));
                            });
                        });
                    } else if (pagination) {
                        pagination.innerHTML = total + ' entries';
                    }
                })
                .catch(function (err) {
                    if (loading) loading.style.display = 'none';
                    if (tbody) tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:24px;color:#c00;">' + escapeHtml(err.message || 'Failed to load audit') + '</td></tr>';
                });
        }

        load(0);

        var applyBtn = byId('audit-apply-filters');
        if (applyBtn) applyBtn.addEventListener('click', function () { load(0); });
        var clearBtn = byId('audit-clear-filters');
        if (clearBtn) {
            clearBtn.addEventListener('click', function () {
                if (byId('audit-filter-actor')) byId('audit-filter-actor').value = '';
                if (byId('audit-filter-action')) byId('audit-filter-action').value = '';
                if (byId('audit-filter-object-type')) byId('audit-filter-object-type').value = '';
                load(0);
            });
        }

        function loadEvents() {
            var entityId = byId('events-filter-entity-id') && byId('events-filter-entity-id').value.trim();
            var eventType = byId('events-filter-event-type') && byId('events-filter-event-type').value.trim();
            var q = '?limit=100';
            if (entityId) q += '&entity_id=' + encodeURIComponent(entityId);
            if (eventType) q += '&event_type=' + encodeURIComponent(eventType);
            var loading = byId('events-loading');
            var tbody = byId('events-tbody');
            if (loading) loading.style.display = 'block';
            if (tbody) tbody.innerHTML = '';
            fetch('/api/jobs/events' + q).then(function (r) { return r.ok ? r.json() : { items: [] }; }).then(function (d) {
                if (loading) loading.style.display = 'none';
                var items = d.items || [];
                if (!tbody) return;
                if (!items.length) tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:16px;color:#555;">No events.</td></tr>';
                else tbody.innerHTML = items.map(function (e) {
                    var py = e.payload && typeof e.payload === 'object' ? JSON.stringify(e.payload) : (e.payload || '—');
                    if (py.length > 60) py = py.slice(0, 60) + '…';
                    return '<tr><td>' + escapeHtml(e.timestamp || '—') + '</td><td>' + escapeHtml(e.entity_type || '') + '/' + escapeHtml(e.entity_id || '') + '</td><td>' + escapeHtml(e.event_type || '—') + '</td><td>' + escapeHtml(e.actor || '—') + '</td><td title="' + escapeHtml(py) + '">' + escapeHtml(py) + '</td></tr>';
                }).join('');
            }).catch(function () { if (loading) loading.style.display = 'none'; if (tbody) tbody.innerHTML = '<tr><td colspan="5" style="color:#c00;">Failed to load events.</td></tr>'; });
        }

        var eventExplorerBtn = byId('audit-event-explorer-btn');
        if (eventExplorerBtn) eventExplorerBtn.addEventListener('click', function () {
            var wrap = byId('audit-event-explorer-wrap');
            if (wrap) { wrap.style.display = wrap.style.display === 'none' ? 'block' : 'none'; if (wrap.style.display === 'block') loadEvents(); }
        });
        var eventExplorerClose = byId('audit-event-explorer-close');
        if (eventExplorerClose) eventExplorerClose.addEventListener('click', function (e) { e.preventDefault(); var w = byId('audit-event-explorer-wrap'); if (w) w.style.display = 'none'; });
        var eventsApply = byId('events-apply');
        if (eventsApply) eventsApply.addEventListener('click', loadEvents);
    }

    window.DashboardTabAudit = { render: render };
})();
