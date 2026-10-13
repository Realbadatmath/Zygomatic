#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ratchet — quality counters that only ever go down.

The 2026-10-08 repo audit counted habits nobody wants more of: 300-line functions, bare
`except Exception`, `print()` in library code, `# noqa` markers, `__file__`/`__name__`
rebinds, `sys.path` edits, pre-monorepo path literals, missing docstrings, paths with a
space in them. None of them can be fixed in one pass, so this tool freezes the count of
each one *per file* in scripts/ratchet_baseline.json and refuses any commit that pushes a
count up. `baseline` re-records the counts, downwards only; going up needs `--allow-up`
with a reason and says so loudly — but nothing used to notice afterwards, so `direction`
diffs the recorded totals against another revision's baseline (origin/main) and refuses a
rise unless ZYG_RATCHET_UP_OK holds the reason.

Scope: files tracked by git under packages/*/src/** for the per-file metrics; the whole index
for space_paths and nonpy_dirs. Contents are read from git's INDEX, not the worktree, so the
gate always measures the tree that is about to be committed (pre-commit stashes unstaged
changes before it runs a hook; an unstaged edit is nothing a gate should pass or refuse).

Metrics (each a per-file integer; a file is only listed when its count is non-zero):
  long_functions     defs/async defs (methods and nested ones too) longer than 300 lines
  broad_except       `except Exception/BaseException ...` and bare `except:` lines
  print_calls        statement-level `print(` lines outside the CLI/script allowlist
  noqa_markers       occurrences of '# noqa'
  dunder_rebinds     `__file__ = ` / `__name__ = ` lines (zero-rule: a new file gets none)
  sys_path_edits     sys.path.insert/append outside **/__main__.py and **/entry.py
  legacy_literals    'Zygomatic Full' / 'agents/crews' outside zyg_workflows/paths.py
  missing_docstrings public module-level functions and classes with no docstring
  space_paths        tracked paths containing a space (zero-rule: no new ones)
  nonpy_dirs         per packages/<p>/src/<pkg>/<topdir>, tracked files that are neither
                     .py nor .license; the set of such dirs is frozen (zero-rule), the
                     counts inside an already-known dir are free
  pyright_errors     per package, with --with-pyright and a pyrightconfig.json (optional)
  smoke_skipped      per module listed in packages/*/tests/import_smoke_skip.txt (the modules
                     scripts/import_smoke.py may not import yet); zero-rule: a new module cannot
                     be born skipped, and the list only shrinks

Coverage (`coverage` command, run by CI after pytest-cov) is gated three ways: the package's
line rate may not fall more than 0.5 pp below its baseline; neither may any top-level source
directory's own rate (so a tested corner stays tested while the rest catches up); and a module
ADDED since origin/main (or --since REF) must have at least one executed line — the cheapest
test there is, the import smoke, already gives a module that.

Commands:
  ratchet.py check [--with-pyright]            gate mode: 0 clean, 1 a counter went up
  ratchet.py report [--with-pyright]           totals per metric + the top 10 files each
  ratchet.py baseline [--init] [--allow-up R]  write/tighten the baseline
  ratchet.py direction [--against REV]         gate mode: 1 if a baseline total rose vs REV
  ratchet.py coverage FILE --package P [--baseline] [--since REF]
                                               pytest-cov XML line rates vs baseline (package,
                                               per directory, new modules must be executed)
  ratchet.py --selftest                        prove the rules on a synthetic git repo

This tool never edits source files; it only counts and refuses.
"""

from __future__ import annotations

import ast
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

LONG_FUNCTION_LINES = int(os.environ.get('ZYG_RATCHET_LONG_LINES', '300'))
COVERAGE_SLACK_PP = 0.5  # percentage points a coverage run may fall below the baseline
MARKER = '# zyg: no-split'  # provenance files: the layout IS the spec, long defs included

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get('ZYG_RATCHET_ROOT') or os.path.dirname(HERE)
BASELINE_PATH = os.environ.get('ZYG_RATCHET_BASELINE') or os.path.join(ROOT, 'scripts', 'ratchet_baseline.json')

IN_SCOPE_RE = re.compile(r'^packages/[^/]+/src/.*\.py$')
TOPDIR_RE = re.compile(r'^(packages/[^/]+/src/[^/]+/[^/]+)/')
BROAD_EXCEPT_RE = re.compile(r'^\s*except\s*(\(?\s*(Exception|BaseException)\b|:)')
PRINT_RE = re.compile(r'^\s*print\(')
DUNDER_RE = re.compile(r'^(__file__|__name__)\s*=')

PRINT_ALLOW = (
    '**/__main__.py',
    '**/cli.py',
    '**/*_cli.py',
    '**/selftest.py',
    '**/scripts/**',
    '**/prop_mesh/pufferball_look.py',
)
SYS_PATH_ALLOW = ('**/__main__.py', '**/entry.py')
LEGACY_EXEMPT = ('packages/workflows/src/zyg_workflows/paths.py',)  # the env defaults live here
LEGACY_LITERALS = ('Zygomatic Full', 'agents/crews')


@dataclass(frozen=True)
class Metric:
    """How one counter is gated. `key` names what the per-entry counts are keyed by."""

    label: str
    key: str = 'file'
    zero_for_new: bool = False  # an entry absent from the baseline must count 0
    gate_growth: bool = True  # a known entry may not grow, and neither may the total
    optional: bool = False  # only collected on request; skipped when absent
    slack: float = 0.0  # tolerated growth as a fraction of the baseline (a noisy counter); 0 = exact


METRICS: dict[str, Metric] = {
    'long_functions': Metric(f'defs longer than {LONG_FUNCTION_LINES} lines'),
    'broad_except': Metric('broad/bare except lines'),
    'print_calls': Metric('print() lines in library code'),
    'noqa_markers': Metric('# noqa markers'),
    'dunder_rebinds': Metric('__file__/__name__ rebinds', zero_for_new=True),
    'sys_path_edits': Metric('sys.path insert/append'),
    'legacy_literals': Metric('pre-monorepo path literals'),
    'missing_docstrings': Metric('public module-level defs without a docstring'),
    'file_noqa': Metric('file-level `# ruff: noqa` lines (a whole file exempted from a rule)'),
    'space_paths': Metric('tracked paths containing a space', key='path', zero_for_new=True),
    'nonpy_dirs': Metric('non-.py files per src subdirectory', key='dir', zero_for_new=True, gate_growth=False),
    # pyright's count on the CI runner varies between identical runs (2026-10-09: 3199, 3226, 3227 for
    # one tree), so this one counter tolerates 1.5 % above the recorded figure instead of exact growth.
    'pyright_errors': Metric('pyright errors', key='package', optional=True, slack=0.015),
    'smoke_skipped': Metric('modules on an import_smoke skip list', key='module', zero_for_new=True),
}
SMOKE_SKIP_RE = re.compile(r'^packages/[^/]+/tests/import_smoke_skip\.txt$')


def sh(args, **kw):
    kw.setdefault('check', False)
    return subprocess.run(  # noqa: PLW1510 — check comes through kw, default False
        args, cwd=ROOT, capture_output=True, text=True, **kw
    )


def index_blobs():
    """{path: blob sha} for git's index — exactly what a commit would contain.

    The index, not the worktree: pre-commit stashes unstaged changes before it runs a hook,
    so a worktree-reading gate measures a tree that is not the one being committed (and, in
    a repo several agents edit at once, not even a stable one).  During a pathspec commit
    (`git commit -- <paths>`) git points the hooks at a TEMPORARY index of HEAD plus those
    paths, which is why the baseline is seeded from HEAD:
        D=$(mktemp -d); GIT_INDEX_FILE=$D/index git read-tree HEAD
        GIT_INDEX_FILE=$D/index python3 scripts/ratchet.py baseline --init
    `git ls-files -s -z` keeps a space in a path intact.
    """
    out = sh(['git', 'ls-files', '-s', '-z']).stdout
    blobs = {}
    for record in out.split('\0'):
        if not record:
            continue
        meta, _, path = record.partition('\t')
        fields = meta.split()
        if len(fields) >= 2 and path:
            blobs[path] = fields[1]
    return blobs


def tracked_py(paths=None):
    paths = list(index_blobs()) if paths is None else paths
    return [p for p in paths if IN_SCOPE_RE.match(p)]


def blob_texts(blobs):
    """{path: text} for the given {path: sha}, read in one `git cat-file --batch` pass."""
    if not blobs:
        return {}
    paths = list(blobs)
    stdin = ('\n'.join(blobs[p] for p in paths) + '\n').encode()
    data = subprocess.run(  # noqa: PLW1510 — a missing blob is reported in the stream, not the rc
        ['git', 'cat-file', '--batch'], cwd=ROOT, input=stdin, capture_output=True
    ).stdout
    texts, pos = {}, 0
    for path in paths:
        end = data.find(b'\n', pos)
        if end < 0:
            break
        fields = data[pos:end].split()
        if len(fields) < 3:  # '<sha> missing': no payload follows
            pos = end + 1
            continue
        size = int(fields[2])
        texts[path] = data[end + 1 : end + 1 + size].decode('utf-8', 'replace')
        pos = end + 1 + size + 1
    return texts


def matches(path, patterns):
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


# ── counting ─────────────────────────────────────────────────────────────────


def count_long_functions(tree):
    n = 0
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and getattr(node, 'end_lineno', node.lineno) - node.lineno + 1 > LONG_FUNCTION_LINES
        ):
            n += 1
    return n


def count_missing_docstrings(tree):
    n = 0
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and not node.name.startswith('_')
            and ast.get_docstring(node) is None
        ):
            n += 1
    return n


def file_metrics(path, text):
    """Every per-file counter for one in-scope Python file."""
    lines = text.splitlines()
    no_split = MARKER in '\n'.join(lines[:60])
    out = {
        'broad_except': sum(1 for ln in lines if BROAD_EXCEPT_RE.match(ln)),
        'print_calls': 0 if matches(path, PRINT_ALLOW) else sum(1 for ln in lines if PRINT_RE.match(ln)),
        'noqa_markers': text.count('# noqa'),
        'file_noqa': sum(1 for ln in lines if ln.startswith('# ruff: noqa')),
        'dunder_rebinds': sum(1 for ln in lines if DUNDER_RE.match(ln)),
        'sys_path_edits': 0
        if matches(path, SYS_PATH_ALLOW)
        else sum(text.count(f'sys.path.{m}(') for m in ('insert', 'append')),
        'legacy_literals': 0 if path in LEGACY_EXEMPT else sum(text.count(lit) for lit in LEGACY_LITERALS),
    }
    try:
        tree = ast.parse(text)
    except SyntaxError:
        out['long_functions'] = 0
        out['missing_docstrings'] = 0
        return out
    out['long_functions'] = 0 if no_split else count_long_functions(tree)
    out['missing_docstrings'] = count_missing_docstrings(tree)
    return out


def pyright_errors():
    """Errors per package, or None when pyright or its config is unavailable."""
    config = os.path.join(ROOT, 'pyrightconfig.json')
    binary = os.path.join(ROOT, '.venv', 'bin', 'pyright')
    if not os.path.exists(binary):
        binary = shutil.which('pyright')
    if not os.path.exists(config) or not binary:
        print('note: pyright_errors skipped (no pyrightconfig.json or no pyright binary)')
        return None
    r = sh([binary, '-p', config, '--outputjson'])
    dump = os.environ.get('ZYG_PYRIGHT_DUMP')
    if dump:  # CI keeps the raw diagnostics as an artifact so a raised count can be traced to files
        with open(dump, 'w', encoding='utf-8') as fh:
            fh.write(r.stdout)
    try:
        payload = json.loads(r.stdout)
    except ValueError:
        print(f'note: pyright_errors skipped (unreadable --outputjson, rc {r.returncode})')
        return None
    counts: dict[str, int] = {}
    for diag in payload.get('generalDiagnostics', []):
        if diag.get('severity') != 'error':
            continue
        rel = os.path.relpath(diag.get('file', ''), ROOT)
        m = re.match(r'^packages/([^/]+)/', rel)
        if m:
            counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    return counts


def collect(with_pyright=False):
    """Current value of every metric: {metric: {key: count}}, zero counts omitted."""
    counts: dict[str, dict[str, int]] = {name: {} for name, m in METRICS.items() if not m.optional}
    blobs = index_blobs()
    paths = list(blobs)
    for path, text in blob_texts({p: blobs[p] for p in tracked_py(paths)}).items():
        for name, value in file_metrics(path, text).items():
            if value:
                counts[name][path] = value
    for path in paths:
        if ' ' in path:
            counts['space_paths'][path] = 1
    for path, text in blob_texts({p: blobs[p] for p in paths if SMOKE_SKIP_RE.match(p)}).items():
        package = path.split('/')[1]
        for raw in text.splitlines():
            line = raw.strip()
            if line and not line.startswith('#'):
                counts['smoke_skipped'][package + ':' + line.partition('#')[0].strip()] = 1
    for path in paths:
        m = TOPDIR_RE.match(path)
        if m and not path.endswith(('.py', '.license')):
            counts['nonpy_dirs'][m.group(1)] = counts['nonpy_dirs'].get(m.group(1), 0) + 1
    if with_pyright:
        found = pyright_errors()
        if found is not None:
            counts['pyright_errors'] = found
    return counts


# ── baseline file ────────────────────────────────────────────────────────────


def load_baseline():
    if not os.path.exists(BASELINE_PATH):
        return {'generated': None, 'metrics': {}, 'coverage': {}, 'allow_up': []}
    with open(BASELINE_PATH, encoding='utf-8') as f:
        data = json.load(f)
    data.setdefault('metrics', {})
    data.setdefault('coverage', {})
    data.setdefault('allow_up', [])
    return data


def save_baseline(data):
    os.makedirs(os.path.dirname(BASELINE_PATH), exist_ok=True)
    with open(BASELINE_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1, sort_keys=False)
        f.write('\n')


def recorded(baseline, name):
    entry = baseline['metrics'].get(name, {})
    return entry.get('entries', {}), entry.get('total', 0)


def as_entry(counts):
    return {'total': sum(counts.values()), 'entries': dict(sorted(counts.items()))}


# ── commands ─────────────────────────────────────────────────────────────────


def _ceiling(recorded_value, metric):
    """The highest current value that still passes: the recorded one, plus the metric's slack."""
    return recorded_value + int(recorded_value * metric.slack)


def _slack_note(metric):
    return f' (even with the {metric.slack:.1%} slack this noisy counter is allowed)' if metric.slack else ''


def cmd_check(with_pyright=False):
    baseline = load_baseline()
    if not baseline['generated']:
        print(f'ratchet: no baseline at {BASELINE_PATH} — run `ratchet.py baseline --init` first')
        return 1
    current = collect(with_pyright)
    violations = []
    for name, metric in METRICS.items():
        if name not in current:
            continue
        base_entries, base_total = recorded(baseline, name)
        counts = current[name]
        for key in sorted(counts):
            n = counts[key]
            if key in base_entries:
                if metric.gate_growth and n > _ceiling(base_entries[key], metric):
                    violations.append(f'{key}: {name} {base_entries[key]}→{n}' + _slack_note(metric))
            elif metric.zero_for_new and n > 0:
                violations.append(f'{key}: {name} 0→{n} — a new {metric.key} must carry none of these')
        total = sum(counts.values())
        if metric.gate_growth and total > _ceiling(base_total, metric):
            violations.append(
                f'TOTAL: {name} {base_total}→{total} — the counter may only go down' + _slack_note(metric)
            )
    if violations:
        print(f'ratchet: {len(violations)} counter(s) went up:')
        for v in violations:
            print('  ' + v)
        print('  fix the new occurrences, or re-record deliberately: ratchet.py baseline --allow-up "<reason>"')
        return 1
    scored = sum(len(current[n]) for n in current)
    print(f'ratchet: clean ({len(METRICS) - 1} metrics, {scored} recorded entries, {len(tracked_py())} .py in scope)')
    return 0


def cmd_report(with_pyright=False):
    baseline = load_baseline()
    current = collect(with_pyright)
    print(f'{"metric":<19} {"now":>8} {"baseline":>9} {"delta":>7}  files  description')
    for name, metric in METRICS.items():
        if name not in current:
            continue
        _, base_total = recorded(baseline, name)
        total = sum(current[name].values())
        delta = total - base_total
        print(f'{name:<19} {total:>8} {base_total:>9} {delta:>+7}  {len(current[name]):>5}  {metric.label}')
    for name in current:
        rows = sorted(current[name].items(), key=lambda kv: (-kv[1], kv[0]))[:10]
        if not rows:
            continue
        print(f'\ntop {len(rows)} by {name}:')
        for key, n in rows:
            print(f'  {n:>6}  {key}')
    cov = baseline.get('coverage', {})
    if cov:
        dirs = baseline.get('coverage_dirs', {})
        print(
            '\ncoverage baseline: '
            + ', '.join(f'{p} {v:.2f}% ({len(dirs.get(p, {}))} dirs)' for p, v in sorted(cov.items()))
        )
    return 0


def cmd_baseline(init=False, allow_up=None, with_pyright=False):
    baseline = load_baseline()
    if baseline['generated'] and init:
        print('baseline exists; --init refused (delete it first if you really mean to re-seed)')
        return 1
    current = collect(with_pyright)
    up, down = [], 0
    for name, metric in METRICS.items():
        if name not in current:
            continue
        base_entries, base_total = recorded(baseline, name)
        counts = current[name]
        for key in sorted(counts):
            n = counts[key]
            was = base_entries.get(key)
            if was is None:
                if metric.zero_for_new and n > 0 and not init:
                    up.append(f'{key}: {name} 0→{n} (new {metric.key})')
            elif n > was:
                up.append(f'{key}: {name} {was}→{n}')
            elif n < was:
                down += 1
        if metric.gate_growth and sum(counts.values()) > base_total and not init:
            up.append(f'TOTAL: {name} {base_total}→{sum(counts.values())}')
        baseline['metrics'][name] = as_entry(counts)
    if up and not (init or allow_up):
        print(f'REFUSED: {len(up)} counter(s) would be re-recorded UP; this baseline only ratchets down:')
        for line in up[:20]:
            print('  ' + line)
        print('  pass --allow-up "<reason>" to record them anyway, and justify it in the commit message')
        return 1
    if up and allow_up:
        print(f'RE-RECORDED UP: {len(up)} counter(s) grew — reason: {allow_up}')
        for line in up[:20]:
            print('  ' + line)
        baseline['allow_up'].append(
            {'when': datetime.now(UTC).isoformat(timespec='seconds'), 'reason': allow_up, 'counters': up[:50]}
        )
    baseline['generated'] = datetime.now(UTC).isoformat(timespec='seconds')
    baseline['long_function_lines'] = LONG_FUNCTION_LINES
    save_baseline(baseline)
    totals = {n: baseline['metrics'][n]['total'] for n in baseline['metrics']}
    print(f'baseline written to {os.path.relpath(BASELINE_PATH, ROOT)}: {down} counter(s) ratcheted down')
    print('  ' + ', '.join(f'{n} {v}' for n, v in totals.items()))
    return 0


def cmd_direction(against='origin/main'):
    """Refuse a baseline whose recorded totals are HIGHER than `against`'s.

    `baseline --allow-up` is deliberately possible, but nothing noticed afterwards: commit
    51c8b16 raised broad_except 3887→3968 and every gate stayed green, because `check` only
    compares the tree with the baseline that ships beside it. This compares the two baseline
    FILES, so a push that loosens the ratchet has to say why in ZYG_RATCHET_UP_OK.
    """
    rel = os.path.relpath(BASELINE_PATH, ROOT)
    if sh(['git', 'rev-parse', '--verify', '-q', against]).returncode != 0:
        print(f'direction: {against} is not reachable here — skipped (CI fetches it)')
        return 0
    shown = sh(['git', 'show', f'{against}:{rel}'])
    if shown.returncode != 0:
        print(f'direction: {against} carries no {rel} — skipped')
        return 0
    try:
        theirs = json.loads(shown.stdout)
    except ValueError as exc:
        print(f'direction: {against}:{rel} is not readable JSON: {exc}')
        return 1
    ours = load_baseline()
    raised = []
    for name in sorted(ours['metrics']):
        was = theirs.get('metrics', {}).get(name, {}).get('total')
        now = ours['metrics'][name].get('total', 0)
        if was is not None and now > was:
            raised.append(f'{name}: {was}→{now} (+{now - was})')
    reason = os.environ.get('ZYG_RATCHET_UP_OK')
    if raised and not reason:
        print(f'direction: {len(raised)} baseline total(s) are HIGHER than {against}:')
        for line in raised:
            print('  ' + line)
        print('  a baseline only ratchets down; to raise one deliberately, push with')
        print('  ZYG_RATCHET_UP_OK="<reason>" set and the same reason in the commit message')
        return 1
    if raised:
        print(f'note: {len(raised)} baseline total(s) raised deliberately — reason: {reason}')
        for line in raised:
            print('  ' + line)
        return 0
    print(f'direction: no baseline total rose against {against} ({len(ours["metrics"])} metrics compared)')
    return 0


def opt(argv, flag):
    return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None


def main(argv):
    cmd = argv[0] if argv else 'check'
    with_pyright = '--with-pyright' in argv
    if cmd == '--selftest':
        from ratchet_selftest import selftest

        return selftest()
    if cmd == 'check':
        return cmd_check(with_pyright)
    if cmd == 'report':
        return cmd_report(with_pyright)
    if cmd == 'baseline':
        return cmd_baseline(init='--init' in argv, allow_up=opt(argv, '--allow-up'), with_pyright=with_pyright)
    if cmd == 'direction':
        return cmd_direction(against=opt(argv, '--against') or 'origin/main')
    if cmd == 'coverage':
        if len(argv) < 2:
            print('usage: ratchet.py coverage <coverage.xml> --package <name> [--baseline] [--since REF]')
            return 2
        since = opt(argv, '--since') or 'origin/main'
        from ratchet_coverage import cmd_coverage

        return cmd_coverage(argv[1], opt(argv, '--package'), record='--baseline' in argv, since=since)
    print(__doc__.strip())
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
