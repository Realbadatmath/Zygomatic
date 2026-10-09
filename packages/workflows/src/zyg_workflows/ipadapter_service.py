# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 9 — IPAdapter face/subject consistency conditioning.

Loads an IP-Adapter image encoder and injects reference conditioning into
the FLUX pipeline so characters/subjects maintain consistent appearance
(face structure, skin tone, hair, clothing) across all slots in a pipeline run.

Architecture
------------
We use diffusers' built-in ``IPAdapterMixin.load_ip_adapter()`` with the
XLabs IP-Adapter for FLUX.  The adapter weights are loaded once for the
entire pipeline run and applied per-slot for identity tags.

XLabs ships only ``ip_adapter.safetensors``; diffusers also needs
``openai/clip-vit-large-patch14`` as the image encoder (see XLabs README).

Usage
-----
    from zyg_workflows import ipadapter_service as ipa

    ipa.setup(flux_pipe, log_fn=_log)
    ipa.condition_pipe(flux_pipe, subject_key, scale=0.6, log_fn=_log)
    ipa.reset_conditioning(flux_pipe)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from PIL import Image
import logging as _zyg_logging


# Hugging Face revision for every from_pretrained/download in this module. 'main' is the
# floating default these call sites used implicitly; $ZYG_HF_REVISION pins a commit instead.
_HF_REVISION = os.environ.get('ZYG_HF_REVISION', '').strip() or 'main'

_zyg_log = _zyg_logging.getLogger(__name__)


_IP_ADAPTER_REPO = 'XLabs-AI/flux-ip-adapter'
_IP_ADAPTER_WEIGHT = 'ip_adapter.safetensors'
_IMAGE_ENCODER_REPO = 'openai/clip-vit-large-patch14'
_MIN_VRAM_GB = 2.0  # adapter + CLIP headroom

_adapter_loaded = False
_reference_cache: dict[str, Image.Image] = {}


def _hf_token() -> str | None:
    tok = (os.environ.get('HF_TOKEN') or os.environ.get('HUGGING_FACE_HUB_TOKEN') or '').strip()
    if tok:
        return tok
    try:
        env_path = Path(__file__).resolve().parents[2] / '.env'
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith('HF_TOKEN='):
                return line.split('=', 1)[1].strip().strip('"').strip("'") or None
    except OSError as _exc:
        _zyg_log.debug('HF token lookup in .env skipped: %s', _exc)
    return None


def ensure_image_encoder_cached(log_fn: Callable[[str], None] | None = None) -> bool:
    """Download/cache CLIP vision encoder required by FLUX IP-Adapter."""

    def _log(m: str) -> None:
        if log_fn:
            log_fn(m)

    try:
        from huggingface_hub import snapshot_download, try_to_load_from_cache

        if try_to_load_from_cache(_IMAGE_ENCODER_REPO, 'config.json') is not None:
            return True
        _log(f'Stage 9/IPAdapter: caching {_IMAGE_ENCODER_REPO}…')
        snapshot_download(
            _IMAGE_ENCODER_REPO,
            token=_hf_token(),
            local_files_only=False,
            revision=_HF_REVISION,
        )
        return True
    except Exception as e:
        _log(f'Stage 9/IPAdapter: image encoder cache failed — {e}')
        return False


def setup(
    flux_pipe,
    log_fn: Callable[[str], None] | None = None,
) -> bool:
    """Attempt to load IP-Adapter weights into the FLUX pipeline.

    Returns True if loaded successfully, False if skipped.
    """
    global _adapter_loaded

    def _log(m: str) -> None:
        if log_fn:
            log_fn(m)

    if _adapter_loaded:
        return True

    if not _check_vram(_MIN_VRAM_GB, _log):
        return False

    try:
        from huggingface_hub import try_to_load_from_cache

        cached = try_to_load_from_cache(_IP_ADAPTER_REPO, _IP_ADAPTER_WEIGHT)
        if cached is None:
            _log(
                f'Stage 9/IPAdapter: {_IP_ADAPTER_REPO} not in HF cache — '
                'use Settings → HuggingFace → Download IPAdapter'
            )
            return False
    except Exception as e:
        _log(f'Stage 9/IPAdapter: cache lookup failed — {e}')
        return False

    if not ensure_image_encoder_cached(_log):
        return False

    adapter_dir = os.path.dirname(cached)

    try:
        import torch
        from transformers import CLIPImageProcessor, CLIPVisionModelWithProjection

        if getattr(flux_pipe, 'image_encoder', None) is None:
            _log(f'Stage 9/IPAdapter: loading image encoder ({_IMAGE_ENCODER_REPO})…')
            _enc = CLIPVisionModelWithProjection.from_pretrained(
                _IMAGE_ENCODER_REPO,
                torch_dtype=getattr(flux_pipe, 'dtype', torch.bfloat16),
                token=_hf_token(),
                local_files_only=False,
                revision=_HF_REVISION,
            )
            _dev = getattr(flux_pipe, 'device', None)
            if _dev is not None:
                _enc = _enc.to(_dev)
            flux_pipe.register_modules(image_encoder=_enc)

        if getattr(flux_pipe, 'feature_extractor', None) is None:
            _clip_size = 224
            if getattr(flux_pipe, 'image_encoder', None) is not None:
                _clip_size = flux_pipe.image_encoder.config.image_size
            flux_pipe.register_modules(
                feature_extractor=CLIPImageProcessor(
                    size=_clip_size,
                    crop_size=_clip_size,
                ),
            )

        flux_pipe.load_ip_adapter(
            adapter_dir,
            subfolder='',
            weight_name=_IP_ADAPTER_WEIGHT,
            image_encoder_folder=None,
            local_files_only=True,
        )
        _adapter_loaded = True
        _log(f'Stage 9/IPAdapter: adapter loaded ({_IP_ADAPTER_REPO})')
        return True
    except Exception as e:
        _msg = str(e)
        if "couldn't connect" in _msg.lower() and 'cached files' in _msg.lower():
            _log(
                'Stage 9/IPAdapter: load failed — missing local weights '
                f'(adapter dir: {adapter_dir}). Download IPAdapter + CLIP via dashboard.'
            )
        else:
            _log(f'Stage 9/IPAdapter: load failed — {e}')
        return False


def register_reference(subject_key: str, image_path: str) -> None:
    """Store the first generated image as the reference for *subject_key*."""
    if subject_key in _reference_cache:
        return
    try:
        img = Image.open(image_path).convert('RGB')
        _reference_cache[subject_key] = img
    except Exception as _exc:
        _zyg_log.warning(
            'reference image %s unreadable, IP-Adapter conditioning for %s will be skipped: %s',
            image_path,
            subject_key,
            _exc,
        )


def condition_pipe(
    flux_pipe,
    subject_key: str,
    scale: float = 0.6,
    log_fn: Callable[[str], None] | None = None,
) -> bool:
    """Apply IP-Adapter conditioning to *flux_pipe* for *subject_key*."""

    def _log(m: str) -> None:
        if log_fn:
            log_fn(m)

    if not _adapter_loaded:
        return False

    ref_img = _reference_cache.get(subject_key)
    if ref_img is None:
        return False

    try:
        flux_pipe.set_ip_adapter_scale(scale)
        _log(f'Stage 9/IPAdapter: conditioning "{subject_key[:30]}" scale={scale}')
        return True
    except Exception as e:
        _log(f'Stage 9/IPAdapter: conditioning failed — {e}')
        return False


def get_reference_image(subject_key: str) -> Image.Image | None:
    """Return the stored reference PIL image or None."""
    return _reference_cache.get(subject_key)


def reset_conditioning(flux_pipe) -> None:
    """Remove IP-Adapter scale (reset to 0.0) after a generation."""
    try:
        if _adapter_loaded:
            flux_pipe.set_ip_adapter_scale(0.0)
    except Exception as _exc:
        _zyg_log.debug('IP-Adapter scale reset skipped: %s', _exc)


def teardown(
    flux_pipe,
    log_fn: Callable[[str], None] | None = None,
) -> None:
    """Unload IP-Adapter weights to free VRAM."""
    global _adapter_loaded

    def _log(m: str) -> None:
        if log_fn:
            log_fn(m)

    if not _adapter_loaded:
        return
    try:
        flux_pipe.unload_ip_adapter()
        _adapter_loaded = False
        _reference_cache.clear()
        _log('Stage 9/IPAdapter: unloaded')
    except Exception as e:
        _log(f'Stage 9/IPAdapter: teardown warning — {e}')


def _check_vram(min_gb: float, log_fn: Callable[[str], None]) -> bool:
    try:
        import torch

        if not torch.cuda.is_available():
            return False
        total_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
        alloc_gb = torch.cuda.memory_allocated(0) / 1024**3
        free_gb = total_gb - alloc_gb
        if free_gb < min_gb:
            log_fn(f'Stage 9/IPAdapter: only {free_gb:.1f} GB VRAM free (need {min_gb}) — skipping')
            return False
        return True
    except Exception:
        return False
