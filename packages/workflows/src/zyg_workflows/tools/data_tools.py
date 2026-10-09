# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Data tools: PRAW (Reddit), pytrends (Google Trends), yt-dlp, RSS feeds,
YouTube Transcript API, MediaInfo, and hardware monitoring.
"""

import json
import os
from datetime import datetime, timezone

from zyg_workflows import paths

try:
    from zoneinfo import ZoneInfo

    _AMS_TZ = ZoneInfo('Europe/Amsterdam')
except Exception:
    _AMS_TZ = None
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def _ams_iso(timespec: str = 'milliseconds') -> str:
    """Tz-aware ISO timestamp in Europe/Amsterdam, including ``+HH:MM`` offset."""
    if _AMS_TZ is not None:
        try:
            return datetime.now(_AMS_TZ).isoformat(timespec=timespec)
        except Exception as _exc:
            _zyg_log.debug('Amsterdam timezone unavailable, falling back to UTC: %s', _exc)
    return datetime.now(timezone.utc).isoformat(timespec=timespec)


try:
    from langchain.tools import BaseTool
except ImportError:
    try:
        from langchain_core.tools import BaseTool
    except ImportError:

        class BaseTool:
            name: str = ''
            description: str = ''

            def _run(self, *args, **kwargs):
                raise NotImplementedError


class RedditAPITool(BaseTool):
    name: str = 'Reddit API (PRAW)'
    description: str = (
        'Search Reddit for posts matching a query using PRAW. '
        'Requires REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT env vars.'
    )

    def _run(self, query: str, subreddit: str = 'all', limit: int = 25, sort: str = 'hot') -> str:
        import praw

        client_id = os.getenv('REDDIT_CLIENT_ID', '')
        client_secret = os.getenv('REDDIT_CLIENT_SECRET', '')
        user_agent = os.getenv('REDDIT_USER_AGENT', 'clipfarm/1.0')
        if not client_id or not client_secret:
            return json.dumps({'error': 'Missing REDDIT_CLIENT_ID or REDDIT_CLIENT_SECRET env vars'})
        reddit = praw.Reddit(client_id=client_id, client_secret=client_secret, user_agent=user_agent, read_only=True)
        sub = reddit.subreddit(subreddit)
        posts = []
        method = getattr(sub, sort, sub.hot)
        for post in method(limit=limit):
            posts.append(
                {
                    'id': post.id,
                    'title': post.title,
                    'score': post.score,
                    'url': post.url,
                    'upvote_ratio': post.upvote_ratio,
                    'num_comments': post.num_comments,
                    'created_utc': post.created_utc,
                    'subreddit': str(post.subreddit),
                }
            )
        return json.dumps({'query': query, 'subreddit': subreddit, 'sort': sort, 'count': len(posts), 'posts': posts})


class RedditHotPostsTool(BaseTool):
    name: str = 'Reddit Hot Posts (PRAW)'
    description: str = (
        'Fetch the current hot posts from a specific subreddit using PRAW. '
        'Requires REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET env vars.'
    )

    def _run(self, subreddit: str = 'videos', limit: int = 25) -> str:
        import praw

        client_id = os.getenv('REDDIT_CLIENT_ID', '')
        client_secret = os.getenv('REDDIT_CLIENT_SECRET', '')
        user_agent = os.getenv('REDDIT_USER_AGENT', 'clipfarm/1.0')
        if not client_id or not client_secret:
            return json.dumps({'error': 'Missing REDDIT_CLIENT_ID or REDDIT_CLIENT_SECRET env vars'})
        reddit = praw.Reddit(client_id=client_id, client_secret=client_secret, user_agent=user_agent, read_only=True)
        posts = []
        for post in reddit.subreddit(subreddit).hot(limit=limit):
            posts.append(
                {
                    'id': post.id,
                    'title': post.title,
                    'score': post.score,
                    'url': post.url,
                    'upvote_ratio': post.upvote_ratio,
                    'num_comments': post.num_comments,
                    'created_utc': post.created_utc,
                }
            )
        return json.dumps({'subreddit': subreddit, 'count': len(posts), 'posts': posts})


class PytrendsTool(BaseTool):
    name: str = 'pytrends (Google Trends)'
    description: str = (
        'Fetch Google Trends data for keywords using pytrends. Returns interest over time and related queries.'
    )

    def _run(self, keywords_json: str, timeframe: str = 'today 3-m', geo: str = '') -> str:
        from pytrends.request import TrendReq

        keywords = json.loads(keywords_json) if isinstance(keywords_json, str) else keywords_json
        if isinstance(keywords, str):
            keywords = [keywords]
        keywords = keywords[:5]  # pytrends limit
        pt = TrendReq(hl='en-US', tz=360)
        pt.build_payload(keywords, cat=0, timeframe=timeframe, geo=geo)
        interest_df = pt.interest_over_time()
        related = {}
        for kw in keywords:
            try:
                rq = pt.related_queries()
                if kw in rq and rq[kw]['top'] is not None:
                    related[kw] = rq[kw]['top'].head(10).to_dict('records')
            except Exception as _exc:
                _zyg_log.debug('related queries unavailable for %s: %s', kw, _exc)
        return json.dumps(
            {
                'keywords': keywords,
                'timeframe': timeframe,
                'geo': geo or 'worldwide',
                'interest_over_time': interest_df.reset_index().to_dict('records') if not interest_df.empty else [],
                'related_queries': related,
            }
        )


class YtDlpAudioDownloadTool(BaseTool):
    name: str = 'yt-dlp (audio download)'
    description: str = (
        'Download audio from a video URL using yt-dlp and extract to MP3/WAV. Returns path to downloaded audio file.'
    )

    def _run(self, url: str, output_dir: str = '', audio_format: str = 'mp3', audio_quality: str = '192') -> str:
        import yt_dlp

        output_dir = output_dir or str(paths.tmp_dir('downloads'))
        output_template = os.path.join(output_dir, '%(title)s.%(ext)s')
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_template,
            'postprocessors': [
                {
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': audio_format,
                    'preferredquality': audio_quality,
                }
            ],
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
        return json.dumps(
            {
                'status': 'ok',
                'title': info.get('title', ''),
                'duration': info.get('duration', 0),
                'output_dir': output_dir,
                'format': audio_format,
            }
        )


class YtDlpVideoDownloadTool(BaseTool):
    name: str = 'yt-dlp (video download)'
    description: str = 'Download video from a URL using yt-dlp. Returns path to downloaded video file.'

    def _run(self, url: str, output_dir: str = '', quality: str = 'bestvideo[height<=1080]+bestaudio/best') -> str:
        import yt_dlp

        output_dir = output_dir or str(paths.tmp_dir('downloads'))
        output_template = os.path.join(output_dir, '%(title)s.%(ext)s')
        ydl_opts = {
            'format': quality,
            'outtmpl': output_template,
            'merge_output_format': 'mp4',
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
        return json.dumps(
            {
                'status': 'ok',
                'title': info.get('title', ''),
                'duration': info.get('duration', 0),
                'width': info.get('width'),
                'height': info.get('height'),
                'output_dir': output_dir,
            }
        )


class YouTubeTranscriptAPITool(BaseTool):
    name: str = 'YouTube Transcript API'
    description: str = (
        'Fetch auto-generated or manual subtitles for a YouTube video using YouTube Transcript API. '
        'Returns full transcript as text and timed segments.'
    )

    def _run(self, video_id: str, language: str = 'en') -> str:
        from youtube_transcript_api import YouTubeTranscriptApi

        try:
            api = YouTubeTranscriptApi()
            transcript = api.fetch(video_id, languages=[language, 'en'])
            snippets = transcript.snippets
            full_text = ' '.join(s.text for s in snippets)
            segments = [{'start': s.start, 'duration': s.duration, 'text': s.text} for s in snippets]
            return json.dumps(
                {
                    'video_id': video_id,
                    'language': language,
                    'full_text': full_text,
                    'segment_count': len(segments),
                    'segments': segments,
                }
            )
        except Exception as e:
            return json.dumps({'error': str(e), 'video_id': video_id})


class YouTubeTrendingRSSTool(BaseTool):
    name: str = 'YouTube Trending RSS'
    description: str = (
        'Fetch the YouTube trending videos RSS feed for a given country code. '
        'No API key required. Returns list of trending video titles and links.'
    )

    def _run(self, country_code: str = 'US', max_results: int = 20) -> str:
        import defusedxml.ElementTree as ET  # remote RSS/Atom; the stdlib parser is entity-bomb prone
        import requests

        # YouTube trending RSS (regional)
        url = f'https://www.youtube.com/feeds/videos.xml?chart=mostpopular&regionCode={country_code}'
        try:
            resp = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            ns = {
                'atom': 'http://www.w3.org/2005/Atom',
                'yt': 'http://www.youtube.com/xml/schemas/2015',
                'media': 'http://search.yahoo.com/mrss/',
            }
            entries = root.findall('atom:entry', ns)[:max_results]
            videos = []
            for entry in entries:
                title_el = entry.find('atom:title', ns)
                link_el = entry.find('atom:link', ns)
                views_el = entry.find('.//yt:statistics', ns)
                videos.append(
                    {
                        'title': title_el.text if title_el is not None else '',
                        'url': link_el.get('href', '') if link_el is not None else '',
                        'views': views_el.get('viewCount', '0') if views_el is not None else '0',
                    }
                )
            return json.dumps({'country': country_code, 'count': len(videos), 'videos': videos})
        except Exception as e:
            return json.dumps({'error': str(e), 'country': country_code})


class RSSFeedReaderTool(BaseTool):
    name: str = 'RSS Feed Reader'
    description: str = (
        'Fetch and parse an RSS or Atom feed URL. '
        'Returns list of feed entries with title, link, published date, and summary.'
    )

    def _run(self, feed_url: str, max_items: int = 20) -> str:
        import requests
        import defusedxml.ElementTree as ET  # remote RSS/Atom; the stdlib parser is entity-bomb prone

        try:
            resp = requests.get(feed_url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            items = []
            # RSS 2.0
            for item in root.findall('.//item')[:max_items]:
                items.append(
                    {
                        'title': (item.findtext('title') or '').strip(),
                        'link': (item.findtext('link') or '').strip(),
                        'pubDate': (item.findtext('pubDate') or '').strip(),
                        'description': (item.findtext('description') or '')[:200].strip(),
                    }
                )
            # Atom fallback
            if not items:
                ns = {'atom': 'http://www.w3.org/2005/Atom'}
                for entry in root.findall('atom:entry', ns)[:max_items]:
                    title_el = entry.find('atom:title', ns)
                    link_el = entry.find('atom:link', ns)
                    updated_el = entry.find('atom:updated', ns)
                    summary_el = entry.find('atom:summary', ns)
                    items.append(
                        {
                            'title': title_el.text if title_el is not None else '',
                            'link': link_el.get('href', '') if link_el is not None else '',
                            'pubDate': updated_el.text if updated_el is not None else '',
                            'description': (summary_el.text or '')[:200] if summary_el is not None else '',
                        }
                    )
            return json.dumps({'feed_url': feed_url, 'count': len(items), 'items': items})
        except Exception as e:
            return json.dumps({'error': str(e), 'feed_url': feed_url})


class MediaInfoTool(BaseTool):
    name: str = 'MediaInfo (metadata)'
    description: str = (
        'Extract detailed media metadata (codec, bitrate, resolution, duration, '
        'audio channels, etc.) from a file using pymediainfo.'
    )

    def _run(self, file_path: str) -> str:
        from pymediainfo import MediaInfo

        mi = MediaInfo.parse(file_path)
        result = {'file': file_path, 'tracks': []}
        for track in mi.tracks:
            t = {'type': track.track_type}
            if track.track_type == 'General':
                t.update(
                    {
                        'format': track.format,
                        'duration_ms': track.duration,
                        'file_size': track.file_size,
                        'overall_bitrate': track.overall_bit_rate,
                    }
                )
            elif track.track_type == 'Video':
                t.update(
                    {
                        'codec': track.codec_id or track.format,
                        'width': track.width,
                        'height': track.height,
                        'frame_rate': track.frame_rate,
                        'bitrate': track.bit_rate,
                        'scan_type': track.scan_type,
                    }
                )
            elif track.track_type == 'Audio':
                t.update(
                    {
                        'codec': track.codec_id or track.format,
                        'channels': track.channel_s,
                        'sample_rate': track.sampling_rate,
                        'bitrate': track.bit_rate,
                        'language': track.language,
                    }
                )
            result['tracks'].append(t)
        return json.dumps(result)


class DiskUsageMonitorTool(BaseTool):
    name: str = 'Disk Usage Monitor (df / psutil)'
    description: str = (
        'Monitor disk usage for a given path using psutil. Returns total, used, free space and usage percentage.'
    )

    def _run(self, path: str = '/') -> str:
        import psutil

        usage = psutil.disk_usage(path)
        partitions = []
        for p in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(p.mountpoint)
                partitions.append(
                    {
                        'mountpoint': p.mountpoint,
                        'device': p.device,
                        'fstype': p.fstype,
                        'total_gb': round(u.total / 1e9, 2),
                        'used_gb': round(u.used / 1e9, 2),
                        'free_gb': round(u.free / 1e9, 2),
                        'percent': u.percent,
                    }
                )
            except PermissionError as _exc:
                _zyg_log.debug('disk usage not readable for %s: %s', p.mountpoint, _exc)
        return json.dumps(
            {
                'path': path,
                'total_gb': round(usage.total / 1e9, 2),
                'used_gb': round(usage.used / 1e9, 2),
                'free_gb': round(usage.free / 1e9, 2),
                'percent_used': usage.percent,
                'all_partitions': partitions,
            }
        )


class HardwareTelemetryReaderTool(BaseTool):
    name: str = 'Hardware Telemetry Reader (GPU temp, VRAM, GPU util, CPU temp, CPU util, RAM free)'
    description: str = (
        'Read real-time hardware telemetry: CPU usage/temp, RAM, GPU usage/VRAM/temp using psutil and pynvml.'
    )

    def _run(self) -> str:
        import psutil

        result = {}
        # CPU
        result['cpu_percent'] = psutil.cpu_percent(interval=0.5)
        result['cpu_count'] = psutil.cpu_count()
        result['cpu_freq_mhz'] = psutil.cpu_freq().current if psutil.cpu_freq() else None
        try:
            temps = psutil.sensors_temperatures()
            cpu_temps = temps.get('coretemp') or temps.get('cpu_thermal') or []
            if cpu_temps:
                result['cpu_temp_c'] = cpu_temps[0].current
        except Exception:
            result['cpu_temp_c'] = None
        # RAM
        mem = psutil.virtual_memory()
        result['ram_total_gb'] = round(mem.total / 1e9, 2)
        result['ram_used_gb'] = round(mem.used / 1e9, 2)
        result['ram_free_gb'] = round(mem.available / 1e9, 2)
        result['ram_percent'] = mem.percent
        # GPU via pynvml
        gpu_info = []
        try:
            import pynvml

            pynvml.nvmlInit()
            device_count = pynvml.nvmlDeviceGetCount()
            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                name = pynvml.nvmlDeviceGetName(handle)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                try:
                    temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                except Exception:
                    temp = None
                gpu_info.append(
                    {
                        'index': i,
                        'name': name if isinstance(name, str) else name.decode(),
                        'gpu_util_percent': util.gpu,
                        'mem_util_percent': util.memory,
                        'vram_total_gb': round(mem_info.total / 1e9, 2),
                        'vram_used_gb': round(mem_info.used / 1e9, 2),
                        'vram_free_gb': round(mem_info.free / 1e9, 2),
                        'temp_c': temp,
                    }
                )
            pynvml.nvmlShutdown()
        except Exception as e:
            gpu_info = [{'error': str(e)}]
        result['gpus'] = gpu_info
        return json.dumps(result)


_RUNTIME_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'runtime')


def _get_youtube_api_key() -> str:
    """Return YouTube API key: env var first, then credentials file."""
    key = os.getenv('YOUTUBE_API_KEY', '')
    if key:
        return key
    creds_file = os.path.join(_RUNTIME_DIR, 'clipfarm_credentials.json')
    if os.path.exists(creds_file):
        try:
            with open(creds_file) as f:
                return json.load(f).get('YOUTUBE_API_KEY', '')
        except Exception as _exc:
            _zyg_log.warning('credentials file unreadable, continuing without a YouTube API key: %s', _exc)
    return ''


class YouTubeChannelRSSScannerTool(BaseTool):
    name: str = 'YouTube Channel RSS Scanner'
    description: str = (
        'Scan known YouTube channels via RSS feed — no API quota consumed. '
        'Reads channel IDs from the channel registry and fetches latest videos. '
        'Use this for channels already discovered. Falls back gracefully on errors.'
    )

    def _run(self, max_videos_per_channel: int = 5, channel_ids_json: str = '') -> str:
        import requests
        import defusedxml.ElementTree as ET  # remote RSS/Atom; the stdlib parser is entity-bomb prone

        channel_registry = os.path.join(_RUNTIME_DIR, 'clipfarm_channels.json')
        channels = []
        if channel_ids_json:
            try:
                channels = json.loads(channel_ids_json)
            except ValueError as _exc:
                _zyg_log.warning('channel_ids_json did not parse, falling back to the channel registry: %s', _exc)
        elif os.path.exists(channel_registry):
            with open(channel_registry) as f:
                raw = json.load(f)
                channels = [c for c in raw if c.get('channel_id') or c.get('id')]

        if not channels:
            return json.dumps(
                {
                    'warning': 'No channels in registry yet. Add channels via YouTube Data API first.',
                    'channels_scanned': 0,
                    'videos_found': 0,
                    'videos': [],
                }
            )

        ns = {
            'atom': 'http://www.w3.org/2005/Atom',
            'yt': 'http://www.youtube.com/xml/schemas/2015',
            'media': 'http://search.yahoo.com/mrss/',
        }
        all_videos = []
        errors = []
        for ch in channels:
            channel_id = ch.get('channel_id') or ch.get('id', '')
            if not channel_id:
                continue

            # PRIMARY: yt-dlp scrapes /videos tab — long-form only, no Shorts, no livestreams.
            # RSS is only a fallback because it returns the last 15 uploads regardless of type,
            # so channels that post Shorts frequently will have their RSS dominated by Shorts.
            ytdlp_ok = False
            try:
                import yt_dlp as _ytdlp

                channel_url = f'https://www.youtube.com/channel/{channel_id}/videos'
                # Fetch more than needed so we still have enough after duration filtering
                ydl_opts = {
                    'quiet': True,
                    'extract_flat': True,
                    'playlistend': max_videos_per_channel * 4,
                    'ignoreerrors': True,
                }
                with _ytdlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(channel_url, download=False)
                ytdlp_entries = (info or {}).get('entries', []) or []
                ch_videos = []
                for entry in ytdlp_entries:
                    if not entry:
                        continue
                    vid_id = entry.get('id', '')
                    if not vid_id:
                        continue
                    # Skip Shorts — duration < 90s or /shorts/ in url
                    duration = entry.get('duration') or 0
                    if duration and duration < 90:
                        continue
                    url_entry = entry.get('url') or entry.get('webpage_url') or ''
                    if '/shorts/' in url_entry:
                        continue
                    # Skip live/upcoming streams
                    _live_status = entry.get('live_status', '') or ''
                    if _live_status in ('is_live', 'is_upcoming', 'post_live'):
                        continue
                    ch_videos.append(
                        {
                            'channel_id': channel_id,
                            'channel_name': ch.get('name', ''),
                            'video_id': vid_id,
                            'title': entry.get('title', ''),
                            'url': f'https://www.youtube.com/watch?v={vid_id}',
                            'published': entry.get('upload_date', ''),
                            'views': str(entry.get('view_count') or 0),
                            'duration': duration,
                            'source': 'ytdlp',
                        }
                    )
                    if len(ch_videos) >= max_videos_per_channel:
                        break
                if ch_videos:
                    all_videos.extend(ch_videos)
                    ytdlp_ok = True
            except Exception as _ye:
                errors.append({'channel_id': channel_id, 'error': f'yt-dlp: {_ye}'})

            # FALLBACK: RSS — used only when yt-dlp fails entirely
            if not ytdlp_ok:
                try:
                    rss_url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'
                    resp = requests.get(rss_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
                    resp.raise_for_status()
                    root = ET.fromstring(resp.content)
                    entries = root.findall('atom:entry', ns)
                    for entry in entries:
                        vid_el = entry.find('yt:videoId', ns)
                        title_el = entry.find('atom:title', ns)
                        link_el = entry.find('atom:link', ns)
                        pub_el = entry.find('atom:published', ns)
                        stats_el = entry.find('.//yt:statistics', ns)
                        href = link_el.get('href', '') if link_el is not None else ''
                        # Skip Shorts even in RSS fallback
                        if '/shorts/' in href:
                            continue
                        all_videos.append(
                            {
                                'channel_id': channel_id,
                                'channel_name': ch.get('name', ''),
                                'video_id': vid_el.text if vid_el is not None else '',
                                'title': title_el.text if title_el is not None else '',
                                'url': href,
                                'published': pub_el.text if pub_el is not None else '',
                                'views': stats_el.get('viewCount', '0') if stats_el is not None else '0',
                                'source': 'rss_fallback',
                            }
                        )
                        if len([v for v in all_videos if v['channel_id'] == channel_id]) >= max_videos_per_channel:
                            break
                except Exception as e:
                    errors.append({'channel_id': channel_id, 'error': f'rss fallback: {e}'})

        return json.dumps(
            {
                'channels_scanned': len(channels),
                'videos_found': len(all_videos),
                'videos': all_videos,
                'errors': errors,
            }
        )


class YouTubeDataAPITool(BaseTool):
    name: str = 'YouTube Data API'
    description: str = (
        'Discover channels, fetch video stats, and query channel stats via YouTube Data API v3. '
        'Uses YOUTUBE_API_KEY. Call sparingly — quota: 10,000 units/day. '
        "Actions: 'search_channels', 'video_stats', 'channel_stats'."
    )

    def _run(
        self, action: str, query: str = '', channel_id: str = '', video_ids_csv: str = '', max_results: int = 10
    ) -> str:
        import requests

        api_key = _get_youtube_api_key()
        if not api_key:
            return json.dumps({'error': 'YOUTUBE_API_KEY not configured'})
        base = 'https://www.googleapis.com/youtube/v3'

        try:
            if action == 'search_channels':
                resp = requests.get(
                    f'{base}/search',
                    timeout=10,
                    params={
                        'part': 'snippet',
                        'type': 'channel',
                        'q': query,
                        'maxResults': min(max_results, 50),
                        'key': api_key,
                    },
                )
                resp.raise_for_status()
                items = resp.json().get('items', [])
                channels = [
                    {
                        'channel_id': i['snippet']['channelId'],
                        'name': i['snippet']['channelTitle'],
                        'description': i['snippet'].get('description', '')[:200],
                    }
                    for i in items
                ]
                # Auto-register discovered channels into registry
                registry_path = os.path.join(_RUNTIME_DIR, 'clipfarm_channels.json')
                existing = []
                if os.path.exists(registry_path):
                    with open(registry_path) as f:
                        existing = json.load(f)
                existing_ids = {c.get('channel_id') or c.get('id') for c in existing}
                for ch in channels:
                    if ch['channel_id'] not in existing_ids:
                        existing.append(
                            {
                                'channel_id': ch['channel_id'],
                                'name': ch['name'],
                                'platform': 'youtube',
                                'added_at': _ams_iso(),
                            }
                        )
                with open(registry_path, 'w') as f:
                    json.dump(existing, f, indent=2)
                return json.dumps(
                    {'query': query, 'channels': channels, 'count': len(channels), 'registered': len(channels)}
                )

            elif action == 'video_stats':
                ids = video_ids_csv or channel_id
                resp = requests.get(
                    f'{base}/videos',
                    timeout=10,
                    params={
                        'part': 'statistics,snippet',
                        'id': ids,
                        'key': api_key,
                    },
                )
                resp.raise_for_status()
                videos = [
                    {
                        'video_id': i['id'],
                        'title': i['snippet']['title'],
                        'views': i['statistics'].get('viewCount', 0),
                        'likes': i['statistics'].get('likeCount', 0),
                        'comments': i['statistics'].get('commentCount', 0),
                    }
                    for i in resp.json().get('items', [])
                ]
                return json.dumps({'videos': videos, 'count': len(videos)})

            elif action == 'channel_stats':
                resp = requests.get(
                    f'{base}/channels',
                    timeout=10,
                    params={
                        'part': 'statistics,snippet',
                        'id': channel_id,
                        'key': api_key,
                    },
                )
                resp.raise_for_status()
                items = resp.json().get('items', [])
                if not items:
                    return json.dumps({'error': 'Channel not found'})
                i = items[0]
                return json.dumps(
                    {
                        'channel_id': channel_id,
                        'name': i['snippet']['title'],
                        'subscribers': i['statistics'].get('subscriberCount', 0),
                        'total_views': i['statistics'].get('viewCount', 0),
                        'video_count': i['statistics'].get('videoCount', 0),
                    }
                )

            return json.dumps({'error': f'Unknown action: {action}'})
        except Exception as e:
            return json.dumps({'error': str(e), 'action': action})


DATA_TOOLS = [
    RedditAPITool(),
    RedditHotPostsTool(),
    PytrendsTool(),
    YtDlpAudioDownloadTool(),
    YtDlpVideoDownloadTool(),
    YouTubeTranscriptAPITool(),
    YouTubeTrendingRSSTool(),
    RSSFeedReaderTool(),
    YouTubeChannelRSSScannerTool(),
    YouTubeDataAPITool(),
    MediaInfoTool(),
    DiskUsageMonitorTool(),
    HardwareTelemetryReaderTool(),
]

__all__ = [
    'RedditAPITool',
    'RedditHotPostsTool',
    'PytrendsTool',
    'YtDlpAudioDownloadTool',
    'YtDlpVideoDownloadTool',
    'YouTubeTranscriptAPITool',
    'YouTubeTrendingRSSTool',
    'RSSFeedReaderTool',
    'YouTubeChannelRSSScannerTool',
    'YouTubeDataAPITool',
    'MediaInfoTool',
    'DiskUsageMonitorTool',
    'HardwareTelemetryReaderTool',
    'DATA_TOOLS',
]
