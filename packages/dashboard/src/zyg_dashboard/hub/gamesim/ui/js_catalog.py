# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Script: the GAMES catalogue, the label/class/order maps, the stats strip, the table and tab switching."""

JS_CATALOG = """<script>
const GAMES = [
  { name:"Minecraft",             tier:"1",  headless:"yes",     method:"server.jar — pure Java, no renderer",          lang:"Java / JS (Mineflayer)",   ram:1.5,   vram:0,    cpu:1.5, diff:"easy",       pop:"massive"   },
  { name:"Garry's Mod",           tier:"1",  headless:"yes",     method:"srcds dedicated server binary",                lang:"Lua",                       ram:1.5,   vram:0,    cpu:1.5, diff:"easy",       pop:"medium"    },
  { name:"StarCraft II",          tier:"1",  headless:"yes",     method:"-headless flag via PySC2 API",                 lang:"Python / Lua",              ram:2,     vram:0,    cpu:3,   diff:"medium",     pop:"medium"    },
  { name:"CS2 / CS:GO",           tier:"1",  headless:"yes",     method:"srcds dedicated server",                       lang:"CFG / SourceMod",           ram:1,     vram:0,    cpu:1.5, diff:"easy",       pop:"very-high" },
  { name:"DOTA 2",                tier:"1",  headless:"yes",     method:"Official headless bot training mode",          lang:"Lua",                       ram:3,     vram:0,    cpu:3,   diff:"medium",     pop:"very-high" },
  { name:"Team Fortress 2",       tier:"1",  headless:"yes",     method:"srcds dedicated server",                       lang:"Lua / SourceMod",           ram:1,     vram:0,    cpu:1.5, diff:"easy",       pop:"medium"    },
  { name:"Left 4 Dead 2",         tier:"1",  headless:"yes",     method:"srcds dedicated server",                       lang:"Lua / SourceMod",           ram:1.5,   vram:0,    cpu:2,   diff:"medium",     pop:"low"       },
  { name:"Valheim",               tier:"1",  headless:"yes",     method:"valheim_server binary",                        lang:"C# (BepInEx)",              ram:2,     vram:0,    cpu:2,   diff:"medium",     pop:"high"      },
  { name:"Rust",                  tier:"1",  headless:"yes",     method:"RustDedicated server binary",                  lang:"C# (Oxide/uMod)",           ram:6,     vram:0,    cpu:4,   diff:"medium",     pop:"high"      },
  { name:"ARK: Survival Evolved", tier:"1",  headless:"yes",     method:"ShooterGameServer binary",                     lang:"Python / C++",              ram:8,     vram:0,    cpu:4,   diff:"hard",       pop:"high"      },
  { name:"Screeps",               tier:"1",  headless:"yes",     method:"screeps-server npm package",                   lang:"JavaScript",                ram:0.5,   vram:0,    cpu:1,   diff:"easy",       pop:"niche"     },
  { name:"Roblox",                tier:"2",  headless:"partial", method:"Roblox Studio only (no dedicated server)",     lang:"Lua",                       ram:2,     vram:1.5,  cpu:2,   diff:"easy",       pop:"massive"   },
  { name:"Warcraft III",          tier:"2",  headless:"partial", method:"Wine + Xvfb on Linux (hacky on Windows)",      lang:"JASS / Lua",                ram:1.5,   vram:0.5,  cpu:2,   diff:"medium",     pop:"low"       },
  { name:"Unreal Tournament",     tier:"2",  headless:"partial", method:"-nullrhi flag disables renderer",              lang:"UnrealScript",              ram:2,     vram:0.25, cpu:2,   diff:"medium",     pop:"niche"     },
  { name:"Among Us",              tier:"2",  headless:"partial", method:"Impostor custom server (no client renderer)",  lang:"C#",                        ram:0.5,   vram:0,    cpu:1,   diff:"easy",       pop:"low"       },
  { name:"Overwatch 2",           tier:"2",  headless:"partial", method:"Workshop scripting only (in-client)",          lang:"Workshop Script",           ram:6,     vram:3,    cpu:4,   diff:"medium",     pop:"very-high" },
  { name:"GTA V (FiveM/RAGE)",    tier:"3",  headless:"no",      method:"Always needs full GPU render pipeline",        lang:"Lua / C# / JS",             ram:8,     vram:5,    cpu:4,   diff:"hard",       pop:"massive"   },
  { name:"Age of Empires II DE",  tier:"3",  headless:"no",      method:"No dedicated server — always renders",         lang:".per scripts",              ram:4,     vram:2,    cpu:3,   diff:"hard",       pop:"medium"    },
  { name:"Halo MCC",              tier:"3",  headless:"no",      method:"No headless mode available",                   lang:"Built-in only",             ram:4,     vram:3.5,  cpu:4,   diff:"hard",       pop:"medium"    },
  { name:"Fortnite",              tier:"3",  headless:"no",      method:"Closed platform — no server/mod access",       lang:"N/A (closed)",              ram:8,     vram:4,    cpu:4,   diff:"impossible",  pop:"massive"   },
  { name:"League of Legends",     tier:"3",  headless:"no",      method:"No official bot API — ToS restrictions",       lang:"Limited (Riot API)",        ram:4,     vram:2,    cpu:3,   diff:"hard",       pop:"massive"   },
  { name:"OpenAI Gym",            tier:"ai", headless:"yes",     method:"Python library — runs entirely in code",       lang:"Python",                    ram:0.25,  vram:0,    cpu:1,   diff:"easy",       pop:"niche"     },
  { name:"Unity ML-Agents",       tier:"ai", headless:"yes",     method:"Unity -batchmode -nographics flag",            lang:"C# / Python",               ram:1,     vram:0,    cpu:2,   diff:"medium",     pop:"niche"     },
  { name:"PySC2 (DeepMind API)",  tier:"ai", headless:"yes",     method:"Official DeepMind StarCraft II API",           lang:"Python",                    ram:2,     vram:0,    cpu:3,   diff:"medium",     pop:"niche"     },
  { name:"OpenSpiel",             tier:"ai", headless:"yes",     method:"Google multi-agent game theory framework",     lang:"Python / C++",              ram:0.25,  vram:0,    cpu:1,   diff:"easy",       pop:"niche"     },
  { name:"Pygame (custom arena)", tier:"ai", headless:"yes",     method:"Build any arena from scratch in Python",       lang:"Python",                    ram:0.125, vram:0,    cpu:1,   diff:"easy",       pop:"niche"     },
];

const TIER_LABEL = { "1":"Tier 1", "2":"Tier 2", "3":"Tier 3", ai:"AI / Research" };
const TIER_CLS   = { "1":"t1", "2":"t2", "3":"t3", ai:"tai" };
const HL_LABEL   = { yes:"Yes", partial:"Partial", no:"No" };
const HL_CLS     = { yes:"hl-yes", partial:"hl-partial", no:"hl-no" };
const DIFF_LABEL = { easy:"Easy", medium:"Medium", hard:"Hard", impossible:"Impossible" };
const DIFF_CLS   = { easy:"d-easy", medium:"d-medium", hard:"d-hard", impossible:"d-impossible" };
const POP_LABEL  = { "massive":"Massive", "very-high":"Very High", high:"High", medium:"Medium", low:"Low", niche:"Niche" };
const POP_CLS    = { "massive":"pop-massive", "very-high":"pop-very-high", high:"pop-high", medium:"pop-medium", low:"pop-low", niche:"pop-niche" };
const TIER_ORD   = { "1":1, "2":2, "3":3, ai:4 };
const HL_ORD     = { yes:1, partial:2, no:3 };
const DIFF_ORD   = { easy:1, medium:2, hard:3, impossible:4 };
const POP_ORD    = { "massive":6, "very-high":5, high:4, medium:3, low:2, niche:1 };

function fmtRam(v)  { return v >= 1 ? v + " GB" : Math.round(v*1024) + " MB"; }
function fmtVram(v) { return v === 0 ? "0 MB" : v >= 1 ? v + " GB" : Math.round(v*1024) + " MB"; }
function fmtCpu(v)  { return v % 1 === 0 ? v : "1–2"; }

// Stats
const yesGames  = GAMES.filter(g => g.headless === "yes");
const partGames = GAMES.filter(g => g.headless === "partial");
const noGames   = GAMES.filter(g => g.headless === "no");
const easyGames = GAMES.filter(g => g.diff === "easy");
document.getElementById("statTotal").textContent   = GAMES.length;
document.getElementById("statYes").textContent     = yesGames.length;
document.getElementById("statPartial").textContent = partGames.length;
document.getElementById("statNo").textContent      = noGames.length;
document.getElementById("statEasy").textContent    = easyGames.map(g=>g.name).slice(0,3).join(", ");

let filter = "all", query = "", sortC = "tier", sortD = 1;

// declared here so render() can reference them
const selected  = new Set();
const installed = new Set(JSON.parse(localStorage.getItem("gamesim_installed") || "[]"));

function saveInstalled() {
  localStorage.setItem("gamesim_installed", JSON.stringify([...installed]));
}

// Auto-detect installed games from server filesystem on load
fetch("/api/installed")
  .then(r => r.json())
  .then(names => {
    let changed = false;
    names.forEach(name => {
      if (!installed.has(name)) { installed.add(name); changed = true; }
    });
    if (changed) {
      saveInstalled();
      // Re-render grid if Creation tab is active
      if (document.getElementById("panel-installed").style.display !== "none") {
        renderGrid(document.getElementById("createSearch").value.trim());
      }
    }
  })
  .catch(() => {}); // silently ignore if API unreachable

function sortVal(g, c) {
  if (c === "name")     return g.name.toLowerCase();
  if (c === "tier")     return TIER_ORD[g.tier];
  if (c === "headless") return HL_ORD[g.headless];
  if (c === "lang")     return g.lang.toLowerCase();
  if (c === "ram")      return g.ram;
  if (c === "vram")     return g.vram;
  if (c === "cpu")      return g.cpu;
  if (c === "diff")     return DIFF_ORD[g.diff];
  if (c === "pop")      return POP_ORD[g.pop];
  return g.name;
}

function render() {
  let list = GAMES.filter(g => {
    if (filter !== "all" && g.headless !== filter) return false;
    if (query) {
      const q = query.toLowerCase();
      return g.name.toLowerCase().includes(q) ||
             g.method.toLowerCase().includes(q) ||
             g.lang.toLowerCase().includes(q) ||
             TIER_LABEL[g.tier].toLowerCase().includes(q);
    }
    return true;
  });

  list.sort((a, b) => {
    const va = sortVal(a, sortC), vb = sortVal(b, sortC);
    return va < vb ? -sortD : va > vb ? sortD : 0;
  });

  document.getElementById("countTag").textContent = list.length + " of " + GAMES.length + " games";

  const tbody = document.getElementById("tbody");
  if (!list.length) {
    tbody.innerHTML = "<tr class='empty-row'><td colspan='9'>No games match your search.</td></tr>";
    return;
  }

  tbody.innerHTML = list.map(g => {
    const vramCell = g.vram === 0
      ? "<span class='spec-val spec-zero'>0 MB</span>"
      : "<span class='spec-val'>" + fmtVram(g.vram) + "</span>";
    const safeName = g.name.replace(/'/g, "&#39;");
    const activated = selected.has(g.name) ? " row-activated" : "";
    return "<tr data-game='" + safeName + "' class='" + activated + "'>" +
      "<td><span class='game-name'>" + g.name + "</span></td>" +
      "<td><span class='tier-badge " + TIER_CLS[g.tier] + "'>" + TIER_LABEL[g.tier] + "</span></td>" +
      "<td><span class='hl-badge " + HL_CLS[g.headless] + "'>" + HL_LABEL[g.headless] + "</span></td>" +
      "<td><span class='method-text'>" + g.method + "</span></td>" +
      "<td><span class='lang-tag'>" + g.lang + "</span></td>" +
      "<td><span class='spec-val'>" + fmtRam(g.ram) + "</span></td>" +
      "<td>" + vramCell + "</td>" +
      "<td><span class='spec-val'>" + g.cpu + "</span></td>" +
      "<td><span class='diff-badge " + DIFF_CLS[g.diff] + "'>" + DIFF_LABEL[g.diff] + "</span></td>" +
      "<td><span class='pop-badge " + POP_CLS[g.pop] + "'><span class='pop-dot'></span>" + POP_LABEL[g.pop] + "</span></td>" +
    "</tr>";
  }).join("");
}

document.querySelectorAll("thead th[data-c]").forEach(th => {
  th.addEventListener("click", () => {
    const c = th.dataset.c;
    if (!c || c === "method") return;
    if (sortC === c) { sortD *= -1; }
    else { sortC = c; sortD = 1; }
    document.querySelectorAll("thead th").forEach(h => h.classList.remove("asc","desc"));
    th.classList.add(sortD === 1 ? "asc" : "desc");
    render();
  });
});

document.querySelectorAll(".chip").forEach(chip => {
  chip.addEventListener("click", () => {
    document.querySelectorAll(".chip").forEach(c => c.classList.remove("active"));
    chip.classList.add("active");
    filter = chip.dataset.f;
    render();
  });
});

document.getElementById("search").addEventListener("input", e => {
  query = e.target.value.trim();
  render();
});

document.querySelector("thead th[data-c='tier']").classList.add("asc");
render();

// ── Tab switching ──────────────────────────────────────────────────────
document.querySelectorAll(".nav-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-tab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    const p = btn.dataset.panel;
    document.getElementById("panel-req").style.display        = p === "req"        ? "" : "none";
    document.getElementById("panel-installed").style.display  = p === "installed"   ? "" : "none";
    document.getElementById("panel-creation").style.display   = p === "creation"    ? "" : "none";
    document.getElementById("panel-library").style.display    = p === "library"     ? "" : "none";
    document.getElementById("panel-benchmark").style.display  = p === "benchmark"   ? "" : "none";
    document.getElementById("panel-schematics").style.display = p === "schematics"  ? "" : "none";
    document.getElementById("panel-production").style.display = p === "production"  ? "" : "none";
    document.getElementById("panel-creator").style.display    = p === "creator"     ? "" : "none";
    if (p === "installed")  renderGrid(document.getElementById("createSearch").value.trim());
    if (p === "creation")   renderGLP();
    if (p === "library")    fetchLibrary();
    if (p === "benchmark")  initBenchPanel();
    if (p === "schematics") initSchematicsTab(); else stopSchemPoll();
    if (p === "production") initProductionTab(); else stopProdPoll();
    if (p === "creator")    initCreatorTab();
  });
});

"""
