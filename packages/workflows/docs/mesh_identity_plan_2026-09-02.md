# Mesh, identity and 3D: analysis and plan (2026-09-02)

Evidence tags used throughout: MEASURED (run or read on this box today), VERIFIED (read at the vendor or repo source today), CLAIMED (secondary source), ASSUMED (inference). Sources: five internal capability maps, six research sweeps, nine Blender headless probes, and the licence verdicts that finished before the workflow was stopped. Notes live in the session scratchpad under `mesh_plan/`.

## 1. Diagnosis: why identity is lost and why the mesh route stalls

1. **The video model is handed a constant where the subject lives.** VACE control frames carry grey 127 under the character mask. `geom/char_vace.py` paints ONE static skeleton for the whole clip. The per-frame path behind `ZYG_VACE_MASK_SEQ` exists, but in sequence mode the geometry painting is structurally unreachable (it sits inside the single-image branch, `wan_vace_service.py:1554-1618`), and `generate_vace_static_clip` has no way to accept an external folder of control frames. MEASURED: no per-frame geometry sequence has ever reached a GPU render. Zero `_vace_ctrlseq` receipts anywhere under output; the 41-frame `anny_animate` depth track from 2026-08-04 was never consumed by any graph; the only job that reached the static-skeleton branch found no character and kept neutral control.
2. **No per-shot pose track exists.** `anny_animate` is a two-pose lerp. `geom/keypoints.py` runs MediaPipe in IMAGE mode. SAM 3D Body is live and returns per-image MHR pose, shape and 70 3D keypoints in 1.2 s, but has no crews-side bridge and its worker drops the two fields a plate needs (`pred_vertices`, `pred_keypoints_2d`).
3. **Nothing measures WHO is in a finished clip.** `identity_bank.check_clip` exists and has zero production callers. `wan_face_restore` re-synthesises faces without scoring before or after. Clip QC measures motion and set drift, not identity.
4. **The registered bodies are not the bodies being animated.** Abel and Cornelis are phenotype-only recipes (six macro numbers, no locals). `anny_fit` and `anny_animate` rebuild the body from `phenotype.calibrate()`, never from the registry's `params.json`, so locals, anatomy layers, hand correction and bone scales never reach a plate. MEASURED: the fit and animation artefacts on disk carry gender 1.0 (female macro in Anny's convention) and a different height parameter than the registered Abel. Same split-brain class as the LoRA staging and phalanx-gate defects.
5. **No path from a 2D sheet to a per-character body SHAPE.** The fitter solves camera and pose only. The only shape evidence is the phenotype-lock residual (5.4 to 14.7 px), which says the SDXL canon draws Abel leggier than a true 12-year-old.
6. **The head is a measurement, not a body change.** GNM identity gain over the MEAN head is only +0.95 to +2.09 mm, the MediaPipe-478 to GNM landmark fit is not built, and there is no head-to-body bridge. Google has not released the GNM body (VERIFIED, roadmap only).
7. **Creatures: one licence-clean canon, one registrable mesh, and the anchors disagree.** Only the pufferball has clean anchors and a LoRA; the other three creatures are FLUX.1-dev references (non-commercial) with nothing a reconstructor may consume. The procedural route cost 68 agents and weeks, and its objective was gamed twice. TRELLIS.2 from one image invents the back (tail absent as geometry). Sheet rendering is pufferball-specific, so no second mesh can enter the proven depth-control path without new code.
8. **The studios promise 3D and draw a plane.** Every studio preview is a textured plane in an orbit scene. The Mesh tab is read-only (two GET routes). `mesh_control.py`, proven on stills (depth steers klein to rank 2 of 16 and Qwen to rank 3 of 16 against chance 8.5), has zero consumers. Movement Studio's MISSING list names exactly the plates this plan wires.
9. **The gate ledger is stale.** Anthro artefacts date 2026-08-08, source 2026-08-26; the pack itself prints STALE. Both derived bodies read FAIL, partly on the known phalanx split-brain.

## 2. The reframe: control-plate geometry first, perfect assets only where the camera orbits

The industry's leading open identity-through-video model, Wan2.2-Animate-14B (Apache-2.0, VERIFIED on the model card), takes a reference image plus a proportion-correct per-frame 2D skeleton and face crops. Its authors chose a 2D skeleton over SMPL "for better generality, particularly for non-humanoid characters". SCAIL (Apache-2.0) moved to rendered 3D-consistent pose plates. Neither ingests a 3D asset. Commercial tools (Kling Motion Control, Runway Act-Two) do the same with closed models and one reference image.

So the target for goal A is: geometry good enough to render a per-frame skeleton, depth, normal and segment plate with the character's own proportions, so the video model cannot reinvent the subject. A perfect textured asset is needed only for subjects the camera orbits (hero creatures, props held in hand), and that is goal B, handled separately.

## 3. Humans

- **Body stays Anny** (Apache code, CC0 data, all ages, differentiable). Installed version is 0.5 (MEASURED); 0.6 (2026-08-06) adds a new rig and facial actions. Upgrade only behind a four-state ledger, because joint chains the gates assume may move. NAVER's own image fitter `anny-fit` is a NAVER Non-Commercial licence with NC submodules (VERIFIED). BANNED. The in-house fitter keeps its name and its job.
- **Pose seed and per-frame track: SAM 3D Body to MHR.** `pip install mhr` (Apache-2.0 code and assets, VERIFIED) into the existing body venv decodes the 204 pose parameters to vertices. SOMA-X (Apache, on disk) is the only registration to Anny; nothing newer exists.
- **Head: GNM stays, plus ICT FaceKit for expression.** ICT FaceKit light model is plain MIT (VERIFIED), 100 identity modes, 53 ARKit-named blendshapes. MediaPipe's Face Landmarker emits ARKit-style blendshape scores, so per-frame face plates need no fitter at all. Identity fitting stays the in-house MediaPipe-478 to GNM job, with the mean-head null attached to every number.
- **Rigging:** Rigify is bundled and PROVEN headless (metarig to a 706-bone rig in 2.5 s; MPFB's `rigify.human_toes` metarig generates 1,090 bones in 0.6 s). MPFB also ships an `openpose` rig preset (VERIFIED on disk), which is the skeleton convention Wan understands. Both are free.
- **Do not buy:** Human Generator (assets non-transferable, adults only), Daz Genesis 9 (EULA excludes use with any AI system that generates derivative content), Character Creator (299 USD), KeenTools FaceBuilder annual (over budget; monthly 18.4 EUR only after the free 15-day trial proves identity gain on plate-steered renders).

## 4. Creatures

- The input problem comes first: mint licence-clean anchors for the three FLUX creatures (klein scratch mode), and reconcile the pufferball's mouth (front anchor open with teeth, side anchor closed beak). No tool at any price resolves anchors that disagree.
- **Pixal3D (TencentARC) is the first multi-view route to test, with one flag.** Checked at file level today: the GitHub LICENSE is plain MIT (Copyright 2026 Tencent), the NOTICE adds no territory or non-commercial term and lists only Apache-2.0 and MIT third-party components, the README carries no EU or NC text, and the Hugging Face repo is NOT gated (weights resolve without a token). The flag: the model card metadata sets `extra_gated_eu_disallowed: true`, which is inert while gating is off but shows Tencent's intent. Pin the weights locally the day they are fetched, register the entry in `model_licences.json` with this open question, and re-read the card before every re-download. It takes posed multi-view input (front and side with camera transforms, released September 2026), which is exactly the constraint the pufferball lacks. Install on top of the existing TRELLIS.2 venv (built without nvdiffrast) plus `natten==0.21.0` (a CUDA-arch build) and the `utils3d` wheel the README links; check at install time whether its texture stage needs nvdiffrast and, if so, use the geometry stage only. Its NOTICE lists only dinov2 (Apache-2.0), TRELLIS.2, Direct3D-S2 and MoGe (MIT). Multi-view input is `inference_mv.py --views_dir` with a `transforms.json`; the shipped example rig is four views at 0, 90, 180 and 270 degrees, elevation 0, 20-degree FOV, first frame the canonical front, and `--num_views 2` restricts a run to our two anchors.
- **Second multi-view route:** SAM 3D Objects (Meta, SAM License, the same family already accepted for SAM 3 and SAM 3D Body; VERIFIED) with the community training-free multi-view forks, in its own venv. Check `kaolin` at file level before install: kaolin is Apache-2.0 at root but ships a `non_commercial` module (FlexiCubes) that must never be imported. Second route, zero install: the TRELLIS.2 trainer already contains a multi-image conditioning mixin (VERIFIED in `trellis2/trainers/.../image_conditioned.py:178-230`) that no released pipeline uses; a tuning-free concatenation of front and side tokens is a small experiment.
- **Every geometry claim runs against two nulls:** N0 front-only (the TRELLIS.2 run already on disk) and N1 with the side view replaced by a mirrored front. Metrics: radial-extent profile at the side yaw, DINOv2 view-rank across 16 mesh renders, and binary checks the anchors demand (tail present, mouth present).
- **Texture without inventing geometry:** TRELLIS.2 ships a shape-conditioned texturing pipeline (MIT, on disk, untested here). Feed the procedural pufferball GLB plus the anchor.
- **Rig with UniRig** (MIT code and weights, VERIFIED; needs its own Python 3.11 venv with `bpy==4.2` pinned). Null: hand-placed armature with automatic weights, scored by deformation artefact area at a fixed bend.
- Deform generator output to the anchors (the ModelSheetTo3D approach) rather than trusting the generator. Its repo shows no licence file and depends on nvdiffrast, so reuse the idea, not the code.

## 5. Props

- The depth-control path is proven on stills for one asset. The missing piece is a **generic GLB-to-sheet renderer**: any registered mesh to 16 views with depth, normal and index EXR passes plus `sheet.json`, feeding `mesh_control.ensure()`. This unlocks 7,312 CC0 pack items and every future creature.
- **Point tracks for prop paste-back:** replace any CoTracker plan with DeepMind tapnet (TAPIR, BootsTAPIR, TAPNext++), code and checkpoints Apache-2.0 (VERIFIED). CoTracker, SpatialTrackerV2 and Pi3 weights are CC-BY-NC (VERIFIED).
- **Depth and normals for a moving subject without a mesh:** MoGe-2/3 (MIT, VERIFIED) and Depth Anything 3 Apache checkpoints only (Base, Small, Metric-Large, Mono-Large; the Giant, Large any-view and Nested checkpoints are CC-BY-NC, VERIFIED).

## 6. Studios to wire (in leverage order)

| # | What | Touches | Effort |
|---|---|---|---|
| A | Movement Studio PLATES rack: object picker to `mesh_control.ensure()` to the existing `prop_plates` kwarg (bp_movement never passes it today) | `movement_studio.py`, `bp_movement.py:316`, `mesh_control.py` | days |
| B | Driver-clip picker: clip to pose track to per-frame plates to a `control_dir`, with per-frame masks from the SAM 3 track (`ZYG_VACE_MASK_SEQ=1`) | `movement_studio.py`, `bp_movement.py`, `wan_vace_service.py`, `geom/anny_animate.py` | days, after Phase 1 |
| C | Character Studio `d_plate` and `d_angles`: render the registered body's depth at canonical angles and show it; make `controlnet_pose_reference` writable with path validation | `inspection.html` CS_TOOLS, `character_studio.py`, `kanban_server.py` | days |
| D | Mesh tab actions as POST routes with hash receipts: derive, reissue, gate re-run | `kanban_server.py`, `geom/mesh_skeletons.py` (the server runs in the agents venv, which cannot import Anny; route to a python3.12 subprocess) | days |
| E | Character Studio Body placeholders (proportions, shoulders, waist, hands, feet, neck, bodyfat) to Anny axes plus reissue. Needs the phalanx gate fix first or every edit reads FAIL | `character_studio.py`, `kanban_server.py`, `geom/mesh_skeletons.py` | week+ |
| F | Creature Studio `cm_view` mesh-backed variant: depth from the registered mesh at the chosen view as Qwen image2 | `creature_fx.py` (new op), `mesh_control.py` | days, only for creatures with a mesh |

## 7. Phases with gates

Every gate names its null. A number without its null is not a result.

**Phase 0, this week: unblock and measure, no new tools.**
- Add a `control_dir` argument to `generate_vace_static_clip` that feeds node 13 (LoadImagesFromFolderKJ) directly and keeps prop and character painting reachable per frame.
- Fix the fit/animate split-brain: build the body from the registry `params.json` (the `Subject.from_registry` pattern in `gates.py:1959`), then regenerate the 41-frame depth track for Abel from his registered body.
- First receipt: render that track through VACE with three arms on one seed and prompt: neutral grey, correct plates, wrong plates (another character's track). Wire `identity_bank.check_clip` as the scorer and add the frame-80 and frame-200 prop edge-correlation from the earlier measurements. Gate: the correct-plate arm beats BOTH nulls, else the plate is not steering.
- Re-run the anthro pack and gates so the ledger is current; fix `t5_phalanx_ratio` reading the pre-correction chain.
- Wire item A (prop plates picker). Rollback: env flag and the existing kwarg default of None.

**Phase 1, weeks 1 to 2: the pose track.**
- Crews bridge for SAM 3D Body (clone `sam3_service._run_worker`); worker keeps `pred_vertices`, `pred_keypoints_2d`, joint global rotations; batch all frames of a clip in one process; lock shape to the median over the track; one-euro smoothing on rotations. Gate: per-frame reprojection px against RTMPose 2D and joint jitter on a held pose, reported against a held-first-frame null and the two-pose lerp null.
- Plates from the track: skeleton in OpenPose colours, depth and normal from MHR vertices directly (no retarget needed for a plate); then map MHR rotations to Anny pose through SOMA-X so a child's proportions are re-stated, with the retarget error measured.
- Wire item B (driver-clip picker).
- Second engine: Wan2.2-Animate-14B fp8 (about 15 GB; ComfyUI native `WanAnimateToVideo`, VERIFIED in the Comfy docs). Feed OUR skeleton video, never the DWPose preprocessor the tutorial uses (dataset NC). Do not enable `--use_flux` retargeting (FLUX.1-Kontext-dev is non-commercial); retarget by rendering the reference from Anny. Gate: per-frame AuraFace cosine to canon against the static-skeleton VACE run, a wrong-reference run, and a frame-shuffled score. The authors advise against LoRAs trained on Wan2.2; ours are Wan2.1, so measure compatibility rather than assume it.
- Wan2.2-VACE-Fun-A14B (Apache-2.0, VERIFIED) as the depth-plate engine on the 2.2 backbone for creatures and props, once the 2.1 VACE path has its receipt.

**Phase 2, weeks 3 to 5: bodies and heads that are the character's.**
- Shape from the sheet: a bounded phenotype and locals solve over the multi-cell sheet (silhouette plus keypoints, held-out cells), baked into `params.json` programmatically through `derive` (never retyped). Nulls: the phenotype-only fit and the mean body at declared age and height.
- Head: MediaPipe-478 to GNM landmark fit per the GNM paper recipe; ICT FaceKit ARKit blendshapes as the expression channel; head-to-body bridge as an anatomy-layer delta (fitted minus mean GNM, applied to Anny head vertices) so topology and gates survive. Build the bridge only if per-character identity gain exceeds the seam's blending error.
- Wire items C, D, E.
- Rigging: Rigify for humans; Mixamo and BVH clips (bundled importers are enabled) retargeted onto the rig for shots without a driver clip.

**Phase 3, weeks 5 to 8: creatures and props as assets.**
- Generic GLB-to-sheet renderer; register a second and third mesh (a Smithsonian bone, a Kenney prop) to prove generality.
- Pufferball: TRELLIS.2 texturing from the anchor; SAM 3D Objects multi-view and the TRELLIS.2 concat experiment against N0 and N1; UniRig; per-frame depth plates through VACE-Fun. Wire item F.
- Mint anchors for the three FLUX creatures and run the same path.

## 8. Buy: nothing now. Three conditional purchases, in order

| Tool | Price | Licence line that makes it safe | Buy only when |
|---|---|---|---|
| Auto-Rig Pro (Superhive) | about 40 USD, roughly 45 EUR incl. VAT (CLAIMED; Superhive pages are Cloudflare-walled to fetchers) | Superhive rule (VERIFIED): code products are GPL or MIT and "the license of the code does not apply to the output"; non-code parts Royalty Free for commercial use | Rigify plus a constraint retarget fails a measured test: joint-angle RMS against the source clip and foot slide, on one Mixamo clip |
| Cascadeur Yearly Indie | 84 EUR per year, converts to perpetual builds (VERIFIED on cascadeur.com/plans) | Indie permits commercial use; revenue cap under 100,000 USD in the trailing twelve months; exports FBX, DAE, USD, glTF | The SAM 3D Body track proves too noisy to clean in code; it is a track-cleaning tool, not a tracker |
| Meshy Pro, one month | 20 USD, about 18.5 EUR (VERIFIED) | Paid plans: you own the outputs; no territory clause; no non-commercial clause (VERIFIED, terms of 2026-03-07). Caveat: Meshy may train on non-enterprise inputs and outputs | The pufferball anchors agree about the mouth AND local multi-view fails N0/N1. Free-tier outputs are owned by Meshy: never use them in production |

Rejected on licence or fit: Quad Remesher (EULA forbids using any mesh it touched to train or test any AI system, and forbids headless use; VERIFIED), Human Generator, Daz, Character Creator, Hunyuan3D and UltraShape (EU territory), InstantMesh (nvdiffrast at module level, undeclared Zero123++ weight licence), Rokoko Vision (cloud, terms unreachable, and a second black box is not a null), DeepMotion (humans only, adult actor spec), Move One (single-person iPhone capture), Kling, Runway Act-Two and Viggle (closed models, cannot load our LoRAs or plates), CoTracker, SpatialTrackerV2, Pi3 and the original VGGT checkpoint (CC-BY-NC), NAVER anny-fit (NC), every SMPL-based reconstructor, LTX-2 (its licence forbids training other models on its output).

## 9. Blender: what the probes proved

- Use `--factory-startup` in every pipeline script: 0.2 s versus 3.8 s, and an add-on registers GPU drawing at import which crashes the headless excepthook (MEASURED).
- MPFB headless is PROVEN: create a human in 0.3 s across age and gender (MPFB gender 0.0 is FEMALE, the opposite of Anny), rigs default (163 bones), game_engine, mixamo, openpose, rigify; GLB export in 0.3 s.
- Rigify PROVEN headless. Blender Studio rigs open and render but the first EEVEE frame costs 110 s (shader compile).
- QuadriFlow PROVEN on watertight input (Anny to 4,322 quads in 2 s) and FAIL-OPEN on non-manifold input: it returns FINISHED with nothing changed. Assert the face count moved. Route for scans: voxel remesh, then QuadriFlow.
- Shrinkwrap and Data Transfer run (weights transferred to 13,718 of 13,718 vertices in 0.3 s); the test target was near-identical topology, so wrapping onto a dissimilar target is still unmeasured.
- Multires normal bake PROVEN. Hair curves work headless but glTF drops them; convert to mesh first.
- The OBJ importer rotates Anny's Z-up files onto their side; pass the up axis explicitly.
- Version: stay on 4.3.2 now. Blender 4.5 LTS (same Python 3.11) is the safe side-by-side upgrade. Blender 5.x needs a Python 3.13 rebuild of every compiled add-on and is justified only by CloudRig, Vitruvian and CAD Sketcher 0.30.

## 10. Costs the operator should expect

- Disk: 137 GB free. Wan2.2-Animate fp8 about 15 GB (pick one precision, not both). SAM 3D Objects venv plus weights roughly 10 GB. UniRig venv a few GB.
- VRAM: a Qwen edit already needs the whole card when the transcriber holds 4 GB. Run per-frame estimation (SAM 3D Body, MoGe) and video renders sequentially, never beside a ComfyUI job.
- Time: every Phase 0 receipt is a real VACE render (minutes each, three arms). Budget an evening.

## 11. What stays unsolved after Phase 3

- A creature's back when the two anchors disagree. That is an authoring decision, not a reconstruction problem.
- A true per-character body shape from an SDXL canon that is itself inconsistent (Abel drawn leggier than a 12-year-old). The fit can only measure the disagreement and let the operator choose which side wins.
- Children: every adult-derived tool (MHR, FaceBuilder, Human Generator) mis-serves Abel; Anny and MPFB are the only all-age bodies, and Anny's finger proportions are still ours to correct.
- 197 of 199 characters have no anchors and no registered body. The plan produces the machine; minting the inputs is per-character work.
- Fur never travels in a GLB.

## 12. Candidate table

| Candidate | Licence verdict | Capability verdict | Cost | Role |
|---|---|---|---|---|
| Wan2.2-Animate-14B | allowed, Apache-2.0 (VERIFIED) | fits goal A, humans and (per authors) non-humanoids with a skeleton | 0 | identity-through-motion engine |
| Wan2.2-VACE-Fun-A14B | allowed, Apache-2.0 (VERIFIED) | fits goal A for depth plates on the 2.2 backbone | 0 | plate engine |
| SAM 3D Body per-frame track | allowed, SAM License (accepted) | fits, the missing pose track | 0 | tracker |
| MHR + pymomentum | allowed, Apache-2.0 (VERIFIED) | fits, decodes SAM 3D Body output | 0 | body decode |
| ICT FaceKit light | allowed, MIT (VERIFIED) | fits expression plates; identity fit still ours | 0 | face expression |
| GNM Head fit | allowed, Apache-2.0 | partial, fine-detail space | 0 | head identity |
| UniRig | allowed, MIT code and weights (VERIFIED) | fits creatures and props | 0 | auto-rig |
| Rigify, MPFB rigs | allowed, bundled GPL tools | proven headless | 0 | human rigs |
| tapnet (TAPIR family) | allowed, Apache-2.0 (VERIFIED) | fits prop tracks | 0 | 2D point tracks |
| MoGe-2/3 | allowed, MIT (VERIFIED) | fits per-frame depth and normals | 0 | plates without a mesh |
| Depth Anything 3 (Apache checkpoints only) | allowed with file-level pick | fits QC depth | 0 | depth QC |
| SAM 3D Objects + MV forks | allowed, SAM License; check kaolin non_commercial module | partial, multi-view is community code | 0 | creature geometry |
| TRELLIS.2 texturing and concat experiment | allowed, MIT (on disk) | partial, unposed | 0 | texture, experiment |
| MapAnything (Apache checkpoint) | allowed | maybe, static scenes | 0 | goal B geometry |
| VGGT-1B-Commercial | gated application | maybe | 0 | goal B geometry |
| Meshy Pro | allowed (VERIFIED, high) | partial: views must be same pose; vendor trains on inputs | 18.5 EUR/month | paid fallback |
| Tripo Pro or API | allowed on paid tiers (VERIFIED via a Wayback copy; live terms Cloudflare-walled) | partial: 4-slot conditioner trained on consistent renders; ranked below TRELLIS.2 on inconsistent views | 18.4 EUR/month | paid fallback |
| Hyper3D Rodin Creator | allowed (VERIFIED, medium) | partial: unposed concat, back invented without a back view | 27.8 EUR/month, no API on this tier | paid fallback |
| Cascadeur Indie | allowed (VERIFIED) | partial: humanoid track cleaning only | 84 EUR/year | conditional |
| Auto-Rig Pro | allowed (Superhive code rule VERIFIED; price CLAIMED) | fits retarget and custom limbs | about 45 EUR | conditional |
| KeenTools FaceBuilder | allowed (terms VERIFIED); annual over budget | partial, adult-derived head | 18.4 EUR/month | trial first |
| DeepMotion, Move One | allowed on paid tiers | does not fit (humans only, adult spec, invents the unseen side) | 14 to 44 EUR/month | rejected |
| Rokoko Vision | allowed (medium) | does not fit | free to 11 EUR | rejected |
| Pixal3D (multi-view mode) | allowed at file level: MIT code and weights, NOTICE and README clean, HF repo not gated (VERIFIED); flag: card metadata `extra_gated_eu_disallowed` | fits goal B: posed front and side input, TRELLIS.2 backbone | 0 | creature geometry, first route |
| Quad Remesher | BANNED, EULA forbids AI use and headless use | fits retopo | 101 to 140 USD | rejected |
| Hunyuan3D family, UltraShape, LATTICE, Pandora3D, TripoSG, PartCrafter | BANNED, EU territory | | | rejected |
| InstantMesh, SpaceControl repo, TEXGen, UniTEX, MV-Adapter as shipped | blocked by nvdiffrast (NC) at module level | | | rejected unless the dependency is replaced |
| CoTracker, SpatialTrackerV2, Pi3, VGGT original, Pippo, PuzzleAvatar, MICA, EMOCA, SMIRK, anny-fit (NAVER) | BANNED, non-commercial | | | rejected |
| Human Generator, Daz Genesis 9, Character Creator 5 | licence or budget | | 118 EUR, free, 299 USD | rejected |
