# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Script: the Content Library and the video modal."""

JS_LIBRARY = """// ── Content Library ────────────────────────────────────────────────────
const GAME_COLORS = {
  "Minecraft":             "#4ade80",
  "Minecraft Build/Mine":  "#86efac",
  "Minecraft Dig FP":      "#78716c",
  "Minecraft Build FP":    "#a8a29e",
  "CS2 / CS:GO":          "#f87171",
  "DOTA 2":               "#c084fc",
  "Team Fortress 2":      "#fb923c",
  "Valheim":              "#38bdf8",
  "Rust":                 "#f97316",
  "Overwatch 2":          "#f472b6",
  "Roblox":               "#fbbf24",
  "Garry's Mod":          "#a3e635",
  "StarCraft II":         "#60a5fa",
  "Left 4 Dead 2":        "#ef4444",
  "Fortnite":             "#818cf8",
  "League of Legends":    "#eab308",
};

let libData = [];

function timeAgo(ts) {
  const secs = Math.floor(Date.now() / 1000) - ts;
  if (secs < 60)   return secs + "s ago";
  if (secs < 3600) return Math.floor(secs / 60) + "m ago";
  if (secs < 86400) return Math.floor(secs / 3600) + "h ago";
  return Math.floor(secs / 86400) + "d ago";
}

function fetchLibrary() {
  fetch("/api/recordings")
    .then(r => r.json())
    .then(data => { libData = data; renderLibrary(); })
    .catch(() => { libData = []; renderLibrary(); });
}

function renderLibrary() {
  const q      = document.getElementById("libSearch").value.trim().toLowerCase();
  const sort   = document.getElementById("libSort").value;
  const empty  = document.getElementById("lib-empty");
  const grid   = document.getElementById("lib-grid");
  const countEl = document.getElementById("libCount");

  let list = q ? libData.filter(r => r.game.toLowerCase().includes(q)) : [...libData];

  if (sort === "date") list.sort((a, b) => b.ts - a.ts);
  else if (sort === "game") list.sort((a, b) => a.game.localeCompare(b.game) || b.ts - a.ts);
  else if (sort === "size") list.sort((a, b) => b.size_mb - a.size_mb);

  countEl.textContent = list.length + " recording" + (list.length !== 1 ? "s" : "");

  if (!list.length) {
    empty.style.display = "";
    grid.innerHTML = "";
    return;
  }
  empty.style.display = "none";

  // Group by game
  const groups = {};
  list.forEach(r => {
    if (!groups[r.game]) groups[r.game] = [];
    groups[r.game].push(r);
  });

  grid.innerHTML = Object.entries(groups).map(([game, recs]) => {
    const color = GAME_COLORS[game] || "#94a3b8";
    const cards = recs.map(r => {
      const instLabel = r.instance > 1 ? "Inst #" + r.instance : "";
      return `<div class="lib-card" data-filename="${r.filename}" data-game="${game}">
        <div class="lib-card-preview">
          <div class="lib-card-thumb">
            <svg viewBox="0 0 24 24" style="width:64px;height:64px;stroke:${color};fill:none;stroke-width:1;stroke-linecap:round">
              <rect x="2" y="7" width="20" height="15" rx="2"/>
              <polyline points="17 2 12 7 7 2"/>
              <polygon points="10,11 10,17 16,14" fill="${color}" opacity="0.4"/>
            </svg>
          </div>
          <video preload="metadata" muted loop data-src="/recordings/${r.filename}"></video>
          <div class="lib-play-btn">
            <div class="lib-play-circle">
              <svg viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            </div>
          </div>
          <span class="lib-game-badge" style="background:${color}22;color:${color};border:1px solid ${color}44">${game}</span>
          ${instLabel ? `<span class="lib-inst-badge">${instLabel}</span>` : ""}
          <button class="lib-delete-btn" data-del="${r.filename}" title="Delete">×</button>
        </div>
        <div class="lib-card-info">
          <div class="lib-card-name">${r.filename}</div>
          <div class="lib-card-meta">
            <span>🕐 ${timeAgo(r.ts)}</span>
            <span>💾 ${r.size_mb} MB</span>
          </div>
        </div>
      </div>`;
    }).join("");

    return `<div class="lib-group">
      <div class="lib-group-title" style="color:${color}">${game} <span style="color:#334155;font-size:10px;text-transform:none;letter-spacing:0">${recs.length} clip${recs.length !== 1 ? "s" : ""}</span></div>
      <div class="lib-group-cards">${cards}</div>
    </div>`;
  }).join("");

  // Bind card events
  grid.querySelectorAll(".lib-card").forEach(card => {
    const filename = card.dataset.filename;
    const game     = card.dataset.game;
    const video    = card.querySelector("video");
    const src      = video.dataset.src;

    // Lazy-load video on hover for preview
    card.addEventListener("mouseenter", () => {
      if (!video.src && src) {
        video.src = src;
        video.load();
        video.addEventListener("loadeddata", () => video.classList.add("loaded"), { once: true });
      }
      video.play().catch(() => {});
    });
    card.addEventListener("mouseleave", () => {
      video.pause();
      video.currentTime = 0;
    });

    // Click card → open modal (but not delete btn)
    card.addEventListener("click", e => {
      if (e.target.closest(".lib-delete-btn")) return;
      openModal("/recordings/" + filename, game + " — " + filename,
        "Game: " + game + "  •  File: " + filename);
    });
  });

  // Delete buttons
  grid.querySelectorAll(".lib-delete-btn").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      const filename = btn.dataset.del;
      if (!confirm("Delete " + filename + "?")) return;
      fetch("/api/recordings/" + encodeURIComponent(filename), { method: "DELETE" })
        .then(r => r.json())
        .then(d => { if (d.ok) fetchLibrary(); });
    });
  });
}

// ── Video modal ─────────────────────────────────────────────────────────
function openModal(src, title, meta) {
  const modal  = document.getElementById("vid-modal");
  const player = document.getElementById("vidModalPlayer");
  document.getElementById("vidModalTitle").textContent = title;
  document.getElementById("vidModalMeta").textContent  = meta;
  player.pause();
  player.src = src;
  player.load();
  modal.style.display = "";
}

function closeModal() {
  const modal  = document.getElementById("vid-modal");
  const player = document.getElementById("vidModalPlayer");
  player.pause();
  player.src = "";
  modal.style.display = "none";
}

document.getElementById("vidModalClose").addEventListener("click", closeModal);
document.getElementById("vidModalBg").addEventListener("click", closeModal);
document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });

"""
