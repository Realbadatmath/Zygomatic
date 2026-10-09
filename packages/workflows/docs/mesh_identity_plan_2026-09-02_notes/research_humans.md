# research_humans.md — parametric humans / heads / hands / image->parametric fitting, EU-commercial, as of 2026-09-02
Evidence tags: MEASURED (ran it here) / VERIFIED-AT-SOURCE (read the licence/README page today) / CLAIMED (secondary source or search-engine summary) / ASSUMED (my inference).
FX used for EUR: 1 USD = 0.92 EUR (ASSUMED).
No local measurement was run this pass (tool budget); everything on-disk is taken from FACTS.md.

## 1. GNM Body (Google) — NOT RELEASED
- VERIFIED-AT-SOURCE https://github.com/google/GNM (read 2026-09-02): only GNM Head is released; "Our roadmap includes releasing a comprehensive suite of statistical models"; no date; latest event "[2026-07-28]: Official technical report for the GNM Head released!". Licence Apache-2.0.
- VERIFIED-AT-SOURCE https://arxiv.org/html/2607.23687: model "encompasses the head, face, neck, eyeballs, teeth, and tongue"; no body/hands. Fitting = "run a dense landmark detector to predict approximately 600 landmarks on the face" then optimise. The fitter and the dense detector are NOT in the repo (README lists no fitter).
- Consequence: the MediaPipe-478 -> GNM landmark fit stays ours to build; the paper's recipe (dense landmarks + optimisation) is the template. Null model for any fit claim: the MEAN GNM head (FACTS: identity gain was only +0.95..+2.09 mm over mean).

## 2. ICT FaceKit (USC ICT) — MIT, no fitter
- VERIFIED-AT-SOURCE raw LICENSE: plain MIT, "(c) 2020 USC Institute for Creative Technologies", no NC clause.
- VERIFIED-AT-SOURCE README: "ICT-FaceKit is released under the MIT license." + "The full model will be released under a different USC specific license." (the FULL model with 200+ id + albedo modes is NOT the MIT one — do not download anything labelled 'full').
- Topology: 26,719 verts / 26,384 faces, triangles, 17 parts (face 9,409 v, eyes 1,570 v each, teeth 4,412 v, gums/tongue 2,977 v; lacrimal, lashes, occlusion meshes). 100 PCA identity modes (light) + 53 expression blendshapes "following Apple ARKit naming convention". Python samples (numpy + openmesh). A Blender script exists at Blender/Scripts/ICTFaceKit.py.
- No landmark or image fitter shipped (VERIFIED absent).
- Fit: ARKit-53 naming matches MediaPipe Face Landmarker's 52 blendshape scores (CLAIMED — MediaPipe task outputs ARKit-style names) -> per-frame expression drive with NO fitter, for goal A face plates. Identity fit = same job as GNM-68 (our optimiser). Test before adopting over GNM: fit both to the same anny heads; null = mean head; report RMS gain over mean.

## 3. Face models + fitters
- FLAME 2023 Open: CC-BY 4.0. VERIFIED-AT-SOURCE https://flame.is.tue.mpg.de/modellicense.html: "grants you the right to share and adapt the model for any purpose, including commercial use" ; attribution required. FLAME 2017/2019/2020 + Blender add-on: NC ("Any use for commercial ... purposes is prohibited"). No territory clause.
- MICA: custom MPI licence, non-commercial (CLAIMED via repo LICENSE summary, https://github.com/Zielon/MICA/blob/master/LICENSE). REJECT.
- EMOCA / INFERNO: "non-commercial scientific research, non-commercial education, or non-commercial artistic projects" (VERIFIED-AT-SOURCE via https://emoca.is.tue.mpg.de/license.html summary). REJECT.
- SMIRK (georgeretsi/smirk): code MIT (CLAIMED from LICENSE listing) but checkpoints regress FLAME-2020 parameters and were initialised from MICA (CLAIMED) -> derivative of NC assets. REJECT unless retrained on FLAME 2023 (nobody has published that).
- Deep3DFaceRecon (sicxu / microsoft): uses BFM09; BFM requires an application to Univ. Basel and commercial use needs a separate licence (VERIFIED-AT-SOURCE README says "Due to the license agreement of Basel Face Model, you have to download the BFM09 model after submitting an application"; commercial term CLAIMED). REJECT.
- SPARK (KelianB): FLAME-based, licence not read. REJECT (unverified, FLAME-2020 lineage).
- New permissive head models 2025-26 from Meta/NVIDIA/Google other than GNM Head: NONE found in 3 searches (ASSUMED negative).

## 4. MHR / Momentum (Meta) — Apache
- VERIFIED-AT-SOURCE MHR README: "MHR is licensed under the Apache Software License 2.0"; install `pip install mhr` + `mhr-download-assets` (or pixi); TorchScript model `assets/mhr_model.pt`. 45 shape params ("the last 5 for hands"), 204 pose params, 72 expression, 7 LODs. No fitter: "If you want to do Human Motion Recovery with MHR, head to Sam3D (sam-3d-body)". No MediaPipe mention. Ships "Conversion between MHR and SMPL/SMPL-X" only — no Anny mention. No child/all-age mention.
- pymomentum: `pip install pymomentum-cpu` / `pip install pymomentum-gpu` (CLAIMED from https://facebookresearch.github.io/momentum/pymomentum/user_guide/getting_started/ summary). MHR README caveat (CLAIMED): "pip installation is experimental, as some dependencies (e.g., pymomentum) may not resolve correctly on all platforms."
- Anny<->MHR: Anny v0.5 (2026-06-03) added "soma" rig + topology; v0.6 (2026-08-06) "improved SOMA compatibility" (VERIFIED-AT-SOURCE Anny README changelog). So the ONLY registration remains SOMA-X (on disk). Nothing new.
- On-disk state (FACTS): `mhr`/`pymomentum` NOT installed in any venv; SAM 3D Body venv is torch 2.13+cu126 py3.11 — pip mhr into THAT venv is the natural home (ASSUMED compatible; must measure).

## 5. Anny 2026 (NAVER)
- Changelog VERIFIED-AT-SOURCE https://github.com/naver/anny README: v0.1 2025-11-05; v0.2 2025-11-21 topologies; v0.3 2026-02-04 "smplx" topology (NC) + nipple shapes off by default; v0.5 2026-06-03 refactor (anny.Anny) + "soma" rig/topology + SMPLX wrapper; v0.6 2026-08-06 new "anny" rig, facial actions, SOMA compat, torch.compile. GitHub Releases page is empty (versions live in README/tags).
- Licence verbatim: code "Copyright (c) 2025 NAVER Corp., is licensed under the Apache License, Version 2.0"; MakeHuman assets CC0; SOMA-X topology Apache-2.0; SMPL-X topology "non-commercial use only".
- Hands: NO hand / phalanx / finger fix in any changelog line (VERIFIED absent). The 25-35 % short proximal phalanx (FACTS) is still ours.
- Image fitter: https://github.com/naver/anny-fit (CVPR 2026 Findings; code 2026-05-05). LICENSE.txt VERIFIED-AT-SOURCE = NAVER "Non-Commercial License": "The Materials are used solely for non-commercial purposes ('Purpose'). You may not use the Materials or derivatives thereof for any commercial purpose." NOTICE.txt lists submodules CameraHMR (MPI licence), Multi-HMR (NAVER NC), UniDepthv2 (CC BY-NC 4.0). -> BANNED: fitted meshes are 'derivatives' and go into monetised video. NAME COLLISION: local `geom/anny_fit.py` is the in-house MediaPipe/RTMPose fitter and is unrelated — keep it that way.
- Action: measure installed anny version (`/usr/bin/python3.12 -m pip show anny`); v0.6's new rig + facial actions may change joint chains that mesh_skeletons.py / the anthro gates assume (ASSUMED risk; four-state ledger before upgrade).

## 6. Multi-view / single-image HUMAN reconstructors
- PSHuman: "based on SMPLX" (VERIFIED project page). REJECT.
- IDOL: MIT code (CLAIMED) but SMPL-X anchors + HuGe100K "well-aligned SMPL-X" (VERIFIED). REJECT.
- LHM / LHM++ (aigc3d): SMPL-X template anchors (VERIFIED paper); licence not read. REJECT.
- PuzzleAvatar: "non-commercial scientific research purposes" (VERIFIED README). REJECT.
- SiTH: SMPL-X (CLAIMED). REJECT.
- Pippo (Meta, CVPR 2025): NO body model (multi-view DiT from one photo) but LICENSE = CC-BY-NC 4.0 (VERIFIED-AT-SOURCE raw LICENSE). REJECT.
- HumanRAM, MVP4D, Human3Diffusion, MVHuman, MoGA: NOT verified (budget). Every 2024-26 entrant actually checked is SMPL-X-conditioned or NC. ASSUMED: no permissive non-SMPL multi-view human reconstructor exists as of 2026-09. Also structurally moot for goal B per FACTS (canon = 2 anchors + LoRA; reconstructors invent the unseen half).

## 7. Commercial <= 150 EUR
### KeenTools FaceBuilder for Blender — VERIFIED-AT-SOURCE https://keentools.io/products/facebuilder-for-blender (2026)
- Prices USD: Freelancer monthly $19.99 (~EUR 18.4); Freelancer annual $15.99/mo billed $191.88/yr (~EUR 177, OVER budget); Studio $699/yr. NO perpetual. 15-day free trial "with no restrictions or limitations". The 2020 "$149/yr personal" figure is obsolete (CLAIMED old CG Channel article).
- Terms: "All results of your work with our products belong to you" incl. commercial sale; head mesh export "in any 3D supporting format"; after cancellation "You will be able to open your projects and export your work results, but you will not be able to make any adjustments". Buy page EULA checkbox: Freelancer = an individual buying with own money, not a company (VERIFIED https://keentools.io/buy). keentools.io/eula returned 404 — full EULA text NOT read; no AI-use clause seen anywhere (ASSUMED none).
- Features: 51 ARKit-compatible FACS blendshapes; multi-view texture projection; high/mid/low topology; Linux 64-bit supported; Blender 2.80+ (latest named 4.2; 4.3.2 ASSUMED fine — check in trial).
- Fit: goal B head of a canonised character from its anchor photos (front+side+cells) — landmark-based, so it fits SDXL/FLUX renders as readily as photos (ASSUMED); output = proprietary-topology mesh we own outright (identity as a mesh, not a coefficient vector). Goal A: ARKit-51 blendshapes -> MediaPipe blendshape drive -> per-frame face depth/normal plates. Unknown: child-head coverage (ASSUMED adult-derived base).
- Null model: the mean FaceBuilder head rendered to plates vs the fitted head; measure AuraFace distance to canon of plate-steered klein/Qwen renders. The 15-day trial answers this at EUR 0 before any spend.
### Human Generator 3D (Ultimate) — VERIFIED-AT-SOURCE https://humgen3d.com/pricing
- Personal/Portfolio $68 (~EUR 63), Commercial $128 (~EUR 118), lifetime. "We made an exception to our license for YouTube and Vimeo creators, so you don't need a commercial license if the only commercial activity you'll be doing is making public YouTube or Vimeo videos." Commercial renders/animations allowed both tiers; no redistribution of models/textures; embedding in software allowed unless extraction is a feature. Code GPL-3 (VERIFIED github README), assets "royalty free". AI/ML training clause: NOT FOUND (superhive page 403; search empty) — UNRESOLVED. Blender 4.3 compat: unverified. Adults only (CLAIMED).
- Fit: weak. Not a fitter; not all-age; MPFB already gives CC0 all-age bodies. Value would be skin/hair/clothing realism for plates — marginal because "the depth map does the steering" (FACTS).
### Daz Genesis 9 — VERIFIED-AT-SOURCE https://www.daz3d.com/eula
- Free base. Renders: may "publish, market, distribute, transfer, sell or sublicense [their] two-dimensional animations, renderings". AI clause: licence "expressly excludes the use, incorporation, or input of any Content, in whole or in part, in connection with i) any AI engine, program, or system ... with capabilities or instructions to auto-generate materials that are derivative, imitative, or otherwise plagiaristic of the Content." Our pipeline feeds mesh-derived plates into diffusion models and trains LoRAs on renders -> live exposure. REJECT.
### Reallusion Character Creator 5 — CLAIMED (CG Channel 2025-08, Reallusion 2026-01)
- $299 perpetual or $29/month. Over budget perpetual; subscription would lapse. REJECT.
### MakeHuman / MPFB — already installed (FACTS); no fitter; nothing to buy.

## Bottom line for the orchestrator
- Nothing on the market fills the BODY fitter gap permissively; anny-fit is NC, everything else is SMPL-X. The in-house MediaPipe/RTMPose -> Anny fit stays the body path; SAM 3D Body -> MHR (pip) -> SOMA-X -> Anny is the pose-seed path.
- The head is where a EUR-0..150 decision exists: (a) free — ICT FaceKit MIT as an ARKit-driven expression space next to GNM; (b) paid — KeenTools FaceBuilder monthly after a 15-day trial, only if the trial's null-model test shows identity gain on plate-steered renders. Do not buy annual (over budget) and do not buy Human Generator/Daz/CC5.
