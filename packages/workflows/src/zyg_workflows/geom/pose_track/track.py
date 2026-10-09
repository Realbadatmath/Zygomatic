# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pose_track.py — a per-shot POSE TRACK for the VACE control channel (2026-09-02).

Sections 2-5: frames, the subject box track, the temporal filters and
``build_track`` itself.
"""

from __future__ import annotations

from .constants import cv2, exe, glob, json, np, os, subprocess, time
from .track_build import (
    Smoothed,
    TrackCtx,
    assemble_track,
    frame_ledger,
    probe_size,
    reproj_error,
    run_fit,
    save_arrays,
    shape_lock,
    stack_series,
    track_dirs,
    track_metrics,
    write_masks,
)

# ---------------------------------------------------------------- frames


def extract_frames(clip: str, out_dir: str, fps: int = 17, max_frames: int = 0) -> list[str]:
    """Clip -> PNG frames at the RENDER fps. Existing frames are cleared first."""
    os.makedirs(out_dir, exist_ok=True)
    for old in glob.glob(os.path.join(out_dir, 'f_*.png')):
        os.remove(old)
    cmd = [exe('ffmpeg'), '-y', '-hide_banner', '-loglevel', 'error', '-i', clip, '-vf', f'fps={fps}']
    if max_frames:
        cmd += ['-frames:v', str(int(max_frames))]
    cmd += [os.path.join(out_dir, 'f_%05d.png')]
    subprocess.run(cmd, capture_output=True, timeout=1800, check=False)
    return sorted(glob.glob(os.path.join(out_dir, 'f_*.png')))


# ---------------------------------------------------------------- subject track


def _iou(a, b) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0.0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    ua = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    ub = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    den = ua + ub - inter
    return float(inter / den) if den > 0 else 0.0


def subject_track(
    frames: list[str], phrase: str, mask_dir: str, *, threshold: float = 0.4, log=print
) -> tuple[dict, dict, dict]:
    """Per-frame box + mask for the phrase-named subject, by IoU continuity.

    Returns (boxes, masks, info). boxes/masks are {frame_path: value} and only
    contain frames where the subject was found; `info` carries the counts and the
    reason when nothing was found — the caller decides whether to degrade.
    """
    # sam3_service reads its subprocess timeout ONCE at import, from
    # ZYG_SAM3_TIMEOUT_S, defaulting to 300 s — sized for the 8-frame prop-persistence
    # probe it was written for. A whole clip is 80-350 frames and takes far longer, and
    # the failure is silent: the worker is killed, _run_worker returns None, and the
    # track degrades to whole-image single-person without ever saying the box track was
    # lost. Size the budget to the clip before importing (that module is not this
    # session's to edit; the env var is its documented knob).
    os.environ.setdefault('ZYG_SAM3_TIMEOUT_S', str(int(300 + 20 * len(frames))))
    from zyg_workflows import sam3_service

    ok, why = sam3_service.available()
    if not ok:
        return {}, {}, {'ok': False, 'reason': f'sam3 unavailable: {why}'}
    os.makedirs(mask_dir, exist_ok=True)
    req = {'images': list(frames), 'phrases': [phrase], 'threshold': float(threshold), 'save_masks_dir': mask_dir}
    t0 = time.time()
    seg = sam3_service._run_worker(req, log)
    if not seg:
        return {}, {}, {'ok': False, 'reason': 'sam3 worker returned nothing'}
    log('  sam3: %d frames segmented in %.1fs' % (len(seg), time.time() - t0))

    boxes: dict = {}
    masks: dict = {}
    source: dict = {}
    prev = None
    switches = 0
    for f in frames:
        inst = ((seg.get(f) or {}).get(phrase) or {}).get('instances') or []
        inst = [i for i in inst if i.get('mask_px', 0) > 0]
        if not inst:
            continue
        if prev is None:
            pick = max(inst, key=lambda i: i['score'])
        else:
            # continuity first: the box that overlaps the previous one most, with
            # score only breaking ties. Picking per-frame max score is how a
            # two-hander swaps subjects mid-clip.
            scored = [(_iou(prev, i['box_xyxy']), i['score'], i) for i in inst]
            scored.sort(key=lambda s: (round(s[0], 3), s[1]), reverse=True)
            pick = scored[0][2]
            if scored[0][0] < 0.2:
                switches += 1
        boxes[f] = [float(v) for v in pick['box_xyxy']]
        source[f] = 'sam3'
        if pick.get('mask_path'):
            masks[f] = pick['mask_path']
        prev = boxes[f]

    # FILL SAM 3's DROPOUTS BY HOLDING THE LAST BOX. Measured on the driver clip
    # 2026-09-02: SAM 3 missed the subject on 5 of 79 frames, scattered singly. Left
    # empty, SAM 3D Body falls back to whole-image single-person on exactly those
    # frames — and in a two-hander that fits the OTHER man. Those 5 frames were the
    # entire reason the first track lost to its own two-pose-lerp null (mean 29.1 px
    # vs 23.2; excluding them and the neighbours the smoother spread them into, 20.0
    # vs 21.7). A one-frame detector dropout is not the subject leaving the shot, so
    # the last known box is held across it and the frame is FLAGGED, never silently
    # re-fitted on whoever else is in frame.
    held = 0
    last = None
    for f in frames:
        if f in boxes:
            last = boxes[f]
        elif last is not None:
            boxes[f] = list(last)
            source[f] = 'held'
            held += 1
    first = next((f for f in frames if source.get(f) == 'sam3'), None)
    if first is not None:  # back-fill any leading gap
        for f in frames:
            if f == first:
                break
            if f not in boxes:
                boxes[f] = list(boxes[first])
                source[f] = 'held'
                held += 1
    return (
        boxes,
        masks,
        {
            'ok': bool(boxes),
            'phrase': phrase,
            'frames_with_subject': sum(1 for v in source.values() if v == 'sam3'),
            'frames_box_held': held,
            'frames_no_box': len(frames) - len(boxes),
            'frames_total': len(frames),
            'low_overlap_steps': switches,
            'box_source': {f: source[f] for f in source},
            'sam3_seconds': round(time.time() - t0, 1),
        },
    )


# ---------------------------------------------------------------- filtering


def _savgol(x: np.ndarray, window: int = 9, order: int = 2) -> np.ndarray:
    """Savitzky-Golay along axis 0, implemented directly (no scipy dependency).

    Edges use the shortest odd window that fits, so the first and last frames are
    smoothed less rather than reflected — a reflected edge invents motion that the
    clip does not contain.
    """
    n = x.shape[0]
    if n < 3 or window < 3:
        return x.copy()
    window = min(window if window % 2 else window + 1, n if n % 2 else n - 1)
    if window < 3:
        return x.copy()
    half = window // 2
    flat = x.reshape(n, -1).astype(np.float64)
    out = np.empty_like(flat)
    for i in range(n):
        h = min(half, i, n - 1 - i)
        if h < 1:
            out[i] = flat[i]
            continue
        k = min(order, 2 * h)
        t = np.arange(-h, h + 1, dtype=np.float64)
        V = np.vander(t, k + 1, increasing=True)
        coef = np.linalg.pinv(V) @ flat[i - h : i + h + 1]
        out[i] = coef[0]  # value of the fit at t = 0
    return out.reshape(x.shape).astype(x.dtype)


def _one_euro(x: np.ndarray, fps: float, min_cutoff: float = 1.0, beta: float = 0.02) -> np.ndarray:
    """One-euro filter along axis 0 — low lag on fast motion, low jitter when still."""
    n = x.shape[0]
    if n < 2:
        return x.copy()
    flat = x.reshape(n, -1).astype(np.float64)
    out = np.empty_like(flat)
    te = 1.0 / max(fps, 1e-6)

    def alpha(cut):
        tau = 1.0 / (2.0 * np.pi * np.maximum(cut, 1e-6))
        return 1.0 / (1.0 + tau / te)

    out[0] = flat[0]
    dx_hat = np.zeros(flat.shape[1])
    a_d = alpha(1.0)
    for i in range(1, n):
        dx = (flat[i] - out[i - 1]) / te
        dx_hat = a_d * dx + (1 - a_d) * dx_hat
        a = alpha(min_cutoff + beta * np.abs(dx_hat))
        out[i] = a * flat[i] + (1 - a) * out[i - 1]
    return out.reshape(x.shape).astype(x.dtype)


def _rotvec(R: np.ndarray) -> np.ndarray:
    """(...,3,3) rotation matrices -> (...,3) rotation vectors, via cv2.Rodrigues."""
    sh = R.shape[:-2]
    flat = R.reshape(-1, 3, 3)
    out = np.empty((flat.shape[0], 3), np.float64)
    for i in range(flat.shape[0]):
        v, _ = cv2.Rodrigues(flat[i].astype(np.float64))
        out[i] = v.ravel()
    return out.reshape(sh + (3,))


def rotvec_to_matrix(v: np.ndarray) -> np.ndarray:
    """(...,3) rotation vectors -> (...,3,3) matrices — the inverse of the conversion
    the track stores. `track_arrays.npz` keeps joint rotations as ROTATION VECTORS,
    not matrices, because a temporal filter applied to the nine elements of a rotation
    matrix does not produce a rotation matrix; this is how a consumer gets matrices
    back."""
    sh = v.shape[:-1]
    flat = v.reshape(-1, 3)
    out = np.empty((flat.shape[0], 3, 3), np.float64)
    for i in range(flat.shape[0]):
        M, _ = cv2.Rodrigues(flat[i].astype(np.float64))
        out[i] = M
    return out.reshape(sh + (3, 3))


def _unwrap_rotvec(v: np.ndarray) -> np.ndarray:
    """Rodrigues vectors are 2*pi-ambiguous; a raw filter across a wrap invents a
    spin. Re-express each frame on the branch nearest the previous one."""
    out = v.copy().astype(np.float64)
    for i in range(1, out.shape[0]):
        a = out[i]
        theta = np.linalg.norm(a, axis=-1, keepdims=True)
        with np.errstate(invalid='ignore', divide='ignore'):
            axis = np.where(theta > 1e-8, a / np.maximum(theta, 1e-8), 0.0)
        alt = axis * (theta - 2 * np.pi)
        d0 = np.linalg.norm(a - out[i - 1], axis=-1)
        d1 = np.linalg.norm(alt - out[i - 1], axis=-1)
        out[i] = np.where((d1 < d0)[..., None], alt, a)
    return out


def smooth_series(arr: np.ndarray, mode: str, fps: float, *, rot: bool = False, window: int = 9) -> np.ndarray:
    if mode == 'none' or arr.shape[0] < 3:
        return arr.copy()
    x = arr
    if rot:
        x = _unwrap_rotvec(x)
    y = _one_euro(x, fps) if mode == 'oneeuro' else _savgol(x, window=window)
    return y


# ---------------------------------------------------------------- the track


def build_track(
    clip: str,
    out_dir: str,
    *,
    subject: str = '',
    fps: int = 17,
    max_frames: int = 0,
    smooth: str = 'savgol',
    window: int = 9,
    threshold: float = 0.4,
    log=print,
) -> dict:
    """The whole chain. Returns the track dict (also written to <out>/track.json)."""
    if cv2 is None:
        raise RuntimeError('cv2 required')
    from zyg_workflows import sam3d_body_service as S3B

    os.makedirs(out_dir, exist_ok=True)
    dirs = track_dirs(out_dir)
    ctx = TrackCtx(
        clip=clip,
        out_dir=out_dir,
        subject=subject,
        fps=fps,
        smooth=smooth,
        window=window,
        dirs=dirs,
        log=log,
    )

    ctx.frames = extract_frames(clip, dirs.frames, fps=fps, max_frames=max_frames)
    ctx.extract_s = time.time() - ctx.t_start
    ctx.W, ctx.H = probe_size(ctx)

    ok, why = S3B.available()
    if not ok:
        raise RuntimeError(f'SAM 3D Body unavailable: {why}')

    # subject_track is passed in rather than imported, so track_build never has to
    # import the module that imports it.
    ctx.fit = run_fit(ctx, S3B, subject_track, threshold=threshold)
    ctx.led = frame_ledger(ctx)
    ctx.raw = stack_series(ctx.led)
    # recorded; see the module header for why the shape lock is not applied
    ctx.shape = shape_lock(ctx.raw)

    # ---- temporal filter. Joint rotations are filtered as ROTATION VECTORS:
    # smoothing the nine elements of a rotation matrix does not give a rotation.
    raw = ctx.raw
    ctx.sm = Smoothed(
        kp3=smooth_series(raw.kp3, smooth, fps, window=window),
        kp2=smooth_series(raw.kp2, smooth, fps, window=window),
        cam=smooth_series(raw.cam_t, smooth, fps, window=window),
        grot=smooth_series(raw.grot, smooth, fps, rot=True, window=window),
        jrv=smooth_series(_rotvec(raw.jrot), smooth, fps, rot=True, window=window),
        verts=smooth_series(raw.verts.astype(np.float64), smooth, fps, window=window).astype(np.float32),
        jco=smooth_series(raw.jcoord, smooth, fps, window=window),
    )

    ctx.metrics = track_metrics(ctx)
    ctx.n_masks, ctx.n_held_masks = write_masks(ctx)
    ctx.npz = save_arrays(ctx)

    track = assemble_track(ctx)
    # projection self-check on the first fitted frame: the model in `projection` must
    # reproduce the estimator's own 2D keypoints, or every plate is drawn wrong.
    track['projection']['verified_reproj_px'] = reproj_error(raw, ctx.W, ctx.H)

    with open(os.path.join(out_dir, 'track.json'), 'w', encoding='utf-8') as fh:
        json.dump(track, fh, indent=1)
    log('  track: %s' % os.path.join(out_dir, 'track.json'))
    return track
