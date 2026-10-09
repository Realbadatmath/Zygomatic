<!-- SPDX-FileCopyrightText: 2026 Zygomatic -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Bring your own models

No model weights ship in this repository and nothing downloads them for you (three small
hash-checked detector files excepted). This page is the map: which external tools the
pipelines talk to, which model families each job expects, and where the code looks for all
of it. The authoritative, generated reference for every variable is
[`packages/workflows/docs/configuration.md`](../packages/workflows/docs/configuration.md);
the licensing ground rules are in
[`packages/workflows/docs/PROVENANCE.md`](../packages/workflows/docs/PROVENANCE.md).

## Read this first: three defaults that will surprise you

1. **ComfyUI is off until you say so.** Set `ZYG_USE_COMFYUI=1` or every render that needs
   it fails fast. `ZYG_COMFY_PRIMARY=1` additionally routes still images through ComfyUI.
2. **FLUX.1 renders are blocked by default.** FLUX.1-dev is licensed non-commercial, so the
   licence gate raises on any FLUX render unless you consciously set
   `ZYG_FLUX_RENDERS=allowed`. The character pipelines still *default* to the FLUX family —
   on a fresh installation either switch the family to a cleared one (klein or qwen) or
   accept the FLUX terms knowingly.
3. **The path defaults describe the author's machine.** Set the roots below before anything
   else; `ZYG_HOME` alone relocates the whole installation.

## The roots

| variable | default | what lives there |
| --- | --- | --- |
| `ZYG_CREWS_ROOT` | `$ZYG_HOME/Zygomatic Full/agents/crews` | the working tree jobs read and write |
| `ZYG_DATA_ROOT` | `$ZYG_CREWS_ROOT/data` | runtime state, `assets/` (detectors, voice seeds, meshes, scenes…), the audit trail |
| `ZYG_OUTPUT_ROOT` | `$ZYG_CREWS_ROOT/output` | finished renders, one folder per department |
| `ZYG_MODELS_ROOT` | `~/ai-models` | the heavy weights: both ComfyUI installs, `FLUX2/`, `SDXL/`, `realesrgan/`, trainers |
| `ZYG_MODELS_DIR` | `~/models` | the isolated-venv tools: `tts_indextts2/`, `vlm_judge/`, `sam3/`, diarization, speaker verify |
| `ZYG_LORA_DATASETS` / `ZYG_LORA_OUTPUTS` | `~/lora-datasets`, `~/lora-outputs` | per-character training sets and trained LoRA legs (`storyteller_chars/<id>/`, `creatures/`…) |

## External tools the code drives

- **ComfyUI, twice.** The main instance (`ZYG_COMFY_URL`, :8188, installed at
  `$ZYG_MODELS_ROOT/comfyui`) serves stills, Wan video, upscales and ACE-Step music; a
  second instance (`ZYG_LTX_COMFY_URL`, :8189, `$ZYG_MODELS_ROOT/comfyui-ltx`) serves
  LTX-2.5 and HiDream. Each needs its own `.venv` and a `start_server.sh` the services use
  to (re)start it; they share one GPU behind a submit lock. Custom nodes the graphs assume:
  WanVideoWrapper, Impact-Pack/Subpack, x-flux-comfyui, HandFixer, PuLID/InstantID,
  segment-anything-2, controlnet_aux. `packages/workflows/scripts/setup_comfyui_stack.sh`
  builds the folder layout;
  [`_comfy_workflows/README.md`](../packages/workflows/src/zyg_workflows/_comfy_workflows/README.md)
  maps each graph to its weights.
- **Blender** on `PATH` (or `BLENDER_BIN`). `bpy` is never installed from PyPI — the code
  that imports it runs inside Blender.
- **Ollama** (`ZYG_OLLAMA_URL`, :11434) is the local LLM server. Pull the tiers you want;
  the defaults across the code are `qwen3.5:9b` (vision/strict-JSON default),
  `qwen3.6:35b-a3b` (heavy), `gpt-oss:20b` (light), `qwen2.5:72b` and `qwen2.5-coder:32b`.
- **Claude, optionally.** The documentary and kids *writing* steps prefer the `claude` CLI
  on the operator's subscription (`ZYG_SCHOLARLY_LLM_BACKEND`, `ZYG_KIDSMUSIC_LLM_BACKEND`);
  Ollama is the fallback, so a fully local installation works.
- **Isolated-venv workers** under `$ZYG_MODELS_DIR`, each a checkout with its own `.venv`:
  IndexTTS-2 (`tts_indextts2/` — the only supported TTS engine; voices are reference WAVs
  to clone, not presets), the Qwen3-VL vision judge (`vlm_judge/`), SAM 3 + SAM 3D Body
  (`sam3/`), NeMo Sortformer diarization, speaker verification. Missing worker = that
  capability skips, it doesn't crash.
- **PostgreSQL** (the run ledger) and **Redis**; `faster-whisper` rides the Hugging Face
  cache (`ZYG_WHISPER_MODEL`, default `large-v3`).
- **Trainers:** SimpleTuner (`ZYG_SIMPLETUNER_DIR`) for image LoRAs, musubi-tuner under
  `$ZYG_MODELS_ROOT` for Wan character LoRAs.

## Model families by job

The cleared-for-commercial set the studio actually runs on today (the full licence verdict
per weight lives in the registry, below):

| job | engine | key weights (ComfyUI folder names) |
| --- | --- | --- |
| stills, licence-clean | FLUX.2 klein-4B (Apache-2.0) | `flux-2-klein-base-4b` + `qwen_3_4b` encoder + `flux2-vae` |
| stills + edits | Qwen-Image-2512 / Qwen-Image-Edit (Apache-2.0) | `qwen_image_2512_fp8_e4m3fn`, `qwen_image_edit_2509_*`, angles LoRA, InstantX inpaint ControlNet |
| kids pictures | HiDream-O1-Image-Dev (MIT), on the :8189 instance | `hidream_o1_image_dev_fp8_scaled` |
| video, image-to-video | Wan 2.1/2.2 I2V (+VACE, +Animate, optional Lightning LoRAs) | `Wan2_1-I2V-14B-480P_fp8_e4m3fn`, `umt5-xxl`, Wan VAE, via WanVideoWrapper |
| video, long-form kids | LTX-2.5 (:8189) | `ltx-2.5-22b-distilled` transformer + Gemma-4 encoder + its VAEs and upscaler |
| lip-sync | InfiniteTalk | `Wan2_1-InfiniteTalk-Single` + `wav2vec2-chinese-base` |
| speech | IndexTTS-2, Whisper ASR check | worker checkout under `$ZYG_MODELS_DIR/tts_indextts2` |
| music | ACE-Step 1.5 (in the main ComfyUI) | `ace_step_1.5_turbo_aio.safetensors` in `checkpoints/` |
| upscale / interpolation | Real-ESRGAN, RIFE (falls back to ffmpeg) | `RealESRGAN_x4plus.pth`, `RealESRGAN_x2.pth`; `rife-v4.6` |
| QC and detection | YOLOv8 face/hand, SAM, MediaPipe tasks, AuraFace identity, Qwen3-VL judge | under `$ZYG_COMFY_ROOT/models/...` and `$ZYG_DATA_ROOT/assets/detectors` |

SDXL (`sd_xl_base_1.0`, Juggernaut, DynaVision) remains for specific legs — note Juggernaut
and DynaVision are deliberately classified *unknown* by the licence registry, so nothing
publishes through them. FLUX.1-dev/Fill and the XLabs IP-Adapter are present in graphs but
non-commercial and gated (see above).
[`stack_upgrade_history.md`](../packages/workflows/docs/stack_upgrade_history.md) records
what replaced what, and why, with dates.

## The licence registry is the gatekeeper

`packages/workflows/src/zyg_workflows/data/runtime/model_licences.json` (override with
`ZYG_MODEL_LICENCES`) holds ~50 glob rules — licence, commercial yes/no, excluded
territories, source — plus LoRA lineage, so a LoRA is charged with its base model's
licence. Before anything publishes, `zyg_workflows.licence_provenance` walks the generation
graph against it. Check your own weight library from the CLI:

```bash
uv run python -m zyg_workflows.licence_provenance state     # whole-installation verdict
uv run python -m zyg_workflows.licence_provenance weight <file.safetensors>
```

## Bootstrap order on a fresh machine

1. Set the roots (`ZYG_HOME`, or each root individually) and the service URLs.
2. Install both ComfyUI instances and their custom nodes
   (`scripts/setup_comfyui_stack.sh` scaffolds the folders), Blender and Ollama; pull the
   Ollama tags you want.
3. Place the diffusion weights for the families you'll use (table above) into the ComfyUI
   model folders; `scripts/fetch_models.py` fetches the three hash-checked detector files;
   `scripts/ensure_comfy_impact_ready.py` and `scripts/ensure_handfixer_ready.py` verify the
   QC nodes.
4. Set up the isolated-venv workers you need (TTS first — nothing speaks without it).
5. Put voice seed WAVs under `data/assets/voice_seeds/` and run the licence CLI until the
   state verdict is clean.
6. `ZYG_USE_COMFYUI=1`, pick your character family, render something small.

## Known rough edges (flagged, not hidden)

- A handful of modules resolve `data/assets` relative to the *package* directory instead of
  `ZYG_DATA_ROOT` (voice-seed pool, some detector lookups). Until that is unified, symlink
  `packages/workflows/src/zyg_workflows/data/assets` → `$ZYG_DATA_ROOT/assets`.
- MediaPipe `.task` files are looked for in three places (`ZYG_MODELS_DIR`,
  `ZYG_MP_MODEL_DIR`, `$ZYG_DATA_ROOT/assets/detectors`); set `ZYG_MP_MODEL_DIR` explicitly
  and keep copies in the detectors folder.
- `ZYG_CHATTERBOX_DIR` (retired TTS fallback) and `ZYG_DIAR_HOME` carry defaults outside
  `zyg_workflows.paths`.
- The default character model family is still `flux` while FLUX renders are gated off —
  pick `klein` or `qwen` explicitly on a fresh installation.
