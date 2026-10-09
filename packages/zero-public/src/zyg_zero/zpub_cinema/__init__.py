#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Zero Cinema — private media library behind the fingerprint gate
================================================================
Scans folders for movies/series, probes them with ffprobe, builds thumbnails,
discovers subtitles (external files + embedded streams) and decides whether a
title can be served byte-for-byte or has to be transcoded on the fly.

Why this shape
--------------
* The library index is a plain JSON file (data/runtime/cinema_library.json).
  It survives restarts, is trivially inspectable, and needs no Redis.
* Nothing is probed twice: an entry is re-probed only when (size, mtime) move.
* Thumbnails come from the VIDEO ITSELF by default. Folder images are only used
  when they pass a denylist — measured 2026-08-30: the genuine backdrop shipped
  with "Gods of Egypt" is 1012x468 (landscape) while the YTS/YIFY *advertising*
  banners are 350x500 (portrait, poster-shaped). An aspect-ratio heuristic picks
  exactly the wrong file here, so the NAME is the primary signal, not the shape.
"""

# ruff: noqa: E402, F401
# E402: the submodule imports must follow the original top import block so
#       that zpub_cinema.os / zpub_cinema.json keep resolving, and must run
#       in the original section order.
# F401: this file IS the re-export surface.

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone


import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# Submodules, in the original section order — module-level side effects
# (the runtime/cache makedirs in constants) run exactly when they used to.
from . import constants as _mod_constants
from . import naming as _mod_naming
from . import probing as _mod_probing
from . import prefs as _mod_prefs
from . import library as _mod_library
from . import vtt as _mod_vtt
from . import playback as _mod_playback
from . import hls as _mod_hls
from . import assembly as _mod_assembly

# Every name the single-file module defined, public and underscore alike.
from .constants import _ams_iso
from .constants import _HERE
from .constants import RUNTIME_DIR
from .constants import LIBRARY_PATH
from .constants import CACHE_DIR
from .constants import THUMB_DIR
from .constants import SUB_DIR
from .constants import FFMPEG
from .constants import FFPROBE
from .constants import VIDEO_EXTS
from .constants import SUB_EXTS
from .constants import MIN_VIDEO_BYTES
from .constants import SKIP_DIRS
from .constants import _lock
from .naming import _QUALITY_TOKENS
from .naming import _QUALITY_RE
from .naming import _YEAR_RE
from .naming import _HALF
from .naming import _EPISODE_RES
from .naming import _SEASON_DIR_RE
from .naming import _AD_IMAGE_RE
from .naming import _POSTER_NAME_RE
from .naming import _clean_title
from .naming import parse_release_name
from .naming import detect_episode
from .naming import _LANG_MAP
from .naming import _LANG_NAMES
from .naming import _norm_lang
from .naming import _lang_from_filename
from .naming import _lang_label
from .probing import _run
from .probing import _parse_chapters
from .probing import probe
from .probing import BROWSER_VCODECS
from .probing import BROWSER_ACODECS
from .probing import DIRECT_CONTAINERS
from .probing import _playback_plan
from .prefs import PREFS_PATH
from .prefs import DEFAULT_PREFS
from .prefs import _PREFS_KEYS
from .prefs import _prefs_cache
from .prefs import _blank_prefs
from .prefs import load_prefs
from .prefs import save_prefs
from .prefs import show_key
from .prefs import item_show_key
from .prefs import _coerce_pref
from .prefs import update_prefs
from .prefs import display_series
from .prefs import prefs_for
from .prefs import _kw_score
from .prefs import _lang_score
from .prefs import _external_subs
from .prefs import TEXT_SUB_CODECS
from .prefs import IMAGE_SUB_CODECS
from .prefs import _embedded_subs
from .prefs import _sub_rank
from .prefs import pick_default_sub
from .prefs import _audio_rank
from .prefs import pick_default_audio
from .prefs import _OP_STRICT_RE
from .prefs import _OP_LOOSE_RE
from .prefs import _TAIL_CH_RE
from .prefs import OP_MIN_SECONDS
from .prefs import OP_MAX_SECONDS
from .prefs import detect_marks
from .prefs import chapters_of
from .library import set_series_name
from .library import _folder_artwork
from .library import thumb_path
from .library import _frame_score
from .library import _lavfi_escape
from .library import _THUMB_DARK_FLOOR
from .library import _THUMB_BLOWN_CEIL
from .library import _THUMB_GOOD_LUMA
from .library import _THUMB_GOOD_BYTES
from .library import _THUMB_FRACTIONS
from .library import build_thumb
from .library import _blank_library
from .library import load_library
from .library import save_library
from .library import item_id_for
from .library import _walk_videos
from .library import build_item
from .library import _scans
from .library import _scan_lock
from .library import scan_status
from .library import start_scan
from .vtt import _TIME_RE
from .vtt import _read_text
from .vtt import srt_to_vtt
from .vtt import _VTT_CUE_RE
from .vtt import _vtt_seconds
from .vtt import _vtt_stamp
from .vtt import shift_vtt
from .vtt import _VTT_TAG_RE
from .vtt import _ASS_BRACE_RE
from .vtt import _ASS_DRAW_RE
from .vtt import SUB_MIN_VISIBLE
from .vtt import SUB_MAX_ACTIVE
from .vtt import SUB_MERGE_GAP
from .vtt import SUB_CACHE_VER
from .vtt import _vtt_blocks
from .vtt import tidy_vtt
from .vtt import _ffmpeg_to_vtt
from .vtt import subtitle_vtt
from .playback import NVENC_MAX_HEIGHT
from .playback import _audio_order
from .playback import transcode_commands
from .playback import keyframe_before
from .playback import exact_start
from .playback import stream_transcode
from .hls import HLS_DIR
from .hls import HLS_SEG_SECONDS
from .hls import HLS_LEAD_SECONDS
from .hls import HLS_IDLE_TIMEOUT
from .hls import HLS_START_TIMEOUT
from .hls import HLS_MIN_FREE_BYTES
from .hls import _HLS
from .hls import _HLS_LOCK
from .hls import _FPS_CACHE
from .hls import _video_fps
from .hls import _hls_tail
from .hls import hls_commands
from .hls import _hls_read_playlist
from .hls import _hls_governor
from .hls import start_hls
from .hls import get_hls
from .hls import note_hls_segment
from .hls import close_hls
from .hls import sweep_hls
from .hls import _norm_title
from .hls import version_suffixes
from .assembly import EPISODE_CHUNK
from .assembly import assign_absolute
from .assembly import _card
from .assembly import board
from .assembly import get_item
from .assembly import item_detail
from .assembly import _audio_label

# '_d' is the makedirs loop variable the single file leaked, and
# __annotations__ is what its compiler built from the five annotated
# module-level assignments; both are rebuilt so that nothing the old
# module exposed disappears.
from .constants import _d

__annotations__ = {}
for _m in (_mod_prefs, _mod_library, _mod_hls):
    __annotations__.update(getattr(_m, '__annotations__', None) or {})
