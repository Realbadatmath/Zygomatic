# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The subcostal angle and the carrying angle."""

from zyg_workflows.geom.form.angles.base import (
    BANDS,
    CV,
    FEATURE_MIN_CONTRAST,
    FEATURE_MIN_FRAC,
    FEATURE_PROBE_RADIUS,
    LMK,
    MS,
    _CACHE,
    _context,
    _skin_mask,
    _spread,
    _unresolved,
    math,
    np,
)
from zyg_workflows.geom.form.angles.face import (
    _lm_frac,
)

import logging as _zyg_logging_local

_zyg_log = _zyg_logging_local.getLogger('zyg_workflows.geom.form.angles')


# ---------------------------------------------------------------------------------
# (3) SUBCOSTAL ANGLE — UNRESOLVED, with a relief sweep and a vocabulary count
# ---------------------------------------------------------------------------------
def subcostal_angle(v, faces, landmarks=None, phenotype=None, local_changes=None, probe=True):
    """The angle between the two costal margins at the xiphoid. UNRESOLVED, measured twice.

    AFS p.13 puts it at about 90 degrees on the male and about 60 on the female. A 30 degree
    separation on a quantity no ANSUR column touches is a real dimorphism signal and it is
    why the costal margin earns a place on the sculpt-layer priority list.

    IT NEEDS A COSTAL MARGIN, AND THERE ISN'T ONE. Three independent measurements say so:

      * landmarks.py already reports tenth_rib UNRESOLVED, in those words: "the tenth rib is
        palpated, not seen: this cage has no costal margin, and no MakeHuman target names
        it", and records that the nearest shipped ring (measure-underbust-circ-incr) sits
        0.062 of stature above the ANSUR tenth-rib height.
      * VOCABULARY, measured here: of anny's 256 local-change labels, the substrings
        'costal', 'rib', 'xiph', 'sternum' and 'thorax' match ZERO targets. There is nothing
        to anchor to even before geometry is consulted.
      * RELIEF, measured here when probe=True: the subcostal window is swept with geodesic
        balls at the radius curvature.relief_null was measured at, and the strongest relief
        in it is reported against that null's p99 on BOTH magnitude and contrast. This is
        the same test regions.py applies to the clavicle and the scapular spine, run here so
        the negative is checkable rather than inherited.

    And even a resolved margin would not be enough: the angle needs the margin as a LINE on
    each side meeting at a vertex, not a patch. That is stated so nobody reads a future
    "the relief probe found something" as "the subcostal angle is now measurable".
    """
    ctx = _context(v, faces, landmarks, phenotype, local_changes)
    v, fz, S, nrm = ctx['v'], ctx['fz'], ctx['S'], ctx['n']

    labels = _local_change_labels()
    vocab = {kw: [n for n in labels if kw in n.lower()] for kw in ('costal', 'rib', 'xiph', 'sternum', 'thorax')}

    ev = {
        'vocabulary_size': len(labels),
        'vocabulary_matches': vocab,
        'landmarks_py_says': {
            'tenth_rib': ctx['lm']['tenth_rib']['confidence'],
            'tenth_rib_note': ctx['lm']['tenth_rib']['note'],
        },
        'band': dict(BANDS['subcostal_angle']),
    }

    if probe:
        # The subcostal window: anterior lower thorax, between the omphalion and the bust
        # ring, both RESOLVED landmarks, so the window travels with a 1.52 m child instead
        # of being a fixed band. Anterior-facing only.
        lo, why_lo = _lm_frac(ctx, 'omphalion')
        hi, why_hi = _lm_frac(ctx, 'bust_ring')
        if lo is None or hi is None:
            ev['relief_probe'] = {'skipped': (why_lo or why_hi)}
        else:
            win = np.nonzero(
                (fz > lo) & (fz < hi) & (nrm[:, 1] < -0.2) & (np.abs(v[:, 0]) / S < 0.13) & _skin_mask(v, ctx['faces'])
            )[0]
            ev['relief_probe'] = _relief_sweep(ctx, win, 'protrusion')
            ev['relief_probe']['window'] = {
                'fz': [lo, hi],
                'anchor': 'omphalion to bust_ring, both resolved landmarks',
                'normal_y_max': -0.2,
                'xabs_over_stature_max': 0.13,
            }

    got = ev.get('relief_probe', {})
    return _unresolved(
        "the subcostal angle needs a costal margin. anny's 256-label vocabulary matches "
        'ZERO targets for costal/rib/xiph/sternum/thorax; landmarks.py reports tenth_rib '
        'UNRESOLVED for the same reason; and a relief sweep of the subcostal window %s. '
        'A margin would in any case have to resolve as a LINE on each side, not a patch, '
        'before an angle between the two could be measured.' % (got.get('summary', 'was not run')),
        **ev,
    )


def _relief_sweep(ctx, window_idx, polarity):
    """Sweep a window of skin for a genuine protrusion or depression, against the cage's own
    relief null. Same test regions._r_feature_search applies, reimplemented here rather than
    imported because regions.py's version is bound to its authored table and to the neutral
    cage; this one runs on any body. The THRESHOLDS are imported from curvature.py, not
    restated, so the two cannot drift apart."""
    v, faces, S = ctx['v'], ctx['faces'], ctx['S']
    if not len(window_idx):
        return {'n_window': 0, 'summary': 'found no vertices in the window at all'}
    areas = CV.mixed_voronoi_area(v, faces)
    normals = ctx['n']
    sgn = 1.0 if polarity == 'protrusion' else -1.0
    best = None
    n_probed = 0
    n_hits = 0
    for i in window_idx:
        try:
            g = CV.geodesic_ball(v, faces, np.atleast_1d(i), FEATURE_PROBE_RADIUS, S)
            r = CV.region_relief(v, faces, g, stature_m=S, areas=areas, normals=normals)
        except ValueError as _exc:
            _zyg_log.debug('feature probe skipped on this vertex: %s', _exc)
            continue
        n_probed += 1
        score = sgn * r['relief_frac_stature']
        if score >= FEATURE_MIN_FRAC and sgn * r['contrast'] >= FEATURE_MIN_CONTRAST:
            n_hits += 1
        if best is None or score > best[0]:
            best = (score, int(i), r)
    if best is None:
        return {
            'n_window': int(len(window_idx)),
            'n_probed': 0,
            'summary': 'produced no usable collar anywhere in the window',
        }
    _, vid, r = best
    out = {
        'n_window': int(len(window_idx)),
        'n_probed': int(n_probed),
        'n_clearing_null_p99': int(n_hits),
        'polarity': polarity,
        'probe_radius_frac_stature': FEATURE_PROBE_RADIUS,
        'threshold_frac_stature': FEATURE_MIN_FRAC,
        'threshold_contrast': FEATURE_MIN_CONTRAST,
        'threshold_source': 'p99 of curvature.relief_null on this cage',
        'best_vertex': vid,
        'best_relief_mm': float(r['relief_mm']),
        'best_relief_frac_stature': float(r['relief_frac_stature']),
        'best_contrast': float(r['contrast']),
        'best_frac_stature': float(ctx['fz'][vid]),
        'best_xyz_mm': [round(float(x) * 1000.0, 2) for x in v[vid]],
    }
    out['summary'] = (
        "probed %d of %d vertices and found %d clearing the cage's own relief p99; the "
        'strongest is %+.2f mm at contrast %+.2f against a required %+.2f mm and %.2f'
        % (
            n_probed,
            len(window_idx),
            n_hits,
            out['best_relief_mm'],
            out['best_contrast'],
            sgn * FEATURE_MIN_FRAC * S * 1000.0,
            FEATURE_MIN_CONTRAST,
        )
    )
    return out


def _local_change_labels():
    if 'labels' in _CACHE:
        return _CACHE['labels']
    m = MS._model()
    for attr in ('local_change_labels', 'local_changes_labels', 'morph_labels'):
        if hasattr(m, attr):
            _CACHE['labels'] = [str(x) for x in getattr(m, attr)]
            return _CACHE['labels']
    raise AttributeError(
        'the anny model exposes no local-change label list, so the absence '
        'of a target cannot be demonstrated rather than assumed'
    )


# ---------------------------------------------------------------------------------
# (4) CARRYING ANGLE — value and DIRECTION resolved, the printed band is not
# ---------------------------------------------------------------------------------
def carrying_angle(v, faces, phenotype=None, local_changes=None):
    """Humerus against forearm. The SEX DIRECTION resolves; the 5-15 degree band does not.

    AFS p.176 gives 5-15 degrees with female greater than male, and the sex term is a
    direction test with no threshold in it — which is the strongest kind of claim in this
    file, because there is nothing to tune.

    THE BAND HAS TWO POSE PRECONDITIONS AND THIS CAGE FAILS BOTH.
      * EXTENSION. The carrying angle is defined with the elbow straight; it is not
        conserved through flexion. MEASURED on the anny neutral, the A-pose elbow is flexed
        38.3 degrees. A number taken at 38 degrees of flexion is not the quantity the band
        bounds, whatever it comes out as.
      * SUPINATION. regions.py measured that "the cage's forearm carries no pronation state
        we can read", so the second precondition cannot even be checked, let alone met.
    A third problem is ours rather than the pose's: the decomposition into a flexion and a
    carrying component needs the elbow FLEXION AXIS, and the best anchor this cage offers
    for it — the major principal direction of the elbow joint-line ring (20 vertices per
    side), taken in the plane perpendicular to the humerus — sits 11.19 degrees off the
    normal of the plane the two segment axes actually span (MEASURED on the neutral, and
    reported per body as 'flexion_axis_error_deg'). At 38 degrees of flexion an 11 degree
    error in that axis is worth about 7 degrees of carrying angle, which is most of the
    band. So the two operationalisations below disagree in SIGN: +3.93 for the coronal
    projection against -6.99 for the decomposition, on the same neutral mesh.

    WHAT SURVIVES, AND WHY. Every body this pipeline issues stands in the SAME rest pose
    (none of them carries pose parameters), so the pose error and the axis error are
    common-mode across characters. A COMPARISON between two of our bodies is therefore
    meaningful even though neither absolute number is. That is what direction_test() in the
    CLI reports, and it is the only part of AFS p.176 this cage can honestly answer.

    Sign: POSITIVE is valgus — the distal forearm deviates LATERALLY from the humerus axis,
    which is the anatomical sense of a carrying angle.
    """
    ctx = _context(v, faces, None, phenotype, local_changes)
    try:
        kp = LMK._coco(phenotype, local_changes)
    except Exception as e:  # noqa: BLE001
        return _unresolved("anny's joint-centre regressor could not be evaluated: %s" % e)
    v = ctx['v']
    adj = _adjacency(ctx['faces'], len(v))
    try:
        idx, _ = MS._morph_support('measure-lowerarm-length-incr', 3e-4)
    except RuntimeError as e:
        return _unresolved('the elbow joint line needs the forearm-length target: %s' % e)
    mask = np.zeros(len(v), bool)
    mask[idx] = True
    ring_all = np.nonzero(mask & (adj.dot((~mask).astype(np.float64)) > 0))[0]

    per = {}
    for side, sgn in (('left', +1.0), ('right', -1.0)):
        sh = np.asarray(kp[side + '_shoulder'], np.float64)
        el = np.asarray(kp[side + '_elbow'], np.float64)
        wr = np.asarray(kp[side + '_wrist'], np.float64)
        u = el - sh
        f = wr - el
        if np.linalg.norm(u) <= 0 or np.linalg.norm(f) <= 0:
            return _unresolved('the %s arm has a degenerate segment' % side)
        u = u / np.linalg.norm(u)
        f = f / np.linalg.norm(f)
        ring = ring_all[v[ring_all, 0] * sgn > 1e-6]
        if len(ring) < 6:
            return _unresolved('the %s elbow joint line resolved to %d vertices' % (side, len(ring)))
        P = v[ring] - v[ring].mean(0)
        P = P - np.outer(P @ u, u)
        w, V = np.linalg.eigh(np.cov(P.T))
        e = V[:, int(np.argmax(w))]
        if e[0] * sgn < 0:  # +x is subject LEFT; lateral for that arm
            e = -e
        e = e - (e @ u) * u
        e = e / np.linalg.norm(e)
        nn = np.cross(u, e)

        # how far the ring-derived axis is from the normal of the plane the two segment axes
        # span: this is the error term, measured per body rather than claimed once
        pl = np.cross(u, f)
        pl_n = np.linalg.norm(pl)
        axis_err = None if pl_n <= 1e-9 else math.degrees(math.acos(float(np.clip(abs(e @ (pl / pl_n)), -1.0, 1.0))))

        flex = math.degrees(math.atan2(float(f @ nn), float(f @ u)))
        decomposed = math.degrees(math.asin(float(np.clip(f @ e, -1.0, 1.0))))
        # coronal projection: no flexion axis needed, so no axis error — but foreshortened
        # by the flexion that is there
        hx = np.array([el[0] - sh[0], el[2] - sh[2]])
        fx = np.array([wr[0] - el[0], wr[2] - el[2]])
        coronal = math.degrees(math.atan2(fx[0] * sgn, -fx[1])) - math.degrees(math.atan2(hx[0] * sgn, -hx[1]))
        per[side] = {
            'coronal_projection_deg': coronal,
            'decomposed_deg': decomposed,
            'elbow_flexion_deg': abs(flex),
            'total_humerus_forearm_deg': math.degrees(math.acos(float(np.clip(u @ f, -1.0, 1.0)))),
            'flexion_axis': [float(x) for x in e],
            'flexion_axis_error_deg': axis_err,
            'ring_vertices': int(len(ring)),
            'ring_principal_spreads_mm': [float(x) for x in np.sqrt(np.abs(w)) * 1000.0],
            'humerus_mm': float(np.linalg.norm(el - sh) * 1000.0),
            'forearm_mm': float(np.linalg.norm(wr - el) * 1000.0),
        }

    ops = {
        'coronal_projection': float(np.mean([per[s]['coronal_projection_deg'] for s in per])),
        'decomposed_ring_axis': float(np.mean([per[s]['decomposed_deg'] for s in per])),
    }
    spread = _spread(ops.values())
    width = BANDS['carrying_angle']['width_deg']
    flexion = float(np.mean([per[s]['elbow_flexion_deg'] for s in per]))

    rec = {
        'resolved': False,
        'value_deg': None,
        'primary_deg': ops['coronal_projection'],
        'operationalisations': ops,
        'operationalisation_spread_deg': spread,
        'band_width_deg': width,
        'per_side': per,
        'claim': 'constructed',
        'elbow_flexion_deg': flexion,
        'preconditions': {
            'elbow_extended': {
                'required_by': 'AFS p.176 (the angle is defined at full extension)',
                'met': False,
                'measured': 'the A-pose elbow is flexed %.1f degrees' % flexion,
            },
            'forearm_supinated': {
                'required_by': 'AFS p.176',
                'met': None,
                'measured': 'UNREADABLE — regions.py measured that this cage carries no pronation state on the forearm',
            },
        },
        'band': dict(BANDS['carrying_angle']),
        'direction_claim': 'female > male — a DIRECTION test with no threshold, valid '
        'between our own bodies because they share one rest pose so the '
        'pose error is common-mode. See --characters.',
        'sign_convention': 'POSITIVE is valgus: the distal forearm deviates LATERALLY.',
        'reason': (
            'the printed 5-15 degree band is out of domain on this mesh. Its two '
            'preconditions fail (the elbow is flexed %.1f degrees; supination is '
            'unreadable), and the two defensible operationalisations disagree by %.1f '
            'degrees against a band width of %.0f — they do not even agree on the sign. '
            'The DIRECTION half of AFS p.176 is answerable and is reported instead.' % (flexion, spread, width)
        ),
    }
    return rec


def _adjacency(faces, n):
    key = ('adj', int(np.asarray(faces).shape[0]), int(n))
    if key not in _CACHE:
        _CACHE[key] = CV.vertex_adjacency(faces, n)
    return _CACHE[key]
