# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The three text cleaners stage 3 defines before it calls the editing LLM.

Originally lines 269-684 of the pre-split `stages_01_18.py`: one factory whose
body was three nested `def`s closing over a local `re` alias. The cleaning
logic now lives at module level in `stage_03_cleaners_regex`, where each phase
and each former closure is a testable function; `_script_cleaners` stays as the
stage's entry point and keeps returning the same three callables in the same
order, so `stage_03.py` and the package `__init__` are untouched.
"""

from .stage_03_cleaners_regex import _regex_clean, _strip_citation_header, _strip_llm_preamble


def _script_cleaners():
    """Return the (header stripper, regex cleaner, LLM preamble stripper) triple."""
    return _strip_citation_header, _regex_clean, _strip_llm_preamble
