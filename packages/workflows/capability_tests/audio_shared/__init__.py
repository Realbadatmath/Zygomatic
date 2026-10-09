# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401
"""audio_shared.py — the bank every voice, music and sound step runs IDENTICALLY. 2026-09-30.

Fifteen steps are prompt-kind `audio` (tts, voice_clone, voice_direction, voice_conversion,
stt, diarization, music_gen, melody, stem_split, sfx_gen, sfx_library, sfx_process, audio_mix,
lipsync, audio_judges). Their sheets share the two 53-sound banks (`Makes:` — the engine
renders the sound; `Hears:` — a judge recognises it in a fixture recording), the 7 Capacity
ladders, the 8 Counting columns, the four Prompt bands and the 27 universal columns. Those
questions are asked in the same words on every sheet, so they must be TESTED with the same
inputs on every sheet: a paraphrase test that uses one prompt for the sfx generator and
another for the singer measures two different things.

Everything here is fixed text. A runner may not touch it.

    SOUNDS           the 53 subjects: id -> (CLAP label, the verbatim render prompt)
    SETTINGS         48 kHz mono, 4 s (ambience 12 s), seeds [11, 12, 13] — the SAME every row
    BASE_PROMPT      the prompt-damage base with a mechanical key (three knocks -> onset_count 3)
    DAMAGE_VARIANTS  one variant per pd_* column, all measured against the SAME key
    FIXTURES         every recording the bank needs, with its recipe and its verification state
    SHARED           the merged dict a step test includes: probes, derive, lookup, wiring, na
    TRANSPORT_NA     the columns a row cannot answer because of HOW it is driven

WHAT THIS BANK RUNS IDENTICALLY
    Each `make_*` column is ONE fixed prompt, rendered at three fixed seeds, screened by CLAP
    against its label and decided by a BLIND operator listen. Each `hear_*` column is ONE
    fixture recording whose true label must rank FIRST among all 53 labels. Capacity columns
    are LADDERS whose answer is a COUNT — the last rung that passed. The Prompt bands mirror
    text_shared: one base task, one variant per column, a clarity ladder, a length ladder, a
    distinct-things ladder, a small-edit chain and a seed-versus-prompt grid.

WHAT IT CANNOT DECIDE
    No machine judges "is this really a door creak, and only that". CLAP is a SCREEN, not a
    judge: measured 2026-09-27 on the house library, a correct render scored 0.827 while a
    chroma-only match scored 0.279 against a 0.252 null — the margin is real but small, and a
    plausible-but-wrong sound passes it. So every `make_*` column carries BOTH a
    `clap_label_min` screen and a BLIND operator yes/no, and the OPERATOR decides. Where a
    detector exists it is used and it is mechanical: librosa onsets for counted events, Whisper
    for words (WER) and for words that must NOT be there, pyannote for how many voices,
    LUFS / true-peak / silence for levels, an RT60 estimate for space, CLAP ranking for
    recognition. The defect-judge bench of 2026-09-27 (34/40 on a global question, 2/8 on a
    local one) is why no local model is asked "is this correct".

HOW THE OPERATOR CHECKS
    See `operator_protocol`. Every operator check is blind: the wavs are written to a folder
    named by a random letter, shuffled across rows and across ladder rungs, and the operator
    answers the written question per item with the model name, the seed and the rung hidden.
"""

from __future__ import annotations

from .settings import (
    AMBIENCE,
    CHECKS_NOTE,
    CHECK_KINDS,
    CLAP_ABSENT_MAX,
    CLAP_MIN,
    CLAP_NULL_MARGIN,
    COND_AMB,
    COND_JUDGE,
    COND_NOTE,
    COND_ONE,
    COND_SOUND,
    DISTANCE_PAIR,
    SETTINGS,
    SOUNDS,
    SOUND_EXTRA,
    SOUND_LABELS,
)
from .fixtures import (
    BASE_CHECKS,
    BASE_LABEL,
    BASE_PROMPT,
    DAMAGE_VARIANTS,
    FIXTURES,
    LYRIC_80,
    LYRIC_RULE,
    PROBES,
    _HEARS_HOWTO,
    _HEARS_RECIPE,
    _probe,
)
from .banks import (
    _COUNT,
    _COUNT_SUFFIX,
    _accept,
    _checks,
    _extra,
    _fx,
    _ins,
    _lbl,
    _pr,
    _q,
    _sid,
)
from .prompt_damage import (
    JUDGE_FIX,
    JUDGE_Q_NEUTRAL,
    _col,
    _text,
)
from .prompt_clarity import (
    CLARITY_RUNGS,
    PROSE_VARIANTS,
)
from .prompt_limits import (
    LEN_CLAUSES,
    LEN_RULE,
    LEN_RUNGS,
)
from .prompt_steering import (
    STEER_CHAIN,
)
from .shared import (
    CONDITIONS_NOTE,
    DERIVE,
    LOOKUP,
    NA,
    OPERATOR_PROTOCOL,
    SHARED,
    TRANSPORT_NA,
    WIRING,
    _SRC,
    _lk,
)
