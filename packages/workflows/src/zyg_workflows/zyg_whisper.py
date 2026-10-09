# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Shared faster-whisper loader for the crews pipeline.

2026-07-28: Consolidates transcription onto faster-whisper large-v3 with VAD.
Replaces the scattered openai-whisper `base`/`tiny` calls that "didn't hear
everything" and had no silence gating. One engine, one cache, one place to tune.

Design goals:
  • Upgrade quality: default model is `large-v3` (env-overridable).
  • VAD on by default: faster-whisper's built-in Silero `vad_filter` trims
    non-speech, which improves segmentation AND suppresses silence hallucinations.
  • VRAM-aware: large-v3 needs real headroom, so device selection checks free
    VRAM against a large-v3-appropriate floor (NOT the old 1536 MiB gate that
    was sized for `base`). Falls back to CPU, and load is retried on CPU on any
    CUDA failure — this path must never hard-crash the pipeline.
  • Cached: models are loaded once per (size, device, compute) and reused.

Env knobs:
  ZYG_WHISPER_MODEL          transcription model (default: large-v3)
  ZYG_WHISPER_FW_MIN_VRAM_MB min free VRAM to use CUDA (default: 5000)
  ZYG_WHISPER_COMPUTE        override compute_type (default: int8_float16 cuda / int8 cpu)
  ZYG_WHISPER_BEAM           beam size (default: 5)
"""

import os
import threading
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_MODEL_CACHE: dict = {}
_LOCK = threading.Lock()

DEFAULT_MODEL = os.environ.get('ZYG_WHISPER_MODEL', 'large-v3')


def _record_degrade(expected, actual, detail=''):
    """Log a silent transcription degrade to the cross-run run_ledger (2026-07-30).

    Fail-safe by construction: the ledger is stdlib-sqlite and lazily imported, and
    any failure here is swallowed — transcription must never break because a debug
    ledger is unhappy."""
    try:
        from zyg_workflows import run_ledger

        run_ledger.record_fallback('whisper', expected, actual, detail=detail)
    except Exception as _exc:
        _zyg_log.debug('degrade %s->%s not recorded in the run ledger: %s', expected, actual, _exc)


def _pick_device_compute():
    """Return (device, compute_type) sized for a large model, VRAM-permitting."""
    device, compute = 'cpu', 'int8'
    try:
        import torch

        if torch.cuda.is_available():
            free, _ = torch.cuda.mem_get_info()
            # Honor the legacy ZYG_WHISPER_MIN_VRAM_MB knob (still read by
            # murch_engine) as an alias, but default to a large-v3-appropriate floor.
            floor_mb = (
                os.environ.get('ZYG_WHISPER_FW_MIN_VRAM_MB') or os.environ.get('ZYG_WHISPER_MIN_VRAM_MB') or '5000'
            )
            floor = int(floor_mb) * 1024 * 1024
            if free >= floor:
                device, compute = 'cuda', 'int8_float16'
    except Exception as _exc:
        _zyg_log.warning('cuda sizing probe failed, transcribing on cpu/int8: %s', _exc)
    compute = os.environ.get('ZYG_WHISPER_COMPUTE', compute)
    return device, compute


def get_model(model_size: str = None):
    """Load (and cache) a faster-whisper model, VRAM-aware, CPU-safe fallback."""
    model_size = model_size or DEFAULT_MODEL
    device, compute = _pick_device_compute()
    key = (model_size, device, compute)
    with _LOCK:
        if key in _MODEL_CACHE:
            return _MODEL_CACHE[key]
        from faster_whisper import WhisperModel

        try:
            model = WhisperModel(model_size, device=device, compute_type=compute)
        except Exception as e:
            # CUDA OOM / driver / compute-type issue → CPU int8 always works.
            model = WhisperModel(model_size, device='cpu', compute_type='int8')
            key = (model_size, 'cpu', 'int8')
            if device != 'cpu':
                _record_degrade(
                    f'{device}:{model_size}:{compute}',
                    f'cpu:{model_size}:int8',
                    f'WhisperModel load failed: {str(e)[:300]}',
                )
        # Drop any stale copy of the SAME size on another device so a CPU model
        # cached under VRAM pressure (or vice-versa) isn't pinned forever.
        for _sk in [k for k in _MODEL_CACHE if k[0] == model_size and k != key]:
            _stale = _MODEL_CACHE.pop(_sk)
            del _stale
        _MODEL_CACHE[key] = model
        _maybe_free_cuda()
        return model


def transcribe_segments(
    audio_path: str,
    language: str = 'en',
    want_words: bool = False,
    vad: bool = True,
    beam_size: int = None,
    model_size: str = None,
    task: str = 'transcribe',
):
    """
    Transcribe with large-v3 + VAD. Returns (segments, info) where segments is a
    list of dicts: {start, end, text[, words]}. `info` is faster-whisper's
    TranscriptionInfo (has .language, .language_probability, .duration).

    faster-whisper decodes audio straight out of video containers via PyAV, so
    `audio_path` may be a video file (mp4/mkv) or an audio file.
    """
    # Device-aware model/beam selection. large-v3 + beam 5 on CPU turns a
    # minutes-long job into HOURS on long media, so when we land on CPU (busy GPU
    # or no CUDA) degrade to a light model + greedy search unless the caller
    # explicitly pinned a model_size.
    device, _ = _pick_device_compute()
    on_cpu = device == 'cpu'
    if model_size is None:
        model_size = os.environ.get('ZYG_WHISPER_CPU_MODEL', 'base') if on_cpu else DEFAULT_MODEL
    if beam_size is None:
        beam_size = 1 if on_cpu else int(os.environ.get('ZYG_WHISPER_BEAM', '5'))
    if on_cpu:
        _zyg_log.warning(
            f'[zyg_whisper] WARNING: low/no free VRAM — CPU transcription with '
            f"model='{model_size}' beam={beam_size} (large-v3 on CPU stalls on "
            f'long media)'
        )
        # 2026-07-30: this degrade used to exist only as a stderr line nobody diffed
        # across runs — transcripts silently came from `base`+greedy instead of
        # large-v3+beam5. Record it in the cross-run ledger. Fail-safe, lazy import.
        _record_degrade(
            f'cuda:{DEFAULT_MODEL}',
            f'cpu:{model_size}',
            f'beam={beam_size} vad={vad} audio={os.path.basename(audio_path)} '
            f'(VRAM floor '
            f'{os.environ.get("ZYG_WHISPER_FW_MIN_VRAM_MB") or os.environ.get("ZYG_WHISPER_MIN_VRAM_MB") or "5000"}MB '
            f'not met or CUDA unavailable)',
        )
    model = get_model(model_size)
    segments, info = model.transcribe(
        audio_path,
        language=language,
        task=task,
        beam_size=beam_size,
        word_timestamps=want_words,
        vad_filter=vad,
    )
    out = []
    for seg in segments:  # generator — consuming it runs the decode
        d = {'start': float(seg.start), 'end': float(seg.end), 'text': (seg.text or '').strip()}
        if want_words and seg.words:
            d['words'] = [
                {
                    'word': (w.word or '').strip(),
                    'start': float(w.start),
                    'end': float(w.end),
                    'prob': round(float(w.probability), 4),
                }
                for w in seg.words
            ]
        out.append(d)
    return out, info


def _maybe_free_cuda():
    """Best-effort GC + CUDA cache flush (no-op if torch/CUDA absent)."""
    try:
        import gc
        import torch

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception as _exc:
        _zyg_log.debug('cuda cache flush skipped: %s', _exc)


def unload_models():
    """Release all cached Whisper models and return their VRAM/RAM to the pool.

    Transcription runs in the long-lived Flask process, so a CUDA large-v3 model
    would otherwise stay resident (~1.5-2 GB VRAM) across unrelated ComfyUI/TTS
    stages. Call this once the transcript for a job is produced.
    """
    with _LOCK:
        while _MODEL_CACHE:
            _k, _m = _MODEL_CACHE.popitem()
            try:
                del _m
            except Exception as _exc:
                _zyg_log.debug('cached model %s was already released: %s', _k, _exc)
    _maybe_free_cuda()
