#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Update Agent Models Script
Updates agent_configurations.json to include model IDs in ai_models arrays
"""

import json
import os
from typing import Dict, List

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def load_model_ids():
    """Load the model ID mapping"""
    with open(os.path.join('crewai_project', 'gpu_ai_models.json'), 'r', encoding='utf-8') as f:
        return json.load(f)


def get_model_id_by_name(model_name: str, model_ids: Dict) -> str:
    """Get model ID by name (case-insensitive)"""
    normalized_name = model_name.strip().lower().replace('_', ' ').replace('-', ' ')
    for mid, info in model_ids.items():
        normalized_stored = info['name'].strip().lower().replace('_', ' ').replace('-', ' ')
        if normalized_name == normalized_stored:
            return mid
    return None


def get_agent_models(agent_name: str, tier: int, role: str) -> List[str]:
    """Determine which models an agent should have based on their role and tier"""
    # Base models for all agents
    base_models = ['1030', '1018']  # Claude 3, Llama 3
    models = set(base_models)

    # Tier-specific models
    if tier == 4:  # Management/Overseer
        models.add('1021')  # Crewai Openagents

    # Role-specific models
    role_lower = role.lower()

    # Animation/Visual models
    if any(
        keyword in role_lower
        for keyword in [
            'animation',
            'character',
            'background',
            'modeling',
            'texturing',
            'rendering',
            'visual',
            'design',
        ]
    ):
        models.update(['1001', '1002', '1005', '1013'])  # Stable Diffusion, Dreamshaper, Controlnet, Dreambooth

    # Video models
    if any(keyword in role_lower for keyword in ['video', 'series', 'animation', 'compositor']):
        models.update(['1004', '1003'])  # Stable Video Diffusion, Animatediff

    # Voice/Audio models
    if any(keyword in role_lower for keyword in ['voice', 'audio', 'sound', 'tts', 'synthesis']):
        models.update(['1007', '1008'])  # Bark, Tortoise TTS

    # Analytics/Reporting models
    if any(keyword in role_lower for keyword in ['analytics', 'reporting', 'performance', 'financial']):
        models.add('1023')  # Plotly

    # Scheduling/Workflow models
    if any(keyword in role_lower for keyword in ['scheduler', 'scheduling', 'workflow', 'task']):
        models.add('1033')  # Airflow

    # Quality Control models
    if any(keyword in role_lower for keyword in ['quality', 'qc', 'control', 'review']):
        models.add('1020')  # HumanEval

    # API/Backend models
    if any(keyword in role_lower for keyword in ['api', 'backend', 'service']):
        models.add('1024')  # Fastapi

    # If only base models, print debug
    if models == set(base_models):
        _zyg_log.info(f'[DEBUG] {agent_name} assigned only base models (no role/tier match)')
    return list(models)


def update_agent_configurations():
    """Update agent_configurations.json with model IDs"""
    config_path = os.path.join('crewai_project', 'agent_configurations.json')
    # Load current configurations
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    # Update each agent
    updated_count = 0
    for agent_name, agent_data in config['agents'].items():
        tier = agent_data.get('tier', 1)
        role = agent_data.get('role', '')

        # Get appropriate models for this agent
        model_ids_for_agent = get_agent_models(agent_name, tier, role)

        # Update the agent's ai_models
        agent_data['ai_models'] = model_ids_for_agent
        updated_count += 1

        _zyg_log.info(f'Updated {agent_name}: {len(model_ids_for_agent)} models')

    # Save updated configurations
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    _zyg_log.info(f'\n✅ Updated {updated_count} agents with model IDs')
    _zyg_log.info(f'📁 Saved to {config_path}')

    return config


if __name__ == '__main__':
    update_agent_configurations()
