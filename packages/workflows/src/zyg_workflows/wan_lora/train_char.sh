#!/bin/bash

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# train_char.sh <char_id> <trigger> — cache latents + text-enc, then train a Wan I2V
# character LoRA (rank 32, lr 5e-5, ~10 epochs — the researched recipe). ~1-3h on 48GB.
set -e
CID="$1"; TRIGGER="$2"
MODELS_ROOT="${ZYG_MODELS_ROOT:-$HOME/ai-models}"
ROOT="$MODELS_ROOT/musubi-tuner"
MODELS="$MODELS_ROOT/wan_train_models"
DATA="${ZYG_LORA_DATASETS:-$HOME/lora-datasets}/wan_chars/$CID"
OUT="${ZYG_LORA_OUTPUTS:-$HOME/lora-outputs}/wan_chars/$CID"
PY="$ROOT/venv/bin/python"
mkdir -p "$OUT"

echo "== prep dataset =="
"$PY" "$(dirname "$0")/prep_dataset.py" "$CID" "$TRIGGER"

echo "== cache latents (i2v: --clip enables image-conditioning latents) =="
"$PY" "$ROOT/src/musubi_tuner/wan_cache_latents.py" \
  --dataset_config "$DATA/dataset.toml" \
  --vae "$MODELS/Wan2.1_VAE.pth" \
  --clip "$MODELS/models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth"

echo "== cache text-encoder outputs =="
"$PY" "$ROOT/src/musubi_tuner/wan_cache_text_encoder_outputs.py" \
  --dataset_config "$DATA/dataset.toml" \
  --t5 "$MODELS/models_t5_umt5-xxl-enc-bf16.pth"

echo "== train =="
"$ROOT/venv/bin/accelerate" launch --num_processes 1 --mixed_precision bf16 \
  "$ROOT/src/musubi_tuner/wan_train_network.py" \
  --task i2v-14B \
  --dit "$MODELS/wan2.1_i2v_720p_14B_fp8_e4m3fn.safetensors" \
  --clip "$MODELS/models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth" \
  --dataset_config "$DATA/dataset.toml" \
  --sdpa --mixed_precision bf16 --fp8_base \
  --optimizer_type adamw8bit --learning_rate 5e-5 \
  --gradient_checkpointing --max_data_loader_n_workers 2 --persistent_data_loader_workers \
  --network_module networks.lora_wan --network_dim 32 \
  --timestep_sampling shift --discrete_flow_shift 3.0 \
  --max_train_epochs 10 --save_every_n_epochs 2 --seed 42 \
  --output_dir "$OUT" --output_name "wan_char_$CID"
echo "=== TRAIN DONE: $OUT ==="
