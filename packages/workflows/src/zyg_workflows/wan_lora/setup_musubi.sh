#!/bin/bash

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# setup_musubi.sh — one-time setup for Wan character-LoRA training (2026-07-29).
# Isolated from the main agents venv (same pattern as the NeMo diarizer). Apache-2.0 stack.
set -e
MODELS_ROOT="${ZYG_MODELS_ROOT:-$HOME/ai-models}"
ROOT="$MODELS_ROOT/musubi-tuner"
MODELS="$MODELS_ROOT/wan_train_models"
mkdir -p "$MODELS"

echo "== clone =="
if [ ! -d "$ROOT/.git" ]; then
  git clone --depth 1 https://github.com/kohya-ss/musubi-tuner "$ROOT"
fi

echo "== venv =="
if [ ! -f "$ROOT/venv/bin/python" ]; then
  python3 -m venv "$ROOT/venv"
fi
"$ROOT/venv/bin/pip" install --upgrade pip -q
# torch first (CUDA 12.x wheel), then musubi + deps
"$ROOT/venv/bin/pip" install -q torch torchvision --index-url https://download.pytorch.org/whl/cu124
"$ROOT/venv/bin/pip" install -q -e "$ROOT"
"$ROOT/venv/bin/pip" install -q accelerate bitsandbytes protobuf six pillow

echo "== model downloads (musubi-supported formats) =="
export HF_HUB_ENABLE_HF_TRANSFER=0
# DiT: Comfy-Org repackaged I2V 720p fp8 (musubi wan.md-supported single file)
[ -f "$MODELS/wan2.1_i2v_720p_14B_fp8_e4m3fn.safetensors" ] || \
  hf download Comfy-Org/Wan_2.1_ComfyUI_repackaged \
    split_files/diffusion_models/wan2.1_i2v_720p_14B_fp8_e4m3fn.safetensors \
    --local-dir "$MODELS/_dl" && \
  { [ -f "$MODELS/wan2.1_i2v_720p_14B_fp8_e4m3fn.safetensors" ] || \
    mv "$MODELS/_dl/split_files/diffusion_models/wan2.1_i2v_720p_14B_fp8_e4m3fn.safetensors" "$MODELS/"; }
# official T5 + CLIP (musubi expects the official .pth files)
[ -f "$MODELS/models_t5_umt5-xxl-enc-bf16.pth" ] || \
  hf download Wan-AI/Wan2.1-I2V-14B-720P models_t5_umt5-xxl-enc-bf16.pth --local-dir "$MODELS"
[ -f "$MODELS/models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth" ] || \
  hf download Wan-AI/Wan2.1-I2V-14B-720P models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth --local-dir "$MODELS"
# VAE: official Wan VAE
[ -f "$MODELS/Wan2.1_VAE.pth" ] || \
  hf download Wan-AI/Wan2.1-I2V-14B-720P Wan2.1_VAE.pth --local-dir "$MODELS"

echo "== sanity =="
"$ROOT/venv/bin/python" -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
ls -la "$MODELS" | grep -vE "^total|^d"
echo "=== SETUP DONE ==="
