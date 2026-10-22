# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Public Flask blueprint for the zero-public site (split of zpub_routes_public.py)."""

# Pattern A split of zpub_routes_public.py: every section below was moved VERBATIM into its own
# module. The submodules are imported in the ORIGINAL SECTION ORDER so that
# module-level side effects run exactly as they did in the single file.

from zyg_zero.zpub_routes_public.core import (
    hmac,
    json,
    os,
    re,
    shutil,
    tempfile,
    time,
    uuid,
    datetime,
    Blueprint,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    stream_with_context,
    paths,
    _seal,
    settings,
    zpub_portfolio_deck,
    ALLOWED_IMAGE_EXTS,
    ALLOWED_VIDEO_EXTS,
    AVG_PIPELINE_SECONDS,
    CHUNK_UPLOAD_ROOT,
    INTERNAL_TOKEN,
    MAX_UPLOAD_BYTES,
    MAX_VIDEO_BYTES,
    PREVIEW_CHUNK_BYTES,
    RATE_LIMIT_PER_HOUR,
    UPLOAD_ROOT,
    _ams_iso,
    public_url,
    _gate_response,
    _require_api_session,
    _session_id,
    _session_invite,
    limiter,
    _get_pipeline_status,
    _parse_creature_options,
    _parse_model_family,
    _parse_pipeline_options,
    _token_check,
    _token_use,
    _check_rate_limit,
    _enqueue,
    _get_running,
    _jobs_for_library,
    _link_session_job,
    _link_token_job,
    _load_job,
    _pending_store,
    _queue_length,
    _queue_position,
    _save_job,
    _session_jobs,
    _set_running,
    _zpub_log,
    bp,
    _inject_licence_state,
    admin_enter,
    invite_page,
    _PORTFOLIO_TOKEN,
    portfolio_invite_page,
)

from zyg_zero.zpub_routes_public.portfolio import (
    _PORTFOLIO_VIDEO_PATH,
    _request_is_same_origin,
    _PORTFOLIO_SPEEDRUN_PATH,
    _stream_portfolio_file,
    portfolio_stream,
    portfolio_speedrun_stream,
    _ATLAS_PATH,
    _ATLAS_DOWNLOAD_NAME,
    _ARCH_PATH,
    _ARCH_DOWNLOAD_NAME,
    _atlas_response,
    atlas_view,
    atlas_download,
    architecture_view,
    architecture_download,
    _PORTFOLIO_SLIDES_DIR,
    _SLIDE_NAME_RE,
    _SLIDE_CACHE,
    _SLIDE_CACHE_TTL,
    _portfolio_slides,
    _inject_portfolio_deck,
    portfolio_slideshow,
    portfolio_deck_json,
    portfolio_slide,
    portfolio_slide_cover,
)

from zyg_zero.zpub_routes_public.jobs import (
    index,
    job_page,
    uploads,
    _preview_chunk_dir,
    _cleanup_preview_chunks,
    _finalize_preview_upload,
    api_preview_upload,
    api_submit,
)

from zyg_zero.zpub_routes_public.status import (
    _reconcile_zpub_job_with_pipeline,
    api_status,
    api_stream,
    download_file,
    api_queue,
    api_token_jobs,
    _C2PA_ROOT_CERT_DEFAULT,
    _C2PA_ROOT_CERT_NAME,
    _PEM_CERT_HEADER,
    _PEM_MAX_BYTES,
    _VERIFY_MAX_BYTES,
    _VERIFY_CHUNK_BYTES,
    _c2pa_root_cert_path,
    c2pa_root_cert,
    _EMPTY_REPORT,
    _verify_view,
    _verify_report,
    verify_page,
    verify_file,
)


# ── re-export surface ────────────────────────────────────────────────────────
# Every name the single zpub_routes_public.py defined, so attribute access on this module
# keeps resolving after the split. Declaring them is what makes the re-export
# deliberate rather than an unused import; nothing does ``import *`` from here,
# so __all__ changes no behaviour.
__all__ = [
    'hmac',
    'json',
    'os',
    're',
    'shutil',
    'tempfile',
    'time',
    'uuid',
    'datetime',
    'Blueprint',
    'Response',
    'jsonify',
    'redirect',
    'render_template',
    'request',
    'send_from_directory',
    'session',
    'stream_with_context',
    'paths',
    '_seal',
    'settings',
    'zpub_portfolio_deck',
    'ALLOWED_IMAGE_EXTS',
    'ALLOWED_VIDEO_EXTS',
    'AVG_PIPELINE_SECONDS',
    'CHUNK_UPLOAD_ROOT',
    'INTERNAL_TOKEN',
    'MAX_UPLOAD_BYTES',
    'MAX_VIDEO_BYTES',
    'PREVIEW_CHUNK_BYTES',
    'RATE_LIMIT_PER_HOUR',
    'UPLOAD_ROOT',
    '_ams_iso',
    'public_url',
    '_gate_response',
    '_require_api_session',
    '_session_id',
    '_session_invite',
    'limiter',
    '_get_pipeline_status',
    '_parse_creature_options',
    '_parse_model_family',
    '_parse_pipeline_options',
    '_token_check',
    '_token_use',
    '_check_rate_limit',
    '_enqueue',
    '_get_running',
    '_jobs_for_library',
    '_link_session_job',
    '_link_token_job',
    '_load_job',
    '_pending_store',
    '_queue_length',
    '_queue_position',
    '_save_job',
    '_session_jobs',
    '_set_running',
    '_zpub_log',
    'bp',
    '_inject_licence_state',
    'admin_enter',
    'invite_page',
    '_PORTFOLIO_TOKEN',
    'portfolio_invite_page',
    '_PORTFOLIO_VIDEO_PATH',
    '_request_is_same_origin',
    '_PORTFOLIO_SPEEDRUN_PATH',
    '_stream_portfolio_file',
    'portfolio_stream',
    'portfolio_speedrun_stream',
    '_ATLAS_PATH',
    '_ATLAS_DOWNLOAD_NAME',
    '_ARCH_PATH',
    '_ARCH_DOWNLOAD_NAME',
    '_atlas_response',
    'atlas_view',
    'atlas_download',
    'architecture_view',
    'architecture_download',
    '_PORTFOLIO_SLIDES_DIR',
    '_SLIDE_NAME_RE',
    '_SLIDE_CACHE',
    '_SLIDE_CACHE_TTL',
    '_portfolio_slides',
    '_inject_portfolio_deck',
    'portfolio_slideshow',
    'portfolio_deck_json',
    'portfolio_slide',
    'portfolio_slide_cover',
    'index',
    'job_page',
    'uploads',
    '_preview_chunk_dir',
    '_cleanup_preview_chunks',
    '_finalize_preview_upload',
    'api_preview_upload',
    'api_submit',
    '_reconcile_zpub_job_with_pipeline',
    'api_status',
    'api_stream',
    'download_file',
    'api_queue',
    'api_token_jobs',
    '_C2PA_ROOT_CERT_DEFAULT',
    '_C2PA_ROOT_CERT_NAME',
    '_PEM_CERT_HEADER',
    '_PEM_MAX_BYTES',
    '_VERIFY_MAX_BYTES',
    '_VERIFY_CHUNK_BYTES',
    '_c2pa_root_cert_path',
    'c2pa_root_cert',
    '_EMPTY_REPORT',
    '_verify_view',
    '_verify_report',
    'verify_page',
    'verify_file',
]


# ---------------------------------------------------------------------------
# The single file used to be one namespace, so a test (or production code) that
# did ``monkeypatch.setattr(zpub_routes_public, '_load_job', ...)`` rebound the
# very global the route bodies read. Now those bodies live in section modules
# and read THEIR OWN globals, so a patch on the package alone would silently do
# nothing. Forward every attribute write/delete into each section module that
# actually holds the name, so the old one-namespace behaviour is preserved.
import sys as _sys
import types as _types

_SECTIONS = (
    'core',
    'portfolio',
    'jobs',
    'status',
)


class _ReexportModule(_types.ModuleType):
    def __setattr__(self, name, value):
        _types.ModuleType.__setattr__(self, name, value)
        for _sec in self.__dict__.get('_SECTIONS') or ():
            _mod = _sys.modules.get(f'{self.__name__}.{_sec}')
            if _mod is not None and name in _mod.__dict__:
                setattr(_mod, name, value)

    def __delattr__(self, name):
        for _sec in self.__dict__.get('_SECTIONS') or ():
            _mod = _sys.modules.get(f'{self.__name__}.{_sec}')
            if _mod is not None and name in _mod.__dict__:
                delattr(_mod, name)
        _types.ModuleType.__delattr__(self, name)


_sys.modules[__name__].__class__ = _ReexportModule
