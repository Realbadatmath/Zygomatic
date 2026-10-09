# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""capabilities_questions.py — the questionnaire behind Metrics > Capabilities (2026-09-28).

Each workflow step's sheet asks two kinds of question of every model/tool in it:

  DOMAIN    what this step specifically needs to know ("does the clip perform the action
            we named", "does the restyle keep the costume colour"). Written per step.
  UNIVERSAL the questions every tool in the house must answer whatever it does — licence,
            cost, reliability, operability. Shared, so a row in one sheet can be read
            against a row in another.

Together a step asks roughly 45-55 questions. That is the point: a five-column sheet
flatters everything in it, because the four things a tool happens to be good at are the
four things that got asked.

A question is written so the honest answer can be "not tested". Nothing here decides an
answer — capabilities_hub.py stores the answers and their grade, and a question with no
recorded answer ships as `untested`.

Column fields: id, label, hint, unit, higher_better (hb), group.
`id` is permanent — it is the key a recorded cell is stored under, so renaming one loses
that cell's evidence. Add, don't rename.
"""

# ruff: noqa: F401
# A package since 2026-10-06: the single 2,381-line file was cut at its own section
# banners. Submodules are imported in the EXACT original section order so the
# module-level DOMAIN/BANKS mutations still run in that order, and every name the old
# module defined is re-exported here, so `capabilities_questions.X` resolves unchanged.

from __future__ import annotations

from zyg_workflows.capabilities_questions.core import ALIASES, DOMAIN, UNIVERSAL, q
from zyg_workflows.capabilities_questions import domain_story_voice_music
from zyg_workflows.capabilities_questions import domain_sfx_image
from zyg_workflows.capabilities_questions import domain_video_motion
from zyg_workflows.capabilities_questions.domain_3d_judges import EXTRA
from zyg_workflows.capabilities_questions.banks import (
    ATTRIBUTES,
    AUDIO_CAPACITY,
    AUDIO_SUBJECTS,
    BANKS,
    COUNTING,
    SPATIAL,
    SUBJECTS,
    _banks,
    audio_bank,
    capacity_bank,
    subject_bank,
)
from zyg_workflows.capabilities_questions.prompt_damage import PROMPT_DAMAGE
from zyg_workflows.capabilities_questions.prompt_extra import (
    PROMPT_EXTRA,
    PROMPT_GROUPS,
    PROMPT_KIND,
    _k,
    _s,
    prompt_bank,
)
