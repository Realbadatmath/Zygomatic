# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import json

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# Load the main mapping file
with open('agent_model_bar_mapping.json', 'r', encoding='utf-8') as f:
    main_mapping = json.load(f)

# Remove Claude 3 (model 1017) from all agents
for _agent, data in main_mapping.items():
    models = data.get('models', [])
    # Keep only non-Claude models
    non_claude_models = [m for m in models if m.get('model') != '1017']
    data['models'] = non_claude_models

# Save updated GPU mapping
with open('agent_model_bar_mapping.json', 'w', encoding='utf-8') as f:
    json.dump(main_mapping, f, indent=2)

_zyg_log.info('Removed Claude 3 (model 1017) from GPU mapping')

# Count remaining models
remaining_models = set()
for agent_data in main_mapping.values():
    for model in agent_data.get('models', []):
        remaining_models.add(model['model'])

_zyg_log.info(f'Remaining models in GPU mapping: {len(remaining_models)}')
_zyg_log.info(f'GPU models: {sorted(remaining_models)}')
