#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Fix Agent Bar Mapping Script
Updates the agent bar mapping to match the frontend expectations
"""

import json
from typing import Dict, List, Any

from . import fix_agent_bar_mapping_tables as _tables

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


class AgentBarMappingFixer:
    def __init__(self, agents_dir: str = 'crewai_project/agents', schedule_dir: str = 'Schedule'):
        """Resolve the agent/schedule directories and load the static lookup tables."""
        self.agents_dir, self.schedule_dir, self.index_path = _tables.resolve_dirs(agents_dir, schedule_dir)

        # Tier mapping from string to number
        self.tier_mapping = _tables.tier_mapping()

        # GPU models that should be in GPU schedule (using names from gpu_ai_models.json)
        self.gpu_models = _tables.gpu_model_names()

        # AI Model to Agent mapping based on agent roles and capabilities
        self.agent_ai_model_mapping = _tables.agent_ai_model_mapping()

    def load_agents_index(self) -> Dict[str, Any]:
        """Load the agents index file"""
        if not self.index_path.exists():
            raise FileNotFoundError(f'Index file not found: {self.index_path}')

        with open(self.index_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def get_all_agents(self) -> List[Dict[str, Any]]:
        """Get all agents from the index"""
        index_data = self.load_agents_index()
        all_agents = []

        for overseer, agents in index_data['agents_by_overseer'].items():
            for agent_info in agents:
                agent_info['overseer'] = overseer
                all_agents.append(agent_info)

        return all_agents

    def generate_bar_id(self) -> str:
        """Generate a unique bar ID"""
        import random

        return str(random.randint(1000, 9999))

    def get_agent_tier(self, agent_name: str) -> int:
        """Get the tier number for an agent based on its name or role"""
        # Check if it's an overseer or director
        if 'Overseer' in agent_name or 'Director' in agent_name:
            return 4
        elif 'Management' in agent_name:
            return 2
        elif 'Specialist' in agent_name:
            return 1
        else:
            return 1  # Default to tier 1

    def get_agent_models(self, agent_name: str) -> List[str]:
        """Get the AI models for an agent"""
        models = []
        for model, agents in self.agent_ai_model_mapping.items():
            if agent_name in agents:
                models.append(model)

        # If no specific models found, assign to general CPU models
        if not models:
            models = ['Claude 3', 'Llama 3']

        return models

    def get_model_id(self, model_name: str, model_id_map: dict) -> str:
        """Find the model ID for a given model name (case-insensitive with normalization)"""
        # Normalize the input model name
        normalized_input = model_name.strip().lower().replace('_', ' ').replace('-', ' ')

        for mid, info in model_id_map.items():
            # Normalize the stored model name
            normalized_stored = info['name'].strip().lower().replace('_', ' ').replace('-', ' ')

            if normalized_input == normalized_stored:
                return mid

        # If no exact match, try partial matching
        for mid, info in model_id_map.items():
            normalized_stored = info['name'].strip().lower().replace('_', ' ').replace('-', ' ')
            if normalized_input in normalized_stored or normalized_stored in normalized_input:
                _zyg_log.info(f"⚠️  Partial match found: '{model_name}' -> '{info['name']}' (ID: {mid})")
                return mid

        _zyg_log.info(f"❌ No model ID found for: '{model_name}'")
        return None

    def create_fixed_agent_bar_mapping(self) -> Dict[str, Dict]:
        """Create a fixed mapping of agents to their bar IDs and models using model IDs"""
        # Load agent configurations
        config_path = 'crewai_project/agent_configurations.json'
        with open(config_path, 'r', encoding='utf-8') as f:
            agent_configs = json.load(f)
        agent_mapping = {}
        # Load model ID map
        with open('crewai_project/gpu_ai_models.json', 'r', encoding='utf-8') as f:
            model_id_map = json.load(f)
        debug_agents = []
        for agent_name, agent_data in agent_configs['agents'].items():
            agent_id = agent_data.get('id', '')
            # Normalize tier: 1 for Tier 1/Specialist, 4 for Management/Overseer, else 2
            tier_raw = agent_data.get('tier', 1)
            if isinstance(tier_raw, int):
                tier = tier_raw
            elif isinstance(tier_raw, str):
                t = tier_raw.lower()
                if t in ['1', 'tier 1', 'specialist']:
                    tier = 1
                elif t in ['4', 'tier 4', 'management', 'overseer']:
                    tier = 4
                else:
                    tier = 2
            else:
                tier = 2
            ai_models = agent_data.get('ai_models', [])  # These should be model IDs
            model_objects = []
            for model_id in ai_models:
                # Only use model IDs that exist in the model_id_map
                if model_id in model_id_map:
                    model_objects.append({'model': model_id, 'bar_id': self.generate_bar_id()})
                else:
                    _zyg_log.info(f'⚠️  Model ID {model_id} not found in model map for agent {agent_name}')
            agent_mapping[agent_name] = {'agent_id': agent_id, 'tier': tier, 'models': model_objects}
            debug_agents.append((agent_name, [m['model'] for m in model_objects]))
        # Debug print for first 5 agents
        _zyg_log.info('[DEBUG] First 5 agents and their model IDs:')
        for name, models in debug_agents[:5]:
            _zyg_log.info(f'  {name}: {models} (types: {[type(m) for m in models]})')
        return agent_mapping

    def save_fixed_agent_bar_mapping(self, mapping: Dict[str, Dict]):
        """Save the fixed agent to bar mapping"""
        mapping_file = self.schedule_dir / 'agent_bar_mapping.json'
        with open(mapping_file, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, indent=2, ensure_ascii=False)
        _zyg_log.info(f'✅ Fixed agent bar mapping saved to {mapping_file}')

    def get_tier1_gpu_agents(self, mapping: Dict[str, Dict]) -> List[str]:
        """Get all tier 1 agents that use GPU models"""
        tier1_gpu_agents = []

        # Get GPU model IDs from the model map
        with open('crewai_project/gpu_ai_models.json', 'r', encoding='utf-8') as f:
            model_id_map = json.load(f)

        # Create a set of GPU model IDs (models that are typically GPU-based)
        gpu_model_ids = set()
        for mid, info in model_id_map.items():
            model_name = info.get('name', '').lower()
            # GPU models are typically image/video/audio processing models
            if any(
                gpu_keyword in model_name
                for gpu_keyword in [
                    'stable diffusion',
                    'dreamshaper',
                    'animatediff',
                    'stable video',
                    'controlnet',
                    'realesrgan',
                    'bark',
                    'tortoise',
                    'blender',
                    'kandinsky',
                    'deforum',
                    'comfyui',
                    'dreambooth',
                    'vae',
                    'lora',
                    'davinci resolve',
                    'ffmpeg',
                    'pydub',
                    'clip',
                ]
            ):
                gpu_model_ids.add(mid)

        for agent_name, agent_data in mapping.items():
            if agent_data.get('tier') == 1:  # Check for integer tier 1
                # Check if any of the agent's models are GPU models
                models = [model_obj['model'] for model_obj in agent_data.get('models', [])]
                if any(model in gpu_model_ids for model in models):
                    tier1_gpu_agents.append(agent_name)

        return tier1_gpu_agents

    def get_all_gpu_agents(self, mapping: Dict[str, Dict]) -> List[str]:
        """Get all agents that use GPU models"""
        gpu_agents = []

        # Get GPU model IDs from the model map
        with open('crewai_project/gpu_ai_models.json', 'r', encoding='utf-8') as f:
            model_id_map = json.load(f)

        # Create a set of GPU model IDs (models that are typically GPU-based)
        gpu_model_ids = set()
        for mid, info in model_id_map.items():
            model_name = info.get('name', '').lower()
            # GPU models are typically image/video/audio processing models
            if any(
                gpu_keyword in model_name
                for gpu_keyword in [
                    'stable diffusion',
                    'dreamshaper',
                    'animatediff',
                    'stable video',
                    'controlnet',
                    'realesrgan',
                    'bark',
                    'tortoise',
                    'blender',
                    'kandinsky',
                    'deforum',
                    'comfyui',
                    'dreambooth',
                    'vae',
                    'lora',
                    'davinci resolve',
                    'ffmpeg',
                    'pydub',
                    'clip',
                ]
            ):
                gpu_model_ids.add(mid)

        for agent_name, agent_data in mapping.items():
            models = [model_obj['model'] for model_obj in agent_data.get('models', [])]
            if any(model in gpu_model_ids for model in models):
                gpu_agents.append(agent_name)

        return gpu_agents


if __name__ == '__main__':  # the CLI lives in fix_agent_bar_mapping_cli
    from zyg_workflows.fix_agent_bar_mapping_cli import main as _cli_main

    raise SystemExit(_cli_main())
