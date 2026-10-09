# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.arcane_restyle.profiles — verbatim from arcane_restyle.py lines 29-145.

the original import block, the profile store path, the commercial-safe
depth checkpoint, the style-only negatives, profile load/assign, the
styled-caption builder and the character-LoRA staging helper
"""

from __future__ import annotations

# ruff: noqa: F401  this module inherits arcane_restyle.py's original top import
# block verbatim; __init__ re-exports the names it binds so old attribute
# accesses off the module (arcane_restyle.os, .json, …) still resolve.

import copy
import json
import os
import re
import shutil
from typing import Callable

from zyg_workflows import animated_sdxl_dataset as _ads  # reuse identity-preservation helpers
from zyg_workflows import paths
import logging as _zyg_logging

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.arcane_restyle')


# character_style_profiles.json — the named "templates"
_PROFILES_PATH = str(paths.DATA_DIR / 'runtime' / 'character_style_profiles.json')

# Commercial-safe depth annotator — see the _DEPTH_CKPT note in arcane_multichar.py.
# Small (vits) = Apache-2.0. Base/Large/Giant = CC-BY-NC-4.0 = BANNED for this project.
_DEPTH_CKPT = os.environ.get('ZYG_DEPTH_CKPT', 'depth_anything_v2_vits.pth')

# Style-only negatives: push away from photoreal AND away from 3D-toon, toward
# painterly 2D. Per-character identity negatives are appended from the bible.
_STYLE_NEG = (
    'photograph, photorealistic, dslr, raw photo, film grain, visible skin pores, '
    '3d render, pixar, disney 3d, cgi, plastic skin, sculpted 3d, '
    'blurry, low quality, deformed face, bad anatomy, extra fingers, watermark, text, '
    'oversized eyes, huge eyes, big anime eyes, bug eyes'
)


def load_profile(name: str) -> dict | None:
    """Return the named style profile dict, or None if unknown/missing."""
    try:
        with open(_PROFILES_PATH, encoding='utf-8') as f:
            data = json.load(f)
        return (data.get('profiles') or {}).get(name)
    except Exception:
        return None


def set_char_profile(char_id: str, profile_name: str) -> bool:
    """Attach a style profile to a character's bible (style_profile.restyle).
    Set ONLY by the storyteller/admin flow — never by the public path."""
    try:
        from zyg_workflows import character_bible_service as _cbs

        pkg = _cbs.load(char_id)
        if not pkg:
            return False
        pkg.setdefault('style_profile', {})['restyle'] = profile_name
        # pin the render checkpoint so the styled LoRA renders on-model (an
        # explicit non-toon sdxl_checkpoint survives the animated-env override).
        prof = load_profile(profile_name) or {}
        rc = prof.get('render_checkpoint')
        if rc:
            pkg.setdefault('conditioning', {})['sdxl_checkpoint'] = rc
        _cbs.save(pkg)
        return True
    except Exception:
        return False


def _styled_caption(photoreal_caption: str, identity_clause: str, style_clause: str) -> str:
    """Strip photoreal texture terms, keep trigger+identity, append the style clause.
    Mirrors animated_sdxl_dataset._toon_caption but with a per-profile style clause."""
    txt = _ads._STRIP_TERMS.sub('', photoreal_caption or '')
    txt = re.sub(r',\s*,+', ', ', txt)
    txt = re.sub(r'\s{2,}', ' ', txt).strip(' ,\n')
    if identity_clause:
        parts = [p.strip() for p in txt.split(',') if p.strip()]
        ti = next((i for i, p in enumerate(parts) if 'ZYG_CHAR' in p), -1)
        if ti >= 0:
            txt = ', '.join(parts[: ti + 1] + [identity_clause] + parts[ti + 1 :])
        else:
            txt = f'{identity_clause}, {txt}' if txt else identity_clause
    return f'{txt}, {style_clause}' if txt else style_clause


def _stage_char_lora(char_id, log_fn=None):
    """Copy a character's trained SDXL identity LoRA into ComfyUI's loras dir under a
    per-char name so the render graph can reference it. Returns the lora file name or None."""
    import os as _os
    import shutil as _sh

    _log = log_fn or (lambda m: None)
    try:
        from zyg_workflows import character_bible_service as _cbs

        _p = ((_cbs.load(char_id) or {}).get('conditioning') or {}).get('sdxl_lora_path') or ''
    except Exception:
        _p = ''
    if not (_p and _os.path.isfile(_p)):
        _log(f'[depth-arcane] no sdxl char LoRA for {char_id} — style-only identity')
        return None
    # 2026-08-09: family-suffixed to match comfy_generation_service._stage_char_lora
    # (zygchar_<cid>_<mf>.safetensors). The two writers had diverged — this one
    # emitted a BARE zygchar_<id> for weights that are always SDXL, so the same
    # character's SDXL adapter existed under two different names depending on which
    # code path staged it, and the bare name carried no family at all. That made
    # lineage unresolvable for licence_provenance (a bare name could be either
    # family, so it has to be charged the worst) and left a second staging name
    # able to drift from the first — the same shape as the 2026-07-31 shared-name
    # collision this per-character scheme was introduced to end.
    name = f'zygchar_{char_id[:12]}_sdxl.safetensors'
    dst = _os.path.join(str(paths.ZYG_COMFY_ROOT), 'models', 'loras', name)
    try:
        if (not _os.path.isfile(dst)) or _os.path.getmtime(dst) < _os.path.getmtime(_p):
            _sh.copy2(_p, dst)
        return name
    except Exception as _e:
        _log(f'[depth-arcane] char LoRA stage failed ({_e})')
        return None
