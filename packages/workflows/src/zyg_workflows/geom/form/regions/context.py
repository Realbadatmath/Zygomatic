# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""regions — neutral-cage context, anchor primitives and the region resolvers.

Moved verbatim out of regions.py; see the package __init__ for the full rationale.
"""

# ruff: noqa: F401
# F401: this module inherits the original top import block; the siblings re-import what they use
# __all__ names only what this module actually defines. The original module's other public
# names live in the sibling modules and are re-exported by the package __init__, which is
# where every caller reads them — listing them here again would just be an F822.

import hashlib
import json
import os
import sys
import tempfile
import time

import numpy as np

from zyg_workflows import paths
from zyg_workflows.geom import mesh_skeletons as MS
from zyg_workflows.geom.anthro import landmarks as LM
from zyg_workflows.geom.form import curvature as CV
import logging as _zyg_logging

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.geom.form.regions')


__all__ = [
    'REGIONS_PATH',
    'SCHEMA_VERSION',
]

SCHEMA_VERSION = 1
CAGE_VERTS = LM.CAGE_VERTS
CAGE_FACES = LM.CAGE_FACES

REGIONS_PATH = str(paths.DATA_DIR / 'assets' / 'form_reference' / 'regions.json')

# The strict cut a FEATURE SEARCH must clear before this module will say a bony landmark
# exists on the cage. It is the p99 of the body's own relief null (curvature.relief_null),
# not a number picked to make things resolve: at the p95 defaults one random patch of
# ordinary skin in twenty already reads as a landmark, and a landmark claim cannot be made
# at that rate. Both conditions must hold.
FEATURE_MIN_FRAC = CV.RELIEF_NULL_P99['min_frac_stature']
FEATURE_MIN_CONTRAST = CV.RELIEF_NULL_P99['min_contrast']
FEATURE_PROBE_RADIUS = 0.012  # of stature; matches the radius the null was taken at


def _patch_seed_fix_enabled():
    """ZYG_REGIONS_PATCH_SEED_FIX — default 1 (on). Set 0 to restore the pre-fix behaviour
    of seeding _r_feature_search's patch growth from the GLOBAL relief peak, which raises
    ValueError whenever that peak fails the contrast cut. Kept only as a rollback."""
    return os.environ.get('ZYG_REGIONS_PATCH_SEED_FIX', '1').strip().lower() not in ('0', 'false', 'no', 'off', '')


# ---------------------------------------------------------------------------------
# neutral-cage context — every anchor in this file is topology-fixed and resolved here
# ---------------------------------------------------------------------------------
_CTX = {}


def _ctx():
    """The anny neutral (landmarks.REF_MALE) plus everything the resolvers share."""
    if _CTX:
        return _CTX
    v, faces, _ = MS._build_mesh(LM.REF_MALE, None)
    v = np.asarray(v, np.float64)
    if len(v) != CAGE_VERTS or np.asarray(faces).shape != (CAGE_FACES, 4):
        raise RuntimeError(
            'the neutral built %d verts / %s faces, not the %d/%d cage this '
            'module is indexed against' % (len(v), (np.asarray(faces).shape,), CAGE_VERTS, CAGE_FACES)
        )
    zmin = float(v[:, 2].min())
    S = float(v[:, 2].max()) - zmin
    _CTX.update(
        {
            'v': v,
            'faces': faces,
            'zmin': zmin,
            'S': S,
            'fz': (v[:, 2] - zmin) / S,
            'adj': CV.vertex_adjacency(faces, len(v)),
            'normals': CV.vertex_normals(v, faces),
            'areas': CV.mixed_voronoi_area(v, faces),
            'mirror': LM._mirror(None),
            'landmarks': LM.resolve_landmarks(v, faces, LM.REF_MALE, None),
        }
    )
    return _CTX


def _relief(g, **kw):
    c = _ctx()
    return CV.region_relief(c['v'], c['faces'], g, stature_m=c['S'], areas=c['areas'], normals=c['normals'], **kw)


def _ball(seed, radius_frac):
    c = _ctx()
    return CV.geodesic_ball(c['v'], c['faces'], np.atleast_1d(seed), radius_frac, c['S'])


def _support(label, thresh=3e-4):
    s = LM._support(label, thresh)
    if s is None:
        raise RuntimeError(
            'morph target %r has empty support at the male reference; the '
            'local-changes vocabulary is not loaded' % label
        )
    return s[0]


def _left(idx):
    return np.asarray(idx)[_ctx()['v'][np.asarray(idx), 0] > 1e-6]


def _joint_line(label, side='l'):
    """The boundary of a segment-length morph's support = that segment's joint line.

    A segment-length target translates everything distal to the segment and stretches the
    segment itself; it does not move the joint it pivots about. So the vertices of its
    support that still touch a non-support vertex ARE the joint's line on the skin.
    landmarks.py uses the same fact to resolve tibiale. Measured on the neutral, each of
    the four limb targets gives 40 boundary vertices, 20 per side, at 0.665 (elbow), 0.771
    (shoulder), 0.252 (knee) and 0.473 (hip) of stature.
    """
    c = _ctx()
    idx = _support(label)
    m = np.zeros(len(c['v']), bool)
    m[idx] = True
    ring = np.nonzero(m & (c['adj'].dot((~m).astype(np.float64)) > 0))[0]
    return _left(ring) if side == 'l' else ring[c['v'][ring, 0] < -1e-6]


def _limb_frame(proximal_ring, distal_ring):
    """(centre, axis, posterior, lateral) for a limb, in the limb's own directions.

    The axis is proximal-ring centroid -> distal-ring centroid, so it survives the A-pose
    without assuming the limb hangs vertically — measured, the left forearm axis on this
    cage is (0.509, -0.696, -0.507), i.e. no global axis is within 45 degrees of it and a
    sector taken in world coordinates would name the wrong side of the elbow.
    """
    c = _ctx()
    o = c['v'][proximal_ring].mean(0)
    a = c['v'][distal_ring].mean(0) - o
    a /= np.linalg.norm(a)
    post = np.array([0.0, 1.0, 0.0]) - a[1] * a
    n = np.linalg.norm(post)
    if n < 1e-6:
        raise RuntimeError('limb axis is parallel to the anteroposterior axis; "posterior" is undefined for it')
    post /= n
    lat = np.cross(a, post)
    lat /= np.linalg.norm(lat)
    if lat[0] < 0:  # +x is the subject's LEFT, measured by frame_report
        lat = -lat
    return o, a, post, lat


def _sector(ring, axis_dirs, direction, half_deg, band_frac, reach_frac, offset_frac=0.0):
    """A patch of one limb: the vertices near a ring, on one side of the limb.

    reach_frac is a GEODESIC leash and it is load-bearing, not a speed trick. In the A-pose
    the arm hangs beside the ribs, so a purely geometric "medial sector of the elbow"
    swallows 312 vertices of TORSO — measured, and it produced a -75 mm "epicondyle"
    against a 21 mm collar residual. Leashing the sector to the surface around the ring
    keeps it on the limb: the same sector then returns 12 vertices and +4.5 mm.
    """
    c = _ctx()
    _, a, _, _ = axis_dirs
    pool = np.nonzero(CV.surface_distance(c['v'], c['faces'], ring) <= reach_frac * c['S'])[0]
    # The band is centred on THE RING'S OWN centroid, never on the frame's origin. The
    # frame's origin is the proximal ring the limb axis was built from, and using it put
    # the wrist, ankle and knee-girth sectors at the elbow and the knee instead —
    # measured, it emptied three regions outright and moved the patella patch from 0.304
    # to 0.255 of stature.
    origin = c['v'][ring].mean(0) + a * offset_frac * c['S']
    rel = c['v'][pool] - origin
    along = rel.dot(a)
    rad = rel - np.outer(along, a)
    rn = np.linalg.norm(rad, axis=1)
    with np.errstate(invalid='ignore', divide='ignore'):
        cos = rad.dot(direction) / np.maximum(rn, 1e-12)
    keep = (np.abs(along) <= band_frac * c['S']) & (cos >= np.cos(np.radians(half_deg))) & (rn > 1e-9)
    return pool[keep]


# ---------------------------------------------------------------------------------
# resolvers. Each returns (left_vertex_indices | None, evidence dict).
# ---------------------------------------------------------------------------------
def _r_landmark_ball(landmark, radius_frac):
    c = _ctx()
    rec = c['landmarks'].get(landmark)
    if rec is None or not rec['vertex_idx']:
        return None, {
            'why': 'geom.anthro.landmarks reports %r as %s' % (landmark, (rec or {}).get('confidence', 'absent'))
        }
    g = _ball(rec['vertex_idx'], radius_frac)
    return g, {
        'seed_vertices': [int(i) for i in rec['vertex_idx']],
        'seed_frac_stature': rec['frac_stature'],
        'landmark_confidence': rec['confidence'],
        'radius_frac_stature': radius_frac,
    }


def _r_support_gap(label_a, label_b, radius_frac, side_left=True):
    """The surface BETWEEN two named muscle supports — i.e. the groove they leave."""
    c = _ctx()
    A = _support(label_a)
    B = _support(label_b)
    if side_left:
        A, B = _left(A), _left(B)
    if not len(A) or not len(B):
        return None, {'why': 'one of the two supports is empty on this side'}
    dA = CV.surface_distance(c['v'], c['faces'], A)
    dB = CV.surface_distance(c['v'], c['faces'], B)
    inside = np.zeros(len(c['v']), bool)
    inside[A] = True
    inside[B] = True
    g = np.nonzero((~inside) & (dA <= radius_frac * c['S']) & (dB <= radius_frac * c['S']) & (c['v'][:, 0] > 1e-6))[0]
    ev = {
        'support_a': label_a,
        'n_a': int(len(A)),
        'support_b': label_b,
        'n_b': int(len(B)),
        'radius_frac_stature': radius_frac,
    }
    return (g if len(g) else None), ev


def _r_feature_search(
    window, polarity, radius_frac=FEATURE_PROBE_RADIUS, min_frac=FEATURE_MIN_FRAC, min_contrast=FEATURE_MIN_CONTRAST
):
    """Sweep a window of skin for a genuine local protrusion or depression.

    THIS IS THE RESOLVER THAT IS ALLOWED TO SAY NO, and on this cage it usually does. Every
    vertex of the window is probed with a geodesic ball of the same radius the relief null
    was measured at, and a landmark is only declared where the relief clears the null's p99
    on BOTH the stature-relative magnitude and the contrast against the collar's own fit
    residual. When nothing clears it the evidence carries the strongest thing the window DID
    contain and where it was, so the negative is checkable rather than merely asserted.
    """
    c = _ctx()
    idx = np.nonzero(_window_mask(window))[0]
    if not len(idx):
        return None, {'why': 'window is empty on this cage', 'window': window}
    sgn = 1.0 if polarity == 'protrusion' else -1.0
    rel = np.full(len(idx), np.nan)
    con = np.full(len(idx), np.nan)
    for k, i in enumerate(idx):
        try:
            r = _relief(_ball(i, radius_frac))
        except ValueError as _exc:
            _zyg_log.debug('relief probe skipped on this vertex: %s', _exc)
            continue
        rel[k] = r['relief_frac_stature']
        con[k] = r['contrast']
    ok = np.isfinite(rel)
    if not ok.any():
        return None, {
            'why': 'no probe in the window produced a usable collar',
            'window': window,
            'n_window': int(len(idx)),
        }
    score = sgn * rel
    best = int(np.nanargmax(np.where(ok, score, -np.inf)))
    ev = {
        'window': window,
        'n_window': int(len(idx)),
        'n_probed': int(ok.sum()),
        'polarity': polarity,
        'probe_radius_frac': radius_frac,
        'threshold_frac': min_frac,
        'threshold_contrast': min_contrast,
        'best_vertex': int(idx[best]),
        'best_relief_mm': float(rel[best] * c['S'] * 1000.0),
        'best_relief_frac': float(rel[best]),
        'best_contrast': float(con[best]),
        'best_frac_stature_height': float(c['fz'][idx[best]]),
        'best_xyz_m': [round(float(x), 4) for x in c['v'][idx[best]]],
    }
    hit = ok & (score >= min_frac) & (sgn * np.nan_to_num(con) >= min_contrast)
    if not hit.any():
        ev['why'] = (
            "no vertex in this window reaches the cage's own relief p99: the "
            'strongest is %+.2f mm at contrast %+.2f against a required %+.2f mm '
            'and %.2f' % (ev['best_relief_mm'], ev['best_contrast'], sgn * min_frac * c['S'] * 1000.0, min_contrast)
        )
        return None, ev
    # Grow the connected patch of same-polarity hits around the strongest QUALIFYING vertex.
    #
    # It must be the strongest QUALIFYING one, not `best`. `best` is an argmax over RELIEF
    # ALONE, while `seeds` holds only the vertices that clear relief AND contrast, so the
    # two are the same vertex only when the global peak happens to pass both cuts. When it
    # does not, seeding from it is not merely wrong, it is unrepresentable: the vertex is
    # not in the patch's own index space. The shipped form of this line was
    #     g = seeds[lab == lab[list(seeds).index(int(idx[best]))]]
    # and it raised `ValueError: <vid> is not in list` for exactly that case. It never fired
    # on the 20 shipped body regions: 11 of them use a different resolver and never reach
    # this line, and the 9 feature_search ones all have zero hits (strongest +4.16 mm at
    # contrast 2.66, scapular_spine) and return above it. It fires
    # reliably on head windows, where relief is large but the collar is itself curved so the
    # contrast ratio is low — MEASURED on the anny neutral: orbital_margin +20.03 mm relief
    # crashes here, superciliary_arch +15.39 mm at contrast 2.35 and nasal_bone +16.93 mm at
    # contrast 1.91 fall short of the 3.70 contrast floor outright.
    #
    # The evidence keeps reporting the GLOBAL peak in best_* — that is what makes a negative
    # checkable — and records the patch's own seed separately, plus whether the peak ended
    # up inside the patch, so the divergence is visible rather than papered over.
    seeds = idx[hit]
    m = np.zeros(len(c['v']), bool)
    m[seeds] = True
    from scipy.sparse.csgraph import connected_components

    sub = c['adj'][seeds][:, seeds]
    _, lab = connected_components(sub, directed=False)
    if _patch_seed_fix_enabled():
        # position WITHIN seeds of the best-scoring hit; score is finite wherever hit is
        seed_pos = int(np.argmax(score[hit]))
    else:
        seed_pos = list(seeds).index(int(idx[best]))  # pre-fix behaviour, may raise
    g = seeds[lab == lab[seed_pos]]
    ev['n_hits'] = int(hit.sum())
    ev['n_patch'] = int(len(g))
    ev['patch_seed_vertex'] = int(seeds[seed_pos])
    ev['patch_seed_relief_mm'] = float(rel[hit][seed_pos] * c['S'] * 1000.0)
    ev['patch_seed_contrast'] = float(con[hit][seed_pos])
    ev['peak_qualifies'] = bool(hit[best])
    ev['peak_in_patch'] = bool(int(idx[best]) in set(int(i) for i in g))
    return g, ev


def _window_mask(w):
    """Window spec -> boolean mask. All extents are FRACTIONS OF STATURE, so the same
    window means the same anatomy on any body — even though these only ever run on the
    neutral, a window written in metres would be silently wrong the day someone reuses it."""
    c = _ctx()
    v, S, fz, n = c['v'], c['S'], c['fz'], c['normals']
    m = np.ones(len(v), bool)
    if 'fz' in w:
        m &= (fz >= w['fz'][0]) & (fz <= w['fz'][1])
    if 'x' in w:
        m &= (v[:, 0] / S >= w['x'][0]) & (v[:, 0] / S <= w['x'][1])
    if 'y' in w:
        m &= (v[:, 1] / S >= w['y'][0]) & (v[:, 1] / S <= w['y'][1])
    if 'normal_y_min' in w:
        m &= n[:, 1] >= w['normal_y_min']
    if 'normal_y_max' in w:
        m &= n[:, 1] <= w['normal_y_max']
    if 'normal_z_min' in w:
        m &= n[:, 2] >= w['normal_z_min']
    return m


_RESOLVERS = {
    'landmark_ball': _r_landmark_ball,
    'support_gap': _r_support_gap,
    'feature_search': _r_feature_search,
    # 'ring_sector' is handled in _resolve_left, because it needs the limb frame built
    # from two rings rather than from its own arguments.
}
