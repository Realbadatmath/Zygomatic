#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Fix index.json to include 'goal' and 'backstory' for each agent.
"""

import json
import os

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def update_index_json():
    index_path = os.path.join('agents', 'index.json')
    with open(index_path, 'r', encoding='utf-8') as f:
        index_data = json.load(f)

    updated = False
    for overseer, agents in index_data.get('agents_by_overseer', {}).items():
        for agent in agents:
            agent_file = agent.get('file')
            if not agent_file:
                continue
            # Try to find the agent file in the correct directory
            agent_dir = index_data.get('overseers', {}).get(overseer, {}).get('directory')
            if not agent_dir:
                continue
            agent_path = os.path.join(agent_dir, agent_file)
            if not os.path.exists(agent_path):
                continue
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
            except Exception as e:
                _zyg_log.info(f'Error reading {agent_path}: {e}')
    if updated:
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, indent=2, ensure_ascii=False)
        _zyg_log.info('✅ index.json updated with goal and backstory fields.')
    else:
        _zyg_log.info('No updates needed. All fields already present.')


if __name__ == '__main__':
    update_index_json()
