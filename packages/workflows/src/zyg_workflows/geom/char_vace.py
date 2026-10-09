# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""char_vace.py — character geometry into the live VACE control channel (2026-08-05).

Called from wan_vace_service.generate_vace_static_clip behind ZYG_CHAR_GEOM_CTRL.

THE DEFECT THIS CLOSES, at its source. The service neutralises the control frames under
the character mask with flat grey 127 — correct inpaint semantics, but it hands VACE a
CONSTANT where the character lives, and the measured consequences are the reason this
whole geometry programme exists: prop fidelity ~0 by frame 80, identity decay by frame
200, the model re-inventing whatever the constant hides in every context window.
prop_control.py fixed it for rigid PROPS by painting rendered geometry back in; this does
the character with the character's own detected geometry:

    detect on the STILL (the character is visible there; the control is already grey
    where they stand) -> 33-joint skeleton + 478-point face mesh
    draw INTO the control frame, clipped to the character mask:
      * the skeleton in OpenPose colour convention — a control modality the Wan family
        actually understands (Wan2.2-Animate is driven by exactly such skeletons)
      * the face tesselation as thin light strokes — the head's geometry statement

    The grey stays as the base: this is a GUIDE for the model's free region, not a paste.
    VACE releases it at vace_end_percent like every other control input.

FAIL-SAFE CONTRACT, same as prop_plates: any failure returns None and the caller keeps
the neutral-grey control untouched. A missing detector, an undetectable character, an
unreadable mask — all downgrade to exactly yesterday's behaviour, logged.

LIMITATION, stated: one static geometry statement for the whole clip. For a clip whose
character moves substantially, a static skeleton mid-motion is wrong guidance late in the
clip — which is why strength/end-percent stay owned by the caller, and why the per-frame
animated path (geom.anny_animate) is the successor once pose tracks exist per shot.

2026-09-02 (S01) — CharGeometryPainter. The service now paints EVERY control frame, not
only the single control image: in per-frame control mode there are 41-341 frames and
composite_char_geometry() re-ran MediaPipe on the same still for each one. The painter
detects once in __init__ and paints many; composite_char_geometry() is now a one-shot
wrapper over it, so the single-image path is unchanged in behaviour and in log lines.
"""

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

_POSE_COLOURS = [
    (0, 0, 255),
    (0, 85, 255),
    (0, 170, 255),
    (0, 255, 255),
    (0, 255, 170),
    (0, 255, 85),
    (0, 255, 0),
    (85, 255, 0),
    (170, 255, 0),
    (255, 255, 0),
    (255, 170, 0),
    (255, 85, 0),
    (255, 0, 0),
    (255, 0, 85),
    (255, 0, 170),
    (255, 0, 255),
    (170, 0, 255),
    (85, 0, 255),
]
_BONES = [
    ('left_shoulder', 'right_shoulder'),
    ('left_shoulder', 'left_elbow'),
    ('left_elbow', 'left_wrist'),
    ('right_shoulder', 'right_elbow'),
    ('right_elbow', 'right_wrist'),
    ('left_shoulder', 'left_hip'),
    ('right_shoulder', 'right_hip'),
    ('left_hip', 'right_hip'),
    ('left_hip', 'left_knee'),
    ('left_knee', 'left_ankle'),
    ('right_hip', 'right_knee'),
    ('right_knee', 'right_ankle'),
    ('nose', 'left_eye'),
    ('nose', 'right_eye'),
    ('left_eye', 'left_ear'),
    ('right_eye', 'right_ear'),
    ('left_ankle', 'left_foot_index'),
    ('right_ankle', 'right_foot_index'),
]


class CharGeometryPainter:
    """Detect the character ONCE on the still, then paint into MANY control frames.

    The detection is the expensive half (MediaPipe cascade over an 832x1216 still) and it
    is a property of the STILL, not of the control frame — so in per-frame control mode it
    must not be repeated per frame. `ok` is False when nothing is drawable; the caller then
    keeps whatever control it already had, exactly as the one-shot function did.
    """

    def __init__(self, still_path, log_fn=None):
        self.log = log_fn or (lambda m: None)
        self.still_path = still_path
        self.det = None
        self.ok = False
        self.reason = ''
        try:
            from . import keypoints as K

            det = K.detect(still_path)
            if not det.body.ok and not det.face.ok:
                self.reason = 'no character detected in the still'
                return
            self.det = det
            self.ok = True
        except Exception as e:  # noqa: BLE001
            self.reason = '%s' % (e,)

    def paint(self, control_src, mask_png, out_path):
        """Paint the cached geometry into one control frame. Path on success, else None."""
        log = self.log
        if not self.ok:
            log('[char-geom] %s — keeping neutral control' % self.reason)
            return None
        try:
            from . import keypoints as K

            det = self.det
            ctrl = cv2.imread(control_src)
            mask = cv2.imread(mask_png, cv2.IMREAD_GRAYSCALE)
            if ctrl is None or mask is None:
                log('[char-geom] control/mask unreadable — keeping neutral control')
                return None
            H, W = ctrl.shape[:2]
            if mask.shape[:2] != (H, W):
                mask = cv2.resize(mask, (W, H), interpolation=cv2.INTER_LINEAR)
            m = mask.astype(np.float32)[:, :, None] / 255.0
            return _draw(det, K, ctrl, m, mask, W, H, out_path, log)
        except Exception as e:  # noqa: BLE001
            log('[char-geom] FAILED (%s) — keeping neutral control' % e)
            return None


def composite_char_geometry(still_path, control_src, mask_png, out_path, log_fn=None):
    """Paint the still's detected character geometry into the control frame, under mask.

    Returns out_path on success, None on ANY failure (caller keeps the old control).
    One-shot wrapper over CharGeometryPainter — same detection, same drawing, same logs.
    """
    log = log_fn or (lambda m: None)
    try:
        p = CharGeometryPainter(still_path, log_fn=log_fn)
        return p.paint(control_src, mask_png, out_path)
    except Exception as e:  # noqa: BLE001
        log('[char-geom] FAILED (%s) — keeping neutral control' % e)
        return None


def _draw(det, K, ctrl, m, mask, W, H, out_path, log):
    """The drawing half, unchanged from the 2026-08-05 one-shot version."""
    try:
        # detection ran at the still's native size; scale into the control's frame
        sx = W / float(det.w)
        sy = H / float(det.h)

        layer = ctrl.copy()
        painted = 0
        if det.body.ok:
            b = det.body.pts
            th = max(3, H // 160)
            for i, (a, c) in enumerate(_BONES):
                pa, pc = b[K.P[a]], b[K.P[c]]
                if pa[2] < 0.4 or pc[2] < 0.4:
                    continue
                if not (0 <= pa[0] < det.w and 0 <= pa[1] < det.h):
                    continue
                if not (0 <= pc[0] < det.w and 0 <= pc[1] < det.h):
                    continue
                cv2.line(
                    layer,
                    (int(pa[0] * sx), int(pa[1] * sy)),
                    (int(pc[0] * sx), int(pc[1] * sy)),
                    _POSE_COLOURS[i % len(_POSE_COLOURS)],
                    th,
                    cv2.LINE_AA,
                )
                painted += 1
        if det.face.ok:
            from . import regions as R

            f = det.face.pts
            for a, c in R._sets()['tesselation']:
                cv2.line(
                    layer,
                    (int(f[a, 0] * sx), int(f[a, 1] * sy)),
                    (int(f[c, 0] * sx), int(f[c, 1] * sy)),
                    (190, 200, 190),
                    1,
                    cv2.LINE_AA,
                )

        if painted == 0 and not det.face.ok:
            log('[char-geom] nothing drawable — keeping neutral control')
            return None

        # geometry only where generation is free; the kept region stays the still's own
        out = (layer.astype(np.float32) * m + ctrl.astype(np.float32) * (1.0 - m)).astype(np.uint8)
        cv2.imwrite(out_path, out)

        changed = int((np.abs(out.astype(np.int16) - ctrl.astype(np.int16)).max(axis=2) > 4).sum())
        in_mask = int((mask > 127).sum()) or 1
        log(
            '[char-geom] geometry painted under mask: %d px (%.1f%% of masked region), '
            '%d bones, face=%s' % (changed, 100.0 * changed / in_mask, painted, det.face.ok)
        )
        return out_path
    except Exception as e:  # noqa: BLE001
        log('[char-geom] FAILED (%s) — keeping neutral control' % e)
        return None
