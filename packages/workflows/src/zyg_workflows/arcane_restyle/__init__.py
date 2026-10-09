# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""ISOLATED per-character STYLE restyle for storyteller characters (2026-07-26).

"Bake the style into the LoRA" (Option 3): restyle a character's photoreal
contact-sheet training tiles into a chosen visual STYLE (e.g. Arcane painterly
animation) via SDXL img2img through a REALISTIC base checkpoint (Juggernaut) +
a style LoRA (style_arcane.safetensors), then the SDXL LoRA is trained on those
styled tiles and renders on-model natively.

WHY A SEPARATE MODULE (isolation): the global animated path
(animated_sdxl_dataset.build_animated_sdxl_dataset) is env-gated (ZYG_SDXL_ANIMATED /
ZYG_ANIM_STYLE_CLAUSE / ZYG_SDXL_ANIMATED_CKPT) and shared with the PUBLIC
zero_public flow. Changing those envs would restyle EVERY character. This module
is invoked ONLY when a character's bible carries `style_profile.restyle = <profile>`
(set exclusively by the storyteller/admin flow), so the public flow — which never
sets that field — is entirely unaffected.

Identity-preservation logic (identity clause, per-character negatives, VLM tile
screen) is REUSED from animated_sdxl_dataset so the two paths never drift.

Profiles live in data/runtime/character_style_profiles.json.
"""

from __future__ import annotations

# ruff: noqa: F401,E402  this __init__ IS the re-export surface of the old arcane_restyle.py.
from __future__ import annotations

# The submodules are imported in the original section order, so any module-level
# side effect still runs exactly when it did in the single-file arcane_restyle.py.
from zyg_workflows.arcane_restyle.profiles import (
    copy,
    json,
    os,
    re,
    shutil,
    Callable,
    _ads,
    paths,
    _zyg_logging,
    _zyg_log,
    _PROFILES_PATH,
    _DEPTH_CKPT,
    _STYLE_NEG,
    load_profile,
    set_char_profile,
    _styled_caption,
    _stage_char_lora,
)
from zyg_workflows.arcane_restyle.depth import (
    depth_controlnet_arcane_restyle,
)
from zyg_workflows.arcane_restyle.instantid import (
    _arcane_prompt,
    instantid_arcane_restyle,
)
from zyg_workflows.arcane_restyle.qwen import (
    qwen_restyle_image,
)
from zyg_workflows.arcane_restyle.dataset import (
    build_styled_sdxl_dataset,
)
