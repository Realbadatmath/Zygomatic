# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Module constants, loggers and optional-dependency probes (original lines 34-108, 1194-1195)."""

from __future__ import annotations

import logging
import os
from zyg_workflows import paths


# Hugging Face revision for every from_pretrained/download in this module. 'main' is the
# floating default these call sites used implicitly; $ZYG_HF_REVISION pins a commit instead.
_HF_REVISION = os.environ.get('ZYG_HF_REVISION', '').strip() or 'main'

# Split deviation (the ONLY byte change in this module): the single module's __name__
# was 'zyg_workflows.comfy_generation_service'; inside this submodule __package__ is
# that exact string, so both logger names stay identical to the originals.
_neg_log = logging.getLogger(__package__)
_zyg_log = logging.getLogger(__package__)


try:
    from zyg_workflows import _comfy_client as _comfy
except ImportError:
    _comfy = None

try:
    from zyg_workflows import character_bible_service as _bible
except ImportError:
    _bible = None

try:
    from zyg_workflows import consistency_qa_service as _cqa
except ImportError:
    _cqa = None


_FLUX_DEV = str(paths.ZYG_FLUX_ROOT / 'flux1-dev')
_FLUX_SCHNELL = str(paths.ZYG_FLUX_ROOT / 'flux1-schnell')
_SDXL_TRAIN_REPO_ID = 'stabilityai/stable-diffusion-xl-base-1.0'
# Same base the SDXL LoRA trainer uses — must match Comfy ``CheckpointLoader`` weights.
_SDXL_ALIGNED_CKPT = (
    os.environ.get(
        'ZYG_SDXL_ALIGNED_CKPT',
        'sd_xl_base_1.0.safetensors',
    ).strip()
    or 'sd_xl_base_1.0.safetensors'
)
_SDXL_FALLBACK_CKPT = (
    os.environ.get(
        'ZYG_SDXL_CHECKPOINT',
        'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors',
    ).strip()
    or 'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors'
)
# 2026-07-25: SDXL is the ANIMATED path (FLUX stays photoreal). The animated
# SDXL characters render + train on a 3D-toon checkpoint (DynaVision XL); the
# photoreal SDXL bases above are only used for legacy/photoreal-SDXL renders.
_SDXL_ANIMATED_CKPT = (
    os.environ.get(
        'ZYG_SDXL_ANIMATED_CKPT',
        'DynaVisionXL.safetensors',
    ).strip()
    or 'DynaVisionXL.safetensors'
)
_SDXL_IMG2IMG_DENOISE = float(os.environ.get('ZYG_SDXL_IMG2IMG_DENOISE', '0.32'))
_CHAR_DRIFT_MIN = float(os.environ.get('ZYG_CHAR_DRIFT_MIN', '0.60'))
_CHAR_DRIFT_ANIMATED = float(os.environ.get('ZYG_CHAR_DRIFT_ANIMATED', '0.45'))
_PREVIEW_LORA_SCALE = float(os.environ.get('ZYG_PREVIEW_LORA_SCALE', '0.75'))
_PREVIEW_SDXL_STEPS = int(os.environ.get('ZYG_PREVIEW_SDXL_STEPS', '36'))
_SKIN_PORE_FACE_WILDCARD = (
    'visible skin pores, natural skin microdetail, fine facial texture, '
    'realistic subsurface skin, sharp eyelashes, detailed iris, natural skin grain, '
    'unretouched, no beauty filter, subtle skin imperfections'
)
_PREVIEW_FACE_PORE_DENOISE = float(os.environ.get('ZYG_PREVIEW_FACE_PORE_DENOISE', '0.52'))
_SMILE_FACE_WILDCARD = (
    'warm open smile, visible teeth, cheerful happy expression, natural smile lines, smiling at camera'
)
_HAND_DETAIL_WILDCARD = (
    'anatomically correct hands, five fingers per hand, detailed knuckles and nails, '
    'natural hand skin texture, symmetrical hands, open relaxed fingers'
)
_COMFY_ROOT = str(paths.ZYG_COMFY_ROOT)
_COMFY_LORA_DIR = str(paths.ZYG_COMFY_LORA_DIR)
_IPA_SCALE_DEFAULT = float(os.environ.get('ZYG_IPADAPTER_SCALE', '0.65'))


def _log_default(msg: str) -> None:
    pass
