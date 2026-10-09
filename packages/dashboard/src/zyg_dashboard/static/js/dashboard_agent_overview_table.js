// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Agent Overview: agents table, search, and agent detail dialog with tabs.
 */
(function () {
    'use strict';

    function byId(id) { return document.getElementById(id); }

    var allAgents = [];
    var allUsers = [];
    var monitoringJobs = { active: [], finished: [], planned: [] };
    var sortColumn = 'name';
    var sortAsc = true;
    var displayedAgents = [];

    function escapeHtml(s) {
        if (s == null || s === undefined) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function sortAgents(agents) {
        agents = Array.isArray(agents) ? agents : [];
        if (agents.length <= 1) return agents.slice();
        var key = sortColumn || 'name';
        var asc = sortAsc !== false;
        var getVal = function (a) {
            switch (key) {
                case 'tier':
                    var t = a.tier;
                    if (t === '—' || t === null || t === undefined) return -1;
                    return typeof t === 'number' ? t : (parseFloat(t) || -1);
                case 'name':
                    return (a.name || '').toLowerCase();
                case 'role':
                    return (a.role || '').toLowerCase();
                case 'active':
                    var v = a.current_tasks;
                    if (v === '—' || v === null || v === undefined) return '';
                    return typeof v === 'number' ? v : String(v).toLowerCase();
                case 'planned':
                    return (a.planned_tasks != null ? a.planned_tasks : '—');
                default:
                    return (a[key] || '').toString().toLowerCase();
            }
        };
        return agents.slice().sort(function (x, y) {
            var vx = getVal(x);
            var vy = getVal(y);
            var cmp;
            if (typeof vx === 'number' && typeof vy === 'number') {
                cmp = vx - vy;
            } else {
                var sx = String(vx);
                var sy = String(vy);
                cmp = sx < sy ? -1 : (sx > sy ? 1 : 0);
            }
            return asc ? cmp : -cmp;
        });
    }

    function updateSortIndicators() {
        var headers = document.querySelectorAll('.dashboard-overview-sortable');
        headers.forEach(function (th) {
            var col = th.getAttribute('data-sort');
            var span = th.querySelector('.sort-indicator');
            if (span) span.remove();
            if (col === sortColumn) {
                var s = document.createElement('span');
                s.className = 'sort-indicator';
                s.textContent = sortAsc ? '\u2191' : '\u2193';
                th.appendChild(s);
            }
        });
    }

    function renderTable(agents) {
        var tbody = byId('dashboard-overview-agents-tbody');
        if (!tbody) return;
        displayedAgents = Array.isArray(agents) ? agents : [];
        agents = sortAgents(displayedAgents);
        if (agents.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:32px;color:#333;font-size:15px;font-weight:500;">No agents found. Configure agents in agent_configurations or connect to the control plane API.</td></tr>';
            return;
        }
        tbody.innerHTML = agents.map(function (a) {
            var tier = a.tier != null ? a.tier : '—';
            var name = escapeHtml(a.name || '—');
            var role = escapeHtml(a.role || '—');
            var active = (a.current_tasks != null && a.current_tasks !== '') ? a.current_tasks : '—';
            var planned = '—';
            return '<tr data-agent-name="' + escapeHtml(a.name || '') + '"><td>' + tier + '</td><td>' + name + '</td><td>' + role + '</td><td>' + active + '</td><td>' + planned + '</td></tr>';
        }).join('');
        updateSortIndicators();
    }

    function userMatchesQuery(u, q) {
        var uid = ((u.id || u.name || '') + '').toLowerCase().trim();
        var uname = ((u.name || '') + '').toLowerCase().trim();
        return uid === q || uname === q || (q && (uid.indexOf(q) >= 0 || uname.indexOf(q) >= 0));
    }

    function filterTable(query) {
        var q = (query || '').toLowerCase().trim();
        if (!q) {
            renderTable(allAgents);
            updateActiveAgentsCircle(allAgents);
            return;
        }
        var matchedUser = allUsers.length ? allUsers.find(function (u) { return userMatchesQuery(u, q); }) : null;
        if (matchedUser) {
            var userId = (matchedUser.id || matchedUser.name || '').trim();
            if (!userId) { renderTable(allAgents); return; }
            fetch('/api/agents/assigned-to/' + encodeURIComponent(userId))
                .then(function (r) { return r.ok ? r.json() : []; })
                .catch(function () { return []; })
                .then(function (agents) {
                    renderTable(Array.isArray(agents) ? agents : []);
                    updateActiveAgentsCircle(Array.isArray(agents) ? agents : []);
                });
            return;
        }
        var filtered = allAgents.filter(function (a) {
            return (a.name && a.name.toLowerCase().indexOf(q) >= 0) ||
                (a.role && a.role.toLowerCase().indexOf(q) >= 0) ||
                (String(a.tier).toLowerCase().indexOf(q) >= 0) ||
                (a.department && a.department.toLowerCase().indexOf(q) >= 0) ||
                (a.goal && a.goal.toLowerCase().indexOf(q) >= 0);
        });
        renderTable(filtered);
        updateActiveAgentsCircle(filtered);
    }

    function openDialog(agent) {
        var overlay = document.createElement('div');
        overlay.className = 'dashboard-agent-dialog-overlay';
        overlay.id = 'dashboard-agent-dialog-overlay';
        var dialog = document.createElement('div');
        dialog.className = 'dashboard-agent-dialog';
        dialog.innerHTML =
            '<div class="dashboard-agent-dialog-header">' +
            '<h3 style="margin:0;">' + escapeHtml(agent.name || 'Agent') + '</h3>' +
            '<button type="button" class="dashboard-agent-dialog-close" aria-label="Close">&times;</button>' +
            '</div>' +
            '<div class="dashboard-agent-dialog-body">' +
            '<div class="dashboard-agent-dialog-tabs" role="tablist" aria-label="Agent details">' +
            '<button type="button" class="dashboard-agent-dialog-tab active" data-tab="biography" role="tab" aria-selected="true" aria-controls="agent-dialog-panel-biography" tabindex="0">Agent Biography</button>' +
            '<button type="button" class="dashboard-agent-dialog-tab" data-tab="role" role="tab" aria-selected="false" aria-controls="agent-dialog-panel-role" tabindex="-1">Agent Role</button>' +
            '<button type="button" class="dashboard-agent-dialog-tab" data-tab="workflow" role="tab" aria-selected="false" aria-controls="agent-dialog-panel-workflow" tabindex="-1">Agent Workflow</button>' +
            '<button type="button" class="dashboard-agent-dialog-tab" data-tab="tasks" role="tab" aria-selected="false" aria-controls="agent-dialog-panel-tasks" tabindex="-1">Tasks</button>' +
            '<button type="button" class="dashboard-agent-dialog-tab" data-tab="team" role="tab" aria-selected="false" aria-controls="agent-dialog-panel-team" tabindex="-1">Agent\'s Team</button>' +
            '<button type="button" class="dashboard-agent-dialog-tab" data-tab="performance" role="tab" aria-selected="false" aria-controls="agent-dialog-panel-performance" tabindex="-1">Performance</button>' +
            '<button type="button" class="dashboard-agent-dialog-tab" data-tab="llms" role="tab" aria-selected="false" aria-controls="agent-dialog-panel-llms" tabindex="-1">LLMs</button>' +
            '<button type="button" class="dashboard-agent-dialog-tab" data-tab="permissions" role="tab" aria-selected="false" aria-controls="agent-dialog-panel-permissions" tabindex="-1">Permissions</button>' +
            '<button type="button" class="dashboard-agent-dialog-tab" data-tab="history" role="tab" aria-selected="false" aria-controls="agent-dialog-panel-history" tabindex="-1">History</button>' +
            '</div>' +
            '<div class="dashboard-agent-dialog-content">' +
            '<div id="agent-dialog-panel-biography" class="dashboard-agent-dialog-panel active" role="tabpanel">' +
            '<div class="dashboard-agent-avatar-wrap">' +
            '<div class="dashboard-agent-avatar-ring" id="agent-dialog-avatar-ring">' +
            '<img id="agent-dialog-avatar-img" src="/api/agents/face/' + encodeURIComponent(agent.id || agent.name || '') + '" alt="" style="display:block;">' +
            '</div>' +
            '<div class="dashboard-agent-biography-text"><p style="white-space:pre-wrap;margin:0;">' + escapeHtml(agent.backstory || '—') + '</p></div>' +
            '</div></div>' +
            '<div id="agent-dialog-panel-role" class="dashboard-agent-dialog-panel" role="tabpanel"><p><strong>Role:</strong> ' + escapeHtml(agent.role || '—') + '</p><p><strong>Goal:</strong> ' + escapeHtml(agent.goal || '—') + '</p></div>' +
            '<div id="agent-dialog-panel-workflow" class="dashboard-agent-dialog-panel" role="tabpanel"><p><strong>Primary task:</strong> ' + escapeHtml(agent.primary_task || '—') + '</p><div id="agent-dialog-workflow-steps"></div></div>' +
            '<div id="agent-dialog-panel-tasks" class="dashboard-agent-dialog-panel" role="tabpanel">' +
            '<div id="agent-dialog-tasks-config" style="margin-bottom:12px;"></div>' +
            '<div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;">' +
            '<button type="button" class="btn dashboard-btn dashboard-agent-tasks-mode active" data-mode="active">Active tasks</button>' +
            '<button type="button" class="btn dashboard-btn dashboard-agent-tasks-mode" data-mode="planned">Planned tasks</button>' +
            '<button type="button" class="btn dashboard-btn dashboard-agent-tasks-mode" data-mode="completed">Completed tasks</button>' +
            '</div>' +
            '<div id="agent-dialog-tasks-table-wrap" class="parameter-control-table-wrap" style="overflow-x:auto;"><table class="dashboard-table" style="width:100%;"><thead><tr><th>Agent</th><th>Start time</th><th>End time</th><th>Duration</th><th>Error message</th><th>Job Description</th></tr></thead><tbody id="agent-dialog-tasks-tbody"></tbody></table></div>' +
            '</div>' +
            '<div id="agent-dialog-panel-team" class="dashboard-agent-dialog-panel" role="tabpanel"><p id="agent-dialog-team-content">Team members and collaboration for this agent.</p></div>' +
            '<div id="agent-dialog-panel-performance" class="dashboard-agent-dialog-panel" role="tabpanel"><p id="agent-dialog-performance-content">—</p></div>' +
            '<div id="agent-dialog-panel-llms" class="dashboard-agent-dialog-panel" role="tabpanel"><p id="agent-dialog-llms-content">LLM models assigned to this agent.</p></div>' +
            '<div id="agent-dialog-panel-permissions" class="dashboard-agent-dialog-panel" role="tabpanel"><p id="agent-dialog-permissions-content">Permissions and access for this agent.</p></div>' +
            '<div id="agent-dialog-panel-history" class="dashboard-agent-dialog-panel" role="tabpanel"><div id="agent-dialog-history-content"><p style="color:#8b949e;">Loading history…</p></div></div>' +
            '</div>' +
            '</div>';
        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        var avatarImg = byId('agent-dialog-avatar-img');
        var avatarRing = byId('agent-dialog-avatar-ring');
        if (avatarImg && avatarRing) {
            avatarImg.onerror = function () {
                avatarImg.style.display = 'none';
                avatarRing.classList.add('dashboard-agent-avatar-faceless');
            };
        }

        function closeDialog() {
            overlay.remove();
            document.removeEventListener('keydown', onEsc);
        }

        function onEsc(e) {
            if (e.key === 'Escape') { e.preventDefault(); closeDialog(); }
        }
        document.addEventListener('keydown', onEsc);
        dialog.querySelector('.dashboard-agent-dialog-close').onclick = closeDialog;
        overlay.onclick = function (e) { if (e.target === overlay) closeDialog(); };

        dialog.querySelectorAll('.dashboard-agent-dialog-tab').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var tab = this.getAttribute('data-tab');
                dialog.querySelectorAll('.dashboard-agent-dialog-tab').forEach(function (b) {
                    b.classList.remove('active');
                    b.setAttribute('aria-selected', 'false');
                    b.setAttribute('tabindex', '-1');
                });
                dialog.querySelectorAll('.dashboard-agent-dialog-panel').forEach(function (p) { p.classList.remove('active'); });
                this.classList.add('active');
                this.setAttribute('aria-selected', 'true');
                this.setAttribute('tabindex', '0');
                var panel = byId('agent-dialog-panel-' + tab);
                if (panel) panel.classList.add('active');
                if (tab === 'tasks') fillTasksTable(agent.name, 'active');
                if (tab === 'history') loadAgentHistory(agent.name);
            });
        });

        function fillTasksTable(agentName, mode) {
            var tbody = byId('agent-dialog-tasks-tbody');
            if (!tbody) return;
            var list = mode === 'active' ? monitoringJobs.active : (mode === 'planned' ? monitoringJobs.planned : monitoringJobs.finished);
            var rows = (list || []).filter(function (j) { return (j.agent || '') === (agentName || ''); });
            var cols = 6;
            var html = rows.length ? rows.map(function (j) {
                return '<tr><td>' + escapeHtml(j.agent || '-') + '</td><td>' + (j.start_time || '-') + '</td><td>' + (j.end_time || '-') + '</td><td>' + (j.duration || '-') + '</td><td>' + escapeHtml(j.error_message || '-') + '</td><td>' + escapeHtml(j.job_description || '-') + '</td></tr>';
            }).join('') : '<tr><td colspan="' + cols + '">No tasks</td></tr>';
            tbody.innerHTML = html;
        }

        dialog.querySelectorAll('.dashboard-agent-tasks-mode').forEach(function (btn) {
            btn.addEventListener('click', function () {
                dialog.querySelectorAll('.dashboard-agent-tasks-mode').forEach(function (b) { b.classList.remove('active'); });
                this.classList.add('active');
                var mode = this.getAttribute('data-mode');
                fillTasksTable(agent.name, mode);
            });
        });
        fillTasksTable(agent.name, 'active');

        var tasksConfigEl = byId('agent-dialog-tasks-config');
        if (tasksConfigEl && agent.tasks && agent.tasks.length) {
            tasksConfigEl.style.display = 'block';
            tasksConfigEl.innerHTML = '<p style="margin:0 0 8px 0;"><strong>Assigned tasks:</strong></p><ul>' + agent.tasks.map(function (t) { return '<li>' + escapeHtml(String(t)) + '</li>'; }).join('') + '</ul>';
        } else if (tasksConfigEl) {
            tasksConfigEl.style.display = 'none';
            tasksConfigEl.innerHTML = '';
        }

        var wfEl = byId('agent-dialog-workflow-steps');
        if (wfEl && agent.production_workflow && agent.production_workflow.length) {
            wfEl.innerHTML = '<p style="margin-top:12px;"><strong>Production workflow:</strong></p><ol>' + agent.production_workflow.map(function (s) { return '<li>' + escapeHtml(s) + '</li>'; }).join('') + '</ol>';
        }
        var teamEl = byId('agent-dialog-team-content');
        if (teamEl) {
            var dept = agent.department ? '<p><strong>Department:</strong> ' + escapeHtml(agent.department) + '</p>' : '';
            var collab = (agent.collaboration_protocols || []).length ? '<p><strong>Collaboration:</strong></p><ul>' + agent.collaboration_protocols.map(function (c) { return '<li>' + escapeHtml(c) + '</li>'; }).join('') + '</ul>' : '';
            teamEl.innerHTML = (dept || collab) ? dept + collab : 'Team members and collaboration for this agent.';
        }
        var perfEl = byId('agent-dialog-performance-content');
        if (perfEl) {
            if (agent.performance_metrics && agent.performance_metrics.length) {
                perfEl.innerHTML = '<ul>' + agent.performance_metrics.map(function (m) { return '<li>' + escapeHtml(m) + '</li>'; }).join('') + '</ul>';
            } else {
                perfEl.textContent = 'No performance metrics defined.';
            }
        }
        var llmsEl = byId('agent-dialog-llms-content');
        var llmsToShow = (agent.ai_models_display && agent.ai_models_display.length) ? agent.ai_models_display : (agent.ai_models || []);
        if (llmsEl && llmsToShow.length) {
            llmsEl.innerHTML = '<ul>' + llmsToShow.map(function (m) { return '<li>' + escapeHtml(String(m)) + '</li>'; }).join('') + '</ul>';
        } else if (llmsEl) {
            llmsEl.textContent = 'No LLMs assigned.';
        }
        var permEl = byId('agent-dialog-permissions-content');
        if (permEl) {
            var perms = agent.permissions && agent.permissions.length ? agent.permissions : (agent.capabilities || agent.skills || []);
            if (perms.length) {
                permEl.innerHTML = '<ul>' + perms.map(function (c) { return '<li>' + escapeHtml(String(c)) + '</li>'; }).join('') + '</ul>';
            } else {
                permEl.textContent = 'Permissions and access for this agent.';
            }
        }
    }

    function loadAgentHistory(agentName) {
        var el = byId('agent-dialog-history-content');
        if (!el) return;
        el.innerHTML = '<p style="color:#8b949e;">Loading history…</p>';
        fetch('/api/agents/' + encodeURIComponent(agentName) + '/logbook')
            .then(function(r){ return r.json(); })
            .then(function(data) {
                var runs = data.runs || [];
                if (!runs.length) {
                    el.innerHTML = '<p style="color:#8b949e;">No history found for this agent.</p>';
                    return;
                }
                var html = '<table style="width:100%;border-collapse:collapse;">' +
                    '<thead><tr style="color:#8b949e;font-size:11px;border-bottom:1px solid #30363d;">' +
                    '<th style="text-align:left;padding:4px 8px;">Pipeline Run</th>' +
                    '<th style="text-align:left;padding:4px 8px;">Date</th>' +
                    '<th style="text-align:left;padding:4px 8px;">Time</th>' +
                    '<th style="text-align:left;padding:4px 8px;">Result</th>' +
                    '</tr></thead><tbody>';
                runs.forEach(function(run) {
                    var dt = (run.first_ts || '').replace('T', ' ');
                    var date = dt.substring(0, 10) || '—';
                    var time = dt.substring(11, 19) || '—';
                    var result = run.has_error
                        ? '<span style="color:#f85149;">&#10008; Error</span>'
                        : '<span style="color:#3fb950;">&#10003; OK</span>';
                    html += '<tr style="border-bottom:1px solid #21262d;cursor:pointer;" data-pid="' + escapeHtml(run.pipeline_id) + '">' +
                        '<td style="padding:4px 8px;font-size:11px;color:#58a6ff;">' + escapeHtml(run.pipeline_id) + '</td>' +
                        '<td style="padding:4px 8px;font-size:11px;">' + escapeHtml(date) + '</td>' +
                        '<td style="padding:4px 8px;font-size:11px;">' + escapeHtml(time) + '</td>' +
                        '<td style="padding:4px 8px;">' + result + '</td>' +
                        '</tr>';
                });
                html += '</tbody></table>';
                el.innerHTML = html;
                el.querySelectorAll('tr[data-pid]').forEach(function(tr) {
                    tr.addEventListener('click', function() {
                        var pid = this.getAttribute('data-pid');
                        var run = runs.filter(function(r){ return r.pipeline_id === pid; })[0];
                        if (run) openLogReaderDialog(run);
                    });
                });
            })
            .catch(function() { el.innerHTML = '<p style="color:#f85149;">Failed to load history.</p>'; });
    }

    function openLogReaderDialog(run) {
        var existing = document.getElementById('agent-log-reader-dialog');
        if (existing) existing.remove();
        var dlg = document.createElement('div');
        dlg.id = 'agent-log-reader-dialog';
        dlg.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);' +
            'background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:10px;' +
            'width:700px;max-height:calc(75vh / var(--ui-zoom,1));display:flex;flex-direction:column;' +
            'font-family:"Consolas","Courier New",monospace;font-size:12px;z-index:100000;' +
            'box-shadow:0 8px 32px rgba(0,0,0,0.85);overflow:hidden;';
        var entries = run.entries || [];
        var logText = entries.map(function(e) {
            return '[' + (e.level||'INFO') + '] [' + (e.timestamp||'').substring(0,19) + '] [' + (e.agent||'') + '] ' + (e.message||'');
        }).join('\n');
        var dt = (run.first_ts || '').replace('T', ' ').substring(0, 19);
        dlg.innerHTML =
            '<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:#161b22;border-bottom:1px solid #30363d;">' +
            '<span style="color:#58a6ff;font-weight:bold;">Log Reader — ' + escapeHtml(run.pipeline_id) + '</span>' +
            '<div style="display:flex;gap:6px;">' +
            '<button id="agent-log-copy-btn" style="background:#21262d;color:#8b949e;border:1px solid #30363d;border-radius:5px;padding:2px 8px;cursor:pointer;font-size:11px;">Copy All</button>' +
            '<button id="agent-log-close-btn" style="background:#da3633;color:#fff;border:none;border-radius:5px;padding:2px 8px;cursor:pointer;">&#10005;</button>' +
            '</div></div>' +
            '<div style="padding:6px 12px;background:#161b22;border-bottom:1px solid #30363d;font-size:11px;color:#8b949e;">' +
            'Pipeline: ' + escapeHtml(run.pipeline_id) + '  &nbsp;|&nbsp;  Date: ' + escapeHtml(dt) + '  &nbsp;|&nbsp;  ' + entries.length + ' entries</div>' +
            '<pre id="agent-log-reader-pre" style="flex:1;overflow-y:auto;padding:10px 14px;margin:0;white-space:pre-wrap;word-break:break-all;line-height:1.5;">' + escapeHtml(logText) + '</pre>';
        document.body.appendChild(dlg);
        document.getElementById('agent-log-close-btn').onclick = function() { dlg.remove(); };
        document.getElementById('agent-log-copy-btn').onclick = function() {
            try { navigator.clipboard.writeText(logText); } catch(_) {}
        };
    }

    function init() {
        var tbody = byId('dashboard-overview-agents-tbody');
        if (!tbody) return;

        var searchToggle = byId('dashboard-overview-search-toggle');
        var searchInput = byId('dashboard-overview-agent-search');
        if (searchToggle && searchInput) {
            searchToggle.addEventListener('click', function () {
                var show = searchInput.style.display !== 'none' && searchInput.style.display !== '';
                searchInput.style.display = show ? 'none' : 'inline-block';
                if (!show) searchInput.focus();
            });
            searchInput.addEventListener('input', function () { filterTable(this.value); });
            searchInput.addEventListener('keydown', function (e) { if (e.key === 'Escape') { this.style.display = 'none'; this.blur(); } });
        }

        tbody.addEventListener('dblclick', function (e) {
            var row = e.target.closest('tr[data-agent-name]');
            if (!row) return;
            var name = row.getAttribute('data-agent-name');
            var agent = allAgents.filter(function (a) { return (a.name || '') === name; })[0];
            if (!agent) return;
            fetch('/api/agents/config/' + encodeURIComponent(agent.name || name))
                .then(function (r) { return r.ok ? r.json() : null; })
                .catch(function () { return null; })
                .then(function (cfg) {
                    if (cfg && typeof cfg === 'object') {
                        agent = Object.assign({}, agent, cfg);
                    }
                    openDialog(agent);
                });
        });

        document.querySelectorAll('.dashboard-overview-sortable').forEach(function (th) {
            th.addEventListener('click', function () {
                var col = this.getAttribute('data-sort');
                if (!col) return;
                if (col === sortColumn) {
                    sortAsc = !sortAsc;
                } else {
                    sortColumn = col;
                    sortAsc = true;
                }
                updateSortIndicators();
                renderTable(displayedAgents);
            });
        });

        function agentsFromMapping(mapping, configs) {
            if (!mapping || typeof mapping !== 'object') return [];
            configs = configs || {};
            return Object.keys(mapping).map(function (name) {
                var m = mapping[name];
                var cfg = configs[name] || {};
                var tier = (m && m.tier != null) ? m.tier : '—';
                return {
                    name: name,
                    id: cfg.id || m.agent_id || name,
                    tier: tier,
                    role: cfg.role || '—',
                    goal: cfg.goal || '—',
                    backstory: cfg.backstory || '—',
                    primary_task: cfg.primary_task || '—',
                    department: cfg.department || (m.department || ''),
                    current_tasks: '',
                    tasks: cfg.tasks || [],
                    production_workflow: cfg.production_workflow || [],
                    performance_metrics: cfg.performance_metrics || [],
                    ai_models: cfg.ai_models || [],
                    ai_models_display: cfg.ai_models_display || [],
                    capabilities: cfg.capabilities || cfg.skills || [],
                    permissions: cfg.permissions || cfg.capabilities || cfg.skills || [],
                    collaboration_protocols: cfg.collaboration_protocols || []
                };
            });
        }
        /** Build agent list from /api/agents/config (all agents) and optionally enrich tier from mapping. */
        function agentsFromConfig(configs, mapping) {
            if (!configs || typeof configs !== 'object') return [];
            mapping = mapping && typeof mapping === 'object' ? mapping : {};
            return Object.keys(configs).map(function (name) {
                var cfg = configs[name] || {};
                var m = mapping[name];
                var tier = (m && m.tier != null) ? m.tier : (cfg.tier != null ? cfg.tier : '—');
                return {
                    name: name,
                    id: cfg.id || (m && m.agent_id) || name,
                    tier: tier,
                    role: cfg.role || '—',
                    goal: cfg.goal || '—',
                    backstory: cfg.backstory || '—',
                    primary_task: cfg.primary_task || '—',
                    department: cfg.department || (m && m.department) || '',
                    current_tasks: '',
                    tasks: cfg.tasks || [],
                    production_workflow: cfg.production_workflow || [],
                    performance_metrics: cfg.performance_metrics || [],
                    ai_models: cfg.ai_models || [],
                    ai_models_display: cfg.ai_models_display || [],
                    capabilities: cfg.capabilities || cfg.skills || [],
                    permissions: cfg.permissions || cfg.capabilities || cfg.skills || [],
                    collaboration_protocols: cfg.collaboration_protocols || []
                };
            });
        }

        var loadingSegments = [
            'Agent Biographies',
            'Agent Roles',
            'Agent Workflows',
            'Agent Tasks',
            'Agent Teams',
            'Performance Stats',
            'Agent Permissions'
        ];
        function setLoadingMsg(segment) {
            if (!tbody) return;
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:24px;color:#666;"><span style="display:block;font-weight:600;">Loading Data</span><span style="display:block;margin-top:6px;">' + (segment || '') + '</span></td></tr>';
        }
        function setSuccessMsg() {
            if (!tbody) return;
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:24px;color:#2e7d32;font-weight:600;">Data Successfully Retrieved</td></tr>';
        }
        var idx = 0;
        var loadingTimer = null;
        function nextSegment() {
            if (idx < loadingSegments.length) {
                setLoadingMsg(loadingSegments[idx]);
                idx++;
                loadingTimer = setTimeout(nextSegment, 280);
            }
        }
        setLoadingMsg(loadingSegments[0]);
        idx = 1;
        loadingTimer = setTimeout(nextSegment, 280);
        Promise.all([
            fetch('/api/agents').then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }),
            fetch('/api/dashboard/monitoring_jobs').then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }),
            fetch('/api/dashboard/users').then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; })
        ]).then(function (results) {
            clearTimeout(loadingTimer);
            idx = loadingSegments.length;
            var apiAgents = results[0];
            var apiJobs = results[1];
            var usersData = results[2];
            if (usersData && typeof usersData === 'object') {
                var admins = usersData.admins || [];
                var ops = usersData.operators || [];
                var aiOps = usersData.ai_operators || [];
                var specs = usersData.spectators || [];
                allUsers = admins.concat(ops).concat(aiOps).concat(specs);
            }
            allAgents = Array.isArray(apiAgents) ? apiAgents : [];
            if (allAgents.length === 0) {
                var mapping = window.agentModelBarMapping;
                var finishFallback = function () {
                    monitoringJobs = (apiJobs && typeof apiJobs === 'object') ? apiJobs : { active: [], finished: [], planned: [] };
                    if (!Array.isArray(monitoringJobs.active)) monitoringJobs.active = [];
                    if (!Array.isArray(monitoringJobs.finished)) monitoringJobs.finished = [];
                    if (!Array.isArray(monitoringJobs.planned)) monitoringJobs.planned = [];
                    setSuccessMsg();
                    setTimeout(function () {
                        renderTable(allAgents);
                        updateActiveAgentsCircle(allAgents);
                    }, 400);
                };
                var enrichAndFinish = function (cfg, m) {
                    if (cfg && typeof cfg === 'object' && Object.keys(cfg).length > 0) {
                        allAgents = agentsFromConfig(cfg, m || {});
                    } else if (m && typeof m === 'object') {
                        allAgents = agentsFromMapping(m, cfg || {});
                    }
                    finishFallback();
                };
                if (mapping && typeof mapping === 'object') {
                    fetch('/api/agents/config').then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; }).then(function (cfg) { enrichAndFinish(cfg, mapping); });
                } else {
                    fetch('/api/agent_model_bar_mapping').then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }).then(function (m) {
                        fetch('/api/agents/config').then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; }).then(function (cfg) { enrichAndFinish(cfg, m); });
                    });
                }
                return;
            }
            monitoringJobs = (apiJobs && typeof apiJobs === 'object') ? apiJobs : { active: [], finished: [], planned: [] };
            if (!Array.isArray(monitoringJobs.active)) monitoringJobs.active = [];
            if (!Array.isArray(monitoringJobs.finished)) monitoringJobs.finished = [];
            if (!Array.isArray(monitoringJobs.planned)) monitoringJobs.planned = [];
            setSuccessMsg();
            setTimeout(function () {
                renderTable(allAgents);
                updateActiveAgentsCircle(allAgents);
            }, 400);
        });
    }

    function updateActiveAgentsCircle(agents) {
        var total = (agents && agents.length) ? agents.length : 0;
        var active = (agents && agents.length) ? agents.filter(function (a) { return (a.current_tasks || 0) > 0; }).length : 0;
        var percent = total ? (active / total) * 100 : 0;
        var valueEl = byId('dashboard-overview-active-agents-value');
        var fillEl = byId('dashboard-overview-active-agents-fill');
        if (valueEl) valueEl.textContent = active + '/' + total;
        if (fillEl) {
            var c = 2 * Math.PI * 50;
            fillEl.style.strokeDashoffset = String(c - (Math.min(100, Math.max(0, percent)) / 100) * c);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
