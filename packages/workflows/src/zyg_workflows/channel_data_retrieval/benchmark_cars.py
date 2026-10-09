# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The BENCHMARK and CARS channel fetchers.

Moved verbatim out of ``channel_data_retrieval.py`` (lines 308-567).
"""

from __future__ import annotations

from zyg_workflows.channel_data_retrieval.config import (
    _MAX_ITEMS,
    _err,
    _fetch_multi,
    _fetch_rss,
    _get,
    _ok,
    _wiki_search,
    json,
)

# ─── BENCHMARK ────────────────────────────────────────────────────────────────


def fetch_benchmark_phones() -> dict:
    CH, LBL = 'benchmark_phones', 'Phone Benchmarks'
    sources = [
        ('GSMArena', 'https://www.gsmarena.com/rss-news-reviews.php3'),
        ('Android Authority', 'https://www.androidauthority.com/feed/'),
        ('The Verge Mobile', 'https://www.theverge.com/rss/mobile/index.xml'),
        ('9to5Mac', 'https://9to5mac.com/feed/'),
        ('PhoneArena', 'https://www.phonearena.com/rss/news.xml'),
        ('XDA Developers', 'https://www.xda-developers.com/feed/'),
    ]
    items, used, errors = _fetch_multi(sources)
    if items:
        return _ok(CH, LBL, ', '.join(used), items)
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))


def fetch_benchmark_gpus_cpus() -> dict:
    CH, LBL = 'benchmark_gpus_cpus', 'GPU & CPU Benchmarks'
    sources = [
        ("Tom's Hardware", 'https://www.tomshardware.com/feeds/all'),
        ('TechPowerUp', 'https://www.techpowerup.com/rss/news.xml'),
        ('Guru3D', 'https://www.guru3d.com/feed/'),
        ('PC Gamer', 'https://www.pcgamer.com/rss/hardware/'),
        ('Ars Technica', 'https://feeds.arstechnica.com/arstechnica/technology-lab'),
        ('The Verge Tech', 'https://www.theverge.com/rss/tech/index.xml'),
    ]
    kw = [
        'gpu',
        'cpu',
        'processor',
        'graphics',
        'benchmark',
        'performance',
        'nvidia',
        'amd',
        'intel',
        'radeon',
        'geforce',
        'ryzen',
        'core i',
    ]
    items, used, errors = _fetch_multi(sources, keywords=kw)
    if not items:
        # Fallback without keyword filter
        items, used, errors = _fetch_multi(sources)
    if items:
        return _ok(CH, LBL, ', '.join(used), items)
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))


def fetch_benchmark_cars() -> dict:
    CH, LBL = 'benchmark_cars', 'Car Benchmarks'
    sources = [
        ('Car and Driver', 'https://www.caranddriver.com/rss/all.xml/'),
        ('Motor Trend', 'https://www.motortrend.com/feed/'),
        ('Autocar', 'https://www.autocar.co.uk/rss'),
        ('Autoweek', 'https://www.autoweek.com/rss/all.xml/'),
        ('Road & Track', 'https://www.roadandtrack.com/rss/all.xml/'),
    ]
    items, used, errors = _fetch_multi(sources)
    if items:
        return _ok(CH, LBL, ', '.join(used), items)
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))


def fetch_benchmark_llm() -> dict:
    CH, LBL, SRC = 'benchmark_llm', 'LLM Benchmarks', 'HuggingFace Hub API'
    items: list[dict] = []
    errors: list[str] = []
    used: list[str] = []

    # Primary: HuggingFace top models
    try:
        raw = json.loads(_get('https://huggingface.co/api/models?sort=likes&direction=-1&limit=25'))
        for m in raw[:_MAX_ITEMS]:
            items.append(
                {
                    'title': m.get('id', ''),
                    'summary': f'Downloads: {m.get("downloads", 0):,}  ·  Likes: {m.get("likes", 0):,}',
                    'link': f'https://huggingface.co/{m.get("id", "")}',
                    'published': m.get('lastModified', ''),
                    'image': '',
                }
            )
        used.append('HuggingFace Hub')
    except Exception as e:
        errors.append(f'HuggingFace: {e}')

    # Supplement: AI news RSS feeds
    rss_sources = [
        ('arXiv CS.AI', 'https://rss.arxiv.org/rss/cs.AI'),
        ('Anthropic Blog', 'https://www.anthropic.com/rss.xml'),
        ('Google AI Blog', 'https://ai.googleblog.com/feeds/posts/default'),
        ('OpenAI Blog', 'https://openai.com/news/rss.xml'),
    ]
    kw = [
        'model',
        'llm',
        'benchmark',
        'language model',
        'gpt',
        'claude',
        'gemini',
        'ai',
        'training',
        'inference',
        'parameter',
        'fine-tun',
    ]
    rss_items, rss_used, rss_errors = _fetch_multi(rss_sources, keywords=kw, max_items=_MAX_ITEMS - len(items))
    items.extend(rss_items)
    used.extend(rss_used)
    errors.extend(rss_errors)

    if items:
        return _ok(CH, LBL, ', '.join(used) or SRC, items[:_MAX_ITEMS])
    return _err(CH, LBL, SRC, ' | '.join(errors))


# ─── CARS ─────────────────────────────────────────────────────────────────────


def fetch_cars_future() -> dict:
    CH, LBL = 'cars_future', 'Future Cars'
    # Primary sources — proper automotive outlets
    primary = [
        ('Motor1', 'https://www.motor1.com/rss/news/all/'),
        ('Car and Driver', 'https://www.caranddriver.com/rss/all.xml/'),
        ('The Drive', 'https://www.thedrive.com/feeds/latest'),
        ('Autocar', 'https://www.autocar.co.uk/rss'),
        ('Autoweek', 'https://www.autoweek.com/rss/all.xml/'),
        ('Road & Track', 'https://www.roadandtrack.com/rss/all.xml/'),
    ]
    items, used, errors = _fetch_multi(primary)

    # Supplement with Electrek — filtered strictly to EV/car reveals
    if len(items) < _MAX_ITEMS:
        electrek_kw = [
            'electric car',
            'ev reveal',
            'concept car',
            'prototype',
            'spy shot',
            'first look',
            'unveil',
            'launch',
            'debut',
            'electric vehicle',
            'crossover',
            'sedan',
            'pickup truck',
            'suv reveal',
        ]
        try:
            extra = _fetch_rss('https://electrek.co/feed/', max_items=40)
            for item in extra:
                text = (item.get('title', '') + ' ' + item.get('summary', '')).lower()
                if any(k in text for k in electrek_kw):
                    link = item.get('link', '')
                    if link not in {i.get('link') for i in items}:
                        items.append(item)
                        if 'Electrek' not in used:
                            used.append('Electrek (filtered)')
                if len(items) >= _MAX_ITEMS:
                    break
        except Exception as e:
            errors.append(f'Electrek: {e}')

    if items:
        return _ok(CH, LBL, ', '.join(used), items[:_MAX_ITEMS])
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))


def fetch_cars_oldtimers() -> dict:
    CH, LBL = 'cars_oldtimers', 'Classic Cars & Oldtimers'
    sources = [
        ('Bring a Trailer', 'https://bringatrailer.com/feed/'),
        ('Hemmings', 'https://www.hemmings.com/blogs/feed/'),
        ('Hagerty Media', 'https://www.hagerty.com/media/feed/'),
        ('Motoring Research', 'https://www.motoringresearch.com/feed'),
        ('Classic Cars Journal', 'https://www.classiccarsjournal.net/feed/'),
        ('Motor Trend Classic', 'https://www.motortrend.com/feed/'),
    ]
    kw = [
        'classic',
        'vintage',
        'oldtimer',
        'restored',
        'auction',
        'collector',
        'historic',
        'retro',
        '196',
        '197',
        '198',
        '195',
        'barn find',
    ]
    items, used, errors = _fetch_multi(sources, keywords=kw)
    if not items:
        items, used, errors = _fetch_multi(sources)
    if not items:
        try:
            items = _wiki_search('classic car auction vintage automobile history restoration')
            used = ['Wikipedia']
        except Exception as e:
            errors.append(f'Wikipedia: {e}')
    if items:
        return _ok(CH, LBL, ', '.join(used), items[:_MAX_ITEMS])
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))


def fetch_cars_mechanics() -> dict:
    CH, LBL = 'cars_mechanics', 'Car Mechanics'
    sources = [
        ('The Drive', 'https://www.thedrive.com/feeds/latest'),
        ('Autoblog', 'https://www.autoblog.com/rss.xml'),
        ('Motor Trend', 'https://www.motortrend.com/feed/'),
        ('Car and Driver', 'https://www.caranddriver.com/rss/all.xml/'),
        ('HowStuffWorks', 'https://auto.howstuffworks.com/rss.xml'),
        ('Popular Mechanics', 'https://www.popularmechanics.com/rss/all.xml/'),
    ]
    kw = [
        'car',
        'truck',
        'engine',
        'vehicle',
        'auto',
        'repair',
        'transmission',
        'suspension',
        'brake',
        'tire',
        'exhaust',
        'maintenance',
        'mechanic',
        'oil',
        'horsepower',
        'torque',
        'cylinder',
        'turbo',
        'supercharg',
    ]
    items, used, errors = _fetch_multi(sources, keywords=kw)
    if not items:
        items, used, errors = _fetch_multi(sources)
    if not items:
        try:
            items = _wiki_search('car engine repair maintenance automotive mechanics')
            used = ['Wikipedia']
        except Exception as e:
            errors.append(f'Wikipedia: {e}')
    if items:
        return _ok(CH, LBL, ', '.join(used), items[:_MAX_ITEMS])
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))
