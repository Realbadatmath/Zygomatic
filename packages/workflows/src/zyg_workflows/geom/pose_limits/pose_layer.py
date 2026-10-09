# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""THE POSE LAYER — the single entry point a gate registry should call.

Moved verbatim out of the old single-file pose_limits.py (lines 3869-4598).
"""

from zyg_workflows.geom.pose_limits.base import (
    ROLLUP_RANK,
    SCHEMA,
    _set_threads,
    _threads,
    enabled,
    strict_wrist,
)
from zyg_workflows.geom.pose_limits.printed import canon_may_block
from zyg_workflows.geom.pose_limits.rig import bone_roster, rig_numerical_floor, rig_report
from zyg_workflows.geom.pose_limits.characters import (
    NEUTRAL,
    POSE_LIBRARY_CHARACTERS,
    characters,
    fit_mask_defect,
    pose_library_report,
    run_character,
)

# The record builders this entry point assembles its dict from. They moved to a sibling
# module on 2026-10-09 when pose_layer() hit 368 lines (the ratchet caps a function at
# 300); the import runs one way — pose_layer_records never imports this module.
from zyg_workflows.geom.pose_limits.pose_layer_records import (
    absent_library_report,
    gate_record,
    library_block,
    stiffness_over_set,
)


# =================================================================================
# THE POSE LAYER — the single entry point a gate registry should call.
#
# WHY IT EXISTS. run_character() measures the REST A-POSE. pose_library_report() measures
# the FITTED POSES WE ACTUALLY SHIP. Until this function the registry called only the
# first while its gate text claimed both, and the result was a blocking PASS for joint ROM
# on a body whose entire fitted library fails the identical gate 44/44. This function
# evaluates every subject a pose gate declares, publishes each subject's verdict
# separately, and rolls them up by a rule that is written down rather than implied.
# =================================================================================
POSE_LAYER_SCHEMA = 'geom.pose_limits/pose_layer/1'

# The roll-up order. Higher rank wins. Stated as data so it can be read, quoted and
# argued with, and so nothing can quietly re-order it inside a branch.
#   PASS < REPORT/SKIP < WARN < UNMEASURABLE/UNRESOLVED < FAIL < ERROR
# (ROLLUP_RANK and rollup() are defined with the status vocabulary near the top of this
# file, because pose_library_report() needs them too.)

# Which subjects each pose gate DECLARES, and — where a subject does not apply — the
# measured reason, not a shrug. `library_scored` says whether the library subject can
# produce a verdict at all; where it is False the reason is that NO PRINTED SOURCE GIVES A
# THRESHOLD for the quantity the library can supply, and inventing one would be the mirror
# image of widening a band.
POSE_LAYER_SUBJECTS = {
    't5_joint_rom': {
        'rest': True,
        'library': True,
        'library_scored': True,
        'declared': 'a joint angle, in the shipped rig rest pose AND in every fitted pose '
        'this character ships to the VACE control channel',
    },
    't5_pronation_isolation': {
        'rest': True,
        'library': True,
        'library_scored': False,
        'declared': 'humeral rotation under forearm pronation, driven on the rig AND '
        'observed in every fitted pose this character ships',
        'library_not_scored_because': 'on an authored/fitted pose the humerus rotation that belongs to the POSE '
        'cannot be separated from the humerus rotation that was used to EXPLAIN '
        'pronation without a coupling threshold, and no printed source gives one. The '
        'coupling is measured and published in full (mean humeral twist, mean forearm '
        'twist, Pearson r, count above the numerical floor) and carries status REPORT. '
        'Manufacturing a threshold so this could FAIL would be the same offence as '
        'widening one so it could PASS.',
    },
    't5_pose_stiffness': {
        'rest': False,
        'library': True,
        'library_scored': True,
        'declared': "the transverse-tilt diversity of this character's fitted pose SET, "
        "against AFS p.16's printed 2 deg standard-deviation floor",
        'rest_not_applicable_because': 'diversity is defined over a SET. One rest pose has a standard deviation of '
        'zero by construction and would be a fabricated failure, not a measurement.',
    },
    't5_scapula_static': {
        'rest': True,
        'library': False,
        'library_scored': False,
        'declared': 'scapular rotation below 90 deg of humeral abduction, on the rig',
        'library_not_applicable_because': 'the rig carries no scapula bone (rig_report().expected_absent). No pose can '
        'supply a subject the skeleton does not contain, so the fitted library adds '
        'nothing this gate could read.',
    },
    't5_elbow_owner': {
        'rest': True,
        'library': False,
        'library_scored': False,
        'declared': 'which frame — humerus or forearm — explains the olecranon patch, on '
        'the rig, across a driven flexion sweep',
        'library_not_applicable_because': 'this gate drives its own flexion sweep and compares two frames on the same '
        'patch, so it already exercises pose. Its subject is the rig SKINNING, which '
        'is a property of the model and is identical in every fitted pose.',
    },
    't5_patellar_ligament': {
        'rest': True,
        'library': False,
        'library_scored': False,
        'declared': 'the patella-to-tuberosity distance through a driven knee sweep, on the rig',
        'library_not_applicable_because': 'this gate drives its own knee sweep at 30/60/75/90/120 deg, which spans more '
        'flexion than the fitted library contains. Its subject is the rig SKINNING, '
        'identical in every fitted pose.',
    },
}

POSE_LAYER_CONTRACT = """geom.pose_limits.pose_layer() — THE PUBLISHED DICT CONTRACT.

Every key listed here is ALWAYS present. `None` means "not computed, and the record says
why"; it never means "fine". No key below is an alias for another: each is computed where
it is published.

TOP LEVEL
  schema                str   POSE_LAYER_SCHEMA
  character             str
  char_asset            str|None   the char_mesh asset whose library was read, or None
  side                  str
  stature_m             float
  anatomical_frame      dict
  rest_geometry         dict  elbow / knee / wrist at rest (as run_character())
  gates                 list[dict]  one ROLLED-UP record per gate, shape below
  gate_index            dict[str, dict]  the same records keyed by gate id
  library               dict  the library-subject block, ALWAYS present, shape below
  subjects_evaluated    list[str]  subset of ['rest', 'library']
  subjects_declared     dict  POSE_LAYER_SUBJECTS, carried so a reader can check the claim
  rollup_rule           str   the roll-up order, in words
  policy                str

GATE RECORD (each element of `gates`; also the value in `gate_index`)
  gate                  str   the gate id
  status                str   THE ROLL-UP over every subject this gate DECLARES. Render
                              this one if the registry text names both subjects.
  explain               str   one sentence naming every subject and its numbers
  observed              dict  the numbers that must survive a whitelist-flattening report
                              writer, which drops `detail` entirely. ALWAYS carries
                              rest_status, library_status, rest_observed. Then, per gate:
                                gates that do NOT declare the library ->
                                  library_subject = 'not applicable: <measured reason>'
                                gates that DO -> n_poses, library_complete, plus the
                                numbers THEIR OWN subject produced:
                                  t5_joint_rom           n_violating, n_warning,
                                                         violation_rate, worst_check,
                                                         worst_check_fail_count
                                  t5_pronation_isolation library_humerus_twist_deg_abs_mean,
                                                         library_forearm_twist_deg_abs_mean,
                                                         library_pearson_r_forearm_vs_humerus,
                                                         library_n_arms, library_not_scored
                                  t5_pose_stiffness      shoulder_tilt_sd_deg,
                                                         hip_tilt_sd_deg,
                                                         transverse_tilt_sd_min_deg,
                                                         tilt_opposition_fraction,
                                                         tilt_opposition_required_fraction,
                                                         tilt_n_same_sign,
                                                         tilt_n_sign_evaluated,
                                                         tilt_n_same_sign_allowed,
                                                         tilt_opposition_rule_drift,
                                                         tilt_same_sign_by_floor_deg,
                                                         scored_check_status,
                                                         elbow_locked_fraction_by_window_deg,
                                                         forearms_parallel_fraction_by_window_deg,
                                                         erect_fraction_by_trunk_window_deg,
                                                         fully_straight_finger_chain_fraction
                              The ROM violation rate is never attached to a gate whose
                              subject is the rig skinning — that would be a different
                              dishonesty from hiding it.
  band                  dict  printed band, from the rest record, else the library record
  source                str   the printed pages
  provenance            str   CANON / HOUSE
  rest_only_status      str|None   the REST-POSE verdict alone.
        *** Rendering rest_only_status as the gate verdict re-creates finding F3 unless
        the registry text is narrowed at the same time to claim the rest pose ONLY. It is
        published so the split is visible, not so the harder subject can be dropped. ***
  library_only_status   str|None   the FITTED-LIBRARY verdict alone
  subject_declared      str   prose, from POSE_LAYER_SUBJECTS
  subjects_declared     list[str]  subset of ['rest', 'library']
  subjects_evaluated    list[str]  subset of subjects_declared
  subject_not_evaluated dict|None  {subject: reason} for a DECLARED subject that could not
                              be evaluated. Each one contributes UNRESOLVED to the roll-up.
                              Never empty when a declared subject was skipped.
  subject_not_applicable dict|None {subject: measured reason} for a subject this gate never
                              claimed (e.g. the library for t5_elbow_owner, whose subject
                              is the rig skinning). Contributes nothing to the roll-up.
  detail                dict  {'rest': <the rest record's detail>,
                               'rest_record': <the full rest _res record or None>,
                               'library': <the library record or None>}

LIBRARY BLOCK (`library`)
  status                str   measured library verdict, or UNRESOLVED when absent
  present               bool
  complete              bool  False the moment one matched file failed to load
  char_asset            str|None
  n_files_found         int
  n_poses               int   poses actually measured == rate_denominator
  rate_denominator      int
  n_violating           int|None   poses whose t5_joint_rom status is FAIL
  n_warning             int|None
  n_passing             int|None
  violation_rate        float|None n_violating / rate_denominator
  warn_rate             float|None
  status_counts         dict
  per_check_counts      dict  {sub-check: {'fail': n, 'warn': n}}
  worst_offenders       dict  {'by_check': [...], 'by_pose': [...]}, worst first, cap 10
  integrity             dict  the file accounting; names EVERY dropped file (F8)
  stiffness             dict|None  the real t5_pose_stiffness record over the SET
  pronation_coupling    dict|None
  occiput_share_failures_by_total_rotation  dict
  explain               str
  reason                str|None   present only when the library could not be read
  policy                str

THE ROLL-UP RULE, once: status = worst(subject statuses actually computed), under
ROLLUP_RANK, and a DECLARED subject that could not be evaluated contributes UNRESOLVED.
So a gate that passes on the rest pose and has no fitted library to check reports
UNRESOLVED, not PASS — half of what it claims to gate was never looked at.

THIS CONTRACT IS ENFORCED, NOT ASSERTED. The four key tuples below (POSE_LAYER_KEYS,
POSE_LAYER_GATE_KEYS, POSE_LAYER_LIBRARY_KEYS, POSE_LIBRARY_INTEGRITY_KEYS) are the
machine-readable form of this document, and verify_contract() runs on every pose_layer()
call: a key that appears in the returned dict but not in the tuple, or the reverse, raises
before the caller ever sees the record. A published contract whose keys are not the keys it
returns is the defect this whole entry point exists to close, so it cannot drift silently.
"""

# The contract, machine-readable. verify_contract() compares these against what
# pose_layer() actually returns, on every call.
POSE_LAYER_KEYS = (
    'schema',
    'character',
    'char_asset',
    'side',
    'stature_m',
    'anatomical_frame',
    'rest_geometry',
    'gates',
    'gate_index',
    'library',
    'subjects_evaluated',
    'subjects_declared',
    'rollup_rule',
    'policy',
)
POSE_LAYER_GATE_KEYS = (
    'gate',
    'status',
    'explain',
    'observed',
    'band',
    'source',
    'provenance',
    'rest_only_status',
    'library_only_status',
    'subject_declared',
    'subjects_declared',
    'subjects_evaluated',
    'subject_not_evaluated',
    'subject_not_applicable',
    'detail',
)
POSE_LAYER_LIBRARY_KEYS = (
    'status',
    'present',
    'complete',
    'char_asset',
    'n_files_found',
    'n_poses',
    'rate_denominator',
    'n_violating',
    'n_warning',
    'n_passing',
    'violation_rate',
    'warn_rate',
    'status_counts',
    'per_check_counts',
    'worst_offenders',
    'integrity',
    'incomplete_note',
    'stiffness',
    'pronation_coupling',
    'occiput_share_failures_by_total_rotation',
    'explain',
    'reason',
    'policy',
)
POSE_LIBRARY_INTEGRITY_KEYS = (
    'root',
    'pattern',
    'char_asset',
    'n_files_found',
    'n_loaded',
    'n_dropped',
    'complete',
    'dropped',
    'dropped_paths',
    'drop_reason_counts',
    'drop_reason_meanings',
    'expected_pose_aa_rows',
    'n_fit_ok_false',
    'fit_ok_false_paths',
    'rule',
)


class PoseLayerContractError(RuntimeError):
    """pose_layer() produced a dict that does not match its own published contract."""


def verify_contract(pl):
    """Raise unless `pl` has EXACTLY the keys POSE_LAYER_CONTRACT documents.

    Called at the end of every pose_layer(). Cheap (four set comparisons) and it is what
    makes the contract a fact rather than a promise: the defect this entry point replaces
    was a consumer reading two keys the producer never returned, and prose alone would not
    have caught it.
    """

    def _cmp(where, got, want):
        got, want = set(got), set(want)
        if got != want:
            raise PoseLayerContractError(
                '%s: contract says %s; the record has %s. Missing %s; unexpected %s.'
                % (where, sorted(want), sorted(got), sorted(want - got), sorted(got - want))
            )

    _cmp('pose_layer() top level', pl, POSE_LAYER_KEYS)
    _cmp('pose_layer()["library"]', pl['library'], POSE_LAYER_LIBRARY_KEYS)
    _cmp(
        'pose_layer()["library"]["integrity"]',
        {k: v for k, v in (pl['library']['integrity'] or {}).items() if k != 'limit_applied' and k != 'note_limit'},
        POSE_LIBRARY_INTEGRITY_KEYS,
    )
    for g in pl['gates']:
        _cmp('pose_layer() gate %r' % g.get('gate'), g, POSE_LAYER_GATE_KEYS)
    if set(pl['gate_index']) != {g['gate'] for g in pl['gates']}:
        raise PoseLayerContractError('gate_index does not index every record in gates')
    return True


def pose_layer(name, phenotype, local_changes=None, side='l', char_asset=None, limit=None, world_up=None):
    """Evaluate every pose gate on EVERY SUBJECT IT DECLARES, and roll them up.

    See POSE_LAYER_CONTRACT (module constant, printable) for the exact dict this returns.
    That string is the contract; this docstring is the reason it exists.

    THE DEFECT THIS CLOSES. The registered ROM and pronation gates ran on the rest A-pose
    only, where passing is structural, while their registry text claimed the subject was a
    joint angle "in our own rig AND IN OUR OWN FITTED POSE LIBRARY". Measured on the
    shipped assets at the time of writing:

        t5_joint_rom            rest pose: PASS, "0 of 11 ROM sub-checks failed"
                                fitted library: violation_rate 1.0 — abel 44/44 FAIL,
                                cornelis 43/43 FAIL, against the printed AFS p.181-182 /
                                HeadNeck p.161 / p.171 bands
        t5_pronation_isolation  rest pose: PASS, humerus rotation ~1.7e-06 deg (and that
                                pass is CONSTRUCTIVE — forward kinematics cannot propagate
                                a child rotation to a parent)
                                fitted library: mean humeral twist 7.28 deg (abel), 13.62
                                deg (cornelis), Pearson r vs forearm twist -0.58 (abel)

    NOTHING IN HERE WIDENS A BAND. The 100% violation rate is the finding, and it is
    published as the headline number of the library block, in `explain`, and in every
    gate record's `observed` — the three places a whitelist-flattening report writer
    cannot drop it. If our poses fail the printed bands, the honest answer is that our
    poses fail the printed bands.

    COST. The library subject re-poses the rig once per fitted pose (44 and 43 poses on
    the two characters that have one) and is by far the expensive half. `limit` truncates
    it, and a truncated library is marked incomplete and cannot report a clean status.
    """
    _set_threads()
    if char_asset is None:
        char_asset = next((a for a, c in POSE_LIBRARY_CHARACTERS.items() if c == name), None)

    rest = run_character(name, phenotype, local_changes, side)
    rest_by_id = {g['gate']: g for g in rest['gates']}

    # ---- the library subject, computed once and shared by every gate that declares it
    lib_present = char_asset is not None
    if lib_present:
        rep = pose_library_report(char_asset, phenotype, local_changes, limit)
    else:
        rep = absent_library_report(name, len(bone_roster()[0]))

    # ---- the diversity statistic, over the SET. This is the real t5_pose_stiffness, the
    #      one carrying AFS p.16's printed 2 deg floor, and until now it was reachable only
    #      from run_all(with_pose_library=True), which no gate called (D2 / calibration 3).
    stiff = None
    if lib_present and rep.get('n_poses'):
        stiff = stiffness_over_set(char_asset, phenotype, local_changes, limit, world_up)

    library = library_block(rep, lib_present, char_asset, stiff)
    gates = [
        gate_record(gid, decl, rest_by_id.get(gid), library, rep, stiff)
        for gid, decl in sorted(POSE_LAYER_SUBJECTS.items())
    ]

    out = {
        'schema': POSE_LAYER_SCHEMA,
        'character': name,
        'char_asset': char_asset,
        'side': side,
        'stature_m': rest['stature_m'],
        'anatomical_frame': rest['anatomical_frame'],
        'rest_geometry': rest['rest_geometry'],
        'gates': gates,
        'gate_index': {g['gate']: g for g in gates},
        'library': library,
        'subjects_evaluated': (['rest'] + (['library'] if library['present'] else [])),
        'subjects_declared': POSE_LAYER_SUBJECTS,
        'rollup_rule': (
            'status = worst(subject statuses actually computed) under '
            'ROLLUP_RANK %s; a DECLARED subject that could not be evaluated '
            'contributes UNRESOLVED, so a gate that passes on the rest pose '
            'and has no fitted library to check reports UNRESOLVED, never '
            'PASS.' % ROLLUP_RANK
        ),
        'policy': (
            'the violation rate of our fitted pose library is a FINDING about our '
            'poses. It is not, and this module cannot make it, a reason to widen a '
            'printed band.'
        ),
    }
    verify_contract(out)  # the published keys ARE the returned keys, checked, always
    return out


def run_all(side='l', with_pose_library=True):
    if not enabled():
        return {'schema': SCHEMA, 'skipped': True, 'why': 'ZYG_POSE_LIMITS=0 — the whole module is switched off'}
    _set_threads()
    doc = {
        'schema': SCHEMA,
        'rig': rig_report(),
        'canon_policy': canon_may_block(),
        'numerical_floor': rig_numerical_floor(NEUTRAL),
        'env_flags': {
            'ZYG_POSE_LIMITS': enabled(),
            'ZYG_POSE_LIMITS_STRICT_WRIST': strict_wrist(),
            'ZYG_POSE_LIMITS_THREADS': _threads(),
        },
        'characters': [],
        'pose_layer': {},
    }
    # The whole run goes through pose_layer() so the CLI and the gate registry read the
    # SAME verdicts. `characters` keeps the rest-pose records for every existing consumer;
    # `pose_layer` carries the rolled-up ones and the library evidence behind them.
    for c in characters():
        if with_pose_library:
            pl = pose_layer(c['name'], c['phenotype'], c['local_changes'], side)
            doc['pose_layer'][c['name']] = pl
            doc['characters'].append(
                {
                    'character': c['name'],
                    'schema': SCHEMA,
                    'stature_m': pl['stature_m'],
                    'anatomical_frame': pl['anatomical_frame'],
                    'rest_geometry': pl['rest_geometry'],
                    'gates': [g['detail']['rest_record'] for g in pl['gates'] if g['detail'].get('rest_record')],
                }
            )
        else:
            doc['characters'].append(run_character(c['name'], c['phenotype'], c['local_changes'], side))
    if with_pose_library:
        doc['fit_mask_defect'] = fit_mask_defect()
        doc['pose_library'] = {ch: pl['library'] for ch, pl in doc['pose_layer'].items() if pl['library']['present']}
        doc['stiffness'] = {
            ch: pl['library']['stiffness'] for ch, pl in doc['pose_layer'].items() if pl['library'].get('stiffness')
        }
    return doc
