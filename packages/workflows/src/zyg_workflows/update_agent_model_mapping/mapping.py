# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Reading the model catalogues, matching names to ids, updating the mapping file.

Verbatim from the single-file update_agent_model_mapping.py: lines 872-1061.
"""

import json
import logging as _zyg_logging

from zyg_workflows.update_agent_model_mapping.constants import CPU_MODELS_FILE, GPU_MODELS_FILE, MAPPING_FILE

from zyg_workflows.update_agent_model_mapping.verticals import BUSINESS_VERTICALS

_zyg_log = _zyg_logging.getLogger('zyg_workflows.update_agent_model_mapping')


def load_json_file(filepath):
    """Load JSON file safely"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        _zyg_log.info(f'Warning: {filepath} not found')
        return {}
    except json.JSONDecodeError as e:
        _zyg_log.info(f'Error reading {filepath}: {e}')
        return {}


def save_json_file(filepath, data):
    """Save JSON file with proper formatting"""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_next_model_id(cpu_models, gpu_models):
    """Get next available model ID"""
    all_ids = []

    # Get IDs from CPU models
    for model_id in cpu_models.keys():
        try:
            all_ids.append(int(model_id))
        except (ValueError, TypeError) as _exc:
            _zyg_log.debug('non-numeric model id %r ignored: %s', model_id, _exc)
            continue

    # Get IDs from GPU models
    for model_id in gpu_models.keys():
        try:
            all_ids.append(int(model_id))
        except (ValueError, TypeError) as _exc:
            _zyg_log.debug('non-numeric model id %r ignored: %s', model_id, _exc)
            continue

    return str(max(all_ids) + 1) if all_ids else '1001'


def normalize_model_name(name):
    """Normalize model name for consistent formatting"""
    # Replace underscores with spaces and handle special cases
    normalized = name.replace('___', ' ').replace('_', ' ')

    # Handle specific model name mappings
    mappings = {
        'Claude 3': 'Claude 3',
        'GPT 4': 'GPT-4',
        'LLaMA 3': 'Llama 3',
        'Mistral Mixtral': 'Mistral Mixtral',
        'Stable Diffusion 1.5 XL': 'Stable Diffusion 1.5 XL',
        'DreamShaper RealisticVision': 'DreamShaper RealisticVision',
        'Stable Video Diffusion': 'Stable Video Diffusion',
        'CrewAI OpenAgents': 'Crewai Openagents',
        'LangChain Llamalend': 'Langchain Llamalend',
        'Davinci Resolve': 'Davinci Resolve',
        'Tortoise TTS': 'Tortoise TTS',
        'AI QC Engine': 'AI QC Engine',
    }

    return mappings.get(normalized, normalized)


def find_model_id(model_name, cpu_models, gpu_models):
    """Find existing model ID or create new one"""
    normalized_name = normalize_model_name(model_name)

    # Check CPU models
    for model_id, model_data in cpu_models.items():
        if model_data.get('name', '').lower() == normalized_name.lower():
            return model_id

    # Check GPU models
    for model_id, model_data in gpu_models.items():
        if model_data.get('name', '').lower() == normalized_name.lower():
            return model_id

    # Create new ID
    new_id = get_next_model_id(cpu_models, gpu_models)

    # Determine if it's CPU or GPU based on model type
    gpu_keywords = [
        'diffusion',
        'stable',
        'dreamshaper',
        'animate',
        'video',
        'controlnet',
        'kandinsky',
        'realesrgan',
        'bark',
        'tortoise',
        'whisper',
        'librosa',
        'ffmpeg',
        'pydub',
        'davinci',
        'blender',
        'comfyui',
        'deforum',
        'dreambooth',
        'lora',
        'vae',
        'opencv',
        'yolo',
        'segment',
    ]

    is_gpu = any(keyword in normalized_name.lower() for keyword in gpu_keywords)

    # Add to appropriate model file
    new_model = {'name': normalized_name}

    if is_gpu:
        gpu_models[new_id] = new_model
        save_json_file(GPU_MODELS_FILE, gpu_models)
        _zyg_log.info(f'Added new GPU model: {normalized_name} (ID: {new_id})')
    else:
        cpu_models[new_id] = new_model
        save_json_file(CPU_MODELS_FILE, cpu_models)
        _zyg_log.info(f'Added new CPU model: {normalized_name} (ID: {new_id})')

    return new_id


def update_agent_mapping():
    """Update agent_model_bar_mapping.json with missing models"""

    # Load existing files
    mapping = load_json_file(MAPPING_FILE)
    cpu_models = load_json_file(CPU_MODELS_FILE)
    gpu_models = load_json_file(GPU_MODELS_FILE)

    if not mapping:
        _zyg_log.info('Error: Could not load agent_model_bar_mapping.json')
        return

    # Track changes
    changes_made = False

    # Process each business vertical
    for _vertical_name, vertical_data in BUSINESS_VERTICALS.items():
        for agent_name, agent_data in vertical_data['agents'].items():
            # Skip if agent doesn't exist in mapping
            if agent_name not in mapping:
                _zyg_log.info(f'Warning: Agent {agent_name} not found in mapping, skipping')
                continue

            # Get existing models for this agent
            existing_models = mapping[agent_name].get('models', [])
            existing_model_names = {model['model'].split(' (')[0] for model in existing_models}

            # Process AI models
            all_models = agent_data.get('ai_models', []) + agent_data.get('gpu_models', [])

            for model_name in all_models:
                normalized_name = normalize_model_name(model_name)

                # Skip if model already exists
                if normalized_name in existing_model_names:
                    continue

                # Find or create model ID
                model_id = find_model_id(model_name, cpu_models, gpu_models)

                # Create new model entry
                new_model_entry = {
                    'model': f'{normalized_name} ({model_id})',
                    'bar_id': f'{agent_name}__{normalized_name}',
                }

                # Add to agent's models
                existing_models.append(new_model_entry)
                changes_made = True

                _zyg_log.info(f'Added {normalized_name} to {agent_name}')

            # Update the agent's models
            mapping[agent_name]['models'] = existing_models

    # Save updated mapping
    if changes_made:
        save_json_file(MAPPING_FILE, mapping)
        _zyg_log.info(f'\nUpdated {MAPPING_FILE} with missing models')
    else:
        _zyg_log.info('\nNo changes needed - all models already present')
