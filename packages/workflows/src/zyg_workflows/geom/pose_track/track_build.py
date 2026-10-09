# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The stages of ``pose_track.track.build_track``.

``build_track`` was one 302-line function with five closures: extract, fit,
ledger, stack, filter, metrics, masks, arrays, track dict. Each stage is a
helper here and :class:`TrackCtx` is the context object that used to be the
function's locals — the five closures (``_stack``, ``jitter3``, ``jitter2``,
``rmse3``, ``rmse2``) are now module-level functions, so the jitter and
null-model arithmetic can be exercised on plain arrays for the first time.

Nothing in here imports ``track.py`` (which imports this module): the two
functions that live there — ``subject_track`` and the smoothing — are passed in
or applied by the orchestrator. Behaviour, log lines, file layout and the
track.json key order are unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .constants import FOUND, MHR70_TO_POSE, NOT_DETECTABLE, NOT_FOUND, UNMEASURABLE, cv2, glob, gpu_lock, json
from .constants import np, os, time

__all__ = [
    'FitRun',
    'Ledger',
    'RawSeries',
    'ShapeLock',
    'Smoothed',
    'TrackCtx',
    'TrackDirs',
    'assemble_track',
    'frame_ledger',
    'jitter2',
    'jitter3',
    'probe_size',
    'reproj_error',
    'rmse2',
    'rmse3',
    'run_fit',
    'save_arrays',
    'shape_lock',
    'stack_series',
    'track_dirs',
    'track_metrics',
    'write_masks',
]


@dataclass
class TrackDirs:
    """The four directories a track is written into, under one out_dir."""

    frames: str
    arrays: str
    sam3_masks: str
    masks: str


@dataclass
class FitRun:
    """What the two GPU stages produced, and how long each of them took.

    ``lock_wait_*`` is time spent waiting for OTHER jobs; ``sam3_s``/``fit_s``
    is time the GPU lock was actually earning it.
    """

    res: dict
    meta: dict
    boxes: dict
    smasks: dict
    sub_info: dict
    dec_ok: bool
    dec_why: str
    lock_wait_sam3_s: float = 0.0
    sam3_s: float = 0.0
    lock_wait_fit_s: float = 0.0
    fit_s: float = 0.0


@dataclass
class Ledger:
    """Per-frame outcome of the fit, and the index of the frames that worked.

    ``boxed[i]`` false means SAM 3 steered nothing on that frame;
    ``box_src[i]`` tells a real detection from a held one.
    """

    ledger: list
    recs: list
    boxed: list
    box_src: list
    idx: list


@dataclass
class RawSeries:
    """The estimator's per-frame output stacked over the fitted frames."""

    kp3: Any
    kp2: Any
    cam_t: Any
    focal: Any
    grot: Any
    shape: Any
    scale: Any
    body_pose: Any
    verts: Any
    jrot: Any
    jcoord: Any


@dataclass
class Smoothed:
    """The same series after the temporal filter (rotations as rotation vectors)."""

    kp3: Any
    kp2: Any
    cam: Any
    grot: Any
    jrv: Any
    verts: Any
    jco: Any


@dataclass
class ShapeLock:
    """The median identity over the track and how far each frame drifts from it."""

    med: Any
    scale_med: Any
    dev: float
    dev_max: float
    std: float


@dataclass
class TrackCtx:
    """Everything one ``build_track`` call accumulates, in stage order.

    The orchestrator fills a field per stage and every helper below reads what
    the earlier stages left here — the same reads the closures used to make on
    the enclosing function's locals.
    """

    clip: str
    out_dir: str
    subject: str
    fps: int
    smooth: str
    window: int
    dirs: TrackDirs
    log: Any
    t_start: float = field(default_factory=time.time)
    extract_s: float = 0.0
    frames: list = field(default_factory=list)
    W: int = 0
    H: int = 0
    fit: Any = None
    led: Any = None
    raw: Any = None
    sm: Any = None
    shape: Any = None
    metrics: dict = field(default_factory=dict)
    npz: str = ''
    n_masks: int = 0
    n_held_masks: int = 0
    t_post: float = 0.0


def track_dirs(out_dir: str) -> TrackDirs:
    """The four output subdirectories of a track, unmade."""
    return TrackDirs(
        frames=os.path.join(out_dir, 'frames'),
        arrays=os.path.join(out_dir, 'arrays'),
        sam3_masks=os.path.join(out_dir, '_sam3_masks'),
        masks=os.path.join(out_dir, 'masks'),
    )


def probe_size(ctx: TrackCtx) -> tuple[int, int]:
    """Read the frame size off the first extracted frame and log the shape.

    In: a ctx whose ``frames`` the extractor just filled. Out: ``(W, H)``.
    Raises RuntimeError when ffmpeg produced no frames at all — there is no
    track to build from a clip that did not decode.
    """
    if not ctx.frames:
        raise RuntimeError(f'no frames extracted from {ctx.clip}')
    probe = cv2.imread(ctx.frames[0])
    H, W = probe.shape[:2]
    ctx.log('  frames: %d at %d fps, %dx%d' % (len(ctx.frames), ctx.fps, W, H))
    return W, H


def run_fit(ctx: TrackCtx, s3b, subject_track, *, threshold: float) -> FitRun:
    """The two GPU stages: SAM 3 subject boxes, then the SAM 3D Body fit.

    In: the ctx, the ``sam3d_body_service`` module, the ``subject_track``
    function (passed in so this module never imports its caller) and the SAM 3
    score threshold. Out: a :class:`FitRun`.

    TWO locks, one per model, NOT one across both. Holding the lock from SAM 3
    through SAM 3D Body kept it for 1h50m at 1% GPU utilisation on 2026-09-03
    with eight jobs queued behind it, because the gap between the models is
    subprocess start-up, mask I/O and worker load — CPU and disk, no GPU. The
    frame extraction and everything after the fit stay outside the lock for the
    same reason.
    """
    log = ctx.log
    boxes: dict = {}
    smasks: dict = {}
    sub_info = {'ok': False, 'reason': 'no --subject given; whole-image single-person'}
    lock_wait_sam3_s = sam3_s = 0.0
    if ctx.subject:
        with gpu_lock(log=log, stage='sam3') as _l:
            lock_wait_sam3_s = _l['wait_s']
            t_s3 = time.time()
            boxes, smasks, sub_info = subject_track(
                ctx.frames, ctx.subject, ctx.dirs.sam3_masks, threshold=threshold, log=log
            )
            sam3_s = time.time() - t_s3
        log('  subject: %s' % json.dumps({k: v for k, v in sub_info.items() if k != 'box_source'}))
    dec_ok, dec_why = s3b.mhr_decode_available()
    with gpu_lock(log=log, stage='sam3d_body') as _l:
        lock_wait_fit_s = _l['wait_s']
        t_fit = time.time()
        res = s3b.fit_batch(
            ctx.frames, bboxes=boxes or None, masks=smasks or None, arrays_dir=ctx.dirs.arrays, log_fn=log
        )
        fit_s = time.time() - t_fit
    ctx.t_post = time.time()
    if not res:
        raise RuntimeError('SAM 3D Body worker returned nothing')
    meta = res.get('_meta') or {}
    log(
        '  fit: %d/%d detected, load %.1fs, %.3fs/frame'
        % (meta.get('n_detected', 0), len(ctx.frames), meta.get('load_s', 0), meta.get('mean_t_s') or 0)
    )
    return FitRun(
        res=res,
        meta=meta,
        boxes=boxes,
        smasks=smasks,
        sub_info=sub_info,
        dec_ok=dec_ok,
        dec_why=dec_why,
        lock_wait_sam3_s=lock_wait_sam3_s,
        sam3_s=sam3_s,
        lock_wait_fit_s=lock_wait_fit_s,
        fit_s=fit_s,
    )


def frame_ledger(ctx: TrackCtx) -> Ledger:
    """Classify every frame and keep the records of the ones that fitted.

    In: the ctx after :func:`run_fit`. Out: a :class:`Ledger`. A frame the
    subject tracker gave no box for still gets a fit — whole-image,
    single-person, which in a two-hander is a DIFFERENT PERSON's measurement
    wearing this track's frame number. It is recorded per frame and counted,
    never averaged away: ``boxed`` false is the flag that says this frame was
    not steered. Raises RuntimeError when no frame fitted at all.
    """
    subject = ctx.subject
    boxes = ctx.fit.boxes
    res = ctx.fit.res
    ledger, recs = [], []
    for f in ctx.frames:
        r = res.get(f)
        if not isinstance(r, dict):
            ledger.append(UNMEASURABLE)
            recs.append(None)
        elif r.get('error'):
            ledger.append(UNMEASURABLE)
            recs.append(None)
        elif not r.get('detected'):
            ledger.append(NOT_DETECTABLE if (subject and f not in boxes) else NOT_FOUND)
            recs.append(None)
        else:
            ledger.append(FOUND)
            recs.append(r)
    bsrc = (ctx.fit.sub_info.get('box_source') or {}) if subject else {}
    boxed = [bool(f in boxes) for f in ctx.frames]
    box_src = [bsrc.get(f, 'none' if subject else 'whole_image') for f in ctx.frames]
    idx = [i for i, s in enumerate(ledger) if s == FOUND]
    if not idx:
        raise RuntimeError('no frame produced a fit — nothing to track')
    return Ledger(ledger=ledger, recs=recs, boxed=boxed, box_src=box_src, idx=idx)


def stack_series(led: Ledger) -> RawSeries:
    """Stack the fitted frames' records into one array per quantity.

    In: the ledger. Out: a :class:`RawSeries` — keypoints (F,70,3) and (F,70,2),
    camera translation (F,3), focal (F,), global rotation (F,3), shape (F,45),
    scale (F,28), body pose, vertices (F,18439,3), joint rotation matrices
    (F,127,3,3) and joint coordinates (F,127,3). The three big ones are loaded
    from the worker's .npy side-cars.
    """
    recs, idx = led.recs, led.idx

    def _stack(key):
        return np.array([np.asarray(recs[i][key], np.float64) for i in idx])

    return RawSeries(
        kp3=_stack('pred_keypoints_3d'),
        kp2=_stack('pred_keypoints_2d'),
        cam_t=_stack('pred_cam_t'),
        focal=np.array([float(recs[i]['focal_length']) for i in idx]),
        grot=_stack('global_rot'),
        shape=_stack('shape_params'),
        scale=_stack('scale_params'),
        body_pose=_stack('body_pose_params'),
        verts=np.array([np.load(recs[i]['npy']['pred_vertices']) for i in idx], dtype=np.float32),
        jrot=np.array([np.load(recs[i]['npy']['pred_global_rots']) for i in idx], dtype=np.float64),
        jcoord=np.array([np.load(recs[i]['npy']['pred_joint_coords']) for i in idx], dtype=np.float64),
    )


def shape_lock(raw: RawSeries) -> ShapeLock:
    """The median shape/scale over the track and the drift away from it.

    In: the raw series. Out: a :class:`ShapeLock`. Recorded, not applied — see
    the module header of the package for why re-synthesis needs pymomentum.
    """
    med = np.median(raw.shape, axis=0)
    return ShapeLock(
        med=med,
        scale_med=np.median(raw.scale, axis=0),
        dev=float(np.abs(raw.shape - med).mean()),
        dev_max=float(np.abs(raw.shape - med).max()),
        std=float(raw.shape.std(axis=0).mean()),
    )


def jitter3(a) -> float | None:
    """Mean per-joint frame-to-frame displacement, in mm."""
    if a.shape[0] < 2:
        return None
    return float(np.linalg.norm(np.diff(a, axis=0), axis=-1).mean() * 1000.0)


def jitter2(a) -> float | None:
    """Mean per-keypoint frame-to-frame displacement, in pixels."""
    if a.shape[0] < 2:
        return None
    return float(np.linalg.norm(np.diff(a, axis=0), axis=-1).mean())


def rmse3(a, b) -> float:
    """Mean euclidean distance between two 3D series, in mm."""
    return float(np.sqrt(((a - b) ** 2).sum(-1)).mean() * 1000.0)


def rmse2(a, b) -> float:
    """Mean euclidean distance between two 2D series, in pixels."""
    return float(np.sqrt(((a - b) ** 2).sum(-1)).mean())


def track_metrics(ctx: TrackCtx) -> dict:
    """Jitter, total motion and the two null models the brief names.

    In: the ctx after the temporal filter. Out: the ``metrics`` dict. The nulls
    are what the track must beat to be worth anything: holding the first frame
    for the whole clip, and lerping between the first and last pose.
    """
    raw, sm = ctx.raw, ctx.sm
    kp3_s, kp2_s = sm.kp3, sm.kp2
    held = np.repeat(kp3_s[:1], kp3_s.shape[0], axis=0)  # null 1
    n = kp3_s.shape[0]
    tt = (np.arange(n) / max(n - 1, 1))[:, None, None]
    lerp = kp3_s[:1] * (1 - tt) + kp3_s[-1:] * tt  # null 2
    held2 = np.repeat(kp2_s[:1], n, axis=0)
    lerp2 = kp2_s[:1] * (1 - tt[:, :, :1]) + kp2_s[-1:] * tt[:, :, :1]
    return {
        'frames_fitted': int(n),
        'jitter_mm_raw': jitter3(raw.kp3),
        'jitter_mm_smoothed': jitter3(kp3_s),
        'jitter_px_2d_raw': jitter2(raw.kp2),
        'jitter_px_2d_smoothed': jitter2(kp2_s),
        'motion_mm_total': float(np.linalg.norm(kp3_s[-1] - kp3_s[0], axis=-1).mean() * 1000.0),
        'null_held_first_frame': {'joint_err_mm': rmse3(held, kp3_s), 'kp2_err_px': rmse2(held2, kp2_s)},
        'null_two_pose_lerp': {'joint_err_mm': rmse3(lerp, kp3_s), 'kp2_err_px': rmse2(lerp2, kp2_s)},
        'smoothing': ctx.smooth,
        'window': ctx.window,
    }


def write_masks(ctx: TrackCtx) -> tuple[int, int]:
    """Write the subject masks in the VACE format, holding across dropouts.

    In: the ctx after the ledger. Out: ``(masks_written, masks_held)``.

    A mask SEQUENCE with holes is not a sequence: every consumer of
    m_%05d.png — vace_control.build, wan_vace_service, S05's picker — indexes
    it positionally against the control frames, so one missing number silently
    shifts every mask after it onto the wrong frame. SAM 3 drops the subject on
    the odd frame, so the last mask is held across the gap exactly as the box
    is, and the holds are counted rather than hidden.
    """
    masks_dir = ctx.dirs.masks
    os.makedirs(masks_dir, exist_ok=True)
    for old in glob.glob(os.path.join(masks_dir, 'm_*.png')):
        os.remove(old)
    recs = ctx.led.recs
    n_masks = 0
    n_held_masks = 0
    last_m = None
    for k, i in enumerate(ctx.led.idx):
        f = ctx.frames[i]
        src = ctx.fit.smasks.get(f) or (recs[i].get('npy') or {}).get('mask')
        m = None
        if src and os.path.isfile(src):
            m = cv2.imread(src, cv2.IMREAD_GRAYSCALE)
        if m is None:
            if last_m is None:
                continue
            m = last_m
            n_held_masks += 1
        if m.shape[:2] != (ctx.H, ctx.W):
            m = cv2.resize(m, (ctx.W, ctx.H), interpolation=cv2.INTER_NEAREST)
        last_m = m
        cv2.imwrite(os.path.join(masks_dir, 'm_%05d.png' % k), (m > 127).astype(np.uint8) * 255)
        n_masks += 1
    return n_masks, n_held_masks


def save_arrays(ctx: TrackCtx) -> str:
    """Write the smoothed series to ``track_arrays.npz`` and return its path.

    Joint rotations are stored as ROTATION VECTORS, not matrices: a temporal
    filter applied to the nine elements of a rotation matrix does not produce a
    rotation matrix (``track.rotvec_to_matrix`` converts back).
    """
    sm = ctx.sm
    npz = os.path.join(ctx.out_dir, 'track_arrays.npz')
    np.savez_compressed(
        npz,
        vertices=sm.verts,
        joint_rotvec=sm.jrv.astype(np.float32),
        joint_coords=sm.jco.astype(np.float32),
        keypoints_3d=sm.kp3.astype(np.float32),
        keypoints_2d=sm.kp2.astype(np.float32),
        cam_t=sm.cam.astype(np.float32),
        focal=ctx.raw.focal.astype(np.float32),
        global_rot=sm.grot.astype(np.float32),
    )
    return npz


def reproj_error(raw: RawSeries, W: int, H: int) -> float:
    """Worst reprojection error of the first fitted frame, in pixels.

    In: the raw series and the frame size. Out: the largest distance between
    the estimator's own 2D keypoints and the pinhole projection of its 3D ones.
    The model written into ``projection`` must reproduce them, or every plate
    downstream is drawn wrong.
    """
    p = raw.kp3[0] + raw.cam_t[0]
    focal = raw.focal
    proj = np.stack([focal[0] * p[:, 0] / p[:, 2] + W / 2.0, focal[0] * p[:, 1] / p[:, 2] + H / 2.0], -1)
    return float(np.linalg.norm(proj - raw.kp2[0], axis=-1).max())


def assemble_track(ctx: TrackCtx) -> dict:
    """Assemble track.json from the finished ctx.

    In: a ctx whose every stage has run. Out: the track dict, with
    ``projection.verified_reproj_px`` still None for the caller's self-check.
    """
    fit, led, raw, sm, shape = ctx.fit, ctx.led, ctx.raw, ctx.sm, ctx.shape
    frames, idx = ctx.frames, led.idx
    focal = raw.focal
    return {
        'schema': 'zyg.pose_track/1',
        'built': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'clip': os.path.abspath(ctx.clip),
        'out_dir': os.path.abspath(ctx.out_dir),
        'fps': ctx.fps,
        'size': [ctx.W, ctx.H],
        'subject': ctx.subject or None,
        'subject_track': {k: v for k, v in fit.sub_info.items() if k != 'box_source'},
        'frames_extracted': len(frames),
        'ledger': {s: led.ledger.count(s) for s in (FOUND, NOT_FOUND, NOT_DETECTABLE, UNMEASURABLE)},
        'ledger_per_frame': led.ledger,
        'fitted_frame_index': idx,
        'fitted_unboxed': int(sum(1 for i in idx if not led.boxed[i])),
        'fitted_box_held': int(sum(1 for i in idx if led.box_src[i] == 'held')),
        'fitted_unboxed_note': (
            'boxed=false means SAM 3 found no instance AND no earlier box could be '
            'held, so SAM 3D Body ran whole-image single-person and may have measured '
            'a DIFFERENT PERSON — never average those in. box_source="held" means the '
            'previous frame box was carried across a one-frame detector dropout: the '
            'subject is right, the box is one frame stale. Per-frame: frames[].boxed '
            'and frames[].box_source.'
        ),
        'projection': {
            'model': 'pinhole, principal point at image centre; u = f*(X+tx)/(Z+tz) + W/2, v = f*(Y+ty)/(Z+tz) + H/2',
            'focal_px': float(np.median(focal)),
            'verified_reproj_px': None,
        },
        'shape_locked': shape.med.tolist(),
        'scale_locked': shape.scale_med.tolist(),
        'shape_lock_applied': False,
        'shape_lock_note': (
            'median over the track, RECORDED not re-synthesised: re-posing the MHR rig '
            'needs pymomentum (conda-only; the PyPI name is an unrelated package). '
            'Downstream geometry uses the estimator per-frame pred_vertices. '
            'mhr_decode_available=%s (%s)' % (fit.dec_ok, fit.dec_why)
        ),
        'shape_drift': {
            'mean_abs_dev': shape.dev,
            'max_abs_dev': shape.dev_max,
            'per_param_std_mean': shape.std,
        },
        'arrays_npz': ctx.npz,
        'faces_npy': fit.meta.get('faces_npy'),
        'arrays_dir': ctx.dirs.arrays,
        'masks_dir': ctx.dirs.masks if ctx.n_masks else None,
        'masks_written': ctx.n_masks,
        'masks_held': ctx.n_held_masks,
        'masks_contiguous': bool(ctx.n_masks == len(idx)),
        # Per STAGE, not per track: the next 1h50m hold has to be attributable to
        # one of these numbers instead of guessed at. lock_wait_* is time spent
        # waiting for OTHER jobs; sam3_s/fit_s is time the GPU lock was actually
        # earning it; extract_s/post_s ran outside the lock entirely.
        'timing': {
            'extract_s': round(ctx.extract_s, 1),
            'lock_wait_sam3_s': round(fit.lock_wait_sam3_s, 1),
            'sam3_s': round(fit.sam3_s, 1),
            'lock_wait_fit_s': round(fit.lock_wait_fit_s, 1),
            'fit_s': round(fit.fit_s, 1),
            'post_s': round(time.time() - ctx.t_post, 1),
            'total_s': round(time.time() - ctx.t_start, 1),
            'fit_seconds': round(fit.fit_s, 1),
            'worker_load_s': fit.meta.get('load_s'),
            'worker_mean_s_per_frame': fit.meta.get('mean_t_s'),
            'total_seconds': round(time.time() - ctx.t_start, 1),
        },
        'metrics': ctx.metrics,
        'frames': [
            {
                'i': k,
                'src_frame': os.path.basename(frames[i]),
                'bbox': [float(v) for v in led.recs[i]['bbox']],
                'focal_length': float(focal[k]),
                'cam_t': sm.cam[k].tolist(),
                'global_rot': sm.grot[k].tolist(),
                'keypoints_2d': np.round(sm.kp2[k], 3).tolist(),
                'keypoints_3d': np.round(sm.kp3[k], 5).tolist(),
                'shape_dev': float(np.abs(raw.shape[k] - shape.med).mean()),
                'boxed': led.boxed[i],
                'box_source': led.box_src[i],
            }
            for k, i in enumerate(idx)
        ],
        'mhr70_to_pose_names': MHR70_TO_POSE,
        'body_pose_dim': int(raw.body_pose.shape[1]),
    }
