# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ratchet coverage gate — pytest-cov line rates vs the baseline (see ratchet.py).

Split out of ratchet.py on 2026-10-13 (modcheck rule C: the gate core stays under the brand line).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from ratchet import COVERAGE_SLACK_PP, load_baseline, save_baseline, sh


def _coverage_rates(xml_path):
    """(package rate, {top-level dir: rate}, {file: hits}) from a pytest-cov XML."""
    root = ET.parse(xml_path).getroot()
    rate = float(root.get('line-rate', '0')) * 100.0
    valid, hit, files = {}, {}, {}
    for cls in root.iter('class'):
        fn = cls.get('filename') or ''
        parts = fn.split('/')
        try:
            i = next(k for k, p in enumerate(parts) if p == 'src') + 1
        except StopIteration:
            i = 0
        top = parts[i + 1] if len(parts) > i + 2 else '(root)'
        n = h = 0
        for ln in cls.iter('line'):
            n += 1
            h += 1 if int(ln.get('hits', '0')) > 0 else 0
        valid[top] = valid.get(top, 0) + n
        hit[top] = hit.get(top, 0) + h
        files[fn] = files.get(fn, 0) + h
    dirs = {d: round(100.0 * hit[d] / valid[d], 2) for d in valid if valid[d]}
    return rate, dirs, files


def _added_since(ref, package):
    """Repo-relative .py files under the package's src added since *ref*; None when ref is unknown."""
    if sh(['git', 'rev-parse', '--verify', '-q', ref]).returncode:
        return None
    out = sh(['git', 'diff', '--name-only', '--diff-filter=A', ref, '--', f'packages/{package}/src']).stdout
    return [p for p in out.splitlines() if p.endswith('.py') and not p.endswith(('/__main__.py', '/entry.py'))]


def cmd_coverage(xml_path, package, record=False, since='origin/main'):
    if not package:
        print('coverage: --package <name> is required')
        return 2
    try:
        rate, dirs, files = _coverage_rates(xml_path)
    except (OSError, ET.ParseError, TypeError, ValueError) as exc:
        print(f'coverage: cannot read a line-rate from {xml_path}: {exc}')
        return 2
    baseline = load_baseline()
    baseline.setdefault('coverage_dirs', {})
    was = baseline['coverage'].get(package)
    was_dirs = baseline['coverage_dirs'].get(package, {})
    if record:
        baseline['coverage'][package] = round(rate, 2)
        baseline['coverage_dirs'][package] = dict(sorted(dirs.items()))
        baseline['generated'] = datetime.now(UTC).isoformat(timespec='seconds')
        save_baseline(baseline)
        print(
            f'coverage baseline: {package} {"none" if was is None else f"{was:.2f}%"} → {rate:.2f}%  ({len(dirs)} dirs)'
        )
        return 0
    problems = []
    if was is None:
        print(f'coverage: {package} has no baseline yet ({rate:.2f}% now) — record it with --baseline')
    elif rate < was - COVERAGE_SLACK_PP:
        problems.append(f'{package} fell {was:.2f}% → {rate:.2f}% (more than {COVERAGE_SLACK_PP} pp below baseline)')
    for d, w in sorted(was_dirs.items()):
        cur = dirs.get(d)
        if cur is not None and cur < w - COVERAGE_SLACK_PP:
            problems.append(
                f'{package}/{d} fell {w:.2f}% → {cur:.2f}% (more than {COVERAGE_SLACK_PP} pp below baseline)'
            )
    added = _added_since(since, package) if since else None
    if added is None and since:
        print(f'coverage: {since} is unknown here — new-module rule not checked')
    for path in added or []:
        # coverage.xml filenames are relative to the package dir (src/...), ours to the repo
        rel = path.split('/', 2)[2] if path.count('/') >= 2 else path
        hits = next((h for fn, h in files.items() if fn == rel or fn.endswith('/' + rel)), None)
        if hits is None:
            problems.append(f'{path}: added since {since} but absent from {xml_path} — not measured at all')
        elif hits == 0:
            problems.append(f'{path}: added since {since} and no test executes a single line of it')
    if problems:
        print(f'coverage: {len(problems)} problem(s):')
        for p in problems:
            print('  ' + p)
        print('  add a test (the import smoke counts), or re-record deliberately with --baseline')
        return 1
    print(
        f'coverage: {package} {rate:.2f}% vs baseline {"none" if was is None else f"{was:.2f}%"}'
        f' — within {COVERAGE_SLACK_PP} pp or better; {len(was_dirs)} dirs held; {len(added or [])} new modules executed'
    )
    return 0
