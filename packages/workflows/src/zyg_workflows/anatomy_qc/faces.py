# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""anatomy_qc face candidate harvesting and face mesh geometry gates."""

from __future__ import annotations

import math
import os


from .constants import (
    FACE_CONF,
    FACE_CONF_STRONG,
    NOISE_FACE_PX,
    STRICT_COUNT,
    YAW_FRONTAL,
    _F_BROW,
    _F_CHEEK_L,
    _F_CHEEK_R,
    _F_CHIN,
    _F_EYE_L_IN,
    _F_EYE_L_OUT,
    _F_EYE_R_IN,
    _F_EYE_R_OUT,
    _F_IRIS_L,
    _F_IRIS_R,
    _F_LIP_BOT,
    _F_LIP_TOP,
    _F_MOUTH_L,
    _F_MOUTH_R,
    _LOCK,
    _log_noop,
)
from .runtime import (
    _dist,
    _get_landmarker,
    _mp_image,
    _np,
    _read_bgr,
)
from .hands import (
    _dedupe,
    _tile_boxes,
    _tile_grids,
)


def _face_candidates(bgr, conf, want=None, only_boxes=None):
    np = _np()
    h, w = bgr.shape[:2]

    def _harvest(box):
        x1, y1, x2, y2 = box
        sub = bgr[y1:y2, x1:x2]
        if sub.size == 0:
            return []
        res = _detect_faces(sub, conf)
        sh, sw = sub.shape[:2]
        out = []
        for lms in res.face_landmarks or []:
            pts = _face_points(lms, sw, sh) + np.asarray([x1, y1], dtype=float)
            out.append({'pts': pts, 'tile': box})
        return out

    if only_boxes is not None:
        cands = []
        for box in only_boxes:
            cands.extend(_harvest(box))
    else:
        cands = _harvest((0, 0, w, h))
        if want is not None:
            for grid in _tile_grids(w, h):
                if len(cands) >= want:
                    break
                for box in _tile_boxes(w, h, grid):
                    cands.extend(_harvest(box))
    cands = [c for c in cands if float(c['pts'][:, 0].max() - c['pts'][:, 0].min()) >= NOISE_FACE_PX]
    return list(_dedupe(cands))


# ---------------------------------------------------------------------------
# face geometry
# ---------------------------------------------------------------------------
def _face_points(landmarks, w, h):
    np = _np()
    return np.asarray([[lm.x * w, lm.y * h] for lm in landmarks], dtype=float)


def _face_metrics(pts):
    """Scale-free facial ratios. None entries mean 'not measurable'."""
    np = _np()
    n = pts.shape[0]

    def p(i):
        return pts[i] if i < n else None

    face_w = _dist(p(_F_CHEEK_L), p(_F_CHEEK_R)) if p(_F_CHEEK_L) is not None and p(_F_CHEEK_R) is not None else 0.0
    face_h = _dist(p(_F_BROW), p(_F_CHIN)) if p(_F_BROW) is not None and p(_F_CHIN) is not None else 0.0
    if p(_F_IRIS_L) is not None and p(_F_IRIS_R) is not None:
        eye_l, eye_r = p(_F_IRIS_L), p(_F_IRIS_R)
    else:
        eye_l = (p(_F_EYE_L_OUT) + p(_F_EYE_L_IN)) / 2.0
        eye_r = (p(_F_EYE_R_OUT) + p(_F_EYE_R_IN)) / 2.0
    inter = _dist(eye_l, eye_r)
    mouth_w = _dist(p(_F_MOUTH_L), p(_F_MOUTH_R))
    mouth_h = _dist(p(_F_LIP_TOP), p(_F_LIP_BOT))
    eye_mid = (np.asarray(eye_l) + np.asarray(eye_r)) / 2.0
    mouth_mid = (p(_F_MOUTH_L) + p(_F_MOUTH_R)) / 2.0
    eye_mouth = _dist(eye_mid, mouth_mid)
    w_eye_l = _dist(p(_F_EYE_L_OUT), p(_F_EYE_L_IN))
    w_eye_r = _dist(p(_F_EYE_R_OUT), p(_F_EYE_R_IN))
    biggest = max(w_eye_l, w_eye_r)
    # Yaw proxy: how far the nose tip sits off the eye midpoint ALONG the eye
    # axis, in inter-ocular units. ~0 frontal, >0.18 turning, ~0.5 profile.
    # Needed because a profile foreshortens the far eye, and eye-width
    # asymmetry then measures pose, not melt (scene20_v7's faces are all
    # three-quarter/profile and every one of them looked "asymmetric").
    yaw = None
    if inter > 1e-6 and p(1) is not None:
        axis = (np.asarray(eye_r) - np.asarray(eye_l)) / inter
        yaw = float(np.dot(np.asarray(p(1)) - eye_mid, axis)) / inter
    return {
        'yaw_proxy': None if yaw is None else round(yaw, 4),
        'frontal': None if yaw is None else bool(abs(yaw) <= YAW_FRONTAL),
        'inter_ocular_px': round(inter, 2),
        'face_width_px': round(face_w, 2),
        'face_height_px': round(face_h, 2),
        'interocular_ratio': round(inter / face_w, 4) if face_w > 1e-6 else None,
        'mouth_ratio': round(mouth_w / inter, 4) if inter > 1e-6 else None,
        'mouth_open_ratio': round(mouth_h / inter, 4) if inter > 1e-6 else None,
        'eye_mouth_ratio': round(eye_mouth / inter, 4) if inter > 1e-6 else None,
        'eye_asymmetry': (round(abs(w_eye_l - w_eye_r) / biggest, 4) if biggest > 1e-6 else None),
        'centroid': (float(pts[:, 0].mean()), float(pts[:, 1].mean())),
    }


_FACE_BANDS = {  # ratio -> (lo, hi) plausible band
    'interocular_ratio': (0.26, 0.66),
    'mouth_ratio': (0.50, 1.55),
    'eye_mouth_ratio': (0.70, 2.30),
}


def _detect_faces(bgr, conf):
    lmk = _get_landmarker('face', conf)
    with _LOCK:
        return lmk.detect(_mp_image(bgr))


def _faces_from_array(bgr, expected_faces=None):
    np = _np()
    h, w = bgr.shape[:2]
    want = int(expected_faces) if expected_faces else 1
    cands = _face_candidates(bgr, FACE_CONF, want)
    if FACE_CONF_STRONG > FACE_CONF and cands:
        boxes = list(dict.fromkeys(c['tile'] for c in cands))
        strict = _face_candidates(bgr, FACE_CONF_STRONG, only_boxes=boxes)
    else:
        strict = cands

    strict_c = [np.asarray([c['pts'][:, 0].mean(), c['pts'][:, 1].mean()]) for c in strict]
    match_tol = 0.06 * math.hypot(w, h)

    faces, issues = [], []
    for i, cand in enumerate(cands):
        pts = cand['pts']
        try:
            m = _face_metrics(pts)
        except Exception as exc:
            # A short/odd mesh must not abort the frame (or, via the clip
            # loop, the whole pass): report it and move on.
            issues.append(
                {
                    'tag': 'face-mesh-unreadable',
                    'face': i,
                    'severity': 'unknown',
                    'text': f'{type(exc).__name__}: {exc} ({pts.shape[0]} landmarks)',
                }
            )
            continue
        c = np.asarray(m['centroid'])
        strong = any(float(np.linalg.norm(c - sc)) <= match_tol for sc in strict_c)
        m['strong'] = bool(strong)
        m['index'] = i
        m['n_landmarks'] = int(pts.shape[0])
        m['box'] = (
            round(float(pts[:, 0].min()), 1),
            round(float(pts[:, 1].min()), 1),
            round(float(pts[:, 0].max()), 1),
            round(float(pts[:, 1].max()), 1),
        )
        f_issues = []
        # Stylized caveat: geometry only becomes a hard verdict on faces the
        # STRICT detector also found. Arcane-restyled renders routinely fall
        # below 0.5 and their ratios are then unscored, not "clean".
        frontal = bool(m.get('frontal'))
        f_hard = 'hard' if strong else 'advisory'
        for key, (lo, hi) in _FACE_BANDS.items():
            v = m.get(key)
            if v is None:
                continue
            # A turned head compresses the inter-ocular span; only the
            # pose-invariant ratios stay in band off-axis.
            if not frontal and key == 'interocular_ratio':
                continue
            if v < lo or v > hi:
                f_issues.append(
                    (
                        f'{key.replace("_", "-")}-implausible',
                        f'{key}={v:.3f} outside [{lo}, {hi}] (yaw {m.get("yaw_proxy")})',
                        f_hard,
                    )
                )
        if frontal and m.get('eye_asymmetry') is not None and m['eye_asymmetry'] > 0.45:
            f_issues.append(
                (
                    'eye-asymmetry',
                    f'eye width asymmetry {m["eye_asymmetry"]:.2f} > 0.45 on a frontal face (yaw {m.get("yaw_proxy")})',
                    f_hard,
                )
            )
        if not strong:
            f_issues.append(
                (
                    'low-confidence-face',
                    'face found only by the permissive pass — geometry advisory (stylized/profile)',
                    'unknown',
                )
            )
        m['issues'] = f_issues
        m['ok'] = False if any(s == 'hard' for _, _, s in f_issues) else (None if f_issues else True)
        faces.append(m)
        for tag, text, sev in f_issues:
            issues.append({'tag': tag, 'face': i, 'severity': sev, 'text': text})

    n = len(faces)
    n_strong = sum(1 for f in faces if f['strong'])
    if expected_faces is not None:
        exp = int(expected_faces)
        if n == 0 and exp > 0:
            issues.append(
                {
                    'tag': 'no-faces-detected',
                    'face': None,
                    'severity': 'unknown',
                    'text': f'expected {exp} face(s), detected 0 — UNKNOWN',
                }
            )
        elif n > exp:
            issues.append(
                {
                    'tag': 'face-count-mismatch',
                    'face': None,
                    'severity': 'hard' if n_strong > exp else 'advisory',
                    'text': f'detected {n} face(s) ({n_strong} strong) > expected {exp} (ghost/double face)',
                }
            )
        elif n < exp:
            issues.append(
                {
                    'tag': 'face-count-mismatch',
                    'face': None,
                    'severity': 'hard' if STRICT_COUNT else 'advisory',
                    'text': f'detected {n} face(s) < expected {exp}',
                }
            )

    sev = {i['severity'] for i in issues}
    ok = False if 'hard' in sev else (None if ('unknown' in sev or n == 0) else True)
    return {
        'ok': ok,
        'faces': faces,
        'issues': issues,
        'detected': n,
        'strong': n_strong,
        'expected_faces': expected_faces,
        'error': None,
    }


def qc_face_frame(image_path: str, expected_faces=None, log_fn=None) -> dict:
    """Face-mesh gate for ONE still. Never raises. Same tri-state 'ok' rule as
    qc_hands_frame. Frame-level scoring is static plausibility only — melt,
    ratio drift and jitter need a series and live in qc_face_clip."""
    log = log_fn or _log_noop
    try:
        out = _faces_from_array(_read_bgr(image_path), expected_faces)
        out['image'] = image_path
    except Exception as exc:
        log(f'anatomy_qc: face gate unavailable for {os.path.basename(image_path)} ({type(exc).__name__}: {exc})')
        return {
            'ok': None,
            'faces': [],
            'issues': [
                {
                    'tag': 'face-gate-unavailable',
                    'face': None,
                    'severity': 'unknown',
                    'text': f'{type(exc).__name__}: {exc}',
                }
            ],
            'detected': 0,
            'strong': 0,
            'expected_faces': expected_faces,
            'image': image_path,
            'error': f'{type(exc).__name__}: {exc}',
        }
    if out['issues']:
        log(
            f'anatomy_qc: face {os.path.basename(image_path)} ok={out["ok"]} '
            f'detected={out["detected"]} :: ' + '; '.join(f'{i["tag"]}[{i["severity"]}]' for i in out['issues'])
        )
    return out
