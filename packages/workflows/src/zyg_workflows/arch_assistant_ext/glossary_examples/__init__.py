# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""glossary_examples — the assistant's KNOWLEDGE layer (no new kinds).

Every other family adds a capability; this one adds the words. Three tools:

  · explain(topic)   — how to ask for something, and which tool does it.
  · translate(word)  — the English studio term for a Dutch / German / French word.
  · units(text)      — feet / inches / yards to metres, floors / verdiepingen /
                       etages to storeys.

It also carries the family's real payload: EXAMPLES, a spread of request -> tool
call pairs covering EVERY family (>= 2 each) in English, Dutch, German and
French. The system prompt shows the first 40 of the pooled EXT_EXAMPLES, so
these are what the model actually learns the studio's dialect from.

Nothing here draws. The tools are read-only: no records, no object ceiling.
"""

# This package is the former single-file module glossary_examples.py, cut at its own
# section banners.  Import path, names and module-level execution order are
# unchanged; every section below is a verbatim move.
# ruff: noqa: F401

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.glossary_examples.terms_nl import (
    re,
    unicodedata,
    Drawing,
    STOREY_M,
    KINDS,
    OPENINGS,
    PROMPT,
    _norm,
    _NL,
)
from zyg_workflows.arch_assistant_ext.glossary_examples.terms_de_fr import (
    _DE,
    _FR,
    GLOSSARY,
    _src,
    _lang,
    _k,
    _v,
    translate,
    language_of,
    _LEN_RE,
    _ST_RE,
    _FT,
    _IN,
    _YD,
    units,
)
from zyg_workflows.arch_assistant_ext.glossary_examples.explain_sheets import (
    _DESIGN_RULES,
    EXPLAIN,
)
from zyg_workflows.arch_assistant_ext.glossary_examples.tools import (
    _ALIAS,
    TOPICS,
    explain,
    t_explain,
    t_translate,
    t_units,
    TOOLS,
)
from zyg_workflows.arch_assistant_ext.glossary_examples.examples_nl_de_fr import (
    EXAMPLES,
)
