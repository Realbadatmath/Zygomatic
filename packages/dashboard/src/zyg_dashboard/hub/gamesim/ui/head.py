# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Document head: <style> opening, design tokens, header, stats strip, toolbar, table."""

HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Game Simulator — Zygomatic</title>
<link rel="icon" type="image/png" href="/favicon.ico">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:       #07070f;
    --surface:  #0e0e1a;
    --surface2: #131325;
    --border:   rgba(255,255,255,0.07);
    --text:     #e2e8f0;
    --muted:    #64748b;
    --accent:   #f472b6;
    --accent-r: 244;
    --accent-g: 114;
    --accent-b: 182;
  }

  html, body {
    min-height: 100%;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
  }

  body::before {
    content: "";
    position: fixed;
    width: 700px; height: 700px;
    top: -250px; left: -200px;
    border-radius: 50%;
    filter: blur(130px);
    pointer-events: none;
    z-index: 0;
    background: radial-gradient(circle, rgba(244,114,182,0.07) 0%, transparent 70%);
  }
  body::after {
    content: "";
    position: fixed;
    width: 500px; height: 500px;
    bottom: -150px; right: -100px;
    border-radius: 50%;
    filter: blur(120px);
    pointer-events: none;
    z-index: 0;
    background: radial-gradient(circle, rgba(167,139,250,0.07) 0%, transparent 70%);
  }

  .page {
    position: relative;
    z-index: 1;
    max-width: 1700px;
    margin: 0 auto;
    padding: 48px 28px 64px;
  }

  /* ── Header ── */
  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 48px;
    flex-wrap: wrap;
    gap: 16px;
    animation: fadeDown 0.5s ease both;
  }

  .wordmark {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .logo-hex {
    width: 40px; height: 40px;
    background: linear-gradient(135deg, #f472b6, #a78bfa);
    clip-path: polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 17px;
    font-weight: 800;
    color: #fff;
    flex-shrink: 0;
  }

  .brand {
    display: flex;
    flex-direction: column;
  }

  .brand-name {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: var(--muted);
  }

  .page-title {
    font-size: 22px;
    font-weight: 700;
    letter-spacing: -0.5px;
    background: linear-gradient(90deg, #f472b6, #c084fc);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }

  .hub-link {
    font-size: 12px;
    color: var(--muted);
    text-decoration: none;
    display: flex;
    align-items: center;
    gap: 6px;
    border: 1px solid var(--border);
    background: var(--surface);
    padding: 7px 14px;
    border-radius: 8px;
    transition: border-color 0.2s, color 0.2s;
  }
  .hub-link:hover { border-color: rgba(244,114,182,0.3); color: var(--text); }

  /* ── Stats strip ── */
  .stats-strip {
    display: flex;
    gap: 16px;
    margin-bottom: 28px;
    flex-wrap: wrap;
    animation: fadeUp 0.4s 0.1s ease both;
  }

  .stat-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px 20px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex: 1;
    min-width: 120px;
  }

  .stat-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--muted);
  }

  .stat-value {
    font-size: 24px;
    font-weight: 700;
    color: #f1f5f9;
    font-variant-numeric: tabular-nums;
  }

  .stat-sub {
    font-size: 11px;
    color: var(--muted);
  }

  /* ── Toolbar ── */
  .toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
    flex-wrap: wrap;
    animation: fadeUp 0.4s 0.15s ease both;
  }

  .search-wrap {
    position: relative;
    flex: 1;
    min-width: 220px;
  }

  .search-wrap svg {
    position: absolute;
    left: 12px; top: 50%;
    transform: translateY(-50%);
    width: 15px; height: 15px;
    stroke: var(--muted);
    fill: none;
    stroke-width: 2;
    stroke-linecap: round;
    pointer-events: none;
  }

  .search-input {
    width: 100%;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    color: var(--text);
    font-size: 13px;
    padding: 10px 12px 10px 36px;
    outline: none;
    transition: border-color 0.2s;
  }

  .search-input:focus { border-color: rgba(244,114,182,0.4); }
  .search-input::placeholder { color: var(--muted); }

  .filter-chips {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }

  .chip {
    padding: 7px 16px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--muted);
    cursor: pointer;
    transition: all 0.2s;
  }

  .chip:hover { color: var(--text); border-color: rgba(244,114,182,0.25); }
  .chip.active         { background: rgba(244,114,182,0.12); border-color: rgba(244,114,182,0.35); color: #f472b6; }
  .chip.c-yes.active   { background: rgba(74,222,128,0.12);  border-color: rgba(74,222,128,0.35);  color: #4ade80; }
  .chip.c-part.active  { background: rgba(251,191,36,0.12);  border-color: rgba(251,191,36,0.35);  color: #fbbf24; }
  .chip.c-no.active    { background: rgba(239,68,68,0.12);   border-color: rgba(239,68,68,0.35);   color: #ef4444; }

  .count-tag {
    font-size: 12px;
    color: var(--muted);
    white-space: nowrap;
    margin-left: auto;
  }

  /* ── Table ── */
  .table-wrap {
    border-radius: 14px;
    border: 1px solid var(--border);
    background: var(--surface);
    overflow-x: auto;
    animation: fadeUp 0.4s 0.2s ease both;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }

  thead th {
    background: var(--surface2);
    color: var(--muted);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    padding: 11px 12px;
    text-align: left;
    white-space: nowrap;
    cursor: pointer;
    user-select: none;
    border-bottom: 1px solid var(--border);
    transition: color 0.2s;
    position: sticky;
    top: 0;
    z-index: 1;
  }

  thead th:hover { color: var(--text); }
  thead th .si { display: inline-block; margin-left: 4px; opacity: 0.3; font-size: 9px; }
  thead th.asc  .si::after { content: " \25B2"; opacity: 1; }
  thead th.desc .si::after { content: " \25BC"; opacity: 1; }
  thead th:not(.asc):not(.desc) .si::after { content: " \21C5"; }

  tbody tr { border-bottom: 1px solid var(--border); transition: background 0.15s; }
  tbody tr:last-child { border-bottom: none; }
  tbody tr:hover { background: rgba(255,255,255,0.025); }
  tbody td { padding: 10px 12px; vertical-align: middle; }

  tbody tr.row-activated {
    background: rgba(244,114,182,0.06);
    border-left: 3px solid rgba(244,114,182,0.6);
  }
  tbody tr.row-activated:hover { background: rgba(244,114,182,0.1); }
  tbody tr.row-activated td:first-child .game-name { color: #f472b6; }

  .game-name { font-weight: 600; color: #f1f5f9; white-space: nowrap; }

  .tier-badge {
    display: inline-block;
    padding: 3px 9px;
    border-radius: 6px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.5px;
    white-space: nowrap;
  }
  .t1  { background: rgba(56,189,248,0.12);  color: #38bdf8; border: 1px solid rgba(56,189,248,0.25); }
  .t2  { background: rgba(167,139,250,0.12); color: #a78bfa; border: 1px solid rgba(167,139,250,0.25); }
  .t3  { background: rgba(100,116,139,0.12); color: #94a3b8; border: 1px solid rgba(100,116,139,0.2); }
  .tai { background: rgba(34,211,238,0.12);  color: #22d3ee; border: 1px solid rgba(34,211,238,0.25); }

  .hl-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 600;
    white-space: nowrap;
  }
  .hl-badge::before { content: ""; width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
  .hl-yes     { background: rgba(74,222,128,0.1);  color: #4ade80; border: 1px solid rgba(74,222,128,0.25); }
  .hl-yes::before     { background: #4ade80; box-shadow: 0 0 4px rgba(74,222,128,0.6); }
  .hl-partial { background: rgba(251,191,36,0.1);  color: #fbbf24; border: 1px solid rgba(251,191,36,0.25); }
  .hl-partial::before { background: #fbbf24; }
  .hl-no      { background: rgba(239,68,68,0.1);   color: #ef4444; border: 1px solid rgba(239,68,68,0.2); }
  .hl-no::before      { background: #ef4444; }

  .diff-badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 600;
  }
  .d-easy       { background: rgba(74,222,128,0.1);  color: #4ade80; }
  .d-medium     { background: rgba(251,191,36,0.1);  color: #fbbf24; }
  .d-hard       { background: rgba(239,68,68,0.1);   color: #ef4444; }
  .d-impossible { background: rgba(100,116,139,0.1); color: #64748b; }

  .spec-val  { font-variant-numeric: tabular-nums; color: #cbd5e1; white-space: nowrap; }
  .spec-zero { color: #4ade80; font-weight: 600; }

  .method-text { color: #94a3b8; font-size: 12px; max-width: 170px; }

  .lang-tag {
    display: inline-block;
    background: rgba(255,255,255,0.05);
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 2px 8px;
    font-size: 11px;
    color: #94a3b8;
    font-family: "SF Mono", "Fira Code", monospace;
    white-space: nowrap;
  }

  .pop-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 600;
    white-space: nowrap;
  }
  .pop-massive   { background: rgba(251,191,36,0.13);  color: #fbbf24; border: 1px solid rgba(251,191,36,0.3);  }
  .pop-very-high { background: rgba(251,146,60,0.12);  color: #fb923c; border: 1px solid rgba(251,146,60,0.28); }
  .pop-high      { background: rgba(74,222,128,0.11);  color: #4ade80; border: 1px solid rgba(74,222,128,0.25); }
  .pop-medium    { background: rgba(56,189,248,0.11);  color: #38bdf8; border: 1px solid rgba(56,189,248,0.25); }
  .pop-low       { background: rgba(148,163,184,0.1);  color: #94a3b8; border: 1px solid rgba(148,163,184,0.2); }
  .pop-niche     { background: rgba(71,85,105,0.15);   color: #64748b; border: 1px solid rgba(71,85,105,0.25);  }

  .pop-dot {
    width: 5px; height: 5px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .pop-massive   .pop-dot { background: #fbbf24; box-shadow: 0 0 4px rgba(251,191,36,0.7); }
  .pop-very-high .pop-dot { background: #fb923c; box-shadow: 0 0 4px rgba(251,146,60,0.6); }
  .pop-high      .pop-dot { background: #4ade80; }
  .pop-medium    .pop-dot { background: #38bdf8; }
  .pop-low       .pop-dot { background: #94a3b8; }
  .pop-niche     .pop-dot { background: #475569; }

  .empty-row td {
    text-align: center;
    padding: 60px 20px;
    color: var(--muted);
  }

"""
