# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""build_reference.py — compile the anthropometric reference pack from primary microdata."""

import argparse
import numpy as np
import os
import shutil
import time
from zyg_workflows.geom.anthro.build_reference.constants import (
    DIMENSIONS,
    DODRACE,
    ISO_20685_1_TABLE4_MM,
    MAHALANOBIS_ORDER,
    MIN_GROUP_N,
    POLICY_MAX_RMSE_MM,
    POLICY_MIN_R,
    ROOT,
    SCHEMA_VERSION,
    SOURCE_FILES,
)
from zyg_workflows.geom.anthro.build_reference.stats import (
    _atomic_json,
    _atomic_npz,
    _build_ratio_specs,
    _diagnostics,
    _load_ansur,
    _load_lms,
    _mahalanobis,
    _ratio_values,
    _resolve_sources,
    _sha256,
    _summary,
)
from zyg_workflows.geom.anthro.build_reference.provenance import _ageing_deltas, _conventions, _gaps, _provenance


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------
def build(source_dir=None, out_root=ROOT):
    src_paths, origin = _resolve_sources(source_dir, out_root)
    os.makedirs(os.path.join(out_root, 'source'), exist_ok=True)

    copied = {}
    for repo_name, _ in SOURCE_FILES:
        dst = os.path.join(out_root, 'source', repo_name)
        if os.path.abspath(src_paths[repo_name]) != os.path.abspath(dst):
            tmp = dst + '.tmp'
            shutil.copyfile(src_paths[repo_name], tmp)
            os.replace(tmp, dst)
        copied[repo_name] = {'sha256': _sha256(dst), 'bytes': os.path.getsize(dst)}

    ratio_specs = _build_ratio_specs()
    stats, diagnostics, maha_meta = {}, {}, {}
    npz = {}
    dropped = []
    # kept per sex so the ageing gap block can be COMPUTED from the microdata instead of
    # quoting a figure — see _ageing_deltas()
    cols_by_sex = {}

    for sex, fname in (('male', 'ANSUR_II_MALE_Public.csv'), ('female', 'ANSUR_II_FEMALE_Public.csv')):
        cols, race, n = _load_ansur(os.path.join(out_root, 'source', fname))
        cols_by_sex[sex] = cols
        for meta in DIMENSIONS.values():
            if meta['ansur'] not in cols:
                raise KeyError('%s: required column %s missing or non-numeric' % (fname, meta['ansur']))

        groups = {'pooled': np.ones(n, dtype=bool)}
        for code, name in DODRACE.items():
            mask = race == code
            if mask.sum() < MIN_GROUP_N:
                if mask.sum():
                    dropped.append(
                        {'sex': sex, 'dodrace': code, 'group': name, 'n': int(mask.sum()), 'floor': MIN_GROUP_N}
                    )
                continue
            groups[name] = mask

        stats[sex] = {}
        for gname, mask in groups.items():
            sub = {k: v[mask] for k, v in cols.items()}
            stats[sex][gname] = {key: _summary(_ratio_values(sub, key, spec)) for key, spec in ratio_specs.items()}

        diagnostics[sex] = _diagnostics(cols, n)
        meta, X, mu, cov, inv, d2 = _mahalanobis(cols)
        maha_meta[sex] = meta
        npz['%s_mu' % sex] = mu
        npz['%s_cov' % sex] = cov
        npz['%s_inv' % sex] = inv
        # The per-subject ratio vectors ship so that a caller measuring only a SUBSET of
        # the ten components can get an exact empirical threshold for that subset instead
        # of a chi-square approximation. 4082 x 10 float32 = 163 kB.
        npz['%s_vectors' % sex] = X.astype(np.float32)
        npz['%s_d2' % sex] = d2.astype(np.float32)

    # Predictability policy, applied to the WORSE sex so a policy is never softer than
    # the data supports for either.
    ageing = _ageing_deltas(cols_by_sex)
    predictability = {}
    for dim in DIMENSIONS:
        per_sex = {s: diagnostics[s][dim] for s in diagnostics}
        r = min(per_sex[s]['r'] for s in per_sex)
        rmse = max(per_sex[s]['rmse_mm'] for s in per_sex)
        tight = (r >= POLICY_MIN_R) and (rmse <= POLICY_MAX_RMSE_MM)
        predictability[dim] = {
            'r': r,
            'rmse_mm': rmse,
            'policy': 'tight' if tight else 'wide',
            'stature_anchored_halfwidth_mm': round(2.0 * rmse, 2),
            'per_sex': {s: {'r': per_sex[s]['r'], 'rmse_mm': per_sex[s]['rmse_mm']} for s in per_sex},
            'iso_class': DIMENSIONS[dim]['iso_class'],
        }

    doc = {
        'schema_version': SCHEMA_VERSION,
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'builder': 'geom/anthro/build_reference.py',
        'purpose': 'Describes what real bodies ARE. Contains no aesthetic target. A '
        'character that sits outside a band is not "wrong"; it is unusual by a '
        'stated amount against a stated population, and any deliberate '
        'departure belongs in a recorded stylization delta.',
        'schema': {
            'stats': 'stats[sex][group][ratio_key] -> {n, mean, sd, cv, min, max, '
            'p1,p5,p25,p50,p75,p95,p99, q}. q is a 101-element list where q[i] '
            'is the i-th empirical percentile; interpolate within it.',
            'groups': 'always contains "pooled"; ancestry groups are DODRace names that '
            'survived the n>=%d floor, which differs between the sexes.' % MIN_GROUP_N,
            'ratios': 'ratios[key] -> {kind, numerator, denominator, scale, iso_class, '
            'units, definition}. kind is stature_ratio | index | derived.',
            'dimensions': 'dimensions[key] -> {ansur, iso_class, landmark, convention}; '
            'the raw millimetre quantity a ratio is built from.',
            'diagnostics': 'diagnostics[sex][dimension] -> regression of the raw millimetre dimension on stature.',
            'predictability': 'predictability[dimension] -> {r, rmse_mm, policy}; r is '
            'the WORSE of the two sexes and rmse_mm the larger.',
            'mahalanobis': 'order + per-sex model metadata; the numeric arrays live in '
            'mahalanobis.npz as <sex>_mu, <sex>_cov, <sex>_inv, '
            '<sex>_vectors (n x 10 float32), <sex>_d2.',
            'cdc_lms': 'cdc_lms[measure][sex] -> parallel lists agemos/L/M/S.',
        },
        'ancestry_codes': {str(k): v for k, v in DODRACE.items()},
        'ancestry_note': 'DODRace is a US Department of Defense administrative category, '
        'self-reported. It is a proxy for population structure, not a '
        'biological variable. It is tabulated because ignoring it is '
        'measurably worse: crotch-height/stature differs by ~0.024 '
        'between the male black and asian groups, which is 44 mm of leg '
        'on a 1.85 m man.',
        'dropped_groups': dropped,
        'min_group_n': MIN_GROUP_N,
        'conventions': _conventions(),
        'iso_20685_1_table4_mm': ISO_20685_1_TABLE4_MM,
        'dimensions': DIMENSIONS,
        'ratios': ratio_specs,
        'stats': stats,
        'diagnostics': diagnostics,
        'predictability': predictability,
        'predictability_policy': {
            'rule': 'tight iff r >= %.2f AND residual rmse <= %.1f mm, evaluated on the '
            'worse sex' % (POLICY_MIN_R, POLICY_MAX_RMSE_MM),
            'provenance': 'HOUSE. The cut values are ours; the r and rmse they are '
            'applied to are MEASURED from ANSUR II (n=4082 male, 1986 '
            'female). Consumers get both numbers and may re-cut.',
            'rationale': "r >= 0.80 means stature explains >= 64% of the dimension's "
            'variance, so a stature-anchored prediction carries information. '
            'The rmse ceiling rejects dimensions that pass on r but whose '
            'residual scatter is still far too wide to anchor a gate to.',
            'consequence': 'a "tight" dimension may be gated around its stature-predicted '
            'value with half-width 2*rmse. A "wide" dimension must be '
            'gated against the population band for its group and NEVER '
            'against a stature-derived point.',
        },
        'mahalanobis': {
            'order': [d + '_over_stature' for d in MAHALANOBIS_ORDER],
            'order_dimensions': MAHALANOBIS_ORDER,
            'rationale': 'the PRIMARY plausibility gate. Independent per-ratio bands both '
            'reject too many real people and admit combinations that never '
            'co-occur; see per-sex independent_bands_check for the measured '
            'admission rate.',
            'excludes_girths_because': 'adult ageing is a girth delta on a near-unchanged '
            'skeleton, so a girth-carrying frame model would '
            'reject a correctly-aged character. The size of '
            "that delta is MEASURED from this pack's own "
            'microdata in gaps[adult ageing].measured; it is '
            'not quoted from anywhere.',
            'arrays': 'mahalanobis.npz',
            'sexes': maha_meta,
        },
        'cdc_lms': {
            'stature_for_age_cm': _load_lms(os.path.join(out_root, 'source', 'cdc_statage.csv')),
            'bmi_for_age': _load_lms(os.path.join(out_root, 'source', 'cdc_bmiagerev.csv')),
            'formula': 'z = ((X/M)^L - 1) / (L*S) for L != 0, else ln(X/M)/S',
            'coverage_agemos': [24, 240],
        },
        'coverage': {
            'ansur_age_years': [17, 58],
            'ansur_population': 'US Army 2010-2012',
            'cdc_age_months': [24, 240],
            'sexes': ['male', 'female'],
        },
        'gaps': _gaps(ageing),
    }

    _atomic_json(os.path.join(out_root, 'reference.json'), doc, indent=1)
    _atomic_npz(os.path.join(out_root, 'mahalanobis.npz'), **npz)
    _atomic_json(os.path.join(out_root, 'PROVENANCE.json'), _provenance(src_paths, copied, origin), indent=1)
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        '--source-dir',
        default=None,
        help='re-import the primary microdata from this directory instead of the copies already in the pack',
    )
    ap.add_argument('--out', default=ROOT)
    a = ap.parse_args(argv)
    doc = build(a.source_dir, a.out)

    print('pack written to %s' % a.out)
    print('  ratios: %d   groups: %s' % (len(doc['ratios']), {s: sorted(doc['stats'][s]) for s in doc['stats']}))
    print(
        '  dropped groups (n < %d): %s' % (MIN_GROUP_N, [(d['sex'], d['group'], d['n']) for d in doc['dropped_groups']])
    )
    for sex, m in doc['mahalanobis']['sexes'].items():
        print(
            '  D2 %-6s n=%4d  empirical p95=%.4f p99=%.4f | chi2 18.307 passes %.4f '
            '(nominal 0.95) | independent p5-p95 bands admit %.4f'
            % (
                sex,
                m['n'],
                m['d2_empirical']['p95'],
                m['d2_empirical']['p99'],
                m['chi2_reference']['p95_empirical_pass_rate'],
                m['independent_bands_check']['admitted_fraction'],
            )
        )
    tight = [d for d, p in doc['predictability'].items() if p['policy'] == 'tight']
    print('  tight dimensions (%d): %s' % (len(tight), ', '.join(sorted(tight))))
    ag = [g for g in doc['gaps'] if g['gap'] == 'adult ageing'][0]['measured']
    lo, hi = int(ag['from_age_years']), int(ag['to_age_years'])
    print('  adult ageing %d->%d y, MEASURED from source/ (no figure is quoted):' % (lo, hi))
    for sex, rec in ag['per_sex'].items():
        c = rec['channels']
        print(
            '    %-6s n=%4d (%d at %d, %d at %d)  waist %+6.2f cm / %+6.2f binned  |  '
            'BMI %+5.2f / %+5.2f  |  crotch/stature %+6.3f%%  cormic %+6.3f%%'
            % (
                sex,
                rec['n_total'],
                rec['n_at_age_%d' % lo],
                lo,
                rec['n_at_age_%d' % hi],
                hi,
                c['waist_circumference_mm']['ols_delta'] / 10.0,
                c['waist_circumference_mm']['binned_delta'] / 10.0,
                c['bmi_kg_m2']['ols_delta'],
                c['bmi_kg_m2']['binned_delta'],
                c['crotch_height_over_stature']['ols_delta_pct_of_age_%d' % lo],
                c['cormic_index']['ols_delta_pct_of_age_%d' % lo],
            )
        )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
