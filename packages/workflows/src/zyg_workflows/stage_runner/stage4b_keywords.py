# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 4b keyword tables and the narrator commentary helper."""

import os
from zyg_workflows.pipeline_config import _OLLAMA_BASE_URL
from zyg_workflows import http_json


def _make_keyword_tables(_log_warn):
    """Build Stage 4b's keyword tables and narrator commentary helper.

    The ``if True`` is an indentation guard: it keeps the block below at the
    depth it had inside _stage_preflight, so the move is byte-for-byte
    (original lines 1061-1238).
    """
    if True:
        # Viral / high-emotion keywords for transcript scoring
        _VIRAL_KEYWORDS = {
            # Shock / disbelief
            'insane',
            'crazy',
            'unbelievable',
            'no way',
            'what the',
            'oh my god',
            'holy',
            'bro',
            'bruh',
            'wait',
            'stop',
            'what',
            'wtf',
            'omg',
            # Fight / confrontation
            'fight',
            'punch',
            'hit',
            'slap',
            'kick',
            'attack',
            'beat',
            'knocked',
            'beef',
            'beef with',
            'square up',
            'pull up',
            'jumped',
            'rushed',
            # Reaction / drama
            'drama',
            'exposed',
            'caught',
            'cheating',
            'lying',
            'fired',
            'banned',
            'cancelled',
            'lawsuit',
            'arrested',
            'leaked',
            'broke up',
            'breakup',
            'pregnant',
            'baby',
            'confession',
            'confessed',
            'admitted',
            'secret',
            # FreshandFit specific
            'red pill',
            'alpha',
            'sigma',
            'female',
            'women',
            'dating',
            'relationship',
            'hypergamy',
            'simping',
            'simp',
            'clout',
            'onlyfans',
            'bag',
            # Strong emotion punctuation patterns handled below
        }

        # Keywords specifically indicating stupidity / contradiction / cringe
        _CRINGE_KEYWORDS = {
            'stupid',
            'dumb',
            'idiot',
            'moron',
            'delusional',
            'cope',
            'seethe',
            'mald',
            'ratio',
            'mid',
            'npc',
            'sheep',
            'clown',
            'wrong',
            'incorrect',
            'false',
            'lie',
            'lying',
            'contradiction',
            "that's not how",
            'woke',
            'triggered',
            'victim',
            'privilege',
            'literally',
            'brainwashed',
            "you don't understand",
            'actually',
            'well actually',
            'feminist',
        }

        # Pre-written narrator commentary lines — wise/sardonic voice-over
        _COMMENTARY_LINES = [
            'This man woke up and chose delusion.',
            'Nature is healing. Just kidding.',
            'And yet, he continues.',
            'The audacity is immeasurable.',
            "I've seen toasters with more self-awareness.",
            'Somewhere, a philosophy professor is weeping.',
            'This is what happens when you skip critical thinking class.',
            'Ladies and gentlemen, the future of mankind.',
            'Charles Darwin would like a word.',
            'The confidence is inversely proportional to the intelligence.',
            'Every word a mystery, every sentence a tragedy.',
            'He really said that with his whole chest.',
            "We're witnessing history, unfortunately.",
            'This argument has more holes than Swiss cheese.',
            "Bold strategy. Let's see if it pays off.",
            'Remarkable. Truly, genuinely remarkable.',
            'The man speaks. The world suffers.',
            'One day, historians will study this moment.',
            'There is no helping some people.',
            'This is the peak of human civilisation.',
        ]

        def _get_contextual_commentary(moment_txt_: str, clip_title_: str) -> str:
            """Ask GPT-4o (or Ollama qwen3.6:35b-a3b fallback) for a 1-sentence narrator reaction.
            Falls back to a static line if both fail."""
            import random as _rcnd

            if not (moment_txt_ or clip_title_):
                return _rcnd.choice(_COMMENTARY_LINES)
            _context = clip_title_ or moment_txt_[:120]
            _cprompt = (
                f'You are a sharp podcast host reacting to a viral clip. '
                f'The clip is about: "{_context}"\n'
                f'Write ONE punchy reaction sentence that a host would say to comment on or challenge what was just said. '
                f'Be direct, provocative, and powerful. No quotes, no intro, no explanation — just the reaction.'
            )
            _tok = os.environ.get('GITHUB_TOKEN', '')
            # Try GPT-4o first if token available
            if _tok:
                try:
                    _cdata = http_json.post_json(
                        'https://models.inference.ai.azure.com/chat/completions',
                        {
                            'model': 'gpt-4o',
                            'messages': [{'role': 'user', 'content': _cprompt}],
                            'max_tokens': 100,
                            'temperature': 0.9,
                        },
                        headers={'Authorization': f'Bearer {_tok}'},
                        timeout=15,
                    )
                    _line = _cdata['choices'][0]['message']['content'].strip().strip('"').strip("'")
                    if _line:
                        return _line
                except Exception as _ce:
                    _log_warn(f'GPT-4o contextual narrator failed ({_ce}) — trying Ollama fallback')
            # Ollama qwen3.6:35b-a3b fallback
            try:
                _odata = http_json.post_json(
                    _OLLAMA_BASE_URL + '/api/chat',
                    {
                        'model': 'qwen3.6:35b-a3b',
                        'messages': [{'role': 'user', 'content': _cprompt}],
                        'stream': False,
                    },
                    timeout=60,
                )
                _line = _odata.get('message', {}).get('content', '').strip().strip('"').strip("'")
                if _line:
                    return _line
            except Exception as _oe:
                _log_warn(f'Ollama narrator fallback failed ({_oe}) — using static line')
            return _rcnd.choice(_COMMENTARY_LINES)

        return _VIRAL_KEYWORDS, _CRINGE_KEYWORDS, _get_contextual_commentary
