// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Parameter Control: live view of CPU/GPU assigned vs usage from schedule entries.
 * Fetches GPU and CPU timeline data, builds tables with Performance and % Overall.
 */
(function () {
    'use strict';

    function byId(id) { return document.getElementById(id); }

    function performanceLabel(assigned, usage) {
        if (assigned == null || assigned === '' || isNaN(parseFloat(assigned))) return '—';
        var a = parseFloat(assigned);
        var u = (usage != null && usage !== '' && !isNaN(parseFloat(usage))) ? parseFloat(usage) : a;
        if (a <= 0) return '—';
        var ratio = u / a;
        if (ratio <= 0.80) return 'High';
        if (ratio <= 1.05) return 'Normal';
        if (ratio <= 1.25) return 'Low';
        return 'Poor';
    }

    function percentOverall(assigned, usage) {
        if (assigned == null || assigned === '' || isNaN(parseFloat(assigned))) return '—';
        var a = parseFloat(assigned);
        var u = (usage != null && usage !== '' && !isNaN(parseFloat(usage))) ? parseFloat(usage) : a;
        if (a === 0) return '—';
        var diff = ((u - a) / a * 100);
        var sign = diff >= 0 ? '+' : '';
        return sign + diff.toFixed(1) + '%';
    }

    function circleHtml(value, label) {
        var num = (value != null && value !== '' && !isNaN(parseFloat(value))) ? parseFloat(value) : 0;
        var percent = num > 100 ? 100 : (num < 0 ? 0 : num);
        var r = 50;
        var c = 2 * Math.PI * r;
        var offset = c - (percent / 100) * c;
        var displayVal = num.toFixed(1) + '%';
        return '<div class="dashboard-overview-circle-wrap"><div class="dashboard-circle-wrap">' +
            '<svg class="dashboard-circle-svg" viewBox="0 0 120 120">' +
            '<circle class="dashboard-circle-bg" cx="60" cy="60" r="' + r + '"/>' +
            '<circle class="dashboard-circle-mover" cx="60" cy="60" r="' + r + '"/>' +
            '<circle class="dashboard-circle-fill" cx="60" cy="60" r="' + r + '" stroke-dasharray="' + c + '" stroke-dashoffset="' + offset + '"/>' +
            '</svg>' +
            '<span class="dashboard-circle-value">' + displayVal + '</span>' +
            '<span class="dashboard-circle-label">' + (label || '') + '</span>' +
            '</div></div>';
    }

    function getRealUsageFromTelemetry(telemetry) {
        if (!telemetry || telemetry.error) return null;
        var cpu = (telemetry.cpu_pct != null && !isNaN(parseFloat(telemetry.cpu_pct))) ? parseFloat(telemetry.cpu_pct) : null;
        var gpu = null;
        var vram = null;
        if (telemetry.gpus && telemetry.gpus.length) {
            var maxUtil = 0;
            var maxVram = 0;
            telemetry.gpus.forEach(function (g) {
                var u = (g.utilization_pct != null && !isNaN(parseFloat(g.utilization_pct))) ? parseFloat(g.utilization_pct) : (g.memory_pct != null ? parseFloat(g.memory_pct) : 0);
                if (u > maxUtil) maxUtil = u;
                var v = (g.memory_pct != null && !isNaN(parseFloat(g.memory_pct))) ? parseFloat(g.memory_pct) : 0;
                if (v > maxVram) maxVram = v;
            });
            gpu = maxUtil;
            vram = maxVram > 0 ? maxVram : null;
        }
        return { cpu: cpu, gpu: gpu, vram: vram };
    }

    function updateCircles(rows, telemetry) {
        var real = getRealUsageFromTelemetry(telemetry);
        var totalCpu = real && real.cpu != null ? real.cpu : 0;
        var totalGpu = real && real.gpu != null ? real.gpu : 0;
        var totalVram = real && real.vram != null ? real.vram : 0;
        if (real === null) {
            rows.forEach(function (r) {
                if (r.cpu_usage !== '' && r.cpu_usage != null) totalCpu += parseFloat(r.cpu_usage) || 0;
                if (r.gpu_usage !== '' && r.gpu_usage != null) totalGpu += parseFloat(r.gpu_usage) || 0;
                if (r.vram_usage !== '' && r.vram_usage != null) totalVram += parseFloat(r.vram_usage) || 0;
            });
        }
        var bothEl = byId('parameter-control-both-circles');
        var cpuEl = byId('parameter-control-cpu-circles');
        var gpuEl = byId('parameter-control-gpu-circles');
        var vram3dEl = byId('parameter-control-3d-circles');
        var cpuLabel = (real && real.cpu != null) ? 'CPU % (live)' : 'CPU %';
        var gpuLabel = (real && real.gpu != null) ? 'GPU % (live)' : 'GPU %';
        var vramLabel = (real && real.vram != null) ? 'VRAM % (live)' : 'VRAM %';
        if (bothEl) bothEl.innerHTML = circleHtml(totalCpu, cpuLabel) + circleHtml(totalGpu, gpuLabel) + circleHtml(totalVram, vramLabel);
        if (cpuEl) cpuEl.innerHTML = circleHtml(totalCpu, cpuLabel);
        if (gpuEl) gpuEl.innerHTML = circleHtml(totalGpu, gpuLabel);
        if (vram3dEl) vram3dEl.innerHTML = circleHtml(totalVram, vramLabel);
    }

    function render() {
        var today = new Date().toISOString().slice(0, 10);
        Promise.all([
            fetch('/api/gpu/timeline/24h').then(function (r) { return r.json(); }),
            fetch('/api/cpu/timeline/24h').then(function (r) { return r.json(); }),
            fetch('/api/telemetry').then(function (r) {
                if (!r.ok) return { cpu_pct: 0, ram_pct: 0, gpus: [], error: 'Telemetry unavailable' };
                return r.json();
            }).catch(function () { return null; }),
            fetch('/api/jobs/runs?status_filter=running').then(function (r) { return r.ok ? r.json() : { items: [] }; }).catch(function () { return { items: [] }; })
        ]).then(function (results) {
            var gpuData = results[0].entries || [];
            var cpuData = results[1].entries || [];
            var telemetry = results[2];
            var runsData = results[3].items || [];

            /* Active claims (runtime truth): who holds a lease right now */
            var claimsEl = byId('parameter-control-claims-count');
            var claimsListEl = byId('parameter-control-claims-list');
            if (claimsEl) claimsEl.textContent = '(' + runsData.length + ' running with lease)';
            if (claimsListEl) {
                if (runsData.length === 0) {
                    claimsListEl.innerHTML = '<span style="color:#888;">No active claims. See Job Lifecycle for full run state.</span>';
                } else {
                    claimsListEl.innerHTML = runsData.map(function (r) {
                        var rid = (r.id != null ? String(r.id) : '');
                        var w = (r.worker_id != null ? String(r.worker_id) : '—').substring(0, 24);
                        var lease = r.lease_expires_at ? String(r.lease_expires_at).substring(0, 19) : '—';
                        return '<div><code>' + rid.substring(0, 8) + (rid.length > 8 ? '…' : '') + '</code> → ' + w + ' (lease ' + lease + ')</div>';
                    }).join('');
                }
            }
            var gpuToday = gpuData.filter(function (e) { return e.date === today; });
            var cpuToday = cpuData.filter(function (e) { return e.date === today; });

            var vramTotalMb = 0;
            if (telemetry && telemetry.gpus && telemetry.gpus.length) {
                telemetry.gpus.forEach(function (g) {
                    vramTotalMb += parseFloat(g.memory_total_mb || 0) || 0;
                });
            }
            var key = function (e) { return (e.agent || '') + '|' + (e.bar_id || e.ai_model || ''); };
            var gpuByKey = {};
            gpuToday.forEach(function (e) {
                var k = key(e);
                var vramA = '';
                if (e.vram_required_mb != null && vramTotalMb > 0) {
                    vramA = ((parseFloat(e.vram_required_mb) || 0) / vramTotalMb * 100).toFixed(1);
                } else if (e.gpu_percent != null) {
                    vramA = e.gpu_percent;
                }
                if (!gpuByKey[k]) gpuByKey[k] = { agent: e.agent, bar_id: e.bar_id || e.ai_model || '—', gpu_assigned: e.gpu_percent, gpu_usage: e.gpu_percent, vram_assigned: vramA, vram_usage: vramA };
                else {
                    gpuByKey[k].gpu_assigned = (parseFloat(gpuByKey[k].gpu_assigned) || 0) + (parseFloat(e.gpu_percent) || 0);
                    gpuByKey[k].gpu_usage = gpuByKey[k].gpu_assigned;
                    if (vramA !== '') gpuByKey[k].vram_assigned = ((parseFloat(gpuByKey[k].vram_assigned) || 0) + (parseFloat(vramA) || 0)).toString();
                    gpuByKey[k].vram_usage = gpuByKey[k].vram_assigned;
                }
            });
            var cpuByKey = {};
            cpuToday.forEach(function (e) {
                var k = key(e);
                if (!cpuByKey[k]) cpuByKey[k] = { agent: e.agent, bar_id: e.bar_id || e.ai_model || '—', cpu_assigned: e.cpu_percent, cpu_usage: e.cpu_percent };
                else cpuByKey[k].cpu_assigned = (parseFloat(cpuByKey[k].cpu_assigned) || 0) + (parseFloat(e.cpu_percent) || 0);
            });

            var allKeys = new Set(Object.keys(gpuByKey).concat(Object.keys(cpuByKey)));
            var rows = [];
            var sumGpuA = 0, sumCpuA = 0, sumVramA = 0;
            allKeys.forEach(function (k) {
                var g = gpuByKey[k];
                var c = cpuByKey[k];
                var agent = (g && g.agent) || (c && c.agent) || '—';
                var barId = (g && g.bar_id) || (c && c.bar_id) || '—';
                var gpuA = g ? g.gpu_assigned : '';
                var gpuU = g ? g.gpu_usage : '';
                var cpuA = c ? c.cpu_assigned : '';
                var cpuU = c ? c.cpu_usage : '';
                var vramA = g && g.vram_assigned !== undefined ? g.vram_assigned : '';
                var vramU = g && g.vram_usage !== undefined ? g.vram_usage : '';
                if (gpuA !== '' && gpuA != null) sumGpuA += parseFloat(gpuA) || 0;
                if (cpuA !== '' && cpuA != null) sumCpuA += parseFloat(cpuA) || 0;
                if (vramA !== '' && vramA != null) sumVramA += parseFloat(vramA) || 0;
                rows.push({
                    agent: agent,
                    bar_id: barId,
                    gpu_assigned: gpuA,
                    gpu_usage: gpuU,
                    cpu_assigned: cpuA,
                    cpu_usage: cpuU,
                    vram_assigned: vramA,
                    vram_usage: vramU
                });
            });
            var real = getRealUsageFromTelemetry(telemetry);
            if (real && (real.cpu != null || real.gpu != null || real.vram != null)) {
                rows.push({
                    agent: 'System (live telemetry)',
                    bar_id: '—',
                    gpu_assigned: sumGpuA.toFixed(1),
                    gpu_usage: real.gpu != null ? real.gpu.toFixed(1) : '',
                    cpu_assigned: sumCpuA.toFixed(1),
                    cpu_usage: real.cpu != null ? real.cpu.toFixed(1) : '',
                    vram_assigned: sumVramA > 0 ? sumVramA.toFixed(1) : '',
                    vram_usage: real.vram != null ? real.vram.toFixed(1) : ''
                });
            }

            var bothTbody = byId('parameter-control-both-tbody');
            var cpuTbody = byId('parameter-control-cpu-tbody');
            var gpuTbody = byId('parameter-control-gpu-tbody');
            var vram3dTbody = byId('parameter-control-3d-tbody');

            if (bothTbody) {
                bothTbody.innerHTML = rows.map(function (r) {
                    var gpuOverall = percentOverall(r.gpu_assigned, r.gpu_usage);
                    var cpuOverall = percentOverall(r.cpu_assigned, r.cpu_usage);
                    var vramOverall = percentOverall(r.vram_assigned, r.vram_usage);
                    var perfG = performanceLabel(r.gpu_assigned, r.gpu_usage);
                    var perfC = performanceLabel(r.cpu_assigned, r.cpu_usage);
                    var perfV = performanceLabel(r.vram_assigned, r.vram_usage);
                    var perf = [perfG, perfC, perfV].filter(function (p) { return p !== '—'; });
                    var perfStr = perf.length ? perf.join(' / ') : '—';
                    return '<tr><td>' + (r.agent || '—') + '</td><td>' + (r.bar_id || '—') + '</td><td>' + (r.gpu_assigned || '—') + '</td><td>' + (r.gpu_usage || '—') + '</td><td>' + gpuOverall + '</td><td>' + (r.cpu_assigned || '—') + '</td><td>' + (r.cpu_usage || '—') + '</td><td>' + cpuOverall + '</td><td>' + (r.vram_assigned || '—') + '</td><td>' + (r.vram_usage || '—') + '</td><td>' + vramOverall + '</td><td>' + perfStr + '</td></tr>';
                }).join('') || '<tr><td colspan="12">No schedule entries for today. Add entries in GPU/CPU Schedule.</td></tr>';
            }
            if (cpuTbody) {
                var cpuRows = rows.filter(function (r) { return r.cpu_assigned !== ''; });
                cpuTbody.innerHTML = cpuRows.length ? cpuRows.map(function (r) {
                    var overall = percentOverall(r.cpu_assigned, r.cpu_usage);
                    var perf = performanceLabel(r.cpu_assigned, r.cpu_usage);
                    return '<tr><td>' + (r.agent || '—') + '</td><td>' + (r.bar_id || '—') + '</td><td>' + (r.cpu_assigned || '—') + '</td><td>' + (r.cpu_usage || '—') + '</td><td>' + overall + '</td><td>' + perf + '</td></tr>';
                }).join('') : '<tr><td colspan="6">No CPU schedule entries for today.</td></tr>';
            }
            if (gpuTbody) {
                var gpuRows = rows.filter(function (r) { return r.gpu_assigned !== ''; });
                gpuTbody.innerHTML = gpuRows.length ? gpuRows.map(function (r) {
                    var overall = percentOverall(r.gpu_assigned, r.gpu_usage);
                    var perf = performanceLabel(r.gpu_assigned, r.gpu_usage);
                    return '<tr><td>' + (r.agent || '—') + '</td><td>' + (r.bar_id || '—') + '</td><td>' + (r.gpu_assigned || '—') + '</td><td>' + (r.gpu_usage || '—') + '</td><td>' + overall + '</td><td>' + perf + '</td></tr>';
                }).join('') : '<tr><td colspan="6">No GPU schedule entries for today.</td></tr>';
            }
            if (vram3dTbody) {
                var vramRows = rows.filter(function (r) { return (r.vram_assigned !== '' && r.vram_assigned != null) || (r.agent === 'System (live telemetry)' && r.vram_usage); });
                vram3dTbody.innerHTML = vramRows.length ? vramRows.map(function (r) {
                    var overall = percentOverall(r.vram_assigned, r.vram_usage);
                    var perf = performanceLabel(r.vram_assigned, r.vram_usage);
                    return '<tr><td>' + (r.agent || '—') + '</td><td>' + (r.bar_id || '—') + '</td><td>' + (r.vram_assigned || '—') + '</td><td>' + (r.vram_usage || '—') + '</td><td>' + overall + '</td><td>' + perf + '</td></tr>';
                }).join('') : '<tr><td colspan="6">No VRAM schedule entries for today.</td></tr>';
            }
            updateCircles(rows, telemetry);
        }).catch(function (err) {
            var tbody = byId('parameter-control-both-tbody');
            if (tbody) tbody.innerHTML = '<tr><td colspan="12">Failed to load data: ' + (err.message || err) + '</td></tr>';
        });
    }

    function setMode(mode) {
        document.querySelectorAll('.parameter-control-table-wrap').forEach(function (el) { el.style.display = 'none'; });
        document.querySelectorAll('.parameter-control-mode').forEach(function (el) { el.classList.remove('active'); });
        var wrap = byId('parameter-control-' + mode);
        if (wrap) wrap.style.display = 'block';
        var btn = document.querySelector('.parameter-control-mode[data-mode="' + mode + '"]');
        if (btn) btn.classList.add('active');
    }

    function init() {
        document.querySelectorAll('.parameter-control-mode').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var mode = this.getAttribute('data-mode');
                if (mode) setMode(mode);
            });
        });
        render();
        setInterval(render, 15000);
    }

    window.DashboardTabParameterControl = {
        render: function (container) {
            if (container) container.style.display = 'block';
            setMode('both');
            render();
            if (!window._parameterControlInit) {
                window._parameterControlInit = true;
                init();
            }
        },
        setMode: setMode
    };
})();
