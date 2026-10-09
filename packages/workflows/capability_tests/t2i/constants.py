# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Check kinds, the long prompt, the conditions and the LoRA facts.

Moved verbatim out of the old single-file t2i.py (lines 52-162).
"""

from __future__ import annotations

from capability_tests.image_shared import COND_RENDER
from zyg_workflows.paths import ZYG_COMFY_LORA_DIR  # noqa: F401 - LORA_PAIRING cites it


# Check kinds this step adds. The base vocabulary is capability_tests/__init__.py and the
# image bank adds the detector kinds; these six are what the domain columns need on top, and
# the runner must implement exactly these rules.
CHECK_KINDS = {
    'box_centre_offset': 'the centre of the largest GroundingDINO box for `query` (above `min_score`) sits at '
    'least `min_frac` of the frame width away from the frame centre on the x axis, and no '
    'more than `max_frac` — an off-centre subject, measured, not judged',
    'depth_size_gradient': 'GroundingDINO finds exactly `count` boxes for `query` above `min_score`; sorted by box '
    'area descending, each next box has area <= `ratio` x the previous AND its top edge at '
    'or above the previous box top edge — the box signature of a row receding from camera',
    'clip_style_label': 'the pinned CLIP model (openai/clip-vit-large-patch14) zero-shot top-1 label over '
    'STYLE_LABELS for this frame is one of `expect`',
    'clip_style_pairwise_max': 'the cosine distance between the CLIP (openai/clip-vit-large-patch14) image embeddings '
    'of every pair of the frames named in `set` is <= `max`; the trial keeps the worst pair',
    'era_gate_clean': 'era_gate.py crop checks derived from this probe prompt report no anachronism at or '
    'above era_gate production confidence for this frame; the trial keeps every finding',
    'lora_names_in_trial': 'the ComfyUI history for this render names exactly the LoRA files in `loras` (an empty '
    'list means no LoraLoader ran) — the receipt that the adapter was applied at all',
}

STYLE_LABELS = [
    'an oil painting',
    'a photograph',
    'a 3d render',
    'an anime drawing',
    'a pencil drawing',
    'a watercolour painting',
]

# ── the long prompt: 90 words, twelve checkable facts ───────────────────────────────────────
LONG_PROMPT = (
    'Cornelis, a grey-bearded Dutch shipwright of about fifty, stands on the stone quay at '
    'Kattenburg, Amsterdam, in 1671, plain daylight. He wears a red wool cloak with five brass '
    'buttons and a wide black felt hat. In his left hand he holds an unlit brass lantern; his '
    'right hand rests on a wooden barrel. Three white gulls stand on the quay wall behind him. '
    'A single wooden sailing ship is moored at the far end of the quay. Wet cobbles, no other '
    'people, nothing modern anywhere in the frame.'
)
LONG_FACTS = [
    'F1  one man, about fifty, grey-bearded, and nobody else',
    'F2  the cloak is red',
    'F3  five brass buttons on it, countable',
    'F4  a wide black felt hat',
    'F5  an unlit lantern in his LEFT hand',
    'F6  his right hand resting on a wooden barrel',
    'F7  exactly three white gulls',
    'F8  the gulls on a wall BEHIND him',
    'F9  one wooden sailing ship, moored',
    'F10 the ship FAR away at the end of the quay',
    'F11 the cobbles wet',
    'F12 nothing modern anywhere',
]
LONG_NOTE = (
    'This cell is a SHARE, not an all-or-nothing pass: the runner counts how many of the twelve '
    'facts land per render and averages over the three seeds, so a model that gets ten of twelve '
    'reads as ten of twelve. yes needs 9/12 (0.75), partial 6/12 (0.5). '
    'The prompt is 89 words ON PURPOSE and it is the only probe on this step that goes past the '
    'bank 60-word rule: the column asks whether a LONG prompt is followed. On a 77-token CLIP '
    'encoder (all three SDXL rows) the tail of it is silently cut, and that is the finding — the '
    'trial records the CLIP token count and which fact the cut fell on, so the cell can be read '
    'beside pd_max_soft and pd_clip77 in the bank instead of being mistaken for incompetence.'
)

# ── conditions ─────────────────────────────────────────────────────────────────────────────
COND = dict(COND_RENDER)
COND_ONE_SEED = dict(COND_RENDER, seeds=[11], repeats=1)

LORA = 'abel_arcane_v2_sdxl_kohya.safetensors'
LORA_SCALE = 0.8
# Read off $ZYG_COMFY_LORA_DIR on 2026-09-30. A row with no trained
# adapter is an ANSWER for lora_pairing (none exists for that base here), not a gap.
LORA_PAIRING = {
    'sd_xl_base_1.0.safetensors': [
        'abel_arcane_sdxl_kohya.safetensors',
        'abel_arcane_v2_sdxl_kohya.safetensors',
        'cornelis_arcane_sdxl_kohya.safetensors',
        'cornelis_char_sdxl_kohya.safetensors',
        'zygchar_*_sdxl_kohya.safetensors',
    ],
    'flux-2-klein-base-4b.safetensors': ['flux2_klein_4b_refcontrol_depth.safetensors', 'zygchar_*_klein.safetensors'],
    'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors': [],
    'DynaVisionXL.safetensors': [],
    'flux1-dev.safetensors': [],
    'flux1-schnell.safetensors': [],
    'qwen_image_2512_fp8_e4m3fn.safetensors': [
        'qwen_edit_2509_multiple_angles.safetensors (EDIT, not t2i)',
        'qwen_edit_skin.safetensors (EDIT, not t2i)',
    ],
}
NO_LORA_REASON = (
    'No text-to-image LoRA trained for this base exists in the ComfyUI store on this machine '
    '(loras/ read 2026-09-30: every kohya adapter is sd_xl_base_1.0, the two klein files are a '
    'depth reference-control adapter and character packs, the qwen files are EDIT adapters for '
    'qwen_image_edit). There is therefore no A/B to run for this row: the column is not '
    'unmeasured, there is nothing on this machine for it to be about. lora_pairing (the lookup) '
    'carries that same fact as its answer, which is where the reader should look.'
)


def _probe(pid, title, feeds, prompt, checks, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'prompt': prompt},
        'conditions': dict(COND),
        'checks': [dict(c) for c in checks],
        'grade': 'measured',
    }
    p.update(kw)
    return p
