# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""vfx_embed.py — frozen DINOv2 features for the VFX Analyzer.

One backbone, loaded once, never trained. Every frame becomes a 768-float
vector, and every probe in vfx_probes reads that same vector.

Why this shape
--------------
The expensive part of a learned detector is the forward pass. Sharing ONE
forward pass across every probe is what makes the marginal cost of the hundredth
observable approximately zero: a probe is a 768xN matrix (~74 KB), so a hundred
of them evaluate as a single matmul against a cached embedding. The alternative —
one trained network per observable — costs a multi-GB model and another few
hundred milliseconds per frame, each time.

DINOv2 is self-supervised: it was trained without labels, to place similar images
near each other. That is why a linear probe on top needs a couple of hundred
labels rather than tens of thousands. You are not teaching it to see; you are
finding the plane that separates classes it already puts in different places.

Measured on this machine (RTX 4090, fp16, batch 64):
    2115 frames/s pure GPU, ~170 frames/s including PNG decode from disk
    0.58 GB VRAM
    facebook/dinov2-base -> 768-d CLS token, 256 patch tokens

Licence: DINOv2 code and weights are Apache-2.0. Nothing here is NC.
"""

import os
import threading

import numpy as np
import logging as _zyg_logging
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


_HERE = os.path.dirname(os.path.abspath(__file__))
BACKBONE = os.environ.get('ZYG_VFX_BACKBONE', 'facebook/dinov2-base')
#: Hub revision the backbone is fetched at. 'main' is NOT a pin — the model card carries no
#: commit this repository can cite, so it is stated rather than implied; set
#: $ZYG_VFX_BACKBONE_REVISION to a commit sha to pin the weights for a reproducible run.
BACKBONE_REVISION = os.environ.get('ZYG_VFX_BACKBONE_REVISION', 'main')
BATCH = int(os.environ.get('ZYG_VFX_EMBED_BATCH', 64))
# Leave headroom: the render pipeline shares this card and a scan must never be
# the reason a render OOMs.
MIN_FREE_MB = int(os.environ.get('ZYG_VFX_EMBED_MIN_FREE_MB', 2000))

_MODEL = {'m': None, 'proc': None, 'dev': None, 'dim': 0, 'err': ''}
_LOCK = threading.Lock()


def _free_vram_mb():
    try:
        import subprocess

        out = subprocess.run(
            [exe('nvidia-smi'), '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=8,
        )
        vals = [int(x) for x in out.stdout.split() if x.strip().isdigit()]
        return max(vals) if vals else None
    except Exception:  # noqa: BLE001
        return None


def available():
    """Can the embedding tier run right now? Reports the reason when not, so a
    probe that could not be evaluated reads as UNMEASURABLE rather than absent."""
    info = {'backbone': BACKBONE, 'ok': False, 'device': '', 'dim': 0, 'note': ''}
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except Exception as e:  # noqa: BLE001
        info['note'] = f'{type(e).__name__}: {e}'
        return info
    from huggingface_hub import try_to_load_from_cache

    hit = try_to_load_from_cache(BACKBONE, 'model.safetensors')
    if not isinstance(hit, str):
        hit = try_to_load_from_cache(BACKBONE, 'pytorch_model.bin')
    if not isinstance(hit, str):
        info['note'] = f'{BACKBONE} not in the local HF cache'
        return info
    free = _free_vram_mb()
    info.update(
        ok=True, device='cuda' if (free or 0) > MIN_FREE_MB else 'cpu', dim=_MODEL['dim'] or 768, free_vram_mb=free
    )
    if info['device'] == 'cpu':
        info['note'] = (
            f'only {free} MB VRAM free (< {MIN_FREE_MB}) — embedding on CPU, roughly 20x slower but still correct'
        )
    return info


def _load():
    with _LOCK:
        if _MODEL['m'] is not None or _MODEL['err']:
            return _MODEL
        try:
            import torch
            from transformers import AutoImageProcessor, AutoModel

            free = _free_vram_mb()
            dev = 'cuda' if (torch.cuda.is_available() and (free or 0) > MIN_FREE_MB) else 'cpu'
            proc = AutoImageProcessor.from_pretrained(BACKBONE, use_fast=True, revision=BACKBONE_REVISION)
            m = AutoModel.from_pretrained(BACKBONE, revision=BACKBONE_REVISION).to(dev).eval()
            if dev == 'cuda':
                m = m.half()
            _MODEL.update(m=m, proc=proc, dev=dev, dim=int(m.config.hidden_size))
        except Exception as e:  # noqa: BLE001
            _MODEL['err'] = f'{type(e).__name__}: {e}'
        return _MODEL


def dim():
    st = _load()
    return st['dim'] or 768


def embed_images(pil_images, log_fn=None):
    """Embed a list of PIL images -> (N, dim) float32. Empty list -> (0, dim)."""
    import torch

    st = _load()
    if st['err'] or st['m'] is None:
        raise RuntimeError(f'embedding backbone unavailable: {st["err"]}')
    out = []
    for i in range(0, len(pil_images), BATCH):
        chunk = pil_images[i : i + BATCH]
        with torch.no_grad():
            b = st['proc'](images=chunk, return_tensors='pt').to(st['dev'])
            if st['dev'] == 'cuda':
                b['pixel_values'] = b['pixel_values'].half()
            # The CLS token is the image-level summary. Patch tokens (also
            # returned by the backbone) are what a LOCALISING probe would need;
            # this tier answers WHAT, deliberately not WHERE.
            out.append(st['m'](**b).last_hidden_state[:, 0].float().cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, dim()), np.float32)


def embed_paths(paths, log_fn=None):
    """Embed image files by path. Unreadable files get a zero row, and their
    index is returned, so a corrupt frame never silently shifts the alignment
    between features and frame numbers."""
    from PIL import Image

    feats, bad = [], []
    for i in range(0, len(paths), BATCH):
        chunk = paths[i : i + BATCH]
        ims, keep = [], []
        for j, p in enumerate(chunk):
            try:
                ims.append(Image.open(p).convert('RGB'))
                keep.append(j)
            except Exception:  # noqa: BLE001
                bad.append(i + j)
        block = np.zeros((len(chunk), dim()), np.float32)
        if ims:
            block[keep] = embed_images(ims)
        feats.append(block)
    X = np.concatenate(feats) if feats else np.zeros((0, dim()), np.float32)
    if bad and log_fn:
        log_fn(f'[vfx-embed] {len(bad)} unreadable frame(s) embedded as zeros: {bad[:8]}')
    return X, bad


def unload():
    """Release the backbone. The scan holds the card for as little as possible."""
    with _LOCK:
        if _MODEL['m'] is None:
            return
        _MODEL['m'] = None
        _MODEL['proc'] = None
        try:
            import gc
            import torch

            gc.collect()
            torch.cuda.empty_cache()
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('vram release skipped: %s', _exc)
