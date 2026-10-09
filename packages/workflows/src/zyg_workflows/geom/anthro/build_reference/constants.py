# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""build_reference — ANSUR II column table, indices, policy constants.

Moved verbatim out of build_reference.py; see the package __init__ for the full rationale.
"""

# ruff: noqa: F401
# F401: this module inherits the original top import block; the siblings re-import what they use

import argparse
import csv
import hashlib
import json
import os
import shutil
import time

import numpy as np

from zyg_workflows import paths as _paths

ROOT = str(_paths.DATA_DIR / 'assets' / 'anthro_reference')
SCHEMA_VERSION = 1

# Where the primary microdata was originally retrieved to. Used only when the repo copy
# does not exist yet; after the first run the repo copy is authoritative.
# $ZYG_ANSUR_IMPORT_DIR overrides it; the default lives under the package scratch root
# (paths.ZYG_TMP_DIR, 0o700) rather than a world-readable fixed /tmp path.
IMPORT_DIR = _paths.ZYG_ANSUR_IMPORT_DIR

# (repo filename, filename in the import dir). The repo filenames are the upstream
# publication names, not the shorthand the download happened to use.
SOURCE_FILES = [
    ('ANSUR_II_MALE_Public.csv', 'ansur_m.csv'),
    ('ANSUR_II_FEMALE_Public.csv', 'ansur_f.csv'),
    ('cdc_statage.csv', 'statage.csv'),
    ('cdc_bmiagerev.csv', 'bmiagerev.csv'),
]

# DODRace coding, ANSUR II working databases. Codes 5/6/8 exist in the data but are far
# below the n>=100 floor in both sexes.
DODRACE = {1: 'white', 2: 'black', 3: 'hispanic', 4: 'asian', 5: 'native_american', 6: 'pacific_islander', 8: 'other'}
MIN_GROUP_N = 100  # HOUSE: below this a percentile band is noise, not evidence.

# ISO 20685-1:2018 Table 4, transcribed from the standard text. These bound the MAXIMUM
# MEAN DIFFERENCE between a scanner-extracted value and a traditionally measured value
# ACROSS A VALIDATION SAMPLE (Clause 5.4). They are NOT a per-subject error budget.
ISO_20685_1_TABLE4_MM = {
    'segment_length': 5,
    'height': 4,
    'circumference_large': 9,
    'circumference_small': 4,
    'breadth': 4,
    'depth': 5,
    'head_without_hair': 1,
    'head_with_hair': 2,
    'hand': 1,
    'foot': 2,
}

# ---------------------------------------------------------------------------
# Dimension table. ansur = column name (lower-cased); iso_class keys into
# ISO_20685_1_TABLE4_MM; landmark/convention are what makes the number comparable.
# All ANSUR II linear columns are millimetres (see PROVENANCE units traps).
# ---------------------------------------------------------------------------
DIMENSIONS = {
    # --- heights: the axis stature predicts well -----------------------------------
    'cervicale_height': dict(
        ansur='cervicaleheight',
        iso_class='height',
        landmark='cervicale (spinous process of C7)',
        convention='vertical distance from standing surface, standing erect',
    ),
    'suprasternale_height': dict(
        ansur='suprasternaleheight',
        iso_class='height',
        landmark='suprasternale (jugular notch)',
        convention='vertical distance from standing surface',
    ),
    'acromial_height': dict(
        ansur='acromialheight',
        iso_class='height',
        landmark='acromion (right)',
        convention='vertical distance from standing surface',
    ),
    'tenthrib_height': dict(
        ansur='tenthribheight',
        iso_class='height',
        landmark='tenth rib midspine',
        convention='vertical distance from standing surface',
    ),
    'waist_height_omphalion': dict(
        ansur='waistheightomphalion',
        iso_class='height',
        landmark='omphalion (navel), anterior',
        convention='vertical distance from standing surface. WAIST SITE TRAP: ANSUR II '
        'defines the waist at OMPHALION. WHO uses the rib-iliac midpoint and '
        'NIH/NHANES uses the iliac crest; those sites differ by up to 10.1 cm '
        'in women. Do not mix conventions.',
    ),
    'iliocristale_height': dict(
        ansur='iliocristaleheight',
        iso_class='height',
        landmark='iliocristale (superior iliac crest, right)',
        convention='vertical distance from standing surface',
    ),
    'trochanterion_height': dict(
        ansur='trochanterionheight',
        iso_class='height',
        landmark='trochanterion (greater trochanter, right)',
        convention='vertical distance from standing surface',
    ),
    'buttock_height': dict(
        ansur='buttockheight',
        iso_class='height',
        landmark='gluteal furrow',
        convention='vertical distance from standing surface',
    ),
    'crotch_height': dict(
        ansur='crotchheight',
        iso_class='height',
        landmark='crotch (perineum), block raised until firm contact',
        convention='vertical distance from standing surface. LEG LENGTH TRAP: "leg '
        'length" is reported in the literature against at least four different '
        'landmarks — crotch, trochanterion, iliocristale and (subischial) '
        'stature-minus-sitting-height. They are not interchangeable.',
    ),
    'wrist_height': dict(
        ansur='wristheight',
        iso_class='height',
        landmark='stylion (radial styloid), right',
        convention='vertical distance from standing surface, arms hanging',
    ),
    'knee_height_midpatella': dict(
        ansur='kneeheightmidpatella',
        iso_class='height',
        landmark='midpatella, right',
        convention='vertical distance from standing surface',
    ),
    'tibiale_height': dict(
        ansur='tibialheight',
        iso_class='height',
        landmark='tibiale (medial tibial condyle), right',
        convention='vertical distance from standing surface',
    ),
    'lateral_malleolus_height': dict(
        ansur='lateralmalleolusheight',
        iso_class='height',
        landmark='lateral malleolus, right',
        convention='vertical distance from standing surface',
    ),
    'sitting_height': dict(
        ansur='sittingheight',
        iso_class='height',
        landmark='vertex, seated',
        convention='vertical distance from sitting surface to top of head; the numerator of the cormic index',
    ),
    'span': dict(
        ansur='span',
        iso_class='segment_length',
        landmark='dactylion to dactylion',
        convention='maximum horizontal distance between fingertips, arms abducted to '
        'the horizontal. ANSUR II ships "span"; there is NO span-akimbo column '
        'in the public release.',
    ),
    # --- breadths: the axis stature barely predicts --------------------------------
    'biacromial_breadth': dict(
        ansur='biacromialbreadth',
        iso_class='breadth',
        landmark='acromion to acromion',
        convention='horizontal skeletal breadth, beam caliper. SHOULDER TRAP: biacromial '
        '(bone), bideltoid (over the deltoids) and shoulder circumference are '
        'three different quantities routinely all called "shoulder width".',
    ),
    'bideltoid_breadth': dict(
        ansur='bideltoidbreadth',
        iso_class='breadth',
        landmark='lateral deltoid to lateral deltoid',
        convention='maximum horizontal breadth over the deltoid muscles (soft tissue)',
    ),
    'bicristal_breadth': dict(
        ansur='bicristalbreadth',
        iso_class='breadth',
        landmark='iliocristale to iliocristale',
        convention='horizontal skeletal pelvis breadth, beam caliper',
    ),
    'hip_breadth': dict(
        ansur='hipbreadth',
        iso_class='breadth',
        landmark='maximum lateral hip contour, standing',
        convention='maximum horizontal breadth over the hips (soft tissue), NOT bicristal',
    ),
    'chest_breadth': dict(
        ansur='chestbreadth',
        iso_class='breadth',
        landmark='chest at nipple level (male) / bustpoint level convention per handbook',
        convention='horizontal breadth at the level of the chest circumference',
    ),
    'waist_breadth': dict(
        ansur='waistbreadth',
        iso_class='breadth',
        landmark='omphalion',
        convention='horizontal breadth at omphalion level, beam caliper',
    ),
    # --- depths --------------------------------------------------------------------
    'chest_depth': dict(
        ansur='chestdepth',
        iso_class='depth',
        landmark='chest at the level of the chest circumference',
        convention='horizontal anterior-posterior depth, standing',
    ),
    'buttock_depth': dict(
        ansur='buttockdepth',
        iso_class='depth',
        landmark='maximum posterior buttock protrusion',
        convention='horizontal anterior-posterior depth, standing',
    ),
    'abdominal_extension_depth_sitting': dict(
        ansur='abdominalextensiondepthsitting',
        iso_class='depth',
        landmark='maximum anterior abdominal protrusion, seated',
        convention='horizontal depth, seated erect',
    ),
    # --- circumferences: tape measurements -----------------------------------------
    'chest_circumference': dict(
        ansur='chestcircumference',
        iso_class='circumference_large',
        landmark='chest at the level of the bustpoints/nipples per handbook',
        convention='taut tape, horizontal, at maximum quiet expiration',
    ),
    'waist_circumference_omphalion': dict(
        ansur='waistcircumference',
        iso_class='circumference_large',
        landmark='omphalion (navel)',
        convention='taut tape, horizontal, passing over the omphalion landmarks. The '
        'ANSUR II column is literally named "waistcircumference" but the '
        'report titles it WAIST CIRCUMFERENCE (OMPHALION).',
    ),
    'buttock_circumference': dict(
        ansur='buttockcircumference',
        iso_class='circumference_large',
        landmark='maximum buttock protrusion',
        convention='taut tape, horizontal. This is the "hip" of a waist-hip ratio',
    ),
    'neck_circumference': dict(
        ansur='neckcircumference',
        iso_class='circumference_small',
        landmark='just inferior to the thyroid cartilage',
        convention='taut tape, perpendicular to the neck axis',
    ),
    'thigh_circumference': dict(
        ansur='thighcircumference',
        iso_class='circumference_large',
        landmark='gluteal furrow',
        convention='taut tape, horizontal, standing',
    ),
    'calf_circumference': dict(
        ansur='calfcircumference',
        iso_class='circumference_small',
        landmark='maximum calf protrusion',
        convention='taut tape, horizontal, standing',
    ),
    'wrist_circumference': dict(
        ansur='wristcircumference',
        iso_class='circumference_small',
        landmark='stylion level',
        convention='taut tape, perpendicular to the forearm axis',
    ),
    'biceps_circumference_flexed': dict(
        ansur='bicepscircumferenceflexed',
        iso_class='circumference_small',
        landmark='maximum upper arm protrusion, elbow flexed 90 deg, fist clenched',
        convention='taut tape, perpendicular to the humerus axis',
    ),
    'shoulder_circumference': dict(
        ansur='shouldercircumference',
        iso_class='circumference_large',
        landmark='over the deltoids, passing over the maximum protrusion',
        convention='taut tape, horizontal',
    ),
    # --- extremities and head ------------------------------------------------------
    'hand_length': dict(
        ansur='handlength',
        iso_class='hand',
        landmark='stylion to dactylion III',
        convention='hand flat, fingers extended',
    ),
    'foot_length': dict(
        ansur='footlength',
        iso_class='foot',
        landmark='pternion to most protruding toe',
        convention='maximum length, weight evenly distributed',
    ),
    'head_length': dict(
        ansur='headlength',
        iso_class='head_with_hair',
        landmark='glabella to occiput',
        convention='maximum anterior-posterior length, spreading caliper',
    ),
    'head_breadth': dict(
        ansur='headbreadth',
        iso_class='head_with_hair',
        landmark='maximum lateral cranial breadth above the ears',
        convention='maximum breadth, spreading caliper',
    ),
    'head_circumference': dict(
        ansur='headcircumference',
        iso_class='head_with_hair',
        landmark='glabella and maximum posterior protrusion',
        convention='taut tape, maximum circumference',
    ),
    'acromion_radiale_length': dict(
        ansur='acromionradialelength',
        iso_class='segment_length',
        landmark='acromion to radiale (upper arm)',
        convention='straight-line distance, elbow flexed 90 deg',
    ),
    'radiale_stylion_length': dict(
        ansur='radialestylionlength',
        iso_class='segment_length',
        landmark='radiale to stylion (forearm)',
        convention='straight-line distance, elbow flexed 90 deg',
    ),
}

# Dimensionless indices — ratios of two measured dimensions, neither of them stature.
# `scale` exists so the cephalic index can be published on its conventional x100 scale.
INDICES = {
    'shoulder_hip_skeletal': dict(
        num='biacromial_breadth',
        den='bicristal_breadth',
        scale=1.0,
        note='biacromial/bicristal, both skeletal. Does NOT separate a 12-year-old boy '
        'from an adult man (both ~1.43); it is not a maturity cue.',
    ),
    'bideltoid_over_hipbreadth': dict(
        num='bideltoid_breadth',
        den='hip_breadth',
        scale=1.0,
        note='the soft-tissue silhouette counterpart of shoulder_hip_skeletal',
    ),
    'waist_hip_circumference': dict(
        num='waist_circumference_omphalion',
        den='buttock_circumference',
        scale=1.0,
        note='WHR. Reported here as a measured distribution ONLY. The "0.7 ideal" is '
        'CONTESTED and is not shipped: 0.7 sits near the 0.5th percentile of this '
        'sample, i.e. it describes almost no real woman.',
    ),
    'shoulder_waist_circumference': dict(
        num='shoulder_circumference',
        den='waist_circumference_omphalion',
        scale=1.0,
        note='The "Adonis index 1.618" has no primary source and is not shipped.',
    ),
    'foot_over_hand_length': dict(
        num='foot_length',
        den='hand_length',
        scale=1.0,
        note='distal proportions; growth is distal-to-proximal so this index is one of '
        'the few that meaningfully separates children from adults',
    ),
    'upperarm_over_forearm': dict(
        num='acromion_radiale_length',
        den='radiale_stylion_length',
        scale=1.0,
        note='brachial index proxy (acromion-radiale / radiale-stylion), NOT the '
        'osteological humerofemoral or radiohumeral index',
    ),
    'cephalic_index': dict(
        num='head_breadth',
        den='head_length',
        scale=100.0,
        note='published on the conventional x100 scale. Measured over hair, so it is not '
        'comparable to craniometric series taken on dry skulls.',
    ),
}

# The FIXED ordered ratio vector of the joint plausibility model. Skeletal frame only:
# heights, skeletal breadths and limb segment lengths, all divided by stature. Girths are
# deliberately EXCLUDED — adult ageing is overwhelmingly a girth delta on a near-unchanged
# skeleton, so a girth-carrying frame model would reject a correctly-aged character for
# being correctly aged. NO NUMBER IS QUOTED HERE ON PURPOSE (2026-08-05): this comment
# used to assert a briefing figure of "waist +12.5 cm while crotch/stature and cormic move
# <0.6%", which is 42% away from what this pack's own microdata gives and, for the female
# crotch ratio, on the wrong side of the 0.6%. The measured deltas are computed at build
# time by _ageing_deltas() and ship in reference.json -> gaps[adult ageing].measured; read
# them from there rather than restating them.
MAHALANOBIS_ORDER = [
    'cervicale_height',
    'acromial_height',
    'iliocristale_height',
    'crotch_height',
    'tibiale_height',
    'sitting_height',
    'biacromial_breadth',
    'bicristal_breadth',
    'acromion_radiale_length',
    'radiale_stylion_length',
]
# chi-square 0.95 and 0.99 quantiles at df=10. Stored as a REFERENCE POINT so the pack can
# report the pass rate they actually achieve; the shipped gate uses the empirical values.
CHI2_DF10 = {'p95': 18.307, 'p99': 23.209}

# HOUSE predictability policy. Derived shape, not derived constants: the cut values below
# are ours, but every consumer gets r and rmse_mm and can re-cut. r>=0.80 means stature
# explains >=64% of the dimension's variance; the rmse ceiling catches dimensions with a
# respectable r whose residual scatter is still far too large to anchor a gate to (span).
POLICY_MIN_R = 0.80
POLICY_MAX_RMSE_MM = 30.0

PERCENTILE_GRID = list(range(101))  # q[i] == the i-th percentile, linear interpolation
REPORT_PERCENTILES = [1, 5, 25, 50, 75, 95, 99]
