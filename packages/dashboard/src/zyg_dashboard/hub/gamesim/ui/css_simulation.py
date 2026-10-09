# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stylesheet: simulation status panel, benchmark, progress, live card, debug console, frames gallery."""

CSS_SIMULATION = """  /* ── Simulation status panel ── */
  #sim-status-panel {
    background: var(--surface);
    border: 1px solid rgba(244,114,182,0.15);
    border-radius: 12px;
    padding: 14px 16px;
  }

  .sim-status-header {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    font-weight: 600;
    color: #f1f5f9;
    margin-bottom: 12px;
  }

  .sim-status-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: #334155;
    flex-shrink: 0;
    transition: background 0.3s;
  }
  .sim-status-dot.starting  { background: #fbbf24; box-shadow: 0 0 6px rgba(251,191,36,0.6); animation: pulse 1s infinite; }
  .sim-status-dot.recording { background: #4ade80; box-shadow: 0 0 6px rgba(74,222,128,0.6); animation: pulse 2s infinite; }
  .sim-status-dot.stopped   { background: #475569; }

  @keyframes pulse {
    0%,100% { opacity: 1; }
    50%      { opacity: 0.4; }
  }

  .sim-instance-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .sim-inst-row {
    display: flex;
    align-items: center;
    gap: 10px;
    background: var(--surface2);
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 11px;
  }

  .sim-inst-name { font-weight: 700; color: #cbd5e1; min-width: 120px; }
  .sim-inst-display { color: #475569; }
  .sim-inst-status { margin-left: auto; font-weight: 600; }
  .sim-inst-status.recording { color: #4ade80; }
  .sim-inst-status.starting  { color: #fbbf24; }
  .sim-inst-status.error     { color: #ef4444; }
  .sim-inst-output { color: #334155; font-size: 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 220px; }

  /* ── Benchmark ── */
  .bench-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 24px;
    flex-wrap: wrap;
  }
  .bench-title-block { display: flex; flex-direction: column; gap: 2px; }
  .bench-title { font-size: 16px; font-weight: 700; color: #f1f5f9; }
  .bench-sub   { font-size: 11px; color: var(--muted); }
  .bench-controls { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .bench-lbl { font-size: 11px; color: var(--muted); white-space: nowrap; }

  /* Progress */
  .bench-prog-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
    font-size: 13px;
    font-weight: 600;
    color: #f1f5f9;
  }
  .bench-prog-track {
    height: 6px;
    background: rgba(255,255,255,0.06);
    border-radius: 3px;
    overflow: hidden;
    margin-bottom: 16px;
  }
  .bench-prog-fill {
    height: 100%;
    background: linear-gradient(90deg, #f472b6, #a855f7);
    border-radius: 3px;
    transition: width 0.5s ease;
  }

  /* Live card */
  .bench-live {
    background: var(--surface);
    border: 1px solid rgba(244,114,182,0.2);
    border-radius: 12px;
    padding: 16px 18px;
    margin-bottom: 24px;
  }
  .bench-live-game {
    font-size: 15px;
    font-weight: 700;
    color: #f1f5f9;
    margin-bottom: 2px;
  }
  .bench-live-phase {
    font-size: 11px;
    color: #f472b6;
    font-weight: 600;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    margin-bottom: 14px;
  }
  .bench-live-metrics {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
    margin-bottom: 14px;
  }
  .bench-metric-box {
    background: var(--surface2);
    border-radius: 8px;
    padding: 10px 12px;
  }
  .bench-metric-label { font-size: 9px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #475569; margin-bottom: 3px; }
  .bench-metric-val   { font-size: 20px; font-weight: 700; font-variant-numeric: tabular-nums; color: #f1f5f9; }
  .bench-metric-unit  { font-size: 10px; color: var(--muted); margin-left: 2px; }

  .bench-time-track {
    height: 4px;
    background: rgba(255,255,255,0.06);
    border-radius: 2px;
    overflow: hidden;
    margin-bottom: 4px;
  }
  .bench-time-fill {
    height: 100%;
    background: #f472b6;
    border-radius: 2px;
    transition: width 1s linear;
  }
  .bench-time-label { font-size: 10px; color: var(--muted); text-align: right; }

  /* Debug console */
  .bench-debug-wrap {
    margin-top: 20px;
    border: 1px solid rgba(244,114,182,0.12);
    border-radius: 10px;
    overflow: hidden;
  }
  .bench-debug-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 16px;
    background: rgba(244,114,182,0.05);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--muted);
    border-bottom: 1px solid rgba(255,255,255,0.05);
  }
  .bench-debug-header span { color: #4ade80; font-size: 10px; font-weight: 400; text-transform: none; letter-spacing: 0; }
  .bench-debug-console {
    background: #06060e;
    font-family: "SF Mono","Fira Code","Cascadia Code",monospace;
    font-size: 11px;
    line-height: 1.75;
    color: #94a3b8;
    padding: 12px 16px;
    height: 420px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .bench-debug-console .dbg-ts   { color: #334155; }
  .bench-debug-console .dbg-err  { color: #f87171; }
  .bench-debug-console .dbg-ok   { color: #4ade80; }
  .bench-debug-console .dbg-sep  { color: #a78bfa; font-weight: 700; }
  .bench-debug-console .dbg-warn { color: #fbbf24; }
  .bench-debug-console .dbg-live { color: #38bdf8; }
  /* ── Frames gallery ── */
  .bench-frames-wrap {
    margin-top: 20px;
    border: 1px solid rgba(99,102,241,0.2);
    border-radius: 10px;
    overflow: hidden;
  }
  .bench-frames-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 16px;
    background: rgba(99,102,241,0.06);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--muted);
    border-bottom: 1px solid rgba(255,255,255,0.05);
  }
  .bench-frames-header .fh-count { color: #818cf8; font-size: 10px; font-weight: 400; text-transform: none; letter-spacing: 0; flex: 1; }
  .bench-frames-filmstrip {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    padding: 12px;
    background: #06060e;
    min-height: 72px;
    max-height: 340px;
    overflow-y: auto;
  }
  .bench-frame-item { display: flex; flex-direction: column; align-items: center; gap: 3px; }
  .bench-frames-thumb {
    width: 160px; height: 90px;
    object-fit: cover;
    border-radius: 6px;
    border: 2px solid transparent;
    cursor: pointer;
    transition: border-color 0.15s, transform 0.1s;
    background: #0f0f1a;
    display: block;
  }
  .bench-frames-thumb:hover { border-color: #818cf8; transform: scale(1.03); }
  .bench-frames-thumb.active { border-color: #6366f1; }
  .bench-frame-ts { font-size: 9px; color: #334155; font-family: monospace; }
  .bench-frames-detail {
    padding: 16px;
    background: #06060e;
    border-top: 1px solid rgba(255,255,255,0.05);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
  }
  .bench-frames-detail img { max-width: 100%; border-radius: 8px; border: 1px solid rgba(99,102,241,0.3); }
  .bench-frames-caption { font-size: 11px; color: #475569; font-family: monospace; }
  .bench-game-logs {
    display: none;
    background: #06060e;
    font-family: "SF Mono","Fira Code",monospace;
    font-size: 10px;
    line-height: 1.65;
    color: #475569;
    padding: 10px 14px;
    max-height: 220px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-all;
    border-top: 1px solid rgba(255,255,255,0.04);
    margin-top: 8px;
  }
  .bench-log-toggle {
    font-size: 10px;
    color: var(--muted);
    background: none;
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 3px 9px;
    cursor: pointer;
    margin-top: 6px;
    transition: color 0.15s, border-color 0.15s;
  }
  .bench-log-toggle:hover { color: var(--text); border-color: rgba(244,114,182,0.3); }

  /* Results */
  .bench-results {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .bench-result-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px 18px;
    display: grid;
    grid-template-columns: 200px 1fr auto;
    gap: 16px;
    align-items: center;
    transition: border-color 0.2s;
    animation: cardIn 0.2s ease both;
  }
  .bench-result-card:hover { border-color: rgba(244,114,182,0.2); }

  .bench-result-left { display: flex; flex-direction: column; gap: 4px; }
  .bench-result-game { font-size: 14px; font-weight: 700; color: #f1f5f9; }
  .bench-result-startup { font-size: 11px; color: var(--muted); }
  .bench-result-fps   { font-size: 11px; color: #4ade80; }

  .bench-result-stats {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
  }

  .bench-stat {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .bench-stat-label { font-size: 9px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #334155; }
  .bench-stat-vals  { font-size: 12px; color: #94a3b8; }
  .bench-stat-vals b { color: #f1f5f9; font-size: 13px; }

  .bench-stat-bar-bg   { height: 3px; background: rgba(255,255,255,0.06); border-radius: 2px; margin-top: 3px; overflow: hidden; }
  .bench-stat-bar-fill { height: 100%; border-radius: 2px; }

  .bench-verdict {
    padding: 6px 14px;
    border-radius: 8px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    white-space: nowrap;
    text-align: center;
    min-width: 90px;
  }
  .v-smooth     { background: rgba(74,222,128,0.1);  color: #4ade80; border: 1px solid rgba(74,222,128,0.2); }
  .v-acceptable { background: rgba(251,191,36,0.1);  color: #fbbf24; border: 1px solid rgba(251,191,36,0.2); }
  .v-heavy      { background: rgba(249,115,22,0.1);  color: #f97316; border: 1px solid rgba(249,115,22,0.2); }
  .v-failed     { background: rgba(239,68,68,0.1);   color: #ef4444; border: 1px solid rgba(239,68,68,0.2); }
  .v-no_folder  { background: rgba(71,85,105,0.2);   color: #475569; border: 1px solid rgba(71,85,105,0.2); }

"""
