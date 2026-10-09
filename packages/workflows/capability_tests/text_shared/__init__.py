# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""text_shared.py — the bank every Story & text step runs IDENTICALLY. 2026-09-28.

Five steps are prompt-kind `text` (llm_script, llm_prompt, llm_agents, llm_research,
subtitles). Their sheets share 75 bank columns (8 counting, 10 spatial, 57 prompt-damage)
and 27 universal columns. Those questions are asked in the same words on every sheet, so
they must be TESTED with the same inputs on every sheet — a paraphrase test that uses one
passage for the writer and another for the researcher measures two different things.

Everything here is fixed text. A runner may not touch it.

    PASSAGE          one 1671 quay scene with a known answer to every counting and spatial question
    KEYS             the answers, with the variants the normaliser accepts
    EXTRACT_TASK     the JSON extraction with one right answer that the prompt-damage
                     variants are measured against (same meaning, other words → same JSON)
    FILLER(n)        deterministic padding for the context and limit probes
    SHARED           the merged dict a step test includes: probes, derive, lookup, wiring, na
    TRANSPORT_NA     the columns a row cannot answer because of HOW it is driven
"""

# ruff: noqa: F401,E402 -- the package re-exports the pre-split module namespace

from __future__ import annotations

from capability_tests.text_shared import banks
from capability_tests.text_shared import probes
from capability_tests.text_shared import dispositions

from capability_tests.text_shared.banks import (
    SYSTEM,
    PASSAGE,
    ATOMIC_SUFFIX,
    KEYS,
    EXTRACT_TASK,
    EXTRACT_KEY,
    EXTRACT_VARIANTS,
    FILLER_LINE,
    FILLER_WINDS,
    FILLER_RULE,
    NEEDLE,
    NEEDLE_Q,
    CONTEXT_SIZES,
    NEEDLE_DEPTHS,
    COND_LITERAL,
    COND_CREATIVE,
    COND_NOTE,
)
from capability_tests.text_shared.probes import (
    _probe,
    _atomic,
    EXTRACT_CHECKS,
    PROBES,
    col,
    txt,
)
from capability_tests.text_shared.dispositions import (
    DERIVE,
    LOOKUP,
    WIRING,
    NA,
    TRANSPORT_NA,
    SHARED,
)
