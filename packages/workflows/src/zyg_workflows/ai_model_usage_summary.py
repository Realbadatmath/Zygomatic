#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
AI Model Usage Summary Generator
Generates a comprehensive summary of all AI models and agent usage
"""

import os

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def load_ai_model_mapping():
    """Load the AI model to agent mapping"""
    mapping_path = os.path.join(os.path.dirname(__file__), 'ai_model_agent_mapping.py')
    import importlib.util

    spec = importlib.util.spec_from_file_location('ai_model_agent_mapping', mapping_path)
    ai_model_agent_mapping = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ai_model_agent_mapping)
    return ai_model_agent_mapping.model_to_agents, ai_model_agent_mapping.CPU_MODELS, ai_model_agent_mapping.GPU_MODELS


def generate_summary():
    """Generate comprehensive AI model usage summary"""
    model_to_agents, cpu_models, gpu_models = load_ai_model_mapping()

    _zyg_log.info('=' * 80)
    _zyg_log.info('COMPREHENSIVE AI MODEL USAGE SUMMARY')
    _zyg_log.info('=' * 80)
    _zyg_log.info('')

    # Sort models by number of agents (descending)
    sorted_models = sorted(model_to_agents.items(), key=lambda x: len(x[1]), reverse=True)

    _zyg_log.info('AI MODEL USAGE BY AGENT COUNT:')
    _zyg_log.info('-' * 50)

    for model, agents in sorted_models:
        model_type = 'CPU' if model in cpu_models else 'GPU'
        _zyg_log.info(f'{model:<30} | {len(agents):>3} agents | {model_type}')

    _zyg_log.info('')
    _zyg_log.info('=' * 80)
    _zyg_log.info('DETAILED BREAKDOWN BY MODEL TYPE')
    _zyg_log.info('=' * 80)

    # CPU Models
    _zyg_log.info('\nCPU MODELS:')
    _zyg_log.info('-' * 30)
    cpu_sorted = [(model, agents) for model, agents in sorted_models if model in cpu_models]
    for model, agents in cpu_sorted:
        _zyg_log.info(f'{model:<30} | {len(agents):>3} agents')

    # GPU Models
    _zyg_log.info('\nGPU MODELS:')
    _zyg_log.info('-' * 30)
    gpu_sorted = [(model, agents) for model, agents in sorted_models if model in gpu_models]
    for model, agents in gpu_sorted:
        _zyg_log.info(f'{model:<30} | {len(agents):>3} agents')

    _zyg_log.info('')
    _zyg_log.info('=' * 80)
    _zyg_log.info('STATISTICS')
    _zyg_log.info('=' * 80)

    total_models = len(model_to_agents)
    total_cpu_models = len(cpu_models)
    total_gpu_models = len(gpu_models)

    # Count total unique agents
    all_agents = set()
    for agents in model_to_agents.values():
        all_agents.update(agents)

    _zyg_log.info(f'Total AI Models: {total_models}')
    _zyg_log.info(f'CPU Models: {total_cpu_models}')
    _zyg_log.info(f'GPU Models: {total_gpu_models}')
    _zyg_log.info(f'Total Unique Agents: {len(all_agents)}')
    _zyg_log.info('')

    # Top 5 most used models
    _zyg_log.info('TOP 5 MOST USED MODELS:')
    _zyg_log.info('-' * 30)
    for i, (model, agents) in enumerate(sorted_models[:5], 1):
        _zyg_log.info(f'{i}. {model}: {len(agents)} agents')

    _zyg_log.info('')
    _zyg_log.info('=' * 80)
    _zyg_log.info('COMPLETE AGENT LIST FOR EACH MODEL')
    _zyg_log.info('=' * 80)

    for model, agents in sorted_models:
        _zyg_log.info(f'\n{model} ({len(agents)} agents):')
        _zyg_log.info('-' * (len(model) + 15))
        for agent in sorted(agents):
            _zyg_log.info(f'  - {agent}')


if __name__ == '__main__':
    generate_summary()
