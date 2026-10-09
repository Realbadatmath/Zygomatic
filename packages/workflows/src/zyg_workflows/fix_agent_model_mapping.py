# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import ast
import json
import re

CONFIG_PATH = 'agent_configurations.json'
MAPPING_PATH = 'ai_model_agent_mapping.py'


# Load agent configurations
def load_agent_configs():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = json.load(f)
    agents = config['agents']
    agent_to_models = {k: set(v.get('ai_models', [])) for k, v in agents.items()}
    return agent_to_models


# Load model_to_agents mapping from Python file
def load_model_to_agents():
    with open(MAPPING_PATH, 'r', encoding='utf-8') as f:
        content = f.read()
    # Extract the model_to_agents dict using regex
    match = re.search(r'model_to_agents\s*=\s*{(.+?)}\s*# Build agent_to_models', content, re.DOTALL)
    if not match:
        match = re.search(r'model_to_agents\s*=\s*{(.+?)}\n}\n', content, re.DOTALL)
    if not match:
        raise ValueError('Could not find model_to_agents in mapping file')
    dict_str = '{' + match.group(1) + '}'
    model_to_agents = ast.literal_eval(dict_str)
    return model_to_agents, content


# Save updated mapping
def save_model_to_agents(model_to_agents, original_content):
    # Rebuild the model_to_agents string
    mapping_str = 'model_to_agents = {\n'
    for model, agents in model_to_agents.items():
        mapping_str += f'    "{model}": [\n'
        for agent in sorted(agents):
            mapping_str += f'        "{agent}",\n'
        mapping_str += '    ],\n'
    mapping_str += '}\n'
    # Replace the old mapping in the file
    new_content = re.sub(
        r'model_to_agents\s*=\s*{(.+?)}\s*# Build agent_to_models',
        mapping_str + '# Build agent_to_models',
        original_content,
        flags=re.DOTALL,
    )
    if new_content == original_content:
        # Try alternate ending
        new_content = re.sub(
            r'model_to_agents\s*=\s*{(.+?)}\n}\n', mapping_str + '}\n', original_content, flags=re.DOTALL
        )
    with open(MAPPING_PATH, 'w', encoding='utf-8') as f:
        f.write(new_content)


if __name__ == '__main__':
    print('🔍 Checking and fixing agent ↔ model mapping...')
    agent_to_models = load_agent_configs()
    model_to_agents, original_content = load_model_to_agents()
    # Build new model_to_agents from config
    new_model_to_agents = {}
    for agent, models in agent_to_models.items():
        for model in models:
            new_model_to_agents.setdefault(model, set()).add(agent)
    # Preserve any models that exist in mapping but not in config (with only valid agents)
    for model, agents in model_to_agents.items():
        for agent in agents:
            if agent in agent_to_models and model in agent_to_models[agent]:
                new_model_to_agents.setdefault(model, set()).add(agent)
    save_model_to_agents(new_model_to_agents, original_content)
    print('✅ Mapping fixed. Each agent now only mapped to their configured AI models.')
