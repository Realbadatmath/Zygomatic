# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""vfx_landmarks.py — the subject layer for the VFX Analyzer.

vfx_metrics measures the PICTURE. This module measures the PEOPLE in it: where
the bodies, faces and hands are, and the per-frame scalars that action detectors
key off (joint angles, eye aperture, mouth aperture, grasp aperture, head pose).

Runs the three MediaPipe Tasks bundles already vendored in this repo
(data/assets/detectors/*.task, Apache-2.0, see PROVENANCE.json) in VIDEO running
mode so the tracker carries identity between frames instead of re-detecting cold.

THE TRI-STATE CONTRACT (inherited from anatomy_qc.py, and load-bearing here)
---------------------------------------------------------------------------
MediaPipe's detectors are trained on PHOTOGRAPHS. On stylized 2D animation they
under-detect badly — anatomy_qc measured ZERO faces whole-frame on a real render
at confidence 0.01 while the same face resolved instantly from a head-sized crop.
So "no landmarks" NEVER means "no person". Every result carries a state:

    'found'        landmarks were detected at strict confidence
    'weak'         detected only by the permissive pass — advisory, not evidence
    'none'         the detector ran cleanly and found nothing
    'unmeasurable' the detector could not run (bundle missing, error)

A detector that consumes this module must map 'none' on stylized input to
UNMEASURABLE, not to "the action did not happen". An analyzer that reports
"no kick" because MediaPipe cannot see an anime leg is lying with confidence.

Two passes run per frame: permissive (recall) and strict (evidence). Both are
reported so a run can be calibrated against frames a human has eyeballed.
"""

import math
import os
import threading

import cv2
import numpy as np
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_HERE = os.path.dirname(os.path.abspath(__file__))
_DET_DIR = os.environ.get('ZYG_VFX_DETECTOR_DIR', os.path.join(_HERE, 'data', 'assets', 'detectors'))
_FALLBACK_DIR = os.path.join(_HERE, 'data', 'models', 'mediapipe')

TASKS = {
    'pose': ('pose_landmarker_full.task', 'pose_landmarker_lite.task'),
    'face': ('face_landmarker.task',),
    'hand': ('hand_landmarker.task',),
}

CONF_WEAK = float(os.environ.get('ZYG_VFX_CONF_WEAK', 0.20))
CONF_STRICT = float(os.environ.get('ZYG_VFX_CONF_STRICT', 0.50))
MAX_POSES = int(os.environ.get('ZYG_VFX_MAX_POSES', 4))
MAX_FACES = int(os.environ.get('ZYG_VFX_MAX_FACES', 4))
MAX_HANDS = int(os.environ.get('ZYG_VFX_MAX_HANDS', 8))
# Tiled escalation: when a whole-frame pass finds nothing, retry on overlapping
# tiles. MediaPipe's detectors run on a small square input, so a subject that
# occupies a modest fraction of a wide frame is below their operating range —
# anatomy_qc measured a face that was invisible whole-frame resolving instantly
# from a head-sized crop. Escalation is the difference between "no person here"
# and "no person at THIS zoom", and only the second one is true.
TILE_GRIDS = tuple(int(x) for x in os.environ.get('ZYG_VFX_TILE_GRIDS', '2,3').split(',') if x.strip())
TILE_MIN_PX = int(os.environ.get('ZYG_VFX_TILE_MIN_PX', 420))
TILE_OVERLAP = float(os.environ.get('ZYG_VFX_TILE_OVERLAP', 0.25))

_LOCK = threading.Lock()
_EPS = 1e-8

# BlazePose 33-point indices. "left"/"right" are the SUBJECT's own.
P = {
    'nose': 0,
    'eye_l': 2,
    'eye_r': 5,
    'ear_l': 7,
    'ear_r': 8,
    'mouth_l': 9,
    'mouth_r': 10,
    'shoulder_l': 11,
    'shoulder_r': 12,
    'elbow_l': 13,
    'elbow_r': 14,
    'wrist_l': 15,
    'wrist_r': 16,
    'pinky_l': 17,
    'pinky_r': 18,
    'index_l': 19,
    'index_r': 20,
    'thumb_l': 21,
    'thumb_r': 22,
    'hip_l': 23,
    'hip_r': 24,
    'knee_l': 25,
    'knee_r': 26,
    'ankle_l': 27,
    'ankle_r': 28,
    'heel_l': 29,
    'heel_r': 30,
    'foot_l': 31,
    'foot_r': 32,
}

# The standard 6-point eye-aspect-ratio sets on the 468-point face mesh.
EAR_L = (33, 160, 158, 133, 153, 144)
EAR_R = (362, 385, 387, 263, 373, 380)
MOUTH = {'upper_inner': 13, 'lower_inner': 14, 'corner_l': 78, 'corner_r': 308, 'upper_outer': 0, 'lower_outer': 17}


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return v if math.isfinite(v) else 0.0


def _task_path(kind):
    for name in TASKS[kind]:
        for d in (_DET_DIR, _FALLBACK_DIR):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
    return None


def available():
    """Which landmark tiers this install can actually run. The report prints
    this so a missing bundle shows up as a stated blind spot, not a silence."""
    out = {}
    for kind in TASKS:
        p = _task_path(kind)
        out[kind] = {
            'ok': bool(p),
            'path': p or '',
            'missing': '' if p else f'no {"/".join(TASKS[kind])} under {_DET_DIR}',
        }
    return out


# ── geometry helpers ─────────────────────────────────────────────────────────


def _angle(a, b, c):
    """Interior angle at b, in degrees (0-180). Points are (x, y) normalised."""
    v1 = (a[0] - b[0], a[1] - b[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 < _EPS or n2 < _EPS:
        return 0.0
    cosv = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.degrees(math.acos(cosv))


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _ear(pts, idx):
    """Eye aspect ratio: (|p2-p6| + |p3-p5|) / (2|p1-p4|). ~0.30 open, <0.18
    closed on photoreal faces — but CALIBRATE per style, do not trust the
    textbook threshold on a drawn eye."""
    try:
        p1, p2, p3, p4, p5, p6 = (pts[i] for i in idx)
    except (IndexError, KeyError):
        return 0.0
    denom = 2.0 * _dist(p1, p4)
    if denom < _EPS:
        return 0.0
    return (_dist(p2, p6) + _dist(p3, p5)) / denom


def _decompose_rt(mat):
    """Yaw/pitch/roll in degrees from MediaPipe's 4x4 facial transform."""
    try:
        m = np.asarray(mat, np.float64).reshape(4, 4)[:3, :3]
        sy = math.sqrt(m[0, 0] ** 2 + m[1, 0] ** 2)
        if sy > 1e-6:
            pitch = math.atan2(m[2, 1], m[2, 2])
            yaw = math.atan2(-m[2, 0], sy)
            roll = math.atan2(m[1, 0], m[0, 0])
        else:
            pitch = math.atan2(-m[1, 2], m[1, 1])
            yaw = math.atan2(-m[2, 0], sy)
            roll = 0.0
        return _f(math.degrees(yaw)), _f(math.degrees(pitch)), _f(math.degrees(roll))
    except (ValueError, TypeError, IndexError):
        return 0.0, 0.0, 0.0


# ── the tracker ──────────────────────────────────────────────────────────────


class LandmarkTracker:
    """Stateful per-clip tracker. Build one per run, call step() on each frame in
    order with a monotonically increasing timestamp, then close().

    Landmarkers in VIDEO mode REQUIRE strictly increasing timestamps and are not
    thread-safe, so one tracker belongs to exactly one run thread."""

    def __init__(
        self, conf_weak=CONF_WEAK, conf_strict=CONF_STRICT, want=('pose', 'face', 'hand'), log_fn=None, tiles=True
    ):
        self.conf_weak = float(conf_weak)
        self.conf_strict = float(conf_strict)
        self.want = tuple(want)
        self.log = log_fn or (lambda _m: None)
        self.tiles = bool(tiles)
        self._lm = {}
        self._err = {}
        self._ts = -1
        self._tile_hits = {'pose': 0, 'face': 0, 'hand': 0}
        self._build()

    def tile_hits(self):
        """How many frames were only rescued by the tiled pass — worth logging,
        because a run that leans on escalation is telling you the subject is
        small in frame and every whole-frame reading is near the detector's floor."""
        return dict(self._tile_hits)

    def _build(self):
        os.environ.setdefault('MEDIAPIPE_DISABLE_GPU', '1')
        try:
            from mediapipe.tasks import python as mpp
            from mediapipe.tasks.python import vision as mpv
        except Exception as e:  # noqa: BLE001 — tier is optional
            for k in self.want:
                self._err[k] = f'{type(e).__name__}: {e}'
            self.log(f'[vfx-lm] mediapipe unavailable — landmark tier off ({e})')
            return
        for kind in self.want:
            path = _task_path(kind)
            if not path:
                self._err[kind] = f'bundle missing under {_DET_DIR}'
                self.log(f'[vfx-lm] {kind}: {self._err[kind]}')
                continue
            for tier, conf in (('weak', self.conf_weak), ('strict', self.conf_strict)):
                try:
                    base = mpp.BaseOptions(model_asset_path=path, delegate=mpp.BaseOptions.Delegate.CPU)
                    kw = {'base_options': base, 'running_mode': mpv.RunningMode.VIDEO}
                    if kind == 'pose':
                        kw.update(
                            num_poses=MAX_POSES,
                            min_pose_detection_confidence=conf,
                            min_pose_presence_confidence=conf,
                            min_tracking_confidence=conf,
                            output_segmentation_masks=False,
                        )
                        obj = mpv.PoseLandmarker.create_from_options(mpv.PoseLandmarkerOptions(**kw))
                    elif kind == 'face':
                        kw.update(
                            num_faces=MAX_FACES,
                            min_face_detection_confidence=conf,
                            min_face_presence_confidence=conf,
                            min_tracking_confidence=conf,
                            output_face_blendshapes=True,
                            output_facial_transformation_matrixes=True,
                        )
                        obj = mpv.FaceLandmarker.create_from_options(mpv.FaceLandmarkerOptions(**kw))
                    else:
                        kw.update(
                            num_hands=MAX_HANDS,
                            min_hand_detection_confidence=conf,
                            min_hand_presence_confidence=conf,
                            min_tracking_confidence=conf,
                        )
                        obj = mpv.HandLandmarker.create_from_options(mpv.HandLandmarkerOptions(**kw))
                    self._lm[(kind, tier)] = obj
                except Exception as e:  # noqa: BLE001
                    self._err[kind] = f'{type(e).__name__}: {e}'
                    self.log(f'[vfx-lm] {kind}/{tier} failed to build: {e}')
            if self.tiles:
                try:
                    base = mpp.BaseOptions(model_asset_path=path, delegate=mpp.BaseOptions.Delegate.CPU)
                    kw = {'base_options': base, 'running_mode': mpv.RunningMode.IMAGE}
                    if kind == 'pose':
                        kw.update(
                            num_poses=MAX_POSES,
                            min_pose_detection_confidence=self.conf_weak,
                            min_pose_presence_confidence=self.conf_weak,
                        )
                        self._lm[(kind, 'tile')] = mpv.PoseLandmarker.create_from_options(
                            mpv.PoseLandmarkerOptions(**kw)
                        )
                    elif kind == 'face':
                        kw.update(
                            num_faces=MAX_FACES,
                            min_face_detection_confidence=self.conf_weak,
                            min_face_presence_confidence=self.conf_weak,
                            output_face_blendshapes=True,
                            output_facial_transformation_matrixes=True,
                        )
                        self._lm[(kind, 'tile')] = mpv.FaceLandmarker.create_from_options(
                            mpv.FaceLandmarkerOptions(**kw)
                        )
                    else:
                        kw.update(
                            num_hands=MAX_HANDS,
                            min_hand_detection_confidence=self.conf_weak,
                            min_hand_presence_confidence=self.conf_weak,
                        )
                        self._lm[(kind, 'tile')] = mpv.HandLandmarker.create_from_options(
                            mpv.HandLandmarkerOptions(**kw)
                        )
                except Exception as e:  # noqa: BLE001 — escalation is optional
                    self.log(f'[vfx-lm] {kind}/tile unavailable: {e}')

    def close(self):
        for obj in self._lm.values():
            try:
                obj.close()
            except Exception as _exc:  # noqa: BLE001
                _zyg_log.debug('landmarker close skipped: %s', _exc)
        self._lm.clear()

    # -- per-frame ----------------------------------------------------------

    def step(self, bgr, ts_ms):
        """One frame in, one dict out. ts_ms MUST strictly increase."""
        import mediapipe as mp

        if ts_ms <= self._ts:
            ts_ms = self._ts + 1
        self._ts = int(ts_ms)
        h, w = bgr.shape[:2]
        self._last_bgr = bgr
        img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        out = {'ts_ms': self._ts}
        for kind, fn in (('pose', self._pose), ('face', self._face), ('hand', self._hand)):
            if kind not in self.want:
                continue
            if kind in self._err and not any(k[0] == kind for k in self._lm):
                out[kind] = {'state': 'unmeasurable', 'reason': self._err[kind], 'items': []}
                continue
            try:
                out[kind] = fn(img, w, h)
            except Exception as e:  # noqa: BLE001 — one bad frame
                out[kind] = {'state': 'unmeasurable', 'reason': f'{type(e).__name__}: {e}', 'items': []}
        return out

    @staticmethod
    def _tile_boxes(W, H):
        """Overlapping tiles. The overlap matters: a subject sitting exactly on a
        tile seam would be cut in half by every tile and found by none."""
        boxes = []
        for g in TILE_GRIDS:
            if g < 2 or min(W, H) / g < TILE_MIN_PX / 2:
                continue
            tw, th = W / g, H / g
            ox, oy = tw * TILE_OVERLAP, th * TILE_OVERLAP
            for r in range(g):
                for c in range(g):
                    x0 = max(0, int(c * tw - ox))
                    y0 = max(0, int(r * th - oy))
                    x1 = min(W, int((c + 1) * tw + ox))
                    y1 = min(H, int((r + 1) * th + oy))
                    if x1 - x0 >= 64 and y1 - y0 >= 64:
                        boxes.append((x0, y0, x1, y1))
        return boxes

    def _escalate(self, kind, bgr):
        """Whole-frame found nothing: retry on tiles and map results back.

        Returns a list of raw (pts, extra) tuples in FULL-FRAME normalised
        coordinates, so everything downstream is unaware a crop was involved."""
        obj = self._lm.get((kind, 'tile'))
        if obj is None or not self.tiles:
            return []
        import mediapipe as mp

        H, W = bgr.shape[:2]
        if max(W, H) < TILE_MIN_PX:
            return []
        out = []
        for x0, y0, x1, y1 in self._tile_boxes(W, H):
            crop = bgr[y0:y1, x0:x1]
            if crop.size == 0:
                continue
            tw, th = x1 - x0, y1 - y0
            try:
                res = obj.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)))
            except Exception as _exc:  # noqa: BLE001 — one bad tile
                _zyg_log.debug('landmark tile skipped: %s', _exc)
                continue

            # The tile geometry is bound at definition time: _map is called inside this
            # iteration only, but a late-bound x0/y0/tw/th would silently map the last tile.
            def _map(lms, _x0=x0, _y0=y0, _tw=tw, _th=th):
                return [((_x0 + _f(l.x) * _tw) / W, (_y0 + _f(l.y) * _th) / H) for l in lms]

            if kind == 'pose' and res.pose_landmarks:
                for lms in res.pose_landmarks:
                    out.append((_map(lms), [_f(getattr(l, 'visibility', 0.0)) for l in lms]))
            elif kind == 'face' and res.face_landmarks:
                for i, lms in enumerate(res.face_landmarks):
                    bs = {}
                    try:
                        for c in res.face_blendshapes[i]:
                            bs[c.category_name] = _f(c.score)
                    except (AttributeError, IndexError, TypeError) as _exc:
                        _zyg_log.debug('blendshapes unavailable for this face: %s', _exc)
                    rt = (0.0, 0.0, 0.0)
                    try:
                        rt = _decompose_rt(res.facial_transformation_matrixes[i])
                    except (AttributeError, IndexError, TypeError) as _exc:
                        _zyg_log.debug('head rotation unavailable for this face: %s', _exc)
                    out.append((_map(lms), bs, rt))
            elif kind == 'hand' and res.hand_landmarks:
                for i, lms in enumerate(res.hand_landmarks):
                    side = ''
                    try:
                        side = res.handedness[i][0].category_name
                    except (AttributeError, IndexError, TypeError) as _exc:
                        _zyg_log.debug('handedness unavailable for this hand: %s', _exc)
                    out.append((_map(lms), side))
            if out:
                break  # the coarsest grid that works is enough
        if out:
            self._tile_hits[kind] += 1
        return out

    def _run(self, kind, tier, img):
        obj = self._lm.get((kind, tier))
        if obj is None:
            return None
        return obj.detect_for_video(img, self._ts)

    @staticmethod
    def _state(n_strict, n_weak):
        if n_strict > 0:
            return 'found'
        if n_weak > 0:
            return 'weak'
        return 'none'

    # -- pose ---------------------------------------------------------------

    def _pose(self, img, w, h):
        strict = self._run('pose', 'strict', img)
        weak = self._run('pose', 'weak', img)
        ns = len(strict.pose_landmarks) if strict and strict.pose_landmarks else 0
        nw = len(weak.pose_landmarks) if weak and weak.pose_landmarks else 0
        src = strict if ns else weak
        items = []
        if src and src.pose_landmarks:
            for lms in src.pose_landmarks:
                pts = [(_f(l.x), _f(l.y)) for l in lms]
                vis = [_f(getattr(l, 'visibility', 0.0)) for l in lms]
                items.append(self._pose_derive(pts, vis, w, h))
        tiled = False
        if not items:
            for pts, vis in self._escalate('pose', self._last_bgr):
                items.append(self._pose_derive(pts, vis, w, h))
                tiled = True
        st = self._state(ns, nw)
        if tiled and st == 'none':
            st = 'weak'  # found only by escalation: advisory, never evidence
        return {
            'state': st,
            'n_strict': ns,
            'n_weak': nw or (len(items) if tiled else 0),
            'items': items,
            'tiled': tiled,
        }

    @staticmethod
    def _pose_derive(pts, vis, w, h):
        g = lambda k: pts[P[k]]  # noqa: E731
        v = lambda k: vis[P[k]]  # noqa: E731
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        sh_l, sh_r = g('shoulder_l'), g('shoulder_r')
        hip_l, hip_r = g('hip_l'), g('hip_r')
        neck = ((sh_l[0] + sh_r[0]) / 2, (sh_l[1] + sh_r[1]) / 2)
        pelvis = ((hip_l[0] + hip_r[0]) / 2, (hip_l[1] + hip_r[1]) / 2)
        torso = _dist(neck, pelvis)
        shoulder_w = _dist(sh_l, sh_r)
        # scale-free unit: every length below is expressed in TORSO lengths, so a
        # threshold tuned on a close-up still means something on a wide shot.
        unit = max(torso, 0.02)
        return {
            'bbox': {'x': _f(min(xs)), 'y': _f(min(ys)), 'w': _f(max(xs) - min(xs)), 'h': _f(max(ys) - min(ys))},
            'pts': [[_f(p[0]), _f(p[1])] for p in pts],
            'vis_mean': _f(sum(vis) / max(1, len(vis))),
            'torso_len': _f(torso),
            'shoulder_w': _f(shoulder_w),
            'unit': _f(unit),
            'neck': [_f(neck[0]), _f(neck[1])],
            'pelvis': [_f(pelvis[0]), _f(pelvis[1])],
            'com': [_f(sum(xs) / len(xs)), _f(sum(ys) / len(ys))],
            # joint angles, degrees, 180 = fully extended
            'elbow_l_deg': _f(_angle(g('shoulder_l'), g('elbow_l'), g('wrist_l'))),
            'elbow_r_deg': _f(_angle(g('shoulder_r'), g('elbow_r'), g('wrist_r'))),
            'knee_l_deg': _f(_angle(g('hip_l'), g('knee_l'), g('ankle_l'))),
            'knee_r_deg': _f(_angle(g('hip_r'), g('knee_r'), g('ankle_r'))),
            'hip_l_deg': _f(_angle(g('shoulder_l'), g('hip_l'), g('knee_l'))),
            'hip_r_deg': _f(_angle(g('shoulder_r'), g('hip_r'), g('knee_r'))),
            'shoulder_l_deg': _f(_angle(g('hip_l'), g('shoulder_l'), g('elbow_l'))),
            'shoulder_r_deg': _f(_angle(g('hip_r'), g('shoulder_r'), g('elbow_r'))),
            # torso lean: 0 = upright, +ve = leaning right in frame
            'torso_lean_deg': _f(math.degrees(math.atan2(neck[0] - pelvis[0], max(_EPS, pelvis[1] - neck[1])))),
            'shoulder_tilt_deg': _f(math.degrees(math.atan2(sh_r[1] - sh_l[1], sh_r[0] - sh_l[0] or _EPS))),
            # reach: how far each extremity sits from the body centre, in torsos
            'wrist_l_reach': _f(_dist(g('wrist_l'), neck) / unit),
            'wrist_r_reach': _f(_dist(g('wrist_r'), neck) / unit),
            'ankle_l_reach': _f(_dist(g('ankle_l'), pelvis) / unit),
            'ankle_r_reach': _f(_dist(g('ankle_r'), pelvis) / unit),
            'wrist_l': [_f(g('wrist_l')[0]), _f(g('wrist_l')[1])],
            'wrist_r': [_f(g('wrist_r')[0]), _f(g('wrist_r')[1])],
            'ankle_l': [_f(g('ankle_l')[0]), _f(g('ankle_l')[1])],
            'ankle_r': [_f(g('ankle_r')[0]), _f(g('ankle_r')[1])],
            'nose': [_f(g('nose')[0]), _f(g('nose')[1])],
            'vis_wrist_l': _f(v('wrist_l')),
            'vis_wrist_r': _f(v('wrist_r')),
            'vis_ankle_l': _f(v('ankle_l')),
            'vis_ankle_r': _f(v('ankle_r')),
            # standing/crouching proxy: pelvis-to-ankle vs torso
            'stance_ratio': _f(max(_dist(pelvis, g('ankle_l')), _dist(pelvis, g('ankle_r'))) / unit),
            'feet_spread': _f(_dist(g('ankle_l'), g('ankle_r')) / unit),
        }

    # -- face ---------------------------------------------------------------

    def _face(self, img, w, h):
        strict = self._run('face', 'strict', img)
        weak = self._run('face', 'weak', img)
        ns = len(strict.face_landmarks) if strict and strict.face_landmarks else 0
        nw = len(weak.face_landmarks) if weak and weak.face_landmarks else 0
        src = strict if ns else weak
        items = []
        if src and src.face_landmarks:
            for i, lms in enumerate(src.face_landmarks):
                pts = [(_f(l.x), _f(l.y)) for l in lms]
                bs = {}
                try:
                    for c in src.face_blendshapes[i]:
                        bs[c.category_name] = _f(c.score)
                except (AttributeError, IndexError, TypeError) as _exc:
                    _zyg_log.debug('blendshapes unavailable for this face: %s', _exc)
                yaw = pitch = roll = 0.0
                try:
                    yaw, pitch, roll = _decompose_rt(src.facial_transformation_matrixes[i])
                except (AttributeError, IndexError, TypeError) as _exc:
                    _zyg_log.debug('head rotation unavailable for this face: %s', _exc)
                items.append(self._face_derive(pts, bs, yaw, pitch, roll))
        tiled = False
        if not items:
            for pts, bs, rt in self._escalate('face', self._last_bgr):
                items.append(self._face_derive(pts, bs, rt[0], rt[1], rt[2]))
                tiled = True
        st = self._state(ns, nw)
        if tiled and st == 'none':
            st = 'weak'
        return {
            'state': st,
            'n_strict': ns,
            'n_weak': nw or (len(items) if tiled else 0),
            'items': items,
            'tiled': tiled,
        }

    @staticmethod
    def _face_derive(pts, bs, yaw, pitch, roll):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        face_w = max(_EPS, max(xs) - min(xs))
        ear_l, ear_r = _ear(pts, EAR_L), _ear(pts, EAR_R)
        try:
            mouth_open = _dist(pts[MOUTH['upper_inner']], pts[MOUTH['lower_inner']])
            mouth_wide = _dist(pts[MOUTH['corner_l']], pts[MOUTH['corner_r']])
        except IndexError:
            mouth_open = mouth_wide = 0.0
        mar = mouth_open / max(_EPS, mouth_wide)
        # Blendshapes are the calibrated read where the face is photoreal enough
        # to produce them; the geometric EAR/MAR are the fallback that still
        # moves on a drawn face. Report BOTH — they disagree, and the
        # disagreement is the calibration signal.
        return {
            'bbox': {'x': _f(min(xs)), 'y': _f(min(ys)), 'w': _f(face_w), 'h': _f(max(ys) - min(ys))},
            'centre': [_f(sum(xs) / len(xs)), _f(sum(ys) / len(ys))],
            'face_w': _f(face_w),
            'ear_left': _f(ear_l),
            'ear_right': _f(ear_r),
            'ear_mean': _f((ear_l + ear_r) / 2.0),
            'ear_asym': _f(abs(ear_l - ear_r)),
            'mar': _f(mar),
            'mouth_open_norm': _f(mouth_open / max(_EPS, face_w)),
            'mouth_width_norm': _f(mouth_wide / max(_EPS, face_w)),
            'head_yaw_deg': _f(yaw),
            'head_pitch_deg': _f(pitch),
            'head_roll_deg': _f(roll),
            'bs_blink_l': _f(bs.get('eyeBlinkLeft', 0.0)),
            'bs_blink_r': _f(bs.get('eyeBlinkRight', 0.0)),
            'bs_squint_l': _f(bs.get('eyeSquintLeft', 0.0)),
            'bs_squint_r': _f(bs.get('eyeSquintRight', 0.0)),
            'bs_wide_l': _f(bs.get('eyeWideLeft', 0.0)),
            'bs_wide_r': _f(bs.get('eyeWideRight', 0.0)),
            'bs_jaw_open': _f(bs.get('jawOpen', 0.0)),
            'bs_mouth_pucker': _f(bs.get('mouthPucker', 0.0)),
            'bs_mouth_funnel': _f(bs.get('mouthFunnel', 0.0)),
            'bs_mouth_smile_l': _f(bs.get('mouthSmileLeft', 0.0)),
            'bs_mouth_smile_r': _f(bs.get('mouthSmileRight', 0.0)),
            'bs_mouth_frown_l': _f(bs.get('mouthFrownLeft', 0.0)),
            'bs_mouth_frown_r': _f(bs.get('mouthFrownRight', 0.0)),
            'bs_brow_down_l': _f(bs.get('browDownLeft', 0.0)),
            'bs_brow_down_r': _f(bs.get('browDownRight', 0.0)),
            'bs_brow_up_c': _f(bs.get('browInnerUp', 0.0)),
            'bs_cheek_puff': _f(bs.get('cheekPuff', 0.0)),
            'bs_look_in_l': _f(bs.get('eyeLookInLeft', 0.0)),
            'bs_look_out_l': _f(bs.get('eyeLookOutLeft', 0.0)),
            'bs_look_up_l': _f(bs.get('eyeLookUpLeft', 0.0)),
            'bs_look_down_l': _f(bs.get('eyeLookDownLeft', 0.0)),
            'blendshapes': bs,
            'has_blendshapes': _f(1.0 if bs else 0.0),
        }

    # -- hands --------------------------------------------------------------

    def _hand(self, img, w, h):
        strict = self._run('hand', 'strict', img)
        weak = self._run('hand', 'weak', img)
        ns = len(strict.hand_landmarks) if strict and strict.hand_landmarks else 0
        nw = len(weak.hand_landmarks) if weak and weak.hand_landmarks else 0
        src = strict if ns else weak
        items = []
        if src and src.hand_landmarks:
            for i, lms in enumerate(src.hand_landmarks):
                pts = [(_f(l.x), _f(l.y)) for l in lms]
                side = ''
                try:
                    side = src.handedness[i][0].category_name
                except (AttributeError, IndexError, TypeError) as _exc:
                    _zyg_log.debug('handedness unavailable for this hand: %s', _exc)
                items.append(self._hand_derive(pts, side))
        tiled = False
        if not items:
            for pts, side in self._escalate('hand', self._last_bgr):
                items.append(self._hand_derive(pts, side))
                tiled = True
        st = self._state(ns, nw)
        if tiled and st == 'none':
            st = 'weak'
        return {
            'state': st,
            'n_strict': ns,
            'n_weak': nw or (len(items) if tiled else 0),
            'items': items,
            'tiled': tiled,
        }

    @staticmethod
    def _hand_derive(pts, side):
        # 21-point hand: 0 wrist, 4 thumb tip, 8 index tip, 12 middle, 16 ring,
        # 20 pinky; 5/9/13/17 are the MCP knuckles.
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        palm = max(_EPS, _dist(pts[0], pts[9]))
        tips, mcps = (4, 8, 12, 16, 20), (2, 5, 9, 13, 17)
        curls = []
        for t, _m in zip(tips, mcps):
            curls.append(_f(_dist(pts[t], pts[0]) / palm))
        return {
            'side': side,
            'bbox': {'x': _f(min(xs)), 'y': _f(min(ys)), 'w': _f(max(xs) - min(xs)), 'h': _f(max(ys) - min(ys))},
            'wrist': [_f(pts[0][0]), _f(pts[0][1])],
            'index_tip': [_f(pts[8][0]), _f(pts[8][1])],
            'thumb_tip': [_f(pts[4][0]), _f(pts[4][1])],
            'palm_len': _f(palm),
            # grasp aperture in palm-lengths: ~0.3 pinched, >1.2 open
            'pinch_aperture': _f(_dist(pts[4], pts[8]) / palm),
            'spread': _f(_dist(pts[4], pts[20]) / palm),
            'finger_extension': [_f(c) for c in curls],
            'extension_mean': _f(sum(curls) / len(curls)),
            # 1.0 = flat open hand, ~0.45 = closed fist
            'openness': _f(sum(curls) / len(curls)),
            'pts': [[_f(p[0]), _f(p[1])] for p in pts],
        }


# ── sequence-level derivation (velocities live HERE, not in step()) ──────────


def velocities(seq, unique_idx, fps):
    """Per-subject velocities and accelerations, computed ONLY between
    consecutive UNIQUE cels and then expressed per SECOND.

    This is the cadence contract made concrete. On a clip shot on 2s, frames
    i and i+1 are the same drawing: a naive per-frame velocity alternates
    real, 0, real, 0 and every peak detector sees a strobing signal. Sampling
    the unique indices and dividing by the REAL elapsed time recovers the
    motion the animator actually drew.

    seq        : list of per-frame dicts from LandmarkTracker.step()
    unique_idx : indices of the first frame of each held cel (vfx_metrics.cadence_map)
    Returns a list parallel to unique_idx.
    """
    out = []
    keys = ('wrist_l', 'wrist_r', 'ankle_l', 'ankle_r', 'nose', 'com', 'pelvis')
    prev = None
    prev_i = None
    for u in unique_idx:
        fr = seq[u] if 0 <= u < len(seq) else {}
        pose = (fr.get('pose') or {}).get('items') or []
        cur = pose[0] if pose else None
        rec = {'frame': int(u), 'has_pose': bool(cur)}
        if cur and prev and prev_i is not None:
            dt = max(_EPS, (u - prev_i) / float(max(_EPS, fps)))
            unit = max(_EPS, cur.get('unit', 0.02))
            for k in keys:
                a, b = prev.get(k), cur.get(k)
                if not (isinstance(a, list) and isinstance(b, list)):
                    continue
                d = math.hypot(b[0] - a[0], b[1] - a[1])
                # torso-lengths per second: scale-free, so one threshold works
                # on a close-up and on a wide shot alike
                rec[f'v_{k}'] = _f(d / unit / dt)
                rec[f'vx_{k}'] = _f((b[0] - a[0]) / unit / dt)
                rec[f'vy_{k}'] = _f((b[1] - a[1]) / unit / dt)
            for k in (
                'elbow_l_deg',
                'elbow_r_deg',
                'knee_l_deg',
                'knee_r_deg',
                'hip_l_deg',
                'hip_r_deg',
                'shoulder_l_deg',
                'shoulder_r_deg',
                'torso_lean_deg',
            ):
                if k in cur and k in prev:
                    rec[f'd_{k}'] = _f((cur[k] - prev[k]) / dt)
        if cur:
            prev, prev_i = cur, u
        out.append(rec)
    # acceleration: an IMPACT is a velocity that stops, which is a large
    # negative acceleration — not a large velocity. Kicks and slaps land here.
    for i in range(1, len(out)):
        for k in list(out[i].keys()):
            if not k.startswith('v_'):
                continue
            p = out[i - 1].get(k)
            if p is None:
                continue
            dt = max(_EPS, (out[i]['frame'] - out[i - 1]['frame']) / float(max(_EPS, fps)))
            out[i]['a' + k[1:]] = _f((out[i][k] - p) / dt)
    return out


def describe():
    """Every landmark-tier scalar this module can emit, for the run report."""
    return {
        'pose': [
            'bbox',
            'vis_mean',
            'torso_len',
            'shoulder_w',
            'unit',
            'neck',
            'pelvis',
            'com',
            'elbow_l_deg',
            'elbow_r_deg',
            'knee_l_deg',
            'knee_r_deg',
            'hip_l_deg',
            'hip_r_deg',
            'shoulder_l_deg',
            'shoulder_r_deg',
            'torso_lean_deg',
            'shoulder_tilt_deg',
            'wrist_l_reach',
            'wrist_r_reach',
            'ankle_l_reach',
            'ankle_r_reach',
            'stance_ratio',
            'feet_spread',
        ],
        'face': [
            'ear_left',
            'ear_right',
            'ear_mean',
            'ear_asym',
            'mar',
            'mouth_open_norm',
            'mouth_width_norm',
            'head_yaw_deg',
            'head_pitch_deg',
            'head_roll_deg',
            'bs_blink_l',
            'bs_blink_r',
            'bs_squint_l',
            'bs_squint_r',
            'bs_wide_l',
            'bs_wide_r',
            'bs_jaw_open',
            'bs_mouth_pucker',
            'bs_mouth_funnel',
            'bs_mouth_smile_l',
            'bs_mouth_smile_r',
            'bs_mouth_frown_l',
            'bs_mouth_frown_r',
            'bs_brow_down_l',
            'bs_brow_down_r',
            'bs_brow_up_c',
            'bs_cheek_puff',
        ],
        'hand': ['side', 'palm_len', 'pinch_aperture', 'spread', 'finger_extension', 'extension_mean', 'openness'],
        'velocity': [
            'v_wrist_l',
            'v_wrist_r',
            'v_ankle_l',
            'v_ankle_r',
            'v_nose',
            'v_com',
            'v_pelvis',
            'a_wrist_l',
            'a_wrist_r',
            'a_ankle_l',
            'a_ankle_r',
            'd_elbow_l_deg',
            'd_knee_l_deg',
        ],
    }
