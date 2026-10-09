# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""Absolute episode numbering and board assembly."""

from .constants import _lock
from .naming import _QUALITY_RE, _lang_label
from .prefs import (
    DEFAULT_PREFS,
    chapters_of,
    detect_marks,
    display_series,
    item_show_key,
    pick_default_audio,
    pick_default_sub,
    prefs_for,
)
from .library import load_library, save_library
from .hls import version_suffixes


# ── Absolute episode numbering ────────────────────────────────────────────────
EPISODE_CHUNK = 100  # bucket size for the range chips (1-100, 101-200, ...)


def assign_absolute(seasons: list[dict]) -> list[dict]:
    """Stamp every episode card with ``abs`` and return its 100-wide range buckets.

    Two numbering schemes exist in the wild and they need opposite handling:

    * **Absolute** — long-running anime ships as ``Show - 1015``, so the parsed
      episode number is ALREADY the series-wide index. Renumbering it from a
      running counter would relabel episode 1015 as "3" in a library holding
      only three files, and the range chips would then point at the wrong
      hundred.
    * **Per-season** — a normal S01E01 / S02E01 show restarts at 1 each season,
      so the episode number alone collides and a running counter is the only
      way to order the whole run.

    Telling them apart needs no metadata: if no episode number repeats across
    seasons the numbering is already series-wide, and is kept verbatim.
    """
    numbers = [e.get('episode') or 0 for s in seasons for e in s['episodes']]
    series_wide = len(numbers) == len(set(numbers))

    counter = 0
    for season in seasons:
        for ep in season['episodes']:
            counter += 1
            ep['abs'] = (ep.get('episode') or counter) if series_wide else counter

    buckets: dict[int, dict] = {}
    for season in seasons:
        for ep in season['episodes']:
            idx = int(max(0, (ep['abs'] - 1)) // EPISODE_CHUNK)  # abs can be 24.5
            b = buckets.setdefault(
                idx, {'start': idx * EPISODE_CHUNK + 1, 'end': (idx + 1) * EPISODE_CHUNK, 'count': 0}
            )
            b['count'] += 1
    return [buckets[k] for k in sorted(buckets)]


# ══ Board assembly ════════════════════════════════════════════════════════════
def _card(item: dict, version: str = '') -> dict:
    """Trim a library entry down to what the board needs."""
    return {
        'id': item['id'],
        'title': item.get('title') or item.get('filename', ''),
        'version': version,
        'year': item.get('year'),
        'duration': item.get('duration') or 0,
        'width': item.get('width') or 0,
        'height': item.get('height') or 0,
        'vcodec': item.get('vcodec') or '',
        'acodec': item.get('acodec') or '',
        'size': item.get('size') or 0,
        'direct': bool(item.get('direct')),
        'transcode_reason': item.get('transcode_reason') or '',
        'subs': len(item.get('subs') or []),
        'audio': len(item.get('audio') or []),
        'kind': item.get('kind', 'movie'),
        'season': item.get('season'),
        'episode': item.get('episode'),
        'episode_title': item.get('episode_title', ''),
        'added_at': item.get('added_at'),
    }


def board() -> dict:
    """Movies list + series (grouped by show, then season, then episode)."""
    lib = load_library()
    items = list((lib.get('items') or {}).values())
    versions = version_suffixes(items)
    movies = sorted(
        [_card(i, versions.get(i['id'], '')) for i in items if i.get('kind') != 'episode'],
        key=lambda c: ((c['title'] or '').lower(), c['year'] or 0, c.get('version') or ''),
    )

    names = lib.get('series_names') or {}
    shows: dict[str, dict] = {}
    for it in items:
        if it.get('kind') != 'episode':
            continue
        key = (display_series(it, names) or 'Unknown').strip()
        show = shows.setdefault(key, {'title': key, 'seasons': {}, 'episodes': 0, 'poster': None, 'duration': 0})
        card = _card(it)
        season = str(it.get('season') or 1)
        show['seasons'].setdefault(season, []).append(card)
        show['episodes'] += 1
        show['duration'] += card['duration']
        if show['poster'] is None:
            show['poster'] = card['id']

    series = []
    for show in shows.values():
        seasons = [
            {'season': int(s), 'episodes': sorted(eps, key=lambda e: e['episode'] or 0)}
            for s, eps in show['seasons'].items()
        ]
        seasons.sort(key=lambda s: s['season'])
        show['seasons'] = seasons
        show['ranges'] = assign_absolute(seasons)
        series.append(show)
    series.sort(key=lambda s: (s['title'] or '').lower())

    return {
        'movies': movies,
        'series': series,
        'roots': lib.get('roots') or [],
        'updated_at': lib.get('updated_at'),
        'count': len(items),
    }


def get_item(item_id: str) -> dict | None:
    return (load_library().get('items') or {}).get(item_id)


def item_detail(item_id: str) -> dict | None:
    """Everything the player needs for one title."""
    lib = load_library()
    it = (lib.get('items') or {}).get(item_id)
    if not it:
        return None
    d = _card(it, version_suffixes(list((lib.get('items') or {}).values())).get(item_id, ''))
    d['subs'] = [
        {
            'id': s['id'],
            'label': s['label'],
            'lang': s.get('lang', ''),
            'text': bool(s.get('text')),
            'kind': s.get('kind'),
            'forced': bool(s.get('forced')),
            'sdh': bool(s.get('sdh')),
        }
        for s in it.get('subs') or []
    ]
    d['audio'] = [
        {
            'id': i,
            'label': _audio_label(t, i),
            'lang': t.get('lang', ''),
            'channels': t.get('channels', 0),
            'codec': t.get('codec', ''),
        }
        for i, t in enumerate(it.get('audio') or [])
    ]
    # Defaults are resolved HERE, not at scan time: changing a preference then
    # takes effect on the next title opened instead of on the next full rescan.
    names = lib.get('series_names') or {}
    pref = prefs_for(it, names)
    d['default_sub'] = pick_default_sub(it.get('subs') or [], pref) or it.get('default_sub') or ''
    d['default_audio'] = pick_default_audio(it.get('audio') or [], pref)
    d['filename'] = it.get('filename', '')
    d['series'] = display_series(it, names) if it.get('kind') == 'episode' else it.get('series')
    d['series_named'] = bool(names.get(it.get('folder') or ''))
    d['show_key'] = item_show_key(it, names)
    if 'chapters' not in it:
        # Indexed before chapters were read; fill it in once, on first open.
        chs = chapters_of(it.get('path') or '')
        it['chapters'] = chs
        with _lock:
            live = load_library()
            entry = (live.get('items') or {}).get(item_id)
            if entry is not None:
                entry['chapters'] = chs
                save_library(live)
    d['chapters'] = it.get('chapters') or []
    d['marks'] = detect_marks(it, pref)
    d['prefs'] = {k: pref[k] for k in DEFAULT_PREFS if k in pref}
    d['prefs_overrides'] = pref.get('_overrides') or []
    return d


def _audio_label(track: dict, i: int) -> str:
    lang = _lang_label(track.get('lang', ''), '') or 'Track'
    bits = [lang]
    title = (track.get('title') or '').strip()
    if title and len(title) <= 60 and not _QUALITY_RE.search(title):
        bits.append(title)
    ch = track.get('channels') or 0
    layout = {1: 'Mono', 2: 'Stereo', 6: '5.1', 8: '7.1'}.get(ch, f'{ch}ch' if ch else '')
    tail = ' · '.join(x for x in [(track.get('codec') or '').upper(), layout] if x)
    label = ' — '.join(bits)
    return f'{label} ({tail})' if tail else f'{label} {i + 1}'
