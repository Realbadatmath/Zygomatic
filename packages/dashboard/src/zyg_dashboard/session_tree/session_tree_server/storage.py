# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Config loading, tree JSON storage and the audit log.

Moved verbatim from session_tree_server.py lines 129-219.
"""

from ._base import (
    ACTIVE,
    AUDIT,
    CONFIG_PATH,
    DEFAULT_CONFIG,
    FINISHED,
    PLANNED,
    SUGGESTED,
    _zyg_log,
    glob,
    json,
    os,
    re,
    time,
)


# ───────────────────────────── config / storage ──────────────────────────────


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH) as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        _zyg_log.info(f'[session-tree] config.json unreadable ({e}); using defaults')
    # config.json ships a ~-relative default so no operator's home is baked into the file.
    cfg['spawn_cwd_default'] = os.path.expanduser(cfg['spawn_cwd_default'])
    return cfg


CFG = load_config()

for d in (ACTIVE, PLANNED, FINISHED, SUGGESTED):
    os.makedirs(d, exist_ok=True)


def now():
    return time.time()


def iso(ts):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))


def _tree_path(tree_id, folder=ACTIVE):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', tree_id or ''):
        return None
    return os.path.join(folder, tree_id + '.json')


def load_tree(tree_id, folder=ACTIVE):
    p = _tree_path(tree_id, folder)
    if not p or not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def save_tree(tree, folder=ACTIVE):
    p = _tree_path(tree['id'], folder)
    tmp = p + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(tree, f, indent=1)
    os.replace(tmp, p)


def list_trees(folder=ACTIVE):
    out = []
    for p in sorted(glob.glob(os.path.join(folder, '*.json'))):
        try:
            with open(p) as f:
                out.append(json.load(f))
        except (OSError, ValueError) as _exc:
            _zyg_log.warning('tree %s unreadable, it is missing from the board listing: %s', p, _exc)
            continue
    out.sort(key=lambda t: t.get('created_at', 0))
    return out


def audit(event):
    event['ts'] = now()
    with open(AUDIT, 'a') as f:
        f.write(json.dumps(event) + '\n')


def audit_tail(n=80):
    try:
        with open(AUDIT, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 200_000))
            lines = f.read().decode('utf-8', 'replace').splitlines()
    except FileNotFoundError:
        return []
    out = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except ValueError as _exc:
            _zyg_log.debug('malformed audit line skipped: %s', _exc)
    return out
