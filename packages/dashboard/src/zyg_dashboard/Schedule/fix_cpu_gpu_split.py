# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import json

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# Define which models should be CPU-only (Claude 3 and a few others)
CPU_ONLY_MODELS = {'1030'}  # Claude 3

# Define which models should be GPU-only (most of the current CPU models)
GPU_ONLY_MODELS = {
    '1007',
    '1008',
    '1014',
    '1015',
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

# Remove Claude 3 from GPU models since it should be CPU-only
GPU_ONLY_MODELS.discard('1030')

_zyg_log.info(' '.join(str(a) for a in ('CPU-only models:', CPU_ONLY_MODELS)))
_zyg_log.info(' '.join(str(a) for a in ('GPU-only models:', sorted(GPU_ONLY_MODELS))))

# Load current mappings
with open('Schedule/cpu_agent_model_bar_mapping.json', 'r', encoding='utf-8') as f:
    cpu_mapping = json.load(f)

with open('Schedule/agent_model_bar_mapping.json', 'r', encoding='utf-8') as f:
    gpu_mapping = json.load(f)

# Create new mappings
new_cpu_mapping = {}
new_gpu_mapping = {}

# Process all agents
all_agents = set(cpu_mapping.keys()) | set(gpu_mapping.keys())

for agent in all_agents:
    # Get agent data from either mapping
    agent_data = cpu_mapping.get(agent, gpu_mapping.get(agent, {}))
    if not agent_data:
        continue

    # Split models based on CPU/GPU classification
    cpu_models = []
    gpu_models = []

    for model in agent_data.get('models', []):
        model_id = model['model']
        if model_id in CPU_ONLY_MODELS:
            cpu_models.append(model)
        elif model_id in GPU_ONLY_MODELS:
            gpu_models.append(model)
        else:
            # For models not explicitly classified, keep them where they are
            if agent in cpu_mapping:
                cpu_models.append(model)
            else:
                gpu_models.append(model)

    # Add to appropriate mapping if it has models
    if cpu_models:
        new_cpu_mapping[agent] = {k: v for k, v in agent_data.items() if k != 'models'}
        new_cpu_mapping[agent]['models'] = cpu_models

    if gpu_models:
        new_gpu_mapping[agent] = {k: v for k, v in agent_data.items() if k != 'models'}
        new_gpu_mapping[agent]['models'] = gpu_models

# Save updated mappings
with open('Schedule/cpu_agent_model_bar_mapping.json', 'w', encoding='utf-8') as f:
    json.dump(new_cpu_mapping, f, indent=2)

with open('Schedule/agent_model_bar_mapping.json', 'w', encoding='utf-8') as f:
    json.dump(new_gpu_mapping, f, indent=2)

_zyg_log.info(f'Updated CPU mapping: {len(new_cpu_mapping)} agents')
_zyg_log.info(f'Updated GPU mapping: {len(new_gpu_mapping)} agents')

# Show which models are in each mapping
cpu_models = set()
gpu_models = set()

for agent_data in new_cpu_mapping.values():
    for model in agent_data.get('models', []):
        cpu_models.add(model['model'])

for agent_data in new_gpu_mapping.values():
    for model in agent_data.get('models', []):
        gpu_models.add(model['model'])

_zyg_log.info(f'CPU models: {sorted(cpu_models)}')
_zyg_log.info(f'GPU models: {sorted(gpu_models)}')
