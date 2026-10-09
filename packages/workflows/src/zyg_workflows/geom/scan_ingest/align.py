# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""STAGE d — RIGID ALIGNMENT (rotation + translation only; NEVER scale).

Moved verbatim out of the old single-file scan_ingest.py (lines 1299-1513).
"""

import math
import os
import time
import numpy as np

from zyg_workflows.geom.scan_ingest.constants import (
    DENSE_BBOX_MARGIN,
    SCHEMA,
    ScanIngestError,
    USE_POISSON_MESH_AS_SCAN,
)
from zyg_workflows.geom.scan_ingest.helpers import (
    _atomic_json,
    _log,
    _read_json,
    _stage_path,
    _stature_of,
    _target_cage,
    _try_trimesh,
)


# ==================================================================================
# STAGE d — RIGID ALIGNMENT (rotation + translation only; NEVER scale)
# ==================================================================================
def _scan_points_m(dn, prefer_mesh=USE_POISSON_MESH_AS_SCAN, verbose=True):
    """The scan as a cleaned point set in METRES.

    THE DEFAULT IS THE DENSE CLOUD, NOT THE POISSON MESH, and that is a finding rather
    than a preference. pycolmap.poisson_meshing runs and writes a mesh, but the mesh it
    wrote on the synthetic run is not usable as geometry:

      * 4,851,090 vertices, of which 2,405 are non-finite — enough that cKDTree refuses
        the whole array outright with 'data must be finite';
      * the finite ones span +-3.4e38, i.e. float32 FLT_MAX sentinels, against a 1.68 m
        subject. PoissonMeshingOptions.trim = 10 did not remove them;
      * clipping to the dense cloud's own robust box left 540,326 of 4,851,090 vertices,
        and that survivor set is dominated by a degenerate blob at the origin: ICP against
        it converged to identity-plus-translation with an RMS of 7 micrometres, which is
        the signature of fitting to a point cloud that is not a body.
      * before the box clip, PCA + ICP on the raw mesh vertices produced a final RMS of
        4.6e28 mm.

    The dense cloud, by contrast, is bbox-rejected against the geometrically verified
    sparse structure and behaves: ICP 11.2 mm RMS, 53.9 % shrinkwrap coverage. So the mesh
    is still WRITTEN (it is what a working Poisson would give, and a machine with open3d
    or a fixed writer could use it) but it is not CONSUMED unless the caller asks. Set
    USE_POISSON_MESH_AS_SCAN = True or pass prefer_mesh=True to opt in.

    Whatever the source, points are filtered to finite values inside the dense cloud's
    robust box: Poisson invents surface and must never be allowed to extend the scan's
    support beyond where photographs actually saw something.
    """
    cloud = np.load(dn['cloud_npz'])['xyz_m'].astype(np.float64)
    cloud = cloud[np.isfinite(cloud).all(axis=1)]
    if len(cloud) < 100:
        raise ScanIngestError('the dense stage left %d finite points.' % len(cloud))
    lo = np.percentile(cloud, 0.5, axis=0)
    hi = np.percentile(cloud, 99.5, axis=0)
    pad = DENSE_BBOX_MARGIN * (hi - lo)
    lo, hi = lo - pad, hi + pad
    tm = _try_trimesh()
    if prefer_mesh and dn.get('mesh_ply') and os.path.exists(dn['mesh_ply']) and tm is not None:
        try:
            mv = np.asarray(tm.load(dn['mesh_ply'], process=False).vertices, np.float64)
            n_raw = len(mv)
            mv = mv[np.isfinite(mv).all(axis=1)]
            mv = mv[np.all((mv >= lo) & (mv <= hi), axis=1)]
            if len(mv) >= 5000:
                _log(
                    verbose,
                    'scan points: %d Poisson mesh vertices of %d survive the '
                    'finite + robust-box filter' % (len(mv), n_raw),
                )
                return mv, 'poisson_mesh_vertices'
            _log(verbose, 'only %d of %d Poisson vertices survive filtering; using the cloud' % (len(mv), n_raw))
        except Exception as e:
            _log(verbose, 'Poisson mesh unusable (%r); using the cloud' % e)
    return cloud, 'dense_cloud'


def _pca_frame(P):
    c = P.mean(0)
    _, _, Vt = np.linalg.svd(P - c, full_matrices=False)
    F = Vt.copy()
    if np.linalg.det(F) < 0:
        F[2] *= -1.0
    return c, F


def _icp(src, dst_tree, R0, t0, iters=40, trim=0.7):
    """Point-to-point ICP with a trimmed correspondence set.

    Trimming (keep the best `trim` fraction of correspondences each iteration) is what
    makes this survive the coverage holes a single-camera scan always has: an unmatched
    region produces enormous residuals that would otherwise drag the whole fit.

    NO SCALE TERM. See the module docstring: solving scale here would put our own cage's
    proportions into the scan and let a later stage read them back out as observation.

    TWO RMS NUMBERS COME BACK, AND WHICH ONE IS PUBLISHED MATTERS.
    `rms_trimmed` is the RMS over the kept `trim` fraction — the quantity the optimiser is
    actually minimising, and the right one to test for convergence. It is NOT the fit error:
    it excludes the worst 30 % of correspondences, which are precisely the coverage holes
    and stereo blunders an alignment guard exists to expose. MEASURED on the synthetic
    self-test (2026-08-08) it reads 47.03 mm against a full-set 132.08 mm, i.e. 2.81x
    optimistic — an alignment sitting at 0.0786 of stature reported at 0.0280. The FULL-SET
    RMS is therefore what stage_align publishes as `icp_rms_m` and what PROVENANCE.json's
    `align_icp_rms_mm` carries; the trimmed value is reported beside it as
    `icp_rms_trimmed_m` under its own name, with the ratio.

    Both are evaluated AFTER the returned transform, not at the pose the iteration started
    from. The old code returned the RMS of `dist`, which was measured before that
    iteration's rotation was applied, so the number described the previous pose.
    """
    R, t = R0.copy(), t0.copy()
    rms = np.inf
    for _ in range(iters):
        S = src @ R.T + t
        dist, idx = dst_tree.query(S, workers=-1)
        k = max(10, int(trim * len(S)))
        sel = np.argsort(dist)[:k]
        A = src[sel]
        B = dst_tree.data[idx[sel]]
        ca, cb = A.mean(0), B.mean(0)
        H = (A - ca).T @ (B - cb)
        U, _, Vt = np.linalg.svd(H)
        D = np.eye(3)
        D[2, 2] = np.sign(np.linalg.det(Vt.T @ U.T))
        R = Vt.T @ D @ U.T
        t = cb - R @ ca
        # re-query at the pose we are about to return, so `new` belongs to THIS transform
        dist_new, _ = dst_tree.query(src @ R.T + t, workers=-1)
        sel_new = np.argsort(dist_new)[:k]
        new = float(np.sqrt((dist_new[sel_new] ** 2).mean()))
        if abs(rms - new) < 1e-7:
            rms = new
            break
        rms = new
    dist_final, _ = dst_tree.query(src @ R.T + t, workers=-1)
    k = max(10, int(trim * len(src)))
    rms_full = float(np.sqrt((dist_final**2).mean()))
    rms_trimmed = float(np.sqrt((np.sort(dist_final)[:k] ** 2).mean()))
    return R, t, rms_trimmed, rms_full


def stage_align(out_dir, target_character, *, yaw_steps=24, max_points=40000, verbose=True):
    """Rigidly place the scan (already in metres) in our cage's frame.

    PCA gives the body axis and a coarse frame; the remaining freedom is essentially the
    yaw about that axis plus a front/back flip, so we sweep yaw and take the best trimmed
    ICP. Rotation and translation only.

    A large final RMS is NOT necessarily a failure: the scan is a different person, and a
    different person does not fit our cage. It is reported and the residual stage is
    designed to survive it (the low-pass is exactly what removes the body-shape mismatch).
    An RMS on the order of the stature, though, means the alignment fell over.
    """
    sc = _read_json(_stage_path(out_dir, 'scale'), 'scale')
    dn = _read_json(_stage_path(out_dir, 'dense'), 'dense')
    from scipy.spatial import cKDTree

    t0 = time.time()

    cage_v, cage_f = _target_cage(target_character)
    S = _stature_of(cage_v)

    cloud, cloud_src = _scan_points_m(dn, verbose=verbose)
    if len(cloud) > max_points:
        rs = np.random.RandomState(0)
        cloud = cloud[rs.choice(len(cloud), max_points, replace=False)]

    cc, CF = _pca_frame(cage_v)
    sc_c, SF = _pca_frame(cloud)
    tree = cKDTree(cage_v)

    best = None
    for k in range(yaw_steps):
        for flip in (1.0, -1.0):
            a = 2.0 * math.pi * k / yaw_steps
            Rz = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
            F = SF.copy()
            F[1] *= flip
            F[2] = np.cross(F[0], F[1])
            R0 = CF.T @ Rz @ F
            t_0 = cc - R0 @ sc_c
            R, t, rms, rms_full = _icp(cloud, tree, R0, t_0, iters=25)
            if best is None or rms < best[2]:
                best = (R, t, rms, rms_full)
    R, t, rms, rms_full = best
    R, t, rms, rms_full = _icp(cloud, tree, R, t, iters=60)

    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    np.save(os.path.join(out_dir, 'align_T.npy'), T)

    doc = {
        'schema': SCHEMA,
        'stage': 'align',
        'status': 'ok',
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'target_character': target_character,
        'target_stature_m': S,
        'transform_scan_to_cage': T.tolist(),
        'transform_has_scale': False,
        # THE FIT ERROR, over EVERY correspondence. This is the number the guard
        # sentence below is about and the one PROVENANCE.json publishes.
        'icp_rms_m': float(rms_full),
        'icp_rms_over_stature': float(rms_full / S),
        'icp_rms_is': 'RMS over ALL %d correspondences at the returned transform' % len(cloud),
        # The optimiser's own objective. Excludes the worst 30% — the coverage holes and
        # blunders — so it is systematically smaller and must never be read as the fit
        # error. Reported under its own name so the gap is visible.
        'icp_rms_trimmed_m': float(rms),
        'icp_trim_fraction': 0.7,
        'icp_rms_trimmed_over_full': float(rms / rms_full) if rms_full > 0 else None,
        'points_used': int(len(cloud)),
        'source': cloud_src,
        'note': 'rotation + translation only. A large RMS means "a different body", '
        'which is expected and survivable; an RMS on the order of the stature '
        'means the alignment failed and the residual below is meaningless. '
        'icp_rms_m is the FULL-SET RMS: the trimmed objective the optimiser '
        'minimises drops the worst 30% of correspondences and reads about 3x '
        'lower, which would make this guard 3x less sensitive to exactly the '
        'holes it exists to catch.',
        'scale_factor_units_to_m': sc['factor_units_to_m'],
    }
    _atomic_json(_stage_path(out_dir, 'align'), doc)
    _log(
        verbose,
        'align: ICP rms %.1f mm full-set (%.4f of stature), %.1f mm trimmed, %.0fs'
        % (1e3 * rms_full, rms_full / S, 1e3 * rms, time.time() - t0),
    )
    return doc
