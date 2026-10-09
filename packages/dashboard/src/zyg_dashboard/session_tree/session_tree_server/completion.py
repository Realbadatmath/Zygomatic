# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Report checking, verify_cmd, tree settle, done and fail.

Moved verbatim from session_tree_server.py lines 2734-3076.
"""

from ._base import ACTIVE, BASE, os, shutil, subprocess
from .storage import CFG, audit, iso, list_trees, now, save_tree
from .peers import archive_tree, operator_notify, peer_for
from .task_helpers import session_task_count
from .spawner import kick_spawner
from .metrics import stamp_task_usage
from .commands import Refuse, _held_task, need_role


def _check_files(task, report):
    """Every file the agent says it changed must exist and have been modified
    after the claim. Every expected file must exist and be fresh too."""
    since = task['claimed_at'] - 5
    problems = []
    files = report.get('changed_files') or []
    if not isinstance(files, list):
        problems.append('changed_files must be a list of absolute paths')
        files = []
    for p in files:
        p = str(p)
        if not os.path.isabs(p):
            problems.append(f'{p}: not an absolute path')
        elif not os.path.exists(p):
            problems.append(f'{p}: listed as changed but does not exist')
        elif os.path.getmtime(p) < since:
            problems.append(
                f'{p}: listed as changed but its mtime ({iso(os.path.getmtime(p))}) '
                f'predates your claim ({iso(task["claimed_at"])}) — it was not touched by this task'
            )
    for p in task.get('expect_files', []):
        if not os.path.exists(p):
            problems.append(f'expected output missing: {p}')
        elif os.path.getmtime(p) < since:
            problems.append(f'expected output {p} was not (re)written during this task')
    return problems


def _run_verify(task, tree):
    cmd = task.get('verify_cmd')
    if not cmd:
        return None
    cwd = task['cwd'] or tree.get('cwd') or BASE
    started = now()
    try:
        # Absolute shell path, never a bare 'bash' off the caller's PATH. This server is
        # stdlib-only on purpose (it runs under /usr/bin/python3, outside the venv), so the
        # lookup is done here rather than with zyg_workflows.bin.exe — same ZYG_BIN_BASH
        # override, same PATH-then-fallback order.
        bash = os.environ.get('ZYG_BIN_BASH') or shutil.which('bash') or '/bin/bash'
        r = subprocess.run([bash, '-lc', cmd], cwd=cwd, capture_output=True, text=True, timeout=CFG['verify_timeout_s'])
        out = r.stdout + ('\n[stderr]\n' + r.stderr if r.stderr.strip() else '')
        return {
            'cmd': cmd,
            'exit': r.returncode,
            'tail': out[-3000:],
            'ran_at': started,
            'seconds': round(now() - started, 1),
        }
    except subprocess.TimeoutExpired as e:
        return {
            'cmd': cmd,
            'exit': -1,
            'tail': f'TIMEOUT after {CFG["verify_timeout_s"]}s\n'
            + ((e.stdout or '') if isinstance(e.stdout, str) else '')[-2000:],
            'ran_at': started,
            'seconds': CFG['verify_timeout_s'],
        }
    except Exception as e:
        return {'cmd': cmd, 'exit': -2, 'tail': f'could not run verify_cmd: {e}', 'ran_at': started, 'seconds': 0}


def _maybe_archive(tree, by='auto (all tasks finished)'):
    if all(x['status'] == 'finished' for x in tree['tasks']):
        return archive_tree(tree, by)
    return None


def _spawn_alive(task):
    """Is the executor the board spawned for this task still a live process?
    A stale lease with a live process is a long task that forgot `st touch`,
    not a dead one — it must not settle the tree. No spawn record → unknown →
    treated as dead (hand-opened sessions must touch their leases)."""
    pid = (task.get('spawned_for') or {}).get('pid')
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def tree_settle(tree):
    """Is there anything left the board could ever run on this tree?

    A tree SETTLES when every task is finished, or is dead to the board: failed,
    stale (its agent stopped touching the lease — an operator decision the
    spawner never takes), or todo behind a dead dependency. Such a tree used to
    sit active forever with the planned queue frozen behind it, until a human
    pressed archive (2026-09-06: one failed verify_cmd blocked two planned trees
    for hours). Now it auto-archives after `settle_archive_minutes` of quiet — the
    window in which a creator may still `st reset` a failed task (any history
    event on any task restarts the clock).
    Returns {settled, since, archive_at|None, failed, stale, blocked, enabled}.
    """
    mins = float(CFG.get('settle_archive_minutes') or 0)
    dead = set()
    changed = True
    while changed:
        changed = False
        for x in tree['tasks']:
            if x['id'] in dead:
                continue
            if (
                x['status'] == 'failed'
                or (x.get('stale') and not _spawn_alive(x))
                or (x['status'] == 'todo' and any(d in dead for d in (x.get('depends_on') or [])))
            ):
                dead.add(x['id'])
                changed = True
    settled = all(x['status'] == 'finished' or x['id'] in dead for x in tree['tasks'])
    last = tree.get('activated_at') or tree.get('created_at') or 0
    for x in tree['tasks']:
        for h in x.get('history') or []:
            last = max(last, h.get('at') or 0)
        last = max(last, x.get('finished_at') or 0)
    return {
        'settled': settled,
        'since': last,
        'enabled': mins > 0,
        'archive_at': (last + mins * 60) if (settled and mins > 0) else None,
        'failed': [x['id'] for x in tree['tasks'] if x['status'] == 'failed'],
        'stale': [x['id'] for x in tree['tasks'] if x.get('stale')],
        'blocked': [x['id'] for x in tree['tasks'] if x['status'] == 'todo' and x['id'] in dead],
    }


def settle_sweep():
    """Auto-archive every settled tree whose grace period has passed. Caller
    holds LOCK. archive_tree() promotes the next planned tree itself."""
    mins = float(CFG.get('settle_archive_minutes') or 0)
    if mins <= 0:
        return []
    out = []
    for tree in list_trees(ACTIVE):
        s = tree_settle(tree)
        if not s['settled'] or now() < (s['archive_at'] or 0):
            continue
        why = 'auto (settled: %d failed, %d stale, %d blocked — no runnable task for %g min)' % (
            len(s['failed']),
            len(s['stale']),
            len(s['blocked']),
            mins,
        )
        note = (
            'Auto-archived by the board: nothing was left that it could run. Failed: %s. Stale: %s. '
            "Blocked behind them: %s. Reports are intact — `st review` reads them; the Finished tab's "
            'reopen puts the tree back if a task is to be reset.' % (s['failed'], s['stale'], s['blocked'])
        )
        audit(
            {
                'cmd': 'archive:settled',
                'tree': tree['id'],
                'ok': True,
                'model': 'board',
                'error': why + ' — quiet since ' + iso(s['since']),
            }
        )
        archive_tree(tree, why, note)
        out.append(tree['id'])
    return out


def cmd_done(ident, body):
    need_role(ident, 'executor')
    tree, task = _held_task(ident, body)
    if task['status'] == 'queued':
        raise Refuse(
            f'#{task["id"]} is queued, not executing — nothing to report yet. '
            f'`st await` first, or `st release` the reservation.'
        )
    report = body.get('report')
    if not isinstance(report, dict):
        raise Refuse('report must be a JSON object — run `st report-template`')
    problems = []
    summary = str(report.get('summary', '')).strip()
    if len(summary) < CFG['min_summary_chars']:
        problems.append(f'summary must be ≥{CFG["min_summary_chars"]} chars and say WHAT was done')
    ver = report.get('verification')
    if not isinstance(ver, dict) or not str(ver.get('cmd', '')).strip() or not str(ver.get('output', '')).strip():
        problems.append(
            'verification.cmd and verification.output are required: the exact command '
            'you ran to prove the work and its literal output'
        )
    if 'not_done' not in report or not str(report.get('not_done')).strip():
        problems.append("not_done is required — list what is NOT done, or the word 'none'")
    problems += _check_files(task, report)
    if problems:
        raise Refuse('report rejected:\n  - ' + '\n  - '.join(problems))

    t = now()
    report = {
        'summary': summary,
        'changed_files': [str(p) for p in (report.get('changed_files') or [])],
        'verification': {'cmd': str(ver['cmd'])[:2000], 'output': str(ver['output'])[-4000:]},
        'not_done': str(report['not_done']).strip()[:2000],
        'notes': str(report.get('notes', '')).strip()[:4000],
        'submitted_at': t,
        'by': ident['model'],
        'session_id': ident['session_id'],
    }
    task['report'] = report
    vr = _run_verify(task, tree)
    task['verify_result'] = vr
    if vr and vr['exit'] != 0:
        task['status'] = 'failed'
        task['stale'] = False
        task['lease_until'] = 0
        task['finished_at'] = t
        task['history'].append({'at': t, 'event': 'report accepted but verify_cmd FAILED', 'exit': vr['exit']})
        save_tree(tree)
        audit(
            {
                'cmd': 'task:failed',
                'tree': tree['id'],
                'task': task['id'],
                'ok': True,
                'model': ident['model'],
                'error': 'verify_cmd exited %s' % vr['exit'],
            }
        )
        return {
            'ok': False,
            'verified': False,
            'status': 'failed',
            'msg': f'verify_cmd exited {vr["exit"]} — task marked FAILED. Do not re-claim it; '
            f'the creator decides. Output tail:\n{vr["tail"][-1500:]}',
            'creator_notify': failure_notify(tree, task, 'verify_cmd failed on st done'),
        }
    task['status'] = 'finished'
    task['stale'] = False
    task['lease_until'] = 0
    task['finished_at'] = t
    task['history'].append({'at': t, 'event': 'finished', 'verified': bool(vr)})
    if task.get('claimed_at'):
        task['actual_minutes'] = round((t - task['claimed_at']) / 60, 1)
    stamp_task_usage(tree, task)
    notice = _maybe_archive(tree)
    if not notice:
        save_tree(tree)
    kick_spawner()  # dependants may be ready now; a slot is free
    left = sum(1 for x in tree['tasks'] if x['status'] == 'todo')
    return {
        'ok': True,
        'status': 'finished',
        'verified': bool(vr) and vr['exit'] == 0,
        'tree_archived': bool(notice),
        'todo_left': left,
        'creator_notify': (
            {
                'model': notice['creator'].get('model'),
                'session_id': notice['creator'].get('session_id'),
                'peer_name': notice['creator_peer']['name'],
                'alive': notice['creator_peer']['alive'],
                'counts': notice['counts'],
            }
            if notice
            else None
        ),
        'tasks_this_session': session_task_count(ident['session_id']),
        'max_tasks_per_session': CFG['max_tasks_per_session'],
    }


def failure_notify(tree, task, how):
    """Payload the CLI turns into a direct SendMessage to the creator when a
    task fails (st fail, or verify_cmd failing on st done). Same peer lookup as
    the archive notice, so the creator is woken the moment it happens instead
    of `settle_archive_minutes` later."""
    creator = tree.get('created_by') or {}
    peer = peer_for(creator.get('session_id'))
    rep = task.get('report') or {}
    if not peer['alive']:
        operator_notify(
            'Session Tree: task %s#%s FAILED, nobody to tell' % (tree['id'][-6:], task['id']),
            '%s\n%s. The creator session %s is not running, so no agent was woken; the tree '
            'settles and auto-archives in %s min unless the task is reset. Open a Fable session '
            'and run: st status'
            % (
                task.get('title', '')[:160],
                how,
                (creator.get('session_id') or '')[:8],
                CFG.get('settle_archive_minutes', 20),
            ),
            tree_id=tree['id'],
            task_id=task['id'],
        )
    return {
        'model': creator.get('model'),
        'session_id': creator.get('session_id'),
        'peer_name': peer['name'],
        'alive': peer['alive'],
        'how': how,
        'tree': tree['id'],
        'task': task['id'],
        'title': task.get('title', ''),
        'summary': (rep.get('summary') or '')[:300],
    }


def cmd_fail(ident, body):
    need_role(ident, 'executor')
    tree, task = _held_task(ident, body)
    if task['status'] == 'queued':
        raise Refuse(f'#{task["id"]} is queued, not executing — `st release` it instead of failing it')
    reason = str(body.get('reason', '')).strip()
    if len(reason) < CFG['min_fail_reason_chars']:
        raise Refuse('reason required: what was tried, what broke, what a retry needs')
    t = now()
    task['status'] = 'failed'
    task['stale'] = False
    task['lease_until'] = 0
    task['finished_at'] = t
    task['report'] = {
        'summary': 'FAILED: ' + reason[:2000],
        'changed_files': [],
        'verification': {'cmd': '', 'output': ''},
        'not_done': 'task failed',
        'notes': str(body.get('notes', ''))[:4000],
        'submitted_at': t,
        'by': ident['model'],
        'session_id': ident['session_id'],
    }
    task['history'].append({'at': t, 'event': 'failed', 'reason': reason[:300]})
    if task.get('claimed_at'):
        task['actual_minutes'] = round((t - task['claimed_at']) / 60, 1)
    stamp_task_usage(tree, task)
    save_tree(tree)
    kick_spawner()
    audit(
        {
            'cmd': 'task:failed',
            'tree': tree['id'],
            'task': task['id'],
            'ok': True,
            'model': ident['model'],
            'error': reason[:200],
        }
    )
    return {'ok': True, 'status': 'failed', 'creator_notify': failure_notify(tree, task, 'st fail')}
