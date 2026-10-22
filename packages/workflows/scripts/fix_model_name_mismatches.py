#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Fix model name mismatches in agent_bar_mapping.json
"""

import json

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def fix_model_name_mismatches():
    """Fix model name mismatches"""

    # Name corrections
    name_corrections = {
        'Stable Diffusion 1.5 Xl': 'Stable Diffusion 1.5 XL',
        'Tortoise Tts': 'Tortoise TTS',
        'Blender (Bpy)': 'Blender (bpy)',
        'Ai Qc Engine': 'AI QC Engine',
        '3D-Render-Farm-Manager-Agent': 'autosave_daemon',  # This seems to be a placeholder
    }

    # Load the agent mapping
    with open('Schedule/agent_bar_mapping.json', 'r', encoding='utf-8') as f:
        mapping = json.load(f)

    # Fix model names
    fixed_count = 0

    for agent_name, agent_data in mapping.items():
        models = agent_data.get('models', [])
        for model_obj in models:
            old_model_name = model_obj.get('model')
            if old_model_name in name_corrections:
                new_model_name = name_corrections[old_model_name]
                model_obj['model'] = new_model_name
                fixed_count += 1
                _zyg_log.info(f"Fixed {agent_name}: '{old_model_name}' -> '{new_model_name}'")

    # Save the updated mapping
    with open('Schedule/agent_bar_mapping.json', 'w', encoding='utf-8') as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)

    _zyg_log.info(f'\n✅ Fixed {fixed_count} model name mismatches')
    _zyg_log.info('📁 Updated file: Schedule/agent_bar_mapping.json')


if __name__ == '__main__':
    fix_model_name_mismatches()
