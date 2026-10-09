#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
qc_gate_admin.py — inspect and promote QC gates.

A gate earns authority; it is not granted it because it sounded convincing.
`promote` REFUSES unless the golden suite passes with the new mode already
applied, so a gate cannot reach `block` without first proving, on every
historical run on disk, that it fails the bad ones and spares the good ones.

    python3 scripts/qc_gate_admin.py list
    python3 scripts/qc_gate_admin.py coverage
    python3 scripts/qc_gate_admin.py show region_flow
    python3 scripts/qc_gate_admin.py promote region_churn         # -> warn/block
    python3 scripts/qc_gate_admin.py demote  region_flow          # always allowed
"""

import argparse
import json
import os
import subprocess
import sys

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _CREWS)

from zyg_workflows import qc_contract as qc  # noqa: E402

_NEXT = {qc.SHADOW: qc.WARN, qc.WARN: qc.BLOCK, qc.BLOCK: qc.BLOCK}
_PREV = {qc.BLOCK: qc.WARN, qc.WARN: qc.SHADOW, qc.SHADOW: qc.SHADOW}


def _run_golden():
    """-> (ok, output). Demoting never needs this; promoting always does."""
    try:
        p = subprocess.run(
            [sys.executable, '-m', 'pytest', 'tests/', '-q', '--no-header', '-x', '-m', 'not slow'],
            cwd=_CREWS,
            capture_output=True,
            text=True,
            timeout=600,
        )
        return p.returncode == 0, (p.stdout + p.stderr)[-4000:]
    except Exception as e:
        return False, f'could not run the golden suite: {e}'


def cmd_list(_):
    rows = qc.registry_table()
    w = max(len(r['gate']) for r in rows)
    print(f'{"gate".ljust(w)}  {"mode":7s} {"default":7s} {"cal":>3s}  detects')
    print('-' * (w + 46))
    for r in rows:
        flag = '' if r['mode'] == r['default'] else '  <- overridden'
        print(f'{r["gate"].ljust(w)}  {r["mode"]:7s} {r["default"]:7s} {r["calibrated_on"]:>3d}  {r["detects"]}{flag}')
    cfg = qc.load_config(force=True)
    print(f'\nglobal default={cfg.get("mode")}  enforce={qc.enforcement_enabled()}')
    if not qc.enforcement_enabled():
        print('  !! enforcement is OFF — every block is behaving as a warn')


def cmd_coverage(_):
    gated = qc.gated_classes()
    print('defect class            gates')
    print('-' * 64)
    for cls in sorted(qc.DEFECT_TAXONOMY):
        gs = sorted(c.name for c in qc.GATE_CONTRACTS.values() if cls in c.detects)
        mark = '' if cls in gated else '   <-- NO GATE. your eyes are the only instrument'
        print(f'{cls:22s} {", ".join(gs) or "—"}{mark}')
    print(f'\n{len(gated)}/{len(qc.DEFECT_TAXONOMY)} classes have at least one gate.')


def cmd_show(a):
    for prefix, c in qc.GATE_CONTRACTS.items():
        if c.name == a.gate:
            d = c.as_dict()
            d['prefix'] = prefix
            d['current_mode'] = qc.mode_for(prefix)
            print(json.dumps(d, indent=2, ensure_ascii=False))
            return 0
    print(f'no gate named {a.gate!r}. try: qc_gate_admin.py list')
    return 1


def _set_and_verify(gate, target, require_golden):
    before = qc.load_config(force=True)
    cur = dict(before.get('gates') or {})
    qc.set_mode(gate, target)
    if not require_golden:
        print(f'{gate}: -> {target}')
        return 0
    print(f'{gate}: trying -> {target}; running the golden suite...')
    ok, out = _run_golden()
    if ok:
        print(f'\nGOLDEN PASSED. {gate} is now at {target}.')
        print('Record why in the commit message.')
        return 0
    # roll back
    cfg = dict(qc.load_config(force=True))
    cfg['gates'] = cur
    qc.write_config(cfg)
    print('\nGOLDEN FAILED — promotion REVERTED. The gate stays where it was.\n')
    print(out)
    print(
        '\nThis is the mechanism working: the gate would have changed a verdict '
        'on a historical run. Fix the calibration, or add a labelled case to '
        'tests/golden/labels.json explaining why the new verdict is correct.'
    )
    return 1


def cmd_promote(a):
    cur = qc.mode_for_gate_name(a.gate)
    target = a.to or _NEXT[cur]
    if target == cur:
        print(f'{a.gate} is already at {cur}')
        return 0
    return _set_and_verify(a.gate, target, require_golden=True)


def cmd_demote(a):
    cur = qc.mode_for_gate_name(a.gate)
    target = a.to or _PREV[cur]
    if target == cur:
        print(f'{a.gate} is already at {cur}')
        return 0
    # Demotion never requires proof: making a gate quieter cannot ship a defect
    # it was already catching, and an operator must always be able to stop the
    # bleeding without waiting on a test suite.
    return _set_and_verify(a.gate, target, require_golden=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('list').set_defaults(fn=cmd_list)
    sub.add_parser('coverage').set_defaults(fn=cmd_coverage)
    s = sub.add_parser('show')
    s.add_argument('gate')
    s.set_defaults(fn=cmd_show)
    s = sub.add_parser('promote')
    s.add_argument('gate')
    s.add_argument('--to', choices=qc._LADDER)
    s.set_defaults(fn=cmd_promote)
    s = sub.add_parser('demote')
    s.add_argument('gate')
    s.add_argument('--to', choices=qc._LADDER)
    s.set_defaults(fn=cmd_demote)
    a = ap.parse_args()
    sys.exit(a.fn(a) or 0)


if __name__ == '__main__':
    main()
