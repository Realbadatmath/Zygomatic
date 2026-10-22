#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Create New Agent Mappings
This script will:
1. Create individual JSON files for each agent in the provided list
2. Assign unique 3-6 digit ID codes
3. Use hybrid format with tasks, roles, AI models, etc.
4. Organize by tier (Executive/Management/Specialist)
5. Replace all existing agent data
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

# Agent list provided by user
AGENT_LIST = [
    'Localization-Master-Agent',
    'Cultural-Adaptation-Master-Agent',
    'Voice-Localization-Master-Agent',
    'English-Localization-Agent',
    'Mandarin-Localization-Agent',
    'Hindi-Localization-Agent',
    'Spanish-Localization-Agent',
    'French-Localization-Agent',
    'Arabic-Localization-Agent',
    'Bengali-Localization-Agent',
    'Portuguese-Localization-Agent',
    'English-Voice-Agent',
    'Mandarin-Voice-Agent',
    'Hindi-Voice-Agent',
    'Spanish-Voice-Agent',
    'French-Voice-Agent',
    'Arabic-Voice-Agent',
    'Bengali-Voice-Agent',
    'Portuguese-Voice-Agent',
    'English-Marketing-Agent',
    'Mandarin-Marketing-Agent',
    'Hindi-Marketing-Agent',
    'Spanish-Marketing-Agent',
    'French-Marketing-Agent',
    'Arabic-Marketing-Agent',
    'Bengali-Marketing-Agent',
    'Portuguese-Marketing-Agent',
    'Multi-Language-QC-Agent',
    'Affiliate-Marketing-Overseer',
    'Affiliate-Marketing-Agent',
    'Campaign-Builder-Agent',
    'SEO-Agent',
    'Conversion-Optimizer-Agent',
    'Content-Writer-Agent',
    'Email-Marketing-Agent',
    'PPC-Agent',
    'Social-Media-Marketing-Agent',
    'Analytics-Reporting-Agent',
    'Audience-Targeting-Agent',
    'Revenue-Optimization-Agent',
    'YouTube-Content-Overseer',
    'YouTube-Script-Agent',
    'YouTube-Thumbnail-Agent',
    'YouTube-Video-Editor-Agent',
    'YouTube-Audio-Agent',
    'YouTube-SEO-Agent',
    'YouTube-Analytics-Agent',
    'YouTube-Community-Agent',
    'YouTube-Scheduling-Agent',
    'YouTube-Trend-Analyst-Agent',
    '3D-Series-Overseer',
    '3D-Series-Agent',
    '3D-Modeling-Agent',
    '3D-Rendering-Agent',
    '3D-Animation-Agent',
    '3D-Environment-Agent',
    '3D-Effects-Agent',
    '3D-Rigging-Agent',
    '3D-Texturing-Agent',
    '3D-Lighting-Agent',
    '3D-Compositor-Agent',
    '3D-Storyboard-Agent',
    '3D-Script-Agent',
    '3D-Character-Designer-Agent',
    '3D-Voice-Agent',
    '3D-Music-Agent',
    '3D-Quality-Control-Agent',
    '3D-Scheduling-Agent',
    '3D-Asset-Manager-Agent',
    '3D-Render-Farm-Manager-Agent',
    '2D-Series-Overseer',
    '2D-Series-Agent',
    '2D-Character-Designer-Agent',
    '2D-Background-Artist-Agent',
    '2D-Animation-Agent',
    '2D-Storyboard-Agent',
    '2D-Script-Agent',
    '2D-Voice-Agent',
    '2D-Music-Agent',
    '2D-Sound-Effects-Agent',
    '2D-Colorist-Agent',
    '2D-Compositor-Agent',
    '2D-Quality-Control-Agent',
    '2D-Scheduling-Agent',
    '2D-Asset-Manager-Agent',
    '2D-Series-1-Agent',
    '2D-Series-2-Agent',
    '2D-Series-3-Agent',
    '2D-Series-4-Agent',
    '2D-Series-5-Agent',
    '2D-Series-6-Agent',
    '2D-Series-7-Agent',
    '2D-Series-8-Agent',
    '2D-Series-9-Agent',
    '2D-Series-10-Agent',
    'Business-Support-Overseer',
    'Financial-Agent',
    'Legal-Agent',
    'Customer-Support-Agent',
    'Compliance-Checker-Agent',
    'Case-Tracker-Agent',
    'Document-Filing-Agent',
    'Error-Detector-Agent',
]


def generate_unique_id(existing_ids: Set[str]) -> str:
    """Generate a unique 3-6 digit ID code"""
    while True:
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
    if 'Localization' in agent_name or 'Voice' in agent_name:
        return 'Localization'
    elif 'Marketing' in agent_name or 'Affiliate' in agent_name:
        return 'Marketing'
    elif 'Animation' in agent_name or '2D' in agent_name or '3D' in agent_name:
        return 'Animation'
    elif 'Business' in agent_name or 'Support' in agent_name:
        return 'Support'
    elif 'Content' in agent_name or 'Production' in agent_name or 'YouTube' in agent_name:
        return 'Production'
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

    return list(set(base_models))


def get_agent_tasks(agent_name: str) -> List[str]:
    """Get tasks for an agent based on their specialization"""
    tasks = []

    if 'Localization' in agent_name:
        tasks.extend(
            [
                'Translate content between languages',
                'Ensure cultural accuracy and sensitivity',
                'Maintain brand voice across languages',
                'Review and approve translations',
            ]
        )
    elif 'Voice' in agent_name:
        tasks.extend(
            [
                'Generate voice content in target language',
                'Ensure pronunciation accuracy',
                'Maintain consistent voice characteristics',
                'Sync voice with visual content',
            ]
        )
    elif 'Marketing' in agent_name:
        tasks.extend(
            [
                'Develop marketing strategies',
                'Create and optimize campaigns',
                'Analyze market trends and performance',
                'Coordinate with content and analytics teams',
            ]
        )
    elif 'Animation' in agent_name or '2D' in agent_name or '3D' in agent_name:
        tasks.extend(
            [
                'Create and animate visual content',
                'Design characters and environments',
                'Ensure quality and consistency',
                'Collaborate with script and voice teams',
            ]
        )
    elif 'YouTube' in agent_name:
        tasks.extend(
            [
                'Create and optimize YouTube content',
                'Manage channel growth and engagement',
                'Analyze performance metrics',
                'Coordinate with production teams',
            ]
        )
    elif 'Support' in agent_name:
        tasks.extend(
            [
                'Provide customer and business support',
                'Handle inquiries and issues',
                'Maintain compliance and quality standards',
                'Document and track support cases',
            ]
        )
    else:
        tasks.extend(
            [
                'Execute assigned tasks efficiently',
                'Collaborate with team members',
                'Maintain quality standards',
                'Report progress and results',
            ]
        )

    return tasks


def get_performance_metrics(agent_name: str) -> List[str]:
    """Get performance metrics for an agent"""
    metrics = []

    if 'Localization' in agent_name:
        metrics.extend(
            [
                'Translation accuracy rate',
                'Cultural adaptation quality',
                'Turnaround time for translations',
                'Client satisfaction scores',
            ]
        )
    elif 'Marketing' in agent_name:
        metrics.extend(
            [
                'Campaign performance metrics',
                'ROI and conversion rates',
                'Market reach and engagement',
                'Strategy effectiveness',
            ]
        )
    elif 'Animation' in agent_name:
        metrics.extend(
            ['Animation quality scores', 'Production efficiency', 'Client feedback ratings', 'Project completion rates']
        )
    else:
        metrics.extend(
            ['Task completion rate', 'Quality of deliverables', 'Collaboration effectiveness', 'Timeliness of work']
        )

    return metrics


def get_collaboration_protocols(agent_name: str) -> List[str]:
    """Get collaboration protocols for an agent"""
    protocols = []

    if 'Overseer' in agent_name or 'Master' in agent_name:
        protocols.extend(
            [
                'Lead and coordinate team efforts',
                'Review and approve team deliverables',
                'Provide guidance and feedback',
                'Report to executive management',
            ]
        )
    else:
        protocols.extend(
            [
                'Collaborate with team members',
                'Follow established workflows',
                'Communicate progress and issues',
                'Seek guidance when needed',
            ]
        )

    return protocols


def get_production_workflow(agent_name: str) -> List[str]:
    """Get production workflow for an agent"""
    workflow = [
        'Receive task or project brief',
        'Plan and execute assigned work',
        'Review and quality check deliverables',
        'Submit for approval or handoff',
        'Document work and lessons learned',
    ]

    return workflow


def get_capabilities(agent_name: str) -> List[str]:
    """Get capabilities for an agent"""
    capabilities = ['Task Execution', 'Collaboration']

    if 'Localization' in agent_name:
        capabilities.extend(['Translation', 'Cultural Adaptation', 'Language Expertise'])
    elif 'Voice' in agent_name:
        capabilities.extend(['Voice Generation', 'Audio Processing', 'Language Pronunciation'])
    elif 'Marketing' in agent_name:
        capabilities.extend(['Marketing Strategy', 'Campaign Management', 'Market Analysis'])
    elif 'Animation' in agent_name or '2D' in agent_name or '3D' in agent_name:
        capabilities.extend(['Animation', 'Design', 'Creative Production'])
    elif 'YouTube' in agent_name:
        capabilities.extend(['Content Creation', 'Channel Management', 'Analytics'])
    elif 'Support' in agent_name:
        capabilities.extend(['Customer Support', 'Problem Solving', 'Documentation'])

    return list(set(capabilities))


def create_agent_config(agent_name: str, agent_id: str) -> Dict:
    """Create a complete agent configuration in hybrid format"""
    tier = get_agent_tier(agent_name)
    department = get_agent_department(agent_name)
    ai_models = get_ai_models_for_agent(agent_name, tier)

    # Create role description
    role_parts = agent_name.replace('-', ' ').split()
    if 'Agent' in role_parts:
        role_parts.remove('Agent')
    role = ' '.join(role_parts).title()

    return {
        'name': agent_name,
        'role': f'{role} - Specialized task execution and collaboration',
        'tasks': get_agent_tasks(agent_name),
        'ai_models': ai_models,
        'id': agent_id,
        'tier': tier,
        'department': department,
        'capabilities': get_capabilities(agent_name),
        'performance_metrics': get_performance_metrics(agent_name),
        'collaboration_protocols': get_collaboration_protocols(agent_name),
        'production_workflow': get_production_workflow(agent_name),
        'status': 'active',
    }


def create_model_bar_mapping(agent_name: str, agent_id: str, ai_models: List[str], tier: str) -> Dict:
    """Create model bar mapping for an agent"""
    models = []
    for model in ai_models:
        models.append({'model': model, 'bar_id': f'{agent_name}__{model}'})

    return {'agent_id': agent_id, 'models': models, 'tier': tier}


def main():
    print('Creating new agent mappings with hybrid format...')

    # Generate unique IDs
    existing_ids = set()
    agent_configs = {}
    agent_mappings = {}

    # Create configurations for each agent
    for agent_name in AGENT_LIST:
        agent_id = generate_unique_id(existing_ids)
        existing_ids.add(agent_id)

        # Create agent configuration
        agent_config = create_agent_config(agent_name, agent_id)
        agent_configs[agent_name] = agent_config

        # Create model mapping
        tier = get_agent_tier(agent_name)
        ai_models = get_ai_models_for_agent(agent_name, tier)
        model_mapping = create_model_bar_mapping(agent_name, agent_id, ai_models, tier)
        agent_mappings[agent_name] = model_mapping

        print(f'Created {agent_name} - ID: {agent_id} - Tier: {tier}')

    # Save main configuration files
    with open('agent_configurations.json', 'w') as f:
        json.dump({'agents': agent_configs}, f, indent=2)

    with open('agent_model_bar_mapping.json', 'w') as f:
        json.dump(agent_mappings, f, indent=2)

    # Create individual JSON files for each agent
    agents_dir = 'agents'
    if not os.path.exists(agents_dir):
        os.makedirs(agents_dir)

    # Organize by department
    departments = {}
    for agent_name, config in agent_configs.items():
        dept = config['department']
        if dept not in departments:
            departments[dept] = []
        departments[dept].append(agent_name)

    # Create department directories and save individual files
    for dept, agents in departments.items():
        dept_dir = os.path.join(agents_dir, dept)
        if not os.path.exists(dept_dir):
            os.makedirs(dept_dir)

        for agent_name in agents:
            config = agent_configs[agent_name]
            filename = f'{agent_name}.json'
            filepath = os.path.join(dept_dir, filename)

            with open(filepath, 'w') as f:
                json.dump(config, f, indent=2)

    print(f'\nSuccessfully created {len(AGENT_LIST)} agent configurations')
    print('Files created:')
    print('- agent_configurations.json (main config)')
    print('- agent_model_bar_mapping.json (model mappings)')
    print('- Individual JSON files in agents/ directory')

    # Summary
    tier_counts = {}
    dept_counts = {}

    for config in agent_configs.values():
        tier = config['tier']
        dept = config['department']

        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        dept_counts[dept] = dept_counts.get(dept, 0) + 1

    print('\nAgent Summary:')
    print('\nBy Tier:')
    for tier, count in tier_counts.items():
        print(f'  {tier}: {count} agents')

    print('\nBy Department:')
    for dept, count in dept_counts.items():
        print(f'  {dept}: {count} agents')


if __name__ == '__main__':
    main()
