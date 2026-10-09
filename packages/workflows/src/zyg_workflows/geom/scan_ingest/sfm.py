# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""STAGE a — SPARSE STRUCTURE FROM MOTION.

Moved verbatim out of the old single-file scan_ingest.py (lines 523-692).
"""

import glob
import os
import time
import numpy as np
import logging as _zyg_logging

from zyg_workflows.geom.scan_ingest.constants import (
    MAX_REPROJ_ERROR_PX,
    MIN_TRACK_LENGTH,
    SCHEMA,
    ScanIngestError,
)
from zyg_workflows.geom.scan_ingest.helpers import (
    _atomic_json,
    _log,
    _maybe_call,
    _stage_path,
    _try_mvconsist,
    _try_pycolmap,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.geom.scan_ingest')


# ==================================================================================
# STAGE a — SPARSE STRUCTURE FROM MOTION
# ==================================================================================
def stage_sfm(photo_dir, out_dir, *, max_features=8192, matcher='auto', verbose=True):
    """Sparse reconstruction: SIFT -> matching -> incremental mapping. CPU only.

    pycolmap reports has_cuda = False on this machine, so feature extraction and matching
    both run with use_gpu = False. Exhaustive matching is O(n^2) in frames: 2,556 pairs at
    72 images, 4,950 at 100. matcher='auto' uses exhaustive up to 80 images and sequential
    (with loop detection off, since we have no vocabulary tree) above that — a walkaround
    is a sequence, so sequential loses little and costs much less.

    Writes out_dir/sfm/{database.db, sparse/}, plus points.npz holding the triangulated
    points with their track lengths and reprojection errors so later stages never have to
    re-open the reconstruction to filter them.
    """
    pc = _try_pycolmap()
    t0 = time.time()
    photo_dir = os.path.abspath(photo_dir)
    if not os.path.isdir(photo_dir):
        raise ScanIngestError('photo_dir does not exist: %s' % photo_dir)
    exts = ('*.jpg', '*.jpeg', '*.JPG', '*.JPEG', '*.png', '*.PNG', '*.tif', '*.tiff')
    images = sorted(sum([glob.glob(os.path.join(photo_dir, e)) for e in exts], []))
    if len(images) < 8:
        raise ScanIngestError(
            'only %d images in %s. A body walkaround needs 60-100 '
            'frames (docs/photogrammetry_capture.md §3.1); below ~8 '
            'there is nothing to reconstruct.' % (len(images), photo_dir)
        )

    sfm_dir = os.path.join(out_dir, 'sfm')
    sparse_dir = os.path.join(sfm_dir, 'sparse')
    os.makedirs(sparse_dir, exist_ok=True)
    db_path = os.path.join(sfm_dir, 'database.db')
    if os.path.exists(db_path):
        os.remove(db_path)

    xopts = pc.FeatureExtractionOptions()
    xopts.use_gpu = False
    try:
        xopts.sift.max_num_features = int(max_features)
    except Exception as _exc:  # pragma: no cover
        _zyg_log.warning('sift.max_num_features could not be set, using the pycolmap default: %s', _exc)
    _log(verbose, 'SIFT over %d images (CPU, max_num_features=%d)' % (len(images), max_features))
    pc.extract_features(
        database_path=db_path,
        image_path=photo_dir,
        camera_mode=pc.CameraMode.AUTO,
        extraction_options=xopts,
        device=pc.Device.cpu,
    )

    mopts = pc.FeatureMatchingOptions()
    mopts.use_gpu = False
    use_exhaustive = matcher == 'exhaustive' or (matcher == 'auto' and len(images) <= 80)
    _log(verbose, 'matching (%s, CPU)' % ('exhaustive' if use_exhaustive else 'sequential'))
    if use_exhaustive:
        pc.match_exhaustive(database_path=db_path, matching_options=mopts, device=pc.Device.cpu)
    else:
        pc.match_sequential(database_path=db_path, matching_options=mopts, device=pc.Device.cpu)

    _log(verbose, 'incremental mapping')
    recs = pc.incremental_mapping(database_path=db_path, image_path=photo_dir, output_path=sparse_dir)
    if not recs:
        raise ScanIngestError(
            'incremental mapping produced no reconstruction from %d images. The usual '
            'causes, in order: featureless or repeating background, too large an angular '
            'step between frames, motion blur, or a flash (a light that travels with the '
            'camera changes the shading in every frame). See '
            'docs/photogrammetry_capture.md §4.' % len(images)
        )

    def _nreg(r):
        return int(_maybe_call(r.num_reg_images))

    best_id = max(recs, key=lambda k: _nreg(recs[k]))
    rec = recs[best_id]
    if len(recs) > 1:
        _log(
            verbose,
            'WARNING: SfM split into %d disconnected models; taking the largest '
            '(%d of %d images registered). A split model normally means the '
            'walkaround lost track.' % (len(recs), _nreg(rec), len(images)),
        )

    ids = sorted(rec.points3D.keys())
    xyz = np.array([rec.points3D[i].xyz for i in ids], np.float64) if ids else np.zeros((0, 3))
    err = np.array([rec.points3D[i].error for i in ids], np.float64) if ids else np.zeros(0)
    trk = np.array([rec.points3D[i].track.length() for i in ids], np.int64) if ids else np.zeros(0, np.int64)
    pid = np.array(ids, np.int64)

    cams = {}
    for im_id in rec.reg_image_ids():
        im = rec.image(im_id)
        cfw = _maybe_call(im.cam_from_world)
        R = np.asarray(_maybe_call(_maybe_call(cfw.rotation).matrix), np.float64)
        t = np.asarray(_maybe_call(cfw.translation), np.float64)
        cams[str(im_id)] = {
            'name': im.name,
            'camera_id': int(im.camera_id),
            'R_cam_from_world': R.tolist(),
            't_cam_from_world': t.tolist(),
            'centre': (-R.T @ t).tolist(),
        }
    cam_models = {
        str(c.camera_id): {
            'model': c.model_name,
            'width': int(c.width),
            'height': int(c.height),
            'params': [float(p) for p in c.params],
        }
        for c in rec.cameras.values()
    }

    np.savez_compressed(os.path.join(sfm_dir, 'points.npz'), point_id=pid, xyz=xyz, error=err, track_length=trk)

    mv = _try_mvconsist()
    mv_report = None
    if mv is not None:
        try:
            mv_report = mv(photo_dir)
            _log(verbose, 'geom.mvconsist.measure() present — recorded alongside, not gated on')
        except Exception as e:
            mv_report = {'status': 'error', 'error': repr(e)}

    keep = (trk >= MIN_TRACK_LENGTH) & (err <= MAX_REPROJ_ERROR_PX)
    doc = {
        'schema': SCHEMA,
        'stage': 'sfm',
        'status': 'ok',
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'photo_dir': photo_dir,
        'images_found': len(images),
        'images_registered': _nreg(rec),
        'registration_fraction': float(_nreg(rec)) / len(images),
        'models_produced': len(recs),
        'model_split': len(recs) > 1,
        'num_points3D': int(len(ids)),
        'mean_track_length': float(trk.mean()) if len(trk) else 0.0,
        'mean_reprojection_error_px': float(err.mean()) if len(err) else 0.0,
        'points_passing_quality_filter': int(keep.sum()),
        'quality_filter': {'min_track_length': MIN_TRACK_LENGTH, 'max_reprojection_error_px': MAX_REPROJ_ERROR_PX},
        'matcher': 'exhaustive' if use_exhaustive else 'sequential',
        'gpu': False,
        'pycolmap_has_cuda': bool(getattr(pc, 'has_cuda', False)),
        'cameras': cams,
        'camera_models': cam_models,
        'sparse_dir': os.path.join(sparse_dir, str(best_id))
        if os.path.isdir(os.path.join(sparse_dir, str(best_id)))
        else sparse_dir,
        'points_npz': os.path.join(sfm_dir, 'points.npz'),
        'mvconsist': mv_report,
        'seconds': round(time.time() - t0, 1),
        'note': 'reconstruction is up to an unknown SIMILARITY transform. Nothing in this artefact is in metres.',
    }
    _atomic_json(_stage_path(out_dir, 'sfm'), doc)
    _log(
        verbose,
        'sfm: %d/%d images registered, %d points (%d pass filter), %.0fs'
        % (
            doc['images_registered'],
            doc['images_found'],
            doc['num_points3D'],
            doc['points_passing_quality_filter'],
            doc['seconds'],
        ),
    )
    return doc
