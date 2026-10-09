# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""video_shared.py — the bank every video and motion step runs IDENTICALLY. 2026-09-30.

Fourteen steps are video-kind (i2v, t2v, v2v, lipsync, interp, vfx, video_assembly, movement,
poses, gestures, facial, muscle, body_fit, rigging). Their sheets share 395 bank columns: the
132 `render_*` subjects (does the subject APPEAR correctly in the clip), the 132 `move_*` pairs
(does the same subject MOVE correctly — a dog moves like a dog, cloth moves with the body, a
hand keeps five fingers while it grips), 12 capacity ladders, 8 counting, 10 spatial, 10
attribute columns, 64 prompt columns and the 27 universal ones. Those questions are asked in
the same words on every sheet, so they must be TESTED with the same inputs on every sheet.

What this bank runs identically
-------------------------------
One FIXED clip per subject. The still that an i2v-type row starts from is the IMAGE bank's
approved subject render, `fixtures/video/subjects/<id>.png`; a t2v row renders the same subject
from `SUBJECTS[id]['prompt']`; every row is then driven by the same one-verb-phrase motion
prompt, the same negative prompt, the same 81 frames at the row's native fps, the same three
seeds [11, 12, 13] and the row's production `shift` recorded into the trial (on Wan, shift IS
the motion lever — [[project_wan_motion_debug]]).

What it cannot decide
---------------------
Whether a clip is correct. No local VLM judges defects reliably: the defect judge bench of
2026-09-27 scored 34/40 on a single global question and 2/8 on fused fingers, extra digits and
a second feather. So the "is the subject rendered and animated correctly" decision is an
OPERATOR blind check — one written yes/no question per subject, outputs anonymised and shuffled
across rows (`operator_protocol`) — PLUS a mechanical check wherever a detector exists:
MediaPipe hand_landmarker for hand and finger counts, ArcFace cosine for identity across the
clip, OCR for lettering and digits, a person detector for counts, optical flow for camera
moves and for "this thing must NOT move", PySceneDetect for cuts. Where both exist, both are
recorded and `state_note` says which decides.

How the operator checks
-----------------------
Every operator question is answered from a folder of anonymised clips (one per trial, the row
id replaced by a random letter, shuffled), with the frame-0 and last-frame stills laid side by
side for the render half. yes/no only; a "maybe" is a no.

Where this bank overlaps another
-------------------------------
body_fit and rigging are video-kind AND judge/geometry-kind, and the `Prompt: *` bands are owned
by every kind, so this bank must give those bands a disposition or `shared video --strict` fails.
It gives them a VIDEO-side probe, never an `na`: because video merges first for those two steps,
an `na` here would silently suppress the judge or geometry bank's own probe for the same column.
The six verdict columns (pd_question_wording, pd_leading, pd_yes_bias, pd_rubric_needed,
pd_abstain, pd_batched_questions) are probed here through `pdv_verdict_wording` on 12 of our own
clips, and exempted per transport for rows that return pixels rather than words. If the judge
bank later probes them better, the step module wins over the bank and nothing here has to move.

    SUBJECTS                 subject id -> label, still prompt, motion prompt, mechanical tags
    FIXED / COND_CLIP        the settings every row shares; DETECTORS pins the mechanical ones
    _subject_probe           the 132 subject probes: one clip answers render_* and move_*
    _ladder                  the capacity and limit ladders, whose answer is a COUNT not a yes
    _scene                   one fixed scene per counting / spatial / attribute column, with its key
    VBASE / VKEY             the prompt-damage base and the key every variant is measured against
    VARIANTS                 one damaged rewrite per pd_* column, against that SAME key
    DERIVE LOOKUP WIRING NA  the universal 27, split by what can honestly be claimed
    FIXTURES                 every file named here, its recipe, and what it blocks until verified
    TRANSPORT_NA             the columns a row cannot answer because of HOW it is driven
    SHARED                   the dict a step test includes with 'include_shared': 'video'
"""

from __future__ import annotations

# ruff: noqa: F401

# the submodules, in the EXACT original section order: every section after `probes`
# appends to the single PROBES list, so import order is the file order.
from .settings import (  # noqa: E402
    CHECK_KINDS,
    COLOUR_HUES,
    COND_CLIP,
    COND_NOTE,
    COND_ONE,
    DETECTORS,
    FIXED,
    NEGATIVE,
    SAMPLE5,
    STATE_3OF3,
)
from .subjects_a import (  # noqa: E402
    SUBJECTS_A,
)
from .subjects_b import (  # noqa: E402
    SUBJECTS_B,
)
from .subjects import (  # noqa: E402
    SUBJECTS,
)
from .probes import (  # noqa: E402
    OP_MOVE,
    OP_RENDER,
    PROBES,
    SUBJ_NOTE,
    _probe,
    _subject_probe,
)
from .capacity import (  # noqa: E402
    CAP_STATE,
    DIGITS,
    LADDER_NOTE,
    NAMED,
    NAMED_STILL,
    OBJECTS,
    SHOTS,
    TERMS,
    WORDS,
    _animals_rung,
    _digits_rung,
    _faces_rung,
    _hands_rung,
    _ladder,
    _named_rung,
    _objects_rung,
    _people_rung,
    _quay,
    _terms_rung,
    _words_rung,
)
from .scenes import (  # noqa: E402
    FR2,
    SCENE_NOTE,
    _dc,
    _op,
    _scene,
)
from .prompt_bands import (  # noqa: E402
    VARIANTS,
    VAR_NOTE,
    VBASE,
    VKEY,
    VMOTION,
    # the VARIANTS loop's leftover bindings, re-exported so the namespace is unchanged
    _col,
    _prompt,
    _what,
)
from .prompt_clarity import (  # noqa: E402
    CLARITY_RUNGS,
)
from .prompt_limits import (  # noqa: E402
    ACTIONS,
    ATTRS,
    CONSTRAINTS,
    INSTRUCTIONS,
    NEG_TERMS,
    PAD_SENTENCES,
    PROMPT_PAD,
    PROMPT_TAIL,
)
from . import prompt_steering
from . import universal
from .dispositions import (  # noqa: E402
    DERIVE,
    LOOKUP,
    NA,
    PROMPT_COLS,
    TRANSPORT_NA,
    TRANSPORT_NA_NOTE,
    WIRING,
    _JUDGE_ONLY,
    _NO_PROMPT,
    _RENDER_ONLY,
)
from .fixtures import (  # noqa: E402
    CONDITIONS_NOTE,
    FIXTURES,
    OPERATOR_PROTOCOL,
    SHARED,
)
