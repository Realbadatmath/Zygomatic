# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.remixai_analyze.title — verbatim from remixai_analyze.py lines 762-858.

section 3 — title FORMAT analysis and the original-title writer
"""

from __future__ import annotations

import os
import re
from zyg_workflows.remixai_analyze import llm as _zyg_llm

# Bound by ASSIGNMENT, never by `from … import`: CPython 3.12 refuses the
# method-call optimisation for an import-bound global, so `NAME.attr(...)`
# inside the moved code would compile to different bytecode than it did in
# the single-file remixai_analyze.py.
_llm = _zyg_llm._llm


# ── 3. title → FORMAT brief ─────────────────────────────────────────────────

_TITLE_ANALYZE_PROMPT = """Analyse this video title's FORMAT so a different title
can be built to the same pattern. Describe the shape, do not rewrite the title.

Return JSON exactly:
{"pattern": "the structural template, e.g. 'NUMBER + superlative noun + that + surprising verb phrase'",
 "hook_device": "one of: number / superlative / question / contrast / curiosity gap / authority claim",
 "capitalisation": "one of: title case / sentence case / all caps / mixed",
 "length_words": <int>,
 "has_number": true/false,
 "keywords": ["the searchable topic keywords, max 5"],
 "emotional_register": "2-4 words"}"""


def analyze_title(title: str, log=None) -> dict:
    if not (title or '').strip():
        return {}
    res, src = _llm(
        _TITLE_ANALYZE_PROMPT + f'\n\nTITLE: {title.strip()[:200]}', num_predict=500, stage='remixai-title-analyze'
    )
    if log and res:
        log(f'title format ({src}): {res.get("pattern", "")[:70]}')
    return res or {}


_TITLE_WRITE_PROMPT = """Write ONE original video title.

Build it to the FORMAT described below, for OUR topic. Do not reproduce or lightly
edit any existing title — write a new one that happens to use the same structural
device.

FORMAT: {pattern}
Hook device: {hook_device}
Capitalisation: {capitalisation}
Target length: {length_words} words. HARD CEILING: 12 words / 70 characters.
Include a number: {has_number}
Emotional register: {register}

OUR TOPIC: {topic}
OUR ANGLE: {angle}

Write ONE title, not a sentence. No trailing explanatory clause after a dash,
colon or semicolon — a title names the thing, it does not summarise it.

Return JSON exactly:
{{"title": "...", "alternates": ["two more options"]}}"""


_TITLE_MAX_WORDS = int(os.environ.get('ZYG_REMIXAI_TITLE_MAX_WORDS', '12') or 12)
_TITLE_MAX_CHARS = int(os.environ.get('ZYG_REMIXAI_TITLE_MAX_CHARS', '70') or 70)


def _tidy_title(t: str) -> str:
    """Trim a generated title down to something that is actually a title.

    The first real job returned 21 words: a full sentence with an em-dash clause
    bolted on ("... — achieving narrative continuity and character stability
    across sequences"). Models reliably do this when asked for a title in the
    same breath as a topic and an angle, because the angle reads as something to
    append. So the explanatory tail is CUT rather than re-prompted: everything
    after the first em-dash, colon or semicolon is the summary half, and the half
    before it is the name. Then a hard word/char ceiling on what remains."""
    t = re.sub(r'\s+', ' ', str(t or '')).strip().strip('"\'')
    t = re.split(r'\s+[—–-]\s+|\s*[:;]\s+', t, maxsplit=1)[0].strip()
    words = t.split()
    if len(words) > _TITLE_MAX_WORDS:
        t = ' '.join(words[:_TITLE_MAX_WORDS])
    if len(t) > _TITLE_MAX_CHARS:
        cut = t[:_TITLE_MAX_CHARS].rsplit(' ', 1)[0]
        t = cut or t[:_TITLE_MAX_CHARS]
    return t.rstrip(' ,.;:-—–')


def regenerate_title(fmt: dict, topic: str, angle: str, log=None) -> dict:
    """Format brief + our topic → a NEW title. The source title is not passed in."""
    prompt = _TITLE_WRITE_PROMPT.format(
        pattern=fmt.get('pattern', 'curiosity gap + topic keyword'),
        hook_device=fmt.get('hook_device', 'curiosity gap'),
        capitalisation=fmt.get('capitalisation', 'title case'),
        length_words=fmt.get('length_words', 8),
        has_number=str(bool(fmt.get('has_number'))).lower(),
        register=fmt.get('emotional_register', 'intriguing'),
        topic=topic or '',
        angle=angle or '',
    )
    res, src = _llm(prompt, num_predict=400, stage='remixai-title-write')
    if not res or not (res.get('title') or '').strip():
        return {}
    res['title'] = _tidy_title(res['title'])
    res['alternates'] = [_tidy_title(a) for a in (res.get('alternates') or []) if _tidy_title(a)][:2]
    res['source'] = src
    if log:
        log(f'title ({src}): {res["title"]}')
    return res
