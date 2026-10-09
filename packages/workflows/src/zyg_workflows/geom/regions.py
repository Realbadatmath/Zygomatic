# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""regions.py — the character region registry: named, addressable, fixed (2026-08-04).

THE POINT OF THE WHOLE SYSTEM. A LoRA character is pixels; nothing in the pipeline can say
"the left ear" about pixels. This module gives every character image a REGION MAP — a
uint8 image where 11 always means left ear, 14 always means torso, on every image of every
character — plus a wireframe overlay that visualises the fitted grid. Everything narrow
the user asked for hangs off that map: crop the lips for the VLM, inpaint only the eye,
measure freckles only on face skin, compare torso to torso across frames.

WHERE EACH REGION COMES FROM (and why it is trustworthy):
  face detail   filled polygons over the 478-point MediaPipe face mesh, whose TOPOLOGY IS
                FIXED — landmark 33 is the same eye corner on every human ever fitted.
                The lip/eye/iris/brow/oval index sets ship with MediaPipe (Apache-2.0,
                weights included; verified 2026-08-04) and are introspected from the
                installed package rather than copied, so they cannot drift from the model.
  nose          a curated index subset of the same mesh (the tasks API exposes no NOSE
                connection set; the indices below are the standard FaceMesh nose group).
  ears          BlazePose carries explicit left_ear/right_ear landmarks; each ear is an
                ellipse around its landmark, scaled by eye distance, clipped to the person
                mask, minus the face oval — so it can never eat cheek.
  body          every person-mask pixel is assigned to its NEAREST BONE (distance to the
                skeleton's segments, normalised per-bone). Voronoi-by-bone means baggy
                17th-century breeches still label as thigh — the nearest bone is the
                thigh — where any fixed-width capsule would leak or starve.
  hair/head     person pixels above the shoulders claimed by neither face nor ears.

PRIORITY. Later layers overwrite earlier ones: body capsules < head/hair < face skin <
ears < nose < brows < eyes < lips < irises. An iris pixel is iris even though it is also
inside the eye, the face oval, the head and the person.

ABSENCE IS INFORMATION. A rear view gets body+hair regions and NO face regions, because
the detector correctly found no face; a gate that then demands lips on a rear view is
wrong, and gate_character.py conditions its expectations on what was detected.
"""

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from . import keypoints as K

# ── the registry: id → name. FIXED — downstream stores these ids on disk. ────
REGION_IDX = {
    'hair_head': 1,
    'face_skin': 2,
    'brow_left': 3,
    'brow_right': 4,
    'eye_left': 5,
    'eye_right': 6,
    'iris_left': 7,
    'iris_right': 8,
    'nose': 9,
    'lips': 10,
    'ear_left': 11,
    'ear_right': 12,
    'neck': 13,
    'torso': 14,
    'upper_arm_left': 15,
    'upper_arm_right': 16,
    'forearm_left': 17,
    'forearm_right': 18,
    'hand_left': 19,
    'hand_right': 20,
    'thigh_left': 21,
    'thigh_right': 22,
    'shin_left': 23,
    'shin_right': 24,
    'foot_left': 25,
    'foot_right': 26,
}
REGION_NAME = {v: k for k, v in REGION_IDX.items()}

FACE_REGIONS = (
    'face_skin',
    'brow_left',
    'brow_right',
    'eye_left',
    'eye_right',
    'iris_left',
    'iris_right',
    'nose',
    'lips',
)
BODY_REGIONS = (
    'neck',
    'torso',
    'upper_arm_left',
    'upper_arm_right',
    'forearm_left',
    'forearm_right',
    'hand_left',
    'hand_right',
    'thigh_left',
    'thigh_right',
    'shin_left',
    'shin_right',
    'foot_left',
    'foot_right',
)

# Distinct colours for the visual map (id -> BGR); background stays black.
_PALETTE = {
    1: (60, 60, 200),
    2: (120, 190, 250),
    3: (40, 120, 90),
    4: (40, 150, 110),
    5: (250, 200, 60),
    6: (250, 160, 40),
    7: (255, 255, 255),
    8: (230, 230, 230),
    9: (90, 220, 220),
    10: (80, 70, 230),
    11: (200, 120, 250),
    12: (170, 90, 230),
    13: (150, 150, 90),
    14: (90, 170, 60),
    15: (200, 200, 50),
    16: (170, 190, 40),
    17: (140, 220, 90),
    18: (110, 200, 70),
    19: (250, 250, 160),
    20: (230, 240, 130),
    21: (60, 110, 220),
    22: (50, 90, 200),
    23: (100, 60, 180),
    24: (90, 50, 160),
    25: (160, 120, 60),
    26: (140, 100, 50),
}

# The standard FaceMesh nose landmark group (bridge, dorsum, tip, alae, base).
_NOSE_IDS = [
    1,
    2,
    4,
    5,
    6,
    19,
    44,
    45,
    48,
    51,
    94,
    97,
    98,
    115,
    168,
    195,
    197,
    220,
    274,
    275,
    278,
    281,
    326,
    327,
    344,
    440,
]

# BlazePose bones per body region: (region, [(a, b, width_scale)...]) — width_scale
# multiplies the reference thickness (shoulder width) for nearest-bone normalisation.
_BONES = [
    ('neck', [('nose', 'mid_shoulder', 0.55)]),
    (
        'torso',
        [('left_shoulder', 'left_hip', 1.0), ('right_shoulder', 'right_hip', 1.0), ('mid_shoulder', 'mid_hip', 1.35)],
    ),
    ('upper_arm_left', [('left_shoulder', 'left_elbow', 0.42)]),
    ('upper_arm_right', [('right_shoulder', 'right_elbow', 0.42)]),
    ('forearm_left', [('left_elbow', 'left_wrist', 0.36)]),
    ('forearm_right', [('right_elbow', 'right_wrist', 0.36)]),
    ('hand_left', [('left_wrist', 'left_index', 0.40)]),
    ('hand_right', [('right_wrist', 'right_index', 0.40)]),
    ('thigh_left', [('left_hip', 'left_knee', 0.66)]),
    ('thigh_right', [('right_hip', 'right_knee', 0.66)]),
    ('shin_left', [('left_knee', 'left_ankle', 0.46)]),
    ('shin_right', [('right_knee', 'right_ankle', 0.46)]),
    ('foot_left', [('left_ankle', 'left_foot_index', 0.42)]),
    ('foot_right', [('right_ankle', 'right_foot_index', 0.42)]),
]


# ── MediaPipe connection sets, introspected from the installed package ───────


def _connection_sets():
    from mediapipe.tasks.python.vision.face_landmarker import FaceLandmarksConnections as C

    def edges(name):
        return [(c.start, c.end) for c in getattr(C, name)]

    return {
        'lips': edges('FACE_LANDMARKS_LIPS'),
        'eye_left': edges('FACE_LANDMARKS_LEFT_EYE'),
        'eye_right': edges('FACE_LANDMARKS_RIGHT_EYE'),
        'brow_left': edges('FACE_LANDMARKS_LEFT_EYEBROW'),
        'brow_right': edges('FACE_LANDMARKS_RIGHT_EYEBROW'),
        'iris_left': edges('FACE_LANDMARKS_LEFT_IRIS'),
        'iris_right': edges('FACE_LANDMARKS_RIGHT_IRIS'),
        'oval': edges('FACE_LANDMARKS_FACE_OVAL'),
        'tesselation': edges('FACE_LANDMARKS_TESSELATION'),
    }


_SETS = None


def _sets():
    global _SETS
    if _SETS is None:
        _SETS = _connection_sets()
    return _SETS


def _loop_from_edges(edges):
    """Order an edge soup into one closed loop (the outer loop when there are two)."""
    nxt = {}
    for a, b in edges:
        nxt.setdefault(a, []).append(b)
        nxt.setdefault(b, []).append(a)
    loops, seen = [], set()
    for start in nxt:
        if start in seen:
            continue
        loop, cur, prev = [start], start, None
        seen.add(start)
        while True:
            cand = [n for n in nxt[cur] if n != prev]
            if not cand:
                break
            prev, cur = cur, cand[0]
            if cur == start:
                break
            if cur in seen:
                break
            seen.add(cur)
            loop.append(cur)
        loops.append(loop)
    return max(loops, key=len)


def _fill(mask, pts_xy, ids, value):
    poly = np.array([pts_xy[i, :2] for i in ids], np.int32)
    if len(poly) >= 3:
        cv2.fillPoly(mask, [poly], int(value))


# ── the builder ──────────────────────────────────────────────────────────────


def build(det):
    """Region map (uint8 H*W of REGION_IDX values) from one keypoints.Detection."""
    h, w = det.h, det.w
    out = np.zeros((h, w), np.uint8)
    person = (det.person_mask > 0.5) if det.person_mask is not None else None

    # ── body: nearest-bone assignment inside the person mask ────────────────
    if det.body.ok and person is not None:
        b = det.body.pts
        pts = {n: b[K.P[n], :2] for n in K.POSE_NAMES}
        pts['mid_shoulder'] = (pts['left_shoulder'] + pts['right_shoulder']) / 2
        pts['mid_hip'] = (pts['left_hip'] + pts['right_hip']) / 2
        ref = max(float(np.linalg.norm(pts['left_shoulder'] - pts['right_shoulder'])), 16.0)

        ys, xs = np.nonzero(person)
        P2 = np.stack([xs, ys], 1).astype(np.float32)
        best_d = np.full(len(P2), np.inf, np.float32)
        best_id = np.zeros(len(P2), np.uint8)
        for region, bones in _BONES:
            rid = REGION_IDX[region]
            for a, bn, wsc in bones:
                A, B = pts[a], pts[bn]
                AB = B - A
                L2 = float(AB @ AB) or 1e-6
                t = np.clip(((P2 - A) @ AB) / L2, 0.0, 1.0)
                d = np.linalg.norm(P2 - (A + t[:, None] * AB), axis=1) / (ref * wsc)
                sel = d < best_d
                best_d[sel] = d[sel]
                best_id[sel] = rid
        out[ys, xs] = best_id

        # hair/head: person pixels above the shoulder line still unlabelled or labelled
        # neck get the head id — the face layers below will carve the face out of it
        shoulder_y = min(pts['left_shoulder'][1], pts['right_shoulder'][1])
        head_zone = np.zeros((h, w), bool)
        head_zone[: int(shoulder_y) + 1, :] = True
        sel = person & head_zone & np.isin(out, [0, REGION_IDX['neck']])
        # keep an actual neck: only override above the chin when a face exists
        chin_y = det.face.pts[152, 1] if det.face.ok else shoulder_y - 0.35 * ref
        rows = np.arange(h)[:, None]
        sel &= rows < chin_y + 0.20 * ref
        out[sel] = REGION_IDX['hair_head']

    # ── face detail from the 478 mesh ───────────────────────────────────────
    if det.face.ok:
        f = det.face.pts
        s = _sets()
        oval = _loop_from_edges(s['oval'])
        face_layer = np.zeros((h, w), np.uint8)
        _fill(face_layer, f, oval, REGION_IDX['face_skin'])

        # ears BEFORE the face fill is composited: ellipse at the BlazePose ear point,
        # clipped to person, minus the oval — so ears never eat cheek
        if det.body.ok:
            eye_d = float(np.linalg.norm(f[33, :2] - f[263, :2])) or 24.0
            for name, rid in (('left_ear', 'ear_left'), ('right_ear', 'ear_right')):
                e = det.body.pts[K.P[name]]
                if e[2] < 0.5:  # visibility gate — no fabricated ears
                    continue
                ear = np.zeros((h, w), np.uint8)
                cv2.ellipse(ear, (int(e[0]), int(e[1])), (int(eye_d * 0.22), int(eye_d * 0.34)), 0, 0, 360, 1, -1)
                m = (ear > 0) & (face_layer == 0)
                if person is not None:
                    m &= person
                out[m] = REGION_IDX[rid]

        m = face_layer > 0
        out[m] = face_layer[m]

        detail = np.zeros((h, w), np.uint8)
        hull = cv2.convexHull(np.array([f[i, :2] for i in _NOSE_IDS], np.float32))
        cv2.fillPoly(detail, [hull.astype(np.int32).reshape(-1, 2)], REGION_IDX['nose'])
        for key in ('brow_left', 'brow_right'):
            loop = _loop_from_edges(s[key])
            _fill(detail, f, loop, REGION_IDX[key])
        for key in ('eye_left', 'eye_right'):
            _fill(detail, f, _loop_from_edges(s[key]), REGION_IDX[key])
        _fill(detail, f, _loop_from_edges(s['lips']), REGION_IDX['lips'])
        for key in ('iris_left', 'iris_right'):
            _fill(detail, f, _loop_from_edges(s[key]), REGION_IDX[key])
        m = detail > 0
        out[m] = detail[m]

    return out


# ── visualisation ────────────────────────────────────────────────────────────


def colourise(region_map):
    out = np.zeros(region_map.shape + (3,), np.uint8)
    for rid, col in _PALETTE.items():
        out[region_map == rid] = col
    return out


def overlay(bgr, det, region_map, alpha=0.38, wire=True):
    """The deliverable image: region tint + face tesselation + skeleton, on the frame."""
    vis = bgr.copy()
    col = colourise(region_map)
    m = region_map > 0
    vis[m] = (vis[m].astype(np.float32) * (1 - alpha) + col[m].astype(np.float32) * alpha).astype(np.uint8)
    # region boundaries, thin
    edges = cv2.Canny(region_map * 9, 1, 1)
    vis[edges > 0] = (255, 255, 255)
    if wire and det.face.ok:
        f = det.face.pts
        for a, b in _sets()['tesselation']:
            cv2.line(vis, (int(f[a, 0]), int(f[a, 1])), (int(f[b, 0]), int(f[b, 1])), (90, 255, 130), 1, cv2.LINE_AA)
    if wire and det.body.ok:
        bpts = det.body.pts
        BONES2D = [
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
        ]
        for a, b in BONES2D:
            pa, pb = bpts[K.P[a]], bpts[K.P[b]]
            cv2.line(vis, (int(pa[0]), int(pa[1])), (int(pb[0]), int(pb[1])), (60, 200, 255), 2, cv2.LINE_AA)
    return vis


def stats(region_map):
    """{region_name: pixel_count} for every region present."""
    ids, counts = np.unique(region_map, return_counts=True)
    return {REGION_NAME[i]: int(c) for i, c in zip(ids, counts) if i in REGION_NAME}
