#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Sync GPU Models in agent_bar_mapping.json
Ensures all GPU models from ai_model_agent_mapping.py are present as columns in the mapping file.
"""

import importlib.util
import json
import os
import random
import string

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# Paths
mapping_path = os.path.join('Schedule', 'agent_bar_mapping.json')
ai_mapping_path = 'ai_model_agent_mapping.py'

# Import GPU model list from ai_model_agent_mapping.py
spec = importlib.util.spec_from_file_location('ai_model_agent_mapping', ai_mapping_path)
ai_model_agent_mapping = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai_model_agent_mapping)
GPU_MODELS = set(ai_model_agent_mapping.GPU_MODELS)

# Read the mapping file
with open(mapping_path, 'r', encoding='utf-8') as f:
    mapping = json.load(f)

# Collect all models currently present in the mapping
present_models = set()
for data in mapping.values():
    for m in data.get('models', []):
        present_models.add(m['model'])

# Find missing GPU models
missing_models = GPU_MODELS - present_models

# Add placeholder entries for missing models
if missing_models:
    _zyg_log.info(f'Adding {len(missing_models)} missing GPU models to mapping...')
    # Add a dummy agent if needed, or add to all agents
    for model in missing_models:
        # Add to a special placeholder agent, or to all tier 1 agents
        placeholder_agent = f'__PLACEHOLDER__{model.replace(" ", "_")}'
        if placeholder_agent not in mapping:
            mapping[placeholder_agent] = {
                'agent_id': ''.join(random.choices(string.hexdigits, k=16)),
                'tier': 0,
                'models': [{'model': model, 'bar_id': ''.join(random.choices(string.hexdigits, k=8))}],
            }
        else:
            # If already exists, just add the model if not present
            existing_models = {m['model'] for m in mapping[placeholder_agent]['models']}
            if model not in existing_models:
                mapping[placeholder_agent]['models'].append(
                    {'model': model, 'bar_id': ''.join(random.choices(string.hexdigits, k=8))}
                )
else:
    _zyg_log.info('No missing GPU models. Mapping is up to date.')

# Write back the updated mapping
with open(mapping_path, 'w', encoding='utf-8') as f:
    json.dump(mapping, f, indent=2)

_zyg_log.info('Done. All GPU models are now present in agent_bar_mapping.json.')
