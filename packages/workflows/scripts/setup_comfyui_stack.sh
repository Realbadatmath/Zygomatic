#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Bootstrap ComfyUI for Zygomatic continuity + pose-locked contact sheets.
set -euo pipefail

COMFY_ROOT="${ZYG_COMFY_ROOT:-${ZYG_MODELS_ROOT:-$HOME/ai-models}/comfyui}"
CREWS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CUSTOM="${COMFY_ROOT}/custom_nodes"
VENV_PY="${COMFY_ROOT}/.venv/bin/python"
HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
CLIP_VIT_CACHE="${HF_HOME}/hub/models--openai--clip-vit-large-patch14/snapshots"

echo "==> Custom nodes: x-flux-comfyui (Flux IPAdapter + XlabsSampler)"
if [ ! -d "${CUSTOM}/x-flux-comfyui" ]; then
  git clone --depth 1 https://github.com/XLabs-AI/x-flux-comfyui.git "${CUSTOM}/x-flux-comfyui"
fi

echo "==> Symlink FLUX IP-Adapter weights"
mkdir -p "${COMFY_ROOT}/models/xlabs/ipadapters"
IPA_SRC=$(find "${HF_HOME}/hub/models--XLabs-AI--flux-ip-adapter/snapshots" -name ip_adapter.safetensors 2>/dev/null | head -1 || true)
if [ -z "${IPA_SRC}" ]; then
  "${VENV_PY}" -c "
from huggingface_hub import hf_hub_download
import os
d='${COMFY_ROOT}/models/xlabs/ipadapters'
os.makedirs(d, exist_ok=True)
hf_hub_download('XLabs-AI/flux-ip-adapter', 'ip_adapter.safetensors', local_dir=d)
" 2>/dev/null || true
  IPA_SRC="${COMFY_ROOT}/models/xlabs/ipadapters/ip_adapter.safetensors"
fi
if [ -n "${IPA_SRC}" ] && [ -f "${IPA_SRC}" ]; then
  ln -sf "${IPA_SRC}" "${COMFY_ROOT}/models/xlabs/ipadapters/flux-ip-adapter.safetensors"
  echo "    OK: flux-ip-adapter.safetensors"
else
  echo "    WARN: flux-ip-adapter.safetensors missing"
fi

echo "==> CLIP vision for IP-Adapter (clip-vit — open-clip breaks LoadFluxIPAdapter)"
mkdir -p "${COMFY_ROOT}/models/clip_vision"
CLIP_SNAP=$(find "${CLIP_VIT_CACHE}" -name model.safetensors 2>/dev/null | head -1 || true)
if [ -z "${CLIP_SNAP}" ]; then
  "${VENV_PY}" -c "from huggingface_hub import snapshot_download; snapshot_download('openai/clip-vit-large-patch14')" 2>/dev/null || true
  CLIP_SNAP=$(find "${CLIP_VIT_CACHE}" -name model.safetensors 2>/dev/null | head -1 || true)
fi
if [ -n "${CLIP_SNAP}" ] && [ -f "${CLIP_SNAP}" ]; then
  ln -sf "${CLIP_SNAP}" "${COMFY_ROOT}/models/clip_vision/clip-vit-large-patch14-ipa.safetensors"
  cp -n "${COMFY_ROOT}/models/clip_vision/flux_clip_config.json" \
    "$(dirname "${CLIP_SNAP}")/flux_clip_config.json" 2>/dev/null || true
  echo "    OK: clip-vit-large-patch14-ipa.safetensors"
else
  echo "    WARN: clip-vit-large-patch14 not found for IP-Adapter"
fi

echo "==> Shakker Union ControlNet (pose mode for FLUX)"
mkdir -p "${COMFY_ROOT}/models/controlnet"
UNION_DST="${COMFY_ROOT}/models/controlnet/FLUX.1-dev-ControlNet-Union-Pro.safetensors"
if [ ! -f "${UNION_DST}" ]; then
  "${VENV_PY}" -c "
from huggingface_hub import hf_hub_download
import os, shutil
dest='${UNION_DST}'
os.makedirs(os.path.dirname(dest), exist_ok=True)
p=hf_hub_download('Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro', 'diffusion_pytorch_model.safetensors')
shutil.copy2(p, dest)
print('    downloaded', dest)
" 2>&1 | tail -3
else
  echo "    OK: Union ControlNet already present"
fi

echo "==> Static OpenPose pose library (24 angles)"
python3 "${CREWS}/scripts/generate_contact_sheet_poses.py" --out-dir "${CREWS}/assets/contact_sheet_poses"

echo "==> FLUX text encoders (if missing)"
CLIP_DIR="${COMFY_ROOT}/models/clip"
mkdir -p "${CLIP_DIR}"
for f in t5xxl_fp8_e4m3fn.safetensors clip_l.safetensors; do
  if [ ! -f "${CLIP_DIR}/${f}" ]; then
    echo "    Downloading ${f}…"
    wget -q -O "${CLIP_DIR}/${f}" \
      "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/${f}" || true
  fi
done

echo "==> Restart ComfyUI"
if pgrep -f "comfyui/.venv/bin/python main.py" >/dev/null; then
  pkill -f "comfyui/.venv/bin/python main.py" || true
  sleep 2
fi
nohup bash "${COMFY_ROOT}/start_server.sh" >/dev/null 2>&1 &
for _i in $(seq 1 30); do
  curl -sf http://127.0.0.1:8188/system_stats >/dev/null && break
  sleep 1
done
if curl -sf http://127.0.0.1:8188/system_stats >/dev/null; then
  echo "    ComfyUI OK on :8188"
  curl -s http://127.0.0.1:8188/object_info | "${VENV_PY}" -c "
import json,sys
d=json.load(sys.stdin)
for k in ('LoadFluxIPAdapter','XlabsSampler','SetShakkerLabsUnionControlNetType','ControlNetApplyAdvanced'):
    print('   ', k + ':', k in d)
"
  cd "${CREWS}" && python3 -c "
import comfy_generation_service as c
print('    pose_locked_stack_ready:', c.pose_locked_stack_ready())
"
else
  echo "    WARN: ComfyUI not responding"
fi

echo "Done. Set ZYG_COMFY_PRIMARY=1, ZYG_CONTACT_SHEET_MODE=auto, restart crewai_web_gui."
