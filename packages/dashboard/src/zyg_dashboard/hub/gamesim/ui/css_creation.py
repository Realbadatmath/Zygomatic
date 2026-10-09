# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stylesheet: the Creation layout — game list, kanban side, system bar, board, cards, calculations."""

CSS_CREATION = """  /* ── Creation layout ── */
  .creation-layout {
    display: flex;
    gap: 16px;
    align-items: flex-start;
    height: calc(calc(100vh / var(--ui-zoom,1)) - 320px);
    min-height: 500px;
  }

  /* Left game list */
  .glp {
    width: 190px;
    flex-shrink: 0;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px 10px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-height: 100%;
    overflow-y: auto;
  }

  .glp-title {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--muted);
    padding: 0 4px;
  }

  .glp-sub {
    font-size: 10px;
    color: #334155;
    padding: 0 4px;
    margin-bottom: 4px;
  }

  .glp-item {
    padding: 8px 10px;
    border-radius: 8px;
    background: var(--surface2);
    border: 1px solid var(--border);
    font-size: 12px;
    font-weight: 600;
    color: #cbd5e1;
    cursor: grab;
    user-select: none;
    transition: background 0.15s, border-color 0.15s, transform 0.1s;
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .glp-item::before {
    content: "⠿";
    color: #334155;
    font-size: 14px;
    flex-shrink: 0;
  }

  .glp-item:hover { background: rgba(244,114,182,0.08); border-color: rgba(244,114,182,0.25); color: #f1f5f9; }
  .glp-item:active { transform: scale(0.97); cursor: grabbing; }
  .glp-item.dragging { opacity: 0.4; }

  /* Kanban side */
  .kanban-side {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 12px;
    max-height: 100%;
  }

  /* System bar */
  .sys-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px 14px;
    font-size: 12px;
    color: var(--muted);
    flex-wrap: wrap;
  }

  .sys-lbl { font-weight: 700; color: #94a3b8; margin-right: 4px; }

  .sys-inp {
    width: 52px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-size: 12px;
    padding: 3px 6px;
    text-align: center;
    outline: none;
    transition: border-color 0.2s;
  }
  .sys-inp:focus { border-color: rgba(244,114,182,0.4); }

  /* Board */
  .kanban-board {
    flex: 1;
    min-height: 180px;
    background: var(--surface);
    border: 2px dashed rgba(255,255,255,0.07);
    border-radius: 12px;
    padding: 12px;
    transition: border-color 0.2s, background 0.2s;
    overflow-y: auto;
    position: relative;
  }

  .kanban-board.drag-over {
    border-color: rgba(244,114,182,0.5);
    background: rgba(244,114,182,0.04);
  }

  .kanban-empty {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    color: #1e293b;
    font-size: 13px;
    pointer-events: none;
  }

  .kanban-cards {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-content: flex-start;
  }

  /* Kanban card */
  .k-card {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px 12px;
    min-width: 150px;
    max-width: 200px;
    cursor: grab;
    user-select: none;
    position: relative;
    transition: border-color 0.15s, transform 0.1s;
    animation: cardIn 0.15s ease both;
  }

  @keyframes cardIn {
    from { opacity: 0; transform: scale(0.9) translateY(-4px); }
    to   { opacity: 1; transform: scale(1) translateY(0); }
  }

  .k-card:hover { border-color: rgba(244,114,182,0.35); }
  .k-card:active { cursor: grabbing; transform: scale(0.97); }
  .k-card.dragging { opacity: 0.3; }

  .k-card-name {
    font-size: 12px;
    font-weight: 700;
    color: #f1f5f9;
    margin-bottom: 4px;
    padding-right: 18px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .k-card-instance {
    font-size: 10px;
    color: #f472b6;
    font-weight: 600;
    margin-bottom: 5px;
  }

  .k-card-spec {
    font-size: 10px;
    color: var(--muted);
    line-height: 1.6;
  }

  .k-card-spec span { color: #94a3b8; }

  .k-remove {
    position: absolute;
    top: 6px; right: 6px;
    width: 16px; height: 16px;
    border-radius: 4px;
    border: none;
    background: rgba(239,68,68,0.12);
    color: #ef4444;
    font-size: 11px;
    line-height: 1;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0;
    transition: opacity 0.15s, background 0.15s;
  }

  .k-card:hover .k-remove { opacity: 1; }
  .k-remove:hover { background: rgba(239,68,68,0.25); }

  /* Double-click hint */
  .k-card::after {
    content: "double-click to duplicate";
    position: absolute;
    bottom: -22px;
    left: 50%;
    transform: translateX(-50%);
    font-size: 9px;
    color: #334155;
    white-space: nowrap;
    opacity: 0;
    transition: opacity 0.2s;
    pointer-events: none;
  }
  .k-card:hover::after { opacity: 1; }

  /* Calculations */
  .calc-panel {
    background: var(--surface);
    border: 1px solid rgba(244,114,182,0.15);
    border-radius: 12px;
    padding: 16px 18px;
  }

  .calc-title {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 14px;
  }

  .calc-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 10px;
    margin-bottom: 14px;
  }

  .calc-item {
    background: var(--surface2);
    border-radius: 8px;
    padding: 10px 12px;
  }

  .calc-item-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 4px;
  }

  .calc-item-value {
    font-size: 18px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: #f1f5f9;
    margin-bottom: 3px;
  }

  .calc-item-sub {
    font-size: 10px;
    color: var(--muted);
    margin-bottom: 6px;
  }

  .calc-bar-bg {
    height: 4px;
    background: rgba(255,255,255,0.06);
    border-radius: 2px;
    overflow: hidden;
  }

  .calc-bar-fill {
    height: 100%;
    border-radius: 2px;
    transition: width 0.4s ease;
  }

  .bar-ok     { background: #4ade80; }
  .bar-warn   { background: #fbbf24; }
  .bar-danger { background: #ef4444; }

  .calc-spike {
    font-size: 10px;
    margin-top: 4px;
    font-weight: 600;
  }

  .activate-btn {
    width: 100%;
    padding: 12px;
    border: none;
    border-radius: 10px;
    background: linear-gradient(135deg, #f472b6, #a855f7);
    color: #fff;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.5px;
    cursor: pointer;
    transition: opacity 0.2s, transform 0.1s, box-shadow 0.2s;
    box-shadow: 0 0 18px rgba(244,114,182,0.25);
  }
  .activate-btn:hover  { opacity: 0.88; box-shadow: 0 0 28px rgba(244,114,182,0.45); }
  .activate-btn:active { transform: scale(0.98); }

"""
