# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``REGISTRY`` and ``CHANNEL_GROUPS`` — the channel-key -> fetcher map.

Moved verbatim out of ``channel_data_retrieval.py`` (lines 1253-1352).
"""

from __future__ import annotations

from zyg_workflows.channel_data_retrieval.benchmark_cars import (
    fetch_benchmark_cars,
    fetch_benchmark_gpus_cpus,
    fetch_benchmark_llm,
    fetch_benchmark_phones,
    fetch_cars_future,
    fetch_cars_mechanics,
    fetch_cars_oldtimers,
)
from zyg_workflows.channel_data_retrieval.financials_news import (
    fetch_fin_crypto,
    fetch_fin_history,
    fetch_fin_housing,
    fetch_fin_landplots,
    fetch_fin_stockmarket,
    fetch_fin_wyscamus,
    fetch_news_cn,
    fetch_news_en,
    fetch_news_eu,
    fetch_news_ru,
    fetch_news_sa,
    fetch_news_world,
)
from zyg_workflows.channel_data_retrieval.storyteller_standalone import (
    fetch_clipped,
    fetch_crime,
    fetch_docudocu,
    fetch_luxury,
    fetch_religion,
    fetch_story_her,
    fetch_story_his,
    fetch_story_madeup,
    fetch_traveling,
)

# ─── REGISTRY ─────────────────────────────────────────────────────────────────

REGISTRY: dict[str, callable] = {
    # Benchmark
    'benchmark_phones': fetch_benchmark_phones,
    'benchmark_gpus_cpus': fetch_benchmark_gpus_cpus,
    'benchmark_cars': fetch_benchmark_cars,
    'benchmark_llm': fetch_benchmark_llm,
    # Cars
    'cars_future': fetch_cars_future,
    'cars_oldtimers': fetch_cars_oldtimers,
    'cars_mechanics': fetch_cars_mechanics,
    # Financials
    'fin_wyscamus': fetch_fin_wyscamus,
    'fin_stockmarket': fetch_fin_stockmarket,
    'fin_crypto': fetch_fin_crypto,
    'fin_history': fetch_fin_history,
    'fin_housing': fetch_fin_housing,
    'fin_landplots': fetch_fin_landplots,
    # News
    'news_world': fetch_news_world,
    'news_ru': fetch_news_ru,
    'news_en': fetch_news_en,
    'news_eu': fetch_news_eu,
    'news_cn': fetch_news_cn,
    'news_sa': fetch_news_sa,
    # Storyteller
    'story_her': fetch_story_her,
    'story_his': fetch_story_his,
    'story_madeup': fetch_story_madeup,
    # Standalone
    'luxury': fetch_luxury,
    'traveling': fetch_traveling,
    'clipped': fetch_clipped,
    'crime': fetch_crime,
    'docudocu': fetch_docudocu,
    'religion': fetch_religion,
}

# Metadata for UI grouping
CHANNEL_GROUPS = [
    {
        'group': 'Benchmark',
        'channels': [
            ('benchmark_phones', 'Phones'),
            ('benchmark_gpus_cpus', 'GPUs & CPUs'),
            ('benchmark_cars', 'Cars'),
            ('benchmark_llm', 'Large Language Models'),
        ],
    },
    {
        'group': 'Cars',
        'channels': [
            ('cars_future', 'Future Cars'),
            ('cars_oldtimers', 'Oldtimers'),
            ('cars_mechanics', 'Car Mechanics'),
        ],
    },
    {
        'group': 'Financials',
        'channels': [
            ('fin_wyscamus', 'Wyscamus'),
            ('fin_stockmarket', 'Stockmarket'),
            ('fin_crypto', 'Cryptodaily'),
            ('fin_history', 'Financial History'),
            ('fin_housing', 'Housing'),
            ('fin_landplots', 'Landplots'),
        ],
    },
    {
        'group': 'News',
        'channels': [
            ('news_world', 'World'),
            ('news_ru', 'Russian'),
            ('news_en', 'Western'),
            ('news_eu', 'Europe'),
            ('news_cn', 'China'),
            ('news_sa', 'South America'),
        ],
    },
    {
        'group': 'Storyteller',
        'channels': [
            ('story_her', 'Her Stories'),
            ('story_his', 'His Stories'),
            ('story_madeup', 'Made Up Stories'),
        ],
    },
    {
        'group': 'Standalone',
        'channels': [
            ('luxury', 'Luxury'),
            ('traveling', 'Traveling'),
            ('clipped', 'Clipped'),
            ('crime', 'Crime'),
            ('docudocu', 'DocuDocu'),
            ('religion', 'Religion'),
        ],
    },
]
