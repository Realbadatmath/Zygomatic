#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
List Missing Models from Language Specifications
Show exactly which models are missing from the web GUI mappings
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


def list_missing_models():
    """List all missing models from language specifications"""
    _zyg_log.info('=== MISSING MODELS ANALYSIS ===\n')

    # Extract models from different sources
    bar_mapping_models = extract_models_from_agent_bar_mapping()
    ai_mapping_models = extract_models_from_ai_mapping()
    language_specs_models = extract_models_from_language_specs()

    _zyg_log.info(f'Total models in language specifications: {len(language_specs_models)}')
    _zyg_log.info(f'Total models in agent_bar_mapping.json: {len(bar_mapping_models)}')
    _zyg_log.info(f'Total models in ai_model_agent_mapping.py: {len(ai_mapping_models)}')

    # Find missing models
    missing_from_bar_mapping = language_specs_models - bar_mapping_models
    missing_from_ai_mapping = language_specs_models - ai_mapping_models
    missing_from_both = language_specs_models - bar_mapping_models - ai_mapping_models

    _zyg_log.info(f'\n=== MISSING FROM agent_bar_mapping.json ({len(missing_from_bar_mapping)}) ===')
    for model in sorted(missing_from_bar_mapping):
        _zyg_log.info(f'  ❌ {model}')

    _zyg_log.info(f'\n=== MISSING FROM ai_model_agent_mapping.py ({len(missing_from_ai_mapping)}) ===')
    for model in sorted(missing_from_ai_mapping):
        _zyg_log.info(f'  ❌ {model}')

    _zyg_log.info(f'\n=== MISSING FROM BOTH FILES ({len(missing_from_both)}) ===')
    for model in sorted(missing_from_both):
        _zyg_log.info(f'  ❌ {model}')

    # Check for normalized name matches (same model, different formatting)
    _zyg_log.info('\n=== POTENTIAL NAME FORMATTING DIFFERENCES ===')
    bar_normalized = {normalize_model_name(m): m for m in bar_mapping_models}
    ai_normalized = {normalize_model_name(m): m for m in ai_mapping_models}
    specs_normalized = {normalize_model_name(m): m for m in language_specs_models}

    # Find models that might be the same but with different formatting
    all_normalized = set(bar_normalized.keys()) | set(ai_normalized.keys()) | set(specs_normalized.keys())

    formatting_issues = []
    for norm_name in all_normalized:
        bar_orig = bar_normalized.get(norm_name)
        ai_orig = ai_normalized.get(norm_name)
        specs_orig = specs_normalized.get(norm_name)

        if bar_orig and specs_orig and bar_orig != specs_orig:
            formatting_issues.append((norm_name, bar_orig, specs_orig))
        if ai_orig and specs_orig and ai_orig != specs_orig:
            formatting_issues.append((norm_name, ai_orig, specs_orig))

    if formatting_issues:
        for norm_name, name1, name2 in formatting_issues:
            _zyg_log.info(f"  🔄 '{name1}' vs '{name2}' (normalized: '{norm_name}')")
    else:
        _zyg_log.info('  ✅ No formatting differences found')

    # Summary
    _zyg_log.info('\n=== SUMMARY ===')
    _zyg_log.info(f'Total unique models in language specs: {len(language_specs_models)}')
    _zyg_log.info(f'Models missing from bar mapping: {len(missing_from_bar_mapping)}')
    _zyg_log.info(f'Models missing from ai mapping: {len(missing_from_ai_mapping)}')
    _zyg_log.info(f'Models missing from both: {len(missing_from_both)}')
    _zyg_log.info(f'Name formatting issues: {len(formatting_issues)}')

    if missing_from_both:
        _zyg_log.info('\n=== COMPLETE LIST OF MISSING MODELS ===')
        for i, model in enumerate(sorted(missing_from_both), 1):
            _zyg_log.info(f'{i:2d}. {model}')


if __name__ == '__main__':
    list_missing_models()
