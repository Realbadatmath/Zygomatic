// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

        function zygConfirm(title, message, okLabel, onConfirm) {
          var backdrop = document.getElementById('zyg-confirm-backdrop');
          document.getElementById('zyg-confirm-title').textContent = title;
          document.getElementById('zyg-confirm-msg').textContent = message;
          document.getElementById('zyg-confirm-ok').textContent = okLabel || 'Confirm';
          backdrop.style.display = 'flex';
          function cleanup() { backdrop.style.display = 'none'; }
          document.getElementById('zyg-confirm-cancel').onclick = cleanup;
          document.getElementById('zyg-confirm-ok').onclick = function() { cleanup(); onConfirm(); };
          backdrop.onclick = function(e) { if (e.target === backdrop) cleanup(); };
        }

        function dashboardRestartServer(btn) {
          zygConfirm('Restart Server', 'This halts all pipelines, restarts the dashboard (port 5000) and Zero Public / zero.zygomaticszero.com (port 5001), and marks interrupted jobs as failed.', 'Restart', function() {
            // Signal all background pollers (Agent Zero, telemetry, etc.) to stay silent
            window._serverRestarting = true;

            // Show full-screen overlay
            var overlay = document.getElementById('restart-overlay');
            overlay.style.display = 'flex';
            btn.disabled = true;

            // Clear all known background intervals so they don't fire error messages
            if (window._agentZeroPendingPollInterval) { clearInterval(window._agentZeroPendingPollInterval); window._agentZeroPendingPollInterval = null; }
            if (window._dashboardTelemetryInterval)   { clearInterval(window._dashboardTelemetryInterval);   window._dashboardTelemetryInterval   = null; }
            if (window._dashboardContextInterval)     { clearInterval(window._dashboardContextInterval);     window._dashboardContextInterval     = null; }

            // Read CSRF from meta tag (injected by Flask template)
            var csrfToken = (document.querySelector('meta[name="csrf-token"]') || {}).getAttribute('content') || '';
            fetch('/api/restart', {
              method: 'POST',
              credentials: 'same-origin',
              headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken }
            })
            .catch(function() { /* server may close the connection mid-response — that's expected */ })
            .finally(function() {
              // Two-phase poll:
              //   Phase 1 — wait until Flask goes DOWN (catches errors or non-ok).
              //             The script kills Flask ~3-4s after the button click, so
              //             a single-phase poll fired at 2.5s would see the OLD
              //             process still alive and falsely declare success.
              //   Phase 2 — wait until the NEW process comes back UP (200 OK).
              //             Only then redirect to /logout → /login.
              var _wentDown = false;
              var _msgEl    = document.getElementById('restart-overlay-msg');
              setTimeout(function poll() {
                fetch('/api/health', { credentials: 'same-origin', cache: 'no-store' })
                  .then(function(r) {
                    if (!_wentDown) {
                      // Still talking to the OLD process — keep waiting for it to die.
                      setTimeout(poll, 1000);
                      return;
                    }
                    if (!r.ok) { setTimeout(poll, 1500); return; }
                    // NEW process is up — done.
                    if (_msgEl) _msgEl.textContent = 'Restarted. Redirecting to login…';
                    document.getElementById('restart-spinner').style.animation = 'none';
                    document.getElementById('restart-spinner').style.stroke = '#7df9aa';
                    window._serverRestarting = false;
                    setTimeout(function() { window.location.href = '/logout'; }, 1200);
                  })
                  .catch(function() {
                    _wentDown = true;  // Phase 1 complete — server is down.
                    if (_msgEl) _msgEl.textContent = 'Server stopped. Waiting for restart…';
                    setTimeout(poll, 1500);
                  });
              }, 1500);
            });
          });
        }
