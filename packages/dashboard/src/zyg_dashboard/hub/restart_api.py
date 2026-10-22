# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Zygomatic Restart API — runs on Linux, port 7001
Accepts POST /restart/{app_id} from the hub.

Start it:   python3 restart_api.py
Keep alive: nohup python3 restart_api.py &

This API restarts services, so it listens on ``zyg_workflows.paths.BIND_HOST``,
which defaults to ``127.0.0.1``: reaching it from the LAN is an explicit opt-in,
made by setting ``BIND_HOST=0.0.0.0`` in the environment. The same value is handed
to the ``nexus`` static server below, so one setting governs both.
"""

import json
import os
import signal
import socket
import subprocess
import time
from http.server import BaseHTTPRequestHandler
from zyg_dashboard.cors import allowed_origin
from zyg_workflows.bin import exe
from zyg_workflows.paths import BIND_HOST, ZYG_CREWS_ROOT, ZYG_LEGACY_VENV_PY
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HOST = BIND_HOST
PORT = 7001

VENV_PY = str(ZYG_LEGACY_VENV_PY)

# Resolved once: the interpreter and shell the managed apps are launched with. These are
# the apps' OWN runtimes picked off PATH exactly as before, not this process's
# interpreter, so `sys.executable` would be the wrong answer here.
PY3 = exe('python3')
BASH = exe('bash')

APPS = {
    'zero': {
        # 2026-09-01: routed at the SYSTEM unit, was kill_port + Popen.
        #
        # Port 5000 had two owners. crewai-gui.service is enabled, so systemd
        # starts it at boot and the health probe restarts it when :5000 stops
        # answering — but this button used to SIGTERM that process and Popen a
        # replacement of its own. A clean TERM exits 0, which Restart=on-failure
        # correctly ignores, so the unit went inactive and the orphan owned the
        # port. Every later `systemctl restart crewai-gui.service` then died on
        # "Address already in use", three times in a row, and the unit sat in
        # start-limit-hit (15:47-15:49 on 2026-09-01, and it had been failing
        # this way since 2026-08-31 16:13).
        #
        # Worse than the red unit: while the orphan served :5000 the probe saw a
        # healthy port and never acted, so the GUI was running with NO wedge
        # recovery, no MemoryHigh=44G and no restart policy at all.
        #
        # One owner now. Same reasoning as medusa below, but a system
        # unit rather than a --user one, so it needs the sudo hop; the three
        # verbs are NOPASSWD in /etc/sudoers.d/zygomatic-services, which matches
        # on the FULL unit name.
        'port': 5000,
        'systemd_system': 'crewai-gui.service',
        'cwd': str(ZYG_CREWS_ROOT),
        'nohup': False,
    },
    'nexus': {
        'port': 8090,
        'cmd': [PY3, '-m', 'http.server', '8090', '--bind', BIND_HOST],
        'cwd': os.path.expanduser('~/Creator Nexus'),
        'nohup': True,
    },
    'hub': {
        'port': 7000,
        'cmd': [PY3, 'hub_server.py'],
        'cwd': os.path.expanduser('~/Zygomatic/hub'),
        'nohup': True,
    },
    'medusa': {
        # systemd --user unit (autostart on boot via linger + Restart=always crash
        # recovery). The "systemd" key routes the hub button
        # to `systemctl --user restart` instead of kill_port+Popen so the two
        # managers never fight over port 5300.
        'port': 5300,
        'systemd': 'medusa.service',
        'cwd': os.path.expanduser('~/Zygomatic/medusa'),
        'nohup': False,
    },
    'nomologin': {
        # kill_port + Popen (no systemd unit). Bound to 127.0.0.1:8750, NOT 0.0.0.0 like
        # the rest of the hub: this board opens browsers holding live sessions for every
        # social account and prints 2FA codes, so it must not be reachable over the LAN.
        # `lsof -ti :8750` still finds a loopback listener, so kill_port works normally.
        #
        # 2026-10-05: now a systemd --user unit (nomologin.service) like medusa, so
        # the hub button routes to `systemctl --user restart` and never fights
        # Restart=on-failure over the port.
        'port': 8750,
        'systemd': 'nomologin.service',
        'cwd': str(ZYG_CREWS_ROOT),
        'nohup': False,
    },
    'sandbox': {
        'port': 5555,
        'cmd': [BASH, 'start.sh'],
        'cwd': os.path.expanduser('~/sandbox-server'),
        'nohup': True,
    },
    'sessiontree': {
        # Session Tree (:7100) — the Claude agent job board. A --user unit like
        # medusa/transcribe, so the hub button routes to systemctl --user and
        # never fights Restart=always over the port.
        'port': 7100,
        'systemd': 'session-tree.service',
        'cwd': os.path.expanduser('~/Zygomatic/session_tree'),
        'nohup': False,
    },
}


def _systemctl(cfg: dict, verb: str) -> dict:
    """Hand a verb to whichever systemd manages this app.

    "systemd"        -> `systemctl --user <verb> <unit>`
    "systemd_system" -> `sudo -n /usr/bin/systemctl <verb> <unit>`

    Returns None when the app is not systemd-managed, so the caller falls
    through to the kill_port + Popen path.
    """
    unit = cfg.get('systemd') or cfg.get('systemd_system')
    if not unit:
        return None
    env = os.environ.copy()
    env.setdefault('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
    try:
        if cfg.get('systemd_system'):
            # Absolute path and full unit name: the sudoers rules match on the exact
            # command string, so `systemctl` or `crewai-gui` (no .service) prompts
            # for a password and hangs a non-interactive call.
            cmd = ['sudo', '-n', '/usr/bin/systemctl', verb, unit]
        else:
            cmd = [exe('systemctl'), '--user', verb, unit]
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=90)
    except Exception as e:
        return {'ok': False, 'error': f'systemctl {verb} failed: {e}'}
    if r.returncode != 0:
        return {
            'ok': False,
            'error': f'systemctl {verb} {unit} exited {r.returncode}: {(r.stderr or r.stdout or "").strip()[:300]}',
        }
    return {'ok': True, 'unit': unit}


def kill_port(port: int):
    """Kill every process listening on tcp:port."""
    try:
        result = subprocess.run([exe('lsof'), '-ti', f':{port}'], capture_output=True, text=True)
        pids = result.stdout.strip().split()
        for pid in pids:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except ProcessLookupError as _exc:
                _zyg_log.debug('pid %s already gone, nothing to kill: %s', pid, _exc)
        if pids:
            time.sleep(1.2)
    except Exception as e:
        _zyg_log.info(f'kill_port({port}) error: {e}')


def restart_app(app_id: str) -> dict:
    cfg = APPS.get(app_id)
    if not cfg:
        return {'ok': False, 'error': f'Unknown app: {app_id}'}

    # systemd-owned apps: hand the restart to systemd so we don't race its own
    # restart policy — and, for crewai-gui, so the port keeps a single owner.
    res = _systemctl(cfg, 'restart')
    if res is not None:
        return {**res, 'app': app_id} if res.get('ok') else res

    try:
        kill_port(cfg['port'])

        env = os.environ.copy()
        kwargs = dict(
            cwd=cfg['cwd'],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        subprocess.Popen(cfg['cmd'], **kwargs)
        return {'ok': True, 'app': app_id}

    except Exception as e:
        return {'ok': False, 'error': str(e)}


def stop_app(app_id: str) -> dict:
    """Turn an app OFF. systemd apps -> systemctl --user stop; others -> kill_port."""
    cfg = APPS.get(app_id)
    if not cfg:
        return {'ok': False, 'error': f'Unknown app: {app_id}'}

    res = _systemctl(cfg, 'stop')
    if res is not None:
        return {**res, 'app': app_id, 'state': 'stopped'} if res.get('ok') else res

    try:
        kill_port(cfg['port'])
        return {'ok': True, 'app': app_id, 'state': 'stopped'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def start_app(app_id: str) -> dict:
    """Turn an app ON. systemd apps -> systemctl --user start; others -> Popen.

    Only invoked by the hub toggle when the app reads OFFLINE, so no double
    instance; still, kill_port first on Popen apps to guarantee a single owner.
    """
    cfg = APPS.get(app_id)
    if not cfg:
        return {'ok': False, 'error': f'Unknown app: {app_id}'}

    res = _systemctl(cfg, 'start')
    if res is not None:
        return {**res, 'app': app_id, 'state': 'started'} if res.get('ok') else res

    try:
        kill_port(cfg['port'])
        env = os.environ.copy()
        kwargs = dict(
            cwd=cfg['cwd'],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        subprocess.Popen(cfg['cmd'], **kwargs)
        return {'ok': True, 'app': app_id, 'state': 'started'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def app_online(app_id: str) -> dict:
    """Is this app's port answering ON THIS MACHINE?

    2026-09-23: the hub used to decide Online/Offline by fetching the card's own URL from
    the *viewer's* browser. That is wrong for any service bound to loopback — Nomologin on
    127.0.0.1:8750 — because a browser on another machine resolves 127.0.0.1 to itself and
    always reports Offline. Worse than a wrong dot: syncPower() reads that dot to decide
    whether the power button sends `start` or `stop`, so a stale Offline turned the button
    into "start" for a service that was already running.

    This asks the question where the answer actually lives. restart_api runs beside the
    apps, so a local connect to the port is the truth, whoever is looking.
    """
    cfg = APPS.get(app_id)
    if not cfg:
        return {'ok': False, 'error': f'Unknown app: {app_id}'}
    port = cfg['port']
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1.5):
            online = True
    except OSError:
        online = False
    return {'ok': True, 'app': app_id, 'port': port, 'online': online}


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        """Answer cross-origin only to an origin listed in ZYG_CORS_ORIGINS (see cors.py).

        This is the API that restarts services, so an unlisted origin gets no
        Access-Control-Allow-Origin at all and the browser drops the response.
        """
        origin = allowed_origin(self.headers.get('Origin'))
        self.send_header('Vary', 'Origin')
        if origin:
            self.send_header('Access-Control-Allow-Origin', origin)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parts = self.path.strip('/').split('/')
        if parts and parts[0] == 'status':
            if len(parts) == 2:
                result = app_online(parts[1])
            else:
                result = {'ok': True, 'apps': {a: app_online(a)['online'] for a in APPS}}
            body = json.dumps(result).encode()
            self.send_response(200)
            self._cors()
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self._cors()
            self.end_headers()

    def do_POST(self):
        parts = self.path.strip('/').split('/')
        if len(parts) == 2 and parts[0] in ('restart', 'stop', 'start'):
            app_id = parts[1]
            if parts[0] == 'stop':
                result = stop_app(app_id)
            elif parts[0] == 'start':
                result = start_app(app_id)
            else:
                result = restart_app(app_id)
            body = json.dumps(result).encode()
            self.send_response(200)
            self._cors()
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self._cors()
            self.end_headers()

    def log_message(self, fmt, *args):
        _zyg_log.info(f'[restart-api] {fmt % args}')


if __name__ == '__main__':  # the CLI lives in restart_api_cli
    from zyg_dashboard.hub.restart_api_cli import main as _cli_main

    raise SystemExit(_cli_main())
