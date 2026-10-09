# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401,E402
"""Default test — Text to image (t2i). 2026-09-30.

Question the sheet asks: which checkpoint gives a usable first take from a prompt alone?

The shared image bank already answers 253 of the 279 columns — the 132 named subjects, the
capacity ladders, counting, space, attributes, the four prompt bands and the 27 universal
columns — at 1024x1024 on seeds [11, 12, 13] with one fixed negative. This module answers the
27 DOMAIN columns the bank leaves to the step: how much of a long prompt survives, whether a
negative removes a named thing, the anatomy columns the house rejects stills over, the style
and resolution levers, and the two LoRA columns.

Shape of the test
-----------------
One probe per domain column, at the bank's conditions, so a domain cell and a subject cell are
comparable. Three of them are A/B pairs where the measurement IS the difference between two
renders (negatives: with and without the term; lora_effect: with and without the adapter;
seed_stable: the same seed three times). Two are ladders whose cell is a NUMBER, not a yes/no
(steps, aspect). `res_native` and `lora_pairing` are lookups — a native resolution and a
pairing table are facts on disk, not things a render decides.

Honest judging
--------------
The 2026-09-27 defect bench settled that no local VLM catches a sixth finger (2/8 on the hard
cases), so every column about whether a body, a face or a light is RIGHT is an operator
question, asked blind, with a detector beside it wherever one exists: MediaPipe
hand_landmarker for fingers, InsightFace/YOLO for faces and people, GroundingDINO for
everything else, PaddleOCR for lettering, era_gate for anachronism, CLIP zero-shot for
"painting or photograph". The detector is authority for what it measures; the operator decides
the rest; both must pass.

What is blocked and why
-----------------------
Nothing in this module needs a fixture: t2i renders from the prompt alone. The bank's
`subject_fixtures` are declared unverified there and block the image-IN steps, not this one —
this step is where those fixtures come FROM. The one hard obstacle is on the row:
`_comfy_workflows/flux_txt2img.json` loads `flux1-dev.safetensors`, which is NOT in the
ComfyUI store on this machine (checked 2026-09-30: unet/, diffusion_models/ and checkpoints/
hold flux1-schnell but no flux1-dev). Until the weight is fetched every flux_dev cell is a
TRANSPORT failure — `untested` with the loader error — and not a `no`. That is recorded on the
row rather than hidden, because the operator needs to know before scheduling 6 GPU hours.
"""

from __future__ import annotations

from capability_tests.image_shared import COND_RENDER, NEGATIVE, QUAY
from zyg_workflows.paths import ZYG_COMFY_LORA_DIR

from capability_tests.t2i.constants import (
    CHECK_KINDS,
    STYLE_LABELS,
    LONG_PROMPT,
    LONG_FACTS,
    LONG_NOTE,
    COND,
    COND_ONE_SEED,
    LORA,
    LORA_SCALE,
    LORA_PAIRING,
    NO_LORA_REASON,
    _probe,
)
from capability_tests.t2i.probes import (
    PROBES,
)
from capability_tests.t2i.spec import (
    LOOKUP,
    DERIVE,
    _FLUX_DEV_WEIGHT,
    TEST,
)
