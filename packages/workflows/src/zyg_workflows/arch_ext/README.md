<!--
SPDX-FileCopyrightText: 2026 Zygomatic

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Architecture Studio extension families (2026-09-06)

One capability family = one basename `<family>` in FOUR places plus a test.
Never edit `inspection.html`, `arch_assistant.py`, `arch_blender_build.py` or
`architecture_studio.py` for a family — the seams below load your files.

| file | what it is | loaded by |
|---|---|---|
| `arch_ext/<family>.js` | geometry + label (+ opening flag) per new kind | `/arch_ext/bundle.js` (served, no cache) → `arGeom()` falls through to `AR_EXT.geom[kind]` |
| `arch_ext/<family>.json` | the library-rail leaves for the new kinds | `architecture_studio.library()` merges it into a rail section |
| `arch_assistant_ext/<family>.py` | the assistant's tools, kinds, prompt paragraph, worked examples | `arch_assistant.load_extensions()` at import |
| `arch_blender_ext/<family>.py` | Blender geometry per new kind | `arch_blender_build.ext_builders()` |
| `tests_arch_ext/test_<family>.py` | the proof (assistant + tab + Blender) | you, and the board's `verify_cmd` |

Worked example: `curved_walls` — copy its five files and rename.

## A record (what everything agrees on)
`{id, kind, name, p:{...numbers}, x, y, z, rx, ry, rz, s, mat, hidden, grp}` — metres, Y is UP,
`ry` is the rotation about the vertical axis in radians, `y` is the storey base
(storey k → `k * 2.7`). Parameters are numbers the geometry is rebuilt from —
**never store geometry**. A drawing that names a kind the client does not know
draws a 0.5 m marker cube; the tests treat that cube as failure.

## `arch_ext/<family>.js`
```js
AR_EXT.geom.wall_arc = function(p, k){          // k = {THREE, box:arBoxG(w,h,d,cx,cy,cz), prism:arPrismG(profile, len), num:arNum(v, default)}
  var N=function(key,d){ return k.num(p[key], d); };
  ...build THREE.BufferGeometry in the record's LOCAL frame: origin at the record's x/z, bottom at y=0, up = +Y...
  return [{g: geometry}, {g: another, sub: 'mat_glass'}];   // parts; `sub` overrides the record's material; `line:1` draws lines
};
AR_EXT.label.wall_arc = 'Curved wall';
AR_EXT.openings.window_round = 1;               // ONLY for opening kinds: arSyncHoles then cuts a RECTANGULAR hole w × h at sill from p.w/p.h/p.sill
```
The built-in kinds live in `arGeom()` in inspection.html (search `case 'roof_hip'`
for a hand-built BufferGeometry, `case 'slab'` for a box, `case 'roof_dome'` for a
lathe). Angles on the plan: 0° = +X, 90° = −Z (north = up in the top view); a point
at angle θ is `(r·cosθ, −r·sinθ)`.

## `arch_ext/<family>.json`
```json
{"section_key": "elements", "section_label": "Building elements",
 "groups": [{"g": "Curved walls",
             "items": [["wall_arc", "Curved wall", {"r": 5, "a0": 0, "a1": 90, "h": 2.7, "t": 0.24}, "Quarter circle by default."]]}]}
```
`section_key` is an existing rail section (`elements`, `primitives`) or a new one
(`site`, `interior`, `structure`, `landmarks`…). Items are `[kind, name, params, note]`.
The Properties panel edits every numeric key of `p` for free.

## `arch_assistant_ext/<family>.py`
```python
from arch_assistant import Drawing, parse_cell, cell_centre, block_bounds, cell_of, MATERIALS, _num, storey_of
KINDS = {'wall_arc': {'r': 5, 'a0': 0, 'a1': 90, 'h': 2.7, 't': 0.24, 'seg': 24}}   # add_object accepts these
OPENINGS = []                                                                         # opening kinds among KINDS
PROMPT = 'Curved walls: draw_curved_wall(centre, radius, start_deg, end_deg, storeys) ...'  # ONE paragraph, what + when
def t_draw_curved_wall(d: Drawing, a: dict, centre, radius=5, start_deg=0, end_deg=90, storeys=1, storey_from=0, material='', wall_h=None, wall_t=None, name=''):
    ...  d.new(kind, p, x, z, y, ry, mat, name=..., grp=...)  ... return 'what was drawn, with ids'
TOOLS = [({'name': 'draw_curved_wall', 'description': '...', 'input_schema': {...}}, t_draw_curved_wall)]
EXAMPLES = [{'ask': 'a curved wall around C4, radius 6, a quarter circle', 'calls': [{'tool': 'draw_curved_wall', 'args': {'centre': 'C4', 'radius': 6}}]}]
```
Tool functions get `(d, a, **args)` — unknown keys raise TypeError, which the caller
turns into "bad arguments". Return a SHORT string the model reads. Refuse with
`'refused: …'`. Extra result channels on `d`: `d.ui.append({'cmd':'view','args':{'view':'top'}})`
(cmds: view, focus{ids}, select{ids}, cells{on}, grid{on}, storey{storey}, sun{hour},
section{storey|null}, hide{ids,hidden}, toast{text}, save{name}); `d.images.append({'title','data_url'})`;
`d.selected = [ids]` (ids to highlight after injection). `d.select(which)` resolves "new" | "all" | a kind | a group | [ids].
Cap object counts (`arch_assistant.MAX_OBJECTS`), keep names/groups readable in the outliner.

## `arch_blender_ext/<family>.py`
```python
def build_wall_arc(bm, p, kit):    # kit = {add_box, add_box_c, add_cylinder, add_sphere, add_prism, add_dome, add_hip, num, bmesh, math}
    ...fill bm with LOCAL geometry: X along, Y = studio −Z (depth), Z up, bottom at z=0...
    return ('', [])                # (name prefix: '' real, '~' approximate; extra material ids)
BUILDERS = {'wall_arc': build_wall_arc}
```
See `arch_blender_build.py` `build_kind()` for the helpers' signatures and the frame.

## `tests_arch_ext/test_<family>.py`
```python
from arch_ext_harness import check, finish, assistant, kinds_of, browser_kinds, blender_kinds, rail_has, tool_names
txt, d = assistant('draw_curved_wall', {'centre': 'C4', 'radius': 6, 'storeys': 2})
check('tool drew 2 arcs', kinds_of(d).get('wall_arc') == 2, txt)
check('rail lists the kinds', rail_has(['wall_arc', 'wall_ring']) == [])
b = browser_kinds([{'kind': 'wall_arc', 'p': {'r': 5, 'a0': 0, 'a1': 90, 'h': 2.7, 't': 0.24}}])
check('wall_arc builds, sized r+t/2', b[0]['ok'] and abs(b[0]['size'][0] - 5.12) < 0.05 and abs(b[0]['size'][1] - 2.7) < 1e-3, b[0])
bl = blender_kinds([{'kind': 'wall_arc', 'p': {...}}])
check('blender builds wall_arc', bl.get('wall_arc', {}).get('polys', 0) > 4, bl)
finish()
```
Run with `"$ZYG_LEGACY_VENV_PY" tests_arch_ext/test_<family>.py` (the legacy tree's venv).
A green test proves three engines agree about your kinds; a size check proves the
parameters mean what the prompt says they mean.

## v3 ground (2026-09-07)

A drawing has ONE ground: a record of kind `ground`. Every ground feature is a
**sculpt**, and a sculpt is a *parameter of the ground*, not a solid standing on
it — which is why a valley can be a valley instead of a plinth. Four seams make
that possible; a family that draws land uses them, and nothing else has to
change.

**`kit.records` — a geometry function may read the other records.**
`arExtKit()` (tab) and `ext_kit()` (Blender) both carry `records`: the drawing's
whole object list, in document order, **read-only**. A `ground` builder walks it
for the sculpts that shape it. In Python the same fact is
`arch_assistant.current_drawing()`, published for the length of a `HEIGHTS` call
by `ground_height()`, plus `arch_assistant.sculpts_of(d)` for the sculpt records
themselves (hidden ones excluded — hiding a sculpt takes its feature out of the
land). Outside a HEIGHTS call `current_drawing()` is `None`; cope with that.
Both kits also carry the studio's material colours: `kit.matRGB(id)` in the tab,
`kit['mat_rgb'](id)` in Blender, each `[r, g, b]` in 0..1 from the same hexes the
presets use.

**`vcolors` — one mesh, many surfaces.** A geometry part may carry a colour per
vertex, so the ground is grass on the flat, rock on the steep face, sand at the
water and snow on top without being cut into four objects:

```js
return [{g: geometry, vcolors: new Float32Array(rgbPerVertex)}];   // tab
```
```python
return ('', [], [(r, g, b), ...])      # Blender: one tuple per vertex, in bm.verts order
```

The tab sets the geometry's `color` attribute and uses a cached vertex-coloured
twin of the record's material (`arMatVC`): white base, no albedo map, the
preset's roughness. Blender creates a `Col` `FLOAT_COLOR` POINT attribute and a
material whose Principled Base Color is driven by an Attribute node reading it.
Because the colours are indexed **by vertex**, `remove_doubles` is skipped for a
vertex-coloured build — such a builder owns its own topology.

**Sculpts are VOID kinds.** A `sculpt_*` kind draws only an outline in the tab
(like `opening`) and Blender skips it: the ground mesh is the only geometry.
Their contribution functions (`sculpt_peak`, `sculpt_ridge`, `sculpt_mesa`,
`sculpt_cut`, `sculpt_channel`, `sculpt_basin`, `sculpt_flat`, `sculpt_step`,
`sculpt_dunes`, `sculpt_shelf`) all work in the sculpt's own local frame, return
0 outside the footprint and feather smoothly to 0 at the rim, so a feature blends
into the land instead of standing on it. As always, the JS, the Blender Python
and the assistant Python are **three copies of one arithmetic** — change one and
you have three landscapes.

**The studio keeps the ground current.** `arGroundRefresh(rec)` rebuilds every
`ground` record whenever a `sculpt_*` record is added, moved, edited or deleted
(`arNewObj`, `arApplyTransform`, `arSetParam`, the push-pull drag, `arRemove`),
and unconditionally after a whole-document injection. Rebuilds are coalesced into
one animation frame, so a forty-sculpt injection cuts the ground once.

**Testing a ground kind.** A `ground` record cannot be built alone, so a harness
case may carry `others`: full record dicts injected before the case record and
removed after (`browser_kinds`) or put into the doc beside it, positioned
relative to it (`blender_kinds`). `browser_kinds` reports `vcolors: true` when the
built mesh has a colour attribute; `blender_kinds` reports `vcol: true` per
object. The worked example is `v3probe` (`arch_ext/v3probe.js`,
`arch_blender_ext/v3probe.py`, `arch_assistant_ext/v3probe.py`) proved by
`tests_arch_ext/test_v3_seam.py` — a quad whose height is the number of `box`
records in the drawing and whose four corners are red, green, blue and white.

## The ICON seam (2026-09-07) — wiring a dock/side icon from your own files

The 231 icons in `AR_TOOLS` (inspection.html) are the studio's option surface;
138 were honest placeholders (`stub:1`, dashed, amber pip, "[placeholder]" tip,
a toast). An icon stops being a placeholder the moment an `arch_ext/<family>.js`
registers its id. **You never edit inspection.html.** The same family name goes
in the other places you need:

| file | what it is | loaded by |
|---|---|---|
| `arch_ext/<family>.js` | `AR_EXT.tools[id]` / `AR_EXT.modes[id]` + hooks | `/arch_ext/bundle.js`, no cache — save, reload the tab |
| `arch_assistant_ext/<family>.py` | `BUTTONS=[ids]` the model may press, `TOOLS` that do the same job server-side (text result), `PROMPT`, `EXAMPLES` | `arch_assistant.load_extensions()` at import — **needs a kanban-server restart to reach the live GUI** (check `/inspect/api/architecture/assistant/active` is 0 first) |
| `arch_server_ext/<family>.py` | `ROUTES={op: fn(payload, method)}` for work the browser cannot do (files, Blender, disk) | `architecture_studio.ext_dispatch()` — **reloaded on file change, no restart** |
| `tests_arch_ext/test_<family>.py` | the proof | you, and the board's `verify_cmd` |

Worked example: **`icon_probe`** wires `s_last` (Select ▸ Previous) —
`arch_ext/icon_probe.js`, `arch_assistant_ext/icon_probe.py`,
`arch_server_ext/icon_probe.py`, `tests_arch_ext/test_icon_probe.py` (14 checks).

### `AR_EXT` registrations (all optional, any number per file)
```js
AR_EXT.tools.e_align = {                 // an ACTION or a SWITCH behind an existing icon id
  act: function(opt){ ... },             // opt = the assistant's args object, or undefined when a person clicked (then prompt())
  on:  function(){ return AR.showX; },   // SWITCHES only: the latched state (the icon lights while true)
  tog: 1,                                // mark as a switch (no 420 ms flash; re-renders the bars after act)
  assist: 1,                             // the assistant may press it via press_button(id[, args])
  tip: 'replaces the tooltip'            // optional
};
AR_EXT.modes.arc = {                     // a POINTER MODE: latches like wall/room; AR.tool === 'arc' while armed
  click: function(P, e, g){ ... },       // P = snapped {x,z,y,snap} on the drawing plane (null off-plane), e = event, g = raw hit
  move:  function(P, e, g){ ... },       // every pointer move while armed (draft or not): draw your own rubber band
  hint:  function(draft){ return 'html'; },  // the hint line; draft = AR.draft (null when idle)
  cancel: function(){ ... },             // Esc / Enter / tool change — drop your draft state
  key:   function(e){ return true; }     // return true to swallow a key (Enter to close a polygon, digits to type a length)
};
AR_EXT.snaps.push(function(P, g, e){ return {x, z, y, snap:'endpoint'} || null; });  // first non-null answer wins; runs AFTER grid snap
AR_EXT.matHooks.push(function(m, def, id){ ... });   // every material made or refreshed (arMat, arMatVC, arMatRefresh); m.userData.arId / arVC
AR_EXT.ticks.push(function(){ ... });                // every frame, before the render
AR_EXT.render = function(){ composer.render(); };    // replaces renderer.render in arTick/arShot/arSnapshotPng; set null to give it back
AR_EXT.resizes.push(function(w, h){ ... });          // after arSize resized the canvas
AR_EXT.keys['shift+d'] = function(e){ ... };         // 'x' or 'shift+x' for keys the studio does not use (see the keydown map)
AR_EXT.sections.push({sec:'Layers', bar:'dock', items:[{id, lb, k, tip, svg, tog}]});  // a whole new dock group
AR_EXT.ready.push(function(){ ... });                // once, when AR.renderer/scene/controls exist (arEnter) — wrap globals here
```
The bundle runs BEFORE the studio script, so at top level you may only
register; anything that touches `AR.renderer`, `AR.scene`, `arSelect` etc.
goes inside `AR_EXT.ready.push(function(){...})`. Function declarations of the
page are writable globals: `var base = arSelect; arSelect = function(ids, add){ ...; base(ids, add); }` wraps one.

**Placeholder → real is automatic:** `arExtApplyTools()` (run by every
`arToolsRender`) deletes `stub` from any `AR_TOOLS` item whose id is in
`AR_EXT.tools` or `AR_EXT.modes`. The dock probe (`test_arch_dock3.py`) and
`arch_ext_harness.icon_state([...ids])` both read that live state.

### The tab's API you will call (all globals in inspection.html)
- **Document:** `AR.objs` (records, document order), `AR.sel` (ids), `arSelRecs()`, `arFind(id)`, `AR.doc = {id, name, ext:{}}` — **`AR.doc.ext` is yours for document-level state** (layers, units, north, rate card…): it is saved, loaded, sent to and returned from the assistant. Per record, **`rec.meta = {}`** is yours (tags, layer, component, zone…): saved, snapshotted, duplicated, and round-tripped through the assistant's `Drawing` (`o['meta']`, `d.ext`). Keep both JSON-plain.
- **Records:** `arNewObj(kind, p, x, z, y)` → rec (pushes into AR.objs, builds it); set `rec.ry/rx/rz/s/mat/name/meta` then `arApplyTransform(rec)` / `arApplyMat(rec)`; `arRebuild(rec)` after changing `rec.p`; `arRemove(rec)`; `arSyncHoles()` after anything that moves walls or openings; `arGeom(kind, p)` → parts; `arKindLabel(kind)`; `arIsOpening(kind)`.
- **Undo:** call **`arPush()` once BEFORE** a change that edits the document (never after; never for a read-only report); `arUndo()/arRedo()`; `arSnapshot()` = the JSON the undo ring holds.
- **Selection:** `arSelect(ids, add)`, `arSelSync()`, `arSelCentre()`, `arSelAll()`, `arSelInvert()`, `arPick(e)` → `{rec, point}` under the pointer, `arGroundAt(e)` → THREE.Vector3 on the drawing plane at `AR.level`.
- **Camera/view:** `AR.cam`, `AR.camP` (perspective), `AR.camO` (ortho), `AR.controls` (OrbitControls, `.target`), `arView('top'|'front'|'right'|'iso'|'back'|'left'|'bottom')`, `arZoomFit(selOnly)`, `arFitIds(ids)`, `arBounds(selOnly)` → `{c, r}`, `arCamPush()/arCamState()/arCamApply(st)`, `AR.ortho` + `arOrthoToggle()`, `arSize()`.
- **Render:** `AR.renderer` (WebGLRenderer, `preserveDrawingBuffer:true`), `AR.scene`, `AR.sun` (DirectionalLight), `AR.hemi`/ambient via `arAmbCycle`, `AR.shadows`, `arShot(maxEdge, quality)` → jpeg data-url of the current frame, `arSnapshotPng()`, `arDownload(blob, name)`.
- **Materials:** `arMat(id)` (cached MeshStandardMaterial), `arMatVC(id)`, `AR.matCache` (every live material; `k.split('|')[0]` is the id), `AR.matDefs[id]` = `{n, col, rough, metal, op, maps, size_m…}`, `arMatRefresh()` re-applies wire/section and runs your matHooks, `arMatRGB(id)` → [r,g,b].
- **Levels/grid:** `AR.level` (drawing plane height) + `arSetLevel(v)`, `AR.defaults.wall_h` (storey), `AR.snap`/`AR.snapOn`/`arSnapV(v)`, `AR_CELL_M`/`arCellName(x,z)`, `AR.grid` (GridHelper), `AR.showGrid`.
- **UI:** `arToast(html, 'warn'|'bad'|'')`, `arHint(html)`, `arSheet(title, html)` + `arRows([[k,v],…])` for a report you READ (statistics/BOM use it), `arSheetClose()`, `arPanel()` (properties/outliner refresh), `arOutliner()`, `arOpts()` (the option strip), `arHud()`, `arToolsRender()`, `esc(s)`, `arFmt(v)`, `arNum(v, default)`, `arDirty(true)`.
- **Modes/tools:** `AR.tool` (armed id), `AR.draft` (the two-click draft `{tool, a:{x,z,y}, chain}`), `AR.rubber` (the rubber-band Line), `AR.cursor`, `arTool(id, opt)` (toggle / act), `arToolApply(id)` (arm without toggling), `arCancelDraft()`, `arToolDef(id)`.
- **Assistant:** `arAssistUi({cmd, args})`, `AR_ASSIST_TOOLS` (the built-in pressable set), `arInjectDoc(objects, {sync})`.
- **Storage:** `localStorage` keys start with `ar.`; `api(url)` → fetch JSON; server ops: `fetch('/inspect/api/architecture/ext/<family>/<op>', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({...})})`; a tuple result downloads (use `r.blob()` then `arDownload`).
- **Three.js is r147** (`vendor/three/three.min.js` declares REVISION "147"; `OrbitControls.js`, `GLTFLoader.js`); anything else from three's examples (EffectComposer, exporters, RGBELoader…) must be vendored into `vendor/three/` as the **examples/js** UMD build, which last shipped at 0.144.0 and works with r147 (UMD, `THREE.*`) build: `https://cdn.jsdelivr.net/npm/three@0.144.0/examples/js/<path>` — and loaded with a `<script>` tag you cannot add, so load it from your family JS via `document.createElement('script')` inside `AR_EXT.ready` (or fetch+eval), then continue in its `onload`.

### `arch_assistant_ext/<family>.py` additions for icons
```python
BUTTONS = ['e_align', 'e_dist']        # ids the model may press: press_button(id, args={...}); the JS registration must say assist:1
PROMPT = 'Align/distribute: press_button("e_align", {"mode":"left"}) ...'   # say the args the icon takes
```
The model cannot click the canvas, so give it a **server-side twin** of every
analysis or report as an ordinary `TOOLS` entry returning text (it reads the
numbers, you keep one arithmetic). Modes (arc, polygon…) have no assistant twin
beyond the drawing tools that already exist.

### Proving an icon
```python
from arch_ext_harness import check, finish, browser_eval, icon_state, server_ext, assistant
st = icon_state(['e_align', 'e_dist'])                     # {'exists','stub','dashed','tip_placeholder','on','section','bar'}
check('icons are real', all(not v['stub'] and not v['dashed'] for v in st.values()), st)
r = browser_eval("() => { const a=arNewObj('slab',{w:2,d:2,t:.2},0,0,0), b=arNewObj('slab',{w:2,d:2,t:.2},5,0,1); "
                 "arSelect([a.id,b.id]); arTool('e_align', {mode:'left'}); return AR.objs.map(o=>[o.id,o.x,o.y,o.z]); }",
                 doc={'objects': []})                       # optional doc injected first, quietly
check('align moved b onto a', r['value'][1][1] == 0 and not r['errors'], r)
out = server_ext('drawings', 'pdf', {'doc': {...}})         # dict for JSON, {'bytes','mime','filename'} for a download
txt, d = assistant('clash_check', {})                      # the server-side twin, as the model sees it
```
`browser_eval(js, doc=None)` runs the SOURCE of a zero-arg function in the live
tab (headless Chrome, SwiftShader, shadows off, prompt() answers its default,
confirm() true) and returns `{'value', 'errors', 'console'}`. Assert on the
DOCUMENT and on numbers, not on pixels — a screenshot proves nothing under
software GL; `arShot(640)` is there when you must look.
Run: `"$ZYG_LEGACY_VENV_PY" tests_arch_ext/test_<family>.py` → ends `ALL GREEN`.

## Reference models (2026-09-23) — building a real thing from its pictures

A *reference model* is a named folder of pictures of one real object — a ship,
a bridge, a lamp post — plus the few numbers that turn pictures into geometry.
The operator fills it from the icon rail beside the assistant chat panel; the
assistant looks at the pictures and builds a Blender asset from them.

**Files.** `arch_reference.py` (the store, stdlib + Pillow, imports nothing from
`arch_assistant`), `arch_server_ext/reference_model.py` (routes, hot-reloaded),
`arch_ext/reference_model.js` (the rail + the sheet), `arch_assistant_ext/reference_model.py`
(four tools), `arch_reference_build.py` (runs INSIDE Blender), probe
`tests_arch_ext/test_reference_model.py`. Store on disk:
`data/architecture/reference/<id>/{model.json, images/, asset/}`.

**Why it is not just an image folder.** One photograph cannot determine a size:
every pixel is a ray, so depth and scale trade off exactly, and nothing in the
file says which. What breaks the tie is knowledge from outside the picture — a
measured length, an orthographic plan, bilateral symmetry. So a picture here is
never just a picture; it carries a ROLE, and the model carries at least one
measured dimension. A reference with neither is reported everywhere as "right
SHAPE, unverified size". Do not let a later edit round that up into a claim.

### The layout convention

Stated once, in `arch_reference.LAYOUT`, and quoted verbatim by the tab, the
system prompt and the Blender harness:

> The subject lies with its LENGTH along +X (front/bow towards +X), its WIDTH
> along Y and its HEIGHT along +Z, centred on the origin. Blender is Z-up,
> +X east, +Y north — the same frame `arch_blender_build.py` maps the studio
> into. So a side view shows length x height, a front view shows width x
> height, and a top view shows length x width.

The first role table was named by compass (`plan_front`, `plan_right`, …) and
was **geometrically self-contradictory**: a right elevation and a top plan of
the same ship could not both be laid out, because they disagreed about which
way the ship pointed. Roles are now named by what you SEE — `view_side`,
`view_side_other`, `view_front`, `view_back`, `view_top`, `view_bottom`,
`section`, plus the non-views `photo` / `detail` / `texture`. Each view's Euler
was derived, not guessed: take forward (from the eye) and up, then
`right = cross(forward, up)`; the image's u must land on right and its v on up.

### The inspection set — the ten pictures a finished build is judged on

The operator's rule, 2026-09-23: *"when the ai assistant is finished with a
drawing, have it take 10 screenshots from different angles and from within the
ship."* `build_reference_asset` does it on every build (`inspect=true` by
default, `--inspect [N|names]` on `arch_reference_build.py`), keeps every frame
beside the asset as `asset/inspect-N-<view>.png`, records them in the model's
`asset.inspect`, and hands the model the pictures plus six questions it must
answer before it calls the asset finished.

The ten, in order: **bow_quarter, beam, bow, stern, aerial** (five standpoints
outside), **section_long, section_mid** (two cut planes), **inside_fwd,
inside_aft, inside_below** (three from inside). `stern_quarter`, `plan` and
`underside` follow if more are asked for.

**Why ten and not one.** The build that produced this rule passed a single iso
view while its castle decks floated two metres clear of the ship's sides, the
hull never touched its own keel, the entire strake between the gunport sills
and their heads was missing, and below the weather deck there was one nine-metre
empty volume with a lid on it. Every one of those is invisible from outside and
obvious from a cut plane or from standing on the deck. A view that cannot fail
is not a check.

**What the cameras do that a fixed camera cannot.**

- **They are placed from the asset, not from a guess.** Exterior standpoints fit
  to a SAMPLE OF THE REAL VERTICES (`_cloud`), not to the bounding box: a ship's
  box corner — abreast the stern, out at the yard-arms, up at the truck — has no
  geometry near it, and framing the box leaves the subject at 60 % of the frame.
  Fitting the box cost this ship a factor of two in every end-on view.
- **The inside ones RAY CAST for a floor.** `_floors` walks down the centreline
  and accepts a surface only when its normal points up, there is headroom over
  it, and four probes at a radius scaled to the asset land within 45 cm of the
  same height (`_floor_like`). Without the four probes the first interior camera
  parked itself on a yard-arm 22 m above the deck, which renders as a perfectly
  plausible picture of nothing.
- **Where to stand is chosen by what can be SEEN.** Every candidate standpoint
  is scored by its clear run along the look direction and the longest wins;
  standing at a fixed fraction of the length put the camera 3.5 m from a
  bulkhead. The weather-deck cameras are held to surfaces near the median top
  floor, or the scoring sends all three into the hold, which is the clearest
  tunnel in any ship.
- **They report their measurement.** Each picture comes back with the surface
  height its camera stands on, the headroom over it, the clear distance ahead
  and the standoff — numbers, beside the picture, so "the deck under the camera
  is at 9.30 m with 3.1 m of headroom" can be checked and "it looks about right"
  cannot be offered.
- **A 1.75 m red figure stands in every interior view**, off the centreline so a
  mast cannot hide it. Without one, a bulwark is chest-high or shoulder-high
  depending on what you already believed.
- **Tall subjects get a PORTRAIT frame** (`bow`, `stern`, `section_mid`): a ship
  end-on fits a 16:9 frame by its height and leaves two thirds of the picture
  empty.
- **A view with no picture still reports its finding.** "there is only ONE level
  on the centreline — no deck below the top one, so the hull has no inside to
  photograph" is worth more than a missing file.

The cut planes are ortho cameras standing ON the plane with a 1 cm near clip, so
everything on the camera's side is simply not there; they frame on the asset's
biggest single mesh (`_body_bounds`) rather than the whole asset, or a 9.5 m
hull inside a 19 m spread of yards is framed at half size.

### THE PORTFOLIO — the forty-odd, and why ten was not enough (2026-09-23)

The operator, hours after the ten-shot rule: *"the ship is allot better, but we
are not there yet. we are missing doors, windows for the cabinets etc, we are
also missing allot of thiings inside the ship … i said 10 before but after every
drawing, make sure ai assistant delivers portfolio folder with 40+ images from
projects"*, and with it *"make sure drawing curves and material quality is done
perfectly"*.

Ten pictures caught a deck floating over the sheer. They did not catch what the
pinas actually was at that point: **not one opening through any deck** — no
hatch, no companion, no scuttle, four solid lids — gunports as bare rectangular
holes with no sill, frame, lid or ironwork, a transom with **no windows at all**
on a ship whose great cabin is where the story happens, no way aboard, and three
decks of empty volume. Every one of those is invisible in the ten: the plan cut
that shows a deck has no hole in it, and the interior camera on the orlop that
shows it is bare, were not among them.

**The plan (`arch_reference_build._portfolio_shots`), generated from the asset,
about 52 frames:**

| family | frames | what only it can show |
| --- | --- | --- |
| `orbit_000`…`orbit_330` | 12 | every quarter — one lucky angle cannot flatter twelve |
| `high_045`…`high_315` | 4 | the decks and the layout from above |
| `ortho_side/‑other/bow/stern/plan/underside` | 6 | the views a CURVE is measured in |
| `section_long`, `section_long_quarter` | 2 | the centreline, and the quarter line the centreline misses |
| `section_at_12`…`section_at_90` | 6 | the body at six stations, deck heights, headroom |
| `deckplan_<n>_<z>` | ≤4 | a cut 1.55 m over every level: what stands on it, **and every opening through it** |
| `inside_<n>_fwd/aft` | ≤8 | two standpoints on **every** level, with the 1.75 m figure |
| `rake_side`, `rake_bottom` | 2 | fairness: the highlight runs the length of the surface, so a flat spot or a station out of line breaks it |
| `detail_bow/stern/midship_side/entry/stern_windows/top/deck_fwd/deck_aft` | 8 | the joints and fittings, where "finished" is decided |

Rules that were paid for, in order:

- **A detail lens is framed by WHAT IT CONTAINS** (`field_m`), never by how near
  it stands. The first portfolio put an 85 mm lens at a fraction of the length
  and came back with four frames of one plank and one of a bare pole against the
  sky. It is 50 mm now, and each detail says how many metres of ship it holds.
- **It aims by RAY CAST**, and ignores a hit closer than a third of the planned
  distance — otherwise a shroud 2 m out becomes what the picture is of. A lens
  that hits nothing says so in its own caption.
- **A cambered deck answers at two heights** and came back as two levels, which
  cost two identical interior views out of eight. `_levels` merges anything
  within `MERGE_M` and throws away surfaces shorter than 12 % of the length —
  the top of a capstan is a surface, not a level.
- **A portfolio frame is a PHOTOGRAPH, not a document** (`_photo_look`). `_setup`
  pins the view transform to Standard because a *plan* under Filmic renders its
  white paper mid-grey — but the same setting under a dark sky renders a tarred
  hull black, and a material you cannot see is a material you cannot judge. The
  portfolio gets AgX, +0.6 exposure and a sky bright enough to fill a hold; the
  check overlays keep Standard.

**The surface audit (`_audit`) is the other half of the answer**, because "make
sure curves and material quality is done perfectly" cannot be settled by
looking: a facet is a facet at 1200 px and a fair curve at 600. Per mesh:
faces, smooth %, the sharpest bend between two faces, the share of edges bending
over 20°, open edges, materials. It turns those into findings: meshes with **no
material**, materials still on Blender's **untouched default** (grey 0.8,
roughness 0.5, no texture), big **flat-shaded** meshes that never turn more than
45° (a curved surface drawn as facets), **smooth** meshes with over 12 % of
their edges bending between 20° and 60° (sections that are not fair, or too
few), and meshes full of open edges.

The 20–60° band is not a detail. The first version counted every edge over 20°,
and a single mesh holding twenty-seven rectangular deck beams — whose edges are
90° *by design* — came back flagged as an unfair surface, which would have sent
the assistant to "fix" geometry that was right. Unfairness lives in the middle
band: a fair loft has almost nothing there, while a corner is a corner.

There is a second half to the same trap. A BEVELLED corner is two edges at
about 45°, which lands in that middle band as well — so properly bevelled
hard-surface geometry would be reported unfair for doing the right thing. The
check therefore only applies to meshes that are surfaces rather than boxes:
`corner_pct < 5`. The pinas's hull has 3 % of its edges over 60°; its deck
beams have 14 %. That is the discriminator, and it is why the hull's real
unfairness (21 % before it was refaired, 4 % after) is still caught while five
bevelled wale strakes are not. On the pinas it reported, correctly and before a
single picture was looked at: seven materials, none textured, every surface a
flat colour; two faceted tops; and the hull unfair at 21 %.

**The folder is the deliverable.** `arch_reference.write_portfolio` writes
`data/architecture/portfolio/<name>-<id>/`: every frame numbered in plan order,
contact sheets of twelve, `portfolio.json`, and `index.html` — the audit
findings in red at the top, then every picture with the measurement its camera
made under it. The folder is swept of its own last build first; a folder that
mixes two builds says nothing about either. It lives in the STORE, not in the
tool module, so a probe or a standalone script can write one without importing
`arch_assistant` (which would close every live conversation as "killed").

**Where it is wired:**

- `build_reference_asset(portfolio=true)` — **on by default**, on every build.
- `portfolio_reference_asset(model)` — re-photograph an asset already built,
  through `arch_reference_build.py --from-blend`, which opens the saved .blend,
  writes no .blend, exports no GLB and runs no script. A report on a thing must
  not be able to change the thing.
- `build_reference_asset(extend=true)` — run a script **on top of** the asset
  already built (`--edit-blend`). Adding a door must not mean re-emitting the
  ship: detail is lost between rounds that way. The base script stays the one
  that built it from an empty scene; every extend is kept beside it in
  `asset.edits`, and `view_build_script(find=…)` hands the model back what it
  actually wrote, so a second round is an extension and not a rewrite from
  memory.
- `portfolio()` in `blender_power` — the same plan over a **drawing's** .blend
  (a storey is a level), written to the same kind of folder, and **`done()` is
  refused until the current drawing has one**, beside the present() gate. The
  camera plan is not written twice: the drawing's .blend is handed to the same
  builder in `--from-blend` mode. `present()` takes one Blender launch per
  frame; fifty that way would be fifty launches, and this is one.

### Seeing the set, and why a rebuilt asset used to stay invisible

The renders are in the REFERENCE MODEL sheet (the icon rail beside the
assistant chat panel): preview, the two check overlays, the ten-up contact
sheet, then the ten thumbs two-up — each one linking to the full-size picture
and carrying its camera's measurement as the tooltip. Served by `op_preview`
(`arch_server_ext/reference_model.py`) which takes a validated model id plus an
INDEX — `k=` a check, `n=` an inspection view, `s=1` the sheet — and reads the
path out of the record. Never a file name off the wire: that would be the first
hole in the wall the picture routes already stand behind. A negative index is
refused, because Python would read `k=-1` as the last check.

**The trap, paid for on 2026-09-23.** The pinas was rebuilt — same pack, same
item, 341 KB -> 1.1 MB, 4,980 -> 23,576 triangles — and the operator's studio
went on drawing the old ship. Three caches, all of them real:

1. `/inspect/arch-asset/` serves `public, max-age=86400` with **no ETag and no
   Last-Modified**, and the handler is `SimpleHTTPRequestHandler`, not Flask, so
   there is no conditional-GET path at all. The browser held the old body as
   fresh for a day and never asked again. A page reload does not help — the GLB
   is fetched by JS, straight from the HTTP cache.
2. `AR.assetCache` in the tab was keyed `pack|item`, which does not move when
   the bytes do.
3. `architecture_assets._signature()` keyed the catalogue cache on pack
   DIRECTORY mtimes, and overwriting a file in place does not touch its
   directory — so the server's own catalogue could stay stale too.

Fixed at the source of truth: `_scan_pack` carries each file's mtime, `_build`
publishes it as **`uv`** (`<pack>/<rel>?v=<mtime>`) beside the untouched `u`
(build scripts join `u` onto PACKS_ROOT and must not see a query), the tab loads
`uv` **and keys its cache on the resolved URL**, and `_signature()` walks mesh
mtimes for the vendors this machine rewrites in place (`VER_VENDORS`). With the
version in the URL, `max-age=86400` becomes correct rather than dangerous — the
URL is now content-addressed. Probe: `the catalogue hands the tab a VERSIONED
url` / `...and it CHANGES when the file is overwritten in place`.

**One more, same day:** `R.delete()` did not clear `current.json`, so a probe
model set as current and then deleted at teardown left the rail pointing at a
model that was not there. `current()` validates, so it degraded quietly to *no
model selected* — beside a live one. delete() lets go now, and the probe asserts
it at its own teardown.

### The three per-picture fields, and why each exists

- **`span_m`** — how many metres the picture's FULL WIDTH covers. A plate is
  almost never cropped to the subject's ends, so the subject's length is *not*
  the image width. Without this every plan lays out too big by its margin.
- **`flip`** — the plate reads the other way round (bow on the wrong side).
  The file is never altered; only the layout is mirrored. Its lettering then
  reads backwards in a check render, which is the right trade: the geometry is
  what is being checked.
- **`datum` (u, v from the picture's bottom-left)** — the point IN THE PICTURE
  that sits at the model's origin. Default `(0.5, 0.5)`. **This one is not
  optional in practice.** Without it `ref_plane` centres the image, so geometry
  lines up in plan and FLOATS in section — which reads exactly like a modelling
  error. Measured on Witsen plate XIX, the keel sits at v = 0.062, not 0.5.

### The build

`build_reference_asset(script=…)` runs the model's bpy in a `--factory-startup`
EMPTY scene — never the drawing's `.blend`, which is what `blender_run` is for.
An asset has its own origin, its own real size, and must survive being placed a
hundred times. The script gets `REF`, `ref_images(role)`, `ref_path()`,
`ref_plane(role, width_m=None, at=0.0, datum=None)` (a NEGATIVE `at` pushes the
plate behind the geometry), `ref_empty()`, `ref_clear()`, `mirror(obj, axis)`,
`asset_objects()`, `asset_meshes()` and `log()`. Its `print()` is captured with
`redirect_stdout` and handed back — the tool description promises it. Reference
objects are tagged `ob['zyg_ref'] = 1` and are never exported, saved or counted.

### The CHECK overlay is the product

Every plan the script laid out is re-rendered in the plan's own view with the
geometry over it in draughtsman's blue. That picture, not the model's
intention, is the evidence the shape is right. Two things about it that a later
edit will want to "simplify" and must not:

- **Two passes, one camera, mixed with numpy** (`_mix`). The obvious one-pass
  version — Workbench `show_xray` — fades BOTH, and a plan at 45 % is not a
  plan you can measure against.
- **`view_settings.view_transform = 'Standard'`.** A plan is a document, not a
  photograph: under Filmic/AgX its white paper renders mid-grey and its lines
  wash out, which is exactly the contrast you are trying to read.

The overlays are copied into the reference model's `asset/` dir, because the
work directory they are written into is swept at the end of the call and the
operator needs to see the same error the model saw.

### Publishing

A built asset is copied into `data/assets/mesh_packs/zyg_reference/<model slug>/`
with `PROVENANCE.json` (`"license": "OWN-WORK"`, a class added to
`architecture_assets.LICENCE_OK` — an unrecognised licence is refused outright)
and `DIMENSIONS.json` in metres and **glTF axes**, so Blender `(x, y, z)`
becomes `[x, z, y]`. The GLB is named after the **asset**, not the reference
model: the catalogue's item id is the glb's stem and `place_reference_asset`
quotes the asset name, and when those disagreed every placement resolved to
nothing and the studio drew a 12-triangle placeholder crate — a whole ship that
looked like a fault in the loader. `place_reference_asset` now refuses an id
that `architecture_assets.resolve()` cannot find, rather than placing a crate.
After that, `search_assets` / `place_asset` find it like any other pack model,
with no new tab code.

### The rail

`arch_ext/reference_model.js` appends a column to `#ar-stage` and follows the
chat panel through ONE wrapper on `arAssistRender` — every open / close /
toggle path already goes through it. `.ar-stage.ar-chat.ar-refrail-on` pushes
`.ar-opts` / `.ar-hud` clear of it. Adding a second icon is one entry in
`RAIL_TOOLS`. Traps paid for: `preview_url` already carries `?m=`, so a
cache-buster must be `&t=`; CSS grid items size to min-content, so the three
dimension fields need `min-width: 0` or the third clips out of the 360 px
sheet; long role labels ship a `short` for the dropdown.

### The reference models on this machine

They are self-documenting: `model.json` carries a `notes` field with the source,
the licence, the measured dimensions and where they came from, and the
assistant reads it through `list_reference_models()` / `view_reference()`. Read
the store, not a copy of it. `2694b5765e77` is Witsen's 1671 pinas, the first
one built.
