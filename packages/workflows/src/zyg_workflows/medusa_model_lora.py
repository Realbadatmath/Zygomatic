#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Medusa BASE-model LoRAs — registry, staging, and the render attach seam.

WHAT THIS IS
    bp_medusa_training.py trains a LoRA that teaches the model ONE PERSON.
    This module owns a different thing: a LoRA that changes what the BASE model
    is willing and able to render at all, for every Medusa render, with no
    character involved. One per model family, trained from its own dataset.

ISOLATION CONTRACT (the whole reason this file is separate)
    Inherited from bp_medusa_training.py's contract, with one addition that
    matters more here. A character LoRA is opt-in by construction: a render only
    loads it if a caller names that character. A BASE LoRA is not — it changes
    the model itself, so if it were ever reachable from a shared code path it
    would silently restyle the storyteller, documentary, creature and kids
    pipelines. Three independent walls keep that from happening:

    1. STORAGE. Datasets and adapters live only under _MODEL_DATASET_ROOT /
       _MODEL_OUTPUT_ROOT — dedicated top-level trees, siblings of and disjoint
       from storyteller_chars, medusa_training, animals, creatures and
       wan_chars. Model ids are `mdm_<12 hex>`, a third shape distinct from
       both `mdt_<12 hex>` (dedicated characters) and bare `<12 hex>` (regular
       characters), so the process-wide job dict in lora_trainer_service cannot
       collide either.

    2. ACTIVATION IS THREAD-LOCAL. An adapter existing on disk does nothing.
       It attaches only while the CALLING THREAD is inside a Medusa worker run,
       via activate()/clear() below — the same thread-local idiom
       medusa_pipeline.py already uses for its swimwear negative rewrite, which
       is the proven pattern in this tree. A storyteller render running
       concurrently in another thread sees active_for_family() -> None. There
       is no module-level "current model", no env var, and no config file that
       could turn one on globally, because any of those would be reachable by
       every other pipeline in the process.

    3. A PRIVATE WORKFLOW. The adapter is wired into node 14 of
       <family>_medusa_base.json, a graph nothing else in this codebase names.
       Even a mis-staged file cannot enter a storyteller render, because the
       storyteller's graphs have no node 14.

STAGING USES A PER-MODEL FILENAME, DELIBERATELY
    comfy_generation_service._stage_style_lora copies every style LoRA onto the
    single shared name 'style_lora.safetensors' and skips the copy when the
    destination looks newer. That is precisely the pattern
    _stage_character_lora's docstring records as having caused 28/28 SDXL and
    37/39 FLUX adapters to render with the WRONG weights, because shutil.copy2
    preserves mtimes so the guard was comparing two unrelated training runs.
    stage() below keys the filename on the model id and compares (size,
    mtime_ns) identity instead. Do not "simplify" it back to a shared name.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from zyg_workflows import paths

_CREWS_DIR = os.path.dirname(os.path.abspath(__file__))

MODEL_DATASET_ROOT = os.path.realpath(paths.ZYG_MEDUSA_MODEL_DATASET_ROOT)
MODEL_OUTPUT_ROOT = os.path.realpath(paths.ZYG_MEDUSA_MODEL_OUTPUT_ROOT)

MODEL_ID_RE = re.compile(r'^mdm_[0-9a-f]{12}$')

# flux is absent on purpose: FLUX.1-dev is licence-paused for this channel
# (comfy_generation_service's own pause, and project_licence_gate), and a LoRA
# trained on it stays a derivative of a non-commercial base.
FAMILIES = ('qwen', 'klein', 'sdxl')

# Where Comfy reads adapters from. Same directory the character stager uses.
_COMFY_LORA_DIR = str(paths.ZYG_COMFY_LORA_DIR)

_DEFAULT_SCALE = 0.85

# ── thread-local activation ──────────────────────────────────────────────────
_TLS = threading.local()


def activate(model_id: str, lora_path: str, family: str, scale: float = _DEFAULT_SCALE) -> None:
    """Attach a base LoRA for THIS THREAD only. Call clear() in a finally."""
    _TLS.base_lora = {
        'model_id': str(model_id or ''),
        'path': str(lora_path or ''),
        'family': normalize_family(family),
        'scale': float(scale),
    }


def clear() -> None:
    _TLS.base_lora = None


def active() -> dict | None:
    """The base LoRA attached to this thread, or None. Never process-wide."""
    return getattr(_TLS, 'base_lora', None)


def active_for_family(family: str) -> dict | None:
    """active(), but only when it matches *family* — a qwen adapter must never
    be handed to a klein or sdxl render, the same rule the character path
    enforces via lora_path_matches_family."""
    cur = active()
    if not cur:
        return None
    if cur.get('family') != normalize_family(family):
        return None
    if not cur.get('path') or not os.path.isfile(cur['path']):
        return None
    return cur


class attached:
    """Context manager: `with medusa_model_lora.attached(meta): ...`

    Using this rather than bare activate()/clear() means an exception inside a
    render cannot leave a base LoRA attached to a pooled worker thread that a
    different pipeline later reuses. That is the one way thread-local isolation
    could leak, so the safe form is the one with a name.
    """

    def __init__(self, model_id: str, lora_path: str, family: str, scale: float = _DEFAULT_SCALE):
        self._args = (model_id, lora_path, family, scale)

    def __enter__(self):
        activate(*self._args)
        return self

    def __exit__(self, *exc):
        clear()
        return False


# ── ids, paths, meta ─────────────────────────────────────────────────────────
def normalize_family(raw) -> str:
    v = str(raw or 'qwen').strip().lower()
    return v if v in FAMILIES else 'qwen'


def new_model_id() -> str:
    import uuid

    return f'mdm_{uuid.uuid4().hex[:12]}'


def dataset_dir(model_id: str) -> str | None:
    """Realpath-confined: a model id that escapes the root resolves to None."""
    if not MODEL_ID_RE.match(model_id or ''):
        return None
    p = os.path.realpath(os.path.join(MODEL_DATASET_ROOT, model_id))
    return p if os.path.dirname(p) == MODEL_DATASET_ROOT else None


def output_dir(model_id: str) -> str | None:
    if not MODEL_ID_RE.match(model_id or ''):
        return None
    p = os.path.realpath(os.path.join(MODEL_OUTPUT_ROOT, model_id))
    return p if os.path.dirname(p) == MODEL_OUTPUT_ROOT else None


def images_dir(model_id: str) -> str | None:
    d = dataset_dir(model_id)
    return os.path.join(d, 'images') if d else None


def meta_path(model_id: str) -> str | None:
    d = dataset_dir(model_id)
    return os.path.join(d, 'meta.json') if d else None


def load_meta(model_id: str) -> dict | None:
    p = meta_path(model_id)
    if not p or not os.path.isfile(p):
        return None
    try:
        with open(p, encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def save_meta(model_id: str, meta: dict) -> None:
    d = dataset_dir(model_id)
    if not d:
        raise ValueError(f'refusing to write meta for bad model id {model_id!r}')
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, 'meta.json')
    tmp = f'{p}.tmp.{os.getpid()}'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(meta, fh, indent=2)
    os.replace(tmp, p)


def list_models(family: str = '') -> list[dict]:
    """Every registered model, newest first. Reads only the isolated root."""
    want = normalize_family(family) if family else ''
    out: list[dict] = []
    try:
        entries = os.listdir(MODEL_DATASET_ROOT)
    except OSError:
        return out
    for mid in entries:
        if not MODEL_ID_RE.match(mid):
            continue
        meta = load_meta(mid)
        if not meta:
            continue
        if want and normalize_family(meta.get('family')) != want:
            continue
        out.append(meta)
    out.sort(key=lambda m: m.get('created', 0), reverse=True)
    return out


# ── adapter discovery ────────────────────────────────────────────────────────
_EXPORT_NAMES = ('pytorch_lora_weights.safetensors', 'adapter_model.safetensors', 'lora.safetensors')


def _weights_dir(model_id: str, family: str) -> str | None:
    o = output_dir(model_id)
    return os.path.join(o, f'lora-weights-{normalize_family(family)}') if o else None


def adapter_path(model_id: str, family: str) -> str | None:
    """Newest usable adapter for this model, or None.

    Mirrors character_lora_family._latest_checkpoint_file: the end-of-run root
    export outranks a lagging checkpoint dir when it is the newer file, because
    lora_trainer_service._cleanup_after_training deletes checkpoint dirs and
    keeps exactly that root export.
    """
    base = _weights_dir(model_id, family)
    if not base or not os.path.isdir(base):
        return None
    best: tuple[float, str] | None = None
    try:
        for entry in os.listdir(base):
            p = os.path.join(base, entry)
            if os.path.isfile(p) and entry.endswith('.safetensors'):
                rank = _EXPORT_NAMES.index(entry) if entry in _EXPORT_NAMES else len(_EXPORT_NAMES)
                try:
                    mt = os.path.getmtime(p)
                except OSError:
                    mt = 0.0
                key = (-rank, mt)
                if best is None or key > best[0]:
                    best = (key, p)
            elif os.path.isdir(p) and entry.startswith('checkpoint-'):
                for name in _EXPORT_NAMES:
                    q = os.path.join(p, name)
                    if os.path.isfile(q):
                        m = re.search(r'checkpoint-(\d+)', entry)
                        step = int(m.group(1)) if m else 0
                        key = (-len(_EXPORT_NAMES), float(step))
                        if best is None or key > best[0]:
                            best = (key, q)
                        break
    except OSError:
        return None
    return best[1] if best else None


def is_trained(model_id: str, family: str) -> bool:
    return adapter_path(model_id, family) is not None


# ── staging ──────────────────────────────────────────────────────────────────
def stage(lora_path: str, model_id: str, family: str, log_fn=None) -> str | None:
    """Copy an adapter into Comfy under a PER-MODEL name; return that name.

    See the module docstring on why this must never share one filename.
    """
    log = log_fn or (lambda m: None)
    if not lora_path or not os.path.isfile(lora_path):
        return None
    if not MODEL_ID_RE.match(model_id or ''):
        log(f'MedusaBaseLoRA: refusing to stage — bad model id {model_id!r}')
        return None
    fam = normalize_family(family)
    name = f'zygmdm_{model_id[4:]}_{fam}.safetensors'
    dst = os.path.join(_COMFY_LORA_DIR, name)
    try:
        os.makedirs(_COMFY_LORA_DIR, exist_ok=True)
        src_st = os.stat(lora_path)
        need = True
        if os.path.isfile(dst):
            d_st = os.stat(dst)
            # Size + mtime_ns identity, NOT "is the source newer" — copy2
            # preserves mtimes, so a newer-than test compares unrelated runs.
            need = not (src_st.st_size == d_st.st_size and src_st.st_mtime_ns == d_st.st_mtime_ns)
        if need:
            shutil.copy2(lora_path, dst)
            log(f'MedusaBaseLoRA: staged {os.path.basename(lora_path)} -> {name}')
        return name
    except Exception as exc:
        log(f'MedusaBaseLoRA: could not stage ({exc}) — continuing without')
        return None


def workflow_for(family: str) -> str:
    """The private graph that carries node 14. Named nowhere else."""
    return f'{normalize_family(family)}_medusa_base'


# ── activation bookkeeping (which model the operator picked per family) ──────
_ACTIVE_FILE = os.path.join(_CREWS_DIR, 'data', 'runtime', 'medusa_active_models.json')


def _read_active() -> dict:
    try:
        with open(_ACTIVE_FILE, encoding='utf-8') as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def get_active_id(family: str) -> str:
    """Which model the operator has switched ON for *family*, or ''.

    This is a PREFERENCE, not an activation: reading it attaches nothing. Only
    a Medusa worker calling activate()/attached() makes a render use it.
    """
    return str(_read_active().get(normalize_family(family)) or '')


def set_active_id(family: str, model_id: str) -> None:
    fam = normalize_family(family)
    cur = _read_active()
    if model_id:
        if not MODEL_ID_RE.match(model_id):
            raise ValueError(f'bad model id {model_id!r}')
        cur[fam] = model_id
    else:
        cur.pop(fam, None)
    os.makedirs(os.path.dirname(_ACTIVE_FILE), exist_ok=True)
    tmp = f'{_ACTIVE_FILE}.tmp.{os.getpid()}'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(cur, fh, indent=2)
    os.replace(tmp, _ACTIVE_FILE)


def resolve_active(family: str) -> dict | None:
    """{'model_id','path','family','scale','name'} for the family's active model.

    Returns None when nothing is switched on or the adapter is not on disk yet.
    Medusa's worker calls this and wraps the result in attached().
    """
    fam = normalize_family(family)
    mid = get_active_id(fam)
    if not mid:
        return None
    path = adapter_path(mid, fam)
    if not path:
        return None
    meta = load_meta(mid) or {}
    return {
        'model_id': mid,
        'path': path,
        'family': fam,
        'scale': float(meta.get('scale') or _DEFAULT_SCALE),
        'name': str(meta.get('name') or mid),
    }


def touch(meta: dict) -> dict:
    meta['updated'] = time.time()
    return meta
