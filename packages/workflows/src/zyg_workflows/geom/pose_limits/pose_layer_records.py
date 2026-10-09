# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The record builders pose_layer() assembles its published dict from.

Extracted 2026-10-09 out of pose_layer.py, where pose_layer() had grown to a 368-line
function (the repo's quality ratchet caps a function at 300). Every helper here is a
verbatim move of one of its blocks, so the published dict is unchanged:

* :func:`absent_library_report` — the stand-in report for a character with no library;
* :func:`stiffness_over_set` — the diversity statistic measured over the fitted pose SET;
* :func:`library_block` — the ``library`` block of the published dict;
* :func:`rate_text` — the violation-rate sentence (was the ``_rate_txt`` closure);
* :func:`gate_subjects`, :func:`gate_observed`, :func:`gate_explain` and
  :func:`gate_record` — one rolled-up gate record, which was the 190-line loop body.

The dependency runs ONE WAY: pose_layer.py imports this module, this module imports the
pose_limits leaves it needs and never pose_layer. The two constants pose_layer owns
(POSE_LAYER_SCHEMA, POSE_LAYER_SUBJECTS) are therefore not read here — the per-gate
declaration arrives as the ``decl`` argument and the top-level dict stays in pose_layer().
"""

from dataclasses import dataclass, field

from zyg_workflows.geom.pose_limits.base import (
    CANON,
    ERROR,
    REPORT,
    UNRESOLVED,
    np,
    rollup,
)
from zyg_workflows.geom.pose_limits.characters import (
    LIBRARY_COMPLETENESS_RULE,
    NEUTRAL,
    POSE_LIBRARY_CHARACTERS,
    POSE_LIBRARY_ROOT,
    scan_pose_library,
)
from zyg_workflows.geom.pose_limits.printed import PRONATION_SOURCE, TRANSVERSE_TILT_STDEV_MIN_DEG
from zyg_workflows.geom.pose_limits.rom import _res
from zyg_workflows.geom.pose_limits.skeleton import skeleton_from_pose_aa
from zyg_workflows.geom.pose_limits.stiffness import t5_pose_stiffness

# The phenotype keys a fitted pose record is allowed to override on the character's own
# phenotype before the skeleton is rebuilt. Stated once, where stiffness_over_set reads it.
POSE_PHENOTYPE_KEYS = ('gender', 'age', 'muscle', 'weight', 'height', 'proportions')


def absent_library_report(name, expected_pose_aa_rows):
    """The stand-in ``pose_library_report()`` for a character that ships no fitted library.

    `name` is the character; `expected_pose_aa_rows` is ``len(bone_roster()[0])``, passed
    in rather than read here so this function stays pure (the roster loads the rig model,
    and the caller only pays for it on this branch, exactly as before).

    Returns the shape ``pose_library_report()`` returns, with every count zeroed, status
    UNRESOLVED, and a `reason` naming the characters POSE_LIBRARY_CHARACTERS does map. It
    is emphatically NOT a pass: the pose half of every gate that declares the library was
    not evaluated, and `explain` says so in those words.
    """
    return {
        'n_poses': 0,
        'rate_denominator': 0,
        'n_violating': None,
        'n_warning': None,
        'n_passing': None,
        'violation_rate': None,
        'warn_rate': None,
        'status': UNRESOLVED,
        'status_counts': {},
        'per_check_counts': {},
        'worst_offenders': {'by_check': [], 'by_pose': []},
        'library_complete': False,
        'library_incomplete_note': None,
        'integrity': {
            'root': POSE_LIBRARY_ROOT,
            'pattern': None,
            'char_asset': None,
            'n_files_found': 0,
            'n_loaded': 0,
            'n_dropped': 0,
            'complete': False,
            'dropped': [],
            'dropped_paths': [],
            'drop_reason_counts': {},
            'drop_reason_meanings': {},
            'expected_pose_aa_rows': expected_pose_aa_rows,
            'n_fit_ok_false': 0,
            'fit_ok_false_paths': [],
            'rule': LIBRARY_COMPLETENESS_RULE,
        },
        'occiput_share_failures_by_total_rotation': {},
        'pronation_coupling': None,
        'rows': [],
        'reason': (
            'no fitted pose library exists for %r: POSE_LIBRARY_CHARACTERS '
            'maps char_mesh assets for %s only' % (name, ', '.join(sorted(POSE_LIBRARY_CHARACTERS.values())))
        ),
        'explain': (
            'no fitted pose library for %r, so the pose half of every gate '
            'that declares it was NOT evaluated. This is not a pass.' % name
        ),
        'policy': 'a high rate is a finding about our pose library. It is not a reason to widen a printed band.',
    }


def stiffness_over_set(char_asset, phenotype, local_changes, limit, world_up):
    """Measure t5_pose_stiffness over the fitted pose SET, or return an ERROR record.

    This is the real t5_pose_stiffness — the one carrying AFS p.16's printed 2 deg
    standard-deviation floor — and it is defined over a SET, so it re-poses the rig once
    per fitted pose (`limit` truncates the set) and hands every skeleton to the check at
    once. An exception becomes an ERROR `_res` record carrying the last 1500 characters of
    the traceback, so a broken pose file cannot take the whole pose layer down with it.
    """
    sks = []
    for r in scan_pose_library(char_asset)['records'][: (int(limit) if limit else None)]:
        p = dict(phenotype or NEUTRAL)
        p.update({k: v for k, v in (r['phenotype'] or {}).items() if k in POSE_PHENOTYPE_KEYS})
        sks.append(skeleton_from_pose_aa(p, r['pose_aa'], local_changes, source='%s/%s' % (char_asset, r['cell'])))
    try:
        return t5_pose_stiffness(sks, world_up=(world_up if world_up is not None else np.array([0.0, 0.0, 1.0])))
    except Exception as e:  # noqa: BLE001
        import traceback

        return _res(
            't5_pose_stiffness', ERROR, '%s: %s' % (type(e).__name__, e), traceback=traceback.format_exc()[-1500:]
        )


def library_block(rep, lib_present, char_asset, stiff):
    """Build the ``library`` block of the published dict from a pose-library report.

    `rep` is a `pose_library_report()` record or the :func:`absent_library_report` stand-in,
    `lib_present` whether POSE_LIBRARY_CHARACTERS mapped a char_mesh asset at all, and
    `stiff` the :func:`stiffness_over_set` record (or None). The block's own `present` is
    narrower than `lib_present`: a mapped asset whose scan measured zero poses is absent
    as far as every gate is concerned.
    """
    return {
        'status': rep.get('status'),
        'present': bool(lib_present and rep.get('n_poses')),
        'complete': bool(rep.get('library_complete')),
        'char_asset': char_asset,
        'n_files_found': (rep.get('integrity') or {}).get('n_files_found', 0),
        'n_poses': rep.get('n_poses', 0),
        'rate_denominator': rep.get('rate_denominator', 0),
        'n_violating': rep.get('n_violating'),
        'n_warning': rep.get('n_warning'),
        'n_passing': rep.get('n_passing'),
        'violation_rate': rep.get('violation_rate'),
        'warn_rate': rep.get('warn_rate'),
        'status_counts': rep.get('status_counts') or {},
        'per_check_counts': rep.get('per_check_counts') or {},
        'worst_offenders': rep.get('worst_offenders') or {'by_check': [], 'by_pose': []},
        'integrity': rep.get('integrity'),
        'incomplete_note': rep.get('library_incomplete_note'),
        'stiffness': stiff,
        'pronation_coupling': rep.get('pronation_coupling'),
        'occiput_share_failures_by_total_rotation': rep.get('occiput_share_failures_by_total_rotation') or {},
        'explain': rep.get('explain'),
        'reason': rep.get('reason'),
        'policy': rep.get('policy'),
    }


def rate_text(library):
    """The violation-rate sentence every library-declaring gate's `explain` ends with.

    Was the ``_rate_txt`` closure of pose_layer(). A library that was not evaluated says
    so; it never reports a rate of zero, which a reader would take for a pass.
    """
    if library['violation_rate'] is None:
        return 'library NOT evaluated'
    return 'library %d/%d pose(s) FAIL (rate %.4f)' % (
        library['n_violating'],
        library['n_poses'],
        library['violation_rate'],
    )


@dataclass
class GateSubjects:
    """One gate's per-subject verdicts and the roll-up over them.

    `rest_status` / `library_status` are the subject verdicts (None where the subject was
    not evaluated), `library_record` the library evidence this particular gate's subject
    produced, `evaluated` the subjects that really were measured, `not_evaluated` the
    DECLARED subjects that could not be (each contributing UNRESOLVED), `not_applicable`
    the subjects this gate never claimed (contributing nothing), and `status` the roll-up.
    """

    rest_status: object = None
    library_status: object = None
    library_record: object = None
    evaluated: list = field(default_factory=list)
    not_evaluated: dict = field(default_factory=dict)
    not_applicable: dict = field(default_factory=dict)
    status: object = None


def gate_subjects(gid, decl, rest_record, library, rep, stiff):
    """Evaluate every subject gate `gid` declares and roll the verdicts up.

    `decl` is this gate's POSE_LAYER_SUBJECTS entry, `rest_record` its `run_character()`
    record (or None when the rest run produced none), `library` the :func:`library_block`,
    `rep` the pose-library report (read for its `reason`) and `stiff` the stiffness record.

    THE ROLL-UP RULE, once: status = worst(subject statuses actually computed) under
    ROLLUP_RANK, and a DECLARED subject that could not be evaluated contributes UNRESOLVED.
    So a gate that passes on the rest pose and has no fitted library to check reports
    UNRESOLVED, not PASS — half of what it claims to gate was never looked at.
    """
    r = rest_record
    sub = GateSubjects(rest_status=(r['status'] if (decl['rest'] and r is not None) else None))

    if decl['rest']:
        if r is None:
            sub.not_evaluated['rest'] = 'geom.pose_limits.run_character returned no record for %r' % gid
        else:
            sub.evaluated.append('rest')
    else:
        sub.not_applicable['rest'] = decl.get('rest_not_applicable_because', '')

    if decl['library']:
        if not library['present']:
            sub.library_status = UNRESOLVED
            sub.not_evaluated['library'] = rep.get('reason') or 'the fitted pose library could not be read'
        elif gid == 't5_joint_rom':
            sub.library_status, sub.library_record = (
                library['status'],
                {
                    'n_poses': library['n_poses'],
                    'n_violating': library['n_violating'],
                    'violation_rate': library['violation_rate'],
                    'per_check_counts': library['per_check_counts'],
                    'worst_offenders': library['worst_offenders'],
                    'complete': library['complete'],
                    'band': (r or {}).get('band'),
                    'source': (r or {}).get('source'),
                    'provenance': (r or {}).get('provenance'),
                },
            )
            sub.evaluated.append('library')
        elif gid == 't5_pronation_isolation':
            sub.library_status, sub.library_record = (
                REPORT,
                {
                    'coupling': library['pronation_coupling'],
                    'not_scored_because': decl['library_not_scored_because'],
                    'source': PRONATION_SOURCE,
                    'provenance': CANON,
                },
            )
            sub.evaluated.append('library')
        elif gid == 't5_pose_stiffness':
            sub.library_status = (stiff or {}).get('status', UNRESOLVED)
            sub.library_record = stiff
            sub.evaluated.append('library')
    else:
        sub.not_applicable['library'] = decl.get('library_not_applicable_because', '')

    # A DECLARED subject that was not evaluated contributes UNRESOLVED. A subject that
    # does not APPLY (with a measured reason) contributes nothing — it was never part
    # of the claim.
    contrib = [s for s in (sub.rest_status, sub.library_status) if s]
    if decl['rest'] and 'rest' not in sub.evaluated:
        contrib.append(UNRESOLVED)
    if decl['library'] and 'library' not in sub.evaluated:
        contrib.append(UNRESOLVED)
    sub.status = rollup(contrib)
    return sub


def gate_observed(gid, decl, base, sub, library, stiff):
    """The `observed` dict of one gate record: every number that must reach a reader.

    WHAT GOES IN `observed`, AND WHY IT MATTERS. A report writer that flattens each
    gate to a whitelist drops `detail` entirely (adversarial-review F4), so any
    number that must reach a reader has to be HERE. Two rules:
      - every gate's library numbers are the ones ITS OWN subject produced. Attaching
        the ROM violation rate to t5_elbow_owner, whose subject is the rig skinning,
        would be a different dishonesty from hiding it.
      - a gate that does not declare the library says so in words, in this dict.

    `base` is the rest record or ``{}``; `sub` the :func:`gate_subjects` result.
    """
    obs = {
        'rest_status': sub.rest_status,
        'library_status': sub.library_status,
        'rest_observed': base.get('observed'),
    }
    if not decl['library']:
        obs['library_subject'] = 'not applicable: %s' % (
            sub.not_applicable.get('library') or 'this gate does not claim the pose library'
        )
        return obs

    obs['n_poses'] = library['n_poses']
    obs['library_complete'] = library['complete']
    if gid == 't5_joint_rom':
        obs.update(
            {
                'n_violating': library['n_violating'],
                'n_warning': library['n_warning'],
                'violation_rate': library['violation_rate'],
                'worst_check': (
                    library['worst_offenders']['by_check'][0]['check']
                    if library['worst_offenders']['by_check']
                    else None
                ),
                'worst_check_fail_count': (
                    library['worst_offenders']['by_check'][0]['fail']
                    if library['worst_offenders']['by_check']
                    else None
                ),
            }
        )
    elif gid == 't5_pronation_isolation':
        pc = library['pronation_coupling'] or {}
        obs.update(
            {
                'library_humerus_twist_deg_abs_mean': pc.get('humerus_twist_deg_abs_mean'),
                'library_forearm_twist_deg_abs_mean': pc.get('forearm_twist_deg_abs_mean'),
                'library_pearson_r_forearm_vs_humerus': pc.get('pearson_r_forearm_vs_humerus'),
                'library_n_arms': pc.get('n_arms'),
                'library_not_scored': True,
            }
        )
    elif gid == 't5_pose_stiffness':
        # THE WHOLE POINT OF (b): the five statistics AFS p.16 / p.175 / p.19 ask
        # for must reach the reader, so they live in `observed`, not in `detail`.
        # `scored_check_status` is the R1 fix in one key: a reader can see which
        # conjuncts were scored and how each came out, without opening `detail`.
        so = (stiff or {}).get('observed') or {}
        obs.update(
            {
                'shoulder_tilt_sd_deg': so.get('shoulder_tilt_sd_deg'),
                'hip_tilt_sd_deg': so.get('hip_tilt_sd_deg'),
                'transverse_tilt_sd_min_deg': TRANSVERSE_TILT_STDEV_MIN_DEG,
                'tilt_opposition_fraction': so.get('tilt_opposition_fraction'),
                'tilt_opposition_required_fraction': so.get('tilt_opposition_required_fraction'),
                'tilt_n_same_sign': so.get('tilt_n_same_sign'),
                'tilt_n_sign_evaluated': so.get('tilt_n_sign_evaluated'),
                # the required fraction as the count it allows here, and the guard
                # that says the two are still the same rule (NEW-1). A report writer
                # that keeps only `observed` still gets both.
                'tilt_n_same_sign_allowed': so.get('tilt_n_same_sign_allowed'),
                'tilt_opposition_rule_drift': so.get('tilt_opposition_rule_drift') or so.get('opposition_rule_drift'),
                'tilt_same_sign_by_floor_deg': so.get('tilt_same_sign_by_floor_deg'),
                'scored_check_status': so.get('scored_check_status'),
                'elbow_locked_fraction_by_window_deg': so.get('elbow_locked_fraction_by_window_deg'),
                'forearms_parallel_fraction_by_window_deg': so.get('forearms_parallel_fraction_by_window_deg'),
                'erect_fraction_by_trunk_window_deg': so.get('erect_fraction_by_trunk_window_deg'),
                'fully_straight_finger_chain_fraction': so.get('fully_straight_finger_chain_fraction'),
            }
        )
    return obs


def gate_explain(gid, decl, base, sub, library, stiff):
    """One sentence naming every subject of gate `gid` and its numbers.

    The clauses are joined with ' | ' in a fixed order — rest, fitted library, then the
    DECLARED-but-not-evaluated subjects and the not-applicable ones, each sorted by
    subject name — because that order is what a reader of the gate report sees.
    """
    parts = []
    if decl['rest']:
        parts.append(
            'rest pose: %s%s'
            % (sub.rest_status or 'not evaluated', (' (%s)' % base['explain'][:90]) if base.get('explain') else '')
        )
    if decl['library']:
        parts.append('fitted pose library: %s — %s' % (sub.library_status or 'not evaluated', rate_text(library)))
        if gid == 't5_pose_stiffness' and stiff:
            # 500, not 150: at 150 the sentence was cut before the sign-opposition
            # clause, which is the half of AFS p.16 that this gate used to drop (R1).
            # A truncation that removes the failing conjunct is the reporting half of
            # the same defect.
            parts[-1] = 'fitted pose library: %s — %s' % (sub.library_status, stiff['explain'][:500])
        if gid == 't5_pronation_isolation' and library['pronation_coupling']:
            pc = library['pronation_coupling']
            parts[-1] = (
                'fitted pose library: report — mean |humeral twist| %s deg, '
                'mean |forearm twist| %s deg, Pearson r %s over %s arms; not '
                'scored because no printed source gives a coupling threshold'
                % (
                    pc['humerus_twist_deg_abs_mean'],
                    pc['forearm_twist_deg_abs_mean'],
                    pc['pearson_r_forearm_vs_humerus'],
                    pc['n_arms'],
                )
            )
    for k, v in sorted(sub.not_evaluated.items()):
        if v:
            parts.append('%s subject DECLARED but NOT evaluated: %s' % (k, v[:170]))
    for k, v in sorted(sub.not_applicable.items()):
        if v:
            parts.append('%s subject not applicable: %s' % (k, v[:170]))
    return ' | '.join(parts)


def gate_record(gid, decl, rest_record, library, rep, stiff):
    """One ROLLED-UP gate record — an element of pose_layer()['gates'].

    Carries exactly POSE_LAYER_GATE_KEYS (verify_contract() checks that on every call).
    `band` / `source` / `provenance` prefer the rest record and fall back to the library
    record, so a gate whose rest subject does not apply still publishes its printed pages.
    """
    base = rest_record or {}
    sub = gate_subjects(gid, decl, rest_record, library, rep, stiff)
    lib_rec = sub.library_record
    return {
        'gate': gid,
        'status': sub.status,
        'explain': gate_explain(gid, decl, base, sub, library, stiff),
        'observed': gate_observed(gid, decl, base, sub, library, stiff),
        'band': base.get('band') or (lib_rec or {}).get('band'),
        'source': base.get('source') or (lib_rec or {}).get('source'),
        'provenance': base.get('provenance') or (lib_rec or {}).get('provenance'),
        'rest_only_status': sub.rest_status,
        'library_only_status': sub.library_status,
        'subject_declared': decl['declared'],
        'subjects_declared': [s for s in ('rest', 'library') if decl[s]],
        'subjects_evaluated': sub.evaluated,
        'subject_not_evaluated': ({k: v for k, v in sub.not_evaluated.items() if v} or None),
        'subject_not_applicable': ({k: v for k, v in sub.not_applicable.items() if v} or None),
        'detail': {'rest': base.get('detail'), 'rest_record': rest_record, 'library': lib_rec},
    }
