# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""relational/cli.py — the swayback validation sweeps and the CLI.

Moved verbatim out of relational.py (lines 1644-1863).
"""

from zyg_workflows.geom.form.relational.constants import (
    LMK,
    MS,
    argparse,
    json,
    np,
    os,
    sys,
    validate_registry,
)
from zyg_workflows.geom.form.relational.body import (
    gluteal_vs_trochanteric,
    measure_relations,
    scalars,
)
from zyg_workflows.geom.form.relational.reference import (
    build_reference,
    form_reference,
)
from zyg_workflows.geom.form.relational.gate_defs import (
    calibrate,
    gate_records,
)
from zyg_workflows.geom.form.relational import constants as _constants

# main() builds its argparse description from __doc__.splitlines()[0]; constants.py
# carries relational.py's docstring verbatim, so read it from there instead of copying it.
__doc__ = _constants.__doc__

# ---------------------------------------------------------------------------------
# VALIDATION: the swayback the detector exists for
# ---------------------------------------------------------------------------------
# The recipe that produced the 2026-08-05 swayback, recovered from the working directory of
# that day (scratchpad/proportions_female.json, 05:17). It is the SECOND-ISSUE female:
# hand-calibrated against the scalar slice-width targets in blender_targets.json, which is
# the method geom/fit_reference.py's docstring blames by name — "any scalar the objective
# does not measure becomes a dumping ground for solver error (the 2026-08-05 swayback)".
# Two levers sit at -1.6, twice the design cap that fit_reference.py introduced in response
# (LOCAL_BOUND = 0.8, "the swayback came from -1.6").
REJECTED_FEMALE_LOCALS = {
    'measure-bust-circ-incr': 1.5,
    'breast-point-incr': 0.25,
    'breast-volume-vert-up': 0.1,
    'measure-shoulder-dist-incr': -1.6,
    'measure-waist-circ-incr': -1.6,
    'measure-hips-circ-incr': -0.2836,
    'measure-neck-circ-incr': 0.65,
    'neck-scale-depth-incr': 0.4883,
    'head-scale-horiz-incr': 0.27,
    'head-scale-vert-incr': 0.0,
    'head-scale-depth-incr': 0.27,
    'measure-upperleg-height-incr': -0.5435,
    'measure-lowerleg-height-incr': -0.5435,
}
# The macro phenotype it was applied to. The height axis is EXACT — fit_reference.py
# FIXED_PHEN records female height 0.680664 as "the FIT-TIME OPERATING POINT (the
# second-issue axes the recorded fits ran at — kept so those runs reproduce exactly)". The
# other four macros are the ORIGINAL_SPEC midpoint 0.5, which is what the originals carried
# before the third-issue chamfer fit produced ORIGINAL_PHEN; that part is a RECONSTRUCTION,
# not a record, and it is why swayback_sweep() reports the one-morph response curve beside
# it — the curve stands whatever the macros were.
REJECTED_FEMALE_PHEN = {'gender': 1.0, 'age': 0.5, 'muscle': 0.5, 'weight': 0.5, 'height': 0.680664, 'proportions': 0.5}
SWAY_LEVER = 'measure-waist-circ-incr'


def swayback_sweep(values=None, lever=SWAY_LEVER):
    """Rebuild the rejected female and sweep the lever that produced it.

    Returns the response curve of every relational scalar against the morph value, plus the
    exact rejected recipe as its own row. The sweep is the load-bearing half: the macro
    reconstruction above could be wrong and the curve would still say what the lever does.
    """
    vals = list(values if values is not None else np.round(np.arange(-1.6, 0.81, 0.2), 2))
    rows = []
    for tag, lc in [('REJECTED (exact recipe)', dict(REJECTED_FEMALE_LOCALS))] + [
        ('%s=%+0.1f' % (lever, x), dict(REJECTED_FEMALE_LOCALS, **{lever: x})) for x in vals
    ]:
        v, faces, _ = MS._build_mesh(REJECTED_FEMALE_PHEN, lc)
        rel = measure_relations(np.asarray(v, np.float64), faces, phenotype=REJECTED_FEMALE_PHEN, local_changes=lc)
        rows.append(
            {
                'tag': tag,
                'lever': lever,
                'lever_value': lc[lever],
                'stature_m': rel['stature_m'],
                'scalars': scalars(rel),
            }
        )
    return rows


def falsification_sweep(values=(0.0, 0.8, 1.6, 2.0, 3.0, 4.0), lever='buttocks-volume-incr'):
    """How far a body has to be pushed before the gluteal/trochanteric gate fires.

    A gate that never fails on anything anyone builds is worth shipping only if the
    distance to failure is measured. This is that measurement.
    """
    rows = []
    for x in values:
        v, faces, _ = MS._build_mesh(LMK.REF_MALE, {lever: float(x)})
        r = gluteal_vs_trochanteric(
            np.asarray(v, np.float64), faces, phenotype=LMK.REF_MALE, local_changes={lever: float(x)}
        )
        rows.append(
            {
                'lever': lever,
                'value': float(x),
                'resolved': r.get('resolved', False),
                'reason': r.get('reason'),
                'margin_mm': r.get('margin_mm'),
                'separation_frac_stature': r.get('separation_frac_stature'),
                'gluteal_width_mm': r.get('gluteal_width_mm'),
                'trochanteric_width_mm': r.get('trochanteric_width_mm'),
            }
        )
    return rows


# ---------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------
def _characters():
    reg = MS._registry()
    for grp in ('originals', 'derived'):
        for name, entry in sorted(reg.get(grp, {}).items()):
            yield grp, name, entry['params']


def _build_character(params):
    v, faces, _ = MS._build_mesh(
        params['phenotype'], params.get('local_changes') or None, params.get('bone_scales') or None
    )
    v = MS._apply_anatomy(v, faces, params.get('anatomy_layer') or {})
    return np.asarray(v, np.float64), faces


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--characters', action='store_true', help='measure every registered character')
    ap.add_argument('--sweep', action='store_true', help='rebuild the rejected female and sweep the swayback lever')
    ap.add_argument('--falsify', action='store_true', help='how far the gluteal gate is from firing')
    ap.add_argument('--build-reference', action='store_true')
    ap.add_argument('-n', type=int, default=600)
    ap.add_argument('--seed', type=int, default=20260806)
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--gates', action='store_true', help='print the calibrated gate registry')
    ap.add_argument('--json', default=None)
    a = ap.parse_args(argv)
    out = {}

    if a.build_reference:

        def prog(k, d, el):
            print('  %4d accepted / %5d drawn  %5.0fs' % (k, d, el), file=sys.stderr)

        p = build_reference(a.n, a.seed, a.workers, progress=prog)
        pack = form_reference(p)
        print(
            'wrote %s: n=%d accepted of %d drawn (%.1f%%), %.0fs'
            % (p, pack['n_accepted'], pack['n_drawn'], 100 * pack['acceptance_rate'], pack['elapsed_s'])
        )
        out['reference'] = p

    if a.characters:
        rows = []
        print(
            '%-10s %8s %9s %9s %9s %9s %8s %9s %9s'
            % ('character', 'stature', 'lordosis', 'curve', 'lowerT', 'upperT', 'glut+mm', 'eyeDiv', 'kneeFTA')
        )
        for grp, name, params in _characters():
            v, faces = _build_character(params)
            rel = measure_relations(
                v, faces, phenotype=params['phenotype'], local_changes=params.get('local_changes') or None
            )
            s = scalars(rel)
            rows.append({'group': grp, 'name': name, 'scalars': s, 'unresolved': rel['unresolved']})
            print(
                '%-10s %8.4f %9.4f %9.4f %9.4f %9.4f %8.2f %9.4f %9.4f'
                % (
                    name,
                    rel['stature_m'],
                    s['lordosis_index'],
                    s['lumbar_curve_angle_deg'],
                    s['lower_chord_tilt_deg'],
                    s['upper_chord_tilt_deg'],
                    s['gluteal_margin_mm'],
                    s['eye_divergence_transverse_deg'],
                    s['knee_fta_deg'],
                )
            )
        print('unresolved on every character: %s' % ', '.join(rows[0]['unresolved']))
        out['characters'] = rows

    if a.sweep:
        rows = swayback_sweep()
        print('%-30s %8s %9s %9s %9s %9s %8s' % ('recipe', 'lever', 'lordosis', 'curve', 'depth_mm', 'trough', 'oppos'))
        for r in rows:
            s = r['scalars']
            print(
                '%-30s %8.2f %9.4f %9.4f %9.4f %9.4f %8s'
                % (
                    r['tag'],
                    r['lever_value'],
                    s['lordosis_index'],
                    s['lumbar_curve_angle_deg'],
                    s['lordosis_depth_mm'],
                    s['trough_frac_stature'],
                    s['opposition_physiological'],
                )
            )
        out['sweep'] = rows

    if a.falsify:
        rows = falsification_sweep()
        for r in rows:
            print(
                '%-24s %+0.2f  margin %s  sep %s  %s'
                % (
                    r['lever'],
                    r['value'],
                    'None' if r['margin_mm'] is None else '%+8.2f mm' % r['margin_mm'],
                    'None' if r['separation_frac_stature'] is None else '%+0.4f' % r['separation_frac_stature'],
                    '' if r['resolved'] else 'REFUSED: ' + (r['reason'] or '')[:90],
                )
            )
        out['falsification'] = rows

    if a.gates:
        gs = gate_records()
        validate_registry(gs)
        for g in gs:
            cal = calibrate(g)
            print(
                '%-42s declared=%-5s effective=%-5s threshold=%s'
                % (g.id, g.severity, cal['severity_effective'], g.threshold)
            )
            print('    %s' % cal['explain'])
        out['gates'] = [dict(g.as_dict(), calibration=calibrate(g)) for g in gs]

    if a.json:
        tmp = a.json + '.tmp'
        with open(tmp, 'w') as fh:
            json.dump(out, fh, indent=1, default=str)
        os.replace(tmp, a.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
