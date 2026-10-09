# UNDERSTAND — studio option surfaces on :8899 vs 3D / mesh / rig / pose / identity
Written 2026-09-02. Read-only pass. Evidence tags: MEASURED (ran/parsed), VERIFIED-AT-SOURCE (read the line), CLAIMED (FACTS pack / docstring), ASSUMED.
Paths: C = `/home/zygomatic/Zygomatic Full/agents/crews/`. H = `C/inspection.html`.

## 0. One-line verdict
Every studio's "3D" is a textured 2D plane in an OrbitControls scene (Character CS3 H:7816-7831, Creature CRST3 H:10190-10205, Movement MVST3 H:11179-11186) — VERIFIED-AT-SOURCE. The ONLY real mesh viewer is the Mesh tab (MV3, H:7548-7670, custom ZM3D binary magic 0x5A4D3344 at H:7634), and it is READ-ONLY: kanban_server.py exposes exactly two GET routes (`/mesh/api/list` :4598, `/mesh/img` :4600) and no POST — MEASURED by grep. No studio can pose, fit, morph, rig, export or emit a control plate from a registered body. The measured-working mesh→control-map bridge `mesh_control.py` has zero consumers (`grep -l mesh_control *.py` → only itself) — MEASURED.

## 1. Mesh tab (top-tab `mesh`, H:3958)
| element | state | evidence | what it does |
|---|---|---|---|
| lanes ORIGINALS / MALE BASE / FEMALE BASE / PROPS & CREATURES | live | H:7130+25..28 (`meshLaneHtml`) | lists registry.json of `data/assets/mesh_skeletons` + `data/assets/prop_meshes` |
| GNM head fits lane | live, study-only | H:7169-7220, kanban_server.py `_gnm_fits` :337-380, `/gnm/api/fits` | face RMS, mean-head control, identity gain — labelled "measurement, NOT a body change" |
| card: hash badge, anthro chip, height, cage verts, subdiv verts, sha | live | H:7099-7113 `meshCardHtml`, H:7048 `anthroState` | anthro chip states: PASS / PASS+WARN / FAIL / NOT GATED / GATES OFF / GATE ERROR, with `+N UNRUN` tail (a PASS over unrun gates is never green) |
| viewer 2D previews per view | live | H:7459-7500 `mvRender` | thumbnails per rendered view |
| viewer 3D orbit + `grid` wireframe + anthro report panel | live | H:7548-7670, H:7256-7275 | three.js r144 (H:5200-5205 GLTFLoader loaded but MV3 uses ZM3D .bin, not GLB); raycast is zoom-pivot only (H:7697-7730) |
| `adjustable.phenotype_axes` + `local_change_labels` + `bone_scale` shown on ORIGINAL cards | live, display-only | H:7495-7499 | the axes exist in params, nothing in the UI edits them |
| derive / reissue / refit / fit-from-sheet / pose / export | MISSING (CLI only) | grep kanban_server.py for POST mesh routes → none | `geom/mesh_skeletons.py reissue` is a CLI |
| registry state on disk | MEASURED | python read of registry.json | originals male+female; derived abel (mesh3d=True, anthro FAIL), cornelis (mesh3d=True, anthro FAIL); props: pufferball only |

## 2. Character Studio (`cst-`; CS_TOOLS H:8013-8632; server `character_studio.py`)
- Registry: 180 tools (MEASURED by parse), 20 sections: 16 side (Identity, Face, Eyes, Hair, Body, Wardrobe, Accessories, Grooming, Expression, Pose, Render, Model, Voice, Motion, Sheet, Checks) + 4 dock (File, Run, Edit, View). Server SECTIONS (character_studio.py:191) has 14 — **Sheet and Checks have no server section; they are client `act:` views over `derived()`** (character_studio.py:262-330) — VERIFIED-AT-SOURCE.
- Live rule: `cstLive(t) = !!(t.f || t.act)` (H:8646); a tool without `f`/`act` renders with tooltip "[placeholder — drawn, not wired]" (H:8655). 88/180 live per FACTS (CLAIMED; my parse lists each tool's state, see `cs_tools_window.js` extract in this dir).
- Preview: CS3 = `PlaneGeometry` with the portrait texture (H:7816-7831). Not a mesh. Fails soft if WebGL unavailable (H:7768-7790).
- Writes: only through the 64-field whitelist `FIELDS` → `character_bible_service.save()` (character_studio.py:38-189, 350-420). Nothing here reads or writes `data/assets/mesh_skeletons`.

### Section promises vs does (the five asked for + Body, which is where the mesh axes should surface)
| section | tool (id) | promise (label/tip) | state | evidence |
|---|---|---|---|---|
| Model | family, lorascale, ipascale, instantid, instantidw, facedetail(+str), handdetail(+str), quality, negative, sdxlckpt | which LoRA path/workflow the renderer picks | live field edits of `conditioning.*` | character_studio.py:118-160 |
| Model | loras, refs | "the weights this character actually has on disk" / "reference set checked against files" | live act; `derived()` stats files | character_studio.py:262-285 |
| Model | masterref | single anchor image | live but **read-only** (`t:'ro'`) | character_studio.py:158 |
| Model | seed | render seed | PLACEHOLDER | CS_TOOLS Model |
| Pose | posture | default carriage, in words | live area field (mirrored to style_profile) | character_studio.py:101 |
| Pose | poseref | "The ControlNet pose plate this character renders against" | live **read-only** — displays `conditioning.controlnet_pose_reference`, cannot set it | character_studio.py:159 (`'t':'ro'`) |
| Pose | poselib, gesture, headturn, stance, handpose, sitting | pose library / gesture / head yaw-pitch-tilt / stance / hand pose / seated-standing | PLACEHOLDER ×6 | CS_TOOLS Pose |
| Motion | emotion, pacing | motion baseline | live enum fields `motion_profile.*` | character_studio.py:170-176 |
| Motion | motionstudio | open Movement Studio with this character | live act | H:8465 |
| Motion | gait, idle, motionpreset | gait / idle motion / named motion | PLACEHOLDER ×3 | CS_TOOLS Motion |
| Sheet | sheet, cells, tiles, finals, training | manifest + counts off disk | live acts over `derived()` | character_studio.py:286-330 |
| Sheet | datasetdir, srcmanifest | paths | live ro fields | character_studio.py:179-180 |
| Sheet | angles ("which of the 48 angles … and which are missing"), resheet | PLACEHOLDER ×2 | CS_TOOLS Sheet |
| Checks | qc, approval, licence, stats, history, disk, diff | identity QC block, approval, licence, gen stats, scene history, disk, unsaved diff | live acts (manifest/bible reads) | character_studio.py:300-330 |
| Checks | drift ("how far a regenerated cell may move from the anchor"), handqc, anachronism | PLACEHOLDER ×3 | CS_TOOLS Checks |
| Body | build, muscle | descriptor + 1-100 | live | character_studio.py:87-92 |
| Body | proportions ("head-to-body count, limb length, torso ratio"), shoulders, waist, hands, feet, neck, bodyfat, tattoos, bodyscars | PLACEHOLDER ×9 — these ARE the anny phenotype/local axes the Mesh card displays (H:7495-7499) but nothing bridges them | CS_TOOLS Body |
| Accessories | props | "A prop the mesh library holds can drive the render through a depth plate rather than a word" | PLACEHOLDER (tip already names the intended wiring) | cs_tools_window.js:228 |
| View dock | d_fit, d_reset, d_full | camera on the plane | live | CS_TOOLS View |
| View dock | d_angles (snap front/side), d_plate ("show the depth or pose plate behind the preview"), d_compare, d_grid | PLACEHOLDER ×4 | cs_tools_window.js:605-608 |
| Run dock | d_preview (render still), d_resheet, d_restyle, d_train, d_stop | PLACEHOLDER ×5; d_refresh live | CS_TOOLS Run |

## 3. Creature Studio (`crst-`; `creature_fx.py`, 221 ops MEASURED)
Sections (MEASURED counts): Appendages 16, Camera 9, Colour 14, Condition 12, Face 12, Form 16, Gear 10, Measure 8, Output 8, Pipeline 6, Pixel 25, Pose 10, Preset 3, Render 10, Scene 11, Source 7, Stack 11, Style 9, Surface 14, View 10.
| op group | ids | state | nature | evidence |
|---|---|---|---|---|
| Pose | cp_stance, cp_action, cp_head, cp_gaze, cp_tailpose, cp_limbpose, cp_weight, cp_ground, cp_interact, cp_sym | live (needs ComfyUI) | **generative Qwen-edit prompt clauses** (`_edit`, needs='comfy') — no geometry | creature_fx.py:1277-1366 |
| Camera / view angle | cm_view (9 camera positions incl. 'directly behind', 'from above'), cm_elev, cm_dist, cm_lens, cm_roll, cm_centre, cm_margin, cm_aspect, cm_dof | live | Qwen-edit clause; multiple-angles LoRA at full strength "because creatures under-rotate: side profile came back as three-quarter on 6/16 cells" | creature_fx.py:1383-1397 (CLAIMED measurement in the tip) |
| Form (proportions/limb count/symmetry) | cf_prop, cf_limbs, cf_limblen, cf_symmetry, cf_posture … | live | Qwen-edit clauses | creature_fx.py:225-374 |
| Measure | ms_identity, ms_change, ms_judge, ms_plan (body-plan sentence agreement), ms_facts, ms_palette, ms_licence, ms_history | live acts (side bar) | image measurements; ms_plan is the body-plan lock | creature_fx.py:2205-2254 |
| Pipeline | pl_sheet (rebuild 16-cell sheet), pl_train | live but **hands you the command, does not run it** | creature_fx.py:2517-2528 |
| 3D / turntable / depth / rig / mesh | — | **MISSING** | `prop_control` appears only inside a tooltip (creature_fx.py:625); no import of prop_mesh_library / mesh_control | grep MEASURED |
| preview | CRST3 | textured plane | H:10190-10205 |

## 4. Movement Studio (`mo-`; `movement_studio.py`)
Racks (VERIFIED-AT-SOURCE :251-663): rail = motion, space, body, language, identity, pin; bar = engine, windows, finish, gates. ACTIONS_LIB 56 entries (:91-227) incl. 4 object actions (obj_rotate/bounce/float/topple). Subject inject: character / creature / object (bp_movement.py:10-20; objects = prop_mesh_library via `_api_movement_objects` kanban_server.py:222-236).
| option | state | evidence | relation to mesh/identity |
|---|---|---|---|
| IDENTITY: lora, lora_strength, lora2, binding, identity_refs (VACE ref_images seat) | live | movement_studio.py:484-518 | identity via LoRA + refs; no geometry |
| VACE PIN: char_geom "Skeleton guide" | live | :545-549 → `ZYG_CHAR_GEOM_CTRL` (:1019) → wan_vace_service.py:1606 → geom/char_vace | paints ONE STATIC skeleton+face tesselation into the control frame (FACTS) — the only UI-reachable geometry control |
| VACE PIN: graded_pin / pin_box / pin_level | live | :550-565 → `ZYG_VACE_DIFFDIFF` | differential-diffusion box pin; semantics, not geometry |
| object inject → still | live | bp_movement.py:230 uses `rec['previews'][0]` (a PNG) | the mesh's rendered depth/normal PASSES are not used |
| prop_plates (rendered rigid geometry per shot) | **missing-by-decision** | MISSING :1091-1094; kwarg exists in `generate_vace_static_clip` (wan_vace_service.py:1396, consumed :1579-1588); bp_movement.py never passes it (grep) | "nothing here knows where the prop is in the frame" |
| pose/depth/OpenPose control plates + driver clip | **missing-by-decision** | MISSING :1080-1085; per-frame path live behind `ZYG_VACE_MASK_SEQ` (wan_vace_service.py:1253, 1486-1494) | "the per-frame plumbing exists and is tested; the missing half is the UI to choose a driver clip" |
| set plate (two-embed split) | missing-by-decision | MISSING :1086-1090; kwargs at wan_vace_service.py:1393,1745 | needs a clean background plate |
| per-frame mask sequence | missing-by-decision | MISSING :1095 | picker not built |
| camera moves | missing-by-decision | MISSING :1075-1079 | locked-camera recipe hard-prefixes '固定镜头' |
| preview MVST3 | textured plane | H:11179-11186 | not a mesh |

## 5. Video Studio (`video_studio.py`)
Racks :94-561 (prompt, camera, motion, look, start-frame, model pathway, engine, timing, finish, gates); PATHWAYS wan21_480p/720p/wan22 (:80-85). Nothing 3D/mesh/pose. MISSING :1370-1388 — audio, FLF2V ("wrapper has no end_image input"), ControlNet/VACE pose-and-depth ("belongs in the Movement tab"), RealESRGAN video, timeline. State: missing-by-decision, correctly routed to Movement.

## 6. Picture Studio (`bp_picture_studio.py`, client H:9825-10080)
`_TOOLS = ('upscale','inpaint','bg_remove')` (:52); client tools upscale + inpaint (H:9897-9898) + bg_remove (H:10080 region). Upscale = Comfy ESRGAN → PIL fallback; inpaint = Qwen via flux_fill_service; bg_remove = bg_remove_service. Nothing 3D. Not related.

## 7. Architecture Studio (`ar-`; `architecture_studio.py`)
Catalogue ELEMENTS/PRIMITIVES/MATERIALS + project store only (:1-30 docstring: "Deliberately NOT here: geometry, meshes, rendering, CSG"). Client three.js geometry factory with real tools: Navigate/Draw/Modify(push-pull, follow-me)/Solids(bool union/subtract/intersect)/Measure/Paint (H AR_TOOLS). Only human element is `person` scale figure 1.75 m (:113). No GLB/character import, no Blender round-trip. Unrelated to identity; note it is the one place with a working client-side 3D editor idiom.

## 8. Cross-cutting: what exists in `geom/` that no studio reaches (MEASURED by `grep -l`)
- `anny_animate`, `char_vace`, `vace_control` → only `wan_vace_service.py`; UI reaches only the STATIC skeleton path (char_geom toggle).
- `mesh_control` (prop mesh → subject-only depth/normal/lineart/segment, `build()` :158, `ensure()` :265, CLI `_main` :278) → no consumer at all.
- `prop_control`/`prop_plates` → wan_vace_service + movement_studio (MISSING text) + creature_fx (tooltip) only.
- Registered bodies abel/cornelis: both anthro **FAIL** (registry MEASURED); split-brain phalanx gate is open (FACTS).

## 9. Null models for any wiring gate (per operator discipline)
- Plate wiring (prop or char depth): compare identity/prop-persistence score WITH plate vs (a) `prop_plates=None` and (b) a flat grey-127 plate (the historical inert control, FACTS). Success = plate arm separates from BOTH nulls; report rank-of-truth as in the klein/Qwen depth tests (rank 2/16, 3/16 vs chance 8.5).
- Per-frame pose track: RTMPose on the output vs the intended track, baseline = static-skeleton run and = no-control run.
- Body-axis edits from Character Studio: anthro gate verdict after `reissue` vs "do nothing" (same body, gate re-run) — a verdict flip that also occurs with no edit is noise, not a fix.

## 10. Wiring table (build candidates, ordered by leverage per effort)
| # | what | touches | effort | why first |
|---|---|---|---|---|
| A | Movement Studio PLATES rack: object picker → `mesh_control.ensure(asset, view)` → `prop_plates=` kwarg | movement_studio.py RACKS, bp_movement.py:316, mesh_control.py | days | kwarg + renderer + measured maps all exist; only the picker and the "where in frame" box are missing |
| B | Driver-clip / pose-track picker → `anny_animate` per-frame depth dir → `mask_path` dir with `ZYG_VACE_MASK_SEQ=1` | movement_studio.py, bp_movement.py, geom/anny_animate.py | days | plumbing tested (41 frames, 0.043% grey); no per-shot pose tracks yet → start with two-pose lerp |
| C | Character Studio d_plate/d_angles + writable pose reference: render the registered body's depth at canonical angles (`geom/mv_render`) and show/assign it | inspection.html CS_TOOLS, character_studio.py (`controlnet_pose_reference` ro→path-validated write), kanban_server.py route | days | makes "the depth map does the steering" reachable per character |
| D | Mesh tab actions: derive / reissue / refit-from-sheet as POST routes with hash receipts | kanban_server.py (new POST), geom/mesh_skeletons.py | days | tab is view-only today |
| E | Character Studio Body placeholders → anny phenotype/local axes (registry `adjustable.*`) + reissue | character_studio.py FIELDS/SECTIONS, kanban_server.py, geom/mesh_skeletons.py | week+ | needs the phalanx split-brain gate fix first or every edit reads FAIL |
| F | Creature Studio `cm_view` mesh-backed variant: depth from the registered pufferball at the chosen view as Qwen image2 | creature_fx.py (new op), mesh_control.py, prop_mesh_library.py | days | only for creatures with a registered mesh (1 today) |
