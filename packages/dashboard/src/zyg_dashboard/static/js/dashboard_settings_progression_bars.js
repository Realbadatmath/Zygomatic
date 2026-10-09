// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Settings: Progression Bars - placeholder for progression bar style picker.
 */
(function () {
    'use strict';

    function openProgressionBars() {
        var overlay = document.getElementById('dashboard-settings-progression-overlay');
        if (overlay) { overlay.style.display = 'flex'; return; }
        overlay = document.createElement('div');
        overlay.id = 'dashboard-settings-progression-overlay';
        overlay.className = 'dashboard-settings-overlay';
        overlay.innerHTML = '<div class="dashboard-settings-panel">' +
            '<h3>Progression Bars</h3>' +
            '<p>Configure progression bar styles here. (Placeholder)</p>' +
            '<button type="button" class="btn dashboard-btn" id="dashboard-progression-close">Close</button>' +
            '</div>';
        overlay.onclick = function (e) { if (e.target === overlay) overlay.style.display = 'none'; };
        document.getElementById('dashboard-progression-close').onclick = function () { overlay.style.display = 'none'; };
        document.body.appendChild(overlay);
        overlay.style.display = 'flex';
    }

    window.DashboardSettings = window.DashboardSettings || {};
    window.DashboardSettings.openProgressionBars = openProgressionBars;
})();
