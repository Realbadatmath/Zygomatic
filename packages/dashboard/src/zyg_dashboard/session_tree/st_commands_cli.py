# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""st_commands_cli — one handler per ``st`` subcommand, and the table ``main`` dispatches on.

Extracted from ``st_cli.main`` (2026-10-09), which was a single 463-line if-ladder over
twenty commands. Each handler takes the argument list after the command word and returns
the process exit status; :data:`COMMANDS` maps the command word to it, so ``st_cli.main``
is the three gates that come first (help, the template commands, the session-id check)
and a dictionary lookup.

Behaviour is the ladder's, unchanged: the same requests, the same printed lines in the
same order, the same statuses. ``usage:`` lines still return 2 and a server refusal still
exits 2 through :func:`st_client_cli.die`.
"""

import json
import sys
import time

# Both import forms, for the same reason st_cli needs them: `st` is a symlink to st_cli.py,
# so /usr/bin/python3 may run this package as plain scripts off one sys.path entry, with no
# package for a relative import to resolve against.
try:
    from .st_client_cli import (
        REPORT_TEMPLATE,
        TREE_TEMPLATE,
        URL,
        call,
        die,
        print_brief,
        print_failure_notify,
        problem_report,
        read_json_arg,
    )
except ImportError:  # run as a script, with no parent package
    from st_client_cli import (  # type: ignore[no-redef]
        REPORT_TEMPLATE,
        TREE_TEMPLATE,
        URL,
        call,
        die,
        print_brief,
        print_failure_notify,
        problem_report,
        read_json_arg,
    )


def cmd_report_template(args):
    """``st report-template`` — print the report JSON skeleton ``st done`` expects."""
    del args
    print(json.dumps(REPORT_TEMPLATE, indent=2))
    return 0


def cmd_tree_template(args):
    """``st tree-template`` — print the tree JSON skeleton ``st create`` expects."""
    del args
    print(json.dumps(TREE_TEMPLATE, indent=2))
    return 0


def cmd_whoami(args):
    """``st whoami`` — the identity the server reads from the transcript, plus pending reviews."""
    del args
    r = call('whoami')
    print(f'session {r.get("session_id", "")[:8]}  model {r.get("model")}  role {r.get("role")}')
    if r.get('why'):
        print('note: ' + r['why'])
    if r.get('active_task'):
        print(f'holding: {r["active_task"][0]}#{r["active_task"][1]}')
    print(f'tasks this session: {r.get("tasks_this_session")}/{r.get("max_tasks_per_session")}')
    for n in r.get('pending_reviews', []):
        c = ' '.join(f'{k}={v}' for k, v in sorted(n['counts'].items()))
        print(
            f'REVIEW PENDING{"" if n["yours"] else " (another creator session)"}: {n["tree"]}  '
            f'"{n["title"][:90]}"  finished {n["finished_at"]}  {c}   →  st review {n["tree"]}'
        )
    return 0


def print_spawner(sp):
    """The executor-pool block of ``st status``: live sessions, brake, usage meter, holds.

    *sp* is the status payload's ``spawner`` section. The usage, auth and hold lines each
    print only when the board has something to say about them.
    """
    brake = sp.get('brake_until') or 0
    print(
        f'executors {sp["live_total"]}/{sp["max_executors"]} live  auto-spawn '
        f'{"on" if sp["auto_spawn"] else "OFF"}  {sp["executor_model"]}  1 task per session'
        + (
            f'  BRAKE until {time.strftime("%H:%M", time.localtime(brake))} (spawns exited without claiming)'
            if brake > time.time()
            else ''
        )
        + (f'  last error: {sp["last_error"]}' if sp.get('last_error') else '')
    )
    u = sp.get('usage') or {}
    if u.get('windows'):
        hm = lambda ts: time.strftime('%a %H:%M', time.localtime(ts)) if ts else '?'
        print(
            'usage  '
            + ' · '.join(
                f'{w["name"]} {"?" if w.get("pct") is None else int(w["pct"])}% resets {hm(w.get("resets_at"))}'
                for w in u['windows']
            )
            + f'  (meter read {int(time.time() - (u.get("ts") or time.time()))} s ago)'
        )
    elif u.get('error'):
        print(f'usage  meter unreadable: {u["error"]}')
    a = sp.get('auth') or {}
    if a.get('broken_since'):
        print(
            f'EXECUTOR LOGIN BROKEN since {time.strftime("%a %H:%M", time.localtime(a["broken_since"]))}: '
            f'{a.get("msg", "")[:120]}\n       -> run `claude login` as the login user; the board retries ONE spawn '
            f'every {a.get("retry_s", 900) // 60} min and resumes by itself when a spawn claims. Tasks stay todo.'
        )
    if u.get('hold') and (u.get('hold_until') or 0) > time.time():
        left = int(u['hold_until'] - time.time())
        print(
            f'USAGE HOLD: auto-spawn paused until {time.strftime("%a %H:%M", time.localtime(u["hold_until"]))} '
            f'({left // 3600}h{left % 3600 // 60:02d}m) — {u.get("hold_reason", "")}. The board resumes '
            f'by itself when Claude refreshes the window; tasks stay todo. Do not close the tree.'
        )


def print_tree(t):
    """One active tree in ``st status``: its counts, its ETA, whether it has settled, its tasks."""
    c = t['counts']
    eta = ''
    if t.get('eta_minutes'):
        el = (t.get('now') or 0) - (t.get('activated_at') or 0)
        eta = f'  ETA {t["eta_minutes"]:g}m elapsed {el / 60:.0f}m' + (
            '  OVER (logged, no action)' if t.get('eta_overrun_at') else ''
        )
    settle = ''
    st_ = t.get('settle') or {}
    if st_.get('settled'):
        left = ((st_.get('archive_at') or 0) - (t.get('now') or 0)) / 60
        settle = '  SETTLED (failed=%d stale=%d blocked=%d) — nothing left to run; ' % (
            len(st_.get('failed') or []),
            len(st_.get('stale') or []),
            len(st_.get('blocked') or []),
        ) + (
            f'auto-archives in {max(0, left):.0f} min unless a task is reset'
            if st_.get('enabled')
            else 'auto-archive is OFF (settle_archive_minutes=0)'
        )
    print(
        f'{t["id"]}  "{t["title"]}"  {t["n"]} tasks  '
        + ' '.join(f'{k}={v}' for k, v in sorted(c.items()))
        + eta
        + settle
    )
    for x in t.get('tasks', []):
        dep = f' needs {x["depends_on"]}' if x['depends_on'] else ''
        vr = f' {x["vram_gb"]:g}G' if x.get('vram_gb') else ''
        sb = x.get('spawn_blocked') or {}
        blk = (
            f'\n       NOT SPAWNED for {max(0, (time.time() - sb["since"]) / 60):.0f} min: {sb.get("why")}'
            if sb.get('since')
            else ''
        )
        print(f'  #{x["id"]:<3}{x["status"]:<17}{x["weight"]}{vr:<6} {x["title"]}{dep}{blk}')


def cmd_status(args):
    """``st status [TREE]`` — the queue, the pool, the planned queue and every active tree."""
    r = call('status', tree=args[0] if args else None)
    if not r.get('ok'):
        die(r)
    q, res = r['queue'], r['resources']
    gpu = res.get('gpu') or {}
    print(
        f'queue heavy {q["heavy_used"]}/{q["heavy_slots"]}  light {q["light_used"]}/{q["light_slots"]}'
        f'  | vram free {gpu.get("vram_free_gb", "?")}G util {gpu.get("util_pct", "?")}%'
        f'  ram avail {res.get("ram_avail_gb", "?")}G'
    )
    sp = r.get('spawner')
    if sp:
        print_spawner(sp)
    for n in r.get('pending_reviews', []):
        c = ' '.join(f'{k}={v}' for k, v in sorted(n['counts'].items()))
        print(
            f'REVIEW PENDING{"" if n["yours"] else " (another creator session)"}: {n["tree"]}  '
            f'"{n["title"]}"  finished {n["finished_at"]}  {c}   →  st review {n["tree"]}'
        )
    if not r['trees']:
        print('no active trees')
    for p in r.get('planned', []):
        print(
            f'PLANNED #{p["position"]}: {p["id"]}  "{p["title"]}"  {p["n"]} tasks  created {p["created_at"]}'
            f'  (activates when the active tree archives)'
        )
    for t in r['trees']:
        print_tree(t)
    return 0


def cmd_next(args):
    """``st next [TREE]`` — the one task to claim now, or why there is none."""
    r = call('next', tree=args[0] if args else None)
    if not r.get('ok'):
        die(r)
    if r.get('none'):
        print('NONE: ' + r['msg'])
        if r.get('retry_after_s'):
            print(
                f'retry: the blockers are light tasks in progress — wait {r["retry_after_s"] // 60} min '
                f'(a background `sleep {r["retry_after_s"]}` then `st next` again), do not end the session'
            )
        return 1
    if r.get('spawned_for_you'):
        print('  (the board spawned this session for that task — it is reserved for you)')
    if r.get('will_queue'):
        print(f'claim this: st claim {r["tree"]} {r["task"]}    ({r["weight"]}) {r["title"]}')
        print(f'  it will QUEUE ({r["queue_ahead"]} ahead): {r["reason"]}')
        print(
            f'  claiming reserves your place; then run `st await {r["tree"]} {r["task"]}` in the '
            f'background — it exits with the brief when the slot is yours. Do not end the session.'
        )
        return 0
    print(f'claim this: st claim {r["tree"]} {r["task"]}    ({r["weight"]}) {r["title"]}')
    return 0


def cmd_claim(args):
    """``st claim TREE N`` — take task N and print its brief, or report the queue position."""
    if len(args) < 2:
        print('usage: st claim TREE N')
        return 2
    r = call('claim', tree=args[0], task=int(args[1]))
    if not r.get('ok'):
        die(r)
    if r.get('queued'):
        print(f'QUEUED {r["tree"]}#{r["task"]} ({r["weight"]}) position {r["position"]} — {r["reason"]}')
        print(f'title: {r["title"]}')
        print(
            f'The task is yours but has NOT started: no brief yet, do no work on it. Run NOW, in a '
            f'background shell:\n    st await {r["tree"]} {r["task"]}\n  It exits when the slot is '
            f'granted and prints the brief; the harness wakes you when it exits. The reservation is '
            f'dropped if nothing polls for {r["wait_stale_minutes"]} min, so keep `st await` running. '
            f'To give the place back: st release {r["tree"]} {r["task"]} "why"'
        )
        return 0
    print_brief(r)
    return 0


def cmd_await(args):
    """``st await TREE N`` — block until the queued slot is granted, then print the brief.

    Meant for a background shell: the position changes go to stderr, the brief to stdout.
    """
    if len(args) < 2:
        print('usage: st await TREE N   (run in the background; exits when the slot is granted)')
        return 2
    last = None
    while True:
        r = call('await', tree=args[0], task=int(args[1]))
        if not r.get('ok'):
            die(r)
        if r.get('granted'):
            print('SLOT GRANTED after queueing.')
            print_brief(r)
            return 0
        cur = f'position {r.get("position")}: {r.get("reason")}'
        if cur != last:
            sys.stderr.write(f'{time.strftime("%H:%M")} {cur}\n')
            sys.stderr.flush()
            last = cur
        time.sleep(int(r.get('poll_s') or 20))


def cmd_touch(args):
    """``st touch TREE N [note]`` — heartbeat with a progress note; extends the lease."""
    if len(args) < 2:
        print('usage: st touch TREE N [note]')
        return 2
    r = call('touch', tree=args[0], task=int(args[1]), note=' '.join(args[2:]))
    if not r.get('ok'):
        die(r)
    print(f'ok lease until {r["lease_until"]}')
    return 0


def cmd_release(args):
    """``st release TREE N "why"`` — give the task back untouched."""
    if len(args) < 2:
        print('usage: st release TREE N "why"')
        return 2
    r = call('release', tree=args[0], task=int(args[1]), reason=' '.join(args[2:]))
    if not r.get('ok'):
        die(r)
    print(r['msg'])
    return 0


def print_archive_notice(cn, tree):
    """The TREE ARCHIVED block: the message the last executor must send the creator."""
    c = ' '.join(f'{k}={v}' for k, v in sorted(cn['counts'].items()))
    print('TREE ARCHIVED — you finished the last task. Notify the creator NOW, then stop:')
    if cn.get('alive') and cn.get('peer_name'):
        print(
            f'  SendMessage to="{cn["peer_name"]}" message="Session tree {tree} is finished ({c}). '
            f'Run st review {tree} and give the user the results report and plan of action."'
        )
    else:
        print(
            f'  creator session {cn.get("session_id", "")[:8]} ({cn.get("model")}) is not running; '
            f"the review request is queued — the next Fable session's `st status` shows it."
        )


def cmd_done(args):
    """``st done TREE N --report FILE`` — submit the report; the server checks and verifies it.

    The report may also arrive on stdin. Returns 3 when the server's ``verify_cmd``
    failed, which marks the task failed rather than finished.
    """
    report, rest = read_json_arg(args, '--report')
    if report is None and not sys.stdin.isatty():
        report = json.load(sys.stdin)
    if report is None or len(rest) < 2:
        print('usage: st done TREE N --report FILE   (or pipe the report JSON on stdin)')
        return 2
    r = call('done', tree=rest[0], task=int(rest[1]), report=report)
    if not r.get('ok'):
        if r.get('status') == 'failed':
            print('VERIFY FAILED — task marked failed.\n' + r['msg'])
            print_failure_notify(r.get('creator_notify'), rest[0], rest[1])
            return 3
        die(r)
    print(
        f'FINISHED {rest[0]}#{rest[1]}  verified={r["verified"]}  '
        f'todo left in tree: {r["todo_left"]}  tree archived: {r["tree_archived"]}'
    )
    cn = r.get('creator_notify')
    if cn:
        print_archive_notice(cn, rest[0])
    print(
        f'tasks this session: {r["tasks_this_session"]}/{r["max_tasks_per_session"]}'
        + (
            '  — session cap reached: stop here.'
            if r['tasks_this_session'] >= r['max_tasks_per_session']
            else '  — you may run `st next` once more, or stop.'
        )
    )
    return 0


def cmd_fail(args):
    """``st fail TREE N "why"`` — record an honest failure and notify the creator."""
    if len(args) < 3:
        print('usage: st fail TREE N "why"')
        return 2
    r = call('fail', tree=args[0], task=int(args[1]), reason=' '.join(args[2:]))
    if not r.get('ok'):
        die(r)
    print(f'FAILED {args[0]}#{args[1]} recorded. Stop working on it.')
    print_failure_notify(r.get('creator_notify'), args[0], args[1])
    return 0


def cmd_wait(args):
    """``st wait TREE [--until-archive]`` — the creator's wake-up: exits on a problem or on archive.

    Polls once a minute, printing each change of state to stderr, and returns 0 with the
    problem report or the archive notice on stdout. ``--until-archive`` ignores problems.
    """
    until_archive = '--until-archive' in args
    args = [a for a in args if not a.startswith('--')]
    if not args:
        print('usage: st wait TREE [--until-archive]   (exits on the FIRST failed/stale task, or on archive)')
        return 2
    last = None
    while True:
        r = call('wait', tree=args[0])
        if not r.get('ok'):
            die(r)
        if r.get('problems') and not until_archive:
            print(problem_report(args[0], r))
            return 0
        if r.get('archived'):
            c = ' '.join(f'{k}={v}' for k, v in sorted((r.get('counts') or {}).items()))
            print(
                f'TREE FINISHED: {args[0]} "{r.get("title", "")}" archived {r.get("finished_at")} by {r.get("by")}  {c}'
            )
            print(f'Now: st review {args[0]}  → then give the user the results report + plan of action in chat.')
            return 0
        if r.get('planned'):
            cur = f'planned #{r.get("position")} behind {r.get("behind")}'
        else:
            cur = json.dumps(r.get('counts'), sort_keys=True)
        if cur != last:
            sys.stderr.write(f'{time.strftime("%H:%M")} {cur}\n')
            sys.stderr.flush()
            last = cur
        time.sleep(60)


def cmd_review(args):
    """``st review TREE`` — the creator's one read of a finished tree's reports."""
    if not args:
        print('usage: st review TREE')
        return 2
    r = call('review', tree=args[0])
    if not r.get('ok'):
        die(r)
    print(f'REVIEW {r["tree"]}  "{r["title"]}"  finished {r["finished_at"]}  closed_by {r.get("closed_by")}')
    if r.get('close_note'):
        print('close note: ' + r['close_note'])
    for x in r['tasks']:
        print(f'\n#{x["id"]} [{x["status"]}] attempts={x["attempts"]} by={x["by"]}  {x["title"]}')
        print('  summary: ' + (x['summary'] or '').replace('\n', ' ')[:1200])
        if x['not_done'] and x['not_done'].strip().lower() != 'none':
            print('  NOT DONE: ' + x['not_done'].replace('\n', ' ')[:800])
        if x['changed_files']:
            print('  changed: ' + ', '.join(x['changed_files'][:12]) + (' …' if len(x['changed_files']) > 12 else ''))
        if x['verify']:
            print(
                f'  server verify exit {x["verify"]["exit"]}'
                + ('' if x['verify']['exit'] == 0 else ': ' + x['verify']['tail'].replace('\n', ' | ')[-300:])
            )
        if x['notes']:
            print('  notes: ' + x['notes'].replace('\n', ' ')[:600])
    return 0


def cmd_create(args):
    """``st create --file tree.json`` — create a tree, then tell the creator to arm ``st wait``."""
    spec, _ = read_json_arg(args, '--file')
    if spec is None:
        print('usage: st create --file tree.json   (st tree-template)')
        return 2
    r = call('create', **spec)
    if not r.get('ok'):
        die(r)
    if r.get('planned'):
        print(
            f'PLANNED tree {r["tree"]} with {r["n"]} tasks — position #{r["position"]} behind '
            f'{", ".join(r.get("behind") or [])}  →  {URL}/ (Planned tab)'
        )
        print(
            'One tree runs at a time. It activates by itself when the active tree archives; '
            'executors cannot see it until then. Do not close the active tree to jump the queue.'
        )
    else:
        print(f'CREATED tree {r["tree"]} with {r["n"]} tasks  →  {URL}/')
    if spec.get('eta_minutes'):
        print(
            f'ETA logged: {float(spec["eta_minutes"]):g} min — compared with reality on the Metrics tab, never acted on.'
        )
    print(f'NOW ARM YOUR WAKE-UP (Bash, run_in_background=true):  st wait {r["tree"]}')
    print('It exits when the tree archives; the harness wakes you. Then: st review ' + r['tree'])
    return 0


def cmd_suggest(args):
    """``st suggest --file tree.json`` — file a modularization tree for the operator to accept."""
    spec, _ = read_json_arg(args, '--file')
    if spec is None:
        print(
            'usage: st suggest --file tree.json   (same shape as create, plus "rationale": why this'
            ' modularization — the operator reads it in the Modularization tab before accepting)'
        )
        return 2
    r = call('suggest', **spec)
    if not r.get('ok'):
        die(r)
    print(
        f'SUGGESTED tree {r["tree"]} with {r["n"]} tasks — #{r["position"]} in the Modularization tab'
        f'  →  {URL}/#modular'
    )
    print(
        'Nothing runs and nothing queues until the operator accepts it there. Do NOT st wait on it; '
        'you are told nothing further unless it is accepted and runs.'
    )
    return 0


def cmd_add(args):
    """``st add TREE --file tasks.json`` — append tasks; ``--eta N`` revises the tree ETA."""
    spec, rest = read_json_arg(args, '--file')
    if spec is None or not rest:
        print('usage: st add TREE --file tasks.json  ({"tasks":[...]} or a list)')
        return 2
    tasks = spec if isinstance(spec, list) else spec.get('tasks')
    eta = None
    if '--eta' in rest:
        i = rest.index('--eta')
        eta = float(rest[i + 1])
        rest = rest[:i] + rest[i + 2 :]
    elif isinstance(spec, dict) and spec.get('eta_minutes'):
        eta = float(spec['eta_minutes'])
    r = call('add', tree=rest[0], tasks=tasks, eta_minutes=eta)
    if not r.get('ok'):
        die(r)
    print(
        f'added {r["added"]} → {r["n"]} tasks in {r["tree"]}'
        + (' (planned)' if r.get('planned') else '')
        + (f'  ETA revised to {r["eta_minutes"]:g} min' if eta else '')
    )
    return 0


def cmd_task_report(args):
    """``st report TREE N`` — read a finished or failed task's report on an active tree."""
    if len(args) < 2:
        print('usage: st report TREE N')
        return 2
    r = call('report', tree=args[0], task=int(args[1]))
    if not r.get('ok'):
        die(r)
    rep = r['report'] or {}
    print(f'#{r["task"]} {r["status"]}  by {rep.get("by")}')
    print('summary: ' + rep.get('summary', ''))
    print('changed: ' + ', '.join(rep.get('changed_files', [])))
    v = rep.get('verification', {})
    print('verification: ' + v.get('cmd', ''))
    print((v.get('output', '') or '')[-800:])
    print('not_done: ' + rep.get('not_done', ''))
    vr = r.get('verify_result')
    if vr:
        print(f'server verify: exit {vr["exit"]} in {vr["seconds"]}s\n' + vr['tail'][-800:])
    return 0


def cmd_reset(args):
    """``st reset TREE N [--brief FILE]`` — put a failed or stale task back to todo."""
    if len(args) < 2:
        print('usage: st reset TREE N [--brief FILE]')
        return 2
    brief = None
    if '--brief' in args:
        brief = open(args[args.index('--brief') + 1]).read()
    r = call('reset', tree=args[0], task=int(args[1]), brief=brief)
    if not r.get('ok'):
        die(r)
    print(f'#{r["task"]} → todo')
    return 0


def cmd_close(args):
    """``st close TREE [note] [--force]`` — archive a tree by hand, planned or active."""
    if not args:
        print('usage: st close TREE [note] [--force]')
        return 2
    force = '--force' in args
    note = ' '.join(a for a in args[1:] if a != '--force')
    r = call('close', tree=args[0], note=note, force=force)
    if not r.get('ok'):
        die(r)
    print(f'archived {r["archived"]}' + (' (was planned, never ran)' if r.get('was_planned') else ''))
    return 0


#: Command word → handler, in the order the old if-ladder tested them. The three commands
#: that work without a session id (`rules`, `report-template`, `tree-template`) are handled
#: by `st_cli.main` before the identity check, so only the last two appear here as well.
COMMANDS = {
    'report-template': cmd_report_template,
    'tree-template': cmd_tree_template,
    'whoami': cmd_whoami,
    'status': cmd_status,
    'next': cmd_next,
    'claim': cmd_claim,
    'await': cmd_await,
    'touch': cmd_touch,
    'release': cmd_release,
    'done': cmd_done,
    'fail': cmd_fail,
    'wait': cmd_wait,
    'review': cmd_review,
    'create': cmd_create,
    'suggest': cmd_suggest,
    'add': cmd_add,
    'report': cmd_task_report,
    'reset': cmd_reset,
    'close': cmd_close,
}
