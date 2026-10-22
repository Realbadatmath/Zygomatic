# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.kids_llm`, moved out of the library module so that library code
never prints; `python -m zyg_workflows.kids_llm` still reaches it.
"""

import json
import sys

from zyg_workflows.kids_llm import (
    OLLAMA_MODEL,
    OPUS_MODEL,
    ask_json,
    opus_available,
    opus_on,
)


def main() -> int:
    """One live probe per backend — what used to run under `if __name__` in kids_llm."""
    print(
        json.dumps(
            {
                'backend': 'subscription' if opus_on() else 'ollama',
                'opus_available': opus_available(),
                'opus_model': OPUS_MODEL,
                'ollama_model': OLLAMA_MODEL,
            },
            indent=1,
        )
    )
    d, i = ask_json(
        opus_prompt='Reply with JSON only: {"ok": true, "who": "<the model name>"}',
        ollama_prompt='Reply with JSON only: {"ok": true, "who": "<the model name>"}',
        system='You answer with one JSON object and nothing else.',
        stage='kids_llm_probe',
        max_tokens=200,
        log_fn=lambda m: print('·', m),
    )
    print(json.dumps({'data': d, 'info': i}, indent=1, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
