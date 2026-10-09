# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""Paths, tool locations and corpus-measured constants."""

import os
import shutil
import threading
from datetime import datetime, timezone


try:
    from zyg_zero.zpub_config import _ams_iso
except Exception:  # pragma: no cover - standalone use

    def _ams_iso(timespec: str = 'milliseconds') -> str:
        return datetime.now(timezone.utc).isoformat(timespec=timespec)


# NOTE: one dirname() more than the single-file zpub_cinema.py needed -- this
# module sits inside the package, so _HERE must still resolve to .../zyg_zero.
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME_DIR = os.path.join(_HERE, 'data', 'runtime')
LIBRARY_PATH = os.path.join(RUNTIME_DIR, 'cinema_library.json')
CACHE_DIR = os.path.join(RUNTIME_DIR, 'cinema_cache')
THUMB_DIR = os.path.join(CACHE_DIR, 'thumbs')
SUB_DIR = os.path.join(CACHE_DIR, 'subs')
for _d in (RUNTIME_DIR, CACHE_DIR, THUMB_DIR, SUB_DIR):
    os.makedirs(_d, exist_ok=True)

FFMPEG = shutil.which('ffmpeg') or '/usr/bin/ffmpeg'
FFPROBE = shutil.which('ffprobe') or '/usr/bin/ffprobe'

VIDEO_EXTS = {
    '.mkv',
    '.mp4',
    '.avi',
    '.m4v',
    '.mov',
    '.webm',
    '.wmv',
    '.flv',
    '.mpg',
    '.mpeg',
    '.ts',
    '.m2ts',
    '.ogv',
    '.divx',
    '.vob',
}
SUB_EXTS = {'.srt', '.vtt', '.ass', '.ssa', '.sub'}

# Files this small are trailers/samples, never a feature.
MIN_VIDEO_BYTES = 20 * 1024 * 1024
# Directories that never hold a feature.
SKIP_DIRS = {
    'other',
    'sample',
    'samples',
    'screens',
    'screenshots',
    'extras',
    'featurettes',
    'proof',
    '.thumbs',
    '__macosx',
}

_lock = threading.RLock()
