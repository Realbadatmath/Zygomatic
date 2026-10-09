# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GUI markup, part 1: document head and the first half of the stylesheet.

Moved verbatim out of medusa_server.py (lines 70-465); reassembled in html.py.
"""

# ─────────────────────────────────────────────────────────────────────────────
# Single-page GUI. Left sidebar = tabs (first is "Medusa"), right = panels.
# Live tabs: Medusa, Inspection, Training, Resources. tab4-tab6 are still empty
# scaffold panels.
# NOTE: plain string (NOT an f-string) so the CSS { } braces stay literal.
# ─────────────────────────────────────────────────────────────────────────────
HEAD_CSS = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Medusa</title>
<link rel="icon" type="image/png" href="/favicon.png">
<link rel="apple-touch-icon" href="/favicon.png">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:        #07070f;
    --surface:   #0e0e1a;
    --panel:     #0b0b14;
    --border:    rgba(255,255,255,0.07);
    --text:      #e2e8f0;
    --muted:     #64748b;
    --accent:    #10b981;   /* emerald — Medusa */
    --accent-2:  #34d399;
    --accent-rgb: 16, 185, 129;
  }

  html, body {
    height: 100%;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
  }

  .app {
    display: grid;
    grid-template-columns: 220px 1fr;
    height: calc(100vh / var(--ui-zoom,1));
    overflow: hidden;
  }

  /* ── Sidebar ── */
  .sidebar {
    position: relative;
    background: var(--surface);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    padding: 20px 14px;
    z-index: 1;
  }

  .brand {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 4px 8px 20px;
    margin-bottom: 6px;
    border-bottom: 1px solid var(--border);
  }

  .logo-hex {
    width: 40px; height: 40px;
    background: linear-gradient(135deg, var(--accent), var(--accent-2));
    clip-path: polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  .logo-hex img {
    width: 35px; height: 35px;
    object-fit: cover;
    clip-path: polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%);
    display: block;
  }

  .brand-name {
    font-size: 18px;
    font-weight: 700;
    letter-spacing: 2.5px;
    text-transform: uppercase;
    background: linear-gradient(90deg, var(--accent), var(--accent-2));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }

  /* ── Tab list ── */
  .tabs {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-top: 14px;
    flex: 1;
    overflow-y: auto;
  }

  .tab {
    position: relative;
    text-align: left;
    width: 100%;
    padding: 11px 14px;
    border: none;
    border-radius: 9px;
    background: transparent;
    color: var(--muted);
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 0.3px;
    cursor: pointer;
    font-family: inherit;
    transition: background 0.18s ease, color 0.18s ease;
  }

  .tab:hover {
    background: rgba(255,255,255,0.03);
    color: var(--text);
  }

  .tab.active {
    background: rgba(var(--accent-rgb), 0.12);
    color: var(--accent-2);
  }

  .tab.active::before {
    content: "";
    position: absolute;
    left: 0; top: 50%;
    transform: translateY(-50%);
    width: 3px; height: 20px;
    border-radius: 0 3px 3px 0;
    background: var(--accent);
  }

  .sidebar-footer {
    padding: 14px 8px 2px;
    border-top: 1px solid var(--border);
    color: #1e293b;
    font-size: 10.5px;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    font-variant-numeric: tabular-nums;
  }

  /* ── Content ── */
  .content {
    position: relative;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .content::before {
    content: "";
    position: absolute;
    inset: 0;
    background:
      radial-gradient(ellipse at top left, rgba(var(--accent-rgb),0.05) 0%, transparent 55%);
    pointer-events: none;
    z-index: 0;
  }

  .content-header {
    position: relative;
    z-index: 1;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 20px 28px;
    border-bottom: 1px solid var(--border);
  }

  .content-title {
    font-size: 16px;
    font-weight: 700;
    letter-spacing: 0.4px;
    color: #f1f5f9;
  }
  .content-title .dot {
    display: inline-block;
    width: 7px; height: 7px;
    border-radius: 50%;
    background: var(--accent);
    box-shadow: 0 0 8px rgba(var(--accent-rgb),0.7);
    margin-right: 9px;
    vertical-align: middle;
  }

  .panels {
    position: relative;
    z-index: 1;
    flex: 1;
    overflow: auto;
  }

  /* Each tab's content lives here. Empty for now (scaffold). */
  .panel { display: none; height: 100%; padding: 28px; }
  .panel.active { display: block; }

  /* ── Vicky (tab4): Medusa's own chat assistant ── */
  /* Scoped to the panel's own child on purpose: an unscoped `.vicky` also
     matches every `.vicky-msg.vicky` answer bubble, which inherited its
     `height: 100%` and `display: flex` and so rendered ~940px tall with one
     line of text in it. (Pre-existing; found 2026-09-17 when the per-message
     engine label made the empty box obvious.) */
  section[data-panel="tab4"] > .vicky { max-width: 820px; height: 100%; display: flex; flex-direction: column; }
  .vicky-log { flex: 1; overflow-y: auto; border: 1px solid var(--border); border-radius: 10px;
              background: var(--panel); padding: 16px; display: flex; flex-direction: column; gap: 12px; }
  .vicky-msg { max-width: 88%; padding: 10px 13px; border-radius: 10px; font-size: 13.5px; line-height: 1.5; white-space: pre-wrap; }
  .vicky-msg.user { align-self: flex-end; background: rgba(var(--accent-rgb),0.14); color: var(--text); }
  .vicky-msg.vicky { align-self: flex-start; background: rgba(255,255,255,0.04); color: var(--text); border: 1px solid var(--border); }
  .vicky-msg.error { align-self: flex-start; background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.35); color: #fca5a5; }
  .vicky-msg .vicky-think { font-size: 12px; color: var(--muted); font-style: italic; margin-bottom: 6px; white-space: pre-wrap; }
  .vicky-msg .vicky-log-line { font-size: 11.5px; color: var(--muted); font-variant-numeric: tabular-nums; }
  .vchat-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
  .vchat-select { flex: 1; min-width: 200px; max-width: 420px; padding: 7px 10px; border-radius: 8px;
                  border: 1px solid var(--border); background: var(--panel); color: var(--text);
                  font-size: 12.5px; font-family: inherit; }
  .vchat-select:focus { outline: none; border-color: var(--accent); }
  .vchat-btn { padding: 6px 12px; border-radius: 8px; border: 1px solid var(--border); background: transparent;
               color: var(--muted); font-size: 12px; font-weight: 600; cursor: pointer; font-family: inherit; }
  .vchat-btn:hover { color: var(--text); border-color: var(--accent); }
  .vchat-btn.danger:hover { color: #fca5a5; border-color: rgba(239,68,68,0.5); }
  .vchat-meta { font-size: 11px; color: var(--muted); margin-left: auto; white-space: nowrap; }
  /* The Pictures gallery: every picture any chat delivered, in one grid. A
     picture otherwise lives in one bubble behind the chat dropdown, which is
     where "the pictures are gone" came from - they were there, one chat each. */
  .vchat-btn.on { color: var(--accent); border-color: var(--accent); background: rgba(var(--accent-rgb),0.10); }
  .vicky-gallery { flex: 1; overflow-y: auto; border: 1px solid var(--border); border-radius: 10px;
                   background: var(--panel); padding: 16px; }
  .vicky-gallery[hidden] { display: none; }
  /* `hidden` loses to a class that sets display, so both views spell it out.
     The gallery also lifts the chat column's 820px cap while it is open:
     a grid of pictures wants the width a transcript does not. */
  .vicky-log[hidden] { display: none; }
  section[data-panel="tab4"] > .vicky.wide { max-width: none; }
  .vicky-gallery-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 12px;
                        font-size: 12.5px; color: var(--muted); }
  .vicky-gallery-head b { color: var(--text); }
  .vicky-gallery-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
  .vicky-pic { border: 1px solid var(--border); border-radius: 8px; background: var(--surface);
               overflow: hidden; display: flex; flex-direction: column; }
  .vicky-pic a.pic { display: block; aspect-ratio: 16 / 9; background: #000; }
  .vicky-pic img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .vicky-pic.gone a.pic { display: flex; align-items: center; justify-content: center;
                          color: #fca5a5; font-size: 12px; }
  .vicky-pic .cap { padding: 7px 9px; font-size: 11.5px; line-height: 1.4; color: var(--muted);
                    overflow-wrap: anywhere; }
  .vicky-pic .cap .t { color: var(--text); font-weight: 600; display: block; }
  .vicky-pic .cap .p { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
                       margin-top: 2px; font-style: italic; }
  .vicky-pic .cap .row { display: flex; gap: 8px; margin-top: 5px; align-items: center; }
  .vicky-pic .cap button { padding: 3px 8px; font-size: 11px; }
  .vicky-pic .cap .when { margin-left: auto; font-variant-numeric: tabular-nums; white-space: nowrap; }
  /* The model switcher. Deliberately the FIRST control in the bar and its own
     colour: which assistant answers changes what the reply costs and what it
     remembers, so it should not read as one more chat-management button. */
  .vchat-engine { flex: 0 0 auto; min-width: 190px; padding: 7px 10px; border-radius: 8px;
                  border: 1px solid rgba(var(--accent-rgb),0.45); background: rgba(var(--accent-rgb),0.10);
                  color: var(--text); font-family: inherit; font-size: 12.5px; font-weight: 600; }
  .vchat-engine:focus { outline: none; border-color: var(--accent); }
  .vchat-engine.offline { border-color: rgba(239,68,68,0.5); background: rgba(239,68,68,0.08); }
  .vicky-msg .vicky-who { font-size: 11px; font-weight: 700; letter-spacing: 0.4px;
                          text-transform: uppercase; color: var(--muted); }
  .vicky-msg.local .vicky-who { color: var(--accent-2); }
  /* Every bubble carries the time it was written. The head row exists even on a
     user bubble, which has no speaker label - the clock is the whole point of
     it there, so it is pushed right by the empty label rather than by a rule
     that only applies to one side. */
  .vicky-msg .vicky-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 5px; }
  .vicky-msg .vicky-time { margin-left: auto; font-size: 10.5px; color: var(--muted);
                           font-variant-numeric: tabular-nums; white-space: nowrap; opacity: 0.8; }
  /* A finished render comes back INTO the chat. The thumbnail is a link to the
     full file, so a click opens the real pixels rather than this scaled copy. */
  /* Sized at the operator's own 67% page zoom, where a 260px thumbnail read as
     a 174px stamp - the picture is the answer to the message, so it gets the
     width of the bubble it arrives in. */
  .vicky-msg .msg-shots { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
  .vicky-msg .msg-shot { display: block; width: 100%; max-width: 560px; max-height: 620px;
                         border-radius: 6px; border: 1px solid var(--border); background: var(--surface); }
  .vicky-msg .msg-shot-cap { font-size: 10.5px; color: var(--muted); margin-top: 3px;
                             max-width: 560px; overflow-wrap: anywhere; }
  .vicky-msg .vicky-meta { font-size: 11px; color: var(--muted); margin-top: 6px; font-variant-numeric: tabular-nums; }
  .vicky-empty { align-self: center; color: var(--muted); font-size: 13px; padding: 24px 0; text-align: center; line-height: 1.6; }
  .vicky-row { display: flex; gap: 8px; margin-top: 12px; }
  .vicky-input { flex: 1; resize: none; min-height: 44px; max-height: 160px; padding: 10px 12px; border-radius: 8px;
                border: 1px solid var(--border); background: var(--surface); color: var(--text); font-size: 13.5px;
                font-family: inherit; }
  .vicky-input:focus { outline: none; border-color: var(--accent); }
  .vicky-send, .vicky-cancel { padding: 0 18px; border: none; border-radius: 8px; font-size: 13px; font-weight: 700;
                               font-family: inherit; cursor: pointer; }
  .vicky-send { background: var(--accent); color: #052e1e; }
  .vicky-send:disabled { opacity: 0.5; cursor: default; }
  .vicky-cancel { background: rgba(239,68,68,0.15); color: #fca5a5; border: 1px solid rgba(239,68,68,0.35); display: none; }
  .vicky-attach { width: 44px; min-height: 44px; padding: 0; border: 1px solid var(--border);
                  border-radius: 8px; background: transparent; color: var(--muted);
                  cursor: pointer; flex-shrink: 0; display: inline-flex;
                  align-items: center; justify-content: center; }
  .vicky-attach svg { display: block; }
  .vicky-attach:hover { color: var(--text); border-color: var(--accent); }
  .vicky-previews { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; min-height: 0; }
  .vicky-previews:empty { display: none; }
  .vp-item { position: relative; display: inline-flex; }
  .vp-img { width: 64px; height: 64px; object-fit: cover; border-radius: 6px;
            border: 1px solid var(--border); display: block; }
  .vp-pill { display: flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 6px;
             border: 1px solid var(--border); background: rgba(255,255,255,0.04);
             font-size: 12px; color: var(--muted); max-width: 220px;
             overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .vp-remove { position: absolute; top: -5px; right: -5px; width: 17px; height: 17px; border-radius: 50%;
               background: rgba(239,68,68,0.85); border: none; color: #fff; font-size: 11px;
               cursor: pointer; display: flex; align-items: center; justify-content: center;
               padding: 0; line-height: 1; font-family: inherit; }
  .vicky-msg.user .msg-thumbs { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 6px; }
  .vicky-msg.user .msg-thumb { max-width: 140px; max-height: 105px; border-radius: 5px;
                               object-fit: cover; display: block; }
  .vicky-msg.user .msg-pill { font-size: 11px; color: var(--muted); padding: 2px 8px;
                              border-radius: 4px; background: rgba(255,255,255,0.06);
                              border: 1px solid var(--border); display: inline-block; }

  /* ── Character Studio (Medusa tab) ── */
  .studio { max-width: 720px; }
  .studio-title { font-size: 20px; font-weight: 700; margin-bottom: 8px; color: #f1f5f9; }
  .studio-sub { font-size: 13px; color: var(--muted); line-height: 1.5; margin-bottom: 22px; }
  .studio-sub strong { color: var(--accent-2); }
  .studio-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px 18px; margin-bottom: 20px; }
  .studio-grid label { display: flex; flex-direction: column; gap: 6px; font-size: 12px; font-weight: 600; color: var(--text); letter-spacing: 0.3px; }
  .studio-grid .opt { color: var(--muted); font-weight: 500; }
  .studio-grid input, .studio-grid select {
    padding: 9px 11px; border-radius: 8px; border: 1px solid var(--border);
    background: var(--panel); color: var(--text); font-size: 13px; font-family: inherit;
  }
  .studio-grid input:focus, .studio-grid select:focus { outline: none; border-color: var(--accent); }
  .studio-prompt-label { display: flex; flex-direction: column; gap: 6px; font-size: 12px; font-weight: 600; color: var(--text); letter-spacing: 0.3px; margin-bottom: 20px; }
  .studio-prompt { width: 100%; min-height: 96px; resize: vertical; padding: 10px 12px; border-radius: 8px; border: 1px solid var(--border); background: var(--panel); color: var(--text); font-size: 13px; font-family: inherit; line-height: 1.5; }
  .studio-prompt:focus { outline: none; border-color: var(--accent); }
  .studio-actions { display: flex; align-items: center; gap: 14px; margin-bottom: 18px; }
  .btn-primary {
    padding: 11px 22px; border: none; border-radius: 9px; cursor: pointer;
    background: linear-gradient(90deg, var(--accent), var(--accent-2));
    color: #04140d; font-size: 14px; font-weight: 700; font-family: inherit; letter-spacing: 0.3px;
  }
  .btn-primary:disabled { opacity: 0.5; cursor: default; }
  .studio-note { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.6px; }
  .studio-result { font-size: 13px; line-height: 1.5; color: var(--muted); min-height: 20px; padding: 12px 14px; border-radius: 8px; border: 1px solid transparent; }
  .studio-result.good { color: #a7f3d0; background: rgba(16,185,129,0.08); border-color: rgba(16,185,129,0.25); }
  .studio-result.bad { color: #fca5a5; background: rgba(239,68,68,0.08); border-color: rgba(239,68,68,0.25); }

  /* ── Angle picker (how many angles, and which) ── */
  .ang-box { border: 1px solid var(--border); border-radius: 10px; background: rgba(255,255,255,0.015); padding: 14px 16px; margin-bottom: 20px; }
  .ang-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 4px; }
  .ang-title { font-size: 12px; font-weight: 700; color: var(--text); letter-spacing: 0.3px; }
  .ang-count { font-size: 12px; font-weight: 700; color: var(--accent-2); white-space: nowrap; }
  .ang-count.warn { color: #fbbf24; }
  .ang-sub { font-size: 12px; color: var(--muted); line-height: 1.5; margin: 6px 0 12px; }
  .ang-presets { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
  .ang-preset { padding: 5px 12px; border-radius: 999px; border: 1px solid var(--border); background: transparent;
                color: var(--muted); font-size: 12px; font-weight: 600; cursor: pointer; font-family: inherit; }
  .ang-preset:hover { color: var(--text); border-color: var(--accent); }
  .ang-preset.on { color: #04140d; background: var(--accent); border-color: var(--accent); }
  .ang-toggle { margin-left: auto; }
  .ang-groups { display: none; flex-direction: column; gap: 4px; border-top: 1px solid var(--border); padding-top: 10px; }
  .ang-groups.open { display: flex; }
  .ang-group { border-bottom: 1px solid var(--border); padding: 8px 0; }
  .ang-group:last-child { border-bottom: none; }
  .ang-group-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
  .ang-group-name { font-size: 12px; font-weight: 700; color: var(--text); }
  .ang-group-name span { color: var(--muted); font-weight: 500; margin-left: 6px; }
  .ang-group-all { padding: 3px 10px; border-radius: 6px; border: 1px solid var(--border); background: transparent;
                   color: var(--muted); font-size: 11px; font-weight: 600; cursor: pointer; font-family: inherit; }
  .ang-group-all:hover { color: var(--text); border-color: var(--accent); }
  .ang-cells { display: grid; grid-template-columns: 1fr 1fr; gap: 2px 16px; margin-top: 6px; }
  .ang-cell { display: flex; align-items: flex-start; gap: 8px; font-size: 12px; color: var(--muted);
              line-height: 1.45; padding: 3px 0; cursor: pointer; font-weight: 500; }
  .ang-cell:hover { color: var(--text); }
  .ang-cell input { margin: 2px 0 0; accent-color: var(--accent); flex: none; }
  /* The anchor is tickable like any other — it is simply re-added first when
     the operator leaves it out, so it is marked, never disabled. */
  .ang-cell.anchor { color: var(--text); }
  .ang-cell.anchor .ang-id { color: var(--accent); }
  .ang-cell .ang-id { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--accent-2);
                      font-size: 11px; flex: none; min-width: 18px; }
  .ang-err { font-size: 12px; color: #fca5a5; }

  /* ── Operator approval queue ── */
  .studio-approvals { max-width: 720px; margin-top: 34px; border-top: 1px solid var(--border); padding-top: 20px; }
  .appr-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
  .appr-title { font-size: 15px; font-weight: 700; color: #f1f5f9; }
  .btn-ghost { padding: 6px 14px; border-radius: 8px; border: 1px solid var(--border); background: transparent; color: var(--muted); font-size: 12px; font-weight: 600; cursor: pointer; font-family: inherit; }
  .btn-ghost:hover { color: var(--text); border-color: var(--accent); }
  .appr-list { display: flex; flex-direction: column; gap: 8px; }
  .appr-empty { font-size: 13px; color: var(--muted); padding: 8px 0; }
  .appr-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 14px; border-radius: 8px; border: 1px solid var(--border); background: var(--panel); }
  .appr-label { font-size: 13px; color: var(--text); }
  .appr-actions { display: flex; gap: 8px; flex-shrink: 0; }
  .btn-appr { padding: 6px 14px; border: none; border-radius: 7px; cursor: pointer; background: var(--accent); color: #04140d; font-size: 12px; font-weight: 700; font-family: inherit; }
  .btn-decline { padding: 6px 14px; border: 1px solid var(--border); border-radius: 7px; cursor: pointer; background: transparent; color: var(--muted); font-size: 12px; font-weight: 600; font-family: inherit; }
  .btn-decline:hover { color: #fca5a5; border-color: rgba(239,68,68,0.4); }

"""
