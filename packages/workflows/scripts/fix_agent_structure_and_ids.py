#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Fix Agent Structure and Assign Unique IDs
This script will:
1. Assign unique 3-6 digit ID codes to all 105 agents
2. Ensure proper AI model mappings for each agent
3. Update agent configurations and model mappings
4. Organize agents by department and tier
"""

import json
import random
import os
from typing import Dict, List, Set

# AI Models available for different tiers
AI_MODELS = {
    'Executive': ['Claude 3', 'Llama 3', 'Crewai Openagents', 'GPT-4'],
    'Management': ['Claude 3', 'Llama 3', 'Crewai Openagents'],
    'Specialist': ['Claude 3', 'Llama 3'],
    'Support': ['Claude 3', 'Llama 3'],
}

# Department mappings
DEPARTMENTS = {
    'CEO-Agent': 'Executive',
    'CTO-Agent': 'Executive',
    'Affiliate-Marketing-Overseer': 'Marketing',
    'Animation-Media-Overseer': 'Animation',
    'Business-Support-Overseer': 'Support',
    'Content-Production-Overseer': 'Production',
    'Adult-NSFW-Overseer': 'Adult',
}

# Tier mappings based on agent type
TIER_MAPPINGS = {'Overseer': 'Management', 'Agent': 'Specialist', 'Master': 'Management'}


def generate_unique_id(existing_ids: Set[str]) -> str:
    """Generate a unique 3-6 digit ID code"""
    while True:
        # Generate 3-6 digit number
        length = random.randint(3, 6)
        new_id = str(random.randint(10 ** (length - 1), 10**length - 1))
        if new_id not in existing_ids:
            return new_id


def get_agent_tier(agent_name: str) -> str:
    """Determine agent tier based on name"""
    if 'Overseer' in agent_name:
        return 'Management'
    elif 'Master' in agent_name:
        return 'Management'
    elif 'CEO' in agent_name or 'CTO' in agent_name:
        return 'Executive'
    else:
        return 'Specialist'


def get_agent_department(agent_name: str) -> str:
    """Determine agent department based on name"""
    if 'CEO' in agent_name:
        return 'Executive'
    elif 'CTO' in agent_name:
        return 'Technology'
    elif 'Marketing' in agent_name or 'Affiliate' in agent_name:
        return 'Marketing'
    elif 'Animation' in agent_name or '2D' in agent_name or '3D' in agent_name:
        return 'Animation'
    elif 'Business' in agent_name or 'Support' in agent_name:
        return 'Support'
    elif 'Content' in agent_name or 'Production' in agent_name or 'YouTube' in agent_name:
        return 'Production'
    elif 'Adult' in agent_name or 'NSFW' in agent_name:
        return 'Adult'
    elif 'Localization' in agent_name or 'Voice' in agent_name:
        return 'Localization'
    else:
        return 'General'


def get_ai_models_for_agent(agent_name: str, tier: str) -> List[str]:
    """Get appropriate AI models for an agent based on tier and specialization"""
    base_models = AI_MODELS.get(tier, AI_MODELS['Specialist'])

    # Add specialized models based on agent type
    if 'Animation' in agent_name or '2D' in agent_name or '3D' in agent_name:
        base_models.extend(['Stable Diffusion', 'Midjourney'])
    elif 'Voice' in agent_name or 'Audio' in agent_name:
        base_models.extend(['ElevenLabs', 'Whisper'])
    elif 'Video' in agent_name or 'Editor' in agent_name:
        base_models.extend(['Runway', 'Pika Labs'])
    elif 'SEO' in agent_name or 'Analytics' in agent_name:
        base_models.extend(['Google Analytics', 'SEMrush'])

    return list(set(base_models))  # Remove duplicates


def create_agent_config(agent_name: str, agent_id: str, role: str, tier: str, department: str) -> Dict:
    """Create a complete agent configuration"""
    ai_models = get_ai_models_for_agent(agent_name, tier)

    return {
        'name': agent_name,
        'role': role,
        'goal': f'Execute {role.lower()} tasks efficiently and contribute to overall project success',
        'backstory': f'Specialized agent with expertise in {role.lower()}. Skilled at performing assigned tasks and collaborating with other agents.',
        'tier': tier,
        'department': department,
        'ai_models': ai_models,
        'capabilities': get_capabilities_for_agent(agent_name),
        'status': 'active',
        'id': agent_id,
    }


def get_capabilities_for_agent(agent_name: str) -> List[str]:
    """Get capabilities for an agent based on their specialization"""
    capabilities = ['Task Execution', 'Collaboration']

    if 'Marketing' in agent_name:
        capabilities.extend(['Marketing', 'Campaign Management'])
    elif 'Animation' in agent_name or '2D' in agent_name or '3D' in agent_name:
        capabilities.extend(['Animation', 'Design', 'Creative'])
    elif 'Video' in agent_name or 'Editor' in agent_name:
        capabilities.extend(['Video Editing', 'Post-Production'])
    elif 'Voice' in agent_name or 'Audio' in agent_name:
        capabilities.extend(['Audio Processing', 'Voice Generation'])
    elif 'SEO' in agent_name or 'Analytics' in agent_name:
        capabilities.extend(['Analytics', 'SEO', 'Data Analysis'])
    elif 'Support' in agent_name or 'Customer' in agent_name:
        capabilities.extend(['Customer Support', 'Problem Solving'])
    elif 'Financial' in agent_name or 'Legal' in agent_name:
        capabilities.extend(['Financial Analysis', 'Legal Compliance'])
    elif 'Localization' in agent_name:
        capabilities.extend(['Translation', 'Localization'])

    return list(set(capabilities))


def create_model_bar_mapping(agent_name: str, agent_id: str, ai_models: List[str], tier: str) -> Dict:
    """Create model bar mapping for an agent"""
    models = []
    for model in ai_models:
        models.append({'model': model, 'bar_id': f'{agent_name}__{model}'})

    return {'agent_id': agent_id, 'models': models, 'tier': tier}


def main():
    print('Starting agent structure fix and ID assignment...')

    # Load existing configurations
    config_file = 'agent_configurations.json'
    mapping_file = 'agent_model_bar_mapping.json'

    existing_configs = {}

    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            existing_configs = json.load(f)

    # Get all agent names from FULL_TASK_SPECIFICATIONS
    with open('FULL_TASK_SPECIFICATIONS.json', 'r') as f:
        full_specs = json.load(f)

    all_agents = list(full_specs['agents'].keys())

    # Add overseer agents
    overseers = [
        'Affiliate-Marketing-Overseer',
        'Animation-Media-Overseer',
        'Business-Support-Overseer',
        'Content-Production-Overseer',
        'Adult-NSFW-Overseer',
    ]

    # Add CEO and CTO agents
    executives = ['CEO-Agent', 'CTO-Agent']

    all_agents.extend(overseers)
    all_agents.extend(executives)

    print(f'Found {len(all_agents)} agents to process')

    # Generate unique IDs
    existing_ids = set()
    if existing_configs.get('agents'):
        for agent_config in existing_configs['agents'].values():
            if 'id' in agent_config:
                existing_ids.add(agent_config['id'])

    # Create new configurations
    new_configs = {'agents': {}}
    new_mappings = {}

    for agent_name in all_agents:
        # Generate unique ID
        agent_id = generate_unique_id(existing_ids)
        existing_ids.add(agent_id)

        # Get agent details from specs or create defaults
        agent_spec = full_specs['agents'].get(agent_name, {})
        role = agent_spec.get('role', f'{agent_name.replace("-", " ")}')

        # Determine tier and department
        tier = get_agent_tier(agent_name)
        department = get_agent_department(agent_name)

        # Create configuration
        agent_config = create_agent_config(agent_name, agent_id, role, tier, department)
        new_configs['agents'][agent_name] = agent_config

        # Create model mapping
        ai_models = get_ai_models_for_agent(agent_name, tier)
        model_mapping = create_model_bar_mapping(agent_name, agent_id, ai_models, tier)
        new_mappings[agent_name] = model_mapping

        print(f'Processed {agent_name} - ID: {agent_id} - Tier: {tier} - Department: {department}')

    # Save new configurations
    with open(config_file, 'w') as f:
        json.dump(new_configs, f, indent=2)

    with open(mapping_file, 'w') as f:
        json.dump(new_mappings, f, indent=2)

    print(f'\nSuccessfully processed {len(all_agents)} agents')
    print(f'Updated {config_file}')
    print(f'Updated {mapping_file}')

    # Create summary
    print('\nAgent Summary:')
    tier_counts = {}
    dept_counts = {}

    for agent_config in new_configs['agents'].values():
        tier = agent_config['tier']
        dept = agent_config['department']

        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        dept_counts[dept] = dept_counts.get(dept, 0) + 1

    print('\nBy Tier:')
    for tier, count in tier_counts.items():
        print(f'  {tier}: {count} agents')

    print('\nBy Department:')
    for dept, count in dept_counts.items():
        print(f'  {dept}: {count} agents')


if __name__ == '__main__':
    main()
