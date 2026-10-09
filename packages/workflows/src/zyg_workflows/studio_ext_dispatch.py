# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Server-side ops of the studio extensions (2026-09-18).

studio_ext_server/<mod>.py exports ROUTES = {op: fn(payload: dict, method: str)}.
fn returns a dict (sent as JSON; {'error':..., 'code':...} sets the status) or a
tuple (bytes, mime, filename) that the server sends as a download. A module is
reloaded when its file changes, so a new op lands without a server restart.

This mirrors architecture_studio.ext_module/ext_families/ext_dispatch, but over
studio_ext_server/ and addressed as /inspect/api/studio/<mod>/<op>.
"""

import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
_EXT_DIR = os.path.join(HERE, 'studio_ext_server')
_EXT_MODS: dict = {}
_EXT_NAME = re.compile(r'^[a-z][a-z0-9_]{0,40}$')


def ext_module(mod: str):
    if not _EXT_NAME.match(mod or ''):
        raise ValueError('bad module name')
    path = os.path.join(_EXT_DIR, mod + '.py')
    if not os.path.isfile(path):
        return None
    mtime = os.path.getmtime(path)
    hit = _EXT_MODS.get(mod)
    if hit and hit[0] == mtime:
        return hit[1]
    import importlib.util

    spec = importlib.util.spec_from_file_location('studio_ext_server.' + mod, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    _EXT_MODS[mod] = (mtime, m)
    return m


def ext_mods() -> dict:
    """{mod: [ops]} for every studio_ext_server/*.py that imports."""
    out: dict = {}
    if not os.path.isdir(_EXT_DIR):
        return out
    for f in sorted(os.listdir(_EXT_DIR)):
        if not f.endswith('.py') or f.startswith('_'):
            continue
        name = f[:-3]
        try:
            m = ext_module(name)
            out[name] = sorted((getattr(m, 'ROUTES', {}) or {}).keys())
        except Exception as e:  # noqa: BLE001
            out[name] = ['ERROR: %s' % (str(e)[:120],)]
    return out


def dispatch(method: str, rest: str, payload: dict):
    """'<mod>/<op>' -> the op's result. Unknown mod/op -> {'error', 'code': 404}."""
    parts = (rest or '').strip('/').split('/')
    if len(parts) == 1 and parts[0] == '':
        return {'ok': True, 'mods': ext_mods()}
    if len(parts) != 2:
        return {'error': 'use /inspect/api/studio/<mod>/<op>', 'code': 404}
    mod, op = parts
    if not _EXT_NAME.match(mod) or not _EXT_NAME.match(op):
        return {'error': 'bad module or op name', 'code': 404}
    m = ext_module(mod)
    if m is None:
        return {'error': f'no studio extension {mod}', 'code': 404}
    fn = (getattr(m, 'ROUTES', {}) or {}).get(op)
    if fn is None:
        return {'error': f'{mod} has no op {op}', 'code': 404}
    return fn(payload if isinstance(payload, dict) else {}, method)
