#!/bin/bash

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# train_char_t2v.sh <char_id> <trigger> — Wan T2V-14B character LoRA (the VACE backbone!).
# 2026-07-29 research: i2v-task LoRAs silently drop keys on the t2v base (kijai #909) and
# ~480 steps @5e-5 was 1/4 of community norm. This recipe: t2v task, lr 1e-4, ~1500 steps.
set -e
CID="$1"; TRIGGER="$2"
MODELS_ROOT="${ZYG_MODELS_ROOT:-$HOME/ai-models}"
ROOT="$MODELS_ROOT/musubi-tuner"
MODELS="$MODELS_ROOT/wan_train_models"
DATA="${ZYG_LORA_DATASETS:-$HOME/lora-datasets}/wan_chars/$CID"
OUT="${ZYG_LORA_OUTPUTS:-$HOME/lora-outputs}/wan_chars/${CID}_t2v"
PY="$ROOT/venv/bin/python"
mkdir -p "$OUT"

echo "== prep dataset =="
"$PY" "$(dirname "$0")/prep_dataset.py" "$CID" "$TRIGGER"

echo "== t2v DiT present? =="
DIT="$MODELS/wan2.1_t2v_14B_fp8_e4m3fn.safetensors"
if [ ! -f "$DIT" ]; then
  hf download Comfy-Org/Wan_2.1_ComfyUI_repackaged \
    split_files/diffusion_models/wan2.1_t2v_14B_fp8_e4m3fn.safetensors --local-dir "$MODELS/_dl"
  mv "$MODELS/_dl/split_files/diffusion_models/wan2.1_t2v_14B_fp8_e4m3fn.safetensors" "$DIT"
fi

echo "== cache latents (t2v: no --clip) =="
rm -rf "$DATA/cache_t2v"; mkdir -p "$DATA/cache_t2v"
sed "s|cache\"|cache_t2v\"|" "$DATA/dataset.toml" > "$DATA/dataset_t2v.toml"
"$PY" "$ROOT/src/musubi_tuner/wan_cache_latents.py" \
  --dataset_config "$DATA/dataset_t2v.toml" \
  --vae "$MODELS/Wan2.1_VAE.pth"

echo "== cache text-encoder outputs =="
"$PY" "$ROOT/src/musubi_tuner/wan_cache_text_encoder_outputs.py" \
  --dataset_config "$DATA/dataset_t2v.toml" \
  --t5 "$MODELS/models_t5_umt5-xxl-enc-bf16.pth"

echo "== train (t2v-14B, lr 1e-4, ~1500 steps) =="
"$ROOT/venv/bin/accelerate" launch --num_processes 1 --mixed_precision bf16 \
  "$ROOT/src/musubi_tuner/wan_train_network.py" \
  --task t2v-14B \
  --dit "$DIT" \
  --dataset_config "$DATA/dataset_t2v.toml" \
  --sdpa --mixed_precision bf16 --fp8_base \
  --optimizer_type adamw8bit --learning_rate 1e-4 \
  --gradient_checkpointing --max_data_loader_n_workers 2 --persistent_data_loader_workers \
  --network_module networks.lora_wan --network_dim 32 \
  --timestep_sampling shift --discrete_flow_shift 3.0 \
  --max_train_epochs 32 --save_every_n_epochs 8 --seed 42 \
  --output_dir "$OUT" --output_name "wan_char_${CID}_t2v"
echo "=== T2V TRAIN DONE: $OUT ==="
