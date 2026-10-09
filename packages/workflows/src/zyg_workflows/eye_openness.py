# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""eye_openness.py — are the eyes OPEN? (2026-08-03)

WHY THIS EXISTS — I WAS MEASURING THE WRONG THING FOR SIX RENDERS.

The operator's note was: "abel doesnt have to open his eyes wide, when i told you his
eyes need to open is because they we're almost closed the entire 20 seconds".

That is a request about EYELID APERTURE — a static property of each frame. Everything I
had been optimising was `face flow_median` from qc_character_balance, which measures
MOTION. The two are not the same and can move in opposite directions: v15 scored best on
flow (0.305) because a startled wide-eyed stare CHANGES a lot between frames, and the
operator rejected exactly that look. A calm face with normally open eyes can score low on
flow and still be precisely what was asked for.

So this measures aperture directly, via MediaPipe FaceLandmarker (already vendored at
data/models/mediapipe/face_landmarker.task, Apache-2.0):

    EAR = mean(vertical lid separation) / horizontal eye width

per eye, per frame. It is scale-invariant, which matters because the two characters are
at different distances and Abel's face is the smaller of the two.

REFERENCE BANDS (the standard blink literature, and they match what we see here):
    EAR >= 0.25   comfortably open
    0.15-0.25     partly lidded / mid-blink
    EAR < 0.15    effectively closed
A real blink is a brief dip; "almost closed the entire 20 seconds" is a LOW MEDIAN, which
is what open_frac and the median below are for. Blink RATE is reported separately so a
character who never blinks at all is also visible — that reads as dead in a different way.
"""

import os

from zyg_workflows import paths
from zyg_workflows.bin import exe

MODEL_DIR = paths.ZYG_MP_MODEL_DIR
FACE_TASK = os.path.join(MODEL_DIR, 'face_landmarker.task')

# MediaPipe FaceMesh indices. Vertical pairs are sampled at two positions across each lid
# so a single mis-fit landmark cannot swing the reading.
LEFT_EYE = {'h': (33, 133), 'v': ((159, 145), (158, 153))}
RIGHT_EYE = {'h': (362, 263), 'v': ((386, 374), (385, 380))}

OPEN_EAR = float(os.environ.get('ZYG_EYE_OPEN_EAR', '0.25'))
CLOSED_EAR = float(os.environ.get('ZYG_EYE_CLOSED_EAR', '0.15'))


def _log_noop(_m):
    pass


def _ear(lm, eye, w, h):
    import math

    (h0, h1) = eye['h']
    x0, y0 = lm[h0].x * w, lm[h0].y * h
    x1, y1 = lm[h1].x * w, lm[h1].y * h
    horiz = math.hypot(x1 - x0, y1 - y0)
    if horiz < 1e-6:
        return None
    vs = []
    for a, b in eye['v']:
        ax, ay = lm[a].x * w, lm[a].y * h
        bx, by = lm[b].x * w, lm[b].y * h
        vs.append(math.hypot(bx - ax, by - ay))
    return (sum(vs) / len(vs)) / horiz


def measure(clip_path, box=None, fps_sample=2, max_frames=200, log_fn=None):
    """-> dict with per-frame EAR stats for the largest face in `box`.

    box: (x0,y0,x1,y1) fractional crop to isolate ONE character before detection —
    without it the detector may lock onto the other person in a two-hander.
    """
    log = log_fn or _log_noop
    try:
        import glob
        import subprocess
        import tempfile
        import numpy as np
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision
    except Exception as e:
        log(f'[eye] deps unavailable ({e})')
        return {'error': str(e)[:200]}
    if not os.path.isfile(FACE_TASK):
        log(f'[eye] face_landmarker.task missing at {FACE_TASK}')
        return {'error': 'face_landmarker.task missing'}
    tmp = tempfile.mkdtemp(prefix='eye_')
    try:
        vf = f'fps={fps_sample}'
        if box:
            x0, y0, x1, y1 = box
            vf = f'crop=iw*{x1 - x0:.4f}:ih*{y1 - y0:.4f}:iw*{x0:.4f}:ih*{y0:.4f},scale=512:-2,{vf}'
        r = subprocess.run(
            [exe('ffmpeg'), '-y', '-loglevel', 'error', '-i', clip_path, '-vf', vf, os.path.join(tmp, 'f_%05d.png')],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            return {'error': (r.stderr or '')[-200:]}
        frames = sorted(glob.glob(os.path.join(tmp, 'f_*.png')))[:max_frames]
        if not frames:
            return {'error': 'no frames'}
        opts = mp_vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=FACE_TASK),
            running_mode=mp_vision.RunningMode.IMAGE,
            num_faces=1,
        )
        ears, missing = [], 0
        with mp_vision.FaceLandmarker.create_from_options(opts) as det:
            for fp in frames:
                img = mp.Image.create_from_file(fp)
                res = det.detect(img)
                if not res.face_landmarks:
                    missing += 1
                    continue
                lm = res.face_landmarks[0]
                h, w = img.height, img.width
                le, re_ = _ear(lm, LEFT_EYE, w, h), _ear(lm, RIGHT_EYE, w, h)
                vals = [v for v in (le, re_) if v is not None]
                if vals:
                    ears.append(sum(vals) / len(vals))
        if not ears:
            return {'error': f'no face detected in {len(frames)} frames'}
        a = np.array(ears, dtype=float)
        # a blink is a dip below CLOSED that recovers; count downward crossings
        below = a < CLOSED_EAR
        blinks = int(((~below[:-1]) & below[1:]).sum())
        out = {
            'n_frames': len(frames),
            'n_measured': int(a.size),
            'n_missing': missing,
            'ear_median': round(float(np.median(a)), 4),
            'ear_mean': round(float(a.mean()), 4),
            'ear_p10': round(float(np.percentile(a, 10)), 4),
            'ear_p90': round(float(np.percentile(a, 90)), 4),
            'open_frac': round(float((a >= OPEN_EAR).mean()), 4),
            'closed_frac': round(float((a < CLOSED_EAR).mean()), 4),
            'blinks': blinks,
            'blinks_per_min': round(blinks / max(len(frames) / fps_sample / 60.0, 1e-6), 1),
            'open_ear': OPEN_EAR,
            'closed_ear': CLOSED_EAR,
        }
        out['verdict'] = (
            'OPEN'
            if out['ear_median'] >= OPEN_EAR
            else 'MOSTLY CLOSED'
            if out['ear_median'] < CLOSED_EAR
            else 'PARTLY LIDDED'
        )
        log(
            f'[eye] {os.path.basename(clip_path)}: EAR median {out["ear_median"]} '
            f'({out["verdict"]}), open {100 * out["open_frac"]:.0f}% of frames, '
            f'closed {100 * out["closed_frac"]:.0f}%, {out["blinks"]} blinks'
        )
        return out
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    import json
    import sys

    def _lg(m):
        print(m, flush=True)

    if len(sys.argv) < 2:
        print('usage: eye_openness.py CLIP [x0 y0 x1 y1]')
        sys.exit(2)
    bx = tuple(float(v) for v in sys.argv[2:6]) if len(sys.argv) >= 6 else None
    print(json.dumps(measure(sys.argv[1], box=bx, log_fn=_lg), indent=1))
