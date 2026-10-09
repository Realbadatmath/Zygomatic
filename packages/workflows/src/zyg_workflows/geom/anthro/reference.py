# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""reference.py — runtime query API over the anthropometric reference pack.

WHY THIS EXISTS: the pack is a large JSON document with a schema that is easy to misread
in exactly the ways that produce a biased gate. This module is the only supported way to
read it, so that four mistakes become impossible rather than merely discouraged.

  1. A band cannot be returned without its source and its population. Callers print
     provenance because they cannot get a number without one.
  2. Asking for a band with ancestry=None does not silently mean "the average human". It
     returns the pooled distribution WITH ancestry_declared=False set in the reply, so a
     caller that never declared an ancestry is visibly gating against a US Army mixture
     rather than against the character's population. The largest proportion effect in the
     data is ancestry (crotch-height/stature spans ~0.024 between male groups, 44 mm of
     leg on a 1.85 m man), so this is not a formality.
  3. The joint plausibility check is Mahalanobis against the stored 10-D ratio vector,
     with EMPIRICAL thresholds. Ten independent 90% bands admit under half the real
     sample (measured) and also admit combinations no human has, so there is deliberately
     no "check every band independently" convenience here.
  4. Supplying only some of the ten vector components does not fall back to a chi-square
     approximation. The pack ships the per-subject ratio vectors, so the marginal model
     for whatever subset was measured is built exactly and its thresholds are empirical
     too.

Nothing here evaluates whether a body is attractive, ideal or correct. It reports how
unusual a body is, against a named population, on a stated measurement convention.
"""

import json
import math
import os
import threading

import numpy as np

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'data', 'assets', 'anthro_reference'
)
SCHEMA_VERSION = 1

# width -> how lo/hi are taken. Percentile widths read the empirical grid; sd widths are
# gaussian and are offered only for callers that need a symmetric interval — the ratio
# distributions are not all symmetric, so the percentile widths are the honest default.
WIDTHS = {
    'p1p99': ('percentile', 1, 99),
    'p5p95': ('percentile', 5, 95),
    'p25p75': ('percentile', 25, 75),
    'sd1': ('sd', 1.0, None),
    'sd2': ('sd', 2.0, None),
    'sd3': ('sd', 3.0, None),
}


def _norm_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


class AnthroReference(object):
    """Lazy, cached reader for data/assets/anthro_reference/.

    Loads reference.json on first query and mahalanobis.npz only when a joint check is
    actually asked for, because most callers never need the 273 kB of arrays.
    """

    def __init__(self, root=ROOT):
        self.root = root
        self._doc = None
        self._prov = None
        self._npz = None
        self._marginal = {}
        self._lock = threading.RLock()

    # -- loading ---------------------------------------------------------------
    @property
    def doc(self):
        if self._doc is None:
            with self._lock:
                if self._doc is None:
                    path = os.path.join(self.root, 'reference.json')
                    if not os.path.exists(path):
                        raise IOError(
                            'anthropometric reference pack missing at %s — build it with '
                            '`python3 -m zyg_workflows.geom.anthro.build_reference`' % path
                        )
                    with open(path) as f:
                        doc = json.load(f)
                    if doc.get('schema_version') != SCHEMA_VERSION:
                        raise ValueError(
                            'reference pack schema_version %r, this module '
                            'speaks %d' % (doc.get('schema_version'), SCHEMA_VERSION)
                        )
                    self._doc = doc
        return self._doc

    @property
    def prov_doc(self):
        if self._prov is None:
            with self._lock:
                if self._prov is None:
                    with open(os.path.join(self.root, 'PROVENANCE.json')) as f:
                        self._prov = json.load(f)
        return self._prov

    @property
    def npz(self):
        if self._npz is None:
            with self._lock:
                if self._npz is None:
                    self._npz = np.load(os.path.join(self.root, 'mahalanobis.npz'))
        return self._npz

    # -- vocabulary ------------------------------------------------------------
    def ratios(self):
        return sorted(self.doc['ratios'])

    def dimensions(self):
        return sorted(self.doc['dimensions'])

    def groups(self, sex):
        return sorted(self.doc['stats'][self._sex(sex)])

    def _sex(self, sex):
        s = str(sex).strip().lower()
        if s in ('m', 'male'):
            return 'male'
        if s in ('f', 'female'):
            return 'female'
        raise ValueError(
            'sex must be male|female, got %r. The pack has no other sex '
            'strata; ANSUR II is published as two single-sex files.' % (sex,)
        )

    def _cell(self, ratio, sex, ancestry):
        """Returns (stats_cell, group_name, ancestry_declared). Unknown names fail loudly
        with the valid set, because a typo'd ancestry silently falling back to pooled is
        exactly the bias this pack exists to prevent."""
        sex = self._sex(sex)
        if ratio not in self.doc['ratios']:
            raise KeyError('unknown ratio %r. Known: %s' % (ratio, ', '.join(self.ratios())))
        declared = ancestry is not None
        if not declared:
            group = 'pooled'
        else:
            group = str(ancestry).strip().lower()
            if group not in self.doc['stats'][sex]:
                dropped = [d for d in self.doc['dropped_groups'] if d['sex'] == sex and d['group'] == group]
                if dropped:
                    raise KeyError(
                        'ancestry %r exists in ANSUR II for %s but only n=%d, below the '
                        'n>=%d floor, so no band was built. Do not substitute pooled '
                        'silently — decide explicitly.' % (group, sex, dropped[0]['n'], self.doc['min_group_n'])
                    )
                raise KeyError(
                    'unknown ancestry %r for %s. Available: %s' % (ancestry, sex, ', '.join(self.groups(sex)))
                )
        return self.doc['stats'][sex][group][ratio], group, declared

    def _source_line(self, sex, group, n):
        cov = self.doc['coverage']
        return (
            'ANSUR II 2012 working database (public release), %s %s, DODRace '
            'group=%s, n=%d, ages %d-%d, measured 2010-10..2012-04'
            % (cov['ansur_population'], sex, group, n, cov['ansur_age_years'][0], cov['ansur_age_years'][1])
        )

    def _population_line(self, sex, group):
        base = (
            'US Army personnel %s, stratified to match Total Army DMDC census '
            '2011-09-30. NOT a civilian population.' % sex
        )
        if group == 'pooled':
            return base + ' Pooled across all DODRace groups.'
        return base + ' DODRace group: %s.' % group

    # -- required surface ------------------------------------------------------
    def band(self, ratio, sex, ancestry=None, width='p5p95'):
        """A plausibility interval for one ratio.

        A band is a MARGINAL statement: it says nothing about whether this ratio can
        co-occur with the others on the same body. Use mahalanobis() for that. Returns
        lo/hi/mean/sd/n/source plus the population and the provenance a caller needs to
        print, and ancestry_declared=False when no ancestry was given.
        """
        if width not in WIDTHS:
            raise ValueError('width must be one of %s, got %r' % (', '.join(sorted(WIDTHS)), width))
        cell, group, declared = self._cell(ratio, sex, ancestry)
        sex = self._sex(sex)
        kind, a, b = WIDTHS[width]
        if kind == 'percentile':
            lo, hi = cell['q'][a], cell['q'][b]
        else:
            lo, hi = cell['mean'] - a * cell['sd'], cell['mean'] + a * cell['sd']
        spec = self.doc['ratios'][ratio]
        out = {
            'lo': float(lo),
            'hi': float(hi),
            'mean': float(cell['mean']),
            'sd': float(cell['sd']),
            'n': int(cell['n']),
            'source': self._source_line(sex, group, cell['n']),
            'population': self._population_line(sex, group),
            'ratio': ratio,
            'sex': sex,
            'ancestry': group,
            'ancestry_declared': declared,
            'width': width,
            'units': spec['units'],
            'definition': spec['definition'],
            'iso_class': spec['iso_class'],
            'licence': 'public domain (US Government work, 17 USC 105)',
        }
        if not declared:
            out['note'] = (
                'no ancestry declared — this is the POOLED US Army mixture. '
                'Ancestry is the largest proportion effect in the data; a '
                'single-population band used as a universal gate is a bias, '
                'not a tolerance.'
            )
        return out

    def percentile(self, ratio, value, sex, ancestry=None):
        """Empirical percentile of `value`, linearly interpolated inside the stored
        101-point grid. Values outside the observed range return 0.0 or 100.0, which is
        the true empirical answer (no member of the sample was more extreme) and not a
        clamp of a computable number."""
        cell, _, _ = self._cell(ratio, sex, ancestry)
        q = np.asarray(cell['q'], dtype=np.float64)
        return float(np.interp(float(value), q, np.arange(101, dtype=np.float64)))

    def mahalanobis(self, ratios, sex):
        """Joint plausibility of a body's frame proportions — the PRIMARY gate.

        `ratios` maps ratio keys (see doc['mahalanobis']['order']) to measured values.
        Any subset of the ten may be supplied: the marginal model for that subset is
        built exactly from the stored per-subject vectors, and its thresholds are the
        empirical percentiles of that subset's D^2 in the real sample.

        pass_  : D^2 <= the empirical p99 threshold (inside the 99% envelope)
        warn   : p95 < D^2 <= p99 (unusual but real; surface it, do not reject)
        missing: vector components the caller did not supply
        """
        sex = self._sex(sex)
        order = self.doc['mahalanobis']['order']
        idx, used, missing = [], [], []
        for i, key in enumerate(order):
            if key in ratios and ratios[key] is not None:
                idx.append(i)
                used.append(key)
            else:
                missing.append(key)
        ignored = sorted(k for k in ratios if k not in order)
        if not idx:
            raise ValueError('mahalanobis() needs at least one of the vector components: %s' % ', '.join(order))

        mu, inv, thr, tsrc = self._model(sex, tuple(idx))
        x = np.asarray([float(ratios[k]) for k in used], dtype=np.float64)
        d = x - mu
        d2 = float(d @ inv @ d)
        meta = self.doc['mahalanobis']['sexes'][sex]
        return {
            'd2': d2,
            'pass_': bool(d2 <= thr['p99']),
            'warn': bool(thr['p95'] < d2 <= thr['p99']),
            'thresholds': dict(thr, source=tsrc),
            'missing': missing,
            'order': order,
            'used': used,
            'ignored': ignored,
            'k': len(idx),
            'sex': sex,
            'reference_n': int(meta['n']),
            'source': self._source_line(sex, 'pooled', meta['n']),
            'chi2_reference': meta['chi2_reference'],
            'note': (
                'thresholds are EMPIRICAL percentiles of D^2 in the real sample. The '
                'chi-square value is reported only for comparison: on this data '
                'chi2(df=%d, .95)=%.3f actually passes %.4f of real people, not '
                '0.95.'
                % (
                    meta['chi2_reference']['df'],
                    meta['chi2_reference']['p95_value'],
                    meta['chi2_reference']['p95_empirical_pass_rate'],
                )
            ),
        }

    def stature_z(self, height_cm, age_months, sex):
        """CDC 2000 stature-for-age LMS z and percentile. Ages 24-240 months only; an
        out-of-range age raises rather than extrapolating a growth curve."""
        return self._lms('stature_for_age_cm', float(height_cm), age_months, sex)

    def bmi_percentile(self, bmi, age_months, sex):
        """CDC 2000 BMI-for-age LMS z and percentile. Flags the region where the LMS tail
        stops being trustworthy and CDC's extended percentiles apply instead."""
        out = self._lms('bmi_for_age', float(bmi), age_months, sex)
        if out['percentile'] > 95.0:
            out['caveat'] = (
                'above the 95th percentile the CDC 2000 LMS tail is known to '
                'be unreliable; CDC publishes extended BMI-for-age '
                'percentiles for this region and this pack does not carry '
                'them. Treat z as indicative only.'
            )
        return out

    def predictability(self, dimension):
        """How well stature predicts one raw dimension, and therefore whether it may be
        gated against a stature-anchored point at all.

        r is the WORSE of the two sexes and rmse_mm the larger, so the policy is never
        softer than the data supports for either. policy=='wide' means: gate against the
        population band for the group, never against a value derived from stature.
        """
        d = self.doc['predictability']
        if dimension not in d:
            raise KeyError('unknown dimension %r. Known: %s' % (dimension, ', '.join(self.dimensions())))
        out = dict(d[dimension])
        out['dimension'] = dimension
        out['rule'] = self.doc['predictability_policy']['rule']
        out['provenance'] = self.doc['predictability_policy']['provenance']
        out['consequence'] = self.doc['predictability_policy']['consequence']
        out['iso_20685_1_mean_diff_mm'] = self.doc['iso_20685_1_table4_mm'].get(out['iso_class'])
        out['iso_caveat'] = (
            'ISO 20685-1 Table 4 bounds a MEAN difference across a '
            'validation sample, not a per-mesh error. Per-mesh use is '
            'HOUSE policy and must be labelled as such.'
        )
        return out

    def provenance(self, key=None):
        """key=None returns the whole PROVENANCE document. Otherwise a source name
        ('ansur_ii_2012', 'cdc_growth_charts_2000', 'iso_20685_1_2018', 'nhanes_iii'), or
        one of the pack-level keys 'conventions', 'gaps', 'coverage',
        'predictability_policy', 'dropped_groups', 'schema'."""
        if key is None:
            return self.prov_doc
        if key in self.prov_doc['sources']:
            return self.prov_doc['sources'][key]
        if key in self.doc:
            return self.doc[key]
        raise KeyError(
            'unknown provenance key %r. Sources: %s. Pack keys: %s'
            % (
                key,
                ', '.join(sorted(self.prov_doc['sources'])),
                ', '.join(['conventions', 'gaps', 'coverage', 'predictability_policy', 'dropped_groups', 'schema']),
            )
        )

    # -- internals -------------------------------------------------------------
    def _model(self, sex, idx):
        """Mean, inverse covariance and empirical thresholds for a subset of the vector.

        For the full ten components this is the model stored by the builder. For a subset
        it is the exact marginal — a marginal of a multivariate distribution is obtained
        by taking the sub-mean and SUB-COVARIANCE, not by dropping columns of the inverse,
        which would give the conditional instead."""
        cached = self._marginal.get((sex, idx))
        if cached is not None:
            return cached
        with self._lock:
            cached = self._marginal.get((sex, idx))
            if cached is not None:
                return cached
            npz = self.npz
            full = tuple(range(len(self.doc['mahalanobis']['order'])))
            if idx == full:
                mu = npz['%s_mu' % sex]
                inv = npz['%s_inv' % sex]
                d2 = npz['%s_d2' % sex].astype(np.float64)
                tsrc = 'empirical, full %d-D vector, n=%d' % (len(idx), d2.size)
            else:
                X = npz['%s_vectors' % sex].astype(np.float64)[:, list(idx)]
                mu = X.mean(axis=0)
                inv = np.linalg.inv(np.cov(X, rowvar=False)) if len(idx) > 1 else np.asarray([[1.0 / X.var(ddof=1)]])
                dv = X - mu
                d2 = np.einsum('ij,jk,ik->i', dv, inv, dv)
                tsrc = 'empirical marginal over %d of %d components, n=%d' % (len(idx), len(full), d2.size)
            thr = {'p95': float(np.percentile(d2, 95)), 'p99': float(np.percentile(d2, 99))}
            out = (np.asarray(mu, dtype=np.float64), np.asarray(inv, dtype=np.float64), thr, tsrc)
            self._marginal[(sex, idx)] = out
            return out

    def _lms(self, measure, value, age_months, sex):
        sex = self._sex(sex)
        tab = self.doc['cdc_lms'][measure][sex]
        age = float(age_months)
        lo, hi = self.doc['cdc_lms']['coverage_agemos']
        if not (lo <= age <= hi):
            raise ValueError(
                'age_months %.3f outside CDC LMS coverage [%g, %g]. The '
                'growth curves are not defined here and will not be '
                'extrapolated.' % (age, lo, hi)
            )
        if value <= 0:
            raise ValueError('%s value must be positive, got %r' % (measure, value))
        ages = np.asarray(tab['agemos'], dtype=np.float64)
        L = float(np.interp(age, ages, tab['L']))
        M = float(np.interp(age, ages, tab['M']))
        S = float(np.interp(age, ages, tab['S']))
        z = (math.log(value / M) / S) if abs(L) < 1e-12 else (((value / M) ** L) - 1.0) / (L * S)
        return {
            'z': z,
            'percentile': 100.0 * _norm_cdf(z),
            'L': L,
            'M': M,
            'S': S,
            'measure': measure,
            'sex': sex,
            'age_months': age,
            'value': value,
            'source': 'CDC 2000 growth charts (NCHS), US children 24-240 months, public domain',
            'interpolation': 'L, M and S linearly interpolated between the half-month grid points',
        }


_SINGLETON = None
_SINGLETON_LOCK = threading.Lock()


def reference(root=ROOT):
    """Module-level singleton. One process holds one parsed copy of the pack; the arrays
    are still loaded lazily inside it."""
    global _SINGLETON
    if _SINGLETON is None or _SINGLETON.root != root:
        with _SINGLETON_LOCK:
            if _SINGLETON is None or _SINGLETON.root != root:
                _SINGLETON = AnthroReference(root)
    return _SINGLETON


get_reference = reference  # alias for callers that prefer the verbose name


def _selftest():
    """Exercises every public method against the built pack and prints what it actually
    measured. Run: python3 -m zyg_workflows.geom.anthro.reference"""
    ref = reference()
    _zyg_log.info('pack %s  schema=%d  ratios=%d' % (ref.root, ref.doc['schema_version'], len(ref.ratios())))
    _zyg_log.info('groups male=%s female=%s' % (ref.groups('male'), ref.groups('female')))

    for anc in (None, 'black', 'asian'):
        b = ref.band('crotch_height_over_stature', 'male', anc)
        _zyg_log.info(
            'band crotch/stature male anc=%-6s p5=%.4f p95=%.4f mean=%.4f n=%d '
            'declared=%s' % (anc, b['lo'], b['hi'], b['mean'], b['n'], b['ancestry_declared'])
        )
    b = ref.band('bideltoid_breadth_over_stature', 'female', 'white', width='p1p99')
    _zyg_log.info('band bideltoid/stature female white p1p99 lo=%.4f hi=%.4f  src=%s' % (b['lo'], b['hi'], b['source']))

    for anc in ('white', 'black'):
        p = ref.percentile('crotch_height_over_stature', 0.4850, 'male', anc)
        _zyg_log.info('percentile crotch/stature=0.4850 male %-5s -> %.2f' % (anc, p))

    order = ref.doc['mahalanobis']['order']
    mu = ref.npz['male_mu']
    typical = {k: float(v) for k, v in zip(order, mu)}
    r = ref.mahalanobis(typical, 'male')
    _zyg_log.info('maha at the sample mean: d2=%.6f pass=%s warn=%s k=%d' % (r['d2'], r['pass_'], r['warn'], r['k']))
    odd = dict(typical)
    odd['crotch_height_over_stature'] += 0.030
    r = ref.mahalanobis(odd, 'male')
    _zyg_log.info(
        'maha with +0.030 crotch: d2=%.3f pass=%s warn=%s thr=%s'
        % (r['d2'], r['pass_'], r['warn'], {k: round(v, 3) for k, v in r['thresholds'].items() if k != 'source'})
    )
    part = {k: typical[k] for k in order[:4]}
    r = ref.mahalanobis(part, 'male')
    _zyg_log.info(
        'maha marginal k=%d d2=%.4f missing=%d thr_p95=%.3f (%s)'
        % (r['k'], r['d2'], len(r['missing']), r['thresholds']['p95'], r['thresholds']['source'])
    )

    z = ref.stature_z(152.0, 12 * 12, 'male')
    _zyg_log.info(
        'stature_z 152.0cm 144mo male: z=%.4f pct=%.2f L=%.4f M=%.2f S=%.5f'
        % (z['z'], z['percentile'], z['L'], z['M'], z['S'])
    )
    bp = ref.bmi_percentile(18.5, 12 * 12, 'male')
    _zyg_log.info('bmi_percentile 18.5 144mo male: z=%.4f pct=%.2f' % (bp['z'], bp['percentile']))

    for dim in ('cervicale_height', 'bideltoid_breadth', 'sitting_height'):
        p = ref.predictability(dim)
        _zyg_log.info(
            'predictability %-20s r=%.3f rmse=%.2fmm policy=%s halfwidth=%.1fmm'
            % (dim, p['r'], p['rmse_mm'], p['policy'], p['stature_anchored_halfwidth_mm'])
        )
    _zyg_log.info(
        ' '.join(str(a) for a in ('provenance ansur licence:', ref.provenance('ansur_ii_2012')['licence'][:60]))
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(_selftest())
