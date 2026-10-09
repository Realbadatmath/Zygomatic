# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""remix_ingest.py — YouTube channel watching, candidate scoring and the clip-library
index for the Remix department (2026-08-05).

Standalone module: NO crewai_web_gui import anywhere (safe to import from bp_remix
and pipeline_remix at module scope). yt_dlp is imported lazily inside functions.

State files (data/runtime/, atomic tmp+os.replace, module RLock):
  remix_channels.json     — operator-managed channel registry (tracked in git)
  remix_watermarks.json   — per-channel seen-video-id sets (gitignored)
  remix_stats.json        — per-video viewCount snapshots for the 10-day window (gitignored)
  remix_library.json      — every produced clip: source, range, score, phash (gitignored)
  remix_settings.json     — operator settings incl. auto_mode (gitignored)
  remix_broll_cache.json  — probed durations of the GameSim b-roll files (gitignored)

Design notes (all measured 2026-08-05, see project memory):
  * RSS is the poll primitive. WITHOUT a cache-buster the feed serves up to 900 s
    stale (cache-control: max-age=900); `&cb=<epoch_ms>` forces an origin hit.
  * The UULF playlist feed excludes Shorts without duration heuristics.
  * search.list is NEVER used (own bucket, 100 calls/day since 2026-06-01).
    videos.list costs 1 unit per 50 ids — the whole watcher runs on ~1-2 % of quota.
  * viewCount is lifetime-only; "views in the last 10 days" is lifetime for videos
    published inside the window (exact), else a snapshot delta.
  * Freshness gates on FIRST-SEEN time, never on <published> — livestream entries
    surface in RSS 2-8 h after their published timestamp.
"""

from __future__ import annotations

import gzip
import json
import os
import random
import re
import threading
import time
import urllib.parse
import urllib.request
import defusedxml.ElementTree as ET
from zyg_workflows import http_json
from datetime import datetime, timedelta, timezone
from zyg_workflows import paths
from zyg_workflows.bin import exe
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_CREWS = os.path.dirname(os.path.abspath(__file__))
_RUNTIME = os.path.join(_CREWS, 'data', 'runtime')

_CHANNELS_PATH = os.path.join(_RUNTIME, 'remix_channels.json')
_WATERMARKS_PATH = os.path.join(_RUNTIME, 'remix_watermarks.json')
_STATS_PATH = os.path.join(_RUNTIME, 'remix_stats.json')
_LIBRARY_PATH = os.path.join(_RUNTIME, 'remix_library.json')
_SETTINGS_PATH = os.path.join(_RUNTIME, 'remix_settings.json')
_BROLL_CACHE_PATH = os.path.join(_RUNTIME, 'remix_broll_cache.json')

_LOCK = threading.RLock()

_UA = 'Mozilla/5.0 (X11; Linux x86_64) ZygomaticRemix/1.0 (contact: operator@lan)'
_UC_RE = re.compile(r'^UC[A-Za-z0-9_-]{22}$')
_TS_COMMENT_RE = re.compile(r'(?<![\d:])(?:(\d{1,2}):)?([0-5]?\d):([0-5]\d)(?![\d:])')

DEFAULT_SETTINGS = {
    'auto_mode': False,  # watcher may auto-start remix jobs
    'poll_sec': 600,  # RSS poll cadence (60 s buys nothing vs feed lag)
    'clips_per_source': 3,  # shorts cut per source episode
    'min_score': 1.5,  # proven-candidate outlier floor
    'compile_minutes': 10,  # compilation target length (8+ min = mid-rolls)
    'narration_min_pct': 12,  # engineering floor, see bp_remix docstring
    'max_auto_per_day': 6,
}


# ── tiny io helpers (bp_storyteller_daily.py:55-71 shape) ────────────────────


def _load(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default() if callable(default) else default


def _save(path, data) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except (OSError, TypeError) as _exc:
        _zyg_log.warning('state write to %s failed, continuing without it: %s', path, _exc)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime = None) -> str:
    return (dt or _now_utc()).strftime('%Y-%m-%dT%H:%M:%S%z')


def _parse_iso(s: str):
    if not s:
        return None
    try:
        s2 = s.replace('Z', '+0000').replace('+00:00', '+0000')
        for fmt in ('%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%S.%f%z'):
            try:
                return datetime.strptime(s2, fmt)
            except ValueError as _exc:
                _zyg_log.debug('timestamp %r does not match %s: %s', s2, fmt, _exc)
                continue
    except (AttributeError, TypeError) as _exc:
        _zyg_log.debug('timestamp %r is not a parsable string: %s', s, _exc)
    return None


def youtube_api_key() -> str:
    """Env first, then the clipfarm credentials file (tools/data_tools.py:432 pattern)."""
    key = os.getenv('YOUTUBE_API_KEY', '')
    if key:
        return key
    creds = os.path.join(_RUNTIME, 'clipfarm_credentials.json')
    try:
        with open(creds) as f:
            return json.load(f).get('YOUTUBE_API_KEY', '')
    except Exception:
        return ''


def settings() -> dict:
    with _LOCK:
        s = dict(DEFAULT_SETTINGS)
        s.update(_load(_SETTINGS_PATH, {}))
        return s


def update_settings(patch: dict) -> dict:
    with _LOCK:
        s = _load(_SETTINGS_PATH, {})
        for k, v in (patch or {}).items():
            if k in DEFAULT_SETTINGS:
                s[k] = v
        _save(_SETTINGS_PATH, s)
    return settings()


# ── channel registry ─────────────────────────────────────────────────────────


def channels() -> list:
    with _LOCK:
        return _load(_CHANNELS_PATH, [])


def resolve_channel(user_input: str) -> dict:
    """Resolve whatever the operator typed (UC id / @handle / URL / name) to a
    channel record. Zero-quota: yt-dlp flat extraction, one request."""
    raw = (user_input or '').strip()
    if not raw:
        return {'error': 'empty input'}
    if _UC_RE.match(raw):
        cid, name = raw, raw
    else:
        url = raw
        if not raw.lower().startswith('http'):
            handle = raw if raw.startswith('@') else '@' + raw.replace(' ', '')
            url = f'https://www.youtube.com/{handle}/videos'
        elif '/videos' not in url:
            url = url.rstrip('/') + '/videos'
        try:
            import yt_dlp

            opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True, 'playlistend': 1, 'socket_timeout': 20}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            cid = info.get('channel_id') or info.get('uploader_id') or ''
            name = info.get('channel') or info.get('uploader') or info.get('title') or raw
            if not _UC_RE.match(cid or ''):
                return {'error': f'could not resolve a channel id from {raw!r}'}
        except Exception as e:
            return {'error': f'resolve failed: {e}'}
    # validate the feed answers
    entries = rss_poll(cid)
    if entries is None:
        return {'error': f'feed for {cid} did not answer'}
    return {'channel_id': cid, 'name': name}


def add_channel(user_input: str, clipping_permission: bool = True, notes: str = '') -> dict:
    r = resolve_channel(user_input)
    if r.get('error'):
        return r
    with _LOCK:
        chans = _load(_CHANNELS_PATH, [])
        if any(c.get('channel_id') == r['channel_id'] for c in chans):
            return {'error': 'channel already registered', 'channel_id': r['channel_id']}
        rec = {
            'channel_id': r['channel_id'],
            'name': r['name'],
            'input': user_input,
            'platform': 'youtube',
            'enabled': True,
            'clipping_permission': bool(clipping_permission),
            'notes': notes or '',
            'added_at': _iso(),
        }
        chans.append(rec)
        _save(_CHANNELS_PATH, chans)
    return rec


def remove_channel(channel_id: str) -> bool:
    with _LOCK:
        chans = _load(_CHANNELS_PATH, [])
        kept = [c for c in chans if c.get('channel_id') != channel_id]
        if len(kept) == len(chans):
            return False
        _save(_CHANNELS_PATH, kept)
    return True


def toggle_channel(channel_id: str, field: str = 'enabled') -> dict:
    if field not in ('enabled', 'clipping_permission'):
        return {'error': 'bad field'}
    with _LOCK:
        chans = _load(_CHANNELS_PATH, [])
        for c in chans:
            if c.get('channel_id') == channel_id:
                c[field] = not bool(c.get(field))
                _save(_CHANNELS_PATH, chans)
                return c
    return {'error': 'not found'}


# ── RSS polling ──────────────────────────────────────────────────────────────


def rss_poll(channel_id: str, timeout: int = 15):
    """Fetch the channel's upload feed. UULF (long-form, excludes Shorts) first,
    plain channel feed as fallback. Always cache-busted + gzip. Returns a list of
    {video_id, title, published, link} or None on total failure."""
    urls = []
    if _UC_RE.match(channel_id or ''):
        suffix = channel_id[2:]
        urls.append(f'https://www.youtube.com/feeds/videos.xml?playlist_id=UULF{suffix}')
    urls.append(f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}')
    for base in urls:
        try:
            cb = int(time.time() * 1000)
            # scheme audit: every `base` above is a literal https:// youtube.com feed URL, and the
            # gzip round trip needs the response headers, which http_json does not hand back.
            req = urllib.request.Request(  # noqa: S310  # nosec B310
                f'{base}&cb={cb}', headers={'User-Agent': _UA, 'Accept-Encoding': 'gzip'}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310  # nosec B310
                body = resp.read()
                if resp.headers.get('Content-Encoding') == 'gzip':
                    body = gzip.decompress(body)
            # strip namespaces so one parser handles Atom + media (channel_data_retrieval idiom)
            text = re.sub(r'xmlns(:\w+)?="[^"]+"', '', body.decode('utf-8', 'replace'))
            text = re.sub(r'<(/?)(?:\w+):', r'<\1', text)
            root = ET.fromstring(text)
            out = []
            for entry in root.findall('entry'):
                vid = (entry.findtext('videoId') or '').strip()
                if not vid:
                    m = re.search(
                        r'v=([\w-]{11})',
                        (entry.find('link').get('href') if entry.find('link') is not None else '') or '',
                    )
                    vid = m.group(1) if m else ''
                if not vid:
                    continue
                out.append(
                    {
                        'video_id': vid,
                        'title': (entry.findtext('title') or '').strip(),
                        'published': (entry.findtext('published') or '').strip(),
                        'link': f'https://www.youtube.com/watch?v={vid}',
                    }
                )
            return out
        except Exception as _exc:
            _zyg_log.warning('youtube feed fetch from %s failed, trying the next feed: %s', base, _exc)
            continue
    return None


def note_seen(channel_id: str, entries: list) -> list:
    """Record feed entries against the watermark; return the NEW ones (first seen now)."""
    now = _iso()
    with _LOCK:
        wm = _load(_WATERMARKS_PATH, {})
        rec = wm.setdefault(channel_id, {'seen': [], 'checked_at': '', 'consecutive_errors': 0})
        seen = set(rec.get('seen') or [])
        fresh = [e for e in (entries or []) if e['video_id'] not in seen]
        rec['seen'] = (list(seen | {e['video_id'] for e in fresh}))[-400:]
        rec['checked_at'] = now
        rec['consecutive_errors'] = 0
        _save(_WATERMARKS_PATH, wm)

        if fresh:
            stats = _load(_STATS_PATH, {})
            for e in fresh:
                stats.setdefault(
                    e['video_id'],
                    {
                        'channel_id': channel_id,
                        'title': e['title'],
                        'published': e['published'],
                        'first_seen': now,
                        'duration': None,
                        'live': None,
                        'snapshots': [],
                    },
                )
            _save(_STATS_PATH, stats)
    return fresh


def note_poll_error(channel_id: str) -> int:
    with _LOCK:
        wm = _load(_WATERMARKS_PATH, {})
        rec = wm.setdefault(channel_id, {'seen': [], 'checked_at': '', 'consecutive_errors': 0})
        rec['consecutive_errors'] = int(rec.get('consecutive_errors') or 0) + 1
        _save(_WATERMARKS_PATH, wm)
        return rec['consecutive_errors']


def watermarks() -> dict:
    with _LOCK:
        return _load(_WATERMARKS_PATH, {})


# ── Data API stats snapshots (1 unit per 50 ids; search.list is never used) ──

_ISO_DUR_RE = re.compile(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?')


def _parse_iso_duration(s: str):
    m = _ISO_DUR_RE.match(s or '')
    if not m:
        return None
    h, mnt, sec = (int(x or 0) for x in m.groups())
    return h * 3600 + mnt * 60 + sec


def refresh_stats(max_videos: int = 200) -> dict:
    """Snapshot viewCounts for tracked videos, tiered by age so quota stays ~1 %:
    <48 h: every 3 h · 2-10 d: every 12 h · 10-30 d: every 24 h · >30 d: pruned."""
    key = youtube_api_key()
    if not key:
        return {'error': 'no YOUTUBE_API_KEY', 'snapshotted': 0}
    now = _now_utc()
    with _LOCK:
        stats = _load(_STATS_PATH, {})
    due = []
    for vid, rec in stats.items():
        fs = _parse_iso(rec.get('first_seen')) or now
        age_h = (now - fs).total_seconds() / 3600.0
        if age_h > 30 * 24:
            continue
        gap_h = 3 if age_h < 48 else (12 if age_h < 240 else 24)
        snaps = rec.get('snapshots') or []
        last = _parse_iso(snaps[-1][0]) if snaps else None
        if last is None or (now - last).total_seconds() / 3600.0 >= gap_h:
            due.append(vid)
        if len(due) >= max_videos:
            break
    done = 0
    for i in range(0, len(due), 50):
        batch = due[i : i + 50]
        try:
            qs = urllib.parse.urlencode(
                {
                    'part': 'statistics,contentDetails,liveStreamingDetails',
                    'id': ','.join(batch),
                    'key': key,
                    'fields': 'items(id,statistics(viewCount),contentDetails(duration),'
                    'liveStreamingDetails(actualEndTime,actualStartTime))',
                }
            )
            data = http_json.request_json(
                f'https://www.googleapis.com/youtube/v3/videos?{qs}', headers={'User-Agent': _UA}, timeout=20
            )
        except Exception:
            break  # bound the damage of an API outage — never spin
        with _LOCK:
            stats = _load(_STATS_PATH, {})
            for item in data.get('items') or []:
                rec = stats.get(item.get('id'))
                if rec is None:
                    continue
                views = int((item.get('statistics') or {}).get('viewCount') or 0)
                rec.setdefault('snapshots', []).append([_iso(now), views])
                rec['snapshots'] = rec['snapshots'][-40:]
                dur = _parse_iso_duration((item.get('contentDetails') or {}).get('duration') or '')
                if dur:
                    rec['duration'] = dur
                lsd = item.get('liveStreamingDetails')
                if lsd is not None:
                    # live-in-progress = started but not ended → counters not comparable
                    rec['live'] = bool(lsd.get('actualStartTime') and not lsd.get('actualEndTime'))
                done += 1
            # prune >30-day-old tracked videos to keep the file bounded
            cutoff = now - timedelta(days=30)
            for vid in [v for v, r in stats.items() if (_parse_iso(r.get('first_seen')) or now) < cutoff]:
                stats.pop(vid, None)
            _save(_STATS_PATH, stats)
    return {'snapshotted': done, 'due': len(due)}


def _views_10d(rec: dict, now: datetime):
    snaps = rec.get('snapshots') or []
    if not snaps:
        return None
    latest = int(snaps[-1][1])
    pub = _parse_iso(rec.get('published')) or _parse_iso(rec.get('first_seen'))
    if pub and (now - pub).days < 10:
        return latest  # lifetime == window for young videos (exact, zero history)
    target = now - timedelta(days=10)
    best = None
    for ts, views in snaps:
        t = _parse_iso(ts)
        if t and t <= target:
            best = int(views)
    if best is None:
        best = int(snaps[0][1])
    return max(0, latest - best)  # clamp: viewCount is NOT monotonic (spam purges)


def ranked_candidates(limit: int = 25) -> list:
    """Fresh uploads first (the 'freshly aired' path), then proven last-10-day
    videos ranked by channel-normalized velocity. Excludes already-remixed sources
    and channels without clipping_permission."""
    now = _now_utc()
    s = settings()
    with _LOCK:
        stats = _load(_STATS_PATH, {})
        lib = _load(_LIBRARY_PATH, {'clips': []})
    chan_ok = {c['channel_id']: c for c in channels() if c.get('enabled') and c.get('clipping_permission')}
    remixed = {c.get('source_video_id') for c in lib.get('clips') or []}

    # per-channel median vph for the outlier ratio
    chan_vph: dict = {}
    feats = {}
    for vid, rec in stats.items():
        if rec.get('channel_id') not in chan_ok or rec.get('live'):
            continue
        dur = rec.get('duration')
        if dur is not None and (dur < 120 or dur > 4 * 3600):
            continue
        fs = _parse_iso(rec.get('first_seen')) or now
        age_h = max((now - fs).total_seconds() / 3600.0, 0.5)
        v10 = _views_10d(rec, now)
        vph = (v10 / min(age_h, 240.0)) if v10 is not None else None
        feats[vid] = (rec, age_h, v10, vph)
        if vph is not None:
            chan_vph.setdefault(rec['channel_id'], []).append(vph)
    medians = {cid: sorted(v)[len(v) // 2] for cid, v in chan_vph.items() if v}

    fresh, proven = [], []
    for vid, (rec, age_h, v10, vph) in feats.items():
        if vid in remixed:
            continue
        base = {
            'video_id': vid,
            'title': rec.get('title') or vid,
            'channel_id': rec['channel_id'],
            'channel': chan_ok[rec['channel_id']].get('name') or rec['channel_id'],
            'url': f'https://www.youtube.com/watch?v={vid}',
            'age_hours': round(age_h, 1),
            'views_10d': v10,
            'duration': rec.get('duration'),
        }
        if age_h <= 24:
            base.update({'reason': 'fresh', 'score': None})
            fresh.append(base)
        elif v10 is not None and v10 >= 500 and vph is not None:
            med = medians.get(rec['channel_id']) or 1.0
            outlier = vph / max(med, 1.0)
            score = round(outlier * (1.0 + 0.3 * pow(2.718, -age_h / (7 * 24))), 2)
            if score >= float(s.get('min_score') or 0):
                base.update({'reason': 'proven', 'score': score, 'outlier': round(outlier, 2)})
                proven.append(base)
    fresh.sort(key=lambda c: c['age_hours'])
    proven.sort(key=lambda c: -(c['score'] or 0))
    return (fresh + proven)[:limit]


# ── per-video intelligence (heatmap / comments / chapters) via yt-dlp ────────


def fetch_video_intel(video_id: str, want_comments: bool = True, max_comments: int = 800) -> dict:
    """One yt-dlp metadata call: heatmap (100 buckets or None), chapters, comments,
    duration, title. Zero quota, anonymous. Never raises."""
    try:
        import yt_dlp

        opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'socket_timeout': 30,
            'getcomments': bool(want_comments),
            'extractor_args': {
                'youtube': {
                    'comment_sort': ['top'],
                    'max_comments': [str(max_comments), str(max_comments), '0', '0'],
                }
            },
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
        return {
            'title': info.get('title') or video_id,
            'channel': info.get('channel') or '',
            'channel_id': info.get('channel_id') or '',
            'duration': info.get('duration'),
            'heatmap': info.get('heatmap'),  # [{start_time,end_time,value}] × 100 or None
            'chapters': info.get('chapters'),
            'comments': [
                {'text': c.get('text') or '', 'likes': int(c.get('like_count') or 0)}
                for c in (info.get('comments') or [])
            ],
            'live_status': info.get('live_status'),
        }
    except Exception as e:
        return {'error': str(e)}


def detrend_heatmap(values: list, w: int = 12) -> list:
    """Divide by a wide moving median — raw heatmap Q1 reads ~2.9× Q4 purely from
    retention decay (audienceWatchRatio is segment-views/total-views). Measured
    2026-08-05 across 7 videos; naive argmax clips the intro every time."""
    import statistics

    n = len(values)
    base = [statistics.median(values[max(0, i - w) : min(n, i + w + 1)]) for i in range(n)]
    det = [values[i] / max(base[i], 1e-3) for i in range(n)]
    lo, hi = min(det), max(det)
    return [(d - lo) / max(hi - lo, 1e-9) for d in det]


def comment_timestamps(comments: list, duration: float) -> list:
    """Extract mm:ss / h:mm:ss mentions → [(seconds, like_count)] within bounds."""
    out = []
    for c in comments or []:
        for m in _TS_COMMENT_RE.finditer(c.get('text') or ''):
            h, mnt, sec = m.groups()
            t = (int(h or 0)) * 3600 + int(mnt) * 60 + int(sec)
            if 0 <= t <= (duration or 0):
                out.append((t, int(c.get('likes') or 0)))
    return out


# ── downloads (cookies + node ladder from stage_runner, plus the throttles it lacks) ──

_COOKIE_PATHS = [
    os.path.join(_RUNTIME, 'youtube_cookies.txt'),
    os.path.expanduser('~/youtube_cookies.txt'),
    os.path.expanduser('~/cookies/youtube_cookies.txt'),
    str(paths.ZYG_HOME / 'youtube_cookies.txt'),
    os.path.join(_CREWS, 'youtube_cookies.txt'),
]


def _cookie_file():
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


def download_video(video_id: str, out_dir: str, log=print) -> str:
    """Download the full episode at ≤1080p into out_dir. Returns the file path or ''."""
    os.makedirs(out_dir, exist_ok=True)
    out_tmpl = os.path.join(out_dir, f'{video_id}.%(ext)s')
    existing = _find_media(out_dir, video_id)
    if existing:
        return existing
    try:
        import shutil as _sh
        import yt_dlp

        has_ffmpeg = bool(_sh.which('ffmpeg'))
        opts = {
            'quiet': True,
            'no_warnings': True,
            'format': (
                'bestvideo[height<=1080]+bestaudio/bestvideo+bestaudio/best' if has_ffmpeg else 'best[ext=mp4]/best'
            ),
            'outtmpl': out_tmpl,
            'merge_output_format': 'mp4',
            'socket_timeout': 45,
            'retries': 3,
            'fragment_retries': 3,
            'max_filesize': 12 * 1024 * 1024 * 1024,  # one 4-h VOD ≈ 9 GB; hard stop above
            'sleep_interval_requests': 0.5,
        }
        ck = _cookie_file()
        if ck:
            opts['cookiefile'] = ck
        node = _node_bin()
        if node:
            # JS-challenge solving → full 1080p formats (stage_runner.py:705-720)
            opts['js_runtimes'] = {'node': {'path': node}}
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f'https://www.youtube.com/watch?v={video_id}'])
    except Exception as e:
        log(f'download failed for {video_id}: {e}')
        return ''
    return _find_media(out_dir, video_id) or ''


def _find_media(out_dir: str, stem: str):
    for ext in ('.mp4', '.mkv', '.webm', '.m4v'):
        p = os.path.join(out_dir, stem + ext)
        if os.path.isfile(p) and os.path.getsize(p) > 100 * 1024:
            return p
    return None


def download_section(video_id: str, start: float, end: float, out_dir: str, pad: float = 3.0, log=print) -> str:
    """Download only [start-pad, end+pad] of a video (compilation re-fetch path).
    Runs the venv's yt_dlp as a subprocess so --download-sections applies cleanly."""
    import subprocess
    import sys

    os.makedirs(out_dir, exist_ok=True)
    stem = f'{video_id}_{int(start)}_{int(end)}'
    existing = _find_media(out_dir, stem)
    if existing:
        return existing
    a, b = max(0.0, start - pad), end + pad
    cmd = [
        sys.executable,
        '-m',
        'yt_dlp',
        '--quiet',
        '--no-warnings',
        '-f',
        'bestvideo[height<=1080]+bestaudio/best',
        '--download-sections',
        f'*{a:.1f}-{b:.1f}',
        '--force-keyframes-at-cuts',
        '--merge-output-format',
        'mp4',
        '--socket-timeout',
        '45',
        '--retries',
        '2',
        '-o',
        os.path.join(out_dir, stem + '.%(ext)s'),
        f'https://www.youtube.com/watch?v={video_id}',
    ]
    ck = _cookie_file()
    if ck:
        cmd[2:2] = ['--cookies', ck]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
        if r.returncode != 0:
            log(f'section download failed: {(r.stderr or "")[-200:]}')
    except Exception as e:
        log(f'section download error: {e}')
    return _find_media(out_dir, stem) or ''


# ── b-roll library (self-recorded GameSim Minecraft; read-only, never mutated) ─


def broll_dir() -> str:
    return paths.ZYG_REMIX_BROLL_DIR


def broll_catalog(min_duration: float = 120.0) -> list:
    """[{path, duration}] for minecraft b-roll files, durations cached on disk."""
    import subprocess

    root = broll_dir()
    with _LOCK:
        cache = _load(_BROLL_CACHE_PATH, {})
    out, dirty = [], False
    try:
        names = sorted(os.listdir(root))
    except Exception:
        return []
    for fn in names:
        if not fn.lower().endswith('.mp4') or 'minecraft' not in fn.lower():
            continue
        p = os.path.join(root, fn)
        dur = cache.get(fn)
        if dur is None:
            try:
                r = subprocess.run(
                    [exe('ffprobe'), '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', p],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                dur = float((r.stdout or '0').strip() or 0)
            except Exception:
                dur = 0.0
            cache[fn] = dur
            dirty = True
        if dur and dur >= min_duration:
            out.append({'path': p, 'duration': dur})
    if dirty:
        with _LOCK:
            _save(_BROLL_CACHE_PATH, cache)
    return out


def pick_broll_window(need_seconds: float, avoid: list = None) -> dict:
    """A (file, offset) window of length need_seconds from the self-recorded library,
    never repeating a window already in `avoid` within the same job."""
    cands = [b for b in broll_catalog(min_duration=need_seconds + 16.0)]
    if not cands:
        return {}
    random.shuffle(cands)
    avoid = avoid or []
    for b in cands:
        for _ in range(6):
            off = random.uniform(4.0, b['duration'] - need_seconds - 4.0)
            clash = any(a.get('path') == b['path'] and abs(a.get('offset', -1e9) - off) < need_seconds for a in avoid)
            if not clash:
                return {'path': b['path'], 'offset': off}
    b = cands[0]
    return {'path': b['path'], 'offset': random.uniform(4.0, max(4.1, b['duration'] - need_seconds - 4.0))}


# ── clip library index (survives the 72 h media TTL; drives compilations) ─────


def library() -> dict:
    with _LOCK:
        return _load(_LIBRARY_PATH, {'clips': []})


def library_register(clip: dict) -> None:
    with _LOCK:
        lib = _load(_LIBRARY_PATH, {'clips': []})
        lib.setdefault('clips', []).append(clip)
        _save(_LIBRARY_PATH, lib)


def library_update(clip_ids: list, patch: dict) -> int:
    n = 0
    with _LOCK:
        lib = _load(_LIBRARY_PATH, {'clips': []})
        for c in lib.get('clips') or []:
            if c.get('clip_id') in clip_ids:
                c.update(patch)
                n += 1
        _save(_LIBRARY_PATH, lib)
    return n


def library_mark_deleted_for_job(pid: str) -> int:
    n = 0
    with _LOCK:
        lib = _load(_LIBRARY_PATH, {'clips': []})
        for c in lib.get('clips') or []:
            if c.get('job_id') == pid and not c.get('deleted'):
                c['deleted'] = True
                n += 1
        _save(_LIBRARY_PATH, lib)
    return n
