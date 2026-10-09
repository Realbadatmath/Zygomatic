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
    AB_PROBE_FLOOR,
    _log_noop,
    _record_fallback,
    _record_gate,
    _truthy,
    exe,
    json,
    os,
)
from zyg_workflows.lora_attest.pins import model_roots, seed_pins
from zyg_workflows.lora_attest.gate import attest_graph

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# ── dynamic half: does the LoRA actually move the model? ─────────────────────

_CLIP_CACHE = {'model': None, 'pre': None}


def _clip_embed_paths(paths, log_fn=None):
    """Mean-pooled, L2-normalised open_clip ViT-B-32 embedding over image paths.

    open_clip is MIT and the openai ViT-B-32 weights are already cached locally
    (same embedder pipeline_debug uses for identity similarity)."""
    import torch
    import open_clip
    from PIL import Image

    if _CLIP_CACHE['model'] is None:
        m, _, pre = open_clip.create_model_and_transforms('ViT-B-32', pretrained='openai')
        m.eval()
        _CLIP_CACHE['model'], _CLIP_CACHE['pre'] = m, pre
    embs = []
    with torch.no_grad():
        for p in paths:
            if not (p and os.path.isfile(p)):
                continue
            t = _CLIP_CACHE['pre'](Image.open(p).convert('RGB')).unsqueeze(0)
            e = _CLIP_CACHE['model'].encode_image(t)
            embs.append(e / e.norm(dim=-1, keepdim=True))
    if not embs:
        return None
    v = torch.cat(embs, 0).mean(0)
    return v / v.norm()


def _free_vram_mb():
    """Free VRAM in MB via nvidia-smi (read-only query, no CUDA context). None on error."""
    import subprocess

    try:
        p = subprocess.run(
            [exe('nvidia-smi'), '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
            capture_output=True,
            timeout=15,
        )
        if p.returncode != 0:
            return None
        return int(p.stdout.decode().strip().splitlines()[0])
    except Exception:
        return None


def _comfy_busy():
    """(busy, detail). True when ComfyUI has anything running or pending.

    The probe must never queue behind — or contend with — a production render, and
    free VRAM alone is not proof of an idle server (a job can be between stages).
    Unreachable/unknown counts as BUSY: refusing to probe is always the safe answer.
    """
    try:
        import requests

        host = os.environ.get('ZYG_COMFY_HOST', '127.0.0.1')
        port = os.environ.get('ZYG_COMFY_PORT', '8188')
        r = requests.get(f'http://{host}:{port}/queue', timeout=5)
        if r.status_code != 200:
            return True, f'/queue returned {r.status_code}'
        q = r.json()
        n_run = len(q.get('queue_running') or [])
        n_pend = len(q.get('queue_pending') or [])
        if n_run or n_pend:
            return True, f'{n_run} running / {n_pend} pending job(s)'
        return False, 'idle'
    except Exception as exc:
        return True, f'queue unreachable ({type(exc).__name__})'


def _ab_probe_graph(lora_name, strength, prompt, seed, frames, size, negative=''):
    """Minimal Wan2.1 T2V graph: LoRA → sampler → decode → SaveImage."""
    t2v = os.environ.get('ZYG_WAN_T2V_MODEL', 'Wan2_1-T2V-14B_fp8_e4m3fn.safetensors')
    g = {
        '1': {
            'class_type': 'WanVideoModelLoader',
            'inputs': {
                'model': t2v,
                'base_precision': 'bf16',
                'quantization': 'fp8_e4m3fn',
                'load_device': 'offload_device',
                'attention_mode': os.environ.get('ZYG_WAN_ATTENTION', 'sdpa').strip() or 'sdpa',
            },
        },
        '8': {
            'class_type': 'WanVideoLoraSelect',
            'inputs': {'lora': lora_name, 'strength': float(strength), 'low_mem_load': False},
        },
        '2': {
            'class_type': 'LoadWanVideoT5TextEncoder',
            'inputs': {'model_name': 'umt5-xxl-enc-bf16.safetensors', 'precision': 'bf16'},
        },
        '4': {
            'class_type': 'WanVideoVAELoader',
            'inputs': {'model_name': 'Wan2_1_VAE_bf16.safetensors', 'precision': 'bf16'},
        },
        '20': {
            'class_type': 'WanVideoTextEncode',
            'inputs': {
                't5': ['2', 0],
                'positive_prompt': str(prompt)[:600],
                'negative_prompt': str(negative)[:300],
                'force_offload': True,
            },
        },
        '25': {
            'class_type': 'WanVideoEmptyEmbeds',
            'inputs': {'width': int(size), 'height': int(size), 'num_frames': int(frames)},
        },
        '30': {
            'class_type': 'WanVideoSampler',
            'inputs': {
                'model': ['1', 0],
                'image_embeds': ['25', 0],
                'text_embeds': ['20', 0],
                'steps': int(os.environ.get('ZYG_AB_PROBE_STEPS', '12')),
                'cfg': 5.0,
                'shift': 5.0,
                'seed': int(seed),
                'scheduler': 'unipc',
                'riflex_freq_index': 0,
                'force_offload': True,
            },
        },
        '40': {
            'class_type': 'WanVideoDecode',
            'inputs': {
                'vae': ['4', 0],
                'samples': ['30', 0],
                'enable_vae_tiling': False,
                'tile_x': 272,
                'tile_y': 272,
                'tile_stride_x': 144,
                'tile_stride_y': 128,
            },
        },
        '50': {
            'class_type': 'SaveImage',
            'inputs': {
                'images': ['40', 0],
                'filename_prefix': f'ZygAbProbe_{abs(hash((lora_name, strength))) % 10000:04d}',
            },
        },
    }
    g['1']['inputs']['lora'] = ['8', 0]
    return g


def ab_probe_lora(
    lora_name,
    trigger_prompt,
    strength,
    seed=7,
    frames=5,
    size=512,
    floor=AB_PROBE_FLOOR,
    log_fn=None,
    run_id=None,
    allow_gpu=None,
    min_free_vram_mb=22000,
):
    """Prove a LoRA is not inert: fixed-seed A/B render at strength 0 vs ``strength``.

    Renders two tiny clips (``frames`` frames at ``size`` px, identical seed, identical
    prompt) — one with the LoRA at 0.0, one at the configured strength — embeds both
    with CLIP and requires ``1 - cosine`` to clear ``floor`` (default 0.02). Below the
    floor the LoRA changed nothing measurable, which is exactly the 2026-07-09
    waxy-skin inert-LoRA failure.

    GPU-GATED AND OFF BY DEFAULT. Arm with ``ZYG_AB_PROBE_LORA=1`` (or allow_gpu=True)
    and only when a run-diff shows a LoRA/checkpoint hash changed — this costs 1-2
    minutes of GPU and must never run while a production render owns the card. Even
    when armed it refuses to submit unless BOTH gates clear: free VRAM >=
    ``min_free_vram_mb`` AND an idle ComfyUI queue (unreachable == busy).

    Returns {'ok': True|False|None, 'delta', 'cosine', 'floor', 'skipped'/'error', ...}.
    """
    log = log_fn or _log_noop
    armed = _truthy(os.environ.get('ZYG_AB_PROBE_LORA')) if allow_gpu is None else bool(allow_gpu)
    res = {
        'ok': None,
        'lora': lora_name,
        'strength': float(strength),
        'seed': int(seed),
        'frames': int(frames),
        'size': int(size),
        'floor': float(floor),
        'delta': None,
        'cosine': None,
    }
    if not armed:
        res['skipped'] = 'gpu-gated: ZYG_AB_PROBE_LORA not set (probe is opt-in)'
        log(f'[attest] A/B probe SKIPPED for {lora_name} — {res["skipped"]}')
        return res
    if abs(float(strength)) < 1e-6:
        res['skipped'] = 'configured strength is 0 — nothing to probe'
        return res
    free_mb = _free_vram_mb()
    if free_mb is not None and free_mb < int(min_free_vram_mb):
        res['skipped'] = f'only {free_mb} MB VRAM free (< {min_free_vram_mb}) — another render owns the card'
        log(f'[attest] A/B probe SKIPPED for {lora_name} — {res["skipped"]}')
        return res
    busy, why = _comfy_busy()
    if busy:
        res['skipped'] = f'ComfyUI not idle: {why}'
        log(f'[attest] A/B probe SKIPPED for {lora_name} — {res["skipped"]}')
        return res
    try:
        from zyg_workflows import _comfy_client as CC

        outs = {}
        for label, s in (('base', 0.0), ('lora', float(strength))):
            g = _ab_probe_graph(lora_name, s, trigger_prompt, seed, frames, size)
            paths = CC.submit(g, timeout_s=int(os.environ.get('ZYG_AB_PROBE_TIMEOUT_S', '900')))
            if not paths:
                res['error'] = f'no output from {label} render'
                return res
            outs[label] = list(paths)
            log(f'[attest] A/B probe {label} render: {len(paths)} frame(s)')
        import torch

        a = _clip_embed_paths(outs['base'], log_fn=log)
        b = _clip_embed_paths(outs['lora'], log_fn=log)
        if a is None or b is None:
            res['error'] = 'CLIP embedding failed on probe frames'
            return res
        with torch.no_grad():
            cos = float((a * b).sum())
        res['cosine'] = cos
        res['delta'] = 1.0 - cos
        res['ok'] = bool(res['delta'] >= float(floor))
        log(
            f'[attest] A/B probe {lora_name} @ {strength}: delta={res["delta"]:.4f} '
            f'(floor {floor}) → {"PASS" if res["ok"] else "FAIL (LoRA appears INERT)"}'
        )
        if not res['ok']:
            _record_fallback(
                f'lora:{lora_name}',
                expected=f'visual delta >= {floor}',
                actual=f'{res["delta"]:.4f}',
                detail='A/B probe: LoRA had no measurable effect',
                run_id=run_id,
            )
        _record_gate(
            run_id, 'PASS' if res['ok'] else 'FAIL', score=res['delta'], tag=f'ab_probe:{os.path.basename(lora_name)}'
        )
    except Exception as exc:
        res['ok'] = None
        res['error'] = f'{type(exc).__name__}: {exc}'
        log(f'[attest] A/B probe broke (non-fatal): {res["error"]}')
    return res


# ── CLI ──────────────────────────────────────────────────────────────────────


def _cli():
    import sys

    argv = sys.argv[1:]
    cmd = argv[0] if argv else 'help'

    def log(m):
        _zyg_log.info(m)

    if cmd == 'seed':
        r = seed_pins(extra=('--extra' in argv), log_fn=log, merge=('--replace' not in argv))
        _zyg_log.info(json.dumps({k: r[k] for k in ('ok', 'added', 'changed', 'path') if k in r}, indent=2))
        return 0 if r.get('ok') else 1
    if cmd == 'attest':
        if len(argv) < 2:
            _zyg_log.info('usage: lora_attest.py attest <graph.json>')
            return 2
        with open(argv[1], 'r', encoding='utf-8') as f:
            graph = json.load(f)
        r = attest_graph(graph, log_fn=log, tag=os.path.basename(argv[1]), record=False)
        _zyg_log.info(json.dumps(r, indent=2))
        return 0 if r.get('ok') else 1
    if cmd == 'roots':
        _zyg_log.info(json.dumps(model_roots(), indent=2))
        return 0
    _zyg_log.info(__doc__)
    return 0


if __name__ == '__main__':
    raise SystemExit(_cli())
