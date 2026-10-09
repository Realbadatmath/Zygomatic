# Research notes — Blender add-ons / retopo / rig / UV / hair / texture-projection tools (as of 2026-09-02)

Legend: VERIFIED = read at source today; MEASURED = local measurement; CLAIMED = search snippet / secondary source / memory; ASSUMED = my inference.
Raw fetches saved under `mesh_plan/gh/` (exo_eula.txt, bl_4.5/5.0/5.1/5.2.html, humgen_pricing.html, faceit_mocap.html, bk_pricing.html ...).
Superhive product pages return a 5.6 KB Cloudflare challenge to both WebFetch and curl (VERIFIED) — Superhive prices below are CLAIMED unless a vendor site gave them.
FX rate ASSUMED 1 USD = 0.92 EUR; NL VAT 21% assumed added by Superhive/Exoside for an EU buyer.

## 1. Quad Remesher (Exoside) — REJECT on EULA
- Price (VERIFIED https://exoside.com/quadremesher/quadremesher-buy/): Pro single-software perpetual $109.90 excl. VAT (~EUR 101 / ~EUR 122 incl. VAT); Pro all-software $139.90; Indie $59.90 "NOT usable for commercial purpose"; 3-month subs $15.99. Linux supported (VERIFIED main page). Blender version matrix deferred to a FAQ page that 404s at the expected URL (UNVERIFIED).
- EULA (VERIFIED https://www.exoside.com/quadremesherdata/QuadRemesher_EULA.txt):
  - line 32: "You agree not to use ... The Software, or any mesh or data generated or obtained by any process that uses The Software, to train, test, improve or create, directly or indirectly, any machine learning algorithm or artificial intelligence system or model."
  - line 43: "You shall not install, use or run 'The Software' on a computer which does not have a graphical user interface or which is not using a graphical interface while running 'The Software'."
  - line 37: no execution "from another computer than the one on which The Software is installed and activated"; line 61: single computer (+1 laptop/home copy, not concurrent).
  - line 66: Indie barred for entities > $100k revenue or >= 4 staff; Indie is non-commercial anyway.
- Consequence: every mesh it touches becomes tainted for LoRA sheets, depth plates fed to Wan/VACE, or any "test" of an AI model — that IS this pipeline. Headless clause also kills scripted use. Rejected regardless of price.

## 2. Auto-Rig Pro (Artell) — TOP paid
- Price: CLAIMED $40 USD (memory; Superhive page blocked). ~EUR 37 excl. / ~EUR 45 incl. VAT. Perpetual, free updates.
- Blender versions: CLAIMED (search snippet of Superhive listing) 2.93-4.5 listed, with recent changelog entries mentioning Blender 5.2 fixes.
- Licence: Superhive rule VERIFIED (support.superhivemarket.com): code products must be GPL or MIT; "The output of a program is not, in general, covered by the copyright on the code ... so the license of the code does not apply to the output". Standard Royalty Free covers non-code parts: commercial use OK, no resell/redistribute of the product itself. No AI clause found.
- Role: rig anny/MPFB bodies (custom limbs incl. tails/wings/extra legs — CLAIMED), Remap = retarget Mixamo/BVH/any FBX onto our body → per-shot pose tracks (the gap named in FACTS: "NO per-shot pose tracks exist to drive it"); export FBX/glTF for downstream. Quick Rig converts existing rigs.
- Null model for adoption: same Mixamo clip retargeted via free Rigify+"Rokoko/Keemap"-style constraint retarget vs ARP Remap; measure joint-angle RMS vs source and foot-slide; ARP must beat the free path or it is a convenience purchase.

## 3. Faceit (Superhive) — strong/maybe paid
- Price: CLAIMED $99 (search snippet) → ~EUR 91 excl. / ~EUR 110 incl. VAT. Blender 5 build v2.3.71 CLAIMED (pirate-site title, June 2026, weak evidence).
- Mocap paths (VERIFIED https://faceit-doc.readthedocs.io/en/latest/mocap_general/): Apple ARKit apps (Live Link Face, Face Cap, iFacialMocap — iPhone TrueDepth), Hallway Tile ("capture the 52 ARKit expressions with a regular webcam ... runs on Windows, Mac and Linux"), Face Landmark Link ("free and open source application that allows to record ARKit data from video sources and also live from a webcam feed" — MediaPipe-based, CLAIMED), NVIDIA Audio2Face. No native MediaPipe import; the free FLL bridge is the MediaPipe route.
- Role: 52-ARKit shape-key rig on any humanoid head (anny/MPFB topology) + mocap → per-frame face geometry → depth/normal plates. Does NOT build the MediaPipe-468→GNM-68 fit that FACTS lists as missing; GNM head already has 383 expressions.
- ARP + Faceit together ≈ EUR 155 incl. VAT → just over the cap. Buy ARP first.

## 4. Human Generator Ultimate — REJECT for this pipeline
- Price (VERIFIED https://humgen3d.com/pricing): Commercial license "$ 128" "lifetime license for 1 user"; a Personal/Portfolio tier and a higher ($300?) tier exist (page text broke on the regex). "Buy from Superhive".
- EULA lines (VERIFIED pricing page + help.humgen3d.com/license snippet): "We made an exception to our license for YouTube and Vimeo creators, so you don't need a commercial license if the only commercial activity you'll be doing is making public YouTube or Vimeo videos"; "It's not allowed to share or sell the 3D models and/or textures of Human Generator to people who don't have a Human Generator license, even when customized ... This restriction is for both the personal and commercial license". Code GPL-3 (VERIFIED README). AI-training use: not addressed anywhere found.
- Why reject: adults-only base (CLAIMED), competes with the locked anny body (all ages), assets non-transferable so meshes cannot be registered as pipeline assets under the operator's permissive-only asset rule.

## 5. UniRig (VAST) — TOP free
- Code MIT (VERIFIED GitHub API), weights MIT on HF VAST-AI/UniRig (VERIFIED model card); release = skeleton + skinning trained on Articulation-XL2.0. Last push 2026-06-04 (VERIFIED).
- Requirements (VERIFIED README/requirements.txt): Python 3.11, torch >= 2.3.1, `bpy==4.2` pinned (so it needs its own py3.11 venv, NOT the 3.12 system python), > 8 GB VRAM. Handles "humans, animals, objects" (VERIFIED README claim; quality CLAIMED). Known limit: skinning degrades when skeleton misses tail/wing bones.
- Role: rig pufferball + future creatures/props → animate → per-frame depth plates. Null model: hand-placed armature + Blender Automatic Weights; score deformation artefact area at a fixed limb bend.

## 6. Voxel Heat Diffuse Skinning — maybe
- $50 CLAIMED (search), v3.5.3 "for Blender on Windows and Mac" (search snippet) — Linux binary UNVERIFIED (ships compiled engine). Cheap, robust on multi-part/non-manifold meshes (pufferball = 39 parts). UniRig covers the same need for free.

## 7. Rigging — free
- Rigify: bundled, GPL, NOT enabled in 4.3.2 (given). CloudRig 2.2.28 needs Blender 5.0 (given).
- Mixamo (CLAIMED via search; helpx page failed to fetch twice): free with Adobe ID; characters/animations "for unlimited commercial or non commercial use"; no repackaging/resale of raw files; humanoid only; site up as of mid-2026 but described by Adobe support as no longer supported (outage June 2025). Blender path: download FBX Binary "with skin" → bundled io_scene_fbx import → ARP Remap or Rigify retarget. Adobe's Mixamo Blender add-on is archived (2.8x era).

## 8. Retopo — free
- RetopoFlow: GitHub CGCookie/retopoflow, GPL-3 code, latest tag 3.4.10 (2026-01-29), push 2026-08-31, requires Blender >= 3.6 (VERIFIED). "RetopoFlow 4" is not a published release as of today. Interactive-only.
- Instant Meshes: BSD-3-style licence (VERIFIED LICENSE.txt, 2015 Jakob/Panozzo/Tarini/Sorkine), CLI binary, last push 2022 — headless quad-dominant remesh, free.
- Blender QuadriFlow remesh: built-in operator `bpy.ops.object.quadriflow_remesh` (CLAIMED) — headless, free.

## 9. UV / hair
- UVPackmaster 3: Gumroad listing "UVPackmaster PRO for Blender (all versions)"; price not extracted (CLAIMED historically ~$29 Std / ~$69 Pro). GPU (CUDA/Vulkan) variant (VERIFIED site). xatlas (MIT) already in python3.12 + Blender's native packer → marginal.
- Hair Tool 4 (Bartosz Styperek = JoseConseco): "Hair Tool 4 (for Blender 4.2 and above)" (VERIFIED docs title); price not extracted (CLAIMED ~$52). Blender native hair curves + bundled GN hair assets are free and sufficient for silhouette-level fur.

## 10. Texture projection / generation
- Blender native camera projection (UV Project modifier / Texture Paint "Project from View" / Bake): free, GPL, works in 4.3.2 (CLAIMED standard feature). Model-clean route for anchors → mesh texture.
- Stable Projectorz: free, AGPL-3.0 since Jan 2026, v2.4.5, textures "freely use and sell commercially" (VERIFIED site) — Windows only (VERIFIED) → unusable on this Ubuntu box.
- Dream Textures: GPL-3, last release 0.4.1 2024-08-26, no push since (VERIFIED) — stale, SD1.5-era.
- MV-Adapter: Apache-2.0 (VERIFIED), requirements pin `git+https://github.com/NVlabs/nvdiffrast.git` (VERIFIED) — nvdiffrast = NVIDIA non-commercial; only used to render position/normal conditioning + bake, replaceable by our mesh_control.py/Blender bake. Image+Geometry→Multiview SDXL adapter; weights on HF huanngzh/mv-adapter (licence CLAIMED Apache; check). Last push 2025-06-26.
- Paint3D: Apache-2.0 (VERIFIED), no nvdiffrast hit in requirements.txt (VERIFIED grep; kaolin unverified), stale 2024-11. SD1.5 UV inpaint models.
- TEXGen: no licence file (GitHub "None", VERIFIED) + nvdiffrast → reject.
- UniTEX: Apache code (VERIFIED) but README installs nvdiffrast (VERIFIED) and credits FLUX (base model unverified) → blocked pending file-level check.
- SyncMVD: MIT (VERIFIED), torch==2.0.1 pin, xatlas; text-only depth-ControlNet texturing → weak for canon fidelity.
- Hunyuan3D-Paint: EU-excluded (given).

## 11. Asset sources
- Blendkit (formerly BlenderKit) pricing (VERIFIED https://www.blendkit.com/plans/pricing/): Full $9.90/month, Business $29/month per seat; Full limited to "Companies with <= 5 employees and yearly revenue <= $100k"; Free plan exists. Licences (VERIFIED docs): Royalty Free = "commercial use without mentioning the author, but doesn't allow for re-sale of the asset in the same form"; CC0 assets exist. AI/ML use not addressed. Under the operator's asset rule only the CC0 subset qualifies.
- Sketchfab CC0 filter: platform state after Epic's Fab migration UNVERIFIED today; Smithsonian + Poly Haven already cover the need.

## 12. Blender versions
- 4.5 LTS released 2025-07-15 (VERIFIED dev notes); Python 3.11 (CLAIMED, VFX platform 2025). 5.0 released 2025-11-18 (VERIFIED); Python 3.11.13 (CLAIMED search snippet); legacy Action API removed (CLAIMED). 5.1 released 2026-03-17 (VERIFIED); "Libraries have been upgraded to match VFX platform 2026, including: Python 3[.13]" (VERIFIED 5.1 notes + Bonsai issue #7623 body: "Blender 5.1 will use Python 3.13"). 5.2 LTS notes page exists (VERIFIED), release date not extracted.
- Add-on compatibility (VERIFIED at source): MPFB 2.0.17 manifest blender_version_min 4.2.0, no max; CharMorph 0.4.0-3 (2025-03-27) "Fixes for Blender 4.4", bl_info min 3.3, no release since; CAD Sketcher 0.30.0 (2026-08-19) "Require Blender 5.0 minimum", 0.31.0-rc.1 manifest min 5.0.0; Poly Haven add-on main bl_info (4,5,0), v1.2.3 2026-07-20; sverchok 1.4.0 (2026-03-05) release title "Blender_3.6...5.1"; Bonsai has Python 3.13 builds for 5.1 in bonsai_unstable_repo (issue closed 2026-07-24); blosm GitHub releases stale (2021) — patched local build, 5.x risk ASSUMED.
- Verdict: 4.5 LTS is the safe upgrade (same Python 3.11 → venvs and bpy wheels unchanged; MPFB/sverchok/Poly Haven 1.2.3 fine; CharMorph ASSUMED ok; blosm/CAD Sketcher 0.27.8 stay as-is). 5.0/5.1 only justified for CloudRig/Vitruvian/CAD Sketcher >= 0.30 and costs a Python 3.13 rebuild of every compiled add-on plus Action-API script breakage → side-by-side install only.

## 13. Shortlist for the <= EUR 150 purchase
1. Auto-Rig Pro (~EUR 45 incl. VAT, CLAIMED price) — the only paid tool that closes a named gap (per-shot pose tracks via Remap).
2. Faceit (~EUR 110) — only if the face path is proven to need ARKit shape keys; together with ARP just over cap.
3. Voxel Heat Diffuse Skinning (~EUR 56) — only if UniRig skinning fails the null test AND a Linux build is confirmed.
Everything else: free (UniRig, Instant Meshes, QuadriFlow, RetopoFlow GitHub, native projection, MV-Adapter minus nvdiffrast, Mixamo library) or rejected (Quad Remesher EULA, Human Generator, Stable Projectorz Windows-only).
