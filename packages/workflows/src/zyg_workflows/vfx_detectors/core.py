# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import math

from zyg_workflows.vfx_detectors.taxonomy import (
    BINDINGS,
    bind,
)

_EPS = 1e-8

# ── default thresholds — every one of these is meant to be re-tuned ──────────
# The values are honest starting points, not calibrated constants. Nothing here
# has been fitted against ground truth yet; the run report prints the best score
# each detector saw so these can be moved with evidence.
THRESHOLDS = {
    # editing / temporal
    'cut_hist_corr': 0.55,
    'flash_luma_z': 3.0,
    'fade_luma': 12.0,
    'held_cel_min': 3,
    # anime 2D
    'impact_luma_z': 2.5,
    'impact_max_frames': 3,
    'speedline_edge_density': 0.14,
    'speedline_orient_peak': 0.30,
    # camera
    'cam_pan_norm': 0.004,
    'cam_zoom_delta': 0.004,
    'cam_roll_deg': 0.35,
    'shake_std': 2.5,
    'static_max_motion': 0.35,
    # post fx
    'bloom_lift': 0.035,
    'ca_px': 0.7,
    'vignette': 0.12,
    'grain_sigma': 1.6,
    'halation': 0.02,
    # lighting
    'lowkey_p50': 60.0,
    'highkey_p50': 185.0,
    'silhouette_bimodal': 0.55,
    'flicker_std': 4.0,
    # natural
    'cloud_flow_min': 0.25,
    'cloud_flow_max': 3.0,
    'cloud_coherence': 0.45,
    'water_curl_var': 0.35,
    'water_incoherence': 0.55,
    'boil_churn': 0.55,
    'boil_net_ratio': 0.30,
    'fire_hue_frac': 0.05,
    'fire_flicker_std': 6.0,
    # face
    'blink_ear': 0.20,
    'blink_bs': 0.45,
    'blink_max_frames': 8,
    'mouth_open_mar': 0.28,
    'lip_move_var': 0.0035,
    'head_turn_deg_per_s': 45.0,
    # body (units: torso-lengths per second, degrees per second)
    'kick_ankle_v': 5.0,
    'kick_knee_extend': 220.0,
    'punch_wrist_v': 6.0,
    'punch_elbow_extend': 260.0,
    'slap_wrist_v': 5.0,
    'jump_com_v': 2.2,
    'crouch_stance': 1.25,
    'gait_alternation': 0.35,
    'fall_com_v': 3.0,
    # hands
    'pinch_aperture': 0.45,
    'hand_mouth_dist': 0.45,
    'point_extension': 0.95,
    'contact_dist': 0.20,
    # interaction
    'proximity_torsos': 2.0,
    # curiosity
    'unknown_min_area': 0.004,
    'unknown_max_area': 0.45,
    'unknown_min_frames': 3,
    'unknown_claim_iou': 0.18,
    'banding_score': 0.55,
}

_REGISTRY = {}


class Ctx:
    """Everything one run measured, handed to every detector."""

    def __init__(
        self,
        run_dir,
        frame_dir,
        names,
        fps,
        frame_metrics,
        pair_metrics,
        unique_idx,
        cadence,
        shots,
        landmarks,
        velocities,
        thresholds,
        log,
        start_s=0.0,
    ):
        self.run_dir = run_dir
        self.frame_dir = frame_dir
        self.names = names
        self.fps = float(fps or 24.0)
        self.fm = frame_metrics
        self.pm = pair_metrics  # {to_frame: pair dict}
        self.uidx = unique_idx
        self.cadence = cadence
        self.shots = shots
        self.lm = landmarks or []
        self.vel = velocities or []
        self.log = log
        self.start_s = float(start_s)
        self.T = dict(THRESHOLDS)
        self.T.update({k: v for k, v in (thresholds or {}).items() if k in THRESHOLDS})
        self.n = len(frame_metrics)

    # -- convenience ---------------------------------------------------------

    def t_of(self, i):
        return round(self.start_s + i / self.fps, 4)

    def series(self, key, default=0.0):
        """A per-frame metric as a list."""
        return [float(f.get(key, default) or 0.0) for f in self.fm]

    def pair_series(self, key, default=0.0):
        """A per-pair metric, indexed by the pair's TO frame. Returns
        (frames, values) over unique-cel pairs only."""
        fr, val = [], []
        for b in sorted(self.pm):
            fr.append(b)
            val.append(float(self.pm[b].get(key, default) or 0.0))
        return fr, val

    def has_pose(self):
        return any((f.get('pose') or {}).get('state') == 'found' for f in self.lm)

    def has_face(self):
        return any((f.get('face') or {}).get('state') == 'found' for f in self.lm)

    def has_hand(self):
        return any((f.get('hand') or {}).get('state') == 'found' for f in self.lm)

    def pose_at(self, i):
        blk = (self.lm[i] if 0 <= i < len(self.lm) else {}).get('pose') or {}
        items = blk.get('items') or []
        return items[0] if items and blk.get('state') in ('found', 'weak') else None

    def faces_at(self, i):
        blk = (self.lm[i] if 0 <= i < len(self.lm) else {}).get('face') or {}
        return (blk.get('items') or []) if blk.get('state') in ('found', 'weak') else []

    def hands_at(self, i):
        blk = (self.lm[i] if 0 <= i < len(self.lm) else {}).get('hand') or {}
        return (blk.get('items') or []) if blk.get('state') in ('found', 'weak') else []

    def vel_at(self, frame):
        for v in self.vel:
            if v.get('frame') == frame:
                return v
        return {}


def _mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _median(xs):
    xs = sorted(x for x in xs if isinstance(x, (int, float)))
    if not xs:
        return 0.0
    k = len(xs) // 2
    return xs[k] if len(xs) % 2 else 0.5 * (xs[k - 1] + xs[k])


def _zscores(xs):
    m, s = _mean(xs), _std(xs)
    if s < _EPS:
        return [0.0] * len(xs)
    return [(x - m) / s for x in xs]


def detector(tid, unit='', threshold_key=None, needs=(), note=''):
    """Register one detector against a taxonomy id.

    needs: any of 'pairs', 'pose', 'face', 'hand'. An unmet need returns
    UNMEASURABLE — never a negative finding."""

    def wrap(fn):
        _REGISTRY[tid] = {
            'fn': fn,
            'unit': unit,
            'threshold_key': threshold_key,
            'needs': tuple(needs),
            'note': note,
            'id': tid,
        }
        return fn

    return wrap


def registry():
    return dict(_REGISTRY)


def _result(tid, meta, events=None, best=None, reason=None, ctx=None, extra=None):
    thr = None
    if meta.get('threshold_key') and ctx is not None:
        thr = ctx.T.get(meta['threshold_key'])
    r = {
        'id': tid,
        'state': 'unmeasurable' if reason else 'ok',
        'events': list(events or []),
        'best': best,
        'threshold': thr,
        'unit': meta.get('unit', ''),
        'note': meta.get('note', ''),
    }
    if reason:
        r['reason'] = reason
    if extra:
        r.update(extra)
    return r


def _ev(tid, frame, ctx, conf, **evidence):
    return {
        'id': tid,
        'frame': int(frame),
        't_s': ctx.t_of(frame),
        'confidence': round(float(conf), 4),
        'evidence': evidence,
    }


def run_all(ctx):
    """Run every registered detector. One failing detector must never take the
    run down — it reports UNMEASURABLE with the exception text."""
    out = []
    unmet = {'pairs': not ctx.pm, 'pose': not ctx.has_pose(), 'face': not ctx.has_face(), 'hand': not ctx.has_hand()}
    reasons = {
        'pairs': 'no unique-cel pairs — the window is a single held frame',
        'pose': 'no body pose resolved in this window (MediaPipe is photoreal-trained; '
        'stylised art commonly yields none) — absence of pose is NOT absence of action',
        'face': 'no face resolved in this window — see the pose note; a drawn face '
        'often fails the photoreal face detector entirely',
        'hand': 'no hand resolved in this window',
    }
    for tid, meta in sorted(_REGISTRY.items()):
        blocked = next((n for n in meta['needs'] if unmet.get(n)), None)
        if blocked:
            for bid, _bev, _d in bind(tid, []):
                out.append(_result(bid, meta, reason=reasons[blocked], ctx=ctx))
            continue
        try:
            r = meta['fn'](ctx)
            events, best, extra = (r + (None,))[:3] if isinstance(r, tuple) else (r, None, None)
            for bid, bev, disc in bind(tid, events or []):
                ex = dict(extra or {})
                ex['from_detector'] = tid
                if not disc:
                    ex['discriminated'] = False
                    ex['undiscriminated_note'] = (
                        f'{tid} cannot tell this entry apart from the others it is bound '
                        f'to ({", ".join(BINDINGS.get(tid, ()))}); the evidence is for the '
                        f'family, not for this specific member'
                    )
                out.append(_result(bid, meta, events=bev, best=best, ctx=ctx, extra=ex))
        except Exception as e:  # noqa: BLE001
            for bid, _bev, _d in bind(tid, []):
                out.append(_result(bid, meta, reason=f'detector raised {type(e).__name__}: {e}', ctx=ctx))
            ctx.log(f'  detector {tid} raised {type(e).__name__}: {e}')
    return out
