# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import json

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# Define all CPU models that should be removed from GPU
CPU_MODELS = {
    '1007',
    '1008',
    '1014',
    '1015',
    '1017',
    '1018',
    '1019',
    '1020',
    '1021',
    '1022',
    '1023',
    '1024',
    '1025',
    '1027',
    '1028',
    '1029',
    '1031',
    '1032',
    '1041',
    '1043',
    '1047',
}

# Load the main mapping file
with open('agent_model_bar_mapping.json', 'r', encoding='utf-8') as f:
    main_mapping = json.load(f)

# Remove CPU models from all agents
for _agent, data in main_mapping.items():
    models = data.get('models', [])
    # Keep only non-CPU models
    gpu_models = [m for m in models if m.get('model') not in CPU_MODELS]
    data['models'] = gpu_models

# Save updated GPU mapping
with open('agent_model_bar_mapping.json', 'w', encoding='utf-8') as f:
    json.dump(main_mapping, f, indent=2)

_zyg_log.info('Removed all CPU models from GPU mapping')

# Count remaining models
remaining_models = set()
for agent_data in main_mapping.values():
    for model in agent_data.get('models', []):
        remaining_models.add(model['model'])

_zyg_log.info(f'Remaining models in GPU mapping: {len(remaining_models)}')
_zyg_log.info(f'GPU models: {sorted(remaining_models)}')

# Show sample agents
_zyg_log.info('\nSample GPU agents:')
count = 0
for agent, data in main_mapping.items():
    if data.get('models') and count < 5:
        models = [m['model'] for m in data['models']]
        _zyg_log.info(f'  {agent}: {models}')
        count += 1
