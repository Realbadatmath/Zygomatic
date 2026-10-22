#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Count AI Models from JSON Data
This script analyzes the provided JSON data to count how many times each AI model appears.
"""

from collections import defaultdict

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def count_ai_models_from_json(json_data):
    """Count occurrences of each AI model in the JSON data"""

    model_counts = defaultdict(int)

    # Function to recursively search through the JSON structure
    def search_for_models(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == 'ai_models' and isinstance(value, list):
                    for model in value:
                        model_counts[model] += 1
                elif key == 'gpu_models' and isinstance(value, list):
                    for model in value:
                        model_counts[model] += 1
                else:
                    search_for_models(value)
        elif isinstance(obj, list):
            for item in obj:
                search_for_models(item)

    # Search through the entire JSON structure
    search_for_models(json_data)

    return model_counts


def analyze_json_data():
    """Analyze the provided JSON data"""

    # The JSON data you provided (truncated for brevity, but contains the structure)
    json_data = {
        'empire_overview': {
            'total_businesses': 8,
            'total_agents': 79,
            'gpu_setup': '3× RTX 4090 D 48GB (144GB total VRAM)',
            'cpu_setup': 'Threadripper PRO 7960X (96 cores/192 threads)',
            'storage': '5× Samsung 990 Pro 2TB (10TB total)',
        },
        'business_verticals': {
            'affiliate_marketing': {
                'description': 'Affiliate Marketing Business',
                'agent_count': 12,
                'gpu_usage': 'LIGHT',
                'agents': {
                    'Affiliate-Marketing-Overseer': {
                        'role': 'Affiliate Marketing Director - Strategy and oversight',
                        'tier': 4,
                        'ai_models': [
                            'Claude_3',
                            'GPT-4',
                            'LLaMA_3',
                            'Mistral___Mixtral',
                            'Plotly',
                            'FastAPI',
                            'AI_QC_Engine',
                        ],
                        'gpu_models': ['Stable_Diffusion_1.5___XL', 'DreamShaper___RealisticVision'],
                        'reasoning': 'Manages affiliate marketing strategy with visual content oversight',
                    },
                    'Affiliate-Marketing-Agent': {
                        'role': 'Affiliate Marketing Specialist - Campaign management',
                        'tier': 2,
                        'ai_models': [
                            'Claude_3',
                            'GPT-4',
                            'LLaMA_3',
                            'Mistral___Mixtral',
                            'Plotly',
                            'FastAPI',
                            'AI_QC_Engine',
                        ],
                        'gpu_models': ['Stable_Diffusion_1.5___XL', 'DreamShaper___RealisticVision'],
                        'reasoning': 'Manages affiliate campaigns with visual content creation',
                    },
                    'Campaign-Builder-Agent': {
                        'role': 'Campaign Builder - Marketing campaign creation',
                        'tier': 2,
                        'ai_models': [
                            'Claude_3',
                            'GPT-4',
                            'LLaMA_3',
                            'Mistral___Mixtral',
                            'Plotly',
                            'FastAPI',
                            'AI_QC_Engine',
                        ],
                        'gpu_models': ['Stable_Diffusion_1.5___XL', 'DreamShaper___RealisticVision'],
                        'reasoning': 'Creates marketing campaigns with visual assets',
                    },
                    'SEO-Agent': {
                        'role': 'SEO Specialist - Search engine optimization',
                        'tier': 2,
                        'ai_models': [
                            'Claude_3',
                            'GPT-4',
                            'LLaMA_3',
                            'Mistral___Mixtral',
                            'Plotly',
                            'FastAPI',
                            'AI_QC_Engine',
                        ],
                        'gpu_models': ['Stable_Diffusion_1.5___XL', 'DreamShaper___RealisticVision'],
                        'reasoning': 'Optimizes content for search engines with visual elements',
                    },
                    'Conversion-Optimizer-Agent': {
                        'role': 'Conversion Optimizer - Conversion rate optimization',
                        'tier': 2,
                        'ai_models': [
                            'Claude_3',
                            'GPT-4',
                            'LLaMA_3',
                            'Mistral___Mixtral',
                            'Plotly',
                            'FastAPI',
                            'AI_QC_Engine',
                        ],
                        'gpu_models': ['Stable_Diffusion_1.5___XL', 'DreamShaper___RealisticVision'],
                        'reasoning': 'Optimizes conversion rates with A/B testing and visual content',
                    },
                    'Content-Writer-Agent': {
                        'role': 'Content Writer - Marketing content creation',
                        'tier': 2,
                        'ai_models': [
                            'Claude_3',
                            'GPT-4',
                            'LLaMA_3',
                            'Mistral___Mixtral',
                            'Plotly',
                            'FastAPI',
                            'AI_QC_Engine',
                        ],
                        'gpu_models': ['Stable_Diffusion_1.5___XL', 'DreamShaper___RealisticVision'],
                        'reasoning': 'Creates marketing content with visual assets',
                    },
                    'Email-Marketing-Agent': {
                        'role': 'Email Marketing Specialist - Email campaign management',
                        'tier': 2,
                        'ai_models': [
                            'Claude_3',
                            'GPT-4',
                            'LLaMA_3',
                            'Mistral___Mixtral',
                            'Plotly',
                            'FastAPI',
                            'AI_QC_Engine',
                        ],
                        'gpu_models': ['Stable_Diffusion_1.5___XL', 'DreamShaper___RealisticVision'],
                        'reasoning': 'Manages email campaigns with visual content',
                    },
                    'PPC-Agent': {
                        'role': 'PPC Specialist - Pay-per-click advertising',
                        'tier': 2,
                        'ai_models': [
                            'Claude_3',
                            'GPT-4',
                            'LLaMA_3',
                            'Mistral___Mixtral',
                            'Plotly',
                            'FastAPI',
                            'AI_QC_Engine',
                        ],
                        'gpu_models': ['Stable_Diffusion_1.5___XL', 'DreamShaper___RealisticVision'],
                        'reasoning': 'Manages PPC campaigns with visual ad creation',
                    },
                    'Social-Media-Marketing-Agent': {
                        'role': 'Social Media Marketing Specialist - Social media management',
                        'tier': 2,
                        'ai_models': [
                            'Claude_3',
                            'GPT-4',
                            'LLaMA_3',
                            'Mistral___Mixtral',
                            'Plotly',
                            'FastAPI',
                            'AI_QC_Engine',
                        ],
                        'gpu_models': ['Stable_Diffusion_1.5___XL', 'DreamShaper___RealisticVision'],
                        'reasoning': 'Manages social media with visual content creation',
                    },
                    'Analytics-Reporting-Agent': {
                        'role': 'Analytics Reporter - Marketing analytics and reporting',
                        'tier': 2,
                        'ai_models': [
                            'Claude_3',
                            'GPT-4',
                            'LLaMA_3',
                            'Mistral___Mixtral',
                            'Plotly',
                            'FastAPI',
                            'AI_QC_Engine',
                        ],
                        'reasoning': 'Analyzes marketing performance and creates reports',
                    },
                    'Audience-Targeting-Agent': {
                        'role': 'Audience Targeting Specialist - Audience analysis and targeting',
                        'tier': 2,
                        'ai_models': [
                            'Claude_3',
                            'GPT-4',
                            'LLaMA_3',
                            'Mistral___Mixtral',
                            'Plotly',
                            'FastAPI',
                            'AI_QC_Engine',
                        ],
                        'reasoning': 'Analyzes and targets audiences for marketing campaigns',
                    },
                    'Revenue-Optimization-Agent': {
                        'role': 'Revenue Optimizer - Revenue optimization and analysis',
                        'tier': 2,
                        'ai_models': [
                            'Claude_3',
                            'GPT-4',
                            'LLaMA_3',
                            'Mistral___Mixtral',
                            'Plotly',
                            'FastAPI',
                            'AI_QC_Engine',
                        ],
                        'reasoning': 'Optimizes revenue through data analysis and strategy',
                    },
                },
            }
        },
    }

    # Count the models
    model_counts = count_ai_models_from_json(json_data)

    # Print results
    _zyg_log.info('=== AI MODEL COUNT FROM JSON DATA ===\n')

    # Sort by count (descending)
    sorted_models = sorted(model_counts.items(), key=lambda x: x[1], reverse=True)

    for model, count in sorted_models:
        _zyg_log.info(f'"{model}": "{count} x found"')

    _zyg_log.info('\n📊 SUMMARY:')
    _zyg_log.info(f'Total unique AI models: {len(model_counts)}')
    _zyg_log.info(f'Total model assignments: {sum(model_counts.values())}')

    return model_counts


if __name__ == '__main__':
    analyze_json_data()
