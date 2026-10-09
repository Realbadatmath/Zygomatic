# ruff: noqa: F401  the original module's top import block lives here; siblings re-import from it
# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The original top import block, the filesystem roots, the licence-tripwire
tables and the shared helpers (verbatim from bp_integrity_ops_steps.py)."""

import concurrent.futures as _cf_ig
import functools
import glob as _g
import json
import logging as _zyg_logging
import os
import re
import shutil as _shu_ig
import subprocess

from zyg_workflows import paths
from zyg_workflows.bin import exe

from zyg_dashboard.gui.runtime_state import _RUNTIME_DIR, _runtime_path
from zyg_dashboard.crewai_web_gui import _STYLE_LORA_DIR, _gpu_work_active
from zyg_dashboard import crewai_web_gui as _main_mod

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_integrity_ops_steps')


# ── Filesystem roots (computed once at import, as the closures did per call) ──
_COMFY_ROOT = str(paths.ZYG_COMFY_ROOT)
_COMFY_MODELS = os.path.join(_COMFY_ROOT, 'models')
_HF_HUB = os.path.join(os.environ.get('HF_HOME', str(paths.ZYG_HOME / '.cache' / 'huggingface')), 'hub')

# nvidia-smi reports a process name, not a role. The first substring that matches
# wins, in this order — the same order the nested conditional chain tested.
_GPU_HOLDER_LABELS = (
    ('comfyui', 'ComfyUI'),
    ('ollama', 'Ollama'),
    ('indextts', 'IndexTTS-2'),
    ('chatterbox', 'Chatterbox'),
    ('vlm_judge', 'VLM judge'),
    ('agents/.venv', 'GUI'),
)

# Weights deleted on licence grounds: ABSENT is the passing state.
_FLUX_DEV_GLOBS = (
    os.path.join(str(paths.ZYG_FLUX_ROOT), 'flux1-dev'),
    os.path.join(_COMFY_MODELS, '*', 'flux1-dev*'),
    os.path.join(_COMFY_MODELS, '*', 'flux1-fill-dev*'),
    os.path.join(_COMFY_MODELS, 'controlnet', '*FLUX.1-dev*'),
)
_FLUX_DEV_HF_REPOS = (
    'models--black-forest-labs--FLUX.1-dev',
    'models--black-forest-labs--FLUX.1-Fill-dev',
    'models--InstantX--FLUX.1-dev-Controlnet-Union',
    'models--Shakker-Labs--FLUX.1-dev-ControlNet-Union-Pro',
)

_SDXL_CHECKPOINTS = (
    'sd_xl_base_1.0.safetensors',
    'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors',
    'DynaVisionXL.safetensors',
)


# ── shared helpers ───────────────────────────────────────────────────────────
def _env_on(name, default=''):
    return os.environ.get(name, default).strip().lower() in ('1', 'true', 'yes', 'on')


def _comfy_files(pairs):
    """[(models subdir, filename)] -> (missing 'subdir/name' list, GB present)."""
    _missing, _gb = [], 0.0
    for _sub, _name in pairs:
        _p = os.path.join(_COMFY_MODELS, _sub, _name)
        if os.path.isfile(_p):
            _gb += os.path.getsize(_p) / 1024**3
        else:
            _missing.append(f'{_sub}/{_name}')
    return _missing, _gb


def _hf_weight_files(repo_dir):
    """Weight files in an HF cache repo. Deletions leave ~12 KB metadata
    stubs (refs + README) behind, and a stub is not a weight."""
    return [
        f
        for f in _g.glob(os.path.join(_HF_HUB, repo_dir, 'snapshots', '**', '*'), recursive=True)
        if f.endswith(('.safetensors', '.bin', '.pth', '.ckpt', '.gguf')) and os.path.isfile(f)
    ]


# Mirrors of comfy_generation_service's resolvers (qwen_t2i_unet,
# qwen_edit_unet, klein_t2i_unet / klein_text_encoder / klein_vae,
# has_qwen_hand_inpaint) — keep the env names and candidate order in step.
# Not imported on purpose: comfy_generation_service imports
# consistency_qa_service, which loads CLIP ViT-B-32 onto the GPU at import
# time, and a health check must not be what puts a model in the GUI process.
def _first_model(subdir, env, candidates):
    _override = os.environ.get(env, '').strip()
    for _n in [_override] if _override else candidates:
        if _n and os.path.isfile(os.path.join(_COMFY_MODELS, subdir, _n)):
            return _n
    return None


def _qwen_t2i_unet():
    return _first_model('diffusion_models', 'ZYG_QWEN_T2I_UNET', ['qwen_image_2512_fp8_e4m3fn.safetensors'])
