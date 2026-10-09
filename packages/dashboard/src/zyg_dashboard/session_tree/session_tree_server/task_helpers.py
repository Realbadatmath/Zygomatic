# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Lease sweep, claimability, task rows and task validation.

Moved verbatim from session_tree_server.py lines 613-757.
"""

from ._base import FINISHED, _zyg_log, glob, json, os
from .storage import list_trees, now
from .resources import queue_position

# Resolved on first call, not on import: spawner.spawn_reservation_live is defined after this
# section in the original file, so importing it here would close a cycle.


def spawn_reservation_live(*args, **kwargs):
    from .spawner import spawn_reservation_live as _impl

    return _impl(*args, **kwargs)


# ───────────────────────────── task helpers ──────────────────────────────────


def sweep_leases(tree):
    """Executing tasks whose lease ran out become 'stale' — still shown as
    executing in the UI but flagged, and re-claimable."""
    changed = False
    t = now()
    for task in tree['tasks']:
        if task['status'] == 'executing' and task['lease_until'] < t and not task.get('stale'):
            task['stale'] = True
            task['history'].append({'at': t, 'event': 'lease expired (no touch/done/fail from agent)'})
            changed = True
        # A queued reservation is kept alive only by `st await` polling. If the
        # waiter stops calling, the reservation goes back to todo — unlike an
        # executing task nothing is in flight, so there is nothing to keep.
        if task['status'] == 'queued' and task['lease_until'] < t:
            task['history'].append(
                {'at': t, 'event': 'queue reservation dropped (no st await poll)', 'from': task.get('claimed_by')}
            )
            task.update(status='todo', stale=False, claimed_by=None, lease_until=0, queued_at=None, progress='')
            changed = True
    return changed


def deps_done(tree, task):
    by_id = {x['id']: x for x in tree['tasks']}
    return all(by_id.get(d, {}).get('status') == 'finished' for d in task.get('depends_on', []))


def claimable(tree, task):
    if task['status'] == 'todo':
        return deps_done(tree, task)
    if task['status'] == 'executing' and task.get('stale'):
        return deps_done(tree, task)
    return False


def reserved_for_other(task, session_id):
    """True when a spawned executor other than `session_id` holds a live
    reservation on this todo task (see spawner). Expired/dead reservations do
    not count — the sweep clears them, and until it does they are ignored."""
    r = task.get('spawned_for')
    if not r or r.get('session_id') == session_id:
        return False
    return spawn_reservation_live(r)


def session_task_count(session_id):
    """Tasks this session has claimed — on active trees AND on trees finished in
    the last 24 h, so the per-session cap survives its own tree archiving (a
    spawned executor's `st next` after its tree archived used to see 0)."""
    n = 0
    trees = list_trees()
    cutoff = now() - 86400
    for p in glob.glob(os.path.join(FINISHED, '*.json')):
        try:
            if os.path.getmtime(p) >= cutoff:
                with open(p) as f:
                    trees.append(json.load(f))
        except (OSError, ValueError) as _exc:
            _zyg_log.warning('finished tree %s unreadable, its tasks do not count toward the session cap: %s', p, _exc)
    for t in trees:
        for task in t['tasks']:
            if (task.get('claimed_by') or {}).get('session_id') == session_id:
                n += 1
    return n


def session_active_task(session_id):
    for t in list_trees():
        for task in t['tasks']:
            if (
                task['status'] in ('executing', 'queued')
                and not task.get('stale')
                and (task.get('claimed_by') or {}).get('session_id') == session_id
            ):
                return t['id'], task['id']
    return None


def public_task_row(task, tree=None):
    """What an agent may see about a task it has not claimed: NO brief."""
    status = task['status'] + ('(stale)' if task.get('stale') else '')
    if task['status'] == 'queued' and tree is not None:
        status = f'queued({queue_position(tree["id"], task) or "?"})'
    if task['status'] == 'todo' and spawn_reservation_live(task.get('spawned_for')):
        status = 'todo(spawned)'
    sb = task.get('spawn_blocked') if task['status'] == 'todo' else None
    return {
        'id': task['id'],
        'title': task['title'],
        'weight': task['weight'],
        'status': status,
        'depends_on': task.get('depends_on', []),
        'vram_gb': task.get('vram_gb') if task['weight'] == 'heavy' else None,
        'spawn_blocked': ({'since': sb.get('since'), 'why': sb.get('why')} if sb else None),
    }


def validate_task(raw, idx):
    if not isinstance(raw, dict):
        raise ValueError(f'task {idx}: not an object')
    title = str(raw.get('title', '')).strip()
    brief = str(raw.get('brief', '')).strip()
    if not title or len(title) > 100:
        raise ValueError(f'task {idx}: title required, ≤100 chars')
    if len(brief) < 30:
        raise ValueError(f'task {idx}: brief must be ≥30 chars — an executor gets ONLY this text')
    weight = raw.get('weight', 'light')
    if weight not in ('heavy', 'light'):
        raise ValueError(f'task {idx}: weight must be heavy|light')
    deps = raw.get('depends_on', []) or []
    if not all(isinstance(d, int) for d in deps):
        raise ValueError(f'task {idx}: depends_on must be task ids (ints)')
    cwd = raw.get('cwd') or ''
    if cwd and not os.path.isdir(cwd):
        raise ValueError(f'task {idx}: cwd does not exist: {cwd}')
    task = {
        'title': title,
        'brief': brief,
        'weight': weight,
        'vram_gb': float(raw.get('vram_gb', 8 if weight == 'heavy' else 0)),
        'ram_gb': float(raw.get('ram_gb', 4)),
        'eta_minutes': (float(raw['eta_minutes']) if raw.get('eta_minutes') else None),
        'cwd': cwd,
        'verify_cmd': (raw.get('verify_cmd') or '').strip(),
        'expect_files': [str(p) for p in (raw.get('expect_files') or [])],
        'depends_on': deps,
        'status': 'todo',
        'stale': False,
        'claimed_by': None,
        'claimed_at': None,
        'lease_until': 0,
        'touched_at': None,
        'progress': '',
        'attempts': 0,
        'history': [],
        'report': None,
        'verify_result': None,
        'finished_at': None,
    }
    return task
