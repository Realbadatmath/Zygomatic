# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Text to speech (tts). 2026-09-30.

Question the sheet asks: which TTS engine can hold a named character voice through a whole
render? Its own verdict already names the failure mode: every engine in the stack is a
zero-shot CLONER, and cloners fail QUIETLY — they synthesise confident, well-formed speech in
the wrong voice. So this test never asks an engine whether it did well. It renders twelve
fixed lines and one 600-word passage from two fixed references, and measures the take with a
speaker embedding, Praat F0/VTL, Whisper timings and level meters; where no detector exists
(breath, wear, a laugh, Dutch names) the check is a BLIND operator yes/no with the question
written down here.

Shape of the test
    REFERENCES  two seeds from the 16-voice pool (m01_warm_baritone, f01_warm_alto) — Maya1
                output, apache-2.0, nobody recorded; the first 10.0 s of each is the reference.
    LINES       twelve lines, verbatim below. Five are the house audition lines
                (voice_studio.DEFAULT_LINES) so a take here is comparable with every bench
                already on disk, which measured on DEFAULT_LINES[0]. The Dutch line is the one
                capability_tests/voice_clone.py uses, for the same reason.
    PASSAGE     the first 600 words of fixtures/tts/passage_600.txt — the long-form and
                age-drift leg, ~4 minutes of audio per take.
    CONDITIONS  seeds [11, 12, 13], repeats 3, delivered 48 kHz mono (the audio bank's
                settings); each engine renders at its native rate and the runner records it.

What is blocked, and why
    `child` is BLOCKED. The house has no verified pre-pubescent child reference. Abel is the
    only young seed and he is NOT a child: abel_narrator_seed.json records voice_age 14-15,
    age_class teen_male, seed 171.9 Hz / 14.64 cm, and Chatterbox rendered him at 154.8 Hz /
    15.94 cm — it GREW the tract by 1.3 cm. The design notes also record why a child seed is
    hard to fake: VTL saturates around 14.4 cm at large pitch shifts, so a pitch-shifted adult
    lands in adult-female territory rather than in a child's. The Abel leg is measured anyway
    and recorded; the column stays `untested — key unverified` until fixtures/tts/child_reference.wav
    exists and the operator has confirmed it.

Two receipts that change how columns are read
    ROMAN NUMERALS are expanded by tts_service.py BEFORE synthesis, and only when the preceding
    word is a real capitalised word of 3+ letters (measured over the scholarly scripts: a bare
    token scan is almost all false positives — I x197, C x94). So the `roman` probe runs both
    legs: in context (expansion expected) and bare (no expansion expected). A row that reads
    "ex-vee-eye-eye" on the bare leg is reporting the SERVICE's gate, not its own weakness, and
    the state_note says so.
    WHISPER RE-FORMATS NUMERALS, so it cannot tell "sixteen seventy-one" from "one thousand six
    hundred and seventy-one" — both come back as 1671. `numbers` therefore keeps the transcript
    only as a screen and lets a blind operator decide, which is the same rule the audio bank
    applies to CLAP.

Everything else — the 53-sound banks, the seven Capacity ladders, the four Prompt bands, the
Licence, Cost, Reliability and Operability columns — comes from capability_tests/audio_shared.py
unchanged, so this sheet and every other audio sheet ask those questions with identical inputs.
"""

# ruff: noqa: E402,F401  # Pattern A re-export shim: the package IS the old module.

from __future__ import annotations

# The sections, imported in their original order.
from .constants import (
    AGED,
    BANDS,
    BANDS_NOTE,
    CHECK_KINDS,
    COND,
    COND_ONE,
    COS_MARGIN,
    COS_MIN,
    COS_TAKES,
    COS_WINDOW,
    F0_PCT,
    FX,
    LINES,
    LINES_NOTE,
    OVERLONG,
    PASSAGE,
    PASSAGE_RULE,
    POOL,
    REFS,
    REF_NOTE,
    REF_SECONDS,
    SEEDS_DIR,
    THRESHOLD_NOTE,
    VTL_CM,
)
from .probes import PROBES, _p, _REF_COS
from .rows import (
    EDGE_NA,
    ROWS,
    TEST,
    _EDGE_NO_REF,
    _EDGE_NO_STYLE,
    _NOT_A_SYNTH,
    _NOT_A_SYNTH_NA,
    _RETIRED_BARK,
    _RETIRED_TORTOISE,
)
