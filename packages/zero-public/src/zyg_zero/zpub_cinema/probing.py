# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""ffprobe wrapper and the direct-play / transcode decision."""

import json
import os
import subprocess

from .constants import FFPROBE
from .naming import _norm_lang

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_zero.zpub_cinema')


# ── ffprobe ───────────────────────────────────────────────────────────────────
def _run(cmd: list[str], timeout: int = 120) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout.decode('utf-8', 'replace'), p.stderr.decode('utf-8', 'replace')
    except subprocess.TimeoutExpired:
        return 124, '', 'timeout'
    except Exception as exc:
        return 1, '', str(exc)


def _parse_chapters(data: dict) -> list[dict]:
    """Named chapters out of an ffprobe payload — the only exact source there is
    for where an opening ends and an ending begins."""
    out = []
    for ch in data.get('chapters') or []:
        try:
            start = float(ch.get('start_time') or 0)
            end = float(ch.get('end_time') or 0)
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
        title = ((ch.get('tags') or {}).get('title') or '').strip()
        out.append({'start': round(start, 3), 'end': round(end, 3), 'title': title})
    out.sort(key=lambda c: c['start'])
    return out


def probe(path: str) -> dict:
    """ffprobe a media file into ``{duration, video, audio[], subs[], chapters[]}``.

    Never raises."""
    rc, out, _err = _run(
        [FFPROBE, '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', '-show_chapters', path],
        timeout=120,
    )
    if rc != 0 or not out.strip():
        return {}
    try:
        data = json.loads(out)
    except Exception:
        return {}
    fmt = data.get('format') or {}
    try:
        duration = float(fmt.get('duration') or 0)
    except (TypeError, ValueError):
        duration = 0.0

    video, audio, subs = None, [], []
    for st in data.get('streams') or []:
        ctype = st.get('codec_type')
        tags = st.get('tags') or {}
        lang = _norm_lang(tags.get('language'))
        title = (tags.get('title') or '').strip()
        if ctype == 'video' and video is None:
            if (st.get('disposition') or {}).get('attached_pic'):
                continue  # embedded cover art
            video = {
                'index': st.get('index'),
                'codec': st.get('codec_name') or '',
                'profile': st.get('profile') or '',
                'width': st.get('width') or 0,
                'height': st.get('height') or 0,
                'pix_fmt': st.get('pix_fmt') or '',
            }
            if not duration:
                try:
                    duration = float(st.get('duration') or 0)
                except (TypeError, ValueError) as _exc:
                    _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
        elif ctype == 'audio':
            audio.append(
                {
                    'index': st.get('index'),
                    'order': len(audio),
                    'codec': st.get('codec_name') or '',
                    'channels': st.get('channels') or 0,
                    'lang': lang,
                    'title': title,
                    'default': bool((st.get('disposition') or {}).get('default')),
                }
            )
        elif ctype == 'subtitle':
            disp = st.get('disposition') or {}
            subs.append(
                {
                    'index': st.get('index'),
                    'order': len(subs),
                    'codec': st.get('codec_name') or '',
                    'lang': lang,
                    'title': title,
                    'forced': bool(disp.get('forced')),
                    'hearing_impaired': bool(disp.get('hearing_impaired')),
                    'default': bool(disp.get('default')),
                }
            )
    return {
        'duration': round(duration, 3),
        'video': video,
        'audio': audio,
        'subs': subs,
        'chapters': _parse_chapters(data),
        'bitrate': int(float(fmt.get('bit_rate') or 0) or 0),
    }


# ── Playability ───────────────────────────────────────────────────────────────
BROWSER_VCODECS = {'h264', 'vp8', 'vp9', 'av1'}
BROWSER_ACODECS = {'aac', 'mp3', 'opus', 'vorbis', 'flac'}
DIRECT_CONTAINERS = {'.mp4', '.m4v', '.webm', '.mov'}


def _playback_plan(path: str, info: dict) -> dict:
    """Decide direct-play vs transcode, and how cheap the transcode can be."""
    ext = os.path.splitext(path)[1].lower()
    v = (info.get('video') or {}).get('codec', '')
    a = (info.get('audio') or [{}])[0].get('codec', '') if info.get('audio') else ''
    v_ok = v in BROWSER_VCODECS
    a_ok = (a in BROWSER_ACODECS) or not a
    # 10-bit H.264 is decodable by essentially no browser; treat it as not OK.
    if v == 'h264' and '10' in ((info.get('video') or {}).get('pix_fmt', '')):
        v_ok = False
    direct = ext in DIRECT_CONTAINERS and v_ok and a_ok
    return {
        'direct': direct,
        'video_copy': v_ok,  # transcode can -c:v copy (remux only)
        'audio_copy': a_ok,
        'reason': ''
        if direct
        else (
            'container'
            if (v_ok and a_ok)
            else ('video+audio' if (not v_ok and not a_ok) else ('video' if not v_ok else 'audio'))
        ),
    }
