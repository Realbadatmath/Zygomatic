# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import logging as _zyg_logging
import os
import shutil
import subprocess
import tarfile
from datetime import datetime

from zyg_zero import nomologin_proxy as np
from zyg_zero import nomologin_sites as ns
from zyg_zero.nomologin.constants import (
    BACKUPS,
    CACHE_ROOT,
    CHROME,
    DISK_CACHE_BYTES,
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
    _du,
    _human,
    _iso,
    _now,
    _read_json,
    _write_json,
)
from zyg_zero.nomologin.launching import chrome_running, x_display
from zyg_zero.nomologin.manifest import (
    _state,
    cache_dir,
    cookie_age_days,
    load_manifest,
    profile_dir,
    validate,
)
from zyg_zero.nomologin.profile import direct_ip, shim_running

_zyg_log = _zyg_logging.getLogger('zyg_zero.nomologin')


# ── reporting ─────────────────────────────────────────────────────────────────────────
def describe(p: dict, with_disk: bool = True) -> dict:
    pid = p.get('id') or '?'
    problems = validate(p)
    prof = profile_dir(pid)
    exists = os.path.exists(prof)
    age = cookie_age_days(pid) if exists else None
    row = _state().get(pid, {})
    cpid = chrome_running(pid) if ID_RE.match(str(pid)) else None
    targets = []
    for t in p.get('targets', []):
        plat = t.get('platform', '?')
        meta = PLATFORMS.get(plat, {})
        targets.append(
            {
                'platform': plat,
                'label': meta.get('label', plat.title()),
                'handle': t.get('handle'),
                'url': t.get('url') or meta.get('compose'),
                'enabled': t.get('enabled', True),
                'group': meta.get('group'),
                'policy': meta.get('policy'),
                'has_totp': bool((_read_json(SECRETS, {}).get(pid) or {}).get(plat)),
            }
        )
    return {
        'id': pid,
        'label': p.get('label', pid),
        'color': p.get('color', '#8b5cf6'),
        'note': p.get('note'),
        'problems': problems,
        'targets': targets,
        'proxy': np.Upstream(p['proxy']).safe if p.get('proxy') and not problems else None,
        'proxy_configured': bool(p.get('proxy')),
        'timezone': p.get('timezone'),
        'profile_exists': exists,
        'logged_in_ever': age is not None,
        'cookie_age_days': round(age, 1) if age is not None else None,
        'stale': bool(age is not None and age > 30),
        'disk': _du(prof) if (with_disk and exists) else None,
        'cache': _du(cache_dir(pid)) if (with_disk and os.path.exists(cache_dir(pid))) else None,
        'running': bool(cpid),
        'chrome_pid': cpid,
        'shim_running': shim_running(pid),
        'shim_port': row.get('shim_port'),
        'last_launch': _iso(row.get('last_launch')),
        'last_probe': row.get('last_probe'),
    }


def _zones() -> list[str]:
    """The zoneinfo names the add form offers. A persona's clock must agree with the
    address it is reached from, so this is a real field, not decoration."""
    common = [
        'Europe/Amsterdam',
        'Europe/London',
        'Europe/Berlin',
        'Europe/Paris',
        'Europe/Madrid',
        'America/New_York',
        'America/Chicago',
        'America/Denver',
        'America/Los_Angeles',
        'America/Sao_Paulo',
        'Asia/Tokyo',
        'Asia/Singapore',
        'Asia/Dubai',
        'Australia/Sydney',
        'UTC',
    ]
    return [z for z in common if os.path.exists(os.path.join('/usr/share/zoneinfo', z))]


def overview(with_disk: bool = True) -> dict:
    personas = [describe(p, with_disk) for p in load_manifest()]
    return {
        'root': ROOT,
        'cache_root': CACHE_ROOT,
        'chrome': CHROME,
        'chrome_ok': os.path.exists(CHROME),
        'host_ip': direct_ip(),
        'platforms': [
            {
                'key': k,
                'label': v['label'],
                'group': v.get('group', 'Core'),
                'policy': v.get('policy', 'ok'),
                'home': v.get('home'),
            }
            for k, v in PLATFORMS.items()
        ],
        'platform_groups': PLATFORM_GROUPS,
        'policy_note': ns.POLICY_NOTE,
        'max_tabs': MAX_TABS,
        'zones': _zones(),
        'personas': personas,
        'totals': {
            'count': len(personas),
            'running': sum(1 for p in personas if p['running']),
            'proxied': sum(1 for p in personas if p['proxy_configured']),
            'broken': sum(1 for p in personas if p['problems']),
            'stale': sum(1 for p in personas if p['stale']),
            'never_logged_in': sum(1 for p in personas if not p['logged_in_ever']),
            'disk': sum(p['disk'] or 0 for p in personas),
            'cache': sum(p['cache'] or 0 for p in personas),
        },
        'generated': _iso(_now()),
    }


def doctor() -> dict:
    """Pre-flight. Everything that would make a launch fail or leak, measured not assumed."""
    checks = []

    def add(name, ok, detail):
        checks.append({'check': name, 'ok': bool(ok), 'detail': detail})

    add('chrome binary', os.path.exists(CHROME), CHROME)
    if os.path.exists(CHROME):
        try:
            v = subprocess.run([CHROME, '--version'], capture_output=True, text=True, timeout=20).stdout.strip()
        except (OSError, subprocess.SubprocessError) as e:
            v = f'could not run: {e}'
        add('chrome version', 'Chrome' in v, v)
    disp = x_display()
    add(
        'X display',
        bool(disp),
        (
            f'{disp} — windows can open'
            if disp
            else 'none: no desktop session reachable from this process, so Chrome would exit at '
            'once. Started by restart_api without DISPLAY, or nobody is logged in at the screen.'
        ),
    )
    add('root writable', os.access(os.path.dirname(ROOT) or '/', os.W_OK), ROOT)
    add('manifest present', os.path.exists(MANIFEST), MANIFEST)

    free = shutil.disk_usage(os.path.dirname(ROOT) or '/').free
    add(
        'disk headroom',
        free > 20 * 1024**3,
        f'{_human(free)} free — a profile runs 50-150 MB, its cache up to {_human(DISK_CACHE_BYTES)}',
    )

    ip = direct_ip()
    add('host egress IP', bool(ip), ip or 'could not determine — proxy leak checks will not be able to compare')

    if os.path.exists(KEYFILE):
        add('secrets.key mode', (os.stat(KEYFILE).st_mode & 0o077) == 0, oct(os.stat(KEYFILE).st_mode & 0o777))
    try:
        from cryptography.fernet import Fernet  # noqa: F401

        add('cryptography', True, 'available — TOTP seeds can be stored encrypted')
    except ImportError:
        add('cryptography', False, 'missing — TOTP storage unavailable')

    personas = load_manifest()
    add('personas parse', True, f'{len(personas)} in the manifest')
    for p in personas:
        bad = validate(p)
        add(f'persona {p.get("id", "?")}', not bad, '; '.join(bad) or 'sound')
    seen: dict = {}
    for p in personas:
        seen.setdefault(p.get('id'), 0)
        seen[p['id']] += 1
    dupes = [k for k, v in seen.items() if v > 1]
    add('unique ids', not dupes, f'duplicated: {dupes}' if dupes else 'all distinct')

    return {'ok': all(c['ok'] for c in checks), 'checks': checks, 'generated': _iso(_now())}


# ── backup / restore / sweep ──────────────────────────────────────────────────────────
# Regenerated caches, never worth storing, and they are most of the bytes.
_SKIP = {
    'Cache',
    'Code Cache',
    'GPUCache',
    'ShaderCache',
    'GrShaderCache',
    'DawnCache',
    'DawnGraphiteCache',
    'DawnWebGPUCache',
    'component_crx_cache',
    'optimization_guide_model_store',
    'Crashpad',
    'Safe Browsing',
    'segmentation_platform',
    'Service Worker',
}


def backup(pid: str) -> dict:
    """Snapshot a profile. Do this right after the first login of each platform: losing a
    profile means redoing every 2FA enrolment for that persona."""
    prof = profile_dir(pid)
    if not os.path.exists(prof):
        return {'ok': False, 'error': f'no profile for {pid!r} yet'}
    if chrome_running(pid):
        return {
            'ok': False,
            'error': 'close this persona first — a cookie jar copied while Chrome holds it open can restore corrupt',
        }
    os.makedirs(BACKUPS, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    out = os.path.join(BACKUPS, f'{pid}-{stamp}.tar.gz')

    def keep(info: tarfile.TarInfo):
        parts = set(info.name.split('/'))
        return None if parts & _SKIP else info

    with tarfile.open(out, 'w:gz') as tar:
        tar.add(prof, arcname=pid, filter=keep)
    os.chmod(out, 0o600)
    return {'ok': True, 'archive': out, 'size': os.path.getsize(out), 'human': _human(os.path.getsize(out))}


def restore(pid: str, archive: str) -> dict:
    if chrome_running(pid):
        return {'ok': False, 'error': 'close this persona first'}
    if not os.path.exists(archive):
        return {'ok': False, 'error': f'{archive} not found'}
    prof = profile_dir(pid)
    if os.path.exists(prof):
        aside = f'{prof}.replaced-{datetime.now().strftime("%Y%m%d-%H%M%S")}'
        os.rename(prof, aside)
    else:
        aside = None
    os.makedirs(PROFILES, exist_ok=True)
    with tarfile.open(archive, 'r:gz') as tar:
        members = [m for m in tar.getmembers() if not m.name.startswith('/') and '..' not in m.name.split('/')]
        # filter='data' is the second half of the guard: the comprehension above drops absolute
        # and traversing names, and the filter refuses links, devices and permission bits that
        # would let an archive escape PROFILES or come back with more rights than it went in.
        tar.extractall(PROFILES, members=members, filter='data')
    extracted = os.path.join(PROFILES, os.path.basename(archive).rsplit('-', 2)[0])
    if extracted != prof and os.path.exists(extracted):
        os.rename(extracted, prof)
    return {'ok': True, 'restored': prof, 'previous_kept_at': aside}


def sweep(idle_days: float = 7.0) -> dict:
    """Drop disk caches for personas nobody has opened lately. Caches regenerate; on a box
    at 93% of 1.8 T they are not worth holding for an idle identity."""
    freed, hit = 0, []
    for p in load_manifest():
        pid = p.get('id')
        if not pid or chrome_running(pid):
            continue
        last = _state().get(pid, {}).get('last_launch') or 0
        if _now() - last < idle_days * 86400:
            continue
        cd = cache_dir(pid)
        if os.path.exists(cd):
            size = _du(cd)
            shutil.rmtree(cd, ignore_errors=True)
            os.makedirs(cd, exist_ok=True)
            freed += size
            hit.append({'id': pid, 'freed': size, 'human': _human(size)})
    return {'ok': True, 'freed': freed, 'human': _human(freed), 'personas': hit}


# ── scaffold ──────────────────────────────────────────────────────────────────────────
SAMPLE = {
    '_readme': 'Nomologin persona manifest. One entry per brand. `id` is permanent — it '
    'names the profile directory that holds the logged-in sessions, so renaming '
    'it orphans every login. Omit `url` on a target to use the platform default '
    'composer. Set `proxy` to socks5://user:pass@host:port for a dedicated exit '
    'IP; leave it null to post from this machine.',
    'personas': [
        {
            'id': 'zygomatic',
            'label': 'Zygomatic Ai',
            'color': '#8b5cf6',
            'note': 'Main studio brand.',
            'proxy': None,
            'timezone': 'Europe/Amsterdam',
            'targets': [
                {'platform': 'x', 'handle': '@zygomaticai'},
                {'platform': 'facebook', 'handle': 'Zygomatic Ai'},
                {'platform': 'instagram', 'handle': 'zygomatic.ai'},
                {'platform': 'threads', 'handle': 'zygomatic.ai'},
                {'platform': 'youtube', 'handle': 'Zygomatic'},
            ],
        },
    ],
}


def init() -> dict:
    made = []
    for d in (ROOT, PROFILES, BACKUPS, LOGS, CACHE_ROOT):
        if not os.path.exists(d):
            os.makedirs(d, exist_ok=True)
            made.append(d)
    try:
        os.chmod(ROOT, 0o700)
    except OSError as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    if not os.path.exists(MANIFEST):
        _write_json(MANIFEST, SAMPLE)
        made.append(MANIFEST)
    return {'ok': True, 'root': ROOT, 'created': made, 'next': f'edit {MANIFEST}, then: python3 nomologin.py doctor'}
