# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Paths, tunables, process-wide state and the taxonomy loader — verbatim sections of
the former vfx_analyzer.py."""

import json
import os
import re
import threading

from zyg_workflows import paths

# _HERE was vfx_analyzer.py's own directory — the zyg_workflows package directory.
_HERE = str(paths.PKG_DIR)
ROOT = paths.ZYG_VFX_ROOT
MEDIA_DIR = os.path.join(ROOT, 'media')
RUNS_DIR = os.path.join(ROOT, 'runs')
TAXONOMY_PATH = os.environ.get('ZYG_VFX_TAXONOMY', str(paths.DATA_DIR / 'runtime' / 'vfx_taxonomy.json'))

FFMPEG = os.environ.get('ZYG_FFMPEG', '/usr/bin/ffmpeg')
FFPROBE = os.environ.get('ZYG_FFPROBE', '/usr/bin/ffprobe')
OLLAMA = paths.ZYG_OLLAMA_URL.rstrip('/')
VLM_MODEL = os.environ.get(
    'ZYG_VFX_VLM', 'qwen3.5:9b'
)  # 2026-09-04: qwen2.5vl removed from Ollama (segfaulted on this build); qwen3.5:9b is the vision default

VIDEO_EXT = ('.mp4', '.mkv', '.mov', '.webm', '.avi', '.m4v', '.mpg', '.mpeg', '.ts', '.wmv')
MAX_WINDOW_S = float(os.environ.get('ZYG_VFX_MAX_WINDOW', 120))
DEFAULT_WINDOW_S = float(os.environ.get('ZYG_VFX_WINDOW', 10))

_ID_RE = re.compile(r'^[a-f0-9]{12}$')
_RUN_RE = re.compile(r'^[a-f0-9]{12}_[0-9]{8}_[0-9]{6}$')
_JOBS = {}
_JOBS_LOCK = threading.Lock()
_JOB_KEEP = 24
_TAX = {'data': None, 'mtime': 0.0}


# ── small utilities ──────────────────────────────────────────────────────────


def _ensure_dirs():
    for d in (ROOT, MEDIA_DIR, RUNS_DIR):
        os.makedirs(d, exist_ok=True)


def _read_json(path, default=None):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


def _safe_media_dir(media_id):
    if not media_id or not _ID_RE.match(str(media_id)):
        return None
    d = os.path.realpath(os.path.join(MEDIA_DIR, media_id))
    root = os.path.realpath(MEDIA_DIR)
    return d if d.startswith(root + os.sep) and os.path.isdir(d) else None


def _safe_run_dir(run_id):
    if not run_id or not _RUN_RE.match(str(run_id)):
        return None
    d = os.path.realpath(os.path.join(RUNS_DIR, run_id))
    root = os.path.realpath(RUNS_DIR)
    return d if d.startswith(root + os.sep) and os.path.isdir(d) else None


# ── taxonomy ─────────────────────────────────────────────────────────────────


def taxonomy(force=False):
    """The observable ontology: every thing the analyzer knows how to look for,
    whether or not it can currently see it. Hot-reloaded when the file changes
    so the list can be edited without a server restart."""
    try:
        mt = os.path.getmtime(TAXONOMY_PATH)
    except OSError:
        mt = 0.0
    if _TAX['data'] is not None and not force and mt == _TAX['mtime']:
        return _TAX['data']
    doc = _read_json(TAXONOMY_PATH, None)
    if not isinstance(doc, dict) or not isinstance(doc.get('entries'), list):
        doc = {'version': 0, 'entries': [], 'error': f'taxonomy missing or malformed at {TAXONOMY_PATH}'}
    by_id = {}
    for e in doc.get('entries') or []:
        if isinstance(e, dict) and e.get('id'):
            by_id[str(e['id'])] = e
    doc['by_id'] = by_id
    doc['count'] = len(by_id)
    _TAX['data'], _TAX['mtime'] = doc, mt
    return doc
