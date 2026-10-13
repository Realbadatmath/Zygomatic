# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import json

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# Define all CPU models (including Claude 3 and others)
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

# Script body guarded: runs only when executed as a script, not when imported.
if __name__ == '__main__':
    # Load the main mapping file
    with open('agent_model_bar_mapping.json', 'r', encoding='utf-8') as f:
        main_mapping = json.load(f)

    # Load existing CPU mapping
    with open('Schedule/cpu_agent_model_bar_mapping.json', 'r', encoding='utf-8') as f:
        cpu_mapping = json.load(f)

    # Add all agents that use any CPU model to the CPU mapping
    for agent, data in main_mapping.items():
        models = data.get('models', [])
        # Find all CPU models for this agent
        cpu_models = [m for m in models if m.get('model') in CPU_MODELS]

        if cpu_models:
            # If agent already exists in CPU mapping, merge models
            if agent in cpu_mapping:
                existing_models = cpu_mapping[agent]['models']
                # Add new CPU models that aren't already there
                existing_model_ids = {m['model'] for m in existing_models}
                for model in cpu_models:
                    if model['model'] not in existing_model_ids:
                        existing_models.append(model)
            else:
                # Add new agent to CPU mapping
                cpu_mapping[agent] = {k: v for k, v in data.items() if k != 'models'}
                cpu_mapping[agent]['models'] = cpu_models

    # Save updated CPU mapping
    with open('Schedule/cpu_agent_model_bar_mapping.json', 'w', encoding='utf-8') as f:
        json.dump(cpu_mapping, f, indent=2)

    _zyg_log.info(f'Updated CPU mapping with {len(cpu_mapping)} agents')

    # Count models in CPU mapping
    cpu_model_ids = set()
    for agent_data in cpu_mapping.values():
        for model in agent_data.get('models', []):
            cpu_model_ids.add(model['model'])

    _zyg_log.info(f'CPU models: {sorted(cpu_model_ids)}')
    _zyg_log.info(f'Number of CPU models: {len(cpu_model_ids)}')

    # Show sample agents
    _zyg_log.info('\nSample CPU agents:')
    for _i, agent in enumerate(list(cpu_mapping.keys())[:5]):
        models = [m['model'] for m in cpu_mapping[agent]['models']]
        _zyg_log.info(f'  {agent}: {models}')
