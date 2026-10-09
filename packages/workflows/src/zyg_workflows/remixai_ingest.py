# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""remixai_ingest.py — discovery + download for the Remix Ai department (2026-08-29).

Finds popular AI-GENERATED videos by keyword sweep (operator-editable term list),
ranks them by view velocity, keeps a dedupe ledger so the same source is never
worked twice, and downloads the winner with its metadata.

Discovery is `ytsearch` through yt-dlp, NOT the Data API: search.list costs 100
quota units per call (the whole daily budget is 10 000), and a flat yt-dlp
extraction gets the same ranked list for zero quota. This mirrors the zero-quota
choice already made in remix_ingest.py for channel polling.

"Popular" is VIEW VELOCITY (views per hour since publish), not raw views. Raw
views rank a 4-year-old video above everything current; velocity is what actually
identifies a format working RIGHT NOW, which is the only reason to study one.

AI-provenance: a search term is a weak signal on its own (a video ABOUT AI is not
an AI-GENERATED video), so every candidate is scored against title/description/tag
markers and anything under the floor is dropped. This is a heuristic, not proof —
`ai_score` rides on the candidate so the operator can see why it was kept.

Files (all under data/runtime/):
  remixai_settings.json  operator settings + search terms
  remixai_seen.json      dedupe ledger — every video_id ever swept or worked
  remixai_library.json   per-source record of what we produced from it
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from zyg_workflows import paths
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_CREWS = os.path.dirname(os.path.abspath(__file__))
_RUNTIME = os.path.join(_CREWS, 'data', 'runtime')

_SETTINGS_F = os.path.join(_RUNTIME, 'remixai_settings.json')
_SEEN_F = os.path.join(_RUNTIME, 'remixai_seen.json')
_LIBRARY_F = os.path.join(_RUNTIME, 'remixai_library.json')

_IO_LOCK = threading.RLock()

# Cookies: reused from the remix department when present (same browser profile,
# same host). Absent is fine — search and most downloads work without it.
_COOKIES = os.environ.get('ZYG_YTDLP_COOKIES', '').strip()

DEFAULT_TERMS = [
    'ai generated video',
    'ai short film',
    'sora ai video',
    'veo 3 ai video',
    'ai animation short',
    'midjourney animation',
    'runway gen 3 video',
    'ai cinematic short',
]

# Title/description/tag markers that a video is AI-GENERATED rather than merely
# about AI. Weighted: a generator NAME is far stronger evidence than the bare
# token "ai", which appears in every commentary video on the platform.
_AI_MARKERS_STRONG = (
    'sora',
    'veo 3',
    'veo3',
    'runway gen',
    'gen-3',
    'gen 3',
    'kling ai',
    'midjourney',
    'stable diffusion',
    'pika labs',
    'luma dream machine',
    'haiper ai',
    'hailuo',
    'minimax video',
    'wan 2.',
    'animatediff',
    'made with ai',
    'generated with ai',
    'ai generated',
    'ai-generated',
)
_AI_MARKERS_WEAK = (
    'ai video',
    'ai film',
    'ai short',
    'ai animation',
    'ai art',
    'text to video',
    'text-to-video',
    'img2vid',
    'prompt to video',
)

_DEFAULTS = {
    'terms': list(DEFAULT_TERMS),
    'per_term': 12,  # yt-dlp flat-search depth per term
    'sweep_sec': 3600,  # discovery cadence — velocity does not move fast
    'min_views': 20000,  # floor: below this "popular" is noise
    'max_age_days': 21,  # a format older than 3 weeks is no longer current
    'min_duration_s': 15,
    'max_duration_s': 900,
    'min_ai_score': 2,  # provenance floor (strong=2, weak=1, capped)
    'auto_mode': False,  # never auto-run until the operator turns it on
    'daily_cap': 4,
    'lang': 'en',
}


# ── tiny json store (remix_ingest.py shape) ─────────────────────────────────


def _load(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp, path)


def settings() -> dict:
    with _IO_LOCK:
        s = dict(_DEFAULTS)
        s.update(_load(_SETTINGS_F, {}) or {})
        if not s.get('terms'):
            s['terms'] = list(DEFAULT_TERMS)
        return s


def save_settings(patch: dict) -> dict:
    with _IO_LOCK:
        s = settings()
        for k, v in (patch or {}).items():
            if k in _DEFAULTS:
                s[k] = v
        _save(_SETTINGS_F, s)
        return s


def seen() -> dict:
    with _IO_LOCK:
        return _load(_SEEN_F, {}) or {}


def mark_seen(video_id: str, **fields):
    """Ledger write. `state` is the load-bearing field:
    'swept'  — discovered, never worked
    'worked' — a pipeline consumed it (never offered again)
    'failed' — a pipeline tried and failed (offered again after a cooldown)"""
    if not video_id:
        return
    with _IO_LOCK:
        led = _load(_SEEN_F, {}) or {}
        rec = led.get(video_id) or {}
        rec.update(fields)
        rec.setdefault('first_seen', time.time())
        rec['updated'] = time.time()
        led[video_id] = rec
        # bound the ledger: keep the 4000 most recent, always keep 'worked'
        if len(led) > 4000:
            keep = {k: v for k, v in led.items() if v.get('state') == 'worked'}
            rest = sorted(
                ((k, v) for k, v in led.items() if k not in keep), key=lambda kv: kv[1].get('updated', 0), reverse=True
            )[:3000]
            led = dict(list(keep.items()) + rest)
        _save(_SEEN_F, led)


def library() -> list:
    with _IO_LOCK:
        return _load(_LIBRARY_F, []) or []


def library_add(rec: dict):
    with _IO_LOCK:
        lib = _load(_LIBRARY_F, []) or []
        lib.insert(0, rec)
        _save(_LIBRARY_F, lib[:800])


# ── AI-provenance scoring ───────────────────────────────────────────────────


def ai_score(title: str, description: str = '', tags=None) -> int:
    """Weighted marker count. Strong markers (a named generator, an explicit
    'made with AI') score 2; weak ones ('ai video') score 1. Capped at 6 so one
    keyword-stuffed description cannot outrank genuine signal."""
    hay = ' '.join([(title or ''), (description or '')[:1200], ' '.join(tags or [])]).lower()
    score = 0
    for m in _AI_MARKERS_STRONG:
        if m in hay:
            score += 2
    for m in _AI_MARKERS_WEAK:
        if m in hay:
            score += 1
    return min(score, 6)


def velocity(view_count, published_ts) -> float:
    """Views per hour since publish. The ranking signal — raw view counts rank
    an old evergreen above everything current, which is the opposite of useful."""
    try:
        views = float(view_count or 0)
    except (TypeError, ValueError):
        return 0.0
    if not published_ts:
        return 0.0
    age_h = max(1.0, (time.time() - float(published_ts)) / 3600.0)
    return views / age_h


# ── yt-dlp ──────────────────────────────────────────────────────────────────


def _ydl_opts(extra: dict = None) -> dict:
    opts = {'quiet': True, 'no_warnings': True, 'skip_download': True, 'ignoreerrors': True, 'socket_timeout': 20}
    if _COOKIES and os.path.isfile(_COOKIES):
        opts['cookiefile'] = _COOKIES
    if extra:
        opts.update(extra)
    return opts


def search_term(term: str, limit: int = 12) -> list:
    """One flat yt-dlp search. Flat extraction returns id/title/views/duration
    without touching each watch page — one request for the whole page of hits."""
    try:
        import yt_dlp
    except Exception:
        return []
    out = []
    try:
        with yt_dlp.YoutubeDL(_ydl_opts({'extract_flat': 'in_playlist'})) as ydl:
            info = ydl.extract_info(f'ytsearch{int(limit)}:{term}', download=False)
        for e in (info or {}).get('entries') or []:
            if not e or not e.get('id'):
                continue
            out.append(
                {
                    'video_id': e.get('id'),
                    'title': (e.get('title') or '').strip(),
                    'description': (e.get('description') or '')[:800],
                    'duration': e.get('duration') or 0,
                    'view_count': e.get('view_count') or 0,
                    'channel': (e.get('channel') or e.get('uploader') or '').strip(),
                    'channel_id': e.get('channel_id') or '',
                    'url': e.get('url') or f'https://www.youtube.com/watch?v={e.get("id")}',
                    'term': term,
                }
            )
    except Exception:
        return out
    return out


def probe(video_id: str) -> dict:
    """Full single-video metadata: upload date (for velocity), tags, description,
    thumbnail, aspect. One watch-page request — only run on candidates that
    already survived the flat-search filters."""
    try:
        import yt_dlp
    except Exception:
        return {}
    try:
        with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:
            info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False) or {}
    except Exception:
        return {}
    ts = info.get('timestamp')
    if not ts and info.get('upload_date'):
        try:
            ts = time.mktime(time.strptime(str(info['upload_date']), '%Y%m%d'))
        except Exception:
            ts = None
    w = info.get('width') or 0
    h = info.get('height') or 0
    return {
        'video_id': video_id,
        'title': (info.get('title') or '').strip(),
        'description': (info.get('description') or '')[:4000],
        'tags': info.get('tags') or [],
        'duration': info.get('duration') or 0,
        'view_count': info.get('view_count') or 0,
        'like_count': info.get('like_count') or 0,
        'channel': (info.get('channel') or info.get('uploader') or '').strip(),
        'channel_id': info.get('channel_id') or '',
        'published_ts': ts,
        'thumbnail': info.get('thumbnail') or '',
        'width': w,
        'height': h,
        'aspect': (round(w / h, 4) if (w and h) else 0.0),
        'fps': info.get('fps') or 0,
        'url': f'https://www.youtube.com/watch?v={video_id}',
    }


# ── sweep ───────────────────────────────────────────────────────────────────


def sweep(log=None, limit_terms: int = None) -> dict:
    """Run the keyword sweep, filter, probe survivors, rank by velocity.

    Two-phase on purpose: the flat search is one cheap request per TERM and
    carries enough (views/duration/title) to throw most hits away, so only the
    survivors pay for a watch-page probe. Probing every hit would be ~100
    requests a sweep for a list that ends up ranking 8."""

    def _log(m):
        if log:
            log(m)

    s = settings()
    terms = list(s['terms'])[: int(limit_terms)] if limit_terms else list(s['terms'])
    led = seen()
    raw, per_term_counts = [], {}
    for term in terms:
        hits = search_term(term, s['per_term'])
        per_term_counts[term] = len(hits)
        raw.extend(hits)
        _log(f'sweep "{term}" → {len(hits)} hit(s)')

    # dedupe within the sweep, then against the ledger
    by_id, skipped_seen = {}, 0
    for r in raw:
        vid = r['video_id']
        if vid in by_id:
            continue
        st = (led.get(vid) or {}).get('state')
        if st == 'worked':
            skipped_seen += 1
            continue
        if st == 'failed' and (time.time() - (led[vid].get('updated') or 0)) < 86400:
            skipped_seen += 1
            continue
        by_id[vid] = r

    # cheap filters BEFORE probing
    cands, dropped = [], {'views': 0, 'duration': 0, 'ai': 0}
    for r in by_id.values():
        if (r['view_count'] or 0) < s['min_views']:
            dropped['views'] += 1
            continue
        dur = r['duration'] or 0
        if dur and not (s['min_duration_s'] <= dur <= s['max_duration_s']):
            dropped['duration'] += 1
            continue
        if ai_score(r['title'], r['description']) < 1:
            dropped['ai'] += 1
            continue
        cands.append(r)

    # rank by raw views first so the probe budget goes to the best prospects
    cands.sort(key=lambda c: -(c['view_count'] or 0))
    probed = []
    for c in cands[:40]:
        info = probe(c['video_id'])
        if not info or not info.get('published_ts'):
            continue
        age_days = (time.time() - info['published_ts']) / 86400.0
        if age_days > s['max_age_days']:
            continue
        sc = ai_score(info['title'], info['description'], info.get('tags'))
        if sc < s['min_ai_score']:
            dropped['ai'] += 1
            continue
        info['term'] = c.get('term', '')
        info['ai_score'] = sc
        info['age_days'] = round(age_days, 2)
        info['velocity'] = round(velocity(info['view_count'], info['published_ts']), 1)
        probed.append(info)
        mark_seen(info['video_id'], state='swept', title=info['title'], velocity=info['velocity'], ai_score=sc)

    probed.sort(key=lambda c: -c['velocity'])
    _log(
        f'sweep done: {len(probed)} candidate(s) from {len(raw)} hit(s) '
        f'({skipped_seen} already seen, dropped views={dropped["views"]} '
        f'duration={dropped["duration"]} ai={dropped["ai"]})'
    )
    result = {
        'ts': time.time(),
        'candidates': probed,
        'terms': per_term_counts,
        'dropped': dropped,
        'skipped_seen': skipped_seen,
    }
    _save(os.path.join(_RUNTIME, 'remixai_last_sweep.json'), result)
    return result


def last_sweep() -> dict:
    return _load(os.path.join(_RUNTIME, 'remixai_last_sweep.json'), {'ts': 0, 'candidates': []}) or {
        'ts': 0,
        'candidates': [],
    }


def ranked_candidates(limit: int = 20) -> list:
    return (last_sweep().get('candidates') or [])[: int(limit)]


# ── download ────────────────────────────────────────────────────────────────

# Cookie jars, newest-wins order (remix_ingest._COOKIE_PATHS shape).
_COOKIE_PATHS = [
    os.path.join(_RUNTIME, 'youtube_cookies.txt'),
    os.path.expanduser('~/youtube_cookies.txt'),
    os.path.expanduser('~/cookies/youtube_cookies.txt'),
    str(paths.ZYG_HOME / 'youtube_cookies.txt'),
    os.path.join(_CREWS, 'youtube_cookies.txt'),
]


def _cookie_file():
    if _COOKIES and os.path.isfile(_COOKIES):
        return _COOKIES
    for p in _COOKIE_PATHS:
        if os.path.isfile(p):
            return p
    return None


def _node_bin():
    import shutil as _sh

    for p in (os.path.join(_CREWS, '..', '.venv', 'bin', 'node'), _sh.which('node')):
        if p and os.path.isfile(p):
            return os.path.abspath(p)
    return None


# Player clients to try in order. YouTube rotates which ones serve full formats
# without a challenge, and a stale pick returns 403 rather than degrading — so
# this is a LADDER, not a setting. Default first (uses cookies + the JS runtime),
# then the clients that historically survive when the web player does not.
_PLAYER_CLIENTS = ['', 'android', 'ios', 'tv', 'web_safari']


def download(video_id: str, dest_dir: str, log=None, max_height: int = 1080) -> dict:
    """Download one source video into dest_dir as '<video_id>.mp4'.

    Runs the venv's yt_dlp as a SUBPROCESS (remix_ingest.py:593 precedent — the
    in-process API and the CLI disagree on format-selector edge cases, and the
    subprocess is the one that has been reliable here).

    403 LADDER (added 2026-08-29 after the first real run died on one). The
    single-attempt version failed with 'HTTP Error 403: Forbidden' — root cause
    was a yt-dlp five months stale, which is the usual cause and is fixed by
    upgrading, not by code. But the failure mode is worth defending against: when
    YouTube next rotates, one client returning 403 should cost an extra attempt,
    not the job. Cookies and a node JS runtime are attached when present (both
    materially widen which formats are offered), and each client is tried in turn.

    NOTE the '<video_id>_transcript.json' sidecar the caller writes beside this
    file: kanban_server._api_videos treats any mp4 sharing a transcript-json
    prefix as DOWNLOADED CONTENT and excludes it from the Videos tab in both
    modes. That is how source material stays out of the inspection grid."""

    def _log(m):
        if log:
            log(m)

    os.makedirs(dest_dir, exist_ok=True)
    out = os.path.join(dest_dir, f'{video_id}.mp4')
    if os.path.isfile(out) and os.path.getsize(out) > 100_000:
        _log(f'source already present: {os.path.basename(out)}')
        return {'path': out, 'cached': True}

    fmt = f'bestvideo[height<={max_height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={max_height}][ext=mp4]/best'
    ck = _cookie_file()
    if ck:
        _log(f'using cookie jar {os.path.basename(ck)}')
    errors = []
    for client in _PLAYER_CLIENTS:
        cmd = [
            sys.executable,
            '-m',
            'yt_dlp',
            '--quiet',
            '--no-warnings',
            '--no-playlist',
            '-f',
            fmt,
            '--merge-output-format',
            'mp4',
            '--socket-timeout',
            '45',
            '--retries',
            '3',
            '--fragment-retries',
            '3',
            '-o',
            out,
            f'https://www.youtube.com/watch?v={video_id}',
        ]
        if ck:
            cmd[3:3] = ['--cookies', ck]
        if client:
            cmd[3:3] = ['--extractor-args', f'youtube:player_client={client}']
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        except subprocess.TimeoutExpired:
            errors.append(f'{client or "default"}: timeout')
            continue
        except Exception as e:
            errors.append(f'{client or "default"}: {e}')
            continue
        if r.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 100_000:
            _log(
                f'downloaded {os.path.getsize(out) / 1e6:.1f} MB via '
                f'{client or "default"} client → {os.path.basename(out)}'
            )
            return {'path': out, 'cached': False, 'client': client or 'default'}
        err = (r.stderr or '').strip()[-200:]
        errors.append(f'{client or "default"}: {err or "failed"}')
        _log(f'client {client or "default"} failed — trying next')
        try:  # never leave a partial behind
            if os.path.isfile(out) and os.path.getsize(out) <= 100_000:
                os.remove(out)
        except OSError as _exc:
            _zyg_log.debug('removal of the truncated download %s skipped: %s', out, _exc)
    return {'error': 'all player clients failed. ' + ' | '.join(errors[-3:])}


def fetch_captions(video_id: str, lang: str = 'en'):
    """YouTube auto-captions — zero GPU. No punctuation and no word timings, so
    a caller that needs either falls through to local ASR."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        api = YouTubeTranscriptApi()
        tx = api.fetch(video_id, languages=[lang])
        return [
            {'start': float(s.start), 'end': float(s.start) + float(s.duration), 'text': (s.text or '').strip()}
            for s in tx.snippets
            if (s.text or '').strip()
        ]
    except Exception:
        return None
