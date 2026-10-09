# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GUI markup, part 2: the per-panel half of the stylesheet.

Moved verbatim out of medusa_server.py (lines 466-825); reassembled in html.py.
"""

CSS_PANELS = """  /* ── Inspection tab: sub-tabs over the :8899 SPA and the local sheet browser.
     The Contact Sheet sub-tab is deliberately NOT part of the :8899 inspection
     SPA — that server is unauthenticated and walks the shared storyteller
     character tree. Rendering sheets here keeps them on Medusa's own origin,
     fed only by the isolated /api/medusa/training/* endpoints. ── */
  /* MUST stay scoped to .active — a bare `.panel-inspection { display:flex }`
     sits after `.panel { display:none }` and so wins for EVERY tab, leaving the
     Inspection panel painted permanently over whichever tab is selected. */
  .panel-inspection { padding: 0; }
  .panel-inspection.active { display: flex; flex-direction: column; }
  .subtabs { display: flex; gap: 4px; padding: 10px 16px 0; border-bottom: 1px solid var(--border); flex-shrink: 0; background: var(--panel); }
  .subtab { padding: 8px 16px; border: none; background: transparent; color: var(--muted); font-size: 13px; font-weight: 600; font-family: inherit; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; }
  .subtab:hover { color: var(--text); }
  .subtab.active { color: var(--accent-2); border-bottom-color: var(--accent); }
  .subpanel { display: none; flex: 1; min-height: 0; overflow: auto; }
  .subpanel.active { display: block; }
  .subpanel[data-subpanel="inspections"].active { display: flex; }
  #insp-frame { width: 100%; height: 100%; border: none; display: block; background: #0e1014; flex: 1; }

  /* ── Contact Sheet browser ── */
  .cs-wrap { padding: 22px 26px; }
  .cs-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
  .cs-head .train-sub { max-width: 620px; margin-bottom: 14px; }
  .cs-head-actions { display: flex; gap: 8px; flex-shrink: 0; }
  .cs-list { display: flex; flex-direction: column; gap: 16px; margin-top: 10px; }
  .cs-card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; }
  .cs-card-h { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 10px; }
  .cs-name { font-size: 14px; font-weight: 700; color: #f1f5f9; }
  .cs-meta { font-size: 11px; color: var(--muted); font-family: ui-monospace, monospace; }
  .cs-spacer { flex: 1; }
  .cs-cov { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 10px; }
  .cs-chip { font-size: 11px; padding: 3px 9px; border-radius: 999px; border: 1px solid var(--border); color: var(--muted); }
  .cs-chip.have { color: #a7f3d0; border-color: rgba(16,185,129,0.4); background: rgba(16,185,129,0.08); }
  .cs-chip.miss { color: #fca5a5; border-color: rgba(239,68,68,0.35); background: rgba(239,68,68,0.06); }
  .cs-chip.warn { color: #fbbf24; border-color: rgba(251,191,36,0.35); background: rgba(251,191,36,0.06); }
  .cs-pages { display: flex; flex-direction: column; gap: 10px; }
  .cs-pages img { width: 100%; border-radius: 8px; border: 1px solid var(--border); display: block; background: var(--bg); }
  .cs-bar { width: 100%; height: 6px; border-radius: 4px; background: #1c1c2a; overflow: hidden; margin: 6px 0 10px; }
  .cs-bar-fill { height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); transition: width 0.3s ease; }
  .cs-empty { font-size: 13px; color: var(--muted); }

  /* ── Trained LoRA browser (Inspection > LoRA) ── */
  .lr-state { font-size: 10px; font-weight: 800; letter-spacing: 0.6px; text-transform: uppercase; padding: 3px 9px; border-radius: 999px; border: 1px solid var(--border); color: var(--muted); }
  .lr-state.ready { color: #a7f3d0; border-color: rgba(16,185,129,0.45); background: rgba(16,185,129,0.10); }
  .lr-state.running { color: #fbbf24; border-color: rgba(251,191,36,0.4); background: rgba(251,191,36,0.07); }
  .lr-state.failed { color: #fca5a5; border-color: rgba(239,68,68,0.4); background: rgba(239,68,68,0.07); }
  .lr-fam { font-size: 10px; font-weight: 800; letter-spacing: 0.6px; text-transform: uppercase; padding: 3px 9px; border-radius: 6px; color: var(--accent-2); border: 1px solid rgba(16,185,129,0.35); background: rgba(16,185,129,0.07); }
  .lr-path { font-size: 11px; font-family: ui-monospace, monospace; color: var(--muted); word-break: break-all; margin: 8px 0 10px; user-select: all; }
  .lr-samples { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
  .lr-samples figure { margin: 0; }
  .lr-samples img { width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 8px; border: 1px solid var(--border); display: block; background: var(--bg); cursor: zoom-in; }
  .lr-samples figcaption { font-size: 10px; color: var(--muted); font-family: ui-monospace, monospace; margin-top: 4px; }

  /* .sec-status is a small shared status-text style, also used by the Training
     tab's upload-status indicator below (kept on removal of the Security tab
     2026-08-06 — the rest of that tab's config-editor CSS was Security-only). */
  .sec-status { font-size: 12px; color: var(--muted); }
  .sec-status.ok { color: #a7f3d0; }
  .sec-status.err { color: #fca5a5; }

  /* ── Training tab (upload-your-own-photos LoRA training) ── */
  .train { max-width: 860px; }
  .train-title { font-size: 20px; font-weight: 700; margin-bottom: 8px; color: #f1f5f9; }
  .train-sub { font-size: 13px; color: var(--muted); line-height: 1.5; margin-bottom: 22px; }
  .train-sub strong { color: var(--accent-2); }
  .train-sub code { color: var(--accent-2); background: rgba(16,185,129,0.08); padding: 1px 5px; border-radius: 4px; font-size: 12px; }
  .train-card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 18px; margin-bottom: 18px; }
  .train-card-h { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
  .train-card-h h3 { font-size: 15px; font-weight: 700; color: #f1f5f9; }
  .train-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px 18px; margin-bottom: 16px; }
  .train-grid label { display: flex; flex-direction: column; gap: 6px; font-size: 12px; font-weight: 600; color: var(--text); letter-spacing: 0.3px; }
  .train-grid .opt { color: var(--muted); font-weight: 500; }
  .train-grid input, .train-grid select {
    padding: 9px 11px; border-radius: 8px; border: 1px solid var(--border);
    background: var(--bg); color: var(--text); font-size: 13px; font-family: inherit;
  }
  .train-grid input:focus, .train-grid select:focus { outline: none; border-color: var(--accent); }
  .train-list { display: flex; flex-direction: column; gap: 14px; }
  .train-empty { font-size: 13px; color: var(--muted); padding: 8px 0; }
  .train-char-card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; }
  .train-char-h { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
  .train-char-name { font-size: 14px; font-weight: 700; color: #f1f5f9; }
  .train-char-meta { font-size: 11px; color: var(--muted); font-family: ui-monospace, monospace; }
  .train-char-status { font-size: 12px; color: var(--muted); }
  .train-char-status.running { color: #fbbf24; }
  .train-char-status.done { color: #a7f3d0; }
  .train-char-status.error { color: #fca5a5; }
  .train-char-spacer { flex: 1; }
  .train-gallery { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
  .train-thumb { position: relative; width: 64px; height: 64px; border-radius: 7px; overflow: hidden; border: 1px solid var(--border); background: var(--bg); }
  .train-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .train-thumb button { position: absolute; top: 2px; right: 2px; width: 18px; height: 18px; border: none; border-radius: 50%; background: rgba(0,0,0,0.6); color: #fca5a5; font-size: 11px; line-height: 1; cursor: pointer; }
  .train-thumb-add { display: flex; align-items: center; justify-content: center; width: 64px; height: 64px; border-radius: 7px; border: 1px dashed var(--border); color: var(--muted); font-size: 22px; cursor: pointer; background: transparent; }
  .train-thumb-add:hover { border-color: var(--accent); color: var(--accent-2); }
  .train-progress-track { width: 100%; height: 6px; border-radius: 4px; background: #1c1c2a; overflow: hidden; margin: 8px 0; }
  .train-progress-fill { height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); transition: width 0.3s ease; }
  .train-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .train-hint { font-size: 12px; color: var(--muted); line-height: 1.55; margin-bottom: 14px; }
  .train-hint em { color: var(--accent-2); font-style: normal; font-weight: 600; }
  .train-scan-row { display: flex; gap: 8px; margin-bottom: 12px; }
  .train-scan-row input {
    flex: 1; padding: 9px 11px; border-radius: 8px; border: 1px solid var(--border);
    background: var(--bg); color: var(--text); font-size: 13px; font-family: ui-monospace, monospace;
  }
  .train-scan-row input:focus { outline: none; border-color: var(--accent); }
  .train-scan-list { display: flex; flex-direction: column; gap: 4px; margin: 10px 0; max-height: 320px; overflow-y: auto; }
  .train-scan-item { display: flex; flex-direction: column; gap: 6px; padding: 8px 10px; border-radius: 7px; background: var(--bg); border: 1px solid var(--border); font-size: 13px; }
  .t-scan-head { display: flex; align-items: center; gap: 10px; }
  .t-scan-mode { display: flex; gap: 16px; flex-wrap: wrap; padding-left: 22px; }
  .t-scan-mode label { display: flex; align-items: center; gap: 5px; font-size: 12px; color: var(--muted); cursor: pointer; }
  .t-scan-mode input { cursor: pointer; }
  .t-promptables { margin-left: 22px; padding: 7px 9px; border-radius: 7px; border: 1px solid rgba(239,68,68,0.4); background: var(--bg); color: var(--text); font-size: 12px; font-family: inherit; }
  .cs-mode-badge { font-size: 10px; padding: 2px 8px; border-radius: 999px; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 700; }
  .cs-mode-badge.identity { color: #a7f3d0; background: rgba(16,185,129,0.12); }
  .cs-mode-badge.body { color: #c4b5fd; background: rgba(139,92,246,0.15); }
  .train-scan-item .nm { flex: 1; color: var(--text); font-weight: 600; }
  .train-scan-item .ct { color: var(--muted); font-size: 12px; font-family: ui-monospace, monospace; }
  .train-inline { display: flex; align-items: center; gap: 7px; font-size: 12px; font-weight: 600; color: var(--text); }
  .train-inline select { padding: 6px 9px; border-radius: 7px; border: 1px solid var(--border); background: var(--bg); color: var(--text); font-size: 12px; font-family: inherit; }
  .train-sheet-line { font-size: 12px; color: var(--muted); margin: 6px 0; }
  .train-sheet-line b { color: var(--accent-2); font-weight: 600; }

  /* ── Resources tab (saved page in → one folder of pictures out) ── */
  .res { max-width: 1000px; }
  .res-drop {
    border: 1px dashed var(--border); border-radius: 12px; padding: 26px 18px;
    text-align: center; background: var(--bg); transition: border-color 0.15s, background 0.15s;
  }
  .res-drop.over { border-color: var(--accent); background: rgba(16,185,129,0.07); }
  .res-drop-t { font-size: 14px; font-weight: 700; color: #f1f5f9; margin-bottom: 6px; }
  .res-drop-s { font-size: 12px; color: var(--muted); }
  .res-files { display: flex; flex-direction: column; gap: 4px; margin: 12px 0 0; }
  .res-file {
    display: flex; align-items: center; gap: 10px; padding: 7px 10px; border-radius: 7px;
    background: var(--bg); border: 1px solid var(--border); font-size: 12px;
  }
  .res-file .nm { flex: 1; color: var(--text); font-weight: 600; word-break: break-all; }
  .res-file .sz { color: var(--muted); font-family: ui-monospace, monospace; }
  .res-file .fmt { font-size: 10px; padding: 2px 7px; border-radius: 999px; font-weight: 700; letter-spacing: 0.4px; }
  .res-file .fmt.mhtml { color: #a7f3d0; background: rgba(16,185,129,0.12); }
  .res-file .fmt.html { color: #fcd34d; background: rgba(251,191,36,0.12); }
  .res-file button { border: none; background: transparent; color: var(--muted); cursor: pointer; font-size: 15px; line-height: 1; font-family: inherit; }
  .res-file button:hover { color: #fca5a5; }
  .res-or {
    display: flex; align-items: center; gap: 12px; margin: 18px 0 14px;
    font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.7px;
  }
  .res-or::before, .res-or::after { content: ""; flex: 1; height: 1px; background: var(--border); }
  .res-urls-label { display: flex; flex-direction: column; gap: 6px; font-size: 12px; font-weight: 600; color: var(--text); }
  .res-urls-label .opt { color: var(--muted); font-weight: 500; line-height: 1.5; }
  #r_urls {
    width: 100%; min-height: 190px; resize: vertical; padding: 12px 13px;
    border-radius: 9px; border: 1px solid var(--border); background: var(--bg);
    color: var(--text); font-size: 12.5px; line-height: 1.65;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  #r_urls:focus { outline: none; border-color: var(--accent); }
  #r_urls::placeholder { color: #3b4354; }
  .res-stop { min-height: 92px; font-size: 12px; line-height: 1.5; }
  .res-preview {
    display: none; margin-top: 14px; padding: 13px 15px; border-radius: 9px;
    border: 1px solid var(--border); background: var(--bg); font-size: 12px; line-height: 1.7;
  }
  .res-preview.show { display: block; }
  .res-preview h4 { font-size: 13px; color: #f1f5f9; margin-bottom: 8px; }
  .res-preview .big { font-size: 20px; font-weight: 700; color: var(--accent-2); }
  .res-preview .row { display: flex; gap: 18px; flex-wrap: wrap; margin-bottom: 8px; }
  .res-preview .k { color: var(--muted); font-family: ui-monospace, monospace; }
  .res-preview .k b { color: var(--text); font-weight: 600; }
  .res-preview .warn { color: #fbbf24; }
  .res-preview ul { margin: 6px 0 0 16px; color: var(--muted); }
  .res-preview code { color: var(--accent-2); font-size: 11px; word-break: break-all; }
  .res-urlbar { display: flex; align-items: center; gap: 12px; margin: 9px 0 4px; flex-wrap: wrap; }
  .res-inline { display: flex; align-items: center; gap: 8px; font-size: 12px; font-weight: 600; color: var(--text); }
  .res-inline input {
    padding: 7px 10px; border-radius: 7px; border: 1px solid var(--border);
    background: var(--bg); color: var(--text); font-size: 12px; font-family: inherit; min-width: 240px;
  }
  .res-inline input:focus { outline: none; border-color: var(--accent); }
  .res-opts { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px 18px; margin: 16px 0 12px; }
  .res-opts label { display: flex; flex-direction: column; gap: 6px; font-size: 12px; font-weight: 600; color: var(--text); }
  .res-opts .opt { color: var(--muted); font-weight: 500; }
  .res-opts input {
    padding: 9px 11px; border-radius: 8px; border: 1px solid var(--border);
    background: var(--bg); color: var(--text); font-size: 13px; font-family: inherit;
  }
  .res-opts input:focus { outline: none; border-color: var(--accent); }
  .res-checks { display: flex; flex-direction: column; gap: 9px; margin-bottom: 16px; }
  .res-checks > label { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--muted); cursor: pointer; }
  .res-checks input[type=checkbox] { cursor: pointer; }
  .res-checks input[type=text] {
    padding: 5px 9px; border-radius: 6px; border: 1px solid var(--border);
    background: var(--bg); color: var(--text); font-size: 12px; font-family: inherit;
  }
  .res-checks input[type=text]:disabled { opacity: 0.4; }
  .res-job, .res-set { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; }
  .res-h { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
  .res-name { font-size: 14px; font-weight: 700; color: #f1f5f9; }
  .res-spacer { flex: 1; }
  .res-state { font-size: 11px; padding: 2px 9px; border-radius: 999px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: var(--muted); background: rgba(255,255,255,0.05); }
  .res-state.parsing, .res-state.downloading, .res-state.queued { color: #fbbf24; background: rgba(251,191,36,0.12); }
  .res-state.done { color: #a7f3d0; background: rgba(16,185,129,0.12); }
  .res-state.error, .res-state.cancelled { color: #fca5a5; background: rgba(239,68,68,0.12); }
  .res-msg { font-size: 12px; color: var(--muted); word-break: break-all; }
  .res-bar { width: 100%; height: 6px; border-radius: 4px; background: #1c1c2a; overflow: hidden; margin: 9px 0; }
  .res-bar-fill { height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); transition: width 0.3s ease; }
  .res-stats { display: flex; gap: 16px; flex-wrap: wrap; font-size: 12px; color: var(--muted); font-family: ui-monospace, monospace; }
  .res-stats b { color: var(--accent-2); font-weight: 600; }
  .res-path { font-size: 11px; color: var(--muted); font-family: ui-monospace, monospace; word-break: break-all; }
  .res-gal { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 4px; }
  .res-gal button {
    display: block; width: 78px; height: 78px; padding: 0; cursor: pointer;
    border-radius: 7px; overflow: hidden; border: 1px solid var(--border); background: var(--bg);
  }
  .res-gal button:hover { border-color: var(--accent); }
  .res-gal button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .res-gal img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .res-more {
    align-self: center; font-size: 11px; color: var(--muted); cursor: pointer;
    background: transparent; border: none; font-family: inherit; padding: 4px 8px;
  }
  .res-more:hover { color: var(--accent-2); }

  /* ── Picture viewer (click a thumbnail; ← → walk the whole folder) ── */
  .res-lb { position: fixed; inset: 0; z-index: 200; display: none; background: rgba(3,3,8,0.985); }
  .res-lb.open { display: flex; flex-direction: column; }
  .res-lb-bar {
    display: flex; align-items: center; gap: 14px; padding: 12px 18px;
    color: var(--muted); font-size: 13px; flex-shrink: 0; flex-wrap: wrap;
    background: var(--surface); border-bottom: 1px solid var(--border);
  }
  .res-lb-name { color: #f1f5f9; font-weight: 600; word-break: break-all; }
  .res-lb-count { font-family: ui-monospace, monospace; }
  .res-lb-hint { font-size: 11px; }
  .res-lb-hint kbd {
    font-family: ui-monospace, monospace; font-size: 10px; padding: 1px 5px;
    border: 1px solid var(--border); border-radius: 4px; color: var(--text);
  }
  .res-lb-stage {
    flex: 1; min-height: 0; position: relative;
    display: flex; align-items: center; justify-content: center; padding: 0 78px 18px;
  }
  .res-lb-stage img { max-width: 100%; max-height: 100%; object-fit: contain; display: block; border-radius: 8px; }
  .res-lb-nav {
    position: absolute; top: 50%; transform: translateY(-50%);
    width: 50px; height: 50px; border-radius: 50%; cursor: pointer;
    border: 1px solid var(--border); background: rgba(12,12,24,0.8);
    color: var(--text); font-size: 24px; line-height: 1; font-family: inherit;
  }
  .res-lb-nav:hover { border-color: var(--accent); color: var(--accent-2); }
  .res-lb-nav.prev { left: 14px; }
  .res-lb-nav.next { right: 14px; }
  .res-errs { margin-top: 10px; font-size: 11px; color: var(--muted); font-family: ui-monospace, monospace; }
  .res-errs summary { cursor: pointer; color: #fca5a5; font-family: inherit; font-size: 12px; }
  .res-errs div { padding: 3px 0 0 12px; word-break: break-all; }

  /* ── Models tab: BASE-model LoRA kanban ── */
  .mdl-wrap { padding: 4px 2px 18px; }
  .mdl-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }
  .mdl-fams { display: flex; gap: 6px; flex-wrap: wrap; }
  .mdl-fam {
    padding: 6px 14px; border-radius: 999px; cursor: pointer; font-size: 13px;
    border: 1px solid var(--border); background: rgba(12,12,24,0.6); color: var(--muted);
    font-family: inherit;
  }
  .mdl-fam:hover { border-color: var(--accent); color: var(--text); }
  .mdl-fam.on { border-color: var(--accent); background: rgba(124,58,237,0.22); color: var(--text); }
  .mdl-fam .mdl-fam-dot {
    display: inline-block; width: 7px; height: 7px; border-radius: 50%;
    background: #22c55e; margin-left: 7px; vertical-align: middle;
  }
  .mdl-headright { margin-left: auto; display: flex; align-items: center; gap: 10px; }
  .mdl-active { font-size: 12px; color: var(--muted); }
  .mdl-active b { color: #4ade80; font-weight: 600; }
  .mdl-sub { font-size: 12px; color: var(--muted); line-height: 1.6; margin: 0 0 12px; max-width: 980px; }
  .mdl-sub strong { color: var(--text); }

  .mdl-new { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
  /* display:flex on these would override the [hidden] attribute the JS toggles,
     leaving the full-screen modal overlay up over the whole tab. */
  .mdl-new[hidden], .mdl-modal[hidden] { display: none !important; }
  .mdl-new input, .mdl-new select {
    padding: 7px 10px; border-radius: 8px; border: 1px solid var(--border);
    background: rgba(12,12,24,0.7); color: var(--text); font-family: inherit; font-size: 13px;
  }
  .mdl-new #mdlNewName { flex: 1 1 320px; }
  .mdl-new #mdlNewScale { width: 84px; }

  /* Five lanes side by side; each scrolls on its own so a long lane cannot
     push the others off screen. min-width keeps cards readable at the
     operator's 67% zoom rather than collapsing to slivers. */
  .mdl-board { display: flex; gap: 10px; align-items: flex-start; overflow-x: auto; padding-bottom: 8px; }
  .mdl-lane { flex: 1 1 0; min-width: 230px; background: rgba(12,12,24,0.45);
              border: 1px solid var(--border); border-radius: 12px; padding: 10px; }
  .mdl-lane-head { display: flex; align-items: baseline; gap: 6px; margin-bottom: 8px; }
  .mdl-lane-head h4 { margin: 0; font-size: 12px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); font-weight: 600; }
  .mdl-lane-head span { font-size: 11px; color: var(--muted); }
  .mdl-lane.lane-active { border-color: #22c55e; background: rgba(34,197,94,0.07); }
  .mdl-lane.lane-training { border-color: var(--accent); }
  .mdl-lane-body { display: flex; flex-direction: column; gap: 8px; max-height: 60vh; overflow-y: auto; }

  .mdl-card {
    border: 1px solid var(--border); border-radius: 10px; padding: 9px 10px;
    background: rgba(20,20,36,0.85); cursor: pointer;
  }
  .mdl-card:hover { border-color: var(--accent); }
  .mdl-card h5 { margin: 0 0 4px; font-size: 13px; font-weight: 600; color: var(--text); word-break: break-word; }
  .mdl-card .mdl-meta { font-size: 11px; color: var(--muted); display: flex; gap: 8px; flex-wrap: wrap; }
  .mdl-card .mdl-badge {
    display: inline-block; padding: 1px 7px; border-radius: 999px; font-size: 10px;
    border: 1px solid var(--border);
  }
  .mdl-badge.ok { color: #4ade80; border-color: rgba(74,222,128,0.5); }
  .mdl-badge.warn { color: #fbbf24; border-color: rgba(251,191,36,0.5); }
  .mdl-badge.age { color: #f87171; border-color: rgba(248,113,113,0.5); }
  .mdl-bar { height: 4px; border-radius: 2px; background: rgba(255,255,255,0.08); margin-top: 6px; overflow: hidden; }
  .mdl-bar i { display: block; height: 100%; background: var(--accent); }
  .mdl-empty { font-size: 11px; color: var(--muted); font-style: italic; padding: 6px 2px; }

  /* Detail modal */
  .mdl-modal { position: fixed; inset: 0; background: rgba(0,0,0,0.72); z-index: 900;
               display: flex; align-items: center; justify-content: center; padding: 24px; }
  .mdl-modal-inner {
    background: var(--panel); border: 1px solid var(--border); border-radius: 14px;
    width: min(900px, 96vw); max-height: 88vh; display: flex; flex-direction: column;
  }
  .mdl-modal-head { display: flex; align-items: center; gap: 12px; padding: 12px 16px;
                    border-bottom: 1px solid var(--border); }
  .mdl-modal-head strong { font-size: 15px; }
  .mdl-modal-head button { margin-left: auto; }
  .mdl-modal-body { padding: 14px 16px; overflow-y: auto; }
  .mdl-sec { margin-bottom: 16px; }
  .mdl-sec h6 { margin: 0 0 6px; font-size: 11px; letter-spacing: .06em; text-transform: uppercase;
                color: var(--muted); font-weight: 600; }
  .mdl-row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .mdl-row input[type=text], .mdl-row input[type=number], .mdl-row textarea {
    padding: 7px 10px; border-radius: 8px; border: 1px solid var(--border);
    background: rgba(12,12,24,0.7); color: var(--text); font-family: inherit; font-size: 13px;
  }
  .mdl-row textarea { width: 100%; min-height: 76px; resize: vertical; font-family: ui-monospace, monospace; font-size: 12px; }
  .mdl-thumbs { display: grid; grid-template-columns: repeat(auto-fill, minmax(78px, 1fr)); gap: 6px; max-height: 240px; overflow-y: auto; }
  .mdl-thumbs img { width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 6px; border: 1px solid var(--border); }
  .mdl-note { font-size: 11px; color: var(--muted); line-height: 1.6; margin: 6px 0 0; }
  .mdl-age-box { border: 1px solid rgba(248,113,113,0.45); border-radius: 10px; padding: 10px 12px;
                 background: rgba(248,113,113,0.06); }
  .mdl-age-box.done { border-color: rgba(74,222,128,0.45); background: rgba(74,222,128,0.06); }
  .mdl-age-box label { display: flex; gap: 8px; align-items: flex-start; font-size: 12px; line-height: 1.55; cursor: pointer; }
  .mdl-status { font-size: 12px; color: var(--muted); margin-top: 8px; min-height: 16px; }
  .mdl-status.err { color: #fca5a5; }
  .mdl-status.ok { color: #4ade80; }
  .mdl-card-thumb { width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 7px;
                    border: 1px solid var(--border); margin-top: 7px; display: block; }
  .mdl-phase { font-size: 11px; color: var(--accent-2, #c4b5fd); margin-top: 5px; }
  .mdl-phase.err { color: #fca5a5; }
  .mdl-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .mdl-pair figure { margin: 0; }
  .mdl-pair img { width: 100%; border-radius: 8px; border: 1px solid var(--border); display: block; cursor: zoom-in; }
  .mdl-pair figcaption { font-size: 11px; color: var(--muted); margin-top: 4px; }
  .mdl-pair figure.main img { border-color: #22c55e; }
</style>
"""
