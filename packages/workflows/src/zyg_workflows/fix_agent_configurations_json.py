#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Fix agent_configurations.json to include 'goal' and 'backstory' for each agent.
"""

import json
import os

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def update_agent_configurations_json():
    config_path = 'agent_configurations.json'
    with open(config_path, 'r', encoding='utf-8') as f:
        config_data = json.load(f)

    updated = False
    for agent_name, agent in config_data.get('agents', {}).items():
        # Try to find the agent file in the agents directory tree
        found = False
        for root, _dirs, files in os.walk('agents'):
            for file in files:
                if file == f'{agent_name}.json':
                    agent_path = os.path.join(root, file)
                    try:
                        with open(agent_path, 'r', encoding='utf-8') as af:
                            agent_config = json.load(af)
                        # Copy over fields
                        for field in [
                            'goal',
                            'backstory',
                            'department',
                            'tier',
                            'supervisor',
                            'subordinates',
                            'ai_models',
                            'gpu_schedule',
                            'tools',
                            'skills',
                            'max_concurrent_tasks',
                            'current_tasks',
                            'primary_task',
                        ]:
                            if field in agent_config:
                                agent[field] = agent_config[field]
                        updated = True
                        found = True
                        break
                    except Exception as e:
                        _zyg_log.info(f'Error reading {agent_path}: {e}')
            if found:
                break
        if not found:
            _zyg_log.info(f'Warning: Could not find JSON file for agent {agent_name}')
    if updated:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
        _zyg_log.info('✅ agent_configurations.json updated with goal and backstory fields.')
    else:
        _zyg_log.info('No updates needed. All fields already present or no agent files found.')


if __name__ == '__main__':
    update_agent_configurations_json()
