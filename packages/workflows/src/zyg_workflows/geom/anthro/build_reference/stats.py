# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""build_reference — io helpers and the summary / ratio / Mahalanobis statistics.

Moved verbatim out of build_reference.py; see the package __init__ for the full rationale.
"""

import csv
import hashlib
import json
import numpy as np
import os
from zyg_workflows.geom.anthro.build_reference.constants import (
    CHI2_DF10,
    DIMENSIONS,
    IMPORT_DIR,
    INDICES,
    ISO_20685_1_TABLE4_MM,
    MAHALANOBIS_ORDER,
    PERCENTILE_GRID,
    REPORT_PERCENTILES,
    SOURCE_FILES,
)


# ---------------------------------------------------------------------------
# io helpers
# ---------------------------------------------------------------------------
def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _atomic_json(path, doc, **kw):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(doc, f, **kw)
    os.replace(tmp, path)


def _atomic_npz(path, **arrays):
    tmp = path + '.tmp.npz'
    np.savez(tmp, **arrays)
    os.replace(tmp, path)


def _r6(x):
    """Six decimals. Ratios live in 0.03..1.1 so this keeps ~5 significant figures while
    holding reference.json to a size that is cheap to parse at runtime."""
    return round(float(x), 6)


def _resolve_sources(source_dir, out_root):
    """Repo copy wins, so a rebuild reproduces the shipped pack rather than whatever the
    download directory happens to hold now. --source-dir forces a re-import."""
    repo_src = os.path.join(out_root, 'source')
    if source_dir:
        base, mapping, origin = source_dir, {r: i for r, i in SOURCE_FILES}, 'import'
    elif all(os.path.exists(os.path.join(repo_src, r)) for r, _ in SOURCE_FILES):
        base, mapping, origin = repo_src, {r: r for r, _ in SOURCE_FILES}, 'repo'
    else:
        base, mapping, origin = IMPORT_DIR, {r: i for r, i in SOURCE_FILES}, 'import'
    out = {}
    for repo_name, _ in SOURCE_FILES:
        p = os.path.join(base, mapping[repo_name])
        if not os.path.exists(p):
            raise IOError('source not found: %s (looked in %s, origin=%s)' % (repo_name, base, origin))
        out[repo_name] = p
    return out, origin


def _load_ansur(path):
    """Returns (cols, dodrace, n). ANSUR II public CSVs contain no missing numeric cells;
    a blank in any column we use is a corrupted file and must stop the build."""
    with open(path, encoding='latin-1', newline='') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError('empty ANSUR csv: %s' % path)
    cols = {}
    for key in rows[0]:
        lk = key.lower()
        vals = []
        for r in rows:
            v = (r[key] or '').strip()
            if not v:
                vals = None
                break
            try:
                vals.append(float(v))
            except ValueError:
                vals = None
                break
        if vals is not None:
            cols[lk] = np.asarray(vals, dtype=np.float64)
    race = np.asarray([int(r['DODRace']) for r in rows], dtype=np.int32)
    return cols, race, len(rows)


def _load_lms(path):
    """CDC LMS csv. bmiagerev.csv repeats its header mid-file (verified: line 221), which
    a naive DictReader turns into a row of the string 'Sex' — drop those explicitly."""
    with open(path, newline='') as f:
        rows = [r for r in csv.DictReader(f) if r.get('Sex') not in (None, 'Sex')]
    out = {}
    for sex_code, sex in ((1, 'male'), (2, 'female')):
        sel = [r for r in rows if int(r['Sex']) == sex_code]
        sel.sort(key=lambda r: float(r['Agemos']))
        out[sex] = {
            'agemos': [float(r['Agemos']) for r in sel],
            'L': [float(r['L']) for r in sel],
            'M': [float(r['M']) for r in sel],
            'S': [float(r['S']) for r in sel],
        }
    return out


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------
def _summary(x):
    x = np.asarray(x, dtype=np.float64)
    mean = float(x.mean())
    sd = float(x.std(ddof=1))
    q = np.percentile(x, PERCENTILE_GRID)
    doc = {
        'n': int(x.size),
        'mean': _r6(mean),
        'sd': _r6(sd),
        'cv': _r6(sd / mean) if mean else None,
        'min': _r6(x.min()),
        'max': _r6(x.max()),
        'q': [_r6(v) for v in q],
    }
    for p in REPORT_PERCENTILES:
        doc['p%d' % p] = _r6(q[p])
    return doc


def _ratio_values(cols, key, spec):
    if spec['kind'] == 'stature_ratio':
        return cols[DIMENSIONS[spec['numerator']]['ansur']] / cols['stature']
    if spec['kind'] == 'index':
        num = cols[DIMENSIONS[spec['numerator']]['ansur']]
        den = cols[DIMENSIONS[spec['denominator']]['ansur']]
        return spec['scale'] * num / den
    if spec['kind'] == 'derived':
        if key == 'bmi':
            # weightkg is HECTOGRAMS (mean 855.2 => 85.52 kg); stature is millimetres.
            return (cols['weightkg'] / 10.0) / (cols['stature'] / 1000.0) ** 2
        if key == 'waist_over_stature':
            return cols['waistcircumference'] / cols['stature']
    raise KeyError('no value rule for ratio %s' % key)


def _build_ratio_specs():
    specs = {}
    for dim, meta in DIMENSIONS.items():
        specs[dim + '_over_stature'] = {
            'kind': 'stature_ratio',
            'numerator': dim,
            'denominator': 'stature',
            'scale': 1.0,
            'iso_class': meta['iso_class'],
            'units': 'dimensionless',
            'definition': '%s / stature; numerator = ANSUR II "%s" at %s (%s)'
            % (dim, meta['ansur'], meta['landmark'], meta['convention']),
        }
    for name, meta in INDICES.items():
        specs[name] = {
            'kind': 'index',
            'numerator': meta['num'],
            'denominator': meta['den'],
            'scale': meta['scale'],
            'iso_class': 'index',
            'units': 'dimensionless' if meta['scale'] == 1.0 else 'x%g' % meta['scale'],
            'definition': '%s / %s%s. %s'
            % (meta['num'], meta['den'], '' if meta['scale'] == 1.0 else ' x %g' % meta['scale'], meta['note']),
        }
    specs['bmi'] = {
        'kind': 'derived',
        'numerator': 'weightkg',
        'denominator': 'stature',
        'scale': 1.0,
        'iso_class': 'index',
        'units': 'kg/m^2',
        'definition': 'ANSUR II weightkg (HECTOGRAMS, /10 for kg) / (stature_mm/1000)^2',
    }
    specs['waist_over_stature'] = {
        'kind': 'derived',
        'numerator': 'waist_circumference_omphalion',
        'denominator': 'stature',
        'scale': 1.0,
        'iso_class': 'index',
        'units': 'dimensionless',
        'definition': 'waist circumference (OMPHALION) / stature — waist-to-height ratio, '
        'at the ANSUR site, which is NOT the WHO or NIH waist site',
    }
    return specs


def _diagnostics(cols, sex_n):
    """r and residual RMSE of every dimension against stature, in millimetres.

    This is the evidence for the heights-tight / breadths-wide policy. It is computed
    here rather than asserted so that a consumer can re-derive the policy, and so that
    the surprises stay visible: lateral malleolus height is a HEIGHT and is nonetheless
    almost unpredictable from stature."""
    st = cols['stature']
    A = np.column_stack([st, np.ones_like(st)])
    out = {}
    for dim, meta in DIMENSIONS.items():
        y = cols[meta['ansur']]
        beta, _, _, _ = np.linalg.lstsq(A, y, rcond=None)
        resid = y - A @ beta
        rmse = float(np.sqrt(np.mean(resid**2)))
        r = float(np.corrcoef(st, y)[0, 1])
        out[dim] = {
            'n': int(sex_n),
            'r': round(r, 4),
            'r2': round(r * r, 4),
            'rmse_mm': round(rmse, 2),
            'slope_mm_per_mm_stature': round(float(beta[0]), 5),
            'intercept_mm': round(float(beta[1]), 2),
            'mean_mm': round(float(y.mean()), 2),
            'sd_mm': round(float(y.std(ddof=1)), 2),
            'iso_class': meta['iso_class'],
            'iso_20685_1_mean_diff_mm': ISO_20685_1_TABLE4_MM.get(meta['iso_class']),
            # The honest half-width of a stature-anchored gate: +-2 residual sigma.
            'stature_anchored_halfwidth_mm': round(2.0 * rmse, 2),
        }
    return out


def _mahalanobis(cols):
    X = np.column_stack([cols[DIMENSIONS[d]['ansur']] / cols['stature'] for d in MAHALANOBIS_ORDER])
    mu = X.mean(axis=0)
    cov = np.cov(X, rowvar=False)
    inv = np.linalg.inv(cov)
    d = X - mu
    d2 = np.einsum('ij,jk,ik->i', d, inv, d)
    doc = {
        'n': int(X.shape[0]),
        'dim': int(X.shape[1]),
        'mean': [float(v) for v in mu],
        'cov_condition_number': round(float(np.linalg.cond(cov)), 3),
        'd2_empirical': {('p%g' % p): round(float(np.percentile(d2, p)), 4) for p in (50, 90, 95, 99, 99.5)},
        'chi2_reference': {
            'df': len(MAHALANOBIS_ORDER),
            'p95_value': CHI2_DF10['p95'],
            'p95_empirical_pass_rate': round(float((d2 <= CHI2_DF10['p95']).mean()), 4),
            'p99_value': CHI2_DF10['p99'],
            'p99_empirical_pass_rate': round(float((d2 <= CHI2_DF10['p99']).mean()), 4),
            'note': 'stored for comparison only; the shipped thresholds are d2_empirical',
        },
    }
    # Evidence for rejecting independent per-ratio bands as the primary gate.
    lo = np.percentile(X, 5, axis=0)
    hi = np.percentile(X, 95, axis=0)
    inside = np.all((X >= lo) & (X <= hi), axis=1)
    doc['independent_bands_check'] = {
        'method': 'fraction of the real sample inside ALL %d independent p5-p95 bands' % X.shape[1],
        'admitted_fraction': round(float(inside.mean()), 4),
        'naive_expectation_if_independent': round(0.9 ** X.shape[1], 4),
        'nominal_claim_of_each_band': 0.9,
    }
    return doc, X, mu, cov, inv, d2
