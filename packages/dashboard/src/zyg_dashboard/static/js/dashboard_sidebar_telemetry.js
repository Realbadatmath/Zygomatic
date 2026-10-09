// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

// ── Sidebar telemetry widget ──────────────────────────────────────────────────
// Five bars bottom-left (Disk, CPU, RAM, GPU, VRAM) plus a hover panel per bar
// answering "what is using this?" — the same question the Workflows rings
// answer, off the same /api/telemetry payload.
//
// Two things here are deliberate:
//  * CPU is shown on the 0–2400 scale this box actually has (24 threads), not
//    clamped to 100. The backend sends cpu_pct already multiplied by the thread
//    count and cpu_pct_max alongside it, so the ceiling is never guessed.
//  * Each panel is a child of its own row, positioned with CSS only
//    (left: 100% + a gap, bottom-anchored so it grows upward). No
//    getBoundingClientRect math — the dashboard runs at html{zoom:.67}, where
//    fixed-position pixel arithmetic and layout pixels disagree.
(function () {
  'use strict';

  var ROWS = ['disk', 'cpu', 'ram', 'gpu', 'vram'];
  var LAST = null;                 // newest telemetry payload

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function num(v, dp) {
    return (v == null || isNaN(v)) ? '—' : Number(v).toFixed(dp == null ? 1 : dp);
  }
  function fmtMB(mb) {
    if (mb == null || mb <= 0) return '—';
    return mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB' : Math.round(mb) + ' MB';
  }
  function gpu0(d) { return (d && d.gpus && d.gpus[0]) || null; }

  function table(head, rows, emptyMsg) {
    if (!rows || !rows.length) {
      return '<div class="st-pop-dim">' + esc(emptyMsg) + '</div>';
    }
    return '<table class="st-pop-table"><thead><tr>' +
      head.map(function (h, i) { return '<th>' + esc(h) + '</th>'; }).join('') +
      '</tr></thead><tbody>' + rows.join('') + '</tbody></table>';
  }

  // ── panel content, one builder per bar ─────────────────────────────────────
  function buildDisk(d) {
    var disks = d.disks || [];
    var main = disks[0] || null;
    var rows = disks.map(function (k) {
      return '<tr><td class="st-pop-proc">' + esc(k.mount) + '</td>' +
        '<td class="st-pop-num">' + num(k.free_gb, 0) + ' GB</td>' +
        '<td class="st-pop-num">' + num(k.used_gb, 0) + ' GB</td>' +
        '<td class="st-pop-num">' + num(k.used_pct, 1) + '%</td></tr>';
    });
    return '<div class="st-pop-title">Disk — what is left</div>' +
      '<dl class="st-pop-stats">' +
      '<dt>Free</dt><dd class="st-pop-strong">' + (main ? num(main.free_gb, 0) + ' GB' : '—') + '</dd>' +
      '<dt>Capacity</dt><dd>' + (main ? num(main.total_gb, 0) + ' GB on ' + esc(main.mount) : '—') + '</dd>' +
      '<dt>Used</dt><dd>' + (main ? num(main.used_gb, 0) + ' GB (' + num(main.used_pct, 1) + '%)' : '—') + '</dd>' +
      '</dl>' +
      table(['Filesystem', 'Free', 'Used', 'Used %'], rows, 'No filesystem reported.') +
      '<div class="st-pop-note">Anything not free counts as used, so the figures agree with '
      + 'each other — the ~5% root-reserved blocks are not writable space.</div>';
  }

  function buildCpu(d) {
    var max = d.cpu_pct_max || ((d.cpu_count || 24) * 100);
    var cores = d.cpu_count || Math.round(max / 100);
    var busy = (d.cpu_pct != null) ? d.cpu_pct / 100 : null;
    var la = d.load_avg || [];
    var rows = (d.cpu_procs || []).map(function (p) {
      return '<tr><td class="st-pop-proc" title="pid ' + esc(p.pid) + '">' + esc(p.label) + '</td>' +
        '<td class="st-pop-num">' + num(p.cpu_pct, 1) + '%</td>' +
        '<td class="st-pop-num">' + fmtMB(p.rss_mb) + '</td></tr>';
    });
    return '<div class="st-pop-title">CPU — where it\'s going</div>' +
      '<dl class="st-pop-stats">' +
      '<dt>In use</dt><dd class="st-pop-strong">' + num(d.cpu_pct, 1) + '% of ' + max + '%</dd>' +
      '<dt>Cores busy</dt><dd>' + num(busy, 1) + ' of ' + cores +
        (d.cpu_count_physical ? ' threads <span class="st-pop-dim">(' + d.cpu_count_physical + ' physical)</span>' : ' threads') + '</dd>' +
      '<dt>Load average</dt><dd>' + (la.length ? la.map(function (v) { return num(v, 2); }).join(' / ') +
        ' <span class="st-pop-dim">1 / 5 / 15 min</span>' : '—') + '</dd>' +
      '<dt>Temperature</dt><dd>' + (d.cpu_temp_c != null ? num(d.cpu_temp_c, 1) + ' °C' : '—') + '</dd>' +
      '<dt>Clock</dt><dd>' + (d.cpu_freq_mhz != null ? num(d.cpu_freq_mhz / 1000, 2) + ' GHz' : '—') + '</dd>' +
      '</dl>' +
      table(['Process', 'CPU', 'RAM'], rows,
            d.cpu_procs ? 'Nothing above 0.5% — the box is idle.' : 'Sampling the process table…') +
      '<div class="st-pop-note">' + cores + ' threads is ' + max + '%. Agent work is pinned to '
      + 'cores 0–19 (2000% between all of it); the services keep all ' + cores + '.</div>';
  }

  function buildRam(d) {
    var rows = (d.ram_procs || []).map(function (p) {
      return '<tr><td class="st-pop-proc" title="pid ' + esc(p.pid) + '">' + esc(p.label) + '</td>' +
        '<td class="st-pop-num">' + fmtMB(p.rss_mb) + '</td>' +
        '<td class="st-pop-num">' + num(p.cpu_pct, 1) + '%</td></tr>';
    });
    return '<div class="st-pop-title">RAM — where it\'s going</div>' +
      '<dl class="st-pop-stats">' +
      '<dt>In use</dt><dd class="st-pop-strong">' + num(d.ram_pct, 1) + '%</dd>' +
      '<dt>Used</dt><dd>' + (d.ram_used_mb != null ? num(d.ram_used_mb / 1024, 1) : '—') + ' / ' +
        (d.ram_total_mb != null ? num(d.ram_total_mb / 1024, 1) : '—') + ' GB</dd>' +
      '<dt>Processes</dt><dd>' + (d.proc_count != null ? d.proc_count : '—') + '</dd>' +
      '</dl>' +
      table(['Process', 'Resident', 'CPU'], rows,
            d.ram_procs ? 'No process is holding memory.' : 'Sampling the process table…') +
      '<div class="st-pop-note">Resident set size per process. It double-counts shared '
      + 'pages, so the rows add up to more than the total in use.</div>';
  }

  function buildGpu(d) {
    var g = gpu0(d);
    if (!g) {
      return '<div class="st-pop-title">GPU — where it\'s going</div>' +
        '<div class="st-pop-dim">No NVIDIA device reported by the sampler.</div>';
    }
    var clk = (g.clock_sm_mhz != null && g.clock_sm_max_mhz)
      ? g.clock_sm_mhz + ' / ' + g.clock_sm_max_mhz + ' MHz' : '—';
    var idleClocks = (g.clock_pct != null && g.clock_pct < 25 && (g.utilization_pct || 0) >= 10);
    var rows = (g.processes || []).map(function (p) {
      return '<tr><td class="st-pop-proc" title="pid ' + esc(p.pid) + '">' + esc(p.label) + '</td>' +
        '<td class="st-pop-num">' + (p.sm_pct > 0 ? p.sm_pct + '%' : '—') + '</td>' +
        '<td class="st-pop-num">' + (p.dec_pct > 0 ? p.dec_pct + '%' : '—') + '</td>' +
        '<td class="st-pop-num">' + fmtMB(p.vram_mb) + '</td></tr>';
    });
    return '<div class="st-pop-title">GPU — where it\'s going</div>' +
      '<dl class="st-pop-stats">' +
      '<dt>Duty cycle</dt><dd class="st-pop-strong">' + num(g.utilization_pct, 1) + '%</dd>' +
      '<dt>Capacity used</dt><dd>' + num(g.capacity_pct, 1) + '% <span class="st-pop-dim">duty × clock ratio</span></dd>' +
      '<dt>SM clock</dt><dd>' + clk + (g.clock_pct != null ? ' <span class="st-pop-dim">(' + num(g.clock_pct, 1) + '% of max)</span>' : '') + '</dd>' +
      '<dt>Power</dt><dd>' + (g.power_w != null ? num(g.power_w, 1) + ' / ' +
        (g.power_limit_w != null ? Math.round(g.power_limit_w) : '?') + ' W' : '—') + '</dd>' +
      '<dt>Temp / fan</dt><dd>' + (g.temperature_c != null ? num(g.temperature_c, 1) + ' °C' : '—') +
        ' · ' + (g.fan_pct != null ? g.fan_pct + '% fan' : '—') + '</dd>' +
      '</dl>' +
      (idleClocks ? '<div class="st-pop-note">Card is at idle clocks. The duty cycle reads high '
        + 'because work at ' + g.clock_sm_mhz + ' MHz fills more of each sample window — capacity '
        + 'used is ' + num(g.capacity_pct, 1) + '%.</div>' : '') +
      table(['Process', 'SM', 'Dec', 'VRAM'], rows, 'No process is holding the GPU.') +
      '<div class="st-pop-note">The bar shows the duty cycle — the share of the window with a '
      + 'kernel resident. The Workflows ring shows capacity used.</div>';
  }

  function buildVram(d) {
    var g = gpu0(d);
    if (!g) {
      return '<div class="st-pop-title">VRAM — who is holding it</div>' +
        '<div class="st-pop-dim">No NVIDIA device reported by the sampler.</div>';
    }
    var procs = (g.processes || []).slice().sort(function (a, b) {
      return (b.vram_mb || 0) - (a.vram_mb || 0);
    });
    var rows = procs.map(function (p) {
      return '<tr><td class="st-pop-proc" title="pid ' + esc(p.pid) + '">' + esc(p.label) + '</td>' +
        '<td class="st-pop-num">' + fmtMB(p.vram_mb) + '</td>' +
        '<td class="st-pop-num">' + esc(p.kind || '—') + '</td></tr>';
    });
    var used = g.memory_used_mb, total = g.memory_total_mb;
    return '<div class="st-pop-title">VRAM — who is holding it</div>' +
      '<dl class="st-pop-stats">' +
      '<dt>In use</dt><dd class="st-pop-strong">' + fmtMB(used) + ' / ' + fmtMB(total) + '</dd>' +
      '<dt>Share</dt><dd>' + (used != null && total ? num(used / total * 100, 1) + '%' : '—') + '</dd>' +
      '<dt>Free</dt><dd>' + (used != null && total ? fmtMB(total - used) : '—') + '</dd>' +
      (d.comfy_vram_mb ? '<dt>ComfyUI</dt><dd>' + fmtMB(d.comfy_vram_mb) + '</dd>' : '') +
      '</dl>' +
      table(['Process', 'VRAM', 'Kind'], rows, 'No process is holding VRAM.') +
      '<div class="st-pop-note">A model parked in VRAM still shows here with no SM load — '
      + 'that is idle residency, not work.</div>';
  }

  var BUILD = { disk: buildDisk, cpu: buildCpu, ram: buildRam, gpu: buildGpu, vram: buildVram };

  // ── panels: one per row, created once, refilled on every tick ─────────────
  function ensurePanels() {
    ROWS.forEach(function (id) {
      var row = document.getElementById('strow-' + id);
      if (!row || row.querySelector('.st-pop')) return;
      var pop = document.createElement('div');
      pop.className = 'st-pop';
      pop.id = 'stpop-' + id;
      row.appendChild(pop);
    });
  }

  function fillPanels(d) {
    ROWS.forEach(function (id) {
      var pop = document.getElementById('stpop-' + id);
      if (!pop) return;
      try {
        pop.innerHTML = BUILD[id](d);
      } catch (e) {
        pop.innerHTML = '<div class="st-pop-dim">Breakdown unavailable: ' + esc(e.message) + '</div>';
      }
    });
  }

  // ── bars ──────────────────────────────────────────────────────────────────
  // pct = the value; max = the scale it is measured against; text = what to print.
  function set(id, pct, max, text) {
    var bar = document.getElementById('stbar-' + id);
    var val = document.getElementById('stval-' + id);
    if (!bar || !val) return;
    if (pct == null || isNaN(pct)) { val.textContent = '—'; return; }
    var share = Math.min(100, Math.max(0, parseFloat(pct) / (max || 100) * 100));
    bar.style.width = share + '%';
    if (share >= 90) { bar.style.background = '#ef5350'; }
    else if (share >= 75) { bar.style.background = '#ffa726'; }
    else { bar.style.removeProperty('background'); }
    val.textContent = text;
  }

  function updateSidebarTelemetry() {
    if (window._serverRestarting) return;
    fetch('/api/telemetry', { cache: 'no-store', credentials: 'same-origin' }).then(function (r) {
      if (!r.ok) { console.error('[Telemetry] HTTP', r.status); return null; }
      return r.json();
    }).then(function (d) {
      if (!d) { return; }
      LAST = d;
      var g = gpu0(d);
      var cpuMax = d.cpu_pct_max || ((d.cpu_count || 24) * 100);
      var vramUsed = g ? g.memory_used_mb : null;
      var vramTotal = g ? g.memory_total_mb : null;
      var vram = (vramUsed != null && vramTotal) ? (vramUsed / vramTotal * 100) : null;
      var disk = (d.disks && d.disks[0]) || null;

      set('disk', disk ? disk.used_pct : null, 100,
          disk ? Math.round(disk.free_gb) + 'G' : '—');
      /* CPU: 0–2400% on a 24-thread box. The bar fills against that ceiling, the
         number is the real figure — clamping it to 100 hid every spike. */
      set('cpu', d.cpu_pct, cpuMax, Math.round(d.cpu_pct || 0) + '%');
      set('ram', d.ram_pct, 100, Math.round(d.ram_pct || 0) + '%');
      set('gpu', g ? g.utilization_pct : null, 100,
          g ? Math.round(g.utilization_pct) + '%' : '—');
      set('vram', vram, 100, vram != null ? Math.round(vram) + '%' : '—');

      ensurePanels();
      fillPanels(d);
    }).catch(function (e) { console.error('[Telemetry] fetch error:', e); });
  }

  ensurePanels();
  updateSidebarTelemetry();
  window._dashboardTelemetryInterval = setInterval(updateSidebarTelemetry, 500);
  window.ZygSidebarTelemetry = { refresh: updateSidebarTelemetry, last: function () { return LAST; } };
})();
