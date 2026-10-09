#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
creature_deps_check.py — every dependency of the creature sheet workflow, verified.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" scripts/creature_deps_check.py [--json]

Prints one line per dependency with OK / MISSING and what it is for. Exit 1 if
anything REQUIRED is missing. Run it in the GUI venv (the one crewai-gui.service
uses) — that is the interpreter the pipeline thread runs in.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import logging as _zyg_logging

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _CREWS)
os.chdir(_CREWS)

COMFY_ROOT = str(paths.ZYG_COMFY_ROOT)
HF = os.path.expanduser('~/.cache/huggingface/hub')
VLM_HOME = os.environ.get('ZYG_VLM_HOME', str(paths.ZYG_MODELS_DIR / 'vlm_judge'))

rows: list[dict] = []


def add(name, ok, purpose, detail='', required=True):
    rows.append({'name': name, 'ok': bool(ok), 'purpose': purpose, 'detail': detail, 'required': required})


def _mod(m):
    return importlib.util.find_spec(m) is not None


def _file(p, min_mb=0):
    return os.path.isfile(p) and os.path.getsize(p) >= min_mb * 1024 * 1024


def _hf(repo):
    d = os.path.join(HF, 'models--' + repo.replace('/', '--'))
    return os.path.isdir(d) and any(
        os.path.getsize(os.path.join(r, f)) > 1_000_000
        for r, _, fs in os.walk(d)
        for f in fs
        if f.endswith('.safetensors')
    )


def _http(url, timeout=3):
    try:
        import requests

        return requests.get(url, timeout=timeout).status_code == 200
    except Exception:
        return False


# ── python (GUI venv) ────────────────────────────────────────────────────────
add(
    'python venv',
    'agents/.venv' in sys.executable or 'Zygomatic' in sys.executable,
    'must be the crewai-gui interpreter',
    sys.executable,
)
for m, why in (
    ('torch', 'DINOv2 identity metric (CPU)'),
    ('transformers', 'DINOv2 AutoModel'),
    ('PIL', 'strips, sheet stitch, letterbox'),
    ('imagehash', 'structural QC (phash)'),
    ('numpy', 'image stats'),
    ('requests', 'ComfyUI + Ollama HTTP'),
):
    add(f'py:{m}', _mod(m), why)

# ── weights: identity ────────────────────────────────────────────────────────
add(
    'hf:facebook/dinov2-base',
    _hf('facebook/dinov2-base'),
    'identity drift metric (Apache-2.0)',
    'fallback dinov2-small' if not _hf('facebook/dinov2-base') else '',
    required=False,
)
add('hf:facebook/dinov2-small', _hf('facebook/dinov2-small'), 'identity metric fallback', required=False)
try:
    from zyg_workflows import creature_identity as cid

    ok = cid._load()
    add('dinov2 loads offline', ok, 'creature_identity._load()', cid.model_id() or cid.unavailable_reason() or '')
except Exception as exc:
    add('dinov2 loads offline', False, 'creature_identity._load()', str(exc)[:200])

# ── ComfyUI + graphs + weights ───────────────────────────────────────────────
add('comfyui :8188', _http('http://127.0.0.1:8188/system_stats'), 'renders every cell')
dm = os.path.join(COMFY_ROOT, 'models', 'diffusion_models')
add(
    'qwen_image_edit_2509 (bf16 or fp8)',
    _file(os.path.join(dm, 'qwen_image_edit_2509_bf16.safetensors'), 1000)
    or _file(os.path.join(dm, 'qwen_image_edit_2509_fp8_e4m3fn.safetensors'), 1000),
    'camera-rotation edits (Apache-2.0)',
)
add(
    'qwen_2.5_vl_7b text encoder',
    _file(os.path.join(COMFY_ROOT, 'models', 'text_encoders', 'qwen_2.5_vl_7b_fp8_scaled.safetensors'), 1000),
    'qwen_edit_angle node 11',
)
add(
    'qwen_image_vae',
    _file(os.path.join(COMFY_ROOT, 'models', 'vae', 'qwen_image_vae.safetensors'), 10),
    'qwen_edit_angle node 12',
)
add(
    'multiple-angles LoRA (dx8152, 2509)',
    _file(os.path.join(COMFY_ROOT, 'models', 'loras', 'qwen_edit_2509_multiple_angles.safetensors'), 100),
    'camera rotation compliance',
)
add(
    'flux-2-klein-base-4b',
    _file(os.path.join(dm, 'flux-2-klein-base-4b.safetensors'), 1000),
    'from-scratch anchor + previews (Apache-2.0)',
)
add(
    'klein text encoder qwen_3_4b',
    _file(os.path.join(COMFY_ROOT, 'models', 'text_encoders', 'qwen_3_4b.safetensors'), 1000),
    'klein graphs node 11',
)
add('flux2-vae', _file(os.path.join(COMFY_ROOT, 'models', 'vae', 'flux2-vae.safetensors'), 10), 'klein graphs node 12')
for g in ('qwen_edit_angle', 'klein_txt2img', 'klein_character_locked', 'qwen_txt2img'):
    add(f'graph:{g}', _file(os.path.join(_CREWS, '_comfy_workflows', f'{g}.json')), 'ComfyUI graph template')
try:
    from zyg_workflows import comfy_generation_service as cgs

    add('comfy: TextEncodeQwenImageEditPlus + angles LoRA', cgs.has_qwen_edit_angles(), 'cgs.has_qwen_edit_angles()')
    add(
        'comfy: klein parts',
        not cgs.klein_missing_parts(),
        'cgs.klein_missing_parts()',
        ', '.join(cgs.klein_missing_parts()),
    )
except Exception as exc:
    add('comfy_generation_service import', False, 'render service', str(exc)[:200])

# ── judge ────────────────────────────────────────────────────────────────────
add('vlm_judge venv', _file(os.path.join(VLM_HOME, '.venv', 'bin', 'python')), 'Qwen3-VL worker interpreter')
add('vlm_worker.py', _file(os.path.join(VLM_HOME, 'vlm_worker.py')), 'judge subprocess')
add('hf:Qwen/Qwen3-VL-8B-Instruct-FP8', _hf('Qwen/Qwen3-VL-8B-Instruct-FP8'), 'resident judge tier (Apache-2.0)')
add(
    'hf:Qwen/Qwen3-VL-32B-Instruct-FP8',
    _hf('Qwen/Qwen3-VL-32B-Instruct-FP8'),
    'boundary judge tier (optional)',
    required=False,
)
try:
    import json as _j

    book = _j.load(open(os.path.join(_CREWS, 'config', 'vlm_checklists.json')))['checklists']
    add('checklist creature_cell', 'creature_cell' in book, 'per-cell binary questions')
    add('checklist creature_anchor', 'creature_anchor' in book, 'anchor / reference questions')
except Exception as exc:
    add('vlm_checklists.json', False, 'judge questions', str(exc)[:120])
try:
    from zyg_workflows import comfy_offload as CO

    add('comfy_offload.gpu_exclusive', hasattr(CO, 'gpu_exclusive'), 'frees ComfyUI VRAM for the judge')
except Exception as exc:
    add('comfy_offload', False, 'VRAM handover', str(exc)[:120])

# ── brief (Ollama vision) ────────────────────────────────────────────────────
ollama_ok = _http('http://localhost:11434/api/tags')
add('ollama :11434', ollama_ok, 'vision brief of the reference')
model = os.environ.get('ZYG_CREATURE_BRIEF_MODEL', 'qwen3.5:9b')
have = False
if ollama_ok:
    try:
        import requests

        have = any(
            m['name'] == model for m in requests.get('http://localhost:11434/api/tags', timeout=3).json()['models']
        )
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
add(f'ollama model {model}', have, 'describes the reference into a brief', required=False)

# ── trainer (klein) ──────────────────────────────────────────────────────────
add('SimpleTuner', _file(str(paths.ZYG_HOME / 'SimpleTuner' / '.venv' / 'bin' / 'python')), 'LoRA training')
kd = os.environ.get('ZYG_KLEIN_DIFFUSERS_DIR', str(paths.ZYG_MODELS_ROOT / 'FLUX2' / 'flux2-klein-base-4b'))
add(
    'klein diffusers tree',
    os.path.isdir(os.path.join(kd, 'transformer'))
    and any(
        os.path.getsize(os.path.join(kd, 'transformer', f)) > 1_000_000_000
        for f in os.listdir(os.path.join(kd, 'transformer'))
    )
    if os.path.isdir(os.path.join(kd, 'transformer'))
    else False,
    'SimpleTuner flux2/klein-4b base (weights present, not just config)',
    kd,
)
try:
    from zyg_workflows import licence_provenance as lp

    add('licence: FLUX paused (expected)', lp.flux_paused(), 'creature path must not need FLUX.1-dev', required=False)
except Exception as _exc:
    _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)

# ── fonts + services ─────────────────────────────────────────────────────────
add(
    'DejaVuSans-Bold.ttf', _file('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'), 'sheet labels', required=False
)
add(
    'crewai-gui :5000',
    _http('http://127.0.0.1:5000/login') or _http('http://127.0.0.1:5000/'),
    'pipeline host (start via /api/internal/pipeline/start)',
)
add('kanban :8899', _http('http://127.0.0.1:8899/kanban.html'), 'board visualiser', required=False)
try:
    free = (
        subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        .stdout.strip()
        .splitlines()[0]
    )
    add(
        'GPU free VRAM',
        int(free) > 20000,
        'Qwen-edit bf16 needs ~41 GB when loaded',
        f'{free} MiB free now',
        required=False,
    )
except Exception:
    add('nvidia-smi', False, 'GPU probe', required=False)

if '--json' in sys.argv:
    print(json.dumps(rows, indent=1))
else:
    w = max(len(r['name']) for r in rows)
    for r in rows:
        flag = 'OK     ' if r['ok'] else ('MISSING' if r['required'] else 'absent ')
        print(f'{flag}  {r["name"]:<{w}}  {r["purpose"]}' + (f'  [{r["detail"]}]' if r['detail'] else ''))
missing = [r for r in rows if r['required'] and not r['ok']]
print(
    f'\n{len(rows) - len(missing)}/{len(rows)} ok — {"ALL REQUIRED PRESENT" if not missing else "MISSING: " + ", ".join(r["name"] for r in missing)}'
)
sys.exit(1 if missing else 0)
