#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Fix Remaining Model Names to IDs
Converts any remaining model names to model IDs in the agent bar mapping
"""

import json
import os

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def fix_remaining_model_names():
    """Fix any remaining model names to model IDs"""

    _zyg_log.info('🔧 FIXING REMAINING MODEL NAMES TO IDS')
    _zyg_log.info('=' * 50)

    # Load the current agent bar mapping
    mapping_path = 'Schedule/agent_model_bar_mapping.json'
    if not os.path.exists(mapping_path):
        _zyg_log.info(f'❌ Agent bar mapping file not found: {mapping_path}')
        return

    with open(mapping_path, 'r', encoding='utf-8') as f:
        current_mapping = json.load(f)

    # Load the model ID mapping
    model_id_path = 'gpu_ai_models.json'
    if not os.path.exists(model_id_path):
        _zyg_log.info(f'❌ Model ID mapping file not found: {model_id_path}')
        return

    with open(model_id_path, 'r', encoding='utf-8') as f:
        model_id_map = json.load(f)

    # Create reverse mapping from name to ID
    name_to_id = {}
    for model_id, model_info in model_id_map.items():
        name_to_id[model_info['name']] = model_id

    _zyg_log.info(f'📊 Loaded {len(name_to_id)} model name to ID mappings')

    # Fix the agent bar mapping
    fixed_count = 0
    error_count = 0

    for _agent_id, agent_data in current_mapping.items():
        for model_info in agent_data.get('models', []):
            model_name = model_info['model']

            # Skip if already a numeric ID
            if model_name.isdigit():
                continue

            if model_name in name_to_id:
                model_id = name_to_id[model_name]
                model_info['model'] = model_id
                fixed_count += 1
                _zyg_log.info(f'✅ Fixed: {model_name} -> {model_id}')
            else:
                _zyg_log.info(f"⚠️  Warning: Model name '{model_name}' not found in ID mapping")
                error_count += 1

    # Save the fixed mapping
    with open(mapping_path, 'w', encoding='utf-8') as f:
        json.dump(current_mapping, f, indent=2, ensure_ascii=False)

    _zyg_log.info('\n📈 SUMMARY:')
    _zyg_log.info(f'✅ Fixed mappings: {fixed_count}')
    _zyg_log.info(f'⚠️  Errors: {error_count}')
    _zyg_log.info(f'💾 Updated: {mapping_path}')

    return current_mapping


if __name__ == '__main__':
    fix_remaining_model_names()
