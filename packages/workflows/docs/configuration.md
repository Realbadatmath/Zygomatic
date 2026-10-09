<!-- SPDX-FileCopyrightText: 2026 Zygomatic -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Configuration

How a zygomatic-workflows checkout is configured: the filesystem roots, the service
endpoints, and every `ZYG_*` feature flag. The tables below are generated — run
`python3 scripts/gen_settings.py` to refresh them and `--check` to assert they are current.

<!-- BEGIN GENERATED SETTINGS (scripts/gen_settings.py) -->
## Roots and service endpoints

Declared in `src/zyg_workflows/paths.py`. Every one is read from the environment and falls
back to the value the production tree uses, so **an unconfigured checkout behaves like the
legacy installation**: `ZYG_CREWS_ROOT` defaults to `~/Zygomatic Full/agents/crews`.

| Variable | Default | Points at |
| --- | --- | --- |
| `ZYG_HOME` | `~` | home directory every other root hangs off |
| `ZYG_CREWS_ROOT` | `~/Zygomatic Full/agents/crews` | the legacy production tree — the default keeps the old installation working untouched |
| `ZYG_DATA_ROOT` | `$ZYG_CREWS_ROOT/data` | crew databases, briefs, state |
| `ZYG_OUTPUT_ROOT` | `$ZYG_CREWS_ROOT/output` | renders and pipeline artefacts |
| `ZYG_MODELS_ROOT` | `~/ai-models` | checkpoints, LoRAs, upscalers |
| `ZYG_COMFY_ROOT` | `$ZYG_MODELS_ROOT/comfyui` | ComfyUI installation |
| `ZYG_COMFY_INPUT` | `$ZYG_COMFY_ROOT/input` | images staged for ComfyUI |
| `ZYG_COMFY_OUTPUT` | `$ZYG_COMFY_ROOT/output` | what ComfyUI writes |
| `ZYG_COMFY_MODELS_ROOT` | `$ZYG_COMFY_ROOT/models` | ComfyUI checkpoints |
| `ZYG_COMFY_LORA_DIR` | `$ZYG_COMFY_ROOT/models/loras` | LoRAs ComfyUI loads |
| `ZYG_FLUX_ROOT` | `$ZYG_MODELS_ROOT/FLUX` | FLUX weights |
| `ZYG_REALESRGAN_ROOT` | `$ZYG_MODELS_ROOT/realesrgan` | Real-ESRGAN weights |
| `ZYG_LORA_DATASETS` | `~/lora-datasets` | LoRA training sets |
| `ZYG_LORA_OUTPUTS` | `~/lora-outputs` | trained LoRA output |
| `ZYG_MODELS_DIR` | `~/models` | misc. local models |
| `BLENDER_BIN` | `which('blender') or /usr/local/bin/blender` | Blender executable |
| `ZYG_TMP_DIR` | `$TMPDIR/zygomatic` | scratch space; tmp_dir() creates it 0o700 |
| `BIND_HOST` | `127.0.0.1` | interface the services bind to — loopback by design |
| `ZYG_COMFY_URL` | `http://127.0.0.1:8188` | ComfyUI API |
| `ZYG_OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama API |
| `ZYG_KANBAN_URL` | `http://127.0.0.1:8899` | kanban board |
| `ZYG_DASHBOARD_URL` | `http://127.0.0.1:5000` | dashboard GUI |
| `ZYG_PUBLIC_URL` | `http://127.0.0.1:5001` | public site |
| `ZYG_SESSION_TREE_URL` | `http://127.0.0.1:7100` | session tree board |
| `ZYG_REDIS_URL` | `redis://127.0.0.1:6379/0` | Redis instance |
| `ZYG_STORYTELLER_CHARS` | `$ZYG_LORA_DATASETS/storyteller_chars` | storyteller character datasets |
| `ZYG_STORYTELLER_LORAS` | `$ZYG_LORA_OUTPUTS/storyteller_chars` | LoRAs trained from them |
| `ZYG_CREATURE_DATASETS` | `$ZYG_LORA_DATASETS/creatures` | creature datasets |
| `ZYG_CREATURE_OUTPUTS` | `$ZYG_LORA_OUTPUTS/creatures` | creature LoRA output |
| `ZYG_CREATURE_LORA_DIR` | `$ZYG_MODELS_ROOT/creature-loras` | creature LoRAs the services load |
| `ZYG_ANIMAL_LORA_DIR` | `$ZYG_MODELS_ROOT/animal-loras` | animal LoRAs the services load |
| `ZYG_MEDUSA_MODEL_DATASET_ROOT` | `$ZYG_LORA_DATASETS/medusa_models` | Medusa model datasets |
| `ZYG_MEDUSA_MODEL_OUTPUT_ROOT` | `$ZYG_LORA_OUTPUTS/medusa_models` | Medusa model LoRA output |
| `ZYG_MEDUSA_RUNTIME_DIR` | `$ZYG_DATA_ROOT/runtime` | per-character `medusa_<id>_state.json` |
| `ZYG_GNM_REPO` | `$ZYG_MODELS_ROOT/gnm` | GNM head-geometry checkout |
| `ZYG_ICT_REPO` | `$ZYG_MODELS_ROOT/ICT-FaceKit` | ICT-FaceKit checkout |
| `ZYG_SAM3_HOME` | `$ZYG_MODELS_DIR/sam3` | SAM 3 checkout |
| `ZYG_SAM3_PYTHON` | `$ZYG_MODELS_DIR/vlm_judge/.venv/bin/python` | interpreter the SAM 3 worker runs on |
| `ZYG_SAM2_NODE_DIR` | `$ZYG_COMFY_ROOT/custom_nodes/ComfyUI-segment-anything-2` | SAM 2 ComfyUI node |
| `ZYG_VLM_HOME` | `$ZYG_MODELS_DIR/vlm_judge` | VLM judge installation |
| `ZYG_MP_MODEL_DIR` | `<package>/data/models/mediapipe` | MediaPipe task files, shipped with the package |
| `ZYG_VFX_ROOT` | `<package>/data/runtime/vfx_library` | VFX library the probes read and write |
| `ZYG_INDEXTTS_DIR` | `$ZYG_MODELS_DIR/tts_indextts2` | IndexTTS-2 checkout |
| `ZYG_VOICE_ANALYSIS_DIR` | `$ZYG_MODELS_DIR/voice_analysis` | voice-analysis models |
| `ZYG_ASR_PYTHON` | `~/.venvs/asr/bin/python` | interpreter the out-of-process ASR runs on |
| `ZYG_SIMPLETUNER_DIR` | `~/SimpleTuner` | SimpleTuner checkout the LoRA trainer drives |
| `ZYG_SERVER_PYTHON` | `$ZYG_CREWS_ROOT/../.venv/bin/python` | interpreter the head-fit worker runs on |
| `ZYG_GPU_LOCK` | `~/.zyg_gpu.lock` | lock file that serialises the GPU |
| `ZYG_LTX_COMFY_ROOT` | `$ZYG_MODELS_ROOT/comfyui-ltx` | the LTX-only ComfyUI installation |
| `ZYG_LTX_COMFY_URL` | `http://127.0.0.1:8189` | its API |
| `ZYG_REMIX_BROLL_DIR` | `~/Zygomatic/GameSim/recordings` | self-recorded b-roll the remix pipeline cuts from |
| `ZYG_REMEDY_KB` | `<package>/config/remedy_kb.json` | authored remedy knowledge base |
| `ZYG_REMEDY_KB_LEARNED` | `<package>/data/runtime/remedy_kb_learned.json` | what the pipeline learns into it |
| `ZYG_REMEDY_KB_STATE` | `<package>/data/runtime/remedy_kb_state.json` | its bookkeeping |
| `ZYG_PLANS_DIR` | `<package>/data/architecture/plans` | floor-plan packs |
| `ZYG_METRICS_RUNTIME_DIR` | `<package>/data/runtime` | runtime directory the metrics writers share |
| `ZYG_ANSUR_IMPORT_DIR` | `$ZYG_TMP_DIR/ansur_import` | scratch for the ANSUR reference import |

Scratch files go to `paths.tmp_dir(sub)`, which creates `$ZYG_TMP_DIR/sub` with mode `0700`.

## Feature flags

799 `ZYG_*` variables, scanned out of `src/zyg_workflows` by `scripts/gen_settings.py`
and registered in `src/zyg_workflows/settings.py` as `FLAGS`. An empty default column means the
call site passes no default (the flag is optional and the code handles its absence).
Read one with `settings.get(name, cast)`; `settings.check()` warns about `ZYG_*` variables that
are set but that nothing reads. Defaults that were absolute paths inside a home directory are
stored home-relative (`~/…`) and expanded by `settings.get()`.

| Flag | Default | Read in |
| --- | --- | --- |
| `ZYG_ABORT_ON_PREVIEW` | `0` | `src/zyg_workflows/render_abort.py` |
| `ZYG_ABORT_POLL_S` | `5` | `src/zyg_workflows/render_abort.py` |
| `ZYG_ABS_PATTERN_V2` | `` | `src/zyg_workflows/geom/mesh_skeletons/abs_definition.py` |
| `ZYG_AB_PROBE_LORA` |  | `src/zyg_workflows/lora_attest/ab_probe.py` |
| `ZYG_AB_PROBE_STEPS` | `12` | `src/zyg_workflows/lora_attest/ab_probe.py` |
| `ZYG_AB_PROBE_TIMEOUT_S` | `900` | `src/zyg_workflows/lora_attest/ab_probe.py` |
| `ZYG_ACE_MAX_SECONDS` | `180` | `src/zyg_workflows/ace_step_service.py`, `src/zyg_workflows/kids_music_service/ace.py`, `src/zyg_workflows/kids_music_service/repaint.py` +1 more |
| `ZYG_ACE_STEP_CHECKPOINT` | `ace_step_1.5_turbo_aio.safetensors` | `src/zyg_workflows/ace_step_service.py`, `src/zyg_workflows/kids_music_service/base.py` |
| `ZYG_ACE_TIMEOUT_S` | `600` | `src/zyg_workflows/ace_step_service.py`, `src/zyg_workflows/kids_music_service/ace.py`, `src/zyg_workflows/kids_music_service/repaint.py` |
| `ZYG_ANCHOR_ATTR_GATE` | `1` | `src/zyg_workflows/contact_sheet_pipeline_steps/anchor_attribute_gate.py` |
| `ZYG_ANCHOR_ATTR_RETRIES` | `2` | `src/zyg_workflows/contact_sheet_pipeline_steps/anchor_attribute_gate.py` |
| `ZYG_ANCHOR_DEDUP_GATE` | `1` | `src/zyg_workflows/contact_sheet_pipeline_steps/anchor_dedup_gate.py` |
| `ZYG_ANCHOR_DEDUP_HARD` | `1` | `src/zyg_workflows/contact_sheet_pipeline_steps/anchor_dedup_gate.py` |
| `ZYG_ANCHOR_DEDUP_MAX_SIM` | `0.52` | `src/zyg_workflows/contact_sheet_pipeline_steps/anchor_dedup_gate.py` |
| `ZYG_ANCHOR_DEDUP_MAX_SIM_ARCHIVED` | `0.58` | `src/zyg_workflows/contact_sheet_pipeline_steps/anchor_dedup_gate.py` |
| `ZYG_ANCHOR_DEDUP_RETRIES` | `3` | `src/zyg_workflows/contact_sheet_pipeline_steps/anchor_dedup_gate.py` |
| `ZYG_ANCHOR_STYLE_GATE` | `1` | `src/zyg_workflows/contact_sheet_pipeline_steps/anchor_structure_gates.py` |
| `ZYG_ANCHOR_STYLE_GATE_LAPVAR` | `50` | `src/zyg_workflows/contact_sheet_pipeline_steps/anchor_identity_gates.py`, `src/zyg_workflows/contact_sheet_pipeline_steps/anchor_structure_gates.py` |
| `ZYG_ANCHOR_STYLE_GATE_LORA_SCALE` | `0.9` | `src/zyg_workflows/contact_sheet_pipeline_steps/anchor_identity_gates.py` |
| `ZYG_ANIMAL_LORA_DIR` |  | `src/zyg_workflows/paths.py` |
| `ZYG_ANIMATED_USE_FLUX` | `1` | `src/zyg_workflows/pipeline_config.py` |
| `ZYG_ANIM_DATASET_CFG` | `6.5` | `src/zyg_workflows/animated_sdxl_dataset.py` |
| `ZYG_ANIM_DATASET_DENOISE` | `0.55` | `src/zyg_workflows/animated_sdxl_dataset.py` |
| `ZYG_ANIM_DATASET_NEG` | `photorealistic, photograph, realistic, dslr, raw photo, film grain, visible skin pores, skin texture, hyperreal, blurry, low quality, deformed face, bad anatomy, extra fingers, watermark, text, oversized eyes, huge eyes, big anime eyes, bug eyes, enlarged eyes, disproportionate eyes` | `src/zyg_workflows/animated_sdxl_dataset.py` |
| `ZYG_ANIM_DATASET_STEPS` | `30` | `src/zyg_workflows/animated_sdxl_dataset.py` |
| `ZYG_ANIM_STYLE_CLAUSE` | `3D Pixar animation style, stylized 3d animated character, Disney Pixar 3d render, cel-shaded, smooth subsurface shading, natural proportional eyes, realistic eye size, clean high quality 3d character render` | `src/zyg_workflows/animated_sdxl_dataset.py` |
| `ZYG_ANIM_TILE_SCREEN` | `1` | `src/zyg_workflows/animated_sdxl_dataset.py` |
| `ZYG_ANIM_TILE_TIMEOUT` | `60` | `src/zyg_workflows/animated_sdxl_dataset.py` |
| `ZYG_ANSUR_IMPORT_DIR` | `` | `src/zyg_workflows/paths.py` |
| `ZYG_ANTHRO_GATES` | `1` | `src/zyg_workflows/geom/mesh_skeletons/anthro.py` |
| `ZYG_APISPORTS_API_KEY` | `` | `src/zyg_workflows/sports_ingest/constants.py` |
| `ZYG_ARCH_ASSIST_CLI` | `` | `src/zyg_workflows/arch_assistant/config.py` |
| `ZYG_ARCH_ASSIST_CLI_MODEL` | `sonnet` | `src/zyg_workflows/arch_assistant/config.py` |
| `ZYG_ARCH_ASSIST_CLI_OUT` | `64000` | `src/zyg_workflows/arch_assistant/config.py` |
| `ZYG_ARCH_ASSIST_CLI_TIMEOUT` | `1800` | `src/zyg_workflows/arch_assistant/config.py` |
| `ZYG_ARCH_ASSIST_EFFORT` | `medium` | `src/zyg_workflows/arch_assistant/backends.py` |
| `ZYG_ARCH_ASSIST_LOCAL` | `qwen3.6:35b-a3b` | `src/zyg_workflows/arch_assistant/config.py` |
| `ZYG_ARCH_ASSIST_LOCAL_GB` | `26` | `src/zyg_workflows/arch_assistant/config.py` |
| `ZYG_ARCH_ASSIST_LOCAL_PREDICT` | `6144` | `src/zyg_workflows/arch_assistant/config.py` |
| `ZYG_ARCH_ASSIST_MODEL` | `` | `src/zyg_workflows/arch_assistant/backends.py`, `src/zyg_workflows/arch_assistant/config.py` |
| `ZYG_ARCH_ASSIST_URL` |  | `src/zyg_workflows/arch_assistant/config.py` |
| `ZYG_ARCH_HERO` | `1` | `src/zyg_workflows/arch_assistant/jobs.py` |
| `ZYG_ARCH_MAX_CALLS` |  | `src/zyg_workflows/arch_assistant/config.py` |
| `ZYG_ARCH_PORTFOLIO_TIMEOUT` | `1800` | `src/zyg_workflows/arch_assistant_ext/blender_power/portfolio.py` |
| `ZYG_ARCH_SPEC_DIR` |  | `src/zyg_workflows/arch_assistant_ext/object_specs.py` |
| `ZYG_ARCH_SPEC_GAPS` |  | `src/zyg_workflows/arch_assistant_ext/object_specs.py` |
| `ZYG_ARCH_TURN_HEADROOM` |  | `src/zyg_workflows/arch_assistant/config.py` |
| `ZYG_ASR_PYTHON` | `` | `src/zyg_workflows/paths.py` |
| `ZYG_ATTEST_ALLOW_ZERO_STRENGTH` |  | `src/zyg_workflows/lora_attest/gate.py` |
| `ZYG_AUDIO_LICENSE_GATE` | `1` | `src/zyg_workflows/ambience_ingest.py` |
| `ZYG_AUDIO_QC_CLAP_MODEL` | `laion/clap-htsat-fused` | `src/zyg_workflows/audio_qc.py` |
| `ZYG_AUDIO_QC_CLAP_REVISION` | `` | `src/zyg_workflows/audio_qc.py` |
| `ZYG_AUDIO_QC_ENFORCE` | `1` | `src/zyg_workflows/abel_voice.py` |
| `ZYG_AUDIO_QC_LANG` | `en` | `src/zyg_workflows/audio_qc.py` |
| `ZYG_BEAT_CHAR_LIMIT` |  | `src/zyg_workflows/run_logbook/plumbing.py` |
| `ZYG_BEAT_MAP_GATE` | `1` | `src/zyg_workflows/wan_vace_service/static_clip.py` |
| `ZYG_BLENDER` | `/usr/local/bin/blender` | `src/zyg_workflows/geom/body_plates.py`, `src/zyg_workflows/geom/gnm_head.py`, `src/zyg_workflows/prop_mesh/sheet_register.py` +1 more |
| `ZYG_BONY_RELIEF` | `1` | `src/zyg_workflows/geom/mesh_skeletons/anatomy.py` |
| `ZYG_BRIEF_ASR_MIN` | `0.66` | `src/zyg_workflows/briefing_video/tts.py` |
| `ZYG_BRIEF_ASR_MODEL` | `small` | `src/zyg_workflows/briefing_video/tts.py` |
| `ZYG_BRIEF_CALM_TTS` | `1` | `src/zyg_workflows/briefing_video/tts.py` |
| `ZYG_BRIEF_EMO_ALPHA` | `0.45` | `src/zyg_workflows/briefing_video/tts.py` |
| `ZYG_BRIEF_EMO_TEXT` | `0` | `src/zyg_workflows/briefing_video/tts.py` |
| `ZYG_BRIEF_INJURIES` | `1` | `src/zyg_workflows/pipeline_sports/pipeline.py` |
| `ZYG_BRIEF_JINGLES` | `1` | `src/zyg_workflows/pipeline_sports/pipeline.py` |
| `ZYG_BRIEF_LLM_MODEL` | `qwen3.5:9b` | `src/zyg_workflows/briefing_jobs.py` |
| `ZYG_BRIEF_PARLAYS` | `1` | `src/zyg_workflows/pipeline_sports/pipeline.py` |
| `ZYG_BRIEF_PLAYER_ART` | `1` | `src/zyg_workflows/pipeline_sports/pipeline.py` |
| `ZYG_BRIEF_TEMPO` | `1.07` | `src/zyg_workflows/briefing_video/episode.py` |
| `ZYG_BRIEF_TTS_ASR_QC` | `1` | `src/zyg_workflows/briefing_video/tts.py` |
| `ZYG_BRIEF_TTS_BATCH` | `1` | `src/zyg_workflows/briefing_video/tts.py` |
| `ZYG_C2PA` | `warn` | `src/zyg_workflows/provenance_seal.py`, `src/zyg_workflows/stage_runner/delivery.py` |
| `ZYG_C2PA_CERT_CHAIN` | `~/.config/zygomatic/c2pa/signer_chain.pem` | `src/zyg_workflows/provenance_seal.py` |
| `ZYG_C2PA_KEY` | `~/.config/zygomatic/c2pa/signer.key` | `src/zyg_workflows/provenance_seal.py` |
| `ZYG_C2PA_ROOT_CERT` | `~/.config/zygomatic/c2pa/root/ca.pem` | `src/zyg_workflows/provenance_seal.py` |
| `ZYG_C2PA_TSA_URL` | `` | `src/zyg_workflows/provenance_seal.py` |
| `ZYG_CANDLE_SEED` | `20260801` | `src/zyg_workflows/candle_fx.py` |
| `ZYG_CANDLE_SPILL` | `2.2` | `src/zyg_workflows/candle_fx.py` |
| `ZYG_CANDLE_STRENGTH` | `0.30` | `src/zyg_workflows/candle_fx.py` |
| `ZYG_CELL_VLM_CLOUD` | `1` | `src/zyg_workflows/cell_vlm_judge.py` |
| `ZYG_CELL_VLM_CLOUD_MODE` | `suspicion` | `src/zyg_workflows/contact_sheet_pipeline_steps/regen_qc.py` |
| `ZYG_CELL_VLM_CLOUD_MODEL` | `claude-sonnet-4-6` | `src/zyg_workflows/cell_vlm_judge.py` |
| `ZYG_CELL_VLM_CLOUD_SIM` | `0.50` | `src/zyg_workflows/contact_sheet_pipeline_steps/regen_qc.py` |
| `ZYG_CELL_VLM_CLOUD_VIS` | `frontal,oblique` | `src/zyg_workflows/contact_sheet_pipeline_steps/regen_qc.py` |
| `ZYG_CELL_VLM_JUDGE` | `1` | `src/zyg_workflows/cell_vlm_judge.py` |
| `ZYG_CELL_VLM_KEEP_ALIVE` | `2m` | `src/zyg_workflows/cell_vlm_judge.py` |
| `ZYG_CELL_VLM_LOCAL` | `1` | `src/zyg_workflows/cell_vlm_judge.py` |
| `ZYG_CELL_VLM_LOCAL_MODEL` | `qwen3.5:9b` | `src/zyg_workflows/cell_vlm_judge.py`, `src/zyg_workflows/hand_qc_service.py` |
| `ZYG_CELL_VLM_MAX_ERRORS` | `3` | `src/zyg_workflows/cell_vlm_judge.py` |
| `ZYG_CELL_VLM_TIMEOUT` | `300` | `src/zyg_workflows/cell_vlm_judge.py` |
| `ZYG_CHARBAL_FACE_DEVICE` | `cpu` | `src/zyg_workflows/pipeline_debug/gates_charbal_detect.py` |
| `ZYG_CHAR_BRIEF` | `1` | `src/zyg_workflows/character_brief_service.py` |
| `ZYG_CHAR_BRIEF_MODEL` | `claude-sonnet-4-6` | `src/zyg_workflows/character_brief_service.py`, `src/zyg_workflows/character_photo_analysis_service.py` |
| `ZYG_CHAR_DEFAULT_MODEL_FAMILY` | `flux` | `src/zyg_workflows/pipeline_config.py` |
| `ZYG_CHAR_DRIFT_ANIMATED` | `0.45` | `src/zyg_workflows/comfy_generation_service/constants.py`, `src/zyg_workflows/pipeline_config.py` |
| `ZYG_CHAR_DRIFT_MIN` | `0.60` | `src/zyg_workflows/comfy_generation_service/constants.py`, `src/zyg_workflows/pipeline_config.py` |
| `ZYG_CHAR_DUAL_LORA_PHOTOREAL` | `0` | `src/zyg_workflows/contact_sheet_pipeline_steps/pipeline_training.py`, `src/zyg_workflows/pipeline_config.py` |
| `ZYG_CHAR_GEOM_CTRL` | `1` | `src/zyg_workflows/wan_vace_service/sequences.py`, `src/zyg_workflows/wan_vace_service/static_clip.py` |
| `ZYG_CHAR_PHOTOREAL_HYBRID_PREVIEW` | `1` | `src/zyg_workflows/pipeline_config.py` |
| `ZYG_CHAR_PHOTO_ANALYSIS` | `1` | `src/zyg_workflows/character_photo_analysis_service.py` |
| `ZYG_CHAR_PHOTO_CONSENSUS` | `1` | `src/zyg_workflows/character_photo_analysis_service.py` |
| `ZYG_CHAR_PHOTO_CONSENSUS_N` | `2` | `src/zyg_workflows/character_photo_analysis_service.py` |
| `ZYG_CHAR_PHOTO_MODEL` |  | `src/zyg_workflows/character_photo_analysis_service.py` |
| `ZYG_CHAR_PHOTO_NUM_CTX` | `8192` | `src/zyg_workflows/character_photo_analysis_service.py` |
| `ZYG_CHAR_PHOTO_NUM_PREDICT` | `1200` | `src/zyg_workflows/character_photo_analysis_service.py` |
| `ZYG_CHAR_PHOTO_OLLAMA_KEEP_ALIVE` | `0` | `src/zyg_workflows/character_photo_analysis_service.py` |
| `ZYG_CHAR_PHOTO_PREFER_OLLAMA` | `1` | `src/zyg_workflows/character_photo_analysis_service.py` |
| `ZYG_CHAR_PHOTO_VISION_MODELS` | `qwen3.5:9b,moondream:latest` | `src/zyg_workflows/character_photo_analysis_service.py` |
| `ZYG_CHATTERBOX_CFG` | `0.4` | `src/zyg_workflows/tts_service/engines.py` |
| `ZYG_CHATTERBOX_DIR` |  | `src/zyg_workflows/tts_service/engines.py`, `src/zyg_workflows/voice_studio/constants.py` |
| `ZYG_CHATTERBOX_EXAGGERATION` | `0.3` | `src/zyg_workflows/tts_service/engines.py` |
| `ZYG_CHATTERBOX_SEED` | `1672` | `src/zyg_workflows/tts_service/engines.py` |
| `ZYG_CLAUDE_CREDENTIALS` |  | `src/zyg_workflows/subscription_llm.py` |
| `ZYG_CLOSEUP_CROP` | `1` | `src/zyg_workflows/contact_sheet_pipeline/cell_regen.py`, `src/zyg_workflows/contact_sheet_pipeline_steps/cell_generation.py` |
| `ZYG_CLOSEUP_SHARPEN` | `1` | `src/zyg_workflows/contact_sheet_pipeline/angle_edit.py` |
| `ZYG_CN_CONDITIONING_SCALE` | `` | `src/zyg_workflows/character_bible_service/prompt_suffixes.py` |
| `ZYG_COMFYUI_URL` |  | `src/zyg_workflows/kids_music_service/ace.py`, `src/zyg_workflows/kids_music_service/repaint.py` |
| `ZYG_COMFY_AUTO_RESTART` | `1` | `src/zyg_workflows/comfy_generation_service/backend.py` |
| `ZYG_COMFY_CLEAR_VRAM_BETWEEN_SLOTS` | `1` | `src/zyg_workflows/comfy_generation_service/backend.py` |
| `ZYG_COMFY_CLIENT_ID` | `` | `src/zyg_workflows/_comfy_client.py`, `src/zyg_workflows/comfy_preview_watcher.py` |
| `ZYG_COMFY_FREE_GC_SEC` | `12` | `src/zyg_workflows/_comfy_client.py` |
| `ZYG_COMFY_FREE_ROUNDS` | `2` | `src/zyg_workflows/_comfy_client.py` |
| `ZYG_COMFY_GLOBAL_INTERRUPT` | `` | `src/zyg_workflows/_comfy_client.py` |
| `ZYG_COMFY_HOST` | `127.0.0.1` | `src/zyg_workflows/_comfy_client.py`, `src/zyg_workflows/comfy_offload.py`, `src/zyg_workflows/contact_sheet_pipeline/sheet_prep.py` +1 more |
| `ZYG_COMFY_IDLE_FREE_MB` | `8192` | `src/zyg_workflows/vram_manager.py` |
| `ZYG_COMFY_IDLE_FREE_RAM_MB` | `6144` | `src/zyg_workflows/vram_manager.py` |
| `ZYG_COMFY_IDLE_FREE_SEC` | `90` | `src/zyg_workflows/vram_manager.py` |
| `ZYG_COMFY_KEEP_LOADED` | `` | `src/zyg_workflows/_comfy_client.py`, `src/zyg_workflows/kids_video_service/render.py`, `src/zyg_workflows/tools/kidsmusic_repaint_spike.py` +1 more |
| `ZYG_COMFY_MAX_IDLE_RAM_MB` | `4096` | `src/zyg_workflows/_comfy_client.py` |
| `ZYG_COMFY_MODELS` | `` | `src/zyg_workflows/lora_attest/pins.py` |
| `ZYG_COMFY_PORT` | `8188` | `src/zyg_workflows/_comfy_client.py`, `src/zyg_workflows/comfy_offload.py`, `src/zyg_workflows/contact_sheet_pipeline/sheet_prep.py` +1 more |
| `ZYG_COMFY_PRIMARY` | `` | `src/zyg_workflows/comfy_generation_service/backend.py` |
| `ZYG_COMFY_RESTART_ON_STUCK` | `1` | `src/zyg_workflows/_comfy_client.py` |
| `ZYG_COMFY_ROOT` |  | `src/zyg_workflows/wardrobe_service.py` |
| `ZYG_COMFY_SERVER` |  | `src/zyg_workflows/comfy_offload.py` |
| `ZYG_COMFY_SLOT_FREE_TIMEOUT` | `60` | `src/zyg_workflows/comfy_generation_service/backend.py` |
| `ZYG_COMFY_SUBMIT_LOCK` | `1` | `src/zyg_workflows/_comfy_client.py` |
| `ZYG_COMFY_SUBMIT_LOCK_PATH` | `` | `src/zyg_workflows/_comfy_client.py` |
| `ZYG_COMFY_SUBMIT_LOCK_WAIT_S` | `` | `src/zyg_workflows/_comfy_client.py` |
| `ZYG_CONTACT_EMAIL` | `` | `src/zyg_workflows/contact.py` |
| `ZYG_CONTACT_SHEET_ANCHOR_GUIDANCE` | `2.6` | `src/zyg_workflows/contact_sheet_pipeline_steps/cell_plan.py` |
| `ZYG_CONTACT_SHEET_ANGLE_SET` | `extended` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_APPROVE_TIMEOUT` | `86400` | `src/zyg_workflows/contact_sheet_pipeline/pipeline.py` |
| `ZYG_CONTACT_SHEET_BEST_OF` | `2` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_BODY_CELL_H` | `1216` | `src/zyg_workflows/contact_sheet_pipeline/angle_edit.py` |
| `ZYG_CONTACT_SHEET_BODY_CELL_W` | `832` | `src/zyg_workflows/contact_sheet_pipeline/angle_edit.py` |
| `ZYG_CONTACT_SHEET_CANVAS_H` | `1080` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_CANVAS_W` | `1920` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_CELL_H` | `640` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_CELL_W` | `512` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_CFG` | `3.5` | `src/zyg_workflows/contact_sheet_pipeline/cell_regen.py`, `src/zyg_workflows/contact_sheet_pipeline/expansion.py`, `src/zyg_workflows/contact_sheet_pipeline/pose_locked.py` +2 more |
| `ZYG_CONTACT_SHEET_COLS` |  | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_DARK_ANCHOR_CFG` | `3.2` | `src/zyg_workflows/contact_sheet_pipeline_steps/cell_plan.py` |
| `ZYG_CONTACT_SHEET_DATASET_REVIEW` | `1` | `src/zyg_workflows/contact_sheet_pipeline_steps/pipeline_training.py` |
| `ZYG_CONTACT_SHEET_DUAL` | `1` | `src/zyg_workflows/contact_sheet_pipeline/layout.py` |
| `ZYG_CONTACT_SHEET_EXPANSION_COUNT` | `16` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_EXPANSION_H` | `1152` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_EXPANSION_MIN_SCORE` | `0.42` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_EXPANSION_W` | `768` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_EXPORT_CELL_H` | `720` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_EXPORT_CELL_W` | `640` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_FLYWHEEL` | `1` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_GUTTER` | `8` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_HAND_FIXER` | `0` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_HEAD_CELL_H` | `1152` | `src/zyg_workflows/contact_sheet_pipeline/angle_edit.py` |
| `ZYG_CONTACT_SHEET_HEAD_CELL_W` | `1024` | `src/zyg_workflows/contact_sheet_pipeline/angle_edit.py` |
| `ZYG_CONTACT_SHEET_I2I_DENOISE` | `0.48` | `src/zyg_workflows/contact_sheet_pipeline/sheet_canvas.py` |
| `ZYG_CONTACT_SHEET_IDQC` | `1` | `src/zyg_workflows/contact_sheet_pipeline/identity_qc.py`, `src/zyg_workflows/contact_sheet_pipeline_steps/pipeline_steps.py`, `src/zyg_workflows/identity_qc_service.py` |
| `ZYG_CONTACT_SHEET_IDQC_BACK_MIN_YAW` | `45` | `src/zyg_workflows/identity_qc_service.py` |
| `ZYG_CONTACT_SHEET_IDQC_EDGE_PCT` | `0.08` | `src/zyg_workflows/identity_qc_service.py` |
| `ZYG_CONTACT_SHEET_IDQC_EXCLUDE_FAILED` | `1` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_IDQC_FRONTAL_MAX_YAW` | `60` | `src/zyg_workflows/identity_qc_service.py` |
| `ZYG_CONTACT_SHEET_IDQC_FULLBODY_MAX_ROLL` | `70` | `src/zyg_workflows/identity_qc_service.py` |
| `ZYG_CONTACT_SHEET_IDQC_MAX_FACES` | `1` | `src/zyg_workflows/identity_qc_service.py` |
| `ZYG_CONTACT_SHEET_IDQC_MAX_RETRIES` | `2` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_IDQC_MAX_ROLL` | `55` | `src/zyg_workflows/identity_qc_service.py` |
| `ZYG_CONTACT_SHEET_IDQC_MIN_DET` | `0.40` | `src/zyg_workflows/identity_qc_service.py` |
| `ZYG_CONTACT_SHEET_IDQC_MISLABEL_KEEP` | `0.42` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_IDQC_OBLIQUE_MIN_YAW` | `12` | `src/zyg_workflows/identity_qc_service.py` |
| `ZYG_CONTACT_SHEET_IDQC_PROFILE_MIN_YAW` | `12` | `src/zyg_workflows/identity_qc_service.py` |
| `ZYG_CONTACT_SHEET_IDQC_REGEN_IPA_SCALE` | `0.80` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_IDQC_REGEN_MIN_SCORE` | `0.42` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_IDQC_REQUIRED` | `1` | `src/zyg_workflows/contact_sheet_pipeline_steps/pipeline_steps.py` |
| `ZYG_CONTACT_SHEET_IDQC_SHEET_MIN` | `0.30` | `src/zyg_workflows/contact_sheet_pipeline_steps/regen_qc.py` |
| `ZYG_CONTACT_SHEET_IDQC_THRESH_FRONTAL` |  | `src/zyg_workflows/identity_qc_service.py` |
| `ZYG_CONTACT_SHEET_IDQC_THRESH_FULLBODY` | `0.18` | `src/zyg_workflows/identity_qc_service.py` |
| `ZYG_CONTACT_SHEET_IDQC_THRESH_OBLIQUE` |  | `src/zyg_workflows/identity_qc_service.py` |
| `ZYG_CONTACT_SHEET_IDQC_THRESH_PROFILE` |  | `src/zyg_workflows/identity_qc_service.py` |
| `ZYG_CONTACT_SHEET_IDQC_YAW` | `1` | `src/zyg_workflows/identity_qc_service.py` |
| `ZYG_CONTACT_SHEET_INSTANTID_REGEN` | `0` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_LIBRARY_STRICT_IDS` | `1` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_LORA_TRAINING` | `1` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_MIN_CELLS` |  | `src/zyg_workflows/contact_sheet_pipeline/pose_locked.py`, `src/zyg_workflows/contact_sheet_pipeline/sheet_canvas.py`, `src/zyg_workflows/contact_sheet_pipeline_steps/sheet_finalize.py` |
| `ZYG_CONTACT_SHEET_MODE` | `auto` | `src/zyg_workflows/contact_sheet_pipeline/layout.py`, `src/zyg_workflows/contact_sheet_pipeline/pipeline.py` |
| `ZYG_CONTACT_SHEET_PER_CELL_IPA_SCALE` | `0.85` | `src/zyg_workflows/contact_sheet_pipeline_steps/cell_plan.py` |
| `ZYG_CONTACT_SHEET_PHOTO_ANCHOR` | `amateur photo on flickr in 2007, candid photograph, ` | `src/zyg_workflows/contact_sheet_pipeline_steps/cell_generation.py` |
| `ZYG_CONTACT_SHEET_POSE_CELL_H` |  | `src/zyg_workflows/contact_sheet_pipeline/pose_locked.py` |
| `ZYG_CONTACT_SHEET_POSE_CELL_W` |  | `src/zyg_workflows/contact_sheet_pipeline/pose_locked.py` |
| `ZYG_CONTACT_SHEET_POSE_CN_END` | `0.90` | `src/zyg_workflows/comfy_generation_service_steps/overrides.py` |
| `ZYG_CONTACT_SHEET_POSE_CN_STRENGTH` | `0.95` | `src/zyg_workflows/comfy_generation_service_steps/overrides.py` |
| `ZYG_CONTACT_SHEET_POSE_DIR` |  | `src/zyg_workflows/comfy_generation_service/capabilities.py` |
| `ZYG_CONTACT_SHEET_POSE_I2I_DENOISE` | `0.35` | `src/zyg_workflows/contact_sheet_pipeline/pose_locked.py` |
| `ZYG_CONTACT_SHEET_POSE_IPA_FACE_REF` | `1` | `src/zyg_workflows/contact_sheet_pipeline/pose_locked.py` |
| `ZYG_CONTACT_SHEET_POSE_IPA_SCALE` | `0.90` | `src/zyg_workflows/contact_sheet_pipeline/pose_locked.py` |
| `ZYG_CONTACT_SHEET_POSE_MAX_CELLS` | `0` | `src/zyg_workflows/contact_sheet_pipeline/pose_locked.py` |
| `ZYG_CONTACT_SHEET_POSE_PREVIEW_COLS` | `6` | `src/zyg_workflows/contact_sheet_pipeline/pose_locked.py` |
| `ZYG_CONTACT_SHEET_POSE_PREVIEW_ROWS` | `4` | `src/zyg_workflows/contact_sheet_pipeline/pose_locked.py` |
| `ZYG_CONTACT_SHEET_POSE_USE_I2I` | `1` | `src/zyg_workflows/contact_sheet_pipeline/pose_locked.py` |
| `ZYG_CONTACT_SHEET_POSE_USE_INSTANTID` | `1` | `src/zyg_workflows/contact_sheet_pipeline/pose_locked.py` |
| `ZYG_CONTACT_SHEET_QC_MIN_PASS_RATE` | `0.60` | `src/zyg_workflows/contact_sheet_pipeline_steps/pipeline_steps.py` |
| `ZYG_CONTACT_SHEET_REALISM_LORA` | `` | `src/zyg_workflows/contact_sheet_pipeline_steps/cell_plan.py` |
| `ZYG_CONTACT_SHEET_REALISM_LORA_SCALE` | `0.7` | `src/zyg_workflows/contact_sheet_pipeline_steps/cell_plan.py` |
| `ZYG_CONTACT_SHEET_REVIEW_GATE` | `0` | `src/zyg_workflows/contact_sheet_pipeline_steps/pipeline_steps.py` |
| `ZYG_CONTACT_SHEET_ROWS` |  | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_SDXL_PER_CELL` | `1` | `src/zyg_workflows/contact_sheet_pipeline/sheet_prep.py` |
| `ZYG_CONTACT_SHEET_SHEET_B_ANCHOR` | `1` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_SHEET_B_I2I_DENOISE` | `0.52` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_SHEET_B_IPA` | `1` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_SHEET_B_IPA_SCALE` | `0.72` | `src/zyg_workflows/comfy_generation_service_steps/overrides.py`, `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_STEPS` | `28` | `src/zyg_workflows/contact_sheet_pipeline/cell_regen.py`, `src/zyg_workflows/contact_sheet_pipeline/expansion.py`, `src/zyg_workflows/contact_sheet_pipeline/pose_locked.py` +2 more |
| `ZYG_CONTACT_SHEET_TPOSE_CELL_H` | `1024` | `src/zyg_workflows/contact_sheet_pipeline/angle_edit.py` |
| `ZYG_CONTACT_SHEET_TPOSE_CELL_W` | `1024` | `src/zyg_workflows/contact_sheet_pipeline/angle_edit.py` |
| `ZYG_CONTACT_SHEET_TRAIN_MIN_SCORE` | `0.32` | `src/zyg_workflows/contact_sheet_pipeline/identity_qc.py` |
| `ZYG_CONTACT_SHEET_UNET` | `flux1-dev.safetensors` | `src/zyg_workflows/contact_sheet_pipeline/cell_regen.py`, `src/zyg_workflows/contact_sheet_pipeline/expansion.py`, `src/zyg_workflows/contact_sheet_pipeline/pose_locked.py` +2 more |
| `ZYG_CONTACT_SHEET_UPSCALE_FACTOR` | `2` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_CONTACT_SHEET_VRAM_WAIT_S` | `45` | `src/zyg_workflows/contact_sheet_pipeline/pose_locked.py`, `src/zyg_workflows/contact_sheet_pipeline/sheet_canvas.py`, `src/zyg_workflows/contact_sheet_pipeline_steps/cell_plan.py` |
| `ZYG_CONTEXT_STRIDE` |  | `src/zyg_workflows/continuity_qc/models.py`, `src/zyg_workflows/vlm_report/constants.py` |
| `ZYG_CONTINUITY_DEVICE` |  | `src/zyg_workflows/continuity_qc/models.py` |
| `ZYG_CPU_CORES` |  | `src/zyg_workflows/cpu_cap.py` |
| `ZYG_CQA_ANCHOR_SEED` | `1` | `src/zyg_workflows/consistency_qa_service.py` |
| `ZYG_CQA_UNKNOWN_NOT_PASS` | `1` | `src/zyg_workflows/consistency_qa_service.py` |
| `ZYG_CREATURE_ANCHOR_SEEDS` | `3` | `src/zyg_workflows/creature_sheet_service/base.py` |
| `ZYG_CREATURE_ANGLES_LORA_SCALE` | `1.0` | `src/zyg_workflows/creature_sheet_service/comfy.py` |
| `ZYG_CREATURE_BRIEF_MODEL` | `qwen3.5:9b` | `src/zyg_workflows/creature_training_service.py` |
| `ZYG_CREATURE_CELL_PX` | `1024` | `src/zyg_workflows/creature_fx/base.py`, `src/zyg_workflows/creature_sheet_service/base.py` |
| `ZYG_CREATURE_CLIP_MAX_FRAMES` | `200` | `src/zyg_workflows/creature_identity.py` |
| `ZYG_CREATURE_CLIP_PASS_FRAC` | `0.70` | `src/zyg_workflows/creature_identity.py` |
| `ZYG_CREATURE_CLIP_STRIDE` | `8` | `src/zyg_workflows/creature_identity.py` |
| `ZYG_CREATURE_CONFORM_SEEDS` | `2` | `src/zyg_workflows/creature_sheet_service/base.py` |
| `ZYG_CREATURE_DATASETS` |  | `src/zyg_workflows/paths.py` |
| `ZYG_CREATURE_DINO` | `1` | `src/zyg_workflows/creature_identity.py` |
| `ZYG_CREATURE_DINO_HARD_FLOOR` | `0.15` | `src/zyg_workflows/creature_identity.py` |
| `ZYG_CREATURE_JUDGE_TIER` |  | `src/zyg_workflows/creature_judge.py` |
| `ZYG_CREATURE_LORA_DIR` |  | `src/zyg_workflows/paths.py` |
| `ZYG_CREATURE_MAX_REGEN` | `2` | `src/zyg_workflows/creature_sheet_service/base.py` |
| `ZYG_CREATURE_MAX_REGEN_SOFT` | `1` | `src/zyg_workflows/creature_sheet_service/base.py` |
| `ZYG_CREATURE_OUTPUTS` |  | `src/zyg_workflows/paths.py` |
| `ZYG_CREATURE_SIDE_TOWARD_BACK` |  | `src/zyg_workflows/creature_sheet_service/base.py` |
| `ZYG_CREATURE_T2I_FAMILY` |  | `src/zyg_workflows/creature_sheet_service/comfy.py` |
| `ZYG_CREATURE_TRAIN_FAMILY` |  | `src/zyg_workflows/creature_training_service.py` |
| `ZYG_CREATURE_VLM` | `1` | `src/zyg_workflows/creature_judge.py` |
| `ZYG_DEDUP_ENFORCE_POST_REGEN` | `1` | `src/zyg_workflows/contact_sheet_pipeline_steps/anchor_attribute_gate.py` |
| `ZYG_DEDUP_ENFORCE_TOL` | `0.02` | `src/zyg_workflows/contact_sheet_pipeline_steps/anchor_attribute_gate.py` |
| `ZYG_DEPTH_CKPT` | `depth_anything_v2_vits.pth` | `src/zyg_workflows/arcane_multichar.py`, `src/zyg_workflows/arcane_restyle/profiles.py` |
| `ZYG_DIARIZATION` | `1` | `src/zyg_workflows/diarize_sortformer.py` |
| `ZYG_DIAR_HOME` |  | `src/zyg_workflows/diarize_sortformer.py` |
| `ZYG_DIAR_TIMEOUT` | `3600` | `src/zyg_workflows/diarize_sortformer.py` |
| `ZYG_DINOV2_MODEL` |  | `src/zyg_workflows/continuity_qc/models.py` |
| `ZYG_DOC_FILMLOOK` |  | `src/zyg_workflows/documentary_film_look.py` |
| `ZYG_DOC_FILMLOOK_DUST` | `1` | `src/zyg_workflows/documentary_film_look.py`, `src/zyg_workflows/scholarly/stages_19_36/video_assembly.py` |
| `ZYG_DOC_FILMLOOK_GRAIN` | `0` | `src/zyg_workflows/documentary_film_look.py`, `src/zyg_workflows/scholarly/stages_19_36/video_assembly.py` |
| `ZYG_DRIFT_THRESHOLD` | `0.72` | `src/zyg_workflows/consistency_qa_service.py` |
| `ZYG_DRIFT_THRESHOLD_HIST` | `0.60` | `src/zyg_workflows/consistency_qa_service.py` |
| `ZYG_ERA_GATE_NO_LOCAL` | `0` | `src/zyg_workflows/era_gate/judge.py` |
| `ZYG_EYE_CLOSED_EAR` | `0.15` | `src/zyg_workflows/eye_openness.py` |
| `ZYG_EYE_OPEN_EAR` | `0.25` | `src/zyg_workflows/eye_openness.py` |
| `ZYG_FACE_EDGE_CACHE` | `1` | `src/zyg_workflows/geom/form/curvature/topology.py` |
| `ZYG_FACE_RESTORE_ID_MAXFRAMES` | `96` | `src/zyg_workflows/wan_face_restore.py` |
| `ZYG_FACE_RESTORE_ID_STRIDE` | `8` | `src/zyg_workflows/wan_face_restore.py` |
| `ZYG_FACE_RESTORE_REQUIRE_GAIN` | `0` | `src/zyg_workflows/wan_face_restore.py` |
| `ZYG_FACE_YOLO_PATH` |  | `src/zyg_workflows/char_state_service/preview_qa.py` |
| `ZYG_FD_PORE_DENOISE_CAP` | `0.30` | `src/zyg_workflows/comfy_generation_service_steps/graph_config.py` |
| `ZYG_FFMPEG` | `/usr/bin/ffmpeg` | `src/zyg_workflows/vfx_analyzer/constants.py` |
| `ZYG_FFPROBE` | `/usr/bin/ffprobe` | `src/zyg_workflows/vfx_analyzer/constants.py` |
| `ZYG_FLUX_CFG_START_FRAC` | `0.18` | `src/zyg_workflows/contact_sheet_pipeline_steps/cell_generation.py` |
| `ZYG_FLUX_FILL_UNET` | `flux1-fill-dev.safetensors` | `src/zyg_workflows/comfy_generation_service/hand_fixer.py` |
| `ZYG_FLUX_PROMPT_MAX_CHARS` | `2000` | `src/zyg_workflows/comfy_generation_service/flux_graph.py`, `src/zyg_workflows/comfy_generation_service/prompts.py`, `src/zyg_workflows/comfy_generation_service_steps/preflight.py` |
| `ZYG_FLUX_RENDERS` | `` | `src/zyg_workflows/licence_provenance.py` |
| `ZYG_FLUX_STYLE_LORA` | `0` | `src/zyg_workflows/pipeline_config.py` |
| `ZYG_FLUX_UNION_CONTROLNET` | `FLUX.1-dev-ControlNet-Union-Pro.safetensors` | `src/zyg_workflows/comfy_generation_service/capabilities.py` |
| `ZYG_FORCE_FLUX_LOCAL` | `` | `src/zyg_workflows/scholarly/stages_37_54.py`, `src/zyg_workflows/video_stages/stage_02_images.py` |
| `ZYG_FORM_ANGLES_STRICT` | `1` | `src/zyg_workflows/geom/form/angles/base.py` |
| `ZYG_GDINO_CONFIG` |  | `src/zyg_workflows/continuity_qc/models.py` |
| `ZYG_GDINO_WEIGHTS` |  | `src/zyg_workflows/continuity_qc/models.py` |
| `ZYG_GNM_REPO` |  | `src/zyg_workflows/paths.py` |
| `ZYG_GPU_LOCK` |  | `src/zyg_workflows/paths.py` |
| `ZYG_HANDS_BACKEND` |  | `src/zyg_workflows/hand_qc_service.py` |
| `ZYG_HAND_FIXER` | `1` | `src/zyg_workflows/comfy_generation_service/hand_fixer.py` |
| `ZYG_HAND_FIXER_ATTEMPTS` | `2` | `src/zyg_workflows/comfy_generation_service_steps/submit.py` |
| `ZYG_HAND_FIXER_CROP_CTX` | `2.2` | `src/zyg_workflows/comfy_generation_service/hand_fixer.py` |
| `ZYG_HAND_FIXER_CROP_PX` | `1024` | `src/zyg_workflows/comfy_generation_service/hand_fixer.py` |
| `ZYG_HAND_FIXER_DENOISE` | `1.0` | `src/zyg_workflows/comfy_generation_service_steps/submit.py` |
| `ZYG_HAND_FIXER_ENGINE` | `qwen` | `src/zyg_workflows/comfy_generation_service_steps/submit.py` |
| `ZYG_HAND_FIXER_GUIDANCE` | `30` | `src/zyg_workflows/comfy_generation_service/hand_fixer.py` |
| `ZYG_HAND_FIXER_MAX_BOXES` | `4` | `src/zyg_workflows/comfy_generation_service/hand_fixer.py` |
| `ZYG_HAND_FIXER_MAX_BOX_PCT` | `12` | `src/zyg_workflows/comfy_generation_service/hand_fixer.py` |
| `ZYG_HAND_FIXER_MAX_COLOR_DELTA` | `55` | `src/zyg_workflows/comfy_generation_service/hand_fixer.py` |
| `ZYG_HAND_FIXER_QWEN_CFG` | `2.5` | `src/zyg_workflows/comfy_generation_service_steps/submit.py` |
| `ZYG_HAND_FIXER_SKIP_CLEAN` | `0.9` | `src/zyg_workflows/comfy_generation_service/hand_fixer.py` |
| `ZYG_HAND_FIXER_STEPS` | `20` | `src/zyg_workflows/comfy_generation_service/hand_fixer.py` |
| `ZYG_HAND_FIXER_YOLO_CONF` | `0.35` | `src/zyg_workflows/hand_qc_service.py` |
| `ZYG_HAND_OOD_DIST_THRESHOLD` | `` | `src/zyg_workflows/hand_qc_service.py` |
| `ZYG_HAND_OOD_K` | `5` | `src/zyg_workflows/hand_qc_service.py` |
| `ZYG_HAND_OOD_SCORE_CAP` | `0.85` | `src/zyg_workflows/hand_qc_service.py` |
| `ZYG_HAND_QC_STRICT` | `0.5` | `src/zyg_workflows/scene_still_helpers.py` |
| `ZYG_HAND_VLM_CB_COOLDOWN_S` | `600` | `src/zyg_workflows/hand_qc_service.py` |
| `ZYG_HAND_VLM_CB_FAILS` | `2` | `src/zyg_workflows/hand_qc_service.py` |
| `ZYG_HAND_VLM_KEEP_ALIVE` | `5m` | `src/zyg_workflows/hand_qc_service.py` |
| `ZYG_HAND_VLM_MAX_CROPS` | `3` | `src/zyg_workflows/hand_qc_service.py` |
| `ZYG_HAND_VLM_MODEL` | `qwen3.5:9b` | `src/zyg_workflows/animated_sdxl_dataset.py`, `src/zyg_workflows/hand_qc_service.py` |
| `ZYG_HAND_VLM_TIMEOUT_S` | `90` | `src/zyg_workflows/hand_qc_service.py` |
| `ZYG_HAND_YOLO_PATH` |  | `src/zyg_workflows/char_state_service/preview_qa.py` |
| `ZYG_HERITAGE_PHRASING` | `features` | `src/zyg_workflows/character_bible_service/prompt_identity.py` |
| `ZYG_HF_REVISION` | `` | `src/zyg_workflows/comfy_generation_service/constants.py`, `src/zyg_workflows/continuity_qc/models.py`, `src/zyg_workflows/creature_identity.py` +3 more |
| `ZYG_HIDREAM_CKPT` | `hidream_o1_image_dev_fp8_scaled.safetensors` | `src/zyg_workflows/ltx_hidream_service.py` |
| `ZYG_HIDREAM_NOISE_SCALE` | `7.6` | `src/zyg_workflows/ltx_hidream_service.py` |
| `ZYG_HIDREAM_STEPS` | `28` | `src/zyg_workflows/ltx_hidream_service.py` |
| `ZYG_HOME` | `` | `src/zyg_workflows/speaker_verify_worker.py`, `src/zyg_workflows/tools/gem_capture.py` |
| `ZYG_ICT_REPO` |  | `src/zyg_workflows/paths.py` |
| `ZYG_IDENTITY_BACKEND` | `facenet` | `src/zyg_workflows/identity_bank/embedding.py` |
| `ZYG_IDENTITY_CLIP` | `1` | `src/zyg_workflows/identity_bank/clip.py` |
| `ZYG_IDENTITY_CLIP_FLOOR_DINOV2` | `0.50` | `src/zyg_workflows/identity_bank/clip.py` |
| `ZYG_IDENTITY_CLIP_FLOOR_FACENET` | `0.42` | `src/zyg_workflows/identity_bank/clip.py` |
| `ZYG_IDENTITY_CLIP_MAX_FRAMES` | `400` | `src/zyg_workflows/identity_bank/clip.py` |
| `ZYG_IDENTITY_CLIP_MIN_FOUND` | `8` | `src/zyg_workflows/identity_bank/clip.py` |
| `ZYG_IDENTITY_CLIP_MODE` | `perframe` | `src/zyg_workflows/identity_bank/clip.py` |
| `ZYG_IDENTITY_CLIP_PASS_FRAC` | `0.70` | `src/zyg_workflows/identity_bank/clip.py` |
| `ZYG_IDENTITY_CLIP_SPREAD_ALARM` | `0.35` | `src/zyg_workflows/identity_bank/clip.py` |
| `ZYG_IDENTITY_CLIP_STRIDE` | `4` | `src/zyg_workflows/identity_bank/clip.py` |
| `ZYG_IDENTITY_DEVICE` | `cpu` | `src/zyg_workflows/identity_bank/embedding.py` |
| `ZYG_IDENTITY_FACE_MARGIN` | `0.45` | `src/zyg_workflows/identity_bank/clip.py` |
| `ZYG_IDENTITY_FLOOR_DINOV2` | `0.50` | `src/zyg_workflows/identity_bank/embedding.py` |
| `ZYG_IDENTITY_FLOOR_FACENET` | `0.35` | `src/zyg_workflows/identity_bank/embedding.py` |
| `ZYG_IDENTITY_NEG_ALL_RENDERS` | `1` | `src/zyg_workflows/comfy_generation_service/prompts.py` |
| `ZYG_IDENTITY_RATCHET_DELTA` | `-0.03` | `src/zyg_workflows/identity_bank/embedding.py` |
| `ZYG_IDENTITY_RATCHET_MIN_RENDERS` | `4` | `src/zyg_workflows/identity_bank/embedding.py` |
| `ZYG_IDENTITY_SPREAD_ALARM` | `0.20` | `src/zyg_workflows/identity_bank/embedding.py` |
| `ZYG_IDENTITY_Z_FLOOR` | `-2.5` | `src/zyg_workflows/identity_bank/embedding.py` |
| `ZYG_IDENTITY_Z_MIN_BANK` | `5` | `src/zyg_workflows/identity_bank/embedding.py` |
| `ZYG_IDENTITY_Z_MIN_STD` | `0.02` | `src/zyg_workflows/identity_bank/embedding.py` |
| `ZYG_IDQC_DRIFT_GATE` | `1` | `src/zyg_workflows/contact_sheet_pipeline_steps/dataset_qc.py` |
| `ZYG_IDQC_DRIFT_WEAK_CEIL` | `0.48` | `src/zyg_workflows/contact_sheet_pipeline_steps/dataset_qc.py` |
| `ZYG_IDQC_INSIGHTFACE_ROOT` |  | `src/zyg_workflows/identity_qc_service.py` |
| `ZYG_IDQC_NOFACE_ABORT_FRAC` | `0.30` | `src/zyg_workflows/contact_sheet_pipeline_steps/sheet_finalize.py` |
| `ZYG_IDQC_PACK` | `auraface` | `src/zyg_workflows/identity_qc_service.py` |
| `ZYG_IDQC_PYTHON` |  | `src/zyg_workflows/identity_qc_service.py` |
| `ZYG_IMG2IMG_MIN_VRAM_GB` | `4.0` | `src/zyg_workflows/storyteller/stage_035_backend.py` |
| `ZYG_INDEXTTS_DIR` |  | `src/zyg_workflows/paths.py` |
| `ZYG_INDEXTTS_EMO_ALPHA` | `0.6` | `src/zyg_workflows/tts_service/engines.py` |
| `ZYG_INDEXTTS_EMO_TEXT` | `1` | `src/zyg_workflows/tts_service/engines.py` |
| `ZYG_INDEXTTS_MIN_VRAM_MB` | `21000` | `src/zyg_workflows/voice_ext/tts.py` |
| `ZYG_INDEXTTS_SEED` | `1672` | `src/zyg_workflows/tts_service/asr.py`, `src/zyg_workflows/tts_service/engines.py` |
| `ZYG_INFLIGHT_DIR` | `` | `src/zyg_workflows/kids_series_common/jobs.py` |
| `ZYG_INK_AUTO_BLUR` | `1` | `src/zyg_workflows/ink_fx/tunables.py` |
| `ZYG_INK_SAM2` | `1` | `src/zyg_workflows/ink_fx/tunables.py` |
| `ZYG_IPADAPTER_SCALE` | `0.65` | `src/zyg_workflows/comfy_generation_service/constants.py` |
| `ZYG_KB_MAX_WORKERS` | `8` | `src/zyg_workflows/scholarly/stages_19_36/video_assembly.py`, `src/zyg_workflows/storyteller/stages_03_05_tts_assembly.py` |
| `ZYG_KIDSMUSIC_A2A` | `1` | `src/zyg_workflows/kids_music_service/run.py` |
| `ZYG_KIDSMUSIC_A2A_DENOISE` | `0.45` | `src/zyg_workflows/kids_music_service/base.py` |
| `ZYG_KIDSMUSIC_A2A_LADDER` | `0.45,0.55,0.65` | `src/zyg_workflows/kids_music_service/base.py` |
| `ZYG_KIDSMUSIC_ACE_MODE` | `` | `src/zyg_workflows/kids_music_service/run_ace.py` |
| `ZYG_KIDSMUSIC_ACE_STEPS` | `0` | `src/zyg_workflows/kids_music_service/base.py` |
| `ZYG_KIDSMUSIC_BARE_ASR` | `1` | `src/zyg_workflows/vocal_analysis.py` |
| `ZYG_KIDSMUSIC_CANDIDATES` | `48` | `src/zyg_workflows/kids_music_service/run.py` |
| `ZYG_KIDSMUSIC_CLEAR_SHARE_MIN` | `0.8` | `src/zyg_workflows/kids_music_service/base.py` |
| `ZYG_KIDSMUSIC_KEEP_TAKES` | `` | `src/zyg_workflows/kids_music_service/run_deliver.py` |
| `ZYG_KIDSMUSIC_LLM` | `qwen3.5:9b` | `src/zyg_workflows/kids_llm.py`, `src/zyg_workflows/kids_music_service/lyrics.py`, `src/zyg_workflows/kids_series_people.py` +1 more |
| `ZYG_KIDSMUSIC_LLM_BACKEND` | `subscription` | `src/zyg_workflows/kids_llm.py` |
| `ZYG_KIDSMUSIC_MIX_MARGIN_DB` | `4.0` | `src/zyg_workflows/kids_music_service/base.py` |
| `ZYG_KIDSMUSIC_NEG` | `1` | `src/zyg_workflows/kids_music_service/ace.py` |
| `ZYG_KIDSMUSIC_OPUS_MODEL` | `` | `src/zyg_workflows/kids_llm.py` |
| `ZYG_KIDSMUSIC_OPUS_TIMEOUT` | `600` | `src/zyg_workflows/kids_llm.py` |
| `ZYG_KIDSMUSIC_REPAINT_DENOISE` | `0.7` | `src/zyg_workflows/kids_music_service/repaint.py` |
| `ZYG_KIDSMUSIC_REPAIR` | `1` | `src/zyg_workflows/kids_music_service/run_ace.py` |
| `ZYG_KIDSMUSIC_REPAIR_BUDGET_S` | `360` | `src/zyg_workflows/kids_music_service/repaint.py`, `src/zyg_workflows/kids_music_service/run_ace.py` |
| `ZYG_KIDSMUSIC_REPAIR_WINDOWS` | `3` | `src/zyg_workflows/kids_music_service/repaint.py` |
| `ZYG_KIDSMUSIC_SF2` |  | `src/zyg_workflows/kids_music_service/base.py` |
| `ZYG_KIDSMUSIC_SINGER_ENFORCE` | `1` | `src/zyg_workflows/kids_music_service/singer.py`, `src/zyg_workflows/tools/kidsmusic_male_octave_bench.py`, `src/zyg_workflows/tools/redtrain_male_fallback.py` +4 more |
| `ZYG_KIDSMUSIC_SINGER_RETRIES` | `` | `src/zyg_workflows/kids_music_service/run_ace.py` |
| `ZYG_KIDSMUSIC_TAIL_WARN_S` | `2.5` | `src/zyg_workflows/kids_music_service/measure.py` |
| `ZYG_KIDSMUSIC_TAKES` | `1` | `src/zyg_workflows/kids_music_service/run_ace.py` |
| `ZYG_KIDSMUSIC_VC` | `1` | `src/zyg_workflows/voice_conversion.py` |
| `ZYG_KIDSMUSIC_VOCAL_DB` | `-25` | `src/zyg_workflows/kids_music_service/singer.py` |
| `ZYG_KIDSMUSIC_VOICE_BUDGET_S` | `900` | `src/zyg_workflows/kids_music_service/run_ace.py` |
| `ZYG_KIDSMUSIC_VOICE_REVIEW` | `1` | `src/zyg_workflows/kids_music_service/run_ace.py` |
| `ZYG_KIDSVIDEO_ABSORB_S` | `1.0` | `src/zyg_workflows/kids_video_service/constants.py` |
| `ZYG_KIDSVIDEO_CANDIDATES` | `2` | `src/zyg_workflows/kids_video_service/screen.py` |
| `ZYG_KIDSVIDEO_CARTOON_MIN` | `0.75` | `src/zyg_workflows/kids_video_service/constants.py` |
| `ZYG_KIDSVIDEO_CFG` |  | `src/zyg_workflows/kids_video_service/constants.py` |
| `ZYG_KIDSVIDEO_CLIP_S` | `5` | `src/zyg_workflows/kids_video_service/constants.py` |
| `ZYG_KIDSVIDEO_CPU_ENCODE` | `` | `src/zyg_workflows/kids_video_service/motion.py` |
| `ZYG_KIDSVIDEO_ETA_S` |  | `src/zyg_workflows/kids_video_service/constants.py` |
| `ZYG_KIDSVIDEO_FAMILY` | `hidream` | `src/zyg_workflows/kids_video_service/constants.py` |
| `ZYG_KIDSVIDEO_FAST` | `1` | `src/zyg_workflows/kids_video_service/constants.py` |
| `ZYG_KIDSVIDEO_FPS` | `24` | `src/zyg_workflows/kids_video_service/constants.py` |
| `ZYG_KIDSVIDEO_H` | `864` | `src/zyg_workflows/kids_video_service/constants.py` |
| `ZYG_KIDSVIDEO_IDEA_BATCH` | `10` | `src/zyg_workflows/kids_video_service/ideas.py` |
| `ZYG_KIDSVIDEO_IDEA_BATCH_OPUS` | `` | `src/zyg_workflows/kids_video_service/ideas.py` |
| `ZYG_KIDSVIDEO_JOY_MIN` | `0.60` | `src/zyg_workflows/kids_video_service/constants.py` |
| `ZYG_KIDSVIDEO_KEEP_VRAM` | `` | `src/zyg_workflows/kids_video_service/comfy.py` |
| `ZYG_KIDSVIDEO_LTX_ETA_S` | `5.96` | `src/zyg_workflows/kids_video_service/motion.py` |
| `ZYG_KIDSVIDEO_MAX_IMAGES` | `120` | `src/zyg_workflows/kids_video_service/constants.py` |
| `ZYG_KIDSVIDEO_MAX_SLOT_S` |  | `src/zyg_workflows/kids_video_service/constants.py` |
| `ZYG_KIDSVIDEO_MIN_SLOT_S` |  | `src/zyg_workflows/kids_video_service/constants.py` |
| `ZYG_KIDSVIDEO_OCR_AREA` | `0.004` | `src/zyg_workflows/kids_video_service/constants.py` |
| `ZYG_KIDSVIDEO_PER_5S` |  | `src/zyg_workflows/kids_video_service/constants.py` |
| `ZYG_KIDSVIDEO_PULSE` | `0.015` | `src/zyg_workflows/kids_video_service/constants.py` |
| `ZYG_KIDSVIDEO_SCREEN` | `1` | `src/zyg_workflows/kids_video_service/screen.py` |
| `ZYG_KIDSVIDEO_SCREEN_LLM` | `qwen3.5:9b` | `src/zyg_workflows/kids_video_service/screen.py` |
| `ZYG_KIDSVIDEO_SCREEN_PX` | `640` | `src/zyg_workflows/kids_video_service/screen.py` |
| `ZYG_KIDSVIDEO_STEPS` |  | `src/zyg_workflows/kids_video_service/constants.py` |
| `ZYG_KIDSVIDEO_VRAM_WAIT_S` | `120` | `src/zyg_workflows/kids_video_service/comfy.py` |
| `ZYG_KIDSVIDEO_W` | `1536` | `src/zyg_workflows/kids_video_service/constants.py` |
| `ZYG_KIDSVIDEO_ZOOM` | `0.07` | `src/zyg_workflows/kids_video_service/constants.py` |
| `ZYG_KIDS_DUCKS_ROUNDS` | `` | `src/zyg_workflows/pipeline_kids_ducks.py` |
| `ZYG_KIDS_HIDREAM_LTX` | `1` | `src/zyg_workflows/kids_series_common/visuals.py` |
| `ZYG_KIDS_WAN_LIGHTNING` | `` | `src/zyg_workflows/kids_series_common/visuals.py` |
| `ZYG_KLEIN_ANCHOR_CFG` | `4.0` | `src/zyg_workflows/contact_sheet_pipeline_steps/cell_generation.py`, `src/zyg_workflows/creature_sheet_service/comfy.py` |
| `ZYG_KLEIN_CLIP` | `` | `src/zyg_workflows/comfy_generation_service/capabilities.py` |
| `ZYG_KLEIN_CONTROL_LORA` | `` | `src/zyg_workflows/comfy_generation_service/capabilities.py` |
| `ZYG_KLEIN_CONTROL_LORA_SCALE` | `1.0` | `src/zyg_workflows/comfy_generation_service/capabilities.py` |
| `ZYG_KLEIN_DIFFUSERS_DIR` |  | `src/zyg_workflows/lora_trainer_service/model_paths.py` |
| `ZYG_KLEIN_DISTILLED` | `0` | `src/zyg_workflows/comfy_generation_service/capabilities.py` |
| `ZYG_KLEIN_POSE_DENOISE` | `0.62` | `src/zyg_workflows/comfy_generation_service_steps/overrides.py` |
| `ZYG_KLEIN_REFCONTROL_ORDER` | `depth_first` | `src/zyg_workflows/comfy_generation_service_steps/overrides.py` |
| `ZYG_KLEIN_T2I_UNET` | `` | `src/zyg_workflows/comfy_generation_service/capabilities.py` |
| `ZYG_KLEIN_VAE` | `` | `src/zyg_workflows/comfy_generation_service/capabilities.py` |
| `ZYG_KYUTAI_REVISION` | `main` | `src/zyg_workflows/voice_harvest_kyutai.py` |
| `ZYG_LIBRARY_GATE_DECLINED` | `1` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_LICENCE_GATE` | `` | `src/zyg_workflows/lipsync_service.py` |
| `ZYG_LICENCE_TERRITORY` | `EU` | `src/zyg_workflows/licence_provenance.py` |
| `ZYG_LIPSYNC_STEPS` | `20` | `src/zyg_workflows/lipsync_service.py` |
| `ZYG_LIPSYNC_TIMEOUT_S` | `3600` | `src/zyg_workflows/lipsync_service.py` |
| `ZYG_LOGBOOK_DIR` |  | `src/zyg_workflows/run_logbook/plumbing.py` |
| `ZYG_LORA_ALPHA` |  | `src/zyg_workflows/lora_trainer_service/st_config_writers.py` |
| `ZYG_LORA_ATTEST` | `` | `src/zyg_workflows/lora_attest/gate.py` |
| `ZYG_LORA_CAPTION_DROPOUT` | `0.10` | `src/zyg_workflows/lora_trainer_service/st_config_writers.py` |
| `ZYG_LORA_CAPTION_IDENTITY` | `0` | `src/zyg_workflows/contact_sheet_pipeline/captions.py` |
| `ZYG_LORA_CAPTION_PREVIEWS` | `0` | `src/zyg_workflows/lora_trainer_service/st_config.py` |
| `ZYG_LORA_CLEAN_CACHES` |  | `src/zyg_workflows/lora_trainer_service/config_support.py` |
| `ZYG_LORA_EPOCHS` | `26` | `src/zyg_workflows/lora_trainer_service/service.py`, `src/zyg_workflows/studio_ext_server/char_run.py` |
| `ZYG_LORA_EPOCH_SCALED` | `1` | `src/zyg_workflows/lora_trainer_service/service.py` |
| `ZYG_LORA_KEEP_CHECKPOINTS` |  | `src/zyg_workflows/lora_trainer_service/config_support.py` |
| `ZYG_LORA_LEGACY_DIR_FALLBACK` | `1` | `src/zyg_workflows/lora_trainer_service/helpers.py` |
| `ZYG_LORA_MAX_STEPS` | `1800` | `src/zyg_workflows/lora_trainer_service/model_paths.py` |
| `ZYG_LORA_MIN_STEPS` | `900` | `src/zyg_workflows/lora_trainer_service/model_paths.py` |
| `ZYG_LORA_OUTPUT_ROOT` | `` | `src/zyg_workflows/licence_provenance.py` |
| `ZYG_LORA_PIPELINE_WAIT_S` | `5400` | `src/zyg_workflows/storyteller/stage_01_character_prep.py` |
| `ZYG_LORA_RANK` | `64` | `src/zyg_workflows/lora_trainer_service/st_config_writers.py` |
| `ZYG_LORA_REFINE_STEPS` | `400` | `src/zyg_workflows/char_state_service/lora_training.py` |
| `ZYG_LORA_START_SIGNAL_REFUSAL` | `1` | `src/zyg_workflows/lora_trainer_service/job_state.py` |
| `ZYG_LORA_STATUS_FAMILY_STRICT` | `1` | `src/zyg_workflows/lora_trainer_service/service.py` |
| `ZYG_LORA_STATUS_SAVE_INTERVAL_S` | `15` | `src/zyg_workflows/lora_trainer_service/model_paths.py` |
| `ZYG_LORA_TIMEOUT_SEC` |  | `src/zyg_workflows/animal_training_service.py`, `src/zyg_workflows/char_state_service/lora_training.py` |
| `ZYG_LORA_TRAIN_RES` | `1024` | `src/zyg_workflows/lora_trainer_service/st_config_writers.py` |
| `ZYG_LORA_TRAIN_STEPS` | `1200` | `src/zyg_workflows/animal_training_service.py`, `src/zyg_workflows/char_state_service/lora_training.py`, `src/zyg_workflows/lora_trainer_service/model_paths.py` |
| `ZYG_LORA_VRAM_MIN_GB` |  | `src/zyg_workflows/lora_trainer_service/service.py` |
| `ZYG_LORA_VRAM_WAIT_S` | `180` | `src/zyg_workflows/lora_trainer_service/service.py` |
| `ZYG_LTX_ASPECT` | `16:9 (Widescreen)` | `src/zyg_workflows/ltx_hidream_service.py` |
| `ZYG_LTX_COMFY_ROOT` |  | `src/zyg_workflows/paths.py` |
| `ZYG_LTX_COMFY_URL` |  | `src/zyg_workflows/paths.py` |
| `ZYG_LTX_MEGAPIXELS` | `0.9` | `src/zyg_workflows/ltx_hidream_service.py` |
| `ZYG_LTX_UNET` | `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` | `src/zyg_workflows/ltx_hidream_service.py` |
| `ZYG_LYRIC_ASR_MODEL` | `large-v3` | `src/zyg_workflows/tools/lyric_align_worker.py` |
| `ZYG_LYRIC_ASR_PY` |  | `src/zyg_workflows/vocal_analysis.py` |
| `ZYG_MAINT_FLAG` |  | `src/zyg_workflows/voice_studio/bake.py` |
| `ZYG_MANIFEST_SHA256` | `1` | `src/zyg_workflows/pipeline_debug/run_report.py` |
| `ZYG_MANIFEST_SHA256_MAX_MB` | `32000` | `src/zyg_workflows/pipeline_debug/run_report.py` |
| `ZYG_MASK_GATE` | `1` | `src/zyg_workflows/wan_vace_service/static_clip.py` |
| `ZYG_MASK_MAX_WHITE` | `0.86` | `src/zyg_workflows/run_logbook/recording.py`, `src/zyg_workflows/wan_vace_service/masks.py` |
| `ZYG_MASTER_SHEET_PARTS_COUNT` | `1` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_MEDUSA_CAPTION_MODEL` | `qwen3.5:9b` | `src/zyg_workflows/medusa_model_jobs.py` |
| `ZYG_MEDUSA_CHAR_DATASET_ROOT` |  | `src/zyg_workflows/medusa_pipeline.py` |
| `ZYG_MEDUSA_CHAR_OUTPUT_ROOT` |  | `src/zyg_workflows/medusa_pipeline.py` |
| `ZYG_MEDUSA_MASK_CONF` | `0.5` | `src/zyg_workflows/medusa_body_mask.py` |
| `ZYG_MEDUSA_MASK_FEATHER_PX` | `8` | `src/zyg_workflows/medusa_body_mask.py` |
| `ZYG_MEDUSA_MASK_GPU` | `1` | `src/zyg_workflows/medusa_body_mask.py` |
| `ZYG_MEDUSA_MASK_GPU_MIN_FREE_GB` | `4` | `src/zyg_workflows/medusa_body_mask.py` |
| `ZYG_MEDUSA_MASK_MAX_FACES` | `5` | `src/zyg_workflows/medusa_body_mask.py` |
| `ZYG_MEDUSA_MASK_MAX_FRACTION` | `0.15` | `src/zyg_workflows/medusa_body_mask.py` |
| `ZYG_MEDUSA_MASK_PAD_DOWN` | `0.18` | `src/zyg_workflows/medusa_body_mask.py` |
| `ZYG_MEDUSA_MASK_PAD_UP` | `0.40` | `src/zyg_workflows/medusa_body_mask.py` |
| `ZYG_MEDUSA_MASK_PAD_X` | `0.28` | `src/zyg_workflows/medusa_body_mask.py` |
| `ZYG_MEDUSA_MASK_VERIFY_ROUNDS` | `3` | `src/zyg_workflows/medusa_body_mask.py` |
| `ZYG_MEDUSA_MASK_VERIFY_SCORE` | `0.40` | `src/zyg_workflows/medusa_body_mask.py` |
| `ZYG_MEDUSA_MODEL_DATASET_ROOT` |  | `src/zyg_workflows/paths.py` |
| `ZYG_MEDUSA_MODEL_OUTPUT_ROOT` |  | `src/zyg_workflows/paths.py` |
| `ZYG_MEDUSA_RUNTIME_DIR` |  | `src/zyg_workflows/paths.py` |
| `ZYG_MEDUSA_SAMPLE_PX` | `1024` | `src/zyg_workflows/medusa_model_jobs.py` |
| `ZYG_MEDUSA_SHEET_BLUR_MIN` | `55` | `src/zyg_workflows/medusa_sheet_service/constants.py` |
| `ZYG_MEDUSA_SHEET_CELL_PX` | `256` | `src/zyg_workflows/medusa_sheet_service/constants.py` |
| `ZYG_MEDUSA_SHEET_COLS` | `8` | `src/zyg_workflows/medusa_sheet_service/constants.py` |
| `ZYG_MEDUSA_SHEET_DETECTORS` |  | `src/zyg_workflows/medusa_sheet_service/constants.py` |
| `ZYG_MEDUSA_SHEET_DUPE_HAMMING` | `4` | `src/zyg_workflows/medusa_sheet_service/constants.py` |
| `ZYG_MEDUSA_SHEET_MIN_EDGE` | `384` | `src/zyg_workflows/medusa_sheet_service/constants.py` |
| `ZYG_MEDUSA_SHEET_ROWS` | `6` | `src/zyg_workflows/medusa_sheet_service/constants.py` |
| `ZYG_MEDUSA_SHEET_WORKERS` | `4` | `src/zyg_workflows/medusa_sheet_service/constants.py` |
| `ZYG_METRICS_RUNTIME_DIR` |  | `src/zyg_workflows/paths.py` |
| `ZYG_MODELS_DIR` | `` | `src/zyg_workflows/speaker_verify_worker.py`, `src/zyg_workflows/tools/gem_capture.py` |
| `ZYG_MODEL_LICENCES` |  | `src/zyg_workflows/licence_provenance.py` |
| `ZYG_MODEL_PINS` |  | `src/zyg_workflows/lora_attest/constants.py` |
| `ZYG_MP_CPU_GL` | `1` | `src/zyg_workflows/anatomy_qc/runtime.py` |
| `ZYG_MP_EGL_VENDOR` | `/usr/share/glvnd/egl_vendor.d/50_mesa.json` | `src/zyg_workflows/anatomy_qc/runtime.py` |
| `ZYG_MP_MODEL_DIR` |  | `src/zyg_workflows/paths.py` |
| `ZYG_MP_STRICT_COUNT` | `0` | `src/zyg_workflows/anatomy_qc/constants.py` |
| `ZYG_MP_TILE_GRIDS` | `2,3` | `src/zyg_workflows/anatomy_qc/hands.py` |
| `ZYG_MURCH_LLM_MODEL` | `qwen3.5:9b` | `src/zyg_workflows/murch_engine/base.py` |
| `ZYG_NATIVE_FPS` |  | `src/zyg_workflows/vlm_report/constants.py` |
| `ZYG_NEG_ALLOW_FACE_MOTION` | `0` | `src/zyg_workflows/wan_vace_service/base.py` |
| `ZYG_NO_DELIVERY` |  | `src/zyg_workflows/stage_runner/delivery.py` |
| `ZYG_ODDS_API_KEY` | `` | `src/zyg_workflows/sports_ingest/constants.py` |
| `ZYG_OLLAMA_HOST` |  | `src/zyg_workflows/animated_sdxl_dataset.py`, `src/zyg_workflows/hand_qc_service.py` |
| `ZYG_PG_DSN` |  | `src/zyg_workflows/pgdb.py` |
| `ZYG_PHOTOREAL_FLUX_DATASET` | `0` | `src/zyg_workflows/blender_character_service.py` |
| `ZYG_PLANS_DIR` |  | `src/zyg_workflows/arch_assistant_ext/floor_plans/plan_packs.py`, `src/zyg_workflows/arch_assistant_ext/plan_solver.py`, `src/zyg_workflows/paths.py` |
| `ZYG_POSE_LIMITS_THREADS` | `4` | `src/zyg_workflows/geom/pose_limits/base.py` |
| `ZYG_POST_ENCODE` | `` | `src/zyg_workflows/pipeline_config.py` |
| `ZYG_POST_INPAINT_SHARPEN` | `1` | `src/zyg_workflows/comfy_generation_service/hand_fixer.py` |
| `ZYG_POST_INPAINT_SHARP_THRESH` | `30` | `src/zyg_workflows/comfy_generation_service/hand_fixer.py` |
| `ZYG_PREVIEW_FACE_PORE_DENOISE` | `0.52` | `src/zyg_workflows/comfy_generation_service/constants.py` |
| `ZYG_PREVIEW_FACE_PORE_DENOISE_PHOTOREAL` | `0.38` | `src/zyg_workflows/char_state_service/render_slots.py` |
| `ZYG_PREVIEW_FACE_SEED_CANDIDATES` | `1` | `src/zyg_workflows/pipeline_config.py` |
| `ZYG_PREVIEW_FACE_SEED_CANDIDATES_SDXL` | `2` | `src/zyg_workflows/char_state_service/render_slots.py` |
| `ZYG_PREVIEW_HAND_DETAIL_DENOISE` | `0.42` | `src/zyg_workflows/char_state_service/render_slots.py`, `src/zyg_workflows/comfy_generation_service/preview.py` |
| `ZYG_PREVIEW_HIDE_HANDS` | `` | `src/zyg_workflows/char_state_service/preview_slots.py` |
| `ZYG_PREVIEW_JUDGE_GPU` | `0` | `src/zyg_workflows/preview_judge.py` |
| `ZYG_PREVIEW_LORA_SCALE` | `0.75` | `src/zyg_workflows/comfy_generation_service/constants.py` |
| `ZYG_PREVIEW_LORA_WAIT_S` | `60` | `src/zyg_workflows/pipeline_config.py` |
| `ZYG_PREVIEW_PHOTOREAL_LORA_SCALE` | `0.65` | `src/zyg_workflows/comfy_generation_service/preview.py` |
| `ZYG_PREVIEW_REQUIRE_PROVENANCE` | `1` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_PREVIEW_SDXL_STEPS` | `36` | `src/zyg_workflows/comfy_generation_service/constants.py` |
| `ZYG_PREVIEW_SEED_CANDIDATES` | `1` | `src/zyg_workflows/pipeline_config.py` |
| `ZYG_PREVIEW_SEED_CANDIDATES_SDXL` | `5` | `src/zyg_workflows/char_state_service/render_slots.py` |
| `ZYG_PREVIEW_SEED_ROUND` | `0` | `src/zyg_workflows/char_state_service/render_slots.py` |
| `ZYG_PROFILE_ANCHOR` | `1` | `src/zyg_workflows/contact_sheet_pipeline_steps/anchor_structure_gates.py` |
| `ZYG_PROFILE_ANCHOR_MIN_SIM` | `0.20` | `src/zyg_workflows/contact_sheet_pipeline_steps/anchor_structure_gates.py` |
| `ZYG_PROP_CONTROL_FEATHER` | `3` | `src/zyg_workflows/prop_control.py` |
| `ZYG_PROP_CONTROL_STRENGTH` | `1.0` | `src/zyg_workflows/prop_control.py` |
| `ZYG_PROP_GATE` | `1` | `src/zyg_workflows/video_stages/stage_04_wan_generate.py` |
| `ZYG_PROP_RESTORE_ID_MAXFRAMES` | `96` | `src/zyg_workflows/wan_prop_restore.py` |
| `ZYG_PROP_RESTORE_ID_STRIDE` | `8` | `src/zyg_workflows/wan_prop_restore.py` |
| `ZYG_PROP_RESTORE_REQUIRE_GAIN` | `0` | `src/zyg_workflows/wan_prop_restore.py` |
| `ZYG_QC_ENFORCE` |  | `src/zyg_workflows/qc_contract.py` |
| `ZYG_QC_SAFETY_VALVE` | `1` | `src/zyg_workflows/contact_sheet_pipeline_steps/pipeline_training.py` |
| `ZYG_QC_STRICT_REGIME` | `1` | `src/zyg_workflows/qc_contract.py` |
| `ZYG_QC_VALVE_MIN_SIM` | `0.42` | `src/zyg_workflows/contact_sheet_pipeline/pipeline.py` |
| `ZYG_QC_VALVE_MIN_SIM_PROFILE` | `0.22` | `src/zyg_workflows/contact_sheet_pipeline/pipeline.py` |
| `ZYG_QC_VALVE_MIN_TEXTURE` | `30` | `src/zyg_workflows/contact_sheet_pipeline/pipeline.py` |
| `ZYG_QC_VRAM_FLOOR_MB` |  | `src/zyg_workflows/continuity_qc/models.py` |
| `ZYG_QWEN_DIFFUSERS_DIR` | `` | `src/zyg_workflows/lora_trainer_service/model_paths.py` |
| `ZYG_QWEN_DL_TIMEOUT_S` |  | `src/zyg_workflows/lora_trainer_service/model_paths.py` |
| `ZYG_QWEN_EDIT_ANGLES_LORA` | `` | `src/zyg_workflows/comfy_generation_service/capabilities.py`, `src/zyg_workflows/comfy_generation_service_steps/overrides.py` |
| `ZYG_QWEN_EDIT_ANGLES_LORA_SCALE` | `0.9` | `src/zyg_workflows/comfy_generation_service_steps/overrides.py`, `src/zyg_workflows/creature_fx/render.py`, `src/zyg_workflows/creature_sheet_service/comfy.py` |
| `ZYG_QWEN_EDIT_ANGLES_LORA_SCALE_CONTROL` | `0.0` | `src/zyg_workflows/comfy_generation_service_steps/overrides.py` |
| `ZYG_QWEN_EDIT_CFG` | `4.0` | `src/zyg_workflows/comfy_generation_service_steps/overrides.py`, `src/zyg_workflows/creature_sheet_service/comfy.py` |
| `ZYG_QWEN_EDIT_MAX_MP` | `1.0` | `src/zyg_workflows/comfy_generation_service_steps/preflight.py` |
| `ZYG_QWEN_EDIT_NEGATIVE` | `smooth plastic skin, airbrushed, retouched, wax figure, doll-like skin` | `src/zyg_workflows/comfy_generation_service_steps/overrides.py` |
| `ZYG_QWEN_EDIT_SKIN_LORA` | `qwen_edit_skin.safetensors` | `src/zyg_workflows/comfy_generation_service_steps/overrides.py` |
| `ZYG_QWEN_EDIT_SKIN_LORA_SCALE` | `1.0` | `src/zyg_workflows/comfy_generation_service_steps/overrides.py` |
| `ZYG_QWEN_EDIT_STEPS` | `36` | `src/zyg_workflows/comfy_generation_service_steps/overrides.py`, `src/zyg_workflows/creature_fx/render.py`, `src/zyg_workflows/creature_sheet_service/comfy.py` |
| `ZYG_QWEN_EDIT_UNET` | `` | `src/zyg_workflows/comfy_generation_service/capabilities.py` |
| `ZYG_QWEN_T2I_UNET` | `` | `src/zyg_workflows/comfy_generation_service/capabilities.py` |
| `ZYG_REF_BUILD_TIMEOUT` | `900` | `src/zyg_workflows/arch_assistant_ext/reference_model/helpers.py` |
| `ZYG_REGIONS_PATCH_SEED_FIX` | `1` | `src/zyg_workflows/geom/form/regions/context.py` |
| `ZYG_REMEDY_KB` |  | `src/zyg_workflows/paths.py`, `src/zyg_workflows/remedy_kb/core.py` |
| `ZYG_REMEDY_KB_LEARNED` |  | `src/zyg_workflows/paths.py`, `src/zyg_workflows/remedy_kb/core.py` |
| `ZYG_REMEDY_KB_STATE` |  | `src/zyg_workflows/paths.py`, `src/zyg_workflows/remedy_kb/core.py` |
| `ZYG_REMIXAI_BRIEF_LEVEL` | `lean` | `src/zyg_workflows/remixai_analyze/brief.py` |
| `ZYG_REMIXAI_CHUNK_STRIDE` | `0` | `src/zyg_workflows/remixai_divergence.py` |
| `ZYG_REMIXAI_CHUNK_WORDS` | `15` | `src/zyg_workflows/remixai_divergence.py` |
| `ZYG_REMIXAI_EMBED_MODEL` | `all-MiniLM-L6-v2` | `src/zyg_workflows/remixai_divergence.py` |
| `ZYG_REMIXAI_HAIKU` | `0` | `src/zyg_workflows/remixai_analyze/llm.py` |
| `ZYG_REMIXAI_HAIKU_MODEL` | `claude-haiku-4-5-20251001` | `src/zyg_workflows/remixai_analyze/llm.py` |
| `ZYG_REMIXAI_LLM_MODEL` | `qwen3.5:9b` | `src/zyg_workflows/remixai_analyze/llm.py` |
| `ZYG_REMIXAI_MODEL_FAMILY` | `klein` | `src/zyg_workflows/pipeline_remixai/media.py` |
| `ZYG_REMIXAI_SUB_STYLE` | `` | `src/zyg_workflows/pipeline_remixai/media.py` |
| `ZYG_REMIXAI_TITLE_MAX_CHARS` | `70` | `src/zyg_workflows/remixai_analyze/title.py` |
| `ZYG_REMIXAI_TITLE_MAX_WORDS` | `12` | `src/zyg_workflows/remixai_analyze/title.py` |
| `ZYG_REMIXAI_TTS_WPM` | `` | `src/zyg_workflows/remixai_analyze/brief.py` |
| `ZYG_REMIXAI_VLM_MODEL` | `qwen3.5:9b` | `src/zyg_workflows/remixai_analyze/llm.py` |
| `ZYG_REMIXAI_VOICE` | `` | `src/zyg_workflows/pipeline_remixai/media.py` |
| `ZYG_REMIX_BROLL_DIR` |  | `src/zyg_workflows/paths.py` |
| `ZYG_REMIX_LLM_MODEL` | `qwen3.5:9b` | `src/zyg_workflows/pipeline_remix/scoring.py` |
| `ZYG_REMIX_VOICE` | `` | `src/zyg_workflows/pipeline_remix/render.py` |
| `ZYG_REQUIRE_VERIFIED_REFS` | `1` | `src/zyg_workflows/geom/manifest.py` |
| `ZYG_RESTORE_DELTA_FLOOR` | `0.018911` | `src/zyg_workflows/restoration_qc.py` |
| `ZYG_RIDGE_ANISOTROPIC_COLLAR` | `1` | `src/zyg_workflows/geom/form/ridge/primitive.py` |
| `ZYG_RUNTIME_STALE_S` | `1800` | `src/zyg_workflows/pipeline_runtime.py` |
| `ZYG_RUN_ID` |  | `src/zyg_workflows/anatomy_qc/runtime.py`, `src/zyg_workflows/contact_sheet_pipeline/sheet_canvas.py`, `src/zyg_workflows/identity_bank/embedding.py` +6 more |
| `ZYG_SAFETY_THRESHOLDS_PATH` | `` | `src/zyg_workflows/pipeline_config.py` |
| `ZYG_SAM2_NODE_DIR` |  | `src/zyg_workflows/paths.py` |
| `ZYG_SAM2_WEIGHTS` |  | `src/zyg_workflows/continuity_qc/models.py` |
| `ZYG_SAM3DB_LOAD_S` | `240` | `src/zyg_workflows/sam3d_body_service.py` |
| `ZYG_SAM3DB_NO_LOCK` |  | `src/zyg_workflows/geom/pose_track/constants.py`, `src/zyg_workflows/sam3d_body_service.py` |
| `ZYG_SAM3DB_PER_FRAME_S` | `6` | `src/zyg_workflows/sam3d_body_service.py` |
| `ZYG_SAM3DB_PYTHON` |  | `src/zyg_workflows/sam3d_body_service.py` |
| `ZYG_SAM3_HOME` |  | `src/zyg_workflows/paths.py` |
| `ZYG_SAM3_PYTHON` |  | `src/zyg_workflows/paths.py` |
| `ZYG_SAM3_TIMEOUT_S` | `300` | `src/zyg_workflows/sam3_service.py` |
| `ZYG_SCAN_FILTER` | `butterworth` | `src/zyg_workflows/geom/scan_ingest/residual.py` |
| `ZYG_SCENE_MAX_GREYBOX` | `0.65` | `src/zyg_workflows/scene_still_helpers.py` |
| `ZYG_SCENE_MIN_BRIGHT` | `28` | `src/zyg_workflows/scene_still_helpers.py` |
| `ZYG_SCENE_MIN_SHARP` | `45` | `src/zyg_workflows/scene_still_helpers.py` |
| `ZYG_SCENE_NO_LORA_SHARP_MULT` | `0.40` | `src/zyg_workflows/scene_still_helpers.py` |
| `ZYG_SCHOLARLY_ALLOW_RAW_SOURCE` | `0` | `src/zyg_workflows/scholarly/stages_01_18/stage_03.py` |
| `ZYG_SCHOLARLY_ALWAYS_REROLL` | `0` | `src/zyg_workflows/scholarly/stages_37_54_flux_slot.py` |
| `ZYG_SCHOLARLY_ANATOMY_ESCALATIONS` | `8` | `src/zyg_workflows/scholarly/stages_37_54_flux_state.py` |
| `ZYG_SCHOLARLY_ASR_FLOOR` | `0.60` | `src/zyg_workflows/scholarly/stages_01_18/stage_08.py` |
| `ZYG_SCHOLARLY_BED_LUFS` | `-34` | `src/zyg_workflows/scholarly/stages_19_36/music_bed.py` |
| `ZYG_SCHOLARLY_CLIP_S` |  | `src/zyg_workflows/scholarly_motion.py` |
| `ZYG_SCHOLARLY_EMO_ALPHA` | `0.45` | `src/zyg_workflows/scholarly/stages_01_18/stage_08.py` |
| `ZYG_SCHOLARLY_EMO_TEXT` | `0` | `src/zyg_workflows/scholarly/stages_01_18/stage_08.py` |
| `ZYG_SCHOLARLY_ERA_JUDGE` | `api` | `src/zyg_workflows/scholarly/stages_37_54_flux_render_gate.py` |
| `ZYG_SCHOLARLY_ERA_REPAIR` | `1` | `src/zyg_workflows/scholarly/stages_37_54_flux_slot.py` |
| `ZYG_SCHOLARLY_FACTCHECK_BLOCK` | `0` | `src/zyg_workflows/scholarly/stages_01_18/stage_04.py` |
| `ZYG_SCHOLARLY_GPU_LOCK_PATH` |  | `src/zyg_workflows/scholarly_stills_backend.py` |
| `ZYG_SCHOLARLY_GPU_LOCK_POLL_S` | `` | `src/zyg_workflows/scholarly_stills_backend.py` |
| `ZYG_SCHOLARLY_GPU_LOCK_STALE_S` | `` | `src/zyg_workflows/scholarly_stills_backend.py` |
| `ZYG_SCHOLARLY_HAND_QC` | `1` | `src/zyg_workflows/scholarly/stages_37_54_flux_setup.py` |
| `ZYG_SCHOLARLY_HAND_QC_MIN_VRAM_GB` | `8` | `src/zyg_workflows/scholarly/stages_37_54_flux_qa.py` |
| `ZYG_SCHOLARLY_LLM_BACKEND` | `subscription` | `src/zyg_workflows/subscription_llm.py` |
| `ZYG_SCHOLARLY_LLM_MODEL` | `` | `src/zyg_workflows/subscription_llm.py` |
| `ZYG_SCHOLARLY_LLM_MODEL_LARGE` | `` | `src/zyg_workflows/subscription_llm.py` |
| `ZYG_SCHOLARLY_LLM_MODEL_SCRIPT` | `` | `src/zyg_workflows/subscription_llm.py` |
| `ZYG_SCHOLARLY_LLM_MODEL_SMALL` | `` | `src/zyg_workflows/subscription_llm.py` |
| `ZYG_SCHOLARLY_LTX` | `1` | `src/zyg_workflows/scholarly_motion.py` |
| `ZYG_SCHOLARLY_MURCH_FLOOR` | `6` | `src/zyg_workflows/scholarly/stages_37_54.py` |
| `ZYG_SCHOLARLY_MUSIC` | `1` | `src/zyg_workflows/scholarly/stages_19_36/music_bed.py` |
| `ZYG_SCHOLARLY_MUSIC_ONLY_LUFS` | `-24` | `src/zyg_workflows/scholarly/stages_19_36/music_bed.py` |
| `ZYG_SCHOLARLY_OCR_MIN_AREA_FRAC` | `0.001` | `src/zyg_workflows/typography_ocr.py` |
| `ZYG_SCHOLARLY_OCR_MIN_CONF` | `0.50` | `src/zyg_workflows/typography_ocr.py` |
| `ZYG_SCHOLARLY_OCR_MIN_REGIONS` | `1` | `src/zyg_workflows/typography_ocr.py` |
| `ZYG_SCHOLARLY_OCR_TEXT` | `1` | `src/zyg_workflows/scholarly/stages_37_54_flux_state.py` |
| `ZYG_SCHOLARLY_QWEN_CLEAR_VRAM` | `0` | `src/zyg_workflows/scholarly/stages_37_54_flux_attempt.py` |
| `ZYG_SCHOLARLY_SCENE_LLM` | `` | `src/zyg_workflows/scholarly/stages_01_18/stage_05.py` |
| `ZYG_SCHOLARLY_SEC_PER_WORD` | `0.55` | `src/zyg_workflows/pipeline_scholarly/constants.py` |
| `ZYG_SCHOLARLY_SEED_WAV` | `` | `src/zyg_workflows/scholarly/stages_01_18/stage_08.py` |
| `ZYG_SCHOLARLY_TYPO_REPAIR` | `1` | `src/zyg_workflows/scholarly/stages_37_54_flux_state.py` |
| `ZYG_SCHOLARLY_VLM_ERA` |  | `src/zyg_workflows/scholarly/stages_37_54.py`, `src/zyg_workflows/scholarly/stages_37_54_flux_state.py` |
| `ZYG_SCHOLARLY_VLM_QC` | `1` | `src/zyg_workflows/scholarly/stages_37_54_flux_state.py` |
| `ZYG_SCHOLARLY_VLM_QC_MODEL` | `moondream` | `src/zyg_workflows/scholarly/stages_37_54_flux_state.py` |
| `ZYG_SCHOLARLY_VLM_TEXT` | `1` | `src/zyg_workflows/scholarly/stages_37_54_flux_state.py` |
| `ZYG_SCHOLARLY_VLM_TEXT_MODEL` |  | `src/zyg_workflows/scholarly/stages_37_54_flux_state.py` |
| `ZYG_SCHOLARLY_VLM_TEXT_TIER` | `resident` | `src/zyg_workflows/scholarly/stages_37_54_flux_render_gate.py`, `src/zyg_workflows/scholarly/stages_37_54_flux_slot.py`, `src/zyg_workflows/scholarly/stages_37_54_flux_vlm_gates.py` |
| `ZYG_SCRATCH` | `` | `src/zyg_workflows/audio_mix/chain.py` |
| `ZYG_SCRATCH_DIR` |  | `src/zyg_workflows/geom/mvconsist/sfm.py` |
| `ZYG_SDXL_ALIGNED_CKPT` | `sd_xl_base_1.0.safetensors` | `src/zyg_workflows/comfy_generation_service/constants.py` |
| `ZYG_SDXL_ANIMATED` | `1` | `src/zyg_workflows/animal_bible_service.py`, `src/zyg_workflows/char_state_service/lora_training.py`, `src/zyg_workflows/character_bible_service/store.py` +4 more |
| `ZYG_SDXL_ANIMATED_CKPT` | `DynaVisionXL.safetensors` | `src/zyg_workflows/animated_sdxl_dataset.py`, `src/zyg_workflows/comfy_generation_service/constants.py` |
| `ZYG_SDXL_CHECKPOINT` | `Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors` | `src/zyg_workflows/comfy_generation_service/constants.py` |
| `ZYG_SDXL_COMFY_MIN_VRAM_GB` | `10` | `src/zyg_workflows/storyteller/stage_035_backend.py` |
| `ZYG_SDXL_DIFFUSERS_DIR` |  | `src/zyg_workflows/lora_trainer_service/model_paths.py` |
| `ZYG_SDXL_HF_REVISION` | `` | `src/zyg_workflows/lora_trainer_service/model_paths.py` |
| `ZYG_SDXL_I2I_KEEP_LORA` | `1` | `src/zyg_workflows/comfy_generation_service/workflows.py` |
| `ZYG_SDXL_IMG2IMG_DENOISE` | `0.32` | `src/zyg_workflows/comfy_generation_service/constants.py` |
| `ZYG_SDXL_TRAIN_CHECKPOINT` | `` | `src/zyg_workflows/lora_trainer_service/model_paths.py` |
| `ZYG_SERVER_PYTHON` |  | `src/zyg_workflows/paths.py` |
| `ZYG_SHA_CACHE` |  | `src/zyg_workflows/run_ledger.py` |
| `ZYG_SHEET_ANCHOR_FAMILY` | `auto` | `src/zyg_workflows/contact_sheet_pipeline/layout.py` |
| `ZYG_SHEET_CORPUS_CELLS` | `96` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_SHEET_CORPUS_DERIVED_FRAC` | `0.35` | `src/zyg_workflows/contact_sheet_pipeline/constants.py` |
| `ZYG_SHEET_DEDUP_HAMMING` | `4` | `src/zyg_workflows/contact_sheet_pipeline/dedup.py` |
| `ZYG_SHEET_MIN_OK_FRAC` | `0.85` | `src/zyg_workflows/contact_sheet_pipeline_steps/sheet_finalize.py` |
| `ZYG_SIMPLETUNER_DIR` | `` | `src/zyg_workflows/paths.py` |
| `ZYG_SKIP_GPU_EXCLUSIVE` | `` | `src/zyg_workflows/vram_manager.py` |
| `ZYG_SMOKE_RUN` |  | `src/zyg_workflows/pipeline_scholarly/pipeline.py` |
| `ZYG_STORYTELLER_CHARS` |  | `src/zyg_workflows/paths.py` |
| `ZYG_STORYTELLER_LORAS` |  | `src/zyg_workflows/paths.py` |
| `ZYG_STRICT_ATTRIBUTES` | `0` | `src/zyg_workflows/contact_sheet_pipeline_steps/anchor_attribute_gate.py` |
| `ZYG_ST_ATTENTION` | `diffusers` | `src/zyg_workflows/lora_trainer_service/st_config_writers.py` |
| `ZYG_ST_COMPILE` | `false` | `src/zyg_workflows/lora_trainer_service/st_config_writers.py` |
| `ZYG_ST_DUPE_CORR` | `0.90` | `src/zyg_workflows/storyteller/stage_05b_subtitles.py` |
| `ZYG_ST_EXTRA_PROMPT_MAX` | `200` | `src/zyg_workflows/pipeline_storyteller.py` |
| `ZYG_ST_GROUP_OFFLOAD` | `false` | `src/zyg_workflows/lora_trainer_service/st_config_writers.py` |
| `ZYG_ST_VALIDATION_INTERVAL` |  | `src/zyg_workflows/lora_trainer_service/st_config.py` |
| `ZYG_SUBSCRIPTION_LLM_CLI` | `` | `src/zyg_workflows/subscription_llm.py` |
| `ZYG_SUBSCRIPTION_LLM_DIR` |  | `src/zyg_workflows/subscription_llm.py` |
| `ZYG_SUBSCRIPTION_LLM_RAW_DIR` |  | `src/zyg_workflows/subscription_llm.py` |
| `ZYG_SUBSCRIPTION_LLM_RETRIES` | `1` | `src/zyg_workflows/subscription_llm.py` |
| `ZYG_SUBSCRIPTION_LLM_THINKING` | `` | `src/zyg_workflows/subscription_llm.py` |
| `ZYG_SUBSCRIPTION_LLM_TIMEOUT` | `900` | `src/zyg_workflows/subscription_llm.py` |
| `ZYG_TEXTURE_QC` | `1` | `src/zyg_workflows/contact_sheet_pipeline_steps/dataset_qc.py` |
| `ZYG_TEXTURE_QC_EXCLUDE_LAPVAR` | `12` | `src/zyg_workflows/contact_sheet_pipeline_steps/dataset_qc.py` |
| `ZYG_TEXTURE_QC_REGION_MODE` | `min` | `src/zyg_workflows/contact_sheet_pipeline/identity_qc.py` |
| `ZYG_TEXTURE_QC_TRAIN_LAPVAR` | `30` | `src/zyg_workflows/contact_sheet_pipeline_steps/dataset_qc.py` |
| `ZYG_TEXTURE_QC_WARN_LAPVAR` | `45` | `src/zyg_workflows/contact_sheet_pipeline_steps/dataset_qc.py` |
| `ZYG_TITANET_MODEL` | `titanet_large` | `src/zyg_workflows/tools/voice_embed_worker.py` |
| `ZYG_TSDB_ART_FRESH_DAYS` | `300` | `src/zyg_workflows/sports_ingest/key_players.py` |
| `ZYG_TSDB_GAP_S` | `1.4` | `src/zyg_workflows/sports_ingest/constants.py` |
| `ZYG_TSDB_NEG_TTL_S` | `21600` | `src/zyg_workflows/sports_ingest/constants.py` |
| `ZYG_TTS_ASR_MIN` | `0.55` | `src/zyg_workflows/tts_service/asr.py` |
| `ZYG_TTS_ASR_MODEL` | `small` | `src/zyg_workflows/tts_service/asr.py` |
| `ZYG_TTS_ASR_QC` | `1` | `src/zyg_workflows/tts_service/asr.py` |
| `ZYG_TTS_CATALOG_GENDER` | `1` | `src/zyg_workflows/voice_pool.py` |
| `ZYG_TTS_CORES` | `0-19` | `src/zyg_workflows/kids_music_service/singer.py`, `src/zyg_workflows/tts_service/engines.py`, `src/zyg_workflows/voice_qc.py` +1 more |
| `ZYG_TTS_KEEP_SEGMENTS` | `0` | `src/zyg_workflows/tts_service/shared.py` |
| `ZYG_TTS_LOUDNORM` | `I=-16:TP=-1.5:LRA=11` | `src/zyg_workflows/tts_service/constants.py` |
| `ZYG_TTS_MAX_CHARS` | `350` | `src/zyg_workflows/tts_service/constants.py` |
| `ZYG_TTS_SEED_WAV` | `` | `src/zyg_workflows/voice_pool.py` |
| `ZYG_TTS_THREADS` | `8` | `src/zyg_workflows/tts_service/engines.py`, `src/zyg_workflows/voice_studio/constants.py` |
| `ZYG_TTS_VOICE` | `` | `src/zyg_workflows/tts_service/shared.py` |
| `ZYG_TTS_VRAM_WAITS` | `30` | `src/zyg_workflows/tts_service/engines.py` |
| `ZYG_TTS_VRAM_WAIT_S` | `20` | `src/zyg_workflows/tts_service/engines.py` |
| `ZYG_TYPO_QWEN_INPAINT` | `auto` | `src/zyg_workflows/typography_repair.py` |
| `ZYG_TYPO_QWEN_MAX_SIDE` | `1024` | `src/zyg_workflows/typography_repair.py` |
| `ZYG_TYPO_QWEN_NEGATIVE` | `text, letters, lettering, writing, words, numbers, characters, signage, sign, logo, watermark, caption, label, inscription, calligraphy, blurry` | `src/zyg_workflows/typography_repair.py` |
| `ZYG_TYPO_QWEN_PROMPT` | `plain surface, no lettering, the same material continuing uninterrupted, matching surface texture, grain, colour and lighting as the surrounding area, photographic, seamless continuation` | `src/zyg_workflows/typography_repair.py` |
| `ZYG_TYPO_QWEN_STEPS` | `20` | `src/zyg_workflows/typography_repair.py` |
| `ZYG_TYPO_QWEN_TIMEOUT_S` | `600` | `src/zyg_workflows/typography_repair.py` |
| `ZYG_TYPO_REPAIR_DILATE` | `0.012` | `src/zyg_workflows/typography_repair.py` |
| `ZYG_TYPO_REPAIR_FEATHER` | `3` | `src/zyg_workflows/typography_repair.py` |
| `ZYG_TYPO_REPAIR_JPEG_Q` | `95` | `src/zyg_workflows/typography_repair.py` |
| `ZYG_TYPO_REPAIR_MAX_AREA` | `0.05` | `src/zyg_workflows/typography_repair.py` |
| `ZYG_TYPO_REPAIR_MAX_BOX` | `0.02` | `src/zyg_workflows/typography_repair.py` |
| `ZYG_TYPO_REPAIR_MAX_CHROMA` | `34` | `src/zyg_workflows/typography_repair.py` |
| `ZYG_TYPO_REPAIR_MAX_LUMA` | `30` | `src/zyg_workflows/typography_repair.py` |
| `ZYG_TYPO_REPAIR_MAX_SIDE` | `768` | `src/zyg_workflows/typography_repair.py` |
| `ZYG_TYPO_REPAIR_MIN_STD` | `2.0` | `src/zyg_workflows/typography_repair.py` |
| `ZYG_TYPO_REPAIR_PROMPT` | `the same material continuing uninterrupted, matching surface texture and grain, same colour and lighting as the surrounding area, photographic, seamless continuation` | `src/zyg_workflows/typography_repair.py` |
| `ZYG_TYPO_REPAIR_STRENGTH` | `0.65` | `src/zyg_workflows/typography_repair.py` |
| `ZYG_USE_COMFYUI` | `` | `src/zyg_workflows/_comfy_client.py`, `src/zyg_workflows/comfy_generation_service/backend.py`, `src/zyg_workflows/video_stages/stage_01_scene_plan.py` +1 more |
| `ZYG_VACE_CTRL_BLEND` | `mask` | `src/zyg_workflows/wan_vace_service/static_clip.py` |
| `ZYG_VC_APPLIO` |  | `src/zyg_workflows/voice_conversion.py` |
| `ZYG_VFX_BACKBONE` | `facebook/dinov2-base` | `src/zyg_workflows/vfx_embed.py` |
| `ZYG_VFX_BACKBONE_REVISION` | `main` | `src/zyg_workflows/vfx_embed.py` |
| `ZYG_VFX_CONF_STRICT` | `0.5` | `src/zyg_workflows/vfx_landmarks.py` |
| `ZYG_VFX_CONF_WEAK` | `0.2` | `src/zyg_workflows/vfx_landmarks.py` |
| `ZYG_VFX_DETECTOR_DIR` |  | `src/zyg_workflows/vfx_landmarks.py` |
| `ZYG_VFX_EMBED_BATCH` | `64` | `src/zyg_workflows/vfx_embed.py` |
| `ZYG_VFX_EMBED_MIN_FREE_MB` | `2000` | `src/zyg_workflows/vfx_embed.py` |
| `ZYG_VFX_MAX_FACES` | `4` | `src/zyg_workflows/vfx_landmarks.py` |
| `ZYG_VFX_MAX_HANDS` | `8` | `src/zyg_workflows/vfx_landmarks.py` |
| `ZYG_VFX_MAX_POSES` | `4` | `src/zyg_workflows/vfx_landmarks.py` |
| `ZYG_VFX_MAX_WINDOW` | `120` | `src/zyg_workflows/vfx_analyzer/constants.py` |
| `ZYG_VFX_PROBE_CONF` | `0.6` | `src/zyg_workflows/vfx_probes.py` |
| `ZYG_VFX_PROBE_MARGIN` | `0.08` | `src/zyg_workflows/vfx_probes.py` |
| `ZYG_VFX_PROBE_OOD_K` | `5` | `src/zyg_workflows/vfx_probes.py` |
| `ZYG_VFX_PROBE_OOD_REF` | `512` | `src/zyg_workflows/vfx_probes.py` |
| `ZYG_VFX_PROBE_OOD_RUN_FRAC` | `0.6` | `src/zyg_workflows/vfx_probes.py` |
| `ZYG_VFX_ROOT` |  | `src/zyg_workflows/paths.py` |
| `ZYG_VFX_TAXONOMY` |  | `src/zyg_workflows/vfx_analyzer/constants.py` |
| `ZYG_VFX_TILE_GRIDS` | `2,3` | `src/zyg_workflows/vfx_landmarks.py` |
| `ZYG_VFX_TILE_MIN_PX` | `420` | `src/zyg_workflows/vfx_landmarks.py` |
| `ZYG_VFX_TILE_OVERLAP` | `0.25` | `src/zyg_workflows/vfx_landmarks.py` |
| `ZYG_VFX_VLM` | `qwen3.5:9b` | `src/zyg_workflows/vfx_analyzer/constants.py` |
| `ZYG_VFX_VLM_CTX` | `4096` | `src/zyg_workflows/vfx_analyzer/capability.py` |
| `ZYG_VFX_WINDOW` | `10` | `src/zyg_workflows/vfx_analyzer/constants.py` |
| `ZYG_VICKY_ACTIVE_URL` |  | `src/zyg_workflows/medusa_model_jobs.py` |
| `ZYG_VIDEO_BLANK_THRESH` |  | `src/zyg_workflows/video_still_qa_service.py` |
| `ZYG_VIDEO_HUMAN_CONFLICT_MARGIN` | `0.02` | `src/zyg_workflows/video_still_qa_service.py` |
| `ZYG_VIDEO_INDOOR_CONFLICT_MARGIN` | `0.015` | `src/zyg_workflows/video_still_qa_service.py` |
| `ZYG_VIDEO_MAX_PORTRAIT_FACES` | `1` | `src/zyg_workflows/video_still_qa_service.py` |
| `ZYG_VIDEO_STILL_FAMILY` | `qwen` | `src/zyg_workflows/video_flux_still_service.py` |
| `ZYG_VIDEO_STILL_MAX_ATTEMPTS` | `3` | `src/zyg_workflows/video_flux_still_service.py` |
| `ZYG_VIDEO_SUBJECT_MIN_SCORE` | `0.17` | `src/zyg_workflows/video_still_qa_service.py` |
| `ZYG_VLM` | `1` | `src/zyg_workflows/vlm_inspector/base.py` |
| `ZYG_VLM_CHECKLIST` | `scene20_binary` | `src/zyg_workflows/vlm_inspector/api.py` |
| `ZYG_VLM_CHECKLISTS` |  | `src/zyg_workflows/creature_judge.py`, `src/zyg_workflows/vlm_inspector/base.py`, `src/zyg_workflows/vlm_report/inspection.py` |
| `ZYG_VLM_CPU_WHEN_BUSY` | `0` | `src/zyg_workflows/vlm_inspector/api.py` |
| `ZYG_VLM_HOME` |  | `src/zyg_workflows/paths.py` |
| `ZYG_VLM_IDLE_TIMEOUT` | `180` | `src/zyg_workflows/vlm_inspector/judge_server.py` |
| `ZYG_VLM_K` | `1` | `src/zyg_workflows/vlm_inspector/api.py` |
| `ZYG_VLM_KEEP_FRAMES` | `0` | `src/zyg_workflows/vlm_inspector/api.py`, `src/zyg_workflows/vlm_inspector/judge_server.py` |
| `ZYG_VLM_PERSISTENT` | `1` | `src/zyg_workflows/vlm_inspector/judge_server.py` |
| `ZYG_VLM_PERSISTENT_TIERS` |  | `src/zyg_workflows/vlm_inspector/judge_server.py` |
| `ZYG_VLM_QPAYLOAD` | `list` | `src/zyg_workflows/vlm_inspector/base.py` |
| `ZYG_VLM_REPORT_CONTINUITY` | `0` | `src/zyg_workflows/vlm_report/entry.py` |
| `ZYG_VLM_REPORT_GROUND` | `1` | `src/zyg_workflows/vlm_report/entry.py` |
| `ZYG_VLM_REPORT_MAXLOC` |  | `src/zyg_workflows/vlm_report/constants.py` |
| `ZYG_VLM_REPORT_MIN_CROP_PX` |  | `src/zyg_workflows/vlm_report/constants.py` |
| `ZYG_VLM_REPORT_SYNTH_TOKENS` |  | `src/zyg_workflows/vlm_report/constants.py` |
| `ZYG_VLM_REPORT_SYNTH_WAIT_S` |  | `src/zyg_workflows/vlm_report/constants.py` |
| `ZYG_VLM_STRICT` | `0` | `src/zyg_workflows/vlm_inspector/base.py` |
| `ZYG_VLM_TIER` | `cpu` | `src/zyg_workflows/vlm_inspector/api.py` |
| `ZYG_VLM_TIMEOUT` |  | `src/zyg_workflows/vlm_inspector/base.py` |
| `ZYG_VOICE_ANALYSIS_DIR` |  | `src/zyg_workflows/paths.py` |
| `ZYG_VOICE_EMBED_PY` |  | `src/zyg_workflows/vocal_analysis.py` |
| `ZYG_VOICE_QC` | `1` | `src/zyg_workflows/voice_qc.py` |
| `ZYG_VOICE_QC_ENFORCE` | `0` | `src/zyg_workflows/voice_qc.py` |
| `ZYG_VOICE_QC_F0_TOL_PCT` | `18` | `src/zyg_workflows/voice_qc.py` |
| `ZYG_VOICE_QC_VTL_TOL_CM` | `1.0` | `src/zyg_workflows/voice_qc.py` |
| `ZYG_WAN22` | `` | `src/zyg_workflows/wan_video_service/constants.py` |
| `ZYG_WAN_ATTENTION` | `sdpa` | `src/zyg_workflows/lora_attest/ab_probe.py`, `src/zyg_workflows/wan_vace_service/probe.py`, `src/zyg_workflows/wan_vace_service/static_clip.py` +1 more |
| `ZYG_WAN_HEIGHT` | `480` | `src/zyg_workflows/wan_vace_service/static_clip.py`, `src/zyg_workflows/wan_video_service/constants.py` |
| `ZYG_WAN_LIGHTNING` | `` | `src/zyg_workflows/wan_video_service/constants.py` |
| `ZYG_WAN_LORA` | `` | `src/zyg_workflows/wan_video_service/helpers.py` |
| `ZYG_WAN_LORA_STRENGTH` | `1.0` | `src/zyg_workflows/wan_video_service/helpers.py` |
| `ZYG_WAN_MODEL` | `Wan2_1-I2V-14B-480P_fp8_e4m3fn.safetensors` | `src/zyg_workflows/wan_video_service/constants.py` |
| `ZYG_WAN_T2V_MODEL` | `Wan2_1-T2V-14B_fp8_e4m3fn.safetensors` | `src/zyg_workflows/lora_attest/ab_probe.py`, `src/zyg_workflows/wan_vace_service/base.py` |
| `ZYG_WAN_TIMEOUT_S` | `900` | `src/zyg_workflows/video_studio/assembly/render.py`, `src/zyg_workflows/wan_vace_service/probe.py`, `src/zyg_workflows/wan_vace_service/static_clip.py` +1 more |
| `ZYG_WAN_VACE_MODULE` | `Wan2_1-VACE_module_14B_fp8_e4m3fn.safetensors` | `src/zyg_workflows/wan_vace_service/base.py` |
| `ZYG_WAN_WIDTH` | `832` | `src/zyg_workflows/wan_vace_service/static_clip.py`, `src/zyg_workflows/wan_video_service/constants.py` |
| `ZYG_WHISPER_BEAM` | `5` | `src/zyg_workflows/zyg_whisper.py` |
| `ZYG_WHISPER_COMPUTE` |  | `src/zyg_workflows/zyg_whisper.py` |
| `ZYG_WHISPER_CPU_MODEL` | `base` | `src/zyg_workflows/voice_stt.py`, `src/zyg_workflows/zyg_whisper.py` |
| `ZYG_WHISPER_FW_MIN_VRAM_MB` |  | `src/zyg_workflows/audio_qc.py`, `src/zyg_workflows/zyg_whisper.py` |
| `ZYG_WHISPER_MIN_VRAM_MB` | `1536` | `src/zyg_workflows/murch_engine/alignment.py`, `src/zyg_workflows/zyg_whisper.py` |
| `ZYG_WHISPER_MODEL` | `large-v3` | `src/zyg_workflows/zyg_whisper.py` |
| `ZYG_YTDLP_COOKIES` | `` | `src/zyg_workflows/remixai_ingest.py` |
<!-- END GENERATED SETTINGS -->

## Credentials and contact details

Not feature flags: these carry a secret or a personal detail, so they have no usable
default and the repository holds no value for them. Everything stays functional when
they are unset — the feature that needs one logs a warning and switches itself off.

| Variable | Default | What it is |
| --- | --- | --- |
| `ZYG_ODDS_API_KEY` | `` | The Odds API key used by `sports_ingest.py` for fixtures and prices; unset disables odds fetching. |
| `ZYG_APISPORTS_API_KEY` | `` | API-Sports (api-football etc.) key used by `sports_ingest.py`; unset disables the API-Sports fallback. |
| `ZYG_CONTACT_EMAIL` | `contact@example.invalid` | Reachable address put in the `User-Agent`/`mailto` of outgoing requests to OSM, Nominatim, OpenAlex and Unpaywall, as their usage policies ask. See `zyg_workflows.contact.contact_email()`. |
| `ZYG_PUBLIC_DOMAIN` | — | Public apex domain, required by `tools/deploy_studio_tls.sh`, which deploys the TLS front door for `studio.$ZYG_PUBLIC_DOMAIN`. |
