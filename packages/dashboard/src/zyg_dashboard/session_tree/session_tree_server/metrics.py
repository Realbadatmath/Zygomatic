# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Token/time attribution per task, the ETA log and the Metrics tab payload.

Moved verbatim from session_tree_server.py lines 1776-2305.
"""

from ._base import ACTIVE, AUDIT, DATA, FINISHED, LOCK, _zyg_log, datetime, json, os
from .storage import audit, list_trees, load_tree, now, save_tree
from .identity import _find_transcript


# ───────────────────────────── metrics / ETA ─────────────────────────────────
# Tokens come from the harness's own usage records on every assistant turn of a
# session's transcript (the same file the role gate reads). Time on task comes
# from task history. ETA is the creator's estimate for the whole tree, logged at
# create and compared with reality at archive — the board NEVER acts on it: an
# overrun writes one audit line (`eta:overrun`) and shows on the Metrics tab.

SERVER_STARTED = now()
SPAWNS_LOG = os.path.join(DATA, 'spawns.jsonl')  # one line per spawn + one per exit (survives restarts)
_usage_cache = {}  # sid -> {"key": (size, mtime), "usage": {...}}
_audit_scan = {'key': None, 'starts': []}
USAGE_V = 2  # bump when attribution changes: stored usage with an older version is recomputed
ZERO_USAGE = {
    'input': 0,
    'cache_creation': 0,
    'cache_read': 0,
    'output': 0,
    'processed': 0,
    'total': 0,
    'turns': 0,
    'tool_calls': 0,
    'text_chars': 0,
}


def _iso_epoch(ts):
    try:
        return datetime.fromisoformat(str(ts).replace('Z', '+00:00')).timestamp()
    except Exception:
        return None


def transcript_usage(sid):
    """Sum the harness-recorded usage over every assistant turn of one session.
    Cached by (size, mtime) — a finished session is parsed once. None if no
    transcript. Reads line by line; only lines that can carry usage are parsed."""
    path = _find_transcript(sid or '')
    if not path:
        return None
    try:
        stt = os.stat(path)
    except OSError:
        return None
    key = (stt.st_size, int(stt.st_mtime))
    c = _usage_cache.get(sid)
    if c and c['key'] == key:
        return c['usage']
    u = dict(ZERO_USAGE, first_at=None, last_at=None, model=None, bytes=stt.st_size, turns_list=[])
    try:
        with open(path, 'rb') as f:
            for raw in f:
                if b'"usage"' not in raw:
                    continue
                try:
                    d = json.loads(raw)
                except ValueError as _exc:
                    _zyg_log.debug('malformed transcript record skipped in %s: %s', path, _exc)
                    continue
                if d.get('type') != 'assistant':
                    continue
                m = d.get('message') or {}
                us = m.get('usage') or {}
                if not us:
                    continue
                row = [
                    int(us.get('input_tokens') or 0),
                    int(us.get('cache_creation_input_tokens') or 0),
                    int(us.get('cache_read_input_tokens') or 0),
                    int(us.get('output_tokens') or 0),
                    0,
                    0,
                ]
                u['turns'] += 1
                u['input'] += row[0]
                u['cache_creation'] += row[1]
                u['cache_read'] += row[2]
                u['output'] += row[3]
                ts = _iso_epoch(d.get('timestamp'))
                if ts:
                    u['first_at'] = u['first_at'] or ts
                    u['last_at'] = ts
                u['model'] = m.get('model') or u['model']
                for b in m.get('content') or []:
                    if isinstance(b, dict):
                        if b.get('type') == 'tool_use':
                            u['tool_calls'] += 1
                            row[4] += 1
                        elif b.get('type') == 'text':
                            n = len(b.get('text') or '')
                            u['text_chars'] += n
                            row[5] += n
                u['turns_list'].append((ts or 0, *row))
    except Exception:
        return None
    u['processed'] = u['input'] + u['cache_creation'] + u['cache_read']
    u['total'] = u['processed'] + u['output']
    _usage_cache[sid] = {'key': key, 'usage': u}
    return u


def _sum_usage(acc, u):
    for k in ZERO_USAGE:
        acc[k] = acc.get(k, 0) + int((u or {}).get(k) or 0)
    return acc


_START_EVENTS = ('claimed', 'slot granted from queue', 'taken over after stale lease')
_END_EVENTS = ('finished', 'failed', 'report accepted but verify_cmd FAILED', 'released')


def task_timeline(task, tnow):
    """(executing intervals, queued wait seconds, spawn→claim startup seconds)
    from the task's history. A stale lease does not end an interval (the holder
    is still on it); reset / takeover / finish / fail / release do."""
    iv, start, queued_at, qwait, spawned_at, startup = [], None, None, 0.0, None, None
    for h in task.get('history') or []:
        ev, at = h.get('event', ''), h.get('at') or 0
        if ev == 'executor spawned by the board':
            spawned_at = at
        elif ev == 'queued':
            queued_at = at
        elif ev in _START_EVENTS:
            if queued_at:
                qwait += max(0, at - queued_at)
                queued_at = None
            if spawned_at and startup is None:
                startup = max(0, at - spawned_at)
            if start is not None:  # takeover ends the previous holder's interval
                iv.append((start, at))
            start = at
        elif ev in _END_EVENTS or ev.startswith('reset by'):
            if start is not None:
                iv.append((start, at))
                start = None
            queued_at = None
        elif ev.startswith('queue reservation dropped'):
            if queued_at:
                qwait += max(0, at - queued_at)
                queued_at = None
    if start is not None and task['status'] == 'executing':
        iv.append((start, tnow))
    if queued_at and task['status'] == 'queued':
        qwait += max(0, tnow - queued_at)
    return iv, qwait, startup


def _union_len(intervals):
    total, cur = 0.0, None
    for a, b in sorted(intervals):
        if cur is None or a > cur[1]:
            if cur:
                total += cur[1] - cur[0]
            cur = [a, b]
        else:
            cur[1] = max(cur[1], b)
    if cur:
        total += cur[1] - cur[0]
    return total


def spawn_record(rec):
    rec['ts'] = now()
    with open(SPAWNS_LOG, 'a') as f:
        f.write(json.dumps(rec) + '\n')


def spawn_records():
    out = {}
    try:
        with open(SPAWNS_LOG) as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except ValueError as _exc:
                    _zyg_log.debug('malformed spawn record skipped: %s', _exc)
                    continue
                out.setdefault(r['sid'], {}).update(r)
    except FileNotFoundError as _exc:
        _zyg_log.debug('no spawn log at %s yet: %s', SPAWNS_LOG, _exc)
    return out


def attribute_session_usage(tree, sid, tnow, final=False):
    """Give every assistant turn of session `sid` to exactly one task of this
    tree: the task whose executing window contains the turn; turns before the
    first claim (startup, `st rules`) go to the first task, turns after the last
    finish (the `st done` turn) to the last task, gaps to the task just ended.
    Before the one-task cap a session did up to three tasks — whole-session
    stamping counted it three times (measured 2026-09-06 on the identity tree).
    Returns True when a task changed."""
    tasks = [x for x in tree['tasks'] if (x.get('claimed_by') or {}).get('session_id') == sid]
    for x in tasks:
        if x.get('usage_v') != USAGE_V:
            x['usage_final'] = False
    if not tasks or all(x.get('usage_final') for x in tasks):
        return False
    u = transcript_usage(sid)
    if u is None:
        return False
    wins = []
    for x in tasks:
        iv, _, _ = task_timeline(x, tnow)
        if iv:
            wins.append((min(a for a, _ in iv), max(b for _, b in iv), x))
    if not wins:
        return False
    wins.sort(key=lambda w: w[0])
    acc = {id(w[2]): [0, 0, 0, 0, 0, 0, 0] for w in wins}
    for ts, i, cc, cr, o, tc, tx in u.get('turns_list') or []:
        tgt = None
        for a, b, x in wins:
            if a <= ts <= b + 1:
                tgt = x
                break
        if tgt is None:
            if ts < wins[0][0]:
                tgt = wins[0][2]
            else:
                prev = [w for w in wins if w[1] < ts]
                tgt = (prev[-1] if prev else wins[-1])[2]
        r = acc[id(tgt)]
        r[0] += 1
        r[1] += i
        r[2] += cc
        r[3] += cr
        r[4] += o
        r[5] += tc
        r[6] += tx
    changed = False
    for _a, _b, x in wins:
        if x.get('usage_final'):
            continue
        r = acc[id(x)]
        x['usage'] = {
            'turns': r[0],
            'input': r[1],
            'cache_creation': r[2],
            'cache_read': r[3],
            'output': r[4],
            'tool_calls': r[5],
            'text_chars': r[6],
            'processed': r[1] + r[2] + r[3],
            'total': r[1] + r[2] + r[3] + r[4],
            'model': u.get('model'),
            'bytes': u.get('bytes'),
            'session_turns': u['turns'],
            'shared': len(wins) > 1,
        }
        x['usage_final'] = bool(final) and x['status'] in ('finished', 'failed')
        x['usage_v'] = USAGE_V
        changed = True
    return changed


def stamp_task_usage(tree, task, final=False):
    sid = (task.get('claimed_by') or {}).get('session_id')
    return bool(sid) and attribute_session_usage(tree, sid, now(), final=final)


def stamp_usage_for_session(sid, active_trees=None):
    """After a spawned session exits, its transcript is final: stamp its task.
    Active trees are stamped on the caller's in-memory copies (the sweep saves
    those itself — saving a separately loaded copy here was clobbered by the
    sweep's later save, measured 2026-09-06); finished trees on disk.
    Returns (claimed: bool, changed_tree_ids: set)."""
    changed = set()
    for tree in active_trees if active_trees is not None else list_trees(ACTIVE):
        for task in tree['tasks']:
            if (task.get('claimed_by') or {}).get('session_id') == sid:
                for x in tree['tasks']:
                    if (x.get('claimed_by') or {}).get('session_id') == sid:
                        x['usage_final'] = False
                if attribute_session_usage(tree, sid, now(), final=True):
                    changed.add(tree['id'])
                    if active_trees is None:
                        save_tree(tree, ACTIVE)
                return True, changed
    for tree in list_trees(FINISHED):
        for task in tree['tasks']:
            if (task.get('claimed_by') or {}).get('session_id') == sid:
                for x in tree['tasks']:
                    if (x.get('claimed_by') or {}).get('session_id') == sid:
                        x['usage_final'] = False
                if attribute_session_usage(tree, sid, now(), final=True):
                    save_tree(tree, FINISHED)
                return True, changed
    return False, changed


def eta_check(trees):
    """Log (once) when an active tree passes its ETA. No other action."""
    changed = set()
    t = now()
    for tree in trees:
        eta = tree.get('eta_minutes')
        start = tree.get('activated_at') or tree.get('created_at')
        if not eta or not start or tree.get('eta_overrun_at'):
            continue
        if t > start + eta * 60:
            tree['eta_overrun_at'] = t
            counts = {}
            for x in tree['tasks']:
                counts[x['status']] = counts.get(x['status'], 0) + 1
            audit(
                {
                    'cmd': 'eta:overrun',
                    'tree': tree['id'],
                    'ok': True,
                    'model': 'metrics',
                    'error': 'ETA %g min passed, tree still running: %s — no action taken, metrics only'
                    % (eta, ' '.join(f'{k}={v}' for k, v in sorted(counts.items()))),
                }
            )
            changed.add(tree['id'])
    return changed


def tree_metrics(tree, tnow, budget):
    """One tree's metrics row; parses at most `budget[0]` uncached transcripts."""
    start = tree.get('activated_at') or tree.get('created_at') or tnow
    end = tree.get('finished_at') or tnow
    span = max(0.0, end - start)
    all_iv, agent_s, qwait_s, startups = [], 0.0, 0.0, []
    tok = dict(ZERO_USAGE)
    counts, rows, pending, dirty, seen = {}, [], 0, False, set()
    for task in tree['tasks']:
        counts[task['status']] = counts.get(task['status'], 0) + 1
        iv, qw, su = task_timeline(task, tnow)
        ex = sum(b - a for a, b in iv)
        all_iv += iv
        agent_s += ex
        qwait_s += qw
        if su is not None:
            startups.append(su)
        cb = task.get('claimed_by') or {}
        sid = cb.get('session_id')
        stale = not task.get('usage_final') or task.get('usage_v') != USAGE_V
        if sid and stale and sid not in seen:
            seen.add(sid)
            if budget[0] > 0:
                budget[0] -= 1
                # final once every task of this session is finished/failed for >10 min
                mine = [x for x in tree['tasks'] if (x.get('claimed_by') or {}).get('session_id') == sid]
                final = all(
                    x['status'] in ('finished', 'failed') and (tnow - (x.get('finished_at') or tnow)) > 600
                    for x in mine
                )
                if attribute_session_usage(tree, sid, tnow, final=final):
                    dirty = True
            elif task.get('usage') is None:
                pending += 1
        u = task.get('usage')
        if u:
            _sum_usage(tok, u)
        eta = task.get('eta_minutes')
        actual_m = ex / 60 if ex else None
        rows.append(
            {
                'id': task['id'],
                'title': task['title'],
                'status': task['status'],
                'weight': task['weight'],
                'session': (cb.get('session_id') or '')[:8],
                'model': cb.get('model'),
                'spawned': bool(cb.get('spawned')),
                'attempts': task.get('attempts', 0),
                'executing_s': round(ex),
                'queue_wait_s': round(qw),
                'startup_s': (round(su) if su is not None else None),
                'eta_minutes': eta,
                'actual_minutes': (round(actual_m, 1) if actual_m else None),
                'ratio': (round(actual_m / eta, 2) if eta and actual_m else None),
                'usage': u,
                'shared': bool(u and u.get('shared')),
                'per_turn': (round(u['processed'] / u['turns']) if u and u.get('turns') else None),
            }
        )
    busy = _union_len(all_iv)
    eta = tree.get('eta_minutes')
    actual_m = span / 60
    return {
        'id': tree['id'],
        'title': tree['title'],
        'status': tree.get('status'),
        'created_at': tree.get('created_at'),
        'activated_at': tree.get('activated_at'),
        'finished_at': tree.get('finished_at'),
        'closed_by': tree.get('closed_by'),
        'n': len(tree['tasks']),
        'counts': counts,
        'eta_minutes': eta,
        'eta_note': tree.get('eta_note', ''),
        'eta_overrun_at': tree.get('eta_overrun_at'),
        'eta_revisions': tree.get('eta_revisions') or [],
        'actual_minutes': round(actual_m, 1),
        'ratio': (round(actual_m / eta, 2) if eta else None),
        'span_s': round(span),
        'busy_s': round(busy),
        'idle_s': round(max(0.0, span - busy)),
        'agent_task_s': round(agent_s),
        'queue_wait_s': round(qwait_s),
        'startup_avg_s': (round(sum(startups) / len(startups)) if startups else None),
        'tokens': tok,
        'pending': pending,
        'tasks': rows,
    }, dirty


def audit_server_starts():
    try:
        stt = os.stat(AUDIT)
    except OSError:
        return []
    key = (stt.st_size, int(stt.st_mtime))
    if _audit_scan['key'] == key:
        return _audit_scan['starts']
    starts = []
    with open(AUDIT, 'rb') as f:
        for ln in f:
            if b'"server:start"' in ln:
                try:
                    starts.append(json.loads(ln)['ts'])
                except (ValueError, KeyError) as _exc:
                    _zyg_log.debug('malformed server:start audit line skipped: %s', _exc)
    _audit_scan.update(key=key, starts=starts)
    return starts


def ui_metrics():
    tnow = now()
    budget = [20]  # uncached transcripts parsed per poll; the tab re-polls until pending == 0
    rows = []
    for folder in (ACTIVE, FINISHED):
        with LOCK:
            trees = list_trees(folder)
        for tree in trees:
            row, dirty = tree_metrics(tree, tnow, budget)
            if dirty:
                with LOCK:
                    cur = load_tree(tree['id'], folder)
                    if cur:  # re-stamp on the current copy, not our snapshot
                        by_id = {x['id']: x for x in tree['tasks']}
                        for x in cur['tasks']:
                            src = by_id.get(x['id'])
                            if src and src.get('usage') and (not x.get('usage_final') or x.get('usage_v') != USAGE_V):
                                x['usage'], x['usage_final'], x['usage_v'] = (
                                    src['usage'],
                                    src.get('usage_final', False),
                                    USAGE_V,
                                )
                        save_tree(cur, folder)
            rows.append(row)
    rows.sort(key=lambda r: r.get('activated_at') or r.get('created_at') or 0, reverse=True)
    tot = dict(ZERO_USAGE)
    agg = {
        'trees': len(rows),
        'tasks': 0,
        'finished': 0,
        'failed': 0,
        'agent_task_s': 0,
        'busy_s': 0,
        'idle_s': 0,
        'queue_wait_s': 0,
        'span_s': 0,
        'pending': 0,
        'turns': 0,
    }
    ratios = []
    for r in rows:
        _sum_usage(tot, r['tokens'])
        agg['tasks'] += r['n']
        agg['finished'] += r['counts'].get('finished', 0)
        agg['failed'] += r['counts'].get('failed', 0)
        for k in ('agent_task_s', 'busy_s', 'idle_s', 'queue_wait_s', 'span_s', 'pending'):
            agg[k] += r[k]
        if r['ratio'] is not None and r['status'] == 'finished':
            ratios.append(r['ratio'])
    ratios.sort()
    eta = {
        'n': len(ratios),
        'median_ratio': (ratios[len(ratios) // 2] if ratios else None),
        'over': sum(1 for x in ratios if x > 1.0),
        'under': sum(1 for x in ratios if x <= 1.0),
        'active_over': sum(1 for r in rows if r['status'] == 'active' and r.get('eta_overrun_at')),
    }
    # spawned sessions that exited without ever claiming — pure waste, tokens included
    recs = spawn_records()
    wasted = [
        {
            'sid': s[:8],
            'tree': r.get('tree'),
            'task': r.get('task'),
            'started_at': r.get('started_at'),
            'exited_at': r.get('exited_at'),
            'exit': r.get('exit'),
            'usage': r.get('usage'),
        }
        for s, r in recs.items()
        if r.get('exited_at') and not r.get('claimed')
    ]
    wtok = dict(ZERO_USAGE)
    for w in wasted:
        _sum_usage(wtok, w['usage'])
    starts = audit_server_starts()
    return {
        'now': tnow,
        'server': {
            'started_at': SERVER_STARTED,
            'uptime_s': round(tnow - SERVER_STARTED),
            'starts_7d': sum(1 for s in starts if s > tnow - 7 * 86400),
            'starts_total': len(starts),
            'first_start': (starts[0] if starts else None),
        },
        'spawner': {
            'total_spawned': len(recs),
            'exited': sum(1 for r in recs.values() if r.get('exited_at')),
            'wasted': len(wasted),
            'wasted_tokens': wtok,
            'live': sum(1 for r in recs.values() if not r.get('exited_at')),
        },
        'totals': {'tokens': tot, **agg},
        'eta': eta,
        'trees': rows,
        'wasted_spawns': wasted[-20:],
        'note': "tokens = harness usage on executor sessions' own transcripts (creator/Fable sessions are "
        'not attributed: one Fable session serves many trees). processed = input + cache '
        'creation + cache read (what the model re-reads each turn); output = what it wrote.',
    }
