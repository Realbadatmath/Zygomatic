# UNDERSTAND — bodies + heads (geom/) — 2026-09-02
Root: /home/zygomatic/Zygomatic Full/agents/crews  (all file:line below relative to it)
Tags: MEASURED (ran/inspected here) · VERIFIED-AT-SOURCE (read in code) · CLAIMED (memory/docstring only) · ASSUMED

## 1. Entry points that run today, and on which interpreter
| entry | cmd | interpreter | evidence |
|---|---|---|---|
| bodies | `python3 -m geom.mesh_skeletons {build-originals,derive,reissue,verify,list,refresh-previews,gate}` | /usr/bin/python3.12 ONLY (needs `anny`+`trimesh`; agents .venv lacks both — MEASURED import probe) | mesh_skeletons.py:3029-3157; _model() imports anny :436-440; _export_glb uses trimesh :1745 |
| head | `/usr/bin/python3.12 -m geom.gnm_head {smoke,build}`; renders self-invoke Blender EEVEE-Next | py3.12 + /usr/local/bin/blender | gnm_head.py:4-5, :70, :284, :309 |
| head fit | `/usr/bin/python3.12 -m geom.gnm_fit run` (CPU torch, 253-dim ICP) | py3.12 | gnm_fit.py:4-5, :217, :388 |
| 2D→pose | `python3 -m geom.char_mesh <id>` → `geom.anny_fit <id> --char-asset char_abel` → `geom.body_grid` → `geom.anny_animate --from --to` → vace_control | py3.12 (anny+mediapipe 0.10.35 both present there; .venv has mediapipe but no anny) | char_mesh.py:3-4; anny_fit.py:3-4,:460-494; body_grid.py:3-4; anny_animate.py:3-5,:81 |
| gates | `python -m geom.anthro check all`; `python -m geom.anthro.pack` (facts cache) | py3.12; pack ran in <60 s here (MEASURED; exit 120 = SIGPIPE from head) | anthro/pack.py:45-47 |
| originals refit | `python -m geom.fit_reference --sex --ref <glb>`; `python -m geom.fit_proportions --sex ... / --bake` | py3.12 | fit_reference.py:3-5; fit_proportions.py:5-6 |
| GUI | kanban_server.py runs under agents .venv (kanban_server_start.sh) → cannot import anny → Mesh tab is READ-ONLY | MEASURED (start script + import probe) | routes only: /mesh/api/list :4598, /mesh/img :4600, /gnm/api/fits :4573, /gnm/img :4575; no derive/reissue/gate route (grep) |

Freshness (MEASURED via pack): anthro artefacts 2026-08-08 21:21; newest source mesh_skeletons.py 2026-08-26 22:43 → pack prints "*** STALE ... Every gate status below is a MEMORY of the previous code". All five subjects (abel, anny-neutral, cornelis, female, male) verdict FAIL/exit 2.

## 2. Shape of a registered body on disk (MEASURED, data/assets/mesh_skeletons/derived/abel/)
- skeleton_abel.glb 494 KB (triangulated cage, 13,718 verts) — sha256 in registry.json derived.abel.sha256
- mesh3d.bin 33 MB — ZM3D binary, Catmull-Clark subdiv 3 limit surface for the GUI orbit viewer (mesh_skeletons.py:1707-1728; DISPLAY_SUBDIV=2, MESH3D_SUBDIV=3 :407-408; inspection.html:7632 parses it)
- view_000/045/090/180.png + head_000/045.png (subdiv-2 shaded previews, :1667)
- params.json 18 KB — keys: kind=DERIVED, char_id, base=male, base_sha256, phenotype{gender 0.0, age 0.2292, muscle 0.5, weight 0.5, height 0.8873, proportions 0.5}, local_changes = {} (0 entries), local_changes_inherited_from_base = [], anatomy_layer{toe_declash 0.005, lip_declash 0.0625}, bone_scales {}, bone_scales_resolved, measured{height 1.52 m, 13,718 verts}, cage_vert_sha256, character_spec (ancestry UNDECLARED), stylization{axis proportions 0.5}, anthro (compact summary), hand_correction{version 1, per-bone Y scales finger2-5 x3, side_solved L}, built 2026-08-05, reissued 2026-08-08T20:21
- anthro_report.json 652 KB — full gate report. Compact verdict FAIL; blocking_failed = [t5_joint_rom, t5_patellar_ligament, t5_digit_chains, t5_phalanx_ratio]; blocking_unrun (11) incl. t1_build_target_stature (status "missing" — derive was run without --target-height, mesh_skeletons.py:3057-3059 says it is a declaration the gate checks against), t2_mahalanobis, t2_vhi_bmi, t4_threshold_provenance, t5_elbow_owner...
- Registry entry keys (derived): dir, glb, sha256, previews, params, mesh3d, visuals_updated, anthro, anthro_report_superseded, anthro_report. NO aux_sha256 on derived entries (originals have it) → _mesh_list integrity check covers originals only (kanban_server.py:158-166).
- Reissue contract: rebuild from params.json through _build_mesh (hand correction from recorded scales :621-672) + _apply_anatomy (bony_relief/toe_declash/lip_declash :1393-1438); refuses if cage hash differs (:2342-2373). Aux-hash defect (found 08-26, blocked derive since 08-08) documented + fixed in reissue() docstring :2762-2776 (VERIFIED-AT-SOURCE that the fix text exists; not re-run here).

## 3. Is there ANY path 2D contact sheet → per-character body SHAPE? — NO (VERIFIED-AT-SOURCE)
- anny_fit.py:41-43 "Phenotype stays an INPUT (declared build, calibrated by geom.phenotype), never fitted". Free params are camera, global_aa, pose_aa only (:351-357 make_params; output keys :437-453 = camera/global_aa/pose_aa/phenotype-echo).
- phenotype.py:33-74 calibrate() solves ONLY height param for a declared age (+optional gender); muscle/weight/proportions/locals never touched. Declared build comes from data/assets/manifest.json assets.char_abel.mesh.phenotype_target {age 12, height 1.52, gender 0.0} (MEASURED).
- body_grid.silhouette_wrap (:140) is a 2D Laplacian conform of the projected wireframe to the person mask → writes wrap_v2d.npy, no parameters, "not a surface reconstruction" (:18-24).
- derive() shape inputs are typed CLI args (--phenotype/--local/--bone-scale, :3034-3047). abel carries 0 locals and no bone scales: his "shape" is 6 macro numbers + hand correction + two declash keys.
- fit_reference.py (3D reference GLB → phenotype+locals via trimmed chamfer, :118) and fit_proportions.py (ANSUR ratio steering, REAL: 1,281 lines, fit_sex :581, steer_decision :440, bake :1134 — used for the FIFTH issue 2026-08-07, mesh_skeletons.py:163; artefact data/assets/mesh_skeletons_fit5_20260807.json exists) fit ORIGINALS from 3D/survey data. Neither takes an image.
- The only 2D-vs-shape measurement that exists: phenotype lock refit error 5.4 → 14.7 px (FACTS, CLAIMED) = the SDXL canon disagrees with the declared 12y build.
- Null model for any future shape fit: (a) the phenotype-only fit as shipped (do-nothing control), (b) anny mean body at declared age/height. A fit that does not beat (a) on HELD-OUT cells has learned nothing.

## 4. MEASURED discrepancy: fit/anim bodies on disk are NOT the registered body
- output/char_mesh/<asset_id>/ (abel = c3345deb5bde, cornelis = 0015c8a3f2e3; three namespaces: registry 'abel', manifest 'char_abel', dataset 'c3345deb5bde' — linked only via manifest.char_abel.mesh.summary.char_id).
- abel: 48 cells, 44 anny_fit.json (fit_mode upper 38 / full 6; fit_ok 37; median err 9.61 px in this run), 37 overlay_body, 6 overlay_wrap, anim_frames + vace_ctrl (41 frames) + anim_report.json. cornelis: 47 cells, 43 fits. Newest mtime 2026-08-08 20:18/20:34.
- Only 9/44 abel and 6/43 cornelis fits carry a non-empty phenotype (the rest ran WITHOUT --char-asset → anny default body). The locked ones carry {age 0.2292, gender 1.0, height 0.9702} (abel) and {age 0.6385, gender 1.0, height 0.5606} (cornelis); anim_report.json phenotype = gender 1.0 too. Per FACTS gender 0.0 = MALE, and manifest now says 0.0 — so the VACE control frames on disk were rendered from a female-macro body at a different height param than the registered abel (gender 0.0, height 0.8873, muscle/weight/proportions 0.5). Caveat (ASSUMED): manifest may have carried 1.0 on 08-08 and been corrected later; either way the artefacts and the registry disagree today.
- Structural cause (VERIFIED-AT-SOURCE): anny_fit.py:470-476 and anny_animate.py:96-101 build the body from phenotype.calibrate(), never from registry params.json → locals, anatomy_layer, hand_correction and bone_scales of the registered body never reach fit/animate (FACTS "known gap").

## 5. Head (gnm_head.py / gnm_fit.py) — MEASURED fit numbers (data/assets/gnm_head/fits/summary.json, 2026-08-21)
| body | face rms mm | identity gain over MEAN head mm | clip_hits | coeff absmax | scale |
| male | 4.757 | 1.965 | 2 | 2.93 | 1.212 |
| female | 4.600 | 1.763 | 1 | 2.68 | 1.118 |
| abel | 4.329 | 0.945 | 1 | 2.73 | 0.981 |
| cornelis | 4.655 | 2.091 | 1 | 2.66 | 1.165 |
Control arm served by kanban_server._gnm_fits (:311-350, fits_phase1_baseline). GUI: /gnm/api/fits lane labelled "measurement only".
What a head<->body bridge would need (derived from what exists):
1. Correspondence already defined one-sided: anny head crop = skinning weight on {head,jaw,eye.L,eye.R} > 0.35 AND neck01-03 < 0.35 (gnm_fit.py:50-57, :103-110); GNM crop = skin_exterior above chin landmark 8 (:184-190). No seam ring, no neck flange handling (:29 drops GNM neck/bust flange).
2. Topology contract: gates t1_topology_identity / t1_watertight / t1_edge_manifold are blocking on the 13,718-vert cage (pack table) → swapping in 17,821 GNM verts breaks every gate and the registry hash contract. Feasible shape: transfer the FITTED-minus-MEAN GNM delta (only 0.9-2.1 mm) onto anny head verts as an anatomy_layer key (like bony_relief, :1468), keeping topology; OR a separate head LOD asset with its own registry lane.
3. Per-body similarity scale 0.98-1.21 → the seam must scale GNM per body, not once.
4. Skinning: GNM joints neck/head/left_eye/right_eye (gnm_head.py:35-36) vs anny neck01-03/head/jaw — weight transfer at the seam not built.
5. Expression: GNM 383 blendshapes vs anny none — if used for video plates the body rig gains a channel anny cannot drive.
6. 2D→head: GNM 68 barycentric landmarks exist (gnm_head.py:115-130); MediaPipe-478 → GNM-68 mapping NOT built (grep 468/478/mediapipe in gnm_*.py = 0 hits) → no path from a contact sheet to a GNM identity either.
7. Null model: mean GNM head under the same similarity (already computed as identity_gain). The bridge is only worth building if per-character gain exceeds the seam's own blending error.

## 6. Hands / gates
- hand_correction.py: per-body solved Y-scales on finger2-5 phalanges, version 1, env ZYG_HAND_PHALANX_FIX (:97-99), solve :152, effective_scales :308, applied at the _build_mesh choke point (mesh_skeletons.py:621-650) and recorded in params.json. gates.Subject.from_registry rebuilds with params=p (gates.py:1959-1965) so the corrected MESH is what gets gated.
- abel anthro_report (08-08 20:22, post-correction) still has t5_phalanx_ratio=fail and t5_digit_chains=fail (MEASURED). Memory says the gate reads the pre-correction bone chain (split-brain) — CLAIMED, consistent with the report, not re-verified in gates.py this pass (the gate's measurement function was not located within budget).
- Pack gate table (MEASURED, stale): 62 gates; abel PASS 19 / warn 20 / fail 3 / skip 11 / report 7 / missing 2 / unrun_blk 11.

## 7. scan_ingest.py / detail_filter.py (headers only)
- scan_ingest: photogrammetry → DETAIL displacement only; proportions from ANSUR by construction; its own low-pass measured leaking (54.9% of a 537 mm feature at the -6 dB cutoff, selectivity 1.77) (:1-60). detail_filter: cotan Laplace-Beltrami + Taubin/Chebyshev families as the fix, and states the real fault: proportion (0.18 S) and detail (0.05 S) overlap in wavelength so no filter separates them (:1-50). No scans on disk (data/assets/sfm has only capability_baseline.json + PROVENANCE.json; form_reference has regions.json).

## 8. Mesh tab (kanban_server.py:132-360 + inspection.html)
- _mesh_list (:132-180): reads registry.json, 20 s cache, sha-verifies ORIGINALS' glb + aux_sha256 → 'verified-immutable' / 'HASH MISMATCH'; marks anthro_report_present per record. _prop_mesh_list (:195-221) second lane (prop_mesh_library, same ZM3D viewer). _gnm_fits (:311-350). _mesh_list_scoped (:353) medusa/female scope filter.
- inspection.html: fetch '/mesh/api/list' (:6577); card = previews + anthro chip (verdict, blocking_unrun_ids, drawer loading anthro_report.json via /mesh/img) (:7046 area); ZM3D orbit viewer (:7632). No Derive/Reissue/Gate/Fit control anywhere (grep: only prose hits "Derived anchors", "Derived — Studio edits").

## 9. Tests: tests/test_gnm_head.py, test_mesh_control.py, test_prop_mesh_library.py. No test for mesh_skeletons, anny_fit, gnm_fit, hand_correction (MEASURED ls).
