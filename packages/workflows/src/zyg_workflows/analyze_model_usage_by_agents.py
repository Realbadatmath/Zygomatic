#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Analyze AI Model Usage by Agents
This script will:
1. Analyze the correct model_to_agents mapping
2. Identify which models should be used by 7+ agents
3. Compare with current usage
4. Generate recommendations
"""

import json

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def load_correct_mapping():
    """Load the correct model_to_agents mapping from ai_model_agent_mapping.py"""
    try:
        from zyg_workflows import ai_model_agent_mapping

        return ai_model_agent_mapping.model_to_agents
    except ImportError:
        _zyg_log.info('Error: Could not import ai_model_agent_mapping')
        return {}


def load_current_agent_configs():
    """Load current agent configurations"""
    try:
        with open('agent_configurations.json', 'r') as f:
            return json.load(f)
    except Exception as e:
        _zyg_log.info(f'Error loading agent_configurations.json: {e}')
        return None


def analyze_model_usage():
    """Analyze which models should be used by 7+ agents"""
    _zyg_log.info('=== AI MODEL USAGE ANALYSIS ===')

    # Load correct mapping
    correct_mapping = load_correct_mapping()
    if not correct_mapping:
        return

    # Load current configs
    current_configs = load_current_agent_configs()
    if not current_configs:
        return

    current_agents = current_configs.get('agents', {})

    _zyg_log.info(f'Total agents in system: {len(current_agents)}')
    _zyg_log.info(f'Total models in correct mapping: {len(correct_mapping)}')

    # Analyze correct mapping
    model_usage = {}
    for model, agents in correct_mapping.items():
        model_usage[model] = len(agents)

    # Sort by usage
    sorted_usage = sorted(model_usage.items(), key=lambda x: x[1], reverse=True)

    _zyg_log.info('\n📊 CORRECT MODEL USAGE (from ai_model_agent_mapping.py):')
    _zyg_log.info(f'{"Model":<30} {"Agents":<8} {"7+ Agents":<10}')
    _zyg_log.info('-' * 50)

    models_with_7_plus = []
    models_under_7 = []

    for model, count in sorted_usage:
        status = '✅ YES' if count >= 7 else '❌ NO'
        _zyg_log.info(f'{model:<30} {count:<8} {status:<10}')

        if count >= 7:
            models_with_7_plus.append((model, count))
        else:
            models_under_7.append((model, count))

    _zyg_log.info('\n🎯 SUMMARY:')
    _zyg_log.info(f'Models used by 7+ agents: {len(models_with_7_plus)}')
    _zyg_log.info(f'Models used by <7 agents: {len(models_under_7)}')

    _zyg_log.info(f'\n✅ MODELS WITH 7+ AGENTS ({len(models_with_7_plus)}):')
    for model, count in models_with_7_plus:
        _zyg_log.info(f'  {model}: {count} agents')

    _zyg_log.info(f'\n❌ MODELS WITH <7 AGENTS ({len(models_under_7)}):')
    for model, count in models_under_7:
        _zyg_log.info(f'  {model}: {count} agents')

    # Analyze current vs correct
    _zyg_log.info('\n🔄 CURRENT VS CORRECT MAPPING:')

    current_model_usage = {}
    for _agent_name, config in current_agents.items():
        ai_models = config.get('ai_models', [])
        for model in ai_models:
            current_model_usage[model] = current_model_usage.get(model, 0) + 1

    _zyg_log.info(f'Current models in use: {len(current_model_usage)}')
    _zyg_log.info(f'Correct models defined: {len(correct_mapping)}')

    # Find missing models
    missing_models = set(correct_mapping.keys()) - set(current_model_usage.keys())
    extra_models = set(current_model_usage.keys()) - set(correct_mapping.keys())

    if missing_models:
        _zyg_log.info('\n⚠️  MISSING MODELS (not in current config):')
        for model in sorted(missing_models):
            correct_count = correct_mapping.get(model, [])
            _zyg_log.info(f'  {model}: should be used by {len(correct_count)} agents')

    if extra_models:
        _zyg_log.info('\n⚠️  EXTRA MODELS (not in correct mapping):')
        for model in sorted(extra_models):
            current_count = current_model_usage.get(model, 0)
            _zyg_log.info(f'  {model}: currently used by {current_count} agents')

    # Calculate vertical bars
    correct_total_bars = sum(len(agents) for agents in correct_mapping.values())
    current_total_bars = sum(current_model_usage.values())

    _zyg_log.info('\n📈 VERTICAL BARS CALCULATION:')
    _zyg_log.info(f'Correct mapping total bars: {correct_total_bars}')
    _zyg_log.info(f'Current mapping total bars: {current_total_bars}')
    _zyg_log.info(f'Difference: {correct_total_bars - current_total_bars}')

    return {
        'correct_mapping': correct_mapping,
        'current_usage': current_model_usage,
        'models_with_7_plus': models_with_7_plus,
        'models_under_7': models_under_7,
        'correct_total_bars': correct_total_bars,
        'current_total_bars': current_total_bars,
    }


def generate_recommendations(results):
    """Generate recommendations based on analysis"""
    _zyg_log.info('\n🎯 RECOMMENDATIONS:')

    if results['correct_total_bars'] > results['current_total_bars']:
        missing_bars = results['correct_total_bars'] - results['current_total_bars']
        _zyg_log.info(f'  ⚠️  Missing {missing_bars} vertical bars')
        _zyg_log.info('  💡 Need to add missing model assignments to agents')

    models_with_7_plus = results['models_with_7_plus']
    _zyg_log.info(f'\n  ✅ These {len(models_with_7_plus)} models should be used by 7+ agents:')
    for model, count in models_with_7_plus:
        _zyg_log.info(f'    - {model}: {count} agents')

    models_under_7 = results['models_under_7']
    _zyg_log.info(f'\n  ❌ These {len(models_under_7)} models are used by <7 agents:')
    for model, count in models_under_7:
        _zyg_log.info(f'    - {model}: {count} agents')

    _zyg_log.info('\n🔧 ACTION ITEMS:')
    _zyg_log.info('  1. Update agent configurations to match correct mapping')
    _zyg_log.info('  2. Add missing model assignments')
    _zyg_log.info('  3. Remove incorrect model assignments')
    _zyg_log.info('  4. Ensure all models used by 7+ agents are properly assigned')


def main():
    """Main analysis function"""
    print('Analyzing AI Model Usage by Agents...')
    results = analyze_model_usage()

    if results:
        generate_recommendations(results)

        print('\n🎯 FINAL ANSWER:')
        print(
            f'  According to the correct mapping, {len(results["models_with_7_plus"])} models should be used by 7+ agents'
        )
        print(f'  Total vertical bars needed: {results["correct_total_bars"]}')
        print(f'  Current vertical bars: {results["current_total_bars"]}')


if __name__ == '__main__':
    main()
