# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import json

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

GPU_MAPPING_PATH = 'Schedule/agent_model_bar_mapping.json'
CPU_MAPPING_PATH = 'Schedule/cpu_agent_model_bar_mapping.json'

claude3_id = '1030'

with open(GPU_MAPPING_PATH, 'r', encoding='utf-8') as f:
    gpu_mapping = json.load(f)

cpu_mapping = {}

for agent, data in gpu_mapping.items():
    models = data.get('models', [])
    # Find Claude 3 models by id
    has_claude3 = any(m.get('model') == claude3_id for m in models)
    if has_claude3:
        # Copy agent to CPU mapping, but only with Claude 3 models
        cpu_models = [m for m in models if m.get('model') == claude3_id]
        if cpu_models:
            cpu_mapping[agent] = {k: v for k, v in data.items() if k != 'models'}
            cpu_mapping[agent]['models'] = cpu_models
        # Remove Claude 3 from GPU mapping
        data['models'] = [m for m in models if m.get('model') != claude3_id]

# Save updated mappings
with open(CPU_MAPPING_PATH, 'w', encoding='utf-8') as f:
    json.dump(cpu_mapping, f, indent=2)
with open(GPU_MAPPING_PATH, 'w', encoding='utf-8') as f:
    json.dump(gpu_mapping, f, indent=2)

_zyg_log.info(f'Moved {len(cpu_mapping)} agents using Claude 3 to CPU mapping.')
