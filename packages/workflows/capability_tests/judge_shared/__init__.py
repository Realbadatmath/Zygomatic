# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""judge_shared.py — the bank every JUDGE step runs IDENTICALLY. 2026-09-30.

Eight steps are prompt-kind `judge` (vlm_judges, pixel_gates, detectors, identity_gates,
text_judges, and — as a second bank beside audio/video — diarization, body_fit,
audio_judges). Their sheets share 132 `Sees:` columns, 132 `Names:` columns, the capacity
ladders, the counting / spatial / attribute questions, the four Prompt bands and the 27
universal columns. Those questions are asked in the same words on every judge sheet, so
they must be TESTED with the same pictures and the same wording on every judge sheet.

What this bank runs identically
-------------------------------
    SUBJECTS         132 subjects, one fixed render prompt each (< 60 words — SDXL truncates
                     silently at 77 CLIP tokens), one label, one synonym list
    every subject    a POSITIVE fixture (the subject is there) AND a matched NEGATIVE one.
                     A judge that answers "yes" to everything scores 50 %, not 100 % — that
                     is the whole point of the pair and the reason recall AND precision are
                     both in the state rule.
    SEE_Q / NAME_Q   one atomic question per subject; the era-gate lesson is that a bundled
                     question cannot be trusted and one checkable question per call can
    COUNT/SPACE/ATTR one matched A/B pair per column, each half carrying its OWN key, so the
                     same answer cannot be right on both
    CAPACITY         ladders whose answer is a COUNT: the last rung that still passed
    BASE_Q           one JSON question about one picture with one right answer; the
                     prompt-damage variants reword it and are scored against the SAME key
    the universal 27 derived from the run's telemetry, looked up with a pinned source,
                     read off the wiring, or `na` with a written reason

What this bank CANNOT decide
----------------------------
No local VLM judges defects reliably. The defect-judge bench of 2026-09-27
($ZYG_LEDGER_INTRO/intro/defect_bench/sheet.json: 6 pictures,
55 questions, 5 models) measured the best model at 34/40 on a global "is anything wrong
here" question and 2/8 on the hard defect classes — fused fingers, extra digits, a second
feather. era_gate's moondream scored 34/40 where Qwen3-VL scored 2/8 on the same crops.
So this bank NEVER lets a VLM decide whether its own fixture shows what its label says.
Two things decide instead, and `state_note` says which:

  * a MECHANICAL detector wherever one exists — MediaPipe hand_landmarker and face mesh
    (anatomy_qc.py) for hands, fingers and faces, the ultralytics person class
    (continuity_qc.py) for people, ArcFace (identity_qc_service.py) for identity, the
    typography OCR judge for lettering, digits, dates, roman numerals and clock faces;
  * the OPERATOR, blind — see `operator_protocol`: one written yes/no question per subject,
    the outputs anonymised and shuffled across rows before anyone sees a model name.

How the operator checks
-----------------------
Every fixture here is declared `verified: False` and BLOCKS the columns it feeds until the
operator has opened the contact sheet once and confirmed, per subject, that the positive
picture shows the subject and the negative one does not. Until that flag flips, those
columns are written `untested` with the note "key unverified" — we do not grade a model
against an answer we have not checked ourselves. Nothing in this file is executed: it is
inputs, conditions, checks and thresholds.
"""

from __future__ import annotations

import os

from zyg_workflows.paths import ZYG_HOME

# ruff: noqa: F401

from . import settings  # noqa: E402
from . import subjects  # noqa: E402
from . import probes_subjects  # noqa: E402
from . import probes_pairs  # noqa: E402
from . import probes_ladders  # noqa: E402
from . import prompt_damage  # noqa: E402
from . import prompt_clarity  # noqa: E402
from . import prompt_limits  # noqa: E402
from . import prompt_steering  # noqa: E402
from . import universal  # noqa: E402
from . import transports  # noqa: E402

from .settings import (  # noqa: E402
    CHECK_KINDS,
    COND_JSON,
    COND_JUDGE,
    COND_LONG,
    COND_NOTE,
    LEDGER_INTRO,
    RESOLUTION,
)
from .subjects import (  # noqa: E402
    FIX,
    HOW_TO_VERIFY,
    LADDER_DIR,
    MECHANICAL,
    NAME_Q,
    NEG,
    PAIR_DIR,
    PROMPT_DIR,
    SEE_Q,
    SUBJECTS,
    SUBJECT_NEG_RULE,
    SUBJECT_PROMPT,
    SUBJ_DIR,
)
from .probes_subjects import (  # noqa: E402
    PROBES,
    _accept,
    _clause,
    _label,
    _m,
    _mech_check,
    _sid,
    _subject_fixture,
)
from .probes_pairs import (  # noqa: E402
    PAIRS,
    _a_accept,
    _a_clause,
    _b_accept,
    _b_clause,
    _ck,
)
from .probes_ladders import (  # noqa: E402
    LADDERS,
    LADDER_NOTE,
    LADDER_VERIFY,
    _checks,
    _mech,
    _rungs,
    _stem,
    _unit,
)
from .prompt_damage import (  # noqa: E402
    BASE_FIXTURE,
    BASE_IMAGE,
    BASE_IMAGE_PROMPT,
    BASE_KEY,
    BASE_TASK,
    DAMAGE,
    DAMAGE_CHECKS,
    _col,
    _q,
    _title,
    _what,
)
from .prompt_clarity import (  # noqa: E402
    CLARITY_LADDER,
    HOUSE_Q,
    PROSE_Q,
    TAGS_Q,
)
from .prompt_limits import (  # noqa: E402
    INSTR_RUNGS,
    LENGTH_RUNGS,
    THINGS_RUNGS,
)
from .universal import (  # noqa: E402
    DERIVE,
    LOOKUP,
    NA,
    WIRING,
)
from .transports import (  # noqa: E402
    SHARED,
    TRANSPORT_NA,
    _BUILTIN_NA,
    _BUILTIN_PROMPT_NA,
)
