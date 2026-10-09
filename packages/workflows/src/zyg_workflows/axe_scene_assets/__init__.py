# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""axe_scene_assets.py — build the FOREST AXE scene's plates from scratch (2026-08-03).

A NEW SCENE, NOT A FORK OF THE CABIN. Nothing here reads scene20's anchor, mask, prop
plates or calibrated floors. The only things carried over are the things that are about
Abel rather than about that room: his LoRA, his bible, and the `arcane_animation` profile.

THE SCENE
    1  CLOSE   an axe buried in a tree; old scars and fresh pale wounds all around it
    2  MED-CL  Abel's hand and forearm enter, grip the haft, wrench it free (no face)
    3  WIDE    he walks back to his throwing mark
    4  CLOSE   his face — the breath before the throw; anger, sadness, focus
    5  MED     the wind-up and the throw; on release the screen dissipates
Five locked-off shots of <=81 frames. Camera moves (the pan-left, the zoom-out) are POST
moves on locked renders, never asked of the model.

WHY THE SCARS LIVE IN THE PLATE AND NOT IN THE PROMPT — this is the whole design.
Measured 2026-08-03: prop fidelity is as stable as a static wall for ~5s and then decays
4-6x by second 12, and small repeated high-frequency detail (page text, and by extension
axe scars) is re-invented by the model wherever it is asked to draw it. But VACE only
invents inside the MASK; everything outside is hard per-frame control it must preserve.
So the scars are authored ONCE into this plate and kept outside the character mask. The
model is never asked to draw them, so it cannot get them wrong. That converts the scene's
single hardest element into its most reliable one.

The same logic covers the axe while it is seated in the trunk. It only becomes fragile in
shot 2, where it has to move — which is why that shot is written so the head barely shifts
and the cut lands on it coming free.

LICENCE: the arcane pass runs through arcane_multichar._arcane_full, which since
2026-08-03 uses Depth-Anything-V2 **Small** (vits, Apache-2.0). Base/Large/Giant are
CC-BY-NC-4.0 and are refused. See _DEPTH_CKPT in arcane_multichar.py.
"""

import os
import shutil
import time


# ruff: noqa: F401,E402

from .tree_base import (
    ARC_ENV,
    ARC_ENV_SWEEP,
    FRAMINGS,
    H_GEN,
    H_REND,
    OUT,
    TREE_BASE_PROMPT,
    TREE_SCENE_DESC,
    W_GEN,
    W_REND,
    _ARC_ENV_NEG,
    _AXE_NEG,
    _AXE_PROMPT,
    _DIR,
    _JUG,
    _NEG_PLATE,
    _SCAR_NEG,
    _SCAR_PROMPT,
    _TREE_COMMON,
    _arcane_env,
    _free,
    _log_noop,
    build_tree_base,
    sweep_arcane_env,
    sweep_tree_base,
)

from .candidates import (
    PROP_DIR,
    apply_scars,
    build_candidates,
    build_tree_plate,
    find_trunk,
    paint_region,
)

from .sprites import (
    AXE_SPRITE_SEED,
    _AXE_SPRITE_NEG,
    _AXE_SPRITE_PROMPT,
    _BARK_PATCH_NEG,
    _BARK_PATCH_PROMPT,
    _match_colour,
    apply_scars_textured,
    composite_axe,
    key_white,
    sweep_axe_sprites,
)

from .hero import (
    _CLOSEUP_PROMPT,
    _ENTRY_NEG,
    _ENTRY_PROMPT,
    _HERO_NEG,
    _HERO_PROMPT,
    closeup_sweep,
    harmonise_entry,
    hero_sweep,
)

from .scar_height import (
    apply_scars_height,
    apply_scars_ratio3d,
    build_scar_height,
    height_to_shading,
)
