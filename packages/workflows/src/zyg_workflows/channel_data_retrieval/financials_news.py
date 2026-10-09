# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The FINANCIALS and NEWS channel fetchers.

Moved verbatim out of ``channel_data_retrieval.py`` (lines 568-874).
"""

from __future__ import annotations

from zyg_workflows.channel_data_retrieval.config import (
    _MAX_ITEMS,
    _err,
    _fetch_multi,
    _get,
    _ok,
    _wiki_search,
    json,
)

# ─── FINANCIALS ───────────────────────────────────────────────────────────────


def fetch_fin_wyscamus() -> dict:
    CH, LBL = 'fin_wyscamus', 'Wyscamus — Money Schemes'
    sources = [
        (
            'SEC Enforcement',
            'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=LR&dateb=&owner=include&count=40&search_text=&output=atom',
        ),
        ('DOJ Press', 'https://www.justice.gov/news/rss'),
        ('FTC Alerts', 'https://consumer.ftc.gov/media/rss.xml'),
        ('FBI News', 'https://www.fbi.gov/feeds/fbi-in-the-news/rss.xml'),
        ('FINRA Alerts', 'https://www.finra.org/investors/have-problem/alert-center/rss'),
    ]
    kw = [
        'fraud',
        'scheme',
        'ponzi',
        'scam',
        'wire fraud',
        'money laundering',
        'pyramid',
        'embezzl',
        'insider trading',
        'securities fraud',
        'investment fraud',
        'financial crime',
        'charge',
        'indict',
        'conviction',
        'penalty',
        'forfeiture',
    ]
    items, used, errors = _fetch_multi(sources, keywords=kw)
    if not items:
        try:
            items = _wiki_search(
                'Ponzi scheme pyramid scheme financial fraud money laundering '
                'investment scam embezzlement wire fraud securities fraud'
            )
            used = ['Wikipedia']
        except Exception as e:
            errors.append(f'Wikipedia: {e}')
    if items:
        return _ok(CH, LBL, ', '.join(used), items[:_MAX_ITEMS])
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))


def fetch_fin_stockmarket() -> dict:
    CH, LBL = 'fin_stockmarket', 'Stock Market'
    sources = [
        ('MarketWatch', 'https://feeds.marketwatch.com/marketwatch/topstories/'),
        ('Reuters Biz', 'https://feeds.reuters.com/reuters/businessNews'),
        ('BBC Business', 'http://feeds.bbci.co.uk/news/business/rss.xml'),
        ('CNBC Markets', 'https://www.cnbc.com/id/100003114/device/rss/rss.html'),
        ('Yahoo Finance', 'https://finance.yahoo.com/news/rssindex'),
        ('Seeking Alpha', 'https://seekingalpha.com/feed.xml'),
    ]
    items, used, errors = _fetch_multi(sources)
    if items:
        return _ok(CH, LBL, ', '.join(used), items[:_MAX_ITEMS])
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))


def fetch_fin_crypto() -> dict:
    CH, LBL = 'fin_crypto', 'Cryptodaily'
    items: list[dict] = []
    used: list[str] = []
    errors: list[str] = []

    # CoinGecko price data
    try:
        url = 'https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=20&page=1'
        coins = json.loads(_get(url))
        for c in coins[:10]:
            chg = c.get('price_change_percentage_24h') or 0
            items.append(
                {
                    'title': f'{c.get("name", "")} ({c.get("symbol", "").upper()})',
                    'summary': (
                        f'${c.get("current_price", 0):,.4f}  ·  '
                        f'24h: {chg:+.2f}%  ·  '
                        f'MCap: ${c.get("market_cap", 0):,.0f}'
                    ),
                    'link': f'https://www.coingecko.com/en/coins/{c.get("id", "")}',
                    'published': c.get('last_updated', ''),
                    'image': c.get('image', ''),
                }
            )
        used.append('CoinGecko API')
    except Exception as e:
        errors.append(f'CoinGecko: {e}')

    # News RSS sources
    rss_sources = [
        ('CoinTelegraph', 'https://cointelegraph.com/rss'),
        ('CoinDesk', 'https://www.coindesk.com/arc/outboundfeeds/rss/'),
        ('Decrypt', 'https://decrypt.co/feed'),
        ('Bitcoin Magazine', 'https://bitcoinmagazine.com/feed'),
        ('Cryptoslate', 'https://cryptoslate.com/feed/'),
    ]
    rss_items, rss_used, rss_errors = _fetch_multi(rss_sources, max_items=_MAX_ITEMS - len(items))
    items.extend(rss_items)
    used.extend(rss_used)
    errors.extend(rss_errors)

    if items:
        return _ok(CH, LBL, ', '.join(used), items[:_MAX_ITEMS])
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))


def fetch_fin_history() -> dict:
    CH, LBL = 'fin_history', 'Financial History & Events'
    sources = [
        ('Investopedia', 'https://www.investopedia.com/news/rss.aspx'),
        ('Econ. History Assoc.', 'https://eh.net/feed/'),
        ('Smithsonian', 'https://www.smithsonianmag.com/rss/latest_articles/'),
    ]
    kw = [
        'financial',
        'economic',
        'market',
        'crash',
        'recession',
        'crisis',
        'banking',
        'currency',
        'inflation',
        'depression',
        'bubble',
        'history',
    ]
    items, used, errors = _fetch_multi(sources, keywords=kw)
    if not items:
        items, used, errors = _fetch_multi(sources)
    if not items:
        try:
            items = _wiki_search('financial crisis economic history recession stock market crash')
            used = ['Wikipedia']
        except Exception as e:
            errors.append(f'Wikipedia: {e}')
    if items:
        return _ok(CH, LBL, ', '.join(used), items[:_MAX_ITEMS])
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))


def fetch_fin_housing() -> dict:
    CH, LBL = 'fin_housing', 'Housing Market'
    sources = [
        ('HousingWire', 'https://www.housingwire.com/feed/'),
        ('Realtor.com', 'https://www.realtor.com/news/feed/'),
        ('NAR', 'https://www.nar.realtor/newsroom/news-releases/rss'),
        ('Mortgage News Daily', 'https://www.mortgagenewsdaily.com/feed/news'),
        ('Zillow Research', 'https://www.zillow.com/research/feed/'),
    ]
    items, used, errors = _fetch_multi(sources)
    if not items:
        try:
            items = _wiki_search('real estate housing market mortgage interest rates prices')
            used = ['Wikipedia']
        except Exception as e:
            errors.append(f'Wikipedia: {e}')
    if items:
        return _ok(CH, LBL, ', '.join(used), items[:_MAX_ITEMS])
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))


def fetch_fin_landplots() -> dict:
    CH, LBL = 'fin_landplots', 'Developmental Landplots'
    sources = [
        ('GlobeSt', 'https://www.globest.com/feed/'),
        ('Commercial Observer', 'https://commercialobserver.com/feed/'),
        ('NREI', 'https://www.nreionline.com/rss/all'),
        ('Bisnow', 'https://www.bisnow.com/feed'),
    ]
    kw = [
        'commercial',
        'development',
        'land',
        'plot',
        'zoning',
        'real estate',
        'industrial',
        'warehouse',
        'mixed-use',
        'ground lease',
        'entitlement',
        'construction',
        'permit',
        'property',
        'office',
        'retail',
    ]
    items, used, errors = _fetch_multi(sources, keywords=kw)
    if not items:
        items, used, errors = _fetch_multi(sources)
    if not items:
        try:
            items = _wiki_search('real estate development land use zoning urban planning commercial property')
            used = ['Wikipedia']
        except Exception as e:
            errors.append(f'Wikipedia: {e}')
    if items:
        return _ok(CH, LBL, ', '.join(used), items[:_MAX_ITEMS])
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))


# ─── NEWS ─────────────────────────────────────────────────────────────────────


def fetch_news_world() -> dict:
    CH, LBL = 'news_world', 'Impactful World News'
    sources = [
        ('BBC World', 'http://feeds.bbci.co.uk/news/world/rss.xml'),
        ('Reuters World', 'https://feeds.reuters.com/reuters/worldNews'),
        ('Al Jazeera', 'https://www.aljazeera.com/xml/rss/all.xml'),
        ('The Guardian', 'https://www.theguardian.com/world/rss'),
        ('AP News', 'https://feeds.apnews.com/rss/topnews'),
    ]
    items, used, errors = _fetch_multi(sources)
    if items:
        return _ok(CH, LBL, ', '.join(used), items[:_MAX_ITEMS])
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))


def fetch_news_ru() -> dict:
    CH, LBL = 'news_ru', 'Daily News Russian'
    sources = [
        ('The Moscow Times', 'https://www.themoscowtimes.com/rss/news'),
        ('Meduza', 'https://meduza.io/rss/en/all'),
        ('Kyiv Independent', 'https://kyivindependent.com/feed/'),
        ('RFE/RL Russia', 'https://www.rferl.org/api/zrqpniqbr-1_0.xml'),
        ('Reuters Russia', 'https://feeds.reuters.com/reuters/russiaNews'),
    ]
    items, used, errors = _fetch_multi(sources)
    if items:
        return _ok(CH, LBL, ', '.join(used), items[:_MAX_ITEMS])
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))


def fetch_news_en() -> dict:
    CH, LBL = 'news_en', 'Daily News Western'
    sources = [
        ('BBC News', 'http://feeds.bbci.co.uk/news/rss.xml'),
        ('Reuters Top', 'https://feeds.reuters.com/reuters/topNews'),
        ('The Guardian', 'https://www.theguardian.com/world/rss'),
        ('NPR News', 'https://feeds.npr.org/1001/rss.xml'),
        ('AP News', 'https://feeds.apnews.com/rss/topnews'),
    ]
    items, used, errors = _fetch_multi(sources)
    if items:
        return _ok(CH, LBL, ', '.join(used), items[:_MAX_ITEMS])
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))


def fetch_news_eu() -> dict:
    CH, LBL = 'news_eu', 'Daily News Europe'
    sources = [
        ('DW', 'https://rss.dw.com/atom/rss-en-top'),
        ('Politico EU', 'https://www.politico.eu/feed/'),
        ('Euronews', 'https://www.euronews.com/rss?format=mrss&level=theme&name=news'),
        ('EUobserver', 'https://euobserver.com/rss.xml'),
        ('The Local', 'https://www.thelocal.com/feed/'),
    ]
    items, used, errors = _fetch_multi(sources)
    if items:
        return _ok(CH, LBL, ', '.join(used), items[:_MAX_ITEMS])
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))


def fetch_news_cn() -> dict:
    CH, LBL = 'news_cn', 'Daily News China'
    sources = [
        ('SCMP', 'https://rss.scmp.com/rss/3'),
        ('China Daily', 'http://www.chinadaily.com.cn/rss/china_rss.xml'),
        ('RFA China', 'https://www.rfa.org/english/news/china/rss2'),
        ('Sixth Tone', 'https://www.sixthtone.com/rss'),
        ('Caixin', 'https://www.caixinglobal.com/rss/feed.xml'),
    ]
    items, used, errors = _fetch_multi(sources)
    if items:
        return _ok(CH, LBL, ', '.join(used), items[:_MAX_ITEMS])
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))


def fetch_news_sa() -> dict:
    CH, LBL = 'news_sa', 'Daily News South America'
    sources = [
        ('Mercopress', 'https://en.mercopress.com/feed'),
        ('The Brazil Report', 'https://thebrazilreport.com/feed/'),
        ('Colombia Reports', 'https://colombiareports.com/feed/'),
        ('Reuters LatAm', 'https://feeds.reuters.com/reuters/latamNews'),
        ('Buenos Aires Times', 'https://www.batimes.com.ar/feed'),
    ]
    items, used, errors = _fetch_multi(sources)
    if not items:
        try:
            items = _wiki_search('South America Latin America news politics economy Brazil Argentina')
            used = ['Wikipedia']
        except Exception as e:
            errors.append(f'Wikipedia: {e}')
    if items:
        return _ok(CH, LBL, ', '.join(used), items[:_MAX_ITEMS])
    return _err(CH, LBL, 'Multi-source', ' | '.join(errors))
