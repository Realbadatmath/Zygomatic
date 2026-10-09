# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Spawning, reaping and sweeping the board's own executor sessions.

Moved verbatim from session_tree_server.py lines 1167-1775.
"""

from ._base import CONFIG_PATH, LOCK, SELF_HOST, _zyg_log, json, os, subprocess, time, uuid
from .storage import CFG, audit, iso, list_trees, now, save_tree
from .peers import _claude_bin, promote_planned
from .resources import admission, queue_state
from .task_helpers import deps_done, sweep_leases
from .spawner_state import SPAWNED, SPAWN_HISTORY, SPAWN_LOGS, _spawn_evt, _spawn_stats
from .usage import (
    _auth_fail_in_log,
    _hold_from_message,
    _limit_hit_in_log,
    auth_hold_active,
    usage_hold_active,
    usage_state,
)
from .metrics import ZERO_USAGE, eta_check, spawn_record, stamp_usage_for_session, transcript_usage

# Resolved on first call, not on import: completion.settle_sweep is defined after this
# section in the original file, so importing it here would close a cycle.


def settle_sweep(*args, **kwargs):
    from .completion import settle_sweep as _impl

    return _impl(*args, **kwargs)


EXECUTOR_PROMPT = """You are a Session Tree executor. The board spawned this session for exactly ONE task: {tree}#{task}.
Do these steps in order and nothing else:
1. Run `st rules` once and follow it — you are the Executor role.
2. Run `st claim {tree} {task}`. It prints the brief. If it prints QUEUED, run `st await {tree} {task}` in a BACKGROUND shell and do no work until it exits with the brief.
3. Do the task in the cwd the brief names. Run `st touch {tree} {task} "note"` at least once an hour.
4. Write the report (`st report-template` shows the shape) and run `st done {tree} {task} --report FILE`, or `st fail {tree} {task} "why"`.
5. Stop. Never run `st next`, never claim another task, never spawn subagents. If `st done` prints TREE ARCHIVED, or if `st fail` / a VERIFY FAILED `st done` prints TASK FAILED — notify the creator, send the one-line SendMessage it shows (the creator must learn of a failure from you, at once, not from the board later), then stop.
If `st claim` is refused, print the refusal and stop."""


def kick_spawner():
    _spawn_evt.set()


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def spawn_reservation_live(r):
    """A reservation is live while its process is alive and younger than
    spawn_reserve_minutes. Anything else is cleared by the next sweep."""
    if not r:
        return False
    if now() - (r.get('at') or 0) > CFG['spawn_reserve_minutes'] * 60:
        return False
    ent = SPAWNED.get(r.get('session_id'))
    if ent is not None:
        return ent.get('exit') is None
    return _pid_alive(r.get('pid'))


def _spawn_env(sid):
    env = os.environ.copy()
    for k in ('CLAUDECODE', 'CLAUDE_CODE_SESSION_ID', 'CLAUDE_PID', 'CLAUDE_CODE_ENTRYPOINT'):
        env.pop(k, None)
    home = os.path.expanduser('~')
    path = env.get('PATH', '/usr/local/bin:/usr/bin:/bin')
    for extra in (os.path.join(home, '.local', 'bin'), '/usr/local/bin'):
        if extra not in path.split(':'):
            path = extra + ':' + path
    env['PATH'] = path
    env['HOME'] = home
    # The address the board is actually listening on (SELF_HOST), not a baked-in literal.
    # The spawned executor runs on this machine, so this stays loopback on a default bind.
    env['SESSION_TREE_URL'] = 'http://%s:%d' % (SELF_HOST, CFG['port'])
    env['SESSION_TREE_SPAWNED'] = sid
    # Measured 2026-09-06: an interactive session exports CLAUDE_CODE_SESSION_ID to
    # its Bash tool, a `claude -p` session does NOT — the first live spawn's `st`
    # was refused with "CLAUDE_CODE_SESSION_ID is not set". We chose the uuid
    # (--session-id), so we export it ourselves; the transcript it names is the
    # one the harness writes, so the role gate still reads the real model.
    env['CLAUDE_CODE_SESSION_ID'] = sid
    return env


def spawn_executor(tree, task):
    """Launch one executor for one task. Caller holds LOCK and saves the tree."""
    b = _claude_bin()
    if not b:
        raise RuntimeError('claude binary not found (config claude_bin / PATH)')
    sid = str(uuid.uuid4())
    cwd = task.get('cwd') or tree.get('cwd') or CFG['spawn_cwd_default']
    if not os.path.isdir(cwd):
        cwd = CFG['spawn_cwd_default']
    prompt = EXECUTOR_PROMPT.format(tree=tree['id'], task=task['id'])
    cmd = [
        b,
        '-p',
        '--model',
        CFG['executor_model'],
        '--session-id',
        sid,
        '--permission-mode',
        CFG['spawn_permission_mode'],
    ]
    if float(CFG.get('spawn_budget_usd') or 0) > 0:
        cmd += ['--max-budget-usd', str(CFG['spawn_budget_usd'])]
    cmd.append(prompt)
    t = now()
    logp = os.path.join(
        SPAWN_LOGS,
        '%s-%s-%02d-%s.log' % (time.strftime('%Y%m%d-%H%M%S', time.localtime(t)), tree['id'][-6:], task['id'], sid[:8]),
    )
    logf = open(logp, 'ab')
    logf.write(
        (
            '# %s  spawn %s#%d  sid %s  cwd %s\n# %s\n'
            % (iso(t), tree['id'], task['id'], sid, cwd, ' '.join(cmd[:-1]) + " '<prompt>'")
        ).encode()
    )
    logf.flush()
    p = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=logf,
        stderr=subprocess.STDOUT,
        env=_spawn_env(sid),
        # own session/process group: a board restart must never take an
        # executor down with it (KillMode=process on the unit is the other half)
        start_new_session=True,
    )
    logf.close()
    SPAWNED[sid] = {
        'pid': p.pid,
        'popen': p,
        'tree': tree['id'],
        'task': task['id'],
        'weight': task['weight'],
        'started_at': t,
        'log': logp,
        'exit': None,
        'exited_at': None,
    }
    task['spawned_for'] = {'session_id': sid, 'pid': p.pid, 'at': t}
    task['history'].append({'at': t, 'event': 'executor spawned by the board', 'session': sid, 'pid': p.pid})
    spawn_record(
        {
            'sid': sid,
            'pid': p.pid,
            'tree': tree['id'],
            'task': task['id'],
            'weight': task['weight'],
            'started_at': t,
            'model': CFG['executor_model'],
        }
    )
    _spawn_stats['total'] += 1
    audit(
        {
            'cmd': 'spawn',
            'tree': tree['id'],
            'task': task['id'],
            'ok': True,
            'model': CFG['executor_model'],
            'session': sid[:8],
            'role': 'spawner',
            'error': 'pid %d  %s' % (p.pid, os.path.basename(logp)),
        }
    )
    return sid


def _kill_spawn(ent, why):
    try:
        os.killpg(os.getpgid(ent['pid']), 15)
    except Exception:
        try:
            os.kill(ent['pid'], 15)
        except Exception as _exc:
            _zyg_log.debug('spawn pid %s already gone, nothing to kill: %s', ent['pid'], _exc)
    audit(
        {
            'cmd': 'spawn:kill',
            'tree': ent['tree'],
            'task': ent['task'],
            'ok': True,
            'session': (ent.get('sid') or '')[:8],
            'role': 'spawner',
            'error': why,
        }
    )


def _task_reserved_sids(trees=None):
    """Session ids a todo task is reserved for (spawned, not yet claimed)."""
    out = set()
    for t in trees if trees is not None else list_trees():
        for x in t['tasks']:
            r = x.get('spawned_for') if x['status'] == 'todo' else None
            if r and r.get('session_id'):
                out.add(r['session_id'])
    return out


def _task_holder_sids():
    """Session ids holding an executing/queued task (spawned or hand-opened)."""
    out = set()
    for t in list_trees():
        for x in t['tasks']:
            if x['status'] in ('executing', 'queued') and not x.get('stale'):
                sid = (x.get('claimed_by') or {}).get('session_id')
                if sid:
                    out.add(sid)
    return out


def _executor_died_holding_task(sid, code, trees, t, limit_hit=None):
    """Measured 2026-09-06 13:31: a board-spawned executor claimed cinematic#7, hit a
    permission denial, printed a question nobody can answer (`claude -p` has no
    operator) and exited — and the task sat 'executing' until its 180-min lease
    ran out. A dead process cannot touch, finish or fail: the moment its exit is
    reaped the task it held is put back to todo ONCE (one automatic retry, same
    brief, after the spawn cooldown); a second death leaves it stale for the
    operator, exactly as a lease expiry would."""
    changed = set()
    for tree in trees:
        for task in tree['tasks']:
            cb = task.get('claimed_by') or {}
            if task['status'] != 'executing' or cb.get('session_id') != sid:
                continue
            died = 'executor %s exited (code %s) without done/fail' % (sid[:8], code)
            if limit_hit:
                # not the executor's fault and not a retry: Claude's usage window is exhausted.
                # Back to todo, no cooldown — the usage hold decides when it is spawned again.
                task['history'].append(
                    {
                        'at': t,
                        'event': died + ' — USAGE LIMIT (%s); back to todo, '
                        're-spawned when the window resets' % limit_hit[:120],
                        'previous': 'executing',
                        'prior_progress': task.get('progress'),
                    }
                )
                task.update(
                    status='todo',
                    stale=False,
                    claimed_by=None,
                    claimed_at=None,
                    lease_until=0,
                    queued_at=None,
                    progress='',
                    spawned_for=None,
                    spawn_cooldown_until=0,
                )
                audit(
                    {
                        'cmd': 'spawn:died',
                        'tree': tree['id'],
                        'task': task['id'],
                        'ok': False,
                        'session': sid[:8],
                        'role': 'spawner',
                        'error': died + ' — usage limit, retried after the reset',
                    }
                )
                changed.add(tree['id'])
                continue
            if task.get('attempts', 0) <= 1 and not task.get('auto_retried'):
                task['history'].append(
                    {
                        'at': t,
                        'event': died + ' — auto-reset to todo for ONE retry',
                        'previous': 'executing',
                        'prior_progress': task.get('progress'),
                    }
                )
                task.update(
                    status='todo',
                    stale=False,
                    claimed_by=None,
                    claimed_at=None,
                    lease_until=0,
                    queued_at=None,
                    progress='',
                    spawned_for=None,
                    auto_retried=True,
                    spawn_cooldown_until=t + CFG['spawn_cooldown_s'],
                )
                audit(
                    {
                        'cmd': 'spawn:died',
                        'tree': tree['id'],
                        'task': task['id'],
                        'ok': False,
                        'session': sid[:8],
                        'role': 'spawner',
                        'error': died + ' — retry once',
                    }
                )
            elif not task.get('stale'):
                task['stale'] = True
                task['history'].append({'at': t, 'event': died + ' — stale (retry already used)'})
                audit(
                    {
                        'cmd': 'spawn:died',
                        'tree': tree['id'],
                        'task': task['id'],
                        'ok': False,
                        'session': sid[:8],
                        'role': 'spawner',
                        'error': died + ' — stale, operator decision',
                    }
                )
            changed.add(tree['id'])
    return changed


def reap_spawned(trees):
    """Record exits; clear reservations whose session died or overstayed
    without claiming; apply the per-task cooldown and the global brake."""
    changed = set()
    t = now()
    for sid, ent in list(SPAWNED.items()):
        ent['sid'] = sid
        if ent['exit'] is None:
            code = ent['popen'].poll()
            if code is not None:
                ent['exit'] = code
                ent['exited_at'] = t
                ent['limit_hit'] = _limit_hit_in_log(ent['log'])
                ent['auth_fail'] = _auth_fail_in_log(ent['log'])
                if ent['auth_fail']:
                    st = _spawn_stats
                    st['auth_broken_since'] = st.get('auth_broken_since') or t
                    st['auth_last_try'] = t
                    st['auth_msg'] = ent['auth_fail']
                    if t - (st.get('auth_last_audit') or 0) > 1800:
                        st['auth_last_audit'] = t
                        audit(
                            {
                                'cmd': 'spawn:auth',
                                'tree': ent['tree'],
                                'task': ent['task'],
                                'ok': False,
                                'role': 'spawner',
                                'error': 'EXECUTOR LOGIN BROKEN since %s: %s -- run `claude login` on '
                                'the login user; one retry spawn every %d s'
                                % (
                                    iso(st['auth_broken_since']),
                                    ent['auth_fail'][:160],
                                    CFG.get('spawn_auth_retry_s', 900),
                                ),
                            }
                        )
                SPAWN_HISTORY.append(
                    {
                        k: ent[k]
                        for k in ('sid', 'pid', 'tree', 'task', 'started_at', 'exit', 'exited_at', 'log', 'limit_hit')
                    }
                )
                del SPAWN_HISTORY[:-30]
                audit(
                    {
                        'cmd': 'spawn:exit',
                        'tree': ent['tree'],
                        'task': ent['task'],
                        'ok': code == 0,
                        'session': sid[:8],
                        'role': 'spawner',
                        'error': 'exit %s after %d s  %s%s'
                        % (
                            code,
                            t - ent['started_at'],
                            os.path.basename(ent['log']),
                            ('  USAGE LIMIT: ' + ent['limit_hit']) if ent['limit_hit'] else '',
                        ),
                    }
                )
                if ent['limit_hit']:
                    _hold_from_message(ent['limit_hit'], t)
                claimed, ch = stamp_usage_for_session(sid, trees)
                if claimed and _spawn_stats.get('auth_broken_since'):
                    audit(
                        {
                            'cmd': 'spawn:auth',
                            'ok': True,
                            'role': 'spawner',
                            'tree': ent['tree'],
                            'task': ent['task'],
                            'error': 'executor login works again (a spawned session claimed)',
                        }
                    )
                    _spawn_stats.update(auth_broken_since=0, auth_last_try=0, auth_msg='', auth_last_audit=0)
                changed |= ch
                changed |= _executor_died_holding_task(sid, code, trees, t, ent['limit_hit'])
                u = transcript_usage(sid)
                spawn_record(
                    {
                        'sid': sid,
                        'exit': code,
                        'exited_at': t,
                        'claimed': claimed,
                        'limit_hit': bool(ent['limit_hit']),
                        'usage': ({k: u.get(k) for k in ZERO_USAGE} if u else None),
                    }
                )
        if ent['exit'] is not None and t - (ent['exited_at'] or t) > 3600:
            del SPAWNED[sid]
    # 2026-09-20: a session that has neither a claimed task nor a reservation is a ghost — it did its
    # one task (or never claimed) and never exited. It still counted as a live spawn of its weight, so
    # one lingering heavy executor held the single heavy slot for 2 h 40 min and the next tree's render
    # task sat in todo. Ghosts get spawn_linger_s of grace (SendMessage/notify after `st done`), then die.
    holders = _task_holder_sids()
    reserved = _task_reserved_sids(trees)
    for sid, ent in list(SPAWNED.items()):
        if ent['exit'] is not None:
            continue
        if sid in holders or sid in reserved:
            ent['idle_since'] = None
            continue
        if not ent.get('idle_since'):
            ent['idle_since'] = t
        elif t - ent['idle_since'] > CFG.get('spawn_linger_s', 300):
            _kill_spawn(
                ent,
                'lingered %d s after leaving its task (no claim, no reservation) — killed so it '
                'cannot hold a %s slot' % (t - ent['idle_since'], ent['weight']),
            )
            ent['idle_since'] = None
    for tree in trees:
        for task in tree['tasks']:
            r = task.get('spawned_for')
            if not r:
                continue
            if task['status'] != 'todo':
                task['spawned_for'] = None  # claimed via another path; nothing to hold
                changed.add(tree['id'])
                continue
            if spawn_reservation_live(r):
                continue
            ent = SPAWNED.get(r['session_id'])
            overstayed = ent is not None and ent['exit'] is None
            if overstayed:
                _kill_spawn(ent, 'no claim within %d min — killed' % CFG['spawn_reserve_minutes'])
            why = 'spawned session %s %s without claiming' % (
                r['session_id'][:8],
                'overstayed' if overstayed else 'exited',
            )
            task['spawned_for'] = None
            if ent is not None and ent.get('auth_fail'):
                # broken login, not a broken executor: no cooldown, no brake count; the auth hold paces retries
                task['spawn_cooldown_until'] = 0
                task['history'].append(
                    {
                        'at': t,
                        'event': why
                        + ' -- EXECUTOR LOGIN BROKEN (%s); retried every %d s'
                        % (ent['auth_fail'][:80], CFG.get('spawn_auth_retry_s', 900)),
                    }
                )
                changed.add(tree['id'])
                continue
            if ent is not None and ent.get('limit_hit'):
                # Claude's usage window, not a broken executor: no cooldown, no brake count.
                # The usage hold (armed when the exit was reaped) decides when it is re-spawned.
                task['spawn_cooldown_until'] = 0
                task['history'].append({'at': t, 'event': why + ' — USAGE LIMIT; re-spawned when the window resets'})
                changed.add(tree['id'])
                continue
            task['spawn_cooldown_until'] = t + CFG['spawn_cooldown_s']
            task['history'].append(
                {'at': t, 'event': why + ' — reservation cleared, cooldown %ds' % CFG['spawn_cooldown_s']}
            )
            _spawn_stats['noclaim_streak'] += 1
            if _spawn_stats['noclaim_streak'] >= CFG['spawn_brake_after']:
                _spawn_stats['brake_until'] = t + CFG['spawn_brake_minutes'] * 60
                _spawn_stats['noclaim_streak'] = 0
                audit(
                    {
                        'cmd': 'spawn:brake',
                        'ok': False,
                        'role': 'spawner',
                        'model': CFG['executor_model'],
                        'error': '%d consecutive spawns exited without claiming — auto-spawn paused %d min; '
                        'read spawn_logs/' % (CFG['spawn_brake_after'], CFG['spawn_brake_minutes']),
                    }
                )
            changed.add(tree['id'])
    return changed


def spawn_sweep(force=False):
    """One pass: reap, then launch executors for ready tasks up to the caps.
    Returns the list of spawned sids. Caller holds LOCK."""
    promote_planned('auto (spawner found no active tree)')
    settle_sweep()  # a tree nothing can run any more archives itself (and promotes the next)
    trees = list_trees()
    changed = set()
    for tree in trees:
        if sweep_leases(tree):
            changed.add(tree['id'])
    changed |= reap_spawned(trees)
    changed |= eta_check(trees)
    spawned = []
    t = now()
    if (
        (CFG.get('auto_spawn') or force)
        and t >= _spawn_stats['brake_until']
        and not usage_hold_active()
        and not auth_hold_active()
    ):
        pending = [e for e in SPAWNED.values() if e['exit'] is None]
        holders = _task_holder_sids()
        reserved = _task_reserved_sids(trees)
        # only sessions that hold a task or are reserved for one occupy a slot; ghosts (see reap_spawned) never do
        live = len(holders | {e['sid'] for e in pending if e.get('sid') in reserved})
        qs = queue_state()
        pend_w = {'heavy': 0, 'light': 0}
        for e in pending:
            if e.get('sid') not in holders and e.get('sid') in reserved:
                pend_w[e['weight']] += 1
        for tree in trees:
            for task in sorted(tree['tasks'], key=lambda x: (x['weight'] != 'light', x['id'])):
                if live >= CFG['max_executors']:
                    break
                if task['status'] != 'todo' or not deps_done(tree, task):
                    continue  # stale takeovers are an operator decision (extend or reset), never automatic
                if task.get('spawned_for') or t < (task.get('spawn_cooldown_until') or 0):
                    continue
                slots = qs[task['weight'] + '_slots']
                used = qs[task['weight'] + '_used'] + pend_w[task['weight']]
                adm = admission(task)
                if used >= slots or adm is not None:
                    why = adm or (
                        '%s slot busy (%d/%d used by executing/queued tasks + reserved spawns)'
                        % (task['weight'], used, slots)
                    )
                    sb = task.get('spawn_blocked') or {'since': t, 'audited': False}
                    sb['why'] = why[:200]
                    if not sb.get('audited') and t - sb['since'] > CFG.get('spawn_starve_s', 600):
                        sb['audited'] = True
                        audit(
                            {
                                'cmd': 'spawn:starved',
                                'tree': tree['id'],
                                'task': task['id'],
                                'ok': False,
                                'role': 'spawner',
                                'error': 'ready for %d min, not spawned: %s' % ((t - sb['since']) // 60, why[:200]),
                            }
                        )
                    task['spawn_blocked'] = sb
                    changed.add(tree['id'])
                    continue
                if task.get('spawn_blocked'):
                    task['spawn_blocked'] = None
                try:
                    sid = spawn_executor(tree, task)
                except Exception as e:
                    _spawn_stats['last_error'] = str(e)
                    audit(
                        {
                            'cmd': 'spawn',
                            'tree': tree['id'],
                            'task': task['id'],
                            'ok': False,
                            'role': 'spawner',
                            'error': str(e)[:300],
                        }
                    )
                    break
                spawned.append(sid)
                pend_w[task['weight']] += 1
                live += 1
                changed.add(tree['id'])
    by_id = {x['id']: x for x in trees}
    for tid in changed:
        if tid in by_id:
            save_tree(by_id[tid])
    return spawned


def spawner_state():
    live = [
        {
            'sid': sid,
            'pid': e['pid'],
            'tree': e['tree'],
            'task': e['task'],
            'weight': e['weight'],
            'started_at': e['started_at'],
            'log': os.path.basename(e['log']),
            'claimed': sid in _task_holder_sids(),
        }
        for sid, e in SPAWNED.items()
        if e['exit'] is None
    ]
    return {
        'auto_spawn': bool(CFG.get('auto_spawn')),
        'max_executors': CFG['max_executors'],
        'executor_model': CFG['executor_model'],
        'live': live,
        'live_total': len(_task_holder_sids() | {x['sid'] for x in live}),
        'brake_until': _spawn_stats['brake_until'],
        'total_spawned': _spawn_stats['total'],
        'last_error': _spawn_stats['last_error'],
        'usage': usage_state(),
        'auth': {
            'broken_since': _spawn_stats.get('auth_broken_since') or 0,
            'last_try': _spawn_stats.get('auth_last_try') or 0,
            'msg': _spawn_stats.get('auth_msg') or '',
            'retry_s': CFG.get('spawn_auth_retry_s', 900),
        },
        'recent_exits': SPAWN_HISTORY[-8:],
    }


def spawner_thread():
    while True:
        _spawn_evt.wait(CFG['spawn_sweep_s'])
        _spawn_evt.clear()
        try:
            with LOCK:
                spawn_sweep()
        except Exception as e:
            _spawn_stats['last_error'] = repr(e)
            _zyg_log.info(f'[session-tree] spawner error: {e!r}')


def save_config():
    with open(CONFIG_PATH, 'w') as f:
        json.dump({k: v for k, v in CFG.items()}, f, indent=2)
