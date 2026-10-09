# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The media library and the runs on disk — verbatim sections of the former
vfx_analyzer.py."""

import hashlib
import json
import os
import shutil
import subprocess
import time

import numpy as np
from zyg_workflows.vfx_analyzer import _zyg_log
from zyg_workflows.vfx_analyzer.constants import (
    FFPROBE,
    MEDIA_DIR,
    RUNS_DIR,
    VIDEO_EXT,
    _ensure_dirs,
    _read_json,
    _safe_media_dir,
    _safe_run_dir,
    _write_json,
    _RUN_RE,
)


# ── media library ────────────────────────────────────────────────────────────


def _hash_file(path, cap=8 * 1024 * 1024):
    h = hashlib.sha1(usedforsecurity=False)
    n = 0
    with open(path, 'rb') as f:
        while n < cap:
            chunk = f.read(min(1 << 20, cap - n))
            if not chunk:
                break
            h.update(chunk)
            n += len(chunk)
    h.update(str(os.path.getsize(path)).encode())
    return h.hexdigest()[:12]


def register_upload(tmp_path, orig_name):
    """Adopt an uploaded file into the library. Content-addressed: re-uploading
    the same clip returns the existing entry instead of a second copy."""
    _ensure_dirs()
    ext = os.path.splitext(orig_name or '')[1].lower()
    if ext not in VIDEO_EXT:
        try:
            os.unlink(tmp_path)
        except OSError as _exc:
            _zyg_log.debug('rejected upload cleanup skipped: %s', _exc)
        return {'error': f'unsupported extension {ext!r}; accepted: {", ".join(VIDEO_EXT)}'}
    mid = _hash_file(tmp_path)
    d = os.path.join(MEDIA_DIR, mid)
    src = os.path.join(d, 'source' + ext)
    if os.path.isdir(d) and os.path.isfile(src):
        try:
            os.unlink(tmp_path)
        except OSError as _exc:
            _zyg_log.debug('duplicate upload cleanup skipped: %s', _exc)
        meta = _read_json(os.path.join(d, 'meta.json'), {})
        meta['duplicate_of_existing'] = True
        return meta
    os.makedirs(d, exist_ok=True)
    shutil.move(tmp_path, src)
    meta = {
        'media_id': mid,
        'name': os.path.basename(orig_name or 'upload')[:180],
        'ext': ext,
        'bytes': os.path.getsize(src),
        'added': time.strftime('%Y-%m-%d %H:%M:%S'),
        'added_ts': time.time(),
    }
    meta['probe'] = _probe_file(src)
    _write_json(os.path.join(d, 'meta.json'), meta)
    return meta


def _probe_file(path):
    """ffprobe the container. r_frame_rate is a RATIO ('24000/1001') and must be
    divided, never parsed as a float — 23.976 vs 24 is a whole frame of drift
    across ten seconds, which is enough to mis-align a cadence map."""
    try:
        out = subprocess.run(
            [FFPROBE, '-v', 'error', '-print_format', 'json', '-show_streams', '-show_format', path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        doc = json.loads(out.stdout or '{}')
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return {'error': f'{type(e).__name__}: {e}'}
    v = next((s for s in doc.get('streams', []) if s.get('codec_type') == 'video'), {})
    a = next((s for s in doc.get('streams', []) if s.get('codec_type') == 'audio'), {})

    def _rate(val):
        try:
            num, den = str(val).split('/')
            return float(num) / float(den) if float(den) else 0.0
        except (ValueError, ZeroDivisionError):
            try:
                return float(val)
            except (TypeError, ValueError):
                return 0.0

    fps = _rate(v.get('r_frame_rate') or 0)
    dur = 0.0
    for cand in (v.get('duration'), (doc.get('format') or {}).get('duration')):
        try:
            dur = float(cand)
            break
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('duration candidate %r is not numeric: %s', cand, _exc)
            continue
    return {
        'width': int(v.get('width') or 0),
        'height': int(v.get('height') or 0),
        'fps': round(fps, 6),
        'avg_fps': round(_rate(v.get('avg_frame_rate') or 0), 6),
        'duration_s': round(dur, 3),
        'nb_frames': int(v.get('nb_frames') or 0) if str(v.get('nb_frames') or '').isdigit() else 0,
        'codec': v.get('codec_name', ''),
        'pix_fmt': v.get('pix_fmt', ''),
        'has_audio': bool(a),
        'audio_codec': a.get('codec_name', ''),
        'sar': v.get('sample_aspect_ratio', ''),
        'dar': v.get('display_aspect_ratio', ''),
    }


def library():
    _ensure_dirs()
    items = []
    for mid in sorted(os.listdir(MEDIA_DIR)):
        d = _safe_media_dir(mid)
        if not d:
            continue
        meta = _read_json(os.path.join(d, 'meta.json'), None)
        if not meta:
            continue
        meta['runs'] = len([r for r in _run_ids() if r.startswith(mid + '_')])
        items.append(meta)
    items.sort(key=lambda m: -float(m.get('added_ts') or 0))
    return items


def get_media(media_id):
    d = _safe_media_dir(media_id)
    return _read_json(os.path.join(d, 'meta.json'), None) if d else None


def media_path(media_id):
    d = _safe_media_dir(media_id)
    if not d:
        return None
    for fn in os.listdir(d):
        if fn.startswith('source') and os.path.splitext(fn)[1].lower() in VIDEO_EXT:
            return os.path.join(d, fn)
    return None


def delete_media(media_id):
    d = _safe_media_dir(media_id)
    if not d:
        return {'error': 'unknown media'}
    for rid in _run_ids():
        if rid.startswith(media_id + '_'):
            rd = _safe_run_dir(rid)
            if rd:
                shutil.rmtree(rd, ignore_errors=True)
    shutil.rmtree(d, ignore_errors=True)
    return {'ok': True, 'media_id': media_id}


# ── runs on disk ─────────────────────────────────────────────────────────────


def _run_ids():
    _ensure_dirs()
    try:
        return sorted((r for r in os.listdir(RUNS_DIR) if _RUN_RE.match(r)), reverse=True)
    except OSError:
        return []


def runs(media_id=None):
    out = []
    for rid in _run_ids():
        if media_id and not rid.startswith(str(media_id) + '_'):
            continue
        d = _safe_run_dir(rid)
        if not d:
            continue
        rep = _read_json(os.path.join(d, 'report.json'), None)
        if not rep:
            continue
        out.append(
            {
                k: rep.get(k)
                for k in (
                    'run_id',
                    'media_id',
                    'media_name',
                    'started',
                    'finished',
                    'seconds',
                    'window',
                    'frames_scanned',
                    'unique_cels',
                    'cadence',
                    'totals',
                    'state',
                    'error',
                )
            }
        )
    return out


def run(run_id):
    d = _safe_run_dir(run_id)
    return _read_json(os.path.join(d, 'report.json'), None) if d else None


def _jsonl(run_id, name, limit=None, offset=0):
    d = _safe_run_dir(run_id)
    if not d:
        return []
    p = os.path.join(d, name)
    out = []
    try:
        with open(p, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                if i < offset:
                    continue
                if limit is not None and len(out) >= limit:
                    break
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError as _exc:
                        _zyg_log.debug('malformed jsonl line ignored: %s', _exc)
    except OSError:
        return []
    return out


def frames(run_id, limit=None, offset=0):
    return _jsonl(run_id, 'frames.jsonl', limit, offset)


def events(run_id):
    return _jsonl(run_id, 'events.jsonl')


def unknowns(run_id):
    return _jsonl(run_id, 'unknowns.jsonl')


def log_text(run_id, tail=4000):
    d = _safe_run_dir(run_id)
    if not d:
        return ''
    try:
        with open(os.path.join(d, 'run.log'), 'r', encoding='utf-8') as f:
            lines = f.readlines()
        return ''.join(lines[-tail:])
    except OSError:
        return ''


def frame_image_path(run_id, index):
    d = _safe_run_dir(run_id)
    if not d:
        return None
    try:
        i = int(index)
    except (TypeError, ValueError):
        return None
    p = os.path.realpath(os.path.join(d, 'frames', 'f%06d.jpg' % i))
    return p if p.startswith(os.path.realpath(d) + os.sep) and os.path.isfile(p) else None


def crop_image_path(run_id, name):
    d = _safe_run_dir(run_id)
    if not d or not name or os.path.basename(name) != name:
        return None
    p = os.path.realpath(os.path.join(d, 'crops', name))
    return p if p.startswith(os.path.realpath(d) + os.sep) and os.path.isfile(p) else None


def features(run_id):
    """The cached per-frame embeddings for a run, or None."""
    d = _safe_run_dir(run_id)
    if not d:
        return None
    p = os.path.join(d, 'features.npy')
    try:
        return np.load(p) if os.path.isfile(p) else None
    except (OSError, ValueError):
        return None


def delete_run(run_id):
    d = _safe_run_dir(run_id)
    if not d:
        return {'error': 'unknown run'}
    shutil.rmtree(d, ignore_errors=True)
    return {'ok': True, 'run_id': run_id}
