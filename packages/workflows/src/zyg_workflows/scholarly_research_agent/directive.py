# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Free-text directive keyword extraction and Claude subject extraction."""

from zyg_workflows.scholarly_research_agent.constants import re
from zyg_workflows.scholarly_research_agent.constants import _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.scholarly_research_agent')


# ── Free-text directive keyword extractor ─────────────────────────────────────
# Words stripped before building search queries from a user's raw prompt.
_DIRECTIVE_NOISE_WORDS = {
    'create',
    'make',
    'a',
    'an',
    'the',
    'documentary',
    'video',
    'film',
    'movie',
    'show',
    'episode',
    'series',
    'on',
    'about',
    'for',
    'and',
    'or',
    'how',
    'what',
    'why',
    'when',
    'where',
    'is',
    'are',
    'was',
    'were',
    'with',
    'all',
    'some',
    'many',
    'most',
    'more',
    'top',
    'best',
    'new',
    'in',
    'into',
    'at',
    'to',
    'from',
    'by',
    'as',
    'up',
    'do',
    'get',
    'vs',
    'this',
    'that',
    'these',
    'those',
    'me',
    'my',
    'we',
    'our',
    'you',
    'your',
    'it',
    'its',
    'they',
    'their',
    'research',
    'essay',
    'paper',
    'study',
    'analysis',
    'academic',
}


def _extract_keywords(text: str) -> list:
    """Extract meaningful content words from a free-text directive or topic string.
    Strips production/filler words to reveal the actual subject matter."""
    words = re.sub(r'[^a-z\s]', '', text.lower()).split()
    return [w for w in words if w not in _DIRECTIVE_NOISE_WORDS and len(w) > 2]


def _claude_extract_subject(directive: str) -> str:
    """Ask Claude to identify the real search subject from the user's directive.

    Returns a clean 1–4 word search phrase (e.g. 'Jacque Fresco') or empty
    string if Claude is unavailable or the call fails.  Falls back gracefully —
    the dumb keyword extractor is still used when this returns ''.
    """
    from zyg_workflows.subscription_llm import (
        anthropic_client as _sub_client,
        api_key_or_login as _sub_key,
        MODEL_SMALL as _sub_small,
    )

    api_key = _sub_key()
    if not api_key:
        return ''
    try:
        client = _sub_client(api_key)
        resp = client.messages.create(
            model=_sub_small,  # 2026-09-17: Opus 5 on the subscription (was Haiku on the key)
            max_tokens=60,
            temperature=0.0,
            messages=[
                {
                    'role': 'user',
                    'content': (
                        'Extract the main search subject from this documentary request. '
                        'Return ONLY the subject as a short phrase (1–4 words), nothing else.\n\n'
                        f'Request: "{directive}"\n\n'
                        'Examples:\n'
                        '  "make a documentary about Jacque Fresco and his buildings" → Jacque Fresco\n'
                        '  "documentary on the French Revolution" → French Revolution\n'
                        '  "show me how black holes work" → black holes\n'
                        '  "video about the life of Nikola Tesla" → Nikola Tesla\n\n'
                        'Subject:'
                    ),
                }
            ],
        )
        subject = resp.content[0].text.strip().strip('"\'').strip()
        # Sanity check — reject if too long or looks like a sentence
        if subject and len(subject.split()) <= 6 and '.' not in subject:
            return subject
    except Exception as _exc:
        _zyg_log.warning('subject extraction failed, falling back to the raw directive: %s', _exc)
    return ''
