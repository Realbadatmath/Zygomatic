# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GATES rows, tier 5.

Moved verbatim out of the old single-file gates.py (lines 7841-8402).
"""

from zyg_workflows.geom.anthro.gates.policy import CANON, CANON_VS_MEASURED_CONFLICT, EV_PHALANX_SERIES, HOUSE, MEASURED
from zyg_workflows.geom.anthro.gates.bands import (
    CAL_DECLARED_BAND,
    CANNOT_FAIL_NOTE,
    SEVERITY_REJECTION_CEILING,
    _printed_band,
    _structural,
)
from zyg_workflows.geom.anthro.gates.gate import Gate
from zyg_workflows.geom.anthro.gates.tier5_form import _section_gate, t5_neck_section
from zyg_workflows.geom.anthro.gates.tier5_gates import (
    AFS_HEAD_UNITS_CHART,
    FAT_INVARIANT_SOURCE,
    PL_STIFFNESS_FLOOR_DEG,
    _angle_gate,
    _digit_gate,
    _pose_gate,
    t5_canon_head_units,
    t5_head_landmark_relief,
    t5_landmark_relief,
)


GATES_TIER_5 = (
    # -- Tier 5 — form, angle, section, relief and pose --------------------------
    # Severity policy in this tier, stated once. A gate whose subject is OUR RIG or OUR
    # REGISTRY declares _structural() and keeps its blocking claim. A gate whose subject
    # is the SHAPE OF A PERSON and whose number comes off a page declares _printed_band()
    # and is DOWNGRADED to warn by calibrate_gate, automatically, because a printed number
    # has no population behind it and a gate that cannot say how many real people it
    # rejects may not block. The two MEASURED thresholds in the tier (integer bone counts;
    # the phalanx-ratio bands from two published radiographic series) keep their blocking
    # claim, and the second of them FAILS on every body including the control — which is
    # the finding, and is not a reason to widen anything.
    Gate(
        't5_joint_rom',
        5,
        'block',
        'every rig joint sits inside its printed range of motion',
        {
            'wrist_extension_deg': 90.0,
            'wrist_flexion_deg': 90.0,
            'ulnar_deviation_deg': 40.0,
            'radial_deviation_deg': 20.0,
            'cervical_extension_total_deg': 85.0,
        },
        CANON,
        'CANON — Anatomy For Sculptors p.181-182 (wrist extension 0-45 natural / 45-90 '
        'forced, flexion 0-50 / 50-90, ulnar deviation <=40, radial <=20) and Form of the '
        'Head and Neck p.161 (total cervical extension <=85 deg, 15-20 deg per joint). '
        'Printed degrees: widening any of them requires contradicting a page, not a run '
        'of our meshes. '
        'SUBJECT CORRECTED 2026-08-06: this gate was evaluated on the REST A-POSE ALONE '
        'until then, where all-zero axis-angle makes "0 of 11 ROM sub-checks failed" a '
        'property of the pose it was handed rather than a verdict — a blocking rubber '
        'stamp (D3 / F3 / calibration finding 6). It now runs on both declared subjects '
        'via pose_limits.pose_layer(), and on the fitted poses this pipeline actually '
        'ships to the VACE control channel it FAILS: 44 of 44 on abel, 43 of 43 on '
        'cornelis, worst sub-check occiput_c2_share_yaw. That rate is a finding about our '
        'poses. It is not a reason to widen a printed degree.',
        _pose_gate('t5_joint_rom'),
        quantities=(
            'wrist_extension_deg',
            'wrist_flexion_deg',
            'ulnar_deviation_deg',
            'radial_deviation_deg',
            'cervical_extension_total_deg',
        ),
        calibration=_structural(
            'the subject is a JOINT ANGLE in our own rig and in our own fitted pose '
            'library, not a proportion of a person. ANSUR II measures no joint range at '
            'all — verified in code by geom.pose_limits.ansur_rom_columns(), which finds '
            'none — so no rejection rate against the reference sample can exist for it, '
            'and its absence is a fact about the survey rather than a gap in this gate.'
        ),
    ),
    Gate(
        't5_pronation_isolation',
        5,
        'block',
        'driving pronation produces zero humerus rotation',
        {'humerus_rotation_deg': 0.0},
        CANON,
        'CANON — AFS p.149: pronation is a forearm event; the radius rolls around a fixed '
        'ulna and the humerus does not rotate. Zero is zero: there is no tolerance here '
        'to widen. '
        'SUBJECT CORRECTED 2026-08-06, and the correction is NOT a second scored claim. '
        'The driven-rotation half is scored on the rig as before, and its PASS is '
        'disclosed as constructive (forward kinematics cannot propagate a child rotation '
        'to a parent, so a zero here is close to guaranteed). The fitted-library half is '
        'now evaluated and REPORTED, not scored: on an authored pose the humeral rotation '
        'belonging to the POSE cannot be separated from the rotation used to explain '
        'pronation without a coupling threshold, and no printed source gives one. The '
        'coupling is published in full instead — abel mean |humeral twist| 7.28 deg '
        'against |forearm twist|, Pearson r -0.58; cornelis 13.62 deg. Manufacturing a '
        'threshold so that this could FAIL would be the same offence as widening one so '
        'it could PASS.',
        _pose_gate('t5_pronation_isolation'),
        quantities=('humerus_rotation_under_pronation_deg',),
        calibration=_structural(
            'an invariance of OUR skinning and OUR bone hierarchy '
            'under a driven rotation. The reference sample contains '
            'no rigs.'
        ),
    ),
    Gate(
        't5_scapula_static',
        5,
        'warn',
        'the scapula stays static below 90 deg of humeral abduction',
        {'scapula_rotation_deg_below_90': 0.0},
        CANON,
        'CANON — AFS p.90. Declared at warn because warn is what would govern anyway: the '
        'calibration is CAL_PRINTED_BAND (a drawing has no sample), and calibrate_gate '
        'strips a blocking claim from every printed-band gate automatically. MEASURED '
        '2026-08-06 by re-declaring this gate at block: effective severity comes back '
        '"warn" — as it does for gonial, subcostal, carrying, nasolabial and orbital. '
        'CORRECTION 2026-08-06: the reason previously shipped here — that a blocking '
        'claim "would add a permanent false blocking-check-did-not-run to every report" — '
        'was factually wrong and described machinery that does not exist. unrun_blocking '
        'is computed off the EFFECTIVE severity (report.py), which would already have '
        'been warn. The severity choice was harmless; the reasoning beside it is what an '
        'auditor reads. The real reason this gate never resolves is that the anny rig HAS '
        'NO SCAPULA BONE, verified by name search over all 163 bones. ' + CANNOT_FAIL_NOTE,
        _pose_gate('t5_scapula_static'),
        quantities=('scapula_rotation_deg',),
        calibration=_printed_band(
            'AFS p.90 is a drawing. No survey measures scapular rhythm, so no rejection rate exists.', 'AFS p.90'
        ),
    ),
    Gate(
        't5_elbow_owner',
        5,
        'block',
        'the olecranon patch is rigid in the FOREARM frame, not the upper-arm frame',
        {'owner': 'forearm'},
        CANON,
        'CANON — AFS p.156: the olecranon belongs to the ulna and travels with the '
        'forearm. A comparative residual between two frames: the gate has no threshold to '
        'tune, only a winner to name. '
        'WHAT ITS PASS IS AND IS NOT, measured 2026-08-06 (D7). Handed '
        "patch='epicondyle_lat' — an unambiguously HUMERAL landmark — the same "
        'discriminator still answers lowerarm01.L and still returns pass: residual 54.75 '
        'mm in the humerus frame against 0.0 mm in the forearm frame, skin ownership '
        '97.5% lowerarm01.L / 2.5% lowerarm02.L / 0% upperarm02.L. Same for '
        'epicondyle_med. So the discriminator answers "forearm" on BOTH sides of the '
        'elbow, and the PASS on the olecranon confirms only that the olecranon patch is '
        'skinned to the forearm — which is what the rig already says. It distinguishes '
        'nothing about this rig at the elbow. It does discriminate ACROSS LIMB SEGMENTS: '
        'handed acromion or patella it FAILs, verified. Read the pass as "the skinning is '
        'not grossly mis-segmented", not as evidence that the olecranon is modelled on '
        'the ulna. (The module additionally hardcodes the words "the olecranon patch" in '
        'its verdict text regardless of the patch argument; that string is '
        "pose_limits.py's and is reported here rather than paraphrased.)",
        _pose_gate('t5_elbow_owner'),
        quantities=('olecranon_frame_owner',),
        calibration=_structural(
            'a comparison of two skinning frames on our own cage. Nothing about a person is being rejected.'
        ),
    ),
    Gate(
        't5_patellar_ligament',
        5,
        'block',
        'patella-to-tibial-tuberosity distance is invariant through the knee range',
        {'max_drift_frac': 0.02, 'claim': 'invariance (no printed number)'},
        HOUSE,
        'HOUSE, on a CANON claim — and the split is the correction. AFS p.208 states an '
        'INVARIANCE: the patellar ligament holds the patella at a fixed distance from the '
        'tibial tuberosity through the entire knee range. The page prints NO tolerance. '
        'This gate previously shipped the sentence "the 2% is the printed tolerance", '
        'which was false (calibration finding 7): 0.02 is OUR operationalisation of the '
        'word "fixed" and therefore HOUSE, and the composite threshold is tagged at the '
        'weaker of its two provenances. HONEST DERIVATION OF THE 0.02, and why it does '
        "not matter: the rig's own numerical noise on this measurement is ~1e-6 of the "
        'distance, and the MEASURED drift on the five shipped bodies is 10.17% to 27.32% '
        '(abel -15.54% at 120 deg, cornelis +16.42% at 75, male -10.17% at 120, female '
        '+27.32% at 90, neutral +16.86% at 75). Every tolerance between the noise floor '
        'and 0.10 therefore returns the identical verdict on all five — FAIL — so the '
        'number is a label on a finding, not a knob that decides it. The CLAIM being '
        'tested is the invariance, which has no free parameter at all.',
        _pose_gate('t5_patellar_ligament'),
        quantities=('patella_tibial_tuberosity_distance_drift',),
        calibration=_structural(
            'the subject is OUR SKINNING SOLVE: the measured cause is that the patella '
            'patch is weighted 82.0% to upperleg02 (the femur), so it rides the thigh '
            'instead of the shin. A skinning weight is a property of our rig and no '
            'survey of people has a rejection rate for one.'
        ),
    ),
    Gate(
        't5_pose_stiffness',
        5,
        'warn',
        "transverse-tilt diversity of this character's fitted pose library",
        {'transverse_tilt_sd_min_deg': PL_STIFFNESS_FLOOR_DEG},
        CANON,
        'CANON — Anatomy For Sculptors p.16 asks for a transverse-tilt standard '
        'deviation above 2 degrees with shoulder and hip tilts of opposite sign; p.175 '
        'names three pose errors (elbows locked at exactly 90 or 180 degrees, fully '
        'extended finger chains in a relaxed hand, left and right forearms parallel); '
        'p.19 gives a five-configuration pose taxonomy. '
        'REGISTERED CORRECTLY 2026-08-06. This gate previously called '
        'pose_limits.pose_library_report() — the ROM census — and not '
        'pose_limits.t5_pose_stiffness(), the statistic it is titled, sourced and '
        'registered for (D2 / calibration finding 3). It also read two keys '
        '(n_violating, violating) that pose_library_report has never returned, so the '
        'one number it existed to print rendered as "ROM-violating None" while the '
        'measured rate was 1.0 (D1 / F2). It now consumes pose_layer(), whose dict '
        'contract is machine-verified, and the transverse-tilt standard deviation is '
        "scored against AFS p.16's PRINTED 2 degree floor. Severity raised report->warn "
        'because the gate can now actually reach a verdict; the ROM violation rate lives '
        'on t5_joint_rom, whose subject it is, and is not attached here.',
        _pose_gate('t5_pose_stiffness'),
        quantities=(
            'transverse_tilt_sd_deg',
            'elbow_locked_fraction',
            'forearms_parallel_fraction',
            'straight_finger_chain_fraction',
        ),
        calibration=_structural(
            'the subject is OUR POSE LIBRARY — a set of files this pipeline authored — '
            'and not the shape of a person. No survey has a rejection rate for the '
            "standard deviation of the shoulder tilts in somebody else's animation "
            'set, and its absence is a fact about surveys rather than a gap here.'
        ),
    ),
    Gate(
        't5_torso_sections',
        5,
        'block',
        'torso cross-sections: width > depth, front flatter than back, a gluteal concavity',
        {'width_over_depth': '>1', 'front_back_curvature': '<1', 'gluteal_concavities': '>=1'},
        CANON,
        'CANON — AFS p.24 (torso cross-sections). Pure sign tests and one integer count: '
        'there is no tolerance in this gate to calibrate on our own mesh. The relief floor '
        "the concavity count is measured against is geom.form.curvature's own MEASURED "
        'null (2.45e-3 of stature), not a number from the book.',
        _section_gate('t5_torso_sections'),
        quantities=('torso_width_over_depth', 'torso_front_back_curvature', 'gluteal_concavity_count'),
        calibration=_printed_band(
            'AFS p.24 is a drawing of a cross-section. Nobody has surveyed the ratio of '
            'anterior to posterior torso curvature, so no rejection rate exists and the '
            'blocking claim is taken away here rather than argued about.',
            'AFS p.24',
        ),
    ),
    Gate(
        't5_neck_section',
        5,
        'block',
        'neck cross-section: hexagonal not circular, spine posterior, sex-correct taper',
        {
            'hex_beats_circle': True,
            'circularity_max': 0.9069,
            'spine_posterior_mm': '>0',
            'taper': 'male ~1.0, female <1.0',
        },
        CANON,
        'CANON — Form of the Head and Neck p.106-107 (the neck is a hexagonal prism, not '
        'a cylinder), p.172-173 (male cylindrical vs female conical taper). The '
        'circularity ceiling 0.9069 is not a tuned number: it is 4*pi*A/P^2 of a REGULAR '
        'HEXAGON, i.e. pi*sqrt(3)/6, arithmetic with no free parameter. '
        "SEX CLAIM WIRED IN 2026-08-06 (calibration finding 5). The module's `taper` "
        'claim is REPORT-only and its own explanation told the reader that "the sex '
        'signal is gated by the paired direction test in neck_taper_dimorphism()" — a '
        "function whose only caller in the repository was sections.py's CLI printout. "
        'The parameter-free form of the claim was therefore in no gate at all, and the '
        'HeadNeck p.172/173 sex claim could not fail on any character we ship. It is now '
        'evaluated per subject (hold the recipe, flip ONLY the gender macro, require the '
        "female neck to taper more) and rolled into this gate's status.",
        t5_neck_section,
        quantities=(
            'neck_hex_beats_circle',
            'neck_circularity',
            'neck_spine_posterior_mm',
            'neck_taper_ratio',
            'neck_taper_sex_dimorphism',
        ),
        calibration=_printed_band(
            'the pack DOES ship neck_circumference_over_stature, and this gate '
            'deliberately does not touch it: a circumference is structurally blind to '
            'whether the section is a hexagon or a circle. The SHAPE claims here have no '
            'survey behind them at all.',
            'HeadNeck p.106-107, p.172-173',
        ),
    ),
    Gate(
        't5_leg_counter_curve',
        5,
        'block',
        'the leg centroid track alternates lateral and medial rather than bowing once',
        {'sign_changes': '>=1'},
        CANON,
        'CANON — AFS p.215: the leg is a counter-curve, not a single bow. An integer count '
        'of sign changes in the centroid residual from the ankle-crotch chord. There is '
        'no threshold: zero sign changes is zero.',
        _section_gate('t5_leg_counter_curve'),
        quantities=('leg_centroid_sign_changes',),
        calibration=_printed_band(
            'AFS p.215 is a drawing. No survey records the sign pattern of a leg centroid track.', 'AFS p.215'
        ),
    ),
    Gate(
        't5_calf_asymmetry',
        5,
        'block',
        'the medial gastrocnemius head sits lower AND larger than the lateral',
        {'medial_lower': True, 'medial_larger': True},
        CANON,
        'CANON — AFS p.216. Two direction tests, both parameter-free.',
        _section_gate('t5_calf_asymmetry'),
        quantities=('calf_medial_lower', 'calf_medial_larger'),
        calibration=_printed_band('a direction test off a drawing; no population rate exists for it.', 'AFS p.216'),
    ),
    Gate(
        't5_digit_chains',
        5,
        'block',
        'integer skeletal counts: 2 thumb phalanges, 3 per finger, 14 per hand',
        {'phalanges_per_hand': 14, 'metacarpals': 5, 'thumb_phalanges': 2},
        CANON,
        'CANON — integer skeletal counts printed at AFS p.179 and p.188, checked against '
        "the rig roster parsed from anny's own 163 bone names. RE-TAGGED 2026-08-06: "
        'this gate shipped as MEASURED while its only citation was two book pages, which '
        'is the exact bypass MEASURED_EVIDENCE_CLASSES now refuses — a page is CANON '
        'however the provenance field is typed, and validate_registry raises on it. '
        'Nothing about the check changed: these are integers, there is no tolerance to '
        'set and nothing that could be tuned to make our rig pass. It keeps block '
        'severity because its subject is OUR BONE ROSTER, which is a fact about the rig '
        'and not a proportion of a person, and because none of the quantities it names is '
        'in MEASURED_COVERED_QUANTITIES — no survey on disk counts phalanges.',
        _digit_gate('digit_chains'),
        quantities=(
            'phalanges_per_hand',
            'metacarpals_per_hand',
            'thumb_phalanges',
            'hallux_phalanges',
            'digit_surface_resolvable',
        ),
        calibration=_structural(
            'a hand either has fourteen phalanges or it does not. '
            'There is no rejection rate to estimate and no width to '
            'widen, and the subject is our bone roster, not a body.'
        ),
    ),
    Gate(
        't5_phalanx_ratio',
        5,
        'block',
        'phalanx segment ratios against two independent radiographic series',
        {'bands': 'mean +/- 3 SD, per digit, mid/prox and dist/mid'},
        MEASURED,
        'MEASURED — Buryanov & Kotiuk 2010 (n=66) and Hamilton & Dunsmuir 2002 (n=197, '
        "joint centres, the rig's own convention). Two independent published series that "
        'agree with each other to 0.014 and disagree with this rig by 0.14-0.16. Nothing '
        'in the band was fitted to any anny mesh.',
        _digit_gate('phalanx_ratio'),
        calibration={
            'kind': CAL_DECLARED_BAND,
            'why': 'the band is mean +/- 3 SD of two published radiographic '
            'series. A 3-SD band rejects 0.27%% of a normal population BY '
            'CONSTRUCTION, which is inside the %.0f%% ceiling, and that '
            'rate is a property of how the band was built rather than '
            'something to be measured against ANSUR. It CANNOT be '
            'measured against ANSUR: ANSUR II ships no phalanx lengths, '
            'so the reference population for this gate is a hand-bone '
            'series and not the soldier sample.' % (100.0 * SEVERITY_REJECTION_CEILING),
            'per_band_by_construction': 0.0027,
            'n': 263,
            'source': 'Buryanov & Kotiuk 2010 n=66; Hamilton & Dunsmuir 2002 n=197',
        },
        evidence=EV_PHALANX_SERIES,
    ),
    Gate(
        't5_child_hand',
        5,
        'warn',
        'child hand form: thicker fingers, knuckle relief near zero, hand:head below adult',
        {
            'finger_thickness': 'above the adult value',
            'knuckle_relief': '~0',
            'hand_over_head': 'below the adult ratio',
        },
        CANON,
        "CANON — AFS p.185 (children's fingers are proportionally thicker) and p.178 "
        "(hand:head below the adult ratio). Direction claims against this pipeline's own "
        'adult reference body, not absolute numbers.',
        _digit_gate('child_hand'),
        quantities=('finger_thickness_over_length', 'knuckle_relief_mm', 'hand_over_head_length'),
        calibration=_printed_band(
            'a direction claim off a drawing; the surveys on disk '
            'measure hand LENGTH for age and say nothing about '
            'finger diameter or knuckle relief.',
            'AFS p.178, p.185',
        ),
    ),
    Gate(
        't5_canthal_tilt',
        5,
        'block',
        'canthal tilt is slightly positive and does not exceed +10 deg',
        {'ceiling_deg': 10.0},
        CANON,
        'CANON — Form of the Head and Neck p.43. A ONE-SIDED rule: the tilt is slightly '
        'positive and does not exceed about +10 deg, and the tolerance IS the width. '
        'Which eye corner is lateral is MEASURED per mesh, not read off the target label. '
        'BAND CORRECTED 2026-08-06 (calibration finding 1). This gate DECLARED [0, +10] '
        "and ENFORCED [-10, +10]: the adapter discarded the module's own band_verdict "
        'and scored the row off ceiling_verdict = |tilt| <= 10 alone. A body with a '
        'resolved -9.9 deg tilt — the slant the page rules out — passed, and the control '
        'shipped as PASS/ok while sitting outside its own declared band at -0.108 deg. '
        'The enforced rule is now: FAIL on |tilt| > 10, FAIL on a RESOLVED NEGATIVE sign, '
        'and PASS with the sign half NAMED AS UNSCORED when the operationalisations '
        'straddle zero. The control still passes — on the honest ground that its sign is '
        'unresolved, not on a band twice the printed width.',
        _angle_gate('canthal_tilt'),
        quantities=('canthal_tilt_deg',),
        calibration=_printed_band(
            'HeadNeck p.43 prints a ceiling with no sample behind it. ANSUR measures no facial angle.', 'HeadNeck p.43'
        ),
    ),
    Gate(
        't5_ear_nose_parallelism',
        5,
        'block',
        'the ear axis is parallel to the nose dorsum within ~8 deg',
        {'max_delta_deg': 8.0},
        CANON,
        'CANON — Form of the Head and Neck p.69. Resolved on all five bodies (two '
        'independent ear anchors agree to 0.01 deg) and FAILED on all five.',
        _angle_gate('ear_nose_parallelism'),
        quantities=('ear_axis_vs_nose_dorsum_deg',),
        calibration=_printed_band(
            'a printed parallelism tolerance; no survey measures ear axis against nasal dorsum.', 'HeadNeck p.69'
        ),
    ),
    Gate(
        't5_gonial_angle',
        5,
        'warn',
        'the mandibular (gonial) angle, the sharpest sex gate in the corpus',
        {'male_adult': [100.0, 120.0], 'female_adult': [120.0, 140.0], 'newborn': [135.0, 150.0]},
        CANON,
        'CANON — Form of the Head and Neck p.15 AND, independently, FacialExpr p.26: the '
        'only cross-book-confirmed number in the corpus, with non-overlapping adult bands '
        'and a monotone age curve. Declared at warn because on THIS rig it cannot resolve: '
        'the `jaw` bone is a single midline hinge segment (the condylion-menton chord) '
        'with no corner, and the surface fallback spreads 45.6-78.9 deg against a 15 deg '
        'band width. The evidence for the refusal travels in the gate record. ' + CANNOT_FAIL_NOTE,
        _angle_gate('gonial_angle'),
        quantities=('gonial_angle_deg',),
        calibration=_printed_band(
            'two books agreeing is still not a sample. No survey on disk measures a mandibular angle.',
            'HeadNeck p.15 / FacialExpr p.26',
        ),
    ),
    Gate(
        't5_subcostal_angle',
        5,
        'warn',
        'the subcostal angle at the xiphoid, ~90 deg male vs ~60 deg female',
        {
            'printed_male_adult_deg': 90.0,
            'printed_female_adult_deg': 60.0,
            'half_width_deg': 12.0,
            'band_male_adult': [78.0, 102.0],
            'band_female_adult': [48.0, 72.0],
        },
        HOUSE,
        'HOUSE, on CANON centres — and the split is the correction (calibration finding '
        '7). AFS p.13 prints TWO SINGLE VALUES, ~90 deg male and ~60 deg female, and the '
        'authentic content of the page is the 30 deg male-female SEPARATION. It prints no '
        'band and no dispersion. The +/-12 deg half-width that turns those values into '
        "[78,102] and [48,72] is OURS: it came from this package's own plan document, so "
        'sourcing it to "the plan" is a circular citation and under rule 5 it has no '
        'external source at all. The centres stay CANON; the width is HOUSE; the '
        'composite is tagged at the weaker of the two, and the printed values are carried '
        'in the threshold beside the derived band so a reader can see which is which. '
        'This changes no verdict: the gate is UNRESOLVED on every body, because the '
        "costal margin does not exist on this cage — a relief sweep clears the cage's "
        'own null p99 on 0 of 325-348 probed vertices, strongest +1.14 to +3.29 mm '
        'against the ~4.13 mm the null demands. ' + CANNOT_FAIL_NOTE,
        _angle_gate('subcostal_angle'),
        quantities=('subcostal_angle_deg',),
        calibration=_printed_band(
            'AFS p.13 prints two single values. There is no sample, and the width around them is ours.', 'AFS p.13'
        ),
    ),
    Gate(
        't5_carrying_angle',
        5,
        'warn',
        'the carrying angle, humerus against forearm, 5-15 deg with female > male',
        {'band_deg': [5.0, 15.0], 'direction': 'female > male'},
        CANON,
        'CANON — AFS p.176. The band is printed and the sex term is a DIRECTION test with '
        'no threshold at all. Both preconditions of the definition (full extension, '
        'forearm supinated) are properties of the POSE, so a mesh in any other pose is '
        "outside the band's domain no matter what number the geometry yields — and "
        '_p_angles only ever hands this gate the REST mesh, whose elbow is flexed '
        '34.9-38.6 deg on the five shipped bodies with supination unreadable. ' + CANNOT_FAIL_NOTE,
        _angle_gate('carrying_angle'),
        quantities=('carrying_angle_deg',),
        calibration=_printed_band('AFS p.176; no survey on disk measures a carrying angle.', 'AFS p.176'),
    ),
    Gate(
        't5_nasolabial_angle',
        5,
        'warn',
        'the nasolabial angle, 92-98 deg male / 95-105 deg female',
        {'male_adult': [92.0, 98.0], 'female_adult': [95.0, 105.0]},
        CANON,
        'CANON — Form of the Head and Neck p.77. The columella, which the angle is '
        'defined from, is absent from the 256-label landmark vocabulary. ' + CANNOT_FAIL_NOTE,
        _angle_gate('nasolabial_angle'),
        quantities=('nasolabial_angle_deg',),
        calibration=_printed_band('printed bands with no sample.', 'HeadNeck p.77'),
    ),
    Gate(
        't5_orbital_long_axis',
        5,
        'warn',
        'the long axis of the bony orbit sits ~20 deg from horizontal',
        {'target_deg': 20.0},
        CANON,
        'CANON — FacialExpr p.20. A BONY quantity: the orbital aperture, which a skin '
        'surface can only approximate, and which has no landmark on this cage. ' + CANNOT_FAIL_NOTE,
        _angle_gate('orbital_long_axis'),
        quantities=('orbital_long_axis_deg',),
        calibration=_printed_band('printed single value with no sample.', 'FacialExpr p.20'),
    ),
    Gate(
        't5_landmark_relief',
        5,
        'block',
        'the bony landmarks visible at EVERY bodyfat show relief on this cage',
        {'fat_invariant_probes_with_no_relief': 0},
        CANON,
        FAT_INVARIANT_SOURCE,
        t5_landmark_relief,
        quantities=('bony_landmark_relief_frac_stature',),
        calibration=_printed_band(
            'AFS p.63 says WHICH regions must show relief and says nothing about how '
            "much. The amplitude cut in force is geom.form.ridge's own measured null, "
            'which is a false-positive rate and not a population rejection rate: it says '
            'how often ORDINARY SKIN would fake a landmark, not how many people would be '
            'rejected. So this gate cannot state a rejection rate and does not block.',
            'AFS p.63, p.193-194; cut from ridge.RIDGE_NULL_P99',
        ),
    ),
    Gate(
        't5_head_landmark_relief',
        5,
        'report',
        'relief on the 12 head/neck windows, reported against a body-calibrated floor',
        None,
        None,
        None,
        t5_head_landmark_relief,
        calibration=_structural(
            'report-only, and deliberately so: the contrast floor these probes are scored '
            'against was measured on TORSO AND LIMB skin, and head features are broad '
            'enough that their own collar is curved. Gating on a floor known to have been '
            'calibrated on the wrong surface is the calibration error this package '
            'refuses; the numbers are printed with the caveat attached instead.'
        ),
    ),
    Gate(
        't5_canon_head_units',
        5,
        'report',
        'the AFS head-unit chart beside the measured head count — the CANON receipt',
        AFS_HEAD_UNITS_CHART,
        CANON,
        'CANON — Anatomy For Sculptors p.91-93. ' + CANON_VS_MEASURED_CONFLICT,
        t5_canon_head_units,
        quantities=('crotch_height_over_stature', 'stature_for_age'),
        calibration=_structural(
            'report-only BY POLICY, not by weakness of evidence: both quantities this '
            'chart constrains are answered by surveys on disk and the chart disagrees '
            'with both, so under the CANON rule it may be printed and may not gate. This '
            'row is the visible receipt of that rule — the same job '
            't4_canon_and_percentiles does for the 8-head drawing canon.'
        ),
    ),
)
