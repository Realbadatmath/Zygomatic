# Stack upgrade history — what was used, what replaced it

Every tool/model swap in the Zygomatic stack that can be dated from evidence on this box.
One row = one decision. "Was" is the thing that was actually running before the decision,
not a thing that was merely considered.

**Sources used to build this (nothing here is from recollection):**

1. `agents/crews/data/models.json` — the scheduler's model roster. Its git history
   (`git log -- data/models.json`) and the dated pre-edit copies
   (`.tts_removal_backups_20260715/`, `.tts_indextts2_primary_backups_20260806/`,
   `.creature_workflow_backups_20260825/`) give **id-level** swaps: when a slot keeps its id
   and changes its name, that is a replacement, in writing.
2. The 293 dated memory files in `~/.claude/projects/-home-zygomatic-zygomatics-zero/memory/`.
   Cited per row by filename.
3. `git log` of `agents/crews` (baseline 2026-05-08).
4. `gpu_ai_models.json` / `cpu_ai_models.json` — the pre-July card roster (see §5).

**Date convention:** the date is the date in the record, i.e. the day the decision was taken
or deployed, not the day the memory file was written. Rows marked ~ are dated only to the
week. §6 lists what could not be dated at all.

---

## 1. Master chronology

| Date | Lane | Was | Became | Why / outcome |
|---|---|---|---|---|
| 2026-05-08 | — | — | git baseline of `agents/crews`; FLUX + SDXL + Wan2.1 already live (FLUX OOM fix commit 05-21) | earliest hard evidence on the box |
| 2026-07-06 | process mgmt | ad-hoc launchers, `kill_port(5000)` + `Popen` | systemd user units | restartable services (`project_workflows_gui`) |
| 2026-07-07 | pipeline control | halt only | pause/resume with a scoped registry + stage-level resume | `project_pipeline_pause_resume` |
| 2026-07-15 | model registry | legacy 1xxx roster (see §5) | the 2xxx live roster: FLUX.1-dev/schnell/fill, Qwen-Image-Edit-2509, SDXL Juggernaut XL v9, PuLID-FLUX, InstantID, ArcFace, Wan2.1-I2V-14B, Kokoro-82M, MusicGen/AudioGen, Ollama tiers | first registry that described the real stack (`data/models.json` @ 9ace0ac1) |
| 2026-07-15 | TTS | Fish-Speech S2-Pro + Orpheus-3B (registered) | both removed; Kokoro-82M stays primary | `.tts_removal_backups_20260715` + roster diff |
| 2026-07-16 | SDXL base | Juggernaut XL v9 under character LoRAs | aligned SDXL base (train/inference base match); dual SDXL twin default OFF | `project_lora_storage` |
| 2026-07-25 | image families | FLUX photoreal only | SDXL (DynaVision-XL) becomes the **animated** 3D-toon twin; FLUX stays photoreal | `project_sdxl_animated` |
| 2026-07-25 | identity QC (animated) | ArcFace identity QC | VLM skin/hair gate | ArcFace mis-scores stylised faces (`project_sdxl_animated`) |
| 2026-07-26 | contact sheet | single 6-cell sheet | 48-angle per-cell sheet (FLUX per-cell + Qwen-Image-Edit-2509 angle LoRA) | `project_sdxl_48angle` |
| 2026-07-27 | face lock / restyle | InstantID; SDXL img2img with no face lock | **universal depth-ControlNet** engine + Qwen-Image-Edit restyle | "InstantID disfigures children"; the no-lock path re-synthesised faces and invented a grey-haired adult (`project_arcane_restyle`) |
| 2026-07-28 | ASR | Whisper base/tiny (openai-whisper) | faster-whisper large-v3 + VAD, shared `zyg_whisper.py` loader | `project_transcribe_diarization` |
| 2026-07-28 | diarization | **none** | NeMo Sortformer 4-spk + TitaNet clustering, isolated venv | same |
| 2026-07-29 | video motion | plain Wan2.1 I2V | VACE control-frame recipe (shift is the lever, 480p only) | `project_wan_motion_debug` |
| 2026-07-30 | visual judge | none (moondream can't read text) | local Qwen3-VL judge with VRAM tiers (`vlm_inspector`) | `project_vlm_inspector` |
| 2026-07-30 | narration | Azure Neural TTS / edge-tts | Kokoro stopgap + pause-map assembler, duck/master chain | `project_narration_audio` |
| 2026-08-06 | **TTS** | Kokoro-82M **and** Azure Neural TTS | **IndexTTS-2 primary, Chatterbox the only fallback** — both are cloners, so a voice became a reference WAV, not a preset | blind bake-off; speed cost 0.03x→0.83x RT accepted (`project_tts_stack`, `project_tts_research_2026`) |
| 2026-08-06 | child voice | Maya1 voice design | Chatterbox + DSP child transform (Maya1 could not design a child voice — all 11 candidates adult male); IndexTTS-2 preserves child timbre | `project_abel_child_voice` |
| 2026-08-08 | Medusa training | pixel editing | SimpleTuner masked loss (identity vs body-template modes) | `project_medusa_dual_mode` |
| 2026-08-09 | **music** | MusicGen / AudioGen (CC-BY-NC) | **ACE-Step 1.5 turbo** (MIT) via `ace_step_service.py`; generative foley tier removed, 14 NC files quarantined | monetised channel = licence exposure (`project_stack_upgrade_aug2026`, `project_documentary_parity`) |
| 2026-08-09 | attention kernel | TeaCache (import-dead) | SageAttention triton (`ZYG_WAN_ATTENTION=sageattn`) | `project_stack_upgrade_aug2026` |
| 2026-08-09 | hand repair | FLUX.1-fill | Qwen InstantX inpaint → cv2 TELEA fallback | FLUX pause + measured tier order (`project_handfixer_rebuild`, `project_kanban_card_sync`) |
| 2026-08-09 | vision LLM | llama3.2-vision | qwen3.5:9b (llama3.2-vision **deleted** — EU exclusion) | `project_stack_upgrade_aug2026` |
| 2026-08-09 | heavy/light LLM | llama3:70b, qwen2.5:72b, mistral:7b | heavy `qwen3.6:35b-a3b`, light `gpt-oss:20b` (qwen2.5:72b kept for murch) | same |
| 2026-08-09 | video anchor stills | FLUX.1-schnell | Qwen-Image-2512 (`ZYG_VIDEO_STILL_FAMILY=qwen`) | same |
| 2026-08-09 | video model | Wan2.1-I2V-14B | Wan2.2-I2V-A14B dual-expert + Lightning 4-step **env-gated, default OFF** | cutover held for motion-gate + identity A/B (same) |
| 2026-08-09 | segmentation | YOLOv8 / Segment Anything era | SAM 3 + SAM 3D Body live (sha-pinned, own venvs) | prop-persistence gate QGT-039 (same) |
| 2026-08-09 | licence | nothing | `licence_provenance.py` + `model_licences.json`; **FLUX renders PAUSED** by default | a LoRA is charged with its base model's licence (`project_licence_gate`) |
| 2026-08-13 | strict-JSON LLM | qwen2.5:7b (remix + briefing) | qwen3.5:9b — **not** gpt-oss:20b, which returns an empty response under `format:json` | verified on ollama 0.17.7 (`project_kanban_card_sync`) |
| 2026-08-15 | typography judge | dead gate (no verdicts) | Qwen3-VL primary + Haiku vision fallback | `project_typography_gate` |
| 2026-08-21 | typography judge | Qwen3-VL (needs 14 GB, 5.9 GB free) + Haiku (HTTP 400 "credit balance too low") | **RapidOCR on CPU**, 1.00/1.00 over 48 labelled frames, 0.58 s/frame | the judge must answer *in-loop*; OCR answers the actual question (`project_typography_ocr_judge`) |
| 2026-08-25 | documentary stills | FLUX.1-schnell | Qwen-Image-2512 + per-slot era gate; negatives live for the first time (real CFG) | `project_anachronism_gate_qwen`; roughly doubled episode runtime (`project_documentary_runtime_profile`) |
| 2026-08-25 | render+train family | FLUX.1-dev (BFL non-commercial) | **FLUX.2 klein-4B (Apache-2.0)** as a first-class render + LoRA-train family | `project_klein_pathway` |
| 2026-08-25 | creature sheet | FLUX.1-dev txt2img stills, template captions, zero QC | judged multi-angle sheet + review gate → klein LoRA | `project_creature_sheet_workflow` |
| 2026-08-25/26 | weights on disk | whole FLUX.1-dev family (dev, fill-dev, both dev ControlNets) | deleted; `vae/flux_ae` repointed at schnell | 153G→439G free (`project_disk_audit_aug25`) |
| 2026-08-26 | virtual keyboard | onboard (segfaults on python3.12) | xvkbd | `project_virtual_keyboard_setup` |
| 2026-08-29 | anime analysis | photo-prior taggers; RAFT optical flow | WD Tagger v3 (only anime-native model); GMFlow over RAFT | photo priors collapse ~5x on animation (`project_vfx_tooling_landscape`) |
| 2026-08-30 | board wiring | `MusicGen Background Music` card | `ACE-Step Background Music` (server map re-keyed to board titles) | 24 of 28 documentary cards could never leave `queued` (`project_kanban_card_sync`) |
| 2026-09-04 | cinema delivery | direct file playback | HLS + hls.js | the browser caps preload at 2.4 s (`project_zero_cinema_hls`) |
| ~2026-09-02 | agent orchestration | ad-hoc chat sessions | Session Tree board (:7100) spawning Opus executors, one task per session | `project_session_tree` |
| 2026-09-06 | sung-pitch meter | Praat | `sung_pitch.py` (RMVPE), RPA 0.971 clean / 0.967 through demucs | Praat retired for sung material (`project_farmyard_register_tree`) |
| 2026-09-06 | arch assistant LLM | Opus 5 (~$0.11 per 5-call request) | Haiku 4.5 (~$0.01) with local `qwen3.6:35b-a3b` tried first; `_cheap_model()` refuses opus/fable/mythos | tool mapping is not reasoning (`feedback_arch_assistant_no_opus`) |
| 2026-09-07 | arch assistant backend | Anthropic API key | `claude -p --model sonnet` on the operator's login + MCP shim; opus/fable→sonnet | "subscription, not API" (`project_arch_assistant`) |
| 2026-09-10 | human base mesh | Human Generator V4 (even the $128 tier grants no AI-training right, no 3D-file distribution) | MPFB (CC0) + CharMorph / MHR / SOMA-X / Z-Anatomy | licence read in full (`project_human_generator_licence`, `project_human_base_install`) |
| 2026-09-15 | voice conversion | — (DDSP-SVC rejected: openvpi vocoder CC BY-NC-SA) | Applio RVC, isolated Py3.12 venv, fixed Warm Control voice | `project_kidsmusic_voice_conversion` |
| 2026-09-15 | defect screen | CLIP defect captions | qwen3.5:9b screen | CLIP captions were a content detector (rocking horses, smiling shapes) (`project_kidsvideo_candidate_pool`) |
| 2026-09-17 | **documentary LLM** | Haiku 4.5 (outline/hooks/fact-check/vision judges) + Sonnet 4.6 (script, scenes, prompts) **on the API key** | **claude-opus-5 through the Max login** via `subscription_llm.py` (headless `claude -p` turns, image blocks over stream-json) | $0.62-0.92/episode API vs ~2-3 ct of the weekly subscription; local Ollama calls stay local (`project_scholarly_opus_subscription`) |
| 2026-09-17 | Vicky's brain | Claude Sonnet | Dolphin-Mistral-24B-Venice Q8_0 local (25 GB, Apache-2.0); `ZYG_VICKY_CLAUDE=on` restores Sonnet | `project_vicky_chat_store` |
| 2026-09-19 | image→mesh | TripoSR / InstantMesh / TRELLIS.2 (and the Tencent-EU-excluded family: TripoSG, PartCrafter, DetailGen3D, Hunyuan3D) | Direct3D-S2 (MIT code **and** weights, EU-clean) | licences checked at FILE level, not repo root (`project_direct3d_s2_install`, `feedback_licence_policy`) |
| 2026-09-19 | motion capture | none usable (SMPL files NC + unobtainable; AMASS forbids commercial training) | GEM-X (192 frames in 57 s, 2 GB VRAM) → SOMA BVH | `project_movement_capture_path`, `project_movement_base_models_research` |
| 2026-09-20 | VACE recipe | single-pass VACE | 5 chained 25-frame chunks, 7-frame overlap cross-fade, strength 0.8 | accepted take 10 of 8 full takes (`project_vace_character_recipe`) |
| 2026-09-23 | anatomy geometry | procedural lathes (abandoned after three passes) | CC0 Blender Studio 135-bone skeleton **mesh** fitted per segment to the cmu_mb rig | `project_movement_real_anatomy_tree` |
| 2026-09-23 | LoRA loading | PEFT-format LoRAs — ComfyUI silently applied **nothing** (453,440 "lora key not loaded" lines) | `convert_lora.py` → ComfyUI-native keys | stack-wide defect (`project_comfy_lora_never_applied`) |
| 2026-10-01 | storage | 52k JSON state files | SQLite (Mongo rejected); `prompt_log` rewrite 185 ms → 21 ms | `project_storage_api_audit` |
| 2026-10-02 | **database** | SQLite (3 DBs) | **Postgres 16** at `~/pg16`, user unit `zyg-postgres.service`, unix socket, no TCP; old files renamed `*.pre-postgres-20261002`, never deleted | `project_postgres_pg16` |
| 2026-10-02 | **video engine** | Wan 2.1/2.2 (609 s for a 5 s clip) | **LTX-2.5 22B distilled** on a separate ComfyUI 0.38.1 (:8189) — 5 s 960² **with audio in 25 s**, identity held | the only open-weights candidate that is both legal here and runnable (`project_ltx25_instance`) |
| 2026-10-02 | **image engine** | Qwen-Image-2512 / klein-4B | **HiDream-O1-Image-Dev** (MIT, 8B pixel-native, no VAE/no separate text encoder) — 1024 in 4.0 s warm, 2048 in 13 s | highest open-weights entry on the T2I arena; identity not yet measured (`project_hidream_o1_install`) |
| 2026-10-02 | kids pipelines | klein stills, no motion | HiDream-O1 pictures + an LTX-2.5 clip for **every** picture (no stills left) via `ltx_hidream_service.py` | operator ask; 67 tests green (`project_kids_hidream_ltx_build`) |
| 2026-10-02 | **kids writing LLM** | `qwen3.5:9b` on local Ollama for the lyric, the storyboard and the daily series' moment | **Claude Opus 5 through the operator's Max subscription** (`kids_llm.py` over `subscription_llm.run_turn`, never the API key); the local model is now the FALLBACK, the template/motif deck the floor | operator ask ("assign opus to each of these steps … through my subscription, NOT on API"); measured on the same theme: 9B shipped 6 lines padded to 12 and a chorus that was different text each return, Opus wrote 30 distinct lines with one verbatim hook and a 32-picture storyboard with 0 motif-deck filler in one 11 s turn (`project_kids_opus_subscription`) |
| 2026-10-02 | TTS fallback | Chatterbox (~4.1 GB, MIT, Perth watermark) | retired on the operator's call — "current TTS works fine" | `project_disk_audit_aug25` |
| 2026-10-02 | ComfyUI | 0.22 production (:8188) only | + a second instance 0.38.1 (:8189) sharing the same weights library; the two never run GPU work at once | `project_ltx25_instance` |

---

## 2. Lineage chains (the short version)

```
IMAGE      SD 1.5 / Dreamshaper / Kandinsky 2.2  (pre-07-15 roster)
             → FLUX.1-dev + schnell              (live by 05-2026)
             → + SDXL DynaVision-XL animated twin   07-25
             → Qwen-Image-2512  (video stills 08-09, documentary 08-25)
             → + FLUX.2 klein-4B, Apache-2.0        08-25   [FLUX.1-dev deleted 08-26]
             → HiDream-O1 (MIT)                     10-02

EDIT/LOCK  InstantID + SDXL img2img (no face lock)
             → universal depth-ControlNet + Qwen-Image-Edit-2509   07-27
INPAINT    FLUX.1-fill → Qwen InstantX inpaint → cv2 TELEA          08-09
UPSCALE    RealESRGAN x2 — still the incumbent (SeedVR2 measured and rejected 08-09)

VIDEO      AnimateDiff / SVD / Deforum  (pre-07-15 roster)
             → Wan2.1-I2V-14B
             → VACE control-frame recipe            07-29, chunked recipe 09-20
             → Wan2.2 A14B + Lightning, env-gated OFF  08-09
             → LTX-2.5 22B distilled (+ audio)      10-02

TTS        Bark / Tortoise → Azure Neural + edge-tts → Kokoro-82M (07-30)
             → IndexTTS-2 primary + Chatterbox fallback   08-06
             → IndexTTS-2 alone (Chatterbox retired)      10-02
           (Fish-Speech S2-Pro and Orpheus-3B removed unused, 07-15)

MUSIC      MusicGen / AudioGen (CC-BY-NC) → ACE-Step 1.5 turbo (MIT)   08-09
PITCH      Praat → sung_pitch.py RMVPE                                  09-06
VOICE CONV (none) → Applio RVC                                          09-15

ASR        Whisper base/tiny → faster-whisper large-v3 + VAD            07-28
           resident stays large-v2 (large-v3-turbo tied WER, not swapped)
DIARIZE    none → NeMo Sortformer 4-spk + TitaNet clustering            07-28
           (the standalone transcriber app keeps pyannote)

JUDGES     moondream (can't read text) → Qwen3-VL local judge           07-30
           typography: Qwen3-VL + Haiku vision → RapidOCR CPU           08-21
           identity: ArcFace → VLM skin/hair gate on the animated path  07-25
           defect: no local VLM is reliable; Qwen3.6-35B best recall 0.82 (09-27)

LLM        Claude 3 / GPT-4 / LLaMA 3 70B (pre-07-15 roster)
  local      llama3:70b, qwen2.5:72b, llama3.2-vision
               → qwen3.6:35b-a3b heavy, gpt-oss:20b light, qwen3.5:9b vision  08-09
               → qwen3.5:9b for strict JSON (gpt-oss returns empty)            08-13
  Anthropic  Haiku 4.5 + Sonnet 4.6 on the API key
               → arch assistant: Opus 5 → Haiku 4.5 → claude -p CLI sonnet  09-06/07
               → documentary: everything → claude-opus-5 on the Max login   09-17
               → Session Tree executors: Opus                                09-02+
  embedded   Vicky: Sonnet → Dolphin-Mistral-24B-Venice Q8_0 local          09-17

3D         TripoSR / InstantMesh / TRELLIS.2 → Direct3D-S2 (MIT, EU-clean)  09-19
           Human Generator V4 → MPFB (CC0)                                  09-10
           UniRig skin weights → Blender auto weights kept                   09-05
           procedural lathes → CC0 Blender Studio skeleton mesh              09-23
           motion capture: none → GEM-X                                      09-19

INFRA      ad-hoc launchers → systemd user units          07-06
           TeaCache → SageAttention                        08-09
           52k JSON files → SQLite → Postgres 16           10-01/10-02
           ComfyUI 0.22 → + 0.38.1 second instance         10-02
```

---

## 3. Upgrades that were measured and **refused** (the incumbent won)

These matter as much as the swaps: each one is a tool that is installed, or was close to
being wired, and is deliberately not in the pipeline.

| Date | Candidate | Incumbent kept | Reason, measured |
|---|---|---|---|
| 2026-08-09 | SeedVR2 7B (+ sharp) | RealESRGAN x2 | incumbent departs less from the source *and* carries ~1.7x the detail energy; SeedVR2 changed more and came out softer (51/65 FAIL) |
| 2026-08-09 | whisper large-v3-turbo | faster-whisper large-v2 resident | tied WER on the synthetic set, 18 % faster — held pending a real-audio A/B |
| 2026-08-09 | AuraFace (full swap) | glintr100 / antelopev2 | frontal on par, **profile markedly worse** (FAR 0.605 vs 0.338) — frontal gates may pilot it, profile gates keep antelopev2 |
| 2026-08-13 | gpt-oss:20b for strict JSON | qwen3.5:9b | `format:'json'` returns an empty response (harmony channels vs the format grammar) |
| 2026-08-09 | Wan2.2 production cutover | Wan2.1 + VACE | gated OFF pending motion-gate + identity A/B; Lightning 4-step is 4x faster but swaps prompted motion for a camera pan (09-06) |
| 2026-09-05 | UniRig | Blender auto weights | loses on both test meshes; two silent-failure traps |
| ~2026-09-15 | Wan-Animate | VACE | full-body-ref replacement rendered a frozen grey statue, pose ignored |
| 2026-09-15 | DDSP-SVC | Applio RVC | openvpi vocoder is CC BY-NC-SA |
| 2026-09-15 | CLIP defect captions | qwen3.5:9b | it is a content detector, not a defect detector |
| 2026-09-10 | Human Generator V4 | MPFB (CC0) | no AI-training right at any tier, including $128 commercial |
| 2026-09-19 | SMPL / AMASS-trained stacks | own-rig pipeline | SMPL files NC and unobtainable since Epic bought Meshcapade; AMASS forbids commercial training |
| 2026-10-01 | MongoDB | SQLite → Postgres | no measured win for this workload |
| 2026-10-02 | MiniMax H3 / MAGI-2 / Wan 2.5-3.0 / HunyuanVideo / Seedance | LTX-2.5 | EU exclusion (H3, Hunyuan), 8 Hopper GPUs + 307 GB (MAGI-2), API-only (Wan 2.5+), closed (Seedance/CapCut) |
| 2026-08-09 | "relief point-landmark primitive" | existing relief layer | wrong twice over; wiring it would have manufactured 3 wrong-signed resolutions |
| 2026-07-16 | inswapper face-swap post-lock, forensic localizers | per-cell locks + gates | 128 px box-only, misses cheek/hair ghosts, re-introduces waxy skin |

---

## 4. Licence-driven removals (not quality upgrades — exposure removals)

The channel being monetised (2026-08) is the single biggest cause of swaps in this file.

| Date | Removed | Licence problem |
|---|---|---|
| 2026-08-09 | MusicGen / AudioGen weights + 14 `ag_*.mp3` | CC-BY-NC |
| 2026-08-09 | llama3.2-vision | EU exclusion |
| 2026-08-09 | FLUX.1-dev renders + LoRA training | BFL non-commercial — every FLUX char LoRA is a derivative of a NC base |
| 2026-08-26 | FLUX.1-dev family deleted from disk | same |
| 2026-09-10 | Human Generator V4 | no AI-training right |
| 2026-09-15 | DDSP-SVC | CC BY-NC-SA vocoder |
| 2026-09-19 | TripoSG / PartCrafter / DetailGen3D | MIT at the repo root, Tencent EU-excluded in the core transformer file |
| 2026-08-29 | (4 suspected "live NC exposures" in VFX) | all four turned out to be dead code |

---

## 5. The pre-2026-07-15 roster

`gpu_ai_models.json` / `cpu_ai_models.json` still carry the roster the boards used before the
2xxx registry existed. Treat it as **the tools the project was built around or planned for**,
not as proof each one rendered a shipped frame — several are cloud services this box never had
keys for:

- image/video: Stable Diffusion 1.5, Dreamshaper / RealisticVision, Kandinsky 2.2,
  AnimateDiff, Stable Video Diffusion, Deforum, ControlNet, RealESRGAN, Dreambooth, CLIP, VAE,
  LoRA, ComfyUI, Blender (bpy), DaVinci Resolve, YOLOv8 + Segment Anything, ImageHash + OpenCV
- hosted: Midjourney, Runway, Pika Labs, ElevenLabs, AssemblyAI, Deepgram, GPT-4, Claude 3,
  SEMrush, Google Analytics
- audio: Bark, Bark-Voice-Cloning, Tortoise TTS, Librosa, pydub, ffmpeg
- LLM/agents: LLaMA 3 70B Q4, Mistral 7B, Mistral Mixtral, DeepSeek Coder 33B,
  CrewAI / OpenAgents, LangChain, HumanEval, Airflow, FastAPI, Plotly

Of that list, the ones that survive into the live stack today are ComfyUI, Blender, ControlNet,
RealESRGAN, LoRA/VAE tooling, CLIP, OpenCV/ImageHash, ffmpeg and the local-LLM idea — everything
else was replaced by the chains in §2.

---

## 6. Known gaps in this chart

- **Nothing before 2026-05-08** is recorded on this box (git baseline), and the memory record
  starts 2026-07-07. Any earlier tool history would have to come from the operator.
- The 1xxx → 2xxx roster change is dated 2026-07-15 by its commit, but the *actual* adoption of
  FLUX/SDXL/Wan2.1 happened earlier and is undated here — FLUX was already in production by the
  2026-05-21 OOM-fix commit.
- `agents/crews` auto-snapshots stop at 2026-08-04, so September and October swaps are dated
  from memory files and dated `.bak-*` / backup directories, not from commits.
- A few swaps are dated to the week only (marked ~): Session Tree executor model, Wan-Animate
  rejection.
- Per-pipeline *stage* lineage (which board card names which engine) lives in
  `bp_pipeline_api.py`'s stage maps and is deliberately not duplicated here —
  see `project_kanban_card_sync` for why card titles are join keys.

---

## 7. The machine-readable twin — Metrics > Lineage

This file is organised by DECISION (one row = one day). The same history organised by
TOOL lives in **`data/stack_lineage/<lane>.json`** and is served as the **Lineage** subtab
of :5000/metrics (`stack_lineage_hub.py`, section `stack_lineage`). One card per model or
tool: what it was for, every problem recorded against it, what the thing that replaced it
actually fixed, and what is still wrong today.

Two rules that make the two files agree instead of drift:

1. **A fix is recorded on the thing that HAD the problem, never on the thing that fixed
   it.** The predecessor's issue carries `"state": "solved"` plus `"by": "<successor id>"`,
   and the successor's "what this upgrade fixed" block is derived from it. A card cannot
   claim a fix its predecessor does not record.
2. **Every issue names its evidence and its grade** — `measured` (a bench in this repo),
   `receipt` (a production run or a commit), `licence` (a licence read in full),
   `operator` (a ruling), `vendor` (a model-card claim, unchecked) or `assumed`. An entity
   with no issues recorded reads as "nothing recorded", never as "no problems".

**Keeping both current:** add a row here the same day a swap goes live, with the evidence
(a measurement, a licence read, or an operator ruling) named in the last column — and add
or update the entity in its lane file, then run `python3 stack_lineage_hub.py check`
(ids, links, enums, dates, evidence) and `pytest tests/test_stack_lineage.py`. A swap with
no reason in the last column is a swap nobody can defend later.
