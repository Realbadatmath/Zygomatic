# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Image space - the same vocabulary on MediaPipe's 21-point hand landmarks.

Moved verbatim out of the old single-file hands.py (lines 1289-1631).
"""

import numpy as np
import logging as _zyg_logging

from zyg_workflows.geom.form.hands.rig import (
    SCHEMA,
    REPORT,
    UNMEASURABLE,
    DIGITS,
    FINGERS,
    _line_residuals,
    _line_angle,
)
from zyg_workflows.geom.form.hands.provenance import (
    _rec,
)
from zyg_workflows.geom.form.hands.mesh import (
    calibration,
    _band_for,
)
from zyg_workflows.geom.form.hands.unresolved import (
    IMAGE_UNRESOLVED,
)

_zyg_log = _zyg_logging.getLogger(__name__)


# ---------------------------------------------------------------------------------
# Image space — the same vocabulary on MediaPipe's 21-point hand landmarks
#
# MediaPipe HandLandmarker indices, from the model card:
#   0 wrist
#   1 thumb CMC   2 thumb MCP   3 thumb IP    4 thumb TIP
#   5 index MCP   6 PIP         7 DIP         8 TIP
#   9 middle MCP 10 PIP        11 DIP        12 TIP
#  13 ring MCP   14 PIP        15 DIP        16 TIP
#  17 pinky MCP  18 PIP        19 DIP        20 TIP
# ---------------------------------------------------------------------------------
MP = {
    'wrist': 0,
    'thumb': (1, 2, 3, 4),
    'index': (5, 6, 7, 8),
    'middle': (9, 10, 11, 12),
    'ring': (13, 14, 15, 16),
    'little': (17, 18, 19, 20),
}
MP_MCP = {'thumb': 2, 'index': 5, 'middle': 9, 'ring': 13, 'little': 17}
MP_TIP = {'thumb': 4, 'index': 8, 'middle': 12, 'ring': 16, 'little': 20}

# HOUSE. Below this hand span in pixels the landmark model is regressing a hand it cannot
# resolve, and a confident 21-point answer on a 30-pixel blob is a detector LIE. Reported
# on every hand rather than used to drop it silently.
MIN_HAND_PX = 60.0
# HOUSE. A digit chain defines a plane only if it is bent. This is the minimum ratio of
# the chain's second principal extent to its first; below it the plane normal is noise and
# thumb_opposition returns unmeasurable for that hand.
MIN_CHAIN_BEND = 0.04


# WHY NOTHING IN THE IMAGE PATH GATES.
#
# The mesh calibration cannot be carried across, for two independent reasons, and both were
# measured rather than argued:
#
#   * A PIXEL STATISTIC IS A PROJECTION. The knuckle-arch residual seen in a frame is the
#     3D arch foreshortened by whatever the camera happened to be doing, so it is bounded
#     ABOVE by the mesh value and a mesh floor applied to it would fail correct hands for
#     being turned away from the lens. Measured on 14 real hands in Abel's LoRA cells the
#     image values run 0.013-0.022 against 0.0115-0.0118 in mesh space — overlapping in
#     magnitude and not the same quantity.
#   * AN IMAGE-SPACE REFERENCE SAMPLE CANNOT BE BUILT FROM OUR OWN GEOMETRY ON THIS
#     MACHINE. MediaPipe's hand landmarker finds 0 hands in all 16 shaded cage renders
#     under data/assets/mesh_skeletons/, and still 0 over 28 pose-derived hand crops
#     upscaled to 384 px. It is trained on photographs and does not fire on an untextured
#     grid-overlaid mesh, so the one population whose hands we KNOW are geometrically
#     correct is invisible to it. Calibrating instead on generated frames would calibrate
#     the gate to accept whatever our generator already emits, which is the defect.
#
# So the image path reports, and carries the mesh band alongside as `band_reference` for
# scale only. An image-space gate needs a reference corpus of REAL photographed hands
# measured through this same detector; that is a separate build.
IMAGE_NOT_GATED = (
    'REPORT ONLY. The mesh band travels as band_reference for scale and is NOT applied: a '
    'pixel statistic is a foreshortened projection of the mesh one, and MediaPipe finds 0 '
    'hands in 16/16 shaded cage renders and 0 in 28/28 upscaled hand crops of them, so no '
    'image-space reference sample of known-good hands can be built on this machine.'
)


def _chain_plane(P):
    """(normal, bend) of a 4-point digit chain. bend = s2/s1 of the centred points."""
    Y = np.asarray(P, np.float64)
    Y = Y - Y.mean(0)
    _, s, vt = np.linalg.svd(Y, full_matrices=False)
    bend = float(s[1] / s[0]) if s[0] > 0 else 0.0
    return vt[2], bend


def _image_predicates(pts, world=None):
    """Predicate records for one detected hand.

    `pts` is (21, 2) in ORIGINAL-image pixels — the 2D statistics are taken there because
    that is what a viewer sees and what the generator actually produced. `world` is
    MediaPipe's (21, 3) metric hand_world_landmarks, used ONLY for thumb_opposition, which
    is a 3D quantity that 2D landmarks cannot express at all. That reliance is flagged on
    the record: world landmarks come from a learned prior over real hands and will
    regularise a malformed one toward plausibility, so they are evidence about the pose
    the model inferred, not about the pixels.
    """
    P = np.asarray(pts, np.float64)[:, :2]
    cal = calibration()
    hand_len = float(np.linalg.norm(P[MP_TIP['middle']] - P[MP['wrist']]))
    span = float(max(P[:, 0].max() - P[:, 0].min(), P[:, 1].max() - P[:, 1].min()))
    preds = {}

    def ref(pred):
        band, cb, _ = _band_for(pred, cal)
        return band, (cb.get('source') if cb else None)

    band, src = ref('knuckle_arch')
    r4 = _line_residuals(P[[MP_MCP[d] for d in FINGERS]])
    val = float(np.sqrt((r4**2).mean()) / hand_len) if hand_len > 0 else None
    # The 3D counterpart, which the projection does NOT shrink. A pixel arch near zero is
    # either a flat knuckle line or a hand seen edge-on, and only this number separates
    # the two — at the cost of leaning on MediaPipe's learned 3D prior, so it is a
    # diagnostic beside the pixel value and never a replacement for it.
    world_arch = None
    if world is not None:
        Wp = np.asarray(world, np.float64)
        wl_len = float(np.linalg.norm(Wp[MP_TIP['middle']] - Wp[MP['wrist']]))
        if wl_len > 0:
            wr = _line_residuals(Wp[[MP_MCP[d] for d in FINGERS]])
            world_arch = float(np.sqrt((wr**2).mean()) / wl_len)
    preds['knuckle_arch'] = _rec(
        'knuckle_arch',
        'image',
        REPORT,
        val,
        'line residual over the four finger MCPs / hand length (wrist->middle tip), in pixels',
        'the four knuckles arch, so a line through landmarks 5/9/13/17 leaves a residual; '
        'a flat residual is the fused-knuckle hand. ' + IMAGE_NOT_GATED,
        band=None,
        source=src,
        band_reference=band,
        rms4_px=float(np.sqrt((r4**2).mean())),
        rms5_px=float(np.sqrt((_line_residuals(P[[MP_MCP[d] for d in DIGITS]]) ** 2).mean())),
        per_finger_px={d: float(x) for d, x in zip(FINGERS, r4)},
        world_arch=world_arch,
    )

    band, src = ref('middle_finger_ratio')
    mf = float(np.linalg.norm(P[MP_TIP['middle']] - P[MP_MCP['middle']]))
    val = mf / hand_len if hand_len > 0 else None
    preds['middle_finger_ratio'] = _rec(
        'middle_finger_ratio',
        'image',
        REPORT,
        val,
        'middle finger (MCP->tip) / hand length (wrist->middle tip), in pixels',
        'the middle finger is about half the hand. The proximal end is MediaPipe landmark '
        '0, which is not the wrist girth ring the mesh path measures from, so the two '
        'numbers are comparable in size but not identical by construction. ' + IMAGE_NOT_GATED,
        band=None,
        source=src,
        band_reference=band,
        middle_finger_px=mf,
        hand_length_px=hand_len,
    )

    preds['webbing'] = _rec(
        'webbing',
        'image',
        UNMEASURABLE,
        None,
        'commissure distance distal of the MCP line / proximal phalanx length',
        IMAGE_UNRESOLVED[0]['evidence'],
    )

    band, src = ref('thumb_opposition')
    if world is None:
        val, worst, bends, weak = None, None, {}, {}
        why = (
            'MediaPipe returned no hand_world_landmarks for this hand, and a flexion '
            'plane cannot be fitted to 2D points'
        )
    else:
        Wp = np.asarray(world, np.float64)
        normals, bends = {}, {}
        for d in DIGITS:
            normals[d], bends[d] = _chain_plane(Wp[list(MP[d])])
        weak = {d: round(b, 4) for d, b in bends.items() if b < MIN_CHAIN_BEND}
        if weak:
            val, worst = None, None
            why = 'digit chains %s are too straight to define a plane' % sorted(weak)
        else:
            M = sum(np.outer(normals[d], normals[d]) for d in FINGERS)
            _, V = np.linalg.eigh(M)
            val = _line_angle(normals['thumb'], V[:, -1])
            worst = max(
                _line_angle(normals[FINGERS[i]], normals[FINGERS[j]]) for i in range(4) for j in range(i + 1, 4)
            )
            why = None
    preds['thumb_opposition'] = _rec(
        'thumb_opposition',
        'image',
        (REPORT if val is not None else UNMEASURABLE),
        val,
        "degrees between the thumb flexion-plane normal and the four fingers' consensus",
        "a nail normal lies IN its digit's flexion plane, perpendicular to the digit's "
        'long axis, so rotating a digit about that axis turns the flexion-plane normal '
        'through the same angle the mesh path measures between dorso-palmar axes. Taken '
        'from MediaPipe world landmarks, which are a learned 3D prior over real hands and '
        'will regularise a malformed one. ' + (IMAGE_NOT_GATED if val is not None else why),
        band=None,
        source=src,
        band_reference=band,
        finger_agreement_deg=worst,
        chain_bend={d: round(b, 4) for d, b in bends.items()},
        ill_conditioned=weak,
        from_world_landmarks=world is not None,
    )

    preds['dorsal_over_palmar'] = _rec(
        'dorsal_over_palmar',
        'image',
        UNMEASURABLE,
        None,
        'dorsal ridge length / palmar ridge length',
        IMAGE_UNRESOLVED[1]['evidence'],
    )

    for p in preds.values():
        if span < MIN_HAND_PX and p['status'] == REPORT:
            p['explain'] += (
                ' Hand spans only %.0f px (floor %.0f): the landmark model '
                'returns 21 confident points on a blob this small, so this '
                'number is not evidence about the hand.' % (span, MIN_HAND_PX)
            )
            p['low_resolution'] = True
    return preds, {'hand_length_px': hand_len, 'span_px': span}


def _detect_hands_raw(bgr):
    """(pixel (21,2), world (21,3), handedness) per hand, via keypoints.py's cached model.

    geom.keypoints.detect() drops MediaPipe's z and its world landmarks, and thumb
    opposition is unrecoverable without them, so the shared singleton is called directly
    rather than a second copy of the model being loaded.
    """
    from zyg_workflows.geom import keypoints as K

    res = K._hands().detect(K._mp_image(bgr))
    h, w = bgr.shape[:2]
    out = []
    wl = getattr(res, 'hand_world_landmarks', None) or []
    for i, lm in enumerate(res.hand_landmarks or []):
        pix = np.array([[l.x * w, l.y * h] for l in lm], np.float64)
        world = np.array([[l.x, l.y, l.z] for l in wl[i]], np.float64) if i < len(wl) else None
        side = ''
        try:
            side = res.handedness[i][0].category_name.lower()
        except (AttributeError, IndexError) as _exc:
            _zyg_log.debug('handedness unavailable for this hand: %s', _exc)
        out.append((pix, world, side))
    return out


def _hand_crops(det, w, h):
    """Hand boxes from the BODY skeleton, for THE CROP RULE.

    Whole-frame hand detection misses small hands for the same reason whole-frame face
    detection misses small faces (see geom/keypoints.py): at frame scale there are not
    enough pixels. BlazePose puts a wrist, thumb, index and pinky point on each hand even
    when the hand landmarker cannot find it, and those four points give a box to re-run in.
    """
    from zyg_workflows.geom.keypoints import P as POSE_IDX

    if not det.body.ok:
        return []
    B = det.body.pts
    boxes = []
    for sd in ('left', 'right'):
        ids = [
            POSE_IDX['%s_wrist' % sd],
            POSE_IDX['%s_thumb' % sd],
            POSE_IDX['%s_index' % sd],
            POSE_IDX['%s_pinky' % sd],
        ]
        pts = B[ids]
        if float(pts[:, 2].max()) < 0.3:
            continue
        cx, cy = float(pts[:, 0].mean()), float(pts[:, 1].mean())
        r = float(np.linalg.norm(pts[:, :2] - np.array([cx, cy]), axis=1).max())
        half = max(r * 3.0, 48.0)
        x0, y0 = int(max(0, cx - half)), int(max(0, cy - half))
        x1, y1 = int(min(w, cx + half)), int(min(h, cy + half))
        if x1 - x0 >= 48 and y1 - y0 >= 48:
            boxes.append((sd, x0, y0, x1, y1))
    return boxes


def check_hand_image(image_or_path, want_crop=True):
    """FORM verdict for every hand MediaPipe finds in one frame.

    Returns {'schema', 'basis': 'image', 'image', 'hands': [...], 'unresolved': [...]}.
    Each hand carries the SAME predicate records check_hand_mesh returns, so a mesh
    verdict and a render verdict line up field for field.
    """
    import cv2
    from zyg_workflows.geom import keypoints as K

    bgr = cv2.imread(image_or_path) if isinstance(image_or_path, str) else image_or_path
    if bgr is None:
        raise FileNotFoundError(str(image_or_path))
    h, w = bgr.shape[:2]
    det = K.detect(image_or_path, want_hands=False)
    hands = []
    for i, (pix, world, side) in enumerate(_detect_hands_raw(bgr)):
        preds, meta = _image_predicates(pix, world)
        hands.append({'index': i, 'side': side or None, 'via': 'full', 'predicates': preds, **meta})
    crop_notes = []
    if want_crop and not hands:
        # crop-first retry, one box per side
        for sd, x0, y0, x1, y1 in _hand_crops(det, w, h):
            crop = bgr[y0:y1, x0:x1]
            s = 1.0
            if min(crop.shape[:2]) < 224:
                s = 224.0 / min(crop.shape[:2])
                crop = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
            got = _detect_hands_raw(crop)
            for pix, world, side in got:
                pix = pix.copy()
                pix[:, 0] = pix[:, 0] / s + x0
                pix[:, 1] = pix[:, 1] / s + y0
                preds, meta = _image_predicates(pix, world)
                hands.append(
                    {
                        'index': len(hands),
                        'side': side or sd,
                        'via': 'crop',
                        'crop_box': [x0, y0, x1, y1],
                        'predicates': preds,
                        **meta,
                    }
                )
            if not got:
                crop_notes.append(
                    {'side': sd, 'box': [x0, y0, x1, y1], 'why': 'no hand in the pose-derived crop either'}
                )
    return {
        'schema': SCHEMA,
        'basis': 'image',
        'image': image_or_path if isinstance(image_or_path, str) else '<array>',
        'width': w,
        'height': h,
        'body_detected': bool(det.body.ok),
        'hands': hands,
        'crop_retries': crop_notes,
        'unresolved': list(IMAGE_UNRESOLVED),
        'calibrated': False,
        'not_gated_reason': IMAGE_NOT_GATED,
        'handedness_note': (
            'MediaPipe handedness assumes an unmirrored photograph of a real person. '
            'On a rendered character it is a guess about which hand is which, and it '
            'has been observed to return two hands both labelled "right" on one '
            'frame. Nothing here depends on the label.'
        ),
    }
