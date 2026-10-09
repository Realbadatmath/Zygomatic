# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import json

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# Load the main mapping file
with open('agent_model_bar_mapping.json', 'r', encoding='utf-8') as f:
    main_mapping = json.load(f)

# Create CPU mapping with only Claude 3 agents
cpu_mapping = {}

for agent, data in main_mapping.items():
    models = data.get('models', [])
    # Find agents that use Claude 3 (model 1017)
    claude_models = [m for m in models if m.get('model') == '1017']
    if claude_models:
        # Add agent to CPU mapping with only Claude 3 models
        cpu_mapping[agent] = {k: v for k, v in data.items() if k != 'models'}
        cpu_mapping[agent]['models'] = claude_models

# Save CPU mapping
with open('Schedule/cpu_agent_model_bar_mapping.json', 'w', encoding='utf-8') as f:
    json.dump(cpu_mapping, f, indent=2)

_zyg_log.info(f'Created CPU mapping with {len(cpu_mapping)} agents using Claude 3')
_zyg_log.info(f'CPU models: {set(m["model"] for agent in cpu_mapping.values() for m in agent.get("models", []))}')

# Show first few agents
_zyg_log.info('\nFirst 5 CPU agents:')
for _i, agent in enumerate(list(cpu_mapping.keys())[:5]):
    _zyg_log.info(f'  {agent}')
