# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""wan_setlock.py — set-lock composite post-pass for locked-camera WAN clips.

Problem (2026-07-29 morph research): single-still I2V re-synthesizes every pixel of every
frame, so on a locked shot the SET (walls, furniture, props) slowly morphs even though
nothing should move. Structural cure: composite the living regions of the generated video
back over the ORIGINAL still, so the set is pixel-stable by construction.

Matte strategy (no extra models, commercially clean): real character/flame motion is FAST
(large consecutive-frame deltas) while set morphing is SLOW (small per-frame drift that only
accumulates). The union of fast frame-to-frame changes across the clip therefore outlines
exactly the regions that are genuinely alive. That union — dilated, closed and feathered,
as ONE static matte (per-frame mattes would flicker) — keeps the video's characters while
everything outside snaps to the still. Frames are color-matched to the still first so
global color creep can't produce seams at the matte edge.

Upgrade path: swap the motion matte for a SAM2 character matte (Apache-2.0) for tighter
silhouettes; the compositing/color logic stays identical.
"""

import os
import glob
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageFilter
import logging as _zyg_logging
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


def _log_noop(_m):
    pass


def _color_match(frame_arr, ref_mean, ref_std):
    out = np.empty_like(frame_arr)
    for ch in range(3):
        t = frame_arr[:, :, ch]
        ts = max(float(t.std()), 1e-4)
        out[:, :, ch] = (t - float(t.mean())) * (ref_std[ch] / ts) + ref_mean[ch]
    return np.clip(out, 0.0, 255.0)


def _stabilize_frames(frames, log):
    """Digital tripod: estimate each frame's global affine motion (zoom/pan/rot) vs frame 0
    via ECC and warp it back. Cancels WAN's uncommanded push-in so the motion matte only
    sees genuine subject motion. In-place overwrite of the frame files. Returns the mean
    absolute scale drift (0 = perfectly static camera)."""
    import cv2
    import numpy as np
    from PIL import Image

    ref = cv2.cvtColor(np.asarray(Image.open(frames[0]).convert('RGB')), cv2.COLOR_RGB2GRAY)
    ref_small = cv2.resize(ref, (ref.shape[1] // 2, ref.shape[0] // 2))
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-5)
    drifts = []
    for fp in frames[1:]:
        img = np.asarray(Image.open(fp).convert('RGB'))
        g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        g_small = cv2.resize(g, (ref_small.shape[1], ref_small.shape[0]))
        warp = np.eye(2, 3, dtype=np.float32)
        try:
            cv2.findTransformECC(ref_small, g_small, warp, cv2.MOTION_EUCLIDEAN, crit, None, 3)
            # euclidean at half-res → scale translation up; add scale via similarity pass
            warp2 = np.eye(2, 3, dtype=np.float32)
            try:
                cv2.findTransformECC(ref_small, g_small, warp2, cv2.MOTION_AFFINE, crit, None, 3)
                warp = warp2
            except cv2.error as _exc:
                _zyg_log.debug('affine ECC pass failed for %s, keeping the euclidean warp: %s', fp, _exc)
            warp_full = warp.copy()
            warp_full[:, 2] *= 2.0
            drifts.append(abs(float(warp[0, 0]) - 1.0) + abs(float(warp[1, 1]) - 1.0))
            fixed = cv2.warpAffine(
                img,
                cv2.invertAffineTransform(warp_full),
                (img.shape[1], img.shape[0]),
                flags=cv2.INTER_LANCZOS4,
                borderMode=cv2.BORDER_REPLICATE,
            )
            Image.fromarray(fixed).save(fp)
        except cv2.error:
            drifts.append(0.0)
    md = float(np.mean(drifts)) if drifts else 0.0
    log(f'[setlock] stabilized {len(frames) - 1} frames (mean scale drift {md:.4f})')
    return md


def lock_background(
    clip_path,
    still_path,
    out_path,
    fps=24,
    motion_thr=14.0,
    dilate_px=25,
    feather_px=19,
    min_keep_ratio=0.02,
    stabilize=True,
    extra_keep_mask=None,
    log_fn=None,
):
    """Composite the clip's moving regions over the original still. Returns out_path or
    None (fail-safe: caller keeps the raw clip). motion_thr is the consecutive-frame delta
    (0-255) above which a pixel counts as genuinely moving."""
    log = log_fn or _log_noop
    if not (os.path.isfile(clip_path) and os.path.isfile(still_path)):
        log('[setlock] missing clip/still')
        return None
    tmp = tempfile.mkdtemp(prefix='setlock_')
    try:
        # 1) explode clip to frames
        r = subprocess.run(
            [
                exe('ffmpeg'),
                '-y',
                '-loglevel',
                'error',
                '-i',
                clip_path,
                '-vsync',
                '0',
                os.path.join(tmp, 'f_%05d.png'),
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            log(f'[setlock] ffmpeg extract failed: {r.stderr[:120]}')
            return None
        frames = sorted(glob.glob(os.path.join(tmp, 'f_*.png')))
        if len(frames) < 8:
            log(f'[setlock] too few frames ({len(frames)})')
            return None
        if stabilize:
            try:
                _stabilize_frames(frames, log)  # cancel push-in/pan BEFORE the matte
            except Exception as e:
                log(f'[setlock] stabilization skipped ({e})')
        first = Image.open(frames[0]).convert('RGB')
        W, H = first.size
        still = Image.open(still_path).convert('RGB').resize((W, H), Image.LANCZOS)
        still_arr = np.asarray(still, dtype=np.float32)
        ref_mean = [float(still_arr[:, :, c].mean()) for c in range(3)]
        ref_std = [max(float(still_arr[:, :, c].std()), 1e-4) for c in range(3)]

        # 2) motion envelope: union of FAST consecutive-frame changes (slow morph excluded)
        env = np.zeros((H, W), dtype=np.float32)
        prev = np.asarray(first.convert('L'), dtype=np.float32)
        for fp in frames[1:]:
            cur = np.asarray(Image.open(fp).convert('L'), dtype=np.float32)
            d = np.abs(cur - prev)
            env = np.maximum(env, d)
            prev = cur
        mask = (env >= float(motion_thr)).astype(np.uint8) * 255
        # guards judge the MOTION ratio only — a deliberate extra_keep_mask (char boxes)
        # legitimately covers most of the frame and must not trip the camera-drift guard
        keep_ratio = float((mask > 0).mean())
        if extra_keep_mask and os.path.isfile(extra_keep_mask):
            ek = np.asarray(Image.open(extra_keep_mask).convert('L').resize((W, H)), dtype=np.uint8)
            mask = np.maximum(mask, (ek > 127).astype(np.uint8) * 255)
        if keep_ratio < min_keep_ratio:
            # almost nothing moves fast — matte would freeze the characters too; bail out
            log(f'[setlock] motion envelope too small ({keep_ratio:.3f}) — skipping lock')
            return None
        if keep_ratio > 0.58:
            # near-global fast motion = camera drift/zoom survived generation; compositing a
            # static still under a moving camera would glitch. Surface it instead of no-opping.
            log(
                f'[setlock] GLOBAL camera motion detected (raw motion {keep_ratio:.2f}) — '
                f'set-lock ineffective on this clip; use the VACE path for a hard camera lock'
            )
            return None
        m = Image.fromarray(mask, mode='L')
        m = m.filter(ImageFilter.MaxFilter(dilate_px if dilate_px % 2 else dilate_px + 1))
        m = m.filter(ImageFilter.MaxFilter(11)).filter(ImageFilter.MinFilter(7))  # close holes
        m = m.filter(ImageFilter.GaussianBlur(feather_px))
        matte = np.asarray(m, dtype=np.float32)[:, :, None] / 255.0
        log(
            f'[setlock] matte covers {float((matte > 0.5).mean()) * 100:.1f}% of frame '
            f'(raw motion {keep_ratio * 100:.1f}%)'
        )

        # 3) per-frame: color-match to the still, then composite through the static matte
        outdir = os.path.join(tmp, 'out')
        os.makedirs(outdir, exist_ok=True)
        for i, fp in enumerate(frames):
            fr = np.asarray(Image.open(fp).convert('RGB'), dtype=np.float32)
            fr = _color_match(fr, ref_mean, ref_std)
            comp = still_arr * (1.0 - matte) + fr * matte
            Image.fromarray(comp.astype('uint8')).save(os.path.join(outdir, f'o_{i:05d}.png'))

        # 4) re-encode
        r = subprocess.run(
            [
                exe('ffmpeg'),
                '-y',
                '-loglevel',
                'error',
                '-framerate',
                str(fps),
                '-i',
                os.path.join(outdir, 'o_%05d.png'),
                '-c:v',
                'libx264',
                '-pix_fmt',
                'yuv420p',
                '-crf',
                '17',
                out_path,
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0 or not os.path.isfile(out_path):
            log(f'[setlock] encode failed: {r.stderr[:120]}')
            return None
        log(f'[setlock] set-locked clip → {os.path.basename(out_path)}')
        return out_path
    except Exception as e:
        log(f'[setlock] failed ({e}) — keeping raw clip')
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
