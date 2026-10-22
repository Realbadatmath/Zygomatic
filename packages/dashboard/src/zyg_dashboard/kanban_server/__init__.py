# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kanban_server.py — static file server + inspection API for the Workflows Kanban.

Serves kanban.html on port 8899. The HTML polls the Flask API (port 5000) for
live pipeline status via the three public endpoints:
  /api/kanban/status
  /api/workflow_status/active
  /api/workflow/steps/agents

2026-07-26: also serves the Contact-Sheet Inspection SPA (inspection.html) with a
small READ-ONLY JSON API + path-safe image serving so the page can live-track a
character's generated images as the pipeline writes them:
  /inspect/api/list                         -> all characters that have a contact sheet
  /inspect/api/char/spec                    -> Character Studio's editable-field registry
  /inspect/api/char/bible                   -> one character's bible + facts measured off disk
  /inspect/api/char/bible/save  (POST)      -> apply dotted-path edits to that bible
  /inspect/api/char?id=<char_id>            -> one character: status + grouped image lists
  /inspect/img?id=<char_id>&cat=<c>&name=<f>-> serve one image (strictly validated)

Run standalone or via start_production.sh.

The listening address is ``zyg_workflows.paths.BIND_HOST`` and defaults to
``127.0.0.1``: this server is loopback-only unless LAN exposure is asked for
explicitly by setting ``BIND_HOST=0.0.0.0`` in the environment.
"""

# Every name the pre-split module bound at import time is re-exported here, used or
# not: outside callers reach them as ``zyg_dashboard.kanban_server.<name>``. The
# surface is declared in __all__ at the bottom of this file.

import os
import re
import json
import math
import time
import hashlib
import shutil
import tempfile
import gzip
import http.server
import socketserver
from urllib.parse import quote as _urlquote, unquote as _urlunquote

from zyg_workflows.paths import BIND_HOST

# ── the sections, split into zyg_dashboard.kanban/ (2026-10-06) ──────────────
# Imported back by name so the handler below can go on calling them bare and
# `zyg_dashboard.kanban_server.<name>` keeps resolving for every outside caller.
from zyg_dashboard.kanban.common import _zyg_log, _FFMPEG, PORT, HERE, _CHARS_ROOT, _RUNTIME  # noqa: F401
from zyg_dashboard.kanban.common import _OUTPUT_ROOT, _DATA_OUTPUT_ROOT, _DATA_RUNTIME_ROOT  # noqa: F401
from zyg_dashboard.kanban.common import _MEDIA_ROOTS  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _CREATURE_ROOT, _CREATURE_ID_RE, _VFX_MAX_UPLOAD  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _REC_MAX_UPLOAD, _MAIN_APP, _internal_token, _MEDIA_MIME  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _MEDIA_PATH_RE, _CATS, _CAT_LABELS, _CAT_ORDER, _ID_RE  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _NAME_RE, _IMG_MIME, _LIST_CACHE, _NAME_CACHE, _MESH_ROOT  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _MESH_CACHE, _MESH_IMG_RE, _MESH_CTYPE, _mesh_list  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _PROP_ROOT, _PROP_CACHE, _prop_mesh_list, _MV_OUT_ROOT  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _MV_JOB_ID_RE, _api_movement_objects, _MV_CACHE  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _MV_CACHE_TTL, _api_movement_library, _GNM_ROOT, _GNM_CACHE  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _gnm_fits, _MESH_JOBS, _MESH_PY, _MESH_JOB_ID_RE  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _MESH_HASH_RE, _MESH_LOCK, _MESH_RUNNING, _MESH_JOBS_MEM  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _MESH_DRYRUN_OK, _mesh_names, _mesh_parse_hashes  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _MESH_VERDICT_RE, _mesh_parse_verdict, _mesh_job_run  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _mesh_job_start, _mesh_list_scoped, _safe_char_dir  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _display_name, _FACET_CACHE, _char_facets, _runtime_status  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _manifest_qc, _list_images, _MEDUSA_IDS_CACHE  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _medusa_id_set, _is_medusa_char, _api_list_all, _api_list  # noqa: F401
from zyg_dashboard.kanban.review_mesh import _api_char, _api_pictures  # noqa: F401
from zyg_dashboard.kanban.creatures_series import _MEDUSA_STILL_DIR, _medusa_still_side  # noqa: F401
from zyg_dashboard.kanban.creatures_series import _medusa_still_path, _api_medusa_pictures  # noqa: F401
from zyg_dashboard.kanban.creatures_series import _CREATURE_OUT_ROOT, _CREATURE_CATS, _CREATURE_LICENCE  # noqa: F401
from zyg_dashboard.kanban.creatures_series import _FLUX1_FAMILIES, _FLUX1_BLOCK_NOTE, _is_flux1  # noqa: F401
from zyg_dashboard.kanban.creatures_series import _creature_manifest, _HUMANISH, _val_prompt  # noqa: F401
from zyg_dashboard.kanban.creatures_series import _creature_dir, _creature_weights, _creature_job  # noqa: F401
from zyg_dashboard.kanban.creatures_series import _creature_images, _api_creatures, _api_bakeoffs  # noqa: F401
from zyg_dashboard.kanban.creatures_series import _api_series, _KS_MOD, _ks_common, _api_kids_series  # noqa: F401
from zyg_dashboard.kanban.media_scan import _VID_SKIP_TOP, _VID_SKIP_PREFIX, _VID_DL_CUT_RE  # noqa: F401
from zyg_dashboard.kanban.media_scan import _VID_TMP_SEGS, _VID_PREV_SEG_RE, _VID_TMP_FILE_RE  # noqa: F401
from zyg_dashboard.kanban.media_scan import _VID_SMOKE_JOB_RE, _VID_SMOKE_JOB_STRICT_RE  # noqa: F401
from zyg_dashboard.kanban.media_scan import _VID_SMOKE_MARKER, _vid_is_test_job, _VID_GROUPS, _VID_CACHE  # noqa: F401
from zyg_dashboard.kanban.media_scan import _VID_CACHE_TTL, _THUMB_DIR, _THUMB_SEM, _THUMB_W  # noqa: F401
from zyg_dashboard.kanban.media_scan import _thumb_path, _PREVIEW_DIR, _PREVIEW_REG, _PREVIEW_SEM  # noqa: F401
from zyg_dashboard.kanban.media_scan import _PREVIEW_W, _PREVIEW_MAX_S, _PREVIEW_CACHE  # noqa: F401
from zyg_dashboard.kanban.media_scan import _preview_registry, _featured_preview, _preview_path  # noqa: F401
from zyg_dashboard.kanban.media_scan import _make_preview, _SUBBURN_DIR, _SUBBURN_SEM, _SUBBURN_STYLE  # noqa: F401
from zyg_dashboard.kanban.media_scan import _SUBBURN_VENC, _subburn_path, _make_subburn, _make_thumb  # noqa: F401
from zyg_dashboard.kanban.media_scan import _IMG_THUMB_DIR, _IMG_THUMB_W, _img_thumb_path  # noqa: F401
from zyg_dashboard.kanban.media_scan import _make_img_thumb, _vid_group, _api_videos  # noqa: F401
from zyg_dashboard.kanban.sfx_vfx import _ALIB_MOD, _ALIB_EXT_MIME, _ALIB_CACHE, _ALIB_CACHE_TTL  # noqa: F401
from zyg_dashboard.kanban.sfx_vfx import _ALIB_DEFER_MIN, _ALIB_PROBE, _ALIB_LOCK, _ALIB_TAKE_RE  # noqa: F401
from zyg_dashboard.kanban.sfx_vfx import _ALIB_CAT_DESC, _alib, _alib_probe, _alib_ai_state, _api_sfx  # noqa: F401
from zyg_dashboard.kanban.sfx_vfx import _VFXA_MOD, _VFXA_CACHE, _VFXA_CACHE_TTL, _VFXA_LOCK  # noqa: F401
from zyg_dashboard.kanban.sfx_vfx import _VFXA_EXT_MIME, _vfxa, _api_vfx_assets, _VFXFX_MOD, _vfxfx  # noqa: F401
from zyg_dashboard.kanban.sfx_vfx import _CRFX_MOD, _crfx, _PFX_MOD, _pfx, _fx_stack_arg  # noqa: F401
from zyg_dashboard.kanban.sfx_vfx import _vfx_featured_preview, _VOLPV_JOBS, _VOLPV_LOCK, _volpv_worker  # noqa: F401
from zyg_dashboard.kanban.sfx_vfx import _volpv_start, _volpv_status, _MERGE_MOD, _sfx_merger  # noqa: F401
from zyg_dashboard.kanban.sfx_vfx import _MUSIC_MOD, _music_studio, _VOICE_MERGE_MOD, _voice_merger  # noqa: F401
from zyg_dashboard.kanban.studios import _AGENT_MOD, _agents, _VFX_MOD, _vfx, _ARCH_MOD, _arch  # noqa: F401
from zyg_dashboard.kanban.studios import _CSTUDIO_MOD, _cstudio, _VOICE_MOD, _voice_studio, _VIDEO_MOD  # noqa: F401
from zyg_dashboard.kanban.studios import _video_studio, _STILL_MOD, _video_stills, _ASSIGN_MOD  # noqa: F401
from zyg_dashboard.kanban.studios import _voice_assign  # noqa: F401
from zyg_dashboard.kanban.music import _KM_ROOTS, _KM_ROOT, _KM_ID_RE, _KM_CACHE, _KM_CACHE_TTL  # noqa: F401
from zyg_dashboard.kanban.music import _KM_FILES, _KM_FRAME_RE, _km_dir, _km_root_of, _KM_DL_LEG  # noqa: F401
from zyg_dashboard.kanban.music import _KM_FAMILIES, _KM_SHELF_OK, _KM_DEFAULT_FAMILY  # noqa: F401
from zyg_dashboard.kanban.music import _KM_FALLBACK_SHELF, _KM_FIRST_SHELF, _KM_STORY_RE  # noqa: F401
from zyg_dashboard.kanban.music import _KM_SLEEPY_MOODS, _km_derive_shelf, _km_shelf_of, _km_file_song  # noqa: F401
from zyg_dashboard.kanban.music import _km_download_name, _KS_DIR_RE, _km_series, _api_kidsmusic  # noqa: F401
from zyg_dashboard.kanban.music import _KM_SPEC_MOD, _km_theory, _km_spec, _km_forward, _pe_forward  # noqa: F401
from zyg_dashboard.kanban.http_cache import _JSON_GZ, _JSON_GZ_MAX, _JSON_GZ_MIN, _JSON_GZ_LOCK  # noqa: F401
from zyg_dashboard.kanban.http_cache import _JSON_MEMO, _STATIC_GZ, _STATIC_GZ_LOCK, _STATIC_GZ_TYPES  # noqa: F401
from zyg_dashboard.kanban.http_cache import _gz_cached  # noqa: F401

# ── the handler, split into mixins (2026-10-06) ──────────────────────────────
# One class of 3,038 lines became eight contiguous, byte-for-byte slices. They are
# listed below in their original order, so the MRO walks the methods in the order
# they were written and `zyg_dashboard.kanban_server.<name>` keeps resolving.
from zyg_dashboard.kanban_server.static_files import _StaticFilesMixin
from zyg_dashboard.kanban_server.fx_toolbox import _FxToolboxMixin
from zyg_dashboard.kanban_server.bridges import _BridgesMixin
from zyg_dashboard.kanban_server.voice_video import _VoiceVideoMixin
from zyg_dashboard.kanban_server.creature_mesh import _CreatureMeshMixin
from zyg_dashboard.kanban_server.vfx_library import _VfxLibraryMixin
from zyg_dashboard.kanban_server.studio_api import _StudioApiMixin
from zyg_dashboard.kanban_server.routes import _RoutesMixin


class _Handler(
    _StaticFilesMixin,
    _FxToolboxMixin,
    _BridgesMixin,
    _VoiceVideoMixin,
    _CreatureMeshMixin,
    _VfxLibraryMixin,
    _StudioApiMixin,
    _RoutesMixin,
    http.server.SimpleHTTPRequestHandler,
):
    """The request handler, reassembled from the eight mixins above."""


class _Server(socketserver.ThreadingTCPServer):
    # 2026-09-05: request_queue_size defaults to 5 in the stdlib. A browser
    # opens 6 connections per host and a thumbnail grid can ask for a hundred
    # tiles at once, so the accept queue overflowed, the kernel silently dropped
    # the SYN, and the tab stalled on a 1 s then 3 s TCP retransmit — the random
    # multi-second hangs, which looked like a slow server and were a full queue.
    request_queue_size = 128
    allow_reuse_address = True
    daemon_threads = True


# ── re-export surface ────────────────────────────────────────────────────────
# The names above, in import order, i.e. the order the pre-split module bound
# them. Declaring the surface is what makes the re-exports deliberate rather
# than unused imports; nothing does ``import *`` from here, so it changes no
# behaviour.
__all__ = [
    # stdlib block of the pre-split module
    'os',
    're',
    'json',
    'math',
    'time',
    'hashlib',
    'shutil',
    'tempfile',
    'gzip',
    'http',
    'socketserver',
    '_urlquote',
    '_urlunquote',
    'BIND_HOST',
    # zyg_dashboard.kanban.common
    '_zyg_log',
    '_FFMPEG',
    'PORT',
    'HERE',
    '_CHARS_ROOT',
    '_RUNTIME',
    '_OUTPUT_ROOT',
    '_DATA_OUTPUT_ROOT',
    '_DATA_RUNTIME_ROOT',
    '_MEDIA_ROOTS',
    # zyg_dashboard.kanban.review_mesh
    '_CREATURE_ROOT',
    '_CREATURE_ID_RE',
    '_VFX_MAX_UPLOAD',
    '_REC_MAX_UPLOAD',
    '_MAIN_APP',
    '_internal_token',
    '_MEDIA_MIME',
    '_MEDIA_PATH_RE',
    '_CATS',
    '_CAT_LABELS',
    '_CAT_ORDER',
    '_ID_RE',
    '_NAME_RE',
    '_IMG_MIME',
    '_LIST_CACHE',
    '_NAME_CACHE',
    '_MESH_ROOT',
    '_MESH_CACHE',
    '_MESH_IMG_RE',
    '_MESH_CTYPE',
    '_mesh_list',
    '_PROP_ROOT',
    '_PROP_CACHE',
    '_prop_mesh_list',
    '_MV_OUT_ROOT',
    '_MV_JOB_ID_RE',
    '_api_movement_objects',
    '_MV_CACHE',
    '_MV_CACHE_TTL',
    '_api_movement_library',
    '_GNM_ROOT',
    '_GNM_CACHE',
    '_gnm_fits',
    '_MESH_JOBS',
    '_MESH_PY',
    '_MESH_JOB_ID_RE',
    '_MESH_HASH_RE',
    '_MESH_LOCK',
    '_MESH_RUNNING',
    '_MESH_JOBS_MEM',
    '_MESH_DRYRUN_OK',
    '_mesh_names',
    '_mesh_parse_hashes',
    '_MESH_VERDICT_RE',
    '_mesh_parse_verdict',
    '_mesh_job_run',
    '_mesh_job_start',
    '_mesh_list_scoped',
    '_safe_char_dir',
    '_display_name',
    '_FACET_CACHE',
    '_char_facets',
    '_runtime_status',
    '_manifest_qc',
    '_list_images',
    '_MEDUSA_IDS_CACHE',
    '_medusa_id_set',
    '_is_medusa_char',
    '_api_list_all',
    '_api_list',
    '_api_char',
    '_api_pictures',
    # zyg_dashboard.kanban.creatures_series
    '_MEDUSA_STILL_DIR',
    '_medusa_still_side',
    '_medusa_still_path',
    '_api_medusa_pictures',
    '_CREATURE_OUT_ROOT',
    '_CREATURE_CATS',
    '_CREATURE_LICENCE',
    '_FLUX1_FAMILIES',
    '_FLUX1_BLOCK_NOTE',
    '_is_flux1',
    '_creature_manifest',
    '_HUMANISH',
    '_val_prompt',
    '_creature_dir',
    '_creature_weights',
    '_creature_job',
    '_creature_images',
    '_api_creatures',
    '_api_bakeoffs',
    '_api_series',
    '_KS_MOD',
    '_ks_common',
    '_api_kids_series',
    # zyg_dashboard.kanban.media_scan
    '_VID_SKIP_TOP',
    '_VID_SKIP_PREFIX',
    '_VID_DL_CUT_RE',
    '_VID_TMP_SEGS',
    '_VID_PREV_SEG_RE',
    '_VID_TMP_FILE_RE',
    '_VID_SMOKE_JOB_RE',
    '_VID_SMOKE_JOB_STRICT_RE',
    '_VID_SMOKE_MARKER',
    '_vid_is_test_job',
    '_VID_GROUPS',
    '_VID_CACHE',
    '_VID_CACHE_TTL',
    '_THUMB_DIR',
    '_THUMB_SEM',
    '_THUMB_W',
    '_thumb_path',
    '_PREVIEW_DIR',
    '_PREVIEW_REG',
    '_PREVIEW_SEM',
    '_PREVIEW_W',
    '_PREVIEW_MAX_S',
    '_PREVIEW_CACHE',
    '_preview_registry',
    '_featured_preview',
    '_preview_path',
    '_make_preview',
    '_SUBBURN_DIR',
    '_SUBBURN_SEM',
    '_SUBBURN_STYLE',
    '_SUBBURN_VENC',
    '_subburn_path',
    '_make_subburn',
    '_make_thumb',
    '_IMG_THUMB_DIR',
    '_IMG_THUMB_W',
    '_img_thumb_path',
    '_make_img_thumb',
    '_vid_group',
    '_api_videos',
    # zyg_dashboard.kanban.sfx_vfx
    '_ALIB_MOD',
    '_ALIB_EXT_MIME',
    '_ALIB_CACHE',
    '_ALIB_CACHE_TTL',
    '_ALIB_DEFER_MIN',
    '_ALIB_PROBE',
    '_ALIB_LOCK',
    '_ALIB_TAKE_RE',
    '_ALIB_CAT_DESC',
    '_alib',
    '_alib_probe',
    '_alib_ai_state',
    '_api_sfx',
    '_VFXA_MOD',
    '_VFXA_CACHE',
    '_VFXA_CACHE_TTL',
    '_VFXA_LOCK',
    '_VFXA_EXT_MIME',
    '_vfxa',
    '_api_vfx_assets',
    '_VFXFX_MOD',
    '_vfxfx',
    '_CRFX_MOD',
    '_crfx',
    '_PFX_MOD',
    '_pfx',
    '_fx_stack_arg',
    '_vfx_featured_preview',
    '_VOLPV_JOBS',
    '_VOLPV_LOCK',
    '_volpv_worker',
    '_volpv_start',
    '_volpv_status',
    '_MERGE_MOD',
    '_sfx_merger',
    '_MUSIC_MOD',
    '_music_studio',
    '_VOICE_MERGE_MOD',
    '_voice_merger',
    # zyg_dashboard.kanban.studios
    '_AGENT_MOD',
    '_agents',
    '_VFX_MOD',
    '_vfx',
    '_ARCH_MOD',
    '_arch',
    '_CSTUDIO_MOD',
    '_cstudio',
    '_VOICE_MOD',
    '_voice_studio',
    '_VIDEO_MOD',
    '_video_studio',
    '_STILL_MOD',
    '_video_stills',
    '_ASSIGN_MOD',
    '_voice_assign',
    # zyg_dashboard.kanban.music
    '_KM_ROOTS',
    '_KM_ROOT',
    '_KM_ID_RE',
    '_KM_CACHE',
    '_KM_CACHE_TTL',
    '_KM_FILES',
    '_KM_FRAME_RE',
    '_km_dir',
    '_km_root_of',
    '_KM_DL_LEG',
    '_KM_FAMILIES',
    '_KM_SHELF_OK',
    '_KM_DEFAULT_FAMILY',
    '_KM_FALLBACK_SHELF',
    '_KM_FIRST_SHELF',
    '_KM_STORY_RE',
    '_KM_SLEEPY_MOODS',
    '_km_derive_shelf',
    '_km_shelf_of',
    '_km_file_song',
    '_km_download_name',
    '_KS_DIR_RE',
    '_km_series',
    '_api_kidsmusic',
    '_KM_SPEC_MOD',
    '_km_theory',
    '_km_spec',
    '_km_forward',
    '_pe_forward',
    # zyg_dashboard.kanban.http_cache
    '_JSON_GZ',
    '_JSON_GZ_MAX',
    '_JSON_GZ_MIN',
    '_JSON_GZ_LOCK',
    '_JSON_MEMO',
    '_STATIC_GZ',
    '_STATIC_GZ_LOCK',
    '_STATIC_GZ_TYPES',
    '_gz_cached',
    # the handler mixins, in MRO order
    '_StaticFilesMixin',
    '_FxToolboxMixin',
    '_BridgesMixin',
    '_VoiceVideoMixin',
    '_CreatureMeshMixin',
    '_VfxLibraryMixin',
    '_StudioApiMixin',
    '_RoutesMixin',
    # defined here
    '_Handler',
    '_Server',
]
