# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import logging as _zyg_logging
import os
import subprocess
import time

from zyg_zero.nomologin.constants import (
    CHROME,
    DISK_CACHE_BYTES,
    LOGS,
    MAX_TABS,
    _alive,
    _cmdline,
    _iso,
    _now,
)
from zyg_zero.nomologin.manifest import (
    _set_state,
    _state,
    cache_dir,
    debug_port,
    get_persona,
    profile_dir,
    target_urls,
    validate,
)
from zyg_zero.nomologin.profile import (
    apply_theme,
    clear_singleton,
    ensure_profile,
    probe,
    start_shim,
    stop_shim,
)

_zyg_log = _zyg_logging.getLogger('zyg_zero.nomologin')


# ── launch ────────────────────────────────────────────────────────────────────────────
def chrome_running(pid: str) -> int | None:
    """The live Chrome pid for this persona, or None. Matched on the user-data-dir rather
    than a stored pid alone, so a recycled pid cannot be mistaken for a live browser."""
    row = _state().get(pid, {})
    cpid = row.get('chrome_pid')
    if _alive(cpid) and profile_dir(pid) in _cmdline(cpid):
        return cpid
    # Chrome may have been started outside the hub, or re-parented after a crash.
    try:
        for entry in os.listdir('/proc'):
            if not entry.isdigit():
                continue
            cl = _cmdline(int(entry))
            if f'--user-data-dir={profile_dir(pid)}' in cl and 'type=' not in cl:
                return int(entry)
    except OSError as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return None


def x_display() -> str | None:
    """The X display a browser window can actually appear on, or None if there is none.

    Chrome is a GUI program and dies instantly without one:
        Missing X server or $DISPLAY / The platform failed to initialize.  Exiting.
    That is not hypothetical — it is what every launch did until 2026-09-23. The board is
    normally started by restart_api / hub_watch, which carry XDG_RUNTIME_DIR and DBUS (so
    `systemctl --user` works) but NOT DISPLAY, so an inherited environment gives Chrome
    nothing to draw on. Resolve the display from the sockets the X server actually created
    rather than assuming :0 ([[measure, do not assume]]).
    """
    d = os.environ.get('DISPLAY')
    if d:
        return d
    # /tmp/.X11-unix is the X server's own socket directory, fixed by the X protocol — this
    # reads it, it does not create anything there, so it is not a temp file of ours.
    x11_sockets = '/tmp/.X11-unix'  # nosec B108  # noqa: S108  X protocol path, read only
    try:
        socks = sorted(n for n in os.listdir(x11_sockets) if n.startswith('X') and n[1:].isdigit())
    except OSError:
        return None
    return f':{socks[0][1:]}' if socks else None


def gui_env(base: dict | None = None) -> tuple[dict, str | None]:
    """A copy of `base` that can open a window, plus the display it will open on."""
    env = dict(base if base is not None else os.environ)
    display = x_display()
    if not display:
        return env, None
    env['DISPLAY'] = display
    if not env.get('XAUTHORITY'):
        for cand in (os.path.expanduser('~/.Xauthority'), os.path.join(env.get('XDG_RUNTIME_DIR', ''), 'Xauthority')):
            if cand and os.path.exists(cand):
                env['XAUTHORITY'] = cand
                break
    return env, display


def _log_tail(pid: str, lines: int = 2) -> str:
    """The last log lines, so a refusal can quote the browser's own reason instead of
    sending the operator off to read a file."""
    try:
        with open(os.path.join(LOGS, f'{pid}.log'), 'rb') as fh:
            try:
                fh.seek(-4096, os.SEEK_END)
            except OSError:
                fh.seek(0)
            got = fh.read().decode('utf-8', 'replace').strip().splitlines()
    except OSError:
        return f'see logs/{pid}.log'
    # Chrome prefixes every line with [pid:tid:date:ERROR:file(line)] — drop it.
    keep = [ln.split('] ', 1)[-1].strip() for ln in got[-lines:] if ln.strip()]
    return ' / '.join(keep) or f'see logs/{pid}.log'


def chrome_argv(p: dict, urls: list[str], port: int | None, dbg: int | None = None) -> list[str]:
    pid = p['id']
    argv = [
        CHROME,
        f'--user-data-dir={profile_dir(pid)}',
        f'--disk-cache-dir={cache_dir(pid)}',
        f'--disk-cache-size={DISK_CACHE_BYTES}',
        # WM_CLASS, so xdotool/wmctrl can address one persona's windows specifically.
        f'--class=nomologin-{pid}',
        '--no-first-run',
        '--no-default-browser-check',
        # Sign-in and sync are the two ways a persona links itself to a Google identity.
        '--disable-sync',
        # Linux default is gnome-keyring/kwallet — one keyring shared by every profile.
        '--password-store=basic',
        '--disable-breakpad',
        '--metrics-recording-only',
        '--disable-background-networking',
    ]
    if dbg:
        # What lets the assistant drive this persona. Loopback is stated, not assumed: the
        # default address has moved between Chrome releases, and a debug port reachable off
        # this box would hand every signed-in session on it to the network.
        argv += [f'--remote-debugging-port={dbg}', '--remote-debugging-address=127.0.0.1']
    if port:
        argv += [
            f'--proxy-server=http://127.0.0.1:{port}',
            # Default bypass includes local addresses; keep it explicit and minimal so
            # nothing routes around the shim.
            '--proxy-bypass-list=<-loopback>',
            # WebRTC will hand out the real address over STUN around a working proxy.
            '--webrtc-ip-handling-policy=disable_non_proxied_udp',
        ]
    if p.get('window'):
        w = p['window']
        if w.get('size'):
            argv.append(f'--window-size={w["size"]}')
        if w.get('position'):
            argv.append(f'--window-position={w["position"]}')
    return argv + urls


def launch(pid: str, only: list[str] | None = None, gate: bool = True) -> dict:
    """Bring a persona up: shim, gate, then Chrome. Returns a dict the board renders."""
    p = get_persona(pid)
    problems = validate(p)
    if problems:
        return {'ok': False, 'stage': 'manifest', 'error': '; '.join(problems)}
    if not os.path.exists(CHROME):
        return {'ok': False, 'stage': 'chrome', 'error': f'{CHROME} not found'}
    env, display = gui_env()
    if not display:
        return {
            'ok': False,
            'stage': 'display',
            'error': 'no X display — there is no desktop session to put a window on',
            'hint': 'if you are logged in at the screen, the board was started without '
            'DISPLAY; restart it from the hub and it will find :0 itself',
        }

    urls = target_urls(p, only)
    if not urls:
        return {'ok': False, 'stage': 'targets', 'error': 'no enabled targets to open'}
    if len(urls) > MAX_TABS:
        return {
            'ok': False,
            'stage': 'targets',
            'error': f'{len(urls)} targets enabled — that is {len(urls)} live '
            f'sessions in one window, past the {MAX_TABS}-tab ceiling',
            'hint': 'open one platform at a time from its chip on the card, or '
            'set ZYG_NOMOLOGIN_MAX_TABS if you mean it',
        }

    ensure_profile(p)
    busy = clear_singleton(pid)
    if busy:
        existing = chrome_running(pid)
        if existing:
            # Relaunching the same user-data-dir hands the URLs to the running browser,
            # which is what we want: the persona gets its tabs, not a second window.
            return _reopen(p, urls, existing)
        return {'ok': False, 'stage': 'profile', 'error': busy}

    port = None
    if p.get('proxy'):
        s = start_shim(p)
        if not s['ok']:
            return {'ok': False, 'stage': 'shim', 'error': s['error']}
        port = s['port']
        if gate:
            pr = probe(pid)
            if pr['verdict'] != 'clean':
                stop_shim(pid)
                return {
                    'ok': False,
                    'stage': 'gate',
                    'verdict': pr['verdict'],
                    'error': pr['detail'],
                    'hint': 'launch with --no-gate to open anyway — the persona will '
                    'post from whatever IP it can reach',
                }

    if p.get('theme', True):
        apply_theme(pid, p.get('color', '#8b5cf6'))

    if p.get('timezone'):
        # A Dutch persona on a US exit is more suspicious than no proxy at all: the clock
        # the page reads must agree with the address it is reached from.
        env['TZ'] = p['timezone']
    if p.get('locale'):
        env['LANG'] = env['LC_ALL'] = p['locale']

    dbg = debug_port(pid)
    argv = chrome_argv(p, urls, port, dbg)
    os.makedirs(LOGS, exist_ok=True)
    log = open(os.path.join(LOGS, f'{pid}.log'), 'ab', buffering=0)
    log.write(f'\n=== {_iso(_now())} launch ===\n{" ".join(argv)}\n'.encode())
    proc = subprocess.Popen(
        argv, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True, env=env
    )
    time.sleep(0.6)
    if proc.poll() is not None:
        if port:
            stop_shim(pid)
        return {
            'ok': False,
            'stage': 'chrome',
            'error': f'chrome exited at once (code {proc.returncode}): {_log_tail(pid)}',
            'hint': f'full output in {LOGS}/{pid}.log',
        }
    _set_state(
        pid, chrome_pid=proc.pid, last_launch=_now(), shim_port=port, debug_port=dbg, opened=urls, last_only=only
    )
    return {
        'ok': True,
        'stage': 'running',
        'pid': proc.pid,
        'shim_port': port,
        'debug_port': dbg,
        'urls': urls,
        'egress': (_state().get(pid, {}).get('last_probe') or {}).get('ip'),
    }


def _reopen(p: dict, urls: list[str], existing: int) -> dict:
    """Hand URLs to the persona's already-running browser."""
    argv = [CHROME, f'--user-data-dir={profile_dir(p["id"])}'] + urls
    subprocess.Popen(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env=gui_env()[0],
    )
    _set_state(p['id'], last_launch=_now(), opened=urls)
    return {'ok': True, 'stage': 'reopened', 'pid': existing, 'urls': urls, 'note': 'tabs handed to the running window'}


def stop(pid: str, hard: bool = False) -> dict:
    """Close a persona. SIGTERM by default: Chrome flushes its cookie jar on a clean exit,
    and a SIGKILL here is how you lose a session you spent 2FA on."""
    cpid = chrome_running(pid)
    if cpid:
        try:
            os.kill(cpid, 9 if hard else 15)
        except OSError as e:
            return {'ok': False, 'error': str(e)}
        deadline = _now() + (2 if hard else 15)
        while _now() < deadline and _alive(cpid):
            time.sleep(0.2)
    stop_shim(pid)
    _set_state(pid, chrome_pid=None, last_stop=_now())
    return {
        'ok': True,
        'was_running': bool(cpid),
        'note': 'cookie jar flushed on clean exit' if cpid and not hard else None,
    }
