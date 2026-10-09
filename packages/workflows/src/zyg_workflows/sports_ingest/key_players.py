# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sports_ingest.key_players — key players per team (operator enhancement 2026-08-07).

Verbatim section of the original sports_ingest.py (lines 879-1113); no logic changes.
"""

from __future__ import annotations

import os
import re
import time

from zyg_workflows.sports_ingest.constants import CATEGORIES, _LOCK, _NEG_TTL, _TEAMS_PATH, _TSDB_GAP, _zyg_log
from zyg_workflows.sports_ingest.helpers import _load, _save
from zyg_workflows.sports_ingest.thesportsdb import _team_cache, _team_cache_put, _tsdb_get, download_art, lookup_entity
from zyg_workflows.sports_ingest.photos import _squad_lookup, apisports_squad, espn_headshot


# ── key players per team (operator enhancement 2026-08-07) ──────────────────
# "when club badge is shown, also show 1-3 of the most important players to that
# team next to / around the badge". TheSportsDB has no importance metric on the
# free key and lookup_all_players caps at ~10 roster rows (verified 2026-08-07,
# Ajax → 10 rows incl. the manager), so "important" is a heuristic: attacking
# positions first, then midfield, then defence, and only players with real
# artwork — a name with no face is dead weight on a badge card.

_PLAYER_POS_SCORE = (
    (re.compile(r'forward|striker|winger|attack', re.I), 3),
    (re.compile(r'midfield', re.I), 2),
    (re.compile(r'back|defen[cs]e|defender', re.I), 1),
    (re.compile(r'keeper|goalie', re.I), 0),
)
_PLAYER_TTL = 7 * 86400.0  # squads change; badges do not

# WRONG-SHIRT DEFENSE (operator 2026-08-07: two Coritiba cutouts on air wore
# Palmeiras and Ceará kits). TheSportsDB image URLs end in their UPLOAD EPOCH
# (…cutout/xxxxxx1705225875.png) — measured on the Coritiba squad: the two
# wrong-shirt cutouts were 14 months old (pre-transfer), every 7-month upload
# wore the correct kit. So artwork RECENCY outranks position when choosing the
# players that go on a badge card.
_ART_FRESH_S = float(os.environ.get('ZYG_TSDB_ART_FRESH_DAYS', '300') or 300) * 86400.0


def _art_epoch(url: str) -> int:
    m = re.search(r'(\d{10})\.\w+$', (url or '').split('?')[0])
    return int(m.group(1)) if m else 0


def _team_colours(tid: str) -> list:
    """Official club colours [(r,g,b), …] via lookupteam.php (cached with the
    player list). TheSportsDB carries strColour1-3 per club."""
    d = _tsdb_get('lookupteam.php', {'id': tid})
    time.sleep(_TSDB_GAP)
    row = ((d or {}).get('teams') or [{}])[0]
    out = []
    for k in ('strColour1', 'strColour2', 'strColour3'):
        hx = (row.get(k) or '').strip().lstrip('#')
        if len(hx) == 6:
            try:
                out.append(tuple(int(hx[i : i + 2], 16) for i in (0, 2, 4)))
            except ValueError as _exc:
                _zyg_log.debug('palette colour %r unparsable, skipped: %s', hx, _exc)
    return out


def _shirt_matches(img_path: str, colours: list):
    """Does the cutout's SHIRT match the club palette? True/False/None(=unknown).

    Freshness alone still let a Mirassol-yellow cutout onto a Coritiba card
    (7-month upload, mid-window transfer). The decisive check is visual: the
    dominant torso colour of the cutout must sit near one of the club's
    official colours — white is always allowed (the universal away kit), black
    is not (it would excuse almost any kit). Unknown (thumbs, unreadable art,
    no palette) passes: this gate exists to kill confident mismatches, not to
    strip cards bare."""
    if not colours:
        return None
    try:
        from PIL import Image

        im = Image.open(img_path).convert('RGBA')
    except Exception:
        return None
    w, h = im.size
    if not w or not h:
        return None
    band = im.crop((int(w * 0.30), int(h * 0.55), int(w * 0.70), int(h * 0.88)))
    data = list(band.getdata())
    opaque = all(a == 255 for _r, _g, _b, a in data[::37])
    px = [(r, g, b) for r, g, b, a in data if a > 200]
    if opaque:
        # square studio headshot (API-Sports style): the flat near-white /
        # near-grey backdrop is not shirt — drop it before judging, or a red
        # away-club kit passes on its background alone
        px = [p for p in px if not (min(p) > 225 or (max(p) - min(p) < 12 and min(p) > 150))]
    px = [
        p for p in px if not (p[0] > 95 and p[1] > 40 and p[2] > 20 and p[0] > p[1] > p[2] and (p[0] - p[2]) > 15)
    ]  # skin
    if len(px) < 200:
        return None
    from collections import Counter

    dom = [
        c
        for c, _n in Counter(
            ((r // 32) * 32 + 16, (g // 32) * 32 + 16, (b // 32) * 32 + 16) for r, g, b in px
        ).most_common(2)
    ]
    pal = list(colours) + [(255, 255, 255)]

    def _close(c, p):
        # near-black (beard shadow, dark collars) may only match a genuinely
        # near-black palette entry — at a loose threshold (16,16,16) sat within
        # range of Coritiba's DARK GREEN and let a Fortaleza-kit photo through
        if max(c) < 60 and max(p) >= 80:
            return False
        # white/light-grey kits photograph grey — treat any light low-chroma
        # dominant as white (away kits are the reason white is always allowed)
        if min(c) > 180 and (max(c) - min(c)) < 45 and min(p) > 245:
            return True
        return sum((a - b) ** 2 for a, b in zip(c, p)) < 72**2

    return any(_close(c, p) for c in dom for p in pal)


def _position_score(pos: str) -> int:
    for pat, sc in _PLAYER_POS_SCORE:
        if pat.search(pos or ''):
            return sc
    return 1


def team_players(name: str, category: str, league_hint: str = '', want: int = 3) -> list:
    """Up to `want` notable players for a team: [{name, position, image, …}].

    Cached per TheSportsDB team id for _PLAYER_TTL. Returns [] for player-entity
    categories, unresolved teams and teams whose lookup predates tsdb_id capture
    on a cache row that cannot be refreshed."""
    if (CATEGORIES.get(category) or {}).get('entity') != 'team':
        return []
    ent = lookup_entity(name, category, league_hint)
    if not ent.get('resolved') or ent.get('confidence') != 'high':
        return []
    tid = ent.get('tsdb_id')
    if not tid:
        # cache row from before tsdb_id existed — drop it once and re-resolve
        key = f'{category}::{(name or "").lower().strip()}'
        with _LOCK:
            d = _load(_TEAMS_PATH, {})
            if key in d:
                del d[key]
                _save(_TEAMS_PATH, d)
        ent = lookup_entity(name, category, league_hint)
        tid = ent.get('tsdb_id')
    if not tid:
        return []

    pkey = f'players::{category}::{tid}'
    cache = _team_cache()
    hit = cache.get(pkey)
    if hit:
        try:
            if (time.time() - float(hit.get('ts') or 0)) < (_PLAYER_TTL if hit.get('players') else _NEG_TTL):
                return (hit.get('players') or [])[:want]
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('cached player entry has an unusable ts, refetching: %s', _exc)

    d = _tsdb_get('lookup_all_players.php', {'id': tid})
    rows = (d or {}).get('player') or []
    time.sleep(_TSDB_GAP)
    out = []
    for r in rows:
        pos = (r.get('strPosition') or '').strip()
        if re.search(r'manager|coach|staff', pos, re.I):
            continue
        img = r.get('strCutout') or r.get('strThumb') or r.get('strRender') or ''
        if not img or not (r.get('strPlayer') or '').strip():
            continue
        ats = _art_epoch(img)
        out.append(
            {
                'name': r.get('strPlayer').strip(),
                'position': pos,
                'image': img,
                'image_kind': 'cutout' if r.get('strCutout') else 'thumb',
                'source': 'TheSportsDB',
                'creative_commons': r.get('strCreativeCommons'),
                'art_ts': ats,
                'art_fresh': bool(ats) and (time.time() - ats) < _ART_FRESH_S,
                '_score': _position_score(pos),
            }
        )
    # fresh shirt first, then position, then newest upload
    out.sort(key=lambda p: (p['art_fresh'], p['_score'], p['art_ts']), reverse=True)
    for p in out:
        p.pop('_score', None)
    # CURRENT-SQUAD FILTER: API-Sports' squad list is this-season truth. A
    # TheSportsDB cutout of a player who has transferred away is simply not in
    # it — the whole wrong-shirt class dies here when the squad is available.
    squad = apisports_squad(category, name)
    if squad:
        members = [p for p in out if _squad_lookup(squad, p['name'])]
        if members:
            out = members
        else:
            _zyg_log.info(
                f'[SPORTS-ART] {name}: no TSDB candidate matched the API-Sports squad — keeping unfiltered list'
            )

    # SHIRT GATE: a candidate only makes the card when its artwork verifiably
    # matches the club — colour-checked cutout, or a current-season photo
    # (API-Sports first, ESPN second) for the ones that fail. A confident
    # mismatch with no substitute photo is dropped entirely: one fewer player
    # beats a Mirassol shirt on a Coritiba card.
    colours = _team_colours(tid)
    picked, rejected = [], []
    for p in out:
        if len(picked) >= want:
            break
        verdict = None
        if p['image_kind'] == 'cutout':
            lp = download_art({'image': p['image'], 'display': p['name']})
            verdict = _shirt_matches(lp, colours) if lp else None
        if p['art_fresh'] and verdict is not False:
            picked.append(p)
            continue
        # STALE art never airs on a colour coincidence — a 14-month Palmeiras
        # cutout is the same green as Coritiba. Stale or colour-failed players
        # need a substitute photo that itself passes the gate, or they're out.
        subs = []
        if squad:
            subs.append(('API-SPORTS', _squad_lookup(squad, p['name']).get('photo') or ''))
        subs.append(('ESPN', espn_headshot(name, category, league_hint, p['name'])))
        swapped = False
        for src, sub in subs:
            if not sub:
                continue
            sp = download_art({'image': sub, 'display': p['name']})
            if not sp or _shirt_matches(sp, colours) is False:
                continue
            p.update(image=sub, image_kind='headshot', source=src, creative_commons=None)
            picked.append(p)
            swapped = True
            break
        if not swapped:
            rejected.append(p['name'])
    if rejected:
        _zyg_log.info(f'[SPORTS-ART] {name}: no shirt-verified art for {", ".join(rejected[:5])} — not shown')
    _team_cache_put(pkey, {'ts': time.time(), 'players': picked[:6]})
    return picked[:want]
