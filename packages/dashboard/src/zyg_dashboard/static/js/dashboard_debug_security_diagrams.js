// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Debug script for Security Diagrams modal and Expanded View.
 * Enable: set window.DEBUG_SECURITY_DIAGRAMS = true before or after load, then open Security Diagrams.
 * Or add ?debug=security-diagrams to the URL and ensure this script runs.
 * Exposes: window.SecurityDiagramsDebug.dump(), .panel()
 */
(function () {
    'use strict';

    var LOG_PREFIX = '[Security Diagrams Debug]';

    function byId(id) {
        return document.getElementById(id);
    }

    function dump() {
        var modal = byId('security-diagrams-modal');
        var dialog = byId('security-diagrams-dialog');
        var viewer = byId('security-diagrams-3d-viewer');
        var lines = [
            '--- Security Diagrams state ---',
            'Modal: ' + (modal ? 'found' : 'MISSING'),
            'Modal display: ' + (modal ? modal.style.display : 'n/a'),
            'Modal has flex centering: ' + (modal && (modal.style.alignItems === 'center' || getComputedStyle(modal).alignItems === 'center')),
            'Dialog: ' + (dialog ? 'found' : 'MISSING'),
            'Dialog expanded (fullscreen class): ' + (dialog && dialog.classList.contains('security-diagrams-fullscreen')),
            'Viewer (pyramid container): ' + (viewer ? 'found' : 'MISSING'),
            'Viewer has object (pyramid SVG): ' + (viewer && viewer.querySelector('object') ? 'yes' : 'no')
        ];
        if (modal) {
            var mr = modal.getBoundingClientRect();
            lines.push('Modal rect: top=' + mr.top + ' left=' + mr.left + ' width=' + mr.width + ' height=' + mr.height);
        }
        if (dialog) {
            var dr = dialog.getBoundingClientRect();
            var cs = getComputedStyle(dialog);
            lines.push('Dialog rect: top=' + dr.top + ' left=' + dr.left + ' width=' + dr.width + ' height=' + dr.height);
            lines.push('Dialog position: ' + cs.position + ', margin: ' + cs.margin);
        }
        var text = lines.join('\n');
        if (typeof console !== 'undefined' && console.log) console.log(LOG_PREFIX + '\n' + text);
        return text;
    }

    function updatePanel() {
        var el = byId('security-diagrams-debug-panel');
        if (!el) return;
        el.innerHTML = '<pre style="margin:0;font-size:11px;white-space:pre-wrap;">' + dump().replace(/</g, '&lt;') + '</pre>';
    }

    function panel(show) {
        var id = 'security-diagrams-debug-panel';
        var el = byId(id);
        if (show !== false) {
            if (!el) {
                el = document.createElement('div');
                el.id = id;
                el.style.cssText = 'position:fixed;bottom:8px;left:8px;max-width:320px;max-height:240px;overflow:auto;background:#1e1e1e;color:#d4d4d4;padding:8px;border-radius:6px;font-family:monospace;z-index:99999;font-size:11px;box-shadow:0 4px 12px rgba(0,0,0,0.4);';
                document.body.appendChild(el);
            }
            el.style.display = 'block';
            updatePanel();
        } else if (el) {
            el.style.display = 'none';
        }
    }

    function installHooks() {
        if (window._securityDiagramsDebugHooksInstalled) return;
        window._securityDiagramsDebugHooksInstalled = true;

        var wrap = function (name, fn) {
            return function () {
                if (window.DEBUG_SECURITY_DIAGRAMS && console && console.log) {
                    console.log(LOG_PREFIX + ' ' + name + ' called');
                }
                var result = fn.apply(this, arguments);
                if (window.DEBUG_SECURITY_DIAGRAMS) {
                    setTimeout(updatePanel, 50);
                }
                return result;
            };
        };

        if (typeof window.openSecurityDiagramsModal === 'function') {
            window.openSecurityDiagramsModal = wrap('openSecurityDiagramsModal', window.openSecurityDiagramsModal);
        }
        if (typeof window.closeSecurityDiagramsModal === 'function') {
            window.closeSecurityDiagramsModal = wrap('closeSecurityDiagramsModal', window.closeSecurityDiagramsModal);
        }

        var enterFn = window.enterSecurityDiagramsFullscreen;
        var exitFn = window.exitSecurityDiagramsFullscreen;
        if (typeof enterFn === 'function') {
            window.enterSecurityDiagramsFullscreen = wrap('enterSecurityDiagramsFullscreen (Advanced View)', enterFn);
        }
        if (typeof exitFn === 'function') {
            window.exitSecurityDiagramsFullscreen = wrap('exitSecurityDiagramsFullscreen', exitFn);
        }

        if (window.DEBUG_SECURITY_DIAGRAMS && console && console.log) {
            console.log(LOG_PREFIX + ' Hooks installed. Use SecurityDiagramsDebug.dump() or SecurityDiagramsDebug.panel(true).');
        }
    }

    function init() {
        if (window.location.search.indexOf('debug=security-diagrams') !== -1) {
            window.DEBUG_SECURITY_DIAGRAMS = true;
        }
        if (window.DEBUG_SECURITY_DIAGRAMS) {
            installHooks();
            if (typeof requestAnimationFrame !== 'undefined') {
                requestAnimationFrame(function () {
                    if (byId('security-diagrams-dialog')) {
                        panel(true);
                    }
                });
            }
        } else {
            installHooks();
        }

        window.SecurityDiagramsDebug = {
            dump: dump,
            panel: panel,
            update: updatePanel,
            enable: function () { window.DEBUG_SECURITY_DIAGRAMS = true; installHooks(); }
        };
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
