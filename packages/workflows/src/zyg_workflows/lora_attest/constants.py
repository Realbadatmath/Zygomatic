# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""lora_attest.py — model-file attestation for ComfyUI graphs (LoRA / checkpoint / VAE).

2026-07-30. Built for the debug-expansion round after three separate incidents where
the pipeline shipped frames from weights nobody had verified:

  * waxy-skin diagnosis (2026-07-09) — a 768px/400-step character LoRA was INERT; the
    logs happily printed its name and strength.
  * same-woman diagnosis (2026-07-17) — the LoRA switch was silently off; the graph
    still carried the LoraSelect node, it just was not wired into the model loader.
  * arcane restyle (2026-07-26) — a checkpoint pin was clobbered (Juggernaut →
    DynaVision) and produced off-model characters for a whole build.

Every one of those was invisible because nothing hashed the files the graph pointed at.
This module closes the static half of that hole:

    from zyg_workflows import lora_attest
    res = lora_attest.attest_graph(graph_dict, log_fn=log)
    # {'ok': True/False/None, 'artifacts': [...], 'mismatches': [...], ...}

and the submit-site hook:

    lora_attest.attest_submit(wf, overrides=overrides, tag='vace', log_fn=log)

The hook is WARN-ONLY by default (a broken QC layer must never block generation).
``ZYG_LORA_ATTEST=strict`` makes a failed attestation raise :class:`AttestationError`
*before* the graph reaches ComfyUI; ``ZYG_LORA_ATTEST=off`` disables it entirely.
At the three wired submit sites strict mode surfaces as a clean stop, not a
traceback: wan_video_service._submit_wan_clip returns False and the two
wan_vace_service generators return None, each with a loud log line, and the FAIL is
already in the ledger by then.

What it checks, per model file referenced anywhere in the graph
--------------------------------------------------------------
  missing_file    the name in the graph does not resolve to a file on disk
  hash_mismatch   sha256 differs from data/runtime/model_pins.json
  strength_zero   a LoRA is present at strength 0.0 → applied to nothing
  not_wired       a LoRA/model node exists but nothing downstream consumes it
                  (only checkable on a LIVE graph — pipeline_debug's captured
                  graph_*.json strips list-valued inputs, i.e. all the wiring)
  unreadable      the file resolved but could not be hashed

artifact dicts:  {'kind', 'name', 'path', 'sha256', 'strength', 'node', 'class',
                  'pinned', 'status', 'size'}
``kind`` is 'lora' | 'checkpoint' | 'vae' for the canonical three, plus
'text_encoder' | 'clip_vision' | 'controlnet' | 'upscale' | 'style_model' | 'other'
for everything else the graph may carry.

Pins file (``data/runtime/model_pins.json``) is a flat ``{name: sha256}`` map keyed by
the exact ComfyUI-relative name used in graphs (e.g. ``wan_chars/wan_char_X_t2v.safetensors``);
basename lookup is accepted as a fallback. Seed/refresh it with::

    python lora_attest.py seed            # char LoRAs + prop LoRAs + Wan T2V checkpoint
    python lora_attest.py seed --extra    # ... plus VACE module, Wan VAE, umT5 encoder
    python lora_attest.py attest <graph.json>

Hashing is sha256 with an (size, mtime_ns) cache in data/runtime/model_hash_cache.json,
so the 15 GB Wan checkpoint is read once and costs microseconds thereafter. Hashing is
delegated to ``run_ledger.sha256_file`` when that module is importable (one hashing
implementation across the debug stack) and falls back to a local implementation.

Dynamic half — ab_probe_lora() — renders a fixed-seed 5-frame 512px A/B at strength 0
vs the configured strength and requires the CLIP-embedding delta to clear a floor
(default 0.02). That is the only thing that proves a LoRA actually MOVED the model,
which is what the inert-LoRA incident needed. It is GPU work, therefore OFF by default
(``ZYG_AB_PROBE_LORA=1`` to arm) and meant to fire only when a run-diff shows a LoRA or
checkpoint hash changed.

License posture (commercial publication): stdlib hashlib/json/os (PSF), numpy (BSD),
torch (BSD-3), open_clip (MIT) — all already in the production venv. No AGPL, no
non-commercial weights. Nothing here writes a pixel into a delivered frame.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from zyg_workflows.bin import exe
from zyg_workflows import paths

# Re-export surface: these four are imported here and not used in this module —
# pins.py, gate.py, ab_probe.py and __init__.py read them off it
# (``from zyg_workflows.lora_attest.constants import hashlib, json, time, exe``).
__all__ = ['hashlib', 'json', 'time', 'exe']

_HERE = str(paths.PKG_DIR)
_RUNTIME_DIR = str(paths.DATA_DIR / 'runtime')

PINS_PATH = os.environ.get('ZYG_MODEL_PINS', os.path.join(_RUNTIME_DIR, 'model_pins.json'))
_HASH_CACHE_PATH = os.path.join(_RUNTIME_DIR, 'model_hash_cache.json')

GATE_NAME = 'lora_attest'
AB_PROBE_FLOOR = 0.02

_MODEL_EXT = ('.safetensors', '.sft', '.ckpt', '.pt', '.pth', '.bin', '.gguf', '.onnx')

# ComfyUI model sub-folders searched per (class, input-key). First match wins; an
# unknown reference falls back to a basename search across every root/sub-folder.
_NODE_FOLDERS = {
    # kijai WanVideoWrapper (the Wan2.1 stack) — folders verified against
    # custom_nodes/ComfyUI-WanVideoWrapper/nodes_model_loading.py
    ('WanVideoModelLoader', 'model'): ('checkpoint', ['diffusion_models', 'unet', 'unet_gguf', 'checkpoints']),
    ('WanVideoModelLoader', 'extra_model'): ('checkpoint', ['diffusion_models', 'unet', 'unet_gguf']),
    ('WanVideoVACEModelSelect', 'vace_model'): ('checkpoint', ['diffusion_models', 'unet', 'unet_gguf']),
    ('WanVideoLoraSelect', 'lora'): ('lora', ['loras']),
    ('WanVideoLoraSelectMulti', 'lora_0'): ('lora', ['loras']),
    ('WanVideoVAELoader', 'model_name'): ('vae', ['vae']),
    ('LoadWanVideoT5TextEncoder', 'model_name'): ('text_encoder', ['text_encoders', 'clip']),
    ('LoadWanVideoClipTextEncoder', 'model_name'): ('clip_vision', ['clip_vision', 'text_encoders']),
    # core ComfyUI
    ('CheckpointLoaderSimple', 'ckpt_name'): ('checkpoint', ['checkpoints']),
    ('CheckpointLoader', 'ckpt_name'): ('checkpoint', ['checkpoints']),
    ('UNETLoader', 'unet_name'): ('checkpoint', ['diffusion_models', 'unet']),
    ('VAELoader', 'vae_name'): ('vae', ['vae']),
    ('LoraLoader', 'lora_name'): ('lora', ['loras']),
    ('LoraLoaderModelOnly', 'lora_name'): ('lora', ['loras']),
    ('CLIPLoader', 'clip_name'): ('text_encoder', ['text_encoders', 'clip']),
    ('DualCLIPLoader', 'clip_name1'): ('text_encoder', ['text_encoders', 'clip']),
    ('DualCLIPLoader', 'clip_name2'): ('text_encoder', ['text_encoders', 'clip']),
    ('CLIPVisionLoader', 'clip_name'): ('clip_vision', ['clip_vision']),
    ('ControlNetLoader', 'control_net_name'): ('controlnet', ['controlnet']),
    ('UpscaleModelLoader', 'model_name'): ('upscale', ['upscale_models']),
    ('StyleModelLoader', 'style_model_name'): ('style_model', ['style_models']),
}

# input keys that carry a LoRA strength, per node class family
_STRENGTH_KEYS = ('strength', 'strength_model', 'lora_strength', 'strength_clip')

_ALL_FOLDERS = [
    'loras',
    'diffusion_models',
    'unet',
    'unet_gguf',
    'checkpoints',
    'vae',
    'text_encoders',
    'clip',
    'clip_vision',
    'controlnet',
    'upscale_models',
    'style_models',
    'embeddings',
    'ultralytics',
    'sams',
    'sam2',
]

# default seed set for model_pins.json — the weights that actually decide identity
_SEED_GLOBS = [
    ('loras', 'wan_chars/*.safetensors'),
    ('loras', 'wan_props/*.safetensors'),
    ('diffusion_models', 'Wan2_1-T2V-14B_fp8_e4m3fn.safetensors'),
]
_SEED_GLOBS_EXTRA = [
    ('diffusion_models', 'Wan2_1-VACE_module_14B_fp8_e4m3fn.safetensors'),
    ('vae', 'Wan2_1_VAE_bf16.safetensors'),
    ('text_encoders', 'umt5-xxl-enc-bf16.safetensors'),
]


class AttestationError(RuntimeError):
    """Raised ONLY in strict mode (ZYG_LORA_ATTEST=strict), before submit."""


def _log_noop(_m):
    pass


def _truthy(v):
    return str(v or '').strip().lower() in ('1', 'true', 'yes', 'on')


# ── ledger bridge (run_ledger is built in parallel; never a hard dependency) ──


def _ledger():
    """Return the run_ledger module or None. Never raises."""
    try:
        from zyg_workflows import run_ledger

        return run_ledger
    except Exception:
        return None


def _run_id(run_id=None):
    return run_id or os.environ.get('ZYG_RUN_ID') or 'adhoc'


def _record_gate(run_id, outcome, score=None, tag=''):
    rl = _ledger()
    if rl is None:
        return False
    try:
        rl.record_gate(_run_id(run_id), GATE_NAME, outcome, score=score, tag=tag)
        return True
    except Exception:
        return False


def _record_fallback(component, expected, actual, detail='', run_id=None):
    rl = _ledger()
    if rl is None:
        return False
    try:
        rl.record_fallback(component, expected, actual, detail=detail, run_id=_run_id(run_id))
        return True
    except Exception:
        return False
