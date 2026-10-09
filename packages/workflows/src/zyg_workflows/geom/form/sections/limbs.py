# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sections.limbs — t5_leg_counter_curve (AFS p.215) and t5_calf_asymmetry (AFS p.216).

Moved verbatim from geom/form/sections.py; no logic, numbers or comments changed.
"""

import numpy as np

from .constants import (
    CANON,
    FAIL,
    LMK,
    PASS,
    RELIEF_NULL_FRAC,
    SRC_CALF,
    SRC_LEG,
    SRC_NULL,
    UNMEASURABLE,
)

from .primitives import (
    _frame,
    _res,
    _section,
    bone_ends,
)


# =================================================================================
# t5_leg_counter_curve — AFS p.215
# =================================================================================
def t5_leg_counter_curve(v, faces, lm, phenotype=None, local_changes=None, stature_m=None, zmin=None, stations=25):
    """The leg's section centroids must ALTERNATE lateral and medial, not be collinear.

    THE FORMULATION, and why the obvious one is vacuous. The test is run on the residual of
    the centroid track from the CHORD JOINING ITS OWN TWO ENDS. A counter-curve crosses that
    chord; a single bow never does. The tempting alternative — residual from a least-squares
    line — is worthless here, because a least-squares residual has mean zero by
    construction, so EVERY track would show sign changes and every body would pass. The
    endpoint chord has no such degeneracy and no free parameter.

    A sign change only counts if both of the residuals flanking it clear the cage's own
    relief null; below that floor the track is straight to within the tessellation's noise
    and the crossing would be quantisation, not anatomy.

    Both legs are run. They are not a second sample — they are a consistency check on the
    slicer and on the cage's mirror symmetry.
    """
    if stature_m is None or zmin is None:
        zmin, stature_m = _frame(v)
    floor = RELIEF_NULL_FRAC * stature_m
    names, heads, tails = bone_ends(phenotype or LMK.REF_MALE, local_changes)
    crotch = (lm.get('crotch') or {}).get('frac_stature')
    per_side = {}
    for side, sgn in (('l', 1.0), ('r', -1.0)):
        S = side.upper()
        rec = {'side': side}
        need = ['upperleg01.%s' % S, 'foot.%s' % S]
        if any(n not in names for n in need):
            rec.update(status=UNMEASURABLE, why='the rig has no %s' % ', '.join(n for n in need if n not in names))
            per_side[side] = rec
            continue
        hip = heads[names.index('upperleg01.%s' % S)]
        ank = heads[names.index('foot.%s' % S)]
        lo = (ank[2] - zmin) / stature_m
        hi = crotch
        if hi is None:
            rec.update(
                status=UNMEASURABLE,
                why='the crotch landmark is UNRESOLVED, so the top of the leg has no '
                'defensible height. Below the crotch a horizontal plane cuts one '
                'leg; above it, the pelvis. Refusing to guess where that is.',
            )
            per_side[side] = rec
            continue
        rec['band_frac_stature'] = [float(lo), float(hi)]
        rec['axis_anchor'] = 'rig upperleg01(head) -> foot(head), used ONLY to pick which closed loop is this leg'
        zs = np.linspace(lo, hi, stations)
        track, refused = [], []
        for fr in zs:
            z = zmin + fr * stature_m
            t = (z - hip[2]) / (ank[2] - hip[2])
            anchor = hip + t * (ank - hip)
            sec, err = _section(
                v,
                faces,
                np.array([0.0, 0.0, z]),
                np.array([0.0, 0.0, 1.0]),
                np.array([1.0, 0.0, 0.0]),
                select='nearest',
                anchor=anchor,
            )
            if sec is None:
                refused.append((float(fr), err['reason']))
                continue
            x = np.asarray(sec['loop']['pts'], np.float64)[:, 0]
            crosses = (x.min() < 0.0) if side == 'l' else (x.max() > 0.0)
            if crosses:
                # measure.py's own limb guard, verbatim in intent: a limb section that spans
                # the midsagittal plane has merged with the trunk or with its partner, and
                # its centroid is a pelvis centroid wearing a leg's name.
                refused.append(
                    (
                        float(fr),
                        'section crosses the midsagittal plane (x %.1f..%.1f mm)' % (x.min() * 1000, x.max() * 1000),
                    )
                )
                continue
            cen = np.asarray(sec['loop']['pts'], np.float64).mean(axis=0)
            track.append((float(fr), float(cen[0] * sgn), float(cen[1])))
        rec['stations_used'] = len(track)
        rec['stations_declared'] = int(stations)
        rec['stations_refused'] = refused[:6]
        if len(track) < 5:
            rec.update(
                status=UNMEASURABLE,
                why='only %d of %d stations produced a clean single-leg section' % (len(track), stations),
            )
            per_side[side] = rec
            continue
        fr = np.array([t[0] for t in track])
        lateral = np.array([t[1] for t in track])
        chord = np.interp(fr, [fr[0], fr[-1]], [lateral[0], lateral[-1]])
        resid = lateral - chord
        big = np.abs(resid) > floor
        sig = np.sign(resid[big])
        changes = int((np.diff(sig) != 0).sum()) if len(sig) > 1 else 0
        rec.update(
            residual_mm=[round(float(x) * 1000, 2) for x in resid],
            frac_stature=[round(float(x), 4) for x in fr],
            max_abs_residual_mm=float(np.abs(resid).max()) * 1000,
            floor_mm=floor * 1000,
            stations_above_floor=int(big.sum()),
            sign_changes=changes,
            first_significant_is_lateral=(bool(sig[0] > 0) if len(sig) else None),
            last_significant_is_medial=(bool(sig[-1] < 0) if len(sig) else None),
            status=PASS if changes >= 1 else FAIL,
        )
        per_side[side] = rec

    got = [r for r in per_side.values() if r.get('status') in (PASS, FAIL)]
    if not got:
        st = UNMEASURABLE
        why = '; '.join(r.get('why', '') for r in per_side.values())
    else:
        bad = [r['side'] for r in got if r['status'] == FAIL]
        st = FAIL if bad else PASS
        why = (
            (
                'the centroid track never crosses its own endpoint chord on %s: the residual '
                'is single-signed, i.e. one bow, not a counter-curve (max |residual| %s mm '
                'against a %.2f mm floor)'
                % (
                    ', '.join(bad),
                    '/'.join('%.1f' % r['max_abs_residual_mm'] for r in got if r['status'] == FAIL),
                    floor * 1000,
                )
            )
            if bad
            else 'the centroid track crosses its endpoint chord on both legs'
        )

    sym = None
    if len(got) == 2 and all('residual_mm' in r for r in got):
        a = np.array(per_side['l']['residual_mm'])
        b = np.array(per_side['r']['residual_mm'])
        if a.shape == b.shape:
            sym = float(np.abs(a - b).max())

    return {
        'gate': 't5_leg_counter_curve',
        'source': SRC_LEG,
        'provenance': CANON,
        'sides': per_side,
        'status': st,
        'claims': {
            'counter_curve': _res(
                st,
                "the leg's section centroids alternate lateral and medial down the limb; they are not collinear",
                SRC_LEG + ' + ' + SRC_NULL,
                CANON,
                why,
                left_right_max_residual_difference_mm=sym,
                floor_mm=floor * 1000,
                why_endpoint_chord=(
                    'a least-squares line would give every track sign '
                    'changes by construction and the test would be '
                    'vacuous; the endpoint chord asks the real question, '
                    'does the track cross the line joining its own ends'
                ),
            )
        },
    }


# =================================================================================
# t5_calf_asymmetry — AFS p.216
# =================================================================================
def t5_calf_asymmetry(v, faces, phenotype=None, local_changes=None, stature_m=None, zmin=None, stations=33):
    """The medial gastrocnemius apex must be BOTH lower AND larger than the lateral.

    TWO DIRECTION TESTS, no thresholds. The only quantities that need a floor are the two
    DIFFERENCES, and both floors are structural rather than chosen: a height difference must
    exceed one scan step to be resolved (an argmax cannot see finer than its own grid), and
    an amplitude difference must exceed the cage's relief null.

    WHAT 'AMPLITUDE' MEANS HERE, and why the obvious reading is wrong. The naive measure is
    the half-width from the shank axis to the medial and lateral surfaces. That is
    contaminated twice over: the rig's shank axis is not centred in the limb (measured on
    the neutral it sits about 4.5 mm medial of the section centre, so the lateral half-width
    starts ahead by that much at every station), and the limb tapers from knee to ankle so
    the half-width carries the taper as well as the muscle. Both are removed by the same
    endpoint-chord trick the counter-curve uses: the BULGE is each side's half-width minus
    the straight line joining its own first and last station. What is left is the muscle
    belly. Both readings are reported.
    """
    if stature_m is None or zmin is None:
        zmin, stature_m = _frame(v)
    floor = RELIEF_NULL_FRAC * stature_m
    names, heads, tails = bone_ends(phenotype or LMK.REF_MALE, local_changes)
    per_side = {}
    for side, sgn in (('l', 1.0), ('r', -1.0)):
        S = side.upper()
        rec = {'side': side}
        need = ['lowerleg01.%s' % S, 'foot.%s' % S]
        if any(n not in names for n in need):
            rec.update(status=UNMEASURABLE, why='the rig has no %s' % ', '.join(n for n in need if n not in names))
            per_side[side] = rec
            continue
        knee = heads[names.index('lowerleg01.%s' % S)]
        ank = heads[names.index('foot.%s' % S)]
        lo = (ank[2] - zmin) / stature_m
        hi = (knee[2] - zmin) / stature_m
        rec['band_frac_stature'] = [float(lo), float(hi)]
        rec['axis_anchor'] = 'rig lowerleg01(head) -> foot(head): the shank segment'
        zs = np.linspace(lo, hi, stations)
        rows = []
        for fr in zs:
            z = zmin + fr * stature_m
            t = (z - knee[2]) / (ank[2] - knee[2])
            anchor = knee + t * (ank - knee)
            sec, err = _section(
                v,
                faces,
                np.array([0.0, 0.0, z]),
                np.array([0.0, 0.0, 1.0]),
                np.array([1.0, 0.0, 0.0]),
                select='nearest',
                anchor=anchor,
            )
            if sec is None:
                continue
            x = np.asarray(sec['loop']['pts'], np.float64)[:, 0]
            if (x.min() < 0.0) if side == 'l' else (x.max() > 0.0):
                continue
            sx = (x - anchor[0]) * sgn
            rows.append((float(fr), float(sx.max()), float(-sx.min())))
        rec['stations_used'] = len(rows)
        rec['stations_declared'] = int(stations)
        if len(rows) < 5:
            rec.update(
                status=UNMEASURABLE,
                why='only %d of %d shank stations produced a clean single-leg section' % (len(rows), stations),
            )
            per_side[side] = rec
            continue
        fr = np.array([r[0] for r in rows])
        lat = np.array([r[1] for r in rows])
        med = np.array([r[2] for r in rows])
        step = float(fr[1] - fr[0]) * stature_m
        bl = lat - np.interp(fr, [fr[0], fr[-1]], [lat[0], lat[-1]])
        bm = med - np.interp(fr, [fr[0], fr[-1]], [med[0], med[-1]])
        il, im = int(np.argmax(bl)), int(np.argmax(bm))
        dz = float(fr[il] - fr[im]) * stature_m  # >0 => medial apex is lower
        da = float(bm[im] - bl[il])  # >0 => medial bulge is larger
        rec.update(
            medial_apex_frac_stature=float(fr[im]),
            lateral_apex_frac_stature=float(fr[il]),
            medial_bulge_mm=float(bm[im]) * 1000,
            lateral_bulge_mm=float(bl[il]) * 1000,
            medial_halfwidth_apex_frac=float(fr[int(np.argmax(med))]),
            lateral_halfwidth_apex_frac=float(fr[int(np.argmax(lat))]),
            medial_halfwidth_max_mm=float(med.max()) * 1000,
            lateral_halfwidth_max_mm=float(lat.max()) * 1000,
            apex_height_difference_mm=dz * 1000,
            scan_step_mm=step * 1000,
            bulge_difference_mm=da * 1000,
            floor_mm=floor * 1000,
            medial_lower=(None if abs(dz) <= step else bool(dz > 0)),
            medial_larger=(None if abs(da) <= floor else bool(da > 0)),
        )
        # A CONJUNCTION, resolved conjunct by conjunct. "Lower AND larger" is false the
        # moment either half is measurably false, whatever the other half does — so an
        # unresolved conjunct beside a false one still gives FAIL, and only an unresolved
        # conjunct with no false one beside it gives UNMEASURABLE. Collapsing the pair to
        # UNMEASURABLE whenever either half is unresolved would have hidden four real
        # failures behind one 12 mm scan step.
        parts = [rec['medial_lower'], rec['medial_larger']]
        if False in parts:
            rec['status'] = FAIL
        elif None in parts:
            rec['status'] = UNMEASURABLE
            rec['why'] = (
                'a conjunct is inside the resolution of the measurement: apex '
                'height difference %.2f mm against a %.2f mm scan step, bulge '
                'difference %.2f mm against a %.2f mm relief null' % (dz * 1000, step * 1000, da * 1000, floor * 1000)
            )
        else:
            rec['status'] = PASS
        per_side[side] = rec

    got = [r for r in per_side.values() if r.get('status') in (PASS, FAIL)]
    if not got:
        st, why = UNMEASURABLE, '; '.join(r.get('why', '') for r in per_side.values())
    else:
        bad = [r for r in got if r['status'] == FAIL]
        st = FAIL if bad else PASS

        def _w(flag, yes, no):
            return 'UNRESOLVED' if flag is None else (yes if flag else no)

        why = (
            '; '.join(
                '%s: medial apex is %s (%+.1f mm) and %s (%+.1f mm)'
                % (
                    r['side'],
                    _w(r['medial_lower'], 'LOWER', 'HIGHER'),
                    r['apex_height_difference_mm'],
                    _w(r['medial_larger'], 'LARGER', 'SMALLER'),
                    r['bulge_difference_mm'],
                )
                for r in bad
            )
            if bad
            else 'the medial apex is both lower and larger on both legs'
        )
    return {
        'gate': 't5_calf_asymmetry',
        'source': SRC_CALF,
        'provenance': CANON,
        'sides': per_side,
        'status': st,
        'claims': {
            'medial_lower_and_larger': _res(
                st,
                'the medial gastrocnemius apex is both lower and larger than the lateral',
                SRC_CALF + ' + ' + SRC_NULL,
                CANON,
                why,
                amplitude_reading='endpoint-chord bulge (the shank axis offset and the '
                'limb taper are removed); raw half-widths reported too',
            )
        },
    }
