# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""self_improve.py — THE LOOP: measure → signature → remedy → next-attempt → verify → learn.

The `self_improve` CLI entry point (section 15 of the original module).
"""

import json
import os

from zyg_workflows.self_improve.base import _jsonable, _read_json
from zyg_workflows.self_improve.planning import plan_next_attempt
from zyg_workflows.self_improve.diagnosis import diagnose, render_next_attempt_md
from zyg_workflows.self_improve.campaign_view import campaign
from zyg_workflows.self_improve.verify import verify_attempt
from zyg_workflows.self_improve.watch import watch_active_run


# ══════════════════════════════════════════════════════════════════════════════
# 15.  CLI
# ══════════════════════════════════════════════════════════════════════════════


def _cli_log(msg):
    print(msg, flush=True)


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(prog='self_improve.py', description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)

    d = sub.add_parser('diagnose', help='measure a finished run and rank remedies')
    d.add_argument('run_dir')
    d.add_argument('--clip', default=None, help='delivered clip (default: auto)')
    d.add_argument('--raw', default=None, help='raw pre-post-process clip (default: auto)')
    d.add_argument('--no-vlm', action='store_true')
    d.add_argument('--tier', default='resident', choices=['cpu', 'resident', 'boundary'])
    d.add_argument('--checklist', default='scene20_binary')
    d.add_argument('--params', default=None, help='JSON file of base params')
    d.add_argument(
        '--commit',
        action='store_true',
        help='record an ATTEMPT against each applied remedy — only when\n                         a driver is actually about to run the resulting plan',
    )

    p = sub.add_parser('plan', help='(re)write next_attempt.json from diagnosis.json')
    p.add_argument('run_dir')
    p.add_argument('--params', default=None)
    p.add_argument('--max-remedies', type=int, default=3)
    p.add_argument(
        '--commit',
        action='store_true',
        help='record an ATTEMPT against each applied remedy — use only\n                         when a driver is actually about to run this plan',
    )

    v = sub.add_parser('verify', help='did the applied remedies move their metrics?')
    v.add_argument('prev_run_dir')
    v.add_argument('new_run_dir')
    v.add_argument('--prev-clip', default=None)
    v.add_argument('--new-clip', default=None)

    c = sub.add_parser('campaign', help='cross-run table of attempts and trajectories')
    c.add_argument('run_dir', nargs='+')
    c.add_argument('--out', default=None)

    w = sub.add_parser('watch', help='poll a LIVE run for an abort recommendation')
    w.add_argument('run_dir')
    w.add_argument('--poll', type=float, default=60.0)
    w.add_argument('--once', action='store_true')

    a = ap.parse_args(argv)
    if a.cmd == 'diagnose':
        base = _read_json(a.params, {}) if a.params else {}
        r = diagnose(
            a.run_dir,
            clip_path=a.clip,
            raw_clip=a.raw,
            params=base,
            use_vlm=not a.no_vlm,
            tier=a.tier,
            checklist=a.checklist,
            record_attempts=a.commit,
            log_fn=_cli_log,
        )
        print(render_next_attempt_md(r) if r.get('ok') else json.dumps(_jsonable(r), indent=1))
        return 0 if r.get('ok') else 2
    if a.cmd == 'plan':
        diag = _read_json(os.path.join(a.run_dir, 'diagnosis.json'))
        if not diag:
            print(f'no diagnosis.json in {a.run_dir} — run diagnose first')
            return 2
        base = _read_json(a.params, {}) if a.params else {}
        pl = plan_next_attempt(diag, base, max_remedies=a.max_remedies, record_attempts=a.commit, log_fn=_cli_log)
        print(json.dumps(_jsonable(pl), indent=1))
        return 0 if pl.get('ok') else 2
    if a.cmd == 'verify':
        r = verify_attempt(a.prev_run_dir, a.new_run_dir, prev_clip=a.prev_clip, new_clip=a.new_clip, log_fn=_cli_log)
        print(
            json.dumps(
                _jsonable({k: r[k] for k in ('ok', 'prev_clip', 'new_clip', 'results', 'learned') if k in r}), indent=1
            )
        )
        return 0 if r.get('ok') else 2
    if a.cmd == 'campaign':
        r = campaign(a.run_dir, out_path=a.out, log_fn=_cli_log)
        print(r.get('markdown') or json.dumps(_jsonable(r), indent=1))
        return 0 if r.get('ok') else 2
    if a.cmd == 'watch':
        r = watch_active_run(a.run_dir, poll_s=a.poll, once=a.once, log_fn=_cli_log)
        print(json.dumps(_jsonable(r), indent=1))
        return 0
    return 2
