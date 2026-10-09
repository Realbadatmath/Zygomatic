# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""mvconsist.sfm — the measurement itself: scratch staging, determinism, measure(), the COLMAP/GLOMAP run, classification and the error result.

Moved verbatim from mvconsist.py (lines 296-895) by the 2026-10 modularization split;
no logic, constant or comment was changed.
"""

from __future__ import annotations

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence
import glob as _glob
import math
import os
import shutil
import time
import uuid
from zyg_workflows.geom.mvconsist.constants import (
    CAMERA_GROUPINGS,
    DEFAULT_GLOB,
    DEFAULT_MAX_IMAGE_SIZE,
    MVConsistError,
    QUALITY_PRESETS,
    _CONFIG_NAMES,
    _CONFIG_WITH_PARALLAX,
    _MIN_CAMERAS_FOR_TRIANGULATION,
    _MIN_POINTS_FOR_STATISTICS,
    _import_pycolmap,
    _quiet,
)

# ---------------------------------------------------------------------------
# Working directory. Fresh every time, deleted every time.
# ---------------------------------------------------------------------------


def _default_scratch_root() -> str:
    """Session scratchpad if the harness provided one, else the system temp dir."""
    env = os.environ.get('ZYG_SCRATCH_DIR') or os.environ.get('CLAUDE_SCRATCH_DIR')
    if env and os.path.isdir(env):
        return env
    import tempfile

    return tempfile.gettempdir()


def _stage_images(image_dir: str, pattern: str, work_dir: str) -> List[str]:
    """Symlink the matching .png files into work_dir/images and return their basenames.

    SYMLINKS, not copies: copying 48 x 1024x1152 PNGs is pointless I/O, and more importantly
    a symlink cannot be written back through by anything downstream that opens it read-only,
    while the original directory is never opened for writing at all. COLMAP reads through
    symlinks without noticing (verified on the Abel sheet).

    Sorted by basename so the image_id assignment COLMAP makes is a function of the file
    names alone. COLMAP's own directory walk order is filesystem-dependent, and the
    incremental mapper's behaviour depends on image ids, so leaving that to readdir() would
    have made results depend on which machine ran them."""
    if not os.path.isdir(image_dir):
        raise MVConsistError('image_dir does not exist or is not a directory: %s' % image_dir)

    paths = sorted(_glob.glob(os.path.join(image_dir, pattern)))
    paths = [p for p in paths if os.path.isfile(p) and p.lower().endswith('.png')]
    if not paths:
        raise MVConsistError(
            'no .png files matched %r in %s — the contract is a directory of .png files, '
            'and an empty set cannot be measured.' % (pattern, image_dir)
        )

    img_root = os.path.join(work_dir, 'images')
    os.makedirs(img_root, exist_ok=False)
    names = []
    for p in paths:
        base = os.path.basename(p)
        os.symlink(os.path.abspath(p), os.path.join(img_root, base))
        names.append(base)
    return names


def _read_sizes(image_dir: str, names: Sequence[str]) -> List[tuple]:
    """(width, height) per image, without decoding pixel data where PIL can avoid it."""
    try:
        from PIL import Image
    except Exception:
        return []
    sizes = []
    for n in names:
        try:
            with Image.open(os.path.join(image_dir, n)) as im:
                sizes.append(tuple(im.size))
        except Exception:
            sizes.append((0, 0))
    return sizes


# ---------------------------------------------------------------------------
# Seeding.
# ---------------------------------------------------------------------------


def _seed_everything(pycolmap, seed: int) -> List[str]:
    """Set every seed pycolmap exposes and return the list of seeds we could NOT set.

    The return value is the honest half of this function. There are four seeds available
    (global RNG, pipeline, mapper, verification RANSAC) and they are all set by the callers
    of this helper. What is NOT seedable is thread scheduling, and that is what the returned
    notes describe. Do not delete these notes to make the result look tidier — they are the
    reason stability() exists."""
    pycolmap.set_random_seed(int(seed))
    return []


def _nondeterminism_notes(num_threads: int) -> List[str]:
    """Everything we know we did not pin down. Written out in full, per result.

    These are not hypotheses. Each names a stage that COLMAP runs multi-threaded, for which
    neither COLMAP nor pycolmap exposes any ordering control, and whose output can therefore
    differ run to run at the last bits. The size of the resulting wobble is not guessed here
    — it is measured by stability() on the actual set."""
    notes = [
        'thread scheduling: SIFT extraction, brute-force descriptor matching and Ceres '
        'bundle adjustment all run on %s threads; neither COLMAP nor pycolmap exposes a '
        'seed or an ordering control for thread completion order, so floating-point '
        'reduction order can differ between runs.' % ('all available' if num_threads < 0 else str(num_threads)),
        'incremental mapper growth order: the mapper picks the next image to register by '
        'MIN_UNCERTAINTY over the current model; ties and near-ties resolve by whichever '
        'score arrived first, which inherits the thread nondeterminism above.',
        'Ceres solver termination: bundle adjustment stops on a relative-change criterion, '
        'so a run that reaches the tolerance one iteration earlier ends at a slightly '
        'different optimum. This moves mean_reproj_error_px in the last decimals.',
    ]
    if num_threads == 1:
        notes = [
            'num_threads=1 was requested, which removes the thread-scheduling source. '
            'Any residual spread reported by stability() is therefore NOT explained by '
            'threading and should be investigated rather than tolerated.'
        ] + notes[1:]
    return notes


# ---------------------------------------------------------------------------
# The measurement.
# ---------------------------------------------------------------------------


def measure(
    image_dir: str,
    work_dir: Optional[str] = None,
    *,
    seed: int = 0,
    max_image_size: int = DEFAULT_MAX_IMAGE_SIZE,
    pattern: str = DEFAULT_GLOB,
    quality: str = 'high',
    camera_grouping: str = 'per_resolution',
    num_threads: int = -1,
    keep_work_dir: bool = False,
) -> Dict[str, Any]:
    """Measure how well a directory of .png images reconstructs as one 3D object.

    Parameters
    ----------
    image_dir : directory of .png files. Never written to. This is the whole contract.
    work_dir  : PARENT for the scratch directory. A fresh uuid-named child is created under
                it and removed afterwards; passing the same work_dir twice does not reuse
                anything. Defaults to the session scratchpad or the system temp dir.
    seed      : passed to every seedable RNG. See result['nondeterminism'] for what it does
                not cover.
    max_image_size : ceiling on the longest edge fed to SIFT. Recorded, with the scale that
                was actually applied, in result['image_scale'].
    pattern   : glob applied inside image_dir. The default takes every .png. Contact-sheet
                directories contain a cell_00_body.png at a different resolution and a
                different framing, which is a different camera and would be measured as an
                inconsistency it did not cause — pass 'cell_[0-9][0-9].png' to exclude it.
    quality   : 'default' or 'high'. Must be held fixed across any sets being compared.
    camera_grouping : 'per_resolution' (default), 'single' or 'per_image'. Which images are
                allowed to share intrinsics. This is NOT cosmetic — on the Abel sheet
                'single' gives 3/48 registered and 'per_image' gives 18/48. Must be held
                fixed across any sets being compared. See the comment in _run_sfm().
    num_threads : -1 for all available. Set to 1 to remove the largest nondeterminism source
                at a large cost in wall clock.

    Returns
    -------
    dict. Always a dict, for every outcome including failure. See the module docstring for
    what `status` does and does not mean. The dict contains no verdict; call verdict() with
    a band derived from controls if you want one.
    """
    t_start = time.time()
    if camera_grouping not in CAMERA_GROUPINGS:
        return _error_result(
            image_dir,
            'camera_grouping must be one of %r, got %r' % (list(CAMERA_GROUPINGS), camera_grouping),
            seed=seed,
            quality=quality,
            elapsed=time.time() - t_start,
        )
    if quality not in QUALITY_PRESETS:
        return _error_result(
            image_dir,
            'quality must be one of %r, got %r' % (list(QUALITY_PRESETS), quality),
            seed=seed,
            quality=quality,
            elapsed=time.time() - t_start,
        )

    scratch_parent = work_dir or _default_scratch_root()
    run_dir = os.path.join(scratch_parent, 'mvconsist_%s' % uuid.uuid4().hex[:12])
    created = False

    try:
        pycolmap = _import_pycolmap()
        _quiet(pycolmap)

        os.makedirs(run_dir, exist_ok=False)
        created = True

        names = _stage_images(image_dir, pattern, run_dir)
        sizes = _read_sizes(image_dir, names)
        distinct_sizes = sorted(set(sizes)) if sizes else []

        result = _run_sfm(
            pycolmap,
            run_dir=run_dir,
            names=names,
            sizes=sizes,
            distinct_sizes=distinct_sizes,
            seed=seed,
            max_image_size=max_image_size,
            quality=quality,
            num_threads=num_threads,
            camera_grouping=camera_grouping,
        )
        result['image_dir'] = os.path.abspath(image_dir)
        result['pattern'] = pattern
        result['elapsed_s'] = round(time.time() - t_start, 3)
        return result

    except MVConsistError as exc:
        return _error_result(
            image_dir, str(exc), seed=seed, quality=quality, pattern=pattern, elapsed=time.time() - t_start
        )
    except Exception as exc:  # unexpected: still must not look like a pass
        return _error_result(
            image_dir,
            'structure-from-motion raised %s: %s — no measurement was made.' % (type(exc).__name__, exc),
            seed=seed,
            quality=quality,
            pattern=pattern,
            elapsed=time.time() - t_start,
        )
    finally:
        # Cache nothing. A reconstruction left on disk is a reconstruction that can be
        # picked up by a later run and reported as if it were fresh.
        if created and not keep_work_dir:
            shutil.rmtree(run_dir, ignore_errors=True)


def _run_sfm(
    pycolmap, *, run_dir, names, sizes, distinct_sizes, seed, max_image_size, quality, num_threads, camera_grouping
) -> Dict[str, Any]:
    """The three COLMAP stages, each timed, with the database interrogated between them.

    Interrogating the database between stages is what makes the failure modes separable. If
    we only looked at the final reconstruction we could not tell 'no texture' from 'texture
    everywhere but no consistent 3D object', and those two want completely different fixes."""
    import numpy as np

    db_path = os.path.join(run_dir, 'colmap.db')
    img_root = os.path.join(run_dir, 'images')
    out_root = os.path.join(run_dir, 'sparse')
    os.makedirs(out_root, exist_ok=False)

    _seed_everything(pycolmap, seed)
    high = quality == 'high'

    # --- camera model ------------------------------------------------------
    # THIS CHOICE MOVES THE ANSWER BY A FACTOR OF SIX AND IS NOT A DETAIL. Measured on the
    # Abel c3345deb5bde sheet with everything else identical:
    #     one shared camera over all 48   ->  3 of 48 registered
    #     one free camera per image       -> 18 of 48 registered
    # Both are wrong here, in opposite directions, and the reason is that the sheet is not
    # one camera: its 48 cells carry THREE resolutions (39 at 1024x1152, 6 at 832x1216,
    # 3 at 1024x1024). Sharing one intrinsic across those forces a single focal length onto
    # three different framings and MANUFACTURES a failure the images did not contain. Giving
    # every image its own free focal length does the opposite — it hands the solver 48 extra
    # free parameters into which genuine inconsistency can be absorbed, which INFLATES
    # registration.
    #
    # So we group by resolution: images of the same pixel dimensions came off the same
    # virtual camera and share intrinsics; different dimensions get their own. COLMAP has no
    # mode for this (CameraMode.AUTO degrades to PER_IMAGE without EXIF, verified: it
    # returned 48 cameras on this set), so it is built by calling extract_features once per
    # resolution group with image_names= and CameraMode.SINGLE, which yields exactly one
    # camera per group (verified: 3 cameras, 39/6/3 images).
    #
    # A COMPARISON ACROSS TWO DIFFERENT GROUPINGS IS NOT A COMPARISON. The grouping used and
    # the resulting camera count are both in the result so a mismatch is detectable later.
    notes: List[str] = []
    by_size: Dict[tuple, List[str]] = {}
    sizes_known = bool(sizes) and len(sizes) == len(names) and all(s and s[0] and s[1] for s in sizes)
    if sizes_known:
        for nm, sz in zip(names, sizes):
            by_size.setdefault(sz, []).append(nm)

    if camera_grouping == 'single':
        groups = {('all',): list(names)}
        camera_grouping_name = 'single_shared_camera'
    elif camera_grouping == 'per_image':
        groups = {(nm,): [nm] for nm in names}
        camera_grouping_name = 'one_camera_per_image'
    elif sizes_known:
        groups = by_size
        camera_grouping_name = 'shared_per_resolution'
    else:
        # We asked for per-resolution grouping and could not read the resolutions, so we
        # cannot do it. Falling back silently would swap in a model that moved measured
        # registration on a real sheet from 12/48 to 3/48 — a difference far larger than
        # anything this gate is meant to detect — while the result still claimed to be a
        # per_resolution measurement. Say so loudly instead.
        groups = {('all',): list(names)}
        camera_grouping_name = 'single_shared_camera_FALLBACK'
        notes.append(
            "camera_grouping='per_resolution' was requested but the image resolutions could "
            'not be read (PIL missing or images unreadable), so one shared camera was used '
            'for all %d images instead. THIS IS NOT THE REQUESTED MODEL and the numbers are '
            'not comparable to a per_resolution measurement.' % len(names)
        )

    if camera_grouping_name == 'shared_per_resolution' and len(groups) > 1:
        notes.append(
            'the set is not one camera: %d distinct resolutions %s. Intrinsics were shared '
            'within each resolution and not across them. A set with mixed framings poses an '
            'easier reconstruction problem than a true fixed-intrinsic orbit, so it is not '
            'directly comparable to a single-resolution control.' % (len(distinct_sizes), distinct_sizes)
        )

    # --- stage 1: features -------------------------------------------------
    ext = pycolmap.FeatureExtractionOptions()
    ext.max_image_size = int(max_image_size)
    ext.num_threads = int(num_threads)
    ext.use_gpu = False  # has_cuda is False here; being explicit stops a silent GPU path
    if high:
        # DSP-SIFT + affine shape. Slower, strictly more descriptive, and the reason we can
        # say a failed reconstruction was not starved of features.
        ext.sift.estimate_affine_shape = True
        ext.sift.domain_size_pooling = True
        ext.sift.max_num_features = 16384
        ext.sift.peak_threshold = 0.0033

    t0 = time.time()
    for _key in sorted(groups, key=lambda k: str(k)):
        pycolmap.extract_features(
            db_path,
            img_root,
            image_names=sorted(groups[_key]),
            camera_mode=pycolmap.CameraMode.SINGLE,
            extraction_options=ext,
            device=pycolmap.Device.cpu,
        )
    t_extract = time.time() - t0

    db = pycolmap.Database.open(db_path)
    try:
        db_images = db.read_all_images()
        kp_counts = [int(db.num_keypoints_for_image(im.image_id)) for im in db_images]
        n_cameras = int(db.num_cameras())
    finally:
        db.close()

    if not kp_counts:
        raise MVConsistError('feature extraction produced no images in the database.')

    # --- stage 2: exhaustive matching + geometric verification -------------
    match_opts = pycolmap.FeatureMatchingOptions()
    match_opts.use_gpu = False
    match_opts.num_threads = int(num_threads)
    if high:
        match_opts.guided_matching = True
    verify = pycolmap.TwoViewGeometryOptions()
    verify.ransac.random_seed = int(seed)

    t0 = time.time()
    pycolmap.match_exhaustive(
        db_path,
        matching_options=match_opts,
        verification_options=verify,
        device=pycolmap.Device.cpu,
    )
    t_match = time.time() - t0

    db = pycolmap.Database.open(db_path)
    try:
        pair_ids, geoms = db.read_two_view_geometries()
        n_matched_pairs = int(db.num_matched_image_pairs())
        n_raw_matches = int(db.num_matches())
    finally:
        db.close()

    cfg_counts: Dict[str, int] = {}
    n_verified_matches = 0
    n_verified_pairs = 0
    n_parallax_pairs = 0
    inliers_per_pair: List[int] = []
    for g in geoms:
        c = int(g.config)
        cfg_counts[_CONFIG_NAMES.get(c, 'config_%d' % c)] = cfg_counts.get(_CONFIG_NAMES.get(c, 'config_%d' % c), 0) + 1
        n_inl = len(g.inlier_matches)
        if c in _CONFIG_WITH_PARALLAX:
            n_parallax_pairs += 1
            n_verified_matches += n_inl
            inliers_per_pair.append(n_inl)
        if c not in (0, 1, 7):
            n_verified_pairs += 1

    # How many images ended up connected to anything at all. An image with zero verified
    # pairs cannot possibly register, and counting them separates "a few bad cells" from
    # "the whole set disagrees".
    degree: Dict[int, int] = {}
    for pid in pair_ids:
        a, b = pycolmap.pair_id_to_image_pair(pid)
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
    n_images_with_pairs = len(degree)

    # --- stage 3: incremental mapping --------------------------------------
    pipe = pycolmap.IncrementalPipelineOptions()
    pipe.random_seed = int(seed)
    pipe.num_threads = int(num_threads)
    pipe.mapper.random_seed = int(seed)
    pipe.mapper.num_threads = int(num_threads)
    pipe.ba_use_gpu = False

    t0 = time.time()
    recs = pycolmap.incremental_mapping(db_path, img_root, out_root, options=pipe)
    t_map = time.time() - t0

    n_models = len(recs)
    model_sizes = sorted((int(r.num_reg_images()) for r in recs.values()), reverse=True)

    n_images = len(names)
    base = {
        'n_images': n_images,
        'n_features_mean': round(float(np.mean(kp_counts)), 1),
        'n_features_min': int(min(kp_counts)),
        'n_features_max': int(max(kp_counts)),
        'n_features_median': float(np.median(kp_counts)),
        'n_pairs_possible': n_images * (n_images - 1) // 2,
        'n_pairs_matched': n_matched_pairs,
        'n_raw_matches': n_raw_matches,
        'n_verified_matches': int(n_verified_matches),
        'n_verified_pairs': int(n_verified_pairs),
        'n_parallax_pairs': int(n_parallax_pairs),
        'n_images_with_verified_pairs': int(n_images_with_pairs),
        'median_inliers_per_parallax_pair': (float(np.median(inliers_per_pair)) if inliers_per_pair else 0.0),
        'two_view_configs': cfg_counts,
        'n_models': int(n_models),
        'model_sizes': model_sizes,
        'n_cameras_in_db': n_cameras,
        'camera_grouping': camera_grouping_name,
        'n_camera_groups': len(groups),
        'image_size': {
            'distinct': [list(s) for s in distinct_sizes],
            'max_image_size_requested': int(max_image_size),
            'scale_applied': _scale_applied(distinct_sizes, max_image_size),
        },
        'quality': quality,
        'seed': int(seed),
        'num_threads': int(num_threads),
        'timings_s': {
            'extract': round(t_extract, 3),
            'match': round(t_match, 3),
            'map': round(t_map, 3),
        },
        'pycolmap_version': getattr(pycolmap, '__version__', 'unknown'),
        'colmap_version': str(getattr(pycolmap, 'COLMAP_version', 'unknown')),
        'colmap_build': str(getattr(pycolmap, 'COLMAP_build', 'unknown')),
        'has_cuda': bool(getattr(pycolmap, 'has_cuda', False)),
        'nondeterminism': _nondeterminism_notes(num_threads),
        'notes': notes,
    }

    if n_models == 0:
        base.update(
            {
                'n_registered': 0,
                'registration_rate': 0.0,
                'n_points3D': 0,
                'mean_reproj_error_px': None,
                'mean_track_length': None,
                'mean_observations_per_reg_image': None,
                'largest_model_index': None,
            }
        )
        base['status'], base['reason'] = _classify(base)
        return base

    best_idx = max(recs, key=lambda k: (recs[k].num_reg_images(), recs[k].num_points3D()))
    rec = recs[best_idx]
    n_registered = int(rec.num_reg_images())
    n_points = int(rec.num_points3D())

    reproj = track = obs = None
    if n_points >= _MIN_POINTS_FOR_STATISTICS:
        try:
            reproj = float(rec.compute_mean_reprojection_error())
            track = float(rec.compute_mean_track_length())
            obs = float(rec.compute_mean_observations_per_reg_image())
        except Exception:
            reproj = track = obs = None

    base.update(
        {
            'n_registered': n_registered,
            'registration_rate': round(n_registered / float(n_images), 6) if n_images else 0.0,
            'n_points3D': n_points,
            'mean_reproj_error_px': (round(reproj, 4) if reproj is not None and math.isfinite(reproj) else None),
            'mean_track_length': (round(track, 4) if track is not None and math.isfinite(track) else None),
            'mean_observations_per_reg_image': (round(obs, 3) if obs is not None and math.isfinite(obs) else None),
            'largest_model_index': int(best_idx),
        }
    )
    base['status'], base['reason'] = _classify(base)
    return base


def _classify(r: Dict[str, Any]) -> tuple:
    """Assign status and reason from an already-populated result. Pure, so it is testable
    without running SfM — the no_model and degenerate branches are otherwise very hard to
    provoke on demand, and an untested branch in the failure path of an honesty-critical
    module is exactly the branch that will be wrong when it finally fires.

    NOTHING HERE IS A QUALITY THRESHOLD. The only comparisons are against
    _MIN_CAMERAS_FOR_TRIANGULATION and _MIN_POINTS_FOR_STATISTICS, which state what a
    reconstruction must contain before mean_reproj_error_px and mean_track_length are
    defined at all. A set that passes them can still be terrible; that is verdict()'s job."""
    n_images = r.get('n_images') or 0
    n_models = r.get('n_models') or 0
    feats = r.get('n_features_mean')
    parallax = r.get('n_parallax_pairs') or 0
    connected = r.get('n_images_with_verified_pairs') or 0

    if n_models == 0:
        # Separate the two failures that look identical in the reconstruction but want
        # completely different fixes: nothing to match vs plenty to match and no agreement.
        if not feats:
            cause = (
                'SIFT found essentially no features (%s per image), so there was '
                'nothing to match. This is an image-content failure, not a geometric '
                'one — a blank or untextured set cannot be tested for consistency.' % feats
            )
        elif parallax == 0:
            cause = (
                'SIFT found %.0f features per image but NOT ONE of the %d image pairs '
                'produced a verified two-view geometry with parallax. There is texture '
                'and no agreement whatsoever between any two views.' % (feats, r.get('n_pairs_possible') or 0)
            )
        else:
            cause = (
                'SIFT found %.0f features per image and %d pairs verified with '
                'parallax, yet no pair was good enough to initialise a model. The views '
                'agree locally and nowhere well enough to support a 3D structure.' % (feats, parallax)
            )
        return 'no_model', ('COLMAP produced no reconstruction at all from %d images. %s' % (n_images, cause))

    n_registered = r.get('n_registered') or 0
    n_points = r.get('n_points3D') or 0
    if (
        n_registered < _MIN_CAMERAS_FOR_TRIANGULATION
        or n_points < _MIN_POINTS_FOR_STATISTICS
        or r.get('mean_reproj_error_px') is None
        or r.get('mean_track_length') is None
    ):
        return 'degenerate', (
            'COLMAP returned %d model(s) but the largest has %d registered camera(s) and %d '
            '3D point(s), below what is structurally required for reprojection error and '
            'track length to be defined (>=%d cameras, >=%d points). The measurement has '
            'nothing to describe. This is a statement about the measurement, not a quality '
            'verdict.' % (n_models, n_registered, n_points, _MIN_CAMERAS_FOR_TRIANGULATION, _MIN_POINTS_FOR_STATISTICS)
        )

    return 'ok', (
        "measurement completed; 'ok' means the numbers are valid, NOT that the set is "
        'consistent — %d of %d cameras registered into the largest of %d model(s) '
        '(sizes %s), %d of %d images connected to any verified pair, mean track length '
        '%.2f. Compare against a control band via verdict().'
        % (n_registered, n_images, n_models, r.get('model_sizes'), connected, n_images, r['mean_track_length'])
    )


def _scale_applied(distinct_sizes, max_image_size) -> Any:
    """The factor COLMAP's rescaler would apply, per distinct resolution.

    Reported rather than assumed: if a caller lowers max_image_size to save time, every
    measured quantity moves (fewer features, different reprojection error in pixels), and a
    comparison across two different scales is not a comparison."""
    if not distinct_sizes:
        return None
    out = {}
    for w, h in distinct_sizes:
        longest = max(w, h)
        s = 1.0 if longest <= max_image_size or longest == 0 else max_image_size / float(longest)
        out['%dx%d' % (w, h)] = round(s, 6)
    return out


def _error_result(image_dir, reason, *, seed=None, quality=None, pattern=None, elapsed=None) -> Dict[str, Any]:
    """The one shape a failure is allowed to take.

    Every numeric field is None, never 0 and never a default. A zero would be a number a
    downstream comparison could act on; None cannot be compared, so a caller that forgets to
    check `status` gets a TypeError instead of a false pass. That is deliberate."""
    return {
        'n_images': None,
        'n_registered': None,
        'registration_rate': None,
        'n_points3D': None,
        'mean_reproj_error_px': None,
        'mean_track_length': None,
        'n_models': None,
        'n_features_mean': None,
        'n_verified_matches': None,
        'status': 'error',
        'reason': reason,
        'image_dir': os.path.abspath(image_dir) if image_dir else None,
        'pattern': pattern,
        'seed': seed,
        'quality': quality,
        'elapsed_s': round(elapsed, 3) if elapsed is not None else None,
    }
