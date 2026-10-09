# VFX Analyzer — tooling & licence ruling (2026-08-30)

> **VERIFIED CORRECTION TO SECTION 1a, added after the survey.**
> The survey reports "four live non-commercial exposures already on this disk".
> All four were checked against the ACTUAL production pipeline and **none of them
> is live**. The NC material is on disk and unused:
>
> * **OpenPose** — `body_pose_model.pth` (200 MB) is on disk, but nothing invokes it.
>   The only `openpose` hits in the codebase are the `generation_mode` STRING LABEL
>   `'pose_locked_ipa_openpose'` and one human-readable node title,
>   `"OpenPose skeleton map"`, inside `flux_pose_ipa_cell.json`. No pose-preprocessor
>   node class appears in any render workflow.
> * **Depth-Anything-V2-Base** — on disk and still named in
>   `character_style_profiles.json` (`profiles/arcane_animation/restyle`), but
>   `arcane_restyle.py:179-183` REJECTS any `vitb`/`vitl`/`vitg` value and falls back
>   to `vits`, logging the refusal. That guard was written on 2026-08-03 and
>   anticipates exactly this case. The JSON string is inert debris.
> * **Vendored DWPose / open_pose** — the NC-at-file-level import is real, but nothing
>   in the pipeline imports `custom_controlnet_aux` in-process at all; the single
>   codebase reference is a COMMENT in `arcane_multichar.py:40`.
> * **anime_face_segment** — its NC weight (`bdsqlsz/qinglong_controlnet-lllite`
>   `UNet.pth`) was never downloaded.
>
> So there is **no NC exposure to remediate today**. What the survey got right, and
> what matters, is FORWARD-LOOKING: these are traps sitting directly in the path of
> the detectors this analyzer is about to add. Step 1 of the build order is therefore
> a guard against re-introduction, not a cleanup.
>
> One other factual slip: the survey states the analyzer runs under `/usr/bin/python3`.
> It does not — kanban-server runs
> `/home/zygomatic/Zygomatic Full/agents/.venv/bin/python` (verified from the running
> process). That venv has cv2 4.13, mediapipe 0.10.35, scipy, skimage, torch, onnxruntime.

---

## VERIFIED CORRECTIONS TO THE BRIEF — read these first, they change rulings

I checked the disputed environment facts myself rather than trusting either the brief or the surveys.

- **The GPU is 48 GB, not 24 GB.** `nvidia-smi` reports one RTX 4090 with 49140 MiB total. It also reported 46065 MiB *in use* by the render pipeline while I ran this. So the honest VRAM answer is a state machine, not a number: Qwen3-VL-32B-FP8 (33.7 GB) is viable when ComfyUI is offloaded and impossible otherwise, and in the observed state nothing above ~3 GB can start at all.
- **`scikit-image` 0.26.0 IS installed** in `/usr/bin/python3` and in the ComfyUI venv, along with scipy 1.17.1, numpy 2.3.5, cv2 4.13.0, av 17.0.1, onnxruntime 1.25.0 (GPU providers), mediapipe 0.10.35, transformers 5.5.3, torch 2.11.0+cu130. The brief's "NOT installed: sklearn" is scikit-**learn**, a different package. This matters a lot for the deterministic tier — the library you need is already there.
- **`ultralytics` is installed at 8.4.56, but only in `/home/zygomatic/ai-models/comfyui/.venv`** (with timm 1.0.27, transformers 5.9.0, torch 2.12.0+cu130). It is absent from `/usr/bin/python3`. Both the brief and one survey were half-right.
- **`/home/zygomatic/zygomatics-zero/venv` is empty** (Pillow only). Whatever runs the analyzer, it is not that. The working interpreter is `/usr/bin/python3` via `~/.local`.
- `facebook/sam3` and `facebook/sam-3d-body-dinov3` are confirmed 12K metadata stubs. Nothing will load.
- `unimatch` is vendored as **code only** — no weights in `ckpts/`. It needs a 29.5 MB fetch from `hr16/Unimatch`.

---

## 1. LICENCE RULING

### 1a. Four live non-commercial exposures already on this disk

These are not hypotheticals from a survey. I opened the files.

**(i) Depth-Anything-V2-Base is CC-BY-NC-4.0 and it is on disk.** `ckpts/depth-anything/Depth-Anything-V2-Base/depth_anything_v2_vitb.pth`, 390 MB, downloaded 27 Jul. I fetched both model cards: `depth-anything/Depth-Anything-V2-Small` declares **apache-2.0**; `depth-anything/Depth-Anything-V2-Base` declares **cc-by-nc-4.0**. Worse, the ComfyUI node's *default* selection is `depth_anything_v2_vitl.pth` (Large, same NC family), so any first run at defaults pulls another NC checkpoint. **DENY the vitb and vitl checkpoints. Keep vits only.** No survey caught this — the flow/depth survey was cut off before it got there — and it is precisely the case the user's own "root licence lies" rule was written for.

**(ii) The CMU OpenPose weights are on disk.** `ckpts/lllyasviel/Annotators/{body_pose_model.pth, hand_pose_model.pth, facenet.pth}` are the CMU OpenPose models. **DENY.**

**(iii) The vendored DWPose package is NC-tainted at import.** `src/custom_controlnet_aux/dwpose/LICENSE` and `.../open_pose/LICENSE` both open with "OPENPOSE ... ACADEMIC OR NON-PROFIT ORGANIZATION NONCOMMERCIAL RESEARCH USE ONLY" — inside a repo that is Apache-2.0 at root. And `dwpose/__init__.py` imports `.body`, `.hand`, `.face` at module scope (lines 16-18), so `from custom_controlnet_aux.dwpose import ...` pulls NC-covered code into the process unconditionally, even if you only intended to use the Apache ONNX weights. **DENY the vendored wrapper.** The weights themselves are clean: I confirmed `yzd-v/DWPose` declares **apache-2.0**. Use rtmlib or a bare `onnxruntime.InferenceSession` against those `.onnx` files and write ~150 lines of pre/post-processing yourself.

**(iv) `anime_face_segment` will silently download an NC checkpoint on first use.** I read `anime_face_segment/__init__.py`: it calls `custom_hf_download(BDS_MODEL_NAME, "UNet.pth", subfolder="Annotators")`, and `util.py:18` sets `BDS_MODEL_NAME = "bdsqlsz/qinglong_controlnet-lllite"`. I fetched that repo: **cc-by-nc-sa-4.0**. The node is installed, the weight is not yet fetched. **DENY as wired.** The underlying model (siyeong0/Anime-Face-Segmentation) is MIT — re-source `UNet.pth` from the author and hard-pin the path, and this flips to ALLOW. Its second download, `isnetis.ckpt` from `skytnt/anime-seg`, is Apache-2.0 and clean.

**Action:** grep the pipeline for `openpose`, `body_pose_model`, `DWPreprocessor`, `AnimeFaceSegmentor`, `custom_controlnet_aux.dwpose`, and `depth_anything_v2_vitb|vitl`. Any hit is a non-commercial dependency inside a monetised channel today.

### 1b. Clean DENY list (with reasons)

| Item | Reason |
|---|---|
| Depth-Anything-V2 **Base/Large** | cc-by-nc-4.0 (verified on the card). Small is apache-2.0 and fine. |
| CMU OpenPose weights + vendored `dwpose/`, `open_pose/` | CMU academic/non-profit non-commercial. |
| `bdsqlsz/qinglong_controlnet-lllite` UNet.pth | cc-by-nc-sa-4.0 (verified). |
| CoTracker / CoTracker3 | CC-BY-NC 4.0. NC restricts *use*; the internal-tool carve-out does not apply. The best dolly-vs-zoom tool in existence, and it is out. |
| Human-Art dataset + every `*-humanart` checkpoint (ViTPose, RTMPose, YOLOX-l, RTMDet) | CC BY-NC-SA 4.0, gated behind a form that is itself a non-commercial declaration. Do not download "just to evaluate". This is the single biggest accuracy fix available for drawn content (cartoon AP 9.7 → 64.7) and it is forbidden. |
| Sapiens **v1** (`facebook/sapiens-pose-1b` etc.) | cc-by-nc-4.0. **Sapiens 2 under `sapiens2-license` is commercially permitted → ALLOW.** Same org, same family, opposite ruling. Check the tag per checkpoint. |
| MANO-based hand mesh: `mesh_graphormer` (**on disk, no LICENSE file, confirmed MANO imports**), HaMeR, WiLoR | MANO is Max Planck research-licensed; commercial needs a separate agreement. MIT wrapper code cannot grant rights to the model it loads. |
| VideoMAE / VideoMAEv2 / TimeSformer Kinetics checkpoints | cc-by-nc-4.0 on every checkpoint that matters. Note the MIT-code/NC-weights split on OpenGVLab/VideoMAEv2. The apache-tagged mirror hosts *distillations of* the NC giant — not a loophole. |
| Magi / Magiv2 | Research/non-commercial; commercial needs author permission. Also the wrong tool (manga pages, not video frames). |
| **Qwen2.5-VL-3B-Instruct** | `qwen-research`: "for research or evaluation purposes only". Trap: `ollama pull qwen2.5vl:3b` is the obvious VRAM-saving move and would import an NC model. The 7B already installed is apache-2.0. |
| Sakuga-42M | CC-BY-NC-SA, academic-only, paper withdrawn. |
| Manga109-derived models | Academic use only. |
| **NTU RGB+D-trained PoseC3D / ST-GCN checkpoints** | The survey called this UNVERIFIED; I am hardening it to **DENY**. MMAction2 distributes the weights under Apache-2.0, but their entire information content derives from a dataset whose release agreement is explicitly academic non-commercial. Under a policy where NC restricts *use*, that is exactly the case the policy exists to catch — and there is a free clean alternative (train your own head), which you need anyway for the domain gap. Take the architecture, not the weights. |

### 1c. Safe to use as an internal tool despite copyleft

Nothing is distributed, so GPL/AGPL/LGPL/ShareAlike cannot trigger. Explicitly cleared:

- **`ultralytics` (AGPL-3.0)** — needed to load `face_yolov8m.pt` / `hand_yolov8s.pt`. Both weights are apache-2.0 per the Bingsu/adetailer card; the *loader* is AGPL. Do not repeat "apache-2.0" as if it covered both.
- **ADetailer lineage (AGPL-3.0)**, **YOLO-World (GPL-3.0)**, **YOLOE (AGPL-3.0)**, **camie-tagger (GPL-3.0)**, **bizarre-pose-estimator (AGPL-3.0)**.
- **DensePose model-zoo weights (CC BY-SA 3.0)** — ShareAlike is copyleft-flavoured, fine internally; it would bite only if a DensePose visualisation ever shipped as a pixel.
- **ffmpeg** (LGPL or GPL depending on build) — invoked as a subprocess, not even a derivative work.

**One genuine caveat on the copyleft carve-out, specific to this project.** AGPL §13 triggers on *remote network interaction*, not distribution. This project runs several LAN services (:8899 kanban, :8500 transcriber, :8600 legal, :5000/:5300 medusa), and the memory index records closing two unauthenticated LAN proxies. If the analyzer ever gets a tab in the :8899 GUI and third parties reach it over the network, the AGPL components (ultralytics, bizarre-pose) become an offer-the-source obligation. Single-operator localhost is fine. A shared tab is not automatically fine. Keep the AGPL pieces behind a CLI/batch boundary if the analyzer is ever GUI-mounted.

### 1d. Where the surveys were wrong or thin

- **SDPose-OOD is not simply MIT.** The repo says MIT and the survey accepted it, but the model is a fine-tuned **Stable Diffusion v2 U-Net**, and SD2 weights carry CreativeML OpenRAIL++-M. That propagates to a derivative. OpenRAIL++ permits commercial use, so this is not a DENY — but the "MIT" label is wrong at the weight layer and the survey missed exactly the pattern it was told to look for. Treat as **ALLOW with OpenRAIL++ use restrictions attached**, and verify before relying.
- **`groundingdino_swint_ogc.pth`** — repo LICENSE is stock Apache-2.0 (raw file read), but no per-checkpoint licence ships with the weight and it was trained on Objects365/GoldG/Cap4M whose terms are not that grant. **UNVERIFIED at the training-data layer.** Swap to LLMDet (Apache-2.0 weights, cleaner provenance, and +3.3 to +17.0 AP better) and the question disappears. Easy call.
- **OWLv2** — verified by card metadata, not by opening a LICENSE file. Fine, but label it verified-by-card.
- **`lllyasviel/Annotators`** — I confirmed the repo declares `license: other` behind an essentially empty README. That is not a grant. `netG.pth` (lineart_anime) and `erika.pth` (manga_line) are **UNVERIFIED**, notwithstanding that their upstream *code* licences are MIT and readable on disk. And note that this same host already supplied the CMU OpenPose weights now sitting in `ckpts/` — a host that declares no terms and demonstrably re-hosts NC material should not be trusted by default.
- **`LayerNorm/DensePose-TorchScript-with-hint-image`** — the upstream detectron2 zoo terms were verified (CC BY-SA 3.0); the re-upload's own terms were not. UNVERIFIED.
- **GLM-4.6V-Flash** — repo table says Apache-2.0, the sibling GLM-4.5V card says MIT, the 4.6V-Flash card itself was never read. UNVERIFIED. Both are permissive so the ruling would be ALLOW either way, but read the card.
- **`deepghs/booru_yolo`** — no licence key on the HF repo, licence None on GitHub. UNVERIFIED, doubly. Do not use.
- **`lbpcascade_animeface`** — 1,982 stars, universally assumed MIT, and it has **no LICENSE file and no licence statement anywhere**. UNVERIFIED. Irrelevant anyway; hysts beats it outright.
- **`AnimeInterp`** — README claims MIT, repo has no LICENSE file, checkpoints on Dropbox with no terms. UNVERIFIED.
- **deepghs is not one licence.** MIT: `anime_person_detection`, `anime_head_detection`, `anime_face_detection`, `anime_rating`, `anime_classification`, `anime_censor_detection`. **OpenRAIL**: `anime_hand_detection`, `anime_eye_detection`, `anime_halfbody_detection`, `anime_portrait`, `anime_aesthetic`, `ccip`. OpenRAIL is a *behavioural* use restriction, not a commercial one — ALLOW, but the restrictions attach and propagate, so record them per model rather than lumping the org together.
- **`imgutils.pose` is a name trap.** It contains `dwpose.py` and an OpenPose-18 keypoint enum. It is a wrapper around photo-trained DWPose, not an anime-trained pose model, and inherits every DWPose failure.

---

## 2. THE TIERED ANSWER

### deterministic — 1,277 entries (58% of the gap)

Plainly: **no model, no download, no licence question. This is unwritten code, and it is the majority of the work.** Nothing in six surveys reduces it.

But it is not 1,277 programs. It collapses into roughly **40 primitive families**, each parameterised many ways:

- *Per-frame global*: luma histogram, mean/percentile luminance, RMS contrast, saturation, colour cast, dominant palette, clipping fraction, entropy.
- *Per-frame spatial*: Sobel/Canny edge density, gradient-orientation histogram, FFT radial slope (sharpness/grain), local variance maps, blockiness, banding via posterisation residual, ringing.
- *Frame-pair*: abs-diff, SSIM, histogram correlation, bit-identity test.
- *Flow-derived* (needs step 3 below): divergence, curl, magnitude, RANSAC affine/homography fit for global camera motion, residual after global motion.
- *Mask-derived* (needs a matte or SAM): area fraction, centroid, bbox, aspect, compactness, convex-hull ratio, overlap/contact.
- *Temporal operators over any of the above*: onset, peak, slope, plateau, oscillation frequency, monotonicity, variance.

Realistic effort: **~40 primitives at ~3,000–5,000 lines including tests, plus a declarative registry** mapping each taxonomy entry to `primitive + params + threshold + unit + null model + noise floor`. Written that way it is two to four weeks for one person and the 1,277 becomes a data file. Written one bespoke function at a time it is six months and it rots.

Libraries that genuinely shortcut it, all already present:

- **scikit-image 0.26.0** (BSD-3, already installed): SSIM, Canny, GLCM/LBP texture, `regionprops`, phase correlation, blur metrics. Covers dozens of the primitives outright.
- **OpenCV 4.13** (BSD-3, installed), **SciPy 1.17** (`ndimage`, `signal`, FFT).
- **ffmpeg filters** — the biggest single shortcut and nobody mentioned it. `signalstats` gives per-frame YUV min/max/avg/stdev, hue, saturation, plus TOUT/**VREP**/BRNG; VREP is literally a repeated-field detector, i.e. cadence. Add `freezedetect`, `blackdetect`, `blackframe`, `scdet`, `cropdetect`, `psnr`, `ssim`. One `ffprobe -f lavfi` pass over a 10 s clip costs ~1 s and populates a large slice of `frame_metrics` and `editing_time` before any Python runs.
- **PySceneDetect** (BSD-3) for shot boundaries; the model-tier upgrade is TransNetV2 (licence UNVERIFIED — the flow/shot survey was truncated before covering it).

Two traps specific to animation. First, **measure cadence on mezzanine frames, not on a transcoded mp4** — h.264 makes held cels non-identical and destroys the bit-exact signal that makes on-2s/on-3s trivially detectable. Second, and this is the project's own hard-won rule at scale: **every one of these 1,277 metrics needs a null model and a noise floor**, or you will ship 1,277 confident numbers, an unknown fraction of which measure the encoder. The GNM head incident (an L2 prior froze identity at 4%; all four "fits" were the mean head) is exactly this failure at n=1.

### landmark — 514 entries

**Replace MediaPipe's *detector*, not its landmarker, and crop first.** The measured evidence converges from three independent directions: MediaPipe found zero faces whole-frame at conf 0.01 and resolved instantly from a head crop; Human-Art measures YOLOX 61.9 AP (photo) → 10.8 AP (cartoon) and Faster R-CNN 52.2 → 8.8; and the CoMix comics benchmark puts zero-shot Grounding DINO at 48.7 mAP vs 78.6 finetuned. The first stage is the dominant failure.

Stage 1, detection — three options, one of which is free:
- **Already on disk**: `face_yolov8m.pt` and `hand_yolov8s.pt`. The finding nobody in this project seems to have registered is that these were **trained on anime data** (Anime Face CreateML for faces, AnHDet for hands, per the Bingsu/adetailer card), not COCO-only. They are labelled "2D / realistic". Zero download.
- **deepghs MIT ONNX detectors** (~90 MB): `anime_head_detection` F1 0.93 including non-frontal and back-of-head, `anime_person_detection` F1 0.85–0.87, `anime_face_detection`. Runs on the installed onnxruntime-gpu with no new packages.
- Keep the COCO detectors too and **take the union** — the 3D/CG half of the material is close enough to photographic that they work there.

Stage 2, landmarks:
- **Face: hysts/anime-face-detector v0.1.0** — 28 anime facial landmarks, **MIT verified at code *and* per-checkpoint level** (both model cards read individually, which is the strongest verification in the entire survey set). It dropped its OpenMMLab runtime in July 2026, so it installs against the exact stack already present. Frontal-only; pair with deepghs head boxes for profile and rear.
- **Body/hands: RTMW-133 / DWPose ONNX via rtmlib** (Apache-2.0 both), 133 keypoints. **Measured on this project's own content**: 17/17 body keypoints on both characters in a CG clip (mean conf 0.790), 13/17 on a painted 2D clip (0.566), against 7/17 on a live-action control. That is the most encouraging number in six surveys.
- **Anime-native body pose: bizarre-pose-estimator** (AGPL, internal-OK). Two surveys searched independently for anything newer with downloadable weights and found nothing. The field's answer is still one WACV 2022 paper with weights behind a Google Drive link and old torch pins.

**A caution the surveys did not land.** "2D anime" in this project largely means *diffusion-painted renders*, not broadcast cel animation. A painted Arcane-style render retains soft shading, texture gradients and near-photographic structure that a Toei frame strips out entirely. DWPose scoring 13/17 on your own painted render is not evidence it will work on a third-party anime episode frame from the remix workflow. Measure both, separately.

Ceiling: coarse configuration works (limbs up/down, stance, facing, two-character proximity, hand present/absent). Fine articulation does not (individual fingers, wrist rotation, foot orientation). Chibi proportions, four-fingered hands and smear frames break everything. Run two estimators and use **keypoint disagreement as a per-frame "too stylised to trust" gate** — the failure mode here is a confident wrong skeleton, not a low score.

### vlm — 232 entries

**Qwen3-VL-8B-Instruct-FP8. Already on disk, Apache-2.0, 10.2 GB measured.** No download decision to make.

**The highest-value change in this entire report is ~20 lines of code, not a model.** I confirmed it on disk: `/home/zygomatic/models/vlm_judge/vlm_worker.py:445` builds `content = [{'type': 'image', 'image': im} for im in images]` and line 462 reads `inputs['image_grid_thw']`, while line 529 prepends the text "…render, in temporal order." That prefix is a promise the tensor layout does not keep — no temporal patching, no temporal mRoPE, and roughly 2× the visual tokens per frame. Switching to `{'type': 'video', ...}` engages `temporal_patch_size=2` and the interleaved mRoPE temporal section the config already declares. Every dependency is present in that venv (transformers 5.14.1, av 18.0.0, qwen-vl-utils) and `chat_template.json` has a video branch.

**Run it two ways, and the split is arithmetic, not preference.**
- **Crop pass** for anything local. The crop rule is a *token-density law*: a 100px hand in an 832×480 frame gets ~4×6 ≈ 24 merged tokens after 16px patching and 2×2 merge. The 32B sees the same 24 tokens. Scale buys reasoning over the tokens it gets, not more tokens. Video input makes this strictly worse per frame, because temporal compression exists precisely to spend fewer tokens per frame.
- **Clip pass** for temporal, large-scale questions: was there a cut, did the camera dolly or zoom, did the character cross frame, what is the shot about.
- **A clip-level question about a 100px detail should be refused by construction** and recorded as `unmeasurable`, never `not_found`. That distinction is the whole quality of the tool.

Frame budget, computed from the on-disk `video_preprocessor_config.json`: 12,288 visual tokens = **63 frames at 832×480, 125 at 448², 222 at 336², 384 at 256²**. A 10 s clip at 24 fps does not fit at native resolution. Downscale to ~336px, or raise `processor.video_processor.size`.

**Cost per 10 s scan**: behind the persistent `--serve` pool (already built, measured 4.0× faster, 64 s → 16 s), budget **~30–70 s for a batched 10-question checklist over one clip**, plus 0.8–9 s per crop question. Do not put it in a per-frame loop — 240 frames × 1 s is four minutes for a single question.

Carry over both doctrines already paid for: **reject-only and additive** (a VLM may never override a pixel-gate fail; false PASSES are its systematic failure), and **phrase every question positively** (4/4 configs answered negatively-phrased questions wrong while their own stated reasoning contradicted their answer). Pre-warm FP8 `kernels` before any offline run. Inherit the existing `reason: comfy_sampling` self-refusal guard. Do not use moondream (blind to ink 0/7; cannot be asked about text — RapidOCR replaced it at 1.00/1.00 on 48 frames).

### model — 63 entries

Mostly these should be **trained, not downloaded**, and the training data is free.

- **Frozen DINOv2-base (Apache, already cached, ~5 ms/frame) + a logistic head on 200–500 own-labelled frames per observable.** Minutes of training. You own the head, the trunk is Apache, the domain gap closes because the labels are your content. This is the only route that solves the licence problem and the domain problem simultaneously.
- **Skeleton-action (ST-GCN, ~200 lines of plain PyTorch) trained on your own scene scripts.** Every clip is generated from a script that already names the action, characters and beat — that is free ground truth at scale on footage you own outright. Do not use the NTU-trained checkpoints.
- Downloads that *are* worth it here: **WD Tagger v3** (Apache, 378–467 MB ONNX, ~20 ms/frame), **deepghs MIT detectors** (~90 MB), **skytnt/anime-seg isnetis** (176 MB Apache ONNX), **hysts anime-face-detector** (285 MB MIT), **LLMDet** weights into the existing transformers path.
- **MM-Grounding-DINO** (Apache) is the sanctioned finetuning path if you ever want a grounding model that works on your frames — CoMix says finetuning is worth roughly +30 mAP on drawn content.
- **SAM 3** only as a measured experiment: gated, custom-but-commercially-permitted licence, 3.44 GB, and the code side already works (`Sam3Model` imports clean under transformers 5.9.0). Its text-grounding half on drawn frames is genuinely unbenchmarked by anyone.

### unsupported — 38 entries

What stays out of reach, and why:

- **Sub-pixel dense point tracking.** CoTracker is the tool and it is NC. GMFlow + LK + SAM2 centroids give you dolly-vs-zoom via radial divergence but not per-point trajectories through occlusion.
- **3D hand mesh / finger articulation on drawn hands.** MANO is licence-blocked *and* semantically wrong: fitting a statistical model of real adult human hands to a four-fingered mitten produces a confident, real-looking, wrong hand. It fails silently, which is worse than failing loudly.
- **Metric depth on 2D cel.** DAv2 inverts shading gradient, texture density, atmospheric falloff and defocus; cel shading removes all four. Relative layer ordering is obtainable; metric depth is not; and per-frame depth flickers in global scale, so frame-to-frame depth deltas measure the model's scale jitter, not the camera.
- **Optical flow inside large flat cel fills.** AnimeRun: flat-region error ~1.5× line-region, and networks "regress to zero" on large flat backgrounds. No method escapes the aperture problem.
- **Craft intent.** Smear frame vs mistake; on-3s as style vs dropped frame; deliberately off-model vs broken. You can measure cadence; you cannot measure intent.
- **VLM counting above ~5.** Known failure mode, unfixed.
- Anything needing labelled anime ground truth — see the ceiling.

---

## 3. THE ANIME ANSWER

The honest synthesis is a three-way split, and "the VLM is the fallback" is wrong in both directions.

**Pixel arithmetic is style-invariant or style-*favoured*.** The largest slice of the gap does not care what the content is, and several observables are *easier* on animation than on film: a held cel is bit-identical, cel edges are cleaner and more closed than photographic edges, and there is no sensor noise floor to fight. Cadence, held-cel detection, line boil, shot boundaries and screen-area fraction are all frame-difference statistics, and they are more reliable here than on live action.

**Class-agnostic geometry survives.** SAM 2.1 keys on closed contours and has no COCO prior to be wrong about. ByteTrack and OC-SORT are Kalman filters and Hungarian matching with no learned appearance model at all — as valid on a drawing as on a photograph. And GMFlow is *measured better than RAFT on AnimeRun* (3.35 vs 4.19 EPE; flat regions 3.85 vs 4.80; large motion 30.14 vs 44.54), which means the photo-SOTA leaderboard is actively inverted on this content and "use the newest RAFT variant" is the wrong instinct.

**Anything with a learned photographic prior collapses by roughly 5×, not "somewhat".** Four independent benchmarks agree: Human-Art (HRNet 75.6 → 9.7, ViTPose 79.8 → 16.3, Faster R-CNN 52.2 → 8.8, YOLOX 61.9 → 10.8), Ani-GIFs (I3D 21.12% → 1.95% top-1, i.e. chance), CoMix (Grounding DINO 48.7 vs 78.6 finetuned), and this project's own MediaPipe result. A 16-AP skeleton is not a degraded measurement; it is noise wearing a plausible shape.

The VLM escapes that collapse, and the mechanism matters: **anime is not out-of-distribution for a web-scale corpus.** It is one of the most heavily represented visual genres on the internet, complete with text describing it. So yes — **for semantics on drawn content the VLM is the primary tier, not the fallback**, because it is the only model class that does not degrade. But it is semantic, not metric: it will say "she is holding a sword in her right hand" and will not give you a joint angle, a sub-pixel motion vector, or a reliable count. And it is *blind to the craft vocabulary* — smear frames, impact frames, held cels, speed lines, limited-animation cadence, cel-shading banding — because web alt-text never labels a frame as "this is a smear frame". Those stay deterministic forever, and that is fine, because deterministic is where they belong.

**Genuinely good anime-native tools, named.** **WD Tagger v3** (Apache-2.0, 10,861 danbooru classes = 8,106 general + 2,751 character + 4 rating, ~20 ms/frame) is the only model in six surveys whose training distribution *is* drawn content — it inverts the domain gap instead of fighting it, and it covers held objects (`holding_sword`, `holding_cup`), relations (`hug`, `holding_hands`, `back-to-back`), framing (`from_above`, `dutch_angle`, `pov`), and lighting (`backlighting`, `rim_light`, `silhouette`). What it does **not** do: localise anything, count instances, recognise this project's own original cast (its character classes are booru characters), or work on 3D/CG that does not read as anime. Its F1 is 0.4541 at the P=R threshold — treat it as ranked evidence that gates an expensive check, never as a measurement. Alongside it: **hysts anime-face-detector** (28 drawn-face landmarks, MIT), **deepghs anime_head_detection** (MIT, F1 0.93, non-frontal), **skytnt isnet-anime** (Apache character matte), and the **anime-trained YOLOs already on disk**.

Finally, be honest about *why* the anime tooling is shaped this way: **the field got generation tooling, not analysis tooling.** Every strong anime model here exists because Stable Diffusion needed it — taggers to caption training sets, segmenters to make ControlNet hints, line extractors to condition img2img. Nothing was built to *measure* an anime frame. That provenance is also why the licence hygiene is so bad, and this machine holds four separate proofs of it.

---

## 4. BUILD ORDER

**Step 1 — Quarantine the non-commercial exposure. Half a day, zero download, zero VRAM, unlocks nothing.**
It is first because it is a live monetised exposure, not because it is valuable. Delete or hard-gate `depth_anything_v2_vitb.pth` (keep vits); delete or gate `ckpts/lllyasviel/Annotators/{body_pose_model,hand_pose_model,facenet}.pth`; forbid `custom_controlnet_aux.dwpose` imports; hard-pin or disable `AnimeFaceSegmentor` so it can never reach `bdsqlsz`. Grep the pipeline for all five. *What goes wrong:* a ComfyUI workflow you forgot about re-downloads one of them at defaults — so gate at the loader, not by deleting files.

**Step 2 — Build the deterministic primitive library. Two to four weeks, ~30 MB of nothing (scikit-image is already installed), 0 GB VRAM, ~1–3 s added per 10 s clip.**
~40 primitives + a declarative registry with a null model and noise floor per entry. Front it with one `ffprobe -f lavfi ... signalstats` pass. *Unlocks (estimate):* 400–500 entries immediately from per-frame and frame-pair statistics; 700–900 once step 3 supplies a flow field. This is the biggest slice of the gap and no download touches it. *What goes wrong:* 1,277 confident numbers with no noise floor; and cadence measured on a transcoded mp4 instead of mezzanine frames.

**Step 3 — Wire in the vendored unimatch/GMFlow and retire Farneback. One hour of wiring, 29.5 MB download, ~1–2 GB VRAM, ~10–25 s per 10 s clip at 512px.**
The code is already vendored; only the `hr16/Unimatch` weights are missing. MIT at both code and weight level. *Unlocks (estimate):* 150–250 entries across `camera` (129), `object_dynamics` (140) and `frame_metrics` (140) that currently read "static" because Farneback returns a **confident zero** on flat cel fills — rank-deficient normal equations on a uniform patch, with no residual to distinguish "no motion" from "cannot know". *What goes wrong:* GMFlow still degrades on flat fills, it just fails less catastrophically. Emit a confidence mask and mark flat-region flow `unmeasurable` rather than 0.

**Step 4 — Fix the VLM video path and enforce the two-pass rule. ~20 lines, zero download, 10.2–13 GB VRAM, ~30–70 s per 10 s clip for a batched checklist.**
Switch `_prepare_inputs` to `{'type':'video'}`; set the video processor to ~336px so 222 frames fit the 12,288-token budget; add the by-construction refusal for local-detail questions asked at clip level. *Unlocks (estimate):* of the 232 vlm-tier entries, 120–180 become answerable at usable confidence, weighted to `interaction_social` (203 domain), `scene_semantics` (144) and hand-object identity. *What goes wrong:* it answers fluently and wrongly. Keep reject-only/additive, phrase positively, pre-warm FP8 kernels, inherit the render-busy refusal guard.

**Step 5 — Add the anime-native crop-supplier and tagger layer. One afternoon, ~1.0 GB download, <2 GB VRAM each loaded sequentially, ~3–8 s per 10 s clip on keyframes.**
WD Tagger v3 ONNX (Apache) + deepghs anime_head/person/face MIT + skytnt isnet-anime (Apache) + hysts anime-face-detector (MIT). All run on the already-installed onnxruntime-gpu; hysts needs only torch/hf-hub/cv2, all present. *Unlocks (estimate):* 200–350 entries directly, plus it is the crop gate in front of ~500 landmark-tier entries and the character matte that separates camera motion from subject motion for step 3. *What goes wrong:* WD Tagger F1 0.4541 is evidence not measurement; hysts is frontal-only; the deepghs hand detector is OpenRAIL (record it separately); none of these are validated on 3D/CG — run both detector families and take the union.

**Step 6 — Text-to-box plus persistent IDs, on crops. One day, ~1–2 GB download, ~2 GB (LLMDet Swin-T) + ~3.5 GB (SAM 2.1, already on disk) sequential, ~2 s detection + ~7 s propagation per tracked object per 10 s clip.**
LLMDet weights into the existing HF transformers path (not the IDEA-Research repo, which needs a custom CUDA op compiled against your torch), SAM 2.1 propagation, OC-SORT vendored from MIT source (~200 lines — do not install ultralytics for a Kalman filter). Detect on keyframes every 6–10 frames or on shot boundaries, propagate, associate. *Unlocks (estimate):* 200–300 entries across `hand_object` (133), `object_dynamics` (140), `interaction_social` (203), `editing_time` (131). *What goes wrong:* CoMix says zero-shot grounding on drawn content is ~60% of achievable. Confidence is calibrated for photographs and is simply wrong on your frames — re-threshold empirically against your own labelled frames, expect false positives, and never trust the 0.35 default.

**The already-vendored controlnet_aux preprocessors worth wiring in immediately:** `unimatch` (step 3, the single best one), `depth_anything_v2` **restricted to vits only**, `densepose` (Apache code, CC BY-SA weights, useful on the CG half as a body-region mask, near-useless on 2D). Worth wiring **after** re-sourcing weights: `anime_face_segment` (7-class anime face parse, ~5 ms/frame, one of the best value-per-megabyte items here once `UNet.pth` comes from siyeong0 instead of bdsqlsz), `lineart_anime` (line-boil measurement, but its checkpoint licence is UNVERIFIED). **Never wire in:** `dwpose`, `open_pose`, `mesh_graphormer`.

---

## 5. THE CEILING

**What none of this solves.** Fine articulation on drawn bodies — individual fingers, wrist rotation, foot orientation — is not reachable with clean licences and without your own labels, and it never will be from an off-the-shelf model. Sub-pixel dense point tracking is gone with CoTracker. Metric depth on 2D cel is not a licensing problem, it is a physics one: the cues the model inverts are the cues cel shading deliberately removes. Optical flow inside a large flat fill degrades for every method. Craft intent is unmeasurable by construction. And the 38 unsupported entries stay unsupported.

**The calibration problem is permanent and is bigger than any single model.** Every photo-trained confidence score on this content is miscalibrated, and it is miscalibrated *differently* for 2D painted renders, for third-party cel animation, and for 3D/CG. Any single accuracy number quoted for "animation" is an average over regimes that behave nothing alike. You will re-threshold per content type, by hand, against your own labelled frames, and you will redo it when the render stack changes. Plan for that as a standing cost, not a one-off.

**The four-state ledger is the load-bearing part of the whole design.** With 2,124 undetected entries and a tier full of models that fail *silently*, the difference between `not_found` and `unmeasurable` is the entire quality of the tool. A detector that cannot see is not a detector that saw nothing. Every model in this report needs a "did I have the resolution, the crop, the contrast and the frame count to answer this at all" gate ahead of its answer, and a confident wrong skeleton or a confident zero flow vector must be capable of reporting itself as unmeasurable.

**Is finetuning on anime realistic? Yes — but only on your own data, because no licence-clean labelled anime dataset exists.** Human-Art is CC-BY-NC-SA behind a non-commercial declaration form. Sakuga-42M is CC-BY-NC-SA, academic-only, and its paper was withdrawn under takedown pressure. Manga109 is academic-only. ATD-12K is a research dataset. CoMix's comic sets are academic. Danbooru dumps are scraped copyrighted illustration with no licence at all — WD Tagger being Apache as a *model* does not make its training images usable. That is the entire field. There is no clean labelled anime dataset for pose, action, or detection, anywhere.

**What minting your own actually requires.** You are unusually well positioned for it, because this project is a *generator*, not a consumer: every clip comes from a scene script that names the action, the characters and the beat; every character has a `params.json`; every render has a seed and a prompt. That is free ground truth on footage you own outright. Concretely: a **linear probe on frozen DINOv2** needs 200–500 labelled frames per observable and trains in minutes — that is realistic this month, and it is the honest route to the 63 model-tier entries. An **ST-GCN skeleton-action head** needs a few thousand auto-labelled clips and is realistic this quarter. A **MM-Grounding-DINO finetune** is worth roughly +30 mAP on drawn content per CoMix, and costs a labelled detection set of thousands of boxes — that is weeks of human labelling, not an afternoon, and I would not start there.

Two disciplines are non-negotiable if you train anything. **Hold out by shot, not by frame** — a head trained on 300 frames drawn from 5 shots learns the shots. And **build a null model for every head before you believe a single fit number**, because a probe with no null will do exactly what the L2 prior did to the GNM head: return four confident fits that are all the mean.

**One last adjudication on the taxonomy itself.** The 1277/514/232/63/38 split is probably wrong by a few hundred entries in both directions, and it will move once the primitives exist. Several things filed as `vlm` or `model` — cadence, held-cel detection, line boil, shot boundaries, character screen-area fraction — are deterministic the moment a mask or a flow field is available. Several filed as `deterministic` will turn out to need a mask they do not have. Treat the tier assignment as a hypothesis the build tests, not as a specification, and re-tier as you go.