# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import hashlib
import os
import re

from zyg_zero import nomologin_proxy as np
from zyg_zero.nomologin.constants import (
    CACHE_ROOT,
    DEBUG_PORT_BASE,
    DEBUG_PORT_SPAN,
    ID_RE,
    MANIFEST,
    PLATFORMS,
    PROFILES,
    SHIM_PORT_BASE,
    SHIM_PORT_SPAN,
    STATE,
    _now,
    _port_free,
    _read_json,
    _write_json,
)


# ── manifest ──────────────────────────────────────────────────────────────────────────
def load_manifest() -> list[dict]:
    raw = _read_json(MANIFEST, None)
    if raw is None:
        return []
    personas = raw.get('personas', raw) if isinstance(raw, dict) else raw
    if not isinstance(personas, list):
        raise ValueError('personas.json must hold a list, or {"personas": [...]}')
    return personas


def validate(p: dict) -> list[str]:
    """Return the reasons this persona cannot be launched. Empty list means it is sound.

    Nothing here infers a default for a field that is wrong — a broken persona is shown as
    a broken card naming the reason, never silently repaired.
    """
    bad = []
    pid = p.get('id')
    if not isinstance(pid, str) or not ID_RE.match(pid):
        bad.append('id must be lowercase a-z0-9_- , 1-32 chars')
    if not p.get('label'):
        bad.append('label is required')
    targets = p.get('targets')
    if not isinstance(targets, list) or not targets:
        bad.append('targets must be a non-empty list')
    else:
        for i, t in enumerate(targets):
            if not isinstance(t, dict) or not t.get('platform'):
                bad.append(f'targets[{i}] needs a platform')
                continue
            if not (t.get('url') or PLATFORMS.get(t['platform'])):
                bad.append(f'targets[{i}]: unknown platform {t["platform"]!r} and no url')
    proxy = p.get('proxy')
    if proxy:
        try:
            np.Upstream(proxy)
        except ValueError as e:
            bad.append(f'proxy: {e}')
    colour = p.get('color', '#8b5cf6')
    if not re.match(r'^#[0-9a-fA-F]{6}$', str(colour)):
        bad.append('color must be #rrggbb')
    tz = p.get('timezone')
    if tz and not os.path.exists(os.path.join('/usr/share/zoneinfo', tz)):
        bad.append(f'timezone {tz!r} is not a zoneinfo name')
    return bad


def get_persona(persona_id: str) -> dict:
    for p in load_manifest():
        if p.get('id') == persona_id:
            return p
    raise KeyError(f'no persona {persona_id!r} in {MANIFEST}')


def save_manifest(personas: list[dict]) -> None:
    """Rewrite personas.json, keeping whatever else the document holds (the _readme)."""
    raw = _read_json(MANIFEST, None)
    doc = dict(raw) if isinstance(raw, dict) and 'personas' in raw else {}
    doc['personas'] = personas
    _write_json(MANIFEST, doc)


def _slug(text: str) -> str:
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', text.lower())).strip('-')[:32]


def add_persona(spec: dict) -> dict:
    """Append one account to the manifest. Validates first, and never merges.

    `id` names the profile directory that holds that account's logged-in sessions, so
    reusing an existing id would silently point a new brand at another brand's cookie jar.
    That is refused, not resolved. Nothing here is written unless the whole persona is
    sound, so a rejected form leaves the manifest exactly as it was.
    """
    label = str(spec.get('label') or '').strip()
    pid = _slug(str(spec.get('id') or '') or label)
    p = {
        'id': pid,
        'label': label,
        'color': str(spec.get('color') or '#8b5cf6').strip().lower(),
        'note': str(spec.get('note') or '').strip(),
        'proxy': str(spec.get('proxy') or '').strip() or None,
        'timezone': str(spec.get('timezone') or '').strip() or None,
        'targets': [],
    }
    for t in spec.get('targets') or []:
        if not isinstance(t, dict):
            continue
        plat = str(t.get('platform') or '').strip().lower()
        if not plat:
            continue
        tgt = {'platform': plat, 'handle': str(t.get('handle') or '').strip()}
        if t.get('url'):
            tgt['url'] = str(t['url']).strip()
        p['targets'].append(tgt)

    problems = []
    if not label:
        problems.append('give the account a name')
    existing = load_manifest()
    if pid and any(x.get('id') == pid for x in existing):
        problems.append(
            f"id {pid!r} is already taken — it names the folder holding that account's logins, so it cannot be shared"
        )
    if not p['targets']:
        problems.append('tick at least one platform')
    extra = [x for x in validate(p) if 'targets must be' not in x]
    if not label:
        # "give the account a name" already says it; the id and label rules are the same
        # complaint in the manifest's vocabulary, and three lines read like three faults.
        extra = [x for x in extra if not x.startswith('id must be') and x != 'label is required']
    problems += extra
    if problems:
        return {'ok': False, 'error': '; '.join(problems), 'problems': problems}

    # An explicit "proxy": null is kept — the manifest is hand-editable and the _readme
    # tells the operator what to put there.
    existing.append({k: v for k, v in p.items() if v != ''})
    save_manifest(existing)
    return {
        'ok': True,
        'id': pid,
        'label': label,
        'note': f'{label} added — open it and sign in by hand once per platform',
    }


def target_urls(p: dict, only: list[str] | None = None) -> list[str]:
    urls = []
    for t in p.get('targets', []):
        plat = t.get('platform')
        if only and plat not in only:
            continue
        if t.get('enabled') is False:
            continue
        url = t.get('url') or (PLATFORMS.get(plat, {}) or {}).get('compose')
        if url:
            urls.append(url)
    return urls


# ── paths and state ───────────────────────────────────────────────────────────────────
def profile_dir(pid: str) -> str:
    return os.path.join(PROFILES, pid)


def cache_dir(pid: str) -> str:
    return os.path.join(CACHE_ROOT, pid)


def shim_port(pid: str) -> int:
    """Deterministic per persona, so a port never silently moves between launches and the
    board can name it before anything is running. Collisions walk forward."""
    h = int(hashlib.sha256(pid.encode()).hexdigest()[:8], 16)
    start = SHIM_PORT_BASE + (h % SHIM_PORT_SPAN)
    taken = {v.get('shim_port') for k, v in _state().items() if isinstance(v, dict) and k != pid}
    for i in range(SHIM_PORT_SPAN):
        port = SHIM_PORT_BASE + ((start - SHIM_PORT_BASE + i) % SHIM_PORT_SPAN)
        if port not in taken and (_port_free(port) or _state().get(pid, {}).get('shim_port') == port):
            return port
    raise RuntimeError('no free shim port in the 41000-41199 range')


def debug_port(pid: str) -> int:
    """Deterministic per persona, collisions walk forward — the same contract as shim_port,
    so the board can name the port before anything is running."""
    h = int(hashlib.sha256(('cdp:' + pid).encode()).hexdigest()[:8], 16)
    start = DEBUG_PORT_BASE + (h % DEBUG_PORT_SPAN)
    taken = {v.get('debug_port') for k, v in _state().items() if isinstance(v, dict) and k != pid}
    current = _state().get(pid, {}).get('debug_port')
    for i in range(DEBUG_PORT_SPAN):
        port = DEBUG_PORT_BASE + ((start - DEBUG_PORT_BASE + i) % DEBUG_PORT_SPAN)
        if port not in taken and (_port_free(port) or current == port):
            return port
    raise RuntimeError('no free debug port in the 42000-42199 range')


def _state() -> dict:
    return _read_json(STATE, {})


def _set_state(pid: str, **kw) -> dict:
    st = _state()
    row = st.setdefault(pid, {})
    row.update(kw)
    _write_json(STATE, st)
    return row


def cookie_age_days(pid: str) -> float | None:
    """Days since this profile's cookie jar was last written. Sessions expire silently, so
    the board shows this: you want to learn a persona has gone stale before a posting day,
    not during one. None means it has never been logged in."""
    prof = profile_dir(pid)
    for rel in ('Default/Network/Cookies', 'Default/Cookies'):
        path = os.path.join(prof, rel)
        if os.path.exists(path):
            return (_now() - os.path.getmtime(path)) / 86400.0
    return None
