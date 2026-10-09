# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The measured bands, the severity-calibration constants they are read against, and the calibration specs the registry rows declare.

Moved verbatim out of the old single-file gates.py (lines 752-1302, 7089-7144).
"""

from zyg_workflows.geom.anthro import integrity as IG
from zyg_workflows.geom.anthro import measure as ME
from zyg_workflows.geom.anthro.reference import reference

from zyg_workflows.geom.anthro.gates.policy import HOUSE


# ---------------------------------------------------------------------------------
# Landmark height chain — MEASURED 2026-08-05 against the ANSUR II public working
# databases on disk (male n=4082, female n=1986, US Army 17-58 y, measured
# 2010-10..2012-04). `violation_rate` is the fraction of REAL SUBJECTS in whom the step
# does not hold. Only 0-violation steps are allowed to block; everything else is a
# warning that carries its own rate, because a gate stricter than the population is a
# gate that rejects people who exist.
# ---------------------------------------------------------------------------------
HARD_HEIGHT_CHAIN = (
    ('stature', 'cervicale_height_house', 0.0, 0.0, 194.0, 197.0),
    ('cervicale_height_house', 'acromial_height', 0.0, 0.0, 30.0, 16.0),
    ('acromial_height', 'waist_height_omphalion', 0.0, 0.0, 290.0, 283.0),
    ('suprasternale_height', 'waist_height_omphalion', 0.0, 0.0, 293.0, 284.0),
    ('waist_height_omphalion', 'trochanterion_height', 0.0, 0.0, 56.0, 46.0),
    ('trochanterion_height', 'tibiale_height', 0.0, 0.0, 310.0, 311.0),
    ('crotch_height', 'tibiale_height', 0.0, 0.0, 292.0, 261.0),
)
SOFT_HEIGHT_CHAIN = (
    ('trochanterion_height', 'buttock_height', 0.19843, 0.17120, -44.0, -65.0),
    ('buttock_height', 'crotch_height', 0.02254, 0.00101, -29.0, -10.0),
    ('trochanterion_height', 'crotch_height', 0.00220, 0.00000, -9.0, 8.0),
    ('acromial_height', 'suprasternale_height', 0.45835, 0.34240, -53.0, -34.0),
)
HEIGHT_CHAIN_SOURCE = (
    'MEASURED 2026-08-05 from ANSUR II 2012 public working databases '
    '(male n=4082, female n=1986, US Army personnel 17-58 y): '
    'per-subject violation rate of each ordering step'
)

# Girth monotonicity, same treatment — but PER STEP, because the chain is not the unit of
# evidence. A chain is only as blockable as its weakest-evidenced step, and on the arm
# chain one step has NO survey evidence at all: ANSUR II ships 18 circumference columns
# and none of them is an elbow (verified from the shipped headers of
# ANSUR_II_{MALE,FEMALE}_Public.csv). This cage has no forearm-maximum site, so the ELBOW
# is what sits in that slot, and 'elbow circumference' is simply not the ANSUR forearm
# dimension. The earlier version of this table blocked on upperarm > elbow > wrist while
# quoting the FOREARM > wrist violation rate (0.0000%) as its licence to do so — a
# MEASURED rate for a step the gate does not apply.
#
# So each step carries its own evidence and its own right to block:
#   blocking=True  -> the surveyed analogue is violated by 0 of 6,068 real subjects
#   blocking=False -> no ANSUR column exists for this step. It may WARN, never FAIL, and
#                     it carries the nearest surveyed analogue's rate so the reader can
#                     see what "nearest" is worth.
# `violation_male/female` and `min_margin_mm` are the rate and the smallest real margin of
# the step's own survey analogue, MEASURED 2026-08-05 by direct recomputation from the two
# public working databases (male n=4082, female n=1986).
HARD_GIRTH_CHAINS = (
    dict(
        name='arm',
        keys=('upperarm_circumference_relaxed_r', 'elbow_circumference_r', 'wrist_circumference_r'),
        steps=(
            dict(
                hi='upperarm_circumference_relaxed_r',
                lo='wrist_circumference_r',
                blocking=True,
                survey_pair='bicepscircumferenceflexed > wristcircumference',
                violation_male=0.0,
                violation_female=0.0,
                min_margin_mm=(73.0, 86.0),
                evidence='the END-TO-END step, and the only step of this chain with '
                'survey evidence: biceps (flexed) exceeds wrist in every one '
                'of the 6,068 ANSUR subjects, smallest real margin 73 mm '
                '(male) / 86 mm (female).',
            ),
            dict(
                hi='upperarm_circumference_relaxed_r',
                lo='elbow_circumference_r',
                blocking=False,
                survey_pair=None,
                nearest_survey_pair=('bicepscircumferenceflexed > forearmcircumferenceflexed'),
                violation_male=0.002695,
                violation_female=0.002014,
                min_margin_mm=(-14.0, -4.0),
                evidence='ANSUR II HAS NO ELBOW CIRCUMFERENCE COLUMN, so no rejection '
                'rate for this step can exist and it may not block. The '
                'nearest surveyed analogue, biceps > forearm (both flexed), '
                'is violated by 0.2695% of men and 0.2014% of women with a '
                'smallest margin of -14 mm / -4 mm — i.e. even the analogue '
                'is violated by real people, which is the second reason this '
                'step warns.',
            ),
            dict(
                hi='elbow_circumference_r',
                lo='wrist_circumference_r',
                blocking=False,
                survey_pair=None,
                nearest_survey_pair='forearmcircumferenceflexed > wristcircumference',
                violation_male=0.0,
                violation_female=0.0,
                min_margin_mm=(81.0, 73.0),
                evidence='the analogue forearm > wrist is violated by 0 of 6,068 '
                'subjects (smallest margin 81 mm / 73 mm), but the ELBOW is '
                'not the forearm maximum: it is a different site on a '
                'different bone landmark and ANSUR measures no elbow at all, '
                'so the 0% belongs to the analogue and not to this step. '
                'HOUSE, and it may only warn.',
            ),
        ),
        caveat='Only the end-to-end step upper arm > wrist inherits the 0-violation '
        'evidence. The two elbow steps are HOUSE and warn.',
    ),
    dict(
        name='leg',
        keys=('thigh_circumference_r', 'calf_circumference_r', 'ankle_circumference_r'),
        steps=(
            dict(
                hi='thigh_circumference_r',
                lo='calf_circumference_r',
                blocking=True,
                survey_pair='thighcircumference > calfcircumference',
                violation_male=0.0,
                violation_female=0.0,
                min_margin_mm=(107.0, 122.0),
                evidence='holds in every one of the 6,068 ANSUR subjects; smallest '
                'real margin 107 mm (male) / 122 mm (female).',
            ),
            dict(
                hi='calf_circumference_r',
                lo='ankle_circumference_r',
                blocking=True,
                survey_pair='calfcircumference > anklecircumference',
                violation_male=0.0,
                violation_female=0.0,
                min_margin_mm=(100.0, 98.0),
                evidence='holds in every one of the 6,068 ANSUR subjects; smallest '
                'real margin 100 mm (male) / 98 mm (female).',
            ),
        ),
        caveat='Both leg steps are measured directly by ANSUR at the same three sites '
        'this cage measures, so both may block.',
    ),
)
GIRTH_CHAIN_SOURCE = (
    'MEASURED 2026-08-05 by direct recomputation from the ANSUR II 2012 public working '
    'databases on disk (male n=4082, female n=1986): per-subject violation rate and '
    'smallest real margin of each step, computed for the step the gate actually applies. '
    'Steps with no ANSUR column (every step involving the elbow) carry no rate and may '
    'not block.'
)

# ---------------------------------------------------------------------------------
# Adult age channel — MEASURED 2026-08-05, ANSUR II, ratio regressed on AGE IN YEARS over
# the full 17-58 range. The point of the table is the contrast: girth ratios carry the age
# signal (waist/stature r=+0.40) and skeletal ratios do not (crotch/stature r=-0.08).
# Cross-sectional, on a fit military population, so the girth slope is SMALLER than the
# +12.5 cm waist quoted for civilian 25->43 cohorts; ours is +7.7 cm (male 23-27 y vs
# 41-45 y, n=1028 vs 361). The MEASURED number is the one shipped.
# ---------------------------------------------------------------------------------
AGE_CHANNEL = {
    'girth': {
        'waist_circumference_omphalion_over_stature': {
            'male': dict(slope_per_year=0.002817, intercept=0.450916, resid_sd=0.05748, r=0.396, n=4082),
            'female': dict(slope_per_year=0.002221, intercept=0.464631, resid_sd=0.05730, r=0.307, n=1986),
        },
        'chest_circumference_over_stature': {
            'male': dict(slope_per_year=0.001980, intercept=0.543565, resid_sd=0.04628, r=0.353, n=4082),
            'female': dict(slope_per_year=0.001966, intercept=0.524910, resid_sd=0.04733, r=0.327, n=1986),
        },
        'buttock_circumference_over_stature': {
            'male': dict(slope_per_year=0.000937, intercept=0.552565, resid_sd=0.04093, r=0.198, n=4082),
            'female': dict(slope_per_year=0.001219, intercept=0.592130, resid_sd=0.04264, r=0.232, n=1986),
        },
    },
    'skeletal': {
        'crotch_height_over_stature': {
            'male': dict(slope_per_year=-0.000126, r=-0.079, n=4082, pop_sd=0.014126),
            'female': dict(slope_per_year=-0.000182, r=-0.100, n=1986, pop_sd=0.015050),
        },
        'cervicale_height_over_stature': {
            'male': dict(slope_per_year=0.000149, r=0.197, n=4082, pop_sd=0.006510),
            'female': dict(slope_per_year=0.000030, r=0.037, n=1986, pop_sd=0.006820),
        },
        'tibiale_height_over_stature': {
            'male': dict(slope_per_year=0.000057, r=0.061, n=4082, pop_sd=0.008130),
            'female': dict(slope_per_year=0.000009, r=0.009, n=1986, pop_sd=0.008440),
        },
    },
}
AGE_CHANNEL_SOURCE = (
    'MEASURED 2026-08-05, ANSUR II 2012 public working databases, '
    'ratio ~ age(years) least squares over 17-58 y, male n=4082 / '
    'female n=1986'
)
# HOUSE. The briefing puts adult skeletal drift under 0.6% for 25->43; measured here it is
# -0.47% (crotch/stature, male) and -0.34% (cormic), so 0.6% is a ceiling the data clears.
SKELETAL_AGE_DRIFT_CEILING = 0.006

# ---------------------------------------------------------------------------------
# Child proportions. The DIRECTION of each assertion is HOUSE (it comes from the research
# briefing's reading of the growth literature, which is not on disk and cannot be verified
# here). The cormic numbers ARE measured, from NHANES III on disk.
# ---------------------------------------------------------------------------------
CHILD_CORMIC = {
    'male': dict(
        child_12y_mean=0.5057, child_12y_sd=0.0142, child_n=204, adult_25_45_mean=0.5218, adult_sd=0.0155, adult_n=3071
    ),
    'female': dict(
        child_12y_mean=0.5147, child_12y_sd=0.0150, child_n=221, adult_25_45_mean=0.5280, adult_sd=0.0150, adult_n=3641
    ),
}
CHILD_CORMIC_SOURCE = (
    'MEASURED 2026-08-05 from NHANES III body-measurement file on disk '
    '(n3b.csv, US civilian, missing codes 8888/88888 dropped): sitting '
    'height / standing height at age 12 vs age 25-45'
)
# Each entry: (ratio key, required direction vs the convention-matched adult, why).
CHILD_PROPORTION_ASSERTIONS = (
    (
        'head_length_over_stature',
        'above',
        'the head reaches ~96% of its adult length at ~85% of adult stature, so head/stature is HIGHER in a child',
    ),
    ('head_circumference_over_stature', 'above', 'same growth argument as head length, on the circumference'),
    (
        'crotch_height_over_stature',
        'above',
        'a 12-year-old cormic index (~0.506 measured) is LOWER than an adult (~0.522), i.e. '
        'legs proportionally longer, which shows on a standing mesh as a higher crotch',
    ),
    (
        'hand_length_over_stature',
        'above_or_equal',
        'growth is distal-to-proximal, so hands are proportionally large in a child',
    ),
    (
        'foot_length_over_stature',
        'above_or_equal',
        'growth is distal-to-proximal, so feet are proportionally large in a child',
    ),
)
CHILD_DIRECTION_PROVENANCE = HOUSE
CHILD_DIRECTION_SOURCE = (
    'HOUSE. Direction taken from the research briefing (distal-to-proximal growth; head '
    '~96% of adult length at ~85% of adult stature). No child hand/foot survey is on '
    'disk, so the MAGNITUDE is not gated, only the sign. The adult bar is measured '
    'through this identical pipeline, so the comparison is convention-matched.'
)

# ---------------------------------------------------------------------------------
# Ancestry, the largest proportion effect in the pack. ONE copy of these numbers, because
# three hand-typed copies is how a wrong estimator survives: the figures previously quoted
# here (.4952/.4796/.4788/.4712) were the RATIO OF THE TWO COLUMN MEANS, which is not the
# statistic anything in this package uses. build_reference._ratio_values computes a
# PER-SUBJECT ratio and every band, percentile and gate in the pack is built on that, so
# the per-subject group mean is what gets quoted. Verified to 6 dp against the pack's own
# stats block and by direct recomputation from the shipped CSV.
# ---------------------------------------------------------------------------------
ANCESTRY_LEG_RATIO = 'crotch_height_over_stature'
ANCESTRY_LEG_MEANS_MALE = (('Black', 0.4951), ('White', 0.4794), ('Hispanic', 0.4787), ('Asian', 0.4711))
ANCESTRY_LEG_SPREAD = 0.02396
ANCESTRY_LEG_SOURCE = (
    'MEASURED 2026-08-05: per-DODRace-group means of the PER-SUBJECT ratio '
    'crotch height / stature in ANSUR II male (n=4082: Black 642, White 2817, Hispanic '
    '440, Asian 117) — %s. Spread %.5f. These are per-subject means, NOT the ratio of the '
    'two column means (which differs in the 4th decimal and is the statistic nothing in '
    'this pack uses).' % (', '.join('%s %.4f' % (g, m) for g, m in ANCESTRY_LEG_MEANS_MALE), ANCESTRY_LEG_SPREAD)
)

# HOUSE. CDC z is a size statement, not a proportion statement. |z|<=2 is the ordinary
# 2.3-97.7 percentile range; 2<|z|<=3 warns; beyond 3 the declared age and the delivered
# size disagree badly enough to block.
CDC_Z_WARN = 2.0
CDC_Z_FAIL = 3.0

# ---------------------------------------------------------------------------------
# Cast diversity. MEASURED calibration: Mahalanobis separation between two RANDOM real
# same-sex ANSUR subjects, over the four vector components this cage can actually
# measure, from the per-subject vectors in the pack (400k sampled pairs, seed 7).
# ---------------------------------------------------------------------------------
CAST_VECTOR_COMPONENTS = (
    'cervicale_height_over_stature',
    'acromial_height_over_stature',
    'crotch_height_over_stature',
    'tibiale_height_over_stature',
)
CAST_PAIR_CALIBRATION = {
    'male': dict(mean=2.6534, p0_1=0.4221, p1=0.7653, p5=1.1810, p50=2.5774, p99=5.2036),
    'female': dict(mean=2.6580, p0_1=0.4349, p1=0.7682, p5=1.1867, p50=2.5867, p99=5.2077),
}
CAST_PAIR_SOURCE = (
    'MEASURED 2026-08-05 from data/assets/anthro_reference/'
    'mahalanobis.npz per-subject vectors (ANSUR II, male n=4082, female '
    'n=1986), 4-component subset, ~400,000 random same-sex pairs'
)
# The table above is the recorded value; the gate recomputes the same null distribution at
# run time with this seed and sample count and reports both, so a drifted pack shows up as
# a disagreement instead of being masked by a frozen constant.
CAST_PAIR_SAMPLES = 400000
CAST_PAIR_SEED = 7
# HOUSE. Two characters closer than the 1st percentile of real same-sex pairs are more
# alike than 99% of randomly drawn pairs of real people — that is same-body syndrome. The
# p5 warn level exists because a cast is not a random sample: two characters built from
# one recipe land there long before they land at p1.
CAST_SAME_BODY_PERCENTILE = 1.0
CAST_SIMILAR_PERCENTILE = 5.0

# ---------------------------------------------------------------------------------
# Stylization reporting. The 8-head canon is an ART CONVENTION with no survey source; it
# is REPORTED as a delta so stylization is visible as a number and is NEVER gated.
# ---------------------------------------------------------------------------------
CANON_HEADS_TALL = 8.0
CANON_SOURCE = (
    'ART CONVENTION (classical figure-drawing canon). NOT a survey statistic '
    'and NOT a target. ANSUR II has no menton-to-vertex head height, so no '
    '"heads tall" figure may be cited to a survey. Reported as a delta only.'
)
STYLIZATION_AXIS = 'proportions'
STYLIZATION_AXIS_NOTE = (
    'anny/MakeHuman ships a BodyProportions macro (108 targets split '
    'idealproportions/uncommonproportions) exposed as the phenotype key %r. The '
    'stylization axis is that NAMED PARAMETER and must be recorded per character with an '
    'intent, not left to whatever the builder defaulted to.' % STYLIZATION_AXIS
)

# ---------------------------------------------------------------------------------
# Realism asymmetry. Kept API-DISTINCT from the morph-correctness symmetry gate, which
# expects exactly zero. Merging them is how a broken morph gets excused as "realism".
# ---------------------------------------------------------------------------------
REALISM_ASYMMETRY_BAND_MM = (0.0, 10.0)
REALISM_ASYMMETRY_POP_MEAN_MM = 5.2

# The morph-symmetry tolerance's provenance, RE-STATED 2026-08-05. The text this replaced
# ("pure-morph bodies deviate 0.0014-0.0229 mm, sculpted bodies 2.93-3.76 mm") was the
# calibration of the OLD 0.05 mm tolerance and its own file now refutes it: the
# abs_definition sculpt was made symmetric by construction, and the two bodies it named as
# "sculpted, 2.93 / 3.76 mm" are pure-morph bodies measuring 0.0600 (cornelis) and 0.0632
# (male) mm. Shipping that string beside an observed 0.0632 mm invited exactly two false
# conclusions — that the male original is anomalous, or that the 0.15 mm band is 6.5x
# looser than its evidence — and it shipped as DATA, three times per report JSON.
SYM_MORPH_TOL_SOURCE = (
    'HOUSE tolerance %.2f mm, calibrated MEASURED 2026-08-05 by integrity.py over six '
    "bodies built with the sculpt layer mirror-symmetric: anny's own local-morph target "
    'data is NOT bit-mirror-symmetric, so a pure-morph body does not measure zero. Floor '
    'measured at 0.0632 mm (male original), then cornelis 0.0600, abel 0.0229, stock '
    'male/female 0.0167, female original 0.0014 — it rises with the number of fitted '
    'measure-* locals applied, i.e. it is the vendor data and not our geometry. %.2f mm '
    'clears that floor with ~2.4x headroom and still catches the defect the gate was '
    'built for (an asymmetric sculpt at 2.93-3.76 mm) by ~25x. Setting it below the floor, '
    'as the original 0.05 mm did, fails bodies with nothing wrong with them.'
    % (IG.SYM_MORPH_TOL_MM, IG.SYM_MORPH_TOL_MM)
)

# HOUSE. No survey publishes volume/stature^2, so a VHI band cannot be derived from
# anything on disk and the caller must declare one.
VHI_UNITS = 'L/m^2'

# ---------------------------------------------------------------------------------
# SEVERITY CALIBRATION — see rule 6 in the module docstring.
#
# The measurable sets below are module constants and not literals inside the gate bodies
# for one reason: the calibration must measure THE SAME BAND SET THE GATE CHECKS. If the
# gate and its calibration each carried their own copy of the ratio list, a ratio added to
# one and not the other would produce a rejection rate for a gate that does not exist,
# which is a worse failure than the one this whole exercise is fixing.
# ---------------------------------------------------------------------------------
# HOUSE ceiling, anchored on a MEASURED calibration — and the anchor is stated as what it
# is. 1% is the DESIGN rate of the pack's primary plausibility MODEL: a threshold that IS
# the empirical p99 of joint D^2 rejects 1% of the sample it came from by construction
# (measured 1.004% male / 1.007% female on the shipped per-subject vectors). It is NOT a
# claim about the GATE that runs that model here: on this cage one of the gate's four
# coordinates is a HOUSE substitution and the same threshold rejects 1.176% of real men,
# which is why t2_mahalanobis is itself downgraded to 'warn' by this policy. So the
# sentence "anything blocking looser than the primary gate would be the tail wagging the
# dog" is true of the MODEL and no longer true of any gate in this registry — nothing in
# here blocks on a population claim at all, and the table says so out loud.
SEVERITY_REJECTION_CEILING = 0.01
SEVERITY_POLICY = (
    "a gate may carry severity 'block' only if, run as configured, it would reject at "
    'most %.1f%% of the real ANSUR II reference sample (plus 1/n, the granularity of an '
    'empirical percentile on that sample). Otherwise it is downgraded to '
    "'warn'. Structural gates — cage integrity, landmark ordering, morph bounds, the "
    'build-target stature check, provenance, and bands the CALLER declared — are not '
    'statistical statements about a population and keep their declared severity.' % (100.0 * SEVERITY_REJECTION_CEILING)
)
ANSUR_REFERENCE_POPULATION = 'the real ANSUR II sample (US Army, male n=4082, female n=1986, 17-58 y)'
SEVERITY_POLICY_PROVENANCE = HOUSE
SEVERITY_POLICY_SOURCE = (
    'HOUSE policy on MEASURED rates. The ceiling is the DESIGN rejection rate of the '
    "pack's primary plausibility MODEL (empirical p99 of joint D^2 = 1% by construction, "
    '1.004% male / 1.007% female as measured on the shipped per-subject vectors) — not '
    'the rate of any gate in this registry, including the gate that runs that model: on '
    'this cage t2_mahalanobis substitutes a HOUSE value for the cervicale coordinate and '
    'rejects 1.176% of real men, so it is downgraded by this same policy. The rates the '
    'ceiling is compared against are measured at run time from the ANSUR II per-subject '
    'microdata shipped inside the reference pack (male n=4082, female n=1986). Motivating '
    'measurement, from the pack itself: ten independent p5-p95 bands admit only 47.16% '
    'of real men and 46.0% of real women.'
)

# Calibration kinds. The first four measure a rate; the last three declare, explicitly,
# that no rate against the reference sample exists for this gate and why.
CAL_RATIO_BANDS = 'ratio_bands'
CAL_STATURE_ANCHORED = 'stature_anchored'
CAL_EMPIRICAL_PERCENTILE = 'empirical_percentile'
CAL_LMS_Z = 'lms_z'
CAL_VIOLATION_RATE = 'measured_violation_rate'
CAL_DECLARED_BAND = 'caller_declared_band'
CAL_STRUCTURAL = 'structural'
CAL_PRINTED_BAND = 'printed_band'
CAL_UNDECLARED = 'undeclared'
CALIBRATION_KINDS = (
    CAL_RATIO_BANDS,
    CAL_STATURE_ANCHORED,
    CAL_EMPIRICAL_PERCENTILE,
    CAL_LMS_Z,
    CAL_VIOLATION_RATE,
    CAL_DECLARED_BAND,
    CAL_STRUCTURAL,
    CAL_PRINTED_BAND,
    CAL_UNDECLARED,
)

# The band sets the wide gates check, as (ratio_key, predictability_dimension) pairs.
BREADTH_RATIOS = (
    ('bideltoid_breadth_over_stature', 'bideltoid_breadth'),
    ('chest_breadth_over_stature', 'chest_breadth'),
    ('waist_breadth_over_stature', 'waist_breadth'),
    ('hip_breadth_over_stature', 'hip_breadth'),
    ('head_breadth_over_stature', 'head_breadth'),
)
GIRTH_RATIOS = (
    ('neck_circumference_over_stature', 'neck_circumference'),
    ('shoulder_circumference_over_stature', 'shoulder_circumference'),
    ('chest_circumference_over_stature', 'chest_circumference'),
    ('waist_circumference_omphalion_over_stature', 'waist_circumference_omphalion'),
    ('buttock_circumference_over_stature', 'buttock_circumference'),
    ('thigh_circumference_over_stature', 'thigh_circumference'),
    ('calf_circumference_over_stature', 'calf_circumference'),
    ('wrist_circumference_over_stature', 'wrist_circumference'),
    ('head_circumference_over_stature', 'head_circumference'),
)
DEPTH_RATIOS = (('chest_depth_over_stature', 'chest_depth'), ('buttock_depth_over_stature', 'buttock_depth'))
# (mesh measurement key, pack dimension). cervicale_height_house is a HOUSE substitution
# on the mesh side; the BAND it is judged against is the real ANSUR cervicale_height, so
# that is the dimension the calibration measures.
TIGHT_HEIGHT_PAIRS = (
    ('acromial_height', 'acromial_height'),
    ('suprasternale_height', 'suprasternale_height'),
    ('waist_height_omphalion', 'waist_height_omphalion'),
    ('trochanterion_height', 'trochanterion_height'),
    ('buttock_height', 'buttock_height'),
    ('crotch_height', 'crotch_height'),
    ('tibiale_height', 'tibiale_height'),
    ('cervicale_height_house', 'cervicale_height'),
)
# The only FAIL-capable thresholds in t2_adult_age_channel: the girth channel may warn but
# never fail, so calibrating on it would describe a rejection that cannot happen.
AGE_CHANNEL_BLOCKING_RATIOS = tuple(sorted(AGE_CHANNEL['skeletal']))
# The width _band_check fails on, and the width it warns on. Named here because the
# calibration has to quote them.
BAND_WIDTH_BLOCK = 'p1p99'
BAND_WIDTH_WARN = 'p5p95'


# ---------------------------------------------------------------------------------
# WHICH BANDS THE GATE CAN ACTUALLY FAIL ON
#
# _band_check demotes a ratio to REPORT — unconditionally, for every subject — when
# measure.py marks the underlying measurement survey_comparable=False (A-pose bideltoid
# and shoulder circumference, bald head breadth/circumference). _wide_gate does the same
# when the pack's predictability policy for the dimension is not 'wide'. Neither can ever
# produce a FAIL or a WARN, so counting them in the severity calibration answers "what
# would this gate reject" for a gate that does not exist — the exact error the comment
# above the ratio lists warns about, applied to the lists themselves.
#
# The flags are read out of measure.py's STATIC spec tables rather than copied, so a spec
# that changes its mind about comparability changes the calibration with it. A ratio the
# scan cannot find is treated as GATEABLE: absence of evidence must widen the measured
# rejection rate (which can only take a blocking claim away), never narrow it.
# ---------------------------------------------------------------------------------
_RATIO_FLAG_CACHE = {}


def _measure_ratio_flags():
    """{ansur ratio key: {'survey_comparable': bool, 'because': str, 'spec': name}} read
    from measure.py's module-level spec tables."""
    if 'v' in _RATIO_FLAG_CACHE:
        return _RATIO_FLAG_CACHE['v']
    out = {}
    for container, val in sorted(vars(ME).items()):
        if not isinstance(val, (tuple, list)) or not val:
            continue
        if not all(isinstance(x, dict) for x in val):
            continue
        for spec in val:
            key = spec.get('ansur')
            if not key:
                continue
            comparable = spec.get('survey_comparable', True) is not False
            prev = out.get(key)
            # If two specs publish the same ratio, the STRICTER answer wins: one
            # non-comparable source makes the ratio non-comparable, which is also what
            # measure.py's own flags() does for composite indices.
            if prev is None or (prev['survey_comparable'] and not comparable):
                out[key] = {
                    'survey_comparable': comparable,
                    'because': spec.get('survey_reason'),
                    'spec': '%s[%s]' % (container, spec.get('name')),
                }
    _RATIO_FLAG_CACHE['v'] = out
    return out


def _gateable_bands(ratios, policy=None):
    """Split a calibration band set into the bands the gate can FAIL on and the rest.

    `ratios` is the (ratio_key, dimension) pair list the gate itself iterates, or a plain
    key list. `policy` is the predictability policy the gate requires ('wide' for the wide
    gates); None means the gate applies no policy filter.

    Returns (gateable_keys, excluded) where excluded is a list of
    {'ratio', 'why'} records that travel into the calibration so the exclusion is
    auditable and cannot become a quiet narrowing of the measured rate.
    """
    flags = _measure_ratio_flags()
    gateable, excluded = [], []
    for r in ratios:
        key, dim = r if isinstance(r, (tuple, list)) else (r, None)
        f = flags.get(key)
        if f is not None and not f['survey_comparable']:
            excluded.append(
                {
                    'ratio': key,
                    'why': 'measure.py marks %s survey_comparable=False, so _band_check '
                    'demotes it to REPORT for every subject and it can never '
                    'FAIL: %s' % (f['spec'], f['because'] or 'no reason given'),
                }
            )
            continue
        if policy is not None and dim is not None:
            got = reference().predictability(dim)['policy']
            if got != policy:
                excluded.append(
                    {
                        'ratio': key,
                        'why': 'the pack classes %s as %r, not %r, so the gate reports '
                        'it instead of banding it' % (dim, got, policy),
                    }
                )
                continue
        gateable.append(key)
    return tuple(gateable), excluded


class GateConfigError(Exception):
    """Raised before any mesh is touched, when the gate registry itself is unshippable."""


class SubjectError(Exception):
    """Raised when a subject cannot be assembled from what the pipeline recorded."""


# ---------------------------------------------------------------------------------
# THE REGISTRY
#
# Every gate carries a CALIBRATION SPEC beside its threshold. The spec says how the gate's
# right to block is to be measured against the reference sample; validate_registry refuses
# a gate that does not have one, and refuses a structural exemption that does not say why.
# The severity column below is therefore the DECLARED severity — read the calibration
# spec, or the severity table the engine prints, for the one that actually governs.
# ---------------------------------------------------------------------------------
# A gate that cannot fail should say so rather than imply it earned its pass (adversarial
# review D8, recorded as INFORMATIONAL and not as a defect). Six tier-5 gates are in this
# class: the anchor they need is absent from the rig or from the 256-label landmark
# vocabulary on every character, so no body this pipeline can build reaches their band and
# no broken control can be handed to them through the registered path. They stay registered
# because a gate that is absent and a gate that cannot run look identical in a report that
# omits one of them — and because the evidence for the refusal is the useful part.
CANNOT_FAIL_NOTE = (
    'THIS GATE CANNOT PRODUCE A FAIL ON ANY BODY THIS PIPELINE CAN BUILD. Measured '
    '2026-08-06 over abel, cornelis, male, female and anny-neutral: not_implementable, '
    'rendered `skip`, on 5 of 5 — never a pass. Its anchor does not exist on this rig or '
    'in the 256-label landmark vocabulary, so there is no broken control that could reach '
    'it through the registered path and its ability to reject is UNDEMONSTRATED. It is '
    'registered so that "the check did not run" is visible instead of absent.'
)


def _structural(why):
    """Not a statistical claim about a population: keeps its declared severity."""
    return {'kind': CAL_STRUCTURAL, 'why': why}


def _printed_band(why, source=None):
    """A number read off a page. There is no sample behind it, so no rejection rate can be
    produced for it — and calibrate_gate therefore TAKES ANY BLOCKING CLAIM AWAY from it
    automatically (block -> warn, with the reason printed in the severity table).

    That downgrade is the mechanism, not an accident: it is how a drawing convention is
    stopped from failing a body by arithmetic rather than by reviewer attention. A tier-5
    gate that must genuinely block declares _structural() instead, and then it has to say
    why its subject is our rig or our registry rather than a person.
    """
    return {'kind': CAL_PRINTED_BAND, 'why': why, 'source': source}


def _bands(ratios, width=BAND_WIDTH_BLOCK, policy=None):
    """Fails when a measured ratio leaves a population band. `ratios` may be the
    (ratio, dimension) pair tuples the wide gates use.

    The PAIRS are kept, not just the keys, and `policy` records the predictability filter
    the gate itself applies — calibrate_gate re-applies both filters before measuring, so
    the rate describes the bands this gate can fail on rather than every band named here.
    The filtering happens at calibration time and not here on purpose: building the
    registry must not require the reference pack to be loadable.
    """
    keys = [r[0] if isinstance(r, (tuple, list)) else r for r in ratios]
    return {'kind': CAL_RATIO_BANDS, 'ratios': keys, 'pairs': list(ratios), 'width': width, 'policy': policy}
