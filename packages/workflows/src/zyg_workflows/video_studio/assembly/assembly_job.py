# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Video Studio: the multi-shot assembly job — the SHOTS rack resolved to real
files, the worker thread and start_assemble()."""

import json
import os
import threading
import time


from .. import HERE, _OUT_ROOT
from ..ffmpeg_finish import _audio_spec
from ..render_jobs import _JOBS, _JOBS_LOCK, _job_log, _job_set, _prune_jobs, job
from ..spec import sanitize


# ─────────────────────────────────────────────────────────────── assembly job
_MEDIA_ROOT = os.path.realpath(os.path.join(HERE, 'output'))


def _resolve_shot_path(ref: str) -> str:
    """A shot's path as the GUI writes it → a real file on this box.

    The board hands clips around as MEDIA paths ('out/video_studio/<job>/
    clip.mp4'), which is what /inspect/media serves, not a filesystem path.
    Anything relative is resolved under this project's output/ tree and then
    checked to still BE under it — a shot list is operator input, and
    '../../etc/passwd' must not become an ffmpeg input."""
    ref = str(ref or '').strip()
    if not ref:
        return ''
    if os.path.isabs(ref):
        return ref
    rel = ref[4:] if ref.startswith('out/') else ref
    full = os.path.realpath(os.path.join(_MEDIA_ROOT, rel))
    if full != _MEDIA_ROOT and not full.startswith(_MEDIA_ROOT + os.sep):
        raise ValueError(f'shot path escapes the output folder: {ref}')
    return full


def _prepare_shotlist(p: dict) -> dict:
    """The SHOTS rack as a video_assembly shot list, paths resolved."""
    try:
        sl = json.loads(str(p.get('shot_list') or '{}') or '{}')
    except (TypeError, ValueError) as exc:
        raise ValueError(f'shot list is not readable JSON: {exc}') from exc
    if not isinstance(sl, dict):
        raise ValueError('shot list must be a JSON object')
    sl = dict(sl)
    shots = []
    for shot in sl.get('shots') or []:
        if not isinstance(shot, dict):
            raise ValueError(f'shot list holds a non-object shot: {shot!r}')
        s = dict(shot)
        for key in ('path', 'still'):
            if s.get(key):
                s[key] = _resolve_shot_path(s[key])
                if not os.path.isfile(s[key]):
                    raise ValueError(f'shot not found: {shot[key]}')
        s.setdefault('xfade_s', float(p['shot_xfade']))
        shots.append(s)
    if not shots:
        raise ValueError('shot list has no shots — fill the SHOTS rack first')
    sl['shots'] = shots
    # The FINISH fades and the AUDIO rack apply to the PROGRAMME here, not to
    # each shot; a shot list that names its own wins, because it was written
    # for this cut.
    sl.setdefault('fade_in_s', float(p['fade_in']))
    sl.setdefault('fade_out_s', float(p['fade_out']))
    sl.setdefault('fade_color', p['fade_color'])
    if 'audio' not in sl:
        sl['audio'] = _audio_spec(p) or None
    return sl


def _assemble_worker(jid: str):
    _job_set(jid, state='running')
    log = lambda msg: _job_log(jid, msg)  # noqa: E731
    out_dir = os.path.join(_OUT_ROOT, jid)
    try:
        p = job(jid)['params']
        sl = _prepare_shotlist(p)
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, 'assembly.mp4')
        log(
            f'assembling {len(sl["shots"])} shot(s) at {sl.get("fps", 24)}fps, '
            f'default crossfade {float(p["shot_xfade"]):g}s, audio ' + ('on' if sl.get('audio') else 'none')
        )
        from zyg_workflows import video_assembly as _vasm

        rec = _vasm.assemble(sl, out, log=log)
        url = f'/inspect/media?path=out/video_studio/{jid}/assembly.mp4'
        log(
            f'assembled {float(rec.get("total_s", 0) or 0):.2f}s from '
            f'{len(rec.get("shots") or [])} shot(s) in '
            f'{float(rec.get("seconds", 0) or 0):.0f}s'
        )
        _job_set(jid, state='done', url=url, urls=[url], finished=time.time())
        log('done')
    except Exception as e:  # noqa: BLE001 — any failure ends the job, never the server
        log(f'error: {e}')
        _job_set(jid, state='error', error=str(e), finished=time.time())


def start_assemble(params: dict) -> dict:
    """Start an assembly job from the SHOTS rack. Returns the job dict, same
    registry and polling contract as start_render()."""
    p = sanitize(params)
    jid = f'{int(time.time() * 1000):x}{os.getpid():x}'
    with _JOBS_LOCK:
        _JOBS[jid] = {
            'id': jid,
            'char_id': '',
            'char_name': 'assembly',
            'state': 'queued',
            'log': [],
            'params': p,
            'url': '',
            'urls': [],
            'error': '',
            'progress': '',
            'end_img': '',
            'started': time.time(),
            'finished': 0.0,
        }
        _prune_jobs()
    threading.Thread(target=_assemble_worker, args=(jid,), daemon=True).start()
    return job(jid)
