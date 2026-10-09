// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Dashboard tab: Integrity Gate — full model & service health hub
 * Shows every model, service, and resource used across all pipeline stages.
 * Auto-refreshes every 20s. Grouped by category with colored status badges.
 * The check list lives server-side in bp_integrity_ops.api_integrity_gate;
 * in the "Licence tripwires" group a pass means the removed weight is absent.
 */
(function () {
    'use strict';

    var _refreshTimer = null;
    var _container = null;

    function esc(s) {
        if (s == null) return '';
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    function statusBadge(status) {
        if (status === 'pass')  return '<span class="ig-badge ig-pass">✅ Pass</span>';
        if (status === 'fail')  return '<span class="ig-badge ig-fail">❌ Fail</span>';
        return '<span class="ig-badge ig-warn">⚠️ Warn</span>';
    }

    function overallBadge(overall, summary) {
        var s = summary || {};
        var label = overall === 'pass' ? '🟢 Healthy'
                  : overall === 'fail' ? '🔴 Degraded'
                  : '🟡 Warning';
        var color = overall === 'pass' ? '#28a745' : overall === 'fail' ? '#dc3545' : '#ffc107';
        var txt   = overall === 'pass' ? '#fff'     : overall === 'fail' ? '#fff'    : '#212529';
        return '<span style="background:' + color + ';color:' + txt + ';padding:4px 14px;border-radius:20px;font-weight:700;font-size:13px;">'
             + label + '</span>'
             + ' <span style="color:#888;font-size:12px;margin-left:8px;">'
             + (s.pass||0) + ' pass &nbsp; ' + (s.warn||0) + ' warn &nbsp; ' + (s.fail||0) + ' fail'
             + ' &nbsp;/ ' + (s.total||0) + ' total</span>';
    }

    function metricCard(title, value, sub, color) {
        return '<div class="ig-card" style="border-top:3px solid ' + color + ';">'
             + '<div class="ig-card-title">' + esc(title) + '</div>'
             + '<div class="ig-card-value" style="color:' + color + ';">' + esc(value) + '</div>'
             + '<div class="ig-card-sub">' + esc(sub) + '</div>'
             + '</div>';
    }

    function renderChecksTable(checks) {
        // Group by category
        var groups = {};
        var order  = [];
        checks.forEach(function(c) {
            var cat = c.category || 'Other';
            if (!groups[cat]) { groups[cat] = []; order.push(cat); }
            groups[cat].push(c);
        });

        var html = '';
        order.forEach(function(cat) {
            var rows = groups[cat];
            var nFail = rows.filter(function(r){ return r.status === 'fail'; }).length;
            var nWarn = rows.filter(function(r){ return r.status === 'warn'; }).length;
            var catColor = nFail > 0 ? '#dc3545' : nWarn > 0 ? '#ffc107' : '#28a745';
            var catIcon  = nFail > 0 ? '❌' : nWarn > 0 ? '⚠️' : '✅';
            html += '<tr class="ig-cat-header">'
                  + '<td colspan="4" style="background:#f8f9fa;font-weight:700;color:' + catColor + ';padding:6px 10px;border-top:2px solid #dee2e6;">'
                  + catIcon + ' ' + esc(cat)
                  + ' <span style="font-weight:400;font-size:11px;color:#888;">'
                  + rows.length + ' checks'
                  + (nFail ? ' · ' + nFail + ' fail' : '')
                  + (nWarn ? ' · ' + nWarn + ' warn' : '')
                  + '</span></td></tr>';
            rows.forEach(function(c) {
                var rowBg = c.status === 'fail' ? '#fff5f5' : c.status === 'warn' ? '#fffdf0' : '';
                html += '<tr style="background:' + rowBg + ';">'
                      + '<td style="padding:5px 10px 5px 22px;font-size:12px;color:#444;">' + esc(c.name) + '</td>'
                      + '<td style="padding:5px 8px;font-size:11px;color:#888;white-space:nowrap;">' + esc(c.stage||'') + '</td>'
                      + '<td style="padding:5px 8px;white-space:nowrap;">' + statusBadge(c.status) + '</td>'
                      + '<td style="padding:5px 8px;font-size:11px;color:#555;word-break:break-word;max-width:420px;">' + esc(c.detail||'') + '</td>'
                      + '</tr>';
            });
        });
        return html;
    }

    function render(container) {
        if (!container) return;
        _container = container;
        if (_refreshTimer) clearInterval(_refreshTimer);

        container.innerHTML =
            '<style>'
            + '.ig-header{display:flex;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:14px;}'
            + '.ig-cards{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px;}'
            + '.ig-card{background:#fff;border:1px solid #dee2e6;border-radius:8px;padding:10px 16px;min-width:140px;flex:1;}'
            + '.ig-card-title{font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px;}'
            + '.ig-card-value{font-size:22px;font-weight:700;line-height:1;}'
            + '.ig-card-sub{font-size:11px;color:#aaa;margin-top:3px;}'
            + '.ig-badge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:600;}'
            + '.ig-pass{background:#d4edda;color:#155724;}'
            + '.ig-warn{background:#fff3cd;color:#856404;}'
            + '.ig-fail{background:#f8d7da;color:#721c24;}'
            + '.ig-cat-header td{user-select:none;}'
            + '.ig-alert-box{background:#fff8e1;border:1px solid #ffc107;border-radius:6px;padding:10px 14px;margin-bottom:12px;font-size:12px;}'
            + '.ig-blocked-box{background:#f8d7da;border:1px solid #dc3545;border-radius:6px;padding:10px 14px;margin-bottom:12px;}'
            + '.ig-section-title{font-weight:700;font-size:13px;color:#495057;margin:14px 0 6px;}'
            + '.ig-cb-box{background:#f8f9fa;border:1px solid #dee2e6;border-radius:6px;padding:10px 14px;margin-bottom:12px;font-size:12px;}'
            + '</style>'
            + '<div class="parameter-control-table-wrap">'
            + '<div class="ig-header">'
            + '  <h3 class="dashboard-monitoring-title" style="margin:0;">Integrity Gate</h3>'
            + '  <div id="ig-overall">Loading…</div>'
            + '  <div style="margin-left:auto;display:flex;align-items:center;gap:8px;">'
            + '    <span id="ig-last-checked" style="font-size:11px;color:#aaa;"></span>'
            + '    <button type="button" class="btn btn-sm btn-secondary" id="ig-refresh-btn" style="font-size:11px;padding:3px 10px;">⟳ Refresh</button>'
            + '  </div>'
            + '</div>'
            + '<div id="ig-blocked" style="display:none;" class="ig-blocked-box"></div>'
            + '<div class="ig-cards" id="ig-cards"></div>'
            + '<div id="ig-schedule-bar" style="margin-bottom:10px;"></div>'
            + '<table class="dashboard-table" style="width:100%;">'
            + '  <thead><tr>'
            + '    <th style="width:22%;">Component / Model</th>'
            + '    <th style="width:14%;">Used by</th>'
            + '    <th style="width:9%;">Status</th>'
            + '    <th>Detail</th>'
            + '  </tr></thead>'
            + '  <tbody id="ig-tbody"><tr><td colspan="4" style="text-align:center;padding:24px;color:#888;">Loading checks…</td></tr></tbody>'
            + '</table>'
            + '<div id="ig-circuit-breaker" style="margin-top:16px;"></div>'
            + '<div id="ig-actions" style="margin-top:12px;"></div>'
            + '</div>';

        document.getElementById('ig-refresh-btn').addEventListener('click', function() { loadData(); });

        _refreshTimer = setInterval(loadData, 20000);
        loadData();
    }

    function loadData() {
        Promise.all([
            fetch('/api/integrity-gate', {credentials:'same-origin'}).then(function(r){ return r.json(); }).catch(function(){ return null; }),
            fetch('/api/admin/schedule-pause', {credentials:'same-origin'}).then(function(r){ return r.ok ? r.json() : {paused:false}; }).catch(function(){ return {paused:false}; })
        ]).then(function(results) {
            var data      = results[0];
            var pauseData = results[1] || {};
            if (!data) {
                document.getElementById('ig-overall').innerHTML = '<span style="color:#c00;">Failed to load</span>';
                return;
            }
            applyData(data, pauseData);
        });
    }

    function applyData(data, pauseData) {
        var overall  = data.overall || 'warn';
        var summary  = data.summary || {};
        var stats    = data.stats   || {};
        var cb       = data.circuit_breaker || {};
        var lp       = data.last_pipeline || {};
        var checks   = data.checks || [];
        var lastChk  = data.last_checked || '';
        var elapsed  = data.elapsed_ms || 0;

        // Overall badge
        var ogEl = document.getElementById('ig-overall');
        if (ogEl) ogEl.innerHTML = overallBadge(overall, summary);

        // Last checked
        var lcEl = document.getElementById('ig-last-checked');
        if (lcEl) lcEl.textContent = lastChk ? 'Checked ' + lastChk.replace('T',' ') + ' (' + elapsed + 'ms)' : '';

        // Blocked banner
        var blk = document.getElementById('ig-blocked');
        if (blk) {
            if (data.blocked_reason) {
                blk.style.display = 'block';
                blk.innerHTML = '<strong>⛔ Blocked:</strong> ' + esc(data.blocked_reason);
            } else {
                blk.style.display = 'none';
            }
        }

        // Metric cards — extract live values from checks
        var vramChk = checks.find(function(c){ return c.name === 'GPU VRAM'; }) || {};
        var ramChk  = checks.find(function(c){ return c.name === 'System RAM'; }) || {};
        var diskChk = checks.find(function(c){ return c.name === 'Disk space'; }) || {};

        function extractFirst(detail, re) {
            if (!detail) return '—';
            var m = detail.match(re);
            return m ? m[1] : '—';
        }

        var vramFree  = extractFirst(vramChk.detail, /([\d.]+)\s*GB free/);
        var vramTotal = extractFirst(vramChk.detail, /\/\s*([\d.]+)\s*GB total/);
        var ramFree   = extractFirst(ramChk.detail,  /([\d.]+)\s*GB available/);
        var ramTotal  = extractFirst(ramChk.detail,  /\/\s*([\d.]+)\s*GB total/);
        var diskFree  = extractFirst(diskChk.detail, /([\d.]+)\s*GB free/);

        var vramColor = vramChk.status === 'pass' ? '#28a745' : vramChk.status === 'fail' ? '#dc3545' : '#ffc107';
        var ramColor  = ramChk.status  === 'pass' ? '#28a745' : ramChk.status  === 'fail' ? '#dc3545' : '#ffc107';
        var diskColor = diskChk.status === 'pass' ? '#28a745' : diskChk.status === 'fail' ? '#dc3545' : '#ffc107';
        var pipeColor = stats.running > 0 ? '#007bff' : '#28a745';

        var nFail = summary.fail || 0;
        var svcColor = nFail > 0 ? '#dc3545' : (summary.warn > 0 ? '#ffc107' : '#28a745');

        var cardsEl = document.getElementById('ig-cards');
        if (cardsEl) {
            cardsEl.innerHTML =
                metricCard('GPU VRAM', vramFree + ' GB', 'free of ' + vramTotal + ' GB', vramColor) +
                metricCard('System RAM', ramFree + ' GB', 'available of ' + ramTotal + ' GB', ramColor) +
                metricCard('Disk', diskFree + ' GB', 'free on the home partition', diskColor) +
                metricCard('Pipelines', stats.running || '0', (stats.running||0) + ' running · ' + (stats.failed||0) + ' failed', pipeColor) +
                metricCard('Services', (summary.pass||0) + '/' + (summary.total||0), nFail + ' failing · ' + (summary.warn||0) + ' warning', svcColor) +
                metricCard('Last Pipeline', lp.status || '—', (lp.department||'') + (lp.topic ? ' — ' + lp.topic.substring(0,30) : ''),
                           lp.status === 'completed' ? '#28a745' : lp.status === 'failed' ? '#dc3545' : '#007bff');
        }

        // Schedule bar
        var sbEl = document.getElementById('ig-schedule-bar');
        if (sbEl) {
            var paused = pauseData.paused || data.paused;
            sbEl.innerHTML = '<strong>Schedule:</strong> '
                + (paused
                    ? '<span style="color:#dc3545;font-weight:700;">⏸ Paused</span>'
                    + (pauseData.reason ? ' — ' + esc(pauseData.reason) : '')
                    : '<span style="color:#28a745;font-weight:700;">▶ Running</span>')
                + ' &nbsp;|&nbsp; Running: ' + (stats.running||0)
                + ' &nbsp; Completed: ' + (stats.completed||0)
                + ' &nbsp; Failed: ' + (stats.failed||0)
                + ' &nbsp; Queued: ' + (stats.queued||0);
        }

        // Checks table
        var tbodyEl = document.getElementById('ig-tbody');
        if (tbodyEl) {
            if (!checks.length) {
                tbodyEl.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:24px;color:#888;">No checks returned.</td></tr>';
            } else {
                tbodyEl.innerHTML = renderChecksTable(checks);
            }
        }

        // Circuit breaker
        var cbEl = document.getElementById('ig-circuit-breaker');
        if (cbEl) {
            var cbState  = cb.state || 'ok';
            var cbAlerts = cb.alerts || [];
            var cbColor  = cbState === 'tripped' ? '#dc3545' : '#28a745';
            var cbLabel  = cbState === 'tripped' ? '🔴 TRIPPED — auto-paused' : '🟢 Normal';
            var alertsHtml = cbAlerts.length
                ? '<div style="margin-top:6px;font-family:monospace;font-size:11px;color:#555;max-height:120px;overflow-y:auto;">'
                  + cbAlerts.map(function(a){ return esc(a); }).join('<br>') + '</div>'
                : '<span style="color:#aaa;font-size:11px;">No alerts logged.</span>';
            cbEl.innerHTML = '<div class="ig-section-title">Circuit Breaker</div>'
                + '<div class="ig-cb-box">'
                + '<strong style="color:' + cbColor + ';">' + cbLabel + '</strong>'
                + ' &nbsp; <span style="font-size:11px;color:#888;">Recent alerts (last 15 lines of integrity_alerts.log):</span>'
                + alertsHtml
                + '</div>';
        }

        // Admin actions
        var actEl = document.getElementById('ig-actions');
        if (actEl && window.DASHBOARD_USER_ROLE === 'admins') {
            var paused = pauseData.paused;
            if (paused) {
                actEl.innerHTML = '<button type="button" class="btn dashboard-btn" id="ig-resume-btn">Force Override — Resume Schedule</button>';
                var rBtn = document.getElementById('ig-resume-btn');
                if (rBtn) rBtn.addEventListener('click', function() {
                    rBtn.disabled = true;
                    fetch('/api/integrity-gate/force-override', {
                        method: 'POST', credentials: 'same-origin',
                        headers: {'Content-Type':'application/json'},
                        body: JSON.stringify({action:'resume', reason:'Admin force resume'})
                    }).then(function(r){ return r.json(); })
                      .then(function(d){ if (d.success) loadData(); else alert('Error: ' + d.error); })
                      .finally(function(){ rBtn.disabled = false; });
                });
            } else {
                actEl.innerHTML = '<button type="button" class="btn btn-secondary" id="ig-pause-btn">Pause Schedule</button>';
                var pBtn = document.getElementById('ig-pause-btn');
                if (pBtn) pBtn.addEventListener('click', function() {
                    pBtn.disabled = true;
                    fetch('/api/admin/schedule-pause', {
                        method: 'POST', credentials: 'same-origin',
                        headers: {'Content-Type':'application/json'},
                        body: JSON.stringify({paused:true, reason:'Manual admin pause'})
                    }).then(function(r){ return r.json(); })
                      .then(function(d){ if (d.success||d.paused) loadData(); else alert('Error: ' + (d.error||'Unknown')); })
                      .finally(function(){ pBtn.disabled = false; });
                });
            }
        } else if (actEl) {
            actEl.innerHTML = '';
        }
    }

    // Cleanup on tab switch
    window.DashboardTabIntegrityGate = {
        render: render,
        destroy: function() { if (_refreshTimer) { clearInterval(_refreshTimer); _refreshTimer = null; } }
    };
})();
