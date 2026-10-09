# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""image_shared — the bank every image step runs identically. 2026-09-30.

Seven steps make pictures (t2i, i2i, inpaint, identity, controlnet, lora_train, upscale) and
all seven ask the same 253 shared questions: can the model draw 132 named subjects, how many
of a thing fit in one frame, does it count, does it place things left of each other, does it
obey a named colour, what does prompt damage do to it, and the 27 licence / cost / reliability
/ operability columns. This module answers those once, under conditions that do not move:
1024x1024, three fixed seeds [11, 12, 13], ONE negative prompt for every subject, no LoRA,
and the row's own production steps/cfg/sampler read from its workflow JSON into the trial.
A step module keeps only its domain columns and may override any probe here.

What this bank CANNOT decide by machine
---------------------------------------
No local VLM judges render defects reliably. The defect-judge bench of 2026-09-27 scored
34/40 on "is this picture broadly right" and 2/8 on the defects that matter — fused fingers,
an extra digit, a second feather. So "is the subject rendered correctly" is an OPERATOR
question, one written yes/no per subject, asked blind (see `operator_protocol`). Wherever a
real detector exists it runs BESIDE the operator and the `state_note` says which decides:
  MediaPipe hand_landmarker    hands present and five distinct fingertips each
  YOLOv8x-COCO / InsightFace   people, faces, dog / cat / horse / cow / sheep / bird counts
  GroundingDINO                open-vocabulary presence and counts for everything else
  PaddleOCR                    lettering, digits, dates, roman numerals, clock numerals
  ArcFace (buffalo_l)          the same named person twice
  LPIPS / pixel distance       did a one-word edit move only what it should
A detector that fires is authority for the thing it measures; the operator decides the rest.
Both must pass for the cell to be `yes`.

How a subject is scored
-----------------------
Three seeds, one render each. `yes` needs 3/3, `partial` 2/3 (`SUBJECT_STATE_RULE`). A render
that comes back empty or malformed is a `no` — it is what the model did. A queue that refuses
or times out is `untested` with the error.

Prompts
-------
One fixed prompt per subject, verbatim, in `SUBJECTS`, EVERY ONE UNDER 60 WORDS: SDXL's text
encoder truncates at 77 CLIP tokens and says nothing, so a longer prompt would test the
truncation, not the subject. Each prompt names ONE subject in plain daylight in the house
world (1671, the Kattenburg yard, the quay, a farmhouse) so a failure is the subject and not
the scene. `pd_clip77` is the ONE probe that deliberately goes past the window.
"""

from __future__ import annotations

# ruff: noqa: F401  -- the package re-exports the single module it replaces.

import sys as _sys

# `zyg_dashboard.capabilities_tests.shared_module` calls importlib.reload on this module.
# reload() re-runs only __init__.py, so the sections below would come back out of
# sys.modules unchanged and their module-level side effects (SUBJECTS.update,
# PROBES += ...) would not be rebuilt the way reloading the single file rebuilt them.
# Dropping them first makes a reload re-execute every section exactly as before.
for _m in [_n for _n in _sys.modules if _n.startswith(f'{__name__}.')]:
    del _sys.modules[_m]

# The sections, in the exact order of the original module, so every module-level side
# effect runs in the same sequence as it did in image_shared.py.
from capability_tests.image_shared.conditions import (  # noqa: E402
    CHECK_KINDS,
    COLOUR_BANDS,
    COND_NOTE,
    COND_RENDER,
    NEGATIVE,
    NEGATIVE_NOTE,
    PROMPT_NOTE,
    SUBJECT_FIXTURES,
)
from capability_tests.image_shared.subjects import (  # noqa: E402
    SUBJECTS,
)
from capability_tests.image_shared.probes import (  # noqa: E402
    PD_BASE,
    PD_CHECKS,
    PD_KEY_NOTE,
    PD_VARIANTS,
    PROBES,
    SUBJECT_CHECKS,
    SUBJECT_QUESTION,
    SUBJECT_STATE_RULE,
    _SUBJECT_NOTE,
    _col,
    _label,
    _probe,
    _prompt,
    _subject,
)
from capability_tests.image_shared.prompt_ladders import (  # noqa: E402
    CLARITY_KEY,
    CLARITY_LADDER,
    FILLER_CLAUSES,
    LANTERN_TAIL,
    LENGTH_KEY,
    LENGTH_RULE,
    LENGTH_RUNGS,
)
from capability_tests.image_shared.steer_capacity import (  # noqa: E402
    CAP_NOTE,
    QUAY,
    STEER_BASE,
)
from capability_tests.image_shared.count_space import (  # noqa: E402
    _SP_SCENE,
)
from capability_tests.image_shared.attributes import (  # noqa: E402
    U_PROMPT,
)
from capability_tests.image_shared.facts import (  # noqa: E402
    DERIVE,
    LOOKUP,
    NA,
    SHARED,
    TRANSPORT_NA,
    TRANSPORT_NA_NOTE,
    WIRING,
    _NO_PROMPT_REASON,
    _NO_PROMPT_TRANSPORTS,
    _NVIDIA,
    _PROMPT_COLS,
)
