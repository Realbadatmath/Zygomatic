# Research: image / multi-view -> 3D mesh reconstructors for OBJECTS + CREATURES (open weights), as of 2026-09-02

Evidence tags: MEASURED (run here) / VERIFIED-AT-SOURCE (fetched the file/page today) / CLAIMED (secondary source or memory) / ASSUMED.
Tool-call budget used: 45 (target ~40). Local clones inspected: /home/zygomatic/TRELLIS.2, /home/zygomatic/InstantMesh.

## The question that matters
Our failure is single-image reconstruction inventing the unseen half (TRELLIS.2-4B: tail absent; radial extent 49% further from anchor than a sphere — MEASURED, given).
We hold per creature: front anchor + right-side anchor (+16 mutually inconsistent Qwen rotations, not reference) + a LoRA + a body-plan sentence.
So the capability is MULTI-VIEW-CONDITIONED generation where each view is POSED (we know the anchors are 0 deg and 90 deg azimuth), with masks.

## Null model for ANY "the side view constrained the back" claim
- N0: same model, same seed, front anchor only (this is the run we already have for TRELLIS.2).
- N1: multi-view run with the side view replaced by a horizontally mirrored front (tests whether the second view carries information or merely adds tokens).
- Metric: silhouette IoU of the result rendered at the side anchor's camera vs the side anchor mask; plus the existing radial-extent / tail-presence metric. A fit number without N0 and N1 means nothing.

## Candidates (ranked)

### 1. Pixal3D (TencentARC) — TOP
- URL: https://github.com/TencentARC/Pixal3D ; weights https://huggingface.co/TencentARC/Pixal3D ; paper arXiv 2605.10922 (SIGGRAPH 2026).
- Licence: LICENSE = plain MIT, "Copyright (c) 2026 Tencent." No Territory / EU / NC clause (VERIFIED-AT-SOURCE, raw LICENSE fetched 2026-09-02). README: "This project is released under the MIT License. The third-party components remain licensed under their respective original terms; see NOTICE" (VERIFIED). HF model card: MIT (VERIFIED summary; the NOTICE file NOT read -> read it on install). WARNING: Tencent has shipped MIT-with-EU-restriction before (Tencent-XR-3DGen) and MIT-root/EU-core (TripoSG) — grep every .py + NOTICE for "EUROPEAN UNION|Territory|Hunyuan" on install.
- Input: single image OR multi-view: `python inference_mv.py --views_dir <dir> --output out.glb`; dir holds RGBA PNGs + transforms.json {camera_angle_x, mesh_scale, frames:[{file_path,name,transform_matrix 4x4 c2w}]}; Z-up world, cameras look down -Z with +Y up; "first frame should be the canonical front view" at (0,-d,0); alpha = mask, non-alpha views auto-segmented; example uses 4 views at 0/90/180/270 deg, no strict count stated (VERIFIED-AT-SOURCE README). Released "Sep 2026: Release multi-view inference code" (VERIFIED; today is 2026-09-02, so days old — expect rough edges).
- Mechanism: "explicitly lifts pixel features into 3D through back-projection, establishing direct pixel-to-3D correspondences" — i.e. the side view's pixels land in the side of the volume, which is exactly the constraint we lack (CLAIMED from abstract; unmeasured).
- Output: GLB mesh + PBR textures, TRELLIS.2 backbone (O-Voxel), so same topology class as our cornelis.glb (729k verts) — needs decimation/remesh for rigging (ASSUMED).
- Install: "follow TRELLIS.2 installation first" (we HAVE /home/zygomatic/TRELLIS.2 + venv, built WITHOUT nvdiffrast) + requirements.txt + natten==0.21.0 (CUDA-arch build) + utils3d 0.0.2 wheel; flash_attn optional (ATTN_BACKEND=sdpa). VRAM not stated; low-VRAM on-demand mode exists; TRELLIS.2 alone measured 2.7 GB here -> ASSUMED well under 48 GB. Two HF branches: default (TRELLIS.2 backbone) and "paper" (Direct3D-S2 backbone).
- Cost: 0 EUR.
- Fit: goal B directly (2 posed anchors -> geometry with the back constrained); goal A indirectly (a correct mesh -> per-frame depth/normal plates via existing mesh_control.py).

### 2. SAM 3D Objects (Meta) + training-free multi-view forks — STRONG
- URL: https://github.com/facebookresearch/sam-3d-objects ; forks: https://github.com/devinli123/multi-view-sam-3d-objects (training-free multidiffusion), https://github.com/devinli123/MV-SAM3D (per-latent weighting, uses Depth Anything 3 for view geometry), https://github.com/Roworks-ai/sam-3d-objects-multi (merges upstream PR #37 for multi-view — CLAIMED from search title).
- Licence: "SAM License" (last updated Nov 19 2025): "non-exclusive, worldwide, non-transferable and royalty-free limited license"; contracting entity "Meta Platforms Ireland Limited (if you are located in ... the EEA or Switzerland)" -> EU explicitly contemplated, not excluded; derivative works owned by you; no NC clause; Trade Controls + acceptable-use policy (VERIFIED-AT-SOURCE LICENSE). Same family as SAM 3 / SAM 3D Body already accepted as internal tools (given).
- NC-dep check: requirements.inference.txt = kaolin==0.17.0, gsplat (git pin), seaborn, gradio (VERIFIED). kaolin root licence is Apache-2.0 (CLAIMED from memory — verify at FILE level; kaolin bundles some NVIDIA-licensed subcomponents e.g. FlexiCubes). gsplat = Apache-2.0 (CLAIMED). requirements.txt / requirements.p3d.txt (pytorch3d, BSD) NOT fetched. No nvdiffrast / diffoctreerast found in the inference reqs.
- Input: single image + mask/point/box prompt; official = single view only. Forks: multiple images of the same object; devinli123 fork "training-free multidiffusion approach", 8-view dog example; MV-SAM3D needs Depth Anything 3 (DA3 code Apache; some DA3 weights are CC-BY-NC — CLAIMED, check before use) -> prefer the pure multidiffusion fork, which needs no DA3.
- Output: gaussian splats (output["gs"].save_ply) + mesh/texture/layout ("reconstructs full 3D shape geometry, texture, and layout") (VERIFIED README). GS->mesh path quality unknown.
- News: 06/2026 encoder weights + 3D-artist object set + HF leaderboard (VERIFIED).
- Install: separate venv (like body_venv, py3.11, torch 2.13+cu126 pattern); kaolin 0.17 wheel must match torch/CUDA — that is the friction point. Cost 0.
- Fit: goal B second route; the forks are unposed-ish (multidiffusion over per-view conditionings) so 2 views may under-constrain vs Pixal3D's posed back-projection. Null model as above.

### 3. TRELLIS.2 (already on disk) — STRONG, two specific uses
- URL: https://github.com/microsoft/TRELLIS.2 ; MIT code+weights (VERIFIED local LICENSE + README line 314); DINOv3 encoder commercial (given); our build excludes nvdiffrast/nvdiffrec (VERIFIED build_ext.sh line 3).
- Multi-image: NOT a released inference feature. Inference `get_cond(list[Image])` stacks images as a BATCH (B,N,D) — not multi-view (VERIFIED trellis2/modules/image_feature_extractor.py). BUT the trainer ships `MultiImageConditionedMixin` that concatenates patch tokens of all views into one cond sequence per sample (VERIFIED trellis2/trainers/flow_matching/mixins/image_conditioned.py:178-230); no released config uses it (grep configs/ = 0 hits). A tuning-free hack (concat tokens of front+side into cond, as TRELLIS v1 "multiimage" did) is a 20-line experiment, unposed, unmeasured. Pixal3D is the trained + posed version of this idea on the same backbone, so do Pixal3D first.
- Texturing: `example_texturing.py` / `app_texturing.py` = shape-conditioned PBR texture generation for a GIVEN mesh (VERIFIED README line 187) -> feed our procedural pufferball GLB + anchor image -> textured canon mesh without inventing geometry. This is the cheapest goal-B win available and needs no new install.
- Cost 0. VRAM 2.7 GB measured.

### 4. SpaceControl (ICLR 2026) — MAYBE (concept, not the repo)
- URL: https://github.com/spacecontrol3d/spacecontrol ; MIT (VERIFIED README). Training-free test-time injection of "coarse primitives to detailed meshes" into TRELLIS latents. Deps: nvdiffrast, diffoctreerast, kaolin, mip-splatting, vox2seq -> TRELLIS v1 stack = NC (VERIFIED README deps). Do NOT install. The idea (initialise/guide the sparse-structure latent from our own procedural mesh voxelisation) is re-implementable on TRELLIS.2 (O-Voxel, no diffoctreerast) — engineering, unmeasured.

### 5. Hi3DGen / Stable3DGen — MAYBE
- URL: https://github.com/Stable-X/Stable3DGen ; MIT code+weights, "removed its dependencies on certain NVIDIA libraries (kaolin, nvdiffrast, flexicube)" (VERIFIED README; file-level not checked). Single image -> normal map (StableNormal) -> geometry (TRELLIS-v1-derived). No multi-view. Possible use: feed a normal map RENDERED from our procedural mesh as the bridge = geometry refiner of our own mesh (ASSUMED workable; the normal-conditioned stage is what the paper trains). Cost 0.

### 6. Direct3D-S2 (DreamTech) — MAYBE
- URL: https://github.com/DreamTechAI/Direct3D-S2 ; MIT code+weights (VERIFIED README); single image; 1024^3 needs ~24 GB, 512 ~10 GB (VERIFIED); torchsparse dep; v1.2 "enhanced character generation" announced June 2025. Pixal3D "paper" branch is built on it. Single view -> invents back -> only as a high-res single-view comparator.

### 7. SPAR3D (Stability) — MAYBE
- URL: https://huggingface.co/stabilityai/stable-point-aware-3d ; Stability AI Community License: free incl. commercial under US$1M annual revenue, enterprise licence above (VERIFIED via HF README quote in search); no EU territory clause known (CLAIMED — licence text not fetched). Single image, <1 s; unique feature: the BACK is an explicit editable point cloud before meshing -> a human can drag the tail into existence. Not multi-view. Deps include its own texture baker; nvdiffrast? (unchecked). Cost 0.

### 8. Step1X-3D (StepFun) — MAYBE/LOW
- URL: https://github.com/stepfun-ai/Step1X-3D ; Apache-2.0 code+weights (VERIFIED README); single image only; 27-29 GB VRAM, ~152 s; deps kaolin 0.17 + pytorch3d + "custom rasterizer and differentiable renderer (adapted from Hunyuan3D 2.0)" (VERIFIED README) -> that adapted file may carry a Tencent header: FILE-LEVEL CHECK REQUIRED before use. No multi-view.

### 9. MV-Adapter — MAYBE (view generator, not a reconstructor)
- URL: https://github.com/huanngzh/MV-Adapter ; Apache-2.0 (CLAIMED, not fetched this session). Generates 6 consistent posed views from an image, with an optional geometry-conditioned mode (mesh -> views). Role: turn front anchor (+ our procedural mesh as geometry) into 4 posed views for Pixal3D MV or for texturing. Adds a generative step = can hallucinate; the anchors must stay the reference.

### 10. Tripo API H3.1 multiview-to-3D — MAYBE (paid fallback)
- URL: https://developers.tripo3d.ai/en/pricing ; "supports 2-4 views of the same object", API 100 credits = US$1 pay-as-you-go; commercial use on paid plans, free-tier outputs CC-BY non-commercial (CLAIMED from search summaries; terms page not fetched). Closed weights; service not EU-excluded as far as found (ASSUMED). Within 150 EUR by orders of magnitude. Use only if Pixal3D MV fails N0/N1.

## Rejected (one line each)
- Hunyuan3D 2.0/2mv/2.1/2.5/3.0/Omni/Part (Tencent): Territory excludes EU incl. outputs (given; the 2.1 licence text re-read today via UltraShape's LICENSE copy).
- UltraShape 1.0 (PKU): LICENSE file IS the Tencent Hunyuan 3D 2.1 Community License: "Territory ... excluding the European Union, United Kingdom and South Korea" (VERIFIED-AT-SOURCE).
- LATTICE (Zeqiang-Lai/LATTICE, CVPR'26): repo returned 404 on 2026-09-02; its open reproduction (UltraShape) is EU-excluded; Tencent-Hunyuan authorship -> assume same terms.
- Pandora3D / Tencent-XR-3DGen: "MIT License but with additional restrictions ... or within the European Union" (VERIFIED via README quote in search results).
- TripoSG, PartCrafter, DetailGen3D: EU-excluded core transformer file (given).
- MIDI-3D (VAST): single-image SCENE composition built on TripoSG (CLAIMED) -> inherits the core-file trap; wrong problem anyway.
- TripoSR (MIT): 2024 single-image LRM, low-res, invents back.
- InstantMesh + Zero123++: Apache root but nvdiffrast imported in src/models/lrm.py, lrm_mesh.py, mesh_util.py, neural_render.py, extract_texture_map.py (VERIFIED locally) and requirements.txt pins git+nvdiffrast -> NC trap; also expects 6 Zero123++ views at fixed poses, not our 2.
- Amodal3R: extends TRELLIS v1 (diffoctreerast NC), single view.
- Unique3D (ISOMER uses nvdiffrast, CLAIMED), Era3D (Apache CLAIMED), Wonder3D (MIT main / AGPL Wonder3D_Plus VERIFIED via snippet), LGM (MIT VERIFIED via HF), CRM (MIT CLAIMED, FlexiCubes/nvdiffrast CLAIMED): all 2024 single-image -> multi-view-diffusion -> reconstruct; the back is hallucinated by the diffusion stage; several carry nvdiffrast.
- SF3D: same licence as SPAR3D, single image, superseded by SPAR3D.
- Sparc3D: no LICENSE file in repo (raw LICENSE 404 on 2026-09-02) = all rights reserved by default; weights release not confirmed; single image.
- SpaceControl repo as-is: NC deps (nvdiffrast, diffoctreerast, kaolin) — kept only as a concept above.
- MeshSplat (AAAI 2026): generalizable 2-view surface recon via 2DGS/cost volumes for posed scene photos; a 90-degree baseline on synthetic renders is out of its training distribution; licence unchecked.
- VGGT (CC-BY-NC weights), Depth Anything 3 (some weights NC, CLAIMED), MapAnything: real-photo geometry estimators, not generative; the 16 Qwen rotations contradict each other so SfM/feed-forward geometry has nothing rigid to recover (given: mvconsist measurements).
- DreamCharacter-1 (arXiv 2607.07817, July 2026): no code/weights repository found on 2026-09-02; watch.
- trellis.cpp (pwilkin): C++/GGML port of TRELLIS.2 with HTTP server; single-image; no new capability.
- Rodin/Hyper3D, Meshy multi-image: paid closed services; not evaluated (Tripo covered as the one paid fallback).
- SV3D / Stable Zero123: view synthesis only, NC-research-tier weights (CLAIMED).
