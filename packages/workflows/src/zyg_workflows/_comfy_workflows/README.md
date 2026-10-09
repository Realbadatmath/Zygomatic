<!--
SPDX-FileCopyrightText: 2026 Zygomatic

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# ComfyUI workflow templates

API-format ComfyUI workflows referenced by the service modules in `..`.

All workflows here are the **API format** (flat dict keyed by node id, each
node has `inputs` + `class_type`). This is what `POST /prompt` accepts.

If you build/refine a workflow in the ComfyUI UI, export it via **"Save (API
Format)"** — not "Save". The UI-format JSON has `nodes`/`links`/`version`
keys and won't submit cleanly.

## Files

| File | Used by | Notes |
|---|---|---|
| `flux_txt2img.json` | `blender_character_service`, `comfy_generation_service` | Standard Flux txt2img |
| `flux_character_locked.json` | `comfy_generation_service` | Flux txt2img + character LoRA + **FaceDetailer second pass** (auto-stripped if Impact-Pack not installed) |
| `flux_character_ipadapter.json` | `comfy_generation_service` | Flux + XLabs IPAdapter + XlabsSampler (clip-vit vision; needs `x-flux-comfyui`) |
| `flux_pose_ipa_cell.json` | `comfy_generation_service` | Per-cell: Union pose ControlNet + IP-Adapter identity (contact sheet cells 01+) |
| `flux_character_instantid.json` | `comfy_generation_service` | Flux + **InstantID/PuLID** identity lock + lower-strength LoRA. Selected automatically when `conditioning.instantid_enabled=true` in the character bible AND any of `ApplyInstantID` / `InstantIDModelLoader` / `PulIDModelLoader` are available on the server. |
| `sdxl_txt2img.json` | `comfy_generation_service` | SDXL Juggernaut txt2img |
| `sdxl_character_locked.json` | `comfy_generation_service` | SDXL 1.0 base + character LoRA + **FaceDetailer** (SAM `device_mode: AUTO` required) |
| `sdxl_character_instantid.json` | `comfy_generation_service` | SDXL + InstantID when enabled |
| `sdxl_img2img.json` | `comfy_generation_service` | SDXL reference img2img for identity |
| `flux_img2img.json` | `comfy_generation_service` | VAE encode + KSampler denoise (Blender reference stills) |
| `klein_refcontrol.json` | `comfy_generation_service` | FLUX.2 klein + **RefControl depth LoRA** (Apache-2.0) — TWO chained `ReferenceLatent` branches: image 1 = depth map (node 22), image 2 = appearance reference (node 42). Chain position IS the image index. Node 14 stacks the control adapter on top of the identity LoRA at node 13. The positive prompt MUST carry the `refcontrol` trigger; the service prepends it. Selected by `_pick_workflow` when a klein render supplies `pose_image` and the adapter is installed. |
| `flux_fill_inpaint.json` | `flux_fill_service` Tier 2 | Flux Fill inpainting |
| `hand_fixer_flux_fill.json` | `comfy_generation_service` | HandFixer: MediaPipe mask + FLUX Fill post-pass |
| `wan_i2v.json` | `wan_video_service` | Wan 2.1 I2V via WanVideoWrapper nodes |
| `wan_i2v_REFERENCE_UI_FORMAT.json` | reference only | The full UI-format example from WanVideoWrapper — open in browser to see the full graph |

## Model files referenced

These workflows expect specific filenames in `ComfyUI/models/`. Ones that need
to be downloaded separately are flagged.

| Filename | Path | Status |
|---|---|---|
| `flux1-dev.safetensors` | `models/checkpoints/` | Already symlinked |
| `flux1-schnell.safetensors` | `models/checkpoints/` | Already symlinked |
| `flux_ae.safetensors` | `models/vae/` | Already symlinked (FLUX VAE) |
| `t5xxl_fp8_e4m3fn.safetensors` | `models/clip/` | **Missing** — download from comfyanonymous/flux_text_encoders |
| `clip_l.safetensors` | `models/clip/` | **Missing** — download from comfyanonymous/flux_text_encoders |
| `flux1-fill-dev.safetensors` | `models/unet/` | **Missing** — download from black-forest-labs/FLUX.1-Fill-dev |
| `Wan2_1-I2V-14B-480P_fp8_e4m3fn.safetensors` | `models/diffusion_models/` | **Missing** — download from Kijai/WanVideo_comfy |
| `umt5-xxl-enc-bf16.safetensors` | `models/text_encoders/` | **Missing** — same repo |
| `open-clip-xlm-roberta-large-vit-huge-14_visual_fp32.safetensors` | `models/clip_vision/` | **Missing** — same repo |
| `Wan2_1_VAE_bf16.safetensors` | `models/vae/` | **Missing** — same repo |

Quickest path to populate the missing FLUX encoders:
```bash
cd /home/zygomatic/ai-models/comfyui/models/clip
wget https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn.safetensors
wget https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors
```

For Wan, see Kijai's WanVideo_comfy repo on Hugging Face. Roughly 30 GB to
fully populate Wan I2V 14B.

## Optional: FaceDetailer second pass

`flux_character_locked.json` and `sdxl_character_locked.json` include **two**
Impact-Pack detail passes:

| Nodes | Pass |
|-------|------|
| 55 / 56 / 60 | Face — `face_yolov8m.pt` + SAM + FaceDetailer |
| 61 / 63 | Hand — `hand_yolov8s.pt` (Bingsu/adetailer) + SAM + FaceDetailer |

When Impact-Pack or weights are missing, `comfy_generation_service` strips
detailer nodes at submit time and routes `SaveImage` to the last available
pass (face-only or first-pass VAE decode).

Install Impact-Pack + Subpack and download weights:

```bash
cd /home/zygomatic/ai-models/comfyui/custom_nodes
git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack
git clone https://github.com/ltdrdata/ComfyUI-Impact-Subpack
# models/ultralytics/bbox/face_yolov8m.pt
# models/ultralytics/bbox/hand_yolov8s.pt   ← ADetailer hand detector
# models/sams/sam_vit_b_01ec64.pth
```

Or run the project checker (downloads SAM if missing):

```bash
cd "$ZYG_CREWS_ROOT"
python3 scripts/ensure_comfy_impact_ready.py
```

## Optional: HandFixer FLUX-Fill post-pass

When `ZYG_HAND_FIXER=1` (default) and `flux1-fill-dev.safetensors` + `ComfyUI-HandFixer`
are present, character previews run **YOLO hand detection → HandFixer FLUX-Fill**
instead of the SDXL HandDetailer inpaint pass. Falls back to HandDetailer if
HandFixer is unavailable.

```bash
python3 scripts/ensure_handfixer_ready.py   # clone node, pip deps, download Fill UNet
# restart ComfyUI after first install so MediapipeHandNode registers
bash /home/zygomatic/ai-models/comfyui/start_server.sh
```

| Env | Default | Purpose |
|---|---|---|
| `ZYG_HAND_FIXER` | `1` | Enable HandFixer post-pass (set `0` for HandDetailer only) |
| `ZYG_HAND_FIXER_DENOISE` | `1.0` | KSampler denoise for FLUX Fill pass |
| `ZYG_HAND_FIXER_STEPS` | `20` | Diffusion steps for hand repair |
| `ZYG_HAND_FIXER_YOLO_GATE` | `1` | Skip pass when YOLO finds zero hand boxes |
| `ZYG_FLUX_FILL_UNET` | `flux1-fill-dev.safetensors` | Fill UNet filename under `models/unet/` |

**SAMLoader** nodes must include `device_mode` (`AUTO`, `Prefer GPU`, or `CPU`).
Without it ComfyUI returns `Required input is missing` on node 56.
```

## Optional: InstantID / PuLID identity lock

`flux_character_instantid.json` provides a much stronger face-identity lock
than IPAdapter alone — useful when LoRA quality is mid-range or the
character has only a few training images. The pipeline auto-selects it when:

1. the character bible has `conditioning.instantid_enabled: true`, AND
2. a `master_reference_image` exists, AND
3. the ComfyUI server exposes `ApplyInstantID` / `InstantIDModelLoader` / `PulIDModelLoader`.

Install with one of:

```bash
# InstantID (Tencent)
cd /home/zygomatic/ai-models/comfyui/custom_nodes
git clone https://github.com/cubiq/ComfyUI_InstantID
# weights → models/instantid/, models/controlnet/, models/insightface/

# PuLID (better for cartoon → photoreal transfer)
git clone https://github.com/cubiq/PuLID_ComfyUI
```

Set `instantid_enabled` true in the bible (or via the new advanced UI
section) once the models are in place.

## Character continuity (Zygomatic)

Enable Comfy as the primary stills backend for the GUI process:

```bash
export ZYG_COMFY_PRIMARY=1   # or legacy ZYG_USE_COMFYUI=1
export ZYG_DRIFT_THRESHOLD=0.72   # optional drift sensitivity
```

Start ComfyUI: `/home/zygomatic/ai-models/comfyui/start_server.sh`

Bootstrap IPAdapter nodes and weights:

```bash
bash "$ZYG_CREWS_ROOT/scripts/setup_comfyui_stack.sh"
```

Optional LoRA directory (symlink trained weights here or set `ZYG_COMFY_LORA_DIR`):

`models/loras/` under the ComfyUI root.

Character bible on disk:

`/home/zygomatic/lora-datasets/storyteller_chars/<char_id>/character_bible.json`

| Env | Purpose |
|---|---|
| `ZYG_COMFY_PRIMARY` | Prefer Comfy for FLUX stills (bible + drift QA still apply) |
| `ZYG_DRIFT_THRESHOLD` | OpenCLIP/histogram drift reject threshold (default 0.72) |
| `ZYG_IPADAPTER_SCALE` | IPAdapter strength when reference image is used (default 0.65) |
| `ZYG_COMFY_LORA_DIR` | Directory scanned for `*.safetensors` character LoRAs |
