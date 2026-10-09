// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* ── Live Tail logic ──────────────────────────────────────────────────────────── */
let _ltActive = false;
let _ltTab    = 'log';

function ltToggle() {
  _ltActive = !_ltActive;
  const panel = document.getElementById('lt-panel');
  if (_ltActive) {
    panel.classList.add('open');
    ltSwitchTab(_ltTab);
  } else {
    panel.classList.remove('open');
  }
  // The agent rail is docked to the panel; it must never outlive it on screen.
  try { _ltSyncAgentChrome(); } catch (e) { /* agent block not parsed yet */ }
}

function ltSwitchTab(tab) {
  _ltTab = tab;
  // Leaving the agent view: the skull's subtab row and pane are part of the
  // same single-pane stack, so a normal tab click has to close them or two
  // panes would render at once.
  if (tab !== 'agents') _ltAgentView = false;
  _ltSyncAgentChrome();
  document.querySelectorAll('.lt-tab').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tab && tab !== 'agents');
  });
  document.querySelectorAll('.lt-pane').forEach(p => {
    p.classList.toggle('active', p.id === 'lt-pane-' + tab);
  });
  if (tab === 'agents') { renderAgentPane(); return; }
  if (tab === 'debug') renderLiveTailDebug();
  if (tab === 'telem') renderLiveTailTelem();
  // Auto-scroll the newly active pane to the bottom (newest entries)
  const activePane = document.getElementById('lt-pane-' + tab);
  if (activePane) _ltScrollPaneBottom(activePane);
  if (tab === 'debug') _ltScrollPaneBottom(document.getElementById('lt-dbg-live-wrap'));
}

document.querySelectorAll('.lt-tab').forEach(b => {
  b.addEventListener('click', () => ltSwitchTab(b.dataset.tab));
});

document.getElementById('lt-close').addEventListener('click', () => {
  _ltActive = false;
  document.getElementById('lt-panel').classList.remove('open');
  try { _ltSyncAgentChrome(); } catch (e) { /* agent block not parsed yet */ }
});

document.getElementById('lt-clear').addEventListener('click', () => {
  if (_ltTab === 'debug') {
    // Tell the backend to set a watermark so old errors don't repopulate on next poll
    fetch(FLASK_BASE + '/api/kanban/clear_errors', { method: 'POST' }).catch(() => {});
    DBG.errors = [];
    DBG.events = [];
    renderLiveTailDebug();
  } else if (_ltTab === 'log') {
    const el = document.getElementById('lt-pane-log');
    if (el) el.innerHTML = '';
    // Reset state trackers so next poll isn't suppressed by dedup guards
    _ltLastStage  = null;
    _ltLastStatus = null;
    _ltLastCards  = {};
    _ltLastJobId  = null;
    _ltPipelineStartedAt = null;
    _ltPipelineEndedAt   = null;
  } else if (_ltTab === 'telem') {
    // Telem is live-only data — just re-render a fresh fetch on next poll
    const el = document.getElementById('lt-pane-telem');
    if (el) el.innerHTML = '';
  } else if (_ltTab === 'agents') {
    // The agent tail is a server-side history, not a browser buffer: clearing
    // it here would only hide what is still true. Drop the cached lines and
    // let the next poll re-fetch.
    _ltAgentLines = {};
    renderAgentPane();
  }
});

/* ── Pipeline log helpers ──────────────────────────────────────────────────── */
let _ltLastStage = null;
let _ltLastStatus = null;
let _ltLastCards = {};
let _ltLastJobId = null;
let _ltPipelineStartedAt = null;   // ISO timestamp from pipeline.started
let _ltPipelineEndedAt  = null;   // latch: pipeline finished (ms, or -1 = time unknown).
                                  // The clock itself is no longer derived from
                                  // this — the server ships the runtime — it just
                                  // keeps the 30-min auto-clear from re-arming.
// Server-computed runtime (pipeline_runtime.py). Authoritative: it excludes the
// dead gaps a crashed-and-resumed run leaves behind and freezes at the last
// recorded activity, so a parked run reports a runtime instead of accumulating.
let _ltRuntimeSecs     = null;
let _ltRuntimeWallSecs = null;
let _ltRuntimeRunning  = false;
let _ltRuntimeGapSecs  = 0;      // total time excluded from the runtime
let _ltRuntimeGaps     = [];     // [{from,to,seconds,reason}] — why wall > runtime
let _ltLoggedGaps      = {};     // freeze → already written to the log pane

/* Statuses that mean a worker is doing work RIGHT NOW. Everything else is at
   rest — a review gate (awaiting_review), a job stopped by a GUI restart, a
   rejected run — and its clock must not tick. The old code only knew four
   terminal statuses and let every other resting state count against
   Date.now(): a creature parked at the sheet-review gate read 20h11m for a
   4h00m run (measured 2026-08-26). */
const LT_RUNNING_STATUSES = ['running', 'in_progress', 'active', 'started', 'busy'];
/* Finished for good — these (and only these) start the 30-min auto-clear. A
   review gate is at rest but NOT finished: clearing the panel out from under
   the operator while they are deciding would throw away the run's context. */
const LT_TERMINAL_STATUSES = ['completed', 'complete', 'done', 'error', 'failed',
                              'stopped', 'cancelled', 'canceled', 'rejected',
                              'declined', 'archived', 'skipped'];

function _ltIsRunning(status) {
  return LT_RUNNING_STATUSES.indexOf(String(status || '').toLowerCase()) !== -1;
}
function _ltIsTerminal(status) {
  return LT_TERMINAL_STATUSES.indexOf(String(status || '').toLowerCase()) !== -1;
}
/* Server emits Europe/Amsterdam ISO with an offset; older runs may be naive
   UTC without a 'Z'. Returns epoch ms, or NaN. */
function _ltStartMs(iso) {
  if (!iso) return NaN;
  const hasTz = iso.endsWith('Z') || /[+\-]\d{2}:?\d{2}$/.test(iso);
  return new Date(hasTz ? iso : iso + 'Z').getTime();
}
function _ltFmtRuntime(sec) {
  const t  = Math.max(0, Math.floor(sec));
  const hh = Math.floor(t / 3600), mm = Math.floor((t % 3600) / 60), ss = t % 60;
  return hh > 0
    ? `${hh}h ${String(mm).padStart(2, '0')}m ${String(ss).padStart(2, '0')}s`
    : `${mm}m ${String(ss).padStart(2, '0')}s`;
}
let _ltAutoClearTimer   = null;   // setTimeout handle for 30-min post-completion clear
let _ltClearedJobId     = null;   // job ID suppressed after auto-clear (avoid re-populating stale data)

let _ltLastLogDate = '';

function _ltPipelineLog(msg, cls = 'info') {
  const el = document.getElementById('lt-pane-log');
  if (!el) return;
  const now  = new Date();
  const date = now.toISOString().slice(0, 10);           // YYYY-MM-DD
  const time = now.toTimeString().slice(0, 8);           // HH:MM:SS
  // Inject date header when day changes
  if (date !== _ltLastLogDate) {
    _ltLastLogDate = date;
    const sep = document.createElement('div');
    sep.className = 'lt-line';
    sep.style.cssText = 'color:#6b7280;font-weight:700;margin-top:6px;margin-bottom:2px;font-size:10px;letter-spacing:0.05em;';
    sep.textContent = date;
    el.appendChild(sep);
  }
  const line = document.createElement('div');
  line.className = 'lt-line ' + cls;
  line.textContent = '[  ' + time + '  ]  ' + msg;
  el.appendChild(line);
  if (el.children.length > 400) el.removeChild(el.firstChild);
  _ltScrollPaneBottom(el);
  const stEl = document.getElementById('lt-status-text');
  if (stEl) stEl.textContent = 'Last: ' + time;
}

/* Clear all Live Tail state — fires automatically 30 min after pipeline completion */
function _ltAutoClear() {
  _ltAutoClearTimer = null;
  _ltClearedJobId   = _ltLastJobId;  // suppress stale API data for this run
  DBG.errors = []; DBG.events = [];
  _ltPipelineStartedAt = null; _ltPipelineEndedAt = null;
  _ltRuntimeSecs = null; _ltRuntimeWallSecs = null; _ltRuntimeRunning = false;
  _ltRuntimeGapSecs = 0; _ltRuntimeGaps = []; _ltLoggedGaps = {};
  _ltLastStatus = null; _ltLastStage = null; _ltLastCards = {}; _ltLastJobId = null;
  const logEl = document.getElementById('lt-pane-log');
  const dbgEl = document.getElementById('lt-pane-debug');
  if (logEl) logEl.innerHTML = '';
  if (dbgEl) dbgEl.innerHTML = '';
  renderLiveTailTelem();
  renderLiveTailDebug();
}

/* Called by pollPipeline() when data arrives — log meaningful changes */
function _ltOnPipelineData(data) {
  const p = data.pipeline;
  if (!p) {
    if (_ltLastStatus !== 'idle') { _ltPipelineLog('No active pipeline — IDLE', 'info'); }
    _ltLastStatus = 'idle'; _ltLastStage = null; _ltLastCards = {}; _ltLastJobId = null; _ltPipelineStartedAt = null; _ltPipelineEndedAt = null;
    _ltRuntimeSecs = null; _ltRuntimeWallSecs = null; _ltRuntimeRunning = false;
    _ltRuntimeGapSecs = 0; _ltRuntimeGaps = []; return;
  }
  const jobId = p.job_id || null;
  // Skip stale data from an auto-cleared run; lift suppression when a genuinely new job arrives
  if (jobId && jobId === _ltClearedJobId) return;
  if (jobId && _ltClearedJobId && jobId !== _ltClearedJobId) _ltClearedJobId = null;
  // Reset card tracking when a new job starts
  if (jobId && jobId !== _ltLastJobId) {
    if (_ltAutoClearTimer) { clearTimeout(_ltAutoClearTimer); _ltAutoClearTimer = null; }
    _ltLastCards = {};
    _ltLastJobId = jobId;
    _ltPipelineStartedAt = p.started || null;
    _ltPipelineEndedAt   = null;   // new job — reset freeze
  }
  if (!_ltPipelineStartedAt && p.started) _ltPipelineStartedAt = p.started;
  if (!p.started) _ltPipelineStartedAt = null;
  // Authoritative runtime straight from the server (see pipeline_runtime.py).
  _ltRuntimeSecs     = (typeof p.runtime_seconds === 'number') ? p.runtime_seconds : null;
  _ltRuntimeWallSecs = (typeof p.runtime_wall_seconds === 'number') ? p.runtime_wall_seconds : null;
  _ltRuntimeRunning  = (typeof p.runtime_running === 'boolean') ? p.runtime_running : _ltIsRunning(p.status);
  _ltRuntimeGapSecs  = (typeof p.runtime_gap_seconds === 'number') ? p.runtime_gap_seconds : 0;
  _ltRuntimeGaps     = Array.isArray(p.runtime_gaps) ? p.runtime_gaps : [];
  // Log each freeze once, when it first shows up, so the reason the wall clock
  // outruns the runtime is in the tail and not only in the widget.
  _ltRuntimeGaps.forEach(g => {
    const key = (p.job_id || '') + '|' + g.from + '|' + g.to;
    if (_ltLoggedGaps[key]) return;
    _ltLoggedGaps[key] = 1;
    _ltPipelineLog(`⏸ clock paused ${_ltFmtRuntime(g.seconds)} — ${g.reason}`, 'warn');
  });
  if (p.status !== _ltLastStatus) {
    _ltPipelineLog(`Pipeline status → ${p.status}`, _ltIsRunning(p.status) ? 'ok' : 'warn');
    // The gate states used to log as a bare status word, which reads like a
    // failure and names no action. Say what is waiting and on whom (2026-08-26).
    if (p.review_pending) {
      _ltPipelineLog('⏸ WAITING ON YOU — approve or reject the sheet in the banner '
                     + 'above the board (or the Zero card on :5000)', 'warn');
    }
    // Arm the post-run auto-clear once, when the pipeline finishes for good.
    if (_ltIsTerminal(p.status) && !_ltPipelineEndedAt) {
      if (p.ended) {
        const _endStr = p.ended.endsWith('Z') ? p.ended : p.ended + 'Z';
        _ltPipelineEndedAt = new Date(_endStr).getTime();
      } else {
        _ltPipelineEndedAt = -1;  // ended but no precise timestamp — use sentinel to avoid accumulation
      }
      // Auto-clear all Live Tail data 30 min after completion (cancelled if new job starts)
      if (_ltAutoClearTimer) clearTimeout(_ltAutoClearTimer);
      _ltAutoClearTimer = setTimeout(_ltAutoClear, 30 * 60 * 1000);
    }
    _ltLastStatus = p.status;
  }
  if (p.current_stage && p.current_stage !== _ltLastStage) {
    _ltPipelineLog(`Stage → ${p.current_stage}`, 'stage');
    _ltLastStage = p.current_stage;
  }
  // Only log card changes while a pipeline is actively running
  if (p.status === 'running') {
    const cards = data.cards || {};
    Object.entries(cards).forEach(([name, st]) => {
      if (st !== _ltLastCards[name]) {
        if (st === 'running') _ltPipelineLog(`  ▶ ${name}`, 'ok');
        if (st === 'error')   _ltPipelineLog(`  ✗ ${name}`, 'err');
        if (st === 'done')    _ltPipelineLog(`  ✓ ${name}`, 'ok');
        _ltLastCards[name] = st;
      }
    });
  }
}

/* ── Telemetry pane renderer ────────────────────────────────────────────────── */
function renderLiveTailTelem() {
  const el = document.getElementById('lt-pane-telem');
  if (!el || _ltTab !== 'telem') return;
  const t = TELEM;

  // ── Pipeline runtime ──────────────────────────────────────────────────────
  // The number comes from the SERVER (pipeline_runtime.py), which owns every
  // timestamp the run produced. It used to be computed here as
  // `Date.now() - pipeline.started`, frozen only on four hard-coded terminal
  // statuses, so any other resting state accumulated forever — a creature
  // parked at the sheet-review gate read 20h11m for a 4h00m run — and a run
  // that crashed and was resumed hours later counted the dead gap as runtime.
  // A page cannot fix that on its own: it only sees what happened while it was
  // open, so a freshly loaded page would freeze a long-parked job at "now".
  let runtimeHtml = '';
  const _startMs   = _ltStartMs(_ltPipelineStartedAt);
  const _haveStart = !isNaN(_startMs);
  if (_ltRuntimeSecs != null || _haveStart) {
    const _isRunning  = _ltRuntimeRunning || _ltIsRunning(_ltLastStatus);
    const _isTerminal = _ltIsTerminal(_ltLastStatus);
    const statusColor = _isRunning ? '#3fb950' : _isTerminal ? '#58a6ff' : '#d29922';
    const statusDot   = _isRunning
      ? '<span style="animation:pulse 1.2s infinite;display:inline-block;">●</span>'
      : '●';

    let secs = _ltRuntimeSecs;
    if (secs == null) {
      // Legacy payload (server not restarted yet). Only a genuinely running
      // pipeline may be timed against the wall clock here; anything at rest
      // shows a dash rather than a number that grows on its own.
      secs = (_isRunning && _haveStart) ? (Date.now() - _startMs) / 1000 : null;
    }

    // A resting pipeline is frozen, and says so instead of pretending to tick.
    const restLabel = !_isRunning && !_isTerminal ? ' · clock paused' : '';
    let subLine = _haveStart
      ? `Started ${new Date(_startMs).toLocaleTimeString()}` : 'Start time unknown';
    // Wall span vs active runtime: when they differ, say so and say why. The
    // difference is time no worker was running — an operator gate, a re-run
    // between attempts, an interrupted worker — never silently absorbed.
    if (_ltRuntimeWallSecs != null && secs != null && (_ltRuntimeWallSecs - secs) > 60) {
      subLine += ` · ${_ltFmtRuntime(_ltRuntimeWallSecs)} wall`;
    }
    subLine += restLabel;
    let freezeHtml = '';
    if (_ltRuntimeGapSecs > 0) {
      const reasons = {};
      _ltRuntimeGaps.forEach(g => { reasons[g.reason] = (reasons[g.reason] || 0) + g.seconds; });
      const detail = Object.keys(reasons)
        .map(r => `${_ltFmtRuntime(reasons[r])} — ${r}`).join('\n');
      const n = _ltRuntimeGaps.length;
      freezeHtml = `
        <div title="${detail.replace(/"/g, '&quot;')}" style="margin-top:5px;padding:4px 6px;background:#1c1408;border:1px solid #3d2d0c;border-radius:4px;color:#d29922;font-size:10px;">
          ⏸ ${_ltFmtRuntime(_ltRuntimeGapSecs)} excluded — ${n} freeze${n === 1 ? '' : 's'}
          <span style="color:#8b6d1f;">(${Object.keys(reasons)[0]}${Object.keys(reasons).length > 1 ? ', …' : ''})</span>
        </div>`;
    }

    runtimeHtml = `
      <div style="margin-bottom:8px;padding:7px 10px;background:#0d1117;border:1px solid #21262d;border-radius:6px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
          <span style="color:#58a6ff;font-size:11px;font-weight:600;">⏱ Pipeline Runtime</span>
          <span style="color:${statusColor};font-size:10px;">${statusDot} ${(_ltLastStatus || 'idle').toUpperCase()}</span>
        </div>
        <div style="font-size:${secs == null ? 14 : 20}px;font-weight:${secs == null ? 600 : 700};color:${secs == null ? '#8b949e' : '#e6edf3'};letter-spacing:1px;font-family:monospace;">${secs == null ? '—' : _ltFmtRuntime(secs)}</div>
        <div style="color:#484f58;font-size:10px;margin-top:3px;">${subLine}</div>
        ${freezeHtml}
      </div>`;
  } else {
    runtimeHtml = `
      <div style="margin-bottom:8px;padding:7px 10px;background:#0d1117;border:1px solid #21262d;border-radius:6px;">
        <span style="color:#484f58;font-size:11px;">⏱ Pipeline Runtime — No active pipeline</span>
      </div>`;
  }

  // ── Who is on the hardware ────────────────────────────────────────────────
  // The rings above say the GPU is at 83%; they never said WHY. When a Claude
  // agent session is holding it — a render, a workflow, a smoke test — the
  // load belongs to a name, and this row is that name.
  let agentHtml = '';
  const _ag = _ltAgentSummary;
  if (_ag && (_ag.count || _ag.orphans)) {
    const rows = _ltAgents
      .filter(s => s.active || s.orphan)
      .slice(0, 6)
      .map(s => `
        <div style="display:flex;justify-content:space-between;gap:8px;font-size:10px;
                    padding:1px 0;color:${s.active ? '#c9d1d9' : '#d29922'};">
          <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer;"
                onclick="ltSelectAgent('${_ltEsc(s.id)}')"
                title="Open this session's live tail">${s.active ? '●' : '⚠'} ${_ltEsc(s.name || s.short)}</span>
          <span style="color:#8b949e;white-space:nowrap;">${_ltAgentFmtLoad(s) || 'idle'}</span>
        </div>`).join('');
    const other = Math.max(0, Math.round((_ag.gpu.other_mb || 0)));
    agentHtml = `
      <div style="margin-bottom:8px;padding:7px 10px;background:#0d1117;border:1px solid #21262d;border-radius:6px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
          <span style="color:#b98fe0;font-size:11px;font-weight:600;">&#128369; Agent Sessions</span>
          <span style="color:${_ag.active ? '#3fb950' : '#484f58'};font-size:10px;">
            ${_ag.active} of ${_ag.count} on the hardware${_ag.orphans ? ` · ${_ag.orphans} orphaned` : ''}</span>
        </div>
        ${rows || '<div style="color:#484f58;font-size:10px;">none currently using CPU or VRAM</div>'}
        <div style="color:#484f58;font-size:10px;margin-top:4px;">
          agents on ${(_ag.cpu / 100).toFixed(1)} of ${_ltCpuCount} cores ·
          holding ${Math.round(_ag.vram)} MiB VRAM${other ? ` · ${other} MiB held by non-agent processes` : ''}
        </div>
      </div>`;
  }

  el.innerHTML = runtimeHtml + agentHtml + `
    <table style="width:100%;border-collapse:collapse;font-size:11px;">
      <thead><tr style="color:#484f58;border-bottom:1px solid #21262d;">
        <th style="text-align:left;padding:3px 8px;">Component</th>
        <th style="text-align:right;padding:3px 8px;">Usage %</th>
        <th style="text-align:right;padding:3px 8px;">Detail 1</th>
        <th style="text-align:right;padding:3px 8px;">Detail 2</th>
      </tr></thead>
      <tbody>
        ${t.map(item => `
          <tr style="border-bottom:1px solid #161b22;">
            <td style="padding:4px 8px;color:#58a6ff;">${item.name}</td>
            <td style="padding:4px 8px;text-align:right;color:${item.val>80?'#f85149':item.val>60?'#d29922':'#3fb950'};">${item.val.toFixed(1)}%</td>
            <td style="padding:4px 8px;text-align:right;color:#c9d1d9;">${item.row1()}</td>
            <td style="padding:4px 8px;text-align:right;color:#8b949e;">${item.row2()}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
    <div style="color:#484f58;font-size:10px;margin-top:6px;">
      Source: ${DBG.telemetryOk ? '<span style="color:#3fb950">Live — ' + DBG.telemetryAt + '</span>' : '<span style="color:#d29922">Fallback (API unreachable)</span>'}
    </div>
  `;
}

/* ═══════════════════════════════════════════════════════════════════════════
   AGENT SESSIONS — the skull badge, its subtabs and their live tails
   ─────────────────────────────────────────────────────────────────────────
   2026-08-30. The Live Tail knew everything about a pipeline run and nothing
   about the other thing that drives this box: a Claude Code session launching
   a workflow, a render or a smoke test. Measured while writing this, ComfyUI
   sat at 55% CPU / 530 MiB VRAM having been started by hand from one session,
   and `comfyui.service` was in `failed` — the board reported an idle pipeline.

   Data comes from THIS server (:8899, same-origin) at /kanban/api/agents; the
   attribution is server-side (agent_activity.py) by inherited environment, so
   a detached `nohup` render is still named. Everything here only renders.
   ═════════════════════════════════════════════════════════════════════════ */
let _ltAgentView   = false;   // skull toggled on → subtab row + agent pane
let _ltAgentSel    = null;    // selected session id
let _ltAgents      = [];      // last snapshot's sessions
let _ltAgentSeq    = 0;       // highest event seq already written to the log
let _ltAgentLines  = {};      // sid → last fetched tail lines
let _ltAgentTailAt = 0;       // ms of the last tail fetch (throttle)
let _ltAgentOk     = null;    // null = never answered, false = endpoint down
let _ltAgentPrimed = false;   // first poll adopts the seq watermark, never replays it
let _ltAgentSummary = null;   // last snapshot's roll-up, shown in the Telemetry pane
let _ltCpuCount    = 1;       // cores on this box, from the server
const LT_AGENT_BASE = location.origin;   // same-origin: no CORS, no token

/* CPU IS SHOWN IN CORES. The server's `cpu_pct` is psutil's per-process scale
   — "percent of ONE core" — so three busy cores read 300% and a hard-working
   session on this 24-core box reads in the thousands, sitting right next to a
   whole-machine CPU ring that also reads in the thousands. The two were read as
   the same number (2026-08-30). The measurement was correct; the unit was not.
   `cpu_cores` comes from the server; the division is a fallback for a payload
   from an older kanban_server. */
function _ltCores(s) {
  const c = (typeof s.cpu_cores === 'number') ? s.cpu_cores : (s.cpu_pct || 0) / 100;
  if (c < 0.05) return '';
  if (c < 1)    return c.toFixed(2) + ' cores';
  return c.toFixed(1) + ' core' + (c >= 0.95 && c < 1.05 ? '' : 's');
}

function _ltAgentFmtLoad(s) {
  const bits = [];
  const cores = _ltCores(s);
  if (cores) bits.push(cores);
  if ((s.vram_mb || 0) >= 1) bits.push(Math.round(s.vram_mb) + 'M vram');
  return bits.join(' · ');
}

/* Show/hide the rail and keep the skull's pressed state honest. The rail is
   only ever visible while the live tail itself is open — it is docked to the
   panel, so on its own it would float against nothing. */
function _ltSyncAgentChrome() {
  const rail = document.getElementById('lt-agent-rail');
  const btn  = document.getElementById('lt-agents-btn');
  const show = _ltAgentView && _ltActive;
  if (rail) rail.classList.toggle('open', show);
  if (btn)  btn.classList.toggle('active', _ltAgentView);
  if (show) _ltPositionAgentRail();
}

/* Dock the rail flush to the panel's left edge and cap it to the panel's
   height. Called on open, on every drag frame, on panel/window resize and
   after each re-render, because #lt-panel is fixed, draggable AND resizable —
   none of which a static CSS offset survives. */
function _ltPositionAgentRail() {
  const rail  = document.getElementById('lt-agent-rail');
  const panel = document.getElementById('lt-panel');
  if (!rail || !panel || !rail.classList.contains('open')) return;
  const r = panel.getBoundingClientRect();
  const w = rail.offsetWidth || 196;
  // Flip to the panel's right edge when there is no room on the left (the
  // panel can be dragged into the left gutter, and a rail off-screen is a rail
  // the operator cannot click).
  const fitsLeft = r.left - w >= 4;
  rail.style.top    = r.top + 'px';
  rail.style.left   = (fitsLeft ? r.left - w : r.right) + 'px';
  rail.style.maxHeight = Math.max(120, r.height) + 'px';
  rail.style.borderRadius   = fitsLeft ? '10px 0 0 10px' : '0 10px 10px 0';
  rail.style.borderRight    = fitsLeft ? 'none' : '';
  rail.style.borderLeft     = fitsLeft ? '' : 'none';
  rail.style.boxShadow      = fitsLeft ? '-8px 8px 28px rgba(0,0,0,0.6)'
                                       : '8px 8px 28px rgba(0,0,0,0.6)';
}

window.addEventListener('resize', _ltPositionAgentRail);
try {
  new ResizeObserver(_ltPositionAgentRail)
    .observe(document.getElementById('lt-panel'));
} catch (e) { /* no ResizeObserver — drag + window resize still reposition */ }

function ltToggleAgents() {
  _ltAgentView = !_ltAgentView;
  if (_ltAgentView) {
    // Opening with nothing selected lands on the busiest session — the
    // snapshot is already sorted active-first by the server.
    if (!_ltAgentSel || !_ltAgents.some(s => s.id === _ltAgentSel)) {
      const busy = _ltAgents.find(s => s.active) || _ltAgents.find(s => s.orphan);
      _ltAgentSel = busy ? busy.id : null;
    }
    ltSwitchTab('agents');
  } else {
    ltSwitchTab('log');
  }
  _ltSyncAgentChrome();
  renderAgentTabs();
}

function ltSelectAgent(sid) {
  _ltAgentSel = sid;
  const pane = document.getElementById('lt-pane-agents');
  if (pane) { pane._ltLastHtml = null; pane._ltInteractAt = 0; }
  _ltAgentView = true;
  _ltAgentTailAt = 0;            // force an immediate tail fetch
  ltSwitchTab('agents');
  renderAgentTabs();
  _ltFetchAgentTail();
}

/* The skull opens the ACTIVE sessions. Every attached session is reachable,
   but a box that routinely has ten agents attached and one rendering should not
   spend its subtab row on the nine that are doing nothing — they collapse
   behind a "+N idle" chip. A selected session always stays visible, even after
   its work finishes under the operator's eyes. */
let _ltAgentShowIdle = false;

function ltToggleIdleAgents() {
  _ltAgentShowIdle = !_ltAgentShowIdle;
  renderAgentTabs();
}

function renderAgentTabs() {
  const rail = document.getElementById('lt-agent-rail');
  if (!rail) return;
  const nActive = _ltAgents.filter(s => s.active).length;
  const hdr = `<div class="lt-rail-hdr"><span>AGENT SESSIONS</span>`
    + `<span class="n">${nActive}/${_ltAgents.length} live</span></div>`;
  if (!_ltAgents.length) {
    _ltSetHtml(rail, hdr + '<div class="lt-rail-empty">'
      + 'No Claude agent sessions attached to this box.</div>');
    _ltPositionAgentRail();
    return;
  }
  const shown = _ltAgentShowIdle
    ? _ltAgents
    : _ltAgents.filter(s => s.active || s.orphan || s.id === _ltAgentSel);
  const hidden = _ltAgents.length - shown.length;
  _ltSetHtml(rail, hdr
    + (shown.length ? '' :
        '<div class="lt-rail-empty">No agent session is on the hardware.</div>')
    + shown.map(s => {
        const cls = 'lt-atab' + (s.id === _ltAgentSel ? ' active' : '')
          + (s.active ? ' busy' : '') + (s.orphan ? ' orphan' : '');
        const load = s.orphan ? (_ltAgentFmtLoad(s) || 'orphaned') + ' · ended'
                              : (_ltAgentFmtLoad(s) || 'idle');
        return `<button class="${cls}" onclick="ltSelectAgent('${_ltEsc(s.id)}')"
                  title="${_ltEsc(s.id)}${s.orphan ? ' — session ended, processes still running' : ''}">
                  <span class="dot"></span>
                  <span class="body"><span class="nm">${_ltEsc(s.name || s.short)}</span>
                  <span class="load">${_ltEsc(load)}</span></span>
                </button>`;
      }).join('')
    + (hidden > 0
        ? `<button class="lt-atab lt-rail-more" onclick="ltToggleIdleAgents()"
             title="Show the sessions that are attached but idle">+${hidden} idle</button>`
        : (_ltAgentShowIdle && _ltAgents.length > 1
            ? `<button class="lt-atab lt-rail-more" onclick="ltToggleIdleAgents()"
                 title="Hide idle sessions">− hide idle</button>` : '')));
  _ltPositionAgentRail();
}

/* Write HTML only when it actually changed, and keep the reader's scroll
   position when it does. The agent panes re-render every poll; a blind
   innerHTML assignment every 3 seconds snaps a scrolled-back pane to the top
   and cancels every hover, which makes a long tail unreadable. */
function _ltSetHtml(el, html) {
  if (!el || el._ltLastHtml === html) return false;
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  const keep = el.scrollTop;
  el._ltLastHtml = html;
  el.innerHTML = html;
  if (!atBottom) el.scrollTop = keep;
  return atBottom;
}

function _ltEsc(v) {
  return String(v == null ? '' : v).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function _ltHHMM(iso) {
  if (!iso) return '--:--:--';
  const d = new Date(iso);
  return isNaN(d.getTime()) ? '--:--:--' : d.toTimeString().slice(0, 8);
}

function renderAgentPane() {
  const el = document.getElementById('lt-pane-agents');
  if (!el || _ltTab !== 'agents') return;
  if (_ltAgentOk === false) {
    _ltSetHtml(el, '<div class="lt-empty">Agent activity endpoint unreachable '
      + '(<code>/kanban/api/agents</code>). The kanban server may predate it — '
      + 'restart it with <code>systemctl --user restart kanban-server</code>.</div>');
    return;
  }
  const s = _ltAgents.find(x => x.id === _ltAgentSel);
  if (!s) {
    _ltSetHtml(el, '<div class="lt-empty">'
      + (_ltAgents.length ? 'Pick a session on the row above — or none is on the hardware right now.'
                          : 'No Claude agent sessions attached to this box.')
      + '</div>');
    return;
  }
  const lines = _ltAgentLines[s.id] || [];
  const procs = (s.procs || []).map(p => `
    <div class="lt-aproc${p.busy ? ' busy' : ''}">
      <span class="pid">${p.pid}</span>
      <span class="cmd" title="${_ltEsc(p.cmd)}">${_ltEsc(p.cmd)}</span>
      <span class="load">${_ltCores(p) ? _ltCores(p) + ' ' : ''}${
        p.vram_mb ? Math.round(p.vram_mb) + 'M ' : ''}${
        p.detached ? '<span style="color:#d29922">detached</span>' : ''}</span>
    </div>`).join('');
  const html = `
    <div class="lt-ahdr">
      <span><span class="k">session</span> <span class="v">${_ltEsc(s.name || s.short)}</span></span>
      <span><span class="k">id</span> <span class="v">${_ltEsc(s.short)}</span></span>
      <span><span class="k">cwd</span> <span class="v">${_ltEsc(s.project || s.cwd || '—')}</span></span>
      <span title="Cores this session's own processes are using. The machine has ${_ltCpuCount} of them."
        ><span class="k">cpu</span> <span class="v">${_ltCores(s) || '—'}</span>${
        s.cpu_share_pct >= 1 ? ` <span class="k">(${s.cpu_share_pct.toFixed(0)}% of box)</span>` : ''}</span>
      <span><span class="k">vram</span> <span class="v">${(s.vram_mb || 0).toFixed(0)} MiB</span></span>
      <span title="Resident set size, summed over the session's processes — pages shared between forks are counted once per process, so this reads high for a worker pool (~11% measured)."
        ><span class="k">ram</span> <span class="v">${((s.ram_mb || 0) / 1024).toFixed(1)} GB</span> <span class="k">rss</span></span>
      <span><span class="k">procs</span> <span class="v">${s.proc_count || 0}</span></span>
      <span style="color:${s.active ? '#3fb950' : s.orphan ? '#d29922' : '#484f58'};font-weight:700;">
        ${s.active ? '● ON HARDWARE' : s.orphan ? '⚠ ORPHANED PROCESSES' : '○ idle'}</span>
    </div>
    ${procs ? `<div style="margin-bottom:6px;">${procs}</div>` : ''}
    ${lines.length
      ? lines.map(l => `<div class="lt-aline ${_ltEsc(l.level)}">`
          + `<span class="t">[ ${_ltHHMM(l.ts)} ]</span> ${_ltEsc(l.text)}</div>`).join('')
      : '<div class="lt-empty">No recorded activity yet for this session.</div>'}`;
  if (_ltSetHtml(el, html)) _ltScrollPaneBottom(el);
}

/* One session's tail. Throttled: the pane polls with the rest of the panel but
   a transcript read is real I/O and only the SELECTED session needs one. */
function _ltFetchAgentTail() {
  if (!_ltAgentSel || _ltTab !== 'agents') return;
  const now = Date.now();
  if (now - _ltAgentTailAt < 2500) return;
  _ltAgentTailAt = now;
  fetch(LT_AGENT_BASE + '/kanban/api/agents/tail?id='
        + encodeURIComponent(_ltAgentSel) + '&limit=160')
    .then(r => r.ok ? r.json() : null)
    .then(d => {
      if (!d || d.error) return;
      _ltAgentLines[d.id || _ltAgentSel] = d.lines || [];
      renderAgentPane();
    })
    .catch(() => {});
}

/* The snapshot poll. Also the source of the ROOM-LEVEL log lines: agent work
   is written into the Pipeline Log pane so the operator sees a smoke test or a
   render burning the card next to the pipeline's own stages, without having to
   know to open the skull first. Events carry a server-side `seq`, so a line is
   written exactly once no matter how the page reloads or how long it polls. */
function pollAgents() {
  fetch(LT_AGENT_BASE + '/kanban/api/agents?since=' + _ltAgentSeq)
    .then(r => r.ok ? r.json() : Promise.reject(r.status))
    .then(d => {
      _ltAgentOk = true;
      _ltAgents  = Array.isArray(d.sessions) ? d.sessions : [];
      const active = d.active || 0;
      if (d.cpu_count) _ltCpuCount = d.cpu_count;
      _ltAgentSummary = {
        active: active, count: d.count || 0, orphans: d.orphans || 0,
        cpu: _ltAgents.reduce((a, s) => a + (s.cpu_pct || 0), 0),
        vram: _ltAgents.reduce((a, s) => a + (s.vram_mb || 0), 0),
        gpu: d.gpu || {}, stale: !!d.stale,
      };
      if (_ltTab === 'telem') renderLiveTailTelem();

      const btn   = document.getElementById('lt-agents-btn');
      const count = document.getElementById('lt-agents-count');
      if (count) count.textContent = String(active);
      if (btn) {
        btn.classList.toggle('live', active > 0);
        btn.title = active
          ? `${active} agent session${active === 1 ? '' : 's'} on the hardware`
            + ` — ${d.count} attached${d.orphans ? `, ${d.orphans} orphaned` : ''}`
          : `${d.count || 0} agent session${d.count === 1 ? '' : 's'} attached — none on the hardware`
            + (d.orphans ? ` · ${d.orphans} ended with processes still running` : '');
      }

      // New events → the shared Pipeline Log. `_ltAgentSeq` is the server's own
      // counter, never a local guess, so nothing is duplicated or skipped.
      const evs = Array.isArray(d.events) ? d.events : [];
      if (!_ltAgentPrimed) {
        // First poll of this page: adopt the watermark instead of replaying the
        // whole backlog into the log pane — but say what is running NOW, or a
        // reload would silently drop a render already in flight.
        _ltAgentPrimed = true;
        _ltAgentSeq = d.seq || 0;
        _ltAgents.filter(s => s.active).forEach(s => {
          _ltPipelineLog(`\u{1F571} agent ${s.name || s.short} on the hardware — `
            + `${_ltAgentFmtLoad(s) || 'busy'} (${s.proc_count} process`
            + `${s.proc_count === 1 ? '' : 'es'})`, 'ok');
        });
      } else if (evs.length) {
        evs.forEach(e => {
          if (e.seq > _ltAgentSeq) _ltAgentSeq = e.seq;
          const who = _ltAgentName(e.sid) || e.short;
          const cls = e.level === 'ok' ? 'ok' : e.level === 'warn' ? 'warn' : 'info';
          _ltPipelineLog(`🕱 agent ${who} — ${e.text}`, cls);
        });
      }

      if (_ltAgentView) renderAgentTabs();
      if (_ltTab === 'agents') { renderAgentPane(); _ltFetchAgentTail(); }
    })
    .catch(() => {
      // Endpoint absent (an older kanban_server still running) — the badge
      // goes quiet rather than lying about zero.
      if (_ltAgentOk === null) _ltAgentOk = false;
      const btn = document.getElementById('lt-agents-btn');
      if (btn) { btn.classList.remove('live'); btn.title = 'Agent activity unavailable'; }
      if (_ltTab === 'agents') renderAgentPane();
    });
}

function _ltAgentName(sid) {
  const s = _ltAgents.find(x => x.id === sid);
  return s ? (s.name || s.short) : '';
}

(function _ltAgentInit() {
  const btn = document.getElementById('lt-agents-btn');
  if (btn) btn.addEventListener('click', ltToggleAgents);
  pollAgents();
  setInterval(pollAgents, 3000);
})();

/* ── Copy active tab to clipboard ───────────────────────────────────────────── */
function ltCopyActiveTab() {
  const pane = document.querySelector('.lt-pane.active');
  if (!pane) return;
  const text = pane.innerText || pane.textContent || '';

  function _confirmCopied() {
    const btn = document.getElementById('lt-copy-btn');
    if (!btn) return;
    btn.textContent = '✓ Copied';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = '📋 Copy'; btn.classList.remove('copied'); }, 1500);
  }

  // Use clipboard API when available (HTTPS / localhost)
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(_confirmCopied).catch(() => _fallbackCopy(text, _confirmCopied));
  } else {
    _fallbackCopy(text, _confirmCopied);
  }
}

function _fallbackCopy(text, onSuccess) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed'; ta.style.top = '0'; ta.style.left = '0';
  ta.style.width = '1px'; ta.style.height = '1px'; ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.focus(); ta.select();
  try { if (document.execCommand('copy')) onSuccess(); }
  catch (e) { console.warn('Copy failed:', e); }
  document.body.removeChild(ta);
}

document.getElementById('lt-copy-btn').addEventListener('click', ltCopyActiveTab);

/* ── Drag support for the panel ──────────────────────────────────────────────── */
(function () {
  const panel = document.getElementById('lt-panel');
  const hdr   = document.getElementById('lt-header');
  let drag = false, ox = 0, oy = 0;
  hdr.addEventListener('mousedown', e => {
    drag = true;
    const r = panel.getBoundingClientRect();
    ox = e.clientX - r.left; oy = e.clientY - r.top;
    panel.style.right = 'auto'; panel.style.bottom = 'auto';
    panel.style.left = r.left + 'px'; panel.style.top = r.top + 'px';
  });
  document.addEventListener('mousemove', e => {
    if (!drag) return;
    panel.style.left = (e.clientX - ox) + 'px';
    panel.style.top  = (e.clientY - oy) + 'px';
    _ltPositionAgentRail();
  });
  document.addEventListener('mouseup', () => { drag = false; });
})();

// ── Agent Zero hotkey bridge ──────────────────────────────────────────────────
// The kanban runs in a cross-origin iframe (port 8899) so the parent's 'z'
// keydown listener never fires when the iframe has focus.
// Forward hotkeys to the parent dashboard via postMessage.
document.addEventListener('keydown', function(e) {
  const tag = (e.target || document.activeElement || {}).tagName || '';
  if (tag === 'INPUT' || tag === 'TEXTAREA') return;
  if (e.key.toLowerCase() === 'z') {
    e.preventDefault();
    window.parent.postMessage({ type: 'zyg_hotkey', key: 'z' }, '*');
  }
  // Also forward Escape (close Zero) and Ctrl+R (reset Zero)
  if (e.key === 'Escape') {
    window.parent.postMessage({ type: 'zyg_hotkey', key: 'Escape' }, '*');
  }
  if (e.ctrlKey && e.key.toLowerCase() === 'r') {
    e.preventDefault();
    window.parent.postMessage({ type: 'zyg_hotkey', key: 'ctrl+r' }, '*');
  }
});
// ─────────────────────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────────────────────
