# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""STAGE c — DENSE.

Moved verbatim out of the old single-file scan_ingest.py (lines 837-1298).
"""

import math
import os
import time
import numpy as np

from zyg_workflows.geom.scan_ingest.constants import (
    DENSE_BBOX_MARGIN,
    DENSE_MAX_POINTS,
    MAX_REPROJ_ERROR_PX,
    MIN_TRACK_LENGTH,
    NORMAL_KNN,
    SCHEMA,
    SGBM_MAX_DISPARITY_PX,
    SGBM_MAX_IMAGE_PX,
    SGBM_MAX_PAIRS,
    SGBM_MAX_TRI_ANGLE_DEG,
    SGBM_MIN_HORIZONTAL_BASELINE,
    SGBM_MIN_TRI_ANGLE_DEG,
    SGBM_RECTIFY_ALPHA,
    ScanIngestError,
)
from zyg_workflows.geom.scan_ingest.helpers import (
    _atomic_json,
    _log,
    _read_json,
    _stage_path,
    _try_cv2,
    _try_pycolmap,
    _try_trimesh,
)


# ==================================================================================
# STAGE c — DENSE
# ==================================================================================
def _camera_K_dist(cam):
    """(K, dist) for a COLMAP camera record, in the cv2 convention.

    Only the models a phone walkaround actually produces are supported. An unsupported
    model raises rather than silently dropping distortion, because dropping distortion
    bends the reconstructed surface and the bend looks like anatomy."""
    m, p = cam['model'], list(map(float, cam['params']))
    K = np.eye(3)
    dist = np.zeros(5)
    if m == 'SIMPLE_PINHOLE':
        f, cx, cy = p
        K[0, 0] = K[1, 1] = f
    elif m == 'PINHOLE':
        fx, fy, cx, cy = p
        K[0, 0], K[1, 1] = fx, fy
    elif m == 'SIMPLE_RADIAL':
        f, cx, cy, k1 = p
        K[0, 0] = K[1, 1] = f
        dist[0] = k1
    elif m == 'RADIAL':
        f, cx, cy, k1, k2 = p
        K[0, 0] = K[1, 1] = f
        dist[0], dist[1] = k1, k2
    elif m == 'OPENCV':
        fx, fy, cx, cy, k1, k2, p1, p2 = p
        K[0, 0], K[1, 1] = fx, fy
        dist[:4] = [k1, k2, p1, p2]
    else:
        raise ScanIngestError(
            'camera model %r is not supported here. Supported: '
            'SIMPLE_PINHOLE, PINHOLE, SIMPLE_RADIAL, RADIAL, OPENCV. '
            'Ignoring an unmodelled distortion bends the surface and '
            'the bend reads as anatomy.' % m
        )
    K[0, 2], K[1, 2] = cx, cy
    return K, dist


def _sgbm_pairs(sfm, out_dir):
    """Image pairs for two-view stereo, chosen off the SfM co-visibility graph.

    Selection is by triangulation angle, which is the thing that actually decides whether
    a two-view depth is conditioned: too small and depth error blows up as 1/sin(theta);
    too large and the two images no longer look alike enough for a block matcher. The
    window here is SGBM_MIN/MAX_TRI_ANGLE_DEG."""
    cams = sfm['cameras']
    ids = sorted(cams.keys(), key=lambda k: cams[k]['name'])
    C = {i: np.asarray(cams[i]['centre'], np.float64) for i in ids}
    centroid = np.mean([C[i] for i in ids], axis=0)
    pairs = []
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            i, j = ids[a], ids[b]
            va, vb = C[i] - centroid, C[j] - centroid
            na, nb = np.linalg.norm(va), np.linalg.norm(vb)
            if na < 1e-9 or nb < 1e-9:
                continue
            ang = math.degrees(math.acos(float(np.clip(va @ vb / (na * nb), -1, 1))))
            if not (SGBM_MIN_TRI_ANGLE_DEG <= ang <= SGBM_MAX_TRI_ANGLE_DEG):
                continue
            # THE BASELINE MUST BE HORIZONTAL IN CAMERA 1. cv2.StereoSGBM searches along
            # image ROWS, and cv2.stereoRectify rectifies along whichever axis the
            # baseline actually lies on. A multi-ring walkaround produces plenty of pairs
            # at the same azimuth and different heights: those have the SMALLEST
            # triangulation angle, so an angle-only ranking puts them first, and they
            # rectify VERTICALLY. Measured on the synthetic run: the top-ranked pair came
            # back with P2[0,3] = 0 and P2[1,3] = 585, every disparity was 0, and the whole
            # dense cloud was garbage that the bbox reject then threw away entirely.
            # Rather than transpose images and rebuild Q, such pairs are simply skipped.
            Ri = np.asarray(cams[i]['R_cam_from_world'], np.float64)
            ti = np.asarray(cams[i]['t_cam_from_world'], np.float64)
            Rj = np.asarray(cams[j]['R_cam_from_world'], np.float64)
            tj = np.asarray(cams[j]['t_cam_from_world'], np.float64)
            T = tj - (Rj @ Ri.T) @ ti
            nt = np.linalg.norm(T)
            if nt < 1e-9 or abs(T[0]) / nt < SGBM_MIN_HORIZONTAL_BASELINE:
                continue
            pairs.append((ang, i, j))
    pairs.sort(key=lambda t: t[0])
    return [(i, j, a) for a, i, j in pairs[:SGBM_MAX_PAIRS]]


def _stereo_pair(cv2, photo_dir, ci, cj, models, sparse_xyz, bbox):
    """One rectified stereo pair -> (world points, colours, camera centre), or None.

    Returns None for every pair this machine cannot usefully match, with the reason
    counted by the caller. The three refusals that matter, all of them learned by
    measurement on the synthetic run rather than assumed:

      * VERTICAL RECTIFICATION. cv2.StereoSGBM searches along image ROWS. A multi-ring
        walkaround produces pairs at the same azimuth and different heights whose baseline
        is vertical; stereoRectify then returns P2[0,3] = 0 and every disparity is 0.
      * WRONG IMAGE ORDER. If the second camera is to the left, the true disparities are
        NEGATIVE and a minDisparity >= 0 search finds nothing. Detected from the sign of
        the sparse cloud's own predicted disparity; the caller retries swapped.
      * SEARCH RANGE. A fixed "quarter of the image width" was the first attempt and it
        failed silently — the true disparities on the synthetic capture were 670-770 px
        against a 224 px window, so the body matched nothing and every surviving point
        came from the background. The range is instead PREDICTED from the sparse cloud
        projected into the rectified pair.
    """
    Ki, di = _camera_K_dist(models[str(ci['camera_id'])])
    Kj, dj = _camera_K_dist(models[str(cj['camera_id'])])
    Ii = cv2.imread(os.path.join(photo_dir, ci['name']), cv2.IMREAD_GRAYSCALE)
    Ij = cv2.imread(os.path.join(photo_dir, cj['name']), cv2.IMREAD_GRAYSCALE)
    if Ii is None or Ij is None or Ii.shape != Ij.shape:
        return None, 'unreadable'
    H, W = Ii.shape
    s = min(1.0, float(SGBM_MAX_IMAGE_PX) / max(H, W))
    if s < 1.0:
        Ii = cv2.resize(Ii, (int(round(W * s)), int(round(H * s))), interpolation=cv2.INTER_AREA)
        Ij = cv2.resize(Ij, (int(round(W * s)), int(round(H * s))), interpolation=cv2.INTER_AREA)
        Ki = Ki.copy()
        Kj = Kj.copy()
        Ki[:2] *= s
        Kj[:2] *= s
        H, W = Ii.shape

    Ri = np.asarray(ci['R_cam_from_world'], np.float64)
    ti = np.asarray(ci['t_cam_from_world'], np.float64)
    Rj = np.asarray(cj['R_cam_from_world'], np.float64)
    tj = np.asarray(cj['t_cam_from_world'], np.float64)
    R = Rj @ Ri.T  # camera j relative to camera i
    T = (tj - R @ ti).reshape(3, 1)
    try:
        R1, R2, P1, P2, Q, _, _ = cv2.stereoRectify(
            Ki, di, Kj, dj, (W, H), R, T, flags=cv2.CALIB_ZERO_DISPARITY, alpha=SGBM_RECTIFY_ALPHA
        )
    except cv2.error:
        return None, 'rectify_failed'
    if abs(P2[0, 3]) < 1e-9:
        return None, 'vertical_baseline'

    Xr = (sparse_xyz @ Ri.T + ti) @ R1.T
    Xr = Xr[Xr[:, 2] > 1e-6]
    if len(Xr) < 30:
        return None, 'no_sparse_support'
    h1 = np.c_[Xr, np.ones(len(Xr))] @ P1.T
    h2 = np.c_[Xr, np.ones(len(Xr))] @ P2.T
    uu1 = h1[:, :2] / h1[:, 2:3]
    uu2 = h2[:, :2] / h2[:, 2:3]
    on = (uu1[:, 0] >= 0) & (uu1[:, 0] < W) & (uu1[:, 1] >= 0) & (uu1[:, 1] < H)
    if on.sum() < 30:
        return None, 'no_sparse_support'
    dsp = (uu1[:, 0] - uu2[:, 0])[on]
    if np.median(dsp) < 0:
        return None, 'wrong_image_order'
    lo_d = int(math.floor(np.percentile(dsp, 1) / 16.0) * 16 - 16)
    nd = int(math.ceil((np.percentile(dsp, 99) - lo_d) / 16.0) * 16) + 16
    if nd > SGBM_MAX_DISPARITY_PX:
        return None, 'search_range_too_wide'
    # cv2.StereoSGBM computes over width - minDisparity - numDisparities columns and does
    # NOT check that this is positive: with minDisparity 720 and numDisparities 256 on a
    # 900 px image it tried to allocate 1.8e19 bytes and threw an OOM. A predicted
    # disparity that eats the image width means the baseline is enormous relative to the
    # subject distance, which is a pair block matching could not have used anyway.
    if lo_d + nd > W - 16 or lo_d <= -W:
        return None, 'disparity_exceeds_image_width'

    m1x, m1y = cv2.initUndistortRectifyMap(Ki, di, R1, P1, (W, H), cv2.CV_32FC1)
    m2x, m2y = cv2.initUndistortRectifyMap(Kj, dj, R2, P2, (W, H), cv2.CV_32FC1)
    r1 = cv2.remap(Ii, m1x, m1y, cv2.INTER_LINEAR)
    r2 = cv2.remap(Ij, m2x, m2y, cv2.INTER_LINEAR)
    sgbm = cv2.StereoSGBM_create(
        minDisparity=lo_d,
        numDisparities=nd,
        blockSize=5,
        P1=8 * 5 * 5,
        P2=32 * 5 * 5,
        disp12MaxDiff=1,
        uniquenessRatio=10,
        speckleWindowSize=100,
        speckleRange=2,
        mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY,
    )
    disp = sgbm.compute(r1, r2).astype(np.float32) / 16.0
    pts = cv2.reprojectImageTo3D(disp, Q)
    ok = (disp > lo_d + 0.5) & np.isfinite(pts).all(axis=2)
    if ok.sum() < 500:
        return None, 'too_few_matches'
    Prect = pts[ok].reshape(-1, 3)
    col = r1[ok].reshape(-1, 1).repeat(3, axis=1).astype(np.uint8)
    # rect-cam1 -> world:  X_cam1 = R1^T X_rect ;  X_world = Ri^T (X_cam1 - ti)
    Xw = ((Prect @ R1) - ti) @ Ri
    if bbox is not None:
        lo, hi = bbox
        keepb = np.all((Xw >= lo) & (Xw <= hi), axis=1)
        Xw, col = Xw[keepb], col[keepb]
        if len(Xw) < 200:
            return None, 'bbox_rejected'
    return (Xw, col, np.asarray(ci['centre'], np.float64)), 'ok'


def _sgbm_densify(sfm, out_dir, sparse_xyz, bbox=None, verbose=True):
    """CPU dense stereo. Returns (points Nx3 in SCAN UNITS, viewpoints, colours, stats).

    This is NOT patch-match. pycolmap.patch_match_stereo is CUDA-only and this machine has
    has_cuda = False, so there is no multi-view photometric consistency check, no per-pixel
    view selection and no normal estimation inside the matcher. What this does instead:
    rectify a pair with the poses COLMAP solved, run cv2.StereoSGBM, reproject the
    disparity, and keep the points. Outliers survive that a patch-match run would have
    rejected; the bbox reject here, the Poisson trim, and the shrinkwrap support test
    downstream are what stop them reaching an asset.
    """
    cv2 = _try_cv2()
    if cv2 is None:
        raise ScanIngestError('cv2 is not importable, so the sgbm dense path cannot run.')
    cams, models = sfm['cameras'], sfm['camera_models']
    photo_dir = sfm['photo_dir']
    pairs = _sgbm_pairs(sfm, out_dir)
    if not pairs:
        raise ScanIngestError(
            'no image pair has a triangulation angle in [%.0f, %.0f] deg '
            'with a horizontal baseline. Too small an angular step gives '
            'ill-conditioned depth; too large and block matching fails.'
            % (SGBM_MIN_TRI_ANGLE_DEG, SGBM_MAX_TRI_ANGLE_DEG)
        )
    _log(verbose, 'sgbm over %d pairs' % len(pairs))

    allP, allC, allV = [], [], []
    reasons = {}
    used = 0
    for k, (i, j, _ang) in enumerate(pairs):
        got, why = _stereo_pair(cv2, photo_dir, cams[i], cams[j], models, sparse_xyz, bbox)
        if got is None and why == 'wrong_image_order':
            got, why = _stereo_pair(cv2, photo_dir, cams[j], cams[i], models, sparse_xyz, bbox)
        reasons[why] = reasons.get(why, 0) + 1
        if got is None:
            continue
        Xw, col, Ci = got
        # decimate: SGBM at 1200 px gives ~1e6 points per pair, far more than Poisson wants
        step = max(1, len(Xw) // 40000)
        Xw, col = Xw[::step], col[::step]
        allP.append(Xw)
        allC.append(col)
        allV.append(np.repeat(Ci[None], len(Xw), axis=0))
        used += 1
        if verbose and (k + 1) % 10 == 0:
            _log(
                verbose, '  sgbm pair %d/%d (%d usable, %d pts)' % (k + 1, len(pairs), used, sum(len(a) for a in allP))
            )
    if not allP:
        raise ScanIngestError('no image pair produced a usable disparity map. Reasons: %r' % (reasons,))
    stats = {'pairs_tried': len(pairs), 'pairs_used': used, 'outcomes': reasons}
    return (np.concatenate(allP), np.concatenate(allV), np.concatenate(allC), stats)


def _estimate_normals(P, viewpoints, knn=NORMAL_KNN):
    """Oriented normals by local PCA, flipped toward the camera that observed the point.

    Poisson surface reconstruction needs ORIENTED normals; an unoriented normal field
    produces a surface turned inside out in patches. We do not have to guess the
    orientation: SfM tells us which camera saw each point, so the outward direction is the
    direction back toward that camera."""
    from scipy.spatial import cKDTree

    tree = cKDTree(P)
    k = min(knn, max(3, len(P)))
    _, idx = tree.query(P, k=k, workers=-1)
    Q = P[idx] - P[idx].mean(axis=1, keepdims=True)
    cov = np.einsum('nki,nkj->nij', Q, Q) / max(1, k - 1)
    w, V = np.linalg.eigh(cov)
    N = V[:, :, 0]  # smallest-eigenvalue direction
    to_cam = viewpoints - P
    flip = np.einsum('ij,ij->i', N, to_cam) < 0
    N[flip] *= -1.0
    n = np.linalg.norm(N, axis=1, keepdims=True)
    return N / np.maximum(n, 1e-12)


def _write_ply(path, P, N, C):
    """Binary little-endian PLY with normals — the input pycolmap.poisson_meshing wants."""
    P = np.asarray(P, np.float32)
    N = np.asarray(N, np.float32)
    C = np.asarray(C, np.uint8)
    hdr = (
        'ply\nformat binary_little_endian 1.0\nelement vertex %d\n'
        'property float x\nproperty float y\nproperty float z\n'
        'property float nx\nproperty float ny\nproperty float nz\n'
        'property uchar red\nproperty uchar green\nproperty uchar blue\n'
        'end_header\n' % len(P)
    )
    dt = np.dtype(
        [
            ('x', '<f4'),
            ('y', '<f4'),
            ('z', '<f4'),
            ('nx', '<f4'),
            ('ny', '<f4'),
            ('nz', '<f4'),
            ('red', 'u1'),
            ('green', 'u1'),
            ('blue', 'u1'),
        ]
    )
    rec = np.empty(len(P), dt)
    rec['x'], rec['y'], rec['z'] = P[:, 0], P[:, 1], P[:, 2]
    rec['nx'], rec['ny'], rec['nz'] = N[:, 0], N[:, 1], N[:, 2]
    rec['red'], rec['green'], rec['blue'] = C[:, 0], C[:, 1], C[:, 2]
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(hdr.encode('ascii'))
        f.write(rec.tobytes())
    return path


def stage_dense(out_dir, *, method='auto', poisson_depth=10, poisson_trim=10.0, verbose=True):
    """Densify and surface. Everything here is CPU, and says so.

    method='patchmatch' RAISES on this machine. That is deliberate: pycolmap reports
    has_cuda = False, COLMAP's patch-match stereo is a CUDA kernel, and a silent fallback
    would let a caller believe they had multi-view dense stereo when they had two-view
    block matching. The limitation is loud, documented, and recorded in the artefact.
    """
    sfm = _read_json(_stage_path(out_dir, 'sfm'), 'sfm')
    sc = _read_json(_stage_path(out_dir, 'scale'), 'scale')
    pc = _try_pycolmap()
    cv2 = _try_cv2()
    t0 = time.time()
    dense_dir = os.path.join(out_dir, 'dense')
    os.makedirs(dense_dir, exist_ok=True)

    if method == 'auto':
        method = 'sgbm' if cv2 is not None else 'sparse'
    if method == 'patchmatch':
        raise ScanIngestError(
            'dense_method="patchmatch" cannot run here. pycolmap.has_cuda is %r and '
            "COLMAP's patch-match stereo is a CUDA kernel — it is not built, not slow. "
            'Use method="sgbm" (CPU two-view semi-global block matching, weaker: no '
            'multi-view photometric consistency, no per-pixel view selection) or '
            'method="sparse" (SfM points only). This module will not pretend one is the '
            'other.' % bool(getattr(pc, 'has_cuda', False))
        )
    if method not in ('sgbm', 'sparse'):
        raise ScanIngestError('unknown dense method %r' % method)

    d = np.load(sfm['points_npz'])
    xyz, trk, err = d['xyz'], d['track_length'], d['error']
    keep = (trk >= MIN_TRACK_LENGTH) & (err <= MAX_REPROJ_ERROR_PX)
    sparseP = xyz[keep]
    if len(sparseP) < 50:
        raise ScanIngestError(
            'only %d sparse points survive the quality filter '
            '(track>=%d, reproj<=%.1f px). Nothing to surface.' % (len(sparseP), MIN_TRACK_LENGTH, MAX_REPROJ_ERROR_PX)
        )
    centres = np.array([c['centre'] for c in sfm['cameras'].values()], np.float64)
    sparseVP = np.repeat(centres.mean(0)[None], len(sparseP), axis=0)

    sgbm_stats = None
    if method == 'sgbm':
        # BLUNDER REJECTION. Two-view block matching has no multi-view consistency check,
        # so a mismatched block reprojects to an arbitrary depth — and a flat background
        # produces those by the million. Measured on the synthetic run before this filter
        # existed, the raw SGBM cloud spanned ~11x the subject's own extent and dragged the
        # PCA frame and the ICP with it (final ICP RMS 19.7 m against a 1.68 m body). The
        # geometrically verified structure is the SPARSE cloud, which has already survived
        # track-length and reprojection filtering, so dense points are clipped to its
        # robust bounding box grown by DENSE_BBOX_MARGIN. This throws away blunders, not
        # detail: real surface is by definition inside the body's own box.
        lo = np.percentile(sparseP, 0.5, axis=0)
        hi = np.percentile(sparseP, 99.5, axis=0)
        pad = DENSE_BBOX_MARGIN * (hi - lo)
        P, VP, C, sgbm_stats = _sgbm_densify(sfm, out_dir, sparseP, bbox=(lo - pad, hi + pad), verbose=verbose)
        sgbm_stats['points_after_bbox_reject'] = int(len(P))
        sgbm_stats['bbox_margin'] = DENSE_BBOX_MARGIN
        if len(P) < 500:
            raise ScanIngestError(
                'only %d dense points survive blunder rejection; the '
                'two-view stereo did not agree with the sparse '
                'structure.' % len(P)
            )
        P = np.concatenate([P, sparseP])
        VP = np.concatenate([VP, sparseVP])
        C = np.concatenate([C, np.full((len(sparseP), 3), 180, np.uint8)])
    else:
        P, VP = sparseP, sparseVP
        C = np.full((len(P), 3), 180, np.uint8)

    if len(P) > DENSE_MAX_POINTS:
        sel = np.random.RandomState(0).choice(len(P), DENSE_MAX_POINTS, replace=False)
        sel.sort()
        _log(verbose, 'subsampling dense cloud %d -> %d (DENSE_MAX_POINTS)' % (len(P), DENSE_MAX_POINTS))
        P, VP, C = P[sel], VP[sel], C[sel]
    _log(verbose, 'normals for %d points (knn=%d)' % (len(P), NORMAL_KNN))
    N = _estimate_normals(P, VP)

    factor = float(sc['factor_units_to_m'])
    Pm = P * factor  # METRES from here on
    ply = _write_ply(os.path.join(dense_dir, 'points.ply'), Pm, N, C)

    mesh_ply = os.path.join(dense_dir, 'mesh.ply')
    popts = pc.PoissonMeshingOptions()
    popts.depth = int(poisson_depth)
    popts.trim = float(poisson_trim)
    mesh_ok, mesh_err = True, None
    try:
        _log(verbose, 'poisson_meshing (CPU, depth=%d trim=%.1f)' % (popts.depth, popts.trim))
        pc.poisson_meshing(ply, mesh_ply, popts)
    except Exception as e:
        mesh_ok, mesh_err = False, repr(e)
    nv = nf = 0
    if mesh_ok and os.path.exists(mesh_ply):
        tm = _try_trimesh()
        if tm is not None:
            try:
                m = tm.load(mesh_ply, process=False)
                nv, nf = int(len(m.vertices)), int(len(m.faces))
            except Exception as e:
                mesh_ok, mesh_err = False, repr(e)
        else:
            mesh_err = 'trimesh absent; mesh written but not verified'
    else:
        mesh_ok = False

    np.savez_compressed(
        os.path.join(dense_dir, 'cloud_m.npz'), xyz_m=Pm.astype(np.float32), normal=N.astype(np.float32)
    )

    doc = {
        'schema': SCHEMA,
        'stage': 'dense',
        'status': 'ok',
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'method': method,
        'patchmatch_available': bool(getattr(pc, 'has_cuda', False)),
        'patchmatch_note': 'COLMAP patch-match stereo is CUDA-only; pycolmap.has_cuda is '
        'False on this machine, so the real multi-view dense stereo '
        'path DOES NOT RUN here under any method setting.',
        'open3d_available': False,
        'points_sparse_filtered': int(len(sparseP)),
        'points_total': int(len(P)),
        'sgbm': sgbm_stats,
        'scale_factor_units_to_m': factor,
        'cloud_npz': os.path.join(dense_dir, 'cloud_m.npz'),
        'points_ply': ply,
        'mesh_ply': mesh_ply if mesh_ok else None,
        'mesh_vertices': nv,
        'mesh_faces': nf,
        'mesh_error': mesh_err,
        'poisson': {
            'depth': popts.depth,
            'trim': popts.trim,
            'note': 'Poisson INVENTS surface in unsupported regions by design; '
            'trim removes the least-supported of it. The residual stage '
            'additionally rejects any cage vertex with no scan sample '
            'within SHRINKWRAP_SUPPORT_FRAC, so invented surface becomes '
            'a coverage hole rather than a fabricated ridge.',
        },
        'seconds': round(time.time() - t0, 1),
    }
    _atomic_json(_stage_path(out_dir, 'dense'), doc)
    _log(
        verbose,
        'dense: %s, %d points, mesh %s (%d v / %d f), %.0fs'
        % (method, len(P), 'ok' if mesh_ok else 'FAILED', nv, nf, doc['seconds']),
    )
    return doc
