# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Executor commands: whoami, status, next, claim, await, touch, release.

Moved verbatim from session_tree_server.py lines 2306-2733.
"""

from .storage import CFG, iso, list_trees, load_tree, now, save_tree
from .peers import pending_notices, planned_trees, promote_planned
from .resources import admission, queue_position, queue_state, resources, wait_queue
from .task_helpers import (
    claimable,
    deps_done,
    public_task_row,
    reserved_for_other,
    session_active_task,
    session_task_count,
    sweep_leases,
)
from .spawner import spawner_state

# Resolved on first call, not on import: completion.tree_settle is defined after this
# section in the original file, so importing it here would close a cycle.


def tree_settle(*args, **kwargs):
    from .completion import tree_settle as _impl

    return _impl(*args, **kwargs)


# ───────────────────────────── agent commands ────────────────────────────────


class Refuse(Exception):
    def __init__(self, msg, retry_after=None):
        super().__init__(msg)
        self.retry_after = retry_after


def need_role(ident, *roles):
    if ident['role'] not in roles:
        who = ident.get('model') or 'unknown model'
        raise Refuse(
            f'refused: this command is for {"/".join(roles)} sessions; '
            f"your transcript says you are '{who}' ({ident['role']}). " + ident.get('why', '')
        )


def cmd_whoami(ident, body):
    out = {
        'ok': True,
        'session_id': ident['session_id'],
        'model': ident['model'],
        'role': ident['role'],
        'why': ident.get('why'),
        'active_task': session_active_task(ident['session_id']),
        'tasks_this_session': session_task_count(ident['session_id']),
        'max_tasks_per_session': CFG['max_tasks_per_session'],
    }
    if ident['role'] == 'creator':
        # whoami is the first command every creator session runs: unreviewed trees must be seen
        # here, not only by a creator that happens to run `st status` (2026-09-23).
        out['pending_reviews'] = [
            {
                'tree': n['tree'],
                'title': n['title'],
                'finished_at': iso(n['finished_at']),
                'counts': n['counts'],
                'yours': not n.get('other_creator'),
            }
            for n in pending_notices(ident['session_id'])
        ]
    return out


def cmd_status(ident, body):
    need_role(ident, 'creator', 'executor')
    promote_planned('auto (status poll found no active tree)')
    trees = list_trees()
    for t in trees:
        if sweep_leases(t):
            save_tree(t)
    out = {
        'ok': True,
        'queue': queue_state(),
        'resources': resources(),
        'trees': [],
        'spawner': {k: v for k, v in spawner_state().items() if k != 'recent_exits'},
    }
    want = body.get('tree')
    for t in trees:
        counts = {}
        for task in t['tasks']:
            k = task['status'] + ('(stale)' if task.get('stale') else '')
            counts[k] = counts.get(k, 0) + 1
        row = {
            'id': t['id'],
            'title': t['title'],
            'counts': counts,
            'n': len(t['tasks']),
            'created_by': t['created_by']['model'],
            'eta_minutes': t.get('eta_minutes'),
            'activated_at': t.get('activated_at') or t.get('created_at'),
            'eta_overrun_at': t.get('eta_overrun_at'),
            'now': now(),
            'settle': tree_settle(t),
        }
        if want and want == t['id']:
            row['tasks'] = [public_task_row(x, t) for x in t['tasks']]
        out['trees'].append(row)
    planned = planned_trees()
    if want and not any(t['id'] == want for t in trees):
        if ident['role'] == 'creator' and any(t['id'] == want for t in planned):
            raise Refuse(
                f"'{want}' is PLANNED, not active — it activates when the active tree archives "
                f'(st status shows its position). Executors cannot see it yet.'
            )
        raise Refuse(f"no active tree '{want}' (finished trees are not readable by agents)")
    if ident['role'] == 'creator':
        out['planned'] = [
            {
                'id': t['id'],
                'title': t['title'],
                'n': len(t['tasks']),
                'position': i + 1,
                'created_at': iso(t.get('created_at') or 0),
                'created_by': t['created_by']['model'],
            }
            for i, t in enumerate(planned)
        ]
        out['pending_reviews'] = [
            {
                'tree': n['tree'],
                'title': n['title'],
                'finished_at': iso(n['finished_at']),
                'counts': n['counts'],
                'yours': not n.get('other_creator'),
            }
            for n in pending_notices(ident['session_id'])
        ]
    return out


def pick_next(trees, ident):
    """Best claimable task for this session: deps satisfied, queue has room.
    Never reveals briefs."""
    active = session_active_task(ident['session_id'])
    if active:
        raise Refuse(f'you already hold task {active[0]}#{active[1]} — finish, fail or release it first')
    if session_task_count(ident['session_id']) >= CFG['max_tasks_per_session']:
        raise Refuse(
            'session cap reached (%d tasks). End this session; a fresh agent costs '
            'fewer tokens than a long one.' % CFG['max_tasks_per_session']
        )
    # A session the board spawned for a task gets THAT task, first and only.
    for t in trees:
        for task in t['tasks']:
            r = task.get('spawned_for') or {}
            if r.get('session_id') == ident['session_id'] and claimable(t, task):
                why = admission(task)
                pick = {
                    'tree': t['id'],
                    'task': task['id'],
                    'title': task['title'],
                    'weight': task['weight'],
                    'spawned_for_you': True,
                }
                if why:
                    pick.update(will_queue=True, reason=why[0], queue_ahead=len(wait_queue(task['weight'])))
                return pick
    blocked = []
    for t in trees:
        for task in sorted(t['tasks'], key=lambda x: (x['weight'] != 'light', x['id'])):
            if not claimable(t, task) or reserved_for_other(task, ident['session_id']):
                continue
            why = admission(task)
            if why is None:
                return {'tree': t['id'], 'task': task['id'], 'title': task['title'], 'weight': task['weight']}
            blocked.append((t, task, why))
    if blocked:
        # Nothing can start this second, but a claim will RESERVE the slot
        # (status queued) and `st await` hands over the brief when it frees.
        t, task, why = blocked[0]
        return {
            'tree': t['id'],
            'task': task['id'],
            'title': task['title'],
            'weight': task['weight'],
            'will_queue': True,
            'reason': why[0],
            'queue_ahead': len(wait_queue(task['weight'])),
        }
    return None


def cmd_next(ident, body):
    need_role(ident, 'executor')
    promote_planned('auto (next found no active tree)')
    trees = list_trees()
    if body.get('tree'):
        trees = [t for t in trees if t['id'] == body['tree']]
        if not trees:
            raise Refuse(f"no active tree '{body['tree']}'")
    pick = pick_next(trees, ident)
    if not pick:
        return {'ok': True, 'none': True, **waiting_summary(trees)}
    return {'ok': True, **pick}


def waiting_summary(trees):
    """Why `next` has nothing: todo tasks blocked on unfinished dependencies,
    with the holder + lease of each blocker, so an executor can decide whether
    to wait (retry_after_s) or end the session. Titles only, never briefs."""
    waiting, blockers = [], {}
    for t in trees:
        by_id = {x['id']: x for x in t['tasks']}
        for task in t['tasks']:
            if task['status'] != 'todo' or deps_done(t, task):
                continue
            open_deps = [d for d in task.get('depends_on', []) if by_id.get(d, {}).get('status') != 'finished']
            waiting.append(f'{t["id"]}#{task["id"]} ({task["weight"]}) waits on {open_deps}')
            for d in open_deps:
                dep = by_id.get(d)
                if not dep or (t['id'], d) in blockers:
                    continue
                cb = dep.get('claimed_by') or {}
                if dep['status'] == 'executing':
                    blockers[(t['id'], d)] = (
                        f'#{d} executing by {(cb.get("session_id") or "?")[:8]}'
                        f'{" (STALE)" if dep.get("stale") else ""}, lease until '
                        f'{iso(dep["lease_until"])}'
                    )
                else:
                    blockers[(t['id'], d)] = f'#{d} is {dep["status"]}'
    if not waiting:
        return {'msg': 'nothing claimable: every task is finished, executing or failed'}
    failed = [b for b in blockers.values() if 'is failed' in b]
    lines = [f'nothing claimable now: {len(waiting)} task(s) wait on dependencies still running']
    lines += ['  ' + w for w in waiting[:8]]
    lines += ['  blocker ' + b for b in blockers.values()]
    if failed:
        lines.append('  a blocker has FAILED — only the creator/operator can reset it; end this session')
    return {
        'msg': '\n'.join(lines),
        'waiting': len(waiting),
        'retry_after_s': None if failed and len(failed) == len(blockers) else 600,
    }


def cmd_claim(ident, body):
    need_role(ident, 'executor')
    tree = load_tree(body.get('tree', ''))
    if not tree:
        raise Refuse(f"no active tree '{body.get('tree')}'")
    sweep_leases(tree)
    task = next((x for x in tree['tasks'] if x['id'] == body.get('task')), None)
    if not task:
        raise Refuse(f'no task #{body.get("task")} in {tree["id"]}')
    active = session_active_task(ident['session_id'])
    if active:
        raise Refuse(f'you already hold {active[0]}#{active[1]} — one task at a time')
    if session_task_count(ident['session_id']) >= CFG['max_tasks_per_session']:
        raise Refuse(
            'session cap reached (%d tasks). End this session and let a fresh agent continue.'
            % CFG['max_tasks_per_session']
        )
    if not claimable(tree, task):
        if task['status'] == 'executing':
            cb = task['claimed_by'] or {}
            raise Refuse(
                f'#{task["id"]} is being executed by {cb.get("model")} '
                f'{(cb.get("session_id") or "")[:8]} (lease until {iso(task["lease_until"])})'
            )
        if task['status'] == 'queued':
            cb = task['claimed_by'] or {}
            raise Refuse(
                f'#{task["id"]} is queued (position {queue_position(tree["id"], task)}) by '
                f'{cb.get("model")} {(cb.get("session_id") or "")[:8]} — waiting for a slot'
            )
        if task['status'] in ('finished', 'failed'):
            raise Refuse(
                f'#{task["id"]} is {task["status"]} — not claimable '
                f'(a failed task is reset by the creator or the operator)'
            )
        raise Refuse(f'#{task["id"]} waits on dependencies {task.get("depends_on")} — not all finished')
    if reserved_for_other(task, ident['session_id']):
        r = task['spawned_for']
        raise Refuse(
            f'#{task["id"]} is reserved for the executor the board spawned for it '
            f'({(r.get("session_id") or "")[:8]}, pid {r.get("pid")}) — run `st next` for yours',
            retry_after=60,
        )
    t = now()
    if task.get('spawned_for'):
        task['claimed_by_spawn'] = task['spawned_for']
        task['spawned_for'] = None
    if task['status'] == 'executing':  # stale takeover
        task['history'].append({'at': t, 'event': 'taken over after stale lease', 'from': task['claimed_by']})
    task['claimed_by'] = {
        'session_id': ident['session_id'],
        'model': ident['model'],
        'pid': ident.get('pid'),
        'spawned': (task.get('claimed_by_spawn') or {}).get('session_id') == ident['session_id'],
    }
    why = admission(task)
    if why:
        # Slot/resources busy: RESERVE instead of refuse. The task is held by
        # this session in status "queued"; the brief stays hidden until
        # `st await` grants the slot, so nobody starts GPU work early. The
        # reservation lives only as long as the waiter keeps polling.
        task['status'] = 'queued'
        task['stale'] = False
        task['queued_at'] = t
        task['touched_at'] = t
        task['lease_until'] = t + CFG['queue_wait_stale_minutes'] * 60
        task['progress'] = 'queued: ' + why[0][:120]
        task['history'].append(
            {'at': t, 'event': 'queued', 'by': ident['model'], 'session': ident['session_id'], 'reason': why[0][:200]}
        )
        save_tree(tree)
        return {
            'ok': True,
            'queued': True,
            'tree': tree['id'],
            'task': task['id'],
            'title': task['title'],
            'weight': task['weight'],
            'reason': why[0],
            'position': queue_position(tree['id'], task),
            'wait_stale_minutes': CFG['queue_wait_stale_minutes'],
        }
    return {'ok': True, **_grant(tree, task, ident, t)}


def _grant(tree, task, ident, t, from_queue=False):
    """Start the task for its holder: lease begins, brief is released."""
    task['status'] = 'executing'
    task['stale'] = False
    task['claimed_at'] = t
    task['touched_at'] = t
    task['queued_at'] = None
    task['lease_until'] = t + CFG['lease_minutes'] * 60
    task['attempts'] += 1
    task['progress'] = ''
    task['history'].append(
        {
            'at': t,
            'event': 'slot granted from queue' if from_queue else 'claimed',
            'by': ident['model'],
            'session': ident['session_id'],
        }
    )
    save_tree(tree)
    return _brief_payload(tree, task)


def _brief_payload(tree, task):
    return {
        'tree': tree['id'],
        'task': task['id'],
        'title': task['title'],
        'weight': task['weight'],
        'cwd': task['cwd'] or tree.get('cwd') or '',
        'brief': task['brief'],
        'verify_cmd': task['verify_cmd'],
        'expect_files': task['expect_files'],
        'lease_until': iso(task['lease_until']),
        'lease_minutes': CFG['lease_minutes'],
    }


def cmd_await(ident, body):
    """One non-blocking check of this session's queued reservation; the CLI
    loops on it every ~20 s. The head of its weight's FIFO gets the slot as
    soon as admission passes; every call refreshes the reservation."""
    need_role(ident, 'executor')
    tree = load_tree(body.get('tree', ''))
    if not tree:
        raise Refuse(f"no active tree '{body.get('tree')}'")
    if sweep_leases(tree):
        save_tree(tree)
    task = next((x for x in tree['tasks'] if x['id'] == body.get('task')), None)
    if not task:
        raise Refuse(f'no task #{body.get("task")} in {tree["id"]}')
    cb = task.get('claimed_by') or {}
    if cb.get('session_id') != ident['session_id']:
        raise Refuse(
            f'#{task["id"]} is not held by your session (status {task["status"]}) — '
            f'the reservation was dropped or taken; run `st next` again'
        )
    if task['status'] == 'executing':  # already granted (CLI re-run) — idempotent
        return {'ok': True, 'granted': True, **_brief_payload(tree, task)}
    if task['status'] != 'queued':
        raise Refuse(f'#{task["id"]} is {task["status"]}, not queued')
    t = now()
    task['touched_at'] = t
    task['lease_until'] = t + CFG['queue_wait_stale_minutes'] * 60
    pos = queue_position(tree['id'], task)
    why = admission(task) if pos == 1 else None
    if pos == 1 and why is None:
        return {'ok': True, 'granted': True, **_grant(tree, task, ident, t, from_queue=True)}
    save_tree(tree)
    return {
        'ok': True,
        'granted': False,
        'position': pos,
        'poll_s': 20,
        'reason': why[0] if why else f'{pos - 1} reservation(s) ahead of you',
    }


def _held_task(ident, body):
    tree = load_tree(body.get('tree', ''))
    if not tree:
        raise Refuse(f"no active tree '{body.get('tree')}'")
    task = next((x for x in tree['tasks'] if x['id'] == body.get('task')), None)
    if not task:
        raise Refuse(f'no task #{body.get("task")} in {tree["id"]}')
    cb = task.get('claimed_by') or {}
    if task['status'] not in ('executing', 'queued') or cb.get('session_id') != ident['session_id']:
        raise Refuse(
            f'#{task["id"]} is not held by your session (status {task["status"]}, '
            f'holder {(cb.get("session_id") or "none")[:8]})'
        )
    return tree, task


def cmd_touch(ident, body):
    need_role(ident, 'executor')
    tree, task = _held_task(ident, body)
    t = now()
    task['touched_at'] = t
    task['stale'] = False
    mins = CFG['queue_wait_stale_minutes'] if task['status'] == 'queued' else CFG['lease_minutes']
    task['lease_until'] = t + mins * 60
    note = str(body.get('note', '')).strip()[:200]
    if note:
        task['progress'] = note
        task['history'].append({'at': t, 'event': 'progress', 'note': note})
    save_tree(tree)
    return {'ok': True, 'lease_until': iso(task['lease_until'])}


def cmd_release(ident, body):
    need_role(ident, 'executor')
    tree, task = _held_task(ident, body)
    reason = str(body.get('reason', '')).strip()[:300]
    task['status'] = 'todo'
    task['stale'] = False
    task['claimed_by'] = None
    task['lease_until'] = 0
    task['queued_at'] = None
    task['progress'] = ''
    task['history'].append({'at': now(), 'event': 'released', 'reason': reason, 'by': ident['model']})
    save_tree(tree)
    return {'ok': True, 'msg': f'#{task["id"]} back to todo'}
