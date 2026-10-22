#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""nomologin_browser.py — Python side of persona browser control.

The driving itself is Puppeteer, in nomologin_node/driver.js. This module decides WHICH
browser to drive and hands over a batch of actions; it holds no protocol code of its own.
The hand-rolled CDP client this replaced is kept as
nomologin_browser.py.bak-handrolled-cdp-20260923 — it worked, but it was blind inside
iframes, which is exactly where consent walls and embedded composers live.

It ATTACHES to the browser Nomologin already put on screen: the persona's own profile, its
own cookie jar, its own proxy. Nothing here signs in. You sign in by hand once per persona
per platform (the Tier B ruling), the session persists in the profile, and this operates it
afterwards — which is why cookie_age_days matters and why the board shows it.

Batched on purpose: one `node` invocation runs a whole sequence over one connection, so a
ten-step posting flow pays Node's startup once instead of ten times.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from zyg_zero import nomologin as nl  # noqa: E402

NODE = os.environ.get('ZYG_NOMOLOGIN_NODE', 'node')
DRIVER = os.path.join(HERE, 'nomologin_node', 'driver.js')

# A batch can legitimately be slow: page loads on a proxied exit plus per-keystroke typing.
# The ceiling is here rather than in the driver so a wedged browser cannot hang the board.
BATCH_TIMEOUT = float(os.environ.get('ZYG_NOMOLOGIN_BATCH_TIMEOUT', '240'))

# Port allocation lives in nomologin.py beside shim_port, because the LAUNCHER owns it — it
# is the thing that hands Chrome the flag. Here we only read it.
debug_port = nl.debug_port


class BrowserError(RuntimeError):
    """Failures the assistant should read and retry differently, not crash on."""


def _port(pid: str) -> int:
    """The port this persona's LIVE browser is on.

    State first, never a fresh allocation: the running Chrome holds whatever port it was
    started with, and a later collision walk must not change our answer out from under it.
    """
    nl.get_persona(pid)
    if not nl.chrome_running(pid):
        raise BrowserError(f'{pid} is not open — Open the persona first')
    port = (nl._state().get(pid, {}) or {}).get('debug_port')
    if not port:
        raise BrowserError(
            f'{pid} is open but was started before browser control existed, so Chrome got '
            'no debug port — Stop it and Open it again'
        )
    return int(port)


def available() -> dict:
    """Whether the driver can run at all. Checked before the assistant is offered the
    tools, so a missing dependency is one clear message instead of a failure per action."""
    out = {'driver': DRIVER, 'driver_ok': os.path.isfile(DRIVER)}
    modules = os.path.join(HERE, 'nomologin_node', 'node_modules', 'puppeteer-core')
    out['puppeteer_ok'] = os.path.isdir(modules)
    try:
        v = subprocess.run([NODE, '--version'], capture_output=True, text=True, timeout=10)
        out['node'] = v.stdout.strip()
        out['node_ok'] = v.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        out['node'], out['node_ok'] = str(exc), False
    out['ok'] = all(out[k] for k in ('driver_ok', 'puppeteer_ok', 'node_ok'))
    if not out['ok']:
        out['hint'] = f'run `npm install puppeteer-core` in {os.path.join(HERE, "nomologin_node")}'
    return out


def run(pid: str, actions: list[dict], timeout: float = BATCH_TIMEOUT) -> list[dict]:
    """Run a batch against the persona's browser. Returns one result per action, in order.

    A failed step returns {'error': ...} in place rather than raising, so the results of
    the steps that already ran are not lost — on a live session, knowing how far a posting
    flow got before it stuck is the difference between retrying and double-posting.
    """
    port = _port(pid)
    payload = json.dumps({'actions': actions})
    try:
        p = subprocess.run([NODE, DRIVER, str(port), payload], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise BrowserError(
            f'browser batch exceeded {timeout:g}s and was abandoned; the '
            'page may be half-way through — read it before retrying'
        ) from None
    except OSError as exc:
        raise BrowserError(f'could not run the driver: {exc}') from exc

    out = (p.stdout or '').strip()
    if not out:
        raise BrowserError(f'driver returned nothing (exit {p.returncode}): {(p.stderr or "").strip()[:400]}')
    try:
        got = json.loads(out)
    except json.JSONDecodeError:
        raise BrowserError(f'driver returned non-JSON: {out[:400]}') from None
    if not got.get('ok'):
        raise BrowserError(got.get('error', 'driver failed'))
    return got.get('results', [])


def act(pid: str, action: str, **kw) -> dict:
    """One action. Convenience over run() for the single-step cases."""
    kw = {k: v for k, v in kw.items() if v is not None}
    return run(pid, [dict(kw, action=action)])[0]


def status(pid: str) -> dict:
    """Whether this persona can be driven, and why not if not. Never raises — the board
    renders this per card and a refusal is an answer, not an outage."""
    out: dict = {'persona': pid, 'drivable': False}
    try:
        out['chrome_pid'] = nl.chrome_running(pid)
        out['debug_port'] = (nl._state().get(pid, {}) or {}).get('debug_port')
        got = run(pid, [{'action': 'status'}])[0]
        if got.get('error'):
            out['why'] = got['error']
            return out
        out.update(drivable=True, browser=got.get('version'), tabs=got.get('tabs', []))
    except (BrowserError, KeyError) as exc:
        out['why'] = str(exc)
    return out


if __name__ == '__main__':  # the CLI lives in nomologin_browser_cli
    from zyg_zero.nomologin_browser_cli import cli_main as _cli_main

    raise SystemExit(_cli_main())
