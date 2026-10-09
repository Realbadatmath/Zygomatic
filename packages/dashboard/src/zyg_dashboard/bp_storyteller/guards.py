# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared guards and small helpers for the storyteller routes.

Verbatim move of bp_storyteller.py:87-261 (2026-10-06 split).
"""

import json
import logging as _zyg_logging
import os
import re
import threading
from typing import Dict, List, Tuple

from zyg_dashboard.bp_storyteller import (  # noqa: E402  the package __init__ binds these before it imports this module
    ZYG_LORA_DATASETS,
    _runtime_path,
)

_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_storyteller')


# ── 2026-07-31 identity audit: shared guards for the storyteller routes ───────
# Every ZYG_ flag below DEFAULTS TO THE NEW (safe) behaviour; set it to
# 0/false/no/off to fall back to the pre-audit behaviour where that is still a
# meaningful thing to want. None of them can resurrect the caption-scraping
# preview sweep — that path fabricated identities and was deleted outright.
def _env_on(name: str, default: str = '1') -> bool:
    return os.environ.get(name, default).strip().lower() not in ('0', 'false', 'no', 'off')


_CHARS_DATASET_ROOT = str(ZYG_LORA_DATASETS / 'storyteller_chars')
# Canonical 12-hex character id. The contact-sheet image route has validated
# against this since 2026-07-19; generate-character and preview/regenerate did
# not, so an unvalidated id reached os.makedirs + file writes.
_CHAR_ID_RE = re.compile(r'^[a-f0-9]{12}$')
# Widened charset for READ-ONLY sheet serving only: 33 legacy dataset dirs use
# slugs (abel_van_haren) whose approval review cards 404'd forever. No dots and
# no separators, and the resolved path is still containment-checked below.
_CHAR_ID_WIDE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')
# The preview sweep's running-flag used to be a check-then-set 28 lines apart —
# two public page loads in the same second started two sweeps on one GPU.
_SWEEP_LOCK = threading.Lock()
# preview/regenerate ran a multi-minute GPU render inline in the Flask worker.
_PREVIEW_REGEN_LOCK = threading.Lock()
_PREVIEW_REGEN_JOBS: Dict[str, dict] = {}


def _is_medusa_cid(char_id: str) -> bool:
    """True iff *char_id* originated from Medusa (shared dataset root, isolated
    app). Fail-safe: any error means 'not medusa', matching filter_out_medusa."""
    try:
        from zyg_dashboard import bp_medusa as _bm_iso

        return bool(_bm_iso.is_medusa_char(char_id))
    except Exception:
        return False


def _production_paused() -> bool:
    """True when the operator pulled the production hold. Fail-open on error so
    a broken pipeline_control never wedges character generation."""
    try:
        from zyg_workflows import pipeline_control as _pc_pp

        return bool(_pc_pp.is_paused(_pc_pp.SCOPE_PRODUCTION))
    except Exception:
        return False


# Preview provenance sidecar (contract D, 2026-07-31): the LoRA-locked renderer
# writes <slot>.meta.json next to <slot>.png. A preview with NO sidecar has
# UNVERIFIED provenance and must never be presented as "LoRA trained" — so an
# absent sidecar is OMITTED from the map rather than defaulted to anything.
_PREVIEW_SLOT_STEMS = (
    'preview_flux_front',
    'preview_flux_face',
    'preview_sdxl_front',
    'preview_sdxl_face',
)


def _preview_provenance_map(dataset_dir: str) -> dict:
    """{slot: {...}} for every preview PNG that has a readable sidecar."""
    out: dict = {}
    if not dataset_dir or not os.path.isdir(dataset_dir):
        return out
    # Containment: char_id reaches here from route path segments.
    try:
        _root_pv = os.path.realpath(_CHARS_DATASET_ROOT)
        if not os.path.realpath(dataset_dir).startswith(_root_pv + os.sep):
            return out
    except Exception:
        return out
    for _stem in _PREVIEW_SLOT_STEMS:
        _png = os.path.join(dataset_dir, f'{_stem}.png')
        _side = os.path.join(dataset_dir, f'{_stem}.meta.json')
        if not (os.path.isfile(_png) and os.path.isfile(_side)):
            continue
        try:
            with open(_side, encoding='utf-8') as _fh:
                _meta = json.load(_fh)
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('skipping preview slot with an unreadable sidecar: %s', _exc)
            continue
        if not isinstance(_meta, dict):
            continue
        out[_stem] = {
            'slot': _meta.get('slot') or _stem,
            'model_family': _meta.get('model_family'),
            'lora_used': bool(_meta.get('lora_used')),
            # basename only — the public wizard proxies this response and has no
            # business learning absolute checkpoint paths.
            'lora_path': os.path.basename(_meta.get('lora_path') or '') or None,
            'trigger_token': _meta.get('trigger_token'),
            'restyle': _meta.get('restyle'),
            'backend': _meta.get('backend'),
            'rendered_at': _meta.get('rendered_at'),
        }
    return out


def _save_uploaded_char_photos(char_id: str, photo_files) -> List[str]:
    """Persist uploaded character photos into the dataset dir; return their paths.

    Split out 2026-07-31 so the Agent Zero park can keep the uploaded bytes (a
    multipart body cannot be snapshotted into the pending store) without also
    running the vision analysis / Sonnet brief the gate exists to defer.
    """
    out: List[str] = []
    if not photo_files or not _CHAR_ID_RE.match(char_id or ''):
        return out
    _char_dataset_dir = os.path.join(_CHARS_DATASET_ROOT, char_id)
    os.makedirs(_char_dataset_dir, exist_ok=True)
    _ALLOWED_EXTS = {'.jpg', '.jpeg', '.png', '.webp'}
    for _idx_up, _fobj in enumerate(list(photo_files)[:15]):
        _fname = _fobj.filename or f'upload_{_idx_up}.jpg'
        _ext = os.path.splitext(_fname)[1].lower()
        if _ext not in _ALLOWED_EXTS:
            _ext = '.jpg'
        _save_path = os.path.join(_char_dataset_dir, f'photo_{_idx_up:03d}{_ext}')
        _fobj.save(_save_path)
        out.append(_save_path)
    return out


def _restore_parked_char_photos(char_id: str, preserved) -> List[str]:
    """Re-attach photos written at Agent-Zero-park time. Containment-checked to
    this character's dataset dir so a doctored snapshot cannot inject paths."""
    out: List[str] = []
    if not preserved or not isinstance(preserved, (list, tuple)):
        return out
    if not _CHAR_ID_RE.match(char_id or ''):
        return out
    try:
        _root = os.path.realpath(os.path.join(_CHARS_DATASET_ROOT, char_id))
    except Exception:
        return out
    for _p in list(preserved)[:15]:
        try:
            _rp = os.path.realpath(str(_p))
        except OSError as _exc:
            _zyg_log.debug('skipping preserved path that cannot be resolved: %s', _exc)
            continue
        if _rp.startswith(_root + os.sep) and os.path.isfile(_rp):
            out.append(_rp)
    return out


def _char_lora_usable(char_id: str, model_family: str = '') -> Tuple[bool, str]:
    """(usable, reason) for *char_id*'s adapter.

    Prefers character_lora_family.char_lora_usable (contract C) which also
    rejects declined / QC-failed contact-sheet runs whose .safetensors exist.
    Degrades to a plain checkpoint-on-disk probe when that helper is absent, so
    the caller still never renders without an adapter.
    """
    try:
        from zyg_workflows import character_lora_family as _clf_use
    except Exception as _ie:
        return False, f'character_lora_family unavailable: {str(_ie)[:80]}'
    _fn = getattr(_clf_use, 'char_lora_usable', None)
    if callable(_fn):
        try:
            _ok, _reason = _fn(char_id, model_family=model_family, runtime_dir=_runtime_path(''))
            return bool(_ok), str(_reason or '')
        except (TypeError, AttributeError) as _exc:
            _zyg_log.debug('char_lora_usable signature mismatch, falling back to the local check: %s', _exc)
        except Exception as _ce:
            return False, f'char_lora_usable error: {str(_ce)[:80]}'
    try:
        _p = _clf_use.resolve_char_lora_path(char_id, model_family or 'flux')
    except Exception as _re_e:
        return False, f'lora resolve error: {str(_re_e)[:80]}'
    if _p and os.path.isfile(_p):
        return True, os.path.basename(_p)
    return False, 'no trained LoRA checkpoint on disk'
