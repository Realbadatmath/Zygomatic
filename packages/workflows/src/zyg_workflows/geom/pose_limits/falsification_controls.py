# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""FALSIFICATION — one function per negative control.

Split out of falsification.py (2026-10-09, the no-function-over-300-lines rule): every
numbered control that demo_broken() used to inline lives here as a named function with
explicit parameters, and demo_broken() is the orchestrator that runs them in order and
collects their rows.

Each function returns the control row (a dict) it used to append, a list of rows where
the control always produced several, or None where the original appended nothing. The
row contents, the log-free side effects and the ORDER are unchanged; the orchestrator
keeps the `if row is not None` guards the original expressed as `if len(cand) >= 8:` and
`if tub is not None and mal is not None:`.

Import direction: this module imports the pose_limits siblings it needs and never
falsification.py, so falsification.py imports it at module level without a cycle.
"""

import shutil
import tempfile

from zyg_workflows.geom.pose_limits.base import (
    FAIL,
    MS,
    PASS,
    REPORT,
    ROLLUP_RANK,
    UNMEASURABLE,
    WARN,
    json,
    np,
    os,
)
from zyg_workflows.geom.pose_limits.printed import (
    CERVICAL_RIG_JOINTS,
    ELBOW_HUMERAL_CONTROL_PATCHES,
    PATELLAR_LIGAMENT_MAX_DRIFT,
    TRANSVERSE_TILT_STDEV_MIN_DEG,
)
from zyg_workflows.geom.pose_limits.rig import (
    bone_index,
    bone_roster,
    local_axis,
    pose_from_local,
    rig_state,
    unit,
)
from zyg_workflows.geom.pose_limits.skeleton import skeleton_from_blazepose, skeleton_from_rig
from zyg_workflows.geom.pose_limits.rom import _hand_frame, cervical_angles, t5_joint_rom, wrist_angles
from zyg_workflows.geom.pose_limits.stiffness import t5_pose_stiffness
from zyg_workflows.geom.pose_limits.pronation import pronation_coupling_in_pose
from zyg_workflows.geom.pose_limits.joint_gates import _region_group, t5_elbow_owner
from zyg_workflows.geom.pose_limits.characters import (
    POSE_LIBRARY_CHARACTERS,
    characters,
    pose_library_report,
    scan_pose_library,
)
from zyg_workflows.geom.pose_limits.pose_layer import pose_layer


def rom_overdrive_controls(ph, local_changes, rest, af):
    """Controls 1 and 2: a wrist and the whole cervical chain driven past their limits.

    `ph`/`local_changes` are the phenotype under test, `rest` its rest-pose rig_state and
    `af` the anatomical frame of that rest state. Returns [wrist_row, cervical_row]: the
    wrist row first, exactly as demo_broken() appended them.
    """
    rows = []
    # 1. wrist driven far past the forced limit. The drive SIGN is measured, not reasoned:
    #    both senses are tried at a small angle and the one that produces extension wins.
    sk0 = skeleton_from_rig(ph, local_changes, None)
    fr, _ = _hand_frame(sk0, 'l')
    lax = local_axis(rest, 'wrist.L', fr['ulnar'])
    probe = {}
    for sgn in (+1.0, -1.0):
        s = skeleton_from_rig(ph, local_changes, pose_from_local({'wrist.L': lax * np.radians(15.0) * sgn}))
        probe[sgn] = wrist_angles(s, 'l')['extension_deg']
    sgn = 1.0 if probe[1.0] > probe[-1.0] else -1.0
    aa = pose_from_local({'wrist.L': lax * np.radians(120.0) * sgn})
    sk = skeleton_from_rig(ph, local_changes, aa, source='broken-wrist')
    r = t5_joint_rom(sk)
    rows.append(
        {
            'control': 'wrist driven to ~120 deg extension',
            'gate': 't5_joint_rom',
            'status': r['status'],
            'must_be': FAIL,
            'ok': r['status'] == FAIL,
            'measured_extension_deg': round(wrist_angles(sk, 'l')['extension_deg'], 2),
            'checks': [c for c in r['detail']['checks'] if c['status'] == FAIL][:4],
        }
    )

    # 2. cervical: 30 deg of extension at each of the four joints, i.e. 120 deg total,
    #    with the occiput joint contributing a quarter instead of at least a half. The
    #    pitch axis and its sign are measured the same way.
    pitch_axis = af['subject_left']
    probe = {}
    for sgn in (+1.0, -1.0):
        s = skeleton_from_rig(
            ph, local_changes, pose_from_local({'head': local_axis(rest, 'head', pitch_axis) * np.radians(15.0) * sgn})
        )
        probe[sgn] = cervical_angles(s)['total_extension_deg']
    sgn = 1.0 if probe[1.0] > probe[-1.0] else -1.0
    d = {b: local_axis(rest, b, pitch_axis) * np.radians(30.0) * sgn for b in CERVICAL_RIG_JOINTS}
    sk = skeleton_from_rig(ph, local_changes, pose_from_local(d), source='broken-neck')
    r = t5_joint_rom(sk)
    fails = [c['check'] for c in r['detail']['checks'] if c['status'] == FAIL]
    rows.append(
        {
            'control': '30 deg of extension at every cervical joint',
            'gate': 't5_joint_rom',
            'status': r['status'],
            'must_be': FAIL,
            'ok': r['status'] == FAIL,
            'failed_checks': fails,
            'measured_total_extension_deg': round(cervical_angles(sk)['total_extension_deg'], 2),
            'measured_occiput_share_pitch': cervical_angles(sk)['occiput_share_pitch'],
        }
    )
    return rows


def clone_pose_set_control(ph, local_changes):
    """Control 3: a pose set with no variety at all — the same pose eight times.

    t5_pose_stiffness must FAIL it; the row carries the gate's own `observed` block.
    """
    sk0 = skeleton_from_rig(ph, local_changes, None, source='clone')
    r = t5_pose_stiffness([sk0] * 8, world_up=np.array([0.0, 0.0, 1.0]))
    return {
        'control': 'the same pose eight times',
        'gate': 't5_pose_stiffness',
        'status': r['status'],
        'must_be': FAIL,
        'ok': r['status'] == FAIL,
        'observed': r['observed'],
    }


def lockstep_pronation_control(ph, local_changes):
    """Control 4: 60 deg of forearm pronation with the humerus twisted in lockstep.

    The AFS p.149 defect, authored directly into a pose the way a retarget would. The
    control holds when the humeral twist comes back non-zero, i.e. detected.
    """
    d = {
        'lowerarm01.L': np.array([0.0, np.radians(30.0), 0.0]),
        'lowerarm02.L': np.array([0.0, np.radians(30.0), 0.0]),
        'upperarm01.L': np.array([0.0, np.radians(25.0), 0.0]),
    }
    sk = skeleton_from_rig(ph, local_changes, pose_from_local(d), source='broken-pronation')
    c = pronation_coupling_in_pose(sk, 'l')
    return {
        'control': 'forearm pronated 60 deg with 25 deg of humeral twist',
        'gate': 't5_pronation_isolation/coupling',
        'observed': {
            'forearm_twist_deg': round(c['forearm_twist_deg'], 3),
            'humerus_twist_deg': round(c['humerus_twist_deg'], 3),
        },
        'must_be': 'humerus twist non-zero and therefore detected',
        'ok': abs(c['humerus_twist_deg']) > 1e-6,
    }


def _humeral_patch_owner_row(ph, local_changes, rest):
    """Control 5: the same elbow-owner comparison run on a >90%-upperarm02 skin patch.

    Returns the control row, or None when the rig carries fewer than eight such vertices
    — in which case demo_broken() appended nothing, and still does not.
    """
    m = MS._model()
    vbi, vbw = m.vertex_bone_indices.numpy(), m.vertex_bone_weights.numpy()
    hum_i = bone_index('upperarm02.L')
    w = np.zeros(len(vbi))
    for cidx in range(vbi.shape[1]):
        w += np.where(vbi[:, cidx] == hum_i, vbw[:, cidx], 0.0)
    cand = np.nonzero(w > 0.90)[0]
    if len(cand) < 8:
        return None
    # order by distance to the elbow so the control patch sits where the real one does
    e = rest['heads'][bone_index('lowerarm01.L')]
    cand = cand[np.argsort(np.linalg.norm(rest['v'][cand] - e, axis=1))][:20]
    uh = unit(rest['heads'][bone_index('lowerarm01.L')] - rest['heads'][bone_index('upperarm01.L')])
    uf = unit(rest['heads'][bone_index('wrist.L')] - rest['heads'][bone_index('lowerarm01.L')])
    ax = unit(np.cross(uh, uf))
    st = rig_state(
        ph,
        local_changes,
        pose_from_local({'lowerarm01.L': local_axis(rest, 'lowerarm01.L', ax) * np.radians(60.0)}),
    )
    resid = {}
    for b in ('upperarm02.L', 'lowerarm01.L'):
        T = st['R'][bone_index(b)] @ rest['R'][bone_index(b)].T
        pred = (rest['v'][cand] - rest['heads'][bone_index(b)]) @ T.T + st['heads'][bone_index(b)]
        resid[b] = float(np.sqrt(((pred - st['v'][cand]) ** 2).sum(1).mean()))
    owner = min(resid, key=resid.get)
    return {
        'control': 'a >90%%-upperarm02 skin patch (n=%d) put through the same comparison' % len(cand),
        'gate': 't5_elbow_owner',
        'observed': {'owner': owner, 'residual_mm': {k: round(1000 * v, 4) for k, v in resid.items()}},
        'must_be': 'upperarm02.L',
        'ok': owner == 'upperarm02.L',
    }


def _elbow_owner_conditioned_rows(ph, local_changes):
    """Control 5b (D7): the gate's PASS must be conditioned on its own negative control.

    Two invariants, both checked against the live record rather than asserted in prose:
    a PASS may only exist when the comparator demonstrably discriminates at this joint,
    and the gate must never return PASS for a patch that is HUMERAL by definition —
    which is precisely what it did before this control existed (epicondyle_lat -> pass,
    owner lowerarm01.L, residual 0.0 mm).
    """
    rows = []
    eo = t5_elbow_owner(ph, local_changes, 'l')
    eo_obs = eo['observed'] or {}
    rows.append(
        {
            'control': 'a PASS from t5_elbow_owner implies its humeral control patches '
            'came back humerus-owned and its synthetic controls held',
            'gate': 't5_elbow_owner',
            'observed': {
                'status': eo['status'],
                'discriminates': eo_obs.get('comparator_discriminates_at_this_joint'),
                'synthetic_ok': eo_obs.get('synthetic_controls_ok'),
                'controls_answering_forearm': eo_obs.get('humeral_controls_answering_forearm'),
            },
            'must_be': 'status != pass unless discriminates and synthetic_ok',
            'ok': bool(
                eo['status'] != PASS
                or (eo_obs.get('comparator_discriminates_at_this_joint') and eo_obs.get('synthetic_controls_ok'))
            ),
        }
    )
    eoc = t5_elbow_owner(ph, local_changes, 'l', patch=ELBOW_HUMERAL_CONTROL_PATCHES[0])
    rows.append(
        {
            'control': 't5_elbow_owner handed %r, a landmark of the distal humerus' % ELBOW_HUMERAL_CONTROL_PATCHES[0],
            'gate': 't5_elbow_owner',
            'observed': {'status': eoc['status'], 'explain': (eoc['explain'] or '')[:140]},
            'must_be': 'anything but pass: "travels with the forearm" is not a claim about a humeral landmark',
            'ok': eoc['status'] != PASS,
        }
    )
    return rows


def elbow_owner_controls(ph, local_changes, rest):
    """Controls 5 and 5b together — every negative control of t5_elbow_owner.

    Returns the skin-patch row (when the rig carries the patch) followed by the two
    conditioned-PASS rows, which is the order demo_broken() appended them in.
    """
    rows = []
    patch_row = _humeral_patch_owner_row(ph, local_changes, rest)
    if patch_row is not None:
        rows.append(patch_row)
    rows.extend(_elbow_owner_conditioned_rows(ph, local_changes))
    return rows


def same_bone_invariance_control(ph, local_changes, rest):
    """Control 6: the patellar-ligament metric's POSITIVE control.

    Two patches on the SAME bone (tibial tuberosity and medial malleolus, both on the
    shank) must stay invariant to within the printed drift limit through 30/60/90 deg of
    knee flexion, which shows the metric itself is sound before it is believed. Returns
    None when either region is absent from the rig, as demo_broken() did.
    """
    tub, _ = _region_group('tibial_tuberosity', 'l')
    mal, _ = _region_group('malleolus_med', 'l')
    if tub is None or mal is None:
        return None
    shin = 'lowerleg01.L'
    uh = unit(rest['heads'][bone_index(shin)] - rest['heads'][bone_index('upperleg01.L')])
    ul = unit(rest['heads'][bone_index('foot.L')] - rest['heads'][bone_index(shin)])
    ax = unit(np.cross(uh, ul))
    d0 = float(np.linalg.norm(rest['v'][tub].mean(0) - rest['v'][mal].mean(0)))
    drifts = []
    for deg in (30.0, 60.0, 90.0):
        st = rig_state(ph, local_changes, pose_from_local({shin: local_axis(rest, shin, ax) * np.radians(deg)}))
        d = float(np.linalg.norm(st['v'][tub].mean(0) - st['v'][mal].mean(0)))
        drifts.append(abs(d - d0) / d0)
    return {
        'control': 'tibial tuberosity vs medial malleolus, both on the shank',
        'gate': 't5_patellar_ligament/metric',
        'observed': {'max_abs_drift': round(max(drifts), 6)},
        'must_be': 'below the 2%% limit (a same-bone pair really is invariant)',
        'ok': max(drifts) < PATELLAR_LIGAMENT_MAX_DRIFT,
    }


def incoming_blazepose_control(ph, local_changes):
    """Control 7: THE INCOMING-POSE PATH, exercised end to end.

    The rig's own joints are written into a BlazePose-shaped array in image pixels,
    twice: once with the depth channel (pseudo3d) and once without (image2d). The gate
    must READ the first and REFUSE the second. Without this control the claim "runs on
    incoming pose data too" is just a docstring. Any exception becomes the error row the
    original produced, so one broken dependency cannot take the whole demo down.
    """
    try:
        from zyg_workflows.geom import keypoints as KP

        names = list(KP.POSE_NAMES)
        rigsk = skeleton_from_rig(ph, local_changes, None)
        m2b = {
            'left_shoulder': 'shoulder_l',
            'right_shoulder': 'shoulder_r',
            'left_elbow': 'elbow_l',
            'right_elbow': 'elbow_r',
            'left_wrist': 'wrist_l',
            'right_wrist': 'wrist_r',
            'left_index': 'index_mcp_l',
            'right_index': 'index_mcp_r',
            'left_pinky': 'pinky_mcp_l',
            'right_pinky': 'pinky_mcp_r',
            'left_thumb': 'thumb_tip_l',
            'right_thumb': 'thumb_tip_r',
            'left_hip': 'hip_l',
            'right_hip': 'hip_r',
            'left_knee': 'knee_l',
            'right_knee': 'knee_r',
            'left_ankle': 'ankle_l',
            'right_ankle': 'ankle_r',
            'left_eye': 'eye_l',
            'right_eye': 'eye_r',
        }
        pts = np.zeros((len(names), 3), np.float64)
        zz = np.zeros(len(names))
        vis = np.zeros(len(names))
        for bn, jn in m2b.items():
            if jn in rigsk.joints:
                p = rigsk.joints[jn]
                i = names.index(bn)
                pts[i] = [p[0] * 1000.0, -p[2] * 1000.0, 1.0]  # a camera, roughly
                zz[i] = p[1] * 1000.0
                vis[i] = 1.0
        r3 = t5_joint_rom(skeleton_from_blazepose(pts, z=zz, visibility=vis))
        r2 = t5_joint_rom(skeleton_from_blazepose(pts, z=None, visibility=vis))
        wr = wrist_angles(skeleton_from_blazepose(pts, z=zz, visibility=vis), 'l')
        return {
            'control': "the rig's own joints re-expressed as a 33-point BlazePose "
            'detection, with and without the depth channel',
            'gate': 't5_joint_rom (incoming pose path)',
            'observed': {
                'pseudo3d_status': r3['status'],
                'pseudo3d_wrist_l_extension_deg': round(wr['extension_deg'], 2),
                'image2d_status': r2['status'],
            },
            'must_be': 'pseudo3d reports, image2d refuses',
            'ok': bool(r3['status'] == REPORT and r2['status'] == UNMEASURABLE),
        }
    except Exception as e:  # noqa: BLE001
        return {
            'control': 'incoming BlazePose path',
            'gate': 't5_joint_rom',
            'ok': False,
            'error': '%s: %s' % (type(e).__name__, e),
        }


def _pose_library_character_rows(char, ph, local_changes):
    """The two rows control 8 produces for one shipped pose library.

    First the t5_joint_rom row (the layer must NOT render a library measured at
    violation_rate 1.0 as a pass, and the rate must be present in `observed`), then the
    t5_pose_stiffness reachability row for AFS p.16's transverse-tilt statistic.
    """
    rows = []
    cph, clc = ph, local_changes
    for c in characters():
        if c['name'] == char:
            cph, clc = c['phenotype'], c['local_changes']
            break
    pl = pose_layer(char, cph, clc)
    g = pl['gate_index']['t5_joint_rom']
    lib = pl['library']
    rows.append(
        {
            'control': 'the SHIPPED fitted pose library for %s, %d poses, through pose_layer()'
            % (char, lib['n_poses']),
            'gate': 't5_joint_rom (pose layer)',
            'status': g['status'],
            'must_be': 'NOT pass, and the violation rate present in observed',
            'observed': {
                'rollup': g['status'],
                'rest_only_status': g['rest_only_status'],
                'library_only_status': g['library_only_status'],
                'n_poses': lib['n_poses'],
                'n_violating': lib['n_violating'],
                'violation_rate': lib['violation_rate'],
                'observed_carries_rate': g['observed'].get('violation_rate') is not None,
            },
            'ok': bool(
                lib['n_poses'] > 0
                and g['status'] != PASS
                and g['observed'].get('violation_rate') is not None
                and g['observed'].get('n_violating') is not None
            ),
        }
    )
    # and the stiffness statistic must be REACHED, with its printed 2 deg floor
    s = lib.get('stiffness')
    rows.append(
        {
            'control': 'AFS p.16 transverse-tilt statistic reachable for %s from the gate entry point' % char,
            'gate': 't5_pose_stiffness (pose layer)',
            'status': (s or {}).get('status'),
            'must_be': 'a real verdict carrying shoulder/hip tilt sd against the '
            'printed %.1f deg floor AND the sign-opposition conjunct of '
            'the same sentence, scored' % TRANSVERSE_TILT_STDEV_MIN_DEG,
            'observed': {
                k: (s or {}).get('observed', {}).get(k)
                for k in (
                    'n_poses',
                    'shoulder_tilt_sd_deg',
                    'hip_tilt_sd_deg',
                    'tilt_opposition_fraction',
                    'tilt_n_same_sign',
                    'tilt_n_same_sign_allowed',
                    'scored_check_status',
                )
            },
            # WHAT THIS CONTROL IS AND IS NOT. It is a REACHABILITY control: the p.16
            # statistic must arrive at the gate entry point with both conjuncts scored
            # and the drift guard clean. It is NOT the control that proves the
            # sign-opposition constant is read — the clause that used to sit here
            # compared the band label against the constant that PRODUCED the band
            # label, which is a tautology and passed happily with the constant set to
            # 0.0 while the gate went on failing at 0.5 (NEW-1). That job now belongs
            # to control 10, which mutates the constant and requires the verdict to
            # move.
            'ok': bool(
                s
                and s['status'] in (PASS, WARN, FAIL)
                and s['observed'].get('shoulder_tilt_sd_deg') is not None
                and (s.get('band') or {}).get('transverse_tilt_sd_min_deg') == TRANSVERSE_TILT_STDEV_MIN_DEG
                # the guard ran on real data and found declared == enforced
                and (s.get('detail') or {}).get('opposition_rule_drift') is None
                # R1: the second conjunct must be SCORED, not merely stored,
                # and it must publish the count its band allows on this
                # denominator so the verdict is checkable against the band.
                and any(
                    r['check'] == 'tilt_sign_opposition'
                    and r.get('entered_verdict')
                    and r.get('status') in (PASS, FAIL)
                    and r.get('n_same_sign_allowed') is not None
                    for r in ((s.get('detail') or {}).get('scored') or [])
                )
            ),
        }
    )
    return rows


def pose_library_controls(ph, local_changes):
    """Control 8: THE SHIPPED FITTED LIBRARY IS THE BROKEN CONTROL FOR THE POSE LAYER.

    And this is the control the previous wave did not have. pose_library_report()
    measures abel's own 44 poses at violation_rate 1.0 against the printed bands, so
    pose_layer() must NOT return PASS for t5_joint_rom on a character that has one. A
    layer that renders those poses as a pass has been falsified. Characters are walked in
    sorted asset order and a failure on one becomes its own error row.
    """
    rows = []
    for _asset, char in sorted(POSE_LIBRARY_CHARACTERS.items()):
        try:
            rows.extend(_pose_library_character_rows(char, ph, local_changes))
        except Exception as e:  # noqa: BLE001
            rows.append(
                {
                    'control': 'pose_layer on %s' % char,
                    'gate': 'pose_layer',
                    'ok': False,
                    'error': '%s: %s' % (type(e).__name__, e),
                }
            )
    return rows


def incomplete_library_control(ph, local_changes):
    """Control 9: A LIBRARY THAT LOST FILES MUST NOT PRESENT ITSELF AS COMPLETE (F8).

    Two synthetic files under a scratch root — one valid, one truncated JSON — must
    produce complete=False, n_dropped=1 and the bad path NAMED. A silent drop would
    leave complete=True with a shrunken denominator, which is a fabricated rate. The
    scratch root is removed whatever happens.
    """
    tmp = tempfile.mkdtemp(prefix='poselib_control_')
    try:
        names, _ = bone_roster()
        src = None
        for a in POSE_LIBRARY_CHARACTERS:
            recs = scan_pose_library(a)['records']
            if recs:
                src = recs[0]
                break
        good = [[0.0, 0.0, 0.0]] * len(names) if src is None else src['pose_aa'].tolist()
        # one valid file, one file whose JSON is truncated mid-array
        for cell, payload in (
            ('cell_00', json.dumps({'cell': 'cell_00', 'pose_aa': good, 'fit_ok': True})),
            ('cell_01', '{"cell": "cell_01", "pose_aa": [[0.0,'),
        ):
            d = os.path.join(tmp, 'ctrl_asset', cell)
            os.makedirs(d)
            with open(os.path.join(d, 'anny_fit.json'), 'w') as fh:
                fh.write(payload)
        integ = scan_pose_library('ctrl_asset', root=tmp)['integrity']
        rep = pose_library_report('ctrl_asset', ph, local_changes, root=tmp)
        return {
            'control': 'a 2-file library with 1 truncated JSON',
            'gate': 'load_pose_library / scan_pose_library integrity (F8)',
            'observed': {
                'n_files_found': integ['n_files_found'],
                'n_loaded': integ['n_loaded'],
                'n_dropped': integ['n_dropped'],
                'complete': integ['complete'],
                'dropped_named': bool(integ['dropped_paths']),
                'dropped_reason': (integ['dropped'][0]['reason'] if integ['dropped'] else None),
                'report_library_complete': rep['library_complete'],
                'report_status': rep['status'],
                'rate_denominator': rep['rate_denominator'],
            },
            'must_be': 'complete=False, n_dropped=1, the dropped path NAMED, and the '
            'report status raised to at least warn',
            'ok': bool(
                integ['n_files_found'] == 2
                and integ['n_loaded'] == 1
                and integ['n_dropped'] == 1
                and integ['complete'] is False
                and integ['dropped_paths']
                and rep['library_complete'] is False
                and ROLLUP_RANK.get(rep['status'], 0) >= ROLLUP_RANK[WARN]
                and rep['rate_denominator'] == 1
            ),
        }
    except Exception as e:  # noqa: BLE001
        return {
            'control': 'incomplete-library control',
            'gate': 'scan_pose_library',
            'ok': False,
            'error': '%s: %s' % (type(e).__name__, e),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
