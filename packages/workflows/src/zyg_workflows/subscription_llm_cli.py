# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.subscription_llm`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.subscription_llm` still reaches it.
"""

import json
import sys

from zyg_workflows.subscription_llm import run_turn


def main() -> int:
    """One live turn on the login — was `python3 subscription_llm.py "prompt"`."""
    prompt = ' '.join(sys.argv[1:]) or 'Reply with the single word OK.'
    r = run_turn([{'role': 'user', 'content': prompt}], max_tokens=200, stage='cli-probe')
    print(
        json.dumps(
            {
                'model': r.model,
                'text': r.content[0].text,
                'in': r.usage.input_tokens,
                'out': r.usage.output_tokens,
                'cache_read': r.usage.cache_read_input_tokens,
                'cache_write': r.usage.cache_creation_input_tokens,
                'cli_cost_usd': r.total_cost_usd,
                'turns': r.num_turns,
                'session': r.session_id,
            },
            indent=1,
        )
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
