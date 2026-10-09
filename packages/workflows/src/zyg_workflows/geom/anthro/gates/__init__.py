# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401
"""gates.py — the four-tier gate engine over a generated parametric body.

WHY THIS EXISTS: measure.py can produce a number for almost anything, and reference.py can
produce a band for almost any number. Putting the two together is where the biases get
introduced, and this module exists to make the five known ones structurally impossible
rather than merely discouraged.

  1. TEN INDEPENDENT BANDS ARE NOT A PLAUSIBILITY TEST. Ten independent 90% intervals
     admit at most 0.9^10 = 35% of real people and simultaneously admit combinations that
     never co-occur on one body. The PRIMARY plausibility gate here is Mahalanobis on the
     joint ratio vector with the pack's EMPIRICAL thresholds. The per-ratio bands are
     secondary and are labelled as marginal statements. On THIS cage that primary gate
     runs on four components, one of which is a HOUSE substitution rather than a
     measurement, and the consequence is measured rather than assumed — see rule 6.

  2. AN ORDERING ASSERTION IS AN EMPIRICAL CLAIM, NOT A FACT ABOUT ANATOMY. Every step of
     the landmark height chain in this file was checked against 6,068 real people before
     it was allowed to block. Four "obvious" steps turned out to be false: acromion above
     suprasternale is a coin flip (violated by 45.8% of ANSUR men), trochanterion above
     buttock is violated by 19.8%, iliocristale above omphalion by 42.5%, buttock above
     crotch by 2.3%. Blocking on those would reject real humans, so they are WARNINGS
     carrying their measured violation rate and only the 0-violation steps block.

  3. A CHILD IS NOT A SMALL ADULT AND ANSUR HAS NO CHILDREN. Every ANSUR-derived band and
     the Mahalanobis gate itself are refused outside 17-58 years, with the numbers still
     printed so the operator can see them, because a band silently applied to a
     12-year-old is worse than no band. The child gate instead compares the child against
     a CONVENTION-MATCHED adult measured through this identical pipeline.

  4. ANCESTRY IS THE LARGEST PROPORTION EFFECT IN THE DATA, so a gate run with no declared
     ancestry does not quietly become "the average human". It warns, every time, and says
     which mixture it fell back to.

  5. TIGHT AND WIDE ARE READ FROM THE DATA, NOT CHOSEN. Whether a dimension may be gated
     against a stature-anchored point comes from reference.predictability(); nothing in
     this file hardcodes which measurements are predictable.

  6. BLOCKING SEVERITY IS MEASURED, NOT DECLARED. See the policy block below.

  7. A BOOK MAY NOT OUTRANK A SURVEY. Added 2026-08-06 with tier 5. The provenance
     vocabulary gains CANON — a number PRINTED IN AN ARTIST OR ANATOMY REFERENCE, ranked
     below MEASURED — and validate_registry refuses `block` severity to any CANON
     threshold over a quantity ANSUR II / CDC / NHANES already answers. The case that
     forced it: Anatomy For Sculptors p.91-93 puts ages 8-12 at 6.0 head units, while this
     pipeline measures 7.06-7.13 on a 12-year-old and on three adults alike, and the same
     chart makes crotch height migrate DOWNWARD with age while the NHANES III cormic data
     already on disk says the opposite. See CANON_VS_MEASURED_CONFLICT. Books set
     thresholds where the surveys are silent — angles, signs, curvature, relief, joint
     ranges — and nowhere else.

  8. "MEASURED" IS A CLAIM THAT HAS TO PRODUCE ITS EVIDENCE. Added 2026-08-06, because
     rule 7 was measured to be bypassable by typing a different word: the same blocking
     CANON gate over crotch height that validate_registry refuses was ACCEPTED with one
     field changed to MEASURED, and the wave shipped a live instance (t5_digit_chains,
     tagged MEASURED and blocking on the strength of two art-anatomy book pages). Every
     MEASURED threshold now carries a structured `evidence` record naming one of
     MEASURED_EVIDENCE_CLASSES, with a population and a positive integer n; a pack-backed
     record must name a source that RESOLVES in the reference pack's own provenance
     document on disk, checked live by t4_threshold_provenance; and a gate whose citation
     — or whose own source line — is a BOOK PAGE is refused the MEASURED tag outright,
     because a page is the definition of CANON however the field is typed.

  9. A GATE MAY NOT BE SCORED ON A SUBJECT IT DID NOT LOOK AT. Added 2026-08-06 after the
     pose gates were measured to be evaluating the REST A-POSE alone while their registry
     text claimed the fitted pose library too — a blocking PASS ("0 of 11 ROM sub-checks
     failed") that was a property of the all-zero pose it was handed, on a body whose
     entire fitted library fails the identical gate 44/44. Pose gates now consume
     pose_limits.pose_layer(), which evaluates every DECLARED subject, publishes each
     verdict separately, and makes a declared-but-unevaluated subject contribute
     UNRESOLVED rather than letting the other subject's pass stand for both.

Every gate is a declarative record with an id, a tier, a severity, a threshold, a
provenance tag and a callable. The engine REFUSES TO RUN if any shipped threshold is
untagged or tagged CONTESTED — that is a real code path, not a comment, and it is what
stops a debunked constant (golden ratio, WHR 0.7, Adonis 1.618) from ever being a gate.

THE SEVERITY CALIBRATION POLICY (rule 6, in full)
-------------------------------------------------
A severity written into a registry by hand is an opinion about how bad a violation is. It
says nothing about how many real people the gate would throw out, and on this pack the
two answers are wildly different. The pack measured it itself: the ten independent p5-p95
bands admit 47.16% of real ANSUR men and 46.0% of real ANSUR women (doc['mahalanobis']
['sexes'][sex]['independent_bands_check']). A gate set that blocks whenever any one
marginal band is left therefore rejects MORE THAN HALF OF REAL HUMANS while the joint
Mahalanobis model beside it is calibrated to reject 1%. That is not a stricter gate, it is
a broken one, and on the male original it is exactly what happened: t2_mahalanobis PASSED
at D^2=5.02 (band 0..13.76) while t2_heights_tight, t2_breadths_wide and t2_girths_wide
all FAILED at blocking severity.

So severity here is DERIVED FROM THE REFERENCE SAMPLE:

    a gate may carry severity 'block' only if, run as configured against the real ANSUR
    sample, it would reject at most 1% of that sample. Otherwise it is 'warn'.

The ceiling is HOUSE, and what it is anchored on has to be stated exactly, because the
obvious reading of it is false. 1% is the DESIGN rejection rate of the pack's primary
plausibility MODEL: a threshold that IS the empirical p99 of joint D^2 rejects 1% of the
sample it was taken from by construction, and measures 1.004% (male n=4082) / 1.007%
(female n=1986) on the shipped per-subject vectors. It is NOT a claim that the GATE which
runs that model on this cage rejects 1%. This cage has no vertebra prominens, so the first
of the four components t2_mahalanobis can supply is a HOUSE substitution — suprasternale
plus a per-sex ANSUR offset — and the same p99 threshold applied to the vector AS
SUBSTITUTED rejects 1.176% of real men (measured, see _reject_empirical_percentile). That
is over the ceiling, so the policy downgrades t2_mahalanobis to 'warn' by exactly the same
arithmetic it applies to everything else. The anchor is the MODEL's rate; the gate the
anchor was taken from gets no exemption from it, and on this cage it does not clear it.

Two details of the arithmetic, stated rather than buried:

  * A p1-p99 band rejects 2% of the reference sample BY CONSTRUCTION, and a p5-p95 band
    rejects 10%, whatever the ratio and whatever the distribution — the percentile grid
    makes it a property of the band's definition, not of the body. So no single-ratio
    p1-p99 band can ever be blocking under this policy, and a gate that rolls up five of
    them rejects more still. That fact is the argument for the policy; it is reported in
    every calibration record rather than hidden inside one.
  * An empirical p99 threshold rejects 1% by construction but lands at 1.004% on n=4082
    and 1.007% on n=1986, because an empirical percentile cannot be resolved finer than
    one subject. The comparison therefore allows exactly that granularity, 1/n, and
    records it. It changes nothing else: the band gates miss the ceiling by factors of 4
    to 23, not by one subject — and t2_mahalanobis misses it by 1.176% against a bar of
    1.024%, which is a sixth of a percent and not a rounding question either.
  * A CALIBRATION MUST MEASURE THE GATE, NOT A NEARBY GATE. Two ways that goes wrong are
    checked for here rather than commented about: measuring a band set wider than the one
    the gate can fail on (see _gateable_bands, which drops the ratios _band_check demotes
    to REPORT before the rate is computed), and measuring a model the gate does not run
    (see the substitution handling in _reject_empirical_percentile). Both produce a
    rejection rate for a gate that does not exist, which is the failure this whole
    exercise is fixing.

Every gate declares WHICH calibration applies to it, the engine measures the rate at run
time from the microdata the pack ships, and the measured rate travels in the gate's result
record, so the severity of every gate in the report is auditable against the sample. Gates
that are STRUCTURAL rather than statistical — cage integrity, landmark ordering, morph
bounds, the build-target stature check, provenance, a caller-declared band — keep their
declared severity, and their records say so and why.
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import numpy as np
from zyg_workflows.geom import mesh_skeletons as MS
from zyg_workflows.geom.anthro import integrity as IG
from zyg_workflows.geom.anthro import landmarks as LMK
from zyg_workflows.geom.anthro import measure as ME
from zyg_workflows.geom.anthro.reference import reference
import logging as _zyg_logging

from zyg_workflows.geom.anthro.gates.policy import (
    _zyg_log,
    SCHEMA,
    MEASURED,
    CANON,
    HOUSE,
    CONTESTED,
    VALID_PROVENANCE,
    PROVENANCE_RANK,
    CANON_DEFINITION,
    CANON_VS_MEASURED_CONFLICT,
    TIERS,
    MEASURED_COVERED_QUANTITIES,
    MEASURED_COVERAGE_SOURCE,
    MEASURED_NOT_COVERED_NOTE,
    measured_covered,
    MEASURED_EVIDENCE_CLASSES,
    WITHDRAWN_EVIDENCE_CLASSES,
    CANON_BOOKS,
    _PAGE_RE,
    canon_book_citations,
    canon_book_pages,
    declared_quantities,
    verify_measured_evidence,
    EV_ANSUR_II,
    EV_PHALANX_SERIES,
    SEVERITIES,
    PASS,
    WARN,
    FAIL,
    REPORT,
    UNMEASURABLE,
    NOT_APPLICABLE,
    NOT_IMPLEMENTABLE,
    MISSING,
    ERROR,
    POLICY_ERROR,
    STATUSES,
    ERROR_CLASS_STATUSES,
    CRASHED_KEY,
    CRASHED_CONTRACT,
    ANSUR_AGE_MIN_Y,
    ANSUR_AGE_MAX_Y,
    ANSUR_COVERAGE_NOTE,
    BUILD_TARGET_STATURE_TOL_MM,
    MORPH_COEFF_ABS_MAX,
    DIURNAL_STATURE_RANGE_MM,
    MIN_ANTHROPOMETRIC_STATURE_TOL_MM,
    STATURE_ANCHOR_SIGMA,
)
from zyg_workflows.geom.anthro.gates.bands import (
    HARD_HEIGHT_CHAIN,
    SOFT_HEIGHT_CHAIN,
    HEIGHT_CHAIN_SOURCE,
    HARD_GIRTH_CHAINS,
    GIRTH_CHAIN_SOURCE,
    AGE_CHANNEL,
    AGE_CHANNEL_SOURCE,
    SKELETAL_AGE_DRIFT_CEILING,
    CHILD_CORMIC,
    CHILD_CORMIC_SOURCE,
    CHILD_PROPORTION_ASSERTIONS,
    CHILD_DIRECTION_PROVENANCE,
    CHILD_DIRECTION_SOURCE,
    ANCESTRY_LEG_RATIO,
    ANCESTRY_LEG_MEANS_MALE,
    ANCESTRY_LEG_SPREAD,
    ANCESTRY_LEG_SOURCE,
    CDC_Z_WARN,
    CDC_Z_FAIL,
    CAST_VECTOR_COMPONENTS,
    CAST_PAIR_CALIBRATION,
    CAST_PAIR_SOURCE,
    CAST_PAIR_SAMPLES,
    CAST_PAIR_SEED,
    CAST_SAME_BODY_PERCENTILE,
    CAST_SIMILAR_PERCENTILE,
    CANON_HEADS_TALL,
    CANON_SOURCE,
    STYLIZATION_AXIS,
    STYLIZATION_AXIS_NOTE,
    REALISM_ASYMMETRY_BAND_MM,
    REALISM_ASYMMETRY_POP_MEAN_MM,
    SYM_MORPH_TOL_SOURCE,
    VHI_UNITS,
    SEVERITY_REJECTION_CEILING,
    SEVERITY_POLICY,
    ANSUR_REFERENCE_POPULATION,
    SEVERITY_POLICY_PROVENANCE,
    SEVERITY_POLICY_SOURCE,
    CAL_RATIO_BANDS,
    CAL_STATURE_ANCHORED,
    CAL_EMPIRICAL_PERCENTILE,
    CAL_LMS_Z,
    CAL_VIOLATION_RATE,
    CAL_DECLARED_BAND,
    CAL_STRUCTURAL,
    CAL_PRINTED_BAND,
    CAL_UNDECLARED,
    CALIBRATION_KINDS,
    BREADTH_RATIOS,
    GIRTH_RATIOS,
    DEPTH_RATIOS,
    TIGHT_HEIGHT_PAIRS,
    AGE_CHANNEL_BLOCKING_RATIOS,
    BAND_WIDTH_BLOCK,
    BAND_WIDTH_WARN,
    _RATIO_FLAG_CACHE,
    _measure_ratio_flags,
    _gateable_bands,
    GateConfigError,
    SubjectError,
    CANNOT_FAIL_NOTE,
    _structural,
    _printed_band,
    _bands,
)
from zyg_workflows.geom.anthro.gates.gate import (
    Gate,
    RECEIPT_KEY,
    _result,
    validate_registry,
    _PROVENANCE_KEY_TOKEN,
    NON_THRESHOLD_PROVENANCE_KEYS,
    scan_module_provenance,
    provenance_direction,
    provenance_shippable,
    MODULE_PROVENANCE_RULE,
    check_module_provenance,
)
from zyg_workflows.geom.anthro.gates.subject import (
    SPEC_KEYS,
    Subject,
    _ADULT_REF_CACHE,
    adult_reference,
    _band_check,
    _ROLL_UP_ORDER,
    _SKIPPED,
    _NO_VERDICT_STATUSES,
    UNEVALUATED_CLAIM,
    DECLARED_CLAIM_CONTRACT,
    _claim_rollup,
    _roll_up,
    _roll_up_summary,
    _skip_phrase,
    _sub,
    _note,
    _predictability_split,
)
from zyg_workflows.geom.anthro.gates.severity_reject import (
    _SAMPLE_CACHE,
    _REJECT_CACHE,
    _norm_sf2,
    _worst_cell,
    ansur_sample,
    _sample_unavailable_reason,
    _cells,
    _reject_ratio_bands,
    _reject_stature_anchored,
    _substituted_column,
    _reject_empirical_percentile,
)
from zyg_workflows.geom.anthro.gates.tier1 import (
    _integrity_gate,
    t1_shell_containment,
    t1_euler_genus,
    t1_self_intersection,
    _region_hint,
    t1_self_intersection_locality,
    t1_build_target_stature,
    t1_morph_bounds,
    _chain_rows,
    t1_landmark_ordering_hard,
    t1_landmark_ordering_soft,
    _girth_steps,
    GIRTH_STEPS,
    t1_girth_chain,
)
from zyg_workflows.geom.anthro.gates.tier2 import (
    _input_provenance,
    t2_mahalanobis,
    t2_heights_tight,
    _wide_gate,
    t2_breadths_wide,
    t2_girths_wide,
    t2_ancestry_leg,
    t2_ancestry_cormic,
    t2_child_growth,
    t2_child_proportions,
    t2_adult_age_channel,
    t2_vhi_bmi,
)
from zyg_workflows.geom.anthro.gates.tier3 import (
    t3_depths_wide,
    t3_morph_symmetry,
    t3_realism_asymmetry,
    t3_spine_curvature,
    _CAST_CACHE,
    _CAST_FAILED,
    registry_cast,
    _cast_vector,
    _CAST_NULL,
    _cast_null,
    t3_cast_diversity,
)
from zyg_workflows.geom.anthro.gates.tier4 import (
    REQUIRED_MEASUREMENT_FIELDS,
    REQUIRED_META_FIELDS,
    t4_measurement_provenance,
    CENSUS_BUCKET_RULE,
    MEASURED_CENSUS_BUCKETS,
    _census_bucket,
    t4_threshold_provenance,
    t4_stylization_axis,
    t4_canon_and_percentiles,
    t4_tolerance_sanity,
)
from zyg_workflows.geom.anthro.gates.tier5_form import (
    ZYG_TIER5_FLAG,
    _tier5_enabled,
    _FORM_MODULES,
    _FORM_IMPORTED,
    form_module,
    _FORM_CACHE_FALLBACK,
    _FORM_CACHE_NOTE,
    _form_cache_key,
    _form_cache,
    _p_sections,
    _p_angles,
    _p_pose_limits,
    _p_hands,
    _p_ridge,
    _FORM_PAYLOADS,
    form_payload,
    _t5_disabled,
    _t5_payload,
    _SECTION_STATUS,
    _HAND_STATUS,
    _xlate,
    _section_gate,
    t5_neck_section,
)
from zyg_workflows.geom.anthro.gates.tier5_gates import (
    PL_STIFFNESS_FLOOR_DEG,
    _pose_gate,
    _digit_gate,
    _angle_gate,
    _canthal_verdict,
    FAT_INVARIANT_SOURCE,
    _relief_summary,
    t5_landmark_relief,
    t5_head_landmark_relief,
    AFS_HEAD_UNITS_CHART,
    t5_canon_head_units,
)
from zyg_workflows.geom.anthro.gates.tier5_capability import (
    _SCRIPT_MODE_PROBE,
    _SCRIPT_MODE_PROBE_SRC,
    script_mode_probe,
    _SCRIPT_MODE_CONTROL_SRC,
    _SCRIPT_MODE_CONTROL,
    _script_mode_negative_control,
    _MVCONSIST_BAND,
    MVCONSIST_ALL48_DIR,
    _SFM_CAPABILITY_CACHE,
    t4_sfm_capability,
    t4_multiview_consistency,
    t4_form_modules_importable,
)
from zyg_workflows.geom.anthro.gates.registry_tiers_1_2 import (
    GATES_TIERS_1_2,
)
from zyg_workflows.geom.anthro.gates.registry_tiers_3_4 import (
    GATES_TIERS_3_4,
)
from zyg_workflows.geom.anthro.gates.registry_tier5 import (
    GATES_TIER_5,
)
from zyg_workflows.geom.anthro.gates.registry import (
    GATES,
)
from zyg_workflows.geom.anthro.gates.severity import (
    _reject_lms_z,
    _reject_violation_rate,
    calibrate_gate,
    calibrate,
    severity_table,
)
from zyg_workflows.geom.anthro.gates.engine import (
    _BLOCKING,
    _WARNING,
    _effective_severity,
    _classify,
    run_gates,
    sub_meta,
    _atomic_json,
)
from zyg_workflows.geom.anthro.gates.selftest_runtime import (
    _selftest_declared_claims,
    _selftest_severity,
    _selftest_rollup,
    _selftest_shells,
    _selftest_paths,
    _selftest_crash_vs_policy,
)
from zyg_workflows.geom.anthro.gates.selftest_provenance import (
    _selftest_refusal,
    _selftest_census_buckets,
    _selftest_measured_bypass,
    _selftest_module_provenance,
)
from zyg_workflows.geom.anthro.gates.cli import (
    _MARK,
    render_severity_table,
    main,
)

__all__ = [
    '_zyg_log',
    'SCHEMA',
    'MEASURED',
    'CANON',
    'HOUSE',
    'CONTESTED',
    'VALID_PROVENANCE',
    'PROVENANCE_RANK',
    'CANON_DEFINITION',
    'CANON_VS_MEASURED_CONFLICT',
    'TIERS',
    'MEASURED_COVERED_QUANTITIES',
    'MEASURED_COVERAGE_SOURCE',
    'MEASURED_NOT_COVERED_NOTE',
    'measured_covered',
    'MEASURED_EVIDENCE_CLASSES',
    'WITHDRAWN_EVIDENCE_CLASSES',
    'CANON_BOOKS',
    '_PAGE_RE',
    'canon_book_citations',
    'canon_book_pages',
    'declared_quantities',
    'verify_measured_evidence',
    'EV_ANSUR_II',
    'EV_PHALANX_SERIES',
    'SEVERITIES',
    'PASS',
    'WARN',
    'FAIL',
    'REPORT',
    'UNMEASURABLE',
    'NOT_APPLICABLE',
    'NOT_IMPLEMENTABLE',
    'MISSING',
    'ERROR',
    'POLICY_ERROR',
    'STATUSES',
    'ERROR_CLASS_STATUSES',
    'CRASHED_KEY',
    'CRASHED_CONTRACT',
    'ANSUR_AGE_MIN_Y',
    'ANSUR_AGE_MAX_Y',
    'ANSUR_COVERAGE_NOTE',
    'BUILD_TARGET_STATURE_TOL_MM',
    'MORPH_COEFF_ABS_MAX',
    'DIURNAL_STATURE_RANGE_MM',
    'MIN_ANTHROPOMETRIC_STATURE_TOL_MM',
    'STATURE_ANCHOR_SIGMA',
    'HARD_HEIGHT_CHAIN',
    'SOFT_HEIGHT_CHAIN',
    'HEIGHT_CHAIN_SOURCE',
    'HARD_GIRTH_CHAINS',
    'GIRTH_CHAIN_SOURCE',
    'AGE_CHANNEL',
    'AGE_CHANNEL_SOURCE',
    'SKELETAL_AGE_DRIFT_CEILING',
    'CHILD_CORMIC',
    'CHILD_CORMIC_SOURCE',
    'CHILD_PROPORTION_ASSERTIONS',
    'CHILD_DIRECTION_PROVENANCE',
    'CHILD_DIRECTION_SOURCE',
    'ANCESTRY_LEG_RATIO',
    'ANCESTRY_LEG_MEANS_MALE',
    'ANCESTRY_LEG_SPREAD',
    'ANCESTRY_LEG_SOURCE',
    'CDC_Z_WARN',
    'CDC_Z_FAIL',
    'CAST_VECTOR_COMPONENTS',
    'CAST_PAIR_CALIBRATION',
    'CAST_PAIR_SOURCE',
    'CAST_PAIR_SAMPLES',
    'CAST_PAIR_SEED',
    'CAST_SAME_BODY_PERCENTILE',
    'CAST_SIMILAR_PERCENTILE',
    'CANON_HEADS_TALL',
    'CANON_SOURCE',
    'STYLIZATION_AXIS',
    'STYLIZATION_AXIS_NOTE',
    'REALISM_ASYMMETRY_BAND_MM',
    'REALISM_ASYMMETRY_POP_MEAN_MM',
    'SYM_MORPH_TOL_SOURCE',
    'VHI_UNITS',
    'SEVERITY_REJECTION_CEILING',
    'SEVERITY_POLICY',
    'ANSUR_REFERENCE_POPULATION',
    'SEVERITY_POLICY_PROVENANCE',
    'SEVERITY_POLICY_SOURCE',
    'CAL_RATIO_BANDS',
    'CAL_STATURE_ANCHORED',
    'CAL_EMPIRICAL_PERCENTILE',
    'CAL_LMS_Z',
    'CAL_VIOLATION_RATE',
    'CAL_DECLARED_BAND',
    'CAL_STRUCTURAL',
    'CAL_PRINTED_BAND',
    'CAL_UNDECLARED',
    'CALIBRATION_KINDS',
    'BREADTH_RATIOS',
    'GIRTH_RATIOS',
    'DEPTH_RATIOS',
    'TIGHT_HEIGHT_PAIRS',
    'AGE_CHANNEL_BLOCKING_RATIOS',
    'BAND_WIDTH_BLOCK',
    'BAND_WIDTH_WARN',
    '_RATIO_FLAG_CACHE',
    '_measure_ratio_flags',
    '_gateable_bands',
    'GateConfigError',
    'SubjectError',
    'CANNOT_FAIL_NOTE',
    '_structural',
    '_printed_band',
    '_bands',
    'Gate',
    'RECEIPT_KEY',
    '_result',
    'validate_registry',
    '_PROVENANCE_KEY_TOKEN',
    'NON_THRESHOLD_PROVENANCE_KEYS',
    'scan_module_provenance',
    'provenance_direction',
    'provenance_shippable',
    'MODULE_PROVENANCE_RULE',
    'check_module_provenance',
    'SPEC_KEYS',
    'Subject',
    '_ADULT_REF_CACHE',
    'adult_reference',
    '_band_check',
    '_ROLL_UP_ORDER',
    '_SKIPPED',
    '_NO_VERDICT_STATUSES',
    'UNEVALUATED_CLAIM',
    'DECLARED_CLAIM_CONTRACT',
    '_claim_rollup',
    '_roll_up',
    '_roll_up_summary',
    '_skip_phrase',
    '_sub',
    '_note',
    '_predictability_split',
    '_SAMPLE_CACHE',
    '_REJECT_CACHE',
    '_norm_sf2',
    '_worst_cell',
    'ansur_sample',
    '_sample_unavailable_reason',
    '_cells',
    '_reject_ratio_bands',
    '_reject_stature_anchored',
    '_substituted_column',
    '_reject_empirical_percentile',
    '_integrity_gate',
    't1_shell_containment',
    't1_euler_genus',
    't1_self_intersection',
    '_region_hint',
    't1_self_intersection_locality',
    't1_build_target_stature',
    't1_morph_bounds',
    '_chain_rows',
    't1_landmark_ordering_hard',
    't1_landmark_ordering_soft',
    '_girth_steps',
    'GIRTH_STEPS',
    't1_girth_chain',
    '_input_provenance',
    't2_mahalanobis',
    't2_heights_tight',
    '_wide_gate',
    't2_breadths_wide',
    't2_girths_wide',
    't2_ancestry_leg',
    't2_ancestry_cormic',
    't2_child_growth',
    't2_child_proportions',
    't2_adult_age_channel',
    't2_vhi_bmi',
    't3_depths_wide',
    't3_morph_symmetry',
    't3_realism_asymmetry',
    't3_spine_curvature',
    '_CAST_CACHE',
    '_CAST_FAILED',
    'registry_cast',
    '_cast_vector',
    '_CAST_NULL',
    '_cast_null',
    't3_cast_diversity',
    'REQUIRED_MEASUREMENT_FIELDS',
    'REQUIRED_META_FIELDS',
    't4_measurement_provenance',
    'CENSUS_BUCKET_RULE',
    'MEASURED_CENSUS_BUCKETS',
    '_census_bucket',
    't4_threshold_provenance',
    't4_stylization_axis',
    't4_canon_and_percentiles',
    't4_tolerance_sanity',
    'ZYG_TIER5_FLAG',
    '_tier5_enabled',
    '_FORM_MODULES',
    '_FORM_IMPORTED',
    'form_module',
    '_FORM_CACHE_FALLBACK',
    '_FORM_CACHE_NOTE',
    '_form_cache_key',
    '_form_cache',
    '_p_sections',
    '_p_angles',
    '_p_pose_limits',
    '_p_hands',
    '_p_ridge',
    '_FORM_PAYLOADS',
    'form_payload',
    '_t5_disabled',
    '_t5_payload',
    '_SECTION_STATUS',
    '_HAND_STATUS',
    '_xlate',
    '_section_gate',
    't5_neck_section',
    'PL_STIFFNESS_FLOOR_DEG',
    '_pose_gate',
    '_digit_gate',
    '_angle_gate',
    '_canthal_verdict',
    'FAT_INVARIANT_SOURCE',
    '_relief_summary',
    't5_landmark_relief',
    't5_head_landmark_relief',
    'AFS_HEAD_UNITS_CHART',
    't5_canon_head_units',
    '_SCRIPT_MODE_PROBE',
    '_SCRIPT_MODE_PROBE_SRC',
    'script_mode_probe',
    '_SCRIPT_MODE_CONTROL_SRC',
    '_SCRIPT_MODE_CONTROL',
    '_script_mode_negative_control',
    '_MVCONSIST_BAND',
    'MVCONSIST_ALL48_DIR',
    '_SFM_CAPABILITY_CACHE',
    't4_sfm_capability',
    't4_multiview_consistency',
    't4_form_modules_importable',
    'GATES_TIERS_1_2',
    'GATES_TIERS_3_4',
    'GATES_TIER_5',
    'GATES',
    '_reject_lms_z',
    '_reject_violation_rate',
    'calibrate_gate',
    'calibrate',
    'severity_table',
    '_BLOCKING',
    '_WARNING',
    '_effective_severity',
    '_classify',
    'run_gates',
    'sub_meta',
    '_atomic_json',
    '_selftest_declared_claims',
    '_selftest_severity',
    '_selftest_rollup',
    '_selftest_shells',
    '_selftest_paths',
    '_selftest_crash_vs_policy',
    '_selftest_refusal',
    '_selftest_census_buckets',
    '_selftest_measured_bypass',
    '_selftest_module_provenance',
    '_MARK',
    'render_severity_table',
    'main',
]
