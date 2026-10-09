# Research process — dimension: devil's advocate + industry practice (2026-09-02)
Tool calls used: 41 (1 facts read, 1 toolsearch, 14 searches, 17 fetches, 1 local bash, 1 notes write, 1 output).
Tags: MEASURED (our own numbers, from FACTS) / VERIFIED-AT-SOURCE (read on the vendor/repo page today) / CLAIMED (third-party blog or search snippet) / ASSUMED (my inference).

## Local verification (MEASURED today)
- /home/zygomatic/InstantMesh: bare clone (48 MB), Apache LICENSE, requirements.txt pulls `git+https://github.com/NVlabs/nvdiffrast/` (NVIDIA NC), no ckpts/ dir -> state = never installed, NC dependency, superseded by TRELLIS.2 on disk.
- No MV-Adapter / Era3D / UniRig / Uni3C / Wan-Animate checkout under /home/zygomatic (find, depth 2). Only /home/zygomatic/ai-models/AnimateDiff matched "animate".

## Q1 evidence — is a "perfect 3D model" the target, or control-plate-grade geometry?
- Wan2.2-Animate-14B (HF card, VERIFIED-AT-SOURCE): Apache-2.0, released 2025-09-19, 14B, 40-60 GB peak single-GPU fp16 (community fp8/block-swap runs on 24 GB, CLAIMED). Paper 2509.14055 (VERIFIED-AT-SOURCE): body driven by ViTPose 2D skeleton; face by implicit 1D latents (Wang et al. 2022 encoder, linear motion decomposition); retargeting = per-limb length ratio scaling to the reference character; authors chose 2D skeleton over 3D SMPL "for better generality, particularly for non-humanoid characters", while admitting 2D skeletons have "spatial ambiguity ... missing or erroneous keypoints".
  -> Industry's leading open identity-through-video model needs (reference image + proportion-correct skeleton track), NOT a 3D asset. The mesh's job is to emit that track with the right proportions (Abel 12y, not the actor's).
- SCAIL (zai-org, CVPR 2026 Findings, VERIFIED-AT-SOURCE): Apache-2.0; Wan2.1 14B DiT; "3D-consistent pose representation" + full-context pose injection; pose extraction via NLFPose (BANNED here: NLF sits on SMPL); trained <512p; weights 2025-12-11; wan branch 2025-12-19.
  -> Frontier moved from 2D skeleton to RENDERED 3D pose plates. That is exactly what a rigged mesh gives us if we render the plate from Anny instead of NLF (ASSUMED feasible; convention in POSE_INSTRUCTION.md not read).
- Uni3C (alibaba-damo-academy, SIGGRAPH Asia 2025, VERIFIED-AT-SOURCE): Apache-2.0; camera control = point clouds unprojected from Depth-Pro monocular depth (PCDController), human control extracted with GVHMR (BANNED); weights 2025-05-22; ~50.8 GB with offload on one H20 -> marginal on 48 GB.
- Diffusion as Shader (SIGGRAPH 2025, CLAIMED from abstract): "versatile and precise video generation control fundamentally requires 3D control signals" — 3D tracking videos as universal control.
- GEN3C (CVPR 2025, CLAIMED): conditions on 2D renderings of a 3D cache along a camera path; NVIDIA research licensing for business.
- VideoFrom3D (arXiv 2509.17985, 2025-09-22, VERIFIED-AT-SOURCE abstract): coarse geometry + camera trajectory + reference image -> image-diffusion anchor views + video-diffusion geometry-guided inbetweening; static scenes only.
- PrevizWhiz (CHI 2026, arXiv 2602.03838, VERIFIED-AT-SOURCE abstract): rough 3D scenes + generative image/video; filmmakers' study: lowers barriers, but raises continuity/authorship concerns.
- Commercial (CLAIMED, vendor help + blogs 2026): Runway Act-Two = driving performance video + character reference; Kling Motion Control = skeleton extraction + retarget onto a target image; Runway Gen-4 References "does not reconstruct full 3D geometry — pattern-matches from a 2D reference; extreme angles break". None ingest a 3D asset. Community production workflows (RunComfy "Blender to ComfyUI AI Renderer 2.0", "Wan 2.2 Graybox to Rendered Sequence"): Blender depth/outline/pose passes -> Wan VACE.
- Our own MEASURED: mesh-driven depth steers klein (rank 2/16) and Qwen-Edit (3/16) vs chance 8.5; anny_animate 41-frame depth validated; VACE 14B on disk; MISSING = per-shot pose tracks, driver-clip picker, plate pickers.

## Q2 evidence — creature from a 2D sheet with no referent
- ModelSheetTo3D (Yoon et al., Eurographics 2026 / CGF 70323; GitHub hjyoon02/ModelSheetTo3D, VERIFIED-AT-SOURCE README): TRELLIS base mesh from yaw-annotated sheet views (TRELLIS.2 / Meshy listed as alternatives); APAP Jacobian deformation to match the sheet; three-layer appearance (view-dependent lines / view-independent colour / decals); "deformable per-pixel camera ray representation ... despite geometric inconsistencies" (abstract, CLAIMED via snippet). Deps: nvdiffrast (NC), Blender 4.3.2 (matches ours), torch 2.6; tested on RTX 4090. NO licence file seen in README -> CHECK before use.
  -> Academic confirmation that sheets are geometrically inconsistent by nature and the fix is deform-generator-output-to-anchors, not trust-the-generator.
- RCM "Rotate Your Character" (arXiv 2601.05722, 2026-01-09, VERIFIED-AT-SOURCE abstract): I2V diffusion orbital video at 1024², canonical-pose transfer, up to 4-view conditioning. No code found (search).
- StdGEN++ (arXiv 2601.07660, 2026-01-12, VERIFIED-AT-SOURCE abstract): semantic-decomposed characters (body/clothes/hair), dual-branch S-LRM; humanoid/anime domain; code/licence not in abstract.
- MV-Adapter (ICCV 2025, VERIFIED-AT-SOURCE via HF/GitHub listing): Apache-2.0; i2mv on SDXL; plug-and-play. Era3D: AGPL-3.0 (VERIFIED via LICENCE file listing) — tool-side only, fine internally but 2024-era. Unique3D: MIT (CLAIMED). Hi3DGen/Stable3DGen (VERIFIED-AT-SOURCE README): MIT, adapted from TRELLIS, kaolin/nvdiffrast/flexicube removed; single-image normal bridging.
- Step1X-3D (VERIFIED-AT-SOURCE README): Apache code+weights, BUT texture baker uses Hunyuan3D 2.0 custom_rasterizer + differentiable_renderer (Tencent = EU-excluded at file level); 27-29 GB VRAM; single-image; multi-view on roadmap only.
- UniRig (VERIFIED-AT-SOURCE LICENSE): MIT, (c) 2025 VAST-AI-Research; SIGGRAPH 2025 auto-rig + skinning.
- Hosted: Meshy pricing page (VERIFIED-AT-SOURCE): Free = CC BY 4.0 (commercial with attribution), Pro $20/mo owns assets, no training without consent, data on AWS US, multi-view supported. Tripo (CLAIMED via Tripo blog snippets; ToS 403 twice): Free = CC BY + no commercial, Pro $19.90/mo full commercial, 2-4 ordered views, ToS updated 2025-07-11. Rodin $20-99/mo (CLAIMED).
- Paid modeller (CLAIMED): one freelancer default "$300, 1 week"; vsquad "$500-40,000"; "$200 game-ready character = simplified, stock, or a rights headache". €150 is below market for a rigged stylised creature.
- Counter to procedural (MEASURED): pufferball fit objective was maximised by a bald body; 9k-line canon look; GLB carries no fur; 39 hand-built parts; anchors disagree about the mouth.
- Counter to reconstructors (MEASURED): TRELLIS.2 single-image invents the back (tail absent; radial extent 49% further from anchor than a sphere); sheet cells contradict (front h/w 0.82 vs back 1.29).

## Position (see StructuredOutput summary)
Target = control-plate-grade geometry (proportion-correct, rigged, silhouette-faithful at the canon yaws), not a perfect textured asset. Escalate to a full "canon-by-decree" asset only for creatures that will be orbited by the camera. Spend nothing now; at most 1 month Meshy Pro (~€18) for a bracketed 4-view-fuse vs TRELLIS.2 comparison AFTER the anchors agree about the mouth.

## Null models for each proposed metric
- Identity through video: per-frame AuraFace cosine to canon; nulls = (a) same seed plain I2V with plates off, (b) cross-character distribution. Four-state ledger (pass/fail/unmeasured/unreachable).
- Shape at canon yaws: silhouette IoU at the two anchor yaws; nulls = equal-volume ellipsoid, TRELLIS.2 single-view, current pufferball ("do nothing").
- Multi-view rigidity: existing mvconsist SfM bracketed by rendered controls.
- Plate steering: rank-of-target (chance 8.5/16) — already MEASURED for depth; repeat for normal/segment/pose plates.
- Pose-track fidelity: 2D reprojection px vs keypoints; null = static fitted pose (anny_fit 4.7 px baseline).
