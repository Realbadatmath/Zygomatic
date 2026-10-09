// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Settings: Buttons - list from Layouts and Themes/Buttons, preview, Apply, Apply To All.
 */
(function () {
    'use strict';

    var BUTTON_VARIANTS = {
        'scaled_steel_buttons_test.html': [
            's1','s2','s3','s4','s5','s6','s7','s8','s9','s10','s11','s12','s13','s14','s15','s16','s17','s18','s19','s20'
        ]
    };
    var BUTTON_LABELS = { 's18': 'Scaled 18 Subtle', 's1': 'Scaled 01', 's2': 'Scaled 02' };

    function openButtons() {
        var overlay = document.getElementById('dashboard-settings-buttons-overlay');
        if (overlay) { overlay.style.display = 'flex'; return; }
        overlay = document.createElement('div');
        overlay.id = 'dashboard-settings-buttons-overlay';
        overlay.className = 'dashboard-settings-overlay';
        overlay.innerHTML = '<div class="dashboard-settings-panel">' +
            '<h3>Buttons</h3>' +
            '<div class="dashboard-settings-split">' +
            '<div class="dashboard-settings-list" id="dashboard-buttons-list"></div>' +
            '<div class="dashboard-settings-preview" id="dashboard-buttons-preview"><iframe id="dashboard-buttons-iframe" title="Preview"></iframe></div>' +
            '</div>' +
            '<button type="button" class="btn dashboard-btn" id="dashboard-buttons-apply">Apply</button>' +
            '</div>';
        overlay.onclick = function (e) { if (e.target === overlay) overlay.style.display = 'none'; };
        document.body.appendChild(overlay);

        var listEl = document.getElementById('dashboard-buttons-list');
        var iframe = document.getElementById('dashboard-buttons-iframe');
        fetch('/api/dashboard/themes/buttons/list').then(function (r) { return r.json(); }).then(function (files) {
            var html = '';
            (files || []).forEach(function (file) {
                var variants = BUTTON_VARIANTS[file] || ['s18'];
                variants.forEach(function (v) {
                    var label = BUTTON_LABELS[v] || v;
                    html += '<div class="dashboard-settings-option" data-file="' + file + '" data-variant="' + v + '">' + file + ' &ndash; ' + label + '</div>';
                });
            });
            if (!html) html = '<div class="dashboard-settings-option" data-file="scaled_steel_buttons_test.html" data-variant="s18">Scaled 18 Subtle</div>';
            listEl.innerHTML = html;
            listEl.querySelectorAll('.dashboard-settings-option').forEach(function (el) {
                el.addEventListener('click', function () {
                    listEl.querySelectorAll('.dashboard-settings-option').forEach(function (x) { x.classList.remove('active'); });
                    this.classList.add('active');
                    var file = this.getAttribute('data-file');
                    iframe.src = '/api/dashboard/themes/buttons/file/' + encodeURIComponent(file);
                });
            });
        });

        document.getElementById('dashboard-buttons-apply').onclick = function () {
            var selected = listEl.querySelector('.dashboard-settings-option.active');
            if (!selected) { alert('Select a button style first.'); return; }
            showApplyToTabsDialog(function (tabs) {
                fetch('/api/dashboard/themes/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        button_theme: {
                            file: selected.getAttribute('data-file'),
                            variant: selected.getAttribute('data-variant'),
                            label: selected.textContent
                        },
                        apply_buttons_to_tabs: tabs
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
        var html = '<div class="dashboard-dialog-overlay" id="dashboard-apply-tabs-dialog">' +
            '<div class="dashboard-dialog">' +
            '<h4>Apply to tabs</h4>' +
            '<label><input type="checkbox" id="apply-to-all" /> Apply To All</label>' +
            '<div id="apply-tabs-list">' + tabs.map(function (t) { return '<label><input type="checkbox" class="apply-tab-cb" value="' + t + '"/> ' + t + '</label>'; }).join('') + '</div>' +
            '<button type="button" class="btn dashboard-btn" id="apply-tabs-ok">Apply</button>' +
            '</div></div>';
        var wrap = document.createElement('div');
        wrap.innerHTML = html;
        document.body.appendChild(wrap.firstElementChild);
        var d = document.getElementById('dashboard-apply-tabs-dialog');
        document.getElementById('apply-to-all').onclick = function () {
            d.querySelectorAll('.apply-tab-cb').forEach(function (cb) { cb.checked = this.checked; }.bind(this));
        };
        document.getElementById('apply-tabs-ok').onclick = function () {
            var list = d.querySelectorAll('.apply-tab-cb:checked');
            var selected = list.length ? Array.from(list).map(function (c) { return c.value; }) : ['all'];
            if (d.querySelector('#apply-to-all').checked) selected = ['all'];
            d.remove();
            callback(selected);
        };
    }

    window.DashboardSettings = window.DashboardSettings || {};
    window.DashboardSettings.openButtons = openButtons;
})();
