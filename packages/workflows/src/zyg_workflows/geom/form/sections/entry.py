# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sections.entry — evaluate() and the synthetic self-test controls.

Moved verbatim from geom/form/sections.py; no logic, numbers or comments changed.
"""

import numpy as np

from .constants import (
    ENV_FLAG,
    ENV_FLAG_DEFAULT,
    HEXAGON_CIRCULARITY,
    HOUSE,
    LMK,
    NOT_APPLICABLE,
    RELIEF_NULL_FRAC,
    SCHEMA,
    enabled,
)

from .primitives import (
    _ORDER,
    _frame,
    _hull_gaps,
    _polygon_area,
    _res,
    _shape_family,
    _split_front_back,
)

from .torso import (
    t5_torso_sections,
)

from .neck import (
    t5_neck_section,
)

from .limbs import (
    t5_calf_asymmetry,
    t5_leg_counter_curve,
)

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def evaluate(v, faces, *, lm=None, phenotype=None, local_changes=None, sex=None, name=None):
    """All four gates on one mesh. Returns a JSON-serialisable report."""
    v = np.asarray(v, np.float64)
    zmin, H = _frame(v)
    meta = {
        'schema': SCHEMA,
        'name': name,
        'sex': sex,
        'stature_m': H,
        'relief_null_mm': RELIEF_NULL_FRAC * H * 1000,
        'flag': ENV_FLAG,
        'flag_default': ENV_FLAG_DEFAULT,
        'enabled': enabled(),
    }
    if not enabled():
        na = _res(
            NOT_APPLICABLE,
            'all section gates',
            'n/a',
            HOUSE,
            '%s is set to 0, so this module is disabled and no geometry was touched' % ENV_FLAG,
        )
        return {
            'meta': meta,
            'gates': {
                k: {'gate': k, 'status': NOT_APPLICABLE, 'claims': {'disabled': na}}
                for k in ('t5_torso_sections', 't5_neck_section', 't5_leg_counter_curve', 't5_calf_asymmetry')
            },
        }
    if lm is None:
        lm = LMK.resolve_landmarks(v, faces, phenotype, local_changes)
    gates = {
        't5_torso_sections': t5_torso_sections(v, faces, lm, H, zmin),
        't5_neck_section': t5_neck_section(v, faces, phenotype, local_changes, sex, H, zmin),
        't5_leg_counter_curve': t5_leg_counter_curve(v, faces, lm, phenotype, local_changes, H, zmin),
        't5_calf_asymmetry': t5_calf_asymmetry(v, faces, phenotype, local_changes, H, zmin),
    }
    meta['status'] = min([g['status'] for g in gates.values()], key=lambda s: _ORDER.get(s, 9))
    return {'meta': meta, 'gates': gates}


# =================================================================================
# controls — a predicate that has never failed anything is not calibrated
# =================================================================================
def _synth(kind, n=84, aspect=1.0):
    """Synthetic closed sections with known answers, sampled at a cage-like point count."""
    t = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    if kind == 'circle':
        xy = np.stack([np.cos(t), np.sin(t)], axis=1)
    elif kind == 'hexagon':
        # a regular hexagon traced at constant arc length
        s = np.linspace(0.0, 6.0, n, endpoint=False)
        k = np.floor(s).astype(int) % 6
        f = s - np.floor(s)
        ang = 2.0 * np.pi * np.arange(7) / 6.0
        vtx = np.stack([np.cos(ang), np.sin(ang)], axis=1)
        xy = vtx[k] + f[:, None] * (vtx[k + 1] - vtx[k])
    elif kind in ('flat_back', 'flat_front'):
        # One half is a semicircle, the other is a super-ellipse lid that is straight over
        # 80% of its span. 'flat_back' is the NEGATIVE control for "the front is flatter":
        # the flat side is the posterior one, so the predicate must say FAIL. 'flat_front'
        # is the same shape reflected and must say PASS. A predicate that cannot produce
        # both answers on these two is not a predicate.
        m = n // 2
        ta = np.linspace(np.pi, 2.0 * np.pi, m, endpoint=False)
        round_half = np.stack([np.cos(ta), np.sin(ta)], axis=1)
        xf = np.cos(np.linspace(0.0, np.pi, n - m, endpoint=False))
        flat_half = np.stack([xf, 0.5 * (1.0 - np.abs(xf) ** 8) ** (1.0 / 8.0)], axis=1)
        xy = np.concatenate([round_half, flat_half], axis=0)
        if kind == 'flat_front':
            xy = xy * np.array([1.0, -1.0])
    elif kind == 'cleft_disc':
        r = 1.0 - 0.25 * np.exp(-(((np.cos(t - np.pi / 2) - 1.0) / 0.12) ** 2))
        xy = np.stack([r * np.cos(t), r * np.sin(t)], axis=1)
    else:
        raise ValueError(kind)
    xy[:, 0] *= aspect
    return xy


def self_test(verbose=True):
    """Prove the predicates discriminate, on shapes whose answers are known in advance.

    The plan's calibration policy is explicit that a gate which has never failed anything is
    not calibrated. These are the deliberately broken controls for the three predicates that
    carry a verdict.
    """
    out = {}
    circ = _synth('circle')
    hexa = _synth('hexagon')
    fc = _shape_family(circ)
    fh = _shape_family(hexa)
    out['circle_prefers_circle'] = (
        not fc['hexagon_beats_circle'],
        fc['best_order'],
        fc['residual_circle'],
        fc['hexagon_residual'],
    )
    out['hexagon_prefers_hexagon'] = (
        fh['hexagon_beats_circle'],
        fh['best_order'],
        fh['residual_circle'],
        fh['hexagon_residual'],
    )
    # The N-gons carry one free parameter the circle does not (a rotation), so the family
    # could in principle beat a circle on a circle by chance. Measured here rather than
    # argued: on a perfect circle the best polygon in the family is WORSE than the circle by
    # this much, so the extra parameter buys the polygons nothing and the hexagon-versus-
    # circle comparison is not stacked.
    out['ngon_best_minus_circle_on_a_circle'] = min(fc['residual_by_order'].values()) - fc['residual_circle']
    ac = 4 * np.pi * _polygon_area(circ) / float(np.linalg.norm(np.roll(circ, -1, axis=0) - circ, axis=1).sum()) ** 2
    ah = 4 * np.pi * _polygon_area(hexa) / float(np.linalg.norm(np.roll(hexa, -1, axis=0) - hexa, axis=1).sum()) ** 2
    out['circularity_circle'] = ac
    out['circularity_hexagon'] = ah
    out['circularity_ceiling_separates'] = bool(ah <= HEXAGON_CIRCULARITY + 1e-6 and ac > HEXAGON_CIRCULARITY)
    g, _ = _hull_gaps(circ, 1e-3)
    gc, _ = _hull_gaps(_synth('cleft_disc'), 1e-3)
    out['circle_has_no_concavity'] = g['n_resolved'] == 0
    out['cleft_disc_has_one'] = (gc['n_resolved'] == 1, gc['n_resolved'])
    fb = _split_front_back(_synth('flat_back'))
    out['flat_back_fails_front_flatter'] = (
        not (fb['front']['median_norm_curvature'] < fb['back']['median_norm_curvature']),
        round(fb['front']['median_norm_curvature'], 4),
        round(fb['back']['median_norm_curvature'], 4),
    )
    ff = _split_front_back(_synth('flat_front'))
    out['flat_front_passes_front_flatter'] = (
        ff['front']['median_norm_curvature'] < ff['back']['median_norm_curvature'],
        round(ff['front']['median_norm_curvature'], 4),
        round(ff['back']['median_norm_curvature'], 4),
    )
    # a straight-line centroid track must not read as a counter-curve
    fr = np.linspace(0.0, 1.0, 25)
    bow = 0.02 * np.sin(np.pi * fr)
    ess = 0.02 * np.sin(2 * np.pi * fr)
    for tag, tr in (('single_bow', bow), ('s_curve', ess)):
        resid = tr - np.interp(fr, [fr[0], fr[-1]], [tr[0], tr[-1]])
        big = np.abs(resid) > 1e-3
        sig = np.sign(resid[big])
        out['track_%s_sign_changes' % tag] = int((np.diff(sig) != 0).sum())
    ok = (
        out['circle_prefers_circle'][0]
        and out['hexagon_prefers_hexagon'][0]
        and out['circularity_ceiling_separates']
        and out['circle_has_no_concavity']
        and out['cleft_disc_has_one'][0]
        and out['flat_back_fails_front_flatter'][0]
        and out['flat_front_passes_front_flatter'][0]
        and out['track_single_bow_sign_changes'] == 0
        and out['track_s_curve_sign_changes'] >= 1
    )
    out['ALL'] = bool(ok)
    if verbose:
        for k in sorted(out):
            _zyg_log.info('  %-38s %s' % (k, out[k]))
    return out
