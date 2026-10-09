// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * CrewAI Dashboard - Tab switching and panel rendering.
 * Modular tab scripts render their content into panel-* elements.
 */
(function () {
    'use strict';

    /**
     * Diagram layout dimensions – aligned to .diagram-box and Arrowheads Svg 1.svg.
     * Box: padding 10px 14px, font 13px, line-height ~1.35, border 1px → height 40px.
     * Step width (box + gap + arrow): ~160px average for perRow calculation.
     */
    var DIAGRAM_LAYOUT = {
        BOX_HEIGHT: 40,
        BOX_PADDING_V: 10,
        BOX_PADDING_H: 14,
        GAP_HORIZONTAL: 8,
        ARROW_WIDTH: 12,
        STEP_WIDTH_AVG: 160,
        U_VIEWBOX: { x: 448, y: 292, w: 22, h: 50 },
        U_DISPLAY_W: 18,
        U_DISPLAY_H: 40,
        U_MARGIN_V: 2
    };

    /** Web Security 13-step diagram – from test_diagram_boxes_arrows.html / diagram_boxes_and_arrows_13_steps.svg */
    var WEB_SECURITY_STEPS = [
        'Reverse proxy + TLS + headers',
        'Cookie/session settings',
        'CSRF protection',
        'CORS locked down',
        'Request validation + size limits',
        'CSP + remove inline JS',
        'XSS hardening in templates',
        'Rate limiting',
        'Error/info leakage hardening',
        'Upload security',
        'Security logging + alerting',
        'Dependency pinning + scanning',
        'Fail-closed control-plane-down behavior'
    ];
    var webSecurityDiagramRendered = false;
    function ensureWebSecurityDiagramRendered() {
        if (webSecurityDiagramRendered) return;
        var stack = byId('security-diagram-web-stack');
        if (stack) attachWebSecurityStackClicks(stack);
        webSecurityDiagramRendered = true;
    }

    function attachWebSecurityStackClicks(containerEl) {
        if (!containerEl) return;
        var boxes = containerEl.querySelectorAll('.diagram-box[data-step]');
        boxes.forEach(function (el) {
            var stepIndex = parseInt(el.getAttribute('data-step'), 10);
            if (stepIndex >= 1 && stepIndex <= 13) {
                el.style.cursor = 'pointer';
                el.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    showDiagramBoxInfo((el.textContent || '').trim(), 'web', stepIndex, el, 0);
                });
            }
        });
    }

    function attachWebSecuritySvgClicks(containerEl) {
        if (!containerEl) return;
        var boxes = containerEl.querySelectorAll('.diagram-box[data-step]');
        boxes.forEach(function (el) {
            var stepIndex = parseInt(el.getAttribute('data-step'), 10);
            if (stepIndex >= 1 && stepIndex <= 13) {
                el.style.cursor = 'pointer';
                el.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    showDiagramBoxInfo((el.textContent || '').trim(), 'web', stepIndex, el, 0);
                });
            }
        });
    }

    function byId(id) { return document.getElementById(id); }
    function showPanel(tabId) {
        if (typeof window.closeSecurityDiagramsModal === 'function') window.closeSecurityDiagramsModal();
        document.querySelectorAll('.dashboard-tab-panel').forEach(function (el) {
            el.classList.remove('active');
            el.style.setProperty('display', 'none', 'important');
        });
        document.querySelectorAll('.dashboard-sidebar-tab').forEach(function (el) {
            el.classList.toggle('active', el.getAttribute('data-tab') === tabId);
        });
        var panel = byId('panel-' + tabId);
        if (panel) {
            panel.style.setProperty('display', 'block', 'important');
            panel.classList.add('active');
        }
    }

    function initSidebar() {
        document.querySelectorAll('.dashboard-sidebar-tab').forEach(function (el) {
            var href = el.getAttribute('href') || el.getAttribute('data-href');
            if (href) {
                /* Native anchor navigation – no JS handler needed; works even if extensions block JS */
                return;
            }
            el.addEventListener('click', function () {
                var tab = this.getAttribute('data-tab');
                showPanel(tab);
                if (window.history && window.history.pushState) {
                    history.pushState({ dashboardTab: tab }, '', window.location.pathname + window.location.search);
                }
                if (window.DashboardTabs && window.DashboardTabs.renderTab) {
                    window.DashboardTabs.renderTab(tab);
                }
            });
        });
    }

    var LOGIN_METHOD_FIELDS = {
        id_password_sms: [
            { name: 'server_name', label: 'Server Name', type: 'text' },
            { name: 'sms_server_api', label: 'Sms Server Api', type: 'text' }
        ],
        id_password_phone: [
            { name: 'server_name', label: 'Server Name', type: 'text' },
            { name: 'phone_api', label: 'Phone/VoIP API', type: 'text' }
        ],
        microsoft_code: [
            { name: 'tenant_id', label: 'Tenant ID', type: 'text' },
            { name: 'client_id', label: 'Client ID', type: 'text' },
            { name: 'client_secret', label: 'Client Secret', type: 'password' },
            { name: 'redirect_uri', label: 'Redirect URI (optional)', type: 'text' }
        ],
        retinal_scan: [
            { name: 'device_name', label: 'Device/Server Name', type: 'text' },
            { name: 'biometric_api', label: 'Biometric API Endpoint', type: 'text' }
        ],
        finger_scan: [
            { name: 'device_name', label: 'Device/Server Name', type: 'text' },
            { name: 'biometric_api', label: 'Biometric API Endpoint', type: 'text' }
        ]
    };
    var LOGIN_METHOD_LABELS = {
        id_password_sms: 'ID/Password + Sms',
        id_password_phone: 'ID/Password + Phone Call',
        microsoft_code: 'Microsoft Code',
        retinal_scan: 'Retinal Scan',
        finger_scan: 'Finger Scan'
    };

    function spectatorSettingsBlock() {
        if (window.DASHBOARD_USER_ROLE === 'spectators') {
            alert('This action is not allowed as Spectator');
            return true;
        }
        return false;
    }
    var securityDiagramsEscHandler = null;
    var LAVENDER_FILL = '#e8ecf7';
    var LAVENDER_BORDER = '#667eea';
    function applyDiagramLavenderStyles() {
        var modal = byId('security-diagrams-modal');
        if (!modal) return;
        modal.querySelectorAll('.diagram-box').forEach(function (el) {
            el.style.setProperty('background', LAVENDER_FILL, 'important');
            el.style.setProperty('border', '1px solid ' + LAVENDER_BORDER, 'important');
        });
        modal.querySelectorAll('.diagram-arrow').forEach(function (el) {
            el.style.setProperty('color', LAVENDER_BORDER, 'important');
        });
    }
    function openLlmsListOverlay() {
        var overlay = byId('dashboard-llms-overlay');
        if (overlay) {
            overlay.style.display = 'flex';
            var listEl = byId('dashboard-llms-list');
            if (listEl && !listEl.dataset.loaded) {
                listEl.dataset.loaded = '1';
                fetch('/api/llms/list').then(function (r) { return r.ok ? r.json() : []; }).catch(function () { return []; })
                    .then(function (llms) {
                        listEl.innerHTML = (Array.isArray(llms) ? llms : []).length === 0
                            ? '<p style="color:#666;">No LLMs found. Add ai_models to agent configs or LLMS documents in Feedback &amp; Workflow.</p>'
                            : '<ul style="list-style:none;padding:0;margin:0;max-height:360px;overflow-y:auto;">' + llms.map(function (m) { return '<li style="padding:8px 12px;border-bottom:1px solid #eee;">' + m + '</li>'; }).join('') + '</ul>';
                    });
            }
            return;
        }
        overlay = document.createElement('div');
        overlay.id = 'dashboard-llms-overlay';
        overlay.className = 'dashboard-modal-overlay';
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:6000;display:flex;align-items:center;justify-content:center;';
        overlay.innerHTML = '<div style="background:#fff;padding:24px;border-radius:12px;max-width:480px;width:90%;max-height:calc(80vh / var(--ui-zoom,1));overflow:hidden;display:flex;flex-direction:column;box-shadow:0 8px 32px rgba(0,0,0,0.2);">' +
            '<h3 style="margin:0 0 16px 0;">LLMs</h3>' +
            '<p style="color:#666;font-size:0.9rem;margin:0 0 12px 0;">Unique LLMs from agent configs and Feedback &amp; Workflow LLMS documents.</p>' +
            '<div id="dashboard-llms-list" style="flex:1;overflow-y:auto;"><p style="color:#666;">Loading…</p></div>' +
            '<button type="button" class="btn dashboard-btn" id="dashboard-llms-close" style="margin-top:16px;">Close</button></div>';
        overlay.onclick = function (e) { if (e.target === overlay) overlay.style.display = 'none'; };
        document.body.appendChild(overlay);
        byId('dashboard-llms-close').onclick = function () { overlay.style.display = 'none'; };
        overlay.style.display = 'flex';
        fetch('/api/llms/list').then(function (r) { return r.ok ? r.json() : []; }).catch(function () { return []; })
            .then(function (llms) {
                var listEl = byId('dashboard-llms-list');
                if (listEl) {
                    listEl.dataset.loaded = '1';
                    listEl.innerHTML = (Array.isArray(llms) ? llms : []).length === 0
                        ? '<p style="color:#666;">No LLMs found. Add ai_models to agent configs or LLMS documents in Feedback &amp; Workflow.</p>'
                        : '<ul style="list-style:none;padding:0;margin:0;max-height:360px;overflow-y:auto;">' + llms.map(function (m) { return '<li style="padding:8px 12px;border-bottom:1px solid #eee;">' + m + '</li>'; }).join('') + '</ul>';
                }
            });
    }
    var DEPENDENCY_EMOJI = { installed: '\u2705', parts_missing: '\uD83D\uDFE1', not_installed: '\u274C' };
    function openDependenciesOverlay() {
        var overlay = byId('dashboard-dependencies-overlay');
        if (overlay) {
            overlay.style.display = 'flex';
            var listEl = byId('dashboard-dependencies-list');
            if (listEl && !listEl.dataset.loaded) {
                listEl.dataset.loaded = '1';
                fetch('/api/dependencies/status').then(function (r) { return r.ok ? r.json() : { items: [] }; }).catch(function () { return { items: [] }; })
                    .then(function (data) {
                        listEl.innerHTML = _renderDependenciesList(data.items || []);
                    });
            }
            return;
        }
        overlay = document.createElement('div');
        overlay.id = 'dashboard-dependencies-overlay';
        overlay.className = 'dashboard-modal-overlay';
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:6000;display:flex;align-items:center;justify-content:center;';
        overlay.innerHTML = '<div style="background:#fff;padding:24px;border-radius:12px;max-width:520px;width:90%;max-height:calc(80vh / var(--ui-zoom,1));overflow:hidden;display:flex;flex-direction:column;box-shadow:0 8px 32px rgba(0,0,0,0.2);">' +
            '<h3 style="margin:0 0 16px 0;">Dependencies</h3>' +
            '<p style="color:#666;font-size:0.9rem;margin:0 0 12px 0;">All dependencies needed throughout the app. Same checkmark system as Security Controls.</p>' +
            '<div id="dashboard-dependencies-list" style="flex:1;overflow-y:auto;"><p style="color:#666;">Loading…</p></div>' +
            '<button type="button" class="btn dashboard-btn" id="dashboard-dependencies-close" style="margin-top:16px;">Close</button></div>';
        overlay.onclick = function (e) { if (e.target === overlay) overlay.style.display = 'none'; };
        document.body.appendChild(overlay);
        byId('dashboard-dependencies-close').onclick = function () { overlay.style.display = 'none'; };
        overlay.style.display = 'flex';
        fetch('/api/dependencies/status').then(function (r) { return r.ok ? r.json() : { items: [] }; }).catch(function () { return { items: [] }; })
            .then(function (data) {
                var listEl = byId('dashboard-dependencies-list');
                if (listEl) {
                    listEl.dataset.loaded = '1';
                    listEl.innerHTML = _renderDependenciesList(data.items || []);
                }
            });
    }
    function _renderDependenciesList(items) {
        if (!items.length) return '<p style="color:#666;">No dependency data available.</p>';
        var labels = { installed: 'Installed', parts_missing: 'Parts missing', not_installed: 'Not installed' };
        return '<ul style="list-style:none;padding:0;margin:0;max-height:360px;overflow-y:auto;">' + items.map(function (d) {
            var emoji = DEPENDENCY_EMOJI[d.status] || '\u274C';
            var label = labels[d.status] || d.status;
            var opt = d.optional ? ' <span style="color:#888;font-size:0.85em;">(optional)</span>' : '';
            var note = d.note ? ' <span style="color:#666;font-size:0.85em;" title="' + (d.note || '').replace(/"/g, '&quot;') + '">— ' + (d.note.length > 40 ? d.note.slice(0, 40) + '…' : d.note) + '</span>' : '';
            return '<li style="padding:8px 12px;border-bottom:1px solid #eee;display:flex;align-items:center;gap:8px;">' +
                '<span style="font-size:1.2em;" title="' + label + '">' + emoji + '</span>' +
                '<span><strong>' + (d.name || d.id) + '</strong>' + opt + note + '</span></li>';
        }).join('') + '</ul>';
    }
    var STATUS_EMOJI = { implemented: '\u2705', partial: '\uD83D\uDFE1', not_implemented: '\u274C' };
    function fetchAndApplySecurityControlStatus() {
        fetch('/api/admin/security-controls', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : { items: [] }; }).catch(function () { return { items: [] }; })
            .then(function (data) {
                var items = data.items || [];
                var map = {};
                items.forEach(function (c) { map[c.id] = c.status || 'not_implemented'; });
                applySecurityControlBadges(map);
            });
    }
    function applySecurityControlBadges(controlMap) {
        var configs = [
            { panelId: 'security-diagram-user', stack: 'user', maxStep: 10 },
            { panelId: 'security-diagram-password', stack: 'auth', maxStep: 8 },
            { panelId: 'security-diagram-web-stack', stack: 'web', maxStep: 13, useDataStep: true },
            { panelId: 'security-diagram-schedules', stack: 'schedule', maxStep: 8 },
            { panelId: 'security-diagram-ai', stack: 'agents', maxStep: 5 }
        ];
        configs.forEach(function (cfg) {
            var panel = byId(cfg.panelId);
            if (!panel) return;
            var boxes = panel.querySelectorAll('.security-diagram-stack-item .diagram-box, .security-diagram-flow .diagram-box');
            boxes.forEach(function (box, idx) {
                var step = cfg.useDataStep ? (parseInt(box.getAttribute('data-step'), 10) || idx + 1) : (idx + 1);
                if (step < 1 || step > cfg.maxStep) return;
                var controlId = cfg.stack + '-' + step;
                var status = controlMap[controlId] || 'not_implemented';
                var emoji = STATUS_EMOJI[status] || '\u274C';
                var badge = box.querySelector('.security-control-badge');
                if (badge) badge.textContent = emoji; else {
                    badge = document.createElement('span');
                    badge.className = 'security-control-badge';
                    badge.style.cssText = 'margin-left:6px;font-size:1em;';
                    badge.textContent = emoji;
                    badge.title = status.replace('_', ' ');
                    box.appendChild(badge);
                }
            });
        });
    }

    function openSecurityDiagramsModal() {
        var modal = byId('security-diagrams-modal');
        if (modal) {
            exitSecurityDiagramsFullscreen();
            modal.classList.add('security-diagrams-open');
            modal.style.display = 'flex';
            applyDiagramLavenderStyles();
            fetchAndApplySecurityControlStatus();
            document.body.style.overflow = 'hidden';
            if (securityDiagramsEscHandler) {
                document.removeEventListener('keydown', securityDiagramsEscHandler, true);
            }
            securityDiagramsEscHandler = function (e) {
                if (e.key === 'Escape' || e.keyCode === 27) {
                    e.preventDefault();
                    e.stopPropagation();
                    closeSecurityDiagramsModal();
                }
            };
            document.addEventListener('keydown', securityDiagramsEscHandler, true);
        }
    }
    function closeSecurityDiagramsModal() {
        var modal = byId('security-diagrams-modal');
        if (modal) {
            if (typeof stopWorkflowActiveAgentPolling === 'function') stopWorkflowActiveAgentPolling();
            stopClipfarmMetricCircles();
            exitSecurityDiagramsFullscreen();
            closeDiagramBoxInfo();
            modal.classList.remove('security-diagrams-open');
            modal.style.display = 'none';
            document.body.style.overflow = '';
            if (securityDiagramsEscHandler) {
                document.removeEventListener('keydown', securityDiagramsEscHandler, true);
                securityDiagramsEscHandler = null;
            }
        }
    }
    var securityDiagramsF11Handler = null;
    var PYRAMID_BAND_INFO = [
        { title: 'Central IdP', desc: 'Single identity provider for all access. One place to manage identities and sign-in.' },
        { title: 'Phishing-resistant MFA', desc: 'Multi-factor authentication that resists phishing (e.g. FIDO2/WebAuthn, not SMS).' },
        { title: 'OIDC Authorization Code + PKCE', desc: 'Secure OAuth2/OIDC flow with PKCE to protect against code interception.' },
        { title: 'No tokens in localStorage', desc: 'Avoid storing tokens in browser storage; use httpOnly cookies or memory.' },
        { title: 'Privileged protections', desc: 'Extra safeguards for privileged actions (e.g. re-auth, approval).' },
        { title: 'Short-lived access tokens + refresh rotation', desc: 'Limited lifetime access tokens and rotating refresh tokens to limit exposure.' },
        { title: 'Step-up auth', desc: 'Re-authenticate for sensitive operations (e.g. change password, delete data).' },
        { title: 'Conditional access / device trust', desc: 'Policies and device trust to grant or restrict access based on context.' }
    ];
    var WEB_SECURITY_STEP_INFO = [
        { title: 'Reverse proxy + TLS + headers', html: '<p>A reverse proxy is deployed in front of all application services and acts as the primary security enforcement point.</p><p><strong>Responsibilities</strong></p><ul><li>TLS termination (HTTPS enforced)</li><li>Request routing: <code>/</code> → Flask UI (presentation layer), <code>/api/</code> → FastAPI control plane</li><li>Global rate limiting</li><li>Centralized security headers</li></ul><p><strong>Mandatory Security Headers</strong></p><ul><li>Content-Security-Policy (strict, default-deny)</li><li>X-Frame-Options: DENY</li><li>X-Content-Type-Options: nosniff</li><li>Referrer-Policy: no-referrer (or strict-origin-when-cross-origin)</li><li>Permissions-Policy (all unused features disabled)</li><li>Strict-Transport-Security (enabled only when HTTPS is permanent)</li></ul>' },
        { title: 'Cookie/session settings', html: '<p>The Flask UI uses server-side sessions only; it does not manage authentication.</p><p><strong>Session Configuration</strong></p><ul><li>HttpOnly cookies</li><li>Secure cookies (HTTPS only)</li><li>SameSite=Lax (or Strict where compatible)</li><li>Session ID regeneration on login</li><li>Short idle timeout (15–30 minutes for privileged users)</li></ul><p><strong>Constraints</strong></p><ul><li>No access or refresh tokens stored in localStorage</li><li>Tokens, if present, are stored server-side only</li></ul>' },
        { title: 'CSRF protection', html: '<p>Because the browser communicates with the UI via cookies, CSRF protection is enforced.</p><p><strong>Model</strong></p><ul><li>Browser → Flask UI (cookies)</li><li>Flask → FastAPI (Bearer token, server-to-server)</li><li>Browser never mutates FastAPI directly</li></ul><p><strong>Controls</strong></p><ul><li>CSRF tokens required on all state-changing UI routes</li><li>FastAPI explicitly rejects cookie-based authentication</li><li>Any direct browser → FastAPI mutation requires independent CSRF controls (disabled by default)</li></ul>' },
        { title: 'CORS locked down', html: '<p>Direct browser access to the control plane is not part of the design.</p><p><strong>Policy</strong></p><ul><li>CORS disabled on FastAPI by default</li><li>If enabled: exact origin allowlist (no wildcards), <code>allow_credentials = false</code>, minimal allowed methods and headers</li></ul>' },
        { title: 'Request validation + size limits', html: '<p>All incoming requests are treated as untrusted.</p><p><strong>Controls</strong></p><ul><li>Strict Pydantic schemas on all endpoints</li><li>Unknown fields rejected (<code>extra = forbid</code>)</li><li>Temporal validation (start &lt; end, allowed windows)</li><li>UUID validation for identifiers</li><li>Request body size limits enforced at proxy</li><li>Request timeouts configured</li></ul>' },
        { title: 'CSP + remove inline JS', html: '<p>A strict CSP is enforced to prevent script injection and data exfiltration.</p><p><strong>Baseline CSP</strong></p><ul><li><code>default-src \'self\'</code></li><li><code>script-src \'self\'</code></li><li><code>style-src \'self\'</code> (nonces if inline styles are unavoidable)</li><li><code>img-src \'self\' data:</code></li><li><code>connect-src \'self\'</code></li><li><code>frame-ancestors \'none\'</code></li><li><code>base-uri \'self\'</code></li><li><code>object-src \'none\'</code></li></ul><p><strong>Guidelines</strong></p><ul><li>Inline scripts eliminated where possible</li><li>CSP nonces used when required</li><li><code>\'unsafe-inline\'</code> avoided</li></ul>' },
        { title: 'XSS hardening in templates', html: '<p>UI rendering is hardened against injection.</p><p><strong>Controls</strong></p><ul><li>Auto-escaping enabled</li><li>No use of <code>|safe</code> without explicit sanitization</li><li>Rich text sanitized via allowlist-based sanitizer if required</li><li>JSON embedded via <code>|tojson</code> only</li></ul>' },
        { title: 'Rate limiting', html: '<p>Abuse controls are enforced at the proxy layer.</p><p><strong>Protected Endpoints</strong></p><ul><li>Login and auth callbacks</li><li>Schedule submissions</li><li>Approvals</li><li>High-cost query endpoints</li></ul><p><strong>Controls</strong></p><ul><li>Request rate limits</li><li>Progressive backoff on repeated failures</li></ul>' },
        { title: 'Error/info leakage hardening', html: '<p>Operational details are not exposed to users.</p><p><strong>Controls</strong></p><ul><li>Debug mode disabled in production</li><li>Generic user-facing error messages</li><li>No stack traces, paths, or environment data leaked</li><li>Centralized logging with secret scrubbing</li></ul>' },
        { title: 'Upload security', html: '<p>File uploads are disabled by default.</p><p><strong>If enabled</strong></p><ul><li>Storage outside web root</li><li>Randomized filenames</li><li>MIME type + magic byte validation</li><li>Strict size limits</li><li>No executable extensions</li><li>Optional malware scanning</li></ul>' },
        { title: 'Security logging + alerting', html: '<p>Security-relevant events are logged and auditable.</p><p><strong>Logged Events</strong></p><ul><li>Authentication success/failure</li><li>Token validation errors</li><li>Authorization denials</li><li>Schedule submissions and diffs</li><li>Approval actions</li><li>Replay or duplicate request attempts</li><li>Rate-limit violations</li></ul>' },
        { title: 'Dependency pinning + scanning', html: '<p>The software supply chain is controlled and auditable.</p><p><strong>Controls</strong></p><ul><li>Dependency pinning with hashes</li><li>SBOM generation</li><li>Automated vulnerability scanning (CI)</li><li>No ad-hoc dependency installation in production</li><li>Frontend libraries version-locked and verified</li></ul>' },
        { title: 'Fail-closed control-plane-down behavior', html: '<p>When the control plane is unavailable, the system fails closed: access is denied rather than granted by default.</p><p><strong>Behavior</strong></p><ul><li>Authentication and authorization are enforced exclusively by the control plane (FastAPI)</li><li>If the control plane is down or unreachable, requests are not assumed authorized</li><li>Flask contains no authoritative permission logic; it defers to the control plane</li><li>Sensitive endpoints optionally require an internal proxy header (e.g. X-Internal-Gateway)</li><li>No silent fallback to permissive access when the control plane is unavailable</li></ul>' }
    ];
    var USERS_STEP_INFO = [
        { title: 'Identity Management', html: '<p>User identity is centralized and externally managed.</p><p><strong>Model</strong></p><ul><li>All user identities are managed by a dedicated Identity Provider (IdP).</li><li>The application does not store, manage, or validate passwords.</li><li>The application treats identity as claims contained in signed tokens.</li></ul><p><strong>Identity Attributes</strong></p><ul><li>Subject identifier (sub)</li><li>Assigned roles/groups</li><li>Issuer and audience</li><li>Authentication assurance level (MFA/passkey status)</li></ul>' },
        { title: 'Authentication', html: '<p>Authentication is delegated entirely to the IdP using modern, phishing-resistant standards.</p><p><strong>Protocol</strong></p><ul><li>OpenID Connect (OIDC)</li><li>Authorization Code Flow with PKCE</li></ul><p><strong>Controls</strong></p><ul><li>No implicit or password grant flows</li><li>No credential handling by application services</li><li>TLS enforced for all authentication exchanges</li></ul><p><strong>Authentication Strength</strong></p><ul><li>Passkeys (WebAuthn/FIDO2) or hardware security keys required for privileged users</li><li>MFA enforced at IdP level, not in application code</li></ul>' },
        { title: 'Token Model', html: '<p>The application uses short-lived, signed tokens for access control.</p><p><strong>Token Types</strong></p><ul><li>Access token (short-lived)</li><li>Refresh token (rotating, optional, server-side only)</li></ul><p><strong>Controls</strong></p><ul><li>Access tokens validated on every request</li><li>Token signature, issuer, audience, and expiration verified</li><li>Tokens never stored in browser localStorage</li><li>Refresh tokens stored server-side only</li></ul>' },
        { title: 'UI Session Handling', html: '<p>Browser sessions are used solely to maintain UI state and token references.</p><p><strong>Controls</strong></p><ul><li>Server-side sessions only</li><li>Secure, HttpOnly cookies</li><li>Short idle timeout</li><li>Session ID regeneration on authentication</li><li>Session invalidation on logout</li></ul>' },
        { title: 'Authorization Model', html: '<p>Authorization is enforced centrally by the control plane.</p><p><strong>Approach</strong></p><ul><li>Role-Based Access Control (RBAC) for baseline permissions</li><li>Attribute-Based Access Control (ABAC) for contextual enforcement</li></ul><p><strong>Roles</strong></p><ul><li>Admin</li><li>Operator</li><li>Spectator</li></ul><p><strong>Principles</strong></p><ul><li>Deny-by-default</li><li>Least privilege</li><li>Explicit allow rules only</li></ul>' },
        { title: 'Privileged Access Controls', html: '<p>High-impact actions are protected by additional safeguards.</p><p><strong>Controls</strong></p><ul><li>Separation of duties (Admin ≠ Operator)</li><li>Two-person approval for high-risk actions</li><li>No self-approval of submitted requests</li><li>Optional step-up authentication for sensitive operations</li></ul>' },
        { title: 'Agent vs Human Identity Separation', html: '<p>Human users and autonomous agents are treated as distinct principals.</p><p><strong>Rules</strong></p><ul><li>Agents may submit requests but never self-approve</li><li>Agent identities have strictly scoped capabilities</li><li>Agent actions are fully attributable and auditable</li><li>Agent credentials are isolated from human credentials</li></ul>' },
        { title: 'Authorization Enforcement', html: '<p>Authorization is enforced consistently and cannot be bypassed by the UI.</p><p><strong>Controls</strong></p><ul><li>All mutation endpoints enforce authorization server-side</li><li>UI performs no authoritative permission checks</li><li>Authorization failures return explicit 403 responses</li><li>Policy evaluation occurs before any state change</li></ul>' },
        { title: 'Auditability and Traceability', html: '<p>All identity-related actions are traceable.</p><p><strong>Logged Events</strong></p><ul><li>Authentication success and failure</li><li>Token validation failures</li><li>Authorization denials</li><li>Role or capability changes</li><li>Approval and rejection actions</li></ul><p><strong>Properties</strong></p><ul><li>Append-only audit records</li><li>Actor identity always recorded</li><li>Tamper-evident storage</li></ul>' },
        { title: 'Failure Behavior', html: '<p>Security failures fail closed.</p><p><strong>Rules</strong></p><ul><li>Invalid or expired tokens → access denied</li><li>Authorization uncertainty → deny</li><li>Identity provider unavailable → no new sessions</li><li>No fallback to local or cached credentials for privileged actions</li></ul>' }
    ];
    var SCHEDULES_STEP_INFO = [
        { title: 'View Active Schedule', html: '<p>Users view the currently active GPU/CPU schedule. The active schedule is the single source of truth; it is immutable and cannot be edited directly.</p><p><strong>Access</strong></p><ul><li>Requires authentication</li><li>Read-only for Operators and Spectators</li><li>Timeline and Pending Schedule Requests share the same session</li></ul>' },
        { title: 'Create or Modify Schedule (Request Phase)', html: '<p>Schedule changes are proposed as requests rather than direct edits. Users create or modify schedules in a request phase; changes are not applied until approved.</p><p><strong>Controls</strong></p><ul><li>No direct schedule writes</li><li>All changes go through the request workflow</li><li>Request includes proposed diff</li></ul>' },
        { title: 'Policy Evaluation', html: '<p>Each schedule request is evaluated against policy before entering the pending state. Policy checks ensure temporal constraints, resource limits, and other rules are satisfied.</p><p><strong>Checks</strong></p><ul><li>Start &lt; end, allowed windows</li><li>Resource availability</li><li>Concurrency limits</li></ul>' },
        { title: 'Pending State', html: '<p>Approved-by-policy requests enter a pending state. They remain there until they are approved by an authorized user (two-person rule for high-risk actions).</p><p><strong>Properties</strong></p><ul><li>Explicit Draft/Pending status in UI</li><li>No execution from drafts</li><li>Clear separation from active schedule</li></ul>' },
        { title: 'Approval Flow', html: '<p>Pending requests require approval before activation. Two-person approval prevents unilateral high-risk changes. No self-approval of submitted requests.</p><p><strong>Rules</strong></p><ul><li>Distinct approver identity</li><li>Separation of duties (Admin ≠ Operator)</li><li>Optional step-up authentication</li></ul>' },
        { title: 'Activation', html: '<p>Approved requests are activated. The new schedule becomes the active schedule atomically. Activation is the only path to schedule changes.</p><p><strong>Properties</strong></p><ul><li>Atomic update</li><li>Single source of truth (Postgres)</li><li>No dual source of truth</li></ul>' },
        { title: 'Audit', html: '<p>All schedule-related actions are audited: submissions, approvals, rejections, and activations. Audit records are append-only and tamper-evident.</p><p><strong>Logged Events</strong></p><ul><li>Schedule submissions and diffs</li><li>Approval and rejection actions</li><li>Activation events</li></ul>' },
        { title: 'Security Properties', html: '<p>Schedule security is enforced end-to-end: authentication, authorization, policy evaluation, approval workflow, and audit. Execution only from approved JobSpecs with signature validation.</p><p><strong>Controls</strong></p><ul><li>Unique request IDs, idempotency keys</li><li>Fail-closed when control plane is down</li><li>Agents cannot approve; strict capability scoping</li></ul>' }
    ];
    var AGENTS_STEP_INFO = [
        { title: 'User selects role (Admin / Operators / Spectators)', html: '<p>Users choose their role at login or through identity provider assignment. Role determines baseline permissions.</p><p><strong>Roles</strong></p><ul><li>Admin: full system access, approvals</li><li>Operator: schedule and agent operations</li><li>Spectator: read-only access</li></ul>' },
        { title: 'Login with ID + Password', html: '<p>Authentication is delegated to the identity provider. Users log in with ID and password (or phishing-resistant MFA) via OIDC.</p><p><strong>Controls</strong></p><ul><li>OIDC Authorization Code + PKCE</li><li>No application-managed passwords</li><li>TLS for all auth exchanges</li></ul>' },
        { title: 'Server validates role + credentials', html: '<p>The control plane validates credentials and role claims from the IdP. Token signature, issuer, audience, and expiration are verified on every request.</p><p><strong>Validation</strong></p><ul><li>RBAC enforced server-side</li><li>Roles derived from IdP claims only</li><li>Deny-by-default</li></ul>' },
        { title: 'Session stores user + role', html: '<p>Server-side sessions maintain UI state and token references. Secure, HttpOnly cookies; short idle timeout; session ID regeneration on login.</p><p><strong>Storage</strong></p><ul><li>No tokens in localStorage</li><li>Tokens server-side only</li><li>Session invalidation on logout</li></ul>' },
        { title: 'Dashboard / Agents restricted by role', html: '<p>Dashboard and agent features are gated by role. Operators can run tasks; Spectators can view only. Permissions extend per role for agents.</p><p><strong>Enforcement</strong></p><ul><li>Authorization enforced exclusively in FastAPI</li><li>UI performs no authoritative permission checks</li><li>403 on unauthorized actions</li></ul>' }
    ];
    var THREAT_MODEL_INFO = [
        { id: 1, title: 'Credential theft', html: '<p><strong>Impact</strong></p><ul><li>Unauthorized access to dashboard</li><li>Privilege abuse if Admin/Operator credentials are stolen</li></ul><p><strong>Mitigations</strong></p><ul><li>Central IdP (OIDC)</li><li>Phishing-resistant MFA (Passkeys / FIDO2)</li><li>No application-managed passwords</li><li>Short-lived access tokens</li></ul>' },
        { id: 2, title: 'Phishing-based account takeover', html: '<p><strong>Impact</strong></p><ul><li>Full user impersonation</li><li>Persistent unauthorized access</li></ul><p><strong>Mitigations</strong></p><ul><li>WebAuthn / FIDO2 authentication</li><li>OIDC redirect-based login</li><li>No credential entry handled by application</li></ul>' },
        { id: 3, title: 'Session hijacking', html: '<p><strong>Impact</strong></p><ul><li>Attacker reuses valid session</li><li>Unauthorized schedule or approval actions</li></ul><p><strong>Mitigations</strong></p><ul><li>HttpOnly, Secure cookies</li><li>No tokens in localStorage</li><li>TLS everywhere</li><li>Session ID regeneration on login</li></ul>' },
        { id: 4, title: 'Token replay attacks', html: '<p><strong>Impact</strong></p><ul><li>Abuse of APIs within token lifetime</li></ul><p><strong>Mitigations</strong></p><ul><li>Short-lived access tokens</li><li>Token expiration enforcement</li><li>Refresh token rotation (server-side)</li><li>Optional token audience binding</li></ul>' },
        { id: 5, title: 'Role escalation', html: '<p><strong>Impact</strong></p><ul><li>Operator acts as Admin</li><li>Unauthorized approvals or system changes</li></ul><p><strong>Mitigations</strong></p><ul><li>RBAC enforced server-side</li><li>Roles derived from IdP claims only</li><li>Deny-by-default authorization</li></ul>' },
        { id: 6, title: 'Horizontal privilege abuse', html: '<p><strong>Impact</strong></p><ul><li>Access to other users\', agents\', or projects\' resources</li></ul><p><strong>Mitigations</strong></p><ul><li>ABAC checks (agent, project, scope)</li><li>Resource-level authorization</li><li>Ownership validation</li></ul>' },
        { id: 7, title: 'Self-approval abuse', html: '<p><strong>Impact</strong></p><ul><li>Governance bypass</li><li>High-risk actions approved unilaterally</li></ul><p><strong>Mitigations</strong></p><ul><li>Two-person approval rule</li><li>Explicit self-approval prevention</li><li>Distinct approver identity enforcement</li></ul>' },
        { id: 8, title: 'Authorization bypass via UI manipulation', html: '<p><strong>Impact</strong></p><ul><li>Unauthorized mutations through tampered UI</li></ul><p><strong>Mitigations</strong></p><ul><li>Authorization enforced exclusively in FastAPI</li><li>UI treated as untrusted</li><li>Backend denies unauthorized actions (403)</li></ul>' },
        { id: 9, title: 'Unauthorized schedule modification', html: '<p><strong>Impact</strong></p><ul><li>Unsafe or malicious workloads scheduled</li></ul><p><strong>Mitigations</strong></p><ul><li>Schedule Requests + approval workflow</li><li>Immutable active schedules</li><li>No direct schedule writes</li></ul>' },
        { id: 10, title: 'Dual source of truth', html: '<p><strong>Impact</strong></p><ul><li>Conflicting schedules</li><li>Execution inconsistencies</li></ul><p><strong>Mitigations</strong></p><ul><li>Single source of truth (Postgres)</li><li>Legacy UI read-only or proxy-only</li><li>Fail-closed behavior when control plane is down</li></ul>' },
        { id: 11, title: 'Offline draft confusion', html: '<p><strong>Impact</strong></p><ul><li>Users believe drafts are active schedules</li></ul><p><strong>Mitigations</strong></p><ul><li>Explicit "Draft / Pending" status</li><li>Clear UI separation</li><li>No execution from drafts</li></ul>' },
        { id: 12, title: 'Replay of old schedule requests', html: '<p><strong>Impact</strong></p><ul><li>Duplicate or unintended execution</li></ul><p><strong>Mitigations</strong></p><ul><li>Unique request IDs</li><li>Idempotency keys</li><li>Expiration timestamps</li><li>Audit validation</li></ul>' },
        { id: 13, title: 'Rogue agent behavior', html: '<p><strong>Impact</strong></p><ul><li>Unauthorized scheduling or resource abuse</li></ul><p><strong>Mitigations</strong></p><ul><li>Agents treated as separate principals</li><li>Strict capability scoping</li><li>Agents cannot approve</li><li>Full agent action auditing</li></ul>' },
        { id: 14, title: 'Prompt injection', html: '<p><strong>Impact</strong></p><ul><li>Agents submit unsafe or unauthorized requests</li></ul><p><strong>Mitigations</strong></p><ul><li>Structured request schemas only</li><li>No free-text execution</li><li>Policy enforcement on all agent requests</li></ul>' },
        { id: 15, title: 'Agent identity impersonation', html: '<p><strong>Impact</strong></p><ul><li>Malicious task submissions</li></ul><p><strong>Mitigations</strong></p><ul><li>Dedicated agent credentials</li><li>Distinct agent identity namespace</li><li>Credential isolation from human users</li></ul>' },
        { id: 16, title: 'GPU / CPU resource starvation', html: '<p><strong>Impact</strong></p><ul><li>Denial of service</li><li>Unfair compute allocation</li></ul><p><strong>Mitigations</strong></p><ul><li>GPU/CPU leases</li><li>Per-agent budgets</li><li>Fair scheduling (WFQ)</li><li>Concurrency limits</li></ul>' },
        { id: 17, title: 'Unauthorized execution', html: '<p><strong>Impact</strong></p><ul><li>Unsafe workloads executed</li></ul><p><strong>Mitigations</strong></p><ul><li>Execution only from approved JobSpecs</li><li>Signed JobSpecs</li><li>Executor signature validation</li></ul>' },
        { id: 18, title: 'Arbitrary code execution', html: '<p><strong>Impact</strong></p><ul><li>Host compromise</li><li>Data exfiltration</li></ul><p><strong>Mitigations</strong></p><ul><li>Container isolation</li><li>Non-root execution</li><li>Read-only filesystems</li><li>Network egress deny-by-default</li></ul>' },
        { id: 19, title: 'Man-in-the-middle (MITM) attacks', html: '<p><strong>Impact</strong></p><ul><li>Credential or token interception</li><li>Data manipulation</li></ul><p><strong>Mitigations</strong></p><ul><li>TLS everywhere</li><li>HSTS</li><li>Secure reverse proxy</li></ul>' },
        { id: 20, title: 'Cross-site scripting (XSS)', html: '<p><strong>Impact</strong></p><ul><li>Session hijacking</li><li>Data exfiltration</li></ul><p><strong>Mitigations</strong></p><ul><li>Strict Content Security Policy</li><li>Template auto-escaping</li><li>No unsafe inline scripts</li></ul>' },
        { id: 21, title: 'Cross-site request forgery (CSRF)', html: '<p><strong>Impact</strong></p><ul><li>Unauthorized state changes</li></ul><p><strong>Mitigations</strong></p><ul><li>CSRF tokens on UI</li><li>Browser never mutates control plane directly</li></ul>' },
        { id: 22, title: 'API abuse or flooding', html: '<p><strong>Impact</strong></p><ul><li>Service degradation</li><li>Resource exhaustion</li></ul><p><strong>Mitigations</strong></p><ul><li>Rate limiting at proxy</li><li>Request size/time limits</li><li>Abuse detection</li></ul>' },
        { id: 23, title: 'Audit log tampering', html: '<p><strong>Impact</strong></p><ul><li>Loss of accountability</li><li>Undetected malicious actions</li></ul><p><strong>Mitigations</strong></p><ul><li>Append-only audit logs</li><li>Hash chaining</li><li>Restricted write access</li></ul>' },
        { id: 24, title: 'Sensitive data leakage', html: '<p><strong>Impact</strong></p><ul><li>Exposure of secrets or internal state</li></ul><p><strong>Mitigations</strong></p><ul><li>Log scrubbing</li><li>Generic error messages</li><li>No secrets in logs or responses</li></ul>' },
        { id: 25, title: 'Malicious dependency introduction', html: '<p><strong>Impact</strong></p><ul><li>Backdoors or remote code execution</li></ul><p><strong>Mitigations</strong></p><ul><li>Dependency pinning with hashes</li><li>SBOM generation</li><li>Automated vulnerability scanning</li></ul>' },
        { id: 26, title: 'Unauthorized code changes', html: '<p><strong>Impact</strong></p><ul><li>Backdoors</li><li>Logic compromise</li></ul><p><strong>Mitigations</strong></p><ul><li>Version control</li><li>Code reviews</li><li>Signed build artifacts</li><li>Restricted deployment access</li></ul>' },
        { id: 27, title: 'Control plane unavailability', html: '<p><strong>Impact</strong></p><ul><li>No approvals or governance actions</li></ul><p><strong>Mitigations</strong></p><ul><li>Fail-closed behavior</li><li>Read-only UI</li><li>Explicit draft-only mode</li></ul>' },
        { id: 28, title: 'Insider abuse', html: '<p><strong>Impact</strong></p><ul><li>High-impact misuse by trusted users</li></ul><p><strong>Mitigations</strong></p><ul><li>Least privilege</li><li>Two-person rule</li><li>Comprehensive audit logging</li><li>Behavioral monitoring</li></ul>' }
    ];
    function positionBandInfoDialogAtCursor(dialogEl, event) {
        if (!dialogEl || !event) return;
        var x = event.clientX;
        var y = event.clientY + 20;
        dialogEl.style.position = 'fixed';
        dialogEl.style.left = x + 'px';
        dialogEl.style.top = y + 'px';
        dialogEl.style.right = 'auto';
        dialogEl.style.bottom = 'auto';
        dialogEl.style.margin = '0';
        requestAnimationFrame(function () {
            var w = dialogEl.offsetWidth;
            var h = dialogEl.offsetHeight;
            var maxW = window.innerWidth - 20;
            var maxH = window.innerHeight - 20;
            if (x + w > maxW) x = maxW - w;
            if (x < 10) x = 10;
            if (y + h > maxH) y = Math.max(10, maxH - h);
            if (y < 10) y = 10;
            dialogEl.style.left = x + 'px';
            dialogEl.style.top = y + 'px';
        });
    }
    function showBandInfo(level, event) {
        var modal = byId('security-diagram-band-info-modal');
        var titleEl = byId('security-diagram-band-info-title');
        var descEl = byId('security-diagram-band-info-desc');
        if (!modal || !titleEl || !descEl || level < 1 || level > 8) return;
        var info = PYRAMID_BAND_INFO[level - 1];
        titleEl.textContent = info.title;
        descEl.textContent = info.desc;
        var dialogEl = modal ? modal.querySelector('.security-diagram-band-info-dialog') : null;
        if (dialogEl) {
            dialogEl.style.maxWidth = '';
            if (event) positionBandInfoDialogAtCursor(dialogEl, event);
        }
        modal.style.display = 'flex';
    }
    function showWebSecurityStepInfo(stepIndex, event) {
        var modal = byId('security-diagram-band-info-modal');
        var titleEl = byId('security-diagram-band-info-title');
        var descEl = byId('security-diagram-band-info-desc');
        if (!modal || !titleEl || !descEl || stepIndex < 1 || stepIndex > 13) return;
        var info = WEB_SECURITY_STEP_INFO[stepIndex - 1];
        titleEl.textContent = info.title;
        descEl.innerHTML = info.html;
        var dialogEl = modal ? modal.querySelector('.security-diagram-band-info-dialog') : null;
        if (dialogEl) {
            dialogEl.style.maxWidth = '520px';
            if (event) positionBandInfoDialogAtCursor(dialogEl, event);
        }
        modal.style.display = 'flex';
    }
    function showUsersStepInfo(stepIndex, event) {
        var modal = byId('security-diagram-band-info-modal');
        var titleEl = byId('security-diagram-band-info-title');
        var descEl = byId('security-diagram-band-info-desc');
        if (!modal || !titleEl || !descEl || stepIndex < 1 || stepIndex > 10) return;
        var info = USERS_STEP_INFO[stepIndex - 1];
        titleEl.textContent = info.title;
        descEl.innerHTML = info.html;
        var dialogEl = modal ? modal.querySelector('.security-diagram-band-info-dialog') : null;
        if (dialogEl) {
            dialogEl.style.maxWidth = '520px';
            if (event) positionBandInfoDialogAtCursor(dialogEl, event);
        }
        modal.style.display = 'flex';
    }
    function showSchedulesStepInfo(stepIndex, event) {
        var modal = byId('security-diagram-band-info-modal');
        var titleEl = byId('security-diagram-band-info-title');
        var descEl = byId('security-diagram-band-info-desc');
        if (!modal || !titleEl || !descEl || stepIndex < 1 || stepIndex > 8) return;
        var info = SCHEDULES_STEP_INFO[stepIndex - 1];
        titleEl.textContent = info.title;
        descEl.innerHTML = info.html;
        var dialogEl = modal ? modal.querySelector('.security-diagram-band-info-dialog') : null;
        if (dialogEl) {
            dialogEl.style.maxWidth = '520px';
            if (event) positionBandInfoDialogAtCursor(dialogEl, event);
        }
        modal.style.display = 'flex';
    }
    function showAgentsStepInfo(stepIndex, event) {
        var modal = byId('security-diagram-band-info-modal');
        var titleEl = byId('security-diagram-band-info-title');
        var descEl = byId('security-diagram-band-info-desc');
        if (!modal || !titleEl || !descEl || stepIndex < 1 || stepIndex > 5) return;
        var info = AGENTS_STEP_INFO[stepIndex - 1];
        titleEl.textContent = info.title;
        descEl.innerHTML = info.html;
        var dialogEl = modal ? modal.querySelector('.security-diagram-band-info-dialog') : null;
        if (dialogEl) {
            dialogEl.style.maxWidth = '520px';
            if (event) positionBandInfoDialogAtCursor(dialogEl, event);
        }
        modal.style.display = 'flex';
    }
    function showThreatModelInfo(threatId, event) {
        var modal = byId('security-diagram-band-info-modal');
        var titleEl = byId('security-diagram-band-info-title');
        var descEl = byId('security-diagram-band-info-desc');
        if (!modal || !titleEl || !descEl) return;
        var info = THREAT_MODEL_INFO.filter(function (t) { return t.id === threatId; })[0];
        if (!info) return;
        titleEl.textContent = info.title;
        descEl.innerHTML = info.html;
        var dialogEl = modal ? modal.querySelector('.security-diagram-band-info-dialog') : null;
        if (dialogEl) {
            dialogEl.style.maxWidth = '520px';
            if (event) positionBandInfoDialogAtCursor(dialogEl, event);
        }
        modal.style.display = 'flex';
    }
    function closeBandInfo() {
        var modal = byId('security-diagram-band-info-modal');
        if (modal) {
            modal.style.display = 'none';
            var dialogEl = modal.querySelector('.security-diagram-band-info-dialog');
            if (dialogEl) {
                dialogEl.style.position = '';
                dialogEl.style.left = '';
                dialogEl.style.top = '';
                dialogEl.style.right = '';
                dialogEl.style.bottom = '';
                dialogEl.style.margin = '';
            }
        }
    }
    function closeDiagramBoxInfo() {
        var modal = byId('security-diagram-box-info-modal');
        if (modal) modal.style.display = 'none';
    }
    function showNavigateToDistributionModal(callback) {
        var modal = byId('navigate-to-distribution-modal');
        var yesBtn = byId('navigate-to-distribution-yes');
        var noBtn = byId('navigate-to-distribution-no');
        if (!modal || !callback) return;
        var boxModal = byId('security-diagram-box-info-modal');
        if (boxModal) boxModal.style.display = 'none';
        function closeAndResolve(ok) {
            modal.style.display = 'none';
            callback(ok);
        }
        if (yesBtn) yesBtn.onclick = function () { closeAndResolve(true); };
        if (noBtn) noBtn.onclick = function () { closeAndResolve(false); };
        modal.onclick = function (e) {
            if (e.target === modal) closeAndResolve(false);
        };
        modal.style.display = 'flex';
    }
    /* Web Security uses diagram_boxes_and_arrows SVG – clicks attached in ensureWebSecurityDiagramRendered via attachWebSecuritySvgClicks */
    function attachUsersBoxClicks() {
        var panel = byId('security-diagram-user');
        if (!panel) return;
        var boxes = panel.querySelectorAll('.security-diagram-stack-list .diagram-box, .security-diagram-flow .diagram-box');
        boxes.forEach(function (el, index) {
            var stepIndex = index + 1;
            if (stepIndex >= 1 && stepIndex <= 10) {
                el.style.cursor = 'pointer';
                el.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    showDiagramBoxInfo((el.textContent || '').trim(), 'user', stepIndex, el, 0);
                });
            }
        });
    }
    function attachSchedulesBoxClicks() {
        var panel = byId('security-diagram-schedules');
        if (!panel) return;
        var boxes = panel.querySelectorAll('.security-diagram-stack-list .diagram-box, .security-diagram-flow .diagram-box');
        boxes.forEach(function (el, index) {
            var stepIndex = index + 1;
            if (stepIndex >= 1 && stepIndex <= 8) {
                el.style.cursor = 'pointer';
                el.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    showDiagramBoxInfo((el.textContent || '').trim(), 'schedules', stepIndex, el, 0);
                });
            }
        });
    }
    function attachPasswordBoxClicks() {
        var panel = byId('security-diagram-password');
        if (!panel) return;
        var boxes = panel.querySelectorAll('.security-diagram-stack-list .diagram-box, .security-diagram-flow .diagram-box');
        boxes.forEach(function (el, index) {
            var level = index + 1;
            if (level >= 1 && level <= 8) {
                el.style.cursor = 'pointer';
                el.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    var info = PYRAMID_BAND_INFO[level - 1];
                    showDiagramBoxInfo(info ? info.title : 'Level ' + level, 'password', level, el, 0);
                });
            }
        });
    }
    function attachAgentsBoxClicks() {
        var panel = byId('security-diagram-ai');
        if (!panel) return;
        var boxes = panel.querySelectorAll('.security-diagram-stack-list .diagram-box, .security-diagram-flow .diagram-box');
        boxes.forEach(function (el, index) {
            var stepIndex = index + 1;
            if (stepIndex >= 1 && stepIndex <= 5) {
                el.style.cursor = 'pointer';
                el.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    showDiagramBoxInfo((el.textContent || '').trim(), 'ai', stepIndex, el, 0);
                });
            }
        });
    }
    function attachBoxClicksToViewerClone(containerEl, diagramId) {
        if (!containerEl) return;
        if (diagramId === 'web') {
            attachWebSecuritySvgClicks(containerEl);
            return;
        }
        var boxes = containerEl.querySelectorAll('.security-diagram-stack-list .diagram-box, .security-diagram-flow .diagram-box, .threat-model-column .diagram-box');
        boxes.forEach(function (el, index) {
            var stepIndex = index + 1;
            el.style.cursor = 'pointer';
            el.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                var label = el.textContent || el.innerText || ('Step ' + stepIndex);
                var threatId = diagramId === 'threat_model' ? parseInt(el.getAttribute('data-threat-id'), 10) : 0;
                showDiagramBoxInfo(label.trim(), diagramId, stepIndex, el, threatId);
            });
        });
    }
    function findLabelForSvgElement(target, svg) {
        if (!target || target === svg) return null;
        var tag = (target.tagName || '').toLowerCase();
        if (tag === 'text' || tag === 'tspan') {
            var txt = (target.textContent || '').trim();
            if (txt) {
                var rect = null;
                var rects = svg.querySelectorAll('rect[width][height]');
                var getRectBounds = function (r) {
                    var x = parseFloat(r.getAttribute('x')) || 0, y = parseFloat(r.getAttribute('y')) || 0;
                    var w = parseFloat(r.getAttribute('width')) || 0, h = parseFloat(r.getAttribute('height')) || 0;
                    return { x: x, y: y, w: w, h: h };
                };
                var pointInRect = function (px, py, r) { return px >= r.x && px <= r.x + r.w && py >= r.y && py <= r.y + r.h; };
                var tb = target.getBBox ? target.getBBox() : null;
                if (tb) {
                    var cx = tb.x + tb.width / 2, cy = tb.y + tb.height / 2;
                    for (var i = 0; i < rects.length; i++) {
                        var rb = getRectBounds(rects[i]);
                        if (pointInRect(cx, cy, rb)) { rect = rects[i]; break; }
                    }
                }
                return { label: txt, rect: rect };
            }
        }
        var rects = svg.querySelectorAll('rect[width][height]');
        var texts = svg.querySelectorAll('text');
        var getRectBounds = function (r) {
            var x = parseFloat(r.getAttribute('x')) || 0;
            var y = parseFloat(r.getAttribute('y')) || 0;
            var w = parseFloat(r.getAttribute('width')) || 0;
            var h = parseFloat(r.getAttribute('height')) || 0;
            return { x: x, y: y, w: w, h: h, cx: x + w / 2, cy: y + h / 2 };
        };
        var pointInRect = function (px, py, r) {
            return px >= r.x && px <= r.x + r.w && py >= r.y && py <= r.y + r.h;
        };
        if (tag === 'ellipse' || tag === 'circle') {
            var cx = parseFloat(target.getAttribute('cx')) || 0;
            var cy = parseFloat(target.getAttribute('cy')) || 0;
            var rx = tag === 'ellipse' ? (parseFloat(target.getAttribute('rx')) || 0) : (parseFloat(target.getAttribute('r')) || 0);
            var ry = tag === 'ellipse' ? (parseFloat(target.getAttribute('ry')) || 0) : rx;
            if (rx > 0 && ry > 0) {
                var label = target.getAttribute('data-step') || 'Overseer';
                return { label: label, rect: target };
            }
        }
        if (tag === 'rect' || tag === 'path' || tag === 'line' || tag === 'polygon' || tag === 'polyline' || tag === 'g') {
            var bbox = target.getBBox ? target.getBBox() : null;
            if (!bbox && tag === 'rect') {
                bbox = { x: parseFloat(target.getAttribute('x')) || 0, y: parseFloat(target.getAttribute('y')) || 0, width: parseFloat(target.getAttribute('width')) || 0, height: parseFloat(target.getAttribute('height')) || 0 };
            }
            if (bbox) {
                var cx = bbox.x + bbox.width / 2;
                var cy = bbox.y + bbox.height / 2;
                var rb = (tag === 'rect') ? getRectBounds(target) : null;
                var rectEl = (tag === 'rect') ? target : null;
                if (!rb) {
                    for (var i = 0; i < rects.length; i++) {
                        var candidate = getRectBounds(rects[i]);
                        if (pointInRect(cx, cy, candidate)) {
                            rb = candidate;
                            rectEl = rects[i];
                            break;
                        }
                    }
                }
                if (rb && !rectEl && tag === 'rect') rectEl = target;
                if (rb) {
                    for (var j = 0; j < texts.length; j++) {
                        var tb = texts[j].getBBox ? texts[j].getBBox() : null;
                        if (tb && pointInRect(tb.x + tb.width / 2, tb.y + tb.height / 2, rb)) {
                            return { label: (texts[j].textContent || '').trim(), rect: rectEl };
                        }
                    }
                    var nearest = null;
                    var best = Infinity;
                    for (var k = 0; k < texts.length; k++) {
                        var tbb = texts[k].getBBox ? texts[k].getBBox() : null;
                        if (tbb && (texts[k].textContent || '').trim()) {
                            var dx = (tbb.x + tbb.width / 2) - (rb.x + rb.w / 2);
                            var dy = (tbb.y + tbb.height / 2) - (rb.y + rb.h / 2);
                            var d = dx * dx + dy * dy;
                            if (d < best) { best = d; nearest = texts[k]; }
                        }
                    }
                    if (nearest) return { label: (nearest.textContent || '').trim(), rect: rectEl };
                }
            }
        }
        return null;
    }
    function findLabelAtSvgPoint(svg, clientX, clientY, debugCtx) {
        if (!svg) return null;
        var rects = svg.querySelectorAll('rect[width][height]');
        var texts = svg.querySelectorAll('text');
        var pointInViewportRect = function (vx, vy, br) {
            return vx >= br.left && vx <= br.right && vy >= br.top && vy <= br.bottom;
        };
        /* Use getBoundingClientRect so click and rect are both in viewport coords. Prefer rects with data-flow-id; if none, allow workflow-sized rects (70-220 x 30-90) to support dead-space clicks when assign hasn't run. */
        var containingRects = [];
        var isWorkflowSized = function (w, h) { return w >= 50 && w <= 350 && h >= 20 && h <= 120; };
        for (var i = 0; i < rects.length; i++) {
            var r = rects[i];
            var flowId = r.getAttribute && r.getAttribute('data-flow-id');
            var br = r.getBoundingClientRect ? r.getBoundingClientRect() : null;
            if (!br || br.width < 1 || br.height < 1) continue;
            if (!pointInViewportRect(clientX, clientY, br)) continue;
            if (flowId) containingRects.push({ area: br.width * br.height, rectEl: r, hasId: true, br: br });
            else if (isWorkflowSized(br.width, br.height)) containingRects.push({ area: br.width * br.height, rectEl: r, hasId: false, br: br });
        }
        if (debugCtx) {
            debugCtx.rectTotal = rects.length;
            debugCtx.containingRects = containingRects.map(function (c) {
                var r = c.rectEl;
                return { flowId: r.getAttribute('data-flow-id'), agentName: r.getAttribute('data-agent-name'), area: Math.round(c.area), hasId: c.hasId, bounds: { left: Math.round(c.br.left), top: Math.round(c.br.top), right: Math.round(c.br.right), bottom: Math.round(c.br.bottom) } };
            });
        }
        if (containingRects.length) {
            containingRects.sort(function (a, b) {
                if (a.hasId !== b.hasId) return a.hasId ? -1 : 1;
                return a.area - b.area;
            });
            var hit = containingRects[0];
            var rectEl = hit.rectEl;
            var rb = { x: parseFloat(rectEl.getAttribute('x')) || 0, y: parseFloat(rectEl.getAttribute('y')) || 0, w: parseFloat(rectEl.getAttribute('width')) || 0, h: parseFloat(rectEl.getAttribute('height')) || 0 };
            var pointInRect = function (qx, qy, r) { return qx >= r.x && qx <= r.x + r.w && qy >= r.y && qy <= r.y + r.h; };
            var cx = rb.x + rb.w / 2;
            var cy = rb.y + rb.h / 2;
            var labelSource = null;
            for (var j = 0; j < texts.length; j++) {
                var tb = texts[j].getBBox ? texts[j].getBBox() : null;
                if (tb && pointInRect(tb.x + tb.width / 2, tb.y + tb.height / 2, rb)) {
                    labelSource = 'textInRect';
                    if (debugCtx) debugCtx.labelSource = labelSource;
                    return { label: (texts[j].textContent || '').trim(), rect: rectEl };
                }
            }
            var nearest = null;
            var best = Infinity;
            for (var k = 0; k < texts.length; k++) {
                var tbb = texts[k].getBBox ? texts[k].getBBox() : null;
                if (tbb) {
                    var dx = (tbb.x + tbb.width / 2) - cx;
                    var dy = (tbb.y + tbb.height / 2) - cy;
                    var d = dx * dx + dy * dy;
                    if (d < best) { best = d; nearest = texts[k]; }
                }
            }
            if (nearest) {
                labelSource = 'nearestText';
                if (debugCtx) debugCtx.labelSource = labelSource;
                return { label: (nearest.textContent || '').trim(), rect: rectEl };
            }
        }
        var ellipses = svg.querySelectorAll('ellipse[data-flow-id]');
        var circles = svg.querySelectorAll('circle[data-flow-id]');
        var getSvgPoint = function (el, vx, vy) {
            if (!el.ownerSVGElement || !el.ownerSVGElement.createSVGPoint) return null;
            var pt = el.ownerSVGElement.createSVGPoint();
            pt.x = vx;
            pt.y = vy;
            var ctm = el.getScreenCTM ? el.getScreenCTM() : null;
            if (!ctm || !ctm.inverse) return null;
            var svgPt = pt.matrixTransform(ctm.inverse());
            return { x: svgPt.x, y: svgPt.y };
        };
        var pointInEllipse = function (qx, qy, el) {
            var cx = parseFloat(el.getAttribute('cx')) || 0;
            var cy = parseFloat(el.getAttribute('cy')) || 0;
            var rx = parseFloat(el.getAttribute('rx')) || parseFloat(el.getAttribute('r')) || 1;
            var ry = parseFloat(el.getAttribute('ry')) || rx;
            return ((qx - cx) / rx) * ((qx - cx) / rx) + ((qy - cy) / ry) * ((qy - cy) / ry) <= 1;
        };
        for (var ei = 0; ei < ellipses.length; ei++) {
            var ep = getSvgPoint(ellipses[ei], clientX, clientY);
            if (ep && pointInEllipse(ep.x, ep.y, ellipses[ei])) {
                return { label: ellipses[ei].getAttribute('data-step') || 'Overseer', rect: ellipses[ei] };
            }
        }
        for (var ci = 0; ci < circles.length; ci++) {
            var cp = getSvgPoint(circles[ci], clientX, clientY);
            if (cp && pointInEllipse(cp.x, cp.y, circles[ci])) {
                return { label: circles[ci].getAttribute('data-step') || 'Overseer', rect: circles[ci] };
            }
        }
        return null;
    }
    var WORKFLOW_CHART_PREFIX = {
        workflow_2d: '2D',
        workflow_3d: '3D',
        workflow_distribution: 'Distribution',
        workflow_maintenance: 'Maintenance',
        workflow_clipfarm: 'Clipfarm',
        workflow_channels: 'Channel'
    };
    var WORKFLOW_BOX_IDS_CACHE = null;
    /** AbortController for in-flight workflow step fetch; cancel when opening a new box to avoid stale responses overwriting current dialog */
    var workflowStepFetchController = null;
    var workflowStepFetchId = 0;
    function getWorkflowBoxIdsMapping() {
        if (WORKFLOW_BOX_IDS_CACHE) return Promise.resolve(WORKFLOW_BOX_IDS_CACHE);
        return fetch('/static/data/workflow_box_ids.json').then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; }).then(function (data) {
            WORKFLOW_BOX_IDS_CACHE = data;
            return data;
        });
    }
    /**
     * Move workflow label text elements to the end of the SVG so they render on top
     * of filled rects (which would otherwise cover text drawn earlier in document order).
     */
    function ensureWorkflowTextOnTop(svg) {
        if (!svg) return;
        var texts = [].slice.call(svg.querySelectorAll('text'));
        var fragment = document.createDocumentFragment();
        for (var i = 0; i < texts.length; i++) {
            var t = texts[i];
            var label = (t.textContent || '').trim();
            if (!label) continue;
            fragment.appendChild(t);
        }
        if (fragment.childNodes.length) {
            svg.appendChild(fragment);
        }
    }
    /**
     * Round text transform coordinates to integers to avoid blurry/subpixel rendering.
     */
    function ensureWorkflowTextSharp(svg) {
        if (!svg) return;
        var texts = svg.querySelectorAll('text[transform]');
        for (var i = 0; i < texts.length; i++) {
            var t = texts[i];
            var tr = t.getAttribute('transform') || '';
            var m = tr.match(/translate\s*\(\s*([\d.-]+)\s*[, ]\s*([\d.-]+)\s*\)/);
            if (m) {
                var tx = Math.round(parseFloat(m[1]));
                var ty = Math.round(parseFloat(m[2]));
                t.setAttribute('transform', 'translate(' + tx + ',' + ty + ')');
            }
        }
    }
    /**
     * Center all text inside workflow boxes and overseer circles horizontally and vertically.
     * Handles both rects (workflow boxes) and ellipses/circles (overseers) in all charts.
     */
    function centerWorkflowBoxText(svg) {
        if (!svg) return;
        var rects = svg.querySelectorAll('rect[width][height]');
        var texts = [].slice.call(svg.querySelectorAll('text'));
        var isWorkflowSized = function (w, h) { return w >= 50 && w <= 350 && h >= 20 && h <= 120; };
        var getRectBounds = function (r) {
            var x = parseFloat(r.getAttribute('x')) || 0;
            var y = parseFloat(r.getAttribute('y')) || 0;
            var w = parseFloat(r.getAttribute('width')) || 0;
            var h = parseFloat(r.getAttribute('height')) || 0;
            return { x: x, y: y, w: w, h: h, cx: x + w / 2, cy: y + h / 2 };
        };
        var pointInRect = function (px, py, r) { return px >= r.x && px <= r.x + r.w && py >= r.y && py <= r.y + r.h; };
        var pointInEllipse = function (px, py, cx, cy, rx, ry) {
            return rx > 0 && ry > 0 && Math.pow((px - cx) / rx, 2) + Math.pow((py - cy) / ry, 2) <= 1;
        };
        var getTextCenter = function (t) {
            try {
                var tr = (t.getAttribute && t.getAttribute('transform')) || '';
                var m = tr.match(/translate\s*\(\s*([\d.-]+)\s*[, ]\s*([\d.-]+)\s*\)/);
                var tx = (m && m[1] != null) ? parseFloat(m[1]) : 0;
                var ty = (m && m[2] != null) ? parseFloat(m[2]) : 0;
                var bbox = t.getBBox ? t.getBBox() : null;
                if (bbox && (bbox.width > 0 || bbox.height > 0)) {
                    var cx = tx + bbox.x + bbox.width / 2;
                    var cy = ty + bbox.y + bbox.height / 2;
                    return { x: cx, y: cy };
                }
                return { x: tx, y: ty };
            } catch (e) { return null; }
        };
        var centerTextInShape = function (t, cx, cy) {
            t.setAttribute('text-anchor', 'middle');
            t.setAttribute('dominant-baseline', 'central');
            t.setAttribute('transform', 'translate(' + Math.round(cx) + ',' + Math.round(cy) + ')');
            var tspans = t.querySelectorAll('tspan');
            var lineHeight = 1.15;
            for (var si = 0; si < tspans.length; si++) {
                tspans[si].setAttribute('x', '0');
                if (tspans.length === 1) {
                    tspans[si].setAttribute('y', '0');
                    tspans[si].removeAttribute('dy');
                } else {
                    /* Multi-line: centre block vertically. First line offset up, each next +lineHeight. */
                    if (si === 0) {
                        var n = tspans.length;
                        var firstDy = -((n - 1) * lineHeight) / 2;
                        tspans[si].setAttribute('dy', firstDy + 'em');
                    } else {
                        tspans[si].setAttribute('dy', lineHeight + 'em');
                    }
                }
            }
        };
        var centeredTexts = {};
        /* 1. Center text in workflow boxes (rects) */
        var rectMargin = 25;
        for (var ri = 0; ri < rects.length; ri++) {
            var r = rects[ri];
            var rb = getRectBounds(r);
            if (!isWorkflowSized(rb.w, rb.h)) continue;
            var rbExpanded = { x: rb.x - rectMargin, y: rb.y - rectMargin, w: rb.w + 2 * rectMargin, h: rb.h + 2 * rectMargin };
            var bestText = null;
            var bestDist = Infinity;
            for (var ti = 0; ti < texts.length; ti++) {
                var t = texts[ti];
                var label = (t.textContent || '').trim();
                if (!label) continue;
                if (centeredTexts[t]) continue;
                var tc = getTextCenter(t);
                if (!tc) continue;
                if (pointInRect(tc.x, tc.y, rbExpanded)) {
                    var d = Math.pow(tc.x - rb.cx, 2) + Math.pow(tc.y - rb.cy, 2);
                    if (d < bestDist) { bestDist = d; bestText = t; }
                }
            }
            if (bestText) {
                centeredTexts[bestText] = true;
                centerTextInShape(bestText, rb.cx, rb.cy);
            }
        }
        /* 2. Center text in overseer circles/ellipses */
        var ellipses = [].slice.call(svg.querySelectorAll('ellipse')).filter(function (el) {
            var rx = parseFloat(el.getAttribute('rx')) || 0;
            var ry = parseFloat(el.getAttribute('ry')) || 0;
            return rx >= 30 && rx <= 120 && ry >= 25 && ry <= 90;
        });
        var circles = [].slice.call(svg.querySelectorAll('circle')).filter(function (el) {
            var r = parseFloat(el.getAttribute('r')) || 0;
            return r >= 25 && r <= 100;
        });
        var overseerShapes = ellipses.map(function (el) {
            var cx = parseFloat(el.getAttribute('cx')) || 0;
            var cy = parseFloat(el.getAttribute('cy')) || 0;
            var rx = parseFloat(el.getAttribute('rx')) || 0;
            var ry = parseFloat(el.getAttribute('ry')) || 0;
            return { cx: cx, cy: cy, rx: rx, ry: ry };
        }).concat(circles.map(function (el) {
            var cx = parseFloat(el.getAttribute('cx')) || 0;
            var cy = parseFloat(el.getAttribute('cy')) || 0;
            var r = parseFloat(el.getAttribute('r')) || 0;
            return { cx: cx, cy: cy, rx: r, ry: r };
        }));
        for (var oi = 0; oi < overseerShapes.length; oi++) {
            var sh = overseerShapes[oi];
            var bestText = null;
            var bestDist = Infinity;
            for (var ti = 0; ti < texts.length; ti++) {
                var t = texts[ti];
                var label = (t.textContent || '').trim();
                if (!label) continue;
                if (centeredTexts[t]) continue;
                if (t.getAttribute('visibility') === 'hidden') continue;
                var tc = getTextCenter(t);
                if (!tc) continue;
                if (pointInEllipse(tc.x, tc.y, sh.cx, sh.cy, sh.rx, sh.ry)) {
                    var d = Math.pow(tc.x - sh.cx, 2) + Math.pow(tc.y - sh.cy, 2);
                    if (d < bestDist) { bestDist = d; bestText = t; }
                }
            }
            if (bestText) {
                centeredTexts[bestText] = true;
                centerTextInShape(bestText, sh.cx, sh.cy);
            }
        }
    }
    function assignWorkflowBoxIds(svg, chartType, boxIdsMapping) {
        if (!svg || !chartType) return;
        if (typeof window.WORKFLOW_BOX_IDS === 'undefined') window.WORKFLOW_BOX_IDS = [];
        /* Reset so only the current chart's entries are present; avoids stale matches from other charts */
        window.WORKFLOW_BOX_IDS = [];
        var rects = svg.querySelectorAll('rect[width][height]');
        var texts = svg.querySelectorAll('text');
        var getRectBounds = function (r) {
            var x = parseFloat(r.getAttribute('x')) || 0;
            var y = parseFloat(r.getAttribute('y')) || 0;
            var w = parseFloat(r.getAttribute('width')) || 0;
            var h = parseFloat(r.getAttribute('height')) || 0;
            return { x: x, y: y, w: w, h: h, cx: x + w / 2, cy: y + h / 2 };
        };
        var pointInRect = function (px, py, r) { return px >= r.x && px <= r.x + r.w && py >= r.y && py <= r.y + r.h; };
        var getTextPosition = function (t) {
            var tr = (t.getAttribute && t.getAttribute('transform')) || '';
            var m = tr.match(/translate\s*\(\s*([\d.-]+)\s+([\d.-]+)\s*\)/) || tr.match(/translate\s*\(\s*([\d.-]+)\s*,\s*([\d.-]+)\s*\)/);
            var tx = (m && m[1] != null) ? parseFloat(m[1]) : 0;
            var ty = (m && m[2] != null) ? parseFloat(m[2]) : 0;
            var bbox = t.getBBox ? t.getBBox() : null;
            if (bbox && (bbox.width > 0 || bbox.height > 0)) {
                var cx = tx + bbox.x + bbox.width / 2;
                var cy = ty + bbox.y + bbox.height / 2;
                return { x: cx, y: cy, ySort: cy, xSort: cx };
            }
            if (m && m[1] != null) return { x: tx, y: ty, ySort: ty, xSort: tx };
            return null;
        };
        var normalize = function (s) { return (s || '').trim().replace(/\s+/g, ' '); };
        /* Match labels flexibly: two-line SVG text (e.g. "Mandarin"+"Marketing") yields textContent without space;
           mapping has "Mandarin Marketing". Compare both normalized and space-removed versions. */
        var labelsMatch = function (a, b) {
            var na = normalize(a);
            var nb = normalize(b);
            if (na === nb) return true;
            if (na.replace(/\s/g, '') === nb.replace(/\s/g, '')) return true;
            /* Known SVG typos/variants vs mapping */
            var la = na.toLowerCase(), lb = nb.toLowerCase();
            if ((la === 'cultural adapation' || lb === 'cultural adapation') && (la === 'cultural adaptation' || lb === 'cultural adaptation')) return true;
            if ((la === 'multilangual voice' || lb === 'multilangual voice') && (la === 'multilingual voice' || lb === 'multilingual voice')) return true;
            return false;
        };
        var textsWithPos = [];
        for (var ti = 0; ti < texts.length; ti++) {
            var t = texts[ti];
            var label = (t.textContent || '').trim();
            if (!label) continue;
            var pos = getTextPosition(t);
            if (!pos) continue;
            textsWithPos.push({ textEl: t, label: label, pos: pos });
        }
        var entries = (boxIdsMapping && boxIdsMapping[chartType]) || [];
        var prefix = WORKFLOW_CHART_PREFIX[chartType] || chartType.replace('workflow_', '').replace(/_/g, ' ');
        var assignedRects = {};
        var unusedEntries = [];
        for (var idx = 0; idx < entries.length; idx++) {
            var entry = entries[idx];
            var matchText = normalize(entry.text);
            var candidates = textsWithPos.filter(function (twp) { return labelsMatch(twp.label, matchText) && !twp.textEl._wfAssigned; });
            candidates.sort(function (a, b) { return (a.pos.ySort - b.pos.ySort) || (a.pos.xSort - b.pos.xSort); });
            if (candidates.length === 0) { unusedEntries.push({ entry: entry, idx: idx }); continue; }
            var twp = candidates[0];
            twp.textEl._wfAssigned = true;
            var px = twp.pos.x;
            var py = twp.pos.y;
            var bestRect = null;
            var bestArea = Infinity;
            for (var ri = 0; ri < rects.length; ri++) {
                var r = rects[ri];
                var rkey = 'r' + ri + '-' + (r.getAttribute('x') || '') + '-' + (r.getAttribute('y') || '');
                if (assignedRects[rkey]) continue;
                var rb = getRectBounds(r);
                if (!pointInRect(px, py, rb)) continue;
                var area = rb.w * rb.h;
                if (area < bestArea) { bestArea = area; bestRect = r; }
            }
            if (!bestRect) continue;
            var rectKey = 'r' + Array.prototype.indexOf.call(rects, bestRect) + '-' + (bestRect.getAttribute('x') || '') + '-' + (bestRect.getAttribute('y') || '');
            assignedRects[rectKey] = true;
            var flowId = entry.flowId || (prefix + '_FLOW' + (idx + 1));
            var txtId = entry.txtId || (prefix + '_TXT' + (idx + 1));
            var agentName = entry.agentName || (prefix + ' ' + twp.label);
            bestRect.setAttribute('id', 'wf-' + chartType + '-' + idx);
            bestRect.setAttribute('data-flow-id', flowId);
            bestRect.setAttribute('data-txt-id', txtId);
            bestRect.setAttribute('data-agent-name', agentName);
            bestRect.setAttribute('data-step', twp.label);
            bestRect.setAttribute('data-unique-label', agentName);
            if (entry.text === 'Distribution') bestRect.setAttribute('data-navigate-only', 'true');
            bestRect.style.pointerEvents = 'all';
            var rbAssign = getRectBounds(bestRect);
            if (twp.textEl) {
                twp.textEl.setAttribute('id', (txtId).toLowerCase().replace(/\s/g, '-'));
                twp.textEl.setAttribute('data-txt-id', txtId);
                twp.textEl.setAttribute('text-anchor', 'middle');
                twp.textEl.setAttribute('dominant-baseline', 'central');
                twp.textEl.setAttribute('transform', 'translate(' + Math.round(rbAssign.cx) + ',' + Math.round(rbAssign.cy) + ')');
                var tspans = twp.textEl.querySelectorAll('tspan');
                for (var si = 0; si < tspans.length; si++) {
                    tspans[si].setAttribute('x', '0');
                    if (tspans.length === 1) tspans[si].setAttribute('y', '0');
                }
            }
            for (var hi = 0; hi < textsWithPos.length; hi++) {
                var ot = textsWithPos[hi];
                if (ot.textEl === twp.textEl) continue;
                if (pointInRect(ot.pos.x, ot.pos.y, rbAssign)) ot.textEl.setAttribute('visibility', 'hidden');
            }
            if (entry.text === 'Distribution' && (chartType === 'workflow_2d' || chartType === 'workflow_3d')) {
                var paths = svg.querySelectorAll('path[d]');
                for (var pi = 0; pi < paths.length; pi++) {
                    var p = paths[pi];
                    try {
                        var pb = p.getBBox && p.getBBox();
                        if (pb && pb.width > 0 && pb.height > 0) {
                            var pcx = pb.x + pb.width / 2;
                            var pcy = pb.y + pb.height / 2;
                            if (pointInRect(pcx, pcy, rbAssign)) p.setAttribute('visibility', 'hidden');
                        }
                    } catch (e) { /* getBBox may fail */ }
                }
            }
            window.WORKFLOW_BOX_IDS.push({
                flowId: flowId,
                txtId: txtId,
                agentName: agentName,
                label: twp.label,
                uniqueLabel: agentName,
                chart: chartType
            });
        }
        if (unusedEntries.length > 0) {
            var unassignedRects = [];
            var isDistributionNavRect = function (rect, bounds) {
                for (var ti = 0; ti < textsWithPos.length; ti++) {
                    if (normalize(textsWithPos[ti].label).toLowerCase() !== 'distribution') continue;
                    if (pointInRect(textsWithPos[ti].pos.x, textsWithPos[ti].pos.y, bounds)) return true;
                }
                return false;
            };
            for (var ri = 0; ri < rects.length; ri++) {
                var r = rects[ri];
                var rkey = 'r' + ri + '-' + (r.getAttribute('x') || '') + '-' + (r.getAttribute('y') || '');
                if (assignedRects[rkey]) continue;
                var rb = getRectBounds(r);
                if (rb.w < 50 || rb.h < 30) continue;
                if (isDistributionNavRect(r, rb)) continue;
                unassignedRects.push({ rect: r, y: rb.cy, x: rb.cx });
            }
            unassignedRects.sort(function (a, b) { return (a.y - b.y) || (a.x - b.x); });
            var ns = 'http://www.w3.org/2000/svg';
            for (var u = 0; u < unusedEntries.length && u < unassignedRects.length; u++) {
                var ue = unusedEntries[u];
                var ur = unassignedRects[u];
                var entry = ue.entry;
                var r = ur.rect;
                var rb = getRectBounds(r);
                var flowId = entry.flowId || (prefix + '_FLOW_orphan_' + u);
                var txtId = entry.txtId || (prefix + '_TXT_orphan_' + u);
                var agentName = entry.agentName || (prefix + ' ' + entry.text);
                var label = entry.text || 'Agent';
                r.setAttribute('id', 'wf-' + chartType + '-orphan-' + u);
                r.setAttribute('data-flow-id', flowId);
                r.setAttribute('data-txt-id', txtId);
                r.setAttribute('data-agent-name', agentName);
                r.setAttribute('data-step', label);
                r.setAttribute('data-unique-label', agentName);
                if (entry.text === 'Distribution') r.setAttribute('data-navigate-only', 'true');
                r.style.pointerEvents = 'all';
                var existingText = null;
                for (var ti = 0; ti < textsWithPos.length; ti++) {
                    var twp = textsWithPos[ti];
                    if (pointInRect(twp.pos.x, twp.pos.y, rb)) { existingText = twp.textEl; break; }
                }
                if (existingText) {
                    existingText.textContent = label;
                    existingText.setAttribute('data-txt-id', txtId);
                    existingText.setAttribute('text-anchor', 'middle');
                    existingText.setAttribute('dominant-baseline', 'central');
                    existingText.setAttribute('transform', 'translate(' + Math.round(rb.cx) + ',' + Math.round(rb.cy) + ')');
                    var tspans = existingText.querySelectorAll('tspan');
                    for (var si = 0; si < tspans.length; si++) {
                        tspans[si].setAttribute('x', '0');
                        if (tspans.length === 1) tspans[si].setAttribute('y', '0');
                    }
                    for (var hi = 0; hi < textsWithPos.length; hi++) {
                        var ot = textsWithPos[hi];
                        if (ot.textEl === existingText) continue;
                        if (pointInRect(ot.pos.x, ot.pos.y, rb)) ot.textEl.setAttribute('visibility', 'hidden');
                    }
                } else {
                    var textEl = document.createElementNS(ns, 'text');
                    textEl.setAttribute('class', 'cls-65');
                    textEl.setAttribute('text-anchor', 'middle');
                    textEl.setAttribute('dominant-baseline', 'central');
                    textEl.setAttribute('transform', 'translate(' + Math.round(rb.cx) + ',' + Math.round(rb.cy) + ')');
                    textEl.setAttribute('data-txt-id', txtId);
                    var tspan = document.createElementNS(ns, 'tspan');
                    tspan.setAttribute('x', '0');
                    tspan.setAttribute('y', '0');
                    tspan.textContent = label;
                    textEl.appendChild(tspan);
                    (r.parentNode || svg).appendChild(textEl);
                }
                /* For Distribution box in 2D/3D chart: hide path-rendered labels that cause double names */
                if ((chartType === 'workflow_2d' || chartType === 'workflow_3d') && label === 'Distribution') {
                    var paths = svg.querySelectorAll('path[d]');
                    for (var pi = 0; pi < paths.length; pi++) {
                        var p = paths[pi];
                        try {
                            var pb = p.getBBox && p.getBBox();
                            if (pb && pb.width > 0 && pb.height > 0) {
                                var pcx = pb.x + pb.width / 2;
                                var pcy = pb.y + pb.height / 2;
                                if (pointInRect(pcx, pcy, rb)) p.setAttribute('visibility', 'hidden');
                            }
                        } catch (e) { /* getBBox may fail on detached elements */ }
                    }
                }
                window.WORKFLOW_BOX_IDS.push({
                    flowId: flowId,
                    txtId: txtId,
                    agentName: agentName,
                    label: label,
                    uniqueLabel: agentName,
                    chart: chartType
                });
            }
        }
        var overseersKey = chartType + '_overseers';
        var overseerEntries = (boxIdsMapping && boxIdsMapping[overseersKey]) || [];
        if (overseerEntries.length) {
            var ellipses = [].slice.call(svg.querySelectorAll('ellipse')).filter(function (el) {
                var rx = parseFloat(el.getAttribute('rx')) || 0;
                var ry = parseFloat(el.getAttribute('ry')) || 0;
                return rx >= 40 && rx <= 100 && ry >= 30 && ry <= 80;
            });
            var circles = [].slice.call(svg.querySelectorAll('circle')).filter(function (el) {
                var r = parseFloat(el.getAttribute('r')) || 0;
                return r >= 30 && r <= 80;
            });
            var shapes = ellipses.map(function (el) {
                var cx = parseFloat(el.getAttribute('cx')) || 0;
                var cy = parseFloat(el.getAttribute('cy')) || 0;
                return { el: el, y: cy, x: cx };
            }).concat(circles.map(function (el) {
                var cx = parseFloat(el.getAttribute('cx')) || 0;
                var cy = parseFloat(el.getAttribute('cy')) || 0;
                return { el: el, y: cy, x: cx };
            }));
            shapes.sort(function (a, b) { return (a.y - b.y) || (a.x - b.x); });
            var seen = {};
            var overseerShapes = [];
            for (var s = 0; s < shapes.length; s++) {
                var key = shapes[s].x.toFixed(0) + ',' + shapes[s].y.toFixed(0);
                if (seen[key]) continue;
                seen[key] = true;
                overseerShapes.push(shapes[s]);
                if (overseerShapes.length >= overseerEntries.length) break;
            }
            var ns = 'http://www.w3.org/2000/svg';
            var getOverseerLabel = function (oe) {
                if (oe.text && normalize(oe.text) !== 'overseer') return oe.text;
                var an = (oe.agentName || '').trim();
                if (!an) return 'Overseer';
                return an.replace(/^[A-Z0-9-]+\s+/, '');
            };
            for (var oidx = 0; oidx < overseerShapes.length && oidx < overseerEntries.length; oidx++) {
                var sh = overseerShapes[oidx];
                var oe = overseerEntries[oidx];
                var el = sh.el;
                var next = el.nextElementSibling;
                while (next) {
                    var tag = (next.tagName || '').toLowerCase();
                    if (tag === 'g' && next.querySelectorAll('path').length > 5) {
                        var toRemove = next;
                        next = next.nextElementSibling;
                        toRemove.remove();
                    } else if (tag === 'ellipse' || tag === 'circle') {
                        next = next.nextElementSibling;
                    } else {
                        break;
                    }
                }
                el.setAttribute('data-flow-id', oe.flowId);
                sh.el.setAttribute('data-txt-id', oe.txtId);
                sh.el.setAttribute('data-agent-name', oe.agentName);
                sh.el.setAttribute('data-step', oe.text || 'Overseer');
                sh.el.setAttribute('data-unique-label', oe.agentName);
                sh.el.setAttribute('id', 'wf-' + chartType + '-overseer-' + oidx);
                sh.el.style.pointerEvents = 'all';
                var label = getOverseerLabel(oe);
                if (chartType === 'workflow_distribution') {
                    window.WORKFLOW_BOX_IDS.push({ flowId: oe.flowId, txtId: oe.txtId, agentName: oe.agentName, label: label, uniqueLabel: oe.agentName, chart: chartType });
                    continue;
                }
                var cx = parseFloat(sh.el.getAttribute('cx')) || 0;
                var cy = parseFloat(sh.el.getAttribute('cy')) || 0;
                var textEl = document.createElementNS(ns, 'text');
                textEl.setAttribute('class', 'cls-65');
                textEl.setAttribute('text-anchor', 'middle');
                textEl.setAttribute('dominant-baseline', 'central');
                textEl.setAttribute('transform', 'translate(' + Math.round(cx) + ',' + Math.round(cy) + ')');
                textEl.setAttribute('data-txt-id', oe.txtId);
                textEl.setAttribute('fill', '#2c3e50');
                textEl.setAttribute('stroke', 'none');
                if (label === 'Clip Farm Overseer' && chartType === 'workflow_clipfarm') {
                  textEl.setAttribute('font-size', '14px');
                  var line1 = document.createElementNS(ns, 'tspan');
                  line1.setAttribute('x', '0');
                  line1.setAttribute('dy', '-0.45em');
                  line1.textContent = 'Clip Farm';
                  var line2 = document.createElementNS(ns, 'tspan');
                  line2.setAttribute('x', '0');
                  line2.setAttribute('dy', '1.2em');
                  line2.textContent = 'Overseer';
                  textEl.appendChild(line1);
                  textEl.appendChild(line2);
                } else if ((label === 'Production Overseer' || label === 'Media Overseer') && (chartType === 'workflow_2d' || chartType === 'workflow_3d')) {
                  textEl.setAttribute('font-size', '15px');
                  textEl.setAttribute('font-weight', '600');
                  var line1 = document.createElementNS(ns, 'tspan');
                  line1.setAttribute('x', '0');
                  line1.setAttribute('dy', '-0.4em');
                  line1.textContent = label.split(' ')[0];
                  var line2 = document.createElementNS(ns, 'tspan');
                  line2.setAttribute('x', '0');
                  line2.setAttribute('dy', '1.15em');
                  line2.textContent = 'Overseer';
                  textEl.appendChild(line1);
                  textEl.appendChild(line2);
                } else if (chartType === 'workflow_distribution' && label && label.indexOf('Overseer') !== -1) {
                  textEl.setAttribute('font-size', '13px');
                  textEl.setAttribute('font-weight', '600');
                  var parts = label.split(' Overseer');
                  var firstPart = parts[0] || label.replace(/\s+Overseer$/, '');
                  var line1 = document.createElementNS(ns, 'tspan');
                  line1.setAttribute('x', '0');
                  line1.setAttribute('dy', '-0.4em');
                  line1.textContent = firstPart || 'Overseer';
                  var line2 = document.createElementNS(ns, 'tspan');
                  line2.setAttribute('x', '0');
                  line2.setAttribute('dy', '1.15em');
                  line2.textContent = 'Overseer';
                  textEl.appendChild(line1);
                  textEl.appendChild(line2);
                } else {
                  var tspan = document.createElementNS(ns, 'tspan');
                  tspan.setAttribute('x', '0');
                  tspan.setAttribute('y', '0');
                  tspan.textContent = label;
                  textEl.appendChild(tspan);
                }
                var parent = sh.el.parentNode || svg;
                parent.appendChild(textEl);
                window.WORKFLOW_BOX_IDS.push({
                    flowId: oe.flowId,
                    txtId: oe.txtId,
                    agentName: oe.agentName,
                    label: label,
                    uniqueLabel: oe.agentName,
                    chart: chartType
                });
            }
        }
        /* Stage 5 Distribution rect: set as navigate-only button - no agent (2D: 1599,326 | 3D: 1598,252). There are 2 overlapping rects; update all. */
        if (chartType === 'workflow_2d' || chartType === 'workflow_3d') {
            var distRectY = chartType === 'workflow_2d' ? 326 : 252;
            var distRectX = chartType === 'workflow_2d' ? 1599 : 1598;
            for (var dri = 0; dri < rects.length; dri++) {
                var dr = rects[dri];
                var dx = parseFloat(dr.getAttribute('x')) || 0;
                var dy = parseFloat(dr.getAttribute('y')) || 0;
                if (Math.abs(dx - distRectX) < 5 && Math.abs(dy - distRectY) < 5) {
                    dr.setAttribute('data-step', 'Distribution');
                    dr.setAttribute('data-navigate-only', 'true');
                    dr.removeAttribute('data-agent-name');
                    dr.setAttribute('data-flow-id', 'FLOW0139');
                    dr.setAttribute('data-txt-id', 'TXT0139');
                    dr.style.pointerEvents = 'all';
                }
            }
        }
    }
    function attachWorkflowSvgBoxClicks(containerEl) {
        if (!containerEl) return;
        var svg = containerEl.querySelector('svg');
        if (!svg) return;
        svg.style.cursor = 'pointer';
        function isDebugEnabled() { return (typeof window.WORKFLOW_CLICK_DEBUG !== 'undefined') ? window.WORKFLOW_CLICK_DEBUG : false; }
        var debugPanel = byId('workflow-click-debug-panel');
        var debugLog = [];
        function updateDebugPanel(info) {
            debugLog.unshift(info);
            if (debugLog.length > 8) debugLog.pop();
            if (!debugPanel) return;
            var html = '<div style="font-family:monospace;font-size:11px;line-height:1.4;color:#333;"><b>Workflow Click Debug</b>';
            for (var i = 0; i < debugLog.length; i++) {
                var d = debugLog[i];
                html += '<div style="margin-top:8px;padding:6px;background:#f0f0f0;border-radius:4px;border-left:3px solid #999;">';
                html += '<b>#' + (debugLog.length - i) + '</b> @ (' + d.clientX + ', ' + d.clientY + ')<br>';
                html += 'Source: ' + (d.source || '-') + ' | Chart: ' + (d.chart || '-') + '<br>';
                html += 'Label: ' + (d.label || '-') + '<br>';
                html += 'Agent: ' + (d.agentName || '-') + '<br>';
                if (d.containingRects && d.containingRects.length) {
                    html += 'Containing rects: ' + d.containingRects.length + ' → picked: ' + (d.containingRects[0] ? (d.containingRects[0].agentName || d.containingRects[0].flowId || '?') : '-') + '<br>';
                } else {
                    html += 'Containing rects: 0 (fell back to element)';
                }
                html += '</div>';
            }
            html += '</div>';
            debugPanel.innerHTML = html;
        }
        containerEl.addEventListener('click', function (e) {
            var chart = (containerEl && containerEl.getAttribute && containerEl.getAttribute('data-workflow-chart')) || (typeof window._selectedWorkflowChart !== 'undefined' ? window._selectedWorkflowChart : '') || '';
            var debugEnabled = isDebugEnabled();
            if (debugEnabled && debugPanel) debugPanel.style.display = 'block';
            var debugCtx = debugEnabled ? {} : null;
            var result = findLabelAtSvgPoint(svg, e.clientX, e.clientY, debugCtx);
            var source = result ? 'findLabelAtSvgPoint' : null;
            if (!result) { result = findLabelForSvgElement(e.target, svg); source = 'findLabelForSvgElement'; }
            var label = result && (typeof result === 'object' && result.label !== undefined) ? result.label : result;
            var rect = result && (typeof result === 'object') ? result.rect : null;
            var workflowIds = null;
            var agentName = null;
            if (rect && rect.getAttribute) {
                var flowId = rect.getAttribute('data-flow-id');
                var txtId = rect.getAttribute('data-txt-id');
                agentName = rect.getAttribute('data-agent-name');
                if (flowId || txtId || agentName) workflowIds = { flowId: flowId || '', txtId: txtId || '', agentName: agentName || '' };
            }
            var isDistributionBox = rect && (rect.getAttribute('data-step') === 'Distribution' || rect.getAttribute('data-navigate-only') === 'true');
            var isDistributionClick = (chart === 'workflow_2d' || chart === 'workflow_3d') && (isDistributionBox || (label === 'Distribution'));
            if (isDistributionClick) {
                showNavigateToDistributionModal(function (ok) {
                    if (ok) {
                        window._selectedWorkflowChart = 'workflow_distribution';
                        document.querySelectorAll('.security-diagram-workflow-option').forEach(function (o) { o.classList.remove('active'); });
                        var distOpt = document.querySelector('.security-diagram-workflow-option[data-chart="workflow_distribution"]');
                        if (distOpt) distOpt.classList.add('active');
                        var wfBtn = byId('security-diagram-workflow-btn');
                        if (wfBtn) wfBtn.classList.add('active');
                        var sublist = byId('security-diagram-workflow-sublist');
                        if (sublist) sublist.style.display = 'flex';
                        switchSecurityDiagramTab('workflow');
                        if (typeof updateWorkflowPanelDisplay === 'function') updateWorkflowPanelDisplay();
                    }
                });
            } else if (label) {
                showDiagramBoxInfo(label, 'workflow', 0, e.target, 0, chart, workflowIds);
            }
            if (debugEnabled) {
                var info = { clientX: e.clientX, clientY: e.clientY, source: source, chart: chart, label: label || '-', agentName: agentName || '-', targetTag: (e.target && e.target.tagName) ? e.target.tagName : '-' };
                if (debugCtx) {
                    info.containingRects = debugCtx.containingRects;
                    info.rectTotal = debugCtx.rectTotal;
                    info.labelSource = debugCtx.labelSource;
                }
                updateDebugPanel(info);
                console.log('[Workflow click]', { click: { x: e.clientX, y: e.clientY }, source: source, chart: chart, label: label, agentName: agentName, rect: rect ? { flowId: rect.getAttribute('data-flow-id'), agentName: rect.getAttribute('data-agent-name') } : null, containingRects: debugCtx ? debugCtx.containingRects : null, rectTotal: debugCtx ? debugCtx.rectTotal : null });
            }
        });
    }
    function showDiagramBoxInfo(boxLabel, diagramId, stepIndex, sourceEl, threatId, workflowChart, workflowIds) {
        threatId = threatId || 0;
        workflowChart = workflowChart || '';
        workflowIds = workflowIds || null;
        if (diagramId === 'workflow' && (!workflowIds || (!workflowIds.flowId && !workflowIds.txtId && !workflowIds.agentName))) {
            var arr = (typeof window.WORKFLOW_BOX_IDS !== 'undefined') ? window.WORKFLOW_BOX_IDS : [];
            var norm = function (s) { return (s || '').trim().replace(/\s+/g, ' '); };
            var match = arr.filter(function (e) {
                return norm(e.label) === norm(boxLabel) && (e.chart || '') === (workflowChart || '');
            })[0];
            if (match) workflowIds = { flowId: match.flowId, txtId: match.txtId, agentName: match.agentName };
        }
        var modal = byId('security-diagram-box-info-modal');
        var titleBox = byId('security-diagram-box-info-title');
        if (!modal || !titleBox) return;
        if (diagramId === 'workflow' && workflowIds && (workflowIds.flowId || workflowIds.txtId || workflowIds.agentName)) {
            titleBox.textContent = workflowIds.agentName || boxLabel;
        } else {
            titleBox.textContent = boxLabel;
        }
        var funcPanel = byId('security-diagram-box-info-function');
        var idsPanel = byId('security-diagram-box-info-ids');
        var agentsPanel = byId('security-diagram-box-info-agents');
        var llmsPanel = byId('security-diagram-box-info-llms');
        var toolsPanel = byId('security-diagram-box-info-tools');
        if (idsPanel) {
            var idsHtml = '—';
            if (diagramId === 'workflow' && workflowIds && (workflowIds.flowId || workflowIds.txtId || workflowIds.agentName)) {
                idsHtml = '<dl style="margin:0; font-size:0.95rem; line-height:1.6;">' +
                    '<dt style="margin:0.4em 0 0.1em; font-weight:600; color:#555;">Workflow Box ID</dt>' +
                    '<dd style="margin:0 0 0 1em; font-family:monospace;">' + (workflowIds.flowId || '—') + '</dd>' +
                    '<dt style="margin:0.4em 0 0.1em; font-weight:600; color:#555;">Text ID</dt>' +
                    '<dd style="margin:0 0 0 1em; font-family:monospace;">' + (workflowIds.txtId || '—') + '</dd>' +
                    '<dt style="margin:0.4em 0 0.1em; font-weight:600; color:#555;">Agent Name</dt>' +
                    '<dd style="margin:0 0 0 1em;">' + (workflowIds.agentName || '—') + '</dd>' +
                    '<dt style="margin:0.4em 0 0.1em; font-weight:600; color:#555;">Display Text</dt>' +
                    '<dd style="margin:0 0 0 1em;">' + (boxLabel || '—') + '</dd>' +
                    '</dl>';
            }
            idsPanel.innerHTML = idsHtml;
        }
        if (funcPanel) {
            var html = '—';
            if (diagramId === 'threat_model' && threatId >= 1 && threatId <= 28) {
                var ti = THREAT_MODEL_INFO.find(function (x) { return x.id === threatId; });
                if (ti) html = ti.html || ('<p>' + (ti.title || '') + '</p>');
            } else if (diagramId === 'password' && stepIndex >= 1 && stepIndex <= 8) html = '<p>' + (PYRAMID_BAND_INFO[stepIndex - 1].desc || PYRAMID_BAND_INFO[stepIndex - 1].title || '') + '</p>';
            else if (diagramId === 'user' && stepIndex >= 1 && stepIndex <= 10) html = USERS_STEP_INFO[stepIndex - 1].html || ('<p>' + (USERS_STEP_INFO[stepIndex - 1].title || '') + '</p>');
            else if (diagramId === 'schedules' && stepIndex >= 1 && stepIndex <= 8) html = SCHEDULES_STEP_INFO[stepIndex - 1].html || ('<p>' + (SCHEDULES_STEP_INFO[stepIndex - 1].title || '') + '</p>');
            else if (diagramId === 'ai' && stepIndex >= 1 && stepIndex <= 5) html = AGENTS_STEP_INFO[stepIndex - 1].html || ('<p>' + (AGENTS_STEP_INFO[stepIndex - 1].title || '') + '</p>');
            else if (diagramId === 'web' && sourceEl && sourceEl.getAttribute) { var step = parseInt(sourceEl.getAttribute('data-step'), 10); if (step >= 1 && step <= 13) html = WEB_SECURITY_STEP_INFO[step - 1].html || ('<p>' + (WEB_SECURITY_STEP_INFO[step - 1].title || '') + '</p>'); }
            else if (diagramId === 'workflow') html = '<p style="color:#666;">Loading...</p>';
            funcPanel.innerHTML = html;
        }
        if (agentsPanel) agentsPanel.textContent = 'No agents assigned.';
        if (llmsPanel) llmsPanel.textContent = 'No LLMs required.';
        if (toolsPanel) toolsPanel.textContent = 'No tools assigned.';
        modal.querySelectorAll('.security-diagram-box-info-panel').forEach(function (p) { p.style.display = 'none'; });
        if (funcPanel) funcPanel.style.display = 'block';
        modal.querySelectorAll('.security-diagram-box-info-tab').forEach(function (t) { t.classList.remove('active'); });
        var funcTab = modal.querySelector('.security-diagram-box-info-tab[data-tab="function"]');
        if (funcTab) funcTab.classList.add('active');
        /* Unique IDs, Assigned Agents, Assigned LLMs and Tools tabs only visible for workflow charts */
        var idsTab = modal.querySelector('.security-diagram-box-info-tab[data-tab="ids"]');
        var agentsTab = modal.querySelector('.security-diagram-box-info-tab[data-tab="agents"]');
        var llmsTab = modal.querySelector('.security-diagram-box-info-tab[data-tab="llms"]');
        var toolsTab = modal.querySelector('.security-diagram-box-info-tab[data-tab="tools"]');
        var showAssignments = diagramId === 'workflow';
        if (idsTab) idsTab.style.display = showAssignments ? '' : 'none';
        if (agentsTab) agentsTab.style.display = showAssignments ? '' : 'none';
        if (llmsTab) llmsTab.style.display = showAssignments ? '' : 'none';
        if (toolsTab) toolsTab.style.display = showAssignments ? '' : 'none';
        modal.style.display = 'flex';
        /* Only fetch when we have a specific agentName. Never use generic "Error Detection" label - it maps to Error-Detector-Agent and causes wrong agent to load for non-Error-Detection boxes. */
        var stepParam = (workflowIds && workflowIds.agentName) ? workflowIds.agentName : null;
        if (showAssignments && !stepParam && funcPanel) {
            funcPanel.innerHTML = '<p style="color:#666;">Agent data unavailable. The workflow box mapping may not have loaded yet.</p>';
        }
        if (showAssignments && stepParam && (agentsPanel || llmsPanel || toolsPanel)) {
            if (workflowStepFetchController) workflowStepFetchController.abort();
            workflowStepFetchController = new AbortController();
            var thisFetchId = ++workflowStepFetchId;
            var url = '/api/workflow/steps/agents?step=' + encodeURIComponent(stepParam);
            if (workflowChart) url += '&chart=' + encodeURIComponent(workflowChart);
            fetch(url, { signal: workflowStepFetchController.signal })
                .then(function (r) { return r.ok ? r.json() : { agents: [], llms: [], tools: [] }; })
                .catch(function (err) { if (err && err.name === 'AbortError') return null; return { agents: [], llms: [], tools: [] }; })
                .then(function (data) {
                    if (data === null || workflowStepFetchId !== thisFetchId) return;
                    var agents = data.agents || [];
                    var llms = data.llms || [];
                    var tools = data.tools || [];
                    var funcHtml = data.function || '';
                    var isExecutionOnly = data.is_execution_only;
                    var orchestratedBy = data.orchestrated_by;
                    if (funcPanel && funcHtml) {
                        var badges = '';
                        if (isExecutionOnly) badges += '<span style="display:inline-block;margin:0 6px 6px 0;padding:4px 8px;background:#e8f5e9;color:#2e7d32;border-radius:4px;font-size:12px;font-weight:600;">EXECUTION ONLY</span>';
                        if (orchestratedBy) badges += '<span style="display:inline-block;margin:0 6px 6px 0;padding:4px 8px;background:#e3f2fd;color:#1565c0;border-radius:4px;font-size:12px;">Orchestrated by: ' + orchestratedBy + '</span>';
                        if (agents.length && agents[0]) badges += '<span style="display:inline-block;margin:0 6px 6px 0;padding:4px 8px;background:#f3e5f5;color:#6a1b9a;border-radius:4px;font-size:12px;">Executor: ' + (agents[0].name || '—') + '</span>';
                        if (badges) funcHtml = '<div style="margin-bottom:10px;">' + badges + '</div>' + funcHtml;
                        funcPanel.innerHTML = funcHtml;
                    } else if (funcPanel && !funcHtml) {
                        funcPanel.innerHTML = '<p>This workflow step describes part of the agent workflow process. Function details can be configured per deployment.</p>';
                    }
                    if (agentsPanel) {
                        agentsPanel.textContent = '';
                        if (agents.length) {
                            agentsPanel.innerHTML = '<ul style="margin:0;padding-left:1.2em;">' + agents.map(function (a) {
                                var roleBadge = a.role_type ? ' <span style="font-size:11px;color:#666;">(' + a.role_type + ')</span>' : '';
                                return '<li><strong>' + (a.name || '—') + '</strong>' + roleBadge + (a.role ? ' – ' + a.role : '') + '</li>';
                            }).join('') + '</ul>';
                        } else {
                            agentsPanel.textContent = 'No agents assigned to this step.';
                        }
                    }
                    if (llmsPanel) {
                        llmsPanel.textContent = '';
                        if (llms.length) {
                            llmsPanel.innerHTML = '<ul style="margin:0;padding-left:1.2em;">' + llms.map(function (m) { return '<li>' + m + '</li>'; }).join('') + '</ul>';
                        } else {
                            llmsPanel.textContent = 'No LLMs required for this step.';
                        }
                    }
                    if (toolsPanel) {
                        toolsPanel.textContent = '';
                        if (tools.length) {
                            toolsPanel.innerHTML = '<ul style="margin:0;padding-left:1.2em;">' + tools.map(function (t) { return '<li>' + t + '</li>'; }).join('') + '</ul>';
                        } else {
                            toolsPanel.textContent = 'No tools assigned to this step.';
                        }
                    }
                });
        }
    }
    function attachPyramidBandClicks(viewerEl) {
        if (!viewerEl) return;
        var handler = function (level) { return function (e) { e.preventDefault(); e.stopPropagation(); showBandInfo(level, e); }; };
        viewerEl.querySelectorAll('[id^="band-"]').forEach(function (el) {
            var id = el.getAttribute('id');
            var level = parseInt(id.replace('band-', ''), 10);
            if (level >= 1 && level <= 8) {
                el.addEventListener('click', handler(level));
                var next = el.nextElementSibling;
                if (next) {
                    next.style.cursor = 'pointer';
                    next.addEventListener('click', handler(level));
                    next = next.nextElementSibling;
                }
                if (next) {
                    next.style.cursor = 'pointer';
                    next.addEventListener('click', handler(level));
                }
            }
        });
    }
    function scaleChartToFitViewer(viewerEl) {
        if (!viewerEl) return;
        var dialog = viewerEl.closest && viewerEl.closest('.security-diagrams-dialog');
        if (!dialog || !dialog.classList.contains('security-diagrams-fullscreen')) return;
        var svg = viewerEl.querySelector('svg');
        if (!svg) return;
        try {
            var bbox = svg.getBBox();
            if (!bbox || bbox.width <= 0 || bbox.height <= 0) return;
            var pad = Math.min(bbox.width, bbox.height) * 0.02 || 1;
            var vx = bbox.x - pad;
            var vy = bbox.y - pad;
            var vw = bbox.width + 2 * pad;
            var vh = bbox.height + 2 * pad;
            svg.setAttribute('viewBox', vx + ' ' + vy + ' ' + vw + ' ' + vh);
            svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
            svg.setAttribute('width', '100%');
            svg.setAttribute('height', '100%');
            svg.removeAttribute('style');
        } catch (e) {}
    }
    /**
     * Apply workflow chart box styling (from workflow_chart_boxes_test):
     * - App background gradient fill for rect, ellipse, polyline
     * - Enhanced border (#8a9aac, 2.5px)
     * - Hide decorative colored offset lines (red, green, purple) but keep structural cls-19 stage dividers
     */
    function applyWorkflowChartBoxStyles(svgText, chartType) {
        chartType = chartType || 'workflow_2d';
        var gradient = '<linearGradient id="boxGrad" x1="0" y1="0" x2="1920" y2="1080" gradientUnits="userSpaceOnUse">' +
            '<stop offset="0%" stop-color="#f4f8fa"/>' +
            '<stop offset="40%" stop-color="#e8eef4"/>' +
            '<stop offset="100%" stop-color="#d0dce8"/>' +
            '</linearGradient>' +
            '<linearGradient id="workflowActiveBorderGrad" x1="0%" y1="0%" x2="100%" y2="100%" gradientUnits="objectBoundingBox">' +
            '<stop offset="0%" stop-color="#98FB98"/>' +
            '<stop offset="50%" stop-color="#7CFC00"/>' +
            '<stop offset="100%" stop-color="#32CD32"/>' +
            '</linearGradient>' +
            '<filter id="workflowActiveGlow" x="-40%" y="-40%" width="180%" height="180%" color-interpolation-filters="sRGB">' +
            '<feDropShadow dx="0" dy="0" stdDeviation="3" flood-color="#7CFC00" flood-opacity="0.85" result="glow1"/>' +
            '<feDropShadow dx="0" dy="0" stdDeviation="6" flood-color="#32CD32" flood-opacity="0.5" result="glow2"/>' +
            '</filter>';
        var baseHide = 'line.cls-9, line.cls-10, line.cls-13, line.cls-20, line.cls-31, line.cls-33, line.cls-34, line.cls-46, line.cls-19, line.cls-49, path.cls-9, path.cls-13, path.cls-14, path.cls-15, path.cls-33, polyline.cls-10, polyline.cls-46, polyline.cls-49';
        var isClipfarm = (chartType === 'workflow_clipfarm');
        var isWorkflowWithStages = (chartType === 'workflow_clipfarm' || chartType === 'workflow_2d' || chartType === 'workflow_3d');
        if (isClipfarm) {
            baseHide += ', line.cls-8, line.cls-9, line.cls-29';
        } else {
            baseHide += ', line.cls-14';
        }
        if (isWorkflowWithStages) {
            baseHide = baseHide.replace(/, line\.cls-20/g, '').replace(/, line\.cls-31/g, '').replace(/, line\.cls-33/g, '').replace(/, line\.cls-34/g, '');
            baseHide = baseHide.replace(/, line\.cls-14/g, '');
            baseHide = baseHide.replace(/, line\.cls-15/g, '');
        }
        if (chartType === 'workflow_2d') {
            /* Don't hide cls-46 (Error), cls-19 (Distribution), cls-33 (Media Overseer) - keep them visible with semantic colors */
            baseHide = baseHide.replace(/, line\.cls-46/g, '').replace(/, line\.cls-19/g, '');
        }
        if (chartType === 'workflow_distribution') {
            baseHide = baseHide.replace(/, line\.cls-19/g, '').replace(/, line\.cls-34/g, '').replace(/, line\.cls-10/g, '');
        }
        /* User request: do not remove/hide any lines - only modify colors. Keep all lines visible. */
        var hideOffsetLines = '';
        var rectOverride = 'rect, ellipse, polyline { fill: url(#boxGrad) !important; stroke: #8a9aac !important; stroke-width: 2.5px !important; }';
        if (isWorkflowWithStages) {
            rectOverride += ' rect.cls-31, rect.cls-33, rect.cls-46, rect.cls-19, rect.cls-10, rect.cls-55, rect.cls-49, rect.cls-58, polyline.cls-46, polyline.cls-10, polyline.cls-55, polyline.cls-49, ellipse.cls-33 { stroke: #8a9aac !important; }';
            /* For 2D: keep semantic line colors - cls-46 red (Error), cls-33 magenta (Media Overseer), cls-19 purple (Distribution). Only override others to grey. */
            if (chartType !== 'workflow_2d') {
                rectOverride += ' line.cls-46, line.cls-19, line.cls-49, line.cls-20 { stroke: #8a9aac !important; }';
            } else {
                rectOverride += ' line.cls-49, line.cls-20 { stroke: #8a9aac !important; }';
                /* Normal connector lines: use Sky gradients. Error/QC red. cls-33 and cls-19 column dividers: sky blue. */
                rectOverride += ' line.cls-4, line.cls-56, line.cls-23, line.cls-60 { stroke: url(#Sky) !important; }';
                rectOverride += ' line.cls-46 { stroke: #ed1c24 !important; }';
                rectOverride += ' line.cls-33, line.cls-19 { stroke: #87CEEB !important; }';
            }
        }
        var overrideStyle = '<style id="workflow-box-override">' +
            rectOverride +
            /* Active overlay — must win over the !important grey stroke from rectOverride */
            ' rect.workflow-active-border-overlay, ellipse.workflow-active-border-overlay {' +
            ' stroke: #00e676 !important; stroke-width: 4px !important; fill: none !important;' +
            ' stroke-dashoffset: 0; pointer-events: none !important;' +
            ' animation: cf-travel-dash var(--cf-duration, 2s) linear infinite !important; }' +
            ' @keyframes cf-travel-dash {' +
            ' from { stroke-dashoffset: 0; }' +
            ' to   { stroke-dashoffset: var(--cf-travel, -500); } }' +
            ' text, text.cls-52, text.cls-65, text.cls-68, text.cls-41, text.cls-44, text.cls-46 { fill: #2c3e50 !important; stroke: none !important; text-anchor: middle !important; dominant-baseline: central !important; }' +
            hideOffsetLines +
            '</style>';
        var injection = gradient + '\n    ' + overrideStyle + '\n    ';
        if (svgText.indexOf('<defs>') !== -1 && svgText.indexOf('<style>') !== -1) {
            svgText = svgText.replace(/(\s*<defs>\s*)(<style>)/, '$1' + injection + '$2');
        }
        return svgText;
    }
    var _workflowActiveAgentPollInterval = null;
    function fetchActiveAgentNames() {
        var names = {};
        function add(n) { if (n && typeof n === 'string') names[n.trim()] = true; }
        return Promise.all([
            fetch('/api/dashboard/monitoring_jobs').then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; }),
            fetch('/api/agents').then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; }),
            fetch('/api/workflow_status/active').then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; })
        ]).then(function (results) {
            var jobs = results[0];
            var agentsData = results[1];
            var pipelineActive = results[2];
            if (jobs && jobs.active && Array.isArray(jobs.active)) {
                jobs.active.forEach(function (j) { add(j.agent); });
            }
            if (agentsData && typeof agentsData === 'object') {
                var arr = Array.isArray(agentsData) ? agentsData : (agentsData.agents || agentsData.items || Object.values(agentsData));
                if (Array.isArray(arr)) {
                    arr.forEach(function (a) {
                        var ag = typeof a === 'object' ? a : { name: a };
                        if ((ag.current_tasks != null && ag.current_tasks !== 0 && ag.current_tasks !== '0' && ag.current_tasks !== '')) {
                            add(ag.name);
                        }
                    });
                } else if (typeof agentsData === 'object') {
                    for (var k in agentsData) {
                        var v = agentsData[k];
                        if (v && typeof v === 'object' && (v.current_tasks != null && v.current_tasks !== 0 && v.current_tasks !== '0' && v.current_tasks !== '')) {
                            add(v.name || k);
                        }
                    }
                }
            }
            /* Clipfarm pipeline active agents — from staged pipeline coordinator */
            if (pipelineActive && Array.isArray(pipelineActive.active_agents)) {
                pipelineActive.active_agents.forEach(function (n) { add(n); });
            }
            return Object.keys(names);
        });
    }
    function isAgentNameMatch(boxName, activeName) {
        if (!boxName || !activeName) return false;
        // Strip dashes/underscores/spaces and lowercase for comparison
        function norm(s) { return String(s).trim().toLowerCase().replace(/[-_\s]+/g, ''); }
        var bn = norm(boxName);
        var an = norm(activeName);
        // Exact match only (after normalisation removes punctuation/spacing differences)
        return bn === an;
    }
    function updateWorkflowActiveBoxes(activeAgentNames) {
        var viewerEl = byId('security-diagrams-3d-viewer');
        if (!viewerEl || !viewerEl.getAttribute('data-workflow-chart')) return;
        var svg = viewerEl.querySelector('svg');
        if (!svg) return;
        var defs = svg.querySelector('defs');
        if (!defs || !defs.querySelector('#workflowActiveBorderGrad') || !defs.querySelector('#workflowActiveGlow')) return;
        var boxes = svg.querySelectorAll('rect[data-agent-name], ellipse[data-agent-name]');
        boxes.forEach(function (box) {
            var agentName = box.getAttribute('data-agent-name');
            var isActive = activeAgentNames.some(function (a) { return isAgentNameMatch(agentName, a); });
            var overlay = box.nextElementSibling;
            if (overlay && overlay.classList && overlay.classList.contains('workflow-active-border-overlay')) {
                if (!isActive) {
                    overlay.parentNode.removeChild(overlay);
                }
                return;
            }
            if (!isActive) return;
            var parent = box.parentNode;
            if (!parent) return;
            var overlayEl;
            var perimeter = 0;
            var tag = box.tagName ? box.tagName.toLowerCase() : '';
            if (tag === 'rect') {
                var x = parseFloat(box.getAttribute('x')) || 0;
                var y = parseFloat(box.getAttribute('y')) || 0;
                var w = parseFloat(box.getAttribute('width')) || 0;
                var h = parseFloat(box.getAttribute('height')) || 0;
                var pad = 2;
                overlayEl = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
                overlayEl.setAttribute('x', x - pad);
                overlayEl.setAttribute('y', y - pad);
                overlayEl.setAttribute('width', w + 2 * pad);
                overlayEl.setAttribute('height', h + 2 * pad);
                perimeter = 2 * ((w + 2 * pad) + (h + 2 * pad));
            } else if (tag === 'ellipse') {
                var cx = parseFloat(box.getAttribute('cx')) || 0;
                var cy = parseFloat(box.getAttribute('cy')) || 0;
                var rx = (parseFloat(box.getAttribute('rx')) || 0) + 2;
                var ry = (parseFloat(box.getAttribute('ry')) || 0) + 2;
                overlayEl = document.createElementNS('http://www.w3.org/2000/svg', 'ellipse');
                overlayEl.setAttribute('cx', cx);
                overlayEl.setAttribute('cy', cy);
                overlayEl.setAttribute('rx', rx);
                overlayEl.setAttribute('ry', ry);
                /* Ramanujan ellipse perimeter approximation */
                perimeter = Math.PI * (3 * (rx + ry) - Math.sqrt((3 * rx + ry) * (rx + 3 * ry)));
            } else {
                return;
            }
            /* Dash = 18% of perimeter, gap = remaining so exactly one dash is visible */
            var dash = Math.round(perimeter * 0.18);
            var gap = Math.round(perimeter - dash);
            var duration = (perimeter / 260).toFixed(2); /* ~260 px/s travel speed */
            overlayEl.setAttribute('class', 'workflow-active-border-overlay');
            overlayEl.setAttribute('fill', 'none');
            overlayEl.setAttribute('stroke', '#00e676');
            overlayEl.setAttribute('stroke-width', '4');
            overlayEl.setAttribute('stroke-dashoffset', '0');
            overlayEl.setAttribute('filter', 'url(#workflowActiveGlow)');
            overlayEl.style.strokeDasharray = dash + ' ' + gap;
            overlayEl.style.strokeDashoffset = '0';
            overlayEl.style.setProperty('--cf-travel', '-' + perimeter.toFixed(1));
            overlayEl.style.setProperty('--cf-duration', duration + 's');
            parent.insertBefore(overlayEl, box.nextSibling);
        });
    }
    function startWorkflowActiveAgentPolling() {
        stopWorkflowActiveAgentPolling();
        function poll() {
            fetchActiveAgentNames().then(function (names) {
                updateWorkflowActiveBoxes(names);
            });
        }
        poll();
        _workflowActiveAgentPollInterval = setInterval(poll, 4000);
    }
    function stopWorkflowActiveAgentPolling() {
        if (_workflowActiveAgentPollInterval) {
            clearInterval(_workflowActiveAgentPollInterval);
            _workflowActiveAgentPollInterval = null;
        }
        var viewerEl = byId('security-diagrams-3d-viewer');
        if (viewerEl) {
            var svg = viewerEl.querySelector('svg');
            if (svg) {
                svg.querySelectorAll('.workflow-active-border-overlay').forEach(function (el) {
                    if (el.parentNode) el.parentNode.removeChild(el);
                });
            }
        }
    }
    function loadViewerContentForDiagram(diagramId) {
        var viewerEl = byId('security-diagrams-3d-viewer');
        var placeholderEl = byId('security-diagrams-3d-viewer-placeholder');
        if (!viewerEl) return;
        if (placeholderEl) placeholderEl.style.display = 'none';
        viewerEl.innerHTML = '';
        viewerEl.classList.remove('viewer-has-panel');
        if (typeof stopWorkflowActiveAgentPolling === 'function') stopWorkflowActiveAgentPolling();
        if (diagramId === 'password') {
            viewerEl.removeAttribute('data-workflow-chart');
            fetch('/static/security_diagrams/authentication_pyramid_3d.svg').then(function (r) { return r.text(); }).then(function (svgText) {
                svgText = svgText.replace('href="digital_shield_transparent.png"', 'href="/static/security_diagrams/digital_shield_transparent.png"');
                viewerEl.innerHTML = svgText;
                attachPyramidBandClicks(viewerEl);
                requestAnimationFrame(function () { scaleChartToFitViewer(viewerEl); });
            }).catch(function () {
                viewerEl.innerHTML = '<object data="/static/security_diagrams/authentication_pyramid_3d.svg" type="image/svg+xml" style="width:100%;height:100%;display:block;min-height:400px;" aria-label="Authentication 8-level pyramid"></object>';
            });
        } else if (diagramId === 'workflow') {
            var chartType = window._selectedWorkflowChart || 'workflow_2d';
            var isFeedback = chartType === 'feedback_2d' || chartType === 'feedback_3d' || chartType === 'feedback_distribution';
            if (isFeedback) {
                viewerEl.removeAttribute('data-workflow-chart');
                viewerEl.innerHTML = '<div style="padding:60px 40px;text-align:center;color:#666;font-size:1rem;line-height:1.5;">Not visible in portfolio or under construction.</div>';
            } else if (chartType === 'workflow_distribution') {
                viewerEl.setAttribute('data-workflow-chart', chartType);
                var distPath = '/static/security_diagrams/workflow_distribution.svg?v=' + (Date.now ? Date.now() : 0);
                Promise.all([
                    fetch(distPath).then(function (r) { return r.text(); }),
                    getWorkflowBoxIdsMapping()
                ]).then(function (results) {
                    var svgText = results[0];
                    var boxIdsMapping = results[1];
                    svgText = applyWorkflowChartBoxStyles(svgText, 'workflow_distribution');
                    viewerEl.innerHTML = svgText;
                    var svg = viewerEl.querySelector('svg');
                    if (svg) {
                        svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
                        svg.setAttribute('style', 'max-width:100%; max-height:100%; width:auto; height:auto; display:block; margin:auto;');
                        assignWorkflowBoxIds(svg, 'workflow_distribution', boxIdsMapping);
                        centerWorkflowBoxText(svg);
                        ensureWorkflowTextOnTop(svg);
                    }
                    attachWorkflowSvgBoxClicks(viewerEl);
                    requestAnimationFrame(function () { scaleChartToFitViewer(viewerEl); });
                    if (typeof startWorkflowActiveAgentPolling === 'function') startWorkflowActiveAgentPolling();
                    stopClipfarmMetricCircles();
                }).catch(function () {
                    viewerEl.innerHTML = '<object data="' + distPath + '" type="image/svg+xml" style="width:100%;max-width:100%;height:auto;display:block;min-height:400px;object-fit:contain;" aria-label="Distribution Chart"></object>';
                });
            } else {
                var svgMap = { workflow_2d: 'workflow_2d.svg', workflow_3d: 'workflow_3d.svg', workflow_maintenance: 'workflow_maintenance.svg', workflow_clipfarm: 'workflow_clipfarm.svg', workflow_channels: 'workflow_channels.svg' };
                var svgPath = '/static/security_diagrams/' + (svgMap[chartType] || 'workflow_2d.svg');
                var svgUrl = svgPath + '?v=' + (Date.now ? Date.now() : 0);
                Promise.all([
                    fetch(svgUrl).then(function (r) { return r.text(); }),
                    getWorkflowBoxIdsMapping()
                ]).then(function (results) {
                    var svgText = results[0];
                    var boxIdsMapping = results[1];
                    svgText = applyWorkflowChartBoxStyles(svgText, chartType);
                    viewerEl.innerHTML = svgText;
                    viewerEl.setAttribute('data-workflow-chart', chartType);
                    var svg = viewerEl.querySelector('svg');
                    if (svg) {
                        svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
                        svg.setAttribute('style', 'max-width:100%; max-height:100%; width:auto; height:auto; display:block; margin:auto;');
                        assignWorkflowBoxIds(svg, chartType, boxIdsMapping);
                        centerWorkflowBoxText(svg);
                        ensureWorkflowTextSharp(svg);
                        ensureWorkflowTextOnTop(svg);
                    }
                    attachWorkflowSvgBoxClicks(viewerEl);
                    requestAnimationFrame(function () { scaleChartToFitViewer(viewerEl); });
                    if (typeof startWorkflowActiveAgentPolling === 'function') startWorkflowActiveAgentPolling();
                    if (chartType === 'workflow_clipfarm') injectClipfarmMetricCircles();
                }).catch(function () {
                    viewerEl.setAttribute('data-workflow-chart', chartType);
                    viewerEl.innerHTML = '<object data="' + svgPath + '" type="image/svg+xml" style="width:100%;max-width:100%;height:auto;display:block;min-height:400px;" aria-label="Workflow Chart"></object>';
                });
            }
        } else {
            stopClipfarmMetricCircles();
            viewerEl.removeAttribute('data-workflow-chart');
            viewerEl.innerHTML = '<div style="padding:24px;color:#666;font-size:0.95rem;text-align:center;">Select Workflow or Authentication tab for expanded diagram view.</div>';
        }
    }

    var _cfMetricInterval = null;

    function stopClipfarmMetricCircles() {
        if (_cfMetricInterval) { clearInterval(_cfMetricInterval); _cfMetricInterval = null; }
        var old = document.getElementById('cf-metric-circles-overlay');
        if (old) old.parentNode.removeChild(old);
    }

    /* GPU hover breakdown for the Clipfarm rings — same content as the Workflows
       board panel (kanban_assets/kanban_main.js), themed light for this dashboard.
       The overlay sets pointer-events:none so it never blocks the 3D viewer, so the
       GPU circle re-enables them on itself to become hoverable. */
    function ensureCfMetricPopStyles() {
        if (document.getElementById('cf-metric-pop-styles')) return;
        var st = document.createElement('style');
        st.id = 'cf-metric-pop-styles';
        st.textContent = [
            '.cf-metric-circle { pointer-events: auto; }',
            '.cf-metric-pop { position:absolute; top:146px; left:0; width:340px; padding:11px 13px 9px;',
            '  background:#fbfaf8; border:1px solid #cfc9c1; border-radius:9px;',
            '  box-shadow:0 12px 34px rgba(40,36,32,0.28); color:#4a453e; font-size:11.5px;',
            '  line-height:1.45; text-align:left; z-index:40; opacity:0; visibility:hidden;',
            '  transform:translateY(-4px); transition:opacity .12s ease, transform .12s ease, visibility .12s;',
            '  pointer-events:none; font-weight:400; }',
            '.cf-metric-circle:hover .cf-metric-pop { opacity:1; visibility:visible; transform:translateY(0); }',
            '.cf-pop-title { font-weight:700; font-size:11px; letter-spacing:.04em; text-transform:uppercase;',
            '  color:#6f675d; margin-bottom:7px; }',
            '.cf-pop-stats { display:grid; grid-template-columns:84px 1fr; gap:2px 10px; margin:0 0 7px; }',
            '.cf-pop-stats dt { color:#8a827a; }',
            '.cf-pop-stats dd { margin:0; color:#3a352f; }',
            '.cf-pop-strong { font-weight:700; font-size:13px; color:#1f6f4a; }',
            '.cf-pop-dim { color:#9a938a; }',
            '.cf-pop-note { margin:0 0 7px; padding:6px 8px; border-left:3px solid #b0a898;',
            '  background:#f1eee9; border-radius:0 4px 4px 0; color:#5b544c; }',
            '.cf-pop-table { width:100%; border-collapse:collapse; font-size:11px; }',
            '.cf-pop-table th { text-align:right; font-weight:600; color:#8a827a;',
            '  border-bottom:1px solid #ddd7cf; padding:3px 0 4px; }',
            '.cf-pop-table th:first-child { text-align:left; }',
            '.cf-pop-table th + th { padding-left:10px; }',
            '.cf-pop-table td { padding:3px 0; border-bottom:1px solid #efebe5; }',
            '.cf-pop-table tr:last-child td { border-bottom:none; }',
            '.cf-pop-proc { color:#3a352f; max-width:176px; overflow:hidden;',
            '  text-overflow:ellipsis; white-space:nowrap; }',
            '.cf-pop-num { text-align:right; font-variant-numeric:tabular-nums; padding-left:10px; }'
        ].join('\n');
        document.head.appendChild(st);
    }

    function cfFmtVram(mb) {
        if (mb == null || mb <= 0) return '—';
        return mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB' : Math.round(mb) + ' MB';
    }

    function renderCfGpuBreakdown(g) {
        var el = document.getElementById('cf-metric-gpu-pop');
        if (!el) return;
        if (!g) {
            el.innerHTML = '<div class="cf-pop-title">GPU — where it\'s going</div>'
                         + '<div class="cf-pop-note">Telemetry unreachable.</div>';
            return;
        }
        var duty = g.utilization_pct != null ? g.utilization_pct : 0;
        var cap  = g.capacity_pct != null ? g.capacity_pct : duty;
        var clkTxt = (g.clock_sm_mhz != null && g.clock_sm_max_mhz)
            ? g.clock_sm_mhz + ' / ' + g.clock_sm_max_mhz + ' MHz' : '—';
        var pwrTxt = (g.power_w != null)
            ? g.power_w.toFixed(1) + ' / ' + (g.power_limit_w != null ? Math.round(g.power_limit_w) : '?') + ' W'
            : '—';
        var idleClocks = (g.clock_pct != null && g.clock_pct < 25 && duty >= 10);
        var rows = (g.processes || []).map(function (p) {
            return '<tr><td class="cf-pop-proc" title="pid ' + p.pid + '">' + p.label + '</td>'
                 + '<td class="cf-pop-num">' + (p.sm_pct > 0 ? p.sm_pct + '%' : '—') + '</td>'
                 + '<td class="cf-pop-num">' + (p.dec_pct > 0 ? p.dec_pct + '%' : '—') + '</td>'
                 + '<td class="cf-pop-num">' + cfFmtVram(p.vram_mb) + '</td></tr>';
        }).join('');
        el.innerHTML =
            '<div class="cf-pop-title">GPU — where it\'s going</div>'
          + '<dl class="cf-pop-stats">'
          + '<dt>Capacity used</dt><dd class="cf-pop-strong">' + cap.toFixed(1) + '%</dd>'
          + '<dt>Duty cycle</dt><dd>' + duty.toFixed(1) + '% <span class="cf-pop-dim">time with a kernel resident</span></dd>'
          + '<dt>SM clock</dt><dd>' + clkTxt
          + (g.clock_pct != null ? ' <span class="cf-pop-dim">(' + g.clock_pct.toFixed(1) + '% of max)</span>' : '') + '</dd>'
          + '<dt>Power</dt><dd>' + pwrTxt + '</dd></dl>'
          + (idleClocks ? '<div class="cf-pop-note">Card is at idle clocks. The duty cycle reads high '
             + 'because work at ' + g.clock_sm_mhz + ' MHz occupies more of each sample window — '
             + 'capacity used is ' + cap.toFixed(1) + '%.</div>' : '')
          + '<table class="cf-pop-table"><thead><tr><th>Process</th><th>SM</th><th>Dec</th><th>VRAM</th></tr></thead>'
          + '<tbody>' + (rows || '<tr><td colspan="4" class="cf-pop-dim">No process is holding the GPU.</td></tr>')
          + '</tbody></table>';
    }

    function injectClipfarmMetricCircles() {
        stopClipfarmMetricCircles();
        var wrap = byId('security-diagrams-3d-viewer-wrap');
        if (!wrap) return;
        ensureCfMetricPopStyles();

        var overlay = document.createElement('div');
        overlay.id = 'cf-metric-circles-overlay';
        overlay.style.cssText = 'position:absolute;top:12px;right:12px;display:flex;flex-direction:row;gap:10px;z-index:20;pointer-events:none;';

        function makeCircle(idPrefix, label) {
            var w = document.createElement('div');
            w.style.cssText = 'position:relative;width:120px;height:140px;text-align:center;';
            var svgNS = 'http://www.w3.org/2000/svg';
            var svg = document.createElementNS(svgNS, 'svg');
            svg.setAttribute('viewBox', '0 0 120 120');
            svg.setAttribute('width', '120');
            svg.setAttribute('height', '120');
            svg.style.cssText = 'display:block;';
            svg.classList.add('dashboard-circle-svg');
            var defs = document.createElementNS(svgNS, 'defs');
            defs.innerHTML = '<linearGradient id="cfMetricGrad_' + idPrefix + '" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#b0a898"/><stop offset="100%" stop-color="#8a8278"/></linearGradient>';
            svg.appendChild(defs);
            var bg = document.createElementNS(svgNS, 'circle');
            bg.setAttribute('cx', '60'); bg.setAttribute('cy', '60'); bg.setAttribute('r', '50');
            bg.classList.add('dashboard-circle-bg');
            svg.appendChild(bg);
            var mover = document.createElementNS(svgNS, 'circle');
            mover.setAttribute('cx', '60'); mover.setAttribute('cy', '60'); mover.setAttribute('r', '50');
            mover.classList.add('dashboard-circle-mover');
            svg.appendChild(mover);
            var fill = document.createElementNS(svgNS, 'circle');
            fill.setAttribute('cx', '60'); fill.setAttribute('cy', '60'); fill.setAttribute('r', '50');
            fill.setAttribute('stroke-dasharray', '314');
            fill.setAttribute('stroke-dashoffset', '314');
            fill.classList.add('dashboard-circle-fill');
            fill.id = 'cf-metric-' + idPrefix + '-fill';
            svg.appendChild(fill);
            w.appendChild(svg);
            var val = document.createElement('span');
            val.classList.add('dashboard-circle-value');
            val.id = 'cf-metric-' + idPrefix + '-value';
            val.style.cssText = 'position:absolute;left:0;right:0;top:0;height:120px;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:bold;flex-direction:column;line-height:1.3;';
            val.innerHTML = '<span style="font-size:13px;font-weight:700;">' + label + '</span>'
                          + '<span id="cf-metric-' + idPrefix + '-num">—</span>'
                          + '<span id="cf-metric-' + idPrefix + '-temp" style="font-size:11px;font-weight:500;opacity:0.75;">—°C</span>'
                          + '<span id="cf-metric-' + idPrefix + '-rpm" style="font-size:10px;font-weight:400;opacity:0.6;">— RPM</span>';
            w.appendChild(val);
            var lbl = document.createElement('span');
            lbl.classList.add('dashboard-circle-label');
            lbl.style.cssText = 'position:absolute;top:125px;left:0;right:0;font-size:11px;display:none;';
            lbl.textContent = label + ' Usage';
            w.appendChild(lbl);
            if (idPrefix === 'gpu') {
                w.classList.add('cf-metric-circle');
                var pop = document.createElement('div');
                pop.id = 'cf-metric-gpu-pop';
                pop.className = 'cf-metric-pop';
                w.appendChild(pop);
            }
            return w;
        }

        overlay.appendChild(makeCircle('gpu', 'GPU'));
        overlay.appendChild(makeCircle('cpu', 'CPU'));
        overlay.appendChild(makeCircle('vram', 'VRAM'));
        wrap.appendChild(overlay);

        // Add purple gradient for VRAM circle
        (function() {
            var vramFill = document.getElementById('cf-metric-vram-fill');
            if (vramFill) {
                var svgNS = 'http://www.w3.org/2000/svg';
                var parentSvg = vramFill.closest('svg');
                if (parentSvg) {
                    var defs = parentSvg.querySelector('defs');
                    if (!defs) { defs = document.createElementNS(svgNS, 'defs'); parentSvg.insertBefore(defs, parentSvg.firstChild); }
                    defs.innerHTML += '<linearGradient id="cfVramGrad" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#a855f7"/><stop offset="100%" stop-color="#3b82f6"/></linearGradient>';
                    vramFill.setAttribute('stroke', 'url(#cfVramGrad)');
                }
            }
        })();

        function updateCircles() {
            fetch('/api/telemetry').then(function(r){ return r.json(); }).then(function(d) {
                /* capacity_pct = NVML duty cycle x (SM clock / max SM clock). The raw
                   utilization_pct reads ~30% on an idle downclocked card, which is not
                   load; keep this ring agreeing with the Workflows ring. */
                var g0 = (d.gpus && d.gpus[0]) || null;
                var gpuPct = g0 ? Math.round((g0.capacity_pct != null ? g0.capacity_pct : g0.utilization_pct) * 10) / 10 : 0;
                renderCfGpuBreakdown(g0);
                var gpuTemp = (d.gpus && d.gpus[0] && d.gpus[0].temperature_c != null) ? Math.round(d.gpus[0].temperature_c * 10) / 10 : null;
                var cpuPct = Math.round((d.cpu_pct || 0) * 10) / 10;
                var cpuTemp = (d.cpu_temp_c != null) ? Math.round(d.cpu_temp_c * 10) / 10 : null;
                var CPU_MAX = 2400; // 24 cores × 100%
                var CPU_CAP = 2000; // arc fills to 100% at this value

                var gpuFill = document.getElementById('cf-metric-gpu-fill');
                var gpuNum = document.getElementById('cf-metric-gpu-num');
                var gpuTempEl = document.getElementById('cf-metric-gpu-temp');
                var gpuRpmEl = document.getElementById('cf-metric-gpu-rpm');
                var gpuFanPct = (d.gpus && d.gpus[0] && d.gpus[0].fan_pct != null) ? d.gpus[0].fan_pct : null;
                if (gpuFill) gpuFill.setAttribute('stroke-dashoffset', String(314 * (1 - gpuPct / 100)));
                if (gpuNum) gpuNum.textContent = gpuPct.toFixed(1) + '/100%';
                if (gpuTempEl) gpuTempEl.textContent = gpuTemp !== null ? gpuTemp.toFixed(1) + '°C' : '—°C';
                if (gpuRpmEl) gpuRpmEl.textContent = gpuFanPct !== null ? gpuFanPct + '% Fan' : '— Fan';

                var cpuFill = document.getElementById('cf-metric-cpu-fill');
                var cpuNum = document.getElementById('cf-metric-cpu-num');
                var cpuTempEl = document.getElementById('cf-metric-cpu-temp');
                var cpuRpmEl = document.getElementById('cf-metric-cpu-rpm');
                var cpuFanRpm = d.cpu_fan_rpm != null ? d.cpu_fan_rpm : null;
                var cpuArcPct = Math.min(cpuPct / CPU_CAP, 1);
                if (cpuFill) cpuFill.setAttribute('stroke-dashoffset', String(314 * (1 - cpuArcPct)));
                if (cpuNum) cpuNum.textContent = cpuPct.toFixed(1) + '/' + CPU_MAX + '%';
                if (cpuTempEl) cpuTempEl.textContent = cpuTemp !== null ? cpuTemp.toFixed(1) + '°C' : '—°C';
                // Show fan RPM if available, otherwise show CPU frequency in GHz
                if (cpuRpmEl) {
                    if (cpuFanRpm !== null) {
                        cpuRpmEl.textContent = cpuFanRpm + ' RPM';
                    } else if (d.cpu_freq_mhz != null) {
                        cpuRpmEl.textContent = (d.cpu_freq_mhz / 1000).toFixed(2) + ' GHz';
                    } else {
                        cpuRpmEl.textContent = '— GHz';
                    }
                }

                // VRAM circle
                var vramFill2 = document.getElementById('cf-metric-vram-fill');
                var vramNum   = document.getElementById('cf-metric-vram-num');
                var vramTemp  = document.getElementById('cf-metric-vram-temp');
                var vramRpm   = document.getElementById('cf-metric-vram-rpm');
                if (d.gpus && d.gpus[0]) {
                    var usedMB  = d.gpus[0].memory_used_mb  || 0;
                    var totalMB = d.gpus[0].memory_total_mb || 49140;
                    var vramPct = Math.min(100, usedMB / totalMB * 100);
                    if (vramFill2) {
                        vramFill2.setAttribute('stroke-dashoffset', String(314 * (1 - vramPct / 100)));
                        vramFill2.setAttribute('stroke', 'url(#cfVramGrad)');
                    }
                    if (vramNum)  vramNum.textContent  = (usedMB / 1024).toFixed(1) + '/' + Math.round(totalMB / 1024) + 'G';
                    if (vramTemp) vramTemp.textContent = vramPct.toFixed(1) + '%';
                    if (vramRpm)  vramRpm.textContent  = '';
                }
            }).catch(function(){ renderCfGpuBreakdown(null); });
        }
        updateCircles();
        _cfMetricInterval = setInterval(updateCircles, 1000);
    }

    function enterSecurityDiagramsFullscreen() {
        var dialog = byId('security-diagrams-dialog');
        var modal = byId('security-diagrams-modal');
        if (dialog) {
            if (window.history && window.history.pushState) {
                history.pushState({ securityDiagramsExpanded: true }, '', window.location.pathname + window.location.search);
            }
            dialog.classList.add('security-diagrams-fullscreen');
            document.body.classList.add('security-diagrams-expanded');
            if (modal) modal.classList.add('security-diagrams-expanded');
            var activeTab = document.querySelector('.security-diagram-tab.active');
            var diagramId = activeTab ? activeTab.getAttribute('data-diagram') : '';
            loadViewerContentForDiagram(diagramId);
            if (securityDiagramsF11Handler) document.removeEventListener('keydown', securityDiagramsF11Handler, true);
            securityDiagramsF11Handler = function (e) {
                if (e.key === 'F11' || e.keyCode === 122) {
                    e.preventDefault();
                    exitSecurityDiagramsFullscreen();
                }
            };
            document.addEventListener('keydown', securityDiagramsF11Handler, true);
        }
    }
    function exitSecurityDiagramsFullscreen() {
        closeBandInfo();
        document.body.classList.remove('security-diagrams-expanded');
        var modal = byId('security-diagrams-modal');
        if (modal) modal.classList.remove('security-diagrams-expanded');
        var dialog = byId('security-diagrams-dialog');
        if (dialog) dialog.classList.remove('security-diagrams-fullscreen');
        if (securityDiagramsF11Handler) {
            document.removeEventListener('keydown', securityDiagramsF11Handler, true);
            securityDiagramsF11Handler = null;
        }
    }
    if (typeof window !== 'undefined') {
        window.closeSecurityDiagramsModal = closeSecurityDiagramsModal;
        window.SecurityDiagramsViewer = {
            render3D: function (data, layout, config) {
                var el = byId('security-diagrams-3d-viewer');
                var placeholder = byId('security-diagrams-3d-viewer-placeholder');
                if (!el) return;
                if (placeholder) placeholder.style.display = 'none';
                if (typeof Plotly !== 'undefined') {
                    Plotly.newPlot(el, data || [], layout || {}, config || { responsive: true });
                }
            },
            clear: function () {
                var el = byId('security-diagrams-3d-viewer');
                var placeholder = byId('security-diagrams-3d-viewer-placeholder');
                if (el && typeof Plotly !== 'undefined') Plotly.purge(el);
                if (placeholder) placeholder.style.display = '';
            }
        };
    }
    function updateWorkflowPanelDisplay() {
        var chart = window._selectedWorkflowChart;
        var isFullscreen = false;
        var dialog = byId('security-diagrams-dialog');
        if (dialog) isFullscreen = dialog.classList.contains('security-diagrams-fullscreen');
        var placeholder = byId('security-diagram-workflow-placeholder');
        var expandBtn = byId('security-diagram-workflow-expand-btn');
        var chartArea = byId('security-diagram-workflow-chart-area');
        var svgWrap = chartArea ? chartArea.querySelector('.workflow-chart-2d') : null;
        var isFeedback = chart === 'feedback_2d' || chart === 'feedback_3d' || chart === 'feedback_distribution';
        if (!chart) {
            if (placeholder) { placeholder.style.display = 'block'; placeholder.textContent = 'Select a chart from the Workflow list.'; }
            if (expandBtn) expandBtn.style.display = 'none';
            if (svgWrap) svgWrap.style.display = 'none';
        } else if (isFullscreen && isFeedback) {
            if (placeholder) placeholder.style.display = 'none';
            if (expandBtn) expandBtn.style.display = 'none';
            if (svgWrap) svgWrap.style.display = 'none';
        } else if (isFullscreen) {
            if (placeholder) placeholder.style.display = 'none';
            if (expandBtn) expandBtn.style.display = 'none';
            if (svgWrap) svgWrap.style.display = (chart === 'workflow_2d' ? 'block' : 'none');
        } else {
            if (placeholder) {
                placeholder.style.display = isFeedback ? 'block' : 'none';
                placeholder.textContent = isFeedback ? 'Not visible in portfolio or under construction.' : 'Select a chart from the Workflow list.';
            }
            if (expandBtn) expandBtn.style.display = isFeedback ? 'none' : 'block';
            if (svgWrap) svgWrap.style.display = 'none';
        }
    }
    function switchSecurityDiagramTab(diagramId) {
        var dialog = byId('security-diagrams-dialog');
        if (dialog && dialog.classList.contains('security-diagrams-fullscreen')) {
            if (diagramId !== 'workflow' && diagramId !== 'password') {
                exitSecurityDiagramsFullscreen();
            }
        }
        if (diagramId !== 'workflow') {
            var sublist = byId('security-diagram-workflow-sublist');
            if (sublist) sublist.style.display = 'none';
        }
        document.querySelectorAll('.security-diagram-panel').forEach(function (el) { el.style.display = 'none'; });
        document.querySelectorAll('.security-diagram-tab').forEach(function (el) { el.classList.remove('active'); });
        var panel = byId('security-diagram-' + diagramId);
        if (panel) panel.style.display = 'block';
        if (diagramId === 'web') ensureWebSecurityDiagramRendered();
        var tab = document.querySelector('.security-diagram-tab[data-diagram="' + diagramId + '"]');
        if (tab) tab.classList.add('active');
        if (diagramId === 'workflow') updateWorkflowPanelDisplay();
        var contentEl = byId('security-diagram-content');
        if (contentEl) {
            if (diagramId === 'web') contentEl.classList.add('security-diagram-active-web');
            else contentEl.classList.remove('security-diagram-active-web');
        }
        var dialog = byId('security-diagrams-dialog');
        if (dialog && dialog.classList.contains('security-diagrams-fullscreen') && (diagramId === 'workflow' || diagramId === 'password')) {
            loadViewerContentForDiagram(diagramId);
        }
    }
    function applyBoustrophedonFlow(flowEl) {
        if (!flowEl || !flowEl.parentElement) return;
        var items = [];
        flowEl.classList.remove('flow-boustrophedon');
        var rows = flowEl.querySelectorAll('.flow-row, .flow-u-connector');
        if (rows.length) {
            rows.forEach(function (row) {
                if (row.classList.contains('flow-row')) {
                    [].slice.call(row.childNodes).forEach(function (c) {
                        if (c.nodeType === 1 && c.classList && c.classList.contains('diagram-arrow')) {
                            c.classList.remove('diagram-arrow-reversed');
                        }
                        items.push(c);
                    });
                }
                row.remove();
            });
        } else {
            [].slice.call(flowEl.childNodes).forEach(function (c) { items.push(c); });
        }
        if (items.length === 0) return;
        var steps = [];
        var i = 0;
        while (i < items.length) {
            var step = [items[i]];
            i++;
            if (i < items.length && items[i].nodeType === 1 && items[i].classList && items[i].classList.contains('diagram-arrow')) {
                step.push(items[i]);
                i++;
            }
            steps.push(step);
        }
        var w = flowEl.offsetWidth || flowEl.parentElement.offsetWidth || 600;
        var perRow = Math.max(2, Math.min(steps.length, Math.floor(w / DIAGRAM_LAYOUT.STEP_WIDTH_AVG)));
        var rowIdx = 0;
        for (var s = 0; s < steps.length; s += perRow) {
            var rowSteps = steps.slice(s, s + perRow);
            if (rowSteps.length === 0) continue;
            var rowItems = [];
            rowSteps.forEach(function (st) { st.forEach(function (it) { rowItems.push(it); }); });
            if (rowIdx % 2 === 1) {
                rowItems.reverse();
                rowItems.forEach(function (node) {
                    if (node.nodeType === 1 && node.classList && node.classList.contains('diagram-arrow')) {
                        node.classList.add('diagram-arrow-reversed');
                    }
                });
            }
            var rowDiv = document.createElement('div');
            rowDiv.className = 'flow-row' + (rowIdx % 2 === 1 ? ' flow-row-reversed' : '');
            rowItems.forEach(function (n) { rowDiv.appendChild(n); });
            flowEl.appendChild(rowDiv);
            flowEl.classList.add('flow-boustrophedon');
            if (rowIdx === 0 && steps.length > perRow) {
                var u = document.createElement('div');
                u.className = 'flow-u-connector';
                var vb = DIAGRAM_LAYOUT.U_VIEWBOX;
                var uw = DIAGRAM_LAYOUT.U_DISPLAY_W;
                var uh = DIAGRAM_LAYOUT.U_DISPLAY_H;
                u.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="' + vb.x + ' ' + vb.y + ' ' + vb.w + ' ' + vb.h + '" width="' + uw + '" height="' + uh + '" fill="none" stroke="#667eea" stroke-width="2" stroke-miterlimit="10" preserveAspectRatio="xMidYMid meet" style="display:block;margin:0 auto"><path d="M464,295c58.07-5.41,42.66,30.43-.93,32.33"/><path fill="#667eea" d="M458,295c5.68-2.11,12.73-5.7,17.09-9.51l-3.44,9.51,3.44,9.51c-4.37-3.81-11.42-7.4-17.09-9.51Z"/><path fill="#667eea" d="M451,327c5.72-2,12.84-5.45,17.28-9.17l-3.63,9.44,3.25,9.58c-4.29-3.89-11.27-7.63-16.9-9.84Z"/></svg>';
                u.setAttribute('aria-hidden', 'true');
                flowEl.appendChild(u);
            }
            rowIdx++;
        }
    }
    function showSettingsMainView() {
        var main = byId('dashboard-settings-main');
        var styles = byId('dashboard-settings-styles');
        var usersView = byId('dashboard-settings-users');
        var myAccountView = byId('dashboard-settings-my-account');
        var apiView = byId('dashboard-settings-api');
        var langView = byId('dashboard-settings-languages');
        var securityView = byId('dashboard-settings-security');
        var loginMethodsView = byId('dashboard-settings-login-methods');
        var loginMethodFormView = byId('dashboard-settings-login-method-form');
        var billingView = byId('dashboard-settings-billing');
        var hotkeysView = byId('dashboard-settings-hotkeys');
        var voiceAssistantView = byId('dashboard-settings-voice-assistant');
        var voicesView = byId('dashboard-settings-voices');
        if (main) main.style.setProperty('display', 'flex', 'important');
        if (styles) styles.style.display = 'none';
        if (usersView) usersView.style.display = 'none';
        if (myAccountView) myAccountView.style.display = 'none';
        if (apiView) apiView.style.display = 'none';
        if (langView) langView.style.display = 'none';
        if (securityView) securityView.style.display = 'none';
        if (loginMethodsView) loginMethodsView.style.display = 'none';
        if (loginMethodFormView) loginMethodFormView.style.display = 'none';
        if (billingView) billingView.style.display = 'none';
        if (hotkeysView) hotkeysView.style.display = 'none';
        if (voiceAssistantView) voiceAssistantView.style.display = 'none';
        if (voicesView) voicesView.style.display = 'none';
        var flaggedView = byId('dashboard-settings-flagged');
        var networkView = byId('dashboard-settings-network');
        var contractsView = byId('dashboard-settings-contracts');
        if (flaggedView) flaggedView.style.display = 'none';
        if (networkView) networkView.style.display = 'none';
        if (contractsView) contractsView.style.display = 'none';
    }
    function showSettingsStylesView() {
        var main = byId('dashboard-settings-main');
        var styles = byId('dashboard-settings-styles');
        if (main) main.style.setProperty('display', 'none', 'important');
        if (styles) styles.style.display = '';
    }
    function showSettingsUsersView() {
        if (spectatorSettingsBlock()) return;
        var main = byId('dashboard-settings-main');
        var usersView = byId('dashboard-settings-users');
        var content = byId('dashboard-settings-users-content');
        if (main) main.style.setProperty('display', 'none', 'important');
        if (usersView) usersView.style.display = '';
        if (content && window.DashboardTabUsers && window.DashboardTabUsers.render) {
            window.DashboardTabUsers.render(content);
        }
        if (window.history && window.history.pushState) {
            history.pushState({ dashboardSettingsView: 'users' }, '', window.location.pathname + window.location.search);
        }
    }
    function showSettingsApiView() {
        if (spectatorSettingsBlock()) return;
        var main = byId('dashboard-settings-main');
        var apiView = byId('dashboard-settings-api');
        var content = byId('dashboard-settings-api-content');
        if (main) main.style.setProperty('display', 'none', 'important');
        if (apiView) apiView.style.display = '';
        if (content && window.DashboardTabApiAuth && window.DashboardTabApiAuth.render) {
            window.DashboardTabApiAuth.render(content);
        }
    }
    var LANGUAGES_LIST = ['English', 'Mandarin (Chinese)', 'Hindi', 'Spanish', 'French', 'Standard Arabic', 'Bengali', 'Portuguese', 'Russian', 'Urdu', 'Indonesian', 'German', 'Japanese', 'Swahili', 'Marathi', 'Telugu', 'Turkish', 'Tamil', 'Vietnamese', 'Korean'];
    // Shown to the operator in an alert, never resolved by code: %USERPROFILE% stays the
    // literal Windows variable so the message reads correctly for whoever is signed in.
    var LANGUAGE_LINKS_PATH_MSG = '%USERPROFILE%\\Desktop\\Zygomatic Origin\\Languages\\Language Links';

    function showSettingsLanguagesView() {
        if (spectatorSettingsBlock()) return;
        var main = byId('dashboard-settings-main');
        var langView = byId('dashboard-settings-languages');
        var listEl = byId('dashboard-settings-languages-list');
        if (main) main.style.setProperty('display', 'none', 'important');
        if (langView) langView.style.display = '';
        if (listEl) {
            listEl.innerHTML = LANGUAGES_LIST.map(function (name, i) {
                return '<li class="dashboard-lang-item" data-lang-name="' + name.replace(/"/g, '&quot;') + '">' + (i + 1) + '. ' + name + '</li>';
            }).join('');
            listEl.querySelectorAll('.dashboard-lang-item').forEach(function (li) {
                li.addEventListener('click', function () {
                    listEl.querySelectorAll('.dashboard-lang-item').forEach(function (l) { l.classList.remove('selected'); });
                    this.classList.add('selected');
                });
            });
        }
    }
    function getSelectedLanguageName() {
        var listEl = byId('dashboard-settings-languages-list');
        if (!listEl) return null;
        var sel = listEl.querySelector('.dashboard-lang-item.selected');
        return sel ? sel.getAttribute('data-lang-name') : null;
    }
    function applyLanguageFlow() {
        var name = getSelectedLanguageName();
        if (!name) {
            alert('Please select a language first.');
            return;
        }
        fetch('/api/dashboard/language_pack/' + encodeURIComponent(name))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var exists = data && data.exists;
                if (exists) {
                    if (confirm('Do you want to use the ' + name + ' language pack?')) {
                        try { localStorage.setItem('dashboard_language', name); } catch (e) {}
                    }
                    return;
                }
                if (!confirm('No language pack found. I will proceed and download the language pack. Should I continue?')) return;
                fetch('/api/dashboard/language_link/' + encodeURIComponent(name))
                    .then(function (r) { return r.json(); })
                    .then(function (linkData) {
                        var url = linkData && linkData.url;
                        if (!url) {
                            alert('No urls found, please add urls to ' + LANGUAGE_LINKS_PATH_MSG);
                            return;
                        }
                        window.open(url, '_blank');
                    })
                    .catch(function () {
                        alert('No urls found, please add urls to ' + LANGUAGE_LINKS_PATH_MSG);
                    });
            })
            .catch(function () {
                alert('Could not check language pack.');
            });
    }
    function showSettingsSecurityView() {
        var main = byId('dashboard-settings-main');
        var securityView = byId('dashboard-settings-security');
        var flaggedView = byId('dashboard-settings-flagged');
        var networkView = byId('dashboard-settings-network');
        var contractsView = byId('dashboard-settings-contracts');
        var agentMonitoringView = byId('dashboard-settings-agent-monitoring');
        var orchView = byId('dashboard-settings-orchestration-permissions');
        var zeroPublicView = byId('dashboard-settings-zero-public');
        var azureView = byId('dashboard-settings-azure');
        var controlSettingsView = byId('dashboard-settings-control-settings');
        if (main) main.style.setProperty('display', 'none', 'important');
        if (securityView) securityView.style.display = 'block';
        if (flaggedView) flaggedView.style.display = 'none';
        if (networkView) networkView.style.display = 'none';
        if (contractsView) contractsView.style.display = 'none';
        if (agentMonitoringView) agentMonitoringView.style.display = 'none';
        if (orchView) orchView.style.display = 'none';
        if (zeroPublicView) zeroPublicView.style.display = 'none';
        if (azureView) azureView.style.display = 'none';
        if (controlSettingsView) controlSettingsView.style.display = 'none';
    }
    window.showSettingsSecurityView = showSettingsSecurityView;
    function showSettingsFlaggedView() {
        if (spectatorSettingsBlock()) return;
        var securityView = byId('dashboard-settings-security');
        var flaggedView = byId('dashboard-settings-flagged');
        if (securityView) securityView.style.display = 'none';
        if (flaggedView) flaggedView.style.display = '';
    }
    function showSettingsNetworkView() {
        var securityView = byId('dashboard-settings-security');
        var networkView = byId('dashboard-settings-network');
        if (securityView) securityView.style.display = 'none';
        if (networkView) networkView.style.display = '';
    }
    function showSettingsContractsView() {
        if (spectatorSettingsBlock()) return;
        var securityView = byId('dashboard-settings-security');
        var contractsView = byId('dashboard-settings-contracts');
        if (securityView) securityView.style.display = 'none';
        if (contractsView) contractsView.style.display = '';
    }
    function showSettingsAgentMonitoringView() {
        if (spectatorSettingsBlock()) return;
        var securityView = byId('dashboard-settings-security');
        var agentMonitoringView = byId('dashboard-settings-agent-monitoring');
        if (securityView) securityView.style.display = 'none';
        if (agentMonitoringView) agentMonitoringView.style.display = '';
    }
    function showSettingsAgentMonitoringBack() {
        var agentMonitoringView = byId('dashboard-settings-agent-monitoring');
        var securityView = byId('dashboard-settings-security');
        if (agentMonitoringView) agentMonitoringView.style.display = 'none';
        if (securityView) securityView.style.display = '';
    }
    function showSettingsSecuritySubBack() {
        var securityView = byId('dashboard-settings-security');
        var flaggedView = byId('dashboard-settings-flagged');
        var networkView = byId('dashboard-settings-network');
        var contractsView = byId('dashboard-settings-contracts');
        var agentMonitoringView = byId('dashboard-settings-agent-monitoring');
        var orchView = byId('dashboard-settings-orchestration-permissions');
        var safetySwitchView = byId('dashboard-settings-safety-switch');
        var zeroPublicView = byId('dashboard-settings-zero-public');
        var azureView = byId('dashboard-settings-azure');
        var controlSettingsView = byId('dashboard-settings-control-settings');
        if (flaggedView) flaggedView.style.display = 'none';
        if (networkView) networkView.style.display = 'none';
        if (contractsView) contractsView.style.display = 'none';
        if (agentMonitoringView) agentMonitoringView.style.display = 'none';
        if (orchView) orchView.style.display = 'none';
        if (safetySwitchView) safetySwitchView.style.display = 'none';
        if (zeroPublicView) zeroPublicView.style.display = 'none';
        if (azureView) azureView.style.display = 'none';
        if (controlSettingsView) controlSettingsView.style.display = 'none';
        if (securityView) securityView.style.display = '';
    }
    function showSettingsSafetySwitchView() {
        if (spectatorSettingsBlock()) return;
        var securityView = byId('dashboard-settings-security');
        var safetySwitchView = byId('dashboard-settings-safety-switch');
        if (securityView) securityView.style.display = 'none';
        if (safetySwitchView) safetySwitchView.style.display = '';
        loadSafetyData();
    }
    function showSettingsSafetySwitchBack() {
        var safetySwitchView = byId('dashboard-settings-safety-switch');
        var securityView = byId('dashboard-settings-security');
        if (safetySwitchView) safetySwitchView.style.display = 'none';
        if (securityView) securityView.style.display = '';
    }
    function showSettingsZeroPublicView() {
        if (spectatorSettingsBlock()) return;
        var securityView = byId('dashboard-settings-security');
        var zpView = byId('dashboard-settings-zero-public');
        if (securityView) securityView.style.display = 'none';
        if (zpView) zpView.style.display = '';
        zpubLoadUrls();
    }
    window.zpubLoadUrls = function () {
        var tbody = byId('zpub-tbody');
        if (!tbody) return;
        tbody.innerHTML = '<tr><td colspan="8" style="padding:20px;color:#999;text-align:center;">Loading…</td></tr>';
        fetch('/api/zero_public/urls', { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var note = byId('zpub-server-url-note');
                if (note && d.public_base) note.textContent = 'Public server: ' + d.public_base;
                zpubRenderTable(d.urls || []);
            }).catch(function () {
                if (tbody) tbody.innerHTML = '<tr><td colspan="8" style="padding:20px;color:#c00;text-align:center;">Failed to load.</td></tr>';
            });
    };
    function zpubRenderTable(urls) {
        var tbody = byId('zpub-tbody');
        if (!tbody) return;
        if (!urls || !urls.length) {
            tbody.innerHTML = '<tr><td colspan="8" style="padding:20px;color:#999;text-align:center;">No links created yet. Click "+ Add Link" to create one.</td></tr>';
            return;
        }
        var statusColors = { active: '#16a34a', exhausted: '#d97706', expired: '#6b7280', revoked: '#dc2626' };
        var statusIcons  = { active: '🟢', exhausted: '🟡', expired: '⚫', revoked: '🔴' };
        var _BADGE_MANUAL = 'display:inline-block;padding:2px 8px;border-radius:10px;font-size:0.77rem;font-weight:600;background:#fff3cd;color:#92400e;border:1px solid #f59e0b;';
        var _BADGE_AUTO   = 'display:inline-block;padding:2px 8px;border-radius:10px;font-size:0.77rem;font-weight:600;background:#d1fae5;color:#065f46;border:1px solid #10b981;';
        var rows = urls.map(function (u) {
            var inviteUrl = u.invite_url;
            // Server emits Amsterdam-aware ISO with offset; legacy values may
            // be naive UTC. Only append 'Z' when there is no TZ marker yet.
            var _expIso = u.expires_at && !u.expires_at.endsWith('Z') && !/[+\-]\d{2}:?\d{2}$/.test(u.expires_at)
                          ? (u.expires_at + 'Z') : u.expires_at;
            var _crIso  = u.created_at && !u.created_at.endsWith('Z') && !/[+\-]\d{2}:?\d{2}$/.test(u.created_at)
                          ? (u.created_at + 'Z') : u.created_at;
            var expiresDate = _expIso ? new Date(_expIso).toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'numeric',timeZone:'Europe/Amsterdam'}) : '—';
            var createdDate = _crIso  ? new Date(_crIso ).toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'numeric',timeZone:'Europe/Amsterdam'}) : '—';
            var statusLabel = (statusIcons[u.status] || '❓') + ' ' + (u.status || '—');
            var statusColor = statusColors[u.status] || '#666';
            var exhausted   = u.status === 'exhausted' || u.status === 'expired' || u.status === 'revoked';
            var permBadge   = u.permission === 'manual'
                ? '<span style="' + _BADGE_MANUAL + '">Manual</span>'
                : '<span style="' + _BADGE_AUTO   + '">Automatic</span>';
            var revokeBtn   = (u.status === 'active' || u.status === 'exhausted')
                ? '<button onclick="zpubRevoke(\'' + u.token + '\')" style="padding:4px 10px;font-size:0.78rem;border:1px solid #e5e7eb;border-radius:5px;background:#fff;cursor:pointer;color:#dc2626;" title="Revoke">Revoke</button>'
                : '<span style="color:#ccc;font-size:0.78rem;">—</span>';
            return '<tr style="border-bottom:1px solid #f3f4f6;">'
                + '<td style="padding:8px 10px;">' + _escHtml(u.label || '') + '</td>'
                + '<td style="padding:8px 10px;font-family:monospace;font-size:0.8rem;">'
                +   '<a href="' + inviteUrl + '" target="_blank" style="color:#667eea;text-decoration:none;">' + inviteUrl + '</a>'
                +   ' <button onclick="zpubCopyUrl(\'' + inviteUrl + '\', this)" style="padding:2px 8px;font-size:0.75rem;border:1px solid #d1d5db;border-radius:4px;background:#f9fafb;cursor:pointer;">Copy</button>'
                + '</td>'
                + '<td style="padding:8px 10px;text-align:center;font-weight:600;">'
                +   '<span style="color:' + (exhausted ? '#d97706' : '#16a34a') + '">' + (u.used_requests || 0) + '</span>'
                +   ' / ' + (u.max_requests || 2)
                + '</td>'
                + '<td style="padding:8px 10px;">' + permBadge + '</td>'
                + '<td style="padding:8px 10px;color:#666;">' + createdDate + '</td>'
                + '<td style="padding:8px 10px;color:#666;">' + expiresDate + '</td>'
                + '<td style="padding:8px 10px;font-weight:600;color:' + statusColor + ';">' + statusLabel + '</td>'
                + '<td style="padding:8px 10px;">' + revokeBtn + '</td>'
                + '</tr>';
        });
        tbody.innerHTML = rows.join('');
    }
    function _escHtml(s) {
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }
    window.zpubOpenAddModal = function () {
        var modal = byId('zpub-add-modal');
        if (modal) { modal.style.display = 'flex'; }
        var lbl = byId('zpub-label-input');
        var mr  = byId('zpub-maxreq-input');
        if (lbl) lbl.value = '';
        if (mr)  mr.value  = '2';
        if (lbl) setTimeout(function () { lbl.focus(); }, 50);
    };
    window.zpubCloseAddModal = function () {
        var modal = byId('zpub-add-modal');
        if (modal) modal.style.display = 'none';
    };
    window.zpubCreateUrl = function () {
        var label  = (byId('zpub-label-input') || {}).value || '';
        var maxReq = parseInt((byId('zpub-maxreq-input') || {}).value || '2', 10);
        var perm   = (byId('zpub-perm-input') || {}).value || 'automatic';
        if (!label.trim()) { alert('Please enter a label.'); return; }
        var saveBtn = byId('zpub-add-save-btn');
        if (saveBtn) saveBtn.disabled = true;
        fetch('/api/zero_public/urls', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ label: label.trim(), max_requests: maxReq, permission: perm }),
        }).then(function (r) { return r.json(); }).then(function (d) {
            if (saveBtn) saveBtn.disabled = false;
            if (d.error) { alert(d.error); return; }
            zpubCloseAddModal();
            zpubLoadUrls();
        }).catch(function () {
            if (saveBtn) saveBtn.disabled = false;
            alert('Failed to create link.');
        });
    };
    window.zpubRevoke = function (token) {
        if (!confirm('Revoke this link? It will no longer be usable.')) return;
        fetch('/api/zero_public/urls/' + token, { method: 'DELETE' })
            .then(function (r) { return r.json(); })
            .then(function () { zpubLoadUrls(); })
            .catch(function () { alert('Failed to revoke.'); });
    };
    window.zpubCopyUrl = function (url, btn) {
        var orig = btn.textContent;
        function flash() { btn.textContent = 'Copied!'; setTimeout(function () { btn.textContent = orig; }, 1500); }
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(url).then(flash).catch(function () { fallbackCopy(url, flash); });
        } else {
            fallbackCopy(url, flash);
        }
    };
    function fallbackCopy(text, cb) {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.style.cssText = 'position:fixed;top:-9999px;left:-9999px;opacity:0';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        try { document.execCommand('copy'); if (cb) cb(); } catch (e) { alert(text); }
        document.body.removeChild(ta);
    }
    function loadSafetyData() {
        fetch('/api/safety/status').then(function (r) { return r.json(); }).catch(function () { return {}; }).then(function (d) {
            var levelEl = byId('safety-protection-level');
            var descEl = byId('safety-protection-desc');
            var cbEl = byId('safety-circuit-breaker');
            var resetBtn = byId('safety-circuit-reset-btn');
            var h = d.hardware || {};
            var s = d.stability || {};
            var levelColors = ['#16a34a', '#ca8a04', '#d97706', '#dc2626', '#7f1d1d'];
            var levelLabels = ['0 — Normal', '1 — Warning', '2 — Protective Degradation', '3 — Hard Stop', '4 — Emergency Halt'];
            if (levelEl) {
                levelEl.textContent = levelLabels[d.protection_level] || (d.protection_level + ' — ' + (d.protection_label || 'Unknown'));
                levelEl.style.color = levelColors[d.protection_level] || levelColors[0];
            }
            if (descEl) descEl.textContent = d.protection_desc || 'System healthy, jobs run normally.';
            if (cbEl) cbEl.textContent = d.circuit_breaker_active ? 'Open (tripped)' : 'Closed (OK)';
            if (resetBtn) resetBtn.style.display = d.circuit_breaker_active ? '' : 'none';
            var setKpi = function (id, val) { var el = byId(id); if (el) el.textContent = val != null && val !== '' ? val : '—'; };
            setKpi('safety-kpi-gpu-temp', h.gpu_temp_c != null ? h.gpu_temp_c + ' °C' : null);
            setKpi('safety-kpi-gpu-pct', h.gpu_pct != null ? h.gpu_pct + '%' : null);
            setKpi('safety-kpi-vram', h.vram_used_mb != null ? h.vram_used_mb + ' MB' : null);
            setKpi('safety-kpi-cpu-temp', h.cpu_temp_c != null ? h.cpu_temp_c + ' °C' : null);
            setKpi('safety-kpi-cpu-pct', h.cpu_pct != null ? h.cpu_pct + '%' : null);
            setKpi('safety-kpi-ram', h.ram_pct != null ? h.ram_pct + '%' : null);
            setKpi('safety-kpi-disk', h.free_disk_gb != null ? h.free_disk_gb + ' GB' : null);
            setKpi('safety-kpi-queue', s.queue_depth);
            setKpi('safety-kpi-oom', s.oom_count);
            var auditEl = byId('safety-audit-log');
            if (auditEl) {
                var events = d.audit_events || [];
                auditEl.innerHTML = events.length ? events.slice(-10).reverse().map(function (e) {
                    return '<div style="margin-bottom:6px;">' + (e.ts || '') + ' — ' + (e.event || '') + '</div>';
                }).join('') : 'No recent safety events.';
            }
            var tbody = byId('safety-thresholds-tbody');
            var actionsDiv = byId('safety-thresholds-actions');
            var isAdmin = window.DASHBOARD_USER_ROLE === 'admins';
            if (tbody) {
                var th = d.thresholds || {};
                var paramMeta = {
                    gpu: { temp_warning_c: ['Temp warning', '°C'], temp_critical_c: ['Temp critical', '°C'], util_warning_pct: ['Util warning', '%'], util_critical_pct: ['Util critical', '%'], vram_warning_pct: ['VRAM warning', '%'], vram_critical_pct: ['VRAM critical', '%'], min_reserve_vram_mb: ['Min reserve VRAM', 'MB'] },
                    cpu: { temp_warning_c: ['Temp warning', '°C'], temp_critical_c: ['Temp critical', '°C'], util_warning_pct: ['Util warning', '%'], util_critical_pct: ['Util critical', '%'], min_reserve_pct: ['Min reserve', '%'] },
                    ram: { warning_pct: ['Warning', '%'], critical_pct: ['Critical', '%'], min_free_reserve_mb: ['Min free reserve', 'MB'] },
                    disk: { warning_free_gb: ['Warning free', 'GB'], critical_free_gb: ['Critical free', 'GB'], emergency_reserve_gb: ['Emergency reserve', 'GB'] },
                    failure_patterns: { max_failed_launches_5m: ['Max failed/5m', ''], max_oom_5m: ['Max OOM/5m', ''], max_retries_per_job: ['Max retries/job', ''], max_agent_crashes_5m: ['Max crashes/5m', ''], queue_depth_warning: ['Queue warning', ''], queue_depth_critical: ['Queue critical', ''] }
                };
                var rows = [];
                var catLabels = { gpu: 'GPU', cpu: 'CPU', ram: 'RAM', disk: 'Disk', failure_patterns: 'Failure patterns' };
                for (var cat in paramMeta) {
                    var meta = paramMeta[cat];
                    var vals = th[cat] || {};
                    for (var key in meta) {
                        var m = meta[key];
                        var v = vals[key];
                        var valStr = v != null ? String(v) : '—';
                        var cell = isAdmin ? '<input type="number" class="dashboard-settings-input safety-threshold-input" data-cat="' + cat + '" data-key="' + key + '" value="' + (v != null ? v : '') + '" style="width:80px;padding:4px;">' : valStr;
                        rows.push('<tr><td>' + (catLabels[cat] || cat) + '</td><td>' + (m[0] || key) + '</td><td>' + cell + '</td><td>' + (m[1] || '') + '</td></tr>');
                    }
                }
                tbody.innerHTML = rows.length ? rows.join('') : '<tr><td colspan="4">No thresholds configured.</td></tr>';
            }
            if (actionsDiv) actionsDiv.style.display = isAdmin ? '' : 'none';
        });
    }
    function showSettingsOrchestrationPermissionsView() {
        if (spectatorSettingsBlock()) return;
        var securityView = byId('dashboard-settings-security');
        var orchView = byId('dashboard-settings-orchestration-permissions');
        var tbody = byId('orchestration-permissions-tbody');
        if (securityView) securityView.style.display = 'none';
        if (orchView) orchView.style.display = '';
        if (tbody) {
            tbody.innerHTML = '<tr><td colspan="3">Loading...</td></tr>';
            fetch('/api/orchestration/permissions').then(function(r) { return r.json(); }).catch(function() { return {}; }).then(function(data) {
                var agents = data.agents || {};
                var defaultRole = data.default_role || 'Executor';
                var rows = [];
                for (var agentName in agents) {
                    var p = agents[agentName];
                    var roleType = p.role_type || defaultRole;
                    var actions = p.allowed_actions || [];
                    var badgeHtml = actions.length ? actions.map(function(a) { return '<span class="orch-badge" title="' + (a || '').replace(/"/g, '&quot;') + '">' + (a || '') + '</span>'; }).join(' ') : '—';
                    rows.push('<tr><td>' + (agentName || '') + '</td><td>' + roleType + '</td><td>' + badgeHtml + '</td></tr>');
                }
                if (rows.length === 0) rows.push('<tr><td colspan="3">No orchestration permissions configured. Edit orchestration_permissions.json.</td></tr>');
                tbody.innerHTML = rows.join('');
            });
        }
    }
    function showSettingsLoginMethodsView() {
        var securityView = byId('dashboard-settings-security');
        var loginMethodsView = byId('dashboard-settings-login-methods');
        if (securityView) securityView.style.display = 'none';
        if (loginMethodsView) loginMethodsView.style.display = '';
    }
    function showSettingsLoginMethodFormView(methodId) {
        if (spectatorSettingsBlock()) return;
        window._dashboardLoginMethodFormId = methodId;
        var loginMethodsView = byId('dashboard-settings-login-methods');
        var formView = byId('dashboard-settings-login-method-form');
        var titleEl = byId('dashboard-settings-login-method-form-title');
        var fieldsEl = byId('dashboard-settings-login-method-form-fields');
        if (loginMethodsView) loginMethodsView.style.display = 'none';
        if (!formView || !fieldsEl) return;
        formView.style.display = '';
        if (titleEl) titleEl.textContent = LOGIN_METHOD_LABELS[methodId] || methodId;
        var fields = LOGIN_METHOD_FIELDS[methodId] || [];
        var html = '';
        fields.forEach(function (f) {
            var safeId = 'lm-' + String(f.name).replace(/[^a-zA-Z0-9_-]/g, '_');
            html += '<div class="form-group"><label for="' + safeId + '">' + f.label + '</label><input type="' + (f.type || 'text') + '" id="' + safeId + '" name="' + f.name + '" style="width:100%;padding:8px 12px;border-radius:8px;margin-top:4px;"></div>';
        });
        fieldsEl.innerHTML = html;
        try {
            var saved = JSON.parse(localStorage.getItem('dashboard_login_method_config_' + methodId) || '{}');
            fields.forEach(function (f) {
                var safeId = 'lm-' + String(f.name).replace(/[^a-zA-Z0-9_-]/g, '_');
                var input = document.getElementById(safeId);
                if (input && saved[f.name]) input.value = saved[f.name];
            });
        } catch (e) {}
    }
    function showSettingsLoginMethodFormBack() {
        var formView = byId('dashboard-settings-login-method-form');
        var loginMethodsView = byId('dashboard-settings-login-methods');
        if (formView) formView.style.display = 'none';
        if (loginMethodsView) loginMethodsView.style.display = '';
    }
    function showSettingsSecurityBack() {
        var securityView = byId('dashboard-settings-security');
        var loginMethodsView = byId('dashboard-settings-login-methods');
        var agentMonitoringView = byId('dashboard-settings-agent-monitoring');
        var main = byId('dashboard-settings-main');
        if (loginMethodsView) loginMethodsView.style.display = 'none';
        if (agentMonitoringView) agentMonitoringView.style.display = 'none';
        if (securityView) securityView.style.display = 'none';
        if (main) main.style.display = 'flex';
    }
    function showSettingsLoginMethodsBack() {
        var loginMethodsView = byId('dashboard-settings-login-methods');
        var securityView = byId('dashboard-settings-security');
        if (loginMethodsView) loginMethodsView.style.display = 'none';
        if (securityView) securityView.style.display = '';
    }
    function showSettingsBillingView() {
        var main = byId('dashboard-settings-main');
        var billingView = byId('dashboard-settings-billing');
        if (main) main.style.setProperty('display', 'none', 'important');
        if (billingView) billingView.style.display = '';
    }
    function showSettingsHotkeysView() {
        if (spectatorSettingsBlock()) return;
        var main = byId('dashboard-settings-main');
        var hotkeysView = byId('dashboard-settings-hotkeys');
        if (main) main.style.setProperty('display', 'none', 'important');
        if (hotkeysView) hotkeysView.style.display = '';
        if (window.DashboardSettingsHotkeys && window.DashboardSettingsHotkeys.render) {
            window.DashboardSettingsHotkeys.render();
        }
    }
    function showSettingsVoicesView() {
        var main = byId('dashboard-settings-main');
        var voicesView = byId('dashboard-settings-voices');
        if (!voicesView) { return; }   // panel not in DOM, do nothing
        if (main) main.style.setProperty('display', 'none', 'important');
        voicesView.style.display = 'block';
        if (window.DashboardSettingsVoices && window.DashboardSettingsVoices.openVoices) {
            window.DashboardSettingsVoices.openVoices();
        }
    }
    window.showSettingsVoicesView = showSettingsVoicesView;
    function showSettingsMyAccountView() {
        if (spectatorSettingsBlock()) return;
        var main = byId('dashboard-settings-main');
        var myAccountView = byId('dashboard-settings-my-account');
        if (main) main.style.setProperty('display', 'none', 'important');
        if (myAccountView) myAccountView.style.display = '';
    }
    function showSettingsVoiceAssistantView() {
        var main = byId('dashboard-settings-main');
        var voiceView = byId('dashboard-settings-voice-assistant');
        if (main) main.style.setProperty('display', 'none', 'important');
        if (voiceView) voiceView.style.display = '';
        var voiceSelect = byId('voice-assistant-voice');
        var customRows = document.querySelectorAll('.voice-assistant-custom-row');
        function updateCustomDisabled() {
            var presetSelected = voiceSelect && voiceSelect.value !== '';
            customRows.forEach(function (row) {
                var selects = row.querySelectorAll('select');
                selects.forEach(function (s) { s.disabled = presetSelected; });
            });
        }
        updateCustomDisabled();
        if (voiceSelect && !voiceSelect._voiceAssistantBound) {
            voiceSelect._voiceAssistantBound = true;
            voiceSelect.addEventListener('change', updateCustomDisabled);
        }
        var applyBtn = byId('voice-assistant-apply-btn');
        if (applyBtn && !applyBtn._voiceAssistantBound) {
            applyBtn._voiceAssistantBound = true;
            applyBtn.addEventListener('click', applyVoiceAssistantSettings);
        }
    }
    function applyVoiceAssistantSettings() {
        var genderSelect = byId('voice-assistant-gender');
        var ageSelect = byId('voice-assistant-age');
        var voiceSelect = byId('voice-assistant-voice');
        var gender = genderSelect ? genderSelect.value : '';
        var age = ageSelect ? ageSelect.value : '';
        var voice = voiceSelect ? voiceSelect.value : '';
        var voicePresetSelected = voice !== '';
        var customFieldsValid = gender !== '' && age !== '';
        if (!voicePresetSelected && !customFieldsValid) {
            alert('Please select an age and gender before applying.');
            return;
        }
        var permissions = [];
        document.querySelectorAll('input[name="voice-permission-tab"]:checked').forEach(function(cb) {
            permissions.push(cb.value);
        });
        try {
            localStorage.setItem('voice_assistant_settings', JSON.stringify({
                voice: voice,
                gender: gender,
                age: age,
                language: byId('voice-assistant-language') ? byId('voice-assistant-language').value : '',
                elegance: byId('voice-assistant-elegance') ? byId('voice-assistant-elegance').value : '',
                mood: byId('voice-assistant-mood') ? byId('voice-assistant-mood').value : '',
                permissions: permissions
            }));
            alert('Voice assistant settings applied successfully.');
        } catch (e) {
            alert('Failed to save settings: ' + (e.message || e));
        }
    }
    function handleSettingsPanelClick(e) {
        var btn = e.target && e.target.closest ? e.target.closest('button') : null;
        if (!btn) return;
        var id = btn.id;
        var method = btn.getAttribute && btn.getAttribute('data-method');
        if (method) {
            e.preventDefault();
            e.stopPropagation();
            showSettingsLoginMethodFormView(method);
            return;
        }
        if (!id) return;
        if (id === 'dashboard-settings-styles-themes-btn') { e.preventDefault(); e.stopPropagation(); showSettingsStylesView(); return; }
        if (id === 'dashboard-settings-users-btn') { e.preventDefault(); e.stopPropagation(); showSettingsUsersView(); return; }
        if (id === 'dashboard-settings-my-account-btn') { e.preventDefault(); e.stopPropagation(); showSettingsMyAccountView(); return; }
        if (id === 'dashboard-settings-api-auth-btn') { e.preventDefault(); e.stopPropagation(); showSettingsApiView(); return; }
        if (id === 'dashboard-settings-languages-btn') { e.preventDefault(); e.stopPropagation(); showSettingsLanguagesView(); return; }
        if (id === 'dashboard-settings-security-btn') { e.preventDefault(); e.stopPropagation(); showSettingsSecurityView(); return; }
        if (id === 'dashboard-settings-billing-btn') { e.preventDefault(); e.stopPropagation(); showSettingsBillingView(); return; }
        if (id === 'dashboard-settings-hotkeys-btn') { e.preventDefault(); e.stopPropagation(); showSettingsHotkeysView(); return; }
        if (id === 'dashboard-settings-voices-btn') { e.preventDefault(); e.stopPropagation(); showSettingsVoicesView(); return; }
        if (id === 'dashboard-settings-voices-back') { e.preventDefault(); e.stopPropagation(); showSettingsMainView(); return; }
        if (id === 'dashboard-settings-voice-assistant-btn') { e.preventDefault(); e.stopPropagation(); showSettingsVoiceAssistantView(); return; }
        if (id === 'dashboard-settings-voice-assistant-back') { e.preventDefault(); e.stopPropagation(); showSettingsMainView(); return; }
        if (id === 'voice-assistant-apply-btn') { e.preventDefault(); e.stopPropagation(); applyVoiceAssistantSettings(); return; }
        if (id === 'dashboard-settings-styles-back') { e.preventDefault(); e.stopPropagation(); showSettingsMainView(); return; }
        if (id === 'dashboard-settings-users-back') { e.preventDefault(); e.stopPropagation(); showSettingsMainView(); return; }
        if (id === 'dashboard-settings-api-back') { e.preventDefault(); e.stopPropagation(); showSettingsMainView(); return; }
        if (id === 'dashboard-settings-languages-back') { e.preventDefault(); e.stopPropagation(); showSettingsMainView(); return; }
        if (id === 'dashboard-settings-languages-apply') { e.preventDefault(); e.stopPropagation(); applyLanguageFlow(); return; }
        if (id === 'dashboard-settings-security-back') { e.preventDefault(); e.stopPropagation(); showSettingsSecurityBack(); return; }
        if (id === 'dashboard-settings-login-methods-back') { e.preventDefault(); e.stopPropagation(); showSettingsLoginMethodsBack(); return; }
        if (id === 'dashboard-settings-login-method-form-back') { e.preventDefault(); e.stopPropagation(); showSettingsLoginMethodFormBack(); return; }
        if (id === 'dashboard-settings-billing-back') { e.preventDefault(); e.stopPropagation(); showSettingsMainView(); return; }
        if (id === 'dashboard-settings-hotkeys-back') { e.preventDefault(); e.stopPropagation(); showSettingsMainView(); return; }
        if (id === 'dashboard-settings-my-account-back') { e.preventDefault(); e.stopPropagation(); showSettingsMainView(); return; }
        if (id === 'dashboard-settings-flagged-back') { e.preventDefault(); e.stopPropagation(); showSettingsSecuritySubBack(); return; }
        if (id === 'dashboard-settings-network-back') { e.preventDefault(); e.stopPropagation(); showSettingsSecuritySubBack(); return; }
        if (id === 'dashboard-settings-contracts-back') { e.preventDefault(); e.stopPropagation(); showSettingsSecuritySubBack(); return; }
        if (id === 'dashboard-settings-orchestration-permissions-btn') { e.preventDefault(); e.stopPropagation(); showSettingsOrchestrationPermissionsView(); return; }
        if (id === 'dashboard-settings-orchestration-permissions-back') { e.preventDefault(); e.stopPropagation(); showSettingsSecuritySubBack(); return; }
        if (id === 'dashboard-settings-flagged-btn') { e.preventDefault(); e.stopPropagation(); showSettingsFlaggedView(); return; }
        if (id === 'dashboard-settings-network-btn') { e.preventDefault(); e.stopPropagation(); showSettingsNetworkView(); return; }
        if (id === 'dashboard-settings-contracts-btn') { e.preventDefault(); e.stopPropagation(); showSettingsContractsView(); return; }
        if (id === 'dashboard-settings-agent-monitoring-btn') { e.preventDefault(); e.stopPropagation(); showSettingsAgentMonitoringView(); return; }
        if (id === 'dashboard-settings-agent-monitoring-back') { e.preventDefault(); e.stopPropagation(); showSettingsAgentMonitoringBack(); return; }
        if (id === 'dashboard-settings-safety-switch-btn') { e.preventDefault(); e.stopPropagation(); showSettingsSafetySwitchView(); return; }
        if (id === 'dashboard-settings-safety-switch-back') { e.preventDefault(); e.stopPropagation(); showSettingsSafetySwitchBack(); return; }
        if (id === 'dashboard-settings-zero-public-btn') { e.preventDefault(); e.stopPropagation(); showSettingsZeroPublicView(); return; }
        if (id === 'dashboard-settings-zero-public-back') { e.preventDefault(); e.stopPropagation(); showSettingsSecuritySubBack(); return; }
        if (id === 'dashboard-settings-azure-btn') { e.preventDefault(); e.stopPropagation(); if (window.showSettingsAzureView) window.showSettingsAzureView(); return; }
        if (id === 'dashboard-settings-azure-back') { e.preventDefault(); e.stopPropagation(); showSettingsSecuritySubBack(); return; }
        if (id === 'dashboard-settings-control-settings-btn') { e.preventDefault(); e.stopPropagation(); if (window.showSettingsControlSettingsView) window.showSettingsControlSettingsView(); return; }
        if (id === 'dashboard-settings-control-settings-back') { e.preventDefault(); e.stopPropagation(); showSettingsSecuritySubBack(); return; }
        if (id === 'safety-emergency-stop-btn') {
            e.preventDefault();
            e.stopPropagation();
            var msgEl = byId('safety-emergency-msg');
            if (msgEl) msgEl.textContent = 'Requesting…';
            fetch('/api/safety/emergency_stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (msgEl) msgEl.textContent = data.message || (data.success ? 'Emergency stop requested.' : 'Request failed.');
                    loadSafetyData();
                })
                .catch(function () {
                    if (msgEl) msgEl.textContent = 'Request failed.';
                });
            return;
        }
        if (id === 'safety-circuit-reset-btn') {
            e.preventDefault();
            e.stopPropagation();
            fetch('/api/admin/schedule-pause', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ paused: false, reason: 'Circuit reset from Safety Switch' }) })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.error) alert('Reset failed: ' + data.error);
                    loadSafetyData();
                })
                .catch(function () { alert('Reset request failed.'); });
            return;
        }
        if (id === 'safety-thresholds-save-btn') {
            e.preventDefault();
            e.stopPropagation();
            var inputs = document.querySelectorAll('.safety-threshold-input');
            var updates = {};
            inputs.forEach(function (inp) {
                var cat = inp.getAttribute('data-cat');
                var key = inp.getAttribute('data-key');
                if (!cat || !key) return;
                var v = parseFloat(inp.value);
                if (isNaN(v) || v < 0) return;
                if (!updates[cat]) updates[cat] = {};
                updates[cat][key] = v;
            });
            var msgEl = byId('safety-thresholds-msg');
            if (msgEl) msgEl.textContent = 'Saving…';
            var csrf = document.querySelector('meta[name="csrf-token"]');
            var headers = { 'Content-Type': 'application/json' };
            if (csrf && csrf.content) headers['X-CSRF-Token'] = csrf.content;
            fetch('/api/safety/thresholds', { method: 'PATCH', headers: headers, body: JSON.stringify(updates) })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (msgEl) msgEl.textContent = data.error ? ('Error: ' + data.error) : 'Thresholds saved.';
                    if (!data.error) loadSafetyData();
                })
                .catch(function () {
                    if (msgEl) msgEl.textContent = 'Request failed.';
                });
            return;
        }
        var agentTab = e.target.closest && e.target.closest('.dashboard-settings-agent-monitoring-tab');
        if (agentTab) {
            e.preventDefault();
            e.stopPropagation();
            var tab = agentTab.getAttribute('data-tab');
            document.querySelectorAll('.dashboard-settings-agent-monitoring-tab').forEach(function (t) { t.classList.remove('active'); });
            agentTab.classList.add('active');
            ['communications', 'activity', 'permissions'].forEach(function (name) {
                var panel = byId('dashboard-settings-agent-monitoring-' + name);
                if (panel) panel.style.display = tab === name ? 'block' : 'none';
            });
            return;
        }
        if (id === 'dashboard-settings-login-methods-btn') { e.preventDefault(); e.stopPropagation(); showSettingsLoginMethodsView(); return; }
        if (id === 'dashboard-settings-security-diagrams-btn') { e.preventDefault(); e.stopPropagation(); openSecurityDiagramsModal(); return; }
        if (id === 'dashboard-settings-llms-btn') { e.preventDefault(); e.stopPropagation(); openLlmsListOverlay(); return; }
        if (id === 'dashboard-settings-dependencies-btn') { e.preventDefault(); e.stopPropagation(); openDependenciesOverlay(); return; }
        if (id === 'security-diagrams-close') { e.preventDefault(); e.stopPropagation(); closeSecurityDiagramsModal(); return; }
        if (id === 'dashboard-settings-open-buttons') { e.preventDefault(); e.stopPropagation(); if (window.DashboardSettings && window.DashboardSettings.openButtons) window.DashboardSettings.openButtons(); return; }
        if (id === 'dashboard-settings-open-backgrounds') { e.preventDefault(); e.stopPropagation(); if (window.DashboardSettings && window.DashboardSettings.openBackgrounds) window.DashboardSettings.openBackgrounds(); return; }
        if (id === 'dashboard-settings-open-sidebar') { e.preventDefault(); e.stopPropagation(); if (window.DashboardSettings && window.DashboardSettings.openSidebar) window.DashboardSettings.openSidebar(); return; }
        if (id === 'dashboard-settings-open-progression-bars') { e.preventDefault(); e.stopPropagation(); if (window.DashboardSettings && window.DashboardSettings.openProgressionBars) window.DashboardSettings.openProgressionBars(); return; }
        if (id === 'dashboard-settings-open-cursors') { e.preventDefault(); e.stopPropagation(); if (window.DashboardSettings && window.DashboardSettings.openCursors) window.DashboardSettings.openCursors(); return; }
    }

    function initSettings() {
        var icon = byId('dashboard-settings-icon');
        var panel = byId('panel-settings');
        if (panel) panel.addEventListener('click', handleSettingsPanelClick);
        /* Fallback: document-level delegation for Security button (in case panel binding misses) */
        document.addEventListener('click', function (e) {
            var btn = e.target && e.target.closest ? e.target.closest('#dashboard-settings-security-btn') : null;
            if (btn && typeof showSettingsSecurityView === 'function') {
                e.preventDefault();
                e.stopPropagation();
                showSettingsSecurityView();
            }
        }, true);
        if (icon) icon.addEventListener('click', function (e) {
            e.stopPropagation();
            if (window.DASHBOARD_USER_ROLE === 'spectators') {
                alert('This action is not allowed as Spectator');
                return;
            }
            if (window.DASHBOARD_INITIAL_TAB && window.DASHBOARD_INITIAL_TAB !== 'settings') {
                window.location.href = '/settings';
                return;
            }
            showPanel('settings');
            showSettingsMainView();
            if (window.history && window.history.pushState) {
                history.pushState({ dashboardSettingsView: 'main' }, '', window.location.pathname + window.location.search);
            }
            if (window.DashboardTabs && window.DashboardTabs.renderTab) {
                window.DashboardTabs.renderTab('settings');
            }
        });
        var usersBtn = byId('dashboard-settings-users-btn');
        if (usersBtn) usersBtn.addEventListener('click', showSettingsUsersView);
        var myAccountBtn = byId('dashboard-settings-my-account-btn');
        if (myAccountBtn) myAccountBtn.addEventListener('click', showSettingsMyAccountView);
        var apiBtn = byId('dashboard-settings-api-auth-btn');
        if (apiBtn) apiBtn.addEventListener('click', showSettingsApiView);
        var langBtn = byId('dashboard-settings-languages-btn');
        if (langBtn) langBtn.addEventListener('click', showSettingsLanguagesView);
        var securityBtn = byId('dashboard-settings-security-btn');
        if (securityBtn) securityBtn.addEventListener('click', showSettingsSecurityView);
        var billingBtn = byId('dashboard-settings-billing-btn');
        if (billingBtn) billingBtn.addEventListener('click', showSettingsBillingView);
        var hotkeysBtn = byId('dashboard-settings-hotkeys-btn');
        if (hotkeysBtn) hotkeysBtn.addEventListener('click', showSettingsHotkeysView);
        var backBtn = byId('dashboard-settings-styles-back');
        if (backBtn) backBtn.addEventListener('click', showSettingsMainView);
        var usersBackBtn = byId('dashboard-settings-users-back');
        if (usersBackBtn) usersBackBtn.addEventListener('click', showSettingsMainView);
        var apiBackBtn = byId('dashboard-settings-api-back');
        if (apiBackBtn) apiBackBtn.addEventListener('click', showSettingsMainView);
        var langBackBtn = byId('dashboard-settings-languages-back');
        if (langBackBtn) langBackBtn.addEventListener('click', showSettingsMainView);
        var langApplyBtn = byId('dashboard-settings-languages-apply');
        if (langApplyBtn) langApplyBtn.addEventListener('click', applyLanguageFlow);
        var securityBackBtn = byId('dashboard-settings-security-back');
        if (securityBackBtn) securityBackBtn.addEventListener('click', showSettingsSecurityBack);
        var loginMethodsBackBtn = byId('dashboard-settings-login-methods-back');
        if (loginMethodsBackBtn) loginMethodsBackBtn.addEventListener('click', showSettingsLoginMethodsBack);
        var loginMethodFormBackBtn = byId('dashboard-settings-login-method-form-back');
        if (loginMethodFormBackBtn) loginMethodFormBackBtn.addEventListener('click', showSettingsLoginMethodFormBack);
        var billingBackBtn = byId('dashboard-settings-billing-back');
        if (billingBackBtn) billingBackBtn.addEventListener('click', showSettingsMainView);
        var hotkeysBackBtn = byId('dashboard-settings-hotkeys-back');
        if (hotkeysBackBtn) hotkeysBackBtn.addEventListener('click', showSettingsMainView);
        var voicesBtn = byId('dashboard-settings-voices-btn');
        if (voicesBtn) voicesBtn.addEventListener('click', showSettingsVoicesView);
        var voicesBackBtn = byId('dashboard-settings-voices-back');
        if (voicesBackBtn) voicesBackBtn.addEventListener('click', showSettingsMainView);
        var myAccountBackBtn = byId('dashboard-settings-my-account-back');
        if (myAccountBackBtn) myAccountBackBtn.addEventListener('click', showSettingsMainView);
        var myAccountSaveBtn = byId('dashboard-settings-my-account-save');
        if (myAccountSaveBtn) myAccountSaveBtn.addEventListener('click', function () {
            var msgEl = byId('dashboard-settings-my-account-msg');
            var payload = {
                email: (byId('my-account-email') && byId('my-account-email').value) || '',
                phone: (byId('my-account-phone') && byId('my-account-phone').value) || '',
                login_method: (byId('my-account-login-method') && byId('my-account-login-method').value) || 'id_password',
                devices: (byId('my-account-devices') && byId('my-account-devices').value) || ''
            };
            var pwd = byId('my-account-password') && byId('my-account-password').value;
            if (pwd) payload.password = pwd;
            fetch('/api/dashboard/my_account', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            }).then(function (r) { return r.json(); }).then(function (res) {
                if (msgEl) msgEl.textContent = res.success ? 'Saved.' : (res.message || 'Save failed.');
                if (res.success) showSettingsMainView();
            }).catch(function () {
                if (msgEl) msgEl.textContent = 'Save failed.';
            });
        });
        if (window.DASHBOARD_USER_ROLE === 'operators' || window.DASHBOARD_USER_ROLE === 'spectators') {
            if (usersBtn) usersBtn.style.display = 'none';
        }
        if (window.DASHBOARD_USER_ROLE === 'operators') {
            if (myAccountBtn) myAccountBtn.style.display = '';
        }
        document.querySelectorAll('#dashboard-settings-login-methods [data-method]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                showSettingsLoginMethodFormView(this.getAttribute('data-method'));
            });
        });
        var loginMethodsBtn = byId('dashboard-settings-login-methods-btn');
        if (loginMethodsBtn) loginMethodsBtn.addEventListener('click', showSettingsLoginMethodsView);
        var flaggedBtn = byId('dashboard-settings-flagged-btn');
        if (flaggedBtn) flaggedBtn.addEventListener('click', showSettingsFlaggedView);
        var networkBtn = byId('dashboard-settings-network-btn');
        if (networkBtn) networkBtn.addEventListener('click', showSettingsNetworkView);
        var contractsBtn = byId('dashboard-settings-contracts-btn');
        if (contractsBtn) contractsBtn.addEventListener('click', showSettingsContractsView);
        var flaggedBackBtn = byId('dashboard-settings-flagged-back');
        if (flaggedBackBtn) flaggedBackBtn.addEventListener('click', showSettingsSecuritySubBack);
        var networkBackBtn = byId('dashboard-settings-network-back');
        if (networkBackBtn) networkBackBtn.addEventListener('click', showSettingsSecuritySubBack);
        var contractsBackBtn = byId('dashboard-settings-contracts-back');
        if (contractsBackBtn) contractsBackBtn.addEventListener('click', showSettingsSecuritySubBack);
        var loginMethodFormSaveBtn = byId('dashboard-settings-login-method-form-save');
        if (loginMethodFormSaveBtn) loginMethodFormSaveBtn.addEventListener('click', function () {
            var formView = byId('dashboard-settings-login-method-form');
            if (!formView || formView.style.display === 'none') return;
            var fieldsEl = byId('dashboard-settings-login-method-form-fields');
            var inputs = fieldsEl ? fieldsEl.querySelectorAll('input[id^="lm-"]') : [];
            var data = {};
            inputs.forEach(function (input) {
                var name = input.getAttribute('name');
                if (name) data[name] = input.value || '';
            });
            var methodId = window._dashboardLoginMethodFormId;
            if (methodId) {
                try { localStorage.setItem('dashboard_login_method_config_' + methodId, JSON.stringify(data)); } catch (e) {}
            }
            showSettingsLoginMethodFormBack();
        });
        var openButtonsBtn = byId('dashboard-settings-open-buttons');
        var openBackgroundsBtn = byId('dashboard-settings-open-backgrounds');
        var openSidebarBtn = byId('dashboard-settings-open-sidebar');
        var openProgressionBtn = byId('dashboard-settings-open-progression-bars');
        var openCursorsBtn = byId('dashboard-settings-open-cursors');
        if (openButtonsBtn) openButtonsBtn.addEventListener('click', function () {
            if (window.DashboardSettings && window.DashboardSettings.openButtons) window.DashboardSettings.openButtons();
        });
        if (openBackgroundsBtn) openBackgroundsBtn.addEventListener('click', function () {
            if (window.DashboardSettings && window.DashboardSettings.openBackgrounds) window.DashboardSettings.openBackgrounds();
        });
        if (openSidebarBtn) openSidebarBtn.addEventListener('click', function () {
            if (window.DashboardSettings && window.DashboardSettings.openSidebar) window.DashboardSettings.openSidebar();
        });
        if (openProgressionBtn) openProgressionBtn.addEventListener('click', function () {
            if (window.DashboardSettings && window.DashboardSettings.openProgressionBars) window.DashboardSettings.openProgressionBars();
        });
        if (openCursorsBtn) openCursorsBtn.addEventListener('click', function () {
            if (window.DashboardSettings && window.DashboardSettings.openCursors) window.DashboardSettings.openCursors();
        });
    }

    function initSecurityDiagramsModal() {
        var diagramsModal = byId('security-diagrams-modal');
        if (!diagramsModal) return;
        diagramsModal.addEventListener('click', function (e) {
            if (e.target === diagramsModal) {
                closeSecurityDiagramsModal();
                return;
            }
            var target = e.target;
            if (target.id === 'security-diagrams-close' || target.closest && target.closest('#security-diagrams-close')) {
                e.preventDefault();
                e.stopPropagation();
                closeSecurityDiagramsModal();
                return;
            }
            if (target.id === 'security-diagrams-back-btn' || (target.closest && target.closest('#security-diagrams-back-btn'))) {
                e.preventDefault();
                e.stopPropagation();
                exitSecurityDiagramsFullscreen();
                return;
            }
            var tab = target.classList && target.classList.contains('security-diagram-tab') ? target : (target.closest && target.closest('.security-diagram-tab'));
            if (tab) {
                var diagram = tab.getAttribute('data-diagram');
                if (diagram) {
                    e.preventDefault();
                    e.stopPropagation();
                    switchSecurityDiagramTab(diagram);
                }
                return;
            }
        });
        var expandBtn = byId('security-diagrams-expand-btn');
        if (expandBtn) expandBtn.addEventListener('click', function (e) { e.preventDefault(); enterSecurityDiagramsFullscreen(); });
        var fullscreenCloseBtn = byId('security-diagrams-fullscreen-close');
        if (fullscreenCloseBtn) fullscreenCloseBtn.addEventListener('click', function (e) { e.preventDefault(); exitSecurityDiagramsFullscreen(); });
        var backBtn = byId('security-diagrams-back-btn');
        if (backBtn) backBtn.addEventListener('click', function (e) { e.preventDefault(); exitSecurityDiagramsFullscreen(); });
        var bandInfoClose = byId('security-diagram-band-info-close');
        if (bandInfoClose) bandInfoClose.addEventListener('click', function (e) { e.preventDefault(); closeBandInfo(); });
        var bandInfoModal = byId('security-diagram-band-info-modal');
        if (bandInfoModal) bandInfoModal.addEventListener('click', function (e) {
            if (e.target === bandInfoModal) closeBandInfo();
        });
        var boxInfoClose = byId('security-diagram-box-info-close');
        if (boxInfoClose) boxInfoClose.addEventListener('click', function (e) { e.preventDefault(); closeDiagramBoxInfo(); });
        var boxInfoModal = byId('security-diagram-box-info-modal');
        if (boxInfoModal) boxInfoModal.addEventListener('click', function (e) {
            if (e.target === boxInfoModal) closeDiagramBoxInfo();
        });
        document.querySelectorAll('.security-diagram-box-info-tab').forEach(function (tab) {
            tab.addEventListener('click', function () {
                var t = this.getAttribute('data-tab');
                if (!t) return;
                document.querySelectorAll('.security-diagram-box-info-tab').forEach(function (x) { x.classList.remove('active'); });
                this.classList.add('active');
                document.querySelectorAll('.security-diagram-box-info-panel').forEach(function (p) { p.style.display = 'none'; });
                var panel = byId('security-diagram-box-info-' + t);
                if (panel) panel.style.display = 'block';
            });
        });
        document.querySelectorAll('.security-diagram-tab').forEach(function (tab) {
            tab.addEventListener('click', function (e) {
                if (this.classList.contains('security-diagram-workflow-parent')) {
                    e.preventDefault();
                    e.stopPropagation();
                    var sublist = byId('security-diagram-workflow-sublist');
                    if (sublist) sublist.style.display = sublist.style.display === 'none' || !sublist.style.display ? 'flex' : 'none';
                    switchSecurityDiagramTab('workflow');
                    return;
                }
                var diagram = this.getAttribute('data-diagram');
                if (diagram) switchSecurityDiagramTab(diagram);
            });
        });
        document.querySelectorAll('.security-diagram-workflow-option').forEach(function (opt) {
            opt.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                var chart = this.getAttribute('data-chart');
                window._selectedWorkflowChart = chart;
                document.querySelectorAll('.security-diagram-workflow-option').forEach(function (o) { o.classList.remove('active'); });
                this.classList.add('active');
                document.querySelectorAll('.security-diagram-tab').forEach(function (t) { t.classList.remove('active'); });
                var wfBtn = byId('security-diagram-workflow-btn');
                if (wfBtn) wfBtn.classList.add('active');
                switchSecurityDiagramTab('workflow');
                updateWorkflowPanelDisplay();
                /* Auto-enter fullscreen so the chart loads immediately */
                var dlg = byId('security-diagrams-dialog');
                if (dlg && !dlg.classList.contains('security-diagrams-fullscreen')) {
                    enterSecurityDiagramsFullscreen();
                } else if (dlg && dlg.classList.contains('security-diagrams-fullscreen')) {
                    loadViewerContentForDiagram('workflow');
                }
            });
        });
        var workflowExpandBtn = byId('security-diagram-workflow-expand-btn');
        if (workflowExpandBtn) workflowExpandBtn.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            enterSecurityDiagramsFullscreen();
        });
        ensureWebSecurityDiagramRendered();
        attachUsersBoxClicks();
        attachSchedulesBoxClicks();
        attachPasswordBoxClicks();
        attachAgentsBoxClicks();
        attachThreatModelBoxClicks();
    }
    function attachThreatModelBoxClicks() {
        var panel = byId('security-diagram-threat_model');
        if (!panel) return;
        panel.querySelectorAll('.security-diagram-stack-list .diagram-box[data-threat-id], .threat-model-column .diagram-box[data-threat-id]').forEach(function (el) {
            var threatId = parseInt(el.getAttribute('data-threat-id'), 10);
            if (threatId >= 1 && threatId <= 28) {
                el.style.cursor = 'pointer';
                el.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    showThreatModelInfo(threatId, e);
                });
                el.addEventListener('dblclick', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    showDiagramBoxInfo((el.textContent || '').trim(), 'threat_model', 0, el, threatId);
                });
            }
        });
    }

    function initDebugToggle() {
        document.addEventListener('keydown', function (e) {
            if (e.key === 'F3') {
                e.preventDefault();
                var dp = byId('debug-panel');
                if (dp) dp.style.display = (dp.style.display === 'none' || !dp.style.display) ? 'block' : 'none';
            }
        });
    }

    function tabDebugLog(lines) {
        var msg = Array.isArray(lines) ? lines.join('\n') : String(lines);
        if (typeof console !== 'undefined' && console.log) console.log('[Dashboard Tab Debug]\n' + msg);
        var dp = byId('debug-panel');
        if (dp) {
            dp.setAttribute('data-tab-debug', msg);
            dp.innerHTML = '<pre style="margin:0;white-space:pre-wrap;font-size:12px;">' + msg.replace(/</g, '&lt;') + '</pre>';
            /* Keep panel hidden by default; user can press F3 to show it */
        }
    }

    window.DashboardTabs = {
        showPanel: showPanel,
        renderTab: function (tabId) {
            if (tabId === 'agent_overview') {
                return;
            }
            if (tabId === 'users' && window.DashboardTabUsers && window.DashboardTabUsers.render) {
                window.DashboardTabUsers.render(byId('panel-users'));
            } else if (tabId === 'error_logs' && window.DashboardTabErrorLogs && window.DashboardTabErrorLogs.render) {
                window.DashboardTabErrorLogs.render(byId('panel-error_logs'));
            } else if (tabId === 'job_status' && window.DashboardTabJobStatus && window.DashboardTabJobStatus.render) {
                window.DashboardTabJobStatus.render(byId('panel-job_status'));
            } else if (tabId === 'monitoring_ui' && window.DashboardTabMonitoringUI && window.DashboardTabMonitoringUI.render) {
                window.DashboardTabMonitoringUI.render(byId('panel-monitoring_ui'));
            } else if (tabId === 'parameter_control' && window.DashboardTabParameterControl && window.DashboardTabParameterControl.render) {
                window.DashboardTabParameterControl.render(byId('panel-parameter_control'));
            } else if (tabId === 'api_authorization' && window.DashboardTabApiAuth && window.DashboardTabApiAuth.render) {
                window.DashboardTabApiAuth.render(byId('panel-api_authorization'));
            } else if (tabId === 'approval_queue' && window.DashboardTabApprovalQueue && window.DashboardTabApprovalQueue.render) {
                window.DashboardTabApprovalQueue.render(byId('panel-approval_queue'));
            } else if (tabId === 'audit' && window.DashboardTabAudit && window.DashboardTabAudit.render) {
                window.DashboardTabAudit.render(byId('panel-audit'));
            } else if (tabId === 'integrity_gate' && window.DashboardTabIntegrityGate && window.DashboardTabIntegrityGate.render) {
                window.DashboardTabIntegrityGate.render(byId('panel-integrity_gate'));
            } else if (tabId === 'job_lifecycle' && window.DashboardTabJobLifecycle && window.DashboardTabJobLifecycle.render) {
                window.DashboardTabJobLifecycle.render(byId('panel-job_lifecycle'));
            } else if (tabId === 'frequency' && window.DashboardTabFrequency && window.DashboardTabFrequency.render) {
                window.DashboardTabFrequency.render(byId('panel-frequency'));
            } else if (tabId === 'metrics' && window.DashboardTabMetrics && window.DashboardTabMetrics.render) {
                window.DashboardTabMetrics.render(byId('panel-metrics'));
            } else if (tabId === 'settings') {
                /* Settings panel content is static; buttons bound in initSettings */
                showSettingsMainView();
            }
        },
        init: function () {
            /* Ensure Security Diagrams modal is closed on load – opened only from Settings → Security → Security Diagrams */
            if (typeof closeSecurityDiagramsModal === 'function') closeSecurityDiagramsModal();
            initSidebar();
            initClock();
            initSecurityDiagramsModal();
            initSettings();
            initDebugToggle();
            initActiveTasksClick();
            initLogoutButton();
            var initialTab = 'welcome';
            var validTabs = ['welcome', 'agent_overview', 'error_logs', 'job_status', 'monitoring_ui', 'parameter_control', 'api_authorization', 'approval_queue', 'audit', 'integrity_gate', 'job_lifecycle', 'metrics', 'users', 'settings', 'workflows', 'frequency', 'benchmark'];
            // Path takes precedence: direct navigation to /monitoring_ui etc. must show that tab
            var pathToTab = {
                '/': 'welcome',
                '/error_logs': 'error_logs',
                '/job_status': 'job_status',
                '/monitoring_ui': 'monitoring_ui',
                '/parameter_control': 'parameter_control',
                '/approval_queue': 'approval_queue',
                '/audit': 'audit',
                '/integrity_gate': 'integrity_gate',
                '/job_lifecycle': 'job_lifecycle',
                '/metrics': 'metrics',
                '/workflows': 'workflows',
                '/frequency': 'frequency',
                '/settings': 'settings',
                '/benchmark': 'benchmark'
            };
            var pathTab = pathToTab[window.location.pathname];
            var storedTab = null;
            try { storedTab = sessionStorage.getItem('dashboardOpenTab'); } catch (e) {}
            var params = new URLSearchParams(window.location.search);
            var tabParam = params.get('tab');

            /* When pathname is /, ?tab= overrides path (e.g. /?tab=agent_overview) */
            if (window.location.pathname === '/' && tabParam !== null && tabParam !== '' && validTabs.indexOf(tabParam) !== -1) {
                initialTab = tabParam;
            } else if (pathTab && validTabs.indexOf(pathTab) !== -1) {
                initialTab = pathTab;
            } else if (tabParam !== null && tabParam !== '') {
                if (validTabs.indexOf(tabParam) !== -1) initialTab = tabParam;
            } else if (typeof window.DASHBOARD_INITIAL_TAB === 'string' && window.DASHBOARD_INITIAL_TAB !== '') {
                if (validTabs.indexOf(window.DASHBOARD_INITIAL_TAB) !== -1) initialTab = window.DASHBOARD_INITIAL_TAB;
            }
            if (initialTab === undefined && storedTab && validTabs.indexOf(storedTab) !== -1) {
                initialTab = storedTab;
                try { sessionStorage.removeItem('dashboardOpenTab'); } catch (e) {}
            }
            if (initialTab === undefined || initialTab === '' || validTabs.indexOf(initialTab) === -1) {
                initialTab = 'welcome';
            }
            /* welcome is the blank home screen — keep it as-is */

            var debugLines = [
                'pathname: ' + window.location.pathname,
                'pathTab (from path): ' + (pathTab == null ? 'null' : pathTab),
                'DASHBOARD_INITIAL_TAB: ' + (typeof window.DASHBOARD_INITIAL_TAB === 'string' ? window.DASHBOARD_INITIAL_TAB : '(not set)'),
                'storedTab: ' + (storedTab || 'null'),
                'tabParam (?tab=): ' + (tabParam || 'null'),
                'final initialTab: ' + initialTab,
                'panel-' + initialTab + ' exists: ' + !!byId('panel-' + initialTab),
                'DashboardTabMonitoringUI: ' + !!(window.DashboardTabMonitoringUI && window.DashboardTabMonitoringUI.render)
            ];
            showPanel(initialTab);
            if (initialTab === 'settings') {
                showSettingsMainView();
            }
            var panelEl = byId('panel-' + initialTab);
            debugLines.push('after showPanel - panel display: ' + (panelEl ? window.getComputedStyle(panelEl).display : 'N/A'));
            var settingsMain = byId('dashboard-settings-main');
            debugLines.push('dashboard-settings-main computed: ' + (settingsMain ? window.getComputedStyle(settingsMain).display : 'NOT FOUND'));
            debugLines.push('dashboard-settings-main inline: ' + (settingsMain ? (settingsMain.style.cssText || 'none') : 'N/A'));
            var aoPanel = byId('panel-agent_overview');
            debugLines.push('panel-agent_overview display: ' + (aoPanel ? window.getComputedStyle(aoPanel).display : 'N/A'));
            tabDebugLog(debugLines);

            if (window.DashboardTabs && window.DashboardTabs.renderTab) {
                window.DashboardTabs.renderTab(initialTab);
            }
            if (window.history && window.history.replaceState) {
                history.replaceState({ dashboardTab: initialTab }, '', window.location.pathname + window.location.search);
            }
            // Re-apply panel visibility on next tick so we override any other script that might show agent_overview
            if (initialTab !== 'agent_overview') {
                setTimeout(function () {
                    showPanel(initialTab);
                    if (initialTab === 'settings') {
                        showSettingsMainView();
                    }
                    if (window.DashboardTabs && window.DashboardTabs.renderTab) {
                        window.DashboardTabs.renderTab(initialTab);
                    }
                }, 0);
            }
        }
    };

    function initClock() {
        var clockTime = byId('clock-time');
        var clockDate = byId('clock-date');
        if (!clockTime || !clockDate) return;
        function updateClock() {
            var manual = localStorage.getItem('dashboard_clock_manual');
            var tz = localStorage.getItem('dashboard_clock_timezone') || 'Europe/Amsterdam';
            var displayDate;
            if (manual === '1') {
                var stored = localStorage.getItem('dashboard_clock_datetime');
                var savedAt = parseInt(localStorage.getItem('dashboard_clock_manual_saved_at'), 10);
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
            var tzOpts = (tz && tz !== 'Local') ? { timeZone: tz } : {};
            clockTime.textContent = displayDate.toLocaleTimeString('en-GB', Object.assign({ hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }, tzOpts));
            clockDate.textContent = displayDate.toLocaleDateString('en-GB', Object.assign({ year: 'numeric', month: '2-digit', day: '2-digit' }, tzOpts));
        }
        setInterval(updateClock, 1000);
        updateClock();
    }

    function initLogoutButton() {
        var btn = byId('dashboard-sidebar-logout');
        if (!btn) return;
        btn.title = 'Logout';
        if (btn.tagName !== 'A') {
            btn.addEventListener('click', function () { window.location.href = '/logout'; });
        }
    }

    function initActiveTasksClick() {
        var activeAgentsWrap = byId('dashboard-overview-active-agents-wrap');
        if (activeAgentsWrap) {
            activeAgentsWrap.style.cursor = 'pointer';
            activeAgentsWrap.addEventListener('click', function () {
                window.location.href = '/monitoring_ui';
            });
        }
        var wrap = byId('dashboard-overview-active-tasks-wrap');
        if (wrap) {
            wrap.style.cursor = 'pointer';
            wrap.addEventListener('click', function () {
                showPanel('job_status');
                if (window.DashboardTabs && window.DashboardTabs.renderTab) {
                    window.DashboardTabs.renderTab('job_status');
                }
                if (window.history && window.history.pushState) {
                    history.pushState({ dashboardTab: 'job_status' }, '', window.location.pathname + window.location.search);
                }
            });
        }
        var plannedWrap = byId('dashboard-overview-planned-wrap');
        if (plannedWrap) {
            plannedWrap.style.cursor = 'pointer';
            plannedWrap.addEventListener('click', function () {
                try { sessionStorage.setItem('dashboardMonitoringList', 'planned'); } catch (e) {}
                window.location.href = '/monitoring_ui';
            });
        }
        var gpuWrap = byId('dashboard-overview-gpu-wrap');
        if (gpuWrap) {
            gpuWrap.style.cursor = 'pointer';
            gpuWrap.addEventListener('click', function () {
                showPanel('parameter_control');
                if (window.DashboardTabs && window.DashboardTabs.renderTab) {
                    window.DashboardTabs.renderTab('parameter_control');
                }
                setTimeout(function () {
                    if (window.DashboardTabParameterControl && window.DashboardTabParameterControl.setMode) {
                        window.DashboardTabParameterControl.setMode('gpu');
                    } else {
                        var gpuBtn = document.querySelector('.parameter-control-mode[data-mode="gpu"]');
                        if (gpuBtn) gpuBtn.click();
                    }
                }, 100);
                if (window.history && window.history.pushState) {
                    history.pushState({ dashboardTab: 'parameter_control' }, '', window.location.pathname + window.location.search);
                }
            });
        }
        var cpuWrap = byId('dashboard-overview-cpu-wrap');
        if (cpuWrap) {
            cpuWrap.style.cursor = 'pointer';
            cpuWrap.addEventListener('click', function () {
                window.location.href = '/job_status';
            });
        }
    }

    // Path -> tab mapping so popstate respects URL (e.g. /settings stays on settings)
    var PATH_TO_TAB = {
        '/': 'welcome',
        '/error_logs': 'error_logs',
        '/job_status': 'job_status',
        '/monitoring_ui': 'monitoring_ui',
        '/parameter_control': 'parameter_control',
        '/approval_queue': 'approval_queue',
        '/audit': 'audit',
        '/integrity_gate': 'integrity_gate',
        '/job_lifecycle': 'job_lifecycle',
        '/metrics': 'metrics',
        '/settings': 'settings',
        '/workflows': 'workflows'
    };
    window.addEventListener('popstate', function (e) {
        var dialog = byId('security-diagrams-dialog');
        if (dialog && dialog.classList.contains('security-diagrams-fullscreen')) {
            exitSecurityDiagramsFullscreen();
            return;
        }
        var state = e.state;
        if (state && state.dashboardSettingsView === 'users') {
            showSettingsUsersView();
            return;
        }
        if (state && state.dashboardSettingsView === 'main') {
            showSettingsMainView();
            return;
        }
        if (state && state.dashboardTab) {
            showPanel(state.dashboardTab);
            if (window.DashboardTabs && window.DashboardTabs.renderTab) {
                window.DashboardTabs.renderTab(state.dashboardTab);
            }
            return;
        }
        showSettingsMainView();
        // When state has no dashboardTab (e.g. back from schedule page), use current path so /settings shows settings
        var pathname = window.location.pathname || '';
        var tabFromPath = PATH_TO_TAB[pathname];
        if (tabFromPath) {
            showPanel(tabFromPath);
            if (window.DashboardTabs && window.DashboardTabs.renderTab) {
                window.DashboardTabs.renderTab(tabFromPath);
            }
        } else {
            showPanel('welcome');
        }
    });

    function runInit() {
        // Ensure Security Diagrams modal is never open by default (fixes auto-open on load/tab switch)
        if (typeof window.closeSecurityDiagramsModal === 'function') {
            window.closeSecurityDiagramsModal();
        } else {
            var modal = byId('security-diagrams-modal');
            if (modal) modal.style.display = 'none';
        }
        // Fix: ensure dashboard-main is visible (not nested inside display:none modal)
        var main = document.querySelector('.dashboard-main');
        if (main) {
            var parent = main.parentElement;
            while (parent && parent !== document.body) {
                var style = window.getComputedStyle(parent);
                if (style.display === 'none' || style.visibility === 'hidden') {
                    var nav = document.querySelector('.dashboard-sidebar');
                    var insertBefore = null;
                    if (nav) {
                        var sib = nav.nextSibling;
                        while (sib && sib.nodeType !== 1) { sib = sib.nextSibling; }
                        insertBefore = sib;
                    }
                    if (insertBefore) {
                        document.body.insertBefore(main, insertBefore);
                    } else {
                        document.body.appendChild(main);
                    }
                    break;
                }
                parent = parent.parentElement;
            }
        }
        window.DashboardTabs.init();
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', runInit);
    } else {
        runInit();
    }
})();
