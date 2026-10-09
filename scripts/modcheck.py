#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""modcheck — the modularization gate (rules A and C; rule B lives on the session-tree board).

Rule A (hard cap + ratchet): a tracked Python file that is not in the baseline may never
exceed LIMIT lines. Files already over the limit when the gate was introduced are listed
in scripts/modcheck_baseline.json with their line count at that moment; a listed file may
shrink but never grow (the ratchet). `modcheck.py baseline` re-records shrunk files so the
ratchet only ever tightens.

Rule C (branding): a file in the brand band — above BRAND_AT (80% of LIMIT) — or any
baseline file is BRANDED. A branded file may only *receive* connector code: compared with
--against (default HEAD), every added top-level statement must be an import, a re-export
alias (`name = other` / `name = module.attr`), an `__all__` assignment, a docstring, or a
`if TYPE_CHECKING:` import block, and the file's growth must be covered by those added
connector lines. Shrinking is always allowed. Logic goes in a new module; the branded file
only gets the lines that connect it there.

Exemptions: paths under "exempt" in the baseline (with a reason), and files carrying a
`# zyg: no-split` marker in their first 60 lines (provenance files where the layout IS the
spec — e.g. the Pufferball look files — must never be tidied by a line-count rule).

Commands:
  modcheck.py check [--against REF]   gate mode: exit 0 clean, 1 violations (the gate runs this)
  modcheck.py report                  rank offenders and brand-band files (feeds `st suggest` trees)
  modcheck.py baseline [--init]       write/tighten the baseline (--init: first creation only)

This tool NEVER edits source files. It refuses commits; it does not rewrite code.
The split work itself is planned per file and executed as session-tree tasks (rule B).
"""

import ast
import json
import os
import subprocess
import sys
from datetime import UTC, datetime

LIMIT = int(os.environ.get('ZYG_MODCHECK_LIMIT', '1000'))  # rule A: hard cap, lines per .py
BRAND_AT = int(os.environ.get('ZYG_MODCHECK_BRAND_AT', str(int(LIMIT * 0.8))))  # rule C: brand threshold
MARKER = '# zyg: no-split'
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BASELINE_PATH = os.path.join(HERE, 'modcheck_baseline.json')


def sh(args, **kw):
    kw.setdefault('check', False)
    return subprocess.run(  # noqa: PLW1510 — check comes through kw, default False
        args, cwd=ROOT, capture_output=True, text=True, **kw
    )


def tracked_py():
    out = sh(['git', 'ls-files', '*.py']).stdout
    return [p for p in out.splitlines() if p and not p.startswith('packages/workflows/docs/')]


def line_count(text):
    return text.count('\n') + (1 if text and not text.endswith('\n') else 0)


def read_file(path):
    with open(os.path.join(ROOT, path), encoding='utf-8', errors='replace') as f:
        return f.read()


def read_ref(path, ref):
    r = sh(['git', 'show', f'{ref}:{path}'])
    return r.stdout if r.returncode == 0 else None  # None: file is new at this ref


def load_baseline():
    if not os.path.exists(BASELINE_PATH):
        return {'generated': None, 'limit': LIMIT, 'files': {}, 'exempt': {}}
    with open(BASELINE_PATH, encoding='utf-8') as f:
        return json.load(f)


def is_exempt(path, text, baseline):
    if path in baseline.get('exempt', {}):
        return baseline['exempt'][path]
    head = '\n'.join(text.splitlines()[:60])
    if MARKER in head:
        return 'in-file marker ' + MARKER
    return None


# ── rule C: connector classification ─────────────────────────────────────────


def _is_connector(node):
    """A top-level statement a branded file may still receive."""
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return True
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
        return True  # docstring / explanatory string
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(t, ast.Name) and t.id == '__all__' for t in targets):
            return True  # re-export list
        v = node.value
        if isinstance(v, (ast.Name, ast.Attribute)):
            return True  # alias: name = other / name = module.attr
        if isinstance(v, ast.List) and all(isinstance(e, ast.Constant) for e in v.elts):
            return True  # __all__-style literal list
    if isinstance(node, ast.If):  # `if TYPE_CHECKING:` import block
        t = node.test
        name = t.id if isinstance(t, ast.Name) else (t.attr if isinstance(t, ast.Attribute) else '')
        if name == 'TYPE_CHECKING' and all(isinstance(n, (ast.Import, ast.ImportFrom)) for n in node.body):
            return True
    return False


def _top_level_fingerprints(tree):
    return {ast.dump(node, annotate_fields=False) for node in tree.body}


def brand_check(path, new_text, old_text):
    """Return a violation string, or None. Called only for branded files that changed."""
    new_n, old_n = line_count(new_text), line_count(old_text)
    if new_n <= old_n:
        return None  # shrinking or equal: always fine
    try:
        new_tree, old_tree = ast.parse(new_text), ast.parse(old_text)
    except SyntaxError as e:
        return f'cannot parse for brand check: {e}'
    old_fp = _top_level_fingerprints(old_tree)
    added = [n for n in new_tree.body if ast.dump(n, annotate_fields=False) not in old_fp]
    bad = [n for n in added if not _is_connector(n)]
    if bad:
        kinds = ', '.join(f'{type(n).__name__} at line {n.lineno}' for n in bad[:5])
        return (
            f'BRANDED (> {BRAND_AT} lines): grew {old_n} -> {new_n} with non-connector '
            f'top-level statements added ({kinds}). A branded file only receives imports, '
            f're-export aliases and docstrings; the logic goes in a new module'
        )
    growth = new_n - old_n
    connector_lines = sum((getattr(n, 'end_lineno', n.lineno) - n.lineno + 1) for n in added)
    if growth > connector_lines:
        return (
            f'BRANDED (> {BRAND_AT} lines): grew by {growth} lines but added connector '
            f'statements cover only {connector_lines} — the rest grew inside existing code. '
            f'Move the logic to a module and connect it'
        )
    return None


# ── commands ─────────────────────────────────────────────────────────────────


def cmd_check(against='HEAD'):
    baseline = load_baseline()
    base_files = baseline.get('files', {})
    violations, branded_checked = [], 0
    for path in tracked_py():
        text = read_file(path) if os.path.exists(os.path.join(ROOT, path)) else None
        if text is None:
            continue
        reason = is_exempt(path, text, baseline)
        if reason:
            continue
        n = line_count(text)
        if n > LIMIT:  # rule A
            if path not in base_files:
                violations.append(
                    f'{path}: {n} lines > cap {LIMIT} and not in the baseline — '
                    f'split before committing (new scripts never exceed the cap)'
                )
                continue
            if n > base_files[path]:
                # Rule C applies to baseline files too: growth is tolerated only when the
                # diff vs --against is connector-only. Committed drift is re-recorded, loudly,
                # by a deliberate `modcheck.py baseline` run (visible in the baseline's git diff).
                old = read_ref(path, against)
                escape = old is not None and old != text and brand_check(path, text, old) is None
                if not escape:
                    violations.append(
                        f'{path}: ratchet broken — baseline {base_files[path]} lines, now {n}. '
                        f'A baseline file only shrinks, or grows by connector lines in the '
                        f'current diff; committed drift needs a deliberate `modcheck.py baseline` '
                        f're-record'
                    )
                    continue
        if n > BRAND_AT:  # rule C
            old = read_ref(path, against)
            if old is not None and old != text:
                branded_checked += 1
                v = brand_check(path, text, old)
                if v:
                    violations.append(f'{path}: {v}')
    if violations:
        print(f'modcheck: {len(violations)} violation(s) (cap {LIMIT}, brand at {BRAND_AT}, vs {against}):')
        for v in violations:
            print('  ' + v)
        return 1
    print(
        f'modcheck: clean ({len(tracked_py())} tracked .py, {len(base_files)} baseline, '
        f'{branded_checked} branded diffs checked vs {against}, cap {LIMIT})'
    )
    return 0


def cmd_report():
    baseline = load_baseline()
    rows, medals, exempt_n = [], {'gold': 0, 'silver': 0, 'bronze': 0, 'over': 0}, 0
    for path in tracked_py():
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            continue
        text = read_file(path)
        n = line_count(text)
        reason = is_exempt(path, text, baseline)
        if reason:
            exempt_n += 1
        else:
            medals['gold' if n < 300 else 'silver' if n < 600 else 'bronze' if n <= LIMIT else 'over'] += 1
        if n <= BRAND_AT:
            continue
        state = ('EXEMPT: ' + reason) if reason else ('OVER CAP' if n > LIMIT else 'BRANDED')
        rows.append((n, path, state))
    rows.sort(reverse=True)
    total = sum(medals.values()) or 1
    pct = lambda k: f'{medals[k]} ({medals[k] * 100 // total}%)'
    print(
        f'medals over {total} scored .py files (+{exempt_n} exempt): '
        f'gold <300: {pct("gold")} · silver <600: {pct("silver")} · '
        f'bronze <=cap: {pct("bronze")} · OVER CAP: {pct("over")}'
    )
    print('split aim: new modules land at 300-600 where the seams allow; 800 (brand) is the ceiling.\n')
    print(f'{"lines":>7}  {"state":<12}  path      (cap {LIMIT}, brand at {BRAND_AT})')
    for n, path, state in rows:
        print(f'{n:>7}  {state:<12}  {path}')
    over = [r for r in rows if r[2] == 'OVER CAP']
    print(
        f'\n{len(over)} file(s) over cap -> candidates for a suggested modularization tree '
        f'(st suggest, Modularization tab).'
    )
    return 0


def cmd_baseline(init=False):
    baseline = load_baseline()
    if baseline['generated'] and init:
        print('baseline exists; --init refused (delete it first if you really mean to re-seed)')
        return 1
    old = baseline.get('files', {})
    files = {}
    for path in tracked_py():
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            continue
        text = read_file(path)
        if is_exempt(path, text, baseline):
            continue
        n = line_count(text)
        if n > LIMIT:
            if not init and path not in old:
                print(
                    f'REFUSED: {path} ({n} lines) is over the cap but not in the baseline — '
                    f'a new over-cap file is a rule-A violation, not a baseline candidate'
                )
                return 1
            if n > old.get(path, n):
                print(
                    f'RE-RECORDED UP: {path} {old[path]} -> {n} lines — justify it in the commit '
                    f'that carries this baseline change'
                )
            files[path] = n
    baseline.update(
        generated=datetime.now(UTC).isoformat(timespec='seconds'), limit=LIMIT, files=dict(sorted(files.items()))
    )
    baseline.setdefault('exempt', {})
    with open(BASELINE_PATH, 'w', encoding='utf-8') as f:
        json.dump(baseline, f, indent=1)
        f.write('\n')
    gone = sorted(set(old) - set(files))
    print(
        f'baseline written: {len(files)} file(s) over cap'
        + (f'; {len(gone)} left the baseline (split or deleted): ' + ', '.join(gone[:8]) if gone else '')
    )
    return 0


def main(argv):
    cmd = argv[0] if argv else 'check'
    if cmd == 'check':
        against = argv[argv.index('--against') + 1] if '--against' in argv else 'HEAD'
        return cmd_check(against)
    if cmd == 'report':
        return cmd_report()
    if cmd == 'baseline':
        return cmd_baseline(init='--init' in argv)
    print(__doc__.strip())
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
