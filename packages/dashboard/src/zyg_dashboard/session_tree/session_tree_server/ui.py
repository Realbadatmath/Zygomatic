# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The browser-only payloads and the operator actions behind them.

Moved verbatim from session_tree_server.py lines 3493-3697.
"""

from ._base import ACTIVE, FINISHED, PLANNED, SUGGESTED, os
from .storage import CFG, _tree_path, iso, list_trees, load_tree, now, save_tree
from .peers import NOTIFY, activate_tree, archive_tree, notice_for, planned_trees, promote_planned, suggested_trees
from .resources import queue_state, resources, wait_queue
from .task_helpers import sweep_leases
from .spawner_state import SPAWNED, _spawn_stats
from .usage import _usage, _usage_evt, _usage_release, usage_hold_active
from .spawner import _kill_spawn, kick_spawner, save_config, spawn_sweep, spawner_state
from .completion import tree_settle
from .creator_commands import _reset_task


# ───────────────────────────── UI (browser only) ─────────────────────────────


def ui_active():
    promote_planned('auto (UI poll found no active tree)')
    trees = list_trees()
    for t in trees:
        if sweep_leases(t):
            save_tree(t)
    for t in trees:
        t['settle'] = tree_settle(t)  # display only — never persisted
    wq = []
    for w in ('heavy', 'light'):
        for i, (t, x) in enumerate(wait_queue(w)):
            wq.append({'tree': t['id'], 'task': x['id'], 'weight': w, 'position': i + 1})
    return {
        'trees': trees,
        'queue': queue_state(),
        'wait_queue': wq,
        'resources': resources(),
        'spawner': spawner_state(),
        'config': {
            k: CFG[k]
            for k in (
                'heavy_slots',
                'light_slots',
                'lease_minutes',
                'max_tasks_per_session',
                'max_tasks_per_tree',
                'gpu_busy_util_pct',
                'vram_reserve_gb',
                'ram_reserve_gb',
                'queue_wait_stale_minutes',
                'auto_spawn',
                'max_executors',
                'settle_archive_minutes',
                'executor_model',
                'spawn_permission_mode',
            )
        },
        'now': now(),
    }


def ui_planned():
    trees = planned_trees()
    for i, t in enumerate(trees):
        t['position'] = i + 1
    return {'trees': trees, 'active': [{'id': a['id'], 'title': a['title']} for a in list_trees(ACTIVE)], 'now': now()}


def ui_suggested():
    trees = suggested_trees()
    for i, t in enumerate(trees):
        t['position'] = i + 1
    return {'trees': trees, 'active': [{'id': a['id'], 'title': a['title']} for a in list_trees(ACTIVE)], 'now': now()}


def ui_counts():
    """Tab badge numbers only. Polled by every open page for all tabs at once, so
    it must stay cheap: count tree files per folder, parse nothing, take no lock,
    and promote nothing (ui_active owns the planned->active promotion)."""

    def n(folder):
        try:
            return sum(1 for f in os.listdir(folder) if f.endswith('.json'))
        except FileNotFoundError:
            return 0

    return {'active': n(ACTIVE), 'planned': n(PLANNED), 'modular': n(SUGGESTED), 'finished': n(FINISHED), 'now': now()}


def ui_finished():
    trees = list(reversed(sorted(list_trees(FINISHED), key=lambda t: t.get('finished_at') or 0)))
    for t in trees:
        t['notice'] = notice_for(t['id'])
    return {'trees': trees, 'now': now()}


def ui_action(body):
    action = body.get('action')
    if action == 'set_auto_spawn':
        CFG['auto_spawn'] = bool(body.get('value'))
        save_config()
        _spawn_stats['brake_until'] = 0
        _spawn_stats['noclaim_streak'] = 0
        if CFG['auto_spawn']:
            kick_spawner()
        return {'ok': True, 'auto_spawn': CFG['auto_spawn']}
    if action == 'usage_poll_now':
        _usage['want_poll'] = True
        _usage_evt.set()
        return {'ok': True}
    if action == 'spawn_now':
        # One pass regardless of the auto switch (caps still apply). An explicit click also
        # clears a usage hold: if the limit is still in force the spawns re-arm it themselves.
        _spawn_stats['brake_until'] = 0
        if usage_hold_active():
            _usage_release('cleared by operator (spawn now)')
        sids = spawn_sweep(force=True)
        return {
            'ok': True,
            'spawned': [s[:8] for s in sids],
            'msg': '' if sids else 'nothing to spawn: no ready task, or caps/slots/resources are full',
        }
    if action == 'accept_suggested':
        # Operator accepted a modularization tree: run it now if nothing is
        # active, otherwise it joins the planned queue like any other tree.
        tree = load_tree(body.get('tree', ''), SUGGESTED)
        if not tree:
            return {'ok': False, 'error': 'no such suggested tree'}
        os.remove(_tree_path(tree['id'], SUGGESTED))
        if list_trees(ACTIVE):
            tree.update(status='planned', planned_at=now())
            save_tree(tree, PLANNED)
            return {
                'ok': True,
                'planned': True,
                'msg': f'{tree["id"]} accepted → Planned queue (a tree is active; it runs when its turn comes)',
            }
        activate_tree(tree, 'operator (UI accept)')
        return {'ok': True, 'planned': False, 'msg': f'{tree["id"]} accepted → ACTIVE, executors spawning'}
    if action == 'reject_suggested':
        tree = load_tree(body.get('tree', ''), SUGGESTED)
        if not tree:
            return {'ok': False, 'error': 'no such suggested tree'}
        os.remove(_tree_path(tree['id'], SUGGESTED))
        return {'ok': True, 'msg': f'{tree["id"]} rejected and removed'}
    if action == 'kill_spawned':
        ent = SPAWNED.get(str(body.get('sid') or ''))
        if not ent or ent['exit'] is not None:
            return {'ok': False, 'error': 'no live spawned session with that id'}
        ent['sid'] = body.get('sid')
        _kill_spawn(ent, 'killed by operator (UI)')
        return {'ok': True}
    if action == 'reset_task':
        tree = load_tree(body.get('tree', ''))
        task = next((x for x in tree['tasks'] if x['id'] == body.get('task')), None) if tree else None
        if not task:
            return {'ok': False, 'error': 'no such task'}
        _reset_task(task, 'reset by operator (UI)')
        save_tree(tree)
        return {'ok': True}
    if action == 'extend_lease':
        # Renew a lease WITHOUT touching claimed_by. A stale task is still held by
        # its original session — cmd_touch/cmd_done check the session id, not the
        # stale flag; staleness only makes the task claimable by someone else. So
        # when the holder is alive but starved (blocked on the shared GPU lock,
        # say) the fix is to push lease_until out, not reset_task, which strips
        # the claim and throws away the work in flight.
        tree = load_tree(body.get('tree', ''))
        task = next((x for x in tree['tasks'] if x['id'] == body.get('task')), None) if tree else None
        if not task:
            return {'ok': False, 'error': 'no such task'}
        if task['status'] != 'executing':
            return {'ok': False, 'error': f'#{task["id"]} is {task["status"]}, not executing'}
        t = now()
        task['stale'] = False
        task['lease_until'] = t + CFG['lease_minutes'] * 60
        task['history'].append(
            {'at': t, 'event': 'lease extended by operator', 'by': str(body.get('by') or 'operator')}
        )
        save_tree(tree)
        return {'ok': True, 'lease_until': iso(task['lease_until'])}
    if action == 'close_tree':
        tree = load_tree(body.get('tree', ''))
        if not tree:
            return {'ok': False, 'error': 'no such tree'}
        archive_tree(tree, 'operator (UI)')
        return {'ok': True}
    if action == 'delete_tree':
        for folder in (ACTIVE, PLANNED, FINISHED):
            p = _tree_path(body.get('tree', ''), folder)
            if p and os.path.exists(p):
                os.remove(p)
                np_ = os.path.join(NOTIFY, body.get('tree', '') + '.json')
                if os.path.exists(np_):
                    os.remove(np_)
                promoted = promote_planned('auto (%s deleted)' % body.get('tree')) if folder == ACTIVE else None
                return {'ok': True, 'promoted': promoted['id'] if promoted else None}
        return {'ok': False, 'error': 'no such tree'}
    if action == 'activate_tree':
        # Operator override: activate a planned tree now, even out of rank
        # order or beside an active tree. Agents never get this.
        tree = load_tree(body.get('tree', ''), PLANNED)
        if not tree:
            return {'ok': False, 'error': 'no such planned tree'}
        activate_tree(tree, 'operator (UI)')
        return {'ok': True}
    if action == 'reopen_tree':
        tree = load_tree(body.get('tree', ''), FINISHED)
        if not tree:
            return {'ok': False, 'error': 'no such finished tree'}
        os.remove(_tree_path(tree['id'], FINISHED))
        tree.update(finished_at=None, closed_by=None, close_note=None)
        if list_trees(ACTIVE):
            # one tree at a time: a reopened tree queues behind the active one
            tree.update(status='planned', planned_at=now())
            save_tree(tree, PLANNED)
            return {'ok': True, 'planned': True}
        activate_tree(tree, 'operator (UI reopen)')
        return {'ok': True, 'planned': False}
    return {'ok': False, 'error': 'unknown action'}
