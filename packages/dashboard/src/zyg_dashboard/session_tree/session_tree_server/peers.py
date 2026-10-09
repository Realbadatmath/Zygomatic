# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Live peer discovery, operator notifications, archive/promote of trees.

Moved verbatim from session_tree_server.py lines 220-432.
"""

from ._base import ACTIVE, DATA, FINISHED, PLANNED, SUGGESTED, _zyg_log, glob, json, os, shutil, subprocess
from .storage import CFG, _tree_path, audit, iso, list_trees, now, save_tree

# Resolved on first call, not on import: spawner.kick_spawner is defined after this
# section in the original file, so importing it here would close a cycle.


def kick_spawner(*args, **kwargs):
    from .spawner import kick_spawner as _impl

    return _impl(*args, **kwargs)


# ───────────────────────────── peers / notify ────────────────────────────────

NOTIFY = os.path.join(DATA, 'notify')
os.makedirs(NOTIFY, exist_ok=True)
_peers_cache = {'at': 0, 'val': []}


def _claude_bin():
    for c in (CFG.get('claude_bin'), os.environ.get('CLAUDE_CODE_EXECPATH'), shutil.which('claude')):
        if c and os.path.exists(c):
            return c
    hits = sorted(
        glob.glob(
            os.path.expanduser('~/.vscode-server/extensions/anthropic.claude-code-*/resources/native-binary/claude')
        )
    )
    return hits[-1] if hits else None


def live_peers():
    """[{sessionId, name, pid, cwd, kind}] from `claude agents --json` (cached 20 s)."""
    if now() - _peers_cache['at'] < 20:
        return _peers_cache['val']
    out = []
    b = _claude_bin()
    if b:
        try:
            r = subprocess.run([b, 'agents', '--json'], capture_output=True, text=True, timeout=15)
            out = json.loads(r.stdout or '[]')
        except Exception as e:
            _zyg_log.info(f'[session-tree] claude agents --json failed: {e}')
    _peers_cache.update(at=now(), val=out)
    return out


def peer_for(session_id):
    for r in live_peers():
        if r.get('sessionId') == session_id:
            return {'name': r.get('name'), 'pid': r.get('pid'), 'cwd': r.get('cwd'), 'alive': True}
    return {'name': None, 'pid': None, 'cwd': None, 'alive': False}


def operator_notify(title, body, tree_id='', task_id=None):
    """Desktop notification to the operator (notify-send on the login's X session).
    Used ONLY when a tree archives or a task fails and no creator session is alive
    to be woken — the case where the review request would otherwise sit unseen
    in notify/ until somebody happens to run `st status` (2026-09-23)."""
    if not CFG.get('operator_notify', True):
        return False
    env = dict(os.environ)
    env.setdefault('DISPLAY', ':0')
    env.setdefault('DBUS_SESSION_BUS_ADDRESS', 'unix:path=/run/user/%d/bus' % os.getuid())
    try:
        subprocess.Popen(
            ['notify-send', '-a', 'Session Tree', '-u', 'critical', '-i', 'dialog-warning', title[:120], body[:800]],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        ok, err = True, title[:200]
    except Exception as e:  # no notify-send / no display: the notice file still exists
        ok, err = False, 'notify-send failed: %s' % e
    audit({'cmd': 'notify:operator', 'tree': tree_id, 'task': task_id, 'ok': ok, 'model': 'board', 'error': err})
    return ok


def archive_tree(tree, by, note=''):
    """Move an active tree to finished/ and leave a review request for its creator."""
    t = now()
    tree['status'] = 'finished'
    tree['finished_at'] = t
    start = tree.get('activated_at') or tree.get('created_at') or t
    if tree.get('eta_minutes'):
        actual = (t - start) / 60
        tree['eta_result'] = {
            'eta_minutes': tree['eta_minutes'],
            'actual_minutes': round(actual, 1),
            'ratio': round(actual / tree['eta_minutes'], 2),
        }
        audit(
            {
                'cmd': 'eta:result',
                'tree': tree['id'],
                'ok': True,
                'model': 'metrics',
                'error': 'ETA %g min, actual %.1f min, ratio %.2f'
                % (tree['eta_minutes'], actual, actual / tree['eta_minutes']),
            }
        )
    if by:
        tree['closed_by'] = by
    if note:
        tree['close_note'] = note[:1000]
    save_tree(tree, FINISHED)
    for folder in (ACTIVE, PLANNED):
        p = _tree_path(tree['id'], folder)
        if p and os.path.exists(p):
            os.remove(p)
    counts = {}
    for x in tree['tasks']:
        counts[x['status']] = counts.get(x['status'], 0) + 1
    creator = tree.get('created_by') or {}
    peer = peer_for(creator.get('session_id'))
    notice = {
        'tree': tree['id'],
        'title': tree['title'],
        'finished_at': t,
        'by': by,
        'counts': counts,
        'creator': creator,
        'creator_peer': peer,
        'reviewed': False,
        'reviewed_at': None,
    }
    with open(os.path.join(NOTIFY, tree['id'] + '.json'), 'w') as f:
        json.dump(notice, f, indent=1)
    audit(
        {
            'cmd': 'archive',
            'tree': tree['id'],
            'ok': True,
            'model': by,
            'error': 'creator %s peer=%s alive=%s' % (creator.get('model'), peer['name'], peer['alive']),
        }
    )
    if not peer['alive']:
        c = ' '.join('%s=%d' % kv for kv in sorted(counts.items()))
        operator_notify(
            'Session Tree: %s archived, nobody to review it' % tree['id'][-6:],
            '%s\n%s (by %s). The creator session %s is not running, so no agent was woken. '
            'Open a Fable session and run: st review %s'
            % (tree['title'][:160], c, by, (creator.get('session_id') or '')[:8], tree['id']),
            tree_id=tree['id'],
        )
    promote_planned('auto (%s archived)' % tree['id'])
    return notice


def planned_trees():
    """Planned trees, oldest first — position 1 is the next to activate."""
    return list_trees(PLANNED)


def suggested_trees():
    """Modularization trees a creator filed with `st suggest`, oldest first.
    They are invisible to executors and to the planned queue until the
    operator accepts one in the Modularization tab."""
    return sorted(list_trees(SUGGESTED), key=lambda t: t.get('created_at') or 0)


def activate_tree(tree, by):
    """Move a planned tree to active/. Its tasks are untouched: all todo, so the
    first `st next` after this finds them."""
    t = now()
    tree['status'] = 'active'
    tree['activated_at'] = t
    tree['activated_by'] = by
    save_tree(tree, ACTIVE)
    p = _tree_path(tree['id'], PLANNED)
    if p and os.path.exists(p):
        os.remove(p)
    audit(
        {
            'cmd': 'activate',
            'tree': tree['id'],
            'ok': True,
            'model': by,
            'error': 'planned since %s, %d task(s)' % (iso(tree.get('created_at') or 0), len(tree['tasks'])),
        }
    )
    kick_spawner()
    return tree


def promote_planned(by='auto'):
    """If nothing is active, the oldest planned tree becomes active. Called
    after every archive/delete and on each status/next/UI poll as a safety
    net, so a missed promotion never leaves executors idle. Returns the
    promoted tree or None."""
    if list_trees(ACTIVE):
        return None
    planned = planned_trees()
    if not planned:
        return None
    return activate_tree(planned[0], by)


def pending_notices(creator_session=None):
    out = []
    for p in sorted(glob.glob(os.path.join(NOTIFY, '*.json'))):
        try:
            with open(p) as f:
                n = json.load(f)
        except (OSError, ValueError) as _exc:
            _zyg_log.warning('notice %s unreadable, skipped: %s', p, _exc)
            continue
        if n.get('reviewed'):
            continue
        if creator_session and (n.get('creator') or {}).get('session_id') != creator_session:
            n = dict(n, other_creator=True)
        out.append(n)
    return out


def notice_for(tree_id):
    p = os.path.join(NOTIFY, tree_id + '.json') if _tree_path(tree_id) else None
    if p and os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return None
