// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

(function () {
  'use strict';

  var _bmHistory   = null;
  var _bmSeeds     = null;
  var _bmPipe      = 'scholarly';
  var _bmPollTimer = null;

  function fmtS(s) {
    if (s == null || isNaN(s) || s < 0) return '—';
    if (s < 0.001)  return '<1ms';
    if (s < 1)      return (s * 1000).toFixed(1) + 'ms';
    if (s < 60)     return s.toFixed(1) + 's';
    if (s < 3600)   return Math.floor(s / 60) + 'm ' + Math.round(s % 60) + 's';
    return Math.floor(s / 3600) + 'h ' + Math.floor((s % 3600) / 60) + 'm';
  }

  function esc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function pipeLabel(p) {
    var m = { scholarly:'Scholarly / Crime', video:'Video', manga:'Manga', storyteller:'Storyteller' };
    return m[p] || p;
  }

  /* ── Load everything ─────────────────────────────────────────────────── */
  window.bmLoadAll = function () {
    var loading = document.getElementById('bm-loading');
    if (loading) { loading.style.display = 'block'; loading.textContent = 'Loading benchmark data…'; }

    Promise.all([
      fetch('/api/benchmark/pipeline_history', { credentials: 'same-origin' }).then(function(r){ return r.json(); }),
      fetch('/api/benchmark/seeds',            { credentials: 'same-origin' }).then(function(r){ return r.json(); }),
      fetch('/api/benchmark/system',           { credentials: 'same-origin' }).then(function(r){ return r.json(); }).catch(function(){ return {}; }),
    ]).then(function(res) {
      _bmHistory = res[0];
      _bmSeeds   = res[1];
      if (loading) loading.style.display = 'none';
      bmRenderSystem(res[2]);
      bmRenderPipe(_bmPipe);
    }).catch(function(e) {
      if (loading) loading.textContent = 'Failed to load: ' + e;
    });
  };

  /* ── Sub-tab switch ──────────────────────────────────────────────────── */
  window.bmSelectPipe = function (pipe) {
    _bmPipe = pipe;
    document.querySelectorAll('.bm-subtab').forEach(function(b) {
      b.classList.toggle('active', b.dataset.pipe === pipe);
    });
    ['scholarly','video','manga','storyteller','multirun'].forEach(function(p) {
      var el = document.getElementById('bm-pipe-' + p);
      if (el) el.style.display = (p === pipe) ? '' : 'none';
    });
    if (pipe === 'multirun') {
      var mfp = document.getElementById('bm-pipe-multirun');
      if (mfp && !mfp.dataset.bmfInited) { mfp.dataset.bmfInited = '1'; bmfBuildForm(); }
    } else {
      if (_bmHistory) bmRenderPipe(pipe);
    }
  };

  /* ── Render pipeline panel ───────────────────────────────────────────── */
  function bmRenderPipe(pipe) {
    if (pipe === 'multirun') return;  /* multirun panel is managed by bmfBuildForm */
    var panel = document.getElementById('bm-pipe-' + pipe);
    if (!panel) return;

    // Crime uses scholarly data (same pipeline internally)
    var hist = _bmHistory && (_bmHistory[pipe] || (pipe === 'crime' ? _bmHistory['scholarly'] : null));
    var seed = _bmSeeds   && _bmSeeds[pipe];

    if (!hist || hist.run_count === 0) {
      panel.innerHTML = '<div class="bm-empty">No completed ' + esc(pipeLabel(pipe)) + ' runs found yet.<br>Run a pipeline to populate benchmark data automatically.</div>';
      return;
    }

    var stages = hist.stages || {};
    var snames = Object.keys(stages).sort(function(a, b) {
      return (stages[a].order || 999) - (stages[b].order || 999);
    });
    var totalAvg = snames.reduce(function(acc, n) { return acc + (stages[n].avg_s || 0); }, 0);
    var heaviest = snames.length
      ? snames.reduce(function(best, n) { return (stages[n].avg_s||0) > (stages[best].avg_s||0) ? n : best; }, snames[0])
      : null;

    var chartId  = 'bm-chart-'  + pipe;
    var trendId  = 'bm-trend-'  + pipe;
    var runPanId = 'bm-runpan-' + pipe;
    var html     = '';

    /* Overview stats */
    html += '<div class="bm-section">';
    html += '<div class="bm-section-title">Overview &mdash; ' + hist.run_count + ' completed run' + (hist.run_count !== 1 ? 's' : '') + '</div>';
    html += '<div class="bm-stats-grid">';
    html += '<div class="bm-stat"><div class="bm-stat-val">' + hist.run_count + '</div><div class="bm-stat-lbl">Total Runs</div></div>';
    html += '<div class="bm-stat"><div class="bm-stat-val">' + snames.length + '</div><div class="bm-stat-lbl">Stages Tracked</div></div>';
    html += '<div class="bm-stat"><div class="bm-stat-val">' + fmtS(totalAvg) + '</div><div class="bm-stat-lbl">Avg Total Time</div></div>';
    if (heaviest) {
      html += '<div class="bm-stat"><div class="bm-stat-val" style="font-size:1rem;line-height:1.3;">' + esc(heaviest.replace(/^Stage \d+[\.\d]*:\s*/,'').slice(0,22)) + '</div><div class="bm-stat-lbl">Heaviest Stage</div></div>';
    }
    html += '</div></div>';

    /* Stage breakdown chart + table */
    var maxAvg = snames.length ? Math.max.apply(null, snames.map(function(n){ return stages[n].avg_s || 0; })) : 1;
    html += '<div class="bm-section">';
    html += '<div class="bm-section-title">Stage Breakdown</div>';
    html += '<div class="bm-chart-wrap" id="' + chartId + '"></div>';
    html += '<table class="bm-table"><thead><tr>';
    html += '<th>Stage</th><th style="text-align:right;">Avg</th><th style="text-align:right;">Min</th>';
    html += '<th style="text-align:right;">P50</th><th style="text-align:right;">P95</th>';
    html += '<th style="text-align:right;">Max</th><th style="text-align:right;">Samples</th>';
    html += '</tr></thead><tbody>';
    snames.forEach(function(n) {
      var s = stages[n];
      var ratio = (s.avg_s || 0) / (maxAvg || 1);
      var dot = ratio < 0.25 ? '#22c55e' : ratio < 0.5 ? '#84cc16' : ratio < 0.75 ? '#f59e0b' : '#ef4444';
      html += '<tr>';
      html += '<td class="bm-td-name"><span class="bm-dot" style="background:' + dot + '"></span>' + esc(n.replace(/^Stage \d+[\.\d]*:\s*/,'')) + '</td>';
      html += '<td class="bm-td-num bm-td-avg">' + fmtS(s.avg_s) + '</td>';
      html += '<td class="bm-td-num">' + fmtS(s.min_s) + '</td>';
      html += '<td class="bm-td-num">' + fmtS(s.p50_s) + '</td>';
      html += '<td class="bm-td-num">' + fmtS(s.p95_s) + '</td>';
      html += '<td class="bm-td-num bm-td-max">' + fmtS(s.max_s) + '</td>';
      html += '<td class="bm-td-num" style="color:#7a8a9a;">' + (s.count || 0) + '</td>';
      html += '</tr>';
    });
    html += '</tbody></table>';
    html += '<div style="margin-top:12px;font-size:0.8rem;color:#94a3b8;letter-spacing:0.02em;">Speed: <span style="color:#22c55e;">&#9679;</span> fast &nbsp;<span style="color:#84cc16;">&#9679;</span> medium &nbsp;<span style="color:#f59e0b;">&#9679;</span> slow &nbsp;<span style="color:#ef4444;">&#9679;</span> heaviest &nbsp;&nbsp;&mdash;&nbsp;&nbsp; Avg in <span style="color:#c7d2fe;font-weight:600;">blue</span> &nbsp;&middot;&nbsp; Max in <span style="color:#fca5a5;font-weight:600;">red</span> &nbsp;&middot;&nbsp; Chart whiskers show min&ndash;max range</div>';
    html += '</div>';

    /* Trend chart */
    if (hist.trend && hist.trend.length > 1) {
      html += '<div class="bm-section"><div class="bm-section-title">Run Trend &mdash; last ' + hist.trend.length + ' runs</div>';
      html += '<div id="' + trendId + '" style="width:100%;min-height:200px;"></div></div>';
    }

    /* Infrastructure test */
    html += '<div class="bm-section"><div class="bm-section-title">Infrastructure Test</div>';
    if (seed) {
      html += '<div class="bm-seed-info">Seed job: <strong style="color:#cbd5e1;">' + esc(seed.topic || seed.pipeline_id || '—') + '</strong> &nbsp;&middot;&nbsp; ' + esc(seed.started);
      if (seed.has_video)  html += ' &nbsp;&middot;&nbsp; ' + seed.video_mb + ' MB video';
      if (seed.has_images) html += ' &nbsp;&middot;&nbsp; ' + seed.image_count + ' images';
      html += '</div>';
    } else {
      html += '<div class="bm-seed-info" style="color:#f97316;">No seed job found — run a ' + esc(pipeLabel(pipe)) + ' pipeline first to enable this test.</div>';
    }
    html += '<button class="bm-run-btn" id="bm-run-btn-' + pipe + '" onclick="bmRunTest(\'' + pipe + '\')"'
          + (seed ? '' : ' disabled') + '>&#9654; Run Infrastructure Test</button>';
    html += '<div id="' + runPanId + '"></div></div>';

    panel.innerHTML = html;

    /* Draw Plotly bar chart — avg bars heat-colored, whiskers show min–max range */
    if (snames.length && typeof Plotly !== 'undefined') {
      var labels  = snames.map(function(n) { return n.replace(/^Stage \d+[\.\d]*:\s*/,''); });
      var avgs    = snames.map(function(n) { return stages[n].avg_s || 0; });
      var mins    = snames.map(function(n) { return stages[n].min_s || 0; });
      var maxs    = snames.map(function(n) { return stages[n].max_s || 0; });
      var barColors = avgs.map(function(a) {
        var r = a / (maxAvg || 1);
        return r < 0.25 ? '#22c55e' : r < 0.5 ? '#84cc16' : r < 0.75 ? '#f59e0b' : '#ef4444';
      });
      var h = Math.max(260, snames.length * 38 + 80);

      Plotly.newPlot(chartId, [{
        type: 'bar', orientation: 'h',
        name: 'Avg Duration',
        x: avgs, y: labels,
        error_x: {
          type: 'data', symmetric: false,
          array:      maxs.map(function(m,i){ return Math.max(0, m - avgs[i]); }),
          arrayminus: avgs.map(function(a,i){ return Math.max(0, a - mins[i]); }),
          visible: true,
          color: 'rgba(180,200,220,0.55)',
          thickness: 2, width: 7,
        },
        marker: { color: barColors, opacity: 0.9 },
        customdata: snames.map(function(n){ return [stages[n].min_s||0, stages[n].max_s||0, stages[n].p95_s||0]; }),
        hovertemplate: '<b>%{y}</b><br>Avg: <b>%{x:.1f}s</b><br>Min: %{customdata[0]:.1f}s &nbsp;·&nbsp; Max: %{customdata[1]:.1f}s<br>P95: %{customdata[2]:.1f}s<extra></extra>',
        showlegend: false,
      }], {
        paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
        font: { color: '#94a3b8', size: 12, family: 'system-ui,-apple-system,sans-serif' },
        xaxis: {
          title: { text: 'Seconds (avg)', font: { size: 12, color: '#94a3b8' } },
          gridcolor: 'rgba(255,255,255,0.07)', zeroline: false,
          tickfont: { size: 11, color: '#94a3b8' }, tickcolor: 'transparent',
          linecolor: 'rgba(255,255,255,0.1)',
        },
        yaxis: {
          automargin: true,
          tickfont: { size: 12, color: '#b8c8d8' },
          gridcolor: 'rgba(0,0,0,0)',
          linecolor: 'rgba(255,255,255,0.1)',
        },
        margin: { l: 10, r: 24, t: 10, b: 52 },
        height: h,
        hoverlabel: {
          bgcolor: '#1e293b', bordercolor: '#64748b',
          font: { color: '#f1f5f9', size: 13 },
        },
      }, { responsive: true, displayModeBar: false });
    }

    /* Draw Plotly trend chart */
    if (hist.trend && hist.trend.length > 1 && typeof Plotly !== 'undefined') {
      var el = document.getElementById(trendId);
      if (el) {
        var dates  = hist.trend.map(function(r){ return r.started; });
        var totals = hist.trend.map(function(r){ return r.total_s; });
        Plotly.newPlot(trendId, [{
          type: 'scatter', mode: 'lines+markers',
          x: dates, y: totals,
          fill: 'tozeroy', fillcolor: 'rgba(99,102,241,0.1)',
          line: { color: '#818cf8', width: 2.5 },
          marker: { color: '#c7d2fe', size: 7, line: { color: '#818cf8', width: 1.5 } },
          hovertemplate: '<b>%{x}</b><br>Total: <b>%{y:.0f}s</b><extra></extra>',
        }], {
          paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
          font: { color: '#94a3b8', size: 12, family: 'system-ui,-apple-system,sans-serif' },
          xaxis: {
            gridcolor: 'rgba(255,255,255,0.06)', zeroline: false,
            tickfont: { size: 11, color: '#94a3b8' }, tickcolor: 'transparent',
            linecolor: 'rgba(255,255,255,0.1)',
          },
          yaxis: {
            title: { text: 'seconds', font: { size: 11, color: '#94a3b8' } },
            gridcolor: 'rgba(255,255,255,0.06)', zeroline: false,
            tickfont: { size: 11, color: '#94a3b8' }, linecolor: 'rgba(255,255,255,0.1)',
          },
          margin: { l: 10, r: 16, t: 8, b: 48 }, height: 210,
          hoverlabel: {
            bgcolor: '#1e293b', bordercolor: '#64748b',
            font: { color: '#f1f5f9', size: 13 },
          },
        }, { responsive: true, displayModeBar: false });
      }
    }
  }

  /* ── Infrastructure test ─────────────────────────────────────────────── */
  window.bmRunTest = function (pipe) {
    var btn = document.getElementById('bm-run-btn-' + pipe);
    var pan = document.getElementById('bm-runpan-' + pipe);
    if (!btn || !pan) return;

    btn.disabled    = true;
    btn.textContent = '⏳ Running…';
    pan.innerHTML   = '<div class="bm-empty" style="padding:12px 0;">Starting…</div>';

    var seed   = _bmSeeds && _bmSeeds[pipe];
    var seedId = seed ? seed.pipeline_id : '';

    fetch('/api/benchmark/run', {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({pipeline: pipe, seed_job_id: seedId}),
    }).then(function(r){ return r.json(); }).then(function(d) {
      if (d.error) { bmInfraErr(pipe, d.error); return; }
      _bmPollTimer && clearInterval(_bmPollTimer);
      _bmPollTimer = setInterval(function(){ bmPollInfra(pipe, d.run_id); }, 1000);
    }).catch(function(e){ bmInfraErr(pipe, String(e)); });
  };

  function bmInfraErr(pipe, msg) {
    var btn = document.getElementById('bm-run-btn-' + pipe);
    if (btn) { btn.disabled = false; btn.textContent = '▶ Run Infrastructure Test'; }
    var pan = document.getElementById('bm-runpan-' + pipe);
    if (pan) pan.innerHTML = '<div style="color:#fca5a5;padding:10px 0;font-size:0.85rem;">Error: ' + esc(msg) + '</div>';
  }

  function bmPollInfra(pipe, runId) {
    fetch('/api/benchmark/status/' + encodeURIComponent(runId), {credentials:'same-origin'})
      .then(function(r){ return r.json(); })
      .then(function(run) {
        bmRenderInfra(pipe, run);
        if (run.status === 'completed' || run.status === 'error') {
          clearInterval(_bmPollTimer);
          _bmPollTimer = null;
          var btn = document.getElementById('bm-run-btn-' + pipe);
          if (btn) { btn.disabled = false; btn.textContent = '▶ Run Infrastructure Test'; }
        }
      }).catch(function(){});
  }

  function bmRenderInfra(pipe, run) {
    var pan = document.getElementById('bm-runpan-' + pipe);
    if (!pan) return;
    var html = '<div style="margin-top:12px;">';
    (run.stages || []).forEach(function(s) {
      var ok = s.status === 'completed';
      html += '<div class="bm-stage-row">';
      html += '<div class="bm-stage-icon">' + (ok ? '✅' : '❌') + '</div>';
      html += '<div class="bm-stage-name">' + esc(s.name) + '</div>';
      html += '<div class="bm-stage-detail">' + esc(s.detail || '') + '</div>';
      html += '<div class="bm-stage-time">' + (ok ? fmtS(s.elapsed_s) : '—') + '</div>';
      html += '</div>';
    });
    if (run.status === 'running' || run.status === 'starting') {
      html += '<div class="bm-stage-row"><div class="bm-stage-icon">⏳</div><div class="bm-stage-name" style="color:#7a9bb8;">Running…</div><div class="bm-stage-detail"></div><div class="bm-stage-time"></div></div>';
    }
    if (run.ended_at && run.started_at) {
      var total = run.ended_at - run.started_at;
      html += '<div style="margin-top:12px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.08);font-size:0.85rem;color:#94a3b8;">Total test time: <strong style="color:#c7d2fe;">' + fmtS(total) + '</strong></div>';
    }
    html += '</div>';
    pan.innerHTML = html;
  }

  /* ── System Resources panel ─────────────────────────────────────────── */
  function bmRenderSystem(data) {
    var el = document.getElementById('bm-sysres');
    if (!el || !data) return;
    var html = '<div class="bm-section" style="margin-bottom:20px;">';
    html += '<div class="bm-section-title">System Resources</div>';
    html += '<div class="bm-res-grid">';

    /* GPU cards */
    var gpus = data.gpu || [];
    if (gpus.length === 0 && data.gpu_error) {
      html += '<div class="bm-res-card"><div class="bm-res-card-title">GPU</div>';
      html += '<div style="font-size:0.82rem;color:#64748b;">Not detected &mdash; ' + esc(data.gpu_error) + '</div></div>';
    }
    gpus.forEach(function(g) {
      var vramPct = g.mem_total_mb ? Math.round((g.mem_used_mb || 0) / g.mem_total_mb * 100) : 0;
      var vramColor = vramPct < 50 ? '#22c55e' : vramPct < 80 ? '#f59e0b' : '#ef4444';
      var utilColor = (g.util_pct == null || g.util_pct < 50) ? '#6366f1' : g.util_pct < 80 ? '#f59e0b' : '#ef4444';
      html += '<div class="bm-res-card">';
      html += '<div class="bm-res-card-title">GPU</div>';
      html += '<div class="bm-res-name">' + esc(g.name) + '</div>';
      if (g.mem_total_mb) {
        html += '<div style="font-size:0.75rem;color:#64748b;margin-bottom:5px;">VRAM &nbsp;' + round1(g.mem_used_mb/1024) + ' / ' + round1(g.mem_total_mb/1024) + ' GB used</div>';
        html += '<div class="bm-res-bar-wrap"><div class="bm-res-bar" style="width:' + vramPct + '%;background:' + vramColor + ';"></div></div>';
      }
      html += '<div class="bm-res-stats">';
      if (g.util_pct != null) {
        html += '<div class="bm-res-stat">Utilization &nbsp;<strong style="color:' + utilColor + ';">' + g.util_pct.toFixed(0) + '%</strong></div>';
      }
      if (g.temp_c != null) {
        var tc = g.temp_c;
        var tcCol = tc < 60 ? '#22c55e' : tc < 80 ? '#f59e0b' : '#ef4444';
        html += '<div class="bm-res-stat">Temp &nbsp;<strong style="color:' + tcCol + ';">' + tc.toFixed(0) + '°C</strong></div>';
      }
      if (g.power_w != null && g.power_limit_w) {
        html += '<div class="bm-res-stat">Power &nbsp;<strong>' + g.power_w.toFixed(0) + ' / ' + g.power_limit_w.toFixed(0) + ' W</strong></div>';
      } else if (g.power_w != null) {
        html += '<div class="bm-res-stat">Power &nbsp;<strong>' + g.power_w.toFixed(0) + ' W</strong></div>';
      }
      if (g.mem_free_mb != null) {
        html += '<div class="bm-res-stat">VRAM free &nbsp;<strong>' + round1(g.mem_free_mb/1024) + ' GB</strong></div>';
      }
      html += '</div></div>';
    });

    /* RAM card */
    var ram = data.ram || {};
    if (ram.total_gb) {
      var ramPct = ram.pct || 0;
      var ramColor = ramPct < 50 ? '#22c55e' : ramPct < 75 ? '#f59e0b' : '#ef4444';
      html += '<div class="bm-res-card">';
      html += '<div class="bm-res-card-title">System RAM</div>';
      html += '<div class="bm-res-name">' + ram.used_gb + ' / ' + ram.total_gb + ' GB used</div>';
      html += '<div class="bm-res-bar-wrap"><div class="bm-res-bar" style="width:' + ramPct + '%;background:' + ramColor + ';"></div></div>';
      html += '<div class="bm-res-stats">';
      html += '<div class="bm-res-stat">Used &nbsp;<strong style="color:' + ramColor + ';">' + ramPct.toFixed(0) + '%</strong></div>';
      html += '<div class="bm-res-stat">Available &nbsp;<strong>' + ram.avail_gb + ' GB</strong></div>';
      html += '</div></div>';
    }

    /* CPU card */
    var cpu = data.cpu || {};
    if (cpu.threads) {
      var cpuColor = (cpu.pct || 0) < 50 ? '#6366f1' : (cpu.pct || 0) < 80 ? '#f59e0b' : '#ef4444';
      html += '<div class="bm-res-card">';
      html += '<div class="bm-res-card-title">CPU</div>';
      html += '<div class="bm-res-name">' + (cpu.cores || '?') + ' cores / ' + cpu.threads + ' threads</div>';
      html += '<div class="bm-res-bar-wrap"><div class="bm-res-bar" style="width:' + (cpu.pct||0) + '%;background:' + cpuColor + ';"></div></div>';
      html += '<div class="bm-res-stats">';
      html += '<div class="bm-res-stat">Load &nbsp;<strong style="color:' + cpuColor + ';">' + (cpu.pct||0).toFixed(0) + '%</strong></div>';
      html += '</div></div>';
    }

    html += '</div></div>';
    el.innerHTML = html;
  }

  function round1(v) { return v != null ? parseFloat(v).toFixed(1) : '—'; }

  /* ══════════════════════════════════════════════════════════════════════
     Multi Form — concurrent pipeline benchmark
     ══════════════════════════════════════════════════════════════════════ */

  var _bmfSessionId    = null;
  var _bmfPollTimer    = null;
  var _bmfStartAbsMs   = null;
  var _bmfResData      = { t:[], gpu:[], cpu:[], ram:[], vram:[] };
  var _bmfChartInited  = false;

  var _BMF_COLORS = {
    'Stage 1': '#6366f1', 'Stage 2': '#7c3aed', 'Stage 3': '#0891b2',
    'Stage 3b': '#0284c7', 'Stage 3.1': '#2563eb', 'Stage 3.5': '#d97706',
    'Stage 4': '#059669', 'Stage 4/WAN': '#f59e0b',
    'Stage 5': '#64748b', 'Stage 6': '#dc2626',
    'Color Grade': '#db2777', 'Subtitle Burn': '#7c3aed',
  };
  // Median seconds from 121 historical runs (used for comparison in results)
  var _BMF_BASELINES = {
    'Stage 1': 0, 'Stage 2': 4.5, 'Stage 3': 52.6, 'Stage 3b': 13.4,
    'Stage 3.1': 9.0, 'Stage 3.5': 248.6, 'Stage 4': 75.2, 'Stage 6': 159.3,
  };

  window.bmfBuildForm = function () {
    var panel = document.getElementById('bm-pipe-multirun');
    if (!panel) return;
    panel.innerHTML =

      /* ── Simulation section ── */
      '<div style="padding-top:6px;">' +
        '<div class="bm-section-title" style="margin-bottom:6px;">Schedule Simulator</div>' +
        '<p style="color:#94a3b8;font-size:0.82rem;margin:0 0 20px;line-height:1.6;">' +
          'Automatically compares all 6 scheduling strategies across every N (1–20 concurrent jobs) ' +
          'and all 3 doc sizes — using median stage durations from 121 historical runs.' +
        '</p>' +
        '<div style="display:flex;gap:14px;align-items:flex-end;flex-wrap:wrap;margin-bottom:18px;">' +
          '<button class="bm-run-btn" onclick="simRunAll()" style="padding:8px 26px;font-size:0.9rem;">&#9654; Simulate All Configurations</button>' +
        '</div>' +
        '<div id="sim-out" style="display:none;"></div>' +
        '<div id="sim-cmp" style="display:none;"></div>' +
        '<div id="sim-swp" style="display:none;"></div>' +

        /* ── Monte Carlo subsection ── */
        '<div style="border-top:1px solid rgba(255,255,255,0.06);margin:22px 0 0;padding-top:18px;">' +
          '<div style="display:flex;align-items:baseline;gap:10px;margin-bottom:6px;">' +
            '<div class="bm-section-title" style="margin:0;">Monte Carlo</div>' +
            '<span style="color:#94a3b8;font-size:0.78rem;">Sweeps all N (2–20) × all 3 doc sizes — 1,000 simulations per configuration</span>' +
          '</div>' +
          '<p style="color:#94a3b8;font-size:0.77rem;margin:0 0 14px;line-height:1.5;">' +
            'Draws random stage durations from log-normal distributions fit to the last 20 completed pipeline runs. ' +
            'Falls back to a 277-run historical baseline for any stage with fewer than 5 recent samples. ' +
            'All 6 strategies run through the same random world — win rates are directly comparable.' +
          '</p>' +
          '<div style="display:flex;gap:14px;align-items:flex-end;flex-wrap:wrap;margin-bottom:14px;">' +
            '<button class="bm-run-btn" id="mc-btn" onclick="mcRun()" style="padding:7px 22px;background:rgba(99,102,241,0.15);border-color:rgba(99,102,241,0.45);">&#127922; Run Monte Carlo</button>' +
          '</div>' +

          /* ── Options row ── */
          '<div style="display:flex;gap:20px;align-items:center;flex-wrap:wrap;margin-bottom:14px;">' +
            '<div style="display:flex;flex-direction:column;gap:5px;">' +
              '<label style="color:#94a3b8;font-size:0.73rem;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;">SLA Target</label>' +
              '<div style="display:flex;align-items:center;gap:8px;">' +
                '<input type="range" id="mc-sla" min="20" max="180" step="5" value="60"' +
                  ' oninput="document.getElementById(\'mc-sla-lbl\').textContent=this.value+\' min\'"' +
                  ' style="width:100px;accent-color:#a78bfa;">' +
                '<span id="mc-sla-lbl" style="color:#a78bfa;font-size:0.85rem;font-weight:700;min-width:52px;">60 min</span>' +
              '</div>' +
            '</div>' +
            '<label style="display:flex;align-items:center;gap:7px;cursor:pointer;user-select:none;">' +
              '<input type="checkbox" id="mc-corr" checked style="accent-color:#6366f1;width:14px;height:14px;">' +
              '<span style="color:#94a3b8;font-size:0.78rem;">Stage Correlation <span style="color:#64748b;">(API stages co-vary)</span></span>' +
            '</label>' +
            '<div id="mc-conv-status" style="color:#4ade80;font-size:0.74rem;display:none;"></div>' +
          '</div>' +

          /* ── Neural viz ── */
          '<div id="mc-viz-wrap" style="display:none;position:relative;margin-bottom:16px;">' +
            /* "Found the sweet spot" label */
            '<div id="mc-sweet-lbl" style="display:none;position:absolute;top:16px;left:0;right:0;text-align:center;' +
              'color:#4ade80;font-size:1.25rem;font-weight:700;letter-spacing:0.1em;z-index:20;opacity:0;' +
              'text-shadow:0 0 28px rgba(74,222,128,0.8);pointer-events:none;transition:opacity 0.9s;">Found the sweet spot</div>' +
            /* flex: canvas | panel */
            '<div id="mc-viz-flex" style="display:flex;align-items:stretch;">' +
              '<div id="mc-cvs-wrap" style="flex:1 1 100%;overflow:hidden;border-radius:10px;background:#060c1a;position:relative;transition:flex 0.75s ease;">' +
                '<canvas id="mc-neural-cvs" style="display:block;width:100%;"></canvas>' +
                /* progress bar overlaid at canvas bottom */
                '<div style="position:absolute;bottom:0;left:0;right:0;height:3px;background:rgba(255,255,255,0.04);">' +
                  '<div id="mc-prog-bar" style="height:100%;width:0%;background:linear-gradient(90deg,#6366f1,#a78bfa);transition:width 0.25s;"></div>' +
                '</div>' +
                /* status text top-right */
                '<div id="mc-prog-msg" style="position:absolute;top:8px;right:10px;color:rgba(148,163,184,0.55);font-size:0.68rem;font-family:monospace;max-width:260px;text-align:right;line-height:1.4;"></div>' +
              '</div>' +
              /* strategy reveal panel */
              '<div id="mc-strat-pnl" style="flex:0 0 0;overflow:hidden;opacity:0;' +
                'background:rgba(6,12,26,0.97);border:1px solid rgba(74,222,128,0.14);border-left:none;' +
                'border-radius:0 10px 10px 0;transition:flex 0.75s ease,opacity 0.5s ease 0.55s;">' +
                '<div id="mc-strat-inner" style="padding:22px 16px;width:260px;"></div>' +
              '</div>' +
            '</div>' +
          '</div>' +

          '<div id="mc-out" style="display:none;"></div>' +
        '</div>' +

      '</div>';

  };

  window.bmfAddRow = function (defaults) {
    defaults = defaults || {};
    var rows   = document.getElementById('bmf-rows');
    if (!rows) return;
    var n      = rows.children.length;
    if (n >= 4) return;
    var LABELS = ['A','B','C','D'];
    var lbl    = defaults.label    || ('Pipeline ' + LABELS[n]);
    var size   = defaults.size     || 'short';
    var off    = defaults.offset_s !== undefined ? defaults.offset_s : n * 180;
    var row    = document.createElement('div');
    row.className   = 'bmf-row';
    row.style.cssText = 'display:flex;gap:10px;align-items:center;background:rgba(255,255,255,0.03);' +
                        'border:1px solid rgba(255,255,255,0.07);border-radius:8px;padding:10px 14px;';
    var _sel = function(val, opts) {
      return '<select class="bmf-size" style="background:#0f172a;border:1px solid rgba(148,163,184,0.2);color:#b8c8d8;border-radius:6px;padding:4px 8px;font-size:0.82rem;">' +
        opts.map(function(o){ return '<option value="'+o.v+'"'+(o.v===val?' selected':'')+'>'+o.t+'</option>'; }).join('') +
        '</select>';
    };
    row.innerHTML =
      '<span style="color:#a5b4fc;font-size:0.78rem;font-weight:700;width:22px;flex-shrink:0;">' + LABELS[n] + '</span>' +
      _sel(size,[{v:'short',t:'Short (~60s)'},{v:'medium',t:'Medium (~120s)'},{v:'long',t:'Long (~240s)'}]) +
      '<span style="color:#94a3b8;font-size:0.8rem;flex-shrink:0;">starts after</span>' +
      '<input class="bmf-offset" type="number" min="0" max="600" step="30" value="' + off + '"' +
        ' style="width:64px;background:#0f172a;border:1px solid rgba(148,163,184,0.2);color:#b8c8d8;border-radius:6px;padding:4px 8px;font-size:0.82rem;">' +
      '<span style="color:#94a3b8;font-size:0.8rem;flex-shrink:0;">seconds</span>' +
      (n > 0
        ? '<button onclick="this.closest(\'.bmf-row\').remove()" style="margin-left:auto;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.25);color:#fca5a5;border-radius:5px;padding:3px 10px;font-size:0.78rem;cursor:pointer;">&#10005;</button>'
        : '<span style="margin-left:auto;width:42px;"></span>');
    rows.appendChild(row);
  };

  window.bmfStart = function () {
    var rows = document.querySelectorAll('#bmf-rows .bmf-row');
    if (rows.length < 2) { alert('Add at least 2 pipelines.'); return; }
    var LABELS  = ['A','B','C','D'];
    var configs = [];
    rows.forEach(function(row, i) {
      configs.push({
        label:    'Pipeline ' + LABELS[i],
        size:     row.querySelector('.bmf-size').value,
        offset_s: parseInt(row.querySelector('.bmf-offset').value) || 0,
      });
    });
    var btn = document.getElementById('bmf-start-btn');
    var msg = document.getElementById('bmf-status-msg');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Launching…'; }
    _bmfResData     = { t:[], gpu:[], cpu:[], ram:[], vram:[] };
    _bmfChartInited = false;
    _bmfStartAbsMs  = null;
    var live    = document.getElementById('bmf-live');
    var results = document.getElementById('bmf-results');
    if (live)    live.style.display    = 'none';
    if (results) results.innerHTML = '';

    fetch('/api/benchmark/multirun', {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({pipelines: configs}),
    }).then(function(r){ return r.json(); }).then(function(d) {
      if (d.error) {
        if (btn) { btn.disabled = false; btn.textContent = '&#9654; Start Multi-Run'; }
        if (msg) msg.textContent = 'Error: ' + d.error;
        return;
      }
      _bmfSessionId = d.session_id;
      if (live) live.style.display = 'block';
      if (msg)  msg.textContent = 'Session ' + d.session_id;
      _bmfPollTimer && clearInterval(_bmfPollTimer);
      _bmfPollTimer = setInterval(bmfPoll, 2000);
    }).catch(function(e) {
      if (btn) { btn.disabled = false; btn.textContent = '&#9654; Start Multi-Run'; }
      if (msg) msg.textContent = 'Request failed: ' + e;
    });
  };

  function bmfPoll() {
    if (!_bmfSessionId) return;
    fetch('/api/benchmark/multirun/' + _bmfSessionId, {credentials:'same-origin'})
      .then(function(r){ return r.json(); }).then(function(d) {
        if (!d || d.error) return;
        if (!_bmfStartAbsMs && d.session_start) _bmfStartAbsMs = d.session_start * 1000;
        bmfRenderGantt(d);
        bmfUpdateResChart(d.resource_timeline || []);
        if (d.status === 'completed' || d.status === 'error') {
          clearInterval(_bmfPollTimer); _bmfPollTimer = null;
          var btn = document.getElementById('bmf-start-btn');
          if (btn) { btn.disabled = false; btn.textContent = '&#9654; Start Multi-Run'; }
          var msg = document.getElementById('bmf-status-msg');
          if (msg) msg.textContent = d.status === 'completed'
            ? ('Done — ' + Math.round(d.total_elapsed_s || 0) + 's total')
            : ('Error: ' + (d.error || 'unknown'));
          if (d.status === 'completed') bmfRenderResults(d);
        }
      }).catch(function(){});
  }

  function bmfStageColor(name) {
    for (var k in _BMF_COLORS) {
      if (name && name.indexOf(k) === 0) return _BMF_COLORS[k];
    }
    return '#64748b';
  }

  function bmfRenderGantt(data) {
    var el = document.getElementById('bmf-gantt');
    if (!el) return;
    var pipes  = data.pipelines_status || [];
    if (!pipes.length) { el.innerHTML = '<div class="bm-empty">Waiting for pipelines to start…</div>'; return; }
    var baseMs  = _bmfStartAbsMs || Date.now();
    var nowRel  = (Date.now() - baseMs) / 1000;
    var spanMax = Math.max(120, nowRel + 20);
    pipes.forEach(function(p) {
      (p.stage_timeline || []).forEach(function(s) {
        if (s.ended_at) {
          var er = (new Date(s.ended_at).getTime() - baseMs) / 1000;
          if (er + 20 > spanMax) spanMax = er + 20;
        }
      });
    });

    // Tick marks every 60 s
    var tickHtml = '';
    for (var t = 0; t <= spanMax; t += 60) {
      var pct = (t / spanMax * 100).toFixed(2);
      tickHtml += '<div style="position:absolute;left:' + pct + '%;top:0;bottom:0;border-left:1px dashed rgba(255,255,255,0.07);pointer-events:none;"></div>' +
                  '<span style="position:absolute;left:' + pct + '%;bottom:2px;transform:translateX(-50%);color:#64748b;font-size:0.65rem;">' + t + 's</span>';
    }

    var rowsHtml = '';
    pipes.forEach(function(p) {
      var statusIcon = p.status === 'running' ? '●' : (p.status === 'completed' ? '✓' : '○');
      var statusCol  = p.status === 'running' ? '#4ade80' : (p.status === 'completed' ? '#6366f1' : '#64748b');
      rowsHtml += '<div style="display:flex;align-items:center;margin-bottom:10px;gap:0;">';
      rowsHtml += '<div style="width:112px;flex-shrink:0;text-align:right;padding-right:10px;">' +
        '<span style="color:' + statusCol + ';font-size:0.68rem;margin-right:4px;">' + statusIcon + '</span>' +
        '<span style="color:#94a3b8;font-size:0.78rem;font-weight:600;">' + (p.label||'') + '</span></div>';
      rowsHtml += '<div style="flex:1;position:relative;height:28px;background:rgba(255,255,255,0.025);border-radius:4px;overflow:visible;">';
      (p.stage_timeline || []).forEach(function(s) {
        if (!s.started_at) return;
        var startRel = (new Date(s.started_at).getTime() - baseMs) / 1000;
        var dur = s.elapsed_s;
        if (!s.ended_at) dur = Math.max(0.5, (Date.now() - new Date(s.started_at).getTime()) / 1000);
        if (!dur || dur < 0.1) return;
        var left  = Math.max(0, startRel / spanMax * 100);
        var width = Math.min(100 - left, dur / spanMax * 100);
        var col   = bmfStageColor(s.name || '');
        var label = (s.name || '').replace(/^Stage /, '').split(':')[0];
        rowsHtml += '<div title="' + (s.name||'') + ' — ' + Math.round(s.elapsed_s||0) + 's"' +
          ' style="position:absolute;top:0;left:' + left.toFixed(2) + '%;width:' + Math.max(0.3, width).toFixed(2) + '%;height:100%;' +
          'background:' + col + ';' + (!s.ended_at ? 'opacity:0.75;' : '') +
          'border-right:1px solid rgba(0,0,0,0.25);border-radius:2px;overflow:hidden;' +
          'display:flex;align-items:center;justify-content:center;">' +
          '<span style="color:rgba(255,255,255,0.92);font-size:0.62rem;font-weight:700;white-space:nowrap;padding:0 3px;text-shadow:0 1px 2px rgba(0,0,0,0.6);">' + label + '</span></div>';
      });
      rowsHtml += '</div>';
      var curStage = (p.current_stage||'').replace('Stage ','S').split(':')[0];
      rowsHtml += '<div style="width:46px;flex-shrink:0;padding-left:6px;color:#64748b;font-size:0.7rem;">' + curStage + '</div>';
      rowsHtml += '</div>';
    });

    el.innerHTML =
      '<div style="position:relative;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.07);border-radius:10px;padding:14px 8px 22px;">' +
        '<div style="position:absolute;left:120px;right:54px;bottom:4px;top:10px;">' + tickHtml + '</div>' +
        '<div style="position:relative;z-index:1;">' + rowsHtml + '</div>' +
      '</div>';
  }

  function bmfUpdateResChart(timeline) {
    if (!timeline || !timeline.length) return;
    var newSamples = timeline.slice(_bmfResData.t.length);
    if (!newSamples.length) return;
    newSamples.forEach(function(s) {
      _bmfResData.t.push(s.t_rel || 0);
      _bmfResData.gpu.push(s.gpu_pct  || 0);
      _bmfResData.cpu.push(s.cpu_pct  || 0);
      _bmfResData.ram.push(s.ram_pct  || 0);
      var vramPct = (s.vram_total_mb && s.vram_total_mb > 0)
        ? Math.round(s.vram_used_mb / s.vram_total_mb * 100) : 0;
      _bmfResData.vram.push(vramPct);
    });
    var el = document.getElementById('bmf-reschart');
    if (!el || typeof Plotly === 'undefined') return;
    var traces = [
      { x:_bmfResData.t, y:_bmfResData.gpu,  name:'GPU %',  mode:'lines', line:{color:'#f59e0b',width:2} },
      { x:_bmfResData.t, y:_bmfResData.vram, name:'VRAM %', mode:'lines', line:{color:'#ef4444',width:2} },
      { x:_bmfResData.t, y:_bmfResData.cpu,  name:'CPU %',  mode:'lines', line:{color:'#06b6d4',width:2} },
      { x:_bmfResData.t, y:_bmfResData.ram,  name:'RAM %',  mode:'lines', line:{color:'#10b981',width:1.5,dash:'dot'} },
    ];
    var layout = {
      paper_bgcolor:'transparent', plot_bgcolor:'rgba(255,255,255,0.02)',
      margin:{t:8,b:36,l:38,r:10},
      xaxis:{title:{text:'seconds',font:{color:'#94a3b8',size:11}},tickfont:{color:'#94a3b8',size:10},
             gridcolor:'rgba(255,255,255,0.05)',color:'#94a3b8'},
      yaxis:{range:[0,100],title:{text:'%',font:{color:'#94a3b8',size:11}},tickfont:{color:'#94a3b8',size:10},
             gridcolor:'rgba(255,255,255,0.05)',color:'#94a3b8'},
      legend:{font:{color:'#94a3b8',size:10},bgcolor:'transparent',orientation:'h',x:0,y:1.12},
      font:{color:'#94a3b8'},
    };
    var cfg = {responsive:true, displayModeBar:false};
    if (!_bmfChartInited) {
      Plotly.newPlot(el, traces, layout, cfg);
      _bmfChartInited = true;
    } else {
      Plotly.react(el, traces, layout);
    }
  }

  function bmfRenderResults(data) {
    var el = document.getElementById('bmf-results');
    if (!el) return;
    var pipes   = data.pipelines_status || [];
    var total   = data.total_elapsed_s  || 0;
    // Sequential baseline = sum of median stage times × number of pipelines
    var singleRunBase = Object.values(_BMF_BASELINES).reduce(function(a,b){return a+b;},0);
    var seqBase = singleRunBase * pipes.length;
    var gain    = seqBase > 0 ? Math.round(seqBase / total * 100) : 0;
    var gainCol = gain >= 150 ? '#4ade80' : gain >= 110 ? '#fbbf24' : '#f87171';

    var html = '<div class="bm-section-title" style="margin-bottom:14px;margin-top:4px;">Results</div>';
    html += '<div class="bm-res-grid" style="margin-bottom:22px;">';
    html += _bmfCard('Total Wall-Clock', Math.round(total) + 's',
                     Math.round(total/60*10)/10 + ' min actual', '#c7d2fe');
    html += _bmfCard('Sequential Baseline', Math.round(seqBase) + 's',
                     pipes.length + ' × ' + Math.round(singleRunBase) + 's back-to-back', '#a0b0c0');
    html += _bmfCard('Throughput Gain', gain + '%',
                     gain >= 100 ? 'faster than sequential' : 'vs sequential', gainCol);
    html += '</div>';

    pipes.forEach(function(p) {
      html += '<div style="margin-bottom:18px;">';
      html += '<div style="color:#b8c8d8;font-size:0.85rem;font-weight:600;margin-bottom:8px;">' + (p.label||'') + ' — ' + (p.size||'') + '</div>';
      html += '<table class="bm-table" style="width:100%;"><thead><tr>' +
        '<th>Stage</th><th>Actual</th><th>Baseline (median)</th><th>Δ</th></tr></thead><tbody>';
      (p.stage_timeline || []).forEach(function(s) {
        if (s.elapsed_s === undefined || s.elapsed_s === null) return;
        var base = null;
        for (var k in _BMF_BASELINES) {
          if (s.name && s.name.indexOf(k) === 0) { base = _BMF_BASELINES[k]; break; }
        }
        var delta    = base !== null ? Math.round(s.elapsed_s - base) : null;
        var dStr     = delta === null ? '—' : (delta >= 0 ? '+' : '') + delta + 's';
        var dCol     = delta === null ? '#94a3b8' : delta > 15 ? '#fca5a5' : delta < -5 ? '#86efac' : '#94a3b8';
        html += '<tr><td>' + (s.name||'') + '</td>' +
          '<td class="bm-td-avg">' + Math.round(s.elapsed_s) + 's</td>' +
          '<td style="color:#94a3b8;">' + (base !== null ? base + 's' : '—') + '</td>' +
          '<td style="color:' + dCol + ';font-weight:600;">' + dStr + '</td></tr>';
      });
      html += '</tbody></table></div>';
    });
    el.innerHTML = html;
  }

  function _bmfCard(title, value, sub, col) {
    return '<div class="bm-res-card"><div class="bm-res-card-title">' + title + '</div>' +
      '<div style="font-size:1.75rem;font-weight:700;color:' + col + ';line-height:1.1;">' + value + '</div>' +
      '<div style="color:#94a3b8;font-size:0.78rem;margin-top:3px;">' + sub + '</div></div>';
  }

  /* ══════════════════════════════════════════════════════════════════════
     PIPELINE SCHEDULE SIMULATOR
     Discrete-event model using 121-run historical medians. Pure frontend.
     ══════════════════════════════════════════════════════════════════════ */

  var _SS = {
    stages: [
      { id:'s2',  lbl:'Research',  dur:4.5,   res:'api',   col:'#7c3aed' },
      { id:'s3',  lbl:'Script',    dur:52.6,  res:'api',   col:'#0891b2' },
      { id:'s3b', lbl:'Tag',       dur:13.4,  res:'light', col:'#0284c7' },
      { id:'s31', lbl:'Emotion',   dur:9.0,   res:'api',   col:'#2563eb' },
      { id:'s35', lbl:'Image Gen', dur:248.6, res:'gpu',   col:'#d97706' },
      { id:'s4',  lbl:'TTS',       dur:75.2,  res:'tts',   col:'#059669' },
      { id:'s6',  lbl:'Assemble',  dur:159.3, res:'cpu',   col:'#dc2626' },
    ],
    res: {
      gpu:   { slots:1, cf:0.0  },
      api:   { slots:5, cf:0.02 },
      tts:   { slots:3, cf:0.05 },
      light: { slots:8, cf:0.0  },
      cpu:   { slots:2, cf:0.30 },
    },
    size: { short:0.25, medium:0.50, long:1.0 },
    strats: [
      { id:'seq',         name:'Sequential',          desc:'One job at a time — fully sequential.' },
      { id:'stagger',     name:'GPU-Aligned Stagger',  desc:'Each job offset by GPU duration so GPU never idles.' },
      { id:'scriptfirst', name:'Script-First Batch',   desc:'All scripts pre-generated before any GPU work starts.' },
      { id:'assembly',    name:'Assembly Line',        desc:'Stage-first ordering — every job flows through each stage in turn.' },
      { id:'gpuburst',    name:'GPU Burst',            desc:'Barrier after all pre-GPU, then GPU non-stop, then parallel post.' },
      { id:'adaptive',    name:'Adaptive Greedy',      desc:'GPU queue sorted by readiness — minimal GPU idle between jobs.' },
    ],
  };
  var _SS_IDX = {};
  _SS.stages.forEach(function(s, i) { _SS_IDX[s.id] = i; });

  /* ── Core DES ─────────────────────────────────────────────────────── */
  function _ssDES(queue) {
    var slots = {};
    Object.keys(_SS.res).forEach(function(r) { slots[r] = Array(_SS.res[r].slots).fill(0); });
    var uid_end = {}, out = [];
    queue.forEach(function(t) {
      var res     = t.stage.res;
      var dep_end = t.dep ? (uid_end[t.dep] || 0) : 0;
      var early   = Math.max(t.start0 || 0, dep_end);
      var sl      = slots[res];
      var minT    = Math.min.apply(null, sl);
      var si      = sl.indexOf(minT);
      var start   = Math.max(early, minT);
      var dur     = t.stage.dur * (t.sc || 1.0);
      var cf      = _SS.res[res].cf;
      if (cf > 0) {
        var olap = 0;
        for (var k = 0; k < out.length; k++) {
          var e = out[k];
          if (e.res === res && e.s < start + dur && e.e > start) olap++;
        }
        if (olap > 0) dur *= (1 + cf * Math.min(olap, 3));
      }
      var end = start + dur;
      sl[si]        = end;
      uid_end[t.uid] = end;
      out.push({ job:t.job, stage:t.stage, res:res, s:Math.round(start*10)/10, e:Math.round(end*10)/10 });
    });
    return out;
  }

  /* Build one job's task chain */
  function _ssChain(j, sc, earliest) {
    var tasks = [], prev = null;
    _SS.stages.forEach(function(stage) {
      var uid = 'j'+j+'_'+stage.id;
      tasks.push({ uid:uid, job:j, stage:stage, sc:sc, start0:(stage===_SS.stages[0] ? (earliest||0) : 0), dep:prev });
      prev = uid;
    });
    return tasks;
  }

  /* ── Strategy builders ─────────────────────────────────────────────── */

  function _ssStratSeq(n, sc) {
    var q = [];
    for (var j = 0; j < n; j++) {
      var ch = _ssChain(j, sc, 0);
      if (j > 0) ch[0].dep = 'j'+(j-1)+'_s6';
      q = q.concat(ch);
    }
    return q;
  }

  function _ssStratStagger(n, sc, off) {
    if (off === undefined) off = 248.6 * sc;
    var q = [];
    for (var j = 0; j < n; j++) q = q.concat(_ssChain(j, sc, j * off));
    q.sort(function(a, b) { return (a.start0||0) - (b.start0||0) || a.job - b.job; });
    return q;
  }

  function _ssStratScriptFirst(n, sc) {
    var PRE = ['s2','s3','s3b','s31'], POST = ['s35','s4','s6'], q = [];
    PRE.forEach(function(sid) {
      var pi = PRE.indexOf(sid);
      for (var j = 0; j < n; j++)
        q.push({ uid:'j'+j+'_'+sid, job:j, stage:_SS.stages[_SS_IDX[sid]], sc:sc, start0:0, dep:pi>0?'j'+j+'_'+PRE[pi-1]:null });
    });
    POST.forEach(function(sid) {
      var pi = POST.indexOf(sid);
      for (var j = 0; j < n; j++) {
        var dep = pi===0 ? 'j'+j+'_s31' : 'j'+j+'_'+POST[pi-1];
        q.push({ uid:'j'+j+'_'+sid, job:j, stage:_SS.stages[_SS_IDX[sid]], sc:sc, start0:0, dep:dep });
      }
    });
    return q;
  }

  function _ssStratAssembly(n, sc) {
    var q = [];
    _SS.stages.forEach(function(stage, si) {
      for (var j = 0; j < n; j++) {
        var dep = si > 0 ? 'j'+j+'_'+_SS.stages[si-1].id : null;
        q.push({ uid:'j'+j+'_'+stage.id, job:j, stage:stage, sc:sc, start0:0, dep:dep });
      }
    });
    return q;
  }

  function _ssStratGPUBurst(n, sc, durMap) {
    var PRE = ['s2','s3','s3b','s31'], q = [];
    PRE.forEach(function(sid) {
      var pi = PRE.indexOf(sid);
      for (var j = 0; j < n; j++)
        q.push({ uid:'j'+j+'_'+sid, job:j, stage:_SS.stages[_SS_IDX[sid]], sc:sc, start0:0, dep:pi>0?'j'+j+'_'+PRE[pi-1]:null });
    });
    var innerQ = q.slice();
    if (durMap) innerQ.forEach(function(t){ t._d = durMap[t.job][t.stage.id]; });
    var pre = durMap ? _mcDES(innerQ) : _ssDES(innerQ); var barrier = 0;
    pre.forEach(function(e) { if (e.stage.id==='s31' && e.e>barrier) barrier=e.e; });
    for (var j = 0; j < n; j++)
      q.push({ uid:'j'+j+'_s35', job:j, stage:_SS.stages[_SS_IDX['s35']], sc:sc, start0:barrier, dep:'j'+j+'_s31' });
    for (var j = 0; j < n; j++) {
      q.push({ uid:'j'+j+'_s4', job:j, stage:_SS.stages[_SS_IDX['s4']], sc:sc, start0:0, dep:'j'+j+'_s35' });
      q.push({ uid:'j'+j+'_s6', job:j, stage:_SS.stages[_SS_IDX['s6']], sc:sc, start0:0, dep:'j'+j+'_s4'  });
    }
    return q;
  }

  function _ssStratAdaptive(n, sc, durMap) {
    var PRE = ['s2','s3','s3b','s31'], q = [];
    PRE.forEach(function(sid) {
      var pi = PRE.indexOf(sid);
      for (var j = 0; j < n; j++)
        q.push({ uid:'j'+j+'_'+sid, job:j, stage:_SS.stages[_SS_IDX[sid]], sc:sc, start0:0, dep:pi>0?'j'+j+'_'+PRE[pi-1]:null });
    });
    var innerQ = q.slice();
    if (durMap) innerQ.forEach(function(t){ t._d = durMap[t.job][t.stage.id]; });
    var pre = durMap ? _mcDES(innerQ) : _ssDES(innerQ), ready = {};
    pre.forEach(function(e) { if (e.stage.id==='s31') ready[e.job]=e.e; });
    var order = Object.keys(ready).map(Number).sort(function(a,b){return ready[a]-ready[b];});
    order.forEach(function(j) {
      q.push({ uid:'j'+j+'_s35', job:j, stage:_SS.stages[_SS_IDX['s35']], sc:sc, start0:0, dep:'j'+j+'_s31' });
    });
    order.forEach(function(j) {
      q.push({ uid:'j'+j+'_s4', job:j, stage:_SS.stages[_SS_IDX['s4']], sc:sc, start0:0, dep:'j'+j+'_s35' });
      q.push({ uid:'j'+j+'_s6', job:j, stage:_SS.stages[_SS_IDX['s6']], sc:sc, start0:0, dep:'j'+j+'_s4'  });
    });
    return q;
  }

  function _ssRunStrat(id, n, sc, durMap) {
    switch(id) {
      case 'seq':         return _ssStratSeq(n, sc);
      case 'stagger':     return _ssStratStagger(n, sc);
      case 'scriptfirst': return _ssStratScriptFirst(n, sc);
      case 'assembly':    return _ssStratAssembly(n, sc);
      case 'gpuburst':    return _ssStratGPUBurst(n, sc, durMap);
      case 'adaptive':    return _ssStratAdaptive(n, sc, durMap);
      default:            return _ssStratSeq(n, sc);
    }
  }

  /* ── Metrics ───────────────────────────────────────────────────────── */
  function _ssMetrics(sched, n, sc) {
    var total  = Math.max.apply(null, sched.map(function(e){return e.e;}));
    var gpuT   = sched.filter(function(e){return e.res==='gpu';}).reduce(function(s,e){return s+(e.e-e.s);},0);
    var seqT   = _SS.stages.reduce(function(s,st){return s+st.dur*sc;},0) * n;
    var gain   = Math.round(seqT / total * 100);
    var gpuU   = Math.round(gpuT / total * 100);
    var tph    = Math.round(n / total * 3600 * 10) / 10;
    var cost   = Math.round(0.057 * n * 100) / 100;
    var j0end  = Math.max.apply(null, sched.filter(function(e){return e.job===0;}).map(function(e){return e.e;}));
    return { total:Math.round(total), seqT:Math.round(seqT), gain:gain, gpuU:gpuU, tph:tph, cost:cost, j0end:Math.round(j0end) };
  }

  /* ── Gantt renderer ────────────────────────────────────────────────── */
  function _ssGantt(containerId, sched, compact) {
    var el = document.getElementById(containerId);
    if (!el) return;
    var jobs = {}, total = Math.max.apply(null, sched.map(function(e){return e.e;}));
    sched.forEach(function(e) { if (!jobs[e.job]) jobs[e.job]=[]; jobs[e.job].push(e); });
    var rh = compact ? 16 : 24, lw = compact ? 42 : 80, fs = compact ? '0.55rem' : '0.65rem';
    var tick = total>3600?600:total>1800?300:total>600?120:60;
    var ticks = '';
    for (var t = 0; t <= total; t += tick) {
      var p = (t/total*100).toFixed(2);
      ticks += '<div style="position:absolute;left:'+p+'%;top:0;bottom:14px;border-left:1px dashed rgba(255,255,255,0.07);pointer-events:none;"></div>' +
               '<span style="position:absolute;left:'+p+'%;bottom:0;transform:translateX(-50%);color:#64748b;font-size:0.58rem;">'+(t>=3600?Math.round(t/60)+'m':t+'s')+'</span>';
    }
    var rows = '';
    Object.keys(jobs).sort(function(a,b){return +a-+b;}).forEach(function(j) {
      rows += '<div style="display:flex;align-items:center;margin-bottom:'+(compact?3:7)+'px;">';
      rows += '<div style="width:'+lw+'px;flex-shrink:0;text-align:right;padding-right:6px;color:#94a3b8;font-size:'+fs+';font-weight:600;">J'+j+'</div>';
      rows += '<div style="flex:1;position:relative;height:'+rh+'px;background:rgba(255,255,255,0.025);border-radius:3px;">';
      jobs[j].forEach(function(e) {
        var left  = (e.s/total*100).toFixed(3);
        var width = Math.max(0.15, ((e.e-e.s)/total*100)).toFixed(3);
        rows += '<div title="'+e.stage.lbl+': '+Math.round(e.e-e.s)+'s ('+Math.round(e.s)+'→'+Math.round(e.e)+'s)"' +
                ' style="position:absolute;top:0;left:'+left+'%;width:'+width+'%;height:100%;background:'+e.stage.col+';' +
                'border-right:1px solid rgba(0,0,0,0.2);border-radius:2px;overflow:hidden;display:flex;align-items:center;justify-content:center;">' +
                '<span style="color:rgba(255,255,255,0.85);font-size:'+fs+';font-weight:700;white-space:nowrap;padding:0 2px;text-shadow:0 1px 2px rgba(0,0,0,0.6);">'+(compact?'':e.stage.lbl)+'</span></div>';
      });
      rows += '</div></div>';
    });
    el.innerHTML =
      '<div style="position:relative;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.07);border-radius:10px;padding:'+(compact?'8px 4px 18px':'12px 6px 22px')+';overflow:visible;">' +
      '<div style="position:absolute;left:'+lw+'px;right:4px;bottom:4px;top:6px;">'+ticks+'</div>' +
      '<div style="position:relative;z-index:1;">'+rows+'</div>' +
      '</div>';
  }

  /* ── Legend ────────────────────────────────────────────────────────── */
  function _ssLegend() {
    return '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px;">' +
      _SS.stages.map(function(s) {
        return '<span style="display:flex;align-items:center;gap:4px;font-size:0.72rem;color:#94a3b8;">' +
               '<span style="width:11px;height:11px;border-radius:2px;background:'+s.col+';flex-shrink:0;display:inline-block;"></span>' + s.lbl + '</span>';
      }).join('') + '</div>';
  }

  /* ── Metric cards for simulation ───────────────────────────────────── */
  function _ssCards(m, label) {
    var gCol = m.gain>=150?'#4ade80':m.gain>=110?'#fbbf24':m.gain>=100?'#cbd5e1':'#f87171';
    var uCol = m.gpuU>=80?'#4ade80':m.gpuU>=50?'#fbbf24':'#f87171';
    return '<div style="color:#94a3b8;font-size:0.78rem;margin-bottom:10px;">'+label+'</div>' +
      '<div class="bm-res-grid" style="margin-bottom:16px;">' +
      _bmfCard('Total Time',      Math.round(m.total/60*10)/10+' min', Math.round(m.total)+'s wall-clock',    '#c7d2fe') +
      _bmfCard('vs Sequential',   m.gain+'%',                          'throughput gain',                     gCol) +
      _bmfCard('GPU Utilisation', m.gpuU+'%',                          'of total time on GPU',                uCol) +
      _bmfCard('Throughput',      m.tph+'/hr',                         'documentaries per hour',              '#cbd5e1') +
      _bmfCard('First Doc Done',  Math.round(m.j0end/60*10)/10+' min', 'job 0 complete',                      '#cbd5e1') +
      _bmfCard('API Cost Est.',   '$'+m.cost,                          'Claude API (Stage 3 + 3.1)',           '#cbd5e1') +
      '</div>';
  }

  /* ── UI entry points ───────────────────────────────────────────────── */
  window.simRunOne = function () {
    var n  = parseInt(document.getElementById('sim-n').value) || 5;
    var sz = document.getElementById('sim-size').value;
    var sid= document.getElementById('sim-strat').value;
    var sc = _SS.size[sz] || 1.0;
    var st = _SS.strats.find(function(s){return s.id===sid;}) || _SS.strats[0];

    var sched = _ssDES(_ssRunStrat(sid, n, sc));
    var m     = _ssMetrics(sched, n, sc);

    var out = document.getElementById('sim-out');
    if (!out) return;
    out.style.display = 'block';
    out.innerHTML = _ssCards(m, st.name+' — N='+n+' × '+sz) + _ssLegend() + '<div id="ss-gantt-main"></div>';
    _ssGantt('ss-gantt-main', sched, false);

    document.getElementById('sim-cmp').style.display = 'none';
    document.getElementById('sim-swp').style.display = 'none';
  };

  window.simCompareAll = function () {
    var n  = parseInt(document.getElementById('sim-n').value) || 5;
    var sz = document.getElementById('sim-size').value;
    var sc = _SS.size[sz] || 1.0;

    var results = _SS.strats.map(function(st) {
      var sched = _ssDES(_ssRunStrat(st.id, n, sc));
      return { st:st, sched:sched, m:_ssMetrics(sched, n, sc) };
    });
    results.sort(function(a,b){ return a.m.total - b.m.total; });

    var cmp = document.getElementById('sim-cmp');
    if (!cmp) return;
    cmp.style.display = 'block';

    var html = '<div class="bm-section-title" style="margin-bottom:10px;">Strategy Comparison — N='+n+' × '+sz+'</div>' + _ssLegend();
    html += '<table class="bm-table" style="width:100%;margin-bottom:20px;"><thead><tr>' +
      '<th>#</th><th>Strategy</th><th>Time</th><th>Gain vs Seq.</th><th>GPU Util</th><th>First Doc</th><th>Cost</th>' +
      '</tr></thead><tbody>';
    results.forEach(function(r, i) {
      var gc = r.m.gain>=150?'#4ade80':r.m.gain>=110?'#fbbf24':'#cbd5e1';
      html += '<tr>' +
        '<td style="color:#94a3b8;font-weight:600;">'+(i+1)+'</td>' +
        '<td style="color:#e2e8f0;font-weight:600;">'+r.st.name+'</td>' +
        '<td class="bm-td-avg">'+Math.round(r.m.total/60*10)/10+' min</td>' +
        '<td style="color:'+gc+';font-weight:600;">'+r.m.gain+'%</td>' +
        '<td style="color:#cbd5e1;">'+r.m.gpuU+'%</td>' +
        '<td style="color:#cbd5e1;">'+Math.round(r.m.j0end/60*10)/10+' min</td>' +
        '<td style="color:#cbd5e1;">$'+r.m.cost+'</td>' +
        '</tr>';
    });
    html += '</tbody></table>';

    results.forEach(function(r, i) {
      var gid = 'ss-cmp-g-'+i;
      html += '<div style="margin-bottom:18px;">' +
        '<div style="color:#cbd5e1;font-size:0.75rem;font-weight:600;margin-bottom:5px;">' +
        (i+1)+'. '+r.st.name+
        ' <span style="color:#94a3b8;font-weight:400;font-size:0.72rem;">— '+r.st.desc+'</span></div>' +
        '<div id="'+gid+'"></div></div>';
    });
    cmp.innerHTML = html;
    results.forEach(function(r, i) { _ssGantt('ss-cmp-g-'+i, r.sched, true); });

    document.getElementById('sim-out').style.display = 'none';
    document.getElementById('sim-swp').style.display = 'none';
  };

  window.simFindOptimal = function () {
    var n  = parseInt(document.getElementById('sim-n').value) || 5;
    var sz = document.getElementById('sim-size').value;
    var sc = _SS.size[sz] || 1.0;
    var gpuDur = 248.6 * sc;

    var xs = [], ysGain = [], ysGPU = [];
    var step = Math.max(5, Math.round(gpuDur * 0.02));
    for (var off = 0; off <= gpuDur * 2.5; off += step) {
      var sched = _ssDES(_ssStratStagger(n, sc, off));
      var m     = _ssMetrics(sched, n, sc);
      xs.push(Math.round(off));
      ysGain.push(m.gain);
      ysGPU.push(m.gpuU);
    }
    var bestI   = ysGain.indexOf(Math.max.apply(null, ysGain));
    var bestOff = xs[bestI], bestGain = ysGain[bestI];

    var swp = document.getElementById('sim-swp');
    if (!swp) return;
    swp.style.display = 'block';
    swp.innerHTML =
      '<div class="bm-section-title" style="margin-bottom:8px;">Optimal Offset Sweep — N='+n+' × '+sz+'</div>' +
      '<p style="color:#94a3b8;font-size:0.8rem;margin:0 0 14px;line-height:1.6;">' +
        'Best stagger offset: <strong style="color:#c7d2fe;">'+bestOff+'s</strong> — gives ' +
        '<strong style="color:#4ade80;">'+bestGain+'%</strong> throughput gain vs sequential. ' +
        'GPU idle time spikes near 0s offset (all jobs fight for GPU at once) and again beyond 2× GPU duration (pipeline gaps appear). ' +
        'The sweet spot is offset ≈ GPU stage duration (<strong style="color:#d97706;">'+Math.round(gpuDur)+'s</strong> for '+sz+' docs).' +
      '</p>' +
      '<div id="ss-sweep-chart" style="height:230px;margin-bottom:24px;"></div>';

    document.getElementById('sim-out').style.display = 'none';
    document.getElementById('sim-cmp').style.display = 'none';

    var el = document.getElementById('ss-sweep-chart');
    if (el && typeof Plotly !== 'undefined') {
      Plotly.newPlot(el, [
        { x:xs, y:ysGain, name:'Throughput gain %', mode:'lines', line:{color:'#6366f1',width:2.5},
          hovertemplate:'%{x}s → %{y}% gain<extra></extra>' },
        { x:xs, y:ysGPU,  name:'GPU utilisation %', mode:'lines', line:{color:'#d97706',width:1.5,dash:'dot'},
          hovertemplate:'%{x}s → %{y}% GPU util<extra></extra>' },
      ], {
        paper_bgcolor:'transparent', plot_bgcolor:'rgba(255,255,255,0.02)',
        margin:{t:8,b:42,l:44,r:16},
        xaxis:{ title:{text:'stagger offset (s)',font:{color:'#94a3b8',size:11}}, tickfont:{color:'#94a3b8',size:10}, gridcolor:'rgba(255,255,255,0.05)', color:'#94a3b8' },
        yaxis:{ title:{text:'%',font:{color:'#94a3b8',size:11}}, tickfont:{color:'#94a3b8',size:10}, gridcolor:'rgba(255,255,255,0.05)', color:'#94a3b8', range:[0,Math.max.apply(null,ysGain)+15] },
        legend:{ font:{color:'#94a3b8',size:10}, bgcolor:'transparent', x:0.65, y:0.98 },
        shapes:[{ type:'line', x0:bestOff, x1:bestOff, y0:0, y1:Math.max.apply(null,ysGain)+15, line:{color:'#4ade80',width:1.5,dash:'dash'} }],
        font:{color:'#94a3b8'},
      }, {responsive:true, displayModeBar:false});
    }
  };

  /* Run all N (1–20) × all 3 sizes × all 6 strategies — no user inputs required */
  window.simRunAll = function () {
    var ALL_N = [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20];
    var ALL_SIZES = [
      {key:'short',  sc:0.25, lbl:'Short'},
      {key:'medium', sc:0.50, lbl:'Medium'},
      {key:'long',   sc:1.0,  lbl:'Full'},
    ];
    var SCOL = {seq:'#64748b',stagger:'#6366f1',scriptfirst:'#0891b2',assembly:'#7c3aed',gpuburst:'#d97706',adaptive:'#4ade80'};
    var SBGD = {seq:'rgba(100,116,139,0.1)',stagger:'rgba(99,102,241,0.1)',scriptfirst:'rgba(8,145,178,0.1)',assembly:'rgba(124,58,237,0.1)',gpuburst:'rgba(217,119,6,0.1)',adaptive:'rgba(74,222,128,0.1)'};
    var SBRD = {seq:'rgba(100,116,139,0.3)',stagger:'rgba(99,102,241,0.3)',scriptfirst:'rgba(8,145,178,0.3)',assembly:'rgba(124,58,237,0.3)',gpuburst:'rgba(217,119,6,0.3)',adaptive:'rgba(74,222,128,0.3)'};

    /* Run all combinations — DES is <1ms each so this is instant */
    var matrix = {};
    ALL_N.forEach(function(n) {
      matrix[n] = {};
      ALL_SIZES.forEach(function(sz) {
        var res = _SS.strats.map(function(st) {
          var sched = _ssDES(_ssRunStrat(st.id, n, sz.sc));
          return {st:st, sched:sched, m:_ssMetrics(sched, n, sz.sc)};
        });
        res.sort(function(a,b){return a.m.total - b.m.total;});
        matrix[n][sz.key] = res;
      });
    });

    /* Count wins across all N × size combinations */
    var winCounts = {};
    _SS.strats.forEach(function(st){winCounts[st.id]=0;});
    ALL_N.forEach(function(n){
      ALL_SIZES.forEach(function(sz){
        winCounts[matrix[n][sz.key][0].st.id]++;
      });
    });

    var html = '<div class="bm-section-title" style="margin-bottom:10px;">All Configurations — N=1 to 20 × 3 Doc Sizes</div>';

    /* Strategy win badges */
    html += '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px;">';
    _SS.strats.forEach(function(st){
      var w = winCounts[st.id]; if (!w) return;
      html += '<div style="background:'+SBGD[st.id]+';border:1px solid '+SBRD[st.id]+';border-radius:8px;padding:6px 14px;">' +
        '<div style="color:'+SCOL[st.id]+';font-size:0.82rem;font-weight:700;">'+st.name+'</div>' +
        '<div style="color:#94a3b8;font-size:0.71rem;">Wins '+w+' of '+(ALL_N.length*ALL_SIZES.length)+' configs</div>' +
        '</div>';
    });
    html += '</div>';

    /* Winner matrix table */
    html += '<div style="overflow-x:auto;margin-bottom:28px;">' +
      '<table class="bm-table" style="width:100%;font-size:0.78rem;">' +
      '<thead><tr>' +
        '<th rowspan="2" style="color:#94a3b8;vertical-align:middle;">N</th>' +
        ALL_SIZES.map(function(sz){
          return '<th colspan="2" style="text-align:center;color:#94a3b8;">'+sz.lbl+'</th>';
        }).join('') +
      '</tr><tr>' +
        ALL_SIZES.map(function(){ return '<th style="color:#94a3b8;">Best Strategy</th><th style="color:#94a3b8;">Time</th>'; }).join('') +
      '</tr></thead><tbody>';

    ALL_N.forEach(function(n){
      html += '<tr><td style="color:#e2e8f0;font-weight:600;">'+n+'</td>';
      ALL_SIZES.forEach(function(sz){
        var best = matrix[n][sz.key][0];
        var time = Math.round(best.m.total/60*10)/10;
        html += '<td style="color:#e2e8f0;font-weight:600;">'+best.st.name+'</td>' +
                '<td style="color:#e2e8f0;">'+time+' min</td>';
      });
      html += '</tr>';
    });
    html += '</tbody></table></div>';

    /* Representative Gantt charts: N=5 × Full */
    var ex_n = 5, ex_sz = 'long';
    var ex_res = matrix[ex_n][ex_sz];
    html += '<div class="bm-section-title" style="margin-bottom:8px;">N=5 Full — Strategy Gantt Charts</div>';
    html += _ssLegend();
    ex_res.forEach(function(r, i){
      html += '<div style="margin-bottom:16px;">' +
        '<div style="color:#cbd5e1;font-size:0.74rem;font-weight:600;margin-bottom:4px;">'+(i+1)+'. '+r.st.name+
        ' <span style="color:#94a3b8;font-weight:400;font-size:0.72rem;">— '+r.st.desc+'</span></div>' +
        '<div id="ss-all-g-'+i+'"></div></div>';
    });

    var cmp = document.getElementById('sim-cmp');
    if (!cmp) return;
    cmp.style.display = 'block';
    cmp.innerHTML = html;
    ex_res.forEach(function(r, i){ _ssGantt('ss-all-g-'+i, r.sched, true); });
    document.getElementById('sim-out').style.display = 'none';
    document.getElementById('sim-swp').style.display = 'none';
  };

  /* ══════════════════════════════════════════════════════════════════════
     MONTE CARLO ENGINE
     Paired simulation: all 6 strategies share the same random stage durations
     per run so win-rates are directly comparable (same "world").
     Distributions: log-normal fit to 277 real pipeline runs.
     ══════════════════════════════════════════════════════════════════════ */

  /* Box-Muller normal sampler */
  var _mcSpare = null;
  function _mcN() {
    if (_mcSpare !== null) { var v = _mcSpare; _mcSpare = null; return v; }
    var u, v, s;
    do { u = Math.random()*2-1; v = Math.random()*2-1; s = u*u+v*v; } while (s >= 1 || s === 0);
    var k = Math.sqrt(-2 * Math.log(s) / s);
    _mcSpare = v * k;
    return u * k;
  }
  function _mcLN(mu, sig) { return Math.exp(mu + sig * _mcN()); }

  /* Per-stage log-normal params (lmu, lsd) — fit to 277 historical runs
     High variance is real: s35 ranges 12 s → 3720 s, s4 6 s → 3266 s */
  /* Baseline log-normal params [mu, sigma] from 277 historical runs — used as fallback */
  var _MC = {
    s2:  [2.1098, 1.4822],   /* Research:   median 4.9s, CV 322% */
    s3:  [3.8035, 0.6314],   /* Script:     median 54s,  CV  34% */
    s3b: [4.3783, 0.5528],   /* Tagging:    median 91s,  CV  29% */
    s31: [2.5462, 1.4329],   /* Emotion:    median 16s,  CV 241% */
    s35: [5.7555, 1.2122],   /* Image Gen:  median 249s, CV 141% */
    s4:  [4.7705, 1.5000],   /* TTS:        median 75s,  CV 164% */
    s6:  [5.2050, 1.1916],   /* Assembly:   median 159s, CV 104% */
  };

  /* Fit log-normal params from the 20 most recent completed pipeline runs.
     Returns { params:{s2:[mu,sig],...}, n_runs:N, from_live:bool, n_samples:{s2:K,...} }
     Falls back to _MC baseline for any stage with fewer than 5 samples. */
  function _mcParamsFromHistory() {
    if (!_bmHistory) return { params:_MC, n_runs:0, from_live:false, n_samples:{} };

    function mapName(name) {
      var n = name.toLowerCase();
      if (n.indexOf('3.1') >= 0 || n.indexOf('emotion') >= 0) return 's31';
      if (n.indexOf('3b') >= 0 || n.indexOf('tagg') >= 0) return 's3b';
      if (n.indexOf('3.5') >= 0 || (n.indexOf('image') >= 0 && n.indexOf('gen') >= 0)) return 's35';
      if (n.indexOf('script') >= 0 || (n.indexOf('stage 3') >= 0 && n.indexOf('3.') < 0)) return 's3';
      if (n.indexOf('research') >= 0 || n.indexOf('academic') >= 0 || n.indexOf('stage 2') >= 0) return 's2';
      if (n.indexOf('tts') >= 0 || n.indexOf('narrat') >= 0 || n.indexOf('stage 4') >= 0) return 's4';
      if (n.indexOf('assembl') >= 0 || n.indexOf('stage 6') >= 0) return 's6';
      return null;
    }

    /* Aggregate trend runs across all departments, keep 20 most recent */
    var allRuns = [];
    ['scholarly','crime','video','manga','storyteller'].forEach(function(dept) {
      if (_bmHistory[dept] && _bmHistory[dept].trend) {
        _bmHistory[dept].trend.forEach(function(r) { allRuns.push(r); });
      }
    });
    allRuns.sort(function(a, b) {
      return (b.started || '').localeCompare(a.started || '');
    });
    var recent = allRuns.slice(0, 20);
    if (!recent.length) return { params:_MC, n_runs:0, from_live:false, n_samples:{} };

    /* Collect per-stage duration samples */
    var stageSamples = {};
    _SS.stages.forEach(function(s) { stageSamples[s.id] = []; });
    recent.forEach(function(run) {
      if (!run.stages) return;
      Object.keys(run.stages).forEach(function(sname) {
        var sid = mapName(sname);
        if (!sid || !stageSamples[sid]) return;
        var dur = run.stages[sname];
        if (dur > 0.5) stageSamples[sid].push(dur);
      });
    });

    /* Fit log-normal per stage; fall back to _MC baseline if < 5 samples */
    var params = {}, n_samples = {};
    _SS.stages.forEach(function(s) {
      var samps = stageSamples[s.id];
      n_samples[s.id] = samps.length;
      if (samps.length >= 5) {
        var logs = samps.map(function(x) { return Math.log(x); });
        var mu   = logs.reduce(function(a, v) { return a + v; }, 0) / logs.length;
        var vari = logs.reduce(function(a, v) { return a + (v-mu)*(v-mu); }, 0) / Math.max(1, logs.length-1);
        params[s.id] = [mu, Math.max(0.05, Math.sqrt(vari))];
      } else {
        params[s.id] = _MC[s.id];
      }
    });

    return { params:params, n_runs:recent.length, from_live:true, n_samples:n_samples };
  }

  /* DES variant that uses per-task duration overrides (_d field) */
  function _mcDES(queue) {
    var slots = {};
    Object.keys(_SS.res).forEach(function(r) { slots[r] = Array(_SS.res[r].slots).fill(0); });
    var uid_end = {}, out = [];
    queue.forEach(function(t) {
      var res     = t.stage.res;
      var dep_end = t.dep ? (uid_end[t.dep] || 0) : 0;
      var early   = Math.max(t.start0 || 0, dep_end);
      var sl      = slots[res], minT = Math.min.apply(null, sl), si = sl.indexOf(minT);
      var start   = Math.max(early, minT);
      var dur     = (t._d !== undefined) ? t._d : t.stage.dur * (t.sc || 1.0);
      var cf      = _SS.res[res].cf;
      if (cf > 0) {
        var olap = 0;
        for (var k = 0; k < out.length; k++) {
          var e = out[k];
          if (e.res === res && e.s < start + dur && e.e > start) olap++;
        }
        if (olap > 0) dur *= (1 + cf * Math.min(olap, 3));
      }
      var end = start + dur;
      sl[si] = end; uid_end[t.uid] = end;
      out.push({ job:t.job, stage:t.stage, res:res, s:start, e:end });
    });
    return out;
  }

  /* Percentile from a sorted numeric array */
  function _mcPct(arr, p) { return arr[Math.max(0, Math.floor((arr.length-1)*p/100))]; }

  /* Aggregate samples → {p10,p50,p90,cvar90,ci95_p50,mean,sd,gpuP50,j0P50,slaPct,n} */
  function _mcAgg(samps, sla_sec) {
    var n = samps.length;
    var tots = samps.map(function(s){return s.total;}).sort(function(a,b){return a-b;});
    var gpus = samps.map(function(s){return s.gpuU;}).sort(function(a,b){return a-b;});
    var j0s  = samps.map(function(s){return s.j0end;}).sort(function(a,b){return a-b;});
    var p10 = _mcPct(tots,10), p50 = _mcPct(tots,50), p90 = _mcPct(tots,90);
    /* CVaR90: mean of worst 10% */
    var tail = tots.slice(Math.floor(n * 0.9));
    var cvar90 = tail.reduce(function(s,v){return s+v;},0) / Math.max(1, tail.length);
    /* 95% CI on P50 via IQR-based SE */
    var iqr = _mcPct(tots,75) - _mcPct(tots,25);
    var ci95_p50 = 1.96 * iqr / (2 * 1.35 * Math.sqrt(n));
    /* Mean + SD */
    var mean = tots.reduce(function(s,v){return s+v;},0) / n;
    var sd = Math.sqrt(tots.reduce(function(s,v){return s+(v-mean)*(v-mean);},0) / Math.max(1,n-1));
    /* SLA: % of runs finishing within sla_sec */
    var slaPct = null;
    if (sla_sec > 0) {
      var under = 0;
      for (var i = 0; i < n; i++) if (tots[i] <= sla_sec) under++;
      slaPct = Math.round(under / n * 100);
    }
    return { p10:p10, p50:p50, p90:p90, cvar90:cvar90,
             ci95_p50:ci95_p50, mean:Math.round(mean), sd:Math.round(sd),
             gpuP50:_mcPct(gpus,50), j0P50:_mcPct(j0s,50), slaPct:slaPct, n:n };
  }

  /* Run n_sims paired simulations.
     opts: { corr:bool, sla_sec:number }
     Techniques: LHS stratified sampling + antithetic variates + Gaussian copula (when corr=true). */
  function _mcBatch(n_jobs, scale, n_sims, opts) {
    opts = opts || {};
    var useCorr = opts.corr !== false;
    var MC = opts.params || _MC;   /* live-fitted params or static fallback */
    var STIDS = _SS.stages.map(function(s){ return s.id; });
    var NS = STIDS.length;
    /* Antithetic: each base world also runs its mirror, halving the variance estimate */
    var n_base = Math.ceil(n_sims / 2);
    /* Cholesky factor — computed once and cached */
    if (useCorr && !_MC_CHOL) _MC_CHOL = _mcChol(_MC_CORR);
    var L = useCorr ? _MC_CHOL : null;
    /* LHS: one stratified uniform per (job × stage × base-world) */
    var lhs = _mcLHSSamples(n_base, n_jobs * NS);
    var perStrat = _SS.strats.map(function(st){ return {st:st, samps:[]}; });

    function buildDM(worldIdx, anti) {
      var dm = {};
      for (var j = 0; j < n_jobs; j++) {
        dm[j] = {};
        /* Step 1: iid standard normals from stratified uniforms */
        var iid = [];
        for (var si = 0; si < NS; si++) {
          var u = lhs[j * NS + si][worldIdx];
          var z = _mcProbit(Math.max(0.0005, Math.min(0.9995, u)));
          iid.push(anti ? -z : z);
        }
        /* Step 2: Cholesky transform for stage correlation (optional) */
        var zc = iid;
        if (L) {
          zc = [];
          for (var si = 0; si < NS; si++) {
            var zv = 0;
            for (var k = 0; k <= si; k++) zv += L[si][k] * iid[k];
            zc.push(zv);
          }
        }
        /* Step 3: log-normal transform per stage */
        for (var si = 0; si < NS; si++) {
          var p = MC[STIDS[si]] || _MC[STIDS[si]];
          dm[j][STIDS[si]] = Math.max(0.1, Math.exp(p[0] + Math.log(scale) + p[1] * zc[si]));
        }
      }
      return dm;
    }

    function runWorld(dm) {
      perStrat.forEach(function(ps) {
        var q = _ssRunStrat(ps.st.id, n_jobs, 1.0, dm);
        q.forEach(function(t){ t._d = dm[t.job][t.stage.id]; });
        ps.samps.push(_ssMetrics(_mcDES(q), n_jobs, 1.0));
      });
    }

    for (var i = 0; i < n_base; i++) {
      runWorld(buildDM(i, false));
      if (perStrat[0].samps.length < n_sims) runWorld(buildDM(i, true));
    }

    var sla = opts.sla_sec || 0;
    perStrat.forEach(function(ps){ ps.agg = _mcAgg(ps.samps, sla); });
    perStrat.sort(function(a,b){ return a.agg.p50 - b.agg.p50; });
    return perStrat;
  }

  /* Win-rate: % of paired runs where strategy A finishes before B */
  function _mcWin(sampsA, sampsB) {
    var w = 0;
    for (var i = 0; i < sampsA.length; i++) if (sampsA[i].total < sampsB[i].total) w++;
    return Math.round(w / sampsA.length * 100);
  }

  /* ── Render: single N/size results ────────────────────────────────── */
  function _mcRenderSingle(results, n_jobs, sz, n_sims, sla_min, convMsg) {
    var seqR = results.find(function(r){return r.st.id==='seq';});
    var topR = results[0];
    var n_actual = topR.samps.length;
    var sla_sec = (sla_min || 0) * 60;

    var ci_min = Math.round(topR.agg.ci95_p50 / 60 * 10) / 10;
    var p50m   = Math.round(topR.agg.p50 / 60 * 10) / 10;
    var cvar_min = Math.round(topR.agg.cvar90 / 60 * 10) / 10;
    var slaStr = (topR.agg.slaPct !== null) ? topR.agg.slaPct+'% finish within '+sla_min+' min. ' : '';

    var html = '<div class="bm-section-title" style="margin-bottom:10px;">' +
      'Monte Carlo — N='+n_jobs+' × '+sz+
      ' &nbsp;<span style="color:#64748b;font-size:0.75rem;font-weight:400;">'+
      n_actual.toLocaleString()+' worlds (LHS + antithetic)</span>' +
      (convMsg ? ' <span style="color:#4ade80;font-size:0.72rem;">'+convMsg+'</span>' : '') +
      '</div>';

    /* Bimodal warnings */
    var warns = _mcBimodalCheck();
    if (warns.length) {
      html += '<div style="background:rgba(251,191,36,0.06);border:1px solid rgba(251,191,36,0.22);border-radius:7px;padding:8px 12px;margin-bottom:12px;">' +
        '<span style="color:#fbbf24;font-size:0.72rem;font-weight:700;">⚠ Possible bimodal distribution: </span>' +
        '<span style="color:#a0b0c0;font-size:0.72rem;">' +
        warns.map(function(w){ return w.lbl+' (CV '+w.cv+'%)'; }).join(', ') +
        ' — may be fast/timeout bimodal. Log-normal may slightly underestimate P90.</span></div>';
    }

    html += '<p style="color:#94a3b8;font-size:0.78rem;margin:0 0 16px;line-height:1.5;">' +
      'Winner: <strong style="color:#4ade80;">'+topR.st.name+'</strong> — ' +
      'P50 <strong style="color:#c7d2fe;">'+p50m+' min</strong> ' +
      '<span style="color:#64748b;font-size:0.74rem;">±'+ci_min+' min (95% CI)</span>, ' +
      'beats sequential '+_mcWin(topR.samps,seqR.samps)+'% of the time. ' +
      slaStr +
      'CVaR90 <strong style="color:#fb923c;">'+cvar_min+' min</strong> ' +
      '<span style="color:#64748b;font-size:0.73rem;">(avg of worst 10% of runs)</span></p>';

    /* Ranked table with CVaR + CI + SLA */
    var showSLA = sla_min > 0;
    html += '<div style="overflow-x:auto;"><table class="bm-table" style="width:100%;margin-bottom:22px;min-width:640px;"><thead><tr>' +
      '<th>#</th><th>Strategy</th><th>P10</th>' +
      '<th>P50 ± 95% CI</th>' +
      '<th>P90</th><th>CVaR90</th>' +
      '<th>Spread</th><th>GPU P50</th><th>vs Sequential</th>' +
      (showSLA ? '<th>≤'+sla_min+'m</th>' : '') +
      '</tr></thead><tbody>';

    results.forEach(function(r, i) {
      var isSeq    = r.st.id === 'seq';
      var spread   = Math.round((r.agg.p90 - r.agg.p10) / 60 * 10) / 10;
      var winRate  = isSeq ? '—' : (_mcWin(r.samps, seqR.samps) + '%');
      var p50_m    = Math.round(r.agg.p50/60*10)/10;
      var ci_m     = Math.round(r.agg.ci95_p50/60*10)/10;
      var p10_m    = Math.round(r.agg.p10/60*10)/10;
      var p90_m    = Math.round(r.agg.p90/60*10)/10;
      var cvar_m   = Math.round(r.agg.cvar90/60*10)/10;
      var rankCol  = i===0?'#4ade80':i<=2?'#a3e635':i<=4?'#fbbf24':'#a0b0c0';
      var wr_int   = parseInt(winRate);
      html += '<tr>' +
        '<td style="color:'+rankCol+';font-weight:700;">'+(i+1)+'</td>' +
        '<td style="color:#b8c8d8;font-weight:600;">'+r.st.name+'</td>' +
        '<td style="color:#94a3b8;font-size:0.78rem;">'+p10_m+' m</td>' +
        '<td><strong style="color:'+rankCol+';">'+p50_m+'</strong>' +
          '<span style="color:#64748b;font-size:0.72rem;"> ±'+ci_m+' min</span></td>' +
        '<td style="color:#94a3b8;font-size:0.78rem;">'+p90_m+' m</td>' +
        '<td style="color:#fb923c;font-size:0.78rem;">'+cvar_m+' m</td>' +
        '<td style="color:'+(spread>30?'#f87171':spread>15?'#fbbf24':'#4ade80')+';">±'+spread+' m</td>' +
        '<td style="color:#a0b0c0;">'+r.agg.gpuP50+'%</td>' +
        '<td style="color:'+(isSeq?'#64748b':wr_int>=80?'#4ade80':wr_int>=55?'#a3e635':'#fbbf24')+';">'+winRate+'</td>' +
        (showSLA ? '<td style="color:'+(r.agg.slaPct>=80?'#4ade80':r.agg.slaPct>=55?'#a3e635':r.agg.slaPct>=30?'#fbbf24':'#f87171')+';">'+(r.agg.slaPct!==null?r.agg.slaPct+'%':'—')+'</td>' : '') +
        '</tr>';
    });
    html += '</tbody></table></div>';

    /* Win matrix */
    html += '<div class="bm-section-title" style="margin-bottom:8px;">Head-to-Head Win Matrix</div>';
    html += '<p style="color:#94a3b8;font-size:0.77rem;margin:0 0 10px;">' +
      'Row strategy vs column — % of worlds where row finishes faster. >50% = row advantage.</p>';
    html += '<div style="overflow-x:auto;"><table class="bm-table" style="font-size:0.72rem;min-width:560px;"><thead><tr>';
    html += '<th style="text-align:left;">↓ Row vs Col →</th>';
    results.forEach(function(r) {
      html += '<th style="font-size:0.66rem;line-height:1.3;max-width:72px;white-space:normal;">'+r.st.name+'</th>';
    });
    html += '</tr></thead><tbody>';
    results.forEach(function(ra) {
      html += '<tr><td style="color:#b8c8d8;font-weight:600;font-size:0.74rem;white-space:nowrap;">'+ra.st.name+'</td>';
      results.forEach(function(rb) {
        if (ra.st.id === rb.st.id) { html += '<td style="color:#334155;">—</td>'; return; }
        var w = _mcWin(ra.samps, rb.samps);
        var col = w>=70?'#4ade80':w>=55?'#a3e635':w>=45?'#fbbf24':w>=30?'#fb923c':'#f87171';
        html += '<td style="color:'+col+';font-weight:'+(w>=60||w<=40?'700':'400')+';">'+w+'%</td>';
      });
      html += '</tr>';
    });
    html += '</tbody></table></div>';

    /* Placeholder for sensitivity tornado (filled async) */
    html += '<div id="mc-sensitivity-out"></div>';

    return html;
  }

  /* ── Render: sweep results (all N values) ──────────────────────────── */
  function _mcRenderSweep(all_results, sz, n_sims, dataSrc, sla_min) {
    var N_VALS = all_results.map(function(r){return r.n_jobs;});
    var html = '<div class="bm-section-title" style="margin-bottom:6px;">N Sweep — Full docs, ' +
      n_sims.toLocaleString()+' sims each</div>';
    if (dataSrc) html += '<div style="color:#64748b;font-size:0.72rem;margin-bottom:10px;">Distribution fit from ' + dataSrc + '</div>';
    html += '<div style="background:#1e293b;border:1px solid #334155;border-radius:6px;padding:8px 14px;margin-bottom:12px;font-size:.73rem;color:#94a3b8;line-height:1.6;">' +
      '<b style="color:#fbbf24;">⚡ Why does this complete in seconds?</b> ' +
      'No pipeline code runs. Each "world" is pure JS arithmetic: draw 7 log-normal stage durations → schedule N jobs through a priority queue → record completion time (~100 float ops). ' +
      '3 sizes × 14 N values × 1,000 worlds = <b style="color:#e2e8f0;">42,000 simulated worlds</b> total (~25 million arithmetic ops, &lt;100ms of real compute). ' +
      'The extra seconds are setTimeout gaps that keep the UI responsive. ' +
      'The SLA target <b style="color:#e2e8f0;">only filters the % column</b> — it does not change loop count or depth.' +
      '</div>';
    html += '<p style="color:#94a3b8;font-size:0.78rem;margin:0 0 14px;line-height:1.5;">' +
      'Each cell = % of worlds where that strategy finished fastest. ' +
      'Deep green (≥50%) = dominant. Bold = clear winner for that N.</p>';

    /* Best-strategy heatmap */
    html += '<div style="overflow-x:auto;margin-bottom:20px;"><table class="bm-table" style="font-size:0.7rem;min-width:700px;">';
    html += '<thead><tr><th>Strategy</th>';
    N_VALS.forEach(function(n){html += '<th>N='+n+'</th>';});
    html += '</tr></thead><tbody>';

    _SS.strats.forEach(function(st) {
      html += '<tr><td style="color:#b8c8d8;font-weight:600;white-space:nowrap;cursor:pointer;text-decoration:underline dotted;text-underline-offset:3px;" data-strat-id="'+st.id+'" title="Click to learn about '+st.name+'">'+st.name+'</td>';
      all_results.forEach(function(ar) {
        /* Count worlds where this strategy won */
        var winners = new Array(ar.results.length).fill(0);
        for (var i = 0; i < n_sims; i++) {
          var bestT = Infinity, bestIdx = 0;
          ar.results.forEach(function(r, ri) {
            if (r.samps[i].total < bestT) { bestT = r.samps[i].total; bestIdx = ri; }
          });
          winners[bestIdx]++;
        }
        var thisIdx = ar.results.findIndex(function(r){return r.st.id===st.id;});
        var frac    = Math.round(winners[Math.max(0,thisIdx)] / n_sims * 100);
        var col     = frac>=50?'#22c55e':frac>=30?'#65a30d':frac>=15?'#d97706':frac>=5?'#64748b':'#1e293b';
        var textCol = frac>=5?col:'#334155';
        html += '<td style="color:'+textCol+';font-weight:'+(frac>=40?'700':'400')+';">'+frac+'%</td>';
      });
      html += '</tr>';
    });
    html += '</tbody></table></div>';

    /* P50 Plotly chart placeholder */
    html += '<div class="bm-section-title" style="margin-bottom:8px;">P50 Wall-Clock vs N</div>';
    html += '<div id="mc-sweep-chart" style="height:260px;margin-bottom:20px;"></div>';

    /* Recommendation */
    var showSLA = sla_min > 0;
    html += '<div class="bm-section-title" style="margin-bottom:8px;">Recommendation by N</div>';
    html += '<table class="bm-table" style="width:100%;"><thead><tr>' +
      '<th>N</th><th>Best Strategy</th><th>P50</th>' +
      (showSLA ? '<th>SLA <span style="color:#64748b;font-weight:400;">≤'+sla_min+'min</span></th>' : '') +
      '<th>vs Sequential P50</th></tr></thead><tbody>';
    all_results.forEach(function(ar) {
      var best  = ar.results[0];
      var seqR  = ar.results.find(function(r){return r.st.id==='seq';});
      var gain  = Math.round((seqR.agg.p50 - best.agg.p50) / seqR.agg.p50 * 100);
      var p50m  = Math.round(best.agg.p50/60*10)/10;
      var seqm  = Math.round(seqR.agg.p50/60*10)/10;
      var slaCol = '';
      if (showSLA && best.agg.slaPct !== null) {
        var sp = best.agg.slaPct;
        var sc = sp >= 90 ? '#22c55e' : sp >= 70 ? '#65a30d' : sp >= 50 ? '#d97706' : '#ef4444';
        slaCol = '<td style="color:'+sc+';font-weight:600;">'+sp+'%</td>';
      } else if (showSLA) { slaCol = '<td style="color:#64748b;">—</td>'; }
      var gainCol = gain > 0 ? '#22c55e' : '#ef4444';
      html += '<tr>' +
        '<td style="color:#e2e8f0;font-weight:700;">'+ar.n_jobs+'</td>' +
        '<td style="color:#e2e8f0;font-weight:600;cursor:pointer;text-decoration:underline dotted;text-underline-offset:3px;" data-strat-id="'+best.st.id+'" data-strat-n="'+ar.n_jobs+'" data-strat-p50="'+Math.round(best.agg.p50)+'" data-strat-seq-p50="'+Math.round(seqR.agg.p50)+'" title="Click to learn about '+best.st.name+'">'+best.st.name+'</td>' +
        '<td class="bm-td-avg">'+p50m+' min</td>' +
        slaCol +
        '<td style="color:'+gainCol+';">'+gain+'% faster (seq='+seqm+'m)</td>' +
        '</tr>';
    });
    html += '</tbody></table>';

    return html;
  }

  function _mcRenderSweepChart(all_results) {
    var el = document.getElementById('mc-sweep-chart');
    if (!el || typeof Plotly === 'undefined') return;
    var xs = all_results.map(function(r){return r.n_jobs;});
    var STRAT_COLS = {
      seq:'#64748b', stagger:'#6366f1', scriptfirst:'#0891b2',
      assembly:'#7c3aed', gpuburst:'#d97706', adaptive:'#4ade80',
    };
    var traces = _SS.strats.map(function(st) {
      var ys50 = all_results.map(function(ar) {
        var r = ar.results.find(function(r){return r.st.id===st.id;});
        return r ? Math.round(r.agg.p50/60*10)/10 : null;
      });
      var ys10 = all_results.map(function(ar) {
        var r = ar.results.find(function(r){return r.st.id===st.id;});
        return r ? Math.round(r.agg.p10/60*10)/10 : null;
      });
      var ys90 = all_results.map(function(ar) {
        var r = ar.results.find(function(r){return r.st.id===st.id;});
        return r ? Math.round(r.agg.p90/60*10)/10 : null;
      });
      return [
        /* Shaded P10-P90 band */
        { x: xs.concat(xs.slice().reverse()),
          y: ys90.concat(ys10.slice().reverse()),
          fill:'toself', fillcolor:_nvRgba(STRAT_COLS[st.id]||'#6366f1',0.10),
          line:{color:'transparent'}, showlegend:false, hoverinfo:'skip',
          name: st.name + ' band' },
        /* P50 line */
        { x:xs, y:ys50, name:st.name, mode:'lines+markers',
          line:{color:STRAT_COLS[st.id]||'#6366f1',width:2},
          marker:{size:5, color:STRAT_COLS[st.id]||'#6366f1'},
          hovertemplate:'N=%{x}  P50=%{y}m<extra>'+st.name+'</extra>' },
      ];
    });
    Plotly.newPlot(el, [].concat.apply([], traces), {
      paper_bgcolor:'transparent', plot_bgcolor:'rgba(255,255,255,0.02)',
      margin:{t:8,b:42,l:46,r:16},
      xaxis:{ title:{text:'N (concurrent jobs)',font:{color:'#94a3b8',size:11}},
              tickfont:{color:'#94a3b8',size:10}, gridcolor:'rgba(255,255,255,0.05)', color:'#94a3b8', dtick:1 },
      yaxis:{ title:{text:'Wall-clock P50 (min)',font:{color:'#94a3b8',size:11}},
              tickfont:{color:'#94a3b8',size:10}, gridcolor:'rgba(255,255,255,0.05)', color:'#94a3b8' },
      legend:{ font:{color:'#94a3b8',size:10}, bgcolor:'transparent', orientation:'h', y:-0.2 },
      font:{color:'#94a3b8'},
    }, {responsive:true, displayModeBar:false});
  }

  /* ══════════════════════════════════════════════════════════════════════
     NEURAL NETWORK VISUALIZATION
     Canvas 2D, RAF loop, bezier edges, convergence zoom, sweet-spot reveal.
     ══════════════════════════════════════════════════════════════════════ */

  var _NV = {
    cvs:null, ctx:null, W:0, H:0, dpr:1,
    nodes:[], edges:[], stratEdges:{}, stratCenters:{}, stratRep:{},
    fireQ:[], glows:[], raf:null,
    state:'idle',            /* idle|running|converging|zooming|revealed */
    winner:null, winnerEdge:null,
    zoom:{ s:1, tx:0, ty:0, ts:1, ttx:0, tty:0 },
    COLS:{ seq:'#64748b', stagger:'#6366f1', scriptfirst:'#0891b2',
           assembly:'#7c3aed', gpuburst:'#d97706', adaptive:'#4ade80' },
  };

  function _nvRgba(hex, a) {
    var r=parseInt(hex.slice(1,3),16), g=parseInt(hex.slice(3,5),16), b=parseInt(hex.slice(5,7),16);
    return 'rgba('+r+','+g+','+b+','+a+')';
  }

  function _nvMkEdge(x1,y1,x2,y2,col,sid) {
    var dx=x2-x1, dy=y2-y1;
    return { x1:x1,y1:y1,x2:x2,y2:y2,
      cpx1:x1+dx*0.3+(Math.random()-0.5)*50, cpy1:y1+dy*0.3+(Math.random()-0.5)*50,
      cpx2:x1+dx*0.7+(Math.random()-0.5)*50, cpy2:y1+dy*0.7+(Math.random()-0.5)*50,
      col:col, sid:sid, fired:0 };
  }

  function _nvEdge(e, alpha, lw) {
    var c=_NV.ctx;
    c.beginPath(); c.moveTo(e.x1,e.y1);
    c.bezierCurveTo(e.cpx1,e.cpy1,e.cpx2,e.cpy2,e.x2,e.y2);
    c.strokeStyle=_nvRgba(e.col,alpha); c.lineWidth=lw||0.5; c.stroke();
  }

  /* Sample a cubic bezier at t, return distance to (mx,my) */
  function _nvBezierDist(e, mx, my) {
    var best=Infinity;
    for(var i=0;i<=80;i++){
      var t=i/80, mt=1-t;
      var x=mt*mt*mt*e.x1+3*mt*mt*t*e.cpx1+3*mt*t*t*e.cpx2+t*t*t*e.x2;
      var y=mt*mt*mt*e.y1+3*mt*mt*t*e.cpy1+3*mt*t*t*e.cpy2+t*t*t*e.y2;
      var d=(x-mx)*(x-mx)+(y-my)*(y-my);
      if(d<best) best=d;
    }
    return Math.sqrt(best);
  }

  function _nvNode(n, alpha) {
    var c=_NV.ctx, a=alpha===undefined?1:alpha;
    var gr=c.createRadialGradient(n.x,n.y,0,n.x,n.y,n.r*3.2);
    gr.addColorStop(0,_nvRgba(n.col,0.35*a)); gr.addColorStop(1,_nvRgba(n.col,0));
    c.beginPath(); c.arc(n.x,n.y,n.r*3.2,0,Math.PI*2); c.fillStyle=gr; c.fill();
    c.beginPath(); c.arc(n.x,n.y,n.r,0,Math.PI*2); c.fillStyle=_nvRgba(n.col,a); c.fill();
  }

  function _nvInit() {
    var cvs=document.getElementById('mc-neural-cvs');
    var wrap=document.getElementById('mc-cvs-wrap');
    if (!cvs||!wrap) return false;
    _NV.dpr=window.devicePixelRatio||1;
    _NV.W=wrap.offsetWidth||680; _NV.H=480;
    cvs.width=_NV.W*_NV.dpr; cvs.height=_NV.H*_NV.dpr;
    cvs.style.width='100%'; cvs.style.height='480px';
    _NV.cvs=cvs; _NV.ctx=cvs.getContext('2d');
    _NV.ctx.scale(_NV.dpr,_NV.dpr);
    _NV.nodes=[]; _NV.edges=[]; _NV.stratEdges={}; _NV.stratCenters={}; _NV.stratRep={};
    _NV.fireQ=[]; _NV.glows=[]; _NV.winner=null; _NV.winnerEdge=null; _NV.state='idle';
    _NV.zoom={s:1,tx:0,ty:0,ts:1,ttx:0,tty:0};

    /* Canvas interaction — only active after winner is revealed */
    if(!cvs._nvListened){
      cvs._nvListened=true;
      function _nvCanvasCoords(ev){
        var rect=cvs.getBoundingClientRect();
        var cssX=ev.clientX-rect.left, cssY=ev.clientY-rect.top;
        var scaleX=_NV.W/rect.width, scaleY=_NV.H/rect.height;
        var z=_NV.zoom;
        return {x:(cssX*scaleX-z.tx)/z.s, y:(cssY*scaleY-z.ty)/z.s};
      }
      function _nvOnWinnerLine(ev){
        if(_NV.state!=='revealed'||!_NV.winnerEdge) return false;
        var p=_nvCanvasCoords(ev);
        return _nvBezierDist(_NV.winnerEdge,p.x,p.y)<14/_NV.zoom.s;
      }
      cvs.addEventListener('mousemove',function(ev){
        cvs.style.cursor=_nvOnWinnerLine(ev)?'pointer':'default';
      });
      cvs.addEventListener('click',function(ev){
        if(_nvOnWinnerLine(ev) && _NV.winner && window.mcShowStrategyDialog){
          window.mcShowStrategyDialog(_NV.winner);
        }
      });
    }

    _nvBuild(); return true;
  }

  function _nvBuild() {
    var W=_NV.W, H=_NV.H;
    var LINES=180;

    /* Per-run chaos scalar: low = gentle arcs, high = wild loops off-screen */
    var chaos = 0.5 + Math.random()*2.2;

    _SS.strats.forEach(function(st){
      var col=_NV.COLS[st.id]||'#6366f1';

      /* Each strategy gets a randomly placed origin zone this run — anywhere on canvas */
      var ancX = W*(0.04 + Math.random()*0.92);
      var ancY = H*(0.04 + Math.random()*0.92);
      /* Bundle spread: some runs tight clusters, some loose fans */
      var spreadX = W*(0.04 + Math.random()*0.22);
      var spreadY = H*(0.04 + Math.random()*0.22);

      var stEdges=[];
      for(var k=0;k<LINES;k++){
        var x1 = ancX + (Math.random()-0.5)*spreadX;
        var y1 = ancY + (Math.random()-0.5)*spreadY;
        var x2 = Math.random()*W;
        var y2 = Math.random()*H;
        /* Control points deviate from the start/end by chaos×canvas — can loop off-screen */
        var cp1x = x1 + (Math.random()-0.5)*W*chaos;
        var cp1y = y1 + (Math.random()-0.5)*H*chaos;
        var cp2x = x2 + (Math.random()-0.5)*W*chaos;
        var cp2y = y2 + (Math.random()-0.5)*H*chaos;
        var e={x1:x1,y1:y1,x2:x2,y2:y2,
               cpx1:cp1x,cpy1:cp1y,cpx2:cp2x,cpy2:cp2y,
               col:col,sid:st.id,fired:0};
        stEdges.push(e);
        _NV.edges.push(e);
      }

      _NV.stratEdges[st.id]=stEdges;

      var rx1 = ancX+(Math.random()-0.5)*spreadX;
      var ry1 = ancY+(Math.random()-0.5)*spreadY;
      var rx2 = Math.random()*W;
      var ry2 = Math.random()*H;
      var repE={
        x1:rx1, y1:ry1, x2:rx2, y2:ry2,
        cpx1:rx1+(Math.random()-0.5)*W*chaos,
        cpy1:ry1+(Math.random()-0.5)*H*chaos,
        cpx2:rx2+(Math.random()-0.5)*W*chaos,
        cpy2:ry2+(Math.random()-0.5)*H*chaos,
        col:col, sid:st.id, fired:0, rep:true
      };
      _NV.stratRep[st.id]=repE;

      _NV.stratCenters[st.id]={
        cx:0.125*repE.x1+0.375*repE.cpx1+0.375*repE.cpx2+0.125*repE.x2,
        cy:0.125*repE.y1+0.375*repE.cpy1+0.375*repE.cpy2+0.125*repE.y2
      };
    });
  }

  function _nvFrame() {
    var c=_NV.ctx; if(!c) return;
    var W=_NV.W, H=_NV.H, dpr=_NV.dpr;
    var z=_NV.zoom;
    z.s  += (z.ts  - z.s)  * 0.032;
    z.tx += (z.ttx - z.tx) * 0.032;
    z.ty += (z.tty - z.ty) * 0.032;

    c.save();
    c.clearRect(0,0,W*dpr,H*dpr);
    c.setTransform(1,0,0,1,0,0);
    c.fillStyle='#060c1a'; c.fillRect(0,0,W*dpr,H*dpr);
    c.setTransform(z.s*dpr,0,0,z.s*dpr,z.tx*dpr,z.ty*dpr);

    var win=_NV.winner;
    var conv=(win&&(_NV.state==='converging'||_NV.state==='zooming'||_NV.state==='revealed'));

    /* Running: draw all lines ultra-thin at low alpha, batched per strategy */
    if(!conv){
      _SS.strats.forEach(function(st){
        var edges=_NV.stratEdges[st.id]; if(!edges) return;
        c.strokeStyle=_nvRgba(_NV.COLS[st.id]||'#6366f1',0.07);
        c.lineWidth=0.25;
        edges.forEach(function(e){
          c.beginPath(); c.moveTo(e.x1,e.y1);
          c.bezierCurveTo(e.cpx1,e.cpy1,e.cpx2,e.cpy2,e.x2,e.y2);
          c.stroke();
        });
      });
    }

    /* Convergence: ALL bundles become soft blue ghosts so they're visible but never compete */
    if(conv){
      _SS.strats.forEach(function(st){
        var edges=_NV.stratEdges[st.id]; if(!edges) return;
        c.strokeStyle=_nvRgba('#38bdf8',0.12);
        c.lineWidth=0.3;
        edges.forEach(function(e){
          c.beginPath(); c.moveTo(e.x1,e.y1);
          c.bezierCurveTo(e.cpx1,e.cpy1,e.cpx2,e.cpy2,e.x2,e.y2);
          c.stroke();
        });
      });
    }

    /* ONLY the single representative winner line gets the bright layered glow */
    if(conv && _NV.winnerEdge){
      var re=_NV.winnerEdge;
      var wCol=_NV.COLS[win]||'#4ade80';
      /* Outer halo */
      c.strokeStyle=_nvRgba(wCol,0.18); c.lineWidth=7;
      c.beginPath(); c.moveTo(re.x1,re.y1);
      c.bezierCurveTo(re.cpx1,re.cpy1,re.cpx2,re.cpy2,re.x2,re.y2); c.stroke();
      /* Mid glow */
      c.strokeStyle=_nvRgba(wCol,0.55); c.lineWidth=2.2;
      c.beginPath(); c.moveTo(re.x1,re.y1);
      c.bezierCurveTo(re.cpx1,re.cpy1,re.cpx2,re.cpy2,re.x2,re.y2); c.stroke();
      /* Sharp core */
      c.strokeStyle=_nvRgba(wCol,0.97); c.lineWidth=0.7;
      c.beginPath(); c.moveTo(re.x1,re.y1);
      c.bezierCurveTo(re.cpx1,re.cpy1,re.cpx2,re.cpy2,re.x2,re.y2); c.stroke();
    }

    /* Drain fire queue */
    if(_NV.state==='running'){
      for(var qi=0;qi<12&&_NV.fireQ.length;qi++){
        var ev=_NV.fireQ.shift();
        _NV.glows.push({e:ev.e,a:1.0,col:ev.col,dec:0.008+Math.random()*0.009});
      }
    }

    /* Active glow pulses — thin bright flashes */
    for(var gi=_NV.glows.length-1;gi>=0;gi--){
      var g=_NV.glows[gi];
      var dim=(conv&&g.e.sid!==win)?0.04:1;
      c.strokeStyle=_nvRgba(g.e.col,g.a*0.85*dim); c.lineWidth=0.7;
      c.beginPath(); c.moveTo(g.e.x1,g.e.y1);
      c.bezierCurveTo(g.e.cpx1,g.e.cpy1,g.e.cpx2,g.e.cpy2,g.e.x2,g.e.y2);
      c.stroke();
      c.strokeStyle=_nvRgba(g.e.col,g.a*0.20*dim); c.lineWidth=2.5;
      c.beginPath(); c.moveTo(g.e.x1,g.e.y1);
      c.bezierCurveTo(g.e.cpx1,g.e.cpy1,g.e.cpx2,g.e.cpy2,g.e.x2,g.e.y2);
      c.stroke();
      g.a-=g.dec;
      if(g.a<=0){g.e.fired++;_NV.glows.splice(gi,1);}
    }

    /* Strategy name labels — left anchor, always readable */
    if(z.s<2.5){
      _SS.strats.forEach(function(st){
        var sc=_NV.stratCenters[st.id]; if(!sc) return;
        var isW=(st.id===win);
        var dim=(conv&&!isW)?0.08:0.90;
        var col=_NV.COLS[st.id]||'#6366f1';
        c.font=(isW&&conv?'bold ':'')+'11px monospace';
        c.textAlign='left';
        c.fillStyle=_nvRgba(col,dim);
        c.fillText(st.name, sc.cx+6, sc.cy+4);
      });
    }
    c.restore();
  }

  function _nvStartLoop() {
    _NV.state='running';
    (function loop(){ _nvFrame(); _NV.raf=requestAnimationFrame(loop); })();
  }
  function _nvStopLoop(){ if(_NV.raf){cancelAnimationFrame(_NV.raf);_NV.raf=null;} }

  function _nvFire(sid, n) {
    var edges=_NV.stratEdges[sid]; if(!edges||!edges.length) return;
    var col=_NV.COLS[sid]||'#6366f1';
    /* Fire ~5% of the edge bundle per call for density that scales with line count */
    var cnt = n || Math.max(6, Math.floor(edges.length*0.05));
    for (var i=0;i<cnt;i++) {
      if (Math.random()<0.25) continue;
      _NV.fireQ.push({e:edges[Math.floor(Math.random()*edges.length)],col:col});
    }
  }

  function _nvReveal(winnerId, panelData) {
    _NV.winner=winnerId; _NV.winnerEdge=_NV.stratRep[winnerId]||null; _NV.state='converging';
    /* Burst-glow only the representative line on reveal */
    if(_NV.winnerEdge){
      _NV.glows.push({e:_NV.winnerEdge,a:0.95,col:_NV.COLS[winnerId]||'#4ade80',dec:0.002});
    }
    setTimeout(function(){ _nvZoom(winnerId, function(){
      var lbl=document.getElementById('mc-sweet-lbl');
      if (lbl){ lbl.style.display='block'; setTimeout(function(){lbl.style.opacity='1';},40); }
      setTimeout(function(){ _nvSlidePanel(panelData); }, 950);
    }); }, 1400);
  }

  function _nvZoom(sid, cb) {
    _NV.state='zooming';
    var sc=_NV.stratCenters[sid]; if(!sc){cb&&cb();return;}
    var W=_NV.W, H=_NV.H, ts=2.7;
    _NV.zoom.ts=ts; _NV.zoom.ttx=W/2-sc.cx*ts; _NV.zoom.tty=H/2-sc.cy*ts;
    var t0=Date.now();
    var chk=setInterval(function(){
      if (Math.abs(_NV.zoom.s-ts)<0.06||(Date.now()-t0>3000)){
        clearInterval(chk); _NV.state='revealed'; cb&&cb();
      }
    },80);
  }

  function _nvSlidePanel(data) {
    var cw=document.getElementById('mc-cvs-wrap');
    var pnl=document.getElementById('mc-strat-pnl');
    var inn=document.getElementById('mc-strat-inner');
    if (!cw||!pnl||!inn) return;
    cw.style.flex='0 0 58%';
    pnl.style.flex='0 0 42%';
    pnl.style.opacity='1';
    if (!data) return;
    var col=_NV.COLS[data.id]||'#4ade80';
    var st=_SS.strats.find(function(s){return s.id===data.id;})||{name:data.id,desc:''};
    var agg=data.agg||{};
    var p50=Math.round((agg.p50||0)/60*10)/10;
    var p10=Math.round((agg.p10||0)/60*10)/10;
    var p90=Math.round((agg.p90||0)/60*10)/10;
    var w=data.winVsSeq||0;
    inn.innerHTML=
      '<div style="display:flex;align-items:center;gap:9px;margin-bottom:14px;">' +
        '<span style="width:12px;height:12px;border-radius:50%;background:'+col+';display:inline-block;box-shadow:0 0 10px '+col+';flex-shrink:0;"></span>' +
        '<span style="color:'+col+';font-size:0.95rem;font-weight:700;line-height:1.25;">'+st.name+'</span>' +
      '</div>' +
      '<div style="color:#64748b;font-size:0.76rem;margin-bottom:16px;line-height:1.6;">'+st.desc+'</div>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:16px;">' +
        _nvMiniCard('P50 time', p50+' min', col) +
        _nvMiniCard('Wins vs seq.', w+'%', w>=70?'#4ade80':w>=50?'#a3e635':'#fbbf24') +
        _nvMiniCard('P10 (best)', p10+' min', '#a0b0c0') +
        _nvMiniCard('P90 (worst)', p90+' min', '#a0b0c0') +
        _nvMiniCard('GPU util P50', (agg.gpuP50||0)+'%', '#d97706') +
        _nvMiniCard('Spread', Math.round(((agg.p90||0)-(agg.p10||0))/60*10)/10+' min', '#94a3b8') +
      '</div>' +
      '<div style="border-top:1px solid rgba(255,255,255,0.06);padding-top:12px;">' +
        '<div style="color:#94a3b8;font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:8px;">Why it wins</div>' +
        '<div style="color:#94a3b8;font-size:0.76rem;line-height:1.65;">'+_nvWhy(data.id,data.n_jobs,w,agg)+'</div>' +
      '</div>';
  }

  function _nvMiniCard(lbl, val, col) {
    return '<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:7px;padding:9px 10px;">' +
      '<div style="color:#64748b;font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:3px;">'+lbl+'</div>' +
      '<div style="color:'+col+';font-size:1.05rem;font-weight:700;">'+val+'</div></div>';
  }

  function _nvWhy(id, n, w, agg) {
    var spread=Math.round(((agg.p90||0)-(agg.p10||0))/60*10)/10;
    var lookup={
      seq:'Baseline control. No scheduling overhead, no resource contention. Competitive at low N where overlap gains are minimal.',
      stagger:'Keeps the GPU perpetually occupied by offsetting each job by exactly the image-gen duration. Breaks down when image-gen variance disrupts the alignment.',
      scriptfirst:'Removes API wait from the GPU critical path by pre-generating all scripts. Pays off when N is large enough that the script batch completes before GPU finishes job 0.',
      assembly:'Treats each stage as a factory station. Efficient when stage durations are balanced — the pipeline stays full with no idle stations.',
      gpuburst:'Explicit barrier ensures all jobs queue simultaneously for the GPU. GPU runs non-stop. Trade-off: job 0 waits for all scripts before GPU starts.',
      adaptive:'Dynamically assigns GPU to whichever job is ready earliest. Under real-world duration variance this consistently outperforms fixed-offset strategies.',
    };
    var base=lookup[id]||'Outperformed all strategies under the simulated conditions.';
    var verdict=w>=78?' Wins '+w+'% of worlds — a dominant result at N='+n+'.'
      :w>=58?' Wins '+w+'% of worlds at N='+n+' — a clear advantage.'
      :' Edges out the competition in '+w+'% of worlds at N='+n+'.';
    var note=spread>28?' Wide spread (±'+spread+' min) reflects real image-gen and TTS variance — plan for tail runs.':'';
    return base+verdict+note;
  }

  /* ══════════════════════════════════════════════════════════════════════
     SAMPLING ENHANCEMENTS
     1. Inverse normal CDF (probit) — for LHS quantile transform
     2. Cholesky decomposition — for Gaussian copula stage correlation
     3. Latin Hypercube Sampling — stratified uniforms for faster convergence
     4. Convergence detection — auto-stop when SE/mean < 0.8%
     5. Sensitivity analysis — tornado: which stage drives P90 variance
     6. Bimodal check — flag stages with CV > 180%
     ══════════════════════════════════════════════════════════════════════ */

  /* Correlation matrix: stage order = s2,s3,s3b,s31,s35,s4,s6
     API stages (s2/s3/s3b/s31) share OpenAI latency — corr ~0.40-0.65.
     GPU/TTS/CPU are largely independent of the API cluster. */
  var _MC_CORR = [
    [1.00, 0.60, 0.40, 0.65, 0.05, 0.05, 0.00],
    [0.60, 1.00, 0.45, 0.60, 0.05, 0.05, 0.00],
    [0.40, 0.45, 1.00, 0.40, 0.05, 0.05, 0.00],
    [0.65, 0.60, 0.40, 1.00, 0.05, 0.05, 0.00],
    [0.05, 0.05, 0.05, 0.05, 1.00, 0.15, 0.20],
    [0.05, 0.05, 0.05, 0.05, 0.15, 1.00, 0.10],
    [0.00, 0.00, 0.00, 0.00, 0.20, 0.10, 1.00],
  ];
  var _MC_CHOL = null; /* Cholesky factor, computed once */

  /* Peter Acklam's rational approximation to the inverse normal CDF (max err 1.15e-9) */
  function _mcProbit(p) {
    if (p <= 0) return -8; if (p >= 1) return 8;
    var a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
              1.383577518672690e+02, -3.066479806614716e+01,  2.506628277459239e+00];
    var b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
              6.680131188771972e+01, -1.328068155288572e+01];
    var c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
             -2.549732539343734e+00,  4.374664141464968e+00,  2.938163982698783e+00];
    var d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00];
    var pL = 0.02425, pH = 1 - pL, q, r;
    if (p < pL) {
      q = Math.sqrt(-2 * Math.log(p));
      return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) /
             ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1);
    } else if (p <= pH) {
      q = p - 0.5; r = q*q;
      return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q /
             (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1);
    } else {
      q = Math.sqrt(-2 * Math.log(1 - p));
      return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) /
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1);
    }
  }

  /* Lower Cholesky factor of a symmetric PD matrix */
  function _mcChol(R) {
    var n = R.length, L = [];
    for (var i = 0; i < n; i++) {
      L.push([]);
      for (var j = 0; j < n; j++) L[i].push(0);
      for (var j = 0; j <= i; j++) {
        var s = 0;
        for (var k = 0; k < j; k++) s += L[i][k] * L[j][k];
        L[i][j] = i === j ? Math.sqrt(Math.max(0, R[i][i] - s))
                           : (L[j][j] > 1e-12 ? (R[i][j] - s) / L[j][j] : 0);
      }
    }
    return L;
  }

  /* Latin Hypercube Sampling: returns n_dim shuffled stratified columns, each length n */
  function _mcLHSSamples(n, n_dim) {
    var out = [];
    for (var d = 0; d < n_dim; d++) {
      var col = [];
      for (var i = 0; i < n; i++) col.push((i + Math.random()) / n);
      for (var i = n - 1; i > 0; i--) {
        var j = Math.floor(Math.random() * (i + 1));
        var tmp = col[i]; col[i] = col[j]; col[j] = tmp;
      }
      out.push(col);
    }
    return out;
  }

  /* Convergence: true when SE/mean of total-time < 0.8% */
  function _mcConverged(samps) {
    var n = samps.length;
    if (n < 120) return false;
    var tots = samps.map(function(s){ return s.total; });
    var mean = tots.reduce(function(a,b){ return a+b; }, 0) / n;
    var sd = Math.sqrt(tots.reduce(function(s,v){ return s+(v-mean)*(v-mean); }, 0) / (n-1));
    return (sd / Math.sqrt(n)) / mean < 0.008;
  }

  /* Sensitivity analysis: freeze each stage's variance, measure P90 drop for winner strategy.
     Uses 300 sims per run — enough for stable relative ranking. */
  function _mcSensitivity(n_jobs, scale, opts) {
    var n_s = 300;
    var baseline = _mcBatch(n_jobs, scale, n_s, opts);
    var topId = baseline[0].st.id, baseP90 = baseline[0].agg.p90;
    var contribs = _SS.stages.map(function(stg) {
      var saved = _MC[stg.id][1];
      _MC[stg.id][1] = 0; /* freeze variance */
      var res = _mcBatch(n_jobs, scale, n_s, opts);
      var noVarR = res.find(function(r){ return r.st.id === topId; }) || res[0];
      _MC[stg.id][1] = saved;
      return { lbl:stg.lbl, id:stg.id, reduction:Math.max(0, baseP90 - noVarR.agg.p90) };
    });
    contribs.sort(function(a,b){ return b.reduction - a.reduction; });
    return { baseP90:baseP90, contribs:contribs, winner:topId };
  }

  /* Flag stages whose log-normal CV > 180% (possible bimodal distribution) */
  function _mcBimodalCheck() {
    var warns = [];
    _SS.stages.forEach(function(s) {
      var sig = _MC[s.id][1];
      var cv = Math.round(Math.sqrt(Math.exp(sig * sig) - 1) * 100);
      if (cv > 180) warns.push({ lbl:s.lbl, cv:cv });
    });
    return warns;
  }

  /* Render tornado chart for sensitivity analysis */
  function _mcRenderSensitivity(sens) {
    if (!sens || !sens.contribs || !sens.contribs.length) return '';
    var maxR = sens.contribs[0].reduction || 1;
    var html = '<div class="bm-section-title" style="margin:22px 0 8px;">Variance Sensitivity — Tornado Chart</div>';
    html += '<p style="color:#94a3b8;font-size:0.77rem;margin:0 0 12px;line-height:1.5;">How much P90 drops if each stage\'s randomness is removed entirely. Longest bar = biggest opportunity to reduce scheduling uncertainty.</p>';
    html += '<div style="display:flex;flex-direction:column;gap:6px;">';
    sens.contribs.forEach(function(c) {
      var pct = c.reduction / maxR;
      var barW = Math.max(2, Math.round(pct * 100));
      var red_min = Math.round(c.reduction / 60 * 10) / 10;
      var col = pct > 0.65 ? '#f87171' : pct > 0.35 ? '#fbbf24' : '#4ade80';
      html += '<div style="display:flex;align-items:center;gap:10px;">' +
        '<div style="width:88px;text-align:right;color:#94a3b8;font-size:0.74rem;white-space:nowrap;">' + c.lbl + '</div>' +
        '<div style="flex:1;background:rgba(255,255,255,0.04);border-radius:3px;height:16px;overflow:hidden;">' +
          '<div style="width:'+barW+'%;height:100%;background:'+col+';border-radius:3px;transition:width 0.5s;"></div>' +
        '</div>' +
        '<div style="width:66px;color:'+col+';font-size:0.74rem;font-weight:700;">' +
          (red_min > 0 ? '−'+red_min+' min' : '<1s') + '</div>' +
      '</div>';
    });
    html += '</div>';
    var base_min = Math.round(sens.baseP90 / 60 * 10) / 10;
    html += '<p style="color:#64748b;font-size:0.72rem;margin:10px 0 0;">Baseline P90 for <strong style="color:#b8c8d8;">' +
      ((_SS.strats.find(function(s){return s.id===sens.winner;})||{name:sens.winner}).name) +
      '</strong>: '+base_min+' min. Bars show how much of that P90 each stage is responsible for.</p>';
    return html;
  }

  /* Compact winner matrix across all 3 doc sizes — appended below the full-size sweep table */
  function _mcRenderSizeMatrix(all_size_results, N_VALS, sla_min) {
    var SCOL = {seq:'#64748b',stagger:'#6366f1',scriptfirst:'#0891b2',assembly:'#7c3aed',gpuburst:'#d97706',adaptive:'#4ade80'};
    var showSLA = sla_min > 0;
    var colSpan = showSLA ? 3 : 2;
    var html = '<div class="bm-section-title" style="margin-top:28px;margin-bottom:8px;">Winner Matrix — All Doc Sizes</div>' +
      '<div style="overflow-x:auto;">' +
      '<table class="bm-table" style="width:100%;font-size:0.78rem;">' +
      '<thead><tr><th style="color:#94a3b8;">N</th>' +
      all_size_results.map(function(sr){
        return '<th colspan="'+colSpan+'" style="text-align:center;color:#94a3b8;">'+sr.label+'</th>';
      }).join('') + '</tr>' +
      '<tr><th></th>' +
      all_size_results.map(function(){
        return '<th style="color:#94a3b8;">Strategy</th><th style="color:#94a3b8;">P50</th>' +
          (showSLA ? '<th style="color:#94a3b8;">SLA&nbsp;≤'+sla_min+'m</th>' : '');
      }).join('') +
      '</tr></thead><tbody>';

    N_VALS.forEach(function(n){
      html += '<tr><td style="color:#e2e8f0;font-weight:600;">'+n+'</td>';
      all_size_results.forEach(function(sr){
        var ar = null;
        for (var i=0;i<sr.all_res.length;i++){if(sr.all_res[i].n_jobs===n){ar=sr.all_res[i];break;}}
        if (!ar){html+='<td colspan="'+colSpan+'" style="color:#64748b;">—</td>';return;}
        var best = ar.results[0];
        var p50  = Math.round(best.agg.p50/60*10)/10;
        var seqRm = null;
        for (var rj=0;rj<ar.results.length;rj++){if(ar.results[rj].st.id==='seq'){seqRm=ar.results[rj];break;}}
        var slaCell = '';
        if (showSLA && best.agg.slaPct !== null) {
          var sp = best.agg.slaPct;
          var sc = sp>=90?'#22c55e':sp>=70?'#65a30d':sp>=50?'#d97706':'#ef4444';
          slaCell = '<td style="color:'+sc+';font-weight:600;">'+sp+'%</td>';
        } else if (showSLA) { slaCell = '<td style="color:#64748b;">—</td>'; }
        var seqAttr = seqRm ? ' data-strat-seq-p50="'+Math.round(seqRm.agg.p50)+'"' : '';
        html += '<td style="color:#e2e8f0;font-weight:600;cursor:pointer;text-decoration:underline dotted;text-underline-offset:3px;" data-strat-id="'+best.st.id+'" data-strat-n="'+n+'" data-strat-p50="'+Math.round(best.agg.p50)+'"'+seqAttr+' title="Click to learn about '+best.st.name+'">'+best.st.name+'</td>' +
                '<td style="color:#e2e8f0;">'+p50+' min</td>' + slaCell;
      });
      html += '</tr>';
    });
    html += '</tbody></table></div>';
    return html;
  }

  /* ── MC Debug renderer ──────────────────────────────────────────────── */
  function _mcRenderDebug(dbg, all_size_results, N_VALS) {
    var SS_LBL = {s2:'Research',s3:'Script',s3b:'Tagging',s31:'Emotion',s35:'Image Gen',s4:'TTS',s6:'Assembly'};
    var BL     = {s2:[2.1098,1.4822],s3:[3.8035,0.6314],s3b:[4.3783,0.5528],s31:[2.5462,1.4329],s35:[5.7555,1.2122],s4:[4.7705,1.5000],s6:[5.2050,1.1916]};

    function _sec(t) {
      return '<div style="color:#6366f1;font-weight:700;letter-spacing:.04em;font-size:.73rem;margin:14px 0 7px;border-bottom:1px solid rgba(99,102,241,.15);padding-bottom:3px;">'+t+'</div>';
    }
    function _min(s) { return (s !== undefined && s !== null) ? Math.round(s/60*10)/10+'m' : '—'; }

    /* Gather run dates from _bmHistory */
    var runDates = [];
    if (typeof _bmHistory !== 'undefined' && _bmHistory) {
      var _allR = [];
      ['scholarly','crime','video','manga','storyteller'].forEach(function(dep) {
        if (_bmHistory[dep] && _bmHistory[dep].trend) {
          _bmHistory[dep].trend.forEach(function(r){ _allR.push({dep:dep,id:r.id||'—',started:r.started||'—',total_s:r.total_s||null}); });
        }
      });
      _allR.sort(function(a,b){ return (b.started||'').localeCompare(a.started||''); });
      runDates = _allR.slice(0,20);
    }

    var s = dbg.settings;
    var html = '<details id="mc-debug-panel" style="margin-top:28px;background:rgba(0,0,0,.45);border:1px solid rgba(99,102,241,.22);border-radius:8px;font-family:monospace;">' +
      '<summary style="padding:11px 18px;cursor:pointer;color:#64748b;font-size:.74rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;list-style:none;display:flex;align-items:center;gap:10px;user-select:none;">' +
      '<span style="color:#6366f1;">⚙</span> MC DEBUG LOG&nbsp;<span style="color:#334155;font-weight:400;">(click to expand)</span></summary>' +
      '<div style="padding:14px 18px;font-size:.71rem;color:#94a3b8;">';

    /* 1 ── Data source */
    var srcCol = dbg.src.from_live ? '#22c55e' : '#f87171';
    html += _sec('1. DATA SOURCE') +
      '<div style="margin-bottom:10px;"><span style="color:'+srcCol+';font-weight:700;">'+(dbg.src.from_live?'LIVE DATA':'BASELINE FALLBACK')+'</span> &mdash; '+(dbg.src.from_live?dbg.src.n_runs+' completed pipeline runs':'277-run historical baseline (no live data available)')+'</div>';
    if (runDates.length) {
      html += '<table style="border-collapse:collapse;margin-bottom:12px;">' +
        '<tr style="color:#475569;"><td style="padding:2px 14px 2px 0;">Dept</td><td style="padding:2px 14px;">Run ID</td><td style="padding:2px 14px;">Started</td><td>Total</td></tr>';
      runDates.forEach(function(r) {
        var dur = r.total_s ? Math.round(r.total_s/60*10)/10+' min' : '—';
        html += '<tr style="color:#94a3b8;">' +
          '<td style="color:#64748b;padding:1px 14px 1px 0;">'+r.dep+'</td>' +
          '<td style="padding:1px 14px;">'+r.id+'</td>' +
          '<td style="padding:1px 14px;">'+r.started+'</td>' +
          '<td>'+dur+'</td></tr>';
      });
      html += '</table>';
    } else if (dbg.src.from_live) {
      html += '<div style="color:#d97706;margin-bottom:10px;">Warning: no run dates extractable from _bmHistory.</div>';
    }

    /* 2 ── Stage distribution parameters */
    html += _sec('2. STAGE DISTRIBUTION PARAMETERS');
    html += '<div style="overflow-x:auto;"><table style="border-collapse:collapse;min-width:680px;margin-bottom:14px;">' +
      '<tr style="color:#475569;border-bottom:1px solid rgba(255,255,255,.08);">' +
      '<td style="padding:3px 12px 3px 0;">Stage</td>' +
      '<td style="padding:3px 10px;">Samples</td>' +
      '<td style="padding:3px 10px;">μ (fit)</td><td style="padding:3px 10px;">σ (fit)</td>' +
      '<td style="padding:3px 10px;">Median</td><td style="padding:3px 10px;">CV%</td>' +
      '<td style="padding:3px 10px;color:#334155;">μ (base)</td><td style="padding:3px 10px;color:#334155;">σ (base)</td>' +
      '<td style="padding:3px 10px;color:#334155;">Med (base)</td>' +
      '<td style="padding:3px 10px;">Δ median</td><td style="padding:3px 10px;">Source</td></tr>';
    _SS.stages.forEach(function(st) {
      var p    = dbg.src.params[st.id]||[0,0];
      var bl   = BL[st.id]||[0,0];
      var ns   = (dbg.src.n_samples||{})[st.id]||0;
      var live = dbg.src.from_live && ns>=5;
      var med  = Math.round(Math.exp(p[0]));
      var cv   = Math.round(Math.sqrt(Math.exp(p[1]*p[1])-1)*100);
      var medB = Math.round(Math.exp(bl[0]));
      var dMed = med-medB;
      html += '<tr style="border-bottom:1px solid rgba(255,255,255,.04);color:#94a3b8;">' +
        '<td style="color:#e2e8f0;padding:2px 12px 2px 0;">'+SS_LBL[st.id]+'</td>' +
        '<td style="color:'+(ns>=10?'#22c55e':ns>=5?'#65a30d':'#ef4444')+';padding:2px 10px;text-align:right;">'+ns+'</td>' +
        '<td style="padding:2px 10px;">'+p[0].toFixed(4)+'</td><td style="padding:2px 10px;">'+p[1].toFixed(4)+'</td>' +
        '<td style="color:#e2e8f0;padding:2px 10px;">'+med+'s</td>' +
        '<td style="padding:2px 10px;">'+cv+'%'+(cv>180?'&nbsp;<span style="color:#f87171;">⚠ bimodal</span>':'')+'</td>' +
        '<td style="color:#475569;padding:2px 10px;">'+bl[0].toFixed(4)+'</td><td style="color:#475569;padding:2px 10px;">'+bl[1].toFixed(4)+'</td>' +
        '<td style="color:#475569;padding:2px 10px;">'+medB+'s</td>' +
        '<td style="color:'+(dMed>5?'#ef4444':dMed<-5?'#22c55e':'#64748b')+';padding:2px 10px;">'+(dMed>=0?'+':'')+dMed+'s</td>' +
        '<td style="padding:2px 10px;">'+(live?'<span style="color:#22c55e;font-weight:700;">LIVE</span>':'<span style="color:#d97706;font-weight:700;">FALLBACK</span>')+'</td></tr>';
    });
    html += '</table></div>';

    /* 3 ── Simulation settings */
    html += _sec('3. SIMULATION SETTINGS');
    html += '<table style="border-collapse:collapse;margin-bottom:14px;">';
    [['Simulations (n_sims)',s.n_sims],
     ['LHS sampling','YES — 500 base strata, doubled with antithetic variates'],
     ['Antithetic variates','YES'],
     ['Gaussian copula',s.useCorr?'<span style="color:#22c55e;">YES — inter-stage correlations active</span>':'<span style="color:#d97706;">NO — stages treated as independent</span>'],
     ['SLA target',s.sla_min?s.sla_min+' min ('+s.sla_min*60+'s)':'— (not set)'],
     ['Total wall-clock',dbg.totalMs+' ms for '+all_size_results.length+' sizes × '+N_VALS.length+' N values'],
    ].forEach(function(r){
      html+='<tr><td style="color:#64748b;padding:2px 12px 2px 0;white-space:nowrap;">'+r[0]+'</td><td>'+r[1]+'</td></tr>';
    });
    html += '</table>';

    /* 4 ── Batch timing */
    html += _sec('4. BATCH TIMING (ms per _mcBatch call)');
    html += '<div style="overflow-x:auto;"><table style="border-collapse:collapse;min-width:400px;margin-bottom:14px;">' +
      '<tr style="color:#475569;border-bottom:1px solid rgba(255,255,255,.08);">' +
      '<td style="padding:3px 12px 3px 0;">Size</td><td style="padding:3px 10px;">N</td>' +
      '<td style="padding:3px 10px;text-align:right;">ms</td><td style="padding:3px 10px;text-align:right;">worlds/sec</td></tr>';
    var szTotal={};
    all_size_results.forEach(function(sr){
      szTotal[sr.key]=0;
      sr.all_res.forEach(function(ar,idx){
        var ms=ar.tMs||0; szTotal[sr.key]+=ms;
        var wps=ms>0?Math.round(s.n_sims*1000/ms):'—';
        html+='<tr style="color:#94a3b8;border-bottom:1px solid rgba(255,255,255,.03);">' +
          '<td style="color:#64748b;padding:2px 12px 2px 0;">'+(idx===0?sr.label:'')+'</td>' +
          '<td style="padding:2px 10px;">'+ar.n_jobs+'</td>' +
          '<td style="padding:2px 10px;text-align:right;">'+ms+'</td>' +
          '<td style="color:#64748b;padding:2px 10px;text-align:right;">'+wps+'</td></tr>';
      });
      html+='<tr style="color:#475569;border-bottom:1px solid rgba(255,255,255,.1);">' +
        '<td colspan="2" style="padding:2px 12px 2px 0;font-style:italic;">'+sr.label+' subtotal</td>' +
        '<td style="padding:2px 10px;text-align:right;">'+szTotal[sr.key]+'</td><td></td></tr>';
    });
    html+='<tr style="color:#e2e8f0;">' +
      '<td colspan="2" style="padding:3px 12px 3px 0;font-weight:700;">Grand total</td>' +
      '<td style="padding:3px 10px;text-align:right;font-weight:700;">'+dbg.totalMs+'</td><td></td></tr>' +
      '</table></div>';

    /* 5 ── Full-size results: every strategy × every N */
    html += _sec('5. FULL-SIZE RESULTS — ALL STRATEGIES (convergence check)');
    var fullSr = null;
    for (var fi=0;fi<all_size_results.length;fi++){if(all_size_results[fi].key==='long'){fullSr=all_size_results[fi];break;}}
    if (fullSr) {
      html += '<div style="overflow-x:auto;"><table style="border-collapse:collapse;font-size:.67rem;white-space:nowrap;min-width:740px;margin-bottom:14px;">' +
        '<tr style="color:#475569;border-bottom:1px solid rgba(255,255,255,.08);">' +
        '<td style="padding:2px 10px 2px 0;">N</td><td style="padding:2px 10px;">Strategy</td>' +
        '<td style="padding:2px 10px;">P10</td><td style="padding:2px 10px;">P50</td><td style="padding:2px 10px;">P90</td>' +
        '<td style="padding:2px 10px;">CVaR90</td><td style="padding:2px 10px;">±CI P50</td>' +
        '<td style="padding:2px 10px;">Mean</td><td style="padding:2px 10px;">SLA%</td>' +
        '<td style="padding:2px 10px;">n</td><td style="padding:2px 10px;">Conv?</td></tr>';
      fullSr.all_res.forEach(function(ar){
        ar.results.forEach(function(r,ri){
          var a=r.agg;
          var conv=_mcConverged(r.samps);
          var sp=a.slaPct;
          html+='<tr style="'+(ri===0?'background:rgba(99,102,241,.07);':'')+
            'border-bottom:1px solid rgba(255,255,255,.03);color:#94a3b8;">' +
            '<td style="color:#e2e8f0;font-weight:600;padding:2px 10px 2px 0;">'+(ri===0?ar.n_jobs:'')+'</td>' +
            '<td style="color:'+(ri===0?'#e2e8f0':'#64748b')+';padding:2px 10px;">'+(ri===0?'★ ':'')+r.st.name+'</td>' +
            '<td style="padding:2px 10px;">'+_min(a.p10)+'</td>' +
            '<td style="color:#e2e8f0;font-weight:600;padding:2px 10px;">'+_min(a.p50)+'</td>' +
            '<td style="padding:2px 10px;">'+_min(a.p90)+'</td>' +
            '<td style="padding:2px 10px;">'+_min(a.cvar90)+'</td>' +
            '<td style="padding:2px 10px;">&plusmn;'+_min(a.ci95_p50)+'</td>' +
            '<td style="padding:2px 10px;">'+_min(a.mean)+'</td>' +
            '<td style="color:'+(sp>=80?'#22c55e':sp>=50?'#d97706':'#ef4444')+';padding:2px 10px;">'+(sp!==null&&sp!==undefined?sp+'%':'—')+'</td>' +
            '<td style="padding:2px 10px;">'+a.n+'</td>' +
            '<td style="color:'+(conv?'#22c55e':'#ef4444')+';font-weight:600;padding:2px 10px;">'+(conv?'✓ YES':'✗ NO')+'</td></tr>';
        });
      });
      html += '</table></div>';
    }

    /* 6 ── Cholesky matrix */
    if (s.useCorr && typeof _MC_CHOL !== 'undefined' && _MC_CHOL && _MC_CHOL.length) {
      html += _sec('6. CHOLESKY FACTOR L (inter-stage correlation decomposition)');
      var LIDS=_SS.stages.map(function(st){return SS_LBL[st.id];});
      html += '<div style="overflow-x:auto;margin-bottom:14px;"><table style="border-collapse:collapse;font-size:.67rem;">' +
        '<tr style="color:#475569;"><td style="padding:2px 8px;"></td>' +
        LIDS.map(function(l){return '<td style="padding:2px 8px;text-align:right;color:#475569;white-space:nowrap;">'+l+'</td>';}).join('') +
        '</tr>';
      _MC_CHOL.forEach(function(row,i){
        html += '<tr><td style="color:#64748b;padding:2px 8px;white-space:nowrap;font-style:italic;">'+LIDS[i]+'</td>';
        row.forEach(function(v){
          var av=Math.abs(v);
          var vc=av>0.5?'#e2e8f0':av>0.15?'#94a3b8':av>0.02?'#475569':'#1e293b';
          html+='<td style="color:'+vc+';padding:2px 8px;text-align:right;">'+(v!==0?v.toFixed(3):'—')+'</td>';
        });
        html += '</tr>';
      });
      html += '</table></div>';
    } else if (!s.useCorr) {
      html += _sec('6. CHOLESKY — SKIPPED (copula disabled)') +
        '<div style="color:#d97706;margin-bottom:14px;">Gaussian copula was OFF. Stages sampled independently (no inter-stage correlation).</div>';
    }

    /* 7 ── Win counts across all sizes × N */
    html += _sec('7. WIN COUNTS — ALL SIZES × N (worlds where each strategy finished fastest)');
    var stW={};
    _SS.strats.forEach(function(st){ stW[st.id]={}; all_size_results.forEach(function(sr){ stW[st.id][sr.key]=0; }); });
    all_size_results.forEach(function(sr){
      sr.all_res.forEach(function(ar){
        var ns=ar.results[0].samps.length;
        for(var wi=0;wi<ns;wi++){
          var bT=Infinity,bId=null;
          ar.results.forEach(function(r){if(r.samps[wi].total<bT){bT=r.samps[wi].total;bId=r.st.id;}});
          if(bId) stW[bId][sr.key]++;
        }
      });
    });
    var totW={};
    _SS.strats.forEach(function(st){ totW[st.id]=all_size_results.reduce(function(sum,sr){return sum+(stW[st.id][sr.key]||0);},0); });
    var maxW=Math.max.apply(null,_SS.strats.map(function(st){return totW[st.id];}));
    var grandWorlds=N_VALS.length*s.n_sims;
    html += '<div style="overflow-x:auto;"><table style="border-collapse:collapse;font-size:.7rem;min-width:440px;margin-bottom:16px;">' +
      '<tr style="color:#475569;border-bottom:1px solid rgba(255,255,255,.08);">' +
      '<td style="padding:3px 12px 3px 0;">Strategy</td>' +
      all_size_results.map(function(sr){return '<td style="padding:3px 10px;text-align:right;">'+sr.label+'</td>';}).join('') +
      '<td style="padding:3px 10px;text-align:right;">Total</td>' +
      '<td style="padding:3px 10px;text-align:right;">Win%</td></tr>';
    _SS.strats.forEach(function(st){
      var tot=totW[st.id]; var top=tot===maxW;
      var winPct=Math.round(tot/(grandWorlds*all_size_results.length)*100);
      html+='<tr style="border-bottom:1px solid rgba(255,255,255,.04);color:#94a3b8;'+(top?'background:rgba(99,102,241,.08);':'')+'">'+
        '<td style="color:'+(top?'#e2e8f0':'#64748b')+';padding:2px 12px 2px 0;">'+(top?'★ ':'')+st.name+'</td>'+
        all_size_results.map(function(sr){
          var w=stW[st.id][sr.key]||0;
          return '<td style="padding:2px 10px;text-align:right;">'+w+' <span style="color:#475569;">('+Math.round(w/grandWorlds*100)+'%)</span></td>';
        }).join('')+
        '<td style="color:'+(top?'#22c55e':'#64748b')+';font-weight:'+(top?'700':'400')+';padding:2px 10px;text-align:right;">'+tot+'</td>'+
        '<td style="color:'+(top?'#22c55e':'#64748b')+';padding:2px 10px;text-align:right;">'+winPct+'%</td></tr>';
    });
    html += '</table></div>';

    html += '</div></details>';
    return html;
  }

  /* ── Strategy explanation dialog ────────────────────────────────────── */
  var _MC_STRAT_DOCS = {
    seq: {
      name: 'Sequential',
      tagline: 'One job at a time — zero concurrency.',
      overview: 'Every job runs all 7 stages in order before the next job begins. Job 1 must fully complete (Research → Script → Tagging → Emotion → Image Gen → TTS → Assembly) before Job 2 starts Research.',
      pattern: [
        'Job 1 → [Research → Script → Tagging → Emotion → Image Gen → TTS → Assembly]',
        'Job 2 →                                                                        [Research → Script → Tagging → Emotion → Image Gen → TTS → Assembly]',
        'Job N →                                                                                                                                              …',
      ],
      resources: 'GPU, API, TTS, and CPU are used one at a time. No resource contention. No parallelism overhead.',
      wins: 'Only wins at N=1 (trivially the same as all strategies). At N≥2 it is always slower — it exists as the baseline comparison.',
      implement: [
        '1. Run the full pipeline for Job 1 end-to-end with <code>await</code>.',
        '2. When Job 1 finishes, start Job 2. Repeat for all N jobs.',
        '3. No queue or scheduler required. Total time = N × single-job time.',
      ],
    },
    stagger: {
      name: 'GPU-Aligned Stagger',
      tagline: 'Jobs offset by the GPU stage duration so the GPU never idles between jobs.',
      overview: 'Each job starts at a fixed time offset equal to the Image Generation duration scaled to doc size (≈249s × scale). Pre-GPU stages (Research+Script+Tagging+Emotion ≈ 79s) are much shorter than GPU, so by the time a job\'s GPU stage finishes, the next job\'s pre-GPU work is already done and waiting.',
      pattern: [
        'offset = Image Gen duration × doc scale   (≈249s for full, ≈62s for short)',
        '',
        'Job 1 starts at t=0:         [R][Sc][T][E]────────[GPU]──────────[TTS][Asm]',
        'Job 2 starts at t=offset:              [R][Sc][T][E][GPU]──────────[TTS][Asm]',
        'Job 3 starts at t=2×offset:                         [R][Sc][T][E][GPU]──────────[TTS][Asm]',
        '',
        'GPU always has the next job ready when it finishes the previous one.',
      ],
      resources: 'GPU runs continuously with no gaps. API calls overlap across jobs (limited by 5 slots). TTS runs in parallel across staggered jobs.',
      wins: 'Wins at medium N (4–10) for full-size docs. Ideal when Image Gen is the dominant bottleneck and pre-GPU stages finish reliably before the GPU offset expires.',
      implement: [
        '1. Measure or estimate your <code>image_gen_duration</code> for the target doc scale.',
        '2. Start Job j at wall-clock time <code>j × image_gen_duration</code>.',
        '3. Each job runs its own stages sequentially from its start time.',
        '4. No explicit coordination needed — the timing offset does all the work.',
        '5. Tip: if your research or script stages are slower than expected, reduce the offset slightly so GPU still has work queued.',
      ],
    },
    scriptfirst: {
      name: 'Script-First Batch',
      tagline: 'Pre-generate all scripts in parallel before any GPU work begins.',
      overview: 'Splits the pipeline into two groups. The PRE group (Research, Script, Tagging, Emotion) runs concurrently across all N jobs, limited only by API slot capacity (5 slots). Only after a job finishes its PRE group does its GPU/TTS/Assembly begin. This keeps the API layer saturated during Phase 1 and the GPU saturated in Phase 2.',
      pattern: [
        'Phase 1 — PRE (all jobs, parallel, API-limited):',
        '  Job 1: [Research → Script → Tagging → Emotion]',
        '  Job 2: [Research → Script → Tagging → Emotion]  ← concurrent',
        '  Job N: [Research → Script → Tagging → Emotion]  ← concurrent',
        '',
        'Phase 2 — POST (each job independently as Phase 1 finishes):',
        '  Job 1:                                           [Image Gen → TTS → Assembly]',
        '  Job 2:                                             [Image Gen → TTS → Assembly]',
        '  Job N:                                               …',
      ],
      resources: 'API is saturated in Phase 1 (up to 5 concurrent calls). GPU queues up as jobs finish Emotion — never waits for scripts since all scripts are pre-generated.',
      wins: 'Wins when script generation is slow or variable, and when N is large enough that Phase 1 overlap saves significant total time. Strong at N=6–14 for medium/long docs.',
      implement: [
        '1. Launch all N Research jobs concurrently (semaphore at 5 concurrent API calls).',
        '2. As each Research finishes, immediately chain Script → Tagging → Emotion (still within the 5-slot API semaphore).',
        '3. As each job\'s Emotion stage completes, submit it to the GPU queue.',
        '4. GPU processes Image Gen jobs one at a time (1 GPU slot).',
        '5. After each Image Gen: TTS (up to 3 concurrent) → Assembly (up to 2 concurrent).',
      ],
    },
    assembly: {
      name: 'Assembly Line',
      tagline: 'All jobs move through each stage together — stage-by-stage, not job-by-job.',
      overview: 'Processes all N jobs through Stage 1 (Research) in parallel, then all N through Stage 2 (Script), and so on. Each job\'s Stage S dependency is its own Stage S-1 completing — not all other jobs finishing Stage S. This creates a natural pipeline where different jobs are at different stages simultaneously.',
      pattern: [
        'Stage  Research:  [Job1][Job2][Job3]─────────────────────────────────────',
        'Stage  Script:              [Job1][Job2][Job3]────────────────────────────',
        'Stage  Tagging:                       [Job1][Job2][Job3]─────────────────',
        'Stage  Emotion:                                 [Job1][Job2][Job3]────────',
        'Stage  Image Gen:                                         [J1][J2][J3]───  ← GPU: serial',
        'Stage  TTS:                                                      [J1][J2][J3]',
        'Stage  Assembly:                                                        [J1][J2][J3]',
        '',
        'Note: GPU has 1 slot — Image Gen for all N jobs runs serially even within the assembly.',
      ],
      resources: 'API stages use all 5 slots. GPU is used one job at a time. TTS up to 3 concurrent. Assembly up to 2 concurrent. Stages flow in waves.',
      wins: 'Performs well at high N (12–20) where the pipeline effect compounds. Good when stages have similar durations. Reduces burst API load compared to Script-First.',
      implement: [
        '1. Build a task graph where task (job=j, stage=s) depends on task (job=j, stage=s-1).',
        '2. Use a pool executor: run tasks as soon as their dependency is met and a resource slot is free.',
        '3. Each stage\'s resource slot count: Research/Script=5, Tagging=8, Emotion=5, Image Gen=1, TTS=3, Assembly=2.',
        '4. The scheduler naturally creates the assembly-line wave pattern without any explicit phase logic.',
        '5. In Python: use <code>asyncio.Semaphore</code> per resource type + <code>asyncio.gather</code>.',
      ],
    },
    gpuburst: {
      name: 'GPU Burst',
      tagline: 'Hard barrier: wait for every job to finish pre-GPU, then blast all GPU work back-to-back.',
      overview: 'Runs pre-GPU stages (Research, Script, Tagging, Emotion) in parallel across all jobs. Then waits for a hard barrier — the moment when the LAST job finishes its Emotion stage. At that point, all GPU Image Gen jobs are queued simultaneously, running one-at-a-time on the single GPU. After each Image Gen, TTS → Assembly run in parallel.',
      pattern: [
        'Pre-GPU (parallel, API-limited):',
        '  Job 1: [R → Sc → T → E]─────────────────────────────────────┐',
        '  Job 2:   [R → Sc → T → E]───────────────────────────────────┤ BARRIER = max(all E finish)',
        '  Job N:     [R → Sc → T → E]─────────────────────────────────┘',
        '                                                                 ↓',
        'GPU phase (serial, 1 slot):                          [J1-GPU][J2-GPU][JN-GPU]',
        'Post-GPU (parallel per job):                                 [J1-TTS→Asm][J2-TTS→Asm]…',
        '',
        'GPU runs at maximum density — never interrupted by straggler jobs arriving late.',
      ],
      resources: 'API fully saturated during Phase 1. GPU runs non-stop from barrier to last Image Gen. TTS/Assembly overlap during GPU phase.',
      wins: 'Wins when GPU utilization is critical and pre-GPU stage durations are consistent (low variance). The barrier cost is worth it when jobs finish Emotion at similar times. Strong at N=3–10.',
      implement: [
        '1. Launch all N jobs\' pre-GPU stages (Research → Script → Tagging → Emotion) concurrently.',
        '2. Track completion of every job\'s Emotion stage.',
        '3. Wait for <code>barrier = max(all Emotion finish times)</code> — i.e., await all pre-GPU tasks.',
        '4. At the barrier, submit all Image Gen jobs to the GPU queue (they run serially, 1 GPU).',
        '5. After each Image Gen completes, immediately start that job\'s TTS and then Assembly.',
        '6. In Python: <code>await asyncio.gather(*[run_pre_gpu(j) for j in range(n)])</code>, then loop GPU.',
      ],
    },
    adaptive: {
      name: 'Adaptive Greedy',
      tagline: 'No barrier — feed the GPU in the order jobs become ready, minimising idle time.',
      overview: 'Runs pre-GPU stages (Research, Script, Tagging, Emotion) in parallel, identical to GPU Burst. The difference: instead of waiting for a global barrier, jobs are sorted by when their Emotion stage finishes (readiness order) and submitted to the GPU queue immediately. A job that finishes Emotion early jumps ahead of a slow-running job, keeping the GPU busy at all times.',
      pattern: [
        'Pre-GPU (parallel, API-limited):',
        '  Job 1: [R────→Sc→T→E]─────────────────────────────────────────────────────────',
        '  Job 2: [R→Sc→T→E]─────────────────────────────────────────────────────────────',
        '  Job 3:   [R──→Sc→T→E]──────────────────────────────────────────────────────────',
        '',
        'Sorted by Emotion finish: Job2 done first → Job3 → Job1',
        '',
        'GPU queue (sorted by readiness):           [J2-GPU][J3-GPU][J1-GPU]',
        'Post-GPU:                                          [J2-TTS→Asm][J3-TTS→Asm][J1-TTS→Asm]',
        '',
        'GPU never waits — the fastest job always goes first.',
      ],
      resources: 'Same resource usage as GPU Burst but with better GPU utilization when pre-GPU times vary. The priority queue ensures GPU idles for as little time as possible.',
      wins: 'The overall best strategy in most simulations. Wins at medium-high N (6–20) across all doc sizes. Especially dominant when Research or Script duration is highly variable (CV > 150%), because fast jobs don\'t get blocked by slow ones.',
      implement: [
        '1. Launch all N jobs\' pre-GPU stages concurrently (Research → Script → Tagging → Emotion).',
        '2. Use a <code>asyncio.Queue</code> or priority queue seeded as jobs finish Emotion.',
        '3. Sort the queue by <code>emotion_finish_time</code> ascending (earliest ready = highest priority).',
        '4. A single GPU worker task pops from the queue and runs Image Gen sequentially.',
        '5. After each Image Gen: TTS → Assembly run concurrently for that job.',
        '6. In Python:',
        '   <code>gpu_queue = asyncio.PriorityQueue()</code>',
        '   <code># Each pre-GPU task puts (emotion_finish_time, job_id) into gpu_queue on complete</code>',
        '   <code>async def gpu_worker(): while True: _, jid = await gpu_queue.get(); await image_gen(jid)</code>',
      ],
    },
  };

  function _mcBuildCmpTab(id, color) {
    var lr = window._mcLastResults;
    if (!lr) return '<div style="color:#64748b;padding:20px;font-size:.82rem;">Run a Monte Carlo sweep first to see comparison data.</div>';

    var winnerId = lr.winnerId;
    var cmpId    = (id === winnerId) ? 'seq' : winnerId;
    var thisDoc  = _MC_STRAT_DOCS[id]    || {name: id};
    var cmpDoc   = _MC_STRAT_DOCS[cmpId] || {name: cmpId};
    var isSweetspot = (id === winnerId);
    var cmpColor = isSweetspot ? '#64748b' : '#22c55e';
    var fullAr   = lr.all_size_results[0].all_res;

    var html = '';

    /* Summary banner */
    html += '<div style="background:'+(isSweetspot?'#ecfdf5':'#f8fafc')+
            ';border:1px solid '+(isSweetspot?'#6ee7b7':'#e2e8f0')+
            ';border-radius:8px;padding:11px 14px;margin-bottom:16px;font-size:.78rem;">';
    if (isSweetspot) {
      html += '<div style="color:#059669;font-weight:800;margin-bottom:3px;">★ This is the Monte Carlo sweetspot strategy</div>';
      html += '<div style="color:#334155;">Shown below: performance vs Sequential baseline across all N values (full-size docs).</div>';
    } else {
      html += '<div style="color:#334155;margin-bottom:3px;">'+
              '<span style="color:'+color+';font-weight:700;">'+thisDoc.name+'</span>'+
              ' vs sweetspot <span style="color:#22c55e;font-weight:700;">★ '+cmpDoc.name+'</span>'+
              ' — full-size documents</div>';
      html += '<div style="color:#64748b;">Gap = how much slower/faster this strategy is. Win% = fraction of 1,000 worlds where this strategy beat all others.</div>';
    }
    html += '</div>';

    /* Compute aggregate overall win count for summary line */
    var totalWin = 0, totalSims = 0;
    fullAr.forEach(function(ar){
      var ns = ar.results[0].samps.length;
      totalSims += ns;
      for (var i=0;i<ns;i++){
        var bestT=Infinity,bestId=null;
        ar.results.forEach(function(r){if(r.samps[i].total<bestT){bestT=r.samps[i].total;bestId=r.st.id;}});
        if(bestId===id) totalWin++;
      }
    });
    var overallPct = Math.round(totalWin/totalSims*100);
    var overallCol = overallPct>=40?'#22c55e':overallPct>=20?'#d97706':'#ef4444';
    html += '<div style="display:flex;gap:12px;margin-bottom:16px;">';
    html += '<div style="flex:1;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;text-align:center;">';
    html += '<div style="color:'+overallCol+';font-size:1.5rem;font-weight:800;line-height:1;">'+overallPct+'%</div>';
    html += '<div style="color:#64748b;font-size:.7rem;margin-top:2px;">Overall win rate<br>(full docs, all N)</div></div>';

    /* Compute cmp strategy overall win too */
    var cmpWin = 0;
    fullAr.forEach(function(ar){
      var ns = ar.results[0].samps.length;
      for (var i=0;i<ns;i++){
        var bestT=Infinity,bestId=null;
        ar.results.forEach(function(r){if(r.samps[i].total<bestT){bestT=r.samps[i].total;bestId=r.st.id;}});
        if(bestId===cmpId) cmpWin++;
      }
    });
    var cmpPct = Math.round(cmpWin/totalSims*100);
    html += '<div style="flex:1;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;text-align:center;">';
    html += '<div style="color:'+cmpColor+';font-size:1.5rem;font-weight:800;line-height:1;">'+cmpPct+'%</div>';
    html += '<div style="color:#64748b;font-size:.7rem;margin-top:2px;">'+(isSweetspot?'Sequential':'★ '+cmpDoc.name)+' win rate<br>(same conditions)</div></div>';
    html += '</div>';

    /* Per-N table */
    html += '<div style="overflow-x:auto;">';
    html += '<table style="width:100%;border-collapse:collapse;font-size:.77rem;">';
    html += '<thead><tr style="background:#f1f5f9;">';
    html += '<th style="color:#475569;padding:8px 10px;text-align:center;font-weight:700;border-radius:6px 0 0 0;">N</th>';
    html += '<th style="color:'+color+';padding:8px 10px;text-align:right;font-weight:700;">'+thisDoc.name+'<br><span style="font-weight:400;font-size:.68rem;">P50</span></th>';
    html += '<th style="color:'+cmpColor+';padding:8px 10px;text-align:right;font-weight:700;">'+(isSweetspot?'Sequential':'★ '+cmpDoc.name)+'<br><span style="font-weight:400;font-size:.68rem;">P50</span></th>';
    html += '<th style="color:#475569;padding:8px 10px;text-align:right;font-weight:700;">Gap</th>';
    html += '<th style="color:#475569;padding:8px 10px;text-align:right;font-weight:700;border-radius:0 6px 0 0;">Win%</th>';
    html += '</tr></thead><tbody>';

    fullAr.forEach(function(ar, ri) {
      var n    = ar.n_jobs;
      var thisR = ar.results.find(function(r){return r.st.id===id;});
      var cmpR  = ar.results.find(function(r){return r.st.id===cmpId;});
      if (!thisR||!cmpR) return;

      /* Per-N win rate */
      var wc = {}; _SS.strats.forEach(function(st){wc[st.id]=0;});
      var ns = thisR.samps.length;
      for (var i=0;i<ns;i++){
        var bestT=Infinity,bestId=null;
        ar.results.forEach(function(r){if(r.samps[i].total<bestT){bestT=r.samps[i].total;bestId=r.st.id;}});
        if(bestId) wc[bestId]++;
      }
      var winPct = Math.round(wc[id]/ns*100);
      var winCol = winPct>=40?'#22c55e':winPct>=20?'#d97706':'#ef4444';

      var thisM = Math.round(thisR.agg.p50/60*10)/10;
      var cmpM  = Math.round(cmpR.agg.p50/60*10)/10;
      var gapS  = thisR.agg.p50 - cmpR.agg.p50;
      var gapM  = Math.round(Math.abs(gapS)/60*10)/10;
      var faster = gapS < 0;
      var gapCol = faster ? '#22c55e' : (gapM<1 ? '#d97706' : '#ef4444');
      var rowBg  = ri%2===0 ? '#ffffff' : '#f8fafc';

      html += '<tr style="border-bottom:1px solid #f1f5f9;background:'+rowBg+';">';
      html += '<td style="padding:7px 10px;color:#334155;font-weight:700;text-align:center;">'+n+'</td>';
      html += '<td style="padding:7px 10px;color:'+color+';text-align:right;font-weight:600;">'+thisM+' min</td>';
      html += '<td style="padding:7px 10px;color:'+cmpColor+';text-align:right;">'+cmpM+' min</td>';
      html += '<td style="padding:7px 10px;color:'+gapCol+';text-align:right;font-weight:700;">'+(faster?'−':'+')+''+gapM+'m</td>';
      html += '<td style="padding:7px 10px;color:'+winCol+';text-align:right;font-weight:700;">'+winPct+'%</td>';
      html += '</tr>';
    });
    html += '</tbody></table></div>';
    return html;
  }

  window.mcShowStrategyDialog = function(id, prodData) {
    var doc = _MC_STRAT_DOCS[id];
    if (!doc) return;

    /* Create or reuse overlay */
    var ov = document.getElementById('mc-strat-dlg-ov');
    if (!ov) {
      ov = document.createElement('div');
      ov.id = 'mc-strat-dlg-ov';
      ov.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.7);display:flex;align-items:center;justify-content:center;padding:20px;backdrop-filter:blur(3px);';
      ov.addEventListener('click', function(e){ if(e.target===ov) ov.style.display='none'; });
      document.body.appendChild(ov);
    }

    var color = {seq:'#64748b',stagger:'#6366f1',scriptfirst:'#0891b2',assembly:'#7c3aed',gpuburst:'#d97706',adaptive:'#22c55e'}[id]||'#6366f1';

    var pLines = doc.pattern.map(function(l){
      return '<div style="color:'+(l===''?'transparent':'#94a3b8')+';line-height:1.6;white-space:pre;">'+(l||' ')+'</div>';
    }).join('');

    var implLines = doc.implement.map(function(l){
      return '<div style="color:#cbd5e1;line-height:1.7;margin-bottom:2px;">'+l+'</div>';
    }).join('');

    var implLinesBlk = doc.implement.map(function(l){
      return '<div style="color:#1e293b;line-height:1.75;margin-bottom:2px;">'+l+'</div>';
    }).join('');

    var pLinesBlk = doc.pattern.map(function(l){
      return '<div style="color:'+(l===''?'transparent':'#374151')+';line-height:1.6;white-space:pre;">'+(l||' ')+'</div>';
    }).join('');

    /* Build production impact section if caller supplied prodData */
    var prodImpactHtml = '';
    if (prodData && prodData.n && prodData.p50 && prodData.seqP50) {
      var pi_n   = prodData.n;
      var pi_p50 = prodData.p50;
      var pi_seq = prodData.seqP50;

      /* Fetch P75 from stored MC samps (sorted percentile) */
      var pi_p75 = null, pi_seq75 = null;
      var lr = window._mcLastResults;
      if (lr) {
        var lrFull = lr.all_size_results[0].all_res;
        for (var lai=0; lai<lrFull.length; lai++) {
          if (lrFull[lai].n_jobs === pi_n) {
            var lrRow = lrFull[lai];
            var lrThis = lrRow.results.find(function(r){return r.st.id===id;});
            var lrSeq  = lrRow.results.find(function(r){return r.st.id==='seq';});
            if (lrThis && lrThis.samps) {
              var st1 = lrThis.samps.map(function(s){return s.total;}).sort(function(a,b){return a-b;});
              pi_p75 = st1[Math.floor(st1.length*0.75)];
            }
            if (lrSeq && lrSeq.samps) {
              var st2 = lrSeq.samps.map(function(s){return s.total;}).sort(function(a,b){return a-b;});
              pi_seq75 = st2[Math.floor(st2.length*0.75)];
            }
            break;
          }
        }
      }

      /* Cards builder — avail = effective seconds/day */
      var _prodPane = function(p_new, p_seq, avail, subtitle) {
        var seqMinPerEp = Math.round(p_seq / pi_n / 60 * 10) / 10;
        var seqEpDay    = Math.floor(avail * pi_n / p_seq);
        var seqEpMonth  = seqEpDay * 29;
        var newMinBatch = Math.round(p_new / 60 * 10) / 10;
        var newBatchDay = Math.floor(avail / p_new);
        var newEpDay    = pi_n * newBatchDay;
        var newEpMonth  = newEpDay * 29;
        var pct         = Math.round((newEpDay / seqEpDay - 1) * 100);
        var gain        = newEpMonth - seqEpMonth;
        var bannerCol   = pct > 0 ? '#059669' : '#dc2626';
        return (subtitle ? '<div style="color:#64748b;font-size:.7rem;margin-bottom:10px;">'+subtitle+'</div>' : '') +
          '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px;">' +
            '<div style="background:#fef2f2;border:2px solid #fca5a5;border-radius:8px;padding:14px;">' +
              '<div style="color:#991b1b;font-weight:800;font-size:.7rem;letter-spacing:.06em;text-transform:uppercase;margin-bottom:10px;">Current · Sequential</div>' +
              '<div style="color:#7f1d1d;font-size:.82rem;line-height:2.15;">' +
                '<span style="display:block;"><b>①</b> Each episode: <b>'+seqMinPerEp+'</b> min</span>' +
                '<span style="display:block;"><b>②</b> Episodes/day: <b>'+seqEpDay.toLocaleString()+'</b></span>' +
                '<span style="display:block;"><b>③</b> Per month (×29): <b>'+seqEpMonth.toLocaleString()+'</b></span>' +
              '</div>' +
            '</div>' +
            '<div style="background:#f8fafc;border:2px solid '+color+';border-radius:8px;padding:14px;">' +
              '<div style="color:'+color+';font-weight:800;font-size:.7rem;letter-spacing:.06em;text-transform:uppercase;margin-bottom:10px;">'+doc.name+' · N='+pi_n+'</div>' +
              '<div style="color:#1e293b;font-size:.82rem;line-height:2.15;">' +
                '<span style="display:block;"><b>①</b> Batch of '+pi_n+' eps: <b>'+newMinBatch+'</b> min</span>' +
                '<span style="display:block;"><b>②</b> '+pi_n+' × '+newBatchDay+' batches = <b>'+newEpDay.toLocaleString()+'</b>/day</span>' +
                '<span style="display:block;"><b>③</b> Per month (×29): <b>'+newEpMonth.toLocaleString()+'</b></span>' +
              '</div>' +
            '</div>' +
          '</div>' +
          '<div style="background:'+bannerCol+';border-radius:8px;padding:11px 16px;display:flex;justify-content:space-between;align-items:center;">' +
            '<span style="color:#fff;font-weight:800;font-size:.95rem;">'+(pct>0?'+':'')+pct+'% throughput</span>' +
            '<span style="color:rgba(255,255,255,.85);font-size:.8rem;">'+(gain>0?'+':'')+gain.toLocaleString()+' eps/month vs sequential</span>' +
          '</div>';
      };

      var hasReal = !!(pi_p75 && pi_seq75);
      var toggleHtml = hasReal
        ? '<div style="display:flex;gap:6px;margin-bottom:14px;">' +
            '<button id="mc-prod-btn-opt" style="padding:5px 14px;border-radius:20px;border:2px solid '+color+';background:'+color+';color:#fff;font-size:.72rem;font-weight:700;cursor:pointer;">Optimistic · P50 · 100%</button>' +
            '<button id="mc-prod-btn-real" style="padding:5px 14px;border-radius:20px;border:2px solid #cbd5e1;background:#fff;color:#64748b;font-size:.72rem;font-weight:600;cursor:pointer;">Realistic · P75 · 75% uptime</button>' +
          '</div>' : '';

      prodImpactHtml =
        '<div style="margin-top:4px;">' +
        _mcDlgSection('Production Impact — N='+pi_n+' Concurrent Jobs', '#059669') +
        toggleHtml +
        '<div id="mc-prod-pane-opt">' + _prodPane(pi_p50, pi_seq, 86400, '') + '</div>' +
        (hasReal ? '<div id="mc-prod-pane-real" style="display:none;">' +
          _prodPane(pi_p75, pi_seq75, 86400*0.75,
            '⚠ P75 completion time · 18 effective hours/day (75% uptime) — a conservative but realistic ceiling') +
          '</div>' : '') +
        '</div>';
    }

    var tabBtnBase = 'padding:10px 20px;border:none;border-bottom:3px solid transparent;background:transparent;cursor:pointer;font-size:.8rem;font-weight:500;color:#64748b;margin-bottom:-2px;transition:color .15s;';
    var tabBtnActive = 'padding:10px 20px;border:none;border-bottom:3px solid '+color+';background:transparent;cursor:pointer;font-size:.8rem;font-weight:700;color:'+color+';margin-bottom:-2px;';

    ov.innerHTML =
      '<div style="background:#ffffff;border:2px solid '+color+';border-radius:12px;max-width:820px;width:100%;max-height:calc(90vh / var(--ui-zoom,1));overflow-y:auto;box-shadow:0 8px 48px rgba(0,0,0,.35);">' +

      /* Header */
      '<div style="background:'+color+';padding:16px 22px;display:flex;align-items:center;gap:14px;border-radius:10px 10px 0 0;">' +
        '<div style="flex:1;">' +
          '<div style="color:#fff;font-size:1.1rem;font-weight:800;letter-spacing:-.01em;">'+doc.name+'</div>' +
          '<div style="color:rgba(255,255,255,.82);font-size:.8rem;margin-top:3px;">'+doc.tagline+'</div>' +
        '</div>' +
        '<button id="mc-dlg-close-btn" style="background:rgba(255,255,255,.2);border:none;border-radius:6px;color:#fff;padding:5px 12px;cursor:pointer;font-size:.9rem;font-weight:700;">✕</button>' +
      '</div>' +

      /* Tab bar */
      '<div style="display:flex;background:#f8fafc;border-bottom:2px solid #e2e8f0;padding:0 18px;">' +
        '<button id="mc-dlg-tab-details" data-pane="details" style="'+tabBtnActive+'">Details</button>' +
        '<button id="mc-dlg-tab-cmp" data-pane="cmp" style="'+tabBtnBase+'">Comparison</button>' +
      '</div>' +

      /* Details pane */
      '<div id="mc-dlg-pane-details" style="padding:22px 24px;font-size:.83rem;">' +
        (prodImpactHtml ? prodImpactHtml + '<div style="height:20px;"></div>' : '') +
        _mcDlgSection('Overview', color) +
        '<p style="color:#1e293b;line-height:1.75;margin:0 0 18px;">'+doc.overview+'</p>' +
        _mcDlgSection('Execution Pattern', color) +
        '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:13px 15px;margin-bottom:18px;font-family:monospace;font-size:.72rem;overflow-x:auto;">'+pLinesBlk+'</div>' +
        _mcDlgSection('Resource Usage', color) +
        '<p style="color:#334155;line-height:1.75;margin:0 0 18px;">'+doc.resources+'</p>' +
        _mcDlgSection('When This Strategy Wins', color) +
        '<p style="color:#334155;line-height:1.75;margin:0 0 18px;">'+doc.wins+'</p>' +
        _mcDlgSection('How to Duplicate This Workflow', color) +
        '<div style="background:#f8fafc;border-left:4px solid '+color+';border-radius:0 6px 6px 0;padding:13px 16px;font-family:monospace;font-size:.76rem;">'+implLinesBlk+'</div>' +
      '</div>' +

      /* Comparison pane */
      '<div id="mc-dlg-pane-cmp" style="padding:22px 24px;font-size:.83rem;display:none;">' +
        _mcBuildCmpTab(id, color) +
      '</div>' +

    '</div>';

    var closeBtn = ov.querySelector('#mc-dlg-close-btn');
    if (closeBtn) closeBtn.addEventListener('click', function(){ ov.style.display='none'; });

    /* Tab switching */
    var tabBtns = ov.querySelectorAll('[data-pane]');
    tabBtns.forEach(function(btn) {
      btn.addEventListener('click', function() {
        var pane = btn.getAttribute('data-pane');
        tabBtns.forEach(function(b) {
          var active = b.getAttribute('data-pane') === pane;
          b.style.borderBottomColor  = active ? color : 'transparent';
          b.style.color              = active ? color : '#64748b';
          b.style.fontWeight         = active ? '700' : '500';
        });
        ov.querySelector('#mc-dlg-pane-details').style.display = (pane==='details') ? '' : 'none';
        ov.querySelector('#mc-dlg-pane-cmp').style.display     = (pane==='cmp')     ? '' : 'none';
      });
    });

    /* Optimistic / Realistic toggle */
    var btnOpt  = ov.querySelector('#mc-prod-btn-opt');
    var btnReal = ov.querySelector('#mc-prod-btn-real');
    if (btnOpt && btnReal) {
      var paneOpt  = ov.querySelector('#mc-prod-pane-opt');
      var paneReal = ov.querySelector('#mc-prod-pane-real');
      var _setProdMode = function(mode) {
        var isOpt = mode === 'opt';
        if (paneOpt)  paneOpt.style.display  = isOpt ? '' : 'none';
        if (paneReal) paneReal.style.display  = isOpt ? 'none' : '';
        btnOpt.style.background   = isOpt ? color : '#fff';
        btnOpt.style.color        = isOpt ? '#fff' : '#64748b';
        btnOpt.style.borderColor  = isOpt ? color : '#cbd5e1';
        btnReal.style.background  = isOpt ? '#fff' : color;
        btnReal.style.color       = isOpt ? '#64748b' : '#fff';
        btnReal.style.borderColor = isOpt ? '#cbd5e1' : color;
      };
      btnOpt.addEventListener('click',  function(){ _setProdMode('opt');  });
      btnReal.addEventListener('click', function(){ _setProdMode('real'); });
    }

    ov.style.display = 'flex';
  };

  function _mcDlgSection(title, color) {
    return '<div style="color:'+color+';font-weight:800;font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;margin-bottom:8px;border-bottom:2px solid '+color+';padding-bottom:4px;">'+title+'</div>';
  }

  /* ── UI entry point ─────────────────────────────────────────────────── */
  var _mcRunning = false;

  window.mcRun = function () {
    if (_mcRunning) return;

    /* Hardcoded optimal settings — no user inputs required */
    var N_VALS    = [2,3,4,5,6,7,8,9,10,12,14,16,18,20];
    var ALL_SIZES = [
      {key:'long',   scale:1.0,  label:'Full (standard)'},
      {key:'medium', scale:0.5,  label:'Medium'},
      {key:'short',  scale:0.25, label:'Short'},
    ];
    var n_sims   = 1000;  /* LHS+antithetic gives ±1–2% P50 error */
    var sla_min  = parseInt((document.getElementById('mc-sla')||{}).value) || 60;
    var useCorr  = (document.getElementById('mc-corr')||{checked:true}).checked;

    /* Fit distributions from the last 20 completed runs; fall back to 277-run baseline */
    var _mcPR  = _mcParamsFromHistory();
    var opts   = {corr:useCorr, sla_sec:sla_min*60, params:_mcPR.params};
    var _mcSrc = _mcPR.from_live
      ? 'last ' + _mcPR.n_runs + ' completed runs'
      : '277-run baseline (no live data)';

    var _dbg = {
      src: _mcPR,
      settings: {n_sims:n_sims, sla_min:sla_min, useCorr:useCorr},
      startMs: performance.now(),
      totalMs: 0
    };

    var outEl  = document.getElementById('mc-out');
    var barEl  = document.getElementById('mc-prog-bar');
    var msgEl  = document.getElementById('mc-prog-msg');
    var convEl = document.getElementById('mc-conv-status');
    var btn    = document.getElementById('mc-btn');
    if (!outEl) return;

    /* Reset viz */
    _nvStopLoop();
    var lbl=document.getElementById('mc-sweet-lbl');
    if (lbl){lbl.style.display='none';lbl.style.opacity='0';}
    var pnl=document.getElementById('mc-strat-pnl');
    var cw=document.getElementById('mc-cvs-wrap');
    if (pnl){pnl.style.flex='0 0 0';pnl.style.opacity='0';}
    if (cw){cw.style.flex='1 1 100%';}
    var vizWrap=document.getElementById('mc-viz-wrap');
    if (vizWrap) vizWrap.style.display='block';
    _nvInit(); _nvStartLoop();

    outEl.style.display='none'; outEl.innerHTML='';
    if (barEl) barEl.style.width='0%';
    if (convEl){ convEl.style.display='none'; convEl.textContent=''; }
    _mcRunning=true;
    if (btn) btn.disabled=true;
    ['sim-out','sim-cmp','sim-swp'].forEach(function(id){
      var e=document.getElementById(id); if(e) e.style.display='none';
    });

    var all_size_results=[], szi=0;
    var total_steps=ALL_SIZES.length*N_VALS.length;

    function _nextSize() {
      if (szi>=ALL_SIZES.length) {
        /* All sizes done — find overall winner across every size × N */
        if (barEl) barEl.style.width='100%';
        _dbg.totalMs = Math.round(performance.now() - _dbg.startMs);
        var winCounts={};
        _SS.strats.forEach(function(st){winCounts[st.id]=0;});
        all_size_results.forEach(function(sr){
          sr.all_res.forEach(function(ar){
            var n_s=ar.results[0].samps.length;
            for (var i=0;i<n_s;i++){
              var bestT=Infinity,bestId=null;
              ar.results.forEach(function(r){if(r.samps[i].total<bestT){bestT=r.samps[i].total;bestId=r.st.id;}});
              if(bestId) winCounts[bestId]++;
            }
          });
        });
        var overallWinner=_SS.strats.reduce(function(a,b){return winCounts[a.id]>=winCounts[b.id]?a:b;});
        /* Reveal using full-size mid-N as representative */
        var fullSr=all_size_results[0];
        var midRes=fullSr.all_res[Math.floor(fullSr.all_res.length/2)].results;
        var winnerResult=midRes.find(function(r){return r.st.id===overallWinner.id;})||midRes[0];
        var seqResult=midRes.find(function(r){return r.st.id==='seq';});
        var wr=seqResult?_mcWin(winnerResult.samps,seqResult.samps):50;
        if (msgEl) msgEl.textContent='';
        /* Store results so dialog Comparison tab can access them */
        window._mcLastResults = {
          all_size_results: all_size_results,
          N_VALS: N_VALS,
          winnerId: overallWinner.id,
          n_sims: n_sims
        };
        _nvReveal(overallWinner.id,{id:overallWinner.id,agg:winnerResult.agg,winVsSeq:wr,n_jobs:'2–20'});
        setTimeout(function(){
          outEl.style.display='block';
          outEl.innerHTML=_mcRenderSweep(fullSr.all_res,'long',n_sims,_mcSrc,sla_min)+
            _mcRenderSizeMatrix(all_size_results,N_VALS,sla_min)+
            _mcRenderDebug(_dbg,all_size_results,N_VALS);
          _mcRenderSweepChart(fullSr.all_res);
          _mcRunning=false; if(btn) btn.disabled=false;
        },5500);
        return;
      }

      var sz=ALL_SIZES[szi], all_res=[], ni=0;

      function _step() {
        if (ni>=N_VALS.length) {
          all_size_results.push({key:sz.key,label:sz.label,all_res:all_res});
          szi++; setTimeout(_nextSize,0); return;
        }
        var done_steps=szi*N_VALS.length+ni;
        var pct=Math.round(done_steps/total_steps*100);
        if (barEl) barEl.style.width=pct+'%';
        if (msgEl) msgEl.textContent=sz.label+' N='+N_VALS[ni]+' ('+pct+'%) — '+_mcSrc;
        _SS.strats.forEach(function(st,si){
          setTimeout(function(){ _nvFire(st.id,3+Math.floor(Math.random()*3)); },si*50);
        });
        setTimeout(function(){
          var _t0=performance.now();
          var res=_mcBatch(N_VALS[ni],sz.scale,n_sims,opts);
          all_res.push({n_jobs:N_VALS[ni],results:res,tMs:Math.round(performance.now()-_t0)});
          ni++; setTimeout(_step,0);
        },0);
      }
      setTimeout(_step,0);
    }
    setTimeout(_nextSize,60);
  };

  /* ── Auto-init ───────────────────────────────────────────────────────── */
  document.addEventListener('DOMContentLoaded', function () {
    // Auto-load if benchmark is already the active tab
    var panel = document.getElementById('panel-benchmark');
    if (panel && panel.classList.contains('active')) {
      bmLoadAll();
    }
    // Lazy-load on first click of sidebar link
    var link = document.querySelector('a[data-tab="benchmark"]');
    if (link) {
      link.addEventListener('click', function () {
        if (!_bmHistory) setTimeout(bmLoadAll, 80);
      });
    }
    /* Delegated click handler for strategy name cells (data-strat-id) */
    document.addEventListener('click', function(ev) {
      var el = ev.target;
      for (var i=0; i<8 && el && el.tagName; i++) {
        if (el.getAttribute && el.getAttribute('data-strat-id')) {
          var sid = el.getAttribute('data-strat-id');
          var pi_n   = parseInt(el.getAttribute('data-strat-n')    || '0');
          var pi_p50 = parseInt(el.getAttribute('data-strat-p50')  || '0');
          var pi_seq = parseInt(el.getAttribute('data-strat-seq-p50') || '0');
          var prodData = (pi_n && pi_p50 && pi_seq) ? {n:pi_n, p50:pi_p50, seqP50:pi_seq} : null;
          window.mcShowStrategyDialog(sid, prodData);
          return;
        }
        el = el.parentNode;
      }
    });
  });

})();
