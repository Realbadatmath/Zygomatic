#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Fix AI Model Mapping Script
Ensures all CPU and GPU models are properly mapped to agents
"""

import json
import os

from zyg_workflows import fix_ai_model_mapping_tables as _tables

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

CPU_MODELS = _tables.CPU_MODELS
GPU_MODELS = _tables.GPU_MODELS


def fix_ai_model_mapping():
    """Fix the AI model mapping to include all models"""

    _zyg_log.info('🔧 FIXING AI MODEL MAPPING')
    _zyg_log.info('=' * 40)

    # Load current agent configurations
    config_path = 'agent_configurations.json'
    if not os.path.exists(config_path):
        _zyg_log.info(f'❌ Agent configurations file not found: {config_path}')
        return

    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    agents = config['agents']
    _zyg_log.info(f'📊 Total agents: {len(agents)}')

    # The model → agents table and the two model-family lists are
    # `fix_ai_model_mapping_tables`; the four "every agent" rows take the
    # agent ids of the configuration just loaded.
    model_to_agents = _tables.table(list(agents.keys()))

    # Create the updated mapping file
    mapping_content = _tables.render_mapping_module(model_to_agents)

    # Save the updated mapping
    with open('ai_model_agent_mapping.py', 'w', encoding='utf-8') as f:
        f.write(mapping_content)

    _zyg_log.info(f'✅ Updated AI model mapping with {len(model_to_agents)} models')
    _zyg_log.info(f'📊 CPU models: {len(CPU_MODELS)}')
    _zyg_log.info(f'🎮 GPU models: {len(GPU_MODELS)}')

    # Count agents per model
    cpu_model_count, gpu_model_count = _tables.count_mapped_models(model_to_agents)

    _zyg_log.info('📈 Models with agent mappings:')
    _zyg_log.info(f'   CPU: {cpu_model_count} models')
    _zyg_log.info(f'   GPU: {gpu_model_count} models')

    return True


if __name__ == '__main__':
    fix_ai_model_mapping()
