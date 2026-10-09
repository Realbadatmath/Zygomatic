# UNDERSTAND — props, creatures, image->3D (2026-09-02, read-only)
Tags: MEASURED = I ran it / read the artefact; VERIFIED-AT-SOURCE = fetched today; CLAIMED = stated in repo docs/manifests, not re-run; ASSUMED = my inference.
Paths: C = /home/zygomatic/Zygomatic Full/agents/crews

## 1. Inputs that exist per subject (what a reconstructor could consume)

### Pufferball d0e44ab002ad (the only creature with a licence-clean canon) — MEASURED (ls + manifest)
- brief.json: body_plan sentence, negative list, anchor_locks {full_body: locks/full_body_J_cand_1.png, side: locks/side_S_cand_2.png}; 5 lock candidates in locks/ (2 full-body, 3 side).
- contact_sheet/: 16 Qwen-rotated cells + anchors/ candidates/ nulls/ refs/ strips/ variants/ + sheet.json report. Cells CONTRADICT each other (FACTS); only the 2 anchors are reference. nulls/bald and refs/furry exist as direction-test pairs (registry provenance.objective_repair_2026_09_01).
- LoRA: klein, /home/zygomatic/lora-outputs/creatures/d0e44ab002ad/lora-weights-klein/pytorch_lora_weights.safetensors; staged as comfy loras/zygchar_d0e44ab002ad_klein.safetensors (+ a zygchar_d0e44ab00fff_klein variant). manifest.status=trained, trigger ZYG_CREATURE_D0E44A. 38 training tiles.
- Procedural mesh (registered, C/data/assets/prop_meshes/pufferball/): pufferball.glb (331k verts incl. fur nodes; 52k solid), pufferball.blend (fur lives ONLY here), sheet.json, mesh3d.bin, 16 beauty PNGs, 48 EXR passes (depth/normal/index x16), control/ = 80 PNGs (depth, normal, lineart, segment, matte x16) + control.json with skipped:{} — MEASURED by listing + control.json read.
- TRELLIS.2 mesh: mesh_trellis/pufferball_trellis.glb 816,212 verts / 926,334 tris, all-triangle, vertex colour only (COLOR_0), no atlas, scale UNBOUND (unit-normalised; bbox 0.94x1.00x0.88 units) — MEASURED (manifest.mesh_recon).
- No Wan LoRA for the creature (wan_props holds only zygledger, zygpipe).

### The other 3 creature datasets — MEASURED (manifests)
- 0246a7387b5b Gray Wolf, 0974b5fd2baf Photorealistic Dragon, 808fc04eca07 Crimson Obsidian Dragon.
- Each: 12 refs ref_00..11.png + .txt captions, 3 preview PNGs, manifest.source = flux_reference_gen (FLUX.1-dev = NC, licence-paused; creature_fx.py:104-114 FLUX1_FAMILIES withholds renders).
- NO brief.json, NO locks/, NO contact_sheet/, NO body_plan, NO LoRA, NO mesh. There is NOTHING licence-clean a reconstructor could consume for these three; a clean anchor pair must be minted first (creature_sheet_service scratch mode = klein txt2img).

### 199 storyteller characters — MEASURED (python walk of /home/zygomatic/lora-datasets/storyteller_chars)
- 200 dirs; 156 manifest.json; 132 character_bible.json (18 top-level keys: identity, canon_appearance, conditioning, style_profile, motion_profile...); 41 have contact_sheet/cells (Cornelis: 49 cells incl. cell_00_body.png = the TRELLIS input); 0 have contact_sheet/anchors populated; manifest.lora_path is None on all 156 (LoRAs live elsewhere).
- LoRAs: /home/zygomatic/lora-outputs/storyteller_chars/ has 98 dirs and 29 .safetensors; comfy loras/ has 7 zygchar_* (0015c8a3f2e3 klein/qwen/sdxl, c3345deb5bde qwen/sdxl, d0e44ab002ad klein x2) + zygmc_* x2. Wan char LoRAs: 0015c8a3f2e3 and c3345deb5bde (i2v + _t2v each).
- Registered bodies: mesh_skeletons/derived/{abel,cornelis}, originals/{male,female} only.
- So for 197 of 199 characters the reconstructor-consumable input is: a bible + (for 41) a 2D contact sheet. No anchors, no body, no depth.

## 2. Exactly what a mesh must provide for mesh_control / klein_refcontrol

### Registration contract — prop_mesh_library.py
- register(asset_id, src_dir, *, name, kind, glb, blend, sheet_name='sheet.json', creature_id, licence, provenance, ...) at :368. src_dir MUST contain a .glb (ValueError otherwise, :386-388); .blend optional; sheet.json copied; beauty/ and passes/ copied.
- Pass naming: passes/<view_id>_<kind>_*.exr with kind in ('depth','normal','index') (:65, pass_path :178-196 matches prefix '<view>_<kind>_'). Beauty: beauty/<view_id>.(png|jpg|webp) (:166-176).
- sheet.json fields consumed: views[] {id, azimuth, elevation, framing, distance_m, cam_r (3x3 world rotation), passes_furred}, idx {name:int} IndexOB vocabulary, size_m, params (MEASURED from the pufferball sheet.json).

### Control-map contract — mesh_control.py
- build(asset_id, view_ids, exclude=('ground',), normalize='view'|'asset', kinds subset of (depth, normal, lineart, segment, matte)) :158-262 -> control/<view>_<kind>.png + control.json.
- Requires: depth EXR (view skipped otherwise :190-192); index EXR + idx map so 'ground' can be excluded (:63-71, warning :173-176 if exclude names absent); cam_r per view or the normal map is WORLD-space and flagged not-valid-ControlNet (:113-129, :224-230); normal EXR must have RGB-named channels (pass_lib.rgb_named_socket) or normal=null (:34-39, :217-218).
- Polarity: depth near=white inverse depth, background black; normal camera-space (n*0.5+0.5), viewer-facing (128,128,255) (:249-251). Fail-closed: empty subject mask -> skipped, never a black PNG (:24-27, :193-199).
- normalize='asset' shares one depth range across views — what a TURNTABLE needs (:29-32, :132-154).

### Diffusion consumption — comfy_generation_service.py + _comfy_workflows/klein_refcontrol.json
- _pick_workflow(..., pose_image=) :1820-1870: klein family routes to 'klein_refcontrol' ONLY when pose_image (a depth PNG path) AND (reference_image or init_image) both exist AND klein_control_lora_name() is staged (:1860-1865). Missing either -> falls through to klein_edit_angle / txt2img (depth silently ignored, comment :1866).
- Graph (klein_refcontrol.json, MEASURED node list): 10 UNETLoader flux-2-klein-base-4b; 13 LoraLoader identity LoRA (bypassed if unstaged); 14 LoraLoaderModelOnly flux2_klein_4b_refcontrol_depth.safetensors stacked on 13; 22 LoadImage depth.png -> 23 scale 1MP -> 24 VAEEncode -> 26/27 ReferenceLatent (ref 1); 42 LoadImage reference.png -> 44 -> 28/29 ReferenceLatent (ref 2, chained = image index); 30 EmptyFlux2LatentImage 1024^2; 34 CFGGuider cfg 5.0 from node 14; 33 Flux2Scheduler 20 steps; euler.
- Service guards :2522-2570: depth first by default (ZYG_KLEIN_REFCONTROL_ORDER=depth_first), 'refcontrol' trigger prepended if absent (:2569-2570), adapter strength = klein_control_lora_scale (:391, :2555).
- Qwen-Image-Edit path :2625-2665: pose_image injected as node 16 LoadImage -> image2 of TextEncodeQwenImageEditPlus nodes 20/21; image1 stays the appearance anchor; angles LoRA forced to 0.0 when a depth map is present (:2661-2665).
- VIDEO: NOT wired. bp_movement._resolve_object :222-245 uses only previews[0] as the still + an optional wan_props/wan_prop_<id>.safetensors LoRA; movement_studio.py:1080-1095 MISSING list: no pose/depth plates picker, no rigid prop plates (prop_control can composite but nothing knows where the prop is). wan_vace_service grey-127 under the mask (FACTS).
- GUI: kanban_server.py:190-221 _prop_mesh_list lists registered props on the Mesh tab (ZM3D orbit viewer); :223-232 objects picker for Movement Studio. NO route calls mesh_control.build or TRELLIS; creature_fx.py:93 and kanban_server.py:677 'mesh' = a display CATEGORY for images already in mesh_trellis/, not an op. creature_fx grep for op ids matching mesh|3d|depth|turntable|rig|pose|angle|trellis: 0 hits (only :3546 angles_lora weight). 0 of 221 ops touch geometry.
- Generality gap: pufferball_sheet.py imports pufferball as PB and applies pufferball_look patches (:63-90, :141-196) — the only thing that can produce a registrable sheet is pufferball-specific. A generic GLB->sheet orbit script does not exist (hurlbat_sheet.py renders 3 angles, no passes/sheet.json). Therefore exactly ONE registrable asset exists and no second mesh can enter klein_refcontrol without new code.

## 3. Procedural route cost vs what TRELLIS.2 delivered

### Procedural (pufferball) — CLAIMED from registry provenance + pbmetrics/pbopt headers, numbers MEASURED there
- Code mass: pufferball.py 47 KB (39 parts, later 49) + pufferball_look.py 557 KB (~7.7-9k lines of cumulative agent code with shadowed names, pbopt.py header) + pbmetrics 53 KB + pbopt 45 KB + pufferball_sheet 26 KB.
- Look-dev: 68 agents, three convergence runs, ~10 h wall clock, ~15 points explored in ~50 dims (pbopt.py header; registry.provenance.lookdev). Critic certified "zero majors" on a render the operator called far off.
- CMA-ES fit (2026-08-29): 20 params searched, 3 adopted, 400 evaluations at 768 px, 11 s per single 512/24 view (pbopt header). Composite loss 0.7438 -> 0.5149 (0=anchor, 1=v1 sphere null); 91% of the gain was FRAMING nobody had measured. The objective was gamed twice: 'fill' term maximised by a bald body (08-29); repaired objective still ranked the bald null 2.1% better than the furry render (09-01) -> direction_report + coat gate.
- Still-open gaps (registry known_gaps): mouth aperture, pupils, belly gold, tail bands/thickness, feet as sphere rows not 3-toed pads, no chin V, flat plate, fur colour, arm gloss. Fur only in .blend (particle), passes render bald by design.
- Anchor aspect error 5.7% (v1 7.0%). Null model for all of it: v1 sphere + bald null + anchor-vs-mirror.

### TRELLIS.2-4B (MEASURED from ztest/*_report.json + manifest.mesh_recon)
- Runtime pufferball: load 48.8 s, generate 112.1 s, export 33.8 s, total 195.4 s, peak VRAM 8.26 GB, 49152 tokens, seed 42; cornelis: 120 s total, 2.71 GB, 729k verts. Raw 5.95M verts -> 816k after clean/simplify.
- Venv /home/zygomatic/TRELLIS.2/venv: py 3.12.3, torch 2.6.0+cu124, CUDA available; imports OK: o_voxel, cumesh, flex_gemm, xformers 0.0.29.post2; ABSENT: nvdiffrast, nvdiffrec, diffoctreerast, diff_gaussian_rasterization, flash_attn, kaolin, spconv (MEASURED by import). build_ext.sh deliberately excludes nvdiffrast/nvdiffrec. zovox_geom.py replaces to_glb's nvdiffrast texel bake with per-vertex sampling -> vertex colours, UVs preserved. rembg swapped RMBG-2.0 (CC BY-NC) -> BiRefNet (MIT) in zrun_trellis.py. DINOv3 encoder licence 'commercial permitted, gated' is CLAIMED in the manifest chain, not verified by me.
- SINGLE-IMAGE ONLY: Trellis2ImageTo3DPipeline.run(self, image: Image.Image, ...) trellis2_image_to_3d.py:489-491; get_cond(image: list[Image.Image]) :164 accepts a list but run() wraps [image] (:539-540); grep 'multi' in the pipeline: 0 hits. A shape-conditioned TEXTURING pipeline exists: Trellis2TexturingPipeline.run(mesh: trimesh.Trimesh, image) trellis2_texturing.py:375-383 — untested here.
- Fidelity vs procedural (manifest.mesh_recon.measured_2026_09_01; both meshes through one neutral rig; nulls = v1 sphere, bald null): FRONT excellent by eye (irises with pupils/lids, open mouth with teeth, 3-toed feet, fur as displaced geometry = 4 of the 5 procedural gaps) but UNMEASURED — no term scores them. SIDE 'not the creature': radial_extent_2d side normalised distance TRELLIS 1.493 vs procedural 0.739 vs canon 0.641 (1.0 = sphere) -> 49% further from the anchor than a ball; radial_extent_3d TRELLIS 1.621 vs procedural whole 3.671 (tail reach 4.14x body radius) -> tail absent as GEOMETRY. bbox aspect comparable (never the discriminator). Silhouette IoU REFUSED: the sphere beat both meshes (0.770/0.667). Only front_full + side_left rendered.
- Verdict recorded: usable as front-half reference; not a replacement. It is a SECOND mesh; does not relicence the procedural one.

### InstantMesh (/home/zygomatic/InstantMesh) — MEASURED unless noted
- Clone at commit 08822c5 (2025-01-03). NO venv, NO ckpts/, NO weights in HF cache (no zero123plus / InstantMesh entries). requirements.txt pins git+nvdiffrast (NC), transformers==4.34.1, diffusers==0.20.2, pytorch-lightning==2.1.2.
- nvdiffrast is a MODULE-LEVEL import in src/models/lrm.py:19, lrm_mesh.py:18, src/utils/mesh_util.py:14, geometry/render/neural_render.py:11, rep_3d/extract_texture_map.py:12 -> the reconstructor cannot import without the NC library; not an optional preview.
- Code LICENSE: Apache-2.0 (file read). Weights TencentARC/InstantMesh: HF card license apache-2.0 (VERIFIED-AT-SOURCE 2026-09-02). sudo-ai/zero123plus-v1.2 weights (run.py:100): HF page 'No model card', API record has NO license field, lastModified 2024-02-01, gated false (VERIFIED-AT-SOURCE 2026-09-02) -> weight licence UNDECLARED. (zero123plus GitHub code is Apache-2.0 — CLAIMED from memory, not fetched.)
- Status: DEAD for this operator: undeclared weight licence + hard NC dependency + stale pins; and it is still single-object multi-view-from-one-image (same 'invents the back' failure class — ASSUMED from method).

## 4. Consequences for the orchestrator
- Depth-from-mesh control is PROVEN for stills (FACTS rank 2/16) and wired end-to-end klein + qwen; it is NOT wired for video (Movement Studio) and cannot be fed by any mesh but the pufferball because sheet rendering is pufferball-specific.
- No reconstructor on disk takes >1 image. The multi-view instrument that exists (geom/mvconsist SfM) measures consistency; it does not build geometry.
- For the 3 FLUX creatures and 197 characters, the missing input is upstream of any mesh tool: licence-clean anchors (creatures) and registered bodies (humans).
- Nothing in this area is fixed by a <=150 EUR purchase: the failure is 'unseen half invented' and 'anchors disagree', which are input problems.
