# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ratchet selftest — the rules proved on a synthetic git repo (see ratchet.py --selftest).

Split out of ratchet.py on 2026-10-13 (modcheck rule C).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

from ratchet import HERE, MARKER

# ── selftest: the rules proved on a synthetic git repo ───────────────────────

SELFTEST_MODULE = '''# a module with a few counted habits
import sys


def public_one(a):
    """Documented."""
    try:
        return a
    except Exception:
        return None


def public_two(a):
    try:
        print(a)
    except Exception:
        pass
    return a  # noqa: RET504 — kept for the selftest


def _private(a):
    sys.path.insert(0, a)
    return a
'''

SELFTEST_CLI = '''"""An allowlisted CLI: its print() calls do not count."""


def main():
    print('hello')
    return 0
'''


def _git(repo, *args):
    return subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True, check=True)


def _run(repo, *args, extra_env=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env['ZYG_RATCHET_ROOT'] = repo
    env['ZYG_RATCHET_BASELINE'] = os.path.join(repo, 'scripts', 'ratchet_baseline.json')
    env.pop('ZYG_RATCHET_UP_OK', None)
    env.update(extra_env or {})
    return subprocess.run(  # noqa: PLW1510 — the return code is the thing under test
        [sys.executable, os.path.join(HERE, 'ratchet.py'), *args], capture_output=True, text=True, env=env
    )


def _read_baseline(repo):
    with open(os.path.join(repo, 'scripts', 'ratchet_baseline.json'), encoding='utf-8') as f:
        return json.load(f)


def _write(repo, rel, text):
    """Write a file and stage it — the gate reads the index, so an unstaged file is invisible."""
    full = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8') as f:
        f.write(text)
    _git(repo, 'add', '-A')
    return full


def _build_repo(repo):
    _git(repo, 'init', '-q')
    _git(repo, 'config', 'user.email', 'selftest@example.invalid')
    _git(repo, 'config', 'user.name', 'selftest')
    pkg = 'packages/demo/src/demo_pkg'
    _write(repo, f'{pkg}/mod.py', SELFTEST_MODULE)
    _write(repo, f'{pkg}/cli.py', SELFTEST_CLI)
    _write(repo, f'{pkg}/data/table.csv', 'a,b\n1,2\n')
    _git(repo, 'add', '-A')


def _case(results, label, ok, detail=''):
    results.append((label, ok, detail))
    print(f'  {"ok  " if ok else "FAIL"}  {label}' + (f' — {detail}' if detail and not ok else ''))


def selftest():
    print('ratchet selftest: synthetic git repo')
    results: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory(prefix='ratchet-selftest-') as repo:
        _build_repo(repo)
        pkg = 'packages/demo/src/demo_pkg'

        r = _run(repo, 'baseline', '--init')
        _case(results, 'baseline --init succeeds', r.returncode == 0, r.stdout + r.stderr)
        base = _read_baseline(repo)
        _case(
            results,
            'baseline records 2 broad_except and 1 print_calls (cli.py allowlisted)',
            base['metrics']['broad_except']['total'] == 2 and base['metrics']['print_calls']['total'] == 1,
            json.dumps(base['metrics']['broad_except']),
        )
        _case(
            results,
            'baseline freezes the data/ dir and both missing docstrings',
            base['metrics']['nonpy_dirs']['entries'].get(f'{pkg}/data') == 1
            and base['metrics']['missing_docstrings']['total'] == 2,
            json.dumps(base['metrics']['nonpy_dirs']) + json.dumps(base['metrics']['missing_docstrings']),
        )

        r = _run(repo, 'check')
        _case(results, 'check is clean on the baselined tree', r.returncode == 0, r.stdout + r.stderr)

        original = SELFTEST_MODULE
        grown = '\n\ndef grown():\n    """Doc."""\n    try:\n        pass\n    except Exception:\n        pass\n'
        _write(repo, f'{pkg}/mod.py', original + grown)
        r = _run(repo, 'check')
        _case(
            results,
            'a grown broad_except count fails check',
            r.returncode == 1 and 'broad_except 2→3' in r.stdout,
            r.stdout + r.stderr,
        )
        r = _run(repo, 'baseline')
        _case(results, 'baseline refuses to record the growth', r.returncode == 1, r.stdout + r.stderr)
        r = _run(repo, 'baseline', '--allow-up', 'selftest')
        _case(
            results,
            '--allow-up records it and says RE-RECORDED UP',
            r.returncode == 0 and 'RE-RECORDED UP' in r.stdout,
            r.stdout + r.stderr,
        )

        shrunk = original.replace('    except Exception:\n        pass\n', '    finally:\n        pass\n', 1)
        _write(repo, f'{pkg}/mod.py', shrunk)
        r = _run(repo, 'baseline')
        _case(results, 'a shrunk count re-baselines without --allow-up', r.returncode == 0, r.stdout + r.stderr)
        base = _read_baseline(repo)
        _case(
            results,
            'the re-baselined total went down to 1',
            base['metrics']['broad_except']['total'] == 1,
            json.dumps(base['metrics']['broad_except']),
        )
        r = _run(repo, 'check')
        _case(results, 'check is clean again after the ratchet', r.returncode == 0, r.stdout + r.stderr)

        _write(repo, f'{pkg}/anchored.py', '"""New module."""\n\nimport os\n\n__file__ = os.path.abspath(__file__)\n')
        _git(repo, 'add', '-A')
        r = _run(repo, 'check')
        _case(
            results,
            'a new file with a dunder rebind fails check',
            r.returncode == 1 and 'dunder_rebinds 0→1' in r.stdout,
            r.stdout + r.stderr,
        )
        _git(repo, 'rm', '-q', '-f', f'{pkg}/anchored.py')
        r = _run(repo, 'check')
        _case(results, 'removing it makes check clean', r.returncode == 0, r.stdout + r.stderr)

        enormous = 'def enormous():\n    """Doc."""\n' + '    pass\n' * 301
        _write(repo, f'{pkg}/long.py', f'"""Long."""\n\n\n{enormous}')
        _git(repo, 'add', '-A')
        r = _run(repo, 'check')
        _case(
            results,
            'a def over 300 lines fails check',
            r.returncode == 1 and 'long_functions 0→1' in r.stdout,
            r.stdout + r.stderr,
        )
        _write(repo, f'{pkg}/long.py', f'{MARKER}\n"""Long."""\n\n\n{enormous}')
        r = _run(repo, 'check')
        _case(
            results,
            f'the same def is exempt under the {MARKER} marker',
            r.returncode == 0,
            r.stdout + r.stderr,
        )
        _git(repo, 'rm', '-q', '-f', f'{pkg}/long.py')

        _write(repo, f'{pkg}/data/a table.csv', 'a,b\n')
        _git(repo, 'add', '-A')
        r = _run(repo, 'check')
        _case(
            results,
            'a tracked path with a space fails check',
            r.returncode == 1 and 'space_paths 0→1' in r.stdout,
            r.stdout + r.stderr,
        )
        _git(repo, 'rm', '-q', '-f', f'{pkg}/data/a table.csv')

        _write(repo, f'{pkg}/images/new.png', 'x')
        _git(repo, 'add', '-A')
        r = _run(repo, 'check')
        _case(
            results,
            'a brand-new non-.py directory fails check',
            r.returncode == 1 and f'{pkg}/images: nonpy_dirs 0→1' in r.stdout,
            r.stdout + r.stderr,
        )
        _git(repo, 'rm', '-q', '-f', f'{pkg}/images/new.png')

        # direction: the baseline FILE may not record a higher total than the reference revision's.
        _git(repo, 'add', '-A')
        _git(repo, 'commit', '-q', '-m', 'selftest: the baselined tree')
        _git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
        r = _run(repo, 'direction')
        _case(results, 'direction is clean against an identical baseline', r.returncode == 0, r.stdout + r.stderr)
        r = _run(repo, 'direction', '--against', 'refs/remotes/origin/nosuch')
        _case(
            results,
            'direction skips an unreachable reference revision',
            r.returncode == 0 and 'not reachable' in r.stdout,
            r.stdout + r.stderr,
        )
        _write(repo, f'{pkg}/mod.py', original + grown)
        r = _run(repo, 'baseline', '--allow-up', 'selftest')
        _case(results, '--allow-up raises the recorded total', r.returncode == 0, r.stdout + r.stderr)
        r = _run(repo, 'direction')
        _case(
            results,
            'direction refuses a baseline raised behind the check gate',
            r.returncode == 1 and 'broad_except: 1→3' in r.stdout,
            r.stdout + r.stderr,
        )
        r = _run(repo, 'direction', extra_env={'ZYG_RATCHET_UP_OK': 'selftest reason'})
        _case(
            results,
            'ZYG_RATCHET_UP_OK lets the raise through as a note',
            r.returncode == 0 and 'selftest reason' in r.stdout,
            r.stdout + r.stderr,
        )

        # smoke_skipped: a skip list may only shrink, and a new module cannot be born on it.
        skip = 'packages/demo/tests/import_smoke_skip.txt'
        _write(repo, skip, '# seeded\ndemo_pkg.mod  # needs bpy\n')
        r = _run(repo, 'baseline', '--allow-up', 'selftest: seed smoke list')
        base = _read_baseline(repo)
        _case(
            results,
            'baseline records the seeded smoke_skipped entry',
            r.returncode == 0 and base['metrics']['smoke_skipped']['entries'].get('demo:demo_pkg.mod') == 1,
            r.stdout + r.stderr + json.dumps(base['metrics'].get('smoke_skipped')),
        )
        _write(repo, skip, '# seeded\ndemo_pkg.mod  # needs bpy\ndemo_pkg.cli  # new\n')
        r = _run(repo, 'check')
        _case(
            results,
            'a module added to the skip list fails check',
            r.returncode == 1 and 'demo:demo_pkg.cli: smoke_skipped 0→1' in r.stdout,
            r.stdout + r.stderr,
        )
        _write(repo, skip, '# seeded\n')
        r = _run(repo, 'check')
        _case(results, 'an emptied skip list passes check', r.returncode == 0, r.stdout + r.stderr)

        # coverage: package rate, per-directory rates, and new modules must be executed.
        def xml(files):
            classes = ''.join(
                f'<class name="x" filename="{fn}"><lines>'
                + ''.join(f'<line number="{i + 1}" hits="{h}"/>' for i, h in enumerate(hits))
                + '</lines></class>'
                for fn, hits in files.items()
            )
            n = sum(len(h) for h in files.values())
            k = sum(sum(1 for x in h if x) for h in files.values())
            return (
                f'<?xml version="1.0" ?><coverage line-rate="{k / n:.4f}" lines-valid="{n}" lines-covered="{k}">'
                f'<packages><package name="p"><classes>{classes}</classes></package></packages></coverage>'
            )

        cov1 = os.path.join(repo, 'cov1.xml')
        with open(cov1, 'w', encoding='utf-8') as f:
            f.write(xml({'src/demo_pkg/a/one.py': [1, 1, 0, 0], 'src/demo_pkg/b/two.py': [1, 0, 0, 0]}))
        r = _run(repo, 'coverage', cov1, '--package', 'demo', '--baseline')
        base = _read_baseline(repo)
        _case(
            results,
            'coverage --baseline records the package and per-directory rates',
            r.returncode == 0
            and base['coverage']['demo'] == 37.5
            and base['coverage_dirs']['demo'] == {'a': 50.0, 'b': 25.0},
            r.stdout + r.stderr + json.dumps(base.get('coverage_dirs')),
        )
        cov2 = os.path.join(repo, 'cov2.xml')
        with open(cov2, 'w', encoding='utf-8') as f:
            f.write(xml({'src/demo_pkg/a/one.py': [1, 1, 1, 1], 'src/demo_pkg/b/two.py': [0, 0, 0, 0]}))
        r = _run(repo, 'coverage', cov2, '--package', 'demo', '--since', 'HEAD')
        _case(
            results,
            'a directory that lost coverage fails even when the package rate rose',
            r.returncode == 1 and 'demo/b fell 25.00% → 0.00%' in r.stdout,
            r.stdout + r.stderr,
        )
        _git(repo, 'add', '-A')
        _git(repo, 'commit', '-q', '-m', 'selftest: before the new module')
        _write(repo, f'{pkg}/b/fresh.py', '"""New."""\n')
        _git(repo, 'commit', '-q', '-m', 'selftest: a new module')
        r = _run(repo, 'coverage', cov1, '--package', 'demo', '--since', 'HEAD~1')
        _case(
            results,
            'a module added since the reference that no test measured fails',
            r.returncode == 1 and 'fresh.py: added since HEAD~1 but absent' in r.stdout,
            r.stdout + r.stderr,
        )
        cov3 = os.path.join(repo, 'cov3.xml')
        with open(cov3, 'w', encoding='utf-8') as f:
            f.write(
                xml(
                    {
                        'src/demo_pkg/a/one.py': [1, 1, 0, 0],
                        'src/demo_pkg/b/two.py': [1, 0, 0, 0],
                        'src/demo_pkg/b/fresh.py': [0],
                    }
                )
            )
        r = _run(repo, 'coverage', cov3, '--package', 'demo', '--since', 'HEAD~1')
        _case(
            results,
            'a new module with zero executed lines fails',
            r.returncode == 1 and 'no test executes a single line of it' in r.stdout,
            r.stdout + r.stderr,
        )
        cov4 = os.path.join(repo, 'cov4.xml')
        with open(cov4, 'w', encoding='utf-8') as f:
            f.write(
                xml(
                    {
                        'src/demo_pkg/a/one.py': [1, 1, 0, 0],
                        'src/demo_pkg/b/two.py': [1, 0, 0, 0],
                        'src/demo_pkg/b/fresh.py': [1],
                    }
                )
            )
        r = _run(repo, 'coverage', cov4, '--package', 'demo', '--since', 'HEAD~1')
        _case(
            results,
            'a new module the import smoke executes passes',
            r.returncode == 0 and '1 new modules executed' in r.stdout,
            r.stdout + r.stderr,
        )
        r = _run(repo, 'coverage', cov4, '--package', 'demo', '--since', 'refs/remotes/origin/nosuch')
        _case(
            results,
            'an unknown --since reference skips the new-module rule, not the gate',
            r.returncode == 0 and 'new-module rule not checked' in r.stdout,
            r.stdout + r.stderr,
        )

    failed = [label for label, ok, _ in results if not ok]
    print(f'selftest: {len(results) - len(failed)}/{len(results)} cases behaved as expected')
    if failed:
        for label, ok, detail in results:
            if not ok:
                print(f'--- {label} ---\n{detail.strip()}', file=sys.stderr)
    return 1 if failed else 0


# ── entry point ──────────────────────────────────────────────────────────────
