# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""vace_control.py — Phase 4: fill the VACE control channel with rendered geometry.

RUN:
    python3 -m zyg_workflows.geom.vace_control <pass_set_or_frames_dir> --frames 341 -o <ctrl_dir>
    python3 -m zyg_workflows.geom.vace_control <dir> --audit        # measure an existing ctrl_dir

THE DEFECT, IN ONE LINE OF SOMEONE ELSE'S CODE.
wan_vace_service.py builds every control frame as

    ctrl = still * (1 - mask) + 127 * mask

so wherever VACE is asked to generate, it is handed a CONSTANT. Measured consequences on
scene20_v15: the region inside the generate mask was 100.0% of the pipe and 95.4% of the
book, edge-correlation against frame 0 fell to 0.201 and 0.164 respectively, and both props
were re-invented in each of six context windows. prop_control.py fixed that for the book by
warping a rendered plate in through a homography — necessary because the plate underneath
came out of a generator and had no camera to match.

FOR A SCENE WE RENDER, THERE IS NO HOMOGRAPHY TO SOLVE. The camera is ours, the geometry is
ours, and the control frame simply IS the render. That removes the alignment step, the
four-corner correspondence and the whole class of drift it was compensating for.

WHY THIS ENDS THE DECAY RATHER THAN REDUCING IT.
The measured failure was that prop fidelity falls off with elapsed generated time — about
0 at frame 80, -0.21 and -0.34 by frame 200, reproduced on v28 and v30. That is a memory
effect: the model is being asked to REMEMBER the prop across windows. Here the prop is
RE-STATED on every single frame, so there is nothing to remember and nothing to forget. The
decay does not get smaller; it has nothing left to act on.

THE AUDIT IS THE POINT. `audit()` measures what fraction of each control frame is still
flat grey. A control directory that is 100% grey inside the mask looks completely normal on
disk and in any log — it is the defect's natural resting state — so it is measured rather
than assumed, and `main()` exits non-zero when the channel is still constant.
"""

import glob
import os

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

GREY = 127
GREY_TOL = 2.0  # same tolerance prop_control.py uses to call a pixel "untouched"


def _frames_in(path):
    """Rendered frames, whether given as a frames dir or a pass-set dir."""
    if os.path.isfile(path):
        return [path]
    hits = sorted(glob.glob(os.path.join(path, 'frame_*.png')))
    if hits:
        return hits
    hits = sorted(glob.glob(os.path.join(path, '*', 'rgb.png')))
    if hits:
        return hits
    p = os.path.join(path, 'rgb.png')
    return [p] if os.path.exists(p) else []


def grey_fraction(img):
    """Share of pixels that are flat grey 127 — the signature of the unfilled channel."""
    a = np.asarray(img, dtype=np.float32)
    if a.ndim == 2:
        a = a[:, :, None]
    return float((np.abs(a - GREY).max(axis=2) < GREY_TOL).mean())


def build(src, out_dir, frames=341, size=None, mask_dir=None, still_bg=None):
    """Write `frames` control frames from rendered geometry.

    src       : a pass-set dir, a frames dir, or a single rendered image
    frames    : length of the clip. A single source image is held for the whole clip, which
                is correct for anything world-static — the tree does not move.
    mask_dir  : optional per-frame generate masks. Where a mask is given, the render fills
                ONLY the masked region and the plate is left alone elsewhere, so this drops
                into the existing service without changing what it composites.
    """
    if cv2 is None:
        raise RuntimeError('cv2 required')
    srcs = _frames_in(src)
    if not srcs:
        raise FileNotFoundError('no rendered frames under %s' % src)
    masks = sorted(glob.glob(os.path.join(mask_dir, '*.png'))) if mask_dir else []
    bg = cv2.imread(still_bg) if still_bg else None

    os.makedirs(out_dir, exist_ok=True)
    for old in glob.glob(os.path.join(out_dir, '*.png')):
        os.remove(old)

    written, greys = [], []
    for i in range(frames):
        img = cv2.imread(srcs[min(i, len(srcs) - 1)], cv2.IMREAD_UNCHANGED)
        if img is None:
            continue
        if img.ndim == 3 and img.shape[2] == 4:
            img = img[:, :, :3]
        if size and (img.shape[1], img.shape[0]) != tuple(size):
            img = cv2.resize(img, tuple(size), interpolation=cv2.INTER_AREA)
        if masks:
            m = cv2.imread(masks[min(i, len(masks) - 1)], cv2.IMREAD_GRAYSCALE)
            if m is not None:
                if m.shape[:2] != img.shape[:2]:
                    m = cv2.resize(m, (img.shape[1], img.shape[0]))
                base = bg if bg is not None else img
                if base.shape[:2] != img.shape[:2]:
                    base = cv2.resize(base, (img.shape[1], img.shape[0]))
                a = (m.astype(np.float32) / 255.0)[:, :, None]
                img = img.astype(np.float32) * a + base.astype(np.float32) * (1 - a)
                img = img.astype(np.uint8)
        p = os.path.join(out_dir, 'ctrl_%05d.png' % i)
        cv2.imwrite(p, img)
        written.append(p)
        greys.append(grey_fraction(img))

    return {
        'ctrl_dir': out_dir,
        'frames': len(written),
        'source_frames': len(srcs),
        'grey_fraction_mean': round(float(np.mean(greys)) if greys else 1.0, 6),
        'grey_fraction_max': round(float(np.max(greys)) if greys else 1.0, 6),
    }


def audit(ctrl_dir, sample=24):
    """How much of this control channel is still a constant?"""
    hits = sorted(glob.glob(os.path.join(ctrl_dir, '*.png')))
    if not hits:
        return {'ok': False, 'reason': 'no frames in %s' % ctrl_dir}
    step = max(1, len(hits) // sample)
    fr = []
    for p in hits[::step]:
        img = cv2.imread(p, cv2.IMREAD_UNCHANGED)
        if img is not None:
            fr.append(grey_fraction(img))
    mean = float(np.mean(fr)) if fr else 1.0
    return {
        'ok': mean < 0.05,
        'frames': len(hits),
        'sampled': len(fr),
        'grey_fraction_mean': round(mean, 6),
        'verdict': (
            'geometry'
            if mean < 0.05
            else 'STILL CONSTANT — VACE is being handed flat grey %d over %.1f%% of '
            'the frame and will re-invent whatever lives there' % (GREY, mean * 100)
        ),
    }


if __name__ == '__main__':  # the CLI lives in vace_control_cli
    from zyg_workflows.geom.vace_control_cli import main as _cli_main

    raise SystemExit(_cli_main())
