// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Dashboard Settings - Hotkeys: table of tab -> hotkey, capture and execute.
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'dashboard_hotkeys';
    var HOTKEY_TARGETS = [
        { id: 'agent_overview', label: 'Agent Overview', href: null },
        { id: 'error_logs', label: 'Error Logs', href: null },
        { id: 'job_status', label: 'Job Status', href: null },
        { id: 'monitoring_ui', label: 'Monitoring UI', href: null },
        { id: 'gpu_schedule', label: 'GPU Schedule', href: 'gpu_schedule.html' },
        { id: 'cpu_schedule', label: 'CPU Schedule', href: 'cpu_schedule.html' }
    ];

    function byId(id) { return document.getElementById(id); }

    function getStored() {
        try {
            var raw = localStorage.getItem(STORAGE_KEY);
            return raw ? JSON.parse(raw) : {};
        } catch (e) { return {}; }
    }
    function setStored(obj) {
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(obj)); } catch (e) {}
    }

    function keyComboFromEvent(e) {
        var parts = [];
        if (e.ctrlKey) parts.push('Ctrl');
        if (e.altKey) parts.push('Alt');
        if (e.shiftKey) parts.push('Shift');
        if (e.metaKey) parts.push('Meta');
        var key = e.key;
        if (key && key.length === 1) key = key.toUpperCase();
        if (key && key !== 'Control' && key !== 'Alt' && key !== 'Shift' && key !== 'Meta') parts.push(key);
        return parts.join('+');
    }

    function normalizeCombo(s) {
        if (!s || !s.trim()) return '';
        var parts = s.split('+').map(function (p) { return p.trim(); }).filter(Boolean);
        var order = ['Ctrl', 'Alt', 'Shift', 'Meta'];
        var mods = [];
        var keyPart = null;
        for (var i = 0; i < parts.length; i++) {
            var p = parts[i];
            if (order.indexOf(p) >= 0) mods.push(p);
            else keyPart = p;
        }
        mods.sort(function (a, b) { return order.indexOf(a) - order.indexOf(b); });
        if (keyPart) mods.push(keyPart);
        return mods.join('+');
    }

    function getCurrentPanel() {
        var active = document.querySelector('.dashboard-sidebar-tab.active');
        if (active) return active.getAttribute('data-tab');
        var visible = document.querySelector('.dashboard-tab-panel.active');
        if (visible) {
            var id = visible.id;
            if (id && id.indexOf('panel-') === 0) return id.replace('panel-', '');
        }
        return 'agent_overview';
    }

    function executeHotkey(targetId) {
        var target = HOTKEY_TARGETS.filter(function (t) { return t.id === targetId; })[0];
        if (!target) return;
        var pathname = window.location.pathname || '';
        var onGpuPage = pathname.indexOf('gpu_schedule') >= 0;
        var onCpuPage = pathname.indexOf('cpu_schedule') >= 0;
        var onSchedulePage = onGpuPage || onCpuPage;

        if (target.href) {
            if (onGpuPage && targetId === 'gpu_schedule') {
                window.location.href = '/';
                return;
            }
            if (onCpuPage && targetId === 'cpu_schedule') {
                window.location.href = '/';
                return;
            }
            window.location.href = '/' + target.href;
            return;
        }
        if (onSchedulePage) {
            var tabToPath = { agent_overview: '/', error_logs: '/error_logs', job_status: '/job_status', monitoring_ui: '/monitoring_ui' };
            var path = tabToPath[targetId];
            window.location.href = path != null ? path : '/';
            return;
        }
        var current = getCurrentPanel();
        if (current === targetId) {
            if (window.DashboardTabs && window.DashboardTabs.showPanel) {
                window.DashboardTabs.showPanel('agent_overview');
                if (window.DashboardTabs.renderTab) window.DashboardTabs.renderTab('agent_overview');
            }
        } else {
            if (window.DashboardTabs && window.DashboardTabs.showPanel) {
                window.DashboardTabs.showPanel(targetId);
                if (window.DashboardTabs.renderTab) window.DashboardTabs.renderTab(targetId);
            }
        }
    }

    function renderTable() {
        var tbody = byId('dashboard-hotkeys-tbody');
        if (!tbody) return;
        var stored = getStored();
        var selectedInputs = [];

        tbody.innerHTML = HOTKEY_TARGETS.map(function (t) {
            var value = stored[t.id] || '';
            return '<tr><td>' + t.label + '</td><td><input type="text" class="dashboard-hotkey-input" data-target="' + t.id + '" value="' + (value ? value.replace(/"/g, '&quot;') : '') + '" readonly></td></tr>';
        }).join('');

        tbody.querySelectorAll('.dashboard-hotkey-input').forEach(function (input) {
            input.addEventListener('click', function (e) {
                if (e.detail === 2) {
                    e.preventDefault();
                    input.readOnly = false;
                    input.focus();
                    input.value = '';
                    input.select();
                    input.classList.add('selected');
                    selectedInputs = [input];
                    return;
                }
                input.readOnly = true;
                input.classList.add('selected');
                selectedInputs = [input];
                tbody.querySelectorAll('.dashboard-hotkey-input').forEach(function (inp) {
                    if (inp !== input) inp.classList.remove('selected');
                });
            });
            input.addEventListener('contextmenu', function (e) {
                if (e.ctrlKey) {
                    e.preventDefault();
                    if (selectedInputs.indexOf(input) >= 0) {
                        input.classList.remove('selected');
                        selectedInputs = selectedInputs.filter(function (inp) { return inp !== input; });
                    } else {
                        input.classList.add('selected');
                        selectedInputs.push(input);
                    }
                }
            });
            input.addEventListener('dblclick', function (e) {
                e.preventDefault();
                input.readOnly = false;
                input.focus();
                input.value = '';
                input.select();
            });
            input.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    var combo = normalizeCombo(input.value.trim());
                    if (combo) {
                        var o = getStored();
                        Object.keys(o).forEach(function (k) {
                            if (o[k] === combo && k !== input.getAttribute('data-target')) delete o[k];
                        });
                        o[input.getAttribute('data-target')] = combo;
                        setStored(o);
                        input.value = combo;
                    }
                    input.readOnly = true;
                    input.blur();
                    return;
                }
                if (e.key === 'Delete' || e.key === 'Backspace') {
                    e.preventDefault();
                    if (selectedInputs.length > 0) {
                        selectedInputs.forEach(function (inp) {
                            var o = getStored();
                            delete o[inp.getAttribute('data-target')];
                            setStored(o);
                            inp.value = '';
                            inp.classList.remove('selected');
                        });
                        selectedInputs = [];
                    } else {
                        var o = getStored();
                        delete o[input.getAttribute('data-target')];
                        setStored(o);
                        input.value = '';
                    }
                    return;
                }
                if (e.key === 'Escape') {
                    input.readOnly = true;
                    input.value = stored[input.getAttribute('data-target')] || '';
                    input.blur();
                    return;
                }
                e.preventDefault();
                input.value = keyComboFromEvent(e);
            });
            input.addEventListener('blur', function () {
                if (!input.readOnly) {
                    input.readOnly = true;
                    input.value = stored[input.getAttribute('data-target')] || '';
                }
            });
        });
    }

    function initGlobalListener() {
        document.addEventListener('keydown', function (e) {
            var active = document.activeElement;
            var isHotkeyInput = active && active.classList && active.classList.contains('dashboard-hotkey-input');
            if (isHotkeyInput) return;
            if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) return;

            var combo = keyComboFromEvent(e);
            if (!combo) return;
            var stored = getStored();
            for (var targetId in stored) {
                if (stored[targetId] === combo) {
                    e.preventDefault();
                    executeHotkey(targetId);
                    return;
                }
            }
        });
    }

    window.DashboardSettingsHotkeys = {
        render: renderTable,
        getStored: getStored,
        setStored: setStored,
        executeHotkey: executeHotkey,
        initGlobalListener: initGlobalListener
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            window.DashboardSettingsHotkeys.initGlobalListener();
        });
    } else {
        window.DashboardSettingsHotkeys.initGlobalListener();
    }
})();
