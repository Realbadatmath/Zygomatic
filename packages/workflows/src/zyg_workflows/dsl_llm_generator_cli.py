# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.dsl_llm_generator`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.dsl_llm_generator` still reaches it.
"""

import sys

from zyg_workflows.dsl_llm_generator import DSLLLMGenerator


def main() -> int:
    """The demo that used to live under `if __name__ == '__main__'` in dsl_llm_generator."""
    # Demo: show prompts
    print('=' * 70)
    print('DSL GENERATION PROMPTS')
    print('=' * 70)

    generator = DSLLLMGenerator(use_caveman=True)

    example_input = 'Deep ocean scene. Unknown creature. Sense of wonder and dread.'

    print('\nSYSTEM PROMPT (with caveman):')
    print(generator.get_system_prompt())

    print('\nUSER PROMPT (with caveman):')
    print(generator.get_generation_prompt(example_input))

    print('\n' + '=' * 70)
    print('Token savings with caveman prompts: ~30-40%')
    return 0


if __name__ == '__main__':
    sys.exit(main())
