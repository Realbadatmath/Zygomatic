# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Script: the toast, the Schematics tab with its voxel preview, and the Production List tab."""

JS_BOARDS = """// ── Toast ───────────────────────────────────────────────────────────────
let toastTimer = null;
function toast(msg, ok = true) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.toggle("err", !ok);
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
}

// ── Schematics tab ──────────────────────────────────────────────────────
const SCHEM_COLS = [
  { id: "backlog",      title: "Backlog" },
  { id: "ready",        title: "Ready to Build" },
  { id: "inproduction", title: "In Production" },
  { id: "built",        title: "Built" },
];

const MAT_COLORS = {
  stone_bricks: "#8d8d8d", mossy_stone_bricks: "#6f8f6a", chiseled_stone_bricks: "#a3a3a3",
  cracked_stone_bricks: "#767676", cobblestone: "#7d7d75", stone: "#909090",
  polished_andesite: "#a8a8aa", dark_oak_log: "#4a3319", oak_planks: "#b8945f",
  oak_log: "#6b5232", spruce_planks: "#805e36", glass: "#bfe3ea",
  sandstone: "#dbcf9c", cut_sandstone: "#e3d9ab", quartz_block: "#efeae2",
  red_wool: "#a12722", obsidian: "#221a33", glowstone: "#ffd76e",
};

let schemData = [], schemPollTimer = null, schemCtxTarget = null, schemDragging = false;

function initSchematicsTab() {
  fetchSchematics();
  if (!schemPollTimer) schemPollTimer = setInterval(fetchSchematics, 4000);
}
function stopSchemPoll() { clearInterval(schemPollTimer); schemPollTimer = null; }

function fetchSchematics() {
  fetch("/api/schematics").then(r => r.json())
    .then(d => { schemData = d; renderSchemBoard(); }).catch(() => {});
  fetch("/api/queue").then(r => r.json()).then(renderSchemBanner).catch(() => {});
}

// Accepts "#rrggbb" (the legacy MAT_COLORS map) or "rgb(r,g,b)" (the real
// texture-sampled palette), so both colour sources shade identically.
function shadeColor(col, f) {
  let r, g, b;
  if (col[0] === "#") {
    const n = parseInt(col.slice(1), 16);
    r = (n >> 16) & 255; g = (n >> 8) & 255; b = n & 255;
  } else {
    const m = col.match(/[0-9]+/g);
    if (!m) return col;
    r = +m[0]; g = +m[1]; b = +m[2];
  }
  return "rgb(" + Math.min(255, Math.round(r * f)) + "," +
                  Math.min(255, Math.round(g * f)) + "," +
                  Math.min(255, Math.round(b * f)) + ")";
}

// Real block colours, sampled from the game's own textures by
// hub/tools/dump_colors.py and shipped in the block manifest. Populated the
// first time the Creator's catalogue loads; MAT_COLORS stays as the fallback so
// the board still renders before then.
const PALETTE_COLORS = {};

function blockColor(mat) {
  const c = PALETTE_COLORS[mat];
  if (c) return "rgb(" + c[0] + "," + c[1] + "," + c[2] + ")";
  return MAT_COLORS[mat] || "#9aa0a6";
}

// Mini isometric voxel render of a schematic's block list.
// opts.rotate  — yaw in radians (the Creator's drag-to-orbit)
// opts.colorFn — per-block colour override (unbuildable red, scaffold amber)
function drawSchematic(canvas, blocks, opts) {
  opts = opts || {};
  const rot = opts.rotate || 0;
  const colorFn = opts.colorFn || (b => blockColor(b.mat));
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  if (!blocks || !blocks.length) return;

  // Rotate around the footprint centre so orbiting doesn't drift off-canvas.
  let cx = 0, cz = 0;
  for (const b of blocks) { cx += b.x; cz += b.z; }
  cx /= blocks.length; cz /= blocks.length;
  const cos = Math.cos(rot), sin = Math.sin(rot);
  const proj = b => {
    const dx = b.x - cx, dz = b.z - cz;
    const rx = dx * cos - dz * sin, rz = dx * sin + dz * cos;
    return { rx, rz, u: rx - rz, v: 0.5 * (rx + rz) - 0.62 * b.y };
  };

  let minU = 1e9, maxU = -1e9, minV = 1e9, maxV = -1e9;
  for (const b of blocks) {
    const p = proj(b);
    if (p.u < minU) minU = p.u; if (p.u > maxU) maxU = p.u;
    if (p.v < minV) minV = p.v; if (p.v > maxV) maxV = p.v;
  }
  const s  = Math.min((W - 10) / (maxU - minU + 2.2), (H - 10) / (maxV - minV + 1.8));
  const w  = s, h = s * 0.5, bh = s * 0.62;
  const ox = W / 2 - s * (minU + maxU) / 2;
  const oy = H / 2 - s * (minV + maxV) / 2 - bh * 0.25;

  // Painter's algorithm in ROTATED space, else the draw order breaks as you orbit.
  const sorted = blocks.map(b => ({ b, p: proj(b) }))
    .sort((a, z) => (a.p.rx + a.p.rz) - (z.p.rx + z.p.rz) || a.b.y - z.b.y ||
                    (a.p.rx - a.p.rz) - (z.p.rx - z.p.rz));

  for (const { b, p } of sorted) {
    const px = ox + s * p.u;
    const py = oy + s * p.v;
    const c  = colorFn(b);
    ctx.beginPath();                                    // top face
    ctx.moveTo(px, py - h); ctx.lineTo(px + w, py); ctx.lineTo(px, py + h); ctx.lineTo(px - w, py);
    ctx.closePath(); ctx.fillStyle = shadeColor(c, 1.22); ctx.fill();
    ctx.beginPath();                                    // left face
    ctx.moveTo(px - w, py); ctx.lineTo(px, py + h); ctx.lineTo(px, py + h + bh); ctx.lineTo(px - w, py + bh);
    ctx.closePath(); ctx.fillStyle = shadeColor(c, 0.8); ctx.fill();
    ctx.beginPath();                                    // right face
    ctx.moveTo(px + w, py); ctx.lineTo(px, py + h); ctx.lineTo(px, py + h + bh); ctx.lineTo(px + w, py + bh);
    ctx.closePath(); ctx.fillStyle = shadeColor(c, 0.58); ctx.fill();
  }
}

function schemCardHTML(s) {
  const diffCls = { easy: "d-easy", medium: "d-med", hard: "d-hard" }[s.difficulty] || "d-med";
  return "<div class='schem-card' draggable='true' data-id='" + s.id + "'>" +
    "<canvas class='schem-preview' data-id='" + s.id + "' width='220' height='130'></canvas>" +
    "<div class='schem-name'>" + s.name + "</div>" +
    "<div class='schem-tags'>" +
      "<span class='schem-cat'>" + s.category + "</span>" +
      "<span class='schem-diff " + diffCls + "'>" + s.difficulty + "</span>" +
      (s.queued_count ? "<span class='schem-qbadge'>in queue ×" + s.queued_count + "</span>" : "") +
    "</div>" +
    "<div class='schem-stats'>" +
      "<span>" + s.size.w + "×" + s.size.h + "×" + s.size.d + "</span>" +
      "<span>" + s.block_count + " blocks</span>" +
      "<span>~" + s.est_minutes + " min</span>" +
    "</div>" +
  "</div>";
}

function renderSchemBoard() {
  if (schemDragging) return;                 // don't yank cards mid-drag
  const board = document.getElementById("schemBoard");
  board.innerHTML = SCHEM_COLS.map(col => {
    const cards = schemData.filter(s => s.column === col.id);
    return "<div class='schem-col' data-col='" + col.id + "'>" +
      "<div class='schem-col-head'>" + col.title +
        "<span class='schem-col-count'>" + cards.length + "</span></div>" +
      "<div class='schem-col-body'>" +
        cards.map(schemCardHTML).join("") +
        (cards.length ? "" : "<div class='schem-col-empty'>Drop cards here</div>") +
      "</div>" +
    "</div>";
  }).join("");

  board.querySelectorAll("canvas[data-id]").forEach(cv => {
    const s = schemData.find(x => x.id === cv.dataset.id);
    if (s) drawSchematic(cv, s.blocks);
  });

  board.querySelectorAll(".schem-card").forEach(card => {
    card.addEventListener("dragstart", e => {
      schemDragging = true;
      e.dataTransfer.setData("text/plain", card.dataset.id);
      e.dataTransfer.effectAllowed = "move";
      card.classList.add("dragging");
    });
    card.addEventListener("dragend", () => {
      schemDragging = false;
      card.classList.remove("dragging");
    });
    card.addEventListener("contextmenu", e => {
      e.preventDefault();
      e.stopPropagation();
      schemCtxTarget = card.dataset.id;
      const s = schemData.find(x => x.id === schemCtxTarget);
      document.getElementById("schemCtxLabel").textContent = s ? s.name : "Schematic";
      const menu = document.getElementById("schem-ctx");
      menu.style.left = Math.min(e.clientX, window.innerWidth - 210) + "px";
      menu.style.top  = Math.min(e.clientY, window.innerHeight - 120) + "px";
      menu.classList.add("show");
    });
  });

  board.querySelectorAll(".schem-col").forEach(col => {
    col.addEventListener("dragover", e => { e.preventDefault(); col.classList.add("drag-over"); });
    col.addEventListener("dragleave", e => { if (!col.contains(e.relatedTarget)) col.classList.remove("drag-over"); });
    col.addEventListener("drop", e => {
      e.preventDefault();
      col.classList.remove("drag-over");
      schemDragging = false;
      const id = e.dataTransfer.getData("text/plain");
      const s = schemData.find(x => x.id === id);
      if (!s || s.column === col.dataset.col) { renderSchemBoard(); return; }
      s.column = col.dataset.col;
      renderSchemBoard();
      fetch("/api/schematics/column", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, column: col.dataset.col })
      }).catch(() => {});
    });
  });
}

function renderSchemBanner(q) {
  const banner = document.getElementById("schemBanner");
  const txt    = document.getElementById("schemBannerText");
  const stop   = document.getElementById("schemStopBtn");
  if (!q.sim_running) { banner.style.display = "none"; return; }
  banner.style.display = "";
  if (q.current_uid) {
    const cur = q.items.find(i => i.uid === q.current_uid);
    txt.textContent = "Production list is building " + (cur ? cur.name : "…") + " — control it from the Production List tab";
    stop.style.display = "none";
  } else {
    const st = q.progress;
    txt.textContent = "Simulation recording" + (st && st.name
      ? " — " + st.name + " (" + (st.placed_total || 0) + "/" + st.total + " blocks)" : " in progress");
    stop.style.display = "";
  }
}

function hideSchemCtx() {
  document.getElementById("schem-ctx").classList.remove("show");
}
document.addEventListener("click", hideSchemCtx);
document.addEventListener("keydown", e => { if (e.key === "Escape") hideSchemCtx(); });
document.addEventListener("scroll", hideSchemCtx, true);

document.getElementById("schemCtxRun").addEventListener("click", () => {
  if (!schemCtxTarget) return;
  const id = schemCtxTarget;
  fetch("/api/schematics/run", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id })
  })
    .then(r => r.json())
    .then(d => {
      if (d.ok) { toast("Build started — simulation and recording are launching"); fetchSchematics(); }
      else toast(d.error || "Could not start build", false);
    })
    .catch(() => toast("Could not start build", false));
});

document.getElementById("schemCtxQueue").addEventListener("click", () => {
  if (!schemCtxTarget) return;
  const id = schemCtxTarget;
  fetch("/api/queue/add", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id })
  })
    .then(r => r.json())
    .then(d => {
      if (d.ok) {
        toast("Added to production list");
        fetchSchematics();
        const t = document.querySelector(".nav-tab[data-panel='production']");
        t.style.background = "rgba(244,114,182,0.25)";
        setTimeout(() => t.style.background = "", 600);
      } else toast(d.error || "Could not queue build", false);
    })
    .catch(() => toast("Could not queue build", false));
});

document.getElementById("schemStopBtn").addEventListener("click", () => {
  fetch("/api/simulate/stop", { method: "POST" })
    .then(() => { toast("Simulation stopped"); fetchSchematics(); })
    .catch(() => {});
});

// ── Production List tab ─────────────────────────────────────────────────
let prodPollTimer = null, prodData = null;

function initProductionTab() {
  fetchQueue();
  if (!prodPollTimer) prodPollTimer = setInterval(fetchQueue, 2000);
}
function stopProdPoll() { clearInterval(prodPollTimer); prodPollTimer = null; }

function fetchQueue() {
  fetch("/api/queue").then(r => r.json())
    .then(d => { prodData = d; renderProd(); }).catch(() => {});
}

const PROD_STATUS = {
  queued:  ["Queued",   "ps-queued"],
  running: ["Building", "ps-running"],
  done:    ["Done",     "ps-done"],
  stopped: ["Stopped",  "ps-stopped"],
  failed:  ["Failed",   "ps-failed"],
};

function renderProd() {
  const d = prodData;
  if (!d) return;

  const badge = document.getElementById("prodState");
  badge.textContent = d.state;
  badge.className = "prod-state st-" + d.state;
  document.getElementById("prodPlayBtn").disabled  = d.state === "playing";
  document.getElementById("prodPauseBtn").disabled = d.state !== "playing";
  document.getElementById("prodStopBtn").disabled  = d.state === "stopped" && !d.current_uid;

  const cur = d.items.find(i => i.uid === d.current_uid);
  const box = document.getElementById("prodCurrent");
  if (cur) {
    box.style.display = "";
    document.getElementById("prodCurName").textContent = cur.name;
    const p   = d.progress && d.progress.total ? d.progress : null;
    const pct = p ? Math.min(100, Math.round(100 * (p.placed_total || 0) / p.total)) : 0;
    document.getElementById("prodProgFill").style.width = pct + "%";
    document.getElementById("prodProgLabel").textContent = p
      ? (p.placed_total || 0) + " / " + p.total + " blocks placed" + (p.pass ? "  ·  pass " + p.pass : "")
      : "Launching simulation — server, bot and recorder are starting…";
    const el = cur.started_at ? Math.max(0, Math.floor(Date.now() / 1000 - cur.started_at)) : 0;
    document.getElementById("prodCurMeta").textContent =
      Math.floor(el / 60) + "m " + (el % 60) + "s elapsed · recording";
  } else {
    box.style.display = "none";
  }

  const list = document.getElementById("prodList");
  document.getElementById("prodEmpty").style.display = d.items.length ? "none" : "";
  list.innerHTML = d.items.map((i, n) => {
    const st = PROD_STATUS[i.status] || [i.status, ""];
    const canMove = i.status === "queued";
    return "<div class='prod-row" + (i.status === "running" ? " running" : "") + "'>" +
      "<span class='prod-num'>" + (n + 1) + "</span>" +
      "<span class='prod-name'>" + i.name + "</span>" +
      "<span class='prod-meta'>" + i.block_count + " blocks · ~" + i.est_minutes + " min</span>" +
      (i.recording && i.status === "done" ? "<span class='prod-rec' title='" + i.recording + "'>✓ recorded</span>" : "") +
      "<span class='prod-status " + st[1] + "'>" + st[0] + "</span>" +
      "<span class='prod-actions'>" +
        (canMove
          ? "<button class='prod-mini' data-act='up' data-uid='" + i.uid + "'>▲</button>" +
            "<button class='prod-mini' data-act='down' data-uid='" + i.uid + "'>▼</button>"
          : "") +
        (i.status !== "running"
          ? "<button class='prod-mini danger' data-act='remove' data-uid='" + i.uid + "'>✕</button>"
          : "") +
      "</span>" +
    "</div>";
  }).join("");

  list.querySelectorAll(".prod-mini").forEach(btn => btn.addEventListener("click", () => {
    const act = btn.dataset.act, uid = btn.dataset.uid;
    const url  = act === "remove" ? "/api/queue/remove" : "/api/queue/move";
    const body = act === "remove" ? { uid } : { uid, dir: act };
    fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(r => r.json())
      .then(res => { if (!res.ok) toast(res.error || "Failed", false); fetchQueue(); })
      .catch(() => {});
  }));
}

function prodCmd(cmd, msg) {
  fetch("/api/queue/" + cmd, { method: "POST" })
    .then(r => r.json())
    .then(d => {
      if (d.ok === false) toast(d.error || "Failed", false);
      else if (msg) toast(msg);
      fetchQueue();
    })
    .catch(() => {});
}
document.getElementById("prodPlayBtn").addEventListener("click",  () => prodCmd("play", "Production started"));
document.getElementById("prodPauseBtn").addEventListener("click", () => prodCmd("pause", "Pausing — current build returns to the queue"));
document.getElementById("prodStopBtn").addEventListener("click",  () => prodCmd("stop", "Production stopped"));
document.getElementById("prodClearBtn").addEventListener("click", () => prodCmd("clear_done", "Cleared finished items"));

"""
