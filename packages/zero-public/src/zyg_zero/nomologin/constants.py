# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

# This module inherits nomologin.py's own top import block verbatim, so every name the
# single file exposed as an attribute still resolves. Names used only by sibling sections
# are therefore 'unused' here on purpose.
import base64
import binascii
import hashlib
import hmac
import json
import logging as _zyg_logging
import os
import re
import socket
import struct
import subprocess
import time
from datetime import datetime, timezone

from zyg_zero import paths as _zero_paths

# The package directory. This code was written in zyg_zero/nomologin.py, one
# directory up, and the sibling scripts it launches still live there.
HERE = str(_zero_paths.PKG_DIR)

from zyg_zero import nomologin_sites as ns  # noqa: E402

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_zero.nomologin')


ROOT = os.path.expanduser(os.environ.get('ZYG_NOMOLOGIN_ROOT', '~/nomologin'))
CACHE_ROOT = os.path.expanduser(os.environ.get('ZYG_NOMOLOGIN_CACHE', '~/.cache/nomologin'))
CHROME = os.environ.get('ZYG_NOMOLOGIN_CHROME', '/usr/bin/google-chrome')

MANIFEST = os.path.join(ROOT, 'personas.json')
SECRETS = os.path.join(ROOT, 'secrets.json')
KEYFILE = os.path.join(ROOT, 'secrets.key')
STATE = os.path.join(ROOT, 'state.json')
PROFILES = os.path.join(ROOT, 'profiles')
BACKUPS = os.path.join(ROOT, 'backups')
LOGS = os.path.join(ROOT, 'logs')

# Shim ports. 41000 is clear of every service on this box (5000/5001/5051/5300/5301/
# 7000/7001/7100/8090/8188/8700/8750/8899) and of MoreLogin's 40000, should it ever be
# installed alongside for comparison. Nomologin is on 8750.
SHIM_PORT_BASE = 41000
SHIM_PORT_SPAN = 200

# DevTools ports for the assistant's browser control, clear of the shim range. The port is
# as sensitive as the cookie jar it fronts — whatever reaches it IS the signed-in persona —
# so Chrome is told to bind loopback explicitly rather than trusting the default, and the
# board that drives it is loopback-only for the same reason.
DEBUG_PORT_BASE = 42000
DEBUG_PORT_SPAN = 200

ID_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{0,31}$')

# Cache ceiling per persona. 256 MB is plenty for a posting session and keeps 20 personas
# under 5 GB — this machine runs at 93% of 1.8 T, so an unbounded cache per profile is a
# real hazard, not a theoretical one.
DISK_CACHE_BYTES = 268435456

# Every posting destination the add-account form can offer. This is data, so it lives in
# nomologin_sites.py — 252 sites across 24 language groups, each carrying its group and
# whether an outbound link actually survives there (the research is in
# NOMOLOGIN_SEEDING_SITES.md). The import is deliberately hard: a persona's targets name
# these keys, so a missing catalogue would make validate() refuse every persona as
# "unknown platform" and show the whole board as broken. A loud ImportError names the
# real fault instead.
PLATFORMS = ns.SITES
PLATFORM_GROUPS = ns.GROUPS

# One tab per enabled target, all handed to a single Chrome. With 252 selectable sites a
# persona can be built that would open 252 live sessions at once, which neither Chrome nor
# this box carries — and each tab is a real logged-in session, not a page. launch() refuses
# above this rather than truncating silently; the per-platform chips on the card are the
# way to open one, and this is the override for an operator who means it.
MAX_TABS = int(os.environ.get('ZYG_NOMOLOGIN_MAX_TABS', '20'))


# ── small utilities ───────────────────────────────────────────────────────────────────
def _now() -> float:
    return time.time()


def _iso(ts: float | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat(timespec='seconds')


def _read_json(path: str, default):
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json(path: str, obj, mode: int = 0o644) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.tmp.{os.getpid()}'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)
        fh.write('\n')
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _cmdline(pid: int) -> str:
    try:
        with open(f'/proc/{pid}/cmdline', 'rb') as fh:
            return fh.read().replace(b'\0', b' ').decode('utf-8', 'replace')
    except OSError:
        return ''


def _port_free(port: int, host: str = '127.0.0.1') -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _port_listening(port: int, host: str = '127.0.0.1', timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False


def _du(path: str) -> int:
    """Bytes on disk under path. `du` is far faster than walking this in Python for a
    Chrome profile, which is tens of thousands of small files."""
    try:
        out = subprocess.run(['du', '-sb', path], capture_output=True, text=True, timeout=60)
        if out.returncode == 0:
            return int(out.stdout.split('\t', 1)[0])
    except (OSError, ValueError, subprocess.SubprocessError) as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return total


def _human(n: int | None) -> str:
    if not n:
        return '0 B'
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or unit == 'TB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024.0
    return f'{n:.1f} TB'


# ── secrets ───────────────────────────────────────────────────────────────────────────
def _fernet():
    """Lazy, because `cryptography` is only needed when a TOTP seed is actually stored."""
    from cryptography.fernet import Fernet

    os.makedirs(ROOT, exist_ok=True)
    if not os.path.exists(KEYFILE):
        key = Fernet.generate_key()
        fd = os.open(KEYFILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as fh:
            fh.write(key)
    with open(KEYFILE, 'rb') as fh:
        return Fernet(fh.read())


def set_secret(persona_id: str, platform: str, seed: str) -> None:
    """Store a TOTP seed (base32, as the platform's 'can't scan the code?' text gives it)."""
    seed = re.sub(r'\s+', '', seed).upper()
    try:
        base64.b32decode(seed + '=' * (-len(seed) % 8), casefold=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f'not a base32 TOTP seed: {e}') from e
    f = _fernet()
    store = _read_json(SECRETS, {})
    store.setdefault(persona_id, {})[platform] = f.encrypt(seed.encode()).decode()
    _write_json(SECRETS, store, mode=0o600)


def get_secret(persona_id: str, platform: str) -> str | None:
    blob = (_read_json(SECRETS, {}).get(persona_id) or {}).get(platform)
    if not blob:
        return None
    return _fernet().decrypt(blob.encode()).decode()


def totp(persona_id: str, platform: str, when: float | None = None, digits: int = 6, period: int = 30) -> dict:
    """RFC 6238 TOTP. Implemented here rather than pulled in: it is twenty lines of hmac,
    and this box has no pyotp (and the sandbox does not install)."""
    seed = get_secret(persona_id, platform)
    if not seed:
        return {'ok': False, 'error': f'no TOTP seed stored for {persona_id}/{platform}'}
    key = base64.b32decode(seed + '=' * (-len(seed) % 8), casefold=True)
    now = when or _now()
    counter = int(now // period)
    digest = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack('>I', digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return {'ok': True, 'code': str(code % (10**digits)).zfill(digits), 'expires_in': int(period - (now % period))}
