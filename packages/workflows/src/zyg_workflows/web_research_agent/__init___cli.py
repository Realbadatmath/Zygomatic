# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.web_research_agent.__init__`, moved out of the library
module so that library code never prints; `python -m zyg_workflows.web_research_agent`
still reaches it.
"""

import sys

from zyg_workflows.web_research_agent import WebResearchAgent


def main() -> int:
    """The standalone test that used to live under `if __name__ == '__main__'` in the package."""
    name = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else 'Ted Bundy'
    case = {
        'name': name,
        'case_title': f'{name} Trial',
        'state': 'Unknown',
        'year': '?',
        'court': 'Unknown',
        'crime_category': 'Serial Murder',
        'summary': '',
        'why_narrate': '',
    }

    def _print_log(level, stage, msg):
        print(f'[{level}] {stage}: {msg}')

    agent = WebResearchAgent(case=case, pipeline_id='test', log_fn=_print_log)
    result = agent.run()
    print('\n\n=== RESULT ===')
    print(f'Sources: {result["sources_used"]}')
    print(f'Total chars: {result["total_chars"]}')
    print(f'Timeline entries: {len(result["timeline"])}')
    print(f'Key people: {result["key_people"]}')
    print(f'\nFirst 2000 chars of raw_text:\n{result["raw_text"][:2000]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
