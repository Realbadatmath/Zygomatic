# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 4a preflight: download videos and transcripts."""

import json
import os
import threading
from zyg_workflows.stage_runner.agents import _pf_agents_active
from zyg_workflows.stage_runner.agents import _pf_agents_done
from zyg_workflows.runtime import _runtime_path
from zyg_workflows import paths

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.stage_runner')


def _pf_stage_4a(stage_name, state, pipeline_id, _save, _log_err, _log_warn, _log_info):
    """The Stage 4a branch of _stage_preflight, verbatim (original lines 807-1022).

    Only the branch keyword changed: the original ``elif`` is an ``if`` here.
    """
    # ── Stage 4a: download videos and transcripts ───────────────────────────
    if 'Stage 4a' in stage_name:
        _pf_agents_active(
            pipeline_id,
            stage_name,
            [
                'CLIPFARM-Video-Fetch-Agent',
                'CLIPFARM-Transcript-Fetch-Agent',
                'CLIPFARM-Rights-Check-Agent',
                'CLIPFARM-Content-Indexer-Agent',
            ],
        )
        approved = state.get('approved_clips', [])
        out_dir = state.get('output_dir') or str(paths.tmp_dir('clipfarm'))
        os.makedirs(out_dir, exist_ok=True)
        _log_info(f'{len(approved)} approved clips to fetch')
        try:
            from zyg_workflows.tools.data_tools import YouTubeTranscriptAPITool

            tx_tool = YouTubeTranscriptAPITool()
        except Exception as _ie:
            _log_err('Stage 4a import', str(_ie))
            tx_tool = None
        fetched = {}
        fetched_lock = threading.Lock()

        # ── Locate YouTube cookies file (checked once per Stage 4a run) ────────
        _COOKIES_SEARCH_PATHS = [
            os.path.join(_runtime_path(''), 'youtube_cookies.txt'),  # data/runtime/
            os.path.expanduser('~/youtube_cookies.txt'),  # home dir
            os.path.expanduser('~/cookies/youtube_cookies.txt'),  # ~/cookies/
            str(paths.ZYG_HOME / 'youtube_cookies.txt'),  # explicit
            str(paths.PKG_DIR / 'youtube_cookies.txt'),  # inside the package
        ]
        _cookies_file = next((p for p in _COOKIES_SEARCH_PATHS if os.path.exists(p)), None)
        if _cookies_file:
            _log_info(f'Stage 4a: using YouTube cookies from {_cookies_file}')
        else:
            _log_info(
                'Stage 4a: no youtube_cookies.txt found — downloads may be bot-blocked. '
                'Drop a cookies file at ~/youtube_cookies.txt to fix.'
            )

        def _fetch_one(clip):
            vid_id = clip.get('video_id', '')
            url = clip.get('url', f'https://www.youtube.com/watch?v={vid_id}')
            if not vid_id:
                return
            vid_out_path = os.path.join(out_dir, f'{vid_id}.mp4')
            if not os.path.exists(vid_out_path):
                try:
                    import yt_dlp as _ytdlp
                    import shutil as _shutil

                    _ffmpeg_bin = _shutil.which('ffmpeg')
                    if _ffmpeg_bin:
                        _fmt = 'bestvideo[height<=1080]+bestaudio/bestvideo+bestaudio/best'
                    else:
                        _fmt = 'best[ext=mp4]/best'

                    def _dl_progress_hook(d):
                        if d.get('status') == 'downloading':
                            downloaded = d.get('downloaded_bytes', 0)
                            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                            speed = d.get('speed') or 0
                            if total > 0:
                                pct = downloaded / total * 100
                                speed_mb = speed / 1_048_576
                                _log_info(
                                    f'Stage 4a: downloading {vid_id} — '
                                    f'{pct:.0f}% of {total / 1_048_576:.1f} MB '
                                    f'@ {speed_mb:.1f} MB/s'
                                )
                        elif d.get('status') == 'finished':
                            total = d.get('total_bytes') or d.get('downloaded_bytes', 0)
                            elapsed = d.get('elapsed') or 1
                            speed_mb = (total / elapsed) / 1_048_576
                            _log_info(
                                f'Stage 4a: ✅ {vid_id} downloaded — '
                                f'{total / 1_048_576:.1f} MB in {elapsed:.0f}s '
                                f'({speed_mb:.1f} MB/s avg)'
                            )

                    # Locate node binary for JS challenge solving (gives full 1080p formats)
                    _node_bin = str(paths.PKG_DIR.parent / '.venv' / 'bin' / 'node')
                    if not os.path.exists(_node_bin):
                        import shutil as _sh2

                        _node_bin = _sh2.which('node') or ''
                    _ydl_opts = {
                        'format': _fmt,
                        'outtmpl': os.path.join(out_dir, f'{vid_id}.%(ext)s'),
                        'merge_output_format': 'mp4',
                        'quiet': True,
                        'no_warnings': True,
                        'progress_hooks': [_dl_progress_hook],
                    }
                    if _node_bin:
                        _ydl_opts['js_runtimes'] = {'node': {'path': _node_bin}}
                        _ydl_opts['remote_components'] = ['ejs:github']
                    if _ffmpeg_bin:
                        _ydl_opts['ffmpeg_location'] = os.path.dirname(_ffmpeg_bin)
                    if _cookies_file:
                        _ydl_opts['cookiefile'] = _cookies_file
                    with _ytdlp.YoutubeDL(_ydl_opts) as _ydl:
                        _ydl.download([url])
                except Exception as _e:
                    _err_str = str(_e)
                    if (
                        'live event' in _err_str.lower()
                        or 'live stream' in _err_str.lower()
                        or 'this live' in _err_str.lower()
                        or 'is upcoming' in _err_str.lower()
                    ):
                        _log_warn(f'Stage 4a: skipping {vid_id} — it is a live/upcoming stream: {_err_str[:120]}')
                        return  # skip this video entirely — no file, no transcript
                    _log_err(f'Stage 4a download {vid_id}', _err_str)
            # Find the actual downloaded file (yt-dlp may use .webm/.mkv if mp4 unavailable)
            _actual_path = vid_out_path
            if not os.path.exists(vid_out_path):
                for _ext in ('webm', 'mkv', 'mp4', 'm4v'):
                    _candidate = os.path.join(out_dir, f'{vid_id}.{_ext}')
                    if os.path.exists(_candidate):
                        _actual_path = _candidate
                        break
            if os.path.exists(_actual_path):
                with fetched_lock:
                    fetched[vid_id] = _actual_path
            else:
                _log_err(f'Stage 4a {vid_id}', 'Download completed but file not found on disk')
            # Fetch transcript — try YouTube API first, fall back to local Whisper
            tx_path = os.path.join(out_dir, f'{vid_id}_transcript.json')
            tx_ok = False
            if tx_tool:
                try:
                    tx_raw = tx_tool._run(video_id=vid_id)
                    tx_data = json.loads(tx_raw) if tx_raw.strip().startswith('{') else {}
                    if tx_data.get('segments') and len(tx_data['segments']) > 0:
                        with open(tx_path, 'w') as _tf:
                            _tf.write(tx_raw)
                        tx_ok = True
                        _log_info(f'Stage 4a {vid_id}: YouTube transcript OK ({len(tx_data["segments"])} segments)')
                    else:
                        _log_err(
                            f'Stage 4a transcript {vid_id}',
                            f'YouTube API returned no segments: {tx_data.get("error", "unknown")}',
                        )
                except Exception as _e:
                    _log_err(f'Stage 4a transcript {vid_id}', str(_e))

            # Whisper fallback: transcribe audio from the downloaded video
            if not tx_ok:
                vid_path_for_tx = fetched.get(vid_id)
                if vid_path_for_tx and os.path.exists(vid_path_for_tx):
                    try:
                        import whisper as _whisper

                        _log_info(f'Stage 4a {vid_id}: YouTube transcript unavailable — running Whisper locally')
                        _wmodel = _whisper.load_model('base')
                        _wresult = _wmodel.transcribe(vid_path_for_tx, fp16=True, verbose=False, language='en')
                        # Convert Whisper output to same segment format as YouTube API
                        _segments = [
                            {
                                'start': float(seg['start']),
                                'duration': float(seg['end']) - float(seg['start']),
                                'text': seg['text'].strip(),
                            }
                            for seg in _wresult.get('segments', [])
                        ]
                        _full_text = ' '.join(s['text'] for s in _segments)
                        _tx_data = {
                            'video_id': vid_id,
                            'language': 'en',
                            'source': 'whisper_local',
                            'full_text': _full_text,
                            'segment_count': len(_segments),
                            'segments': _segments,
                        }
                        with open(tx_path, 'w') as _tf:
                            json.dump(_tx_data, _tf, indent=2)
                        _log_info(f'Stage 4a {vid_id}: Whisper transcribed {len(_segments)} segments')
                        # Unload Whisper model immediately to free VRAM
                        del _wmodel
                        import gc as _gc

                        _gc.collect()
                        try:
                            import torch as _torch

                            if _torch.cuda.is_available():
                                _torch.cuda.empty_cache()
                        except Exception as _exc:
                            _zyg_log.debug('cuda cache release after whisper skipped: %s', _exc)
                    except Exception as _we:
                        _log_err(f'Stage 4a whisper {vid_id}', str(_we))
                else:
                    _log_err(f'Stage 4a transcript {vid_id}', 'No video file available for Whisper fallback')

        import concurrent.futures as _cf4a

        with _cf4a.ThreadPoolExecutor(max_workers=5) as _pool4a:
            list(_pool4a.map(_fetch_one, approved[:5]))

        state['fetched_files'] = fetched
        _save(state)
        _log_info(f'fetched_files: {list(fetched.keys())}')
        _pf_agents_done(
            pipeline_id,
            stage_name,
            [
                'CLIPFARM-Video-Fetch-Agent',
                'CLIPFARM-Transcript-Fetch-Agent',
                'CLIPFARM-Rights-Check-Agent',
                'CLIPFARM-Content-Indexer-Agent',
            ],
        )
