# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""CLI.

Moved verbatim out of the old single-file pose_limits.py (lines 5211-5509).
"""

from zyg_workflows.geom.pose_limits.base import (
    ERROR,
    FAIL,
    PASS,
    REPORT,
    SKIP,
    UNMEASURABLE,
    UNRESOLVED,
    WARN,
    json,
    np,
    sys,
)
from zyg_workflows.geom.pose_limits.rig import rig_report
from zyg_workflows.geom.pose_limits.characters import characters
from zyg_workflows.geom.pose_limits.pose_layer import POSE_LAYER_CONTRACT, POSE_LAYER_SCHEMA, pose_layer, run_all
from zyg_workflows.geom.pose_limits.falsification import demo_broken


# ---------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------
def _fmt_status(s):
    return {
        PASS: 'PASS',
        FAIL: 'FAIL',
        WARN: 'warn',
        REPORT: 'report',
        UNRESOLVED: 'UNRESOLVED',
        UNMEASURABLE: 'UNMEASURABLE',
        SKIP: 'skip',
        ERROR: 'ERROR',
    }.get(s, s)


def render_text(doc):
    L = []
    rig = doc['rig']
    L.append('=' * 78)
    L.append('RIG — %d bones' % rig['n_bones'])
    L.append('=' * 78)
    L.append('  ' + rig['verdict'])
    for fam, have in sorted(rig['families_present'].items()):
        miss = rig['families_incomplete'].get(fam)
        L.append('  %-16s %d present%s' % (fam, len(have), ('  MISSING %s' % miss) if miss else ''))
    for key, rec in sorted(rig['expected_absent'].items()):
        L.append(
            '  %-16s %s   (disables: %s)'
            % (key, 'ABSENT' if rec['absent'] else 'present: %s' % rec['bones'], rec['disables'])
        )
    cp = doc['canon_policy']
    L.append('  CANON may block: %s — %s' % (cp['may_block'], cp['why']))
    nf = doc.get('numerical_floor') or {}
    L.append(
        '  numerical floor: reproducibility %.3e deg, orthonormality %.3e; an '
        'unprojected trace formula would have read %.3e deg for a bone that did not '
        'move'
        % (
            nf.get('reproducibility_deg', 0),
            nf.get('orthonormality_max_abs', 0),
            nf.get('unprojected_angle_floor_deg', 0),
        )
    )
    L.append('  flags: %s' % doc.get('env_flags'))

    for ch in doc['characters']:
        L.append('')
        L.append('=' * 78)
        L.append('%s   stature %.4f m' % (ch['character'], ch['stature_m']))
        L.append('=' * 78)
        rg = ch['rest_geometry']
        L.append('  rest elbow %s   knee %s' % (rg['elbow_included_deg'], rg['knee_included_deg']))
        for s in ('l', 'r'):
            w = rg['wrist'][s]
            L.append(
                '  rest wrist %s  extension %+6.2f  ulnar deviation %+6.2f  '
                '(frame: %s)' % (s.upper(), w['extension_deg'], w['ulnar_deviation_deg'], w['frame_kind'])
            )
        for g in ch['gates']:
            L.append('  %-24s %-13s %s' % (g['gate'], _fmt_status(g['status']), g['explain'][:120]))
            d = g.get('detail') or {}
            if g['gate'] == 't5_joint_rom':
                cerv = d.get('cervical')
                if cerv:
                    L.append(
                        '      cervical total ext %+.2f deg, per joint %s'
                        % (
                            cerv['total_extension_deg'],
                            {k: round(v['extension_deg'], 2) for k, v in cerv['per_joint'].items()},
                        )
                    )
            if g['gate'] == 't5_patellar_ligament' and g.get('observed'):
                L.append(
                    '      rest %.2f mm, max drift %.3f%% at %.0f deg; patella skin '
                    '%s / tuberosity skin %s'
                    % (
                        g['observed']['rest_distance_mm'],
                        100 * g['observed']['max_abs_drift'],
                        g['observed']['at_drive_deg'],
                        list(d.get('patella_skin_ownership', {}).items())[:1],
                        list(d.get('tuberosity_skin_ownership', {}).items())[:1],
                    )
                )
            if g['gate'] == 't5_elbow_owner' and g.get('observed'):
                L.append(
                    '      owner per angle %s, median residual ratio %.4f, patch skin '
                    '%s'
                    % (
                        g['observed']['owner_per_angle'],
                        g['observed']['median_ratio_forearm_over_upperarm'],
                        list(d.get('patch_skin_ownership', {}).items())[:2],
                    )
                )
                # The controls print WHETHER OR NOT the row passed. A pass whose control is
                # blind is exactly the row a reader must not skim past (D7).
                L.append(
                    '      synthetic control (comparator can name the humerus): %s'
                    % {k: v['ok'] for k, v in (d.get('negative_control_synthetic') or {}).items()}
                )
                for k, v in sorted((d.get('negative_control_humeral') or {}).items()):
                    L.append(
                        '      humeral control %-15s must be %s, measured %s -> %s'
                        % (
                            k,
                            v['must_be_owned_by'],
                            sorted(set(v['owner_per_angle'].values())),
                            'discriminates' if v['ok'] else 'BLIND: a humeral landmark answers forearm too',
                        )
                    )
                if not d.get('negative_control_humeral'):
                    L.append('      humeral control NOT AVAILABLE: %s' % (d.get('negative_control_unavailable') or {}))
            if g['gate'] == 't5_scapula_static':
                L.append('      %s' % d.get('complement_finding', '')[:200])
            if g['gate'] == 't5_pronation_isolation' and g.get('observed'):
                o = g['observed']
                L.append(
                    '      humerus rotation %.3e deg (floor %.3e); non-decreasing=%s '
                    'max at wrist=%s  rigid-null %s'
                    % (
                        o['max_humerus_rotation_deg'],
                        o['numerical_floor_deg'],
                        o['gradient_non_decreasing'],
                        o['gradient_max_at_wrist'],
                        {k: round(v, 6) for k, v in o['rigid_rotation_null_deg'].items()},
                    )
                )

    if doc.get('pose_layer'):
        L.append('')
        L.append('=' * 78)
        L.append('POSE LAYER — rolled up over EVERY declared subject (%s)' % POSE_LAYER_SCHEMA)
        L.append('=' * 78)
        L.append('  rule: %s' % next(iter(doc['pose_layer'].values()))['rollup_rule'][:200])
        for char, pl in sorted(doc['pose_layer'].items()):
            lib = pl['library']
            L.append(
                '  %-14s library %s'
                % (
                    char,
                    (
                        '%d pose(s), %d FAIL, rate %.4f, complete=%s'
                        % (lib['n_poses'], lib['n_violating'] or 0, lib['violation_rate'], lib['complete'])
                    )
                    if lib['present']
                    else 'ABSENT — %s' % (lib['reason'] or '')[:80],
                )
            )
            for g in pl['gates']:
                L.append(
                    '     %-24s %-13s rest=%-12s library=%-12s'
                    % (
                        g['gate'],
                        _fmt_status(g['status']),
                        _fmt_status(g['rest_only_status'] or '-'),
                        _fmt_status(g['library_only_status'] or 'n/a'),
                    )
                )

    if doc.get('fit_mask_defect'):
        f = doc['fit_mask_defect']
        L.append('')
        L.append('=' * 78)
        L.append('FITTED POSE LIBRARY')
        L.append('=' * 78)
        L.append('  anny_fit bone mask: %s' % f['finding'])
    for char, rep in sorted((doc.get('pose_library') or {}).items()):
        if not rep.get('n_poses'):
            L.append('  %-10s %s' % (char, rep.get('reason')))
            continue
        L.append(
            '  %-10s %d poses  fail %.1f%%  warn %.1f%%  %s   complete=%s'
            % (
                char,
                rep['n_poses'],
                100 * rep['violation_rate'],
                100 * rep['warn_rate'],
                rep['status_counts'],
                rep['complete'],
            )
        )
        integ = rep.get('integrity') or {}
        if integ.get('n_dropped'):
            L.append(
                '       DROPPED %d of %d matched file(s): %s'
                % (integ['n_dropped'], integ['n_files_found'], ', '.join(integ['dropped_paths'][:4]))
            )
        for k, v in sorted(rep['per_check_counts'].items(), key=lambda kv: -(kv[1][FAIL] + kv[1][WARN]))[:8]:
            mag = rep['occiput_share_failures_by_total_rotation'].get(k)
            L.append(
                '       %-34s fail %3d  warn %3d%s'
                % (k, v[FAIL], v[WARN], ('   by total rotation %s' % mag) if mag else '')
            )
        for w in (rep.get('worst_offenders') or {}).get('by_pose', [])[:3]:
            L.append(
                '       worst pose %s/%s  %d fail  worst %s by %s %s'
                % (w['asset'], w['cell'], w['n_fail'], w['worst_check'], w['worst_exceedance'], w['worst_units'])
            )
        pc = rep['pronation_coupling']
        L.append(
            '       pronation coupling: forearm |twist| %s deg, humerus |twist| %s '
            'deg, r=%s'
            % (pc['forearm_twist_deg_abs_mean'], pc['humerus_twist_deg_abs_mean'], pc['pearson_r_forearm_vs_humerus'])
        )
    for char, s in sorted((doc.get('stiffness') or {}).items()):
        if not s:
            continue
        L.append('  t5_pose_stiffness %-10s %-13s %s' % (char, _fmt_status(s['status']), s['explain'][:400]))
        o = s['observed']
        for r in (s.get('detail') or {}).get('scored') or []:
            L.append(
                '       %-24s %-13s %s%s'
                % (
                    r['check'],
                    _fmt_status(r['status']),
                    r['provenance'],
                    '' if r.get('can_block') else ' (cannot block)',
                )
            )
        L.append('       elbows locked at 90/180: %s' % o['elbow_locked_fraction_by_window_deg'])
        L.append('       forearms parallel:       %s' % o['forearms_parallel_fraction_by_window_deg'])
        L.append('       ERECT fraction:          %s (reported, not scored)' % o['erect_fraction_by_trunk_window_deg'])
        L.append('       straight finger chains:  %s' % o['fully_straight_finger_chain_fraction'])
        L.append(
            '       tilt opposition:         %s of %s poses same-sign, fraction %s '
            'against a required %s; sensitivity %s'
            % (
                o['tilt_n_same_sign'],
                o['tilt_n_sign_evaluated'],
                o['tilt_opposition_fraction'],
                o['tilt_opposition_required_fraction'],
                o['tilt_same_sign_by_floor_deg'],
            )
        )
    return '\n'.join(L)


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(x) for x in o]
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else 'run'
    out_json = None
    if '-o' in argv:
        out_json = argv[argv.index('-o') + 1]
    if cmd == 'rig':
        r = rig_report()
        print(json.dumps(_jsonable({k: v for k, v in r.items() if k != 'bone_names'}), indent=1))
        print('\nbones:')
        for i, (n, p) in enumerate(zip(r['bone_names'], r['bone_parents'])):
            print('%3d %-22s parent=%s' % (i, n, r['bone_names'][p] if p >= 0 else '(root)'))
        return 0
    if cmd == 'demo':
        d = demo_broken()
        print(json.dumps(_jsonable(d), indent=1))
        return 0 if d['all_controls_behaved'] else 1
    if cmd == 'contract':
        print(POSE_LAYER_CONTRACT)
        return 0
    if cmd == 'layer':
        # one character, both subjects, the dict a gate registry consumes
        who = next((a for a in argv[1:] if not a.startswith('-')), None)
        c = next((x for x in characters() if x['name'] == who), None)
        if c is None:
            print('usage: pose_limits.py layer <character>   (have: %s)' % ', '.join(x['name'] for x in characters()))
            return 2
        pl = pose_layer(c['name'], c['phenotype'], c['local_changes'])
        print(json.dumps(_jsonable({k: v for k, v in pl.items() if k != 'gate_index'}), indent=1))
        return 1 if any(g['status'] in (FAIL, ERROR) for g in pl['gates']) else 0
    doc = run_all(with_pose_library=('--no-library' not in argv))
    if doc.get('skipped'):
        print(doc['why'])
        return 0
    print(render_text(doc))
    if out_json:
        with open(out_json, 'w') as fh:
            json.dump(_jsonable(doc), fh, indent=1)
        print('\nwrote %s' % out_json)
    # The exit code follows the ROLLED-UP verdicts where they exist. Scoring off the
    # rest-pose records alone is the defect this wave closed; it is not re-introduced here.
    if doc.get('pose_layer'):
        bad = sum(1 for pl in doc['pose_layer'].values() for g in pl['gates'] if g['status'] in (FAIL, ERROR))
    else:
        bad = sum(1 for c in doc['characters'] for g in c['gates'] if g['status'] in (FAIL, ERROR))
    return 1 if bad else 0
