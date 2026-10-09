# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Video Studio, presets and the two render entry points.

Moved verbatim (lines 5190-5305 of the old single-file module): the preset
files under _PRESET_DIR, the frame extractor that turns an existing clip into
an I2V starting image, and start_render() / start_render_from_video(), which
register a job and hand it to assembly._render_worker.

Last in the package's import order because it is the only module that needs
the render worker.
"""

import hashlib
import json
import os
import subprocess
import threading
import time

from zyg_workflows import wan_video_service as _wan
from zyg_workflows.bin import exe

from . import _OUT_ROOT, _PRESET_DIR, _zyg_log
from .assembly import _render_worker
from .render_jobs import _JOBS, _JOBS_LOCK, _prune_jobs, job
from .spec import sanitize


# ──────────────────────────────────────────────────────────────────── presets
def presets() -> list:
    try:
        return sorted(f[:-5] for f in os.listdir(_PRESET_DIR) if f.endswith('.json'))
    except OSError:
        return []


def preset_load(name: str) -> dict:
    safe = ''.join(c for c in (name or '') if c.isalnum() or c in ' _-')[:60].strip()
    if not safe:
        raise ValueError('bad preset name')
    with open(os.path.join(_PRESET_DIR, f'{safe}.json')) as fh:
        return sanitize(json.load(fh))


def preset_save(name: str, params: dict) -> str:
    safe = ''.join(c for c in (name or '') if c.isalnum() or c in ' _-')[:60].strip()
    if not safe:
        raise ValueError('bad preset name')
    os.makedirs(_PRESET_DIR, exist_ok=True)
    with open(os.path.join(_PRESET_DIR, f'{safe}.json'), 'w') as fh:
        json.dump(sanitize(params), fh, indent=1)
    return safe


def preset_delete(name: str) -> None:
    safe = ''.join(c for c in (name or '') if c.isalnum() or c in ' _-')[:60].strip()
    if not safe:
        raise ValueError('bad preset name')
    try:
        os.remove(os.path.join(_PRESET_DIR, f'{safe}.json'))
    except OSError as _exc:
        _zyg_log.warning('preset %s was not deleted: %s', safe, _exc)


_INJECT_FRAME_DIR = os.path.join(_OUT_ROOT, '_inject_frames')


def _extract_at(src_video_path: str, out_png: str, mode: str, at_s: float) -> bool:
    """Pull the seed frame. 'last' reuses wan_video_service's own extractor (the
    same one the chained sub-clip loop uses between links); 'first'/'time' are a
    single ffmpeg seek."""
    if mode == 'last':
        return _wan._extract_last_frame(src_video_path, out_png, None)
    args = [exe('ffmpeg'), '-y']
    if mode == 'time' and at_s > 0:
        args += ['-ss', f'{at_s:.3f}']
    args += ['-i', src_video_path, '-frames:v', '1', '-q:v', '2', out_png]
    try:
        r = subprocess.run(args, capture_output=True, timeout=120)
        return r.returncode == 0 and os.path.isfile(out_png)
    except Exception:
        return False


def start_render_from_video(video_id: str, video_label: str, src_video_path: str, params: dict) -> dict:
    """Continue (or re-take) an existing clip: pull the seed frame chosen by the
    SOURCE rack and feed it into start_render() as the I2V starting image.
    Extract-once, cache-by-(source-path, mode, timestamp) so changing Start
    frame re-extracts instead of silently reusing the previous one."""
    if not src_video_path or not os.path.isfile(src_video_path):
        raise ValueError('video not found')
    p = sanitize(params)
    os.makedirs(_INJECT_FRAME_DIR, exist_ok=True)
    ident = f'{src_video_path}|{p["start_from"]}|{p["start_at_s"]:.2f}'
    key = hashlib.sha1(ident.encode(), usedforsecurity=False).hexdigest()[:20]
    frame_path = os.path.join(_INJECT_FRAME_DIR, f'{key}.png')
    src_mtime = os.path.getmtime(src_video_path)
    if not (os.path.isfile(frame_path) and os.path.getmtime(frame_path) >= src_mtime):
        if not _extract_at(src_video_path, frame_path, p['start_from'], p['start_at_s']):
            raise ValueError('could not extract a frame from that video')

    # The end frame (FLF2V) comes out of the same clip, cached the same way.
    # 'start' reuses the seed frame itself — that is the honest way to ask the
    # MODEL for a closed loop, rather than crossfading one in the finish.
    end_path = ''
    if p['end_frame'] != 'off':
        if p['end_frame'] == 'start':
            end_path = frame_path
        else:
            e_ident = f'{src_video_path}|end|{p["end_frame"]}|{p["end_at_s"]:.2f}'
            e_key = hashlib.sha1(e_ident.encode(), usedforsecurity=False).hexdigest()[:20]
            end_path = os.path.join(_INJECT_FRAME_DIR, f'{e_key}.png')
            if not (os.path.isfile(end_path) and os.path.getmtime(end_path) >= src_mtime):
                if not _extract_at(src_video_path, end_path, p['end_frame'], p['end_at_s']):
                    raise ValueError('could not extract the end frame from that video')
    return start_render(video_id, video_label, frame_path, params, end_img=end_path)


def start_render(char_id: str, char_name: str, img_path: str, params: dict, end_img: str = '') -> dict:
    if not img_path or not os.path.isfile(img_path):
        raise ValueError('no start image found')
    p = sanitize(params)
    jid = f'{int(time.time() * 1000):x}{os.getpid():x}'
    with _JOBS_LOCK:
        _JOBS[jid] = {
            'id': jid,
            'char_id': char_id,
            'char_name': char_name,
            'state': 'queued',
            'log': [],
            'params': p,
            'url': '',
            'urls': [],
            'error': '',
            'progress': '',
            'end_img': end_img,
            'started': time.time(),
            'finished': 0.0,
        }
        _prune_jobs()
    threading.Thread(target=_render_worker, args=(jid, img_path, char_name), daemon=True).start()
    return job(jid)
