// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Dashboard tab: Api Authorization
 * Placeholder UI for API authorization management.
 */
(function () {
    'use strict';

    function render(container) {
        if (!container) return;
        container.innerHTML = '<div class="dashboard-api-auth">' +
            '<h3>Api Authorization</h3>' +
            '<p>Manage API keys and authorization rules here.</p>' +
            '<div class="dashboard-api-auth-placeholder">Content to be implemented.</div>' +
            '</div>';
    }

    window.DashboardTabApiAuth = { render: render };
})();
