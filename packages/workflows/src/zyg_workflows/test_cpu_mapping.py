#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Test script to verify CPU agent model bar mapping
"""

import requests
from zyg_workflows import paths

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def test_cpu_agent_model_bar_mapping():
    """Test the CPU agent model bar mapping endpoint"""

    _zyg_log.info('=== Testing CPU Agent Model Bar Mapping ===')

    try:
        # Test the CPU agent model bar mapping endpoint
        response = requests.get(paths.ZYG_DASHBOARD_URL + '/api/cpu/agent_model_bar_mapping', timeout=30)

        if response.status_code == 200:
            data = response.json()
            _zyg_log.info('✅ CPU Agent Model Bar Mapping loaded successfully')
            _zyg_log.info(f'📊 Number of agents: {len(data)}')

            # Show first few agents
            _zyg_log.info('\n📋 First 5 CPU agents:')
            for i, (agent_name, agent_data) in enumerate(list(data.items())[:5]):
                models = agent_data.get('models', [])
                model_names = [m.get('model', 'Unknown') for m in models]
                _zyg_log.info(f'  {i + 1}. {agent_name}: {model_names}')

            # Check if it's different from GPU mapping
            gpu_response = requests.get(paths.ZYG_DASHBOARD_URL + '/api/agent_model_bar_mapping', timeout=30)
            if gpu_response.status_code == 200:
                gpu_data = gpu_response.json()
                _zyg_log.info(f'\n📊 GPU mapping has {len(gpu_data)} agents')
                _zyg_log.info(f'📊 CPU mapping has {len(data)} agents')

                if len(data) != len(gpu_data):
                    _zyg_log.info('✅ CPU and GPU mappings have different numbers of agents - this is correct!')
                else:
                    _zyg_log.info('⚠️  CPU and GPU mappings have the same number of agents - this might be wrong')

                # Check for CPU-specific agents
                cpu_agents = ['CEO-Agent', 'CTO-Agent', 'Affiliate-Marketing-Overseer']
                found_cpu_agents = [agent for agent in cpu_agents if agent in data]
                _zyg_log.info(f'\n🔍 CPU-specific agents found: {found_cpu_agents}')

                if found_cpu_agents:
                    _zyg_log.info('✅ CPU-specific agents are present in the mapping')
                else:
                    _zyg_log.info('❌ CPU-specific agents are missing from the mapping')

        else:
            _zyg_log.info(f'❌ Failed to load CPU agent model bar mapping: {response.status_code}')
            _zyg_log.info(f'Response: {response.text}')

    except requests.exceptions.ConnectionError:
        _zyg_log.info('❌ Could not connect to the server. Make sure the Flask app is running.')
    except Exception as e:
        _zyg_log.info(f'❌ Error testing CPU agent model bar mapping: {e}')


def test_cpu_canonical_models():
    """Test the CPU canonical models endpoint"""

    _zyg_log.info('\n=== Testing CPU Canonical Models ===')

    try:
        response = requests.get(paths.ZYG_DASHBOARD_URL + '/api/canonical_cpu_models', timeout=30)

        if response.status_code == 200:
            data = response.json()
            models = data.get('models', [])
            _zyg_log.info('✅ CPU Canonical Models loaded successfully')
            _zyg_log.info(f'📊 Number of CPU models: {len(models)}')
            _zyg_log.info(f'📋 CPU models: {models[:10]}...')  # Show first 10

        else:
            _zyg_log.info(f'❌ Failed to load CPU canonical models: {response.status_code}')

    except requests.exceptions.ConnectionError:
        _zyg_log.info('❌ Could not connect to the server. Make sure the Flask app is running.')
    except Exception as e:
        _zyg_log.info(f'❌ Error testing CPU canonical models: {e}')


if __name__ == '__main__':
    test_cpu_agent_model_bar_mapping()
    test_cpu_canonical_models()
