# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""integrity.entry — Entry point: check_integrity, the report printer and the CLI."""

import os

import numpy as np
from zyg_workflows.geom.anthro.integrity.constants import SYM_MORPH_TOL_MM, TOPOLOGY_SCOPES, _ms, _now
from zyg_workflows.geom.anthro.integrity.mesh_checks import (
    _check_degenerate,
    _check_edge_manifold,
    _check_euler,
    _check_outward,
    _check_vertex_manifold,
    _check_watertight,
    _check_winding,
    _components,
    triangulate_quads,
)
from zyg_workflows.geom.anthro.integrity.self_intersection import _check_self_intersection
from zyg_workflows.geom.anthro.integrity.shells import _check_shell_components
from zyg_workflows.geom.anthro.integrity.symmetry_topology import _check_mirror, _check_topology_identity

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# ---------------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------------


def check_integrity(
    v,
    faces,
    *,
    expect_vertices=None,
    expect_faces=None,
    self_intersection=True,
    symmetry_tol_mm=SYM_MORPH_TOL_MM,
    self_intersection_tol_m=0.0,
    cross_check_diagonal=True,
    shell_components=True,
    containment=True,
):
    """Run every Tier-1 check independently and return them side by side.

    Returns {check_name: {'pass': bool, 'detail': ..., 'ms': float}} plus a '_summary'
    entry of the same shape. The underscore is load-bearing: '_summary' is a roll-up of
    the others, so any caller iterating the checks must skip keys starting with '_' or it
    will double-count.

    Nothing here short-circuits. A mesh that fails watertightness still gets its
    self-intersection measured, because the two are independent and the operator needs
    both to know what actually broke.

    `containment=False` keeps the shell inventory (cheap, and the part an operator reads)
    while skipping the winding-number and ray work (the only part with a real cost). Every
    shell then reports state 'not_tested', `asserted` is False and the check asserts
    nothing — it never reports a cheerful 'enclosed' it did not earn.

    `self_intersection=False` with containment left ON is a different thing and is NOT an
    opt-out: enclosure is undecidable without knowing whether a shell's faces cross the
    body, so every shell reports 'crossing_not_tested' and shell_components FAILS. Pass
    `containment=False` as well to opt out cleanly. A check that could not run must not
    come back green.
    """
    v = np.asarray(v, np.float64)
    faces = np.asarray(faces)
    if v.ndim != 2 or v.shape[1] != 3:
        raise ValueError('v must be (N,3), got %r' % (v.shape,))
    if faces.ndim != 2 or faces.shape[1] not in (3, 4):
        raise ValueError('faces must be (F,3) or (F,4), got %r' % (faces.shape,))
    if faces.size and (faces.max() >= len(v) or faces.min() < 0):
        raise ValueError('face index out of range for %d vertices: [%d, %d]' % (len(v), faces.min(), faces.max()))

    t_all = _now()
    tris = triangulate_quads(faces)
    ncomp, labels = _components(v, tris)

    out = {}
    out['topology_identity'] = _check_topology_identity(v, faces, expect_vertices, expect_faces)
    out['watertight'] = _check_watertight(v, tris)
    out['edge_manifold'] = _check_edge_manifold(v, tris)
    out['vertex_manifold'] = _check_vertex_manifold(v, tris)
    out['winding_consistent'] = _check_winding(v, tris)
    # outward_normals DEPENDS on winding: signed volume is only a volume on a coherently
    # oriented surface. Passing the winding verdict in is what stops it answering an
    # ill-posed question with a pass. See _check_outward.__doc__.
    out['outward_normals'] = _check_outward(
        v, tris, labels, ncomp, winding_ok=bool(out['winding_consistent'].get('pass'))
    )
    out['degenerate_geometry'] = _check_degenerate(v, faces, tris)
    out['euler_genus'] = _check_euler(v, tris, labels, ncomp)
    out['mirror_symmetry_morph'] = _check_mirror(v, symmetry_tol_mm)

    # self-intersection first: shell_components needs to know which shells touch which,
    # and re-deriving that would mean running the narrow phase twice. The counts handed
    # over are the DELIVERED-triangulation ones, because "does this shell cross the body
    # surface" is a question about the surface that ships, not about the diagonal-agreeing
    # subset of it.
    delivered_by_pair = None
    if self_intersection:
        si = _check_self_intersection(v, faces, labels, self_intersection_tol_m, cross_check_diagonal)
        out['self_intersection'] = si
        delivered_by_pair = si['detail']['delivered_face_pairs_by_component_pair']
    if shell_components:
        out['shell_components'] = _check_shell_components(
            v,
            faces,
            tris,
            labels,
            ncomp,
            out['euler_genus']['detail']['per_component'],
            delivered_by_pair,
            containment=containment,
        )

    failed = sorted(k for k, r in out.items() if not r['pass'])
    # A check that was switched off is not a check that passed. `failed` cannot carry it
    # (it produced no verdict at all), so it gets its own list rather than vanishing into
    # the difference between two counts nobody computes.
    not_run = sorted(
        k for k, on in (('self_intersection', self_intersection), ('shell_components', shell_components)) if not on
    )
    unasserted = sorted(
        k
        for k, r in out.items()
        if isinstance(r.get('detail'), dict)
        and (
            r['detail'].get('nothing_asserted')
            or r['detail'].get('nothing_declared')
            or r['detail'].get('asserted') is False
        )
    )
    out['_summary'] = {
        'pass': bool(not failed),
        'detail': {
            'checks_run': len(out),
            'failed': failed,
            'not_run': not_run,
            'passed_but_asserted_nothing': unasserted,
            'roll_up_note': '`pass` is the AND of the checks that ran. It is not a statement '
            'about `not_run` (switched off by the caller) or about '
            '`passed_but_asserted_nothing` (ran, found nothing to object to, '
            'and asserted nothing — an undeclared topology scope, or '
            'containment=False). Neither of those is a pass; read all three '
            'lists.',
            'vertices': int(len(v)),
            'faces': int(len(faces)),
            'face_arity': int(faces.shape[1]),
            'triangles': int(len(tris)),
        },
        'ms': _ms(t_all),
    }
    return out


def _fmt(name, r):
    """PASS/FAIL, and never a bare PASS for a check that asserted nothing."""
    d = r.get('detail')
    flag = ''
    if (
        isinstance(d, dict)
        and r['pass']
        and (d.get('nothing_asserted') or d.get('nothing_declared') or d.get('asserted') is False)
    ):
        flag = '  (NOTHING ASSERTED — not a verification)'
    return '  %-24s %-4s %8.1f ms%s' % (name, 'PASS' if r['pass'] else 'FAIL', r['ms'], flag)


def _print_shells(res):
    """The inventory in a form an operator can read without opening the JSON. This is the
    output that stops the next person spending a day deciding whether 500 intersecting
    quad pairs mean the head is broken."""
    sc = res.get('shell_components')
    if sc:
        d = sc['detail']
        _zyg_log.info(
            '    shells: %d components, body=comp %d (chi=%s genus=%s closed=%s)'
            % (d['components'], d['body_component'], d['body_euler_chi'], d['body_genus'], d['body_closed'])
        )
        for e in d['inventory']:
            c = e.get('containment') or {}
            extra = ''
            if e['role'] == 'shell':
                sky = c.get('open_sky_from_outside_vertices') or {}
                extra = '  in=%s/%s sky=%s envelope_margin_max=%s mm %s' % (
                    c.get('vertices_inside_body'),
                    e['vertices'],
                    sky.get('mean'),
                    c.get('envelope_margin_max_mm'),
                    c.get('state'),
                )
            _zyg_log.info(
                '      comp %d %-16s %5d v  z %.4f-%.4f%s'
                % (e['component'], e['name'], e['vertices'], e['z_frac_min'], e['z_frac_max'], extra)
            )
            if c.get('unresolved_because'):
                _zyg_log.info('        UNRESOLVED: %s' % c['unresolved_because'])
        _zyg_log.info(
            '      ray-parity agreement: %s   envelope: %s' % (d['ray_parity_agreement'], d.get('convex_envelope'))
        )
        if not d.get('asserted', True):
            _zyg_log.info(
                '      NOTHING ASSERTED about where the shells sit: %s'
                % d.get('note_containment', 'containment not established')
            )
    si = res.get('self_intersection')
    if si:
        d = si['detail']
        _zyg_log.info(
            '    self-intersection (DELIVERED triangulation): INTRA=%s (defect) '
            'INTER=%s (shells meeting) total=%s  by component pair %s'
            % (
                d['face_pairs_delivered_intra_component'],
                d['face_pairs_delivered_inter_component'],
                d['intersecting_face_pairs'],
                d['delivered_face_pairs_by_component_pair'],
            )
        )
        _zyg_log.info(
            '      diagonal split: agreeing INTRA=%s, delivered-only INTRA=%s, '
            'alt-diagonal-only INTRA=%s (do not ship)'
            % (
                d.get('face_pairs_diagonal_agreeing_intra_component'),
                d.get('face_pairs_delivered_only_intra_component'),
                d.get('face_pairs_alt_diagonal_only_intra_component'),
            )
        )
        loc = d.get('example_locality') or {}
        allz = d.get('defect_locality_all_pairs') or {}
        if d['examples']:
            _zyg_log.info('      example intra-component face pairs: %s' % (d['examples'][:4],))
            _zyg_log.info(
                '      examples sit at z %.4f-%.4f of stature, around %s'
                % (loc['z_frac_min'], loc['z_frac_max'], loc['pairs'][0]['centroid_m'])
            )
            _zyg_log.info(
                '      ALL %s defect pairs span z %.4f-%.4f'
                % (allz.get('n_pairs'), allz.get('z_frac_min'), allz.get('z_frac_max'))
            )


def main(argv=None):
    import argparse
    import glob
    import json

    ap = argparse.ArgumentParser(description='Tier-1 mesh integrity on issued meshes.')
    ap.add_argument('paths', nargs='*', help='.glb files (default: the issued cages)')
    ap.add_argument('--scope', default='full', choices=sorted(TOPOLOGY_SCOPES))
    ap.add_argument('--no-self-intersection', action='store_true')
    ap.add_argument('--no-containment', action='store_true', help='inventory the shells but do not test where they sit')
    ap.add_argument('--json', help='write the full report here')
    a = ap.parse_args(argv)

    paths = a.paths
    if not paths:
        from zyg_workflows.geom import mesh_skeletons as MS

        paths = sorted(glob.glob(os.path.join(MS.ROOT, '*', '*', 'skeleton_*.glb')))
    if not paths:
        raise SystemExit('no meshes found')

    import trimesh

    report = {}
    for p in paths:
        m = trimesh.load(p, process=False, force='mesh')
        name = os.path.basename(os.path.dirname(p))
        # trimesh returns the exported TRIANGLES; the quad cage is recoverable only from
        # anny, so .glb input is checked as tris and the quad-diagonal cross-check does
        # not apply to it.
        res = check_integrity(
            np.asarray(m.vertices),
            np.asarray(m.faces),
            expect_vertices=a.scope,
            expect_faces=a.scope,
            self_intersection=not a.no_self_intersection,
            containment=not a.no_containment,
        )
        report[name] = res
        print('%s  (%s)' % (name, p))
        for k in sorted(res):
            if k != '_summary':
                print(_fmt(k, res[k]))
        print(_fmt('_summary', res['_summary']))
        _print_shells(res)
        print()
    if a.json:
        tmp = a.json + '.tmp'
        with open(tmp, 'w') as fh:
            json.dump(report, fh, indent=1, default=str)
        os.replace(tmp, a.json)
        print('wrote %s' % a.json)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
