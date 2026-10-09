# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The argparse CLI.

Moved verbatim out of the old single-file mesh_skeletons.py (lines 3302-3509).
"""

import argparse

from zyg_workflows.geom.mesh_skeletons.artifacts import _registry

from zyg_workflows.geom.mesh_skeletons.originals import (
    build_originals,
    gate_registered,
    refresh_previews,
    verify_originals,
)

from zyg_workflows.geom.mesh_skeletons.derive import derive, reissue


def _parse_kv(s, cast=float):
    out = {}
    for part in (s or '').split(','):
        if '=' in part:
            k, _, val = part.partition('=')
            out[k.strip()] = cast(val)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build-originals')
    b.add_argument('--force', action='store_true')
    dv = sub.add_parser('derive')
    dv.add_argument('char_id')
    dv.add_argument('--base', default='male', choices=('male', 'female'))
    dv.add_argument('--phenotype', default='')
    dv.add_argument(
        '--bone-scale',
        default='',
        help='per-bone scale, k=v,... The keys are anny RIG bone names '
        'matched as case-insensitive substrings — e.g. '
        'upperleg=1.1,head=0.95 (the leg bones are upperleg01/'
        'upperleg02/lowerleg01/lowerleg02 + foot, per side .L/.R; there '
        'is NO bone called "thigh"). A key that matches no bone is an '
        'error, so the issued body is always the one asked for. Full '
        'roster: params.json -> adjustable.bone_scale_names',
    )
    dv.add_argument('--local', default='')
    dv.add_argument('--note', default='')
    dv.add_argument(
        '--no-inherit-locals',
        action='store_true',
        help="do NOT inherit the template original's local morphs NOR its anatomy layer",
    )
    dv.add_argument(
        '--anatomy', default='', help='anatomy layer k=v (e.g. abs_definition=1.7); merged over the inherited layer'
    )
    dv.add_argument(
        '--ancestry',
        default=None,
        help='DECLARED ancestry (a DODRace group the reference pack carries). '
        'Omit if unknown — it is recorded as undeclared, never guessed',
    )
    dv.add_argument(
        '--target-height',
        type=float,
        default=None,
        help='DECLARED build-target stature in metres. Recorded, not solved '
        'for: the gate checks the delivered stature against it',
    )
    dv.add_argument(
        '--stylization-intent',
        default=None,
        help='why the BodyProportions axis is where it is (only meaningful when --phenotype sets proportions)',
    )
    dv.add_argument('--declared-by', default=None)
    ri = sub.add_parser(
        'reissue',
        help='rebuild registered bodies from their own params.json '
        'under the current house layers (e.g. the phalanx '
        'correction), changing no declared input',
    )
    ri.add_argument('names', nargs='*', help='default: every registered body')
    ri.add_argument('--dry-run', action='store_true', help='print the before/after cage hashes and write nothing')
    ri.add_argument(
        '--force',
        action='store_true',
        help='re-issue even when the rebuild reproduces the recorded cage '
        'exactly. This is the REPAIR path for a body whose aux hashes '
        'went stale: an identical cage is proof the recipe still '
        'reproduces the registered geometry, so regenerating and '
        're-recording every artifact is sound rather than a laundering '
        'of unknown bytes.',
    )
    ri.add_argument(
        '--set-anatomy',
        default='',
        help='k=v,... anatomy_layer changes to DECLARE on the named bodies '
        '(e.g. toe_declash=0.005). This edits a declared input, so it '
        'is recorded with its previous value in anatomy_layer_changed.',
    )
    ri.add_argument(
        '--set-target',
        default='',
        help='name=METRES,... the build-target stature to DECLARE on the '
        'named bodies, so t1_build_target_stature has something to '
        'check the delivered stature against instead of reporting '
        'MISSING. It is a declaration: it solves nothing and moves no '
        'vertex, and it is deliberately NOT taken from the delivered '
        'stature, which would make the gate pass by construction. '
        'Recorded with its previous value in height_target_changed. '
        'Use name= (empty) to withdraw a declaration.',
    )
    sub.add_parser('verify')
    sub.add_parser('list')
    sub.add_parser('refresh-previews')
    g = sub.add_parser('gate', help='(re-)run the anthropometric gates on issued characters; never touches a vertex')
    g.add_argument('names', nargs='*')
    a = ap.parse_args(argv)

    if a.cmd == 'build-originals':
        build_originals(force=a.force)
    elif a.cmd == 'refresh-previews':
        return 0 if refresh_previews() else 2
    elif a.cmd == 'derive':
        derive(
            a.char_id,
            a.base,
            _parse_kv(a.phenotype),
            _parse_kv(a.local),
            _parse_kv(a.bone_scale),
            a.note,
            inherit_base_locals=not a.no_inherit_locals,
            anatomy=_parse_kv(a.anatomy),
            ancestry=a.ancestry,
            target_height_m=a.target_height,
            stylization_intent=a.stylization_intent,
            declared_by=a.declared_by,
        )
    elif a.cmd == 'gate':
        res = gate_registered(a.names or None)
        # 'blocking' is split into FAILED and NEVER-RAN: a blocking gate with no verdict
        # used to be in neither column and the table read '0 blocking' for a body whose
        # stature had been checked against nothing.
        print('%-14s %-20s %-8s %-9s %-9s %s' % ('character', 'verdict', 'blk-fail', 'blk-unrun', 'warnings', 'report'))
        for n in sorted(res):
            s = res[n]
            print(
                '%-14s %-20s %-8d %-9d %-9d %s'
                % (
                    n,
                    s.get('verdict') or s.get('status'),
                    len(s.get('blocking_failed') or []),
                    len(s.get('blocking_unrun') or []),
                    len(s.get('warnings') or []),
                    s.get('report') or s.get('error', ''),
                )
            )
        for n in sorted(res):
            for u in res[n].get('blocking_unrun') or []:
                print('  %s: BLOCKING GATE NEVER RAN — %s [%s]' % (n, u.get('id'), u.get('status')))
        # exit 3 only when the ENGINE failed. A FAIL verdict is a measurement result and
        # is reported, not turned into a build error by this command.
        return 3 if any(r.get('status') not in ('ok', 'disabled') for r in res.values()) or not res else 0
    elif a.cmd == 'reissue':
        sa = _parse_kv(a.set_anatomy) if a.set_anatomy else None
        if sa and not a.names:
            raise SystemExit(
                '--set-anatomy changes a DECLARED input, so it must name the '
                'bodies it applies to. Refusing to edit every registered '
                "body's declaration at once."
            )
        st = None
        if a.set_target:
            st = {}
            for part in a.set_target.split(','):
                if '=' not in part:
                    continue
                k, _, val = part.partition('=')
                val = val.strip()
                st[k.strip()] = None if val == '' else float(val)
            if st and not a.names:
                raise SystemExit('--set-target DECLARES an input, so it must name the bodies it applies to.')
            stray = sorted(set(st) - set(a.names or []))
            if stray:
                # Silently declaring a target on a body the command did not name is how
                # a declaration lands on the wrong character.
                raise SystemExit(
                    '--set-target names %s, which the command does not '
                    're-issue. Name every body it applies to.' % ', '.join(stray)
                )
        reissue(a.names or None, dry_run=a.dry_run, set_anatomy=sa, force=a.force, set_target=st)
        return 0
    elif a.cmd == 'verify':
        bad = verify_originals()
        print('originals: %s' % ('OK — byte-identical to issue' if not bad else bad))
        return 2 if bad else 0
    elif a.cmd == 'list':
        reg = _registry()

        def _verdict(r):
            an = r.get('anthro') or {}
            v = an.get('verdict') or an.get('status') or 'not-gated'
            n = len(an.get('blocking_unrun') or [])
            # a verdict over gates that never ran is not the verdict it looks like
            return '%s+%dUNRUN' % (v, n) if n else v

        for sex, r in reg.get('originals', {}).items():
            print(
                'ORIGINAL %-7s %s sha=%s… %s anthro=%s'
                % (
                    sex,
                    r['params']['measured'],
                    r['sha256'][:12],
                    'IMMUTABLE' if r.get('immutable') else '',
                    _verdict(r),
                )
            )
        for cid, r in reg.get('derived', {}).items():
            p = r['params']
            print(
                'derived  %-14s base=%-6s %s anthro=%-20s note=%s'
                % (cid, p['base'], p['measured'], _verdict(r), p.get('note', '')[:40])
            )
    return 0
