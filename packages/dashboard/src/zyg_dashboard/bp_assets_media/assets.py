# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Output-SCP config, the SFX/reaction catalogues and the asset downloader.

Moved verbatim out of bp_assets_media.py (original lines 56-346).
"""

import json
import os
import threading

from flask import jsonify, request

from zyg_dashboard import paths
from zyg_dashboard.gui.runtime_state import _runtime_path

from zyg_dashboard.bp_assets_media.base import (
    _ASSETS_REACTION_DIR,
    _ASSETS_SFX_DIR,
    _agent_log,
    _zyg_log,
    bp,
    limiter,
)


@bp.route('/api/output-scp/config', methods=['GET'])
def get_scp_config():
    cfg_path = _runtime_path('output_scp_config.json')
    try:
        with open(cfg_path) as _f:
            return jsonify(json.load(_f))
    except FileNotFoundError:
        return jsonify({})  # not configured yet — the same empty config PATCH starts from
    except Exception as _e:
        return jsonify({'error': str(_e)}), 500


@bp.route('/api/output-scp/config', methods=['PATCH'])
def patch_scp_config():
    cfg_path = _runtime_path('output_scp_config.json')
    try:
        with open(cfg_path) as _f:
            cfg = json.load(_f)
    except Exception:
        cfg = {}
    updates = request.get_json(silent=True) or {}
    cfg.update(updates)
    try:
        with open(cfg_path, 'w') as _f:
            json.dump(cfg, _f, indent=2)
        return jsonify(cfg)
    except Exception as _e:
        return jsonify({'error': str(_e)}), 500


def _parse_sfx_catalogue() -> list:
    """Parse sound_effects.txt → list of {file, url, name, desc, use_when} dicts."""
    txt = os.path.join(_ASSETS_SFX_DIR, 'sound_effects.txt')
    items, cur = [], {}
    try:
        with open(txt) as f:
            for line in f:
                raw = line.rstrip()
                stripped = raw.strip()
                if stripped.startswith('FILE:'):
                    if cur.get('file') and cur.get('url'):
                        items.append(cur)
                    cur = {'file': stripped.split(':', 1)[1].strip()}
                elif stripped.startswith('URL:'):
                    cur['url'] = stripped.split(':', 1)[1].strip()
                elif stripped.startswith('NAME:'):
                    cur['name'] = stripped.split(':', 1)[1].strip()
                elif stripped.startswith('DESC:'):
                    cur['desc'] = stripped.split(':', 1)[1].strip()
                elif stripped.startswith('USE WHEN:'):
                    cur['use_when'] = stripped.split(':', 1)[1].strip()
                elif (
                    cur.get('use_when') is not None
                    and stripped
                    and not stripped.startswith('---')
                    and not stripped.startswith('FILE:')
                    and not stripped.startswith('TRIGGER')
                ):
                    # continuation line for USE WHEN
                    cur['use_when'] = cur['use_when'] + ' ' + stripped
        if cur.get('file') and cur.get('url'):
            items.append(cur)
    except Exception as _exc:
        _zyg_log.warning('sfx catalogue parse failed, returning %d item(s): %s', len(items), _exc)
    return items


def _parse_reaction_catalogue() -> list:
    """Parse reaction_clips.txt → list of {file, source, desc, use_when} dicts."""
    txt = os.path.join(_ASSETS_REACTION_DIR, 'reaction_clips.txt')
    items, cur = [], {}
    try:
        with open(txt) as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith('FILE:'):
                    if cur.get('file'):
                        items.append(cur)
                    cur = {'file': stripped.split(':', 1)[1].strip(), 'source': '', 'desc': '', 'use_when': ''}
                elif stripped.startswith('SOURCE:'):
                    cur['source'] = stripped.split(':', 1)[1].strip()
                elif stripped.startswith('DESC:'):
                    cur['desc'] = stripped.split(':', 1)[1].strip()
                elif stripped.startswith('USE WHEN:'):
                    cur['use_when'] = stripped.split(':', 1)[1].strip()
                elif (
                    cur.get('use_when') is not None
                    and cur.get('use_when') != ''
                    and stripped
                    and not stripped.startswith('HOW TO GET')
                    and not stripped.startswith('FILE:')
                    and not stripped.startswith('---')
                ):
                    cur['use_when'] = cur['use_when'] + ' ' + stripped
                elif stripped.startswith('HOW TO GET:'):
                    rest = stripped.split(':', 1)[1].strip()
                    if 'search' in rest.lower() and '"' in rest:
                        import re as _re2

                        m = _re2.search(r'"([^"]+)"', rest)
                        if m and not cur.get('desc'):
                            cur['desc'] = m.group(1)
        if cur.get('file'):
            items.append(cur)
    except Exception as _exc:
        _zyg_log.warning('reaction catalogue parse failed, returning %d item(s): %s', len(items), _exc)
    # back-compat: add 'search' key for callers that expect it
    for item in items:
        item.setdefault('search', item.get('desc') or item['file'].replace('_', ' ').replace('.mp4', ''))
    return items


def _download_assets_background():
    """Download missing SFX mp3s and reaction clip mp4s. Runs in a daemon thread."""
    import urllib.request as _ur
    import subprocess as _dl_sp
    from urllib.parse import urlsplit as _urlsplit

    def _log_info(msg):
        _zyg_log.info(f'[ASSET-DL] {msg}')
        _agent_log('INFO', 'ASSET-DOWNLOADER', 'asset_download', 'Asset Download', msg)

    def _log_err(stage, err):
        msg = f'{stage}: {err}'
        _zyg_log.info(f'[ASSET-DL ERROR] {msg}')
        _agent_log('ERROR', 'ASSET-DOWNLOADER', 'asset_download', 'Asset Download', msg)

    _log_info('Asset downloader: starting download of missing SFX and reaction clips')

    # ── SFX mp3s ──────────────────────────────────────────────────────────────
    os.makedirs(_ASSETS_SFX_DIR, exist_ok=True)
    for item in _parse_sfx_catalogue():
        dest = os.path.join(_ASSETS_SFX_DIR, item['file'])
        if os.path.exists(dest) and os.path.getsize(dest) > 1000:
            _log_info(f'Asset downloader: SFX {item["file"]} already present — skip')
            continue
        try:
            _log_info(f'Asset downloader: downloading SFX {item["file"]} from {item["url"]}')
            # The catalogue is editable, so the scheme is checked before urlopen sees it;
            # the UA header is why this cannot go through net.safe_urlopen().
            if _urlsplit(item['url']).scheme not in ('http', 'https'):
                raise ValueError(f'refusing non-http(s) SFX URL {item["url"]!r}')
            req = _ur.Request(item['url'], headers={'User-Agent': 'Mozilla/5.0'})  # noqa: S310  scheme checked above
            with _ur.urlopen(req, timeout=30) as resp, open(dest, 'wb') as f:  # nosec B310  # noqa: S310  scheme checked above
                f.write(resp.read())
            size_kb = os.path.getsize(dest) // 1024
            _log_info(f'Asset downloader: ✅ {item["file"]} saved ({size_kb} KB)')
        except Exception as _e:
            _log_err('Asset downloader SFX', f'{item["file"]}: {_e}')

    # ── Reaction clips mp4s ───────────────────────────────────────────────────
    os.makedirs(_ASSETS_REACTION_DIR, exist_ok=True)
    import shutil as _sh

    yt_bin = _sh.which('yt-dlp') or str(paths.PKG_DIR.parent / '.venv' / 'bin' / 'yt-dlp')
    ffmpeg_bin = _sh.which('ffmpeg')
    # locate cookies file (same search order as Stage 4a)
    _REACT_COOKIE_PATHS = [
        os.path.join(_runtime_path(''), 'youtube_cookies.txt'),
        os.path.expanduser('~/youtube_cookies.txt'),
        os.path.expanduser('~/cookies/youtube_cookies.txt'),
        str(paths.PKG_DIR / 'youtube_cookies.txt'),
    ]
    _react_cookies = next((p for p in _REACT_COOKIE_PATHS if os.path.exists(p)), None)
    for item in _parse_reaction_catalogue():
        dest = os.path.join(_ASSETS_REACTION_DIR, item['file'])
        if os.path.exists(dest) and os.path.getsize(dest) > 10000:
            _log_info(f'Asset downloader: reaction {item["file"]} already present — skip')
            continue
        try:
            search_query = f'ytsearch1:{item["search"]}'
            tmp_out = dest.replace('.mp4', '_raw.%(ext)s')
            _log_info(f"Asset downloader: searching YouTube for reaction clip '{item['search']}'")
            dl_cmd = [
                yt_bin,
                '--no-playlist',
                '-f',
                'best[height<=480]',
                '--merge-output-format',
                'mp4',
                '--extractor-args',
                'youtube:player_client=android',
                '-o',
                tmp_out,
                '--quiet',
                '--no-warnings',
            ]
            if _react_cookies:
                dl_cmd += ['--cookies', _react_cookies]
            dl_cmd.append(search_query)
            _dl_sp.run(dl_cmd, capture_output=True, timeout=120)
            # find the downloaded raw file
            raw_path = dest.replace('.mp4', '_raw.mp4')
            if not os.path.exists(raw_path):
                for _ext in ('webm', 'mkv', 'mp4'):
                    _cand = dest.replace('.mp4', f'_raw.{_ext}')
                    if os.path.exists(_cand):
                        raw_path = _cand
                        break
            if not os.path.exists(raw_path):
                _log_err('Asset downloader reaction', f"{item['file']}: yt-dlp found nothing for '{item['search']}'")
                continue
            # trim to 2 seconds with ffmpeg
            if ffmpeg_bin:
                trim_cmd = [
                    ffmpeg_bin,
                    '-y',
                    '-i',
                    raw_path,
                    '-t',
                    '2',
                    '-c:v',
                    'libx264',
                    '-c:a',
                    'aac',
                    '-vf',
                    'scale=480:-2',
                    dest,
                ]
                _dl_sp.run(trim_cmd, capture_output=True, timeout=60)
                os.remove(raw_path)
            else:
                os.rename(raw_path, dest)
            size_kb = os.path.getsize(dest) // 1024 if os.path.exists(dest) else 0
            _log_info(f'Asset downloader: ✅ {item["file"]} saved ({size_kb} KB) trimmed to 2s')
        except Exception as _e:
            _log_err('Asset downloader reaction', f'{item["file"]}: {_e}')

    _log_info('Asset downloader: ✅ all assets processed')


@bp.route('/api/assets/download', methods=['POST'])
@limiter.exempt
def trigger_asset_download():
    """Trigger background download of all missing SFX and reaction clips."""
    t = threading.Thread(target=_download_assets_background, name='asset-downloader', daemon=True)
    t.start()
    return jsonify({'success': True, 'message': 'Asset download started — watch Live Tail for progress'})


@bp.route('/api/assets/status')
@limiter.exempt
def asset_status():
    """Return which asset files are present/missing."""
    sfx_items = _parse_sfx_catalogue()
    reaction_items = _parse_reaction_catalogue()
    sfx_status = []
    for item in sfx_items:
        p = os.path.join(_ASSETS_SFX_DIR, item['file'])
        sfx_status.append(
            {
                'file': item['file'],
                'name': item.get('name', item['file'].replace('.mp3', '')),
                'desc': item.get('desc', ''),
                'use_when': item.get('use_when', ''),
                'present': os.path.exists(p) and os.path.getsize(p) > 1000,
                'size_kb': os.path.getsize(p) // 1024 if os.path.exists(p) else 0,
            }
        )
    reaction_status = []
    for item in reaction_items:
        p = os.path.join(_ASSETS_REACTION_DIR, item['file'])
        reaction_status.append(
            {
                'file': item['file'],
                'source': item.get('source', ''),
                'desc': item.get('desc', ''),
                'use_when': item.get('use_when', ''),
                'present': os.path.exists(p) and os.path.getsize(p) > 10000,
                'size_kb': os.path.getsize(p) // 1024 if os.path.exists(p) else 0,
            }
        )
    return jsonify({'sfx': sfx_status, 'reaction_clips': reaction_status})


@bp.route('/api/assets/preview/<asset_type>/<path:filename>')
@limiter.exempt
def asset_preview(asset_type, filename):
    """Serve an asset file for in-browser preview (video/audio)."""
    from flask import send_file as _sf, abort as _abort

    safe = os.path.basename(filename)
    if asset_type == 'sfx':
        path = os.path.join(_ASSETS_SFX_DIR, safe)
    elif asset_type == 'reaction':
        path = os.path.join(_ASSETS_REACTION_DIR, safe)
    else:
        return _abort(404)
    if not os.path.exists(path):
        return _abort(404)
    return _sf(path, conditional=True)
