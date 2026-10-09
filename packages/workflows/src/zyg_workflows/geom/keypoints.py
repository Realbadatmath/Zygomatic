# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""keypoints.py — crop-first detector cascade for character images (2026-08-04).

Every downstream consumer of the character mesh grid — region masks, gates, control maps —
starts from what this module returns: the 478-point face mesh, the 33-point body skeleton,
the person segmentation, and (optionally) 21-point hands, in ORIGINAL-IMAGE pixel
coordinates whatever crop they were actually detected in.

WHY CROP-FIRST IS NOT OPTIONAL.
Measured on Abel's 48 Arcane-styled LoRA cells (2026-08-04): whole-image face detection
locks on 38/48. The ten misses split two ways, and the split matters:
  * full-body wides — the face is ~40px tall there, below what the detector resolves at
    frame scale. Detecting the PERSON first, cropping the head, and re-running recovers
    these. This is THE CROP RULE from the VLM work (5/5 on crops, 0/2 on full frames)
    applied one layer down.
  * rear views — there is no face. The correct output is "no face", and the cascade
    reports it as such rather than hallucinating one. A rear-view cell with a confident
    face mesh would be a detector LIE, and gates downstream treat it as one.

LICENCES. All four model files are MediaPipe, Apache-2.0 INCLUDING the weights (official
model cards, verified 2026-08-04; see data/assets/detectors/PROVENANCE.json). No SMPL, no
DensePose, no dlib, no insightface — every one of those is non-commercial and banned here.

COORDINATES. Everything returned is in ORIGINAL image pixels, float32, regardless of any
internal cropping. Face landmarks also carry z (MediaPipe's relative depth, roughly
iris-scaled); body landmarks carry visibility. Callers should trust `face.ok`/`body.ok`
and never the mere presence of arrays.
"""

import os

import numpy as np

from zyg_workflows import paths as _paths

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# The MediaPipe task files are weights, not source: they live under the data root
# (ZYG_DATA_ROOT/assets/detectors), never inside the package.
_DET_DIR = str(_paths.ZYG_DATA_ROOT / 'assets' / 'detectors')

# lazily-created singletons — mediapipe graph startup is ~0.5s each, and a batch run
# would otherwise pay it per image
_FACE = _POSE = _SEG = _HANDS = None


def _mp():
    import mediapipe as mp
    from mediapipe.tasks import python as mpp
    from mediapipe.tasks.python import vision

    return mp, mpp, vision


def _face():
    global _FACE
    if _FACE is None:
        mp, mpp, vision = _mp()
        _FACE = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=mpp.BaseOptions(model_asset_path=os.path.join(_DET_DIR, 'face_landmarker.task')),
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=True,
                num_faces=1,
                min_face_detection_confidence=0.3,
            )
        )
    return _FACE


def _pose():
    global _POSE
    if _POSE is None:
        mp, mpp, vision = _mp()
        _POSE = vision.PoseLandmarker.create_from_options(
            vision.PoseLandmarkerOptions(
                base_options=mpp.BaseOptions(model_asset_path=os.path.join(_DET_DIR, 'pose_landmarker_full.task')),
                output_segmentation_masks=True,
                min_pose_detection_confidence=0.3,
            )
        )
    return _POSE


def _hands():
    global _HANDS
    if _HANDS is None:
        mp, mpp, vision = _mp()
        _HANDS = vision.HandLandmarker.create_from_options(
            vision.HandLandmarkerOptions(
                base_options=mpp.BaseOptions(model_asset_path=os.path.join(_DET_DIR, 'hand_landmarker.task')),
                num_hands=2,
                min_hand_detection_confidence=0.3,
            )
        )
    return _HANDS


# BlazePose 33-landmark names — the skeleton the body regions hang off
POSE_NAMES = [
    'nose',
    'left_eye_inner',
    'left_eye',
    'left_eye_outer',
    'right_eye_inner',
    'right_eye',
    'right_eye_outer',
    'left_ear',
    'right_ear',
    'mouth_left',
    'mouth_right',
    'left_shoulder',
    'right_shoulder',
    'left_elbow',
    'right_elbow',
    'left_wrist',
    'right_wrist',
    'left_pinky',
    'right_pinky',
    'left_index',
    'right_index',
    'left_thumb',
    'right_thumb',
    'left_hip',
    'right_hip',
    'left_knee',
    'right_knee',
    'left_ankle',
    'right_ankle',
    'left_heel',
    'right_heel',
    'left_foot_index',
    'right_foot_index',
]
P = {n: i for i, n in enumerate(POSE_NAMES)}


class Part:
    """One detected part: points (N,2 or N,3) in original-image pixels, plus flags."""

    def __init__(self, ok, pts=None, extra=None, via=''):
        self.ok = bool(ok)
        self.pts = pts  # float32 array or None
        self.extra = extra or {}
        self.via = via  # 'full' | 'crop' | ''

    def __repr__(self):
        n = 0 if self.pts is None else len(self.pts)
        return '<Part ok=%s n=%d via=%s>' % (self.ok, n, self.via)


class Detection:
    def __init__(self, path, w, h):
        self.path, self.w, self.h = path, w, h
        self.face = Part(False)
        self.body = Part(False)
        self.hands = []
        self.person_mask = None  # (H,W) float32 0..1, original size
        self.blendshapes = {}

    def summary(self):
        return {
            'face': self.face.ok,
            'face_via': self.face.via,
            'body': self.body.ok,
            'hands': len(self.hands),
            'person_mask': self.person_mask is not None,
        }


def _mp_image(bgr):
    import mediapipe as mp

    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))


def _face_pts(res, w, h, off=(0, 0)):
    lm = res.face_landmarks[0]
    pts = np.array([[l.x * w + off[0], l.y * h + off[1], l.z * w] for l in lm], np.float32)
    bs = {}
    if res.face_blendshapes:
        bs = {b.category_name: float(b.score) for b in res.face_blendshapes[0]}
    # head orientation from the facial transformation matrix — THE profile signal the
    # body fitter needs (2D keypoints cannot distinguish a profile from a failed frontal;
    # the head can). Yaw extracted about the vertical axis; crop-first detection does not
    # disturb it (a crop is scale+translate, rotation-free).
    yaw = None
    mats = getattr(res, 'facial_transformation_matrixes', None)
    if mats:
        M = np.asarray(mats[0], np.float32)
        R = M[:3, :3]
        yaw = float(np.arctan2(-R[2, 0], np.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2)))
    return pts, bs, yaw


def _head_crop(body_pts, w, h):
    """Head box from the skeleton: the face landmarks 0..10 plus shoulder width for scale.

    Padding is generous on purpose — the face detector needs context (hair, jaw, neck) and
    a too-tight crop re-creates the failure it exists to fix.
    """
    head = body_pts[:11, :2]
    ls, rs = body_pts[P['left_shoulder'], :2], body_pts[P['right_shoulder'], :2]
    scale = max(float(np.linalg.norm(ls - rs)), 24.0)
    cx, cy = float(head[:, 0].mean()), float(head[:, 1].mean())
    half = scale * 1.35
    x0, y0 = int(max(0, cx - half)), int(max(0, cy - half * 1.15))
    x1, y1 = int(min(w, cx + half)), int(min(h, cy + half * 1.05))
    if x1 - x0 < 48 or y1 - y0 < 48:
        return None
    return x0, y0, x1, y1


def detect(path_or_bgr, want_hands=False):
    """Run the cascade on one image. Returns a Detection.

    Order matters: body first (it nearly always fires — 44/48 measured — and its
    segmentation mask and head box are what make the face recoverable on wides), then
    face at full frame, then face again on the head crop only if the full frame missed.
    """
    if cv2 is None:
        raise RuntimeError('cv2 required')
    bgr = cv2.imread(path_or_bgr) if isinstance(path_or_bgr, str) else path_or_bgr
    if bgr is None:
        raise FileNotFoundError(str(path_or_bgr))
    h, w = bgr.shape[:2]
    det = Detection(path_or_bgr if isinstance(path_or_bgr, str) else '<array>', w, h)
    img = _mp_image(bgr)

    pr = _pose().detect(img)
    if pr.pose_landmarks:
        lm = pr.pose_landmarks[0]
        det.body = Part(True, np.array([[l.x * w, l.y * h, l.visibility] for l in lm], np.float32), via='full')
        # BlazePose's per-landmark z (roughly image-width units, hip-relative) was being
        # discarded — and it is exactly the signal that tells a fitter which way the
        # person FACES. A profile view is unrecoverable from 2D keypoints alone
        # (measured: cell_28 fitted frontal at 98px error); the shoulder z-difference
        # hands the yaw over directly. Kept separate from pts so no consumer of the
        # [x, y, visibility] layout has to change.
        det.body.extra['z'] = np.array([l.z * w for l in lm], np.float32)
        if pr.segmentation_masks:
            # numpy_view may come back (H,W,1); everyone downstream expects (H,W)
            m = np.squeeze(pr.segmentation_masks[0].numpy_view()).astype(np.float32)
            if m.shape[:2] != (h, w):
                m = cv2.resize(m, (w, h))
            det.person_mask = m

    fr = _face().detect(img)
    if fr.face_landmarks:
        pts, bs, yaw = _face_pts(fr, w, h)
        det.face = Part(True, pts, via='full')
        det.face.extra['yaw'] = yaw
        det.blendshapes = bs
    elif det.body.ok:
        box = _head_crop(det.body.pts, w, h)
        if box:
            x0, y0, x1, y1 = box
            crop = bgr[y0:y1, x0:x1]
            # upscale small heads so the detector sees a face-sized face
            s = 1.0
            if min(crop.shape[:2]) < 256:
                s = 256.0 / min(crop.shape[:2])
                crop = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
            fr2 = _face().detect(_mp_image(crop))
            if fr2.face_landmarks:
                pts, bs, yaw = _face_pts(fr2, crop.shape[1], crop.shape[0])
                pts[:, 0] = pts[:, 0] / s + x0
                pts[:, 1] = pts[:, 1] / s + y0
                pts[:, 2] /= s
                det.face = Part(True, pts, via='crop')
                det.face.extra['yaw'] = yaw
                det.blendshapes = bs

    if want_hands:
        hr = _hands().detect(img)
        for i, lm in enumerate(hr.hand_landmarks or []):
            side = ''
            try:
                side = hr.handedness[i][0].category_name.lower()
            except (AttributeError, IndexError) as _exc:
                _zyg_log.debug('handedness unavailable for this hand: %s', _exc)
            det.hands.append(
                Part(True, np.array([[l.x * w, l.y * h] for l in lm], np.float32), {'side': side}, via='full')
            )
    return det
