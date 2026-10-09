#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Analyze AI Model Mapping Discrepancies
Compare model mappings across different configuration files
"""

import json
import os

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def load_json_file(filepath):
    """Load and return JSON data from file"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        _zyg_log.info(f'Error loading {filepath}: {e}')
        return None


def extract_models_from_agent_bar_mapping():
    """Extract models from agent_bar_mapping.json"""
    mapping_path = os.path.join('Schedule', 'agent_bar_mapping.json')
    data = load_json_file(mapping_path)
    if not data:
        return set()

    models = set()
    for agent_data in data.values():
        for model_info in agent_data.get('models', []):
            models.add(model_info.get('model', ''))
    return models


def extract_models_from_ai_mapping():
    """Extract models from ai_model_agent_mapping.py"""
    try:
        from zyg_workflows import ai_model_agent_mapping

        cpu_models = set(ai_model_agent_mapping.CPU_MODELS)
        gpu_models = set(ai_model_agent_mapping.GPU_MODELS)
        return cpu_models.union(gpu_models)
    except Exception as e:
        _zyg_log.info(f'Error loading ai_model_agent_mapping.py: {e}')
        return set()


def extract_models_from_language_specs():
    """Extract models from 8_LANGUAGE_AGENT_SPECIFICATIONS.json"""
    specs_path = os.environ.get(
        'LANGUAGE_SPECS_PATH', os.path.join(os.path.dirname(__file__), '8_LANGUAGE_AGENT_SPECIFICATIONS.json')
    )
    data = load_json_file(specs_path)
    if not data:
        return set()

    models = set()
    for category in data.values():
        if isinstance(category, dict):
            # Check all agent categories
            for agent_category in [
                'localization_agents',
                'voice_synthesis_agents',
                'marketing_agents',
                'quality_control_agents',
            ]:
                for agent in category.get(agent_category, {}).values():
                    models.update(agent.get('ai_models', []))
                    models.update(agent.get('gpu_models', []))
    return models


def normalize_model_name(name):
    """Normalize model names for comparison"""
    if not name:
        return ''
    # Remove underscores, dashes, spaces, dots, and lowercase everything
    return ''.join(e for e in name if e.isalnum()).lower()


def analyze_mappings():
    """Analyze all model mappings and report discrepancies"""
    _zyg_log.info('=== AI Model Mapping Analysis ===\n')

    # Extract models from different sources
    bar_mapping_models = extract_models_from_agent_bar_mapping()
    ai_mapping_models = extract_models_from_ai_mapping()
    language_specs_models = extract_models_from_language_specs()

    _zyg_log.info(f'Models in agent_bar_mapping.json: {len(bar_mapping_models)}')
    _zyg_log.info(f'Models in ai_model_agent_mapping.py: {len(ai_mapping_models)}')
    _zyg_log.info(f'Models in 8_LANGUAGE_AGENT_SPECIFICATIONS.json: {len(language_specs_models)}')

    _zyg_log.info('\n=== Model Lists ===')
    _zyg_log.info('\nagent_bar_mapping.json models:')
    for model in sorted(bar_mapping_models):
        _zyg_log.info(f'  {model}')

    _zyg_log.info('\nai_model_agent_mapping.py models:')
    for model in sorted(ai_mapping_models):
        _zyg_log.info(f'  {model}')

    _zyg_log.info('\n8_LANGUAGE_AGENT_SPECIFICATIONS.json models:')
    for model in sorted(language_specs_models):
        _zyg_log.info(f'  {model}')

    # Find discrepancies
    _zyg_log.info('\n=== Discrepancies ===')

    # Models in bar_mapping but not in ai_mapping
    missing_in_ai_mapping = bar_mapping_models - ai_mapping_models
    if missing_in_ai_mapping:
        _zyg_log.info(
            f'\nModels in agent_bar_mapping.json but NOT in ai_model_agent_mapping.py ({len(missing_in_ai_mapping)}):'
        )
        for model in sorted(missing_in_ai_mapping):
            _zyg_log.info(f'  {model}')

    # Models in ai_mapping but not in bar_mapping
    missing_in_bar_mapping = ai_mapping_models - bar_mapping_models
    if missing_in_bar_mapping:
        _zyg_log.info(
            f'\nModels in ai_model_agent_mapping.py but NOT in agent_bar_mapping.json ({len(missing_in_bar_mapping)}):'
        )
        for model in sorted(missing_in_bar_mapping):
            _zyg_log.info(f'  {model}')

    # Models in language_specs but not in either mapping
    missing_in_both_mappings = language_specs_models - bar_mapping_models - ai_mapping_models
    if missing_in_both_mappings:
        _zyg_log.info(
            f'\nModels in 8_LANGUAGE_AGENT_SPECIFICATIONS.json but NOT in either mapping ({len(missing_in_both_mappings)}):'
        )
        for model in sorted(missing_in_both_mappings):
            _zyg_log.info(f'  {model}')

    # Check for normalized name matches
    _zyg_log.info('\n=== Normalized Name Analysis ===')
    bar_normalized = {normalize_model_name(m): m for m in bar_mapping_models}
    ai_normalized = {normalize_model_name(m): m for m in ai_mapping_models}
    specs_normalized = {normalize_model_name(m): m for m in language_specs_models}

    # Find models that might be the same but with different formatting
    all_normalized = set(bar_normalized.keys()) | set(ai_normalized.keys()) | set(specs_normalized.keys())

    potential_matches = []
    for norm_name in all_normalized:
        bar_orig = bar_normalized.get(norm_name)
        ai_orig = ai_normalized.get(norm_name)
        specs_orig = specs_normalized.get(norm_name)

        if bar_orig and ai_orig and bar_orig != ai_orig:
            potential_matches.append((norm_name, bar_orig, ai_orig))
        if bar_orig and specs_orig and bar_orig != specs_orig:
            potential_matches.append((norm_name, bar_orig, specs_orig))
        if ai_orig and specs_orig and ai_orig != specs_orig:
            potential_matches.append((norm_name, ai_orig, specs_orig))

    if potential_matches:
        _zyg_log.info(f'\nPotential name formatting differences ({len(potential_matches)}):')
        for norm_name, name1, name2 in potential_matches:
            _zyg_log.info(f"  Normalized: '{norm_name}' -> '{name1}' vs '{name2}'")

    _zyg_log.info('\n=== Recommendations ===')
    if missing_in_ai_mapping:
        _zyg_log.info('1. Add missing models to ai_model_agent_mapping.py')
    if missing_in_bar_mapping:
        _zyg_log.info('2. Add missing models to agent_bar_mapping.json')
    if missing_in_both_mappings:
        _zyg_log.info('3. Consider adding language specification models to both mappings')
    if potential_matches:
        _zyg_log.info('4. Standardize model name formatting across all files')


if __name__ == '__main__':
    analyze_mappings()
