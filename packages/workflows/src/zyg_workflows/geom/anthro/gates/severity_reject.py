# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Measuring what a gate would reject out of the real ANSUR sample.

Moved verbatim out of the old single-file gates.py (lines 2544-3054).
"""

import math
import os
import numpy as np
from zyg_workflows.geom.anthro.reference import reference

from zyg_workflows.geom.anthro.gates.bands import (
    ANSUR_REFERENCE_POPULATION,
    BAND_WIDTH_BLOCK,
    CAL_EMPIRICAL_PERCENTILE,
    CAL_RATIO_BANDS,
    CAL_STATURE_ANCHORED,
    GateConfigError,
)


# ---------------------------------------------------------------------------------
# SEVERITY CALIBRATION ENGINE
#
# Measures, for every gate whose threshold is a band over a measurable ratio, the fraction
# of the REAL ANSUR sample that gate would reject as configured — and resolves the gate's
# effective severity from that number instead of from the registry's opinion.
#
# The rates come from the per-subject microdata the pack ships in its own source/
# directory, read through build_reference's loaders so that the ratio definitions used
# here are literally the ones that built the bands. When that microdata is unreachable the
# engine does NOT go quiet: it falls back to the rate the band's own definition forces
# (a p1-p99 band excludes 2% of any sample; a +/-k*rmse band excludes the normal tail),
# labels the record as a by-construction lower bound, and carries on. Both paths answer
# the same question; only the tightness of the answer differs.
# ---------------------------------------------------------------------------------
_SAMPLE_CACHE = {}
_REJECT_CACHE = {}


def _norm_sf2(k):
    """Two-tailed normal survival: P(|Z| > k). Used only where a residual band is stated
    in multiples of an rmse and the microdata is not available to measure the real rate."""
    return math.erfc(float(k) / math.sqrt(2.0))


def _worst_cell(cells):
    """The (sex, ancestry) cell with the highest rejection rate — the one that governs.

    Its n, not the smallest n in the table, is what sets the 1/n granularity allowance:
    the allowance exists because the GOVERNING rate was estimated on a finite sample, so
    taking it from some other, smaller cell would loosen the ceiling with a number that
    had nothing to do with the measurement being judged.
    """
    return max(cells, key=lambda c: c['rejected']) if cells else None


def ansur_sample():
    """Per-subject ratio and dimension vectors for the real reference sample.

    Returns {'male': {...}, 'female': {...}, 'source': str} or None with the reason
    recorded, never a partial structure. Cached: the read is ~0.2 s and a four-tier run
    would otherwise repeat it per gate.
    """
    if 'v' in _SAMPLE_CACHE:
        return _SAMPLE_CACHE['v']
    out, why = None, None
    try:
        from zyg_workflows.geom.anthro import build_reference as BR

        specs = BR._build_ratio_specs()
        out = {'source': None, 'by_sex': {}}
        for sex, fname in (('male', 'ANSUR_II_MALE_Public.csv'), ('female', 'ANSUR_II_FEMALE_Public.csv')):
            path = os.path.join(BR.ROOT, 'source', fname)
            if not os.path.exists(path):
                raise IOError('%s not shipped with the pack' % fname)
            cols, race, n = BR._load_ansur(path)
            out['by_sex'][sex] = {
                'n': int(n),
                'race': race,
                'stature_mm': cols['stature'],
                'ratios': {k: BR._ratio_values(cols, k, s) for k, s in specs.items()},
                'dimensions': {d: cols[m['ansur']] for d, m in BR.DIMENSIONS.items() if m['ansur'] in cols},
                'group_codes': {v: k for k, v in BR.DODRACE.items()},
            }
        # Repo-relative, not absolute: this string travels into the report and into its
        # stable digest, and a machine's home directory is not part of the provenance.
        rel = os.path.relpath(
            os.path.join(BR.ROOT, 'source'),
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        )
        out['source'] = (
            'per-subject ANSUR II 2012 public working databases shipped in '
            'the reference pack (%s), male n=%d female n=%d, ratios computed '
            'through build_reference._ratio_values — the same code that '
            'built the bands' % (rel, out['by_sex']['male']['n'], out['by_sex']['female']['n'])
        )
    except Exception as e:  # noqa: BLE001
        out, why = None, '%s: %s' % (type(e).__name__, e)
    _SAMPLE_CACHE['v'] = out
    _SAMPLE_CACHE['why'] = why
    return out


def _sample_unavailable_reason():
    ansur_sample()
    return _SAMPLE_CACHE.get('why')


def _cells(sex_sample, sex):
    """(group_name, boolean selector) for every band cell a subject of this sex could be
    gated against — the pooled mixture and each DODRace group the pack kept."""
    ref = reference()
    n = sex_sample['n']
    out = [('pooled', np.ones(n, dtype=bool))]
    for g in ref.groups(sex):
        if g == 'pooled':
            continue
        code = sex_sample['group_codes'].get(g)
        if code is None:
            continue
        sel = sex_sample['race'] == code
        if int(sel.sum()) > 0:
            out.append((g, sel))
    return out


def _reject_ratio_bands(ratio_keys, width=BAND_WIDTH_BLOCK):
    """Fraction of the real sample that leaves at least one of these bands.

    Reported per (sex, ancestry group) cell, because that is the granularity at which a
    band is actually applied — a subject with a declared ancestry is judged against that
    group's band, and the joint rate differs by group. The governing number is the WORST
    cell, which is the same convention the pack uses for predictability (worse sex wins),
    and it is the only conservative choice when the subject's group is not known until
    run time.
    """
    ratio_keys = tuple(ratio_keys)
    key = ('bands', ratio_keys, width)
    if key in _REJECT_CACHE:
        return _REJECT_CACHE[key]
    if not ratio_keys:
        # Every band this gate declares is one _band_check demotes to REPORT, so there is
        # no band it can fail on and no fraction of the sample it can reject. That is NOT
        # a 0% rejection rate — a gate that cannot reject anybody has not earned a
        # blocking claim, it has no population claim at all — so the rate is None and
        # calibrate_gate's "no rate could be produced" rule takes the block away.
        out = {
            'kind': CAL_RATIO_BANDS,
            'rate': None,
            'basis': 'no_fail_capable_band',
            'reference_population': ANSUR_REFERENCE_POPULATION,
            'width': width,
            'ratios': [],
            'per_band_by_construction': None,
            'union_upper_bound': None,
            'cells': [],
            'reference_n': None,
            'explain': 'none of the bands this gate declares can produce a FAIL or a '
            'WARN on this cage (see ratios_excluded), so no rejection rate '
            'against the reference sample exists for it.',
            'source': 'no fail-capable band',
        }
        _REJECT_CACHE[key] = out
        return out
    ref = reference()
    # The band edges come from reference.WIDTHS rather than from a literal here, so that
    # 'what p1p99 means' has exactly one definition in the package.
    from zyg_workflows.geom.anthro.reference import WIDTHS

    kind, a, b = WIDTHS[width]
    if kind != 'percentile':
        raise GateConfigError('calibration only understands percentile band widths, got %r' % width)
    lo_p, hi_p = float(a), float(b)
    by_construction = (lo_p + (100.0 - hi_p)) / 100.0

    sample = ansur_sample()
    cells, per_ratio = [], {}
    if sample is not None:
        for sex in ('male', 'female'):
            ss = sample['by_sex'][sex]
            for group, sel in _cells(ss, sex):
                anc = None if group == 'pooled' else group
                bad = np.zeros(int(sel.sum()), dtype=bool)
                marg = {}
                for rk in ratio_keys:
                    band = ref.band(rk, sex, anc, width=width)
                    x = ss['ratios'][rk][sel]
                    out = (x < band['lo']) | (x > band['hi'])
                    marg[rk] = round(float(out.mean()), 5)
                    bad |= out
                cells.append(
                    {
                        'sex': sex,
                        'group': group,
                        'n': int(sel.sum()),
                        'rejected': round(float(bad.mean()), 5),
                        'per_ratio': marg,
                    }
                )
                per_ratio.setdefault(sex, {})[group] = marg
        worst = _worst_cell(cells)
        rate = worst['rejected']
        basis = 'measured'
        n_eff = worst['n']
        explain = (
            '%d band(s) at %s: measured on the real sample, the worst cell is %s '
            '%s (n=%d) at %.2f%% rejected; each single band excludes %.1f%% by '
            'construction.'
            % (len(ratio_keys), width, worst['sex'], worst['group'], worst['n'], 100.0 * rate, 100.0 * by_construction)
        )
    else:
        # No microdata: the band definition still forces a floor. One band at p1-p99
        # excludes 2% of ANY sample; k bands exclude at least that and at most k times it.
        rate = by_construction
        cells = []
        n_eff = None
        basis = 'by_construction'
        explain = (
            '%d band(s) at %s. The per-subject microdata could not be read (%s), so '
            'this is the LOWER BOUND the band definition forces: a %s band excludes '
            '%.1f%% of any sample by construction, and the union over %d bands is '
            'at least that and at most %.1f%%.'
            % (
                len(ratio_keys),
                width,
                _sample_unavailable_reason(),
                width,
                100.0 * by_construction,
                len(ratio_keys),
                100.0 * min(1.0, by_construction * len(ratio_keys)),
            )
        )
    out = {
        'kind': CAL_RATIO_BANDS,
        'rate': rate,
        'basis': basis,
        'explain': explain,
        'reference_population': ANSUR_REFERENCE_POPULATION,
        'width': width,
        'ratios': list(ratio_keys),
        'per_band_by_construction': by_construction,
        'union_upper_bound': min(1.0, by_construction * len(ratio_keys)),
        'cells': cells,
        'reference_n': n_eff,
        'source': (sample or {}).get('source') or 'band definition (percentile grid)',
        'rate_bound': (
            'upper bound on the gate as run: the rate is computed as if every '
            'band were measurable on this cage, and a ratio measure.py cannot '
            'produce returns UNMEASURABLE and rejects nobody'
        ),
    }
    _REJECT_CACHE[key] = out
    return out


def _reject_stature_anchored(pairs, sigma):
    """Fraction of the real sample outside |dimension - stature-regression| <= sigma*rmse.

    This is the gate that looks tightest and is loosest with real people: the residual
    band is a normal-tail band on EACH dimension, so a roll-up over eight of them rejects
    a quarter of the sample at sigma=2. Measured, not assumed.
    """
    pairs = tuple(pairs)
    key = ('anchor', pairs, float(sigma))
    if key in _REJECT_CACHE:
        return _REJECT_CACHE[key]
    ref = reference()
    tight = [(mk, dim) for mk, dim in pairs if ref.predictability(dim)['policy'] == 'tight']
    per_dim_normal = _norm_sf2(sigma)
    sample = ansur_sample()
    cells, n_eff = [], None
    if sample is not None and tight:
        for sex in ('male', 'female'):
            ss = sample['by_sex'][sex]
            diag = ref.doc['diagnostics'][sex]
            st = ss['stature_mm']
            bad = np.zeros(ss['n'], dtype=bool)
            marg = {}
            for _mk, dim in tight:
                d = diag[dim]
                x = ss['dimensions'][dim]
                resid = x - (d['slope_mm_per_mm_stature'] * st + d['intercept_mm'])
                out = np.abs(resid) > sigma * d['rmse_mm']
                marg[dim] = round(float(out.mean()), 5)
                bad |= out
            cells.append(
                {
                    'sex': sex,
                    'group': 'pooled',
                    'n': int(ss['n']),
                    'rejected': round(float(bad.mean()), 5),
                    'per_ratio': marg,
                }
            )
        worst = _worst_cell(cells)
        rate = worst['rejected']
        n_eff = worst['n']
        basis = 'measured'
        explain = (
            '%d dimension(s) gated at +/-%g x the MEASURED residual rmse. Measured '
            'on the real sample: %.2f%% of the worse sex falls outside at least '
            'one of them (a single +/-%g-rmse band excludes %.2f%% of a normal '
            'residual by itself).' % (len(tight), sigma, 100.0 * rate, sigma, 100.0 * per_dim_normal)
        )
    else:
        rate = per_dim_normal
        basis = 'by_construction'
        explain = (
            '%d dimension(s) at +/-%g x rmse; the per-subject microdata could not '
            'be read (%s), so this is the normal-tail floor for ONE dimension, '
            '%.2f%%. The roll-up over %d cannot be lower.'
            % (len(tight), sigma, _sample_unavailable_reason(), 100.0 * per_dim_normal, len(tight))
        )
    out = {
        'kind': CAL_STATURE_ANCHORED,
        'rate': rate,
        'basis': basis,
        'explain': explain,
        'reference_population': ANSUR_REFERENCE_POPULATION,
        'sigma': float(sigma),
        'dimensions': [d for _m, d in tight],
        'dimensions_not_tight': [d for _m, d in pairs if (_m, d) not in tight],
        'per_band_by_construction': per_dim_normal,
        'cells': cells,
        'reference_n': n_eff,
        'source': (sample or {}).get('source') or 'normal tail of the MEASURED rmse',
    }
    _REJECT_CACHE[key] = out
    return out


def _substituted_column(sex, sub_spec):
    """The per-subject values of a vector component AS THIS PIPELINE SUPPLIES IT.

    A component the cage cannot measure is not simply missing from the gate: measure.py
    substitutes a HOUSE value for it (cervicale = suprasternale + a per-sex ANSUR mean
    offset) and publishes it under the ANSUR name. Rebuilding that same substitution over
    the reference sample is what makes the calibration a statement about the gate that
    runs rather than about the model the pack shipped.

    Returns (values, description) or (None, why-not).
    """
    sample = ansur_sample()
    if sample is None:
        return None, (
            'per-subject microdata unavailable (%s), so the substitution cannot '
            'be rebuilt over the reference sample' % _sample_unavailable_reason()
        )
    src = sub_spec['from_ratio']
    ss = sample['by_sex'][sex]
    if src not in ss['ratios']:
        return None, 'the reference pack ships no per-subject %s' % src
    off = sub_spec['offset_frac_stature'][sex]
    # The description is written per-sex-agnostic on purpose: it is stored once per
    # component and would otherwise report whichever sex the loop happened to finish on.
    return (
        np.asarray(ss['ratios'][src], dtype=np.float64) + float(off),
        '%s + the per-sex ANSUR mean offset (%s) — %s'
        % (
            src,
            ', '.join('%s %.4f' % (s, v) for s, v in sorted(sub_spec['offset_frac_stature'].items())),
            sub_spec.get('offset_source') or 'offset source not stated',
        ),
    )


def _reject_empirical_percentile(spec):
    """A threshold that IS an empirical percentile of the reference rejects 100-p percent
    of it by construction. Verified numerically against the pack's per-subject D^2 where
    the arrays exist, because 'by construction' is a claim about the builder and this is
    the cheapest place to check the builder kept it.

    AND, where the gate does not feed the model the pack's own coordinates, the rate is
    re-measured on the vector AS SUBSTITUTED. This is not a refinement. t2_mahalanobis
    feeds a cervicale coordinate that is suprasternale plus a mean offset (the cage has no
    vertebra prominens); in ANSUR the two correlate at only r=0.545 (male) / 0.480
    (female), so the substituted coordinate is a materially different quantity from the one
    the covariance was estimated on. Measured consequence at the shipped p99 threshold:
    1.176% of real men are rejected instead of 1.004%, 19 of the 41 men the real model
    rejects now pass, and 26 it passes are now rejected. Certifying that gate's licence to
    block with the rate of a model it does not run is the failure this branch exists to
    stop.
    """
    pct = float(spec['percentile'])
    by_construction = (100.0 - pct) / 100.0
    subs = spec.get('substitutions') or {}
    # The cache key carries the substitution CONTENT, not just the component names: two
    # gates substituting the same coordinate with different offsets are two different
    # measurements and must not share a cached rate.
    key = (
        'emp',
        pct,
        spec.get('verify'),
        tuple(spec.get('components') or ()),
        tuple(
            sorted(
                (k, v.get('from_ratio'), tuple(sorted((v.get('offset_frac_stature') or {}).items())))
                for k, v in subs.items()
            )
        ),
    )
    if key in _REJECT_CACHE:
        return _REJECT_CACHE[key]
    cells, n_eff, basis = [], None, 'by_construction'
    verified = None  # the rate of the model as the PACK built it
    as_configured = None  # the rate of the vector as THIS PIPELINE supplies it
    sub_notes, sub_fail = {}, None
    if spec.get('verify') == 'mahalanobis':
        try:
            ref = reference()
            order = ref.doc['mahalanobis']['order']
            comps = list(spec.get('components') or order)
            idx = tuple(order.index(k) for k in comps)
            model_cells, conf_cells = [], []
            for sex in ('male', 'female'):
                vec = np.asarray(ref.npz['%s_vectors' % sex], dtype=np.float64)
                mu, inv, thr, _src = ref._model(sex, idx)
                X = vec[:, list(idx)]
                dv = X - mu
                d2 = np.einsum('ij,jk,ik->i', dv, inv, dv)
                model_cells.append(
                    {
                        'sex': sex,
                        'group': 'pooled',
                        'n': int(len(d2)),
                        'rejected': round(float((d2 > thr['p99']).mean()), 5),
                        'per_ratio': {},
                        'vector': 'as the pack built it',
                    }
                )
                if not subs:
                    continue
                Xs = X.copy()
                for comp_key, sub_spec in subs.items():
                    if comp_key not in comps:
                        raise GateConfigError(
                            'calibration declares a substitution for %r, which is not one '
                            "of this gate's components %r" % (comp_key, comps)
                        )
                    col, note = _substituted_column(sex, sub_spec)
                    sub_notes[comp_key] = note
                    if col is None:
                        raise IOError(note)
                    if len(col) != len(Xs):
                        raise ValueError(
                            'substituted column for %s has %d rows, the pack '
                            'vectors have %d' % (comp_key, len(col), len(Xs))
                        )
                    Xs[:, comps.index(comp_key)] = col
                dvs = Xs - mu
                d2s = np.einsum('ij,jk,ik->i', dvs, inv, dvs)
                conf_cells.append(
                    {
                        'sex': sex,
                        'group': 'pooled',
                        'n': int(len(d2s)),
                        'rejected': round(float((d2s > thr['p99']).mean()), 5),
                        'per_ratio': {},
                        'vector': 'AS SUBSTITUTED by this pipeline',
                        'moved_off_reject': int(((d2 > thr['p99']) & (d2s <= thr['p99'])).sum()),
                        'moved_onto_reject': int(((d2 <= thr['p99']) & (d2s > thr['p99'])).sum()),
                    }
                )
            verified = _worst_cell(model_cells)['rejected']
            cells = model_cells
            if subs:
                worst = _worst_cell(conf_cells)
                as_configured = worst['rejected']
                n_eff = worst['n']
                cells = conf_cells + model_cells
            else:
                n_eff = _worst_cell(model_cells)['n']
            basis = 'measured'
        except Exception as e:  # noqa: BLE001
            # A substitution that could not be rebuilt is NOT a licence to fall back to
            # the model's own rate: that is precisely the number that overstates this
            # gate's right to block. rate stays None and calibrate_gate takes the block
            # away.
            sub_fail = '%s: %s' % (type(e).__name__, e)
            cells, verified, as_configured = [], None, None
            basis = 'error' if subs else 'by_construction'
            spec = dict(spec, verify_error=sub_fail)
    if subs:
        rate = as_configured
    else:
        rate = by_construction if verified is None else verified
    detail = ''
    if verified is not None:
        detail += (
            '; measured %.3f%% on the shipped per-subject arrays, the difference '
            'being that an empirical percentile cannot be resolved finer than one '
            'subject in n' % (100.0 * verified)
        )
    if subs:
        if as_configured is None:
            detail += (
                '. THE GATE AS CONFIGURED COULD NOT BE MEASURED (%s), so no rejection rate exists for it' % sub_fail
            )
        else:
            detail += (
                ". But this gate does not feed the model the pack's own "
                'coordinates: %s. Run on the vector AS SUBSTITUTED the same '
                'threshold rejects %.3f%% of the reference, and THAT is the number '
                'this gate is judged on'
                % (
                    '; '.join('%s = %s' % (k, v) for k, v in sorted(sub_notes.items())) or 'substitutions declared',
                    100.0 * as_configured,
                )
            )
    out = {
        'kind': CAL_EMPIRICAL_PERCENTILE,
        'rate': rate,
        'basis': basis,
        'percentile': pct,
        'per_band_by_construction': by_construction,
        'reference_population': spec.get('reference_population') or ANSUR_REFERENCE_POPULATION,
        'cells': cells,
        'reference_n': n_eff,
        'rate_of_model_as_built': verified,
        'rate_as_configured': as_configured,
        'substitutions': {k: dict(v, rebuilt_as=sub_notes.get(k)) for k, v in subs.items()},
        'explain': (spec.get('why') or '')
        + (
            ' Threshold is the empirical p%g of the reference itself, so it '
            'rejects %.1f%% of it by construction%s.' % (pct, 100.0 * by_construction, detail)
        ),
        'source': spec.get('source') or 'empirical percentile of the reference sample',
        'verify_error': spec.get('verify_error'),
    }
    _REJECT_CACHE[key] = out
    return out
