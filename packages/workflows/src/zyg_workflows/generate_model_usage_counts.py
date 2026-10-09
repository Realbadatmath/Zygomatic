#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Generate model usage counts for GPU schedule visualization.
This script counts how many times each model appears across all agents
and creates a mapping for the GPU schedule bars.
"""

import json
import os
import re

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def count_model_usage():
    """Count how many times each model is used across all agents"""

    # Load the agent model bar mapping
    mapping_file = 'agent_model_bar_mapping.json'
    if not os.path.exists(mapping_file):
        _zyg_log.info(f'Error: {mapping_file} not found')
        return {}

    with open(mapping_file, 'r', encoding='utf-8') as f:
        agent_mapping = json.load(f)

    # Count model usage
    model_counts = {}

    for _agent_name, agent_data in agent_mapping.items():
        models = agent_data.get('models', [])
        for model_info in models:
            model_id = model_info.get('model')
            if model_id:
                # Extract just the numeric ID if it's in format "Name (ID)"
                if isinstance(model_id, str) and '(' in model_id:
                    # Extract the ID from "Name (ID)" format
                    match = re.search(r'\((\d+)\)', model_id)
                    if match:
                        model_id = match.group(1)
                model_counts[model_id] = model_counts.get(model_id, 0) + 1

    return model_counts


def save_model_counts():
    """Save the model usage counts to a JSON file"""
    model_counts = count_model_usage()

    # Sort by count (descending)
    sorted_counts = dict(sorted(model_counts.items(), key=lambda x: x[1], reverse=True))

    # Save to file
    output_file = 'model_usage_counts.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(sorted_counts, f, indent=2)

    _zyg_log.info(f'Model usage counts saved to {output_file}')
    _zyg_log.info('\nModel usage summary:')
    for model_id, count in sorted_counts.items():
        _zyg_log.info(f'  Model ID {model_id}: {count} bars')

    return sorted_counts


if __name__ == '__main__':
    counts = save_model_counts()
    print(f'\nTotal models: {len(counts)}')
    print(f'Total bars: {sum(counts.values())}')
