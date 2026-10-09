# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Creator commands: create, suggest, add, reset, close, report, wait, review.

Moved verbatim from session_tree_server.py lines 3077-3492.
"""

from ._base import ACTIVE, FINISHED, PLANNED, SUGGESTED, json, os, re, uuid
from .storage import CFG, audit, iso, list_trees, load_tree, now, save_tree
from .peers import NOTIFY, archive_tree, notice_for, planned_trees, promote_planned, suggested_trees
from .task_helpers import sweep_leases, validate_task
from .spawner import kick_spawner
from .commands import Refuse, cmd_await, cmd_claim, cmd_next, cmd_release, cmd_status, cmd_touch, cmd_whoami, need_role
from .completion import _spawn_alive, cmd_done, cmd_fail, tree_settle


# creator commands


def cmd_create(ident, body):
    need_role(ident, 'creator')
    title = str(body.get('title', '')).strip()
    if not title:
        raise Refuse('title required')
    raw_tasks = body.get('tasks') or []
    if not 1 <= len(raw_tasks) <= CFG['max_tasks_per_tree']:
        raise Refuse(f'a tree holds 1..{CFG["max_tasks_per_tree"]} tasks (got {len(raw_tasks)})')
    tasks = []
    for i, raw in enumerate(raw_tasks, 1):
        try:
            task = validate_task(raw, i)
        except ValueError as e:
            raise Refuse(str(e)) from e
        task['id'] = i
        tasks.append(task)
    for task in tasks:
        for d in task['depends_on']:
            if d == task['id'] or not 1 <= d <= len(tasks):
                raise Refuse(f'task {task["id"]}: bad dependency {d}')
    cwd = body.get('cwd') or ''
    if cwd and not os.path.isdir(cwd):
        raise Refuse(f'cwd does not exist: {cwd}')
    eta = body.get('eta_minutes')
    try:
        eta = float(eta)
    except (TypeError, ValueError):
        eta = 0
    if eta <= 0:
        raise Refuse(
            "eta_minutes required: your estimate, in minutes, of the whole tree's wall time from "
            'activation to archive (see `st rules` → ETA). It is only logged and compared with reality '
            'on the Metrics tab — nothing acts on it. Add eta_note with the arithmetic.'
        )
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:40] or 'tree'
    tree_id = f'{slug}-{uuid.uuid4().hex[:6]}'
    tree = {
        'id': tree_id,
        'title': title,
        'goal': str(body.get('goal', '')).strip()[:2000],
        'cwd': cwd,
        'status': 'active',
        'created_at': now(),
        'finished_at': None,
        'activated_at': None,
        'activated_by': None,
        'created_by': {'session_id': ident['session_id'], 'model': ident['model']},
        'eta_minutes': eta,
        'eta_note': str(body.get('eta_note', '')).strip()[:1000],
        'eta_overrun_at': None,
        'eta_result': None,
        'tasks': tasks,
    }
    audit(
        {
            'cmd': 'eta:logged',
            'tree': tree_id,
            'ok': True,
            'model': ident['model'],
            'error': 'ETA %g min for %d task(s)%s'
            % (eta, len(tasks), (': ' + tree['eta_note'][:160]) if tree['eta_note'] else ''),
        }
    )
    promote_planned('auto (create found no active tree)')
    active = list_trees(ACTIVE)
    if active:
        # One tree at a time: this one waits its turn behind the active tree
        # and any earlier planned trees, ranked by created_at.
        tree['status'] = 'planned'
        tree['planned_at'] = tree['created_at']
        save_tree(tree, PLANNED)
        position = len(planned_trees())
        return {
            'ok': True,
            'tree': tree_id,
            'n': len(tasks),
            'planned': True,
            'position': position,
            'behind': [t['id'] for t in active] + [t['id'] for t in planned_trees()[: position - 1]],
        }
    tree['activated_at'] = tree['created_at']
    tree['activated_by'] = 'create (no active tree)'
    save_tree(tree)
    kick_spawner()
    return {'ok': True, 'tree': tree_id, 'n': len(tasks), 'planned': False, 'auto_spawn': bool(CFG.get('auto_spawn'))}


def cmd_suggest(ident, body):
    """A creator files a fully-formed modularization tree for the operator to
    accept or reject in the Modularization tab. Same validation as create;
    nothing runs and nothing queues until the operator accepts it."""
    need_role(ident, 'creator')
    title = str(body.get('title', '')).strip()
    if not title:
        raise Refuse('title required')
    raw_tasks = body.get('tasks') or []
    if not 1 <= len(raw_tasks) <= CFG['max_tasks_per_tree']:
        raise Refuse(f'a tree holds 1..{CFG["max_tasks_per_tree"]} tasks (got {len(raw_tasks)})')
    tasks = []
    for i, raw in enumerate(raw_tasks, 1):
        try:
            task = validate_task(raw, i)
        except ValueError as e:
            raise Refuse(str(e)) from e
        task['id'] = i
        tasks.append(task)
    for task in tasks:
        for d in task['depends_on']:
            if d == task['id'] or not 1 <= d <= len(tasks):
                raise Refuse(f'task {task["id"]}: bad dependency {d}')
    cwd = body.get('cwd') or ''
    if cwd and not os.path.isdir(cwd):
        raise Refuse(f'cwd does not exist: {cwd}')
    eta = body.get('eta_minutes')
    try:
        eta = float(eta)
    except (TypeError, ValueError):
        eta = 0
    if eta <= 0:
        raise Refuse('eta_minutes required, with eta_note holding the arithmetic (see `st rules` → ETA)')
    rationale = str(body.get('rationale', '')).strip()[:2000]
    if not rationale:
        raise Refuse(
            'rationale required: why this modularization, which files, current line counts — '
            'it is what the operator reads before accepting'
        )
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:40] or 'tree'
    tree_id = f'{slug}-{uuid.uuid4().hex[:6]}'
    tree = {
        'id': tree_id,
        'title': title,
        'goal': str(body.get('goal', '')).strip()[:2000],
        'cwd': cwd,
        'status': 'suggested',
        'created_at': now(),
        'finished_at': None,
        'activated_at': None,
        'activated_by': None,
        'created_by': {'session_id': ident['session_id'], 'model': ident['model']},
        'eta_minutes': eta,
        'eta_note': str(body.get('eta_note', '')).strip()[:1000],
        'eta_overrun_at': None,
        'eta_result': None,
        'rationale': rationale,
        'tasks': tasks,
    }
    save_tree(tree, SUGGESTED)
    return {'ok': True, 'tree': tree_id, 'n': len(tasks), 'position': len(suggested_trees())}


def cmd_add(ident, body):
    need_role(ident, 'creator')
    folder = ACTIVE
    tree = load_tree(body.get('tree', ''))
    if not tree:
        folder = PLANNED
        tree = load_tree(body.get('tree', ''), PLANNED)
    if not tree:
        raise Refuse(f"no active or planned tree '{body.get('tree')}'")
    raw_tasks = body.get('tasks') or []
    if len(tree['tasks']) + len(raw_tasks) > CFG['max_tasks_per_tree']:
        raise Refuse(f'tree would exceed {CFG["max_tasks_per_tree"]} tasks')
    start = len(tree['tasks'])
    new = []
    for i, raw in enumerate(raw_tasks, start + 1):
        try:
            task = validate_task(raw, i)
        except ValueError as e:
            raise Refuse(str(e)) from e
        task['id'] = i
        new.append(task)
    tree['tasks'] += new
    if body.get('eta_minutes'):
        try:
            new_eta = float(body['eta_minutes'])
        except (TypeError, ValueError):
            new_eta = 0
        if new_eta > 0:
            tree.setdefault('eta_revisions', []).append(
                {'at': now(), 'from': tree.get('eta_minutes'), 'to': new_eta, 'why': 'st add %d task(s)' % len(new)}
            )
            audit(
                {
                    'cmd': 'eta:revised',
                    'tree': tree['id'],
                    'ok': True,
                    'model': ident['model'],
                    'error': 'ETA %s → %g min after adding %d task(s)' % (tree.get('eta_minutes'), new_eta, len(new)),
                }
            )
            tree['eta_minutes'] = new_eta
            tree['eta_overrun_at'] = None
    save_tree(tree, folder)
    kick_spawner()
    return {
        'ok': True,
        'tree': tree['id'],
        'added': [x['id'] for x in new],
        'n': len(tree['tasks']),
        'planned': folder == PLANNED,
        'eta_minutes': tree.get('eta_minutes'),
    }


def cmd_reset(ident, body):
    need_role(ident, 'creator')
    tree = load_tree(body.get('tree', ''))
    if not tree:
        if load_tree(body.get('tree', ''), PLANNED):
            raise Refuse(f"'{body.get('tree')}' is planned — nothing has run yet, nothing to reset")
        raise Refuse(f"no active tree '{body.get('tree')}'")
    task = next((x for x in tree['tasks'] if x['id'] == body.get('task')), None)
    if not task:
        raise Refuse('no such task')
    _reset_task(task, f'reset by creator {ident["model"]}')
    if body.get('brief'):
        task['brief'] = str(body['brief']).strip()
    save_tree(tree)
    return {'ok': True, 'task': task['id'], 'status': 'todo'}


def _reset_task(task, why):
    task['history'].append({'at': now(), 'event': why, 'previous': task['status'], 'prior_report': task.get('report')})
    task.update(
        status='todo',
        stale=False,
        claimed_by=None,
        claimed_at=None,
        lease_until=0,
        queued_at=None,
        progress='',
        report=None,
        verify_result=None,
        finished_at=None,
        spawned_for=None,
        spawn_cooldown_until=0,
    )
    kick_spawner()


def cmd_close(ident, body):
    need_role(ident, 'creator')
    tree = load_tree(body.get('tree', ''))
    if not tree:
        tree = load_tree(body.get('tree', ''), PLANNED)
        if tree:
            archive_tree(tree, ident['model'], str(body.get('note', '')) or 'closed while planned')
            return {'ok': True, 'archived': tree['id'], 'was_planned': True}
        raise Refuse(f"no active or planned tree '{body.get('tree')}'")
    live = [x['id'] for x in tree['tasks'] if x['status'] in ('executing', 'queued') and not x.get('stale')]
    if live and not body.get('force'):
        raise Refuse(f'tasks {live} are executing right now — wait, or pass force')
    archive_tree(tree, ident['model'], str(body.get('note', '')))
    return {'ok': True, 'archived': tree['id']}


def cmd_report(ident, body):
    """Creator-only read of a finished/failed task's report on an ACTIVE tree
    (so Fable can decide whether to reset it). Never reads finished trees."""
    need_role(ident, 'creator')
    tree = load_tree(body.get('tree', ''))
    if not tree:
        raise Refuse(f"no active tree '{body.get('tree')}'")
    task = next((x for x in tree['tasks'] if x['id'] == body.get('task')), None)
    if not task:
        raise Refuse('no such task')
    if task['status'] not in ('finished', 'failed'):
        raise Refuse(f'#{task["id"]} is {task["status"]} — no report yet')
    return {
        'ok': True,
        'task': task['id'],
        'status': task['status'],
        'report': task['report'],
        'verify_result': task['verify_result'],
    }


def cmd_wait(ident, body):
    """One non-blocking check; the CLI loops on it. Creator only."""
    need_role(ident, 'creator')
    tid = body.get('tree', '')
    n = notice_for(tid)
    if n:
        return {
            'ok': True,
            'archived': True,
            'finished_at': iso(n['finished_at']),
            'counts': n['counts'],
            'by': n['by'],
            'title': n['title'],
        }
    tree = load_tree(tid)
    if not tree:
        promote_planned('auto (wait poll found no active tree)')
        tree = load_tree(tid)
    if not tree:
        if load_tree(tid, FINISHED):
            return {'ok': True, 'archived': True, 'counts': {}, 'title': tid, 'finished_at': '?', 'by': '?'}
        for i, p in enumerate(planned_trees()):
            if p['id'] == tid:
                active = [a['id'] for a in list_trees(ACTIVE)]
                return {
                    'ok': True,
                    'archived': False,
                    'planned': True,
                    'position': i + 1,
                    'behind': active + [q['id'] for q in planned_trees()[:i]],
                    'counts': {'planned': len(p['tasks'])},
                    'title': p['title'],
                }
        raise Refuse(f"no tree '{tid}' anywhere")
    sweep_leases(tree)
    counts = {}
    problems = []
    for x in tree['tasks']:
        k = x['status'] + ('(stale)' if x.get('stale') else '')
        counts[k] = counts.get(k, 0) + 1
        if x['status'] == 'failed' or (x.get('stale') and not _spawn_alive(x)):
            rep = x.get('report') or {}
            hist = [h for h in (x.get('history') or []) if h.get('event')]
            problems.append(
                {
                    'id': x['id'],
                    'title': x.get('title', ''),
                    'status': 'stale' if x.get('stale') else 'failed',
                    'event': (hist[-1].get('event') if hist else ''),
                    'at': iso(x.get('finished_at') or (hist[-1].get('at') if hist else 0) or 0),
                    'summary': (rep.get('summary') or '')[:400],
                }
            )
    st = tree_settle(tree)
    return {
        'ok': True,
        'archived': False,
        'counts': counts,
        'title': tree['title'],
        'problems': problems,
        'blocked': st['blocked'],
        'settled': st['settled'],
        'archive_at': iso(st['archive_at']) if st.get('archive_at') else None,
    }


def cmd_review(ident, body):
    """Creator-only read of a FINISHED tree's reports, once, to write the
    results report + plan of action for the user. Marks the notice reviewed."""
    need_role(ident, 'creator')
    tid = body.get('tree', '')
    tree = load_tree(tid, FINISHED)
    if not tree:
        if load_tree(tid):
            raise Refuse(f"'{tid}' is still active — use st status {tid} / st report {tid} N")
        if load_tree(tid, PLANNED):
            raise Refuse(f"'{tid}' is still planned — nothing has run yet")
        raise Refuse(f"no finished tree '{tid}'")
    rows = []
    for x in tree['tasks']:
        r = x.get('report') or {}
        vr = x.get('verify_result')
        rows.append(
            {
                'id': x['id'],
                'title': x['title'],
                'status': x['status'],
                'attempts': x['attempts'],
                'by': r.get('by'),
                'summary': r.get('summary', ''),
                'not_done': r.get('not_done', ''),
                'changed_files': r.get('changed_files', []),
                'notes': (r.get('notes') or '')[:1500],
                'verify': ({'exit': vr['exit'], 'tail': vr['tail'][-600:]} if vr else None),
            }
        )
    n = notice_for(tid)
    if n and not n.get('reviewed'):
        n['reviewed'] = True
        n['reviewed_at'] = now()
        n['reviewed_by'] = {'session_id': ident['session_id'], 'model': ident['model']}
        with open(os.path.join(NOTIFY, tid + '.json'), 'w') as f:
            json.dump(n, f, indent=1)
    return {
        'ok': True,
        'tree': tid,
        'title': tree['title'],
        'goal': tree.get('goal', ''),
        'finished_at': iso(tree.get('finished_at') or 0),
        'closed_by': tree.get('closed_by'),
        'close_note': tree.get('close_note', ''),
        'tasks': rows,
    }


AGENT_COMMANDS = {
    'wait': cmd_wait,
    'review': cmd_review,
    'whoami': cmd_whoami,
    'status': cmd_status,
    'next': cmd_next,
    'claim': cmd_claim,
    'touch': cmd_touch,
    'release': cmd_release,
    'done': cmd_done,
    'fail': cmd_fail,
    'await': cmd_await,
    'create': cmd_create,
    'add': cmd_add,
    'reset': cmd_reset,
    'close': cmd_close,
    'report': cmd_report,
    'suggest': cmd_suggest,
}
