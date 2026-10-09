# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Script: creation panel, context menu, creation tab, board drag-drop, load calculations, simulation wiring."""

JS_CREATION = """// ── Creation panel ─────────────────────────────────────────────────────
function fmtRamS(v) { return v >= 1 ? v + " GB" : Math.round(v*1024) + " MB"; }

function renderGrid(q) {
  const grid = document.getElementById("gamesGrid");
  const list = q ? GAMES.filter(g => g.name.toLowerCase().includes(q.toLowerCase())) : GAMES;
  grid.innerHTML = list.map(g => {
    const sel  = selected.has(g.name);
    const inst = installed.has(g.name);
    const safeName = g.name.replace(/'/g, "&#39;");
    return "<div class='game-card" + (sel ? " selected" : "") + "' data-name='" + safeName + "'>" +
      "<div class='gc-name'>" + g.name + "</div>" +
      "<div class='gc-spec'>RAM: <span>" + fmtRamS(g.ram) + "</span> &nbsp; CPU: <span>" + g.cpu + " cores</span></div>" +
      "<span class='gc-installed " + (inst ? "yes" : "no") + "' data-inst='" + safeName + "'>" +
        (inst ? "Installed" : "Not Installed") +
      "</span>" +
    "</div>";
  }).join("");

  grid.querySelectorAll(".game-card").forEach(card => {
    card.addEventListener("click", e => {
      if (e.target.closest("[data-inst]")) return;
      const name = card.dataset.name;
      if (selected.has(name)) selected.delete(name);
      else selected.add(name);
      updateSummary();
      render();
      renderGrid(document.getElementById("createSearch").value);
    });
  });

  grid.querySelectorAll("[data-inst]").forEach(pill => {
    pill.addEventListener("click", e => {
      e.stopPropagation();
      const name = pill.dataset.inst;
      if (installed.has(name)) installed.delete(name);
      else installed.add(name);
      saveInstalled();
      renderGrid(document.getElementById("createSearch").value);
    });
  });
}

function updateSummary() {
  const sel = GAMES.filter(g => selected.has(g.name));
  const count = sel.length;
  const ram   = sel.reduce((s, g) => s + g.ram, 0);
  const cpu   = sel.reduce((s, g) => s + g.cpu, 0);
  const vram  = sel.reduce((s, g) => s + g.vram, 0);
  const allHL = sel.every(g => g.headless === "yes");
  const anyNo = sel.some(g => g.headless === "no");

  document.getElementById("sumCount").textContent   = count;
  document.getElementById("sumRam").textContent     = ram >= 1 ? ram.toFixed(1) + " GB" : Math.round(ram*1024) + " MB";
  document.getElementById("sumCpu").textContent     = cpu % 1 === 0 ? cpu + " cores" : cpu.toFixed(1) + " cores";
  document.getElementById("sumVram").textContent    = vram === 0 ? "0 MB" : vram >= 1 ? vram.toFixed(1) + " GB" : Math.round(vram*1024) + " MB";
  document.getElementById("sumHeadless").textContent = count === 0 ? "—" : allHL ? "All ✓" : anyNo ? "Mixed ✗" : "Partial";
  document.getElementById("createCount").textContent = count + " selected";
  document.getElementById("sumBtn").disabled = count === 0;
}

document.getElementById("createSearch").addEventListener("input", e => {
  renderGrid(e.target.value.trim());
});

document.getElementById("btnSelectAll").addEventListener("click", () => {
  const q = document.getElementById("createSearch").value.trim();
  const list = q ? GAMES.filter(g => g.name.toLowerCase().includes(q.toLowerCase())) : GAMES;
  list.forEach(g => selected.add(g.name));
  updateSummary();
  render();
  renderGrid(q);
});

document.getElementById("btnClear").addEventListener("click", () => {
  selected.clear();
  updateSummary();
  render();
  renderGrid(document.getElementById("createSearch").value.trim());
});

// ── Context menu ───────────────────────────────────────────────────────
const ctxMenu     = document.getElementById("ctx-menu");
const ctxLabel    = document.getElementById("ctx-label");
const ctxActivate = document.getElementById("ctx-activate");
let ctxTargetGame = null;

function hideCtx() {
  ctxMenu.classList.remove("show");
  ctxTargetGame = null;
}

document.getElementById("tbody").addEventListener("contextmenu", e => {
  const row = e.target.closest("tr[data-game]");
  if (!row) return;
  e.preventDefault();
  ctxTargetGame = row.dataset.game;
  ctxLabel.textContent = ctxTargetGame;

  // position near cursor, keep inside viewport
  const x = Math.min(e.clientX, window.innerWidth  - 210);
  const y = Math.min(e.clientY, window.innerHeight - 80);
  ctxMenu.style.left = x + "px";
  ctxMenu.style.top  = y + "px";
  ctxMenu.classList.add("show");
});

ctxActivate.addEventListener("click", () => {
  if (!ctxTargetGame) return;
  selected.add(ctxTargetGame);
  updateSummary();
  render();
  hideCtx();

  // flash the nav tab to signal the game was queued
  const installedTab = document.querySelector(".nav-tab[data-panel='installed']");
  installedTab.style.background = "rgba(244,114,182,0.25)";
  setTimeout(() => installedTab.style.background = "", 600);
});

document.addEventListener("click",       hideCtx);
document.addEventListener("keydown", e => { if (e.key === "Escape") hideCtx(); });
document.addEventListener("scroll",      hideCtx, true);

// ── Creation tab ────────────────────────────────────────────────────────
let boardItems = [];
let boardIdCounter = 0;

// Difficulty → fraction of one CPU core used by one instance
const DIFF_CPU_FRAC = { easy: 0.50, medium: 0.70, hard: 0.85, impossible: 0.90 };

function renderGLP() {
  const list = document.getElementById("glp-list");
  const installedGames = GAMES.filter(g => installed.has(g.name));
  if (!installedGames.length) {
    list.innerHTML = "<div style='font-size:11px;color:#334155;padding:4px 0'>No installed games detected.<br>Mark games as Installed in the Installed tab.</div>";
    return;
  }
  list.innerHTML = installedGames.map(g => {
    const safeName = g.name.replace(/'/g, "&#39;");
    return "<div class='glp-item' draggable='true' data-name='" + safeName + "'>" + g.name + "</div>";
  }).join("");

  list.querySelectorAll(".glp-item").forEach(item => {
    item.addEventListener("dragstart", e => {
      e.dataTransfer.setData("text/plain", item.dataset.name);
      e.dataTransfer.effectAllowed = "copy";
      item.classList.add("dragging");
    });
    item.addEventListener("dragend", () => item.classList.remove("dragging"));
  });
}

// ── Board drag-drop ─────────────────────────────────────────────────────
const kanbanBoard = document.getElementById("kanban-board");

kanbanBoard.addEventListener("dragover", e => {
  e.preventDefault();
  e.dataTransfer.dropEffect = "copy";
  kanbanBoard.classList.add("drag-over");
});

kanbanBoard.addEventListener("dragleave", e => {
  if (!kanbanBoard.contains(e.relatedTarget)) kanbanBoard.classList.remove("drag-over");
});

kanbanBoard.addEventListener("drop", e => {
  e.preventDefault();
  kanbanBoard.classList.remove("drag-over");
  const name = e.dataTransfer.getData("text/plain");
  if (!name) return;
  addToBoard(name);
});

function addToBoard(name) {
  const game = GAMES.find(g => g.name === name);
  if (!game) return;
  boardItems.push({ id: boardIdCounter++, name, game });
  renderBoard();
  renderCalcs();
}

function renderBoard() {
  const cards = document.getElementById("kanban-cards");
  const empty = document.getElementById("kanban-empty");

  if (!boardItems.length) {
    empty.style.display = "";
    cards.innerHTML = "";
    document.getElementById("calc-panel").style.display = "none";
    return;
  }

  empty.style.display = "none";

  // Count instances per name for labeling
  const nameCounts = {};
  boardItems.forEach(item => { nameCounts[item.name] = (nameCounts[item.name] || 0) + 1; });
  const nameIdx = {};

  cards.innerHTML = boardItems.map(item => {
    nameIdx[item.name] = (nameIdx[item.name] || 0) + 1;
    const g = item.game;
    const isMulti = nameCounts[item.name] > 1;
    const instLabel = isMulti ? "Instance #" + nameIdx[item.name] : "";
    return "<div class='k-card' data-id='" + item.id + "'>" +
      "<button class='k-remove' data-remove='" + item.id + "'>×</button>" +
      "<div class='k-card-name'>" + g.name + "</div>" +
      (instLabel ? "<div class='k-card-instance'>" + instLabel + "</div>" : "") +
      "<div class='k-card-spec'>RAM <span>" + fmtRam(g.ram) + "</span></div>" +
      "<div class='k-card-spec'>CPU <span>" + g.cpu + " cores</span></div>" +
      (g.vram > 0 ? "<div class='k-card-spec'>VRAM <span>" + fmtVram(g.vram) + "</span></div>" : "") +
      "<div class='k-card-spec'>Diff <span>" + DIFF_LABEL[g.diff] + "</span></div>" +
    "</div>";
  }).join("");

  cards.querySelectorAll("[data-remove]").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      const id = parseInt(btn.dataset.remove);
      boardItems = boardItems.filter(item => item.id !== id);
      renderBoard();
      renderCalcs();
    });
  });

  cards.querySelectorAll(".k-card").forEach(card => {
    card.addEventListener("dblclick", () => {
      const id = parseInt(card.dataset.id);
      const original = boardItems.find(item => item.id === id);
      if (original) addToBoard(original.name);
    });
  });
}

// ── Load calculations ───────────────────────────────────────────────────
function calculateLoad() {
  const sysPhysicalCpu = parseFloat(document.getElementById("sysPhysicalCpu").value) || 24;
  const sysCpu  = parseFloat(document.getElementById("sysCpu").value)  || 20;
  const sysRam  = parseFloat(document.getElementById("sysRam").value)  || 32;
  const sysVram = parseFloat(document.getElementById("sysVram").value) || 48;

  let totalRam       = 0;
  let totalVram      = 0;
  let totalCpuCores  = 0;
  let totalCpuLoad   = 0;

  boardItems.forEach(item => {
    const g = item.game;
    totalRam      += g.ram;
    totalVram     += g.vram;
    totalCpuCores += g.cpu;
    totalCpuLoad  += g.cpu * DIFF_CPU_FRAC[g.diff];
  });

  const ramPct  = sysRam  > 0 ? (totalRam  / sysRam)  * 100 : 0;
  const vramPct = sysVram > 0 ? (totalVram / sysVram)  * 100 : (totalVram > 0 ? 100 : 0);
  const cpuPct  = sysCpu  > 0 ? (totalCpuLoad / sysCpu) * 100 : 0;
  const gpuPct  = vramPct * 1.10;

  const cpuSpikePct = cpuPct  * 1.35;
  const gpuSpikePct = gpuPct  * 1.25;

  return {
    totalRam, totalVram, totalCpuCores, totalCpuLoad,
    ramPct, vramPct, cpuPct, gpuPct, cpuSpikePct, gpuSpikePct,
    sysCpu, sysRam, sysVram, sysPhysicalCpu
  };
}

function barCls(pct) {
  if (pct < 70)  return "bar-ok";
  if (pct < 90)  return "bar-warn";
  return "bar-danger";
}

function renderCalcs() {
  const panel = document.getElementById("calc-panel");
  if (!boardItems.length) { panel.style.display = "none"; return; }
  panel.style.display = "";

  const c = calculateLoad();

  const metrics = [
    { label: "RAM Usage",      value: c.ramPct.toFixed(1)  + "%", sub: fmtRam(c.totalRam)  + " / " + c.sysRam  + " GB",                                           pct: c.ramPct,  spike: null,             spikeDetail: null },
    { label: "CPU Load",       value: c.cpuPct.toFixed(1)  + "%", sub: c.totalCpuCores + " cores allocated / " + c.totalCpuLoad.toFixed(1) + " effective in use",  pct: c.cpuPct,  spike: c.cpuSpikePct,    spikeDetail: "~" + (c.totalCpuLoad * 1.35).toFixed(1) + " of your " + c.sysCpu + " cores (" + c.sysPhysicalCpu + " core cpu)" },
    { label: "VRAM Usage",     value: c.vramPct.toFixed(1) + "%", sub: (c.totalVram > 0 ? fmtVram(c.totalVram) : "0 MB") + " / " + c.sysVram + " GB",             pct: c.vramPct, spike: null,             spikeDetail: null },
    { label: "GPU Load (est)", value: c.gpuPct.toFixed(1)  + "%", sub: "estimated from VRAM activity",                                                             pct: c.gpuPct,  spike: c.gpuSpikePct,    spikeDetail: "peak render burst" },
  ];

  document.getElementById("calc-grid").innerHTML = metrics.map(m => {
    const fillW  = Math.min(m.pct, 100).toFixed(1);
    const valStyle = m.pct > 100 ? " style='color:#ef4444'" : "";
    const spikeHtml = m.spike !== null
      ? "<div class='calc-spike' style='color:" + (m.spike > 100 ? "#ef4444" : "#fbbf24") + "'>Spike up to " + m.spike.toFixed(1) + "%" + (m.spikeDetail ? " (" + m.spikeDetail + ")" : "") + "</div>"
      : "";
    return "<div class='calc-item'>" +
      "<div class='calc-item-label'>" + m.label + "</div>" +
      "<div class='calc-item-value'" + valStyle + ">" + m.value + "</div>" +
      "<div class='calc-item-sub'>" + m.sub + "</div>" +
      "<div class='calc-bar-bg'><div class='calc-bar-fill " + barCls(m.pct) + "' style='width:" + fillW + "%'></div></div>" +
      spikeHtml +
    "</div>";
  }).join("");

}

// ── Simulation wiring ──────────────────────────────────────────────────
let simPollTimer = null;
let simStartTime = null;

function fmtElapsed(secs) {
  const m = Math.floor(secs / 60), s = Math.floor(secs % 60);
  return m > 0 ? m + "m " + s + "s" : s + "s";
}

function renderSimStatus(data) {
  const panel   = document.getElementById("sim-status-panel");
  const dot     = document.getElementById("simDot");
  const label   = document.getElementById("simStatusLabel");
  const elapsed = document.getElementById("simElapsed");
  const list    = document.getElementById("sim-instance-list");

  if (!data || (!data.running && !data.instances.length)) {
    panel.style.display = "none";
    return;
  }

  panel.style.display = "";

  const allRecording = data.instances.length > 0 && data.instances.every(i => i.status === "recording");
  const anyRecording = data.instances.some(i => i.status === "recording");

  if (allRecording) {
    dot.className = "sim-status-dot recording";
    label.textContent = "Simulation running — " + data.instances.length + " instance" + (data.instances.length !== 1 ? "s" : "") + " recording";
  } else if (anyRecording) {
    dot.className = "sim-status-dot starting";
    label.textContent = "Starting up…";
  } else {
    dot.className = "sim-status-dot starting";
    label.textContent = "Launching…";
  }

  if (data.started_at) {
    const secs = (Date.now() / 1000) - data.started_at;
    elapsed.textContent = fmtElapsed(secs);
  }

  list.innerHTML = data.instances.map(inst => {
    const isSt = inst.status === "recording" ? "recording" : inst.status.startsWith("error") ? "error" : "starting";
    const stLabel = inst.status === "recording" ? "● Recording" : inst.status.startsWith("error") ? "✕ " + inst.status : "⟳ Starting";
    const instLabel = inst.instance > 1 ? " #" + inst.instance : "";
    const outputShort = inst.output ? inst.output.split("/").pop() : "";
    return "<div class='sim-inst-row'>" +
      "<span class='sim-inst-name'>" + inst.game + instLabel + "</span>" +
      "<span class='sim-inst-display'>:display " + inst.display + "</span>" +
      "<span class='sim-inst-status " + isSt + "'>" + stLabel + "</span>" +
      (outputShort ? "<span class='sim-inst-output'>" + outputShort + "</span>" : "") +
    "</div>";
  }).join("");
}

function startStatusPoll() {
  if (simPollTimer) return;
  simPollTimer = setInterval(() => {
    fetch("/api/simulate/status")
      .then(r => r.json())
      .then(data => {
        renderSimStatus(data);
        if (!data.running && !data.instances.length) stopStatusPoll();
      })
      .catch(() => {});
  }, 2000);
}

function stopStatusPoll() {
  clearInterval(simPollTimer);
  simPollTimer = null;
}

document.getElementById("activateSimBtn").addEventListener("click", () => {
  const games = boardItems.map(item => item.name);
  if (!games.length) return;

  const btn = document.getElementById("activateSimBtn");
  btn.disabled = true;
  btn.textContent = "Launching…";

  fetch("/api/simulate/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ games })
  })
    .then(r => r.json())
    .then(data => {
      if (data.ok) {
        document.getElementById("sim-status-panel").style.display = "";
        renderSimStatus({ running: true, started_at: Date.now() / 1000, instances: [] });
        startStatusPoll();
        btn.textContent = "Simulation Running";
      } else {
        btn.disabled = false;
        btn.textContent = "Activate Simulation";
        alert("Error: " + (data.error || "Unknown error"));
      }
    })
    .catch(() => {
      btn.disabled = false;
      btn.textContent = "Activate Simulation";
    });
});

document.getElementById("stopSimBtn").addEventListener("click", () => {
  fetch("/api/simulate/stop", { method: "POST" })
    .then(r => r.json())
    .then(() => {
      stopStatusPoll();
      document.getElementById("sim-status-panel").style.display = "none";
      const btn = document.getElementById("activateSimBtn");
      btn.disabled = false;
      btn.textContent = "Activate Simulation";
    })
    .catch(() => {});
});

"""
