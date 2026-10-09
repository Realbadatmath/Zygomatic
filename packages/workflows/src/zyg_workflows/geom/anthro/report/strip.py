# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro.report — the percentile strip.

Moved out of the old single-file report.py (lines 1521-1774).
"""

from zyg_workflows.geom.anthro.report.constants import _DEFAULT_WIDTH, _STRIP_WIDTH
from zyg_workflows.geom.anthro.report.textfmt import _fmt_num, _fmt_pct, _num, _wrap


# ---------------------------------------------------------------------------------
# the percentile strip
# ---------------------------------------------------------------------------------
def _strip(pct, lo_pct, hi_pct, width=_STRIP_WIDTH):
    """An ASCII position of one value inside its reference band, drawn in PERCENTILE
    space so that every ratio's strip is on the same axis regardless of its units.

    '.' outside the band, '-' inside it, '[' ']' the band edges, ':' the median tick,
    '#' the measured value. '<' or '>' replace the marker when the value is off the end of
    the reference sample entirely, which is a true empirical statement (no member of the
    sample was more extreme) and not a clamp.
    """
    cells = ['.'] * width

    def idx(p):
        if p is None:
            return None
        p = min(100.0, max(0.0, float(p)))
        return int(round(p / 100.0 * (width - 1)))

    ilo, ihi = idx(lo_pct), idx(hi_pct)
    if ilo is not None and ihi is not None and ihi >= ilo:
        for i in range(ilo, ihi + 1):
            cells[i] = '-'
    i50 = idx(50.0)
    if cells[i50] in '.-':
        cells[i50] = ':'
    if ilo is not None:
        cells[ilo] = '['
    if ihi is not None:
        cells[ihi] = ']'
    ip = idx(pct)
    if ip is not None:
        if pct <= 0.0:
            cells[0] = '<'
        elif pct >= 100.0:
            cells[width - 1] = '>'
        elif ip == ilo:
            # One cell is ~3 percentile points wide, so a body within a hair of the band
            # edge lands on the edge itself. Overwriting the bracket with '#' would erase
            # the band from the picture; '{' and '}' keep both facts in the one cell.
            cells[ip] = '{'
        elif ip == ihi:
            cells[ip] = '}'
        else:
            cells[ip] = '#'
    return ''.join(cells)


def ratio_rows(ratios, sex, ancestry=None, width='p5p95', stature_m=None, ref=None, gates_by_ratio=None):
    """One strip row per measured ratio: value, percentile, band, and the signed distance
    to the nearer band edge in the ratio's own units AND in millimetres of this subject.

    `ratios` is measure_mesh()['ratios'] (values may be floats or {'value': ...} records).
    Ratios the reference pack does not carry are NOT dropped — they are rendered with
    'no reference band', because a measurement that nothing checks is a thing the reader
    needs to know exists.

    The reference module is imported lazily so that a caller who only wants a text dump
    never pays for the pack.
    """
    if ref is None:
        try:
            from zyg_workflows.geom.anthro.reference import reference as _reference

            ref = _reference()
        except Exception as e:  # noqa: BLE001
            ref = None
            ref_error = str(e)
        else:
            ref_error = None
    else:
        ref_error = None

    known = set(ref.ratios()) if ref is not None else set()
    rows = []
    for name in sorted(ratios or {}):
        rec = ratios[name]
        if isinstance(rec, dict):
            val = _num(rec.get('value'))
            units = rec.get('units')
            comparable = rec.get('survey_comparable', True)
            why_not = rec.get('survey_not_comparable_because')
            note = rec.get('note')
            convention = rec.get('convention')
        else:
            val = _num(rec)
            units = None
            comparable, why_not, note, convention = True, None, None, None

        row = {
            'ratio': name,
            'value': val,
            'units': units,
            'percentile': None,
            'band_lo': None,
            'band_hi': None,
            'band_lo_pct': None,
            'band_hi_pct': None,
            'band_width': width,
            'inside': None,
            'delta': None,
            'delta_mm_of_stature': None,
            'source': None,
            'population': None,
            'ancestry_declared': None,
            'survey_comparable': bool(comparable),
            'survey_not_comparable_because': why_not,
            'note': note,
            'convention': convention,
            'status': None,
            'flags': [],
        }

        if val is None:
            row['status'] = 'no-value'
            row['flags'].append('novalue')
            rows.append(row)
            continue
        if ref is None:
            row['status'] = 'no-reference'
            row['note_render'] = 'reference pack unavailable: %s' % ref_error
            row['flags'].append('nopack')
            rows.append(row)
            continue
        if name not in known:
            row['status'] = 'no-band'
            row['flags'].append('noband')
            rows.append(row)
            continue

        try:
            b = ref.band(name, sex, ancestry, width=width)
            pct = ref.percentile(name, val, sex, ancestry)
            lo_pct = ref.percentile(name, b['lo'], sex, ancestry)
            hi_pct = ref.percentile(name, b['hi'], sex, ancestry)
        except Exception as e:  # noqa: BLE001
            row['status'] = 'band-error'
            row['note_render'] = str(e)
            row['flags'].append('err')
            rows.append(row)
            continue

        row.update(
            {
                'percentile': pct,
                'band_lo': b['lo'],
                'band_hi': b['hi'],
                'band_lo_pct': lo_pct,
                'band_hi_pct': hi_pct,
                'source': b['source'],
                'population': b['population'],
                'ancestry_declared': b['ancestry_declared'],
                'mean': b['mean'],
                'sd': b['sd'],
                'n': b['n'],
                'definition': b.get('definition'),
                'iso_class': b.get('iso_class'),
            }
        )
        inside = b['lo'] <= val <= b['hi']
        row['inside'] = inside
        if val < b['lo']:
            row['delta'] = val - b['lo']
        elif val > b['hi']:
            row['delta'] = val - b['hi']
        else:
            row['delta'] = 0.0
        if stature_m and name.endswith('_over_stature') and row['delta'] is not None:
            row['delta_mm_of_stature'] = row['delta'] * stature_m * 1000.0
        if b['sd']:
            row['z'] = (val - b['mean']) / b['sd']
        row['status'] = 'inside' if inside else 'outside'
        if not comparable:
            row['flags'].append('conv')
        if not b['ancestry_declared']:
            row['flags'].append('pooled')
        if gates_by_ratio and name in gates_by_ratio:
            row['gate_id'] = gates_by_ratio[name]
        rows.append(row)
    return rows


def render_percentile_strip(rows, width=_DEFAULT_WIDTH, caveat=None):
    """The strip table. Ratios with a band are drawn first, then the ones nothing checks,
    because 'measured but ungated' is a different fact from 'measured and in band'."""
    out = []
    out.append('PERCENTILE STRIP — every measured ratio against the reference distribution')
    out.append('  the strip is PERCENTILE space 0..100; [ ] are the band edges, : is the median, # is this body,')
    out.append('  { or } is this body sitting on a band edge, < or > is outside the sampled range entirely')
    if caveat:
        out.append('')
        out.extend(_wrap('!! %s' % caveat, width, 2))
    out.append('')
    out.append(
        '  %-44s %9s %6s %-*s %11s %10s %s'
        % ('ratio', 'value', 'pct', _STRIP_WIDTH, 'p0' + ' ' * (_STRIP_WIDTH - 6) + 'p100', 'delta', 'mm@stat', 'flags')
    )
    banded = [r for r in rows if r.get('percentile') is not None]
    other = [r for r in rows if r.get('percentile') is None]
    for r in banded:
        d = r.get('delta')
        dtxt = '-' if d is None else ('in band' if d == 0.0 else '%+.4f' % d)
        dmm = r.get('delta_mm_of_stature')
        mtxt = '-' if dmm is None else ('%+.1f' % dmm if dmm else '0.0')
        out.append(
            '  %-44s %9s %6s %s %11s %10s %s'
            % (
                r['ratio'][:44],
                _fmt_num(r['value']),
                _fmt_pct(r['percentile']),
                _strip(r['percentile'], r.get('band_lo_pct'), r.get('band_hi_pct')),
                dtxt,
                mtxt,
                ','.join(r.get('flags') or []) or '-',
            )
        )
    if other:
        out.append('')
        out.append('  measured but NOT checked against any band:')
        for r in other:
            out.append(
                '    %-44s %9s   %s%s'
                % (
                    r['ratio'][:44],
                    _fmt_num(r['value']),
                    r.get('status'),
                    (' — ' + str(r['note_render'])[:60]) if r.get('note_render') else '',
                )
            )
    footnotes = []
    if any('conv' in (r.get('flags') or []) for r in banded):
        footnotes.append(
            "conv   = this mesh measurement is NOT on the survey's "
            'convention; its percentile compares two different definitions '
            'and is indicative only'
        )
    if any('pooled' in (r.get('flags') or []) for r in banded):
        footnotes.append(
            'pooled = no ancestry declared, so the band is the pooled US '
            'Army mixture. Ancestry is the largest proportion effect in the '
            'data (crotch/stature spread .024 = 44 mm on a 1.85 m man)'
        )
    if footnotes:
        out.append('')
        for f in footnotes:
            out.extend(_wrap(f, width, 2))
    conv = [r for r in banded if 'conv' in (r.get('flags') or [])]
    for r in conv:
        out.extend(
            _wrap('%s: %s' % (r['ratio'], r.get('survey_not_comparable_because') or 'convention mismatch'), width, 4)
        )
    return '\n'.join(out)
