# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""musicgen_service.py — Local AI background music generation via Meta MusicGen.

Uses facebook/musicgen-small (~300MB) via HuggingFace transformers.
Generates ~30s of music from a text prompt at 32kHz, saved as WAV then
converted to MP3 via ffmpeg.

Main API
--------
  generate(prompt, out_path, duration_s=30, *, log_fn=None) → bool
  is_available() → bool
  model_id() → str
"""

from __future__ import annotations
import os
import subprocess
import logging
import logging as _zyg_logging
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


_log = logging.getLogger(__name__)

# Model size options (trade-off: quality vs VRAM vs speed)
# small  ~ 300 MB,  ~2 GB VRAM,  ~15s generate time for 30s clip
# medium ~ 1.5 GB,  ~4 GB VRAM,  ~40s generate time for 30s clip
# large  ~ 3.3 GB,  ~8 GB VRAM,  ~90s generate time for 30s clip
MODEL_ID = os.environ.get('MUSICGEN_MODEL', 'facebook/musicgen-small')
#: Hub revision MODEL_ID is loaded at. MODEL_ID is configurable, so no single commit sha
#: can be hardcoded; set MUSICGEN_MODEL_REVISION to a sha to pin a specific snapshot.
MODEL_REVISION = os.environ.get('MUSICGEN_MODEL_REVISION', '') or 'main'

_processor = None
_model = None
_loaded_id = None


def is_available() -> bool:
    """Return True if MusicGen dependencies are importable."""
    try:
        from transformers import AutoProcessor, MusicgenForConditionalGeneration  # noqa
        import scipy  # noqa

        return True
    except ImportError:
        return False


def model_id() -> str:
    return MODEL_ID


def _load(log_fn=None):
    """Lazy-load the MusicGen model into VRAM (idempotent)."""
    global _processor, _model, _loaded_id

    def _notify(msg):
        if log_fn:
            log_fn(msg)
        else:
            _log.info(msg)

    if _model is not None and _loaded_id == MODEL_ID:
        return True

    try:
        import torch
        from transformers import AutoProcessor, MusicgenForConditionalGeneration

        _notify(f'Loading MusicGen model: {MODEL_ID}…')
        _processor = AutoProcessor.from_pretrained(MODEL_ID, revision=MODEL_REVISION)
        _model = MusicgenForConditionalGeneration.from_pretrained(MODEL_ID, revision=MODEL_REVISION)

        if torch.cuda.is_available():
            _model = _model.to('cuda')
            _notify(f'MusicGen loaded on GPU ✓ ({MODEL_ID})')
        else:
            _notify(f'MusicGen loaded on CPU — will be slow ({MODEL_ID})')

        _loaded_id = MODEL_ID
        return True
    except Exception as e:
        _notify(f'MusicGen load failed: {e}')
        return False


def unload():
    """Release model from VRAM (call after BGM is generated to free memory)."""
    global _processor, _model, _loaded_id
    if _model is not None:
        try:
            import torch

            _model.cpu()
            del _model
            del _processor
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception as _exc:
            _zyg_log.debug('MusicGen unload from VRAM incomplete: %s', _exc)
        _model = _processor = _loaded_id = None


def generate(
    prompt: str,
    out_path: str,
    duration_s: int = 30,
    *,
    seed: int | None = None,
    log_fn=None,
) -> bool:
    """Generate background music from *prompt* and save as MP3 at *out_path*.

    Parameters
    ----------
    prompt:     Text description of desired music (e.g. 'epic orchestral battle music').
    out_path:   Destination .mp3 path.
    duration_s: Approximate duration in seconds (capped at 30 by musicgen-small).
    seed:       Random seed for reproducibility. If None, a random seed is used each call.
    log_fn:     Optional callback for progress messages.

    Returns True on success.
    """

    def _notify(msg):
        if log_fn:
            log_fn(msg)
        else:
            _log.info(msg)

    if os.path.exists(out_path) and os.path.getsize(out_path) > 10_000:
        _notify(f'MusicGen: using cached track {os.path.basename(out_path)}')
        return True

    if not _load(log_fn=log_fn):
        return False

    try:
        import torch
        import numpy as np
        import scipy.io.wavfile as _wav
        import random as _random_mod

        if seed is None:
            seed = _random_mod.randint(0, 2**31 - 1)

        _notify(f'MusicGen: generating {duration_s}s — "{prompt[:80]}" (seed={seed})')

        # Set global seed — MusicGen doesn't accept a generator kwarg
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)

        inputs = _processor(
            text=[prompt],
            padding=True,
            return_tensors='pt',
        )
        if torch.cuda.is_available():
            inputs = {k: v.to('cuda') for k, v in inputs.items()}

        # max_new_tokens: musicgen-small produces 50 tokens/second at 32kHz
        # so duration_s * 50 tokens = target length
        max_tokens = min(duration_s * 50, 1500)  # cap at 30s for small model

        with torch.no_grad():
            audio_values = _model.generate(**inputs, max_new_tokens=max_tokens, do_sample=True, guidance_scale=3.0)

        # audio_values: [batch, channels, samples] on GPU
        audio_np = audio_values[0, 0].cpu().numpy()
        # Normalise to int16
        audio_np = np.clip(audio_np, -1.0, 1.0)
        audio_int16 = (audio_np * 32767).astype(np.int16)

        sample_rate = _model.config.audio_encoder.sampling_rate  # 32000
        wav_path = out_path.replace('.mp3', '.wav')
        _wav.write(wav_path, sample_rate, audio_int16)

        # Convert WAV → MP3 via ffmpeg
        r = subprocess.run(
            [exe('ffmpeg'), '-y', '-i', wav_path, '-b:a', '192k', out_path],
            capture_output=True,
            timeout=60,
        )
        try:
            os.remove(wav_path)
        except OSError as _exc:
            _zyg_log.debug('intermediate wav %s removal skipped: %s', wav_path, _exc)

        if r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 10_000:
            sz_kb = os.path.getsize(out_path) // 1024
            _notify(f'MusicGen: ✅ generated {os.path.basename(out_path)} ({sz_kb}KB, {duration_s}s)')
            return True

        _notify(f'MusicGen: ffmpeg conversion failed — {r.stderr.decode()[:200]}')
        return False

    except Exception as e:
        _notify(f'MusicGen: generation error — {e}')
        return False
    finally:
        # Always free VRAM after generation so WAN/FLUX can load
        unload()
