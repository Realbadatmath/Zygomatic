# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import logging as _zyg_logging
import os
import subprocess
import sys
import time

from zyg_zero import nomologin_proxy as np
from zyg_zero.nomologin.constants import (
    HERE,
    LOGS,
    PROFILES,
    ROOT,
    SECRETS,
    _alive,
    _cmdline,
    _now,
    _port_listening,
    _read_json,
    _write_json,
)
from zyg_zero.nomologin.manifest import _set_state, _state, cache_dir, get_persona, profile_dir, shim_port

# Bound by assignment, under the single file's own logger name, so the records this section
# emits are indistinguishable from the ones it emitted before the split.
_zyg_log = _zyg_logging.getLogger('zyg_zero.nomologin')

# ── profile creation ──────────────────────────────────────────────────────────────────
# Seeded once, at profile creation, and never rewritten: Chrome owns this file afterwards
# and clobbering a live profile's Preferences would drop the operator's own settings.
_SEED_PREFS = {
    'signin': {'allowed': False, 'allowed_on_next_startup': False},
    'browser': {'has_seen_welcome_page': True, 'check_default_browser': False},
    'credentials_enable_service': False,
    'credentials_enable_autosignin': False,
    'profile': {
        # Sends a hash of every password you type to Google, from every profile. A
        # correlation channel that outlives perfect cookie isolation.
        'password_manager_leak_detection': False,
        'default_content_setting_values': {'notifications': 2},
    },
    # Omnibox suggestions ship each keystroke to the search provider. Typing a persona's
    # own handle into the bar of another persona's window is a link you cannot take back.
    'search': {'suggest_enabled': False},
    'alternate_error_pages': {'enabled': False},
    'translate': {'enabled': False},
    'safebrowsing': {'enabled': True, 'enhanced': False},
}


# Chrome's own "user colour" theme. Verified on Chrome 148: an unpacked theme passed with
# --load-extension is silently ignored, but these prefs tint the frame, toolbar and active
# tab, and two personas side by side are unmistakable. Variant 3 is the vibrant scheme —
# the tonal-spot default washes out to nearly white.
THEME_VARIANT_VIBRANT = 3


def _sk_color(colour: str) -> int | None:
    """#rrggbb -> the signed 32-bit ARGB integer Chrome stores in prefs."""
    try:
        r, g, b = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
    except (ValueError, IndexError):
        return None
    argb = (0xFF << 24) | (r << 16) | (g << 8) | b
    return argb - (1 << 32) if argb >= (1 << 31) else argb


def apply_theme(pid: str, colour: str) -> bool:
    """Tint this persona's window in its own colour.

    The cheapest guard against the commonest and costliest mistake in multi-account work:
    posting into the wrong identity. A glance at the frame tells you who you are.

    Written on every launch so a colour edit in personas.json takes effect, but only ever
    as a surgical merge into the existing Preferences — Chrome owns that file, and
    clobbering it would drop the operator's own settings. Safe here because launch() has
    already established that this profile has no live Chrome holding it.
    """
    argb = _sk_color(colour)
    if argb is None:
        return False
    prefs_path = os.path.join(profile_dir(pid), 'Default', 'Preferences')
    prefs = _read_json(prefs_path, {})
    theme = prefs.setdefault('browser', {}).setdefault('theme', {})
    theme.update(
        {
            'user_color2': argb,
            'color_variant2': THEME_VARIANT_VIBRANT,
            'is_grayscale2': False,
            'follows_system_colors': False,
        }
    )
    _write_json(prefs_path, prefs)
    return True


def ensure_profile(p: dict) -> tuple[str, bool]:
    """Create the profile dir if absent. Returns (path, created_now)."""
    pid = p['id']
    prof = profile_dir(pid)
    created = not os.path.exists(prof)
    os.makedirs(os.path.join(prof, 'Default'), exist_ok=True)
    os.makedirs(cache_dir(pid), exist_ok=True)
    os.makedirs(LOGS, exist_ok=True)
    prefs = os.path.join(prof, 'Default', 'Preferences')
    if not os.path.exists(prefs):
        _write_json(prefs, _SEED_PREFS)
        created = True
    # 0700: these directories hold live session cookies for every account this persona
    # owns. A readable profile dir is a readable set of logged-in sessions.
    for d in (ROOT, PROFILES, prof, SECRETS if os.path.exists(SECRETS) else prof):
        try:
            os.chmod(d, 0o700 if os.path.isdir(d) else 0o600)
        except OSError as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return prof, created


def clear_singleton(pid: str) -> str | None:
    """Chrome leaves SingletonLock -> <host>-<pid> behind after a hard kill, and refuses to
    start while it points at a live pid. Removing it blindly would let two Chromes share
    one profile and corrupt the cookie jar, so the target pid is checked first."""
    prof = profile_dir(pid)
    lock = os.path.join(prof, 'SingletonLock')
    if not os.path.islink(lock):
        return None
    try:
        target = os.readlink(lock)
        owner = int(target.rsplit('-', 1)[-1])
    except (OSError, ValueError):
        owner = 0
    if _alive(owner) and 'chrome' in _cmdline(owner).lower():
        return f'profile is in use by live pid {owner}'
    for name in ('SingletonLock', 'SingletonCookie', 'SingletonSocket'):
        try:
            os.unlink(os.path.join(prof, name))
        except OSError as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return None


# ── the proxy shim, per persona ───────────────────────────────────────────────────────
def shim_running(pid: str) -> bool:
    row = _state().get(pid, {})
    spid, port = row.get('shim_pid'), row.get('shim_port')
    return bool(port and _alive(spid) and 'nomologin_proxy' in _cmdline(spid) and _port_listening(port))


def start_shim(p: dict) -> dict:
    """Start this persona's shim and wait for it to accept connections."""
    pid = p['id']
    proxy = p.get('proxy')
    if not proxy:
        return {'ok': True, 'port': None, 'note': 'no proxy configured'}
    if shim_running(pid):
        return {'ok': True, 'port': _state()[pid]['shim_port'], 'note': 'already running'}
    port = shim_port(pid)
    os.makedirs(LOGS, exist_ok=True)
    log = open(os.path.join(LOGS, f'{pid}-proxy.log'), 'ab', buffering=0)
    proc = subprocess.Popen(
        [sys.executable, os.path.join(HERE, 'nomologin_proxy.py'), '--listen', str(port), '--upstream', proxy],
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        cwd=HERE,
    )
    deadline = _now() + 10
    while _now() < deadline:
        if _port_listening(port):
            _set_state(pid, shim_pid=proc.pid, shim_port=port, shim_started=_now())
            return {'ok': True, 'port': port, 'pid': proc.pid}
        if proc.poll() is not None:
            return {
                'ok': False,
                'error': f'shim exited immediately (code {proc.returncode}) — see logs/{pid}-proxy.log',
            }
        time.sleep(0.15)
    proc.terminate()
    return {'ok': False, 'error': f'shim did not listen on {port} within 10 s'}


def stop_shim(pid: str) -> bool:
    row = _state().get(pid, {})
    spid = row.get('shim_pid')
    if _alive(spid) and 'nomologin_proxy' in _cmdline(spid):
        try:
            os.kill(spid, 15)
        except OSError as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    _set_state(pid, shim_pid=None)
    return True


_direct_ip_cache: dict = {}


def direct_ip(max_age: float = 900.0) -> str | None:
    """This machine's own egress IP, cached — it is asked on every gated launch."""
    hit = _direct_ip_cache.get('v')
    if hit and _now() - hit[1] < max_age:
        return hit[0]
    ip = np.direct_ip()
    _direct_ip_cache['v'] = (ip, _now())
    return ip


def probe(pid: str) -> dict:
    """Measure what the world sees for this persona, and judge it.

    Verdicts: `clean` (a proxy IP distinct from the host's), `leak` (the proxy resolved to
    this machine's own address — it is not proxying), `direct` (no proxy configured, so the
    host IP is expected and honest), `down` (the upstream could not be reached).
    """
    p = get_persona(pid)
    proxy = p.get('proxy')
    mine = direct_ip()
    if not proxy:
        return {
            'verdict': 'direct',
            'ip': mine,
            'host_ip': mine,
            'proxy': None,
            'ok': True,
            'checked': _now(),
            'detail': 'no proxy configured — this persona posts from the host IP',
        }
    r = np.probe(proxy)
    if not r['ok']:
        out = {
            'verdict': 'down',
            'ip': None,
            'host_ip': mine,
            'ok': False,
            'proxy': np.Upstream(proxy).safe,
            'checked': _now(),
            'detail': r['error'],
        }
    elif mine and r['ip'] == mine:
        out = {
            'verdict': 'leak',
            'ip': r['ip'],
            'host_ip': mine,
            'ok': False,
            'proxy': np.Upstream(proxy).safe,
            'checked': _now(),
            'detail': "the upstream returned this machine's own address — it is not "
            'proxying, and this persona would post from the host IP',
        }
    else:
        out = {
            'verdict': 'clean',
            'ip': r['ip'],
            'host_ip': mine,
            'ok': True,
            'proxy': np.Upstream(proxy).safe,
            'checked': _now(),
            'detail': f'egress {r["ip"]} via {r["via"]} in {r["ms"]} ms',
        }
    _set_state(pid, last_probe=out)
    return out
