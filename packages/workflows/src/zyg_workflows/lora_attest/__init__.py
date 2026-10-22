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

from zyg_workflows.lora_attest.constants import (
    annotations,
    hashlib,
    json,
    os,
    time,
    exe,
    paths,
    _HERE,
    _RUNTIME_DIR,
    PINS_PATH,
    _HASH_CACHE_PATH,
    GATE_NAME,
    AB_PROBE_FLOOR,
    _MODEL_EXT,
    _NODE_FOLDERS,
    _STRENGTH_KEYS,
    _ALL_FOLDERS,
    _SEED_GLOBS,
    _SEED_GLOBS_EXTRA,
    AttestationError,
    _log_noop,
    _truthy,
    _ledger,
    _run_id,
    _record_gate,
    _record_fallback,
)
from zyg_workflows.lora_attest.pins import (
    _sha256_local,
    _load_cache,
    _save_cache,
    sha256_file,
    model_roots,
    resolve_model_path,
    load_pins,
    save_pins,
    _pin_for,
    seed_pins,
)
from zyg_workflows.lora_attest.gate import (
    _node_class,
    _is_output_class,
    _wiring_known,
    _reachable_nodes,
    _guess_kind,
    _node_strength,
    collect_model_refs,
    attest_graph,
    merge_overrides,
    attest_submit,
)
from zyg_workflows.lora_attest.ab_probe import (
    _CLIP_CACHE,
    _clip_embed_paths,
    _free_vram_mb,
    _comfy_busy,
    _ab_probe_graph,
    ab_probe_lora,
    _cli,
)


# ── re-export surface ─────────────────────────────────────────────────────────
# Every name below is imported above and not used in this module: this file
# exists so that ``zyg_workflows.lora_attest.<name>``
# resolves exactly as it did on the pre-split single-file module.
# Nothing does ``import *`` from here.
__all__ = [
    'annotations',
    'hashlib',
    'json',
    'os',
    'time',
    'exe',
    'paths',
    '_HERE',
    '_RUNTIME_DIR',
    'PINS_PATH',
    '_HASH_CACHE_PATH',
    'GATE_NAME',
    'AB_PROBE_FLOOR',
    '_MODEL_EXT',
    '_NODE_FOLDERS',
    '_STRENGTH_KEYS',
    '_ALL_FOLDERS',
    '_SEED_GLOBS',
    '_SEED_GLOBS_EXTRA',
    'AttestationError',
    '_log_noop',
    '_truthy',
    '_ledger',
    '_run_id',
    '_record_gate',
    '_record_fallback',
    '_sha256_local',
    '_load_cache',
    '_save_cache',
    'sha256_file',
    'model_roots',
    'resolve_model_path',
    'load_pins',
    'save_pins',
    '_pin_for',
    'seed_pins',
    '_node_class',
    '_is_output_class',
    '_wiring_known',
    '_reachable_nodes',
    '_guess_kind',
    '_node_strength',
    'collect_model_refs',
    'attest_graph',
    'merge_overrides',
    'attest_submit',
    '_CLIP_CACHE',
    '_clip_embed_paths',
    '_free_vram_mb',
    '_comfy_busy',
    '_ab_probe_graph',
    'ab_probe_lora',
    '_cli',
]
