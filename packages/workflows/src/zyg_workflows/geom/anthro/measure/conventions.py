# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""compare_conventions() — hull vs contour vs vendor polyline on one body.

Moved verbatim out of the old single-file measure.py (lines 3343-3449).
"""

import numpy as np

from zyg_workflows.geom import mesh_skeletons as MS
from zyg_workflows.geom.anthro import landmarks as LMK
from zyg_workflows.geom.anthro.measure.constants import SCAN_STEP_FRAC
from zyg_workflows.geom.anthro.measure.anchors import (
    _ear_top_frac,
    _limb_axes,
)
from zyg_workflows.geom.anthro.measure.tables_girth import GIRTH_SITES
from zyg_workflows.geom.anthro.measure.sites import _girth_site


# ---------------------------------------------------------------------------------
# convention comparison
# ---------------------------------------------------------------------------------
def compare_conventions(v, faces, *, phenotype=None, local_changes=None, landmarks=None):
    """Quantify hull vs contour vs inscribed polyline per girth site, on THIS mesh.

    The claim to test is that the convex hull (taut tape) is never shorter than the
    MakeHuman inscribed polyline. Both numbers come from the same plane and the same
    selected loop, so the difference is purely the convention.
    """
    v = np.asarray(v, np.float64)
    faces = np.asarray(faces)
    if landmarks is None:
        landmarks = LMK.resolve_landmarks(v, faces, phenotype, local_changes)
    try:
        coco = LMK._coco(phenotype, local_changes)
    except Exception:  # noqa: BLE001
        coco = None
    axes = _limb_axes(coco)
    zmin = float(v[:, 2].min())
    H = float(v[:, 2].max()) - zmin
    step = SCAN_STEP_FRAC * H
    ear_top = _ear_top_frac(v, zmin, H)
    crotch_frac = (landmarks.get('crotch') or {}).get('frac_stature')

    rows = {}
    for spec in GIRTH_SITES:
        if spec['scope'] == 'all':
            continue  # merged-loop hull has no single vertex ring
        for side in spec['sides'] or (None,):
            key = spec['name'] + ('_' + side if side else '')
            r = _girth_site(v, faces, spec, side, landmarks, axes, zmin, H, step, coco, ear_top, crotch_frac)
            if r.get('hull_mm') is None or r.get('polyline_mm') is None:
                rows[key] = {
                    'hull_mm': r.get('hull_mm'),
                    'contour_mm': r.get('contour_mm'),
                    'polyline_mm': r.get('polyline_mm'),
                    'reason': r.get('reason', 'one convention unavailable'),
                }
                continue
            rows[key] = {
                'hull_mm': r['hull_mm'],
                'contour_mm': r['contour_mm'],
                'polyline_mm': r['polyline_mm'],
                'hull_minus_polyline_mm': r['hull_mm'] - r['polyline_mm'],
                'hull_minus_polyline_pct': 100.0 * (r['hull_mm'] - r['polyline_mm']) / r['polyline_mm'],
                'hull_minus_contour_mm': r['hull_mm'] - r['contour_mm'],
                'polyline_planar_mm': r.get('polyline_planar_mm'),
                'hull_minus_polyline_planar_mm': None
                if r.get('polyline_planar_mm') is None
                else r['hull_mm'] - r['polyline_planar_mm'],
                'contour_points': r.get('contour_points'),
                'ring_vertices': r.get('ring_vertices'),
                'ring_out_of_plane_mm': r.get('polyline_ring_out_of_plane_mm'),
                'plane': spec['plane'],
                'iso_class': spec['iso_class'],
            }

    good = [x for x in rows.values() if x.get('hull_minus_polyline_mm') is not None]
    hp = [x['hull_minus_polyline_mm'] for x in good]
    hc = [x['hull_minus_contour_mm'] for x in good]
    hpp = [x['hull_minus_polyline_planar_mm'] for x in good if x.get('hull_minus_polyline_planar_mm') is not None]
    summary = {
        'n_sites': len(good),
        'hull_ge_polyline_everywhere': bool(all(x >= 0 for x in hp)) if hp else None,
        'hull_ge_polyline_planar_everywhere': bool(all(x >= 0 for x in hpp)) if hpp else None,
        'hull_minus_polyline_planar_mm': {'min': min(hpp), 'max': max(hpp), 'mean': float(np.mean(hpp))}
        if hpp
        else None,
        'hull_minus_polyline_mm': {'min': min(hp), 'max': max(hp), 'mean': float(np.mean(hp))} if hp else None,
        'hull_minus_contour_mm': {'min': min(hc), 'max': max(hc), 'mean': float(np.mean(hc))} if hc else None,
        'hull_le_contour_everywhere': bool(all(x <= 1e-9 for x in hc)) if hc else None,
        'ring_out_of_plane_mm_max': max(
            (x['ring_out_of_plane_mm'] for x in good if x.get('ring_out_of_plane_mm') is not None), default=None
        ),
        'interpretation': 'hull <= contour is a theorem, not a finding: the convex hull is the shortest '
        'closed curve enclosing a plane curve, so a contour that dips into a '
        'concavity is LONGER than the tape that bridges it. hull vs polyline is the '
        'empirical question, and the answer depends on how non-planar the vertex ring '
        'is — a ring that undulates vertically charges for the undulation in its 3D '
        'chord sum and can exceed both the contour and the hull. Read '
        'ring_out_of_plane_mm alongside every polyline number.',
    }
    native = None
    try:
        from anny.anthropometry import Anthropometry
        import torch

        a = Anthropometry(MS._model())
        with torch.no_grad():
            native = float(a.waist_circumference(torch.as_tensor(v, dtype=torch.float32)[None])[0]) * 1000
    except Exception as e:  # noqa: BLE001
        native = None
        summary['anny_native_error'] = str(e)
    if native is not None:
        ours = rows.get('waist_circumference_anny_ring', {})
        summary['anny_native_waist_polyline_mm'] = native
        summary['anny_native_vs_our_hull_mm'] = None if ours.get('hull_mm') is None else ours['hull_mm'] - native
        summary['anny_native_note'] = (
            'anny.anthropometry.Anthropometry.waist_circumference over its own 46-vertex '
            "ring, in the vendor's own chord-sum convention. This is the number a caller "
            'gets from the model if they do not slice, and the gap to our hull is the '
            'error they would import into a survey comparison.'
        )
    return {'sites': rows, 'summary': summary}
