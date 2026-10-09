# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stylesheet: Schematics kanban, production list, Schematic Creator, toast and context menu."""

CSS_BOARDS = """  /* ── Schematics kanban ── */
  .schem-topbar { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 14px; min-height: 34px; }
  .schem-hint { font-size: 11px; color: var(--muted); }
  .schem-banner { display: flex; align-items: center; gap: 10px; background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.25); border-radius: 10px; padding: 6px 12px; font-size: 12px; color: #fca5a5; }
  .rec-dot { width: 8px; height: 8px; border-radius: 50%; background: #ef4444; animation: recPulse 1.2s infinite; flex-shrink: 0; }
  @keyframes recPulse { 0%,100% { opacity: 1; } 50% { opacity: 0.35; } }

  .schem-board { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; align-items: start; }
  .schem-col { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 10px; min-height: 340px; transition: border-color 0.15s, background 0.15s; }
  .schem-col.drag-over { border-color: rgba(244,114,182,0.5); background: rgba(244,114,182,0.05); }
  .schem-col-head { display: flex; align-items: center; justify-content: space-between; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: var(--muted); padding: 2px 4px 10px; }
  .schem-col-count { background: rgba(255,255,255,0.07); border-radius: 99px; padding: 1px 8px; font-size: 10px; color: var(--text); }
  .schem-col-empty { border: 1px dashed rgba(255,255,255,0.1); border-radius: 10px; padding: 24px 10px; text-align: center; font-size: 11px; color: #334155; }

  .schem-card { background: rgba(255,255,255,0.03); border: 1px solid var(--border); border-radius: 12px; padding: 10px; margin-bottom: 10px; cursor: grab; transition: border-color 0.15s, transform 0.15s, box-shadow 0.15s; }
  .schem-card:hover { border-color: rgba(244,114,182,0.45); transform: translateY(-1px); box-shadow: 0 6px 18px rgba(0,0,0,0.35); }
  .schem-card.dragging { opacity: 0.45; }
  .schem-preview { width: 100%; height: auto; display: block; border-radius: 8px; background: linear-gradient(180deg, rgba(148,163,184,0.07), rgba(148,163,184,0.02)); margin-bottom: 8px; }
  .schem-name { font-size: 13px; font-weight: 700; color: var(--text); margin-bottom: 6px; }
  .schem-tags { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 7px; }
  .schem-cat  { font-size: 9px; font-weight: 700; letter-spacing: 0.7px; text-transform: uppercase; padding: 2px 7px; border-radius: 99px; background: rgba(96,165,250,0.12); color: #93c5fd; }
  .schem-diff { font-size: 9px; font-weight: 700; letter-spacing: 0.7px; text-transform: uppercase; padding: 2px 7px; border-radius: 99px; }
  .d-easy { background: rgba(74,222,128,0.12); color: #4ade80; }
  .d-med  { background: rgba(251,191,36,0.12); color: #fbbf24; }
  .d-hard { background: rgba(239,68,68,0.12); color: #f87171; }
  .schem-qbadge { font-size: 9px; font-weight: 700; padding: 2px 7px; border-radius: 99px; background: rgba(244,114,182,0.14); color: #f472b6; }
  .schem-stats { display: flex; gap: 10px; font-size: 10px; color: var(--muted); font-variant-numeric: tabular-nums; }

  /* ── Production list ── */
  .prod-controls { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
  .prod-btn { border: none; border-radius: 9px; padding: 9px 18px; font-size: 13px; font-weight: 700; cursor: pointer; transition: opacity 0.15s, transform 0.1s; color: #0b0b14; }
  .prod-btn:disabled { opacity: 0.3; cursor: default; }
  .prod-btn:not(:disabled):hover { transform: translateY(-1px); }
  .p-play  { background: #4ade80; }
  .p-pause { background: #fbbf24; }
  .p-stop  { background: #f87171; }
  .prod-state { font-size: 10px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; padding: 4px 12px; border-radius: 99px; }
  .st-playing { background: rgba(74,222,128,0.12); color: #4ade80; }
  .st-paused  { background: rgba(251,191,36,0.12); color: #fbbf24; }
  .st-stopped { background: rgba(148,163,184,0.12); color: #94a3b8; }

  .prod-current { background: var(--surface); border: 1px solid rgba(74,222,128,0.3); border-radius: 14px; padding: 14px 16px; margin-bottom: 16px; }
  .prod-current-head { display: flex; align-items: center; gap: 10px; font-size: 14px; font-weight: 700; color: var(--text); margin-bottom: 10px; }
  .prod-cur-meta { font-size: 11px; font-weight: 500; color: var(--muted); margin-left: auto; font-variant-numeric: tabular-nums; }
  .prod-prog-track { height: 8px; border-radius: 99px; background: rgba(255,255,255,0.06); overflow: hidden; }
  .prod-prog-fill { height: 100%; border-radius: 99px; background: linear-gradient(90deg, #4ade80, #22d3ee); transition: width 0.6s ease; }
  .prod-prog-label { font-size: 11px; color: var(--muted); margin-top: 7px; font-variant-numeric: tabular-nums; }

  .prod-list { display: flex; flex-direction: column; gap: 8px; }
  .prod-row { display: flex; align-items: center; gap: 12px; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 10px 14px; }
  .prod-row.running { border-color: rgba(74,222,128,0.35); }
  .prod-num { width: 22px; height: 22px; border-radius: 50%; background: rgba(255,255,255,0.06); display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 700; color: var(--muted); flex-shrink: 0; }
  .prod-name { font-size: 13px; font-weight: 600; color: var(--text); }
  .prod-meta { font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums; }
  .prod-rec { font-size: 10px; color: #4ade80; }
  .prod-status { margin-left: auto; font-size: 9px; font-weight: 700; letter-spacing: 0.8px; text-transform: uppercase; padding: 3px 9px; border-radius: 99px; }
  .ps-queued  { background: rgba(96,165,250,0.12); color: #93c5fd; }
  .ps-running { background: rgba(74,222,128,0.12); color: #4ade80; animation: recPulse 1.4s infinite; }
  .ps-done    { background: rgba(74,222,128,0.10); color: #86efac; }
  .ps-stopped { background: rgba(148,163,184,0.12); color: #94a3b8; }
  .ps-failed  { background: rgba(239,68,68,0.12); color: #f87171; }
  .prod-actions { display: flex; gap: 4px; }
  .prod-mini { border: 1px solid var(--border); background: transparent; color: var(--muted); border-radius: 7px; width: 24px; height: 24px; font-size: 10px; cursor: pointer; transition: color 0.15s, border-color 0.15s; }
  .prod-mini:hover { color: var(--text); border-color: rgba(255,255,255,0.3); }
  .prod-mini.danger:hover { color: #f87171; border-color: rgba(239,68,68,0.4); }
  .prod-empty { border: 1px dashed rgba(255,255,255,0.1); border-radius: 14px; padding: 36px 20px; text-align: center; font-size: 12px; color: #475569; }

  /* ── Schematic Creator ── */
  .cr-top { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
  .cr-src { display: flex; gap: 6px; }
  .cr-srcbtn { border: 1px solid var(--border); background: rgba(255,255,255,0.03); color: var(--text); border-radius: 9px; padding: 7px 12px; font-size: 12px; font-weight: 600; cursor: pointer; display: flex; align-items: center; gap: 6px; transition: border-color .15s, background .15s; }
  .cr-srcbtn:hover { border-color: rgba(244,114,182,0.5); background: rgba(244,114,182,0.08); }
  .cr-name { flex: 1; min-width: 160px; background: rgba(255,255,255,0.04); border: 1px solid var(--border); border-radius: 9px; padding: 8px 12px; color: var(--text); font-size: 13px; font-weight: 600; font-family: inherit; }
  .cr-name:focus { outline: none; border-color: rgba(244,114,182,0.5); }
  .cr-sel { background: rgba(255,255,255,0.04); border: 1px solid var(--border); border-radius: 9px; padding: 8px 10px; color: var(--text); font-size: 12px; font-family: inherit; }
  .cr-save { background: #4ade80; color: #0b0b14; border: none; border-radius: 9px; padding: 9px 18px; font-size: 13px; font-weight: 700; cursor: pointer; }
  .cr-save:disabled { opacity: .35; cursor: default; }

  .cr-layout { display: grid; grid-template-columns: 300px 1fr 280px; gap: 14px; align-items: start; }
  .cr-col { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 12px; }
  .cr-h { font-size: 10px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: var(--muted); margin-bottom: 10px; display: flex; align-items: center; justify-content: space-between; }
  .cr-ops { display: flex; flex-direction: column; gap: 7px; max-height: 460px; overflow-y: auto; }
  .cr-op { border: 1px solid var(--border); border-radius: 10px; background: rgba(255,255,255,0.02); }
  .cr-op.muted { opacity: .45; }
  .cr-op-head { display: flex; align-items: center; gap: 6px; padding: 7px 9px; cursor: pointer; }
  .cr-op-name { font-size: 12px; font-weight: 700; color: var(--text); flex: 1; }
  .cr-op-n { font-size: 9px; color: var(--muted); font-variant-numeric: tabular-nums; }
  .cr-mini { border: 1px solid var(--border); background: transparent; color: var(--muted); border-radius: 6px; width: 20px; height: 20px; font-size: 9px; cursor: pointer; line-height: 1; }
  .cr-mini:hover { color: var(--text); border-color: rgba(255,255,255,.3); }
  .cr-mini.danger:hover { color: #f87171; border-color: rgba(239,68,68,.4); }
  .cr-op-body { padding: 4px 9px 9px; display: none; }
  .cr-op.open .cr-op-body { display: block; }
  .cr-p { display: flex; align-items: center; gap: 6px; margin-bottom: 5px; }
  .cr-p label { font-size: 10px; color: var(--muted); width: 74px; flex-shrink: 0; }
  .cr-p input[type=number], .cr-p input[type=text], .cr-p select { flex: 1; min-width: 0; background: rgba(255,255,255,0.05); border: 1px solid var(--border); border-radius: 6px; padding: 4px 7px; color: var(--text); font-size: 11px; font-family: inherit; }
  .cr-p input:focus, .cr-p select:focus { outline: none; border-color: rgba(244,114,182,.5); }
  .cr-addop { width: 100%; border: 1px dashed rgba(255,255,255,0.16); background: transparent; color: var(--muted); border-radius: 9px; padding: 8px; font-size: 11px; font-weight: 600; cursor: pointer; margin-top: 8px; }
  .cr-addop:hover { color: #f472b6; border-color: rgba(244,114,182,.45); }

  .cr-view { position: relative; }
  .cr-canvas { width: 100%; height: auto; display: block; border-radius: 10px; background: linear-gradient(180deg, rgba(148,163,184,.08), rgba(148,163,184,.02)); cursor: crosshair; }
  .cr-viewbar { display: flex; align-items: center; gap: 8px; margin-top: 9px; flex-wrap: wrap; }
  .cr-tab2 { border: 1px solid var(--border); background: transparent; color: var(--muted); border-radius: 7px; padding: 4px 10px; font-size: 11px; font-weight: 600; cursor: pointer; }
  .cr-tab2.on { background: rgba(244,114,182,.15); color: #f472b6; border-color: rgba(244,114,182,.4); }
  .cr-slider { flex: 1; min-width: 90px; accent-color: #f472b6; }
  .cr-legend { display: flex; gap: 10px; font-size: 10px; color: var(--muted); }
  .cr-dot { display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 3px; vertical-align: middle; }

  .cr-grid { display: grid; gap: 1px; background: rgba(255,255,255,.05); border-radius: 8px; padding: 1px; margin: 0 auto; }
  .cr-cell { width: 100%; aspect-ratio: 1; background: #0f172a; border-radius: 1px; cursor: pointer; position: relative; }
  .cr-cell:hover { outline: 1px solid #f472b6; z-index: 2; }
  .cr-cell.below { opacity: .3; }
  .cr-cell.bad { outline: 1.5px solid #ef4444; z-index: 1; }

  .cr-report { font-size: 11px; }
  .cr-verdict { display: flex; align-items: center; gap: 8px; padding: 9px 11px; border-radius: 10px; font-size: 12px; font-weight: 700; margin-bottom: 10px; }
  .cr-ok { background: rgba(74,222,128,.1); color: #4ade80; border: 1px solid rgba(74,222,128,.3); }
  .cr-bad { background: rgba(239,68,68,.1); color: #f87171; border: 1px solid rgba(239,68,68,.3); }
  .cr-busy { background: rgba(148,163,184,.1); color: #94a3b8; border: 1px solid rgba(148,163,184,.25); }
  .cr-stat { display: flex; justify-content: space-between; padding: 3px 0; color: var(--muted); }
  .cr-stat b { color: var(--text); font-weight: 600; font-variant-numeric: tabular-nums; }
  .cr-issues { margin-top: 9px; max-height: 150px; overflow-y: auto; display: flex; flex-direction: column; gap: 4px; }
  .cr-issue { background: rgba(239,68,68,.07); border-left: 2px solid rgba(239,68,68,.5); border-radius: 4px; padding: 5px 7px; font-size: 10px; color: #fca5a5; }
  .cr-issue.warn { background: rgba(251,191,36,.07); border-left-color: rgba(251,191,36,.5); color: #fbbf24; }
  .cr-mats { margin-top: 9px; display: flex; flex-direction: column; gap: 3px; max-height: 140px; overflow-y: auto; }
  .cr-mat { display: flex; align-items: center; gap: 6px; font-size: 10px; color: var(--muted); }
  .cr-sw { width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0; border: 1px solid rgba(255,255,255,.15); }

  .cr-pal { display: grid; grid-template-columns: repeat(auto-fill, minmax(22px, 1fr)); gap: 3px; max-height: 130px; overflow-y: auto; margin-top: 6px; }
  .cr-swatch { aspect-ratio: 1; border-radius: 3px; cursor: pointer; border: 1.5px solid transparent; }
  .cr-swatch.on { border-color: #f472b6; transform: scale(1.15); }
  .cr-search { width: 100%; background: rgba(255,255,255,.05); border: 1px solid var(--border); border-radius: 7px; padding: 5px 8px; color: var(--text); font-size: 11px; font-family: inherit; }
  .cr-search:focus { outline: none; border-color: rgba(244,114,182,.5); }
  .cr-curmat { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--text); margin-top: 7px; }

  /* ── Toast ── */
  #toast { position: fixed; bottom: 26px; left: 50%; transform: translateX(-50%) translateY(16px); background: #1a1a2e; border: 1px solid rgba(74,222,128,0.4); color: var(--text); font-size: 13px; font-weight: 600; padding: 10px 20px; border-radius: 12px; box-shadow: 0 12px 40px rgba(0,0,0,0.6); opacity: 0; pointer-events: none; transition: opacity 0.2s, transform 0.2s; z-index: 10000; }
  #toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
  #toast.err { border-color: rgba(239,68,68,0.5); }

  /* ── Context menu ── */
  #ctx-menu, #schem-ctx {
    position: fixed;
    z-index: 9999;
    background: #1a1a2e;
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 10px;
    padding: 5px;
    min-width: 190px;
    box-shadow: 0 12px 40px rgba(0,0,0,0.6);
    display: none;
    animation: ctxIn 0.12s ease both;
  }

  #ctx-menu.show, #schem-ctx.show { display: block; }

  @keyframes ctxIn {
    from { opacity: 0; transform: scale(0.95) translateY(-4px); }
    to   { opacity: 1; transform: scale(1) translateY(0); }
  }

  .ctx-item {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 9px 12px;
    border-radius: 7px;
    font-size: 13px;
    font-weight: 500;
    color: var(--text);
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
  }

  .ctx-item svg {
    width: 14px; height: 14px;
    stroke: currentColor;
    fill: none;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
    flex-shrink: 0;
    opacity: 0.7;
  }

  .ctx-item:hover {
    background: rgba(244,114,182,0.12);
    color: #f472b6;
  }

  .ctx-item:hover svg { opacity: 1; }

  .ctx-game-label {
    padding: 6px 12px 4px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--muted);
  }

"""
