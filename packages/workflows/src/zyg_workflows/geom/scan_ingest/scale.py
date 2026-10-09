# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""STAGE b — SCALE. THE STAGE THAT REFUSES TO GUESS.

Moved verbatim out of the old single-file scan_ingest.py (lines 693-836).
"""

import time
import numpy as np

from zyg_workflows.geom.scan_ingest.constants import (
    MAX_REPROJ_ERROR_PX,
    MIN_TRACK_LENGTH,
    SCHEMA,
    ScanIngestError,
    VALID_SCALE_KINDS,
)
from zyg_workflows.geom.scan_ingest.helpers import (
    _atomic_json,
    _log,
    _read_json,
    _stage_path,
)


# ==================================================================================
# STAGE b — SCALE. THE STAGE THAT REFUSES TO GUESS.
# ==================================================================================
def stage_scale(out_dir, scale, *, verbose=True):
    """Turn the SfM reconstruction's arbitrary units into metres, from a DECLARED input.

    SfM solves the scene up to a similarity: a body twice as large photographed from twice
    as far is pixel-identical. Scale is not recoverable from the photographs and this
    function will not invent it. `scale` must be a dict with a 'kind' from
    VALID_SCALE_KINDS, a 'value', and a 'source' string saying who measured it and how:

      stature_m         value = the subject's measured standing stature in metres. The
                        scan's own stature is taken as the robust extent (p0.5..p99.5)
                        along the point cloud's principal axis, which for a standing
                        subject is the vertical. This is only as good as the cloud's
                        completeness — if the feet or the crown did not reconstruct, the
                        extent is short and the whole scan comes out too big. The measured
                        extent is reported so that can be checked.
      point_pair_m      value = the real distance in metres between two reconstructed
                        points, given as scale['point3d_ids'] = [a, b]. This is the scale
                        bar in frame: pick the two ends of the ruler.
      camera_baseline_m value = the real distance in metres between two camera positions,
                        given as scale['images'] = ['a.jpg', 'b.jpg'].
      explicit_factor   value = the multiplier itself, for a re-run whose factor is
                        already known.

    Diurnal stature variation in one person is 14.4-19.3 mm, so a stature_m declaration
    without a time of day is a ~1 % scale uncertainty; that is fine for a detail harvest
    and would not be fine for a dimensional claim. This module never makes a dimensional
    claim off a scan.
    """
    sfm = _read_json(_stage_path(out_dir, 'sfm'), 'sfm')
    if not isinstance(scale, dict):
        raise ScanIngestError(
            'no scale declaration. Photogrammetry cannot recover scale — SfM solves the '
            'scene up to an unknown similarity transform — and this module will not guess '
            'one. Pass scale={"kind": one of %s, "value": ..., "source": "..."}. '
            'A silently mis-scaled scan corrupts every measurement downstream and is '
            'invisible while it does it.' % (VALID_SCALE_KINDS,)
        )
    kind = scale.get('kind')
    if kind not in VALID_SCALE_KINDS:
        raise ScanIngestError('scale kind %r is not one of %s' % (kind, VALID_SCALE_KINDS))
    try:
        value = float(scale.get('value'))
    except (TypeError, ValueError) as exc:
        raise ScanIngestError('scale["value"] must be a number, got %r' % (scale.get('value'),)) from exc
    if not np.isfinite(value) or value <= 0:
        raise ScanIngestError('scale["value"] must be finite and positive, got %r' % value)
    if not str(scale.get('source') or '').strip():
        raise ScanIngestError(
            'scale["source"] must say who measured this and how. A scale '
            'with no provenance is a guess with a decimal point.'
        )

    d = np.load(sfm['points_npz'])
    xyz, trk, err = d['xyz'], d['track_length'], d['error']
    keep = (trk >= MIN_TRACK_LENGTH) & (err <= MAX_REPROJ_ERROR_PX)
    P = xyz[keep] if keep.sum() >= 50 else xyz
    if len(P) < 20:
        raise ScanIngestError('only %d usable sparse points; nothing to scale.' % len(P))

    measured, detail = None, {}
    if kind == 'explicit_factor':
        factor = value
    elif kind == 'stature_m':
        c = P.mean(0)
        Q = P - c
        # principal axis of the cloud; for a standing subject this is the body axis
        _, _, Vt = np.linalg.svd(Q, full_matrices=False)
        axis = Vt[0]
        proj = Q @ axis
        measured = float(np.percentile(proj, 99.5) - np.percentile(proj, 0.5))
        detail = {
            'principal_axis': axis.tolist(),
            'extent_units_p0.5_p99.5': measured,
            'caveat': 'robust extent along the cloud principal axis. If the crown or '
            'the feet did not reconstruct this is SHORT and the scan comes '
            'out too large.',
        }
        if measured <= 1e-9:
            raise ScanIngestError('degenerate point cloud extent; cannot apply a stature scale.')
        factor = value / measured
    elif kind == 'point_pair_m':
        ids = scale.get('point3d_ids')
        if not (isinstance(ids, (list, tuple)) and len(ids) == 2):
            raise ScanIngestError('point_pair_m needs scale["point3d_ids"] = [a, b]')
        pid = d['point_id']
        idx = []
        for want in ids:
            hit = np.nonzero(pid == int(want))[0]
            if not len(hit):
                raise ScanIngestError('point3D id %r is not in the reconstruction' % want)
            idx.append(int(hit[0]))
        measured = float(np.linalg.norm(xyz[idx[0]] - xyz[idx[1]]))
        detail = {'point3d_ids': [int(i) for i in ids], 'distance_units': measured}
        if measured <= 1e-9:
            raise ScanIngestError('the two scale points are coincident')
        factor = value / measured
    else:  # camera_baseline_m
        names = scale.get('images')
        if not (isinstance(names, (list, tuple)) and len(names) == 2):
            raise ScanIngestError('camera_baseline_m needs scale["images"] = [a, b]')
        centres = {c['name']: np.asarray(c['centre'], np.float64) for c in sfm['cameras'].values()}
        for n in names:
            if n not in centres:
                raise ScanIngestError(
                    'image %r is not registered in the reconstruction '
                    '(registered: %d of %d)' % (n, sfm['images_registered'], sfm['images_found'])
                )
        measured = float(np.linalg.norm(centres[names[0]] - centres[names[1]]))
        detail = {'images': list(names), 'baseline_units': measured}
        if measured <= 1e-9:
            raise ScanIngestError('the two named cameras are at the same position')
        factor = value / measured

    if not np.isfinite(factor) or factor <= 0:
        raise ScanIngestError('computed scale factor is not usable: %r' % factor)

    doc = {
        'schema': SCHEMA,
        'stage': 'scale',
        'status': 'ok',
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'kind': kind,
        'declared_value': value,
        'declared_source': scale.get('source'),
        'measured_in_scan_units': measured,
        'factor_units_to_m': float(factor),
        'detail': detail,
        'note': 'scale is DECLARED, never inferred. The rigid alignment in stage '
        '"align" is rotation+translation only and must never solve for scale: '
        'that would launder our cage proportions into the scan and read them '
        'back as if observed.',
    }
    _atomic_json(_stage_path(out_dir, 'scale'), doc)
    _log(
        verbose,
        'scale: %s -> factor %.6g units/m^-1 (measured %s)'
        % (kind, factor, 'n/a' if measured is None else '%.6g' % measured),
    )
    return doc
