# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Document body: the page markup, the left nav and every panel."""

BODY = """</head>
<body>
<div class="page">

  <div class="header">
    <div class="wordmark">
      <div class="logo-hex">Z</div>
      <div class="brand">
        <span class="brand-name">Zygomatic</span>
        <span class="page-title">Game Simulator</span>
      </div>
    </div>
    <a class="hub-link" href="http://__ZYG_LAN_HOST__:7000">&#8592; Hub</a>
  </div>

  <div class="stats-strip" id="statsStrip">
    <div class="stat-card">
      <span class="stat-label">Total Games</span>
      <span class="stat-value" id="statTotal">26</span>
      <span class="stat-sub">across 4 tiers</span>
    </div>
    <div class="stat-card">
      <span class="stat-label">Full Headless</span>
      <span class="stat-value" style="color:#4ade80" id="statYes">—</span>
      <span class="stat-sub">0 MB VRAM</span>
    </div>
    <div class="stat-card">
      <span class="stat-label">Partial</span>
      <span class="stat-value" style="color:#fbbf24" id="statPartial">—</span>
      <span class="stat-sub">reduced rendering</span>
    </div>
    <div class="stat-card">
      <span class="stat-label">Needs GPU</span>
      <span class="stat-value" style="color:#ef4444" id="statNo">—</span>
      <span class="stat-sub">full render required</span>
    </div>
    <div class="stat-card">
      <span class="stat-label">Easiest to Bot</span>
      <span class="stat-value" style="font-size:14px;padding-top:4px" id="statEasy">—</span>
      <span class="stat-sub">easy difficulty</span>
    </div>
  </div>

  <div class="main-body">

    <!-- Left nav -->
    <nav class="left-nav">
      <button class="nav-tab active" data-panel="req">
        <svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
        Requirements
      </button>
      <button class="nav-tab" data-panel="installed">
        <svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>
        Installed
      </button>
      <button class="nav-tab" data-panel="creation">
        <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/></svg>
        Creation
      </button>
      <button class="nav-tab" data-panel="library">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="2" y="7" width="20" height="15" rx="2"/><polyline points="17 2 12 7 7 2"/><line x1="12" y1="12" x2="12" y2="17"/><line x1="9.5" y1="14.5" x2="14.5" y2="14.5"/></svg>
        Content Library
      </button>
      <button class="nav-tab" data-panel="benchmark">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/><circle cx="12" cy="12" r="3"/></svg>
        Benchmark
      </button>
      <button class="nav-tab" data-panel="schematics">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 21h18"/><path d="M5 21V8l2 1V6h2v3h6V6h2v3l2-1v13"/><path d="M10 21v-5h4v5"/></svg>
        Schematics
      </button>
      <button class="nav-tab" data-panel="production">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="10" y1="6" x2="21" y2="6"/><line x1="10" y1="12" x2="21" y2="12"/><line x1="10" y1="18" x2="21" y2="18"/><polygon points="3 4 7 6.5 3 9"/><line x1="3" y1="12" x2="5" y2="12"/><line x1="3" y1="18" x2="5" y2="18"/></svg>
        Production List
      </button>
      <button class="nav-tab" data-panel="creator">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 2l9 5-9 5-9-5 9-5z"/><path d="M3 12l9 5 9-5"/><path d="M3 17l9 5 9-5"/><circle cx="19" cy="5" r="2.6" fill="currentColor" stroke="none" opacity=".9"/></svg>
        Schematic Creator
      </button>
    </nav>

    <div class="content">

      <!-- Requirements panel -->
      <div id="panel-req">
        <div class="toolbar">
          <div class="search-wrap">
            <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <input class="search-input" id="search" placeholder="Search games, methods, languages..." autocomplete="off">
          </div>
          <div class="filter-chips">
            <button class="chip active" data-f="all">All</button>
            <button class="chip c-yes"  data-f="yes">Headless</button>
            <button class="chip c-part" data-f="partial">Partial</button>
            <button class="chip c-no"   data-f="no">No Headless</button>
          </div>
          <span class="count-tag" id="countTag"></span>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th data-c="name">Game <span class="si"></span></th>
                <th data-c="tier">Tier <span class="si"></span></th>
                <th data-c="headless">Headless <span class="si"></span></th>
                <th data-c="method">Method</th>
                <th data-c="lang">Language <span class="si"></span></th>
                <th data-c="ram">RAM <span class="si"></span></th>
                <th data-c="vram">VRAM <span class="si"></span></th>
                <th data-c="cpu">CPU <span class="si"></span></th>
                <th data-c="diff">Difficulty <span class="si"></span></th>
                <th data-c="pop">Popularity <span class="si"></span></th>
              </tr>
            </thead>
            <tbody id="tbody"></tbody>
          </table>
        </div>
      </div>

      <!-- Installed panel -->
      <div id="panel-installed" style="display:none">
        <div class="create-toolbar">
          <div class="create-search-wrap">
            <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <input class="create-search" id="createSearch" placeholder="Filter games..." autocomplete="off">
          </div>
          <button class="btn-sm" id="btnSelectAll">Select All</button>
          <button class="btn-sm" id="btnClear">Clear</button>
          <span class="count-tag" id="createCount">0 selected</span>
        </div>
        <div class="games-grid" id="gamesGrid"></div>
        <div class="summary-bar">
          <div class="sum-item">
            <span class="sum-label">Selected</span>
            <span class="sum-value pink" id="sumCount">0</span>
          </div>
          <div class="sum-item">
            <span class="sum-label">Total RAM</span>
            <span class="sum-value" id="sumRam">0 GB</span>
          </div>
          <div class="sum-item">
            <span class="sum-label">Total CPU</span>
            <span class="sum-value" id="sumCpu">0 cores</span>
          </div>
          <div class="sum-item">
            <span class="sum-label">VRAM</span>
            <span class="sum-value" id="sumVram">0 MB</span>
          </div>
          <div class="sum-item">
            <span class="sum-label">Headless</span>
            <span class="sum-value" id="sumHeadless">—</span>
          </div>
          <button class="sum-btn" id="sumBtn" disabled>Generate Simulation</button>
        </div>
      </div>

      <!-- Creation panel -->
      <div id="panel-creation" style="display:none">
        <div class="creation-layout">

          <!-- Left: installed game list -->
          <div class="glp">
            <div class="glp-title">Installed Games</div>
            <div class="glp-sub">Drag a name onto the board</div>
            <div id="glp-list"></div>
          </div>

          <!-- Right: kanban + calculations -->
          <div class="kanban-side">

            <!-- System specs bar -->
            <div class="sys-bar">
              <span class="sys-lbl">Your System:</span>
              CPU <input class="sys-inp" id="sysPhysicalCpu" type="number" value="24" min="1" max="1024"> core cpu &nbsp;
              Allocated <input class="sys-inp" id="sysCpu"  type="number" value="20" min="1" max="512"> cores &nbsp;
              RAM <input class="sys-inp" id="sysRam"  type="number" value="32" min="1" max="4096"> GB &nbsp;
              VRAM <input class="sys-inp" id="sysVram" type="number" value="48"  min="0" max="256"> GB
              <button class="btn-sm" id="clearBoard" style="margin-left:auto">Clear Board</button>
            </div>

            <!-- Board -->
            <div id="kanban-board" class="kanban-board">
              <div class="kanban-empty" id="kanban-empty">
                <svg viewBox="0 0 24 24" style="width:32px;height:32px;stroke:#334155;fill:none;stroke-width:1.5;stroke-linecap:round"><rect x="3" y="3" width="18" height="18" rx="3"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
                <span>Drag games here to plan your simulation</span>
              </div>
              <div id="kanban-cards" class="kanban-cards"></div>
            </div>

            <!-- Calculations -->
            <div class="calc-panel" id="calc-panel" style="display:none">
              <div class="calc-title">System Load Estimate</div>
              <div class="calc-grid" id="calc-grid"></div>
              <button class="activate-btn" id="activateSimBtn">Activate Simulation</button>
            </div>

            <!-- Simulation status panel -->
            <div id="sim-status-panel" style="display:none">
              <div class="sim-status-header">
                <span class="sim-status-dot" id="simDot"></span>
                <span id="simStatusLabel">Starting…</span>
                <span id="simElapsed" style="margin-left:auto;font-size:11px;color:var(--muted)"></span>
                <button class="btn-sm" id="stopSimBtn" style="margin-left:12px;background:rgba(239,68,68,0.12);color:#ef4444;border:1px solid rgba(239,68,68,0.2)">Stop All</button>
              </div>
              <div id="sim-instance-list" class="sim-instance-list"></div>
            </div>

          </div><!-- /kanban-side -->
        </div><!-- /creation-layout -->
      </div><!-- /panel-creation -->

      <!-- Content Library panel -->
      <div id="panel-library" style="display:none">
        <div class="lib-toolbar">
          <div class="lib-search-wrap">
            <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <input class="lib-search" id="libSearch" placeholder="Filter by game…" autocomplete="off">
          </div>
          <select class="lib-sort" id="libSort">
            <option value="date">Newest first</option>
            <option value="game">By game</option>
            <option value="size">Largest first</option>
          </select>
          <button class="btn-sm" id="libRefresh">
            <svg viewBox="0 0 24 24" style="width:13px;height:13px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
            Refresh
          </button>
          <span class="count-tag" id="libCount">0 recordings</span>
        </div>

        <!-- Empty state -->
        <div id="lib-empty" class="lib-empty">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" style="width:48px;height:48px;color:#1e293b"><rect x="2" y="7" width="20" height="15" rx="2"/><polyline points="17 2 12 7 7 2"/></svg>
          <div>No recordings yet</div>
          <div style="font-size:11px;color:#334155;margin-top:4px">Activate a simulation to start recording</div>
        </div>

        <!-- Cards grid grouped by game -->
        <div id="lib-grid" class="lib-grid"></div>
      </div><!-- /panel-library -->

      <!-- Benchmark panel -->
      <div id="panel-benchmark" style="display:none">

        <!-- Toolbar -->
        <div class="bench-toolbar">
          <div class="bench-title-block">
            <span class="bench-title">Simulator Benchmark</span>
            <span class="bench-sub">Tests each game independently — one at a time</span>
          </div>
          <div class="bench-controls">
            <label class="bench-lbl">Duration per game</label>
            <select class="lib-sort" id="benchDuration">
              <option value="15">15 seconds</option>
              <option value="30" selected>30 seconds</option>
              <option value="60">60 seconds</option>
              <option value="120">2 minutes</option>
              <option value="300">5 minutes</option>
            </select>
            <button class="activate-btn" id="benchRunBtn" style="width:auto;padding:10px 22px">▶ Run Benchmark</button>
            <button class="btn-sm" id="benchStopBtn" style="display:none;background:rgba(239,68,68,0.12);color:#ef4444;border:1px solid rgba(239,68,68,0.2)">■ Stop</button>
          </div>
        </div>

        <!-- Progress bar -->
        <div id="bench-progress" style="display:none">
          <div class="bench-prog-header">
            <span id="benchProgLabel">Preparing…</span>
            <span id="benchProgFraction" style="color:var(--muted);font-size:12px"></span>
          </div>
          <div class="bench-prog-track">
            <div class="bench-prog-fill" id="benchProgFill"></div>
          </div>

          <!-- Live metrics card -->
          <div class="bench-live" id="bench-live">
            <div class="bench-live-game" id="benchLiveGame">—</div>
            <div class="bench-live-phase" id="benchLivePhase"></div>
            <div class="bench-live-metrics" id="benchLiveMetrics"></div>
            <div class="bench-time-track">
              <div class="bench-time-fill" id="benchTimeFill"></div>
            </div>
            <div class="bench-time-label" id="benchTimeLabel"></div>
          </div>
        </div>

        <!-- Results -->
        <div id="bench-results-wrap">
          <div id="bench-empty" class="lib-empty" style="display:none">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" style="width:48px;height:48px;color:#1e293b"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4"/><circle cx="12" cy="12" r="3"/></svg>
            <div>No benchmark results yet</div>
            <div style="font-size:11px;color:#334155;margin-top:4px">Press Run Benchmark to start</div>
          </div>
          <div id="bench-results" class="bench-results"></div>
        </div>

        <!-- Debug console -->
        <div class="bench-debug-wrap" id="benchDebugWrap" style="display:none">
          <div class="bench-debug-header">
            Debug Log
            <span id="benchDebugCount">0 lines</span>
          </div>
          <div class="bench-debug-console" id="benchDebugConsole"></div>
        </div>

        <!-- Frames gallery -->
        <div class="bench-frames-wrap" id="benchFramesWrap" style="display:none">
          <div class="bench-frames-header">
            Simulation Frames
            <span class="fh-count" id="benchFramesCount">captured every 2 s</span>
            <button class="btn-sm" id="benchFramesClear" style="font-size:10px;padding:3px 10px;opacity:.7">✕ Clear</button>
          </div>
          <div class="bench-frames-filmstrip" id="benchFramesFilmstrip">
            <div style="color:#1e293b;font-size:11px;padding:4px 2px;align-self:center">Waiting for first frame…</div>
          </div>
          <div class="bench-frames-detail" id="benchFramesDetail" style="display:none">
            <img id="benchFramesFull" src="" alt="Frame">
            <div class="bench-frames-caption" id="benchFramesCaption"></div>
          </div>
        </div>

      </div><!-- /panel-benchmark -->

      <!-- Schematics panel -->
      <div id="panel-schematics" style="display:none">
        <div class="schem-topbar">
          <span class="schem-hint">Drag cards between columns &nbsp;·&nbsp; right-click a card to run or queue its build</span>
          <div class="schem-banner" id="schemBanner" style="display:none">
            <span class="rec-dot"></span>
            <span id="schemBannerText">Simulation running</span>
            <button class="btn-sm" id="schemStopBtn">■ Stop</button>
          </div>
        </div>
        <div class="schem-board" id="schemBoard"></div>
      </div><!-- /panel-schematics -->

      <!-- Production List panel -->
      <div id="panel-production" style="display:none">
        <div class="prod-controls">
          <button class="prod-btn p-play"  id="prodPlayBtn">▶ Play</button>
          <button class="prod-btn p-pause" id="prodPauseBtn">❚❚ Pause</button>
          <button class="prod-btn p-stop"  id="prodStopBtn">■ Stop</button>
          <span class="prod-state st-stopped" id="prodState">stopped</span>
          <span style="flex:1"></span>
          <button class="btn-sm" id="prodClearBtn">Clear finished</button>
        </div>
        <div class="prod-current" id="prodCurrent" style="display:none">
          <div class="prod-current-head">
            <span class="rec-dot"></span>
            <span id="prodCurName">—</span>
            <span class="prod-cur-meta" id="prodCurMeta"></span>
          </div>
          <div class="prod-prog-track"><div class="prod-prog-fill" id="prodProgFill" style="width:0%"></div></div>
          <div class="prod-prog-label" id="prodProgLabel"></div>
        </div>
        <div class="prod-list" id="prodList"></div>
        <div class="prod-empty" id="prodEmpty">Production list is empty — right-click a schematic card and choose “Queue this build”.</div>
      </div><!-- /panel-production -->

      <!-- Schematic Creator panel -->
      <div id="panel-creator" style="display:none">
        <div class="cr-top">
          <div class="cr-src">
            <button class="cr-srcbtn" id="crNew">✦ New</button>
            <button class="cr-srcbtn" id="crFork">⑂ Fork…</button>
            <button class="cr-srcbtn" id="crImport">↥ Import .schem</button>
            <button class="cr-srcbtn" id="crCapture">◎ Capture World</button>
            <input type="file" id="crFile" accept=".schem" style="display:none">
          </div>
          <input class="cr-name" id="crName" placeholder="Build name…" autocomplete="off">
          <select class="cr-sel" id="crCat">
            <option>Tower</option><option>Castle</option><option>House</option>
            <option>Monument</option><option>Infrastructure</option><option>Custom</option>
          </select>
          <select class="cr-sel" id="crDiff">
            <option value="easy">easy</option>
            <option value="medium" selected>medium</option>
            <option value="hard">hard</option>
          </select>
          <button class="cr-save" id="crSave" disabled>Publish to Backlog</button>
        </div>

        <div class="cr-layout">
          <!-- Left: the recipe -->
          <div class="cr-col">
            <div class="cr-h">Recipe <span class="cr-op-n" id="crOpCount">0 ops</span></div>
            <div class="cr-ops" id="crOps"></div>
            <button class="cr-addop" id="crAddOp">+ Add step</button>
            <div class="cr-h" style="margin-top:14px">Material</div>
            <input class="cr-search" id="crMatSearch" placeholder="Search blocks…" autocomplete="off">
            <div class="cr-pal" id="crPal"></div>
            <div class="cr-curmat"><span class="cr-sw" id="crCurSw"></span><span id="crCurMat">stone_bricks</span></div>
          </div>

          <!-- Centre: preview + layer painter -->
          <div class="cr-col cr-view">
            <div class="cr-h">
              <span id="crViewTitle">Preview</span>
              <span class="cr-legend">
                <span><span class="cr-dot" style="background:#ef4444"></span>unbuildable</span>
                <span><span class="cr-dot" style="background:#fbbf24"></span>scaffold</span>
              </span>
            </div>
            <canvas class="cr-canvas" id="crCanvas" width="760" height="430"></canvas>
            <div id="crGridWrap" style="display:none"></div>
            <div class="cr-viewbar">
              <button class="cr-tab2 on" id="crModeIso">Isometric</button>
              <button class="cr-tab2" id="crModePaint">Paint layer</button>
              <span id="crLayerCtl" style="display:none;flex:1;display:none;align-items:center;gap:8px">
                <span style="font-size:11px;color:var(--muted)">y=<b id="crLayerY">65</b></span>
                <input type="range" class="cr-slider" id="crLayer" min="65" max="80" value="65">
              </span>
              <span style="font-size:10px;color:var(--muted)" id="crHint">drag to rotate</span>
            </div>
          </div>

          <!-- Right: the compiler's verdict -->
          <div class="cr-col">
            <div class="cr-h">Buildability</div>
            <div class="cr-report">
              <div class="cr-verdict cr-busy" id="crVerdict">— nothing to build yet</div>
              <div class="cr-stat"><span>Blocks</span><b id="crStBlocks">0</b></div>
              <div class="cr-stat"><span>Placed by bot</span><b id="crStPlaced">0</b></div>
              <div class="cr-stat"><span>Scaffold added</span><b id="crStScaf">0</b></div>
              <div class="cr-stat"><span>Inventory slots</span><b id="crStSlots">0</b></div>
              <div class="cr-stat"><span>Build passes</span><b id="crStPasses">0</b></div>
              <div class="cr-stat"><span>Est. time</span><b id="crStTime">—</b></div>
              <div class="cr-issues" id="crIssues"></div>
              <div class="cr-h" style="margin-top:12px">Materials</div>
              <div class="cr-mats" id="crMats"></div>
            </div>
          </div>
        </div>
      </div><!-- /panel-creator -->

      <!-- Video player modal -->
      <div id="vid-modal" class="vid-modal" style="display:none">
        <div class="vid-modal-bg" id="vidModalBg"></div>
        <div class="vid-modal-box">
          <div class="vid-modal-header">
            <span id="vidModalTitle">Recording</span>
            <button class="vid-modal-close" id="vidModalClose">×</button>
          </div>
          <video id="vidModalPlayer" class="vid-modal-player" controls autoplay>
            Your browser does not support video playback.
          </video>
          <div class="vid-modal-meta" id="vidModalMeta"></div>
        </div>
      </div>

    </div><!-- /content -->
  </div><!-- /main-body -->

</div>

<!-- Context menu -->
<div id="ctx-menu">
  <div class="ctx-game-label" id="ctx-label">Game</div>
  <div class="ctx-item" id="ctx-activate">
    <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
    Activate In Creation
  </div>
</div>

<!-- Schematic context menu -->
<div id="schem-ctx">
  <div class="ctx-game-label" id="schemCtxLabel">Schematic</div>
  <div class="ctx-item" id="schemCtxRun">
    <svg viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg>
    Run this build
  </div>
  <div class="ctx-item" id="schemCtxQueue">
    <svg viewBox="0 0 24 24"><line x1="9" y1="6" x2="21" y2="6"/><line x1="9" y1="12" x2="21" y2="12"/><line x1="9" y1="18" x2="21" y2="18"/><path d="M4 3v6M1 6h6"/></svg>
    Queue this build
  </div>
</div>

<div id="toast"></div>
"""
