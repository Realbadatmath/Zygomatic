#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Agent Configuration System for CrewAI
Defines all 79 agents with their roles, goals, and capabilities
"""

from typing import Dict, List, Optional

from zyg_dashboard.agent_config_catalog import DEPARTMENT_BUILDERS as DEPARTMENT_BUILDERS
from zyg_dashboard.agent_config_catalog import AgentConfig as AgentConfig
from zyg_dashboard.agent_config_catalog import AgentTier as AgentTier
from zyg_dashboard.agent_config_catalog import GPUSchedule as GPUSchedule
from zyg_dashboard.agent_config_catalog import department_structures as department_structures


class AgentManager:
    def __init__(self):
        self.agents = {}
        self.departments = {}
        self.gpu_scheduler = GPUScheduler()
        self.load_agent_configurations()

    def load_agent_configurations(self):
        """Load all agent configurations"""
        for build in DEPARTMENT_BUILDERS:
            self.agents.update(build())

        # Initialize departments
        self._initialize_departments()

    def _initialize_departments(self):
        """Initialize department structures"""
        self.departments = department_structures()

    def get_agent(self, name: str) -> Optional[AgentConfig]:
        """Get agent configuration by name"""
        return self.agents.get(name)

    def get_tier_1_agents(self) -> List[AgentConfig]:
        """Get all tier 1 agents (GPU intensive)"""
        return [agent for agent in self.agents.values() if agent.tier == AgentTier.TIER_1]

    def get_department_agents(self, department: str) -> List[AgentConfig]:
        """Get all agents in a specific department"""
        if department not in self.departments:
            return []
        return [self.agents[name] for name in self.departments[department]['agents'] if name in self.agents]

    def get_agent_hierarchy(self) -> Dict:
        """Get the complete agent hierarchy"""
        hierarchy = {}
        for name, agent in self.agents.items():
            hierarchy[name] = {
                'name': name,
                'role': agent.role,
                'tier': agent.tier.value,
                'department': agent.department,
                'supervisor': agent.supervisor,
                'subordinates': agent.subordinates,
                'gpu_schedule': agent.gpu_schedule.__dict__ if agent.gpu_schedule else None,
            }
        return hierarchy


class GPUScheduler:
    """Manages GPU scheduling for tier 1 agents"""

    def __init__(self):
        self.schedule = {}
        self.gpu_capacity = 100  # Total GPU capacity percentage
        self.current_allocations = {}

    def allocate_gpu_time(self, agent_name: str, gpu_schedule: GPUSchedule) -> bool:
        """Allocate GPU time for an agent"""
        # Check if allocation is possible
        if self._can_allocate(agent_name, gpu_schedule):
            self.current_allocations[agent_name] = gpu_schedule
            return True
        return False

    def _can_allocate(self, agent_name: str, gpu_schedule: GPUSchedule) -> bool:
        """Check if GPU allocation is possible"""
        # Simple allocation check - in practice, this would be more sophisticated
        total_allocated = sum(schedule.max_gpu_percent for schedule in self.current_allocations.values())
        return total_allocated + gpu_schedule.max_gpu_percent <= self.gpu_capacity

    def get_optimal_schedule(self) -> Dict:
        """Generate optimal schedule for all tier 1 agents"""
        # This would implement sophisticated scheduling algorithms
        # For now, return a simple schedule
        return {
            'morning_slot': ['2D-Series-Agent', '3D-Series-Agent'],
            'afternoon_slot': ['Scene-Editor-Agent', 'Render-Agent'],
            'night_slot': ['Render-Agent'],
        }

    def release_gpu_time(self, agent_name: str):
        """Release GPU time for an agent"""
        if agent_name in self.current_allocations:
            del self.current_allocations[agent_name]


# Global agent manager instance
agent_manager = AgentManager()
