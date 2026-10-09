#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Agent ID Assignment Script
Assigns unique IDs to all agents and updates their JSON files and index
"""

import json
import uuid
from pathlib import Path
from typing import Dict, Any

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


class AgentIDAssigner:
    def __init__(self, agents_dir: str = 'agents'):
        self.agents_dir = Path(agents_dir)
        self.index_path = self.agents_dir / 'index.json'
        self.assigned_ids = set()

    def generate_unique_id(self) -> str:
        """Generate a unique ID that hasn't been used yet"""
        while True:
            agent_id = str(uuid.uuid4())
            if agent_id not in self.assigned_ids:
                self.assigned_ids.add(agent_id)
                return agent_id

    def load_index(self) -> Dict[str, Any]:
        """Load the current index file"""
        if not self.index_path.exists():
            raise FileNotFoundError(f'Index file not found: {self.index_path}')

        with open(self.index_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def save_index(self, index_data: Dict[str, Any]):
        """Save the updated index file"""
        with open(self.index_path, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, indent=2, ensure_ascii=False)

    def update_agent_file(self, overseer: str, agent_name: str, agent_id: str):
        """Update an agent's JSON file with the new ID"""
        agent_path = self.agents_dir / overseer / f'{agent_name}.json'

        if not agent_path.exists():
            _zyg_log.info(f'Warning: Agent file not found: {agent_path}')
            return

        with open(agent_path, 'r', encoding='utf-8') as f:
            agent_data = json.load(f)

        # Add the ID to the agent data
        agent_data['id'] = agent_id

        # Save the updated agent file
        with open(agent_path, 'w', encoding='utf-8') as f:
            json.dump(agent_data, f, indent=2, ensure_ascii=False)

        _zyg_log.info(f'Updated {overseer}/{agent_name} with ID: {agent_id}')

    def assign_ids_to_all_agents(self):
        """Assign unique IDs to all agents and update index"""
        _zyg_log.info('Loading current index...')
        index_data = self.load_index()

        _zyg_log.info('Assigning unique IDs to all agents...')
        total_assigned = 0

        # Process each overseer
        for overseer, agents in index_data['agents_by_overseer'].items():
            _zyg_log.info(f'\nProcessing {overseer} ({len(agents)} agents)...')

            for agent_info in agents:
                agent_name = agent_info['name']

                # Generate unique ID
                agent_id = self.generate_unique_id()

                # Update agent file
                self.update_agent_file(overseer, agent_name, agent_id)

                # Update index entry
                agent_info['id'] = agent_id

                total_assigned += 1

        # Update metadata
        index_data['metadata']['total_agents_with_ids'] = total_assigned
        index_data['metadata']['id_assignment_date'] = str(Path().cwd())

        # Save updated index
        _zyg_log.info(f'\nSaving updated index with {total_assigned} agent IDs...')
        self.save_index(index_data)

        _zyg_log.info(f'✅ Successfully assigned IDs to {total_assigned} agents!')
        return index_data


def main():
    assigner = AgentIDAssigner()

    try:
        updated_index = assigner.assign_ids_to_all_agents()
        print('\nSummary:')
        print(f'- Total agents processed: {updated_index["metadata"]["total_agents_with_ids"]}')
        print(f'- Index file updated: {assigner.index_path}')

    except Exception as e:
        print(f'Error: {e}')
        return 1

    return 0


if __name__ == '__main__':
    exit(main())
