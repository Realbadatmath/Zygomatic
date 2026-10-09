# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""build_reference — provenance, conventions and the adult-ageing deltas.

Moved verbatim out of build_reference.py; see the package __init__ for the full rationale.
"""

import numpy as np
import os
import time
from zyg_workflows.geom.anthro.build_reference.constants import DODRACE
from zyg_workflows.geom.anthro.build_reference.stats import _r6


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------
def _provenance(src_paths, copied, origin):
    return {
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'source_origin': origin,
        'sources': {
            'ansur_ii_2012': {
                'citation': 'Gordon, C.C., Blackwell, C.L., Bradtmiller, B., Parham, '
                'J.L., Barrientos, P., Paquette, S.P., Corner, B.D., Carson, '
                'J.M., Venezia, J.C., Rockwell, B.M., Mucher, M., and '
                'Kristensen, S., 2014 (dated December 2014, published 2015). '
                '"2012 Anthropometric Survey of U.S. Army Personnel: Methods '
                'and Summary Statistics." Report No. NATICK/TR-15/007. U.S. '
                'Army Natick Soldier Research, Development and Engineering '
                'Center, Natick, MA.',
                'measurer_handbook': 'Hotzman, J., Gordon, C.C., Bradtmiller, B., Corner, '
                'B.D., Mucher, M., Kristensen, S., Paquette, S., and '
                'Blackwell, C.L., 2011. "Measurer\'s Handbook: US '
                'Army and Marine Corps Anthropometric Surveys, '
                '2010-2011." Report No. NATICK/TR-11/017.',
                'population': 'U.S. Army personnel (Active Duty, National Guard and '
                'Reserve). The public files are the ANSUR II "working '
                'databases": stratified random samples drawn so that age, '
                'racial/ethnic and component subgroup frequencies match '
                'Total Army DMDC census data for 30 September 2011. '
                'EXPLICITLY NOT a US civilian sample — the source report '
                'states designs based on these data "will not accommodate '
                'most user populations in the intended manner". Ages 17-58.',
                'n': {'male': 4082, 'female': 1986},
                'year_measured': 'October 2010 - April 2012',
                'year_public': 2017,
                'units': {
                    'linear_columns': 'MILLIMETRES (all body dimensions)',
                    'weightkg': 'HECTOGRAMS despite the column name — sample mean 855.2 '
                    'means 85.52 kg. Divide by 10 for kilograms.',
                    'interpupillarybreadth': '0.1 mm units, not mm',
                    'Heightin_Weightlbs': 'the two trailing columns do not agree with the '
                    'measured stature and mass and are likely '
                    'self-reported; NOT used by this pack',
                },
                'coding': {
                    'DODRace': {str(k): v for k, v in DODRACE.items()},
                    'Gender': 'one value per file (Male / Female)',
                },
                'retrieval': 'https://www.openlab.psu.edu/ansur2/ -> '
                'http://tools.openlab.psu.edu/publicData/'
                'ANSUR_II_MALE_Public.csv and ANSUR_II_FEMALE_Public.csv '
                '(Penn State OPEN Design Lab mirror of the public release)',
                'licence': 'PUBLIC DOMAIN. Work of the U.S. Government prepared by U.S. '
                'Army NSRDEC employees and contractors in the course of '
                'official duties; not subject to copyright protection in the '
                'United States (17 U.S.C. 105).',
                'licence_evidence': 'The technical report title page and SF-298 both '
                'carry the distribution statement "Approved for '
                'public release; distribution is unlimited" '
                '(NATICK/TR-15/007, verified in the report text). The '
                'microdata files are published for open download with '
                'no click-through, registration or use restriction.',
            },
            'cdc_growth_charts_2000': {
                'citation': 'Kuczmarski, R.J., Ogden, C.L., Guo, S.S., et al., 2002. '
                '"2000 CDC growth charts for the United States: methods and '
                'development." Vital and Health Statistics Series 11, No. '
                '246. National Center for Health Statistics.',
                'population': 'United States children and adolescents; NHANES I/II/III '
                'and other national survey data, birth cohorts 1963-1994. '
                'Stature-for-age and BMI-for-age LMS parameters.',
                'coverage': 'age 24-240 months, both sexes',
                'units': {'stature_M': 'centimetres', 'bmi_M': 'kg/m^2', 'agemos': 'months, half-month resolution'},
                'files': ['cdc_statage.csv (stature-for-age LMS)', 'cdc_bmiagerev.csv (BMI-for-age LMS, revised)'],
                'retrieval': 'https://www.cdc.gov/growthcharts/ data files (statage.csv, bmiagerev.csv)',
                'licence': 'PUBLIC DOMAIN. Work of the U.S. Government (NCHS/CDC); not '
                'subject to copyright in the United States (17 U.S.C. 105).',
                'caveat': 'The LMS z-score is unreliable in the far upper BMI tail; CDC '
                'now publishes extended BMI-for-age percentiles above the 95th. '
                'bmi_percentile() flags results above that point.',
            },
            'iso_20685_1_2018': {
                'citation': 'ISO 20685-1:2018, "Ergonomics — 3-D scanning methodologies '
                'for internationally compatible anthropometric databases — '
                'Part 1: Evaluation protocol for body dimensions extracted '
                'from 3-D body scans", Table 4.',
                'what_is_stored': 'Table 4 allowances only, transcribed as integers.',
                'what_table4_actually_bounds': 'the MAXIMUM MEAN DIFFERENCE between a '
                'scanner-extracted value and a '
                'traditionally measured value across a '
                'validation sample (Clause 5.4). It is NOT '
                'a per-subject error budget.',
                'house_policy_warning': 'Applying a Table 4 value to a SINGLE generated '
                'mesh is HOUSE policy, not ISO conformance, and '
                'must be labelled as such wherever it is '
                'reported. A per-mesh 4 mm "anthropometric '
                'accuracy" claim is in any case meaningless '
                'against live subjects: diurnal stature variation '
                'in one real person is 14.4-19.3 mm. A +-2 mm '
                'check against a DECLARED BUILD TARGET is a '
                'different and valid thing.',
                'licence': 'ISO standards are copyrighted. Only the ten Table 4 integers '
                'and the clause references are reproduced here, as facts '
                'necessary to state a tolerance policy; no ISO text is '
                'redistributed by this pack.',
            },
            'nhanes_iii': {
                'status': 'CONSULTED, NOT INGESTED',
                'citation': 'National Center for Health Statistics, Third National Health '
                'and Nutrition Examination Survey (NHANES III), 1988-1994, '
                'body measurements file.',
                'why_not_ingested': 'The repo ships no NHANES III codebook, so column '
                'identities would be inferred rather than documented. '
                'An empirical check of an inferred mapping passes for '
                'adults (men 20-49 mean stature 174.3 cm, cormic '
                '0.5218) and for 12-year-old boys (cormic 0.5057) but '
                'FAILS a plausibility check at age 8, where the '
                'inferred upper-arm column reads 23.6 cm against '
                '32.2 cm at age 12 — an impossible 4-year jump. The '
                'mapping is therefore not trustworthy across the age '
                'range and no NHANES-derived band is shipped.',
                'consequence': 'This pack has NO child or adolescent ratio bands. See reference.json -> gaps.',
                'licence': 'PUBLIC DOMAIN (U.S. Government work, NCHS).',
            },
        },
        'files': copied,
        'read_from': {k: os.path.abspath(v) for k, v in src_paths.items()},
    }


def _conventions():
    return {
        'girth_measurement': {
            'this_pack': 'ANSUR II circumferences are TAUT TAPE measurements on live subjects.',
            'how_to_reproduce_on_a_mesh': 'horizontal PLANE SLICE of the mesh at the '
            'landmark height, then the CONVEX HULL '
            'perimeter of the intersection contour. This is '
            'what SHAPY, A2B, CALVIS and ISO 18825-2 use to '
            'emulate a taut tape.',
            'what_NOT_to_compare': 'MakeHuman/anny Ruler.getMeasure sums straight chords '
            'along a vertex ring — an INSCRIBED POLYLINE. The '
            'ordering is hull >= true contour >= polyline, so '
            'polyline girths are systematically SMALL and must '
            'never be compared against the circumference bands in '
            'this pack.',
        },
        'definition_traps': {
            'waist': 'ANSUR II = omphalion (navel). WHO = midpoint between the lowest rib '
            'and the iliac crest. NIH/NHANES = iliac crest. The WHO and NIH sites '
            'differ by up to 10.1 cm in women. A "waist" number without its site '
            'is not a measurement.',
            'leg_length': 'at least four incompatible definitions — crotch height, '
            'trochanterion height, iliocristale height, and subischial '
            'length (stature minus sitting height).',
            'shoulder_width': 'biacromial breadth (skeletal), bideltoid breadth (soft '
            'tissue) and shoulder circumference are three different '
            'quantities with the same colloquial name.',
            'rule': 'every stored measurement carries landmark + convention + population '
            '+ date. A consumer that cannot state all four for its own '
            'measurement cannot legitimately compare it to these bands.',
        },
        'not_shipped_because_contested': {
            'golden_ratio_1_618': 'measured stature/navel-height in this sample is not '
            'phi; the empirical attractor is nearer 5/3. Not a '
            'proportion target.',
            'waist_hip_0_7': 'sits near the 0.5th percentile of real women. The '
            'distribution is shipped; the "ideal" is not.',
            'adonis_1_618_shoulder_to_waist': 'no primary source; the commonly cited 2023 IJSM study does not exist.',
            'symmetry_as_beauty': 'effect is near zero after publication-bias correction.',
            'drillis_contini_segment_constants': 'small convenience sample, superseded by the microdata in this pack.',
            'nth_percentile_person': 'does not exist — a p95-stature man averages about '
            'p62 waist and p53 head breadth. Never assemble a '
            'body by stacking one percentile.',
        },
        'symmetry': {
            'morph_space_symmetry': 'a mesh produced by a symmetric morph space should be NEAR-zero '
            'left-right asymmetric, so a material deviation is a broken morph — but '
            "do NOT gate at floating-point tolerance. The consumer's own morph "
            'target data sets the floor, and vendor tables are not required to be '
            'bit-mirror-symmetric. Measure your own floor over several bodies with '
            "any sculpt layer disabled and clear it with headroom. This package's "
            'own implementation (geom.anthro.integrity.SYM_MORPH_TOL_MM) measured a '
            'floor of 0.0632 mm across six anny bodies and ships 0.15 mm, ~2.4x '
            'above it. CORRECTED 2026-08-05: this convention previously read '
            '"EXACTLY zero ... must be gated at floating-point tolerance", which is '
            'the pre-fix intent from when the tolerance was 0.05 mm. A consumer '
            'implementing it as served would gate at float epsilon and reject 4 of 4 '
            'bodies this package issues, i.e. 100% false-fail.',
            'morph_space_symmetry_provenance': 'HOUSE convention, calibrated on MEASURED values. The floor is a property '
            'of the morph library in use, not of this pack; the number quoted is the '
            'one geom.anthro measured for anny and is offered as a worked example, '
            'not as a constant to copy.',
            'realism_injected_asymmetry': 'a separate, deliberate 0-10 mm band (population mean about 5.2 mm).',
            'do_not_merge': 'these two checks answer different questions and must stay separate gates.',
        },
        'stylization': {
            'rule': 'the target is PLAUSIBLE plus a RECORDED stylization delta. Never '
            'encode an aesthetic ideal into a band.',
            'named_axis': 'MakeHuman/anny ships a BodyProportions macro (108 targets, '
            'split idealproportions/uncommonproportions). The stylization '
            'axis is that NAMED PARAMETER, recorded per character, not a '
            'drift baked into these distributions.',
        },
    }


AGEING_REFERENCE_AGES = (25, 43)
AGEING_BIN_HALFWIDTH_Y = 1  # 24-26 vs 42-44, i.e. +-1 year around each anchor


def _ageing_deltas(cols_by_sex, ages=AGEING_REFERENCE_AGES):
    """MEASURED adult-ageing deltas, computed from the microdata this pack ships.

    WHY THIS FUNCTION EXISTS (2026-08-05). reference.json -> gaps[adult ageing] used to
    state, as fact and with no provenance key at all, that "25->43 gives waist +12.5 cm
    and BMI +3.2 while crotch/stature and cormic drift under 0.6%". That is an
    unattributed civilian-cohort briefing figure. Recomputed from the ANSUR II CSVs in
    this pack's own source/ directory it is waist +8.77 cm and BMI +2.27 for men — the
    shipped claim was 42% and 41% high — and the female crotch-height/stature drift is
    -0.69%, i.e. on the wrong side of the "<0.6%" it also asserted. The gap block is
    served through the public API as provenance, so a consumer sizing an ageing character
    off it would have added ~4 cm of waist that nothing in this population supports.
    It is now DERIVED IN CODE from the shipped CSVs and cannot drift again.

    Two estimators, both reported, because they answer slightly different questions and
    neither is privileged: `ols` is the least-squares slope over the whole 17-58 sample
    multiplied by the 18-year span (uses every subject, assumes linearity); `binned` is
    the difference of the means in +-1 y windows around each anchor age (assumes nothing,
    uses ~20% of the sample). ANSUR II is CROSS-SECTIONAL and militarily selected, so
    neither is a longitudinal ageing trajectory for anyone — see `caveat`.
    """
    a_lo, a_hi = float(ages[0]), float(ages[1])
    span = a_hi - a_lo
    hw = AGEING_BIN_HALFWIDTH_Y
    out = {}
    for sex, cols in cols_by_sex.items():
        age = cols['age']
        st = cols['stature']
        channels = {
            'waist_circumference_mm': cols['waistcircumference'],
            'bmi_kg_m2': (cols['weightkg'] / 10.0) / (st / 1000.0) ** 2,
            'crotch_height_over_stature': cols['crotchheight'] / st,
            'cormic_index': cols['sittingheight'] / st,
        }
        m_lo = (age >= a_lo - hw) & (age <= a_lo + hw)
        m_hi = (age >= a_hi - hw) & (age <= a_hi + hw)
        per = {}
        for key, y in channels.items():
            beta = np.linalg.lstsq(np.column_stack([age, np.ones_like(age)]), y, rcond=None)[0]
            at_lo = float(beta[0] * a_lo + beta[1])
            ols = float(beta[0]) * span
            binned = float(y[m_hi].mean() - y[m_lo].mean())
            per[key] = {
                'ols_delta': _r6(ols),
                'binned_delta': _r6(binned),
                'fitted_value_at_age_%d' % int(a_lo): _r6(at_lo),
                'ols_delta_pct_of_age_%d' % int(a_lo): (_r6(100.0 * ols / at_lo) if at_lo else None),
                'binned_delta_pct_of_age_%d' % int(a_lo): (
                    _r6(100.0 * binned / float(y[m_lo].mean())) if float(y[m_lo].mean()) else None
                ),
            }
        out[sex] = {
            'n_total': int(age.size),
            'n_at_age_%d' % int(a_lo): int(m_lo.sum()),
            'n_at_age_%d' % int(a_hi): int(m_hi.sum()),
            'channels': per,
        }
    return {
        'from_age_years': a_lo,
        'to_age_years': a_hi,
        'bin_halfwidth_years': hw,
        'estimators': {
            'ols': 'least-squares slope of the channel on age over the whole 17-58 '
            'sample, times the %g-year span' % span,
            'binned': 'mean over ages %g-%g minus mean over ages %g-%g' % (a_hi - hw, a_hi + hw, a_lo - hw, a_lo + hw),
        },
        'provenance': 'MEASURED, computed at build time by build_reference._ageing_deltas '
        'from the ANSUR II microdata copied into this pack under source/. '
        'No figure here is quoted from anywhere.',
        'caveat': 'CROSS-SECTIONAL and militarily selected. A 43-year-old soldier passed '
        'the same fitness standard as a 25-year-old, so this is the difference '
        'between two age groups in one selected population, NOT the trajectory '
        'of one person ageing, and it is smaller than the corresponding '
        'civilian figure. Do not use it as a life-course model.',
        'per_sex': out,
    }


def _gaps(ageing):
    m = ageing['per_sex']['male']['channels']
    f = ageing['per_sex']['female']['channels']
    a_lo, a_hi = int(ageing['from_age_years']), int(ageing['to_age_years'])
    pct_key = 'ols_delta_pct_of_age_%d' % a_lo
    skel = [
        m['crotch_height_over_stature'][pct_key],
        m['cormic_index'][pct_key],
        f['crotch_height_over_stature'][pct_key],
        f['cormic_index'][pct_key],
    ]
    skeletal_worst = max(abs(x) for x in skel)
    # stated as a magnitude with its direction spelled out, because the four skeletal
    # channels move DOWN and a signed "+0.68%" would read as the opposite
    skeletal_dir = (
        'all downward' if all(x < 0 for x in skel) else 'all upward' if all(x > 0 for x in skel) else 'mixed in sign'
    )
    return [
        {
            'gap': 'children and adolescents',
            'detail': 'ANSUR II covers ages 17-58. NO ratio band in this pack applies to a '
            'child. Scaling an adult band down is WRONG in three known ways: a '
            "12-year-old cormic index (~0.507) is LOWER than an adult's (~0.523), "
            'i.e. legs proportionally longer; head length is ~96% of adult at ~85% '
            'of adult stature; growth is distal-to-proximal so hands and feet are '
            'proportionally large.',
            'what_is_available': 'CDC LMS stature-for-age and BMI-for-age (24-240 months) '
            'are folded in and DO apply to children — but they '
            'constrain size, not proportion.',
            'not_closed_because': 'see PROVENANCE.json -> sources.nhanes_iii.why_not_ingested',
        },
        {
            'gap': 'non-US and non-military populations',
            'detail': 'the ANSUR II working databases match the Total Army, not any civilian '
            'population. Ancestry groups here are US military DODRace categories, '
            'which are administrative, not biological.',
        },
        {
            'gap': 'female asian group',
            'detail': 'DODRace 4 has n=71 women, below the n>=100 floor, so no female asian '
            'band is shipped while a male one is. An ancestry-aware gate must '
            'handle this asymmetry explicitly rather than falling back silently.',
        },
        {
            'gap': 'adult ageing',
            'detail': 'ANSUR II is measured 17-58 but this pack does not model the ageing '
            'trajectory. The shape, MEASURED from the microdata under source/ '
            '(least squares, %d->%d y): a GIRTH delta on a near-unchanged '
            'skeleton — waist %+.2f cm and BMI %+.2f for men, %+.2f cm and %+.2f '
            'for women, while crotch/stature and the cormic index move by at most '
            '%.2f%% of their value at %d (%s). Gate ageing on girths, never on '
            'frame ratios. Every figure in this sentence is recomputed at build '
            'time; see .measured for both estimators, per sex, with n.'
            % (
                a_lo,
                a_hi,
                m['waist_circumference_mm']['ols_delta'] / 10.0,
                m['bmi_kg_m2']['ols_delta'],
                f['waist_circumference_mm']['ols_delta'] / 10.0,
                f['bmi_kg_m2']['ols_delta'],
                skeletal_worst,
                a_lo,
                skeletal_dir,
            ),
            'measured': ageing,
            'provenance': ageing['provenance'],
            'supersedes': 'until 2026-08-05 this block asserted, with no provenance key and '
            'no attribution, "25->43 gives waist +12.5 cm and BMI +3.2 while '
            'crotch/stature and cormic drift under 0.6%". That was a civilian '
            'briefing figure, not a measurement of this population: it is 42% '
            'high on waist and 41% high on BMI against the least-squares '
            'estimate from the CSVs shipped here, and the female '
            'crotch/stature drift is -0.69%, outside the "<0.6%" it claimed. '
            'It was replaced by values derived in code from those CSVs.',
        },
    ]
