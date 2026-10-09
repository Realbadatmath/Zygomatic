# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sports_ingest.thesportsdb — TheSportsDB: badges, cutouts, country.

Verbatim section of the original sports_ingest.py (lines 553-878); no logic changes.
"""

from __future__ import annotations

import os
import re
import time

import requests

from zyg_workflows.sports_ingest.constants import (
    CATEGORIES,
    _ART_DIR,
    _HDRS,
    _LOCK,
    _NEG_TTL,
    _TEAMS_PATH,
    _TSDB_BASE,
    _TSDB_GAP,
    _zyg_log,
)
from zyg_workflows.sports_ingest.helpers import _load, _save, settings


# ── TheSportsDB: badges, cutouts, country ───────────────────────────────────


def _tsdb_get(endpoint, params):
    key = (settings().get('thesportsdb_key') or '3').strip() or '3'
    try:
        r = requests.get(f'{_TSDB_BASE}/{key}/{endpoint}', params=params, headers=_HDRS, timeout=20)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def _team_cache() -> dict:
    return _load(_TEAMS_PATH, {})


def _team_cache_put(key, rec):
    with _LOCK:
        d = _load(_TEAMS_PATH, {})
        d[key] = rec
        if len(d) > 4000:
            d = dict(list(d.items())[-3000:])
        _save(_TEAMS_PATH, d)


_PAREN_RE = re.compile(r'\s*\([^)]*\)\s*')


def _norm_name(name: str) -> str:
    return _PAREN_RE.sub(' ', (name or '')).strip()


# Odds-API name → the query TheSportsDB actually answers. VERIFIED entries only
# (live-tested from this host): "FC Zwolle" finds nothing but a Belgian
# basketball club, while "PEC Zwolle" returns the real Eredivisie side with its
# badge. Keys are lowercase _norm_name() forms.
_TSDB_QUERY_ALIASES = {
    'fc zwolle': 'PEC Zwolle',
}


# The country a whitelisted competition implies. Used to disambiguate club names
# and to decide whether a lookup can be trusted. Competitions spanning several
# countries deliberately have NO hint.
_LEAGUE_COUNTRY = {
    'soccer_epl': 'England',
    'soccer_england_efl_cup': 'England',
    'soccer_spain_la_liga': 'Spain',
    'soccer_spain_copa_del_rey': 'Spain',
    'soccer_italy_serie_a': 'Italy',
    'soccer_italy_coppa_italia': 'Italy',
    'soccer_germany_bundesliga': 'Germany',
    'soccer_germany_dfb_pokal': 'Germany',
    'soccer_france_ligue_one': 'France',
    'soccer_netherlands_eredivisie': 'Netherlands',
    'soccer_portugal_primeira_liga': 'Portugal',
    'soccer_belgium_first_div': 'Belgium',
    'soccer_spl': 'Scotland',
    'soccer_brazil_campeonato': 'Brazil',
    'soccer_argentina_primera_division': 'Argentina',
    'soccer_usa_mls': 'United States',
    'basketball_nba': 'United States',
    'basketball_wnba': 'United States',
    'americanfootball_nfl': 'United States',
    'americanfootball_nfl_preseason': 'United States',
}

_TEAM_NOISE_RE = re.compile(
    r'\b(fc|cf|ca|sc|ac|as|sv|vv|bk|if|sk|ks|ksv|cd|ud|rc|afc|cfc|club|de|'
    r'футбол)\b',
    re.I,
)


_COUNTRY_ALIAS = {
    'the netherlands': 'netherlands',
    'holland': 'netherlands',
    'usa': 'united states',
    'us': 'united states',
    'united states of america': 'united states',
    'uk': 'united kingdom',
    'great britain': 'united kingdom',
    'south korea': 'korea republic',
    'republic of ireland': 'ireland',
}


def _country_key(s: str) -> str:
    """TheSportsDB says "The Netherlands"; the whitelist says "Netherlands". Left
    unnormalised, every Eredivisie club scored a country MISMATCH and dropped to
    low confidence."""
    c = ' '.join((s or '').strip().lower().split())
    return _COUNTRY_ALIAS.get(c, c)


def _name_key(s: str) -> str:
    """Comparable form of a club/player name: lowercase, unaccented, no filler."""
    import unicodedata

    s = unicodedata.normalize('NFKD', _norm_name(s))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    s = _TEAM_NOISE_RE.sub(' ', s)
    return ' '.join(s.split())


# Reserve/youth/women squad markers. 2026-08-07: TheSportsDB's search for
# "FC Porto" returns ONLY "FC Porto Juniors" (the first team is stored under
# another spelling), and a prefix match + right sport + right country scored
# that B-team HIGH — its badge went on air next to a Primeira Liga bet and the
# presenter said "F C Porto Juniors" seven times. An extension word from this
# list means a DIFFERENT squad, whatever the rest of the name says.
_VARIANT_RE = re.compile(
    r'^(?:juniors?|b|ii|iii|u\d{2}|under\d{2}|reserves?|youth|academy|'
    r'women|ladies|femin\w*|femen\w*)$',
    re.I,
)


def _variant_mismatch(target_key: str, cand_key: str) -> bool:
    extra = set((cand_key or '').split()) - set((target_key or '').split())
    return any(_VARIANT_RE.match(w) for w in extra)


def _pick_row(
    rows: list, want_name: str, want_sport: str, want_country: str, name_field: str, country_field: str
) -> tuple:
    """(best_row, confidence, country_conflict, variant_mismatch). Scored, not
    first-match.

    Taking rows[0] resolved "pumas" to a South African club, "tigres" to a
    Colombian one and "estudiantes" to a Spanish one. That is not just an ugly
    badge: a wrong country feeds the Asia/Africa filter, so a mis-resolved club
    could silently delete a legitimate fixture from the card.
    """
    target = _name_key(want_name)
    best, best_score = None, -99
    for r in rows or []:
        score = 0
        cand = _name_key(r.get(name_field) or '')
        if cand == target:
            score += 6
        elif cand.startswith(target) or target.startswith(cand):
            score += 3
        elif target and cand and (target in cand or cand in target):
            score += 2
        else:
            score -= 2
        if _variant_mismatch(target, cand):
            score -= 8  # a reserve/youth/women squad is a wrong club
        if (r.get('strSport') or '') == want_sport:
            score += 3
        else:
            score -= 4
        rc = _country_key(r.get(country_field) or '')
        if want_country:
            if rc == _country_key(want_country):
                score += 4
            elif rc:
                score -= 5  # right name, wrong country = wrong club
        if score > best_score:
            best, best_score = r, score
    # "high" means: the name really matches AND the sport is right AND, when the
    # competition implies a country, the country agrees. Only a high-confidence
    # record is allowed to drive the continent exclusion.
    conflict, variant = False, False
    if best is not None:
        if want_country:
            rc = _country_key(best.get(country_field) or '')
            conflict = bool(rc) and rc != _country_key(want_country)
        variant = _variant_mismatch(target, _name_key(best.get(name_field) or ''))
    conf = 'high' if (best_score >= 7 and not variant) else 'low'
    return best, conf, conflict, variant


def lookup_entity(name: str, category: str, league_hint: str = '') -> dict:
    """{display, country, image, image_kind, source, resolved, confidence, …}.

    Successful lookups are cached forever (Arsenal's badge does not change).
    FAILURES are cached for `_NEG_TTL` only: the shared free key rate-limits, and
    caching a rate-limited miss forever meant West Ham, PSV, Southampton and 77
    others were permanently badge-less after one bad minute.
    """
    cat = CATEGORIES.get(category) or {}
    entity = cat.get('entity', 'team')
    key = f'{category}::{(name or "").lower().strip()}'
    cache = _team_cache()
    hit = cache.get(key)
    if hit:
        if hit.get('resolved') and not hit.get('cache_retry'):
            return hit
        try:
            # negative rows AND untrusted resolved rows expire after _NEG_TTL
            if (time.time() - float(hit.get('ts') or 0)) < _NEG_TTL:
                return hit
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('cached club entry has an unusable ts, refetching: %s', _exc)

    want_country = _LEAGUE_COUNTRY.get(league_hint or '', '')
    rec = {
        'name': name,
        'display': name,
        'country': '',
        'image': '',
        'image_kind': '',
        'source': '',
        'creative_commons': None,
        'resolved': False,
        'confidence': 'none',
        'ts': time.time(),
    }
    q = _norm_name(name)
    q = _TSDB_QUERY_ALIASES.get(q.lower(), q)
    if q:
        endpoint, param, nf, cf = (
            ('searchplayers.php', 'p', 'strPlayer', 'strNationality')
            if entity == 'player'
            else ('searchteams.php', 't', 'strTeam', 'strCountry')
        )
        rows = None
        for attempt in range(2):  # one retry: an empty body is usually the limiter
            d = _tsdb_get(endpoint, {param: q})
            rows = (d or {}).get('player' if entity == 'player' else 'teams') or []
            if rows:
                break
            time.sleep(_TSDB_GAP * (attempt + 2))
        row, conf, conflict, variant = _pick_row(rows, name, cat.get('tsdb_sport'), want_country, nf, cf)
        if conf != 'high' and entity == 'team':
            # Second pass with the noise-stripped name: TheSportsDB's search for
            # "FC Porto" returns only the Juniors squad, while "Porto" finds the
            # first team. Only replaces the pick when it genuinely scores better.
            q2 = ' '.join(w for w in _norm_name(name).split() if not _TEAM_NOISE_RE.fullmatch(w))
            if q2 and q2.lower() != q.lower():
                time.sleep(_TSDB_GAP)
                d2 = _tsdb_get(endpoint, {param: q2})
                rows2 = (d2 or {}).get('teams') or []
                if rows2:
                    row2, conf2, conflict2, variant2 = _pick_row(
                        rows2, name, cat.get('tsdb_sport'), want_country, nf, cf
                    )
                    if row2 is not None and conf2 == 'high':
                        row, conf, conflict, variant = row2, conf2, conflict2, variant2
        if row:
            trusted = conf == 'high' and not conflict and not variant
            rec['confidence'] = conf
            rec['country_conflict'] = conflict
            rec['variant_mismatch'] = variant
            rec['resolved'] = True
            rec['source'] = 'TheSportsDB'
            rec['creative_commons'] = row.get('strCreativeCommons')
            # An untrusted match may never RENAME the team on air — the raw
            # fixture name is the truth, the lookup only decorates it. 2026-08-07:
            # "FC Zwolle" matched a Belgian BASKETBALL club called "Zwolle" (the
            # only row TheSportsDB returns) and its "_No League Basketball ·
            # Belgium" line was printed on the focus card next to an Eredivisie
            # bet. Wrong-club metadata is worse than no metadata.
            rec['display'] = (row.get(nf) or name) if trusted else name
            rec['country'] = (row.get(cf) or '').strip()
            rec['tsdb_id'] = row.get('idPlayer' if entity == 'player' else 'idTeam') or ''
            if entity == 'player':
                rec['image'] = row.get('strCutout') or row.get('strThumb') or row.get('strRender') or ''
                rec['image_kind'] = 'cutout' if row.get('strCutout') else 'thumb'
                rec['team'] = (row.get('strTeam') or '').strip()
            else:
                rec['image'] = row.get('strBadge') or row.get('strLogo') or ''
                rec['image_kind'] = 'badge' if row.get('strBadge') else 'logo'
                rec['league'] = (row.get('strLeague') or '').strip()
            if not trusted:
                # The competition says one country and the matched club says
                # another, so this is almost certainly a different club with the
                # same name ("Pumas" resolved to a South African side) — or the
                # match is a reserve/youth/women squad of the right club ("FC
                # Porto" → "FC Porto Juniors"), or the name barely matched at
                # all. Keep the fixture, but do NOT put a stranger's crest,
                # league line or team line on screen next to a bet — the
                # initials card with the raw fixture name is the honest
                # fallback.
                rec['image'] = ''
                rec['image_kind'] = ''
                rec['league'] = ''
                rec['team'] = ''
    # An untrusted "resolved" row must NOT be cached forever like a good one —
    # "FC Zwolle"→Belgian basketball sat in the cache permanently and poisoned
    # every later episode. Mark it so the cache treats it like a miss (_NEG_TTL)
    # and the lookup gets retried once the TTL lapses.
    if rec['resolved'] and not (
        rec.get('confidence') == 'high' and not rec.get('country_conflict') and not rec.get('variant_mismatch')
    ):
        rec['cache_retry'] = True
    _team_cache_put(key, rec)
    time.sleep(_TSDB_GAP)  # shared free key — 0.3 s got us rate-limited
    return rec


def download_art(rec: dict) -> str:
    """Cache the badge/cutout on disk, unmodified. Returns a local path or ''."""
    url = (rec or {}).get('image') or ''
    if not url:
        return ''
    ext = os.path.splitext(url.split('?')[0])[1].lower()
    if ext not in ('.png', '.jpg', '.jpeg', '.webp'):
        ext = '.png'
    # the filename carries a hash of the URL: keyed on display name alone, a
    # player's NEW photo (API-Sports swap) silently reused the OLD cutout that
    # was already on disk under the same name — 2026-08-08, Felipe Jonatan's
    # replaced Mirassol shirt came back from this cache
    import hashlib as _hl_art

    safe = re.sub(r'[^A-Za-z0-9._-]', '_', f'{rec.get("display") or "x"}')[:52]
    tag = _hl_art.md5(url.encode(), usedforsecurity=False).hexdigest()[:8]
    path = os.path.join(_ART_DIR, f'{safe}_{tag}{ext}')
    if os.path.isfile(path) and os.path.getsize(path) > 500:
        return path
    try:
        os.makedirs(_ART_DIR, exist_ok=True)
        r = requests.get(url, headers=_HDRS, timeout=25)
        if r.status_code != 200 or len(r.content) < 500:
            return ''
        tmp = path + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(r.content)
        os.replace(tmp, path)
        return path
    except Exception:
        return ''
