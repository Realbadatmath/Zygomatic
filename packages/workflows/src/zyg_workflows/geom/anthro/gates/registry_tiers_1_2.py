# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GATES rows, tiers 1 and 2.

Moved verbatim out of the old single-file gates.py (lines 7148-7590).
"""

from zyg_workflows.geom.anthro import integrity as IG
from zyg_workflows.geom.anthro import landmarks as LMK

from zyg_workflows.geom.anthro.gates.policy import (
    BUILD_TARGET_STATURE_TOL_MM,
    DIURNAL_STATURE_RANGE_MM,
    EV_ANSUR_II,
    HOUSE,
    MEASURED,
    MORPH_COEFF_ABS_MAX,
    STATURE_ANCHOR_SIGMA,
)
from zyg_workflows.geom.anthro.gates.bands import (
    AGE_CHANNEL,
    AGE_CHANNEL_BLOCKING_RATIOS,
    AGE_CHANNEL_SOURCE,
    ANCESTRY_LEG_RATIO,
    ANCESTRY_LEG_SOURCE,
    ANCESTRY_LEG_SPREAD,
    BREADTH_RATIOS,
    CAL_DECLARED_BAND,
    CAL_EMPIRICAL_PERCENTILE,
    CAL_LMS_Z,
    CAL_STATURE_ANCHORED,
    CAL_VIOLATION_RATE,
    CAST_VECTOR_COMPONENTS,
    CDC_Z_FAIL,
    CDC_Z_WARN,
    CHILD_DIRECTION_SOURCE,
    GIRTH_CHAIN_SOURCE,
    GIRTH_RATIOS,
    HARD_HEIGHT_CHAIN,
    HEIGHT_CHAIN_SOURCE,
    SOFT_HEIGHT_CHAIN,
    TIGHT_HEIGHT_PAIRS,
    _bands,
    _structural,
)
from zyg_workflows.geom.anthro.gates.gate import Gate
from zyg_workflows.geom.anthro.gates.tier1 import (
    GIRTH_STEPS,
    _integrity_gate,
    t1_build_target_stature,
    t1_euler_genus,
    t1_girth_chain,
    t1_landmark_ordering_hard,
    t1_landmark_ordering_soft,
    t1_morph_bounds,
    t1_self_intersection,
    t1_self_intersection_locality,
    t1_shell_containment,
)
from zyg_workflows.geom.anthro.gates.tier2 import (
    t2_adult_age_channel,
    t2_ancestry_cormic,
    t2_ancestry_leg,
    t2_breadths_wide,
    t2_child_growth,
    t2_child_proportions,
    t2_girths_wide,
    t2_heights_tight,
    t2_mahalanobis,
    t2_vhi_bmi,
)


GATES_TIERS_1_2 = (
    # -- Tier 1 ---------------------------------------------------------------
    Gate(
        't1_topology_identity',
        1,
        'block',
        'cage vertex/face count matches the declared scope',
        IG.TOPOLOGY_SCOPES['full'],
        HOUSE,
        'HOUSE — RE-TAGGED 2026-08-06 (re-review R5). 13718 vertices / 13710 quads / 4 '
        'components is a CENSUS OF OUR OWN CAGE, not a measurement of people, and the '
        'refusal in validate_registry() says in as many words what to do with a number '
        'like this: "tag the gate CANON if the number came off a page and HOUSE if it is '
        'ours". It shipped as MEASURED, and it could only ship as MEASURED because the '
        'previous wave invented an evidence class (own_assets) whose own population '
        'string read "Not a population of people: a census of our own output" — the '
        'ENFORCED definition of MEASURED widened until it no longer matched the DECLARED '
        'one, to admit this one gate. The class is withdrawn (see '
        'WITHDRAWN_EVIDENCE_CLASSES) and this is HOUSE. What it costs and what it buys: '
        'PROVENANCE_RANK ranks MEASURED above CANON, so a fact about our repository was '
        'being ranked as the strongest evidence in the file, and the census reported '
        'MEASURED=13 where the survey-backed count is 12. Nothing about the CHECK '
        'changes — it is still an exact integer identity on the shipped cage at block '
        'severity, and it still cannot be widened, because there is no band. '
        'The measurement behind the numbers, unchanged and still true: '
        + str(IG.TOPOLOGY_SCOPES['full']['provenance']),
        _integrity_gate('topology_identity'),
        calibration=_structural(
            'a vertex count is an identity check on the cage we shipped, not a proportion drawn from a population'
        ),
    ),
    Gate(
        't1_watertight',
        1,
        'block',
        'closed surface',
        {'boundary_edges': 0},
        HOUSE,
        'HOUSE: a body shell that is not closed has no volume and no cross-section',
        _integrity_gate('watertight'),
        calibration=_structural('mesh topology; no real person is rejected by it'),
    ),
    Gate(
        't1_edge_manifold',
        1,
        'block',
        'every edge has exactly two faces',
        {'nonmanifold_edges': 0},
        HOUSE,
        'HOUSE: the plane-slice girth algorithm in measure.py requires edge-manifoldness '
        'to close its contours without a distance tolerance',
        _integrity_gate('edge_manifold'),
        calibration=_structural('mesh topology; no real person is rejected by it'),
    ),
    Gate(
        't1_vertex_manifold',
        1,
        'block',
        'every vertex link is a single closed cycle',
        {'pinch_vertices': 0},
        HOUSE,
        'HOUSE: a pinch vertex passes both watertight and edge-manifold and still breaks any region flood-fill',
        _integrity_gate('vertex_manifold'),
        calibration=_structural('mesh topology; no real person is rejected by it'),
    ),
    Gate(
        't1_winding_consistent',
        1,
        'block',
        'consistent face winding',
        {'inconsistent_edges': 0},
        HOUSE,
        'HOUSE: inconsistent winding makes the signed volume and every normal meaningless',
        _integrity_gate('winding_consistent'),
        calibration=_structural('mesh topology; no real person is rejected by it'),
    ),
    Gate(
        't1_outward_normals',
        1,
        'block',
        'normals point out of the shell',
        {'inverted_components': 0},
        HOUSE,
        'HOUSE: an inverted shell yields a negative volume and inverts the sign of every depth measurement',
        _integrity_gate('outward_normals'),
        calibration=_structural('mesh topology; no real person is rejected by it'),
    ),
    Gate(
        't1_degenerate_geometry',
        1,
        'block',
        'no zero-area faces or duplicate vertices',
        {'degenerate_faces': 0},
        HOUSE,
        'HOUSE: a degenerate face has no normal, so it silently corrupts every area-weighted quantity',
        _integrity_gate('degenerate_geometry'),
        calibration=_structural('mesh topology; no real person is rejected by it'),
    ),
    Gate(
        't1_self_intersection',
        1,
        'block',
        'shell does not penetrate itself',
        {'robust_face_pairs': 0},
        HOUSE,
        'HOUSE: only pairs found under BOTH quad diagonals count; a pair seen under one '
        'diagonal is an artefact of triangulating a non-planar quad',
        t1_self_intersection,
        calibration=_structural(
            'a shell penetrating itself is a broken cage, not an unusual body; there is no population rate for it'
        ),
    ),
    Gate(
        't1_self_intersection_locality',
        1,
        'report',
        'where the self-intersections are',
        None,
        None,
        None,
        t1_self_intersection_locality,
        calibration=_structural('report-only locality map; gates nothing'),
    ),
    Gate(
        't1_shell_containment',
        1,
        'block',
        'every non-body shell sits where a shell may sit (WIRED 2026-08-05)',
        {'shells_defective': 0},
        HOUSE,
        "HOUSE: the defect states are integrity.py's own — detached_in_open_air, "
        'straddles_without_crossing, enclosed_but_crossing, indeterminate. Containment is '
        'by generalised winding number against the body component, ray-parity '
        'cross-checked, and a shell that was NOT tested reports unmeasurable rather than '
        'passing. Before this gate existed the whole containment engine was computed on '
        'every character and read by nothing: a tongue teleported 2 m in front of the '
        'body produced a byte-identical 34-gate verdict.',
        t1_shell_containment,
        calibration=_structural(
            'where a mesh component sits relative to the body shell '
            'is a cage-correctness question. No survey of people '
            'has a rate for "the tongue is two metres away".'
        ),
    ),
    Gate(
        't1_euler_genus',
        1,
        'report',
        'per-component Euler characteristic and genus, reported not gated',
        None,
        None,
        None,
        t1_euler_genus,
        calibration=_structural(
            'report-only: integrity.py deliberately does not assert '
            'genus 0 (a mouth cavity connecting to the throat is '
            'legitimately higher genus), so neither does this. It '
            'exists so the numbers reach the artefact instead of '
            'living in a payload nothing reads.'
        ),
    ),
    Gate(
        't1_build_target_stature',
        1,
        'block',
        'delivered stature vs the declared BUILD TARGET (not an anthropometric claim)',
        {'tolerance_mm': BUILD_TARGET_STATURE_TOL_MM},
        HOUSE,
        'HOUSE. A convergence check on the height solver. Explicitly NOT an '
        'anthropometric-accuracy claim: real stature varies %.1f-%.1f mm within one day.' % DIURNAL_STATURE_RANGE_MM,
        t1_build_target_stature,
        calibration=_structural(
            'a contract check against the number the RECIPE asked '
            'for. The reference population never declared a build '
            'target, so it cannot be rejected by this gate'
        ),
    ),
    Gate(
        't1_morph_bounds',
        1,
        'block',
        'every morph coefficient within +/-%.1f' % MORPH_COEFF_ABS_MAX,
        {'abs_max': MORPH_COEFF_ABS_MAX},
        HOUSE,
        'HOUSE, task-specified. Applies to the +/-1 local-change weights only; the 0..1 '
        'macros are domain-checked instead because 0 and 1 are legitimate there.',
        t1_morph_bounds,
        calibration=_structural(
            'a bound on OUR morph coefficients, which are a property of the recipe and not a measurement of anybody'
        ),
    ),
    Gate(
        't1_landmark_ordering_hard',
        1,
        'block',
        'height chain steps that no ANSUR subject violates',
        {'violation_rate_in_reference': 0.0},
        MEASURED,
        HEIGHT_CHAIN_SOURCE,
        t1_landmark_ordering_hard,
        calibration={
            'kind': CAL_VIOLATION_RATE,
            'rate': max(max(t[2], t[3]) for t in HARD_HEIGHT_CHAIN),
            'n': 6068,
            'source': HEIGHT_CHAIN_SOURCE,
            'why': 'this chain IS the same policy applied by hand before the '
            'policy existed: a step was admitted to the blocking chain '
            'only because 0 of 6,068 real subjects violate it. The four '
            'steps that real people do violate are in the SOFT chain.',
        },
        evidence=EV_ANSUR_II,
    ),
    Gate(
        't1_landmark_ordering_soft',
        1,
        'warn',
        'height chain steps that real people do violate',
        {'max_violation_rate_in_reference': 0.45835},
        MEASURED,
        HEIGHT_CHAIN_SOURCE,
        t1_landmark_ordering_soft,
        calibration={
            'kind': CAL_VIOLATION_RATE,
            'rate': max(max(t[2], t[3]) for t in SOFT_HEIGHT_CHAIN),
            'n': 6068,
            'source': HEIGHT_CHAIN_SOURCE,
            'why': 'the worked example of the policy: acromion above '
            'suprasternale is violated by 45.8% of real men, which is '
            '46x the blocking ceiling, so it warns.',
        },
        evidence=EV_ANSUR_II,
    ),
    Gate(
        't1_girth_chain',
        1,
        'block',
        'monotonic limb girths PER STEP, plus underbust <= bust',
        {
            'violation_rate_in_reference': 0.0,
            'fail_capable_steps': [s['id'] for s in GIRTH_STEPS if s.get('blocking')],
            'warn_only_steps': [s['id'] for s in GIRTH_STEPS if not s.get('blocking')],
        },
        MEASURED,
        'MEASURED 2026-08-05 from ANSUR II, PER STEP. Fail-capable: upper arm > wrist '
        '(biceps>wrist, violated by 0 of 6,068, smallest margin 73/86 mm), thigh > calf '
        '(0/6,068, 107/122 mm) and calf > ankle (0/6,068, 100/98 mm). NOT fail-capable: '
        'both elbow steps — ANSUR II ships no elbow circumference column at all, so no '
        'rejection rate for them can exist; and the bust pair, which has no underbust '
        'column. Those three warn.',
        t1_girth_chain,
        calibration={
            'kind': CAL_VIOLATION_RATE,
            'steps': GIRTH_STEPS,
            'n': 6068,
            'source': GIRTH_CHAIN_SOURCE,
            'why': 'the rate is derived from the step table, not declared beside '
            'it: the previous version blocked on upper arm > ELBOW while '
            'quoting the FOREARM > wrist rate (0.0000%) as the evidence, '
            'which is a MEASURED number for a step this gate does not '
            'apply. The bust pair likewise has no survey support and may '
            'only warn.',
        },
        evidence=EV_ANSUR_II,
    ),
    # -- Tier 2 ---------------------------------------------------------------
    Gate(
        't2_mahalanobis',
        2,
        'block',
        'PRIMARY plausibility: joint Mahalanobis on the ratio vector',
        {'empirical_percentiles': ['p95 warn', 'p99 block']},
        MEASURED,
        'MEASURED: empirical percentiles of D^2 in ANSUR II itself (male n=4082, female '
        'n=1986). Never chi-square — the pack shows the chi-square p95 value does not '
        'pass 95% of real people. ON THIS CAGE the first of the four components is a '
        'HOUSE substitution (cervicale = suprasternale + a per-sex ANSUR mean offset; '
        'there is no vertebra prominens to measure), so the threshold is MEASURED but one '
        'of the coordinates it judges is not.',
        t2_mahalanobis,
        calibration={
            'kind': CAL_EMPIRICAL_PERCENTILE,
            'percentile': 99.0,
            'verify': 'mahalanobis',
            'components': CAST_VECTOR_COMPONENTS,
            'substitutions': {
                'cervicale_height_over_stature': {
                    'from_ratio': 'suprasternale_height_over_stature',
                    'offset_frac_stature': {
                        'male': LMK.CERVICALE_OVER_SUPRASTERNALE['male'][0],
                        'female': LMK.CERVICALE_OVER_SUPRASTERNALE['female'][0],
                    },
                    'offset_source': 'MEASURED per-subject ANSUR mean of cervicale minus '
                    'suprasternale as a fraction of stature, male 0.0448 '
                    '+/- 0.0065 / female 0.0405 +/- 0.0071; the SD is '
                    'irreducible uncertainty the gate cannot see',
                    'why': 'measure.py emits cervicale_height as UNMEASURABLE '
                    'and publishes cervicale_height_house under the '
                    'ANSUR ratio name, so this is the coordinate the '
                    'gate really feeds the model',
                }
            },
            'source': "empirical p99 of D^2 in ANSUR II, measured on the pack's "
            'per-subject vectors over the four components this cage '
            'can measure AND re-measured with the cervicale '
            'coordinate substituted the way this pipeline substitutes '
            'it',
            'why': 'the gate the ceiling was taken from — and the ceiling is the '
            "MODEL's design rate (1% by construction), not this gate's. "
            'Run on the vector as substituted the same threshold rejects '
            '1.176% of real men, so this gate does not clear its own '
            'anchor and is downgraded like anything else.',
        },
        evidence=EV_ANSUR_II,
    ),
    Gate(
        't2_heights_tight',
        2,
        'block',
        'heights, TIGHT against a stature-anchored point',
        {'halfwidth': '%g x MEASURED residual rmse' % STATURE_ANCHOR_SIGMA},
        HOUSE,
        'HOUSE multiplier on a MEASURED residual. Permitted only for dimensions '
        'reference.predictability() classes as tight (r>=0.80, rmse<=30mm).',
        t2_heights_tight,
        calibration={'kind': CAL_STATURE_ANCHORED, 'pairs': TIGHT_HEIGHT_PAIRS, 'sigma': STATURE_ANCHOR_SIGMA},
    ),
    Gate(
        't2_breadths_wide',
        2,
        'block',
        'breadths, WIDE against the population band',
        {'block': 'p1-p99', 'warn': 'p5-p95'},
        MEASURED,
        'MEASURED percentiles of the group distribution in ANSUR II. Never a '
        'stature-derived point: biacromial r=0.53, bideltoid r=0.31.',
        t2_breadths_wide,
        calibration=_bands(BREADTH_RATIOS, policy='wide'),
        evidence=EV_ANSUR_II,
    ),
    Gate(
        't2_girths_wide',
        2,
        'block',
        'circumferences, WIDE against the population band',
        {'block': 'p1-p99', 'warn': 'p5-p95'},
        MEASURED,
        'MEASURED percentiles of the group distribution in ANSUR II. Waist circumference vs stature is r=0.21.',
        t2_girths_wide,
        calibration=_bands(GIRTH_RATIOS, policy='wide'),
        evidence=EV_ANSUR_II,
    ),
    Gate(
        't2_ancestry_leg',
        2,
        'warn',
        'leg proportion against an ancestry-parameterised band',
        {'block': 'p1-p99 of the DECLARED group'},
        MEASURED,
        'MEASURED per-DODRace-group bands in ANSUR II. %s A %.3f spread is 44 mm of leg '
        'on a 1.85 m man, 11x the ISO height tolerance.' % (ANCESTRY_LEG_SOURCE, ANCESTRY_LEG_SPREAD),
        t2_ancestry_leg,
        calibration=_bands([ANCESTRY_LEG_RATIO]),
        evidence=EV_ANSUR_II,
    ),
    Gate(
        't2_ancestry_cormic',
        2,
        'warn',
        'cormic index against an ancestry-parameterised band',
        {'block': 'p1-p99 of the DECLARED group'},
        MEASURED,
        'MEASURED per-group bands in ANSUR II; not computable from a standing mesh.',
        t2_ancestry_cormic,
        calibration=_bands(['sitting_height_over_stature']),
        evidence=EV_ANSUR_II,
    ),
    Gate(
        't2_child_growth',
        2,
        'block',
        'child SIZE against CDC 2000 stature/BMI-for-age',
        {'z_warn': CDC_Z_WARN, 'z_fail': CDC_Z_FAIL},
        HOUSE,
        'HOUSE cut points on the MEASURED CDC 2000 LMS curves (NCHS, US children 24-240 months, public domain).',
        t2_child_growth,
        calibration={
            'kind': CAL_LMS_Z,
            'z_fail': CDC_Z_FAIL,
            'why': 'only stature-for-age can FAIL; BMI-for-age may only warn, '
            'because the mesh BMI assumes a uniform density and the CDC '
            "LMS tail above p95 is unreliable by CDC's own statement.",
        },
    ),
    Gate(
        't2_child_proportions',
        2,
        'warn',
        'child PROPORTIONS vs a convention-matched adult (catches a scaled-down adult)',
        {'direction_only': True},
        HOUSE,
        CHILD_DIRECTION_SOURCE,
        t2_child_proportions,
        calibration=_structural(
            'a DIRECTION test against a convention-matched adult built by this same '
            'pipeline. No survey of children is on disk, so there is no reference sample '
            'to compute a rejection rate against — which is also exactly why the gate '
            'asserts only the sign and never a magnitude, and why it may not block.'
        ),
    ),
    Gate(
        't2_adult_age_channel',
        2,
        'warn',
        'ageing is a girth delta on an unchanged skeleton',
        AGE_CHANNEL,
        MEASURED,
        AGE_CHANNEL_SOURCE,
        t2_adult_age_channel,
        calibration=_bands(AGE_CHANNEL_BLOCKING_RATIOS),
        evidence=EV_ANSUR_II,
    ),
    Gate(
        't2_vhi_bmi',
        2,
        'block',
        'VHI against a declared band; BMI against the pack',
        {'vhi_band': 'CALLER-DECLARED', 'bmi': 'p1-p99'},
        HOUSE,
        'HOUSE: no survey publishes volume/stature^2, so a VHI band cannot be derived '
        'and must be declared. BMI may only warn because the mesh BMI assumes a density.',
        t2_vhi_bmi,
        calibration={
            'kind': CAL_DECLARED_BAND,
            'informational_bands': ['bmi'],
            'why': 'the only FAIL-capable threshold in this gate is the VHI '
            'band, and that band is DECLARED BY THE CALLER for the '
            'character type. No survey on disk publishes volume/'
            'stature^2, so there is no reference sample it could reject '
            'a fraction of; like the build-target stature check it is a '
            'contract, not a population claim. The BMI half is already '
            'downgraded to warn inside the gate and its band rejects '
            '2% of the reference by construction.',
        },
    ),
)
