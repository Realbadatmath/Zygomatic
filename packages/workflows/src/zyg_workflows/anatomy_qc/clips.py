# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""anatomy_qc clip-level hand and face aggregation over sampled frames."""

from __future__ import annotations

import math
import logging as _zyg_logging


from .constants import (
    CHIRAL_SURE,
    CHIRAL_TRACK_FRAC,
    DETECT_RATE_FLOOR,
    FACE_TRACK_FRAC,
    JITTER_FLOOR,
    JITTER_MAX,
    JITTER_Z,
    MELT_RUN,
    NOISE_FACE_PX,
    RATIO_Z,
    YAW_FRONTAL,
    _envi,
    _log_noop,
)
from .runtime import (
    _ledger_gate,
    _np,
    _robust_z,
)
from .hands import (
    _hands_from_array,
)
from .faces import (
    _faces_from_array,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.anatomy_qc')


# ---------------------------------------------------------------------------
# clip sampling + aggregation
# ---------------------------------------------------------------------------
def _iter_frames(clip_path, sample_every, max_frames):
    """Yield (frame_index, bgr). Uses grab() to skip cheaply."""
    import cv2

    cap = cv2.VideoCapture(clip_path)
    if not cap.isOpened():
        raise OSError(f'cannot open clip: {clip_path}')
    try:
        step = max(1, int(sample_every))
        idx, taken = 0, 0
        while taken < max_frames:
            ok = cap.grab()
            if not ok:
                break
            if idx % step == 0:
                ok, frame = cap.retrieve()
                if not ok or frame is None:
                    break
                taken += 1
                yield idx, frame
            idx += 1
    finally:
        cap.release()


def _clip_fps(clip_path):
    import cv2

    cap = cv2.VideoCapture(clip_path)
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    finally:
        cap.release()
    return fps if fps > 1e-3 else 0.0


def qc_hands_clip(clip_path: str, n_people: int, sample_every: int = 8, log_fn=None, run_id=None) -> dict:
    """Sampled hand gate across a clip. Never raises.

    n_people -> expected_hands = 2 * n_people (the usual seated-dialogue case;
    pass n_people=0 to disable the count check entirely).
    Adds two clip-only signals: chirality flips on a positionally tracked hand,
    and the detection rate (a collapse is itself a finding).
    """
    log = log_fn or _log_noop
    expected = (2 * int(n_people)) if n_people else None
    max_frames = _envi('ZYG_MP_CLIP_MAX_FRAMES', 240)
    out = {
        'ok': None,
        'clip': clip_path,
        'expected_hands': expected,
        'frames_sampled': 0,
        'frames_with_hands': 0,
        'detect_rate': None,
        'issue_counts': {},
        'issues': [],
        'per_frame': [],
        'chirality_flips': 0,
        'error': None,
    }
    try:
        np = _np()
        fps = _clip_fps(clip_path)
        prev = []  # [(wrist_xy, label, score)]
        flips = 0
        for idx, frame in _iter_frames(clip_path, sample_every, max_frames):
            r = _hands_from_array(frame, expected)
            out['frames_sampled'] += 1
            if r['detected']:
                out['frames_with_hands'] += 1
            # Chirality flip on a POSITIONALLY TRACKED hand. Association is
            # scale-relative (a hand only matches a previous hand within a
            # fraction of its own size, not a fixed slice of the frame) and
            # a flip is only claimed when BOTH endpoints are strong detections
            # the classifier was sure about — otherwise sampled-motion
            # association across 0.5 s manufactures flips between two people's
            # hands, which is what a frame-diagonal tolerance did here (7 spurious
            # flips on scene20_v7 pasted17.mp4).
            cur = []
            for hnd in r['hands']:
                x1, y1, x2, y2 = hnd['box']
                cur.append(
                    (
                        np.asarray([(x1 + x2) / 2.0, (y1 + y2) / 2.0]),
                        hnd.get('handedness'),
                        hnd.get('handedness_score'),
                        bool(hnd.get('strong')),
                        math.hypot(x2 - x1, y2 - y1),
                    )
                )
            for c_xy, c_lab, c_sc, c_strong, c_sz in cur:
                best, bd = None, None
                for p_xy, p_lab, p_sc, p_strong, p_sz in prev:
                    tol = CHIRAL_TRACK_FRAC * max(c_sz, p_sz)
                    d = float(np.linalg.norm(c_xy - p_xy))
                    if d <= tol and (bd is None or d < bd):
                        bd, best = d, (p_lab, p_sc, p_strong)
                if not (best and c_lab and best[0] and c_lab != best[0]):
                    continue
                if not (c_strong and best[2]):
                    continue
                if (c_sc or 0) >= CHIRAL_SURE and (best[1] or 0) >= CHIRAL_SURE:
                    flips += 1
                    out['issues'].append(
                        {
                            'tag': 'chirality-flip',
                            'frame': idx,
                            'severity': 'hard',
                            'text': f'tracked hand flipped {best[0]}({best[1]:.2f})'
                            f'->{c_lab}({c_sc:.2f}) at frame {idx}',
                        }
                    )
            prev = cur
            for i in r['issues']:
                rec = dict(i)
                rec['frame'] = idx
                out['issues'].append(rec)
            out['per_frame'].append(
                {
                    'frame': idx,
                    't_s': round(idx / fps, 3) if fps else None,
                    'ok': r['ok'],
                    'detected': r['detected'],
                    'strong': r['strong'],
                    'tags': sorted({i['tag'] for i in r['issues']}),
                }
            )
        out['chirality_flips'] = flips
        if out['frames_sampled']:
            out['detect_rate'] = round(out['frames_with_hands'] / out['frames_sampled'], 4)
        counts = {}
        for i in out['issues']:
            counts[i['tag']] = counts.get(i['tag'], 0) + 1
        out['issue_counts'] = counts
        sev = {i['severity'] for i in out['issues']}
        if 'hard' in sev:
            out['ok'] = False
        elif out['frames_sampled'] == 0:
            out['ok'] = None
        elif expected and (out['detect_rate'] or 0.0) < DETECT_RATE_FLOOR:
            out['ok'] = None
            out['issues'].append(
                {
                    'tag': 'hand-detect-rate-low',
                    'frame': None,
                    'severity': 'unknown',
                    'text': f'hands found in only {out["detect_rate"]:.0%} of sampled '
                    f'frames — UNKNOWN (stylized art or a real dropout)',
                }
            )
        else:
            out['ok'] = None if 'unknown' in sev else True
    except Exception as exc:
        out['error'] = f'{type(exc).__name__}: {exc}'
        out['ok'] = None
        log(f'anatomy_qc: hand clip gate unavailable ({out["error"]})')
    _ledger_gate(
        'anatomy.hands.clip',
        out['ok'],
        score=out['detect_rate'],
        tag=','.join(sorted(out['issue_counts'])[:6]),
        run_id=run_id,
    )
    log(
        f'anatomy_qc: hands clip ok={out["ok"]} sampled={out["frames_sampled"]} '
        f'detect_rate={out["detect_rate"]} flips={out["chirality_flips"]} '
        f'tags={out["issue_counts"]}'
    )
    return out


def qc_face_clip(clip_path: str, n_people: int, sample_every: int = 8, log_fn=None, run_id=None) -> dict:
    """Sampled face gate across a clip. Never raises.

    Clip-only signals (the ones that actually catch melt):
      * detection-rate collapse + longest consecutive-loss run  -> melt event
      * MAD z-score drift of inter-ocular / mouth / eye-mouth ratios
      * ECC-compensated landmark jitter: a global euclidean warp between
        consecutive sampled frames is estimated on downscaled greyscale, the
        previous landmarks are warped by it, and the residual displacement
        (normalized by inter-ocular distance) is what remains after camera and
        subject translation are removed.
    """
    log = log_fn or _log_noop
    expected = int(n_people) if n_people else None
    max_frames = _envi('ZYG_MP_CLIP_MAX_FRAMES', 240)
    out = {
        'ok': None,
        'clip': clip_path,
        'expected_faces': expected,
        'frames_sampled': 0,
        'frames_with_faces': 0,
        'detect_rate': None,
        'melt_runs': [],
        'jitter_median': None,
        'jitter_p95': None,
        'ratio_drift': {},
        'issue_counts': {},
        'issues': [],
        'per_frame': [],
        'error': None,
    }
    try:
        import cv2

        np = _np()
        fps = _clip_fps(clip_path)
        # Per-face TRACKS. Everything clip-level (drift, jitter, melt) has to be
        # measured on one continuous subject: a "largest face per frame" series
        # silently alternates between the two actors and between a real face and
        # a spurious hair blob, which on scene20_v7 produced a jitter p95 of
        # 15.8 inter-ocular units — an identity switch reported as facial motion.
        tracks = []  # {'id','ratios':{k:{sample:v}},'last':i,'c':xy,'w':px,'hits':n,'samples':set}
        warps = {}  # sample_i -> 2x3 warp from previous sample
        prev_small = None
        sample_i = -1
        for idx, frame in _iter_frames(clip_path, sample_every, max_frames):
            sample_i += 1
            r = _faces_from_array(frame, expected)
            out['frames_sampled'] += 1
            if r['detected']:
                out['frames_with_faces'] += 1

            small = cv2.cvtColor(cv2.resize(frame, (0, 0), fx=0.35, fy=0.35), cv2.COLOR_BGR2GRAY)
            if prev_small is not None:
                warp = np.eye(2, 3, dtype=np.float32)
                try:
                    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, 1e-4)
                    cv2.findTransformECC(prev_small, small, warp, cv2.MOTION_EUCLIDEAN, crit, None, 5)
                    warp[0, 2] /= 0.35
                    warp[1, 2] /= 0.35
                    warps[sample_i] = warp
                except Exception as _exc:
                    _zyg_log.debug('ECC motion estimate skipped for sample %s: %s', sample_i, _exc)
            prev_small = small

            # greedy association, biggest face first, scale-relative tolerance
            taken = set()
            for f in sorted(r['faces'], key=lambda a: -(a.get('face_width_px') or 0.0)):
                c = np.asarray(f['centroid'], dtype=float)
                fw = float(f.get('face_width_px') or 0.0) or NOISE_FACE_PX
                best, bd = None, None
                for t in tracks:
                    if t['id'] in taken or t['last'] == sample_i:
                        continue
                    d = float(np.linalg.norm(c - t['c']))
                    if d <= FACE_TRACK_FRAC * max(fw, t['w']) and (bd is None or d < bd):
                        bd, best = d, t
                if best is None:
                    best = {
                        'id': len(tracks),
                        'ratios': {},
                        'last': -1,
                        'c': c,
                        'w': fw,
                        'hits': 0,
                        'strong_hits': 0,
                        'centroids': {},
                        'inter': {},
                        'yaws': {},
                        'samples': set(),
                    }
                    tracks.append(best)
                taken.add(best['id'])
                best['last'] = sample_i
                best['c'] = c
                best['w'] = fw
                best['hits'] += 1
                best['strong_hits'] += 1 if f.get('strong') else 0
                best['samples'].add(sample_i)
                best['centroids'][sample_i] = c
                best['inter'][sample_i] = f.get('inter_ocular_px') or 0.0
                best['yaws'][sample_i] = f.get('yaw_proxy')
                for key in ('interocular_ratio', 'mouth_ratio', 'eye_mouth_ratio'):
                    if f.get(key) is not None:
                        best['ratios'].setdefault(key, {})[sample_i] = f[key]

            for i in r['issues']:
                rec = dict(i)
                rec['frame'] = idx
                out['issues'].append(rec)
            out['per_frame'].append(
                {
                    'frame': idx,
                    't_s': round(idx / fps, 3) if fps else None,
                    'ok': r['ok'],
                    'detected': r['detected'],
                    'strong': r['strong'],
                    'tags': sorted({i['tag'] for i in r['issues']}),
                }
            )

        n_samples = out['frames_sampled']
        if n_samples:
            out['detect_rate'] = round(out['frames_with_faces'] / n_samples, 4)

        # Only tracks that actually established themselves get gated; a
        # two-frame blob is noise, not a character.
        min_hits = _envi('ZYG_MP_TRACK_MIN_HITS', 5)
        live = [t for t in tracks if t['hits'] >= min_hits]
        out['tracks'] = [
            {
                'id': t['id'],
                'hits': t['hits'],
                'strong_hits': t['strong_hits'],
                'first_sample': min(t['samples']),
                'last_sample': max(t['samples']),
            }
            for t in tracks
        ]

        # --- melt: an ESTABLISHED face that goes missing for a run of samples.
        # A dropout is only HARD evidence when the detector is otherwise
        # reliable on this clip and the track was confidently detected at least
        # once; on Arcane-stylized footage the same pattern is plain recall
        # failure, and calling that a melt would be a false-positive machine.
        melt_min_hits = _envi('ZYG_MP_MELT_MIN_HITS', 8)
        reliable = (out['detect_rate'] or 0.0) >= DETECT_RATE_FLOOR
        for t in live:
            ss = sorted(t['samples'])
            gaps, run, start = [], 0, None
            for s in range(ss[0], n_samples):
                if s in t['samples']:
                    if run >= MELT_RUN:
                        gaps.append((start, run))
                    run, start = 0, None
                else:
                    if run == 0:
                        start = s
                    run += 1
            if run >= MELT_RUN:
                gaps.append((start, run))
            base = reliable and t['hits'] >= melt_min_hits and t['strong_hits'] > 0
            for start, run in gaps:
                # Pose veto: MediaPipe's face detector loses a head well before
                # full profile, so a dropout right after the subject turned away
                # is recall, not melt. Verified on scene20_v7: Cornelis's track
                # drops out twice while his face is intact but in profile
                # (yaw proxy 0.5-0.67) — reported, never gated.
                prior = [s for s in t['samples'] if s < start]
                yaw = t['yaws'].get(max(prior)) if prior else None
                frontal_before = yaw is not None and abs(yaw) <= YAW_FRONTAL
                sev = 'hard' if (base and frontal_before) else 'advisory'
                note = (
                    ''
                    if sev == 'hard'
                    else f' (advisory: last pose yaw={yaw} — profile/unreliable detection, not proof of melt)'
                )
                out['melt_runs'].append(
                    {'track': t['id'], 'start_sample': start, 'length': run, 'severity': sev, 'yaw_before': yaw}
                )
                out['issues'].append(
                    {
                        'tag': 'face-detection-collapse',
                        'frame': None,
                        'severity': sev,
                        'text': f'face track #{t["id"]} (established over {t["hits"]} '
                        f'samples, {t["strong_hits"]} strong) vanished for '
                        f'{run} consecutive samples from #{start} — melt '
                        f'event{note}',
                    }
                )

        # --- ratio drift, per track. A MAD z-score off five points is a
        # coin flip; short tracks are measured and reported but never gated.
        drift_min_n = _envi('ZYG_MP_DRIFT_MIN_N', 8)
        for t in live:
            for key, by_sample in t['ratios'].items():
                vals = [by_sample[s] for s in sorted(by_sample)]
                med, mad, zs = _robust_z(vals)
                slot = out['ratio_drift'].setdefault(key, {})
                worst = max(zs) if zs else 0.0
                slot[f'track{t["id"]}'] = {
                    'median': round(med, 4),
                    'mad': round(mad, 5),
                    'n': len(vals),
                    'max_z': round(worst, 2),
                }
                if worst > RATIO_Z and mad > 1e-6 and len(vals) >= drift_min_n:
                    k = int(max(range(len(zs)), key=lambda i: zs[i]))
                    where = sorted(by_sample)[k]
                    out['issues'].append(
                        {
                            'tag': f'{key.replace("_", "-")}-drift',
                            'frame': where,
                            'severity': 'hard',
                            'text': f'track #{t["id"]} {key} z={worst:.1f} at sample '
                            f'#{where} (median {med:.3f}, n={len(vals)})',
                        }
                    )

        # --- ECC-compensated jitter, per track, consecutive samples only
        jitters, jitter_at = [], []
        for t in live:
            for s in sorted(t['samples']):
                if (s - 1) not in t['samples'] or s not in warps:
                    continue
                inter = t['inter'].get(s - 1) or 0.0
                if inter <= 1e-6:
                    continue
                w = warps[s]
                p = t['centroids'][s - 1]
                pv = np.asarray([p[0], p[1], 1.0])
                pred = np.asarray([float(w[0] @ pv), float(w[1] @ pv)])
                jit = float(np.linalg.norm(t['centroids'][s] - pred)) / inter
                if jit > JITTER_MAX:
                    continue  # association slip, not facial motion
                jitters.append(jit)
                jitter_at.append((s, t['id']))
        if jitters:
            arr = np.asarray(jitters, dtype=float)
            out['jitter_median'] = round(float(np.median(arr)), 4)
            out['jitter_p95'] = round(float(np.percentile(arr, 95)), 4)
            _, jmad, jz = _robust_z(jitters)
            worst = max(jz) if jz else 0.0
            k = int(max(range(len(jz)), key=lambda i: jz[i])) if jz else 0
            where, wtrack = jitter_at[k] if jitter_at else (None, None)
            if worst > JITTER_Z and out['jitter_p95'] > JITTER_FLOOR:
                out['issues'].append(
                    {
                        'tag': 'landmark-jitter',
                        'frame': where,
                        'severity': 'hard',
                        'text': f'ECC-compensated face jitter spike z={worst:.1f} on '
                        f'track #{wtrack} at sample #{where} '
                        f'(p95 {out["jitter_p95"]:.3f} of inter-ocular, '
                        f'n={len(jitters)})',
                    }
                )

        counts = {}
        for i in out['issues']:
            counts[i['tag']] = counts.get(i['tag'], 0) + 1
        out['issue_counts'] = counts
        sev = {i['severity'] for i in out['issues']}
        if 'hard' in sev:
            out['ok'] = False
        elif out['frames_sampled'] == 0:
            out['ok'] = None
        elif expected and (out['detect_rate'] or 0.0) < DETECT_RATE_FLOOR:
            out['ok'] = None
            out['issues'].append(
                {
                    'tag': 'face-detect-rate-low',
                    'frame': None,
                    'severity': 'unknown',
                    'text': f'faces found in only {out["detect_rate"]:.0%} of sampled '
                    f'frames — UNKNOWN (stylized art or a real dropout)',
                }
            )
        else:
            out['ok'] = None if 'unknown' in sev else True
    except Exception as exc:
        out['error'] = f'{type(exc).__name__}: {exc}'
        out['ok'] = None
        log(f'anatomy_qc: face clip gate unavailable ({out["error"]})')
    _ledger_gate(
        'anatomy.face.clip',
        out['ok'],
        score=out['detect_rate'],
        tag=','.join(sorted(out['issue_counts'])[:6]),
        run_id=run_id,
    )
    log(
        f'anatomy_qc: face clip ok={out["ok"]} sampled={out["frames_sampled"]} '
        f'detect_rate={out["detect_rate"]} jitter_p95={out["jitter_p95"]} '
        f'tags={out["issue_counts"]}'
    )
    return out
