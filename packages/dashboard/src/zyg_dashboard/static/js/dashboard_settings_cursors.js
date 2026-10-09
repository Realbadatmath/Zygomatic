// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Settings: Cursors - select cursor style for the dashboard.
 * Shows "Apply selected?" confirmation before applying.
 * Persists choice in localStorage.
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'dashboard_cursor_style';
    var CURSOR_OPTIONS = [
        { value: 'default', label: 'Default (Arrow)' },
        { value: 'pointer', label: 'Pointer (Hand)' },
        { value: 'text', label: 'Text (I‑beam)' },
        { value: 'crosshair', label: 'Crosshair' },
        { value: 'move', label: 'Move (Four arrows)' },
        { value: 'grab', label: 'Grab (Open hand)' },
        { value: 'grabbing', label: 'Grabbing (Closed hand)' },
        { value: 'wait', label: 'Wait (Hourglass)' },
        { value: 'progress', label: 'Progress (Arrow + Hourglass)' },
        { value: 'not-allowed', label: 'Not allowed (Prohibited)' },
        { value: 'no-drop', label: 'No drop' },
        { value: 'zoom-in', label: 'Zoom in (Magnify +)' },
        { value: 'zoom-out', label: 'Zoom out (Magnify -)' },
        { value: 'copy', label: 'Copy' },
        { value: 'alias', label: 'Alias (Link)' },
        { value: 'cell', label: 'Cell (Table selection)' },
        { value: 'context-menu', label: 'Context menu' },
        { value: 'help', label: 'Help (Question mark)' },
        { value: 'n-resize', label: 'North resize (↕)' },
        { value: 'ne-resize', label: 'North-east resize (↗)' }
    ];

    function getStoredCursor() {
        try {
            return localStorage.getItem(STORAGE_KEY) || 'default';
        } catch (e) {
            return 'default';
        }
    }

    function setStoredCursor(value) {
        try {
            localStorage.setItem(STORAGE_KEY, value || 'default');
        } catch (e) {}
    }

    function applyCursor(value) {
        var v = value || getStoredCursor();
        if (document.body) document.body.style.cursor = v;
        if (document.documentElement) document.documentElement.style.cursor = v;
    }

    function showApplyDialog(cursorValue, cursorLabel, onYes, onNo) {
        var overlay = document.getElementById('dashboard-cursors-apply-dialog');
        if (overlay) {
            overlay.style.display = 'flex';
            return;
        }
        overlay = document.createElement('div');
        overlay.id = 'dashboard-cursors-apply-dialog';
        overlay.className = 'dashboard-settings-overlay';
        overlay.innerHTML = '<div class="dashboard-settings-panel" style="max-width:360px;">' +
            '<h3 class="dashboard-settings-panel-title">Apply selected?</h3>' +
            '<p style="margin:16px 0;color:#555;">Apply cursor: <strong id="dashboard-cursors-apply-label">' + (cursorLabel || '') + '</strong></p>' +
            '<div style="display:flex;gap:12px;justify-content:flex-end;">' +
            '<button type="button" class="btn dashboard-btn btn-secondary" id="dashboard-cursors-apply-no">No</button>' +
            '<button type="button" class="btn dashboard-btn" id="dashboard-cursors-apply-yes">Yes</button>' +
            '</div></div>';
        overlay.onclick = function (e) {
            if (e.target === overlay) {
                overlay.style.display = 'none';
                if (onNo) onNo();
            }
        };
        document.body.appendChild(overlay);

        var labelEl = document.getElementById('dashboard-cursors-apply-label');
        if (labelEl) labelEl.textContent = cursorLabel || '';

        document.getElementById('dashboard-cursors-apply-yes').onclick = function () {
            overlay.style.display = 'none';
            if (onYes) onYes();
        };
        document.getElementById('dashboard-cursors-apply-no').onclick = function () {
            overlay.style.display = 'none';
            if (onNo) onNo();
        };
        overlay.style.display = 'flex';
    }

    function openCursors() {
        var overlay = document.getElementById('dashboard-settings-cursors-overlay');
        if (overlay) {
            overlay.style.display = 'flex';
            return;
        }
        overlay = document.createElement('div');
        overlay.id = 'dashboard-settings-cursors-overlay';
        overlay.className = 'dashboard-settings-overlay';
        overlay.innerHTML = '<div class="dashboard-settings-panel">' +
            '<h3 class="dashboard-settings-panel-title">Cursors</h3>' +
            '<p style="margin-bottom:16px;color:#666;font-size:0.9rem;">Select a cursor style. When you pick one, you will be asked to confirm before applying.</p>' +
            '<div class="dashboard-settings-list" id="dashboard-cursors-list" style="max-height:400px;"></div>' +
            '</div>';
        overlay.onclick = function (e) {
            if (e.target === overlay) overlay.style.display = 'none';
        };
        document.body.appendChild(overlay);

        var listEl = document.getElementById('dashboard-cursors-list');
        var stored = getStoredCursor();
        var html = '';
        CURSOR_OPTIONS.forEach(function (opt) {
            var active = opt.value === stored ? ' active' : '';
            html += '<div class="dashboard-settings-option cursor-option' + active + '" data-cursor="' + opt.value + '" data-label="' + (opt.label || opt.value) + '" style="cursor:' + opt.value + ';">' +
                (opt.label || opt.value) + '</div>';
        });
        listEl.innerHTML = html;

        function updateActiveState() {
            var current = getStoredCursor();
            listEl.querySelectorAll('.cursor-option').forEach(function (x) {
                x.classList.toggle('active', x.getAttribute('data-cursor') === current);
            });
        }
        listEl.querySelectorAll('.cursor-option').forEach(function (el) {
            el.addEventListener('click', function () {
                var value = this.getAttribute('data-cursor');
                var label = this.getAttribute('data-label') || value;
                showApplyDialog(value, label, function () {
                    setStoredCursor(value);
                    applyCursor(value);
                    updateActiveState();
                    overlay.style.display = 'none';
                }, function () {
                    updateActiveState();
                });
            });
        });
        overlay.style.display = 'flex';
    }

    function initStoredCursor() {
        document.addEventListener('DOMContentLoaded', function () {
            applyCursor(getStoredCursor());
        });
        if (document.readyState === 'loading') {
            /* already queued above */
        } else {
            applyCursor(getStoredCursor());
        }
    }

    window.DashboardSettings = window.DashboardSettings || {};
    window.DashboardSettings.openCursors = openCursors;
    window.DashboardSettings.applyStoredCursor = function () { applyCursor(); };
    initStoredCursor();
})();
