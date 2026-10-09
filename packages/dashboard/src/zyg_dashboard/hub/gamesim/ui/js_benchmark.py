# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Script: the benchmark run, its progress and results, the frames gallery and the debug console."""

JS_BENCHMARK = """// ── Benchmark ──────────────────────────────────────────────────────────
let benchPollTimer = null;

const VERDICT_LABEL = { smooth:"Smooth", acceptable:"Acceptable", heavy:"Heavy", failed:"Failed", no_folder:"Not Installed" };
const VERDICT_CLS   = { smooth:"v-smooth", acceptable:"v-acceptable", heavy:"v-heavy", failed:"v-failed", no_folder:"v-no_folder" };
const PHASE_LABEL   = { starting:"Starting up…", testing:"Running test…", stopping:"Stopping…", cooldown:"Cooldown…", done:"Complete", idle:"Idle" };

function barColor(pct) {
  if (pct < 65)  return "#4ade80";
  if (pct < 85)  return "#fbbf24";
  return "#ef4444";
}

function fmtRamMB(mb) {
  if (mb >= 1024) return (mb/1024).toFixed(1) + " GB";
  return Math.round(mb) + " MB";
}

function renderBenchResult(r) {
  const vc  = VERDICT_CLS[r.verdict]   || "v-failed";
  const vl  = VERDICT_LABEL[r.verdict] || r.verdict;
  const ok  = r.status === "ok";

  const cpuBar  = Math.min(r.peak_cpu,  100).toFixed(1);
  const ramPct  = Math.min(r.peak_ram / 320, 100).toFixed(1);  // 32GB = 100%
  const gpuBar  = Math.min(r.peak_gpu,  100).toFixed(1);
  const vramPct = Math.min(r.peak_vram / 480, 100).toFixed(1); // 48GB VRAM

  const statsHtml = ok ? `
    <div class="bench-stat">
      <div class="bench-stat-label">CPU</div>
      <div class="bench-stat-vals">avg <b>${r.avg_cpu}%</b> · peak ${r.peak_cpu}%</div>
      <div class="bench-stat-bar-bg"><div class="bench-stat-bar-fill" style="width:${cpuBar}%;background:${barColor(r.peak_cpu)}"></div></div>
    </div>
    <div class="bench-stat">
      <div class="bench-stat-label">RAM</div>
      <div class="bench-stat-vals">avg <b>${fmtRamMB(r.avg_ram)}</b> · peak ${fmtRamMB(r.peak_ram)}</div>
      <div class="bench-stat-bar-bg"><div class="bench-stat-bar-fill" style="width:${ramPct}%;background:${barColor(parseFloat(ramPct))}"></div></div>
    </div>
    <div class="bench-stat">
      <div class="bench-stat-label">GPU</div>
      <div class="bench-stat-vals">avg <b>${r.avg_gpu}%</b> · peak ${r.peak_gpu}%</div>
      <div class="bench-stat-bar-bg"><div class="bench-stat-bar-fill" style="width:${gpuBar}%;background:${barColor(r.peak_gpu)}"></div></div>
    </div>
    <div class="bench-stat">
      <div class="bench-stat-label">VRAM</div>
      <div class="bench-stat-vals">avg <b>${fmtRamMB(r.avg_vram)}</b> · peak ${fmtRamMB(r.peak_vram)}</div>
      <div class="bench-stat-bar-bg"><div class="bench-stat-bar-fill" style="width:${vramPct}%;background:${barColor(parseFloat(vramPct))}"></div></div>
    </div>` : `<div style="font-size:12px;color:#475569;align-self:center">${r.notes.join(" · ") || r.status}</div>`;

  const debugLines = r.debug_lines || [];
  const safeGame = r.game.replace(/[^a-zA-Z0-9]/g, "_");
  const debugHtml = debugLines.length
    ? debugLines.map(l => {
        const esc = l.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
        if (/ERROR|Traceback|exception/i.test(esc)) return `<span class="dbg-err">${esc}</span>`;
        if (/===|---/.test(esc)) return `<span class="dbg-sep">${esc}</span>`;
        if (/started|DONE|verdict=/i.test(esc)) return `<span class="dbg-ok">${esc}</span>`;
        if (/WARN|warn|fps=0/.test(esc)) return `<span class="dbg-warn">${esc}</span>`;
        return esc;
      }).join("\\n")
    : "No debug output captured.";

  return `<div class="bench-result-card" id="brc-${safeGame}">
    <div class="bench-result-left">
      <div class="bench-result-game">${r.game}</div>
      ${ok ? `<div class="bench-result-startup">Startup: ${(r.startup_ms/1000).toFixed(1)}s</div>` : ""}
      ${ok && r.ffmpeg_fps > 0 ? `<div class="bench-result-fps">FFmpeg ${r.ffmpeg_fps} fps captured</div>` : ""}
      ${r.recording ? `<div style="font-size:10px;color:#475569;margin-top:2px">📹 ${r.recording.split('/').pop()}</div>` : ""}
      ${!ok ? `<div style="font-size:11px;color:#ef4444;margin-top:4px">${(r.notes[0] || "Error").replace(/</g,"&lt;")}</div>` : ""}
      <button class="bench-log-toggle" onclick="toggleBenchLog('${safeGame}')">▶ Debug Logs (${debugLines.length} lines)</button>
      <div class="bench-game-logs" id="bgl-${safeGame}">${debugHtml}</div>
    </div>
    <div class="bench-result-stats">${statsHtml}</div>
    <div class="bench-verdict ${vc}">${vl}</div>
  </div>`;
}

function renderBenchResults(results) {
  const wrap  = document.getElementById("bench-results");
  const empty = document.getElementById("bench-empty");
  if (!results.length) {
    empty.style.display = "";
    wrap.innerHTML = "";
    return;
  }
  empty.style.display = "none";
  wrap.innerHTML = results.map(renderBenchResult).join("");
}

function updateBenchProgress(data) {
  const prog   = document.getElementById("bench-progress");
  const runBtn = document.getElementById("benchRunBtn");
  const stopBtn = document.getElementById("benchStopBtn");

  if (!data.running && data.phase !== "done") {
    prog.style.display  = "none";
    runBtn.style.display  = "";
    stopBtn.style.display = "none";
    runBtn.disabled       = false;
    runBtn.textContent    = "▶ Run Benchmark";
    return;
  }

  prog.style.display  = "";
  runBtn.style.display  = "none";
  stopBtn.style.display = "";

  const total    = data.total || 1;
  const done     = data.results ? data.results.length : 0;
  const pct      = data.phase === "done" ? 100 : Math.round(done / total * 100);
  document.getElementById("benchProgFill").style.width     = pct + "%";
  document.getElementById("benchProgFraction").textContent = done + " / " + total + " games";

  if (data.phase === "done") {
    document.getElementById("benchProgLabel").textContent = "Benchmark complete";
    document.getElementById("bench-live").style.display   = "none";
    stopBtn.style.display = "none";
    runBtn.style.display  = "";
    runBtn.disabled       = false;
    runBtn.textContent    = "▶ Run Again";
    stopBenchPoll();
    stopDebugPoll();
    stopFramesPoll();
    fetchDebugLog();
    if (data.frames_folder) fetchFramesFinal(data.frames_folder);
  } else {
    const game  = data.current_game || "—";
    const phase = PHASE_LABEL[data.phase] || data.phase;
    document.getElementById("benchProgLabel").textContent  = game;
    document.getElementById("bench-live").style.display    = "";
    document.getElementById("benchLiveGame").textContent   = game;
    document.getElementById("benchLivePhase").textContent  = phase;

    const live = data.live || {};
    document.getElementById("benchLiveMetrics").innerHTML = `
      <div class="bench-metric-box">
        <div class="bench-metric-label">CPU</div>
        <div class="bench-metric-val">${live.cpu ?? "—"}<span class="bench-metric-unit">%</span></div>
      </div>
      <div class="bench-metric-box">
        <div class="bench-metric-label">RAM</div>
        <div class="bench-metric-val">${live.ram_mb != null ? fmtRamMB(live.ram_mb) : "—"}</div>
      </div>
      <div class="bench-metric-box">
        <div class="bench-metric-label">GPU</div>
        <div class="bench-metric-val">${live.gpu ?? "—"}<span class="bench-metric-unit">%</span></div>
      </div>
      <div class="bench-metric-box">
        <div class="bench-metric-label">VRAM</div>
        <div class="bench-metric-val">${live.vram_mb != null ? fmtRamMB(live.vram_mb) : "—"}</div>
      </div>`;

    if (live.elapsed != null && live.target) {
      const timePct = Math.min(live.elapsed / live.target * 100, 100).toFixed(1);
      document.getElementById("benchTimeFill").style.width  = timePct + "%";
      document.getElementById("benchTimeLabel").textContent = live.elapsed + "s / " + live.target + "s";
    }
  }
}

// ── Frames gallery ──────────────────────────────────────────────────────────
let _framesPollTimer = null;
let _framesFolder    = null;
const _framesLoaded  = new Set();

function startFramesPoll(folder) {
  if (_framesFolder === folder && _framesPollTimer) return;
  _framesFolder = folder;
  document.getElementById("benchFramesWrap").style.display = "";
  if (_framesPollTimer) clearInterval(_framesPollTimer);
  _framesPollTimer = setInterval(() => pollFrames(folder), 3000);
  pollFrames(folder);
}

function stopFramesPoll() {
  clearInterval(_framesPollTimer);
  _framesPollTimer = null;
}

function pollFrames(folder) {
  fetch("/api/frames/" + folder)
    .then(r => r.json())
    .then(names => addFrames(folder, names))
    .catch(() => {});
}

function fetchFramesFinal(folder) {
  _framesFolder = folder;
  document.getElementById("benchFramesWrap").style.display = "";
  fetch("/api/frames/" + folder)
    .then(r => r.json())
    .then(names => addFrames(folder, names))
    .catch(() => {});
}

function addFrames(folder, names) {
  if (!names || !names.length) return;
  const strip   = document.getElementById("benchFramesFilmstrip");
  const countEl = document.getElementById("benchFramesCount");
  let addedAny  = false;
  names.forEach((name, i) => {
    if (_framesLoaded.has(name)) return;
    _framesLoaded.add(name);
    if (!addedAny) {
      addedAny = true;
      if (strip.children.length === 1 && !strip.children[0].classList.contains("bench-frame-item")) {
        strip.innerHTML = "";  // remove placeholder
      }
    }
    const t    = i * 2;
    const mm   = String(Math.floor(t / 60)).padStart(2, "0");
    const ss   = String(t % 60).padStart(2, "0");
    const item = document.createElement("div");
    item.className = "bench-frame-item";
    item.innerHTML =
      `<img class="bench-frames-thumb" src="/frames/${folder}/${name}"` +
      ` data-folder="${folder}" data-name="${name}" data-idx="${i}"` +
      ` title="Frame ${i + 1} · t=${mm}:${ss}" loading="lazy">` +
      `<div class="bench-frame-ts">${mm}:${ss}</div>`;
    item.querySelector("img").addEventListener("click", showFrameFull);
    strip.appendChild(item);
  });
  countEl.textContent = _framesLoaded.size + " frames";
}

function showFrameFull(e) {
  const img  = e.currentTarget;
  document.querySelectorAll(".bench-frames-thumb.active").forEach(el => el.classList.remove("active"));
  img.classList.add("active");
  const i    = parseInt(img.dataset.idx);
  const t    = i * 2;
  const mm   = String(Math.floor(t / 60)).padStart(2, "0");
  const ss   = String(t % 60).padStart(2, "0");
  document.getElementById("benchFramesFull").src        = `/frames/${img.dataset.folder}/${img.dataset.name}`;
  document.getElementById("benchFramesCaption").textContent =
    `Frame ${i + 1}  ·  t = ${mm}:${ss}  ·  ${img.dataset.name}  ·  ${img.dataset.folder}`;
  document.getElementById("benchFramesDetail").style.display = "";
}

document.getElementById("benchFramesClear").addEventListener("click", () => {
  stopFramesPoll();
  _framesFolder = null;
  _framesLoaded.clear();
  document.getElementById("benchFramesWrap").style.display   = "none";
  document.getElementById("benchFramesFilmstrip").innerHTML  =
    '<div style="color:#1e293b;font-size:11px;padding:4px 2px;align-self:center">Waiting for first frame…</div>';
  document.getElementById("benchFramesDetail").style.display = "none";
  document.getElementById("benchFramesCount").textContent    = "captured every 2 s";
});
// ────────────────────────────────────────────────────────────────────────────

function startBenchPoll() {
  if (benchPollTimer) return;
  benchPollTimer = setInterval(() => {
    fetch("/api/benchmark/status")
      .then(r => r.json())
      .then(data => {
        updateBenchProgress(data);
        renderBenchResults(data.results || []);
        // Start live frames polling as soon as a frames folder is known
        if (data.frames_folder && data.frames_folder !== _framesFolder) {
          startFramesPoll(data.frames_folder);
        }
      })
      .catch(() => {});
  }, 1500);
}

function stopBenchPoll() {
  clearInterval(benchPollTimer);
  benchPollTimer = null;
}

function toggleBenchLog(safeGame) {
  const el  = document.getElementById("bgl-" + safeGame);
  const btn = el ? el.previousElementSibling : null;
  if (!el) return;
  const shown = el.style.display === "block";
  el.style.display = shown ? "none" : "block";
  if (btn) btn.textContent = shown
    ? "▶ Debug Logs (" + el.textContent.split("\\n").length + " lines)"
    : "▼ Hide Debug Logs";
  if (!shown) el.scrollTop = el.scrollHeight;
}

let _debugPollTimer = null;

function fetchDebugLog() {
  fetch("/api/benchmark/debug")
    .then(r => r.json())
    .then(data => {
      const lines  = data.lines || [];
      const cons   = document.getElementById("benchDebugConsole");
      const wrap   = document.getElementById("benchDebugWrap");
      const countEl= document.getElementById("benchDebugCount");
      if (!cons) return;
      wrap.style.display = lines.length ? "" : "none";
      countEl.textContent = lines.length + " lines";
      const atBottom = cons.scrollHeight - cons.scrollTop <= cons.clientHeight + 50;
      cons.innerHTML = lines.map(l => {
        const esc = l.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
        if (/ERROR|Traceback|exception/i.test(esc)) return `<div class="dbg-err">${esc}</div>`;
        if (/===|---/.test(esc))   return `<div class="dbg-sep">${esc}</div>`;
        if (/WARN|warn|fps=0/.test(esc)) return `<div class="dbg-warn">${esc}</div>`;
        if (/started|DONE|verdict=/i.test(esc)) return `<div class="dbg-ok">${esc}</div>`;
        if (esc.includes('[game-live]')) return `<div class="dbg-live">${esc}</div>`;
        const m = esc.match(/^(\\[\\d{2}:\\d{2}:\\d{2}\\])\\s*(.*)/s);
        return m ? `<div><span class="dbg-ts">${m[1]}</span> ${m[2]}</div>` : `<div>${esc}</div>`;
      }).join("");
      if (atBottom) cons.scrollTop = cons.scrollHeight;
    })
    .catch(() => {});
}

function startDebugPoll() {
  if (_debugPollTimer) return;
  document.getElementById("benchDebugWrap").style.display = "";
  _debugPollTimer = setInterval(fetchDebugLog, 1500);
  fetchDebugLog();
}

function stopDebugPoll() {
  clearInterval(_debugPollTimer);
  _debugPollTimer = null;
}

function initBenchPanel() {
  // Sync state on tab open
  fetch("/api/benchmark/status")
    .then(r => r.json())
    .then(data => {
      updateBenchProgress(data);
      renderBenchResults(data.results || []);
      if (data.running) startBenchPoll();
    })
    .catch(() => {});
}

document.getElementById("benchRunBtn").addEventListener("click", () => {
  const duration = parseInt(document.getElementById("benchDuration").value);
  const btn = document.getElementById("benchRunBtn");
  btn.disabled    = true;
  btn.textContent = "Starting…";

  fetch("/api/benchmark/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ duration })
  })
    .then(r => r.json())
    .then(data => {
      if (data.ok) {
        startBenchPoll();
        startDebugPoll();
      } else {
        btn.disabled    = false;
        btn.textContent = "▶ Run Benchmark";
        alert(data.error || "Failed to start");
      }
    })
    .catch(() => { btn.disabled = false; btn.textContent = "▶ Run Benchmark"; });
});

document.getElementById("benchStopBtn").addEventListener("click", () => {
  fetch("/api/benchmark/stop", { method: "POST" })
    .then(() => {
      stopBenchPoll();
      stopDebugPoll();
      stopFramesPoll();
      fetchDebugLog();
      document.getElementById("bench-progress").style.display = "none";
      document.getElementById("benchRunBtn").style.display    = "";
      document.getElementById("benchStopBtn").style.display   = "none";
      document.getElementById("benchRunBtn").disabled         = false;
      document.getElementById("benchRunBtn").textContent      = "▶ Run Benchmark";
    });
});

document.getElementById("libSearch").addEventListener("input", renderLibrary);
document.getElementById("libSort").addEventListener("change", renderLibrary);
document.getElementById("libRefresh").addEventListener("click", fetchLibrary);

document.getElementById("sysPhysicalCpu").addEventListener("input", renderCalcs);
document.getElementById("sysCpu").addEventListener("input",  renderCalcs);
document.getElementById("sysRam").addEventListener("input",  renderCalcs);
document.getElementById("sysVram").addEventListener("input", renderCalcs);
document.getElementById("clearBoard").addEventListener("click", () => {
  boardItems = [];
  renderBoard();
  renderCalcs();
});

"""
