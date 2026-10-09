# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The STORYTELLER seeds/fetchers and the standalone channels.

Moved verbatim out of ``channel_data_retrieval.py`` (lines 875-1252).
"""

from __future__ import annotations

from zyg_workflows.channel_data_retrieval.config import (
    _MAX_ITEMS,
    _err,
    _fetch_multi,
    _ok,
    _wiki_search,
    _zyg_log,
    datetime,
    json,
    paths,
    tempfile,
    timezone,
)

# ─── STORYTELLER ──────────────────────────────────────────────────────────────

_HER_STORY_SEEDS = [
    {
        'title': 'The Woman Who Rewrote the Rules',
        'summary': 'A professional defies industry norms and reshapes an entire field.',
        'link': '',
        'published': '',
        'image': '',
    },
    {
        'title': 'She Left Everything Behind',
        'summary': 'An unexpected life pivot leads to remarkable reinvention.',
        'link': '',
        'published': '',
        'image': '',
    },
    {
        'title': 'The Inheritance She Never Wanted',
        'summary': 'A family secret forces a reckoning with identity and legacy.',
        'link': '',
        'published': '',
        'image': '',
    },
    {
        'title': 'First in Her Family',
        'summary': 'Breaking generational patterns through education and ambition.',
        'link': '',
        'published': '',
        'image': '',
    },
    {
        'title': 'The Silent Partnership',
        'summary': "The untold story behind a famous man's achievements.",
        'link': '',
        'published': '',
        'image': '',
    },
]

_HIS_STORY_SEEDS = [
    {
        'title': "The Builder's Gamble",
        'summary': 'A man bets everything on one final project.',
        'link': '',
        'published': '',
        'image': '',
    },
    {
        'title': 'What He Never Said',
        'summary': "A son discovers his father's hidden wartime letters.",
        'link': '',
        'published': '',
        'image': '',
    },
    {
        'title': 'The Long Walk Back',
        'summary': 'Redemption after a decade-long fall from grace.',
        'link': '',
        'published': '',
        'image': '',
    },
    {
        'title': "Brother's Keeper",
        'summary': 'Two brothers, one secret, and the price of loyalty.',
        'link': '',
        'published': '',
        'image': '',
    },
    {
        'title': "The Mentor's Last Class",
        'summary': 'A retiring teacher gives a final gift to an unlikely student.',
        'link': '',
        'published': '',
        'image': '',
    },
]

_MADEUP_STORY_SEEDS = [
    {
        'title': 'The Cartographer of Forgotten Lands',
        'summary': 'Fantasy/Adventure — A mapmaker discovers maps that rewrite history.',
        'link': '',
        'published': '',
        'image': '',
    },
    {
        'title': 'When the Clocks Stopped',
        'summary': 'Sci-Fi/Thriller — One city frozen in time while the world moves on.',
        'link': '',
        'published': '',
        'image': '',
    },
    {
        'title': 'The Last Lighthouse Keeper',
        'summary': 'Drama/Mystery — A keeper guards a lighthouse no ship ever passes.',
        'link': '',
        'published': '',
        'image': '',
    },
    {
        'title': 'Artificial Grief',
        'summary': 'Sci-Fi/Emotion — An AI programmed to mourn on behalf of a grieving family.',
        'link': '',
        'published': '',
        'image': '',
    },
    {
        'title': 'The Town That Voted to Disappear',
        'summary': 'Dark Comedy — A small town unanimously decides to cease existing legally.',
        'link': '',
        'published': '',
        'image': '',
    },
]


def fetch_story_her() -> dict:
    CH, LBL = 'story_her', 'Her Stories'
    sources = [
        ('Reddit WritingPrompts', 'https://www.reddit.com/r/WritingPrompts/.rss'),
        ('Reedsy Prompts', 'https://blog.reedsy.com/creative-writing-prompts/feed/'),
        ('The Story Shack', 'https://thestoryshack.com/feed/'),
    ]
    kw = [
        'woman',
        'she',
        'her',
        'girl',
        'daughter',
        'mother',
        'wife',
        'sister',
        'female',
        'lady',
        'queen',
        'princess',
        'women',
    ]
    items, used, _ = _fetch_multi(sources, keywords=kw, max_items=15)
    # Pad with seeds if needed
    if len(items) < 5:
        seen = {i.get('title') for i in items}
        for seed in _HER_STORY_SEEDS:
            if seed['title'] not in seen:
                items.append(seed)
    return _ok(CH, LBL, ', '.join(used) if used else 'Internal Seed Library', items[:_MAX_ITEMS])


def fetch_story_his() -> dict:
    CH, LBL = 'story_his', 'His Stories'
    sources = [
        ('Reddit WritingPrompts', 'https://www.reddit.com/r/WritingPrompts/.rss'),
        ('Reedsy Prompts', 'https://blog.reedsy.com/creative-writing-prompts/feed/'),
        ('The Story Shack', 'https://thestoryshack.com/feed/'),
    ]
    kw = [
        'man',
        'he',
        'his',
        'boy',
        'son',
        'father',
        'husband',
        'brother',
        'male',
        'king',
        'prince',
        'soldier',
        'men',
        'veteran',
        'grandfather',
    ]
    items, used, _ = _fetch_multi(sources, keywords=kw, max_items=15)
    if len(items) < 5:
        seen = {i.get('title') for i in items}
        for seed in _HIS_STORY_SEEDS:
            if seed['title'] not in seen:
                items.append(seed)
    return _ok(CH, LBL, ', '.join(used) if used else 'Internal Seed Library', items[:_MAX_ITEMS])


def fetch_story_madeup() -> dict:
    CH, LBL = 'story_madeup', 'Made Up Stories'
    sources = [
        ('Reddit WritingPrompts', 'https://www.reddit.com/r/WritingPrompts/.rss'),
        ('Daily Sci-Fi', 'https://dailysciencefiction.com/rss.xml'),
        ('Clarkesworld', 'https://clarkesworld.com/feed/'),
        ('Reedsy Prompts', 'https://blog.reedsy.com/creative-writing-prompts/feed/'),
    ]
    items, used, _ = _fetch_multi(sources, max_items=15)
    if len(items) < 5:
        seen = {i.get('title') for i in items}
        for seed in _MADEUP_STORY_SEEDS:
            if seed['title'] not in seen:
                items.append(seed)
    return _ok(CH, LBL, ', '.join(used) if used else 'Internal Seed Library', items[:_MAX_ITEMS])


# ─── STANDALONE CHANNELS ──────────────────────────────────────────────────────


def fetch_luxury() -> dict:
    CH, LBL = 'luxury', 'Luxury'
    sources = [
        ('Robb Report', 'https://robbreport.com/feed/'),
        ('Architectural Digest', 'https://www.architecturaldigest.com/feed/rss'),
        ('Town & Country', 'https://www.townandcountrymag.com/rss/all.xml/'),
        ('Vogue', 'https://www.vogue.com/rss/everything.xml'),
        ('Business of Fashion', 'https://www.businessoffashion.com/rss'),
        ('Forbes Lifestyle', 'https://www.forbes.com/lifestyle/feed2/'),
    ]
    items, used, errors = _fetch_multi(sources)
    if items:
        return _ok(CH, LBL, ', '.join(used), items[:_MAX_ITEMS])
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))


def fetch_traveling() -> dict:
    CH, LBL = 'traveling', 'Traveling'
    sources = [
        ('Atlas Obscura', 'https://www.atlasobscura.com/feeds/latest'),
        ('Condé Nast Traveler', 'https://www.cntraveler.com/feed/rss'),
        ('Lonely Planet', 'https://www.lonelyplanet.com/news/feed'),
        ('National Geographic Travel', 'https://www.nationalgeographic.com/travel/article/feed.rss'),
        ('Travel + Leisure', 'https://www.travelandleisure.com/rss/all.xml'),
    ]
    items, used, errors = _fetch_multi(sources)
    if items:
        return _ok(CH, LBL, ', '.join(used), items[:_MAX_ITEMS])
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))


def fetch_clipped() -> dict:
    """Scan locally produced pipeline output for clip assets."""
    import os
    import glob as _glob

    CH, LBL, SRC = 'clipped', 'Clipped', 'Local Pipeline Output'
    search_roots = [
        str(paths.ZYG_DATA_ROOT / 'assets'),
        str(paths.ZYG_HOME / 'pipeline_output'),
        os.path.join(tempfile.gettempdir(), 'pipeline'),
    ]
    items = []
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        for fp in _glob.glob(os.path.join(root, '**', '*.mp4'), recursive=True)[:_MAX_ITEMS]:
            stat = os.stat(fp)
            items.append(
                {
                    'title': os.path.basename(fp),
                    'summary': f'Size: {stat.st_size / (1024 * 1024):.1f} MB',
                    'link': fp,
                    'published': datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                    'image': '',
                }
            )
    if not items:
        items = [
            {
                'title': 'No local clips found',
                'summary': 'Run the pipeline to produce clip assets.',
                'link': '',
                'published': '',
                'image': '',
            }
        ]
    return _ok(CH, LBL, SRC, items)


def fetch_crime() -> dict:
    CH, LBL = 'crime', 'Crime'
    sources = [
        ('Crime Reads', 'https://crimereads.com/feed/'),
        ('The Marshall Project', 'https://www.themarshallproject.org/feeds/news'),
        ('ProPublica CJ', 'https://feeds.propublica.org/propublica/crimejustice'),
        ('BBC UK News', 'http://feeds.bbci.co.uk/news/uk/rss.xml'),
        ('True Crime Daily', 'https://truecrimedaily.com/feed/'),
    ]
    kw = [
        'crime',
        'murder',
        'kill',
        'arrest',
        'sentence',
        'court',
        'trial',
        'guilty',
        'verdict',
        'detective',
        'suspect',
        'police',
        'criminal',
        'homicide',
        'robbery',
        'assault',
        'prison',
        'convict',
        'indict',
    ]
    items, used, errors = _fetch_multi(sources, keywords=kw)
    if not items:
        items, used, errors = _fetch_multi(sources)

    # Supplement with local court_cases.json
    import os

    cc_path = str(paths.DATA_DIR / 'runtime' / 'court_cases.json')
    if os.path.isfile(cc_path):
        try:
            with open(cc_path) as _f:
                cases = json.load(_f)
            for c in (cases.get('cases') or [])[:5]:
                link = ''
                seen_links = {i.get('link') for i in items}
                if link not in seen_links:
                    items.insert(
                        0,
                        {
                            'title': c.get('name', ''),
                            'summary': c.get('why_narrate', c.get('summary', '')),
                            'link': '',
                            'published': str(c.get('year', '')),
                            'image': '',
                        },
                    )
        except Exception as _exc:
            _zyg_log.warning('court cases file unreadable, no seeded cases added: %s', _exc)

    if items:
        return _ok(CH, LBL, ', '.join(used) or 'court_cases.json', items[:_MAX_ITEMS])
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))


def fetch_docudocu() -> dict:
    CH, LBL = 'docudocu', 'DocuDocu'
    sources = [
        ('Smithsonian', 'https://www.smithsonianmag.com/rss/latest_articles/'),
        ('National Geographic', 'https://www.nationalgeographic.com/pages/article/feed.rss'),
        ('NOVA PBS', 'https://www.pbs.org/wgbh/nova/rss/nova.xml'),
        ('Scientific American', 'https://www.scientificamerican.com/feed/'),
        ('History.com', 'https://www.history.com/.rss/full/'),
    ]
    items, used, errors = _fetch_multi(sources)
    if not items:
        try:
            items = _wiki_search('documentary history civilization science discovery archaeology')
            used = ['Wikipedia']
        except Exception as e:
            errors.append(f'Wikipedia: {e}')
    if items:
        return _ok(CH, LBL, ', '.join(used), items[:_MAX_ITEMS])
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))


def fetch_religion() -> dict:
    CH, LBL = 'religion', 'Religion'
    sources = [
        ('Religion News Service', 'https://religionnews.com/feed/'),
        ('Christianity Today', 'https://www.christianitytoday.com/feeds/all.xml'),
        ('The Revealer', 'https://therevealer.org/feed/'),
        ('Beliefnet', 'https://www.beliefnet.com/feeds/news.rss'),
        ('Buddhist Door', 'https://www.buddhistdoor.net/feed/'),
    ]
    items, used, errors = _fetch_multi(sources)
    if not items:
        try:
            items = _wiki_search('world religion theology history Christianity Islam Judaism Buddhism Hinduism')
            used = ['Wikipedia']
        except Exception as e:
            errors.append(f'Wikipedia: {e}')
    if items:
        return _ok(CH, LBL, ', '.join(used), items[:_MAX_ITEMS])
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))
