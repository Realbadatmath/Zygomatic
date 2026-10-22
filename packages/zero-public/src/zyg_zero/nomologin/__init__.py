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

# nomologin.py became this package on 2026-10-07; every section moved verbatim. The import
# path is unchanged (`from zyg_zero import nomologin as nl`), and the original top import
# block is re-done here so attribute accesses like nomologin.os / nomologin.np still work.
import base64
import binascii
import hashlib
import hmac
import json
import logging as _zyg_logging
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone

from zyg_zero import nomologin_proxy as np
from zyg_zero import nomologin_sites as ns

# Submodules in the original section order, so module-level side effects (constants.py's
# hard nomologin_sites import) still run in that order.
from zyg_zero.nomologin import constants as constants
from zyg_zero.nomologin import manifest as manifest
from zyg_zero.nomologin import profile as profile
from zyg_zero.nomologin import launching as launching
from zyg_zero.nomologin import reporting as reporting
from zyg_zero.nomologin import cli as cli
from zyg_zero.nomologin.constants import (
    CACHE_ROOT,
    CHROME,
    DEBUG_PORT_BASE,
    DEBUG_PORT_SPAN,
    DISK_CACHE_BYTES,
    HERE,
    ID_RE,
    KEYFILE,
    LOGS,
    MANIFEST,
    MAX_TABS,
    PLATFORM_GROUPS,
    PLATFORMS,
    PROFILES,
    ROOT,
    SECRETS,
    SHIM_PORT_BASE,
    SHIM_PORT_SPAN,
    STATE,
    BACKUPS,
    _alive,
    _cmdline,
    _du,
    _fernet,
    _human,
    _iso,
    _now,
    _port_free,
    _port_listening,
    _read_json,
    _write_json,
    _zyg_log,
    get_secret,
    set_secret,
    totp,
)
from zyg_zero.nomologin.manifest import (
    _set_state,
    _slug,
    _state,
    add_persona,
    cache_dir,
    cookie_age_days,
    debug_port,
    get_persona,
    load_manifest,
    profile_dir,
    save_manifest,
    shim_port,
    target_urls,
    validate,
)
from zyg_zero.nomologin.profile import (
    _SEED_PREFS,
    _direct_ip_cache,
    _sk_color,
    THEME_VARIANT_VIBRANT,
    apply_theme,
    clear_singleton,
    direct_ip,
    ensure_profile,
    probe,
    shim_running,
    start_shim,
    stop_shim,
)
from zyg_zero.nomologin.launching import (
    _log_tail,
    _reopen,
    chrome_argv,
    chrome_running,
    gui_env,
    launch,
    stop,
    x_display,
)
from zyg_zero.nomologin.reporting import (
    _SKIP,
    _zones,
    SAMPLE,
    backup,
    describe,
    doctor,
    init,
    overview,
    restore,
    sweep,
)
from zyg_zero.nomologin.cli import _print, _table, main

# ── re-export surface ────────────────────────────────────────────────────────
# Every name the single nomologin.py defined, so attribute access on this module
# keeps resolving after the split. Declaring them is what makes the re-export
# deliberate rather than an unused import; nothing does ``import *`` from here,
# so __all__ changes no behaviour.
__all__ = [
    'base64',
    'binascii',
    'hashlib',
    'hmac',
    'json',
    '_zyg_logging',
    'os',
    're',
    'shutil',
    'socket',
    'struct',
    'subprocess',
    'sys',
    'tarfile',
    'time',
    'datetime',
    'timezone',
    'np',
    'ns',
    'constants',
    'manifest',
    'profile',
    'launching',
    'reporting',
    'cli',
    'CACHE_ROOT',
    'CHROME',
    'DEBUG_PORT_BASE',
    'DEBUG_PORT_SPAN',
    'DISK_CACHE_BYTES',
    'HERE',
    'ID_RE',
    'KEYFILE',
    'LOGS',
    'MANIFEST',
    'MAX_TABS',
    'PLATFORM_GROUPS',
    'PLATFORMS',
    'PROFILES',
    'ROOT',
    'SECRETS',
    'SHIM_PORT_BASE',
    'SHIM_PORT_SPAN',
    'STATE',
    'BACKUPS',
    '_alive',
    '_cmdline',
    '_du',
    '_fernet',
    '_human',
    '_iso',
    '_now',
    '_port_free',
    '_port_listening',
    '_read_json',
    '_write_json',
    '_zyg_log',
    'get_secret',
    'set_secret',
    'totp',
    '_set_state',
    '_slug',
    '_state',
    'add_persona',
    'cache_dir',
    'cookie_age_days',
    'debug_port',
    'get_persona',
    'load_manifest',
    'profile_dir',
    'save_manifest',
    'shim_port',
    'target_urls',
    'validate',
    '_SEED_PREFS',
    '_direct_ip_cache',
    '_sk_color',
    'THEME_VARIANT_VIBRANT',
    'apply_theme',
    'clear_singleton',
    'direct_ip',
    'ensure_profile',
    'probe',
    'shim_running',
    'start_shim',
    'stop_shim',
    '_log_tail',
    '_reopen',
    'chrome_argv',
    'chrome_running',
    'gui_env',
    'launch',
    'stop',
    'x_display',
    '_SKIP',
    '_zones',
    'SAMPLE',
    'backup',
    'describe',
    'doctor',
    'init',
    'overview',
    'restore',
    'sweep',
    '_print',
    '_table',
    'main',
]
