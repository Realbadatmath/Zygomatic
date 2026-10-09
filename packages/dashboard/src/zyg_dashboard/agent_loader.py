#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Agent Loader Script
Loads individual agent files from the agents directory structure
"""

import json
from pathlib import Path
from typing import Dict, List, Any


class AgentLoader:
    def __init__(self, agents_dir: str = 'agents'):
        self.agents_dir = Path(agents_dir)
        self.agents_cache = {}
        self.index_data = None

    def load_index(self) -> Dict[str, Any]:
        """Load the index file"""
        index_path = self.agents_dir / 'index.json'
        if not index_path.exists():
            raise FileNotFoundError(f'Index file not found: {index_path}')

        with open(index_path, 'r', encoding='utf-8') as f:
            self.index_data = json.load(f)
        return self.index_data

    def load_agent(self, overseer: str, agent_name: str) -> Dict[str, Any]:
        """Load a specific agent by overseer and name"""
        cache_key = f'{overseer}/{agent_name}'

        if cache_key in self.agents_cache:
            return self.agents_cache[cache_key]

        agent_path = self.agents_dir / overseer / f'{agent_name}.json'
        if not agent_path.exists():
            raise FileNotFoundError(f'Agent file not found: {agent_path}')

        with open(agent_path, 'r', encoding='utf-8') as f:
            agent_data = json.load(f)

        self.agents_cache[cache_key] = agent_data
        return agent_data

    def load_overseer_agents(self, overseer: str) -> List[Dict[str, Any]]:
        """Load all agents for a specific overseer"""
        if not self.index_data:
            self.load_index()

        if overseer not in self.index_data['agents_by_overseer']:
            raise ValueError(f'Overseer not found: {overseer}')

        agents = []
        for agent_info in self.index_data['agents_by_overseer'][overseer]:
            agent_data = self.load_agent(overseer, agent_info['name'])
            agents.append(agent_data)

        return agents

    def load_all_agents(self) -> Dict[str, List[Dict[str, Any]]]:
        """Load all agents organized by overseer"""
        if not self.index_data:
            self.load_index()

        all_agents = {}
        for overseer in self.index_data['agents_by_overseer']:
            all_agents[overseer] = self.load_overseer_agents(overseer)

        return all_agents

    def get_agent_by_role(self, role: str) -> Dict[str, Any]:
        """Find an agent by role across all overseers"""
        if not self.index_data:
            self.load_index()

        for overseer in self.index_data['agents_by_overseer']:
            for agent_info in self.index_data['agents_by_overseer'][overseer]:
                if agent_info['role'].lower() == role.lower():
                    return self.load_agent(overseer, agent_info['name'])

        raise ValueError(f"Agent with role '{role}' not found")

    def get_agents_by_tier(self, tier: str) -> List[Dict[str, Any]]:
        """Get all agents of a specific tier"""
        if not self.index_data:
            self.load_index()

        tier_agents = []
        for overseer in self.index_data['agents_by_overseer']:
            for agent_info in self.index_data['agents_by_overseer'][overseer]:
                if agent_info['tier'].lower() == tier.lower():
                    agent_data = self.load_agent(overseer, agent_info['name'])
                    tier_agents.append(agent_data)

        return tier_agents


# Example usage
if __name__ == '__main__':
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
