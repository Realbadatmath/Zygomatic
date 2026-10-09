# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""nomologin.py — the persona store and launcher. 2026-09-22.

One hub for every social identity that has to post. A *persona* is one brand — its
Facebook, X, Instagram, Threads and YouTube accounts all live inside a single Chrome
profile that is never shared with any other persona, and reaches the network through its
own proxy shim on its own loopback port.

The design in one line: **we never log in.** You sign into each platform by hand, once,
inside the persona's profile; the cookie jar keeps that session for months. Scripted logins
are what trigger 2FA challenges, captchas and "suspicious login" mail — this avoids all of
it by never doing it.

Isolation rests on four things, in descending order of how easily they are silently undone:

  1. `--user-data-dir` per persona. Separate cookies, localStorage, IndexedDB, service
     workers, history, extensions, and a separate process tree. Chrome's own profile
     switcher (`--profile-directory`) is NOT enough: it shares a browser process, a GPU
     process and the sign-in surface.
  2. `--password-store=basic`. Chrome on Linux defaults to gnome-keyring/kwallet, which is
     shared by every profile at the OS level — saved passwords for all personas would land
     in one keyring. `basic` keeps each profile's credentials in its own directory.
  3. Seeded prefs that switch off Chrome sign-in, sync, omnibox suggestions and password
     leak detection. Signing into Chrome in even one profile links that persona to a Google
     account and ships its cookies and history to sync; leak detection sends password
     hashes to Google from every profile. Both are correlation channels that survive
     perfect cookie isolation.
  4. `--proxy-server` pointing at this persona's shim, plus
     `--webrtc-ip-handling-policy=disable_non_proxied_udp`, because WebRTC will happily
     hand out the real address over STUN around a perfectly good proxy.

FAIL CLOSED. A persona with a proxy configured is launched only after its shim is up and
an egress probe has returned an IP that is *not* this machine's. If the proxy is down,
Chrome does not open at all — it never falls back to the direct connection. A persona that
quietly posts from the host IP defeats the entire point ([[feedback_measure_before_claim]]:
the claim "this persona is on its own IP" gets measured before it is made, every launch).

Layout, rooted at $ZYG_NOMOLOGIN_ROOT (default ~/nomologin):

    personas.json          hand-edited manifest — the only file you normally touch
    secrets.json           Fernet-encrypted TOTP seeds, mode 0600
    secrets.key            the key, mode 0600 (back this up separately from secrets.json)
    state.json             runtime: pids, shim ports, last launch, last measured egress IP
    profiles/<id>/         Chrome --user-data-dir. The valuable thing. Back these up.
    backups/<id>-<ts>.tar.gz
    logs/<id>.log

Disk caches live OUTSIDE that root, at $ZYG_NOMOLOGIN_CACHE (default ~/.cache/nomologin),
so profiles stay ~50-150 MB and back up cheaply instead of ~1 GB each. Each persona gets
its own cache dir — a shared one is a cross-persona timing vector.

CLI:

    python3 nomologin.py init                    scaffold the root and a sample manifest
    python3 nomologin.py list                    personas, disk, cookie age, running state
    python3 nomologin.py show <id>
    python3 nomologin.py doctor                  check chrome, prefs, proxies, direct IP
    python3 nomologin.py probe <id>              measure this persona's egress IP
    python3 nomologin.py launch <id> [--no-gate] [--only x,facebook]
    python3 nomologin.py stop <id>
    python3 nomologin.py status
    python3 nomologin.py backup <id> | restore <id> <archive>
    python3 nomologin.py totp <id> <platform>
    python3 nomologin.py set-secret <id> <platform>     reads the seed from stdin
    python3 nomologin.py sweep                   drop disk caches for idle personas

The board (nomologin_board.py, :8750) is a thin skin over this module — every decision,
number and refusal is made here, so the CLI and the board cannot disagree.
"""

from __future__ import annotations

import json
import sys

from zyg_zero.nomologin.constants import _human, set_secret, totp
from zyg_zero.nomologin.launching import launch, stop
from zyg_zero.nomologin.manifest import get_persona
from zyg_zero.nomologin.profile import probe
from zyg_zero.nomologin.reporting import backup, describe, doctor, init, overview, restore, sweep


# ── CLI ───────────────────────────────────────────────────────────────────────────────
def _print(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def _table(ov: dict) -> None:
    print(f'Nomologin — {ov["root"]}   host IP {ov["host_ip"] or "unknown"}')
    print(f'{"ID":<14} {"LABEL":<22} {"STATE":<9} {"EXIT":<16} {"COOKIES":<10} {"DISK":>9}')
    print('-' * 86)
    for p in ov['personas']:
        if p['problems']:
            state = 'BROKEN'
        elif p['running']:
            state = 'running'
        elif not p['logged_in_ever']:
            state = 'no login'
        elif p['stale']:
            state = 'stale'
        else:
            state = 'ready'
        probe_row = p.get('last_probe') or {}
        exit_ip = probe_row.get('ip') or ('host' if not p['proxy_configured'] else '?')
        age = f'{p["cookie_age_days"]:.0f}d' if p['cookie_age_days'] is not None else '—'
        print(f'{p["id"]:<14} {p["label"][:22]:<22} {state:<9} {str(exit_ip):<16} {age:<10} {_human(p["disk"]):>9}')
        for prob in p['problems']:
            print(f'{"":<14} ! {prob}')
    t = ov['totals']
    print('-' * 86)
    print(
        f'{t["count"]} personas · {t["running"]} running · {t["proxied"]} proxied · '
        f'{t["broken"]} broken · {t["stale"]} stale · {t["never_logged_in"]} never '
        f'logged in · {_human(t["disk"])} profiles + {_human(t["cache"])} cache'
    )


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    try:
        if cmd == 'init':
            _print(init())
        elif cmd == 'list':
            ov = overview()
            _print(ov) if '--json' in rest else _table(ov)
        elif cmd == 'show':
            _print(describe(get_persona(rest[0])))
        elif cmd == 'doctor':
            d = doctor()
            if '--json' in rest:
                _print(d)
            else:
                for c in d['checks']:
                    print(f'[{"ok" if c["ok"] else "FAIL"}] {c["check"]}: {c["detail"]}')
                print('\nall clear' if d['ok'] else '\nsome checks failed')
            return 0 if d['ok'] else 1
        elif cmd == 'probe':
            _print(probe(rest[0]))
        elif cmd == 'launch':
            only = None
            if '--only' in rest:
                only = rest[rest.index('--only') + 1].split(',')
            _print(launch(rest[0], only=only, gate='--no-gate' not in rest))
        elif cmd == 'stop':
            _print(stop(rest[0], hard='--hard' in rest))
        elif cmd == 'status':
            _print(overview(with_disk='--disk' in rest))
        elif cmd == 'backup':
            _print(backup(rest[0]))
        elif cmd == 'restore':
            _print(restore(rest[0], rest[1]))
        elif cmd == 'sweep':
            _print(sweep())
        elif cmd == 'totp':
            _print(totp(rest[0], rest[1]))
        elif cmd == 'set-secret':
            seed = sys.stdin.read().strip()
            set_secret(rest[0], rest[1], seed)
            _print({'ok': True, 'stored': f'{rest[0]}/{rest[1]}'})
        else:
            print(f'unknown command {cmd!r} — see --help', file=sys.stderr)
            return 2
    except (KeyError, ValueError, IndexError, RuntimeError) as e:
        print(f'error: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
