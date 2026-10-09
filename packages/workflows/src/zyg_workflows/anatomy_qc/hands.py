# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""anatomy_qc hand geometry scoring and the tiled hand detection sweep."""

from __future__ import annotations

import math
import os
import logging as _zyg_logging


from .constants import (
    BONE_TOL,
    CHIRAL_AMBIG,
    FINGERS,
    FUSE_FRAC,
    FUSE_REL,
    HAND_CONF,
    HAND_CONF_STRONG,
    KNUCKLE_SLACK,
    MIN_PALM_PX,
    NOISE_PALM_PX,
    OPEN_FRAC,
    REVERSE_DEG,
    REVERSE_DOT,
    STRICT_COUNT,
    TURN_MAX_DEG,
    WRIST,
    _BONE_REF,
    _KNUCKLES,
    _LOCK,
    _LONG_FINGERS,
    _TIPS,
    _envf,
    _log_noop,
)
from .runtime import (
    _angle_deg,
    _dist,
    _get_landmarker,
    _mp_image,
    _np,
    _read_bgr,
    _unit,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.anatomy_qc')


# ---------------------------------------------------------------------------
# hand geometry
# ---------------------------------------------------------------------------
def _hand_points(landmarks, w, h):
    """21x2 pixel-space array (aspect-correct; normalized coords are not)."""
    np = _np()
    return np.asarray([[lm.x * w, lm.y * h] for lm in landmarks], dtype=float)


def _hand_world(world_landmarks):
    np = _np()
    if not world_landmarks:
        return None
    return np.asarray([[lm.x, lm.y, lm.z] for lm in world_landmarks], dtype=float)


def _score_hand(pts, world, handed_label, handed_score, strong):
    """All geometry checks for ONE hand. Returns a per-hand dict.

    Every check is written to be silent on ordinary curled / foreshortened /
    partially-occluded hands (that is what sank the 2026-07-24 attempt) and to
    fire only on template deformation a real hand cannot produce.
    """
    np = _np()
    issues = []  # (tag, text, severity)
    palm = _dist(pts[WRIST], pts[9])
    if palm < 1e-6:
        return {
            'ok': None,
            'issues': [('hand-landmark-degenerate', 'zero-scale hand landmark hull', 'unknown')],
            'palm_px': 0.0,
        }
    # Resolution gate: below MIN_PALM_PX a phalanx spans a handful of pixels
    # and every ratio is landmark noise. Such hands are still REPORTED (a
    # 6 px palm in a 1664 px frame is itself a bogus detection) but can never
    # produce a hard verdict.
    scored = bool(strong and palm >= MIN_PALM_PX)
    hard = 'hard' if scored else 'advisory'

    # --- finger extension (gates the fused-finger test) --------------------
    extended, chain_len, spans = {}, {}, {}
    for name, idx in FINGERS.items():
        chain = sum(_dist(pts[idx[i]], pts[idx[i + 1]]) for i in range(3))
        span = _dist(pts[idx[0]], pts[idx[3]])
        chain_len[name] = chain
        spans[name] = span
        extended[name] = bool(chain > 1e-6 and span / chain >= OPEN_FRAC)

    # --- fingertip clustering: fused / merged fingers -----------------------
    tip_gap = FUSE_FRAC * palm
    clusters, seen = 0, [False] * 5
    tip_pts = [pts[t] for t in _TIPS]
    for i in range(5):  # single-linkage over 5 points
        if seen[i]:
            continue
        clusters += 1
        stack = [i]
        seen[i] = True
        while stack:
            k = stack.pop()
            for j in range(5):
                if not seen[j] and _dist(tip_pts[k], tip_pts[j]) < tip_gap:
                    seen[j] = True
                    stack.append(j)
    fused_pairs = []
    for a, b in (('index', 'middle'), ('middle', 'ring'), ('ring', 'pinky')):
        if not (extended[a] and extended[b]):
            continue
        d_tip = _dist(pts[FINGERS[a][3]], pts[FINGERS[b][3]])
        d_knu = _dist(pts[FINGERS[a][0]], pts[FINGERS[b][0]])
        if d_tip < tip_gap and (d_knu < 1e-6 or d_tip < FUSE_REL * d_knu):
            fused_pairs.append(f'{a}+{b}')
    n_ext = sum(1 for f in _LONG_FINGERS if extended[f])
    if fused_pairs:
        issues.append(
            ('fused-fingers', 'fingertips collapsed together while extended: ' + ', '.join(fused_pairs), hard)
        )
    elif n_ext >= 4 and clusters < 4:
        issues.append(
            ('fused-fingers', f'{n_ext} extended fingers resolve to only {clusters} fingertip cluster(s)', hard)
        )

    # --- joint chain monotonicity + hyperflexion (3D when available) -------
    src = world if world is not None else None
    reversed_joints, hyper_joints = [], []
    for name, idx in FINGERS.items():
        if src is not None:
            p = [src[i] for i in idx]
        else:
            p = [np.append(pts[i], 0.0) for i in idx]
        v1, v2, v3 = p[1] - p[0], p[2] - p[1], p[3] - p[2]
        a1, a2 = _angle_deg(v1, v2), _angle_deg(v2, v3)
        if max(a1, a2) > TURN_MAX_DEG:
            hyper_joints.append(f'{name}({max(a1, a2):.0f}deg)')
        if min(a1, a2) > REVERSE_DEG:
            # Bend AXES, not 2D turn signs: a projected sign flip is routine
            # under foreshortening, but two consecutive joints of one finger
            # rotating about opposed axes in 3D is not a pose, it is a defect.
            n1, n2 = np.cross(v1, v2), np.cross(v2, v3)
            if float(np.dot(_unit(n1), _unit(n2))) < REVERSE_DOT:
                reversed_joints.append(f'{name}({a1:.0f}/{a2:.0f}deg)')
    if reversed_joints:
        issues.append(
            ('nonmonotonic-joint', 'finger bends reverse direction mid-chain: ' + ', '.join(reversed_joints), hard)
        )
    if hyper_joints:
        issues.append(('hyperflexed-joint', 'joint turn beyond human range: ' + ', '.join(hyper_joints), hard))

    # --- bone-length ratio sanity (3D world coords; gross violations only) --
    bone_flags, bone_ratios = [], {}
    for name, idx in FINGERS.items():
        if src is not None:
            l1 = float(np.linalg.norm(src[idx[1]] - src[idx[0]]))
            l2 = float(np.linalg.norm(src[idx[2]] - src[idx[1]]))
            l3 = float(np.linalg.norm(src[idx[3]] - src[idx[2]]))
        else:
            l1 = _dist(pts[idx[0]], pts[idx[1]])
            l2 = _dist(pts[idx[1]], pts[idx[2]])
            l3 = _dist(pts[idx[2]], pts[idx[3]])
        if min(l1, l2, l3) < 1e-6:
            bone_flags.append(f'{name}(zero-length phalanx)')
            continue
        r1, r2 = l2 / l1, l3 / l2
        bone_ratios[name] = (round(r1, 3), round(r2, 3))
        m1, m2 = _BONE_REF[name]
        if not (m1 / BONE_TOL <= r1 <= m1 * BONE_TOL):
            bone_flags.append(f'{name} mid/prox={r1:.2f} (ref {m1:.2f})')
        if not (m2 / BONE_TOL <= r2 <= m2 * BONE_TOL):
            bone_flags.append(f'{name} dist/mid={r2:.2f} (ref {m2:.2f})')
    if bone_flags:
        issues.append(
            (
                'bone-ratio-implausible',
                'phalanx proportions outside the landmarker envelope: ' + ', '.join(bone_flags),
                hard,
            )
        )

    # --- gross finger-length ordering --------------------------------------
    lm = chain_len['middle']
    if lm > 1e-6:
        if chain_len['pinky'] > lm * 1.05:
            issues.append(('finger-length-order', f'pinky longer than middle ({chain_len["pinky"] / lm:.2f}x)', hard))
        elif lm < 0.90 * max(chain_len['index'], chain_len['ring']):
            issues.append(('finger-length-order', 'middle finger shorter than index/ring', 'advisory'))

    # --- knuckle ordering (independent of the handedness classifier) -------
    axis = pts[_KNUCKLES[-1]] - pts[_KNUCKLES[0]]
    axis_n = float(np.linalg.norm(axis))
    knuckle_ok = True
    if axis_n > 0.25 * palm:
        axis = axis / axis_n
        proj = [float(np.dot(pts[k] - pts[_KNUCKLES[0]], axis)) / axis_n for k in _KNUCKLES]
        for i in range(3):
            if proj[i + 1] < proj[i] - KNUCKLE_SLACK:
                knuckle_ok = False
        if not knuckle_ok:
            issues.append(
                ('knuckle-order', f'MCP knuckles out of index->pinky order ({[round(p, 2) for p in proj]})', hard)
            )

    # --- chirality --------------------------------------------------------
    # Deliberately NOT compared against a geometric left/right sign: the
    # model's handedness IS derived from that geometry, so the test would be
    # circular. What is not circular is the classifier's own certainty — a
    # hand it cannot assign to a side is a hand whose thumb/palm topology is
    # inconsistent, which is exactly the AI defect we are hunting.
    if handed_score is not None and handed_score < CHIRAL_AMBIG:
        issues.append(
            (
                'chirality-ambiguous',
                f'handedness undecidable ({handed_label}={handed_score:.2f} < {CHIRAL_AMBIG:.2f})',
                hard,
            )
        )

    if not strong:
        issues.append(
            (
                'low-confidence-hand',
                'hand found only by the permissive pass — geometry is advisory (stylized/painterly art)',
                'unknown',
            )
        )
    if palm < MIN_PALM_PX:
        issues.append(
            (
                'hand-too-small-to-score',
                f'palm spans {palm:.0f}px (< {MIN_PALM_PX:.0f}px): phalanx '
                f'geometry is landmark noise at this scale — advisory only',
                'unknown',
            )
        )

    sev = {s for _, _, s in issues}
    ok = False if 'hard' in sev else (None if sev else True)
    return {
        'ok': ok,
        'issues': issues,
        'scored': scored,
        'handedness': handed_label,
        'handedness_score': (None if handed_score is None else round(float(handed_score), 3)),
        'strong': bool(strong),
        'palm_px': round(palm, 1),
        'extended_fingers': n_ext,
        'fingertip_clusters': clusters,
        'bone_ratios': bone_ratios,
        'knuckle_order_ok': knuckle_ok,
    }


def _hand_box(pts, w, h, pad=None):
    if pad is None:
        pad = _envf('ZYG_HANDS_MP_BOX_PAD', 0.10)
    xs, ys = pts[:, 0], pts[:, 1]
    x1, x2 = float(xs.min()), float(xs.max())
    y1, y2 = float(ys.min()), float(ys.max())
    mx, my = (x2 - x1) * pad, (y2 - y1) * pad
    return (max(0.0, x1 - mx), max(0.0, y1 - my), min(float(w), x2 + mx), min(float(h), y2 + my))


def _detect_hands(bgr, conf):
    lmk = _get_landmarker('hand', conf)
    with _LOCK:  # task objects are not documented reentrant
        return lmk.detect(_mp_image(bgr))


# ---------------------------------------------------------------------------
# tiled detection
# ---------------------------------------------------------------------------
# MediaPipe's palm and face detectors run on a small square input (192-256 px),
# so a subject occupying a modest fraction of a 1664x960 render is below their
# operating range: scene20_v7 beat_1.0.png returns ZERO faces whole-frame even
# at confidence 0.01, yet returns Cornelis's face immediately from a head-sized
# crop. Tiling recovers that recall. It escalates only while the frame is still
# short of `want`, so ordinary close-up content stays at one pass.
def _tile_boxes(w, h, grid, overlap=0.30):
    np = _np()
    tw, th = int(w / grid * (1 + overlap)), int(h / grid * (1 + overlap))
    tw, th = max(64, min(w, tw)), max(64, min(h, th))
    xs = np.linspace(0, max(0, w - tw), grid).astype(int)
    ys = np.linspace(0, max(0, h - th), grid).astype(int)
    seen, out = set(), []
    for y in ys:
        for x in xs:
            box = (int(x), int(y), min(w, int(x) + tw), min(h, int(y) + th))
            if box not in seen:
                seen.add(box)
                out.append(box)
    return out


def _tile_grids(w=None, h=None):
    # Tiling a region that is already subject-sized only manufactures
    # duplicates: a 233x201 hand crop went from 65 to 151 boxes when tiled.
    if w is not None and h is not None:
        if min(w, h) < _envf('ZYG_MP_TILE_MIN_PX', 400.0):
            return []
    raw = os.environ.get('ZYG_MP_TILE_GRIDS', '2,3')
    if raw.strip() in ('', '0', 'off'):
        return []
    grids = []
    for tok in raw.split(','):
        try:
            g = int(tok.strip())
        except ValueError as _exc:
            _zyg_log.warning('ignoring non-integer ZYG_MP_TILE_GRIDS entry %r: %s', tok, _exc)
            continue
        if g >= 2:
            grids.append(g)
    return grids


def _dedupe(cands, key='pts'):
    """Greedy NMS on landmark hulls: keep the biggest, drop anything whose
    centroid sits within half the kept hull's width."""
    scored = []
    for c in cands:
        p = c[key]
        wdt = float(p[:, 0].max() - p[:, 0].min())
        hgt = float(p[:, 1].max() - p[:, 1].min())
        scored.append((max(wdt, hgt), float(p[:, 0].mean()), float(p[:, 1].mean()), c))
    scored.sort(key=lambda t: -t[0])
    kept = []
    for size, cx, cy, c in scored:
        if all(math.hypot(cx - kx, cy - ky) > 0.5 * max(size, ks) for ks, kx, ky in kept):
            kept.append((size, cx, cy))
            yield c


def _hand_candidates(bgr, conf, want=None, only_boxes=None):
    """[{'pts','world','label','score','tile'}] in FULL-FRAME pixels.

    ``only_boxes`` restricts the sweep to given regions — used for the strict
    confirmation pass so it re-examines exactly the crops the permissive pass
    fired on (identical input region, higher threshold) instead of paying for
    the whole tile sweep a second time.
    """
    np = _np()
    h, w = bgr.shape[:2]

    def _harvest(box):
        x1, y1, x2, y2 = box
        sub = bgr[y1:y2, x1:x2]
        if sub.size == 0:
            return []
        res = _detect_hands(sub, conf)
        sh, sw = sub.shape[:2]
        worlds = getattr(res, 'hand_world_landmarks', None) or []
        handed = getattr(res, 'handedness', None) or []
        out = []
        for i, lms in enumerate(res.hand_landmarks or []):
            pts = _hand_points(lms, sw, sh) + np.asarray([x1, y1], dtype=float)
            label = score = None
            if i < len(handed) and handed[i]:
                label = getattr(handed[i][0], 'category_name', None)
                score = getattr(handed[i][0], 'score', None)
            out.append(
                {
                    'pts': pts,
                    'world': _hand_world(worlds[i]) if i < len(worlds) else None,
                    'label': label,
                    'score': score,
                    'tile': box,
                }
            )
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
    # Tiling buys recall at the cost of speck detections (a 6 px "palm" in a
    # 1664 px frame). Those are detector noise, not hands: dropping them here
    # keeps them out of the count check instead of manufacturing a mismatch.
    cands = [c for c in cands if _dist(c['pts'][WRIST], c['pts'][9]) >= NOISE_PALM_PX]
    return list(_dedupe(cands))


def _hands_from_array(bgr, expected_hands=None):
    """Core per-frame hand QC on a decoded BGR array. RAISES on tool failure;
    the public wrappers convert that into {'ok': None, 'error': ...}."""
    h, w = bgr.shape[:2]
    # want=1 when the caller does not know the count: without a target the
    # tile sweep never runs and recall collapses to the whole-frame pass.
    want = int(expected_hands) if expected_hands else 1
    cands = _hand_candidates(bgr, HAND_CONF, want)
    if HAND_CONF_STRONG > HAND_CONF and cands:
        boxes = list(dict.fromkeys(c['tile'] for c in cands))
        strict_c = _hand_candidates(bgr, HAND_CONF_STRONG, only_boxes=boxes)
    else:
        strict_c = cands
    strict_wrists = [c['pts'][WRIST] for c in strict_c]
    match_tol = 0.05 * math.hypot(w, h)

    hands, issues = [], []
    for i, c in enumerate(cands):
        pts = c['pts']
        strong = any(_dist(pts[WRIST], sw) <= match_tol for sw in strict_wrists)
        info = _score_hand(pts, c['world'], c['label'], c['score'], strong)
        info['box'] = tuple(round(v, 1) for v in _hand_box(pts, w, h))
        info['index'] = i
        hands.append(info)
        for tag, text, sev in info['issues']:
            issues.append({'tag': tag, 'hand': i, 'severity': sev, 'text': text})

    n = len(hands)
    n_strong = sum(1 for x in hands if x['strong'])
    if expected_hands is not None:
        exp = int(expected_hands)
        if n == 0 and exp > 0:
            issues.append(
                {
                    'tag': 'no-hands-detected',
                    'hand': None,
                    'severity': 'unknown',
                    'text': f'expected {exp} hand(s), detected 0 — '
                    f'UNKNOWN, not clean (photoreal detector on '
                    f'possibly stylized art)',
                }
            )
        elif n > exp:
            issues.append(
                {
                    'tag': 'hand-count-mismatch',
                    'hand': None,
                    'severity': 'hard' if n_strong > exp else 'advisory',
                    'text': f'detected {n} hand(s) ({n_strong} strong) > expected {exp}',
                }
            )
        elif n < exp:
            issues.append(
                {
                    'tag': 'hand-count-mismatch',
                    'hand': None,
                    'severity': 'hard' if STRICT_COUNT else 'advisory',
                    'text': f'detected {n} hand(s) < expected {exp} (detector recall, not necessarily a defect)',
                }
            )

    sev = {i['severity'] for i in issues}
    ok = False if 'hard' in sev else (None if ('unknown' in sev or n == 0) else True)
    return {
        'ok': ok,
        'hands': hands,
        'issues': issues,
        'detected': n,
        'strong': n_strong,
        'expected_hands': expected_hands,
        'error': None,
    }


def qc_hands_frame(image_path: str, expected_hands=None, log_fn=None) -> dict:
    """Hand anatomy gate for ONE still. Never raises.

    Returns {'ok', 'hands':[...], 'issues':[...], 'detected', 'error'}.
    'ok' is None when the verdict is UNKNOWN (tool unavailable, nothing
    detected, permissive-only detections) — callers must never read None as
    clean; that exact bug shipped 12 defective frames in run 6278904c.
    """
    log = log_fn or _log_noop
    try:
        out = _hands_from_array(_read_bgr(image_path), expected_hands)
        out['image'] = image_path
    except Exception as exc:
        log(f'anatomy_qc: hand gate unavailable for {os.path.basename(image_path)} ({type(exc).__name__}: {exc})')
        return {
            'ok': None,
            'hands': [],
            'issues': [
                {
                    'tag': 'hand-gate-unavailable',
                    'hand': None,
                    'severity': 'unknown',
                    'text': f'{type(exc).__name__}: {exc}',
                }
            ],
            'detected': 0,
            'strong': 0,
            'expected_hands': expected_hands,
            'image': image_path,
            'error': f'{type(exc).__name__}: {exc}',
        }
    if out['issues']:
        log(
            f'anatomy_qc: hands {os.path.basename(image_path)} ok={out["ok"]} '
            f'detected={out["detected"]} :: ' + '; '.join(f'{i["tag"]}[{i["severity"]}]' for i in out['issues'])
        )
    return out
