# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""blockout — The two demonstrations, the character sweep, the self test and the CLI."""

from zyg_workflows.geom.form.blockout.spectral import (
    BANDS,
    CV,
    __version__,
    decompose,
    np,
    os,
    spectral_basis,
)
from zyg_workflows.geom.form.blockout.regions import (
    region_map,
)
from zyg_workflows.geom.form.blockout.energies import (
    _rms,
    band_energies,
    delta_bands,
    render_blockout,
    report,
    smooth,
    write_json,
)
from zyg_workflows.geom.form.blockout import spectral as _spectral

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# main() takes its argparse description from __doc__.split('\n')[0]; spectral.py
# carries the original module docstring verbatim.
__doc__ = _spectral.__doc__


# ---------------------------------------------------------------------------------
# the two demonstrations
# ---------------------------------------------------------------------------------
def _gate_ab(params, lc_a, lc_b, v_a, v_b, faces):
    """Run the finished anthro gate suite on both bodies and report only what CHANGED.

    This is the load-bearing half of demonstration (a): the claim is not "the block-out
    band moved", it is "the block-out band moved and THE METRIC LAYER DID NOT NOTICE", and
    only the gate engine can say whether it noticed.
    """
    from zyg_workflows.geom import mesh_skeletons as MS
    from zyg_workflows.geom.anthro.gates.engine import run_gates
    from zyg_workflows.geom.anthro.gates.subject import Subject

    spec = MS._anthro_spec(params)
    out = {}
    for tag, lc, v in (('shipped', lc_a, v_a), ('bad', lc_b, v_b)):
        sub = Subject.from_mesh(np.asarray(v, np.float64), faces, dict(spec, local_changes=lc), 'male_' + tag)
        rows = run_gates(sub, strict=False)['gates']
        out[tag] = {r['id']: r for r in rows}
    changed, checks = [], []
    for gid, ra in out['shipped'].items():
        rb = out['bad'].get(gid)
        if rb is None:
            continue
        # run_gates rows carry 'status'; 'effective_status' is added downstream by
        # geom.anthro.report.build, which is not run here.
        sa, sb = ra.get('status'), rb.get('status')
        if sa != sb:
            changed.append(
                {
                    'gate': gid,
                    'shipped': sa,
                    'bad': sb,
                    'explain_shipped': ra.get('explain'),
                    'explain_bad': rb.get('explain'),
                }
            )
        for ca, cb in zip((ra.get('detail') or {}).get('checks') or [], (rb.get('detail') or {}).get('checks') or []):
            if ca.get('status') != cb.get('status'):
                checks.append(
                    {
                        'gate': gid,
                        'check': ca.get('id'),
                        'shipped': ca.get('status'),
                        'bad': cb.get('status'),
                        'observed_shipped': ca.get('observed'),
                        'observed_bad': cb.get('observed'),
                        'explain_bad': cb.get('explain'),
                    }
                )
    return {'status_changes': changed, 'check_changes': checks, 'counts': {t: _status_counts(out[t]) for t in out}}


def _status_counts(rows):
    c = {}
    for r in rows.values():
        k = r.get('status', 'unknown')
        c[k] = c.get(k, 0) + 1
    return c


def demo_level1_error(out_dir=None, pectoral_bad=1.5, verbose=True, with_gates=True):
    """(a) LEVEL-1 ERROR WITH CORRECT WIDTHS.

    Rebuild the male original with torso-muscle-pectoral-incr at the value the operator
    rejected as "looked like a bust", against the shipped 0.28, and put the block-out band
    beside the metric widths AND beside the verdict of the finished anthro gate suite.
    Nothing is re-issued: both meshes live in memory.
    """
    from zyg_workflows.geom import mesh_skeletons as MS
    from zyg_workflows.geom.anthro import measure as ME

    reg = MS._registry()
    p = reg['originals']['male']['params']

    def build(lc):
        v, faces, _ = MS._build_mesh(p['phenotype'], lc, p.get('bone_scales') or None)
        return MS._apply_anatomy(v, faces, p.get('anatomy_layer') or {}), faces

    good_lc = dict(p['local_changes'])
    bad_lc = dict(good_lc, **{'torso-muscle-pectoral-incr': float(pectoral_bad)})
    v_good, faces = build(good_lc)
    v_bad, _ = build(bad_lc)

    basis = spectral_basis(v_good, faces, name='male@pectoral=%.2f' % good_lc['torso-muscle-pectoral-incr'])
    rm = region_map(v_good, faces, basis['shells']['vid'])
    delta = delta_bands(basis, v_bad, v_good, rm['regions'])

    mm_good = ME.measure_mesh(
        v_good, faces, sex='male', phenotype=p['phenotype'], local_changes=good_lc, name='male_pectoral_shipped'
    )
    mm_bad = ME.measure_mesh(
        v_bad,
        faces,
        sex='male',
        phenotype=p['phenotype'],
        local_changes=bad_lc,
        name='male_pectoral_%.2f' % pectoral_bad,
    )
    widths = {}
    for key, rec in mm_good['measurements'].items():
        a = rec.get('value_mm')
        b = mm_bad['measurements'].get(key, {}).get('value_mm')
        if a is None or b is None:
            continue
        widths[key] = {
            'shipped_mm': round(float(a), 2),
            'bad_mm': round(float(b), 2),
            'delta_mm': round(float(b) - float(a), 3),
            'delta_pct': round(100.0 * (float(b) - float(a)) / float(a), 3) if a else None,
        }

    e_good = band_energies(basis, decompose(basis, v_good[basis['shells']['vid']]), rm['regions'])
    basis_bad = spectral_basis(v_bad, faces, name='male@pectoral=%.2f' % pectoral_bad)
    e_bad = band_energies(basis_bad, decompose(basis_bad, v_bad[basis_bad['shells']['vid']]), rm['regions'])

    doc = {
        'schema': 'geom.form.blockout/demo_level1/%s' % __version__,
        'what': 'male original, torso-muscle-pectoral-incr %.2f (shipped) vs %.2f '
        '(the value the operator rejected as "looked like a bust")'
        % (good_lc['torso-muscle-pectoral-incr'], pectoral_bad),
        'delta_bands': delta,
        'band_energy_shipped': e_good,
        'band_energy_bad': e_bad,
        'measurements': widths,
        'region_source': rm['source'],
        'region_notes': rm['notes'],
    }
    if with_gates:
        doc['anthro_gates'] = _gate_ab(p, good_lc, bad_lc, v_good, v_bad, faces)

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        write_json(os.path.join(out_dir, 'demo_level1_pectoral.json'), doc)
        doc['renders'] = render_blockout(v_good, faces, out_dir, basis=basis, prefix='male_pec028') + render_blockout(
            v_bad, faces, out_dir, basis=basis_bad, prefix='male_pec%03d' % round(pectoral_bad * 100)
        )
    if verbose:
        _print_level1(doc, pectoral_bad, good_lc['torso-muscle-pectoral-incr'])
    return doc


def _print_level1(doc, bad, good):
    d = doc['delta_bands']['regions']
    _zyg_log.info('\n=== (a) LEVEL-1 ERROR: pectoral %.2f -> %.2f ===' % (good, bad))
    _zyg_log.info('displacement bands, millistature (1 mstat = 1.850 mm on this body)')
    _zyg_log.info(
        '%-18s %8s %8s %8s %8s %8s %8s %7s' % ('region', 'LOW', 'MID', 'HIGH', 'MICRO', 'total', 'max mm', 'sum/tot')
    )
    for r in ('body', 'thorax', 'morph_pectoral', 'abdomen', 'head'):
        if r not in d:
            continue
        row = d[r]
        _zyg_log.info(
            '%-18s %8.4f %8.4f %8.4f %8.4f %8.4f %8.2f %7s'
            % (
                r,
                row['low']['rms_mstat'],
                row['mid']['rms_mstat'],
                row['high']['rms_mstat'],
                row['micro']['rms_mstat'],
                row['total']['rms_mstat'],
                row['max_mm'],
                row['band_sum_over_total'],
            )
        )
    _zyg_log.info('  metric measurements that moved most:')
    mv = sorted(doc['measurements'].items(), key=lambda kv: -abs(kv[1]['delta_pct'] or 0))[:8]
    for k, r in mv:
        _zyg_log.info('    %-38s %9.1f -> %9.1f mm  (%+.2f%%)' % (k, r['shipped_mm'], r['bad_mm'], r['delta_pct'] or 0))
    g = doc.get('anthro_gates')
    if g:
        _zyg_log.info(
            '  anthro gate suite (%d gates): %s -> %s'
            % (sum(g['counts']['shipped'].values()), g['counts']['shipped'], g['counts']['bad'])
        )
        if not g['status_changes'] and not g['check_changes']:
            _zyg_log.info('    NO gate and NO individual check changed status.')
        for c in g['status_changes']:
            _zyg_log.info(
                '    gate   %-26s %-6s -> %-6s | %s'
                % (c['gate'], c['shipped'], c['bad'], (c['explain_bad'] or '')[:60])
            )
        for c in g['check_changes']:
            oa, ob = c['observed_shipped'], c['observed_bad']
            num = (
                '%.6f -> %.6f' % (oa, ob)
                if isinstance(oa, (int, float)) and isinstance(ob, (int, float))
                else '%s -> %s' % (oa, ob)
            )
            _zyg_log.info(
                '    check  %-26s %-6s -> %-6s | %s [%s]' % (c['check'], c['shipped'], c['bad'], num, c['gate'])
            )


WAXY_SWEEP = (0.001, 0.002, 0.004, 0.008)


def demo_waxy(subject='cornelis', sweep=WAXY_SWEEP, out_dir=None, verbose=True, with_metrics=True):
    """(b) MISSING HIGH-FREQUENCY BAND ("waxy").

    Take a real character, Laplacian-smooth it at a sweep of diffusion lengths, and show
    the surface bands collapse while the block-out is untouched — and, with with_metrics,
    that no measurement moves enough to be visible to the metric layer either. cornelis is
    the default because he carries the abs_definition 1.7 sculpt layer, i.e. real
    high-frequency relief to lose.

    All steps are decomposed in the ORIGINAL body's basis, so the numbers are one linear
    operator applied to five position fields, not five different measurements.
    """
    from zyg_workflows.geom import mesh_skeletons as MS
    from zyg_workflows.geom.anthro import measure as ME

    reg = MS._registry()
    grp = 'derived' if subject in reg.get('derived', {}) else 'originals'
    p = reg[grp][subject]['params']
    v, faces, _ = MS._build_mesh(p['phenotype'], p.get('local_changes') or None, p.get('bone_scales') or None)
    v = MS._apply_anatomy(v, faces, p.get('anatomy_layer') or {})

    basis = spectral_basis(v, faces, name=subject)
    rm = region_map(v, faces, basis['shells']['vid'])
    vid = basis['shells']['vid']
    H = basis['stature_m']
    e0 = band_energies(basis, decompose(basis, v[vid]), rm['regions'])
    mm0 = (
        ME.measure_mesh(
            v, faces, sex=None, phenotype=p['phenotype'], local_changes=p.get('local_changes') or None, name=subject
        )
        if with_metrics
        else None
    )

    steps = []
    for sf in sweep:
        v_wax = smooth(v, faces, sf, vid=vid)
        e1 = band_energies(basis, decompose(basis, v_wax[vid]), rm['regions'])
        change = {
            r: {
                b: {
                    'before_mstat': e0[r][b]['rms_mstat'],
                    'after_mstat': e1[r][b]['rms_mstat'],
                    'pct': round(100.0 * (e1[r][b]['rms_mstat'] - e0[r][b]['rms_mstat']) / e0[r][b]['rms_mstat'], 3)
                    if e0[r][b]['rms_mstat']
                    else None,
                }
                for b in BANDS
            }
            for r in e0
        }
        moved = np.linalg.norm(v[vid] - v_wax[vid], axis=1)
        step = {
            'sigma_frac_stature': sf,
            'sigma_mm': round(sf * H * 1000, 3),
            'max_vertex_move_mm': round(float(moved.max()) * 1000, 4),
            'mean_vertex_move_mm': round(float(moved.mean()) * 1000, 4),
            'band_change': change,
        }
        if with_metrics:
            mm1 = ME.measure_mesh(
                v_wax,
                faces,
                sex=None,
                phenotype=p['phenotype'],
                local_changes=p.get('local_changes') or None,
                name='%s_waxy_%.4f' % (subject, sf),
            )
            moves = []
            for key, rec in mm0['measurements'].items():
                a = rec.get('value_mm')
                b = mm1['measurements'].get(key, {}).get('value_mm')
                if a in (None, 0) or b is None:
                    continue
                moves.append((abs(100.0 * (float(b) - float(a)) / float(a)), key))
            moves.sort(reverse=True)
            step['measurement_change'] = {
                'n_measured': len(moves),
                'n_over_1pct': int(sum(1 for m, _ in moves if m > 1.0)),
                'median_abs_pct': round(float(np.median([m for m, _ in moves])), 4) if moves else None,
                'worst': [{'name': k, 'abs_pct': round(m, 4)} for m, k in moves[:5]],
            }
        steps.append(step)

    doc = {
        'schema': 'geom.form.blockout/demo_waxy/%s' % __version__,
        'subject': subject,
        'stature_m': round(H, 4),
        'what': 'implicit Laplacian smoothing at a sweep of diffusion lengths, all '
        "decomposed in the ORIGINAL body's basis",
        'baseline_band_energy': e0,
        'steps': steps,
        'region_source': rm['source'],
        'region_notes': rm['notes'],
    }

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        write_json(os.path.join(out_dir, 'demo_waxy_%s.json' % subject), doc)
        v_wax = smooth(v, faces, sweep[-1], vid=vid)
        doc['renders'] = render_blockout(v, faces, out_dir, basis=basis, prefix='%s_real' % subject) + render_blockout(
            v_wax, faces, out_dir, basis=basis, prefix='%s_waxy' % subject
        )
    if verbose:
        _zyg_log.info('\n=== (b) WAXY: %s (stature %.3f m), whole body, millistature ===' % (subject, H))
        _zyg_log.info(
            '%-9s %8s %8s %8s %8s %8s %s'
            % (
                'sigma',
                'max mm',
                'LOW',
                'MID',
                'HIGH',
                'MICRO',
                'measurements: median |d| / n>1% / worst' if with_metrics else '',
            )
        )
        b0 = e0['body']
        _zyg_log.info(
            '%-9s %8s %8.4f %8.4f %8.4f %8.4f   (absolute mstat, not a change)'
            % (
                '0 (real)',
                '0.00',
                b0['low']['rms_mstat'],
                b0['mid']['rms_mstat'],
                b0['high']['rms_mstat'],
                b0['micro']['rms_mstat'],
            )
        )
        for s in steps:
            c = s['band_change']['body']
            mc = s.get('measurement_change')
            tail = ''
            if mc:
                w = mc['worst'][0] if mc['worst'] else {}
                tail = '%.3f%% / %d of %d / %s %.2f%%' % (
                    mc['median_abs_pct'],
                    mc['n_over_1pct'],
                    mc['n_measured'],
                    w.get('name'),
                    w.get('abs_pct', 0.0),
                )
            _zyg_log.info(
                '%-9.4f %8.2f %8s %8s %8s %8s   %s'
                % (
                    s['sigma_frac_stature'],
                    s['max_vertex_move_mm'],
                    '%+.1f%%' % c['low']['pct'],
                    '%+.1f%%' % c['mid']['pct'],
                    '%+.1f%%' % c['high']['pct'],
                    '%+.1f%%' % c['micro']['pct'],
                    tail,
                )
            )
        _zyg_log.info('  MICRO band by region at sigma=%.4f (before -> after):' % steps[-1]['sigma_frac_stature'])
        ch = steps[-1]['band_change']
        for r in ('thorax', 'abdomen', 'morph_stomach', 'morph_pectoral', 'head', 'thigh', 'arm'):
            if r not in ch:
                continue
            c = ch[r]['micro']
            _zyg_log.info(
                '    %-16s %8.4f -> %8.4f  %+6.1f%%   (LOW %+.2f%%)'
                % (r, c['before_mstat'], c['after_mstat'], c['pct'], ch[r]['low']['pct'])
            )
    return doc


# ---------------------------------------------------------------------------------
# characters
# ---------------------------------------------------------------------------------
def character_meshes(names=None):
    """(name, v, faces) for the issued characters. Rebuilt from the registry recipe —
    this module never writes to a character directory."""
    from zyg_workflows.geom import mesh_skeletons as MS

    reg = MS._registry()
    out = []
    for grp in ('originals', 'derived'):
        for nm in reg.get(grp, {}):
            if names and nm not in names:
                continue
            p = reg[grp][nm]['params']
            v, faces, _ = MS._build_mesh(p['phenotype'], p.get('local_changes') or None, p.get('bone_scales') or None)
            v = MS._apply_anatomy(v, faces, p.get('anatomy_layer') or {})
            out.append((nm, v, faces))
    return out


def run_characters(out_dir=None, names=None, render=True, verbose=True):
    docs = {}
    for nm, v, faces in character_meshes(names):
        doc = report(nm, v, faces)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            write_json(os.path.join(out_dir, 'blockout_%s.json' % nm), doc)
            if render:
                doc['renders'] = render_blockout(v, faces, out_dir, prefix=nm)
        docs[nm] = doc
    if verbose and docs:
        _zyg_log.info('\n=== band energies, whole body (millistature; 1 mstat = 0.001 stature) ===')
        _zyg_log.info(
            '%-10s %8s %8s %5s %9s %9s %9s %9s' % ('char', 'stature', 'area', 'k', 'LOW', 'MID', 'HIGH', 'MICRO')
        )
        for nm, d in docs.items():
            b = d['energies']['body']
            _zyg_log.info(
                '%-10s %7.3fm %6.3fm2 %5d %9.3f %9.4f %9.4f %9.4f'
                % (
                    nm,
                    d['stature_m'],
                    d['body_area_m2'],
                    d['ladder']['k_solved'],
                    b['low']['rms_mstat'],
                    b['mid']['rms_mstat'],
                    b['high']['rms_mstat'],
                    b['micro']['rms_mstat'],
                )
            )
        for band in ('micro', 'high'):
            _zyg_log.info('\n=== %s band by region (millistature) ===' % band.upper())
            keys = [k for k in docs[list(docs)[0]]['energies'] if k != 'body' and not k.startswith('morph_')]
            keys += [k for k in docs[list(docs)[0]]['energies'] if k.startswith('morph_')]
            _zyg_log.info('%-10s %s' % ('char', ' '.join('%9s' % k.replace('morph_', 'm.')[:9] for k in keys)))
            for nm, d in docs.items():
                _zyg_log.info('%-10s %s' % (nm, ' '.join('%9.4f' % d['energies'][k][band]['rms_mstat'] for k in keys)))
    return docs


# ---------------------------------------------------------------------------------
# self test
# ---------------------------------------------------------------------------------
def self_test(verbose=True):
    """Properties that must hold for any of the numbers above to mean anything."""
    nm, v, faces = character_meshes(['abel'])[0]
    ok = []

    b = spectral_basis(v, faces, name=nm)
    dec = decompose(b, v[b['shells']['vid']])

    r = float(np.abs(sum(dec[b] for b in BANDS) - dec['x']).max())
    ok.append(('the %d bands reconstruct the surface exactly' % len(BANDS), r < 1e-9, 'max residual %.3g m' % r))

    U, m = b['U'], b['mass']
    orth = float(np.abs(U.T @ (m[:, None] * U) - np.eye(U.shape[1])).max())
    ok.append(('eigenvectors are M-orthonormal', orth < 1e-9, 'max |UtMU - I| %.2e' % orth))

    rm = region_map(v, faces, b['shells']['vid'])

    # Scale invariance — the whole reason the units are millistature. Compared on the RAW
    # _rms values, not on the 4-decimal figures the report rounds to: rounding would hide
    # a relative error of up to 1e-3 on the small bands, which is the size of the error
    # this test exists to catch.
    s = 1.7
    b2 = spectral_basis(v * s, faces, name=nm + '@x1.7')
    rm2 = region_map(v * s, faces, b2['shells']['vid'])
    dec2 = decompose(b2, (v * s)[b2['shells']['vid']])
    worst, worst_key = 0.0, None
    for r_ in rm['regions']:
        if r_ not in rm2['regions']:
            continue
        for bd in BANDS:
            a1 = _rms(dec[bd], b['mass'], rm['regions'][r_], b['stature_m'])
            a2 = _rms(dec2[bd], b2['mass'], rm2['regions'][r_], b2['stature_m'])
            if a1 > 1e-9:
                rel = abs(a2 - a1) / a1
                if rel > worst:
                    worst, worst_key = rel, '%s/%s' % (r_, bd)
    ok.append(
        (
            'band energies are invariant under a x%.1f uniform scale' % s,
            worst < 5e-3,
            'worst %.3e at %s' % (worst, worst_key),
        )
    )

    # a change of basis must not change a delta: band(a)-band(b) == band(a-b)
    v2 = smooth(v, faces, 0.004, vid=b['shells']['vid'])
    d_direct = decompose(b, v[b['shells']['vid']] - v2[b['shells']['vid']])
    d_a = decompose(b, v[b['shells']['vid']])
    d_b = decompose(b, v2[b['shells']['vid']])
    lin = max(float(np.abs(d_a[x] - d_b[x] - d_direct[x]).max()) for x in BANDS)
    ok.append(('band projection is linear in the shared basis', lin < 1e-9, 'max %.3g m' % lin))

    n_null = int((b['lambda_norm'] < 1e-6).sum())
    ok.append(('body shell has exactly one constant mode', n_null == 1, '%d null eigenvalues' % n_null))

    sh = b['shells']
    ok.append(
        (
            'four shells found on the anny cage',
            sh['n_shells'] == 4,
            '%d shells, body %d v, excluded %s'
            % (sh['n_shells'], sh['body_vertices'], [x['vertices'] for x in sh['excluded']]),
        )
    )

    ok.append(
        (
            'delivered triangulation matches the exporter',
            np.array_equal(CV.delivered_triangles(faces), np.concatenate([faces[:, [0, 1, 2]], faces[:, [0, 2, 3]]])),
            'geom.form.curvature.delivered_triangles vs mesh_skeletons._export_glb',
        )
    )

    if verbose:
        for title, good, detail in ok:
            _zyg_log.info('%-4s %-56s %s' % ('PASS' if good else 'FAIL', title, detail))
    return all(g for _, g, _ in ok), ok


# ---------------------------------------------------------------------------------
def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('command', nargs='?', default='all', choices=('all', 'characters', 'level1', 'waxy', 'selftest'))
    ap.add_argument('--out', default=None, help='directory for PNGs and JSON')
    ap.add_argument('--no-render', action='store_true')
    ap.add_argument('--pectoral-bad', type=float, default=1.5)
    ap.add_argument('--waxy-subject', default='cornelis')
    ap.add_argument(
        '--sweep',
        default=','.join(str(x) for x in WAXY_SWEEP),
        help='comma-separated diffusion lengths in fractions of stature',
    )
    ap.add_argument('--no-gates', action='store_true', help='skip the anthro gate A/B in the level-1 demo')
    a = ap.parse_args(argv)

    if a.command in ('all', 'selftest'):
        good, _ = self_test()
        if not good:
            return 1
    if a.command in ('all', 'characters'):
        run_characters(a.out, render=not a.no_render)
    if a.command in ('all', 'level1'):
        demo_level1_error(a.out, pectoral_bad=a.pectoral_bad, with_gates=not a.no_gates)
    if a.command in ('all', 'waxy'):
        demo_waxy(a.waxy_subject, tuple(float(x) for x in a.sweep.split(',') if x.strip()), a.out)
    return 0
