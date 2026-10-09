// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Settings: Backgrounds - list from Layouts and Themes/Background, preview, Apply, Apply To All.
 */
(function () {
    'use strict';

    var BG_VARIANTS = {
        'soft_backgrounds_test.html': ['bg37', 'bg1', 'bg2', 'bg3', 'bg4', 'bg5', 'bg6', 'bg7', 'bg8', 'bg9', 'bg10', 'bg11', 'bg12', 'bg13', 'bg14', 'bg15', 'bg16', 'bg17', 'bg18', 'bg19', 'bg20', 'bg21', 'bg22', 'bg23', 'bg24', 'bg25', 'bg26', 'bg27', 'bg28', 'bg29', 'bg30', 'bg31', 'bg32', 'bg33', 'bg34', 'bg35', 'bg36', 'bg37', 'bg38', 'bg39', 'bg40']
    };
    var BG_LABELS = { 'bg37': 'Smoky Pearl' };

    function openBackgrounds() {
        var overlay = document.getElementById('dashboard-settings-backgrounds-overlay');
        if (overlay) { overlay.style.display = 'flex'; return; }
        overlay = document.createElement('div');
        overlay.id = 'dashboard-settings-backgrounds-overlay';
        overlay.className = 'dashboard-settings-overlay';
        overlay.innerHTML = '<div class="dashboard-settings-panel">' +
            '<h3>Backgrounds</h3>' +
            '<div class="dashboard-settings-split">' +
            '<div class="dashboard-settings-list" id="dashboard-backgrounds-list"></div>' +
            '<div class="dashboard-settings-preview" id="dashboard-backgrounds-preview"><iframe id="dashboard-backgrounds-iframe" title="Preview"></iframe></div>' +
            '</div>' +
            '<button type="button" class="btn dashboard-btn" id="dashboard-backgrounds-apply">Apply</button>' +
            '</div>';
        overlay.onclick = function (e) { if (e.target === overlay) overlay.style.display = 'none'; };
        document.body.appendChild(overlay);

        var listEl = document.getElementById('dashboard-backgrounds-list');
        var iframe = document.getElementById('dashboard-backgrounds-iframe');
        fetch('/api/dashboard/themes/backgrounds/list').then(function (r) { return r.json(); }).then(function (files) {
            var html = '';
            (files || []).forEach(function (file) {
                var variants = BG_VARIANTS[file] || ['bg37'];
                variants.forEach(function (v) {
                    var label = BG_LABELS[v] || v;
                    html += '<div class="dashboard-settings-option" data-file="' + file + '" data-variant="' + v + '">' + label + '</div>';
                });
            });
            if (!html) html = '<div class="dashboard-settings-option" data-file="soft_backgrounds_test.html" data-variant="bg37">Smoky Pearl</div>';
            listEl.innerHTML = html;
            listEl.querySelectorAll('.dashboard-settings-option').forEach(function (el) {
                el.addEventListener('click', function () {
                    listEl.querySelectorAll('.dashboard-settings-option').forEach(function (x) { x.classList.remove('active'); });
                    this.classList.add('active');
                    var file = this.getAttribute('data-file');
                    iframe.src = '/api/dashboard/themes/backgrounds/file/' + encodeURIComponent(file);
                });
            });
        });

        document.getElementById('dashboard-backgrounds-apply').onclick = function () {
            var selected = listEl.querySelector('.dashboard-settings-option.active');
            if (!selected) { alert('Select a background first.'); return; }
            showApplyToTabsDialog(function (tabs) {
                fetch('/api/dashboard/themes/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        background_theme: {
                            file: selected.getAttribute('data-file'),
                            variant: selected.getAttribute('data-variant'),
                            label: selected.textContent
                        },
                        apply_background_to_tabs: tabs
                    })
                }).then(function (r) { return r.json(); }).then(function (res) {
                    if (res.success && window.DashboardTheme) window.DashboardTheme.apply();
                    overlay.style.display = 'none';
                });
            });
        };
        overlay.style.display = 'flex';
    }

    function showApplyToTabsDialog(callback) {
        var tabs = ['users', 'error_logs', 'job_status', 'monitoring_ui', 'api_authorization'];
        var html = '<div class="dashboard-dialog-overlay" id="dashboard-apply-bg-tabs-dialog">' +
            '<div class="dashboard-dialog">' +
            '<h4>Apply to tabs</h4>' +
            '<label><input type="checkbox" id="apply-bg-to-all" /> Apply To All</label>' +
            '<div id="apply-bg-tabs-list">' + tabs.map(function (t) { return '<label><input type="checkbox" class="apply-bg-tab-cb" value="' + t + '"/> ' + t + '</label>'; }).join('') + '</div>' +
            '<button type="button" class="btn dashboard-btn" id="apply-bg-tabs-ok">Apply</button>' +
            '</div></div>';
        var wrap = document.createElement('div');
        wrap.innerHTML = html;
        document.body.appendChild(wrap.firstElementChild);
        var d = document.getElementById('dashboard-apply-bg-tabs-dialog');
        document.getElementById('apply-bg-to-all').onclick = function () {
            d.querySelectorAll('.apply-bg-tab-cb').forEach(function (cb) { cb.checked = this.checked; }.bind(this));
        };
        document.getElementById('apply-bg-tabs-ok').onclick = function () {
            var list = d.querySelectorAll('.apply-bg-tab-cb:checked');
            var selected = list.length ? Array.from(list).map(function (c) { return c.value; }) : ['all'];
            if (d.querySelector('#apply-bg-to-all').checked) selected = ['all'];
            d.remove();
            callback(selected);
        };
    }

    window.DashboardSettings = window.DashboardSettings || {};
    window.DashboardSettings.openBackgrounds = openBackgrounds;
})();
