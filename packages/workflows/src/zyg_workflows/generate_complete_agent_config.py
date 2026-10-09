#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Generate Complete Agent Configurations Script
Creates a complete agent_configurations.json file with all 134 agents
"""

import json
from pathlib import Path

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# AI Model mapping for different agent types
_AI_MODEL_MAPPING = {
    # Executive agents
    'CEO-Agent': ['Claude 3', 'Llama 3', 'Crewai Openagents'],
    'CTO-Agent': ['Claude 3', 'Llama 3', 'Crewai Openagents'],
    # Overseer agents
    'Affiliate-Marketing-Overseer': ['Claude 3', 'Llama 3', 'Crewai Openagents'],
    'Animation-Media-Overseer': ['Claude 3', 'Llama 3', 'Mistral Mixtral', 'Crewai Openagents'],
    'Business-Support-Overseer': ['Claude 3', 'Llama 3', 'Mistral Mixtral', 'Crewai Openagents'],
    'Content-Production-Overseer': ['Claude 3', 'Llama 3', 'Mistral Mixtral', 'Crewai Openagents'],
    'Adult-NSFW-Overseer': ['Claude 3', 'Llama 3', 'Crewai Openagents'],
    '2D-Series-Overseer': ['Claude 3', 'Llama 3', 'Mistral Mixtral', 'Crewai Openagents'],
    '3D-Series-Overseer': ['Claude 3', 'Llama 3', 'Mistral Mixtral', 'Crewai Openagents'],
    'YouTube-Content-Overseer': ['Claude 3', 'Llama 3', 'Mistral Mixtral', 'Crewai Openagents'],
    # Animation agents
    '2D-Animation-Agent': ['Stable Video Diffusion', 'Animatediff', 'Whisper'],
    '3D-Animation-Agent': ['Stable Video Diffusion', 'Animatediff', 'Whisper', 'Blender (Bpy)'],
    '2D-Character-Designer-Agent': [
        'Stable Diffusion 1.5 Xl',
        'Dreamshaper Realisticvision',
        'Controlnet',
        'Dreambooth',
    ],
    '3D-Character-Designer-Agent': [
        'Stable Diffusion 1.5 Xl',
        'Dreamshaper Realisticvision',
        'Controlnet',
        'Dreambooth',
    ],
    '3D-Modeling-Agent': [
        'Stable Diffusion 1.5 Xl',
        'Dreamshaper Realisticvision',
        'Controlnet',
        'Dreambooth',
        'Blender (Bpy)',
    ],
    '3D-Rendering-Agent': ['Realesrgan', 'Blender (Bpy)', '3D-Render-Farm-Manager-Agent'],
    '3D-Environment-Agent': ['Stable Diffusion 1.5 Xl', 'Dreamshaper Realisticvision', 'Controlnet'],
    '3D-Lighting-Agent': ['Blender (Bpy)'],
    '3D-Rigging-Agent': ['Blender (Bpy)'],
    '3D-Texturing-Agent': ['Stable Diffusion 1.5 Xl', 'Dreamshaper Realisticvision', 'Dreambooth', 'Blender (Bpy)'],
    '3D-Compositor-Agent': ['Realesrgan', 'Blender (Bpy)'],
    '3D-Storyboard-Agent': ['Blender (Bpy)'],
    '3D-Effects-Agent': ['Stable Video Diffusion', 'Realesrgan'],
    '3D-Render-Farm-Manager-Agent': ['3D-Render-Farm-Manager-Agent'],
    # Voice agents
    '2D-Voice-Agent': ['Bark', 'Bark-Voice-Cloning', 'Tortoise Tts', 'Whisper'],
    '3D-Voice-Agent': ['Bark', 'Bark-Voice-Cloning', 'Tortoise Tts', 'Whisper'],
    'English-Voice-Agent': ['Bark', 'Bark-Voice-Cloning', 'Tortoise Tts', 'Whisper'],
    'Spanish-Voice-Agent': ['Bark', 'Bark-Voice-Cloning', 'Tortoise Tts', 'Whisper'],
    'French-Voice-Agent': ['Bark', 'Bark-Voice-Cloning', 'Tortoise Tts', 'Whisper'],
    'German-Voice-Agent': ['Bark', 'Bark-Voice-Cloning', 'Tortoise Tts', 'Whisper'],
    'Italian-Voice-Agent': ['Bark', 'Bark-Voice-Cloning', 'Tortoise Tts', 'Whisper'],
    'Portuguese-Voice-Agent': ['Bark', 'Bark-Voice-Cloning', 'Tortoise Tts', 'Whisper'],
    'Russian-Voice-Agent': ['Bark', 'Bark-Voice-Cloning', 'Tortoise Tts', 'Whisper'],
    'Japanese-Voice-Agent': ['Bark', 'Bark-Voice-Cloning', 'Tortoise Tts', 'Whisper'],
    'Korean-Voice-Agent': ['Bark', 'Bark-Voice-Cloning', 'Tortoise Tts', 'Whisper'],
    'Arabic-Voice-Agent': ['Bark', 'Bark-Voice-Cloning', 'Tortoise Tts', 'Whisper'],
    'Hindi-Voice-Agent': ['Bark', 'Bark-Voice-Cloning', 'Tortoise Tts', 'Whisper'],
    'Bengali-Voice-Agent': ['Bark', 'Bark-Voice-Cloning', 'Tortoise Tts', 'Whisper'],
    'Mandarin-Voice-Agent': ['Bark', 'Bark-Voice-Cloning', 'Tortoise Tts', 'Whisper'],
    # Content production agents
    'YouTube-Video-Editor-Agent': [
        'Stable Video Diffusion',
        'Animatediff',
        'Realesrgan',
        'Davinci Resolve',
        'Whisper',
    ],
    'YouTube-Audio-Agent': ['Bark', 'Bark-Voice-Cloning', 'Tortoise Tts', 'Whisper', 'Humaneval'],
    'YouTube-Analytics-Agent': ['Clip', 'Plotly'],
    'YouTube-Channel-Agent': ['Claude 3', 'Llama 3'],
    'YouTube-Community-Agent': ['Claude 3', 'Llama 3'],
    'YouTube-Scheduling-Agent': ['Airflow'],
    'YouTube-Thumbnail-Agent': ['Stable Diffusion 1.5 Xl', 'Dreamshaper Realisticvision'],
    'YouTube-Trend-Analyst-Agent': ['Claude 3', 'Llama 3'],
    'YouTube-Script-Agent': ['Claude 3', 'Llama 3'],
    'YouTube-SEO-Agent': ['Claude 3', 'Llama 3'],
    # Analytics and reporting agents
    'Analytics-Agent': ['Clip', 'Plotly'],
    'Analytics-Reporting-Agent': ['Clip', 'Plotly'],
    'Financial-Report-Agent': ['Plotly'],
    'Performance-Evaluator-Agent': ['Plotly'],
    # Quality control agents
    'Quality-Control-Agent': ['Ai Qc Engine'],
    '2D-Quality-Control-Agent': ['Ai Qc Engine'],
    '3D-Quality-Control-Agent': ['Ai Qc Engine'],
    'Multi-Language-QC-Agent': ['Ai Qc Engine'],
    # Scheduling and management agents
    'Daily-Production-Scheduler-Agent': ['Airflow'],
    'Task-Scheduler-Agent': ['Airflow'],
    '2D-Scheduling-Agent': ['Airflow'],
    '3D-Scheduling-Agent': ['Airflow'],
    'Video-Scheduler-Agent': ['Airflow'],
    'Reminder-Agent': ['Airflow'],
    # Asset and file management agents
    '2D-Asset-Manager-Agent': ['autosave_daemon'],
    '3D-Asset-Manager-Agent': ['autosave_daemon'],
    'Footage-Organizer-Agent': ['autosave_daemon'],
    'Document-Filing-Agent': ['autosave_daemon'],
    'Case-Tracker-Agent': ['autosave_daemon'],
    # Marketing agents
    'Affiliate-Marketing-Agent': ['Claude 3', 'Llama 3'],
    'Campaign-Builder-Agent': ['Claude 3', 'Llama 3'],
    'Conversion-Optimizer-Agent': ['Claude 3', 'Llama 3'],
    'Email-Marketing-Agent': ['Claude 3', 'Llama 3'],
    'PPC-Agent': ['Claude 3', 'Llama 3'],
    'SEO-Agent': ['Claude 3', 'Llama 3'],
    'Social-Media-Marketing-Agent': ['Claude 3', 'Llama 3'],
    'Content-Writer-Agent': ['Claude 3', 'Llama 3'],
    # Language-specific marketing agents
    'Arabic-Marketing-Agent': ['Claude 3', 'Llama 3'],
    'Bengali-Marketing-Agent': ['Claude 3', 'Llama 3'],
    'English-Marketing-Agent': ['Claude 3', 'Llama 3'],
    'French-Marketing-Agent': ['Claude 3', 'Llama 3'],
    'Hindi-Marketing-Agent': ['Claude 3', 'Llama 3'],
    'Mandarin-Marketing-Agent': ['Claude 3', 'Llama 3'],
    'Portuguese-Marketing-Agent': ['Claude 3', 'Llama 3'],
    'Spanish-Marketing-Agent': ['Claude 3', 'Llama 3'],
    # Business support agents
    'Customer-Support-Agent': ['Claude 3', 'Llama 3'],
    'Legal-Agent': ['Claude 3', 'Llama 3'],
    'Financial-Agent': ['Claude 3', 'Llama 3'],
    'Payroll-Agent': ['Claude 3', 'Llama 3'],
    'Tax-Agent': ['Claude 3', 'Llama 3'],
    'Expense-Agent': ['Claude 3', 'Llama 3'],
    'Invoice-Agent': ['Claude 3', 'Llama 3'],
    'Contract-Generator-Agent': ['Claude 3', 'Llama 3'],
    'Compliance-Checker-Agent': ['Claude 3', 'Llama 3'],
    'FAQ-Updater-Agent': ['Claude 3', 'Llama 3'],
    'Review-Agent': ['Claude 3', 'Llama 3'],
    'Ticket-Processor-Agent': ['Claude 3', 'Llama 3'],
    # Localization agents
    'Arabic-Localization-Agent': ['Claude 3', 'Llama 3'],
    'Bengali-Localization-Agent': ['Claude 3', 'Llama 3'],
    'English-Localization-Agent': ['Claude 3', 'Llama 3'],
    'French-Localization-Agent': ['Claude 3', 'Llama 3'],
    'Hindi-Localization-Agent': ['Claude 3', 'Llama 3'],
    'Mandarin-Localization-Agent': ['Claude 3', 'Llama 3'],
    'Portuguese-Localization-Agent': ['Claude 3', 'Llama 3'],
    'Spanish-Localization-Agent': ['Claude 3', 'Llama 3'],
    'Localization-Master-Agent': ['Claude 3', 'Llama 3'],
    'Voice-Localization-Master-Agent': ['Claude 3', 'Llama 3'],
    'Cultural-Adaptation-Master-Agent': ['Claude 3', 'Llama 3'],
    # Series-specific agents
    '2D-Series-Agent': ['Stable Video Diffusion', 'Animatediff', 'Whisper'],
    '3D-Series-Agent': ['Stable Video Diffusion', 'Animatediff', 'Whisper'],
    '2D-Series-1-Agent': ['Stable Video Diffusion', 'Animatediff', 'Whisper'],
    '2D-Series-2-Agent': ['Stable Video Diffusion', 'Animatediff', 'Whisper'],
    '2D-Series-3-Agent': ['Stable Video Diffusion', 'Animatediff', 'Whisper'],
    '2D-Series-4-Agent': ['Stable Video Diffusion', 'Animatediff', 'Whisper'],
    '2D-Series-5-Agent': ['Stable Video Diffusion', 'Animatediff', 'Whisper'],
    '2D-Series-6-Agent': ['Stable Video Diffusion', 'Animatediff', 'Whisper'],
    '2D-Series-7-Agent': ['Stable Video Diffusion', 'Animatediff', 'Whisper'],
    '2D-Series-8-Agent': ['Stable Video Diffusion', 'Animatediff', 'Whisper'],
    '2D-Series-9-Agent': ['Stable Video Diffusion', 'Animatediff', 'Whisper'],
    '2D-Series-10-Agent': ['Stable Video Diffusion', 'Animatediff', 'Whisper'],
    # Script and content agents
    '2D-Script-Agent': ['Claude 3', 'Llama 3'],
    '3D-Script-Agent': ['Claude 3', 'Llama 3'],
    'Script-Agent': ['Claude 3', 'Llama 3'],
    'Scene-Editor-Agent': ['Davinci Resolve', 'Effects-Agent'],
    'Effects-Agent': ['Stable Video Diffusion', 'Realesrgan'],
    'Render-Agent': ['Realesrgan', '3D-Render-Farm-Manager-Agent'],
    'Thumbnail-Agent': ['Stable Diffusion 1.5 Xl', 'Dreamshaper Realisticvision'],
    'Upload-Agent': ['Fastapi'],
    'Progress-Tracker-Agent': ['Clip'],
    'Metadata-Agent': ['Clip'],
    'Comment-Moderator-Agent': ['Claude 3', 'Llama 3'],
    'Channel-Manager-Agent': ['Claude 3', 'Llama 3'],
    'Audio-Editor-Agent': ['Humaneval', 'Whisper'],
    '2D-Sound-Effects-Agent': ['Humaneval'],
    '2D-Background-Artist-Agent': ['Stable Diffusion 1.5 Xl', 'Dreamshaper Realisticvision'],
    '2D-Colorist-Agent': ['Realesrgan'],
    '2D-Compositor-Agent': ['Realesrgan'],
    '2D-Music-Agent': ['Humaneval'],
    '2D-Storyboard-Agent': ['Claude 3', 'Llama 3'],
    '3D-Music-Agent': ['Humaneval'],
    'Audience-Targeting-Agent': ['Claude 3', 'Llama 3'],
    'Movies-of-Peoples-Lives-Agent': ['Claude 3', 'Llama 3'],
    'Revenue-Optimization-Agent': ['Claude 3', 'Llama 3'],
    'Error-Detector-Agent': ['Claude 3', 'Llama 3'],
    'Feedback-Collector-Agent': ['Claude 3', 'Llama 3'],
}

# Department mapping
_DEPARTMENT_MAPPING = {
    'CEO-Agent': 'Executive',
    'CTO-Agent': 'Executive',
    'Affiliate-Marketing-Overseer': 'Marketing',
    'Animation-Media-Overseer': 'Animation',
    'Business-Support-Overseer': 'Business Support',
    'Content-Production-Overseer': 'Content Production',
    'Adult-NSFW-Overseer': 'Content Production',
    '2D-Series-Overseer': 'Animation',
    '3D-Series-Overseer': 'Animation',
    'YouTube-Content-Overseer': 'Content Production',
}

# Tier mapping
_TIER_MAPPING = {
    'CEO-Agent': 'Executive',
    'CTO-Agent': 'Executive',
    'Affiliate-Marketing-Overseer': 'Management',
    'Animation-Media-Overseer': 'Management',
    'Business-Support-Overseer': 'Management',
    'Content-Production-Overseer': 'Management',
    'Adult-NSFW-Overseer': 'Management',
    '2D-Series-Overseer': 'Management',
    '3D-Series-Overseer': 'Management',
    'YouTube-Content-Overseer': 'Management',
}

#: (token, capabilities) in the order the old if-ladder tested them. A role string
#: collects the capabilities of every token it contains, appended in this order.
_CAPABILITY_RULES = (
    ('Animation', ['Animation', 'Creative Design']),
    ('Marketing', ['Marketing', 'Campaign Management']),
    ('Support', ['Support', 'Operations']),
    ('Production', ['Content Production', 'Quality Control']),
    ('Voice', ['Voice Synthesis', 'Audio Processing']),
    ('Analytics', ['Data Analysis', 'Reporting']),
    ('Scheduling', ['Scheduling', 'Resource Management']),
    ('Quality', ['Quality Assurance', 'Testing']),
    ('Asset', ['Asset Management', 'Organization']),
    ('SEO', ['SEO', 'Optimization']),
    ('Video', ['Video Editing', 'Post-Production']),
    ('3D', ['3D Modeling', 'Rendering']),
    ('2D', ['2D Animation', 'Design']),
)

#: What an agent whose role matches none of the _CAPABILITY_RULES tokens gets.
_DEFAULT_CAPABILITIES = ['Task Execution', 'Collaboration']

#: AI models for an agent that is not named in _AI_MODEL_MAPPING.
_DEFAULT_AI_MODELS = ['Claude 3', 'Llama 3']


def _capabilities_for(agent_role):
    """Capabilities implied by a role string.

    Takes the role text; returns a fresh list holding, in _CAPABILITY_RULES order,
    the capabilities of every token the role contains — or a copy of
    _DEFAULT_CAPABILITIES when it contains none.
    """
    capabilities = []
    for token, caps in _CAPABILITY_RULES:
        if token in agent_role:
            capabilities.extend(caps)
    if not capabilities:
        capabilities = list(_DEFAULT_CAPABILITIES)
    return capabilities


def _agent_entry(agent_info, overseer):
    """One agent's configuration record.

    agent_info is an index entry ({'name', 'role', 'id'}) and overseer is the
    index key it was listed under, which is also the department fallback
    ('Animation-Overseer' -> 'Animation'). Returns the record dict.
    """
    agent_name = agent_info['name']
    agent_role = agent_info['role']
    agent_id = agent_info['id']

    # Determine department
    department = _DEPARTMENT_MAPPING.get(agent_name, overseer.replace('-Overseer', ''))

    # Determine tier
    tier = _TIER_MAPPING.get(agent_name, 'Specialist')

    # Get AI models
    ai_models = _AI_MODEL_MAPPING.get(agent_name, list(_DEFAULT_AI_MODELS))

    # Generate goal and backstory based on role
    goal = f'Execute {agent_role.lower()} tasks efficiently and contribute to overall project success'
    backstory = (
        f'Specialized agent with expertise in {agent_role.lower()}. '
        'Skilled at performing assigned tasks and collaborating with other agents.'
    )

    return {
        'name': agent_name,
        'role': agent_role,
        'goal': goal,
        'backstory': backstory,
        'tier': tier,
        'department': department,
        'ai_models': ai_models,
        'capabilities': _capabilities_for(agent_role),
        'status': 'active',
        'id': agent_id,
    }


def _agents_config(index_data):
    """{agent name: record} for every agent in a parsed agents/index.json.

    Walks index_data['agents_by_overseer'] in file order, so the result keeps the
    index's ordering; a name listed twice keeps its last entry, as before.
    """
    agents_config = {}
    for overseer, agents in index_data['agents_by_overseer'].items():
        for agent_info in agents:
            agents_config[agent_info['name']] = _agent_entry(agent_info, overseer)
    return agents_config


def _complete_config(agents_config):
    """Wrap the per-agent records in the file-level {'agents', 'metadata'} shape."""
    return {
        'agents': agents_config,
        'metadata': {
            'total_agents': len(agents_config),
            'version': '1.0',
            'last_updated': '2025-07-13',
            'description': 'Complete agent configurations for CrewAI Dashboard',
        },
    }


def generate_agent_configurations():
    """Generate complete agent configurations from the index file"""

    # Load the agents index
    index_path = Path('agents/index.json')
    if not index_path.exists():
        _zyg_log.info(f'Index file not found: {index_path}')
        return

    with open(index_path, 'r', encoding='utf-8') as f:
        index_data = json.load(f)

    # Generate agent configurations
    agents_config = _agents_config(index_data)

    # Create the complete configuration
    complete_config = _complete_config(agents_config)

    # Save the configuration
    output_path = 'agent_configurations.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(complete_config, f, indent=2, ensure_ascii=False)

    _zyg_log.info(f'✅ Generated complete agent configurations with {len(agents_config)} agents')
    _zyg_log.info(f'📁 Saved to: {output_path}')

    return complete_config


if __name__ == '__main__':
    generate_agent_configurations()
