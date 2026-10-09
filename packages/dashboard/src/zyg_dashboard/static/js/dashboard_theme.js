// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Dashboard theme: load config, apply Smoky Pearl background + Scaled 18 Subtle buttons by default.
 * Persisted via /api/dashboard/themes/config.
 */
(function () {
    'use strict';

    var DEFAULT_BG = 'radial-gradient(circle at 0 0, #f4f2ef, transparent 55%), linear-gradient(145deg, #e0dbd4, #b8b1aa);';
    var DEFAULT_BTN = '.dashboard-btn, .btn { background: linear-gradient(140deg, #f3f5f9, #ccd1da 50%, #8d95a7) !important; color: #181b22 !important; border-radius: 999px; box-shadow: 0 1px 0 rgba(255,255,255,0.12), 0 2px 4px rgba(0,0,0,0.08); }';
    /* Lavender diagram boxes: injected here so they always override any cascade */
    var DIAGRAM_LAVENDER = '#security-diagrams-modal .diagram-box, #security-diagrams-modal .threat-model-column .diagram-box { background: #e8ecf7 !important; border: 1px solid #667eea !important; } #security-diagrams-modal .diagram-arrow { color: #667eea !important; }';

    function apply() {
        // Apply Smoky Pearl immediately so no purple flash before fetch completes
        document.body.style.background = DEFAULT_BG;
        document.body.style.minHeight = 'calc(100vh / var(--ui-zoom,1))';
        fetch('/api/dashboard/themes/config').then(function (r) { return r.json(); }).then(function (config) {
            var styleId = 'dashboard-theme-injected';
            var el = document.getElementById(styleId);
            if (!el) {
                el = document.createElement('style');
                el.id = styleId;
                document.head.appendChild(el);
            }
            var bg = DEFAULT_BG;
            var btn = DEFAULT_BTN;
            if (config.background_theme && config.background_theme.variant === 'bg37') {
                bg = DEFAULT_BG;
            }
            if (config.button_theme && (config.button_theme.variant === 's18' || config.button_theme.label === 'Scaled 18 Subtle')) {
                btn = DEFAULT_BTN;
            }
            el.textContent = '#dashboard-body.dashboard-body-default { background: ' + bg + ' !important; min-height: calc(100vh / var(--ui-zoom,1)); } ' + btn + ' ' + DIAGRAM_LAVENDER;
            document.body.classList.add('dashboard-body-default');
        }).catch(function () {
            var el = document.getElementById('dashboard-theme-injected');
            if (!el) {
                el = document.createElement('style');
                el.id = 'dashboard-theme-injected';
                document.head.appendChild(el);
            }
            el.textContent = '#dashboard-body.dashboard-body-default { background: ' + DEFAULT_BG + ' !important; min-height: calc(100vh / var(--ui-zoom,1)); } ' + DEFAULT_BTN + ' ' + DIAGRAM_LAVENDER;
        });
    }

    function applySidebar() {
        fetch('/api/dashboard/themes/config').then(function (r) { return r.json(); }).then(function (config) {
            var sb = config.sidebar_theme;
            var styleId = 'dashboard-sidebar-theme';
            var el = document.getElementById(styleId);
            if (!el) {
                el = document.createElement('style');
                el.id = styleId;
                document.head.appendChild(el);
            }
            if (sb && sb.background) {
                el.textContent = '.dashboard-sidebar { background: ' + sb.background + ' !important; }';
            } else {
                el.textContent = '';
            }
        }).catch(function () {});
    }
    window.DashboardTheme = { apply: apply, applySidebar: applySidebar };
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', apply);
    } else {
        apply();
    }
})();
