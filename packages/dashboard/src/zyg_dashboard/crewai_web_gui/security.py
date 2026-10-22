#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Request-time auth, and the canonical-data readers.

Lines 357-818 of the original module, verbatim: the 429 handler, the CSRF check,
``_is_loopback`` with the complete list of loopback-only session-auth bypasses,
the ``require_login`` before_request hook, the canonical-data paths, the dashboard
error-log push and the CPU/GPU model-list readers.
"""

# Verbatim move: the original import order is load-bearing, and every name here is read
# back off zyg_dashboard.crewai_web_gui by the bp_* blueprints.  The late imports that
# stayed at their old definition sites carry their own per-line E402 suppressions.

from zyg_dashboard import paths as _dash_paths
from zyg_dashboard.crewai_web_gui._bootstrap import (
    SESSION_VALIDITY_TOKEN,
    _ZERO_PUBLIC_TOKEN,
    _ams_iso,
    _login_debug,
    _page_load_debug,
    _runtime_path,
    _zyg_log,
    app,
    apply_cors,
    gui_state,
    json,
    jsonify,
    os,
    redirect,
    request,
    secrets,
    session,
    threading,
    url_for,
)


@app.errorhandler(429)
def ratelimit_handler(e):
    """Return JSON on rate limit exceed (for API routes)."""
    resp = jsonify(
        {
            'success': False,
            'error': 'rate_limit_exceeded',
            'message': 'Too many requests. Please wait before trying again.',
        }
    )
    # 2026-09-23: the kanban boards are served cross-origin from :8899 and their
    # status endpoints answer with Access-Control-Allow-Origin. A 429 did NOT,
    # so the browser dropped the response before the page could read it and a
    # rate-limited board was indistinguishable from an unreachable server — which
    # is how /api/medusa/kanban_status spent a day being 429'd unnoticed. Same
    # header, same read-only paths, so the failure is legible next time.
    # 2026-10-05: the header is now the ZYG_CORS_ORIGINS allowlist (cors.py), so
    # the board's origin must be listed for the 429 to stay readable — exactly as
    # for the status endpoints it mirrors.
    if request.path.startswith('/api/medusa/') or request.path.startswith('/api/kanban/'):
        apply_cors(resp, request)
    return resp, 429


# 2026-10-06 round-2 split: the LOGIN_DEBUG / PAGE_LOAD_DEBUG / BACKEND_DEBUG toggles,
# SESSION_VALIDITY_TOKEN, the three _*_debug printers and the
# runtime.register(backend_debug=...) call moved to zyg_dashboard.gui.telemetry


# CSRF: state-changing API routes require X-CSRF-Token header when using cookie sessions
# 2026-10-06 layering: _ensure_csrf_token moved to zyg_dashboard.appcore
from zyg_dashboard.appcore import _ensure_csrf_token  # noqa: E402  kept at the old definition site


def _require_csrf():
    """Return error response if CSRF check fails; None if OK."""
    if request.method not in ('POST', 'PUT', 'DELETE', 'PATCH'):
        return None
    path = request.path
    if not path.startswith('/api/'):
        return None
    if path == '/api/login':
        return None
    token = (
        request.headers.get('X-CSRF-Token') or request.headers.get('X-XSRF-Token') or request.headers.get('X-CSRFToken')
    )
    expected = session.get('_csrf_token')
    if not expected:
        _ensure_csrf_token()
        expected = session.get('_csrf_token')
    if not token or not secrets.compare_digest(token, expected):
        return jsonify(
            {'success': False, 'error': 'Invalid or missing CSRF token', 'message': 'Refresh the page and try again.'}
        ), 403
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Loopback-only session-auth bypasses — the complete list, in one place
#
# Services on this same box call the dashboard's API without a browser session:
# the kanban server on :8899 (which the children's and movement panels post
# through), Medusa on :5300, and operator shell scripts. They reach :5000 over
# 127.0.0.1, so these path prefixes answer them without a session and give a
# 401 / login redirect to everyone else. Every blueprint behind them re-checks
# the client address itself on its state-changing routes, so this list alone
# cannot widen anything.
#
# Bypassed only for a loopback client (see require_login below):
#   /api/medusa/                     Medusa :5300 -> generate / pending / decide
#   /api/jackmona/                   Life of Jack / Life of Mona, driven from this box
#   /api/storyteller/training/       scripts/qwen_cast_retrain.py per-character LoRA
#   /api/approval_queue/             Approval Queue board + smoke checks
#   /api/preempt/                    Pre-Emptive bank, same callers
#   /api/internal/kidsmusic/         Children's Music composer panel (:8899 hop)
#   /api/internal/kidseries/         the ten children's series menus (:8899 hop)
#   /api/internal/movement/          Movement Studio panel (:8899 hop)
#   /api/internal/char2d/            2D Character Basics I Run button (:8899 hop)
#   /api/internal/picture_studio/    Picture Studio tools, proxied by Medusa
#
# Dates, for the record: medusa 2026-07-26, storyteller 2026-08-09,
# kidsmusic 2026-08-29, movement 2026-08-31, kidseries 2026-09-06,
# char2d 2026-09-16, picture_studio 2026-09-17, approval_queue/preempt
# 2026-09-20, jackmona 2026-10-02. Collapsed into one helper 2026-10-05.
# ─────────────────────────────────────────────────────────────────────────────
_LOOPBACK_ADDRS = ('127.0.0.1', '::1')

_LOOPBACK_ONLY_PREFIXES = (
    '/api/medusa/',
    '/api/jackmona/',
    '/api/storyteller/training/',
    '/api/approval_queue/',
    '/api/preempt/',
    '/api/internal/kidsmusic/',
    '/api/internal/kidseries/',
    '/api/internal/movement/',
    '/api/internal/char2d/',
    '/api/internal/picture_studio/',
)


def _is_loopback(req) -> bool:
    """True when the request came from this machine over the loopback interface."""
    return req.remote_addr in _LOOPBACK_ADDRS


@app.before_request
def require_login():
    """Redirect unauthenticated dashboard/schedule access to login; allow only /login and /api/login publicly."""
    path = request.path
    user_role = session.get('user_role')
    session_keys = list(session.keys()) if hasattr(session, 'keys') else []
    _login_debug(f'before_request path={path!r} session_keys={session_keys} user_role={user_role!r}')
    _page_load_debug(f'request path={path!r} role={user_role!r}')
    if path == '/login' or path == '/api/login':
        _login_debug('  -> allow (login path)')
        return None
    if path == '/logout' or path == '/api/logout':
        _page_load_debug('  -> allow (logout)')
        return None
    # Static files (CSS, JS, images) are always public — never require authentication
    if path.startswith('/static/'):
        return None
    # 2026-08-25: browsers probe /favicon.ico and /apple-touch-icon.png at the root by default;
    # pages without a <link rel="icon"> would otherwise show the login redirect as their icon.
    if path in ('/favicon.ico', '/apple-touch-icon.png', '/apple-touch-icon-precomposed.png'):
        return None
    # Hardware telemetry is non-sensitive — always public so dashboard gauges keep
    # updating even after a server restart invalidates the browser session.
    if path == '/api/telemetry':
        return None
    if path == '/api/vram/free':
        return None
    if path == '/api/health':
        return None
    # Kanban board status + workflow step detail — public so the iframe on port 8899 can poll without session auth
    if path in (
        '/api/kanban/status',
        '/api/kanban/clear_errors',
        '/api/workflow_status/active',
        '/api/workflow/steps/agents',
        '/api/sports-video/status',
        '/api/output/new-videos',
        '/api/marketing/upload',
        '/api/youtube/channel-videos',
        '/api/marketing/dismiss',
        '/api/marketing/undismiss',
        '/api/marketing/dismissed',
    ):
        return None
    # Creator Nexus autosave (2026-08-03) — the app is a static frontend on :8090
    # with no session, so its durable-copy endpoints must be reachable without auth.
    if path.startswith('/api/creator-nexus/'):
        return None
    # Internal calls from zero_public_server — bypass session auth for /api/internal/ and token check/use paths
    if (
        _ZERO_PUBLIC_TOKEN
        and request.headers.get('X-Zero-Public-Token') == _ZERO_PUBLIC_TOKEN
        and (
            path.startswith('/api/internal/')
            or path.startswith('/api/zero_public/token_check/')
            or path.startswith('/api/zero_public/token_use/')
            or path in ('/api/zero/stop', '/api/zero/stop/reset')
        )
    ):
        return None
    # The Medusa board status is read-only and polled by the :8899 kanban iframe,
    # so it is public like /api/kanban/status — no loopback condition.
    if path == '/api/medusa/kanban_status':
        return None
    # The ten loopback-only bypasses, listed and explained at _LOOPBACK_ONLY_PREFIXES
    # above. Additive; inert for every other path and for every non-local client.
    if _is_loopback(request) and path.startswith(_LOOPBACK_ONLY_PREFIXES):
        return None
    # Require login for any non-public path
    if not user_role and path not in ('/login', '/api/login', '/logout', '/api/logout'):
        # API paths must return JSON 401, not a redirect (redirects break programmatic callers)
        if path.startswith('/api/'):
            _login_debug('  -> 401 Login required (api, no role)')
            return jsonify({'success': False, 'message': 'Login required'}), 401
        _login_debug(f'  -> redirect to login (no role, path={path!r})')
        return redirect(url_for('login_page'))
    # CSRF check for state-changing API requests (cookie-based session)
    csrf_err = _require_csrf()
    if csrf_err is not None:
        return csrf_err
    # Any session from a previous server run is invalid (token changes on each start): force login again
    _dashboard_paths = (
        '/',
        '/gpu_schedule.html',
        '/cpu_schedule.html',
        '/error_logs',
        '/job_status',
        '/monitoring_ui',
        '/parameter_control',
        '/settings',
        '/approval_queue',
        '/audit',
        '/integrity_gate',
        '/job_lifecycle',
        '/metrics',
        '/mechanics',
    )
    if path in _dashboard_paths and user_role:
        if session.get('_validity') != SESSION_VALIDITY_TOKEN:
            session.clear()
            _login_debug('  -> session invalid (server restarted), clear and redirect to login')
            _page_load_debug('  -> redirect to login (stale session)')
            return redirect(url_for('login_page'))
    if path in _dashboard_paths and not user_role:
        _login_debug('  -> redirect to login_page (no role)')
        _page_load_debug('  -> redirect to login (no role)')
        return redirect(url_for('login_page'))
    # API: reject stale sessions (server was restarted)
    if path.startswith('/api/') and user_role and session.get('_validity') != SESSION_VALIDITY_TOKEN:
        session.clear()
        return jsonify({'success': False, 'message': 'Session expired (server restarted). Please log in again.'}), 401
    if path.startswith('/api/') and not user_role:
        _login_debug('  -> 401 Login required')
        _page_load_debug('  -> 401 (no role)')
        return jsonify({'success': False, 'message': 'Login required'}), 401
    _login_debug('  -> allow (has role)')
    _page_load_debug(f'  -> allow role={user_role!r}')
    return None


# 2026-10-06 round-2 split: block_spectator_mutation moved to zyg_dashboard.gui.zero_store;
# the crewai.LLM / Ollama probe (CrewAILLM, Ollama, OLLAMA_AVAILABLE, _OLLAMA_BASE_URL) moved
# to zyg_dashboard.gui.controller, beside the only code that reads it.

# --- Canonical data (single truth per entity, see docs/canonical-data-ownership.md) ---
# 2026-10-06 layering: DATA_DIR moved to zyg_dashboard.appcore (same directory)
from zyg_dashboard.appcore import DATA_DIR  # noqa: E402  kept at the old definition site

REPO_ROOT = str(_dash_paths.PKG_DIR.parent.parent)  # packages/dashboard
DOCS_DIR = os.path.join(REPO_ROOT, 'docs')

# 2026-10-05 layering: _RUNTIME_DIR moved to zyg_workflows.pipeline_config
# 2026-10-06 round-2 split: the os.makedirs(_RUNTIME_DIR) that stood here moved to
# zyg_dashboard.gui.runtime_state, so the directory exists before any importer reads it


# 2026-10-05 layering: _runtime_path moved to zyg_workflows.runtime


# 2026-10-05 layering: _FLUX_PERF_TELEMETRY_PATH moved to zyg_workflows.pipeline_config

# ── Benchmark replay cache ────────────────────────────────────────────────────
# When ZYG_BENCH_REPLAY=1, the scholarly pipeline uses pre-recorded Claude
# outputs instead of making live API calls.  Build the cache once with:
#   python scripts/build_bench_replay_cache.py
_BENCH_REPLAY_CACHE_PATH = _runtime_path('bench_replay_cache.json')
gui_state._bench_replay_cache: dict = {}  # loaded lazily on first use


# 2026-07-17 heavy-tranche: _bench_replay_load moved to bp_benchmark.py


# 2026-07-17 heavy-tranche: _bench_replay_get moved to bp_benchmark.py
_BENCHMARK_PATH = _runtime_path('benchmark_telemetry.json')

_benchmark_lock = threading.Lock()
# 2026-07-17 heavy-tranche: _bm_infra_runs moved to bp_benchmark.py
_bm_infra_lock = threading.Lock()
# 2026-07-17 heavy-tranche: _bm_mr_sessions moved to bp_benchmark.py
_bm_mr_lock = threading.Lock()


# 2026-07-17 heavy-tranche: _bm_record moved to bp_benchmark.py


# 2026-07-17 heavy-tranche: _bm_record_pipeline moved to bp_benchmark.py


# 2026-07-17 heavy-tranche: _cleanup_pipeline_output moved to pipeline_common.py


# ── Dashboard error-log helper ─────────────────────────────────────────────
# Called from every pipeline's inner _log() closure so ERROR/WARNING events
# reach the dashboard Error Logs tab in real-time.
_error_log_lock = threading.Lock()


def _push_error_log(level: str, stage: str, msg: str, pipeline_id: str = '') -> None:
    """Append an entry to dashboard_error_logs.json for ERROR and WARNING events."""
    if level not in ('ERROR', 'WARNING'):
        return
    try:
        from zyg_dashboard.dashboard_config import ERROR_LOGS_DATA_PATH as _ELP

        _msg_lower = str(msg).lower()
        _LOW_RISK_KEYWORDS = (
            'skip',
            'skipping',
            'fallback',
            'optional',
            'non-fatal',
            'not found',
            'unavailable',
            'missing',
            'cache miss',
            'continuing without',
            'gracefully',
            'ignored',
            'warn',
        )
        if 'cuda' in _msg_lower or 'out of memory' in _msg_lower or 'oom' in _msg_lower or 'vram' in _msg_lower:
            _cat = 'gpu_memory_overflows'
        elif 'timeout' in _msg_lower or 'timed out' in _msg_lower:
            _cat = 'timeouts'
        elif (
            'load failed' in _msg_lower
            or 'model' in _msg_lower
            or 'flux' in _msg_lower
            or 'wan' in _msg_lower
            or 'controlnet' in _msg_lower
        ):
            _cat = 'ai_model_fails'
        elif 'api' in _msg_lower or 'endpoint' in _msg_lower or 'request' in _msg_lower:
            _cat = 'api_errors'
        elif level == 'ERROR':
            _cat = 'high_risk_errors'
        elif level == 'WARNING' and any(k in _msg_lower for k in _LOW_RISK_KEYWORDS):
            _cat = 'low_risk_errors'
        else:
            _cat = 'medium_risk_errors'
        _entry = {
            'ts': _ams_iso(timespec='seconds'),
            'level': level,
            'stage': stage,
            'msg': str(msg)[:400],
            'pipeline_id': pipeline_id or '',
        }
        _default = {
            k: []
            for k in (
                'ai_model_fails',
                'gpu_memory_overflows',
                'timeouts',
                'api_errors',
                'high_risk_errors',
                'medium_risk_errors',
                'low_risk_errors',
            )
        }
        with _error_log_lock:
            _data = _default.copy()
            if os.path.exists(_ELP):
                try:
                    with open(_ELP, 'r', encoding='utf-8') as _f:
                        _loaded = json.load(_f)
                    for _k in _default:
                        if isinstance(_loaded.get(_k), list):
                            _data[_k] = _loaded[_k]
                except Exception as _exc:
                    _zyg_log.warning('%s unreadable, it is rewritten from this entry on: %s', _ELP, _exc)
            _data[_cat].append(_entry)
            if len(_data[_cat]) > 200:
                _data[_cat] = _data[_cat][-200:]
            try:
                with open(_ELP, 'w', encoding='utf-8') as _f:
                    json.dump(_data, _f, indent=2)
            except Exception as _exc:
                _zyg_log.warning('%s not written, this error log entry is lost: %s', _ELP, _exc)
    except Exception as _exc:
        _zyg_log.warning('error log entry dropped: %s', _exc)


# 2026-07-17 heavy-tranche: _load_flux_seconds_per_image_estimate moved to pipeline_common.py


# 2026-07-17 heavy-tranche: _update_flux_seconds_per_image_estimate moved to pipeline_common.py


# 2026-10-05 layering: _VOICE_LIBRARY_PATH moved to zyg_workflows.pipeline_config
# 2026-10-05 layering: _CHANNEL_VOICES_PATH moved to zyg_workflows.pipeline_config
# 2026-10-05 layering: _INTROS_GENERAL_PATH moved to zyg_workflows.pipeline_config
# 2026-10-05 layering: _INTROS_FEMALE_PATH moved to zyg_workflows.pipeline_config
# 2026-10-05 layering: _VOICE_LOCK moved to zyg_workflows.runtime

# vid_id → channel_id mapping populated at pipeline start (Stage 4b)
# 2026-07-17 heavy-tranche: _vid_to_channel_id moved to narrator_voice_service.py

# Fixed outro CTA line spoken at the end of every clip
from zyg_workflows.pipeline_config import _NARRATOR_OUTRO  # noqa: E402,F401  kept at the old definition site

# 2026-10-05 layering: _INTRO_CATEGORY_KEYWORDS moved to zyg_workflows.pipeline_config
# 2026-10-05 layering: _INTRO_FEMALE_KEYWORDS moved to zyg_workflows.pipeline_config

# 2026-07-17 heavy-tranche: _pick_narrator_intro moved to narrator_voice_service.py


# 2026-07-17 heavy-tranche: _get_narrator_voice moved to narrator_voice_service.py


# 2026-07-17 heavy-tranche: _auto_assign_voice moved to narrator_voice_service.py


# ── TTS ──────────────────────────────────────────────────────────────────────
# 2026-08-06: the whole engine layer lives in tts_service.py — IndexTTS-2
# (primary) and Chatterbox (fallback), both cloners driven over subprocess
# workers in their own venvs. The Azure-Speech and Kokoro legs were removed;
# nothing here defines TTS engine state any more.


# ══════════════════════════════════════════════════════════════════════════════
# DEMONETIZATION PREVENTION — word lists, helpers
# ══════════════════════════════════════════════════════════════════════════════

# 2026-10-05 layering: _DEMONET_TIER1 moved to zyg_workflows.pipeline_config

# Tier 2: bleep in audio + mask in subtitles, but NOT removed from titles
from zyg_workflows.pipeline_config import _DEMONET_TIER2  # noqa: E402,F401  kept at the old definition site

# 2026-10-05 layering: _DEMONET_TIER3_TITLE moved to zyg_workflows.pipeline_config

# Synonym replacement table for titles (Tier 1 + Tier 3 hits in titles)
from zyg_workflows.pipeline_config import _TITLE_SYNONYMS  # noqa: E402,F401  kept at the old definition site

# Sensitive topic keywords — trigger REVIEW REQUIRED warning in logs only
from zyg_workflows.pipeline_config import _SENSITIVE_TOPIC_KEYWORDS  # noqa: E402,F401  kept at the old definition site


# 2026-07-17 heavy-tranche: _mask_bad_words moved to tts_service.py


# 2026-07-17 heavy-tranche: _sanitize_title moved to tts_service.py


# 2026-07-17 heavy-tranche: _bleep_audio_in_clip moved to tts_service.py


LEGACY_JSON_ARCHIVE = str(_dash_paths.PKG_DIR / 'legacy_json_archive')


def _load_canonical_json(name_in_data: str, fallback_path: str, subkey: str = None):
    """Load JSON from data/ if exists, else fallback, else legacy_json_archive. subkey: optional key to return."""
    data_path = os.path.join(DATA_DIR, name_in_data)
    fallback_full = os.path.join(str(_dash_paths.PKG_DIR), fallback_path)
    archive_full = os.path.join(LEGACY_JSON_ARCHIVE, fallback_path)
    for path in (data_path, fallback_full, archive_full):
        if os.path.isfile(path):
            with open(path, 'r', encoding='utf-8') as f:
                out = json.load(f)
            if subkey:
                return out.get(subkey, out)
            return out
    return {} if subkey else {}


def _get_gpu_models():
    """GPU model dict from data/models.json or gpu_ai_models.json."""
    m = _load_canonical_json('models.json', 'gpu_ai_models.json')
    return m.get('gpu', m) if isinstance(m, dict) and 'gpu' in m else (m or {})


def _get_cpu_models():
    """CPU model dict from data/models.json or cpu_ai_models.json."""
    m = _load_canonical_json('models.json', 'cpu_ai_models.json')
    return m.get('cpu', m) if isinstance(m, dict) and 'cpu' in m else (m or {})
