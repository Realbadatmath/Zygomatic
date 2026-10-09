// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

        let selectedAgents = [];
        let allAgents = [];
        let departments = [];
        let allSelected = false;
        let editingDay = null;
        let editingTasks = [];
        let editingAgent = null;
        /* 2026-07-17 modularization: dead code removed here (legacy schedule add-entry / tab code targeting DOM absent from this page). Original in crews_modularization_backups_20260717. */
        // Load agent_configurations.json and build model-to-agent mapping
        let modelToAgents = {};
        let agentToModels = {};
        fetch('/api/agents/config')
          .then(res => res.json())
          .then(agentConfigs => {
            for (const agentName in agentConfigs) {
              const agent = agentConfigs[agentName];
              if (agent.ai_models) {
                agent.ai_models.forEach(model => {
                  if (!modelToAgents[model]) modelToAgents[model] = [];
                  modelToAgents[model].push(agentName);
                  if (!agentToModels[agentName]) agentToModels[agentName] = [];
                  agentToModels[agentName].push(model);
                });
              }
            }
          });
        // --- BEGIN: Agent-Model-Bar Mapping (with DEBUG, readable names) ---
        window.agentModelBarMapping = null;
        window.agentModelBarMappingLoaded = false;
        window.cpuAgentModelBarMapping = null;
        window.cpuAgentModelBarMappingLoaded = false;
        window.allScheduleAgents = [];
        window.allScheduleAgentsLoaded = false;
        fetch('/api/agent_model_bar_mapping')
          .then(r => r.json())
          .then(data => {
            console.log('[DEBUG] Loaded agentModelBarMapping (readable):', data);
            window.agentModelBarMapping = data || {};
            window.agentModelBarMappingLoaded = true;
            if (!data || Object.keys(data || {}).length === 0) {
              console.error('[DEBUG] agentModelBarMapping is empty!');
            }
          })
          .catch(err => {
            console.error('[DEBUG] Failed to load agentModelBarMapping:', err);
            window.agentModelBarMapping = {};
          });
        fetch('/api/cpu/agent_model_bar_mapping')
          .then(r => r.json())
          .then(data => {
            window.cpuAgentModelBarMapping = data || {};
            window.cpuAgentModelBarMappingLoaded = true;
          })
          .catch(err => {
            console.error('[DEBUG] Failed to load cpuAgentModelBarMapping:', err);
            window.cpuAgentModelBarMapping = {};
          });
        fetch('/api/agents')
          .then(r => r.json())
          .then(data => {
            window.allScheduleAgents = Array.isArray(data) ? data : [];
            window.allScheduleAgentsLoaded = true;
            console.log('[DEBUG] Loaded allScheduleAgents:', window.allScheduleAgents.length);
          })
          .catch(err => {
            console.error('[DEBUG] Failed to load allScheduleAgents:', err);
            window.allScheduleAgents = [];
          });
        // --- END: Agent-Model-Bar Mapping (with DEBUG, readable names) ---
        // --- BEGIN: Model List (readable, with DEBUG) ---
        let readableModelList = [];
        let modelIdNameMap = {};
        fetch('/api/model_ids')
          .then(r => r.json())
          .then(function(data) {
            if (data && data.model_ids) {
                const raw = data.model_ids;
                modelIdNameMap = {};
                readableModelList = [];
                Object.keys(raw).forEach(function(id) {
                    const entry = raw[id];
                    const name = (entry && entry.name) ? entry.name : id;
                    modelIdNameMap[id] = name;
                    readableModelList.push(name);
                });
                window.modelIdNameMap = modelIdNameMap;
            } else {
                console.warn('[DEBUG] No model_ids found in response:', data);
            }
            console.log('[DEBUG] Loaded readableModelList:', readableModelList);
            const modelSelect = document.getElementById('ai_model_select');
            if (modelSelect) {
                modelSelect.innerHTML = '<option value="">Select model</option>' + readableModelList.map(m => `<option value="${m}">${m}</option>`).join('');
            }
          })
          .catch(function(err) {
            console.error('[DEBUG] Failed to load model list:', err);
            readableModelList = [];
          });
        // --- END: Model List (readable, with DEBUG) ---
        // --- BEGIN: Agent List (readable) ---
        let readableAgentList = [];
        fetch('/api/agents')
          .then(r => r.json())
          .then(function(data) {
            if (data && data.agent_ids) {
                readableAgentList = Object.keys(data.agent_ids);
            } else if (data && data.agents) {
                readableAgentList = Object.keys(data.agents);
            } else {
                readableAgentList = [];
                console.warn('[DEBUG] No agent_ids or agents found in response:', data);
            }
            console.log('[DEBUG] Loaded readableAgentList:', readableAgentList);
          })
          .catch(function(err) {
            console.error('[DEBUG] Failed to load agent list:', err);
            readableAgentList = [];
          });
        // --- END: Agent List (readable) ---
        // Initialize dashboard (use early-fetched promises if available for faster paint when coming from schedule pages)
        document.addEventListener('DOMContentLoaded', function() {
            var hasAgentList = document.getElementById('agent-list');
            if (hasAgentList) {
                if (window._dashboardAgentsPromise) {
                    window._dashboardAgentsPromise.then(function(data) {
                        allAgents = Array.isArray(data) ? data : [];
                        updateStats();
                        updateDepartmentFilter();
                        renderAgentList(getAgentsForAllTab(), 'agent-list');
                    });
                } else {
                    loadAgents();
                }
                if (window._dashboardDepartmentsPromise) {
                    window._dashboardDepartmentsPromise.then(function(data) {
                        departments = Array.isArray(data) ? data : [];
                    });
                } else {
                    loadDepartments();
                }
                setTimeout(function() {
                    var selectAllBtn = document.getElementById('select-all-btn');
                    if (selectAllBtn) {
                        selectAllBtn.onclick = function() {
                            var agentItems = document.querySelectorAll('.agent-item');
                            agentItems.forEach(function(item) {
                                if (!item.classList.contains('selected')) item.click();
                            });
                        };
                    }
                }, 500);
            }
            updateGPUStatus();
            window._agentZeroPendingPollInterval = setInterval(updateGPUStatus, 30000);
            var restartBtn = document.getElementById('restartDashboardBtn');
            if (restartBtn) restartBtn.onclick = function() {
                zygConfirm('Restart Dashboard', 'This will shut down and relaunch the dashboard process.', 'Restart', function() {
                    fetch('/api/restart_dashboard', { method: 'POST' })
                        .then(res => res.json())
                        .then(data => { alert('Dashboard is restarting...'); })
                        .catch(err => alert('Failed to restart: ' + err));
                });
            };
            // Update debug panel content only when it exists (panel stays hidden by default; F3 toggles)
            if (typeof updateDebugPanel === 'function') updateDebugPanel();
        });
        /* 2026-07-17 modularization: dead code removed here (legacy schedule add-entry / tab code targeting DOM absent from this page). Original in crews_modularization_backups_20260717. */
        async function loadAgents() {
            try {
                const response = await fetch('/api/agents');
                allAgents = await response.json();
                updateStats();
                updateDepartmentFilter();
                renderAgentList(getAgentsForAllTab(), 'agent-list');
            } catch (error) {
                console.error('Error loading agents:', error);
            }
        }
        async function loadDepartments() {
            try {
                const response = await fetch('/api/departments');
                departments = await response.json();
            } catch (error) {
                console.error('Error loading departments:', error);
            }
        }
        function updateDepartmentFilter() {
            const filter = document.getElementById('department-filter');
            const select = document.getElementById('department-select');
            if (!filter || !select) return;
            filter.innerHTML = '<option value="">All Departments</option>';
            select.innerHTML = '<option value="">Select Department</option>';
            departments.forEach(dept => {
                filter.innerHTML += `<option value="${dept}">${dept}</option>`;
                select.innerHTML += `<option value="${dept}">${dept}</option>`;
            });
        }
        function loadDepartmentOptions() {
            updateDepartmentFilter();
        }
        async function loadDepartmentAgents() {
            const department = document.getElementById('department-select').value;
            if (!department) return;
            try {
                const response = await fetch(`/api/agents/department/${department}`);
                const departmentAgents = await response.json();
                renderAgentList(departmentAgents, 'department-agent-list');
            } catch (error) {
                console.error('Error loading department agents:', error);
            }
        }
        function getAgentsForAllTab() {
            const filterEl = document.getElementById('department-filter');
            const department = filterEl ? filterEl.value : '';
            const base = department ? allAgents.filter(agent => agent.department === department) : allAgents;
            const searchEl = document.getElementById('agent-search');
            const q = (searchEl && searchEl.value) ? searchEl.value.trim().toLowerCase() : '';
            if (!q) return base;
            return base.filter(agent => {
                const name = (agent.name || '').toLowerCase();
                const role = (agent.role || '').toLowerCase();
                const dept = (agent.department || '').toLowerCase();
                const goal = (agent.goal || '').toLowerCase();
                const tierStr = ('tier ' + (agent.tier ?? '')).toLowerCase();
                const tierNum = String(agent.tier ?? '').toLowerCase();
                return name.includes(q) || role.includes(q) || dept.includes(q) || goal.includes(q) ||
                    tierStr.includes(q) || tierNum === q;
            });
        }
        function filterByDepartment() {
            renderAgentList(getAgentsForAllTab(), 'agent-list');
        }
        function onAgentSearchInput() {
            renderAgentList(getAgentsForAllTab(), 'agent-list');
        }
        function normalizeTierForDisplay(tier) {
            if (tier === 'Specialist') return 5;
            if (tier === 'Management') return 4;
            return tier;
        }
        function renderAgentList(agents, containerId) {
            const container = document.getElementById(containerId);
            if (!container) return;
            container.innerHTML = '';
            agents.forEach(agent => {
                const tierNum = normalizeTierForDisplay(agent.tier);
                const agentDiv = document.createElement('div');
                agentDiv.className = 'agent-item';
                agentDiv.setAttribute('data-agent-name', agent.name);
                agentDiv.onclick = () => toggleAgentSelection(agent);
                agentDiv.innerHTML = `
                    <h3>${agent.name} <span class="agent-tier tier-${tierNum}">Tier ${tierNum}</span></h3>
                    <p><strong>Role:</strong> ${agent.role}</p>
                    <p><strong>Department:</strong> ${agent.department}</p>
                    <p><strong>Goal:</strong> ${agent.goal.substring(0, 100)}...</p>
                `;
                container.appendChild(agentDiv);
            });
        }
        function toggleAgentSelection(agent) {
            if (spectatorNotAllowed()) return;
            const index = selectedAgents.findIndex(a => a.name === agent.name);
            if (index === -1) {
                selectedAgents.push(agent);
                document.querySelectorAll('.agent-item').forEach(item => {
                    if (item.getAttribute('data-agent-name') === agent.name) {
                        item.classList.add('selected');
                    }
                });
            } else {
                selectedAgents.splice(index, 1);
                document.querySelectorAll('.agent-item').forEach(item => {
                    if (item.getAttribute('data-agent-name') === agent.name) {
                        item.classList.remove('selected');
                    }
                });
            }
            const selectAllBtn = document.getElementById('select-all-btn');
            if (selectedAgents.length === allAgents.length) {
                allSelected = true;
                if (selectAllBtn) selectAllBtn.textContent = 'Deselect All Agents';
            } else {
                allSelected = false;
                if (selectAllBtn) selectAllBtn.textContent = 'Select All Agents';
            }
            updateSelectedAgentsDisplay();
            if (selectedAgents.length === 1) { console.log('Selected agent:', selectedAgents[0]); }
            autoFillTaskDescription();
        }
        function updateSelectedAgentsDisplay() {
            const container = document.getElementById('selected-agents');
            if (!container) return;
            if (selectedAgents.length === 0) {
                container.innerHTML = '<p style="color: #999; text-align: center;">Click on agents to select them</p>';
                return;
            }
            container.innerHTML = selectedAgents.map(agent => `
                <div style="display: inline-block; background: #667eea; color: white; padding: 5px 10px; border-radius: 15px; margin: 2px; font-size: 0.9rem;">
                    ${agent.name} <span onclick="removeAgent('${agent.name}')" style="cursor: pointer; margin-left: 5px;">×</span>
                </div>
            `).join('');
        }
        function removeAgent(agentName) {
            selectedAgents = selectedAgents.filter(agent => agent.name !== agentName);
            document.querySelectorAll('.agent-item').forEach(item => {
                if (item.getAttribute('data-agent-name') === agentName) {
                    item.classList.remove('selected');
                }
            });
            updateSelectedAgentsDisplay();
        }
        function clearSelection() {
            selectedAgents = [];
            document.querySelectorAll('.agent-item').forEach(item => item.classList.remove('selected'));
            allSelected = false;
            const selectAllBtn = document.getElementById('select-all-btn');
            if (selectAllBtn) selectAllBtn.textContent = 'Select All Agents';
            updateSelectedAgentsDisplay();
        }
        async function runTask() {
            const taskDescription = document.getElementById('task-description').value;
            const useGPUScheduling = false;
            if (!taskDescription.trim()) { alert('Please enter a task description'); return; }
            if (!selectedAgents.length) { alert('Please select at least one agent'); return; }
            const resultDiv = document.getElementById('task-result');
            if (resultDiv) {
                resultDiv.style.display = 'block';
                resultDiv.innerHTML = '<div class="loading"><div class="spinner"></div>Executing task...</div>';
            }
            try {
                const response = await fetch('/api/run_task', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        agents: selectedAgents.map(agent => agent.name),
                        task: taskDescription,
                        use_gpu_scheduling: useGPUScheduling
                    })
                });
                const result = await response.json();
                if (resultDiv) {
                    if (result.error) {
                        resultDiv.innerHTML = `<div class="status error">Error: ${result.error}</div>`;
                    } else {
                        resultDiv.innerHTML = `
                            <div class="status success">Task completed successfully!</div>
                            <h4>Agents Used:</h4>
                            <p>${result.agents_used.join(', ')}</p>
                            <h4>Result:</h4>
                            <p>${result.result}</p>
                            ${result.gpu_allocations ? `<h4>GPU Allocations:</h4><p>${JSON.stringify(result.gpu_allocations, null, 2)}</p>` : ''}
                        `;
                    }
                }
            } catch (error) {
                if (resultDiv) resultDiv.innerHTML = `<div class="status error">Error: ${error.message}</div>`;
            }
        }
        async function updateGPUStatus() {
            if (window._serverRestarting) return;
            try {
                const response = await fetch('/api/gpu/schedule');
                const gpuData = await response.json();
                const totalAllocated = gpuData.total_allocated || 0;
                const gpuBarFill = document.getElementById('gpu-bar-fill');
                const gpuUsageText = document.getElementById('gpu-usage-text');
                if (gpuBarFill) gpuBarFill.style.width = `${totalAllocated}%`;
                if (gpuUsageText) gpuUsageText.textContent = `${totalAllocated}%`;
                const allocationsContainer = document.getElementById('gpu-allocations');
                if (allocationsContainer) {
                    allocationsContainer.innerHTML = '';
                    Object.entries(gpuData.allocations || {}).forEach(([agent, allocation]) => {
                        const allocationDiv = document.createElement('div');
                        allocationDiv.className = 'gpu-allocation';
                        allocationDiv.innerHTML = `
                            <h4>${agent}</h4>
                            <p>GPU Usage: ${allocation.gpu_percent}%</p>
                            <p>Duration: ${allocation.duration_hours} hours</p>
                            <p>Started: ${new Date(allocation.start_time).toLocaleString()}</p>
                            <button class="btn btn-danger" onclick="releaseGPU('${agent}')">Release GPU</button>
                        `;
                        allocationsContainer.appendChild(allocationDiv);
                    });
                }
                // NOTE: do NOT touch dashboard-overview-gpu-fill here —
                // _updateHardwareCirclesClipfarm owns that circle with live pynvml data.
            } catch (error) {
                console.error('Error updating GPU status:', error);
            }
        }
        async function releaseGPU(agentName) {
            try {
                const response = await fetch('/api/gpu/release', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ agent: agentName })
                });
                const result = await response.json();
                if (result.success) {
                    updateGPUStatus();
                } else {
                    alert(`Error: ${result.error}`);
                }
            } catch (error) {
                console.error('Error releasing GPU:', error);
            }
        }
        function updateOverviewCircle(fillId, valueId, percent, valueText) {
            var fill = document.getElementById(fillId);
            var valueEl = document.getElementById(valueId);
            if (!fill || !valueEl) return;
            var p = Math.min(100, Math.max(0, percent));
            var c = 2 * Math.PI * 50;
            fill.style.strokeDashoffset = (c - (p / 100) * c).toString();
            valueEl.textContent = valueText;
        }
        // ── Real hardware circles (GPU %, CPU %, VRAM) from /api/telemetry ──
        var _sessionExpiredShown = false;
        function _showSessionExpiredBanner() {
            if (_sessionExpiredShown) return;
            _sessionExpiredShown = true;
            var b = document.getElementById('session-expired-banner');
            if (b) b.style.display = 'block';
        }
        function _updateHardwareCirclesClipfarm() {
            if (window._serverRestarting) return;
            fetch('/api/telemetry').then(function(r) {
                if (r.status === 401) { _showSessionExpiredBanner(); return null; }
                return r.json();
            }).then(function(d) {
                if (!d) return;
                // GPU utilisation
                var gpuPct = (d.gpus && d.gpus[0]) ? Math.round(d.gpus[0].utilization_pct * 10) / 10 : 0;
                updateOverviewCircle('dashboard-overview-gpu-fill', 'dashboard-overview-gpu-value', gpuPct, gpuPct.toFixed(1) + '%');

                // CPU (raw 0-100)
                var cpuRaw = d.cpu_pct_raw != null ? Math.round(d.cpu_pct_raw * 10) / 10 : Math.min(100, Math.round((d.cpu_pct || 0) / 24));
                updateOverviewCircle('dashboard-overview-cpu-fill', 'dashboard-overview-cpu-value', cpuRaw, cpuRaw.toFixed(1) + '%');

                // VRAM
                var vramFill  = document.getElementById('dashboard-overview-vram-fill');
                var vramValue = document.getElementById('dashboard-overview-vram-value');
                if (vramFill && vramValue && d.gpus && d.gpus[0]) {
                    var usedMB  = d.gpus[0].memory_used_mb  || 0;
                    var totalMB = d.gpus[0].memory_total_mb || 49140;
                    var vramPct = Math.min(100, (usedMB / totalMB) * 100);
                    var c = 2 * Math.PI * 50;
                    vramFill.style.strokeDashoffset = (c - (vramPct / 100) * c).toString();
                    vramFill.style.stroke = 'url(#vram-gradient-clip)';
                    vramValue.textContent = (usedMB / 1024).toFixed(1) + '/' + Math.round(totalMB / 1024) + 'G';
                }
            }).catch(function(){});
        }
        _updateHardwareCirclesClipfarm();
        window._dashboardContextInterval = setInterval(_updateHardwareCirclesClipfarm, 2000);
        function updateStats() {
            var total = allAgents.length;
            var activeAgents = allAgents.filter(function (a) { return (a.current_tasks || 0) > 0; }).length;
            var activePercent = total ? (activeAgents / total) * 100 : 0;
            updateOverviewCircle('dashboard-overview-active-agents-fill', 'dashboard-overview-active-agents-value', activePercent, activeAgents + '/' + total);
            var activeTasks = allAgents.reduce(function (sum, agent) { return sum + (agent.current_tasks || 0); }, 0);
            var maxTasks = total ? total * 5 : 1;
            var activePercentTasks = Math.min(100, (activeTasks / maxTasks) * 100);
            updateOverviewCircle('dashboard-overview-active-fill', 'dashboard-overview-active-value', activePercentTasks, activeTasks);
            fetch('/api/dashboard/monitoring_jobs').then(function (r) { return r.json(); }).then(function (data) {
                var plannedList = data.planned;
                var plannedCount = Array.isArray(plannedList) ? plannedList.length : 0;
                var plannedPercent = Math.min(100, plannedCount * 10);
                updateOverviewCircle('dashboard-overview-planned-fill', 'dashboard-overview-planned-value', plannedPercent, String(plannedCount));
            }).catch(function () {
                updateOverviewCircle('dashboard-overview-planned-fill', 'dashboard-overview-planned-value', 0, '0');
            });
        }
        function showAgentDetails(agentName) {
            const agent = allAgents.find(a => a.name === agentName);
            if (!agent) return;
            document.getElementById('modal-title').textContent = `${agent.name} - Details`;
            document.getElementById('modal-content').innerHTML = `
                <div class="agent-details">
                    <h4>Role & Goal</h4>
                    <p><strong>Goal:</strong> ${agent.goal}</p>
                    <p><strong>Backstory:</strong> ${agent.backstory}</p>
                    <h4>Organization</h4>
                    <p><strong>Tier:</strong> ${agent.tier}</p>
                    <p><strong>Supervisor:</strong> ${agent.supervisor || 'None'}</p>
                    <p><strong>Subordinates:</strong> ${agent.subordinates.join(', ') || 'None'}</p>
                    <h4>Capabilities</h4>
                    <p><strong>Max Concurrent Tasks:</strong> ${agent.max_concurrent_tasks}</p>
                    <p><strong>Current Tasks:</strong> ${agent.current_tasks}</p>
                    ${agent.gpu_schedule ? `
                        <h4>GPU Schedule</h4>
                        <p><strong>Max GPU %:</strong> ${agent.gpu_schedule.max_gpu_percent}%</p>
                        <p><strong>Preferred Times:</strong> ${agent.gpu_schedule.preferred_time_slots.join(', ')}</p>
                        <p><strong>Priority:</strong> ${agent.gpu_schedule.priority_level}</p>
                        <p><strong>Duration:</strong> ${agent.gpu_schedule.estimated_duration_hours} hours</p>
                    ` : ''}
                    <h4>Tools</h4>
                    <div class="skills-list">
                        ${agent.tools.map(tool => `<span class="skill-tag">${tool}</span>`).join('')}
                    </div>
                    <h4>Skills</h4>
                    <div class="skills-list">
                        ${agent.skills.map(skill => `<span class="skill-tag">${skill}</span>`).join('')}
                    </div>
                </div>
            `;
            document.getElementById('agent-modal').style.display = 'block';
        }
        function closeModal() {
            document.getElementById('agent-modal').style.display = 'none';
        }
        // Close modal when clicking outside
        document.getElementById('agent-modal').onclick = function(e) {
            if (e.target === this) {
                closeModal();
            }
        };
        function autoFillTaskDescription() {
            const taskDescription = document.getElementById('task-description');
            if (!taskDescription) return;
            if (selectedAgents.length === 1) {
                const agent = selectedAgents[0];
                taskDescription.value = agent.primary_task || '';
            } else if (selectedAgents.length > 1) {
                taskDescription.value = 'Coordinate tasks among selected agents.';
            } else {
                taskDescription.value = '';
            }
        }
        // Schedule Modal Logic (updated for CPU/GPU split)
        // (REMOVED: All schedule modal and schedule-related JS code)
        /* 2026-07-17 modularization: dead code removed here (legacy schedule add-entry / tab code targeting DOM absent from this page). Original in crews_modularization_backups_20260717. */
        // Digital clock: timezone and optional manual time (from modal)
        function updateAmsterdamClock() {
            const clockTime = document.getElementById('clock-time');
            const clockDate = document.getElementById('clock-date');
            if (!clockTime || !clockDate) return;
            const manual = localStorage.getItem('dashboard_clock_manual');
            const tz = localStorage.getItem('dashboard_clock_timezone') || 'Europe/Amsterdam';
            let displayDate;
            if (manual === '1') {
                const stored = localStorage.getItem('dashboard_clock_datetime');
                const savedAt = parseInt(localStorage.getItem('dashboard_clock_manual_saved_at'), 10);
                if (stored && !isNaN(savedAt)) {
                    displayDate = new Date(new Date(stored).getTime() + (Date.now() - savedAt));
                } else if (stored) {
                    displayDate = new Date(stored);
                } else {
                    displayDate = new Date();
                }
            } else {
                displayDate = new Date();
            }
            const tzOpts = (tz && tz !== 'Local') ? { timeZone: tz } : {};
            clockTime.textContent = displayDate.toLocaleTimeString('en-GB', Object.assign({ hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }, tzOpts));
            clockDate.textContent = displayDate.toLocaleDateString('en-GB', Object.assign({ year: 'numeric', month: '2-digit', day: '2-digit' }, tzOpts));
        }
        setInterval(updateAmsterdamClock, 1000);
        updateAmsterdamClock();
        (function initClockModal() {
            const modal = document.getElementById('dashboard-clock-modal');
            const clockEl = document.getElementById('amsterdam-clock');
            const tzSelect = document.getElementById('dashboard-clock-timezone');
            const manualCb = document.getElementById('dashboard-clock-manual');
            const manualWrap = document.getElementById('dashboard-clock-manual-wrap');
            const datetimeInput = document.getElementById('dashboard-clock-datetime');
            const saveBtn = document.getElementById('dashboard-clock-save');
            const cancelBtn = document.getElementById('dashboard-clock-cancel');
            if (!modal || !clockEl) return;
            if (modal.style.display === 'none') modal.style.display = 'none';
            modal.style.display = 'none';
            modal.style.alignItems = 'center';
            modal.style.justifyContent = 'center';
            clockEl.addEventListener('click', function () {
                tzSelect.value = localStorage.getItem('dashboard_clock_timezone') || 'Europe/Amsterdam';
                manualCb.checked = localStorage.getItem('dashboard_clock_manual') === '1';
                manualWrap.style.display = manualCb.checked ? 'block' : 'none';
                var stored = localStorage.getItem('dashboard_clock_datetime');
                if (stored) {
                    var d = new Date(stored);
                    datetimeInput.value = d.toISOString().slice(0, 16);
                } else {
                    datetimeInput.value = new Date().toISOString().slice(0, 16);
                }
                modal.style.display = 'flex';
            });
            manualCb.addEventListener('change', function () { manualWrap.style.display = this.checked ? 'block' : 'none'; });
            function closeModal() { modal.style.display = 'none'; }
            saveBtn.addEventListener('click', function () {
                localStorage.setItem('dashboard_clock_timezone', tzSelect.value);
                localStorage.setItem('dashboard_clock_manual', manualCb.checked ? '1' : '0');
                if (manualCb.checked && datetimeInput.value) {
                    localStorage.setItem('dashboard_clock_datetime', new Date(datetimeInput.value).toISOString());
                    localStorage.setItem('dashboard_clock_manual_saved_at', String(Date.now()));
                }
                updateAmsterdamClock();
                closeModal();
            });
            cancelBtn.addEventListener('click', closeModal);
            modal.addEventListener('click', function (e) { if (e.target === modal) closeModal(); });
        })();
        /* 2026-07-17 modularization: dead code removed here (legacy schedule add-entry / tab code targeting DOM absent from this page). Original in crews_modularization_backups_20260717. */
        function updateDebugPanel(extraError) {
            const panel = document.getElementById('debug-panel');
            if (!panel) return;
            const mapping = window.agentModelBarMapping || {};
            const nAgents = Object.keys(mapping).length;
            const scheduleType = window.currentScheduleType;
            const availableAgents = scheduleType === 'gpu'
                ? Object.keys(mapping).filter(a => mapping[a].tier === 1)
                : Object.keys(mapping);
            let html = `<b>Debug Panel</b><br>`;
            html += `Mapping loaded: <b>${window.agentModelBarMappingLoaded}</b><br>`;
            html += `# agents in mapping: <b>${nAgents}</b><br>`;
            html += `Current schedule type: <b>${scheduleType}</b><br>`;
            html += `Available agents (${availableAgents.length}): <div style='max-height:60px;overflow:auto;'>${availableAgents.join(', ')}</div>`;
            if (extraError) html += `<div style='color:red;'><b>Error:</b> ${extraError}</div>`;
            panel.innerHTML = html;
        }
        // Fix select all logic for agent lists
        const selectAllBtnAll = document.getElementById('select-all-btn-all');
        if (selectAllBtnAll) {
            selectAllBtnAll.onclick = function() {
                document.querySelectorAll('#agent-list .agent-item').forEach(item => {
                    if (!item.classList.contains('selected')) item.classList.add('selected');
                });
                if (typeof allAgents !== 'undefined') {
                    selectedAgents = [...allAgents];
                    updateSelectedAgentsDisplay();
                    autoFillTaskDescription();
                }
            };
        }
        const selectAllBtnDept = document.getElementById('select-all-btn-dept');
        if (selectAllBtnDept) {
            selectAllBtnDept.onclick = function() {
                document.querySelectorAll('#department-agent-list .agent-item').forEach(item => {
                    if (!item.classList.contains('selected')) item.classList.add('selected');
                });
                const dept = document.getElementById('department-select');
                if (dept && typeof allAgents !== 'undefined') {
                    const deptAgents = allAgents.filter(a => a.department === dept.value);
                    selectedAgents = [...deptAgents];
                    updateSelectedAgentsDisplay();
                }
            };
        }
    <!-- Enhanced debug logging and timeline functions -->
    (function() {
        const origLog = console.log;
        const origErr = console.error;
        const origWarn = console.warn;
        function sendLog(level, args) {
            try {
                fetch('/api/frontend_log', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        level: level,
                        message: Array.from(args).map(a => (typeof a === 'object' ? JSON.stringify(a) : String(a))).join(' '),
                        ts: new Date().toISOString()
                    })
                });
            } catch (e) {}
        }
        console.log = function() { origLog.apply(console, arguments); sendLog('log', arguments); };
        console.error = function() { origErr.apply(console, arguments); sendLog('error', arguments); };
        console.warn = function() { origWarn.apply(console, arguments); sendLog('warn', arguments); };
    })();
    // Enhanced debug logging for timeline functions
    function debugLog(message, data) {
        const timestamp = new Date().toISOString();
        console.log(`[FRONTEND DEBUG] ${timestamp}: ${message}`);
        if (data) console.log('[FRONTEND DEBUG] Data:', data);
    }
        /* 2026-07-17 modularization: dead code removed here (legacy schedule add-entry / tab code targeting DOM absent from this page). Original in crews_modularization_backups_20260717. */
