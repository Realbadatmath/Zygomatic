# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Script: the Schematic Creator — recipe editor, material palette, compile, preview, layer painter, sources."""

JS_CREATOR = """// ── Schematic Creator ───────────────────────────────────────────────────
// The tab is a thin authoring surface over one idea: everything you can do here
// bakes to a block list, and hub/schem_compiler.py decides whether the bot can
// actually build it. The verdict panel is never hidden, because the constraints
// are only learnable if you see them react as you edit.
let crCatalog = null;
let crDraft = { ops: [] };
let crLast = { blocks: [], report: null };
let crMat = "stone_bricks";
let crMode = "iso";
let crLayerY = 65;
let crRotate = 0.0;
let crCompileTimer = null;
let crCompiling = false;

function crColor(mat) {
  if (crCatalog && crCatalog.colorMap[mat]) {
    const c = crCatalog.colorMap[mat];
    return "rgb(" + c[0] + "," + c[1] + "," + c[2] + ")";
  }
  return MAT_COLORS[mat] || "#9aa0a6";
}

function initCreatorTab() {
  if (crCatalog) { crRender(); return; }
  fetch("/api/creator/catalog").then(r => r.json()).then(d => {
    crCatalog = d;
    crCatalog.colorMap = {};
    d.palette.forEach(m => { crCatalog.colorMap[m.n] = m.c; });
    ["stairs", "slabs", "doors"].forEach(g =>
      d.oriented[g].forEach(m => { crCatalog.colorMap[m.n] = m.c; }));
    // Share the real texture colours with the Schematics board too.
    Object.assign(PALETTE_COLORS, crCatalog.colorMap);
    crRenderPalette("");
    if (!crDraft.ops.length) crSeedDefault();
    crRender();
  }).catch(() => toast("Could not load the block catalogue", false));
}

// A starter recipe, so the tab is never an empty canvas: a real tower you can
// immediately publish, then take apart to learn the vocabulary.
function crSeedDefault() {
  crDraft = {
    name: "", category: "Tower", difficulty: "medium",
    ops: [
      { op: "box", params: { x0: -3, x1: 3, z0: -9, z1: -3, y0: 65, y1: 70,
          mats: ["stone_bricks", "cobblestone", "mossy_stone_bricks"],
          corner_mat: "dark_oak_log", pattern: "noise", hollow: true } },
      { op: "erase", params: { x0: -1, x1: 1, y0: 65, y1: 66, z0: -3, z1: -3 } },
      { op: "stair_ring", params: { x0: -3, x1: 3, z0: -9, z1: -3, ybase: 65, ytop: 70,
          mat: "cobblestone", inset: 1 } },
      { op: "battlements", params: { x0: -3, x1: 3, z0: -9, z1: -3, y: 71,
          mat: "chiseled_stone_bricks", every: 2 } },
    ],
  };
}

// ── Recipe editor ──
function crRender() {
  crRenderOps();
  crCompileSoon();
}

function crParamField(opIdx, op, spec) {
  const v = op.params[spec.k] !== undefined ? op.params[spec.k] : spec.d;
  const id = "crp_" + opIdx + "_" + spec.k;
  let field;
  if (spec.t === "bool") {
    field = "<input type='checkbox' id='" + id + "' " + (v ? "checked" : "") + ">";
  } else if (spec.t === "enum") {
    field = "<select id='" + id + "'>" + spec.opts.map(o =>
      "<option" + (String(o) === String(v) ? " selected" : "") + ">" + o + "</option>").join("") + "</select>";
  } else if (spec.t === "int") {
    field = "<input type='number' id='" + id + "' value='" + v + "'>";
  } else if (spec.t === "mat" || spec.t === "mats") {
    const val = Array.isArray(v) ? v.join(", ") : (v || "");
    field = "<input type='text' id='" + id + "' value='" + val + "' placeholder='block name'>";
  } else if (spec.t === "ints" || spec.t === "cells") {
    field = "<input type='text' id='" + id + "' value='" + JSON.stringify(v || []) + "'>";
  } else {
    return "";  // 'blocks' is edited by the painter, not by hand
  }
  return "<div class='cr-p'><label>" + spec.k + "</label>" + field + "</div>";
}

function crRenderOps() {
  const box = document.getElementById("crOps");
  document.getElementById("crOpCount").textContent = crDraft.ops.length + " ops";
  box.innerHTML = crDraft.ops.map((op, i) => {
    const meta = (crCatalog.ops[op.op]) || { label: op.op, params: [] };
    const painted = op.op === "voxels";
    const n = painted ? (op.params.blocks || []).length + " cells" : "";
    return "<div class='cr-op" + (op.muted ? " muted" : "") + (op._open ? " open" : "") + "' data-i='" + i + "'>" +
      "<div class='cr-op-head' data-act='toggle'>" +
        "<span class='cr-op-name'>" + (painted ? "Painted Cells" : meta.label) + "</span>" +
        "<span class='cr-op-n'>" + n + "</span>" +
        "<button class='cr-mini' data-act='up' title='Earlier'>▲</button>" +
        "<button class='cr-mini' data-act='down' title='Later'>▼</button>" +
        "<button class='cr-mini' data-act='mute' title='Mute'>" + (op.muted ? "○" : "◉") + "</button>" +
        "<button class='cr-mini danger' data-act='del' title='Remove'>✕</button>" +
      "</div>" +
      "<div class='cr-op-body'>" +
        (painted ? "<div style='font-size:10px;color:var(--muted)'>Edited with the layer painter.</div>"
                 : (meta.params || []).map(s => crParamField(i, op, s)).join("")) +
      "</div>" +
    "</div>";
  }).join("");

  box.querySelectorAll(".cr-op").forEach(el => {
    const i = +el.dataset.i;
    el.querySelectorAll("[data-act]").forEach(btn => {
      btn.addEventListener("click", e => {
        e.stopPropagation();
        const act = btn.dataset.act;
        if (act === "toggle") { crDraft.ops[i]._open = !crDraft.ops[i]._open; crRenderOps(); return; }
        if (act === "mute") { crDraft.ops[i].muted = !crDraft.ops[i].muted; }
        if (act === "del") { crDraft.ops.splice(i, 1); }
        if (act === "up" && i > 0) { const t = crDraft.ops[i]; crDraft.ops[i] = crDraft.ops[i-1]; crDraft.ops[i-1] = t; }
        if (act === "down" && i < crDraft.ops.length - 1) { const t = crDraft.ops[i]; crDraft.ops[i] = crDraft.ops[i+1]; crDraft.ops[i+1] = t; }
        crRender();
      });
    });
    // Param edits: read the field back into the recipe, then recompile.
    el.querySelectorAll("input,select").forEach(inp => {
      inp.addEventListener("change", () => {
        const key = inp.id.split("_").slice(2).join("_");
        const meta = crCatalog.ops[crDraft.ops[i].op];
        const spec = (meta.params || []).find(s => s.k === key);
        if (!spec) return;
        let val;
        if (spec.t === "bool") val = inp.checked;
        else if (spec.t === "int") val = parseInt(inp.value) || 0;
        else if (spec.t === "mats") val = inp.value.split(",").map(s => s.trim()).filter(Boolean);
        else if (spec.t === "ints" || spec.t === "cells") { try { val = JSON.parse(inp.value); } catch (_) { return; } }
        else val = inp.value.trim();
        crDraft.ops[i].params[key] = val;
        crCompileSoon();
      });
    });
  });
}

document.getElementById("crAddOp").addEventListener("click", () => {
  const names = Object.keys(crCatalog.ops);
  const menu = names.map((n, i) => (i + 1) + ") " + crCatalog.ops[n].label).join("\\n");
  const pick = prompt("Add a step:\\n\\n" + menu + "\\n\\nNumber:");
  const idx = parseInt(pick) - 1;
  if (isNaN(idx) || idx < 0 || idx >= names.length) return;
  const name = names[idx];
  const params = {};
  (crCatalog.ops[name].params || []).forEach(s => { params[s.k] = s.d; });
  crDraft.ops.push({ op: name, params, _open: true });
  crRender();
});

// ── Material palette ──
function crRenderPalette(q) {
  const list = crCatalog.palette
    .concat(crCatalog.oriented.stairs, crCatalog.oriented.slabs, crCatalog.oriented.doors)
    .filter(m => !q || m.n.includes(q.toLowerCase()));
  document.getElementById("crPal").innerHTML = list.slice(0, 220).map(m =>
    "<div class='cr-swatch" + (m.n === crMat ? " on" : "") + "' data-m='" + m.n + "' title='" + m.n +
    "' style='background:rgb(" + m.c[0] + "," + m.c[1] + "," + m.c[2] + ")'></div>").join("");
  document.getElementById("crPal").querySelectorAll(".cr-swatch").forEach(s =>
    s.addEventListener("click", () => {
      crMat = s.dataset.m;
      crRenderPalette(document.getElementById("crMatSearch").value.trim());
      document.getElementById("crCurMat").textContent = crMat;
      document.getElementById("crCurSw").style.background = crColor(crMat);
    }));
  document.getElementById("crCurSw").style.background = crColor(crMat);
  document.getElementById("crCurMat").textContent = crMat;
}
document.getElementById("crMatSearch").addEventListener("input", e =>
  crRenderPalette(e.target.value.trim()));

// ── Compile (debounced) ──
function crCompileSoon() {
  clearTimeout(crCompileTimer);
  crCompileTimer = setTimeout(crCompile, 350);
}

function crCompile() {
  if (crCompiling) { crCompileSoon(); return; }
  const ops = crDraft.ops.filter(o => !o.muted);
  if (!ops.length) {
    crLast = { blocks: [], report: null };
    crSetVerdict("busy", "— nothing to build yet");
    crDrawPreview();
    return;
  }
  crCompiling = true;
  crSetVerdict("busy", "⟳ proving buildability…");
  fetch("/api/creator/compile", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ops: ops.map(o => ({ op: o.op, params: o.params })) })
  })
    .then(r => r.json())
    .then(d => {
      crCompiling = false;
      if (!d.ok) { crSetVerdict("bad", "✕ " + d.error); crLast = { blocks: [], report: null }; crDrawPreview(); return; }
      crLast = { blocks: d.blocks, report: d.report };
      crShowReport(d.report);
      crDrawPreview();
    })
    .catch(() => { crCompiling = false; crSetVerdict("bad", "✕ compile failed"); });
}

function crSetVerdict(kind, text) {
  const el = document.getElementById("crVerdict");
  el.className = "cr-verdict " + (kind === "ok" ? "cr-ok" : kind === "bad" ? "cr-bad" : "cr-busy");
  el.textContent = text;
  document.getElementById("crSave").disabled = kind !== "ok";
}

function crShowReport(r) {
  const unb = r.stats.unbuilt || 0;
  crSetVerdict(r.certified ? "ok" : "bad",
    r.certified ? "✓ the bot can build this" : "✕ " + unb + " block" + (unb === 1 ? "" : "s") + " unreachable");
  document.getElementById("crStBlocks").textContent = r.block_count;
  document.getElementById("crStPlaced").textContent = r.stats.placed || 0;
  document.getElementById("crStScaf").textContent = (r.scaffold || []).length;
  document.getElementById("crStSlots").textContent = r.slots + " / 36";
  document.getElementById("crStPasses").textContent = r.passes;
  const mins = Math.max(1, Math.round((r.stats.placed || 0) * 1.8 / 60) + 2);
  document.getElementById("crStTime").textContent = "~" + mins + " min";

  const issues = [];
  (r.errors || []).forEach(e => issues.push({ w: false, t: e.detail }));
  (r.unbuilt || []).slice(0, 12).forEach(u => issues.push({
    w: false, t: u.mat + " at " + u.pos.join(",") + " — " +
      (u.verdict === "nosupport" ? "nothing to place against" : "bot cannot reach it")
  }));
  (r.warnings || []).forEach(w => issues.push({ w: true, t: w.detail }));
  document.getElementById("crIssues").innerHTML = issues.map(i =>
    "<div class='cr-issue" + (i.w ? " warn" : "") + "'>" + i.t + "</div>").join("");

  const mats = Object.entries(r.materials || {}).sort((a, b) => b[1] - a[1]);
  document.getElementById("crMats").innerHTML = mats.map(([m, n]) =>
    "<div class='cr-mat'><span class='cr-sw' style='background:" + crColor(m) + "'></span>" +
    m + " <b style='margin-left:auto;color:var(--text)'>" + n + "</b></div>").join("");
}

// ── Preview ──
// Unbuildable cells paint red and scaffold paints amber, on the same isometric
// projection the kanban cards use — so what you see here is what gets built.
function crDrawPreview() {
  const cv = document.getElementById("crCanvas");
  const grid = document.getElementById("crGridWrap");
  if (crMode === "paint") {
    cv.style.display = "none"; grid.style.display = "";
    crDrawGrid();
    return;
  }
  cv.style.display = ""; grid.style.display = "none";

  const bad = new Set((crLast.report ? crLast.report.unbuilt : []).map(u => u.pos.join(",")));
  const scaf = new Set((crLast.report ? crLast.report.scaffold || [] : []).map(s => [s.x, s.y, s.z].join(",")));
  drawSchematic(cv, crLast.blocks, {
    rotate: crRotate,
    colorFn: b => {
      const k = [b.x, b.y, b.z].join(",");
      if (bad.has(k)) return "#ef4444";
      if (scaf.has(k)) return "#fbbf24";
      return crColor(b.mat);
    }
  });
}

// Drag to orbit the preview.
(function () {
  const cv = document.getElementById("crCanvas");
  let down = false, lastX = 0;
  cv.addEventListener("mousedown", e => { down = true; lastX = e.clientX; });
  window.addEventListener("mouseup", () => { down = false; });
  window.addEventListener("mousemove", e => {
    if (!down || crMode !== "iso") return;
    crRotate += (e.clientX - lastX) * 0.01;
    lastX = e.clientX;
    crDrawPreview();
  });
})();

// ── Layer painter ──
// Picking is trivial in 2D (floor(mx/cell)), which is exactly why the painter is
// a per-layer grid rather than a 3D gizmo: no raycasting, no ambiguity.
function crVoxOp() {
  let op = crDraft.ops.find(o => o.op === "voxels");
  if (!op) { op = { op: "voxels", params: { blocks: [] } }; crDraft.ops.push(op); }
  return op;
}

function crDrawGrid() {
  const z0 = crCatalog.model.zone.z0, z1 = crCatalog.model.zone.z1;
  const x0 = crCatalog.model.zone.x0, x1 = crCatalog.model.zone.x1;
  const cols = x1 - x0 + 1, rows = z1 - z0 + 1;
  const at = {}, below = {};
  crLast.blocks.forEach(b => {
    if (b.y === crLayerY) at[b.x + "," + b.z] = b.mat;
    if (b.y === crLayerY - 1) below[b.x + "," + b.z] = b.mat;
  });
  const bad = new Set((crLast.report ? crLast.report.unbuilt : [])
    .filter(u => u.pos[1] === crLayerY).map(u => u.pos[0] + "," + u.pos[2]));

  let html = "<div class='cr-grid' style='grid-template-columns:repeat(" + cols +
    ",1fr);max-width:" + (cols * 30) + "px'>";
  for (let z = z0; z <= z1; z++) {
    for (let x = x0; x <= x1; x++) {
      const k = x + "," + z;
      const m = at[k], b = below[k];
      const col = m ? crColor(m) : (b ? crColor(b) : "#0f172a");
      html += "<div class='cr-cell" + (!m && b ? " below" : "") + (bad.has(k) ? " bad" : "") +
        "' data-x='" + x + "' data-z='" + z + "' title='" + x + "," + crLayerY + "," + z +
        (m ? " " + m : "") + "' style='background:" + col + "'></div>";
    }
  }
  html += "</div>";
  const wrap = document.getElementById("crGridWrap");
  wrap.innerHTML = html;
  wrap.querySelectorAll(".cr-cell").forEach(c => {
    const paint = e => {
      if (e.buttons !== 1 && e.type === "mouseover") return;
      const x = +c.dataset.x, z = +c.dataset.z;
      const op = crVoxOp();
      const list = op.params.blocks;
      const i = list.findIndex(b => b.x === x && b.y === crLayerY && b.z === z);
      if (e.shiftKey) { if (i >= 0) list.splice(i, 1); }
      else if (i >= 0) list[i].mat = crMat;
      else list.push({ x, y: crLayerY, z, mat: crMat, kind: "voxel" });
      crRenderOps();
      crCompileSoon();
    };
    c.addEventListener("mousedown", paint);
    c.addEventListener("mouseover", paint);
  });
}

document.getElementById("crModeIso").addEventListener("click", () => {
  crMode = "iso";
  document.getElementById("crModeIso").classList.add("on");
  document.getElementById("crModePaint").classList.remove("on");
  document.getElementById("crLayerCtl").style.display = "none";
  document.getElementById("crViewTitle").textContent = "Preview";
  document.getElementById("crHint").textContent = "drag to rotate";
  crDrawPreview();
});
document.getElementById("crModePaint").addEventListener("click", () => {
  crMode = "paint";
  document.getElementById("crModePaint").classList.add("on");
  document.getElementById("crModeIso").classList.remove("on");
  const c = document.getElementById("crLayerCtl");
  c.style.display = "flex";
  document.getElementById("crViewTitle").textContent = "Paint layer";
  document.getElementById("crHint").textContent = "click to paint · shift-click to erase";
  crDrawPreview();
});
document.getElementById("crLayer").addEventListener("input", e => {
  crLayerY = +e.target.value;
  document.getElementById("crLayerY").textContent = crLayerY;
  if (crMode === "paint") crDrawGrid();
});

// ── Sources ──
document.getElementById("crNew").addEventListener("click", () => {
  crDraft = { ops: [] };
  document.getElementById("crName").value = "";
  crRender();
});

document.getElementById("crFork").addEventListener("click", () => {
  const ids = schemData.map(s => s.id);
  const pick = prompt("Fork which schematic?\\n\\n" + ids.map((n, i) => (i + 1) + ") " + n).join("\\n") + "\\n\\nNumber:");
  const i = parseInt(pick) - 1;
  if (isNaN(i) || i < 0 || i >= ids.length) return;
  fetch("/api/creator/fork", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: ids[i] })
  }).then(r => r.json()).then(d => {
    if (!d.ok) { toast(d.error, false); return; }
    crDraft = { ops: d.ops };
    document.getElementById("crName").value = d.name;
    document.getElementById("crCat").value = d.category;
    document.getElementById("crDiff").value = d.difficulty;
    toast(d.parametric ? "Forked as an editable recipe" : "Forked as painted cells (built-ins have no recipe)");
    crRender();
  });
});

document.getElementById("crImport").addEventListener("click", () =>
  document.getElementById("crFile").click());

document.getElementById("crFile").addEventListener("change", e => {
  const f = e.target.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  toast("Importing " + f.name + "…");
  fetch("/api/creator/import", { method: "POST", body: fd })
    .then(r => r.json())
    .then(d => {
      if (!d.ok) { toast(d.error, false); return; }
      crDraft = { ops: [{ op: "voxels", params: { blocks: d.blocks } }] };
      document.getElementById("crName").value = d.name;
      let msg = "Imported " + d.kept + "/" + d.imported + " blocks";
      if (d.dropped.length) msg += " · dropped " + d.dropped.length + " unplaceable types";
      toast(msg);
      crRender();
    })
    .catch(() => toast("Import failed", false));
  e.target.value = "";
});

document.getElementById("crCapture").addEventListener("click", () => {
  const box = prompt("Capture a region you built in-game.\\n\\nfrom x y z / to x y z:", "-6 65 -12 / 6 78 -2");
  if (!box) return;
  const parts = box.split("/").map(s => s.trim().split(/[ ]+/).map(Number));
  if (parts.length !== 2 || parts[0].length !== 3 || parts[1].length !== 3) {
    toast("Could not read that region", false); return;
  }
  toast("Capturing — a bot is joining the server to read the blocks…");
  fetch("/api/creator/capture", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ from: parts[0], to: parts[1] })
  }).then(r => r.json()).then(d => {
    if (!d.ok) { toast(d.error, false); return; }
    crDraft = { ops: [{ op: "voxels", params: { blocks: d.blocks } }] };
    document.getElementById("crName").value = "Captured Build";
    toast("Captured " + d.captured + " blocks from " + d.scanned + " cells scanned");
    crRender();
  }).catch(() => toast("Capture failed", false));
});

document.getElementById("crSave").addEventListener("click", () => {
  const name = document.getElementById("crName").value.trim();
  if (!name) { toast("Give the build a name first", false); return; }
  const btn = document.getElementById("crSave");
  btn.disabled = true; btn.textContent = "Publishing…";
  fetch("/api/creator/save", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      desc: "Created in the Schematic Creator.",
      category: document.getElementById("crCat").value,
      difficulty: document.getElementById("crDiff").value,
      ops: crDraft.ops.filter(o => !o.muted).map(o => ({ op: o.op, params: o.params })),
      column: "ready",
    })
  }).then(r => r.json()).then(d => {
    btn.textContent = "Publish to Backlog";
    if (!d.ok) { btn.disabled = false; toast(d.error, false); return; }
    toast("Published — “" + name + "” is on the Schematics board, ready to build");
    const t = document.querySelector(".nav-tab[data-panel='schematics']");
    t.style.background = "rgba(244,114,182,0.25)";
    setTimeout(() => t.style.background = "", 600);
    fetchSchematics();
  }).catch(() => { btn.disabled = false; btn.textContent = "Publish to Backlog"; });
});
</script>
</body>
</html>"""
