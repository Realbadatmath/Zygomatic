# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stylesheet: Content Library, its cards, the video modal and the custom scrollbars."""

CSS_LIBRARY = """  /* ── Content Library ── */
  .lib-toolbar {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 18px;
    flex-wrap: wrap;
  }

  .lib-search-wrap {
    position: relative;
    flex: 1;
    min-width: 180px;
  }
  .lib-search-wrap svg {
    position: absolute;
    left: 10px; top: 50%;
    transform: translateY(-50%);
    width: 13px; height: 13px;
    stroke: var(--muted); fill: none; stroke-width: 2; stroke-linecap: round;
    pointer-events: none;
  }
  .lib-search {
    width: 100%;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    font-size: 13px;
    padding: 7px 10px 7px 32px;
    outline: none;
    transition: border-color 0.2s;
  }
  .lib-search:focus { border-color: rgba(244,114,182,0.4); }

  .lib-sort {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    font-size: 12px;
    padding: 7px 10px;
    outline: none;
    cursor: pointer;
  }

  .lib-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    padding: 80px 0;
    color: #1e293b;
    font-size: 14px;
    font-weight: 600;
  }

  .lib-grid {
    display: flex;
    flex-direction: column;
    gap: 28px;
  }

  .lib-group-title {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .lib-group-title::after {
    content: '';
    flex: 1;
    height: 1px;
    background: var(--border);
  }

  .lib-group-cards {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 14px;
  }

  /* Card */
  .lib-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
    cursor: pointer;
    transition: border-color 0.2s, transform 0.15s, box-shadow 0.2s;
    position: relative;
  }
  .lib-card:hover {
    border-color: rgba(244,114,182,0.35);
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  }

  .lib-card-preview {
    position: relative;
    width: 100%;
    aspect-ratio: 16/9;
    background: #050510;
    overflow: hidden;
  }

  .lib-card-preview video {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    opacity: 0;
    transition: opacity 0.3s;
    pointer-events: none;
  }
  .lib-card-preview video.loaded { opacity: 1; }

  .lib-card-thumb {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(135deg, #0a0a18, #0e0e22);
    transition: opacity 0.3s;
  }
  .lib-card-thumb svg { opacity: 0.12; }
  .lib-card:hover .lib-card-thumb { opacity: 0; }

  .lib-play-btn {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0;
    transition: opacity 0.2s;
    background: rgba(0,0,0,0.3);
    pointer-events: none;
  }
  .lib-card:hover .lib-play-btn { opacity: 1; }

  .lib-play-circle {
    width: 44px; height: 44px;
    background: rgba(244,114,182,0.9);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 0 20px rgba(244,114,182,0.5);
  }
  .lib-play-circle svg { width: 18px; height: 18px; fill: white; margin-left: 2px; }

  .lib-game-badge {
    position: absolute;
    top: 8px; left: 8px;
    padding: 3px 8px;
    border-radius: 6px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.5px;
    backdrop-filter: blur(8px);
  }

  .lib-inst-badge {
    position: absolute;
    top: 8px; right: 32px;
    padding: 3px 7px;
    border-radius: 6px;
    font-size: 10px;
    font-weight: 600;
    background: rgba(0,0,0,0.6);
    color: #94a3b8;
    backdrop-filter: blur(8px);
  }

  .lib-delete-btn {
    position: absolute;
    top: 6px; right: 6px;
    width: 22px; height: 22px;
    background: rgba(239,68,68,0.15);
    border: 1px solid rgba(239,68,68,0.2);
    border-radius: 6px;
    color: #ef4444;
    font-size: 13px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    opacity: 0;
    transition: opacity 0.15s, background 0.15s;
    z-index: 2;
  }
  .lib-card:hover .lib-delete-btn { opacity: 1; }
  .lib-delete-btn:hover { background: rgba(239,68,68,0.3); }

  .lib-card-info {
    padding: 10px 12px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .lib-card-name {
    font-size: 13px;
    font-weight: 700;
    color: #f1f5f9;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .lib-card-meta {
    font-size: 10px;
    color: var(--muted);
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .lib-card-meta span { display: flex; align-items: center; gap: 3px; }

  /* Video modal */
  .vid-modal {
    position: fixed;
    inset: 0;
    z-index: 1000;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .vid-modal-bg {
    position: absolute;
    inset: 0;
    background: rgba(0,0,0,0.85);
    backdrop-filter: blur(6px);
    cursor: pointer;
  }

  .vid-modal-box {
    position: relative;
    z-index: 1;
    width: min(1100px, calc(94vw / var(--ui-zoom,1)));
    background: var(--surface);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    overflow: hidden;
    box-shadow: 0 32px 80px rgba(0,0,0,0.8);
    animation: modalIn 0.18s ease both;
  }

  @keyframes modalIn {
    from { opacity: 0; transform: scale(0.95) translateY(10px); }
    to   { opacity: 1; transform: scale(1)    translateY(0); }
  }

  .vid-modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 18px;
    border-bottom: 1px solid var(--border);
  }
  .vid-modal-header span { font-size: 14px; font-weight: 700; color: #f1f5f9; }

  .vid-modal-close {
    width: 28px; height: 28px;
    background: rgba(255,255,255,0.06);
    border: none;
    border-radius: 8px;
    color: var(--muted);
    font-size: 18px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background 0.15s, color 0.15s;
  }
  .vid-modal-close:hover { background: rgba(239,68,68,0.15); color: #ef4444; }

  .vid-modal-player {
    width: 100%;
    aspect-ratio: 16/9;
    background: #000;
    display: block;
  }

  .vid-modal-meta {
    padding: 12px 18px;
    font-size: 11px;
    color: var(--muted);
    display: flex;
    gap: 16px;
    border-top: 1px solid var(--border);
  }

  /* ── Custom scrollbars ── */
  .kanban-board::-webkit-scrollbar,
  .glp::-webkit-scrollbar {
    width: 4px;
  }
  .kanban-board::-webkit-scrollbar-track,
  .glp::-webkit-scrollbar-track {
    background: transparent;
  }
  .kanban-board::-webkit-scrollbar-thumb,
  .glp::-webkit-scrollbar-thumb {
    background: rgba(244,114,182,0.25);
    border-radius: 99px;
  }
  .kanban-board::-webkit-scrollbar-thumb:hover,
  .glp::-webkit-scrollbar-thumb:hover {
    background: rgba(244,114,182,0.5);
  }

"""
