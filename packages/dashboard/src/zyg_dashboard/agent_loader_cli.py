# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.agent_loader`, moved out of the library module so that library code never prints; `python -m zyg_dashboard.agent_loader` still reaches it."""

import sys

from zyg_dashboard.agent_loader import AgentLoader


def main() -> int:
    """The example usage that used to live under `if __name__ == '__main__'` in agent_loader."""
    loader = AgentLoader()

    try:
        # Load index
        index = loader.load_index()
        print(f'Loaded {index["metadata"]["total_agents"]} agents')

        # Example: Load a specific agent
        ceo_agent = loader.load_agent('CEO-Agent', 'CEO-Agent')
        print(f'CEO Agent role: {ceo_agent["role"]}')

        # Example: Load all agents for an overseer
        cto_agents = loader.load_overseer_agents('CTO-Agent')
        print(f'CTO-Agent has {len(cto_agents)} agents')

    except Exception as e:
        print(f'Error: {e}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
