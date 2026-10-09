#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Fix Humaneval model references in agent configurations.
Convert string "Humaneval" to numeric ID "1020" in all relevant files.
"""

import json
import os
from typing import Dict, Any

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def load_json_file(file_path: str) -> Dict[str, Any]:
    """Load a JSON file and return its contents."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        _zyg_log.info(f'Error loading {file_path}: {e}')
        return {}


def save_json_file(file_path: str, data: Dict[str, Any]) -> bool:
    """Save data to a JSON file."""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        _zyg_log.info(f'Error saving {file_path}: {e}')
        return False


def fix_humaneval_in_agent_configs():
    """Fix Humaneval references in agent configuration files."""

    # Files to check and fix
    files_to_fix = [
        'agent_configurations.json',
        'Schedule/agent_bar_mapping.json',
        'Schedule/agent_model_bar_mapping_fixed.json',
        'Schedule/agent_model_bar_mapping_backup.json',
        'agent_model_bar_mapping.json',
    ]

    fixed_count = 0

    for file_path in files_to_fix:
        if not os.path.exists(file_path):
            _zyg_log.info(f'File not found: {file_path}')
            continue

        _zyg_log.info(f'\nProcessing: {file_path}')
        data = load_json_file(file_path)
        if not data:
            continue

        file_fixed = False

        # Fix agent configurations
        if 'agents' in data:
            for agent_name, agent_config in data['agents'].items():
                if 'ai_models' in agent_config:
                    models = agent_config['ai_models']
                    if isinstance(models, list):
                        for i, model in enumerate(models):
                            if model == 'Humaneval':
                                models[i] = '1020'
                                file_fixed = True
                                _zyg_log.info(f'  Fixed {agent_name}: Humaneval -> 1020')

        # Fix agent bar mappings
        for key, value in data.items():
            if isinstance(value, dict) and 'models' in value:
                models = value['models']
                if isinstance(models, list):
                    for model_entry in models:
                        if isinstance(model_entry, dict) and 'model' in model_entry:
                            if model_entry['model'] == 'Humaneval':
                                model_entry['model'] = '1020'
                                file_fixed = True
                                _zyg_log.info(f'  Fixed {key}: Humaneval -> 1020')

        if file_fixed:
            if save_json_file(file_path, data):
                fixed_count += 1
                _zyg_log.info(f'  ✓ Saved {file_path}')
            else:
                _zyg_log.info(f'  ✗ Failed to save {file_path}')
        else:
            _zyg_log.info(f'  No Humaneval references found in {file_path}')

    return fixed_count


def fix_individual_agent_files():
    """Fix Humaneval references in individual agent JSON files."""

    agents_dir = 'agents'
    if not os.path.exists(agents_dir):
        _zyg_log.info(f'Agents directory not found: {agents_dir}')
        return 0

    fixed_count = 0

    for root, _dirs, files in os.walk(agents_dir):
        for file in files:
            if file.endswith('.json'):
                file_path = os.path.join(root, file)
                data = load_json_file(file_path)
                if not data:
                    continue

                file_fixed = False

                if 'ai_models' in data:
                    models = data['ai_models']
                    if isinstance(models, list):
                        for i, model in enumerate(models):
                            if model == 'Humaneval':
                                models[i] = '1020'
                                file_fixed = True
                                _zyg_log.info(f'  Fixed {file_path}: Humaneval -> 1020')

                if file_fixed:
                    if save_json_file(file_path, data):
                        fixed_count += 1
                        _zyg_log.info(f'  ✓ Saved {file_path}')
                    else:
                        _zyg_log.info(f'  ✗ Failed to save {file_path}')

    return fixed_count


def main():
    """Main function to fix all Humaneval references."""
    print('=== Fixing Humaneval Model References ===')
    print("Converting 'Humaneval' string to numeric ID '1020'")

    # Fix main configuration files
    print('\n1. Fixing main configuration files...')
    config_fixed = fix_humaneval_in_agent_configs()

    # Fix individual agent files
    print('\n2. Fixing individual agent files...')
    agent_fixed = fix_individual_agent_files()

    total_fixed = config_fixed + agent_fixed

    print('\n=== Summary ===')
    print(f'Configuration files fixed: {config_fixed}')
    print(f'Individual agent files fixed: {agent_fixed}')
    print(f'Total files fixed: {total_fixed}')

    if total_fixed > 0:
        print('\n✓ Humaneval references have been converted to numeric IDs.')
        print('Please restart your backend to apply the changes.')
    else:
        print('\nNo Humaneval references found to fix.')


if __name__ == '__main__':
    main()
