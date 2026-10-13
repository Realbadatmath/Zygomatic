#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""import_smoke — every module under packages/*/src must import cleanly, in a child process.

The cheapest safety net there is: the regressions the 2026-10 modularization waves let through
were all import-time failures (a re-export that no longer binds, a caller that opens a file that
became a package, a name bound late by a sibling). Importing every module once, in a process
that is not the test runner, catches that class outright and gives every module at least its
top-level lines of coverage.

Modules that cannot be imported yet sit in `packages/<p>/tests/import_smoke_skip.txt`, one per
line with a reason. That list only ever shrinks: scripts/ratchet.py counts its entries
(`smoke_skipped`, zero for a new file), so a new module cannot be born skipped. Entries name a
module or a package; a package entry covers its submodules.

Every child hides the GPU (CUDA_VISIBLE_DEVICES=''), sets ZYG_IMPORT_SMOKE=1, points the
database at the test DSN, and installs a meta-path guard that refuses two modules outright,
whatever imports them: `zyg_workflows.arch_assistant` (its import closes the live assistant's
open conversation) and `zyg_workflows.comfy_generation_service` (talks to ComfyUI at import).
A child that hangs is killed on its per-module alarm, one that grows past --mem-gb is killed by
the parent's watchdog, one that crashes is restarted after the module that killed it.

Commands:
  import_smoke.py list   [--package P]                         modules in scope, after the skip list
  import_smoke.py run    [--package P] [--only M ...] [--changed REF] [--workers N]
                         [--timeout S] [--mem-gb G] [--json OUT] [--write-skip] [--all]
                         exit 0 when every module in scope imported, 1 otherwise
  import_smoke.py skipped [--package P]                        the skip list with reasons
  --changed REF   only modules whose files differ from REF (git) — the push gate's mode;
                  an unknown REF runs nothing and exits 0
  --all           include skipped modules (to see whether a skip is still deserved)
  --write-skip    append every failing module to the skip list with its reason (seeding;
                  afterwards the ratchet refuses growth, so do this deliberately)

The pytest wrapper per package is tests/test_import_smoke.py; scripts/scan.sh runs the
--changed mode on every push.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get('ZYG_SMOKE_ROOT') or os.path.dirname(HERE)
PACKAGES_DIR = os.path.join(ROOT, 'packages')
ENTRY_FILES = ('__main__.py', 'entry.py')  # run a program on import by design: never smoked
GUARDED = ('zyg_workflows.arch_assistant', 'zyg_workflows.comfy_generation_service')

CHILD = r"""
import importlib, json, os, signal, sys, time, traceback
GUARDED = %(guarded)r
class _Guard:
    def find_spec(self, name, path=None, target=None):
        if name in GUARDED or any(name.startswith(g + '.') for g in GUARDED):
            raise ImportError('blocked by import_smoke: ' + name + ' must never be imported for a check')
        return None
sys.meta_path.insert(0, _Guard())
try:
    from zyg_workflows import pgdb  # the test database, never production (as tests/conftest.py)
    os.environ.setdefault('ZYG_PG_DSN', pgdb.DEFAULT_DSN.replace('/zygomatic?', '/zygomatic_test?'))
except Exception:
    pass
class ImportHung(BaseException):
    pass
def _alarm(signum, frame):
    raise ImportHung('import did not return within %(timeout)d s')
signal.signal(signal.SIGALRM, _alarm)
for mod in sys.argv[1:]:
    t0 = time.time(); signal.alarm(%(timeout)d)
    try:
        importlib.import_module(mod)
        rec = {'module': mod, 'ok': True}
    except BaseException as exc:  # SystemExit and KeyboardInterrupt are findings too
        tb = traceback.format_exc().strip().splitlines()
        where = next((l.strip() for l in reversed(tb) if l.strip().startswith('File "') and 'zyg_' in l), '')
        rec = {'module': mod, 'ok': False, 'error': type(exc).__name__ + ': ' + str(exc).splitlines()[0][:200]
               if str(exc) else type(exc).__name__, 'where': where[:200]}
    finally:
        signal.alarm(0)
    rec['secs'] = round(time.time() - t0, 2)
    sys.stdout.write(json.dumps(rec) + '\n'); sys.stdout.flush()
"""


def packages() -> dict[str, tuple[str, str]]:
    """{package dir name: (import name, src path)} for every packages/*/src/<pkg>."""
    out = {}
    for p in sorted(os.listdir(PACKAGES_DIR)):
        src = os.path.join(PACKAGES_DIR, p, 'src')
        if not os.path.isdir(src):
            continue
        for name in sorted(os.listdir(src)):
            if os.path.isdir(os.path.join(src, name)) and os.path.exists(os.path.join(src, name, '__init__.py')):
                out[p] = (name, src)
                break
    return out


def skip_path(package: str) -> str:
    return os.path.join(PACKAGES_DIR, package, 'tests', 'import_smoke_skip.txt')


def read_skip(package: str) -> dict[str, str]:
    """{module: reason} from the package's skip list; blank lines and comments ignored."""
    entries: dict[str, str] = {}
    try:
        with open(skip_path(package), encoding='utf-8') as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith('#'):
                    continue
                mod, _, reason = line.partition('#')
                entries[mod.strip()] = reason.strip()
    except FileNotFoundError:
        pass
    return entries


def write_skip(package: str, entries: dict[str, str]) -> None:
    path = skip_path(package)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('# import_smoke skip list — modules that do not import cleanly yet, one per line:\n')
        fh.write('#   <dotted.module>  # <reason>\n')
        fh.write('# A package entry covers its submodules. This list only shrinks (scripts/ratchet.py\n')
        fh.write('# counts it as smoke_skipped, zero for a new file). Remove a line once the module imports.\n')
        fh.writelines(f'{mod}  # {entries[mod]}\n' for mod in sorted(entries))


def is_skipped(mod: str, skip: dict[str, str]) -> bool:
    return any(mod == s or mod.startswith(s + '.') for s in skip)


def all_modules(package: str) -> list[str]:
    """Every importable dotted name under the package's src tree (entry files excluded)."""
    pkg, src = packages()[package]
    mods = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(src, pkg)):
        dirnames[:] = sorted(d for d in dirnames if d.isidentifier() and d != '__pycache__')
        rel = os.path.relpath(dirpath, src).split(os.sep)
        if not all(part.isidentifier() for part in rel):
            continue
        for f in sorted(filenames):
            if not f.endswith('.py') or f in ENTRY_FILES:
                continue
            stem = f[:-3]
            if not stem.isidentifier():
                continue
            mods.append('.'.join(rel) if stem == '__init__' else '.'.join(rel + [stem]))
    return mods


def module_of(path: str) -> tuple[str, str] | None:
    """(package, dotted module) for a repo-relative file path under packages/*/src, else None."""
    parts = path.split('/')
    if len(parts) < 5 or parts[0] != 'packages' or parts[2] != 'src' or not path.endswith('.py'):
        return None
    if os.path.basename(path) in ENTRY_FILES:
        return None
    rel = parts[3:]
    rel[-1] = rel[-1][:-3]
    if rel[-1] == '__init__':
        rel = rel[:-1]
    if not all(p.isidentifier() for p in rel):
        return None
    return parts[1], '.'.join(rel)


def changed_modules(ref: str) -> dict[str, list[str]] | None:
    """{package: [modules]} whose files differ from REF (index and worktree), None if REF is unknown."""
    if subprocess.run(
        ['git', 'rev-parse', '--verify', '-q', ref], cwd=ROOT, capture_output=True, check=False
    ).returncode:
        return None
    out = subprocess.run(
        ['git', 'diff', '--name-only', '--diff-filter=AMR', ref, '--', 'packages'],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    untracked = subprocess.run(
        ['git', 'ls-files', '--others', '--exclude-standard', '--', 'packages'],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    found: dict[str, list[str]] = defaultdict(list)
    for line in (out + untracked).splitlines():
        hit = module_of(line.strip())
        if hit and os.path.exists(os.path.join(ROOT, line.strip())):
            found[hit[0]].append(hit[1])
    return {p: sorted(set(m)) for p, m in found.items()}


def python_for(package: str) -> str:
    """The interpreter that can import the package: the current one if it can, else the root venv."""
    cur = sys.executable
    venv = os.path.join(ROOT, '.venv', 'bin', 'python')
    pkg = packages()[package][0]
    for cand in (cur, venv):
        if (
            os.path.exists(cand)
            and subprocess.run([cand, '-c', f'import {pkg}'], capture_output=True, check=False).returncode == 0
        ):
            return cand
    return cur


def child_env() -> dict[str, str]:
    env = os.environ.copy()
    env['CUDA_VISIBLE_DEVICES'] = ''
    env['ZYG_IMPORT_SMOKE'] = '1'
    env['PYTHONUNBUFFERED'] = '1'
    env.pop('DISPLAY', None)  # a GUI toolkit must not open a window from an import
    return env


def _rss_gb(pid: int) -> float:
    try:
        with open(f'/proc/{pid}/status', encoding='utf-8') as fh:
            for line in fh:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) / (1024 * 1024)
    except OSError:
        pass
    return 0.0


def _watchdog(
    proc: subprocess.Popen,
    done: threading.Event,
    verdict: list[str],
    mem_gb: float,
    quiet: float,
    progress: list[float],
) -> None:
    """Kill the child when it outgrows --mem-gb or reports nothing for *quiet* seconds; say why in *verdict*."""
    while not done.wait(0.5):
        if _rss_gb(proc.pid) > mem_gb:
            verdict.append(f'killed: resident memory above {mem_gb:g} GB during import')
            proc.kill()
            return
        if time.time() - progress[0] > quiet:
            verdict.append(f'killed: no import returned for {quiet:g} s (hung in C, a thread join, or a server loop)')
            proc.kill()
            return


def run_batch(python: str, mods: list[str], timeout: int, mem_gb: float, cwd: str) -> list[dict]:
    """Import *mods* in order in one child; restart after any module that kills or hangs the child."""
    results: list[dict] = []
    code = CHILD % {'guarded': GUARDED, 'timeout': timeout}
    pending = list(mods)
    while pending:
        proc = subprocess.Popen(
            [python, '-c', code, *pending],
            cwd=cwd,
            env=child_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # one pipe, drained line by line: a second, undrained pipe hangs a chatty import
            text=True,
            errors='replace',
        )
        done = threading.Event()
        verdict: list[str] = []
        progress = [time.time()]
        th = threading.Thread(target=_watchdog, args=(proc, done, verdict, mem_gb, timeout + 15, progress), daemon=True)
        th.start()
        got = []
        noise: list[str] = []
        assert proc.stdout is not None
        for line in proc.stdout:
            progress[0] = time.time()
            line = line.rstrip('\n')
            if not line.startswith('{"module"'):
                noise.append(line.strip()[:200])
                del noise[:-6]
                continue
            try:
                got.append(json.loads(line))
            except ValueError:
                continue
        proc.wait()
        done.set()
        th.join()
        results.extend(got)
        reported = {r['module'] for r in got}
        rest = [m for m in pending if m not in reported]
        if not rest:
            break
        culprit = rest[0]
        tail = ' | '.join(noise[-2:])[:200] if noise else ''
        killed_for = verdict[0] if verdict else None
        results.append(
            {
                'module': culprit,
                'ok': False,
                'secs': 0.0,
                'error': killed_for
                or f'child died (exit {proc.returncode}) during import' + (f': {tail}' if tail else ''),
            }
        )
        pending = rest[1:]
    return results


def run(package: str, mods: list[str], workers: int, timeout: int, mem_gb: float) -> list[dict]:
    """Batch by top-level directory so siblings share one interpreter; batches run in parallel."""
    if not mods:
        return []
    python = python_for(package)
    cwd = os.path.join(PACKAGES_DIR, package)
    batches: dict[str, list[str]] = defaultdict(list)
    for m in mods:
        parts = m.split('.')
        batches[parts[1] if len(parts) > 2 else '(root)'].append(m)
    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for res in pool.map(lambda b: run_batch(python, b, timeout, mem_gb, cwd), batches.values()):
            out.extend(res)
    # A module that fails only because a sibling imported before it in the same interpreter
    # left global state behind (a Flask blueprint registered twice, an op table filled) is not
    # a failure: every failure is retried alone in a fresh process and that verdict stands.
    failed = [r['module'] for r in out if not r['ok']]
    if failed:
        retried: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            for res in pool.map(lambda m: run_batch(python, [m], timeout, mem_gb, cwd), failed):
                for r in res:
                    retried[r['module']] = r
        out = [retried.get(r['module'], r) if not r['ok'] else r for r in out]
        for r in out:
            if r['ok'] and r['module'] in retried and r.get('secs') is not None:
                r['batch_only'] = True  # imported fine alone; failed only after its batch siblings
    return sorted(out, key=lambda r: r['module'])


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('cmd', choices=['list', 'run', 'skipped'])
    ap.add_argument('--package', '-p', action='append', help='packages/<name>; default: every package')
    ap.add_argument('--only', nargs='*', default=None, help='dotted modules to import (one package)')
    ap.add_argument('--changed', metavar='REF', help='only modules whose files differ from this git ref')
    ap.add_argument('--workers', type=int, default=min(8, max(1, (os.cpu_count() or 4) // 3)))
    ap.add_argument('--timeout', type=int, default=90, help='seconds one import may take')
    ap.add_argument('--mem-gb', type=float, default=12.0, help='kill a child above this resident size')
    ap.add_argument('--json', metavar='OUT', help='write every result here')
    ap.add_argument('--write-skip', action='store_true', help='append failures to the skip list')
    ap.add_argument('--all', action='store_true', help='include skipped modules')
    ap.add_argument('--prune', action='store_true', help='retest the skip list and drop every module that imports now')
    ap.add_argument('--quiet', '-q', action='store_true')
    a = ap.parse_args(argv)

    pkgs = packages()
    names = a.package or sorted(pkgs)
    unknown = [p for p in names if p not in pkgs]
    if unknown:
        print(f'import_smoke: no such package under packages/: {", ".join(unknown)}')
        return 2

    changed = None
    if a.changed:
        changed = changed_modules(a.changed)
        if changed is None:
            print(f'import smoke: ref {a.changed} is unknown here — nothing checked')
            return 0

    failed_total = 0
    all_results: dict[str, list[dict]] = {}
    for package in names:
        skip = read_skip(package)
        if a.cmd == 'skipped':
            for m, why in sorted(skip.items()):
                print(f'{package}  {m}  # {why}')
            continue
        if a.prune:
            mods = [m for m in all_modules(package) if is_skipped(m, skip)]
            results = run(package, mods, a.workers, a.timeout, a.mem_gb)
            good = {r['module'] for r in results if r['ok']}
            gone = [m for m in skip if m in good]
            for m in gone:
                del skip[m]
            if gone:
                write_skip(package, skip)
            print(
                f'import smoke: {package}  prune: {len(gone)} of {len(mods)} skipped modules import now and were removed'
            )
            continue
        if a.only is not None:
            mods = list(a.only)
        elif changed is not None:
            mods = changed.get(package, [])
        else:
            mods = all_modules(package)
        if not a.all:
            mods = [m for m in mods if not is_skipped(m, skip)]
        if a.cmd == 'list':
            for m in mods:
                print(m)
            continue
        t0 = time.time()
        results = run(package, mods, a.workers, a.timeout, a.mem_gb)
        all_results[package] = results
        bad = [r for r in results if not r['ok']]
        failed_total += len(bad)
        if not a.quiet or bad:
            for r in bad:
                where = f'  @ {r["where"]}' if r.get('where') else ''
                print(f'FAIL {package}  {r["module"]}  {r["error"]}{where}')
        print(
            f'import smoke: {package}  {len(results) - len(bad)}/{len(results)} modules import'
            f'  ({len(skip)} skipped, {time.time() - t0:.0f} s)'
        )
        if a.write_skip and bad:
            for r in bad:
                skip.setdefault(r['module'], r['error'][:160])
            write_skip(package, skip)
            print(f'import smoke: {len(bad)} modules appended to {os.path.relpath(skip_path(package), ROOT)}')
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as fh:
            json.dump(all_results, fh, indent=1)
    return 1 if failed_total and not a.write_skip else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
