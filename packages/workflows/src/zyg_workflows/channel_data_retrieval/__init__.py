# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Re-export shim: the package IS the old module.

"""
channel_data_retrieval.py
=========================
Multi-source data retrieval for all Creator Nexus channels (sports excluded).

Each public fetch_* function returns a standard result dict:
    {
        'channel':    str   — channel key
        'label':      str   — human label
        'source':     str   — active sources used (comma-separated)
        'status':     'ok' | 'error'
        'error':      str | None
        'item_count': int
        'items':      list[dict]  — each item: title, link, summary, published, image
        'fetched_at': ISO-8601 UTC string
    }

REGISTRY maps every channel key to its fetcher:
    from zyg_workflows.channel_data_retrieval import REGISTRY
    result = REGISTRY['fin_crypto']()
"""

from __future__ import annotations

# Pattern A split of channel_data_retrieval.py: every section below was moved VERBATIM into its own
# module. The submodules are imported in the ORIGINAL SECTION ORDER so that
# module-level side effects run exactly as they did in the single file.

from zyg_workflows.channel_data_retrieval.config import (
    json,
    re,
    ssl,
    tempfile,
    _up,
    _ur,
    datetime,
    timezone,
    xml_fromstring,
    paths,
    contact_email,
    _zyg_logging,
    _zyg_log,
    _UA,
    _TIMEOUT,
    _MAX_ITEMS,
    _SSL_CTX,
    _now,
    _ok,
    _err,
    _IMG_EXT_RE,
    _BAD_IMG_RE,
    _BAD_IMG_HOSTS,
    _looks_like_image,
    _validate_image_url,
    _extract_image,
    _checked_url,
    _get,
    _strip_ns,
    _fetch_rss,
    _wiki_search,
    _fetch_multi,
)

from zyg_workflows.channel_data_retrieval.benchmark_cars import (
    fetch_benchmark_phones,
    fetch_benchmark_gpus_cpus,
    fetch_benchmark_cars,
    fetch_benchmark_llm,
    fetch_cars_future,
    fetch_cars_oldtimers,
    fetch_cars_mechanics,
)

from zyg_workflows.channel_data_retrieval.financials_news import (
    fetch_fin_wyscamus,
    fetch_fin_stockmarket,
    fetch_fin_crypto,
    fetch_fin_history,
    fetch_fin_housing,
    fetch_fin_landplots,
    fetch_news_world,
    fetch_news_ru,
    fetch_news_en,
    fetch_news_eu,
    fetch_news_cn,
    fetch_news_sa,
)

from zyg_workflows.channel_data_retrieval.storyteller_standalone import (
    _HER_STORY_SEEDS,
    _HIS_STORY_SEEDS,
    _MADEUP_STORY_SEEDS,
    fetch_story_her,
    fetch_story_his,
    fetch_story_madeup,
    fetch_luxury,
    fetch_traveling,
    fetch_clipped,
    fetch_crime,
    fetch_docudocu,
    fetch_religion,
)

from zyg_workflows.channel_data_retrieval.registry import (
    REGISTRY,
    CHANNEL_GROUPS,
)


# Every name below is imported above and not used in this module: this package
# IS the re-export surface of the pre-split module, so the imports are the
# deliberate public surface, not dead weight.  Nothing does ``import *`` from
# here, so __all__ changes no behaviour.
__all__ = [
    'json',
    're',
    'ssl',
    'tempfile',
    '_up',
    '_ur',
    'datetime',
    'timezone',
    'xml_fromstring',
    'paths',
    'contact_email',
    '_zyg_logging',
    '_zyg_log',
    '_UA',
    '_TIMEOUT',
    '_MAX_ITEMS',
    '_SSL_CTX',
    '_now',
    '_ok',
    '_err',
    '_IMG_EXT_RE',
    '_BAD_IMG_RE',
    '_BAD_IMG_HOSTS',
    '_looks_like_image',
    '_validate_image_url',
    '_extract_image',
    '_checked_url',
    '_get',
    '_strip_ns',
    '_fetch_rss',
    '_wiki_search',
    '_fetch_multi',
    'fetch_benchmark_phones',
    'fetch_benchmark_gpus_cpus',
    'fetch_benchmark_cars',
    'fetch_benchmark_llm',
    'fetch_cars_future',
    'fetch_cars_oldtimers',
    'fetch_cars_mechanics',
    'fetch_fin_wyscamus',
    'fetch_fin_stockmarket',
    'fetch_fin_crypto',
    'fetch_fin_history',
    'fetch_fin_housing',
    'fetch_fin_landplots',
    'fetch_news_world',
    'fetch_news_ru',
    'fetch_news_en',
    'fetch_news_eu',
    'fetch_news_cn',
    'fetch_news_sa',
    '_HER_STORY_SEEDS',
    '_HIS_STORY_SEEDS',
    '_MADEUP_STORY_SEEDS',
    'fetch_story_her',
    'fetch_story_his',
    'fetch_story_madeup',
    'fetch_luxury',
    'fetch_traveling',
    'fetch_clipped',
    'fetch_crime',
    'fetch_docudocu',
    'fetch_religion',
    'REGISTRY',
    'CHANNEL_GROUPS',
]
