# Blender 4.3.2 headless probe results — 2026-09-02
All runs: `/usr/local/bin/blender` -> `/opt/blender-4.3.2-linux-x64/blender`, Python 3.11.9, numpy 1.24.3. Scripts + raw logs live in this directory (p1..p9 *.py / *.log). Each probe ran under `timeout 120`.
Legend: MEASURED = number from a run here; VERIFIED-AT-SOURCE = read from a file/manifest/official index; CLAIMED = web-search summary; ASSUMED = not tested.

## P8 Startup cost (MEASURED, 3 runs each)
`for i in 1 2 3; do /usr/bin/time -f "addons %e s" blender -b --python-expr "pass"; done` -> 3.90 / 3.84 / 3.74 s
`... blender -b --factory-startup --python-expr "pass"` -> 0.19 / 0.19 / 0.20 s
Side effects of the add-on startup (every headless run): `SystemError: GPU functions for drawing are not available in background mode` (an add-on registers GPU draw at import; excepthook then crashes), sverchok `NODE_OT_tree_importer registration error`, asset_bridge urllib3 warning, blosm `_PT_` warnings. Bonsai injects a library link `extensions/.local/lib/python3.11/site-packages/bonsai/bim/data/workspace.blend` into any opened .blend (seen in P3 `bpy.data.libraries`). Recommendation: pipeline scripts use `--factory-startup` and enable only what they need. NOT TESTED (ASSUMED): `addon_utils.enable('bl_ext.user_default.mpfb')` under `--factory-startup`.

## P1 MPFB headless (PROVEN) — `blender -b --python p1_mpfb.py` (normal startup), log p1.log
- enable: `addon_utils.enable('bl_ext.user_default.mpfb', default_set=False, persistent=True)`; services at `~/.config/blender/4.3/extensions/user_default/mpfb/services/{humanservice,targetservice,rigservice,systemservice,locationservice}.py`.
- `HumanService.create_human(macro_detail_dict=...)` (humanservice.py:1485). Macro keys (targetservice.py:849): gender, age, muscle, weight, proportions, height, cupsize, firmness, race{asian,caucasian,african}. MPFB gender 0.0 = FEMALE, 1.0 = MALE (opposite of anny where 0.0 is male) — MEASURED by height: age0.3/g0 -> 1.385 m, age0.3/g1 -> 1.495 m. `height` is a slider, not metres: age0.5/g1/height1.0 -> 2.431 m.
- Each create: 0.21-0.32 s. Raw 19,158 verts / 18,486 polys (body + helpers); evaluated with the MASK modifier 13,380 verts / 13,378 polys; 152 vertex groups before rigging.
- Rigs on disk (VERIFIED-AT-SOURCE `mpfb/data/rigs/`): standard = cmu_mb, default, default_no_toes, game_engine, game_engine_with_breast, mixamo, mixamo_unity, **openpose**; rigify = human, human_toes. `SystemService.check_for_rigify()` False until `bpy.ops.preferences.addon_enable(module='rigify')` (0.06 s), then True.
- `HumanService.add_builtin_rig(bm, name, import_weights=True)` (humanservice.py:1547): default -> 163 bones, 0.55 s, mesh vgroups 291; game_engine -> 53 bones, 0.27 s, vgroups 204; rigify.human_toes -> 213-bone metarig, 0.32 s, vgroups 361 (mesh gets two ARMATURE modifiers).
- `bpy.ops.pose.rigify_generate()` on the MPFB metarig -> armature `Human.rigify` 1,090 bones in 0.63 s.
- GLB: `bpy.ops.export_scene.gltf(use_selection=True, export_apply=True, export_skins=True)` -> A (default rig) 968,820 B in 0.28 s; B (game_engine) 932,920 B in 0.10 s. Vertex count inside the GLB not re-imported (ASSUMED 13,380 body verts since export_apply applies the MASK).
- Whole script 3.05 s after the 3.8 s startup.

## P2 Rigify headless (PROVEN) — `blender -b --factory-startup --python p2_rigify.py`, log p2.log
`bpy.ops.preferences.addon_enable(module='rigify')` -> {'FINISHED'} 0.03 s. `bpy.ops.object.armature_human_metarig_add()` -> 159 bones. `bpy.ops.pose.rigify_generate()` -> `rig` 706 bones + ~230 WGT meshes in 2.48 s. Metarig operators present: armature_basic_human / basic_quadruped / bird / cat / horse / human / shark / wolf _metarig_add.

## P3 Blender Studio character (PROVEN, SLOW) — `blender -b ".../blender_studio_characters/ellie/ellie.blend" --python p3_studio.py`, log p3_ellie.log
- ellie.blend 21.8 MB (CC-BY). Armatures: META-ellie 466 bones (rigify metarig + cloudrig_parameters), RIG-Ellie 1,887 bones (CloudRig-generated; `rig_id`, `cloudrig` props). 154 objects, 13 collections, 66 shape keys across meshes. GEO-ellie_body 2,110 verts + SUBSURF; hair = mesh cards (GEO-ellie_hair 7,364, hair_cut 9,969, groom_base 4,719). Stdout: `scripts disabled ... skipping 'cloudrig.py'` (rig UI script; render unaffected).
- First render attempt FAILED: `RuntimeError: Cannot write a single file with an animation format selected` — the file's output is an FFmpeg format; fix `scene.render.image_settings.file_format='PNG'`.
- EEVEE-Next 256x256, 8 samples, existing LGT-Camera: **110.59 s** (MEASURED once; shader compile dominant — ASSUMED, second-frame cost not measured). Output p3_ellie.blend.png 44,142 B, visually verified: T-pose character, dark key.

## P4 Remesh / retopo (PROVEN with one FAIL-OPEN) — `blender -b --factory-startup --python p4_remesh.py`, log p4.log
- `bpy.ops.wm.obj_import(anny_neutral.obj)`: 13,718 verts / 13,710 polys, 0 non-manifold, 0 boundary edges (watertight). **The OBJ importer applies rotation_euler X=+90 deg (Y-up assumption); anny OBJs are Z-up, so the object lies along world -Y** — pass `up_axis='Z'` or clear rotation (P5 confirmed [1.571,0,0]).
- `bpy.ops.object.quadriflow_remesh(target_faces=5000, mode='FACES')` on anny: {'FINISHED'} 1.97 s -> 4,322 verts / 4,314 polys, 100% quads.
- REMESH modifier VOXEL on anny: voxel 0.01 m -> 21,484 verts / 21,474 faces; 0.005 m -> 86,208 verts; depsgraph eval 0.03 s each (MEASURED, surprisingly fast).
- Smithsonian `smithsonian/Entomology/Corydalus_affinis.glb`: 86,687 verts / 149,239 tris, 23,371 non-manifold (=boundary) edges, dims 0.078x0.037x0.023 m. DECIMATE to 50,000 tris 0.51 s. quadriflow -> returns {'FINISHED'} in 0.00 s with polys unchanged (50,000, 0 quads); only stdout `Warning: QuadriFlow: The mesh needs to be manifold and have face normals that point in a consistent direction` (p4.log:23). **FAIL-OPEN: a caller must assert the face count changed.** VOXEL remesh at bbox/100 (0.00078 m) -> 6,072 verts, closes the shell (works on non-manifold) -> route for scans is voxel -> quadriflow.

## P5 Shrinkwrap + Data Transfer (PROVEN as primitives; WEAK test) — `blender -b --python p5_wrap.py`, log p5.log
- Source: MPFB default human (19,158 raw / 13,380 body verts, 1.659 m, default rig 163 bones, 291 vgroups). Target: anny_neutral.obj (13,718 verts, 1.626 m, rotation cleared). Alignment: uniform scale 0.98 + bbox-centre match.
- NULL (do nothing after alignment): nearest-surface distance mean 4.0 mm, median 3.3 mm, p95 9.9 mm, max 22.9 mm. The two are near-identical (both MakeHuman-family topology), so this only proves the primitive runs, not that wrapping works on a dissimilar target.
- SHRINKWRAP NEAREST_SURFACEPOINT (0.06 s): distance -> 0 by construction; edge-length |ratio-1| median 0.068, p95 0.834, max 12.35 (null = 0) -> heavy distortion in the tail even on near-identical bodies.
- SHRINKWRAP PROJECT along normals, limit 0.2 m (0.06 s): mean 0.2 mm max 11.6 mm; edge distortion median 0.072, p95 1.55, max 98.
- DATA_TRANSFER VGROUP_WEIGHTS POLYINTERP_NEAREST MPFB -> anny via `bpy.ops.object.datalayout_transfer` + `modifier_apply`: 291 groups, 13,718/13,718 verts weighted, 0.27 s.
- Better target for a real test: `data/assets/mesh_packs/blender_human_base/human-base-meshes-bundle-v1.4.1/human_base_meshes_bundle.blend` (CC0, 10.6k quads).

## P6 Multires + normal bake (PROVEN) — `blender -b --factory-startup --python p6_multires.py`, log p6.log
Suzanne 507 verts, MULTIRES 2 x `multires_subdivide` (levels 2), Cycles CPU, `scene.render.use_bake_multires=True; bake_type='NORMALS'; bpy.ops.object.bake_image()` -> 256^2 map, mean R/G 0.500/0.504, std R 0.101 (null flat map: std 0). 0.10 s total. File p6_multires_normal.png.

## P7 Hair curves (PROVEN partial) — `blender -b --factory-startup --python p7_hair.py`, log p7.log
`bpy.ops.curves` has: add_bezier, add_circle, attribute_set, convert_from_particle_system, convert_to_particle_system, curve_type_set, cyclic_toggle, delete, draw, duplicate(_move), extrude(_move), handle_type_set, sculptmode_toggle, select_*, set_selection_domain, snap_curves_to_surface, subdivide, surface_set, switch_direction, tilt_clear. `bpy.ops.object.curves_empty_hair_add()` OK (Curves object, surface=Sphere, NODES modifier). API `Curves.add_curves([6]*200)` + point positions OK. `snap_curves_to_surface(attach_mode='NEAREST')` OK. `convert_to_particle_system` ran but yielded a particle system with count 0 (NOT validated; likely needs surface_uv_coordinate). EEVEE 128 px render with hair 0.80 s. glTF export drops Curves (GLB 70,248 B = sphere only) -> hair must be converted to mesh before GLB (not probed).

## P9 Version + side-by-side plan
- MEASURED: `bpy.app.version_string` 4.3.2 (release), binary /opt/blender-4.3.2-linux-x64/blender, symlink /usr/local/bin/blender; extension repos blender_org / user_default / system; config ~/.config/blender/4.3/{config,scripts,extensions}. Config and extension dirs are per MAJOR.MINOR, so a tarball at /opt/blender-5.2.1-linux-x64 would use ~/.config/blender/5.2 and coexist with 4.3.2 (extensions must be re-installed there). 138 GB free on /.
- VERIFIED-AT-SOURCE (download.blender.org/release/ index, 2026-09-02): Blender4.5/ (LTS; latest tarball seen in grep tail 4.5.9 21-Apr-2026, dir mtime 25-Aug-2026 -> newer point releases exist), Blender5.0/ (dir 16-Dec-2025), Blender5.1/ (dir 19-May-2026), Blender5.2/ with blender-5.2.0-linux-x64.tar.xz 14-Jul-2026 and blender-5.2.1-linux-x64.tar.xz 25-Aug-2026 (384 MB). CLAIMED (search result title "Blender 5.2 LTS Manual"): 5.2 is the current LTS. CLAIMED (search summary of docs.blender.org): legacy bl_info add-ons still supported through 5.x.
- Add-on declarations (VERIFIED-AT-SOURCE, minimums only, none declares a max): MPFB 2.0.17 `blender_version_min = "4.2.0"` (extensions/user_default/mpfb/blender_manifest.toml:10; upstream master identical); CAD_Sketcher 0.27.8 min 4.0.0 (user_default/CAD_Sketcher/blender_manifest.toml:11); bonsai 0.8.5-post1 min 4.2.0 (extensions/blender_org/bonsai/blender_manifest.toml:29); terrainmixer 3.1.3 min 4.2.0; legacy bl_info: CharMorph 0.4.0 blender (4,3,0) patched down from (4,4,0) (scripts/addons/CharMorph/__init__.py:35, ZYG comment); polyhavenassets 1.1.11 (3,2,0); sverchok 1.4.0 (3,5,0); blosm 2.4.21 (2,80,0). A min-only declaration is NOT proof of 5.x compatibility. From FACTS: CloudRig 2.2.28, Vitruvian 1.6.1, CAD Sketcher latest need >= 5.0; Poly Haven main needs 4.5.

## Output files
p1_A_age03_g0_default.glb, p1_B_age03_g1_gameengine.glb, p3_ellie.blend.png, p6_multires_normal.png, p7_hair.png, p7_hair.glb, p1.log p2.log p3_ellie.log p4.log p5.log p6.log p7.log p9.log
