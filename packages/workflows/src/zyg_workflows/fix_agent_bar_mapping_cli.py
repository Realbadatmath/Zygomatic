# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.fix_agent_bar_mapping`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.fix_agent_bar_mapping` still reaches it.
"""

import json
import sys

from zyg_workflows.fix_agent_bar_mapping import AgentBarMappingFixer


def main():
    """The command line that used to live in fix_agent_bar_mapping.main()."""
    fixer = AgentBarMappingFixer()

    try:
        print('🔧 Fixing agent bar mapping structure...')

        # Get agent count
        all_agents = fixer.get_all_agents()
        print(f'📊 Found {len(all_agents)} agents to process')

        # Create fixed agent bar mapping
        print('🔗 Creating fixed agent to bar mapping...')
        agent_mapping = fixer.create_fixed_agent_bar_mapping()
        fixer.save_fixed_agent_bar_mapping(agent_mapping)

        # Get tier 1 GPU agents for asset management
        tier1_gpu_agents = fixer.get_tier1_gpu_agents(agent_mapping)
        print(
            f'🎯 Tier 1 GPU agents ({len(tier1_gpu_agents)}): {", ".join(tier1_gpu_agents[:5])}{"..." if len(tier1_gpu_agents) > 5 else ""}'
        )

        # Get all GPU agents for GPU schedule
        all_gpu_agents = fixer.get_all_gpu_agents(agent_mapping)
        print(
            f'🚀 All GPU agents ({len(all_gpu_agents)}): {", ".join(all_gpu_agents[:5])}{"..." if len(all_gpu_agents) > 5 else ""}'
        )

        # Summary
        print('\n✅ Agent bar mapping fixed!')
        print('📈 Summary:')
        print(f'   - Total agents: {len(all_agents)}')
        print(f'   - Tier 1 GPU agents: {len(tier1_gpu_agents)}')
        print(f'   - All GPU agents: {len(all_gpu_agents)}')
        print(f'   - Agent bar mapping: {len(agent_mapping)} agents mapped')

        # Save tier 1 GPU agents list for asset management
        tier1_gpu_file = fixer.schedule_dir / 'tier1_gpu_agents.json'
        with open(tier1_gpu_file, 'w', encoding='utf-8') as f:
            json.dump({'tier1_gpu_agents': tier1_gpu_agents}, f, indent=2, ensure_ascii=False)
        print(f'💾 Tier 1 GPU agents list saved to {tier1_gpu_file}')

        # Save all GPU agents list for GPU schedule
        all_gpu_file = fixer.schedule_dir / 'all_gpu_agents.json'
        with open(all_gpu_file, 'w', encoding='utf-8') as f:
            json.dump({'all_gpu_agents': all_gpu_agents}, f, indent=2, ensure_ascii=False)
        print(f'💾 All GPU agents list saved to {all_gpu_file}')

    except Exception as e:
        print(f'❌ Error: {e}')
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
