# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro.report — the measurement table, the reference lookup and the artifact.

Moved out of the old single-file report.py (lines 3596-3817).
"""

import json
import os
from zyg_workflows.geom.anthro.report.constants import ROOT, SCHEMA, UNKNOWN, _DEFAULT_WIDTH, _zyg_log
from zyg_workflows.geom.anthro.report.textfmt import _fmt_num, _is_num, _jsonable, _wrap


# ---------------------------------------------------------------------------------
# the measurement table and the reference lookup
# ---------------------------------------------------------------------------------
def render_measurements(measurement, width=_DEFAULT_WIDTH):
    """Every measurement with the CONVENTION that produced it, on the same row.

    The convention column is not decoration. "waist" has no agreed site — the WHO
    rib-iliac midpoint and the NIH iliac crest differ by up to 10.1 cm in women — and
    "shoulder width" is three different measurements. A table of numbers without the
    landmark and the convention beside each one is not reproducible, and definition traps
    cause more error in practice than any tolerance does.
    """
    M = (measurement or {}).get('measurements') or {}
    meta = (measurement or {}).get('meta') or {}
    out = ['MEASUREMENTS — %s' % (meta.get('name') or UNKNOWN)]
    out.append(
        '  stature %s   pose %s   %s'
        % (
            ('%.4f m' % meta['stature_m']) if meta.get('stature_m') else UNKNOWN,
            meta.get('pose', UNKNOWN),
            meta.get('handedness', ''),
        )
    )
    out.append(
        '  values are MILLIMETRES unless a unit is printed; frac_H is the value as '
        "a fraction of this body's own stature"
    )
    out.append('')
    out.append(
        '  %-42s %12s %8s %-19s %-10s %s' % ('measurement', 'value', 'frac_H', 'iso class', 'provenance', 'flags')
    )
    ok, refused, unmeasurable = [], [], []
    for k in sorted(M):
        r = M[k] if isinstance(M[k], dict) else {}
        prov = r.get('provenance')
        if prov == 'UNMEASURABLE':
            unmeasurable.append(k)
        elif prov == 'REFUSED':
            refused.append((k, r.get('reason')))
        else:
            ok.append((k, r))
    for k, r in ok:
        val = r.get('value_mm')
        units = 'mm'
        if val is None:
            val, units = r.get('value'), r.get('units') or ''
        marks = []
        if r.get('survey_comparable') is False:
            marks.append('NOT-SURVEY-COMPARABLE')
        if r.get('endpoint_warning'):
            marks.append('BAND-EDGE')
        if r.get('arms_included'):
            marks.append('ARMS-INCLUDED')
        out.append(
            (
                '  %-42s %12s %8s %-19s %-10s %s'
                % (
                    k[:42],
                    _fmt_num(val, units if units != 'mm' else None),
                    ('%.4f' % r['frac_stature']) if _is_num(r.get('frac_stature')) else '-',
                    (r.get('iso_class') or '-')[:19],
                    (r.get('provenance') or '-')[:10],
                    ' '.join(marks),
                )
            ).rstrip()
        )
        # Landmark and convention go on their own lines rather than in a column: a
        # truncated landmark name is a different measurement, not a shorter one.
        if r.get('landmark'):
            out.extend(_wrap('landmark: %s' % r['landmark'], width, 6))
        conv = r.get('convention')
        if conv:
            out.extend(_wrap('convention: %s' % conv, width, 6))
        for extra_key in ('survey_not_comparable_because', 'endpoint_warning', 'band_adjustment'):
            if r.get(extra_key):
                out.extend(_wrap('%s: %s' % (extra_key, r[extra_key]), width, 6))
    if refused:
        out.append('')
        out.append('  REFUSED — measurable in principle, not on this mesh:')
        for k, why in refused:
            out.extend(_wrap('%s — %s' % (k, why), width, 4))
    if unmeasurable:
        out.append('')
        out.extend(_wrap('UNMEASURABLE ON THIS CAGE: %s' % ', '.join(unmeasurable), width, 2))
    out.append('')
    out.append('  CONVENTIONS IN FORCE')
    for k in (
        'girth_convention',
        'limb_girth_convention',
        'arm_exclusion',
        'coco_source',
        'vertex_scope',
        'band_floors',
        'axis_convention',
        'ground_plane',
        'units',
        'iso_caveat',
    ):
        if meta.get(k):
            out.extend(_wrap('%s: %s' % (k, meta[k]), width, 4))
    also = meta.get('girth_conventions_also_reported') or {}
    for k in sorted(also):
        out.extend(_wrap('%s: %s' % (k, also[k]), width, 4))
    return '\n'.join(out)


def render_reference(ratio, sex, ancestry=None, width_label='p5p95', ref=None, width=_DEFAULT_WIDTH):
    """The band for one ratio, with everything needed to decide whether it may be used:
    the population it came from, its n, and — for the dimension behind it — whether
    stature predicts it well enough to be gated tightly at all."""
    if ref is None:
        from zyg_workflows.geom.anthro.reference import reference as _reference

        ref = _reference()
    b = ref.band(ratio, sex, ancestry, width=width_label)
    out = ['REFERENCE BAND — %s' % ratio]
    out.append('')
    out.append('  %-22s %s' % ('band (%s)' % b['width'], '%.6f .. %.6f' % (b['lo'], b['hi'])))
    out.append('  %-22s %.6f' % ('mean', b['mean']))
    out.append('  %-22s %.6f' % ('sd', b['sd']))
    out.append('  %-22s %d' % ('n', b['n']))
    out.append('  %-22s %s' % ('units', b['units']))
    out.append('  %-22s %s' % ('iso class', b['iso_class'] or '-'))
    out.append('  %-22s %s' % ('sex', b['sex']))
    out.append('  %-22s %s%s' % ('ancestry', b['ancestry'], '' if b['ancestry_declared'] else '  (NOT DECLARED)'))
    out.append('')
    out.extend(_wrap('definition: %s' % b['definition'], width, 2))
    out.append('')
    out.extend(_wrap('source: %s' % b['source'], width, 2))
    out.extend(_wrap('population: %s' % b['population'], width, 2))
    out.extend(_wrap('licence: %s' % b['licence'], width, 2))
    if b.get('note'):
        out.append('')
        out.extend(_wrap('NOTE: %s' % b['note'], width, 2))
    out.append('')
    out.append('  bands available for this ratio:')
    for w in ('p1p99', 'p5p95', 'p25p75', 'sd1', 'sd2', 'sd3'):
        try:
            bb = ref.band(ratio, sex, ancestry, width=w)
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('no %s band for this ratio: %s', w, _exc)
            continue
        out.append('    %-8s %.6f .. %.6f' % (w, bb['lo'], bb['hi']))
    dim = ratio[: -len('_over_stature')] if ratio.endswith('_over_stature') else ratio
    try:
        p = ref.predictability(dim)
    except Exception:  # noqa: BLE001
        p = None
    if p:
        out.append('')
        out.append('  STATURE PREDICTABILITY of %s' % dim)
        out.append(
            '    r = %.3f   rmse = %.1f mm   policy = %s'
            % (p.get('r', float('nan')), p.get('rmse_mm', float('nan')), p.get('policy', UNKNOWN))
        )
        for k in ('rule', 'consequence'):
            if p.get(k):
                out.extend(_wrap('%s: %s' % (k, p[k]), width, 4))
        if p.get('iso_20685_1_mean_diff_mm') is not None:
            out.extend(
                _wrap(
                    'ISO 20685-1 Table 4 for class %r: %s mm. %s'
                    % (p.get('iso_class'), p['iso_20685_1_mean_diff_mm'], p.get('iso_caveat', '')),
                    width,
                    4,
                )
            )
    if ratio in ref.doc['mahalanobis']['order']:
        out.append('')
        out.extend(
            _wrap(
                'this ratio is a component of the JOINT mahalanobis vector. A '
                'marginal band on it says nothing about whether it can co-occur '
                'with the other nine on the same body; ten independent 90% '
                'bands admit at most 0.9^10 = 35% of real people. Use the joint '
                'gate as the primary plausibility check.',
                width,
                2,
            )
        )
    return '\n'.join(out)


# ---------------------------------------------------------------------------------
# the artifact
# ---------------------------------------------------------------------------------
def report_path(name, root=ROOT):
    safe = ''.join(ch if (ch.isalnum() or ch in '-_.') else '_' for ch in str(name))
    if not safe or safe in ('.', '..'):
        raise ValueError('refusing to write a report for character name %r' % name)
    return os.path.join(root, safe + '.json')


def write_json(doc, path):
    """Atomic: a reader either sees the whole previous report or the whole new one, never
    a half-written file. fsync before the rename, and on the directory after it, because a
    rename that is not durable is not atomic across a power loss."""
    path = os.path.abspath(path)
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    tmp = '%s.tmp.%d' % (path, os.getpid())
    with open(tmp, 'w') as f:
        json.dump(doc, f, indent=1, sort_keys=True, default=_jsonable)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fd = os.open(d, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return path


def read_json(path):
    with open(path) as f:
        doc = json.load(f)
    if doc.get('schema') != SCHEMA:
        raise ValueError('report at %s has schema %r, this module speaks %r' % (path, doc.get('schema'), SCHEMA))
    return doc
