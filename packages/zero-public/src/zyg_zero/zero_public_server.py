#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Zero Public Server  —  port 5001
=================================
A public-facing interface that lets anyone submit a prompt to Agent Zero
and receive generated content (videos, narrations, images).

Architecture
------------
- Standalone Flask app — completely separate from the main dashboard.
- Redis-backed persistent job queue. Jobs survive browser close/refresh.
- Per-session UUID job IDs so two visitors never see each other's work.
- Single worker thread — one pipeline runs at a time (GPU constraint).
- SSE stream for live progress updates without polling overhead.
- Download route serves completed output files directly.

Queue mechanics
---------------
  zpub:queue              — Redis list (RPUSH to add, BLPOP to consume)
  zpub:running            — Redis string: current running job_id
  zpub:job:<job_id>       — Redis string: JSON-encoded job dict
  zpub:sess:<session_id>  — Redis list: job_ids belonging to this session
  zpub:rate:<ip>          — Redis sorted set: submission timestamps for rate-limit

Job lifecycle:  queued → running → done | failed
"""

# 2026-07-17 modularization: split into zpub_config/store/main_api/worker/gate + 4 route blueprints.
# Originals + changelog: crews_modularization_backups_20260717/
import json
import logging as _zyg_logging
import os
import shutil
import threading
import time

from flask import (
    Flask,
    jsonify,
    request,
    send_from_directory,
)
from werkzeug.exceptions import RequestEntityTooLarge

_zyg_log = _zyg_logging.getLogger(__name__)

# Load .env early so ZERO_PUBLIC_TOKEN and other secrets are available before
# any module-level os.environ.get() calls below.
_dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')
try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(_dotenv_path, override=False)
except ImportError as _exc:
    _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)

# noqa: E402 below — every zyg_zero module reads os.environ at import time (settings.py,
# zpub_config.py), so the .env load above MUST happen before these imports.
from zyg_zero import settings, zpub_store  # noqa: E402  must follow the .env load above
from zyg_zero.zpub_config import (  # noqa: E402  must follow the .env load above
    MAX_VIDEO_BYTES,
    PORT,
    SECRET_KEY,
    _ams_iso,
)
from zyg_zero.zpub_gate import _gate_response, limiter  # noqa: E402  must follow the .env load above
from zyg_zero.zpub_routes_admin import bp as _bp_admin  # noqa: E402  must follow the .env load above
from zyg_zero.zpub_routes_cinema import bp as _bp_cinema  # noqa: E402  must follow the .env load above
from zyg_zero.zpub_routes_public import (  # noqa: E402  must follow the .env load above
    _reconcile_zpub_job_with_pipeline,
    bp as _bp_public,
)
from zyg_zero.zpub_routes_sports import bp as _bp_sports  # noqa: E402  must follow the .env load above
from zyg_zero.zpub_routes_storyteller import bp as _bp_story  # noqa: E402  must follow the .env load above
from zyg_zero.zpub_store import (  # noqa: E402  must follow the .env load above
    _JOB_PERSIST_DIR,
    _LOG_DIR,
    _RUNNING_KEY,
    _get_redis,
    _mem_lock,
    _save_job,
)
from zyg_zero.zpub_worker import _worker_loop  # noqa: E402  must follow the .env load above


app = Flask(__name__, template_folder='templates')
app.secret_key = SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = __import__('datetime').timedelta(days=30)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['MAX_CONTENT_LENGTH'] = MAX_VIDEO_BYTES + (1024 * 1024)

# 2026-07-31: make request.remote_addr reflect the real client.
# cloudflared terminates the public tunnel and forwards to this app over
# loopback, so WITHOUT ProxyFix every public request looked like 127.0.0.1.
# That (a) poisoned the user log — 18,734 of ~18,900 entries in
# data/runtime/zpub_user_log.jsonl read ip=127.0.0.1 against ~100 from real LAN
# addresses, (b) collapsed every flask-limiter per-IP bucket into one shared
# global bucket, so a single visitor could burn the whole rate budget, and
# (c) until today's fix in zpub_routes_admin.py, let public traffic satisfy a
# "localhost only" auth shortcut on /api/admin/run_approved.
#
# ProxyFix TRUSTS X-Forwarded-For — it does not verify the peer. That is only
# acceptable here because the cloudflared tunnel started by
# _start_public_tunnel() below is the SOLE PUBLIC INGRESS and always rewrites
# XFF with the real client IP; x_for=1 therefore reads the rightmost (proxy-
# appended) entry, which a client cannot forge through the tunnel.
# If the ingress topology changes — a second reverse proxy, an extra hop in
# front of cloudflared, or a direct public bind — this MUST be re-evaluated and
# x_for raised to the real hop count, or the header will become spoofable.
# Caveat (accepted): a deployment that sets ZYG_BIND_HOST to a LAN address for
# LAN access lets a host that reaches :5001 directly spoof X-Forwarded-For. That
# only affects logging and rate-limit bucketing — as of 2026-07-31 no route in
# this app authorises on IP any more, which is what makes the trade-off safe.
# Rollback: ZYG_ZPUB_PROXY_FIX=0
if (os.environ.get('ZYG_ZPUB_PROXY_FIX', '1') or '').strip().lower() not in ('', '0', 'false', 'no', 'off'):
    try:
        from werkzeug.middleware.proxy_fix import ProxyFix as _ProxyFix

        app.wsgi_app = _ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
        _zyg_log.info('[ZeroPub] ProxyFix enabled (x_for=1, x_proto=1) — remote_addr = real client IP')
    except Exception as _pf_exc:
        _zyg_log.info(f'[ZeroPub] ProxyFix unavailable ({_pf_exc}) — remote_addr stays the tunnel loopback address')

limiter.init_app(app)

app.register_blueprint(_bp_public)
app.register_blueprint(_bp_admin)
app.register_blueprint(_bp_story)
app.register_blueprint(_bp_sports)
app.register_blueprint(_bp_cinema)

_ZPUB_ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates', 'assets')


@app.route('/assets/zero/<path:filename>')
def zero_public_assets(filename):
    """Static assets for Zero Public UI (honeycomb textures, etc.)."""
    return send_from_directory(_ZPUB_ASSETS_DIR, filename)


@app.after_request
def _no_cache_html(response):
    """Prevent browsers from caching HTML pages — ensures JS/CSS changes are always picked up."""
    if 'text/html' in response.content_type:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


@app.errorhandler(RequestEntityTooLarge)
def _handle_request_too_large(_exc):
    if request.path.startswith('/api/'):
        mb = MAX_VIDEO_BYTES // (1024 * 1024)
        return jsonify(
            {
                'success': False,
                'error': f'File too large (max {mb} MB for preview video)',
            }
        ), 413
    return _gate_response()


# ── Start worker ───────────────────────────────────────────────────────────────
_worker = threading.Thread(target=_worker_loop, daemon=True, name='zpub-worker')
_worker.start()


def _start_mdns(hostname: str = 'ZygomaticsZero') -> None:
    """Register a custom mDNS hostname so LAN clients can use <hostname>.local instead of a raw IP."""
    import subprocess
    import socket

    # Get the actual LAN IP (not loopback)
    local_ip = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    if not local_ip or local_ip.startswith('127.'):
        # No route off the box (or only loopback): fall back to the configured LAN host,
        # which is loopback itself unless the deployment named an address.
        local_ip = settings.ZYG_LAN_HOST
    cmd = ['avahi-publish', '-a', '-R', f'{hostname}.local', local_ip]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _zyg_log.info(f'[ZeroPub] mDNS: {hostname}.local → {local_ip}  (avahi-publish PID {proc.pid})')
    except Exception as e:
        _zyg_log.info(f'[ZeroPub] mDNS registration failed: {e}')


def _start_public_tunnel() -> None:
    """Start a Cloudflare Tunnel for public access.

    The tunnel's own hostname is configured on the Cloudflare side and named here by
    ZERO_PUBLIC_URL, so no deployment's domain is baked in; without it the sidecar records
    the loopback URL and the public links fall back to the Host header of each request.
    The URL is permanent — written to the sidecar on start. Auto-restarts if cloudflared
    exits.

    The tunnel credential comes from ZERO_PUBLIC_CF_TOKEN. It is a secret and is never
    stored in this tree; with no token there is no tunnel and the site stays local-only.
    """
    import subprocess

    CF_URL = os.environ.get('ZERO_PUBLIC_URL', '').strip().rstrip('/') or f'http://localhost:{PORT}'
    CF_TOKEN = os.environ.get('ZERO_PUBLIC_CF_TOKEN', '').strip()
    if not CF_TOKEN:
        _zyg_log.info('[ZeroPub] ZERO_PUBLIC_CF_TOKEN not set — skipping public tunnel.')
        return

    cf_bin = shutil.which('cloudflared') or os.path.expanduser('~/.local/bin/cloudflared')
    if not os.path.isfile(cf_bin) and not shutil.which('cloudflared'):
        _zyg_log.info('[ZeroPub] cloudflared not found — skipping public tunnel.')
        return

    _sidecar = os.path.join(_LOG_DIR, 'tunnel_url.txt')
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        with open(_sidecar, 'w') as f:
            f.write(CF_URL)
    except Exception as e:
        _zyg_log.info(f'[ZeroPub] Could not write tunnel sidecar: {e}')

    def _run():
        while True:
            try:
                _zyg_log.info(f'[ZeroPub] Starting Cloudflare Tunnel → {CF_URL}')
                proc = subprocess.Popen(
                    [cf_bin, 'tunnel', 'run', '--token', CF_TOKEN],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                for raw in proc.stdout:
                    line = raw.decode('utf-8', errors='replace').strip()
                    if line:
                        _zyg_log.info(f'[cloudflared] {line}')
                proc.wait()
                _zyg_log.info('[ZeroPub] cloudflared exited — reconnecting in 10 s…')
            except Exception as e:
                _zyg_log.info(f'[ZeroPub] cloudflared error: {e}')
            time.sleep(10)

    t = threading.Thread(target=_run, daemon=True, name='cf-tunnel')
    t.start()


# ── Entry point ────────────────────────────────────────────────────────────────
def _recover_stale_jobs() -> None:
    """On startup, finalize jobs still stuck in ``running`` after a process restart."""
    try:
        if not os.path.isdir(_JOB_PERSIST_DIR):
            return
        import glob as _gl

        _now = _ams_iso()
        n_recovered = 0
        for _jf in _gl.glob(os.path.join(_JOB_PERSIST_DIR, '*.json')):
            try:
                with open(_jf, encoding='utf-8') as _f:
                    _j = json.load(_f)
                if _j.get('status') != 'running':
                    continue
                # Prefer main-app truth when Flask is up (interrupted vs still live).
                _j = _reconcile_zpub_job_with_pipeline(_j)
                if _j.get('status') == 'running':
                    _j['status'] = 'failed'
                    _j['error'] = _j.get('error') or 'Server restarted — pipeline interrupted'
                    _j['completed_at'] = _now
                    _j['current_stage'] = None
                    _save_job(_j)
                n_recovered += 1
                _zyg_log.info(f'[ZeroPub] Recovered stale job {_j.get("job_id", "?")} → {_j.get("status")}')
            except Exception as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
        r = _get_redis()
        if r:
            try:
                r.delete(_RUNNING_KEY)
            except Exception as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
        with _mem_lock:
            zpub_store._mem_running = None
        if n_recovered:
            _zyg_log.info(f'[ZeroPub] Stale job recovery: {n_recovered} job(s) reconciled')
    except Exception as _e:
        _zyg_log.info(f'[ZeroPub] job recovery error: {_e}')


if __name__ == '__main__':  # the CLI lives in zero_public_server_cli
    from zyg_zero.zero_public_server_cli import main as _cli_main

    raise SystemExit(_cli_main())
