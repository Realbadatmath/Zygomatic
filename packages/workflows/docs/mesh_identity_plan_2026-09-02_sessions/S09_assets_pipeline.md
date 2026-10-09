# S09: assets. Generic GLB to sheet, registrations, the Creature Studio mesh op, TRELLIS.2 texturing

Read `README.md` first. Plan sections 4, 5, 6 item F, 7 Phase 3. Notes: `understand_props_recon.md` sections 2 and 3, `understand_studios.md` section 3.

## Why this session exists
The mesh-to-control path is proven on stills (depth steers klein to rank 2 of 16 and Qwen to rank 3 of 16, chance 8.5) but exactly ONE registrable asset exists, because `prop_mesh/pufferball_sheet.py` imports the pufferball and its look patches; `hurlbat_sheet.py` renders three angles without passes. The registration contract (`prop_mesh_library.register` `:368`) needs a GLB, `sheet.json` with `views[] {id, azimuth, elevation, framing, distance_m, cam_r}` and `idx`, beauty PNGs, and EXR passes named `<view>_<kind>_*.exr` with kind in depth, normal, index (`:65`, `:178-196`), and normal EXRs must carry RGB-named channels (`pass_lib.rgb_named_socket`). `mesh_control.build` (`:158-262`) then makes subject-only depth, normal, lineart, segment, matte with the ground excluded by index name. Creature Studio has 221 ops and 0 touch geometry. TRELLIS.2 on disk ships a shape-conditioned texturing pipeline (`trellis2_texturing.py:375-383`, `Trellis2TexturingPipeline.run(mesh, image)`) that nobody has run.

## Owns / reads
Owns: new files under `prop_mesh/` (`sheet_render.py`, tests), `prop_mesh_library.py`, `mesh_control.py`, `creature_fx.py` (add ONE op; the file is 200 KB, grep and Edit only), `data/assets/prop_meshes/**` (new entries; the pufferball entry is verified and stays untouched), `/home/zygomatic/TRELLIS.2/ztest/**`. Reads: `prop_mesh/pufferball_sheet.py` and `pass_lib.py` (copy the pass wiring, do not edit), `comfy_generation_service.py` (`_pick_workflow` `:1820-1870`, Qwen `image2` injection `:2625-2665`, klein refcontrol `:2522-2570`), `creature_sheet_service.py`, `data/assets/mesh_packs/` (Smithsonian, Kenney, Poly Haven GLBs).
Blender: `blender -b --factory-startup` (the OBJ importer lays Z-up files on their side; GLB is Y-up and the viewer is Z-up, see `mesh3d.bin` rotation note). GPU: flock for TRELLIS and any Comfy render. Disk budget 10 GB.

## Tasks
1. **`prop_mesh/sheet_render.py`.** Any GLB in metres to the pufferball's 16 view ids, azimuths, elevations and framings; beauty PNG plus depth, normal (RGB-named sockets) and index EXR per view; `sheet.json` with `cam_r` per view, `idx` vocabulary including `ground`, `size_m`, and `assert_parts_visible` style pixel counts; then `prop_mesh_library.register(...)` with hashes and provenance inherited from the pack's own licence file. Prove generality on a Smithsonian bone (`data/assets/mesh_packs/smithsonian/`, pick a cranium or the Allosaurus) and a Kenney prop; run `mesh_control.build` on each and check `control.json` has no skipped views.
2. **View-rank receipt per asset.** Render the asset's 16 beauty views; for one klein render steered by the asset's `top_down` depth (the `klein_refcontrol` path, adapter on) report the rank of the true view among the 16 by DINOv2 (`creature_identity.similarity`), with adapter OFF as the null (chance 8.5).
3. **Creature Studio op (item F).** One new generative op in `creature_fx.py`: "mesh view": for a creature whose dataset has a registered mesh, take `mesh_control` depth for the chosen `cm_view` angle as Qwen `image2` (angles LoRA forced to 0, as the service already does when a depth map is present) and label it generative with the `~` pip and "[generative]" tooltip like the other 133. No page change is needed; the registry is server-side.
4. **TRELLIS.2 texturing test.** In the TRELLIS.2 venv run `Trellis2TexturingPipeline` on the SOLID procedural pufferball GLB (`data/assets/prop_meshes/pufferball/pufferball.glb`, exclude fur nodes; 52k solid verts) with the front anchor `lora-datasets/creatures/d0e44ab002ad/locks/full_body_J_cand_1.png`; render the result at the two anchor yaws with a neutral rig; score DINOv2 against both anchors with the v1 sphere and bald nulls from `prop_mesh/pbmetrics.py`; look at it. Record whether the texturing stage needs nvdiffrast (our build excludes it) and the peak VRAM.

GATES: two new VERIFIED registry entries; `control.json` clean for each; view-rank per asset with the adapter-off null; the texturing verdict with nulls and a side-by-side image.

## Do not
Edit `pufferball.py`, `pufferball_look.py`, `pufferball_sheet.py`, `pbmetrics.py`, `pbopt.py` or the pufferball registry entry. Edit `comfy_generation_service.py` or `creature_sheet_service.py`. Rebuild the creature sheet or retrain a LoRA (hand-offs only).

## Receipt
`receipts/S09.md`: renderer CLI, the two registrations with hashes, rank table, the op id, the texturing numbers and image paths, VRAM and time.
