#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""lipsync_receipt.py — one InfiniteTalk take + the receipt that proves it moved.

Run it UNDER the GPU lock, e.g.

    flock -w 7200 "${ZYG_GPU_LOCK:-$HOME/.zyg_gpu.lock}" -c \
      '"../.venv/bin/python" scripts/lipsync_receipt.py SRC WAV OUT_DIR'

Writes OUT_DIR/receipt.json with wall_s, vram_peak_mb, mp4, frames, fps, the
audio/video duration agreement (ffprobe, must be within 0.1 s) and the mouth-motion
check: mean absolute inter-frame difference inside the LOWER 40 % of the head box
must be more than twice the same measure on the UPPER 40 %. The head box comes from
geom.keypoints on frame 1 of the produced clip.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import lipsync_service as LS  # noqa: E402


def gpu_used_mb():
    try:
        r = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return int(r.stdout.strip().splitlines()[0])
    except Exception:
        return 0


class VramPoller(threading.Thread):
    def __init__(self, period=2.0):
        super().__init__(daemon=True)
        self.period, self.peak, self.stop = period, 0, threading.Event()

    def run(self):
        while not self.stop.is_set():
            self.peak = max(self.peak, gpu_used_mb())
            self.stop.wait(self.period)


def head_box(png):
    """(x0,y0,x1,y1) head box on one frame, via the repo's keypoint cascade.

    The face-landmark bbox is preferred when it exists: on a close-up portrait the
    shoulder-scaled body head crop saturates the frame (it returned the whole
    832x480 on the canon still), which would make "lower 40 % of the head" a
    full-width band of background rather than a mouth region.
    """
    from zyg_workflows.geom import keypoints as KP

    det = KP.detect(png)
    if det.face is not None and det.face.ok:
        p = det.face.pts
        x0, y0 = float(p[:, 0].min()), float(p[:, 1].min())
        x1, y1 = float(p[:, 0].max()), float(p[:, 1].max())
        pad_x, pad_y = (x1 - x0) * 0.10, (y1 - y0) * 0.10
        return (
            int(max(0, x0 - pad_x)),
            int(max(0, y0 - pad_y)),
            int(min(det.w, x1 + pad_x)),
            int(min(det.h, y1 + pad_y)),
        ), 'face_bbox'
    if det.body is not None and det.body.ok:
        box = KP._head_crop(det.body.pts, det.w, det.h)
        if box:
            return box, 'body_head_crop'
    return None, 'no_detection'


def mean_abs_frame_diff(frames_dir, box):
    """Mean |frame[i] - frame[i-1]| over a box, in 0-255 grey levels."""
    import cv2
    import numpy as np

    x0, y0, x1, y1 = box
    paths = sorted(os.path.join(frames_dir, f) for f in os.listdir(frames_dir) if f.endswith('.png'))
    prev, acc = None, []
    for p in paths:
        g = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        crop = g[y0:y1, x0:x1].astype(np.float32)
        if prev is not None:
            acc.append(float(np.abs(crop - prev).mean()))
        prev = crop
    return (sum(acc) / len(acc)) if acc else 0.0, len(paths)


def main():
    src, wav, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    poller = VramPoller()
    poller.start()
    t0 = time.time()
    mp4 = LS.lipsync(src, wav, out_dir, width=832, height=480, log_fn=lambda m: print(m, flush=True))
    wall_s = round(time.time() - t0, 1)
    poller.stop.set()
    poller.join(timeout=5)

    rec = {
        'src': src,
        'wav': wav,
        'wall_s': wall_s,
        'vram_peak_mb': poller.peak,
        'mp4': mp4,
        'native_fps': LS.NATIVE_FPS,
        'note': (
            'InfiniteTalk generates at 25 fps; an image source has no fps '
            'of its own so the take keeps 25 and no resample was needed.'
        ),
    }
    if not mp4:
        rec['ok'] = False
        rec['error'] = 'lipsync returned None'
        _write(out_dir, rec)
        return 1

    rec['frames'] = LS.probe_frames(mp4)
    rec['fps'] = LS.probe_fps(mp4)
    v_dur = LS.probe_duration_s(mp4)
    a_dur = LS.probe_duration_s(wav)
    rec['sync_check'] = {
        'video_duration_s': v_dur,
        'audio_duration_s': a_dur,
        'delta_s': round(abs((v_dur or 0) - (a_dur or 0)), 4),
        'tolerance_s': 0.1,
        'ok': v_dur is not None and a_dur is not None and abs(v_dur - a_dur) <= 0.1,
    }

    frames_dir = os.path.join(out_dir, 'frames')
    if os.path.isdir(frames_dir):
        shutil.rmtree(frames_dir)  # a shorter take must not read stale frames
    os.makedirs(frames_dir, exist_ok=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', mp4, os.path.join(frames_dir, 'f_%05d.png')], check=True)
    first = os.path.join(frames_dir, 'f_00001.png')
    box, via = head_box(first)
    if box:
        x0, y0, x1, y1 = box
        h = y1 - y0
        lower = (x0, int(y1 - 0.40 * h), x1, y1)
        upper = (x0, y0, x1, int(y0 + 0.40 * h))
        lo, n = mean_abs_frame_diff(frames_dir, lower)
        up, _ = mean_abs_frame_diff(frames_dir, upper)
        rec['mouth_motion'] = {
            'head_box': list(box),
            'head_box_via': via,
            'lower_face_box': list(lower),
            'upper_face_box': list(upper),
            'lower_mean_abs_diff': round(lo, 4),
            'upper_mean_abs_diff': round(up, 4),
            'ratio': round(lo / up, 3) if up else None,
            'threshold': 2.0,
            'frames_compared': n,
            'ok': bool(up and lo / up > 2.0),
        }
    else:
        rec['mouth_motion'] = {'ok': False, 'head_box_via': via, 'error': 'no head box on frame 1'}
    rec['ok'] = bool(rec['sync_check']['ok'] and rec['mouth_motion'].get('ok'))
    _write(out_dir, rec)
    return 0 if rec['ok'] else 2


def _write(out_dir, rec):
    p = os.path.join(out_dir, 'receipt.json')
    with open(p, 'w') as fh:
        json.dump(rec, fh, indent=2)
    print(json.dumps(rec, indent=2), flush=True)


if __name__ == '__main__':
    sys.exit(main())
