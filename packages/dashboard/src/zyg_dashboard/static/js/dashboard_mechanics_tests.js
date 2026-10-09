// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

// ── Pipeline Workflow Test Runner ───────────────────────────────────────────
window.runPipelineTest = async function () {
  const btn    = document.getElementById('mechanics-workflow-test-btn');
  const status = document.getElementById('mechanics-workflow-status');
  const results = document.getElementById('mechanics-workflow-results');
  if (!btn) return;

  btn.disabled = true;
  btn.textContent = '⏳ Running…';
  status.style.display = 'block';
  status.textContent = 'Running pipeline health checks…';
  results.innerHTML = '';

  try {
    const r = await fetch('/api/pipeline/test', { method: 'POST',
      headers: { 'Content-Type': 'application/json',
                 'X-CSRF-Token': (document.cookie.match(/csrf_token=([^;]+)/)||[])[1] || '' }
    });
    const data = await r.json();
    const checks = data.checks || [];
    const pass = checks.filter(c => c.status === 'ok').length;
    const fail = checks.filter(c => c.status === 'fail').length;
    const warn = checks.filter(c => c.status === 'warn').length;
    status.innerHTML = `Completed in ${(data.elapsed_ms/1000).toFixed(1)}s — `
      + `<span style="color:#16a34a;font-weight:600;">${pass} OK</span>, `
      + `<span style="color:#d97706;font-weight:600;">${warn} warn</span>, `
      + `<span style="color:#dc2626;font-weight:600;">${fail} fail</span>`;

    results.innerHTML = checks.map(c => {
      const colours = { ok: '#f0fdf4', warn: '#fffbeb', fail: '#fef2f2' };
      const icons   = { ok: '✅', warn: '⚠️', fail: '❌' };
      const borders = { ok: '#16a34a', warn: '#d97706', fail: '#dc2626' };
      const bg = colours[c.status] || '#f8f9fa';
      const icon = icons[c.status] || '•';
      const border = borders[c.status] || '#e5e7eb';
      return `<div style="background:${bg};border:1px solid ${border};border-radius:8px;padding:10px 12px;">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
          <span style="font-size:14px;">${icon}</span>
          <strong style="font-size:12px;color:#111;">${c.name}</strong>
          <span style="font-size:10px;color:#888;margin-left:auto;">${c.elapsed_ms != null ? c.elapsed_ms+'ms' : ''}</span>
        </div>
        <div style="font-size:11px;color:#444;line-height:1.5;">${c.detail || ''}</div>
      </div>`;
    }).join('');
  } catch (e) {
    status.innerHTML = `<span style="color:#dc2626;">Request failed: ${e.message}</span>`;
  }

  btn.disabled = false;
  btn.textContent = '▶ Run Test';
};

/* ── Pipeline Smoke Test runner (dashboard) ───────────────────────────────── */
(function () {
  const _ds = { runId: null, pipeline: null, linesShown: 0, pollTimer: null };

  const CSRF = () => (document.cookie.match(/csrf_token=([^;]+)/) || [])[1] || '';

  window.runDashSmokeTest = function (pipeline) {
    // If already running show output and bail
    if (_ds.runId && _ds.status === 'running') { _dsShowOutput(); return; }

    _ds.runId      = null;
    _ds.pipeline   = pipeline;
    _ds.linesShown = 0;
    _ds.status     = 'running';

    const labels = { video: '🎬 Video Pipeline Smoke Test', documentary: '📚 Documentary Pipeline Smoke Test', intro: '🎞 Intro Pipeline Smoke Test' };
    _dsShowOutput();
    _dsSetTitle(labels[pipeline] || pipeline);
    _dsBadge('running', 'RUNNING', '#1d4ed8', '#fff');
    _dsMeta('Starting…');
    document.getElementById('smoke-dash-output').textContent = '';

    ['video','documentary','intro'].forEach(p => {
      const b = document.getElementById(`smoke-dash-btn-${p}`);
      if (b) { b.disabled = (p === pipeline); b.textContent = p === pipeline ? '⏳ Running…' : '▶ Run Test'; }
    });

    fetch('/api/smoke-test/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': CSRF() },
      body: JSON.stringify({ pipeline }),
    })
    .then(r => r.json())
    .then(d => {
      if (d.error) { _dsError(pipeline, d.error); return; }
      _ds.runId = d.run_id;
      _dsMeta(`Run ID: ${d.run_id}  |  PID: ${d.pid}`);
      _dsPoll();
    })
    .catch(e => _dsError(pipeline, String(e)));
  };

  function _dsPoll() {
    if (!_ds.runId) return;
    fetch(`/api/smoke-test/status/${_ds.runId}`)
      .then(r => r.json())
      .then(d => {
        _dsAppend(d.output || []);
        if (d.status !== 'running') {
          _ds.status = d.status;
          const ok = d.status === 'passed';
          _dsBadge(d.status, d.status.toUpperCase(), ok ? '#16a34a' : '#dc2626', '#fff');
          // Server emits Amsterdam-aware timestamps (with offset). Legacy
          // runs may still be naive UTC — append 'Z' only when no TZ marker
          // is present so both formats display the correct local clock time.
          const _finIso = d.finished ? (
            d.finished.endsWith('Z') || /[+\-]\d{2}:?\d{2}$/.test(d.finished)
              ? d.finished : d.finished + 'Z'
          ) : null;
          _dsMeta(`Run ID: ${d.run_id}  |  Exit: ${d.exit_code}  |  Finished: ${_finIso ? new Date(_finIso).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit',timeZone:'Europe/Amsterdam'}) : '?'}`);
          _dsBtnDone(_ds.pipeline, d.status);
        } else {
          _ds.pollTimer = setTimeout(_dsPoll, 1500);
        }
      })
      .catch(() => { _ds.pollTimer = setTimeout(_dsPoll, 3000); });
  }

  function _dsAppend(allLines) {
    const el = document.getElementById('smoke-dash-output');
    if (!el) return;
    const newLines = allLines.slice(_ds.linesShown);
    if (!newLines.length) return;
    _ds.linesShown = allLines.length;
    newLines.forEach(line => {
      const div = document.createElement('div');
      div.textContent = line;
      if      (line.includes('✅ PASS'))  div.style.color = '#16a34a';
      else if (line.includes('❌ FAIL'))  div.style.color = '#dc2626';
      else if (line.includes('⚠️'))       div.style.color = '#d97706';
      else if (line.startsWith('  ─'))    div.style.color = '#d1d5db';
      else if (line.includes('RESULTS'))  { div.style.color = '#1d4ed8'; div.style.fontWeight = '700'; }
      el.appendChild(div);
    });
    el.scrollTop = el.scrollHeight;
  }

  function _dsError(pipeline, msg) {
    _ds.status = 'error';
    _dsBadge('fail', 'ERROR', '#dc2626', '#fff');
    _dsAppend([`[error] ${msg}`]);
    _dsBtnDone(pipeline, 'failed');
  }

  function _dsBtnDone(pipeline, status) {
    ['video','documentary','intro'].forEach(p => {
      const b = document.getElementById(`smoke-dash-btn-${p}`);
      if (!b) return;
      b.disabled = false;
      if (p === pipeline) {
        b.textContent = status === 'passed' ? '✓ Passed' : '✗ Failed';
        b.style.background = status === 'passed' ? '#16a34a' : '#dc2626';
        setTimeout(() => { b.textContent = '▶ Run Test'; b.style.background = '#1d4ed8'; }, 8000);
      } else {
        b.textContent = '▶ Run Test';
      }
    });
  }

  function _dsShowOutput() { const w = document.getElementById('smoke-dash-output-wrap'); if (w) w.style.display = 'flex'; }
  function _dsSetTitle(t)  { const e = document.getElementById('smoke-dash-title');       if (e) e.textContent = t; }
  function _dsMeta(t)      { const e = document.getElementById('smoke-dash-meta');        if (e) e.textContent = t; }
  function _dsBadge(cls, text, bg, fg) {
    const e = document.getElementById('smoke-dash-badge');
    if (!e) return;
    e.textContent = text; e.style.background = bg; e.style.color = fg;
  }
})();
