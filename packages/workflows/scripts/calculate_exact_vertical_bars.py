#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Calculate Exact Vertical Bars Needed for Agent-Model Mapping
This script analyzes the current agent-model mappings to determine the exact
number of vertical bars needed for the dashboard visualization.
"""

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def load_agent_model_mapping():
    """Load the agent-model mapping from the Python file"""
    # Import the mapping from the existing file
    import sys
    import os

    sys.path.append(os.path.dirname(os.path.abspath(__file__)))

    from zyg_workflows.ai_model_agent_mapping import model_to_agents, agent_to_models

    return model_to_agents, agent_to_models


def calculate_vertical_bars():
    """Calculate the exact number of vertical bars needed"""
    model_to_agents, agent_to_models = load_agent_model_mapping()

    # Calculate total vertical bars (each agent-model combination = 1 bar)
    total_bars = 0
    model_usage_count = {}
    agent_model_count = {}

    _zyg_log.info('=== EXACT VERTICAL BARS CALCULATION ===\n')

    # Count bars per model
    _zyg_log.info('📊 VERTICAL BARS PER AI MODEL:')
    _zyg_log.info('-' * 50)

    for model, agents in model_to_agents.items():
        bar_count = len(agents)
        total_bars += bar_count
        model_usage_count[model] = bar_count
        _zyg_log.info(f'{model}: {bar_count} bars')

    _zyg_log.info(f'\n📈 TOTAL VERTICAL BARS: {total_bars}')

    # Count models per agent
    _zyg_log.info('\n🤖 MODELS PER AGENT:')
    _zyg_log.info('-' * 50)

    for agent, models in agent_to_models.items():
        model_count = len(models)
        agent_model_count[agent] = model_count
        _zyg_log.info(f'{agent}: {model_count} models')

    # Statistics
    _zyg_log.info('\n📊 STATISTICS:')
    _zyg_log.info('-' * 50)
    _zyg_log.info(f'Total AI Models: {len(model_to_agents)}')
    _zyg_log.info(f'Total Agents: {len(agent_to_models)}')
    _zyg_log.info(f'Total Vertical Bars: {total_bars}')
    _zyg_log.info(f'Average Models per Agent: {total_bars / len(agent_to_models):.2f}')
    _zyg_log.info(f'Average Agents per Model: {total_bars / len(model_to_agents):.2f}')

    # Models with 7+ agents
    models_with_7_plus = {model: count for model, count in model_usage_count.items() if count >= 7}
    _zyg_log.info(f'\n🎯 MODELS USED BY 7+ AGENTS ({len(models_with_7_plus)} models):')
    _zyg_log.info('-' * 50)
    for model, count in sorted(models_with_7_plus.items(), key=lambda x: x[1], reverse=True):
        _zyg_log.info(f'{model}: {count} agents')

    # Models with fewer than 7 agents
    models_with_fewer_than_7 = {model: count for model, count in model_usage_count.items() if count < 7}
    _zyg_log.info(f'\n⚠️  MODELS USED BY <7 AGENTS ({len(models_with_fewer_than_7)} models):')
    _zyg_log.info('-' * 50)
    for model, count in sorted(models_with_fewer_than_7.items(), key=lambda x: x[1], reverse=True):
        _zyg_log.info(f'{model}: {count} agents')

    # Agents with most models
    top_agents = sorted(agent_model_count.items(), key=lambda x: x[1], reverse=True)[:10]
    _zyg_log.info('\n🏆 TOP 10 AGENTS BY MODEL COUNT:')
    _zyg_log.info('-' * 50)
    for agent, count in top_agents:
        _zyg_log.info(f'{agent}: {count} models')

    # Agents with fewest models
    bottom_agents = sorted(agent_model_count.items(), key=lambda x: x[1])[:10]
    _zyg_log.info('\n📉 BOTTOM 10 AGENTS BY MODEL COUNT:')
    _zyg_log.info('-' * 50)
    for agent, count in bottom_agents:
        _zyg_log.info(f'{agent}: {count} models')

    return total_bars, model_usage_count, agent_model_count


def compare_with_expected():
    """Compare current bars with expected ranges"""
    total_bars, model_usage_count, agent_model_count = calculate_vertical_bars()

    _zyg_log.info('\n🔍 COMPARISON WITH EXPECTED RANGES:')
    _zyg_log.info('-' * 50)

    # Expected calculations
    total_agents = len(agent_model_count)
    total_models = len(model_usage_count)

    # Different scenarios
    scenarios = {
        'Conservative (10 models per agent)': total_agents * 10,
        'Moderate (15 models per agent)': total_agents * 15,
        'Aggressive (20 models per agent)': total_agents * 20,
        'Maximum (all models per agent)': total_agents * total_models,
    }

    _zyg_log.info(f'Current System: {total_bars} bars')
    _zyg_log.info(f'Total Agents: {total_agents}')
    _zyg_log.info(f'Total Models: {total_models}')
    _zyg_log.info('')

    for scenario, expected in scenarios.items():
        difference = expected - total_bars
        percentage = (total_bars / expected) * 100 if expected > 0 else 0
        _zyg_log.info(f'{scenario}:')
        _zyg_log.info(f'  Expected: {expected} bars')
        _zyg_log.info(f'  Difference: {difference:+d} bars')
        _zyg_log.info(f'  Current Usage: {percentage:.1f}%')
        _zyg_log.info('')


if __name__ == '__main__':
    calculate_vertical_bars()
    compare_with_expected()
