# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The measured constants, the resolution contract and the AFS p.63 fat-invariant roster.

Moved verbatim out of the old single-file ridge.py (lines 198-206, 262-766).
"""

from zyg_workflows.geom.form import curvature as CV


import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def _require(cond: object, msg: str) -> None:
    """Raise :class:`RuntimeError` when *cond* is falsy — an ``assert`` that survives ``-O``."""
    if not cond:
        raise RuntimeError(msg)


# ---------------------------------------------------------------------------------
# geometry of the primitive. HOUSE, in fractions of stature so the same physical band is
# used on a 1.52 m child and a 1.85 m adult. These are not thresholds and nothing passes or
# fails because of them: ridge_null() is measured with THE SAME geometry, so whatever they
# are, the false-positive rate quoted against them is the true one.
# ---------------------------------------------------------------------------------
RIDGE_CORE_FRAC = 0.004  # crest half-width, 6.7 mm at 1.686 m. A clavicle is ~10-15
# mm wide (AFS p.35 plates); the crest patch must sit inside
# the bone, not on its shoulder.
RIDGE_GAP_FRAC = 0.008  # 13.5 mm. Strictly wider than curvature.COLLAR_GAP_FRAC
# (0.006) because a whole-bone feature has a wider shoulder
# than a point one.
RIDGE_WIDTH_FRAC = CV.COLLAR_WIDTH_FRAC  # 0.014 — curvature.py's own collar width
RIDGE_ALONG_STATIONS = 2  # +/- 2 stations of arc admitted to one station's collar
RIDGE_ALONG_WIDENING = (2, 3, 4, 6)  # tried in order; the value used is reported
RIDGE_N_STATIONS = 14  # stations per candidate curve
RIDGE_MIN_STATIONS = 5  # below this a "profile" is not a profile

# The isotropic probe this module is measured against: regions.FEATURE_PROBE_RADIUS. Named
# here rather than imported so the core primitives do not depend on regions.py loading.
POINT_PROBE_RADIUS_FRAC = 0.012

# Candidate-curve search multiplicity. ridge_null() is measured at exactly these numbers;
# changing either without re-running the null invalidates the run threshold.
SEARCH_N_DIRECTIONS = 6
SEARCH_N_OFFSETS = 7

# ---------------------------------------------------------------------------------
# PER-STATION CUT — inherited unchanged from curvature.RELIEF_NULL_P99, which is the p99 of
# |relief| and |contrast| over 298 random patches of the neutral's own torso and limb skin.
# MEASURED, provenance 'MEASURED-NULL'. This module may raise it (see ridge_null) and may
# never lower it: a station that does not clear the cage's own p99 is not relief, whatever
# primitive found it.
# ---------------------------------------------------------------------------------
STATION_MIN_FRAC_STATURE = CV.RELIEF_NULL_P99['min_frac_stature']  # 2.45e-3
STATION_MIN_CONTRAST = CV.RELIEF_NULL_P99['min_contrast']  # 3.7

# The false-positive rate a RESOLVING run is allowed to carry on landmark-free skin.
# 1% is the same alpha curvature.RELIEF_NULL_P99 is quoted at, so both halves of the
# criterion (per-station cut, run length) admit the same chance rate and the product can be
# stated. It is not a knob: moving it moves the advertised FPR with it.
RIDGE_NULL_ALPHA = 0.01

# THE SEED PANEL. Fixed, named and shipped, so that "the upper bound over the panel" is a
# deterministic rule somebody can re-run and reproduce exactly — not an open-ended maximum
# that creeps every time another draw is taken. 24 seeds, fixed BEFORE any of them was
# scored, and deliberately including all seven the reviewer used (1, 7, 99, 31337, 424242,
# 20260805, 20260806) so their measurement and this one are comparable line by line.
RIDGE_NULL_SEED_PANEL = (
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    10,
    11,
    12,
    13,
    42,
    99,
    101,
    777,
    31337,
    424242,
    20260805,
    20260806,
    20260807,
    123456,
    987654,
)
RIDGE_NULL_PANEL_N_POOLS = 320  # per target size, so 960 pools per seed, 23,040 pooled

# ---------------------------------------------------------------------------------
# THE MEASURED NULL FOR THIS PRIMITIVE. RE-DERIVED 2026-08-07 OVER A 24-SEED PANEL,
# because the value it replaces was ONE DRAW, and one draw is not a measurement of this cage.
#
# WHAT WAS WRONG. ridge_null() at n_pools=40 scores 120 pools and reported `implied_min_run`
# = ceil(np.percentile(best_longest_run, 99)) + 1. best_longest_run is an INTEGER 0..14; the
# 99th percentile of 120 integers is fixed by the one or two most extreme pools and then
# INTERPOLATED to a value the statistic cannot take, so the +1 flips on noise. Re-run over 24
# seeds at that same n_pools — the identical experiment, only the RNG seed differing — the
# estimator returns, in mode 'ridge':
#
#     min_run   2 x1,  3 x18,  4 x4,  5 x1      station cut  2.931e-3 .. 3.389e-3
#
# and the seed that shipped, 20260806, is the UNIQUE seed of the 24 returning min_run 2, with
# the second-lowest station cut of the 24. Nobody chose it for being permissive. That is
# precisely why it could not stay: a threshold that is 1-of-24 permissive is
# indistinguishable from one tuned until our own bodies passed, and every landmark
# "resolution" the previous pass reported had run length 2 or 3.
#
# HOW IT IS DERIVED NOW — ridge_null_sweep(), one command:
#     python -m zyg_workflows.geom.form.ridge sweep 320
# 24 fixed seeds (RIDGE_NULL_SEED_PANEL) x 320 pools per target size (30/100/300) = 23,040
# landmark-free pools attempted, 22,957 scored, on the anny neutral's torso and limb skin at
# stature 1.68605 m, each pool searched with the same 6 directions x 7 offsets = 42 candidate
# curves x 14 stations this module uses in anger.
#
# TWO THINGS CHANGED IN THE ESTIMATOR, not merely in the sample size.
# (1) COUNTS, NOT PERCENTILES. A histogram of an integer statistic is ADDITIVE across seeds;
#     a percentile is not. So the seeds pool into one experiment instead of being averaged.
# (2) min_run is the EXCEEDANCE form: the shortest run whose chance of occurring on
#     landmark-free skin is already <= RIDGE_NULL_ALPHA. That is what "p99 + 1" was reaching
#     for, computed on the integer the statistic actually is.
#
# POOLED OVER 22,957 LANDMARK-FREE POOLS — best same-sign qualifying run per pool:
#
#   run length             0       1      2     3    4   5
#   mode 'ridge'       16289    5415   1016   153   72  12
#   mode 'point'       21039     942    976     0    0   0
#
#   P(run >= r)   r=1      r=2      r=3      r=4      r=5
#   mode 'ridge'  29.05%   5.458%   1.032%   0.366%   0.052%
#   mode 'point'   8.35%   4.251%   0.000%   0.000%   0.000%
#
# THE CHOICE, STATED PLAINLY: THE PANEL UPPER BOUND. Not the median, and never a draw.
#   'ridge' min_run   per-seed at n_pools=320: 3 x12, 4 x12 (median 3.5, MAX 4)
#                     pooled over all 22,957 pools:                            4
#                     -> SHIPS 4. Point estimate and upper bound AGREE, so there was no
#                     third option to pick between. P(run >= 3) = 1.032% is ABOVE the 1%
#                     the criterion advertises; 3 cannot be certified at alpha and 4 can
#                     (0.366%).
#   'ridge' station   per-seed at n_pools=320: min 3.107e-3, median 3.184e-3, MAX 3.284e-3
#                     -> SHIPS 3.284e-3, the panel MAXIMUM. The median (3.184e-3) would be
#                     defensible as a point estimate; the maximum ships because the two
#                     error directions are not symmetric. Too low manufactures anatomy this
#                     cage does not carry. Too high under-claims a landmark that is really
#                     there — and an under-claim is a result we can publish. The value it
#                     replaces, 2.973e-3, sits BELOW the panel minimum at every n_pools >= 80.
#   'point'           unanimous: 24 of 24 seeds return min_run 3 at every n_pools >= 80, and
#                     the mode's own p99 stays under the published isotropic cut on every
#                     seed, so it keeps curvature.RELIEF_NULL_P99 (2.45e-3 / 3.7) unchanged.
#                     Point mode was already right. It is not touched.
#
# WHY NOT THE POOLED ESTIMATE EVERYWHERE, given it is 22,957 samples? Because those are not
# 22,957 INDEPENDENT samples. The skin mask holds 3,311 vertices and every seed draws its
# pool centres from that same set, so 24 seeds resample the same geometry about seven times
# over. The naive binomial interval on 1.032% (+/- 0.13%) therefore UNDERSTATES the
# uncertainty, while the panel spread does see the resampling. The upper end of that spread
# is the number that cannot manufacture a landmark.
#
# ONE INCONSISTENCY, STATED RATHER THAN HIDDEN. The pooled run histogram was accumulated
# with each seed scoring at ITS OWN per-station cut, not at the panel-maximum cut that ships.
# The shipped cut is >= every seed's cut, and raising a cut can only UN-qualify stations, so
# runs at the shipped cut are equal or shorter and the true exceedance is <= the one measured
# above. min_run 4 therefore remains valid — its real FPR is at most the 0.366% quoted — but
# it is CONSERVATIVE rather than provably minimal: at the shipped cut, P(run >= 3) might
# itself fall under alpha. The error runs toward under-claiming, which is the direction this
# module is allowed to err in, and it is written down here so the next person does not
# rediscover it as a defect.
#
# SPREAD AS A FUNCTION OF n_pools — the evidence for running the panel at 320:
#
#   n_pools   per-seed min_run, mode 'ridge'    station cut e-3  min/median/max    cv
#      40     2 x1, 3 x18, 4 x4, 5 x1           2.931 / 3.159 / 3.389           4.18%
#      80            3 x16, 4 x7, 5 x1          3.012 / 3.141 / 3.402           3.01%
#     160            3 x13, 4 x11               3.001 / 3.190 / 3.287           1.71%
#     320            3 x12, 4 x12               3.107 / 3.184 / 3.284           1.27%
#
# The per-station cut CONVERGES (cv 4.18% -> 1.27%). The per-seed min_run does NOT collapse
# to a single integer even at 960 pools per seed, because the true exceedance at run 3 sits
# almost exactly on alpha (1.032% against 1.000%). A statistic straddling its own threshold
# cannot be settled by one seed at any n_pools — that is the general form of the defect this
# constant had. It is settled by pooling the counts, and by refusing the permissive side of
# the straddle.
#
# WHAT THE OLD CONSTANT ACTUALLY COST. min_run 2 in mode 'ridge' carried a MEASURED
# false-positive rate of 5.79% on landmark-free skin — 5.8x the 1% the criterion advertises.
# Every resolution claimed at run length 2 or 3 was inside that.
#
# AND THE CONVERSE, WHICH IS THE POINT OF THE `null_rate_*` FIELDS BELOW. min_run is the
# alpha point, so every run length BELOW it is INSIDE the null. A run of 1 is not weak
# evidence of a landmark; it is the modal non-zero outcome of pointing this primitive at skin
# that has no landmark on it — 29.05% of landmark-free pools in mode 'ridge', 8.35% in mode
# 'point'. A probe is scored under BOTH modes and counted resolved if EITHER resolves, so the
# rate governing a resolution claim is the union: 0.37% for the resolved class, but 34.98%
# for "resolved OR point_only". That second number is not a threshold anybody may use.
# See RESOLVED_VERDICTS.
#
# min_run_any_sign is the same derivation on the ANY-SIGN run, which is >= the same-sign run
# by construction and is therefore a DIFFERENT and never-smaller null. Pooled over the panel
# it comes out equal to min_run in both modes — but it is read off its own distribution,
# because "equal today" is not the same claim as "read off the right null".
#
# EVERY NUMBER BELOW IS REPRODUCIBLE. The seeds, the pool count, the pooled histograms and
# the exceedance table are shipped IN the constant, and self_test() asserts the shipped
# min_run against them, so a hand-edited threshold fails the test rather than passing quietly.
# ---------------------------------------------------------------------------------
RIDGE_NULL_P99 = {
    'ridge': {
        'min_run': 4,
        'station_min_frac_stature': 3.2841308722575736e-3,
        'station_min_contrast': 4.3052630687635896,
        'null_p99_run': 3,
        'min_run_any_sign': 4,
        'null_p99_run_any_sign': 3,
        'null_rate_point_only_or_better': 0.29045607004399532,
        'null_rate_resolved': 0.003659014679618417,
        # The panel this was read off, so the shipped number can be checked against
        # its own evidence without re-running 23,040 pools.
        'panel_min_run_hist': {3: 12, 4: 12},
        'panel_cut_frac_min_median_max': (3.1068951690505957e-3, 3.1842303127628509e-3, 3.2841308722575736e-3),
        'panel_cut_contrast_min_median_max': (4.1886991719808657, 4.2334968416323644, 4.3052630687635896),
        'pooled_run_hist': {0: 16289, 1: 5415, 2: 1016, 3: 153, 4: 72, 5: 12},
        'pooled_run_hist_any_sign': {0: 16289, 1: 5338, 2: 1086, 3: 160, 4: 72, 5: 12},
        'pooled_min_run': 4,
        'pooled_min_run_any_sign': 4,
        'superseded': {
            'min_run': 2,
            'station_min_frac_stature': 2.973146984749219e-3,
            'station_min_contrast': 4.159972680828111,
            'derived_from_seed': 20260806,
            'n_pools': 40,
            'measured_false_positive_rate': 0.05793439909395827,
            'why': 'single draw; unique minimum of 24 seeds on both axes; its advertised 1% FPR was measured at 5.79%',
        },
    },
    'point': {
        'min_run': 3,
        'station_min_frac_stature': STATION_MIN_FRAC_STATURE,
        'station_min_contrast': STATION_MIN_CONTRAST,
        'null_p99_run': 2,
        'min_run_any_sign': 3,
        'null_p99_run_any_sign': 2,
        'null_rate_point_only_or_better': 0.08354750185128719,
        'null_rate_resolved': 0.0,
        'panel_min_run_hist': {3: 24},
        'panel_cut_frac_min_median_max': (STATION_MIN_FRAC_STATURE,) * 3,
        'panel_cut_contrast_min_median_max': (STATION_MIN_CONTRAST,) * 3,
        'pooled_run_hist': {0: 21039, 1: 942, 2: 976},
        'pooled_run_hist_any_sign': {0: 21039, 1: 942, 2: 976},
        'pooled_min_run': 3,
        'pooled_min_run_any_sign': 3,
        'superseded': None,
    },
    'min_run': 4,  # default mode is 'ridge'
    'alpha': RIDGE_NULL_ALPHA,
    'n_candidates': 42,
    'n_stations': 14,
    'target_sizes': (30, 100, 300),
    'provenance': 'MEASURED-NULL',
    'measured_on': (
        'anny neutral (landmarks.REF_MALE) at stature 1.686050 m, torso+limb skin mask (3,311 vertices), 2026-08-07'
    ),
    # HOW TO RE-RUN EXACTLY WHAT PRODUCED THESE NUMBERS.
    'derivation': {
        'command': 'python -m zyg_workflows.geom.form.ridge sweep 320',
        'function': 'geom.form.ridge.ridge_null_sweep',
        'rule': (
            'PANEL UPPER BOUND: max over the fixed seed panel, cross-checked against '
            'the pooled-histogram point estimate. NOT the median, NOT a single draw.'
        ),
        'seeds': RIDGE_NULL_SEED_PANEL,
        'n_seeds': len(RIDGE_NULL_SEED_PANEL),
        'n_pools': RIDGE_NULL_PANEL_N_POOLS,  # per target size
        'pools_attempted': 23040,
        'pools_scored': 22957,
        'alpha': RIDGE_NULL_ALPHA,
        'date': '2026-08-07',
        'estimator': (
            'min_run = min{ r : P(best_longest_run >= r) <= alpha } on the POOLED '
            'seed histograms. The superseded value used '
            'ceil(np.percentile(runs, 99)) + 1 on a single 120-pool draw.'
        ),
        'spread_vs_n_pools': {  # per-seed min_run over the 24 seeds, mode 'ridge'
            40: {2: 1, 3: 18, 4: 4, 5: 1},
            80: {3: 16, 4: 7, 5: 1},
            160: {3: 13, 4: 11},
            320: {3: 12, 4: 12},
        },
        'cut_cv_vs_n_pools': {40: 0.0418, 80: 0.0301, 160: 0.0171, 320: 0.0127},
    },
}

VERDICTS = ('ridge', 'furrow', 'mixed_strip', 'point_only', 'flat', 'unmeasurable')

# ---------------------------------------------------------------------------------
# THE RESOLUTION CONTRACT — which verdicts mean "this cage carries the landmark".
#
# THIS LIVES HERE AND NOWHERE ELSE. A consumer that re-lists the verdict strings for itself
# is re-deriving a calibration decision from a name, and a name is not a threshold. The
# defect this replaces was exactly that: an adapter wrote
#     if vd in ('ridge', 'furrow', 'mixed_strip', 'point_only'):
# and thereby counted the module's own below-null verdict as a resolution. On abel that
# turned 0 resolved body landmarks into "8 of 20" — 0.40 against a measured chance rate of
# 0.3778 for the same criterion (z = 0.21), i.e. a headline indistinguishable from pointing
# the instrument at blank skin. Every consumer must read `resolves_relief` off the record
# rather than pattern-match the verdict.
#
# RESOLVED    the run cleared min_run, which is p99 + 1 of the null. Measured FPR per mode
#             0.83% (ridge) / 0.00% (point); <= 0.83% for "either mode", the criterion a
#             probe is actually scored on.
# BELOW_NULL  stations qualified but never min_run in a row ('point_only'), or none
#             qualified at all ('flat'). point_only is INSIDE the null by construction and
#             occurs on a third of landmark-free pools. It is reported — it is a real
#             measurement and the amplitude beside it is real — but it resolves nothing.
# NO_VERDICT  the primitive could not run: fewer than RIDGE_MIN_STATIONS measurable
#             stations. Not a statement about relief in either direction.
# ---------------------------------------------------------------------------------
RESOLVED_VERDICTS = frozenset(('ridge', 'furrow', 'mixed_strip'))
BELOW_NULL_VERDICTS = frozenset(('point_only', 'flat'))
NO_VERDICT_VERDICTS = frozenset(('unmeasurable',))

VERDICT_CLASS = dict(
    [(v, 'resolved') for v in RESOLVED_VERDICTS]
    + [(v, 'below_null') for v in BELOW_NULL_VERDICTS]
    + [(v, 'no_verdict') for v in NO_VERDICT_VERDICTS]
)

# Every verdict the primitive can emit is classified, and no verdict is classified twice.
# Asserted at import so a new verdict string cannot be added without a caller having to
# decide, in this file, which side of the null it falls on.
_require(
    set(VERDICT_CLASS) == set(VERDICTS),
    'VERDICT_CLASS does not classify exactly VERDICTS: %s' % (set(VERDICT_CLASS) ^ set(VERDICTS),),
)
_require(
    not (RESOLVED_VERDICTS & BELOW_NULL_VERDICTS)
    and not (RESOLVED_VERDICTS & NO_VERDICT_VERDICTS)
    and not (BELOW_NULL_VERDICTS & NO_VERDICT_VERDICTS),
    'the verdict classes overlap; a verdict cannot be both inside and outside the null',
)


_VERDICT_MEANING = {
    'ridge': 'a same-sign qualifying run of at least min_run=%(min_run)d stations, POSITIVE '
    '— outside the measured null (%(rate).2f%% of landmark-free pools reach this)',
    'furrow': 'a same-sign qualifying run of at least min_run=%(min_run)d stations, '
    'NEGATIVE — outside the measured null (%(rate).2f%% of landmark-free pools '
    'reach this)',
    'mixed_strip': 'a qualifying run of at least min_run_any=%(min_run_any)d stations that '
    'changes sign within the run — outside the any-sign null '
    '(%(rate).2f%%)',
    'point_only': 'stations qualified but never %(min_run)d in a row. INSIDE THE MEASURED '
    'NULL: %(rate).1f%% of landmark-free skin pools produce this by chance '
    'under the identical search. Resolves nothing; the amplitude beside it '
    'is real but it is one vertex, not a landmark',
    'flat': 'no station cleared the measured per-station cut. Probed and found flat',
    'unmeasurable': 'fewer than %(min_stations)d stations could be measured at all. NOT a '
    'statement about relief in either direction',
}


def resolves_relief(verdict):
    """True only for a verdict whose run cleared the mode's own measured null.

    The single place the question is answered. `point_only` returns False and always will:
    ridge_relief defines it as run_len < min_run and min_run is the null's p99 + 1, so
    point_only IS the null's measured support.
    """
    if verdict not in VERDICT_CLASS:
        raise ValueError(
            'unknown relief verdict %r — classify it in VERDICT_CLASS before '
            'any caller can ask whether it resolves anything' % (verdict,)
        )
    return verdict in RESOLVED_VERDICTS


# ---------------------------------------------------------------------------------
# CANON targets — plan section 2 priority list. REPORT ONLY.
# Provenance 'CANON' (artist canon) ranks BELOW 'MEASURED' (survey data). Per the plan's
# section 1.3 rule these may never carry block severity and may never be used as a pass
# threshold; they are printed beside the measurement so a reader can see how far the cage is
# from the book, which is the whole point of measuring.
# ---------------------------------------------------------------------------------
CANON_TARGETS = {
    'clavicle_shaft': dict(
        sign=+1, frac=3.0e-3, kind='ridge', src='AFS p.10 whole-bone; p.35-37 always visible arms down'
    ),
    'l_triangle': dict(sign=-1, frac=3.0e-3, kind='pit', src='AFS p.35 supraclavicular fossa; plan #1c'),
    'sternal_end': dict(sign=+1, frac=2.4e-3, kind='ridge', src='AFS p.10; plan #1'),
    'scapular_spine': dict(sign=+1, frac=2.4e-3, kind='ridge', src='AFS p.10 whole-bone'),
    'scapula_medial_border': dict(sign=+1, frac=2.2e-3, kind='ridge', src='AFS p.10'),
    'scapula_inferior_angle': dict(sign=+1, frac=2.0e-3, kind='ridge', src='AFS p.90'),
    'asis': dict(sign=+1, frac=3.2e-3, kind='ridge', src='AFS p.12/p.54; plan #4'),
    'psis': dict(sign=-1, frac=2.2e-3, kind='pit', src='AFS p.11, p.56; plan #5'),
    'olecranon': dict(sign=+1, frac=4.0e-3, kind='ridge', src='AFS p.156; plan #2'),
    'ulnar_head': dict(sign=+1, frac=2.8e-3, kind='ridge', src='AFS p.171; plan #2b'),
    'malleolus_med': dict(
        sign=+1, frac=3.2e-3, kind='strip', src='AFS p.206 medial tibial strip runs into it; plan #3/#3c'
    ),
    'malleolus_lat': dict(sign=+1, frac=2.6e-3, kind='ridge', src='AFS p.216; plan #3b'),
    'trochanter': dict(
        sign=0, frac=2.8e-3, kind='sign_variable', src='AFS p.195 convex when lean, DIMPLE at high fat; plan #8'
    ),
    'acromion': dict(sign=+1, frac=2.4e-3, kind='ridge', src='AFS p.172; plan #9'),
    'suprasternal_notch': dict(sign=-1, frac=4.0e-3, kind='pit', src='HeadNeck p.160 "the pit of the neck"; plan #1c'),
    'cervicale': dict(sign=+1, frac=3.0e-3, kind='ridge', src='HeadNeck p.168-169, pose-conditional; plan #6'),
    'zygomatic_arch': dict(
        sign=+1, frac=2.4e-3, kind='ridge', src='HeadNeck p.80 SOLID line; FacialExpr profile plates'
    ),
    'nasal_bone': dict(sign=+1, frac=2.4e-3, kind='ridge', src='HeadNeck p.80 SOLID'),
    'orbital_margin': dict(
        sign=+1, frac=2.4e-3, kind='ridge', src='HeadNeck p.80 SOLID; p.31 reads as the tear trough'
    ),
    'temporal_line': dict(sign=+1, frac=2.0e-3, kind='ridge', src='HeadNeck p.80 SOLID'),
    'gonion': dict(sign=+1, frac=2.2e-3, kind='ridge', src='HeadNeck p.80 SOLID lower border of mandible'),
}


# ---------------------------------------------------------------------------------
# AFS p.63 — THE FAT-INVARIANT ROSTER, WITH ITS DENOMINATOR INTACT.
#
# p.63 names EIGHT regions that keep bony relief at every bodyfat. The roster below carries
# all eight, each with the probes that cover it and — where there are none — the reason. It
# is a tuple of (page_region, body_probes, head_probes, note).
#
# WHY IT IS SHAPED LIKE THIS. The shipped adapter quoted "n of the 11 AFS p.63 fat-invariant
# probes", and 11 is the count of BODY POOLS that happened to map, not the page's list.
# Three of the page's eight regions — facial mask, nape, spine midline — have no body pool at
# all, and dropping them from the denominator makes a partial census read as a complete one.
# The rule is the one that governs every threshold in this package: a denominator may not
# shrink quietly. An unprobed region is REPORTED as unprobed; it never leaves the roster.
#
# Two of the five covered regions are also covered only in part, and the roster says so
# rather than letting "wrists/hands" stand for a probe that only ever looks at a wrist.
AFS_P63_REGIONS = (
    (
        'facial_mask',
        (),
        (
            'superciliary_arch',
            'zygomatic_arch',
            'orbital_margin',
            'nasal_bone',
            'temporal_line',
            'temporal_fossa',
            'gonion',
            'mental_protuberance',
        ),
        'NO BODY PROBE. Covered only by the head/neck window set, which is scored at a cut '
        'calibrated on TORSO AND LIMB skin and is therefore report-only. It may not be counted '
        'towards a body result in either direction.',
    ),
    (
        'nape',
        (),
        ('cervicale',),
        'NO BODY PROBE. The nape is represented only by the C7 head/neck window, which is '
        'report-only and pose-conditional (HeadNeck p.168-169). The nape proper — the '
        'trapezius ridge either side of the midline — has no window authored on it.',
    ),
    (
        'clavicle_sternum',
        ('clavicle_shaft', 'sternal_end', 'acromion'),
        ('suprasternal_notch',),
        'acromion is the acromial end of the clavicle; the '
        'suprasternal notch is in the head/neck set and is not counted on the body.',
    ),
    (
        'spine_midline',
        (),
        (),
        'NOT PROBED BY EITHER SET. There is no window on the thoracic or lumbar midline in '
        'regions.REGION_SPEC or in HEAD_PROBES. This region of p.63 is unmeasured, which is '
        'not the same finding as unresolved and must never be folded into one.',
    ),
    ('elbows', ('olecranon', 'epicondyle_lat', 'epicondyle_med'), (), ''),
    (
        'wrists_hands',
        ('ulnar_head',),
        (),
        'PARTIAL: the wrist only. The hand carries no relief window at all — geom.form.hands '
        'measures digit chains and phalanx ratios, not surface relief.',
    ),
    ('knees', ('patella', 'tibial_tuberosity'), (), ''),
    (
        'ankles_feet',
        ('malleolus_lat', 'malleolus_med'),
        (),
        'PARTIAL: the ankle only. The foot carries no relief window.',
    ),
)

# The body probes of the roster, in roster order. Derived, never hand-listed, so it cannot
# drift from AFS_P63_REGIONS.
FAT_INVARIANT_PROBES = tuple(p for _r, body, _h, _n in AFS_P63_REGIONS for p in body)

# The page regions with NO body probe. This tuple is the denominator's missing piece and is
# reported beside every fat-invariant count.
AFS_P63_UNPROBED_ON_BODY = tuple(r for r, body, _h, _n in AFS_P63_REGIONS if not body)

AFS_P63_SOURCE = (
    'CANON — Anatomy For Sculptors p.63 names eight regions that keep bony relief at every '
    'bodyfat: facial mask, nape, clavicle-sternum, spine midline, elbows, wrists/hands, '
    'knees, ankles/feet. %d of the eight have a body relief probe (%d probe windows); %d '
    'have none and are reported unprobed: %s. The CUT is not from the book: it is '
    "ridge.RIDGE_NULL_P99, this module's own measured false-positive floor (22,957 "
    'landmark-free skin pools x 3 sizes over a fixed %d-seed panel, 2026-08-07 — not one '
    'draw). The book supplies WHICH regions must show relief; the mesh supplies what counts '
    'as showing it.'
    % (
        len(AFS_P63_REGIONS) - len(AFS_P63_UNPROBED_ON_BODY),
        len(FAT_INVARIANT_PROBES),
        len(AFS_P63_UNPROBED_ON_BODY),
        ', '.join(AFS_P63_UNPROBED_ON_BODY),
        len(RIDGE_NULL_SEED_PANEL),
    )
)
