# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""era_gate.py — per-slot, prompt-derived, crop-based anachronism gate (2026-08-25).

Why this exists
---------------
The documentary period lock policed WORDS. `_period_guard` rejects a prompt that
says "car" or "jeans"; the Black Death episode (run 2f1ffabb) contained none and
still shipped 19 major anachronisms — a motor fishing boat, telegraph poles, a
baby's sneaker, a wristwatch, electric festoon bulbs, a CCTV floodlight and
coronavirus icons on a 1349 map. The failure is the unqualified noun: "vessel"
renders as a motor boat, "lantern" as a gas lamp, and any head without a
described hairstyle gets a 2020s haircut.

The one pixel-level check that existed asked moondream a single global question
("does this show anything modern?") and could not be turned on: yes on 34/40
frames from moondream, 2/8 recall from Qwen3-VL at 1280 px — it missed a
full-width motor boat.

What this does instead — the same decomposition that turned the typography judge
from useless into primary:

  1. ONE cheap Haiku call per batch extracts the CHECKABLE OBJECTS from each S
     prompt: boat -> "no engine, wheelhouse or glass windows"; clothing -> "no
     buttons, zips, T-shirts, sneakers". Each check carries a positive 'fix'
     phrase the retry ladder appends when it fails. A deterministic keyword
     derivation is the fallback, so the gate never depends on the API.
  2. Universal tells every historical frame is asked about regardless of prompt:
     poles/wires, shopfronts/printed signs, wristwatches/bangles/painted nails,
     modern haircuts, modern dress, electric light.
  3. Two content questions: "is the prompted subject present?" (catches bubo ->
     naval mine, the missing ruin, flea -> winged fly) and "open wound or exposed
     bone visible?" (render-level gore from a clean prompt).
  4. Qwen3-VL answers one atomic yes/no per item over 3x2 ENLARGED TILES of the
     frame rather than the full frame — the crop rule from the VLM-inspector
     work; a boat that hides at 1280 px is unmissable in a 640 px tile. The
     subject question is asked on the full frame.
  5. Every flag carries a bbox mapped back into frame coordinates (0-1000, the
     vlm_inspector convention), so small items (a watch, a bulb, a sneaker) can
     go to region repair instead of a re-render.

Judge order: local Qwen3-VL through vlm_inspector (free, bbox-capable) when the
GPU can hold it; otherwise a single Anthropic vision call with the same tiles
and the same question list. Neither available -> {'skipped': True}, never a pass.

Bench before wiring: scripts/bench_era_gate.py re-extracts an episode's frames
from its mp4 and scores this gate against a hand-confirmed truth set. An
unmeasured gate is a decoration.
"""

# ruff: noqa: F401  this __init__ IS the re-export surface of the old era_gate.py.
from __future__ import annotations

# The submodules are imported in the original section order, so any module-level
# side effect still runs exactly when it did in the single-file era_gate.py.
from zyg_workflows.era_gate.constants import (
    base64,
    json,
    os,
    re,
    tempfile,
    time,
    Callable,
    _zyg_logging,
    _zyg_log,
    _DIR,
    BUCKETS,
    period_bucket,
    PERIOD_VOCAB,
    UNIVERSAL_ITEMS,
    GORE_ITEM,
    QUESTION_TEMPLATES,
    _after_phrase,
    _KIND_TO_VOCAB,
)
from zyg_workflows.era_gate.checks import (
    _OFFLINE_RULES,
    _STAINED_RE,
    check_for_kind,
    derive_checks_offline,
    subject_phrase_offline,
    extract_checks,
    _resolve_fix,
    build_items,
)
from zyg_workflows.era_gate.judge import (
    tile_boxes,
    make_tiles,
    map_tile_bbox,
    bbox_area_frac,
    _preamble,
    _preamble_frame,
    judge_frame,
    _judge_local,
    _judge_api,
    region_repair,
    ladder_qualifier,
)
