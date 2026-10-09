# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""angles.py — ANGLES WITH PRINTED BANDS, and an honest record of which of them this cage
cannot carry.

measure_angles() over a whole body, scalars(), the falsification sweep and the CLI.
main() prints __doc__.splitlines()[0] as its argparse description, which is why the
first two lines above are the original module docstring's own."""

from zyg_workflows.geom.form.angles.base import (
    BANDS,
    CANON,
    HOUSE,
    LMK,
    ME,
    MS,
    SCHEMA,
    SIGN_CONVENTION,
    _band_for,
    _context,
    _frame,
    _strict,
    _verdict,
    argparse,
    json,
    np,
    os,
    sys,
    time,
)
from zyg_workflows.geom.form.angles.face import (
    face_profile,
    gonial_angle,
)
from zyg_workflows.geom.form.angles.trunk_limb import (
    carrying_angle,
    subcostal_angle,
)
from zyg_workflows.geom.form.angles.eyes import (
    canthal_tilt,
    orbital_long_axis,
)
from zyg_workflows.geom.form.angles.nose_ear import (
    ear_nose_parallelism,
    nasolabial_angle,
)


# ---------------------------------------------------------------------------------
# one call for a whole body
# ---------------------------------------------------------------------------------
def measure_angles(
    v, faces, *, phenotype=None, local_changes=None, landmarks=None, sex=None, age_years=None, probe=True
):
    """Every angle in this file on one body, resolved and unresolved alike."""
    t0 = time.time()
    ctx = _context(v, faces, landmarks, phenotype, local_changes)
    lm = ctx['lm']
    prof = face_profile(v, faces, landmarks=lm)
    out = {
        'schema': SCHEMA,
        'stature_m': ctx['S'],
        'sex': sex,
        'age_years': age_years,
        'strict': _strict(),
        'frame': {
            k: _frame(ctx['v'], ctx['faces'])[k]
            for k in ('convention', 'up_axis', 'anterior_axis', 'subject_left_axis')
        },
        'sign_convention': SIGN_CONVENTION,
        'face_profile': prof,
        'gonial_angle': gonial_angle(v, faces, landmarks=lm, phenotype=phenotype, local_changes=local_changes),
        'subcostal_angle': subcostal_angle(
            v, faces, landmarks=lm, phenotype=phenotype, local_changes=local_changes, probe=probe
        ),
        'carrying_angle': carrying_angle(v, faces, phenotype, local_changes),
        'canthal_tilt': canthal_tilt(v, faces, landmarks=lm, phenotype=phenotype, local_changes=local_changes),
        'orbital_long_axis': orbital_long_axis(
            v, faces, landmarks=lm, phenotype=phenotype, local_changes=local_changes
        ),
        'nasolabial_angle': nasolabial_angle(
            v, faces, landmarks=lm, phenotype=phenotype, local_changes=local_changes, profile=prof
        ),
        'ear_nose_parallelism': ear_nose_parallelism(
            v, faces, landmarks=lm, phenotype=phenotype, local_changes=local_changes, profile=prof
        ),
    }
    # Band verdicts are applied HERE, once, so the sex/age rule lives in one place.
    for key in BANDS:
        rec = out.get(key)
        if not isinstance(rec, dict):
            continue
        band, name = _band_for(key, sex, age_years)
        rec['band_applies'] = name if band else None
        if band is None:
            rec['band_verdict'] = 'no_applicable_band'
            rec['band_reason'] = name
        elif rec.get('value_deg') is None:
            rec['band_verdict'] = 'unresolved'
        else:
            rec['band_verdict'] = _verdict(rec['value_deg'], band[0], band[1])
            rec['band_applied'] = list(band)
    out['unresolved'] = sorted(k for k, r in out.items() if isinstance(r, dict) and r.get('resolved') is False)
    out['resolved'] = sorted(k for k, r in out.items() if isinstance(r, dict) and r.get('resolved') is True)
    out['elapsed_s'] = round(time.time() - t0, 3)
    return out


def scalars(rec):
    """The gateable scalars out of a measure_angles() record, None where unresolved."""
    g = lambda k, f: rec[k].get(f) if rec[k].get('resolved') else None
    return {
        'gonial_angle_deg': g('gonial_angle', 'value_deg'),
        'gonial_spread_deg': rec['gonial_angle'].get('operationalisation_spread_deg'),
        'condylion_menton_tilt_deg': (rec['gonial_angle'].get('condylion_menton_chord') or {}).get('sagittal_tilt_deg'),
        'subcostal_angle_deg': g('subcostal_angle', 'value_deg'),
        'carrying_angle_coronal_deg': (rec['carrying_angle'].get('operationalisations') or {}).get(
            'coronal_projection'
        ),
        'carrying_angle_decomposed_deg': (rec['carrying_angle'].get('operationalisations') or {}).get(
            'decomposed_ring_axis'
        ),
        'elbow_flexion_deg': rec['carrying_angle'].get('elbow_flexion_deg'),
        'canthal_tilt_deg': g('canthal_tilt', 'value_deg'),
        'canthal_tilt_primary_deg': rec['canthal_tilt'].get('primary_deg'),
        'canthal_ceiling_verdict': rec['canthal_tilt'].get('ceiling_verdict'),
        'canthal_sign_resolved': rec['canthal_tilt'].get('sign_resolved'),
        'orbital_long_axis_deg': g('orbital_long_axis', 'value_deg'),
        'nasolabial_angle_deg': g('nasolabial_angle', 'value_deg'),
        'nasolabial_primary_deg': rec['nasolabial_angle'].get('primary_deg'),
        'nasolabial_spread_deg': rec['nasolabial_angle'].get('operationalisation_spread_deg'),
        'ear_nose_delta_deg': g('ear_nose_parallelism', 'value_deg'),
        'ear_axis_deg': (rec['ear_nose_parallelism'].get('ear_axis_deg') or {}).get('ear-scale-vert-incr'),
        'dorsum_axis_deg': (rec['ear_nose_parallelism'].get('dorsum_axis_deg') or {}).get('nasion_pronasale_chord'),
        'ear_nose_verdict': rec['ear_nose_parallelism'].get('band_verdict'),
    }


# ---------------------------------------------------------------------------------
# FALSIFICATION: a gate that has never failed anything is not calibrated
# ---------------------------------------------------------------------------------
def falsification_sweep(values=None):
    """Drive the two RESOLVED angles across their bands on purpose, in both directions.

    The plan's calibration policy is explicit that "every gate must be shown to FAIL a
    deliberately broken control", following blockout.demo_level1_error, and a gate that has
    never fired is not calibrated. Both sweeps push a MakeHuman target well past
    geom/fit_reference.py's design cap (LOCAL_BOUND 0.8), so the distance from a shipping
    body to a verdict change is a measured number rather than a hope.

      canthal tilt        driven by the eye-corner targets, which raise the lateral canthus.
                          It starts INSIDE HeadNeck p.43's ceiling and is driven OUT of it
                          between lever 1.6 and 3.0 (measured 6.20 -> 11.42 degrees).
      ear/nose difference swept from BOTH sides, because it already fails on the stock body
                          and a gate that only ever fails is as uninformative as one that
                          only ever passes. nose-base-up moves the DORSUM half and gives a
                          clean monotone response (measured 17.7 -> 45.0 degrees over
                          -3 to +5) with the ear untouched. l/r-ear-rot-forward moves the
                          EAR half and is the more interesting row, because past about
                          +/-0.8 the two ear anchors stop agreeing and the resolution test
                          starts REFUSING — a heavily rotated ear has no single long axis,
                          and the refusal is the correct answer rather than a gap in the
                          sweep. NOTE THE FINDING IN THE NUMBERS: no single lever in the
                          256-label vocabulary brings the difference inside the 8 degree
                          tolerance anywhere in +/-5, which is six times the design cap.
    """
    rows = []
    for tag, lever, vals in (
        ('canthal_tilt', ('l-eye-corner1-up', 'r-eye-corner1-up'), values or (0.0, 0.4, 0.8, 1.6, 3.0, 5.0)),
        ('ear_nose_parallelism', ('nose-base-up',), values or (-3.0, -1.6, -0.8, 0.0, 0.8, 1.6, 3.0, 5.0)),
        (
            'ear_nose_parallelism',
            ('l-ear-rot-forward', 'r-ear-rot-forward'),
            values or (-1.6, -0.8, 0.0, 0.8, 1.6, 3.0),
        ),
    ):
        for x in vals:
            lc = {k: float(x) for k in lever}
            v, faces, _ = MS._build_mesh(LMK.REF_MALE, lc)
            v = np.asarray(v, np.float64)
            rec = measure_angles(
                v, faces, phenotype=LMK.REF_MALE, local_changes=lc, sex='male', age_years=25.0, probe=False
            )
            r = rec[tag]
            rows.append(
                {
                    'gate': tag,
                    'lever': '+'.join(lever),
                    'value': float(x),
                    'resolved': r.get('resolved'),
                    'deg': r.get('value_deg', r.get('primary_deg')),
                    'spread_deg': r.get('operationalisation_spread_deg'),
                    'band_verdict': r.get('band_verdict'),
                    'ceiling_verdict': r.get('ceiling_verdict'),
                }
            )
    return rows


# ---------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------
def _cases():
    """The anny neutral as a CONTROL, then every registered character."""
    out = [('anny-neutral', LMK.REF_MALE, None, None, 'male', ME._age_years(LMK.REF_MALE['age']))]
    reg = MS._registry()
    for grp in ('originals', 'derived'):
        for name, entry in sorted(reg.get(grp, {}).items()):
            p = entry['params']
            sex = p.get('sex') or ('female' if p['phenotype'].get('gender', 0) > 0.5 else 'male')
            out.append(
                (
                    name,
                    p['phenotype'],
                    p.get('local_changes') or None,
                    p.get('anatomy_layer') or {},
                    sex,
                    ME._age_years(p['phenotype']['age']),
                )
            )
    return out


def _build(phen, locs, anat):
    v, faces, _ = MS._build_mesh(phen, locs)
    v = MS._apply_anatomy(v, faces, anat or {})
    return np.asarray(v, np.float64), faces


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        '--characters', action='store_true', help='measure every registered character plus the anny-neutral control'
    )
    ap.add_argument('--falsify', action='store_true', help='drive the two resolved angles until they fail')
    ap.add_argument('--bands', action='store_true', help='print the printed-band table')
    ap.add_argument('--no-probe', action='store_true', help='skip the subcostal relief sweep (the slow part)')
    ap.add_argument('--json', default=None)
    a = ap.parse_args(argv)
    out = {}

    if a.bands or not (a.characters or a.falsify):
        print(
            '=== PRINTED BANDS (provenance per row; subcostal_angle is %s on %s '
            'centres, every other row is %s) ===' % (HOUSE, CANON, CANON)
        )
        for k in sorted(BANDS):
            b = BANDS[k]
            print('  %-22s %s' % (k, b['source']))
            for nm, (lo, hi) in sorted(b['bands'].items()):
                print('      %-16s %6.1f .. %6.1f deg' % (nm, lo, hi))
            print(
                '      resolution-test width: %s deg'
                % ('n/a (point value)' if b['width_deg'] is None else '%.0f' % b['width_deg'])
            )
        out['bands'] = BANDS

    if a.characters:
        rows = []
        print('\n=== ANGLES, five bodies (strict=%s) ===' % _strict())
        hdr = '%-13s %7s %5s %5s  %8s %8s %8s %8s %8s %8s' % (
            'body',
            'stature',
            'sex',
            'age',
            'canthal',
            'earNose',
            'earAx',
            'dorsAx',
            'carryCor',
            'nasolab',
        )
        print(hdr)
        for name, phen, locs, anat, sex, age in _cases():
            v, faces = _build(phen, locs, anat)
            rec = measure_angles(
                v, faces, phenotype=phen, local_changes=locs, sex=sex, age_years=age, probe=not a.no_probe
            )
            s = scalars(rec)
            rows.append(
                {
                    'name': name,
                    'sex': sex,
                    'age_years': age,
                    'stature_m': rec['stature_m'],
                    'scalars': s,
                    'resolved': rec['resolved'],
                    'unresolved': rec['unresolved'],
                }
            )
            fmt = lambda x: '   -    ' if x is None else '%8.3f' % x
            print(
                '%-13s %7.4f %5s %5.1f  %s %s %s %s %s %s'
                % (
                    name,
                    rec['stature_m'],
                    sex,
                    age,
                    fmt(s['canthal_tilt_primary_deg']),
                    fmt(s['ear_nose_delta_deg']),
                    fmt(s['ear_axis_deg']),
                    fmt(s['dorsum_axis_deg']),
                    fmt(s['carrying_angle_coronal_deg']),
                    fmt(s['nasolabial_primary_deg']),
                )
            )
            rows[-1]['record'] = rec

        print('\n--- per-angle verdicts ---')
        print('%-13s %-22s %-11s %-16s %s' % ('body', 'angle', 'resolved', 'band_verdict', 'value / reason'))
        for r in rows:
            for k in sorted(BANDS):
                rr = r['record'][k]
                val = rr.get('value_deg')
                txt = ('%.3f deg' % val) if val is not None else ((rr.get('reason') or '')[:78])
                print('%-13s %-22s %-11s %-16s %s' % (r['name'], k, rr.get('resolved'), rr.get('band_verdict'), txt))

        print('\n--- SEX DIRECTION TEST, AFS p.176 carrying angle (female > male) ---')
        f = [r for r in rows if r['sex'] == 'female']
        m = [r for r in rows if r['sex'] == 'male']
        for op in ('carrying_angle_coronal_deg', 'carrying_angle_decomposed_deg'):
            fv = [r['scalars'][op] for r in f if r['scalars'][op] is not None]
            mv = [r['scalars'][op] for r in m if r['scalars'][op] is not None]
            if fv and mv:
                print(
                    '   %-32s female mean %+7.3f (n=%d)  male mean %+7.3f (n=%d)  '
                    'direction %s'
                    % (
                        op,
                        float(np.mean(fv)),
                        len(fv),
                        float(np.mean(mv)),
                        len(mv),
                        'HOLDS' if np.mean(fv) > np.mean(mv) else 'FAILS',
                    )
                )

        print('\n--- resolution evidence (operationalisation spread vs printed band width) ---')
        for r in rows:
            for k in sorted(BANDS):
                rr = r['record'][k]
                sp = rr.get('operationalisation_spread_deg')
                if sp is None:
                    continue
                print(
                    '   %-13s %-22s spread %8.2f deg   band width %s deg   %s'
                    % (
                        r['name'],
                        k,
                        sp,
                        'n/a' if rr.get('band_width_deg') is None else '%4.0f' % rr['band_width_deg'],
                        'RESOLVED' if rr.get('resolved') else 'REFUSED',
                    )
                )
        for r in rows:
            r.pop('record', None)
        out['characters'] = rows

    if a.falsify:
        print('\n=== FALSIFICATION: drive the resolved angles until they fail ===')
        rows = falsification_sweep()
        print(
            '%-22s %-28s %6s %9s %9s %-14s %s' % ('gate', 'lever', 'value', 'deg', 'spread', 'band_verdict', 'ceiling')
        )
        for r in rows:
            print(
                '%-22s %-28s %6.2f %9s %9s %-14s %s'
                % (
                    r['gate'],
                    r['lever'],
                    r['value'],
                    '  -  ' if r['deg'] is None else '%9.3f' % r['deg'],
                    '  -  ' if r['spread_deg'] is None else '%9.3f' % r['spread_deg'],
                    r['band_verdict'],
                    r['ceiling_verdict'],
                )
            )
        out['falsification'] = rows

    if a.json:
        tmp = a.json + '.tmp'
        with open(tmp, 'w') as fh:
            json.dump(out, fh, indent=1, default=str)
        os.replace(tmp, a.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
