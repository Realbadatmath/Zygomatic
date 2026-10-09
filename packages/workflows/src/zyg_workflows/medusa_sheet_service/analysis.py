# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from zyg_workflows.medusa_sheet_service.constants import (
    Any,
    FRAMING_TERMS,
    PITCH_BUCKETS,
    PITCH_TERMS,
    YAW_BUCKETS,
    YAW_TERMS,
    _BLUR_VAR_MIN,
    _EAR_DX_BACK_MAX,
    _EAR_DX_PROFILE_MAX,
    _MIN_EDGE_PX,
    _NOSE_OFF_SIDED_MIN,
    _POSE_MIN_SHOULDER_SPAN,
    _bucket,
    _euler_from_matrix,
    _get_detectors,
    os,
)

import logging as _zyg_logging

# Bound by ASSIGNMENT (not `from .constants import _zyg_log`) so the moved
# `_zyg_log.debug(...)` calls keep compiling to the same method form; the
# channel is kept from the pre-split module.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.medusa_sheet_service')

# ══════════════════════════════════════════════════════════════════════════
# Per-image analysis
# ══════════════════════════════════════════════════════════════════════════
POSE_NOSE, POSE_L_SH, POSE_R_SH = 0, 11, 12
POSE_L_EAR, POSE_R_EAR = 7, 8
POSE_L_HIP, POSE_R_HIP = 23, 24
POSE_L_ANK, POSE_R_ANK = 27, 28
POSE_L_KNEE, POSE_R_KNEE = 25, 26


def _framing_from(face_h_frac: float | None, pose_lm) -> str:
    """Framing from how much of the body is in frame.

    face_h_frac (face bbox height / image height) separates close-up from
    head-and-shoulders; pose landmark presence separates chest-up from
    full-body. Measured: close-up cell 0.54 vs head-and-shoulders ~0.32.
    """

    def _vis(idx: int) -> float:
        try:
            return float(pose_lm[idx].visibility)
        except Exception:
            return 0.0

    def _in_frame(idx: int) -> bool:
        """Visible AND actually inside the frame — MediaPipe happily
        extrapolates landmarks past the image edge with high visibility."""
        try:
            p = pose_lm[idx]
        except Exception:
            return False
        return float(p.visibility) >= 0.5 and -0.02 <= float(p.y) <= 1.02 and -0.02 <= float(p.x) <= 1.02

    if pose_lm is not None:
        ankles = _in_frame(POSE_L_ANK) or _in_frame(POSE_R_ANK)
        knees = _in_frame(POSE_L_KNEE) or _in_frame(POSE_R_KNEE)
        hips = _in_frame(POSE_L_HIP) or _in_frame(POSE_R_HIP)
        if ankles or knees:
            return 'full_body'
        if hips:
            return 'chest_up'

    if face_h_frac is not None:
        if face_h_frac >= 0.45:
            return 'close_up'
        if face_h_frac >= 0.12:
            return 'head_shoulders'
        # A small face with NO body landmarks in frame is not evidence of a full
        # body — it is equally a distant or occluded subject. Same rule as the
        # angle tiers: an absent word beats a wrong one in a caption.
        return 'unknown'
    return 'unknown'


def _dhash(img) -> int:
    """64-bit difference hash for near-duplicate detection."""
    from PIL import Image

    small = img.convert('L').resize((9, 8), Image.LANCZOS)
    px = list(small.getdata())
    bits = 0
    for row in range(8):
        base = row * 9
        for col in range(8):
            bits = (bits << 1) | (1 if px[base + col] > px[base + col + 1] else 0)
    return bits


def _blur_variance(img) -> float:
    """Variance of the Laplacian — the standard sharpness proxy."""
    try:
        import cv2
        import numpy as np

        g = np.asarray(img.convert('L'), dtype='uint8')
        if max(g.shape) > 720:
            scale = 720.0 / max(g.shape)
            g = cv2.resize(g, (max(1, int(g.shape[1] * scale)), max(1, int(g.shape[0] * scale))))
        return float(cv2.Laplacian(g, cv2.CV_64F).var())
    except Exception:
        return -1.0


def analyze_image(path: str) -> dict:
    """Measure one photograph. Never raises — returns {'error': ...} instead."""
    out: dict[str, Any] = {'file': os.path.basename(path)}
    try:
        from PIL import Image, ImageOps
        import mediapipe as mp
        import numpy as np
    except Exception as exc:
        return {'file': os.path.basename(path), 'error': f'imaging stack unavailable: {exc}'}

    try:
        pil = Image.open(path)
        pil = ImageOps.exif_transpose(pil).convert('RGB')
    except Exception:
        return {'file': os.path.basename(path), 'error': 'decode failed'}

    w, h = pil.size
    out['width'], out['height'] = w, h
    out['blur_var'] = round(_blur_variance(pil), 1)
    out['dhash'] = _dhash(pil)

    face_det, pose_det = _get_detectors()
    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(pil, dtype='uint8'))

    yaw = pitch = roll = None
    face_h_frac = None
    try:
        fr = face_det.detect(mp_img)
        if fr.facial_transformation_matrixes:
            yaw, pitch, roll = _euler_from_matrix(fr.facial_transformation_matrixes[0])
            lm = fr.face_landmarks[0]
            ys = [p.y for p in lm]
            face_h_frac = max(ys) - min(ys)
    except Exception as _exc:
        _zyg_log.debug('face detection produced no usable transform: %s', _exc)

    pose_lm = None
    sh_span = ear_dx = nose_off = None
    try:
        pr = pose_det.detect(mp_img)
        if pr.pose_landmarks:
            pose_lm = pr.pose_landmarks[0]
            l_sh, r_sh = float(pose_lm[POSE_L_SH].x), float(pose_lm[POSE_R_SH].x)
            sh_span = abs(l_sh - r_sh)
            if sh_span >= _POSE_MIN_SHOULDER_SPAN:
                ear_dx = (float(pose_lm[POSE_L_EAR].x) - float(pose_lm[POSE_R_EAR].x)) / sh_span
                nose_off = (float(pose_lm[POSE_NOSE].x) - (l_sh + r_sh) / 2.0) / sh_span
    except Exception as _exc:
        _zyg_log.debug('pose detection produced no usable landmarks: %s', _exc)

    out['has_face'] = yaw is not None
    out['has_pose'] = pose_lm is not None
    if face_h_frac is not None:
        out['face_h_frac'] = round(face_h_frac, 3)
    if sh_span is not None:
        out['shoulder_span'] = round(sh_span, 3)

    # Head landmark positions in PIXELS — consumed by medusa_body_mask's
    # placement check to prove a face mask actually landed on the head rather
    # than on a hand, a background object, or a second person.
    if pose_lm is not None:
        pts = []
        for idx in (POSE_NOSE, POSE_L_EAR, POSE_R_EAR, 2, 5):
            try:
                p = pose_lm[idx]
                pts.append([round(float(p.x) * w, 1), round(float(p.y) * h, 1)])
            except (IndexError, TypeError, ValueError) as _exc:
                _zyg_log.debug('head landmark %s unavailable: %s', idx, _exc)
                continue
        if pts:
            out['head_points'] = pts
    if ear_dx is not None:
        out['ear_dx'] = round(ear_dx, 3)
        out['nose_off'] = round(nose_off, 3)

    # ── Angle decision ────────────────────────────────────────────────────
    if yaw is not None:
        # Tier 1 — head-pose geometry. Authoritative.
        out['yaw'] = round(yaw, 1)
        out['pitch'] = round(pitch, 1)
        out['roll'] = round(roll, 1)
        out['yaw_slot'] = _bucket(yaw, YAW_BUCKETS)
        out['pitch_slot'] = _bucket(pitch, PITCH_BUCKETS)
        out['angle_method'] = 'geometry'
        out['angle_confidence'] = 'high'
    elif ear_dx is not None:
        # Tier 2 — pose geometry. Sign of ear_dx picks the hemisphere, its
        # magnitude picks profile-vs-front, nose_off recovers the side.
        sided_left = nose_off <= -_NOSE_OFF_SIDED_MIN
        sided_right = nose_off >= _NOSE_OFF_SIDED_MIN
        if ear_dx <= _EAR_DX_BACK_MAX:
            # Facing away. Never sided — see the module docstring.
            out['yaw_slot'] = 'back_three_quarter' if (sided_left or sided_right) else 'back'
            out['angle_method'] = 'pose_geometry'
            out['angle_confidence'] = 'medium'
        elif ear_dx < _EAR_DX_PROFILE_MAX:
            out['yaw_slot'] = 'profile_left' if sided_left else 'profile_right' if sided_right else 'profile_unsided'
            out['angle_method'] = 'pose_geometry'
            out['angle_confidence'] = 'low'
        else:
            # Facing the camera with ears well separated, yet no face mesh —
            # usually a face too small in frame or an extreme pitch. There is
            # no evidence for a specific angle here, so claim none.
            out['yaw_slot'] = 'unknown'
            out['angle_method'] = 'none'
            out['angle_confidence'] = 'none'
        out['pitch_slot'] = 'unknown'
    else:
        out['yaw_slot'] = 'unknown'
        out['pitch_slot'] = 'unknown'
        out['angle_method'] = 'none'
        out['angle_confidence'] = 'none'

    out['framing_slot'] = _framing_from(face_h_frac, pose_lm)

    # ── QC flags ──────────────────────────────────────────────────────────
    flags: list[str] = []
    if not out['has_face'] and not out['has_pose']:
        flags.append('no_person_detected')
    if min(w, h) < _MIN_EDGE_PX:
        flags.append('low_resolution')
    if 0 <= out['blur_var'] < _BLUR_VAR_MIN:
        flags.append('soft_or_blurry')
    if out['angle_confidence'] in ('none',):
        flags.append('angle_unknown')
    out['flags'] = flags
    return out


# ══════════════════════════════════════════════════════════════════════════
# Captions
# ══════════════════════════════════════════════════════════════════════════
def caption_for(meas: dict, trigger: str, suffix: str = '', mode: str = 'identity', promptables: str = '') -> str:
    """Assemble a caption from the fixed vocabulary.

    Order: trigger, framing, yaw, pitch, operator suffix. Anything unknown is
    simply omitted — we never write a guessed angle.

    MODE INVERTS THE IDENTITY RULE. The house rule is that whatever you caption
    stays promptable and whatever you omit welds itself to the trigger token:

      identity  — face, hair and build are deliberately NOT captioned, so they
                  bind to the trigger and the character stays recognisable.
      body      — the trigger names a BODY, so the operator's hair/skin/wardrobe
                  description MUST be captioned. Omit it and this person's
                  haircut ships with every body generated from the template.

    The vocabulary tables are NOT extended for body mode: hair and skin arrive
    as an operator-supplied string, not a measured word. There is no calibrated
    hair or skin classifier on this box, and the module's rule is never to write
    a word it cannot measure.
    """
    parts: list[str] = []
    if trigger:
        parts.append(f'{trigger} body type' if mode == 'body' else trigger)

    framing = FRAMING_TERMS.get(meas.get('framing_slot') or 'unknown', '')
    yaw_term = YAW_TERMS.get(meas.get('yaw_slot') or 'unknown', '')
    pitch_term = PITCH_TERMS.get(meas.get('pitch_slot') or 'unknown', '')

    if framing and yaw_term:
        parts.append(f'{framing}, {yaw_term}')
    elif framing:
        parts.append(framing)
    elif yaw_term:
        parts.append(yaw_term)
    if pitch_term:
        parts.append(pitch_term)
    if mode == 'body' and (promptables or '').strip():
        parts.append(promptables.strip())
    if suffix:
        parts.append(suffix)
    return ', '.join(p for p in parts if p)
