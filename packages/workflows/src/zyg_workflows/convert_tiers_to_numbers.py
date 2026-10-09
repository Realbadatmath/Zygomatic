#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Convert string tier values to numeric values in agent_bar_mapping.json
"""

import json

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def convert_tiers_to_numbers():
    """Convert string tier values to numeric values"""

    # Tier mapping
    tier_mapping = {'Specialist': 1, 'Management': 2, 'Director': 3, 'Overseer': 4, 'Executive': 5}

    # Load the mapping file
    mapping_path = 'Schedule/agent_bar_mapping.json'
    with open(mapping_path, 'r', encoding='utf-8') as f:
        mapping = json.load(f)

    # Convert tiers
    converted_count = 0
    for agent_name, agent_data in mapping.items():
        old_tier = agent_data.get('tier')
        if isinstance(old_tier, str):
            new_tier = tier_mapping.get(old_tier, 1)  # Default to 1 if not found
            agent_data['tier'] = new_tier
            converted_count += 1
            _zyg_log.info(f"Converted {agent_name}: '{old_tier}' -> {new_tier}")

    # Save the updated mapping
    with open(mapping_path, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)

    _zyg_log.info(f'\n✅ Converted {converted_count} agents to numeric tiers')
    _zyg_log.info(f'📁 Updated file: {mapping_path}')

    # Verify the conversion
    with open(mapping_path, 'r', encoding='utf-8') as f:
        mapping = json.load(f)

    first_agent = list(mapping.values())[0]
    _zyg_log.info(f'🔍 Verification - First agent tier: {first_agent["tier"]} (type: {type(first_agent["tier"])})')


if __name__ == '__main__':
    convert_tiers_to_numbers()
