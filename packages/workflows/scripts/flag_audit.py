#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
flag_audit.py — inventory every ZYG_ flag and find the dead ones.

The problem this measures: 567 distinct ZYG_ flags are referenced in Python here,
and 17 are set anywhere. ~550 have never had their alternate branch executed.

That matters because those flags are sold as a rollback mechanism. A rollback
flag whose alternate path has never run is not a rollback — it is an untested
code path you will first execute during an incident, at 3 a.m., under pressure.
Git is the rollback; a flag is configuration.

    python3 scripts/flag_audit.py                 # summary
    python3 scripts/flag_audit.py --stale 30      # candidates older than 30 days
    python3 scripts/flag_audit.py --json
"""

import argparse
import collections
import datetime
import json
import os
import re
import subprocess
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.dirname(os.path.dirname(_CREWS))  # Zygomatic Full
FLAG_RE = re.compile(r'\bZYG_[A-Z0-9_]+\b')

ENV_FILES = [os.path.join(_ROOT, '.env'), os.path.join(_CREWS, '.env')]

# Flags that are genuinely tunable CONFIG, not rollback switches. These should
# graduate into a config file with declared defaults rather than being deleted.
CONFIG_HINTS = (
    '_MIN',
    '_MAX',
    '_FRAC',
    '_SIM',
    '_THRESH',
    '_FLOOR',
    '_CAP',
    '_SEC',
    '_SECONDS',
    '_TIMEOUT',
    '_STEPS',
    '_RES',
    '_SCALE',
    '_GUIDANCE',
    '_WAIT',
    '_SIZE',
    '_MP',
    '_CHARS',
    '_RETRIES',
    '_LAPVAR',
    '_STRENGTH',
    '_DENOISE',
    '_MODE',
    '_BACKEND',
    '_DIR',
    '_PATH',
    '_URL',
    '_HOST',
    '_PORT',
    '_MODEL',
)


def referenced():
    """flag -> [(file, lineno)]"""
    hits = collections.defaultdict(list)
    for dirpath, dirnames, filenames in os.walk(_CREWS):
        dirnames[:] = [
            d for d in dirnames if not d.startswith('.') and d not in ('__pycache__', 'node_modules', 'output', 'venv')
        ]
        for fn in filenames:
            if not fn.endswith('.py'):
                continue
            p = os.path.join(dirpath, fn)
            try:
                with open(p, 'r', encoding='utf-8', errors='replace') as f:
                    for i, line in enumerate(f, 1):
                        for m in FLAG_RE.findall(line):
                            hits[m].append((os.path.relpath(p, _CREWS), i))
            except Exception as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
                continue
    return hits


def assigned():
    """flag -> file where it is actually SET"""
    out = {}
    for path in ENV_FILES:
        if not os.path.exists(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    line = line[7:].strip() if line.startswith('export ') else line
                    if '=' in line:
                        k = line.split('=', 1)[0].strip()
                        if k.startswith('ZYG_'):
                            out[k] = os.path.relpath(path, _ROOT)
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
    for k in os.environ:
        if k.startswith('ZYG_'):
            out.setdefault(k, '<environment>')
    return out


def first_seen(flag, sites):
    """Age of a flag via git-blame on its first reference site."""
    if not sites:
        return None
    rel, line = sites[0]
    try:
        p = subprocess.run(
            ['git', 'blame', '-L', f'{line},{line}', '--porcelain', '--', rel],
            cwd=_CREWS,
            capture_output=True,
            text=True,
            timeout=20,
        )
        for ln in p.stdout.splitlines():
            if ln.startswith('author-time '):
                ts = int(ln.split()[1])
                return datetime.date.fromtimestamp(ts)
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        '--stale',
        type=int,
        default=30,
        help='days after which an unset rollback flag is a deletion candidate (default 30)',
    )
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--blame', action='store_true', help='git-blame each candidate for its age (slow)')
    a = ap.parse_args()

    refs = referenced()
    setv = assigned()
    rollback, config = [], []
    for flag in sorted(refs):
        (config if any(h in flag for h in CONFIG_HINTS) else rollback).append(flag)

    unset_rollback = [f for f in rollback if f not in setv]

    if a.json:
        print(
            json.dumps(
                {
                    'referenced': len(refs),
                    'set': len(setv),
                    'rollback_flags': len(rollback),
                    'config_flags': len(config),
                    'unset_rollback': unset_rollback,
                    'set_flags': setv,
                },
                indent=1,
            )
        )
        return

    print(f'ZYG_ flags referenced in .py : {len(refs)}')
    print(f'  actually set somewhere     : {len(setv)}' + (f'  ({", ".join(sorted(setv)[:4])}...)' if setv else ''))
    print(
        f'  look like CONFIG           : {len(config)}  (thresholds/paths/models — graduate these into a config file)'
    )
    print(f'  look like ROLLBACK switches : {len(rollback)}')
    print(f'  ROLLBACK + never set        : {len(unset_rollback)}   <-- never-executed alternate branches')
    print()
    print('A rollback flag whose other branch has never run is not a rollback.')
    print('Policy: validate the change in production, then DELETE the flag and')
    print('the dead branch in a follow-up commit. git revert is the rollback.')
    print()

    if a.blame:
        cutoff = datetime.date.today() - datetime.timedelta(days=a.stale)
        rows = []
        for flag in unset_rollback:
            d = first_seen(flag, refs[flag])
            if d and d <= cutoff:
                rows.append((d, flag, len(refs[flag])))
        rows.sort()
        print(f'{len(rows)} unset rollback flags older than {a.stale} days:')
        for d, flag, n in rows[:60]:
            print(f'   {d}  {flag:52s} {n} site(s)')
        if len(rows) > 60:
            print(f'   ... and {len(rows) - 60} more')
    else:
        print(f'first {min(40, len(unset_rollback))} unset rollback flags:')
        for flag in unset_rollback[:40]:
            print(f'   {flag:52s} {len(refs[flag])} site(s)  {refs[flag][0][0]}:{refs[flag][0][1]}')
        print('\n(pass --blame to date them and get deletion candidates)')


if __name__ == '__main__':
    main()
