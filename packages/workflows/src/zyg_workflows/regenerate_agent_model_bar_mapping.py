# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import json

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

CONFIG_PATH = 'crewai_project/agent_configurations.json'
OUTPUT_PATH = 'agent_model_bar_mapping.json'

# Hardcoded exclusion list for CPU models (by name and by ID)
CPU_MODEL_NAMES = set(
    [
        'Claude 3',
        'GPT-4',
        'Llama 3',
        'Mistral Mixtral',
        'HumanEval',
        'Crewai Openagents',
        'LangChain Llamalend',
        'Plotly',
        'FastAPI',
        'AI QC Engine',
        'Whisper',
        'librosa',
        'AssemblyAI',
        'Deepgram',
    ]
)
CPU_MODEL_IDS = set(
    [
        # Add known CPU model IDs here if available, e.g. '1030', '1018', etc.
        # These should be updated to match your actual CPU model IDs if you want to exclude by ID as well
    ]
)


def is_cpu_model(model):
    # Model can be in format 'Name (ID)' or just ID or just Name
    if isinstance(model, dict):
        model_str = model.get('model', '')
    else:
        model_str = str(model)
    # Check for 'Name (ID)' format
    if '(' in model_str and ')' in model_str:
        name_part = model_str.split('(')[0].strip()
        id_part = model_str.split('(')[-1].replace(')', '').strip()
        if name_part in CPU_MODEL_NAMES or id_part in CPU_MODEL_IDS:
            return True
    # Check if the whole string is a CPU model name or ID
    if model_str in CPU_MODEL_NAMES or model_str in CPU_MODEL_IDS:
        return True
    return False


def regenerate_agent_model_bar_mapping():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = json.load(f)
    agents = config['agents']
    mapping = {}
    for agent_name, agent_info in agents.items():
        models = agent_info.get('ai_models', [])
        # Filter out CPU models
        filtered_models = [m for m in models if not is_cpu_model(m)]
        # Each model gets a dummy bar_id for now (can be replaced with real logic)
        mapping[agent_name] = {
            'agent_id': agent_info.get('id', ''),
            'models': [{'model': m, 'bar_id': f'{agent_name}__{m}'} for m in filtered_models],
            'tier': agent_info.get('tier', 0),
        }
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)
    _zyg_log.info(f'✅ agent_model_bar_mapping.json generated with {len(mapping)} agents (CPU models excluded).')


if __name__ == '__main__':
    regenerate_agent_model_bar_mapping()
