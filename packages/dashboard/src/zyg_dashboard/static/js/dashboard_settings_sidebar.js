// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Settings: Sidebar - list from Layouts and Themes/Sidebar, preview, Apply.
 */
(function () {
    'use strict';

    function openSidebar() {
        var overlay = document.getElementById('dashboard-settings-sidebar-overlay');
        if (overlay) { overlay.style.display = 'flex'; return; }
        overlay = document.createElement('div');
        overlay.id = 'dashboard-settings-sidebar-overlay';
        overlay.className = 'dashboard-settings-overlay';
        overlay.innerHTML = '<div class="dashboard-settings-panel">' +
            '<h3>Sidebar style</h3>' +
            '<div class="dashboard-settings-split">' +
            '<div class="dashboard-settings-list" id="dashboard-sidebar-list"></div>' +
            '<div class="dashboard-settings-preview"><iframe id="dashboard-sidebar-iframe" title="Preview"></iframe></div>' +
            '</div>' +
            '<button type="button" class="btn dashboard-btn" id="dashboard-sidebar-apply">Apply</button>' +
            '</div>';
        overlay.onclick = function (e) { if (e.target === overlay) overlay.style.display = 'none'; };
        document.body.appendChild(overlay);

        var listEl = document.getElementById('dashboard-sidebar-list');
        var iframe = document.getElementById('dashboard-sidebar-iframe');
        fetch('/api/dashboard/themes/sidebar/list').then(function (r) { return r.json(); }).then(function (files) {
            var html = (files || []).length ? (files || []).map(function (file) {
                return '<div class="dashboard-settings-option" data-file="' + file + '">' + file + '</div>';
            }).join('') : '<div class="dashboard-settings-option" data-file="">No sidebar styles found. Add HTML files to Layouts and Themes\\Sidebar.</div>';
            listEl.innerHTML = html;
            listEl.querySelectorAll('.dashboard-settings-option').forEach(function (el) {
                el.addEventListener('click', function () {
                    if (!this.getAttribute('data-file')) return;
                    listEl.querySelectorAll('.dashboard-settings-option').forEach(function (x) { x.classList.remove('active'); });
                    this.classList.add('active');
                    var file = this.getAttribute('data-file');
                    iframe.src = '/api/dashboard/themes/sidebar/file/' + encodeURIComponent(file);
                });
            });
        });

        document.getElementById('dashboard-sidebar-apply').onclick = function () {
            var selected = listEl.querySelector('.dashboard-settings-option.active');
            if (!selected || !selected.getAttribute('data-file')) { alert('Select a sidebar style first.'); return; }
            fetch('/api/dashboard/themes/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sidebar_theme: { file: selected.getAttribute('data-file'), label: selected.textContent }
                })
            }).then(function (r) { return r.json(); }).then(function (res) {
                if (res.success && window.DashboardTheme && window.DashboardTheme.applySidebar) window.DashboardTheme.applySidebar();
                overlay.style.display = 'none';
            });
        };
        overlay.style.display = 'flex';
    }

    window.DashboardSettings = window.DashboardSettings || {};
    window.DashboardSettings.openSidebar = openSidebar;
})();
