# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import json
from collections import Counter

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def count_model_usage():
    # Read the JSON file
    with open('agent_model_bar_mapping.json', 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Counter to track model usage
    model_counter = Counter()

    # Count each model usage
    for _agent_name, agent_data in data.items():
        if 'models' in agent_data and isinstance(agent_data['models'], list):
            for model_entry in agent_data['models']:
                if 'model' in model_entry:
                    model_name = model_entry['model']
                    model_counter[model_name] += 1

    # Print results sorted by usage count (highest first)
    _zyg_log.info('Model Usage Count Across All Agents:')
    _zyg_log.info('=' * 50)

    for model, count in model_counter.most_common():
        _zyg_log.info(f'{model}: {count} times')

    _zyg_log.info(f'\nTotal unique models: {len(model_counter)}')
    _zyg_log.info(f'Total model instances: {sum(model_counter.values())}')


if __name__ == '__main__':
    count_model_usage()
