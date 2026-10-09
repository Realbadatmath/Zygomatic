# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import requests
from zyg_workflows import paths

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def test_cpu_api():
    try:
        response = requests.get(paths.ZYG_DASHBOARD_URL + '/api/cpu/agent_model_bar_mapping', timeout=30)
        if response.status_code == 200:
            data = response.json()
            _zyg_log.info(f'CPU API returned {len(data)} agents')

            # Count unique models
            models = set()
            for agent_data in data.values():
                for model in agent_data.get('models', []):
                    models.add(model['model'])

            _zyg_log.info(f'CPU API has {len(models)} unique models: {sorted(models)}')

            # Show first few agents as example
            _zyg_log.info('\nFirst 5 agents:')
            for i, (agent_name, agent_data) in enumerate(data.items()):
                if i >= 5:
                    break
                models_str = ', '.join([m['model'] for m in agent_data.get('models', [])])
                _zyg_log.info(f'  {agent_name}: {models_str}')

        else:
            _zyg_log.info(f'Error: {response.status_code}')
    except Exception as e:
        _zyg_log.info(f'Error: {e}')


if __name__ == '__main__':
    test_cpu_api()
