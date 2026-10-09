# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 by the GUI modularization (split out of zero_public_server.py).
# Source line refs: crews_modularization_backups_20260717/originals/zero_public_server.py

import ipaddress
import os
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo

    _AMS_TZ = ZoneInfo('Europe/Amsterdam')
except Exception:
    _AMS_TZ = None

from flask import (
    request,
)
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def _ams_now() -> datetime:
    """Return timezone-aware now() in Europe/Amsterdam (UTC fallback)."""
    if _AMS_TZ is not None:
        try:
            return datetime.now(_AMS_TZ)
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return datetime.now(timezone.utc)


def _ams_iso(timespec: str = 'milliseconds') -> str:
    """Tz-aware ISO timestamp in Europe/Amsterdam, including ``+HH:MM`` offset."""
    try:
        return _ams_now().isoformat(timespec=timespec)
    except TypeError:
        return _ams_now().isoformat()


# Load .env early so ZERO_PUBLIC_TOKEN and other secrets are available before
# any module-level os.environ.get() calls below.
_dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')
try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(_dotenv_path, override=False)
except ImportError as _exc:
    _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)

# ── Configuration ─────────────────────────────────────────────────────────────
MAIN_APP_URL = os.environ.get('ZERO_MAIN_APP_URL', 'http://localhost:5000')
# Public base URL for user-facing links (/u/<token> invites) — this server's own public
# address, NOT the internal dashboard (MAIN_APP_URL). No deployment's domain is baked in:
# ZERO_PUBLIC_URL wins when set (a tunnel's hostname differs from the Host header the
# tunnel forwards), otherwise the address the request actually arrived on is used, and
# loopback is the last resort for a link built outside a request.
_PUBLIC_URL_ENV = os.environ.get('ZERO_PUBLIC_URL', '').strip().rstrip('/')


def public_url() -> str:
    """Return the base URL to build user-facing links on, without a trailing slash."""
    if _PUBLIC_URL_ENV:
        return _PUBLIC_URL_ENV
    if request:
        return request.host_url.rstrip('/')
    return f'http://localhost:{PORT}'


INTERNAL_TOKEN = os.environ.get('ZERO_PUBLIC_TOKEN', '')
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
PORT = int(os.environ.get('ZERO_PUBLIC_PORT', 5001))
SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', os.urandom(32).hex())

# Upload directory for user-uploaded media (preview windows + video pipeline images)
UPLOAD_ROOT = os.path.join(os.path.dirname(__file__), 'data', 'runtime', 'uploads')
os.makedirs(UPLOAD_ROOT, exist_ok=True)
ALLOWED_IMAGE_EXTS = {'.jpg', '.jpeg', '.png'}
ALLOWED_VIDEO_EXTS = {'.mp4', '.webm', '.mov'}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB per file
MAX_VIDEO_BYTES = 1024 * 1024 * 1024  # 1 GB per video file (preview window persistence)
PREVIEW_CHUNK_BYTES = 8 * 1024 * 1024  # per-chunk limit (Cloudflare tunnel ~100 MB body cap)
CHUNK_UPLOAD_ROOT = os.path.join(UPLOAD_ROOT, '.preview_chunks')
os.makedirs(CHUNK_UPLOAD_ROOT, exist_ok=True)

# Average pipeline duration in seconds — used for ETA calculation (45 min default)
AVG_PIPELINE_SECONDS = int(os.environ.get('ZERO_AVG_PIPELINE_S', 2700))

# Max jobs per IP per hour (local/LAN IPs are always exempt)
RATE_LIMIT_PER_HOUR = int(os.environ.get('ZERO_RATE_LIMIT', 2))


def is_local_client(addr: str) -> bool:
    """True for a client on this machine or on the local network — the rate-limit
    exemption above. ``ipaddress`` answers it from the address itself, so no network
    this install happens to sit on has to be named here."""
    if not addr:
        return False
    if addr == 'localhost':
        return True
    try:
        ip = ipaddress.ip_address(addr.strip())
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


# Redis key TTL — jobs persist for 48 hours
JOB_TTL = 48 * 3600
