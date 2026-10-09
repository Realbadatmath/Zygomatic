# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""WHO IS ALIVE IN THE SHOT (2026-08-01): the measured calibration block for the
character-balance / beat / regression gates, the per-pixel statistics, box
geometry helpers and the MTCNN face locator the pixel-side gate measures with."""

import os


# ═══════════════════════════════════════════════════════════════════════════════
# 2026-08-01 — WHO IS ALIVE IN THE SHOT (the "lifeless Abel" batch)
# ═══════════════════════════════════════════════════════════════════════════════
# The gates above ask "does this REGION move, and does it move well". Scene 20 failed a
# question none of them ask: BOTH characters moved, both passed every region gate, and the
# shot still read wrong because ONE character carried it and the other sat there. v11's own
# report is the proof — every region PASS (a_hand 0.53, a_head 0.18, c_hands 0.29, pipe 0.46
# against a 0.12 floor), verdict green, and the operator's verdict was "Abel is lifeless".
#
# Three gates close that hole:
#   qc_character_balance  — the pixel side: per character face/hand flow, reversals and
#                           coherence, plus the CROSS-CHARACTER face ratio.
#   qc_beat_prominence    — the prompt side: who is the SENTENCE SUBJECT of each beat. Runs
#                           in milliseconds on text, before the 90-minute render.
#   qc_regression_vs      — the diff: same regions, new clip vs a named baseline, signed.
#
# ── MEASURED, 2026-08-01, on the three finished 1664x960 24fps deliverables ────────────
# Statistic: per-pixel Farneback flow magnitude at sample_every=4 — the SAME number
# qc_region_flow calls flow_mean. Cross-checked against the run record before any threshold
# was chosen, and it reproduces exactly: v11 a_head 0.250 (recorded 0.25), v11 candle 0.179
# and v12 candle 0.305 (recorded 0.179 / 0.305), v11/v12 a_hand reversals 6.91 / 6.55 at
# step=2 (recorded 6.91 / 6.55). Face boxes from MTCNN medians over 21 sampled frames,
# grown 0.02 on every side.
#
#   clip   CORNELIS face        ABEL face          face ratio (max/min)
#          median   mean        median   mean      median      mean
#   v6     0.196    0.237       0.306    1.123     1.56 (Abel) 4.74 (Abel)
#   v11    0.392    1.126       0.175    0.214     2.24 (Corn) 5.27 (Corn)
#   v12    0.403    0.422       0.188    0.236     2.15 (Corn) 1.78 (Corn)
#   frozen 0.0004   0.0008      0.0008   0.0010    — one v11 frame looped 20s, the noise floor
#
# WHY THE MEDIAN AND NOT THE MEAN. The mean is burst-dominated and its ranking is WRONG.
# v6's Abel: mean 1.123, median 0.306, p90 4.49, max 8.82, and 33% of samples above twice
# the median — one head-turn. On the mean v6 measures MORE asymmetric than v11 (4.74 vs
# 5.27) AND the leader flips, so a mean-based ratio cap that fails v11 also fails the clip
# the operator likes. The median asks "what does this face do MOST OF THE TIME", which is
# what "lifeless" means: not that Abel never moves, but that his resting state is dead.
# The mean is still reported, because it carries the OTHER signal — v12's global graded pin
# collapsed Cornelis's mean 1.126 -> 0.422 (-63%, the operator's "doesn't move at all")
# while his MEDIAN went UP 0.392 -> 0.403. Two different failures, two different statistics.
# qc_regression_vs is the gate that catches the mean collapse; do not conflate them.
#
# _CHARBAL_FACE_RATIO_MAX = 1.85. Geometric mid-gap of the WORST v6 (1.68) and the WORST
# v11 (2.00) across the whole supported box envelope below is 1.83; 1.85 rounds it. At the
# recommended tightness — the boxes locate_character_faces() actually returns — the verified
# end-to-end numbers are v6 1.68 PASS (10% headroom), v11 2.24 FAIL (21% over), v12 2.18
# FAIL (18% over). HONEST WARNING: that is a THINNER gate than the 4.5/s reversal gate, it
# is calibrated on THREE clips, and it is a ratio of medians, so it will not survive a
# composition change without re-measurement. Treat a marginal 1.7-2.0 as "go and look at
# it", not as a verdict, and never as grounds to re-render on its own.
#
# _CHARBAL_FACE_FLOW_MIN = 0.12 is the house _REGION_FLOW_MIN and it is a FREEZE BACKSTOP,
# NOT the asymmetry detector. Say that out loud, because the numbers tempt you: the quietest
# face in the clip the operator LIKED (v6 Cornelis, 0.196) and the "lifeless" one (v11 Abel,
# 0.175) are 12% apart. No floor can separate those without false-failing v6. Abel is not
# frozen — a frozen face measures 0.0008 — he is SUBORDINATE, and only the ratio sees that.
#
# ── THE BOX IS THE MEASUREMENT. Pad sweep (same MTCNN box grown by m on every side) ───────
#   m      v6 R    v11 R   v12 R   box area (frac of frame)   verdict at 1.80
#   0.00   1.65    2.23    2.25    0.031-0.035                separates  <- recommended
#   0.02   1.56    2.24    2.15    0.047-0.052                separates
#   0.05   1.54    2.13    1.85    0.078-0.085                separates
#   0.08   1.23    2.00    1.62    0.116-0.124                separates, thin (5% margin)
#   0.12   1.20    1.45    1.48    0.178-0.188                BLIND (v11 passes)
#   0.18   1.41    1.24    1.42    0.277-0.299                INVERTED (v6 > v11)
# (pad 0.00 re-measured end-to-end through locate_character_faces' own 8-frame boxes reads
#  v6 1.68 / v11 2.24 / v12 2.18 — box jitter between an 8- and a 21-frame median moves the
#  ratio by a couple of percent, which is the noise this cap has to sit outside of.)
# And with v11's OWN production face boxes (a_face 0.68,0.04,0.90,0.40 / c_face
# 0.10,0.08,0.32,0.44, recorded in that run's debug/report.json) the ratio compresses to
# v6 1.54 / v11 1.69 — under the cap, gate BLIND. Those boxes are 7.9% of frame each, which
# the area rule alone would wave through: they are the right SIZE but the wrong PLACE (they
# sit high, over hat and wall, and only ~33% of each box is actually face). That is why
# verify_boxes runs a detector and reports face_fill, and why a bad box raises a SEPARATE
# 'box_quality' check tagged qc-broken instead of quietly passing the shot: a gate that
# passes because it read the wall is the exact failure this whole file exists to stop.
# locate_character_faces() below returns boxes at face_fill ~0.65 in about a second.
_CHARBAL_FLOW_STEP = 4  # sample interval for the FLOW statistic (qc_region_flow's)
_CHARBAL_DIR_STEP = 2  # sample interval for reversals/coherence (the jitter gate's)
_CHARBAL_FACE_FLOW_MIN = 0.12  # freeze backstop only — see the block above
_CHARBAL_FACE_RATIO_MAX = 1.85  # median face flow, max/min across characters
_CHARBAL_FACE_FILL_MIN = 0.40  # measured: 0.394 still separates, 0.332 (prod boxes) does not
_CHARBAL_BOX_AREA_MAX = 0.12  # measured: 0.124 still separates, 0.178 goes blind
_CHARBAL_VERIFY_FRAMES = 8  # MTCNN frames for box verification (~0.7s at full res)
_BEAT_EVEN_SHARE_FRAC = 0.8  # a character must lead >= 80% of an even split of the beats
_REGRESSION_TOLERANCE = 0.15  # relative move that counts as "something changed"
_REGRESSION_FLOOR = 0.02  # both readings under this are noise; ratio not reported


def _perpix_stats(series):
    """Per-pixel flow series -> median/mean/p90/max/burst_frac (None if too short)."""
    import numpy as np

    a = np.asarray(series or [], dtype='float64')
    if a.size < 2:
        return None
    med = float(np.median(a))
    return {
        'flow_median': med,
        'flow_mean': float(a.mean()),
        'flow_p90': float(np.percentile(a, 90)),
        'flow_max': float(a.max()),
        # burst_frac is the evidence for "the mean is one gesture": v6's Abel face
        # reads 0.33 here, v11's Abel 0.08.
        'burst_frac': float((a > 2.0 * med).mean()) if med > 1e-9 else 0.0,
        'n_samples': int(a.size),
    }


def _box_area(b):
    return max(0.0, float(b[2]) - float(b[0])) * max(0.0, float(b[3]) - float(b[1]))


def _box_inter(a, b):
    x0, y0 = max(float(a[0]), float(b[0])), max(float(a[1]), float(b[1]))
    x1, y1 = min(float(a[2]), float(b[2])), min(float(a[3]), float(b[3]))
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _valid_box(b):
    try:
        b = tuple(float(v) for v in b)
    except Exception:
        return None
    return b if len(b) == 4 and b[2] > b[0] and b[3] > b[1] else None


def locate_character_faces(clip_path, expect=2, sample=None, min_conf=0.90, log_fn=None):
    """MTCNN face boxes for a multi-character clip, sorted LEFT to RIGHT (2026-08-01).

    Exists because the character-balance gate is only as good as its face boxes and the
    hand-set production ones were measured to be wrong enough to blind it (see the block
    above). Detection runs on CPU by default — ~0.7s for 8 full-res frames, i.e. free next
    to the ~35s optical-flow pass — and never touches the GPU the renderer is using.
    Override with ZYG_CHARBAL_FACE_DEVICE=cuda if you know the GPU is idle.

    Grouping is by x-centre: every detection above min_conf from every sampled frame is
    pooled, sorted by centre, and split at the `expect-1` LARGEST gaps. That is robust for
    characters who stay on their own side of the frame (this shot) and WRONG for characters
    who cross horizontally — check n_detections and the reported x-spread before trusting it.

    facenet-pytorch is MIT; no AGPL/NC detector is used here.

    Returns {'ok', 'faces': [{'box': (fx0,fy0,fx1,fy1), 'side', 'n_detections', 'conf',
    'x_spread'}], 'frames_sampled', 'error'}. Fail-safe: {'ok': False, 'faces': []} when the
    detector is unavailable — callers must then supply boxes themselves."""
    log = log_fn or (lambda _m: None)
    out = {'ok': False, 'faces': [], 'frames_sampled': 0, 'error': None}
    try:
        import cv2
        import numpy as np

        try:
            from facenet_pytorch import MTCNN
        except Exception as e:
            out['error'] = f'facenet_pytorch unavailable ({e}) — supply face boxes manually'
            log(f'[locate_character_faces] {out["error"]}')
            return out
        dev = os.environ.get('ZYG_CHARBAL_FACE_DEVICE', 'cpu')
        det = MTCNN(keep_all=True, device=dev, min_face_size=40)
        cap = cv2.VideoCapture(clip_path)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        k = int(sample or _CHARBAL_VERIFY_FRAMES)
        if n < 2 or W < 2 or H < 2:
            cap.release()
            out['error'] = f'clip unreadable ({n} frames, {W}x{H})'
            log(f'[locate_character_faces] {out["error"]}')
            return out
        pool = []
        for i in range(k):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * (i + 0.5) / k))
            ok, fr = cap.read()
            if not ok:
                continue
            out['frames_sampled'] += 1
            boxes, probs = det.detect(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))
            if boxes is None:
                continue
            for b, p in zip(boxes, probs):
                if p is None or float(p) < float(min_conf):
                    continue
                pool.append((float((b[0] + b[2]) / 2 / W), float(p), (b[0] / W, b[1] / H, b[2] / W, b[3] / H)))
        cap.release()
        if not pool:
            out['error'] = 'no faces detected above the confidence floor'
            log(f'[locate_character_faces] {out["error"]}')
            return out
        pool.sort(key=lambda t: t[0])
        want = max(1, int(expect or 1))
        gaps = sorted(range(1, len(pool)), key=lambda i: pool[i][0] - pool[i - 1][0], reverse=True)
        cuts = sorted(gaps[: max(0, want - 1)])
        groups, start = [], 0
        for c in cuts + [len(pool)]:
            if c > start:
                groups.append(pool[start:c])
            start = c
        for gi, g in enumerate(groups):
            arr = np.asarray([t[2] for t in g], dtype='float64')
            med = np.median(arr, axis=0)
            out['faces'].append(
                {
                    'box': tuple(round(float(v), 4) for v in med),
                    'side': ('left' if gi == 0 else 'right' if gi == len(groups) - 1 else f'mid{gi}'),
                    'n_detections': len(g),
                    'conf': round(float(np.mean([t[1] for t in g])), 3),
                    'x_spread': round(float(g[-1][0] - g[0][0]), 4),
                }
            )
        out['ok'] = True
        for f in out['faces']:
            log(
                f'[locate_character_faces] {f["side"]}: box {f["box"]} '
                f'({f["n_detections"]} detections, conf {f["conf"]}, '
                f'x-spread {f["x_spread"]})'
            )
    except Exception as e:
        out['error'] = str(e)[:200]
        log(f'[locate_character_faces] ERROR: {e}')
    return out


def _charbal_normalize(characters):
    """{'name': {'face': box, 'hands': box}} in, normalized dict + complaints out.
    Also accepts {'name': box} (box = face) and 'head'/'hand' as key spellings."""
    norm, bad = {}, []
    for name, spec in (characters or {}).items():
        rec = {'face': None, 'hands': None}
        if isinstance(spec, dict):
            for key, dest in (('face', 'face'), ('head', 'face'), ('hands', 'hands'), ('hand', 'hands')):
                if spec.get(key) is not None and rec[dest] is None:
                    b = _valid_box(spec.get(key))
                    if b is None:
                        bad.append(f'{name}.{key} is not a valid (fx0,fy0,fx1,fy1) box')
                    else:
                        rec[dest] = b
        else:
            b = _valid_box(spec)
            if b is None:
                bad.append(f'{name} is neither a box nor a dict of boxes')
            else:
                rec['face'] = b
        if rec['face'] is None and rec['hands'] is None:
            bad.append(f'{name} has no usable box — skipped')
            continue
        norm[str(name)] = rec
    return norm, bad


def _detector_face_boxes_for(clip_path, characters, log_fn=None):
    """Rebuild `characters` with face boxes from locate_character_faces, keeping each
    character's supplied hands box. Returns None if detection cannot be matched.

    Matching is by x-centre order: the detector returns faces sorted left-to-right, and
    the supplied boxes are ordered the same way, so the Nth detection belongs to the Nth
    character. That is the only assumption, and it is the same one the 'side' field encodes.
    """
    log = log_fn or (lambda _m: None)
    try:
        det = locate_character_faces(clip_path, expect=len(characters), log_fn=log)
    except Exception as e:
        log(f'[qc_character_balance] auto-boxes: detector failed ({e})')
        return None
    faces = (det or {}).get('faces') if isinstance(det, dict) else det
    if not faces or len(faces) < len(characters):
        log(
            '[qc_character_balance] auto-boxes: detector found '
            f'{len(faces or [])} face(s) for {len(characters)} character(s) — not applied'
        )
        return None

    def _cx(b):
        return (float(b[0]) + float(b[2])) / 2.0

    named = [(k, v) for k, v in characters.items() if isinstance(v, dict) and _valid_box(v.get('face'))]
    if len(named) != len(characters):
        return None
    named.sort(key=lambda kv: _cx(kv[1]['face']))
    dets = sorted(faces, key=lambda f: _cx(f['box']))[: len(named)]
    out = {}
    for (k, v), d in zip(named, dets):
        nv = dict(v)
        nv['face'] = tuple(float(x) for x in d['box'])
        out[k] = nv
        log(
            f'[qc_character_balance] auto-boxes: {k}.face '
            f'{tuple(round(float(x), 3) for x in v["face"])} -> '
            f'{tuple(round(float(x), 3) for x in d["box"])}'
        )
    return out
