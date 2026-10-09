# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The measurement record builder and the anchor resolver.

Moved verbatim out of the old single-file measure.py (lines 2209-2263).
"""

import numpy as np

from zyg_workflows.geom.anthro.measure.constants import (
    ISO_20685_1_TABLE4_MM,
    ISO_CAVEAT,
)
from zyg_workflows.geom.anthro.measure.anchors import _ring_anchor


# ---------------------------------------------------------------------------------
# the record builder
# ---------------------------------------------------------------------------------
def _rec(value_mm, kind, landmark, convention, iso_class, note, provenance='MEASURED', **extra):
    d = {
        'value_mm': None if value_mm is None else float(value_mm),
        'kind': kind,
        'landmark': landmark,
        'convention': convention,
        'iso_class': iso_class,
        'note': note,
        'provenance': provenance,
    }
    if iso_class:
        d['iso_20685_1_mean_diff_mm'] = ISO_20685_1_TABLE4_MM.get(iso_class)
        d['iso_caveat'] = ISO_CAVEAT
    d.update(extra)
    return d


HULL_CONVENTION = (
    'plane slice + CONVEX HULL of the intersection contour (taut-tape '
    'emulation, as used by SHAPY / A2B / CALVIS and implied by '
    'ISO 18825-2)'
)
POLYLINE_CONVENTION = (
    'cage vertex ring immediately below the cut, chord-summed in 3D — the MakeHuman / '
    'anny Ruler convention generalised to an arbitrary site. NEVER comparable to a survey '
    'circumference. MEASURED on this cage it comes out LONGER than the taut-tape hull at '
    '124 of 125 site-character combinations (by 5.0 to 226.4 mm, mean 65.8), because the '
    'ring undulates 8.2-40.2 mm out of the plane and the chord sum charges for the '
    'undulation. See compare_conventions() and its polyline_planar_mm decomposition.'
)


def _anchor_point(anchor, lm, v, side=None):
    """Resolve a site anchor to a 3D point, or None with a reason."""
    if anchor.get('landmark'):
        name = anchor['landmark']
        r = lm.get(name)
        if r is None or r.get('point') is None:
            return None, 'landmark %r did not resolve on this mesh' % name
        return np.asarray(r['point'], np.float64), 'landmark %s' % name
    if anchor.get('ring'):
        p = _ring_anchor(v, anchor['ring'], side)
        if p is None:
            return None, 'ring %r has no support on this side' % anchor['ring']
        return p, 'MakeHuman ring %s%s' % (anchor['ring'], '' if not side else ' (%s)' % side)
    if anchor.get('coco'):
        return None, 'coco'
    if anchor.get('fz_band'):
        return None, 'band'
    return None, 'no anchor'
