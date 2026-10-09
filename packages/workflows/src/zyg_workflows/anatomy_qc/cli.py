# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""anatomy_qc fail-closed HandFixer gate and the module self-test CLI."""

from __future__ import annotations

import os
import sys


from .constants import (
    _envf,
    _envi,
)
from .runtime import (
    _read_bgr,
    available,
)
from .hands import (
    _hand_box,
    _hand_candidates,
    qc_hands_frame,
)
from .faces import (
    qc_face_frame,
)
from .clips import (
    qc_face_clip,
    qc_hands_clip,
)


# ---------------------------------------------------------------------------
# fail-closed detector for the HandFixer (the ONE raising entry point)
# ---------------------------------------------------------------------------
def detect_hand_boxes_strict(image_path: str, conf: float | None = None) -> list:
    """MediaPipe replacement for hand_qc_service.detect_hand_boxes.

    Returns [{'box': (x1,y1,x2,y2), 'conf': float, 'handedness': str}, ...] in
    PIXELS, the exact shape the r4 HandFixer expects.

    RAISES on any failure, deliberately breaking this module's fail-safe rule:
    this is the fail-closed gate. The pre-r4 detector returned a (True, -1)
    sentinel on exceptions and 29/29 renders of run 6278904c ran a blind
    whole-frame inpaint logged as a success. Detection unavailable must mean
    "skip the repair", never "repair blind".

    'conf' is a palm-detector confidence, not a YOLO objectness: the default
    (ZYG_HANDS_MP_CONF, 0.20) is deliberately permissive because the fixer's
    own downstream guards (VLM accept, tone guard, monotonic frame guard,
    box-count conservation) reject bad crops, whereas a missed hand is never
    repaired at all.
    """
    if conf is None:
        conf = _envf('ZYG_HANDS_MP_CONF', 0.12)
    bgr = _read_bgr(image_path)
    h, w = bgr.shape[:2]
    # Tiled sweep with a generous target: measured against the ADetailer
    # hand_yolov8s boxes on scene20_v7, a single whole-frame MediaPipe pass
    # recovers only ~55% of them, and a hand the fixer never sees is a hand it
    # never repairs. Tiling + a low palm threshold closes most of that gap;
    # over-detection is the safe direction here because every box still has to
    # survive the fixer's VLM accept, tone guard, monotonic frame guard and
    # box-count conservation before a pixel changes.
    want = _envi('ZYG_HANDS_MP_WANT', 4)
    cands = _hand_candidates(bgr, float(conf), want)
    out = []
    for c in cands:
        out.append(
            {
                'box': _hand_box(c['pts'], w, h),
                'conf': float(c['score'] if c['score'] is not None else 1.0),
                'handedness': str(c['label'] or ''),
            }
        )
    return out


# ---------------------------------------------------------------------------
# self-test CLI
# ---------------------------------------------------------------------------
def _expand(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            out.extend(
                sorted(
                    os.path.join(p, f) for f in os.listdir(p) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))
                )
            )
        else:
            out.append(p)
    return out


def _main(argv):
    import json

    args = list(argv[1:])
    if not args:
        print(__doc__)
        return 2
    mode = args[0]
    people = 0
    every = 8
    rest, skip = [], False
    for i, a in enumerate(args[1:], start=1):
        if skip:
            skip = False
            continue
        if a in ('--people', '--every'):
            val = args[i + 1] if i + 1 < len(args) else '0'
            if a == '--people':
                people = int(val)
            else:
                every = int(val)
            skip = True
            continue
        if a.startswith('--'):
            continue
        rest.append(a)
    ok, why = available()
    print(f'# mediapipe available={ok} {why}')
    if mode == '--hands':
        for p in _expand(rest):
            r = qc_hands_frame(p, (2 * people) if people else None)
            print(
                f'{os.path.basename(p):28s} ok={str(r["ok"]):5s} '
                f'hands={r["detected"]}(strong={r["strong"]}) '
                f'tags={sorted({i["tag"] for i in r["issues"]})}'
            )
    elif mode == '--faces':
        for p in _expand(rest):
            r = qc_face_frame(p, people or None)
            print(
                f'{os.path.basename(p):28s} ok={str(r["ok"]):5s} '
                f'faces={r["detected"]}(strong={r["strong"]}) '
                f'tags={sorted({i["tag"] for i in r["issues"]})}'
            )
    elif mode == '--clip':
        for p in rest:
            print(json.dumps(qc_hands_clip(p, people, every, log_fn=print), indent=1, default=str)[:1200])
            print(json.dumps(qc_face_clip(p, people, every, log_fn=print), indent=1, default=str)[:1200])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(_main(sys.argv))
