# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The CLI and the severity-table renderer.

Moved verbatim out of the old single-file gates.py (lines 8727-8763, 9957-10068).
"""

import argparse
from zyg_workflows.geom import mesh_skeletons as MS

from zyg_workflows.geom.anthro.gates.subject import Subject, _predictability_split
from zyg_workflows.geom.anthro.gates.severity import severity_table
from zyg_workflows.geom.anthro.gates.engine import _atomic_json, run_gates
from zyg_workflows.geom.anthro.gates.selftest_runtime import (
    _selftest_paths,
    _selftest_rollup,
    _selftest_severity,
    _selftest_shells,
)
from zyg_workflows.geom.anthro.gates.selftest_provenance import _selftest_refusal


# ---------------------------------------------------------------------------------
# CLI / self-test
# ---------------------------------------------------------------------------------
_MARK = {'blocking': 'BLOCK', 'warning': 'warn ', 'not_run': '  -  ', 'ok': ' ok  '}


def render_severity_table(gates=None):
    """The severity table as text: which gates block, and the measured rate that entitles
    each of them to. This is the artefact that makes rule 6 auditable without reading the
    JSON."""
    st = severity_table(gates)
    out = [
        'SEVERITY CALIBRATION — every severity below is measured, not declared',
        '  policy: %s' % st['policy'],
        '  reference: %s' % st['reference'],
    ]
    for sex, ib in sorted(st['independent_bands_admission'].items()):
        out.append("  the pack's own warning, %s: %s = %.4f" % (sex, ib['method'], ib['admitted_fraction']))
    out.append('')
    out.append('  %-32s %-8s %-9s %10s  %-16s %s' % ('gate', 'declared', 'effective', 'rejects', 'basis', 'kind'))
    for r in st['rows']:
        out.append(
            '  %-32s %-8s %-9s %10s  %-16s %s'
            % (
                r['id'],
                r['declared'],
                r['effective'] + ('*' if r['downgraded'] else ''),
                '-' if r['rejection_rate'] is None else '%.3f%%' % (100.0 * r['rejection_rate']),
                r['basis'],
                r['kind'],
            )
        )
    out.append('')
    out.append('  * = severity was TAKEN AWAY by measurement: %s' % (', '.join(st['downgraded']) or 'none'))
    for gid in st['downgraded']:
        out.append('      %s: %s' % (gid, st['gates'][gid]['reason']))
    return '\n'.join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Four-tier anthropometric gate engine.')
    ap.add_argument('names', nargs='*', help='registered characters (default: all)')
    ap.add_argument('--tiers', default=None, help='e.g. 1,2')
    ap.add_argument('--json', help='write the full report here')
    ap.add_argument('--verbose', action='store_true', help='print every sub-check')
    ap.add_argument(
        '--severity-table', action='store_true', help='print the measured severity table for the whole registry'
    )
    a = ap.parse_args(argv)

    print('threshold-provenance refusal self-test:')
    for line in _selftest_refusal():
        print('  ' + line)
    print('severity-calibration self-test:')
    for line in _selftest_severity():
        print('  ' + line)
    print('roll-up self-test (a skipped check must never read as a pass):')
    for line in _selftest_rollup():
        print('  ' + line)
    if not a.names:
        print('shell-containment self-test:')
        for line in _selftest_shells():
            print('  ' + line)
        print('engine self-test (paths our four assets never take):')
        for line in _selftest_paths():
            print('  ' + line)
    tight, wide = _predictability_split()
    print(
        'predictability split read from the pack: %d tight, %d wide (tight: %s)'
        % (len(tight), len(wide), ', '.join(tight[:6]) + ' ...')
    )
    if a.severity_table:
        print()
        print(render_severity_table())

    reg = MS._registry()
    names = a.names or sorted(list(reg.get('originals', {})) + list(reg.get('derived', {})))
    tiers = None if not a.tiers else [int(x) for x in a.tiers.split(',')]

    reports = {}
    for name in names:
        sub = Subject.from_registry(name)
        rep = run_gates(sub, tiers=tiers)
        reports[name] = rep
        m = rep['subject']
        print('\n' + '=' * 100)
        print(
            '%s   sex=%s  age=%.1fy  stature=%.1f mm  ancestry=%s  (%.1fs)'
            % (name, m['sex'], m['age_years'], m['stature_mm'], m['ancestry'] or 'NOT DECLARED', rep['elapsed_s'])
        )
        print(
            'VERDICT: %s   blocking=%d warnings=%d not-run=%d ok=%d'
            % (
                rep['verdict'],
                rep['counts']['blocking'],
                rep['counts']['warning'],
                rep['counts']['not_run'],
                rep['counts']['ok'],
            )
        )
        if rep['blocking_gates_not_run'] or rep['blocking_gates_missing_input']:
            print(
                '         NOT VERIFIED: %d blocking gate(s) did not run (%s); %d had no '
                'declared input (%s)'
                % (
                    len(rep['blocking_gates_not_run']),
                    ', '.join(rep['blocking_gates_not_run']) or '-',
                    len(rep['blocking_gates_missing_input']),
                    ', '.join(rep['blocking_gates_missing_input']) or '-',
                )
            )
        for r in rep['gates']:
            if r['classification'] == 'ok' and not a.verbose:
                continue
            print(
                '  [%s] t%d %-30s %-16s %s'
                % (_MARK[r['classification']], r['tier'], r['id'], r['status'], r['explain'][:160])
            )
            if r.get('severity_calibrated'):
                print(
                    '        severity %s -> %s: %s'
                    % (r['severity_declared'], r['severity'], r['severity_reason'][:150])
                )
            if a.verbose:
                for c in (r.get('detail') or {}).get('checks', []):
                    print('        - %-34s %-14s %s' % (c.get('id'), c.get('status'), str(c.get('explain'))[:120]))
    if a.json:
        _atomic_json(a.json, reports)
        print('\nwrote %s' % a.json)

    print('\n' + '=' * 100)
    print(
        '%-12s %-20s %-9s %-9s %-9s %-16s %s'
        % ('character', 'verdict', 'blocking', 'warnings', 'not-run', 'block-verified', 'block-NOT-verified')
    )
    for n in names:
        r = reports[n]
        print(
            '%-12s %-20s %-9d %-9d %-9d %-16d %d'
            % (
                n,
                r['verdict'],
                r['counts']['blocking'],
                r['counts']['warning'],
                r['counts']['not_run'],
                len(r['blocking_verified']),
                len(r['blocking_gates_not_run']) + len(r['blocking_gates_missing_input']),
            )
        )
    return 0
