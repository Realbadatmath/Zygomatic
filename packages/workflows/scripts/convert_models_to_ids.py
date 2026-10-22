#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Convert model names to model IDs in agent_bar_mapping.json
"""

import json

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def convert_models_to_ids():
    """Convert model names to model IDs"""

    # Load the model ID mapping
    with open('gpu_ai_models.json', 'r', encoding='utf-8') as f:
        model_id_map = json.load(f)

    # Create reverse mapping: name -> id
    name_to_id = {}
    for mid, info in model_id_map.items():
        name_to_id[info['name']] = mid

    _zyg_log.info(f'Loaded {len(name_to_id)} model name to ID mappings')

    # Load the agent mapping
    with open('Schedule/agent_bar_mapping.json', 'r', encoding='utf-8') as f:
        mapping = json.load(f)

    # Convert models
    converted_count = 0
    not_found_count = 0

    for agent_name, agent_data in mapping.items():
        models = agent_data.get('models', [])
        for model_obj in models:
            old_model_name = model_obj.get('model')
            if old_model_name in name_to_id:
                new_model_id = name_to_id[old_model_name]
                model_obj['model'] = new_model_id
                converted_count += 1
                _zyg_log.info(f"Converted {agent_name}: '{old_model_name}' -> '{new_model_id}'")
            else:
                not_found_count += 1
                _zyg_log.info(f"⚠️  Model not found: '{old_model_name}' for agent {agent_name}")

    # Save the updated mapping
    with open('Schedule/agent_bar_mapping.json', 'w', encoding='utf-8') as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)

    _zyg_log.info(f'\n✅ Converted {converted_count} models to IDs')
    _zyg_log.info(f'⚠️  {not_found_count} models not found in mapping')
    _zyg_log.info('📁 Updated file: Schedule/agent_bar_mapping.json')

    # Verify the conversion
    with open('Schedule/agent_bar_mapping.json', 'r', encoding='utf-8') as f:
        mapping = json.load(f)

    first_agent = list(mapping.values())[0]
    first_model = first_agent['models'][0]['model'] if first_agent['models'] else None
    _zyg_log.info(f'🔍 Verification - First agent first model: {first_model} (type: {type(first_model)})')


if __name__ == '__main__':
    convert_models_to_ids()
